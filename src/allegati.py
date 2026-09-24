"""
Gli allegati che sono tabelle, non articoli.

I decreti annuali sulle violazioni amministrative (33 atti, dal 1991 al 2016)
hanno sei articoli e, dopo la firma, le tabelle delle infrazioni: un allegato
per autorita' competente ("Allegato A / Costituiscono violazioni
amministrative, di competenza del Commissario della Legge...") e in ciascuno
le voci numerate:

    16) Legge 28 maggio 1881
        (Stampa)
        artt. 2, 3, 4, 24, 28 e 34
        sanzione di € 20,00

Il riconoscitore degli articoli leggeva "art. 166" e "artt. 2, 3" come
intestazioni: DD-149-2016 usciva con 524 articoli invece di 6, "art. 3"
ripetuto ventotto volte, e 03_load.py lo rifiutava per numerazione
patologica; otto decreti piu' vecchi, sotto la soglia, erano caricati con
articoli come `all1-3`. Qui, quando gli allegati di un atto hanno la
numerazione di una tabella di rimandi, si rileggono le righe dopo la firma:
ogni allegato diventa un articolo `all-A`, `all-B`..., ogni voce un comma col
suo numero.

La voce che non nomina l'atto a cui si riferisce vale per l'ultimo nominato:
"Legge 25 febbraio 1974, n. 17 (Codice Penale)" copre le voci da 1 a 15. Il
comma lo porta davanti fra quadre, perche' la ricerca e le citazioni sappiano
di quale "art. 184" si parla. E' l'unica cosa che nel testo della voce non
c'e'.

Lo stesso modulo dice a 03_load.py quando la numerazione di un atto non e'
credibile: gli allegati con una numerazione propria (convenzioni, testi
unici, reiterazioni) ripetono "Art. 1" tante volte quanti sono, ma ognuno
riparte da 1 e sale di uno; una tabella di rimandi no.
"""

import re

from commi import RE_FIRMA

# Oltre questa soglia un numero d'articolo ripetuto non e' piu' credibile:
# vedi numerazione_patologica().
MAX_RIPETIZIONI_NUMERO = 3
# Quota di passi fuori sequenza oltre la quale gli allegati sono una tabella di
# rimandi. Le convenzioni e i testi unici rifiutati fino al 17/09 stanno sotto
# il 7%; le tabelle delle violazioni sopra il 60%.
SOGLIA_DISORDINE = 0.25

RE_VOCE = re.compile(r"^\s*(\d{1,3})(?:\)|\.(?=\s|$))\s*(.*)$")
RE_ALLEGATO = re.compile(r"^\s*Allegato\s+[\"“]?([A-Z]{1,2}(?:\s?\d{1,2})?)[\"”]?\s*$")
RE_COMPETENZA = re.compile(r"^\s*Costituiscono\s+violazioni", re.I)
# L'intestazione di pagina ("Allegati al Decreto Delegato ... n.149") e il
# numero di pagina che le sta accanto.
RE_TESTATA = re.compile(r"^\s*Allegat[oi]\s+al(?:l['’]|la|lo)?\s", re.I)
RE_NUMERO_SOLO = re.compile(r"^\s*(?:\d{1,4}|-\s*\d{1,4}\s*-)\s*$")
RIGHE_COMPETENZA = 10
RE_ATTO = re.compile(r"^\s*(?:Legge|Decreto|Regolamento|Codice|Statuto|Testo\s+Unico|Delibera"
                     r"|Ordinanza|Convenzione|Accordo|Norme)\b", re.I)
RE_DISPOSIZIONE = re.compile(r"^\s*(?:artt?\s*\.|articol|sanzion|come\s+al)", re.I)
RIGHE_INTESTAZIONE = 6


def _intero(numero):
    m = re.match(r"\d+", str(numero or ""))
    return int(m.group(0)) if m else None


def _unisci(righe):
    return re.sub(r"\s+", " ", " ".join(r.strip() for r in righe if r.strip())).strip()


def _piu_ripetuto(numeri):
    return max((numeri.count(n) for n in set(numeri)), default=0)


def _numero_testo(a):
    return str(a.get("numeroOriginale") or a.get("numero"))


