"""
Definizioni condivise dalla pipeline.

L'identificativo di una norma dipende dal suo tipo, e il tipo arriva da una
stringa libera scritta nella scheda del portale. Tenere questa mappa in un solo
posto evita che i vari script derivino id diversi per la stessa norma.
"""

import os
import re


def certifica():
    """Fa leggere a Python le CA di certifi invece di quelle di sistema.

    Su questa macchina lo store radice che Python eredita da Windows contiene
    36 CA soltanto, e fra quelle manca chi firma il certificato di Aura: ogni
    connessione muore con "self signed certificate in certificate chain" senza
    che nessuno stia intercettando nulla - riprodotto su reti diverse. Con le
    CA di certifi (le stesse che usa gia' `requests` qui dentro) se ne vedono
    147 e la verifica passa.

    Si agisce su SSL_CERT_FILE e non sui parametri del driver perche' la
    pipeline apre connessioni in tre modi diversi - Neo4jGraph, il driver
    grezzo di neo4j, e Neo4jVector, che il suo driver se lo costruisce da se'
    e non accetta configurazione - e OpenSSL legge questa variabile in tutti
    e tre. Cosi' lo schema neo4j+s:// resta quello dichiarato nel .env, con
    la cifratura che impone.

    Va chiamata prima di aprire la connessione; chiamarla piu' volte non fa
    danno. Se qualcuno ha gia' impostato SSL_CERT_FILE, si rispetta la sua
    scelta.
    """
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except ImportError:      # senza certifi si prova comunque: altrove funziona
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()

# L'archivio non usa solo le etichette del menu a tendina: la L.140/2017 e'
# schedata come "Legge ordinaria", che nel dropdown non compare affatto.
PREFISSI = {
    "legge": "L",
    "legge ordinaria": "L",
    "legge costituzionale": "LC",
    "legge qualificata": "LQ",
    "legge di revisione costituzionale": "LRC",
    "legge revisione costituzionale": "LRC",
    "decreto": "D",
    "decreto delegato": "DD",
    "decreto legge": "DL",
    "decreto-legge": "DL",
    "decreto - legge": "DL",
    "decreto -legge": "DL",
    "decreto- legge": "DL",
    "decreto reggenziale": "DR",
    "decreto consiliare": "DC",
    "decreto consigliare": "DC",
    "decreto conisliare": "DC",
    "decreto delagato": "DD",
    "decreto delega5to": "DD",
    "decreto - legga": "DL",
    "legge orginaria": "L",
    "regolamento": "R",
    "notifica": "N",
    "statuto": "S",
    "ordinanza": "O",
    "verbale": "V",
    "errata corrige": "EC",
}

LABELS = {
    "legge": "Legge",
    "legge ordinaria": "Legge",
    "legge orginaria": "Legge",
    "legge costituzionale": "LeggeCostituzionale",
    "legge qualificata": "LeggeQualificata",
    "legge di revisione costituzionale": "LeggeRevisioneCostituzionale",
    "legge revisione costituzionale": "LeggeRevisioneCostituzionale",
    "decreto": "Decreto",
    "decreto delegato": "DecretoDelegato",
    "decreto delagato": "DecretoDelegato",
    "decreto delega5to": "DecretoDelegato",
    "decreto legge": "DecretoLegge",
    "decreto-legge": "DecretoLegge",
    "decreto - legge": "DecretoLegge",
    "decreto -legge": "DecretoLegge",
    "decreto- legge": "DecretoLegge",
    "decreto - legga": "DecretoLegge",
    "decreto reggenziale": "DecretoReggenziale",
    "decreto consiliare": "DecretoConsiliare",
    "decreto consigliare": "DecretoConsiliare",
    "decreto conisliare": "DecretoConsiliare",
    "regolamento": "Regolamento",
    "notifica": "Notifica",
    "statuto": "Statuto",
    "ordinanza": "Ordinanza",
    "verbale": "Verbale",
    "errata corrige": "ErrataCorrige",
}

tipi_ignoti = set()

