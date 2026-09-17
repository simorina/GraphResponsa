"""
12 - Integra nel grafo una raccolta coordinata del Consiglio Grande e Generale.

10_codice_penale.py fa questo lavoro per un atto solo. Le raccolte ne tengono
diversi nello stesso PDF - quella sull'Edilizia Sovvenzionata coordina la
L-110/1994, la L-44/2015, la L-64/2025 e il R-5/2026, e in coda, sotto "ALTRE
NORME", riporta articoli di altri tredici atti - e hanno tre cose che il
Codice Penale non aveva:

  - i commi numerati ("1.", "1 bis.") accanto a quelli distinti dal solo
    rientro;
  - interi Titoli abrogati: "TITOLO II [ABROGATO]", con gli articoli che non
    compaiono piu' nel corpo ma restano, nel grafo, col testo del 1994;
  - atti che citano altri atti. I commi riscritti perdono le citazioni
    ricavate dal testo di prima, e vanno ricalcolate su quello nuovo con le
    stesse espressioni del parser.

Si riscrive solo cio' che il coordinato cambia davvero: gli articoli con una
nota (modificati, inseriti, abrogati), quelli che il grafo non ha, e tutti gli
articoli degli atti che il caricamento aveva ridotto a un comma implicito per
articolo. Un articolo mai toccato resta com'e', con i suoi commi e i suoi
vettori.

Le abrogazioni NON si scrivono qui, per la stessa ragione di 10: le deposita
in data/derivato/, e 08_abrogazioni.py le legge.

Uso:
    .venv/Scripts/python.exe src/12_raccolta_coordinata.py --pdf <file> --nome <slug>
    .venv/Scripts/python.exe src/12_raccolta_coordinata.py --pdf <file> --nome <slug> --scrivi

E' idempotente: rieseguirlo sullo stesso PDF riscrive gli stessi valori.
"""

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

import fitz

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from comune import SEPARATORE_COLLISIONE, norma_id  # noqa: E402


def _modulo(nome, file):
    spec = importlib.util.spec_from_file_location(nome, RADICE / "src" / file)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# Le espressioni si importano da chi le ha collaudate invece di ricopiarle: la
# lettura delle note da 10, le citazioni dal parser e da 09. Se divergessero,
# lo stesso testo produrrebbe archi diversi a seconda di chi l'ha caricato.
cp = _modulo("codice_penale10", "10_codice_penale.py")
parser = _modulo("parse02", "02_parse.py")
riallinea = _modulo("riallinea09", "09_riallinea_citazioni.py")

DERIVATO = RADICE / "data" / "derivato"
FONTE = cp.FONTE

# Nella raccolta sul Lavoro il trattino manca ("DECRETO LEGGE 5 ottobre 2011
# n.156") e l'intestazione puo' chiudere col punto ("LEGGE 17 febbraio 1961 n.
# 7."): senza, i due atti finivano dentro quello che li precede nel PDF.
TIPI_ATTO = (r"legge\s+costituzionale|legge\s+qualificata|legge|regolamento"
             r"|decreto\s*[-–—]?\s*legge|decreto\s+delegato|decreto\s+consiliare"
             r"|decreto\s+reggenziale|decreto")
RE_ATTO = re.compile(
    r"(?P<tipo>" + TIPI_ATTO + r")\s+\d{1,2}\s+(?:" + cp.MESI + r")\s+"
    r"(?P<anno>\d{4})\s*,?\s*n\.?\s*(?P<numero>\d+)\s*\.?", re.I)
# "Art 22-bis" compare senza punto: con l'espressione di 10 l'articolo spariva
# dentro il precedente. "Art. 8/bis" e "Articolo Unico" vengono dal Lavoro; nel
# grafo l'articolo unico e' numerato "Unico".
RE_ART = re.compile(
    r"^\s*Art(?:\.|icolo)?\s*(\d+|unico)\s*(?:[-\s/]\s*(" + cp.ORDINALI + r"))?\s*\.?\s*$", re.I)
RE_COMMA_NUMERATO = re.compile(
    r"^(\d{1,3})\s*(?:[-\s]\s*(" + cp.ORDINALI + r"))?\s*\.\s+(?=\S)", re.I)
RE_ABROGATO_INTERO = re.compile(r"\[ABROGAT[OA]\][.;]?")
RE_ABROGATO_PARTE = re.compile(r"\[ABROGAT[OA]\]")
RE_AGGIORNAMENTO = re.compile(r"\((?:Aggiornamento|aggiornat[oa])\s+al\s+([^)]+)\)", re.I)
# Un Allegato in coda all'atto e' una tabella o un modulo: l'organico
# dell'Ufficio del Lavoro dietro la L-131/2005 sono undici pagine di "POSTI N. 1
# / FUNZIONI / LIVELLO RETRIBUTIVO", che finivano tutte nell'art. 24.
RE_ALLEGATO = re.compile(r"^\s*Allegat[oi]\b", re.I)
# "Articoli abrogati dalla Legge 29 aprile 2014 n.71, Articolo 24: vedere nota
# n. 35." - la nota dei gruppi di articoli caduti insieme non ha l'intestazione
# "Modifiche legislative", e senza di essa l'atto abrogante non si leggeva.
RE_ABROGATI_DA = re.compile(r"^(\d{1,3}\s+)Articol[oi]\s+abrogat[oi]\s+dal(?:la|lo|l['’])?\s*", re.I)
# "Testo originario Legge 31 marzo 2014 n.43, Articolo 3:" - l'articolo nato da
# una novella, con l'atto per esteso invece che fra parentesi come in 10.
RE_ORIGINE_ESTESA = re.compile(
    r"Testo originario\s+(" + cp.TIPO + r")\s+\d{1,2}\s+(?:" + cp.MESI + r")\s+(\d{4})"
    r"\s*,?\s*n\.?\s*(\d+)\s*,\s*(?:Articolo|Art\.?)\s*(\d+)", re.I)