def disordine_allegati(articoli):
    """(articoli d'allegato, passi fuori sequenza) nella numerazione degli allegati.

    Fuori sequenza: un allegato che non parte da 1, un numero che non segue il
    precedente (lo stesso numero con un -bis e' in sequenza).
    """
    sezioni = {}
    for a in articoli:
        if a.get("allegato") and not a.get("tabella"):
            sezioni.setdefault(a["allegato"], []).append(_intero(_numero_testo(a)))
    totale = disordini = 0
    for interi in sezioni.values():
        totale += len(interi)
        disordini += interi[0] != 1
        disordini += sum(1 for p, q in zip(interi, interi[1:])
                         if p is None or q is None or q - p not in (0, 1))
    return totale, disordini


def _tabella_di_rimandi(articoli):
    """Gli allegati hanno la numerazione di una tabella di rimandi.

    Non conta quante volte un numero si ripete: otto decreti sulle violazioni
    del 1991-2001 restavano sotto le tre ripetizioni ed erano caricati con
    articoli come `all1-3`, `all1-5`, `all2-6`.
    """
    totale, disordini = disordine_allegati(articoli)
    return totale >= 3 and disordini > SOGLIA_DISORDINE * totale


def numerazione_patologica(articoli):
    """Perche' la numerazione degli articoli non e' credibile, o None.

    Il riconoscitore puo' scambiare per articoli propri i rimandi di una
    tabella: DD-149-2016 arrivava a 524 articoli contro i 6 reali. Sull'intero
    archivio 10.782 norme non ripetono mai un numero, 245 arrivano a due (le
    novelle che citano testualmente gli articoli di un altro atto), 37 a tre:
    oltre il tre l'atto si rifiuta, a meno che le ripetizioni non vengano
    tutte da allegati numerati in sequenza, ognuno da 1. Il conteggio e' sul
    numero del testo, non su quello reso univoco da articoli.py: i prefissi
    d'allegato non bastano a far passare un atto.
    """
    numeri = [_numero_testo(a) for a in articoli]
    tutti = _piu_ripetuto(numeri)
    if tutti <= MAX_RIPETIZIONI_NUMERO:
        return None
    nel_corpo = _piu_ripetuto([_numero_testo(a) for a in articoli if not a.get("allegato")])
    totale, disordini = disordine_allegati(articoli)
    if nel_corpo <= MAX_RIPETIZIONI_NUMERO and totale and disordini <= SOGLIA_DISORDINE * totale:
        return None
    return (f"numerazione patologica: uno stesso numero d'articolo ricorre {tutti} volte "
            f"su {len(numeri)} articoli ({nel_corpo} nel corpo, {disordini} passi fuori "
            f"sequenza su {totale} articoli d'allegato)")


def _riga_della_firma(righe, quale):
    """L'indice della riga dove comincia la `quale`-esima formula (da 1)."""
    testo = "\n".join(righe)
    for k, m in enumerate(RE_FIRMA.finditer(testo), 1):
        if k == quale:
            return testo.count("\n", 0, m.start())
    return None


def _intestazioni(righe):
    """{indice: (lettera, competenza, righe occupate)} delle intestazioni d'allegato."""
    trovate = {}
    for i, riga in enumerate(righe):
        m = RE_ALLEGATO.match(riga)
        if not m:
            continue
        seguenti = [j for j in range(i + 1, min(i + 6, len(righe))) if righe[j].strip()][:2]
        inizio = next((j for j in seguenti if RE_COMPETENZA.match(righe[j])), None)
        if inizio is None:
            continue
        fine = inizio
        while (fine < min(inizio + RIGHE_COMPETENZA, len(righe) - 1)
               and not righe[fine].rstrip().endswith(".")):
            fine += 1
        # La frase intera, non la sola autorita': "del Direttore del
        # Dipartimento Prevenzione (...), salvo quelle attribuite all'Ufficio
        # Prevenzione e Ambiente..." dice anche cosa NON e' di sua competenza.
        competenza = _unisci(righe[inizio:fine + 1])
        trovate[i] = (m.group(1).replace(" ", ""), competenza, {i, *range(inizio, fine + 1)})
    return trovate


