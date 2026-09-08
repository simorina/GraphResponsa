"""
Riallinea gli archi CITA_ARTICOLO al riconoscimento corrente del parser.

Il parser aggancia il bersaglio d'articolo di una citazione con RE_BERSAGLIO,
che fino a oggi pretendeva l'adiacenza fra il numero d'articolo e il nome
dell'atto. Nel linguaggio degli atti quasi mai lo sono - "l'ultimo comma
dell'art. 2 CAP. IV della Legge n.38/1974" - e il 6% delle citazioni nominava
l'articolo senza che venisse letto: 3.775 rinvii che il grafo conosceva solo a
grana d'atto. Allargata l'espressione, sul corpus si passa dal 28,0% al 40,3%.

Quel guadagno pero' vale solo per i caricamenti futuri, e rifare il
caricamento da zero non e' un'opzione: il presidio contro gli Allegati letti
come corpo rifiuterebbe 60 norme che oggi sono in archivio. Questo script
applica il riconoscimento nuovo ai testi GIA' nel grafo e aggiunge gli archi
mancanti, senza toccare nient'altro.

E' idempotente: usa MERGE, e rieseguirlo non duplica nulla. Non cancella archi
esistenti - il riconoscimento e' stato allargato, non ristretto, quindi cio'
che c'era resta valido.

    .venv/Scripts/python.exe src/09_riallinea_citazioni.py           # solo misura
    .venv/Scripts/python.exe src/09_riallinea_citazioni.py --scrivi  # applica
"""

import importlib.util
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from comune import norma_id  # noqa: E402

# Si importano le espressioni DAL PARSER invece di ricopiarle: se un giorno
# divergessero, il grafo smetterebbe di corrispondere a cio' che un
# caricamento pulito produrrebbe, e nessuno se ne accorgerebbe.
_spec = importlib.util.spec_from_file_location("parse02", ROOT / "src" / "02_parse.py")
_parse = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_parse)
RE_CITAZIONE = _parse.RE_CITAZIONE
RE_BERSAGLIO = _parse.RE_BERSAGLIO

FINESTRA = 90   # quanto testo prima della citazione guarda RE_BERSAGLIO


def bersagli(testo, id_corrente):
    """Le coppie (id della norma citata, numero d'articolo) leggibili nel testo."""
    fuori = []
    for m in RE_CITAZIONE.finditer(testo):
        anno = m.group("anno_slash") or m.group("anno_data")
        if not anno:
            continue          # senza anno la norma non e' identificabile
        prima = testo[max(0, m.start() - FINESTRA):m.start()]
        colpito = RE_BERSAGLIO.search(prima)
        if not colpito:
            continue          # citazione d'atto, non d'articolo
        tipo = " ".join(m.group("tipo").split()).title()
        bersaglio = norma_id(tipo, int(m.group("numero")), int(anno))
        if bersaglio == id_corrente:
            continue          # autocitazione
        voce = (bersaglio, colpito.group(1))
        if voce not in fuori:
            fuori.append(voce)
    return fuori


def _finestra(testo, bersaglio, numero):
    """Il tratto attorno alla citazione, non l'inizio del comma.

    Stampare i primi caratteri del testo ha gia' portato una volta a giudicare
    sbagliata una coppia corretta: il campione va letto sulla porzione che ha
    prodotto l'aggancio.
    """
    import re as _re
    for m in _re.finditer(_re.escape(numero), testo):
        prima = testo[max(0, m.start() - 40):m.start()]
        if RE_BERSAGLIO.search(prima + numero + " della "):
            return " ".join(testo[max(0, m.start() - 60):m.start() + 90].split())
    return testo[:150]


