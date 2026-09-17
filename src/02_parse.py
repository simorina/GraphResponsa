"""
02 - Parsing dei PDF normativi in JSON strutturato.

Non tocca la rete: legge data/raw/ e scrive data/parsed/, cosi' si puo'
rigiocare all'infinito mentre si affinano i pattern.

Struttura riconosciuta nel testo (verificata sui PDF del portale):

    TITOLO I                          <- partizione, rubrica sulla riga dopo
    DISPOSIZIONI SULLA ...
    CAPO I                            <- partizione annidata nel titolo
    DISPOSIZIONI GENERALI
    Art.1                             <- articolo, su riga propria
    (Principi e obiettivi generali)   <- rubrica, puo' andare a capo
    1.                                <- numero di comma, su riga da solo
    Si definisce governo ...          <- testo del comma

Output: data/parsed/<norma-id>.json
"""

import json
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comune import PREFISSI, norma_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PARSED = ROOT / "data" / "parsed"

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}

RE_PARTIZIONE = re.compile(r"^(TITOLO|CAPO|SEZIONE)\s+([IVXLC]+)\s*$", re.I)
# Intestazione d'articolo su riga propria. Oltre a "Art. 5", "Art. 5 bis",
# "Articolo unico", accetta tre grafie misurate sul corpus
# (scripts/diag_varianti.py, solo righe il cui numero prosegue la sequenza):
#   "Art 19", "Art 4."        senza punto dopo Art    151 righe,  99 documenti
#   "Art. 23 (23)", "Art. 54. (10)"  richiamo di nota    84 righe,   8 documenti
#   "Art. 12°", "Articolo 7°"  simbolo di grado          27 righe,   3 documenti
# Il richiamo di nota e il grado non entrano nel numero. La rubrica sulla stessa
# riga ("Art. 21 - Rubrica") resta fuori: il "$" finale la esclude.
#
# "Art. 5-bis" (trattino) resta fuori di proposito. Accettarlo recupera 186
# articoli veri in 91 documenti, ma in 41 documenti le intestazioni sono quelle
# di articoli CITATI da una novella ("Dopo l'articolo 44 e' inserito: Art.
# 44-bis ...") e diventerebbero articoli spuri del decreto che le cita. Serve
# prima un controllo sulla sequenza in parse().
RE_ARTICOLO = re.compile(
    r"^(?:Art\.?|Articolo)\s*(\d+|[Uu]nico)\s*[°º]?\.?\s*"
    r"(bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies)?\.?\s*"
    r"(?:\(\d+\))?\s*[-:.]?\s*$", re.I)

_PROVE_ARTICOLO = [
    ("Art. 5", "5"),
    ("Articolo unico", "unico"),
    ("Art. 5 bis", "5 bis"),
    # senza punto
    ("Art 19", "19"),
    ("Art 4.", "4"),
    ("Art 7 - L'imposta e' dovuta", None),       # rubrica/testo sulla riga: fuori scope
    # richiamo di nota
    ("Art. 23 (23)", "23"),
    ("Art. 54. (10)", "54"),
    ("Art. 106.(12)", "106"),
    ("Art. 3 (Oggetto)", None),                   # rubrica sulla riga, non nota
    # grado
    ("Art. 12°", "12"),
    ("Articolo 7°", "7"),
    ("Art 11° - I due segretari terranno il registro", None),
    ("Art. 12° bis", "12 bis"),
    # trattino prima del suffisso: escluso finche' non c'e' il controllo sulle novelle
    ("Art.1-bis", None),
    # trattino lungo finale: in L-59-2016 "Articolo 9 –" e' una voce del sommario
    ("Articolo 9 –", None),
    # riferimento nel testo, non intestazione
    ("Art. 24 della legge 18 febbraio 1998 n.30", None),
    ("Arte 5", None),
]
for _riga, _atteso in _PROVE_ARTICOLO:
    _m = RE_ARTICOLO.match(_riga)
    _numero = (_m.group(1).lower() + (f" {_m.group(2).lower()}" if _m.group(2) else "")) if _m else None
    assert _numero == _atteso, f"RE_ARTICOLO: {_riga!r} -> {_numero!r}"
RE_COMMA = re.compile(r"^(\d+)\.\s*$")
RE_COMMA_INLINE = re.compile(r"^(\d+)\.\s+(\S.*)$")

# Una citazione normativa: tipo, eventuale data estesa, numero, eventuale /anno.
RE_CITAZIONE = re.compile(
    # L'ordine conta: le alternative vanno dalla piu' specifica alla piu'
    # generica. Con "Legge" davanti, "Decreto Legge n.89/2014" veniva letto
    # come "Legge n.89/2014" e la norma finiva sotto l'id sbagliato.
    r"(?P<tipo>Legge\s+Costituzionale|Legge\s+Qualificata"
    r"|Decreto\s+Delegato|Decreto\s+Legge|Decreto\s+Reggenziale"
    r"|Decreto\s+Consiliare|Decreto|Regolamento|Legge)"
    r"\s*"
    r"(?:(?P<giorno>\d{1,2})\s+(?P<mese>gennaio|febbraio|marzo|aprile|maggio|giugno"
    r"|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(?P<anno_data>\d{4})\s*)?"
    r"n\.\s*(?P<numero>\d+)"
    r"(?:\s*/\s*(?P<anno_slash>\d{4}))?",
    re.I,
)

