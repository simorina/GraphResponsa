"""
Genera un benchmark di valutazione per l'agente.

Il principio: le domande NON si inventano, si derivano dal grafo. Per ogni riga
si parte da un comma reale gia' caricato, e da quello si ricava una domanda la
cui risposta e' contenuta in quel comma e in nessun altro posto. Cosi' la
risposta attesa e' verificabile aprendo il PDF alla pagina giusta, e il
benchmark misura il recupero: l'agente sa ritrovare quel comma partendo da una
domanda posta con parole diverse?

Tre famiglie di domande:

  contenuto   85 righe, generate da un comma vero. Misurano la ricerca.
  struttura   10 righe, costruite meccanicamente dal grafo (quanti articoli ha
              la norma X, che rubrica ha l'articolo N). La risposta attesa e'
              esatta per costruzione, senza passare da un modello.
  negative     5 righe, materie che l'ordinamento sammarinese non disciplina.
              La risposta giusta e' «non e' in archivio»: misurano il presidio
              anti-allucinazione, non il recupero.

    python scripts/genera_benchmark.py
"""

import csv
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

ISTRUZIONI = """Ricevi il testo di un comma della normativa di San Marino.

Scrivi UNA domanda e la sua risposta, rispettando queste regole:

1. La domanda deve essere posta come la porrebbe un cittadino o un
   professionista, in italiano corrente. NON deve ricalcare le parole del
   comma: se il comma dice "soggiorni culturali", la domanda puo' dire
   "vacanze studio". E' proprio questo che il benchmark deve misurare.

2. La domanda NON deve citare la norma. Niente "secondo la L. 202/2020...":
   deve essere rispondibile solo cercando nel merito.

3. La risposta deve stare INTERAMENTE dentro il comma che ti do. Non
   aggiungere nulla che non ci sia scritto. Se il comma non contiene un fatto
   verificabile e autoconclusivo, rispondi esattamente: SCARTA

4. La risposta deve essere una frase secca, max 30 parole, con il dato
   concreto (il termine, la cifra, il requisito, l'organo competente).

Rispondi SOLO con questo JSON, senza altro testo:
{"domanda": "...", "risposta": "..."}
oppure
{"scarta": true}
"""


