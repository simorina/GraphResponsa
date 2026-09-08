"""
Archi di abrogazione: quali atti ne hanno abrogato un altro per intero.

Nel corpus ci sono 1.728 commi che dicono "e' abrogato" o "sono abrogati", ma
quasi nessuno e' leggibile meccanicamente senza rischio. La forma piu' comune
abroga una PARTE - "All'articolo 2 della Legge n.55/1994, il punto 8.0 e'
abrogato" - e leggerla come abrogazione dell'articolo 2 direbbe che una norma
viva e' morta. E' l'errore peggiore che questo archivio possa commettere: far
negare un diritto che esiste.

Si riconoscono percio' le sole forme che colpiscono un atto INTERO:

    "E' abrogata la Legge 27 ottobre 2004 n. 146"       (avanti)
    "La Legge n.146/2004 e' abrogata"                   (indietro)
    "Sono abrogate la Legge n.97/1989 e la Legge n.99/1991"  (plurale)

e si scarta tutto il resto: parti d'atto, decorrenze differite a date future,
clausole di salvezza. Restano 111 norme.

Non si scrive l'abrogazione di singoli ARTICOLI, che pure sarebbe misurabile
(34 archi verificati su 24 articoli): il guadagno e' minore e la granularita' e'
esattamente il punto in cui il riconoscimento sbaglia.

## La seconda fonte, indipendente dalla prima

L'archivio di Stato marca da se' gli atti caduti, premettendo "ABROGATO - " al
titolo: 125 norme. E' una fonte redazionale, non una lettura nostra, e i due
segnali sono in larga parte disgiunti - 9 norme in comune. Il titolo dice CHE un
atto e' caduto, i commi dicono DA CHI: si tengono entrambi, il flag `abrogata`
dall'unione e l'attribuzione `abrogataDa` dai soli commi. In tutto 227 norme.

## Cosa NON copre, ed e' la parte piu' grande

Non si scandagliano le 12.248 norme chiedendosi per ciascuna se sia caduta:
l'informazione non sta nella norma morta, sta nell'atto che l'ha uccisa. Restano
fuori, in ordine di frequenza:

  - l'abrogazione PARZIALE, un articolo o un comma soppressi dentro una legge
    che per il resto vive: e' il caso di gran lunga piu' frequente;
  - le forme che il riconoscimento non sa leggere, 1.578 commi su 1.728;
  - l'abrogazione TACITA, una legge posteriore incompatibile con una anteriore
    senza dirlo, che nessun metodo testuale puo' trovare.

## Il pericolo non e' l'arco sbagliato, e' l'arco assente

La copertura e' dell'1,9% delle norme. Un indice cosi' rado induce a leggere il
silenzio come conferma - "nessun arco, quindi e' in vigore" - e quel silenzio
non dimostra niente. Per questo l'informazione entra nel prompt come avviso
esclusivamente POSITIVO: la presenza dell'arco autorizza a dire "abrogata",
l'assenza non autorizza a dire "vigente".

    .venv/Scripts/python.exe src/08_abrogazioni.py           # solo misura
    .venv/Scripts/python.exe src/08_abrogazioni.py --scrivi  # scrive nel grafo
"""

import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

TIPO = (r"(legge|decreto\s+delegato|decreto\s*[-–]?\s*legge|"
        r"decreto\s+reggenziale|regolamento|decreto\s+consil\w+|decreto\s+consigl\w+)")
RIF = r"(?:n\.?\s*(\d+)\s*/\s*(\d{4})|(\d{4})\s+n\.?\s*(\d+))"
AVANTI = re.compile(
    rf"(?:è|e')\s+abrogat[ao]\s+(?:il|la|lo)?\s*{TIPO}[^;]{{0,60}}?{RIF}", re.I)
INDIETRO = re.compile(
    rf"\b(?:il|la)\s+{TIPO}[^;]{{0,60}}?{RIF}[^;]{{0,40}}?(?:è|e')\s+abrogat[ao]", re.I)

