import re, json
import requests
from bs4 import BeautifulSoup
from pathlib import Path

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PARSED = ROOT / "data" / "parsed"

doc_statuti = [
    {"scheda_id": "17009068", "doc_id": "17016469", "titolo": "Statuto - Libro Primo dell'Arringo Generale", "anno": 1600, "tipo": "Statuto"},
    {"scheda_id": "17009069", "doc_id": "17016470", "titolo": "Statuto - Libro Secondo delle Cause Civili", "anno": 1600, "tipo": "Statuto"},
    {"scheda_id": "17009070", "doc_id": "17016471", "titolo": "Statuto - Libro Terzo dei Delitti (Cause Criminali)", "anno": 1600, "tipo": "Statuto"},
    {"scheda_id": "17009071", "doc_id": "17016472", "titolo": "Statuto - Libro Quarto delle Appellazioni", "anno": 1600, "tipo": "Statuto"},
    {"scheda_id": "17009072", "doc_id": "17016473", "titolo": "Statuto - Libro Quinto di Materie Diverse", "anno": 1600, "tipo": "Statuto"},
    {"scheda_id": "17009073", "doc_id": "17016474", "titolo": "Statuto - Libro Sesto dei Danni Dati per Pubblica Utilita'", "anno": 1600, "tipo": "Statuto"},
    {"scheda_id": "17009074", "doc_id": "17016475", "titolo": "Statuto per la Medaglia del Merito Militare e Civile", "anno": 1860, "tipo": "Statuto"},
    {"scheda_id": "17009075", "doc_id": "17016476", "titolo": "Statuto dell'Ordine Equestre di San Marino", "anno": 1859, "tipo": "Statuto"},
    {"scheda_id": "17009095", "doc_id": "17016496", "titolo": "Statuto Organici Ospedale degli Infermi e Ricovero", "anno": 1900, "tipo": "Statuto"},
    {"scheda_id": "17009155", "doc_id": "17016556", "titolo": "Statuto Congregazione di Carita' (Parte 1)", "anno": 1900, "tipo": "Statuto"},
    {"scheda_id": "17009156", "doc_id": "17016557", "titolo": "Statuto Congregazione di Carita' (Parte 2)", "anno": 1900, "tipo": "Statuto"},
    {"scheda_id": "17009252", "doc_id": "17016653", "titolo": "Statuto Congregazione di Carita' (Parte 3)", "anno": 1900, "tipo": "Statuto"},
]

s = requests.Session()
s.headers.update({'User-Agent': UA})

print("=== SCARICAMENTO E PARSING HTML DI TUTTI I 12 STATUTI ===")

for item in doc_statuti:
    doc_id = item["doc_id"]
    scheda_id = item["scheda_id"]
    titolo = item["titolo"]
    anno = item["anno"]
    tipo = item["tipo"]
    
    id_norma = f"S-{scheda_id}-{anno}"
    cartella = RAW / id_norma
    cartella.mkdir(parents=True, exist_ok=True)
    
    url_html = f"https://www.consigliograndeegenerale.sm/on-line/home/archivio-leggi-decreti-e-regolamenti/documento{doc_id}.html"
    url_scheda = f"https://www.consigliograndeegenerale.sm/on-line/home/archivio-leggi-decreti-e-regolamenti/scheda{scheda_id}.html"
    
    r = s.get(url_html, timeout=20)
    html_text = r.text
    (cartella / "testo.html").write_text(html_text, encoding="utf-8")
    
    # Salva scheda.json
    scheda_data = {
        "id": id_norma,
        "tipo": tipo,
        "numero": scheda_id,
        "anno": anno,
        "titolo": titolo,
        "urlScheda": url_scheda,
        "urlDocumento": url_html
    }
    (cartella / "scheda.json").write_text(json.dumps(scheda_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # Estrai testo pulito e rubriche
    soup = BeautifulSoup(html_text, 'html.parser')
    text_content = soup.get_text('\n', strip=True)
    
    # Segmentazione in rubriche / capitoli degli Statuti
    # Negli statuti le sezioni sono tipo "Rubrica I", "Capitolo I", "Rubrica 1", "Art. 1"
    righe = [line.strip() for line in text_content.split('\n') if line.strip()]
    
    articoli = []
    art_corrente = None
    commi_correnti = []
    
    re_rubrica = re.compile(r'^(?:Rubrica|Capitolo|Art\.?|Articolo)\s*([IVXLCDM\d]+|[Uu]nico)\.?\s*[-:.]?\s*(.*)$', re.I)
    
    for riga in righe:
        m = re_rubrica.match(riga)
        if m:
            if art_corrente:
                art_corrente["commi"] = commi_correnti or [{"numero": "1", "testo": art_corrente["rubrica"]}]
                articoli.append(art_corrente)
                commi_correnti = []
            
            num_rubrica = m.group(1)
            rubrica_txt = m.group(2) or riga
            art_corrente = {
                "numero": num_rubrica,
                "rubrica": rubrica_txt,
                "ordine": len(articoli) + 1,
                "commi": []
            }
        else:
            if art_corrente:
                commi_correnti.append({
                    "numero": str(len(commi_correnti) + 1),
                    "testo": riga
                })
            else:
                # Testo di preambolo
                pass
                
    if art_corrente:
        art_corrente["commi"] = commi_correnti or [{"numero": "1", "testo": art_corrente["rubrica"]}]
        articoli.append(art_corrente)
        
    if not articoli and len(text_content) > 50:
        # Fallback: articolo unico se non ci sono rubriche esplicite
        articoli.append({
            "numero": "1",
            "rubrica": titolo,
            "ordine": 1,
            "commi": [{"numero": "1", "testo": text_content[:5000]}]
        })
        
    parsed_data = {
        "id": id_norma,
        "tipo": tipo,
        "numero": int(scheda_id) if scheda_id.isdigit() else 1,
        "anno": anno,
        "titolo": titolo,
        "dataPubblicazione": None,
        "dataEntrataVigore": f"{anno}-01-01",
        "preambolo": "",
        "urlScheda": url_scheda,
        "urlDocumento": url_html,
        "articoli": articoli,
        "allegati": [],
        "citazioni": []
    }
    
    (PARSED / f"{id_norma}.json").write_text(json.dumps(parsed_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] {id_norma}: {len(articoli)} rubriche/articoli estratti -> {titolo}")

print("\nParsing di tutti i 12 Statuti completato con successo in data/parsed/!")
