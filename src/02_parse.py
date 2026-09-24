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

    .venv/Scripts/python.exe src/02_parse.py                     # solo i nuovi
    .venv/Scripts/python.exe src/02_parse.py --atti <file.json>  # rilegge gli atti elencati
"""

import json
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comune import PREFISSI, norma_id  # noqa: E402
from allegati import allegati_tabellari  # noqa: E402
from articoli import ristruttura_articoli  # noqa: E402
from commi import RE_PROMULGAZIONE, ristruttura  # noqa: E402

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
# riga ("Art. 21 - Rubrica") la prende RE_ARTICOLO_ESTESO, qui sotto.
#
# Il trattino prima del suffisso ("Art. 5-bis") e' la forma piu' usata dalle
# novelle: 341 intestazioni in 136 documenti. In una parte dei documenti quelle
# righe sono articoli CITATI ("Dopo l'articolo 44 e' inserito il seguente
# articolo: Art. 44-bis"): si accetta perche' c'e' il riconoscimento del testo
# citato (righe_citate). Il trattino lungo resta escluso: in L-59-2016
# "Articolo 9 –" e' una voce del sommario, e accettarla creava 42 doppioni.
RE_ARTICOLO = re.compile(
    r"^(?:Art\.?|Articolo)\s*(\d+|[Uu]nico)\s*[°º]?\.?\s*-?\s*"
    r"(bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies)?\.?\s*"
    r"(?:\(\d+\))?\s*[-:.]?\s*$", re.I)

_PROVE_ARTICOLO = [
    ("Art. 5", "5"),
    ("Articolo unico", "unico"),
    ("Art. 5 bis", "5 bis"),
    # senza punto
    ("Art 19", "19"),
    ("Art 4.", "4"),
    ("Art 7 - L'imposta e' dovuta", None),       # testo sulla riga: non e' la riga del solo numero
    # richiamo di nota
    ("Art. 23 (23)", "23"),
    ("Art. 54. (10)", "54"),
    ("Art. 106.(12)", "106"),
    ("Art. 3 (Oggetto)", None),                   # rubrica sulla riga: RE_ARTICOLO_ESTESO
    # grado
    ("Art. 12°", "12"),
    ("Articolo 7°", "7"),
    ("Art 11° - I due segretari terranno il registro", None),
    ("Art. 12° bis", "12 bis"),
    # trattino prima del suffisso
    ("Art.1-bis", "1 bis"),
    ("Art. 44-bis", "44 bis"),
    ("Art. 5 - quater", "5 quater"),
    ("Art.9-bis.", "9 bis"),
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

# Dopo la formula di promulgazione le grafie in piu' di RE_ARTICOLO non
# valgono: sono misurate sul dispositivo, e in un allegato "Art 13" senza punto
# e' spesso il rinvio di una tabella. Con la regex larga DC-36-2020 e
# L-108-2011 arrivavano a ripetere un numero oltre la soglia di 03_load.py, e
# sarebbero usciti dal grafo.
RE_ARTICOLO_DOPO_FIRMA = re.compile(r"^(?:Art\.|Articolo)\s*(\d+|[Uu]nico)\.?\s*(bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies)?\s*[-:.]?\s*$", re.I)

# L'intestazione con la rubrica sulla stessa riga, o fra trattini: "Art. 1
# (Prima seduta della legislatura)", "Art.1 - Quorum per la validita' delle
# deliberazioni", "- Art. 3 -". RE_ARTICOLO vuole la riga col solo numero, e
# queste righe finivano nel testo: la L-21-1981 (53 articoli) era un articolo
# unico, lo Statuto allegato al D-100-1995 spariva del tutto. Si accettano
# solo in sequenza (vedi parse), perche' "Art. 3 Legge n.5/2000" a inizio riga
# puo' essere il seguito di una frase.
RE_ARTICOLO_ESTESO = re.compile(
    r"^[-–—\s]*(?i:Art\.|Articolo)\s*(\d{1,3})\s*"
    r"((?i:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies))?\s*"
    r"(?:[-–—:.]\s*)?"
    r"(?:\((?P<tra_parentesi>[^()]{1,150})\)|(?P<in_linea>[A-ZÀ-ÖØ-Ý\"«'][^;]{2,160}?))?"
    r"\s*[-–—]*\s*$")
# Un comma aggiunto da una novella prende il suffisso ordinale, come gli
# articoli: "All'articolo 97 e' aggiunto il seguente comma 1-bis)". Senza
# riconoscerlo, "1 bis." resta testo e il comma novellato si fonde con quello
# che lo precede (misurate 572 righe in 228 documenti). Il numero prende la
# forma "1-bis", la stessa dell'id degli articoli bis.
#
# RE_COMMA_INLINE ha tre gruppi - numero, suffisso, testo - e il testo e'
# group(3): chi rimette group(2) mette il suffisso al posto del comma.
SUFFISSO_ORDINALE = (r"(bis|ter|quater|quinquies|sexies|septies|octies"
                     r"|nonies|decies)")
RE_COMMA = re.compile(rf"^(\d+)(?:(?:\s*-\s*|\s+){SUFFISSO_ORDINALE})?\.\s*$", re.I)
RE_COMMA_INLINE = re.compile(
    rf"^(\d+)(?:(?:\s*-\s*|\s+){SUFFISSO_ORDINALE})?\.\s+(\S.*)$", re.I)


def numero_comma(m):
    """Numero del comma da RE_COMMA/RE_COMMA_INLINE, suffisso compreso."""
    return m.group(1) + (f"-{m.group(2).lower()}" if m.group(2) else "")


_PROVE_COMMA = [
    ("1.", "1", None),
    ("12.", "12", None),
    ("2 bis.", "2-bis", None),
    ("3-ter.", "3-ter", None),
    ("4 QUATER.", "4-quater", None),
    ("1-bis. Il canone e' dovuto per intero.", "1-bis", "Il canone e' dovuto per intero."),
    ("5. Il termine decorre dalla notifica.", "5", "Il termine decorre dalla notifica."),
    # negativi: senza punto e' un riferimento, con la parentesi e' un elenco
    ("5 quinquies", None, None),
    ("1)", None, None),
    ("1-bis)", None, None),
    ("Art. 5 bis", None, None),
    ("bis.", None, None),
]
for _riga, _atteso, _testo in _PROVE_COMMA:
    _m = RE_COMMA.match(_riga) or RE_COMMA_INLINE.match(_riga)
    assert (numero_comma(_m) if _m else None) == _atteso, f"RE_COMMA: {_riga!r}"
    if _testo is not None:
        assert _m.group(3) == _testo, f"testo inline: {_riga!r}"

# Una citazione normativa: tipo, eventuale data estesa, numero, eventuale /anno.
RE_CITAZIONE = re.compile(
    # L'ordine conta: le alternative vanno dalla piu' specifica alla piu'
    # generica. Con "Legge" davanti, "Decreto Legge n.89/2014" veniva letto
    # come "Legge n.89/2014" e la norma finiva sotto l'id sbagliato.
    #
    # Forme che si perdevano, misurate sul corpus il 17/09 (circa 2.300
    # citazioni): la virgola fra anno e numero ("27 febbraio 1947, n. 2",
    # 1.444), le abbreviazioni ("D.D. n.128/2013", "L.40/1998", 572), il
    # plurale ("Leggi 28 giugno 1974 n. 46", 221), "del" davanti alla data
    # ("Decreto del 24 marzo 1993 n.50", 118), "Decreto Consigliare" e
    # "Decreto-Legge". Il tipo abbreviato lo scioglie tipo_citato().
    r"(?<![A-Za-z\u00c0-\u00ff])"
    r"(?P<tipo>Legge\s+Costituzionale|Legge\s+Qualificata"
    r"|Decreto\s+Delegato|Decreto(?:\s*[-–—]\s*|\s+)Legge|Decreto\s+Reggenziale"
    r"|Decreto\s+Consi(?:g)?liare|Decreto|Regolamento|Leggi|Legge"
    # Statuto, Notifica, Ordinanza, Verbale ed Errata Corrige mancavano pur
    # essendo tipi che comune.PREFISSI sa gia' tradurre in un id: 338
    # documenti citavano un atto di questi tipi senza che il rinvio venisse
    # riconosciuto (389 occorrenze stimate).
    r"|Errata\s+Corrige|Notifica|Ordinanza|Verbale|Statuto"
    r"|L\.\s?C\.|L\.\s?Q\.|D\.\s?D\.|D\.\s?L\.|D\.\s?C\.|L\.)"
    r"\s*(?:del\s+)?"
    # "1° marzo 2010": il primo del mese si scrive con l'ordinale, e senza il
    # simbolo qui la citazione intera andava persa - 120 nel corpus, 36 verso
    # la Legge 1° marzo 2010 n.42 sul trust.
    r"(?:(?P<giorno>\d{1,2})\s*[°º]?\s+(?P<mese>gennaio|febbraio|marzo|aprile|maggio|giugno"
    r"|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(?P<anno_data>\d{4})\s*,?\s*)?"
    # "n." puo' mancare solo nella forma con la barra ("L. 40/1998"):
    # citazione_leggibile() scarta il resto.
    r"(?P<n>n\s*[.°º]\s*[°º]?\s*)?(?P<numero>\d+)"
    r"(?:\s*/\s*(?P<anno_slash>\d{4}))?",
    re.I,
)

ABBREVIAZIONI = {
    "l.": "Legge", "leggi": "Legge", "l.c.": "Legge Costituzionale",
    "l.q.": "Legge Qualificata", "d.d.": "Decreto Delegato",
    "d.l.": "Decreto Legge", "d.c.": "Decreto Consiliare",
}


def tipo_citato(m):
    """Il tipo d'atto di una citazione, per esteso."""
    grezzo = " ".join(m.group("tipo").split())
    return ABBREVIAZIONI.get(re.sub(r"\s", "", grezzo).lower(), grezzo.title())


