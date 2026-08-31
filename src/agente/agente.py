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

1. **Ogni affermazione va ancorata a una fonte.** Cita sempre norma, articolo e comma
   nella forma "L. 87/2026, art. 7, comma 2". Non affermare nulla che non provenga dal
   risultato di uno strumento.

2. **Se non trovi, dillo.** Se gli strumenti non restituiscono nulla di pertinente,
   dichiara che l'archivio non contiene la risposta. Non colmare il vuoto con conoscenza
   generale sul diritto italiano o di altri ordinamenti: San Marino ha un ordinamento
   proprio e una risposta plausibile ma inventata è il danno peggiore.

3. **Distingui cosa c'è da cosa è solo citato.** L'archivio contiene il testo completo di
   alcune norme; altre compaiono solo perché citate (campo `testoDisponibile: false`).
   Se una norma rilevante non ha il testo, dillo apertamente: "la L. 59/1974 è richiamata
   ma il suo testo non è in archivio".

## Metodo

Parti quasi sempre da `cerca_testo` con parole chiave del linguaggio normativo. Quando un
articolo si rivela centrale, chiama `leggi_articolo` per averne il testo integrale prima
di rispondere: gli estratti della ricerca sono troncati.

**Per domande sulla struttura di una norma** - quanti articoli ha, com'è organizzata, di
cosa tratta l'articolo N - usa `struttura_norma`, che risponde in una sola chiamata.
Non leggere mai gli articoli uno per uno per contarli o per farti un'idea d'insieme.

Per domande su presupposti e rinvii usa `citazioni_da`; per l'impatto di una norma usa
`chi_cita`. Se l'utente chiede cosa contiene la banca dati, usa `elenco_norme`.

Puoi chiamare più strumenti in parallelo quando le richieste sono indipendenti.

## Forma della risposta

**Scrivi sempre e solo in italiano**, comprese le brevi frasi che precedono una chiamata
agli strumenti: l'utente le vede in tempo reale.

Rispondi in modo diretto e sostanziale. Apri con la risposta, non con un preambolo sul
metodo. Cita le fonti nel corpo del testo, dove servono. Riporta il testo normativo tra
virgolette quando la formulazione esatta conta.

Se la domanda è ambigua o troppo generica, rispondi comunque con quello che l'archivio
offre di più pertinente, e indica come restringere la ricerca.
"""

# Il checkpointer tiene le conversazioni in memoria di processo: si azzerano al
# riavvio del server. Per renderle durevoli si sostituisce con un checkpointer
# persistente (langchain_neo4j espone Neo4jSaver) senza toccare altro.
_memoria = InMemorySaver()
_agente = None


def agente():
    global _agente
    if _agente is None:
        modello = ChatAnthropic(
            model=MODELLO,
            max_tokens=16000,
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
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
