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
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from comune import norma_id, risolutore_per_data  # noqa: E402

# Si importano le espressioni DAL PARSER invece di ricopiarle: se un giorno
# divergessero, il grafo smetterebbe di corrispondere a cio' che un
# caricamento pulito produrrebbe, e nessuno se ne accorgerebbe.
_spec = importlib.util.spec_from_file_location("parse02", ROOT / "src" / "02_parse.py")
_parse = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_parse)
RE_BERSAGLIO = _parse.RE_BERSAGLIO

FINESTRA = 90   # quanto testo prima della citazione guarda RE_BERSAGLIO


def risolutore(g):
    """Il tipo scritto nella citazione non e' sempre quello dell'archivio."""
    return risolutore_per_data((r["id"], r["data"]) for r in g.query(
        "MATCH (n:Norma) WHERE n.caricata RETURN n.id AS id, toString(n.data) AS data"))


def bersagli(testo, id_corrente, risolvi=None):
    """Le coppie (id della norma citata, numero d'articolo) leggibili nel testo.

    Passa da estrai_citazioni(), cosi' le forme che il parser riconosce - e le
    autocitazioni che scarta - sono le stesse qui e in un caricamento pulito.
    """
    fuori = []
    for c in _parse.estrai_citazioni(testo, id_corrente):
        if not c["anno"] or not c["articoloCitato"]:
            continue          # norma non identificabile, o citazione d'atto
        bersaglio = norma_id(c["tipo"], c["numero"], c["anno"])
        if risolvi:
            bersaglio = risolvi(bersaglio, c["testo"])
        if bersaglio == id_corrente:
            continue          # l'atto che nomina se stesso con un altro tipo
        voce = (bersaglio, c["articoloCitato"])
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


# Le citazioni d'atto che il parser di allora non leggeva: "Legge 1° marzo 2010
# n.42", "Legge 17 marzo 2005, n. 37", "D.D. n.128/2013", "Leggi 28 giugno 1974
# n. 46". Senza l'arco CITA il comma restava fuori anche dal riallineamento qui
# sotto, che parte dai commi che citano gia' qualcosa. Si rileggono tutti i
# testi e si aggiungono solo gli archi che mancano: quelli presenti non si
# toccano (ON CREATE).
Q_TESTI = """
MATCH (f:Norma)-[:HA_ARTICOLO]->(:Articolo)-[:HA_COMMA]->(c:Comma)
WHERE c.testo IS NOT NULL
RETURN c.id AS comma, c.testo AS testo, f.id AS fonte
"""
Q_PREAMBOLI = """
MATCH (f:Norma) WHERE f.preambolo IS NOT NULL AND f.preambolo <> ''
RETURN f.id AS fonte, f.preambolo AS testo
"""
Q_CITA_ATTO = """
UNWIND $citazioni AS c
MATCH (x) WHERE (c.comma IS NOT NULL AND x:Comma AND x.id = c.comma)
             OR (c.comma IS NULL AND x:Norma AND x.id = c.fonte)
MERGE (target:Norma {id: c.targetId})
  ON CREATE SET target.tipo = c.tipo, target.numero = c.numero,
                target.anno = c.anno, target.caricata = false
MERGE (x)-[r:CITA]->(target)
  ON CREATE SET r.testoCitazione = c.testo, r.articoloCitato = c.articoloCitato,
                r.commaCitato = c.commaCitato, r.origine = c.origine
"""

# L'intestazione dell'atto letta come citazione: il preambolo comincia con
# "DECRETO 20 settembre 2004 n. 119", l'atto sta in archivio come DC-119-2004,
# e l'arco andava a D-119-2004, che non esiste. Lo stesso numero e anno, e la
# citazione in apertura del preambolo: un errata corrige che cita l'atto che
# corregge lo fa piu' avanti. Gli stub rimasti senza archi si tolgono.
Q_INTESTAZIONI = """
MATCH (n:Norma)-[c:CITA]->(x:Norma)
WHERE c.origine = 'preambolo' AND x.numero = n.numero AND x.anno = n.anno
  AND x.id <> n.id AND n.preambolo IS NOT NULL
RETURN n.id AS fonte, x.id AS bersaglio, c.testoCitazione AS testo, elementId(c) AS arco,
       left(n.preambolo, 400) AS inizio
"""
Q_TOGLI_INTESTAZIONI = """
UNWIND $archi AS a
MATCH ()-[c:CITA]->(x:Norma) WHERE elementId(c) = a
DELETE c
WITH DISTINCT x
WHERE NOT coalesce(x.caricata, false) AND NOT (x)--()
DELETE x
RETURN count(x) AS stub
"""


