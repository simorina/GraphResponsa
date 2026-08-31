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
RE_ARTICOLO = re.compile(r"^Art\.\s*(\d+)\s*(bis|ter|quater|quinquies)?\s*$", re.I)
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
RE_BERSAGLIO = re.compile(
    r"(?:articolo|art\.?)\s*(\d+)(?:\s*,?\s*commi?\s*(\d+))?\s*"
    r"(?:,\s*(?:lettera|lett\.?)\s*\w\)\s*)?"
    r"(?:del(?:la)?|di)?\s*$",
    re.I,
)



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


def parse(id_norma, meta):
    righe = righe_pdf(RAW / id_norma / "testo.pdf")

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
            i += 1
            continue

        # --- Rubrica dell'articolo: fra parentesi, puo' proseguire su piu' righe ---
        if attesa_rubrica:
            if riga.startswith("(") or rubrica_buffer:
                rubrica_buffer.append(riga)
                if riga.endswith(")"):
                    testo = unisci(rubrica_buffer)
                    articolo_corrente["rubrica"] = testo.strip("()").strip()
                    attesa_rubrica = False
                    rubrica_buffer = []
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
    }


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def main(force=False):
    PARSED.mkdir(parents=True, exist_ok=True)
    cartelle = sorted(p for p in RAW.iterdir() if p.is_dir())
    if not cartelle:
        raise RuntimeError("data/raw/ e' vuota: eseguire prima 01_scrape.py")

    da_parsare = []
    for c in cartelle:
        if not (c / "scheda.json").exists() or not (c / "testo.pdf").exists():
            continue
        if not force and (PARSED / f"{c.name}.json").exists():
            continue
        da_parsare.append(c)

    print(f"File totali su disco: {len(cartelle)}. Nuovi da parsare: {len(da_parsare)}.")
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
    main(force="--force" in sys.argv)
