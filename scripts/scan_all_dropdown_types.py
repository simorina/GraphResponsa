"""
Scansione e scaricamento integrale di TUTTE le voci del menu a tendina 'Tipo documento':
1. Legge
2. Legge Costituzionale
3. Legge Qualificata
4. Legge Revisione Costituzionale
5. Decreto
6. Decreto Reggenziale
7. Decreto Legge
8. Decreto Consiliare
9. Decreto Delegato
10. Regolamento
11. Notifica
12. Statuto
13. Verbale
14. Ordinanza
15. Errata Corrige
16. Non Definito
17. Tutti i tipi (controllo globale)
"""

import concurrent.futures
import json
import os
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "src"))
from comune import PREFISSI, norma_id

BASE = "https://www.consigliograndeegenerale.sm"
ARCHIVIO = f"{BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

OPZIONI_TENDINA = [
    ("+Legge", "Legge"),
    ("+Legge AND +Costituzionale", "Legge Costituzionale"),
    ("+Legge AND +Qualificata", "Legge Qualificata"),
    ("+Legge AND +Revisione AND +Costituziuonale", "Legge Revisione Costituzionale"),
    ("+Decreto", "Decreto"),
    ("+Decreto AND +Reggenziale", "Decreto Reggenziale"),
    ("+Decreto AND +Legge", "Decreto Legge"),
    ("+Decreto AND +Consiliare", "Decreto Consiliare"),
    ("+Decreto AND +Delegato", "Decreto Delegato"),
    ("+Regolamento", "Regolamento"),
    ("+Notifica", "Notifica"),
    ("+Statuto", "Statuto"),
    ("+Verbale", "Verbale"),
    ("+Ordinanza", "Ordinanza"),
    ("+Errata AND +Corrige", "Errata Corrige"),
    ("+Non AND +definito", "Non Definito"),
]

PARAMS_BASE = {
    "P0_path": "/home/tomcat/indicizzazione/indexleggi",
    "P0_paginazione": "15",
    "P0_pagina": "1",
    "P0_orderBy": "index_lucene,data_ordered,numero",
    "P0_order": "asc,desc,desc",
    "P0_operatorMustBe": "yes",
    "P0_title": "",
    "P0_numero": "",
    "P0_anno": "",
    "P0_data_gg": "",
    "P0_data_mm": "",
    "P0_data_aa": "",
    "annoiniziale": "",
    "annofinale": "",
    "P0_document": "",
    "P0_data_ordered": "",
    "indicericerca": "-1",
}


