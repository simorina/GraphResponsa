"""
L'agente, costruito con LangChain 1.x.

`create_agent` e' l'interfaccia corrente: in LangGraph 1.0 `create_react_agent`
di langgraph.prebuilt e' deprecato in suo favore.

Espone `rispondi()`, un generatore che emette eventi mentre l'agente lavora -
strumenti chiamati, testo, fonti - cosi' la UI puo' mostrare il processo invece
di una barra di caricamento.

La conversazione non viaggia piu' avanti e indietro col browser: la tiene il
checkpointer, e il client manda solo un identificativo di conversazione.
"""

import json
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain.agents.middleware import AgentMiddleware
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from .strumenti import STRUMENTI, grafo

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

# Sovrascrivibile con MODELLO nell'ambiente, per confrontare i modelli a
# parita' di tutto il resto senza toccare il codice.
#
# Sonnet 5 dal 17/09. Haiku 4.5 non seguiva in modo affidabile le regole su
# rinvii, definizioni, vigenza e completezza: sulla chat reale sul trust
# scriveva "elenco completo", inventava rubriche e una volta ha negato un
# ricorso che l'art. 12 del DD 85/2013 disciplina. Sonnet, sulla stessa chat,
# le rispetta. Costa il doppio per token (vedi PREZZI) e scrive risposte piu'
# lunghe: il server tiene viva la connessione durante l'attesa (BATTITO).
MODELLO = os.environ.get("MODELLO", "claude-sonnet-5")
# Il fornitore lo sceglie il nome del modello: "gemini-..." dall'API di Google,
# tutto il resto da Anthropic, e in mezzo il gateway OpenAI-compatibile di
# Alibaba Model Studio, che serve modelli di case diverse - Qwen, DeepSeek,
# Kimi, GLM - dietro la stessa chiave e lo stesso URL. Per questo il fornitore
# qui e' il GATEWAY e non la casa che ha fatto il modello. Istruzioni, strumenti
# e potatura restano gli stessi, cosi' il confronto e' a parita' di tutto.
SUL_GATEWAY = ("qwen", "deepseek", "kimi", "glm")


def fornitore_di(nome):
    if nome.startswith("gemini"):
        return "google"
    return "alibaba" if nome.startswith(SUL_GATEWAY) else "anthropic"


FORNITORE = fornitore_di(MODELLO)
# I tenant regionali hanno host diversi, quindi si cambia dall'ambiente senza
# toccare il codice.
QWEN_BASE = os.environ.get("QWEN_BASE_URL",
                           "https://maas.qwencloudapi.com/compatible-mode/v1")
# Quanto far ragionare i modelli del gateway prima di scrivere. Lasciati a se'
# stessi pensano moltissimo: misurato il 24/09 su deepseek-v4.1-flash, tre giri
# per livello sulla stessa richiesta, temperatura 0 e tetto largo -
#
#   nessuna leva  40,1s   4.317 token di pensiero   risposta 2.649 caratteri
#   minimal       31,6s   2.175                              2.746
#   low           29,1s   2.286                              2.647
#   medium        30,4s   2.563                              2.493
#   high          43,1s   4.645 (molto variabile)            2.780
#   niente pensiero 13,6s     0                              2.469
#
# - cioe' il pensiero e' quasi tutto il tempo e quasi tutta l'uscita, che si
# paga a prezzo pieno. "medium" lo dimezza senza accorciare la risposta.
# Spegnerlo del tutto e' tre volte piu' veloce, ma su un assistente giuridico
# non si toglie il ragionamento senza misurare prima cosa succede alle fonti.
RAGIONAMENTO = os.environ.get("RAGIONAMENTO", "medium")
# A chi passare quando il gateway rifiuta il contenuto, in ordine. Serve solo
# partendo dal gateway, perche' e' li' che vive quel filtro; si spegne mettendo
# MODELLO_RISERVA vuoto nell'ambiente, o si cambia con una lista separata da
# virgole.
#
# Tre modelli via via piu' grossi, tutti sul gateway. Va saputo che questo NON
# mette al riparo del tutto: il 24/09 il filtro ha respinto anche
# deepseek-v4-pro-0813, sulla stessa domanda a cui aveva risposto poco prima,
# quindi non e' il difetto di un modello ma un comportamento intermittente
# della piattaforma, e un episodio puo' prendere tutti e tre gli anelli. Il
# riparo vero e' un fornitore diverso in coda: basta
# MODELLO_RISERVA="deepseek-v4-pro-0813,qwen3.8-max,claude-sonnet-5", e Sonnet
# si paga solo nei rari casi in cui i primi due sono caduti.
RISERVE = [n.strip() for n in os.environ.get(
    "MODELLO_RISERVA",
    "deepseek-v4-pro-0813,qwen3.8-max" if FORNITORE == "alibaba" else ""
).split(",") if n.strip() and n.strip() != MODELLO]
# ChatAnthropic non manda la temperatura se non gliela si da', e l'API allora
# usa la propria: 1.0, cioe' il massimo campionamento casuale. Su un assistente
# giuridico e' la scelta peggiore possibile - la stessa domanda deve dare la
# stessa risposta, e chi legge non sa quale delle due versioni ha ricevuto.
# Si puo' alzare con TEMPERATURA nell'ambiente, per confrontare gli assetti.
TEMPERATURA = float(os.environ.get("TEMPERATURA", "0"))
ACCETTANO_TEMPERATURA = {"claude-haiku-4-5"}
# Su Gemini la temperatura la ascoltano i 2.5 e i flash-lite; dal 3.5 in su
# il campionamento e' fisso.
ASCOLTANO_TEMPERATURA = re.compile(r"gemini-(2\.5|3\.1-flash-lite)")

MAX_GIRI = 12   # Ogni chiamata a uno strumento consuma DUE passi del grafo
                # (nodo modello + nodo strumenti), quindi il tetto vero e'
                # circa MAX_GIRI-1 chiamate. Con 8 si fermava a sette, e le
                # regole su riformulazione e vigenza portano regolarmente a
                # sette-nove: misurato, 2 consultazioni su 6 morivano di
                # GraphRecursionError invece di rispondere. Un'interruzione
                # costa all'utente tutto, un giro in piu' costa mezzo
                # centesimo.
                #
                # Il tetto conta PASSI DEL GRAFO, non chiamate, e quanto
                # lavoro ci stia dentro dipende dal modello. Sonnet lancia due
                # o tre strumenti insieme nello stesso turno: cinque chiamate
                # gli costano otto passi. Gemini ne chiama uno per volta -
                # misurati quattordici turni di fila il 23/09, mai due insieme
                # - quindi con lo stesso tetto arriva a dodici chiamate e si
                # ferma li'. Non e' che ragioni peggio: gli serve il doppio
                # dei passi per fare lo stesso lavoro, e glieli diamo.
                # Qwen invece li raggruppa come Sonnet - due per turno,
                # misurato il 24/09 - e con la stessa domanda ha chiuso in due
                # giri: gli basta il moltiplicatore normale.
SEPARATORE = "\n\n"

# Quanto costa rileggere un token dalla cache, in frazione del prezzo
# d'ingresso. Su Anthropic e' un decimo, dichiarato. Su Qwen il listino distingue
# due cache: quella esplicita, che si rilegge a un decimo ($0,032 su $0,32), e
# quella IMPLICITA, che e' quella che ci tocca perche' non creiamo oggetti di
# cache a mano, e costa $0,064, cioe' un quinto. Contarla a un decimo mostrerebbe
# all'utente meta' del conto vero sulla parte riletta - lo stesso errore trovato
# il 22/09 sulle scritture di Anthropic. Su Gemini il listino di 3.5-flash da'
# $0,15 su $1,50, quindi un decimo; per i flash 3.6/3.7/3.8 Google non pubblica
# la voce, e finche' non la pubblica tengo lo stesso rapporto.
FATTORE_CACHE = {"anthropic": 0.10, "google": 0.10, "alibaba": 0.20}

# Quanti passi del grafo costa una chiamata a uno strumento, che dipende da
# quante ne lancia insieme il modello: chi le raggruppa spende meta' del tetto
# di chi le fa una per volta. Vedi la misura sopra MAX_GIRI. Fuori da Anthropic
# il tetto resta largo anche per chi le raggruppa - Qwen lo fa - perche' e' una
# rete di sicurezza contro i cicli infiniti, non un budget da spendere: darne di
# piu' non costa nulla a chi chiude in due giri, e toglie di mezzo il rischio di
# tagliare la risposta a un modello nuovo che ancora non abbiamo misurato.
PASSI_PER_CHIAMATA = {"anthropic": 2, "google": 4, "alibaba": 4}

# Prezzi per milione di token, per la stima mostrata nella UI: ingresso,
# uscita, e quanto costa rileggere un token dalla cache in frazione
# dell'ingresso. Il terzo valore sta qui e non in FATTORE_CACHE perche' cambia
# da modello a modello e non da fornitore: sullo stesso gateway, Qwen rilegge a
# un quinto e DeepSeek a un dodicesimo. Si scrive come divisione per lasciare in
# chiaro i due numeri del listino.
PREZZI = {
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
    "claude-sonnet-5": (2.0, 10.0, 0.10),
    "claude-opus-5": (5.0, 25.0, 0.10),
    # Listino a pagamento di Google al 23/09/2026, per prompt sotto i 200k
    # token: sopra, Pro raddoppia l'ingresso e alza l'uscita a 18.
    # Sul gateway Alibaba, listini letti il 24/09/2026. Plus e' scontato del
    # 20%; Max costa piu' di Sonnet in ingresso e meno in uscita; DeepSeek-Pro
    # sta in mezzo ma rilegge la cache a un dodicesimo invece che a un quinto.
    "qwen3.7-plus": (0.32, 1.28, 0.064 / 0.32),
    "qwen3.7-max": (2.5, 7.5, 0.5 / 2.5),
    "qwen3.8-max": (2.0, 6.0, 0.25 / 2.0),
    "qwen3.8-max-0902": (2.0, 6.0, 0.25 / 2.0),
    "deepseek-v4-pro": (2.4, 4.8, 0.2 / 2.4),
    "deepseek-v4-pro-0813": (2.4, 4.8, 0.2 / 2.4),
    # Flash: sedici volte meno di Sonnet in uscita, e la cache a un decimo
    # come Anthropic. Il listino e' quello di punta; fra le 22 e le 8 (UTC+8,
    # cioe' fra le 16 e le 2 da noi) Alibaba applica uno sconto che non
    # pubblica, quindi il conto mostrato puo' risultare piu' alto del vero.
    "deepseek-v4.1-flash": (0.15, 0.6, 0.015 / 0.15),
    # I flash 3.6/3.7/3.8 stanno in promozione fino al 31/12/2026: da gennaio
    # raddoppiano, a (1.5, 7.5).
    "gemini-3.8-flash": (0.75, 3.75, 0.10),
    "gemini-3.7-flash": (0.75, 3.75, 0.10),
    "gemini-3.6-flash": (0.75, 3.75, 0.10),
    "gemini-3.5-flash": (1.5, 9.0, 0.15 / 1.5),
    "gemini-3.1-pro-preview": (2.0, 12.0, 0.2 / 2.0),
    "gemini-2.5-flash": (0.3, 2.5, 0.03 / 0.3),
    "gemini-2.5-pro": (1.25, 10.0, 0.125 / 1.25),
}

