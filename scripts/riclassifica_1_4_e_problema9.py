"""
Riclassificazione del segnale "commi anomali" (impatto misurato per 1.4) e
misura indipendente del problema #9 ("Art N" senza punto), su tutto il
corpus, in streaming da S3. Sola lettura: nessun file locale del corpus,
nessuna modifica a 02_parse.py/06_qa.py, nessun tocco al grafo.

Riusa:
  - le regex del parser (RE_ARTICOLO, RE_PARTIZIONE) da 02_parse.py, per
    trovare i confini di articolo esattamente come li vede il parser vero;
  - l'elenco dei commi anomali gia' calcolato dalla baseline precedente
    (data/qa_report_baseline_2026-09-15.jsonl, campo "commi_lunghi"), cosi'
    non si ricalcola da zero cio' che 06_qa.py ha gia' misurato.

Per ogni documento con almeno un comma anomalo, isola il blocco di righe
grezze "inghiottite" nell'articolo che lo contiene (dalla riga "Art. N" di
apertura alla riga immediatamente prima del prossimo Art./TITOLO/CAPO/
SEZIONE riconosciuto, o fine file) e applica il discriminante:

  a. c'e' la formula di promulgazione ("Dato/Data dalla Nostra Residenza
     ... CAPITANI REGGENTI")? -> CAUSA-A, allegato post-promulgazione
     genuino: tutto cio' che segue la formula non e' dispositivo legislativo.
  b. altrimenti, ci sono almeno 2 intestazioni "Art[.] N" (con o senza
     punto) a inizio riga, con numerazione progressiva crescente, dentro il
     blocco? -> CAUSA-B, vero collasso (bug 1.4): sono articoli veri persi.
  c. altrimenti -> CAUSA-C, causa non chiara, da rivedere a mano.

Indipendentemente dai commi anomali, su OGNI documento del corpus conta
anche le righe che sembrano un'intestazione d'articolo "Art N" scritta
SENZA punto (problema #9, distinto dal trattino di 1.2).

Uso:
    .venv/Scripts/python.exe scripts/riclassifica_1_4_e_problema9.py
    .venv/Scripts/python.exe scripts/riclassifica_1_4_e_problema9.py --limite 300
"""

import argparse
import importlib.util
import json
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path, PurePosixPath

import boto3
import fitz
import urllib3
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
BUCKET = "graphresponsa-archivio-392900064778"
OGGI = date.today().isoformat()
BASELINE_JSONL = ROOT / "data" / "qa_report_baseline_2026-09-15.jsonl"

load_dotenv(ROOT / ".env")
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)


def _carica(nomefile, nomemodulo):
    spec = importlib.util.spec_from_file_location(nomemodulo, SRC / nomefile)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Si importano solo le regex del parser (nessuna chiamata a parse()/main()):
# restano sincronizzate con 02_parse.py senza copiarle a mano.
p02 = _carica("02_parse.py", "parse02_ric")
RE_ARTICOLO = p02.RE_ARTICOLO
RE_PARTIZIONE = p02.RE_PARTIZIONE

s3 = boto3.client("s3")

# --------------------------------------------------------------------------
# Discriminante A: formula di promulgazione. Tollerante a "Dato"/"Data",
# alla distanza variabile dovuta alla data e a "d.F.R.", e non pretende "I"
# prima di "CAPITANI" perche' l'estrazione a volte lo stacca su righe diverse.
RE_PROMULGAZIONE = re.compile(
    r"Dat[oa]\s+dalla\s+Nostra\s+Residenza.{0,200}?CAPITANI\s+REGGENTI",
    re.I | re.S)

# Discriminante B/C: intestazione d'articolo a inizio riga, punto opzionale,
# NON richiede che la riga finisca li' (a differenza di RE_ARTICOLO) perche'
# il caso reale trovato (DD-45-2010) ha testo subito dopo sulla stessa riga:
# "Art 8  L'allegato XII del Decreto Delegato...".
RE_ART_INIZIO_RIGA = re.compile(
    r"^Art(?:icolo)?\.?\s*(\d+)\s*(?:[-\s]?\s*(?:bis|ter|quater|quinquies|sexies|septies))?",
    re.I)

# Problema #9: "Art" + spazio + numero, SENZA punto, riga a se' stante
# (stesso stampo di rigore di RE_ARTICOLO, solo senza il punto obbligatorio).
RE_ART_SENZA_PUNTO = re.compile(
    r"^Art\s+(\d+)\s*(?:bis|ter|quater|quinquies|sexies|septies)?\s*[-:.]?\s*$", re.I)


