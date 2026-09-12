"""
Gli strumenti che l'agente puo' usare sul grafo, come tool LangChain.

Scelta di fondo: strumenti tipizzati, non Cypher generato dal modello.
`langchain-neo4j` offre GraphCypherQAChain, che traduce la domanda in Cypher -
ma richiede allow_dangerous_requests=True e su materia giuridica una query
sbagliata non produce un errore: produce una risposta plausibile e falsa.
Qui le query sono scritte e verificate una volta sola; il modello puo' solo
comporle.

La connessione passa da Neo4jGraph, il wrapper dell'integrazione ufficiale.

La docstring di ogni funzione diventa la descrizione che il modello legge per
decidere se usarla: e' documentazione operativa, non commento.
"""

import hashlib
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_neo4j import Neo4jGraph

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

# Un comma puo' essere lunghissimo: negli elenchi si tronca per non saturare il
# contesto, ma l'agente ha sempre leggi_articolo() per il testo integrale.
#
# A 1200 caratteri si tagliava il 6,5% dei commi; a 2000 si scende al 2,6%, e
# il costo in contesto resta modesto perche' i risultati sono otto. Cio' che
# resta tagliato viene ora dichiarato con `troncato: true`: prima il modello
# vedeva un testo mutilo senza sapere che mancava qualcosa, e non aveva motivo
# di chiamare leggi_articolo().
MAX_TESTO = 2000

_grafo = None


# Aura avverte che db.index.vector.queryNodes e' deprecata a ogni singola
# ricerca. La chiamata la fa LangChain, non noi, e non possiamo cambiarla:
# ottanta righe di avviso identico per ogni domanda seppellivano i log veri.
# Si spegne il logger e non il driver, perche' la notifica esce anche dalla
# connessione separata del vector store, che non passa da grafo().
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)


def grafo() -> Neo4jGraph:
    """Connessione condivisa, aperta alla prima richiesta."""
    global _grafo
    if _grafo is None:
        _grafo = Neo4jGraph(
            url=os.environ["NEO4J_URI"],
            username=os.environ["NEO4J_USERNAME"],
            password=os.environ["NEO4J_PASSWORD"],
            database=os.environ.get("NEO4J_DATABASE", "neo4j"),
            # Lo schema non serve: non generiamo Cypher dal modello, e
            # ricavarlo a ogni avvio costa un giro di query inutile.
            refresh_schema=False,
        )
    return _grafo


def _taglia(testo, limite=MAX_TESTO):
    testo = (testo or "").strip()
    return testo if len(testo) <= limite else testo[:limite] + " [...]"


def _lucene(query):
    """Neutralizza la sintassi Lucene: la query e' italiano, non un'espressione.

    `db.index.fulltext.queryNodes` passa la stringa al parser di Lucene, che su
    una parentesi non bilanciata solleva un errore invece di cercare. Misurato:
    "art. 47 lettera a) b) c) sosta" faceva fallire la consultazione, e l'agente
    scrive query cosi' ogni volta che riformula citando un elenco di lettere.
    Colpisce anche l'utente che digita "art. 47 (comma 2)".

    Si sfugge ogni carattere speciale perche' qui nessuno vuole davvero gli
    operatori: chi cerca "AND" intende la parola, non la congiunzione booleana.
    """
    speciali = set('+-&|!(){}[]^"~*?:' + '\\' + '/')
    fuori = "".join('\\' + c if c in speciali else c for c in (query or ""))
    return fuori.strip() or '""'


def _firma(testo):
    """Impronta del testo, per riconoscere i passi identici.

    Lo stesso comma ricorre in archivio sotto piu' atti: un decreto che ne
    ripubblica un altro, una versione consolidata accanto all'originale, un
    id qualificato per collisione. Sono atti distinti e vanno tenuti distinti,
    ma mostrarne il testo due volte consuma i posti utili senza aggiungere
    nulla: misurato su dieci domande poste in lingua corrente, il 21% dei
    risultati era una ripetizione, e su una domanda 5 posti su 8.
    """
    return hashlib.md5(re.sub(r"\W+", "", (testo or "").lower())[:300].encode()).hexdigest()


def _troncato(testo, limite=MAX_TESTO):
    return len((testo or "").strip()) > limite


# --------------------------------------------------------------- strumenti

# --------------------------------------------------------------- ricerca ibrida

INDICE_VETTORIALE = "commi_vettoriale"
INDICE_KEYWORD = "testo_normativo"
MODELLO_EMBEDDING = "voyage-4"

# La retrieval_query gira DOPO il match vettoriale, con `node` e `score` gia'
# disponibili: e' il punto in cui si risale il grafo. Ricerca semantica e
# navigazione delle relazioni diventano cosi' una query sola.
RISALITA = """
// L'indice full-text copre Comma E Articolo, rubriche comprese. La versione
// precedente pretendeva (art)-[:HA_COMMA]->(node): un Articolo agganciato per
// la sua rubrica produceva zero righe e spariva senza errore, proprio mentre
// l'indice lo aveva trovato per primo. La rubrica e' la riga piu' densa di
// senso di un articolo - "(Incompatibilita' con altre cariche)" - e perderla
// era il difetto piu' costoso del recupero.
OPTIONAL MATCH (padre:Articolo)-[:HA_COMMA]->(node)
WITH node, score,
     coalesce(padre, CASE WHEN node:Articolo THEN node END) AS art
WHERE art IS NOT NULL
MATCH (norma:Norma)-[:HA_ARTICOLO]->(art)
RETURN node.testo AS text, score,
       {normaId: norma.id, normaTitolo: norma.titolo,
        anno: norma.anno,
        inVigoreDal: toString(norma.dataEntrataVigore),
        dataAtto: toString(norma.data),
        articolo: art.numero, rubrica: art.rubrica,
        partizioneTitolo: art.titolo, partizioneCapo: art.capoRubrica,
        comma: CASE WHEN node:Comma THEN node.numero ELSE null END} AS metadata
"""

_vettoriale = "non_provato"   # None = non disponibile, altrimenti lo store


