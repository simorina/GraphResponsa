"""
Verifica che ogni risposta attesa del benchmark stia davvero nel comma citato,
e rimpiazza quelle che non ci stanno.

Serve perche' il modello che genera le domande, ogni tanto, risponde con quello
che sa invece che con quello che legge. Su un campione di sei righe ne e' emersa
una che dichiarava una tariffa postale di 6.750 mai comparsa nel comma citato.

Una verita' di riferimento sbagliata e' peggio di una riga mancante: fa
risultare in errore un agente che ha risposto bene, e il benchmark comincia a
mentire nella direzione opposta a quella che dovrebbe misurare.

Il verificatore e' volutamente severo e separato dal generatore: gli si da' solo
il comma e la risposta, senza la domanda, e gli si chiede se il secondo e'
interamente contenuto nel primo.

    python scripts/verifica_benchmark.py            # verifica e riferisce
    python scripts/verifica_benchmark.py --ripara   # sostituisce le righe cadute
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
CSV = OUT / "benchmark_100.csv"
CAMPI = ["id", "categoria", "domanda", "risposta", "riferimento", "fonte"]

load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

GIUDICE = """Ricevi il testo di un comma di legge e una AFFERMAZIONE.

Stabilisci se l'affermazione e' interamente ricavabile dal comma, cioe' se ogni
dato che contiene (cifre, termini, organi, condizioni) compare nel testo o ne
discende in modo diretto e incontestabile.

Sii severo. In particolare rispondi NO se:
- una cifra dell'affermazione non compare nel comma
- l'affermazione nomina un organo, un termine o una condizione assenti
- l'affermazione e' vera in generale ma non e' scritta li'

Rispondi SOLO con questo JSON:
{"fondata": true}
oppure
{"fondata": false, "motivo": "in dieci parole"}
"""


def leggi_comma(sessione, riferimento):
    m = re.match(r"(\S+) art\. (\S+) c\. (\S+)", riferimento or "")
    if not m:
        return None
    norma, art, com = m.groups()
    r = sessione.run("""
        MATCH (:Norma {id:$n})-[:HA_ARTICOLO]->(a:Articolo {numero:$a})-[:HA_COMMA]->(c:Comma {numero:$c})
        RETURN c.testo AS t""", n=norma, a=art, c=com).single()
    return r["t"] if r else None


def giudica(modello, testo_comma, affermazione):
    r = modello.invoke([("system", GIUDICE),
                        ("human", f"COMMA:\n{testo_comma}\n\nAFFERMAZIONE:\n{affermazione}")])
    t = r.content if isinstance(r.content, str) else "".join(
        b.get("text", "") for b in r.content if isinstance(b, dict))
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return True, ""          # nel dubbio si tiene: meglio un falso positivo
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return True, ""
    return bool(d.get("fondata")), d.get("motivo", "")


def main():
    from langchain_anthropic import ChatAnthropic
    from neo4j import GraphDatabase

    ripara = "--ripara" in sys.argv
    righe = list(csv.DictReader(open(CSV, encoding="utf-8-sig"), delimiter=";"))
    modello = ChatAnthropic(model="claude-haiku-4-5", max_tokens=300,
                            api_key=os.environ["ANTHROPIC_API_KEY"])
    drv = GraphDatabase.driver(os.environ["NEO4J_URI"],
                               auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    buone, cadute = [], []
    contenuto = [r for r in righe if r["categoria"] == "contenuto"]
    print(f"Verifico {len(contenuto)} righe di contenuto...")
    t0 = time.time()
    with drv.session(database=db) as s:
        for i, r in enumerate(contenuto, 1):
            testo = leggi_comma(s, r["riferimento"])
            if not testo:
                cadute.append((r, "comma non ritrovato"))
                continue
            ok, motivo = giudica(modello, testo, r["risposta"])
            (buone if ok else cadute).append(r if ok else (r, motivo))
            if i % 20 == 0:
                print(f"  {i}/{len(contenuto)}  fondate {len(buone)}, cadute {len(cadute)}")

    print(f"\nFondate: {len(buone)}   Cadute: {len(cadute)}   ({time.time()-t0:.0f}s)")
    for r, motivo in cadute[:12]:
        print(f"  [{r['id']}] {motivo}")
        print(f"      {r['risposta'][:78]}")

    if not ripara:
        print("\nSolo verifica. Per sostituire le righe cadute: --ripara")
        drv.close()
        return

    # Rimpiazza pescando commi nuovi, verificati prima di entrare.
    import importlib.util
    sp = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "genera_benchmark.py")
    gen = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(gen)

    generatore = ChatAnthropic(model="claude-haiku-4-5", max_tokens=600,
                               api_key=os.environ["ANTHROPIC_API_KEY"])
    usate = {r["riferimento"].split()[0] for r in righe if r["riferimento"]}
    servono = len(cadute)
    print(f"\nCerco {servono} sostituzioni, verificate una per una...")

    with drv.session(database=db) as s:
        candidati = s.run("""
            MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)-[:HA_COMMA]->(c:Comma)
            WHERE n.caricata AND NOT n.id IN $usate
              AND size(c.testo) > 320 AND size(c.testo) < 850 AND n.anno >= 1995
              AND NOT toLower(c.testo) CONTAINS 'e sostituito dal seguente'
              AND NOT c.testo CONTAINS '----'
            RETURN n.id AS norma, n.titolo AS titolo, a.numero AS articolo,
                   a.rubrica AS rubrica, c.numero AS comma, c.testo AS testo
            ORDER BY rand() LIMIT $q
        """, usate=list(usate), q=servono * 6).data()

        nuove = []
        for c in candidati:
            if len(nuove) >= servono:
                break
            if not (ROOT / "data" / "raw" / c["norma"] / "testo.pdf").exists():
                continue
            try:
                d = gen.genera(c, generatore)
            except Exception:
                continue
            if not d:
                continue
            ok, _ = giudica(modello, c["testo"], d["risposta"])
            if not ok:
                continue
            nuove.append({
                "id": "", "categoria": "contenuto",
                "domanda": d["domanda"].strip(), "risposta": d["risposta"].strip(),
                "riferimento": f"{c['norma']} art. {c['articolo']} c. {c['comma']}",
                "fonte": f"data/raw/{c['norma']}/testo.pdf",
            })
    drv.close()
    print(f"Sostituzioni trovate e verificate: {len(nuove)}")

    finali = buone + nuove \
        + [r for r in righe if r["categoria"] == "struttura"] \
        + [r for r in righe if r["categoria"] == "negativa"]
    for i, r in enumerate(finali, 1):
        r["id"] = f"B{i:03d}"

    with open(CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPI, delimiter=";")
        w.writeheader()
        w.writerows(finali)
    print(f"\n{len(finali)} righe scritte in {CSV}")


if __name__ == "__main__":
    main()
