"""
15 - Ricarica dal PDF gli atti con articoli che il caricamento aveva fuso.

268 atti avevano nel JSON due articoli con lo stesso id - un allegato che
riparte da "Art. 1" dopo la firma, un refuso, un'intestazione incollata in coda
a un comma (vedi src/articoli.py). 03_load.py fa MERGE sull'id: i due articoli
finivano nello stesso nodo, e il testo del primo spariva sotto il secondo.

Il JSON di questi atti non basta a ricostruirli: alcuni vengono da versioni
precedenti del parser, che li leggevano peggio (il D-11-2000 aveva al posto
dell'art. 1 una riga della sua tabella di sanzioni). Per ogni atto coinvolto:

  - si rilegge il PDF con 02_parse.py, che applica articoli.py e commi.py;
  - se 03_load.py rifiuterebbe il risultato, l'atto resta com'e' e si segnala;
  - si cancellano articoli e commi dell'atto (non la norma, ne' le citazioni
    del suo preambolo) e si ricreano con le query di 03_load.py;
  - i vettori tornano dove il testo e' identico, cosi' 07 calcola solo quelli
    del testo che il grafo non aveva;
  - le citazioni si ricalcolano; gli archi di novella scritti dai testi
    coordinati (quelli con un'origine) si ricollegano all'articolo con lo
    stesso id;
  - il JSON si riscrive con la lettura nuova.

Restano fuori gli atti con articoli riscritti dai testi coordinati e quelli
ricomposti da 13_atto_composto.py. Il backup tiene gli articoli di prima con
tutti gli archi, e i commi per intero - vettore compreso - solo dove il testo
non torna nella lettura nuova.

Con `--atti <file.json>` (un elenco di id) si ricaricano gli atti indicati
invece di quelli con articoli fusi: e' cosi' che il 17/09 sono rientrati gli
atti che il parser leggeva male (intestazioni "Art. 1 (Rubrica)", testo
perso dopo un TITOLO). Per questi il controllo sul testo non e' "almeno il 90%
dei caratteri" - le intestazioni riconosciute e gli indici passano fuori dai
commi - ma "nessuna parola del grafo scompare".

Uso:
    .venv/Scripts/python.exe src/15_ricostruisci_articoli.py            # solo misura
    .venv/Scripts/python.exe src/15_ricostruisci_articoli.py --scrivi --backup <file.json>
    .venv/Scripts/python.exe src/15_ricostruisci_articoli.py --atti <elenco.json> [--scrivi --backup ...]
    .venv/Scripts/python.exe src/15_ricostruisci_articoli.py --atti <elenco.json> --testo-nuovo ...
        (PDF sostituito da 21_testi_scambiati.py: niente controllo sulle parole)

Dopo --atti: anche 19_frammenti.py --scrivi e 20_pulizia_grafo.py --scrivi.

Dopo: 14_rinumera_commi.py (deve trovare zero), 09_riallinea_citazioni.py
--scrivi, 08_abrogazioni.py --scrivi, 07_embeddings.py,
07b_embeddings_rubriche.py.
"""

import collections
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from agente.strumenti import grafo  # noqa: E402
from articoli import ristruttura_articoli  # noqa: E402
from comune import risolutore_per_data  # noqa: E402


def _modulo(nome, file):
    spec = importlib.util.spec_from_file_location(nome, RADICE / "src" / file)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


parser = _modulo("parse02", "02_parse.py")
carica = _modulo("load03", "03_load.py")

PARSED = RADICE / "data" / "parsed"
LOTTO = 200
STRUTTURALI = ("preambolo", "citazioniPreambolo", "partizioni", "articoli")

Q_STATO = """
MATCH (:Norma {id: $norma})-[:HA_ARTICOLO]->(a:Articolo)
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
RETURN a.id AS id, a.fonteTesto IS NOT NULL AS coordinato, a.rubrica AS rubrica,
       collect({id: c.id, testo: c.testo}) AS commi
"""

