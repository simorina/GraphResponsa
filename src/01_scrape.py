"""
01 - Scraping dell'archivio leggi del Consiglio Grande e Generale.

Scarica le prime N leggi: scheda (metadati) + PDF del testo normativo.

Tre trappole del portale, gestite qui (vedi la spec per il dettaglio):
  1. La ricerca si attiva solo con indicericerca=-1 E tutti i campi del form,
     anche vuoti. Con meno parametri il server risponde 200 con zero risultati.
  2. Le pagine dichiarano charset=utf-8 ma sono windows-1252.
  3. documento<ID>.html non e' HTML: e' un PDF, oppure uno ZIP se la norma ha
     allegati (per la L.87/2026 sono 124 MB, quasi tutti cartografia).

Output: data/raw/<norma-id>/{scheda.json, testo.pdf}
Con cache: se il PDF esiste gia', non riscarica.
"""

import json
import os
import re
import sys
import time
import zipfile
from io import BytesIO
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comune import PREFISSI, norma_id, id_qualificato, normalizza_estremi  # noqa: E402

BASE = "https://www.consigliograndeegenerale.sm"
ARCHIVIO = f"{BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
PAUSA = 3.0  # secondi fra richieste: e' un server istituzionale

# Il form va inviato per intero, anche i campi vuoti, o la ricerca non parte.
PARAMS_BASE = {
    "P0_path": "/home/tomcat/indicizzazione/indexleggi",
    "P0_paginazione": "15",
    "P0_pagina": "1",
    "P0_orderBy": "index_lucene,data_ordered,numero",
    "P0_order": "asc,desc,desc",
    "P0_operatorMustBe": "yes",
    "P0_title": "",
    "P0_numero": "",
    "P0_anno": "",
    "P0_data_gg": "",
    "P0_data_mm": "",
    "P0_data_aa": "",
    "annoiniziale": "",
    "annofinale": "",
    "P0_document": "",
    "P0_data_ordered": "",
    "indicericerca": "-1",  # il trigger: senza, nessun risultato
}




# Una sessione sola: riusa la connessione invece di riaprirla ogni volta.
SESSIONE = requests.Session()
SESSIONE.headers.update({"User-Agent": UA})

ATTESE_RETRY = [3, 8, 20, 45]   # secondi


def get(url, params=None, stream=False):
    """
    GET con User-Agent e retry.

    Il portale chiude la connessione (ConnectionReset) quando le richieste si
    infittiscono: non e' un errore definitivo, va solo aspettato. Senza retry
    una sessione lunga di scaricamento muore a meta'.
    """
    ultimo = None
    for tentativo, attesa in enumerate([0] + ATTESE_RETRY):
        if attesa:
            time.sleep(attesa)
        try:
            r = SESSIONE.get(url, params=params, timeout=120, stream=stream)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            ultimo = e
            if tentativo < len(ATTESE_RETRY):
                print(f"      connessione interrotta, riprovo fra "
                      f"{ATTESE_RETRY[tentativo]}s...")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code < 500:
                raise         # 404 e simili non migliorano riprovando
            ultimo = e
    raise ultimo


# Il sito scrive gli apostrofi tipografici come &#146;, che punta a U+0092:
# un carattere di controllo, non un apostrofo. Le entita' &#128;-&#159; vanno
# reinterpretate secondo cp1252, o il testo perde apostrofi e virgolette.
_CP1252_CTRL = {c: bytes([c]).decode("cp1252", errors="replace")
                for c in range(0x80, 0xA0)}


def normalizza(testo: str) -> str:
    """Rimappa i caratteri di controllo U+0080-U+009F sui simboli cp1252."""
    return testo.translate(_CP1252_CTRL) if testo else testo


def html_di(resp) -> str:
    """Decodifica cp1252: il charset dichiarato dal sito e' sbagliato."""
    return resp.content.decode("cp1252", errors="replace")