def citazione_leggibile(m):
    """L'anno della citazione, None se non si puo' identificare la norma, o
    False se il riscontro non e' una citazione.

    Senza "n." si accetta solo numero/anno con un anno plausibile: "Legge 5"
    o "L. 30/40" non citano nulla.
    """
    anno = m.group("anno_slash") or m.group("anno_data")
    if not m.group("n"):
        if not m.group("anno_slash") or not 1600 <= int(m.group("anno_slash")) <= 2099:
            return False
    return int(anno) if anno else None


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
          r"|dell|allegato|[IVXLC]+|\d+|[a-z]\)|[a-z](?![a-z]))")
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
    ("all'articolo 14 dell'Allegato A della ", "14"),
    ("l'articolo 58, comma 3, dell'Allegato A alla ", "58"),
]
for _testo, _atteso in _PROVE_BERSAGLIO:
    _m = RE_BERSAGLIO.search(_testo)
    assert (_m.group(1) if _m else None) == _atteso, f"RE_BERSAGLIO: {_testo!r}"

# "l'articolo 14 dell'Allegato A alla Legge n.188/2011": l'articolo e' quello
# dell'allegato, che articoli.py numera "all-14". Agganciarlo all'art. 14 della
# legge sarebbe sbagliato; prima della separazione degli articoli fusi era
# ambiguo, perche' i due stavano nello stesso nodo.
RE_IN_ALLEGATO = re.compile(r"\bdell['’]\s*allegat", re.I)


