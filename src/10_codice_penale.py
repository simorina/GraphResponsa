"""
10 - Integra nel grafo il testo coordinato del Codice Penale.

L'archivio del portale non e' consolidato: pubblica ogni atto nella forma in
cui e' nato. Del Codice Penale il grafo teneva percio' la versione del 1974,
in blocco - 408 articoli, 408 commi tutti impliciti, due sole rubriche, zero
citazioni uscenti - mentre cinquant'anni di novelle non comparivano da
nessuna parte.

Il testo coordinato pubblicato dal Consiglio Grande e Generale contiene
invece tutto cio' che al grafo mancava, e in forma leggibile da un programma:

  - il testo VIGENTE di ogni articolo, con i capoversi al loro posto;
  - le rubriche;
  - gli articoli inseriti dopo il 1974 (69-bis, 282-bis, 340-bis...), che nel
    grafo non esistevano affatto;
  - la marcatura [ABROGATO] sugli articoli caduti;
  - per ogni articolo toccato, l'elenco degli atti che l'hanno modificato con
    il rispettivo articolo: e' il dato di novella che il parser non riesce a
    ricavare dal testo degli atti modificanti.

Il testo del 1974 non si butta: finisce in Articolo.testoOriginario, cosi'
resta possibile dire come la disposizione suonava prima.

Le abrogazioni NON si scrivono qui. 08_abrogazioni.py azzera e riscrive da
capo Articolo.abrogato a ogni esecuzione - e' cosi' che resta idempotente -
quindi qualunque marcatura scritta altrove sparirebbe alla prima riesecuzione.
Questo script deposita le evidenze in data/derivato/, e 08 le legge.

Uso:
    .venv/Scripts/python.exe src/10_codice_penale.py             # solo misura
    .venv/Scripts/python.exe src/10_codice_penale.py --scrivi    # applica

E' idempotente: rieseguirlo sullo stesso PDF riscrive gli stessi valori.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import fitz
from dotenv import load_dotenv
from langchain_neo4j import Neo4jGraph

sys.path.insert(0, str(Path(__file__).parent))
from comune import norma_id  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
PDF_DEFAULT = RADICE / "data" / "coordinati" / "codice-penale.pdf"
EVIDENZE = RADICE / "data" / "derivato" / "abrogazioni_codice_penale.json"

NORMA = "L-17-1974"
FONTE = "testo coordinato del Consiglio Grande e Generale"

# ---------------------------------------------------------------- estrazione

ORDINALI = ("bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies"
            "|undecies|duodecies|terdecies|quaterdecies")
RE_ART = re.compile(
    r"^\s*Art(?:\.|icolo)\s*(\d+)\s*(?:[-\s]\s*(" + ORDINALI + r"))?\s*\.?\s*$", re.I)
RE_PARTIZIONE = re.compile(
    r"^\s*(LIBRO|TITOLO|CAPO|CAPITOLO|SEZIONE)\s+[IVXLC]+\s*$", re.I)
RE_ENUMERATORE = re.compile(r"^\s*(?:\d{1,2}\)|[a-z]\)|[a-z]\.)\s*$", re.I)
RE_AGGIORNATO = re.compile(r"\(Aggiornato al\s+([^)]+)\)", re.I)

# Nel PDF i capoversi rientrano: la prima riga parte da x~92, le successive da
# x~57. E' l'unico segnale di confine fra un comma e l'altro - il testo non li
# numera - ed e' netto, mentre l'euristica sulla punteggiatura non lo e'.
X_RIENTRO = 75
X_CENTRATO = 130


def righe_pdf(pdf):
    """Corpo e note, separati per corpo del carattere.

    Le note stanno a 8pt, il testo a 11-12pt: la separazione e' netta e non
    richiede di indovinare dove finisce la pagina. Il richiamo di nota e' uno
    span di sole cifre piu' piccolo sulla stessa riga, e va staccato: senza
    questo "Art. 153" con la nota 43 diventa "Art. 15343".
    """
    corpo, note = [], []
    for pagina in fitz.open(pdf):
        visive = {}
        for blocco in pagina.get_text("dict")["blocks"]:
            for riga in blocco.get("lines", []):
                span = riga["spans"]
                dim = max((s["size"] for s in span), default=0)
                if dim < 10:
                    note.append("".join(s["text"] for s in span).rstrip())
                    continue
                # Le intestazioni centrate hanno le parole molto distanziate e
                # PyMuPDF ne fa una "riga" per parola: "La | concessione |
                # della | liberazione | condizionale". Vanno rimesse insieme
                # per quota verticale, altrimenti ogni parola sembra un
                # capoverso a se' e il rientro non dice piu' nulla.
                visive.setdefault(round(riga["bbox"][1]), []).append((riga, dim))
        for quota in sorted(visive):
            pezzi = sorted(visive[quota], key=lambda r: r[0]["bbox"][0])
            testo, richiami = "", []
            for riga, dim in pezzi:
                for s in riga["spans"]:
                    if s["size"] < dim - 1 and s["text"].strip().isdigit():
                        richiami.append(int(s["text"].strip()))
                    else:
                        testo += s["text"]
                testo += " "
            corpo.append((re.sub(r"\s+", " ", testo).strip(),
                          round(pezzi[0][0]["bbox"][0]), richiami))
    return corpo, note


def solo_codice(corpo):
    """Il Codice finisce dove comincia l'appendice 'ALTRE NORME'.

    L'appendice riporta gli atti di coordinamento, che hanno una propria
    numerazione di articoli: senza il taglio si sovrascriverebbero gli
    articoli 1, 2, 3... del Codice con quelli della Legge n.86/1974.
    """
    inizio = next(i for i, (t, _, _) in enumerate(corpo) if RE_ART.match(t))
    fine = next(i for i, (t, _, _) in enumerate(corpo) if t == "ALTRE NORME")
    return corpo[inizio:fine]


def estrai_articoli(righe):
    articoli, corrente, rubrica_aperta = [], None, False
    for testo, x, richiami in righe:
        m = RE_ART.match(testo)
        if m:
            numero = m.group(1) + ("-" + m.group(2).lower() if m.group(2) else "")
            corrente = {"numero": numero, "rubrica": None, "commi": [],
                        "note": list(richiami)}
            articoli.append(corrente)
            rubrica_aperta = False
            continue
        if corrente is None or not testo:
            continue
        corrente["note"] += richiami

        # La rubrica sta fra parentesi subito sotto il numero e puo' andare a
        # capo: "(Improcedibilita' per taluni reati commessi all'estero in
        # danno di un cittadino)" occupa due righe.
        if not corrente["commi"] and (rubrica_aperta or testo.startswith("(")):
            corrente["rubrica"] = ((corrente["rubrica"] or "") + " " + testo).strip()
            rubrica_aperta = not testo.endswith(")")
            if not rubrica_aperta:
                corrente["rubrica"] = corrente["rubrica"].strip("()").strip()
            continue
        if RE_PARTIZIONE.match(testo) or re.fullmatch(r"\d{1,3}", testo):
            continue
        # Intestazione di partizione non numerata ("MISFATTI", "La concessione
        # della liberazione condizionale"): sta al centro della pagina, dove
        # il testo dell'articolo non arriva mai. [ABROGATO] e' centrato pure
        # lui ma non e' un'intestazione: e' la sostanza dell'articolo.
        if x >= X_CENTRATO and "[" not in testo:
            continue
        # Alcune intestazioni ("I MISFATTORI ABITUALI, DI MESTIERE E
        # COSTITUZIONALI") stanno piu' a sinistra della soglia e finivano in
        # coda all'articolo precedente. Si riconoscono dal non avere una sola
        # minuscola: il testo degli articoli non e' mai scritto cosi'.
        if testo.upper() == testo and re.search(r"[A-ZÀ-Ù]{3}", testo) and "[" not in testo:
            continue

        if not corrente["commi"] or (x >= X_RIENTRO
                                     and apre_comma(testo, corrente["commi"][-1])):
            corrente["commi"].append([testo])
        else:
            corrente["commi"][-1].append(testo)
    return articoli


def apre_comma(testo, precedente):
    """Se la riga rientrata comincia davvero un comma nuovo.

    Il rientro da solo non basta. Negli articoli inseriti di recente anche le
    voci di un elenco rientrano, e l'elenco appartiene al comma che lo
    introduce: senza questo controllo l'art. 340-bis diventava sei commi, uno
    dei quali spezzato a meta' frase ("costringere i poteri pubblici a
    compiere o" / "astenersi dal compiere un qualsiasi atto").

    Il segnale sta nella punteggiatura di chi precede - un comma non finisce
    con i due punti, col punto e virgola o con una virgola - e nella maiuscola
    di chi comincia.
    """
    if RE_ENUMERATORE.match(precedente[-1]):
        return False               # "1)" isolato: la voce che introduce e' sua
    if " ".join(precedente).rstrip().endswith((":", ";", ",")):
        return False
    primo = testo.lstrip()[:1]
    return primo.isupper() or primo.isdigit() or primo in "[«“"


def rifinisci(articoli):
    for a in articoli:
        a["commi"] = [c for c in (" ".join(p).strip() for p in a["commi"]) if c]
        a["testo"] = " ".join(a["commi"])
        a["note"] = sorted(set(a["note"]))
        # [ABROGATO] al posto del testo significa che l'articolo e' caduto;
        # [ABROGATO] in mezzo al testo segna il singolo punto caduto - l'art.
        # 90 ha perso il punto 4) del primo comma, l'art. 282 il n. 2 - e
        # l'articolo resta in vigore. Marcarlo abrogato sarebbe un'affermazione
        # falsa, e il grafo autorizza a dire "abrogato" solo dove lo sa.
        # Il marcatore compare come "[ABROGATO]" e come "[ABROGATO]." - la
        # punteggiatura finale non cambia il fatto.
        a["abrogato"] = bool(a["commi"]) and re.fullmatch(
            r"\[ABROGATO\][.;]?", a["commi"][0].replace(" ", "")) is not None
        a["abrogatoInParte"] = not a["abrogato"] and "[ABROGATO]" in a["testo"]
    return articoli


# --------------------------------------------------------------------- note

MESI = ("gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto"
        "|settembre|ottobre|novembre|dicembre")
TIPO = (r"Legge Costituzionale|Legge Qualificata|Legge"
        r"|Decreto\s*[-–—]?\s*Legge|Decreto Delegato"
        r"|Decreto Reggenziale|Decreto Consiliare|Decreto")

# Nelle intestazioni l'atto e' per esteso ("Legge 31 marzo 2014 n.41"), nel
# richiamo al testo originario e' abbreviato ("Legge n.101/2003"): due forme,
# due espressioni.
# Gli estremi compaiono per esteso ("31 marzo 2014 n.41") e in forma breve
# ("n.59/2025"): la seconda apre l'intestazione che abroga l'art. 282-bis, e
# senza di essa quel testo finiva attribuito al Decreto che l'articolo lo
# aveva soltanto modificato.
ESTREMI = (r"(?:\s+\d{1,2}\s+(?:" + MESI + r")\s+(?P<anno>\d{4})\s*,?\s*n\.?\s*(?P<numero>\d+)"
           r"|\s*n\.?\s*(?P<numero2>\d+)\s*/\s*(?P<anno2>\d{4}))")
RE_MODIFICA = re.compile(
    r"(?P<tipo>" + TIPO + r")" + ESTREMI +
    # Di norma l'intestazione chiude con i due punti, ma non sempre: la Legge
    # n.24/2022 che abroga l'art. 145 e' seguita dalla propria rubrica fra
    # parentesi, e senza questa alternativa il suo testo finiva assorbito
    # nell'atto precedente - che l'articolo l'aveva riscritto, non abrogato.
    # La chiusura larga vale pero' solo per chi dichiara il proprio articolo:
    # concessa a tutti agganciava ogni richiamo a meta' frase ("l'articolo 1
    # della Legge n.139/1997 (") e ne nascevano decine di modifiche inventate.
    r"(?:[^:\n]{0,80}?,?\s*(?:Articolo|Art\.?)\s*(?P<articolo>\d+[a-z\-]*)"
    r"(?:\s*,?\s*comma\s+(?P<comma>\S+?))?\s*(?::|(?=\s*\()|(?=\s*\d+\.\s))"
    r"|[^:\n]{0,80}?:)", re.I)
RE_ORIGINE = re.compile(
    r"Testo originario\s*\(\s*(" + TIPO + r")\s*n\.?\s*(\d+)\s*/\s*(\d{4})"
    r"(?:\s*,\s*(?:Articolo|Art\.?)\s*(\d+))?", re.I)
RE_ABROGATO = re.compile(r"\babrogat[oiae]\b", re.I)
# Il riferimento apre con "articolo"/"art." e puo' proseguire in elenco:
# "gli articoli 337-bis e 337-ter" nomina due articoli, ma la parola compare
# una volta sola.
RE_RIFERIMENTO = re.compile(
    r"\bart(?:t?\.|icol[oi])\s*(\d+(?:[\s-](?:" + ORDINALI + r"))?)"
    r"((?:\s*(?:,|e|ed)\s*\d+(?:[\s-](?:" + ORDINALI + r"))?)*)", re.I)
RE_SEGUITO = re.compile(r"\d+(?:[\s-](?:" + ORDINALI + r"))?", re.I)
# Un punto o un comma nominato accanto all'articolo restringe l'abrogazione a
# quel frammento: "l'articolo 90, comma 1, punto 4) e' abrogato" non abroga
# l'articolo 90.
RE_FRAMMENTO = re.compile(r"\b(?:comma|punto|numero|n\.|lettera)\b", re.I)


def spezza_note(righe_note, quante):
    """Il flusso delle note in un dizionario numero -> testo.

    Il numero apre la riga; oltre l'ultimo richiamo del corpo ogni cifra a
    inizio riga e' un falso positivo, per questo si passa 'quante'.
    """
    inizi, atteso = [], 1
    for i, r in enumerate(righe_note):
        m = re.match(r"^(\d{1,3}) (\S.*)", r)
        if m and int(m.group(1)) == atteso and atteso <= quante:
            inizi.append((i, atteso))
            atteso += 1
    fuori = {}
    for k, (i, n) in enumerate(inizi):
        if k + 1 < len(inizi):
            fine = inizi[k + 1][0]
        else:
            # L'ultima nota del Codice non finisce col Codice: dopo di essa il
            # PDF prosegue con l'appendice, che ha note proprie e riparte da
            # capo a numerare. Senza questo taglio la nota 191 se le prendeva
            # tutte, e all'art. 409 finivano attribuite quarantacinque
            # modifiche che riguardavano altri atti.
            fine = next((j for j in range(i + 1, len(righe_note))
                         if re.match(r"^\d{1,3} \S", righe_note[j])), len(righe_note))
        blocco = " ".join(x.strip() for x in righe_note[i:fine])
        fuori[n] = re.sub(r"\s+", " ", blocco).strip()
    return fuori


def modifiche(nota):
    """Gli atti elencati sotto 'Modifiche legislative', in ordine di data."""
    parti = re.split(r"Modifiche legislative", nota, maxsplit=1, flags=re.I)
    if len(parti) < 2:
        return []
    coda = parti[1]
    trovate = list(RE_MODIFICA.finditer(coda))
    # Il testo di una modifica arriva fino all'intestazione della successiva.
    # Con una finestra a lunghezza fissa sconfinava, e l'abrogazione dichiarata
    # da un atto finiva attribuita anche ai due che lo precedono nell'elenco.
    return [{"tipo": re.sub(r"\s+", " ", m.group("tipo")).strip(),
             "anno": int(m.group("anno") or m.group("anno2")),
             "numero": int(m.group("numero") or m.group("numero2")),
             "articolo": m.group("articolo"), "comma": m.group("comma"),
             "testo": coda[m.end():(trovate[i + 1].start()
                                    if i + 1 < len(trovate) else len(coda))].strip()}
            for i, m in enumerate(trovate)]


def origine(nota):
    """L'atto che ha introdotto l'articolo, per quelli nati dopo il 1974."""
    m = RE_ORIGINE.search(nota)
    if not m:
        return None
    return {"tipo": re.sub(r"\s+", " ", m.group(1)).strip(),
            "numero": int(m.group(2)), "anno": int(m.group(3)),
            "articolo": m.group(4)}


def id_atto(m):
    return norma_id(m["tipo"], m["numero"], m["anno"])


def leggi(pdf):
    corpo, righe_note = righe_pdf(pdf)
    articoli = rifinisci(estrai_articoli(solo_codice(corpo)))
    quante = max((n for a in articoli for n in a["note"]), default=0)
    note = spezza_note(righe_note, quante)
    for a in articoli:
        a["modifiche"], a["origine"] = [], None
        for n in a["note"]:
            testo = note.get(n, "")
            a["modifiche"] += modifiche(testo)
            a["origine"] = a["origine"] or origine(testo)
    aggiornato = None
    for testo, _, _ in corpo[:400]:
        m = RE_AGGIORNATO.search(testo)
        if m:
            aggiornato = m.group(1).strip()
            break
    return articoli, note, aggiornato


def abroganti(articolo):
    """Chi ha abrogato l'articolo, fra gli atti elencati nella sua nota.

    Non basta prendere l'ultimo della lista: la nota elenca tutte le
    modifiche, e quella che abroga si riconosce dal proprio testo. La formula
    non e' una sola - "e' abrogato l'articolo 8", "l'articolo 268 e'
    abrogato", "gli articoli 337-bis e 337-ter sono abrogati", "sono abrogate
    le seguenti normative: - Articolo 322" - e nemmeno l'ordine lo e'. Si
    lavora percio' per vicinanza: fra il riferimento all'articolo e la parola
    'abrogato', in un verso o nell'altro, non devono correre piu' di due righe
    e non deve comparire un comma o un punto, che restringerebbero
    l'abrogazione a un frammento ("l'articolo 90, comma 1, punto 4) e'
    abrogato" non abroga l'articolo 90).

    Dove il testo non lo dice, l'articolo resta marcato senza fonte: il grafo
    ammette abrogataDa vuoto, e attribuire l'atto sbagliato - la Legge che
    aveva riscritto l'articolo, non quella che poi l'ha soppresso - sarebbe
    peggio che tacerlo.
    """
    mio = chiave(articolo["numero"])
    fuori = []
    for m in articolo["modifiche"]:
        for inizio, fine in _riferimenti(m["testo"], mio):
            for a in RE_ABROGATO.finditer(m["testo"]):
                if a.start() > fine:
                    fra = m["testo"][fine:a.start()]
                elif a.end() < inizio:
                    fra = m["testo"][a.end():inizio]
                else:
                    continue
                if len(fra) <= DISTANZA_ABROGAZIONE and not RE_FRAMMENTO.search(fra):
                    fuori.append(id_atto(m))
                    break
    return sorted(set(fuori))


DISTANZA_ABROGAZIONE = 160


def _riferimenti(testo, numero):
    """Dove il testo nomina proprio quell'articolo, estremi compresi."""
    fuori = []
    for m in RE_RIFERIMENTO.finditer(testo):
        if chiave(m.group(1)) == numero:
            fuori.append((m.start(), m.start(1) + len(m.group(1))))
        for s in RE_SEGUITO.finditer(m.group(2) or ""):
            if chiave(s.group(0)) == numero:
                base = m.start(2)
                fuori.append((base + s.start(), base + s.end()))
    return fuori


