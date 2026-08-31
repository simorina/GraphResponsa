import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv('.env')

driver = GraphDatabase.driver(
    os.environ['NEO4J_URI'],
    auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD'])
)

with driver.session() as s:
    tot_nodi = s.run('MATCH (n) RETURN count(n) AS c').single()['c']
    tot_rel = s.run('MATCH ()-[r]->() RETURN count(r) AS c').single()['c']

    labels_res = s.run("""
        MATCH (n)
        UNWIND labels(n) AS l
        RETURN l AS label, count(n) AS count
        ORDER BY count DESC
    """).data()

    rel_res = s.run("""
        MATCH ()-[r]->()
        RETURN type(r) AS tipo, count(r) AS count
        ORDER BY count DESC
    """).data()

    norme_res = s.run("""
        MATCH (n:Norma)
        RETURN n.caricata AS caricata, count(n) AS count
    """).data()

    pref_res = s.run("""
        MATCH (n:Norma)
        WHERE n.caricata = true
        WITH split(n.id, '-')[0] AS pref, count(n) AS quanti, min(n.anno) AS anno_min, max(n.anno) AS anno_max
        RETURN pref, quanti, anno_min, anno_max
        ORDER BY quanti DESC
    """).data()

    print("=== TOTALE GRAFO ===")
    print(f"Nodi totali: {tot_nodi}")
    print(f"Relazioni totali: {tot_rel}")

    print("\n=== ETICHETTE (NODI) ===")
    for row in labels_res:
        print(f"  :{row['label']:25s} -> {row['count']:,}")

    print("\n=== RELAZIONI (ARCHI) ===")
    for row in rel_res:
        print(f"  [:{row['tipo']:20s}] -> {row['count']:,}")

    print("\n=== NORME PER STATO ===")
    for row in norme_res:
        stato = "Caricate con Testo" if row['caricata'] else "Stub (solo citate)"
        print(f"  {stato:25s} -> {row['count']:,}")

    print("\n=== NORME INTEGRATE PER PREFISSO ===")
    for row in pref_res:
        print(f"  Prefisso {row['pref']:5s} -> {row['quanti']:,} atti (Anni {row['anno_min']} - {row['anno_max']})")

driver.close()
