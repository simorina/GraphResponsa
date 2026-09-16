"""
Orchestratore della baseline "prima del fix" del parser.

Ri-scarica l'intero corpus dal portale (tutte le 8 categorie di ricerca),
lo riparsa con 02_parse.py cosi' com'e' oggi (nessuna modifica a regex o
logica), ed esegue 06_qa.py sul risultato. Non tocca data/raw|parsed
originali - qui non esistono nemmeno, su questa macchina - ne' il grafo
Neo4j: scrive tutto sotto cartelle *_baseline_<data>, cosi' l'esecuzione
"prima del fix" resta al sicuro e confrontabile con quella "dopo il fix".

E' pensato per girare per molte ore (l'archivio ha 11k+ documenti e lo
scraper rispetta un ritardo di cortesia verso un server istituzionale):
va lanciato in background e monitorato dal file di log.

Uso:
    .venv/Scripts/python.exe scripts/baseline_pipeline.py
"""

import importlib.util
import sys
import time
import traceback
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OGGI = date.today().isoformat()

RAW_BASE = ROOT / "data" / f"raw_baseline_{OGGI}"
PARSED_BASE = ROOT / "data" / f"parsed_baseline_{OGGI}"
QA_OUT = ROOT / "data" / f"qa_report_baseline_{OGGI}"
LOG = ROOT / "data" / f"baseline_{OGGI}.log"

# Le stesse 8 query usate altrove nel repo (scripts/verifica_archivio.py) per
# enumerare l'intero archivio: "+Decreto" da solo prende gia' tutti i suoi
# sottotipi (Delegato, Reggenziale, Consiliare, Legge), quindi non serve
# interrogarli separatamente.
TIPI = ["+Legge", "+Decreto", "+Regolamento", "+Notifica", "+Statuto",
        "+Verbale", "+Ordinanza", "+Errata AND +Corrige"]


def _log(msg):
    riga = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(riga, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(riga + "\n")


def _carica(nomefile, nomemodulo):
    spec = importlib.util.spec_from_file_location(nomemodulo, SRC / nomefile)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fase_scraping():
    RAW_BASE.mkdir(parents=True, exist_ok=True)
    sc = _carica("01_scrape.py", "scrape_baseline")
    # RAW e INDICE sono globali di modulo letti a runtime dalle funzioni:
    # sovrascriverli dopo l'import basta a redirigere tutto lo scraping qui,
    # senza toccare una riga di 01_scrape.py.
    sc.RAW = RAW_BASE
    sc.INDICE = RAW_BASE / "_indice.json"

    for tipo in TIPI:
        _log(f"=== scraping tipo={tipo!r} ===")
        try:
            sc.main(tipo=tipo)
        except Exception as e:
            _log(f"FALLITO tipo {tipo!r}: {type(e).__name__}: {e}")
            _log(traceback.format_exc())

    n = len(list(RAW_BASE.glob("*/testo.pdf")))
    _log(f"Scraping completato: {n} PDF scaricati in {RAW_BASE}")
    return n


def fase_parsing():
    PARSED_BASE.mkdir(parents=True, exist_ok=True)
    p02 = _carica("02_parse.py", "parse_baseline")
    p02.RAW = RAW_BASE
    p02.PARSED = PARSED_BASE
    _log("=== parsing (02_parse.py, nessuna modifica) ===")
    p02.main(force=True)
    n = len(list(PARSED_BASE.glob("*.json")))
    _log(f"Parsing completato: {n} file JSON in {PARSED_BASE}")
    return n


def fase_qa():
    _log("=== QA (06_qa.py) ===")
    qa = _carica("06_qa.py", "qa_baseline")
    qa.esegui(parsed_dir=PARSED_BASE, raw_dir=RAW_BASE, out_base=QA_OUT)
    _log(f"QA completata: {QA_OUT}.json / {QA_OUT}.md / {QA_OUT}.jsonl")


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    _log(f"Baseline avviata. RAW={RAW_BASE}  PARSED={PARSED_BASE}")
    inizio = time.time()

    n_raw = fase_scraping()
    if n_raw == 0:
        _log("ATTENZIONE: zero PDF scaricati, salto parsing e QA.")
        return

    fase_parsing()
    fase_qa()

    ore = (time.time() - inizio) / 3600
    _log(f"BASELINE COMPLETATA in {ore:.1f} ore.")


if __name__ == "__main__":
    main()