def genera(comma, modello):
    contesto = (f"Norma: {comma['titolo']}\n"
                f"Articolo {comma['articolo']}"
                f"{' (' + comma['rubrica'] + ')' if comma.get('rubrica') else ''}, "
                f"comma {comma['comma']}\n\n{comma['testo']}")
    r = modello.invoke([("system", ISTRUZIONI), ("human", contesto)])
    testo = r.content if isinstance(r.content, str) else "".join(
        b.get("text", "") for b in r.content if isinstance(b, dict))
    m = re.search(r"\{.*\}", testo, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    if d.get("scarta") or not d.get("domanda") or not d.get("risposta"):
        return None
    return d


def domande_struttura(driver, db):
    """Dieci domande la cui risposta e' esatta per costruzione."""
    righe = []
    with driver.session(database=db) as s:
        for r in s.run("""
            MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)
            WHERE n.caricata AND n.anno >= 2000
            WITH n, count(a) AS quanti WHERE quanti >= 8
            RETURN n.id AS norma, n.titolo AS titolo, n.tipo AS tipo,
                   n.numero AS numero, n.anno AS anno, quanti
            ORDER BY rand() LIMIT 5
        """):
            righe.append({
                "categoria": "struttura",
                "domanda": f"Quanti articoli ha {r['tipo']} {r['numero']}/{r['anno']}?",
                "risposta": f"{r['quanti']} articoli.",
                "norma": r["norma"], "articolo": "", "comma": "",
            })
        for r in s.run("""
            MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)
            WHERE n.caricata AND n.anno >= 2000 AND a.rubrica IS NOT NULL
              AND size(a.rubrica) > 12
            RETURN n.id AS norma, n.tipo AS tipo, n.numero AS numero, n.anno AS anno,
                   a.numero AS articolo, a.rubrica AS rubrica
            ORDER BY rand() LIMIT 5
        """):
            righe.append({
                "categoria": "struttura",
                "domanda": f"Di cosa tratta l'articolo {r['articolo']} di "
                           f"{r['tipo']} {r['numero']}/{r['anno']}?",
                "risposta": r["rubrica"],
                "norma": r["norma"], "articolo": r["articolo"], "comma": "",
            })
    return righe


NEGATIVE = [
    "Quali requisiti deve avere una nave rompighiaccio per operare in Artico?",
    "Come si ottiene la licenza per l'estrazione mineraria offshore?",
    "Qual e' la disciplina sammarinese del trasporto ferroviario ad alta velocita'?",
    "Quali sono i limiti di pesca nelle acque territoriali della Repubblica?",
    "Come si registra un marchio presso l'ufficio brevetti dell'Unione Europea?",
]


def main():
    from langchain_anthropic import ChatAnthropic
    from neo4j import GraphDatabase

    candidati = json.loads((OUT / "candidati_benchmark.json").read_text(encoding="utf-8"))
    modello = ChatAnthropic(model="claude-haiku-4-5", max_tokens=600,
                            api_key=os.environ["ANTHROPIC_API_KEY"])

    print(f"Genero le domande di contenuto da {len(candidati)} commi...")
    righe, scartati, t0 = [], 0, time.time()
    for i, c in enumerate(candidati, 1):
        try:
            d = genera(c, modello)
        except Exception as e:
            print(f"  [{i}] errore: {type(e).__name__}")
            d = None
        if not d:
            scartati += 1
            continue
        righe.append({
            "categoria": "contenuto",
            "domanda": d["domanda"].strip(),
            "risposta": d["risposta"].strip(),
            "norma": c["norma"], "articolo": c["articolo"], "comma": c["comma"],
        })
        if i % 15 == 0:
            print(f"  {i}/{len(candidati)}  tenute {len(righe)}, scartate {scartati}")

    print(f"Contenuto: {len(righe)} domande in {time.time()-t0:.0f}s "
          f"({scartati} commi scartati perche' non autoconclusivi)")

    drv = GraphDatabase.driver(os.environ["NEO4J_URI"],
                               auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    strutturali = domande_struttura(drv, os.environ.get("NEO4J_DATABASE", "neo4j"))
    drv.close()
    print(f"Struttura: {len(strutturali)} domande")

    righe += strutturali
    for q in NEGATIVE:
        righe.append({"categoria": "negativa", "domanda": q,
                      "risposta": "L'archivio non contiene disposizioni in materia.",
                      "norma": "", "articolo": "", "comma": ""})
    print(f"Negative: {len(NEGATIVE)} domande")

    # Il PDF e' la fonte che si apre per verificare: senza, la riga non serve.
    finali = []
    for i, r in enumerate(righe[:100], 1):
        pdf = f"data/raw/{r['norma']}/testo.pdf" if r["norma"] else ""
        if pdf and not (ROOT / pdf).exists():
            continue
        riferimento = r["norma"]
        if r["articolo"]:
            riferimento += f" art. {r['articolo']}"
        if r["comma"]:
            riferimento += f" c. {r['comma']}"
        finali.append({
            "id": f"B{i:03d}", "categoria": r["categoria"],
            "domanda": r["domanda"], "risposta": r["risposta"],
            "riferimento": riferimento, "fonte": pdf,
        })

    dove = OUT / "benchmark_100.csv"
    with open(dove, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["id", "categoria", "domanda", "risposta",
                                          "riferimento", "fonte"], delimiter=";")
        w.writeheader()
        w.writerows(finali)
    print(f"\n{len(finali)} righe scritte in {dove}")


if __name__ == "__main__":
    main()
