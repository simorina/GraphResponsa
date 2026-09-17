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
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from .strumenti import STRUMENTI, grafo

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

# Sovrascrivibile con MODELLO nell'ambiente, per confrontare i modelli a
# parita' di tutto il resto senza toccare il codice.
#
# Sonnet 5 dal 17/09. Haiku 4.5 non seguiva in modo affidabile le regole su
# rinvii, definizioni, vigenza e completezza: sulla chat reale sul trust
# scriveva "elenco completo", inventava rubriche e una volta ha negato un
# ricorso che l'art. 12 del DD 85/2013 disciplina. Sonnet, sulla stessa chat,
# le rispetta. Costa il doppio per token (vedi PREZZI) e scrive risposte piu'
# lunghe: il server tiene viva la connessione durante l'attesa (BATTITO).
MODELLO = os.environ.get("MODELLO", "claude-sonnet-5")
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
Rispondi solo con cio' che leggi nel grafo della normativa, tramite gli strumenti.

## 1. Prima cerca, poi rispondi

- Non chiedere chiarimenti prima di aver cercato. Su una domanda vaga prendi
  l'interpretazione piu' probabile, cerca, e poi esponi cosa hai trovato e come
  restringere. Anche "questa legge" senza un atto nominato prima: cerca la
  materia di cui parla, e sara' la ricerca a dirti quale atto e'. Chiedi quale
  interessa solo se dopo la ricerca restano candidati incompatibili.
- Parti da `cerca_testo` con il lessico normativo. Se rende poco, riformula
  (chi scrive "vacanza studio", la norma dice "soggiorno culturale"). Solo dopo
  due formulazioni senza esito concludi che la materia non c'e'.
- `cerca_testo` restituisce sempre qualcosa, anche quando l'archivio non ha la
  materia: la pertinenza la stabilisce il testo, non il rango. Se nulla e'
  pertinente, dillo. Non colmare il vuoto con il diritto italiano o di altri
  ordinamenti: una risposta plausibile ma inventata e' il danno peggiore.
- Se una norma rilevante e' solo citata (`testoDisponibile: false`), di' che il
  suo testo non e' in archivio.
- L'archivio raccoglie disposizioni, non procedure amministrative. Su moduli,
  sportelli e documenti da presentare rispondi con cio' che la norma prescrive
  (requisiti, termini, organo competente) e di' che la prassi non e' in
  archivio. Non dedurre passi pratici dalla disposizione.

## 2. Citazioni

- Ogni affermazione viene da un risultato degli strumenti e porta la citazione
  in prosa seguita dal marcatore `{{cita:normaId:articolo:comma}}`, con gli id
  esatti degli strumenti: "...L. 87/2026, art. 7, comma 2{{cita:L-87-2026:7:2}},
  che stabilisce...". Il marcatore diventa il link al PDF. Metti `-` al posto
  del comma per l'articolo intero, e al posto di articolo e comma per l'atto
  intero: `{{cita:L-64-2025:-:-}}`.
- Il marcatore punta al passo da cui viene il dato: un requisito letto al
  comma 18 si cita al comma 18, e un atto nominato nel suo insieme non si cita
  all'art. 1.
- Un marcatore per dato, non per frase: se piu' frasi di seguito vengono dallo
  stesso comma, mettilo una volta, alla fine del gruppo.
- Ogni atto che nomini ha il suo marcatore, e il marcatore vale solo per cio'
  che hai letto. Un atto che conosci solo da un campo (`abrogataDa`,
  `passoAbrogatoDa`, `ancheIn`, `novellataDa`) va aperto prima di nominarlo:
  `trova_norma` per identificarlo, `leggi_articolo` per citarne un passo. Se
  non e' in archivio, dillo.
