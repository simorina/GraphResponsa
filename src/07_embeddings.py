"""
07 - Calcola gli embedding dei commi e crea l'indice vettoriale.

Perche' serve: l'indice full-text pesa le parole, non il significato. Sul
corpus attuale "quanto devo aspettare per una risposta dal comune" restituisce
"Abrogazioni" del Codice Ambientale, e la L.160/2011 sul procedimento
amministrativo - che e' in archivio con 48 articoli - non compare.

from_existing_graph aggiunge gli embedding come proprieta' dei nodi :Comma che
gia' esistono: non crea un archivio parallelo, non duplica i testi. Il grafo
resta uno solo, con una proprieta' in piu'.

Modello: voyage-4, multilingue. Attenzione a voyage-law-2: il nome promette il
dominio giuridico, ma non e' multilingue - su testi italiani rende meno di un
modello generale multilingue.

    .venv/Scripts/python.exe src/07_embeddings.py

E' idempotente: calcola gli embedding solo per i commi che non ce l'hanno.
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_neo4j import Neo4jVector
from langchain_voyageai import VoyageAIEmbeddings
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODELLO_EMBEDDING = "voyage-4"
INDICE_VETTORIALE = "commi_vettoriale"
INDICE_KEYWORD = "testo_normativo"   # il full-text gia' esistente
LOTTO = 16                           # commi per richiesta: tiene sotto i limiti
                                     # di un account senza metodo di pagamento


def conta(driver, db):
    with driver.session(database=db) as s:
        return s.run("""
            MATCH (c:Comma)
            RETURN count(c) AS totali,
                   sum(CASE WHEN c.embedding IS NOT NULL THEN 1 ELSE 0 END) AS con_embedding
        """).single().data()


def main():
    for chiave in ("VOYAGE_API_KEY", "NEO4J_URI"):
        if not os.environ.get(chiave):
            raise SystemExit(f"Manca {chiave} nel file .env")

    uri = os.environ["NEO4J_URI"]
    utente = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(utente, password))
    prima = conta(driver, db)
    print(f"Commi nel grafo: {prima['totali']}, gia' con embedding: {prima['con_embedding']}")
    if prima["con_embedding"] >= prima["totali"]:
        print("Tutti i commi hanno gia' un embedding. Niente da fare.")
        driver.close()
        return

    print(f"Calcolo gli embedding mancanti con {MODELLO_EMBEDDING}...")
    inizio = time.time()

    # Un account Voyage senza metodo di pagamento e' limitato a 10.000 token al
    # minuto: un lotto grande lo sfonda al primo colpo. Con lotti piccoli la
    # corsa e' piu' lenta ma non si interrompe.
    embedding = VoyageAIEmbeddings(
        model=MODELLO_EMBEDDING,
        api_key=os.environ["VOYAGE_API_KEY"],
        batch_size=LOTTO,
    )

    # from_existing_graph legge i nodi :Comma, calcola l'embedding del campo
    # `testo` e lo salva su ogni nodo. Crea anche l'indice vettoriale.
    try:
        Neo4jVector.from_existing_graph(
            embedding=embedding,
            url=uri, username=utente, password=password, database=db,
            node_label="Comma",
            text_node_properties=["testo"],
            embedding_node_property="embedding",
            index_name=INDICE_VETTORIALE,
            keyword_index_name=INDICE_KEYWORD,
            search_type="hybrid",
        )
    except Exception as e:
        if "rate limit" in str(e).lower() or "RateLimit" in type(e).__name__:
            fatti = conta(driver, db)["con_embedding"]
            driver.close()
            raise SystemExit(
                f"\nVoyage ha applicato un limite di velocita'. "
                f"Indicizzati finora: {fatti}/{prima['totali']}.\n"
                f"Registra un metodo di pagamento su dashboard.voyageai.com "
                f"(i token restano gratuiti, salgono solo i limiti), attendi "
                f"qualche minuto e rilancia: riprende da dove si e' fermato."
            ) from e
        raise

    dopo = conta(driver, db)
    driver.close()
    nuovi = dopo["con_embedding"] - prima["con_embedding"]
    print(f"Fatto in {time.time() - inizio:.0f}s: {nuovi} nuovi embedding, "
          f"{dopo['con_embedding']}/{dopo['totali']} commi indicizzati.")
    print(f"Indice vettoriale: '{INDICE_VETTORIALE}' (ibrido con '{INDICE_KEYWORD}')")


if __name__ == "__main__":
    main()
