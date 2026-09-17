"""
Simula il caricamento di 03_load.py senza scrivere nulla.

Applica la semantica di MERGE+SET di Q_ARTICOLI - per un id gia' visto il SET
sovrascrive le proprieta' - e dice quanti articoli e commi verrebbero
cancellati da un omonimo dentro lo stesso documento.

Uso:
    .venv/Scripts/python.exe scripts/sim_load.py              # L-0-1910
    .venv/Scripts/python.exe scripts/sim_load.py L-168-2005
"""
import importlib.util as u, json, sys, re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
_argv, sys.argv = sys.argv, sys.argv[:1]
sys.path.insert(0, str(ROOT / 'scripts'))
import baseline_from_s3 as b
spec = u.spec_from_file_location('load03', ROOT/'src/03_load.py')
l03 = u.module_from_spec(spec)
sys.modules['load03'] = l03
spec.loader.exec_module(l03)   # import-only: main() non viene chiamata

def carica_doc(nid):
    meta = json.loads(b._s3.get_object(Bucket=b.BUCKET, Key=f"raw/{nid}/scheda.json")["Body"].read())
    dati = b.p02.parse(nid, meta); b._cache.pop(f"raw/{nid}/testo.pdf", None)
    return dati

def simula(dati):
    """Applica Q_ARTICOLI come farebbe Neo4j: MERGE per id, SET sovrascrive."""
    articoli, _, _ = l03.prepara(dati)
    nodi_art, nodi_comma, rel = {}, {}, {}
    perse_art, perse_comma = [], []
    for a in articoli:
        if a["id"] in nodi_art and nodi_art[a["id"]]["testo"] != a["testo"]:
            perse_art.append((a["id"], nodi_art[a["id"]]["testo"], a["testo"]))
        nodi_art[a["id"]] = a
        for c in a["commi"]:
            if c["id"] in nodi_comma and nodi_comma[c["id"]]["testo"] != c["testo"]:
                perse_comma.append((c["id"], nodi_comma[c["id"]]["testo"], c["testo"]))
            nodi_comma[c["id"]] = c
            rel.setdefault(a["id"], set()).add(c["id"])
    return articoli, nodi_art, nodi_comma, rel, perse_art, perse_comma

if __name__ == "__main__":
    nid = _argv[1] if len(_argv) > 1 else "L-0-1910"
    dati = carica_doc(nid)
    art, na, nc, rel, pa, pc = simula(dati)
    print(f"{nid}: articoli nel JSON {len(art)} -> nodi :Articolo {len(na)}; "
          f"commi {sum(len(a['commi']) for a in art)} -> nodi :Comma {len(nc)}")
    print("scarto di 03_load.motivo_scarto():", l03.motivo_scarto(dati))
    print(f"\nARTICOLI sovrascritti: {len(pa)}   COMMI sovrascritti: {len(pc)}")
    for i, (cid, vecchio, nuovo) in enumerate(pa[:3]):
        print(f"\n  {cid}\n    PRIMO  (perso): {vecchio[:220]}\n    SECONDO (resta): {nuovo[:220]}")
    for cid, vecchio, nuovo in pc[:3]:
        print(f"\n  {cid}\n    PRIMO  (perso): {vecchio[:200]}\n    SECONDO (resta): {nuovo[:200]}")
    # commi orfani: relazioni rimaste dal primo atto sotto un articolo sovrascritto
    misti = {aid: sorted(cs) for aid, cs in rel.items()
             if len(cs) != len([c for c in na[aid]["commi"]])}
    print(f"\narticoli il cui nodo finale ha piu' commi di quelli del suo ultimo testo: {len(misti)}")
    for aid, cs in list(misti.items())[:3]:
        print(f"  {aid}: commi collegati {len(cs)}, commi dell'ultimo articolo {len(na[aid]['commi'])}")