# Tipo+numero+anno non e' una chiave: l'archivio numera uguale atti distinti
# (e ogni Errata Corrige eredita gli estremi dell'atto che corregge). Quando
# due schede collidono, la prima tiene l'id piano e la seconda lo qualifica
# con il proprio schedaId. Cosi' nessun id gia' assegnato cambia, e le
# citazioni - che si risolvono per tipo/numero/anno - continuano a puntare
# all'atto canonico.
SEPARATORE_COLLISIONE = "~"


def id_canonico(id_norma):
    """
    'D-66-1983~17012616' -> 'D-66-1983'.

    Serve a chi deve risalire dall'id qualificato a quello che le citazioni
    nominano.
    """
    return (id_norma or "").split(SEPARATORE_COLLISIONE, 1)[0]


def id_qualificato(id_norma, scheda_id):
    """Aggiunge lo schedaId a un id conteso."""
    return f"{id_canonico(id_norma)}{SEPARATORE_COLLISIONE}{scheda_id}"


ANNO_MINIMO = 1600
ANNO_MASSIMO = 2100


def normalizza_estremi(numero, anno, data=None):
    """
    Rimette a posto numero e anno quando la scheda del portale li confonde.

    Due guasti osservati sull'archivio reale:

      - **invertiti**: la scheda di DD n.9 del 2007 riporta numero=2007 e
        anno=9. Senza correzione nasce l'id 'DD-2007-9', che nessuna citazione
        potra' mai agganciare, e l'ordinamento per anno lo mette nell'anno 9.
      - **anno assente**: anno=0 oppure vuoto, mentre la data completa c'e'.

    Restituisce (numero, anno) come interi dove possibile, altrimenti li
    lascia come sono: meglio un dato grezzo che un dato inventato.
    """
    def intero(v):
        try:
            return int(str(v).strip())
        except (TypeError, ValueError):
            return None

    def plausibile(y):
        return y is not None and ANNO_MINIMO <= y <= ANNO_MASSIMO

    n, a = intero(numero), intero(anno)
    anno_data = intero(str(data)[:4]) if data else None

    # Invertiti: l'anno e' finito nel numero. Il numero "sembra un anno" o
    # perche' lo e', o perche' e' vicinissimo alla data della scheda - e'
    # cosi' che si riconosce il refuso 2208 al posto di 2008.
    if not plausibile(a) and n is not None:
        sembra_anno = plausibile(n) or (
            anno_data is not None and 1000 <= n <= 2999 and abs(n - anno_data) <= 300)
        if sembra_anno:
            n, a = a, n

    # Anno ancora inservibile: lo si prende dalla data, il dato piu' solido
    # che la scheda offre.
    if not plausibile(a) and anno_data is not None:
        a = anno_data

    return (n if n is not None else numero, a if a is not None else anno)


def norma_id(tipo, numero, anno):
    """
    Costruisce l'id di una norma, es. "L-87-2026", "DD-120-2026", "DL-88-2026".

    Un tipo sconosciuto produrrebbe id 'X-...' silenziosi che non combaciano
    con quelli dedotti dalle citazioni, lasciando stub orfani accanto alle
    norme caricate. Meglio dirlo subito.
    """
    chiave = (tipo or "").strip().lower()
    chiave = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u00ad\uff0d\x96\ufffd–—−]", "-", chiave)
    chiave = re.sub(r"\s+", " ", chiave)
    chiave = re.sub(r"\s*-\s*", "-", chiave)
    prefisso = PREFISSI.get(chiave) or PREFISSI.get(chiave.replace("-", " "))
    if prefisso is None and "decreto" in chiave and ("legge" in chiave or "legga" in chiave):
        prefisso = "DL"
    elif prefisso is None and "decreto" in chiave and ("consiliare" in chiave or "consigliare" in chiave or "conisliare" in chiave):
        prefisso = "DC"
    elif prefisso is None and "decreto" in chiave and ("delegato" in chiave or "delagato" in chiave or "delega" in chiave):
        prefisso = "DD"
    elif prefisso is None and "decreto" in chiave and "reggenziale" in chiave:
        prefisso = "DR"
    elif prefisso is None and ("legge" in chiave or "ordinaria" in chiave):
        prefisso = "L"
    elif prefisso is None and ("decreto" in chiave or "decreti" in chiave):
        prefisso = "D"
    elif prefisso is None:
        if tipo not in tipi_ignoti:
            tipi_ignoti.add(tipo)
            print(f"    ATTENZIONE: tipo di norma non riconosciuto: {tipo!r} "
                  f"-> uso il prefisso 'X'. Aggiungerlo a comune.PREFISSI.")
        prefisso = "X"
    return f"{prefisso}-{numero}-{anno}"


