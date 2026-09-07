"""
Ricostruisce data/parsed/S-*.json a partire dal grafo.

Perche' serve: gli Statuti non passano da 02_parse.py, che non ne riconosce la
struttura (RUBRICA I., RUBRICA II. al posto di Art. 1, Art. 2) e ripiega su
struttura_dedotta, producendo un unico articolo "unico". Li integra lo script
dedicato integra_tutti_i_12_statuti.py, che scrive sia sul grafo sia su
data/parsed/.

Un `02_parse.py --force` calpestava quei file: lo Statuto del 1600 Libro Primo
passava da 124 articoli e 4.630 commi a 1 articolo e 153 commi. Il grafo non ne
soffriva - 03_load fonde, non cancella - ma il caricamento successivo avrebbe
aggiunto a ogni statuto un articolo spurio "unico" con i commi duplicati.

Il grafo conserva la versione buona, quindi la si riporta su disco da li':
esatto e senza riscaricare nulla dal portale. Da eseguire dopo un --force, o
ogni volta che i file degli statuti risultassero da rifare.

    .venv/Scripts/python.exe scripts/ricostruisci_statuti_parsed.py

Da oggi 02_parse.py salta gli Statuti, quindi non dovrebbe piu' servire.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
PARSED = ROOT / "data" / "parsed"
RAW = ROOT / "data" / "raw"
load_dotenv(ROOT / ".env")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def statuti(sessione):
    return [r["id"] for r in sessione.run(
        "MATCH (n:Norma) WHERE n.id STARTS WITH 'S-' AND n.caricata "
        "RETURN n.id AS id ORDER BY n.id")]


def contenuto(sessione, norma_id):
    """Articoli e commi come li ha il grafo, nella forma che 03_load si aspetta."""
    righe = sessione.run("""
        MATCH (n:Norma {id: $id})-[:HA_ARTICOLO]->(a:Articolo)
        OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
        WITH a, c ORDER BY a.ordine, c.ordine, c.id
        WITH a, collect(CASE WHEN c IS NULL THEN null ELSE {
                 id: c.id, numero: c.numero, testo: c.testo,
                 numerazioneAnomala: coalesce(c.numerazioneAnomala, false),
                 commaImplicito: coalesce(c.commaImplicito, false)} END) AS commi
        RETURN a.id AS id, a.numero AS numero, a.rubrica AS rubrica,
               a.ordine AS ordine, [x IN commi WHERE x IS NOT NULL] AS commi
        ORDER BY a.ordine
    """, id=norma_id).data()
    for i, a in enumerate(righe):
        a["partizioneId"] = None
        a["ordine"] = a["ordine"] if a["ordine"] is not None else i
        # Le citazioni si ricavano dal grafo solo con fatica e non servono al
        # ricarico: gli archi ci sono gia'. Si lascia la lista vuota invece di
        # inventarne una parziale.
        a["citazioni"] = []
    return righe


def main():
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    with driver.session(database=db) as s:
        ids = statuti(s)
        print(f"Statuti nel grafo: {len(ids)}")
        for nid in ids:
            testa = s.run("""
                MATCH (n:Norma {id: $id})
                RETURN n.id AS id, n.tipo AS tipo, n.numero AS numero,
                       n.anno AS anno, toString(n.data) AS data,
                       toString(n.dataPubblicazione) AS dataPubblicazione,
                       toString(n.dataEntrataVigore) AS dataEntrataVigore,
                       n.titolo AS titolo, n.iterFormazione AS iterFormazione,
                       n.urlIter AS urlIter, n.urlScheda AS urlScheda,
                       n.urlDocumento AS urlDocumento,
                       n.nomeFileOriginale AS nomeFileOriginale
            """, id=nid).single().data()

            articoli = contenuto(s, nid)
            commi = sum(len(a["commi"]) for a in articoli)

            dati = {**testa, "allegati": [], "preambolo": "",
                    "citazioniPreambolo": [], "partizioni": [],
                    "articoli": articoli}

            destinazione = PARSED / f"{nid}.json"
            prima = 0
            if destinazione.exists():
                try:
                    vecchio = json.loads(destinazione.read_text(encoding="utf-8"))
                    prima = sum(len(a.get("commi") or []) for a in vecchio.get("articoli", []))
                except Exception:
                    pass
            destinazione.write_text(
                json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  {nid:<14} {len(articoli):>4} articoli, {commi:>5} commi "
                  f"(sul disco c'erano {prima})")

    driver.close()
    print("\nFatto. I file degli Statuti rispecchiano di nuovo il grafo.")


if __name__ == "__main__":
    main()
