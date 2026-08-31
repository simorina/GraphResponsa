"""
Benchmark per testare l'Agente AI di GraphResponsa sul Knowledge Graph di San Marino.
Valuta 5 scenari chiave:
1. Struttura di una Legge Costituzionale/Qualificata
2. Lettura puntuale di articolo e commi
3. Ricerca tematica/ibrida
4. Attraversamento delle citazioni e rinvii nel grafo
5. Negative test (norma inesistente / assenza di allucinazioni)
"""

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from agente.agente import rispondi

DOMANDE_BENCHMARK = [
    {
        "id": "BENCH-01",
        "categoria": "Struttura e Organizzazione Norma (Legge Qualificata)",
        "domanda": "Com'è strutturata la Legge Qualificata n. 186/2005 sui Capitani Reggenti e quanti articoli contiene?",
        "atteso": "Uso di struttura_norma, conteggio articoli e suddivisione per materie/rubriche."
    },
    {
        "id": "BENCH-02",
        "categoria": "Lettura Puntuale Articolo e Commi (Precisione Testuale)",
        "domanda": "Cosa stabilisce l'articolo 1 della Legge Costituzionale n. 1/2011 su Bandiera e Stemma ufficiale?",
        "atteso": "Uso di trova_norma o leggi_articolo, citazione esatta dei commi e descrizione dei simboli."
    },
    {
        "id": "BENCH-03",
        "categoria": "Ricerca Tematica e Ibrida (Materia Sanità/Lavoro)",
        "domanda": "Quali disposizioni sono previste per il lavoro agile a San Marino nella Legge 202/2020?",
        "atteso": "Uso di cerca_testo / leggi_articolo, riferimenti puntuali a L. 202/2020."
    },
    {
        "id": "BENCH-04",
        "categoria": "Attraversamento Relazioni Grafo (Citazioni e Rinvii)",
        "domanda": "Quali n1orme richiama la Legge Qualificata n. 184/2005 sul Congresso di Stato?",
        "atteso": "Uso di citazioni_da, individuazione delle leggi costituzionali citate nel preambolo/testo."
    },
    {
        "id": "BENCH-05",
        "categoria": "Controllo Allucinazioni e Fallback Negativo",
        "domanda": "Cosa prevede la normativa di San Marino per le licenze di navigazione di navi rompighiaccio nell'Oceano Artico?",
        "atteso": "Riconoscimento dell'assenza della disciplina nell'archivio senza allucinazioni o invenzioni."
    }
]


def esegui_benchmark():
    print("=" * 80)
    print("🚀 AVVIO BENCHMARK AGENTE AI GRAPHRESPONSA SU NEO4J")
    print(f"📊 Totale domande test: {len(DOMANDE_BENCHMARK)}")
    print("=" * 80 + "\n")

    risultati_finali = []

    for test in DOMANDE_BENCHMARK:
        print(f"\n[{test['id']}] Categoria: {test['categoria']}")
        print(f"❓ Domanda: {test['domanda']}")
        print(f"🎯 Obiettivo atteso: {test['atteso']}")
        print("-" * 80)

        t0 = time.time()
        strumenti_usati = []
        testo_risposta = []
        fonti = []
        fine_info = {}

        for evento in rispondi(test["domanda"]):
            tipo = evento.get("tipo")
            if tipo == "strumento":
                print(f"  🛠️  Chiamata Tool: {evento['nome']} -> {evento['argomenti']}")
                strumenti_usati.append(evento['nome'])
            elif tipo == "risultato":
                print(f"  📥 Risultato Tool: {evento['nome']} (elementi: {evento.get('quante')})")
            elif tipo == "testo":
                testo_risposta.append(evento["testo"])
            elif tipo == "fonti":
                fonti = evento.get("fonti", [])
            elif tipo == "fine":
                fine_info = evento
            elif tipo == "errore":
                print(f"  ❌ ERRORE: {evento.get('messaggio')}")

        t_elapsed = time.time() - t0
        risposta_str = "".join(testo_risposta).strip()

        print("\n💬 RISPOSTA DELL'AGENTE:")
        print(risposta_str)
        print(f"\n📚 Fonti ancorate: {len(fonti)}")
        for f in fonti[:4]:
            print(f"   - {f.get('norma')} | Art. {f.get('articolo')} c.{f.get('comma')}: {f.get('rubrica') or ''}")
        print(f"⏱️ Tempo: {t_elapsed:.2f}s | Token In: {fine_info.get('tokenIn', 0)} | Token Out: {fine_info.get('tokenOut', 0)} | Costo: ${fine_info.get('costo', 0)}")
        print("=" * 80)

        risultati_finali.append({
            "id": test["id"],
            "domanda": test["domanda"],
            "strumenti": strumenti_usati,
            "tempo": t_elapsed,
            "fonti_count": len(fonti),
            "risposta": risposta_str,
            "fine": fine_info
        })

    print("\n" + "=" * 80)
    print("🏆 RIEPILOGO BENCHMARK COMPLETATO")
    for r in risultati_finali:
        print(f"  - [{r['id']}] Tool usati: {r['strumenti']} | Fonti: {r['fonti_count']} | Tempo: {r['tempo']:.2f}s")
    print("=" * 80)


if __name__ == "__main__":
    esegui_benchmark()
