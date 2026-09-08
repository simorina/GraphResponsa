# Architettura del Knowledge Graph

Grafo Neo4j della normativa della Repubblica di San Marino, costruito per essere
interrogato da un agente in modalità Graph RAG.

**Stato aggiornato:** **268.441 nodi**, **342.618 relazioni**, **11.134 norme con testo
integrale** su 11.136 scaricabili dal portale, distribuite su 16 tipologie di atto:
leggi, decreti in tutte le loro forme, regolamenti, notifiche, ordinanze, statuti,
errata corrige e verbali. Tutti i 180.932 commi hanno un embedding.

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
| **`:Comma`** | **`181.248`** | Unità atomica di testo, ricerca semantica e retrieval |
| **`:Articolo`** | **`74.742`** | Articoli con rubriche, capi e collocazione tematica |
| **`:Norma`** | **`12.248`** | Tutti gli atti normativi censiti: |
| ↳ *con testo integrale (`caricata: true`)* | *`11.134`* | *Su 11.136 scaricabili dal portale, 16 tipologie* |
| ↳ *stub citati (`caricata: false`)* | *`1.114`* | *Atti richiamati nei testi per tracciare i rinvii* |
| **`:Allegato`** | **`519`** | Tabelle, cartografie e allegati normativi |
| **TOTALE NODI** | **`268.757`** | |

### Relazioni (Archi)

| Relazione | Quantità | Direzione | Significato |
|---|---|---|---|
| **`HA_COMMA`** | **`181.248`** | `Articolo ➔ Comma` | Contenimento strutturale |
| **`HA_ARTICOLO`** | **`74.742`** | `Norma ➔ Articolo` | Contenimento strutturale |
| **`CITA`** | **`69.662`** | `(Comma/Norma) ➔ Norma` | Rinvio normativo formale |
| **`CITA_ARTICOLO`** | **`16.763`** | `Comma ➔ Articolo` | Rinvio puntuale ad articolo specifico risolto |
| **`HA_ALLEGATO`** | **`519`** | `Norma ➔ Allegato` | Presenza di allegato tecnico |
| **`ABROGA`** | **`189`** | `Norma ➔ Norma` | Abrogazione di un atto per intero, riconosciuta senza ambiguità |
| **TOTALE ARCHI** | **`343.123`** | | |

I `:Comma` erano 180.932 fino alla riparazione del parser: i **316 in più** sono
il testo che si perdeva su 312 articoli, dove il buffer della rubrica non si
chiudeva su `)` seguito da punteggiatura. Il conteggio dei nodi per etichetta
somma a 281.005 e non a 268.757 perché ogni `:Norma` ne porta due — quella
generica e quella del tipo (`:Legge`, `:DecretoDelegato`, e così via).

### Marcature di vigenza

Non sono relazioni ma proprietà sui nodi, ed è una scelta: la lettura le trova
sul nodo che ha già in mano, senza un `MATCH` in più su ogni ricerca.

| Proprietà | Su | Quantità | Significato |
|---|---|---:|---|
| `Norma.abrogata` / `abrogataDa` | `:Norma` | **279** | L'atto è caduto per intero |
| `Articolo.abrogato` / `abrogatoDa` | `:Articolo` | **49** | Articolo soppresso dentro un atto vivo |
| `Comma.abrogato` / `abrogatoDa` | `:Comma` | **26** | Comma soppresso dentro un atto vivo |

Le si ricalcola da zero a ogni esecuzione di `src/08_abrogazioni.py --scrivi`,
archi `ABROGA` compresi: senza cancellarli prima, un arco che smette di essere
riconosciuto sopravvive alla correzione del filtro che lo escludeva.

#### `ABROGA`, e perché è così piccolo

Nel corpus ci sono **1.728 commi** che contengono «è abrogato», «sono
abrogati» o «e' abrogato», e se ne modellano 189. Non è una svista: la forma più comune abroga
una **parte** — *«All'articolo 2 della Legge n.55/1994, il punto 8.0 è
abrogato»* — e leggerla come abrogazione dell'articolo 2 dichiarerebbe morta
una norma viva. In un archivio che deve dire a un cittadino se ha diritto a
qualcosa, quello è l'errore peggiore disponibile: gli errori di omissione
lasciano l'utente dov'era, questo gli nega un diritto che ha.

