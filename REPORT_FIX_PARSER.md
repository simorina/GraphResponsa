# Fix al parser — branch `fix-parser`

Sessione di lavoro su `src/02_parse.py` (15–19 settembre 2026). Dieci
interventi, tutti misurati sull'intero corpus (11.134 documenti letti da S3 in
streaming, nessun file locale). Questo documento serve a chi deve **capire il
codice o risolvere un conflitto di merge**: per ogni fix ci sono il commit, il
problema con un esempio reale, la regola introdotta e il motivo per cui è
scritta così, le alternative scartate e l'impatto misurato.

Quello che resta aperto sta in [LIMITI_NOTI.md](LIMITI_NOTI.md), con i numeri
e il motivo del rinvio. Non ripetuto qui.

## Indice dei commit

| Commit | Titolo | File |
|---|---|---|
| `53e8ddb` | (pre-sessione) taglio alla formula di promulgazione — CAUSA-A | `src/02_parse.py`, `src/06_qa.py`, `scripts/baseline_from_s3.py` |
| `3212487` | La rubrica presunta inghiottiva l'apertura degli elenchi — 1.1 | `src/02_parse.py` |
| `d2a2bb2` | Script diagnostici (`diag_1_4.py`, `diag_varianti.py`) | `scripts/` |
| `2693f82` | Varianti di intestazione `Art 19`, `Art. 23 (23)`, `Art. 12°` | `src/02_parse.py` |
| `272d816` | Due atti nello stesso PDF si cancellavano gli articoli | `src/02_parse.py` |
| `c5182d2` | Script di misura (`misura_citazioni_articoli.py`, `sim_load.py`) | `scripts/` |
| `a536644` | Quattro fix: tipi di citazione, intestazioni minuscole, convenzioni, errata corrige | `src/02_parse.py` |
| `6828237` | Primo `LIMITI_NOTI.md` | `LIMITI_NOTI.md` |
| `cba315f` | Articoli citati da una novella — P1 | `src/02_parse.py` |
| `85228a1` | Limiti noti: P1, tabelle, numerazione rotta | `LIMITI_NOTI.md` |
| `9b330f9` | Commi con suffisso ordinale — 1.3 | `src/02_parse.py`, `src/04_verify.py` |
| `a535ffe` | `Art. 5-bis` con il trattino — 1.2 | `src/02_parse.py` |
| `4adf5c5` | Limiti noti: 1.2 e 1.3 | `LIMITI_NOTI.md` |

`src/03_load.py` **non è mai stato toccato**. Vedi in fondo la nota sul
caricamento.

## Come leggere il codice

Tutte le prove girano **all'import** del modulo (`_PROVE_*`), non c'è un
framework di test: `python -c "import importlib.util…"` su `src/02_parse.py`
fallisce subito se una regola si rompe. Ogni fix ha le sue prove accanto alla
funzione che introduce, con il nome del documento reale da cui viene il caso.
Se un merge tocca una di quelle liste, **la prova va tenuta**: è l'unico
posto dove è scritto perché quella riga esiste.

L'ordine delle definizioni nel file conta, perché le prove girano dove sono
scritte: `RE_ARTICOLO` → `RE_COMMA` → `RE_CITAZIONE` → `RE_BERSAGLIO` →
promulgazione → rubrica presunta → marcatore d'atto → intestazione minuscola →
testo citato → convenzione → errata corrige → `parse()` → prove a livello di
`parse()`.

---

## 1. CAUSA-A — l'allegato dopo la promulgazione veniva letto come dispositivo

**Commit** `53e8ddb` (fatto prima di questa sessione, incluso qui perché è il
fix che cambia i numeri di tutti gli altri) · `src/02_parse.py`

