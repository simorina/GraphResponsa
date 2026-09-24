"""
Il riordino degli articoli di un atto, dopo che il parser li ha letti.

268 atti caricati avevano due articoli con lo stesso id. Il caricamento fa
MERGE sull'id, quindi i due articoli finivano nello stesso nodo: rubrica e
testo del secondo sopra quelli del primo, i commi dei due mescolati, e dove
anche gli id dei commi coincidevano il testo del primo era perso. Le cause:

  - l'**allegato dopo la formula di promulgazione** con una numerazione sua -
    il regolamento della L-84/1981 riparte da "Art. 1", il trattato dopo il
    decreto di ratifica pure. Gli articoli dopo la firma prendono un prefisso:
    `all-3`, e `all2-3` quando gli allegati che ripartono sono piu' d'uno
    (le reiterazioni tengono piu' decreti nello stesso PDF). E' la stessa idea
    di 13_atto_composto.py, che per gli atti che conosce usa il nome della
    sezione (`reg-15`, `tabB-1`);
  - l'**intestazione incollata in fondo a un comma**: "Comma soppresso. Art.
    2-bis (Procedura attivazione posti)" e poi 1, 2, 3. Il parser non l'aveva
    vista, e l'art. 2-bis stava dentro l'art. 2 con i suoi commi. Diventa un
    articolo;
  - il **refuso della legge**, due "Art. 9". Il secondo diventa `9-rip2`: non
    si inventa un numero che la legge non ha, ma i due articoli restano due.

Il numero che l'articolo aveva nel testo resta in `numeroOriginale`, e
03_load.py conta le ripetizioni su quello: un atto rifiutato per numerazione
patologica resta rifiutato anche se i prefissi lo rendono univoco.
"""

import re

from commi import RE_FIRMA, RE_PROMULGAZIONE, _saldo

ORDINALI = ("bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies"
            "|undecies|duodecies|terdecies|quaterdecies")
# L'intestazione chiude il comma, dopo la fine di una frase, e ha la rubrica
# fra parentesi: "...all'art. 12" in coda a una frase e' un rinvio, non un
# articolo.
RE_INCOLLATO = re.compile(
    r"(?:^|(?P<punto>[.;:])\s*)Art(?:icolo|\.)?\s*(?P<n>\d{1,3})\s*"
    r"(?:[-\s]?\s*(?P<ord>" + ORDINALI + r"))?\s*\.?\s*\((?P<rub>[^()]{2,160})\)\s*$", re.I)


def chiave(numero):
    """Come il frontend confronta i numeri d'articolo: "19 bis" = "19-bis"."""
    return re.sub(r"[\s.\-–]+", "", str(numero or "")).lower()


def _intero(numero):
    m = re.match(r"\d+", str(numero or ""))
    return int(m.group(0)) if m else None


def id_articolo(norma, numero):
    return f"{norma}/art-{str(numero).replace(' ', '-')}"