def ricerca_vettoriale():
    """Il vector store ibrido, se gli embedding sono stati calcolati.

    Restituisce None finche' 07_embeddings.py non e' stato eseguito: cosi' la
    ricerca continua a funzionare in sola modalita' full-text.
    """
    global _vettoriale
    if _vettoriale != "non_provato":
        return _vettoriale
    try:
        from langchain_neo4j import Neo4jVector
        from langchain_voyageai import VoyageAIEmbeddings
        _vettoriale = Neo4jVector.from_existing_index(
            embedding=VoyageAIEmbeddings(
                model=MODELLO_EMBEDDING,
                api_key=os.environ["VOYAGE_API_KEY"],
            ),
            url=os.environ["NEO4J_URI"],
            username=os.environ["NEO4J_USERNAME"],
            password=os.environ["NEO4J_PASSWORD"],
            database=os.environ.get("NEO4J_DATABASE", "neo4j"),
            index_name=INDICE_VETTORIALE,
            # NON "hybrid": la fusione dell'integrazione normalizza ogni ramo
            # sul proprio massimo e poi prende il maggiore, cosi' il primo
            # risultato lessicale vale SEMPRE 1.000 e pareggia col primo
            # vettoriale, spazzatura compresa. Misurato: su "quanto costa
            # spedire una raccomandata" il ramo lessicale portava in cima la
            # convocazione di un consiglio d'amministrazione (aggancio su
            # "spedire") mentre quello semantico trovava il "Diritto di
            # raccomandazione" del D-37/1947. Qui si prende la sola semantica
            # e si fonde a valle con _fondi(), a ranghi reciproci.
            search_type="vector",
            retrieval_query=RISALITA,
        )
    except Exception:
        _vettoriale = None    # indice assente o chiave mancante
    return _vettoriale


def _full_text(query, limite, dal_anno=None):
    """Ricerca lessicale: la riserva quando il vettoriale non e' disponibile."""
    righe = grafo().query("""
        CALL db.index.fulltext.queryNodes('testo_normativo', $query)
        YIELD node, score
        // Anche qui l'articolo agganciato per la rubrica va tenuto, non scartato.
        OPTIONAL MATCH (padre:Articolo)-[:HA_COMMA]->(node)
        WITH node, score,
             coalesce(padre, CASE WHEN node:Articolo THEN node END) AS art
        WHERE art IS NOT NULL
        MATCH (norma:Norma)-[:HA_ARTICOLO]->(art)
        // Stessa guardia: il ramo lessicale puo' agganciare quelle
        // intestazioni per la loro rubrica.
        WHERE node.testo IS NOT NULL AND trim(node.testo) <> ''
          AND ($dal_anno IS NULL OR norma.anno >= $dal_anno)
        RETURN norma.id AS normaId, norma.titolo AS normaTitolo,
               norma.anno AS anno,
               toString(norma.dataEntrataVigore) AS inVigoreDal,
               toString(norma.data) AS dataAtto,
               art.numero AS articolo, art.rubrica AS rubrica,
               art.titolo AS partizioneTitolo, art.capoRubrica AS partizioneCapo,
               CASE WHEN node:Comma THEN node.numero ELSE null END AS comma,
               node.testo AS testo, norma.urlDocumento AS urlDocumento
        ORDER BY score DESC, norma.anno DESC LIMIT $ampio
    """, {"query": _lucene(query), "limite": limite, "ampio": limite * 3,
          "dal_anno": dal_anno})

    # Stessa potatura dei doppioni del ramo ibrido: due rami, una semantica.
    tenute, viste = [], {}
    for r in righe:
        impronta = _firma(r["testo"])
        if impronta in viste:
            gia = viste[impronta]
            if r["normaId"] != gia["normaId"] and r["normaId"] not in gia.get("ancheIn", []):
                gia.setdefault("ancheIn", []).append(r["normaId"])
            continue
        viste[impronta] = r
        tenute.append(r)
        if len(tenute) >= limite:
            break
    for i, r in enumerate(tenute, 1):
        r["rango"] = i
        r["troncato"] = _troncato(r["testo"])
        r["testo"] = _taglia(r["testo"])
    return tenute


# Fusione a ranghi reciproci: punteggio = peso / (K + rango), sommato sui rami.
#
# I due parametri sono tarati, non scelti, e la taratura e' stata rifatta dopo
# aver vettorializzato le rubriche degli articoli (07b_embeddings_rubriche.py).
# Misurando il rango reciproco medio su tre famiglie di prove - domande in
# lingua corrente, trappole lessicali su parole comuni, ricerca per rubrica:
#
#     peso   colloquiali  trappole  rubriche   media
#     0.00       1.000      0.750     0.312    0.688   <- solo semantico
#     0.30       1.000      0.750     0.542    0.764
#     0.50       1.000      0.750     0.875    0.875
#     0.75       1.000      0.750     1.000    0.917   <- scelto
#     1.00       0.900      0.667     1.000    0.856
#
# Prima che gli articoli avessero un embedding il peso ottimale era 1.5, e
# c'era un compromesso obbligato: alzandolo si trovavano le rubriche ma
# tornavano le trappole, e viceversa. Vettorializzare le rubriche ha tolto il
# compromesso - ora 1.000 su entrambe insieme - e ha dimezzato il peso che
# serve al ramo lessicale.
#
# Il lessicale resta comunque acceso: a peso zero le rubriche scendono da
# 1.000 a 0.312, perche' l'embedding di una rubrica coglie il senso ma non la
# corrispondenza letterale, ed e' letteralmente che si cerca un articolo di
# cui si conosce il nome.
# Quanti candidati pescare per ramo, in multipli di `limite`. Piu' e' largo,
# piu' e' probabile che il passo giusto sia nel bacino - il riordino e la
# fusione possono solo ordinare cio' che ricevono, non ripescare cio' che
# manca - ma oltre un certo punto si aggiunge solo rumore.
AMPIEZZA = 3
K_RRF = 20
PESO_SEMANTICO = 1.0
PESO_LESSICALE = 0.75


# Due indici vettoriali, non uno. `commi_vettoriale` sta su Comma.embedding,
# `rubriche_vettoriale` su Articolo.embedding: un articolo non ha un embedding
# dei suoi commi, ha quello della propria rubrica, preceduta dal titolo della
# norma (vedi 07b_embeddings_rubriche.py). Senza il secondo, cercare per
# rubrica - come cerca un giurista - era possibile solo dal ramo lessicale.
INDICE_RUBRICHE = "rubriche_vettoriale"