# ------------------------------------------------------------------- scrittura

Q_ARTICOLI = """
UNWIND $articoli AS a
MATCH (n:Norma {id: $norma})
MERGE (art:Articolo {id: a.id})
  ON CREATE SET art.ordine = a.ordine
// Il testo del 1974 si conserva alla prima sovrascrittura e non si tocca piu':
// rieseguire lo script non deve far diventare "originario" il coordinato. Il
// confronto con a.testo non e' superfluo - gli articoli inseriti dopo il 1974
// un originario non ce l'hanno, e alla seconda esecuzione si sarebbero visti
// attribuire come tale il proprio testo vigente.
SET art.testoOriginario = CASE
      WHEN art.testoOriginario IS NOT NULL AND art.testoOriginario <> a.testo
        THEN art.testoOriginario
      WHEN art.testo IS NOT NULL AND art.testo <> a.testo THEN art.testo
      ELSE null END,
    art.testo = a.testo,
    art.numero = a.numero,
    art.rubrica = a.rubrica,
    art.ordine = a.ordine,
    art.fonteTesto = $fonte,
    art.testoAggiornatoAl = $aggiornato
MERGE (n)-[:HA_ARTICOLO]->(art)
"""

# I commi vecchi si cancellano: erano uno solo per articolo, implicito, con
# dentro tutto il testo del 1974. Tenerli accanto ai nuovi significherebbe
# avere la stessa disposizione due volte nell'indice vettoriale, in due
# versioni diverse, senza modo di dire quale sia quella vigente.
Q_PULISCI_COMMI = """
UNWIND $articoli AS a
MATCH (:Articolo {id: a.id})-[:HA_COMMA]->(c:Comma)
WHERE NOT c.id IN a.commiId
DETACH DELETE c
"""

