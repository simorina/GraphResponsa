# Dove il sistema è debole — grafo e agente, 18 settembre 2026

Analisi misurata sul grafo in produzione e sul codice dell'agente, dopo i
lavori del 16–18 settembre. Ogni punto porta il numero che lo dimostra, cosa
significa per chi usa il servizio e cosa costerebbe rimediare.

Il sistema oggi contiene **11.110 atti** dal 1599 al 2026, 77.387 articoli,
177.369 commi, 68.267 citazioni. Le debolezze non stanno nella quantità.

---

## Il quadro in una riga

| | |
|---|---|
| **La debolezza principale** | Il grafo sa *cosa dice* una norma, non *se vale ancora* |
| **La seconda** | Prima del 2000 il testo è poco strutturato: articoli senza rubrica, articoli non divisi in commi |
| **La terza** | Quando non trova, l'agente insiste fino a esaurire i passi invece di dichiarare il limite |

---

## 1. Il grafo

### 1.1 La vigenza: il buco strutturale

| Segnale di vigenza | Copertura |
|---|---|
| Atti marcati abrogati | 528 su 11.110 (**4,8%**) |
| Atti con la data di entrata in vigore | 3.624 su 11.110 (**33%**) |
| Articoli con il testo aggiornato alle modifiche | 781 (**3 raccolte coordinate**) |
| Atti di cui il grafo traccia le modifiche ricevute | **19** |

Le abrogazioni si riconoscono solo dove una clausola le dichiara per esteso, e
il segnale è **solo positivo**: la presenza dell'arco autorizza a dire
"abrogata", l'assenza non autorizza a dire "vigente". Su 594 atti vivi citati
da almeno venti commi, il grafo non sa dire quali articoli siano stati
riscritti nel frattempo.

Dettagli che pesano:
- la data di entrata in vigore c'è **solo dal 2010** (2.022 atti su 2.051 negli
  anni '10, 30 su 1.616 negli anni 2000, zero prima del 1950): il portale la
  pubblica da allora;
- 117 atti abroganti sono a loro volta abrogati, quindi la catena va percorsa;
- il testo consolidato esiste per Codice Penale, Edilizia e Lavoro, e la
  raccolta sul Lavoro è ferma al 2018.

**Per un avvocato** significa che la risposta è affidabile sul *contenuto* e va
verificata sulla *vigenza*. È il limite da dichiarare a chi usa il servizio.

**Rimedio:** nessuno è a costo zero. Il più utile è costruire l'indice delle
novelle (chi ha modificato cosa) dai testi che dicono "l'articolo X è così
sostituito", che oggi copre 19 atti perché si appoggia alle sole raccolte
coordinate.

### 1.2 Gli allegati non entrano nel grafo

509 PDF, 860 MB, 27 atti. Il caso che blocca risposte: il **DD-1-2018**, il
decreto sulle violazioni amministrative oggi in vigore, ha nel grafo i suoi 6
articoli e **nessuna delle 44 tabelle** delle sanzioni; del **DD-12-2017** è
stato conservato l'Allegato A al posto del decreto, e le sue voci sono 30
articoli falsi (`art-166`, `art-222`…).

Il resto sono bilanci e rendiconti dello Stato (22 leggi, ~630 MB di tabelle
contabili) e la cartografia della L. 87/2026: materiale di scarso valore per
la ricerca giuridica.

**Rimedio:** caricare i 44+44 allegati delle violazioni e il DD-130-2008
(linee guida VIA). Il lettore di tabelle esiste già ed è stato provato su 33
decreti.

### 1.3 Il testo antico è strutturato male

| Epoca | Articoli senza rubrica | Commi non divisi (articolo in un comma solo) |
|---|---|---|
| prima del 1950 | 7.717 su 8.747 (**88%**) | 8.834 su 17.114 (51%) |
| 1950–1999 | 18.073 su 25.160 (**71%**) | 24.175 su 30.697 (**78%**) |
| dal 2000 | 12.154 su 43.480 (27%) | 12.550 su 129.558 (9%) |

Due conseguenze concrete:
- *«il secondo comma dell'art. 13 della L. 22/1974»* **non esiste come nodo**:
  l'articolo è un comma unico. Le clausole di abrogazione che nominano commi
  ordinali restano perciò inapplicabili (116 clausole misurate);
- la ricerca e l'accorpamento delle versioni si appoggiano alla rubrica, che
  per gli atti anteriori al 2000 manca nella maggior parte dei casi.

**Rimedio:** dividere in commi le leggi antiche nel parser. È il lavoro che
sblocca la famiglia più grande di clausole non lette.

### 1.4 Citazioni che non arrivano a destinazione

| | |
|---|---|
| Citazioni verso atti senza testo in archivio | 594 (verso 277 atti) |
| Atti fantasma che hanno un omonimo caricato | 194 |
| Citazioni che nominano un articolo senza agganciarlo | 251 |
| Voci delle tabelle che citano la legge ma non l'articolo | tutte |

Gli atti più citati e assenti: `DC-186-2021` (56 citazioni), `D-57-2000` (28,
ed è uno dei due atti che il controllo di numerazione rifiuta), `L-156-2011`
(21).

### 1.5 Lo stesso atto sotto due schede