# Il plurale: "Sono abrogate la Legge 20 settembre 1989 n.97 e la Legge 25
# luglio 1991 n.99". Le due espressioni sopra sono al singolare e questa forma
# sfuggiva del tutto. Si prende la coda dopo "sono abrogati" e vi si cercano
# tutti gli atti nominati per esteso: ognuno resta poi da verificare per conto
# suo su tipo, unicita' e verso, quindi elencarne piu' d'uno non allenta nulla.
PLURALE = re.compile(r"sono\s+abrogat[ei]\b([^;]{0,240})", re.I)
UNO = re.compile(rf"\b{TIPO}[^;,]{{0,40}}?{RIF}", re.I)

# Nel plurale il bersaglio parziale non si annuncia con una parola sola: si
# scrive "Sono abrogate le DISPOSIZIONI della Legge n.78", "Sono abrogati il
# TITOLO I della Legge n.37", "i CAPI I, II e VII del Decreto n.122". La legge
# nominata sopravvive, e marcarla morta negherebbe diritti che esistono. Si
# guarda percio' il tratto che precede ogni atto elencato: se vi compare una
# parola di partizione, quell'atto e' colpito solo in parte e si scarta.
# Le due forme singolari non ne hanno bisogno - pretendono il tipo dell'atto
# subito dopo "e' abrogata la", dove una partizione non entrerebbe.
# "art." e "artt." vanno elencate a parte: gli atti abbreviano piu' spesso di
# quanto scrivano "articolo" per esteso, e cercare la sola forma lunga lasciava
# passare "Sono abrogati gli artt. 32, 33, 34 della Legge n.76/1976", che abroga
# tre articoli e non la legge.
PARTITIVO = re.compile(r"(disposizion|norm[ae]|titol[oi]|cap[oi]\b|capitol|sezion|"
                       r"parte|part[ie]\b|tabell|allegat|articol|comm[ai]|"
                       r"letter[ae]|punt[oi]|capovers|\bartt?\b)", re.I)
LOOKBACK = 45

# Il tipo dichiarato nel testo, contro il prefisso dell'id del bersaglio.
# Si confronta col prefisso e non con Norma.tipo, che e' scritto a mano e pieno
# di refusi - "Decreto Delagato", "Decreto Delega5to", "Decreto Conisliare".
# Oggi questo controllo non respinge nulla (83 coppie su 83 concordano): serve
# a impedire che, crescendo l'archivio, "Legge n.88/2003" si agganci a un
# decreto con lo stesso numero e lo stesso anno.
PREFISSO = {"legge": {"L"}, "decreto delegato": {"DD"},
            "decreto legge": {"DL", "EC"}, "decreto reggenziale": {"D"},
            "regolamento": {"R"}, "decreto consiliare": {"DC", "DD"}}

# Se compare una partizione, il bersaglio e' quella e non l'atto.
PARTE = re.compile(r"(?:articol|comm[ai]|punt[oi]|letter[ae]|capovers|allegat)", re.I)
# "Con l'entrata in vigore della presente legge" NON e' un differimento: e' la
# decorrenza ordinaria dell'atto che abroga. Lo e' una data esplicita.
DIFFERITA = re.compile(r"(a\s+decorrere\s+dal|con\s+decorrenza\s+dal\s+\d|"
                       r"con\s+efficacia\s+dal|a\s+far\s+data|abrogat\w+\s+dal\s+\d)", re.I)
# "fatti salvi gli effetti prodotti" tiene in vita una parte dell'atto.
SALVEZZA = re.compile(r"(fatt[oi]\s+salv[oi]|fatt[ae]\s+salv[ae]|salvo\s+quanto|"
                      r"salv[oi]\s+gli\s+effetti)", re.I)