RISALITA_COMMI = """
CALL db.index.vector.queryNodes($indice, $k, $vettore) YIELD node, score
MATCH (art:Articolo)-[:HA_COMMA]->(node)
MATCH (norma:Norma)-[:HA_ARTICOLO]->(art)
// Un nodo senza testo non e' un risultato. 28 :Articolo esistono come sola
// intestazione: negli Allegati dei decreti sulle violazioni amministrative
// compaiono righe come "Art. 50 (Alterazione di marche)" che rimandano a un
// altro atto e non hanno un corpo. Uscivano fra i risultati col testo vuoto,
// misurato al secondo posto cercando la loro stessa rubrica.
WHERE node.testo IS NOT NULL AND trim(node.testo) <> ''
  AND ($dal_anno IS NULL OR norma.anno >= $dal_anno)
RETURN norma.id AS normaId, norma.titolo AS normaTitolo, norma.anno AS anno,
       toString(norma.dataEntrataVigore) AS inVigoreDal,
       toString(norma.data) AS dataAtto,
       art.numero AS articolo, art.rubrica AS rubrica,
       art.titolo AS partizioneTitolo, art.capoRubrica AS partizioneCapo,
       node.numero AS comma, node.testo AS testo,
       norma.urlDocumento AS urlDocumento,
       norma.abrogata AS abrogata, norma.abrogataDa AS abrogataDa,
       coalesce(node.abrogato, art.abrogato) AS passoAbrogato,
       coalesce(node.abrogatoDa, art.abrogatoDa) AS passoAbrogatoDa
ORDER BY score DESC
"""

RISALITA_RUBRICHE = """
CALL db.index.vector.queryNodes($indice, $k, $vettore) YIELD node AS art, score
MATCH (norma:Norma)-[:HA_ARTICOLO]->(art)
// Un nodo senza testo non e' un risultato. 28 :Articolo esistono come sola
// intestazione: negli Allegati dei decreti sulle violazioni amministrative
// compaiono righe come "Art. 50 (Alterazione di marche)" che rimandano a un
// altro atto e non hanno un corpo. Uscivano fra i risultati col testo vuoto,
// misurato al secondo posto cercando la loro stessa rubrica.
WHERE art.testo IS NOT NULL AND trim(art.testo) <> ''
  AND ($dal_anno IS NULL OR norma.anno >= $dal_anno)
RETURN norma.id AS normaId, norma.titolo AS normaTitolo, norma.anno AS anno,
       toString(norma.dataEntrataVigore) AS inVigoreDal,
       toString(norma.data) AS dataAtto,
       art.numero AS articolo, art.rubrica AS rubrica,
       art.titolo AS partizioneTitolo, art.capoRubrica AS partizioneCapo,
       null AS comma, art.testo AS testo,
       norma.urlDocumento AS urlDocumento,
       norma.abrogata AS abrogata, norma.abrogataDa AS abrogataDa,
       art.abrogato AS passoAbrogato, art.abrogatoDa AS passoAbrogatoDa
ORDER BY score DESC
"""


def _vettore_domanda(query):
    """La domanda in 1024 numeri. None se gli embedding non sono disponibili.

    Si vettorializza UNA volta sola e si interrogano entrambi gli indici con lo
    stesso vettore: passando dallo store di LangChain, che vettorializza da se'
    a ogni ricerca, si pagherebbe Voyage due volte per la stessa domanda.
    """
    store = ricerca_vettoriale()
    if store is None:
        return None
    try:
        return store.embedding.embed_query(query)
    except Exception:
        return None


def _semantico(query, limite, dal_anno=None):
    """I due indici vettoriali fusi in una lista sola. None se non disponibili."""
    vettore = _vettore_domanda(query)
    if vettore is None:
        return None
    liste = []
    for indice, risalita in ((INDICE_VETTORIALE, RISALITA_COMMI),
                             (INDICE_RUBRICHE, RISALITA_RUBRICHE)):
        try:
            liste.append(grafo().query(risalita, {
                "indice": indice, "k": limite, "vettore": vettore,
                "dal_anno": dal_anno}))
        except Exception:
            # L'indice delle rubriche puo' non esserci ancora: si prosegue con
            # quello dei commi invece di far fallire tutta la ricerca.
            continue
    if not liste:
        return None
    # I commi pesano piu' delle rubriche: una rubrica dice di cosa tratta
    # l'articolo, un comma contiene la disposizione. Ma una rubrica centrata
    # vale piu' di un comma alla lontana, quindi non si azzera.
    return _fondi([(liste[0], 1.0)] + [(l, 0.7) for l in liste[1:]],
                  limite, taglia=False)


MODELLO_RERANK = "rerank-2.5"
RERANK = os.environ.get("RERANK", "").lower() in ("1", "si", "true")
_riordinatore = "non_provato"


def _rerank(query, righe, limite):
    """Riordina i candidati con un cross-encoder, che legge domanda e testo insieme.

    Il bi-encoder confronta due vettori calcolati separatamente; il cross-encoder
    guarda la coppia, quindi coglie sfumature che la distanza fra vettori perde.
    Puo' solo riordinare cio' che riceve: se il passo giusto non e' fra i
    candidati, nessun riordino lo fa comparire.

    La rubrica entra nel testo dato al riordinatore: e' la riga piu' densa di
    senso dell'articolo, e senza di essa il modello non vedrebbe proprio il
    dato su cui si gioca la corrispondenza letterale.
    """
    global _riordinatore
    if _riordinatore == "non_provato":
        try:
            import voyageai
            _riordinatore = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
        except Exception:
            _riordinatore = None
    if _riordinatore is None or not righe:
        return righe[:limite]
    documenti = [((r.get("rubrica") or "") + " " + (r.get("testo") or ""))[:2000]
                 for r in righe]
    try:
        esito = _riordinatore.rerank(query=query, documents=documenti,
                                     model=MODELLO_RERANK, top_k=limite)
    except Exception:
        return righe[:limite]
    return [righe[x.index] for x in esito.results]


# Le formule con cui un atto riscrive un altro: "e' cosi' sostituito", "sono
# abrogati", "e' aggiunto il seguente articolo". Distinguono la novella vera
# dal semplice rimando - "i soggetti in possesso dei requisiti di cui
# all'articolo 3" cita l'articolo senza toccarlo - e l'apostrofo va in una
# classe di caratteri perche' gli atti usano ' e ’ indifferentemente.
#
# NON si usa \b davanti a "è": in Java - il motore che sta dietro a `=~` di
# Cypher - \w e' ASCII, quindi fra uno spazio e una vocale accentata NON c'e'
# confine di parola e l'espressione non agganciava mai nulla. Misurato: "e'
# cosi' sostituito" dava riscrive=false. Il confine si scrive a mano.
RISCRITTURA = (r"(?is).*(?:^|[\s,;:.(«\"])(?:è|e['’]|sono|viene|vengono)\s+"
               r"(?:cos[ìi]['’]?\s+)?"
               r"(?:sostituit|modificat|abrogat|aggiunt|inserit|soppress)\w*.*")


