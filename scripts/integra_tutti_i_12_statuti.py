"""
Integrazione completa di TUTTI i 12 Statuti della Repubblica di San Marino:
1. Libro Primo dell'Arringo Generale (1600)
2. Libro Secondo delle Cause Civili (1600)
3. Libro Terzo dei Delitti - Cause Criminali (1600)
4. Libro Quarto delle Appellazioni (1600)
5. Libro Quinto di Materie Diverse (1600)
6. Libro Sesto dei Danni Dati per Pubblica Utilita' (1600)
7. Statuto Medaglia del Merito Militare e Civile (1860)
8. Statuto dell'Ordine Equestre di San Marino (1859)
9. Statuto Organici Ospedale degli Infermi (1900)
10-12. Statuti Congregazione di Carita' (1900)
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import pymupdf
import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PARSED = ROOT / "data" / "parsed"
RAW.mkdir(parents=True, exist_ok=True)
PARSED.mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / ".env")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

STATUTI = [
    {"scheda_id": "17009068", "doc_id": "17016469", "numero": "1", "anno": 1600, "titolo": "Statuto del 1600 - Libro Primo dell'Arringo Generale"},
    {"scheda_id": "17009069", "doc_id": "17016470", "numero": "2", "anno": 1600, "titolo": "Statuto del 1600 - Libro Secondo delle Cause Civili"},
    {"scheda_id": "17009070", "doc_id": "17016471", "numero": "3", "anno": 1600, "titolo": "Statuto del 1600 - Libro Terzo dei Delitti e Cause Criminali"},
    {"scheda_id": "17009071", "doc_id": "17016472", "numero": "4", "anno": 1600, "titolo": "Statuto del 1600 - Libro Quarto delle Appellazioni"},
    {"scheda_id": "17009072", "doc_id": "17016473", "numero": "5", "anno": 1600, "titolo": "Statuto del 1600 - Libro Quinto di Materie Diverse"},
    {"scheda_id": "17009073", "doc_id": "17016474", "numero": "6", "anno": 1600, "titolo": "Statuto del 1600 - Libro Sesto dei Danni Dati per Pubblica Utilita'"},
    {"scheda_id": "17009074", "doc_id": "17016475", "numero": "7", "anno": 1860, "titolo": "Statuto per la Medaglia del Merito Militare e Civile"},
    {"scheda_id": "17009075", "doc_id": "17016476", "numero": "8", "anno": 1859, "titolo": "Statuto dell'Ordine Equestre di San Marino"},
    {"scheda_id": "17009095", "doc_id": "17016496", "numero": "9", "anno": 1900, "titolo": "Statuto Organici Ospedale degli Infermi e Ricovero"},
    {"scheda_id": "17009155", "doc_id": "17016556", "numero": "10", "anno": 1900, "titolo": "Statuto Congregazione di Carita' - Parte 1"},
    {"scheda_id": "17009156", "doc_id": "17016557", "numero": "11", "anno": 1900, "titolo": "Statuto Congregazione di Carita' - Parte 2"},
    {"scheda_id": "17009252", "doc_id": "17016653", "numero": "12", "anno": 1900, "titolo": "Statuto Congregazione di Carita' - Parte 3"},
]


def scarica_e_parsa_statuti():
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    
    print("=== SCARICAMENTO E PARSING DEI 12 STATUTI DI SAN MARINO ===")
    
    tutti_parsed = []
    
    for s_info in STATUTI:
        doc_id = s_info["doc_id"]
        scheda_id = s_info["scheda_id"]
        num = s_info["numero"]
        anno = s_info["anno"]
        titolo = s_info["titolo"]
        
        id_norma = f"S-{num}-{anno}"
        cartella = RAW / id_norma
        cartella.mkdir(parents=True, exist_ok=True)
        
        url_doc = f"https://www.consigliograndeegenerale.sm/on-line/home/archivio-leggi-decreti-e-regolamenti/documento{doc_id}.html"
        url_scheda = f"https://www.consigliograndeegenerale.sm/on-line/home/archivio-leggi-decreti-e-regolamenti/scheda{scheda_id}.html"
        
        # 1. Scarica PDF binario reale
        r = session.get(url_doc, timeout=25)
        pdf_bytes = r.content
        (cartella / "testo.pdf").write_bytes(pdf_bytes)
        
        scheda_data = {
            "id": id_norma,
            "tipo": "Statuto",
            "numero": int(num),
            "anno": anno,
            "titolo": titolo,
            "urlScheda": url_scheda,
            "urlDocumento": url_doc
        }
        (cartella / "scheda.json").write_text(json.dumps(scheda_data, ensure_ascii=False, indent=2), encoding="utf-8")
        
        # 2. Estrazione testo con PyMuPDF
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        pagine_testo = []
        for pag in doc:
            pagine_testo.append(pag.get_text())
        testo_completo = "\n".join(pagine_testo)
        
        # 3. Parsing Rubriche / Articoli
        re_rubrica = re.compile(r"^(?:RUBRICA|CAPITOLO|ART\.?|ARTICOLO)\s*([IVXLCDM\d]+|[Uu]nico)\.?\s*[-:.]?\s*(.*)$", re.I)
        
        righe = [line.strip() for line in testo_completo.split("\n") if line.strip()]
        articoli = []
        art_corrente = None
        commi_correnti = []
        
        for riga in righe:
            m = re_rubrica.match(riga)
            if m:
                if art_corrente:
                    art_corrente["commi"] = commi_correnti or [{"numero": "1", "testo": art_corrente["rubrica"]}]
                    articoli.append(art_corrente)
                    commi_correnti = []
                num_rub = m.group(1)
                rub_txt = m.group(2) or riga
                art_corrente = {
                    "id": f"{id_norma}_art{num_rub}",
                    "numero": str(num_rub),
                    "rubrica": rub_txt[:300],
                    "ordine": len(articoli) + 1,
                    "commi": []
                }
            else:
                if art_corrente:
                    commi_correnti.append({
                        "id": f"{art_corrente['id']}_c{len(commi_correnti) + 1}",
                        "numero": str(len(commi_correnti) + 1),
                        "testo": riga
                    })
                    
        if art_corrente:
            art_corrente["commi"] = commi_correnti or [{"numero": "1", "testo": art_corrente["rubrica"]}]
            articoli.append(art_corrente)
            
        if not articoli:
            articoli.append({
                "id": f"{id_norma}_art1",
                "numero": "1",
                "rubrica": titolo,
                "ordine": 1,
                "commi": [{"id": f"{id_norma}_art1_c1", "numero": "1", "testo": testo_completo[:3000]}]
            })
            
        parsed_data = {
            "id": id_norma,
            "tipo": "Statuto",
            "numero": int(num),
            "anno": anno,
            "titolo": titolo,
            "dataPubblicazione": None,
            "dataEntrataVigore": f"{anno}-01-01",
            "preambolo": f"Antichi Statuti della Serenissima Repubblica di San Marino ({titolo})",
            "urlScheda": url_scheda,
            "urlDocumento": url_doc,
            "articoli": articoli,
            "allegati": [],
            "citazioni": []
        }
        
        (PARSED / f"{id_norma}.json").write_text(json.dumps(parsed_data, ensure_ascii=False, indent=2), encoding="utf-8")
        tutti_parsed.append(parsed_data)
        print(f"  -> {id_norma}: {len(doc)} pagine, {len(articoli)} rubriche/articoli parsati -> '{titolo}'")
        
    return tutti_parsed


def carica_nel_grafo_neo4j(statuti_parsed):
    print("\n=== CARICAMENTO NEL GRAFO NEO4J AURA ===")
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])
    )
    
    with driver.session() as s:
        for st in statuti_parsed:
            nid = st["id"]
            s.run("""
                MERGE (n:Norma {id: $id})
                SET n:Statuto,
                    n.tipo = $tipo,
                    n.numero = $numero,
                    n.anno = $anno,
                    n.titolo = $titolo,
                    n.dataEntrataVigore = date($dataEntrataVigore),
                    n.preambolo = $preambolo,
                    n.urlScheda = $urlScheda,
                    n.urlDocumento = $urlDocumento,
                    n.caricata = true
            """, {
                "id": nid, "tipo": st["tipo"], "numero": st["numero"],
                "anno": st["anno"], "titolo": st["titolo"],
                "dataEntrataVigore": st["dataEntrataVigore"],
                "preambolo": st["preambolo"],
                "urlScheda": st["urlScheda"], "urlDocumento": st["urlDocumento"]
            })
            
            # Carica articoli e commi
            for art in st["articoli"]:
                aid = f"{nid}_{art['numero']}"
                s.run("""
                    MATCH (n:Norma {id: $normaId})
                    MERGE (a:Articolo {id: $artId})
                    SET a.numero = $numero,
                        a.rubrica = $rubrica,
                        a.ordine = $ordine
                    MERGE (n)-[:HA_ARTICOLO]->(a)
                """, {
                    "normaId": nid, "artId": aid, "numero": str(art["numero"]),
                    "rubrica": art["rubrica"], "ordine": art["ordine"]
                })
                
                for c in art["commi"]:
                    cid = f"{aid}_c{c['numero']}"
                    s.run("""
                        MATCH (a:Articolo {id: $artId})
                        MERGE (cm:Comma {id: $commaId})
                        SET cm.numero = $numero,
                            cm.testo = $testo
                        MERGE (a)-[:HA_COMMA]->(cm)
                    """, {
                        "artId": aid, "commaId": cid,
                        "numero": str(c["numero"]), "testo": c["testo"]
                    })
            print(f"  [Neo4j OK] Caricato '{st['titolo']}' ({len(st['articoli'])} articoli) nel Grafo!")
            
    driver.close()
    print("\nTutti i 12 Statuti sono ora vivi e vegeti nel Knowledge Graph!")


if __name__ == "__main__":
    statuti = scarica_e_parsa_statuti()
    carica_nel_grafo_neo4j(statuti)