Si riconoscono perciò le sole forme che colpiscono un **atto intero** — `È
abrogata la Legge 27 ottobre 2004 n. 146`, `La Legge n.146/2004 è abrogata`,
`Sono abrogate la Legge n.97/1989 e la Legge n.99/1991` — scartando parti
d'atto, decorrenze differite a date future e clausole di salvezza. Il
riconoscimento porta le proprie prove in `src/08_abrogazioni.py`: se una
fallisce, lo script esce senza scrivere.

La marcatura effettiva non viene solo da lì. L'archivio di Stato segna da sé
gli atti caduti premettendo `ABROGATO - ` al titolo — **125 norme** — e i due
segnali sono in larga parte disgiunti, appena **9 in comune**: il titolo dice *che* un
atto è caduto, i commi dicono *da chi*. L'unione marca **279 norme** con
`Norma.abrogata`, e le 163 con attribuzione nota portano anche
`Norma.abrogataDa`.

Tre trappole di lettura sono costate care. La prima è l'apostrofo: gli atti
scrivono `E' abrogata` e `E’ abrogata` quanto `È abrogata`, e cercare la sola
forma accentata perdeva **412 commi su 1.728** — fra cui la L-145/2022, che
abroga la L-106/2009. Senza quella riga l'agente, richiesto della L-106/2009,
indicava come successore la L-107/2009: un atto anteriore, su un'altra materia.
La seconda è il tipo dell'atto, che va confrontato col **prefisso dell'id** e
non con `Norma.tipo`: quest'ultimo è scritto a mano e contiene *Decreto
Delagato*, *Decreto Delega5to*, *Decreto Conisliare*.

La terza è la **partizione in testa a un elenco**. Nel plurale la parola che
delimita il bersaglio compare una volta sola e governa tutto ciò che segue:
in *«Sono abrogate le disposizioni della Legge n.9/1960, della Legge
n.24/1972»* la seconda legge ha davanti un innocuo `, della `, e guardare solo
il tratto adiacente la marcava morta. Si scarta perciò l'elenco intero quando
una parola di partizione precede il primo atto nominato — e si perde qualche
bersaglio buono, come il decreto interamente abrogato in coda a *«Sono abrogati
i Capi I e VII del Decreto n.122 e il Decreto Delegato n.146»*. Vale la pena:
qui un falso positivo dichiara morta una legge viva. Nella stessa famiglia
rientrano le abbreviazioni `art.` e `artt.`, che gli atti usano più spesso della
forma per esteso.

#### Cosa `ABROGA` non copre, che è la parte più grande

Non si scandagliano le 12.248 norme chiedendosi per ciascuna se sia caduta:
l'informazione non sta nella norma morta, sta nell'atto che l'ha uccisa. Restano
fuori, in ordine di frequenza:

| Non coperto | Perché |
|---|---|
| **Forme illeggibili** — 719 commi su 1.728 | Bersagli impliciti, rinvii a «norme in contrasto», elenchi non strutturati |
| **Partizioni sotto il comma** — «la lettera d), comma 1, dell'articolo 3» | Il grafo non modella lettere e punti: non c'è nodo da marcare |
| **Abrogazione tacita** — una legge posteriore incompatibile con una anteriore, senza dirlo | Nessun metodo testuale può trovarla |

#### Il livello parziale: `Articolo.abrogato` e `Comma.abrogato`

Un articolo o un comma soppressi dentro una legge che per il resto vige sono il
caso più frequente e il più insidioso: l'atto risulta in vigore, il testo del
passo si legge intero e sensato, e **nulla in esso avverte che non vale più**.
L'archivio di Stato conserva gli atti come furono pubblicati e non li riscrive —
non è un testo consolidato — quindi in un testo vigente quell'articolo direbbe
«(Abrogato)», qui invece resta scritto per esteso. Verificato: su 74.742
articoli, **uno solo** ha la rubrica `(Abrogato)`.

Qui però il bersaglio non va indovinato: l'arco `CITA_ARTICOLO` esiste già e lo
indica, e resta da verificare che il numero scritto coincida con quello a cui
l'arco punta — su 35 coppie d'articolo, **zero discordanze**. Si marcano così
**49 articoli** e **26 commi**, con `abrogato` e `abrogatoDa`, esposti al
modello come `passoAbrogato`.

Il numero è piccolo perché solo **433 commi abroganti su 1.728** hanno un arco,
e di quelli la maggioranza scende ancora più in basso. Due trappole specifiche
di questo livello: *«è abrogato **e sostituito** dal seguente»* non è
un'abrogazione ma una novella — l'articolo resta, riscritto — e il divario fra
«articolo N» e «è abrogato» non deve **scavalcare un confine di frase**, perché
in *«…della Legge n.40/2014 e successive modifiche. 3 bis. E' abrogato…»*
l'espressione agganciava un verbo che apparteneva alla frase seguente.

