"""
La password smarrita: una password temporanea per email, e al primo accesso se
ne sceglie una nuova.

Dal browser Cognito sa mandare solo codici di verifica (ForgotPassword). Una
password temporanea per un utente che esiste gia' e' un'operazione da
amministratore, e percio' sta qui:

  1. AdminSetUserPassword con Permanent=False porta l'utente in
     FORCE_CHANGE_PASSWORD, lo stato di un account appena creato;
  2. AdminCreateUser con MessageAction=RESEND genera una password temporanea
     nuova e rimanda l'email d'invito, quella con utente e password.

Al primo accesso Cognito risponde allora NEW_PASSWORD_REQUIRED, e la pagina
d'accesso lo gestisce gia' per gli account nuovi. Chi e' gia' in
FORCE_CHANGE_PASSWORD - un account nuovo con la temporanea scaduta - salta il
primo passo e riceve una temporanea fresca.

Il prezzo va detto: la vecchia password smette di valere subito, anche se la
richiesta l'ha fatta un altro. Nessuno entra al posto dell'utente - la
temporanea arriva solo alla sua email - ma un estraneo potrebbe costringerlo a
sceglierne una nuova. Di qui i limiti: una richiesta per indirizzo ogni 15
minuti, poche per IP, un tetto complessivo all'ora.

La risposta e' la stessa per indirizzi registrati e no, e anche oltre i
limiti: distinguerli direbbe a chiunque quali email hanno un account.
"""
import logging
import os
import re
import secrets
import string
import threading
import time
from collections import deque

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

POOL = os.environ.get("COGNITO_POOL_ID")
REGIONE = os.environ.get("REGIONE", "eu-central-1")

RE_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")

PAUSA_INDIRIZZO = 15 * 60          # secondi fra due richieste per lo stesso indirizzo
PER_IP = (5, 15 * 60)              # richieste, finestra in secondi
TOTALE = (30, 60 * 60)


class Indisponibile(Exception):
    """Il recupero non funziona per ragioni nostre: permessi, configurazione,
    Cognito che non risponde. Non dice nulla dell'indirizzo."""


# I limiti stanno in memoria: il servizio gira su un task solo, e un riavvio
# che li azzera vale al massimo qualche richiesta in piu'.
_lucchetto = threading.Lock()
_ultima: dict[str, float] = {}
_per_ip: dict[str, deque] = {}
_totale: deque = deque()


def _entro_i_limiti(chiave: str, ip: str, adesso: float) -> bool:
    """Registra la richiesta se rientra nei limiti. Conta anche gli indirizzi
    non registrati, altrimenti i limiti stessi direbbero quali esistono."""
    with _lucchetto:
        while _totale and adesso - _totale[0] > TOTALE[1]:
            _totale.popleft()
        coda = _per_ip.setdefault(ip, deque())
        while coda and adesso - coda[0] > PER_IP[1]:
            coda.popleft()
        for k in [k for k, t in _ultima.items() if adesso - t >= PAUSA_INDIRIZZO]:
            del _ultima[k]
        for k in [k for k, c in _per_ip.items() if not c and k != ip]:
            del _per_ip[k]

        if len(_totale) >= TOTALE[0] or len(coda) >= PER_IP[0] or chiave in _ultima:
            return False
        _totale.append(adesso)
        coda.append(adesso)
        _ultima[chiave] = adesso
        return True


def _password_di_passaggio() -> str:
    """Una password che nessuno vedra': serve solo a portare l'utente in
    FORCE_CHANGE_PASSWORD, e RESEND la sostituisce subito con quella che
    arriva per email. Rispetta comunque la politica del pool."""
    alfabeto = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(alfabeto) for _ in range(24))
        if any(c.islower() for c in p) and any(c.isupper() for c in p) and any(c.isdigit() for c in p):
            return p


def _mascherata(email: str) -> str:
    """Per i log: abbastanza per riconoscere un caso, non l'indirizzo intero."""
    nome, _, dominio = email.partition("@")
    return f"{nome[:1]}***@{dominio}"


def manda_password_temporanea(email: str, ip: str, cognito=None) -> None:
    """Manda all'indirizzo, se ha un account attivo, una password temporanea.

    Non restituisce nulla e, per un indirizzo sconosciuto o oltre i limiti,
    non segnala nulla. Solleva Indisponibile solo se il servizio non funziona.
    """
    email = (email or "").strip()
    if len(email) > 254 or not RE_EMAIL.match(email):
        return
    if not _entro_i_limiti(email.lower(), ip or "?", time.monotonic()):
        log.info("recupero: oltre i limiti (%s)", _mascherata(email))
        return
    if not POOL:
        raise Indisponibile("COGNITO_POOL_ID non impostato")

    cognito = cognito or boto3.client("cognito-idp", region_name=REGIONE)
    try:
        utente = cognito.admin_get_user(UserPoolId=POOL, Username=email)
    except ClientError as e:
        if e.response["Error"]["Code"] == "UserNotFoundException":
            return
        raise Indisponibile(e.response["Error"]["Code"]) from e
    if not utente.get("Enabled", True):
        return

    try:
        if utente.get("UserStatus") != "FORCE_CHANGE_PASSWORD":
            cognito.admin_set_user_password(UserPoolId=POOL, Username=email,
                                            Password=_password_di_passaggio(), Permanent=False)
        cognito.admin_create_user(UserPoolId=POOL, Username=email, MessageAction="RESEND",
                                  DesiredDeliveryMediums=["EMAIL"])
    except ClientError as e:
        raise Indisponibile(e.response["Error"]["Code"]) from e
    log.info("recupero: password temporanea mandata (%s)", _mascherata(email))