def norma_label(tipo):
    """
    Restituisce l'etichetta Cypher specifica per il tipo di norma
    (es. 'Legge', 'DecretoDelegato', 'DecretoLegge', ecc.).
    """
    chiave = (tipo or "").strip().lower()
    chiave = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u00ad\uff0d\x96\ufffd–—−]", "-", chiave)
    chiave = re.sub(r"\s+", " ", chiave)
    chiave = re.sub(r"\s*-\s*", "-", chiave)
    lbl = LABELS.get(chiave) or LABELS.get(chiave.replace("-", " "))
    if not lbl and "decreto" in chiave and ("legge" in chiave or "legga" in chiave):
        lbl = "DecretoLegge"
    elif not lbl and "decreto" in chiave and ("consiliare" in chiave or "consigliare" in chiave or "conisliare" in chiave):
        lbl = "DecretoConsiliare"
    elif not lbl and "decreto" in chiave and ("delegato" in chiave or "delagato" in chiave or "delega" in chiave):
        lbl = "DecretoDelegato"
    elif not lbl and "decreto" in chiave and "reggenziale" in chiave:
        lbl = "DecretoReggenziale"
    elif not lbl and ("decreto" in chiave or "decreti" in chiave):
        lbl = "Decreto"
    elif not lbl and ("legge" in chiave or "ordinaria" in chiave):
        lbl = "Legge"
    if not lbl:
        pulito = re.sub(r"[^a-zA-Z0-9]", "", (tipo or "").title())
        lbl = pulito if pulito else None
    return lbl


# ------------------------------------------------------------ tipo sbagliato

MESI_CITATI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
               "agosto", "settembre", "ottobre", "novembre", "dicembre"]
RE_DATA_CITATA = re.compile(
    r"(\d{1,2})\s*[°º]?\s+(" + "|".join(MESI_CITATI) + r")\s+(\d{4})", re.I)


def data_citata(testo):
    """La data scritta in una citazione ("Decreto 1° luglio 2004 n.94"), o None."""
    m = RE_DATA_CITATA.search(testo or "")
    if not m:
        return None
    try:
        import datetime
        return datetime.date(int(m.group(3)), MESI_CITATI.index(m.group(2).lower()) + 1,
                             int(m.group(1))).isoformat()
    except ValueError:
        return None


def risolutore_per_data(atti):
    """Una funzione (id citato, testo della citazione) -> id da collegare.

    Il testo chiama un atto con un tipo, l'archivio lo cataloga con un altro:
    "Decreto Reggenziale 1° settembre 2003 n.113" e' in archivio come D-113-2003,
    "Decreto 1° luglio 2004 n.94" come DR-94-2004. L'id costruito dal tipo
    scritto non esiste, e la citazione finiva su un atto fantasma che l'agente
    non poteva aprire: 794 citazioni il 17/09, con la stessa data dell'atto
    caricato.

    Si reindirizza solo se l'id citato non e' in archivio, la citazione porta
    una data, e fra gli atti caricati con lo stesso numero e anno UNO SOLO ha
    quella data. Tipi diversi possono avere lo stesso numero nello stesso anno
    (DD-12-2017 e R-12-2017): la data e' cio' che li distingue, e senza data
    non si decide.

    `atti` e' un iterabile di (id, data ISO) degli atti con testo.
    """
    presenti, per_estremi = set(), {}
    for id_atto, data in atti:
        presenti.add(id_atto)
        m = re.match(r"^[A-Z]+-(\d+)-(\d{4})$", id_atto or "")
        if m and data:
            per_estremi.setdefault(m.groups(), []).append((id_atto, str(data)[:10]))

    def risolvi(id_citato, testo):
        if id_citato in presenti:
            return id_citato
        m = re.match(r"^[A-Z]+-(\d+)-(\d{4})$", id_citato or "")
        data = data_citata(testo)
        if not m or not data:
            return id_citato
        uguali = [i for i, d in per_estremi.get(m.groups(), []) if d == data]
        return uguali[0] if len(uguali) == 1 else id_citato

    return risolvi