**Problema.** Dopo l'ultimo articolo l'atto chiude con "Dato dalla Nostra
Residenza… I CAPITANI REGGENTI". Ciò che segue non è dispositivo: è un
trattato, uno statuto societario, una tabella di bilancio. Il parser
continuava a leggere. DC-52-2016 assorbiva 20 articoli di un trattato ONU
come fossero suoi; in DD-19-2019 e DD-138-2018 il comma dell'ultimo articolo
vero superava il milione di caratteri.

**Regola.** `RE_PROMULGAZIONE` cerca `Dato/Data dalla Nostra Residenza … CAPITANI
REGGENTI` su una finestra di `FINESTRA_PROMULGAZIONE = 20` righe unite.
`_cerca_promulgazione()` usa **`match()` e non `search()`**: con `search()` la
finestra trovava la formula in anticipo e tagliava mentre la riga corrente era
ancora testo dell'ultimo articolo. Le 20 righe servono solo a tollerare che la
formula sia spezzata su più righe. Il testo dopo il taglio finisce in
`allegatoPostPromulgazione`, e `_ha_struttura_propria()` segnala in
`allegatoHaStrutturaPropria` se contiene a sua volta intestazioni `Art. N`.

**Scartato.** Strutturare l'allegato: sarebbero articoli di un *altro*
documento (vedi L-115-2019, il cui Allegato A è lo statuto di una società). Si
dichiara e basta. Restano fuori i decreti 1918–1943, che chiudono con una
formula diversa: meno di 30 casi, e allargare la regex costava falsi positivi.

**Impatto.** 2.967 documenti su 11.134 (26,7%). Articoli 80.032 → 67.063,
caratteri 110.139.077 → 64.769.109. Il calo è l'effetto voluto: quei 13.000
articoli e 45 milioni di caratteri non erano testo normativo sammarinese.

## 2. Fix 1.1 — la rubrica presunta si mangiava l'apertura degli elenchi

**Commit** `3212487` · `src/02_parse.py`

**Problema.** Dopo `Art. N`, una riga corta chiusa da un punto veniva presa per
rubrica. Il recupero a fine `parse()` la restituisce al testo **solo se
l'articolo è rimasto senza commi**: se altri commi arrivavano, quella riga
spariva. Esempi reali: `L'Art. 3 è così modificato:` e `Il cittadino ha
diritto:` (apertura di elenco), `È abrogata la Legge …` (frase).

**Regola.** `_puo_essere_rubrica(riga)`: al massimo 80 caratteri, deve finire
con `.` (quindi mai con i due punti) e non deve cominciare come una frase —
`RE_INCIPIT_FRASE` copre articoli determinativi, `l'`, `è/e'`, `non`, `sono`,
`ogni`. Una rubrica vera è `Giuramento.`, `Caccia vietata su terreno ricoperto
di neve.`.

**Nota per chi legge il diff.** Lo scenario descritto nella review originale
("rubrica presunta seguita da un comma numerato ≥ 2") **non esiste nel
corpus**: misurato, zero casi. Le cause vere sono le due sopra. Se qualcuno
riscrive questa regola partendo dalla review, ripeterà l'errore.

**Impatto.** Rubriche perse 3.177 → 792, documenti colpiti 1.183 → 113,
+149.158 caratteri di testo recuperati.

## 3. Varianti di intestazione d'articolo

**Commit** `2693f82` · `src/02_parse.py` (`RE_ARTICOLO`, `_PROVE_ARTICOLO`)

**Problema.** Tre grafie non aprivano un articolo: `Art 19` (senza punto, 151
righe in 99 documenti), `Art. 23 (23)` (richiamo di nota a piè di pagina),
`Art. 12°` (grado). Il testo dell'articolo finiva nel comma del precedente.

**Regola.** Nella regex: `\.?` dopo `Art`, `[°º]?` dopo il numero, `(?:\(\d+\))?`
per il richiamo di nota.

**Scartati, con il motivo.**
- **Trattino lungo finale** (`Articolo 9 –`): provato e ritirato. In L-59-2016
  quelle sono voci del sommario e creavano 42 doppioni. La prova negativa
  `("Articolo 9 –", None)` è lì per questo — non toglierla.
