# Limiti noti del parser — stato al 17/09/2026

Elenco dei problemi **non risolti** in questa sessione di lavoro su
`src/02_parse.py`. Ogni voce riporta l'impatto misurato sull'intero corpus
(11.134 documenti, letti da S3) e il motivo per cui il fix è stato rimandato.
I numeri vengono dai report in `data/` e dagli script in `scripts/`, non da
stime: dove un numero è incerto è detto esplicitamente.

Cosa è stato invece corretto: la formula di promulgazione (allegati assorbiti
come commi), la rubrica presunta, tre varianti di intestazione d'articolo, gli
id duplicati fra articoli, i tipi di citazione mancanti, le intestazioni
minuscole, le convenzioni nel dispositivo e le errata corrige. Vedi `git log`
sul branch `fix-parser`.

---

## 1. Articoli citati trattati come articoli propri (P1)

**Impatto**: 114 documenti, 287 intestazioni. Due livelli di certezza: 56
documenti (221 occorrenze) dove la numerazione riprende da dove si era
interrotta (prova strutturale forte), 58 documenti (66 occorrenze) dove la
sola prova è il contesto testuale.

**Cos'è**: un atto che modifica un'altra legge ne riporta gli articoli
("Dopo l'articolo 44 è inserito: Art. 44-bis…"), e quelle intestazioni
diventano articoli dell'atto che cita. Esempio: L-168-2005 assorbe gli
articoli 11–29 della Legge n.65/2000.

