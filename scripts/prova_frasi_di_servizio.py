"""Le frasi di servizio non arrivano all'utente: ne' nella bozza, ne' nel testo
finale, ne' in una conversazione riaperta. Nessuna chiamata di rete.

    .venv\\Scripts\\python.exe scripts\\prova_frasi_di_servizio.py

Il 02/10 DeepSeek ha aperto una risposta con «I'll search the archive for this
law and its provisions.» e «I found the law. Let me read the full text...»: il
prompt vieta di scrivere prima degli strumenti, il modello lo fa lo stesso, e
rispondi() metteva quelle frasi in testa alla risposta. Sui checkpoint di
produzione le scrivono il 28% delle chiamate di DeepSeek e tutte quelle di Haiku.
"""
import json
import os
import pathlib
import sys
from types import SimpleNamespace

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RADICE), str(RADICE / "src")]
os.environ["TABELLA_CHECKPOINT"] = ""
os.environ["TABELLA_SCRITTURE"] = ""
os.environ.setdefault("MODELLO", "deepseek-v4.1-flash")

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage  # noqa: E402

from agente import agente as A  # noqa: E402  (lo stesso modulo che usa server.py)

assert type(A._checkpointer()).__name__ == "InMemorySaver", "le prove userebbero i checkpoint veri"

MODELLO = {"langgraph_node": "model"}
PRIMA = "I'll search the archive for this law and its provisions."
SECONDA = "I found the law. Let me read the full text of the key articles and check the modifications."
RISPOSTA = ("Ecco cosa prevede la Legge 4 dicembre 2015 n. 178: prestito d'onore fino a 15.000 euro, "
            "aliquota IGR agevolata del 4% per i primi sei anni, sgravi contributivi del 50% e "
            "credito agevolato con interessi a carico dello Stato. ") * 4
LUNGA = ("Prima di rispondere verifico anche le modifiche successive e le norme collegate, "
         "perche' la legge e' stata ritoccata piu' volte negli anni. ") * 3
BREVE = "Si', la legge e' in vigore."


def risultato(articolo):
    return {"risultati": [{"normaId": "L-178-2015", "normaTitolo": "Legge 178/2015",
                           "articolo": articolo, "comma": "1", "testo": "..."}]}


def chiamata(id_, testo, strumento=None, a_pezzi=True, articolo="4"):
    """Gli eventi di una chiamata al modello, come li manda LangGraph in streaming."""
    eventi = []
    passo = max(1, len(testo) // 8)
    for i in range(0, len(testo), passo):
        eventi.append(("messages", (AIMessageChunk(content=testo[i:i + passo], id=id_), MODELLO)))
    chiamate = []
    if strumento:
        chiamate = [{"name": "cerca_testo", "args": {"q": "x"}, "id": strumento, "type": "tool_call"}]
        if a_pezzi:
            eventi.append(("messages", (AIMessageChunk(content="", id=id_, tool_call_chunks=[
                {"name": "cerca_testo", "args": '{"q": "x"}', "id": strumento, "index": 0}]), MODELLO)))
    # L'ultimo frammento porta solo l'uso dei token: vuoto, e con un id suo.
    eventi.append(("messages", (AIMessageChunk(
        content="", id=None if id_ is None else id_ + "-uso",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}), MODELLO)))
    eventi.append(("updates", {"model": {"messages": [AIMessage(content=testo, id=id_, tool_calls=chiamate)]}}))
    if strumento:
        eventi.append(("updates", {"tools": {"messages": [ToolMessage(
            content=json.dumps(risultato(articolo)), tool_call_id=strumento, name="cerca_testo")]}}))
    return eventi


class Grafo:
    """Sta al posto dell'agente: ripete gli eventi dati e una cronologia."""

    def __init__(self, eventi=(), storia=()):
        self.eventi, self.storia = list(eventi), list(storia)

    def stream(self, ingresso, config=None, stream_mode=None):
        yield from self.eventi

    def get_state(self, config):
        return SimpleNamespace(values={"messages": self.storia})