Q_COMMI = """
UNWIND $commi AS c
MATCH (art:Articolo {id: c.articoloId})
MERGE (cm:Comma {id: c.id})
SET cm.numero = c.numero, cm.ordine = c.ordine,
    cm.commaImplicito = false, cm.numerazioneAnomala = false,
    // L'embedding va buttato quando il testo cambia, altrimenti la ricerca
    // semantica continua a rispondere con il vettore del testo di prima.
    cm.embedding = CASE WHEN cm.testo = c.testo THEN cm.embedding ELSE null END,
    cm.testo = c.testo
MERGE (art)-[:HA_COMMA]->(cm)
"""

# La novella si aggancia al comma dell'atto modificante che nomina davvero
# l'articolo bersaglio: _novelle() mostra all'agente il TESTO di quel comma,
# e agganciare l'articolo intero gliene farebbe leggere uno a caso.
Q_NOVELLE = """
UNWIND $novelle AS x
MATCH (:Norma {id: x.atto})-[:HA_ARTICOLO]->(a:Articolo {numero: x.articolo})
MATCH (a)-[:HA_COMMA]->(c:Comma)
MATCH (bersaglio:Articolo {id: x.bersaglio})
WITH c, bersaglio, x,
     c.testo =~ ('(?is).*articol[oi]\\\\s+' + x.numeroBersaglio + '\\\\b.*') AS nomina
WITH bersaglio, x, collect({c: c, nomina: nomina}) AS commi
WITH bersaglio, [y IN commi WHERE y.nomina] AS scelti, commi
UNWIND (CASE WHEN size(scelti) > 0 THEN scelti ELSE commi END) AS y
WITH bersaglio, y.c AS c
MERGE (c)-[r:CITA_ARTICOLO]->(bersaglio)
SET r.origine = $origine
"""

