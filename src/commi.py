"""
Il riordino dei commi di un articolo, dopo che il parser li ha letti.

Quattromila articoli uscivano dal parser con due commi dello stesso numero. Non
era un difetto solo:

  - la **rubrica letta come comma**. "Art. 12 / Denuncia / 1. Il presente
    Protocollo..." - una rubrica senza parentesi e senza punto finale finiva nel
    testo come comma implicito "1", seguito dal vero comma 1;
  - il **numero di pagina** rimasto solo su una riga, diventato un comma "5";
  - il **testo citato da una novella** ("l'articolo 3-bis e' cosi' sostituito:
    “1. ... 2. ...”"), i cui commi ripartivano da 1. Diventano **capoversi** del
    comma che li introduce: `1.cap2` e' il comma 1, capoverso 2;
  - l'**elenco numerato** dentro un comma ("posizionati in modo da essere: 1.
    ... 2. ..."), letto come commi. Diventano **punti**: `1.p2`;
  - la **coda dopo la formula di promulgazione**: l'allegato in fondo all'ultimo
    articolo, con la sua numerazione. Diventa **parte d'allegato**: `all3`.

Capoversi, punti e parti d'allegato portano `parte` ("capoverso", "punto",
"allegato") e `numeroOriginale`, il numero che avevano nel testo. Il testo non
cambia mai: cambiano numero e id.

La funzione e' una sola e la usano 02_parse.py, perche' un caricamento nuovo
nasca giusto, e 14_rinumera_commi.py, che porta il grafo esistente allo stesso
stato. Se divergessero, ricaricare un atto cambierebbe gli id dei suoi commi.

Cio' che resta con numeri doppi - refusi della legge, firme di trattati,
tabelle - resta com'e', marcato `numerazioneAnomala`.
"""

import re

# Il verbo con cui una novella annuncia il testo che segue.
RE_INTRO = re.compile(
    r"(?:\bseguent[ei]\b|\bcome\s+segue\b|\bche\s+segue\b"
    r"|cos[iì]['’]?\s+(?:sostituit|modificat|riformulat|integrat|formulat)"
    r"|sostituit[oa]\s+(?:dal|con)\b"
    r"|\b(?:è|e['’]|sono|viene|vengono)\s+(?:aggiunt|inserit|introdott|premess)"
    r"|seguente\s+tenore)", re.I)
RE_FIRMA = re.compile(r"\bDat[oa]\s+dalla\s+Nostra\s+Residenza", re.I)
# Dove un trattato non ha la formula: le firme delle parti e poi "Allegato
# Esproprio", o il testo inglese che comincia con "Article 1".
RE_ALLEGATO_IN_CODA = re.compile(r"\bAllegat[oi]\b[^.;:]{0,80}$|\bArticle\s+1\b")
RE_DUE_PUNTI = re.compile(r":\s*\d{0,3}\s*$")
RE_SOLO_NUMERO = re.compile(r"\d{1,4}")
RE_VOCE_ELENCO = re.compile(r"^\s*(?:[a-z]\)|[a-z]\.\s|\d+\)|[-•])", re.I)
LUNGHEZZA_RUBRICA = 120
LUNGHEZZA_CITAZIONE = 60


def _saldo(testo, aperte):
    """Le virgolette aperte dopo questo testo, partendo da `aperte`.

    Le tipografiche si contano; le dritte non dicono se aprono o chiudono, e
    ognuna rovescia lo stato. Alcuni PDF rendono “ ” come ― ‖, altri scrivono
    due apostrofi al posto delle virgolette doppie.
    """
    for ch in testo.replace("''", '"'):
        if ch in "“«―":
            aperte += 1
        elif ch in "”»‖":
            aperte = max(aperte - 1, 0)
        elif ch == '"':
            aperte = aperte - 1 if aperte else 1
    return aperte


def _intero(numero):
    m = re.match(r"\d+", str(numero or ""))
    return int(m.group(0)) if m else None


def _e_rubrica(primo, secondo):
    """Il primo comma e' una rubrica rimasta nel testo.

    Solo nella forma che il parser produce: un comma implicito, corto, senza
    punteggiatura finale, seguito da un comma numerato 1. Un articolo di una
    frase finisce col punto, e resta testo.
    """
    testo = primo["testo"].strip()
    return (primo.get("commaImplicito") and not secondo.get("commaImplicito")
            and str(secondo["numero"]) == "1"
            and len(testo) <= LUNGHEZZA_RUBRICA and re.search(r"[A-Za-zÀ-ÿ]{3}", testo)
            and not re.search(r"[.;:,]\s*$", testo)
            and not RE_INTRO.search(testo) and _saldo(testo, 0) == 0
            and not RE_VOCE_ELENCO.match(testo))


