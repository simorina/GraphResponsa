"""
Definizioni condivise dalla pipeline.

L'identificativo di una norma dipende dal suo tipo, e il tipo arriva da una
stringa libera scritta nella scheda del portale. Tenere questa mappa in un solo
posto evita che i vari script derivino id diversi per la stessa norma.
"""

import re

# L'archivio non usa solo le etichette del menu a tendina: la L.140/2017 e'
# schedata come "Legge ordinaria", che nel dropdown non compare affatto.
PREFISSI = {
    "legge": "L",
    "legge ordinaria": "L",
    "legge costituzionale": "LC",
    "legge qualificata": "LQ",
    "legge di revisione costituzionale": "LRC",
    "legge revisione costituzionale": "LRC",
    "decreto": "D",
    "decreto delegato": "DD",
    "decreto legge": "DL",
    "decreto-legge": "DL",
    "decreto - legge": "DL",
    "decreto -legge": "DL",
    "decreto- legge": "DL",
    "decreto reggenziale": "DR",
    "decreto consiliare": "DC",
    "decreto consigliare": "DC",
    "decreto conisliare": "DC",
    "decreto delagato": "DD",
    "decreto delega5to": "DD",
    "decreto - legga": "DL",
    "legge orginaria": "L",
    "regolamento": "R",
    "notifica": "N",
    "statuto": "S",
    "ordinanza": "O",
    "verbale": "V",
    "errata corrige": "EC",
}

LABELS = {
    "legge": "Legge",
    "legge ordinaria": "Legge",
    "legge orginaria": "Legge",
    "legge costituzionale": "LeggeCostituzionale",
    "legge qualificata": "LeggeQualificata",
    "legge di revisione costituzionale": "LeggeRevisioneCostituzionale",
    "legge revisione costituzionale": "LeggeRevisioneCostituzionale",
    "decreto": "Decreto",
    "decreto delegato": "DecretoDelegato",
    "decreto delagato": "DecretoDelegato",
    "decreto delega5to": "DecretoDelegato",
    "decreto legge": "DecretoLegge",
    "decreto-legge": "DecretoLegge",
    "decreto - legge": "DecretoLegge",
    "decreto -legge": "DecretoLegge",
    "decreto- legge": "DecretoLegge",
    "decreto - legga": "DecretoLegge",
    "decreto reggenziale": "DecretoReggenziale",
    "decreto consiliare": "DecretoConsiliare",
    "decreto consigliare": "DecretoConsiliare",
    "decreto conisliare": "DecretoConsiliare",
    "regolamento": "Regolamento",
    "notifica": "Notifica",
    "statuto": "Statuto",
    "ordinanza": "Ordinanza",
    "verbale": "Verbale",
    "errata corrige": "ErrataCorrige",
}

tipi_ignoti = set()

# Tipo+numero+anno non e' una chiave: l'archivio numera uguale atti distinti
# (e ogni Errata Corrige eredita gli estremi dell'atto che corregge). Quando
# due schede collidono, la prima tiene l'id piano e la seconda lo qualifica
# con il proprio schedaId. Cosi' nessun id gia' assegnato cambia, e le
# citazioni - che si risolvono per tipo/numero/anno - continuano a puntare
# all'atto canonico.
SEPARATORE_COLLISIONE = "~"


def id_canonico(id_norma):
    """
    'D-66-1983~17012616' -> 'D-66-1983'.

    Serve a chi deve risalire dall'id qualificato a quello che le citazioni
    nominano.
    """
    return (id_norma or "").split(SEPARATORE_COLLISIONE, 1)[0]


def id_qualificato(id_norma, scheda_id):
    """Aggiunge lo schedaId a un id conteso."""
    return f"{id_canonico(id_norma)}{SEPARATORE_COLLISIONE}{scheda_id}"


ANNO_MINIMO = 1600
ANNO_MASSIMO = 2100


