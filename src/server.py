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
import logging
import mimetypes
import sys
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agente.agente import rispondi, nuova_conversazione   # noqa: E402
from agente.strumenti import grafo, url_documento         # noqa: E402
from servizio import archivio                             # noqa: E402
from servizio.identita import Utente, utente_corrente     # noqa: E402

from fastapi.staticfiles import StaticFiles

WEB = ROOT / "web"
FRONTEND_DIST = ROOT / "frontend" / "dist"

registro = logging.getLogger("graphresponsa")

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


# ------------------------------------------------------------------ documenti

@app.get("/documenti/{norma_id}")
def documento(norma_id: str):
    """
    Proxy verso il PDF originale della norma sul portale del Consiglio Grande
    e Generale, senza autenticazione: sono atti pubblici, e a differenza di
    /chat non spendono la chiave Anthropic, quindi non c'e' conto da proteggere.

    Il portale marca la risposta `Content-Disposition: attachment`: il browser
    la scarica invece di mostrarla. Qui si rilegge il file e lo si re-inoltra
    con `inline`, cosi' si apre nel visualizzatore PDF del browser.
    """
    url = url_documento(norma_id)
    if not url:
        raise HTTPException(status_code=404,
                            detail="Documento non disponibile per questa norma.")

    try:
        richiesta = urllib.request.Request(
            url, headers={"User-Agent": "graphResponsa/1.0"})
        risposta = urllib.request.urlopen(richiesta, timeout=20)
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502,
                            detail=f"Portale del Consiglio non raggiungibile: {e}")

    tipo = risposta.headers.get_content_type() or "application/pdf"

    # Quasi sempre e' un PDF - verificato su tutte le 11.134 norme con
    # documento, il campione serve application/pdf da 18 a 209 KB - ma non
    # sempre: gli atti con allegati arrivano impacchettati, e L-171-2022 rende
    # 17,7 MB di application/download_zip. Un archivio chiamato .pdf e servito
    # `inline` lascia il browser a fissare byte che non sa disegnare, quindi
    # solo il PDF si apre nel visualizzatore: il resto si scarica, col suo nome.
    ESTENSIONI = {"application/pdf": ".pdf", "application/download_zip": ".zip",
                  "application/zip": ".zip", "application/x-zip-compressed": ".zip"}
    estensione = ESTENSIONI.get(tipo) or mimetypes.guess_extension(tipo) or ".pdf"
    disposizione = "inline" if tipo == "application/pdf" else "attachment"

    def a_pezzi():
        # Non l'intero file in memoria: un allegato puo' pesare diversi MB, e
        # ogni richiesta concorrente terrebbe una copia completa piu' un
        # thread del pool per tutta la durata del download.
        with risposta:
            while pezzo := risposta.read(65536):
                yield pezzo

    return StreamingResponse(
        a_pezzi(), media_type=tipo,
        headers={"Content-Disposition":
                 f'{disposizione}; filename="{norma_id}{estensione}"',
                 "Cache-Control": "public, max-age=86400"})


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
                    # Una citazione che nessuno strumento ha restituito e' un
                    # atto che il modello non ha letto. Va a giornale perche'
                    # e' l'unico difetto di qualita' misurabile senza un
                    # giudizio umano: o quella norma e' stata consultata, o no.
                    sospette = ev.get("citazioniNonVerificate") or []
                    if sospette:
                        registro.warning(
                            "citazioni non verificate conversazione=%s: %s",
                            conversazione, ", ".join(sospette))
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