def get_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def scarica_card_se_mancante(session, card, fallback_tipo):
    """Scarica scheda.json e testo.pdf se non già su disco."""
    h3 = card.find("h3")
    titolo = re.sub(r"\s+", " ", h3.get_text(" ", strip=True)).strip() if h3 else ""
    scheda_id = card["id"].replace("card_", "")
    
    link_doc = card.find("a", href=re.compile(r"documento\d+\.html"))
    doc_id = re.search(r"documento(\d+)\.html", link_doc["href"]).group(1) if link_doc else None
    
    m = re.match(r"(?P<tipo>Legge\s+Costituzionale|Legge\s+Qualificata|Legge\s+Revisione\s+Costituzionale|Decreto\s+Delegato|Decreto\s+Legge|Decreto\s+Reggenziale|Decreto\s+Consiliare|Decreto|Regolamento|Notifica|Statuto|Verbale|Ordinanza|Errata\s+Corrige|Legge)\s*(?:[^\n\d]*)\s*n\.\s*(?P<numero>\d+(?:-[A-Za-z]+)?)\s*(?:/|\s+del\s+.*?\s+)?(?P<anno>\d{4})?", titolo, re.I)
    
    tipo_str = m.group("tipo") if m else fallback_tipo
    num_str = m.group("numero") if m else scheda_id
    anno_str = m.group("anno") if (m and m.group("anno")) else None
    
    if not anno_str:
        m_a = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", titolo)
        anno_str = m_a.group(1) if m_a else "2000"
        
    id_norma = norma_id(tipo_str, num_str, int(anno_str))
    cartella = RAW / id_norma
    
    if (cartella / "scheda.json").exists() and (cartella / "testo.pdf").exists() and (cartella / "testo.pdf").stat().st_size > 0:
        return id_norma, False
        
    cartella.mkdir(parents=True, exist_ok=True)
    
    url_scheda = f"{BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti/scheda{scheda_id}.html"
    url_doc = f"{BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti/documento{doc_id}.html" if doc_id else ""
    
    scheda_data = {
        "id": id_norma,
        "tipo": tipo_str,
        "numero": num_str,
        "anno": int(anno_str),
        "titolo": titolo,
        "urlScheda": url_scheda,
        "urlDocumento": url_doc,
    }
    
    if doc_id:
        url_download = f"{BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti/documento{doc_id}.pdf"
        try:
            r_pdf = session.get(url_download, timeout=30)
            if r_pdf.status_code == 200 and len(r_pdf.content) > 0:
                (cartella / "testo.pdf").write_bytes(r_pdf.content)
        except Exception:
            pass
            
    (cartella / "scheda.json").write_text(json.dumps(scheda_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return id_norma, True


def scansiona_categoria(valore_tipo, label_tipo):
    session = get_session()
    params_p1 = dict(PARAMS_BASE, P0_tipo=valore_tipo, P0_pagina="1")
    
    try:
        resp = session.get(ARCHIVIO, params=params_p1, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"Errore caricamento pag 1 per {label_tipo}: {e}")
        return label_tipo, 0, 0, 0
        
    cards_p1 = soup.select('div[id^="card_"]')
    if not cards_p1:
        return label_tipo, 0, 0, 0
        
    # Trova ultima pagina
    links_pag = soup.find_all("a", href=re.compile(r"P0_pagina="))
    pagine = [1]
    for a in links_pag:
        m = re.search(r"P0_pagina=(\d+)", a["href"])
        if m:
            pagine.append(int(m.group(1)))
            
    # Trova l'ultima pagina effettiva
    max_pag = max(pagine)
    while True:
        p_test = dict(PARAMS_BASE, P0_tipo=valore_tipo, P0_pagina=str(max_pag + 1))
        r_test = session.get(ARCHIVIO, params=p_test, timeout=30)
        s_test = BeautifulSoup(r_test.text, "html.parser")
        c_test = s_test.select('div[id^="card_"]')
        if c_test:
            max_pag += 1
        else:
            break
            
    tot_atti = 0
    nuovi_scaricati = 0
    
    for pag in range(1, max_pag + 1):
        params = dict(PARAMS_BASE, P0_tipo=valore_tipo, P0_pagina=str(pag))
        try:
            r = session.get(ARCHIVIO, params=params, timeout=30)
            s = BeautifulSoup(r.text, "html.parser")
            cards = s.select('div[id^="card_"]')
            tot_atti += len(cards)
            for card in cards:
                _, scaricato = scarica_card_se_mancante(session, card, label_tipo)
                if scaricato:
                    nuovi_scaricati += 1
        except Exception as e:
            print(f"  Errore pag {pag} in {label_tipo}: {e}")
            
    return label_tipo, tot_atti, max_pag, nuovi_scaricati


def main():
    print("=== SCANSIONE DI TUTTE LE 16 TIPOLOGIE DEL MENU A TENDINA CGG ===")
    t0 = time.time()
    
    risultati = []
    
    # Esegui in parallelo sulle tipologie
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(scansiona_categoria, val, lab): lab for val, lab in OPZIONI_TENDINA}
        for f in concurrent.futures.as_completed(futures):
            lab, tot_atti, tot_pagine, nuovi = f.result()
            risultati.append((lab, tot_atti, tot_pagine, nuovi))
            print(f"  -> [{lab:30s}]: {tot_atti:5,d} atti sul portale ({tot_pagine:3d} pag.) | Scaricati nuovi: {nuovi}")
            
    print("\n" + "=" * 70)
    print("=== BILANCIO GENERALE PER TUTTE LE VOCI DELLA TENDINA ===")
    print(f"{'Tipologia Atto':<32} | {'Atti sul Portale':<18} | {'Pagine':<8} | {'Scaricati Nuovi'}")
    print("-" * 70)
    
    tot_portale = 0
    tot_nuovi_globale = 0
    for lab, tot_atti, tot_pag, nuovi in sorted(risultati, key=lambda x: x[1], reverse=True):
        print(f"{lab:<32} | {tot_atti:18,d} | {tot_pag:8d} | {nuovi:d}")
        tot_portale += tot_atti
        tot_nuovi_globale += nuovi
        
    print("-" * 70)
    print(f"Tempo totale impiegato: {time.time() - t0:.2f}s")
    print(f"Totale complessivo atti su disco in data/raw/: {len(list(RAW.iterdir())):,d}")
    print("=" * 70)


if __name__ == "__main__":
    main()
