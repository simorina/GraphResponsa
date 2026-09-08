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
import re
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

# Sovrascrivibile con MODELLO nell'ambiente, per confrontare i modelli a
# parita' di tutto il resto senza toccare il codice.
MODELLO = os.environ.get("MODELLO", "claude-haiku-4-5")
# ChatAnthropic non manda la temperatura se non gliela si da', e l'API allora
# usa la propria: 1.0, cioe' il massimo campionamento casuale. Su un assistente
# giuridico e' la scelta peggiore possibile - la stessa domanda deve dare la
# stessa risposta, e chi legge non sa quale delle due versioni ha ricevuto.
# Si puo' alzare con TEMPERATURA nell'ambiente, per confrontare gli assetti.
TEMPERATURA = float(os.environ.get("TEMPERATURA", "0"))
ACCETTANO_TEMPERATURA = {"claude-haiku-4-5"}

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

   Subito dopo la citazione in prosa, aggiungi anche un marcatore macchina
   nella forma `{{cita:normaId:articolo:comma}}`, usando esattamente gli
   identificativi `normaId`, `articolo` e `comma` come li hai ricevuti dallo
   strumento - l'id interno (es. `L-87-2026`), non come li scrivi in prosa
   (es. "L. 87/2026"). Se la citazione riguarda l'intero articolo senza un
   comma preciso, scrivi `-` al posto del comma. Il marcatore non e' visibile
   a chi legge: diventa un riferimento cliccabile che apre il PDF originale
   alla fonte esatta. Uno per ogni citazione, subito dopo, mai su un dato che
   non hai letto da uno strumento.

   Esempio: "...come previsto dalla L. 87/2026, art. 7, comma
   2{{cita:L-87-2026:7:2}}, che stabilisce..."

   **OGNI atto che nomini nella risposta deve avere il suo marcatore.** Se
   nella prosa scrivi "L. 145/2022", "il Decreto Delegato 146/2023", "la Legge
   sulle societa'", quel riferimento dev'essere cliccabile: senza marcatore
   resta testo morto, e chi legge non puo' verificarlo ne' aprirne il PDF.

   Il marcatore pero' vale solo per cio' che hai LETTO da uno strumento, e
   alcuni campi ti danno un identificativo senza il testo - `abrogataDa`,
   `passoAbrogatoDa`, `ancheIn`, `novellataDa`. Le due regole insieme dicono una
   cosa sola: **se stai per nominare un atto che non hai ancora aperto, aprilo
   prima**, con trova_norma() se ti basta identificarlo o con leggi_articolo()
   se ne citi un passo. Una chiamata in piu' costa mezzo centesimo; una
   citazione che non si puo' aprire costa la verificabilita' della risposta.

   Se davvero non puoi aprirlo - non e' in archivio - allora dillo invece di
   nominarlo e basta: "il testo della L. 59/1974 non e' in archivio".

3. **Se non trovi, dillo.** Se gli strumenti non restituiscono nulla di
   pertinente, dichiara che l'archivio non contiene la risposta. Non colmare il
   vuoto con conoscenza generale sul diritto italiano o di altri ordinamenti:
   San Marino ha un ordinamento proprio e una risposta plausibile ma inventata
   e' il danno peggiore.

4. **Distingui cosa c'e' da cosa e' solo citato.** L'archivio contiene il testo
   completo di alcune norme; altre compaiono solo perche' citate
   (`testoDisponibile: false`). Se una norma rilevante non ha il testo, dillo:
   "la L. 59/1974 e' richiamata ma il suo testo non e' in archivio".

5. **Le due date, che non sono la stessa cosa.** `inVigoreDal` e' la data in cui
   l'atto ha cominciato ad applicarsi; `dataAtto` e' la data in cui e' stato
   emanato. Fra le due passano di solito quindici giorni, ma possono passare
   anni, e su una domanda di diritto la differenza conta.

   Il portale pubblica `inVigoreDal` solo per un terzo degli atti: sulle altre
   due terzi lo riceverai vuoto, e avrai la sola `dataAtto`. In quel caso usala
   per collocare l'atto nel tempo - "la Legge e' del 2014", "e' l'atto piu'
   recente sulla materia" - ma **non dire che e' in vigore da quella data**, che
   non lo sai. Se la domanda dipende proprio da quando una norma ha cominciato
   ad applicarsi, e `inVigoreDal` manca, dillo invece di stimarlo.

