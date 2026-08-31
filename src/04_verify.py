"""
04 - Esegue le query di 04_verify.cypher e confronta con i valori attesi.

I conteggi attesi vengono dalla lettura diretta del PDF della L.87/2026:
8 titoli, 18 capi, 60 articoli. Se il grafo non li riproduce, il parsing e'
rotto e va corretto prima di fidarsi di qualunque risposta dell'agente.
"""

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
CYPHER = ROOT / "src" / "04_verify.cypher"

ATTESI = {
    1: {"titoli": 8, "capi": 18, "articoli": 60, "commi": 240},
    2: {"articoli_senza_commi": 0},
    3: {"commi_vuoti": 0},
}


def query_dal_file():
    """Estrae le query dal .cypher, con il titolo del blocco di commento."""
    testo = CYPHER.read_text(encoding="utf-8")
    blocchi = []
    for pezzo in testo.split("\n\n\n"):
        titolo = None
        m = re.search(r"^// --- (\d+)\. (.+?) -+\s*$", pezzo, re.M)
        if not m:
            continue
        titolo = f"{m.group(1)}. {m.group(2).strip()}"
        query = "\n".join(r for r in pezzo.split("\n") if not r.strip().startswith("//"))
        query = query.strip().rstrip(";")
        if query:
            blocchi.append((int(m.group(1)), titolo, query))
    return blocchi


def formatta(valore):
    if isinstance(valore, list):
        return ", ".join(str(v) for v in valore) or "-"
    testo = str(valore)
    return testo[:150] + "..." if len(testo) > 150 else testo


def main():
    load_dotenv(ROOT / ".env")
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    fallimenti = []
    with driver.session(database=db) as s:
        for numero, titolo, query in query_dal_file():
            print(f"\n{'=' * 70}\n{titolo}\n{'=' * 70}")
            righe = list(s.run(query))
            if not righe:
                print("  (nessun risultato)")
            for r in righe[:8]:
                d = r.data()
                print("  " + " | ".join(f"{k}={formatta(v)}" for k, v in d.items()))
            if len(righe) > 8:
                print(f"  ... e altre {len(righe) - 8} righe")

            atteso = ATTESI.get(numero)
            if atteso and righe:
                effettivo = righe[0].data()
                for chiave, valore in atteso.items():
                    ottenuto = effettivo.get(chiave)
                    if ottenuto != valore:
                        fallimenti.append(f"{titolo}: {chiave} atteso {valore}, ottenuto {ottenuto}")
                    else:
                        print(f"  OK  {chiave} = {valore}")

    driver.close()

    print(f"\n{'=' * 70}")
    if fallimenti:
        print("VERIFICA FALLITA:")
        for f in fallimenti:
            print("  -", f)
        sys.exit(1)
    print("VERIFICA SUPERATA: tutti i conteggi attesi corrispondono.")


if __name__ == "__main__":
    main()
