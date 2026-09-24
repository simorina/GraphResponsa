# Limiti noti del parser — stato al 24/09/2026, dopo l'integrazione su main

Elenco dei problemi **non risolti** in questa sessione di lavoro su
`src/02_parse.py`. Ogni voce riporta l'impatto misurato sull'intero corpus
(11.134 documenti, letti da S3) e il motivo per cui il fix è stato rimandato.
I numeri vengono dai report in `data/` e dagli script in `scripts/`, non da
stime: dove un numero è incerto è detto esplicitamente.

Cosa è stato invece corretto: la formula di promulgazione (allegati assorbiti
come commi), la rubrica presunta, tre varianti di intestazione d'articolo, gli
id duplicati fra articoli, i tipi di citazione mancanti, le intestazioni
minuscole, le convenzioni nel dispositivo, le errata corrige, gli articoli di
una legge citata da una novella (P1, per la parte annunciata: punto 1), gli
articoli "Art. 5-bis" con il trattino (1.2) e i commi con suffisso ordinale
(1.3). Vedi `git log` sul branch `fix-parser`.

Il 24/09 i fix sono stati portati su main, che nel frattempo aveva
riorganizzato allegati, articoli e commi (`src/articoli.py`, `src/commi.py`,
`src/allegati.py`). Come ogni fix e' stato adattato sta in
[REPORT_FIX_PARSER.md](REPORT_FIX_PARSER.md), sezione "Integrazione su main";
qui sotto le voci sono aggiornate a quello stato.

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
proprio (`articoli.py` rende univoci i numeri ripetuti con `-ripN`), quindi a
valle nessun testo ne cancella un altro.

Misura riproducibile: `.venv/Scripts/python.exe scripts/misura_citazioni_articoli.py`

## 2. L'indice iniziale genera articoli doppi, con id invertiti (P3)

**Impatto**: 9 documenti, 104 articoli doppi. I più colpiti: DD-192-2020 e
DD-9-2021 (33 ciascuno), L-59-2016 (21).

**In parte risolto su main**: `_indice_iniziale()` riconosce l'indice fatto di
intestazioni estese ("Art.1 - Principi", "Art.2 - ...") e lo lascia testo:
R-1-2004 passa da 1 articolo dedotto a 56, L-2-2015 non ha piu' doppioni.
Restano L-59-2016 (42 articoli `-rip2`) e DD-192-2020 (32), il cui indice usa
intestazioni semplici.

**Cos'è**: il sommario in testa al documento elenca "Articolo N" con la
rubrica, e il parser li prende per articoli. Peggio: le voci dell'indice
arrivano per prime e si tengono l'id canonico (`/art-1`), mentre gli articoli
veri finiscono con l'id reso univoco (`/art-1-rip2`). Le citazioni in entrata
puntano quindi alla voce d'indice.

**Perché rimandato**: il riconoscimento è misurato e affidabile, ma la
correzione richiede di scartare un blocco di testo all'inizio del documento,
il che è rischioso senza un controllo a campione più ampio.

## 3. Un articolo bis attaccato a un articolo citato (residuo di 1.2)

**Impatto residuo**: non misurato in modo esatto; il solo caso trovato
aprendo i documenti è L-24-2022, e lì non si verifica.

**Risolto**: `RE_ARTICOLO` accetta il trattino prima del suffisso. Sul corpus:
174 articoli veri in più in 92 documenti, e 24 articoli citati in meno in 15
(fra cui il "58 bis" di L-162-2004, che era il residuo noto del punto 1).
DD-103-2025, il caso peggiore del tentativo precedente, resta a 9 articoli:
i suoi 44-bis...44-septies stanno dentro un blocco citato.

**Cos'è il residuo**: un "Art. N-bis" viene accettato come articolo dell'atto
quando N è il numero in corso o il successivo. Se l'articolo N è a sua volta
un articolo citato che il punto 1 non ha riconosciuto — perché l'annuncio è
troppo lontano — allora anche il suo bis passa. In L-24-2022 il blocco
residuo (articoli 59-67 del codice di procedura penale) non contiene bis,
quindi il caso non si presenta, ma la strada esiste.

**Perché rimandato**: dipende interamente dal residuo del punto 1. Chiuso
quello, si chiude anche questo; una regola in più qui non aggiungerebbe
niente.

## 4. Commi con suffisso dentro un testo citato (residuo di 1.3)

