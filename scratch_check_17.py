import requests, re
from bs4 import BeautifulSoup

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ARCHIVIO = 'https://www.consigliograndeegenerale.sm/on-line/home/archivio-leggi-decreti-e-regolamenti.html'

opzioni = [
    ('+Legge', 'Legge Ordinaria'),
    ('+Legge AND +Costituzionale', 'Legge Costituzionale'),
    ('+Legge AND +Qualificata', 'Legge Qualificata'),
    ('+Legge AND +Revisione AND +Costituziuonale', 'Legge Revisione Costituzionale'),
    ('+Decreto', 'Decreto Generale'),
    ('+Decreto AND +Reggenziale', 'Decreto Reggenziale'),
    ('+Decreto AND +Legge', 'Decreto Legge'),
    ('+Decreto AND +Consiliare', 'Decreto Consiliare'),
    ('+Decreto AND +Delegato', 'Decreto Delegato'),
    ('+Regolamento', 'Regolamento'),
    ('+Notifica', 'Notifica'),
    ('+Statuto', 'Statuto'),
    ('+Verbale', 'Verbale'),
    ('+Ordinanza', 'Ordinanza'),
    ('+Errata AND +Corrige', 'Errata Corrige'),
    ('+Non AND +definito', 'Non Definito'),
    ('', 'TUTTI I TIPI (TOTALE PORTALE)')
]

params_base = {
    'P0_path': '/home/tomcat/indicizzazione/indexleggi',
    'P0_paginazione': '15',
    'P0_pagina': '1',
    'P0_orderBy': 'index_lucene,data_ordered,numero',
    'P0_order': 'asc,desc,desc',
    'P0_operatorMustBe': 'yes',
    'P0_title': '',
    'P0_numero': '',
    'P0_anno': '',
    'P0_data_gg': '',
    'P0_data_mm': '',
    'P0_data_aa': '',
    'annoiniziale': '',
    'annofinale': '',
    'P0_document': '',
    'P0_data_ordered': '',
    'indicericerca': '-1',
}

session = requests.Session()
session.headers.update({'User-Agent': UA})

print('=== CENSIMENTO INTEGRALE DELLE 17 VOCI DEL MENU A TENDINA CGG ===')
print(f'{"Voce nel Menu":<32} | {"Pagine":<8} | {"Stima Atti sul Portale"}')
print('-' * 65)

for val, lab in opzioni:
    p = dict(params_base, P0_tipo=val)
    try:
        r = session.get(ARCHIVIO, params=p, timeout=25)
        s = BeautifulSoup(r.text, 'html.parser')
        cards = s.select('div[id^="card_"]')
        
        if not cards:
            print(f'{lab:<32} | {0:8d} | 0 atti')
            continue
            
        links = s.find_all('a', href=re.compile(r'P0_pagina='))
        pags = [1]
        for a in links:
            m = re.search(r'P0_pagina=(\d+)', a['href'])
            if m:
                pags.append(int(m.group(1)))
        max_p = max(pags)
        
        # se c'è un'ultima pagina controlliamo quanti atti ha
        p_last = dict(params_base, P0_tipo=val, P0_pagina=str(max_p))
        r_last = session.get(ARCHIVIO, params=p_last, timeout=25)
        s_last = BeautifulSoup(r_last.text, 'html.parser')
        cards_last = s_last.select('div[id^="card_"]')
        
        tot_stimato = (max_p - 1) * 15 + len(cards_last)
        print(f'{lab:<32} | {max_p:8d} | {tot_stimato:6,d} atti')
    except Exception as e:
        print(f'{lab:<32} | Errore: {e}')

print('-' * 65)