RE_TITOLO_CITATO = re.compile(r"\bTitol[oi]\s+([IVXLC]+)\b")
RE_NOTA_SOSTANZIALE = re.compile(r"Testo originario|Modifiche legislative", re.I)
# Il rinvio puo' seguire il frammento ("comma 1, punto primo dell'elenco:
# vedere nota n. 1.") e dire quale nota: e' il dato piu' affidabile che c'e'.
RE_RINVIO_NOTA = re.compile(
    r"(?:^|:)\W*(?:vedi|vedere)\s+(?:la\s+)?nota\b\s*(?:n\.?\s*(?P<numero>\d+)|(?P<precedente>precedente))?",
    re.I)
# "articoli 8, 9, 10, 11 del Titolo III, 26 e 27 del Titolo IV": la
# partizione in mezzo spezzava l'elenco, e gli artt. 26 e 27 della L-7/1961
# restavano abrogati senza fonte.
RE_PARTIZIONE_IN_ELENCO = re.compile(
    r"\s+del(?:la|l['’])?\s+(?:Titolo|Capo|Capitolo|Sezione)\s+[IVXLC]+\b(?=\s*(?:,|e\b|ed\b))", re.I)
# L'articolo che introduce una novella in un altro atto: il coordinato ne
# riporta il testo aggiornato dalle modifiche successive, che pero' riguardano
# l'atto bersaglio. Scritto qui, l'art. 11 della L-115/2017 avrebbe detto nel
# 2017 cio' che un Decreto-Legge del 2018 ha scritto nella L-71/2013.
RE_VEICOLO_NOVELLA = re.compile(
    r"seguent[ei]\s+articol|cos[iì]['’]?\s+sostituit[oa]\s*:|sostituit[oa]\s+dal\s+seguente", re.I)

# Qui i capoversi non numerati rientrano a x~82 e le righe che proseguono una
# voce d'elenco a x~75: la soglia di 10 (75) le scambiava per commi nuovi.
X_RIENTRO = 80
X_INTESTAZIONE = 70


# ---------------------------------------------------------------- estrazione

def _dimensione(span):
    """Il corpo di una riga senza i numeri di nota.

    Il richiamo in apice (6.5pt) o il numero che apre la nota (12pt alla nota
    95 del Lavoro) non dicono se la riga e' testo o nota: contato, la nota 95
    finiva nel corpo e ci apriva un atto.
    """
    piene = [s for s in span if s["text"].strip()]
    testo = [s for s in piene if not s["text"].strip().isdigit()] or piene
    return max((s["size"] for s in testo), default=0)


def _riga_nota(span):
    """"50Legge 21 dicembre..." - il numero che apre la nota va staccato dal
    testo, o spezza_note non ci vede l'inizio della nota 50."""
    piene = [s for s in span if s["text"].strip()]
    if len(piene) > 1 and piene[0]["text"].strip().isdigit():
        i = span.index(piene[0])
        return (piene[0]["text"].strip() + " " + "".join(s["text"] for s in span[i + 1:]).strip()).rstrip()
    return "".join(s["text"] for s in span).rstrip()


def righe_pdf(pdf):
    """Come in 10, con in piu' il grassetto.

    Senza il grassetto l'intestazione di un atto non si distingue da una riga
    di testo che nomina un atto e basta: l'art. 84 della L-110/1994 elenca le
    leggi abrogate una per riga, "Legge 28 gennaio 1982 n.13", e ognuna
    sarebbe diventata l'inizio di un atto nuovo.
    """
    corpo, note = [], []
    pagine = [[riga for blocco in pagina.get_text("dict")["blocks"]
               for riga in blocco.get("lines", [])] for pagina in fitz.open(pdf)]
    # Le note stanno un punto o piu' sotto il testo, ma non allo stesso corpo in
    # ogni raccolta: 9pt sotto gli 11 dell'Edilizia, 10pt sotto gli 11 del
    # Lavoro. La soglia fissa a 10 prendeva le note del Lavoro per testo.
    dimensioni = Counter(round(_dimensione(r["spans"])) for righe in pagine for r in righe
                         if _dimensione(r["spans"]))
    soglia = dimensioni.most_common(1)[0][0] - 0.5 if dimensioni else 10
    for righe in pagine:
        visive = {}
        for riga in righe:
            span = riga["spans"]
            dim = _dimensione(span)
            if dim < soglia:
                note.append(_riga_nota(span))
                continue
            visive.setdefault(round(riga["bbox"][1]), []).append((riga, dim))
        for quota in sorted(visive):
            pezzi = sorted(visive[quota], key=lambda r: r[0]["bbox"][0])
            testo, richiami, grassetto = "", [], False
            for riga, dim in pezzi:
                for s in riga["spans"]:
                    if s["size"] < dim - 1 and s["text"].strip().isdigit():
                        richiami.append(int(s["text"].strip()))
                    else:
                        testo += s["text"]
                        grassetto = grassetto or (bool(s["flags"] & 16) and bool(s["text"].strip()))
                testo += " "
            corpo.append((re.sub(r"\s+", " ", testo).strip(),
                          round(pezzi[0][0]["bbox"][0]), richiami, grassetto))
    return corpo, note


