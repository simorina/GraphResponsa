# Architettura del Knowledge Graph

Grafo Neo4j della normativa della Repubblica di San Marino, costruito per essere
interrogato da un agente in modalità Graph RAG.

**Stato aggiornato:** **83.231 nodi**, **107.539 relazioni**, **2.444 norme con testo integrale** (100% dell'archivio di Leggi, Leggi Qualificate e Costituzionali).

---

## 1. Modello Concettuale ed Entità

Un corpus normativo ha due strutture sovrapposte:
1. **Struttura Gerarchica:** `Norma ➔ Articolo ➔ Comma` (e allegati). Consente l'ancoraggio preciso e la risalita dal frammento al contesto normativo.
2. **Rete delle Citazioni e Rinvii:** collegamenti incrociati tra commi/norme ed altri atti richiamati (`CITA`, `CITA_ARTICOLO`).

### Schema Entità-Relazioni (Mermaid)

```mermaid
erDiagram
    NORMA ||--o{ ARTICOLO : HA_ARTICOLO
    ARTICOLO ||--o{ COMMA : HA_COMMA
    NORMA ||--o{ ALLEGATO : HA_ALLEGATO
    COMMA }o--o{ NORMA : CITA
    COMMA }o--o{ ARTICOLO : CITA_ARTICOLO
    NORMA }o--o{ NORMA : CITA

    NORMA {
        string id PK "es. L-87-2026, LQ-186-2005"
        string tipo "Legge, Legge Qualificata, Legge Costituzionale"
        int numero "Numero atto"
        int anno "Anno emanazione"
        boolean caricata "true se con testo, false se stub"
        string titolo "Titolo ufficiale della norma"
        string preambolo "Formula di promulgazione"
        date dataPubblicazione "Data Bollettino"
        date dataEntrataVigore "Data efficacia"
    }

    ARTICOLO {
        string id PK "es. L-87-2026/art-7"
        string numero "es. 7, 7-bis"
        int ordine "Ordinamento progressivo"
        string rubrica "Rubrica articolo"
        string titolo "Titolo di appartenenza"
        string capo "Capo di appartenenza"
        string testo "Testo aggregato"
    }

    COMMA {
        string id PK "es. L-87-2026/art-7/c-2"
        string numero "es. 1, 2, 2-bis"
        int ordine "Ordinamento nel comma"
        string testo "Testo integrale atomico"
        floatArray embedding "Vettore Voyage-4 1024d"
        boolean numerazioneAnomala "Flag duplicati ufficiali"
        boolean commaImplicito "Flag comma non numerato"
    }

    ALLEGATO {
        string id PK "es. L-87-2026/all-1"
        string nome "Nome documento allegato"
        int bytes "Dimensione in byte"
    }
```

### 1.1 Cosa sono le "Rubriche" e perché sono fondamentali

Nel diritto e nella tecnica legislativa, la **rubrica** è il **titolo sintetico o intestazione che dà il nome a un articolo** (o a un Capo/Titolo), posto subito dopo il numero dell'articolo tra parentesi o in grassetto.

```text
Art. 4                              ◄─── Numero Articolo
(Incompatibilità con altre cariche) ◄─── RUBRICA DELL'ARTICOLO
1. La carica di Capitano Reggente...◄─── Testo del Comma 1
```

Nel nostro Knowledge Graph, le rubriche svolgono due funzioni cruciali:
1. **Navigazione dell'Indice in 1ms (`struttura_norma`):** l'agente riceve in una sola chiamata l'elenco di tutti gli articoli con le rispettive rubriche, individuando immediatamente l'articolo pertinente senza dover leggere l'intera legge.
2. **Doppia Indicizzazione Full-Text (`[n.testo, n.rubrica]`):** l'indice Lucene indicizza sia il corpo dei commi sia le rubriche degli articoli. Se un utente cerca un termine (es. *"Incompatibilità"* o *"Sanzioni"*), il sistema individua l'articolo anche se la parola chiave compare solo nel titolo dell'articolo e non nel corpo del comma.

---

## 2. Metriche e Consistenza del Grafo

| Entità / Label | Quantità | Ruolo nel Modello |
|---|---|---|
| **`:Comma`** | **`53.393`** | Unità atomica di testo, ricerca semantica e retrieval |
| **`:Articolo`** | **`25.803`** | Articoli con rubriche, capi e collocazione tematica |
| **`:Norma`** | **`3.650`** | Tutti gli atti normativi censiti: |
| ↳ *con testo integrale (`caricata: true`)* | *`2.444`* | *100% dell'archivio ufficiale delle Leggi, Costituzionali e Qualificate* |
| ↳ *stub citati (`caricata: false`)* | *`1.206`* | *Atti richiamati nei testi normativi per tracciare i rinvii* |
| **`:Allegato`** | **`385`** | Tabelle, cartografie e allegati normativi |
| **TOTALE NODI** | **`83.231`** | |

### Relazioni (Archi)

| Relazione | Quantità | Direzione | Significato |
|---|---|---|---|
| **`HA_COMMA`** | **`53.393`** | `Articolo ➔ Comma` | Contenimento strutturale |
| **`HA_ARTICOLO`** | **`25.803`** | `Norma ➔ Articolo` | Contenimento strutturale |
| **`CITA`** | **`21.341`** | `(Comma/Norma) ➔ Norma` | Rinvio normativo formale |
| **`CITA_ARTICOLO`** | **`6.617`** | `Comma ➔ Articolo` | Rinvio puntuale ad articolo specifico risolto |
| **`HA_ALLEGATO`** | **`385`** | `Norma ➔ Allegato` | Presenza di allegato tecnico |
| **TOTALE ARCHI** | **`107.539`** | | |

---

## 3. Pipeline di Acquisizione e Caricamento

```mermaid
flowchart TD
    subgraph S["1. Web Scraping Multi-Worker"]
        A["Portale Consiglio Grande e Generale"] --> B["01_scrape.py (4 Worker Paralleli)"]
        B --> C["data/raw/&lt;id&gt; (scheda.json + testo.pdf)"]
        B --> D["Atomic Index Merge (_indice.json)"]
    end

    subgraph P["2. Parsing Strutturale Deterministico"]
        C --> E["02_parse.py (PyMuPDF / regex)"]
        E --> F["data/parsed/&lt;id&gt;.json"]
        F --> G["Articoli, Commi, Rubriche, Citazioni puntuali"]
    end

    subgraph L["3. Knowledge Graph Loading"]
        F --> H["03_load.py"]
        H --> I["Vincoli e Indici di Unicità"]
        H --> J["MERGE Nodi Norma, Articolo, Comma, Allegato"]
        H --> K["Chunked Ingestion Relazioni CITA / CITA_ARTICOLO"]
        H --> M[("Neo4j Aura Graph Database")]
    end

    subgraph EMD["4. Semantic Indexing"]
        M --> N["07_embeddings.py"]
        N --> O["Voyage AI (voyage-4 1024d)"]
        O --> P2["c.embedding property sui nodi :Comma"]
        P2 --> M
    end
```

---

## 4. Indici e Vincoli di Integrità

```cypher
-- Vincoli di unicità (idempotenza assoluta del caricamento)
CREATE CONSTRAINT norma_id    FOR (n:Norma)    REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT articolo_id FOR (a:Articolo) REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT comma_id    FOR (c:Comma)    REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT allegato_id FOR (x:Allegato) REQUIRE x.id IS UNIQUE;

-- Indici Full-Text per ricerca lessicale italiana
CREATE FULLTEXT INDEX testo_normativo FOR (n:Comma|Articolo) ON EACH [n.testo, n.rubrica]
  OPTIONS {indexConfig: {`fulltext.analyzer`: 'italian'}};
CREATE FULLTEXT INDEX titoli_norme FOR (n:Norma) ON EACH [n.titolo];

-- Indice Vettoriale per ricerca semantica ibrida
VECTOR INDEX commi_vettoriale FOR (c:Comma) ON c.embedding    -- 1024 dimensioni (cosine)
```

---

## 5. Riconciliazione delle Anomalie Giuridiche Reali

1. **Gestione Duplicate/Novelle (`numerazioneAnomala`):**
   * Alcune leggi storiche contengono commi con lo stesso numero o derivanti da novelle legislative (es. due commi 2 in un articolo). Il loader non sovrascrive né perde testo: aggiunge un suffisso deterministico (`/c-2`, `/c-2-2`) e applica il flag `numerazioneAnomala = true`.
2. **Commi Impliciti (`commaImplicito`):**
   * Per le leggi storiche antecedenti al 2000 prive di commi numerati, il testo dell'articolo viene conservato in un comma implicito marcato con `commaImplicito = true`.
3. **Gestione Multi-Label Idempotente:**
   * L'assegnazione delle etichette specializzate (`:LeggeQualificata`, `:LeggeCostituzionale`, `:DecretoLegge`) avviene dopo la creazione del nodo base `(:Norma {id: $id})` tramite istruzioni `SET`, evitando `ConstraintError` su nodi precedentemente creati come stub.
