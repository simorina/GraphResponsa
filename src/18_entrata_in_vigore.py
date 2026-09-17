"""
18 - La data di entrata in vigore, quando l'atto la scrive per esteso.

Il portale pubblica `dataEntrataVigore` per un terzo degli atti: al 17/09 ne
mancavano 7.519 su 11.054. Quasi sempre non si puo' ricavare: la formula
tipica - "entra in vigore il quinto giorno successivo a quello della sua
legale pubblicazione" - si conta dalla data di pubblicazione, che per quegli
atti manca anch'essa (13 su 7.519 l'hanno).

Qui si prende solo il caso certo: "Il presente decreto entra in vigore il 1°
gennaio 1988", "... entra in vigore a datare dal 10 febbraio 1977". Una data
lontana piu' di un anno da quella dell'atto si scarta: e' piu' probabile che
riguardi altro. La proprieta' `fonteEntrataVigore = 'testo'` dice da dove viene
il dato, e non si tocca mai una data gia' pubblicata dal portale.

Uso:
    .venv/Scripts/python.exe src/18_entrata_in_vigore.py            # solo misura
    .venv/Scripts/python.exe src/18_entrata_in_vigore.py --scrivi
"""

import datetime
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]
RE_VIGORE = re.compile(
    r"(?:il|la)\s+present[ei]\s+(?:legge|decreto|regolamento|ordinanza|norma)[^.;]{0,80}?"
    r"entra(?:no)?\s+in\s+vigore\s+(?:il|dal|a\s+(?:datare|decorrere)\s+dal?)\s+"
    r"(\d{1,2})\s*[°º]?\s+(" + "|".join(MESI) + r")\s+(\d{4})", re.I)

assert RE_VIGORE.search("Il presente decreto entra in vigore il 1° gennaio 1988").groups() == ("1", "gennaio", "1988")
assert RE_VIGORE.search("Il presente decreto, che abroga ogni precedente disposizione in materia, "
                        "entra in vigore a datare dal 10 febbraio 1977").group(3) == "1977"
assert not RE_VIGORE.search("Il presente decreto entra in vigore il quinto giorno successivo")


def data_scritta(testo):
    m = RE_VIGORE.search(" ".join((testo or "").split()))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), MESI.index(m.group(2).lower()) + 1, int(m.group(1)))
    except ValueError:
        return None


def main():
    from agente.strumenti import grafo

    scrivi = "--scrivi" in sys.argv
    g = grafo()
    righe = g.query("""
        MATCH (n:Norma)-[:HA_ARTICOLO]->(:Articolo)-[:HA_COMMA]->(c:Comma)
        WHERE n.caricata AND n.dataEntrataVigore IS NULL AND toLower(c.testo) CONTAINS 'in vigore'
        RETURN n.id AS id, toString(n.data) AS data, c.testo AS testo
    """)
    date, scartate = {}, []
    for r in righe:
        vigore = data_scritta(r["testo"])
        if not vigore or r["id"] in date:
            continue
        atto = datetime.date.fromisoformat(r["data"]) if r["data"] else None
        if atto and abs((vigore - atto).days) > 366:
            scartate.append((r["id"], r["data"], vigore))
            continue
        date[r["id"]] = vigore
    print(f"  atti senza data di entrata in vigore che la scrivono per esteso: {len(date)}")
    print(f"  scartati perche' lontani dalla data dell'atto: {len(scartate)} {scartate[:5]}")
    for i, d in list(date.items())[:8]:
        print(f"    {i:<14} {d}")
    if scrivi and date:
        g.query("""
            UNWIND $righe AS r MATCH (n:Norma {id: r.id})
            WHERE n.dataEntrataVigore IS NULL
            SET n.dataEntrataVigore = date(r.data), n.fonteEntrataVigore = 'testo'
        """, {"righe": [{"id": i, "data": d.isoformat()} for i, d in date.items()]})
        print(f"  scritte {len(date)} date")
    elif not scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi per applicare.")


if __name__ == "__main__":
    main()