def _novelle(righe):
    """Annota quali risultati sono citati da atti SUCCESSIVI.

    Il grafo tiene archi CITA_ARTICOLO fra il comma che cita e l'articolo
    citato. Quando una legge del 2025 dice "il comma 1 dell'articolo 6 della
    Legge 171/2022 e' cosi' modificato", quell'arco esiste: e' il segnale
    deterministico che l'articolo e' stato toccato dopo.

    Serve perche' accorgersene leggendo non e' affidabile. Misurato sulla stessa
    domanda posta due volte: una volta l'agente ha trovato la novella del 2025 e
    ha risposto con la disciplina vigente, l'altra ha citato la versione del
    2022 - 35 anni invece di 40, scadenza 2025 invece di 2026 - pur avendo la
    novella al terzo posto fra i risultati che aveva sotto gli occhi.

    Si calcola sui soli risultati finali, non sui candidati: una query sola.
    """
    chiavi = [{"n": r["normaId"], "a": str(r.get("articolo"))}
              for r in righe if r.get("normaId") and r.get("articolo")]
    if not chiavi:
        return righe
    try:
        trovate = grafo().query("""
            UNWIND $chiavi AS k
            MATCH (n:Norma {id: k.n})-[:HA_ARTICOLO]->(a:Articolo {numero: k.a})
            MATCH (c:Comma)-[:CITA_ARTICOLO]->(a)
            MATCH (dopo:Norma)-[:HA_ARTICOLO]->(artDopo:Articolo)-[:HA_COMMA]->(c)
            WHERE dopo.anno > n.anno
            // Un comma che RISCRIVE la disposizione vale piu' di uno che la
            // richiama di passaggio, e va detto al modello.
            WITH k, dopo, artDopo, c,
                 CASE WHEN c.testo =~ $riscrittura THEN true ELSE false END AS riscrive
            ORDER BY riscrive DESC
            // Un comma per ATTO, non i primi due commi in assoluto: un atto
            // recente con due rimandi si prendeva tutti i posti e l'atto che
            // l'articolo lo aveva riscritto restava fuori. Misurato sull'art.
            // 3 della L-44/2015: comparivano due commi della L-87/2026 che vi
            // rimandano, e non la L-64/2025 che ne ha sostituito le lettere.
            WITH k, dopo, collect({norma: dopo.id, anno: dopo.anno,
                                   articolo: artDopo.numero, comma: c.numero,
                                   testo: c.testo, riscrive: riscrive})[0] AS voce
            ORDER BY voce.riscrive DESC, voce.anno DESC
            WITH k, collect(voce)[..3] AS novelle
            RETURN k.n AS norma, k.a AS articolo, novelle
        """, {"chiavi": chiavi, "riscrittura": RISCRITTURA})
    except Exception:
        return righe
    mappa = {(t["norma"], t["articolo"]): t["novelle"] for t in trovate}
    for r in righe:
        novelle = mappa.get((r.get("normaId"), str(r.get("articolo"))))
        if novelle:
            # Il TESTO della novella, non solo il suo identificativo. Chiedere
            # al modello di andarselo a leggere non funziona in modo affidabile:
            # misurato sulla stessa domanda, a volte apriva l'atto successivo e
            # a volte citava il testo scaduto pur avendone il riferimento
            # davanti. Se il testo nuovo arriva insieme, non c'e' piu' un passo
            # da ricordarsi di fare.
            r["citatoDaAttiSuccessivi"] = [
                {**n, "testo": _taglia(n["testo"], 900)} for n in novelle]
    return righe


def _bersagli_abrogati(righe):
    """Annota i risultati che introducono o modificano un passo ABROGATO.

    Un atto che inserisce un articolo in un codice ne riporta il testo per
    intero: la L-101/2003 contiene tutto l'art. 282-bis del Codice Penale. La
    ricerca lo trova li', e da li' il testo si legge intero e sensato - ma
    quell'articolo e' stato abrogato dalla L-59/2025, e la marcatura sta sul
    nodo del Codice, non su quello dell'atto che lo introdusse.

    Misurato sul caso reale: alla domanda "il maltrattamento di animali e'
    ancora punito dall'art. 282-bis?" l'agente rispondeva di si', leggendo
    l'atto del 2003 e senza mai aprire l'articolo del Codice.

    L'arco CITA_ARTICOLO che collega i due esiste gia'. Si segue e si guarda
    se il bersaglio e' marcato: e' un segnale POSITIVO come tutti gli altri di
    vigenza - la sua presenza autorizza a dire "abrogato", la sua assenza non
    autorizza a dire "vigente".
    """
    chiavi = [{"n": r["normaId"], "a": str(r.get("articolo"))}
              for r in righe if r.get("normaId") and r.get("articolo")]
    if not chiavi:
        return righe
    try:
        trovate = grafo().query("""
            UNWIND $chiavi AS k
            MATCH (n:Norma {id: k.n})-[:HA_ARTICOLO]->(a:Articolo {numero: k.a})
            MATCH (a)-[:HA_COMMA]->(:Comma)-[:CITA_ARTICOLO]->(b:Articolo)
            WHERE b.abrogato
            MATCH (bn:Norma)-[:HA_ARTICOLO]->(b)
            WITH k, collect(DISTINCT {norma: bn.id, titolo: bn.titolo,
                                      articolo: b.numero,
                                      abrogatoDa: b.abrogatoDa})[..3] AS caduti
            RETURN k.n AS norma, k.a AS articolo, caduti
        """, {"chiavi": chiavi})
    except Exception:
        return righe
    mappa = {(t["norma"], t["articolo"]): t["caduti"] for t in trovate}
    for r in righe:
        caduti = mappa.get((r.get("normaId"), str(r.get("articolo"))))
        if caduti:
            r["passiIntrodottiOraAbrogati"] = caduti
    return righe