- Le parti numerate si citano per quello che sono, col numero esatto nel
  marcatore:
  - `1.cap2` capoverso: testo che l'articolo inserisce in un altro atto, non
    una sua regola ("art. 5, comma 1, capoverso 2");
  - `1.p3` voce di un elenco ("comma 1, punto 3");
  - `all4` testo dell'allegato stampato dopo la promulgazione ("allegato
    all'atto");
  - `1.rip2` il secondo comma 1 di un articolo che ne numera due;
  - articoli `all-3` (art. 3 dell'allegato), `all2-3` (del secondo allegato),
    `9-rip2` (il secondo articolo numerato 9).
- I nomi dei campi (`citatoDaAttiSuccessivi`, `testoCoordinatoAl`...) e degli
  strumenti non vanno nella risposta: di' cosa significano ("una legge del 2008
  ha modificato questo articolo"). A "che leggi hai usato?" rispondi con gli
  atti e gli articoli letti, ciascuno col suo marcatore.

## 3. Vigenza

L'utente vuole la disciplina in vigore oggi. L'archivio conserva i testi come
furono pubblicati: i marchi seguenti dicono cosa e' cambiato, e vanno letti
prima di citare. Su una norma di qualche anno fa in una materia ancora attuale,
cerca anche con `dal_anno` se c'e' una disciplina piu' recente.

- `abrogata: true`: l'atto e' caduto per intero. Dillo in apertura, apri con
  `trova_norma` l'atto indicato in `abrogataDa`, e cerca la disciplina che l'ha
  sostituito. Citalo solo per dire cosa prevedeva. Se il titolo comincia con
  "DECADUTO", il decreto ha perso efficacia: dillo con questa parola, non
  "abrogato", e non attribuirgli un atto abrogante.
- `passoAbrogato` sull'articolo, `abrogato` sul comma: quel passo e' soppresso
  dentro un atto vivo, e il testo non lo lascia capire. Non esporlo come
  disciplina: di' che e' abrogato, da chi, e cosa si applica al suo posto.
- L'assenza di questi marchi non prova nulla: coprono una piccola parte delle
  abrogazioni. "Vigente", "in vigore", "attualmente" si scrivono solo con una
  prova letta (una modifica recente, un atto posteriore che lo applica);
  altrimenti "nessuna abrogazione risulta in archivio". Vale per ogni voce di un
  elenco.
- `citatoDaAttiSuccessivi`: un atto posteriore cita l'articolo, e quasi sempre
  lo modifica. Se lo porta il passo che citi, leggi la modifica prima di
  rispondere (prima le voci con `riscrive: true`, qualunque sia l'anno) ed
  esponi il testo vigente dicendo cosa e' cambiato.
- `attoNovellatoDa`: l'atto e' stato modificato da leggi successive negli
  `articoli` elencati. Sulle domande generali ("come funziona X") e' il marchio
  piu' importante: la ricerca ti porta gli articoli che parlano del tema, non
  quelli riscritti. Se compare su un atto che usi, apri il novellante piu'
  recente PRIMA di scrivere, ed esponi la disciplina di adesso dicendo cosa e'
  cambiato. Che l'articolo che
  citi sia stato modificato lo dicono solo `toccaQuestoArticolo: true`,
  `citatoDaAttiSuccessivi` o il testo letto: con `false` le modifiche
  riguardano altri articoli, e se la domanda e' su un articolo preciso non
  serve aprire il novellante.
- `testoCoordinatoAl`: l'articolo e' il testo coordinato, aggiornato fino a
  quella data. Modifiche posteriori (`citatoDaAttiSuccessivi`,
  `versionePiuRecente`) vanno aperte; se la data e' lontana e non ne trovi,
  dillo ("testo coordinato aggiornato al 24 dicembre 2018").
- `testoAggiornatoIn`: l'articolo ha scritto il suo testo in un altro atto (l'art.
  5 della L. 64/2025 aggiunge l'art. 3-bis alla L. 44/2015). Leggi e cita
  l'articolo indicato, e presenta quello che hai davanti come "introdotto dalla
  L. 64/2025, art. 5".
- `versionePiuRecente` e `ancheIn`: la stessa rubrica o lo stesso testo
  ricorrono in un atto piu' recente. Esponi il piu' recente e cita il
  precedente solo per dire cosa e' cambiato. Non serve su domande storiche o su
  atti esauriti.
- Per sapere se un articolo e' aggiornato bastano questi marchi. `chi_cita`
  elenca i rinvii a un atto intero, non le modifiche a un articolo.
- Filtri di `cerca_testo`: `al_anno` per le domande storiche ("prima del 2000":
  `dal_anno` escluderebbe proprio quel periodo), `dal_anno` per la disciplina
  recente, `tipi` per un tipo d'atto, `escludi_abrogati` per la disciplina
  vigente (toglie solo le abrogazioni note).
- Date: `inVigoreDal` e' l'entrata in vigore, `dataAtto` l'emanazione. Se
  `inVigoreDal` manca usa `dataAtto` per collocare l'atto nel tempo, ma non
  dire che e' in vigore da quella data; se la domanda dipende proprio da
  quello, di' che il dato manca.

## 4. Leggere bene

- Un rinvio si segue. Se la risposta dipende da articoli richiamati ("i
  provvedimenti degli artt. 53, 54 e 55 della L. 42/2010"), leggili. Non
  descrivere un articolo, ne' la sua rubrica, dal numero o dal tema:
  `struttura_norma` da' tutte le rubriche di un atto in una chiamata.
- I termini definiti ("Autorita' Giudiziaria", "Ufficio") si leggono
  nell'articolo di definizioni della legge madre, con i suoi marchi, quando la
  risposta dipende da chi o cosa indicano: la definizione puo' essere stata
  riscritta (la L. 123/2019 ha fatto dell'"Autorita' Giudiziaria" della L.
  42/2010 la Corte per il Trust). Due norme che con la definizione vigente
  indicano lo stesso organo non sono situazioni diverse.
- Di' solo cio' che il testo dice. Se una norma elimina delle parole, riporta
  quali e l'effetto letterale. Una qualificazione giuridica che non leggi in un
  atto la ometti, o la presenti come tua interpretazione.
- `troncato: true` vuol dire testo tagliato: leggi l'articolo con
  `leggi_articolo` prima di citarlo, e comunque quando e' centrale. Se anche
  `leggi_articolo` risponde `parziale: true` (allegati, tabelle), leggi solo i
  commi che servono con `comma` e `da_carattere`, e di' che il testo e' lungo e
  che ne hai letto una parte. Un risultato di `cerca_testo` con `daCarattere`
  e' gia' il passo giusto di un comma lunghissimo: citalo col numero del comma
  e, se ti serve il contesto, leggi da quel carattere.
- Struttura di una norma (quanti articoli, com'e' organizzata, di cosa tratta
  l'art. N): `struttura_norma`, mai gli articoli uno per uno. Presupposti e
  rinvii: `citazioni_da`. Chi richiama una norma: `chi_cita`. Contenuto della
  banca dati: `elenco_norme`. Gli strumenti indipendenti chiamali in parallelo.
- "Tutte le norme", "elenco completo": prima cerca per titolo con
  `trova_norma(testo=..., limite=...)` con i termini della materia, guarda con
  `chi_cita` chi richiama le leggi cardine, e includi convenzioni
  internazionali e ratifiche. Senza questa ricerca presenta l'elenco come "le
  principali norme trovate", mai come completo.

## 5. Il diritto sammarinese

- Usa le parole dell'articolo che citi, anche se quelle italiane ti sembrano
  piu' naturali: *prigionia* (non reclusione), *interdizione*, *multa a
  giorni*; il *misfatto* e' doloso, il *delitto* colposo (art. 150 "se il
  misfatto e' commesso", art. 163 "il delitto di omicidio" colposo).
- Una pena in gradi va tradotta in durata: leggi l'articolo che definisce i
  gradi (per la prigionia l'art. 81 del Codice Penale vigente,
  `leggi_articolo("L-17-1974", "81")`) e dai la durata accanto al grado, con
  il marcatore di quell'articolo.
- Gli elenchi della legge si riportano con i loro numeri e lettere - 1), 1
  bis), 2); a), b) - senza rinumerarli ne' trasformarli in punti elenco.

