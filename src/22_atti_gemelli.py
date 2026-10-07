"""
22 - Gli atti gemelli si vedono a vicenda le modifiche successive.

La stessa disciplina sta in due nodi in due casi:

  - il testo coordinato pubblicato come atto a se' e la legge che coordina:
    il DD-46-2011 e' il "Testo coordinato della Legge 23 febbraio 2006 n. 47";
  - il decreto e la sua ratifica, che ne ripubblica il testo, a volte con
    modifiche: il DD-51-2017 ratifica il DD-126-2016.

Chi modifica dopo ne nomina uno solo, e l'arco CITA_ARTICOLO va li': l'altro
sembra intatto. Il 06/10, in una consultazione vera, l'agente ha dato la soglia
del collegio sindacale del 2011 (7,3 milioni) leggendo il DD-46-2011, mentre
la L-30/2025 aveva modificato la L-47-2006 portandola a 9. Misurato il 07/10:
345 citazioni posteriori verso la L-47-2006 e 2 verso il coordinato; nelle 534
coppie di ratifica, 3.154 citazioni posteriori a entrambi i gemelli che ne
raggiungono uno solo, quasi tutte la ratifica (chi legge il decreto originale
non vede nulla).

Qui:

  - (coordinato)-[:COORDINA]->(legge) e (ratifica)-[:RATIFICA]->(decreto);
  - ogni comma di un atto posteriore a entrambi che cita un articolo di uno
    cita anche l'articolo omologo dell'altro. L'arco porta l'origine
    ('coordinato' o 'ratifica') e `attoCitato`/`articoloCitato`, l'atto e
    l'articolo che il comma nomina davvero: gli strumenti li usano per
    riconoscere la riscrittura, perche' la novella dice "n.26/2015" e non
    "n.226/2014". Gli archi del parser restano suoi;
  - un articolo o un comma abrogato da un atto posteriore a entrambi porta la
    stessa marcatura sull'omologo, se il testo e' lo stesso.

L'omologo. Il coordinato conserva la numerazione: e' l'articolo con lo stesso
numero. La ratifica no: puo' aggiungere articoli e spostare i numeri (il
DD-26-2015 ne ha 53, il DD-226-2014 35) o essere un altro testo (il DD-12-2017
contro il DD-149-2016). Per la ratifica l'omologo e' lo stesso numero se il
testo somiglia o la rubrica e' la stessa, altrimenti l'articolo di testo quasi
uguale sotto un altro numero; se non c'e', nessun arco. Misurato il 07/10 sui
949 articoli citati: 908 allo stesso numero, 6 sotto un altro, 35 senza.

Le coppie di ratifica sono quelle di 08_abrogazioni.ratifiche(). Le marcature
di abrogazione le azzera e le riscrive 08: questo script va rieseguito DOPO 08
(e dopo 09, che scrive gli archi del parser).

Uso:
    .venv/Scripts/python.exe src/22_atti_gemelli.py            # solo misura
    .venv/Scripts/python.exe src/22_atti_gemelli.py --scrivi
"""

import difflib
import importlib.util
import os
import re
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from langchain_neo4j import Neo4jGraph

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# La stessa espressione con cui l'agente riconosce un coordinato: se le due
# divergessero, l'agente cercherebbe una base diversa da quella scritta qui.
from agente.strumenti import ORIGINI_GEMELLI, RE_COORDINATO  # noqa: E402

TIPI = {"coordinato": "COORDINA", "ratifica": "RATIFICA"}
# Gli strumenti riconoscono questi archi dall'origine: le due liste coincidono.
assert set(TIPI) == set(ORIGINI_GEMELLI)
# Somiglianza dei testi (sui primi 600 caratteri, a meno di spazi e maiuscole):
SIMILE = 0.6         # stesso numero e testo che somiglia: lo stesso articolo
ALTROVE = 0.8        # sotto un altro numero ci vuole di piu'
STESSO_TESTO = 0.9   # per propagare un'abrogazione, il testo dev'essere quello


