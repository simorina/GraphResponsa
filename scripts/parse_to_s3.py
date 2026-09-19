"""
Rigenera il JSON di 02_parse.py per l'intero corpus e lo scrive su S3, in una
cartella versionata, senza toccare quella in uso.

  legge   s3://<bucket>/raw/<id>/{testo.pdf,scheda.json}   (streaming)
  scrive  s3://<bucket>/parsed_v2/<id>.json

La cartella di destinazione si sceglie con --prefisso: parsed/ resta quella
del grafo attuale e non va mai sovrascritta, quindi e' rifiutata a meno di
--consenti-parsed. Le prossime versioni useranno parsed_v3 e cosi' via.

Gli Statuti (S-*) sono saltati dal parser, come fa 02_parse.main(): la loro
struttura ("RUBRICA I." al posto di "Art. 1") non viene riconosciuta e li
produce un integratore dedicato. Con --copia-statuti i loro JSON gia' presenti
in parsed/ vengono copiati nella nuova cartella (copia lato server, la
sorgente non viene toccata), cosi' la cartella nuova e' completa.

Nessun file locale: i PDF passano in memoria e il JSON va diritto su S3.

Uso:
    .venv/Scripts/python.exe scripts/parse_to_s3.py --prefisso parsed_v2
    .venv/Scripts/python.exe scripts/parse_to_s3.py --prefisso parsed_v2 --limite 20
"""

import argparse
import json
import sys
import time
import warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import urllib3

warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
_argv, sys.argv = sys.argv, sys.argv[:1]
import baseline_from_s3 as b  # noqa: E402  (monkeypatch di RAW e righe_pdf)
sys.argv = _argv

p02 = b.p02
BUCKET = b.BUCKET

# parse() legge le righe da righe_pdf(), che baseline_from_s3 ha gia'
# sostituito con la versione che scarica i byte da S3: nessun file locale.


def _con_retry(f, *a, tentativi=4):
    """S3 chiude ogni tanto una connessione a meta': un passaggio sul corpus
    intero non puo' morire per questo."""
    for k in range(tentativi):
        try:
            return f(*a)
        except Exception:
            if k == tentativi - 1:
                raise
            time.sleep(2 * (k + 1))


def parsa_e_scrivi(nid, prefisso):
    def lavoro():
        chiave = f"raw/{nid}/testo.pdf"
        meta = json.loads(b._s3.get_object(
            Bucket=BUCKET, Key=f"raw/{nid}/scheda.json")["Body"].read())
        dati = p02.parse(nid, meta)
        b._cache.pop(chiave, None)          # niente accumulo in memoria
        corpo = json.dumps(dati, ensure_ascii=False, indent=2).encode("utf-8")
        b._s3.put_object(Bucket=BUCKET, Key=f"{prefisso}/{nid}.json", Body=corpo,
                         ContentType="application/json; charset=utf-8")
        return {
            "id": nid,
            "byte": len(corpo),
            "articoli": len(dati["articoli"]),
            "commi": sum(len(a["commi"]) for a in dati["articoli"]),
            "citazioni": (sum(len(a["citazioni"]) for a in dati["articoli"])
                          + len(dati["citazioniPreambolo"])),
            "caratteri": sum(len(c["testo"]) for a in dati["articoli"] for c in a["commi"]),
            "dedotta": any(a.get("strutturaDedotta") for a in dati["articoli"]),
            "univoci": sum(1 for a in dati["articoli"] if a.get("idResoUnivoco")),
            "parti": sorted({a.get("parte") for a in dati["articoli"]} - {None}),
            "allegato": bool(dati.get("allegatoPostPromulgazione")),
            "convenzione": bool(dati.get("convenzioneNelDispositivo")),
        }

    try:
        return _con_retry(lavoro)
    except Exception as e:
        return {"id": nid, "errore": f"{type(e).__name__}: {e}"}


def copia_statuti(prefisso, origine="parsed"):
    """Copia i JSON degli Statuti dalla cartella in uso, lato server."""
    copiati = []
    token = None
    while True:
        extra = {"ContinuationToken": token} if token else {}
        r = b._s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{origine}/S-", **extra)
        for o in r.get("Contents", []):
            nome = o["Key"].split("/")[-1]
            b._s3.copy_object(Bucket=BUCKET, Key=f"{prefisso}/{nome}",
                              CopySource={"Bucket": BUCKET, "Key": o["Key"]})
            copiati.append(nome)
        if not r.get("IsTruncated"):
            return copiati
        token = r["NextContinuationToken"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefisso", default="parsed_v2")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--worker", type=int, default=8)
    ap.add_argument("--copia-statuti", action="store_true")
    ap.add_argument("--consenti-parsed", action="store_true",
                    help="permette di scrivere in parsed/, la cartella del grafo attuale")
    args = ap.parse_args()

    prefisso = args.prefisso.strip("/")
    if prefisso == "parsed" and not args.consenti_parsed:
        raise SystemExit("parsed/ e' la cartella in uso dal grafo: usare parsed_v2 o simili")

    ids = [x for x in b.elenco_documenti() if not x.startswith("S-")]
    if args.limite:
        ids = ids[:args.limite]
    print(f"Documenti da parsare: {len(ids)} -> s3://{BUCKET}/{prefisso}/")

    esiti, fatti = [], 0
    with ThreadPoolExecutor(args.worker) as ex:
        for r in ex.map(lambda n: parsa_e_scrivi(n, prefisso), ids):
            esiti.append(r)
            fatti += 1
            if fatti % 500 == 0:
                print(f"  [{fatti}/{len(ids)}]")

    errori = [r for r in esiti if r.get("errore")]
    ok = [r for r in esiti if not r.get("errore")]
    print(f"\nScritti {len(ok)} file, errori {len(errori)}")
    for r in errori[:10]:
        print(f"  {r['id']}: {r['errore']}")
    somma = lambda k: sum(r[k] for r in ok)
    print(f"articoli {somma('articoli'):,}, commi {somma('commi'):,}, "
          f"citazioni {somma('citazioni'):,}, caratteri {somma('caratteri'):,}")
    print(f"documenti a struttura dedotta {sum(1 for r in ok if r['dedotta'])}, "
          f"con parti {sum(1 for r in ok if r['parti'])}, "
          f"con id resi univoci {sum(1 for r in ok if r['univoci'])}, "
          f"con allegato post promulgazione {sum(1 for r in ok if r['allegato'])}, "
          f"con convenzione nel dispositivo {sum(1 for r in ok if r['convenzione'])}")
    print(f"byte totali {somma('byte'):,}; file piu' piccolo "
          f"{min(r['byte'] for r in ok):,} ({min(ok, key=lambda r: r['byte'])['id']})")

    if args.copia_statuti:
        copiati = copia_statuti(prefisso)
        print(f"Statuti copiati da parsed/: {len(copiati)} {copiati[:5]}")

    fuori = ROOT / "data" / f"esiti_{prefisso}.json"
    fuori.write_text(json.dumps(esiti, ensure_ascii=False), encoding="utf-8")
    print(f"Esiti per documento: {fuori}")
    print("Tipi di documento:", Counter(x["id"].split("-")[0] for x in ok).most_common(8))


if __name__ == "__main__":
    main()
