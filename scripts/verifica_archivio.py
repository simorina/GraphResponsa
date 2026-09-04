"""
Riconciliazione dell'intero archivio fra portale, disco, parsing e grafo.

Generalizza scripts/verifica_decreti.py a tutte le voci del menu "Tipo
documento". Le voci di primo livello sono query Lucene larghe che inglobano i
sottotipi ("+Decreto" prende anche Decreto Delegato, Reggenziale, Consiliare):
scandirle tutte moltiplicherebbe le richieste senza aggiungere atti.

La chiave di riconciliazione e' lo schedaId, non l'id ricostruito: compare
nell'URL della scheda ed e' gia' salvato sia in data/raw/<id>/scheda.json sia
sul nodo :Norma. Non costa nessuna richiesta in piu' ed e' immune alle
collisioni di tipo+numero+anno.

    python scripts/verifica_archivio.py               # tutto l'archivio
    python scripts/verifica_archivio.py --da-cache    # riusa le scansioni
    python scripts/verifica_archivio.py --tipo +Legge # un tipo solo
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

sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

_spec = importlib.util.spec_from_file_location("scrape", ROOT / "src" / "01_scrape.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

# Solo le voci di primo livello: i sottotipi ricadono gia' dentro queste.
# "Tutti i tipi" ha value vuoto e non attiva la ricerca, quindi non e' usabile.
TIPI = [
    "+Legge",
    "+Decreto",
    "+Regolamento",
    "+Notifica",
    "+Statuto",
    "+Verbale",
    "+Ordinanza",
    "+Errata AND +Corrige",
    "+Non AND +definito",
]

PER_PAGINA = 200
RE_SCHEDA = re.compile(r"scheda(\d+)\.html")


def file_cache(tipo):
    return OUT / f"indice_{re.sub(r'[^a-z0-9]+', '_', tipo.lower()).strip('_')}.json"


def scansiona(tipo):
    """Sfoglia l'indice di un tipo e restituisce una card per atto."""
    carte, pagina, totale = {}, 1, None

    while True:
        params = dict(sc.PARAMS_BASE, P0_tipo=tipo,
                      P0_pagina=str(pagina), P0_paginazione=str(PER_PAGINA))
        html = sc.html_di(sc.get(sc.ARCHIVIO, params=params))

        if totale is None:
            m = re.search(r"Risultati trovati:\s*<small>(\d+)</small>", html)
            totale = int(m.group(1)) if m else 0
            print(f"  '{tipo}': il portale ne dichiara {totale}")

        blocchi = BeautifulSoup(html, "lxml").select('div[id^="card_"]')
        if not blocchi:
            break

        for card in blocchi:
            scheda_id = card["id"].replace("card_", "")
            h3 = card.find("h3")
            link = card.find("a", href=re.compile(r"documento\d+\.html"))
            carte[scheda_id] = {
                "schedaId": scheda_id,
                "tipoRicerca": tipo,
                "titolo": sc.normalizza(h3.get_text(" ", strip=True)) if h3 else "",
                "documentoId": (re.search(r"documento(\d+)\.html", link["href"]).group(1)
                                if link else None),
            }

        if len(blocchi) < PER_PAGINA:
            break
        pagina += 1
        time.sleep(sc.PAUSA)

    print(f"  '{tipo}': raccolte {len(carte)} carte in {pagina} pagine")
    return {"tipo": tipo, "totaleDichiarato": totale, "carte": list(carte.values())}


def id_fabbricato(id_norma, scheda_id):
    """
    Riconosce gli id in cui al posto del numero e' finito lo schedaId, lasciati
    da verify_all_8214_decreti.py quando la sua regex sul titolo non aggancia.
    Sono cartelle senza PDF: contarle falserebbe lo stato del disco.
    """
    pezzi = (id_norma or "").split("-")
    return len(pezzi) >= 3 and pezzi[1] == scheda_id