def carica_anomali():
    """id -> [(articolo_numero, commaId, lunghezza), ...] dalla baseline gia' calcolata."""
    mappa = {}
    with open(BASELINE_JSONL, encoding="utf-8") as f:
        for riga in f:
            d = json.loads(riga)
            lunghi = d.get("commi_lunghi") or []
            if lunghi:
                mappa[d["id"]] = [(c["articolo"], c["commaId"], c["lunghezza"]) for c in lunghi]
    return mappa


def elenco_documenti(limite=None):
    paginator = s3.get_paginator("list_objects_v2")
    ids = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix="raw/"):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if k.endswith("/testo.pdf"):
                ids.append(k[len("raw/"):-len("/testo.pdf")])
    ids.sort()
    return ids[:limite] if limite else ids


def righe_pdf_s3(nid):
    obj = s3.get_object(Bucket=BUCKET, Key=f"raw/{nid}/testo.pdf")
    data = obj["Body"].read()
    doc = fitz.open(stream=data, filetype="pdf")
    righe = [r.rstrip() for pagina in doc for r in pagina.get_text().split("\n")]
    doc.close()
    return righe


def _sequenza_crescente(numeri, almeno=2):
    """Vero se esiste una sotto-sequenza di almeno N valori strettamente
    crescenti, nell'ordine in cui compaiono nel testo."""
    corrente = -1
    trovati = 0
    migliore = 0
    for n in numeri:
        if n > corrente:
            trovati += 1
            corrente = n
            migliore = max(migliore, trovati)
        else:
            corrente = n
            trovati = 1
    return migliore >= almeno


def classifica_documento(nid, righe, commi_anomali):
    """
    Applica il discriminante sull'INTERA coda del documento, non sul solo
    blocco del comma peggiore.

    Scoperta sui 6 casi ispezionati a mano: quando l'allegato che segue la
    promulgazione contiene a sua volta intestazioni "Articolo N" (perche' e'
    il testo integrale di un atto straniero/internazionale - una decisione
    UE, un trattato, uno statuto societario), il riconoscitore normale del
    parser le prende per nuovi articoli DEL decreto sammarinese e spezza
    l'allegato in piu' frammenti. Il comma piu' lungo (quello che fa scattare
    "commi anomali") appartiene quasi sempre all'ULTIMO di questi frammenti
    spuri, che per costruzione non contiene la formula di promulgazione:
    quella sta nel PRIMO frammento, quello vero, scritto subito dopo l'ultimo
    articolo genuino dell'atto.

    Si prende percio' il punto di rottura piu' precoce fra TUTTI i commi
    anomali di questo documento (non solo il piu' lungo), e si cerca la
    formula su tutta la coda da li' a fine documento, non solo fino al
    prossimo Art./Partizione riconosciuto.
    """
    indici_art = [i for i, r in enumerate(righe) if RE_ARTICOLO.match(r.strip())]

    aperture = []
    for art_num, comma_id, lunghezza in commi_anomali:
        numero = str(art_num)
        for i in indici_art:
            m = RE_ARTICOLO.match(righe[i].strip())
            base = m.group(1) + (f" {m.group(2).lower()}" if m.group(2) else "")
            if base == numero:
                aperture.append((i, art_num, comma_id, lunghezza))
                break

    if not aperture:
        peggiore = max(commi_anomali, key=lambda x: x[2])
        return {"id": nid, "causa": "NON_ANALIZZABILE", "lunghezza": peggiore[2],
                "commaId": peggiore[1], "articolo": str(peggiore[0])}

    # il punto di rottura e' il PIU' PRECOCE fra tutti quelli trovati
    rottura, art_num, comma_id, lunghezza = min(aperture, key=lambda x: x[0])
    peggiore = max(commi_anomali, key=lambda x: x[2])

    coda_righe = righe[rottura:]
    coda_testo = " ".join(coda_righe)

    m_prom = RE_PROMULGAZIONE.search(coda_testo)
    if m_prom:
        lunghezza_allegato = len(coda_testo) - m_prom.end()
        return {"id": nid, "causa": "A", "lunghezza": peggiore[2], "commaId": peggiore[1],
                "articolo": str(art_num), "riga_rottura": rottura, "righe_coda": len(coda_righe),
                "n_frammenti_spuri": len(aperture), "lunghezza_allegato_stimata": lunghezza_allegato}

    numeri = []
    for r in coda_righe[1:]:
        m = RE_ART_INIZIO_RIGA.match(r.strip())
        if m:
            numeri.append(int(m.group(1)))
    collasso = _sequenza_crescente(numeri, almeno=2)
    causa = "B" if collasso else "C"
    return {"id": nid, "causa": causa, "lunghezza": peggiore[2], "commaId": peggiore[1],
            "articolo": str(art_num), "riga_rottura": rottura, "righe_coda": len(coda_righe),
            "n_frammenti_spuri": len(aperture),
            "n_intestazioni_trovate": len(numeri), "esempio_numeri": numeri[:10]}