def segmenta(corpo):
    """Il corpo diviso per atto.

    Un'intestazione apre un atto solo se prima della successiva c'e' almeno un
    articolo: la copertina elenca gli stessi atti con la stessa grafia, e
    senza questo controllo ognuno diventava un atto vuoto.
    """
    teste = [i for i, (t, x, _, b) in enumerate(corpo)
             if b and x < X_INTESTAZIONE and RE_ATTO.fullmatch(t)]
    # "ALTRE NORME" nell'Edilizia, "ALTRE NORME IN MATERIA DI LAVORO:" nel
    # Lavoro. Maiuscolo e a margine: "altre norme in vigore" a capo resta testo.
    altre = next((i for i, (t, x, _, _) in enumerate(corpo)
                  if x < X_INTESTAZIONE and t == t.upper()
                  and re.match(r"ALTRE NORME\b", t)), len(corpo))
    segmenti = []
    for k, i in enumerate(teste):
        fine = teste[k + 1] if k + 1 < len(teste) else len(corpo)
        if i < altre < fine:
            fine = altre
        righe = corpo[i + 1:fine]
        if not any(RE_ART.match(t) for t, _, _, _ in righe):
            continue
        m = RE_ATTO.fullmatch(corpo[i][0])
        segmenti.append({"intestazione": corpo[i][0],
                         "tipo": re.sub(r"\s*[-–—]\s*", "-", re.sub(r"\s+", " ", m.group("tipo"))).title(),
                         "numero": int(m.group("numero")), "anno": int(m.group("anno")),
                         "appendice": i > altre, "righe": righe})
    return segmenti


def _progressivo(precedente, numero, ordinale):
    """Se "N." apre davvero il comma successivo e non e' una riga che comincia
    con un numero ("2. e' abrogato" citato dentro un comma resta dov'e')."""
    if precedente is None:
        return True
    base = int(re.match(r"\d+", precedente).group(0))
    return numero > base or (numero == base and ordinale is not None)


def estrai_articoli(righe):
    articoli, partizioni = [], []
    corrente, rubrica_aperta, partizione, allegato = None, False, None, False
    contesto = {"titolo": None, "titoloRubrica": None, "capo": None, "capoRubrica": None}
    for testo, x, richiami, grassetto in righe:
        # Il numero di pagina va scartato per primo: fra un "TITOLO II
        # [ABROGATO]" e il Titolo successivo corrono otto pagine di sole note, e
        # i loro numeri finivano nel nome del Titolo.
        if not testo or re.fullmatch(r"\d{1,3}", testo):
            continue
        # Solo le intestazioni in grassetto aprono un articolo: nell'art. 41
        # della L-110/1994 una riga va a capo su "articolo 31." e l'art. 31 -
        # abrogato col suo Titolo - risorgeva col testo dell'art. 41.
        m = RE_ART.match(testo) if grassetto else None
        if m:
            base = "Unico" if m.group(1).lower() == "unico" else m.group(1)
            numero = base + ("-" + m.group(2).lower() if m.group(2) else "")
            corrente = {"numero": numero, "rubrica": None, "commi": [], "numeri": [],
                        "note": list(richiami), "numerato": None, **contesto}
            articoli.append(corrente)
            rubrica_aperta, partizione, allegato = False, None, False
            continue
        # Maiuscolo o centrato: "Allegato A della Legge..." andato a capo a
        # margine resta testo del comma.
        if RE_ALLEGATO.match(testo) and (testo.split()[0].isupper() or x >= cp.X_CENTRATO):
            corrente, partizione, allegato = None, None, True
            continue
        if allegato:
            continue

        mp = cp.RE_PARTIZIONE.match(testo)
        if mp:
            tipo = mp.group(1).capitalize()
            nome = f"{tipo} {testo.split()[-1].upper()}"
            partizione = {"nome": nome, "tipo": tipo, "rubrica": None,
                          "abrogata": False, "note": list(richiami)}
            partizioni.append(partizione)
            if tipo == "Titolo":
                contesto = {"titolo": nome, "titoloRubrica": None,
                            "capo": None, "capoRubrica": None}
            else:
                contesto = {**contesto, "capo": nome, "capoRubrica": None}
            continue
        # Fra l'intestazione di una partizione e il primo articolo stanno il
        # suo nome e, se e' caduta, [ABROGATO]: roba sua, non dell'articolo
        # che la precede. La nota di "TITOLO II [ABROGATO]" finiva altrimenti
        # all'art. 30.
        if partizione is not None:
            if RE_ABROGATO_INTERO.fullmatch(testo.replace(" ", "")):
                partizione["abrogata"] = True
            else:
                partizione["rubrica"] = ((partizione["rubrica"] or "") + " " + testo).strip()
                chiave = "titoloRubrica" if partizione["tipo"] == "Titolo" else "capoRubrica"
                contesto[chiave] = partizione["rubrica"]
            partizione["note"] += richiami
            continue

        if corrente is None:
            continue
        corrente["note"] += richiami
        # Un articolo abrogato e' "[ABROGATO]" e basta. Dopo l'art. 5 della
        # L-71/2014 la nota col testo originario prosegue per due pagine al
        # corpo del testo, e senza questo arresto diventava l'articolo.
        if corrente.get("chiuso"):
            continue
        if not corrente["commi"] and (rubrica_aperta or testo.startswith("(")):
            corrente["rubrica"] = ((corrente["rubrica"] or "") + " " + testo).strip()
            rubrica_aperta = not testo.endswith(")")
            if not rubrica_aperta:
                corrente["rubrica"] = corrente["rubrica"].strip("()").strip()
            continue
        if x >= cp.X_CENTRATO and "[" not in testo:
            continue
        if testo.upper() == testo and re.search(r"[A-ZÀ-Ù]{3}", testo) and "[" not in testo:
            continue

        if not corrente["commi"] and RE_ABROGATO_INTERO.fullmatch(testo.replace(" ", "")):
            corrente["commi"].append([testo])
            corrente["numeri"].append("1")
            corrente["chiuso"] = True
            continue

        mn = RE_COMMA_NUMERATO.match(testo)
        if corrente["numerato"] is None:
            corrente["numerato"] = bool(mn)
        if corrente["numerato"]:
            precedente = corrente["numeri"][-1] if corrente["numeri"] else None
            if mn and _progressivo(precedente, int(mn.group(1)), mn.group(2)):
                corrente["commi"].append([testo[mn.end():]])
                corrente["numeri"].append(mn.group(1) + ("-" + mn.group(2).lower()
                                                         if mn.group(2) else ""))
            elif corrente["commi"]:
                corrente["commi"][-1].append(testo)
            else:
                corrente["commi"].append([testo])
                corrente["numeri"].append("1")
        elif not corrente["commi"] or (x >= X_RIENTRO
                                       and cp.apre_comma(testo, corrente["commi"][-1])):
            corrente["commi"].append([testo])
            corrente["numeri"].append(str(len(corrente["commi"])))
        else:
            corrente["commi"][-1].append(testo)
    return articoli, partizioni


