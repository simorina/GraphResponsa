"""
13 - Ricarica un atto che contiene piu' testi con numerazioni proprie.

La Legge 29 ottobre 1981 n.85 "sulle imposte di registro e relativo
regolamento" tiene nello stesso PDF la legge (artt. 1-76), la Tabella A delle
tariffe, la Tabella B (artt. 1-4), la Tabella C (art. 1) e il Regolamento di
applicazione (artt. 1-19). Il parser la legge come un testo solo:

  - i numeri 1-4 ricorrono quattro volte, e 03_load.py la rifiuta come
    "numerazione patologica" - il presidio giusto contro gli Allegati letti
    come corpo, che qui pero' scarta un atto sano;
  - le firme, la Tabella A e la Tabella B finiscono in un secondo comma
    dell'art. 76 di 11.000 caratteri.

Nel grafo la L-85/1981 era cosi' uno stub: 104 commi la citano, e nessuno dei
suoi articoli si poteva leggere.

Questo script divide il PDF nelle sue sezioni, fa leggere ciascuna al parser
di 02 e ne qualifica gli articoli: "reg-1" e' l'art. 1 del Regolamento, "tabB-1"
l'art. 1 della Tabella B. La sezione di provenienza va anche in Articolo.titolo,
cosi' l'agente vede "Regolamento di applicazione" accanto all'articolo.

La Tabella A resta fuori: nel PDF e' una tabella a quattro colonne, e il testo
estratto le alterna riga per riga ("1 Vendite, cessioni, Al n.1 - Le impo-").
Nell'indice diventerebbe testo senza senso ma cercabile, e il grafo non tiene
testo che produce citazioni plausibili e false.

Lo stesso vale per la Legge 22 dicembre 1972 n.41, la legge organica per i
dipendenti dello Stato: artt. 1-108 e, dietro, gli Allegati B, C, E e H con
numerazione propria ("allB-1", ...). Gli Allegati A e F restano fuori: il primo
il PDF non lo contiene, il secondo e' una tabella a colonne.

Uso:
    .venv/Scripts/python.exe src/13_atto_composto.py                      # solo misura
    .venv/Scripts/python.exe src/13_atto_composto.py --scrivi             # JSON e grafo
    .venv/Scripts/python.exe src/13_atto_composto.py L-41-1972 --scrivi   # un atto solo

E' idempotente: il JSON si rigenera dal PDF e il caricamento usa MERGE.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def _modulo(nome, file):
    spec = importlib.util.spec_from_file_location(nome, RADICE / "src" / file)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


parser = _modulo("parse02", "02_parse.py")
carica = _modulo("load03", "03_load.py")

PARSED = RADICE / "data" / "parsed"
RAW = RADICE / "data" / "raw"

# Le sezioni si riconoscono dalla riga che le apre. "fine_legge" chiude il
# corpo della legge sulla formula di promulgazione: dopo vengono le firme e la
# Tabella A.
ATTI = {
    "L-85-1981": {
        "fine_legge": re.compile(r"^\s*Data(ta)? dalla Nostra Residenza", re.I),
        "sezioni": [
            {"apertura": re.compile(r'^\s*TABELLA\s+"A"', re.I), "prefisso": None,
             "motivo": "tabella a colonne: il testo estratto alterna le colonne riga per riga"},
            {"apertura": re.compile(r'^\s*TABELLA\s+"B"', re.I), "prefisso": "tabB",
             "tipo": "Tabella", "numero": "B",
             "rubrica": "Imposta di registro sui trasferimenti di veicoli"},
            {"apertura": re.compile(r'^\s*TABELLA\s+"C"', re.I), "prefisso": "tabC",
             "tipo": "Tabella", "numero": "C", "rubrica": "Diritti erariali"},
            {"apertura": re.compile(r"^\s*REGOLAMENTO PER L.APPLICAZIONE", re.I), "prefisso": "reg",
             "tipo": "Regolamento", "numero": "di applicazione",
             "rubrica": "Regolamento per l'applicazione della legge sulle imposte di registro"},
        ],
    },
    # La legge organica per i dipendenti dello Stato: artt. 1-108, poi sei
    # Allegati, quattro dei quali ricominciano da "Art. 1". Citata dalla
    # raccolta coordinata sul Lavoro.
    "L-41-1972": {
        "fine_legge": re.compile(r"^\s*Data(ta)? dalla Nostra Residenza", re.I),
        "sezioni": [
            {"apertura": re.compile(r'^\s*ALLEGATO\s+"A"\s*$', re.I), "prefisso": None,
             "motivo": "sei avvertenze e le tavole dei concorsi, che il PDF stesso non riporta "
                       "(\"Testo da pag. 107 a pag. 147 B.U. 1972 n 6 non inserito\")"},
            {"apertura": re.compile(r"^\s*ALLEGATO\s+B\s*-", re.I), "prefisso": "allB",
             "tipo": "Allegato", "numero": "B",
             "rubrica": "Norme per la tenuta del fascicolo personale dei dipendenti"},
            {"apertura": re.compile(r"^\s*ALLEGATO\s+C\s*-", re.I), "prefisso": "allC",
             "tipo": "Allegato", "numero": "C", "rubrica": "Norme che regolano i concorsi"},
            {"apertura": re.compile(r"^\s*ALLEGATO\s+E\s*-", re.I), "prefisso": "allE",
             "tipo": "Allegato", "numero": "E",
             "rubrica": "Calendario degli uffici ed orario di servizio"},
            {"apertura": re.compile(r'^\s*ALLEGATO\s+"F"\s*$', re.I), "prefisso": None,
             "motivo": "tabella fuori organico a colonne: qualifiche e importi alternati riga per riga"},
            {"apertura": re.compile(r"^\s*ALLEGATO\s+H\s*-", re.I), "prefisso": "allH",
             "tipo": "Allegato", "numero": "H",
             "rubrica": "Regolamento per la disciplina dei diritti sindacali sanciti dalla legge organica"},
        ],
    },
}


def dividi(righe, conf):
    """Le righe del PDF per sezione: la legge, poi una lista per sezione."""
    inizi = []
    for s in conf["sezioni"]:
        i = next((k for k, r in enumerate(righe) if s["apertura"].match(r)), None)
        assert i is not None, f"sezione non trovata: {s['apertura'].pattern}"
        inizi.append(i)
    assert inizi == sorted(inizi), "le sezioni non sono nell'ordine atteso"
    fine = next(k for k, r in enumerate(righe[:inizi[0]]) if conf["fine_legge"].match(r))
    legge = righe[:fine]
    pezzi = []
    for n, (s, i) in enumerate(zip(conf["sezioni"], inizi)):
        stop = inizi[n + 1] if n + 1 < len(inizi) else len(righe)
        # L'ultima sezione della L-41/1972 chiude con una seconda formula di
        # promulgazione e le firme: senza il taglio finivano nell'art. 9
        # dell'Allegato H.
        stop = next((k for k in range(i + 1, stop) if conf["fine_legge"].match(righe[k])), stop)
        # La prima riga e' l'intestazione (a volte su due righe): il parser
        # la tratterebbe da preambolo, e va bene cosi'.
        pezzi.append((s, righe[i:stop]))
    return legge, pezzi


RE_SOLO_ANNO = re.compile(r"^\s*\d{4}\.?\s*$")
RE_ART_RICHIAMO = re.compile(r"^(\s*Art\.?\s*\d+)\s*\(\*\)\s*$")


def riattacca_anni(righe):
    """Un anno andato a capo da solo torna alla riga che lo precede.

    "...entra in vigore il 1° gennaio / 1982." - per il parser "1982." e' il
    numero di un comma nuovo, e l'art. 76 finiva monco con un comma vuoto
    "c-1982" dietro. Nessun comma ha un numero di quattro cifre.
    """
    fuori = []
    for r in righe:
        if RE_SOLO_ANNO.match(r) and fuori and fuori[-1].strip():
            fuori[-1] = fuori[-1].rstrip() + " " + r.strip()
        else:
            fuori.append(r)
    return fuori


def leggi_con(righe, norma, meta):
    """Il parser di 02 su un tratto di righe invece che sull'intero PDF."""
    originale = parser.righe_pdf
    parser.righe_pdf = lambda _percorso: righe
    try:
        return parser.parse(norma, meta)
    finally:
        parser.righe_pdf = originale


