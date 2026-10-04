"""
21 - Parsing delle Linee Guida e dei Protocolli operativi del Tribunale.

Le fonti non sono atti dell'archivio del Consiglio Grande e Generale ma i PDF
del sito del Tribunale (scripts/scarica_linee_guida.py), e il riconoscitore di
02_parse.py non si puo' riusare per tre ragioni:

  - 17 PDF su 20 sono scansioni senza testo. Il testo viene dalle trascrizioni
    in data/linee-guida/trascrizioni/<file>.md, fatte pagina per pagina; anche
    i tre PDF con testo nativo sono stati portati in Markdown, cosi' il parser
    legge una forma sola;
  - la struttura non e' "Art. N / comma": sezioni A), B)..., punti 1), 2)...,
    lettere e numeri romani annidati, note esplicative con note a pie' di
    pagina. Gli "Art." ci sono solo nei protocolli e nel regolamento;
  - le norme si citano "legge n. 154 del 2021", "d.del. n. 102/2024", "legge
    93/08": forme che RE_CITAZIONE non legge. Si normalizzano prima di
    passargliele, e il testo dei commi resta quello trascritto.

Convenzioni delle trascrizioni:

    <!-- pagina N -->        comincia la pagina N del PDF
    # Titolo                 intestazione del documento; cio' che la precede
                             (protocollo, destinatari) va nel preambolo
    ## Sezione               una sezione con sottosezioni "###" e' una
    ### Sottosezione         partizione e le sottosezioni i suoi articoli;
                             una sezione senza sottosezioni e' un articolo
    [Titolo]                 fra parentesi quadre: aggiunto in trascrizione
    una riga, un blocco      paragrafo o voce d'elenco; 4 spazi per livello di
                             rientro (le lettere dentro un punto)
    [^n] e [^n]: testo       rimando e nota a pie' di pagina
    | a | b |                riga di tabella
    ---                      fine del testo: seguono data e firme

Il preambolo arriva fino alla formula con cui il Dirigente adotta il testo
("adotta le seguenti Linee Guida", "si concorda quanto segue"), se ce n'e' una
prima della prima sezione; il testo tra il titolo e la prima sezione, se non e'
preambolo, e' l'articolo "premessa" (o "unico", se sezioni non ce ne sono).

Output: data/linee-guida/parsed/<id>.json, nella forma di 02_parse.py, con in
piu' protocollo, intestazione, chiusura e la pagina di commi e articoli:

  - id LG-<protocollo>-<anno>: "Prot. n. 588/D/2025" -> LG-588-2025. Senza
    protocollo, le prime tre parole del nome del file e numero null:
    LG-procedimento-esecutivo-2022;
  - numero dell'articolo: la sigla della sezione ("A", "1", "3" per "Art. 3"),
    o il suo titolo ridotto a slug ("note-esplicative");
  - commi: le voci col loro numero ("3", "B"), i paragrafi senza numero in
    ordine, saltando i numeri gia' presi (commaImplicito); le voci rientrate
    sono punti del comma che le contiene ("3.b", "3.b.ii", parte "punto"), e
    le note a pie' di pagina seguono il comma che le richiama ("nota4", parte
    "nota").

Non tocca la rete ne' il grafo.

Uso:
    .venv/Scripts/python.exe src/21_linee_guida.py
    .venv/Scripts/python.exe src/21_linee_guida.py --mostra LG-588-2025
"""

import argparse
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from comune import norma_id  # noqa: E402


def _modulo(nome, file):
    spec = importlib.util.spec_from_file_location(nome, RADICE / "src" / file)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# Le citazioni si estraggono con le espressioni del parser: se divergessero, la
# stessa legge citata da un atto e da una linea guida finirebbe sotto id diversi.
parser = _modulo("parse02", "02_parse.py")

