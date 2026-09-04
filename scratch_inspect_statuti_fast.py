import requests, re, json
from bs4 import BeautifulSoup
from pathlib import Path

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ARCHIVIO = 'https://www.consigliograndeegenerale.sm/on-line/home/archivio-leggi-decreti-e-regolamenti.html'

params = {
    'P0_path': '/home/tomcat/indicizzazione/indexleggi',
    'P0_paginazione': '15',
    'P0_pagina': '1',
    'P0_orderBy': 'index_lucene,data_ordered,numero',
    'P0_order': 'asc,desc,desc',
    'P0_operatorMustBe': 'yes',
    'P0_tipo': '+Statuto',
    'indicericerca': '-1',
}

r = requests.get(ARCHIVIO, params=params, headers={'User-Agent': UA})
soup = BeautifulSoup(r.text, 'html.parser')
cards = soup.select('div[id^="card_"]')

print(f"=== I {len(cards)} STATUTI SUL PORTALE CGG ===\n")
raw_dir = Path('data/raw')
parsed_dir = Path('data/parsed')

# Costruisci indice rapido
mappa_schede = {}
for p in raw_dir.iterdir():
    if p.is_dir() and (p / 'scheda.json').exists():
        try:
            data = json.loads((p / 'scheda.json').read_text(encoding='utf-8', errors='ignore'))
            url_s = data.get('urlScheda', '')
            m = re.search(r'scheda(\d+)\.html', url_s)
            if m:
                mappa_schede[m.group(1)] = p
        except Exception:
            pass

for i, card in enumerate(cards, 1):
    h3 = card.find('h3')
    titolo = re.sub(r'\s+', ' ', h3.get_text(' ', strip=True)).strip() if h3 else ''
    scheda_id = card['id'].replace('card_', '')
    link_doc = card.find('a', href=re.compile(r'documento\d+\.html'))
    doc_id = re.search(r'documento(\d+)\.html', link_doc['href']).group(1) if link_doc else None
    
    cartella = mappa_schede.get(scheda_id)
    print(f"[{i:2d}] Scheda {scheda_id} | Doc ID: {doc_id}")
    print(f"     Titolo: {titolo}")
    
    if cartella:
        pdf_file = cartella / 'testo.pdf'
        has_pdf = pdf_file.exists() and pdf_file.stat().st_size > 0
        parsed_file = parsed_dir / f"{cartella.name}.json"
        has_parsed = parsed_file.exists()
        print(f"     Cartella: {cartella.name} | PDF: {has_pdf} ({pdf_file.stat().st_size if has_pdf else 0} bytes) | Parsato nel grafo: {has_parsed}")
    else:
        print("     Cartella: NON PRESENTE")
    print()
