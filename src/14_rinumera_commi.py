"""
14 - Porta il grafo esistente alla numerazione dei commi di commi.ristruttura.

Quattromila articoli avevano due commi con lo stesso numero: la rubrica letta
come comma, un numero di pagina rimasto solo, il testo citato da una novella,
un elenco numerato, l'allegato dopo la formula di promulgazione (vedi
src/commi.py). 02_parse.py applica ora il riordino ai caricamenti nuovi; questo
script lo applica a quelli fatti.

La fonte e' data/parsed: e' li' che il parser ha lasciato i commi come li ha
letti. Un articolo si tocca solo se nel grafo ha ancora esattamente quei commi,
con quegli id e quel testo. Restano fuori, e si contano:

  - gli articoli riscritti dai testi coordinati (10, 12): la loro numerazione
    viene dal coordinato;
  - le norme che 03_load.py ha rifiutato, che nel grafo non ci sono;
  - gli articoli che il grafo ha in una forma diversa dal JSON.

Nel grafo i nodi restano gli stessi - vettori, citazioni, marcature di
abrogazione vanno con loro - e cambiano id, numero e ordine. Si cancellano i
commi che erano una rubrica o un numero di pagina.

Un caso a parte: nove articoli di atti degli anni '80, letti dal parser con la
struttura dedotta, avevano nel JSON piu' commi con lo stesso id. Il
caricamento li aveva fusi in un nodo solo, e il testo di 70 commi era andato
perso. Quegli articoli si ricostruiscono: commi nuovi, citazioni ricalcolate
con le funzioni del parser e del caricamento. I loro vettori li calcola 07.

Il JSON si riscrive nella stessa forma, citazioni comprese, cosi' che un
ricaricamento produca lo stesso grafo.

Uso:
    .venv/Scripts/python.exe src/14_rinumera_commi.py            # solo misura
    .venv/Scripts/python.exe src/14_rinumera_commi.py --scrivi

E' idempotente: sul risultato non trova piu' niente da cambiare.
Dopo: 09_riallinea_citazioni.py --scrivi, 08_abrogazioni.py --scrivi,
07_embeddings.py, 07b_embeddings_rubriche.py.
"""

import collections
import copy
import importlib.util
import json
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from agente.strumenti import grafo  # noqa: E402
from commi import ristruttura  # noqa: E402


def _modulo(nome, file):
    spec = importlib.util.spec_from_file_location(nome, RADICE / "src" / file)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


parser = _modulo("parse02", "02_parse.py")
carica = _modulo("load03", "03_load.py")

PARSED = RADICE / "data" / "parsed"
LOTTO = 400
CAMPI = ("id", "numero", "commaImplicito", "numerazioneAnomala", "parte", "numeroOriginale", "testo")
PROPRIETA = ("id", "numero", "ordine", "commaImplicito", "numerazioneAnomala", "parte", "numeroOriginale")

Q_COORDINATI = "MATCH (a:Articolo) WHERE a.fonteTesto IS NOT NULL RETURN a.id AS id"
Q_CARICATE = "MATCH (n:Norma) WHERE n.caricata RETURN n.id AS id"

Q_STATO = """
UNWIND $ids AS aid
MATCH (a:Articolo {id: aid})
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
WITH a, c ORDER BY c.ordine
RETURN a.id AS id, collect({id: c.id, testo: c.testo}) AS commi
"""

Q_CANCELLA = """
UNWIND $ids AS cid
MATCH (c:Comma {id: cid})
DETACH DELETE c
"""

# Due passaggi: il nome nuovo di un comma puo' essere il nome vecchio di un
# altro dello stesso articolo (c-1-2 diventa c-1 dopo che c-1 e' sparito).
Q_PARCHEGGIA = """
UNWIND $commi AS x
MATCH (c:Comma {id: x.origine})
SET c.id = 'rinumera§' + x.id
"""

Q_COMMI = """
UNWIND $commi AS x
MATCH (c:Comma {id: 'rinumera§' + x.id})
SET c.id = x.id, c.numero = x.numero, c.ordine = x.ordine,
    c.commaImplicito = x.commaImplicito, c.numerazioneAnomala = x.numerazioneAnomala,
    c.parte = x.parte, c.numeroOriginale = x.numeroOriginale,
    // Solo i commi che hanno assorbito un frammento cambiano testo: il loro
    // vettore va rifatto da 07.
    c.embedding = CASE WHEN c.testo = x.testo THEN c.embedding ELSE null END,
    c.testo = x.testo
"""