def _piu_recenti(righe):
    """Marca i risultati che hanno un omologo piu' recente nella stessa lista.

    Il criterio e' la rubrica identica. Due atti con la stessa rubrica -
    "Disposizioni in materia di imposte per la prima casa" in L-158-2025 e in
    DD-52-2026 - sono quasi sempre la stessa disposizione riscritta, e quello
    con l'anno maggiore e' la versione da esporre.

    Serve dove gli archi non arrivano. _novelle() segue CITA_ARTICOLO, ma quei
    due commi non ce l'hanno: modificano entrambi una TABELLA della L. 85/1981,
    e il parser crea gli archi verso gli articoli, non verso le tabelle. Il
    risultato e' che due novelle parallele allo stesso bersaglio si ignorano.
    Misurato sul caso reale: l'agente citava la versione 2025 senza accorgersi
    che il 2026 la riscriveva.

    Non costa nulla: si confrontano le righe gia' in mano, senza interrogare.
    """
    gruppi = {}
    for r in righe:
        chiave = " ".join((r.get("rubrica") or "").lower().split())
        if len(chiave) > 12:          # le rubriche corte ("Definizioni",
            gruppi.setdefault(chiave, []).append(r)   # "Sanzioni") coincidono
                                                      # per caso, non per parentela
    for gruppo in gruppi.values():
        if len(gruppo) < 2:
            continue
        recente = max(gruppo, key=lambda r: r.get("anno") or 0)
        for r in gruppo:
            if r is not recente and (r.get("anno") or 0) < (recente.get("anno") or 0):
                # Il testo, non solo il rimando: col solo riferimento il
                # modello riconosceva la catena ma non la percorreva fino in
                # fondo. Il testo e' gia' in mano - quel risultato sta nella
                # stessa lista - quindi allegarlo non costa una query.
                r["versionePiuRecente"] = {
                    "norma": recente.get("normaId"), "anno": recente.get("anno"),
                    "articolo": recente.get("articolo"),
                    "comma": recente.get("comma"),
                    "testo": _taglia(recente.get("testo"), 900),
                }
    return righe


def _fondi(liste, limite, taglia=True):
    """Unisce piu' liste ordinate col metodo dei ranghi reciproci.

    Ogni risultato vale `peso / (K + rango)` in ciascuna lista dove compare, e
    i contributi si sommano. Cosi' nessun ramo puo' imporre il primo posto da
    solo - e' la comparsa in entrambi a spingere davvero un passo in cima, che
    e' il vero segnale di pertinenza. Sostituisce la fusione precedente, che
    normalizzava ogni ramo sul proprio massimo e prendeva il maggiore: li' il
    primo lessicale valeva sempre 1.000 anche quando era fuori tema.
    """
    punti, primo = {}, {}
    for righe, peso in liste:
        for rango, r in enumerate(righe, 1):
            impronta = _firma(r["testo"])
            punti[impronta] = punti.get(impronta, 0.0) + peso / (K_RRF + rango)
            if impronta not in primo:
                primo[impronta] = dict(r)
            else:
                # Stesso testo sotto un altro atto: si annota dove ricorre,
                # invece di spendere un posto utile per ripeterlo.
                gia = primo[impronta]
                altro = r.get("normaId")
                if altro and altro != gia["normaId"] and altro not in gia.get("ancheIn", []):
                    gia.setdefault("ancheIn", []).append(altro)

    ordinate = sorted(punti, key=lambda f: punti[f], reverse=True)[:limite]
    finali = []
    for i, impronta in enumerate(ordinate, 1):
        r = primo[impronta]
        r["rango"] = i
        if taglia:
            r["troncato"] = _troncato(r["testo"])
            r["testo"] = _taglia(r["testo"])
        finali.append(r)
    return finali


