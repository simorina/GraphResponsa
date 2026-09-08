"""
Ricalcola Articolo.testo dove e' vuoto ma i commi hanno testo.

`Articolo.testo` non e' un dato originale: e' l'aggregato dei commi, che
03_load.py costruisce al caricamento con

    "testo": " ".join(c["testo"] for c in a.get("commi") or [])

Chi ripara i commi DOPO il caricamento - come ha fatto
`ripara_articoli_vuoti.py` - lascia pero' l'aggregato indietro, e nessuno se ne
accorge: l'articolo continua a essere trovato dai suoi commi.

Se ne accorge invece il ramo semantico delle rubriche, che filtra con
`art.testo IS NOT NULL`. Quel filtro serve a escludere le 28 intestazioni senza
corpo - righe come "Art. 50 (Alterazione di marche)" negli Allegati dei decreti
sulle violazioni - ma con l'aggregato indietro ne escludeva 1.038, di cui 715
con una rubrica utile: articoli vivi, cercabili dai commi, che non potevano
emergere dall'indice costruito apposta per trovarli per argomento.

Qui si ricalcola l'aggregato con la stessa formula del loader, cosi' il grafo
torna a corrispondere a cio' che un caricamento pulito produrrebbe. Restano
vuoti i soli articoli che non hanno davvero nulla da aggregare.

    .venv/Scripts/python.exe scripts/ripara_testo_articoli.py           # misura
    .venv/Scripts/python.exe scripts/ripara_testo_articoli.py --scrivi  # applica
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def main():
    from agente.strumenti import grafo

    scrivi = "--scrivi" in sys.argv
    g = grafo()

    stato = g.query("""
        MATCH (a:Articolo)
        OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
        WHERE c.testo IS NOT NULL AND trim(c.testo) <> ''
        WITH a, count(c) AS commiPieni
        RETURN count(a) AS totali,
               sum(CASE WHEN (a.testo IS NULL OR trim(a.testo) = '')
                        AND commiPieni > 0 THEN 1 ELSE 0 END) AS daRiparare,
               sum(CASE WHEN (a.testo IS NULL OR trim(a.testo) = '')
                        AND commiPieni = 0 THEN 1 ELSE 0 END) AS senzaNulla
    """)[0]
    print(f"  articoli in archivio                       {stato['totali']:>8,}")
    print(f"    testo vuoto ma commi pieni: DA RIPARARE  {stato['daRiparare']:>8,}")
    print(f"    testo vuoto e nessun comma: corretti cosi'{stato['senzaNulla']:>7,}")

    if not scrivi:
        print("\n  campione:")
        for r in g.query("""
            MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)-[:HA_COMMA]->(c:Comma)
            WHERE (a.testo IS NULL OR trim(a.testo) = '')
              AND c.testo IS NOT NULL AND trim(c.testo) <> ''
            WITH n, a, collect(c.testo) AS testi LIMIT 6
            RETURN n.id AS norma, a.numero AS art, a.rubrica AS rubrica,
                   size(testi) AS commi, left(testi[0], 70) AS primo
        """):
            print(f"    {r['norma']:<14} art.{str(r['art']):<6} {str(r['rubrica'])[:34]:<36}"
                  f" {r['commi']} commi")
            print(f"       {' '.join((r['primo'] or '').split())}")
        print("\n  Nulla scritto. Aggiungi --scrivi per applicare al grafo.")
        return

    # Stessa formula del loader: i commi nell'ordine in cui stanno, uniti da uno
    # spazio. Si ordina per `ordine` e, dove e' nullo, per id: senza un ordine
    # esplicito l'aggregato cambierebbe a ogni esecuzione.
    g.query("""
        MATCH (a:Articolo) WHERE a.testo IS NULL OR trim(a.testo) = ''
        MATCH (a)-[:HA_COMMA]->(c:Comma)
        WHERE c.testo IS NOT NULL AND trim(c.testo) <> ''
        WITH a, c ORDER BY coalesce(c.ordine, 999999), c.id
        WITH a, collect(c.testo) AS testi
        SET a.testo = trim(reduce(t = '', x IN testi | t + ' ' + x))
    """)

    dopo = g.query("""
        MATCH (a:Articolo)
        OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
        WHERE c.testo IS NOT NULL AND trim(c.testo) <> ''
        WITH a, count(c) AS commiPieni
        RETURN sum(CASE WHEN (a.testo IS NULL OR trim(a.testo) = '')
                        AND commiPieni > 0 THEN 1 ELSE 0 END) AS restano,
               sum(CASE WHEN a.testo IS NULL OR trim(a.testo) = ''
                        THEN 1 ELSE 0 END) AS vuotiInTutto
    """)[0]
    print(f"\n  riparati. Restano da riparare: {dopo['restano']}")
    print(f"  articoli ancora senza testo:   {dopo['vuotiInTutto']}"
          f"   (le intestazioni senza corpo)")


if __name__ == "__main__":
    main()
