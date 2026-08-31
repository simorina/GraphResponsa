"""
05 - Risoluzione degli stub: scarica il testo delle norme citate.

Legge dal grafo le norme con caricata=false (citate ma senza testo), le cerca
nell'archivio per tipo+numero+anno e ne scarica scheda e PDF. Le piu' citate
per prime: sono quelle su cui il corpus poggia davvero.

Dopo questo script vanno rieseguiti 02_parse.py e 03_load.py, che
trasformeranno gli stub in norme complete e collegheranno le citazioni
puntuali (CITA_ARTICOLO) ora che gli articoli bersaglio esistono.

Uso:
    python src/05_risolvi_stub.py           # tutte le norme stub
    python src/05_risolvi_stub.py 5         # solo le 5 piu' citate
"""

import importlib.util
import os
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comune import norma_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# 01_scrape.py inizia con una cifra e non e' importabile con `import`:
# lo carichiamo a mano per riusarne le funzioni invece di duplicarle.
_spec = importlib.util.spec_from_file_location("scrape", ROOT / "src" / "01_scrape.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

# Dal tipo leggibile alla query Lucene attesa dal campo "Tipo documento".
TIPO_LUCENE = {
    "legge": "+Legge",
    "legge costituzionale": "+Legge AND +Costituzionale",
    "legge qualificata": "+Legge AND +Qualificata",
    "decreto": "+Decreto",
    "decreto delegato": "+Decreto AND +Delegato",
    "decreto legge": "+Decreto AND +Legge",
    "decreto reggenziale": "+Decreto AND +Reggenziale",
    "decreto consiliare": "+Decreto AND +Consiliare",
    "regolamento": "+Regolamento",
}

Q_STUB = """
MATCH (:Comma|Norma)-[r:CITA]->(n:Norma {caricata: false})
RETURN n.id AS id, n.tipo AS tipo, n.numero AS numero, n.anno AS anno,
       count(r) AS citazioni
ORDER BY citazioni DESC, n.anno DESC
"""


def cerca_norma(tipo, numero, anno):
    """Cerca una norma precisa. Restituisce il primo risultato o None."""
    lucene = TIPO_LUCENE.get((tipo or "").strip().lower())
    if not lucene:
        return None
    params = dict(sc.PARAMS_BASE, P0_tipo=lucene,
                  P0_numero=str(numero), P0_anno=str(anno))
    html = sc.html_di(sc.get(sc.ARCHIVIO, params=params))
    soup = BeautifulSoup(html, "lxml")

    for card in soup.select('div[id^="card_"]'):
        h3 = card.find("h3")
        link = card.find("a", href=re.compile(r"documento\d+\.html"))
        if not h3 or not link:
            continue
        scheda_id = card["id"].replace("card_", "")
        doc_id = re.search(r"documento(\d+)\.html", link["href"]).group(1)
        base = f"{sc.BASE}/on-line/home/archivio-leggi-decreti-e-regolamenti"
        return {
            "titolo": sc.normalizza(h3.get_text(" ", strip=True)),
            "urlScheda": f"{base}/scheda{scheda_id}.html",
            "urlDocumento": f"{base}/documento{doc_id}.html",
        }
    return None


def main(limite=None):
    load_dotenv(ROOT / ".env")
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
        stub = [r.data() for r in s.run(Q_STUB)]
    driver.close()

    if limite:
        stub = stub[:limite]
    if not stub:
        print("Nessuno stub da risolvere.")
        return

    print(f"{len(stub)} norme da scaricare\n")
    ok, mancanti, disallineate = 0, [], []

    for i, n in enumerate(stub, 1):
        atteso = n["id"]
        etichetta = f"{n['tipo']} n.{n['numero']}/{n['anno']}"
        print(f"[{i}/{len(stub)}] {atteso}  ({n['citazioni']} citazioni)  {etichetta}")

        cartella = sc.RAW / atteso
        if (cartella / "testo.pdf").exists():
            print("    gia' presente\n")
            ok += 1
            continue

        time.sleep(sc.PAUSA)
        try:
            trovata = cerca_norma(n["tipo"], n["numero"], n["anno"])
        except Exception as e:
            print(f"    errore nella ricerca: {e}\n")
            mancanti.append((atteso, str(e)))
            continue

        if not trovata:
            print("    NON TROVATA nell'archivio\n")
            mancanti.append((atteso, "nessun risultato"))
            continue

        print(f"    {trovata['titolo'][:78]}")
        time.sleep(sc.PAUSA)
        campi, nome_file, iter_url = sc.leggi_scheda(trovata["urlScheda"])

        # L'id vero viene dalla scheda: se non coincide con lo stub, la
        # citazione aveva classificato il tipo in modo diverso e va segnalato,
        # altrimenti resterebbe uno stub orfano accanto alla norma caricata.
        reale = norma_id(campi.get("tipo"), campi.get("numero"), campi.get("anno"))
        if reale != atteso:
            print(f"    ATTENZIONE: la scheda dice {reale}, lo stub era {atteso}")
            disallineate.append((atteso, reale))
            cartella = sc.RAW / reale

        cartella.mkdir(parents=True, exist_ok=True)
        time.sleep(sc.PAUSA)
        try:
            _, allegati = sc.scarica_testo(trovata["urlDocumento"], cartella, nome_file)
        except Exception as e:
            print(f"    errore nello scaricamento: {e}\n")
            mancanti.append((atteso, str(e)))
            continue

        meta = {
            "id": reale,
            "tipo": campi.get("tipo"),
            "numero": int(campi["numero"]) if str(campi.get("numero", "")).isdigit() else campi.get("numero"),
            "anno": int(campi["anno"]) if str(campi.get("anno", "")).isdigit() else campi.get("anno"),
            "data": sc.data_iso(campi.get("data")),
            "dataPubblicazione": sc.data_iso(campi.get("data pubblicazione")),
            "dataEntrataVigore": sc.data_iso(campi.get("data entrata vigore")),
            "titolo": trovata["titolo"],
            "iterFormazione": campi.get("iter di formazione"),
            "urlIter": iter_url,
            "urlScheda": trovata["urlScheda"],
            "urlDocumento": trovata["urlDocumento"],
            "nomeFileOriginale": nome_file,
            "allegati": allegati,
        }
        import json
        (cartella / "scheda.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        ok += 1
        print()

    print("=" * 60)
    print(f"Scaricate: {ok}/{len(stub)}")
    if disallineate:
        print("Id diversi da quelli dedotti dalle citazioni:")
        for a, r in disallineate:
            print(f"  {a} -> {r}")
    if mancanti:
        print("Non recuperate:")
        for nid, motivo in mancanti:
            print(f"  {nid}: {motivo}")
    print("\nOra: python src/02_parse.py && python src/03_load.py")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limite=n)
