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

REGIONE = os.environ.get("REGIONE", "eu-central-1")

T_UTENTI = os.environ.get("TABELLA_UTENTI")
T_CONVERSAZIONI = os.environ.get("TABELLA_CONVERSAZIONI")
T_RISCONTRI = os.environ.get("TABELLA_RISCONTRI")
T_CONSUMI = os.environ.get("TABELLA_CONSUMI")

GIORNI_CONSERVAZIONE = int(os.environ.get("GIORNI_CONSERVAZIONE_CHAT", "90"))
LIMITE_RICHIESTE_GIORNO = int(os.environ.get("LIMITE_RICHIESTE_GIORNO", "100"))
LIMITE_COSTO_MESE = float(os.environ.get("LIMITE_COSTO_MESE", "20"))

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
    """Una conversazione si legge solo se e' tua. Senza questo, un id indovinato
    aprirebbe le consultazioni di chiunque."""
    if not T_CONVERSAZIONI:
        return True
    r = _tabella(T_CONVERSAZIONI).get_item(
        Key={"utente": utente_id, "conversazione": conversazione})
    return "Item" in r


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

def _periodi():
    o = datetime.now(timezone.utc)
    return o.strftime("giorno#%Y-%m-%d"), o.strftime("mese#%Y-%m")


def verifica_limiti(utente_id: str) -> str | None:
    """
    Restituisce il motivo del rifiuto, o None se si puo' procedere.

    Protegge la spesa verso Anthropic, che l'infrastruttura AWS non tocca
    minimamente: un utente autenticato, senza questo, puo' bruciare centinaia
    di euro in un pomeriggio e lo si scopre dalla fattura.
    """
    if not T_CONSUMI:
        return None
    giorno, mese = _periodi()
    t = _tabella(T_CONSUMI)

    r = t.get_item(Key={"utente": utente_id, "periodo": giorno}).get("Item") or {}
    if int(r.get("richieste", 0)) >= LIMITE_RICHIESTE_GIORNO:
        return (f"Hai raggiunto il limite di {LIMITE_RICHIESTE_GIORNO} consultazioni "
                f"per oggi. Riprova domani.")

    r = t.get_item(Key={"utente": utente_id, "periodo": mese}).get("Item") or {}
    if float(r.get("costo", 0)) >= LIMITE_COSTO_MESE:
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


def consumi_correnti(utente_id: str) -> dict:
    if not T_CONSUMI:
        return {}
    giorno, mese = _periodi()
    t = _tabella(T_CONSUMI)
    g = t.get_item(Key={"utente": utente_id, "periodo": giorno}).get("Item") or {}
    m = t.get_item(Key={"utente": utente_id, "periodo": mese}).get("Item") or {}
    return {
        "richiesteOggi": int(g.get("richieste", 0)),
        "limiteGiorno": LIMITE_RICHIESTE_GIORNO,
        "costoMese": float(m.get("costo", 0)),
        "limiteMese": LIMITE_COSTO_MESE,
    }