def cerca(tipo_lucene="+Legge", limite=3, pagina=1, silenzioso=False):
    """
    Esegue la ricerca su una pagina di risultati.

    L'archivio pagina a 15 risultati: per scorrerlo tutto si incrementa
    P0_pagina. Restituisce (risultati, totale_complessivo).
    """
    params = dict(PARAMS_BASE, P0_tipo=tipo_lucene, P0_pagina=str(pagina))
    resp = get(ARCHIVIO, params=params)
    html = html_di(resp)
    soup = BeautifulSoup(html, "lxml")

    totale = None
    m = re.search(r"Risultati trovati:\s*<small>(\d+)</small>", html)
    if m:
        totale = int(m.group(1))

    cards = soup.select('div[id^="card_"]')
    if not cards:
        # Il fallimento di questo endpoint e' una pagina 200 senza risultati.
        # Deve essere rumoroso, altrimenti passa inosservato.
        raise RuntimeError(
            f"Nessun risultato a pagina {pagina}: la ricerca non si e' attivata. "
            "Verificare che i parametri del form siano completi e che "
            "indicericerca=-1 sia presente."
        )

    if not silenzioso:
        print(f"Risultati totali per '{tipo_lucene}': {totale}")

    risultati = []
    for card in cards[:limite]:
        scheda_id = card["id"].replace("card_", "")
        h3 = card.find("h3")
        link_doc = card.find("a", href=re.compile(r"documento\d+\.html"))
        if not h3 or not link_doc:
            continue
        doc_id = re.search(r"documento(\d+)\.html", link_doc["href"]).group(1)
        risultati.append({
            "schedaId": scheda_id,
            "documentoId": doc_id,
            "titolo": normalizza(h3.get_text(" ", strip=True)),
            "urlScheda": f"{BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti/scheda{scheda_id}.html",
            "urlDocumento": f"{BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti/documento{doc_id}.html",
        })
    return risultati, totale


def leggi_scheda(url_scheda):
    """Estrae i metadati dalla scheda: coppie span.descrizione -> valore."""
    resp = get(url_scheda)
    html = html_di(resp)
    soup = BeautifulSoup(html, "lxml")

    campi = {}
    for div in soup.select("div.campodettaglio"):
        span = div.find("span", class_="descrizione")
        if not span:
            continue
        etichetta = normalizza(span.get_text(strip=True)).rstrip(":").strip().lower()
        valore = normalizza(div.get_text(" ", strip=True))
        valore = valore[len(normalizza(span.get_text(strip=True))):].strip()
        if etichetta and valore:
            campi[etichetta] = valore

    # Lo script filesize() rivela il nome reale del file e la sua estensione,
    # cosi' si sa in anticipo se e' uno ZIP senza fare una HEAD.
    nome_file = None
    m = re.search(r"filesize\('([^']+)'", html)
    if m:
        nome_file = m.group(1)

    # "iter di formazione" e' un link a un'altra scheda (il progetto di legge)
    iter_url = None
    for div in soup.select("div.campodettaglio"):
        span = div.find("span", class_="descrizione")
        if span and "iter" in span.get_text(strip=True).lower():
            a = div.find("a", href=True)
            if a:
                iter_url = BASE + a["href"]

    return campi, nome_file, iter_url