def _testate(righe):
    """Le righe dell'intestazione di pagina e dei numeri di pagina accanto."""
    fuori = set()
    for i, riga in enumerate(righe):
        if not RE_TESTATA.match(riga):
            continue
        fuori.add(i)
        for passo in (-1, 1):
            j = i + passo
            while 0 <= j < len(righe) and not righe[j].strip():
                j += passo
            if 0 <= j < len(righe) and RE_NUMERO_SOLO.match(righe[j]):
                fuori.add(j)
    return fuori


def _voci(righe, intestazioni):
    """Le voci della tabella: [(indice riga, numero, testo sulla riga, apre)].

    Una voce segue la precedente di uno (fino a tre, se qualcuna non si e'
    letta); un 1 apre un allegato, e lo apre anche la prima voce dopo
    un'intestazione che non continua la numerazione (una "2)" dopo la voce 7).
    Un numero fuori sequenza e' testo: "n. 36)" spezzato a capo non apre una
    voce.
    """
    voci, precedente, dopo_intestazione = [], 0, False
    for i, riga in enumerate(righe):
        if i in intestazioni:
            dopo_intestazione = True
        m = RE_VOCE.match(riga)
        if not m:
            continue
        n = int(m.group(1))
        apre = n == 1 or (dopo_intestazione and n != precedente + 1 and n <= 5)
        if apre or (precedente and precedente < n <= precedente + 3):
            voci.append((i, n, m.group(2), apre))
            precedente, dopo_intestazione = n, False
    return voci


def _assegna(intestazioni, voci):
    """Quale allegato apre ogni intestazione.

    Restituisce {riga della voce d'apertura: riga dell'intestazione} e le
    intestazioni rimaste senza voci.

    Le pagine a colonne stampano l'intestazione dopo le prime voci: "1) 2) 3)
    Allegato C ... 4) 5)". Se dopo l'intestazione la numerazione continua,
    l'intestazione e' dell'allegato in corso; se riparte, apre il successivo
    (cosi' sono impaginati i decreti fino al 2005: "Allegato A ... 1)").
    Quando due intestazioni reclamano lo stesso allegato vince quella che
    continua la numerazione, poi la piu' vicina. All'altra resta il testo senza
    numero che la segue: il Decreto 28 gennaio 1986 n. 7 dell'Allegato I, prima
    dell'"1)" che e' gia' dell'Allegato L.
    """
    aperture = [v[0] for v in voci if v[3]] or [voci[0][0]]
    continua, apre = {}, {}
    for h in sorted(intestazioni):
        prima = next((v for v in reversed(voci) if v[0] < h), None)
        dopo = next((v for v in voci if v[0] > h), None)
        if prima is not None and (dopo is None or not dopo[3]):
            sezione = max((a for a in aperture if a <= prima[0]), default=aperture[0])
            continua.setdefault(sezione, h)
        elif dopo is not None:
            apre.setdefault(dopo[0], []).append(h)
    assegnate, vuote = dict(continua), []
    for sezione, candidate in apre.items():
        if sezione not in assegnate:
            assegnate[sezione] = candidate.pop()
        vuote += candidate
    vuote += [h for h in intestazioni if h not in assegnate.values() and h not in vuote]
    return assegnate, sorted(set(vuote))


