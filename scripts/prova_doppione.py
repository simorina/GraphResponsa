"""Le prove del doppione (src/agente/doppione.py): chi vince, chi si chiude,
cosa succede agli errori. Il gateway e' sostituito da flussi finti a tempo.

    .venv\\Scripts\\python.exe scripts\\prova_doppione.py
"""
import os
import pathlib
import sys
import threading
import time

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RADICE), str(RADICE / "src")]
os.environ["TABELLA_CHECKPOINT"] = ""
os.environ["TABELLA_SCRITTURE"] = ""

from langchain_core.messages import AIMessageChunk  # noqa: E402
from langchain_core.outputs import ChatGenerationChunk  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from src.agente.doppione import ChatConDoppione  # noqa: E402

# Il piano delle richieste: per ciascuna, dopo quanto arriva il primo frammento,
# quali frammenti, e se cade con un errore. Le richieste lo consumano in ordine.
piano = []
aperte, chiuse = [], []
lucchetto = threading.Lock()


def finto_stream(self, messages, stop=None, run_manager=None, **kwargs):
    with lucchetto:
        n = len(aperte)
        ritardo, pezzi, errore = piano[n]
        aperte.append(n)
    try:
        time.sleep(ritardo)
        if errore:
            raise errore
        for p in pezzi:
            yield ChatGenerationChunk(message=AIMessageChunk(content=f"{n}:{p}"))
            time.sleep(0.02)
    finally:
        with lucchetto:
            chiuse.append(n)


ChatOpenAI._stream = finto_stream
modello = ChatConDoppione(model="finto", api_key="x", base_url="http://localhost:9", ritardo_doppione=0.3)


def leggi():
    return [c.message.content for c in modello._stream([])]


def prepara(*richieste):
    piano[:] = list(richieste)
    aperte.clear()
    chiuse.clear()


errori = 0


def controlla(nome, ok, dettaglio=""):
    global errori
    errori += not ok
    print(f'  {"OK " if ok else "NO "} {nome:<60} {dettaglio}')


prepara((0.05, ["ciao", " mondo"], None))
t0 = time.perf_counter()
esito = leggi()
controlla("rapida: una sola richiesta, nessun doppione", aperte == [0] and esito == ["0:ciao", "0:mondo"][:1] + ["0: mondo"], esito)

prepara((1.2, ["lenta"], None), (0.1, ["rapida", " davvero"], None))
t0 = time.perf_counter()
esito = leggi()
durata = time.perf_counter() - t0
controlla("la prima tarda: parte il doppione e vince", esito == ["1:rapida", "1: davvero"], esito)
controlla("...e non si aspetta la lenta", durata < 0.9, f"{durata:.2f}s")
time.sleep(1.2)
controlla("...la lenta si chiude appena risponde", 0 in chiuse, str(chiuse))

prepara((0.5, ["prima"], None), (2.0, ["seconda"], None))
esito = leggi()
controlla("doppione partito ma la prima arriva prima: vince la prima", esito == ["0:prima"], esito)

prepara((0.05, [], RuntimeError("data_inspection_failed")))
try:
    leggi()
    ok = False
except RuntimeError as e:
    ok = "data_inspection_failed" in str(e)
controlla("errore subito: si propaga, nessun doppione", ok and aperte == [0], str(aperte))

prepara((0.5, [], RuntimeError("rete")), (0.2, ["salva"], None))
esito = leggi()
controlla("la prima cade dopo la scadenza: il doppione salva", esito == ["1:salva"], esito)

prepara((0.5, [], RuntimeError("primo errore")), (0.6, [], RuntimeError("secondo errore")))
try:
    leggi()
    ok = False
except RuntimeError as e:
    ok = str(e) == "primo errore"
controlla("cadono entrambe: si propaga l'errore della prima", ok)

prepara((0.05, [], None))
controlla("risposta vuota: nessun frammento, nessun errore", leggi() == [])

prepara((0.05, ["a", "b", "c", "d"], None))
flusso = modello._stream([])
next(flusso)
flusso.close()
time.sleep(0.2)
controlla("chi legge smette a meta': la richiesta si chiude", 0 in chiuse, str(chiuse))

spento = ChatConDoppione(model="finto", api_key="x", base_url="http://localhost:9", ritardo_doppione=0)
prepara((0.5, ["unica"], None), (0.0, ["mai"], None))
controlla("ritardo 0: doppione spento", [c.message.content for c in spento._stream([])] == ["0:unica"] and aperte == [0])

print("\nfallite:", errori)
sys.exit(1 if errori else 0)