**Perché rimandato**: sul campione di 15 casi "solo contesto" ne sono emersi
2 falsi positivi (LC-41-2004 e LC-27-2004, due leggi costituzionali che
iniziano da "Art. 2" per un'intestazione non riconosciuta). Un fix
automatico richiede di distinguere i due livelli di prova e di gestire i
falsi positivi: troppo per il tempo disponibile, e il rischio è di perdere
articoli veri.

**Nota**: il testo non si perde più. Dal fix sugli id duplicati ogni articolo
citato ha un id proprio, quindi nessun testo viene sovrascritto a valle.

Misura riproducibile: `.venv/Scripts/python.exe scripts/misura_citazioni_articoli.py`

## 2. L'indice iniziale genera articoli doppi, con id invertiti (P3)

**Impatto**: 9 documenti, 104 articoli doppi. I più colpiti: DD-192-2020 e
DD-9-2021 (33 ciascuno), L-59-2016 (21).

**Cos'è**: il sommario in testa al documento elenca "Articolo N" con la
rubrica, e il parser li prende per articoli. Peggio: le voci dell'indice
arrivano per prime e si tengono l'id canonico (`/art-1`), mentre gli articoli
veri finiscono con l'id reso univoco (`/art-1-2`). Le citazioni in entrata
puntano quindi alla voce d'indice.

**Perché rimandato**: il riconoscimento è misurato e affidabile, ma la
correzione richiede di scartare un blocco di testo all'inizio del documento,
il che è rischioso senza un controllo a campione più ampio.

## 3. "Art. 5-bis" con il trattino non riconosciuto (1.2)

**Impatto**: 341 intestazioni in 136 documenti.

**Perché rimandato**: accettarlo recupera 186 articoli veri in 91 documenti,
ma in **41 documenti** le intestazioni con il trattino appartengono ad
articoli citati da una modifica ("Dopo l'articolo 44 è inserito: Art.
44-bis"), e diventerebbero articoli spuri: DD-103-2025 passerebbe da 9 a 15
articoli. Separare i due casi richiede il controllo sulla sequenza del
punto 1, quindi i due fix vanno fatti insieme.

## 4. "comma 5 bis" non riconosciuto (1.3)

**Impatto**: 572 occorrenze in 228 documenti. Il comma novellato si fonde con
il precedente.

**Perché rimandato**: mai affrontato in questa sessione. Stessa famiglia del
punto 3, e con lo stesso rischio: dentro una novella i "5 bis" citati non
sono commi dell'atto che li cita.

## 5. Collasso strutturale residuo (1.4)

**Impatto**: circa 11 documenti con collassi veri, da un campione, non da una
misura completa.

**Cos'è**: il riconoscimento degli articoli si interrompe a metà di un testo
legislativo vero, e il resto finisce in un unico comma lunghissimo.

**Perché rimandato**: la stima originale (104 documenti) si è rivelata
gonfiata: 43 casi erano già risolti dai fix di questa sessione e circa 50
erano falsi positivi del criterio di classificazione. Il numero di 11 va
confermato aprendo i PDF uno per uno.

## 6. Documenti vuoti o scansionati (1.5)

**Impatto**: 263 documenti sotto la soglia di testo per pagina, di cui 11 con
zero contenuto estratto.

**Cos'è**: PDF scansionati senza livello di testo, o estrazione fallita. Il
parser non solleva nessun errore e produce un JSON quasi vuoto.

**Perché rimandato**: non è un fix di regex. Serve un controllo di sanità
post-parse che confronti il testo estratto con il numero di pagine, e una
decisione su cosa fare dei documenti segnalati (scartarli, passarli a un OCR,
caricarli comunque marcati).

## 7. Statuti con un parser separato e più povero (1.7)

**Impatto**: 12 documenti (`S-*`).

**Cos'è**: `scripts/integra_tutti_i_12_statuti.py` produce dati più poveri di
`02_parse.py`: niente citazioni, un comma per riga, id in un formato diverso
(`_art{N}` invece di `/art-{N}`). `02_parse.py` salta apposta le cartelle
`S-*`, perché la loro struttura ("RUBRICA I." al posto di "Art. 1") non viene
riconosciuta.

**Perché rimandato**: è un progetto a sé, fuori dalla pipeline principale.

## 8. Rubrica sulla stessa riga dell'intestazione

**Impatto**: **numero da ricontrollare.** La misura dice 1.244 righe in 77
documenti, ma è sovrastimata: lo script `scripts/diag_varianti.py` non applica
il taglio alla promulgazione negli atti ad "Articolo unico", e ha quindi
contato anche gli articoli di convenzioni allegate che il parser esclude già
(almeno 17 documenti DC su 21 controllati). Prima di dimensionare il fix va
corretto lo script e rifatta la misura.

**Cos'è**: intestazioni come `Art. 14 CONTRIBUTO IN CONTO INTERESSI` o
`Articolo 59 – Denunce`, con la rubrica sulla stessa riga. `RE_ARTICOLO`
pretende che la riga finisca dopo il numero, quindi non le riconosce e il
testo dell'articolo finisce nel comma dell'articolo precedente.

**Perché rimandato**: è il fix più rischioso del gruppo, perché richiede di
separare rubrica e testo sulla stessa riga, e va misurato di nuovo.

## 9. Campi nuovi non ancora portati nel grafo

`02_parse.py` produce campi che `03_load.py` non legge, perché in questa
sessione il caricamento non è stato toccato per scelta:

| Campo | Significato |
|---|---|
| `parte` | l'articolo appartiene a un secondo atto nello stesso PDF (`reg`, `parte-2`, …) |
| `idResoUnivoco` | l'id era già usato ed è stato reso unico: da controllare |
| `allegatoPostPromulgazione` | testo dopo la formula di promulgazione |
| `allegatoHaStrutturaPropria` | l'allegato ha articoli suoi |
| `convenzioneNelDispositivo` | testo della convenzione riportata nell'atto di ratifica |
| `strutturaDedotta` | gli articoli sono stati inferiti, non letti dal testo |

**Da decidere quando si costruirà il caricamento sul grafo nuovo**: se
`parte` diventa una proprietà di `:Articolo`, se gli allegati diventano nodi
propri, e se i documenti con `idResoUnivoco` vanno caricati o segnalati.

**Nota sull'ambiente**: l'istanza Neo4j Aura indicata in `.env`
(`caf5539f.databases.neo4j.io`) non esiste più — il dominio non risolve.
Il grafo va ricostruito da zero su una nuova istanza.

---

## Limiti degli strumenti di misura

- `scripts/diag_varianti.py`: non taglia alla promulgazione quando il
  documento ha un solo "Articolo unico" (vedi punto 8). Da correggere prima
  di riusarlo.
- `src/06_qa.py`, metrica `d_rubrica_presunta`: conta come "persa" ogni
  rubrica presunta rimasta rubrica, comprese quelle vere. Il valore residuo
  (785 occorrenze in 108 documenti) è quindi un tetto massimo, non una
  perdita.
- `src/06_qa.py`, metrica `citazioni_tipi_mancanti_stimate`: usa una regex
  più permissiva di `RE_CITAZIONE` (tollera fino a 40 caratteri fra il tipo e
  il numero), quindi resta a 321 anche dopo il fix dei tipi mancanti. Il
  guadagno reale misurato è +98 citazioni.
- `scripts/riclassifica_1_4_e_problema9.py`: il criterio "causa B" conta
  anche le intestazioni già riconosciute, e produce quasi solo falsi
  positivi. Usare `scripts/diag_1_4.py` al suo posto.