def normalizza_estremi(numero, anno, data=None):
    """
    Rimette a posto numero e anno quando la scheda del portale li confonde.

    Due guasti osservati sull'archivio reale:

      - **invertiti**: la scheda di DD n.9 del 2007 riporta numero=2007 e
        anno=9. Senza correzione nasce l'id 'DD-2007-9', che nessuna citazione
        potra' mai agganciare, e l'ordinamento per anno lo mette nell'anno 9.
      - **anno assente**: anno=0 oppure vuoto, mentre la data completa c'e'.

    Restituisce (numero, anno) come interi dove possibile, altrimenti li
    lascia come sono: meglio un dato grezzo che un dato inventato.
    """
    def intero(v):
        try:
            return int(str(v).strip())
        except (TypeError, ValueError):
            return None

    def plausibile(y):
        return y is not None and ANNO_MINIMO <= y <= ANNO_MASSIMO

    n, a = intero(numero), intero(anno)
    anno_data = intero(str(data)[:4]) if data else None

    # Invertiti: l'anno e' finito nel numero. Il numero "sembra un anno" o
    # perche' lo e', o perche' e' vicinissimo alla data della scheda - e'
    # cosi' che si riconosce il refuso 2208 al posto di 2008.
    if not plausibile(a) and n is not None:
        sembra_anno = plausibile(n) or (
            anno_data is not None and 1000 <= n <= 2999 and abs(n - anno_data) <= 300)
        if sembra_anno:
            n, a = a, n

    # Anno ancora inservibile: lo si prende dalla data, il dato piu' solido
    # che la scheda offre.
    if not plausibile(a) and anno_data is not None:
        a = anno_data

    return (n if n is not None else numero, a if a is not None else anno)


def norma_id(tipo, numero, anno):
    """
    Costruisce l'id di una norma, es. "L-87-2026", "DD-120-2026", "DL-88-2026".

    Un tipo sconosciuto produrrebbe id 'X-...' silenziosi che non combaciano
    con quelli dedotti dalle citazioni, lasciando stub orfani accanto alle
    norme caricate. Meglio dirlo subito.
    """
    chiave = (tipo or "").strip().lower()
    chiave = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u00ad\uff0d\x96\ufffd–—−]", "-", chiave)
    chiave = re.sub(r"\s+", " ", chiave)
    chiave = re.sub(r"\s*-\s*", "-", chiave)
    prefisso = PREFISSI.get(chiave) or PREFISSI.get(chiave.replace("-", " "))
    if prefisso is None and "decreto" in chiave and ("legge" in chiave or "legga" in chiave):
        prefisso = "DL"
    elif prefisso is None and "decreto" in chiave and ("consiliare" in chiave or "consigliare" in chiave or "conisliare" in chiave):
        prefisso = "DC"
    elif prefisso is None and "decreto" in chiave and ("delegato" in chiave or "delagato" in chiave or "delega" in chiave):
        prefisso = "DD"
    elif prefisso is None and "decreto" in chiave and "reggenziale" in chiave:
        prefisso = "DR"
    elif prefisso is None and ("legge" in chiave or "ordinaria" in chiave):
        prefisso = "L"
    elif prefisso is None and ("decreto" in chiave or "decreti" in chiave):
        prefisso = "D"
    elif prefisso is None:
        if tipo not in tipi_ignoti:
            tipi_ignoti.add(tipo)
            print(f"    ATTENZIONE: tipo di norma non riconosciuto: {tipo!r} "
                  f"-> uso il prefisso 'X'. Aggiungerlo a comune.PREFISSI.")
        prefisso = "X"
    return f"{prefisso}-{numero}-{anno}"


def norma_label(tipo):
    """
    Restituisce l'etichetta Cypher specifica per il tipo di norma
    (es. 'Legge', 'DecretoDelegato', 'DecretoLegge', ecc.).
    """
    chiave = (tipo or "").strip().lower()
    chiave = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u00ad\uff0d\x96\ufffd–—−]", "-", chiave)
    chiave = re.sub(r"\s+", " ", chiave)
    chiave = re.sub(r"\s*-\s*", "-", chiave)
    lbl = LABELS.get(chiave) or LABELS.get(chiave.replace("-", " "))
    if not lbl and "decreto" in chiave and ("legge" in chiave or "legga" in chiave):
        lbl = "DecretoLegge"
    elif not lbl and "decreto" in chiave and ("consiliare" in chiave or "consigliare" in chiave or "conisliare" in chiave):
        lbl = "DecretoConsiliare"
    elif not lbl and "decreto" in chiave and ("delegato" in chiave or "delagato" in chiave or "delega" in chiave):
        lbl = "DecretoDelegato"
    elif not lbl and "decreto" in chiave and "reggenziale" in chiave:
        lbl = "DecretoReggenziale"
    elif not lbl and ("decreto" in chiave or "decreti" in chiave):
        lbl = "Decreto"
    elif not lbl and ("legge" in chiave or "ordinaria" in chiave):
        lbl = "Legge"
    if not lbl:
        pulito = re.sub(r"[^a-zA-Z0-9]", "", (tipo or "").title())
        lbl = pulito if pulito else None
    return lbl