# Gli archi di novella si azzerano e si riscrivono, come fa 08 con le
# marcature: senza, un'espressione che smette di riconoscere una modifica
# lascerebbe nel grafo l'arco della volta prima. Si cancellano i soli archi
# marcati da questo script, cosi' quelli che il parser ricava dal testo degli
# atti restano dove sono.
Q_PULISCI_NOVELLE = """
MATCH (:Norma {id: $norma})-[:HA_ARTICOLO]->(a:Articolo)
MATCH ()-[r:CITA_ARTICOLO {origine: $origine}]->(a)
DELETE r
"""


def grafo():
    load_dotenv(RADICE / ".env")
    return Neo4jGraph(url=os.environ["NEO4J_URI"],
                      username=os.environ["NEO4J_USERNAME"],
                      password=os.environ["NEO4J_PASSWORD"],
                      database=os.getenv("NEO4J_DATABASE", "neo4j"),
                      refresh_schema=False)


def chiave(numero):
    return re.sub(r"[\s.]", "", str(numero or "")).lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", default=str(PDF_DEFAULT))
    ap.add_argument("--scrivi", action="store_true")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        sys.exit(f"PDF non trovato: {pdf}")

    articoli, note, aggiornato = leggi(pdf)
    for i, a in enumerate(articoli, 1):
        a["id"] = f"{NORMA}/art-{a['numero']}"
        a["ordine"] = i
    print(f"\n  {pdf.name} - {FONTE}, aggiornato al {aggiornato}")
    print(f"  articoli {len(articoli)} | con rubrica "
          f"{sum(bool(a['rubrica']) for a in articoli)} | abrogati "
          f"{sum(a['abrogato'] for a in articoli)}")
    print(f"  commi {sum(len(a['commi']) for a in articoli)} "
          f"(nel grafo il Codice ne aveva uno per articolo, implicito)")
    print(f"  note lette {len(note)} | modifiche legislative "
          f"{sum(len(a['modifiche']) for a in articoli)}")

    g = grafo()
    presenti = {chiave(r["n"]): r for r in g.query(
        "MATCH (:Norma {id: $n})-[:HA_ARTICOLO]->(a:Articolo) "
        "RETURN a.numero AS n, a.id AS id", {"n": NORMA})}
    nuovi = [a for a in articoli if chiave(a["numero"]) not in presenti]
    print(f"\n  gia' nel grafo {len(presenti)} | nel coordinato "
          f"{len(articoli)} | da creare {len(nuovi)}")
    if nuovi:
        print("   " + ", ".join(a["numero"] for a in nuovi))

    # Gli atti modificanti si risolvono sugli id del grafo: quelli assenti
    # sono citazioni che non si possono agganciare, e vanno detti.
    atti = {}
    for a in articoli:
        for m in a["modifiche"]:
            atti.setdefault(id_atto(m), []).append((a, m))
    noti = {r["id"] for r in g.query(
        "UNWIND $ids AS id MATCH (n:Norma {id: id}) RETURN n.id AS id",
        {"ids": sorted(atti)})}
    print(f"\n  atti modificanti citati {len(atti)} | presenti nel grafo "
          f"{len(noti)} | assenti {len(atti) - len(noti)}")
    assenti = sorted(set(atti) - noti)
    if assenti:
        print("   assenti: " + ", ".join(assenti))

    evidenze = [{"articolo": a["numero"], "articoloId": a["id"],
                 "fonti": abroganti(a)}
                for a in articoli if a["abrogato"]]
    senza = [e["articolo"] for e in evidenze if not e["fonti"]]
    print(f"\n  articoli marcati [ABROGATO] {len(evidenze)} | con l'atto "
          f"abrogante riconosciuto {len(evidenze) - len(senza)}")
    for e in evidenze:
        print(f"   art. {e['articolo']:<10} {', '.join(e['fonti']) or '(fonte non dichiarata)'}")

    if not args.scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi per applicare al grafo.")
        return

    lotti = [articoli[i:i + 200] for i in range(0, len(articoli), 200)]
    for lotto in lotti:
        for a in lotto:
            a["commiId"] = [f"{a['id']}/c-{k}" for k in range(1, len(a["commi"]) + 1)]
        g.query(Q_ARTICOLI, {"norma": NORMA, "fonte": FONTE,
                             "aggiornato": aggiornato,
                             "articoli": [{k: a[k] for k in
                                           ("id", "numero", "rubrica", "testo", "ordine")}
                                          for a in lotto]})
        g.query(Q_PULISCI_COMMI, {"articoli": [{"id": a["id"], "commiId": a["commiId"]}
                                               for a in lotto]})
        g.query(Q_COMMI, {"commi": [
            {"articoloId": a["id"], "id": cid, "numero": str(k), "ordine": k,
             "testo": testo}
            for a in lotto
            for k, (cid, testo) in enumerate(zip(a["commiId"], a["commi"]), 1)]})
    print(f"\n  scritti {len(articoli)} articoli e "
          f"{sum(len(a['commi']) for a in articoli)} commi")

    novelle = [{"atto": aid, "articolo": m["articolo"], "bersaglio": a["id"],
                "numeroBersaglio": re.match(r"\d+", a["numero"]).group(0)}
               for aid, coppie in atti.items() if aid in noti
               for a, m in coppie if m["articolo"]]
    prima = g.query("MATCH ()-[r:CITA_ARTICOLO]->(:Articolo) "
                    "WHERE r IS NOT NULL RETURN count(r) AS n")[0]["n"]
    g.query(Q_PULISCI_NOVELLE, {"norma": NORMA, "origine": FONTE})
    for i in range(0, len(novelle), 200):
        g.query(Q_NOVELLE, {"novelle": novelle[i:i + 200], "origine": FONTE})
    dopo = g.query("MATCH ()-[r:CITA_ARTICOLO]->(:Articolo) "
                   "WHERE r IS NOT NULL RETURN count(r) AS n")[0]["n"]
    print(f"  novelle agganciabili {len(novelle)} | archi CITA_ARTICOLO "
          f"{prima:,} -> {dopo:,} (+{dopo - prima:,})")

    EVIDENZE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENZE.write_text(json.dumps(
        {"norma": NORMA, "fonte": FONTE, "aggiornatoAl": aggiornato,
         "articoli": evidenze}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  evidenze di abrogazione in {EVIDENZE.relative_to(RADICE)}"
          f" ({len(evidenze)} articoli)")
    print("\n  Ora: 08_abrogazioni.py --scrivi (marca gli abrogati),"
          " poi 07_embeddings.py (i commi nuovi non hanno vettore).")


if __name__ == "__main__":
    main()