# I vettori si leggono atto per atto, al momento di scrivere: tutti insieme
# sarebbero gigabyte.
Q_VETTORI = """
MATCH (:Norma {id: $norma})-[:HA_ARTICOLO]->(a:Articolo)
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
RETURN a.rubrica AS rubrica, a.embedding AS vettoreRubrica,
       collect({id: c.id, testo: c.testo, embedding: c.embedding}) AS commi
"""

Q_BACKUP = """
UNWIND $ids AS aid
MATCH (a:Articolo {id: aid})
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
WITH a, collect(c) AS commi
RETURN a.id AS id, properties(a) AS proprieta,
       [(x)-[r]->(a) | {tipo: type(r), da: x.id, proprieta: properties(r)}] AS entranti,
       [c IN commi | {id: c.id, numero: c.numero, testo: c.testo,
                      uscenti: [(c)-[r]->(t) | {tipo: type(r), verso: t.id, proprieta: properties(r)}],
                      entranti: [(x)-[r]->(c) WHERE type(r) <> 'HA_COMMA' |
                                 {tipo: type(r), da: x.id, proprieta: properties(r)}]}] AS commi
"""

Q_CANCELLA = """
MATCH (:Norma {id: $norma})-[:HA_ARTICOLO]->(a:Articolo)
OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
DETACH DELETE c, a
"""

Q_VETTORI_COMMI = """
UNWIND $commi AS x
MATCH (c:Comma {id: x.id})
SET c.embedding = x.embedding
"""

Q_VETTORI_ARTICOLI = """
UNWIND $articoli AS x
MATCH (a:Articolo {id: x.id})
SET a.embedding = x.embedding
"""

Q_NOVELLE = """
UNWIND $archi AS x
MATCH (c:Comma {id: x.da})
MATCH (a:Articolo {id: x.verso})
MERGE (c)-[r:CITA_ARTICOLO]->(a)
SET r += x.proprieta
"""


Q_TITOLI = """
UNWIND $articoli AS x
MATCH (a:Articolo {id: x.id})
SET a.titolo = x.titolo, a.titoloRubrica = null, a.capo = null, a.capoRubrica = null
"""


def allinea_allegati(g, caricate, scrivi):
    """Il titolo "Allegato" agli articoli d'allegato gia' ricaricati.

    La prima ricarica li aveva lasciati nel contesto del parser - l'ultimo
    Titolo della legge - e l'art. 1 del regolamento della L-84/1981 risultava
    "Titolo II". articoli.py ora li marca; qui si porta il grafo alla stessa
    lettura, senza ricaricare nulla.
    """
    articoli_aggiornati, atti = 0, 0
    for f in sorted(PARSED.glob("*.json")):
        try:
            dati = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        vecchi = dati.get("articoli") or []
        if (dati.get("id") not in caricate or dati.get("fonteParsing")
                or not any(a.get("numeroOriginale") and str(a.get("numero", "")).startswith("all")
                           for a in vecchi)):
            continue
        letti = {a["id"]: a for a in ristruttura_articoli(dati["id"], copy.deepcopy(vecchi))}
        aggiorna = []
        for a in vecchi:
            nuovo = letti.get(a["id"])
            if nuovo and nuovo.get("allegato") and (a.get("allegato") != nuovo["allegato"]
                                                    or a.get("partizioneId")):
                a["allegato"], a["partizioneId"] = nuovo["allegato"], None
                aggiorna.append({"id": a["id"], "titolo": nuovo["allegato"]})
        if not aggiorna:
            continue
        articoli_aggiornati += len(aggiorna)
        atti += 1
        if scrivi:
            g.query(Q_TITOLI, {"articoli": aggiorna})
            f.write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n    articoli d'allegato col titolo da correggere: {articoli_aggiornati:,} in {atti} atti"
          + (" - scritti" if scrivi else ""))