- **Trattino prima del suffisso** (`Art.1-bis`): rimandato allora perché
  avrebbe creato articoli spuri in 41 documenti; fatto dopo, quando il
  riconoscimento del testo citato ha reso sicuro accettarlo (§ 10).
- **Rubrica sulla stessa riga** (`Art. 14 CONTRIBUTO IN CONTO INTERESSI`):
  fuori scope, resta un limite noto.

**Impatto.** Articoli 67.063 → 67.306 (+243).

## 4. Id duplicati e secondo atto nello stesso PDF

**Commit** `272d816` · `src/02_parse.py`

**Problema.** Un solo PDF contiene spesso due atti (una Legge e il suo
Regolamento), e il secondo rinumera da 1. Gli articoli del secondo prendevano
gli stessi id del primo, e `03_load.py` fa `MERGE … SET`: **l'ultimo vince, in
silenzio**. In L-0-1910 i 22 articoli della Legge venivano cancellati dai 22
del Regolamento. Misurato: 486 id di articolo e 574 id di comma duplicati,
186.256 caratteri a rischio di sovrascrittura.

**Regola.** Due livelli, in questo ordine dentro `id_articolo(numero, i)`:
1. **Riconoscimento del secondo atto**: se l'id è già usato, `_marcatore_atto()`
   guarda fino a `FINESTRA_MARCATORE = 6` righe non vuote sopra l'intestazione
   cercando `RE_MARCATORE_ATTO` (regolamento, statuto, tariffa, allegato,
   tabella, convenzione, `parte N`, disposizioni transitorie). Se c'è, da lì in
   avanti gli articoli vanno in una **parte**: `L-0-1910/reg/art-1`, più il
   campo `parte` sull'articolo.
2. **Rete di sicurezza**: senza marcatore l'id viene comunque reso unico
   (`/art-1-2`) e l'articolo porta `idResoUnivoco: True`, che `main()` stampa a
   video documento per documento.

**Scelte di design, e perché.**
- **La parte è un segmento dell'id, non un `id_norma` nuovo.** Un id_norma
  diverso spezzerebbe la risoluzione delle citazioni in entrata, che puntano
  all'atto con il suo id d'archivio.
- **`CAPO` è deliberatamente fuori** da `RE_MARCATORE_ATTO`. Provato: in
  L-59-2016 e DD-192-2020 l'indice iniziale spingeva gli articoli **veri**
  dentro una parte, lasciando l'id canonico alle voci del sommario. La prova
  `R-0-1883: un capitolo che rinumera non e' un secondo atto` documenta la
  scelta.
- `struttura_dedotta.nuovo_comma()` ha lo stesso controllo sugli id: senza,
  D-122-1985 produceva 66 commi con lo stesso id.

**Impatto.** Id duplicati (articoli + commi) 1.060 → **0**. Secondo atto
riconosciuto in 19 documenti; 116 documenti (329 articoli) salvati dalla sola
rete di sicurezza; 2 documenti entrambi.

## 5. Fix A — tipi di citazione mai estratti (1.6)

**Commit** `a536644` · `RE_CITAZIONE`, `_PROVE_CITAZIONE`

**Problema.** `Statuto`, `Notifica`, `Ordinanza`, `Verbale`, `Errata Corrige`
mancavano dall'alternanza di `RE_CITAZIONE` pur essendo tipi che
`comune.PREFISSI` sa già tradurre in un id: quelle citazioni non diventavano
archi nel grafo.

**Regola.** Aggiunti all'alternanza. **L'ordine conta**: dal più specifico al
più generico, altrimenti `Decreto Legge n.89/2014` viene letto come `Legge
n.89/2014` e la citazione punta all'atto sbagliato. Le prove negative
(`lo statuto della societa' X n.5 del registro`) tengono fuori l'uso comune
della parola.

