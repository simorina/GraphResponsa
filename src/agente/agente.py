"""
L'agente, costruito con LangChain 1.x.

`create_agent` e' l'interfaccia corrente: in LangGraph 1.0 `create_react_agent`
di langgraph.prebuilt e' deprecato in suo favore.

Espone `rispondi()`, un generatore che emette eventi mentre l'agente lavora -
strumenti chiamati, testo, fonti - cosi' la UI puo' mostrare il processo invece
di una barra di caricamento.

La conversazione non viaggia piu' avanti e indietro col browser: la tiene il
checkpointer, e il client manda solo un identificativo di conversazione.
"""

import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from .strumenti import STRUMENTI

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

MODELLO = "claude-haiku-4-5"
MAX_GIRI = 12   # Ogni chiamata a uno strumento consuma DUE passi del grafo
                # (nodo modello + nodo strumenti), quindi il tetto vero e'
                # circa MAX_GIRI-1 chiamate. Con 8 si fermava a sette, e le
                # regole su riformulazione e vigenza portano regolarmente a
                # sette-nove: misurato, 2 consultazioni su 6 morivano di
                # GraphRecursionError invece di rispondere. Un'interruzione
                # costa all'utente tutto, un giro in piu' costa mezzo
                # centesimo.
SEPARATORE = "\n\n"

# Prezzi per milione di token, per la stima mostrata nella UI.
PREZZI = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
}