def data_iso(s):
    """03/07/2026 -> 2026-07-03"""
    if not s:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s.strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def scarica_testo(url_doc, cartella, nome_file_atteso=None):
    """
    Scarica il documento. Restituisce (path_pdf, lista_allegati).
    L'endpoint puo' rispondere PDF o ZIP: si decide dal Content-Type.
    """
    pdf_path = cartella / "testo.pdf"
    allegati_path = cartella / "allegati.json"

    if pdf_path.exists():
        allegati = json.loads(allegati_path.read_text(encoding="utf-8")) if allegati_path.exists() else []
        print(f"    (cache) {pdf_path.name}")
        return pdf_path, allegati

    try:
        head = SESSIONE.head(url_doc, timeout=60)
        ctype = head.headers.get("Content-Type", "")
        clen = int(head.headers.get("Content-Length", 0))
    except (requests.ConnectionError, requests.Timeout):
        ctype, clen = "", 0   # la HEAD e' solo informativa: si prosegue col GET
    print(f"    tipo={ctype} peso={clen/1e6:.1f} MB")

    resp = get(url_doc, stream=True)
    buf = BytesIO()
    scaricato = 0
    for chunk in resp.iter_content(chunk_size=1 << 20):
        buf.write(chunk)
        scaricato += len(chunk)
        if clen and scaricato % (20 << 20) < (1 << 20):
            print(f"      {scaricato/1e6:.0f}/{clen/1e6:.0f} MB")
    dati = buf.getvalue()

    allegati = []
    if dati[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(BytesIO(dati)) as z:
            membri = [i for i in z.infolist() if not i.is_dir()]
            pdf_membri = [i for i in membri if i.filename.lower().endswith(".pdf")]
            # Il testo normativo e' il PDF senza suffisso " All. X" o prefisso "All."
            principali = [
                i for i in pdf_membri
                if " all." not in Path(i.filename).name.lower()
                and " all " not in Path(i.filename).name.lower()
                and " all_" not in Path(i.filename).name.lower()
                and not Path(i.filename).name.lower().startswith("all.")
                and not Path(i.filename).name.lower().startswith("all_")
                and not Path(i.filename).name.lower().startswith("all ")
            ]
            if not principali and pdf_membri:
                principali = pdf_membri
            if not principali:
                raise RuntimeError(f"Nessun PDF nello ZIP: {[i.filename for i in membri]}")
            principale = min(principali, key=lambda i: len(Path(i.filename).name))
            pdf_path.write_bytes(z.read(principale))
            allegati = [{"nome": Path(i.filename).name, "bytes": i.file_size}
                        for i in membri if i is not principale]
            print(f"    ZIP: estratto '{Path(principale.filename).name}', "
                  f"{len(allegati)} allegati scartati")
    elif dati[:4] == b"%PDF":
        pdf_path.write_bytes(dati)
        print(f"    PDF diretto ({len(dati)/1e3:.0f} KB)")
    else:
        raise RuntimeError(f"Formato inatteso: {dati[:16]!r} (Content-Type: {ctype})")

    allegati_path.write_text(json.dumps(allegati, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return pdf_path, allegati


INDICE = RAW / "_indice.json"


def carica_indice():
    """schedaId -> normaId, per saltare cio' che e' gia' stato scaricato
    senza interrogare di nuovo il portale."""
    try:
        if INDICE.exists():
            return json.loads(INDICE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def salva_indice(indice):
    try:
        esistente = carica_indice()
        esistente.update(indice)
        temp_file = INDICE.with_suffix(f".tmp.{os.getpid()}")
        temp_file.write_text(json.dumps(esistente, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        temp_file.replace(INDICE)
    except Exception:
        pass


def detentore_di(nid):
    """
    Lo schedaId a cui appartiene la cartella <nid>, letto dalla sua scheda.

    Restituisce None se la cartella non esiste o non e' interpretabile: in
    entrambi i casi l'id e' libero.
    """
    scheda = RAW / nid / "scheda.json"
    if not scheda.exists():
        return None
    try:
        d = json.loads(scheda.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    m = re.search(r"scheda(\d+)\.html", d.get("urlScheda") or "")
    return m.group(1) if m else None


def scarica_uno(r, indice):
    """Scarica scheda + PDF di un risultato. Restituisce l'id, o None se salta."""
    gia = indice.get(r["schedaId"])
    if gia and (RAW / gia / "testo.pdf").exists() and detentore_di(gia) == r["schedaId"]:
        return None                      # gia' in archivio locale

    time.sleep(PAUSA)
    campi, nome_file, iter_url = leggi_scheda(r["urlScheda"])
    # Il portale a volte scambia numero e anno, o lascia l'anno a zero: si
    # raddrizzano qui, prima che l'errore finisca nell'id e diventi permanente.
    numero, anno = normalizza_estremi(campi.get("numero"), campi.get("anno"),
                                      data_iso(campi.get("data")))
    nid = norma_id(campi.get("tipo"), numero, anno)

    # Tipo+numero+anno non e' una chiave: se la cartella e' gia' di un'altra
    # scheda, sovrascriverla farebbe sparire quell'atto dall'archivio. L'id
    # viene qualificato con lo schedaId invece di rubare quello altrui.
    detentore = detentore_di(nid)
    if detentore is not None and detentore != r["schedaId"]:
        nid = id_qualificato(nid, r["schedaId"])
        print(f"      id conteso da {detentore}: uso {nid}")

    cartella = RAW / nid
    cartella.mkdir(parents=True, exist_ok=True)
    time.sleep(PAUSA)
    _, allegati = scarica_testo(r["urlDocumento"], cartella, nome_file)

    meta = {
        "id": nid,
        "tipo": campi.get("tipo"),
        "numero": numero,
        "anno": anno,
        "data": data_iso(campi.get("data")),
        "dataPubblicazione": data_iso(campi.get("data pubblicazione")),
        "dataEntrataVigore": data_iso(campi.get("data entrata vigore")),
        "titolo": r["titolo"],
        "iterFormazione": campi.get("iter di formazione"),
        "urlIter": iter_url,
        "urlScheda": r["urlScheda"],
        "urlDocumento": r["urlDocumento"],
        "nomeFileOriginale": nome_file,
        "allegati": allegati,
    }
    (cartella / "scheda.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    indice[r["schedaId"]] = nid
    return nid


def main(da_pagina=1, a_pagina=None, tipo="+Legge"):
    """
    Scorre l'archivio pagina per pagina (15 risultati ciascuna).

    E' ripartibile: cio' che e' gia' su disco viene saltato senza toccare la
    rete, quindi si puo' interrompere e riprendere senza perdere lavoro.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    indice = carica_indice()

    _, totale = cerca(tipo, limite=0, pagina=da_pagina)
    pagine = (totale + 14) // 15
    ultima = min(a_pagina or pagine, pagine)
    print(f"{totale} documenti in {pagine} pagine. "
          f"Elaboro dalla {da_pagina} alla {ultima}.\n")

    nuovi = saltati = falliti = 0
    for pagina in range(da_pagina, ultima + 1):
        try:
            risultati, _ = cerca(tipo, limite=15, pagina=pagina, silenzioso=True)
        except Exception as e:
            print(f"[pagina {pagina}] ricerca fallita: {e}")
            falliti += 1
            continue

        for r in risultati:
            try:
                nid = scarica_uno(r, indice)
                if nid is None:
                    saltati += 1
                else:
                    nuovi += 1
                    print(f"[p{pagina:>3}] {nid:14s} {r['titolo'][:62]}")
            except Exception as e:
                falliti += 1
                print(f"[p{pagina:>3}] FALLITO {r['titolo'][:48]}: "
                      f"{type(e).__name__}: {str(e)[:70]}")
        salva_indice(indice)
        if pagina % 10 == 0 or pagina == ultima:
            print(f"    -- pagina {pagina}/{ultima}: {nuovi} nuovi, "
                  f"{saltati} gia' presenti, {falliti} falliti")

    salva_indice(indice)
    print(f"\nCompletato: {nuovi} nuovi, {saltati} saltati, {falliti} falliti.")
    print(f"Documenti in archivio locale: {len(list(RAW.glob('*/testo.pdf')))}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scraper archivio leggi San Marino")
    parser.add_argument("da_pagina", nargs="?", type=int, default=1, help="Pagina iniziale (default: 1)")
    parser.add_argument("a_pagina", nargs="?", type=int, default=None, help="Pagina finale (default: tutte)")
    parser.add_argument("--tipo", type=str, default="+Legge", help="Tipo lucene (default: '+Legge')")
    args = parser.parse_args()
    main(tipo=args.tipo, da_pagina=args.da_pagina, a_pagina=args.a_pagina)
