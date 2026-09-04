"""
Riconciliazione dei Decreti fra portale, disco, parsing e grafo.

Non ricostruisce l'id dal titolo della card: quella derivazione e' fragile e
diverge da quella che la pipeline ottiene leggendo la scheda. Usa invece lo
schedaId, che compare nell'URL della scheda ed e' gia' salvato sia in
data/raw/<id>/scheda.json sia sul nodo :Norma. E' una chiave esatta e non
costa nessuna richiesta in piu'.

L'indice del portale si sfoglia a 200 risultati per pagina invece dei 15 di
default: 42 richieste invece di 548, sullo stesso contenuto.

    python scripts/verifica_decreti.py              # scansiona e riconcilia
    python scripts/verifica_decreti.py --da-cache   # riusa l'ultima scansione
"""

import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from neo4j import GraphDatabase

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PARSED = ROOT / "data" / "parsed"
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
CACHE = OUT / "indice_decreti_portale.json"

sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

# 01_scrape.py inizia con una cifra e non e' importabile con `import`.
_spec = importlib.util.spec_from_file_location("scrape", ROOT / "src" / "01_scrape.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

TIPO = "+Decreto"
PER_PAGINA = 200
RE_SCHEDA = re.compile(r"scheda(\d+)\.html")


def scansiona_portale():
    """Sfoglia tutto l'indice dei Decreti e restituisce una card per atto."""
    carte = {}
    pagina = 1
    totale = None

    while True:
        params = dict(sc.PARAMS_BASE, P0_tipo=TIPO,
                      P0_pagina=str(pagina), P0_paginazione=str(PER_PAGINA))
        html = sc.html_di(sc.get(sc.ARCHIVIO, params=params))

        if totale is None:
            m = re.search(r"Risultati trovati:\s*<small>(\d+)</small>", html)
            totale = int(m.group(1)) if m else -1
            print(f"Il portale dichiara {totale} atti per '{TIPO}'.")

        soup = BeautifulSoup(html, "lxml")
        blocchi = soup.select('div[id^="card_"]')
        if not blocchi:
            break

        for card in blocchi:
            scheda_id = card["id"].replace("card_", "")
            h3 = card.find("h3")
            link = card.find("a", href=re.compile(r"documento\d+\.html"))
            carte[scheda_id] = {
                "schedaId": scheda_id,
                "titolo": sc.normalizza(h3.get_text(" ", strip=True)) if h3 else "",
                "documentoId": (re.search(r"documento(\d+)\.html", link["href"]).group(1)
                                if link else None),
            }

        print(f"  pagina {pagina}: {len(blocchi)} carte  (raccolte finora: {len(carte)})")
        if len(blocchi) < PER_PAGINA:
            break
        pagina += 1
        time.sleep(sc.PAUSA)

    return {"totaleDichiarato": totale, "carte": list(carte.values())}


def id_fabbricato(id_norma, scheda_id):
    """
    Riconosce gli id prodotti da verify_all_8214_decreti.py quando la sua
    regex sul titolo non aggancia: al posto del numero finisce lo schedaId,
    e nasce una cartella 'D-17016853-1997' senza PDF accanto a quella buona.
    Vanno ignorate, o falsano il conteggio del disco.
    """
    pezzi = (id_norma or "").split("-")
    return len(pezzi) >= 3 and pezzi[1] == scheda_id


def indice_disco():
    """
    schedaId -> stato su disco.

    Uno stesso schedaId puo' avere piu' cartelle (quella buona piu' quelle
    fabbricate): si aggrega, e la scheda conta come presente se ALMENO una
    cartella ha il PDF e il JSON parsato.
    """
    per_scheda = {}
    for scheda in RAW.glob("*/scheda.json"):
        try:
            d = json.loads(scheda.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        m = RE_SCHEDA.search(d.get("urlScheda") or "")
        if not m:
            continue
        scheda_id = m.group(1)
        id_norma = d.get("id")
        if id_fabbricato(id_norma, scheda_id):
            continue

        pdf = scheda.parent / "testo.pdf"
        stato = per_scheda.setdefault(scheda_id, {"id": id_norma, "pdf": False, "parsed": False})
        if pdf.exists() and pdf.stat().st_size > 0:
            stato["pdf"] = True
            stato["id"] = id_norma
        if (PARSED / f"{id_norma}.json").exists():
            stato["parsed"] = True
            stato["id"] = id_norma
    return per_scheda


def indice_grafo():
    """schedaId -> id della norma, per le sole norme con testo caricato."""
    drv = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    per_scheda = {}
    with drv.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
        for row in s.run("""
            MATCH (n:Norma) WHERE n.caricata AND n.urlScheda IS NOT NULL
            OPTIONAL MATCH (n)-[:HA_ARTICOLO]->(a:Articolo)
            RETURN n.id AS id, n.urlScheda AS url, count(a) AS articoli
        """):
            m = RE_SCHEDA.search(row["url"] or "")
            if m:
                per_scheda[m.group(1)] = {"id": row["id"], "articoli": row["articoli"]}
    drv.close()
    return per_scheda


def riga(etichetta, n, base):
    if base:
        return f"  {etichetta:<40} {n:>6}   {n / base * 100:5.1f}%"
    return f"  {etichetta:<40} {n:>6}"


def main():
    da_cache = "--da-cache" in sys.argv

    if da_cache and CACHE.exists():
        indice = json.loads(CACHE.read_text(encoding="utf-8"))
        print(f"Riuso la scansione in {CACHE.name} ({len(indice['carte'])} carte).")
    else:
        indice = scansiona_portale()
        CACHE.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
        print(f"Scansione salvata in {CACHE}")

    carte = indice["carte"]
    dichiarato = indice["totaleDichiarato"]
    scaricabili = [c for c in carte if c["documentoId"]]
    senza_documento = [c for c in carte if not c["documentoId"]]

    disco = indice_disco()
    grafo = indice_grafo()

    mancanti_disco = []
    senza_pdf = []
    non_parsati = []
    non_nel_grafo = []
    senza_articoli = []

    for c in scaricabili:
        sid = c["schedaId"]

        # Lo stato sul disco e quello nel grafo si controllano separatamente:
        # una scheda assente dal disco puo' comunque essere gia' nel grafo da
        # un caricamento precedente, e va vista.
        d = disco.get(sid)
        if not d:
            mancanti_disco.append(c)
        else:
            if not d["pdf"]:
                senza_pdf.append(c)
            if not d["parsed"]:
                non_parsati.append(c)

        g = grafo.get(sid)
        if not g:
            non_nel_grafo.append(c)
        elif g["articoli"] == 0:
            senza_articoli.append(dict(c, id=g["id"]))

    base = len(scaricabili)

    print("\n" + "=" * 68)
    print("RICONCILIAZIONE DECRETI  -  portale > disco > parsing > grafo")
    print("=" * 68)
    print(riga("Dichiarati dal portale", dichiarato, 0))
    print(riga("Carte effettivamente indicizzate", len(carte), 0))
    print(riga("Di cui scaricabili (con documento)", len(scaricabili), len(carte)))
    print(riga("Di cui senza link al documento", len(senza_documento), len(carte)))
    print("-" * 68)
    print(riga("Presenti su disco", base - len(mancanti_disco), base))
    print(riga("Con PDF non vuoto", base - len(mancanti_disco) - len(senza_pdf), base))
    print(riga("Parsati in data/parsed", base - len(mancanti_disco) - len(non_parsati), base))
    print(riga("Caricati nel grafo", base - len(non_nel_grafo), base))
    print(riga("Nel grafo ma con zero articoli", len(senza_articoli), base))
    print("=" * 68)

    esito = {
        "totaleDichiarato": dichiarato,
        "carteIndicizzate": len(carte),
        "scaricabili": len(scaricabili),
        "senzaDocumento": senza_documento,
        "mancantiSuDisco": mancanti_disco,
        "senzaPdf": senza_pdf,
        "nonParsati": non_parsati,
        "nonNelGrafo": non_nel_grafo,
        "senzaArticoli": senza_articoli,
    }
    rapporto = OUT / "verifica_decreti.json"
    rapporto.write_text(json.dumps(esito, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRapporto completo: {rapporto}")

    sezioni = [
        ("SENZA LINK AL DOCUMENTO (non scaricabili dal portale)", senza_documento),
        ("MANCANTI SU DISCO", mancanti_disco),
        ("CON PDF VUOTO O ASSENTE", senza_pdf),
        ("NON PARSATI", non_parsati),
        ("NON NEL GRAFO", non_nel_grafo),
        ("NEL GRAFO CON ZERO ARTICOLI", senza_articoli),
    ]
    for etichetta, elenco in sezioni:
        if not elenco:
            continue
        print(f"\n{etichetta}: {len(elenco)}")
        for c in elenco[:12]:
            print(f"  scheda {c['schedaId']}  {c['titolo'][:76]}")
        if len(elenco) > 12:
            print(f"  ... altri {len(elenco) - 12}, tutti nel rapporto JSON")


if __name__ == "__main__":
    main()
