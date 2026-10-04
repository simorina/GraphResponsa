"""
Scarica le linee guida e i protocolli operativi del Tribunale Unico di San
Marino e li deposita in data/linee-guida/, con un manifesto.json che ne
conserva titolo e data: nel PDF non si leggono, perche' quasi tutti sono
scansioni senza testo.

La pagina ha un paragrafo per documento: un link al PDF col testo GG_MM_AAAA,
seguito dal titolo. Un paragrafo puo' avere piu' di un link (il protocollo
con la UO Tutela Minori ne ha due, due scansioni diverse): si tengono tutti,
col suffisso -1, -2.

Ogni PDF si riconosce dal suo jcr:<uuid> nel DAM del sito, che cambia se il
Tribunale sostituisce il file. Un id gia' in manifesto.json, col suo file
presente sul disco, non si riscarica: rilanciare lo script scarica solo le
novita', o i PDF che mancano (per esempio dopo un clone, se i PDF non sono
versionati).

Uso:
    .venv/Scripts/python.exe scripts/scarica_linee_guida.py
    .venv/Scripts/python.exe scripts/scarica_linee_guida.py --scarica
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

import requests

RADICE = Path(__file__).resolve().parent.parent
DEST = RADICE / "data" / "linee-guida"
MANIFESTO = DEST / "manifesto.json"

SITO = "https://www.tribunale.sm"
PAGINA = f"{SITO}/pub1/TribunaleSM/il-tribunale/Linee-Guida-e-Protocolli-Operativi.html"

# Quasi ogni titolo apre con "Linee Guida per la/sul/in materia di": senza
# toglierle, ogni slug comincerebbe con le stesse parole.
STOPWORD = {
    "linee", "guida", "per", "la", "il", "lo", "le", "gli", "i", "di", "del",
    "della", "delle", "dei", "degli", "in", "materia", "sul", "sulla", "sulle",
    "sui", "e", "ed", "fra", "tra", "a",
}
RE_DATA = re.compile(r"(\d{2})_(\d{2})_(\d{4})")
RE_JCR = re.compile(r"/dam/jcr:([0-9a-f-]{36})/")


def _slug(titolo):
    """"Linee Guida sul Diritto di Famiglia" -> "diritto-famiglia"."""
    t = unicodedata.normalize("NFKD", titolo).encode("ascii", "ignore").decode()
    parole = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", t) if w.lower() not in STOPWORD]
    return "-".join(parole[:7]) or "documento"


def elenco_documenti(sessione):
    """Un dict per PDF, nell'ordine della pagina: id, url, data, titolo,
    nome_originale e il nome di file proposto."""
    from bs4 import BeautifulSoup
    r = sessione.get(PAGINA, timeout=60)
    r.raise_for_status()
    # Il server non dichiara il charset e requests ripiegherebbe su latin-1,
    # guastando "indennita'" e simili.
    soup = BeautifulSoup(r.content.decode("utf-8"), "html.parser")
    documenti = []
    for p in soup.find("div", class_="single-careers-content").find_all("p"):
        links = [a["href"] for a in p.find_all("a", href=RE_JCR)]
        if not links:
            continue
        # split() senza argomenti spezza anche sui &nbsp; sparsi nei titoli.
        testo = " ".join(p.get_text(" ").split())
        m = RE_DATA.search(testo)
        if not m:
            print(f"  ! paragrafo senza data, saltato: {testo}")
            continue
        g, mese, anno = m.groups()
        data = f"{anno}-{mese}-{g}"
        titolo = testo[m.end():].strip(" .")
        for n, href in enumerate(links, 1):
            suffisso = f"-{n}" if len(links) > 1 else ""
            documenti.append({
                "id": RE_JCR.search(href).group(1),
                "url": SITO + href,
                "data": data,
                "titolo": titolo,
                "nome_originale": unquote(href.rsplit("/", 1)[1]),
                "file": f"{data}_{_slug(titolo)}{suffisso}.pdf",
            })
    return documenti


def scarica_pdf(sessione, url, tentativi=3):
    """Il server del Tribunale e' lento e ogni tanto si pianta a meta' di un
    PDF da qualche MB: si riprova prima di arrendersi."""
    for n in range(1, tentativi + 1):
        try:
            r = sessione.get(url, timeout=(30, 300))
            r.raise_for_status()
            if r.content[:5] != b"%PDF-":
                raise ValueError("la risposta non e' un PDF")
            return r.content
        except (requests.RequestException, ValueError) as e:
            if n == tentativi:
                raise
            print(f"    {type(e).__name__}, riprovo ({n}/{tentativi - 1})")


def scrivi_manifesto(manifesto):
    # Dal piu' recente, come sulla pagina, cosi' si legge anche a occhio.
    voci = sorted(manifesto.items(), key=lambda kv: kv[1]["file"])
    voci.sort(key=lambda kv: kv[1]["data"], reverse=True)
    MANIFESTO.write_text(json.dumps(dict(voci), ensure_ascii=False, indent=1), encoding="utf-8")


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
    sessione.headers["User-Agent"] = "Mozilla/5.0 (compatibile; raccolta-linee-guida)"

    print("  lettura della pagina...")
    documenti = elenco_documenti(sessione)

    # Un id gia' nel manifesto tiene il nome che aveva, anche se nel frattempo
    # il Tribunale ha ritoccato il titolo: il file non cambia nome sotto i piedi.
    piano = []
    usati = {v["file"] for v in manifesto.values()}
    for d in documenti:
        if d["id"] in manifesto:
            d["file"] = manifesto[d["id"]]["file"]
            if (DEST / d["file"]).exists():
                continue
        else:
            base, nome, n = d["file"][:-4], d["file"], 2
            while nome in usati:
                nome, n = f"{base}-{n}.pdf", n + 1
            d["file"] = nome
            usati.add(nome)
        piano.append(d)

    sulla_pagina = {d["id"] for d in documenti}
    spariti = [v["file"] for k, v in manifesto.items() if k not in sulla_pagina]
    print(f"  {len(documenti)} PDF sulla pagina | {len(manifesto)} nel manifesto"
          f" | {len(piano)} da scaricare\n")
    for d in piano:
        print(f"  {d['file']}")
        print(f"      {d['titolo']}")
    if spariti:
        print(f"\n  {len(spariti)} PDF del manifesto non piu' sulla pagina (sostituiti o"
              " ritirati? il file resta): " + ", ".join(spariti))

    if not args.scarica:
        print("\n  Nulla scaricato. Aggiungi --scarica per salvare i PDF in "
              f"{DEST.relative_to(RADICE)}/.")
        return

    # Il manifesto si aggiorna via via, cosi' un rilancio dopo un errore
    # riparte da dove si era fermato.
    falliti = []
    for d in piano:
        try:
            pdf = scarica_pdf(sessione, d["url"])
        except Exception as e:
            print(f"  ! {d['file']}: {e}")
            falliti.append(d["file"])
            continue
        (DEST / d["file"]).write_bytes(pdf)
        manifesto[d["id"]] = {k: d[k] for k in ("file", "data", "titolo", "nome_originale", "url")}
        scrivi_manifesto(manifesto)
        print(f"  scritto {d['file']} ({len(pdf):,} byte)")

    if falliti:
        print(f"\n  {len(falliti)} PDF non scaricati, rilancia lo script per riprovarli: "
              + ", ".join(falliti))
    print(f"\n  manifesto aggiornato: {MANIFESTO.relative_to(RADICE)}")


if __name__ == "__main__":
    main()