def rifinisci(articoli):
    for a in articoli:
        coppie = [(n, re.sub(r"\s+", " ", " ".join(p)).strip())
                  for n, p in zip(a["numeri"], a["commi"])]
        coppie = [(n, t) for n, t in coppie if t]
        a["numeri"] = [n for n, _ in coppie]
        a["commi"] = [t for _, t in coppie]
        a["testo"] = " ".join(a["commi"])
        a["note"] = sorted(set(a["note"]))
        a["abrogato"] = bool(a["commi"]) and all(
            RE_ABROGATO_INTERO.fullmatch(t.replace(" ", "")) for t in a["commi"])
        a["abrogatoInParte"] = not a["abrogato"] and bool(RE_ABROGATO_PARTE.search(a["testo"]))
    return articoli


def origine(nota):
    trovata = cp.origine(nota)
    if trovata:
        return trovata
    m = RE_ORIGINE_ESTESA.search(nota)
    return m and {"tipo": re.sub(r"\s+", " ", m.group(1)).strip(),
                  "numero": int(m.group(3)), "anno": int(m.group(2)), "articolo": m.group(4)}


def leggi(pdf):
    corpo, righe_note = righe_pdf(pdf)
    segmenti = segmenta(corpo)
    for s in segmenti:
        s["articoli"], s["partizioni"] = estrai_articoli(s["righe"])
        rifinisci(s["articoli"])
    quante = max([n for s in segmenti for a in s["articoli"] for n in a["note"]]
                 + [n for s in segmenti for p in s["partizioni"] for n in p["note"]]
                 + [0])
    note = {n: RE_ABROGATI_DA.sub(r"\1Modifiche legislative: ", t)
            for n, t in cp.spezza_note(righe_note, quante).items()}
    voci = [v for s in segmenti for v in s["articoli"] + s["partizioni"]]
    per_nota = {n: [{**m, "nota": n} for m in cp.modifiche(t)] for n, t in note.items()}
    for voce in voci:
        voce["modifiche"], voce["origine"] = [], None
        # Una nota che dice solo "Si veda il Decreto Delegato n.35/2025" o
        # riporta una proroga di termini non tocca il testo dell'articolo:
        # riscriverlo per quella nota costerebbe vettori e citazioni senza
        # cambiare una parola.
        voce["noteSostanziali"] = [n for n in voce["note"]
                                   if RE_NOTA_SOSTANZIALE.search(note.get(n, ""))]
        for n in voce["note"]:
            voce["modifiche"] += [dict(m) for m in per_nota.get(n, [])]
            voce["origine"] = voce["origine"] or origine(note.get(n, ""))
    risolvi_rinvii(voci, per_nota)
    aggiornato = next((RE_AGGIORNAMENTO.search(t).group(1).strip()
                       for t, _, _, _ in corpo[:80] if RE_AGGIORNAMENTO.search(t)), None)
    return segmenti, note, aggiornato


def _rinvio(testo):
    return RE_RINVIO_NOTA.search(testo) if len(testo) < 200 else None


def risolvi_rinvii(voci, per_nota):
    """"vedere nota n. 15", "vedere nota precedente": il testo della modifica
    sta in un'altra nota.

    Prima si guarda la nota indicata, se vi compare lo stesso atto: nel Lavoro
    la L-63/1985 modifica sia la L-7/1961 sia la L-23/1977, e cercata solo per
    atto e articolo la nota 16 riceveva il testo scritto per la L-7. Ma il
    numero puo' essere sbagliato - "Decreto-Legge n.30/2018, Articolo 5:
    vedere nota n. 4." nell'Edilizia, dove e' la 5 - e allora, se la nota
    indicata non nomina l'atto per quell'articolo, vale atto e articolo; senza,
    gli artt. 29 e 30 restavano abrogati senza fonte.
    """
    completi = {}
    for voce in voci:
        for m in voce["modifiche"]:
            if not _rinvio(m["testo"]):
                completi.setdefault((m["numero"], m["anno"], m["articolo"]), m["testo"])
    for voce in voci:
        for m in voce["modifiche"]:
            r = _rinvio(m["testo"])
            if not r:
                continue
            indicata = (int(r.group("numero")) if r.group("numero")
                        else m["nota"] - 1 if r.group("precedente") else None)
            candidati = [c for c in per_nota.get(indicata, [])
                         if (c["numero"], c["anno"]) == (m["numero"], m["anno"])
                         and not _rinvio(c["testo"])
                         and (c["articolo"] is None or m["articolo"] is None
                              or c["articolo"] == m["articolo"])]
            if candidati:
                m["testo"] = candidati[0]["testo"]
            else:
                m["testo"] = completi.get((m["numero"], m["anno"], m["articolo"]), m["testo"])


def abroganti(articolo):
    """cp.abroganti sulle modifiche con gli elenchi di articoli ricuciti."""
    return cp.abroganti({**articolo, "modifiche": [
        {**m, "testo": RE_PARTIZIONE_IN_ELENCO.sub("", m["testo"])}
        for m in articolo["modifiche"]]})


# ------------------------------------------------------------ risoluzione atti