# Le prove girano prima di ogni esecuzione. Tre di queste forme hanno superato
# versioni precedenti del filtro e sarebbero finite nel grafo.
PROVE = [
    ("È abrogata la Legge 27 ottobre 2004 n. 146.", 1),
    ("La Legge n.146/2004 è abrogata.", 1),
    ("Con l'entrata in vigore della presente legge è abrogata la Legge 20 novembre 1990 n.137.", 1),
    ("È abrogato l'articolo 8 della Legge n.146/2004.", 0),
    ("All’articolo 2 della Legge n.55/1994, il punto 8.0 è abrogato.", 0),
    ("Sono abrogate tutte le norme incompatibili con il presente decreto.", 0),
    ("È abrogata la Legge n.146/2004 a decorrere dal 1° gennaio 2015.", 0),
    ("È abrogato il DD 12 settembre 2019 n.139, fatti salvi gli effetti prodotti.", 0),
    ("Fatti salvi gli effetti, la Legge 8 giugno 1963 n. 35 è abrogata.", 0),
    # L'italiano degli atti scrive "e' abrogata" tanto quanto "è abrogata", e
    # l'apostrofo e' spesso quello tipografico. Ignorarlo faceva perdere 412
    # commi su 1.728 - fra cui la L-145/2022, che abroga la L-106/2009: senza
    # questa riga l'agente indicava come vigente una disciplina sostituita.
    ("E’ abrogata la Legge 31 luglio 2009 n.106, senza reviviscenza.", 1),
    ("E' abrogato il Decreto Delegato 2 agosto 2012 n.106.", 1),
    # Il plurale, che elenca piu' atti in una volta sola.
    ("Sono abrogate la Legge 20 settembre 1989 n.97 e la Legge 25 luglio 1991 n.99.", 2),
    ("Sono abrogati il Decreto Delegato 29 marzo 2024 n.80 ed il Decreto Delegato "
     "22 agosto 2024 n.133.", 2),
    ("Sono abrogate le norme in contrasto con il presente decreto delegato.", 0),
    ("Sono abrogati i commi 1 bis e 2 dell'articolo 86-bis della Legge n.140/2017.", 0),
    # Bersagli PARZIALI in forma plurale: la legge nominata sopravvive.
    ("Sono abrogate tutte le disposizioni della Legge 26 luglio 1989 n.78 in contrasto.", 0),
    ("Sono abrogati il Titolo I della Legge 30 giugno 1964 n.37.", 0),
    ("Sono abrogate le disposizioni di cui alla Legge 21 novembre 1990 n.139.", 0),
    ("Sono abrogate le sottoelencate disposizioni a decorrere dal sessantesimo giorno: "
     "Legge 12 marzo 1943 n.19.", 0),
    # La partizione in testa governa l'elenco: qui il DD n.146 cade per intero,
    # ma "i Capi I e VII" apre la frase e non c'e' modo meccanico di sapere
    # dove finisca il suo raggio. Si scarta tutto, e si perde un bersaglio buono.
    ("Sono abrogati i Capi I e VII del Decreto 22 ottobre 1985 n.122 e il Decreto "
     "Delegato 6 agosto 2010 n.146.", 0),
    # Ma una partizione a META' elenco non tocca chi la precede.
    ("Sono abrogate la Legge 13 febbraio 1980 n.10, la Legge 29 settembre 1981 "
     "n.76, il capitolo VI del Titolo VII della Legge 20 novembre 1987 n.135.", 2),
    ("Sono abrogate le disposizioni della Legge 16 maggio 1960 n. 9, della Legge "
     "27 luglio 1972 n. 24.", 0),
    # Gli atti abbreviano: "art." e "artt." valgono "articolo" quanto la forma
    # lunga, e senza di esse questi due passavano per abrogazioni totali.
    ("Sono abrogati l'art. 54 della legge 12 agosto 1946 n. 43.", 0),
    ("Sono abrogati gli artt. 32, 33, 34 della Legge 16 dicembre 1976 n.76.", 0),
]

# Le due grafie dell'apostrofo sono la stessa parola: si normalizzano prima di
# leggere, cosi' le espressioni restano scritte in un modo solo.
APOSTROFI = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})


