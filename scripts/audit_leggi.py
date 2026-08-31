import sys
import importlib.util
from pathlib import Path
import collections
import json
import concurrent.futures

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("scraper", ROOT / "src" / "01_scrape.py")
scraper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scraper)

print("Scaricamento di tutti i 2.460 record di indice dalle 164 pagine del portale...")

def fetch_page(p):
    ris, tot = scraper.cerca("+Legge", limite=15, pagina=p, silenzioso=True)
    return p, ris

tutti_risultati = []
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    futures = [ex.submit(fetch_page, p) for p in range(1, 165)]
    for f in concurrent.futures.as_completed(futures):
        p, ris = f.result()
        for r in ris:
            tutti_risultati.append({**r, "pagina": p})

tutti_risultati.sort(key=lambda x: (x["pagina"], x.get("titolo", "")))
print(f"Totale risultati estratti dal portale: {len(tutti_risultati)}")

raw_dir = ROOT / "data" / "raw"
parsed_dir = ROOT / "data" / "parsed"

# Mappiamo le schede scaricate
scheda_to_norma = {}
for cartella in raw_dir.iterdir():
    if not cartella.is_dir():
        continue
    scheda_f = cartella / "scheda.json"
    if scheda_f.exists():
        try:
            d = json.loads(scheda_f.read_text(encoding="utf-8"))
            scheda_to_norma[d.get("urlScheda")] = cartella.name
            scheda_to_norma[cartella.name] = cartella.name
        except Exception:
            pass

norma_to_schede = collections.defaultdict(list)
non_scaricati = []
for r in tutti_risultati:
    nid = scheda_to_norma.get(r["urlScheda"])
    if nid:
        norma_to_schede[nid].append(r)
    else:
        non_scaricati.append(r)

print(f"\nNorme distinte mappate: {len(norma_to_schede)}")
print(f"Schede non scaricate / non mappate: {len(non_scaricati)}")

duplicati = {k: v for k, v in norma_to_schede.items() if len(v) > 1}
print(f"Norme con più schede associate (atti duplicati/ripubblicati sul portale): {len(duplicati)}")
print(f"Totale 'righe duplicate' assorbite: {sum(len(v) - 1 for v in duplicati.values())}")

print("\nElenco di atti ripetuti nel portale con lo stesso identificativo normativo:")
for k, v in list(duplicati.items()):
    print(f"  ID: {k} (compare {len(v)} volte nel portale)")
    for item in v:
        print(f"    - Pagina {item['pagina']}: {item['titolo'][:70]}... [{item['schedaId']}]")

if non_scaricati:
    print(f"\nAtti non trovati in locale ({len(non_scaricati)}):")
    for item in non_scaricati:
        print(f"    - Pagina {item['pagina']}: {item['titolo']} [{item['schedaId']}] -> {item['urlScheda']}")