def _leggi(righe):
    """Gli allegati di una tabella, e la riga dove la tabella comincia.

    Restituisce ([{lettera, competenza, voci: [(numero, testo, implicita)]}], inizio).
    """
    intestazioni = _intestazioni(righe)
    occupate = set().union(*(v[2] for v in intestazioni.values())) if intestazioni else set()
    utili = {i for i in range(len(righe)) if i not in occupate} - _testate(righe)
    voci = _voci([r if i in utili else "" for i, r in enumerate(righe)], set(intestazioni))
    if not voci:
        return [], None
    assegnate, vuote = _assegna(intestazioni, voci)

    # Le intestazioni senza voci tengono il testo che le segue, fino alla
    # prossima voce o intestazione.
    eventi = sorted([v[0] for v in voci] + list(intestazioni))
    senza_voci = []
    for h in vuote:
        ultima = max(intestazioni[h][2])
        fine = next((e for e in eventi if e > ultima), len(righe))
        tenute = [j for j in range(ultima + 1, fine) if j in utili]
        utili -= set(tenute)
        senza_voci.append({"inizio": h, "intestazione": intestazioni[h][:2],
                           "voci": [{"n": 1, "riga": "", "prima": [], "elenco": [],
                                     "righe": tenute, "implicita": True}]})

    # Le voci di ogni allegato, con le righe (indici) di ognuna.
    sezioni = []
    for k, (i, n, sulla_riga, apre) in enumerate(voci):
        if apre or not sezioni:
            sezioni.append({"inizio": i, "voci": []})
        fine = voci[k + 1][0] if k + 1 < len(voci) else len(righe)
        sezioni[-1]["voci"].append({"n": n, "riga": sulla_riga, "prima": [], "elenco": [],
                                    "righe": [j for j in range(i + 1, fine) if j in utili]})
    for sezione in sezioni:
        if sezione["inizio"] in assegnate:
            sezione["intestazione"] = intestazioni[assegnate[sezione["inizio"]]][:2]

    # Quel che sta subito prima della prima voce di un allegato - "Codice
    # Penale", o l'atto che l'impaginazione ha messo sopra il numero - e' di
    # quella voce, non della precedente. E' il blocco senza righe vuote sopra.
    for s, sezione in enumerate(sezioni):
        j, blocco = sezione["inizio"] - 1, []
        while j >= 0 and len(blocco) < RIGHE_INTESTAZIONE:
            if (j in occupate or not righe[j].strip() or RE_VOCE.match(righe[j])
                    or RE_DISPOSIZIONE.match(righe[j])):
                break
            if j in utili:
                blocco.insert(0, j)
            j -= 1
        sezione["voci"][0]["prima"] = blocco
        if blocco and s > 0:
            precedente = sezioni[s - 1]["voci"][-1]
            precedente["righe"] = [x for x in precedente["righe"] if x not in blocco]

    # Un allegato c'e' solo con la sua intestazione. Una sezione senza e' un
    # elenco numerato dentro una voce ("1) violazione dell'art. 36...") se i
    # suoi numeri si sovrappongono a quelli dell'allegato, e torna testo di
    # quella voce; altrimenti sono voci dell'allegato che l'impaginazione ha
    # spostato.
    unite = sezioni[:1]
    for sezione in sezioni[1:]:
        precedente = unite[-1]
        if sezione.get("intestazione"):
            unite.append(sezione)
        elif {v["n"] for v in precedente["voci"]} & {v["n"] for v in sezione["voci"]}:
            precedente["voci"][-1]["elenco"] += sezione["voci"]
        else:
            precedente["voci"] = sorted(precedente["voci"] + sezione["voci"], key=lambda v: v["n"])
    primo_blocco = sezioni[0]["voci"][0]["prima"]
    sezioni = sorted(unite + senza_voci, key=lambda s: s["inizio"])

    def linee(voce, marcatore=False):
        testa = f"{voce['n']}) {voce['riga']}" if marcatore else voce["riga"]
        fuori = [righe[j] for j in voce["prima"]] + [testa] + [righe[j] for j in voce["righe"]]
        for interna in voce["elenco"]:
            fuori += linee(interna, marcatore=True)
        return fuori

    fuori = []
    for sezione in sezioni:
        lettera, competenza = sezione.get("intestazione", (None, None))
        contesto, voci_testo = None, []
        for voce in sezione["voci"]:
            tutte = linee(voce)
            testo = _unisci(tutte)
            if not testo:
                continue
            piene = [r for r in tutte if r.strip()]
            prima = _unisci(righe[j] for j in voce["prima"])
            if piene and (RE_ATTO.match(piene[0]) or (prima and len(prima) <= 60)):
                testa = []
                for r in piene:
                    if RE_DISPOSIZIONE.match(r) or len(testa) >= RIGHE_INTESTAZIONE:
                        break
                    testa.append(r)
                contesto = _unisci(testa) or contesto
            elif contesto:
                testo = f"[{contesto}] {testo}"
            voci_testo.append((voce["n"], testo, voce.get("implicita", False)))
        # Un allegato di cui resta solo l'intestazione - le sue voci il PDF le
        # ha altrove, o non le ha - non si butta: l'intestazione e' testo.
        if not voci_testo and competenza:
            voci_testo = [(1, competenza, True)]
        if voci_testo:
            fuori.append({"lettera": lettera, "competenza": competenza, "voci": voci_testo})

    inizio = min([voci[0][0], *primo_blocco, *intestazioni])
    return fuori, inizio