def articolo_citato(bersaglio):
    """Il numero d'articolo agganciato da RE_BERSAGLIO, con l'allegato se c'e'."""
    numero = bersaglio.group(1)
    return f"all-{numero}" if RE_IN_ALLEGATO.search(bersaglio.group(0)) else numero



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
        return {
            "id": f"{art['id']}/c-{numero}",
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


# Cio' che puo' precedere l'intestazione di un atto nel suo preambolo: niente,
# un numero di pagina, "REPUBBLICA DI SAN MARINO".
RE_PRIMA_INTESTAZIONE = re.compile(r"\s*(?:\d+\s+)?(?:repubblica\s+di\s+san\s+marino\s*)?", re.I)


def estrai_citazioni(testo, id_norma_corrente, preambolo=False):
    """
    Trova i riferimenti ad altre norme nel testo.
    Scarta l'autocitazione: una legge che cita se stessa non e' una dipendenza.

    Nel preambolo scarta anche l'intestazione dell'atto stesso. Il preambolo
    comincia spesso con "DECRETO 20 settembre 2004 n. 119": se l'archivio
    tiene l'atto come Decreto Consiliare (DC-119-2004), l'id letto (D-119-2004)
    e' diverso e la riga diventava la citazione di un atto che non esiste - 724
    archi il 17/09. Si riconosce dalla posizione - in apertura, al piu' dopo
    "REPUBBLICA DI SAN MARINO" - e da numero e anno uguali: un errata corrige
    che cita l'atto che corregge, stesso numero e stesso anno, lo fa dopo
    "ERRATA CORRIGE AL" e resta.
    """
    proprio = re.match(r"^[A-Z]+-(\d+)-(\d{4})", id_norma_corrente or "")
    citazioni = []
    for m in RE_CITAZIONE.finditer(testo):
        anno = citazione_leggibile(m)
        if anno is False:
            continue
        tipo = tipo_citato(m)
        numero = int(m.group("numero"))

        if (preambolo and proprio and RE_PRIMA_INTESTAZIONE.fullmatch(testo[:m.start()])
                and (str(numero), str(anno)) == proprio.groups()):
            continue  # intestazione dell'atto stesso

        prima = testo[max(0, m.start() - 90):m.start()]
        bersaglio = RE_BERSAGLIO.search(prima)
        art_citato = articolo_citato(bersaglio) if bersaglio else None
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


assert [(c["numero"], c["anno"], c["articoloCitato"]) for c in estrai_citazioni(
    "L'articolo 1, comma 1, lettera b) della Legge 1° marzo 2010 n.42 è così modificato", "L-123-2019")
] == [(42, 2010, "1")]


for _riga, _atteso in [
    ("Art. 1 (Prima seduta della legislatura)", ("1", "Prima seduta della legislatura", None)),
    ("Art.12- Rappresentanza e difesa davanti al Collegio", ("12", None, "Rappresentanza e difesa davanti al Collegio")),
    ("- Art. 3 -", ("3", None, None)),
    ("Art. 4 bis (Deroghe)", ("4", "Deroghe", None)),
    ("Art. 5 della Legge 12 marzo 2003 n.4", None),
    ("Art. 2 (1)", ("2", "1", None)),
]:
    _m = RE_ARTICOLO_ESTESO.match(_riga)
    assert (_m and (_m.group(1), _m.group("tra_parentesi"), _m.group("in_linea"))) == _atteso or \
        (_m is None and _atteso is None), (_riga, _m and _m.groupdict())

_PROVE_CITAZIONE = [
    ("la Legge 17 marzo 2005, n. 37 e' abrogata", ("Legge", 37, 2005)),
    ("ai sensi della Legge del 17 marzo 2005 n. 37", ("Legge", 37, 2005)),
    ("le Leggi 17 marzo 2005 n.38 e", ("Legge", 38, 2005)),
    ("ex art.4 del D.D. n.128/2013 nei", ("Decreto Delegato", 128, 2013)),
    ("come previsto dalla L.40/1998", ("Legge", 40, 1998)),
    ("il D.L. 36/2011 ha", ("Decreto Legge", 36, 2011)),
    ("la L. C. n. 185/2005", ("Legge Costituzionale", 185, 2005)),
    ("Decreto Consigliare del 30 giugno 1934, n.8", ("Decreto Consigliare", 8, 1934)),
    ("il Decreto-Legge n. 89/2014", ("Decreto-Legge", 89, 2014)),
    ("Legge 5 dicembre 2011 n.189", ("Legge", 189, 2011)),
    ("la Legge 5 e la tabella L. 30/40", None),
    ("nel decreto 12 marzo 2020 recante", None),
    ("dell'art. 3 del. 5/2020", None),
]
for _testo, _atteso in _PROVE_CITAZIONE:
    _c = estrai_citazioni(_testo, "X-1-1900")
    _letto = (_c[0]["tipo"], _c[0]["numero"], _c[0]["anno"]) if _c and _c[0]["anno"] else None
    assert _letto == _atteso, f"RE_CITAZIONE: {_testo!r} -> {_letto}"
# I cinque tipi aggiunti: un tipo in piu' nell'alternanza sposta l'id di
# destinazione della citazione.
_PROVE_TIPI_CITAZIONE = [
    ("ai sensi dello Statuto n.12/1600", ("Statuto", 12, 1600)),
    ("vista la Notifica n.4/2019", ("Notifica", 4, 2019)),
    ("richiamata l'Ordinanza n.7/2020", ("Ordinanza", 7, 2020)),
    ("visto il Verbale n.3/2018", ("Verbale", 3, 2018)),
    ("come da Errata Corrige n.9/2015", ("Errata Corrige", 9, 2015)),
    ("la Legge 29 luglio 2014 n.125", ("Legge", 125, 2014)),
    ("il Decreto Delegato n.62/2008", ("Decreto Delegato", 62, 2008)),
    # non sono citazioni normative: manca il numero d'atto
    ("lo statuto della societa' per azioni X", None),
    ("lo statuto della societa' X n.5 del registro", None),
    ("il verbale della seduta del Consiglio", None),
]
for _testo, _atteso in _PROVE_TIPI_CITAZIONE:
    _c = estrai_citazioni(_testo, "X-1-1900")
    _letto = (_c[0]["tipo"], _c[0]["numero"], _c[0]["anno"]) if _c else None
    assert _letto == _atteso, f"RE_CITAZIONE: {_testo!r} -> {_letto}"
assert norma_id("Errata Corrige", 9, 2015) == "EC-9-2015"
assert norma_id("Statuto", 12, 1600) == "S-12-1600"
assert norma_id("Decreto Consigliare", 8, 1934) == "DC-8-1934"
assert norma_id("Decreto-Legge", 89, 2014) == "DL-89-2014"
assert estrai_citazioni("DECRETO 20 settembre 2004 n. 119 REPUBBLICA DI SAN MARINO", "DC-119-2004", preambolo=True) == []
assert estrai_citazioni("REPUBBLICA DI SAN MARINO DECRETO – LEGGE 31 gennaio 2007 n.10 Noi Capitani",
                        "D-10-2007", preambolo=True) == []
assert estrai_citazioni("1 REPUBBLICA DI SAN MARINO DECRETO - LEGGE 2 maggio 2011 n.73 Noi",
                        "DL-73-2011", preambolo=True) == []
assert len(estrai_citazioni("REPUBBLICA DI SAN MARINO ERRATA CORRIGE AL DECRETO DELEGATO 14 FEBBRAIO 2008 N.29",
                            "EC-29-2008", preambolo=True)) == 1
assert len(estrai_citazioni("Regolamento 7 Marzo 1914 per l'applicazione della superiore Legge. (Legge 7 Marzo 1914 N. 4)",
                            "R-4-1914", preambolo=True)) == 1
assert [c["tipo"] for c in estrai_citazioni("del Decreto – Legge n. 93/2017", "X-1-1900")] == ["Decreto – Legge"]
assert norma_id("Decreto – Legge", 93, 2017) == "DL-93-2017"


# Una voce d'indice: il titolo seguito dai puntini e dal numero di pagina,
# "Oggetto della Convenzione ....... 35".
RE_VOCE_INDICE = re.compile(r"\.{4,}\s*\d{1,4}\s*$")


def _indice_iniziale(righe):
    """Le righe di un indice: "Art.1 - ...", "Art.2 - ..." una sotto l'altra,
    prima che il testo ricominci da "Art. 1". Restano testo, non articoli: il
    R-1-2004 apre con l'indice dei suoi 56 articoli, la L-2-2015 con quello dei
    suoi 46, e poi il testo usa intestazioni semplici ("Art. 1"). La ripartenza
    si cerca percio' fra tutte le intestazioni, non solo fra quelle estese.
    Le voci coi puntini e il numero di pagina sono indice comunque.
    """
    estese, tutte = [], []
    for k, r in enumerate(righe):
        riga = r.strip()
        if RE_ARTICOLO.match(riga):
            m = re.match(r"^(?:Art\.|Articolo)\s*(\d+)", riga, re.I)
            if m:
                tutte.append((k, int(m.group(1))))
        elif (m := RE_ARTICOLO_ESTESO.match(riga)):
            estese.append((k, int(m.group(1))))
            tutte.append((k, int(m.group(1))))
    fuori = {k for k, r in enumerate(righe) if RE_VOCE_INDICE.search(r.strip())
             and (RE_ARTICOLO_ESTESO.match(r.strip()) or re.match(r"^\s*(?:Art\.|Articolo)", r.strip(), re.I))}
    primo = next((pos for pos, (_, n) in enumerate(estese) if n == 1), None)
    if primo is None:
        return fuori
    inizio = estese[primo][0]
    ripresa = next((k for k, n in tutte if k > inizio and n == 1), None)
    if ripresa is None:
        return fuori
    serie = [(k, n) for k, n in estese if inizio <= k < ripresa]
    if len(serie) < 3:
        return fuori
    distanza = (serie[-1][0] - serie[0][0]) / (len(serie) - 1)
    return fuori | ({k for k, _ in serie} if distanza <= 2.5 else set())


assert _indice_iniziale(["INDICE", "Art.1 - Principi", "Art.2 - Unita'", "Art.3 - Sottosistemi",
                         "", "Art. 1", "(Principi)", "testo", "Art. 2", "testo"]) == {1, 2, 3}
assert _indice_iniziale(["Articolo 1 Oggetto della Convenzione ........ 35", "Art. 1", "testo"]) == {0}
assert _indice_iniziale(["Art. 1 (Prima seduta)", "testo", "testo", "testo", "Art. 2 (Segreteria)", "testo"]) == set()

# --- Fine del dispositivo: formula di promulgazione ---
#
# Dopo l'ultimo articolo vero, l'atto chiude quasi sempre con "Dato/Data
# dalla Nostra Residenza, addi'... d.F.R." seguito da "I CAPITANI REGGENTI" e
# i due nomi. Cio' che segue - i Segretari di Stato, e spesso un Allegato -
# non e' piu' dispositivo: un trattato, uno statuto, una tabella di bilancio.
# Misurato sul corpus: 2.967 documenti su 11.134 hanno testo dopo la formula.
# L'allegato resta nel grafo (vedi articoli.py e commi.py), ma non come testo
# dell'ultimo articolo: DD-19-2019 e DD-138-2018 avevano l'ultimo comma oltre
# il milione di caratteri, e DC-52-2016 20 articoli di un trattato ONU come
# fossero suoi. Restano fuori i decreti 1918-1943, che chiudono con una formula
# diversa: meno di 30 casi, e allargare la regex costava falsi positivi.
FINESTRA_PROMULGAZIONE = 20  # righe di preavviso: tollera interruzioni di riga/pagina
# Sotto questa lunghezza il testo dopo le firme e' un loro residuo - un nome
# spezzato dall'estrazione, "(1) Gia' separatamente pubblicato" - non un
# allegato: resta dov'e'. Misurato sulle 9.880 formule complete: 1.527
# documenti hanno fra 1 e 200 caratteri dopo le firme, e sono residui; sopra
# i 200 ci sono tabelle, accordi, regolamenti (1.375 documenti).
MIN_ALLEGATO = 200
RE_CAPITANI = re.compile(r"CAPITANI\s+REGGENTI", re.I)
RE_SEGRETARIO = re.compile(r"SEGRETARI[OA]\s+DI\s+STATO", re.I)


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


def _fine_firme(righe, i):
    """La prima riga dopo le firme della formula che inizia alla riga i.

    "I CAPITANI REGGENTI", la riga dei due nomi, poi per ogni Segretario di
    Stato la carica ("IL SEGRETARIO DI STATO / PER GLI AFFARI INTERNI") e il
    nome. E' la forma di due documenti su tre; dove l'estrazione spezza le
    lettere il residuo resta sotto MIN_ALLEGATO.
    """
    j = next((k for k in range(i, min(i + FINESTRA_PROMULGAZIONE, len(righe)))
              if RE_CAPITANI.search(righe[k])), i)
    piene = [k for k in range(j + 1, len(righe)) if righe[k].strip()]
    pos = 0
    if pos < len(piene) and not RE_SEGRETARIO.search(righe[piene[pos]]):
        pos += 1                                  # i nomi dei Capitani
    while pos < len(piene) and RE_SEGRETARIO.search(righe[piene[pos]]):
        pos += 1
        while pos < len(piene) and (righe[piene[pos]].strip().isupper()
                                    or re.match(r"^\s*(?:E\s+)?PER\s", righe[piene[pos]], re.I)
                                    or RE_SEGRETARIO.search(righe[piene[pos]])):
            pos += 1                              # il resto della carica
        pos += 1                                  # il nome del Segretario
    return piene[pos] if pos < len(piene) else len(righe)


def _taglio_allegato(righe, i):
    """La riga da cui comincia l'allegato dopo la formula alla riga i, o None."""
    fine = _fine_firme(righe, i)
    return fine if len(unisci(righe[fine:])) > MIN_ALLEGATO else None


_PROVE_PROMULGAZIONE = [
    # _cerca_promulgazione(righe, 0) replica esattamente come il ciclo
    # principale la interroga: la riga 0 di ogni fixture e' la riga che il
    # ciclo starebbe processando in quel momento.
    ("caso semplice",
     ["Dato dalla Nostra Residenza, addì 23 luglio 2015/1714 d.F.R", "",
      "I CAPITANI REGGENTI", "Andrea Belluzzi – Roberto Venturini"], True),
    ("interruzione di riga anomala fra 'Dato' e 'dalla Nostra Residenza'",
     ["Dato", "dalla Nostra", "Residenza, addì 16 luglio 2019/1718 d.F.R.", "",
      "I CAPITANI REGGENTI", "Nicola Selva - Michele Muratori"], True),
    ("trattino normale invece di en-dash fra i nomi: nessuna differenza attesa",
     ["Data dalla Nostra Residenza, addì 2 marzo 2020/1719 d.F.R", "",
      "I CAPITANI REGGENTI", "Luca Boschi - Mariella Mularoni"], True),
    ("nessuna formula: testo normativo qualunque",
     ["1. Il presente regolamento disciplina l'accesso agli atti.",
      "2. Si applica a tutti gli uffici pubblici."], False),
    # "Dato" nel senso comune ("dato atto di"), non l'incipit della formula
    ("'Dato' usato in un senso diverso non e' la formula di chiusura",
     ["Dato atto di quanto sopra deliberato, si procede.",
      "Restano ferme le disposizioni ordinarie in materia di bilancio."], False),
    # una voce di bilancio che nomina i Capitani Reggenti (L-115-2019)
    ("riga che non inizia con 'Dato'/'Data': mai la formula",
     ["Assegni alle LL.EE. i Capitani Reggenti", "1-2-1230", " 178.000,00"], False),
]
for _nome, _righe_test, _atteso in _PROVE_PROMULGAZIONE:
    assert _cerca_promulgazione(_righe_test, 0) == _atteso, f"RE_PROMULGAZIONE ({_nome}): {_righe_test!r}"

_FIRME = ["Dato dalla Nostra Residenza, addì 23 luglio 2015/1714 d.F.R", "",
          "I CAPITANI REGGENTI", "Andrea Belluzzi – Roberto Venturini", "",
          "IL SEGRETARIO DI STATO", "PER GLI AFFARI INTERNI", "Gian Carlo Venturini"]
assert _fine_firme(_FIRME + ["ALLEGATO A"], 0) == 8
assert _fine_firme(_FIRME, 0) == 8
assert _fine_firme(["Dato dalla Nostra Residenza", "I CAPITANI REGGENTI", "A - B",
                    "IL SEGRETARIO DI STATO PER GLI AFFARI ESTERI", "Nome Uno",
                    "IL SEGRETARIO DI STATO", "PER GLI AFFARI INTERNI", "Nome Due", "Allegato"], 0) == 8
# D-192-2005: la carica ripetuta in minuscolo sotto quella in maiuscolo
assert _fine_firme(["Dato dalla Nostra Residenza", "I CAPITANI REGGENTI", "(A - B)",
                    "p. IL SEGRETARIO DI STATO", "PER GLI AFFARI INTERNI", "Il Segretario di Stato",
                    "Pier Marino Mularoni", "Allegato A"], 0) == 7
assert _taglio_allegato(_FIRME + ["(1) Già separatamente pubblicato alla data di promulgazione."], 0) is None
assert _taglio_allegato(_FIRME + ["ALLEGATO A", "TABELLA DELLE RETRIBUZIONI " * 12], 0) == 8


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


# --- Intestazione minuscola: testo andato a capo, non un articolo ---
#
# "... di cui al successivo / articolo 20." finisce su due righe, e la seconda
# ha la forma di un'intestazione. Le intestazioni vere iniziano con la
# maiuscola: misurate 114 righe minuscole in 75 documenti, ognuna un articolo
# inventato che spezza in due il comma in corso (DD-12-2017 ne ha 27).
# Vale dentro un articolo aperto e prima della formula di promulgazione. Dopo
# la formula "art. 166" in minuscolo e' la voce di una tabella delle
# violazioni, e allegati_tabellari() la riconosce proprio da li'. Prima del
# primo articolo non c'e' un comma da spezzare, e senza intestazione il testo
# finirebbe nel preambolo, fuori dalla ricerca: DD-12-2017 comincia con la
# tabella, e ci perdeva 6.719 caratteri.
def maiuscola(riga):
    return bool(riga) and not riga[0].islower()


def intestazione_articolo(riga):
    """RE_ARTICOLO, ma solo se la riga comincia con la maiuscola."""
    return RE_ARTICOLO.match(riga) if maiuscola(riga) else None


_PROVE_INTESTAZIONE = [
    ("Art. 20", "20"),
    ("ART. 5", "5"),
    ("Articolo 12", "12"),
    ("articolo 20.", None),
    ("art. 166", None),
    ("art.9.", None),
]
for _riga, _atteso in _PROVE_INTESTAZIONE:
    _m = intestazione_articolo(_riga)
    assert (_m.group(1) if _m else None) == _atteso, f"intestazione minuscola: {_riga!r}"


# --- Articoli citati da una novella, non articoli propri ---
#
# Un atto che ne modifica un altro ne riporta il testo, intestazioni comprese:
# "Il Titolo III della Legge 28 aprile 1999 n.53 e' cosi' modificato:" e
# seguono "Art. 7" ... "Art. 14", che sono articoli della legge modificata.
# Senza riconoscerli diventano articoli di questo atto: misurate 287
# intestazioni in 114 documenti (L-162-2004 ne assorbe 29 di due leggi
# diverse).
#
# La sentinella e' la riga di annuncio, non il contesto generico. Fra
# l'intestazione precedente e quella che rompe la numerazione deve esserci
# una frase di sostituzione che apre una citazione (due punti o virgolette
# aperte). Ispezionando otto PDF a mano, l'annuncio c'e' in tutti i casi veri
# e manca in tutti quelli che sembravano tali ma non lo sono:
#   LC-41-2004, LC-27-2004  il PDF scrive "Art.l" con la elle al posto
#                           dell'uno, la numerazione salta da 0 a 2;
#   L-5-1921                un secondo atto stampato in nota a pie' di pagina;
#   L-52-1947               due "Art. 4." di seguito nel testo originale.
# Il criterio precedente (una citazione qualsiasi nelle righe sopra) scattava
# su tutti e quattro.
#
# Dall'annuncio le intestazioni sono citate fino al rientro nella sequenza
# dell'atto - il numero che l'atto si aspettava - o fino alla formula di
# promulgazione. Dei 114 documenti del pattern, 71 non annunciano la citazione
# in nessun modo riconoscibile e restano come sono: vedi LIMITI_NOTI.md.
RE_ANNUNCIO_CITAZIONE = re.compile(
    r"\b(?:[eè]'?|é|sono|siano|viene|vengono|venga)\s+"
    r"(?:cos[iì]'?\s+)?(?:\w+mente\s+)?(?:cos[iì]'?\s+)?"
    r"(?:modificat|sostituit|riformulat|integrat|inserit|introdott|aggiunt)\w*"
    r"|\bsostituit\w+\s+(?:dal|dai|dalla|con)\s+(?:il\s+|i\s+|la\s+)?seguent\w+"
    r"|\bapportat\w+\s+le\s+seguenti\s+modific\w*"
    r"|\b(?:dopo|prima)\s+(?:l['’]|il\s+|la\s+)?"
    r"(?:articol|comma|allegat|titol|cap|sezion)\w*"
    r".{0,80}?\b(?:inserit|aggiunt|introdott)\w+"
    r"|\bcos[iì]'?\s+(?:\w+mente\s+)?(?:modificat|sostituit|riformulat)\w*", re.I)
# Dopo l'annuncio la citazione si apre: "... e' cosi' modificato:", oppure le
# virgolette del testo riportato ("ALLEGATO A). Senza apertura la frase parla
# di una modifica avvenuta altrove e non introduce niente.
RE_APERTURA_CITAZIONE = re.compile('[:«“"]')
# ... e quello che si apre e' una struttura: un titolo, un capo, un allegato o
# l'intestazione stessa. Se il testo riportato comincia con un comma
# ("All'articolo 97, comma 1, e' aggiunto il seguente comma 1-bis): <<1-bis)
# ...") allora la citazione non contiene articoli, e l'intestazione che segue
# piu' avanti e' dell'atto: senza questo controllo DD-19-2016 perdeva otto
# articoli veri, inghiottiti fino in fondo al documento.
RE_STRUTTURA_CITATA = re.compile(
    '^[\\s\'"«“]*(?:TITOLO|CAPO|SEZIONE|PARTE|LIBRO|ALLEGATO|TABELLA|Art)\\b', re.I)
FINESTRA_ANNUNCIO = 12   # righe non vuote sopra l'intestazione, mai oltre la precedente


def _inizio_citazione(righe, prec, i):
    """Riga da cui parte il testo citato prima dell'intestazione i, se annunciato."""
    idx = [j for j in range(prec + 1, i) if righe[j].strip()][-FINESTRA_ANNUNCIO:]
    for k, j in enumerate(idx):
        # l'annuncio puo' spezzarsi in due righe: "... e' cosi'" / "sostituito:"
        testo = " ".join(righe[x].strip() for x in idx[max(0, k - 1):k + 1])
        m = RE_ANNUNCIO_CITAZIONE.search(testo)
        if not m:
            continue
        apertura = RE_APERTURA_CITAZIONE.search(testo, m.end())
        if not apertura:
            continue
        # cosa si apre: la struttura puo' stare subito dopo i due punti,
        # oppure sulla riga seguente, oppure essere l'intestazione stessa.
        coda = testo[apertura.end():].strip()
        seguito = idx[k + 1:]
        if RE_STRUTTURA_CITATA.match(coda) or (
                not coda and (not seguito
                              or RE_STRUTTURA_CITATA.match(righe[seguito[0]].strip()))):
            return prec + 1
    return None


def _teste_articolo(righe, indice=frozenset()):
    """Le intestazioni come le vede parse() prima della formula di promulgazione.

    Restituisce ([(indice, numero|None, suffisso)], riga della formula o
    len(righe)). Le intestazioni estese ("Art. 3 (Rubrica)") contano solo in
    sequenza, come in parse().
    """
    teste = []
    for i, r in enumerate(righe):
        s = r.strip()
        if not s:
            continue
        if teste and _cerca_promulgazione(righe, i):
            return teste, i    # oltre la formula parse() non e' piu' nel dispositivo
        m = intestazione_articolo(s) if teste else RE_ARTICOLO.match(s)
        if m:
            numero = m.group(1)
            teste.append((i, int(numero) if numero.isdigit() else None,
                          (m.group(2) or "").lower()))
            continue
        if i in indice or (teste and not maiuscola(s)) or RE_PARTIZIONE.match(s):
            continue
        e = RE_ARTICOLO_ESTESO.match(s)
        if e:
            n, suff = int(e.group(1)), (e.group(2) or "").lower()
            prec = next((t[1] for t in reversed(teste) if t[1] is not None), None)
            in_sequenza = (n == 1) if prec is None else (n == prec + 1 or (n == prec and bool(suff)))
            if in_sequenza:
                teste.append((i, n, suff))
    return teste, len(righe)


def righe_citate(righe, indice=frozenset()):
    """Righe che appartengono al testo di un altro atto, riportato qui dentro."""
    citate = set()
    main = 0          # ultimo numero della sequenza propria dell'atto
    atteso = None     # numero con cui l'atto riprende dopo la citazione
    inizio = None     # prima riga del blocco citato, se e' aperto
    prec = -1         # intestazione precedente: oltre non si cerca l'annuncio
    teste, fine = _teste_articolo(righe, indice)
    for i, n, suff in teste:
        if n is None:             # "Articolo unico": la sequenza riparte
            if inizio is not None:
                citate.update(range(inizio, i))
                inizio = None
            main, prec = 0, i
            continue
        if inizio is not None:
            if n == atteso:       # rientro: l'atto riprende il suo discorso
                citate.update(range(inizio, i))
                inizio, main = None, n
            prec = i
            continue
        if n == main + 1 or (suff and n == main) or (main == 0 and n == 1):
            main = n              # prosegue la sequenza
        else:
            da = _inizio_citazione(righe, prec, i)
            if da is not None:
                inizio, atteso = da, main + 1
            elif suff:
                # Un articolo bis appartiene all'atto quando la sua base e' il
                # numero in corso o quello successivo: "Art. 3" e poi
                # "Art.3-bis" (DD-19-2016). Se la base e' altrove, e'
                # l'articolo di un'altra legge riportato qui: L-24-2022
                # sostituisce gli articoli da 53 a 58 del codice di procedura
                # penale e ne riporta dodici bis, a partire dal proprio
                # articolo 1. L'annuncio c'e' ma resta troppo lontano
                # (l'articolo 53 citato occupa trenta righe), quindi la
                # sentinella non lo vede: il bis fuori sequenza apre il blocco
                # al posto suo, e come ogni blocco si chiude al rientro.
                inizio, atteso = prec + 1, main + 1
            else:
                main = n          # salto senza annuncio: numerazione dell'atto
        prec = i
    if inizio is not None:        # nessun rientro: citato fino alla formula
        citate.update(range(inizio, fine))
    return citate


_PROVE_CITATE = [
    ("L-162-2004: l'articolo 1 riscrive il Titolo III di un'altra legge",
     ["Art. 1", "Il Titolo III della Legge 28 aprile 1999 n.53 e' cosi' modificato:",
      '"TITOLO III', "Art. 7", "Per procedere alla costituzione non e' necessario il Nulla Osta.",
      "Art. 8", "Nel presente Titolo l'espressione Regolamento indica quanto segue.",
      "Art. 2", "La presente legge entra in vigore il quindicesimo giorno."],
     set(range(1, 7))),
    ("DD-204-2020: annuncio spezzato su due righe",
     ["Art.3", "1.", "Il Titolo II del Decreto Delegato n.146/2018 e' cosi'",
      "sostituito:", "«TITOLO II - COSTITUZIONE DELL'AUTORITA' ICT",
      "Art.6", "1.", "E' istituita l'Autorita' per la vigilanza.",
      "Art. 7", "1.", "Si assumono le seguenti definizioni.",
      "Art.4", "1.", "Il presente decreto entra in vigore."],
     set(range(1, 11))),
    ("L-119-2015: allegato di un'altra legge, poi rientro sulla sequenza propria",
     ["Art.34", "L'articolo 1 dell'Allegato A alla Legge 10 agosto 2012 n.122 e' cosi' modificato:",
      '"ALLEGATO A', "Art.1", "I requisiti psicofisici minimi sono i seguenti.",
      "Art.35", "L'articolo 2 dell'Allegato A alla Legge 10 agosto 2012 n.122 e' cosi' modificato:",
      '"ALLEGATO A', "Art.2", "L'accertamento e' effettuato dall'Ufficio competente.",
      "Art.36"],
     set(range(1, 5)) | set(range(6, 10))),
    ("anche i CAPO e i TITOLO riportati nella citazione sono testo citato",
     ["Art. 1", "Il Titolo III della Legge 28 aprile 1999 n.53 e' cosi' modificato:",
      '"TITOLO III', "CAPO I", "Delle disposizioni generali",
      "Art. 7", "La costituzione avviene con atto pubblico.",
      "Art. 2", "La presente legge entra in vigore il quindicesimo giorno."],
     set(range(1, 7))),
    # L-24-2022 sostituisce gli articoli da 53 a 58 del codice di procedura
    # penale e ne riporta dodici bis a partire dal proprio articolo 1:
    # l'annuncio c'e' ma resta trenta righe piu' su, fuori dalla finestra.
    ("l'articolo bis con la base lontana dalla sequenza e' citato lo stesso",
     ["Art. 1", "(Misure cautelari personali)", "1.",
      "Il Giudice ordina limitazioni della liberta' personale del prevenuto.",
      "Art. 53-bis", "(Esigenze cautelari)", "1.",
      "Le misure cautelari sono disposte dal Giudice Inquirente.",
      "Art. 2", "1.", "La presente legge entra in vigore il quindicesimo giorno."],
     set(range(1, 8))),
    ("l'articolo bis che segue la propria base resta dell'atto",
     ["Art. 3", "1.", "Il punto vi. della Legge n.166/2013 e' cosi' modificato.",
      "Art.3-bis", "1.", "All'articolo 13 e' aggiunto il seguente punto.",
      "Art. 4", "1.", "Il presente decreto entra in vigore."],
     set()),
    # Le intestazioni estese contano in sequenza: "Art. 2 (Rubrica)" fra due
    # intestazioni semplici non e' un salto da 1 a 3.
    ("un'intestazione con la rubrica sulla riga continua la sequenza",
     ["Art. 1", "1.", "L'articolo 5 della Legge n.3/2000 e' cosi' modificato: «Art. 5 - Il termine e' di dieci giorni.»",
      "Art. 2 (Entrata in vigore)", "1.", "Il presente decreto entra in vigore subito.",
      "Art. 3", "1.", "Testo."],
     set()),
    # Senza rientro il blocco arriva alla formula, non oltre: dopo la formula
    # c'e' l'allegato, che non e' testo citato.
    ("un blocco senza rientro si ferma alla formula di promulgazione",
     ["Art. 1", "Il Titolo III della Legge 28 aprile 1999 n.53 e' cosi' modificato:",
      '"TITOLO III', "Art. 7", "La costituzione avviene con atto pubblico.",
      "Dato dalla Nostra Residenza, addì 23 luglio 2015/1714 d.F.R", "I CAPITANI REGGENTI",
      "Andrea Belluzzi – Roberto Venturini", "Art. 1", "Le Parti si impegnano."],
     set(range(1, 5))),
    # I quattro casi in cui la numerazione salta ma nessuno cita niente.
    ("LC-41-2004: \"Art.l\" letto male, la sequenza parte da 2",
     ["Art.l", "(Istituzione)",
      "Nel rispetto dei principi fondamentali dell'Ordinamento della Repubblica, ed ai sensi",
      "dell'articolo 4 della Legge 26 febbraio 2002 n.36, e' istituito il Collegio di Controllo.",
      "Art.2", "(Funzioni)", "Al Collegio sono affidate le funzioni di controllo."],
     set()),
    ("LC-27-2004: stesso difetto di lettura, stesso salto",
     ["Art.l", "(Istituzione)",
      "Nel rispetto dei principi fondamentali dell'Ordinamento della Repubblica e' istituito",
      "il Collegio di Controllo della Finanza Pubblica, organo di rilievo costituzionale.",
      "Art.2", "(Funzioni)", "Al Collegio sono affidate le funzioni giurisdizionali."],
     set()),
    ("L-5-1921: un secondo atto riportato in nota a pie' di pagina",
     ["Art. 34.", "- La nomina dei rappresentanti verra' fatta quindici giorni dopo.",
      "(1) Statuto Agrario: R. pag. 197.",
      "(2) Decreto Reggenziale 24 Luglio 1921 N.25: Decreto Reggenziale 4 Luglio 1923 N. 18:",
      "Art. 1.", "- L'Articolo 15 della Legge aggiuntiva agraria e' modificato come segue."],
     set()),
    ("L-52-1947: due \"Art. 4.\" di seguito nel testo originale",
     ["Art. 3.", "In relazione all'art. 156 del Codice Penale ogni giorno corrisponde a lire cento.",
      "Art. 4.", "Il limite di applicazione del Decreto Penale e' elevato a lire seimila.",
      "Art. 4.", "E' fissato in lire cinquecento il deposito prescritto per gli appelli.",
      "Art. 6.", "La competenza del Giudice Conciliatore e' elevata a lire duemila."],
     set()),
    ("l'annuncio di un comma non apre una citazione di articoli",
     ["Art. 14", "1.",
      "All'articolo 97, comma 1, della Legge n.166/2013 e' aggiunto il seguente comma 1-bis):",
      "«1-bis) Per i ricavi certificati non e' obbligatoria la certificazione.».",
      "Art. 16", "1.", "Il presente decreto entra in vigore il giorno successivo."],
     set()),
    ("una modifica gia' avvenuta, senza testo riportato, non e' un annuncio",
     ["Art. 1", "La legge 5 dicembre 2011 n.188 e' stata modificata in materia di personale.",
      "Art. 7", "Restano ferme le disposizioni vigenti."],
     set()),
]
for _nome, _righe_test, _atteso in _PROVE_CITATE:
    assert righe_citate(_righe_test) == _atteso, \
        f"righe citate ({_nome}): {sorted(righe_citate(_righe_test))}"


# --- Errata Corrige: non ha articoli propri ---
#
# Un'errata corrige riporta la formulazione corretta di un articolo di un
# ALTRO atto ("La formulazione corretta dell'articolo 6 ... e' la seguente:
# Art. 6"). Quelle intestazioni diventavano articoli suoi: 31 documenti su
# 193 ne producevano, tutti sbagliati. Senza intestazioni il testo passa da
# struttura_dedotta() e resta interamente nel JSON, dichiarato come dedotto.
def e_errata_corrige(id_norma, meta):
    if PREFISSI.get(str((meta or {}).get("tipo") or "").strip().lower()) == "EC":
        return True
    return str(id_norma).startswith("EC-")


_PROVE_ERRATA = [
    ("EC-None-2019~17162000", {}, True),
    ("EC-12-2020", {"tipo": "Errata Corrige"}, True),
    ("L-87-2026", {"tipo": "Legge"}, False),
    ("DD-45-2010", {"tipo": "Decreto Delegato"}, False),
    ("L-1-2020", {"tipo": "errata corrige"}, True),
]
for _nid, _meta, _atteso in _PROVE_ERRATA:
    assert e_errata_corrige(_nid, _meta) == _atteso, f"errata corrige: {_nid}"


def parse(id_norma, meta, righe=None):
    # righe: per le prove all'import, che non hanno un PDF da leggere.
    if righe is None:
        righe = righe_pdf(RAW / id_norma / "testo.pdf")
    indice = _indice_iniziale(righe)
    # Un'errata corrige non ha articoli propri: le sue "Art. N" sono
    # dell'atto corretto. Il testo passa da struttura_dedotta().
    errata = e_errata_corrige(id_norma, meta)
    # Le intestazioni di un testo citato restano testo del comma in corso:
    # e' l'articolo che cita a contenerle.
    citate = set() if errata else righe_citate(righe, indice)
    dopo_firma = False       # passata la formula di promulgazione
    taglio_allegato = None   # riga da cui comincia l'allegato, se c'e'

    partizioni = []       # albero: Titoli con figli Capi
    articoli = []
    ids_usati = set()

    titolo_corrente = None
    capo_corrente = None
    articolo_corrente = None
    comma_corrente = None
    buffer = []
    attesa_rubrica = False   # siamo appena dopo "Art.N"
    rubrica_buffer = []
    preambolo = []
    iniziato = False
    # Il testo che segue un TITOLO o un CAPO prima di un nuovo articolo. Di
    # solito e' il resto della rubrica della partizione, e si lascia; ma se la
    # riga dopo e' un'intestazione che il riconoscitore non vede, e' il corpo
    # di un allegato, e prima andava perso tutto.
    orfane = []

    def recupera_orfane():
        nonlocal orfane
        testo = unisci(orfane)
        orfane = []
        if len(testo) <= 200 or not articoli:
            return
        ultimo = articoli[-1]
        base = f"{ultimo['id']}/c-{len(ultimo['commi']) + 1}"
        cid, n = base, 1
        while cid in {c["id"] for c in ultimo["commi"]}:
            n += 1
            cid = f"{base}-{n}"
        ultimo["commi"].append({"id": cid, "numero": str(len(ultimo["commi"]) + 1),
                                "testo": testo, "numerazioneAnomala": False,
                                "commaImplicito": True})

    def in_sequenza(numero, suffisso):
        """Se un'intestazione estesa continua la numerazione degli articoli."""
        precedenti = [int(a["numero"].split()[0]) for a in articoli
                      if a["numero"].split()[0].isdigit()]
        if not precedenti:
            return numero == 1
        ultimo = precedenti[-1]
        return numero == ultimo + 1 or (numero == ultimo and bool(suffisso))

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

        # --- Formula di promulgazione: da qui non e' piu' dispositivo ---
        # L'allegato che segue le firme apre un comma suo, che commi.py marca
        # come parte d'allegato (`all1`): non e' piu' testo dell'ultimo
        # articolo. Gli articoli dopo la formula li marca articoli.py.
        if articolo_corrente is not None and not dopo_firma and _cerca_promulgazione(righe, i):
            dopo_firma = True
            taglio_allegato = _taglio_allegato(righe, i)
        if i == taglio_allegato and articolo_corrente is not None:
            chiudi_comma()

        m_part = RE_PARTIZIONE.match(riga)
        # Dentro un articolo, prima della formula, un'intestazione comincia con
        # la maiuscola ("articolo 20." a capo e' testo). Dopo la formula vale
        # la lettura stretta: "art. 166" e' la voce di una tabella che
        # allegati_tabellari() rilegge.
        minuscola_ok = dopo_firma or articolo_corrente is None
        if errata:
            m_art = None
        elif dopo_firma:
            m_art = RE_ARTICOLO_DOPO_FIRMA.match(riga)
        else:
            m_art = RE_ARTICOLO.match(riga) if minuscola_ok else intestazione_articolo(riga)
        m_esteso = None
        if (not errata and not m_art and not m_part and i not in indice
                and (minuscola_ok or maiuscola(riga))):
            m_esteso = RE_ARTICOLO_ESTESO.match(riga)
            if m_esteso and not in_sequenza(int(m_esteso.group(1)), m_esteso.group(2)):
                m_esteso = None

        # Dentro un testo citato niente e' struttura di questo atto: ne'
        # "Art. 7" ne' il "TITOLO III"/"CAPO I" riportati nella citazione.
        # Senza togliere anche le partizioni, "CAPO I" chiude l'articolo in
        # corso e il testo che segue finisce fuori da ogni articolo: L-168-2005
        # ci perdeva 35.953 caratteri.
        if i in citate:
            m_part = m_art = m_esteso = None

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
        if m_art or m_esteso:
            chiudi_comma()
            recupera_orfane()
            iniziato = True
            m_intest = m_art or m_esteso
            numero = m_intest.group(1) + (f" {m_intest.group(2).lower()}" if m_intest.group(2) else "")
            genitore = capo_corrente or titolo_corrente
            articolo_corrente = {
                "id": f"{id_norma}/art-{numero.replace(' ', '-')}",
                "numero": numero,
                "rubrica": None,
                "partizioneId": genitore["id"] if genitore else None,
                "ordine": len(articoli),
                "commi": [],
            }
            articoli.append(articolo_corrente)
            attesa_rubrica = True
            rubrica_buffer = []
            if m_esteso:
                rubrica = (m_esteso.group("tra_parentesi") or "").strip()
                in_linea = (m_esteso.group("in_linea") or "").strip()
                if rubrica and not re.fullmatch(r"[\d\s,]+", rubrica):
                    # "(1)" e' il rimando a una nota, non una rubrica
                    articolo_corrente["rubrica"] = rubrica
                    articolo_corrente["_rubricaVera"] = True
                    attesa_rubrica = False
                elif in_linea and len(in_linea) <= 100 and not in_linea.endswith("."):
                    articolo_corrente["rubrica"] = in_linea
                    articolo_corrente["_rubricaVera"] = True
                    attesa_rubrica = False
                elif in_linea:
                    # una frase intera: e' il primo comma, non la rubrica
                    buffer = [in_linea]
                    attesa_rubrica = False
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
        m_c = m_comma or m_comma_inline
        # Dentro un testo citato il comma novellato ("1-bis.") e' dell'altro
        # atto: aprirlo qui darebbe a questo articolo la numerazione altrui.
        # I commi semplici restano come sono sempre stati: il loro testo
        # finisce comunque nell'articolo che cita.
        if m_c is not None and m_c.group(2) and i in citate:
            m_c = None
        if articolo_corrente is not None and m_c is not None:
            chiudi_comma()
            comma_corrente = numero_comma(m_c)
            if m_comma is None:
                buffer = [m_c.group(3)]
            i += 1
            continue

        # --- Testo corrente ---
        if articolo_corrente is not None:
            buffer.append(riga)
        elif not iniziato:
            preambolo.append(riga)
        else:
            orfane.append(riga)
        i += 1

    chiudi_comma()
    recupera_orfane()

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

    # Articoli con lo stesso numero - allegati dopo la firma, intestazioni
    # incollate in coda a un comma, refusi: articoli.py. Poi i commi: rubriche
    # lette come commi, numeri di pagina, testo citato dalle novelle, elenchi,
    # allegati: commi.py. Rinumerano e rinominano, quindi vanno prima delle
    # citazioni, che portano l'id del comma.
    articoli = ristruttura_articoli(id_norma, articoli)
    # Le tabelle dopo la firma lette come articoli ("art. 166 / sanzione da
    # ...") tornano tabelle: un articolo per allegato, un comma per voce.
    articoli = allegati_tabellari(id_norma, righe, articoli)
    for art in articoli:
        art.pop("origine", None)
    for art in articoli:
        ristruttura(art)
        for c in art["commi"]:
            c.pop("origine", None)
            c.pop("assorbiti", None)

    # Citazioni: per comma, con l'indicazione del comma di origine.
    for art in articoli:
        art["citazioni"] = []
        for c in art["commi"]:
            for cit in estrai_citazioni(c["testo"], id_norma):
                cit["commaId"] = c["id"]          # l'id vero, non ricostruito dal numero
                cit["commaOrigine"] = c["numero"]
                art["citazioni"].append(cit)

    testo_preambolo = unisci(preambolo)
    citazioni_preambolo = estrai_citazioni(testo_preambolo, id_norma, preambolo=True)

    return {
        **meta,
        "preambolo": testo_preambolo,
        "citazioniPreambolo": citazioni_preambolo,
        "partizioni": partizioni,
        "articoli": articoli,
    }


# --- Prove a livello di parse(): girano all'import, su righe finte ---

def _ids(d):
    return [a["id"] for a in d["articoli"]]


def _testo(d):
    return " ".join(c["testo"] for a in d["articoli"] for c in a["commi"]) + " " + d["preambolo"]


# Numerazione decimale che ricomincia in una sezione successiva (D-122-1985):
# gli id dei commi restano univoci e nessun testo si perde.
_d = parse("T-2-2000", {}, righe=[
    "1.1 Le presenti norme si applicano agli edifici civili.",
    "1.2 Sono esclusi gli edifici industriali.",
    "2.1 Le autorimesse rispettano le distanze.",
    "1.1 Le presenti norme riguardano gli impianti a gas."])
_id_commi = [c["id"] for a in _d["articoli"] for c in a["commi"]]
assert len(set(_id_commi)) == len(_id_commi), f"id di comma ripetuti: {_id_commi}"
assert "riguardano gli impianti a gas" in _testo(_d)

_PROVE_PARSE = [
    # (nome, id, meta, righe, id attesi degli articoli, testo che non si deve perdere)
    ("errata corrige: nessun articolo proprio, testo conservato",
     "EC-None-2019~17162000", {"tipo": "Errata Corrige"},
     ["ERRATA CORRIGE",
      "La formulazione corretta dell'articolo 6 della Legge n.145/2003 e' la seguente:",
      "Art. 6", "1.", "Il Consiglio delibera a maggioranza assoluta."],
     None, ["Il Consiglio delibera a maggioranza assoluta."]),
    ("intestazione minuscola: resta testo del comma",
     "T-3-2000", {"tipo": "Legge"},
     ["Art. 1", "1.", "Le imposte sono riscosse nei modi previsti dal successivo",
      "articolo 20.", "Art. 2", "1.", "Le spese sono a carico del richiedente."],
     ["T-3-2000/art-1", "T-3-2000/art-2"], ["articolo 20."]),
    ("rubrica presunta: l'apertura di un elenco resta testo",
     "T-3-2000", {},
     ["Art. 1", "Il cittadino ha diritto:", "1.", "all'istruzione;", "2.", "alla salute."],
     ["T-3-2000/art-1"], ["Il cittadino ha diritto:"]),
    ("due atti nello stesso PDF: il secondo rinumera da 1, gli id restano univoci",
     "T-1-2000", {},
     ["Art. 1", "1.", "Prima norma della legge.", "Art. 2", "1.",
      "Seconda norma della legge.", "", "REGOLAMENTO", "",
      "Art. 1", "1.", "Prima norma del regolamento."],
     ["T-1-2000/art-1", "T-1-2000/art-2", "T-1-2000/art-1-rip2"],
     ["Prima norma della legge.", "Prima norma del regolamento."]),
    ("gli articoli citati non diventano articoli propri, e il testo resta",
     "T-2-2000", {},
     ["Art. 1", "Il Titolo III della Legge 28 aprile 1999 n.53 e' cosi' modificato:",
      '"TITOLO III', "Art. 7", "Per procedere alla costituzione serve il Nulla Osta.",
      "Art. 8", "Nel presente Titolo l'espressione Regolamento indica quanto segue.",
      "Art. 2", "La presente legge entra in vigore il quindicesimo giorno."],
     ["T-2-2000/art-1", "T-2-2000/art-2"],
     ["serve il Nulla Osta.", "indica quanto segue."]),
    ("una partizione dentro la citazione non porta via il testo",
     "T-2-2000", {},
     ["Art. 1", "Il Titolo III della Legge 28 aprile 1999 n.53 e' cosi' modificato:",
      '"TITOLO III', "CAPO I", "Delle disposizioni generali",
      "Art. 7", "La costituzione avviene con atto pubblico.",
      "Art. 2", "La presente legge entra in vigore il quindicesimo giorno."],
     ["T-2-2000/art-1", "T-2-2000/art-2"],
     ["Delle disposizioni generali", "La costituzione avviene con atto pubblico."]),
    ("L-24-2022: l'articolo bis citato non torna articolo per articoli.py",
     "T-2-2000", {},
     ["Art. 1", "(Misure cautelari personali)", "1.",
      "Il Giudice ordina limitazioni della liberta' personale del prevenuto.",
      "Art. 53-bis", "(Esigenze cautelari)", "1.",
      "Le misure cautelari sono disposte dal Giudice Inquirente.",
      "Art. 2", "1.", "La presente legge entra in vigore il quindicesimo giorno."],
     ["T-2-2000/art-1", "T-2-2000/art-2"],
     ["Le misure cautelari sono disposte dal Giudice Inquirente."]),
    ("nessun annuncio: il salto di numerazione resta un articolo dell'atto",
     "T-2-2000", {},
     ["Art.l", "(Istituzione)", "E' istituito il Collegio di Controllo della Finanza Pubblica.",
      "Art.2", "(Funzioni)", "Al Collegio sono affidate le funzioni di controllo."],
     ["T-2-2000/art-2"], ["Al Collegio sono affidate"]),
    ("numerazione rotta nell'originale: due articoli 4, id resi univoci",
     "T-2-2000", {},
     ["Art. 3.", "Ogni giorno di prigionia corrisponde a lire cento di multa.",
      "Art. 4.", "Il limite di applicazione del Decreto Penale e' elevato a lire seimila.",
      "Art. 4.", "E' fissato in lire cinquecento il deposito prescritto per gli appelli.",
      "Art. 6.", "La competenza del Giudice Conciliatore e' elevata a lire duemila."],
     ["T-2-2000/art-3", "T-2-2000/art-4", "T-2-2000/art-4-rip2", "T-2-2000/art-6"],
     ["elevato a lire seimila.", "prescritto per gli appelli."]),
    ("l'articolo bis dell'atto apre un articolo proprio",
     "T-4-2000", {},
     ["Art. 5", "1.", "Il canone e' dovuto in via anticipata.",
      "Art. 5-bis", "1.", "Il canone non e' dovuto dagli esenti.",
      "Art. 6", "1.", "Le somme sono versate entro il mese."],
     ["T-4-2000/art-5", "T-4-2000/art-5-bis", "T-4-2000/art-6"],
     ["Il canone non e' dovuto dagli esenti."]),
    ("l'articolo bis citato da una novella resta testo dell'articolo che cita",
     "T-4-2000", {},
     ["Art. 3", "1.",
      "Dopo l'articolo 44 della Legge 5 dicembre 2011 n.188 e' inserito il seguente articolo:",
      "Art. 44-bis", "1.", "La domanda e' presentata per via telematica.",
      "Art. 4", "1.", "Il presente decreto entra in vigore il giorno successivo."],
     ["T-4-2000/art-3", "T-4-2000/art-4"],
     ["La domanda e' presentata per via telematica."]),
    # Dopo la formula intera gli articoli sono di un allegato anche se i numeri
    # non si ripetono (DC-52-2016).
    ("trattato dopo la firma: articoli d'allegato, non del decreto",
     "T-5-2000", {},
     ["Articolo Unico", "E' ratificato il Trattato allegato.",
      "Dato dalla Nostra Residenza, addì 23 luglio 2015/1714 d.F.R", "",
      "I CAPITANI REGGENTI", "Andrea Belluzzi – Roberto Venturini",
      "Art. 1", "Le Parti si impegnano.", "Art. 2", "Le Parti cooperano."],
     ["T-5-2000/art-Unico", "T-5-2000/art-all-1", "T-5-2000/art-all-2"],
     ["Le Parti si impegnano.", "Le Parti cooperano."]),
    # Il trattato riportato prima della firma (X-3-1942).
    ("convenzione nel dispositivo: articoli d'allegato",
     "T-6-2000", {},
     ["Articolo Unico", "1.", "E' ratificata la Convenzione fra la Repubblica di San",
      "Marino e il Regno d'Italia in materia postale.", "",
      "Art. 1.", "- Le Parti contraenti si impegnano al servizio reciproco.",
      "Art. 2.", "- Le spese sono ripartite in parti uguali.",
      "Art. 3.", "- La convenzione ha durata decennale.",
      "Art. 4.", "- Le controversie sono risolte in via diplomatica."],
     ["T-6-2000/art-Unico", "T-6-2000/art-all-1", "T-6-2000/art-all-2",
      "T-6-2000/art-all-3", "T-6-2000/art-all-4"],
     ["Le spese sono ripartite in parti uguali."]),
    ("decreto normale che riparte da 1 senza ratifica: nessun allegato",
     "T-6-2000", {},
     ["Art. 1", "1.", "Il presente decreto disciplina l'accesso agli atti.",
      "Art. 2", "1.", "Le domande si presentano all'ufficio competente.",
      "Art. 3", "1.", "Il regolamento entra in vigore subito.",
      "Art. 4", "1.", "Sono abrogate le disposizioni contrarie.",
      "Art. 1", "1.", "Il presente decreto e' pubblicato."],
     ["T-6-2000/art-1", "T-6-2000/art-2", "T-6-2000/art-3", "T-6-2000/art-4", "T-6-2000/art-1-rip2"],
     ["Il presente decreto e' pubblicato."]),
]
for _nome, _nid, _meta, _righe_test, _ids_attesi, _frasi in _PROVE_PARSE:
    _d = parse(_nid, dict(_meta), righe=_righe_test)
    if _ids_attesi is None:
        assert all(a.get("strutturaDedotta") for a in _d["articoli"]), _nome
    else:
        assert _ids(_d) == _ids_attesi, f"{_nome}: {_ids(_d)}"
    for _f in _frasi:
        assert _f in _testo(_d), f"testo perso ({_nome}): {_f!r}"
    _id_commi = [c["id"] for a in _d["articoli"] for c in a["commi"]]
    assert len(set(_id_commi)) == len(_id_commi), f"id di comma ripetuti ({_nome})"

# I commi con suffisso aprono un comma proprio, tranne dentro un testo citato.
_d = parse("T-3-2000", {}, righe=[
    "Art. 1", "1.", "Il canone e' dovuto in via anticipata.",
    "1 bis.", "Il canone non e' dovuto dagli esenti.",
    "2.", "Le somme sono versate entro il mese."])
assert [c["id"] for c in _d["articoli"][0]["commi"]] == [
    "T-3-2000/art-1/c-1", "T-3-2000/art-1/c-1-bis", "T-3-2000/art-1/c-2"]
_d = parse("T-3-2000", {}, righe=[
    "Art. 1", "Il Titolo III della Legge 28 aprile 1999 n.53 e' cosi' modificato:",
    '"TITOLO III', "Art. 7", "1-bis.", "Il testo citato del comma.",
    "Art. 2", "1.", "Il testo vero dell'atto."])
assert [c["id"] for a in _d["articoli"] for c in a["commi"]] == [
    "T-3-2000/art-1/c-1", "T-3-2000/art-2/c-1"]
assert "Il testo citato del comma." in _testo(_d)

# L'allegato dopo le firme non e' testo dell'ultimo articolo: apre una parte
# d'allegato. Un residuo corto (una nota, un nome spezzato) resta dov'e'.
_FIRMA_PROVA = ["Dato dalla Nostra Residenza, addì 23 luglio 2015/1714 d.F.R", "",
                "I CAPITANI REGGENTI", "Andrea Belluzzi – Roberto Venturini", "",
                "IL SEGRETARIO DI STATO", "PER GLI AFFARI INTERNI", "Gian Carlo Venturini"]
_d = parse("T-7-2000", {}, righe=["Art. 1", "1.", "Il presente decreto entra in vigore."]
           + _FIRMA_PROVA + ["ALLEGATO A", "Tabella delle tariffe postali. " * 10])
_c = _d["articoli"][0]["commi"]
assert [(c["numero"], c.get("parte")) for c in _c] == [("1", None), ("all1", "allegato")], _c
assert "CAPITANI REGGENTI" in _c[0]["testo"] and "Tabella delle tariffe" in _c[1]["testo"]
_d = parse("T-7-2000", {}, righe=["Art. 1", "1.", "Il presente decreto entra in vigore."]
           + _FIRMA_PROVA + ["(1) Già separatamente pubblicato alla data di promulgazione."])
assert len(_d["articoli"][0]["commi"]) == 1


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def main(force=False, atti=None):
    PARSED.mkdir(parents=True, exist_ok=True)
    cartelle = sorted(p for p in RAW.iterdir() if p.is_dir())
    # Con --atti si rileggono solo gli atti della lista, sovrascrivendo il JSON.
    if atti is not None:
        cartelle = [c for c in cartelle if c.name in set(atti)]
        force = True
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
    elenco = None
    if "--atti" in sys.argv:
        elenco = json.loads(Path(sys.argv[sys.argv.index("--atti") + 1]).read_text(encoding="utf-8"))
    main(force="--force" in sys.argv, atti=elenco)
