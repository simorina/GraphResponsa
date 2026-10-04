"""
Il testo delle email che manda Cognito, in italiano e con il nome Responsa.

Uso (con una sessione `aws login --profile root` attiva):
    python aws/configura_cognito.py                  mostra i testi attuali, non cambia niente
    python aws/configura_cognito.py conferma         imposta i testi qui sotto
    python aws/configura_cognito.py prova EMAIL      prova il recupero su un utente usa e getta

L'email della password temporanea e' una sola, l'invito di Cognito: la ricevono
sia gli account nuovi sia chi usa "Password smarrita" (src/servizio/recupero.py
la rimanda con AdminCreateUser RESEND). Il testo vale quindi per entrambi.

Il segnaposto {username} e' obbligatorio, ma il nome utente di Cognito qui e'
un codice interno (UUID): si entra con l'email. Sta in un commento HTML, che il
lettore non vede.

Cognito non ha un'API per cambiare solo i testi: UpdateUserPool rimette ai
valori predefiniti cio' che non riceve. Si rilegge quindi tutta la
configurazione, la si rimanda intera, e la si rilegge per controllare che sia
cambiato solo il testo. Lo stesso testo e' in aws/infrastruttura.yaml (PoolUtenti).

Finche' SES e' in sandbox le email partono da Cognito (no-reply@verificationemail.com,
50 al giorno): spedirle da noreply@responsarsm.com richiede SES in produzione.
"""
import json
import secrets
import string
import sys
import time
import urllib.error
import urllib.request

import boto3

POOL_NOME = "graphresponsa-utenti"
SITO = "https://responsarsm.com"
FIRMA = '<p style="color:#52687a">Responsa<br>Repubblica di San Marino</p>'

INVITO = {
    "EmailSubject": "Responsa: la tua password temporanea",
    "EmailMessage": (
        "<p>Buongiorno,</p>"
        "<p>ecco la password temporanea per entrare in Responsa: <b>{####}</b></p>"
        f'<p>Accedi da <a href="{SITO}/#accesso">responsarsm.com</a> con la tua email e questa password: '
        "al primo accesso ti chiederemo di sceglierne una nuova. La password temporanea vale 7 giorni.</p>"
        "<p>Ricevi questa email perché è stato creato il tuo account, oppure perché è stata "
        "chiesta una nuova password per il tuo indirizzo. Nel secondo caso la password precedente non vale "
        "più: se la richiesta non l'hai fatta tu, entra con questa e scegline una nuova.</p>"
        f"{FIRMA}<!-- {{username}} -->"),
}
VERIFICA = {
    "EmailSubject": "Responsa: il tuo codice di verifica",
    "EmailMessage": f"<p>Il tuo codice di verifica per Responsa è <b>{{####}}</b>.</p>{FIRMA}",
}
# Le impostazioni che UpdateUserPool riceve tali e quali, se il pool le ha.
INTATTE = ("Policies", "DeletionProtection", "LambdaConfig", "AutoVerifiedAttributes", "MfaConfiguration",
           "EmailConfiguration", "AccountRecoverySetting", "UserAttributeUpdateSettings", "UserPoolTier",
           "IssuerConfiguration", "KeyConfiguration", "DeviceConfiguration", "SmsConfiguration",
           "UserPoolAddOns", "SmsVerificationMessage", "SmsAuthenticationMessage")

comando = sys.argv[1] if len(sys.argv) > 1 else ""
if comando not in ("", "conferma", "prova") or (comando == "prova" and len(sys.argv) < 3):
    raise SystemExit(__doc__)

c = boto3.Session(profile_name="root", region_name="eu-central-1").client("cognito-idp")
pool = next(p["Id"] for p in c.list_user_pools(MaxResults=60)["UserPools"] if p["Name"] == POOL_NOME)
prima = c.describe_user_pool(UserPoolId=pool)["UserPool"]
invito = prima["AdminCreateUserConfig"].get("InviteMessageTemplate", {})
print(f"== Pool {pool}: email da {prima['EmailConfiguration'].get('EmailSendingAccount')}")
print(f"  oggetto della password temporanea: {invito.get('EmailSubject') or '(quello standard di Cognito, in inglese)'}")
print(f"  testo gia' in italiano: {invito.get('EmailMessage') == INVITO['EmailMessage']}")

