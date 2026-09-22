"""Copia il grafo da Aura a Neo4j Community sull'istanza EC2.

Perche' una copia logica e non il file di Aura: Aura salva il database in
formato `block`, che esiste solo in Enterprise; Community legge soltanto
`aligned`, e il .backup esportato da Aura non si apre. La copia passa per
Cypher, quindi non dipende da formato ne' da versione, e Aura resta in
servizio mentre gira.

Si lancia sull'istanza (che legge Aura da internet e scrive su localhost):
    python3 neo4j-copia-da-aura.py            # copia tutto
    python3 neo4j-copia-da-aura.py --verifica # solo il confronto finale

Rilanciabile: i nodi entrano con MERGE su una chiave temporanea (l'elementId di
Aura, in `_eid` sotto l'etichetta `_Copia`), le relazioni di un tipo si
cancellano e si ricopiano per intero. Alla fine chiave ed etichetta
temporanee spariscono, e gli indici full-text e vettoriali si costruiscono a
dati fermi, una volta sola.
"""
import json
import subprocess
import sys
import time

from neo4j import GraphDatabase

REGIONE = "eu-central-1"
PAGINA = 1000          # nodi per pagina letta da Aura
LOTTO_VETTORI = 250    # nodi con embedding per transazione: ~2 MB di numeri
LOTTO = 2000           # nodi senza embedding, e relazioni, per transazione
# Etichette con vincolo di unicita' su `id`: si leggono a pagine ordinate
# sull'indice, in transazioni brevi. Le altre sono poche e si leggono intere.
CON_ID = ("Comma", "Articolo", "Frammento", "Norma")


def segreto(nome):
    uscita = subprocess.run(
        ["aws", "secretsmanager", "get-secret-value", "--region", REGIONE,
         "--secret-id", nome, "--query", "SecretString", "--output", "text"],
        capture_output=True, text=True, check=True).stdout
    return json.loads(uscita)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def etichette_cypher(etichette):
    return "".join(f":`{e.replace('`', '')}`" for e in etichette)


def schema(s_aura):
    vincoli = [r["createStatement"] for r in s_aura.run(
        "SHOW CONSTRAINTS YIELD createStatement RETURN createStatement")]
    indici = [dict(r) for r in s_aura.run(
        "SHOW INDEXES YIELD name, type, owningConstraint, createStatement, labelsOrTypes, properties, options "
        "WHERE type <> 'LOOKUP' AND owningConstraint IS NULL "
        "RETURN name, type, createStatement, labelsOrTypes, properties, options")]
    return vincoli, indici


def crea(s_dest, istruzione):
    """CREATE ... IF NOT EXISTS: rilanciare lo script non da' errore."""
    istr = istruzione
    for parola in ("CONSTRAINT", "INDEX"):
        # "CREATE VECTOR INDEX `nome` FOR" -> "... `nome` IF NOT EXISTS FOR"
        if " IF NOT EXISTS" not in istr and f"{parola} `" in istr:
            testa, coda = istr.split(" FOR ", 1)
            istr = f"{testa} IF NOT EXISTS FOR {coda}"
            break
    s_dest.run(istr).consume()


def copia_nodi(aura, dest, db_aura):
    with aura.session(database=db_aura) as s:
        gruppi = [(r["l"], r["c"]) for r in s.run(
            "MATCH (n) RETURN labels(n) AS l, count(*) AS c ORDER BY c DESC")]
    for etichette, quanti in gruppi:
        et = etichette_cypher(etichette)
        chiave = next((e for e in CON_ID if e in etichette), None)
        lotto = LOTTO_VETTORI if chiave in ("Comma", "Articolo", "Frammento") else LOTTO
        scrivi = (f"UNWIND $righe AS r MERGE (n:_Copia {{_eid: r.eid}}) "
                  f"SET n{et} SET n += r.p")
        filtro = f"MATCH (n{et}) WHERE size(labels(n)) = {len(etichette)}"
        log(f"nodi {etichette}: {quanti}")
        copiati = 0

        def svuota(righe):
            nonlocal copiati
            for i in range(0, len(righe), lotto):
                with dest.session(database="neo4j") as sd:
                    sd.execute_write(lambda tx, b=righe[i:i + lotto]: tx.run(scrivi, righe=b).consume())
            copiati += len(righe)

        if chiave is None:
            with aura.session(database=db_aura) as s:
                svuota([{"eid": r["eid"], "p": r["p"]} for r in s.run(
                    f"{filtro} RETURN elementId(n) AS eid, properties(n) AS p")])
        else:
            # Prima gli eventuali nodi senza id (non passano dal cursore), poi
            # a pagine sull'indice di `id`.
            with aura.session(database=db_aura) as s:
                svuota([{"eid": r["eid"], "p": r["p"]} for r in s.run(
                    f"{filtro} AND n.id IS NULL RETURN elementId(n) AS eid, properties(n) AS p")])
            ultimo = ""
            while True:
                with aura.session(database=db_aura) as s:
                    righe = [{"eid": r["eid"], "p": r["p"], "id": r["id"]} for r in s.run(
                        f"{filtro} AND n.id > $u RETURN elementId(n) AS eid, properties(n) AS p, n.id AS id "
                        f"ORDER BY n.id LIMIT {PAGINA}", u=ultimo)]
                if not righe:
                    break
                ultimo = righe[-1]["id"]
                svuota([{"eid": r["eid"], "p": r["p"]} for r in righe])
                if copiati % 20000 < PAGINA:
                    log(f"   {copiati}/{quanti}")
        log(f"   fatti {copiati}/{quanti}")