# "articolo 10 della Legge ..." -> il bersaglio della citazione precede la norma.
#
# La versione precedente pretendeva che il riferimento all'articolo fosse
# ADIACENTE al nome dell'atto, e nel linguaggio degli atti quasi mai lo e':
# "l'ultimo comma dell'art. 2 CAP. IV della Legge n.38/1974", "all'art.8 PRIMO
# COMMA della Legge n.136/1997". Misurato sul corpus, il 6,0% delle citazioni
# nominava l'articolo senza che venisse agganciato - 3.775 rinvii che il grafo
# conosceva solo a grana d'atto.
#
# Fra l'articolo e l'atto si ammette percio' un tratto, ma non uno spazio
# libero: solo una LISTA BIANCA di parole strutturali - commi, capi, titoli,
# lettere, ordinali, numeri romani. Con uno spazio libero si sarebbe agganciato
# l'articolo di una frase vicina: "dell'articolo 5 e in deroga a quanto
# previsto dalla Legge X" non riguarda l'articolo 5 della Legge X.
#
# Tre errori, nel riscriverla: `articoli?` non aggancia "articolo" (serve
# `articol[oi]`), `commi?` non aggancia "comma", e senza "del" nella lista
# bianca "del Cap. V della" restava fuori.
_TOKEN = (r"(?:e|ed|primo|second[oa]|terz[oa]|quart[oa]|quint[oa]|sest[oa]|ultim[oa]"
          r"|penultim[oa]|comm[ai]|capo|cap|titolo|sezione|letter[ae]|lett|punt[oi]"
          r"|numero|n|bis|ter|quater|del|dello|della|dei|degli|delle|dal|dalla"
          r"|[IVXLC]+|\d+|[a-z]\))")
_FILLER = r"(?:[\s,;.')]*" + _TOKEN + r"){0,8}[\s,;.')]*"
RE_BERSAGLIO = re.compile(
    r"(?:artt?\.?|articol[oi])\s*(\d+)"
    r"(?:\s*,?\s*comm[ai]\s*(\d+))?"
    + _FILLER +
    r"(?:dell[ao]|dell'|del|della|dei|degli|di|al|alla|allo|ai|agli)\s*$",
    re.I,
)

# Le prove girano all'import: un'espressione che sbaglia qui produce archi
# CITA_ARTICOLO verso l'articolo sbagliato, e nessuno se ne accorgerebbe.
_PROVE_BERSAGLIO = [
    ("ai sensi dell'articolo 5 della ", "5"),
    ("l'ultimo comma dell'art. 2 Cap. IV della ", "2"),
    ("in base all'art. 3 del Cap. V della ", "3"),
    ("di cui all'art.8 primo comma della ", "8"),
    ("e dagli artt.208 e 209 della ", "208"),
    ("l'articolo 12, comma 3, della ", "12"),
    ("all'articolo 4, lettera b), della ", "4"),
    # fra l'articolo e l'atto c'e' una frase, non una struttura: non aggancia
    ("dell'articolo 5 e in deroga a quanto previsto dalla ", None),
    ("l'articolo 7 stabilisce i criteri applicabili alla ", None),
    ("secondo quanto disposto nella ", None),
    ("l'articolo 3 e' abrogato. Si applica la ", None),
]
for _testo, _atteso in _PROVE_BERSAGLIO:
    _m = RE_BERSAGLIO.search(_testo)
    assert (_m.group(1) if _m else None) == _atteso, f"RE_BERSAGLIO: {_testo!r}"


# --- Fine del dispositivo legislativo: formula di promulgazione ---
#
# Dopo l'ultimo articolo vero, l'atto chiude quasi sempre con "Dato/Data
# dalla Nostra Residenza, addi'... d.F.R." seguito da "I CAPITANI REGGENTI" e
# i due nomi. Cio' che segue - i Segretari di Stato, e spesso un Allegato -
# non e' piu' dispositivo: e' un trattato, uno statuto, una tabella di
# bilancio. Il riconoscitore normale non lo sa, e se l'allegato contiene a
# sua volta intestazioni "Art. N" (una decisione UE, un trattato ONU, uno
# statuto societario), le prende per nuovi articoli DELL'ATTO SAMMARINESE: il
# comma dell'ultimo articolo vero arriva a superare il milione di caratteri
# (misurato: DD-19-2019, DD-138-2018), e in altri casi l'allegato si
# frammenta in articoli spuri (DC-52-2016 ne assorbe 20 da un trattato ONU
# come se fossero suoi, DC-109-2015 duplica "Articolo unico" perche' la
# decisione UE allegata ne ha uno proprio).
#
# Misurato sul corpus intero: 2.967 documenti su 11.134 (26,7%) hanno
# quest'esatto problema. Restano fuori scope i decreti 1918-1943, che
# chiudono con una formula diversa: allargare la regex per prenderli
# aumenterebbe il rischio di falsi positivi altrove, e sono un numero
# residuale (meno di 30 casi misurati).
RE_PROMULGAZIONE = re.compile(
    r"Dat[oa]\s+dalla\s+Nostra\s+Residenza.{0,250}?CAPITANI\s+REGGENTI",
    re.I | re.S)
FINESTRA_PROMULGAZIONE = 20  # righe di preavviso: tollera interruzioni di riga/pagina


def _cerca_promulgazione(righe, i):
    """
    La formula di promulgazione inizia PROPRIO A QUESTA riga?

    match(), non search(): con search() la finestra di preavviso (20 righe)
    trovava la formula troppo presto, quando la riga corrente era ancora
    testo vero dell'ultimo articolo e la formula stava solo qualche riga piu'
    in la'. match() ancora l'inizio della frase alla riga corrente - le 20
    righe di finestra servono solo a tollerare che "Dato"/"dalla Nostra
    Residenza"/"CAPITANI REGGENTI" siano spezzati su piu' righe, non a
    cercare la formula in anticipo.
    """
    finestra = " ".join(r.strip() for r in righe[i:i + FINESTRA_PROMULGAZIONE])
    return bool(RE_PROMULGAZIONE.match(finestra))