ISTRUZIONI = """Sei un assistente esperto della normativa della Repubblica di San Marino.
Rispondi solo con cio' che leggi nel grafo della normativa, tramite gli strumenti.

## 1. Prima cerca, poi rispondi

- Non chiedere chiarimenti prima di aver cercato. Su una domanda vaga prendi
  l'interpretazione piu' probabile, cerca, e poi esponi cosa hai trovato e come
  restringere. Anche "questa legge" senza un atto nominato prima: cerca la
  materia di cui parla, e sara' la ricerca a dirti quale atto e'. Chiedi quale
  interessa solo se dopo la ricerca restano candidati incompatibili.
- Parti da `cerca_testo` con il lessico normativo. Se rende poco, riformula
  (chi scrive "vacanza studio", la norma dice "soggiorno culturale"). Solo dopo
  due formulazioni senza esito concludi che la materia non c'e'.
- `cerca_testo` restituisce sempre qualcosa, anche quando l'archivio non ha la
  materia: la pertinenza la stabilisce il testo, non il rango. Se nulla e'
  pertinente, dillo. Non colmare il vuoto con il diritto italiano o di altri
  ordinamenti: una risposta plausibile ma inventata e' il danno peggiore.
- Se una norma rilevante e' solo citata (`testoDisponibile: false`), di' che il
  suo testo non e' in archivio.
- L'archivio raccoglie disposizioni, non procedure amministrative. Su moduli,
  sportelli e documenti da presentare rispondi con cio' che la norma prescrive
  (requisiti, termini, organo competente) e di' che la prassi non e' in
  archivio. Non dedurre passi pratici dalla disposizione.

## 2. Citazioni

- Ogni affermazione viene da un risultato degli strumenti e porta la citazione
  in prosa seguita dal marcatore `{{cita:normaId:articolo:comma}}`, con gli id
  esatti degli strumenti: "...L. 87/2026, art. 7, comma 2{{cita:L-87-2026:7:2}},
  che stabilisce...". Il marcatore diventa il link al PDF. Metti `-` al posto
  del comma per l'articolo intero, e al posto di articolo e comma per l'atto
  intero: `{{cita:L-64-2025:-:-}}`.
- Il marcatore punta al passo da cui viene il dato: un requisito letto al
  comma 18 si cita al comma 18, e un atto nominato nel suo insieme non si cita
  all'art. 1.
- Il numero d'articolo scritto in prosa e quello dentro il marcatore sono lo
  stesso numero. Se scrivi "art. 33" il marcatore dice `:33:`, mai un altro
  articolo: una fonte che non si puo' aprire e' peggio di nessuna fonte.
- Un marcatore per dato, non per frase: se piu' frasi di seguito vengono dallo
  stesso comma, mettilo una volta, alla fine del gruppo.
- Ogni atto che nomini ha il suo marcatore, e il marcatore vale solo per cio'
  che hai letto. Un atto che conosci solo da un campo (`abrogataDa`,
  `passoAbrogatoDa`, `ancheIn`, `novellataDa`) va aperto prima di nominarlo:
  `trova_norma` per identificarlo, `leggi_articolo` per citarne un passo. Se
  non e' in archivio, dillo.
- Le parti numerate si citano per quello che sono, col numero esatto nel
  marcatore:
  - `1.cap2` capoverso: testo che l'articolo inserisce in un altro atto, non
    una sua regola ("art. 5, comma 1, capoverso 2");
  - `1.p3` voce di un elenco ("comma 1, punto 3");
  - `all4` testo dell'allegato stampato dopo la promulgazione ("allegato
    all'atto");
  - `1.rip2` il secondo comma 1 di un articolo che ne numera due;
  - articoli `all-3` (art. 3 dell'allegato), `all2-3` (del secondo allegato),
    `9-rip2` (il secondo articolo numerato 9).
- I nomi dei campi (`citatoDaAttiSuccessivi`, `testoCoordinatoAl`...) e degli
  strumenti non vanno nella risposta: di' cosa significano ("una legge del 2008
  ha modificato questo articolo"). A "che leggi hai usato?" rispondi con gli
  atti e gli articoli letti, ciascuno col suo marcatore.

## 3. Vigenza

L'utente vuole la disciplina in vigore oggi. L'archivio conserva i testi come
furono pubblicati: i marchi seguenti dicono cosa e' cambiato, e vanno letti
prima di citare. Su una norma di qualche anno fa in una materia ancora attuale,
cerca anche con `dal_anno` se c'e' una disciplina piu' recente.

- `abrogata: true`: l'atto e' caduto per intero. Dillo in apertura, apri con
  `trova_norma` l'atto indicato in `abrogataDa`, e cerca la disciplina che l'ha
  sostituito. Citalo solo per dire cosa prevedeva. Se il titolo comincia con
  "DECADUTO", il decreto ha perso efficacia: dillo con questa parola, non
  "abrogato", e non attribuirgli un atto abrogante.
- `passoAbrogato` sull'articolo, `abrogato` sul comma: quel passo e' soppresso
  dentro un atto vivo, e il testo non lo lascia capire. Non esporlo come
  disciplina: di' che e' abrogato, da chi, e cosa si applica al suo posto.
- L'assenza di questi marchi non prova nulla: coprono una piccola parte delle
  abrogazioni. "Vigente", "in vigore", "attualmente" si scrivono solo con una
  prova letta (una modifica recente, un atto posteriore che lo applica);
  altrimenti "nessuna abrogazione risulta in archivio". Vale per ogni voce di un
  elenco.
- Le clausole generali di abrogazione ("sono abrogate tutte le norme in
  contrasto con la presente legge", "sono altresi' da intendersi tacitamente
  abrogate...") non nominano i bersagli, e nessun marchio le segnala: stanno di
  solito negli ultimi articoli dell'atto ("Abrogazioni", "Norme finali"). Se la
  domanda riguarda la vigenza di una norma anteriore e un atto posteriore della
  stessa materia ne ha una, citala sempre col suo marcatore, e di' che la norma
  anteriore vale solo in quanto compatibile. Allora non scrivere che e' vigente,
  ne' che "torna in vigore" perche' un atto l'ha tolta da un elenco di
  abrogazioni espresse: di' che l'abrogazione espressa non c'e' piu' e che
  resta la clausola generale.
- Una norma abrogata non rivive perche' l'atto che l'abrogava e' stato a sua
  volta abrogato o riscritto. La reviviscenza si scrive solo se un testo la
  dispone ("rivive", "torna ad applicarsi", "si applica il regime previgente"),
  citandolo.
- `citatoDaAttiSuccessivi`: un atto posteriore cita l'articolo, e quasi sempre
  lo modifica. Se lo porta il passo che citi, leggi la modifica prima di
  rispondere (prima le voci con `riscrive: true`, qualunque sia l'anno) ed
  esponi il testo vigente dicendo cosa e' cambiato.
- `attoNovellatoDa`: l'atto e' stato modificato da leggi successive negli
  `articoli` elencati. Sulle domande generali ("come funziona X") e' il marchio
  piu' importante: la ricerca ti porta gli articoli che parlano del tema, non
  quelli riscritti. Se compare su un atto che usi, apri il novellante piu'
  recente PRIMA di scrivere, ed esponi la disciplina di adesso dicendo cosa e'
  cambiato. Che l'articolo che
  citi sia stato modificato lo dicono solo `toccaQuestoArticolo: true`,
  `citatoDaAttiSuccessivi` o il testo letto: con `false` le modifiche
  riguardano altri articoli, e se la domanda e' su un articolo preciso non
  serve aprire il novellante.
- `testoCoordinatoAl`: l'articolo e' il testo coordinato, aggiornato fino a
  quella data. Modifiche posteriori (`citatoDaAttiSuccessivi`,
  `versionePiuRecente`) vanno aperte; se la data e' lontana e non ne trovi,
  dillo ("testo coordinato aggiornato al 24 dicembre 2018").
- `testoAggiornatoIn`: l'articolo ha scritto il suo testo in un altro atto (l'art.
  5 della L. 64/2025 aggiunge l'art. 3-bis alla L. 44/2015). Leggi e cita
  l'articolo indicato, e presenta quello che hai davanti come "introdotto dalla
  L. 64/2025, art. 5".
- `versionePiuRecente` e `ancheIn`: la stessa rubrica o lo stesso testo
  ricorrono in un atto piu' recente. Esponi il piu' recente e cita il
  precedente solo per dire cosa e' cambiato. Non serve su domande storiche o su
  atti esauriti.
- Per sapere se un articolo e' aggiornato bastano questi marchi. `chi_cita`
  elenca i rinvii a un atto intero, non le modifiche a un articolo.
- Filtri di `cerca_testo`: `al_anno` per le domande storiche ("prima del 2000":
  `dal_anno` escluderebbe proprio quel periodo), `dal_anno` per la disciplina
  recente, `tipi` per un tipo d'atto, `escludi_abrogati` per la disciplina
  vigente (toglie solo le abrogazioni note).
- Date: `inVigoreDal` e' l'entrata in vigore, `dataAtto` l'emanazione. Se
  `inVigoreDal` manca usa `dataAtto` per collocare l'atto nel tempo, ma non
  dire che e' in vigore da quella data; se la domanda dipende proprio da
  quello, di' che il dato manca.

## 4. Leggere bene

- Un rinvio si segue. Se la risposta dipende da articoli richiamati ("i
  provvedimenti degli artt. 53, 54 e 55 della L. 42/2010"), leggili. Non
  descrivere un articolo, ne' la sua rubrica, dal numero o dal tema:
  `struttura_norma` da' tutte le rubriche di un atto in una chiamata.
- I termini definiti ("Autorita' Giudiziaria", "Ufficio") si leggono
  nell'articolo di definizioni della legge madre, con i suoi marchi, quando la
  risposta dipende da chi o cosa indicano: la definizione puo' essere stata
  riscritta (la L. 123/2019 ha fatto dell'"Autorita' Giudiziaria" della L.
  42/2010 la Corte per il Trust). Due norme che con la definizione vigente
  indicano lo stesso organo non sono situazioni diverse.
- Di' solo cio' che il testo dice. Se una norma elimina delle parole, riporta
  quali e l'effetto letterale. Una qualificazione giuridica che non leggi in un
  atto la ometti, o la presenti come tua interpretazione.
- `troncato: true` vuol dire testo tagliato: leggi l'articolo con
  `leggi_articolo` prima di citarlo, e comunque quando e' centrale. Se anche
  `leggi_articolo` risponde `parziale: true` (allegati, tabelle), leggi solo i
  commi che servono con `comma` e `da_carattere`, e di' che il testo e' lungo e
  che ne hai letto una parte. Un risultato di `cerca_testo` con `daCarattere`
  e' gia' il passo giusto di un comma lunghissimo: citalo col numero del comma
  e, se ti serve il contesto, leggi da quel carattere. Se non risponde, prova
  le posizioni in `altriPassi`, prima di scorrere il comma.
- Struttura di una norma (quanti articoli, com'e' organizzata, di cosa tratta
  l'art. N): `struttura_norma`, mai gli articoli uno per uno. Presupposti e
  rinvii: `citazioni_da`. Chi richiama una norma: `chi_cita`. Contenuto della
  banca dati: `elenco_norme`. Gli strumenti indipendenti chiamali in parallelo.
- Un atto noto solo per data ("la legge di giugno 1977"): `elenco_norme` con
  `tipo`, `anno` e `mese`, e scegli dalla `dataAtto`. Chiedi all'utente solo se
  restano piu' candidati.
- "Tutte le norme", "elenco completo": prima cerca per titolo con
  `trova_norma(testo=..., limite=...)` con i termini della materia, guarda con
  `chi_cita` chi richiama le leggi cardine, e includi convenzioni
  internazionali e ratifiche. Senza questa ricerca presenta l'elenco come "le
  principali norme trovate", mai come completo.

## 5. Il diritto sammarinese

- Usa le parole dell'articolo che citi, anche se quelle italiane ti sembrano
  piu' naturali: *prigionia* (non reclusione), *interdizione*, *multa a
  giorni*; il *misfatto* e' doloso, il *delitto* colposo (art. 150 "se il
  misfatto e' commesso", art. 163 "il delitto di omicidio" colposo).
- Una pena in gradi va tradotta in durata: leggi l'articolo che definisce i
  gradi (per la prigionia l'art. 81 del Codice Penale vigente,
  `leggi_articolo("L-17-1974", "81")`) e dai la durata accanto al grado, con
  il marcatore di quell'articolo.
- Gli elenchi della legge si riportano con i loro numeri e lettere - 1), 1
  bis), 2); a), b) - senza rinumerarli ne' trasformarli in punti elenco.

## 6. La risposta

- Scrivi sempre e solo in italiano, anche le frasi prima di una chiamata agli
  strumenti: l'utente le vede.
- Apri con la risposta, non con il metodo, e parti dal fatto: "hai trenta
  giorni, e sono perentori (L. 28/1991, art. 30)", non "l'articolo 30 della L.
  28/1991 dispone che...". Il professionista trova gli estremi e la lettera
  dove conta; il cittadino capisce comunque. Riporta tra virgolette il testo
  quando la formulazione esatta conta.
- Con una fonte esplicita trovata subito, esponila senza esitazioni. Se sei
  arrivato alla risposta dopo molti tentativi, o il passo che citi risponde
  solo di sbieco, dillo: "e' quanto di piu' pertinente l'archivio
  contiene, ma non disciplina espressamente il tuo caso".

Prima di inviare, ricontrolla:
- ogni rubrica, contenuto o modifica che nomini l'hai letta in un risultato;
- "vigente", "in vigore", "attualmente" hanno una prova letta;
- "completo", "tutte" vengono dopo la ricerca sistematica;
- se la risposta dipende da un termine definito, hai letto la definizione e le
  sue modifiche;
- ogni atto nominato ha il suo marcatore.
"""