_r = risolutore_per_data([("D-113-2003", "2003-09-01"), ("DD-12-2017", "2017-01-18"),
                          ("R-12-2017", "2017-10-11"), ("L-5-2020", "2020-01-10")])
assert _r("DR-113-2003", "Decreto Reggenziale 1° settembre 2003 n.113") == "D-113-2003"
assert _r("DR-113-2003", "Decreto Reggenziale n.113/2003") == "DR-113-2003"           # senza data
assert _r("L-12-2017", "Legge 11 ottobre 2017 n.12") == "R-12-2017"
assert _r("L-12-2017", "Legge 3 marzo 2017 n.12") == "L-12-2017"                      # nessuna data uguale
assert _r("L-5-2020", "Legge 2 febbraio 2020 n.5") == "L-5-2020"                      # presente: non si tocca
del _r


# ------------------------------------------------------------ caratteri corrotti

_MOJIBAKE = re.compile(r"[ÂÃ][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192"
                       r"\u02c6\u02dc\u2013\u2014\u2018\u2019\u201a\u201c\u201d\u201e\u2020"
                       r"\u2021\u2022\u2026\u2030\u2039\u203a\u20ac\u2122]")


def ripara_mojibake(testo):
    """Il testo UTF-8 letto come Windows-1252 e riscritto: "NÂ° 27" -> "N° 27".

    Si ripara coppia per coppia, non la stringa intera: un titolo puo' avere
    lettere accentate giuste accanto a quelle corrotte, e decodificarlo tutto
    insieme fallirebbe. Una coppia che non torna UTF-8 valido resta com'e'.
    """
    if not testo or ("Â" not in testo and "Ã" not in testo):
        return testo

    def una(m):
        try:
            return m.group(0).encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            try:
                return m.group(0).encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                return m.group(0)

    riparato = _MOJIBAKE.sub(una, testo)
    # "Ã " e' una "à" il cui secondo byte (lo spazio non separabile) e'
    # diventato uno spazio qualunque: lo spazio va assorbito. "Â" isolata
    # davanti a uno spazio e' il resto di uno spazio non separabile.
    riparato = re.sub(r"Ã\s", "à", riparato)
    return re.sub(r"Â(?=\s)", "", riparato)


assert ripara_mojibake("MODIFICHE ALLA LEGGE 20 FEBBRAIO 1991 NÂ° 27") == "MODIFICHE ALLA LEGGE 20 FEBBRAIO 1991 N° 27"
assert ripara_mojibake("attivitÃ  e perchÃ© cosÃ¬") == "attività e perché così"
assert ripara_mojibake("città già giusta") == "città già giusta"
assert ripara_mojibake("la liberta\u0300 Ã\u00a0 garantita") == "la liberta\u0300 à garantita"


def data_pulita(data, anno):
    """La data di un atto, senza i segnaposto del portale.

    31 schede avevano date impossibili: "1200-01-01" dove la data non era nota,
    "0006-01-11" per l'11 gennaio 2006. La prima non dice nulla e si toglie; la
    seconda ha l'anno troncato, e l'anno dell'atto lo completa. Le date
    anteriori al 1500 non sono di questo archivio (il documento piu' antico e'
    del 1599).
    """
    if not data:
        return None
    s = str(data)[:10]
    try:
        anno_data = int(s[:4])
    except ValueError:
        return None
    if anno_data >= 1500:
        return s
    try:
        anno = int(anno)
    except (TypeError, ValueError):
        return None
    if 1 <= anno_data <= 99 and anno % 100 == anno_data:
        return f"{anno:04d}{s[4:]}"
    return None


assert data_pulita("1200-01-01", 1949) is None
assert data_pulita("0006-01-11", 2006) == "2006-01-11"
assert data_pulita("1599-06-27", 1599) == "1599-06-27"
assert data_pulita("2015-01-28", 2014) == "2015-01-28"
assert data_pulita(None, 2000) is None