def _ha_struttura_propria(righe_resto):
    """
    L'allegato contiene a sua volta intestazioni 'Art. N'?

    Si segnala soltanto (allegatoHaStrutturaPropria): non si prova a
    strutturarlo, perche' sarebbero gli articoli di un documento diverso
    (un trattato, uno statuto societario), non dell'atto sammarinese - vedi
    L-115-2019, il cui Allegato A e' lo statuto di una societa' con una
    numerazione propria che non ha nulla a che fare con la legge che lo
    approva.
    """
    return any(RE_ARTICOLO.match(r.strip()) for r in righe_resto if r.strip())


_PROVE_PROMULGAZIONE = [
    # _cerca_promulgazione(righe, 0) replica esattamente come il ciclo
    # principale la interroga: SOLO quando la riga corrente e' quella su cui
    # ci si trova, mai "cerca piu' avanti" - la riga 0 di ogni fixture e'
    # percio' la riga che il ciclo starebbe processando in quel momento, e
    # deve essere l'inizio vero della formula (o di testo qualunque, per i
    # casi negativi), non una riga di testo normativo che la precede.
    ("caso semplice",
     ["Dato dalla Nostra Residenza, addì 23 luglio 2015/1714 d.F.R", "",
      "I CAPITANI REGGENTI", "Andrea Belluzzi – Roberto Venturini"], True),
    ("interruzione di riga anomala fra 'Dato' e 'dalla Nostra Residenza'",
     ["Dato", "dalla Nostra", "Residenza, addì 16 luglio 2019/1718 d.F.R.", "",
      "I CAPITANI REGGENTI", "Nicola Selva - Michele Muratori"], True),
    ("trattino normale invece di en-dash fra i nomi: nessuna differenza attesa",
     ["Data dalla Nostra Residenza, addì 2 marzo 2020/1719 d.F.R", "",
      "I CAPITANI REGGENTI", "Luca Boschi - Mariella Mularoni"], True),
    ("nessuna formula: testo normativo qualunque, nessun taglio",
     ["1. Il presente regolamento disciplina l'accesso agli atti.",
      "2. Si applica a tutti gli uffici pubblici."], False),
    # "Dato" nel senso comune ("dato atto di"), non l'incipit della formula:
    # non deve agganciare solo perche' inizia con la stessa parola.
    ("'Dato' usato in un senso diverso non e' la formula di chiusura",
     ["Dato atto di quanto sopra deliberato, si procede.",
      "Restano ferme le disposizioni ordinarie in materia di bilancio."], False),
    # la riga corrente non e' l'inizio della formula (e' una voce di bilancio
    # che nomina i Capitani Reggenti, misurata in L-115-2019): il ciclo
    # principale non la incontrerebbe mai come "riga i" di questo controllo
    # se non fosse gia' passato da un "Dato dalla Nostra Residenza" prima.
    ("riga che non inizia con 'Dato'/'Data': mai la formula",
     ["Assegni alle LL.EE. i Capitani Reggenti", "1-2-1230", " 178.000,00"], False),
]
for _nome, _righe_test, _atteso in _PROVE_PROMULGAZIONE:
    assert _cerca_promulgazione(_righe_test, 0) == _atteso, f"RE_PROMULGAZIONE ({_nome}): {_righe_test!r}"

_PROVE_STRUTTURA_ALLEGATO = [
    ("caso L-115-2019: l'allegato e' uno statuto societario con Art. propri",
     ["I CAPITANI REGGENTI", "Nicola Selva - Michele Muratori", "",
      "Allegato \"A\" alla Legge 16 luglio 2019 n.115", "", "STATUTO DELLA SOCIETA'",
      "Art.1", "(Denominazione)", "", "Art.9", "(Competenze)"], True),
    ("allegato senza struttura propria (una decisione UE senza articoli qui)",
     ["I CAPITANI REGGENTI", "Andrea Belluzzi - Roberto Venturini", "",
      "IL SEGRETARIO DI STATO", "PER GLI AFFARI INTERNI", "Gian Carlo Venturini",
      "", "DECISIONE DELLA COMMISSIONE", "del 6 marzo 2014"], False),
]
for _nome, _righe_test, _atteso in _PROVE_STRUTTURA_ALLEGATO:
    assert _ha_struttura_propria(_righe_test) == _atteso, f"struttura allegato ({_nome}): {_righe_test!r}"


# --- Rubrica presunta: riga breve chiusa da un punto subito dopo "Art. N" ---
#
# Quando e' presa per rubrica ma e' testo, sparisce: l'articolo ha altri commi,
# e il recupero a fine parse() scatta solo per gli articoli rimasti vuoti.
# Misurato sul corpus intero (3.177 rubriche presunte rimaste rubrica): nessuna
# era seguita da un comma numerato >= 2; 2.038 finivano con ":" ("L'Art. 3 e'
# cosi' modificato:", "Il cittadino ha diritto:") e sono sempre l'apertura di
# un elenco o di una novella; circa 330 di quelle chiuse da "." sono frasi
# ("E' abrogata la Legge ...", "La presente legge entra in vigore ...").
# Una rubrica non finisce con i due punti e non inizia con un articolo o con
# un verbo: "Giuramento.", "Caccia vietata su terreno ricoperto di neve.".
RE_INCIPIT_FRASE = re.compile(
    r"^[-–\s]*(?:(?:il|lo|la|i|gli|le|un|una|uno|non|sono|ogni)\s|l['’]|(?:è|é|e['’])\s)",
    re.I)


def _puo_essere_rubrica(riga):
    return (len(riga) <= 80 and riga.endswith(".")
            and not RE_INCIPIT_FRASE.match(riga))


