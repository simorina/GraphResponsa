# Graph RAG sulle leggi sammarinesi

Grafo Neo4j della normativa della Repubblica di San Marino, costruito per essere
interrogato da un agente AI. Le fonti sono scaricate dall'archivio ufficiale del
Consiglio Grande e Generale.

Stato: **pilota su 3 leggi**, con la pipeline pronta a scalare.

## Cosa c'è nel grafo

449 nodi, 562 relazioni.

## Il modello

```
(:Norma)-[:HA_ARTICOLO]->(:Articolo)-[:HA_COMMA]->(:Comma)
(:Norma)-[:HA_ALLEGATO]->(:Allegato)
(:Comma)-[:CITA]->(:Norma)
(:Comma)-[:CITA_ARTICOLO]->(:Articolo)
(:Norma)-[:CITA]->(:Norma)
```

Tutti gli atti normativi (Leggi, Decreti, Decreti Delegati, Leggi Costituzionali, ecc.) sono entità **`:Norma`**, con un'etichetta secondaria specifica (`:Legge`, `:DecretoDelegato`, `:Decreto`, ecc.) e proprietà `tipo`.

**Titoli e Capi non sono entità (nodi) nel grafo**, ma proprietà informative memorizzate direttamente sull'Articolo (`titolo`, `titoloRubrica`, `capo`, `capoRubrica`). Questo semplifica il grafo, velocizza le query e mantiene la gerarchia snella: **la norma possiede direttamente gli articoli, e gli articoli possiedono i commi**.

Due scelte che reggono tutto il resto:

**Il comma è l'unità di retrieval.** È l'unità con cui il diritto cita se stesso
("art. 5, comma 2"). L'agente trova il comma esatto e risale il grafo per il contesto,
invece di ricevere un frammento tagliato a lunghezza fissa.

**Le norme citate ma non scaricate esistono come stub** (`caricata: false`). Il grafo sa
che una norma è citata anche senza averne il testo, quindi l'agente può dichiarare la
dipendenza invece di tacere. Sono anche la lista di lavoro per il prossimo scaricamento.

## Uso

Serve un file `.env` con le credenziali Aura (`NEO4J_URI`, `NEO4J_USERNAME`,
`NEO4J_PASSWORD`, `NEO4J_DATABASE`).

```bash
pip install -r requirements.txt

python src/01_scrape.py 3    # scarica le prime N leggi (cache su disco)
python src/02_parse.py       # PDF -> JSON strutturato, nessuna rete
python src/03_load.py        # JSON -> Neo4j, idempotente
python src/04_verify.py      # verifica i conteggi attesi ed esce != 0 se falliscono
```

`src/04_verify.cypher` contiene le stesse query commentate, incollabili nel Neo4j Browser.

## Note sulla fonte

Il portale ha tre comportamenti che fanno fallire uno scraper ingenuo, tutti gestiti in
`01_scrape.py` e documentati nella
[spec di design](docs/superpowers/specs/2026-08-29-graph-rag-leggi-sammarinesi-design.md):

1. **La ricerca si attiva solo con `indicericerca=-1` e tutti i campi del form**, anche
   vuoti. Con meno parametri il server risponde `200` con zero risultati: fallisce in
   silenzio. Per questo lo scraper solleva un errore esplicito se non trova risultati.
2. **Le pagine dichiarano `charset=utf-8` ma sono windows-1252**, e scrivono gli apostrofi
   come `&#146;` (un carattere di controllo). Senza rimappatura si perdono accenti e
   apostrofi.
3. **`documento<ID>.html` non è HTML**: è un PDF, oppure uno ZIP se la norma ha allegati.
   Per la L. 87/2026 sono 124 MB, di cui il testo normativo è 428 KB e il resto cartografia.

Lo scraper mette in pausa fra le richieste e usa la cache su disco: il sito viene
interrogato una volta sola per documento.

## Limiti noti

- `CITA_ARTICOLO` è ancora vuoto: tutte le citazioni puntuali bersagliano articoli di norme
  non ancora scaricate. Si popola da sé man mano che si caricano le norme citate.
