"""
Chi sta parlando: validazione del token Cognito.

Il servizio non puo' restare aperto. Non per riservatezza: perche' ogni domanda
spende la chiave Anthropic dell'esercente. Un endpoint pubblico e' un conto
corrente pubblico.

Perche' non l'azione `authenticate-cognito` nativa dell'ALB, che non
richiederebbe questo file: fa redirect e posa cookie sul dominio dell'ALB, e
dietro CloudFront diventa fragile. Soprattutto, un redirect a meta' di uno
stream SSE e' un guasto muto - il browser vede la connessione chiudersi senza
capire perche'. Validando qui si risponde 401 in JSON, e il frontend sa cosa
fare.

In sviluppo, senza COGNITO_POOL_ID, l'autenticazione si spegne e tutti sono
"locale": cosi' `python src/server.py` continua a funzionare senza AWS.
"""

import os
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException

POOL = os.environ.get("COGNITO_POOL_ID")
CLIENT = os.environ.get("COGNITO_CLIENT_ID")
REGIONE = os.environ.get("REGIONE", "eu-central-1")

# Le chiavi pubbliche cambiano di rado: rileggerle a ogni richiesta
# aggiungerebbe una chiamata di rete a ogni domanda, per niente.
_chiavi = None
_chiavi_lette = 0.0
VALIDITA_CHIAVI = 3600


@dataclass(frozen=True)
class Utente:
    id: str          # il "sub" di Cognito: stabile, non cambia se cambia la mail
    email: str
    nome: str


UTENTE_LOCALE = Utente(id="locale", email="locale@sviluppo", nome="Sviluppo locale")


def autenticazione_attiva() -> bool:
    return bool(POOL and CLIENT)


def _scarica_chiavi():
    global _chiavi, _chiavi_lette
    if _chiavi is not None and (time.time() - _chiavi_lette) < VALIDITA_CHIAVI:
        return _chiavi
    import urllib.request
    import json as _json
    url = (f"https://cognito-idp.{REGIONE}.amazonaws.com/{POOL}"
           f"/.well-known/jwks.json")
    with urllib.request.urlopen(url, timeout=10) as r:
        _chiavi = _json.loads(r.read())["keys"]
    _chiavi_lette = time.time()
    return _chiavi


def _decodifica(token: str) -> dict:
    from jose import jwt
    from jose.utils import base64url_decode  # noqa: F401  (import esplicito, la libreria e' opzionale)

    intestazione = jwt.get_unverified_header(token)
    chiave = next((k for k in _scarica_chiavi() if k["kid"] == intestazione.get("kid")), None)
    if chiave is None:
        # Chiave sconosciuta: puo' voler dire rotazione appena avvenuta.
        # Si rilegge una volta sola, poi si rinuncia.
        global _chiavi
        _chiavi = None
        chiave = next((k for k in _scarica_chiavi() if k["kid"] == intestazione.get("kid")), None)
    if chiave is None:
        raise HTTPException(status_code=401, detail="Token non riconosciuto.")

    return jwt.decode(
        token, chiave, algorithms=["RS256"], audience=CLIENT,
        issuer=f"https://cognito-idp.{REGIONE}.amazonaws.com/{POOL}",
    )


def utente_corrente(authorization: str | None = Header(default=None)) -> Utente:
    """Dipendenza FastAPI: restituisce chi sta chiamando, o solleva 401."""
    if not autenticazione_attiva():
        return UTENTE_LOCALE

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Accesso richiesto.")

    try:
        d = _decodifica(authorization.split(" ", 1)[1].strip())
    except HTTPException:
        raise
    except Exception:
        # Il motivo preciso (scaduto, firma errata, pubblico sbagliato) non si
        # riferisce al chiamante: aiuterebbe solo chi sta tentando di indovinare.
        raise HTTPException(status_code=401, detail="Sessione non valida.")

    return Utente(
        id=d["sub"],
        email=d.get("email") or "",
        # L'email prima di cognito:username: in un pool con accesso per email
        # quest'ultimo e' il sub, cioe' un UUID, che mostrato a schermo non
        # dice niente a nessuno.
        nome=d.get("name") or d.get("email") or d.get("cognito:username") or "",
    )