_PROVE_RUBRICA_PRESUNTA = [
    ("Giuramento.", True),
    ("Caccia vietata su terreno ricoperto di neve.", True),
    ("- Vitto.", True),
    ("Il Collegio dei sindaci revisori.", False),  # ponytail: sacrificata, resta nel testo e non si perde
    ("L'Art. 21 è così modificato:", False),
    ("Il cittadino ha diritto:", False),
    ("E' abrogata la Legge 17 settembre 1986 n.98.", False),
    ("È nominato Presidente del Centro il Prof. Umberto Eco.", False),
    ("L’uso dei richiami è consentito dal 2 settembre 2001.", False),
    ("- Il Rettore indicherà l'ora dell'uscita.", False),
    ("Sono abrogati gli artt. 3 e 4 della Legge 25 novembre 1980, n.86.", False),
    ("Lotteria nazionale e giochi", False),  # senza punto: mai presunta
]
for _riga, _atteso in _PROVE_RUBRICA_PRESUNTA:
    assert _puo_essere_rubrica(_riga) == _atteso, f"rubrica presunta: {_riga!r}"


# --- Due atti nello stesso PDF ---
#
# Il PDF del portale a volte contiene due atti di seguito: una Legge e il suo
# Regolamento, una Tariffa, una Parte seconda. Il secondo rinumera gli
# articoli da 1, e senza riconoscerlo i suoi articoli prendono gli id del
# primo: a valle sopravvive un solo testo per id (misurato: 131 documenti e
# 459 articoli, fra cui i 22 della Legge in L-0-1910, cancellati dai 22 del
# Regolamento). L'id_norma resta uno solo - le citazioni in entrata puntano
# li' - ma gli articoli del secondo atto prendono un segmento proprio:
# "L-0-1910/reg/art-1".
RE_MARCATORE_ATTO = re.compile(
    r"^\s*(?:[\dIVXLC]+\s*[.)]{1,2}\s*)?"
    r"(regolamento|statuto|tariffa|tariffe|allegato|tabella|convenzione"
    r"|parte\s+[IVXLC\d]+"
    r"|disposizion[ei]\s+transitori[ae])"
    r"\s*[.:]?\s*$", re.I)
FINESTRA_MARCATORE = 6   # righe non vuote da guardare sopra l'intestazione


def _marcatore_atto(righe, i, finestra=FINESTRA_MARCATORE):
    """Sopra la riga i comincia un altro atto? Restituisce il segmento di id."""
    viste, j = 0, i - 1
    while j >= 0 and viste < finestra:
        s = righe[j].strip()
        if s:
            viste += 1
            m = RE_MARCATORE_ATTO.match(s)
            if m:
                testo = m.group(1).lower()
                if testo.startswith("regolament"):
                    return "reg"
                return re.sub(r"[^a-z0-9]+", "-", testo).strip("-")
        j -= 1
    return None


_PROVE_MARCATORE = [
    ("L-0-1910: il Regolamento dopo l'ultimo articolo della Legge",
     ["servizio nella misura del 4 per cento sullo stipendio percepito.", "",
      "REGOLAMENTO", "Istruzione obbligatoria.", "Art. 1."], 4, "reg"),
    ("L-111-1918: il regolamento numerato come voce di un elenco",
     ["- Questa legge entrera' in vigore il 1 Agosto 1918.", "2.) Regolamento.",
      "Parte I", "Art. 1."], 3, "parte-i"),
    ("L-32-1987: seconda parte dello stesso atto",
     ["del mezzo.", "Parte 2", "MISSIONI E TRASFERTE", "Art. 1"], 3, "parte-2"),
    # "CAPO III" e' una partizione dell'atto, non un atto nuovo: in L-59-2016 e
    # DD-192-2020 l'indice iniziale avrebbe spinto gli articoli veri in una
    # parte, lasciando l'id canonico alle voci dell'indice. Resta alla rete di
    # sicurezza (id reso univoco).
    ("R-0-1883: un capitolo che rinumera non e' un secondo atto",
     ["avvenuti.", "Cap. III.", "Del cantoniere come appaltatore.", "Art. 1."], 3, None),
    ("testo normativo qualunque: nessun marcatore",
     ["- La presente legge entra in vigore subito.", "Art. 1."], 1, None),
    ("la parola dentro una frase non e' un'intestazione",
     ["Il regolamento e' approvato con decreto delegato.", "Art. 1."], 1, None),
]
for _nome, _righe_test, _i, _atteso in _PROVE_MARCATORE:
    assert _marcatore_atto(_righe_test, _i) == _atteso, f"marcatore atto ({_nome})"


def righe_pdf(path):
    doc = fitz.open(path)
    righe = []
    for pagina in doc:
        righe += pagina.get_text().split("\n")
    doc.close()
    return [r.rstrip() for r in righe]


def unisci(buffer):
    """Unisce le righe di un blocco in un testo pulito."""
    testo = " ".join(r.strip() for r in buffer if r.strip())
    return re.sub(r"\s+", " ", testo).strip()


# Molti decreti anteriori agli anni '90 non scrivono mai "Art. N": numerano per
# livelli ("1.1", "1.2" sotto un CAPO) oppure stendono il dispositivo di
# seguito. Senza articoli il testo finisce tutto nel preambolo, e la ricerca
# non lo vede: cerca_testo interroga i nodi :Comma.
RE_ART_DECIMALE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.?\s+(\S.*)$")
RE_FINE_PREAMBOLO = re.compile(
    r"^\s*(decretiamo|decreta|decretano|promulghiamo|ordiniamo|"
    r"si\s+decreta|abbiamo\s+decretato)\b", re.I)