def _modulo(nome, file):
    spec = importlib.util.spec_from_file_location(nome, RADICE / "src" / file)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def grafo():
    load_dotenv(RADICE / ".env")
    return Neo4jGraph(url=os.environ["NEO4J_URI"],
                      username=os.environ["NEO4J_USERNAME"],
                      password=os.environ["NEO4J_PASSWORD"],
                      database=os.getenv("NEO4J_DATABASE", "neo4j"),
                      refresh_schema=False)


def _normale(testo):
    return " ".join((testo or "").lower().split())[:600]


def somiglianza(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, _normale(a), _normale(b)).ratio()


def _stessa_rubrica(a, b):
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return len(a) > 12 and a == b


# --- le coppie -------------------------------------------------------------

Q_COORDINATI = """
MATCH (n:Norma) WHERE toLower(n.titolo) CONTAINS 'testo coordinato'
RETURN n.id AS id, n.titolo AS titolo ORDER BY n.id
"""

# L'id piu' corto: le schede doppie portano un suffisso ("L-17-1917~17148777")
# e l'originale e' quella senza.
Q_BASE = """
MATCH (b:Norma)
WHERE toLower(trim(b.tipo)) = $tipo AND toString(b.numero) = $numero
  AND b.anno = $anno AND b.id <> $id
RETURN b.id AS id ORDER BY size(b.id), b.id LIMIT 1
"""


# 08 cerca le ratifiche fra gli atti con "ratifica" nel TITOLO. Diciotto lo
# dicono solo nel preambolo: il DD-81-2008 si intitola "CODICE DELLA STRADA" e
# si apre con "(Ratifica Decreto Delegato 28 aprile 2008 n.67)"; 196 modifiche
# posteriori raggiungevano uno solo dei due. Qui si leggono con le stesse
# regole di 08; quattro erano abbinamenti sbagliati (il DD-4-2017 "Reiterazione
# Decreto Delegato" finiva sulla Legge Qualificata sul Congresso di Stato), e
# si tengono solo le coppie che hanno davvero articoli in comune (vedi
# condividono()). 08 resta com'e': per le abrogazioni dell'atto intero.
Q_RATIFICHE_PREAMBOLO = """
MATCH (r:Norma) WHERE r.caricata AND NOT toLower(r.titolo) CONTAINS 'ratifica'
  AND toLower(substring(coalesce(r.preambolo, ''), 0, 600)) CONTAINS 'ratifica'
  AND NOT r.id STARTS WITH 'EC-' AND NOT toLower(r.titolo) CONTAINS 'errata'
RETURN r.id AS id, r.titolo AS titolo, r.data AS data,
       substring(coalesce(r.preambolo, ''), 0, 600) AS intestazione
"""
# Quota degli articoli del piu' piccolo dei due che deve avere un omologo.
IN_COMUNE = 0.3


def ratifiche_dal_preambolo(g, ab):
    """Le coppie (ratifica, decreto) dichiarate solo nel preambolo, con i controlli di 08."""
    trovate = []
    for r in g.query(Q_RATIFICHE_PREAMBOLO):
        m = ab.RATIFICA.search(r["intestazione"].translate(ab.APOSTROFI))
        nominato = m and ab.NOMINATO.search(m.group(1))
        if not nominato:
            continue
        numero, anno = ab.estremi(nominato.groups()[1:])
        tipo = re.sub(r"\s*[-–]\s*", " ", " ".join(nominato.group(1).lower().split()))
        norme = g.query("""
            MATCH (n:Norma) WHERE n.numero = $numero AND n.anno = $anno AND n.caricata
            RETURN n.id AS id, toString(n.data) AS data
        """, {"numero": numero, "anno": anno})
        motivo, scelto = ab.atto_del_tipo([x["id"] for x in norme], tipo.replace("consigliare", "consiliare"))
        if motivo or scelto == r["id"]:
            continue
        data = next(x["data"] for x in norme if x["id"] == scelto)
        if ab.data_discorde(nominato.group(0), numero, anno, data):
            continue
        if not data or not r["data"] or str(r["data"]) < data:
            continue
        trovate.append((r["id"], scelto))
    return trovate


