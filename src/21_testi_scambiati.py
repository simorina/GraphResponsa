"""
21 - Il PDF giusto per gli atti che avevano il testo di un altro.

11_doppioni.py segnalava 35 gruppi di schede (71 atti) con lo stesso testo e
titoli inconciliabili: L-0-1910 "dei cadaveri" aveva i 119 articoli di "sulle
scuole elementari" (L-0-1910~17009270). Il guasto non e' del portale: per
L-0-1910 il portale serve oggi un PDF diverso da quello in data/raw. Due schede
con lo stesso id canonico hanno scritto nella stessa cartella, e il documento
della seconda ha preso il posto di quello della prima.

Qui si riscarica il documento di ogni scheda dei gruppi segnalati, con la
funzione di 01_scrape.py, in una cartella temporanea. Se differisce da quello
in data/raw lo si sostituisce: il vecchio resta accanto come
testo.scambiato.pdf. Gli atti col PDF cambiato si scrivono in un elenco per
15_ricostruisci_articoli.py:

    .venv/Scripts/python.exe src/21_testi_scambiati.py                  # solo misura
    .venv/Scripts/python.exe src/21_testi_scambiati.py --scrivi --elenco <file.json>
    .venv/Scripts/python.exe src/15_ricostruisci_articoli.py --atti <file.json> --testo-nuovo --scrivi --backup <file>

Dopo: 07, 07b, 09 --scrivi, 08 --scrivi, 19 --scrivi, 20 --scrivi, e 11 per
controllare che i gruppi siano spariti.
"""

import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

RAW = RADICE / "data" / "raw"


def _modulo(nome, file):
    spec = importlib.util.spec_from_file_location(nome, RADICE / "src" / file)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def impronta(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def main():
    scrivi = "--scrivi" in sys.argv
    doppioni = _modulo("doppioni11", "11_doppioni.py")
    scrape = _modulo("scrape01", "01_scrape.py")
    g = doppioni.grafo()
    gruppi = doppioni.testi_scambiati(g)
    ids = sorted({x["id"] for gruppo in gruppi for x in gruppo})
    print(f"  gruppi col testo scambiato: {len(gruppi)}, schede: {len(ids)}")

    cambiati, uguali, errori = [], [], []
    for id_ in ids:
        url = g.query("MATCH (n:Norma {id: $i}) RETURN n.urlDocumento AS u", {"i": id_})[0]["u"]
        locale = RAW / id_ / "testo.pdf"
        with tempfile.TemporaryDirectory() as tmp:
            try:
                nuovo, _ = scrape.scarica_testo(url, Path(tmp))
            except Exception as e:
                errori.append((id_, str(e)[:80]))
                continue
            if locale.exists() and impronta(nuovo) == impronta(locale):
                uguali.append(id_)
                continue
            cambiati.append(id_)
            if scrivi:
                if locale.exists():
                    shutil.copyfile(locale, locale.with_name("testo.scambiato.pdf"))
                shutil.copyfile(nuovo, locale)
    print(f"\n  PDF uguali a quello del portale: {len(uguali)}")
    print(f"  PDF diversi (sostituiti con --scrivi): {len(cambiati)}  {cambiati[:10]}")
    print(f"  errori di scaricamento: {len(errori)}  {errori[:5]}")
    if scrivi and "--elenco" in sys.argv:
        Path(sys.argv[sys.argv.index("--elenco") + 1]).write_text(
            json.dumps(cambiati, ensure_ascii=False), encoding="utf-8")
        print("  elenco scritto per 15_ricostruisci_articoli.py")


if __name__ == "__main__":
    main()