# Un comma dedotto oltre questa soglia si spezza: un blocco unico di decine di
# migliaia di caratteri rende inutile sia l'embedding sia la citazione.
TAGLIO_COMMA = 1400


def _spezza_in_commi(testo):
    """Divide un corpo non strutturato in blocchi, chiudendo a fine frase."""
    if len(testo) <= TAGLIO_COMMA:
        return [testo] if testo else []
    frasi = re.split(r"(?<=[.;:])\s+", testo)
    blocchi, corrente = [], ""
    for f in frasi:
        if corrente and len(corrente) + len(f) + 1 > TAGLIO_COMMA:
            blocchi.append(corrente.strip())
            corrente = f
        else:
            corrente = f"{corrente} {f}".strip()
    if corrente.strip():
        blocchi.append(corrente.strip())
    return blocchi


def struttura_dedotta(id_norma, righe):
    """
    Ricava una struttura da un atto che il parsing normale non ha agganciato.

    Restituisce (articoli, righe_di_preambolo). Viene invocata SOLO quando non
    e' stato riconosciuto nemmeno un articolo, cosi' non puo' alterare i
    documenti che gia' si strutturano bene.

    Gli articoli prodotti portano `strutturaDedotta: True`: l'inferenza resta
    dichiarata, invece di confondersi con la numerazione reale dell'atto.
    """
    inizio = 0
    for i, r in enumerate(righe[:80]):
        if RE_FINE_PREAMBOLO.match(r):
            inizio = i + 1
            break
    preambolo = righe[:inizio]
    corpo = [r for r in righe[inizio:] if r.strip()]
    if not corpo:
        return [], righe

    def nuovo_articolo(numero, ordine):
        return {
            "id": f"{id_norma}/art-{numero}",
            "numero": numero,
            "rubrica": None,
            "partizioneId": None,
            "ordine": ordine,
            "commi": [],
            "strutturaDedotta": True,
        }

    def nuovo_comma(art, numero, testo):
        # Nei regolamenti tecnici la stessa coppia "1.1" ricorre in sezioni
        # diverse (D-122-1985: 66 commi con lo stesso id). Un id ripetuto, a
        # valle, e' un testo che ne cancella un altro: si rende unico qui,
        # come fa chiudi_comma() per il parsing normale.
        base = f"{art['id']}/c-{numero}"
        esistenti = {c["id"] for c in art["commi"]}
        cid, n = base, 1
        while cid in esistenti:
            n += 1
            cid = f"{base}-{n}"
        return {
            "id": cid,
            "numero": str(numero),
            "testo": testo,
            "numerazioneAnomala": False,
            "commaImplicito": True,
        }

    # --- Numerazione decimale: "1.1", "1.2", "2.1" ---
    agganci = [RE_ART_DECIMALE.match(r) for r in corpo]
    if sum(1 for m in agganci if m) >= 3:
        articoli, per_numero, buffer, comma = [], {}, [], None
        for riga, m in zip(corpo, agganci):
            if m:
                if comma is not None:
                    comma["testo"] = unisci(buffer)
                art_n, comma_n, testa = m.group(1), m.group(2), m.group(3)
                art = per_numero.get(art_n)
                if art is None:
                    art = nuovo_articolo(art_n, len(articoli))
                    per_numero[art_n] = art
                    articoli.append(art)
                comma = nuovo_comma(art, comma_n, "")
                art["commi"].append(comma)
                buffer = [testa]
            elif comma is not None:
                buffer.append(riga)
            else:
                preambolo.append(riga)
        if comma is not None:
            comma["testo"] = unisci(buffer)
        return [a for a in articoli if any(c["testo"] for c in a["commi"])], preambolo

    # --- Nessuna struttura: un articolo unico, spezzato in blocchi leggibili ---
    corpo_unito = unisci(corpo)
    blocchi = _spezza_in_commi(corpo_unito)
    if not blocchi:
        return [], righe

    art = nuovo_articolo("unico", 0)
    art["commi"] = [nuovo_comma(art, i, b) for i, b in enumerate(blocchi, 1)]
    return [art], preambolo


def estrai_citazioni(testo, id_norma_corrente):
    """
    Trova i riferimenti ad altre norme nel testo.
    Scarta l'autocitazione: una legge che cita se stessa non e' una dipendenza.
    """
    citazioni = []
    for m in RE_CITAZIONE.finditer(testo):
        tipo = re.sub(r"\s+", " ", m.group("tipo")).strip().title()
        numero = int(m.group("numero"))
        anno = m.group("anno_slash") or m.group("anno_data")
        anno = int(anno) if anno else None

        prima = testo[max(0, m.start() - 90):m.start()]
        bersaglio = RE_BERSAGLIO.search(prima)
        art_citato = bersaglio.group(1) if bersaglio else None
        comma_citato = bersaglio.group(2) if bersaglio else None

        if anno and norma_id(tipo, numero, anno) == id_norma_corrente:
            continue  # autocitazione

        citazioni.append({
            "tipo": tipo,
            "numero": numero,
            "anno": anno,
            "articoloCitato": art_citato,
            "commaCitato": comma_citato,
            "testo": re.sub(r"\s+", " ", m.group(0)).strip(),
        })
    return citazioni