@tool
def cerca_testo(query: str, limite: int = 8, dal_anno: int | None = None) -> dict:
    """Cerca nel testo della normativa in archivio.

    E' lo strumento da usare per primo su qualunque domanda di merito
    ("cosa prevede la legge su X"). Restituisce i passi piu' pertinenti, ognuno
    gia' corredato di norma, articolo, rubrica e collocazione nel testo.

    La ricerca e' ibrida: trova sia per corrispondenza di parole sia per
    significato, quindi puoi usare tanto i termini tecnici del linguaggio
    normativo quanto le parole con cui la domanda e' stata posta.

    Se un risultato ha `troncato: true` il testo mostrato e' tagliato: per il
    contenuto completo chiama leggi_articolo().

    Ogni risultato porta due date, che non vanno confuse: `inVigoreDal` e' la
    data in cui l'atto ha cominciato ad applicarsi, `dataAtto` quella in cui e'
    stato emanato. Il portale pubblica la prima solo per un terzo degli atti;
    la seconda c'e' quasi sempre. Quando `inVigoreDal` manca, usa `dataAtto`
    per collocare l'atto nel tempo, ma non spacciarla per la data di entrata in
    vigore.

    Il campo `passoAbrogato` dice che PROPRIO QUESTO articolo o comma e' stato
    soppresso, dentro un atto che per il resto resta in vigore. E' il caso piu'
    insidioso: il testo si legge intero e sensato, e nulla in esso avverte che
    non vale piu', perche' questo archivio conserva gli atti come furono
    pubblicati e non li riscrive. Non citarlo come disciplina: di' che e' stato
    abrogato, indica `passoAbrogatoDa`, e cerca cosa si applica al suo posto.

    Il campo `abrogata` riguarda invece l'atto INTERO: se e' true, quell'atto
    e' stato abrogato tutto e non e' piu' diritto vigente, per quanto il
    testo si legga bene. Dillo in apertura, cita `abrogataDa` se c'e', e cerca
    la disciplina che l'ha sostituito. L'assenza del campo non prova nulla in
    senso contrario: il marchio copre 358 norme su oltre dodicimila.

    Il campo `citatoDaAttiSuccessivi` e' il piu' importante che leggi. Elenca
    gli atti POSTERIORI che citano proprio quell'articolo, e in questo
    ordinamento citarlo significa quasi sempre modificarlo: "il comma 1
    dell'articolo 6 della Legge 171/2022 e' cosi' modificato". Se compare, il
    testo che hai davanti puo' NON essere quello vigente: il campo porta con
    se' il TESTO della modifica, gia' pronto da leggere. Confrontalo con il
    passo principale ed esponi la versione vigente, dicendo cosa e' cambiato.

    Il campo `ancheIn` elenca altri atti che riportano lo stesso identico testo:
    tariffari riemessi ogni anno, decreti che ne ripubblicano altri, versioni
    consolidate. Compaiono una volta sola per non sprecare i posti utili, ma
    l'elenco e' un indizio di vigenza da non ignorare: se il passo che stai per
    citare ricorre anche in atti piu' recenti, la versione da esporre e' quella,
    e vale la pena aprirla con leggi_articolo() prima di rispondere.

    Se la prima ricerca rende poco, riformula con il lessico normativo prima di
    concludere che l'archivio non contiene la materia.

    ATTENZIONE: questa ricerca restituisce SEMPRE dei risultati, anche quando
    l'archivio non disciplina affatto la materia chiesta - in quel caso rende
    i passi meno lontani, che possono non entrarci nulla. Il `rango` dice solo
    l'ordine, non la pertinenza. L'unico modo di stabilire se un risultato
    risponde e' leggerne il testo. Se nessuno parla davvero della materia,
    la risposta giusta e' che l'archivio non la contiene.

    Args:
        query: cosa cercare, es. "vincoli alla edificazione in zona agricola"
        limite: quanti risultati restituire (default 8, alzalo se la materia e' ampia)
        dal_anno: opzionale, scarta le norme anteriori a quell'anno. Utile per
            cercare la disciplina piu' recente su una materia gia' individuata.
    """
    lessicali = _full_text(query, limite * AMPIEZZA, dal_anno)
    semantici = _semantico(query, limite * AMPIEZZA, dal_anno)
    if semantici is None:
        righe = lessicali[:limite]
        modo = "solo lessicale (semantica non disponibile)"
    else:
        if RERANK:
            # Si riordina sui CANDIDATI, non sui primi otto: riordinare solo il
            # risultato finale non potrebbe ripescare nulla da piu' in basso.
            larghi = _fondi([(semantici, PESO_SEMANTICO), (lessicali, PESO_LESSICALE)],
                            limite * AMPIEZZA, taglia=False)
            righe = _rerank(query, larghi, limite)
            for i, r in enumerate(righe, 1):
                r["rango"] = i
                r["troncato"] = _troncato(r["testo"])
                r["testo"] = _taglia(r["testo"])
            modo = "ibrida con riordino"
        else:
            righe = _fondi([(semantici, PESO_SEMANTICO), (lessicali, PESO_LESSICALE)], limite)
            modo = "ibrida"
    if righe:
        righe = _piu_recenti(_bersagli_abrogati(_novelle(righe)))

    if not righe:
        return {"risultati": [], "quanti": 0, "ricerca": modo,
                "nota": "Nessun comma trovato. Prova sinonimi o termini piu' generali."}
    return {"risultati": righe, "quanti": len(righe), "ricerca": modo}


@tool
def leggi_articolo(norma_id: str, numero: str) -> dict:
    """Restituisce il testo integrale di un articolo, comma per comma, senza troncamenti.

    Da usare quando cerca_testo ha individuato un articolo rilevante e serve il
    testo completo per rispondere con precisione.

    Porta gli stessi marchi di vigenza di cerca_testo, e vanno letti prima di
    citare: `abrogata` (l'atto e' caduto per intero: non e' piu' vigente, e
    l'assenza del campo non dimostra che lo sia), `passoAbrogato` sull'articolo
    e `abrogato` sul singolo comma (quella partizione e' stata soppressa dentro
    un atto ancora vivo), `citatoDaAttiSuccessivi` (un atto posteriore cita questo articolo,
    e qui citare significa quasi sempre modificare) e `versionePiuRecente` (un
    atto posteriore ha un articolo con la stessa rubrica, cioe' quasi sempre la
    stessa disposizione riscritta). Se uno dei due compare, la catena non
    finisce qui: aprilo, perche' il testo che stai leggendo non e' l'ultimo.

    Args:
        norma_id: id della norma, es. "L-87-2026"
        numero: numero dell'articolo, es. "7" oppure "12 bis"
    """
    righe = grafo().query("""
        MATCH (n:Norma {id: $norma_id})-[:HA_ARTICOLO]->(a:Articolo)
        WHERE a.numero = $numero
        OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
        WITH n, a, c ORDER BY c.ordine
        RETURN n.id AS normaId, n.titolo AS normaTitolo,
               toString(n.dataEntrataVigore) AS inVigoreDal,
               toString(n.data) AS dataAtto,
               a.numero AS articolo, a.rubrica AS rubrica,
               a.titolo AS partizioneTitolo, a.capoRubrica AS partizioneCapo,
               n.urlDocumento AS urlDocumento,
               n.abrogata AS abrogata, n.abrogataDa AS abrogataDa,
               a.abrogato AS passoAbrogato, a.abrogatoDa AS passoAbrogatoDa,
               collect({numero: c.numero, testo: c.testo,
                        abrogato: c.abrogato, abrogatoDa: c.abrogatoDa}) AS commi
    """, {"norma_id": norma_id, "numero": str(numero)})
    if not righe:
        # Un vicolo cieco costringe a indovinare, e indovinare costa un giro
        # intero. La numerazione vera ha forme che non si prevedono - "12 bis",
        # "3-ter", "1 (Definizioni)" - quindi si restituisce l'elenco: dallo
        # sbaglio si esce leggendo, non ritentando alla cieca.
        esistenti = grafo().query("""
            MATCH (n:Norma {id: $norma_id})-[:HA_ARTICOLO]->(a:Articolo)
            RETURN a.numero AS numero ORDER BY a.ordine
        """, {"norma_id": norma_id})
        if not esistenti:
            return {"errore": f"La norma '{norma_id}' non e' in archivio, oppure "
                              f"il suo testo non e' stato caricato. Individuala "
                              f"con trova_norma()."}
        numeri = [e["numero"] for e in esistenti]
        return {"errore": f"L'articolo {numero} non esiste in {norma_id}.",
                "articoliDisponibili": numeri if len(numeri) <= 60 else
                                       numeri[:60] + [f"... e altri {len(numeri) - 60}"],
                "quantiArticoli": len(numeri)}
    # Gli stessi marchi di vigenza che porta cerca_testo. Senza, la catena si
    # spezza proprio quando l'agente va a fondo: misurato sul caso reale,
    # apriva L-158-2025 con questo strumento e non vedeva piu' che DD-52-2026
    # la riscrive.
    riga = dict(righe[0])
    riga["testo"] = " ".join(c.get("testo") or "" for c in riga.get("commi") or [])
    riga["normaId"] = riga.get("normaId")
    _novelle([riga])
    _bersagli_abrogati([riga])
    for marchio in ("citatoDaAttiSuccessivi", "passiIntrodottiOraAbrogati"):
        if riga.get(marchio):
            righe[0][marchio] = riga[marchio]

    rub = (righe[0].get("rubrica") or "").strip()
    if len(rub) > 12:
        try:
            piu = grafo().query("""
                MATCH (mia:Norma {id: $norma_id})
                MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)
                WHERE n.anno > mia.anno AND a.rubrica IS NOT NULL
                  AND toLower(trim(a.rubrica)) = toLower($rub)
                OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
                WITH n, a, c ORDER BY c.ordine
                WITH n, a, collect(c.testo)[..3] AS testi
                RETURN n.id AS norma, n.anno AS anno, a.numero AS articolo,
                       reduce(t = "", x IN testi | t + " " + coalesce(x, "")) AS testo
                ORDER BY n.anno DESC LIMIT 2
            """, {"norma_id": norma_id, "rub": rub})
        except Exception:
            piu = []
        if piu:
            # Il testo, non solo il rimando. Col solo riferimento l'agente
            # riconosceva la catena ma la percorreva 1 volta su 4: misurato.
            righe[0]["versionePiuRecente"] = [
                {**x, "testo": _taglia(x.get("testo"), 1200)} for x in piu]

    return righe[0]