CARTELLA = RADICE / "data" / "linee-guida"
TRASCRIZIONI = CARTELLA / "trascrizioni"
MANIFESTO = CARTELLA / "manifesto.json"
PARSED = CARTELLA / "parsed"
PAGINA_SITO = "https://www.tribunale.sm/pub1/TribunaleSM/il-tribunale/Linee-Guida-e-Protocolli-Operativi.html"
TIPO = "Linee Guida"

MESI = "gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre"
RE_DATA_ESTESA = re.compile(r"\b(\d{1,2})\s*[°º]?\s+(" + MESI + r")\s+(\d{4})\b", re.I)
RE_ENTRATA_VIGORE = re.compile(r"entra\s+in\s+vigore\s+in\s+data\s+" + RE_DATA_ESTESA.pattern, re.I)
RE_PROTOCOLLO = re.compile(r"\bprot\.?\s*n\.?\s*(\d+)\s*/\s*D\s*/\s*(\d{2,4})\b", re.I)

RE_PAGINA = re.compile(r"^<!--\s*pagina\s+(\d+)\s*-->$")
RE_TITOLO = re.compile(r"^(#{1,3})\s+(.*)$")
RE_NOTA = re.compile(r"^\[\^(\d+)\]:\s*(.*)$")
RE_RIMANDO = re.compile(r"\s*\[\^(\d+)\]")
# "3)", "3.", "(1)", "B)", "b.", "iv)". Le maiuscole solo con la parentesi:
# "A. " a inizio riga non compare come voce, "L. 24 giugno..." si'.
RE_VOCE = re.compile(r"^(?:\((\d{1,2})\)|(\d{1,2})[).]|([A-Z])\)|([a-z])[).]|([ivx]{2,5})[).])\s+(?=\S)")
RE_TRATTINO = re.compile(r"^[-•]\s+")
RE_ART = re.compile(r"^(?:Art\.?|Articolo)\s*(\d+)\s*[.:]?\s*(.*)$", re.I)
RE_SIGLA = re.compile(r"^(?:([A-Z]|\d{1,2}|[a-z])[).]|([IVX]{1,4})\s)\s*(.*)$")
# La formula che chiude il preambolo. Si cerca solo prima della prima sezione e
# della prima voce numerata: piu' avanti "adotta" e' il verbo di una regola.
RE_FORMULA = re.compile(r"\b(?:adotta|sono\s+adottate|si\s+concorda\s+quanto\s+segue"
                        r"|sono\s+richiesti\s+di\s+attenersi)\b", re.I)


def _anno_esteso(m):
    anno = m.group(3)
    return f"{m.group(1)} n. {m.group(2)}/{'20' if int(anno) <= 30 else '19'}{anno}"


NORMALIZZA = [
    (re.compile(r"\bd\.\s?del\.", re.I), "Decreto Delegato"),
    (re.compile(r"\bl\.\s?cost\.", re.I), "Legge Costituzionale"),
    # "n. 154 del 2021", "n.97 del 20 giugno 2008" -> "n. 154/2021"
    (re.compile(r"\bn\.\s*(\d+)\s*,?\s+del(?:l['’])?\s+(?:\d{1,2}\s*[°º]?\s+(?:" + MESI
                + r")\s+)?(\d{4})\b", re.I), r"n. \1/\2"),
    # "legge 1999 n. 83" -> "legge n. 83/1999"
    (re.compile(r"\b(legge|decreto)\s+(\d{4})\s+n\.\s*(\d+)", re.I), r"\1 n. \3/\2"),
    # "legge 93/08": l'anno a due cifre
    (re.compile(r"\b(legge|l\.)\s*(?:n\.\s*)?(\d{1,4})\s*/\s*(\d{2})\b(?![\d/])", re.I), _anno_esteso),
]


def normalizza(testo):
    """Il testo riscritto nelle forme che RE_CITAZIONE sa leggere."""
    for espressione, sostituzione in NORMALIZZA:
        testo = espressione.sub(sostituzione, testo)
    return testo


def citazioni(testo, nid, preambolo=False):
    return parser.estrai_citazioni(normalizza(testo), nid, preambolo=preambolo)