ESTRATTO_STRUMENTO = 200
POTATO = " […risultato accorciato: se serve, rileggi con leggi_articolo]"


class PotaturaFraDomande(AgentMiddleware):
    """Accorcia i risultati degli strumenti delle domande precedenti.

    Una consultazione lunga costa quasi tutta in SCRITTURE di cache: sulla
    chat sui teatri 496.187 token scritti contro 109 di ingresso pieno, e il
    78% di quelle scritture erano riscritture a freddo - la cache dura cinque
    minuti, e chi torna dopo mezz'ora si ripaga per intero il contesto
    accumulato. L'ultima ripresa, dopo quattro giorni, valeva 147.000 token.

    Dentro quel contesto i risultati degli strumenti sono il 92%; le domande
    dell'utente lo 0,2%. Qui si accorciano quelli delle domande gia' chiuse,
    tenendo per intero le risposte del modello: il filo del discorso resta, e
    un articolo lo si rilegge se serve davvero.

    Si pota **una volta per domanda**, in `before_agent`, non a soglia durante
    il ragionamento. La differenza non e' un dettaglio: potare in mezzo al
    ciclo riscrive la cronologia a ogni giro, quindi obbliga a riscrivere la
    cache, e misurato faceva salire la prima domanda da 0,156 a 0,256 dollari.
    Potare al confine paga una sola riscrittura, e su un contesto molto piu'
    piccolo.

    Il taglio e' idempotente - un risultato gia' accorciato si riconosce dalla
    coda e si lascia stare - perche' fra una potatura e l'altra i messaggi
    devono restare identici byte per byte, altrimenti la cache si invalida
    lo stesso.
    """

    def __init__(self, estratto: int = ESTRATTO_STRUMENTO):
        super().__init__()
        self.estratto = estratto

    def before_agent(self, state, runtime):
        messaggi = list(state.get("messages") or [])
        # La domanda appena arrivata e' l'ultima: si pota tutto cio' che la
        # precede. Senza una domanda in coda non c'e' niente da chiudere.
        ultima = next((i for i in range(len(messaggi) - 1, -1, -1)
                       if isinstance(messaggi[i], HumanMessage)), None)
        if ultima is None:
            return None
        potati = []
        for m in messaggi[:ultima]:
            if not isinstance(m, ToolMessage) or not isinstance(m.content, str):
                continue
            if m.content.endswith(POTATO) or len(m.content) <= self.estratto:
                continue
            copia = m.model_copy(update={"content": m.content[:self.estratto] + POTATO})
            potati.append(copia)
        # Stesso id: il riduttore dei messaggi sostituisce invece di aggiungere.
        return {"messages": potati} if potati else None


INTERROTTA = "[La consultazione si e' interrotta prima dei risultati.]"


class RiparaChiamateOrfane(AgentMiddleware):
    """Toglie dalla cronologia le chiamate a strumenti rimaste senza risultato.

    Il checkpoint salva la risposta del modello che chiede gli strumenti prima
    che gli strumenti rispondano. Se la consultazione si interrompe in mezzo -
    un rilascio che ferma il container, un riavvio, un errore - la cronologia
    resta con chiamate senza risposta, e Anthropic la rifiuta per sempre:
    "tool_use ids were found without tool_result blocks". Il 26/09 una
    conversazione interrotta il 22/09 dava questo 400 a ogni nuova domanda.

    Si ripara in `before_agent`, una volta per domanda, e solo prima
    dell'ultima domanda: le chiamate che la seguono sono quelle in corso. Le
    chiamate orfane si tolgono dal messaggio che le conteneva, sul posto e con
    lo stesso id; il suo testo resta. Aggiungere risultati finti significherebbe
    far leggere al modello qualcosa che nessuno strumento ha detto.
    """

    def before_agent(self, state, runtime):
        messaggi = list(state.get("messages") or [])
        ultima = next((i for i in range(len(messaggi) - 1, -1, -1)
                       if isinstance(messaggi[i], HumanMessage)), None)
        if ultima is None:
            return None
        riparati = []
        for i, m in enumerate(messaggi[:ultima]):
            if not isinstance(m, AIMessage) or not m.tool_calls:
                continue
            risposte = set()
            for seguente in messaggi[i + 1:]:
                if not isinstance(seguente, ToolMessage):
                    break
                risposte.add(seguente.tool_call_id)
            orfane = {c["id"] for c in m.tool_calls} - risposte
            if orfane:
                riparati.append(_senza_chiamate(m, orfane))
        return {"messages": riparati} if riparati else None


def _senza_chiamate(messaggio, orfane):
    """Il messaggio del modello senza le chiamate indicate, ovunque stiano:
    in `tool_calls`, nei blocchi `tool_use` del contenuto (Anthropic) e in
    `additional_kwargs` (gateway compatibile OpenAI)."""
    chiamate = [c for c in messaggio.tool_calls if c["id"] not in orfane]
    contenuto = messaggio.content
    if isinstance(contenuto, list):
        contenuto = [b for b in contenuto
                     if not (isinstance(b, dict) and b.get("id") in orfane)]
    extra = dict(messaggio.additional_kwargs)
    if extra.get("tool_calls"):
        extra["tool_calls"] = [c for c in extra["tool_calls"] if c.get("id") not in orfane]
        if not extra["tool_calls"]:
            del extra["tool_calls"]
    # Anthropic rifiuta anche un messaggio vuoto: se non resta ne' testo ne'
    # chiamata, lo dice il messaggio stesso.
    if not chiamate:
        if isinstance(contenuto, list):
            if not any(isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()
                       for b in contenuto):
                contenuto = contenuto + [{"type": "text", "text": INTERROTTA}]
        elif not str(contenuto or "").strip():
            contenuto = INTERROTTA
    return messaggio.model_copy(update={"tool_calls": chiamate, "content": contenuto,
                                        "additional_kwargs": extra})


