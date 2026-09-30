"""Le prove del recupero della password con password temporanea.

    .venv\\Scripts\\python.exe scripts\\prova_recupero.py

Non tocca Cognito: le chiamate passano da uno Stubber di botocore, che
fallisce se il codice ne fa una non prevista. Si controlla quali operazioni
partono per ogni stato dell'utente, e che la risposta non dica mai se un
indirizzo esiste.
"""
import os
import pathlib
import re
import sys

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RADICE), str(RADICE / "src")]
os.environ["TABELLA_CHECKPOINT"] = ""
os.environ["TABELLA_SCRITTURE"] = ""

import boto3                                   # noqa: E402
from botocore.stub import ANY, Stubber         # noqa: E402

from servizio import recupero                  # noqa: E402

POOL = "eu-central-1_PROVA"
recupero.POOL = POOL


def azzera_limiti():
    recupero._ultima.clear()
    recupero._per_ip.clear()
    recupero._totale.clear()


def prova_caso(nome, email, risposte, ip="10.0.0.1", attesa=None):
    """`risposte`: le chiamate previste, in ordine, come (operazione, esito)."""
    client = boto3.client("cognito-idp", region_name="eu-central-1",
                          aws_access_key_id="x", aws_secret_access_key="x")
    stub = Stubber(client)
    for operazione, esito in risposte:
        if isinstance(esito, str):
            stub.add_client_error(operazione, service_error_code=esito, http_status_code=400)
        else:
            risposta, parametri = esito
            stub.add_response(operazione, risposta, parametri)
    errore = None
    with stub:
        try:
            recupero.manda_password_temporanea(email, ip, cognito=client)
        except Exception as e:        # noqa: BLE001
            errore = e
        try:
            stub.assert_no_pending_responses()
            mancanti = None
        except AssertionError as e:
            mancanti = str(e)
    if attesa is None:
        ok = errore is None and mancanti is None
    else:
        ok = isinstance(errore, attesa) and mancanti is None
    return ok, f"{type(errore).__name__ if errore else ''} {mancanti or ''}".strip()


def utente(stato, attivo=True):
    return ({"Username": "3f2c-uuid", "UserStatus": stato, "Enabled": attivo},
            {"UserPoolId": POOL, "Username": "persona@responsa.sm"})


IMPOSTA = ({}, {"UserPoolId": POOL, "Username": "persona@responsa.sm", "Password": ANY, "Permanent": False})
RIMANDA = ({"User": {"Username": "3f2c-uuid"}},
           {"UserPoolId": POOL, "Username": "persona@responsa.sm", "MessageAction": "RESEND",
            "DesiredDeliveryMediums": ["EMAIL"]})