# Le prove girano all'import, come in 02_parse.py: una normalizzazione sbagliata
# non da' errori, aggancia la linea guida alla legge sbagliata.
for _testo, _atteso in [
    ("ai sensi dell'art. 7 della legge n. 154 del 2021", [("Legge", 154, 2021, "7")]),
    ("secondo l'art. 4, comma 2 d.del. n. 102/2024", [("Decreto Delegato", 102, 2024, None)]),
    ("dell'art. 1 della l. cost. n. 2/2020", [("Legge Costituzionale", 2, 2020, "1")]),
    ("all'art.3 della legge 93/08, al fine", [("Legge", 93, 2008, "3")]),
    ("La legge n.97 del 20 giugno 2008 e succ. mod.", [("Legge", 97, 2008, None)]),
    ("si applica l'art. 5 della legge 1999 n. 83, e cioè", [("Legge", 83, 1999, "5")]),
    ("art. 40 L. 24 giugno 2022, n. 94", [("Legge", 94, 2022, None)]),
    ("nella causa civile n. 227 del 2011, inedita", []),
    ("Prot. n. 35/RB/24 del 7 giugno", []),
]:
    _letto = [(c["tipo"], c["numero"], c["anno"], c["articoloCitato"])
              for c in citazioni(_testo, "LG-1-1900")]
    assert _letto == _atteso, f"citazioni: {_testo!r} -> {_letto}"


def data_iso(testo):
    m = RE_DATA_ESTESA.search(testo or "")
    if not m:
        return None
    mese = MESI.split("|").index(m.group(2).lower()) + 1
    return f"{int(m.group(3)):04d}-{mese:02d}-{int(m.group(1)):02d}"


def slug(testo):
    t = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode().lower()
    return "-".join(re.findall(r"[a-z0-9]+", t)[:6]) or "sezione"


def sigla_e_rubrica(titolo):
    """"B) Formalità per ..." -> ("B", "Formalità per ..."); "Art. 3" -> ("3", None);
    "NOTE ESPLICATIVE" -> ("note-esplicative", "NOTE ESPLICATIVE")."""
    titolo = RE_RIMANDO.sub("", titolo).strip().strip("[]").strip()
    if (m := RE_ART.match(titolo)):
        return m.group(1), (m.group(2).strip(" .:") or None)
    if (m := RE_SIGLA.match(titolo)):
        return (m.group(1) or m.group(2)), (m.group(3).strip(" .:") or None)
    return slug(titolo), titolo.strip(" .:")


assert sigla_e_rubrica("B) Formalità per l'attivazione") == ("B", "Formalità per l'attivazione")
assert sigla_e_rubrica("Art.1") == ("1", None)
assert sigla_e_rubrica("1.") == ("1", None)
assert sigla_e_rubrica("I GRIGLIA PER LA COMPILAZIONE") == ("I", "GRIGLIA PER LA COMPILAZIONE")
assert sigla_e_rubrica("[Linee guida]") == ("linee-guida", "Linee guida")


def voce(testo):
    """(sigla, testo senza sigla): "3) Il Giudice..." -> ("3", "Il Giudice...").
    Il trattino e' una voce senza sigla; un paragrafo non e' una voce."""
    if (m := RE_VOCE.match(testo)):
        return next(g for g in m.groups() if g), testo[m.end():]
    if (m := RE_TRATTINO.match(testo)):
        return "", testo[m.end():]
    return None, testo