Q_ARTICOLI = """
UNWIND $articoli AS x
MATCH (a:Articolo {id: x.id})
SET a.testo = x.testo,
    a.embedding = CASE WHEN coalesce(a.rubrica, '') = coalesce(x.rubrica, '')
                       THEN a.embedding ELSE null END,
    a.rubrica = x.rubrica
"""

Q_SVUOTA = """
UNWIND $ids AS aid
MATCH (:Articolo {id: aid})-[:HA_COMMA]->(c:Comma)
DETACH DELETE c
"""

Q_CREA = """
UNWIND $commi AS x
MATCH (a:Articolo {id: x.articolo})
CREATE (c:Comma {id: x.id})
SET c.numero = x.numero, c.testo = x.testo, c.ordine = x.ordine,
    c.commaImplicito = x.commaImplicito, c.numerazioneAnomala = x.numerazioneAnomala,
    c.parte = x.parte, c.numeroOriginale = x.numeroOriginale
MERGE (a)-[:HA_COMMA]->(c)
"""


def _forma(commi):
    return [tuple(c.get(k) for k in CAMPI) for c in commi]


def pulisci(commi):
    """Il comma come lo scrive il parser: senza le chiavi di lavoro."""
    return [{k: v for k, v in c.items() if k not in ("origine", "assorbiti")} for c in commi]


def citazioni_di(norma, articolo):
    """Le citazioni dei commi dell'articolo, come le calcola il parser."""
    fuori = []
    for c in articolo["commi"]:
        for cit in parser.estrai_citazioni(c["testo"], norma):
            cit["commaId"] = c["id"]
            cit["commaOrigine"] = c["numero"]
            fuori.append(cit)
    return fuori


def pianifica(dati, coordinati):
    """Gli articoli di una norma che il riordino cambia, e quelli da ricostruire."""
    cambi, ricostruzioni = [], []
    for a in dati.get("articoli") or []:
        if a["id"] in coordinati or not a.get("commi") or any("id" not in c for c in a["commi"]):
            continue
        nuovo = ristruttura(copy.deepcopy(a))
        ids = [c["id"] for c in a["commi"]]
        if len(ids) != len(set(ids)):
            ricostruzioni.append((a, nuovo))
            continue
        prima = [{**{k: None for k in CAMPI}, **c} for c in a["commi"]]
        if (_forma(prima) == _forma(nuovo["commi"])
                and (a.get("rubrica") or None) == (nuovo.get("rubrica") or None)):
            continue
        cambi.append((a, nuovo))
    return cambi, ricostruzioni


Q_BACKUP = """
UNWIND $ids AS cid
MATCH (c:Comma {id: cid})
OPTIONAL MATCH (c)-[r]->(t)
RETURN c.id AS id, properties(c) AS proprieta,
       collect(CASE WHEN r IS NULL THEN null
               ELSE {tipo: type(r), verso: t.id, proprieta: properties(r)} END) AS archi
"""


def salva_backup(g, file, in_sync, ricostruire, dati_per_file):
    """Quanto serve per tornare indietro.

    I nodi che si cancellano per intero, con vettore e archi; per gli altri
    basta la mappa dei nomi, perche' testo, vettore e archi non cambiano. Poi
    le rubriche di prima e i JSON originali delle norme toccate.
    """
    cancellati, rinomine, rubriche = [], [], {}
    for _, a, n in in_sync:
        tenuti = {c["origine"] for c in n["commi"]}
        cancellati += [c["id"] for c in a["commi"] if c["id"] not in tenuti]
        rinomine += [{"da": c["origine"], "a": c["id"]} for c in n["commi"] if c["id"] != c["origine"]]
        rubriche[a["id"]] = a.get("rubrica")
    for _, a, _ in ricostruire:
        cancellati += sorted({c["id"] for c in a["commi"]})
    nodi = []
    for i in range(0, len(cancellati), LOTTO):
        nodi += [dict(r) for r in g.query(Q_BACKUP, {"ids": cancellati[i:i + LOTTO]})]
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({
        "cancellati": nodi, "rinomine": rinomine, "rubriche": rubriche,
        "articoliRicostruiti": [a["id"] for _, a, _ in ricostruire],
        "json": {str(f.name): d for f, d in dati_per_file.items()},
    }, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"    backup: {file} ({file.stat().st_size / 1e6:.0f} MB, {len(nodi):,} nodi, "
          f"{len(rinomine):,} rinomine)")