**Impatto.** +98 citazioni, 91 dei cinque tipi nuovi in 79 documenti. La
metrica `f_copertura_tipi_citazione` di `06_qa.py` resta a 321 perché usa una
regex più permissiva del parser (tollera 40 caratteri fra tipo e numero): non
è un fallimento del fix, è un limite dello strumento di misura.

## 6. Fix B — intestazione minuscola (P2b)

**Commit** `a536644` · `intestazione_articolo()`, `_PROVE_INTESTAZIONE`

**Problema.** `… di cui al successivo` / `articolo 20.` va a capo e la seconda
riga ha la forma di un'intestazione: nasceva un articolo inventato che
spezzava in due il comma in corso. DD-12-2017 ne aveva 27.

**Regola.** `intestazione_articolo(riga)` è `RE_ARTICOLO.match()` **più** il
vincolo che la riga cominci con la maiuscola. Da qui in avanti `parse()` chiama
sempre questa funzione, mai `RE_ARTICOLO` direttamente: è il punto unico dove
si decide se una riga apre un articolo.

**Impatto.** 85 documenti, nessun carattere perso (il testo resta nel comma).

## 7. Fix C — convenzione riportata nel dispositivo (P4)

**Commit** `a536644` · `inizio_convenzione()`, `_PROVE_CONVENZIONE`

**Problema.** Stessa famiglia di CAUSA-A, ma la convenzione sta **prima** della
promulgazione: un decreto di ratifica riporta il trattato per intero, con la
sua numerazione che riparte da `Art. 1`. X-3-1942 produceva 24 articoli, uno
solo dei quali suo.

**Regola.** Tre condizioni insieme, tutte necessarie: almeno
`MIN_ART_CONVENZIONE = 5` righe `Art…` prima della promulgazione, una
numerazione che **riparte da 1** dopo la prima intestazione, e fra le due una
frase che contenga sia `RE_RATIFICA` (ratifica / piena ed intera esecuzione /
recepimento) sia `RE_TRATTATO` (Convenzione, Trattato, Accordo, Protocollo,
Parti contraenti, Stati membri). Il testo va nel campo
`convenzioneNelDispositivo`.

**Correzione di una misura sbagliata.** La stima iniziale diceva "21 documenti
DC": era un artefatto di `scripts/diag_varianti.py`, che non applica il taglio
alla promulgazione sugli atti ad "Articolo unico". 17 di quei 21 avevano la
convenzione **dopo** la promulgazione, già gestita. I documenti veri sono 6.

**Impatto.** 6 documenti (X-3-1942, D-28-1924, D-9-1972, DR-12-1922,
DC-16-1918, DC-21-1914), 40.287 caratteri spostati nel campo dedicato.
X-3-1942 passa da 24 articoli a 1.

## 8. Fix D — l'errata corrige non ha articoli propri

**Commit** `a536644` · `e_errata_corrige()`, `_PROVE_ERRATA`