## 6. La risposta

- Scrivi sempre e solo in italiano, anche le frasi prima di una chiamata agli
  strumenti: l'utente le vede.
- Apri con la risposta, non con il metodo, e parti dal fatto: "hai trenta
  giorni, e sono perentori (L. 28/1991, art. 30)", non "l'articolo 30 della L.
  28/1991 dispone che...". Il professionista trova gli estremi e la lettera
  dove conta; il cittadino capisce comunque. Riporta tra virgolette il testo
  quando la formulazione esatta conta.
- Con una fonte esplicita trovata subito, esponila senza esitazioni. Se sei
  arrivato alla risposta dopo molti tentativi, o il passo che citi risponde
  solo di sbieco, dillo: "e' quanto di piu' pertinente l'archivio
  contiene, ma non disciplina espressamente il tuo caso".

Prima di inviare, ricontrolla:
- ogni rubrica, contenuto o modifica che nomini l'hai letta in un risultato;
- "vigente", "in vigore", "attualmente" hanno una prova letta;
- "completo", "tutte" vengono dopo la ricerca sistematica;
- se la risposta dipende da un termine definito, hai letto la definizione e le
  sue modifiche;
- ogni atto nominato ha il suo marcatore.
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
        # identico a ogni giro del ciclo ReAct: 7.632 token misurati con l'API
        # di conteggio (3.673 le istruzioni, riscritte il 17/09 da 7.380), e
        # sopra la soglia di Haiku per la cache.
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

        # Il marcatore sul system copre solo il prefisso fisso. Il resto - la
        # cronologia, che a ogni giro del ciclo si rispedisce intera con i
        # risultati degli strumenti - si pagava a prezzo pieno: la chat sui
        # trust del 16/09 ha mandato 630.687 token d'ingresso per quattro
        # domande, e solo 104.088 venivano dalla cache. Il middleware aggiunge
        # il punto di rottura in coda alla richiesta, cosi' ogni giro rilegge
        # il precedente a un decimo del prezzo.
        _agente = create_agent(
            model=modello,
            tools=STRUMENTI,
            system_prompt=istruzioni,
            checkpointer=_memoria,
            middleware=[AnthropicPromptCachingMiddleware(ttl="5m")],
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
# I nomi composti vanno prima: "Decreto Delegato 50/2010" e "Legge Qualificata
# n. 1 del 2012" non si leggevano, perche' dopo "Decreto" o "Legge" veniva una
# parola invece del numero.
TIPO = (r"(?:legge[\s\u00a0]+(?:qualificata|costituzionale)"
        r"|decreto[\s\u00a0-]+(?:delegato|legge|reggenziale|consiliare)"
        r"|legge|l\.|lq\.?|lc\.?|d\.l\.|dl\.?|d\.d\.|dd\.?|decreto"
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


def _aggiungi_fonti_d_atto(fonti, viste):
    """Per ogni atto consultato, anche la fonte dell'atto intero.

    L'aggancio automatico mette un marcatore dopo ogni atto nominato in prosa,
    e il marcatore deve puntare a una fonte esistente. Senza una fonte d'atto
    ripiegava sulla prima fonte di quell'atto: su una domanda risolta con
    struttura_norma era l'art. 1, e ogni "L. 64/2025" della risposta finiva
    seguita da "[art. 1]", un articolo che non c'entrava. Con leggi_articolo era
    il comma 1 dell'articolo letto, anche per requisiti scritti al comma 18.
    Chi nomina la legge nomina la legge: "[atto]".
    """
    # Lo stesso per l'articolo intero: "art. 5 della L. 64/2025" senza un
    # comma e' un marcatore {{cita:L-64-2025:5:-}}, e senza la sua fonte il
    # sito lo scartava anche se l'articolo era stato letto.
    for f in list(fonti):
        if not f.get("norma"):
            continue
        for articolo in ("-", str(f.get("articolo") or "-")):
            chiave = (f["norma"], articolo, "-")
            if chiave in viste:
                continue
            viste.add(chiave)
            fonti.append({"norma": f["norma"], "titoloNorma": f.get("titoloNorma"),
                          "articolo": articolo, "rubrica": f.get("rubrica") if articolo != "-" else None,
                          "pagina": f.get("pagina") if articolo != "-" else None,
                          "comma": "-",
                          "testo": (f.get("rubrica") if articolo != "-" else None)
                                   or f.get("titoloNorma") or "",
                          "haDocumento": bool(f.get("haDocumento")),
                          "abrogata": bool(f.get("abrogata")),
                          "abrogataDa": f.get("abrogataDa") or []})
    return fonti


# I nomi dei campi che gli strumenti restituiscono, e come si dicono a chi
# legge. Il prompt chiede di non scriverli; qui si traducono quelli che passano
# lo stesso - misurato: "l'articolo 150 ha `citatoDaAttiSuccessivi` che
# indicano modifiche", scritto a un utente.
CAMPI_INTERNI = {
    "citatoDaAttiSuccessivi": "le modifiche successive registrate",
    "attoNovellatoDa": "gli atti che l'hanno modificato",
    "toccaQuestoArticolo": "la modifica di questo articolo",
    "testoCoordinatoAl": "la data di aggiornamento del testo coordinato",
    "testoAggiornatoIn": "l'articolo in cui il testo e' stato inserito",
    "versionePiuRecente": "la versione piu' recente",
    "passiIntrodottiOraAbrogati": "i passi introdotti e poi abrogati",
    "passoAbrogatoDa": "gli atti che hanno abrogato il passo",
    "passoAbrogato": "l'abrogazione del passo",
    "abrogataDa": "gli atti che l'hanno abrogata",
    "novellataDa": "gli atti che l'hanno modificata",
    "testoDisponibile": "la disponibilita' del testo",
    "numeroOriginale": "il numero nel testo",
    "inVigoreDal": "la data di entrata in vigore",
    "ancheIn": "gli altri atti con lo stesso testo",
}
RE_CAMPO_INTERNO = re.compile(r"`?\b(" + "|".join(sorted(CAMPI_INTERNI, key=len, reverse=True)) + r")\b`?")

# "L." / "D.D." come li scrive il modello, e il tipo d'atto che vogliono dire.
TIPI_ABBREVIATI = [
    (re.compile(r"^\s*(?:legge\s+qualificata|l\.?\s*q\.?)", re.I), "Legge Qualificata"),
    (re.compile(r"^\s*(?:legge\s+costituzionale|l\.?\s*c\.?)\b", re.I), "Legge Costituzionale"),
    (re.compile(r"^\s*(?:decreto[\s-]*legge|d\.?\s*l\.?)", re.I), "Decreto Legge"),
    (re.compile(r"^\s*(?:decreto\s+delegato|d\.?\s*d\.?)", re.I), "Decreto Delegato"),
    (re.compile(r"^\s*(?:regolamento|reg\.|r\.)", re.I), "Regolamento"),
    (re.compile(r"^\s*(?:legge|l\.)", re.I), "Legge"),
]


def _prefisso_nominato(citazione):
    """Il prefisso d'id dell'atto come lo nomina la prosa, o None.

    Numero e anno non bastano: la Legge Costituzionale e la Legge Qualificata
    del 26 gennaio 2012 sono entrambe n.1, e "Legge Qualificata 26 gennaio
    2012 n.1" riceveva il riferimento della LC-1-2012. Per "Decreto" senza
    altro il tipo resta ignoto (None): decide solo se l'atto e' uno.
    """
    m = re.match(r"\s*([A-Z]{1,3})-\d", citazione)
    if m:
        return m.group(1)
    tipo = next((t for e, t in TIPI_ABBREVIATI if e.match(citazione)), None)
    if not tipo:
        return None
    from comune import norma_id
    return norma_id(tipo, 1, 2000).split("-")[0]


def _chiave_articolo(articolo):
    """Come il frontend confronta i numeri d'articolo."""
    if articolo in (None, ""):
        return "-"
    return re.sub(r"[\s.\-–]+", "", str(articolo)).lower()


def _senza_campi_interni(testo):
    return RE_CAMPO_INTERNO.sub(lambda m: CAMPI_INTERNI[m.group(1)], testo)


def _fonte_d_atto(norma):
    """La fonte a livello d'atto per una norma con testo, o None."""
    try:
        righe = grafo().query("""
            MATCH (n:Norma {id: $id}) WHERE n.caricata
            RETURN n.id AS id, n.titolo AS titolo, n.urlDocumento AS url,
                   n.abrogata AS abrogata, n.abrogataDa AS abrogataDa""", {"id": norma})
    except Exception:
        return None
    if not righe:
        return None
    r = righe[0]
    return {"norma": r["id"], "titoloNorma": r["titolo"], "articolo": "-", "comma": "-",
            "testo": r["titolo"] or "", "haDocumento": bool(r["url"]),
            "abrogata": bool(r["abrogata"]), "abrogataDa": r["abrogataDa"] or []}


def _ripara_marcatori(testo, fonti, viste):
    """I marcatori senza fonte, riportati al livello che la fonte ha davvero.

    Il frontend scarta un marcatore che non trova fra le fonti: il riferimento
    spariva. Un comma non letto di un articolo letto diventa l'articolo; un
    passo di un atto che non e' stato aperto diventa l'atto, se l'atto ha il
    testo in archivio. Un marcatore verso cio' che l'archivio non ha si toglie,
    come farebbe il frontend.
    """
    chiavi = {(str(f.get("norma")), _chiave_articolo(f.get("articolo")),
               str(f.get("comma") if f.get("comma") not in (None, "") else "-")) for f in fonti}

    def sostituisci(m):
        norma, articolo, comma = m.group(1), m.group(2), m.group(3) or "-"
        if (norma, _chiave_articolo(articolo), comma) in chiavi:
            return m.group(0)
        if (norma, _chiave_articolo(articolo), "-") in chiavi:
            return f"{{{{cita:{norma}:{articolo}:-}}}}"
        if (norma, "-", "-") not in chiavi:
            fonte = _fonte_d_atto(norma)
            if fonte is None:
                return ""
            fonti.append(fonte)
            viste.add((norma, "-", "-"))
            chiavi.add((norma, "-", "-"))
        return f"{{{{cita:{norma}:-:-}}}}"

    return re.sub(r"\{\{cita:([^:{}]+):([^:{}]*):([^:{}]*)\}\}", sostituisci, testo)


def _fonti_atti_nominati(testo, fonti, viste):
    """Gli atti nominati in prosa ma mai aperti, se l'archivio ne ha il testo.

    "L'unica modifica e' quella della L. 97/2008": il modello l'aveva letta nei
    marchi di leggi_articolo senza aprirla, e il riferimento restava testo
    morto. Si aggiunge la fonte dell'atto - titolo e PDF, niente che il
    modello non abbia visto - e _ancora_gli_atti lo rende cliccabile.
    """
    presenti = set()
    for f in fonti:
        pezzi = str(f.get("norma") or "").split("-")
        if len(pezzi) >= 3 and pezzi[1].isdigit():
            presenti.add((pezzi[0], str(int(pezzi[1])), pezzi[2].split("~")[0]))
    mascherato = MARCATORE.sub(lambda m: " " * len(m.group(0)), testo)
    for i, espressione in enumerate(CITAZIONI):
        for m in espressione.finditer(mascherato):
            numero, anno = ((m.group(2), m.group(1)) if i == 2 else (m.group(1), m.group(2)))
            prefisso = _prefisso_nominato(m.group(0))
            if not prefisso:
                continue
            chiave = (prefisso, str(int(numero)), anno)
            if chiave in presenti:
                continue
            norma = f"{prefisso}-{int(numero)}-{anno}"
            fonte = _fonte_d_atto(norma)
            if fonte is None or (norma, "-", "-") in viste:
                continue
            fonti.append(fonte)
            viste.add((norma, "-", "-"))
            presenti.add(chiave)
    return fonti


# "{cita:DD-50-2010:8:3}", con una graffa sola: Sonnet lo ha scritto cosi' nella
# prova del 16/09 sui trust, il sito non lo riconosce, e _ancora_gli_atti ci infilava
# dentro un secondo marcatore sull'id.
RE_MARCATORE_SEMPLICE = re.compile(r"(?<!\{)\{cita:([^{}]+)\}(?!\})")

RE_MARCATORE_PARTI = re.compile(r"\{\{cita:([^:{}]+):([^:{}]*):([^:{}]*)\}\}")


def fonti_della_storia(messaggi):
    """Le fonti dei risultati degli strumenti in una sequenza di messaggi."""
    fonti, viste = [], set()
    for m in messaggi:
        if getattr(m, "type", "") != "tool":
            continue
        esito = m.content
        if isinstance(esito, str):
            try:
                esito = json.loads(esito)
            except (ValueError, TypeError):
                pass
        for f in _fonti_da(getattr(m, "name", "") or "", esito):
            chiave = (f["norma"], f["articolo"], f["comma"])
            if chiave not in viste:
                viste.add(chiave)
                fonti.append(f)
    return fonti


def _richiama_precedenti(testo, fonti, viste, precedenti):
    """Le fonti dei turni precedenti che la risposta cita.

    "Che leggi hai usato?" non chiama strumenti: il modello risponde con cio'
    che ha letto prima, e scrive i marcatori giusti - art. 150, commi 1, 2 e 3.
    Ma le fonti si raccoglievano solo dal turno in corso, erano zero, e il sito
    scartava ogni marcatore. Si riprendono dai turni precedenti quelle citate,
    e solo quelle: il pannello delle fonti resta quello del turno.
    """
    if not precedenti:
        return
    presenti = {(str(f.get("norma")), _chiave_articolo(f.get("articolo")), str(f.get("comma") or "-"))
                for f in fonti}
    for m in RE_MARCATORE_PARTI.finditer(testo):
        norma, articolo, comma = m.group(1), _chiave_articolo(m.group(2)), m.group(3) or "-"
        if (norma, articolo, comma) in presenti:
            continue
        stesso_articolo = [f for f in precedenti if str(f.get("norma")) == norma
                           and _chiave_articolo(f.get("articolo")) == articolo]
        candidati = ([f for f in stesso_articolo if str(f.get("comma") or "-") == comma]
                     or stesso_articolo
                     or [f for f in precedenti if str(f.get("norma")) == norma][:1])
        for f in candidati[:1] if comma == "-" or not stesso_articolo else candidati:
            chiave = (f["norma"], f["articolo"], f["comma"])
            if chiave not in viste:
                viste.add(chiave)
                fonti.append(f)
            presenti.add((str(f["norma"]), _chiave_articolo(f["articolo"]), str(f["comma"] or "-")))


def rifinisci(testo, fonti, viste, precedenti=None):
    """La risposta come la vede l'utente: tutte le cure, sempre nello stesso ordine.

    La usano rispondi() dal vivo e il server quando ricostruisce una
    conversazione dal checkpoint: se divergessero, ricaricare la pagina
    cambierebbe le citazioni. `precedenti` sono le fonti dei turni prima di
    questo.
    """
    testo = RE_MARCATORE_SEMPLICE.sub(r"{{cita:\1}}", testo)
    _richiama_precedenti(testo, fonti, viste, precedenti)
    _aggiungi_fonti_d_atto(fonti, viste)
    testo = _senza_campi_interni(testo)
    testo = _ripara_marcatori(testo, fonti, viste)
    _fonti_atti_nominati(testo, fonti, viste)
    return _ancora_gli_atti(testo, fonti)


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
    # riferimento nominato in prosa senza articolo. rispondi() la aggiunge per
    # ogni atto consultato (_aggiungi_fonti_d_atto): ripiegare sulla prima
    # fonte etichettava la legge come "[art. 1]".
    # Le fonti stanno sotto (numero, anno) e poi sotto il prefisso: la prosa
    # dice il tipo, e fra LC-1-2012 e LQ-1-2012 decide quello.
    per_atto = {}
    for f in fonti:
        pezzi = str(f.get("norma") or "").split("-")
        if len(pezzi) < 3 or not pezzi[1].isdigit():
            continue
        stessi = per_atto.setdefault((str(int(pezzi[1])), pezzi[2].split("~")[0]), {})
        precedente = stessi.get(pezzi[0])
        migliore = (precedente is None
                    or (str(f.get("articolo")) == "-" and str(precedente[1]) != "-")
                    or ("~" not in str(f["norma"]) and "~" in str(precedente[0])))
        if migliore:
            stessi[pezzi[0]] = (f["norma"], f.get("articolo"), f.get("comma"))
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
            trovate.append((m.start(), m.end(), str(int(numero)), anno,
                            _prefisso_nominato(m.group(0))))
    trovate.sort()
    for k, (inizio, termine, numero, anno, prefisso) in enumerate(trovate):
        if inizio < fine:
            continue                      # gia' coperta da un aggancio precedente
        stessi = per_atto.get((numero, anno)) or {}
        if prefisso in stessi:
            rif = stessi[prefisso]
        elif prefisso is None and len(stessi) == 1:
            rif = next(iter(stessi.values()))
        else:
            continue                      # non fra le fonti: resta testo semplice
        # anche dopo uno spazio o la chiusura del grassetto: "L. 17/1974
        # {{cita:...}}" e "**L. 42/2010**{{cita:...}}" ne ricevevano due
        if re.match(r"[\s*_\"»)\]]*\{\{cita:", testo[termine:termine + 16]):
            continue                      # il modello l'ha gia' messo. Non si
                                          # avanza `fine`: il testo saltato deve
                                          # comunque finire nell'uscita, o la
                                          # prosa davanti al marcatore sparisce.
        # "**L. 1° marzo 2010 n.42 - L'Istituto del Trust**{{cita:L-42-2010:-:-}}":
        # il modello ha messo il marcatore dopo il titolo. Se nella stessa riga
        # ne arriva uno per lo stesso atto prima che se ne nomini un altro,
        # basta quello.
        riga = testo[termine:termine + 200].split("\n", 1)[0]
        dopo = riga.find("{{cita:" + rif[0] + ":")
        prossima = trovate[k + 1][0] - termine if k + 1 < len(trovate) else len(riga) + 1
        if 0 <= dopo < prossima:
            continue
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
                # La pagina del PDF dove l'articolo comincia, quando il testo
                # viene da un testo coordinato: il sito apre il documento li'.
                "pagina": r.get("paginaDocumento"),
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
                    "pagina": risultato.get("paginaDocumento"),
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
    # Le fonti dei turni precedenti: una domanda di seguito puo' rispondere
    # senza strumenti, citando cio' che e' stato letto prima.
    try:
        precedenti = fonti_della_storia(
            (agente().get_state(config).values or {}).get("messages", []))
    except Exception:
        precedenti = []
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
               "testo": rifinisci(SEPARATORE.join(blocchi_testo), fonti_raccolte, viste,
                                  precedenti)}

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