if comando == "conferma":
    richiesta = {k: prima[k] for k in INTATTE if prima.get(k) is not None}
    richiesta.update(
        UserPoolId=pool, PoolName=prima["Name"],
        # UnusedAccountValidityDays e' il vecchio nome della validita' della password temporanea,
        # che ora sta in Policies (TemporaryPasswordValidityDays): non si rimanda.
        AdminCreateUserConfig={"AllowAdminCreateUserOnly": prima["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"],
                               "InviteMessageTemplate": INVITO},
        VerificationMessageTemplate={"DefaultEmailOption": (prima.get("VerificationMessageTemplate") or {}).get(
            "DefaultEmailOption", "CONFIRM_WITH_CODE"), **VERIFICA})
    c.update_user_pool(**richiesta)
    dopo = c.describe_user_pool(UserPoolId=pool)["UserPool"]
    # EmailVerificationMessage e EmailVerificationSubject sono i vecchi campi del codice di
    # verifica: Cognito ci copia da se' il testo di VerificationMessageTemplate.
    toccate = ("LastModifiedDate", "AdminCreateUserConfig", "VerificationMessageTemplate", "EstimatedNumberOfUsers",
               "EmailVerificationMessage", "EmailVerificationSubject")
    diverse = sorted(k for k in set(prima) | set(dopo) if k not in toccate and prima.get(k) != dopo.get(k))
    print("\n== Aggiornato")
    print(f"  oggetto: {dopo['AdminCreateUserConfig']['InviteMessageTemplate']['EmailSubject']}")
    print(f"  password temporanea valida {dopo['Policies']['PasswordPolicy']['TemporaryPasswordValidityDays']} giorni, "
          f"solo su invito: {dopo['AdminCreateUserConfig']['AllowAdminCreateUserOnly']}")
    print(f"  altre impostazioni cambiate: {diverse or 'nessuna'}")
    if diverse:
        print("  ATTENZIONE: prima/dopo diversi, avvisa Claude:",
              json.dumps({k: [prima.get(k), dopo.get(k)] for k in diverse}, default=str)[:800])

if comando == "prova":
    # Il percorso vero del recupero (la pagina chiama /recupero-password), su un utente creato
    # apposta e cancellato subito dopo: la password di un account vero non si tocca.
    email = sys.argv[2].strip().lower()
    try:
        c.admin_get_user(UserPoolId=pool, Username=email)
        raise SystemExit(f"  {email} ha gia' un account: per la prova serve un indirizzo nuovo, "
                         "per esempio con +prova prima della chiocciola")
    except c.exceptions.UserNotFoundException:
        pass
    caratteri = string.ascii_letters + string.digits
    c.admin_create_user(UserPoolId=pool, Username=email, MessageAction="SUPPRESS",
                        TemporaryPassword="Pr0va" + "".join(secrets.choice(caratteri) for _ in range(20)),
                        UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}])
    try:
        richiesta = urllib.request.Request(f"{SITO}/recupero-password", data=json.dumps({"email": email}).encode(),
                                           headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(richiesta, timeout=30) as r:
                print(f"\n== Prova: /recupero-password ha risposto {r.status}")
        except urllib.error.HTTPError as e:
            print(f"\n== Prova: /recupero-password ha risposto {e.code}")
        time.sleep(5)
        stato = c.admin_get_user(UserPoolId=pool, Username=email)["UserStatus"]
        print(f"  utente di prova in {stato}: Cognito ha rimandato la password temporanea a {email}")
    finally:
        c.admin_delete_user(UserPoolId=pool, Username=email)
        print("  utente di prova cancellato")