def parse(id_norma, meta, righe=None):
    # righe: per le prove all'import, che non hanno un PDF da leggere.
    if righe is None:
        righe = righe_pdf(RAW / id_norma / "testo.pdf")

    partizioni = []       # albero: Titoli con figli Capi
    articoli = []
    ids_usati = set()
    ids_articoli = set()
    parti_usate = set()
    parte_corrente = None    # None = atto principale del documento

    titolo_corrente = None
    capo_corrente = None
    articolo_corrente = None
    comma_corrente = None
    buffer = []
    attesa_rubrica = False   # siamo appena dopo "Art.N"
    rubrica_buffer = []
    preambolo = []
    iniziato = False
    allegato_testo = None
    allegato_ha_struttura_propria = False

    def chiudi_comma():
        """
        Chiude il comma in corso.

        La numerazione dei commi non e' sempre progressiva, per due motivi
        diversi che non si possono distinguere con certezza:
          - errori nella legge stessa (la L.87/2026 ha due commi "2" nell'art.7,
            entrambi reali e con testo diverso);
          - articoli di novella, che citano testualmente i commi di un'altra
            norma e ne riportano la numerazione (art.52).
        In entrambi i casi il testo va preservato: perdere contenuto normativo
        e' il danno peggiore. Gli id vengono resi univoci e il comma fuori
        sequenza viene marcato, cosi' l'anomalia resta visibile invece di
        sparire in un MERGE.
        """
        nonlocal comma_corrente, buffer
        if articolo_corrente is not None:
            testo = unisci(buffer)
            if testo:
                commi = articolo_corrente["commi"]
                # Le leggi anteriori agli anni 2000 non numerano i commi: il
                # testo segue direttamente "Art. 1". Senza questo ramo quegli
                # articoli resterebbero vuoti (la L.59/1974, Dichiarazione dei
                # Diritti, ne ha 16). Il testo diventa un comma implicito.
                implicito = comma_corrente is None
                numero = str(len(commi) + 1) if implicito else comma_corrente

                base = f"{articolo_corrente['id']}/c-{numero}"
                cid, n = base, 1
                esistenti = {c["id"] for c in commi}
                while cid in esistenti:
                    n += 1
                    cid = f"{base}-{n}"

                progressivo = True
                if commi and not implicito:
                    try:
                        progressivo = int(numero) > int(commi[-1]["numero"])
                    except ValueError:
                        progressivo = True

                commi.append({
                    "id": cid,
                    "numero": numero,
                    "testo": testo,
                    "numerazioneAnomala": not progressivo,
                    "commaImplicito": implicito,
                })
        comma_corrente = None
        buffer = []

    def id_articolo(numero, i):
        """
        Id univoco dell'articolo, e riconoscimento del secondo atto.

        Se l'id e' gia' stato usato e sopra l'intestazione c'e' quella di un
        altro atto (RE_MARCATORE_ATTO), da qui in avanti gli articoli vanno
        in una parte con un segmento di id proprio. Senza marcatore l'id
        viene comunque reso unico: un id ripetuto, a valle, e' un testo che
        ne cancella un altro.
        """
        nonlocal parte_corrente
        slug = numero.replace(" ", "-")

        def costruisci():
            base = f"{id_norma}/{parte_corrente}" if parte_corrente else id_norma
            return f"{base}/art-{slug}"

        candidato = costruisci()
        if candidato in ids_articoli:
            marcatore = _marcatore_atto(righe, i)
            if marcatore:
                parte, n = marcatore, 1
                while parte in parti_usate:
                    n += 1
                    parte = f"{marcatore}-{n}"
                parti_usate.add(parte)
                parte_corrente = parte
                candidato = costruisci()
        reso_univoco = candidato in ids_articoli
        base, n = candidato, 1
        while candidato in ids_articoli:
            n += 1
            candidato = f"{base}-{n}"
        ids_articoli.add(candidato)
        return candidato, reso_univoco

    def id_partizione(tipo, numero):
        """Il percorso rende l'id unico: i Capi si rinumerano dentro ogni Titolo."""
        base = f"{id_norma}"
        if tipo.upper() != "TITOLO" and titolo_corrente:
            base += f"/tit-{titolo_corrente['numero']}"
        base += f"/{tipo.lower()}-{numero}"
        candidato, n = base, 1
        while candidato in ids_usati:   # la L.87/2026 ha due "CAPO IV" nello stesso titolo
            n += 1
            candidato = f"{base}-{n}"
        ids_usati.add(candidato)
        return candidato

    i = 0
    while i < len(righe):
        riga = righe[i].strip()

        if not riga:
            i += 1
            continue

        # --- Fine del dispositivo: formula di promulgazione ---
        # Da qui in poi non e' piu' testo dell'ultimo articolo: e' un
        # allegato (trattato, statuto, tabella). Si chiude il comma in corso
        # e si esce dal ciclo, cosi' il riconoscitore non rientra in
        # modalita' "cerco Art. N" sul contenuto dell'allegato - che e' esatto
        # il modo in cui DC-52-2016 finiva per assorbire i 20 articoli di un
        # trattato ONU come fossero suoi.
        if articolo_corrente is not None and _cerca_promulgazione(righe, i):
            chiudi_comma()
            resto = righe[i:]
            allegato_testo = unisci(resto)
            allegato_ha_struttura_propria = _ha_struttura_propria(resto)
            break

        m_part = RE_PARTIZIONE.match(riga)
        m_art = RE_ARTICOLO.match(riga)

        # --- Partizione: TITOLO / CAPO / SEZIONE ---
        if m_part:
            chiudi_comma()
            articolo_corrente = None
            iniziato = True
            tipo = m_part.group(1).upper().capitalize()
            numero = m_part.group(2).upper()
            rubrica = righe[i + 1].strip() if i + 1 < len(righe) else ""
            nodo = {
                "id": id_partizione(tipo, numero),
                "tipo": tipo,
                "numero": numero,
                "rubrica": rubrica,
                "ordine": len(partizioni),
            }
            if tipo.upper() == "TITOLO":
                nodo["figli"] = []
                partizioni.append(nodo)
                titolo_corrente = nodo
                capo_corrente = None
            else:
                if titolo_corrente:
                    titolo_corrente["figli"].append(nodo)
                else:
                    nodo["figli"] = []
                    partizioni.append(nodo)
                capo_corrente = nodo
            i += 2  # salta la rubrica
            continue

        # --- Articolo ---
        if m_art:
            chiudi_comma()
            iniziato = True
            numero = m_art.group(1) + (f" {m_art.group(2).lower()}" if m_art.group(2) else "")
            genitore = capo_corrente or titolo_corrente
            aid, reso_univoco = id_articolo(numero, i)
            articolo_corrente = {
                "id": aid,
                "numero": numero,
                "parte": parte_corrente,
                "rubrica": None,
                "partizioneId": genitore["id"] if genitore else None,
                "ordine": len(articoli),
                "commi": [],
            }
            if reso_univoco:
                # nessun marcatore ha spiegato la collisione: l'id e' stato
                # comunque reso unico, cosi' il testo non sparisce. main() lo
                # dichiara a fine parsing.
                articolo_corrente["idResoUnivoco"] = True
            articoli.append(articolo_corrente)
            attesa_rubrica = True
            rubrica_buffer = []
            i += 1
            continue

        # --- Rubrica dell'articolo: fra parentesi o breve titolo su riga singola ---
        if attesa_rubrica:
            if riga.startswith("(") or rubrica_buffer:
                rubrica_buffer.append(riga)
                # La parentesi puo' essere seguita da punteggiatura: senza
                # tollerarla, "(Iscrizione dei ricavi ...)." non chiudeva il
                # buffer, che continuava a inghiottire i commi fino
                # all'articolo successivo. Misurato: 38 articoli restavano del
                # tutto vuoti, corpo compreso.
                if riga.rstrip().rstrip(".:;,").endswith(")"):
                    testo = unisci(rubrica_buffer)
                    articolo_corrente["rubrica"] = testo.strip(" .:;,").strip("()").strip()
                    articolo_corrente["_rubricaVera"] = True
                    attesa_rubrica = False
                    rubrica_buffer = []
                elif len(rubrica_buffer) >= 3:
                    # Una rubrica non occupa tre righe: se non si e' chiusa,
                    # non era una rubrica. Si restituisce tutto al testo invece
                    # di perderlo.
                    for r in rubrica_buffer:
                        buffer.append(r)
                    rubrica_buffer = []
                    attesa_rubrica = False
                i += 1
                continue
            elif not m_art and not m_part and not RE_COMMA.match(riga) and not RE_COMMA_INLINE.match(riga) and _puo_essere_rubrica(riga):
                articolo_corrente["rubrica"] = riga.rstrip(".:").strip()
                # Presunta, non certa: negli atti storici un articolo e' spesso
                # una frase sola, e questa regola gliela porta via lasciandolo
                # senza testo. Si segna la provenienza e si decide a fine
                # analisi, quando si sa se sono arrivati dei commi.
                articolo_corrente["_rubricaPresunta"] = riga.rstrip(".:").strip()
                attesa_rubrica = False
                i += 1
                continue
            attesa_rubrica = False   # articolo senza rubrica: non deve bloccare

        # --- Comma ---
        m_comma = RE_COMMA.match(riga)
        m_comma_inline = RE_COMMA_INLINE.match(riga)
        if articolo_corrente is not None and (m_comma or m_comma_inline):
            chiudi_comma()
            if m_comma:
                comma_corrente = m_comma.group(1)
            else:
                comma_corrente = m_comma_inline.group(1)
                buffer = [m_comma_inline.group(2)]
            i += 1
            continue

        # --- Testo corrente ---
        if articolo_corrente is not None:
            buffer.append(riga)
        elif not iniziato:
            preambolo.append(riga)
        i += 1

    chiudi_comma()

    # Se non e' stato riconosciuto nemmeno un articolo, l'atto non e' vuoto:
    # e' scritto con una struttura che il riconoscitore non prevede. Meglio
    # dedurla e dichiararla che lasciare il testo fuori dalla ricerca.
    if not articoli:
        articoli, preambolo = struttura_dedotta(id_norma, righe)

    # Un articolo senza nemmeno un comma ha perso il proprio testo. Quando la
    # rubrica era stata solo presunta - riga corta chiusa da un punto - quella
    # riga E' il testo dell'articolo: "Art. 12. / I registri dello Stato Civile
    # costituiscono una raccolta di atti pubblici." e' un articolo di una frase,
    # non un titolo. Si restituisce al testo invece di lasciarlo fuori dalla
    # ricerca.
    for art in articoli:
        presunta = art.pop("_rubricaPresunta", None)
        art.pop("_rubricaVera", None)
        if art["commi"] or not presunta:
            continue
        art["commi"].append({
            "id": f"{art['id']}/c-1",
            "numero": "1",
            "testo": presunta if presunta.endswith((".", ":", "!", "?")) else presunta + ".",
            "numerazioneAnomala": False,
            "commaImplicito": True,
        })
        art["rubrica"] = None

    # Citazioni: per comma, con l'indicazione del comma di origine.
    for art in articoli:
        art["citazioni"] = []
        for c in art["commi"]:
            for cit in estrai_citazioni(c["testo"], id_norma):
                cit["commaId"] = c["id"]          # l'id vero, non ricostruito dal numero
                cit["commaOrigine"] = c["numero"]
                art["citazioni"].append(cit)

    testo_preambolo = unisci(preambolo)
    citazioni_preambolo = estrai_citazioni(testo_preambolo, id_norma)

    return {
        **meta,
        "preambolo": testo_preambolo,
        "citazioniPreambolo": citazioni_preambolo,
        "partizioni": partizioni,
        "articoli": articoli,
        "allegatoPostPromulgazione": allegato_testo,
        "allegatoHaStrutturaPropria": allegato_ha_struttura_propria,
    }