def _dividi(norma, articoli):
    """Separa gli articoli la cui intestazione e' finita in coda a un comma.

    Solo se il comma dopo riparte da 1, se l'intestazione non sta dentro una
    citazione (una novella che riporta "Art. 175 (Definizioni)" non apre un
    articolo dell'atto che la contiene) e se il numero non c'e' gia'.

    E solo se il numero e' quello dell'articolo in corso o il successivo
    ("Art. 2-bis" dentro l'art. 2, "Art. 3" dentro l'art. 2). Le intestazioni
    che il parser lascia nel testo perche' citate da una novella senza
    virgolette (02_parse.righe_citate) hanno quasi sempre un numero lontano:
    L-24-2022 riporta dall'art. 1 gli articoli 58-bis ... 58-nonies del codice
    di procedura penale, e separarli qui li rifaceva articoli della legge.
    """
    esistenti = {chiave(a["numero"]) for a in articoli}
    fuori = []
    for a in articoli:
        corrente = a
        fuori.append(corrente)
        commi = list(a.get("commi") or [])
        corrente["commi"] = []
        aperte = 0
        for k, c in enumerate(commi):
            corrente["commi"].append(c)
            testo = c["testo"]
            m = RE_INCOLLATO.search(testo)
            dopo = commi[k + 1] if k + 1 < len(commi) else None
            if (m and dopo is not None and str(dopo.get("numero")).strip() == "1"
                    and not dopo.get("commaImplicito")
                    and not _saldo(testo[:m.start()], aperte)):
                numero = m.group("n") + (f"-{m.group('ord').lower()}" if m.group("ord") else "")
                base, mio = int(m.group("n")), _intero(corrente["numero"])
                if chiave(numero) not in esistenti and (mio is None or mio <= base <= mio + 1):
                    taglio = m.start("punto") + 1 if m.group("punto") else 0
                    resto = testo[:taglio].strip()
                    if resto:
                        c["testo"] = resto
                    else:
                        corrente["commi"].pop()
                    esistenti.add(chiave(numero))
                    corrente = {"id": id_articolo(norma, numero), "numero": numero,
                                "rubrica": m.group("rub").strip(),
                                "partizioneId": a.get("partizioneId"),
                                "ordine": None, "commi": [], "citazioni": [],
                                "intestazioneIncollata": True}
                    fuori.append(corrente)
                    aperte = 0
                    continue
            aperte = _saldo(testo, aperte)
    return fuori


def _formula(articoli):
    """L'indice dell'articolo con la formula di promulgazione, se non e' l'ultimo."""
    for i, a in enumerate(articoli[:-1]):
        if any(RE_FIRMA.search(c["testo"]) for c in a.get("commi") or []):
            return i
    return None


# Un decreto di ratifica che riporta il trattato prima della firma: il
# trattato ha la sua numerazione, che riparte da "Art. 1". Misurato: 6
# documenti (X-3-1942, D-9-1972, D-28-1924, DC-16-1918, DR-12-1922,
# DC-21-1914); X-3-1942 aveva 24 articoli, uno solo suo.
RE_RATIFICA = re.compile(r"ratific|piena\s+ed?\s+intera\s+esecuzione|recepit", re.I)
RE_TRATTATO = re.compile(r"\b(?:Convenzione|Trattato|Accordo|Protocollo|"
                         r"Parti\s+contraenti|Stati\s+membri)\b")
MIN_ART_CONVENZIONE = 5


def _convenzione(articoli):
    """L'indice del primo articolo di una convenzione riportata nel dispositivo.

    Tre condizioni insieme: almeno MIN_ART_CONVENZIONE articoli, una
    numerazione che riparte da 1, e prima della ripartenza una frase di
    ratifica che nomina un trattato.
    """
    if len(articoli) < MIN_ART_CONVENZIONE:
        return None
    k = next((k for k, a in enumerate(articoli) if k and _intero(a["numero"]) == 1), None)
    if k is None:
        return None
    fra = " ".join(c["testo"] for a in articoli[:k] for c in a.get("commi") or [])
    return k if RE_RATIFICA.search(fra) and RE_TRATTATO.search(fra) else None


def _allegato_certo(articoli, firma):
    """Da quale articolo comincia un allegato, anche senza numeri ripetuti.

    Dopo la formula intera ("Dato dalla Nostra Residenza ... I CAPITANI
    REGGENTI") non c'e' piu' dispositivo: DC-52-2016 teneva i 20 articoli del
    trattato ONU come articoli del decreto, perche' "Unico" e 1...20 non si
    ripetono. Lo stesso per il trattato riportato prima della firma. Si decide
    sul testo, cosi' riapplicare il riordino (15_ricostruisci_articoli.py) da'
    lo stesso risultato.
    """
    # Nella struttura dedotta gli articoli sono raggruppati per numero, non in
    # ordine di testo: la firma in fondo al D-122-1985 sta nell'articolo "1".
    if any(a.get("strutturaDedotta") for a in articoli):
        return None
    fino = firma + 1 if firma is not None else len(articoli)
    convenzione = _convenzione(articoli[:fino])
    if convenzione is not None:
        return convenzione
    if firma is not None and any(RE_PROMULGAZIONE.search(c["testo"]) for c in articoli[firma]["commi"]):
        return firma + 1
    return None