6. **Principio di vigenza.** L'utente intende la disciplina in vigore oggi.
   Quando trovi una norma di qualche anno fa su una materia ancora attuale,
   controlla se e' stata novellata - con `chi_cita`, o con `cerca_testo` e
   `dal_anno` impostato a qualche anno prima di oggi. Esponi in primo piano la
   disciplina vigente, e se il dato e' cambiato dillo: "il compenso e' ora di X
   (L. .../2023); era di Y fino al ...".

   **`abrogata: true` significa che l'atto e' caduto per intero.** Il suo testo
   e' ancora in archivio e si legge benissimo, ma non e' piu' diritto vigente.
   Non presentarlo come la disciplina in vigore: dillo subito, in apertura -
   "la L. 34/2010 e' stata abrogata" - indica l'atto abrogante se il campo
   `abrogataDa` lo riporta, e cerca la disciplina che l'ha sostituita. Puoi
   citarlo solo per dire cosa prevedeva e che non vale piu'.

   **L'atto abrogante va aperto, non solo nominato.** `abrogataDa` ti da' un
   identificativo, non un testo: chiamaci trova_norma() prima di scriverlo, cosi'
   la citazione diventa cliccabile e chi legge puo' arrivare all'atto che ha
   sostituito quello caduto. E' il passo che rende utile l'avviso: dire "e'
   abrogata" lascia l'utente a meta' strada, dire "e' abrogata dalla L. 145/2022"
   con il riferimento aperto lo porta a destinazione.

   **`passoAbrogato` colpisce piu' in piccolo e piu' spesso.** Dice che quel
   singolo articolo, o quel singolo comma, e' stato soppresso dentro un atto
   che per il resto e' vivo. E' il caso piu' insidioso di tutti: l'atto risulta
   vigente, il testo del passo si legge intero e perfettamente sensato, e nulla
   in esso avverte che non vale piu' - questo archivio conserva i testi come
   furono pubblicati e non li riscrive. Se il campo compare, non esporre quel
   passo come disciplina: di' che e' stato abrogato, indica l'atto che l'ha
   soppresso, e cerca cosa si applica al suo posto.

   **L'assenza di quel campo non dimostra il contrario.** Il marchio copre 358
   norme su oltre dodicimila: quasi tutti gli atti caduti NON ce l'hanno. Quindi
   `abrogata` assente significa "non risulta", mai "e' in vigore". Non scrivere
   mai che una norma risulta vigente, o tuttora in vigore, appoggiandoti a
   questo silenzio: sulla vigenza puoi affermare solo cio' che hai letto in un
   atto, e il resto e' incertezza da dichiarare.

   **Il campo `citatoDaAttiSuccessivi` non e' un suggerimento, e' un obbligo.**
   Se il passo che stai per citare lo porta, un atto posteriore lo ha citato -
   e qui citare un articolo significa quasi sempre modificarlo. Apri quell'atto
   con leggi_articolo() prima di rispondere, e riporta la versione vigente
   dicendo cosa e' cambiato. Rispondere con il testo marcato senza averlo
   aperto e' un errore, anche quando il testo sembra completo e sensato:
   sembrera' sempre completo e sensato, e sara' scaduto.

   Vale lo stesso per `versionePiuRecente`: dice che fra i risultati ce n'e'
   un altro con la stessa rubrica e un anno maggiore, cioe' quasi sempre la
   stessa disposizione riscritta. **Fra due atti sulla stessa materia, esponi
   sempre il piu' recente**, e cita il precedente solo per dire cosa e'
   cambiato.

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
        # La temperatura si manda solo dove il modello la accetta: su Sonnet 5
        # e Opus 5 il parametro e' deprecato e l'API rifiuta la richiesta con
        # un 400. Il campionamento la' lo governa il modello, non noi.
        parametri = {"model": MODELLO, "max_tokens": 16000,
                     "api_key": os.environ["ANTHROPIC_API_KEY"]}
        if MODELLO in ACCETTANO_TEMPERATURA:
            parametri["temperature"] = TEMPERATURA
        modello = ChatAnthropic(**parametri)

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


# Un id di norma come compare nei risultati degli strumenti: L-171-2022,
# DD-4-2014, EC-None-2019~17163212.
RE_ID_NORMA = re.compile(r"\b([A-Z]{1,3})-(-?\d+|None)-(\d{4})\b")