def qualifica(articoli, norma, sezione, partizione_id):
    """Numeri e id resi univoci dentro l'atto: "reg-1", ".../art-reg-1/c-1"."""
    for a in articoli:
        numero = f"{sezione['prefisso']}-{a['numero']}"
        vecchio = a["id"]
        a["numero"] = numero
        a["id"] = f"{norma}/art-{numero}"
        a["partizioneId"] = partizione_id
        # Il suffisso del comma resta quello del parser (commi.ristruttura):
        # cambia solo l'articolo, cosi' capoversi e punti tengono il loro nome.
        for c in a["commi"]:
            c["id"] = a["id"] + c["id"][len(vecchio):]
        # Le citazioni portano l'id del comma: si ricalcolano sugli id nuovi
        # con la stessa funzione del parser.
        a["citazioni"] = []
        for c in a["commi"]:
            for cit in parser.estrai_citazioni(c["testo"], norma):
                cit["commaId"] = c["id"]
                cit["commaOrigine"] = c["numero"]
                a["citazioni"].append(cit)
    return articoli


def ricostruisci(norma, conf):
    vecchio = json.loads((PARSED / f"{norma}.json").read_text(encoding="utf-8"))
    meta = {k: v for k, v in vecchio.items()
            if k not in ("preambolo", "citazioniPreambolo", "partizioni", "articoli")}
    # "Art. 94 (*)": col richiamo il parser non riconosce l'intestazione, e
    # l'art. 94 della L-41/1972 spariva dentro il 93.
    righe = [RE_ART_RICHIAMO.sub(r"\1", r)
             for r in riattacca_anni(parser.righe_pdf(RAW / norma / "testo.pdf"))]
    legge, pezzi = dividi(righe, conf)

    dati = leggi_con(legge, norma, meta)
    articoli = list(dati["articoli"])
    partizioni = list(dati["partizioni"])
    esclusi = []
    for s, tratto in pezzi:
        if s["prefisso"] is None:
            esclusi.append({"sezione": tratto[0].strip(), "righe": len(tratto), "motivo": s["motivo"]})
            continue
        pid = f"{norma}/{s['prefisso']}"
        partizioni.append({"id": pid, "tipo": s["tipo"], "numero": s["numero"],
                           "rubrica": s["rubrica"], "ordine": len(partizioni), "figli": []})
        articoli += qualifica(leggi_con(tratto, norma, meta)["articoli"], norma, s, pid)
    for i, a in enumerate(articoli):
        a["ordine"] = i
    return {**dati, "partizioni": partizioni, "articoli": articoli,
            "fonteParsing": "13_atto_composto.py", "sezioniEscluse": esclusi}, vecchio