def _inizio_coda(commi):
    """Dove comincia l'allegato: dopo il comma con la formula di promulgazione.

    Solo se dopo quel comma ci sono altri commi. Il comma con la formula resta
    com'e' - di solito e' l'ultimo, e non c'e' nulla da fare. Senza formula
    valgono "Allegato ..." in coda al comma o l'"Article 1" di un testo
    inglese, ma solo se il comma dopo riparte da 1.
    """
    for k, c in enumerate(commi[:-1]):
        if RE_FIRMA.search(c["testo"]):
            return k + 1
        if (RE_ALLEGATO_IN_CODA.search(c["testo"]) and not commi[k + 1].get("commaImplicito")
                and str(commi[k + 1]["numero"]).strip() == "1"):
            return k + 1
    return None


RE_ORDINALE = re.compile(r"^(\d+)\s*[-\s]?\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies)$", re.I)


def _fine_senza_chiusura(commi, i):
    """Dove finisce un testo citato che non richiude le virgolette.

    E' la sequenza 1, 2, 3... (con i -bis in mezzo) che segue chi lo
    introduce. Vale solo se arriva in fondo all'articolo, o se subito dopo
    riprende la numerazione dei commi veri: altrimenti non si sa dove finisca.
    """
    mio = _intero(commi[i]["numero"])
    atteso, j, ultimo = _intero(commi[i + 1]["numero"]), i + 1, None
    while j < len(commi) and not commi[j].get("commaImplicito") and atteso is not None:
        numero = str(commi[j]["numero"]).strip()
        m = RE_ORDINALE.match(numero)
        if numero == str(atteso):
            atteso += 1
        elif not (m and int(m.group(1)) == atteso - 1):
            break
        ultimo, j = j, j + 1
    if ultimo is None:
        return None
    if j == len(commi) or _intero(commi[j]["numero"]) == mio + 1:
        return ultimo
    return None


def _blocchi_citati(commi):
    """Posizione -> posizione del comma che introduce il testo citato.

    Un blocco comincia dopo un comma che lascia aperte le virgolette e annuncia
    la novella - o comincia con le virgolette, quando l'annuncio e' finito
    nella rubrica ("“Art. 120 bis (Norme di coordinamento)"). Finisce sul comma
    che le richiude tutte: un comma che chiude una citazione e ne apre un'altra
    ("...”; “Art. 54") non la interrompe. Senza chiusura vale la numerazione
    (_fine_senza_chiusura). La numerazione del blocco deve comunque ripartire -
    il primo comma citato non supera chi lo introduce - perche' un numero
    doppio e' meglio di un comma vero scambiato per testo citato.
    """
    blocchi, i = {}, 0
    while i < len(commi) - 1:
        testo = commi[i]["testo"]
        aperte = _saldo(testo, 0)
        mio, primo = _intero(commi[i]["numero"]), _intero(commi[i + 1]["numero"])
        annuncia = (RE_INTRO.search(testo) or testo.lstrip()[:1] in "“«\"―"
                    or testo.lstrip().startswith("''"))
        if (aperte and annuncia and mio is not None
                and primo is not None and primo <= mio):
            fine = None
            for j in range(i + 1, min(len(commi), i + 1 + LUNGHEZZA_CITAZIONE)):
                aperte = _saldo(commi[j]["testo"], aperte)
                if not aperte:
                    fine = j
                    break
            if fine is None:
                fine = _fine_senza_chiusura(commi, i)
            if fine is not None:
                for j in range(i + 1, fine + 1):
                    blocchi[j] = i
                i = fine + 1
                continue
        i += 1
    return blocchi


def _elenchi(commi, occupati):
    """Posizione -> posizione del comma che apre un elenco numerato.

    L'elenco segue un comma che finisce coi due punti (magari seguiti dal
    numero di pagina), parte da 1 e prosegue di uno in uno. Finisce quando la
    numerazione si rompe, oppure su una voce chiusa dal punto se il comma dopo
    riprende la numerazione dei commi. Una voce che finisce coi due punti apre
    un altro elenco dello stesso comma, e i punti proseguono.
    """
    elenchi = {}
    for i, c in enumerate(commi[:-1]):
        if i in occupati or not RE_DUE_PUNTI.search(c["testo"]):
            continue
        radice = elenchi.get(i, i)
        mio = _intero(commi[radice]["numero"])
        if mio is None:
            continue
        atteso, k = 1, i + 1
        while (k < len(commi) and k not in occupati and not commi[k].get("commaImplicito")
               and str(commi[k]["numero"]).strip() == str(atteso)):
            elenchi[k] = radice
            chiusa = commi[k]["testo"].rstrip().endswith(".")
            if chiusa and k + 1 < len(commi) and _intero(commi[k + 1]["numero"]) == mio + 1:
                break
            atteso += 1
            k += 1
    return elenchi