def elabora_uno(nid, anomali_map):
    try:
        righe = righe_pdf_s3(nid)
    except Exception as e:
        return nid, None, None, f"{type(e).__name__}: {e}"

    # problema #9, indipendente dai commi anomali: su OGNI documento
    match_senza_punto = [r.strip() for r in righe if RE_ART_SENZA_PUNTO.match(r.strip())]

    esito_1_4 = None
    if nid in anomali_map:
        esito_1_4 = classifica_documento(nid, righe, anomali_map[nid])

    return nid, esito_1_4, match_senza_punto, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--worker", type=int, default=24)
    args = ap.parse_args()

    anomali_map = carica_anomali()
    print(f"Documenti con almeno un comma anomalo (dalla baseline): {len(anomali_map)}")

    ids = elenco_documenti(args.limite)
    print(f"Documenti totali da scansionare per il problema #9: {len(ids)}\n")

    risultati_1_4 = []
    problema9_docs = []
    problema9_occorrenze = 0
    errori = []

    inizio = time.time()
    with ThreadPoolExecutor(max_workers=args.worker) as ex:
        futures = {ex.submit(elabora_uno, nid, anomali_map): nid for nid in ids}
        for i, fut in enumerate(as_completed(futures), 1):
            nid, esito_1_4, match_senza_punto, err = fut.result()
            if err:
                errori.append({"id": nid, "errore": err})
                continue
            if esito_1_4:
                risultati_1_4.append(esito_1_4)
            if match_senza_punto:
                problema9_docs.append({"id": nid, "occorrenze": len(match_senza_punto),
                                       "esempio": match_senza_punto[0][:80]})
                problema9_occorrenze += len(match_senza_punto)
            if i % 1000 == 0 or i == len(ids):
                print(f"  [{i}/{len(ids)}] ({time.time()-inizio:.0f}s, {len(errori)} errori)", flush=True)

    conteggi = {"A": 0, "B": 0, "C": 0, "NON_ANALIZZABILE": 0}
    for r in risultati_1_4:
        conteggi[r["causa"]] += 1

    tot_anomali = len(anomali_map)
    tot_corpus = len(ids)

    print(f"\n{'='*80}\nRICLASSIFICAZIONE 1.4 (su {len(risultati_1_4)}/{tot_anomali} documenti con commi anomali)")
    print(f"{'='*80}")
    for causa, etichetta in [("A", "allegato post-promulgazione genuino"),
                             ("B", "vero collasso strutturale (1.4 corretto)"),
                             ("C", "causa non chiara, da rivedere a mano"),
                             ("NON_ANALIZZABILE", "apertura articolo non individuata")]:
        n = conteggi[causa]
        pct_corpus = 100 * n / tot_corpus if tot_corpus else 0
        pct_anomali = 100 * n / tot_anomali if tot_anomali else 0
        print(f"  CAUSA-{causa:<18} {etichetta:<42} {n:>5}  ({pct_corpus:5.2f}% corpus, {pct_anomali:5.2f}% degli anomali)")

    print(f"\n{'='*80}\nPROBLEMA #9 ('Art N' senza punto, indipendente dai commi anomali, tutto il corpus)")
    print(f"{'='*80}")
    print(f"  documenti impattati: {len(problema9_docs)} ({100*len(problema9_docs)/tot_corpus:.2f}% del corpus)")
    print(f"  occorrenze totali:   {problema9_occorrenze}")
    problema9_docs.sort(key=lambda x: -x["occorrenze"])
    print("  top 15:")
    for d in problema9_docs[:15]:
        print(f"    {d['id']:<16} {d['occorrenze']:>3}  es: {d['esempio']!r}")

    print("\nEsempi CAUSA-C (da rivedere a mano), primi 15:")
    for r in [x for x in risultati_1_4 if x["causa"] == "C"][:15]:
        print(f"    {r['id']:<16} art.{r['articolo']:<6} lunghezza={r['lunghezza']:<8} "
              f"intestazioni_trovate={r.get('n_intestazioni_trovate')} numeri={r.get('esempio_numeri')}")

    out = ROOT / "data" / f"riclassifica_1_4_e_problema9_{OGGI}.json"
    out.write_text(json.dumps({
        "generato": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "totale_corpus": tot_corpus,
        "totale_con_commi_anomali": tot_anomali,
        "conteggi_causa": conteggi,
        "problema9": {"documenti_impattati": len(problema9_docs),
                      "occorrenze_totali": problema9_occorrenze,
                      "top": problema9_docs[:50]},
        "dettaglio_1_4": risultati_1_4,
        "errori": errori[:20],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSalvato: {out}")
    if errori:
        print(f"Errori totali: {len(errori)} (primi: {errori[:5]})")


if __name__ == "__main__":
    main()