def condividono(articoli_a, articoli_b):
    """Se due atti hanno davvero articoli in comune: lo dice il testo, non il titolo."""
    piccolo, grande = sorted((articoli_a, articoli_b), key=len)
    if not piccolo:
        return False
    con_omologo = sum(omologo("ratifica", a, grande)[0] is not None for a in piccolo)
    return con_omologo >= IN_COMUNE * len(piccolo)


def coppie(g):
    """[{tipo, a, b}]: a e' il coordinato o la ratifica, b la legge o il decreto."""
    trovate, senza = [], []
    for c in g.query(Q_COORDINATI):
        m = RE_COORDINATO.search(c["titolo"] or "")
        if not m:
            senza.append((c["id"], "titolo non riconosciuto"))
            continue
        base = g.query(Q_BASE, {"tipo": re.sub(r"\s+", " ", m.group(1).lower()),
                                "numero": m.group(3), "anno": int(m.group(2)), "id": c["id"]})
        if base:
            trovate.append({"tipo": "coordinato", "a": c["id"], "b": base[0]["id"]})
        else:
            senza.append((c["id"], f"base {m.group(1)} {m.group(3)}/{m.group(2)} non in archivio"))
    abrogazioni = _modulo("abrogazioni08", "08_abrogazioni.py")
    note = abrogazioni.ratifiche(g)
    trovate += [{"tipo": "ratifica", "a": r, "b": d} for r, d in note]
    trovate += [{"tipo": "ratifica", "a": r, "b": d, "preambolo": True}
                for r, d in ratifiche_dal_preambolo(g, abrogazioni) if (r, d) not in set(note)]
    return trovate, senza


# --- le citazioni posteriori -------------------------------------------------

# Posteriore a entrambi i gemelli: nello stesso anno decide la data. Gli archi
# scritti da qui non si propagano a loro volta.
Q_CITAZIONI = """
UNWIND $coppie AS p
MATCH (x:Norma {id: p.a}), (y:Norma {id: p.b})
WITH p, x, y, CASE WHEN x.data >= y.data THEN x ELSE y END AS ultimo
UNWIND [[x, y], [y, x]] AS verso
WITH p, ultimo, verso[0] AS citato, verso[1] AS gemello
MATCH (citato)-[:HA_ARTICOLO]->(a:Articolo)<-[r:CITA_ARTICOLO]-(cm:Comma)
      <-[:HA_COMMA]-(:Articolo)<-[:HA_ARTICOLO]-(dopo:Norma)
WHERE NOT coalesce(r.origine, '') IN $nostre
  AND dopo.id <> p.a AND dopo.id <> p.b
  AND (dopo.anno > ultimo.anno OR (dopo.anno = ultimo.anno AND dopo.data > ultimo.data))
RETURN p.tipo AS tipo, citato.id AS citato, gemello.id AS gemello,
       a.numero AS numero, cm.id AS comma, dopo.id AS atto
"""

Q_ARTICOLI = """
UNWIND $norme AS nid
MATCH (:Norma {id: nid})-[:HA_ARTICOLO]->(a:Articolo)
RETURN nid AS norma, a.id AS id, a.numero AS numero, a.rubrica AS rubrica, a.testo AS testo
"""

Q_GIA = """
UNWIND $archi AS x
MATCH (:Comma {id: x.comma})-[:CITA_ARTICOLO]->(:Articolo {id: x.articolo})
RETURN x.comma AS comma, x.articolo AS articolo
"""


