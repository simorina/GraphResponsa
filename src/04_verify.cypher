// =====================================================================
// 04 - Verifica del grafo e dimostrazione di cosa sa rispondere.
// Incollabile nel Neo4j Browser di Aura, oppure eseguibile con 04_verify.py
// che confronta i risultati con gli attesi.
// =====================================================================


// --- 1. Struttura della L.87/2026 -----------------------------------
// Atteso: 60 articoli, 240 commi, 8 titoli, 18 capi (come metadati degli articoli).
// Sono i conteggi verificati a mano sul PDF: uno scarto significa parsing rotto.
MATCH (n:Norma {id: 'L-87-2026'})
MATCH (n)-[:HA_ARTICOLO]->(a:Articolo)
OPTIONAL MATCH (a)-[:HA_COMMA]->(cm:Comma)
RETURN count(DISTINCT a) AS articoli,
       count(DISTINCT cm) AS commi,
       count(DISTINCT a.titolo) AS titoli,
       count(DISTINCT CASE WHEN a.capo IS NOT NULL THEN a.titolo + '/' + coalesce(a.capoRubrica, a.capo) END) AS capi;


// --- 2. Integrita': articoli senza commi ----------------------------
// Atteso: 0
MATCH (a:Articolo) WHERE NOT (a)-[:HA_COMMA]->() RETURN count(a) AS articoli_senza_commi;


// --- 3. Integrita': commi vuoti -------------------------------------
// Atteso: 0
MATCH (c:Comma) WHERE c.testo IS NULL OR trim(c.testo) = ''
RETURN count(c) AS commi_vuoti;


// --- 4. Le norme piu' citate ----------------------------------------
// Mostra su cosa poggia davvero il corpus. caricata=false sono gli stub:
// norme che il grafo sa esistere, senza averne il testo.
MATCH (:Comma)-[r:CITA]->(t:Norma)
RETURN t.id AS norma, t.tipo AS tipo, t.caricata AS in_archivio,
       count(r) AS volte_citata
ORDER BY volte_citata DESC, norma LIMIT 10;


// --- 5. Tracciamento di una dipendenza normativa --------------------
// Chi cita la Legge 59/1974, e da quale punto esatto del testo.
MATCH (norma:Norma)-[:HA_ARTICOLO]->(a:Articolo)-[:HA_COMMA]->(cm:Comma)-[r:CITA]->(t:Norma {id: 'L-59-1974'})
RETURN norma.id AS da_norma, a.numero AS articolo, cm.numero AS comma,
       r.articoloCitato AS articolo_citato, t.caricata AS bersaglio_in_archivio,
       r.testoCitazione AS citazione;


// --- 6. LA query Graph RAG ------------------------------------------
// Ricerca full-text sul comma, poi risalita del grafo per il contesto:
// l'agente ottiene il testo esatto E il punto in cui si colloca nella norma.
CALL db.index.fulltext.queryNodes('testo_normativo', 'pianificazione territoriale')
YIELD node, score
WHERE node:Comma
MATCH (art:Articolo)-[:HA_COMMA]->(node)
MATCH (norma:Norma)-[:HA_ARTICOLO]->(art)
RETURN round(score, 2) AS punteggio,
       norma.id AS norma,
       coalesce(art.titolo, '-') AS titolo,
       coalesce(art.capoRubrica, art.capo, '-') AS capo,
       'Art.' + art.numero AS articolo,
       art.rubrica AS rubrica,
       node.numero AS comma,
       left(node.testo, 160) AS estratto
ORDER BY score DESC LIMIT 5;


// --- 7. Contesto completo di un singolo comma -----------------------
// Quello che un agente passerebbe al modello come contesto di risposta:
// il comma, la sua collocazione, e le norme da cui dipende.
MATCH (cm:Comma {id: 'L-87-2026/art-1/c-3'})
MATCH (art:Articolo)-[:HA_COMMA]->(cm)
MATCH (norma:Norma)-[:HA_ARTICOLO]->(art)
OPTIONAL MATCH (cm)-[r:CITA]->(dip:Norma)
RETURN norma.titolo AS norma,
       norma.dataEntrataVigore AS in_vigore_dal,
       'Art.' + art.numero + ' (' + art.rubrica + ') comma ' + cm.numero AS riferimento,
       cm.testo AS testo,
       collect(dip.id + CASE WHEN dip.caricata THEN ' [in archivio]' ELSE ' [non in archivio]' END) AS dipende_da;


// --- 8. Le norme da scaricare al prossimo giro ----------------------
// Gli stub ordinati per quanto sono citati: la lista di lavoro naturale.
MATCH (:Comma)-[r:CITA]->(t:Norma {caricata: false})
RETURN t.tipo AS tipo, t.numero AS numero, t.anno AS anno, count(r) AS citazioni
ORDER BY citazioni DESC, anno DESC;