def allegati_tabellari(norma, righe, articoli):
    """Sostituisce le tabelle lette come articoli con gli allegati e le loro voci.

    Solo per un atto i cui allegati hanno la numerazione di una tabella di
    rimandi, e solo se almeno un allegato ha l'intestazione "Allegato X /
    Costituiscono violazioni...": altrimenti, o se le voci non si trovano, gli
    articoli restano quelli del riconoscitore. Senza l'intestazione il lettore
    scambiava per tabella l'allegato di una reiterazione (D-84-1990) e quello
    di un protocollo (DC-207-2014).
    """
    if not _tabella_di_rimandi(articoli):
        return articoli
    corpo = [a for a in articoli if not a.get("allegato")]
    firmati = [k for k, a in enumerate(corpo) if any(RE_FIRMA.search(c["testo"]) for c in a["commi"])]
    if not firmati:
        return articoli
    firma = corpo[firmati[0]]
    quale = sum(len(RE_FIRMA.findall(c["testo"])) for a in corpo[:firmati[0]] for c in a["commi"])
    j = next(j for j, c in enumerate(firma["commi"]) if RE_FIRMA.search(c["testo"]))
    quale += 1 + sum(len(RE_FIRMA.findall(c["testo"])) for c in firma["commi"][:j])
    riga = _riga_della_firma(righe, quale)
    if riga is None:
        return articoli
    dopo = righe[riga + 1:]
    tabelle, inizio = _leggi(dopo)
    if (not tabelle or sum(len(t["voci"]) for t in tabelle) < 3
            or not any(t["lettera"] for t in tabelle)):
        return articoli

    # Il comma con la formula tiene firma e firmatari, non l'inizio della
    # tabella che il riconoscitore gli aveva attaccato.
    # 02_parse.py apre un comma nuovo dove finiscono le firme: si riuniscono,
    # perche' i firmatari fino all'inizio della tabella restano col comma
    # della formula. Se l'inizio della tabella non si ritrova, il comma della
    # formula resta com'e'.
    comma = firma["commi"][j]
    seguito = " ".join(c["testo"] for c in firma["commi"][j:])
    m = RE_FIRMA.search(seguito)
    taglio = seguito.find(_unisci([dopo[inizio]])[:30], m.end())
    if taglio > 0:
        comma["testo"] = seguito[:taglio].rstrip()
    firma["commi"] = firma["commi"][:j + 1]
    corpo = corpo[:firmati[0] + 1]

    usate, fuori = set(), list(corpo)
    for k, t in enumerate(tabelle, 1):
        sigla = t["lettera"] or str(k)
        while sigla in usate:
            sigla += "bis"
        usate.add(sigla)
        numero = f"all-{sigla}"
        art_id = f"{norma}/art-{numero}"
        visti, commi = set(), []
        for n, testo, implicita in t["voci"]:
            numero_voce = str(n)
            while numero_voce in visti:
                numero_voce += "-rip"
            visti.add(numero_voce)
            commi.append({"id": f"{art_id}/c-{numero_voce}", "numero": numero_voce, "testo": testo,
                          "numerazioneAnomala": False, "commaImplicito": implicita})
        fuori.append({"id": art_id, "numero": numero, "rubrica": t["competenza"],
                      "partizioneId": None, "commi": commi, "tabella": True,
                      "allegato": f"Allegato {t['lettera']}" if t["lettera"] else f"Allegato {k}"})
    for i, a in enumerate(fuori):
        a["ordine"] = i
    return fuori