**Il rischio non è l'arco sbagliato, è l'arco assente.** Con l'1,6% di
copertura, l'assenza del marchio non dimostra nulla, ma un indice rado invita a
leggerla come conferma di vigenza. Perciò il campo entra nel prompt come avviso
esclusivamente positivo: la presenza autorizza «è stata abrogata», l'assenza
non autorizza «risulta vigente», e le istruzioni lo vietano espressamente.

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

## 4. Gli Embedding: dove stanno e a cosa servono

### 4.1 Il problema che risolvono

L'indice full-text pesa le **parole**, non il **significato**. Un cittadino non
scrive «soggiorno culturale per giovani cittadini sammarinesi residenti
all'estero»: scrive «vacanza studio per figli di emigrati che vogliono imparare
la lingua». Le due frasi non condividono quasi nessuna parola, e per Lucene sono
estranee.

Gli embedding trasformano ogni testo in **1024 numeri**, disposti in modo che
frasi con lo stesso significato finiscano vicine nello spazio. Misurato sulle
frasi qui sopra:

| Confronto | Somiglianza coseno |
|---|---:|
| «soggiorno culturale... residenti all'estero» ⟷ «vacanza studio... figli di emigrati» | **0,778** |
| «soggiorno culturale... residenti all'estero» ⟷ «aliquote IGR e detrazioni» | 0,494 |

Nessuna parola in comune, ma i numeri sanno che parlano della stessa cosa.

### 4.2 Chi fa cosa

Tre componenti distinti, che non si parlano mai fra loro:

| Componente | Compito | Cosa NON fa |
|---|---|---|
| **Voyage AI** (`voyage-4`) | trasforma testo in 1024 numeri | non capisce di diritto, non scrive nulla, non vede mai la risposta |
| **Neo4j** | conserva quei numeri e trova i più vicini | non genera testo |
| **Claude** | legge i commi ripescati e scrive la risposta con le citazioni | non vede mai un vettore |

Anthropic non offre un'API di embedding, e non è una lacuna: comprimere un
significato in un punto dello spazio e ragionare su un testo sono due mestieri
diversi.

### 4.3 Dove risiedono fisicamente

**Dentro Neo4j, come proprietà dei nodi stessi.** Non esiste un archivio
vettoriale separato:

```
Comma.embedding      1024 float per comma      es. L-101-2025/art-1/c-1
180.932 commi        ~0,69 GB nell'istanza Aura
```

`07_embeddings.py` usa `from_existing_graph`: aggiunge la proprietà ai nodi
`:Comma` che già esistono, invece di duplicare i testi altrove. **Il grafo resta
uno solo.**

È questa scelta a rendere possibile la `retrieval_query` di `strumenti.py`, che
gira *dopo* il match vettoriale con `node` e `score` già disponibili e da lì
risale comma → articolo → norma. Ricerca semantica e navigazione del grafo
diventano **una query sola**. Con un database vettoriale separato servirebbero
due sistemi da tenere allineati, e ogni ricerca sarebbe due viaggi di rete.

### 4.4 Quando Voyage viene chiamato

Due momenti, di costo incomparabile:

| Momento | Volume | Costo | Frequenza |
|---|---|---|---|
| **Indicizzazione del corpus** | 17,8 M token per 180.932 commi | ~1,07 $ | una volta, poi solo per gli atti nuovi |
| **Ogni interrogazione** | ~20 token (la domanda) | frazioni di millesimo | a ogni `cerca_testo` |

L'ultima indicizzazione completa ha richiesto **97 minuti** per 128.613 commi.
L'account dispone di 200 milioni di token gratuiti sulla generazione 4, quindi
in pratica il costo è nullo.

### 4.5 Due trappole

**`voyage-law-2` non va usato.** Il nome promette il dominio giuridico, ma il
modello non è multilingue e su testi italiani rende meno di `voyage-4`, che è
generalista. È annotato anche in `07_embeddings.py`.

**Un comma senza embedding è quasi invisibile.** Non è semplicemente «meno
trovabile»: competendo solo sul ramo lessicale contro 180.000 altri commi, perde
sistematicamente contro documenti più lunghi che ripetono le stesse parole.
Verificato sul campo: prima dell'indicizzazione il Regolamento 10/2026 non usciva
nei primi risultati **nemmeno interrogandolo con le sue stesse parole**. Dopo,
compare in terza posizione. Per questo `07_embeddings.py` va rieseguito dopo ogni
caricamento: è idempotente e calcola solo i commi che non ce l'hanno.