- 6 commi su 299 hanno `numerazioneAnomala: true` — novelle che riportano la numerazione
  della norma modificata, o refusi della legge (l'art.7 della L. 87/2026 ha due commi "2").
  Il testo è conservato integralmente; il flag serve a non fidarsi ciecamente del numero.
- Aura Free regge 200k nodi / 400k relazioni: abbondante ora, da rivalutare prima di
  caricare tutte le 2460 leggi dell'archivio.

## Interfaccia e agente (LangChain)

L'ambiente e' isolato in un venv dedicato: l'ambiente Python globale ospita altri
progetti con `langchain` 0.3, incompatibile con la 1.x richiesta qui.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/Scripts/python.exe src/server.py                        # -> http://127.0.0.1:8000
```

Chat web in cui fare domande in italiano sulla normativa.

**Stack:** `create_agent` di LangChain 1.x (in LangGraph 1.0 `create_react_agent` di
`langgraph.prebuilt` e' deprecato in suo favore), modello `claude-haiku-4-5` via
`langchain-anthropic`, connessione al grafo via `Neo4jGraph` di `langchain-neo4j`,
memoria conversazionale con checkpointer LangGraph.

Sette strumenti tipizzati (`@tool` in `src/agente/strumenti.py`):

| Strumento | Cosa fa |
|---|---|
| `cerca_testo` | Ricerca **ibrida** (semantica + lessicale) sui commi, con contesto risalito dal grafo |
| `leggi_articolo` | Testo integrale di un articolo, comma per comma |
| `struttura_norma` | L'indice di una norma: quanti e quali articoli, con rubriche |
| `trova_norma` | Individua una norma per tipo/numero/anno o per titolo |
| `elenco_norme` | Cosa contiene davvero l'archivio |
| `citazioni_da` | Le dipendenze di una norma |
| `chi_cita` | Chi dipende da una norma |

**Perche' strumenti e non `GraphCypherQAChain`.** `langchain-neo4j` offre una catena
text2cypher che traduce la domanda in Cypher partendo dallo schema del grafo. Richiede
pero' `allow_dangerous_requests=True`, e su materia giuridica una query sbagliata non
produce un errore: produce una risposta plausibile e falsa. Ignorerebbe inoltre le
sottigliezze di questo schema - la distinzione fra norme con testo e norme solo citate,
i commi con numerazione anomala. Qui le query sono scritte e verificate una volta sola;
il modello puo' solo comporle.

**Contro le allucinazioni.** Il prompt impone tre regole: ogni affermazione va ancorata a
norma/articolo/comma; se gli strumenti non trovano nulla l'agente deve dirlo invece di
attingere al diritto italiano; le norme con testo vanno distinte da quelle solo citate.
Sotto ogni risposta la UI mostra i commi effettivamente consultati.

**Ricerca ibrida.** `cerca_testo` usa `Neo4jVector` in modalita' `search_type="hybrid"`:
il canale vettoriale trova per significato, quello full-text per corrispondenza di parole,
e i punteggi si fondono. Gli embedding (`voyage-4`, 1024 dimensioni) stanno come proprieta'
sui nodi `:Comma` gia' esistenti - nessun archivio parallelo, nessun testo duplicato.

La `retrieval_query` gira **dopo** il match vettoriale, con `node` e `score` disponibili:
e' li' che si risale il grafo fino ad articolo e norma. Ricerca semantica e navigazione
delle relazioni sono una query sola, non due passaggi.

Si indicizza con `.venv/Scripts/python.exe src/07_embeddings.py` (idempotente, ~150s per
4.087 commi). Senza `VOYAGE_API_KEY` o senza indice, `cerca_testo` ricade sul full-text e
lo dichiara nel campo `ricerca` del risultato.

Attenzione a `voyage-law-2`: il nome promette il dominio giuridico, ma **non e' multilingue**
- su testi italiani rende meno di `voyage-4`.

**Memoria.** La cronologia non viaggia piu' fra browser e server: la tiene il checkpointer
LangGraph, e il client manda solo un id di conversazione. `InMemorySaver` si azzera al
riavvio; `langchain_neo4j` espone `Neo4jSaver` per renderla durevole, sostituendo una riga.

Serve `ANTHROPIC_API_KEY` nel `.env`. Costo osservato: **~$0.02-0.06 a domanda**.
Il modello si cambia dalla costante `MODELLO` in `src/agente/agente.py`.

### Collaudo

Tre domande con esito atteso noto, verificate attraverso il server:

- *"Cosa prevede la legge sull'Osservatorio Permanente?"* -> `cerca_testo` +
  `leggi_articolo`, cita L. 87/2026 art. 7 commi 1 e 2, 7 fonti allegate
- *"Quanti articoli ha la legge 87/2026?"* -> `struttura_norma` in una sola chiamata,
  risponde 60 articoli e 240 commi
- *"Cosa dice la normativa sammarinese sulle criptovalute?"* -> tre ricerche piu' la
  ricognizione dell'archivio, poi dichiara che non esiste nulla in materia

## Prossimi passi

Layer di retrieval Python → server MCP per l'agente → estensione ai Decreti Delegati
(i più citati) → risoluzione degli stub.