def carica_norma(dati):
    """Il caricamento di 03 ristretto a una norma: stesse query, stesso ordine."""
    from agente.strumenti import grafo

    motivo = carica.motivo_scarto(dati)
    assert motivo is None, f"03_load la rifiuterebbe ancora: {motivo}"
    g = grafo()
    articoli, citazioni, preambolo = carica.prepara(dati)
    etichetta = carica.norma_label(dati.get("tipo"))
    imposta = f"SET n:`{etichetta}`" if etichetta and etichetta != "Norma" else ""
    g.query(f"""
        MERGE (n:Norma {{id: $id}})
        {imposta}
        SET n.tipo = $tipo, n.numero = $numero, n.anno = $anno,
            n.data = CASE WHEN $data IS NULL THEN NULL ELSE date($data) END, n.titolo = $titolo,
            n.dataPubblicazione = CASE WHEN $dataPubblicazione IS NULL THEN NULL ELSE date($dataPubblicazione) END,
            n.dataEntrataVigore  = CASE WHEN $dataEntrataVigore  IS NULL THEN NULL ELSE date($dataEntrataVigore)  END,
            n.urlScheda = $urlScheda, n.urlDocumento = $urlDocumento,
            n.preambolo = $preambolo,
            n.caricata = true
    """, {k: dati.get(k) for k in ["id", "tipo", "numero", "anno", "data", "titolo",
                                   "dataPubblicazione", "dataEntrataVigore",
                                   "urlScheda", "urlDocumento", "preambolo"]})
    g.query(carica.Q_ARTICOLI, {"normaId": dati["id"], "articoli": articoli})
    if citazioni:
        g.query(carica.Q_CITAZIONI, {"citazioni": citazioni})
    if preambolo:
        g.query(carica.Q_CITAZIONI_PREAMBOLO, {"citazioni": preambolo})
    puntuali = [c for c in citazioni if c["articoloCitato"]]
    if puntuali:
        g.query(carica.Q_CITA_ARTICOLO, {"citazioni": puntuali})
    return g.query("""
        MATCH (n:Norma {id: $id})-[:HA_ARTICOLO]->(a)
        OPTIONAL MATCH (a)-[:HA_COMMA]->(c)
        RETURN count(DISTINCT a) AS articoli, count(DISTINCT c) AS commi,
               COUNT { (n)<-[:CITA]-() } AS citataDa""", {"id": dati["id"]})[0]