---

## 5. Indici e Vincoli di Integrità

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
VECTOR INDEX commi_vettoriale FOR (c:Comma) ON c.embedding
-- configurazione effettiva in esercizio:
--   vector.dimensions           1024
--   vector.similarity_function  COSINE
--   vector.hnsw.m               16
--   vector.hnsw.ef_construction 100
--   vector.quantization.type    SCALAR   comprime i vettori in memoria: ricerca
--                                        piu' leggera, perdita di precisione
--                                        trascurabile su 181.000 commi
```

### 5.1 I due indici non coprono le stesse cose

E' un'asimmetria voluta, ma va conosciuta perche' condiziona chi legge i
risultati:

| | `testo_normativo` (Lucene) | `commi_vettoriale` | `rubriche_vettoriale` |
|---|---|---|---|
| etichette | `Comma` **e** `Articolo` | `Comma` | `Articolo` |
| proprieta' | `testo` e `rubrica` | `embedding` | `embedding` |
| cosa vettorializza | - | il testo del comma | titolo della norma + rubrica |
| trova per | parole esatte, flesse dall'analizzatore italiano | significato del contenuto | significato dell'argomento |

Un `:Articolo` ha un embedding **della propria rubrica**, non dei suoi commi: la
rubrica dice di cosa tratta l'articolo, i commi dicono cosa dispone.

Si vettorializza `titolo della norma + rubrica`, non la rubrica nuda: le rubriche
sono spesso una parola sola - «Destinatari», «Sanzioni», «Definizioni» - e da
sole darebbero un vettore ambiguo. Con il titolo davanti si collocano, che e'
anche il modo in cui un giurista le legge. Il testo dell'articolo non entra: e'
gia' coperto dagli embedding dei suoi commi.

Costo: 35.713 rubriche, ~425.000 token, **$0,025** con voyage-4, e ~140 MB in
piu' su Aura. Lo calcola `07b_embeddings_rubriche.py`, idempotente come il 07 e
da rieseguire insieme a quello dopo ogni caricamento.

**Prima che esistesse il terzo indice**, un `:Articolo` poteva entrare nei
risultati solo dal ramo lessicale, e questo imponeva un compromesso nella
fusione: alzando il peso lessicale si trovavano le rubriche ma tornavano i
risultati fuori tema agganciati da una parola comune. Il terzo indice ha tolto
il compromesso - vedi §4.2 dell'architettura dell'agente.

Le rubriche restano indicizzate perche' sono la riga piu' densa di senso di un
articolo (`(Incompatibilita' con altre cariche)`, `(Morte dell'assegnatario)`):
spesso dicono in cinque parole cio' che il comma dice in trecento.

Questa asimmetria ha prodotto il difetto di recupero piu' costoso del sistema.
La query di risalita apriva con `MATCH (art:Articolo)-[:HA_COMMA]->(node)`
obbligatorio: corretto per un `Comma`, ma su un nodo `:Articolo` non ha alcun
risultato, e quel nodo spariva dai risultati **senza errore**, proprio mentre
l'indice l'aveva classificato per primo. Corretto con `OPTIONAL MATCH` e
`coalesce` — vedi §4.1 dell'architettura dell'agente.

**Regola per chi scrive query su `testo_normativo`: non dare per scontato che
`node` sia un `Comma`.** Vale anche per le query diagnostiche in
`04_verify.cypher`.

---

## 6. Riconciliazione delle Anomalie Giuridiche Reali

1. **Gestione Duplicate/Novelle (`numerazioneAnomala`):**
   * Alcune leggi storiche contengono commi con lo stesso numero o derivanti da novelle legislative (es. due commi 2 in un articolo). Il loader non sovrascrive né perde testo: aggiunge un suffisso deterministico (`/c-2`, `/c-2-2`) e applica il flag `numerazioneAnomala = true`.
2. **Commi Impliciti (`commaImplicito`):**
   * Per le leggi storiche antecedenti al 2000 prive di commi numerati, il testo dell'articolo viene conservato in un comma implicito marcato con `commaImplicito = true`.
3. **Gestione Multi-Label Idempotente:**
   * L'assegnazione delle etichette specializzate (`:LeggeQualificata`, `:LeggeCostituzionale`, `:DecretoLegge`) avviene dopo la creazione del nodo base `(:Norma {id: $id})` tramite istruzioni `SET`, evitando `ConstraintError` su nodi precedentemente creati come stub.
