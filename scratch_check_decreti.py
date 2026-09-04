import sys
from pathlib import Path
sys.path.insert(0, 'src')
import importlib.util
spec = importlib.util.spec_from_file_location('scrape', 'src/01_scrape.py')
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

from bs4 import BeautifulSoup
import re

params = dict(sc.PARAMS_BASE, P0_tipo='+Decreto', P0_pagina='1')
resp = sc.get(sc.ARCHIVIO, params=params)
soup = BeautifulSoup(resp.text, 'html.parser')

print('=== VERIFICA PORTALE CGG (TIPO: +Decreto) ===')
cards = soup.select('div[id^="card_"]')
print('Risultati pagina 1:', len(cards), 'card trovate')

links_pag = soup.find_all('a', href=re.compile(r'P0_pagina='))
pagine = []
for a in links_pag:
    m = re.search(r'P0_pagina=(\d+)', a['href'])
    if m:
        pagine.append(int(m.group(1)))

if pagine:
    max_pag = max(pagine)
    print('Ultima pagina indicata nel selettore:', max_pag)

# Cerchiamo l'ultima pagina effettiva del portale
# Proviamo a interrogare la pagina 548 (548 * 15 = 8220)
params_last = dict(sc.PARAMS_BASE, P0_tipo='+Decreto', P0_pagina='548')
resp_last = sc.get(sc.ARCHIVIO, params=params_last)
soup_last = BeautifulSoup(resp_last.text, 'html.parser')
cards_last = soup_last.select('div[id^="card_"]')
print('Risultati a pagina 548:', len(cards_last), 'card trovate')

# Censimento locale
raw_dir = Path('data/raw')
decreti_locali = [p.name for p in raw_dir.iterdir() if p.is_dir() and any(p.name.startswith(pref) for pref in ['D-', 'DD-', 'DC-', 'DL-', 'DR-', 'EC-'])]
leggi_locali = [p.name for p in raw_dir.iterdir() if p.is_dir() and any(p.name.startswith(pref) for pref in ['L-', 'LQ-', 'LC-', 'LRC-'])]

print('\n--- CENSIMENTO LOCALE (data/raw/) ---')
print('Decreti totali salvati su disco:', len(decreti_locali))
print('Leggi totali salvate su disco:  ', len(leggi_locali))
print('Totale atti su disco:          ', len(list(raw_dir.iterdir())))
