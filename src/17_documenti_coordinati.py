"""
17 - Gli articoli dei testi coordinati aprono il PDF da cui vengono.

Il riferimento a un articolo apre il PDF della norma. Per il Codice Penale il
documento della L-17-1974 e' la legge di emanazione: due pagine, cinque
articoli, e un rimando "(V. Allegato A B a pag. 29)". I 480 articoli del Codice
nel grafo vengono invece dal testo coordinato (10_codice_penale.py), che sul
portale e' un altro documento. Chi cliccava sull'art. 150 non lo trovava.

Qui, per ogni testo coordinato in data/coordinati/documenti.json:

  - si legge il PDF e si annota la pagina dove comincia ogni articolo:
    l'intestazione "Art. N" in grassetto, al corpo del testo (le note, piu'
    piccole, riportano i testi originari con le stesse intestazioni), sotto
    l'ultima intestazione d'atto incontrata;
  - gli articoli del grafo scritti da quel testo coordinato - riconosciuti
    dalla data di aggiornamento, e per il Codice anche dalla norma - ricevono
    `urlDocumento` (il documento del portale) e `paginaDocumento`.

Gli strumenti restituiscono l'URL dell'articolo quando c'e', il server lo usa
in /documenti/{norma}?articolo=N, il sito apre il PDF a #page=N.

Va rieseguito dopo 10_codice_penale.py e 12_raccolta_coordinata.py.

Uso:
    .venv/Scripts/python.exe src/17_documenti_coordinati.py            # solo misura
    .venv/Scripts/python.exe src/17_documenti_coordinati.py --scrivi
"""

import collections
import importlib.util
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

import fitz

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def _modulo(nome, file):
    spec = importlib.util.spec_from_file_location(nome, RADICE / "src" / file)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


rc = _modulo("raccolta12", "12_raccolta_coordinata.py")
cp = rc.cp

COORDINATI = RADICE / "data" / "coordinati"
PORTALE = "https://www.consigliograndeegenerale.sm/on-line/home/archivio-leggi-decreti-e-regolamenti/documento{}.html"

Q_ARTICOLI = """
MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)
WHERE a.fonteTesto IS NOT NULL AND a.testoAggiornatoAl = $aggiornato
  AND ($norma IS NULL OR n.id = $norma)
RETURN n.id AS norma, a.id AS id, a.numero AS numero
"""

Q_SCRIVI = """
UNWIND $articoli AS x
MATCH (a:Articolo {id: x.id})
SET a.urlDocumento = x.url, a.paginaDocumento = x.pagina
"""


def pagine(pdf, norma_fissa, risolvi):
    """(norma, chiave del numero) -> prima pagina, contando da 1."""
    documento = fitz.open(pdf)
    righe = [[r for b in p.get_text("dict")["blocks"] for r in b.get("lines", [])] for p in documento]
    dimensioni = collections.Counter(round(rc._dimensione(r["spans"])) for rr in righe for r in rr
                                     if rc._dimensione(r["spans"]))
    soglia = dimensioni.most_common(1)[0][0] - 0.5
    trovate, atto = {}, norma_fissa
    for n, rr in enumerate(righe, 1):
        for r in rr:
            span = [s for s in r["spans"] if s["text"].strip()]
            if not span or rc._dimensione(r["spans"]) < soglia:
                continue
            testo = re.sub(r"\s+", " ", "".join(s["text"] for s in r["spans"])).strip()
            grassetto = any(s["flags"] & 16 for s in span)
            if not norma_fissa and grassetto and r["bbox"][0] < rc.X_INTESTAZIONE:
                m = rc.RE_ATTO.fullmatch(testo)
                if m:
                    tipo = re.sub(r"\s*[-–—]\s*", "-", re.sub(r"\s+", " ", m.group("tipo"))).title()
                    atto = risolvi(tipo, int(m.group("numero")), int(m.group("anno")))
                    continue
            m = rc.RE_ART.match(testo)
            if m and atto and (grassetto or norma_fissa):
                base = "Unico" if m.group(1).lower() == "unico" else m.group(1)
                numero = base + ("-" + m.group(2).lower() if m.group(2) else "")
                trovate.setdefault((atto, cp.chiave(numero)), n)
    return trovate, len(righe)


def controlla(url):
    """Il tipo del documento sul portale. Uno ZIP va bene se contiene un PDF:
    il Codice Penale e l'Edilizia arrivano cosi', e il server estrae il PDF
    completo."""
    try:
        richiesta = urllib.request.Request(url, headers={"User-Agent": "graphResponsa/1.0"})
        with urllib.request.urlopen(richiesta, timeout=60) as r:
            tipo, dati = r.headers.get_content_type(), r.read()
    except Exception as e:
        return f"errore: {e}", 0
    if tipo != "application/pdf":
        try:
            nomi = zipfile.ZipFile(io.BytesIO(dati)).namelist()
        except zipfile.BadZipFile:
            return tipo, len(dati)
        if any(n.lower().endswith(".pdf") for n in nomi):
            return "application/pdf (in zip)", len(dati)
    return tipo, len(dati)


def main():
    scrivi = "--scrivi" in sys.argv
    g = cp.grafo()
    risolvi = rc.risolutore(rc.indice_norme(g))
    documenti = json.loads((COORDINATI / "documenti.json").read_text(encoding="utf-8"))
    for nome, d in documenti.items():
        url = PORTALE.format(d["documento"])
        tipo, byte = controlla(url)
        trovate, totale = pagine(COORDINATI / d["pdf"], d.get("norma"), risolvi)
        articoli = g.query(Q_ARTICOLI, {"aggiornato": d["aggiornatoAl"], "norma": d.get("norma")})
        lotto = [{"id": a["id"], "url": url,
                  "pagina": trovate.get((a["norma"], cp.chiave(a["numero"])))} for a in articoli]
        senza = [a["id"] for a, x in zip(articoli, lotto) if x["pagina"] is None]
        print(f"\n  {nome}: documento {d['documento']} ({tipo}, {byte / 1e6:.1f} MB letti) | pagine {totale}")
        print(f"    articoli nel grafo {len(articoli)} | con la pagina {len(articoli) - len(senza)}"
              + (f" | senza: {', '.join(senza[:8])}" if senza else ""))
        esempi = [x for x in lotto if x["pagina"]][:3] + [x for x in lotto if x["id"].endswith(("/art-150", "/art-81"))]
        for x in esempi[:5]:
            print(f"      {x['id']:<28} pagina {x['pagina']}")
        if scrivi and tipo.startswith("application/pdf"):
            g.query(Q_SCRIVI, {"articoli": lotto})
            print(f"    scritti {len(lotto)} articoli")
        elif scrivi:
            print("    NON scritto: il portale non restituisce un PDF per questo documento")
    if not scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi per applicare.")


if __name__ == "__main__":
    main()