ISTRUZIONI = """Sei un assistente esperto della normativa della Repubblica di San Marino.
Rispondi consultando esclusivamente il grafo della normativa attraverso gli strumenti a disposizione.

## Regole non negoziabili

1. **Cerca sempre, prima di rispondere qualsiasi cosa.**
   Non chiedere mai all'utente di precisare la norma, l'anno o il riferimento
   prima di aver cercato. Una domanda vaga si affronta cercando, non
   rimandandola al mittente: prendi l'interpretazione piu' probabile, cerca,
   e con i risultati in mano esponi cosa hai trovato e come restringere.
   Una risposta che chiede chiarimenti senza aver invocato uno strumento e'
   sempre sbagliata, anche quando la domanda e' davvero ambigua.

   Vale in particolare quando la domanda dice "questa legge", "questa norma",
   "il presente decreto" senza che nulla, prima, l'abbia indicata: non e' una
   domanda a cui manchi il soggetto, e' una domanda il cui soggetto va
   ritrovato. Cerca la materia di cui parla - i benefici per i minori, le
   societa' tra professionisti, i rendiconti approvati - e sara' la ricerca a
   dirti di quale atto si tratta. Solo se dopo aver cercato restano piu'
   candidati incompatibili puoi esporli e chiedere quale interessa.

2. **Ogni affermazione va ancorata a una fonte.** Cita sempre norma, articolo e
   comma nella forma "L. 87/2026, art. 7, comma 2". Non affermare nulla che non
   provenga dal risultato di uno strumento.

3. **Se non trovi, dillo.** Se gli strumenti non restituiscono nulla di
   pertinente, dichiara che l'archivio non contiene la risposta. Non colmare il
   vuoto con conoscenza generale sul diritto italiano o di altri ordinamenti:
   San Marino ha un ordinamento proprio e una risposta plausibile ma inventata
   e' il danno peggiore.

4. **Distingui cosa c'e' da cosa e' solo citato.** L'archivio contiene il testo
   completo di alcune norme; altre compaiono solo perche' citate
   (`testoDisponibile: false`). Se una norma rilevante non ha il testo, dillo:
   "la L. 59/1974 e' richiamata ma il suo testo non e' in archivio".

5. **Principio di vigenza.** L'utente intende la disciplina in vigore oggi.
   Quando trovi una norma di qualche anno fa su una materia ancora attuale,
   controlla se e' stata novellata - con `chi_cita`, o con `cerca_testo` e
   `dal_anno` impostato a qualche anno prima di oggi. Esponi in primo piano la
   disciplina vigente, e se il dato e' cambiato dillo: "il compenso e' ora di X
   (L. .../2023); era di Y fino al ...".
   **Il campo `citatoDaAttiSuccessivi` non e' un suggerimento, e' un obbligo.**
   Se il passo che stai per citare lo porta, un atto posteriore lo ha citato -
   e qui citare un articolo significa quasi sempre modificarlo. Apri quell'atto
   con leggi_articolo() prima di rispondere, e riporta la versione vigente
   dicendo cosa e' cambiato. Rispondere con il testo marcato senza averlo
   aperto e' un errore, anche quando il testo sembra completo e sensato:
   sembrera' sempre completo e sensato, e sara' scaduto.

   Il campo `ancheIn` dei risultati e' il segnale piu' economico che hai: se il
   passo che stai per citare ricorre identico anche in atti piu' recenti, la
   versione da esporre e' quella dell'atto piu' recente, e ti costa zero giri
   accorgertene. Succede di continuo con i tariffari e le tabelle di sanzioni,
   riemessi ogni anno.
   Non fare questa verifica quando la domanda riguarda un fatto storico o un
   atto gia' esaurito: costa giri di ricerca e non aggiunge nulla.

## Metodo

Parti quasi sempre da `cerca_testo` con parole del linguaggio normativo.

**Se la prima ricerca rende poco, riformula prima di arrenderti.** Chi scrive
dice "vacanza studio", la norma dice "soggiorno culturale"; chi scrive dice
"quanto tempo ho", la norma dice "termine perentorio". Una seconda ricerca con
il lessico giuridico e' quasi sempre piu' fruttuosa della prima. Solo dopo due
formulazioni diverse senza esito puoi concludere che la materia non c'e'.

Se un risultato riporta `troncato: true`, il testo che vedi e' tagliato: chiama
`leggi_articolo` prima di citarlo, o rischi di perdere proprio il dato che
serve. Fallo comunque quando un articolo si rivela centrale.

**Per domande sulla struttura di una norma** - quanti articoli ha, com'e'
organizzata, di cosa tratta l'articolo N - usa `struttura_norma`, che risponde
in una sola chiamata. Non leggere mai gli articoli uno per uno per contarli.

Per presupposti e rinvii usa `citazioni_da`; per l'impatto di una norma usa
`chi_cita`. Se l'utente chiede cosa contiene la banca dati, usa `elenco_norme`.

Puoi chiamare piu' strumenti in parallelo quando le richieste sono indipendenti.

## Cosa l'archivio contiene, e cosa no

L'archivio raccoglie le **disposizioni** normative, non le **procedure**
amministrative. A chi chiede come si compila un modulo, a quale sportello si
presenta un'istanza o quali documenti pretenda l'ufficio, puoi rispondere solo
con cio' che la norma prescrive - i requisiti, i termini, l'organo competente -
e devi dire chiaramente che la prassi non e' in archivio. Non dedurre i passi
pratici dalla disposizione: sembrerebbero istruzioni operative e non lo sono.

## Quanto sei sicuro

Se sei arrivato alla risposta con una o due ricerche e la fonte e' esplicita,
esponila senza esitazioni.

Se ci sei arrivato dopo molti tentativi, o se il passo che citi risponde solo
di sbieco alla domanda, **dillo**: "e' quanto di piu' pertinente l'archivio
contiene, ma non disciplina espressamente il tuo caso". Una risposta incerta
presentata con la sicurezza di una certa e' un danno, perche' chi legge non ha
modo di accorgersene.

## Chi hai davanti

Ti consultano due tipi di persone, spesso senza dirti quale sono.

Il **professionista** conosce il lessico e vuole l'appiglio esatto: gli servono
gli estremi, il comma preciso, la formulazione letterale da riportare in un
atto. Non semplificare per lui, e non parafrasare dove la lettera conta.

L'**impiegato allo sportello o il cittadino** pone la domanda in lingua
corrente - "bonus prima casa chi ha accesso?", "quanto pago la multa?" - e ha
bisogno della risposta prima della citazione. Apri con il dato che gli serve,
in parole sue, e metti gli estremi subito dopo: servono a lui per verificare e
a te per non essere creduto sulla parola.

Non scegliere fra i due registri: rispondi in modo che il primo trovi la
precisione e il secondo capisca comunque. Il modo di scriverlo e' cominciare
dal fatto e non dalla norma - "hai trenta giorni, e sono perentori (L. 28/1991,
art. 30)" invece di "l'articolo 30 della L. 28/1991 dispone che...".

## Forma della risposta

**Scrivi sempre e solo in italiano**, comprese le brevi frasi che precedono una
chiamata agli strumenti: l'utente le vede in tempo reale.

Rispondi in modo diretto e sostanziale. Apri con la risposta, non con un
preambolo sul metodo. Cita le fonti nel corpo del testo, dove servono. Riporta
il testo normativo tra virgolette quando la formulazione esatta conta.
"""

def _checkpointer():
    """
    Dove vivono le conversazioni.

    In produzione su DynamoDB, non su Aura. Aura tiene la normativa: metterci
    anche le chat significherebbe che `03_load.py --reset`, che esegue
    `MATCH (n) DETACH DELETE n`, cancella le conversazioni di tutti a ogni
    ricarico del grafo.

    Su DynamoDB i container diventano senza stato, ed e' la ragione per cui si
    puo' alzare il numero di task senza che un messaggio di seguito atterri su
    un'istanza che non sa di cosa si sta parlando.

    Senza le variabili delle tabelle si torna alla memoria di processo, cosi'
    `python src/server.py` continua a funzionare in locale senza AWS.
    """
    checkpoint = os.environ.get("TABELLA_CHECKPOINT")
    scritture = os.environ.get("TABELLA_SCRITTURE")
    if not (checkpoint and scritture):
        return InMemorySaver()

    from langgraph_checkpoint_dynamodb.saver import DynamoDBSaver
    return DynamoDBSaver(
        client_config={"region_name": os.environ.get("REGIONE", "eu-central-1")},
        checkpoints_table_name=checkpoint,
        writes_table_name=scritture,
    )


