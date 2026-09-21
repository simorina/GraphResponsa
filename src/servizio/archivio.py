"""
Lo stato applicativo su DynamoDB: utenti, conversazioni, riscontri, consumi.

Le conversazioni NON stanno su Aura. Tre ragioni concrete:

  1. `03_load.py --reset` esegue `MATCH (n) DETACH DELETE n`. Un ricarico del
     grafo cancellerebbe le chat di tutti - e di ricarichi se ne fanno.
  2. I checkpoint crescerebbero senza limite dentro il grafo della normativa,
     mescolati alle norme.
  3. Neo4j non ha scadenza automatica. Qui il TTL e' un campo.

Aura tiene la normativa. Questo modulo tiene le persone.

Senza le variabili delle tabelle (sviluppo locale) ogni funzione diventa un
no-op silenzioso: il server continua a girare senza AWS.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

REGIONE = os.environ.get("REGIONE", "eu-central-1")

T_UTENTI = os.environ.get("TABELLA_UTENTI")
T_CONVERSAZIONI = os.environ.get("TABELLA_CONVERSAZIONI")
T_RISCONTRI = os.environ.get("TABELLA_RISCONTRI")
T_CONSUMI = os.environ.get("TABELLA_CONSUMI")

GIORNI_CONSERVAZIONE = int(os.environ.get("GIORNI_CONSERVAZIONE_CHAT", "90"))
LIMITE_RICHIESTE_GIORNO = int(os.environ.get("LIMITE_RICHIESTE_GIORNO", "100"))
LIMITE_COSTO_MESE = float(os.environ.get("LIMITE_COSTO_MESE", "20"))

# Il giorno di chi usa il servizio, non quello di Greenwich.
#
# I contatori si azzerano al cambio della chiave "giorno#AAAA-MM-GG": se la
# chiave la scrive l'ora UTC, l'azzeramento cade all'01:00 d'inverno e alle
# 02:00 d'estate, e a chi alle 00:30 riprova convinto di avere un plafond
# nuovo il servizio risponde ancora "riprova domani". Il fuso si tiene
# configurabile perche' l'unica cosa peggiore di un fuso sbagliato e' un fuso
# sbagliato che non si puo' correggere senza un rilascio.
FUSO = ZoneInfo(os.environ.get("FUSO_ORARIO", "Europe/Rome"))

# Le fasce: nome, messaggi al giorno, spesa al mese.
#
# La spesa e' in DOLLARI, come i listini Anthropic in agente.PREZZI: e' la
# valuta in cui il costo viene calcolato, e convertirlo qui vorrebbe dire
# inchiodare un tasso di cambio che invecchia da solo.
#
# Due tetti e non uno perche' misurano cose diverse: una domanda che costringe
# l'agente a otto ricerche resta un messaggio solo, ma di token ne spende otto
# volte tanti. Il conteggio dei messaggi difende dall'uso ossessivo, quello
# della spesa dalla bolletta.
FASCE_PREDEFINITE = "prova:10:2,base:50:5,pro:100:25"


def _leggi_fasce(grezzo):
    """"prova:10:2,base:50:5" -> {"prova": (10, 2.0), "base": (50, 5.0)}.

    Una voce malformata si salta invece di far morire il servizio all'avvio:
    un errore di battitura nella configurazione dello stack non deve impedire
    a nessuno di consultare la normativa. Chi resta senza fascia ricade sui
    limiti globali, che sono comunque definiti.
    """
    fasce = {}
    for voce in (grezzo or "").split(","):
        pezzi = [p.strip() for p in voce.split(":")]
        if len(pezzi) != 3 or not pezzi[0]:
            continue
        try:
            fasce[pezzi[0].lower()] = (int(pezzi[1]), float(pezzi[2]))
        except ValueError:
            continue
    return fasce


FASCE = _leggi_fasce(os.environ.get("LIMITI_FASCIA", FASCE_PREDEFINITE))


def limiti_di(fascia) -> tuple[int, float]:
    """I due tetti di chi sta chiedendo.

    `fascia` arriva dai gruppi Cognito e puo' essere una lista: un utente puo'
    stare in piu' gruppi, e in quel caso vale il piu' generoso - essere
    aggiunti a un gruppo non deve mai togliere qualcosa.
    """
    nomi = [fascia] if isinstance(fascia, str) else list(fascia or [])
    trovate = [FASCE[n.lower()] for n in nomi if n and n.lower() in FASCE]
    if not trovate:
        return LIMITE_RICHIESTE_GIORNO, LIMITE_COSTO_MESE
    return max(t[0] for t in trovate), max(t[1] for t in trovate)

_risorsa = None


def attivo() -> bool:
    return bool(T_CONVERSAZIONI)


def _tabella(nome):
    global _risorsa
    if _risorsa is None:
        import boto3
        _risorsa = boto3.resource("dynamodb", region_name=REGIONE)
    return _risorsa.Table(nome)


def _adesso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _scadenza(giorni: int) -> int:
    return int(time.time() + giorni * 86400)


# ----------------------------------------------------------------- utenti

def registra_accesso(utente):
    """Annota chi e' entrato. Scritta a ogni richiesta: e' un PutItem, costa nulla."""
    if not T_UTENTI:
        return
    _tabella(T_UTENTI).update_item(
        Key={"utente": utente.id},
        UpdateExpression=("SET email = :e, nome = :n, ultimoAccesso = :a, "
                          "creato = if_not_exists(creato, :a)"),
        ExpressionAttributeValues={":e": utente.email, ":n": utente.nome, ":a": _adesso()},
    )


# ---------------------------------------------------------- conversazioni

def annota_conversazione(utente_id: str, conversazione: str, titolo: str):
    """
    Salva solo i metadati.

    I messaggi stanno nei checkpoint di LangGraph: duplicarli qui creerebbe due
    verita' che prima o poi divergono.
    """
    if not T_CONVERSAZIONI:
        return
    ora = _adesso()
    _tabella(T_CONVERSAZIONI).update_item(
        Key={"utente": utente_id, "conversazione": conversazione},
        UpdateExpression=("SET titolo = if_not_exists(titolo, :t), aggiornata = :o, "
                          "creata = if_not_exists(creata, :o), "
                          "messaggi = if_not_exists(messaggi, :zero) + :uno, "
                          "scadenza = :s"),
        ExpressionAttributeValues={
            ":t": titolo[:120], ":o": ora, ":zero": 0, ":uno": 1,
            ":s": _scadenza(GIORNI_CONSERVAZIONE),
        },
    )


def elenca_conversazioni(utente_id: str, limite: int = 50) -> list[dict]:
    if not T_CONVERSAZIONI:
        return []
    from boto3.dynamodb.conditions import Key
    r = _tabella(T_CONVERSAZIONI).query(
        IndexName="per-aggiornamento",
        KeyConditionExpression=Key("utente").eq(utente_id),
        ScanIndexForward=False,          # le piu' recenti per prime
        Limit=limite,
    )
    return [
        {"conversazione": v["conversazione"], "titolo": v.get("titolo", ""),
         "aggiornata": v.get("aggiornata"), "messaggi": int(v.get("messaggi", 0))}
        for v in r.get("Items", [])
    ]


def appartiene(utente_id: str, conversazione: str) -> bool:
    """Una conversazione si continua solo se e' tua, o se non e' di nessuno.

    Senza il controllo, un id indovinato aprirebbe le consultazioni di
    chiunque. Ma un id che non esiste in tabella non appartiene a nessuno, e
    rifiutarlo lascia l'utente in un vicolo cieco: il sito ricorda l'ultima
    conversazione in `localStorage` e la ripropone, quindi bastava passare
    dalla produzione allo sviluppo - o aspettare i 90 giorni della scadenza -
    per vedersi rispondere "Conversazione non tua" a ogni messaggio, senza
    modo di uscirne se non svuotando il browser. Qui si riparte da capo con
    quell'id, che e' esattamente cosa ci si aspetta.
    """
    if not T_CONVERSAZIONI:
        return True
    r = _tabella(T_CONVERSAZIONI).get_item(
        Key={"utente": utente_id, "conversazione": conversazione})
    if "Item" in r:
        return True
    # Di qualcun altro, o inesistente? Si guarda se l'id esiste per chiunque.
    altrui = _tabella(T_CONVERSAZIONI).scan(
        FilterExpression="conversazione = :c",
        ExpressionAttributeValues={":c": conversazione}, Limit=1).get("Items")
    return not altrui


# -------------------------------------------------------------- riscontri

def salva_riscontro(utente_id: str, conversazione: str, indice: int, giudizio: str,
                    motivo: str = "", categorie: list[str] | None = None,
                    domanda: str = "", estratto: str = "", fonti: list[str] | None = None):
    """
    Registra il giudizio su un messaggio.

    Salva anche domanda, estratto della risposta e fonti: senza quel contesto,
    fra un mese un record che dice «non utile, fonte sbagliata» non e'
    analizzabile - e i checkpoint saranno scaduti per TTL.

    Idempotente sulla coppia conversazione + indice: ripensarci sovrascrive.
    """
    if not T_RISCONTRI:
        return
    _tabella(T_RISCONTRI).put_item(Item={
        "conversazione": conversazione,
        "messaggio": f"messaggio#{indice:04d}",
        "utente": utente_id,
        "giudizio": giudizio,
        "motivo": (motivo or "")[:2000],
        "categorie": categorie or [],
        "domanda": (domanda or "")[:1000],
        "estrattoRisposta": (estratto or "")[:2000],
        "fonti": (fonti or [])[:20],
        "creato": _adesso(),
    })


# ---------------------------------------------------------------- consumi

def _periodi(adesso=None):
    """Le due chiavi del contatore, datate nel fuso di chi consulta.

    `adesso` si passa solo dalle prove: l'unico modo di verificare un cambio
    di mezzanotte senza aspettare la mezzanotte.
    """
    o = (adesso or datetime.now(timezone.utc)).astimezone(FUSO)
    return o.strftime("giorno#%Y-%m-%d"), o.strftime("mese#%Y-%m")


def prossimi_azzeramenti(adesso=None) -> tuple[str, str]:
    """Quando ripartono i due contatori, come istanti assoluti.

    Si mandano al sito come istanti e non come "mancano N ore": la pagina
    resta aperta per ore, e una durata calcolata dal server invecchia mentre
    la si guarda. Il conto alla rovescia lo fa il browser.

    La mezzanotte non si ottiene sommando un giorno: nelle due notti in cui
    cambia l'ora legale il giorno dura 23 o 25 ore. Si costruisce la data del
    giorno dopo a mezzanotte e la si lascia risolvere al fuso.
    """
    o = (adesso or datetime.now(timezone.utc)).astimezone(FUSO)
    domani = (o + timedelta(days=1)).date()
    mezzanotte = datetime(domani.year, domani.month, domani.day, tzinfo=FUSO)
    primo = (datetime(o.year + (o.month == 12), o.month % 12 + 1, 1, tzinfo=FUSO))
    return (mezzanotte.astimezone(timezone.utc).isoformat(timespec="seconds"),
            primo.astimezone(timezone.utc).isoformat(timespec="seconds"))


def verifica_limiti(utente_id: str, fascia=None) -> str | None:
    """
    Restituisce il motivo del rifiuto, o None se si puo' procedere.

    Protegge la spesa verso Anthropic, che l'infrastruttura AWS non tocca
    minimamente: un utente autenticato, senza questo, puo' bruciare centinaia
    di euro in un pomeriggio e lo si scopre dalla fattura.

    Il rifiuto dice l'ora esatta in cui il contatore riparte: "riprova domani"
    e' inutile a chi scrive alle 23:50, e ambiguo per tutti gli altri.
    """
    if not T_CONSUMI:
        return None
    tetto_giorno, tetto_mese = limiti_di(fascia)
    giorno, mese = _periodi()
    t = _tabella(T_CONSUMI)

    r = t.get_item(Key={"utente": utente_id, "periodo": giorno}).get("Item") or {}
    if int(r.get("richieste", 0)) >= tetto_giorno:
        quando = datetime.fromisoformat(prossimi_azzeramenti()[0]).astimezone(FUSO)
        return (f"Hai raggiunto il limite di {tetto_giorno} consultazioni per oggi. "
                f"Il contatore riparte alle {quando.strftime('%H:%M')} "
                f"di {quando.strftime('%d/%m')}.")

    r = t.get_item(Key={"utente": utente_id, "periodo": mese}).get("Item") or {}
    if float(r.get("costo", 0)) >= tetto_mese:
        return ("Hai raggiunto il tetto di spesa mensile previsto per il tuo "
                "profilo. Contatta l'amministratore.")
    return None


def registra_consumo(utente_id: str, token_in: int, token_out: int, costo: float):
    """
    Somma i consumi sui contatori del giorno e del mese.

    `rispondi()` calcolava gia' token e costo per mostrarli nella UI, e poi li
    buttava. Qui finalmente restano.
    """
    if not T_CONSUMI:
        return
    t = _tabella(T_CONSUMI)
    for periodo, giorni in zip(_periodi(), (35, 400)):
        t.update_item(
            Key={"utente": utente_id, "periodo": periodo},
            UpdateExpression=("ADD richieste :uno, tokenIn :ti, tokenOut :to, costo :c "
                              "SET scadenza = :s"),
            ExpressionAttributeValues={
                ":uno": 1, ":ti": token_in, ":to": token_out,
                ":c": Decimal(str(round(costo, 6))), ":s": _scadenza(giorni),
            },
        )


def consumi_correnti(utente_id: str, fascia=None) -> dict:
    """I due contatori con i rispettivi tetti e il momento in cui ripartono.

    Senza tabella - sviluppo locale - si restituiscono comunque i tetti e gli
    azzeramenti con contatori a zero: il sito mostra le barre vuote invece di
    non mostrare niente, e la differenza fra "nessun limite" e "limite non
    ancora toccato" resta visibile a chi sviluppa.
    """
    tetto_giorno, tetto_mese = limiti_di(fascia)
    azzera_giorno, azzera_mese = prossimi_azzeramenti()
    base = {
        "richiesteOggi": 0, "limiteGiorno": tetto_giorno,
        "costoMese": 0.0, "limiteMese": tetto_mese,
        "azzeraGiorno": azzera_giorno, "azzeraMese": azzera_mese,
    }
    if not T_CONSUMI:
        return base
    giorno, mese = _periodi()
    t = _tabella(T_CONSUMI)
    g = t.get_item(Key={"utente": utente_id, "periodo": giorno}).get("Item") or {}
    m = t.get_item(Key={"utente": utente_id, "periodo": mese}).get("Item") or {}
    return {**base,
            "richiesteOggi": int(g.get("richieste", 0)),
            "costoMese": float(m.get("costo", 0))}


# ------------------------------------------------------------------- prove
#
# Girano all'import, come in 08_abrogazioni.py. Qui servono piu' che altrove:
# un cambio di mezzanotte non si verifica a mano senza aspettare la
# mezzanotte, e i due casi in cui si sbaglia davvero - le notti in cui cambia
# l'ora legale - capitano due volte l'anno. Un errore li' resterebbe invisibile
# per sei mesi.

def _t(iso):
    return datetime.fromisoformat(iso)


# D'inverno Roma e' UTC+1: le 23:30 UTC sono gia' il giorno dopo a Roma.
assert _periodi(_t("2026-01-15T23:30:00+00:00"))[0] == "giorno#2026-01-16"
assert _periodi(_t("2026-01-15T22:30:00+00:00"))[0] == "giorno#2026-01-15"
# D'estate e' UTC+2: il confine si sposta di un'ora ancora.
assert _periodi(_t("2026-07-15T22:30:00+00:00"))[0] == "giorno#2026-07-16"
assert _periodi(_t("2026-07-15T21:30:00+00:00"))[0] == "giorno#2026-07-15"
# Il mese cambia con lo stesso scarto: l'ultimo dell'anno non fa eccezione.
assert _periodi(_t("2026-01-31T23:30:00+00:00"))[1] == "mese#2026-02"
assert _periodi(_t("2026-12-31T23:30:00+00:00"))[1] == "mese#2027-01"

# L'azzeramento e' la mezzanotte di Roma, espressa in UTC: 23:00 d'inverno,
# 22:00 d'estate. E' il calcolo che era sbagliato prima, e si vede solo cosi'.
assert prossimi_azzeramenti(_t("2026-01-15T10:00:00+00:00"))[0] == "2026-01-15T23:00:00+00:00"
assert prossimi_azzeramenti(_t("2026-07-15T10:00:00+00:00"))[0] == "2026-07-15T22:00:00+00:00"
# Alle 23:30 UTC di gennaio a Roma e' gia' il 16: il prossimo azzeramento e'
# quello del 17, non quello appena passato.
assert prossimi_azzeramenti(_t("2026-01-15T23:30:00+00:00"))[0] == "2026-01-16T23:00:00+00:00"

# Le due notti del cambio d'ora. Il 29 marzo 2026 Roma passa a UTC+2 e il
# giorno dura 23 ore; il 25 ottobre torna a UTC+1 e ne dura 25. Sommare 24 ore
# invece di ricostruire la data sbaglierebbe qui, e solo qui.
assert prossimi_azzeramenti(_t("2026-03-28T12:00:00+00:00"))[0] == "2026-03-28T23:00:00+00:00"
assert prossimi_azzeramenti(_t("2026-03-29T12:00:00+00:00"))[0] == "2026-03-29T22:00:00+00:00"
assert prossimi_azzeramenti(_t("2026-10-24T12:00:00+00:00"))[0] == "2026-10-24T22:00:00+00:00"
assert prossimi_azzeramenti(_t("2026-10-25T12:00:00+00:00"))[0] == "2026-10-25T23:00:00+00:00"

# Il mese riparte il primo, e dicembre scavalca l'anno.
assert prossimi_azzeramenti(_t("2026-05-20T10:00:00+00:00"))[1] == "2026-05-31T22:00:00+00:00"
assert prossimi_azzeramenti(_t("2026-12-20T10:00:00+00:00"))[1] == "2026-12-31T23:00:00+00:00"

# Le fasce: quella giusta, quella sconosciuta, e chi sta in due gruppi.
_f = _leggi_fasce("prova:10:2,base:50:5,pro:100:25")
assert _f == {"prova": (10, 2.0), "base": (50, 5.0), "pro": (100, 25.0)}
assert _leggi_fasce("prova:10:2,rotta,base:cinquanta:5")["prova"] == (10, 2.0)
assert "base" not in _leggi_fasce("prova:10:2,base:cinquanta:5")
assert _leggi_fasce("") == {} and _leggi_fasce(None) == {}

assert limiti_di("base") == (50, 5.0)
assert limiti_di("BASE") == (50, 5.0)                      # il gruppo non e' case sensitive
assert limiti_di(["prova", "pro"]) == (100, 25.0)          # vince il piu' generoso
assert limiti_di("inesistente") == (LIMITE_RICHIESTE_GIORNO, LIMITE_COSTO_MESE)
assert limiti_di(None) == (LIMITE_RICHIESTE_GIORNO, LIMITE_COSTO_MESE)
assert limiti_di([]) == (LIMITE_RICHIESTE_GIORNO, LIMITE_COSTO_MESE)
