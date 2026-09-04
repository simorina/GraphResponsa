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

import logging
import os
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
            keyword_index_name=INDICE_KEYWORD,
            search_type="hybrid",
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
        WHERE $dal_anno IS NULL OR norma.anno >= $dal_anno
        RETURN norma.id AS normaId, norma.titolo AS normaTitolo,
               norma.anno AS anno,
               toString(norma.dataEntrataVigore) AS inVigoreDal,
               art.numero AS articolo, art.rubrica AS rubrica,
               art.titolo AS partizioneTitolo, art.capoRubrica AS partizioneCapo,
               CASE WHEN node:Comma THEN node.numero ELSE null END AS comma,
               node.testo AS testo
        ORDER BY score DESC, norma.anno DESC LIMIT $limite
    """, {"query": query, "limite": limite, "dal_anno": dal_anno})
    for i, r in enumerate(righe, 1):
        r["rango"] = i
        r["troncato"] = _troncato(r["testo"])
        r["testo"] = _taglia(r["testo"])
    return righe


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
    store = ricerca_vettoriale()
    if store is None:
        righe = _full_text(query, limite, dal_anno)
        modo = "solo lessicale"
    else:
        try:
            # Con un filtro sull'anno si pesca piu' largo e si taglia dopo:
            # il filtro agisce sui risultati, non sull'indice.
            k = limite * 4 if dal_anno else limite
            trovati = store.similarity_search_with_score(query, k=k)
            righe = []
            for documento, punteggio in trovati:
                m = documento.metadata or {}
                if dal_anno and (m.get("anno") or 0) < dal_anno:
                    continue
                righe.append({
                    # Niente punteggio: il retriever ibrido lo rinormalizza, e
                    # misurato vale ~1.000 tanto per "termine per il ricorso
                    # elettorale" (che l'archivio disciplina) quanto per
                    # "requisiti della nave rompighiaccio in Artico" (che non
                    # esiste in San Marino). Un numero costante che si legge
                    # come confidenza spinge a rispondere sul nulla. Il rango
                    # dice il vero: questo e' il k-esimo passo piu' vicino fra
                    # quelli esistenti, senza promettere che sia pertinente.
                    "rango": len(righe) + 1,
                    "normaId": m.get("normaId"), "normaTitolo": m.get("normaTitolo"),
                    "anno": m.get("anno"),
                    "inVigoreDal": m.get("inVigoreDal"),
                    "articolo": m.get("articolo"), "rubrica": m.get("rubrica"),
                    "partizioneTitolo": m.get("partizioneTitolo"),
                    "partizioneCapo": m.get("partizioneCapo"),
                    "comma": m.get("comma"),
                    "troncato": _troncato(documento.page_content),
                    "testo": _taglia(documento.page_content),
                })
                if len(righe) >= limite:
                    break
            modo = "ibrida"
        except Exception:
            righe = _full_text(query, limite, dal_anno)
            modo = "solo lessicale (ricerca ibrida non disponibile)"

    if not righe:
        return {"risultati": [], "quanti": 0, "ricerca": modo,
                "nota": "Nessun comma trovato. Prova sinonimi o termini piu' generali."}
    return {"risultati": righe, "quanti": len(righe), "ricerca": modo}


@tool
def leggi_articolo(norma_id: str, numero: str) -> dict:
    """Restituisce il testo integrale di un articolo, comma per comma, senza troncamenti.

    Da usare quando cerca_testo ha individuato un articolo rilevante e serve il
    testo completo per rispondere con precisione.

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
               a.numero AS articolo, a.rubrica AS rubrica,
               a.titolo AS partizioneTitolo, a.capoRubrica AS partizioneCapo,
               collect({numero: c.numero, testo: c.testo}) AS commi
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
    return righe[0]


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
               n.caricata AS testoDisponibile,
               toString(n.dataEntrataVigore) AS inVigoreDal
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
                   n.urlScheda AS urlScheda, articoli
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
                   node.urlScheda AS urlScheda, articoli
            ORDER BY score DESC LIMIT 10
        """, {"testo": testo})
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
               n.caricata AS testoDisponibile, articoli
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
               t.caricata AS testoDisponibile, volte, punti[..6] AS citataIn
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
        RETURN src.id AS norma, src.titolo AS titolo, articoli[..6] AS articoli, volte
        ORDER BY volte DESC LIMIT 20
    """, {"norma_id": norma_id})
    return {"citataDa": righe, "quante": len(righe)}


STRUMENTI = [cerca_testo, leggi_articolo, struttura_norma, trova_norma,
             elenco_norme, citazioni_da, chi_cita]
