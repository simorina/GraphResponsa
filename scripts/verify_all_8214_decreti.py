"""
Verifica millimetrica di tutti gli 8.214 Decreti sul portale del Consiglio Grande e Generale.
Scansiona tutte le 548 pagine di risultati e verifica che ogni singolo atto sia scaricato su disco.
Se ne trova uno mancante, lo scarica all'istante con scheda e PDF.
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
    "P0_tipo": "+Decreto",
}


def get_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def scarica_scheda_e_pdf(session, card):
    """Scarica scheda e PDF per una card se non già presente."""
    h3 = card.find("h3")
    titolo = re.sub(r"\s+", " ", h3.get_text(" ", strip=True)).strip() if h3 else ""
    scheda_id = card["id"].replace("card_", "")
    
    link_doc = card.find("a", href=re.compile(r"documento\d+\.html"))
    doc_id = re.search(r"documento(\d+)\.html", link_doc["href"]).group(1) if link_doc else None
    
    # Determina estremi
    m = re.match(r"(?P<tipo>Decreto\s+Delegato|Decreto\s+Legge|Decreto\s+Reggenziale|Decreto\s+Consiliare|Decreto|Errata\s+Corrige|Regolamento|Legge)\s*(?:[^\n\d]*)\s*n\.\s*(?P<numero>\d+(?:-[A-Za-z]+)?)\s*(?:/|\s+del\s+.*?\s+)?(?P<anno>\d{4})?", titolo, re.I)
    
    tipo_str = m.group("tipo") if m else "Decreto"
    num_str = m.group("numero") if m else scheda_id
    anno_str = m.group("anno") if (m and m.group("anno")) else None
    
    if not anno_str:
        m_a = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", titolo)
        anno_str = m_a.group(1) if m_a else "2000"
        
    id_norma = norma_id(tipo_str, num_str, int(anno_str))
    cartella = RAW / id_norma
    
    if (cartella / "scheda.json").exists() and (cartella / "testo.pdf").exists() and (cartella / "testo.pdf").stat().st_size > 0:
        return id_norma, False  # già presente
        
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
    
    # Scarica PDF
    if doc_id:
        url_download = f"{BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti/documento{doc_id}.pdf"
        r_pdf = session.get(url_download, timeout=30)
        if r_pdf.status_code == 200 and len(r_pdf.content) > 0:
            (cartella / "testo.pdf").write_bytes(r_pdf.content)
            
    (cartella / "scheda.json").write_text(json.dumps(scheda_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return id_norma, True  # scaricato ora


def verifica_intervallo_pagine(p_da, p_a):
    session = get_session()
    tot_atti = 0
    nuovi_scaricati = 0
    
    for pag in range(p_da, p_a + 1):
        params = dict(PARAMS_BASE, P0_pagina=str(pag))
        try:
            resp = session.get(ARCHIVIO, params=params, timeout=30)
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select('div[id^="card_"]')
            tot_atti += len(cards)
            for card in cards:
                _, scaricato = scarica_scheda_e_pdf(session, card)
                if scaricato:
                    nuovi_scaricati += 1
            if pag % 25 == 0 or pag == p_a:
                print(f"  Worker [{p_da}-{p_a}]: pagina {pag}/{p_a} completata ({tot_atti} atti verificati, {nuovi_scaricati} nuovi).")
        except Exception as e:
            print(f"  Worker [{p_da}-{p_a}]: errore a pagina {pag}: {e}")
            time.sleep(2)
            
    return tot_atti, nuovi_scaricati


def main():
    print("=== CONTROLLO TOTALE DI TUTTI GLI 8.214 DECRETI SUL PORTALE CGG ===")
    t0 = time.time()
    
    pagine_totali = 548
    num_workers = 4
    step = pagine_totali // num_workers
    ranges = []
    for i in range(num_workers):
        p_da = i * step + 1
        p_a = pagine_totali if i == num_workers - 1 else (i + 1) * step
        ranges.append((p_da, p_a))
        
    print(f"Lancio {num_workers} worker in parallelo su 548 pagine di Decreti: {ranges}\n")
    
    tot_atti_portale = 0
    tot_nuovi = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(verifica_intervallo_pagine, r[0], r[1]) for r in ranges]
        for f in concurrent.futures.as_completed(futures):
            atti, nuovi = f.result()
            tot_atti_portale += atti
            tot_nuovi += nuovi
            
    print("\n" + "=" * 60)
    print("=== RISULTATO VERIFICA INTEGRALE 8.214 DECRETI ===")
    print(f"Atti totali indicizzati dal portale: {tot_atti_portale:,d} su 548 pagine")
    print(f"Nuovi atti scaricati durante la verifica: {tot_nuovi:,d}")
    print(f"Tempo totale di scansione: {time.time() - t0:.2f}s")
    
    raw_dir = RAW
    decreti_disco = len([p for p in raw_dir.iterdir() if p.is_dir() and any(p.name.startswith(pref) for pref in ['D-', 'DD-', 'DC-', 'DL-', 'DR-', 'EC-'])])
    tot_disco = len(list(raw_dir.iterdir()))
    print(f"Decreti totali salvati su disco (data/raw/): {decreti_disco:,d}")
    print(f"Atti complessivi su disco (Leggi + Decreti): {tot_disco:,d}")
    print("=" * 60)


if __name__ == "__main__":
    main()