def omologo(tipo, articolo, articoli_gemello):
    """(articolo omologo nel gemello, come e' stato trovato) o (None, motivo)."""
    stesso = next((a for a in articoli_gemello if a["numero"] == articolo["numero"]), None)
    if tipo == "coordinato":
        return (stesso, "stesso numero") if stesso else (None, "nessun omologo")
    if stesso and (somiglianza(articolo["testo"], stesso["testo"]) >= SIMILE
                   or _stessa_rubrica(articolo["rubrica"], stesso["rubrica"])):
        return stesso, "stesso numero"
    migliore, punti = None, 0.0
    for a in articoli_gemello:
        s = somiglianza(articolo["testo"], a["testo"])
        if s > punti:
            migliore, punti = a, s
    if migliore is not None and punti >= ALTROVE:
        return migliore, "altro numero"
    return None, ("stesso numero, testo diverso" if stesso else "nessun omologo")


# --- le abrogazioni -----------------------------------------------------------

Q_ABROGATI = """
UNWIND $norme AS nid
MATCH (:Norma {id: nid})-[:HA_ARTICOLO]->(a:Articolo)
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma) WHERE c.abrogato
WITH nid, a, c WHERE a.abrogato OR c IS NOT NULL
RETURN nid AS norma, a.numero AS numero, c.numero AS comma, a.abrogato AS articoloAbrogato,
       CASE WHEN c IS NULL THEN a.testo ELSE c.testo END AS testo,
       CASE WHEN c IS NULL THEN a.abrogatoDa ELSE c.abrogatoDa END AS fonti,
       a.abrogatoDa AS fontiArticolo, a.testo AS testoArticolo
"""

Q_DATE = """
UNWIND $ids AS id MATCH (n:Norma {id: id})
RETURN n.id AS id, n.anno AS anno, toString(n.data) AS data
"""

Q_COMMI = """
UNWIND $articoli AS aid
MATCH (:Articolo {id: aid})-[:HA_COMMA]->(c:Comma)
RETURN aid AS articolo, c.id AS id, c.numero AS numero, c.testo AS testo, c.abrogato AS abrogato
"""


def abrogazioni(g, piano, articoli, date):
    """[(tipo, id del bersaglio nel gemello, fonti posteriori, descrizione)] e gli scarti."""
    norme = sorted({x for p in piano for x in (p["a"], p["b"])})
    righe = g.query(Q_ABROGATI, {"norme": norme})
    # Un articolo abrogato per intero con anche commi abrogati compare piu'
    # volte: la riga dell'articolo si ricava dalla prima.
    voci = []
    for r in righe:
        if r["comma"] is not None:
            voci.append({**r})
        if r["articoloAbrogato"]:
            voci.append({**r, "comma": None, "testo": r["testoArticolo"], "fonti": r["fontiArticolo"]})
    voci = list({(v["norma"], v["numero"], v["comma"]): v for v in voci}.values())
    fonti = sorted({f for v in voci for f in (v["fonti"] or [])})
    date.update({r["id"]: (r["anno"] or 0, r["data"] or "") for r in g.query(Q_DATE, {"ids": fonti})})
    gemelli = {}
    for p in piano:
        gemelli.setdefault(p["a"], []).append((p["tipo"], p["b"], p))
        gemelli.setdefault(p["b"], []).append((p["tipo"], p["a"], p))

    candidati, scarti = [], Counter()
    for v in voci:
        for tipo, gemello, p in gemelli.get(v["norma"], []):
            ultimo = max(date[p["a"]], date[p["b"]])
            posteriori = [f for f in (v["fonti"] or []) if f in date and date[f] > ultimo]
            parte = f"{v['norma']} art. {v['numero']}" + (f", comma {v['comma']}" if v["comma"] else "")
            if not posteriori:
                scarti["abrogazione anteriore al gemello (gia' nel suo testo) o senza fonte"] += 1
                continue
            articolo = next(a for a in articoli[v["norma"]] if a["numero"] == v["numero"])
            art_gemello, _ = omologo(tipo, articolo, articoli[gemello])
            if art_gemello is None:
                scarti["nessun articolo omologo"] += 1
                continue
            candidati.append({"tipo": tipo, "parte": parte, "comma": v["comma"], "testo": v["testo"],
                              "articolo": art_gemello, "fonti": posteriori})
    commi = {}
    ids = sorted({c["articolo"]["id"] for c in candidati if c["comma"]})
    for r in (g.query(Q_COMMI, {"articoli": ids}) if ids else []):
        commi.setdefault(r["articolo"], []).append(r)

    risultato = []
    for c in candidati:
        if c["comma"] is None:
            bersaglio = c["articolo"]
            gia = False
        else:
            bersaglio = next((x for x in commi.get(c["articolo"]["id"], [])
                              if x["numero"] == c["comma"]), None)
            gia = bool(bersaglio and bersaglio["abrogato"])
        if bersaglio is None:
            scarti["nessun comma omologo"] += 1
        elif somiglianza(c["testo"], bersaglio["testo"]) < STESSO_TESTO:
            scarti["l'omologo ha un testo diverso"] += 1
        else:
            risultato.append({"tipo": c["tipo"], "id": bersaglio["id"], "fonti": c["fonti"],
                              "comma": c["comma"] is not None, "parte": c["parte"], "gia": gia})
    return risultato, scarti


