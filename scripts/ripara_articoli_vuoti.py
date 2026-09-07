"""
Ridà il testo agli articoli che nel grafo non hanno nemmeno un comma.

340 articoli su 74.742, in 231 norme, esistevano come intestazione vuota: per
l'agente erano articoli che non dispongono nulla. Le cause erano due difetti di
02_parse.py, corretti nel commit "Il parser perdeva il testo di 340 articoli":

  - la rubrica si mangiava il testo degli articoli di una frase sola
  - il buffer della rubrica non si chiudeva su "(...)." e inghiottiva i commi

Perche' una riparazione mirata invece di un 03_load.py completo: il parser
attuale, su alcuni atti, produce articoli spuri. DD-149-2016 "Violazioni
amministrative" ne rende 524 contro i 110 del grafo, perche' i suoi Allegati
elencano le infrazioni citando gli articoli di ALTRE leggi e il riconoscitore
li scambia per propri - lo si vede dai numeri ripetuti, "art. 3" ventotto
volte. Un caricamento completo avrebbe aggiunto ~6.000 articoli inventati: un
danno molto piu' grande dei 340 vuoti da riparare. Quel difetto resta aperto e
va affrontato a parte.

Qui si tocca solo cio' che si e' rotto: si aggiunge un comma agli articoli che
nel grafo ne hanno zero e che il parser corretto ora riempie. Nessuna
cancellazione, nessun articolo nuovo.

    .venv/Scripts/python.exe scripts/ripara_articoli_vuoti.py            # riferisce
    .venv/Scripts/python.exe scripts/ripara_articoli_vuoti.py --scrivi   # scrive
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
PARSED = ROOT / "data" / "parsed"
load_dotenv(ROOT / ".env")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def vuoti(sessione):
    return sessione.run("""
        MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)
        WHERE NOT (a)-[:HA_COMMA]->()
        RETURN n.id AS norma, a.id AS articoloId, a.numero AS numero,
               a.rubrica AS rubrica
        ORDER BY n.id, a.ordine
    """).data()


def rimedi(elenco):
    """Per ogni articolo vuoto, il comma che il parser corretto ora produce."""
    per_norma = {}
    for v in elenco:
        per_norma.setdefault(v["norma"], []).append(v)

    trovati, senza = [], []
    for norma, articoli in per_norma.items():
        f = PARSED / f"{norma}.json"
        if not f.exists():
            senza += articoli
            continue
        try:
            dati = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            senza += articoli
            continue
        per_numero = {str(a["numero"]): a for a in dati.get("articoli", [])}
        for v in articoli:
            a = per_numero.get(str(v["numero"]))
            if not a or not a.get("commi"):
                senza.append(v)
                continue
            trovati.append({
                "articoloId": v["articoloId"],
                "rubrica": a.get("rubrica"),
                "commi": [{"id": c["id"], "numero": c["numero"], "testo": c["testo"],
                           "numerazioneAnomala": bool(c.get("numerazioneAnomala")),
                           "commaImplicito": bool(c.get("commaImplicito"))}
                          for c in a["commi"]],
            })
    return trovati, senza


def scrivi(sessione, rimedi_):
    return sessione.run("""
        UNWIND $rimedi AS r
        MATCH (a:Articolo {id: r.articoloId})
        SET a.rubrica = r.rubrica
        WITH a, r
        UNWIND r.commi AS c
        MERGE (cm:Comma {id: c.id})
        SET cm.numero = c.numero, cm.testo = c.testo,
            cm.numerazioneAnomala = c.numerazioneAnomala,
            cm.commaImplicito = c.commaImplicito
        MERGE (a)-[:HA_COMMA]->(cm)
        RETURN count(DISTINCT cm) AS commi
    """, rimedi=rimedi_).single()["commi"]


def main():
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    with driver.session(database=db) as s:
        elenco = vuoti(s)
        print(f"Articoli senza commi nel grafo: {len(elenco)}")
        da_riparare, senza = rimedi(elenco)
        commi = sum(len(r["commi"]) for r in da_riparare)
        print(f"  riparabili: {len(da_riparare)} articoli, {commi} commi da aggiungere")
        print(f"  non riparabili: {len(senza)} (il parser non produce testo nemmeno ora)")
        for v in senza[:5]:
            print(f"      {v['norma']} art.{v['numero']}")

        if "--scrivi" not in sys.argv:
            print("\nSolo lettura. Per applicare: --scrivi")
            driver.close()
            return

        scritti = scrivi(s, da_riparare)
        restano = len(vuoti(s))
        print(f"\nScritti {scritti} commi. Articoli ancora senza commi: {restano}")

    driver.close()


if __name__ == "__main__":
    main()
