"""
07b - Calcola gli embedding delle rubriche degli articoli.

Perche' serve: l'indice vettoriale `commi_vettoriale` sta su `Comma.embedding`.
Gli :Articolo non ne hanno uno, quindi la ricerca semantica non li vede mai, e
cercare per rubrica - "Morte dell'assegnatario", "Incompatibilita' con altre
cariche", cioe' come cerca un giurista - poteva funzionare solo dal ramo
lessicale. Misurato spegnendo quel ramo: rango reciproco medio 0,042 contro
0,500, e su 88 :Articolo disponibili ne usciva zero.

Cosa si vettorializza: **la rubrica preceduta dal titolo della norma**, non la
rubrica nuda. Le rubriche sono spesso una parola sola - "Destinatari",
"Sanzioni", "Definizioni" - e da sole danno un vettore ambiguo; con il titolo
davanti si collocano, che e' anche il modo in cui un giurista le legge.
Il testo dell'articolo NON entra: e' gia' coperto dagli embedding dei suoi
commi, e rifarlo qui duplicherebbe il costo senza aggiungere segnale.

Costo misurato: ~425.000 token per 35.713 rubriche, circa $0,025 con voyage-4.
Occupazione in piu' su Aura: ~140 MB.

    .venv/Scripts/python.exe src/07b_embeddings_rubriche.py

E' idempotente come il 07: calcola solo le rubriche che non hanno il vettore.
Va rieseguito dopo ogni 03_load.py, insieme al 07.
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_voyageai import VoyageAIEmbeddings
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

MODELLO_EMBEDDING = "voyage-4"
INDICE_RUBRICHE = "rubriche_vettoriale"
DIMENSIONI = 1024
LOTTO = 128          # le rubriche sono corte: ~12 token l'una, 1.500 a lotto


def conta(sessione):
    return sessione.run("""
        MATCH (a:Articolo) WHERE a.rubrica IS NOT NULL AND trim(a.rubrica) <> ''
        RETURN count(a) AS totali,
               sum(CASE WHEN a.embedding IS NOT NULL THEN 1 ELSE 0 END) AS fatti
    """).single().data()


def da_fare(sessione, quanti):
    """Le rubriche ancora senza vettore, con il titolo della norma davanti."""
    return sessione.run("""
        MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)
        WHERE a.rubrica IS NOT NULL AND trim(a.rubrica) <> '' AND a.embedding IS NULL
        RETURN elementId(a) AS id,
               coalesce(n.titolo, n.id) + ' - ' + a.rubrica AS testo
        LIMIT $quanti
    """, quanti=quanti).data()


def salva(sessione, coppie):
    sessione.run("""
        UNWIND $coppie AS c
        MATCH (a) WHERE elementId(a) = c.id
        SET a.embedding = c.vettore
    """, coppie=coppie)


def indice(sessione):
    sessione.run(f"""
        CREATE VECTOR INDEX {INDICE_RUBRICHE} IF NOT EXISTS
        FOR (a:Articolo) ON (a.embedding)
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {DIMENSIONI},
            `vector.similarity_function`: 'cosine',
            `vector.quantization.type`: 'SCALAR'
        }}}}
    """)


def main():
    for chiave in ("VOYAGE_API_KEY", "NEO4J_URI"):
        if not os.environ.get(chiave):
            raise SystemExit(f"Manca {chiave} nel file .env")

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    embedding = VoyageAIEmbeddings(
        model=MODELLO_EMBEDDING,
        api_key=os.environ["VOYAGE_API_KEY"],
        batch_size=LOTTO,
    )

    with driver.session(database=db) as s:
        prima = conta(s)
        print(f"Articoli con rubrica: {prima['totali']}, "
              f"gia' vettorializzati: {prima['fatti']}")
        if prima["fatti"] >= prima["totali"]:
            print("Niente da fare. Verifico solo l'indice.")
            indice(s)
            driver.close()
            return

        inizio, fatti = time.time(), 0
        while True:
            lotto = da_fare(s, LOTTO)
            if not lotto:
                break
            try:
                vettori = embedding.embed_documents([r["testo"] for r in lotto])
            except Exception as e:
                if "rate" in str(e).lower():
                    print(f"\nVoyage ha applicato un limite di velocita' dopo "
                          f"{fatti} rubriche. Attendi qualche minuto e rilancia: "
                          f"riprende da dove si e' fermato.")
                    break
                raise
            salva(s, [{"id": r["id"], "vettore": v} for r, v in zip(lotto, vettori)])
            fatti += len(lotto)
            if fatti % (LOTTO * 20) == 0:
                velocita = fatti / max(1, time.time() - inizio)
                restano = (prima["totali"] - prima["fatti"] - fatti) / max(velocita, 0.1)
                print(f"  {fatti}/{prima['totali'] - prima['fatti']}  "
                      f"({velocita:.0f}/s, restano ~{restano/60:.0f} min)")

        print("Creo l'indice vettoriale sulle rubriche...")
        indice(s)
        dopo = conta(s)

    driver.close()
    print(f"\nFatto in {time.time() - inizio:.0f}s: {fatti} nuove rubriche, "
          f"{dopo['fatti']}/{dopo['totali']} indicizzate.")
    print(f"Indice vettoriale: '{INDICE_RUBRICHE}' su (:Articolo).embedding")


if __name__ == "__main__":
    main()