**Risolto**: `RE_COMMA` e `RE_COMMA_INLINE` accettano il suffisso ordinale.
Sul corpus: 527 commi riconosciuti in 209 documenti, 50 commi oltre i 1.400
caratteri in meno. L-87-2026 passa da 240 a 245 commi, i cinque veri della
legge (l'atteso di `04_verify.py` è aggiornato).

**Cos'è il residuo**: dentro un blocco citato il comma con suffisso non apre
un comma — sarebbe la numerazione di un altro atto — e il suo testo resta nel
comma dell'articolo che cita. Su main il testo citato fra virgolette diventa
capoverso del comma che lo introduce (`commi.py`): dei 526 commi con suffisso
del branch, 129 sono capoversi (`1.cap5`), 368 restano commi con suffisso.
Un "1-bis)" citato senza virgolette non e' interrogabile come comma a se'.

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

**Risolto su main** per le intestazioni in sequenza: `RE_ARTICOLO_ESTESO`
accetta "Art. 1 (Prima seduta)", "Art.1 - Quorum", "- Art. 3 -" quando il
numero continua la numerazione. L-21-1981 passa da un articolo dedotto a 21
articoli. Resta fuori un'intestazione con la rubrica sulla riga che rompe la
sequenza. Il testo sotto e' la voce com'era prima dell'integrazione.

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

## 9. Campi nuovi: superato dall'integrazione su main

Sul branch `fix-parser` il parser produceva campi che `03_load.py` non
leggeva (`parte`, `idResoUnivoco`, `allegatoPostPromulgazione`,
`allegatoHaStrutturaPropria`, `convenzioneNelDispositivo`). Su main non ci
sono piu': gli allegati sono struttura del grafo (articoli `all-N` col campo
`allegato`, parti d'allegato `all1` nei commi), i numeri ripetuti diventano
`-ripN` con `numeroOriginale`, e 03 li carica gia'. Resta da decidere solo
`strutturaDedotta`, che 03 non porta nel grafo.

## 10. Tabelle a colonne appiattite dall'estrazione

**Impatto**: accertato su DD-12-2017 (2 intestazioni, pagine 5 e 6). Non
misurato sul corpus. Dopo l'integrazione DD-12-2017 ha 4 articoli (166, 6, 7,
13): il PDF comincia con la tabella, e la prima voce "art. 166", prima di ogni
articolo, resta un'intestazione come su main perche' il testo non finisca nel
preambolo. E' uno degli allegati delle violazioni che `allegati_tabellari()`
non legge ancora (docs/debolezze-2026-09-18.md, punto 1).

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
parser li tiene tutti, il secondo con l'id reso univoco (`/art-4-rip2`).

**Perché non risolvibile**: non c'è niente da riconoscere. Rinumerarli
d'ufficio significherebbe inventare un dato che nel documento non c'è, e le
citazioni in entrata che puntano all'articolo 5 di questa legge non hanno
comunque un bersaglio corretto a cui puntare. La cosa giusta è che l'anomalia
resti visibile: l'id reso univoco la segnala già.

## 12. L-108-2011 rifiutata da 03_load.py (nuovo, dall'integrazione)

**Impatto**: 1 documento. Su main veniva caricata; col parser integrato
`allegati.numerazione_patologica()` la rifiuta.

**Cos'è**: la legge scrive le intestazioni senza punto ("Art 1" ... "Art 18"),
e main ne leggeva 6. Col fix sulle varianti le legge tutte e 18. Dopo la
firma, pero', tre allegati sono intitolati "Art. 9" e uno "Art 7": sono i
moduli (registri di carico e scarico) allegati a quegli articoli, e main li
legge come articoli d'allegato fuori sequenza. Con l'art. 9 del corpo, "9"
ricorre quattro volte: oltre la soglia di tre, con allegati disordinati, e'
esattamente la forma che la regola di main rifiuta (la prova `_rimandi` in
`allegati.py`). Main la caricava solo perche' non vedeva l'art. 9.

**Perche' non toccato**: allentare la regola fa cadere la prova di main, e una
regola che riconosca "ALLEGATO N / Art. M" come etichetta sarebbe fatta su
misura per un documento (lo schema compare in 35 documenti, quasi tutti
tabelle di rimandi e statuti). Con `03_load.py --atti` e
`15_ricostruisci_articoli.py` un atto rifiutato resta nel grafo com'e';
sparirebbe solo con un caricamento da zero.

## 13. L'allegato dopo la firma resta un comma solo (residuo di CAUSA-A)

**Impatto**: 41 commi oltre i 100.000 caratteri (erano 42).

**Cos'è**: il testo dopo le firme non e' piu' coda dell'ultimo articolo:
apre una parte d'allegato (`c-all1`). Ma se l'allegato non ha struttura
propria resta un blocco unico: in DD-19-2019 la parte `all1` ha 1.018.401
caratteri. Il comma dispositivo e' pulito; la parte d'allegato la spezza
`19_frammenti.py` per la ricerca, e `leggi_articolo` la legge a porzioni.

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
