"""
Benchmark su Casi Reali, Questioni Storiche e Dubbi Applicativi.
Interroga l'Agente AI di GraphResponsa simulando quesiti di cittadini, imprese e giuristi.
"""

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

load_dotenv(ROOT / ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from agente.agente import rispondi

CASI_REALI_BENCHMARK = [
    {
        "id": "CASO-01",
        "titolo": "Diritto Storico: Elettorato delle Donne e Riforma Famiglia",
        "domanda": "In quale anno e con quale legge le donne a San Marino hanno ottenuto per la prima volta l'estensione del diritto di voto, e quali principi ha introdotto la successiva riforma del diritto di famiglia del 1986?",
        "contesto": "Quesito storico-giuridico che richiede di identificare la L. 17/1959 e la L. 49/1986."
    },
    {
        "id": "CASO-02",
        "titolo": "Caso Pratico di Lavoro: Smart Working e Fornitura Dispositivi",
        "domanda": "Un'azienda a San Marino vuole attivare il lavoro agile per un programmatore. Il datore di lavoro è tenuto a fornire gli strumenti di lavoro o il dipendente può usare i propri? E quali sono le regole di recesso dall'accordo secondo la Legge 202/2020?",
        "contesto": "Consulenza aziendale giuslavoristica su L. 202/2020 (art. 3 e art. 4)."
    },
    {
        "id": "CASO-03",
        "titolo": "Diritto Costituzionale: Requisiti e Incompatibilità della Reggenza",
        "domanda": "Quali sono i requisiti di eleggibilità e le principali incompatibilità con la carica di Capitano Reggente previsti dalla Legge Costituzionale 185/2005 e dalla Legge Qualificata 186/2005?",
        "contesto": "Analisi istituzionale su fonti di rango costituzionale e qualificato."
    },
    {
        "id": "CASO-04",
        "titolo": "Caso d'Impresa: Incentivi per Giovani Imprenditori",
        "domanda": "Un gruppo di giovani intende avviare una nuova attività commerciale/tecnologica a San Marino: quali agevolazioni e requisiti prevede la Legge n. 178/2015 a sostegno dei giovani imprenditori?",
        "contesto": "Diritto dell'economia e incentivi all'autoimprenditorialità su L. 178/2015."
    }
]


def esegui_casi():
    print("=" * 85)
    print("⚖️  BENCHMARK CASI REALI, STORICI E DUBBI APPLICATIVI (GRAPHRESPONSA)")
    print(f"📋 Totale casi pratici da risolvere: {len(CASI_REALI_BENCHMARK)}")
    print("=" * 85 + "\n")

    resoconto = []

    for caso in CASI_REALI_BENCHMARK:
        print(f"\n[{caso['id']}] {caso['titolo']}")
        print(f"🏢 Caso/Domanda: \"{caso['domanda']}\"")
        print(f"🎯 Contesto: {caso['contesto']}")
        print("-" * 85)

        t0 = time.time()
        tools_chiamati = []
        testo = []
        fonti = []
        fine_dati = {}

        for ev in rispondi(caso["domanda"]):
            t = ev.get("tipo")
            if t == "strumento":
                print(f"  🛠️  Tool: {ev['nome']}({ev['argomenti']})")
                tools_chiamati.append(ev['nome'])
            elif t == "risultato":
                print(f"  📥 Risultato: {ev['nome']} -> {ev.get('quante')} record")
            elif t == "testo":
                testo.append(ev["testo"])
            elif t == "fonti":
                fonti = ev.get("fonti", [])
            elif t == "fine":
                fine_dati = ev
            elif t == "errore":
                print(f"  ❌ Errore: {ev.get('messaggio')}")

        t_tot = time.time() - t0
        risp_completa = "".join(testo).strip()

        print("\n📜 RISPOSTA MOTIVATA DELL'AGENTE:")
        print(risp_completa)
        print(f"\n📌 Fonti normative verificate ({len(fonti)} commi):")
        for f in fonti[:5]:
            print(f"   • {f.get('norma')} - Art. {f.get('articolo')} c.{f.get('comma')} ({f.get('rubrica') or 'N/A'})")

        print(f"\n⏱️ Tempo risposta: {t_tot:.2f}s | Token Totali: {fine_dati.get('tokenIn', 0) + fine_dati.get('tokenOut', 0)} | Costo: ${fine_dati.get('costo', 0)}")
        print("=" * 85)

        resoconto.append({
            "id": caso["id"],
            "titolo": caso["titolo"],
            "tempo": t_tot,
            "tools": tools_chiamati,
            "fonti": len(fonti),
            "costo": fine_dati.get("costo", 0)
        })

    print("\n" + "=" * 85)
    print("📊 RIEPILOGO FINALE CASI PRATICI E STORICI")
    for r in resoconto:
        print(f"  [{r['id']}] {r['titolo']}: {r['tempo']:.2f}s | Fonti: {r['fonti']} | Tool usati: {r['tools']}")
    print("=" * 85)


if __name__ == "__main__":
    esegui_casi()
