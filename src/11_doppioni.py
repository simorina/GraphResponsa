"""
11 - Toglie dal grafo gli atti schedati due volte dal portale.

L'archivio pubblica lo stesso atto sotto due schede distinte, con due URL di
documento diversi. Il caricamento le tiene entrambe - non puo' sapere che sono
la stessa cosa - qualificando la seconda con il proprio schedaId: 'L-17-1974'
e 'L-17-1974~17011720'. Il risultato e' un atto che nel grafo esiste due volte,
compete con se stesso nel recupero e produce risposte con l'id qualificato al
posto di quello canonico. E' successo davvero: interrogato sul Codice Penale
l'agente ha risposto che "ci sono due versioni del Codice Penale in archivio".

## Perche' non basta guardare il testo

Il separatore '~' non segnala un doppione: segnala una COLLISIONE su
(tipo, numero, anno), e la stragrande maggioranza delle collisioni sono atti
davvero distinti - i decreti ottocenteschi senza numero (D-0-1910 sono 21
decreti diversi del 1910), le errata corrige che non hanno numero affatto
(EC-None-2024 sono 19 correzioni ad atti diversi). Cancellarli sarebbe perdere
normativa.

Nemmeno il testo identico basta, e tre trappole lo dimostrano:

  - **gli atti senza testo collidono tutti**: l'impronta della stringa vuota
    e' la stessa per tutti, e D-0-1889 "sui cani" finiva appaiato a
    "sull'astensione dal voto del consigliere". Da qui la soglia sui caratteri;
  - **ratifica ed esecuzione hanno lo stesso corpo**: D-0-1906 esiste in due
    decreti pari pari, uno che ratifica la convenzione e uno che la esegue;
  - **l'atto ratificato e il ratificante pure**: 'DD-52-2022~17176152' si
    intitola "Decreto - Legge 23 marzo 2022 n.53", che e' un ALTRO atto.
    Stesso corpo, numero diverso. Sono quattro casi cosi', e senza il
    controllo sul numero se ne andrebbero nel mucchio.

## La regola

Un gruppo e' un doppione quando tutte e tre le condizioni tengono:

  1. testo integrale identico e di almeno 400 caratteri;
  2. stesso numero di articoli;
  3. o i titoli coincidono, oppure nessun titolo nomina un atto DIVERSO da
     quello del nodo. Un titolo che si limita a richiamare i propri estremi
     ("Legge 25 febbraio 1974 n.17") non distingue nulla ed e' compatibile con
     un titolo descrittivo ("emanazione del nuovo codice penale").

Si tiene sempre la scheda con l'id canonico, quella senza '~': e' l'unica a cui
le citazioni arrivano - misurato, le schede qualificate ne ricevono ZERO - e
quella che gli id nelle risposte devono nominare.

Uso:
    .venv/Scripts/python.exe src/11_doppioni.py             # solo misura
    .venv/Scripts/python.exe src/11_doppioni.py --scrivi    # cancella

Dopo la cancellazione va rieseguito 08_abrogazioni.py, che ricalcola gli archi
ABROGA da capo.
"""

import argparse
import collections
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_neo4j import Neo4jGraph

sys.path.insert(0, str(Path(__file__).parent))
from comune import SEPARATORE_COLLISIONE  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
ELENCO = RADICE / "out" / "doppioni_rimossi.json"

# Sotto questa lunghezza il testo non identifica l'atto: gli atti privi di
# corpo hanno tutti la stessa impronta e finirebbero appaiati fra loro.
MIN_TESTO = 400

MESI = ("gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto"
        "|settembre|ottobre|novembre|dicembre")
# Un riferimento ad atto dentro il titolo: "Legge 21 dicembre 2009 N.168",
# "Decreto Delegato 03/11/2020 n.194", "LEGGE 25 MAGGIO 2004 N. 69".
RE_RIFERIMENTO = re.compile(
    r"(?:(\d{1,2}\s+(?:" + MESI + r")\s+(\d{4}))|(\d{1,2}/\d{1,2}/(\d{4})))"
    r"[^0-9]{0,12}?n\.?\s*(\d+)", re.I)