_memoria = None
_agente = None


def agente():
    global _agente, _memoria
    if _agente is None:
        _memoria = _checkpointer()
        modello = ChatAnthropic(
            model=MODELLO,
            max_tokens=16000,
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )

        # --- Prompt caching ---
        #
        # Il prefisso - istruzioni piu' gli schemi dei sette strumenti - e'
        # identico a ogni giro del ciclo ReAct e pesa 5.613 token, misurati con
        # l'API di conteggio. Su una consultazione da tre giri sono 16.839
        # token rispediti uguali: il 64% dell'ingresso totale.
        #
        # Due cose andavano capite, e su entrambe mi ero sbagliato prima.
        #
        # 1. `cache_control` non e' un parametro, e' un MARCATORE SU UN BLOCCO
        #    di contenuto. I tentativi con `modello.bind(cache_control=...)` e
        #    con `model_kwargs` fallivano per questo. Avevo scritto che era
        #    `bind_tools()` a scartarlo: falso, verificato: con bind_tools il
        #    marcatore viene onorato (8.875 token riletti in prova diretta).
        #
        # 2. Haiku 4.5 non mette in cache prefissi sotto i 4.096 token, e non
        #    lo segnala: ignora il marcatore in silenzio. Era questo, e solo
        #    questo, a tenere la cache spenta. Il prefisso reale misurato sul
        #    filo stava a ~3.990 token, un centinaio sotto la soglia.
        #
        # Il marcatore in coda al prompt di sistema mette in cache tutto cio'
        # che lo precede nella richiesta - gli schemi degli strumenti stanno
        # prima del system - quindi un solo punto di rottura copre l'intero
        # prefisso.
        istruzioni = SystemMessage(content=[{
            "type": "text",
            "text": ISTRUZIONI,
            "cache_control": {"type": "ephemeral"},
        }])

        _agente = create_agent(
            model=modello,
            tools=STRUMENTI,
            system_prompt=istruzioni,
            checkpointer=_memoria,
        )
    return _agente


def nuova_conversazione() -> str:
    return str(uuid.uuid4())


def _fonti_da(nome_strumento, risultato):
    """Estrae dai risultati i riferimenti da mostrare come fonti nella UI."""
    fonti = []
    if not isinstance(risultato, dict):
        return fonti
    if nome_strumento == "cerca_testo":
        for r in risultato.get("risultati", []):
            fonti.append({
                "norma": r.get("normaId"), "titoloNorma": r.get("normaTitolo"),
                "articolo": r.get("articolo"), "rubrica": r.get("rubrica"),
                "comma": r.get("comma"), "testo": r.get("testo"),
            })
    elif nome_strumento == "leggi_articolo" and "articolo" in risultato:
        for c in risultato.get("commi", []):
            if c.get("numero"):
                fonti.append({
                    "norma": risultato.get("normaId"),
                    "titoloNorma": risultato.get("normaTitolo"),
                    "articolo": risultato.get("articolo"),
                    "rubrica": risultato.get("rubrica"),
                    "comma": c.get("numero"), "testo": c.get("testo"),
                })
    return fonti


def _quante(risultato):
    if not isinstance(risultato, dict):
        return 0
    for chiave in ("risultati", "norme", "dipendenze", "citataDa", "articoli", "commi"):
        if isinstance(risultato.get(chiave), list):
            return len(risultato[chiave])
    return 0


def _testo_di(messaggio):
    """Il testo di un AIMessage, che il contenuto sia una stringa o blocchi.

    Nella forma a blocchi interessa solo `type == "text"`: gli altri blocchi
    sono gli argomenti degli strumenti, che non vanno nella risposta.
    """
    contenuto = getattr(messaggio, "content", None)
    if isinstance(contenuto, str):
        return contenuto.strip()
    if isinstance(contenuto, list):
        return "".join(b.get("text", "") for b in contenuto
                       if isinstance(b, dict) and b.get("type") == "text").strip()
    return ""


