"""
20 - Tre pulizie sul grafo esistente, con le regole che 03 e 09 applicano ora.

  1. **Citazioni verso l'atto del tipo sbagliato.** Il testo chiama un atto con
     un tipo e l'archivio lo cataloga con un altro: "Decreto Reggenziale 1°
     settembre 2003 n.113" e' in archivio come D-113-2003. L'arco finiva su un
     atto inesistente (DR-113-2003) che l'agente non poteva aprire. Il 17/09
     erano 1.305 citazioni verso 523 atti fantasma con un omonimo caricato; 794
     avevano la stessa data dell'omonimo. Si spostano sull'atto giusto
     (comune.risolutore_per_data), con l'arco all'articolo quando c'e', e gli
     atti fantasma rimasti senza archi si tolgono. L'arco ricorda l'id da cui
     veniva (`risoltoDa`).
  2. **Titoli letti con la codifica sbagliata.** "NÂ° 27", "1Â° luglio": 269
     titoli, e un comma (comune.ripara_mojibake).
  3. **Date segnaposto.** "1200-01-01" dove la data non era nota, "0006-01-11"
     con l'anno troncato: 31 atti (comune.data_pulita).

Un comma che cambia testo ha i frammenti da rifare: dopo --scrivi eseguire
19_frammenti.py. I cambiamenti si salvano prima in un file di backup.

Uso:
    .venv/Scripts/python.exe src/20_pulizia_grafo.py
    .venv/Scripts/python.exe src/20_pulizia_grafo.py --scrivi --backup <file.json>
"""

import json
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from comune import data_pulita, ripara_mojibake, risolutore_per_data  # noqa: E402

Q_ARCHI_FANTASMA = """
MATCH (x)-[k:CITA]->(s:Norma)
WHERE NOT coalesce(s.caricata, false)
  AND EXISTS { MATCH (c:Norma) WHERE c.caricata AND c.numero = s.numero AND c.anno = s.anno }
OPTIONAL MATCH (f:Norma)-[:HA_ARTICOLO]->(:Articolo)-[:HA_COMMA]->(x)
RETURN elementId(k) AS arco, elementId(x) AS sorgente, x:Comma AS daComma, s.id AS fantasma,
       coalesce(f.id, x.id) AS fonte, properties(k) AS proprieta
"""

Q_SPOSTA = """
UNWIND $archi AS a
MATCH (x)-[k:CITA]->(s:Norma) WHERE elementId(k) = a.arco
MATCH (c:Norma {id: a.giusto})
MERGE (x)-[nuovo:CITA]->(c)
  ON CREATE SET nuovo = a.proprieta, nuovo.risoltoDa = s.id
DELETE k
WITH x, c, a
WHERE a.daComma AND a.proprieta.articoloCitato IS NOT NULL
MATCH (c)-[:HA_ARTICOLO]->(art:Articolo {numero: a.proprieta.articoloCitato})
MERGE (x)-[:CITA_ARTICOLO]->(art)
"""

Q_FANTASMI_ISOLATI = """
UNWIND $ids AS i
MATCH (s:Norma {id: i}) WHERE NOT coalesce(s.caricata, false) AND NOT (s)--()
DELETE s
RETURN count(*) AS tolti
"""