def main():
    scrivi = "--scrivi" in sys.argv
    g = grafo()
    coordinati = {r["id"] for r in g.query(Q_COORDINATI)}
    caricate = {r["id"] for r in g.query(Q_CARICATE)}

    dati_per_file, tutti, ricostruire, rifiutate = {}, [], [], 0
    for f in sorted(PARSED.glob("*.json")):
        try:
            dati = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        cambi, ricostruzioni = pianifica(dati, coordinati)
        if not (cambi or ricostruzioni):
            continue
        if dati.get("id") not in caricate:
            rifiutate += len(cambi) + len(ricostruzioni)
            continue
        dati_per_file[f] = dati
        tutti += [(f, a, n) for a, n in cambi]
        ricostruire += [(f, a, n) for a, n in ricostruzioni]
    print(f"\n  articoli da riordinare: {len(tutti):,} | da ricostruire: {len(ricostruire)}"
          f" | in norme rifiutate da 03 (saltati): {rifiutate:,}")

    in_sync, fuori_sync = [], []
    for i in range(0, len(tutti), LOTTO):
        lotto = tutti[i:i + LOTTO]
        stato = {r["id"]: r for r in g.query(Q_STATO, {"ids": [a["id"] for _, a, _ in lotto]})}
        for f, a, n in lotto:
            s = stato.get(a["id"])
            nel_grafo = [(c["id"], c["testo"]) for c in (s["commi"] if s else []) if c["id"]]
            if s and nel_grafo == [(c["id"], c["testo"]) for c in a["commi"]]:
                in_sync.append((f, a, n))
            else:
                fuori_sync.append(a["id"])

    conta = collections.Counter()
    esempi = collections.defaultdict(list)
    for _, a, n in in_sync:
        tenuti = {c["origine"] for c in n["commi"]}
        cancellati = len({c["id"] for c in a["commi"]} - tenuti)
        rubrica = bool(not (a.get("rubrica") or "").strip() and (n.get("rubrica") or "").strip())
        parti = collections.Counter(c["parte"] for c in n["commi"] if c["parte"])
        conta["articoli"] += 1
        conta["rubriche recuperate"] += rubrica
        conta["commi-spazzatura tolti"] += cancellati - rubrica - sum(len(c.get("assorbiti", [])) for c in n["commi"])
        for parte, q in parti.items():
            conta[f"{parte}: commi"] += q
            conta[f"{parte}: articoli"] += 1
            if len(esempi[parte]) < 2:
                esempi[parte].append((a, n))
        if rubrica and len(esempi["rubrica"]) < 2:
            esempi["rubrica"].append((a, n))
        conta["frammenti riuniti"] += sum(len(c.get("assorbiti", [])) for c in n["commi"])
        if any(c.get("assorbiti") for c in n["commi"]) and len(esempi["riuniti"]) < 2:
            esempi["riuniti"].append((a, n))
        conta["commi rinominati"] += sum(1 for c in n["commi"] if c["id"] != c["origine"])
        numeri = [c["numero"] for c in n["commi"]]
        conta["ancora con numeri doppi"] += len(numeri) != len(set(numeri))

    for k in ("articoli", "rubriche recuperate", "commi-spazzatura tolti", "frammenti riuniti",
              "capoverso: articoli", "capoverso: commi", "punto: articoli", "punto: commi",
              "allegato: articoli", "allegato: commi", "commi rinominati", "ancora con numeri doppi"):
        print(f"    {k:<32} {conta[k]:>7,}")
    print(f"    {'fuori sincronia (saltati)':<32} {len(fuori_sync):>7,}"
          + (f"  es. {', '.join(fuori_sync[:5])}" if fuori_sync else ""))
    for _, a, n in ricostruire:
        print(f"    da ricostruire {a['id']}: {len(a['commi'])} commi nel JSON, "
              f"{len({c['id'] for c in a['commi']})} id distinti")
    for chiave, casi in esempi.items():
        for a, n in casi:
            print(f"\n  [{chiave}] {a['id']}  rubrica: {a.get('rubrica')!r} -> {n.get('rubrica')!r}")
            for c in n["commi"][:7]:
                print(f"     {c['origine'].split('/')[-1]:>10} -> {c['id'].split('/')[-1]:<12} {c['numero']:<9} "
                      f"{c['testo'][-70:]!r}")

    if not scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi --backup <file.json> per applicare al grafo e ai JSON.")
        return
    if "--backup" not in sys.argv:
        sys.exit("  --scrivi vuole --backup <file.json>: si cancellano nodi, e deve restare il modo di rimetterli.")
    salva_backup(g, Path(sys.argv[sys.argv.index("--backup") + 1]), in_sync, ricostruire, dati_per_file)

    for i in range(0, len(in_sync), LOTTO):
        lotto = in_sync[i:i + LOTTO]
        cancella, commi, articoli = [], [], []
        for _, a, n in lotto:
            tenuti = {c["origine"] for c in n["commi"]}
            cancella += [c["id"] for c in a["commi"] if c["id"] not in tenuti]
            commi += [{**{k: c.get(k) for k in PROPRIETA}, "origine": c["origine"], "ordine": k,
                       "testo": c["testo"]}
                      for k, c in enumerate(n["commi"])]
            articoli.append({"id": a["id"], "rubrica": n.get("rubrica"),
                             "testo": " ".join(c["testo"] for c in n["commi"])})
        g.query(Q_CANCELLA, {"ids": cancella})
        g.query(Q_PARCHEGGIA, {"commi": commi})
        g.query(Q_COMMI, {"commi": commi})
        g.query(Q_ARTICOLI, {"articoli": articoli})
        # Le citazioni dei frammenti se ne sono andate coi loro nodi: si
        # ricalcolano sul comma che li ha assorbiti.
        cambiati = [(f, n) for f, a, n in lotto if any(c.get("assorbiti") for c in n["commi"])]
        for f, n in cambiati:
            norma = dati_per_file[f]["id"]
            solo = {**n, "commi": [c for c in n["commi"] if c.get("assorbiti")]}
            solo["citazioni"] = citazioni_di(norma, solo)
            _, citazioni, _ = carica.prepara({"id": norma, "articoli": [solo]})
            if citazioni:
                g.query(carica.Q_CITAZIONI, {"citazioni": citazioni})
        print(f"    grafo: {min(i + LOTTO, len(in_sync)):,}/{len(in_sync):,}")

    for f, a, n in ricostruire:
        norma = dati_per_file[f]["id"]
        g.query(Q_SVUOTA, {"ids": [a["id"]]})
        g.query(Q_CREA, {"commi": [{**{k: c.get(k) for k in PROPRIETA}, "testo": c["testo"],
                                    "ordine": k, "articolo": a["id"]}
                                   for k, c in enumerate(n["commi"])]})
        g.query(Q_ARTICOLI, {"articoli": [{"id": a["id"], "rubrica": n.get("rubrica"),
                                           "testo": " ".join(c["testo"] for c in n["commi"])}]})
        n["citazioni"] = citazioni_di(norma, n)
        _, citazioni, _ = carica.prepara({"id": norma, "articoli": [n]})
        if citazioni:
            g.query(carica.Q_CITAZIONI, {"citazioni": citazioni})
        print(f"    ricostruito {a['id']}: {len(n['commi'])} commi, {len(citazioni)} citazioni")

    toccati = collections.defaultdict(dict)
    for f, a, n in in_sync + ricostruire:
        toccati[f][a["id"]] = n
    ricostruiti = {a["id"] for _, a, _ in ricostruire}
    for f, nuovi in toccati.items():
        dati = dati_per_file[f]
        for a in dati["articoli"]:
            n = nuovi.get(a["id"])
            if not n:
                continue
            a["rubrica"] = n.get("rubrica")
            a["commi"] = pulisci(n["commi"])
            if a["id"] in ricostruiti:
                a["citazioni"] = citazioni_di(dati["id"], a)
                continue
            mappa = {c["origine"]: c for c in n["commi"]}
            mappa.update({v: c for c in n["commi"] for v in c.get("assorbiti", [])})
            rifatti = {c["id"] for c in n["commi"] if c.get("assorbiti")}
            vecchie = [{**cit, "commaId": mappa[cit["commaId"]]["id"],
                        "commaOrigine": mappa[cit["commaId"]]["numero"]}
                       for cit in a.get("citazioni") or [] if cit.get("commaId") in mappa]
            nuove = citazioni_di(dati["id"], {"commi": [c for c in n["commi"] if c["id"] in rifatti]})
            a["citazioni"] = [c for c in vecchie if c["commaId"] not in rifatti] + nuove
        f.write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"    JSON riscritti: {len(toccati):,}")
    print("\n  Ora: 09_riallinea_citazioni.py --scrivi, 08_abrogazioni.py --scrivi,"
          " 07_embeddings.py, 07b_embeddings_rubriche.py.")


if __name__ == "__main__":
    main()