def leggi(md):
    """Il Markdown come lista di elementi, ciascuno col numero di pagina."""
    elementi, pagina, tabella = [], 1, None
    for riga in md.splitlines():
        pulita = riga.strip()
        if pulita.startswith("|"):
            celle = [c.strip() for c in pulita.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in celle):
                continue
            if tabella is None:
                tabella = {"tipo": "tabella", "righe": [], "pagina": pagina, "livello": 0}
                elementi.append(tabella)
            tabella["righe"].append(celle)
            continue
        tabella = None
        if not pulita:
            continue
        if (m := RE_PAGINA.match(pulita)):
            pagina = int(m.group(1))
        elif pulita.startswith("<!--"):
            continue
        elif pulita == "---":
            elementi.append({"tipo": "fine"})
        elif (m := RE_TITOLO.match(riga)):
            elementi.append({"tipo": "titolo", "livello": len(m.group(1)),
                             "testo": m.group(2).strip(), "pagina": pagina})
        elif (m := RE_NOTA.match(pulita)):
            elementi.append({"tipo": "nota", "numero": m.group(1),
                             "testo": m.group(2).strip(), "pagina": pagina})
        else:
            rientro = len(riga) - len(riga.lstrip(" "))
            elementi.append({"tipo": "blocco", "livello": rientro // 4,
                             "testo": pulita, "pagina": pagina})
    return elementi


def testo_di(elemento):
    if elemento["tipo"] == "tabella":
        return "; ".join(" | ".join(c for c in riga if c) for riga in elemento["righe"])
    return elemento["testo"]


def commi_di(art, elementi, note, nid):
    """I commi di un articolo, dai suoi blocchi. Restituisce le note usate."""
    # Prima l'albero: ogni blocco rientrato appartiene all'ultimo blocco di
    # livello inferiore.
    radici, pila = [], []
    for e in elementi:
        sigla, testo = voce(testo_di(e)) if e["tipo"] == "blocco" else (None, testo_di(e))
        nodo = {"sigla": sigla, "testo": testo, "pagina": e["pagina"], "figli": []}
        livello = e.get("livello", 0)
        while pila and pila[-1][0] >= livello:
            pila.pop()
        (pila[-1][1]["figli"] if pila else radici).append(nodo)
        pila.append((livello if pila or livello == 0 else 0, nodo))

    # Un elenco introdotto da un paragrafo che finisce coi due punti e' fatto
    # di punti di quel paragrafo, come in commi.py: "si ritiene opportuno: (1)
    # ... (2) ...". Senza, i due elenchi 1)-4) e 1)-2) della delibazione, uno
    # dopo l'altro nella stessa sezione, davano commi doppi.
    # L'elenco finisce al primo paragrafo o alla prima voce di altro tipo: dopo
    # "Pertanto:" e i suoi trattini, "B) Per l'adozione..." e' la voce che segue
    # la A), non un altro trattino.
    def tipo_voce(sigla):
        if sigla == "":
            return "trattino"
        return "numero" if sigla.isdigit() else ("maiuscola" if sigla.isupper() else "minuscola")

    annidate, introduzione, tipo_elenco = [], None, None
    for n in radici:
        if n["sigla"] is not None and introduzione is not None \
                and tipo_voce(n["sigla"]) == (tipo_elenco or tipo_voce(n["sigla"])):
            tipo_elenco = tipo_voce(n["sigla"])
            introduzione["figli"].append(n)
            continue
        annidate.append(n)
        introduzione = n if (n["sigla"] is None and not n["figli"]
                             and n["testo"].rstrip().endswith(":")) else None
        tipo_elenco = None
    radici = annidate

    # Poi i numeri: le voci tengono la loro sigla, i paragrafi prendono il
    # primo numero libero, i punti quello del padre piu' il proprio.
    prese = {n["sigla"] for n in radici if n["sigla"]}
    libero = 1
    for n in radici:
        if not n["sigla"]:
            while str(libero) in prese:
                libero += 1
            n["numero"], n["implicito"] = str(libero), True
            libero += 1
        else:
            n["numero"], n["implicito"] = n["sigla"], False

    commi, usate, ids = [], [], set()

    def aggiungi(numero, testo, pagina, implicito, parte=None, originale=None):
        base = f"{art['id']}/c-{numero.replace('.', '-')}"
        cid, k = base, 1
        while cid in ids:
            k += 1
            cid = f"{base}-{k}"
        ids.add(cid)
        comma = {"id": cid, "numero": numero, "testo": testo,
                 "numerazioneAnomala": cid != base, "commaImplicito": implicito,
                 "pagina": pagina}
        if parte:
            comma.update(parte=parte, numeroOriginale=originale)
        commi.append(comma)

    def visita(nodo, numero, parte=None):
        rimandi = RE_RIMANDO.findall(nodo["testo"])
        testo = re.sub(r"\s+([.,;:])", r"\1", RE_RIMANDO.sub("", nodo["testo"])).strip()
        aggiungi(numero, testo, nodo["pagina"], nodo.get("implicito", False),
                 parte, nodo["sigla"] or None)
        senza_sigla = 0
        for figlio in nodo["figli"]:
            if figlio["sigla"]:
                sigla = figlio["sigla"]
            else:
                senza_sigla += 1
                sigla = f"p{senza_sigla}"
            visita(figlio, f"{numero}.{sigla}", "punto")
        for r in rimandi:
            if r in note:
                aggiungi(f"nota{r}", note[r]["testo"], note[r]["pagina"], False, "nota", r)
                usate.append(r)
            else:
                print(f"    ! {nid} {art['id']}: rimando alla nota {r}, che non c'e'")

    for n in radici:
        visita(n, n["numero"])
    art["commi"] = commi
    art["citazioni"] = []
    for c in commi:
        for cit in citazioni(c["testo"], nid):
            cit["commaId"] = c["id"]
            cit["commaOrigine"] = c["numero"]
            art["citazioni"].append(cit)
    return usate