def impronta(commi):
    """L'impronta del contenuto, indipendente dall'ordine di raccolta.

    `collect()` non garantisce un ordine, e due schede con lo STESSO testo
    producevano impronte diverse: le due schede del Codice Penale, 187.183
    caratteri identici a testa, non si riconoscevano. Si ordina prima.
    """
    testo = " ".join(sorted(c or "" for c in commi))
    return hashlib.md5(re.sub(r"\W+", "", testo.lower()).encode()).hexdigest()


def lunghezza(commi):
    return len(re.sub(r"\W+", "", " ".join(c or "" for c in commi)))


def titolo_normale(titolo):
    return re.sub(r"\W+", "", (titolo or "").lower())


def nomina_altro_atto(titolo, numero, anno):
    """Se il titolo richiama un atto che non e' quello del nodo.

    E' il controllo che salva i casi in cui l'archivio scheda sotto lo stesso
    corpo l'atto ratificato e quello che lo ratifica: il titolo di
    'DD-52-2022~17176152' dice "Decreto - Legge 23 marzo 2022 n.53", e n.53 non
    e' n.52. Senza, si cancellerebbe un atto vero.
    """
    for m in RE_RIFERIMENTO.finditer(titolo or ""):
        suo_anno = m.group(2) or m.group(4)
        if str(numero) != m.group(5) or str(anno) != suo_anno:
            return True
    return False


def titolo_utile(titolo, numero, anno):
    """Il titolo privato del richiamo dell'atto a se stesso.

    "Legge 25 febbraio 1974 n.17" non dice nulla che l'id non dica gia', e
    resta compatibile con qualunque titolo descrittivo dello stesso atto: e'
    cosi' che le due schede del Codice Penale si riconoscono per una cosa
    sola. Cio' che avanza, invece, DEVE combaciare.
    """
    testo = titolo or ""
    for m in reversed(list(RE_RIFERIMENTO.finditer(testo))):
        if m.group(5) == str(numero) and (m.group(2) or m.group(4)) == str(anno):
            testo = testo[:m.start()] + testo[m.end():]
    testo = re.sub(r"^\W*(legge|decreto(?:\s*[-–]?\s*\w+)?|regolamento)\b", "",
                   testo, flags=re.I)
    return re.sub(r"\W+", "", testo.lower())


# Un titolo che si annuncia come errata corrige o come allegato descrive un
# documento DIVERSO dall'atto, anche quando l'archivio gli ha caricato dentro
# lo stesso testo: la correzione e l'allegato hanno una vita propria e vanno
# raggiunti per conto loro.
RE_ALTRO_DOCUMENTO = re.compile(r"\b(errata\s*corrige|allegato\s+al)\b", re.I)


def specie_diversa(membri):
    marcati = [bool(RE_ALTRO_DOCUMENTO.search(x["titolo"] or "")) for x in membri]
    return any(marcati) and not all(marcati)


def titoli_compatibili(membri):
    """Se i titoli possono descrivere lo stesso atto.

    Non e' pignoleria. Fra le schede in collisione ce ne sono con lo STESSO
    testo e titoli inconciliabili - 'D-19-1960' si chiama "apertura della
    caccia" e nel corpo ha il decreto sui francobolli, che e' il titolo della
    sua gemella. Li' il difetto non e' il doppione: e' che a uno dei due atti
    e' stato caricato il testo dell'altro, e cancellarne uno distruggerebbe
    l'unica copia buona del suo contenuto.

    Si accetta quindi solo se, tolto il richiamo agli estremi, un titolo e'
    contenuto nell'altro - oppure se non ne resta niente.
    """
    utili = [titolo_utile(x["titolo"], x["numero"], x["anno"]) for x in membri]
    for a in utili:
        for b in utili:
            if a and b and a not in b and b not in a:
                return False
    return True


def famiglie(g):
    """Le schede raggruppate per id canonico, con testo e titolo."""
    righe = g.query("""
        MATCH (n:Norma)
        WHERE n.id CONTAINS $sep
           OR EXISTS { MATCH (m:Norma) WHERE m.id STARTS WITH n.id + $sep }
        OPTIONAL MATCH (n)-[:HA_ARTICOLO]->(a:Articolo)-[:HA_COMMA]->(c:Comma)
        WITH n, count(DISTINCT a) AS articoli, collect(c.testo) AS testi
        OPTIONAL MATCH (n)<-[cit:CITA]-()
        RETURN n.id AS id, coalesce(n.titolo, "") AS titolo,
               n.numero AS numero, n.anno AS anno,
               articoli, size(testi) AS commi, testi, count(cit) AS citata
    """, {"sep": SEPARATORE_COLLISIONE})
    fuori = collections.defaultdict(list)
    for r in righe:
        fuori[r["id"].split(SEPARATORE_COLLISIONE)[0]].append(r)
    return fuori