Q_SCRIVI_ARCHI = """
UNWIND $archi AS x
MATCH (cm:Comma {id: x.comma}), (a:Articolo {id: x.articolo})
MERGE (cm)-[r:CITA_ARTICOLO]->(a)
  ON CREATE SET r.origine = x.origine, r.attoCitato = x.attoCitato, r.articoloCitato = x.articoloCitato
"""
Q_SCRIVI_ARTICOLI = """
UNWIND $voci AS x MATCH (a:Articolo {id: x.id})
SET a.abrogato = true, a.abrogatoDa = x.fonti
"""
Q_SCRIVI_COMMI = """
UNWIND $voci AS x MATCH (c:Comma {id: x.id})
SET c.abrogato = true, c.abrogatoDa = x.fonti
"""


def main():
    scrivi = "--scrivi" in sys.argv
    g = grafo()
    piano, senza = coppie(g)
    norme = sorted({x for p in piano for x in (p["a"], p["b"])})
    articoli = {n: [] for n in norme}
    for r in g.query(Q_ARTICOLI, {"norme": norme}):
        articoli[r["norma"]].append(r)
    dal_preambolo = [p for p in piano if p.get("preambolo")]
    scartate = [p for p in dal_preambolo if not condividono(articoli[p["a"]], articoli[p["b"]])]
    piano = [p for p in piano if p not in scartate]
    norme = sorted({x for p in piano for x in (p["a"], p["b"])})
    per_tipo = Counter(p["tipo"] for p in piano)
    print(f"\n  coppie: {dict(per_tipo)}  (ratifiche dichiarate solo nel preambolo: "
          f"{len(dal_preambolo) - len(scartate)} tenute, {len(scartate)} senza articoli in comune)")
    for p in scartate:
        print(f"   scartata {p['a']} ratifica {p['b']}: nessun articolo in comune")
    for nid, motivo in senza:
        print(f"   saltato {nid}: {motivo}")

    citazioni = []
    for i in range(0, len(piano), 50):
        citazioni += g.query(Q_CITAZIONI, {"coppie": piano[i:i + 50], "nostre": list(TIPI)})
    date = {r["id"]: (r["anno"] or 0, r["data"] or "") for r in g.query(Q_DATE, {"ids": norme})}

    archi, esiti = {}, Counter()
    cache = {}
    for c in citazioni:
        chiave = (c["tipo"], c["citato"], c["numero"], c["gemello"])
        if chiave not in cache:
            articolo = next(a for a in articoli[c["citato"]] if a["numero"] == c["numero"])
            cache[chiave] = omologo(c["tipo"], articolo, articoli[c["gemello"]])
        bersaglio, come = cache[chiave]
        esiti[(c["tipo"], come)] += 1
        if bersaglio is not None:
            archi[(c["comma"], bersaglio["id"])] = {
                "comma": c["comma"], "articolo": bersaglio["id"], "origine": c["tipo"],
                "attoCitato": c["citato"], "articoloCitato": c["numero"]}
    gia = set()
    lista = list(archi.values())
    for i in range(0, len(lista), 2000):
        gia |= {(r["comma"], r["articolo"]) for r in g.query(Q_GIA, {"archi": lista[i:i + 2000]})}
    nuovi = [a for k, a in archi.items() if k not in gia]

    print(f"\n  citazioni posteriori a entrambi i gemelli: {len(citazioni)}")
    for (tipo, come), n in sorted(esiti.items()):
        print(f"   {tipo:<11} {come:<30} {n:>6}")
    print(f"  archi verso l'omologo: {len(archi)} | gia' presenti: {len(gia)} | da aggiungere: "
          f"{len(nuovi)}  {dict(Counter(a['origine'] for a in nuovi))}")
    print(f"  atti che vengono raggiunti di nuovo: "
          f"{len({a['articolo'].split('/')[0] for a in nuovi})}")

    abrogati, scarti = abrogazioni(g, piano, articoli, date)
    print(f"\n  abrogazioni da propagare all'omologo: {len(abrogati)} "
          f"({sum(not v['gia'] for v in abrogati)} non ancora marcate)")
    for v in abrogati[:20]:
        print(f"   {v['tipo']:<11} {v['parte']} -> {v['id']} da {v['fonti']}"
              + (" (gia' marcato)" if v["gia"] else ""))
    if len(abrogati) > 20:
        print(f"   ... e altre {len(abrogati) - 20}")
    for motivo, n in scarti.most_common():
        print(f"   non propagate: {n:>4}  {motivo}")

    if not scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi per applicare al grafo.")
        return

    g.query("MATCH ()-[r:CITA_ARTICOLO]->() WHERE r.origine IN $nostre DELETE r",
            {"nostre": list(TIPI)})
    for tipo, relazione in TIPI.items():
        g.query(f"MATCH ()-[r:{relazione}]->() DELETE r")
        g.query(f"""
            UNWIND $coppie AS p MATCH (a:Norma {{id: p.a}}), (b:Norma {{id: p.b}})
            MERGE (a)-[:{relazione}]->(b)
        """, {"coppie": [p for p in piano if p["tipo"] == tipo]})
    for i in range(0, len(nuovi), 1000):
        g.query(Q_SCRIVI_ARCHI, {"archi": nuovi[i:i + 1000]})
    g.query(Q_SCRIVI_ARTICOLI, {"voci": [{"id": v["id"], "fonti": v["fonti"]}
                                         for v in abrogati if not v["comma"]]})
    g.query(Q_SCRIVI_COMMI, {"voci": [{"id": v["id"], "fonti": v["fonti"]}
                                      for v in abrogati if v["comma"]]})
    conta = g.query("""
        MATCH ()-[r:CITA_ARTICOLO]->() WHERE r.origine IN $nostre
        WITH r.origine AS origine, count(r) AS n RETURN collect([origine, n]) AS archi
    """, {"nostre": list(TIPI)})[0]["archi"]
    relazioni = {t: g.query(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS n")[0]["n"]
                 for t, rel in TIPI.items()}
    print(f"\n  scritto: {relazioni} | archi CITA_ARTICOLO {dict(conta)} | "
          f"abrogazioni propagate {len(abrogati)}")
    print("  Se si riesegue 08_abrogazioni.py, rieseguire poi anche questo script.")


if __name__ == "__main__":
    main()