**Problema.** Un'errata corrige riporta l'articolo che corregge ("La
formulazione corretta dell'articolo 6 della Legge n.145/2003 è la seguente:
Art. 6 …"). Quel `Art. 6` diventava un articolo dell'errata corrige.

**Regola.** `e_errata_corrige(id_norma, meta)` guarda il **tipo** dell'atto
tramite `comune.PREFISSI` (`EC`) o il prefisso dell'id (`EC-`); in `parse()`,
se è un'errata corrige, nessuna riga apre un articolo e il testo passa da
`struttura_dedotta()`. È un guard di classe, non una regola di testo: vale per
tutte le errata corrige, non solo per le formule già viste.

**Impatto.** Errata corrige con articoli propri 31 → **0** (su 193 nel corpus).

## 9. P1 — gli articoli di una legge citata diventavano articoli propri

**Commit** `cba315f` · `src/02_parse.py`

**Problema.** Un atto che ne modifica un altro ne riporta il testo,
intestazioni comprese: `Il Titolo III della Legge 28 aprile 1999 n.53 è così
modificato:` e seguono `Art. 7` … `Art. 14`, che sono articoli della **legge
modificata**. L-162-2004 ne assorbiva 28 di due leggi diverse (il ventinovesimo, un
`58 bis`, e' caduto con il fix 1.2 del § 11), L-168-2005 32. Misurato: 287
intestazioni in 114 documenti.

**Come ci si è arrivati.** Prima di scrivere una riga ho scaricato otto PDF e
li ho letti: due casi ad alta confidenza, due mai verificati, i due falsi
positivi noti e due dubbi. Il segnale comune ai casi veri non era la citazione
generica, era **la riga di annuncio**.

**Regola**, in `righe_citate(righe)`:
1. `_teste_articolo()` ripercorre le intestazioni come le vede `parse()`
   (stessa funzione `intestazione_articolo`, stesso stop alla promulgazione).
2. Quando un'intestazione **rompe la sequenza**, `_inizio_citazione()` cerca
   nelle ultime `FINESTRA_ANNUNCIO = 12` righe non vuote — mai oltre
   l'intestazione precedente — una frase di `RE_ANNUNCIO_CITAZIONE` (`è così
   modificato`, `è sostituito`, `sono apportate le seguenti modifiche`, `dopo
   l'articolo N … è inserito`), seguita da un'apertura (`:` o virgolette) e poi
   da `RE_STRUTTURA_CITATA` (TITOLO, CAPO, SEZIONE, PARTE, LIBRO, ALLEGATO,
   TABELLA, `Art`) sulla stessa riga, sulla riga dopo, o — se non c'è altro —
   dall'intestazione stessa.
3. Il blocco va **dall'annuncio fino al rientro** sul numero che l'atto si
   aspettava, o fino alla fine del testo. `parse()` riceve l'insieme delle
   righe e lì dentro non riconosce **niente** come struttura propria.

**Perché ogni pezzo esiste** (ognuno viene da un caso rotto, con la prova
corrispondente):
- **Il criterio contestuale precedente è stato buttato.** Riconosceva una
  citazione qualsiasi nelle righe sopra, e scattava su tutti e quattro i casi
  in cui la numerazione salta per altri motivi: LC-41-2004 e LC-27-2004 (il PDF
  scrive `Art.l` con la elle al posto dell'uno, la sequenza parte da 2),
  L-5-1921 (un secondo atto stampato in nota a piè di pagina), L-52-1947 (due
  `Art. 4.` di seguito nell'originale). Sono le quattro prove negative di
  `_PROVE_CITATE`.
- **Serve l'apertura su una struttura.** Senza, DD-19-2016 apriva un blocco su
  `All'articolo 97, comma 1, … è aggiunto il seguente comma 1-bis):` — una
  citazione di *comma*, che non contiene articoli. Non arrivando mai il
  rientro, il blocco si mangiava otto articoli veri fino in fondo al
  documento. Prova: `l'annuncio di un comma non apre una citazione di
  articoli`.
- **Il blocco è un intervallo di righe, non le sole intestazioni.** Provata
  prima la versione che marcava la riga dell'intestazione: in L-168-2005 il
  `CAPO I` riportato dentro la citazione restava una partizione dell'atto,
  chiudeva l'articolo in corso, e il testo che seguiva non finiva più in
  nessun comma — **35.953 caratteri persi**. Per questo in `parse()` il
  controllo è `if i in citate: m_part, m_art = None, None`, partizioni
  comprese.
- **Il criterio "rientro" da solo non è implementato.** Era la prova
  strutturale più forte (56 documenti, 5 su 5 corretti a mano), ma guarda
  avanti nel documento e, quando il rientro non arriva, inghiotte tutto: il
  rischio è esattamente il danno di DD-19-2016. Resta nei limiti noti.

**Impatto.** 44 documenti, 197 articoli inventati in meno, 0 documenti con più
articoli, **0 caratteri persi**, 0 id duplicati, L-87-2026 invariato. Dei 114
documenti del pattern ne copre 43; il 44° (DL-152-2023) la misura non l'aveva
visto ed è un caso vero, verificato a mano. In 9 documenti il blocco arriva
fino in fondo senza rientro: ne ho aperti 7, tutti corretti (decreti di
ratifica e decreti consigliari il cui corpo è per intero testo altrui).

## 10. Fix 1.3 — commi con suffisso ordinale

**Commit** `9b330f9` · `src/02_parse.py`, `src/04_verify.py`

**Problema.** `RE_COMMA` e `RE_COMMA_INLINE` volevano cifre pure, quindi `1
bis.` e `2-ter.` restavano testo e il comma novellato si fondeva con quello
precedente. 572 occorrenze in 228 documenti.

**Regola.** `SUFFISSO_ORDINALE` (bis…decies) diventa un gruppo opzionale
preceduto da spazio o trattino, **solo se il suffisso c'è**: la forma semplice
`^(\d+)\.` resta identica a prima, così nessun documento cambia per caso.
`numero_comma(m)` compone `1-bis`, coerente con l'id degli articoli bis; l'id
del comma diventa `…/art-97/c-1-bis`.

**Attenzione al numero dei gruppi.** `RE_COMMA_INLINE` ora ha tre gruppi
(numero, suffisso, testo): il testo è `group(3)`, non più `group(2)`. Un merge
che ripristini `group(2)` metterebbe il suffisso al posto del testo del comma.

**Overlap con P1.** Dentro un blocco citato un comma con suffisso **non** apre
un comma: sarebbe la numerazione di un altro atto dentro questo articolo. I
commi semplici continuano a comportarsi come prima — è una scelta
conservativa, per non cambiare il comportamento esistente insieme al fix.
Prova: `il comma citato dentro una novella non diventa un comma di questo
atto`.

**Impatto.** 527 commi riconosciuti in 209 documenti, commi oltre i 1.400
caratteri 5.007 → 4.957, nessun articolo in più o in meno, nessun id
duplicato. Il testo "perso" (4.778 caratteri su 212 documenti) sono
esattamente le righe del marcatore, che ora sono struttura e non contenuto.

**L-87-2026 passa da 240 a 245 commi** ed è una correzione, non una
regressione: sono i cinque commi veri della legge (art. 52 comma 3-ter, art. 57
da 16-ter a 16-sexies) che prima si fondevano con il precedente. Titoli (8),
capi (18), articoli (60), commi vuoti (0), articoli senza commi (0) non
cambiano. L'atteso in `src/04_verify.py` è aggiornato **con il motivo scritto
accanto**: se qualcuno lo rimette a 240 il controllo fallirà.

## 11. Fix 1.2 — `Art. 5-bis` con il trattino

**Commit** `a535ffe` · `src/02_parse.py`

**Problema.** `RE_ARTICOLO` accettava `Art. 5 bis` ma non `Art. 5-bis`, che è
la grafia più usata: 341 intestazioni in 136 documenti restavano testo.

**Perché si poteva farlo solo adesso.** Il tentativo precedente era stato
ritirato: in una parte dei documenti quelle righe sono articoli **citati** da
una novella (`Dopo l'articolo 44 … è inserito: Art. 44-bis`), e diventavano
articoli propri — DD-103-2025 passava da 9 a 15. Con il riconoscimento del
testo citato (§ 9) quel caso è coperto: in DD-103-2025 i sei articoli
44-bis…44-septies stanno dentro il blocco annunciato da `è aggiunto il seguente
Titolo V-bis:`, e il documento resta a 9 articoli.

**Ma la sentinella di P1 da sola non basta**, e questa è la parte da capire
prima di toccare il codice. In L-24-2022 l'annuncio c'è (`Gli articoli da 53 a
58 del Capitolo VIII del codice di procedura penale sono sostituiti dai
seguenti:`) ma il primo bis arriva **trenta righe dopo**, perché l'articolo 53
citato per intero sta in mezzo: fuori dalla finestra di 12 righe. Allargare la
finestra avrebbe riportato i falsi positivi che la finestra serve a evitare.

**Regola aggiuntiva** (il ramo `elif suff:` in `righe_citate`): un `Art. N-bis`
è dell'atto solo se **N è il numero in corso o il successivo** — `Art. 3` e poi
`Art.3-bis` (DD-19-2016, articoli suoi: il comma che segue modifica un'altra
legge). Se la base è altrove, apre un blocco citato come gli altri. Le due
prove `l'articolo bis con la base lontana dalla sequenza e' citato lo stesso` e
`l'articolo bis che segue la propria base resta dell'atto` sono i due lati di
questa regola.

**Perché apre un blocco e non marca la sola riga.** Provata anche quella
versione: L-33-1988 perdeva 3.278 caratteri, perché il `TITOLO IV` riportato
dentro la citazione restava partizione dell'atto e chiudeva l'articolo in
corso. Stesso meccanismo di L-168-2005 al § 9. Aprendo il blocco, quel testo
non solo non si perde: se ne recuperano 1.535 caratteri che si perdevano
**anche prima** del fix.

**Impatto.** Articoli con suffisso 60 → 215: +174 articoli veri in 92
documenti, −24 articoli citati in 15 (fra cui il `58 bis` di L-162-2004, che
era un residuo dichiarato al § 9, e i dodici bis di L-24-2022, che perde anche
i cinque articoli plain già spuri prima). Nessun id duplicato, nessun testo
perso oltre alle righe di intestazione, L-87-2026 invariato. La metrica
`g_art_bis_non_risolti` passa da 341 a **0**.

Verificati a mano i recuperi su DD-33-2020, L-86-1974, DD-16-2017, DD-19-2016:
sono articoli propri, con la rubrica che dichiara la modifica.

---

## Numeri, dalla baseline del 15/09 a oggi

Tutte le colonne vengono da `scripts/baseline_from_s3.py` (parser + `06_qa.py`
sull'intero corpus, 11.134 documenti, 0 errori). I report stanno in `data/`.

| Metrica | 15/09 iniziale | dopo CAUSA-A | dopo 1.1 | dopo varianti | 17/09 (A–D, id univoci) | **19/09 finale (P1, 1.3, 1.2)** |
|---|---|---|---|---|---|---|
| Articoli | 80.032 | 67.063 | 67.063 | 67.306 | 67.118 | **67.071** |
| Caratteri di testo | 110.139.077 | 64.769.109 | 64.918.267 | 64.925.380 | 64.889.415 | **64.903.092** |
| Citazioni | 72.252 | 61.455 | 62.275 | 62.242 | 62.340 | **62.298** |
| Id duplicati (articoli + commi) | 1.060 | 1.060 | 1.060 | 1.060 | 0 | **0** |
| Documenti con rubrica persa | 2.220 | 1.183 | 113 | 113 | 108 | **107** |
| Rubriche perse | 4.632 | 3.177 | 792 | 795 | 785 | **784** |
| Commi oltre 1.400 caratteri | 8.967 | 4.954 | 4.979 | 4.982 | 4.974 | **4.927** |
| Documenti con commi lunghi | 3.100 | 2.257 | 2.266 | 2.267 | 2.259 | **2.243** |
| `Art. N-bis` non risolti | 341 | 341 | 341 | 341 | 341 | **0** |
| Commi `N bis` non risolti | 572 | 572 | 572 | 572 | 572 | **20** |
| Documenti con gap di sequenza > 20% | 172 | 438 | 438 | 426 | 409 | **414** |
| Documenti vuoti o quasi | 11 | 11 | 11 | 11 | 11 | **11** |
| Documenti a struttura dedotta | 689 | 689 | 689 | 684 | 715 | **717** |

**Tre numeri da leggere con attenzione.**

- **Articoli e caratteri calano dal 15/09**: è l'effetto voluto del taglio
  degli allegati (CAUSA-A). Il testo normativo vero è cresciuto: +149.158
  caratteri dalle rubriche, +243 articoli dalle varianti di intestazione,
  +174 dagli articoli bis.
- **I documenti con gap di sequenza salgono da 172 a 414**: non è un
  peggioramento. Prima gli articoli dell'allegato riempivano i buchi della
  numerazione e li mascheravano; ora i buchi sono visibili, ed è il segnale
  che serve per il lavoro sul punto 1 dei limiti noti.
- **Le citazioni passano da 62.340 a 62.298** (−42) pur avendo aggiunto cinque
  tipi: togliendo gli articoli citati cambiano i confini dei commi su cui gira
  l'estrazione, e qualche rinvio che prima veniva contato due volte ora è
  contato una. Il guadagno del fix sui tipi (+98) è misurato a parità di
  confini.

## Cosa resta aperto

[LIMITI_NOTI.md](LIMITI_NOTI.md), undici voci con impatto misurato e motivo del
rinvio. Le tre che pesano di più:

1. **Citazioni senza riga di annuncio** (71 documenti dei 114 di P1): la
   formula che introduce il testo citato non è riconoscibile, tipico degli atti
   anteriori agli anni '90.
2. **L'indice iniziale genera articoli doppi con id invertiti** (9 documenti,
   104 articoli): le voci del sommario si tengono l'id canonico e gli articoli
   veri finiscono con l'id reso univoco, quindi le citazioni in entrata
   puntano alla voce d'indice.
3. **Rubrica sulla stessa riga dell'intestazione**: il numero misurato (1.244
   righe in 77 documenti) è sovrastimato e va rifatto, perché lo script di
   misura non applica il taglio alla promulgazione.

Il documento riporta anche i **limiti degli strumenti di misura**: leggerli
prima di ripartire dai numeri della review originale, che in tre casi su tre
si sono rivelati gonfiati (104 documenti per il collasso strutturale, 2.220 per
le rubriche, 21 DC per le convenzioni).

## Nota sul caricamento nel grafo

`src/03_load.py` non è stato toccato in nessun commit. Il parser produce oggi
campi che il loader non legge:

| Campo | Significato | Va nel grafo? |
|---|---|---|
| `allegatoPostPromulgazione` | testo dopo la formula di promulgazione | **no**, non è dispositivo |
| `allegatoHaStrutturaPropria` | l'allegato ha articoli suoi | solo come segnale |
| `convenzioneNelDispositivo` | trattato riportato in un atto di ratifica | **no**, non è dispositivo |
| `parte` | l'articolo appartiene a un secondo atto nello stesso PDF | da decidere |
| `idResoUnivoco` | l'id era già usato ed è stato reso unico | da decidere: è un segnale di anomalia |
| `strutturaDedotta` | gli articoli sono inferiti, non letti dal testo | da decidere |

Oggi `prepara()` legge solo `partizioni`, `articoli` (con `commi` e
`citazioni`) e `citazioniPreambolo`: i campi degli allegati **non finiscono già
nel grafo**, ma per omissione, non per una scelta scritta. Prima del prossimo
caricamento vale la pena renderla esplicita.

## Rieseguire le misure

```
.venv/Scripts/python.exe scripts/baseline_from_s3.py            # parser + QA sull'intero corpus
.venv/Scripts/python.exe scripts/misura_citazioni_articoli.py   # pattern P1/P2/P3/P4
.venv/Scripts/python.exe scripts/sim_load.py L-0-1910           # semantica MERGE+SET, senza scrivere
.venv/Scripts/python.exe scripts/parse_to_s3.py --prefisso parsed_v2   # rigenera il JSON su S3
```

Serve `.env` con le credenziali AWS. Nessuno di questi script scrive nel grafo.
