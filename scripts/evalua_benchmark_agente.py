"""
Script di valutazione automatica del Benchmark (400 quesiti) con l'Agente Giuridico.
Esegue i quesiti del file benchmark.csv, valuta le risposte rispetto al ground-truth,
misura l'accuratezza delle citazioni normative, la latenza e salva i risultati in CSV.

Uso:
    # Valutazione rapida su campione (es. 10 domande):
    python scripts/evalua_benchmark_agente.py --limit 10

    # Valutazione completa:
    python scripts/evalua_benchmark_agente.py
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CSV_IN = ROOT / "benchmark.csv"
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
CSV_OUT = OUT / "benchmark_valutazione_400.csv"

sys.path.insert(0, str(ROOT / "src"))
from agente.agente import rispondi


def valuta_accuratezza(risposta_agente: str, risposta_attesa: str, tools_usati: list) -> dict:
    """Calcola metriche di accuratezza, presenza di riferimenti normativi e coerenza."""
    # Estrai estremi normativi dalla risposta attesa
    m_leggi = re.findall(r"(?:Legge|Decreto|DD|DL|DR|DC|Art\.|Articolo)\s*\d+(?:/\d+)?", risposta_attesa, re.I)
    
    score_norme = 0.0
    if m_leggi:
        trovate = sum(1 for rif in m_leggi if rif.lower() in risposta_agente.lower())
        score_norme = trovate / len(m_leggi)
    else:
        score_norme = 1.0 if len(risposta_agente) > 50 else 0.5
        
    # Verifica che la risposta non sia vuota o un messaggio di errore generico
    ha_risposto = len(risposta_agente.strip()) > 30 and "errore interno" not in risposta_agente.lower()
    ha_usato_tools = len(tools_usati) > 0
    
    # Punteggio sintetico (0-100)
    punteggio = 0
    if ha_risposto:
        punteggio += 40
    if ha_usato_tools:
        punteggio += 20
    punteggio += int(score_norme * 40)
    
    giudizio = "ECCELLENTE" if punteggio >= 85 else ("BUONO" if punteggio >= 65 else "DA_REVISIONARE")
    
    return {
        "punteggio": punteggio,
        "giudizio": giudizio,
        "score_normativo": round(score_norme, 2),
        "ha_risposto": ha_risposto,
        "num_tools": len(tools_usati)
    }


def interroga_agente(domanda: str):
    """Esegue l'agente e raccoglie la risposta completa e i tool chiamati."""
    testo_chunks = []
    tools_usati = []
    
    for evento in rispondi(domanda):
        t = evento.get("tipo")
        if t == "testo":
            testo_chunks.append(evento.get("contenuto", ""))
        elif t == "strumento":
            tools_usati.append(evento.get("nome", ""))
            
    risposta_completa = "".join(testo_chunks).strip()
    return risposta_completa, tools_usati


def esegui_benchmark(limit: int = None, offset: int = 0):
    print(f"Caricamento benchmark da {CSV_IN}...")
    with open(CSV_IN, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        
    tot_disponibili = len(reader)
    quesiti_da_eseguire = reader[offset : (offset + limit) if limit else tot_disponibili]
    print(f"Avvio test su {len(quesiti_da_eseguire)} domande (totale nel dataset: {tot_disponibili})...\n")
    
    risultati = []
    t_start = time.time()
    for i, q in enumerate(quesiti_da_eseguire, 1):
        q_id = q.get("id", i)
        domanda = q["domanda"]
        risposta_attesa = q["risposta"]
        cat = q.get("categoria", "")
        stile = q.get("stile", "")
        
        print(f"[{i}/{len(quesiti_da_eseguire)}] [ID {q_id}] ({cat} - {stile})")
        print(f"  Q: {domanda}")
        
        t0 = time.time()
        try:
            risposta_agente, tools_usati = interroga_agente(domanda)
            lat = round(time.time() - t0, 2)
            
            val = valuta_accuratezza(risposta_agente, risposta_attesa, tools_usati)
            print(f"  -> Giudizio: {val['giudizio']} (Score: {val['punteggio']}/100 | Latenza: {lat}s | Tools: {tools_usati})")
            print(f"  -> Estratto risposta: {risposta_agente[:120]}...\n")
            
            risultati.append({
                "id": q_id,
                "domanda": domanda,
                "categoria": cat,
                "stile": stile,
                "risposta_attesa": risposta_attesa,
                "risposta_agente": risposta_agente,
                "punteggio": val["punteggio"],
                "giudizio": val["giudizio"],
                "score_normativo": val["score_normativo"],
                "tools_usati": ", ".join(tools_usati),
                "latenza_sec": lat
            })
            
        except Exception as e:
            print(f"  -> ERRORE: {e}\n")
            risultati.append({
                "id": q_id,
                "domanda": domanda,
                "categoria": cat,
                "stile": stile,
                "risposta_attesa": risposta_attesa,
                "risposta_agente": f"ERRORE: {e}",
                "punteggio": 0,
                "giudizio": "ERRORE",
                "score_normativo": 0.0,
                "tools_usati": "",
                "latenza_sec": 0
            })

    # Salvataggio su CSV di valutazione
    fieldnames = [
        "id", "categoria", "stile", "punteggio", "giudizio", 
        "latenza_sec", "score_normativo", "tools_usati", 
        "domanda", "risposta_attesa", "risposta_agente"
    ]
    with open(CSV_OUT, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(risultati)
        
    tempo_tot = round(time.time() - t_start, 2)
    media_score = round(sum(r["punteggio"] for r in risultati) / len(risultati), 1) if risultati else 0
    eccellenti = sum(1 for r in risultati if r["giudizio"] == "ECCELLENTE")
    buoni = sum(1 for r in risultati if r["giudizio"] == "BUONO")
    
    print("=" * 70)
    print("=== RISULTATO FINALE DEL BENCHMARK ===")
    print(f"Domande testate:         {len(risultati)}")
    print(f"Punteggio Medio:         {media_score} / 100")
    print(f"Risposte Eccellenti:     {eccellenti} ({round(eccellenti/len(risultati)*100, 1)}%)")
    print(f"Risposte Buone:          {buoni} ({round(buoni/len(risultati)*100, 1)}%)")
    print(f"Tempo Totale:            {tempo_tot}s (Media: {round(tempo_tot/len(risultati), 2)}s per domanda)")
    print(f"Report dettagliato CSV:  {CSV_OUT}")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Esegui benchmark delle risposte dell'agente.")
    parser.add_argument("--limit", type=int, default=10, help="Numero massimo di domande da testare.")
    parser.add_argument("--offset", type=int, default=0, help="Indice iniziale da cui partire.")
    args = parser.parse_args()
    
    esegui_benchmark(limit=args.limit, offset=args.offset)