def ristruttura(articolo):
    """Riordina i commi dell'articolo, in place. Restituisce l'articolo.

    Ogni comma porta `origine`: l'id che aveva prima, per chi deve rinominare
    i nodi nel grafo.
    """
    commi = [dict(c, origine=c.get("origine", c.get("id"))) for c in articolo.get("commi") or []]
    # Riapplicata a commi gia' riordinati, riparte dai numeri del testo: le
    # parti si ricalcolano con le stesse regole, e il risultato non cambia.
    for c in commi:
        if c.get("parte"):
            c["numero"] = c.get("numeroOriginale") or c["numero"]
            c["parte"] = None

    # "sanzione da L.10" / "00 0 a L.50" - un importo spezzato dall'estrazione:
    # la riga "00 0" e' diventata un comma "0", che nessuna legge numera. Il
    # frammento torna in coda al comma da cui viene.
    uniti = []
    for c in commi:
        if uniti and not c.get("commaImplicito") and str(c["numero"]).strip() == "0":
            padre = uniti[-1]
            padre["testo"] = f"{padre['testo']} {c['testo']}".strip()
            padre["assorbiti"] = padre.get("assorbiti", []) + [c["origine"]] + c.get("assorbiti", [])
        else:
            uniti.append(c)
    commi = uniti

    if len(commi) > 1:
        tenuti = [c for c in commi if not RE_SOLO_NUMERO.fullmatch(c["testo"].strip())]
        commi = tenuti or commi

    if (len(commi) > 1 and not (articolo.get("rubrica") or "").strip()
            and _e_rubrica(commi[0], commi[1])):
        articolo["rubrica"] = commi[0]["testo"].strip()
        commi = commi[1:]

    coda = _inizio_coda(commi)
    corpo = commi[:coda] if coda is not None else commi
    blocchi = _blocchi_citati(corpo)
    elenchi = _elenchi(corpo, set(blocchi) | set(blocchi.values()))

    fuori, usati, precedente, propri = [], set(), None, 0
    ripetuti = {}
    progressivo_parte, parte_precedente, allegato = 0, None, 0
    for k, c in enumerate(commi):
        nuovo = {"testo": c["testo"], "origine": c["origine"], "commaImplicito": False,
                 "numerazioneAnomala": False, "numeroOriginale": str(c["numero"])}
        if c.get("assorbiti"):
            nuovo["assorbiti"] = c["assorbiti"]
        if coda is not None and k >= coda:
            allegato += 1
            nuovo.update(numero=f"all{allegato}", parte="allegato")
            base = f"{articolo['id']}/c-all{allegato}"
        elif k in blocchi or k in elenchi:
            padre = blocchi.get(k, elenchi.get(k))
            parte, sigla = ("capoverso", "cap") if k in blocchi else ("punto", "p")
            progressivo_parte = progressivo_parte + 1 if parte_precedente == (padre, parte) else 1
            parte_precedente = (padre, parte)
            numero_padre = fuori[padre]["numero"]
            nuovo.update(numero=f"{numero_padre}.{sigla}{progressivo_parte}", parte=parte)
            base = f"{articolo['id']}/c-{numero_padre}-{sigla}{progressivo_parte}"
        else:
            propri += 1
            implicito = bool(c.get("commaImplicito"))
            numero = str(propri) if implicito else str(c["numero"])
            anomalo = False
            if precedente is not None and not implicito:
                try:
                    anomalo = not int(numero) > int(precedente)
                except ValueError:
                    anomalo = False
            precedente = numero
            ripetuti[numero] = ripetuti.get(numero, 0) + 1
            if ripetuti[numero] > 1:
                # Ultima risorsa: il refuso della legge stessa, o una forma che
                # nessuna regola riconosce. Il secondo comma "1" resta un comma,
                # col suo nome: "1.rip2", il secondo comma numerato 1.
                nuovo.update(numero=f"{numero}.rip{ripetuti[numero]}", parte="ripetizione",
                             numeroOriginale=numero, commaImplicito=False,
                             numerazioneAnomala=True)
            else:
                nuovo.update(numero=numero, parte=None, numeroOriginale=None,
                             commaImplicito=implicito, numerazioneAnomala=anomalo)
            base = f"{articolo['id']}/c-{nuovo['numero'].replace('.', '-')}"
        cid, n = base, 1
        while cid in usati:
            n += 1
            cid = f"{base}-{n}"
        usati.add(cid)
        nuovo["id"] = cid
        fuori.append(nuovo)
    articolo["commi"] = fuori
    return articolo