def doppioni(g):
    gruppi = []
    for base, membri in famiglie(g).items():
        per_contenuto = collections.defaultdict(list)
        for x in membri:
            if lunghezza(x["testi"]) < MIN_TESTO:
                continue
            per_contenuto[(impronta(x["testi"]), x["articoli"])].append(x)
        for v in per_contenuto.values():
            if len(v) < 2:
                continue
            titoli = {titolo_normale(x["titolo"]) for x in v}
            if len(titoli) > 1:
                if any(nomina_altro_atto(x["titolo"], x["numero"], x["anno"])
                       for x in v):
                    continue
                if specie_diversa(v) or not titoli_compatibili(v):
                    continue
            # Si tiene il canonico; dove non c'e' si tiene il primo per id, ma
            # e' un caso che nel corpus non ricorre e vale la pena saperlo.
            v.sort(key=lambda x: (SEPARATORE_COLLISIONE in x["id"], x["id"]))
            # Se la scheda che si tiene non ha un titolo che dica qualcosa -
            # 'L-0-1913' si chiama "Legge" e basta - lo si prende da quella che
            # si butta, che invece lo ha ("per causa di pubblica utilita'").
            # Altrimenti la pulizia costerebbe l'unica descrizione dell'atto.
            titolo = None
            if not titolo_utile(v[0]["titolo"], v[0]["numero"], v[0]["anno"]):
                migliori = [x["titolo"] for x in v[1:]
                            if titolo_utile(x["titolo"], x["numero"], x["anno"])]
                titolo = migliori[0] if migliori else None
            gruppi.append({"base": base, "tiene": v[0], "butta": v[1:],
                           "titoloDaRiportare": titolo})
    return sorted(gruppi, key=lambda x: -x["tiene"]["articoli"])


def testi_scambiati(g):
    """Schede con lo stesso testo e titoli che non possono descriverlo entrambi.

    Non sono doppioni: sono atti DIVERSI a uno dei quali e' stato caricato il
    testo dell'altro. 'L-0-1910' si intitola "dei cadaveri" e ha 97 articoli
    identici a quelli di "sulle scuole elementari". Le due schede hanno URL
    diversi sul portale, ma il PDF che se ne scarica e' lo stesso file, byte
    per byte: il guasto sta a monte del caricamento.

    Non si aggiusta da qui - non c'e' modo di sapere quale dei due titoli
    appartenga al testo senza riaprire il portale - ma va detto, perche' e'
    peggio di un doppione: uno dei due atti nel grafo e' una risposta
    sbagliata che si presenta come giusta.
    """
    fuori = []
    for base, membri in famiglie(g).items():
        per_contenuto = collections.defaultdict(list)
        for x in membri:
            if lunghezza(x["testi"]) < MIN_TESTO:
                continue
            per_contenuto[(impronta(x["testi"]), x["articoli"])].append(x)
        for v in per_contenuto.values():
            if len(v) < 2 or len({titolo_normale(x["titolo"]) for x in v}) == 1:
                continue
            if any(nomina_altro_atto(x["titolo"], x["numero"], x["anno"]) for x in v):
                continue
            if not specie_diversa(v) and not titoli_compatibili(v):
                fuori.append(v)
    return sorted(fuori, key=lambda v: -v[0]["articoli"])


