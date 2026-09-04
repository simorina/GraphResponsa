import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()
driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])
)

with driver.session() as s:
    rows = s.run("""
        MATCH (s:Statuto)
        OPTIONAL MATCH (s)-[:HA_ARTICOLO]->(a:Articolo)
        OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
        RETURN s.id AS id, s.titolo AS titolo, s.numero AS num,
               count(DISTINCT a) AS articoli, count(c) AS commi
        ORDER BY num
    """).data()
    
    print("=" * 80)
    print("=== LIVE CYPHER QUERY: TUTTI I 12 STATUTI IN NEO4J AURA ===")
    print("=" * 80)
    for r in rows:
        print(f"ID: {r['id']:<10} | Articoli: {r['articoli']:2d} | Commi: {r['commi']:4d} | Titolo: {r['titolo']}")
        
    tot_s = s.run("MATCH (s:Statuto) RETURN count(s) AS c").single()["c"]
    tot_a = s.run("MATCH (:Statuto)-[:HA_ARTICOLO]->(a:Articolo) RETURN count(a) AS c").single()["c"]
    tot_c = s.run("MATCH (:Statuto)-[:HA_ARTICOLO]->(:Articolo)-[:HA_COMMA]->(c:Comma) RETURN count(c) AS c").single()["c"]
    
    print("-" * 80)
    print(f"TOTALE NODI STATUTO: {tot_s}/12")
    print(f"TOTALE ARTICOLI:     {tot_a:,d}")
    print(f"TOTALE COMMI/TESTO:  {tot_c:,d}")
    print("=" * 80)

driver.close()