def bersagli(testo):
    """Gli atti interi che questo comma abroga senza ambiguita'. Quasi sempre zero."""
    testo = testo.translate(APOSTROFI)
    if PARTE.search(testo) or DIFFERITA.search(testo) or SALVEZZA.search(testo):
        return []
    trovate = []
    for espressione in (AVANTI, INDIETRO):
        trovate.extend(espressione.finditer(testo))
    for coda in PLURALE.finditer(testo):
        elenco = coda.group(1)
        atti = list(UNO.finditer(elenco))
        if not atti:
            continue
        # La parola di partizione in TESTA governa tutto l'elenco che segue:
        # "le disposizioni della Legge n.9/1960, della Legge n.24/1972" colpisce
        # in parte entrambe, ma solo la prima se la vede accanto - la seconda ha
        # davanti un innocuo ", della ". Se compare prima del primo atto
        # nominato, quindi, si scarta l'elenco intero. Costa qualche bersaglio
        # buono - "i Capi I e VII del Decreto n.122 E IL Decreto Delegato
        # n.146", dove il secondo cade davvero per intero - e si paga
        # volentieri: qui un falso positivo dichiara morta una legge viva.
        if PARTITIVO.search(elenco[:atti[0].start()]):
            continue
        for m in atti:
            if PARTITIVO.search(elenco[max(0, m.start() - LOOKBACK):m.start()]):
                continue
            trovate.append(m)

    fuori = []
    for m in trovate:
        tipo, g = m.group(1), m.groups()[1:]
        numero, anno = (g[0], g[1]) if g[0] else (g[3], g[2])
        # Il tipo si normalizza qui: "Decreto - Legge" e "decreto legge" sono
        # la stessa cosa, e la grafia varia atto per atto.
        tipo = re.sub(r"\s*[-–]\s*", " ", " ".join(tipo.lower().split()))
        tipo = tipo.replace("consigliare", "consiliare")
        voce = (int(numero), int(anno), tipo)
        if voce not in fuori:
            fuori.append(voce)
    return fuori


def prova():
    esiti = [(t, atteso, len(bersagli(t))) for t, atteso in PROVE]
    for t, atteso, letto in esiti:
        print(f"    {'ok  ' if letto == atteso else 'NO  '} atteso={atteso} "
              f"letto={letto}  {t[:64]}")
    if any(letto != atteso for _, atteso, letto in esiti):
        sys.exit("\n  Il riconoscimento non e' affidabile: non scrivo nulla.")


def candidati(g):
    righe = g.query("""
        MATCH (c:Comma)
        WHERE toLower(c.testo) CONTAINS 'sono abrogat'
           OR toLower(c.testo) CONTAINS 'è abrogat'
           OR toLower(c.testo) CONTAINS "e' abrogat"
           OR toLower(c.testo) CONTAINS 'e’ abrogat'
        MATCH (c)<-[:HA_COMMA]-(:Articolo)<-[:HA_ARTICOLO]-(f:Norma)
        RETURN c.id AS comma, c.testo AS testo, f.id AS fonte, f.anno AS anno
    """)
    print(f"\n  commi abroganti nel corpus: {len(righe)}")

    trovati = []
    scarti = {"nessun bersaglio riconosciuto": 0, "bersaglio assente o ambiguo": 0,
              "abrogherebbe se stessa": 0, "bersaglio posteriore alla fonte": 0,
              "tipo dell'atto discordante": 0}
    for r in righe:
        testo = " ".join((r["testo"] or "").split())
        trovato = bersagli(testo)
        if not trovato:
            scarti["nessun bersaglio riconosciuto"] += 1
            continue
        # Ogni bersaglio nominato si verifica per conto suo. Un comma che ne
        # abroga due - "Sono abrogate la Legge n.97/1989 e la Legge n.99/1991" -
        # ne produce due, e se uno solo supera i controlli si tiene quello.
        for numero, anno, tipo in trovato:
            norme = g.query("""
                MATCH (n:Norma) WHERE n.numero = $numero AND n.anno = $anno
                RETURN n.id AS id, n.titolo AS titolo
            """, {"numero": numero, "anno": anno})
            if len(norme) != 1:
                scarti["bersaglio assente o ambiguo"] += 1
                continue
            if norme[0]["id"] == r["fonte"]:
                scarti["abrogherebbe se stessa"] += 1
                continue
            attesi = PREFISSO.get(tipo)
            if attesi and norme[0]["id"].split("-")[0] not in attesi:
                scarti["tipo dell'atto discordante"] += 1
                continue
            # Un atto non puo' abrogarne uno successivo: se il verso e'
            # invertito, il riferimento e' stato letto male e va scartato.
            if (anno or 0) > (r["anno"] or 0):
                scarti["bersaglio posteriore alla fonte"] += 1
                continue
            trovati.append({"fonte": r["fonte"], "bersaglio": norme[0]["id"],
                            "comma": r["comma"], "testo": testo,
                            "titolo": norme[0]["titolo"]})
    return trovati, scarti


