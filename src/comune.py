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
    "legge costituzionale": "LeggeCostituzionale",
    "legge qualificata": "LeggeQualificata",
    "legge di revisione costituzionale": "LeggeRevisioneCostituzionale",
    "legge revisione costituzionale": "LeggeRevisioneCostituzionale",
    "decreto": "Decreto",
    "decreto delegato": "DecretoDelegato",
    "decreto legge": "DecretoLegge",
    "decreto-legge": "DecretoLegge",
    "decreto - legge": "DecretoLegge",
    "decreto -legge": "DecretoLegge",
    "decreto- legge": "DecretoLegge",
    "decreto reggenziale": "DecretoReggenziale",
    "decreto consiliare": "DecretoConsiliare",
    "regolamento": "Regolamento",
    "notifica": "Notifica",
    "statuto": "Statuto",
    "ordinanza": "Ordinanza",
    "verbale": "Verbale",
    "errata corrige": "ErrataCorrige",
}

tipi_ignoti = set()


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
    if prefisso is None and "decreto" in chiave and "legge" in chiave:
        prefisso = "DL"
    elif prefisso is None and "decreto" in chiave and "delegato" in chiave:
        prefisso = "DD"
    elif prefisso is None and "decreto" in chiave and "reggenziale" in chiave:
        prefisso = "DR"
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
    if not lbl and "decreto" in chiave and "legge" in chiave:
        lbl = "DecretoLegge"
    elif not lbl and "decreto" in chiave and "delegato" in chiave:
        lbl = "DecretoDelegato"
    elif not lbl and "decreto" in chiave and "reggenziale" in chiave:
        lbl = "DecretoReggenziale"
    if not lbl:
        pulito = re.sub(r"[^a-zA-Z0-9]", "", (tipo or "").title())
        lbl = pulito if pulito else None
    return lbl