def coinvolto(dati):
    """Se l'atto ha articoli da separare o con lo stesso id."""
    articoli = dati.get("articoli") or []
    if not articoli or any("id" not in c for a in articoli for c in a.get("commi") or []):
        return False
    ids = [a["id"] for a in articoli]
    if len(ids) != len(set(ids)):
        return True
    nuovi = ristruttura_articoli(dati["id"], copy.deepcopy(articoli))
    return any(a["origine"] is None or a["id"] != a["origine"] for a in nuovi)


def leggi(dati):
    meta = {k: v for k, v in dati.items() if k not in STRUTTURALI}
    return parser.parse(dati["id"], meta)


def parole_perse(stato, nuovo):
    """Le parole dei commi del grafo che la lettura nuova non ha da nessuna
    parte: ne' nei commi, ne' nelle rubriche o nei titoli d'allegato, ne' nel
    preambolo. L'intestazione "Allegato A / Costituiscono violazioni..." era
    testo di un comma, e allegati.py la sposta nel titolo e nella rubrica."""
    def parole(testo):
        return collections.Counter(re.findall(r"[a-zà-ù]{4,}", (testo or "").lower()))
    prima = parole(" ".join(c["testo"] or "" for r in stato for c in r["commi"] if c["id"]))
    dopo = parole(" ".join(c["testo"] for a in nuovo["articoli"] for c in a["commi"])
                  + " " + " ".join(f'{a.get("rubrica") or ""} {a.get("allegato") or ""}'
                                   for a in nuovo["articoli"])
                  + " " + (nuovo.get("preambolo") or ""))
    # "articolo" delle intestazioni riconosciute non e' testo perso
    persi = prima - dopo
    persi.pop("articolo", None)
    return sum(persi.values()), sum(prima.values())