def main():
    from agente.strumenti import grafo

    scrivi = "--scrivi" in sys.argv
    print("  prova del riconoscimento:")
    prova()

    g = grafo()
    trovati, scarti = candidati(g)
    for k, v in scarti.items():
        print(f"  scartati, {k:<32} {v:>5}")

    unici = {}
    for t in trovati:
        unici.setdefault((t["fonte"], t["bersaglio"]), t)
    dai_commi = {t["bersaglio"] for t in trovati}

    # "ABROGATO - Decreto Delegato..." e' la marcatura redazionale dell'archivio
    # di Stato. STARTS WITH e non CONTAINS: "referendum abrogativo" ricorre in
    # una quarantina di titoli e non significa che l'atto sia caduto.
    dal_titolo = {r["id"] for r in g.query("""
        MATCH (n:Norma) WHERE toUpper(n.titolo) STARTS WITH 'ABROGAT'
        RETURN n.id AS id
    """)}
    tutte = dai_commi | dal_titolo

    print(f"\n  coppie fonte->bersaglio: {len(unici)}")
    print(f"  abrogate secondo i commi:  {len(dai_commi):>4}")
    print(f"  abrogate secondo il titolo:{len(dal_titolo):>4}")
    print(f"  in comune:                 {len(dai_commi & dal_titolo):>4}")
    print(f"  ABROGATE IN TUTTO:         {len(tutte):>4}\n")
    for (fonte, bersaglio), t in sorted(unici.items()):
        print(f"    {fonte:<13} -> {bersaglio:<13} {(t['titolo'] or '')[:56]}")
        print(f"       {t['testo'][:110]}")

    if not scrivi:
        print("\n  Nulla scritto. Aggiungi --scrivi per applicare al grafo.")
        return

    g.query("""
        UNWIND $archi AS a
        MATCH (f:Norma {id: a.fonte}), (b:Norma {id: a.bersaglio})
        MERGE (f)-[r:ABROGA]->(b)
        SET r.comma = a.comma, r.testo = a.testo
    """, {"archi": [{"fonte": t["fonte"], "bersaglio": t["bersaglio"],
                     "comma": t["comma"], "testo": t["testo"][:400]}
                    for t in unici.values()]})

    # Le proprieta' denormalizzate servono alla lettura: le query di risalita
    # hanno gia' il nodo Norma in mano e leggerle costa zero, mentre seguire
    # l'arco costerebbe un MATCH in piu' su ogni ricerca. Si ricalcolano da capo
    # a ogni esecuzione, cosi' lo script resta idempotente.
    g.query("""MATCH (n:Norma) WHERE n.abrogata IS NOT NULL OR n.abrogataDa IS NOT NULL
               REMOVE n.abrogata, n.abrogataDa""")
    g.query("""
        UNWIND $ids AS id MATCH (n:Norma {id: id}) SET n.abrogata = true
    """, {"ids": sorted(tutte)})
    g.query("""
        MATCH (f:Norma)-[:ABROGA]->(b:Norma)
        WITH b, collect(DISTINCT f.id) AS fonti
        SET b.abrogataDa = fonti
    """)
    conferma = g.query("""
        MATCH ()-[r:ABROGA]->() WITH count(r) AS archi
        MATCH (n:Norma) WHERE n.abrogata
        RETURN archi, count(n) AS marcate,
               size([x IN collect(n) WHERE x.abrogataDa IS NOT NULL]) AS conFonte
    """)[0]
    print(f"\n  scritto: {conferma['archi']} archi ABROGA, "
          f"{conferma['marcate']} norme marcate abrogata, "
          f"{conferma['conFonte']} con l'atto abrogante")


if __name__ == "__main__":
    main()