def url_documento(norma_id: str) -> str | None:
    """URL del PDF originale sul portale, se la norma esiste e lo possiede.

    Non e' un tool per l'agente: serve al proxy del server web, che lo
    rinoltra al browser.
    """
    righe = grafo().query(
        "MATCH (n:Norma {id: $id}) RETURN n.urlDocumento AS url", {"id": norma_id})
    return righe[0]["url"] if righe else None


@tool
def struttura_norma(norma_id: str) -> dict:
    """Restituisce l'indice di una norma: quanti articoli ha, con numero, rubrica,
    numero di commi e collocazione in Titolo/Capo.

    USA SEMPRE QUESTO per domande del tipo "quanti articoli ha", "com'e'
    strutturata", "di cosa tratta l'articolo N", o per orientarti prima di
    leggere. Non leggere mai gli articoli uno per uno per contarli: e' questo
    lo strumento che risponde in una sola chiamata.

    Args:
        norma_id: id della norma, es. "L-87-2026"
    """
    testa = grafo().query("""
        MATCH (n:Norma {id: $norma_id})
        RETURN n.id AS id, n.titolo AS titolo, n.tipo AS tipo,
               n.urlDocumento AS urlDocumento,
               n.caricata AS testoDisponibile,
               toString(n.dataEntrataVigore) AS inVigoreDal,
               toString(n.data) AS dataAtto
    """, {"norma_id": norma_id})
    if not testa:
        return {"errore": f"Norma '{norma_id}' non trovata. Usa trova_norma() per individuarla."}

    articoli = grafo().query("""
        MATCH (:Norma {id: $norma_id})-[:HA_ARTICOLO]->(a:Articolo)
        OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
        WITH a, count(c) AS commi
        RETURN a.numero AS numero, a.rubrica AS rubrica, commi,
               a.titolo AS titoloPartizione, a.capoRubrica AS capoPartizione
        ORDER BY a.ordine
    """, {"norma_id": norma_id})

    return {**testa[0], "totaleArticoli": len(articoli),
            "totaleCommi": sum(a["commi"] for a in articoli),
            "articoli": articoli}


@tool
def trova_norma(numero: int | None = None, anno: int | None = None,
                tipo: str | None = None, testo: str | None = None) -> dict:
    """Individua una norma per tipo/numero/anno (es. Legge 140 del 2017) oppure
    per parole contenute nel titolo.

    Il campo testoDisponibile dice se l'archivio ne possiede il testo integrale
    o se la norma compare solo perche' citata da altre.

    Args:
        numero: numero della norma
        anno: anno della norma
        tipo: es. "Legge", "Decreto Delegato"
        testo: parole del titolo, se non conosci numero e anno
    """
    if numero is not None:
        righe = grafo().query("""
            MATCH (n:Norma)
            WHERE n.numero = $numero
              AND ($anno IS NULL OR n.anno = $anno)
              AND ($tipo IS NULL OR toLower(n.tipo) CONTAINS toLower($tipo))
            OPTIONAL MATCH (n)-[:HA_ARTICOLO]->(a:Articolo)
            WITH n, count(a) AS articoli
            RETURN n.id AS id, n.tipo AS tipo, n.numero AS numero, n.anno AS anno,
                   n.titolo AS titolo, n.caricata AS testoDisponibile,
                   toString(n.dataEntrataVigore) AS inVigoreDal,
                   toString(n.data) AS dataAtto,
                   n.urlScheda AS urlScheda, n.urlDocumento AS urlDocumento,
                   articoli,
                   n.abrogata AS abrogata, n.abrogataDa AS abrogataDa
            ORDER BY n.anno DESC LIMIT 10
        """, {"numero": int(numero), "anno": int(anno) if anno else None, "tipo": tipo})
    elif testo:
        righe = grafo().query("""
            CALL db.index.fulltext.queryNodes('titoli_norme', $testo)
            YIELD node, score
            OPTIONAL MATCH (node)-[:HA_ARTICOLO]->(a:Articolo)
            WITH node, score, count(a) AS articoli
            RETURN node.id AS id, node.tipo AS tipo, node.numero AS numero,
                   node.anno AS anno, node.titolo AS titolo,
                   node.caricata AS testoDisponibile,
                   toString(node.dataEntrataVigore) AS inVigoreDal,
                   toString(node.data) AS dataAtto,
                   node.urlScheda AS urlScheda, node.urlDocumento AS urlDocumento,
                   articoli,
                   node.abrogata AS abrogata, node.abrogataDa AS abrogataDa
            ORDER BY score DESC LIMIT 10
        """, {"testo": _lucene(testo)})
    else:
        return {"errore": "Serve almeno 'numero' oppure 'testo'."}

    if not righe and numero is not None:
        # Come per leggi_articolo: dal buco si esce con un dato, non con un
        # nuovo tentativo alla cieca. Quasi sempre il numero e' giusto e ballano
        # l'anno o la tipologia, quindi si mostra quel numero negli altri anni.
        altrove = grafo().query("""
            MATCH (n:Norma) WHERE n.numero = $numero
            RETURN n.id AS id, n.tipo AS tipo, n.anno AS anno,
                   n.caricata AS testoDisponibile, left(n.titolo, 90) AS titolo
            ORDER BY abs(n.anno - coalesce($anno, n.anno)), n.anno DESC LIMIT 8
        """, {"numero": int(numero), "anno": int(anno) if anno else None})
        if altrove:
            return {"risultati": [], "nota":
                    f"Nessun atto n. {numero}"
                    + (f" del {anno}" if anno else "")
                    + (f" di tipo '{tipo}'" if tipo else "")
                    + ". Con quel numero l'archivio ha pero' questi:",
                    "altriCandidati": altrove}
        return {"risultati": [], "nota":
                f"Nessun atto porta il numero {numero}. Se il numero viene da "
                f"una citazione puo' essere errato: cerca per materia con "
                f"cerca_testo(), o per parole del titolo con trova_norma(testo=...)."}
    if not righe:
        return {"risultati": [], "nota":
                "Nessun titolo corrisponde a queste parole. L'indice cerca nel "
                "titolo, non nel testo: per il merito usa cerca_testo()."}
    return {"risultati": righe}