def main():
    from agente.strumenti import grafo

    scrivi = "--scrivi" in sys.argv
    g = grafo()

    righe = g.query("""
        MATCH (c:Comma)-[:CITA]->(:Norma)
        MATCH (c)<-[:HA_COMMA]-(:Articolo)<-[:HA_ARTICOLO]-(f:Norma)
        WHERE c.testo IS NOT NULL
        RETURN DISTINCT c.id AS comma, c.testo AS testo, f.id AS fonte
    """)
    print(f"  commi che citano almeno un atto: {len(righe):,}")

    nuovi, scarti = [], {"atto non in archivio": 0, "articolo inesistente": 0,
                         "arco gia' presente": 0}
    cache_norma, cache_art = {}, {}
    for r in righe:
        testo = " ".join((r["testo"] or "").split())
        for bersaglio, numero in bersagli(testo, r["fonte"]):
            chiave = (bersaglio, numero)
            if chiave not in cache_art:
                if bersaglio not in cache_norma:
                    cache_norma[bersaglio] = bool(g.query(
                        "MATCH (n:Norma {id: $i}) RETURN n.id LIMIT 1", {"i": bersaglio}))
                if not cache_norma[bersaglio]:
                    cache_art[chiave] = None
                else:
                    trovato = g.query("""
                        MATCH (n:Norma {id: $i})-[:HA_ARTICOLO]->(a:Articolo)
                        WHERE trim(coalesce(a.numero, '')) = $num
                        RETURN a.id AS id
                    """, {"i": bersaglio, "num": numero})
                    cache_art[chiave] = trovato[0]["id"] if len(trovato) == 1 else None
            if cache_art[chiave] is None:
                scarti["atto non in archivio" if not cache_norma.get(bersaglio)
                       else "articolo inesistente"] += 1
                continue
            nuovi.append({"comma": r["comma"], "articolo": cache_art[chiave],
                          "bersaglio": bersaglio, "numero": numero,
                          "testo": _finestra(testo, bersaglio, numero)})

    # quanti di questi archi esistono gia'?
    esistenti = set()
    for i in range(0, len(nuovi), 5000):
        blocco = nuovi[i:i + 5000]
        for t in g.query("""
            UNWIND $c AS k
            MATCH (:Comma {id: k.comma})-[:CITA_ARTICOLO]->(a:Articolo {id: k.articolo})
            RETURN k.comma AS comma, k.articolo AS articolo
        """, {"c": [{"comma": n["comma"], "articolo": n["articolo"]} for n in blocco]}):
            esistenti.add((t["comma"], t["articolo"]))
    da_creare = [n for n in nuovi if (n["comma"], n["articolo"]) not in esistenti]
    scarti["arco gia' presente"] = len(nuovi) - len(da_creare)

    for k, v in scarti.items():
        print(f"  scartati, {k:<28} {v:>7,}")
    print(f"\n  archi CITA_ARTICOLO da creare: {len(da_creare):,}")

    prima = g.query("MATCH ()-[r:CITA_ARTICOLO]->() RETURN count(r) AS n")[0]["n"]
    print(f"  archi attuali nel grafo:       {prima:,}")

    if not scrivi:
        print("\n  campione da leggere a mano:")
        for n in da_creare[:12]:
            print(f"    {n['comma']:<34} -> {n['bersaglio']} art.{n['numero']}")
            print(f"       {n['testo'][:104]}")
        print("\n  Nulla scritto. Aggiungi --scrivi per applicare al grafo.")
        return

    for i in range(0, len(da_creare), 2000):
        g.query("""
            UNWIND $c AS k
            MATCH (cm:Comma {id: k.comma}), (a:Articolo {id: k.articolo})
            MERGE (cm)-[:CITA_ARTICOLO]->(a)
        """, {"c": [{"comma": n["comma"], "articolo": n["articolo"]}
                    for n in da_creare[i:i + 2000]]})
        print(f"    {min(i + 2000, len(da_creare)):,}/{len(da_creare):,}")

    dopo = g.query("MATCH ()-[r:CITA_ARTICOLO]->() RETURN count(r) AS n")[0]["n"]
    print(f"\n  archi CITA_ARTICOLO: {prima:,} -> {dopo:,}   (+{dopo - prima:,})")


if __name__ == "__main__":
    main()
