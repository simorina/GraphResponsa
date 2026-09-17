"""
19 - I commi lunghissimi spezzati in frammenti, ciascuno col suo vettore.

Un comma ha un solo embedding, calcolato da 07_embeddings.py sul testo intero.
Per il comma mediano (297 caratteri) va benissimo; per quelli che contengono
un allegato intero no, per due ragioni misurate il 17/09:

  - voyage-4 legge al massimo 32.000 token e la libreria taglia in silenzio
    (`truncation=True`): 43 commi in 40 atti li superano, e 2,3 milioni di
    token non erano rappresentati da nessun vettore. L'art. 8 del DD-19-2019
    (295.700 token) ha un vettore quasi identico a quello dei suoi primi
    100.000 caratteri;
  - anche sotto quel limite, un vettore solo per 300.000 caratteri e' una
    media che non somiglia a niente, e l'indice full-text penalizza i testi
    lunghi. Cercando "operatore specializzato amministrativo" o "OPSPAMMI",
    che stanno nei profili di ruolo del DD-165-2014 (un comma di 338.513
    caratteri), quel decreto non usciva.

Qui ogni comma oltre SOGLIA caratteri viene spezzato in frammenti di al piu'
PASSO caratteri, tagliati a fine frase o a fine riga, con una piccola
sovrapposizione perche' una disposizione a cavallo non si perda:

    (:Comma)-[:HA_FRAMMENTO]->(:Frammento {id, ordine, da, a, testo,
                                           improntaComma, embedding})

`da` e `a` sono posizioni nel testo del comma cosi' com'e' nel grafo: sono le
stesse che leggi_articolo(comma=..., da_carattere=...) usa per leggere il
passo. Il testo del frammento resta puro (serve all'indice full-text e a chi
legge); il vettore si calcola su titolo della norma, articolo e rubrica
seguiti dal frammento, perche' una riga di tabella da sola non dice di che
cosa parla.

Gli indici sono due, `frammenti_vettoriale` e `testo_frammenti`, e
cerca_testo li interroga accanto a quelli dei commi: un frammento trovato
restituisce il suo comma, con il passo al posto dell'inizio del testo.

E' idempotente. `improntaComma` e' l'impronta del testo del comma: se il comma
cambia (una migrazione, un ricaricamento) i suoi frammenti si rifanno; se
sparisce, o si accorcia sotto la soglia, si tolgono. Va rieseguito dopo
07_embeddings.py e dopo ogni script che tocca i commi (02/03, 13, 14, 15, 16).

Uso:
    .venv/Scripts/python.exe src/19_frammenti.py            # solo misura
    .venv/Scripts/python.exe src/19_frammenti.py --scrivi
"""

import hashlib
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

RADICE = Path(__file__).resolve().parent.parent
load_dotenv(RADICE / ".env")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
# Alla prima esecuzione etichetta e relazione non esistono ancora, e Neo4j
# lo segnala a ogni query.
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

MODELLO_EMBEDDING = "voyage-4"
DIMENSIONI = 1024
INDICE_VETTORIALE = "frammenti_vettoriale"
INDICE_TESTO = "testo_frammenti"

SOGLIA = 6000          # commi piu' lunghi si spezzano: 887 al 17/09
PASSO = 1700           # lunghezza di un frammento: con l'eventuale coda
                       # (CODA_MINIMA) resta sotto MAX_TESTO (2000) di
                       # strumenti.py, cosi' cerca_testo lo mostra intero
MINIMO = 1150          # non si cerca la fine frase prima di questo punto
SOVRAPPOSIZIONE = 200
CODA_MINIMA = 300      # un avanzo piu' corto si attacca al frammento prima
LOTTO = 64             # frammenti per richiesta a Voyage: ~40.000 token
SEPARATORI = (".\n", ";\n", "\n", ". ", "; ", ": ")


def spezza(testo):
    """Le coppie (da, a) dei frammenti di un testo.

    Si taglia all'ultimo separatore dopo MINIMO caratteri; in mancanza,
    all'ultimo spazio; in mancanza anche di quello, a PASSO netto. Il
    frammento successivo riparte SOVRAPPOSIZIONE caratteri prima, da un
    inizio di parola.
    """
    n = len(testo)
    pezzi, da = [], 0
    while da < n:
        a = min(n, da + PASSO)
        if n - a < CODA_MINIMA:
            a = n
        if a < n:
            finestra = testo[da + MINIMO:a]
            tagli = [finestra.rfind(s) + len(s) for s in SEPARATORI if finestra.rfind(s) >= 0]
            if tagli:
                a = da + MINIMO + max(tagli)
            else:
                spazio = testo.rfind(" ", da + MINIMO, a)
                if spazio > 0:
                    a = spazio + 1
        pezzi.append((da, a))
        if a >= n:
            break
        ripresa = a - SOVRAPPOSIZIONE
        spazio = testo.find(" ", ripresa, a)
        da = spazio + 1 if spazio >= 0 else ripresa
    return pezzi


