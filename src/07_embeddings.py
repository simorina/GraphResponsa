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
# Quanti giri prima di arrendersi su un errore di rete. Ogni giro riparte dai
# commi ancora senza vettore, quindi ritentare non costa lavoro rifatto.
TENTATIVI = 6


CONTEGGIO = """
    MATCH (c:Comma)
    RETURN count(c) AS totali,
           sum(CASE WHEN c.embedding IS NOT NULL THEN 1 ELSE 0 END) AS con_embedding
"""


def conta(uri, auth, db):
    """Apre e chiude la propria connessione, per non dipendere da un driver guasto.

    Contava attraverso un driver condiviso, e quando la corsa moriva per una
    connessione caduta il gestore dell'errore chiamava proprio questa funzione
    per dire a che punto era arrivata: la chiamata rilanciava sul driver
    ormai defunto, e il ritentativo non partiva nemmeno. Un guasto della rete
    finiva cosi' per uccidere il meccanismo che doveva ripararlo.
    """
    with GraphDatabase.driver(uri, auth=auth) as d:
        with d.session(database=db) as s:
            return s.run(CONTEGGIO).single().data()


def conta_o_niente(uri, auth, db):
    """Il conteggio per i messaggi, che non deve mai far fallire chi lo chiama."""
    try:
        return conta(uri, auth, db)["con_embedding"]
    except Exception:
        return None


def main():
    for chiave in ("VOYAGE_API_KEY", "NEO4J_URI"):
        if not os.environ.get(chiave):
            raise SystemExit(f"Manca {chiave} nel file .env")

    uri = os.environ["NEO4J_URI"]
    utente = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    auth = (utente, password)
    prima = conta(uri, auth, db)
    print(f"Commi nel grafo: {prima['totali']}, gia' con embedding: {prima['con_embedding']}")
    if prima["con_embedding"] >= prima["totali"]:
        print("Tutti i commi hanno gia' un embedding. Niente da fare.")
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
    #
    # Sulla corsa intera - 171.165 commi, oltre due ore - una connessione che
    # cade e' quasi certa, e succedeva da entrambi i lati: "RemoteDisconnected"
    # da Voyage al 51%, "SessionExpired" da Neo4j al 74%. Il lavoro fatto non
    # si perde mai (i vettori sono gia' sui nodi e ogni giro riparte da quelli
    # che ne sono privi), ma bisognava accorgersene e rilanciare a mano. Ora ci
    # riprova da se', e ritentare non ricalcola nulla.
    for tentativo in range(1, TENTATIVI + 1):
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
            break
        except Exception as e:
            if "rate limit" in str(e).lower() or "RateLimit" in type(e).__name__:
                raise SystemExit(
                    f"\nVoyage ha applicato un limite di velocita'. "
                    f"Indicizzati finora: {conta_o_niente(uri, auth, db)}"
                    f"/{prima['totali']}.\n"
                    f"Registra un metodo di pagamento su dashboard.voyageai.com "
                    f"(i token restano gratuiti, salgono solo i limiti), attendi "
                    f"qualche minuto e rilancia: riprende da dove si e' fermato."
                ) from e
            fatti = conta_o_niente(uri, auth, db)
            if tentativo == TENTATIVI:
                raise SystemExit(
                    f"\nInterrotto dopo {TENTATIVI} tentativi: "
                    f"{type(e).__name__}: {e}\n"
                    f"Indicizzati finora: {fatti}/{prima['totali']}. "
                    f"Rilanciare riprende da qui."
                ) from e
            attesa = 15 * tentativo
            print(f"  {type(e).__name__} a {fatti}/{prima['totali']}: "
                  f"riprovo fra {attesa}s (tentativo {tentativo}/{TENTATIVI})",
                  flush=True)
            time.sleep(attesa)

    dopo = conta(uri, auth, db)
    nuovi = dopo["con_embedding"] - prima["con_embedding"]
    print(f"Fatto in {time.time() - inizio:.0f}s: {nuovi} nuovi embedding, "
          f"{dopo['con_embedding']}/{dopo['totali']} commi indicizzati.")
    print(f"Indice vettoriale: '{INDICE_VETTORIALE}' (ibrido con '{INDICE_KEYWORD}')")


if __name__ == "__main__":
    main()