# Una citazione come la scrive il modello, in tutte le forme d'uso. Un giurista
# scrive lo stesso atto in quattro modi diversi, e riconoscerne uno solo rende
# la spia cieca proprio dove servirebbe. Misurato sul benchmark: un controllo
# che vedeva solo "numero/anno" dava per assenti ventuno citazioni corrette.
#
#   L. 164/2022                              numero / anno
#   Legge n. 164 del 2022                    numero poi anno
#   Decreto Delegato 23 agosto 2024 n. 134   anno poi numero (la data estesa)
#   DD-44-2008                               l'id come lo rendono gli strumenti
TIPO = (r"(?:legge|l\.|lq\.?|lc\.?|d\.l\.|dl\.?|d\.d\.|dd\.?|decreto"
        r"|regolamento|reg\.|r\.)")
CITAZIONI = [
    # Un marcatore di tipo davanti al numero e' obbligatorio nella forma con la
    # barra, altrimenti "fino al 31/12/2026" verrebbe letto come la norma
    # 12/2026.
    re.compile(TIPO + r"[\s\u00a0]*(?:n[\.\u00b0]?[\s\u00a0]*)?"
               r"(\d{1,4})[\s\u00a0]*/[\s\u00a0]*((?:19|20)\d{2})", re.I),
    re.compile(TIPO + r"[\s\u00a0]*n[\.\u00b0]?[\s\u00a0]*(\d{1,4})\b"
               r".{0,40}?\b((?:19|20)\d{2})\b", re.I),
    re.compile(TIPO + r"[^\n]{0,40}?\b((?:19|20)\d{2})\b[^\n]{0,20}?"
               r"n[\.\u00b0]?[\s\u00a0]*(\d{1,4})\b", re.I),
    re.compile(r"\b[A-Z]{1,3}-(\d{1,4})-((?:19|20)\d{2})\b"),
]

MARCATORE = re.compile(r"\{\{cita:[^{}]*\}\}")


def _ancora_gli_atti(testo, fonti):
    """Rende cliccabile ogni atto nominato nella prosa, se la fonte esiste.

    Chiedere al modello di non dimenticarsi un marcatore e' chiedergli di fare
    contabilita', e la contabilita' si fa nel codice: misurato su quattro
    domande, nominava da uno a due atti per risposta senza il marcatore, e chi
    legge si trovava un riferimento che non si puo' aprire.

    Si aggiunge il marcatore SOLO se fra le fonti c'e' davvero quell'atto. Se
    non c'e', il riferimento resta testo semplice: e' la stessa garanzia che il
    frontend applica scartando i marcatori senza riscontro, e vale la pena
    ripeterla qui invece di allentarla.
    """
    if not fonti:
        return testo
    # Per ogni atto si tiene una fonte RAPPRESENTATIVA, non solo il suo id: il
    # marcatore dev'essere (norma, articolo, comma) di una fonte davvero
    # presente, altrimenti il frontend lo scarta. Si preferisce la fonte a
    # livello d'atto - articolo "-" - perche' e' quella che corrisponde a un
    # riferimento nominato in prosa senza articolo; se non c'e', va bene la
    # prima, che porta comunque al pannello e al PDF dell'atto giusto.
    per_atto = {}
    for f in fonti:
        pezzi = str(f.get("norma") or "").split("-")
        if len(pezzi) < 3 or not pezzi[1].isdigit():
            continue
        chiave = (pezzi[1], pezzi[2].split("~")[0])
        precedente = per_atto.get(chiave)
        migliore = (precedente is None
                    or (str(f.get("articolo")) == "-" and str(precedente[1]) != "-")
                    or ("~" not in str(f["norma"]) and "~" in str(precedente[0])))
        if migliore:
            per_atto[chiave] = (f["norma"], f.get("articolo"), f.get("comma"))
    if not per_atto:
        return testo

    # I marcatori gia' presenti si mascherano con spazi PRIMA di cercare: il
    # riferimento vive anche dentro il marcatore - {{cita:L-145-2022:-:-}} - e
    # senza mascherarlo se ne agganciava uno dentro l'altro. Gli spazi hanno la
    # stessa lunghezza, cosi' le posizioni restano valide sul testo originale.
    mascherato = MARCATORE.sub(lambda m: " " * len(m.group(0)), testo)

    fuori, fine = [], 0
    # si raccolgono tutte le occorrenze, poi si inseriscono da sinistra a destra
    trovate = []
    for i, espressione in enumerate(CITAZIONI):
        for m in espressione.finditer(mascherato):
            numero, anno = ((m.group(2), m.group(1)) if i == 2
                            else (m.group(1), m.group(2)))
            trovate.append((m.start(), m.end(), numero, anno))
    for inizio, termine, numero, anno in sorted(trovate):
        if inizio < fine:
            continue                      # gia' coperta da un aggancio precedente
        rif = per_atto.get((numero, anno))
        if not rif:
            continue                      # non fra le fonti: resta testo semplice
        if testo[termine:termine + 2] == "{{":
            continue                      # il modello l'ha gia' messo. Non si
                                          # avanza `fine`: il testo saltato deve
                                          # comunque finire nell'uscita, o la
                                          # prosa davanti al marcatore sparisce.
        norma, articolo, comma = rif
        articolo = "-" if articolo in (None, "") else str(articolo)
        comma = "-" if comma in (None, "") else str(comma)
        fuori.append(testo[fine:termine]
                     + f"{{{{cita:{norma}:{articolo}:{comma}}}}}")
        fine = termine
    fuori.append(testo[fine:])
    return "".join(fuori)