def citazioni_d_atto(g, scrivi):
    risolvi = risolutore(g)
    lotto = []
    for r in g.query(Q_TESTI) + g.query(Q_PREAMBOLI):
        testo = " ".join((r["testo"] or "").split())
        preambolo = r.get("comma") is None
        for c in _parse.estrai_citazioni(testo, r["fonte"], preambolo=preambolo):
            destinazione = risolvi(norma_id(c["tipo"], c["numero"], c["anno"]), c["testo"]) if c["anno"] else None
            if c["anno"] and destinazione != r["fonte"]:
                lotto.append({**c, "comma": r.get("comma"), "fonte": r["fonte"],
                              "targetId": destinazione,
                              "origine": "preambolo" if preambolo else None})
    esistenti = set()
    for i in range(0, len(lotto), 5000):
        for t in g.query("""
            UNWIND $c AS k
            MATCH (x)-[:CITA]->(:Norma {id: k.targetId})
            WHERE (k.comma IS NOT NULL AND x:Comma AND x.id = k.comma)
               OR (k.comma IS NULL AND x:Norma AND x.id = k.fonte)
            RETURN DISTINCT k.comma AS comma, k.fonte AS fonte, k.targetId AS t
        """, {"c": [{"comma": c["comma"], "fonte": c["fonte"], "targetId": c["targetId"]}
                    for c in lotto[i:i + 5000]]}):
            esistenti.add((t["comma"], t["fonte"], t["t"]))
    mancanti = list({(c["comma"], c["fonte"], c["targetId"]): c for c in lotto
                     if (c["comma"], c["fonte"], c["targetId"]) not in esistenti}.values())
    nuovi_atti = {c["targetId"] for c in mancanti}
    in_archivio = {r["id"] for r in g.query(
        "UNWIND $ids AS i MATCH (n:Norma {id: i}) RETURN n.id AS id", {"ids": list(nuovi_atti)})}
    print(f"  citazioni d'atto lette: {len(lotto):,}; archi CITA mancanti: {len(mancanti):,} "
          f"verso {len(nuovi_atti):,} atti ({len(nuovi_atti - in_archivio):,} da creare come stub)")
    for c in mancanti[:12]:
        print(f"    {c['comma'] or c['fonte'] + ' (preambolo)':<34} -> {c['targetId']:<14} ({c['testo']})")
    if scrivi and mancanti:
        for i in range(0, len(mancanti), 2000):
            g.query(Q_CITA_ATTO, {"citazioni": mancanti[i:i + 2000]})
        print(f"    scritti {len(mancanti):,}")
    return mancanti


def intestazioni(g, scrivi):
    righe = []
    for r in g.query(Q_INTESTAZIONI):
        inizio = " ".join((r["inizio"] or "").split())
        pos = inizio.lower().find((r["testo"] or "").lower())
        # "DECRETO - LEGGE 31 gennaio 2007 n.10": il parser di prima, che non
        # conosceva il trattino, ne aveva letto solo "LEGGE ...".
        davanti = re.sub(r"(?i)decreto\s*[-–—]?\s*$", "", inizio[:max(pos, 0)])
        if pos >= 0 and _parse.RE_PRIMA_INTESTAZIONE.fullmatch(davanti):
            righe.append(r)
    print(f"  intestazioni lette come citazione: {len(righe):,}")
    for r in righe[:6]:
        print(f"    {r['fonte']:<22} -> {r['bersaglio']:<14} ({r['testo']})")
    if scrivi and righe:
        tolti = 0
        for i in range(0, len(righe), 2000):
            esito = g.query(Q_TOGLI_INTESTAZIONI, {"archi": [r["arco"] for r in righe[i:i + 2000]]})
            tolti += esito[0]["stub"] if esito else 0
        print(f"    tolti {len(righe):,} archi e {tolti:,} stub rimasti isolati")


def main():
    from agente.strumenti import grafo

    scrivi = "--scrivi" in sys.argv
    g = grafo()
    intestazioni(g, scrivi)
    citazioni_d_atto(g, scrivi)

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
    risolvi = risolutore(g)
    for r in righe:
        testo = " ".join((r["testo"] or "").split())
        for bersaglio, numero in bersagli(testo, r["fonte"], risolvi):
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
