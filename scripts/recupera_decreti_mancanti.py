"""
Scarica i Decreti che la riconciliazione ha trovato assenti dal disco.

Legge out/verifica_decreti.json (prodotto da verifica_decreti.py) e per ogni
scheda mancante richiama scarica_uno() di 01_scrape.py: e' la stessa funzione
della pipeline, quindi l'id nasce dai metadati della scheda e non da una regex
sul titolo, e l'endpoint del documento e' quello giusto (documento<ID>.html,
che risponde PDF o ZIP secondo il Content-Type).

    python scripts/recupera_decreti_mancanti.py           # solo i decreti
    python scripts/recupera_decreti_mancanti.py --archivio # tutto l'archivio
    python scripts/recupera_decreti_mancanti.py 20        # solo i primi 20

Dopo questo script vanno rieseguiti 02_parse.py e 03_load.py.
"""

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
# Il rapporto da recuperare: quello dei soli decreti o quello dell'archivio.
RAPPORTO = OUT / ("verifica_archivio.json" if "--archivio" in sys.argv
                  else "verifica_decreti.json")

sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("scrape", ROOT / "src" / "01_scrape.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

BASE_SCHEDA = f"{sc.BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti"


def main(limite=None):
    if not RAPPORTO.exists():
        sys.exit(f"Manca {RAPPORTO}. Esegui prima scripts/verifica_decreti.py")

    dati = json.loads(RAPPORTO.read_text(encoding="utf-8"))
    # Chi non e' nel grafo, non solo chi manca dal disco: alcuni atti sono su
    # disco ma con l'id conteso, e vanno riscaricati per prendersi il proprio.
    per_scheda = {c["schedaId"]: c for c in dati["mancantiSuDisco"]}
    for c in dati.get("nonNelGrafo", []):
        per_scheda.setdefault(c["schedaId"], c)
    mancanti = list(per_scheda.values())
    if limite:
        mancanti = mancanti[:limite]

    print(f"Atti da recuperare: {len(mancanti)}")
    print(f"Pausa fra richieste: {sc.PAUSA}s (due richieste per atto)")
    print(f"Tempo stimato: circa {len(mancanti) * sc.PAUSA * 2 / 60:.0f} minuti\n")

    indice = sc.carica_indice()
    presi, saltati, falliti = [], 0, []
    t0 = time.time()

    for i, c in enumerate(mancanti, 1):
        r = {
            "schedaId": c["schedaId"],
            "documentoId": c["documentoId"],
            "titolo": c["titolo"],
            "urlScheda": f"{BASE_SCHEDA}/scheda{c['schedaId']}.html",
            "urlDocumento": f"{BASE_SCHEDA}/documento{c['documentoId']}.html",
        }
        try:
            nid = sc.scarica_uno(r, indice)
            if nid is None:
                saltati += 1
                print(f"[{i:>3}/{len(mancanti)}] gia' presente     scheda {c['schedaId']}")
            else:
                presi.append(nid)
                pdf = sc.RAW / nid / "testo.pdf"
                peso = pdf.stat().st_size // 1024 if pdf.exists() else 0
                print(f"[{i:>3}/{len(mancanti)}] {nid:<18} {peso:>6} KB  {c['titolo'][:44]}")
        except Exception as e:
            falliti.append({"schedaId": c["schedaId"], "titolo": c["titolo"],
                            "errore": f"{type(e).__name__}: {e}"})
            print(f"[{i:>3}/{len(mancanti)}] FALLITO scheda {c['schedaId']}: {type(e).__name__}: {e}")
            traceback.print_exc(limit=1)

        if i % 25 == 0:
            sc.salva_indice(indice)

    sc.salva_indice(indice)

    print("\n" + "=" * 60)
    print(f"Scaricati ora : {len(presi)}")
    print(f"Gia' presenti : {saltati}")
    print(f"Falliti       : {len(falliti)}")
    print(f"Durata        : {(time.time() - t0) / 60:.1f} min")
    print("=" * 60)

    if falliti:
        dove = OUT / "decreti_falliti.json"
        dove.write_text(json.dumps(falliti, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nElenco dei falliti: {dove}")
        for f in falliti[:10]:
            print(f"  scheda {f['schedaId']}  {f['errore']}")

    if presi:
        print("\nOra: python src/02_parse.py  &&  python src/03_load.py")


if __name__ == "__main__":
    # Il limite e' il primo argomento numerico, ovunque si trovi: cosi'
    # "--archivio 5" non viene letto come "nessun limite".
    numerici = [a for a in sys.argv[1:] if a.isdigit()]
    main(int(numerici[0]) if numerici else None)