_PROVE_STRUTTURA_DEDOTTA = [
    # numerazione decimale che ricomincia in una sezione successiva
    ("1.1 Le presenti norme si applicano agli edifici civili.",
     "1.2 Sono esclusi gli edifici industriali.",
     "2.1 Le autorimesse rispettano le distanze.",
     "1.1 Le presenti norme riguardano gli impianti a gas."),
]
for _righe_test in _PROVE_STRUTTURA_DEDOTTA:
    _d = parse("T-2-2000", {}, righe=list(_righe_test))
    _id_commi = [c["id"] for a in _d["articoli"] for c in a["commi"]]
    assert len(set(_id_commi)) == len(_id_commi), f"id di comma ripetuti: {_id_commi}"
    _testi = " ".join(c["testo"] for a in _d["articoli"] for c in a["commi"])
    for _r in _righe_test:
        assert _r.split(" ", 1)[1] in _testi, f"testo perso: {_r!r}"


_PROVE_DUE_ATTI = [
    ("due atti nello stesso PDF: il secondo rinumera da 1",
     ["Art. 1", "1.", "Prima norma della legge.", "Art. 2", "1.",
      "Seconda norma della legge.", "", "REGOLAMENTO", "",
      "Art. 1", "1.", "Prima norma del regolamento."],
     ["T-1-2000/art-1", "T-1-2000/art-2", "T-1-2000/reg/art-1"],
     [None, None, "reg"]),
    ("numerazione continua: niente parti, id invariati",
     ["Art. 1", "1.", "Prima norma.", "Art. 2", "1.", "Seconda norma.",
      "Art. 3", "1.", "Terza norma."],
     ["T-1-2000/art-1", "T-1-2000/art-2", "T-1-2000/art-3"],
     [None, None, None]),
    ("riparte da 1 senza marcatore: solo la rete di sicurezza",
     ["Art. 1", "1.", "Prima norma.", "Art. 1", "1.", "Prima norma di un altro atto."],
     ["T-1-2000/art-1", "T-1-2000/art-1-2"],
     [None, None]),
]
for _nome, _righe_test, _attesi, _parti in _PROVE_DUE_ATTI:
    _d = parse("T-1-2000", {}, righe=_righe_test)
    _ids = [a["id"] for a in _d["articoli"]]
    assert _ids == _attesi, f"due atti ({_nome}): {_ids}"
    assert [a["parte"] for a in _d["articoli"]] == _parti, f"parte ({_nome})"
    _id_commi = [c["id"] for a in _d["articoli"] for c in a["commi"]]
    assert len(set(_id_commi)) == len(_id_commi), f"id di comma ripetuti ({_nome})"
    # nessun testo perso: ogni riga di contenuto finisce in un comma
    _testi = " ".join(c["testo"] for a in _d["articoli"] for c in a["commi"])
    for _r in _righe_test:
        if _r.endswith(".") and " " in _r:      # riga di testo, non un numero di comma
            assert _r in _testi, f"testo perso ({_nome}): {_r!r}"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def main(force=False):
    PARSED.mkdir(parents=True, exist_ok=True)
    cartelle = sorted(p for p in RAW.iterdir() if p.is_dir())
    if not cartelle:
        raise RuntimeError("data/raw/ e' vuota: eseguire prima 01_scrape.py")

    da_parsare = []
    saltati = []
    for c in cartelle:
        if not (c / "scheda.json").exists() or not (c / "testo.pdf").exists():
            continue
        if not force and (PARSED / f"{c.name}.json").exists():
            continue
        # Gli Statuti hanno un integratore dedicato. Qui la struttura non viene
        # riconosciuta - "RUBRICA I." al posto di "Art. 1" - e si ripiega su
        # struttura_dedotta, che produce un unico articolo. Con --force questo
        # calpestava i file buoni: il Libro Primo del 1600 passava da 124
        # articoli e 4.630 commi a 1 articolo e 153 commi. Si saltano.
        if c.name.startswith("S-"):
            saltati.append(c.name)
            continue
        da_parsare.append(c)

    print(f"File totali su disco: {len(cartelle)}. Nuovi da parsare: {len(da_parsare)}.")
    if saltati:
        print(f"Statuti saltati ({len(saltati)}): li integra "
              f"integra_tutti_i_12_statuti.py. Se i loro file mancassero, "
              f"ricostruiscili con scripts/ricostruisci_statuti_parsed.py")
    errori = 0
    for idx, cartella in enumerate(da_parsare, 1):
        try:
            meta = json.loads((cartella / "scheda.json").read_text(encoding="utf-8"))
            dati = parse(cartella.name, meta)

            n_capi = sum(len(t.get("figli", [])) for t in dati["partizioni"])
            n_commi = sum(len(a["commi"]) for a in dati["articoli"])
            n_cit = sum(len(a["citazioni"]) for a in dati["articoli"])

            univoci = [a["id"] for a in dati["articoli"] if a.get("idResoUnivoco")]
            if univoci:
                print(f"  {cartella.name}: {len(univoci)} id di articolo gia' usati, "
                      f"resi univoci senza riconoscere un secondo atto: "
                      f"{', '.join(univoci[:5])}")

            if idx % 50 == 0 or idx == len(da_parsare):
                print(f"  [{idx}/{len(da_parsare)}] {cartella.name}: {len(dati['articoli'])} art, {n_commi} commi, {n_cit} cit")

            (PARSED / f"{cartella.name}.json").write_text(
                json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            errori += 1
            print(f"  Errore nel parsing di {cartella.name}: {e}")

    tot_parsed = len(list(PARSED.glob("*.json")))
    print(f"\nParsing completato: {tot_parsed} file pronti in data/parsed/ (errori: {errori}).")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