def _checkpointer():
    """
    Dove vivono le conversazioni.

    In produzione su DynamoDB, non su Aura. Aura tiene la normativa: metterci
    anche le chat significherebbe che `03_load.py --reset`, che esegue
    `MATCH (n) DETACH DELETE n`, cancella le conversazioni di tutti a ogni
    ricarico del grafo.

    Su DynamoDB i container diventano senza stato, ed e' la ragione per cui si
    puo' alzare il numero di task senza che un messaggio di seguito atterri su
    un'istanza che non sa di cosa si sta parlando.

    Senza le variabili delle tabelle si torna alla memoria di processo, cosi'
    `python src/server.py` continua a funzionare in locale senza AWS.
    """
    checkpoint = os.environ.get("TABELLA_CHECKPOINT")
    scritture = os.environ.get("TABELLA_SCRITTURE")
    if not (checkpoint and scritture):
        return InMemorySaver()

    from langgraph_checkpoint_dynamodb.saver import DynamoDBSaver
    return DynamoDBSaver(
        client_config={"region_name": os.environ.get("REGIONE", "eu-central-1")},
        checkpoints_table_name=checkpoint,
        writes_table_name=scritture,
    )


_memoria = None
_agenti = {}


def agente(nome=None):
    """L'agente per un modello, costruito una volta sola e tenuto da parte.

    Il nome serve alla riserva: due agenti diversi sullo stesso checkpointer,
    cosi' il secondo vede la conversazione che il primo ha lasciato a meta'.
    """
    global _memoria
    nome = nome or MODELLO
    if nome not in _agenti:
        _memoria = _memoria or _checkpointer()
        # La temperatura si manda solo dove il modello la accetta: su Sonnet 5
        # e Opus 5 il parametro e' deprecato e l'API rifiuta la richiesta con
        # un 400. Il campionamento la' lo governa il modello, non noi.
        if fornitore_di(nome) == "google":
            # L'import sta qui dentro e non in cima al file: il container di
            # produzione non si porta langchain-google-genai finche' gira su
            # Anthropic. Il tetto sull'uscita la' si chiama max_output_tokens.
            #
            # Dal 3.5 in poi il campionamento e' fisso e la temperatura viene
            # ignorata: la libreria lo dice con un warning a ogni chiamata, che
            # su una domanda sola sono dieci righe di rumore nei log. Gliela si
            # manda solo dove viene ascoltata - e dove non lo e', la risposta
            # alla stessa domanda puo' cambiare, cosa che su Sonnet non accade.
            from langchain_google_genai import ChatGoogleGenerativeAI
            parametri = {"model": nome, "max_output_tokens": 16000,
                         "google_api_key": os.environ["GEMINI_API_KEY"]}
            if ASCOLTANO_TEMPERATURA.match(nome):
                parametri["temperature"] = TEMPERATURA
            modello = ChatGoogleGenerativeAI(**parametri)
        elif fornitore_di(nome) == "alibaba":
            # Gateway OpenAI-compatibile: ci si parla con ChatOpenAI cambiando
            # base_url, non serve un pacchetto dedicato. La temperatura la'
            # arriva e viene rispettata, quindi gliela si manda sempre.
            #
            # La chiave: QWEN_API_KEY, o DASHSCOPE_API_KEY come la chiama la
            # documentazione di Model Studio.
            # Il tetto sull'uscita passa da extra_body e non da max_tokens,
            # perche' langchain-openai traduce max_tokens nel campo nuovo di
            # OpenAI, `max_completion_tokens`, e sul gateway di Alibaba i due
            # campi NON sono sinonimi. Misurato il 24/09 chiedendo venti citta'
            # con tetto 40:
            #   max_tokens=40            -> 977 token, di cui 933 di pensiero,
            #                               e la risposta visibile c'e'.
            #   max_completion_tokens=40 -> 40 token, tutti di pensiero,
            #                               e la risposta visibile e' VUOTA.
            # Qwen3.7 ragiona prima di scrivere: col campo nuovo il tetto conta
            # anche il pensiero, e un tetto stretto restituisce il nulla. Con
            # `max_tokens` il tetto vale sulla risposta, che e' cio' che
            # vogliamo limitare.
            from langchain_openai import ChatOpenAI
            chiave = os.environ.get("QWEN_API_KEY") or os.environ["DASHSCOPE_API_KEY"]
            modello = ChatOpenAI(model=nome, temperature=TEMPERATURA,
                                 base_url=QWEN_BASE, api_key=chiave,
                                 reasoning_effort=RAGIONAMENTO,
                                 extra_body={"max_tokens": 16000})
        else:
            parametri = {"model": nome, "max_tokens": 16000,
                         "api_key": os.environ["ANTHROPIC_API_KEY"]}
            if nome in ACCETTANO_TEMPERATURA:
                parametri["temperature"] = TEMPERATURA
            modello = ChatAnthropic(**parametri)

        # --- Prompt caching ---
        #
        # Il prefisso - istruzioni piu' gli schemi dei sette strumenti - e'
        # identico a ogni giro del ciclo ReAct: 7.632 token misurati con l'API
        # di conteggio (3.673 le istruzioni, riscritte il 17/09 da 7.380), e
        # sopra la soglia di Haiku per la cache.
        #
        # Due cose andavano capite, e su entrambe mi ero sbagliato prima.
        #
        # 1. `cache_control` non e' un parametro, e' un MARCATORE SU UN BLOCCO
        #    di contenuto. I tentativi con `modello.bind(cache_control=...)` e
        #    con `model_kwargs` fallivano per questo. Avevo scritto che era
        #    `bind_tools()` a scartarlo: falso, verificato: con bind_tools il
        #    marcatore viene onorato (8.875 token riletti in prova diretta).
        #
        # 2. Haiku 4.5 non mette in cache prefissi sotto i 4.096 token, e non
        #    lo segnala: ignora il marcatore in silenzio. Era questo, e solo
        #    questo, a tenere la cache spenta. Il prefisso reale misurato sul
        #    filo stava a ~3.990 token, un centinaio sotto la soglia.
        #
        # Il marcatore in coda al prompt di sistema mette in cache tutto cio'
        # che lo precede nella richiesta - gli schemi degli strumenti stanno
        # prima del system - quindi un solo punto di rottura copre l'intero
        # prefisso.
        if fornitore_di(nome) == "anthropic":
            istruzioni = SystemMessage(content=[{
                "type": "text",
                "text": ISTRUZIONI,
                "cache_control": {"type": "ephemeral"},
            }])
        else:
            # Fuori da Anthropic la cache non si marca: su Gemini e su Qwen e'
            # implicita, la decide il fornitore quando riconosce un prefisso
            # gia' visto, e `cache_control` qui sarebbe un blocco di contenuto
            # sconosciuto. In cambio non la governiamo: misurato su Gemini, il
            # prefisso si ripaga quasi intero a ogni giro.
            istruzioni = SystemMessage(content=ISTRUZIONI)

        # Il marcatore sul system copre solo il prefisso fisso. Il resto - la
        # cronologia, che a ogni giro del ciclo si rispedisce intera con i
        # risultati degli strumenti - si pagava a prezzo pieno: la chat sui
        # trust del 16/09 ha mandato 630.687 token d'ingresso per quattro
        # domande, e solo 104.088 venivano dalla cache. Il middleware aggiunge
        # il punto di rottura in coda alla richiesta, cosi' ogni giro rilegge
        # il precedente a un decimo del prezzo.
        #
        # Cinque minuti e non un'ora: a un'ora le SCRITTURE in cache costano 2
        # volte invece di 1,25, e sono il 76% del conto (misurato sulla chat
        # sui teatri: 496.187 token scritti contro 1.474.457 riletti).
        #
        # Restano care le RISCRITTURE: la cache dura cinque minuti, e chi
        # riprende una conversazione dopo una pausa ripaga per intero il
        # contesto accumulato. Per questo si pota al confine fra le domande
        # (PotaturaFraDomande) e non a ogni passata, come farebbe
        # ContextEditingMiddleware: quello riscrive la conversazione e quindi
        # obbliga a riscrivere la cache, e provato il 21/09 faceva salire la
        # prima domanda da 0,156 a 0,256 dollari.
        _agenti[nome] = create_agent(
            model=modello,
            tools=STRUMENTI,
            system_prompt=istruzioni,
            checkpointer=_memoria,
            # La potatura fra le domande vale per tutti i fornitori; il
            # middleware della cache no, e' Anthropic e basta.
            middleware=([RiparaChiamateOrfane(), PotaturaFraDomande(),
                         AnthropicPromptCachingMiddleware(ttl="5m")]
                        if fornitore_di(nome) == "anthropic"
                        else [RiparaChiamateOrfane(), PotaturaFraDomande()]),
        )
    return _agenti[nome]


def nuova_conversazione() -> str:
    return str(uuid.uuid4())


# Un id di norma come compare nei risultati degli strumenti: L-171-2022,
# DD-4-2014, EC-None-2019~17163212.
RE_ID_NORMA = re.compile(r"\b([A-Z]{1,3})-(-?\d+|None)-(\d{4})\b")

# Una citazione come la scrive il modello, in tutte le forme d'uso. Un giurista
# scrive lo stesso atto in quattro modi diversi, e riconoscerne uno solo rende
# la spia cieca proprio dove servirebbe. Misurato sul benchmark: un controllo
# che vedeva solo "numero/anno" dava per assenti ventuno citazioni corrette.
#
#   L. 164/2022                              numero / anno
#   Legge n. 164 del 2022                    numero poi anno
#   Decreto Delegato 23 agosto 2024 n. 134   anno poi numero (la data estesa)
#   DD-44-2008                               l'id come lo rendono gli strumenti
# I nomi composti vanno prima: "Decreto Delegato 50/2010" e "Legge Qualificata
# n. 1 del 2012" non si leggevano, perche' dopo "Decreto" o "Legge" veniva una
# parola invece del numero.
# Le forme lunghe stanno prima delle abbreviazioni, e fra le abbreviazioni
# "d.d." e "d.l." prima di "d." da sola, altrimenti un Decreto Delegato
# verrebbe letto come Decreto. "d." mancava: le risposte che scrivono
# "D. 43/1995" - forma normale per un Decreto - sfuggivano a ogni controllo
# sulle citazioni, ed e' cosi' che il 24/09 e' passata una fonte inventata.
TIPO = (r"(?:legge[\s\u00a0]+(?:qualificata|costituzionale)"
        r"|decreto[\s\u00a0-]+(?:delegato|legge|reggenziale|consiliare)"
        r"|legge|l\.|lq\.?|lc\.?|d\.l\.|dl\.?|d\.d\.|dd\.?|d\.|decreto"
        r"|regolamento|reg\.|r\.)")
