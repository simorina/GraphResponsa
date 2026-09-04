import requests, re
from bs4 import BeautifulSoup

url = 'https://www.consigliograndeegenerale.sm/on-line/home/archivio-leggi-decreti-e-regolamenti.html'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'

r = requests.get(url, headers={'User-Agent': UA})
soup = BeautifulSoup(r.text, 'html.parser')

print('=== TUTTI I SELECT NEL FORM DI RICERCA ===')
for s in soup.find_all('select'):
    print(f"\nSelect: name='{s.get('name')}' id='{s.get('id')}'")
    for opt in s.find_all('option'):
        val = opt.get('value')
        label = opt.get_text(strip=True)
        print(f"  Option: value='{val}' | label='{label}'")