def main():
    scrivi = "--scrivi" in sys.argv
    scelte = [a for a in sys.argv[1:] if not a.startswith("--")]
    for norma, conf in ATTI.items():
        if scelte and norma not in scelte:
            continue
        dati, vecchio = ricostruisci(norma, conf)
        print(f"\n  {norma} - {dati.get('titolo')}")
        print(f"    prima: {len(vecchio['articoli'])} articoli, rifiutata da 03: "
              f"{carica.motivo_scarto(vecchio) is not None}")
        per_sezione = {}
        for a in dati["articoli"]:
            per_sezione.setdefault(a.get("partizioneId") or "legge", []).append(a)
        for sezione, arts in per_sezione.items():
            lunghi = [a["numero"] for a in arts if max((len(c["testo"]) for c in a["commi"]), default=0) > 3000]
            print(f"    {sezione}: {len(arts)} articoli ({arts[0]['numero']} .. {arts[-1]['numero']}), "
                  f"{sum(len(a['commi']) for a in arts)} commi"
                  + (f" | ! commi oltre 3000 caratteri in {', '.join(lunghi)}" if lunghi else ""))
        for e in dati["sezioniEscluse"]:
            print(f"    esclusa: {e['sezione']} ({e['righe']} righe) - {e['motivo']}")
        print(f"    03 la rifiuterebbe ancora: {carica.motivo_scarto(dati) or 'no'}")
        # La coda di ogni sezione e' dove finiscono firme e tabelle della
        # sezione dopo: e' la prima cosa da guardare.
        for sezione, arts in per_sezione.items():
            coda = arts[-1]["commi"][-1]["testo"] if arts[-1]["commi"] else ""
            print(f"    fine {sezione} (art. {arts[-1]['numero']}): ...{coda[-160:]}")

        if not scrivi:
            continue
        (PARSED / f"{norma}.json").write_text(json.dumps(dati, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
        print(f"    scritto data/parsed/{norma}.json")
        print(f"    nel grafo: {carica_norma(dati)}")

    if not scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi per rigenerare il JSON e caricare.")
    else:
        print("\n  Ora: 09_riallinea_citazioni.py --scrivi, 08_abrogazioni.py --scrivi, 07_embeddings.py.")


if __name__ == "__main__":
    main()