CITAZIONI = [
    # Un marcatore di tipo davanti al numero e' obbligatorio nella forma con la
    # barra, altrimenti "fino al 31/12/2026" verrebbe letto come la norma
    # 12/2026.
    re.compile(TIPO + r"[\s\u00a0]*(?:n[\.\u00b0]?[\s\u00a0]*)?"
               r"(\d{1,4})[\s\u00a0]*/[\s\u00a0]*((?:19|20)\d{2})", re.I),
    re.compile(TIPO + r"[\s\u00a0]*n[\.\u00b0]?[\s\u00a0]*(\d{1,4})\b"
               r".{0,40}?\b((?:19|20)\d{2})\b", re.I),
    re.compile(TIPO + r"[^\n]{0,40}?\b((?:19|20)\d{2})\b[^\n]{0,20}?"
               r"n[\.\u00b0]?[\s\u00a0]*(\d{1,4})\b", re.I),
    re.compile(r"\b[A-Z]{1,3}-(\d{1,4})-((?:19|20)\d{2})\b"),
]

MARCATORE = re.compile(r"\{\{cita:[^{}]*\}\}")


def _aggiungi_fonti_d_atto(fonti, viste):
    """Per ogni atto consultato, anche la fonte dell'atto intero.

    L'aggancio automatico mette un marcatore dopo ogni atto nominato in prosa,
    e il marcatore deve puntare a una fonte esistente. Senza una fonte d'atto
    ripiegava sulla prima fonte di quell'atto: su una domanda risolta con
    struttura_norma era l'art. 1, e ogni "L. 64/2025" della risposta finiva
    seguita da "[art. 1]", un articolo che non c'entrava. Con leggi_articolo era
    il comma 1 dell'articolo letto, anche per requisiti scritti al comma 18.
    Chi nomina la legge nomina la legge: "[atto]".
    """
    # Lo stesso per l'articolo intero: "art. 5 della L. 64/2025" senza un
    # comma e' un marcatore {{cita:L-64-2025:5:-}}, e senza la sua fonte il
    # sito lo scartava anche se l'articolo era stato letto.
    for f in list(fonti):
        if not f.get("norma"):
            continue
        for articolo in ("-", str(f.get("articolo") or "-")):
            chiave = (f["norma"], articolo, "-")
            if chiave in viste:
                continue
            viste.add(chiave)
            fonti.append({"norma": f["norma"], "titoloNorma": f.get("titoloNorma"),
                          "articolo": articolo, "rubrica": f.get("rubrica") if articolo != "-" else None,
                          "pagina": f.get("pagina") if articolo != "-" else None,
                          "comma": "-",
                          "testo": (f.get("rubrica") if articolo != "-" else None)
                                   or f.get("titoloNorma") or "",
                          "haDocumento": bool(f.get("haDocumento")),
                          "abrogata": bool(f.get("abrogata")),
                          "abrogataDa": f.get("abrogataDa") or []})
    return fonti


# I nomi dei campi che gli strumenti restituiscono, e come si dicono a chi
# legge. Il prompt chiede di non scriverli; qui si traducono quelli che passano
# lo stesso - misurato: "l'articolo 150 ha `citatoDaAttiSuccessivi` che
# indicano modifiche", scritto a un utente.
CAMPI_INTERNI = {
    "citatoDaAttiSuccessivi": "le modifiche successive registrate",
    "attoNovellatoDa": "gli atti che l'hanno modificato",
    "toccaQuestoArticolo": "la modifica di questo articolo",
    "testoCoordinatoAl": "la data di aggiornamento del testo coordinato",
    "testoAggiornatoIn": "l'articolo in cui il testo e' stato inserito",
    "versionePiuRecente": "la versione piu' recente",
    "passiIntrodottiOraAbrogati": "i passi introdotti e poi abrogati",
    "passoAbrogatoDa": "gli atti che hanno abrogato il passo",
    "passoAbrogato": "l'abrogazione del passo",
    "abrogataDa": "gli atti che l'hanno abrogata",
    "novellataDa": "gli atti che l'hanno modificata",
    "testoDisponibile": "la disponibilita' del testo",
    "numeroOriginale": "il numero nel testo",
    "inVigoreDal": "la data di entrata in vigore",
    "ancheIn": "gli altri atti con lo stesso testo",
}
RE_CAMPO_INTERNO = re.compile(r"`?\b(" + "|".join(sorted(CAMPI_INTERNI, key=len, reverse=True)) + r")\b`?")

# "L." / "D.D." come li scrive il modello, e il tipo d'atto che vogliono dire.
TIPI_ABBREVIATI = [
    (re.compile(r"^\s*(?:legge\s+qualificata|l\.?\s*q\.?)", re.I), "Legge Qualificata"),
    (re.compile(r"^\s*(?:legge\s+costituzionale|l\.?\s*c\.?)\b", re.I), "Legge Costituzionale"),
    (re.compile(r"^\s*(?:decreto[\s-]*legge|d\.?\s*l\.?)", re.I), "Decreto Legge"),
    (re.compile(r"^\s*(?:decreto\s+delegato|d\.?\s*d\.?)", re.I), "Decreto Delegato"),
    (re.compile(r"^\s*(?:regolamento|reg\.|r\.)", re.I), "Regolamento"),
    (re.compile(r"^\s*(?:legge|l\.)", re.I), "Legge"),
]


def _prefisso_nominato(citazione):
    """Il prefisso d'id dell'atto come lo nomina la prosa, o None.

    Numero e anno non bastano: la Legge Costituzionale e la Legge Qualificata
    del 26 gennaio 2012 sono entrambe n.1, e "Legge Qualificata 26 gennaio
    2012 n.1" riceveva il riferimento della LC-1-2012. Per "Decreto" senza
    altro il tipo resta ignoto (None): decide solo se l'atto e' uno.
    """
    m = re.match(r"\s*([A-Z]{1,3})-\d", citazione)
    if m:
        return m.group(1)
    tipo = next((t for e, t in TIPI_ABBREVIATI if e.match(citazione)), None)
    if not tipo:
        return None
    from comune import norma_id
    return norma_id(tipo, 1, 2000).split("-")[0]


def _chiave_articolo(articolo):
    """Come il frontend confronta i numeri d'articolo."""
    if articolo in (None, ""):
        return "-"
    return re.sub(r"[\s.\-–]+", "", str(articolo)).lower()


def _senza_campi_interni(testo):
    return RE_CAMPO_INTERNO.sub(lambda m: CAMPI_INTERNI[m.group(1)], testo)


def _fonte_d_atto(norma):
    """La fonte a livello d'atto per una norma con testo, o None."""
    try:
        righe = grafo().query("""
            MATCH (n:Norma {id: $id}) WHERE n.caricata
            RETURN n.id AS id, n.titolo AS titolo, n.urlDocumento AS url,
                   n.abrogata AS abrogata, n.abrogataDa AS abrogataDa""", {"id": norma})
    except Exception:
        return None
    if not righe:
        return None
    r = righe[0]
    return {"norma": r["id"], "titoloNorma": r["titolo"], "articolo": "-", "comma": "-",
            "testo": r["titolo"] or "", "haDocumento": bool(r["url"]),
            "abrogata": bool(r["abrogata"]), "abrogataDa": r["abrogataDa"] or []}


def _ripara_marcatori(testo, fonti, viste):
    """I marcatori senza fonte, riportati al livello che la fonte ha davvero.

    Il frontend scarta un marcatore che non trova fra le fonti: il riferimento
    spariva. Un comma non letto di un articolo letto diventa l'articolo; un
    passo di un atto che non e' stato aperto diventa l'atto, se l'atto ha il
    testo in archivio. Un marcatore verso cio' che l'archivio non ha si toglie,
    come farebbe il frontend.
    """
    chiavi = {(str(f.get("norma")), _chiave_articolo(f.get("articolo")),
               str(f.get("comma") if f.get("comma") not in (None, "") else "-")) for f in fonti}

    def sostituisci(m):
        norma, articolo, comma = m.group(1), m.group(2), m.group(3) or "-"
        if (norma, _chiave_articolo(articolo), comma) in chiavi:
            return m.group(0)
        if (norma, _chiave_articolo(articolo), "-") in chiavi:
            return f"{{{{cita:{norma}:{articolo}:-}}}}"
        if (norma, "-", "-") not in chiavi:
            fonte = _fonte_d_atto(norma)
            if fonte is None:
                return ""
            fonti.append(fonte)
            viste.add((norma, "-", "-"))
            chiavi.add((norma, "-", "-"))
        return f"{{{{cita:{norma}:-:-}}}}"

    return re.sub(r"\{\{cita:([^:{}]+):([^:{}]*):([^:{}]*)\}\}", sostituisci, testo)


def _fonti_atti_nominati(testo, fonti, viste):
    """Gli atti nominati in prosa ma mai aperti, se l'archivio ne ha il testo.

    "L'unica modifica e' quella della L. 97/2008": il modello l'aveva letta nei
    marchi di leggi_articolo senza aprirla, e il riferimento restava testo
    morto. Si aggiunge la fonte dell'atto - titolo e PDF, niente che il
    modello non abbia visto - e _ancora_gli_atti lo rende cliccabile.
    """
    presenti = set()
    for f in fonti:
        pezzi = str(f.get("norma") or "").split("-")
        if len(pezzi) >= 3 and pezzi[1].isdigit():
            presenti.add((pezzi[0], str(int(pezzi[1])), pezzi[2].split("~")[0]))
    mascherato = MARCATORE.sub(lambda m: " " * len(m.group(0)), testo)
    for i, espressione in enumerate(CITAZIONI):
        for m in espressione.finditer(mascherato):
            numero, anno = ((m.group(2), m.group(1)) if i == 2 else (m.group(1), m.group(2)))
            prefisso = _prefisso_nominato(m.group(0))
            if not prefisso:
                continue
            chiave = (prefisso, str(int(numero)), anno)
            if chiave in presenti:
                continue
            norma = f"{prefisso}-{int(numero)}-{anno}"
            fonte = _fonte_d_atto(norma)
            if fonte is None or (norma, "-", "-") in viste:
                continue
            fonti.append(fonte)
            viste.add((norma, "-", "-"))
            presenti.add(chiave)
    return fonti


# "{cita:DD-50-2010:8:3}", con una graffa sola: Sonnet lo ha scritto cosi' nella
# prova del 16/09 sui trust, il sito non lo riconosce, e _ancora_gli_atti ci infilava
# dentro un secondo marcatore sull'id.
RE_MARCATORE_SEMPLICE = re.compile(r"(?<!\{)\{cita:([^{}]+)\}(?!\})")

RE_MARCATORE_PARTI = re.compile(r"\{\{cita:([^:{}]+):([^:{}]*):([^:{}]*)\}\}")


