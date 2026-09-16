"""
Intestazioni d'articolo che RE_ARTICOLO non riconosce, su tutto il corpus S3,
raggruppate per variante.

Una riga conta solo se il suo numero e' il successivo dell'ultima intestazione
vista (riconosciuta o candidata), e solo prima della formula di promulgazione:
cosi' "Art. 24 della legge ..." dentro il testo e gli articoli di un allegato
non entrano nel conteggio. Il criterio "B" di riclassifica_1_4_e_problema9.py
contava invece anche le intestazioni gia' riconosciute, e dava quasi solo
falsi positivi.

Uso:
    .venv/Scripts/python.exe scripts/diag_varianti.py [--out data/diag_varianti_art.json]
"""
import argparse
import json
import random
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
_argv, sys.argv = sys.argv, sys.argv[:1]
import baseline_from_s3 as b  # noqa: E402  (applica il monkeypatch S3)
sys.argv = _argv

RE_ARTICOLO = b.p02.RE_ARTICOLO
BASE = re.compile(r"^Art(?:icolo)?(\.?)\s*(\d+)(.*)$", re.I)
SUFF = r"(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies)"
VARIANTI = [
    ("nota", re.compile(r"^\.?\s*(?:" + SUFF + r"\.?\s*)?\(\d+\)\s*[-:.]?\s*$", re.I)),
    ("grado", re.compile(r"^\s*[°º]", re.I)),
    ("slash", re.compile(r"^\s*/\s*\d+")),
    ("trattino_bis", re.compile(r"^\s*-\s*" + SUFF + r"\b", re.I)),
    ("vuota_senza_punto", re.compile(r"^\s*(?:" + SUFF + r")?\s*[-:.]?\s*$", re.I)),
    # rubrica o testo sulla stessa riga: dopo il numero, maiuscola o parentesi
    ("inline", re.compile(r"^\s*(?:" + SUFF + r"\s*)?(?:[-–.:]\s*|\s+)[-–]?\s*[A-ZÀ-Ý(«\"]")),
]


def scansiona(nid):
    righe = b._righe_pdf_s3(f"raw/{nid}/testo.pdf")
    b._cache.pop(f"raw/{nid}/testo.pdf", None)
    prev, trovati = 0, []
    for i, r in enumerate(righe):
        s = r.strip()
        if prev and b.p02._cerca_promulgazione(righe, i):
            break
        m_ok = RE_ARTICOLO.match(s)
        if m_ok:
            if m_ok.group(1).isdigit():
                prev = int(m_ok.group(1))
            continue
        m = BASE.match(s)
        if not m or not s.startswith("A"):
            continue
        n, resto = int(m.group(2)), m.group(3)
        if n != prev + 1:
            continue
        var = next((k for k, rx in VARIANTI if rx.match(resto)), None)
        if var == "vuota_senza_punto" and m.group(1):
            var = None
        if var is None:
            continue
        trovati.append((var, s[:90]))
        prev = n
    return nid, trovati


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "diag_varianti_art.json"))
    ap.add_argument("--worker", type=int, default=24)
    args = ap.parse_args()

    per = defaultdict(list)
    docs = set()
    with ThreadPoolExecutor(args.worker) as ex:
        for nid, tr in ex.map(scansiona, b.elenco_documenti()):
            for v, s in tr:
                per[v].append((nid, s))
                docs.add(nid)
    print("documenti con almeno una intestazione mancata:", len(docs))
    random.seed(7)
    for v, l in sorted(per.items(), key=lambda kv: -len(kv[1])):
        print(f"\n=== {v}: {len(l)} occorrenze, {len({x[0] for x in l})} documenti")
        for nid, s in random.sample(l, min(15, len(l))):
            print(f"  {nid} | {s}")
    Path(args.out).write_text(json.dumps(per, ensure_ascii=False), encoding="utf-8")
    print("\n", args.out)


if __name__ == "__main__":
    main()
