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
from langgraph.checkpoint.memory import InMemorySaver

from .strumenti import STRUMENTI

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

MODELLO = "claude-haiku-4-5"
MAX_GIRI = 8
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

   Subito dopo la citazione in prosa, aggiungi anche un marcatore macchina
   nella forma `{{cita:normaId:articolo:comma}}`, usando esattamente gli
   identificativi `normaId`, `articolo` e `comma` come li hai ricevuti dallo
   strumento - l'id interno (es. `L-87-2026`), non come li scrivi in prosa
   (es. "L. 87/2026"). Se la citazione riguarda l'intero articolo senza un
   comma preciso, scrivi `-` al posto del comma. Il marcatore non e' visibile
   a chi legge: diventa un riferimento cliccabile sulla fonte esatta. Uno per
   ogni citazione, subito dopo, mai su un dato che non hai letto da uno
   strumento.

   Esempio: "...come previsto dalla L. 87/2026, art. 7, comma
   2{{cita:L-87-2026:7:2}}, che stabilisce..."

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

## Quanto sei sicuro

Se sei arrivato alla risposta con una o due ricerche e la fonte e' esplicita,
esponila senza esitazioni.

Se ci sei arrivato dopo molti tentativi, o se il passo che citi risponde solo
di sbieco alla domanda, **dillo**: "e' quanto di piu' pertinente l'archivio
contiene, ma non disciplina espressamente il tuo caso". Una risposta incerta
presentata con la sicurezza di una certa e' un danno, perche' chi legge non ha
modo di accorgersene.

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

        # Il prompt caching qui NON si puo' attivare, ed e' stato misurato:
        #
        #   - `modello.bind(cache_control=...)`  -> `bind_tools()`, che
        #     create_agent chiama, scarta i kwarg legati prima
        #   - `bind_tools().bind(cache_control=...)` -> il parametro non
        #     raggiunge comunque l'API: cache_read resta a zero
        #   - `system_prompt=SystemMessage([... cache_control ...])` -> idem
        #
        # E anche se arrivasse, Haiku 4.5 ha una soglia minima di 4.096 token
        # di prefisso: il nostro (istruzioni + sette strumenti) sta sui 2.700,
        # quindi i primi giri non sarebbero comunque eleggibili. Sotto soglia
        # Anthropic non mette in cache e non segnala niente.
        #
        # Con ChatAnthropic nudo la cache funziona (verificato: 6.262 token
        # riletti). Se un domani si passa a un modello con soglia piu' bassa
        # - Opus 5 ne chiede 512 - vale la pena riprovare, ma servira'
        # aggirare create_agent, non solo aggiungere un parametro.
        _agente = create_agent(
            model=modello,
            tools=STRUMENTI,
            system_prompt=ISTRUZIONI,
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
                "haDocumento": bool(r.get("urlDocumento")),
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
                    "haDocumento": bool(risultato.get("urlDocumento")),
                })
    return fonti


def _quante(risultato):
    if not isinstance(risultato, dict):
        return 0
    for chiave in ("risultati", "norme", "dipendenze", "citataDa", "articoli", "commi"):
        if isinstance(risultato.get(chiave), list):
            return len(risultato[chiave])
    return 0


def rispondi(domanda, conversazione=None):
    """
    Genera eventi: {"tipo": ..., ...}

      testo       testo della risposta, incrementale
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
    # I nomi arrivano con l'AIMessage, i risultati dopo col ToolMessage:
    # questa mappa li ricongiunge per id di chiamata.
    nomi_per_id = {}
    # Il modello riprende a scrivere dopo gli strumenti: senza uno stacco la
    # frase nuova si salda a quella precedente.
    dopo_strumento = False

    try:
        for modo, pezzo in agente().stream(
            {"messages": [{"role": "user", "content": domanda}]},
            config=config,
            stream_mode=["updates", "messages"],
        ):
            if modo == "messages":
                messaggio, _meta = pezzo
                contenuto = getattr(messaggio, "content", None)
                # Il contenuto e' una lista di blocchi: interessa solo il testo,
                # non i frammenti di JSON degli argomenti degli strumenti.
                if isinstance(contenuto, list):
                    for blocco in contenuto:
                        if isinstance(blocco, dict) and blocco.get("type") == "text":
                            if blocco.get("text"):
                                if dopo_strumento:
                                    yield {"tipo": "testo", "testo": SEPARATORE}
                                    dopo_strumento = False
                                yield {"tipo": "testo", "testo": blocco["text"]}
                elif isinstance(contenuto, str) and contenuto and \
                        type(messaggio).__name__ == "AIMessageChunk":
                    yield {"tipo": "testo", "testo": contenuto}
                continue

            for _nodo, stato in pezzo.items():
                if not isinstance(stato, dict):
                    continue
                for messaggio in stato.get("messages", []) or []:
                    uso = getattr(messaggio, "usage_metadata", None)
                    if uso:
                        token_in += uso.get("input_tokens", 0)
                        token_out += uso.get("output_tokens", 0)

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
                        dopo_strumento = True
                        yield {"tipo": "risultato", "nome": nome,
                               "quante": _quante(esito),
                               "errore": esito.get("errore") if isinstance(esito, dict) else None}

    except Exception as e:
        yield {"tipo": "errore", "messaggio": f"{type(e).__name__}: {e}"}
        return

    if fonti_raccolte:
        yield {"tipo": "fonti", "fonti": fonti_raccolte}

    prezzo_in, prezzo_out = PREZZI.get(MODELLO, (5.0, 25.0))
    yield {"tipo": "fine", "tokenIn": token_in, "tokenOut": token_out,
           "costo": round(token_in / 1e6 * prezzo_in + token_out / 1e6 * prezzo_out, 4),
           "conversazione": conversazione}