def prova():
    errori = 0

    def controlla(nome, ok, dettaglio=""):
        nonlocal errori
        errori += not ok
        print(f'  {"OK " if ok else "NO "} {nome:<60} {dettaglio}')

    print("stati dell'utente")
    for stato, previste in [
        ("CONFIRMED", [("admin_get_user", utente("CONFIRMED")), ("admin_set_user_password", IMPOSTA),
                       ("admin_create_user", RIMANDA)]),
        ("RESET_REQUIRED", [("admin_get_user", utente("RESET_REQUIRED")), ("admin_set_user_password", IMPOSTA),
                            ("admin_create_user", RIMANDA)]),
        ("FORCE_CHANGE_PASSWORD", [("admin_get_user", utente("FORCE_CHANGE_PASSWORD")),
                                   ("admin_create_user", RIMANDA)]),
    ]:
        azzera_limiti()
        ok, d = prova_caso(stato, "persona@responsa.sm", previste)
        controlla(f"{stato}: le chiamate giuste, nell'ordine giusto", ok, d)

    azzera_limiti()
    ok, d = prova_caso("disattivato", "persona@responsa.sm", [("admin_get_user", utente("CONFIRMED", attivo=False))])
    controlla("account disattivato: nessuna password mandata", ok, d)

    azzera_limiti()
    ok, d = prova_caso("sconosciuto", "persona@responsa.sm", [("admin_get_user", "UserNotFoundException")])
    controlla("indirizzo sconosciuto: nessun errore, nessuna altra chiamata", ok, d)

    azzera_limiti()
    ok, d = prova_caso("malformato", "non-una-email", [])
    controlla("email malformata: nessuna chiamata", ok, d)

    azzera_limiti()
    ok, d = prova_caso("permessi", "persona@responsa.sm", [("admin_get_user", "AccessDeniedException")],
                       attesa=recupero.Indisponibile)
    controlla("permessi mancanti: Indisponibile (-> 503)", ok, d)

    azzera_limiti()
    ok, d = prova_caso("invio", "persona@responsa.sm",
                       [("admin_get_user", utente("CONFIRMED")), ("admin_set_user_password", IMPOSTA),
                        ("admin_create_user", "LimitExceededException")], attesa=recupero.Indisponibile)
    controlla("Cognito rifiuta l'invio: Indisponibile", ok, d)

    print("\nlimiti")
    azzera_limiti()
    prova_caso("primo", "persona@responsa.sm", [("admin_get_user", "UserNotFoundException")])
    ok, d = prova_caso("secondo", "Persona@Responsa.sm ", [])
    controlla("stesso indirizzo entro 15 minuti: nessuna chiamata", ok, d)

    azzera_limiti()
    for i in range(recupero.PER_IP[0]):
        prova_caso("ip", f"p{i}@responsa.sm", [("admin_get_user", "UserNotFoundException")], ip="10.9.9.9")
    ok, d = prova_caso("ip oltre", "altro@responsa.sm", [], ip="10.9.9.9")
    controlla(f"stesso IP oltre {recupero.PER_IP[0]} richieste: nessuna chiamata", ok, d)
    ok, d = prova_caso("altro ip", "altro@responsa.sm", [("admin_get_user", "UserNotFoundException")], ip="10.8.8.8")
    controlla("un altro IP passa", ok, d)

    azzera_limiti()
    for i in range(recupero.TOTALE[0]):
        prova_caso("tot", f"t{i}@responsa.sm", [("admin_get_user", "UserNotFoundException")], ip=f"10.1.{i}.1")
    ok, d = prova_caso("tot oltre", "ultimo@responsa.sm", [], ip="10.2.2.2")
    controlla(f"oltre {recupero.TOTALE[0]} richieste l'ora in tutto: nessuna chiamata", ok, d)

    print("\npassword di passaggio")
    campione = [recupero._password_di_passaggio() for _ in range(300)]
    controlla("rispettano la politica del pool (12+, maiuscola, minuscola, numero)",
              all(len(p) >= 12 and re.search(r"[A-Z]", p) and re.search(r"[a-z]", p) and re.search(r"\d", p)
                  for p in campione))
    controlla("tutte diverse", len(set(campione)) == len(campione))

    print("\nendpoint")
    from fastapi.testclient import TestClient  # noqa: E402
    import server  # noqa: E402

    chiamate = []
    originale = recupero.manda_password_temporanea
    client = TestClient(server.app)
    try:
        recupero.manda_password_temporanea = lambda email, ip, cognito=None: chiamate.append((email, ip))
        r = client.post("/recupero-password", json={"email": "persona@responsa.sm"},
                        headers={"X-Forwarded-For": "6.6.6.6, 81.2.3.4, 130.176.0.1"})
        controlla("risponde {ok: true}", r.status_code == 200 and r.json() == {"ok": True}, r.text)
        controlla("l'IP e' il penultimo di X-Forwarded-For, non il primo",
                  chiamate and chiamate[-1][1] == "81.2.3.4", str(chiamate[-1:]))

        def indisponibile(email, ip, cognito=None):
            raise recupero.Indisponibile("AccessDeniedException")
        recupero.manda_password_temporanea = indisponibile
        r = client.post("/recupero-password", json={"email": "persona@responsa.sm"})
        controlla("servizio non disponibile: 503", r.status_code == 503, r.text)
        r = client.post("/recupero-password", json={"email": "x" * 300})
        controlla("email troppo lunga: rifiutata prima di Cognito", r.status_code == 422)
    finally:
        recupero.manda_password_temporanea = originale

    print("\nfallite:", errori)
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(prova())
