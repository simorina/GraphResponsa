"""
Scarica i testi coordinati dal sito del Consiglio Grande e Generale e li
deposita in data/coordinati/, pronti per 12_raccolta_coordinata.py.

Il sito non elenca i PDF direttamente: ogni sezione tematica (docCat.NNN...)
elenca dei documenti, e ogni documento (documentoNNN.html) restituisce - senza
bisogno di login - uno zip con dentro il PDF con note e uno "SENZA NOTE"; si
tiene solo quello con le note, perche' 12_raccolta_coordinata.py le legge per
ricalcolare abrogazioni e novelle.

Le sezioni sono elencate a mano (l'elenco cambia raramente e non vale la pena
raschiare anche la pagina indice); un documento gia' presente in
manifesto.json non si riscarica, cosi' rilanciare lo script dopo che il sito
ha aggiornato un testo scarica solo le novita' - la sostituzione di un file
gia' scaricato va fatta a mano, cancellando la sua riga dal manifesto.

Uso:
    .venv/Scripts/python.exe scripts/scarica_testi_coordinati.py
    .venv/Scripts/python.exe scripts/scarica_testi_coordinati.py --scarica
"""

import argparse
import io
import json
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import requests

RADICE = Path(__file__).resolve().parent.parent
DEST = RADICE / "data" / "coordinati"
MANIFESTO = DEST / "manifesto.json"

BASE = "https://www.consigliograndeegenerale.sm/on-line"

# I - X, dall'indice /on-line/home/testi-coordinati.html.
CATEGORIE = [
    "17003128", "17003129", "17003130",  # I  Affari costituzionali/interni
    "17003105", "17003106", "17003107",  # II Affari esteri
    "17003090", "17003091", "17003092", "17003093", "17003094", "17003095", "17004781",  # III Finanze
    "17003116", "17003117", "17003118", "17003119",  # IV Cultura
    "17003120", "17003121",  # V Sanita' e sicurezza sociale
    "17003114", "17003115", "17005070", "17005116",  # VI Territorio ed ambiente
    "17003108", "17003109", "17003110", "17003111", "17003112", "17003113",  # VII Economia
    "17003122", "17003123", "17003267",  # VIII Giustizia
    "17003124", "17003125", "17003126", "17003127",  # IX Lavoro
    "17005042",  # X Turismo
]

STOPWORD = {
    "testo", "coordinato", "coordinata", "raccolta", "unico", "unica",
    "leggi", "in", "materia", "di", "d", "del", "della", "delle", "dei",
    "degli", "il", "lo", "la", "i", "gli", "le", "un", "una", "e", "ed",
    "con", "sul", "sulla", "sulle", "sui", "sull", "che", "al", "alla",
    "alle", "ai", "agli", "per", "tra", "fra", "dal", "dalla", "dalle", "n",
}
# Il titolo apre quasi sempre con "Testo coordinato"/"Raccolta coordinata" (il
# nome dell'atto, se c'e', segue) e chiude con "(aggiornato al ...)" o
# "(aggiornamento a ...)": senza toglierli, ogni slug comincerebbe con le
# stesse due parole e finirebbe con la data anziche' col soggetto.
RE_PREFISSO = re.compile(r"^(testo\s+coordinato|raccolta\s+coordinata)\b[\s:–—-]*", re.I)
RE_DATA_AGGIORNAMENTO = re.compile(r"\s*\([^)]*[Aa]ggiorna[^)]*\)\s*$")


def _slug(titolo):
    """"Testo coordinato in materia di edilizia sovvenzionata (...)" ->
    "edilizia-sovvenzionata": stessa forma dei due file gia' in data/coordinati/."""
    t = RE_DATA_AGGIORNAMENTO.sub("", titolo)
    t = RE_PREFISSO.sub("", t)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    parole = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", t) if w.lower() not in STOPWORD]
    return "-".join(parole[:8]) or "testo"