def main():
    scrivi = "--scrivi" in sys.argv
    g = grafo()
    caricate = {r["id"] for r in g.query("MATCH (n:Norma) WHERE n.caricata RETURN n.id AS id")}
    indicati = None
    if "--atti" in sys.argv:
        indicati = set(json.loads(Path(sys.argv[sys.argv.index("--atti") + 1]).read_text(encoding="utf-8")))

    piani, saltati, esempi = [], collections.defaultdict(list), []
    for f in sorted(PARSED.glob("*.json")):
        try:
            dati = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if dati.get("id") not in caricate or dati.get("fonteParsing"):
            continue
        if (dati["id"] not in indicati) if indicati is not None else not coinvolto(dati):
            continue
        stato = g.query(Q_STATO, {"norma": dati["id"]})
        if any(r["coordinato"] for r in stato):
            saltati["con testo coordinato"].append(dati["id"])
            continue
        nuovo = leggi(dati)
        motivo = carica.motivo_scarto(nuovo)
        if motivo:
            saltati["03 rifiuterebbe la lettura nuova"].append(f"{dati['id']} ({motivo[:40]})")
            continue
        # Gli Statuti del 1600 sono stati integrati a parte, non da 02: riletti
        # dal PDF perderebbero meta' del testo. Un atto che la lettura nuova
        # impoverisce resta com'e'. Le rubriche recuperate spostano un po' di
        # testo fuori dai commi, da qui il margine.
        prima = sum(len(re.sub(r"\s+", "", c["testo"] or "")) for r in stato for c in r["commi"] if c["id"])
        dopo = sum(len(re.sub(r"\s+", "", c["testo"])) for a in nuovo["articoli"] for c in a["commi"])
        if indicati is not None and "--testo-nuovo" in sys.argv:
            # Il PDF e' stato sostituito (21_testi_scambiati.py): il testo cambia
            # per davvero, e quello "perso" e' dell'atto sbagliato. Basta che
            # la lettura nuova non sia vuota.
            if not dopo:
                saltati["la lettura nuova e' vuota"].append(dati["id"])
                continue
        elif indicati is not None:
            persi, totale = parole_perse(stato, nuovo)
            if persi > max(3, 0.01 * totale):
                saltati["la lettura nuova perde parole del grafo"].append(f"{dati['id']} ({persi}/{totale})")
                continue
        elif dopo < 0.9 * prima:
            saltati["la lettura nuova ha meno testo del grafo"].append(f"{dati['id']} ({dopo / prima:.0%})")
            continue
        ids = [a["id"] for a in nuovo["articoli"]]
        cids = [c["id"] for a in nuovo["articoli"] for c in a["commi"]]
        if len(ids) != len(set(ids)) or len(cids) != len(set(cids)):
            saltati["id ancora ripetuti nella lettura nuova"].append(dati["id"])
            continue
        piani.append({"file": f, "dati": dati, "nuovo": nuovo, "stato": stato})

    conta = collections.Counter()
    for p in piani:
        vecchi_testi = {c["testo"] for r in p["stato"] for c in r["commi"] if c["id"]}
        nuovi_testi = [c["testo"] for a in p["nuovo"]["articoli"] for c in a["commi"]]
        conta["atti"] += 1
        conta["articoli prima (nodi)"] += len(p["stato"])
        conta["articoli dopo"] += len(p["nuovo"]["articoli"])
        conta["commi prima (nodi)"] += sum(1 for r in p["stato"] for c in r["commi"] if c["id"])
        conta["commi dopo"] += len(nuovi_testi)
        conta["commi con testo nuovo (vettore da fare)"] += sum(1 for t in nuovi_testi if t not in vecchi_testi)
        conta["testi che spariscono"] += len(vecchi_testi - set(nuovi_testi))
        vecchio_json = [(a["id"], [c["testo"] for c in a.get("commi") or []]) for a in p["dati"]["articoli"]]
        conta["JSON superato dal parser attuale"] += len({t for _, ts in vecchio_json for t in ts} - set(nuovi_testi)) > 0
        numeri = [a["numero"] for a in p["nuovo"]["articoli"]]
        conta["articoli d'allegato"] += sum(1 for n in numeri if str(n).startswith("all"))
        conta["articoli ripetuti (-rip)"] += sum(1 for n in numeri if "-rip" in str(n))
        conta["intestazioni separate"] += sum(1 for a in p["nuovo"]["articoli"] if a.get("intestazioneIncollata"))
        if len(esempi) < 5 and len(p["stato"]) != len(p["nuovo"]["articoli"]):
            esempi.append(p)
    print()
    for k, v in conta.items():
        print(f"    {k:<42} {v:>7,}")
    for k, v in saltati.items():
        print(f"    saltati, {k}: {len(v)}  {', '.join(v[:6])}")
    for p in esempi:
        print(f"\n  {p['dati']['id']}: {len(p['stato'])} nodi -> "
              f"{[a['numero'] for a in p['nuovo']['articoli']][:30]}")

    if not scrivi:
        allinea_allegati(g, caricate, False)
        print("\n  Nulla scritto. Aggiungi --scrivi --backup <file.json> per applicare.")
        return
    if not piani:
        allinea_allegati(g, caricate, True)
        return
    if "--backup" not in sys.argv:
        sys.exit("  --scrivi vuole --backup <file.json>.")
    file = Path(sys.argv[sys.argv.index("--backup") + 1])

    # Il backup va scritto tutto prima di cancellare qualunque cosa.
    copia = []
    for p in piani:
        nuovi_testi = {c["testo"] for a in p["nuovo"]["articoli"] for c in a["commi"]}
        persi = {c["id"]: c["embedding"] for r in g.query(Q_VETTORI, {"norma": p["dati"]["id"]})
                 for c in r["commi"] if c["id"] and c["testo"] not in nuovi_testi}
        righe = [dict(r) for r in g.query(Q_BACKUP, {"ids": [r["id"] for r in p["stato"]]})]
        for r in righe:
            r["proprieta"].pop("embedding", None)
            for c in r["commi"]:
                if c["id"] in persi:
                    c["embedding"] = persi[c["id"]]
        copia.append({"norma": p["dati"]["id"], "articoli": righe, "json": p["dati"]})
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(copia, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n    backup: {file} ({file.stat().st_size / 1e6:.0f} MB, {len(copia)} atti)")

    risolvi = risolutore_per_data((r["id"], r["data"]) for r in g.query(
        "MATCH (n:Norma) WHERE n.caricata RETURN n.id AS id, toString(n.data) AS data"))
    for n, (p, b) in enumerate(zip(piani, copia), 1):
        norma, nuovo = p["dati"]["id"], p["nuovo"]
        vettori = g.query(Q_VETTORI, {"norma": norma})
        vettori_commi = {c["testo"]: c["embedding"] for r in vettori for c in r["commi"]
                         if c["id"] and c["embedding"]}
        vettori_rubriche = {r["rubrica"]: r["vettoreRubrica"] for r in vettori
                            if r["rubrica"] and r["vettoreRubrica"]}
        novelle = [{"da": e["da"], "verso": r["id"], "proprieta": e["proprieta"]}
                   for r in b["articoli"] for e in r["entranti"]
                   if e["tipo"] == "CITA_ARTICOLO" and e["proprieta"].get("origine")]

        g.query(Q_CANCELLA, {"norma": norma})
        articoli, citazioni, cit_preambolo = carica.prepara(nuovo)
        if "--testo-nuovo" in sys.argv:
            # Col PDF sbagliato era sbagliato anche il preambolo, e le sue
            # citazioni: si riscrivono insieme agli articoli.
            g.query("""MATCH (n:Norma {id: $norma}) SET n.preambolo = $preambolo
                       WITH n MATCH (n)-[k:CITA {origine: 'preambolo'}]->() DELETE k""",
                    {"norma": norma, "preambolo": nuovo.get("preambolo")})
            for c in cit_preambolo:
                c["targetId"] = risolvi(c["targetId"], c["testo"])
            cit_preambolo = [c for c in cit_preambolo if c["targetId"] != norma]
            if cit_preambolo:
                g.query(carica.Q_CITAZIONI_PREAMBOLO, {"citazioni": cit_preambolo})
        for c in citazioni:
            c["targetId"] = risolvi(c["targetId"], c["testo"])
        citazioni = [c for c in citazioni if c["targetId"] != norma]
        for i in range(0, len(articoli), LOTTO):
            g.query(carica.Q_ARTICOLI, {"normaId": norma, "articoli": articoli[i:i + LOTTO]})
        for i in range(0, len(citazioni), 2000):
            g.query(carica.Q_CITAZIONI, {"citazioni": citazioni[i:i + 2000]})
        puntuali = [c for c in citazioni if c["articoloCitato"]]
        if puntuali:
            g.query(carica.Q_CITA_ARTICOLO, {"citazioni": puntuali})
        commi = [{"id": c["id"], "embedding": vettori_commi[c["testo"]]}
                 for a in nuovo["articoli"] for c in a["commi"] if c["testo"] in vettori_commi]
        for i in range(0, len(commi), LOTTO):
            g.query(Q_VETTORI_COMMI, {"commi": commi[i:i + LOTTO]})
        g.query(Q_VETTORI_ARTICOLI, {"articoli": [
            {"id": a["id"], "embedding": vettori_rubriche[a["rubrica"]]}
            for a in nuovo["articoli"] if a.get("rubrica") in vettori_rubriche]})
        if novelle:
            g.query(Q_NOVELLE, {"archi": novelle})

        p["file"].write_text(json.dumps(nuovo, ensure_ascii=False, indent=2), encoding="utf-8")
        if n % 25 == 0 or n == len(piani):
            print(f"    {n}/{len(piani)} atti")
    allinea_allegati(g, caricate, True)
    print("\n  Ora: 14_rinumera_commi.py (zero), 09 --scrivi, 08 --scrivi, 07, 07b.")


if __name__ == "__main__":
    main()