def indice_norme(g):
    indice = {}
    for r in g.query("""
        MATCH (n:Norma) WHERE n.numero IS NOT NULL AND n.anno IS NOT NULL
        RETURN n.id AS id, n.numero AS numero, n.anno AS anno,
               COUNT { (n)-[:HA_ARTICOLO]->() } AS articoli"""):
        try:
            chiave = (int(r["numero"]), int(r["anno"]))
        except (TypeError, ValueError):
            continue
        indice.setdefault(chiave, []).append(r)
    return indice


# "Decreto" senza aggettivo e' la forma breve con cui le note chiamano anche i
# Decreti Consiliari e Reggenziali: il Decreto 21 febbraio 2006 n.39 e' nel
# grafo come DC-39-2006, e D-39-2006 e' uno stub vuoto nato da una citazione.
# I decreti condividono una numerazione annua, e il portale a volte registra
# da Decreto Delegato una ratifica che il coordinato chiama Decreto-Legge: il
# "Decreto - Legge 24 luglio 2014 n.118" e' nel grafo come DD-118-2014.
AFFINI = {"D": {"D", "DC", "DR"}, "DL": {"DL", "DD"}, "DD": {"DD", "DL"}}


def risolutore(indice):
    def risolvi(tipo, numero, anno):
        try:
            atteso = norma_id(tipo, numero, anno)
        except ValueError:
            return None
        caricati = [c for c in indice.get((numero, anno), [])
                    if c["articoli"] > 0 and SEPARATORE_COLLISIONE not in c["id"]]
        if any(c["id"] == atteso for c in caricati):
            return atteso
        prefisso = atteso.split("-")[0]
        scelti = [c["id"] for c in caricati
                  if c["id"].split("-")[0] in AFFINI.get(prefisso, {prefisso})]
        return scelti[0] if len(scelti) == 1 else None
    return risolvi


# ---------------------------------------------------------------- abrogazioni

def abroganti_partizione(partizione, risolvi):
    """Chi ha abrogato un Titolo, fra gli atti elencati nella sua nota.

    Stessa regola di vicinanza di cp.abroganti, ma sul nome della partizione:
    "l'articolo 1, il Titolo II ed il Titolo V della Legge n.110/1994 ... sono
    abrogate" non nomina nessuno degli articoli 31-36, e cercarli per numero
    avrebbe lasciato il Titolo abrogato senza fonte.
    """
    romano = partizione["nome"].split()[-1]
    fuori = []
    for m in partizione["modifiche"]:
        testo = m["testo"]
        for t in RE_TITOLO_CITATO.finditer(testo):
            if t.group(1) != romano:
                continue
            for a in cp.RE_ABROGATO.finditer(testo):
                fra = (testo[t.end():a.start()] if a.start() > t.end()
                       else testo[a.end():t.start()] if a.end() < t.start() else None)
                if fra is not None and len(fra) <= cp.DISTANZA_ABROGAZIONE \
                        and not cp.RE_FRAMMENTO.search(fra):
                    atto = risolvi(m["tipo"], m["numero"], m["anno"])
                    if atto:
                        fuori.append(atto)
                    break
    return sorted(set(fuori))


# ------------------------------------------------------------------- scrittura

Q_PRESENTI = """
MATCH (:Norma {id: $norma})-[:HA_ARTICOLO]->(a:Articolo)
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
WITH a, c ORDER BY c.ordine
RETURN a.id AS id, a.numero AS numero, a.ordine AS ordine, a.titolo AS titolo,
       a.capo AS capo, collect(c.testo) AS commi,
       all(x IN collect(c) WHERE coalesce(x.commaImplicito, false)) AS implicito
"""

# Come Q_ARTICOLI di 10, con due differenze. L'ordine si tocca solo dove si
# riscrive l'atto intero: altrove l'articolo resta al suo posto. E il vettore
# della rubrica cade se la rubrica cambia, come quello del comma col testo -
# altrimenti la ricerca risponde con il significato di prima.
Q_ARTICOLI = """
UNWIND $articoli AS a
MATCH (n:Norma {id: $norma})
MERGE (art:Articolo {id: a.id})
  ON CREATE SET art.ordine = a.ordine
SET art.testoOriginario = CASE
      WHEN art.testoOriginario IS NOT NULL AND art.testoOriginario <> a.testo
        THEN art.testoOriginario
      WHEN art.testo IS NOT NULL AND art.testo <> a.testo THEN art.testo
      ELSE null END,
    art.embedding = CASE WHEN a.rubrica IS NULL OR art.rubrica = a.rubrica
                         THEN art.embedding ELSE null END,
    art.rubrica = coalesce(a.rubrica, art.rubrica),
    art.testo = a.testo,
    art.numero = a.numero,
    art.ordine = CASE WHEN a.riordina THEN a.ordine ELSE art.ordine END,
    art.titolo = coalesce(a.titolo, art.titolo),
    art.titoloRubrica = coalesce(a.titoloRubrica, art.titoloRubrica),
    art.capo = CASE WHEN a.titolo IS NULL THEN art.capo ELSE a.capo END,
    art.capoRubrica = CASE WHEN a.titolo IS NULL THEN art.capoRubrica ELSE a.capoRubrica END,
    art.fonteTesto = $fonte,
    art.testoAggiornatoAl = $aggiornato
MERGE (n)-[:HA_ARTICOLO]->(art)
"""

# Le citazioni ricavate dal testo vecchio si staccano prima di riscriverlo:
# quelle marcate con un'origine le ha scritte qualcun altro e restano.
Q_STACCA_CITAZIONI = """
UNWIND $articoli AS aid
MATCH (:Articolo {id: aid})-[:HA_COMMA]->(:Comma)-[r:CITA|CITA_ARTICOLO]->()
WHERE r.origine IS NULL
DELETE r
"""