def _qualifica(norma, articoli):
    """Numeri univoci: prefisso d'allegato dopo la firma, suffisso sui refusi."""
    firma = _formula(articoli)
    certo = _allegato_certo(articoli, firma)
    if certo is None and len({chiave(a["numero"]) for a in articoli}) == len(articoli):
        return articoli
    inizio = certo if certo is not None else (firma + 1 if firma is not None else None)
    if inizio is not None:
        prima = {chiave(a["numero"]) for a in articoli[:inizio]}
        # Le tabelle di allegati.py hanno gia' il loro numero ("all-A").
        dopo = [a for a in articoli[inizio:] if not a.get("tabella")]
        # Le sezioni dopo la firma: una nuova ogni volta che la numerazione
        # riparte o un numero si ripete.
        sezioni, sezione, visti, precedente = [], 0, set(), None
        for a in dopo:
            k, n = chiave(a["numero"]), _intero(a["numero"])
            if (not sezioni or k in visti
                    or (n is not None and precedente is not None and n <= precedente)):
                sezione += 1
                visti = set()
            visti.add(k)
            precedente = n if n is not None else precedente
            sezioni.append(sezione)
        chiavi_dopo = [chiave(a["numero"]) for a in dopo]
        collide = (any(k in prima for k in chiavi_dopo)
                   or len(set(zip(sezioni, chiavi_dopo))) != len(set(chiavi_dopo)))
        if collide or certo is not None:
            for a, s in zip(dopo, sezioni):
                prefisso = "all" if sezione == 1 else f"all{s}"
                a["numeroOriginale"] = a.get("numeroOriginale") or a["numero"]
                a["numero"] = f"{prefisso}-{a['numero']}"
                # L'articolo d'allegato non sta nell'ultimo Titolo della legge:
                # col contesto del parser l'art. 1 del regolamento della
                # L-84/1981 risultava "Titolo II", e l'agente contava undici
                # allegati dove c'era un regolamento di undici articoli.
                a["allegato"] = "Allegato" if sezione == 1 else f"Allegato {s}"
                a["partizioneId"] = None
    visti = {}
    for a in articoli:
        k = chiave(a["numero"])
        visti[k] = visti.get(k, 0) + 1
        if visti[k] > 1:
            a["numeroOriginale"] = a.get("numeroOriginale") or a["numero"]
            a["numero"] = f"{a['numero']}-rip{visti[k]}"
            visti[chiave(a["numero"])] = 1
    return articoli


def ristruttura_articoli(norma, articoli):
    """Riordina gli articoli dell'atto. Restituisce la lista nuova.

    Ogni articolo porta `origine`, l'id che aveva prima (None per quelli nati
    da un'intestazione incollata), per chi deve ricostruire i nodi nel grafo.
    Gli id dei commi si ricalcolano dopo, con commi.ristruttura.
    """
    lavoro = [dict(a, origine=a.get("origine", a.get("id")), commi=[dict(c) for c in a.get("commi") or []])
              for a in articoli]
    # Riapplicata ad articoli gia' riordinati riparte dai numeri del testo.
    for a in lavoro:
        if a.get("numeroOriginale"):
            a["numero"] = a.pop("numeroOriginale")
    divisi = _dividi(norma, lavoro)
    for a in divisi:
        a.setdefault("origine", None)
    qualificati = _qualifica(norma, divisi)
    for i, a in enumerate(qualificati):
        a["id"] = id_articolo(norma, a["numero"])
        a["ordine"] = i
    return qualificati
