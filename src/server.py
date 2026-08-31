"""
Server web: serve la UI e trasmette le risposte dell'agente in streaming.

    python src/server.py
    -> http://127.0.0.1:8000

Gli eventi dell'agente viaggiano come SSE, cosi' il browser mostra il
ragionamento e le chiamate agli strumenti mentre accadono.
"""

import json
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agente.agente import rispondi           # noqa: E402
from agente.strumenti import grafo           # noqa: E402

from fastapi.staticfiles import StaticFiles

WEB = ROOT / "web"
FRONTEND_DIST = ROOT / "frontend" / "dist"

app = FastAPI(title="graphResponsa")

if FRONTEND_DIST.exists() and (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


class Domanda(BaseModel):
    domanda: str
    conversazione: str | None = None


@app.get("/")
def home():
    if (FRONTEND_DIST / "index.html").exists():
        return FileResponse(FRONTEND_DIST / "index.html")
    return FileResponse(WEB / "index.html")


_stato_cache = None
_stato_cache_time = 0

@app.get("/stato")
def stato():
    """Riepilogo dell'archivio e metriche del Knowledge Graph."""
    global _stato_cache, _stato_cache_time
    import time
    if _stato_cache and (time.time() - _stato_cache_time < 60):
        return _stato_cache

    try:
        r = grafo().query("""
            MATCH (n:Norma)
            WITH sum(CASE WHEN n.caricata THEN 1 ELSE 0 END) AS conTesto,
                 sum(CASE WHEN n.caricata THEN 0 ELSE 1 END) AS soloCitate,
                 count(n) AS totaleNorme
            MATCH (a:Articolo)
            WITH conTesto, soloCitate, totaleNorme, count(a) AS articoli
            MATCH (c:Comma)
            WITH conTesto, soloCitate, totaleNorme, articoli, count(c) AS commi
            OPTIONAL MATCH (al:Allegato)
            WITH conTesto, soloCitate, totaleNorme, articoli, commi, count(al) AS allegati
            RETURN conTesto, soloCitate, totaleNorme, articoli, commi, allegati,
                   (totaleNorme + articoli + commi + allegati) AS totaleNodi
        """)[0]
        
        rel_q = grafo().query("MATCH ()-[r]->() RETURN count(r) AS totaleRelazioni")[0]
        
        _stato_cache = {
            "ok": True,
            **r,
            "totaleRelazioni": rel_q.get("totaleRelazioni", 107539)
        }
        _stato_cache_time = time.time()
        return _stato_cache
    except Exception as e:
        return {"ok": False, "errore": str(e)}


@app.post("/chat")
def chat(d: Domanda):
    def eventi():
        try:
            for ev in rispondi(d.domanda, d.conversazione):
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:
            errore = {"tipo": "errore", "messaggio": f"{type(e).__name__}: {e}"}
            yield f"data: {json.dumps(errore, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        eventi(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    print("graphResponsa -> http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