@tool
def elenco_norme(tipo: str | None = None, anno: int | None = None, limite: int = 50) -> dict:
    """Restituisce il riepilogo complessivo delle norme presenti in archivio e un estratto.

    Da usare quando l'utente chiede cosa contiene la banca dati o per verificare
    la copertura normativa per anno/tipologia. Per cercare un atto specifico usare trova_norma.

    Args:
        tipo: opzionale, filtra per tipologia (es. 'Legge', 'Legge Qualificata', 'Decreto Legge')
        anno: opzionale, filtra per anno di emanazione
        limite: numero massimo di norme da restituire in dettaglio (default 50, max 100)
    """
    limite = min(max(1, limite), 100)

    # Riepilogo per tipologia
    per_tipo = grafo().query("""
        MATCH (n:Norma)
        RETURN coalesce(n.tipo, 'Altro') AS tipo,
               sum(CASE WHEN n.caricata THEN 1 ELSE 0 END) AS conTesto,
               sum(CASE WHEN n.caricata THEN 0 ELSE 1 END) AS soloCitate,
               count(n) AS totale
        ORDER BY conTesto DESC
    """)

    totali = grafo().query("""
        MATCH (n:Norma)
        RETURN sum(CASE WHEN n.caricata THEN 1 ELSE 0 END) AS conTesto,
               sum(CASE WHEN n.caricata THEN 0 ELSE 1 END) AS soloCitate,
               count(n) AS totaleComplessivo
    """)[0]

    # Dettaglio norme filtrate
    filtri = ["($anno IS NULL OR n.anno = $anno)"]
    if tipo:
        filtri.append("toLower(n.tipo) CONTAINS toLower($tipo)")

    where_clause = " AND ".join(filtri)

    righe = grafo().query(f"""
        MATCH (n:Norma)
        WHERE {where_clause}
        OPTIONAL MATCH (n)-[:HA_ARTICOLO]->(a:Articolo)
        WITH n, count(a) AS articoli
        RETURN n.id AS id, n.tipo AS tipo, n.titolo AS titolo, n.anno AS anno,
               n.caricata AS testoDisponibile, articoli,
               n.urlDocumento AS urlDocumento
        ORDER BY n.anno DESC, n.numero DESC
        LIMIT $limite
    """, {"anno": anno, "tipo": tipo, "limite": limite})

    return {
        "riepilogoTotale": totali,
        "distribuzionePerTipo": per_tipo,
        "normeEstratte": righe,
        "conteggioEstratte": len(righe),
        "limiteApplicato": limite
    }


@tool
def citazioni_da(norma_id: str) -> dict:
    """Restituisce le norme da cui dipende quella indicata, con i punti del testo
    in cui sono richiamate, piu' la base giuridica citata nel preambolo.

    Da usare per domande su presupposti, rinvii e dipendenze normative.

    Args:
        norma_id: id della norma, es. "L-87-2026"
    """
    righe = grafo().query("""
        MATCH (n:Norma {id: $norma_id})
        OPTIONAL MATCH (n)-[:HA_ARTICOLO]->(art:Articolo)-[:HA_COMMA]->(cm:Comma)-[r:CITA]->(t:Norma)
        WITH t, collect(DISTINCT 'art.' + art.numero + ' c.' + cm.numero) AS punti, count(r) AS volte
        WHERE t IS NOT NULL
        RETURN t.id AS norma, t.tipo AS tipo, t.titolo AS titolo,
               t.caricata AS testoDisponibile, volte, punti[..6] AS citataIn,
               t.urlDocumento AS urlDocumento
        ORDER BY volte DESC
    """, {"norma_id": norma_id})
    preambolo = grafo().query("""
        MATCH (n:Norma {id: $norma_id})-[r:CITA]->(t:Norma)
        WHERE r.origine = 'preambolo'
        RETURN t.id AS norma, t.titolo AS titolo, t.caricata AS testoDisponibile,
               r.articoloCitato AS articoloCitato
    """, {"norma_id": norma_id})
    return {"dipendenze": righe, "basePreambolo": preambolo}


@tool
def chi_cita(norma_id: str) -> dict:
    """Restituisce le norme dell'archivio che richiamano quella indicata.

    Serve per capire l'impatto di una norma o chi ne dipende.

    Args:
        norma_id: id della norma, es. "L-140-2017"
    """
    righe = grafo().query("""
        MATCH (src:Norma)-[:HA_ARTICOLO]->(art:Articolo)-[:HA_COMMA]->(cm:Comma)-[r:CITA]->(:Norma {id: $norma_id})
        WITH src, collect(DISTINCT 'art.' + art.numero) AS articoli, count(r) AS volte
        RETURN src.id AS norma, src.titolo AS titolo, articoli[..6] AS articoli, volte,
               src.urlDocumento AS urlDocumento
        ORDER BY volte DESC LIMIT 20
    """, {"norma_id": norma_id})
    return {"citataDa": righe, "quante": len(righe)}


STRUMENTI = [cerca_testo, leggi_articolo, struttura_norma, trova_norma,
             elenco_norme, citazioni_da, chi_cita]