def esegui(eventi):
    A.agente = lambda nome=None: Grafo(eventi)
    return list(A.rispondi("domanda", "prova"))


def schermo(eventi):
    """Cio' che l'utente ha davanti dopo ogni evento, tenuto come fa useChat.ts."""
    testo, storia = "", []
    for e in eventi:
        if e["tipo"] == "bozza":
            testo = (e.get("testo") or "") if e.get("azzera") else testo + e["delta"]
        elif e["tipo"] == "testo":
            testo = e["testo"]
        storia.append((e["tipo"], testo))
    return storia


def finale(eventi):
    return next((e["testo"] for e in eventi if e["tipo"] == "testo"), None)


def ultima_bozza(eventi):
    return next((t for tipo, t in reversed(schermo(eventi)) if tipo == "bozza"), "")


errori = 0


def controlla(nome, ok, dettaglio=""):
    global errori
    errori += not ok
    print(f'  {"OK " if ok else "NO "} {nome:<66} {"" if ok else dettaglio}')


def mai_visto(eventi, frase):
    return not any(frase[:30] in t for _, t in schermo(eventi))


vero_agente, vero_rifinisci = A.agente, A.rifinisci
A.rifinisci = lambda testo, *a, **k: testo   # le cure del testo hanno le loro prove, e vanno in rete
try:
    print("La risposta del 02/10: due frasi in inglese prima degli strumenti")
    out = esegui(chiamata("r1", PRIMA, "c1") + chiamata("r2", SECONDA, "c2", articolo="7")
                 + chiamata("r3", RISPOSTA))
    controlla("le frasi di servizio non compaiono mai", mai_visto(out, PRIMA) and mai_visto(out, SECONDA))
    controlla("il testo finale e' solo la risposta", finale(out) == RISPOSTA.strip(), repr(finale(out))[:120])
    bozze = [e for e in out if e["tipo"] == "bozza"]
    controlla("la risposta arriva in bozza, a pezzi", sum(not b.get("azzera") for b in bozze) >= 2, str(len(bozze)))
    controlla("la bozza parte dall'inizio della risposta",
              next(t for tipo, t in schermo(out) if tipo == "bozza" and t).startswith("Ecco"))
    controlla("la bozza completa e' la risposta", ultima_bozza(out).strip() == RISPOSTA.strip())
    controlla("nessun ritiro: niente di sbagliato era in vista", not any(b.get("azzera") for b in bozze))
    controlla("gli strumenti e i risultati restano nell'avanzamento",
              [e["tipo"] for e in out if e["tipo"] in ("strumento", "risultato")]
              == ["strumento", "risultato", "strumento", "risultato"])

    print("\nUna frase di servizio piu' lunga della soglia")
    out = esegui(chiamata("r1", LUNGA, "c1") + chiamata("r2", RISPOSTA))
    controlla("si vede per un attimo...", not mai_visto(out, LUNGA))
    controlla("...e si ritira quando arriva lo strumento",
              any(e["tipo"] == "bozza" and e.get("azzera") and not e["testo"] for e in out))
    controlla("la bozza della risposta non la contiene", LUNGA[:30] not in ultima_bozza(out))
    controlla("il testo finale e' solo la risposta", finale(out) == RISPOSTA.strip())

    print("\nUn gateway che manda la chiamata allo strumento tutta insieme, alla fine")
    out = esegui(chiamata("r1", PRIMA, "c1", a_pezzi=False) + chiamata("r2", RISPOSTA))
    controlla("una frase breve non compare mai", mai_visto(out, PRIMA))
    controlla("il testo finale e' solo la risposta", finale(out) == RISPOSTA.strip())
    out = esegui(chiamata("r1", LUNGA, "c1", a_pezzi=False) + chiamata("r2", RISPOSTA))
    controlla("una frase lunga si ritira al messaggio completo",
              any(e["tipo"] == "bozza" and e.get("azzera") for e in out) and LUNGA[:30] not in ultima_bozza(out))
    controlla("il testo finale e' solo la risposta", finale(out) == RISPOSTA.strip())

    print("\nUn fornitore che non numera i frammenti")
    out = esegui(chiamata(None, PRIMA, "c1") + chiamata(None, RISPOSTA))
    controlla("la frase di servizio non compare", mai_visto(out, PRIMA))
    controlla("la risposta arriva comunque in bozza",
              sum(e["tipo"] == "bozza" and not e.get("azzera") for e in out) >= 2)
    controlla("il testo finale e' solo la risposta", finale(out) == RISPOSTA.strip())

    print("\nUna risposta breve, senza strumenti")
    out = esegui(chiamata("r1", BREVE))
    controlla("arriva intera nel testo finale", finale(out) == BREVE)
    controlla("il frammento dell'uso non ritira niente", not any(e.get("azzera") for e in out))

    print("\nI middleware che riscrivono messaggi VECCHI prima della domanda")
    vecchi = [("updates", {"PotaturaFraDomande.before_agent": {"messages": [ToolMessage(
                  content="risultato vecchio accorciato[...]", tool_call_id="vecchia", name="cerca_testo")]}}),
              ("updates", {"RiparaChiamateOrfane.before_agent": {"messages": [AIMessage(
                  content="Risposta di una domanda passata.", id="vecchia",
                  usage_metadata={"input_tokens": 9000, "output_tokens": 900, "total_tokens": 9900})]}})]
    out = esegui(vecchi + chiamata("r1", RISPOSTA))
    controlla("nessun risultato fantasma nell'avanzamento", not [e for e in out if e["tipo"] == "risultato"])
    controlla("il testo vecchio resta fuori", finale(out) == RISPOSTA.strip(), repr(finale(out))[:80])
    fine = next(e for e in out if e["tipo"] == "fine")
    controlla("i token vecchi non si ricontano", fine["tokenIn"] == 0, str(fine["tokenIn"]))

    print("\nUna conversazione riaperta")
    from fastapi.testclient import TestClient  # noqa: E402
    import server  # noqa: E402

    chiama = {"name": "cerca_testo", "args": {}, "type": "tool_call"}
    storia = [HumanMessage("Cosa prevede la legge 178/2015?", id="h1"),
              AIMessage(PRIMA, id="a1", tool_calls=[{**chiama, "id": "c1"}]),
              ToolMessage(json.dumps(risultato("4")), tool_call_id="c1", name="cerca_testo", id="t1"),
              AIMessage(SECONDA, id="a2", tool_calls=[{**chiama, "id": "c2"}]),
              ToolMessage(json.dumps(risultato("7")), tool_call_id="c2", name="cerca_testo", id="t2"),
              AIMessage(RISPOSTA, id="a3")]
    A.agente = lambda nome=None: Grafo(storia=storia)
    appartiene = server.archivio.appartiene
    server.archivio.appartiene = lambda *a: True
    server.app.dependency_overrides[server.utente_corrente] = lambda: SimpleNamespace(id="prova")
    try:
        messaggi = TestClient(server.app).get("/conversazioni/prova").json()["messaggi"]
    finally:
        server.archivio.appartiene = appartiene
        server.app.dependency_overrides.clear()
    controlla("una domanda e una risposta, niente frasi di servizio",
              [m["role"] for m in messaggi] == ["user", "assistant"], str([m["content"][:30] for m in messaggi]))
    controlla("la risposta e' quella vera", messaggi[-1]["content"].strip() == RISPOSTA.strip())
    controlla("le fonti di entrambi i giri stanno con la risposta",
              sorted(f["articolo"] for f in messaggi[-1]["fonti"]) == ["4", "7"],
              str([f["articolo"] for f in messaggi[-1]["fonti"]]))
finally:
    A.agente, A.rifinisci = vero_agente, vero_rifinisci

print("\nfallite:", errori)
sys.exit(1 if errori else 0)