def _prova():
    corto = "a" * 100
    assert spezza(corto) == [(0, 100)]
    frasi = ("Il dipendente ha diritto al congedo. " * 400)
    pezzi = spezza(frasi)
    assert pezzi[0][0] == 0 and pezzi[-1][1] == len(frasi)
    assert all(a - da <= PASSO for da, a in pezzi[:-1])
    assert all(a - da < 2000 for da, a in pezzi)
    assert all(frasi[a - 2:a] == ". " for _, a in pezzi[:-1])
    assert all(pezzi[i + 1][0] < pezzi[i][1] for i in range(len(pezzi) - 1))   # sovrapposti
    senza_spazi = "x" * 5000
    assert spezza(senza_spazi)[-1][1] == 5000
    # l'avanzo corto si attacca al frammento prima
    assert spezza("y " * 1000)[-1][1] == 2000


_prova()


def impronta(testo):
    return hashlib.md5((testo or "").encode("utf-8")).hexdigest()[:16]


Q_COMMI = """
MATCH (n:Norma)-[:HA_ARTICOLO]->(art:Articolo)-[:HA_COMMA]->(c:Comma)
WHERE size(c.testo) > $soglia
OPTIONAL MATCH (c)-[:HA_FRAMMENTO]->(f:Frammento)
WITH n, art, c, collect(f) AS fr
RETURN c.id AS id, c.testo AS testo, n.titolo AS titolo, art.numero AS articolo,
       art.rubrica AS rubrica,
       size(fr) AS frammenti,
       [x IN fr | x.improntaComma] AS impronte,
       all(x IN fr WHERE x.id STARTS WITH c.id + '#') AS idCoerenti,
       size([x IN fr WHERE x.embedding IS NULL]) AS senzaVettore
"""

Q_TOGLI_DI_COMMI = """
UNWIND $ids AS i
MATCH (:Comma {id: i})-[:HA_FRAMMENTO]->(f:Frammento)
DETACH DELETE f
"""

Q_ORFANI = """
MATCH (f:Frammento)
WHERE NOT EXISTS { MATCH (:Comma)-[:HA_FRAMMENTO]->(f) }
   OR EXISTS { MATCH (c:Comma)-[:HA_FRAMMENTO]->(f) WHERE size(c.testo) <= $soglia }
RETURN elementId(f) AS id
"""

Q_CREA = """
UNWIND $frammenti AS x
MATCH (c:Comma {id: x.comma})
CREATE (c)-[:HA_FRAMMENTO]->(:Frammento {
    id: x.id, ordine: x.ordine, da: x.da, a: x.a, testo: x.testo,
    improntaComma: x.impronta, testoVettore: x.testoVettore})
"""

Q_DA_VETTORIZZARE = """
MATCH (f:Frammento) WHERE f.embedding IS NULL
RETURN elementId(f) AS id, f.testoVettore AS testo
LIMIT $quanti
"""

Q_SALVA = """
UNWIND $coppie AS x
MATCH (f:Frammento) WHERE elementId(f) = x.id
SET f.embedding = x.vettore
REMOVE f.testoVettore
"""

INDICI = [
    "CREATE CONSTRAINT frammento_id IF NOT EXISTS FOR (f:Frammento) REQUIRE f.id IS UNIQUE",
    f"""CREATE VECTOR INDEX {INDICE_VETTORIALE} IF NOT EXISTS
        FOR (f:Frammento) ON (f.embedding)
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {DIMENSIONI},
            `vector.similarity_function`: 'cosine',
            `vector.quantization.type`: 'SCALAR'
        }}}}""",
    f"""CREATE FULLTEXT INDEX {INDICE_TESTO} IF NOT EXISTS
        FOR (f:Frammento) ON EACH [f.testo]
        OPTIONS {{indexConfig: {{`fulltext.analyzer`: 'italian'}}}}""",
]


