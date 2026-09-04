"""
Server web: serve la UI e trasmette le risposte dell'agente in streaming.

    python src/server.py
    -> http://127.0.0.1:8000

Gli eventi dell'agente viaggiano come SSE, cosi' il browser mostra il
ragionamento e le chiamate agli strumenti mentre accadono.

In produzione sta dietro CloudFront, l'identita' arriva da Cognito e lo stato
applicativo da DynamoDB. In locale, senza quelle variabili d'ambiente, tutto
degrada a vuoto e il server continua a funzionare da solo.
"""

import json
import sys
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agente.agente import rispondi, nuova_conversazione   # noqa: E402
from agente.strumenti import grafo                        # noqa: E402
from servizio import archivio                             # noqa: E402
from servizio.identita import Utente, utente_corrente     # noqa: E402

from fastapi.staticfiles import StaticFiles

WEB = ROOT / "web"
FRONTEND_DIST = ROOT / "frontend" / "dist"

app = FastAPI(title="graphResponsa")

if FRONTEND_DIST.exists() and (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


class Domanda(BaseModel):
    domanda: str
    conversazione: str | None = None


class Riscontro(BaseModel):
    conversazione: str
    indiceMessaggio: int
    giudizio: str = Field(pattern="^(utile|non_utile)$")
    motivo: str = ""
    categorie: list[str] = []
    domanda: str = ""
    estrattoRisposta: str = ""
    fonti: list[str] = []


# --------------------------------------------------------------- diagnostica

@app.get("/salute")
def salute():
    """
    Sonda per il bilanciatore. Non interroga Neo4j di proposito.

    Se l'health check dipendesse da Aura, un suo singhiozzo farebbe uccidere e
    ricreare i container in ciclo: un problema del database diventerebbe
    un'interruzione totale del servizio. Qui si risponde alla sola domanda che
    interessa all'ALB, cioe' se il processo e' vivo.
    """
    return {"ok": True}


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

        rel = grafo().query("MATCH ()-[r]->() RETURN count(r) AS totaleRelazioni")[0]

        _stato_cache = {"ok": True, **r, **rel}
        _stato_cache_time = time.time()
        return _stato_cache
    except Exception as e:
        return {"ok": False, "errore": str(e)}


# ---------------------------------------------------------------- consultazione

@app.post("/chat")
def chat(d: Domanda, utente: Utente = Depends(utente_corrente)):
    archivio.registra_accesso(utente)

    # I tetti si verificano PRIMA di chiamare Anthropic: dopo sarebbe inutile,
    # i soldi sono gia' spesi.
    rifiuto = archivio.verifica_limiti(utente.id)
    if rifiuto:
        raise HTTPException(status_code=429, detail=rifiuto)

    conversazione = d.conversazione or nuova_conversazione()

    # Una conversazione si continua solo se e' tua: senza questo controllo, un
    # identificativo indovinato aprirebbe le consultazioni di chiunque.
    if d.conversazione and not archivio.appartiene(utente.id, d.conversazione):
        raise HTTPException(status_code=403, detail="Conversazione non tua.")

    archivio.annota_conversazione(utente.id, conversazione, d.domanda)

    def eventi():
        try:
            for ev in rispondi(d.domanda, conversazione):
                if ev.get("tipo") == "fine":
                    # I consumi erano gia' calcolati per mostrarli nella UI, e
                    # venivano buttati. Qui restano, e alimentano i tetti.
                    archivio.registra_consumo(
                        utente.id, ev.get("tokenIn", 0), ev.get("tokenOut", 0),
                        float(ev.get("costo", 0)))
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:
            errore = {"tipo": "errore", "messaggio": f"{type(e).__name__}: {e}"}
            yield f"data: {json.dumps(errore, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        eventi(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -------------------------------------------------------------------- riscontro

@app.post("/riscontro")
def riscontro(r: Riscontro, utente: Utente = Depends(utente_corrente)):
    """
    Registra il giudizio su una risposta.

    Idempotente sulla coppia conversazione + indice: ripensarci sovrascrive,
    non accumula. Salva anche domanda, estratto e fonti, perche' fra un mese un
    record che dice solo «non utile» non e' analizzabile - e i checkpoint
    saranno scaduti.
    """
    if not archivio.appartiene(utente.id, r.conversazione):
        raise HTTPException(status_code=403, detail="Conversazione non tua.")

    archivio.salva_riscontro(
        utente_id=utente.id, conversazione=r.conversazione, indice=r.indiceMessaggio,
        giudizio=r.giudizio, motivo=r.motivo, categorie=r.categorie,
        domanda=r.domanda, estratto=r.estrattoRisposta, fonti=r.fonti)
    return {"ok": True}


# ----------------------------------------------------------------- conversazioni

@app.get("/conversazioni")
def conversazioni(utente: Utente = Depends(utente_corrente)):
    return {
        "conversazioni": archivio.elenca_conversazioni(utente.id),
        "consumi": archivio.consumi_correnti(utente.id),
        "utente": {"nome": utente.nome, "email": utente.email},
    }


@app.get("/conversazioni/{conversazione}")
def conversazione(conversazione: str, utente: Utente = Depends(utente_corrente)):
    """
    Ricostruisce i messaggi dal checkpoint.

    Non si rilegge da una copia in DynamoDB: i messaggi vivono nei checkpoint di
    LangGraph, e duplicarli creerebbe due verita' che prima o poi divergono.
    """
    if not archivio.appartiene(utente.id, conversazione):
        raise HTTPException(status_code=403, detail="Conversazione non tua.")

    from agente.agente import agente
    stato = agente().get_state({"configurable": {"thread_id": conversazione}})
    messaggi = []
    for m in (stato.values or {}).get("messages", []):
        ruolo = {"human": "user", "ai": "assistant"}.get(getattr(m, "type", ""), None)
        if not ruolo:
            continue
        contenuto = m.content
        if isinstance(contenuto, list):
            contenuto = "".join(b.get("text", "") for b in contenuto
                                if isinstance(b, dict) and b.get("type") == "text")
        if contenuto:
            messaggi.append({"role": ruolo, "content": contenuto})
    return {"conversazione": conversazione, "messaggi": messaggi}


if __name__ == "__main__":
    print("graphResponsa -> http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
