"""
Scarica un campione da una cartella di output su S3 e controlla che i file
siano sani: JSON valido, non troncato, chiavi attese, id univoci, nessun
comma vuoto, e i conteggi dei casi di riferimento usati nelle prove del
parser.

I quindici documenti sono i casi che i fix hanno cambiato - o che NON devono
cambiare - con l'attesa accanto: se un giorno uno di questi numeri non torna,
il fix corrispondente si e' rotto. Il perche' di ognuno sta in
REPORT_FIX_PARSER.md.

Uso:
    .venv/Scripts/python.exe scripts/verifica_campione_s3.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.argv = sys.argv[:1]
import baseline_from_s3 as b  # noqa

DEST = ROOT / "data" / "campione_parsed_v2"
DEST.mkdir(parents=True, exist_ok=True)

# casi di riferimento dei test, piu' un paio di classi particolari
CAMPIONE = {
    "L-87-2026": "smoke test di 04_verify.py",
    "L-0-1910": "due atti nello stesso PDF (Legge + Regolamento)",
    "X-3-1942": "convenzione riportata nel dispositivo",
    "DD-12-2017": "tabella a colonne, deve restare invariato",
    "L-24-2022": "articoli del codice di procedura penale citati",
    "L-162-2004": "novella che riporta due leggi",
    "L-168-2005": "il blocco citato piu' grande del corpus",
    "DD-204-2020": "titolo sostituito per intero",
    "L-119-2015": "tre allegati citati in coda",
    "LC-41-2004": "falso positivo noto: 'Art.l' letto male",
    "L-52-1947": "numerazione sbagliata nell'originale",
    "DD-19-2016": "articoli bis propri, non citati",
    "EC-None-2019~17162000": "errata corrige, nessun articolo proprio",
    "D-122-1985": "struttura dedotta",
    "S-1-1600": "Statuto copiato da parsed/",
}

# Gli articoli attesi sono quelli propri dell'atto: gli articoli d'allegato
# (campo "allegato", numero "all-N") non si contano.
ATTESI = {          # da REPORT_FIX_PARSER.md e dalle prove inline
    "L-87-2026": {"articoli": 60, "commi": 245, "titoli": 8, "capi": 18},
    "DD-12-2017": {"articoli": 4},
    "X-3-1942": {"articoli": 1},
    "L-24-2022": {"articoli": 40},
    "L-162-2004": {"articoli": 9},
    "L-168-2005": {"articoli": 17},
    "DD-204-2020": {"articoli": 4},
    "L-119-2015": {"articoli": 38},
    "LC-41-2004": {"articoli": 6},
    "L-52-1947": {"articoli": 9},
    "DD-19-2016": {"articoli": 27},
}

CHIAVI = ["id", "preambolo", "citazioniPreambolo", "partizioni", "articoli"]

print(f"{'documento':<24} {'byte':>9}  {'art':>4} {'commi':>6} {'cit':>5}  esito")
guasti = []
for nid, nota in CAMPIONE.items():
    chiave = f"parsed_v2/{nid}.json"
    grezzo = b._s3.get_object(Bucket=b.BUCKET, Key=chiave)["Body"].read()
    (DEST / f"{nid}.json").write_bytes(grezzo)

    problemi = []
    testo = grezzo.decode("utf-8")
    if not testo.rstrip().endswith("}"):
        problemi.append("file troncato")
    try:
        d = json.loads(testo)
    except ValueError as e:
        guasti.append((nid, f"JSON non valido: {e}"))
        print(f"{nid:<24} {len(grezzo):>9,}  JSON NON VALIDO")
        continue

    statuto = nid.startswith("S-")
    if not statuto:
        mancanti = [k for k in CHIAVI if k not in d]
        if mancanti:
            problemi.append(f"chiavi mancanti: {mancanti}")
    if d.get("id") != nid:
        problemi.append(f"id incoerente: {d.get('id')!r}")

    art = d.get("articoli") or []
    ids_art = [a["id"] for a in art]
    ids_comma = [c["id"] for a in art for c in (a.get("commi") or [])]
    commi = len(ids_comma)
    cit = sum(len(a.get("citazioni") or []) for a in art) + len(d.get("citazioniPreambolo") or [])
    if len(set(ids_art)) != len(ids_art):
        problemi.append("id di articolo duplicati")
    if len(set(ids_comma)) != len(ids_comma):
        problemi.append("id di comma duplicati")
    if not art:
        problemi.append("nessun articolo")
    vuoti = [c["id"] for a in art for c in (a.get("commi") or []) if not (c.get("testo") or "").strip()]
    if vuoti:
        problemi.append(f"{len(vuoti)} commi vuoti")
    senza = [a["id"] for a in art if not (a.get("commi") or [])]
    if senza:
        problemi.append(f"{len(senza)} articoli senza commi")
    for a in art:
        if not str(a.get("numero") or "").strip():
            problemi.append("articolo senza numero")
            break
    for a in art:
        for c in a.get("citazioni") or []:
            if not all(k in c for k in ("tipo", "numero", "commaId", "testo")):
                problemi.append("citazione con campi mancanti")
                break

    att = ATTESI.get(nid)
    if att:
        propri = [a for a in art if not a.get("allegato")]
        if len(propri) != att["articoli"]:
            problemi.append(f"articoli propri {len(propri)} invece di {att['articoli']}")
        if "commi" in att and commi != att["commi"]:
            problemi.append(f"commi {commi} invece di {att['commi']}")
        if "titoli" in att:
            t = [p for p in d.get("partizioni") or [] if p["tipo"] == "Titolo"]
            c = sum(len(p.get("figli") or []) for p in d.get("partizioni") or [])
            if len(t) != att["titoli"] or c != att["capi"]:
                problemi.append(f"partizioni {len(t)} titoli / {c} capi")

    esito = "ok" if not problemi else "; ".join(problemi)
    if problemi:
        guasti.append((nid, esito))
    print(f"{nid:<24} {len(grezzo):>9,}  {len(art):>4} {commi:>6} {cit:>5}  {esito}")

print(f"\nScaricati in {DEST}")
print("TUTTO SANO" if not guasti else f"PROBLEMI su {len(guasti)}: {guasti}")

# controlli di merito sui casi che i fix hanno cambiato
d = json.loads((DEST / "L-0-1910.json").read_text(encoding="utf-8"))
ripetuti = [a["numero"] for a in d["articoli"] if "-rip" in a["numero"]]
print(f"L-0-1910 articoli del secondo atto: {len(ripetuti)}, articoli {len(d['articoli'])}")
d = json.loads((DEST / "X-3-1942.json").read_text(encoding="utf-8"))
print(f"X-3-1942 articoli {len(d['articoli'])}, di cui della convenzione "
      f"{sum(1 for a in d['articoli'] if a.get('allegato'))}")
d = json.loads((DEST / "EC-None-2019~17162000.json").read_text(encoding="utf-8"))
print(f"errata corrige: articoli {len(d['articoli'])}, "
      f"tutti dedotti {all(a.get('strutturaDedotta') for a in d['articoli'])}")
d = json.loads((DEST / "L-87-2026.json").read_text(encoding="utf-8"))
bis = [c["numero"] for a in d["articoli"] for c in a["commi"] if "-" in c["numero"]]
print(f"L-87-2026 commi con suffisso: {bis}")
