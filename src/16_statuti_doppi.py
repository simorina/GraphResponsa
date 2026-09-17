"""
16 - Toglie la seconda copia degli Statuti, caricati due volte.

Gli Statuti non vengono da 02_parse.py: sono stati integrati a parte, e dieci
di loro portano ogni rubrica due volte, con due forme di id -
`S-1-1600_artI` e `S-1-1600_I` - lo stesso numero, la stessa rubrica, lo stesso
numero di commi. Il testo e' quasi lo stesso, ma non uguale: una delle due
estrazioni salta righe ("...parlare inaffari piu' gravi" contro "...parlare in
primo luogo dello Arringo").

Misurato sul PDF, con le coppie di parole consecutive che ciascuna copia ha in
comune col testo del documento: la copia `_art` ne ritrova il 98-100%, l'altra
il 97-98%. Nessuna delle due ha archi. Si tiene la `_art`.

Due copie della stessa rubrica non fanno solo rumore: la ricerca restituisce
due volte lo stesso passo, e l'agente non sa quale dei due citare. S-8-1859 e
S-11-1900 hanno una copia sola, e restano come sono.

Uso:
    .venv/Scripts/python.exe src/16_statuti_doppi.py            # solo misura
    .venv/Scripts/python.exe src/16_statuti_doppi.py --scrivi --backup <file.json>
"""

import json
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from agente.strumenti import grafo  # noqa: E402

PARSED = RADICE / "data" / "parsed"

# Gli articoli della copia da togliere: hanno una gemella `_art` con lo stesso
# numero nello stesso statuto.
Q_DOPPI = """
MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)
WHERE n.id STARTS WITH 'S-' AND NOT a.id STARTS WITH n.id + '_art'
MATCH (n)-[:HA_ARTICOLO]->(b:Articolo)
WHERE b.id = n.id + '_art' + substring(a.id, size(n.id) + 1) AND b.numero = a.numero
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
OPTIONAL MATCH (c)-[r]-() WHERE type(r) <> 'HA_COMMA'
RETURN n.id AS norma, a.id AS id, b.id AS gemella, count(DISTINCT c) AS commi, count(r) AS archi
"""

Q_BACKUP = """
UNWIND $ids AS aid
MATCH (a:Articolo {id: aid})
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
RETURN properties(a) AS articolo, collect(properties(c)) AS commi
"""

Q_CANCELLA = """
UNWIND $ids AS aid
MATCH (a:Articolo {id: aid})
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
DETACH DELETE c, a
"""


def main():
    scrivi = "--scrivi" in sys.argv
    g = grafo()
    doppi = g.query(Q_DOPPI)
    per_norma = {}
    for r in doppi:
        per_norma.setdefault(r["norma"], []).append(r)
    for norma, righe in sorted(per_norma.items()):
        print(f"    {norma:<12} articoli doppi {len(righe):>4} | commi {sum(r['commi'] for r in righe):>6}"
              f" | archi {sum(r['archi'] for r in righe)}")
    con_archi = [r["id"] for r in doppi if r["archi"]]
    if con_archi:
        sys.exit(f"  copie con archi, da guardare a mano: {con_archi[:10]}")
    if not scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi --backup <file.json> per applicare.")
        return
    if "--backup" not in sys.argv:
        sys.exit("  --scrivi vuole --backup <file.json>.")
    file = Path(sys.argv[sys.argv.index("--backup") + 1])
    ids = [r["id"] for r in doppi]
    copia = [dict(r) for r in g.query(Q_BACKUP, {"ids": ids})]
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(copia, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"    backup: {file} ({file.stat().st_size / 1e6:.0f} MB)")
    g.query(Q_CANCELLA, {"ids": ids})
    togli = set(ids)
    for norma in per_norma:
        f = PARSED / f"{norma}.json"
        dati = json.loads(f.read_text(encoding="utf-8"))
        prima = len(dati["articoli"])
        dati["articoli"] = [a for a in dati["articoli"] if a["id"] not in togli]
        f.write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    {norma}: articoli nel JSON {prima} -> {len(dati['articoli'])}")
    print(f"\n  tolti {len(ids)} articoli doppi. Ora: 07b non serve, i vettori restano sulla copia tenuta.")


if __name__ == "__main__":
    main()