def fonti_della_storia(messaggi):
    """Le fonti dei risultati degli strumenti in una sequenza di messaggi."""
    fonti, viste = [], set()
    for m in messaggi:
        if getattr(m, "type", "") != "tool":
            continue
        esito = m.content
        if isinstance(esito, str):
            try:
                esito = json.loads(esito)
            except (ValueError, TypeError):
                pass
        for f in _fonti_da(getattr(m, "name", "") or "", esito):
            chiave = (f["norma"], f["articolo"], f["comma"])
            if chiave not in viste:
                viste.add(chiave)
                fonti.append(f)
    return fonti


def _richiama_precedenti(testo, fonti, viste, precedenti):
    """Le fonti dei turni precedenti che la risposta cita.

    "Che leggi hai usato?" non chiama strumenti: il modello risponde con cio'
    che ha letto prima, e scrive i marcatori giusti - art. 150, commi 1, 2 e 3.
    Ma le fonti si raccoglievano solo dal turno in corso, erano zero, e il sito
    scartava ogni marcatore. Si riprendono dai turni precedenti quelle citate,
    e solo quelle: il pannello delle fonti resta quello del turno.
    """
    if not precedenti:
        return
    presenti = {(str(f.get("norma")), _chiave_articolo(f.get("articolo")), str(f.get("comma") or "-"))
                for f in fonti}
    for m in RE_MARCATORE_PARTI.finditer(testo):
        norma, articolo, comma = m.group(1), _chiave_articolo(m.group(2)), m.group(3) or "-"
        if (norma, articolo, comma) in presenti:
            continue
        stesso_articolo = [f for f in precedenti if str(f.get("norma")) == norma
                           and _chiave_articolo(f.get("articolo")) == articolo]
        candidati = ([f for f in stesso_articolo if str(f.get("comma") or "-") == comma]
                     or stesso_articolo
                     or [f for f in precedenti if str(f.get("norma")) == norma][:1])
        for f in candidati[:1] if comma == "-" or not stesso_articolo else candidati:
            chiave = (f["norma"], f["articolo"], f["comma"])
            if chiave not in viste:
                viste.add(chiave)
                fonti.append(f)
            presenti.add((str(f["norma"]), _chiave_articolo(f["articolo"]), str(f["comma"] or "-")))


def rifinisci(testo, fonti, viste, precedenti=None):
    """La risposta come la vede l'utente: tutte le cure, sempre nello stesso ordine.

    La usano rispondi() dal vivo e il server quando ricostruisce una
    conversazione dal checkpoint: se divergessero, ricaricare la pagina
    cambierebbe le citazioni. `precedenti` sono le fonti dei turni prima di
    questo.
    """
    testo = RE_MARCATORE_SEMPLICE.sub(r"{{cita:\1}}", testo)
    _richiama_precedenti(testo, fonti, viste, precedenti)
    _aggiungi_fonti_d_atto(fonti, viste)
    testo = _senza_campi_interni(testo)
    testo = _ripara_marcatori(testo, fonti, viste)
    _fonti_atti_nominati(testo, fonti, viste)
    return _ancora_gli_atti(testo, fonti)


def _ancora_gli_atti(testo, fonti):
    """Rende cliccabile ogni atto nominato nella prosa, se la fonte esiste.

    Chiedere al modello di non dimenticarsi un marcatore e' chiedergli di fare
    contabilita', e la contabilita' si fa nel codice: misurato su quattro
    domande, nominava da uno a due atti per risposta senza il marcatore, e chi
    legge si trovava un riferimento che non si puo' aprire.

    Si aggiunge il marcatore SOLO se fra le fonti c'e' davvero quell'atto. Se
    non c'e', il riferimento resta testo semplice: e' la stessa garanzia che il
    frontend applica scartando i marcatori senza riscontro, e vale la pena
    ripeterla qui invece di allentarla.
    """
    if not fonti:
        return testo
    # Per ogni atto si tiene una fonte RAPPRESENTATIVA, non solo il suo id: il
    # marcatore dev'essere (norma, articolo, comma) di una fonte davvero
    # presente, altrimenti il frontend lo scarta. Si preferisce la fonte a
    # livello d'atto - articolo "-" - perche' e' quella che corrisponde a un
    # riferimento nominato in prosa senza articolo. rispondi() la aggiunge per
    # ogni atto consultato (_aggiungi_fonti_d_atto): ripiegare sulla prima
    # fonte etichettava la legge come "[art. 1]".
    # Le fonti stanno sotto (numero, anno) e poi sotto il prefisso: la prosa
    # dice il tipo, e fra LC-1-2012 e LQ-1-2012 decide quello.
    per_atto = {}
    for f in fonti:
        pezzi = str(f.get("norma") or "").split("-")
        if len(pezzi) < 3 or not pezzi[1].isdigit():
            continue
        stessi = per_atto.setdefault((str(int(pezzi[1])), pezzi[2].split("~")[0]), {})
        precedente = stessi.get(pezzi[0])
        migliore = (precedente is None
                    or (str(f.get("articolo")) == "-" and str(precedente[1]) != "-")
                    or ("~" not in str(f["norma"]) and "~" in str(precedente[0])))
        if migliore:
            stessi[pezzi[0]] = (f["norma"], f.get("articolo"), f.get("comma"))
    if not per_atto:
        return testo

    # I marcatori gia' presenti si mascherano con spazi PRIMA di cercare: il
    # riferimento vive anche dentro il marcatore - {{cita:L-145-2022:-:-}} - e
    # senza mascherarlo se ne agganciava uno dentro l'altro. Gli spazi hanno la
    # stessa lunghezza, cosi' le posizioni restano valide sul testo originale.
    mascherato = MARCATORE.sub(lambda m: " " * len(m.group(0)), testo)

    fuori, fine = [], 0
    # si raccolgono tutte le occorrenze, poi si inseriscono da sinistra a destra
    trovate = []
    for i, espressione in enumerate(CITAZIONI):
        for m in espressione.finditer(mascherato):
            numero, anno = ((m.group(2), m.group(1)) if i == 2
                            else (m.group(1), m.group(2)))
            trovate.append((m.start(), m.end(), str(int(numero)), anno,
                            _prefisso_nominato(m.group(0))))
    trovate.sort()
    for k, (inizio, termine, numero, anno, prefisso) in enumerate(trovate):
        if inizio < fine:
            continue                      # gia' coperta da un aggancio precedente
        stessi = per_atto.get((numero, anno)) or {}
        if prefisso in stessi:
            rif = stessi[prefisso]
        elif prefisso is None and len(stessi) == 1:
            rif = next(iter(stessi.values()))
        else:
            continue                      # non fra le fonti: resta testo semplice
        # anche dopo uno spazio o la chiusura del grassetto: "L. 17/1974
        # {{cita:...}}" e "**L. 42/2010**{{cita:...}}" ne ricevevano due
        if re.match(r"[\s*_\"»)\]]*\{\{cita:", testo[termine:termine + 16]):
            continue                      # il modello l'ha gia' messo. Non si
                                          # avanza `fine`: il testo saltato deve
                                          # comunque finire nell'uscita, o la
                                          # prosa davanti al marcatore sparisce.
        # "**L. 1° marzo 2010 n.42 - L'Istituto del Trust**{{cita:L-42-2010:-:-}}":
        # il modello ha messo il marcatore dopo il titolo. Se nella stessa riga
        # ne arriva uno per lo stesso atto prima che se ne nomini un altro,
        # basta quello.
        riga = testo[termine:termine + 200].split("\n", 1)[0]
        dopo = riga.find("{{cita:" + rif[0] + ":")
        prossima = trovate[k + 1][0] - termine if k + 1 < len(trovate) else len(riga) + 1
        if 0 <= dopo < prossima:
            continue
        norma, articolo, comma = rif
        articolo = "-" if articolo in (None, "") else str(articolo)
        comma = "-" if comma in (None, "") else str(comma)
        fuori.append(testo[fine:termine]
                     + f"{{{{cita:{norma}:{articolo}:{comma}}}}}")
        fine = termine
    fuori.append(testo[fine:])
    return "".join(fuori)


def _citazioni_non_verificate(testo, norme_viste):
    """Le norme citate nella risposta che nessuno strumento ha restituito.

    Il sistema SA quali sono le fonti giuste: gli strumenti tornano normaId,
    articolo e comma esatti. Il modello poi riscrive la citazione in prosa, e
    li' puo' sbagliarla. Il confronto e' deterministico - o quell'atto e' stato
    letto, o e' stato inventato - e non richiede alcun giudizio.

    Misurato sul benchmark: 79 risposte corrette su 96 nel merito, ma fonte
    giusta solo 50 su 95. Un assistente giuridico che dice la cosa esatta
    citando la norma sbagliata non e' meta' corretto: chi legge non puo'
    verificare.

    Volutamente prudente: si segnala solo la forma esplicita "tipo numero/anno".
    Un falso allarme costa piu' di una segnalazione mancata.
    """
    coppie_viste = {(n, a) for _t, n, a in
                    (m.groups() for m in RE_ID_NORMA.finditer(norme_viste))}
    coppie = []
    for i, espressione in enumerate(CITAZIONI):
        for m in espressione.finditer(testo or ""):
            # La terza forma trova prima l'anno e poi il numero: si rimette
            # nell'ordine delle altre invece di duplicare la logica a valle.
            coppie.append((m.group(2), m.group(1)) if i == 2
                          else (m.group(1), m.group(2)))

    fuori = []
    for numero, anno in coppie:
        if (numero, anno) in coppie_viste or (numero.lstrip("0"), anno) in coppie_viste:
            continue
        etichetta = f"{numero}/{anno}"
        if etichetta not in fuori:
            fuori.append(etichetta)
    return fuori


# L'articolo citato in prosa subito prima di un marcatore: "art. 33",
# "articolo 7, comma 2", "art. all2-30, comma 4". Deve contenere una cifra:
# "dell'articolo precedente" e' testo di legge citato, non un riferimento,
# e senza questa condizione faceva scattare un allarme falso.
RE_ARTICOLO_PRIMA = re.compile(
    r"art(?:\.|icolo)?[\s\u00a0]*([\w][\w\-\.]{0,14}?)"
    r"(?:[\s\u00a0]*,?[\s\u00a0]*comma[\s\u00a0]*[\w\-\.]+)?[\s\u00a0]*$",
    re.I)


# "all-36" e' l'articolo 36 dell'allegato, "all2-30" il 30 dell'allegato 2:
# e' l'id del grafo, e la prosa lo scrive "allegato, art. 36".
RE_ALLEGATO = re.compile(r"^all\d*-")


