"""Le prove del tetto ai giri (ChiudiDopoTroppiGiri): quando la chiamata e'
l'ultima concessa il modello non puo' chiamare strumenti - sul gateway gli si
tolgono, su Anthropic tool_choice "none" - e le istruzioni chiedono di
rispondere. Nessuna chiamata di rete.

    .venv\\Scripts\\python.exe scripts\\prova_giri.py
"""
import os
import pathlib
import sys

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RADICE), str(RADICE / "src")]
os.environ["TABELLA_CHECKPOINT"] = ""
os.environ["TABELLA_SCRITTURE"] = ""

from langchain.agents.middleware.types import ModelRequest  # noqa: E402
from langchain_anthropic import ChatAnthropic  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from src.agente.agente import CHIUSURA, SPINTA_FINALE, ChiudiDopoTroppiGiri  # noqa: E402

GATEWAY = ChatOpenAI(model="deepseek-v4.1-flash", api_key="x", base_url="http://localhost:9")
CLAUDE = ChatAnthropic(model="claude-sonnet-5", api_key="x")
STRUMENTO = {"type": "function", "function": {"name": "cerca_testo", "parameters": {"type": "object"}}}


def giro(n):
    return [AIMessage("", tool_calls=[{"name": "cerca_testo", "args": {}, "id": f"c{n}", "type": "tool_call"}]),
            ToolMessage("risultato", tool_call_id=f"c{n}", name="cerca_testo")]


def richiesta(messaggi, modello=GATEWAY, sistema=SystemMessage("ISTRUZIONI"), strumenti=(STRUMENTO,)):
    return ModelRequest(model=modello, messages=messaggi, system_message=sistema, tools=list(strumenti))


errori = 0


def controlla(nome, ok, dettaglio=""):
    global errori
    errori += not ok
    print(f'  {"OK " if ok else "NO "} {nome:<62} {dettaglio}')


tetto = ChiudiDopoTroppiGiri(giri=3)
domanda = [HumanMessage("domanda")]

r = tetto.wrap_model_call(richiesta(domanda + giro(1)), lambda x: x)
controlla("seconda chiamata su tre: richiesta intatta", r.tool_choice is None and r.system_message.content == "ISTRUZIONI")

r = tetto.wrap_model_call(richiesta(domanda + giro(1) + giro(2)), lambda x: x)
controlla("terza chiamata su tre, gateway: strumenti tolti", r.tools == [], str(r.tools))
controlla("...le istruzioni chiedono di rispondere", r.system_message.content.endswith(CHIUSURA))
controlla("...e la spinta esplicita sta in coda (senza, DeepSeek li chiama lo stesso)",
          isinstance(r.messages[-1], HumanMessage) and r.messages[-1].content == SPINTA_FINALE
          and len(r.messages) == 6)

prima = [HumanMessage("vecchia")] + giro(1) + giro(2) + [AIMessage("risposta vecchia")]
r = tetto.wrap_model_call(richiesta(prima + [HumanMessage("nuova")] + giro(3)), lambda x: x)
controlla("i giri della domanda precedente non contano", r.tool_choice is None)

sistema_claude = SystemMessage(content=[{"type": "text", "text": "ISTRUZIONI", "cache_control": {"type": "ephemeral"}}])
r = tetto.wrap_model_call(richiesta(domanda + giro(1) + giro(2), modello=CLAUDE, sistema=sistema_claude), lambda x: x)
controlla("Anthropic: tool_choice in forma di dizionario", r.tool_choice == {"type": "none"}, str(r.tool_choice))
controlla("Anthropic: gli strumenti restano (senza, rifiuta la cronologia)", len(r.tools) == 1)
controlla("Anthropic: nessuna spinta in coda, basta tool_choice", len(r.messages) == 5)
controlla("Anthropic: il blocco in cache resta, la chiusura si aggiunge dopo",
          r.system_message.content[0].get("cache_control") == {"type": "ephemeral"}
          and r.system_message.content[-1]["text"] == CHIUSURA.strip())

r = tetto.wrap_model_call(richiesta(domanda + giro(1) + giro(2), strumenti=()), lambda x: x)
controlla("senza strumenti: nulla da chiudere", r.tool_choice is None)

print("\nfallite:", errori)
sys.exit(1 if errori else 0)