def grafo():
    load_dotenv(RADICE / ".env")
    return Neo4jGraph(url=os.environ["NEO4J_URI"],
                      username=os.environ["NEO4J_USERNAME"],
                      password=os.environ["NEO4J_PASSWORD"],
                      database=os.getenv("NEO4J_DATABASE", "neo4j"),
                      refresh_schema=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scrivi", action="store_true")
    args = ap.parse_args()

    g = grafo()
    gruppi = doppioni(g)
    da_togliere = [x for gr in gruppi for x in gr["butta"]]
    print(f"\n  doppioni: {len(gruppi)} gruppi, {len(da_togliere)} schede da togliere")
    print(f"  articoli {sum(x['articoli'] for x in da_togliere):,}"
          f" | commi {sum(x['commi'] for x in da_togliere):,}")

    citate = [x for x in da_togliere if x["citata"]]
    print(f"  fra queste, con citazioni in entrata: {len(citate)}"
          f"{' -> ' + ', '.join(x['id'] for x in citate) if citate else ''}")
    senza_canonico = [gr for gr in gruppi
                      if SEPARATORE_COLLISIONE in gr["tiene"]["id"]]
    if senza_canonico:
        print(f"  gruppi senza id canonico: {len(senza_canonico)}"
              f" -> {', '.join(gr['tiene']['id'] for gr in senza_canonico)}")
    print()
    for gr in gruppi:
        print(f"  art={gr['tiene']['articoli']:<4} {gr['tiene']['titolo'][:56]}")
        print(f"       TIENE  {gr['tiene']['id']:<26} citata={gr['tiene']['citata']}")
        for x in gr["butta"]:
            print(f"       butta  {x['id']:<26} citata={x['citata']}  {x['titolo'][:38]}")
        if gr["titoloDaRiportare"]:
            print(f"       titolo riportato sul nodo tenuto: "
                  f"{gr['titoloDaRiportare'][:56]!r}")

    scambiati = testi_scambiati(g)
    if scambiati:
        print(f"\n  NON sono doppioni ma un guasto peggiore: {len(scambiati)} gruppi"
              f" ({sum(len(v) for v in scambiati)} schede) hanno lo stesso testo e"
              f" titoli inconciliabili.\n  A uno dei due atti e' stato caricato il"
              f" testo dell'altro, e da qui non si sa quale.")
        for v in scambiati[:12]:
            print(f"    art={v[0]['articoli']:<4} " + " | ".join(
                f"{x['id']}: {x['titolo'][:30]}" for x in v))
        if len(scambiati) > 12:
            print(f"    ... e altri {len(scambiati) - 12}")

    if not args.scrivi:
        print("\n  Nulla cancellato. Aggiungi --scrivi per applicare al grafo.")
        return

    # L'elenco si scrive PRIMA di cancellare: se qualcosa andasse storto, o se
    # a mente fredda un atto risultasse cancellato a torto, questo file e' cio'
    # che resta per ritrovarlo sul portale.
    ELENCO.parent.mkdir(parents=True, exist_ok=True)
    ELENCO.write_text(json.dumps(
        [{k: x[k] for k in ("id", "titolo", "articoli", "commi", "citata")}
         | {"tenuto": gr["tiene"]["id"]}
         for gr in gruppi for x in gr["butta"]],
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  elenco di cio' che sparisce in {ELENCO.relative_to(RADICE)}")

    riporti = [{"id": gr["tiene"]["id"], "titolo": gr["titoloDaRiportare"]}
               for gr in gruppi if gr["titoloDaRiportare"]]
    if riporti:
        g.query("UNWIND $r AS x MATCH (n:Norma {id: x.id}) SET n.titolo = x.titolo",
                {"r": riporti})
        print(f"  titoli riportati sulla scheda tenuta: {len(riporti)}")

    ids = [x["id"] for x in da_togliere]
    prima = g.query("MATCH (n) RETURN count(n) AS n")[0]["n"]
    g.query("""
        UNWIND $ids AS id
        MATCH (n:Norma {id: id})
        OPTIONAL MATCH (n)-[:HA_ARTICOLO]->(a:Articolo)
        OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
        DETACH DELETE c, a, n
    """, {"ids": ids})
    dopo = g.query("MATCH (n) RETURN count(n) AS n")[0]["n"]
    print(f"  nodi nel grafo: {prima:,} -> {dopo:,}  ({prima - dopo:,} rimossi)")
    rimasti = g.query(
        "UNWIND $ids AS id MATCH (n:Norma {id: id}) RETURN count(n) AS n",
        {"ids": ids})[0]["n"]
    print(f"  schede ancora presenti fra quelle da togliere: {rimasti}")
    print("\n  Ora: 08_abrogazioni.py --scrivi (ricalcola gli archi ABROGA).")


if __name__ == "__main__":
    main()