def _citazioni_non_verificate(testo, norme_viste):
    """Le norme citate nella risposta che nessuno strumento ha restituito.

    Il sistema SA quali sono le fonti giuste: gli strumenti tornano normaId,
    articolo e comma esatti. Il modello poi riscrive la citazione in prosa, e
    li' puo' sbagliarla. Il confronto e' deterministico - o quell'atto e' stato
    letto, o e' stato inventato - e non richiede alcun giudizio.

    Misurato sul benchmark: 79 risposte corrette su 96 nel merito, ma fonte
    giusta solo 50 su 95. Un assistente giuridico che dice la cosa esatta
    citando la norma sbagliata non e' meta' corretto: chi legge non puo'
    verificare.

    Volutamente prudente: si segnala solo la forma esplicita "tipo numero/anno".
    Un falso allarme costa piu' di una segnalazione mancata.
    """
    coppie_viste = {(n, a) for _t, n, a in
                    (m.groups() for m in RE_ID_NORMA.finditer(norme_viste))}
    coppie = []
    for i, espressione in enumerate(CITAZIONI):
        for m in espressione.finditer(testo or ""):
            # La terza forma trova prima l'anno e poi il numero: si rimette
            # nell'ordine delle altre invece di duplicare la logica a valle.
            coppie.append((m.group(2), m.group(1)) if i == 2
                          else (m.group(1), m.group(2)))

    fuori = []
    for numero, anno in coppie:
        if (numero, anno) in coppie_viste or (numero.lstrip("0"), anno) in coppie_viste:
            continue
        etichetta = f"{numero}/{anno}"
        if etichetta not in fuori:
            fuori.append(etichetta)
    return fuori


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
                # Gli atti che riportano lo STESSO identico testo. La potatura
                # li collassa in una riga sola per non sprecare i posti utili,
                # ma come fonti valgono quanto quello mostrato: un tariffario
                # riemesso in cinque decreti si puo' citare da ognuno dei
                # cinque. Non elencarli faceva sembrare unica una fonte che
                # non lo e', e chi cercava la propria versione non la trovava.
                # Il portale possiede il PDF originale di questo atto: il
                # frontend puo' offrirne l'apertura.
                "haDocumento": bool(r.get("urlDocumento")),
                "ancheIn": r.get("ancheIn") or [],
                # L'atto successivo che modifica questo articolo: chi legge
                # deve poterci arrivare, non solo il modello.
                "novellataDa": [n.get("norma") for n in
                                (r.get("citatoDaAttiSuccessivi") or [])],
                # L'atto e' caduto per intero. Il marchio e' raro - 358 norme
                # su 12.248 - e proprio per questo va mostrato dove compare:
                # chi legge non ha modo di dedurlo dal testo, che di suo resta
                # perfettamente sensato. L'assenza del marchio non dice nulla.
                "abrogata": bool(r.get("abrogata")),
                "abrogataDa": r.get("abrogataDa") or [],
                # Il passo in se', dentro un atto ancora vivo. Va mostrato
                # proprio perche' il testo attorno resta valido: nulla, nel
                # leggerlo, farebbe sospettare che questo pezzo non valga piu'.
                "passoAbrogato": bool(r.get("passoAbrogato")),
                "passoAbrogatoDa": r.get("passoAbrogatoDa") or [],
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
                    "abrogata": bool(risultato.get("abrogata")),
                    "abrogataDa": risultato.get("abrogataDa") or [],
                    "passoAbrogato": bool(c.get("abrogato")
                                          or risultato.get("passoAbrogato")),
                    "passoAbrogatoDa": (c.get("abrogatoDa")
                                        or risultato.get("passoAbrogatoDa") or []),
                })
    # Anche `trova_norma` e `struttura_norma` consultano davvero l'archivio, e
    # finora non producevano fonti. La conseguenza non era solo una lista vuota
    # in fondo: il frontend SCARTA i marcatori {{cita:...}} che non trovano
    # riscontro fra le fonti - giustamente, un marcatore inventato non deve
    # produrre un link - quindi su una domanda risolta con questi due strumenti
    # sparivano anche le citazioni dentro il testo. La risposta restava giusta e
    # sembrava non ancorata a nulla.
    #
    # Il bersaglio qui e' l'atto o l'articolo, non il comma: si usa "-" per le
    # partizioni che mancano, la stessa convenzione che il modello gia' scrive
    # nei marcatori ({{cita:L-106-2009:-:-}}) e che normalizzaComma() conosce.
    elif nome_strumento == "trova_norma":
        for r in risultato.get("risultati", []):
            if not r.get("id"):
                continue
            fonti.append({
                "norma": r.get("id"), "titoloNorma": r.get("titolo"),
                "articolo": "-", "comma": "-",
                "testo": r.get("titolo") or "",
                "haDocumento": bool(r.get("urlDocumento")),
                "abrogata": bool(r.get("abrogata")),
                "abrogataDa": r.get("abrogataDa") or [],
            })
    elif nome_strumento == "struttura_norma" and risultato.get("id"):
        for a in risultato.get("articoli", []):
            if not a.get("numero"):
                continue
            fonti.append({
                "norma": risultato.get("id"),
                "titoloNorma": risultato.get("titolo"),
                "articolo": a.get("numero"), "rubrica": a.get("rubrica"),
                "comma": "-",
                # La struttura porta la rubrica, non il testo: e' cio' che
                # l'agente ha davvero letto, e non si finge di piu'.
                "testo": a.get("rubrica") or "",
                "haDocumento": bool(risultato.get("urlDocumento")),
            })
    # Gli strumenti di RETE - chi cita, chi e' citato, l'elenco - restituiscono
    # riferimenti a livello d'atto, e finora non producevano fonti. Il costo si
    # vedeva su una domanda tipica: "quali modifiche ha subito la L. 36/1958"
    # elencava sei atti modificanti e nessuno era cliccabile, perche' nessuno
    # era fra le fonti e l'ancoraggio - giustamente - non inventa.
    elif nome_strumento in ("chi_cita", "citazioni_da", "elenco_norme"):
        elenchi = ((risultato.get("citataDa") or [])
                   + (risultato.get("dipendenze") or [])
                   + (risultato.get("basePreambolo") or [])
                   + (risultato.get("normeEstratte") or []))
        for r in elenchi:
            atto = r.get("norma") or r.get("id")
            if not atto:
                continue
            fonti.append({
                "norma": atto, "titoloNorma": r.get("titolo"),
                "articolo": "-", "comma": "-",
                "testo": r.get("titolo") or "",
                "haDocumento": bool(r.get("urlDocumento")),
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
    # Il grezzo di tutti i risultati: serve a stabilire quali norme il
    # modello ha davvero avuto sotto gli occhi.
    grezzo_strumenti = []
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
                        grezzo_strumenti.append(
                            json.dumps(esito, ensure_ascii=False, default=str))
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
        yield {"tipo": "testo",
               "testo": _ancora_gli_atti(SEPARATORE.join(blocchi_testo),
                                         fonti_raccolte)}

    if fonti_raccolte:
        yield {"tipo": "fonti", "fonti": fonti_raccolte}

    prezzo_in, prezzo_out = PREZZI.get(MODELLO, (5.0, 25.0))
    # Scrivere in cache costa 1,25 volte; rileggere 0,10.
    pieni = token_in - token_letti - token_scritti
    costo = (pieni + token_scritti * 1.25 + token_letti * 0.10) / 1e6 * prezzo_in         + token_out / 1e6 * prezzo_out
    sospette = _citazioni_non_verificate(
        SEPARATORE.join(blocchi_testo), " ".join(grezzo_strumenti))

    yield {"tipo": "fine", "tokenIn": token_in, "tokenOut": token_out,
           "tokenDaCache": token_letti,
           "citazioniNonVerificate": sospette,
           "costo": round(costo, 4),
           "conversazione": conversazione}