428 atti hanno un gemello con id qualificato (`~`). Non sono doppioni — il
portale pubblica davvero due schede — ma competono nel recupero e l'agente
rischia di citare `L-0-1910~17009253` invece dell'id canonico. Da oggi il
recupero preferisce l'id canonico a parità di anno.

### 1.6 Cosa il grafo non contiene affatto

- **Giurisprudenza e prassi:** nessuna sentenza, nessuna circolare, nessun
  parere. Per un avvocato è metà del lavoro.
- **2.424 commi in inglese** (convenzioni internazionali) indicizzati con
  l'analizzatore italiano: la ricerca per parole su quei testi rende poco.
- 69 atti di tipo non definito, 43 senza data, 190 con meno di 200 caratteri di
  testo, 11 senza articoli, 117 commi di sole cifre, 3 caratteri illeggibili.

---

## 2. L'agente

### 2.1 Si blocca invece di dichiarare il limite

`MAX_GIRI = 12`, cioè 24 passi del grafo. Provato oggi sulla domanda *«l'art.
184 del Codice Penale è stato depenalizzato? quale sanzione si applica
oggi?»*: 15 strumenti, limite raggiunto, **nessuna risposta** e un messaggio
tecnico (`GraphRecursionError`) all'utente. Il motivo è la lacuna di 1.2: la
sanzione vigente sta in un allegato che non c'è, e l'agente continua a
cercarla.

Costo della domanda fallita: circa 0,2 $.

**Rimedio:** una regola nel prompt e un ultimo giro dedicato — quando i passi
stanno per finire, l'agente deve dire cosa ha trovato, cosa manca e perché,
invece di insistere. E il server non deve mostrare l'errore tecnico.

### 2.2 Nessuna prova automatica

Non esiste una suite di test né una CI. Le verifiche vivono negli `assert` di
import dei moduli (parser, citazioni, allegati, ricerca) e nei benchmark in
`scripts/`, che vanno lanciati a mano. Il benchmark delle risposte **non è
stato rifatto da quando il modello è Sonnet 5**.

Effetto misurato oggi: due modifiche alla ricerca sono state corrette *durante*
la prova, non prima. Senza prove sistematiche una regressione si scopre da una
risposta sbagliata a un utente.

### 2.3 Il costo per domanda è variabile e alto

| | |
|---|---|
| Media storica registrata (periodo Haiku) | 0,029 $ su 320 richieste |
| Domande misurate oggi con Sonnet 5 | 0,086 $ (trust), 0,138 $ (urbanistica), 0,267 $ (divieto di sosta) |
| Tetto per utente | 20 $ al mese |

Con Sonnet una consultazione impegnativa vale 100-150 mila token in ingresso.
Il tetto mensile si raggiunge intorno alle 100-200 domande. Non c'è un timeout
verso Anthropic né un allarme di spesa.

### 2.4 Il recupero dipende da segnali che mancano

Dopo le correzioni di oggi, su dodici domande da avvocato l'atto atteso è nei
primi tre in **10 casi su 12** (era 8). Restano due debolezze note:
- l'accorpamento delle versioni si appoggia alla **rubrica**, assente nel 71–88%
  degli articoli anteriori al 2000;
- il riordino con modello (`RERANK`) è **spento**;
- la variabilità fra esecuzioni non è nulla: a codice fermo la stessa domanda
  ogni tanto cambia risultati, per via del ramo vettoriale.

### 2.5 La verifica delle citazioni segnala ma non corregge

L'agente marca le citazioni che non ha potuto verificare
(`citazioniNonVerificate`): nella prova sul trust erano 3 — `144/2003`,
`165/2005`, `55/2003` — atti nominati nel testo di legge ma non presenti in
archivio con quell'id. Il segnale finisce nei log, non davanti all'utente.

### 2.6 Il prompt regge, ma è l'unico presidio

11.072 caratteri, sei sezioni, tutte le regole di condotta (citare solo ciò che
si è letto, dichiarare la vigenza, non dedurre). È scritto bene, ma è l'unico
posto dove queste regole vivono: nessun controllo a valle verifica che la
risposta le rispetti, tranne la verifica formale delle citazioni.

---

## 3. Da dove comincerei

| Intervento | Cosa risolve | Sforzo |
|---|---|---|
| **1. Allegati delle violazioni** (DD-1-2018, DD-12-2017) | Sblocca la famiglia "quale sanzione si applica oggi", che oggi non riceve risposta | Mezza giornata: il lettore esiste |
| **2. Ultimo giro dichiarativo** quando i passi finiscono | Niente più errori tecnici né domande che costano 0,2 $ e non rispondono | Poche ore |
| **3. Suite di prove e CI** sulle domande da avvocato | Le regressioni si vedono prima degli utenti | Uno o due giorni |
| **4. Indice delle novelle** esteso a tutto l'archivio | Attacca la debolezza principale: "questo articolo è ancora così?" | Settimane |
| **5. Commi delle leggi antiche** | Rende citabili i commi ordinali e sblocca 116 clausole di abrogazione | Giorni |
| **6. Giurisprudenza e prassi** | Copre la metà del lavoro di un avvocato che oggi manca | Progetto a sé, dipende dalle fonti |

I punti 1 e 2 sono contenuti e hanno effetto immediato. Il 4 è quello che
cambia davvero il valore del servizio per un professionista.