# Stessa forma di Q_CITAZIONI in 03_load.py.
Q_CITA = """
UNWIND $citazioni AS c
MATCH (cm:Comma {id: c.commaId})
MERGE (target:Norma {id: c.targetId})
  ON CREATE SET target.tipo = c.tipo, target.numero = c.numero,
                target.anno = c.anno, target.caricata = false
MERGE (cm)-[r:CITA]->(target)
SET r.testoCitazione = c.testo,
    r.articoloCitato = c.articoloCitato,
    r.commaCitato = c.commaCitato
"""

# Stessa regola di 09: l'arco si crea solo se il numero identifica un articolo
# solo.
Q_CITA_ARTICOLO = """
UNWIND $citazioni AS k
MATCH (cm:Comma {id: k.commaId})
MATCH (:Norma {id: k.bersaglio})-[:HA_ARTICOLO]->(a:Articolo)
WHERE trim(coalesce(a.numero, '')) = k.numero
WITH cm, collect(a) AS trovati
WHERE size(trovati) = 1
WITH cm, trovati[0] AS a
MERGE (cm)-[:CITA_ARTICOLO]->(a)
"""


Q_ARTICOLI_ATTO = """
MATCH (:Norma {id: $atto})-[:HA_ARTICOLO]->(a:Articolo)
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
WITH a, c ORDER BY c.ordine
WITH a, collect(c.testo) AS commi
RETURN a.numero AS numero, coalesce(a.rubrica, '') + ' ' + coalesce(commi[0], '') AS testo
"""


def articolo_introduttivo(g, atto, numero, anno, articolo):
    """L'articolo di `atto` che ha inserito `articolo` nella legge numero/anno.

    Si riconosce da rubrica e primo comma: nominano l'articolo inserito
    ("articolo 3-bis"), la legge che lo riceve ("Legge n.44/2015") e il verbo
    dell'inserimento. Vale solo se il candidato e' uno: meglio nessun arco che
    uno sull'articolo sbagliato.
    """
    base, _, ordinale = str(articolo).partition("-")
    nome = re.escape(base) + (r"\s*[-\s]?\s*" + re.escape(ordinale) if ordinale else "")
    re_articolo = re.compile(r"articol[oi]\s+" + nome + r"\b", re.I)
    re_legge = re.compile(rf"\b{numero}\s*/\s*{anno}\b|\b{anno}\s*,?\s*n\.?\s*{numero}\b", re.I)
    re_verbo = re.compile(r"aggiunt|inserit|introdu", re.I)
    candidati = [r["numero"] for r in g.query(Q_ARTICOLI_ATTO, {"atto": atto})
                 if all(e.search(r["testo"][:800]) for e in (re_articolo, re_legge, re_verbo))]
    return candidati[0] if len(candidati) == 1 else None


def gemelli(g, norma):
    return [r["id"] for r in g.query(
        "MATCH (n:Norma) WHERE n.id = $n OR n.id STARTS WITH $p RETURN n.id AS id ORDER BY id",
        {"n": norma, "p": norma + SEPARATORE_COLLISIONE})]


def _piano(testo):
    return " ".join((testo or "").split()).lower()


