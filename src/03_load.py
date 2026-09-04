"""
03 - Caricamento del JSON strutturato in Neo4j Aura.

Tutto in MERGE: rieseguire non duplica nulla (idempotente).

Ordine deliberato: prima le norme realmente scaricate (caricata=true), poi le
citazioni. Cosi' una norma citata che e' anche stata scaricata non viene mai
declassata a stub.

Le norme citate ma non presenti in archivio diventano nodi stub con
caricata=false: il grafo sa che esistono e sono citate, pur senza averne il
testo. Sono anche la lista di lavoro per il prossimo scaricamento.
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comune import LABELS, PREFISSI, norma_id, norma_label  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PARSED = ROOT / "data" / "parsed"

VINCOLI = [
    "CREATE CONSTRAINT norma_id IF NOT EXISTS FOR (n:Norma) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT articolo_id IF NOT EXISTS FOR (a:Articolo) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT comma_id IF NOT EXISTS FOR (c:Comma) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT allegato_id IF NOT EXISTS FOR (x:Allegato) REQUIRE x.id IS UNIQUE",
]

# L'analizzatore italiano fa convergere "edilizio" ed "edilizia".
INDICI = [
    ("""CREATE FULLTEXT INDEX testo_normativo IF NOT EXISTS
        FOR (n:Comma|Articolo) ON EACH [n.testo, n.rubrica]
        OPTIONS {indexConfig: {`fulltext.analyzer`: 'italian'}}""",
     """CREATE FULLTEXT INDEX testo_normativo IF NOT EXISTS
        FOR (n:Comma|Articolo) ON EACH [n.testo, n.rubrica]"""),
    ("""CREATE FULLTEXT INDEX titoli_norme IF NOT EXISTS
        FOR (n:Norma) ON EACH [n.titolo]
        OPTIONS {indexConfig: {`fulltext.analyzer`: 'italian'}}""",
     """CREATE FULLTEXT INDEX titoli_norme IF NOT EXISTS
        FOR (n:Norma) ON EACH [n.titolo]"""),
]

Q_NORMA = """
MERGE (n:Norma {id: $id})
SET n.tipo = $tipo, n.numero = $numero, n.anno = $anno,
    n.data = CASE WHEN $data IS NULL THEN NULL ELSE date($data) END, n.titolo = $titolo,
    n.dataPubblicazione = CASE WHEN $dataPubblicazione IS NULL THEN NULL ELSE date($dataPubblicazione) END,
    n.dataEntrataVigore  = CASE WHEN $dataEntrataVigore  IS NULL THEN NULL ELSE date($dataEntrataVigore)  END,
    n.urlScheda = $urlScheda, n.urlDocumento = $urlDocumento,
    n.preambolo = $preambolo,
    n.caricata = true
"""

Q_ARTICOLI = """
UNWIND $articoli AS a
MATCH (n:Norma {id: $normaId})
MERGE (art:Articolo {id: a.id})
SET art.numero = a.numero, art.rubrica = a.rubrica, art.ordine = a.ordine,
    art.testo = a.testo,
    art.titolo = a.titolo, art.titoloRubrica = a.titoloRubrica,
    art.capo = a.capo, art.capoRubrica = a.capoRubrica
MERGE (n)-[:HA_ARTICOLO]->(art)
WITH art, a
UNWIND a.commi AS c
MERGE (cm:Comma {id: c.id})
SET cm.numero = c.numero, cm.testo = c.testo, cm.ordine = c.ordine,
    cm.numerazioneAnomala = c.numerazioneAnomala,
    cm.commaImplicito = c.commaImplicito
MERGE (art)-[:HA_COMMA]->(cm)
"""

Q_ALLEGATI = """
UNWIND $allegati AS al
MATCH (n:Norma {id: $normaId})
MERGE (x:Allegato {id: al.id})
SET x.nome = al.nome, x.bytes = al.bytes
MERGE (n)-[:HA_ALLEGATO]->(x)
"""

# Le citazioni creano stub solo per norme non gia' presenti.
Q_CITAZIONI = """
UNWIND $citazioni AS c
MATCH (cm:Comma {id: c.commaId})
MERGE (target:Norma {id: c.targetId})
  ON CREATE SET target.tipo = c.tipo, target.numero = c.numero,
                target.anno = c.anno, target.caricata = false
