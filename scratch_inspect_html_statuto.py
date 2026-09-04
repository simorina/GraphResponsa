import requests
from bs4 import BeautifulSoup

url = 'https://www.consigliograndeegenerale.sm/on-line/home/archivio-leggi-decreti-e-regolamenti/documento17016469.html'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
r = requests.get(url, headers={'User-Agent': UA})
soup = BeautifulSoup(r.text, 'html.parser')

print('Title:', soup.title.get_text() if soup.title else '')

# Trova tutti i tag p, div con testo
body = soup.find('body')
text = body.get_text('\n', strip=True) if body else ''

print('\n--- PRIMI 1500 CARATTERI DEL LIBRO PRIMO DEGLI STATUTI ---')
print(text[:1500])
