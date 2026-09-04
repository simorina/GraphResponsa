"""
Ripara le schede il cui numero e anno il portale ha confuso.

Sull'archivio reale ci sono due guasti:

  - **invertiti**: la scheda del Decreto Delegato n.9 del 2007 riporta
    numero=2007 e anno=9. Ne nasce l'id 'DD-2007-9', che nessuna citazione
    potra' mai agganciare, e che l'ordinamento per anno colloca nell'anno 9 -
    rompendo il principio di vigenza su cui l'agente si appoggia.
  - **anno assente**: anno=0, mentre la data completa e' presente.

`comune.normalizza_estremi()` impedisce che ricapiti su cio' che si scarica da
adesso. Questo script sistema cio' che e' gia' a terra: rinomina la cartella,
riscrive scheda.json e cancella il JSON parsato, cosi' 02_parse.py lo rigenera.

    python scripts/ripara_estremi.py            # mostra cosa farebbe
    python scripts/ripara_estremi.py --applica  # lo fa davvero
"""

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PARSED = ROOT / "data" / "parsed"
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)

sys.path.insert(0, str(ROOT / "src"))
from comune import normalizza_estremi, norma_id, SEPARATORE_COLLISIONE  # noqa: E402


def main():
    applica = "--applica" in sys.argv
    da_riparare = []

    for scheda in RAW.glob("*/scheda.json"):
        try:
            d = json.loads(scheda.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue

        numero, anno = normalizza_estremi(d.get("numero"), d.get("anno"), d.get("data"))

        vecchio = scheda.parent.name
        base = norma_id(d.get("tipo"), numero, anno)
        # Un id qualificato conserva il suo suffisso: identifica la scheda, non
        # gli estremi, e perderlo rimetterebbe in piedi la collisione.
        coda = vecchio.split(SEPARATORE_COLLISIONE, 1)
        nuovo = f"{base}{SEPARATORE_COLLISIONE}{coda[1]}" if len(coda) > 1 else base

        # Il confronto va fatto sull'id, non sui campi grezzi: alcune schede
        # tengono numero e anno come stringhe e altre come interi, e "122" != 122
        # farebbe scattare la riparazione su migliaia di record gia' a posto.
        if nuovo == vecchio:
            continue

        # Un numero non interamente numerico (es. "6-EC") non va normalizzato:
        # la parte alfabetica e' significativa, e trattarla come cifra produce
        # id senza senso.
        if not str(d.get("numero") or "").strip().isdigit():
            continue

        # Due cause diverse, che meritano trattamenti diversi:
        #   estremi - numero o anno sono cambiati
        #   tipo    - cambia solo il prefisso, perche' PREFISSI e' stato esteso
        #             dopo che quella scheda era gia' stata scaricata
        estremi_cambiati = (str(numero) != str(d.get("numero"))
                            or str(anno) != str(d.get("anno")))

        da_riparare.append({
            "vecchio": vecchio, "nuovo": nuovo,
            "causa": "estremi" if estremi_cambiati else "tipo",
            "prefissoVecchio": vecchio.split("-")[0],
            "numeroPrima": d.get("numero"), "annoPrima": d.get("anno"),
            "numeroDopo": numero, "annoDopo": anno,
            "data": d.get("data"), "titolo": (d.get("titolo") or "")[:44],
        })

    estremi = [r for r in da_riparare if r["causa"] == "estremi"]
    # Il prefisso si tocca solo quando era 'X', cioe' quando il tipo non era
    # stato riconosciuto: quegli id nessuna citazione puo' agganciarli, quindi
    # cambiarli e' solo un guadagno. Un prefisso valido che ne diventa un altro
    # e' un giudizio sul merito dell'atto, e non lo prende uno script.
    tipo_x = [r for r in da_riparare if r["causa"] == "tipo" and r["prefissoVecchio"] == "X"]
    tipo_altro = [r for r in da_riparare if r["causa"] == "tipo" and r["prefissoVecchio"] != "X"]

    print(f"Numero e anno da raddrizzare   : {len(estremi)}")
    print(f"Prefisso X ora riconoscibile   : {len(tipo_x)}")
    print(f"Cambio di prefisso da decidere : {len(tipo_altro)}  (NON toccati)")
    print()
    print(f"  {'vecchio id':<24}{'nuovo id':<22}{'era':>16}   data")
    print('  ' + '-' * 76)
    for r in estremi:
        era = f"n={r['numeroPrima']} a={r['annoPrima']}"
        print(f"  {r['vecchio']:<24}{r['nuovo']:<22}{era:>16}   {r['data']}")
    if tipo_x:
        print()
        print(f"  primi 6 dei {len(tipo_x)} con prefisso X:")
        for r in tipo_x[:6]:
            print(f"    {r['vecchio']:<22} -> {r['nuovo']}")
    if tipo_altro:
        print()
        print("  NON toccati, il prefisso era gia' valido:")
        for r in tipo_altro:
            print(f"    {r['vecchio']:<22} -> {r['nuovo']}   ({r['titolo']})")

    da_riparare = estremi + tipo_x

    (OUT / "riparazione_estremi.json").write_text(
        json.dumps(da_riparare, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRapporto: {OUT / 'riparazione_estremi.json'}")

    if not applica:
        print("\nProva a vuoto. Per eseguire davvero: --applica")
        return

    fatti, saltati = 0, []
    for r in da_riparare:
        vecchia = RAW / r["vecchio"]
        d = json.loads((vecchia / "scheda.json").read_text(encoding="utf-8"))
        destinazione = r["nuovo"]

        if (RAW / destinazione).exists():
            # La destinazione e' occupata. Non e' un doppione: i due atti
            # puntano a schede diverse del portale e dopo la correzione degli
            # estremi rivendicano lo stesso id. E' la collisione gia' nota, e
            # si risolve qualificando con lo schedaId invece di sovrascrivere.
            m = re.search(r"scheda(\d+)\.html", d.get("urlScheda") or "")
            if not m:
                saltati.append((r["vecchio"], "destinazione occupata e scheda illeggibile"))
                continue
            destinazione = f"{r['nuovo']}{SEPARATORE_COLLISIONE}{m.group(1)}"
            if (RAW / destinazione).exists():
                saltati.append((r["vecchio"], f"anche {destinazione} esiste"))
                continue
            r["nuovo"] = destinazione

        nuova = RAW / destinazione
        d["numero"], d["anno"], d["id"] = r["numeroDopo"], r["annoDopo"], destinazione
        (vecchia / "scheda.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        vecchia.rename(nuova)

        # Il JSON parsato porta ancora l'id vecchio: si rigenera.
        (PARSED / f"{r['vecchio']}.json").unlink(missing_ok=True)
        fatti += 1

    print(f"\nRiparate: {fatti}")
    if saltati:
        print(f"Saltate: {len(saltati)}")
        for v, perche in saltati:
            print(f"  {v}: {perche}")

    print("\nOra: python src/02_parse.py  &&  python src/03_load.py")
    print("Poi vanno rimossi dal grafo i nodi con gli id vecchi:")
    print("  python scripts/ripara_estremi.py --pulisci-grafo")


def pulisci_grafo():
    """Toglie dal grafo i nodi rimasti con l'id vecchio, e il loro sottoalbero."""
    import os
    from dotenv import load_dotenv
    from neo4j import GraphDatabase
    load_dotenv(ROOT / ".env")

    dati = json.loads((OUT / "riparazione_estremi.json").read_text(encoding="utf-8"))
    vecchi = [r["vecchio"] for r in dati]
    drv = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    with drv.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
        # Prima articoli e commi, poi la norma: un DETACH DELETE sulla sola
        # norma lascerebbe articoli e commi orfani nel grafo.
        r = s.run("""
            UNWIND $ids AS vecchio
            MATCH (n:Norma {id: vecchio})
            OPTIONAL MATCH (n)-[:HA_ARTICOLO]->(a:Articolo)
            OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
            DETACH DELETE c, a, n
            RETURN count(DISTINCT vecchio) AS norme
        """, ids=vecchi).single()
        print(f"Nodi con id vecchio rimossi: {r['norme']}")
    drv.close()


if __name__ == "__main__":
    if "--pulisci-grafo" in sys.argv:
        pulisci_grafo()
    else:
        main()