def rispondi(domanda, conversazione=None):
    """
    Genera eventi: {"tipo": ..., ...}

      testo       la risposta, in un unico evento a fine ciclo
      strumento   lo strumento sta per essere eseguito
      risultato   lo strumento ha risposto
      fonti       i commi consultati, per il pannello delle fonti
      fine        uso dei token, costo stimato, id conversazione
      errore      qualcosa e' andato storto
    """
    conversazione = conversazione or nuova_conversazione()
    config = {"configurable": {"thread_id": conversazione},
              "recursion_limit": MAX_GIRI * 2}

    fonti_raccolte, viste = [], set()
    token_in = token_out = 0
    token_letti = token_scritti = 0
    # I nomi arrivano con l'AIMessage, i risultati dopo col ToolMessage:
    # questa mappa li ricongiunge per id di chiamata.
    nomi_per_id = {}
    # I blocchi di testo che il modello scrive lungo il ciclo - le frasi di
    # servizio prima di uno strumento e la risposta finale - si accumulano qui
    # e partono insieme. Il modello riprende a scrivere dopo gli strumenti:
    # senza uno stacco la frase nuova si salderebbe alla precedente.
    blocchi_testo = []

    try:
        # `_modo` non serve piu' - resta perche' stream() con una lista di
        # modi restituisce comunque coppie (modo, pezzo).
        for _modo, pezzo in agente().stream(
            {"messages": [{"role": "user", "content": domanda}]},
            config=config,
            # Solo "updates": il modo "messages" serviva a emettere il testo
            # frammento per frammento, e la risposta non si consegna piu' cosi'.
            # Gli eventi degli strumenti restano in diretta - misurate, le
            # consultazioni durano 8 secondi mediani e 22 al massimo, e tanto
            # silenzio si legge come un blocco - ma il testo arriva intero,
            # cosi' il Markdown viene reso una volta sola, gia' completo: una
            # tabella o un blocco di codice non passano piu' per gli stati
            # intermedi in cui la sintassi e' ancora a meta'.
            stream_mode=["updates"],
        ):
            for _nodo, stato in pezzo.items():
                if not isinstance(stato, dict):
                    continue
                for messaggio in stato.get("messages", []) or []:
                    uso = getattr(messaggio, "usage_metadata", None)
                    if uso:
                        # `input_tokens` comprende i token riletti dalla cache,
                        # che pero' costano un decimo, e quelli scritti, che
                        # costano un quarto in piu'. Sommarli al prezzo pieno
                        # gonfierebbe il costo mostrato all'utente e quello
                        # registrato sui consumi.
                        d = uso.get("input_token_details") or {}
                        letti = d.get("cache_read", 0)
                        scritti = d.get("cache_creation", 0)
                        token_in += uso.get("input_tokens", 0)
                        token_letti += letti
                        token_scritti += scritti
                        token_out += uso.get("output_tokens", 0)

                    if type(messaggio).__name__ == "AIMessage":
                        scritto = _testo_di(messaggio)
                        if scritto:
                            blocchi_testo.append(scritto)

                    for chiamata in getattr(messaggio, "tool_calls", None) or []:
                        nomi_per_id[chiamata["id"]] = chiamata["name"]
                        yield {"tipo": "strumento", "nome": chiamata["name"],
                               "argomenti": chiamata["args"]}

                    if type(messaggio).__name__ == "ToolMessage":
                        nome = nomi_per_id.get(getattr(messaggio, "tool_call_id", None),
                                               getattr(messaggio, "name", "?"))
                        esito = messaggio.content
                        if isinstance(esito, str):
                            try:
                                esito = json.loads(esito)
                            except (ValueError, TypeError):
                                pass
                        for f in _fonti_da(nome, esito):
                            chiave = (f["norma"], f["articolo"], f["comma"])
                            if chiave not in viste:
                                viste.add(chiave)
                                fonti_raccolte.append(f)
                        yield {"tipo": "risultato", "nome": nome,
                               "quante": _quante(esito),
                               "errore": esito.get("errore") if isinstance(esito, dict) else None}

    except Exception as e:
        yield {"tipo": "errore", "messaggio": f"{type(e).__name__}: {e}"}
        return

    if blocchi_testo:
        yield {"tipo": "testo", "testo": SEPARATORE.join(blocchi_testo)}

    if fonti_raccolte:
        yield {"tipo": "fonti", "fonti": fonti_raccolte}

    prezzo_in, prezzo_out = PREZZI.get(MODELLO, (5.0, 25.0))
    # Scrivere in cache costa 1,25 volte; rileggere 0,10.
    pieni = token_in - token_letti - token_scritti
    costo = (pieni + token_scritti * 1.25 + token_letti * 0.10) / 1e6 * prezzo_in         + token_out / 1e6 * prezzo_out
    yield {"tipo": "fine", "tokenIn": token_in, "tokenOut": token_out,
           "tokenDaCache": token_letti,
           "costo": round(costo, 4),
           "conversazione": conversazione}