def pianifica(segmento, presenti):
    """Quali articoli riscrivere, e con quale ordine.

    Restituisce anche gli articoli lasciati stare perche' veicolo di una
    novella, e quelli riscritti perche' nel grafo avevano inghiottito un
    articolo "-bis".
    """
    # Un estratto in appendice non dice nulla degli articoli che non riporta:
    # "tutti impliciti" autorizza a riscrivere l'atto intero solo se il
    # coordinato l'atto intero lo contiene.
    # Anche nel corpo una raccolta puo' riportare un solo pezzo di un atto: il
    # Lavoro tiene due articoli dei quindici del DD-14/2018. Riordinare l'atto
    # intero su quei due si fa solo se il coordinato copre quasi tutto il grafo.
    coperti = {cp.chiave(a["numero"]) for a in segmento["articoli"]} & set(presenti)
    tutto_implicito = (not segmento["appendice"] and bool(presenti)
                       and all(p["implicito"] for p in presenti.values())
                       and len(coperti) >= 0.9 * len(presenti))
    visti, doppi, scelti, veicoli, assorbenti = set(), [], [], [], []
    precedente_presente = None
    for a in segmento["articoli"]:
        k = cp.chiave(a["numero"])
        if k in visti:
            doppi.append(a["numero"])
            continue
        visti.add(k)
        if k in presenti:
            if (tutto_implicito or a["noteSostanziali"]
                    or a["abrogato"] or a["abrogatoInParte"]):
                if (not tutto_implicito and a["commi"]
                        and RE_VEICOLO_NOVELLA.search(a["commi"][0][:300])):
                    a["veicolo"] = True
                    veicoli.append(a["numero"])
                else:
                    scelti.append(a)
            precedente_presente = a
            continue
        scelti.append(a)
        # Il parser non riconosceva "Art. 6 - bis": il testo del 6-bis e del
        # 6-ter e' finito dentro l'art. 6 del DL-30/2018, che nel grafo ha 22
        # commi. Aggiungere il 6-bis senza riscrivere il 6 terrebbe lo stesso
        # testo due volte.
        if precedente_presente is not None and a["commi"]:
            inizio = _piano(a["commi"][0])[:60]
            vecchio = _piano(" ".join(presenti[cp.chiave(precedente_presente["numero"])]["commi"]))
            if inizio and inizio in vecchio and precedente_presente not in scelti:
                scelti.append(precedente_presente)
                assorbenti.append(precedente_presente["numero"])
    # Un articolo nuovo si mette subito dopo quello che lo precede nel
    # coordinato: il 3-bis dopo il 3, non in fondo all'atto.
    massimo = max([p["ordine"] for p in presenti.values() if p["ordine"] is not None] + [0])
    # Si rinumera solo se il coordinato ha tutti gli articoli del grafo: la
    # L-7/1961 non riporta il Titolo I abrogato, e gli artt. 6-60 rinumerati da
    # 1 avrebbero preso l'ordine degli artt. 1-5, che restano.
    riordina = tutto_implicito and set(presenti) <= {cp.chiave(a["numero"]) for a in segmento["articoli"]}
    ultimo = None
    for i, a in enumerate(segmento["articoli"], 1):
        k = cp.chiave(a["numero"])
        if riordina:
            a["ordine"], a["riordina"] = i, True
        elif k in presenti:
            a["ordine"], a["riordina"] = presenti[k]["ordine"], False
        else:
            a["ordine"], a["riordina"] = (ultimo if ultimo is not None else massimo) + 0.01, False
        ultimo = a["ordine"] if a["ordine"] is not None else ultimo
    ordine_scelti = {id(a) for a in scelti}
    scelti = [a for a in segmento["articoli"] if id(a) in ordine_scelti]
    return scelti, tutto_implicito, doppi, veicoli, assorbenti


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--nome", required=True, help="slug della raccolta, per il file di evidenze")
    ap.add_argument("--scrivi", action="store_true")
    ap.add_argument("--dump", help="salva gli articoli letti in questo JSON, per controllarli")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        sys.exit(f"PDF non trovato: {pdf}")

    segmenti, note, aggiornato = leggi(pdf)
    print(f"\n  {pdf.name} - {FONTE}, aggiornato al {aggiornato}")
    print(f"  atti letti {len(segmenti)} | note {len(note)}")
    if args.dump:
        Path(args.dump).write_text(json.dumps(
            [{k: v for k, v in s.items() if k != "righe"} for s in segmenti],
            ensure_ascii=False, indent=1), encoding="utf-8")

    g = cp.grafo()
    risolvi = risolutore(indice_norme(g))
    # cp.abroganti risolve gli atti con cp.id_atto: gli si passa il resolver
    # che conosce gli stub, o il Decreto n.39/2006 finirebbe sullo stub vuoto.
    cp.id_atto = lambda m: risolvi(m["tipo"], m["numero"], m["anno"]) or norma_id(
        m["tipo"], m["numero"], m["anno"])

    piani, irrisolti = [], set()
    for s in segmenti:
        norma = risolvi(s["tipo"], s["numero"], s["anno"])
        etichetta = f"{s['tipo']} {s['numero']}/{s['anno']}" + (" (altre norme)" if s["appendice"] else "")
        if norma is None:
            print(f"\n  ! {etichetta}: nessun atto caricato corrispondente nel grafo, saltato")
            continue
        presenti = {cp.chiave(r["numero"]): r for r in g.query(Q_PRESENTI, {"norma": norma})}
        scelti, tutto, doppi, veicoli, assorbenti = pianifica(s, presenti)
        nuovi = [a["numero"] for a in scelti if cp.chiave(a["numero"]) not in presenti]
        uguali = sum(1 for a in scelti if cp.chiave(a["numero"]) in presenti
                     and presenti[cp.chiave(a["numero"])]["commi"] == a["commi"])
        print(f"\n  {etichetta} -> {norma}")
        print(f"    nel coordinato {len(s['articoli'])} articoli | nel grafo {len(presenti)}"
              f" | da riscrivere {len(scelti)}{' (tutti: nel grafo erano commi impliciti)' if tutto else ''}"
              f" | gia' identici {uguali}")
        if nuovi:
            print(f"    nuovi: {', '.join(nuovi)}")
        if assorbenti:
            print(f"    riscritti perche' nel grafo contenevano l'articolo inserito dopo: {', '.join(assorbenti)}")
        if veicoli:
            print(f"    lasciati stare, introducono una novella in un altro atto: {', '.join(veicoli)}")
        if doppi:
            print(f"    ! numeri ripetuti nel coordinato, tenuto il primo: {', '.join(doppi)}")
        abrogati = [a["numero"] for a in s["articoli"] if a["abrogato"]]
        in_parte = [a["numero"] for a in s["articoli"] if a["abrogatoInParte"]]
        if abrogati or in_parte:
            print(f"    [ABROGATO] interi: {', '.join(abrogati) or '-'} | in parte: {', '.join(in_parte) or '-'}")

        evidenze = [{"articolo": a["numero"],
                     "fonti": [f for f in abroganti(a) if f],
                     "articoloId": f"{norma}/art-{a['numero']}"}
                    for a in s["articoli"] if a["abrogato"]]
        vivi = {cp.chiave(a["numero"]) for a in s["articoli"] if not a["abrogato"]}
        for p in s["partizioni"]:
            if not p["abrogata"]:
                continue
            campo = "titolo" if p["tipo"] == "Titolo" else "capo"
            dentro = [r for r in presenti.values()
                      if (r[campo] or "").lower() == p["nome"].lower()
                      and cp.chiave(r["numero"]) not in vivi]
            fonti = abroganti_partizione(p, risolvi)
            print(f"    {p['nome']} [ABROGATO]: articoli {', '.join(r['numero'] for r in dentro) or 'nessuno trovato'}"
                  f" | fonte {', '.join(fonti) or '(non dichiarata)'}")
            evidenze += [{"articolo": r["numero"], "fonti": fonti, "articoloId": r["id"],
                          "partizione": p["nome"]} for r in dentro]
        for e in evidenze:
            if "partizione" not in e:
                print(f"     art. {e['articolo']:<8} {', '.join(e['fonti']) or '(fonte non dichiarata)'}")

        novelle = []
        for a in s["articoli"]:
            # Le modifiche elencate sotto un veicolo di novella riguardano
            # l'atto bersaglio: agganciarle al veicolo direbbe che il
            # Decreto-Legge n.103/2018 ha modificato la L-115/2017.
            if a.get("veicolo"):
                continue
            for m in a["modifiche"] + ([a["origine"]] if a["origine"] else []):
                atto = risolvi(m["tipo"], m["numero"], m["anno"])
                if atto is None:
                    irrisolti.add(f"{m['tipo']} {m['numero']}/{m['anno']}")
                elif m.get("articolo") and atto != norma:
                    novelle.append({"atto": atto, "articolo": m["articolo"],
                                    "bersaglio": f"{norma}/art-{a['numero']}",
                                    "numeroBersaglio": (re.match(r"\d+", a["numero"])
                                                        or re.match(r".+", a["numero"])).group(0)})
                elif m is a["origine"] and atto != norma:
                    # "Testo originario (Legge n.64/2025)" non dice quale
                    # articolo abbia inserito il 3-bis nella L-44/2015: senza
                    # arco l'agente non sapeva che l'art. 5 della L-64/2025 e il
                    # 3-bis sono lo stesso testo, e lo cercava nella legge sbagliata.
                    introduttivo = articolo_introduttivo(g, atto, s["numero"], s["anno"], a["numero"])
                    if introduttivo:
                        novelle.append({"atto": atto, "articolo": introduttivo,
                                        "bersaglio": f"{norma}/art-{a['numero']}",
                                        "numeroBersaglio": a["numero"]})
                        print(f"    art. {a['numero']} inserito da {atto}, art. {introduttivo}")
                    else:
                        print(f"    ! art. {a['numero']} inserito da {atto}: articolo introduttivo non trovato")
        print(f"    novelle agganciabili {len(novelle)}")
        piani.append({"segmento": s, "norma": norma, "scelti": scelti,
                      "evidenze": evidenze, "novelle": novelle})

    if irrisolti:
        print(f"\n  atti modificanti non risolti sul grafo ({len(irrisolti)}): "
              + ", ".join(sorted(irrisolti)))

    if not args.scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi per applicare al grafo.")
        return

    conta = lambda: g.query("""
        MATCH (c:Comma) WITH count(c) AS commi
        MATCH ()-[r:CITA_ARTICOLO]->() WITH commi, count(r) AS ca
        MATCH ()-[r:CITA]->() RETURN commi, ca, count(r) AS cita""")[0]
    prima = conta()
    scritti_art = scritti_commi = 0
    for piano in piani:
        s, norma = piano["segmento"], piano["norma"]
        for scheda in gemelli(g, norma):
            lotto = []
            for a in piano["scelti"]:
                aid = f"{scheda}/art-{a['numero']}"
                lotto.append({**{k: a[k] for k in ("numero", "rubrica", "testo", "ordine", "riordina",
                                                  "titolo", "titoloRubrica", "capo", "capoRubrica")},
                              "id": aid, "commi": a["commi"], "numeri": a["numeri"],
                              "commiId": [f"{aid}/c-{k}" for k in range(1, len(a["commi"]) + 1)]})
            if not lotto:
                continue
            g.query(Q_ARTICOLI, {"norma": scheda, "fonte": FONTE, "aggiornato": aggiornato,
                                 "articoli": [{k: v for k, v in x.items()
                                               if k not in ("commi", "numeri", "commiId")}
                                              for x in lotto]})
            g.query(Q_STACCA_CITAZIONI, {"articoli": [x["id"] for x in lotto]})
            g.query(cp.Q_PULISCI_COMMI, {"articoli": [{"id": x["id"], "commiId": x["commiId"]}
                                                      for x in lotto]})
            g.query(cp.Q_COMMI, {"commi": [
                {"articoloId": x["id"], "id": cid, "numero": num, "ordine": k, "testo": testo}
                for x in lotto
                for k, (cid, num, testo) in enumerate(zip(x["commiId"], x["numeri"], x["commi"]), 1)]})
            citazioni, cita_articolo = [], []
            for x in lotto:
                for cid, testo in zip(x["commiId"], x["commi"]):
                    for c in parser.estrai_citazioni(testo, norma):
                        if not c["anno"]:
                            continue
                        try:
                            target = norma_id(c["tipo"], c["numero"], c["anno"])
                        except ValueError:
                            continue
                        citazioni.append({**c, "commaId": cid, "targetId": target})
                    for bersaglio, numero in riallinea.bersagli(" ".join(testo.split()), norma):
                        cita_articolo.append({"commaId": cid, "bersaglio": bersaglio,
                                              "numero": numero})
            if citazioni:
                g.query(Q_CITA, {"citazioni": citazioni})
            if cita_articolo:
                g.query(Q_CITA_ARTICOLO, {"citazioni": cita_articolo})
            scritti_art += len(lotto)
            scritti_commi += sum(len(x["commi"]) for x in lotto)

        if piano["novelle"]:
            for scheda in gemelli(g, norma):
                g.query(cp.Q_PULISCI_NOVELLE, {"norma": scheda, "origine": FONTE})
            g.query(cp.Q_NOVELLE, {"novelle": piano["novelle"], "origine": FONTE})

        if piano["evidenze"]:
            DERIVATO.mkdir(parents=True, exist_ok=True)
            file = DERIVATO / f"abrogazioni_{args.nome}_{norma}.json"
            file.write_text(json.dumps(
                {"norma": norma, "fonte": f"{FONTE} ({pdf.name})", "aggiornatoAl": aggiornato,
                 "articoli": [{**e, "articoloId": e["articoloId"].replace(norma, scheda, 1)}
                              for scheda in gemelli(g, norma) for e in piano["evidenze"]]},
                ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  evidenze di abrogazione: {file.relative_to(RADICE)}")

    dopo = conta()
    print(f"\n  scritti {scritti_art} articoli e {scritti_commi} commi")
    print(f"  commi {prima['commi']:,} -> {dopo['commi']:,} | CITA {prima['cita']:,} -> {dopo['cita']:,}"
          f" | CITA_ARTICOLO {prima['ca']:,} -> {dopo['ca']:,}")
    print("\n  Ora: 08_abrogazioni.py --scrivi, poi 07_embeddings.py e 07b_embeddings_rubriche.py.")


if __name__ == "__main__":
    main()
