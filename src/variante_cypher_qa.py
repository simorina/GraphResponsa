"""
Variante sperimentale basata su GraphCypherQAChain (langchain-neo4j).

Traduce la domanda in linguaggio naturale direttamente in una query Cypher,
la esegue sul Grafo Neo4j e sintetizza la risposta con il modello QA.

Uso:
    python src/variante_cypher_qa.py "Quanti articoli ha la Legge 7/1961?"
    python src/variante_cypher_qa.py "Quali norme citano il Decreto Delegato 173 del 2024?"
    python src/variante_cypher_qa.py   (modalità interattiva)
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import PromptTemplate
from langchain_neo4j import GraphCypherQAChain, Neo4jGraph

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Schema descrittivo e regole per la generazione di query Cypher legali corrette
SCHEMA_CYPHER_PROMPT = """Sei un esperto sviluppatore Neo4j specializzato nel diritto della Repubblica di San Marino.
Genera una query Cypher precisa ed efficiente per rispondere alla domanda dell'utente.

## Schema del Database Neo4j:
- (:Norma {{id: string, numero: integer, anno: integer, tipo: string, titolo: string, caricata: boolean, dataEntrataVigore: date}})
- (:Articolo {{id: string, numero: string, rubrica: string, ordine: integer}})
- (:Comma {{id: string, numero: string, testo: string}})
- (:Partizione {{id: string, tipo: string, numero: string, rubrica: string}})

## Relazioni:
- (:Norma)-[:HA_ARTICOLO]->(:Articolo)
- (:Articolo)-[:HA_COMMA]->(:Comma)
- (:Norma)-[:HA_PARTIZIONE]->(:Partizione)
- (:Norma|:Comma)-[:CITA]->(:Norma)
- (:Comma)-[:CITA_ARTICOLO]->(:Articolo)

## Regole di Scrittura Cypher:
1. Restituisci SOLO la query Cypher all'interno di ```cypher ... ``` o come testo puro, senza commenti né spiegazioni.
2. Usa sempre confronti case-insensitive: toLower(n.titolo) CONTAINS toLower('...') oppure indici fulltext quando opportuno.
3. Per contare articoli o commi di una norma:
   MATCH (n:Norma {{numero: 7, anno: 1961}})-[:HA_ARTICOLO]->(a:Articolo) RETURN count(a) AS totale_articoli
4. Non usare mai comandi di modifica dati (DELETE, SET, MERGE, CREATE). Solo lettura (MATCH, RETURN).
5. Limita sempre i risultati con LIMIT 20 se la query estrae testi lunghi o commi.

Schema:
{schema}

Domanda dell'utente: {question}
Query Cypher:"""

CYPHER_PROMPT = PromptTemplate(
    input_variables=["schema", "question"],
    template=SCHEMA_CYPHER_PROMPT
)


def crea_chain(verbose=True):
    """Inizializza la GraphCypherQAChain collegata al Neo4j di San Marino."""
    graph = Neo4jGraph(
        url=os.environ["NEO4J_URI"],
        username=os.environ["NEO4J_USERNAME"],
        password=os.environ["NEO4J_PASSWORD"],
        database=os.environ.get("NEO4J_DATABASE", "neo4j"),
        refresh_schema=True,
    )

    llm = ChatAnthropic(
        model="claude-haiku-4-5",
        temperature=0.0,
        max_tokens=2048,
    )

    chain = GraphCypherQAChain.from_llm(
        graph=graph,
        cypher_llm=llm,
        qa_llm=llm,
        cypher_prompt=CYPHER_PROMPT,
        verbose=verbose,
        return_intermediate_steps=True,
        return_direct=False,
        allow_dangerous_requests=True,
    )
    return chain


def chiedi_cypher(domanda: str, verbose: bool = True) -> dict:
    """Esegue un quesito tramite GraphCypherQAChain restituendo Cypher generato, risultato grezzo e risposta."""
    chain = crea_chain(verbose=verbose)
    risposta = chain.invoke({"query": domanda})

    cypher_generato = None
    contesto_grafo = None

    if "intermediate_steps" in risposta:
        steps = risposta["intermediate_steps"]
        for step in steps:
            if isinstance(step, dict) and "query" in step:
                cypher_generato = step["query"]
            elif isinstance(step, dict) and "context" in step:
                contesto_grafo = step["context"]

    return {
        "domanda": domanda,
        "cypher_generato": cypher_generato,
        "risultato_grafo": contesto_grafo,
        "risposta": risposta.get("result", ""),
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        domanda_cli = " ".join(sys.argv[1:])
        print(f"\n[GraphCypherQAChain] Domanda: {domanda_cli}\n" + "=" * 60)
        res = chiedi_cypher(domanda_cli, verbose=True)
        print("\n" + "=" * 60)
        print(f"QUERY CYPHER GENERATA:\n{res['cypher_generato']}\n")
        print(f"RISULTATO DAL GRAFO:\n{res['risultato_grafo']}\n")
        print(f"RISPOSTA FINALE:\n{res['risposta']}\n" + "=" * 60)
    else:
        print("=== MODALITÀ INTERATTIVA GRAPHCYPHERQACHAIN ===")
        print("Scrivi una domanda giuridica (o 'exit' per uscire):\n")
        chain = crea_chain(verbose=True)
        while True:
            try:
                d = input("Domanda > ").strip()
                if not d or d.lower() in ("exit", "quit", "esci"):
                    break
                print("\n--- Elaborazione in corso ---")
                res = chain.invoke({"query": d})
                print(f"\nRISPOSTA:\n{res.get('result')}\n")
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Errore: {e}\n")