# Le due impaginazioni: fino al 2005 l'intestazione sta sopra la voce 1; dal
# 2006 la pagina a colonne la stampa dopo le prime voci (qui C, dopo la 2). B
# ha una voce sola senza numero. "1) 2)" dopo la voce 3 di C sono un elenco
# dentro la voce, e la testata di pagina col suo numero sparisce.
_TABELLA = [
    "I CAPITANI REGGENTI", "",
    "Allegato A",
    "Costituiscono violazioni amministrative, di competenza del Commissario della Legge, le",
    "infrazioni previste dalle seguenti disposizioni di legge.",
    "Codice Penale",
    "1) art.166", "sanzione da L.50.000",
    "2) art.181", "sanzione da L.50.000",
    "Allegati al Decreto 30 dicembre 1996 n.157", "3",
    "3) Legge 28 maggio 1881", "(stampa)", "art. 2", "sanzione di L.40.000",
    "4) art. 5", "sanzione", "",
    "Allegato B",
    "Costituiscono violazioni amministrative, di competenza del Direttore delle Poste, le infrazioni",
    "previste dalle seguenti disposizioni di legge.",
    "Decreto 28 gennaio 1986, n. 7", "art. 9", "sanzione da 10 a 60 volte", "",
    "1)", "Legge 25 luglio 2000 n. 65", "art. 76", "sanzione",
    "2)", "Legge 29 novembre 1995, n. 131", "art. 11", "sanzione",
    "Allegato C",
    "Costituiscono violazioni amministrative, di competenza del Dirigente dell'Ufficio Industria, "
    "le infrazioni previste dalle seguenti disposizioni di legge.",
    "3)", "art. 12", "sanzione",
    "1) prima ipotesi", "2) seconda ipotesi",
]
_letti, _inizio = _leggi(_TABELLA)
assert _inizio == 2
assert [(t["lettera"], t["competenza"]) for t in _letti] == [
    ("A", "Costituiscono violazioni amministrative, di competenza del Commissario della Legge, "
          "le infrazioni previste dalle seguenti disposizioni di legge."),
    ("B", "Costituiscono violazioni amministrative, di competenza del Direttore delle Poste, "
          "le infrazioni previste dalle seguenti disposizioni di legge."),
    ("C", "Costituiscono violazioni amministrative, di competenza del Dirigente dell'Ufficio "
          "Industria, le infrazioni previste dalle seguenti disposizioni di legge.")]
assert _letti[0]["voci"] == [
    (1, "Codice Penale art.166 sanzione da L.50.000", False),
    (2, "[Codice Penale] art.181 sanzione da L.50.000", False),
    (3, "Legge 28 maggio 1881 (stampa) art. 2 sanzione di L.40.000", False),
    (4, "[Legge 28 maggio 1881 (stampa)] art. 5 sanzione", False)]
assert _letti[1]["voci"] == [(1, "Decreto 28 gennaio 1986, n. 7 art. 9 sanzione da 10 a 60 volte", True)]
assert _letti[2]["voci"] == [
    (1, "Legge 25 luglio 2000 n. 65 art. 76 sanzione", False),
    (2, "Legge 29 novembre 1995, n. 131 art. 11 sanzione", False),
    (3, "[Legge 29 novembre 1995, n. 131] art. 12 sanzione 1) prima ipotesi 2) seconda ipotesi", False)]


def _art(numero, allegato=None, originale=None):
    return {"numero": numero, "allegato": allegato, "numeroOriginale": originale}


# Quattro allegati numerati ognuno da 1: "1" ricorre cinque volte, ma passa.
_convenzione = [_art(str(n)) for n in (1, 2)] + [
    _art(f"all{k}-{n}", f"Allegato {k}", str(n)) for k in range(1, 5) for n in (1, 2, 3)]
assert numerazione_patologica(_convenzione) is None
# Una tabella di rimandi letta come articoli: allegati che partono da 3, 36, 166.
_rimandi = [_art(str(n)) for n in (1, 2, 3)] + [
    _art(f"all{k}-{n}", f"Allegato {k}", str(n))
    for k, numeri in enumerate([(3, 114), (36,), (5, 8), (3,), (166, 409), (3, 6)], 1) for n in numeri]
assert numerazione_patologica(_rimandi).startswith("numerazione patologica")
# Ripetizioni nel corpo: si rifiuta anche con allegati in ordine.
_corpo = [_art("4") for _ in range(5)] + [_art(f"all-{n}", "Allegato", str(n)) for n in (1, 2)]
assert numerazione_patologica(_corpo).startswith("numerazione patologica")