def copia_relazioni(aura, dest, db_aura):
    with aura.session(database=db_aura) as s:
        tipi = [(r["t"], r["c"]) for r in s.run(
            "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC")]
    for tipo, quanti in tipi:
        t = tipo.replace("`", "")
        log(f"relazioni {tipo}: {quanti}")
        # Tutto o niente per tipo: se una copia precedente si e' fermata a
        # meta', si ricomincia pulito invece di contare doppioni.
        with dest.session(database="neo4j") as sd:
            while sd.run(f"MATCH ()-[r:`{t}`]->() WITH r LIMIT 20000 DELETE r RETURN count(*) AS c").single()["c"]:
                pass
        scrivi = (f"UNWIND $righe AS r MATCH (a:_Copia {{_eid: r.a}}) MATCH (b:_Copia {{_eid: r.b}}) "
                  f"CREATE (a)-[x:`{t}`]->(b) SET x = r.p")
        righe = []
        with aura.session(database=db_aura, fetch_size=5000) as s:
            for r in s.run(f"MATCH (a)-[r:`{t}`]->(b) RETURN elementId(a) AS a, elementId(b) AS b, properties(r) AS p"):
                righe.append({"a": r["a"], "b": r["b"], "p": r["p"]})
        for i in range(0, len(righe), LOTTO):
            with dest.session(database="neo4j") as sd:
                sd.execute_write(lambda tx, b=righe[i:i + LOTTO]: tx.run(scrivi, righe=b).consume())
        log(f"   fatte {len(righe)}/{quanti}")


def pulisci(dest):
    log("tolgo chiave ed etichetta temporanee")
    with dest.session(database="neo4j") as sd:
        while sd.run("MATCH (n:_Copia) WITH n LIMIT 10000 REMOVE n:_Copia, n._eid RETURN count(*) AS c").single()["c"]:
            pass
        sd.run("DROP INDEX copia_eid IF EXISTS").consume()


def conta(sessione):
    etichette = {r["l"]: r["c"] for r in sessione.run(
        "MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS c")}
    tipi = {r["t"]: r["c"] for r in sessione.run(
        "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")}
    return etichette, tipi