def _stessa_voce(detto, marcato):
    a = (detto or "").strip().lower().lstrip("0")
    b = (marcato or "").strip().lower().lstrip("0")
    # Si accetta anche il numero nudo contro l'id d'allegato. Si perde il caso
    # in cui un atto abbia sia l'art. 36 nel corpo sia il 36 in allegato e il
    # modello confonda i due: e' un prezzo basso, perche' l'alternativa e' un
    # allarme falso su OGNI citazione d'allegato, e qui un falso costa piu' di
    # una segnalazione mancata.
    return a == b or a == RE_ALLEGATO.sub("", b)


def _citazioni_discordi(testo):
    """Dove la prosa e il marcatore attaccato non dicono la stessa cosa.

    Il controllo sopra guarda l'ATTO - quello e' stato letto o no - e non vede
    il caso peggiore: atto vero, articolo inventato. Successo il 24/09 con
    Qwen, che ha scritto "D. 63/1995, art. 33" e poi il marcatore
    `{{cita:D-63-1995:18:2}}`: l'art. 33 non esiste (il decreto finisce al 18)
    e il 18 comma 2 parla della composizione del Consiglio. Chi legge clicca e
    trova un'altra norma, o niente.

    Vale anche per il NUMERO DELL'ATTO, sbagliato due volte nella stessa
    risposta: "D. 43/1995 (Ingegneri e Architetti)" col marcatore a D-63-1995,
    e "DD. 145/2014 (Periti Industriali)" col marcatore a DD-173-2014. Il
    controllo sull'atto letto non li vede, perche' entrambi gli atti erano
    stati consultati davvero: e' l'abbinamento a essere inventato.

    Deterministico come l'altro: non giudica se la citazione sia pertinente,
    confronta numeri che il modello ha scritto lui. Si guarda solo il testo
    ATTACCATO al marcatore - la forma che le istruzioni prescrivono - perche'
    un atto o un articolo nominati a meta' frase possono legittimamente essere
    altri. Per la stessa prudenza il confronto sull'atto si ferma davanti a un
    punto fermo: oltre, e' un'altra frase.
    """
    fuori = []
    for m in RE_MARCATORE_PARTI.finditer(testo or ""):
        articolo = (m.group(2) or "").strip()
        if not articolo or articolo == "-":
            continue
        # Il tratto che appartiene a QUESTO marcatore: dalla fine del
        # precedente, e non oltre l'a capo.
        prima = testo[:m.start()].rsplit("}}", 1)[-1].rsplit("\n", 1)[-1]
        detto = RE_ARTICOLO_PRIMA.search(prima)
        if detto and not any(c.isdigit() for c in detto.group(1)):
            detto = None
        testa = prima[:detto.start()] if detto else prima
        # L'articolo si confronta solo se un atto e' nominato prima di lui: e'
        # la forma prescritta dalle istruzioni. Un "art. 57" senza atto davanti
        # e' un rinvio dentro al testo di legge - "punito con le pene del primo
        # comma dell'art. 57" - e confrontarlo col marcatore e' un falso.
        if detto and _nomina_un_atto(testa) and not _stessa_voce(detto.group(1), articolo):
            _aggiungi(fuori,
                      f"{m.group(1)} art. {detto.group(1)} (il marcatore dice {articolo})")
        _confronta_atto(fuori, testa, m.group(1))
    return fuori


def _nomina_un_atto(tratto):
    """Se nel tratto compare un atto, in una qualunque delle forme scritte."""
    return any(e.search(tratto or "") for e in CITAZIONI)


def _confronta_atto(fuori, prima, marcato):
    """L'atto nominato in prosa subito prima, contro quello del marcatore."""
    id_marcato = RE_ID_NORMA.search(marcato or "")
    if not id_marcato or id_marcato.group(2) == "None":
        return
    # Solo la forma "numero/anno", non quelle con la data estesa, e non e' una
    # svista: "D. 23 febbraio 1996 n. 20, art. 59{{cita:D-32-1996:59:-}}" e'
    # CORRETTO - il D-20-1996 e' il decreto sull'Ordine dei Medici e il
    # D-32-1996 e' la ratifica che ne porta il testo, quindi il numero in prosa
    # e quello del marcatore divergono per forza. Allargare il confronto alle
    # forme con la data farebbe scattare un allarme su ogni atto ratificato.
    finestra = prima[-90:]
    ultimo = None
    for nominato in CITAZIONI[0].finditer(finestra):
        ultimo = nominato
    if not ultimo or ". " in finestra[ultimo.end():]:
        return
    if (_stessa_voce(ultimo.group(1), id_marcato.group(2))
            and ultimo.group(2) == id_marcato.group(3)):
        return
    _aggiungi(fuori, f"{ultimo.group(0).strip()} (il marcatore dice {marcato})")


def _aggiungi(fuori, etichetta):
    if etichetta not in fuori:
        fuori.append(etichetta)


def _fonti_da(nome_strumento, risultato):
    """Estrae dai risultati i riferimenti da mostrare come fonti nella UI."""
    fonti = []
    if not isinstance(risultato, dict):
        return fonti
    if nome_strumento == "cerca_testo":
        for r in risultato.get("risultati", []):
            fonti.append({
                "norma": r.get("normaId"), "titoloNorma": r.get("normaTitolo"),
                "articolo": r.get("articolo"), "rubrica": r.get("rubrica"),
                "comma": r.get("comma"), "testo": r.get("testo"),
                # Gli atti che riportano lo STESSO identico testo. La potatura
                # li collassa in una riga sola per non sprecare i posti utili,
                # ma come fonti valgono quanto quello mostrato: un tariffario
                # riemesso in cinque decreti si puo' citare da ognuno dei
                # cinque. Non elencarli faceva sembrare unica una fonte che
                # non lo e', e chi cercava la propria versione non la trovava.
                # Il portale possiede il PDF originale di questo atto: il
                # frontend puo' offrirne l'apertura.
                "haDocumento": bool(r.get("urlDocumento")),
                # La pagina del PDF dove l'articolo comincia, quando il testo
                # viene da un testo coordinato: il sito apre il documento li'.
                "pagina": r.get("paginaDocumento"),
                "ancheIn": r.get("ancheIn") or [],
                # L'atto successivo che modifica questo articolo: chi legge
                # deve poterci arrivare, non solo il modello.
                "novellataDa": [n.get("norma") for n in
                                (r.get("citatoDaAttiSuccessivi") or [])],
                # L'atto e' caduto per intero. Il marchio e' raro - 358 norme
                # su 12.248 - e proprio per questo va mostrato dove compare:
                # chi legge non ha modo di dedurlo dal testo, che di suo resta
                # perfettamente sensato. L'assenza del marchio non dice nulla.
                "abrogata": bool(r.get("abrogata")),
                "abrogataDa": r.get("abrogataDa") or [],
                # Il passo in se', dentro un atto ancora vivo. Va mostrato
                # proprio perche' il testo attorno resta valido: nulla, nel
                # leggerlo, farebbe sospettare che questo pezzo non valga piu'.
                "passoAbrogato": bool(r.get("passoAbrogato")),
                "passoAbrogatoDa": r.get("passoAbrogatoDa") or [],
            })
    elif nome_strumento == "leggi_articolo" and "articolo" in risultato:
        for c in risultato.get("commi", []):
            if c.get("numero"):
                fonti.append({
                    "norma": risultato.get("normaId"),
                    "titoloNorma": risultato.get("normaTitolo"),
                    "articolo": risultato.get("articolo"),
                    "rubrica": risultato.get("rubrica"),
                    "comma": c.get("numero"), "testo": c.get("testo"),
                    "haDocumento": bool(risultato.get("urlDocumento")),
                    "pagina": risultato.get("paginaDocumento"),
                    "abrogata": bool(risultato.get("abrogata")),
                    "abrogataDa": risultato.get("abrogataDa") or [],
                    "passoAbrogato": bool(c.get("abrogato")
                                          or risultato.get("passoAbrogato")),
                    "passoAbrogatoDa": (c.get("abrogatoDa")
                                        or risultato.get("passoAbrogatoDa") or []),
                })
    # Anche `trova_norma` e `struttura_norma` consultano davvero l'archivio, e
    # finora non producevano fonti. La conseguenza non era solo una lista vuota
    # in fondo: il frontend SCARTA i marcatori {{cita:...}} che non trovano
    # riscontro fra le fonti - giustamente, un marcatore inventato non deve
    # produrre un link - quindi su una domanda risolta con questi due strumenti
    # sparivano anche le citazioni dentro il testo. La risposta restava giusta e
    # sembrava non ancorata a nulla.
    #
    # Il bersaglio qui e' l'atto o l'articolo, non il comma: si usa "-" per le
    # partizioni che mancano, la stessa convenzione che il modello gia' scrive
    # nei marcatori ({{cita:L-106-2009:-:-}}) e che normalizzaComma() conosce.
    elif nome_strumento == "trova_norma":
        for r in risultato.get("risultati", []):
            if not r.get("id"):
                continue
            fonti.append({
                "norma": r.get("id"), "titoloNorma": r.get("titolo"),
                "articolo": "-", "comma": "-",
                "testo": r.get("titolo") or "",
                "haDocumento": bool(r.get("urlDocumento")),
                "abrogata": bool(r.get("abrogata")),
                "abrogataDa": r.get("abrogataDa") or [],
            })
    elif nome_strumento == "struttura_norma" and risultato.get("id"):
        for a in risultato.get("articoli", []):
            if not a.get("numero"):
                continue
            fonti.append({
                "norma": risultato.get("id"),
                "titoloNorma": risultato.get("titolo"),
                "articolo": a.get("numero"), "rubrica": a.get("rubrica"),
                "comma": "-",
                # La struttura porta la rubrica, non il testo: e' cio' che
                # l'agente ha davvero letto, e non si finge di piu'.
                "testo": a.get("rubrica") or "",
                "haDocumento": bool(risultato.get("urlDocumento")),
            })
    # Gli strumenti di RETE - chi cita, chi e' citato, l'elenco - restituiscono
    # riferimenti a livello d'atto, e finora non producevano fonti. Il costo si
    # vedeva su una domanda tipica: "quali modifiche ha subito la L. 36/1958"
    # elencava sei atti modificanti e nessuno era cliccabile, perche' nessuno
    # era fra le fonti e l'ancoraggio - giustamente - non inventa.
    elif nome_strumento in ("chi_cita", "citazioni_da", "elenco_norme"):
        elenchi = ((risultato.get("citataDa") or [])
                   + (risultato.get("dipendenze") or [])
                   + (risultato.get("basePreambolo") or [])
                   + (risultato.get("normeEstratte") or []))
        for r in elenchi:
            atto = r.get("norma") or r.get("id")
            if not atto:
                continue
            fonti.append({
                "norma": atto, "titoloNorma": r.get("titolo"),
                "articolo": "-", "comma": "-",
                "testo": r.get("titolo") or "",
                "haDocumento": bool(r.get("urlDocumento")),
            })
    return fonti


