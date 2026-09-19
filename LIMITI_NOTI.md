# Limiti noti del parser — stato al 19/09/2026

Elenco dei problemi **non risolti** in questa sessione di lavoro su
`src/02_parse.py`. Ogni voce riporta l'impatto misurato sull'intero corpus
(11.134 documenti, letti da S3) e il motivo per cui il fix è stato rimandato.
I numeri vengono dai report in `data/` e dagli script in `scripts/`, non da
stime: dove un numero è incerto è detto esplicitamente.

Cosa è stato invece corretto: la formula di promulgazione (allegati assorbiti
come commi), la rubrica presunta, tre varianti di intestazione d'articolo, gli
id duplicati fra articoli, i tipi di citazione mancanti, le intestazioni
minuscole, le convenzioni nel dispositivo, le errata corrige e gli articoli di
una legge citata da una novella (P1, per la parte annunciata: punto 1). Vedi
`git log` sul branch `fix-parser`.

---

## 1. Citazioni senza riga di annuncio (residuo di P1)

**Impatto residuo**: 71 documenti dei 114 misurati.

**Risolto**: 44 documenti, 197 articoli inventati in meno — i 43 coperti fra
i 114, più DL-152-2023 che la misura non aveva visto. Nessun documento con
più articoli di prima, nessun carattere di testo perso, nessun id duplicato.
Commit: "Gli articoli di una legge citata non sono piu' articoli dell'atto
che la cita".

**Cos'è il residuo**: un atto che ne modifica un altro ne riporta gli
articoli, ma senza la riga che annuncia il testo sostituito ("è così
modificato:", "è così sostituito:", seguita da TITOLO/CAPO/ALLEGATO o
dall'intestazione citata). Senza quella riga non c'è niente da riconoscere
che distingua una citazione da una numerazione che salta per altri motivi, e
sono proprio quegli altri motivi ad avere generato i falsi positivi del
criterio precedente (vedi punti 10 e 11). Fra i non coperti c'è L-54-1974,
che era stato verificato a mano come caso vero: le leggi anteriori agli anni
'90 introducono il testo citato senza formula fissa.

**Perché rimandato**: il criterio per i casi non annunciati è "la numerazione
riprende più avanti da dove si era interrotta" (prova strutturale, 56
documenti). È forte ma richiede di guardare avanti nel documento e di
decidere cosa fare quando il rientro non arriva: il rischio è inghiottire
articoli veri fino in fondo al testo, che è esattamente quello che è successo
in prova su DD-19-2016 (otto articoli veri persi) prima di aggiungere il
controllo sulla struttura citata.

**Nota**: il testo non si perde comunque. Ogni articolo citato ha un id
proprio dal fix sugli id duplicati, quindi a valle nessun testo ne cancella
un altro.

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

## 10. Tabelle a colonne appiattite dall'estrazione

**Impatto**: accertato su DD-12-2017 (2 intestazioni, pagine 5 e 6). Non
misurato sul corpus.

**Cos'è**: l'Allegato A elenca le violazioni in una tabella — numero, legge,
articolo, comma. L'estrazione del testo appiattisce le colonne e la cella
"Art. 6" finisce su una riga da sola, dove il parser legge l'intestazione di
un articolo del decreto. Somiglia a P1 ma la causa è il layout, non una
citazione: non c'è nessuna riga di annuncio, quindi la sentinella del punto 1
non lo tocca — correttamente, perché quel criterio qui non c'entra.

**Perché rimandato**: prima va misurato quanti documenti hanno tabelle di
questa forma. Il riconoscimento richiede informazioni che le righe di testo
non hanno (le coordinate dei blocchi, che PyMuPDF può dare con
`get_text("dict")`), quindi è un lavoro a sé, non una regex in più.

## 11. Numerazione sbagliata nel testo originale

**Impatto**: accertato su L-52-1947 aprendo il PDF. Non misurato sul corpus:
non è distinguibile da un'estrazione difettosa se non a occhio.

**Cos'è**: nel testo di L-52-1947 "Art. 4." compare due volte di seguito e
l'articolo successivo è "Art. 6." — o la stampa originale ha sbagliato, o il
"5" è stato letto come "4". Sono articoli veri con un numero sbagliato: il
parser li tiene tutti, il secondo con l'id reso univoco (`/art-4-2`).

**Perché non risolvibile**: non c'è niente da riconoscere. Rinumerarli
d'ufficio significherebbe inventare un dato che nel documento non c'è, e le
citazioni in entrata che puntano all'articolo 5 di questa legge non hanno
comunque un bersaglio corretto a cui puntare. La cosa giusta è che l'anomalia
resti visibile: l'id reso univoco la segnala già.

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
