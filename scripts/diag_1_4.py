"""
Ricontrollo dei casi "B" (vero collasso, 1.4 corretto) di
riclassifica_1_4_e_problema9: quali hanno ancora commi anomali in un report
QA piu' recente, e quali righe "Art..." del PDF il parser non ha preso come
intestazione. Una lista vuota sotto un documento significa che il comma e'
solo lungo, non collassato.

Uso:
    .venv/Scripts/python.exe scripts/diag_1_4.py \
        --riclassifica data/riclassifica_1_4_e_problema9_2026-09-16.json \
        --qa data/qa_report_fix11_2026-09-17.jsonl
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
_argv, sys.argv = sys.argv, sys.argv[:1]
import baseline_from_s3 as b  # noqa: E402  (applica il monkeypatch S3)
sys.argv = _argv

RE_ART = re.compile(r"^Art(?:icolo)?\.?\s*(\d+)", re.I)


def esamina(nid, lunghi):
    meta = json.loads(b._s3.get_object(Bucket=b.BUCKET, Key=f"raw/{nid}/scheda.json")["Body"].read())
    dati = b.p02.parse(nid, meta)
    righe, _ = b._cache.pop(f"raw/{nid}/testo.pdf")
    out = [f"\n##### {nid}  commi lunghi: "
           f"{[(c['commaId'].split('/', 1)[1], c['lunghezza']) for c in lunghi]}"
           f"  articoli prodotti: {len(dati['articoli'])}"]
    for i, r in enumerate(righe):
        s = r.strip()
        if RE_ART.match(s) and not b.p02.RE_ARTICOLO.match(s):
            ctx = " ⏎ ".join(t.strip() for t in righe[i:i + 3] if t.strip())
            out.append(f"  r{i}: {ctx[:150]}")
    return "\n".join(out[:25])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--riclassifica", required=True)
    ap.add_argument("--qa", required=True, help="report .jsonl di baseline_from_s3.py")
    args = ap.parse_args()

    ricl = json.loads(Path(args.riclassifica).read_text(encoding="utf-8"))
    casi_b = [x["id"] for x in ricl["dettaglio_1_4"] if x["causa"] == "B"]
    with open(args.qa, encoding="utf-8") as f:
        qa = {d["id"]: d for d in map(json.loads, f)}
    ancora = [nid for nid in casi_b if qa[nid]["commi_lunghi"]]
    print(f"B: {len(casi_b)}, ancora anomali: {len(ancora)}")
    with ThreadPoolExecutor(16) as ex:
        for s in ex.map(lambda n: esamina(n, qa[n]["commi_lunghi"]), ancora):
            print(s)


if __name__ == "__main__":
    main()