def elenco_documenti(sessione):
    """{docid: {"titolo":..., "categorie": [...]}} da tutte le pagine di categoria."""
    from bs4 import BeautifulSoup
    documenti = {}
    for cat in CATEGORIE:
        url = f"{BASE}/home/testi-coordinati/docCat.{cat}.1.150.20.html"
        r = sessione.get(url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tr in soup.find_all("tr"):
            a = tr.find("a", href=re.compile(r"documento\d+\.html"))
            if not a:
                continue
            docid = re.search(r"documento(\d+)\.html", a["href"]).group(1)
            cella = tr.find("td", id="bordosx")
            if not cella:
                continue
            titolo = cella.get_text(" ", strip=True)
            voce = documenti.setdefault(docid, {"titolo": titolo, "categorie": []})
            voce["categorie"].append(cat)
    return documenti


def scarica_pdf(sessione, docid):
    """Dietro /on-line/documentoNNN.html c'e' a volte uno zip (con dentro il
    PDF con note e uno "SENZA NOTE": si tiene il primo), a volte il PDF gia'
    da solo - il sito non e' coerente fra un documento e l'altro."""
    r = sessione.get(f"{BASE}/documento{docid}.html", timeout=60)
    r.raise_for_status()
    if r.content[:4] == b"%PDF":
        return r.content
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        candidati = [n for n in z.namelist()
                    if n.lower().endswith(".pdf") and "senza note" not in n.lower()]
        if not candidati:
            return None
        return z.read(candidati[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scarica", action="store_true", help="scrive i PDF; senza, solo l'anteprima")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    DEST.mkdir(parents=True, exist_ok=True)
    manifesto = json.loads(MANIFESTO.read_text(encoding="utf-8")) if MANIFESTO.exists() else {}

    sessione = requests.Session()
    sessione.headers["User-Agent"] = "Mozilla/5.0 (compatibile; raccolta-testi-coordinati)"

    print("  lettura delle sezioni...")
    documenti = elenco_documenti(sessione)
    nuovi = {docid: v for docid, v in documenti.items() if docid not in manifesto}
    print(f"  {len(documenti)} documenti sul sito | {len(manifesto)} gia' scaricati"
          f" | {len(nuovi)} nuovi\n")

    piano = []
    usati = {v["file"] for v in manifesto.values()}
    for docid, v in sorted(nuovi.items(), key=lambda kv: kv[1]["titolo"]):
        slug = base = _slug(v["titolo"])
        n = 2
        while slug in usati:
            slug, n = f"{base}-{n}", n + 1
        usati.add(slug)
        piano.append((docid, slug, v["titolo"]))
        print(f"  {docid}  {slug}.pdf")
        print(f"           {v['titolo']}")

    if not args.scarica:
        print("\n  Nulla scaricato. Aggiungi --scarica per salvare i PDF in "
              f"{DEST.relative_to(RADICE)}/.")
        return

    # Il sito ogni tanto risponde con una pagina di errore anziche' col PDF:
    # un errore per documento non deve buttare via il lavoro gia' fatto sugli
    # altri, e il manifesto si aggiorna via via cosi' un rilancio riparte da
    # dove si era fermato.
    falliti = []
    for docid, slug, titolo in piano:
        try:
            pdf = scarica_pdf(sessione, docid)
        except Exception as e:
            print(f"  ! {docid} ({slug}): {e}")
            falliti.append(docid)
            continue
        if pdf is None:
            print(f"  ! {docid} ({slug}): nessun PDF trovato, saltato")
            falliti.append(docid)
            continue
        (DEST / f"{slug}.pdf").write_bytes(pdf)
        manifesto[docid] = {"file": f"{slug}.pdf", "titolo": titolo,
                            "categorie": documenti[docid]["categorie"]}
        MANIFESTO.write_text(json.dumps(manifesto, ensure_ascii=False, indent=1, sort_keys=True),
                             encoding="utf-8")
        print(f"  scritto {slug}.pdf ({len(pdf):,} byte)")

    if falliti:
        print(f"\n  {len(falliti)} documenti non scaricati, rilancia lo script per riprovarli: "
              + ", ".join(falliti))
    print(f"\n  manifesto aggiornato: {MANIFESTO.relative_to(RADICE)}")
    print("  Ora: src/12_raccolta_coordinata.py --pdf data/coordinati/<file>.pdf --nome <slug>"
          " per ciascun nuovo testo.")


if __name__ == "__main__":
    main()