def indice_disco():
    """schedaId -> stato su disco, aggregando le cartelle che lo condividono."""
    per_scheda = {}
    for scheda in RAW.glob("*/scheda.json"):
        try:
            d = json.loads(scheda.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        m = RE_SCHEDA.search(d.get("urlScheda") or "")
        if not m:
            continue
        scheda_id, id_norma = m.group(1), d.get("id")
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
    """schedaId -> id e numero di articoli, per le norme con testo caricato."""
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
        return f"  {etichetta:<38} {n:>6}   {n / base * 100:5.1f}%"
    return f"  {etichetta:<38} {n:>6}"


def main():
    da_cache = "--da-cache" in sys.argv
    tipi = TIPI
    if "--tipo" in sys.argv:
        tipi = [sys.argv[sys.argv.index("--tipo") + 1]]

    print("Scansione dell'indice per tipo di documento\n")
    indici = []
    for tipo in tipi:
        cache = file_cache(tipo)
        if da_cache and cache.exists():
            indici.append(json.loads(cache.read_text(encoding="utf-8")))
            print(f"  '{tipo}': riuso {cache.name} ({len(indici[-1]['carte'])} carte)")
            continue
        ind = scansiona(tipo)
        cache.write_text(json.dumps(ind, ensure_ascii=False), encoding="utf-8")
        indici.append(ind)
        time.sleep(sc.PAUSA)

    # Un atto puo' comparire sotto piu' query Lucene: si deduplica per schedaId.
    unione = {}
    for ind in indici:
        for c in ind["carte"]:
            unione.setdefault(c["schedaId"], c)
    carte = list(unione.values())

    disco = indice_disco()
    grafo = indice_grafo()

    scaricabili = [c for c in carte if c["documentoId"]]
    senza_documento = [c for c in carte if not c["documentoId"]]

    mancanti, senza_pdf, non_parsati, non_nel_grafo, senza_articoli = [], [], [], [], []
    for c in scaricabili:
        sid = c["schedaId"]
        d = disco.get(sid)
        if not d:
            mancanti.append(c)
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
    print("\n" + "=" * 66)
    print("RICONCILIAZIONE ARCHIVIO  -  portale > disco > parsing > grafo")
    print("=" * 66)
    for ind in indici:
        print(f"  {ind['tipo']:<24} dichiarati {ind['totaleDichiarato']:>6}   "
              f"indicizzati {len(ind['carte']):>6}")
    print("-" * 66)
    print(riga("Atti distinti (deduplicati)", len(carte), 0))
    print(riga("Di cui scaricabili", base, len(carte)))
    print(riga("Senza link al documento", len(senza_documento), len(carte)))
    print("-" * 66)
    print(riga("Presenti su disco", base - len(mancanti), base))
    print(riga("Con PDF non vuoto", base - len(mancanti) - len(senza_pdf), base))
    print(riga("Parsati", base - len(mancanti) - len(non_parsati), base))
    print(riga("Caricati nel grafo", base - len(non_nel_grafo), base))
    print(riga("Nel grafo con zero articoli", len(senza_articoli), base))
    print("=" * 66)

    esito = {
        "tipi": [{"tipo": i["tipo"], "dichiarati": i["totaleDichiarato"],
                  "indicizzati": len(i["carte"])} for i in indici],
        "attiDistinti": len(carte),
        "scaricabili": base,
        "senzaDocumento": senza_documento,
        "mancantiSuDisco": mancanti,
        "senzaPdf": senza_pdf,
        "nonParsati": non_parsati,
        "nonNelGrafo": non_nel_grafo,
        "senzaArticoli": senza_articoli,
    }
    rapporto = OUT / "verifica_archivio.json"
    rapporto.write_text(json.dumps(esito, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRapporto completo: {rapporto}")

    for etichetta, elenco in (
        ("SENZA LINK AL DOCUMENTO", senza_documento),
        ("MANCANTI SU DISCO", mancanti),
        ("NON NEL GRAFO", non_nel_grafo),
        ("NEL GRAFO CON ZERO ARTICOLI", senza_articoli),
    ):
        if not elenco:
            continue
        print(f"\n{etichetta}: {len(elenco)}")
        for c in elenco[:10]:
            print(f"  scheda {c['schedaId']}  [{c['tipoRicerca']}]  {c['titolo'][:56]}")
        if len(elenco) > 10:
            print(f"  ... altri {len(elenco) - 10}, tutti nel rapporto JSON")


if __name__ == "__main__":
    main()