def parse(md, voce_manifesto, stem):
    elementi = leggi(md)
    note = {e["numero"]: e for e in elementi if e["tipo"] == "nota"}
    elementi = [e for e in elementi if e["tipo"] != "nota"]

    i_h1 = next(k for k, e in enumerate(elementi) if e["tipo"] == "titolo" and e["livello"] == 1)
    fine = next((k for k, e in enumerate(elementi) if e["tipo"] == "fine"), len(elementi))
    testata = elementi[:i_h1]
    corpo = elementi[i_h1 + 1:fine]
    chiusura = [e for e in elementi[fine + 1:] if e["tipo"] != "fine"]

    # Il preambolo: fino alla formula, se c'e' prima della prima sezione o voce.
    preambolo = [e for e in testata]
    inizio = 0
    while inizio < len(corpo) and corpo[inizio]["tipo"] == "blocco" \
            and re.fullmatch(r"\(.*\)", corpo[inizio]["testo"]):
        inizio += 1                     # "(art. 40 Legge 24 giugno 2022, n. 94)"
    formula = None
    for k, e in enumerate(corpo[inizio:], inizio):
        if e["tipo"] != "blocco" or voce(e["testo"])[0]:
            break
        if RE_FORMULA.search(e["testo"]):
            formula = k
    fine_preambolo = formula + 1 if formula is not None else inizio
    preambolo += corpo[:fine_preambolo]
    corpo = corpo[fine_preambolo:]

    # Estremi.
    testo_testata = " ".join(testo_di(e) for e in testata if e["tipo"] != "titolo")
    testo_chiusura = " ".join(testo_di(e) for e in chiusura)
    m_prot = RE_PROTOCOLLO.search(testo_testata)
    data = data_iso(testo_chiusura) or data_iso(testo_testata) or voce_manifesto["data"]
    anno = int(data[:4])
    if m_prot:
        numero = int(m_prot.group(1))
        anno_prot = int(m_prot.group(2))
        anno = anno_prot + 2000 if anno_prot < 100 else anno_prot
        nid = norma_id(TIPO, numero, anno)
        protocollo = f"{numero}/D/{anno}"
    else:
        numero, protocollo = None, None
        nid = f"LG-{'-'.join(stem.split('_', 1)[1].split('-')[:3])}-{anno}"
    testo_corpo = " ".join(testo_di(e) for e in corpo if e["tipo"] != "titolo")
    m_vigore = RE_ENTRATA_VIGORE.search(testo_corpo)

    # Sezioni: "##" con i suoi "###", o "###" da soli.
    sezioni, attuale, testa, ultima_sezione = [], None, [], None
    for e in corpo:
        if e["tipo"] == "titolo":
            attuale = {"titolo": e["testo"], "pagina": e["pagina"], "blocchi": [], "figli": []}
            if e["livello"] == 3 and ultima_sezione is not None:
                ultima_sezione["figli"].append(attuale)
            else:
                sezioni.append(attuale)
                if e["livello"] == 2:
                    ultima_sezione = attuale
        elif attuale is None:
            testa.append(e)
        else:
            attuale["blocchi"].append(e)

    partizioni, articoli, numeri, usate = [], [], set(), []

    def articolo(sigla, rubrica, blocchi, pagina, partizione=None, prefisso=None):
        numero_art = sigla
        if numero_art in numeri and prefisso:
            numero_art = f"{prefisso}.{sigla}"
        k = 1
        while numero_art in numeri:
            k += 1
            numero_art = f"{sigla}-{k}"
        numeri.add(numero_art)
        # "Art. 1 / AMBITO DI APPLICAZIONE", "Art.1 / (Trasmissione informazioni)"
        if rubrica is None and blocchi and blocchi[0]["tipo"] == "blocco":
            primo = blocchi[0]["testo"]
            if len(primo) <= 120 and (re.fullmatch(r"\(.*\)", primo)
                                      or (primo.upper() == primo and re.search(r"[A-Z]", primo))):
                rubrica, blocchi = primo.strip("()").strip(), blocchi[1:]
        art = {"id": f"{nid}/art-{re.sub(r'[^A-Za-z0-9.-]', '-', numero_art)}",
               "numero": numero_art, "rubrica": rubrica,
               "partizioneId": partizione["id"] if partizione else None,
               "ordine": len(articoli), "paginaDocumento": pagina, "commi": []}
        usate.extend(commi_di(art, blocchi, note, nid))
        if art["commi"]:
            articoli.append(art)
        else:
            numeri.discard(numero_art)

    if testa:
        articolo("premessa" if sezioni else "unico", None, testa, testa[0]["pagina"])
    for s in sezioni:
        sigla, rubrica = sigla_e_rubrica(s["titolo"])
        if not s["figli"]:
            articolo(sigla, rubrica, s["blocchi"], s["pagina"])
            continue
        partizione = {"id": f"{nid}/sez-{re.sub(r'[^A-Za-z0-9.-]', '-', sigla)}", "tipo": "Sezione",
                      "numero": sigla, "rubrica": rubrica, "ordine": len(partizioni), "figli": []}
        partizioni.append(partizione)
        if s["blocchi"]:
            articolo(sigla, rubrica, s["blocchi"], s["pagina"], partizione)
        for f in s["figli"]:
            sigla_f, rubrica_f = sigla_e_rubrica(f["titolo"])
            articolo(sigla_f, rubrica_f, f["blocchi"], f["pagina"], partizione, prefisso=sigla)

    orfane = sorted(set(note) - set(usate), key=int)
    if orfane:
        print(f"    ! {nid}: note mai richiamate: {', '.join(orfane)}")

    testo_preambolo = " ".join(RE_RIMANDO.sub("", testo_di(e)) for e in preambolo)
    testo_preambolo = re.sub(r"\s+", " ", testo_preambolo.replace("[", "").replace("]", "")).strip()
    intestazione = RE_RIMANDO.sub("", elementi[i_h1]["testo"]).strip("[] ")
    return {
        "id": nid,
        "tipo": TIPO,
        "numero": numero,
        "anno": anno,
        "data": data,
        "dataPubblicazione": voce_manifesto["data"],
        "dataEntrataVigore": data_iso(m_vigore.group(0)) if m_vigore else None,
        "titolo": voce_manifesto["titolo"],
        "protocollo": protocollo,
        "intestazione": intestazione,
        "urlScheda": PAGINA_SITO,
        "urlDocumento": voce_manifesto["url"],
        "nomeFileOriginale": voce_manifesto["nome_originale"],
        "allegati": [],
        "fileTrascrizione": f"trascrizioni/{stem}.md",
        "chiusura": testo_chiusura or None,
        "preambolo": testo_preambolo,
        "citazioniPreambolo": parser.estrai_citazioni(normalizza(testo_preambolo), nid, preambolo=True),
        "partizioni": partizioni,
        "articoli": articoli,
    }


