"""
Baseline "prima del fix" leggendo il corpus direttamente da S3, in streaming,
senza mai scrivere PDF o JSON grezzi su disco.

Bucket: graphresponsa-archivio-392900064778
  raw/<id>/testo.pdf      - PDF originale (quello che 02_parse.py legge)
  raw/<id>/scheda.json    - metadati (quello che main() passa a parse() come meta)

Per ogni documento: si scaricano in memoria PDF + scheda, si rilanciano le
righe attraverso 02_parse.py::parse() COSI' COM'E' OGGI (nessuna riga di
02_parse.py viene toccata: si sostituisce solo la funzione righe_pdf() con una
versione che legge da bytes invece che da un path locale, stesso identico
comportamento), e si passano righe+risultato a 06_qa.py::analizza_documento()
per calcolare le metriche. I bytes vengono scartati subito dopo.

Sul disco restano solo i tre file di report finali (pochi MB), non il corpus.

Richiede in .env: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION.

Uso:
    .venv/Scripts/python.exe scripts/baseline_from_s3.py
    .venv/Scripts/python.exe scripts/baseline_from_s3.py --limite 200   # prova veloce
"""

import argparse
import importlib.util
import json
import sys
import time
import traceback
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path, PurePosixPath

import boto3
import fitz
import urllib3
from dotenv import load_dotenv

# pip-system-certs/truststore verifica i certificati contro lo store di
# Windows (necessario qui: un filtro TLS aziendale intercetta l'HTTPS e il
# bundle CA di default di Python non lo conosce). urllib3 pero' ispeziona
# l'attributo verify_mode del contesto SSL per decidere se avvisare, e
# truststore non lo valorizza come si aspetta - da cui il warning, anche se
# la verifica avviene comunque (confermato: un certificato self-signed non
# valido viene correttamente rifiutato). E' un falso positivo noto, si
# silenzia solo il rumore, non la verifica.
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OGGI = date.today().isoformat()
BUCKET = "graphresponsa-archivio-392900064778"

load_dotenv(ROOT / ".env")


def _carica(nomefile, nomemodulo):
    spec = importlib.util.spec_from_file_location(nomemodulo, SRC / nomefile)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


p02 = _carica("02_parse.py", "parse02_s3")
qa = _carica("06_qa.py", "qa06_s3")

# Solo per costruire chiavi S3 nella stessa forma "raw/<id>/testo.pdf" che usa
# gia' 02_parse.py con Path locali: PurePosixPath supporta "/" senza toccare
# il filesystem.
p02.RAW = PurePosixPath("raw")

_s3 = boto3.client("s3")

# parse() chiama righe_pdf() UNA sola volta per documento: si intercetta quella
# singola chiamata e si mettono da parte anche le righe (non solo le pagine),
# cosi' analizza_documento() le riusa subito dopo senza un secondo GET su S3.
_cache = {}  # chiave S3 -> (righe, pagine)


def _righe_pdf_s3(chiave_posix):
    """Sostituisce 02_parse.righe_pdf(): stessa logica (fitz, get_text, split
    su \\n, rstrip), ma legge i byte da S3 invece che da un file locale."""
    chiave = str(chiave_posix)
    obj = _s3.get_object(Bucket=BUCKET, Key=chiave)
    data = obj["Body"].read()
    doc = fitz.open(stream=data, filetype="pdf")
    pagine = len(doc)
    righe = [r.rstrip() for pagina in doc for r in pagina.get_text().split("\n")]
    doc.close()
    _cache[chiave] = (righe, pagine)
    return righe


p02.righe_pdf = _righe_pdf_s3


def elenco_documenti(limite=None):
    """Id norma per ogni raw/<id>/testo.pdf presente nel bucket."""
    paginator = _s3.get_paginator("list_objects_v2")
    ids = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix="raw/"):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if k.endswith("/testo.pdf"):
                ids.append(k[len("raw/"):-len("/testo.pdf")])
    ids.sort()
    return ids[:limite] if limite else ids


def elabora_uno(nid):
    chiave_pdf = f"raw/{nid}/testo.pdf"
    try:
        meta_obj = _s3.get_object(Bucket=BUCKET, Key=f"raw/{nid}/scheda.json")
        meta = json.loads(meta_obj["Body"].read().decode("utf-8"))

        dati = p02.parse(nid, meta)  # unico GET del PDF, via righe_pdf_s3
        righe, pagine = _cache.pop(chiave_pdf, (None, None))

        m = qa.analizza_documento(nid, dati, righe, pagine)
        return nid, m, None
    except Exception as e:
        return nid, None, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=None, help="solo i primi N documenti (prova veloce)")
    ap.add_argument("--worker", type=int, default=16)
    ap.add_argument("--out", default=str(ROOT / "data" / f"qa_report_baseline_{OGGI}"))
    args = ap.parse_args()

    out_base = Path(args.out)
    out_base.parent.mkdir(parents=True, exist_ok=True)

    print("Elenco documenti dal bucket...", flush=True)
    ids = elenco_documenti(args.limite)
    print(f"{len(ids)} documenti da analizzare (worker={args.worker})\n", flush=True)

    risultati, errori = [], []
    inizio = time.time()
    jsonl_path = out_base.with_suffix(".jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as fjsonl:
        with ThreadPoolExecutor(max_workers=args.worker) as ex:
            futures = {ex.submit(elabora_uno, nid): nid for nid in ids}
            for i, fut in enumerate(as_completed(futures), 1):
                nid, m, err = fut.result()
                if err:
                    errori.append({"id": nid, "errore": err})
                else:
                    risultati.append(m)
                    fjsonl.write(json.dumps(m, ensure_ascii=False) + "\n")
                if i % 500 == 0 or i == len(ids):
                    trascorso = time.time() - inizio
                    print(f"  [{i}/{len(ids)}] analizzati... ({trascorso:.0f}s, "
                          f"{len(errori)} errori)", flush=True)

    agg = qa.aggrega(risultati, soglia_gap=0.20, soglia_chars_pagina=250, top_n=20)
    agg["documenti_con_errore_qa"] = len(errori)
    agg["errori_qa"] = errori[:20]

    fonte = f"s3://{BUCKET}/raw/ (streaming, nessun file locale)"
    parametri = {
        "generato": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "fonte": fonte, "parsed_dir": fonte, "raw_dir": fonte,
        "soglia_gap": 0.20, "soglia_chars_pagina": 250,
        "taglio_comma": qa.TAGLIO_COMMA_DEFAULT,
    }
    report = {"parametri": parametri, **agg}

    out_base.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    out_base.with_suffix(".md").write_text(qa.render_markdown(agg, parametri), encoding="utf-8")

    ore = (time.time() - inizio) / 60
    print(f"\nCompletato in {ore:.1f} minuti. {len(risultati)} analizzati, {len(errori)} errori.")
    print(f"  {out_base}.json")
    print(f"  {out_base}.md")
    print(f"  {jsonl_path}")
    if errori:
        print("\nPrimi errori:")
        for e in errori[:10]:
            print(f"  {e['id']}: {e['errore'].splitlines()[0]}")


if __name__ == "__main__":
    main()