def main():
    from agente.strumenti import grafo

    scrivi = "--scrivi" in sys.argv
    g = grafo()

    # 1. citazioni
    risolvi = risolutore_per_data((r["id"], r["data"]) for r in g.query(
        "MATCH (n:Norma) WHERE n.caricata RETURN n.id AS id, toString(n.data) AS data"))
    archi = g.query(Q_ARCHI_FANTASMA)
    spostati = []
    for a in archi:
        giusto = risolvi(a["fantasma"], a["proprieta"].get("testoCitazione"))
        if giusto != a["fantasma"] and giusto != a["fonte"]:
            spostati.append({**a, "giusto": giusto})
    print(f"  citazioni verso atti fantasma con un omonimo caricato: {len(archi)}")
    print(f"  da spostare (stessa data, un solo candidato): {len(spostati)}")
    for a in spostati[:6]:
        print(f"    {a['fantasma']:<13} -> {a['giusto']:<13} {a['proprieta'].get('testoCitazione')}")

    # L'atto che nomina se stesso con un altro tipo: la prima pulizia, il
    # 17/09, lo aveva risolto come citazione di se stesso (87 archi).
    autocitazioni = g.query("""
        MATCH (f:Norma)-[:HA_ARTICOLO]->(:Articolo)-[:HA_COMMA]->(:Comma)-[k:CITA]->(f)
        RETURN elementId(k) AS arco, f.id AS atto""") + g.query("""
        MATCH (f:Norma)-[k:CITA]->(f) RETURN elementId(k) AS arco, f.id AS atto""")
    print(f"  autocitazioni da togliere: {len(autocitazioni)}")

    # 2. titoli, rubriche, commi
    titoli = [{"id": r["id"], "prima": r["t"], "dopo": ripara_mojibake(r["t"])} for r in g.query(
        "MATCH (n:Norma) WHERE n.titolo CONTAINS 'Â' OR n.titolo CONTAINS 'Ã' RETURN n.id AS id, n.titolo AS t")]
    titoli = [t for t in titoli if t["prima"] != t["dopo"]]
    rubriche = [{"id": r["id"], "prima": r["t"], "dopo": ripara_mojibake(r["t"])} for r in g.query(
        "MATCH (a:Articolo) WHERE a.rubrica CONTAINS 'Â' OR a.rubrica CONTAINS 'Ã' RETURN a.id AS id, a.rubrica AS t")]
    rubriche = [t for t in rubriche if t["prima"] != t["dopo"]]
    commi = [{"id": r["id"], "prima": r["t"], "dopo": ripara_mojibake(r["t"])} for r in g.query(
        "MATCH (c:Comma) WHERE c.testo =~ '(?s).*(Ã.|Â.).*' RETURN c.id AS id, c.testo AS t")]
    commi = [t for t in commi if t["prima"] != t["dopo"]]
    print(f"\n  titoli da riparare: {len(titoli)}, rubriche: {len(rubriche)}, commi: {len(commi)}")
    for t in titoli[:3]:
        print(f"    {t['id']:<13} {t['dopo'][:80]}")

    # 3. date
    date = []
    for r in g.query("""MATCH (n:Norma) WHERE n.data IS NOT NULL AND n.data.year < 1500
                        RETURN n.id AS id, toString(n.data) AS data, n.anno AS anno"""):
        date.append({"id": r["id"], "prima": r["data"], "dopo": data_pulita(r["data"], r["anno"])})
    print(f"\n  date da correggere: {len(date)} "
          f"({sum(1 for d in date if d['dopo'])} completate, {sum(1 for d in date if not d['dopo'])} tolte)")
    for d in date[:4]:
        print(f"    {d['id']:<20} {d['prima']} -> {d['dopo']}")

    if not scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi --backup <file.json> per applicare.")
        return
    if "--backup" not in sys.argv:
        sys.exit("  --scrivi vuole --backup <file.json>.")
    Path(sys.argv[sys.argv.index("--backup") + 1]).write_text(json.dumps(
        {"citazioni": spostati, "autocitazioni": autocitazioni, "titoli": titoli, "rubriche": rubriche, "commi": commi, "date": date},
        ensure_ascii=False, default=str), encoding="utf-8")

    for i in range(0, len(spostati), 500):
        g.query(Q_SPOSTA, {"archi": [{"arco": a["arco"], "giusto": a["giusto"], "daComma": a["daComma"],
                                      "proprieta": a["proprieta"]} for a in spostati[i:i + 500]]})
    g.query("UNWIND $a AS e MATCH ()-[k:CITA]->() WHERE elementId(k) = e DELETE k",
            {"a": [x["arco"] for x in autocitazioni]})
    tolti = g.query(Q_FANTASMI_ISOLATI, {"ids": sorted({a["fantasma"] for a in spostati})})[0]["tolti"]
    print(f"\n  spostate {len(spostati)} citazioni, tolti {tolti} atti fantasma rimasti isolati")
    g.query("UNWIND $x AS t MATCH (n:Norma {id: t.id}) SET n.titolo = t.dopo", {"x": titoli})
    g.query("UNWIND $x AS t MATCH (a:Articolo {id: t.id}) SET a.rubrica = t.dopo", {"x": rubriche})
    g.query("UNWIND $x AS t MATCH (c:Comma {id: t.id}) SET c.testo = t.dopo", {"x": commi})
    g.query("""UNWIND $x AS d MATCH (n:Norma {id: d.id})
               SET n.data = CASE WHEN d.dopo IS NULL THEN NULL ELSE date(d.dopo) END""", {"x": date})
    print(f"  riparati {len(titoli)} titoli, {len(rubriche)} rubriche, {len(commi)} commi; corrette {len(date)} date")
    if commi:
        print("  Esegui 19_frammenti.py --scrivi: i commi cambiati hanno i frammenti da rifare.")


if __name__ == "__main__":
    main()