def mostra(dati):
    print(f"{dati['id']}  {dati['titolo']}")
    print(f"  data {dati['data']}, pubblicata {dati['dataPubblicazione']}, protocollo {dati['protocollo']}")
    print(f"  preambolo: {dati['preambolo'][:300]}{'...' if len(dati['preambolo']) > 300 else ''}")
    for p in dati["partizioni"]:
        print(f"  [partizione {p['numero']}] {p['rubrica'] or ''}")
    for a in dati["articoli"]:
        print(f"  art. {a['numero']}  {a['rubrica'] or ''}  (p. {a['paginaDocumento']}"
              + (f", in {a['partizioneId'].rsplit('/', 1)[1]}" if a["partizioneId"] else "") + ")")
        for c in a["commi"]:
            segno = "~" if c["commaImplicito"] else ("!" if c["numerazioneAnomala"] else " ")
            print(f"      {segno}{c['numero']:<10} {c['testo'][:90]}")
        for cit in a["citazioni"]:
            print(f"      -> {cit['tipo']} {cit['numero']}/{cit['anno']}"
                  + (f" art. {cit['articoloCitato']}" if cit["articoloCitato"] else "")
                  + f"  (comma {cit['commaOrigine']})")
    print(f"  chiusura: {dati['chiusura']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mostra", metavar="ID", help="stampa la struttura di un documento")
    args = ap.parse_args()

    manifesto = json.loads(MANIFESTO.read_text(encoding="utf-8"))
    per_file = {v["file"][:-4]: v for v in manifesto.values()}
    trascrizioni = sorted(TRASCRIZIONI.glob("*.md"))

    senza = sorted(set(per_file) - {t.stem for t in trascrizioni})
    estranee = [t.stem for t in trascrizioni if t.stem not in per_file]
    if estranee:
        raise SystemExit(f"trascrizioni senza voce nel manifesto: {', '.join(estranee)}")

    risultati = [parse(t.read_text(encoding="utf-8"), per_file[t.stem], t.stem) for t in trascrizioni]
    ids = [d["id"] for d in risultati]
    doppi = {i for i in ids if ids.count(i) > 1}
    if doppi:
        raise SystemExit(f"id ripetuti: {', '.join(sorted(doppi))}")

    if args.mostra:
        dati = next((d for d in risultati if d["id"] == args.mostra), None)
        if dati is None:
            raise SystemExit(f"{args.mostra}: nessun documento con questo id ({', '.join(ids)})")
        mostra(dati)
        return

    PARSED.mkdir(parents=True, exist_ok=True)
    # La cartella e' solo di questo script: un id cambiato non deve lasciare
    # dietro di se' il file col nome vecchio.
    for vecchio in PARSED.glob("*.json"):
        if vecchio.stem not in ids:
            vecchio.unlink()
            print(f"  rimosso {vecchio.name}: nessuna trascrizione produce piu' questo id")
    print(f"  {'id':<42}{'art':>4}{'commi':>7}{'note':>6}{'cit':>5}")
    for d in risultati:
        commi = [c for a in d["articoli"] for c in a["commi"]]
        n_note = sum(1 for c in commi if c.get("parte") == "nota")
        n_cit = sum(len(a["citazioni"]) for a in d["articoli"]) + len(d["citazioniPreambolo"])
        print(f"  {d['id']:<42}{len(d['articoli']):>4}{len(commi):>7}{n_note:>6}{n_cit:>5}")
        (PARSED / f"{d['id']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    if senza:
        print(f"\n  PDF senza trascrizione, non parsati: {', '.join(senza)}")
    print(f"\n  {len(risultati)} documenti in {PARSED.relative_to(RADICE)}/")


if __name__ == "__main__":
    main()
