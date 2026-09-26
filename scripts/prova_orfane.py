"""Le prove della riparazione delle chiamate a strumenti rimaste senza risultato.

    .venv\\Scripts\\python.exe scripts\\prova_orfane.py

Non tocca ne' il grafo ne' le API: controlla i messaggi nella forma in cui
langchain_anthropic li spedirebbe. Il caso vero, 26/09: una consultazione del
22/09 si era interrotta dopo che Sonnet aveva chiesto tre strumenti, e da quel
momento ogni domanda nella stessa conversazione tornava con un 400 di
Anthropic ("tool_use ids were found without tool_result blocks").
"""
import os
import pathlib
import sys

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RADICE), str(RADICE / "src")]
os.environ["TABELLA_CHECKPOINT"] = ""
os.environ["TABELLA_SCRITTURE"] = ""

from langchain_anthropic.chat_models import _format_messages    # noqa: E402
from langchain_core.messages import (AIMessage, HumanMessage,    # noqa: E402
                                     ToolMessage)
from langgraph.graph.message import add_messages                 # noqa: E402

from src.agente.agente import RiparaChiamateOrfane               # noqa: E402


def chiamata(id_, nome="cerca_testo"):
    return {"name": nome, "args": {"query": "armi"}, "id": id_, "type": "tool_call"}


def blocco(id_, nome="cerca_testo"):
    return {"type": "tool_use", "id": id_, "name": nome, "input": {"query": "armi"}}


def orfane_per_anthropic(messaggi):
    """I tool_use senza tool_result nel messaggio successivo: cio' che Anthropic
    rifiuta con il 400."""
    _, formattati = _format_messages(messaggi)
    orfane = []
    for i, m in enumerate(formattati):
        if m["role"] != "assistant" or not isinstance(m["content"], list):
            continue
        usi = {b["id"] for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"}
        dopo = formattati[i + 1]["content"] if i + 1 < len(formattati) else []
        risposte = {b.get("tool_use_id") for b in dopo if isinstance(b, dict)} if isinstance(dopo, list) else set()
        orfane += sorted(usi - risposte)
    return orfane


def vuoti_per_anthropic(messaggi):
    """I messaggi senza contenuto, che Anthropic rifiuta anch'essi."""
    _, formattati = _format_messages(messaggi)
    return [i for i, m in enumerate(formattati) if not m["content"]]


def ripara(messaggi):
    """Come fa il grafo: il middleware restituisce un aggiornamento, e il
    riduttore dei messaggi lo applica."""
    aggiornamento = RiparaChiamateOrfane().before_agent({"messages": messaggi}, None)
    return add_messages(messaggi, aggiornamento["messages"]) if aggiornamento else messaggi


# Il caso vero: Sonnet chiede tre strumenti, la consultazione si interrompe, e
# arrivano altre domande.
SONNET_INTERROTTO = [
    HumanMessage("questa e' la legge piu' recente o ce ne sono altre", id="h1"),
    AIMessage(content=[{"type": "text", "text": "Verifico."}, blocco("toolu_A"), blocco("toolu_B"),
                       blocco("toolu_C")],
              tool_calls=[chiamata("toolu_A"), chiamata("toolu_B"), chiamata("toolu_C")], id="a1"),
    HumanMessage("Quali agevolazioni prevede la Legge 178/2015?", id="h2"),
]

# Senza testo: dopo la riparazione il messaggio resterebbe vuoto.
SOLO_CHIAMATE = [
    HumanMessage("domanda", id="h1"),
    AIMessage(content=[blocco("toolu_A")], tool_calls=[chiamata("toolu_A")], id="a1"),
    HumanMessage("altra domanda", id="h2"),
]

# Due chiamate in parallelo, una sola risposta arrivata.
META_RISPOSTE = [
    HumanMessage("domanda", id="h1"),
    AIMessage(content=[blocco("toolu_A"), blocco("toolu_B")],
              tool_calls=[chiamata("toolu_A"), chiamata("toolu_B")], id="a1"),
    ToolMessage("risultato A", tool_call_id="toolu_A", name="cerca_testo", id="t1"),
    HumanMessage("altra domanda", id="h2"),
]

# DeepSeek, dal gateway compatibile OpenAI: il contenuto e' una stringa e le
# chiamate stanno anche in additional_kwargs.
DEEPSEEK_INTERROTTO = [
    HumanMessage("domanda", id="h1"),
    AIMessage(content="", tool_calls=[chiamata("call_1")], id="a1",
              additional_kwargs={"tool_calls": [{"id": "call_1", "type": "function",
                                                 "function": {"name": "cerca_testo",
                                                              "arguments": "{}"}}]}),
    HumanMessage("altra domanda", id="h2"),
]

# Una consultazione sana: nulla da toccare.
SANA = [
    HumanMessage("domanda", id="h1"),
    AIMessage(content=[blocco("toolu_A")], tool_calls=[chiamata("toolu_A")], id="a1"),
    ToolMessage("risultato", tool_call_id="toolu_A", name="cerca_testo", id="t1"),
    AIMessage("Risposta.", id="a2"),
    HumanMessage("altra domanda", id="h2"),
]

# Chiamate dopo l'ultima domanda: sono quelle in corso, e non si toccano.
IN_CORSO = [
    HumanMessage("domanda", id="h1"),
    AIMessage(content=[blocco("toolu_A")], tool_calls=[chiamata("toolu_A")], id="a1"),
]


def prova():
    errori = 0

    def controlla(nome, ok, dettaglio=""):
        nonlocal errori
        errori += not ok
        print(f'  {"OK " if ok else "NO "} {nome:<52} {dettaglio}')

    controlla("il caso vero fa il 400 senza riparazione",
              orfane_per_anthropic(SONNET_INTERROTTO) == ["toolu_A", "toolu_B", "toolu_C"],
              orfane_per_anthropic(SONNET_INTERROTTO))
    riparati = ripara(SONNET_INTERROTTO)
    controlla("riparato: nessun tool_use orfano", not orfane_per_anthropic(riparati),
              orfane_per_anthropic(riparati))
    controlla("riparato: il testo del modello resta",
              "Verifico." in str(riparati[1].content))
    controlla("riparato: stesso posto, stesso id, stesse domande",
              [m.id for m in riparati] == ["h1", "a1", "h2"])

    riparati = ripara(SOLO_CHIAMATE)
    controlla("senza testo: nessun orfano e nessun messaggio vuoto",
              not orfane_per_anthropic(riparati) and not vuoti_per_anthropic(riparati),
              f"{orfane_per_anthropic(riparati)} {vuoti_per_anthropic(riparati)}")

    riparati = ripara(META_RISPOSTE)
    controlla("parallele: resta la chiamata con la risposta",
              not orfane_per_anthropic(riparati)
              and [c["id"] for c in riparati[1].tool_calls] == ["toolu_A"],
              [c["id"] for c in riparati[1].tool_calls])

    riparati = ripara(DEEPSEEK_INTERROTTO)
    controlla("DeepSeek: tolte anche da additional_kwargs",
              not riparati[1].tool_calls and not riparati[1].additional_kwargs.get("tool_calls")
              and bool(riparati[1].content))

    controlla("consultazione sana: nessun aggiornamento",
              RiparaChiamateOrfane().before_agent({"messages": SANA}, None) is None)
    controlla("chiamate in corso dopo l'ultima domanda: intatte",
              RiparaChiamateOrfane().before_agent({"messages": IN_CORSO}, None) is None)

    print("\nfallite:", errori)
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(prova())