def _quante(risultato):
    if not isinstance(risultato, dict):
        return 0
    for chiave in ("risultati", "norme", "dipendenze", "citataDa", "articoli", "commi"):
        if isinstance(risultato.get(chiave), list):
            return len(risultato[chiave])
    return 0


def _testo_di(messaggio):
    """Il testo di un AIMessage, che il contenuto sia una stringa o blocchi.

    Nella forma a blocchi interessa solo `type == "text"`: gli altri blocchi
    sono gli argomenti degli strumenti, che non vanno nella risposta.
    """
    contenuto = getattr(messaggio, "content", None)
    if isinstance(contenuto, str):
        return contenuto.strip()
    if isinstance(contenuto, list):
        return "".join(b.get("text", "") for b in contenuto
                       if isinstance(b, dict) and b.get("type") == "text").strip()
    return ""


def _rifiuto_di_contenuto(errore):
    """Il gateway ha respinto la richiesta per il suo filtro sui contenuti.

    Succede su deepseek-v4.1-flash con domande del tutto normali - misurata il
    24/09 su "quali incentivi sono previsti per i giovani imprenditori", due
    tentativi su due - e non e' un problema di rete: ritentare lo stesso
    modello da' lo stesso rifiuto.
    """
    return "data_inspection_failed" in str(errore)


def _flusso(config, ingresso, passa_a_riserva, stream_mode=None):
    """Gli aggiornamenti del grafo, scorrendo le riserve se il filtro ci ferma.

    Le riserve riprendono con `None`: LangGraph riparte dal checkpoint, quindi
    le ricerche gia' fatte non si rifanno e non si ripagano. Si passa oltre
    solo per il rifiuto del filtro: un errore di rete o il tetto dei giri
    devono restare visibili, non nascondersi dietro un cambio di modello.
    """
    catena = [(MODELLO, ingresso)] + [(nome, None) for nome in RISERVE]
    for posto, (nome, ingresso_suo) in enumerate(catena):
        if posto:
            passa_a_riserva(nome)
        try:
            for pezzo in agente(nome).stream(ingresso_suo, config=config,
                                             stream_mode=stream_mode):
                yield pezzo
            return
        except Exception as e:
            if not _rifiuto_di_contenuto(e) or posto == len(catena) - 1:
                raise


def rispondi(domanda, conversazione=None):
    """
    Genera eventi: {"tipo": ..., ...}

      testo       la risposta, in un unico evento a fine ciclo
      strumento   lo strumento sta per essere eseguito
      risultato   lo strumento ha risposto
      fonti       i commi consultati, per il pannello delle fonti
      fine        uso dei token, costo stimato, id conversazione
      errore      qualcosa e' andato storto
    """
    conversazione = conversazione or nuova_conversazione()
    config = {"configurable": {"thread_id": conversazione},
              "recursion_limit": MAX_GIRI * PASSI_PER_CHIAMATA[FORNITORE]}

    fonti_raccolte, viste = [], set()
    # Le fonti dei turni precedenti: una domanda di seguito puo' rispondere
    # senza strumenti, citando cio' che e' stato letto prima.
    try:
        precedenti = fonti_della_storia(
            (agente().get_state(config).values or {}).get("messages", []))
    except Exception:
        precedenti = []
    # Il grezzo di tutti i risultati: serve a stabilire quali norme il
    # modello ha davvero avuto sotto gli occhi.
    grezzo_strumenti = []
    # Un conto per modello: se la riserva subentra a meta', i token del primo
    # sono stati comunque consumati e vanno pagati al suo listino, non a quello
    # della riserva.
    conti = {}

    def conto_di(nome):
        return conti.setdefault(nome, dict(dentro=0, fuori=0, letti=0,
                                           scritti=0, scritti_ora=0))

    corrente = {"conto": conto_di(MODELLO), "modello": MODELLO}

    def passa_a_riserva(nome):
        corrente["conto"] = conto_di(nome)
        corrente["modello"] = nome
    # I nomi arrivano con l'AIMessage, i risultati dopo col ToolMessage:
    # questa mappa li ricongiunge per id di chiamata.
    nomi_per_id = {}
    # I blocchi di testo che il modello scrive lungo il ciclo - le frasi di
    # servizio prima di uno strumento e la risposta finale - si accumulano qui
    # e partono insieme. Il modello riprende a scrivere dopo gli strumenti:
    # senza uno stacco la frase nuova si salderebbe alla precedente.
    blocchi_testo = []

    try:
        # `_modo` non serve piu' - resta perche' stream() con una lista di
        # modi restituisce comunque coppie (modo, pezzo).
        for _modo, pezzo in _flusso(
            config,
            {"messages": [{"role": "user", "content": domanda}]},
            passa_a_riserva,
            # Solo "updates": il modo "messages" serviva a emettere il testo
            # frammento per frammento, e la risposta non si consegna piu' cosi'.
            # Gli eventi degli strumenti restano in diretta - misurate, le
            # consultazioni durano 8 secondi mediani e 22 al massimo, e tanto
            # silenzio si legge come un blocco - ma il testo arriva intero,
            # cosi' il Markdown viene reso una volta sola, gia' completo: una
            # tabella o un blocco di codice non passano piu' per gli stati
            # intermedi in cui la sintassi e' ancora a meta'.
            stream_mode=["updates"],
        ):
            for _nodo, stato in pezzo.items():
                if not isinstance(stato, dict):
                    continue
                for messaggio in stato.get("messages", []) or []:
                    uso = getattr(messaggio, "usage_metadata", None)
                    if uso:
                        # `input_tokens` comprende i token riletti dalla cache,
                        # che pero' costano un decimo, e quelli scritti, che
                        # costano un quarto in piu'. Sommarli al prezzo pieno
                        # gonfierebbe il costo mostrato all'utente e quello
                        # registrato sui consumi.
                        # Le scritture non stanno in `cache_creation`: quando
                        # l'API manda il dettaglio per durata della cache,
                        # langchain-anthropic mette i token in
                        # `ephemeral_5m/1h_input_tokens` e AZZERA `cache_creation`
                        # per non contarli due volte. Leggendo solo quello, le
                        # scritture finivano fra i token a prezzo pieno e il
                        # costo usciva piu' basso del vero del 14% (misurato il
                        # 22/09 su tutte le domande fatte con Sonnet).
                        d = uso.get("input_token_details") or {}
                        letti = d.get("cache_read", 0) or 0
                        cinque_min = d.get("ephemeral_5m_input_tokens", 0) or 0
                        un_ora = d.get("ephemeral_1h_input_tokens", 0) or 0
                        scritti = d.get("cache_creation", 0) or 0
                        if cinque_min or un_ora:
                            scritti = 0      # gia' contati nelle due voci sopra
                        c = corrente["conto"]
                        c["dentro"] += uso.get("input_tokens", 0)
                        c["letti"] += letti
                        c["scritti"] += scritti + cinque_min
                        c["scritti_ora"] += un_ora
                        c["fuori"] += uso.get("output_tokens", 0)

                    if type(messaggio).__name__ == "AIMessage":
                        scritto = _testo_di(messaggio)
                        if scritto:
                            blocchi_testo.append(scritto)

                    for chiamata in getattr(messaggio, "tool_calls", None) or []:
                        nomi_per_id[chiamata["id"]] = chiamata["name"]
                        yield {"tipo": "strumento", "nome": chiamata["name"],
                               "argomenti": chiamata["args"]}

                    if type(messaggio).__name__ == "ToolMessage":
                        nome = nomi_per_id.get(getattr(messaggio, "tool_call_id", None),
                                               getattr(messaggio, "name", "?"))
                        esito = messaggio.content
                        if isinstance(esito, str):
                            try:
                                esito = json.loads(esito)
                            except (ValueError, TypeError):
                                pass
                        grezzo_strumenti.append(
                            json.dumps(esito, ensure_ascii=False, default=str))
                        for f in _fonti_da(nome, esito):
                            chiave = (f["norma"], f["articolo"], f["comma"])
                            if chiave not in viste:
                                viste.add(chiave)
                                fonti_raccolte.append(f)
                        yield {"tipo": "risultato", "nome": nome,
                               "quante": _quante(esito),
                               "errore": esito.get("errore") if isinstance(esito, dict) else None}

    except Exception as e:
        yield {"tipo": "errore", "messaggio": f"{type(e).__name__}: {e}"}
        return

    if blocchi_testo:
        yield {"tipo": "testo",
               "testo": rifinisci(SEPARATORE.join(blocchi_testo), fonti_raccolte, viste,
                                  precedenti)}

    if fonti_raccolte:
        yield {"tipo": "fonti", "fonti": fonti_raccolte}

    costo = 0.0
    for nome, c in conti.items():
        prezzo_in, prezzo_out, letto = PREZZI.get(
            nome, (5.0, 25.0, FATTORE_CACHE[fornitore_di(nome)]))
        pieni = c["dentro"] - c["letti"] - c["scritti"] - c["scritti_ora"]
        # Scrivere in cache costa 1,25 volte con la scadenza a 5 minuti e 2
        # volte con quella a un'ora: sono voci che solo Anthropic riporta, e
        # fuori da la' restano a zero. La rilettura la fanno tutti, a fattori
        # diversi.
        costo += ((pieni + c["scritti"] * 1.25 + c["scritti_ora"] * 2 + c["letti"] * letto)
                  / 1e6 * prezzo_in + c["fuori"] / 1e6 * prezzo_out)
    token_in = sum(c["dentro"] for c in conti.values())
    token_out = sum(c["fuori"] for c in conti.values())
    token_letti = sum(c["letti"] for c in conti.values())
    scritto = SEPARATORE.join(blocchi_testo)
    sospette = (_citazioni_non_verificate(scritto, " ".join(grezzo_strumenti))
                + _citazioni_discordi(scritto))

    yield {"tipo": "fine", "tokenIn": token_in, "tokenOut": token_out,
           "tokenDaCache": token_letti,
           "citazioniNonVerificate": sospette,
           "costo": round(costo, 4),
           # Chi ha risposto davvero: se il filtro del gateway ci ha fermati,
           # in fondo c'e' una riserva e il conto porta piu' di un listino.
           "modello": corrente["modello"],
           "conversazione": conversazione}