MERGE (cm)-[r:CITA]->(target)
SET r.testoCitazione = c.testo,
    r.articoloCitato = c.articoloCitato,
    r.commaCitato = c.commaCitato
"""

# Le citazioni del preambolo ("Visto l'articolo 4 della Legge Costituzionale
# n.185/2005...") non stanno in nessun comma: partono dalla norma stessa.
# Sono la base costituzionale dell'atto, quindi non vanno perse.
Q_CITAZIONI_PREAMBOLO = """
UNWIND $citazioni AS c
MATCH (n:Norma {id: c.normaId})
MERGE (target:Norma {id: c.targetId})
  ON CREATE SET target.tipo = c.tipo, target.numero = c.numero,
                target.anno = c.anno, target.caricata = false
MERGE (n)-[r:CITA]->(target)
SET r.testoCitazione = c.testo,
    r.articoloCitato = c.articoloCitato,
    r.commaCitato = c.commaCitato,
    r.origine = 'preambolo'
"""

# Collegamento puntuale, solo se l'articolo bersaglio esiste davvero nel grafo.
Q_CITA_ARTICOLO = """
UNWIND $citazioni AS c
MATCH (cm:Comma {id: c.commaId})
MATCH (a:Articolo {id: c.targetId + '/art-' + c.articoloCitato})
MERGE (cm)-[:CITA_ARTICOLO]->(a)
"""


def motivo_scarto(dati):
    """
    Dice perche' un record non e' caricabile, o None se e' sano.

    Non tutto cio' che sta in data/parsed viene da 02_parse.py: alcuni Statuti
    sono stati integrati da script a parte e portano i byte grezzi del PDF al
    posto del testo estratto. Caricarli riempirebbe i nodi :Comma di binario,
    che finirebbe nell'indice full-text, negli embedding e quindi nelle
    risposte dell'agente come se fosse testo normativo. Meglio saltarli, e
    dirlo forte: un record scartato in silenzio e' un buco che nessuno trova.
    """
    for a in dati.get("articoli") or []:
        for c in a.get("commi") or []:
            if "id" not in c:
                return "commi privi di id: non prodotto da 02_parse.py"
            testo = (c.get("testo") or "").lstrip()
            if testo.startswith("%PDF") or "endstream" in testo[:2000]:
                return "testo binario: il PDF non e' stato estratto"
    return None


def prepara(dati):
    """Appiattisce il JSON nelle forme attese dalle query."""
    nid = dati["id"]

    # Titolo e Capo diventano proprieta' dell'articolo: la struttura del grafo
    # e' Norma -> Articolo -> Comma, ma il contesto tematico non si perde.
    #
    # Le chiavi si leggono con .get(): non tutti i JSON in data/parsed vengono
    # da 02_parse.py - alcuni Statuti sono stati integrati a parte, con una
    # forma piu' povera. Una chiave assente non deve far cadere il caricamento
    # dell'intero corpus a tre quarti del lavoro.
    contesto = {}
    for t in dati.get("partizioni") or []:
        contesto[t["id"]] = {"titolo": f"{t['tipo']} {t['numero']}",
                             "titoloRubrica": t.get("rubrica"),
                             "capo": None, "capoRubrica": None}
        for c in t.get("figli", []):
            contesto[c["id"]] = {"titolo": f"{t['tipo']} {t['numero']}",
                                 "titoloRubrica": t.get("rubrica"),
                                 "capo": f"{c['tipo']} {c['numero']}",
                                 "capoRubrica": c.get("rubrica")}

    articoli = []
    for a in dati.get("articoli") or []:
        # L'id del comma arriva dal parser: e' lui a sapere come disambiguare
        # i numeri ripetuti (novelle e refusi della legge).
        commi = [{"id": c["id"], "numero": c["numero"], "testo": c["testo"],
                  "ordine": i, "numerazioneAnomala": c.get("numerazioneAnomala", False),
                  "commaImplicito": c.get("commaImplicito", False)}
                 for i, c in enumerate(a.get("commi") or [])]
        ctx = contesto.get(a.get("partizioneId")) or {
            "titolo": None, "titoloRubrica": None, "capo": None, "capoRubrica": None}
        articoli.append({
            "id": a["id"], "numero": a["numero"], "rubrica": a.get("rubrica"),
            "ordine": a.get("ordine", 0), **ctx,
            "testo": " ".join(c["testo"] for c in a.get("commi") or []),
            "commi": commi,
        })

    citazioni = []
    for a in dati.get("articoli") or []:
        for c in a.get("citazioni") or []:
            if not c["anno"]:
                continue  # senza anno la norma non e' identificabile
            citazioni.append({
                "commaId": c["commaId"],
                "targetId": norma_id(c["tipo"], c["numero"], c["anno"]),
                "tipo": c["tipo"], "numero": c["numero"], "anno": c["anno"],
                "articoloCitato": c["articoloCitato"],
                "commaCitato": c["commaCitato"],
                "testo": c["testo"],
            })

    cit_preambolo = []
    for c in dati.get("citazioniPreambolo", []):
        if not c["anno"]:
            continue
        cit_preambolo.append({
            "normaId": nid,
            "targetId": norma_id(c["tipo"], c["numero"], c["anno"]),
            "tipo": c["tipo"], "numero": c["numero"], "anno": c["anno"],
            "articoloCitato": c["articoloCitato"],
            "commaCitato": c["commaCitato"],
            "testo": c["testo"],
        })

    allegati = [{"id": f"{nid}/all-{i}", "nome": al["nome"], "bytes": al["bytes"]}
                for i, al in enumerate(dati.get("allegati", []))]

    return articoli, citazioni, cit_preambolo, allegati


def run_con_retry(driver, db, query, params=None, max_tentativi=4):
    """Esegue una query gestendo riconnessioni e retry automatici."""
    for tentativo in range(max_tentativi):
        try:
            with driver.session(database=db) as s:
                return s.run(query, **(params or {})).consume()
        except Exception as e:
            if tentativo == max_tentativi - 1:
                raise
            time.sleep(2 * (tentativo + 1))


def chunk_list(lista, dimensione=500):
    """Divide una lista in sotto-liste di dimensione fissa."""
    for i in range(0, len(lista), dimensione):
        yield lista[i:i + dimensione]


def main(reset=False):
    load_dotenv(ROOT / ".env")
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        max_connection_lifetime=180,
    )
    driver.verify_connectivity()
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    file_json = sorted(PARSED.glob("*.json"))
    if not file_json:
        raise RuntimeError("data/parsed/ e' vuota: eseguire prima 02_parse.py")

    with driver.session(database=db) as s:
        if reset:
            s.run("MATCH (n) DETACH DELETE n")
            print("Grafo svuotato.")
        for q in VINCOLI:
            s.run(q)
        for preferita, ripiego in INDICI:
            try:
                s.run(preferita)
            except Exception:
                s.run(ripiego)
        print("Vincoli e indici pronti.")

        rimossi = s.run("MATCH (p:Partizione) DETACH DELETE p "
                        "RETURN count(p) AS c").single()["c"]
        if rimossi:
            print(f"Rimossi {rimossi} nodi Partizione (ora sono proprieta').")

    print(f"\nCaricamento di {len(file_json)} norme...")
    tutte_citazioni = []
    tutte_preambolo = []

    # Carica le norme e gli articoli
    scartati = []
    for idx, f in enumerate(file_json, 1):
        # L'elenco dei file si legge all'inizio, ma il caricamento dura minuti:
        # se nel frattempo qualcosa tocca data/parsed - una riparazione, un
        # nuovo parsing - il file puo' non esserci piu'. Non e' un motivo per
        # buttare via il lavoro fatto su altri diecimila.
        try:
            dati = json.loads(f.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError) as e:
            scartati.append((f.stem, f"illeggibile: {type(e).__name__}"))
            continue
        nid = dati["id"]

        motivo = motivo_scarto(dati)
        if motivo:
            scartati.append((nid, motivo))
            continue

        articoli, citazioni, cit_preambolo, allegati = prepara(dati)
        tutte_preambolo += cit_preambolo
        tutte_citazioni += citazioni

        lbl = norma_label(dati.get("tipo"))
        set_lbl = f"SET n:`{lbl}`" if (lbl and lbl != "Norma") else ""
        q_norma_specifica = f"""
        MERGE (n:Norma {{id: $id}})
        {set_lbl}
        SET n.tipo = $tipo, n.numero = $numero, n.anno = $anno,
            n.data = CASE WHEN $data IS NULL THEN NULL ELSE date($data) END, n.titolo = $titolo,
            n.dataPubblicazione = CASE WHEN $dataPubblicazione IS NULL THEN NULL ELSE date($dataPubblicazione) END,
            n.dataEntrataVigore  = CASE WHEN $dataEntrataVigore  IS NULL THEN NULL ELSE date($dataEntrataVigore)  END,
            n.urlScheda = $urlScheda, n.urlDocumento = $urlDocumento,
            n.preambolo = $preambolo,
            n.caricata = true
        """

        norma_params = {k: dati.get(k) for k in
                        ["id", "tipo", "numero", "anno", "data", "titolo",
                         "dataPubblicazione", "dataEntrataVigore",
                         "urlScheda", "urlDocumento", "preambolo"]}

        run_con_retry(driver, db, q_norma_specifica, norma_params)
        if articoli:
            run_con_retry(driver, db, Q_ARTICOLI, {"normaId": nid, "articoli": articoli})
        if allegati:
            run_con_retry(driver, db, Q_ALLEGATI, {"normaId": nid, "allegati": allegati})

        if idx % 25 == 0 or idx == len(file_json):
            print(f"  [{idx}/{len(file_json)}] caricate...")

    if scartati:
        print(f"\nScartati {len(scartati)} record non caricabili:")
        for nid, motivo in scartati[:10]:
            print(f"  {nid}: {motivo}")
        if len(scartati) > 10:
            print(f"  ... e altri {len(scartati) - 10}")

    print(f"\nCaricamento citazioni ({len(tutte_citazioni)} totali)...")
    for chunk in chunk_list(tutte_citazioni, 500):
        run_con_retry(driver, db, Q_CITAZIONI, {"citazioni": chunk})

    if tutte_preambolo:
        print(f"Caricamento citazioni preambolo ({len(tutte_preambolo)} totali)...")
        for chunk in chunk_list(tutte_preambolo, 500):
            run_con_retry(driver, db, Q_CITAZIONI_PREAMBOLO, {"citazioni": chunk})

    puntuali = [c for c in tutte_citazioni if c["articoloCitato"]]
    if puntuali:
        print(f"Collegamento citazioni puntuali ({len(puntuali)} totali)...")
        for chunk in chunk_list(puntuali, 500):
            run_con_retry(driver, db, Q_CITA_ARTICOLO, {"citazioni": chunk})

    # Assegna etichette secondarie in batch per tipo
    print("Assegnazione etichette secondarie...")
    for tipo_chiave, label_nome in set(LABELS.items()):
        if label_nome and label_nome != "Norma":
            q_lbl = f"""
            MATCH (n:Norma)
            WHERE toLower(trim(n.tipo)) = $tipo AND NOT n:`{label_nome}`
            SET n:`{label_nome}`
            """
            run_con_retry(driver, db, q_lbl, {"tipo": tipo_chiave.lower()})

    with driver.session(database=db) as s:
        stub = s.run("MATCH (n:Norma {caricata: false}) RETURN count(n) AS c").single()["c"]
        tot = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rel = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"\nGrafo completato: {tot} nodi, {rel} relazioni, {stub} norme stub (citate ma non caricate).")

    driver.close()


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