def contesto(r):
    """Cio' che precede il frammento nel testo da vettorializzare."""
    rubrica = f" ({r['rubrica'].strip()})" if (r.get("rubrica") or "").strip() else ""
    return f"{r.get('titolo') or ''} - art. {r['articolo']}{rubrica}\n"


def vettorizza(s, client):
    fatti, inizio = 0, time.time()
    while True:
        lotto = s.run(Q_DA_VETTORIZZARE, quanti=LOTTO).data()
        if not lotto:
            return fatti
        for tentativo in range(6):
            try:
                vettori = client.embed([x["testo"] for x in lotto], model=MODELLO_EMBEDDING,
                                       input_type="document", truncation=True).embeddings
                break
            except Exception as e:
                attesa = 20 * (tentativo + 1)
                print(f"    Voyage: {type(e).__name__}: {str(e)[:120]} - riprovo fra {attesa}s")
                time.sleep(attesa)
        else:
            raise SystemExit("Voyage non risponde: rilancia piu' tardi, si riprende da qui.")
        s.run(Q_SALVA, coppie=[{"id": x["id"], "vettore": v} for x, v in zip(lotto, vettori)])
        fatti += len(lotto)
        if fatti % (LOTTO * 20) == 0:
            print(f"    {fatti} frammenti vettorializzati ({fatti / (time.time() - inizio):.1f}/s)")


def main():
    scrivi = "--scrivi" in sys.argv
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
                                  auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    with driver.session(database=db) as s:
        commi = s.run(Q_COMMI, soglia=SOGLIA).data()
        da_rifare, nuovi = [], []
        for r in commi:
            imp = impronta(r["testo"])
            aggiornati = (r["frammenti"] > 0 and r["idCoerenti"]
                          and all(x == imp for x in r["impronte"]))
            if aggiornati:
                continue
            if r["frammenti"]:
                da_rifare.append(r["id"])
            testa = contesto(r)
            for ordine, (da, a) in enumerate(spezza(r["testo"]), 1):
                pezzo = r["testo"][da:a]
                nuovi.append({"comma": r["id"], "id": f"{r['id']}#f{ordine}", "ordine": ordine,
                              "da": da, "a": a, "testo": pezzo, "impronta": imp,
                              "testoVettore": testa + " ".join(pezzo.split())})
        orfani = [x["id"] for x in s.run(Q_ORFANI, soglia=SOGLIA).data()]
        caratteri = sum(len(x["testoVettore"]) for x in nuovi)
        print(f"  commi oltre {SOGLIA} caratteri: {len(commi)}")
        print(f"  gia' spezzati e aggiornati: {len(commi) - len({x['comma'] for x in nuovi})}")
        print(f"  da spezzare: {len({x['comma'] for x in nuovi})} ({len(da_rifare)} da rifare) "
              f"-> {len(nuovi)} frammenti, ~{caratteri / 3.4 / 1e6:.1f} M token")
        print(f"  frammenti orfani o di commi ormai corti: {len(orfani)}")
        for x in nuovi[:3]:
            print(f"    {x['id']:<34} {x['da']:>7}-{x['a']:<7} {x['testo'][:70]!r}")
        if not scrivi:
            print("\n  Nulla scritto. Aggiungi --scrivi per applicare.")
            driver.close()
            return

        for q in INDICI[:1]:
            s.run(q)
        if orfani:
            s.run("UNWIND $ids AS i MATCH (f:Frammento) WHERE elementId(f) = i DETACH DELETE f", ids=orfani)
        for i in range(0, len(da_rifare), 500):
            s.run(Q_TOGLI_DI_COMMI, ids=da_rifare[i:i + 500])
        for i in range(0, len(nuovi), 500):
            s.run(Q_CREA, frammenti=nuovi[i:i + 500])
        print(f"  creati {len(nuovi)} frammenti")

        import voyageai
        client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
        fatti = vettorizza(s, client)
        print(f"  vettorializzati {fatti} frammenti")
        for q in INDICI[1:]:
            s.run(q)
        conto = s.run("""MATCH (f:Frammento) RETURN count(f) AS frammenti,
                         sum(CASE WHEN f.embedding IS NULL THEN 1 ELSE 0 END) AS senzaVettore""").single()
        print(f"  frammenti nel grafo: {conto['frammenti']}, senza vettore: {conto['senzaVettore']}")
    driver.close()


if __name__ == "__main__":
    main()