def verifica(aura, dest, db_aura):
    log("VERIFICA")
    esito = True
    with aura.session(database=db_aura) as sa, dest.session(database="neo4j") as sd:
        ea, ta = conta(sa)
        ed, td = conta(sd)
        for nome, a, d in (("etichetta", ea, ed), ("relazione", ta, td)):
            for k in sorted(set(a) | set(d)):
                ok = a.get(k) == d.get(k)
                esito &= ok
                if not ok or nome == "relazione":
                    log(f"   {nome} {k}: Aura {a.get(k)} / EC2 {d.get(k)} {'ok' if ok else 'DIVERSO'}")
        na = sa.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        nd = sd.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        esito &= na == nd
        log(f"   nodi totali: Aura {na} / EC2 {nd}")

        for r in sd.run("SHOW INDEXES YIELD name, type, state, populationPercent "
                        "RETURN name, type, state, populationPercent ORDER BY name"):
            ok = r["state"] == "ONLINE"
            esito &= ok
            log(f"   indice {r['name']:24} {r['type']:9} {r['state']} {r['populationPercent']}%")

        # Campione: testo ed embedding identici su commi presi a caso.
        campione = [r["id"] for r in sa.run(
            "MATCH (c:Comma) WHERE c.embedding IS NOT NULL WITH c, rand() AS x ORDER BY x LIMIT 25 RETURN c.id AS id")]
        diversi = 0
        for i in campione:
            a = sa.run("MATCH (c:Comma {id:$i}) RETURN c.testo AS t, c.embedding AS e", i=i).single()
            d = sd.run("MATCH (c:Comma {id:$i}) RETURN c.testo AS t, c.embedding AS e", i=i).single()
            if d is None or a["t"] != d["t"] or list(a["e"]) != list(d["e"]):
                diversi += 1
        esito &= diversi == 0
        log(f"   campione di 25 commi: {25 - diversi} identici, {diversi} diversi")

        # Stessa ricerca vettoriale da tutte e due le parti: stessi primi 10?
        vettore = sa.run("MATCH (c:Comma) WHERE c.embedding IS NOT NULL RETURN c.embedding AS e LIMIT 1").single()["e"]
        q = ("CALL db.index.vector.queryNodes('commi_vettoriale', 10, $v) YIELD node, score "
             "RETURN node.id AS id")
        pa = [r["id"] for r in sa.run(q, v=vettore)]
        pd = [r["id"] for r in sd.run(q, v=vettore)]
        comuni = len(set(pa) & set(pd))
        log(f"   ricerca vettoriale, primi 10: {comuni}/10 in comune")
        esito &= comuni >= 9     # HNSW e' approssimato: uno scambio in coda e' fisiologico
    log("VERIFICA RIUSCITA" if esito else "VERIFICA: CI SONO DIFFERENZE")
    return esito


def main():
    aura_c = segreto("graphresponsa/aura-migrazione")
    dest_c = segreto("graphresponsa/neo4j")
    db_aura = aura_c.get("NEO4J_DATABASE") or "neo4j"
    aura = GraphDatabase.driver(aura_c["NEO4J_URI"], auth=(aura_c["NEO4J_USERNAME"], aura_c["NEO4J_PASSWORD"]))
    dest = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", dest_c["NEO4J_PASSWORD"]))
    aura.verify_connectivity()
    dest.verify_connectivity()
    log("connesso ad Aura e all'istanza")

    if "--verifica" in sys.argv:
        sys.exit(0 if verifica(aura, dest, db_aura) else 1)

    with aura.session(database=db_aura) as sa:
        vincoli, indici = schema(sa)
    with dest.session(database="neo4j") as sd:
        presenti = sd.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        in_copia = sd.run("MATCH (n:_Copia) RETURN count(n) AS c").single()["c"]
    copia_finita = presenti > 0 and in_copia == 0
    if copia_finita:
        log(f"i dati ci sono gia' ({presenti} nodi, copia pulita): passo a indici e verifica")
    with dest.session(database="neo4j") as sd:
        for v in vincoli:
            crea(sd, v)
        sd.run("CREATE INDEX copia_eid IF NOT EXISTS FOR (n:_Copia) ON (n._eid)").consume()
        sd.run("CALL db.awaitIndexes(600)").consume()
    log(f"schema: {len(vincoli)} vincoli creati; indici full-text e vettoriali dopo i dati")

    inizio = time.time()
    if not copia_finita:
        copia_nodi(aura, dest, db_aura)
        copia_relazioni(aura, dest, db_aura)
        pulisci(dest)

    with dest.session(database="neo4j") as sd:
        for ind in indici:
            log(f"creo l'indice {ind['name']} ({ind['type']})")
            try:
                crea(sd, ind["createStatement"])
            except Exception as e:
                if ind["type"] != "VECTOR":
                    raise
                # Aura 5.27 puo' scrivere opzioni che la 5.26 non conosce: si
                # ripiega sulle due che contano, dimensioni e similarita'.
                conf = ind["options"]["indexConfig"]
                log(f"   opzioni di Aura non accettate ({type(e).__name__}): ripiego sulle essenziali")
                sd.run(f"CREATE VECTOR INDEX `{ind['name']}` IF NOT EXISTS "
                       f"FOR (n:`{ind['labelsOrTypes'][0]}`) ON (n.`{ind['properties'][0]}`) "
                       "OPTIONS {indexConfig: {`vector.dimensions`: $d, `vector.similarity_function`: $f}}",
                       d=conf["vector.dimensions"], f=conf["vector.similarity_function"]).consume()
        log("attendo che gli indici siano pronti (i vettoriali richiedono qualche minuto)")
        sd.run("CALL db.awaitIndexes(7200)").consume()
    log(f"copia finita in {(time.time() - inizio) / 60:.1f} minuti")
    ok = verifica(aura, dest, db_aura)
    aura.close()
    dest.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
