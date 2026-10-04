"""
La posta di responsarsm.com su Amazon SES: spedire dal dominio e ricevere sul dominio.

Uso (con una sessione `aws login --profile root` attiva):
    python aws/configura_posta.py              solo controlli, non cambia niente
    python aws/configura_posta.py conferma     dominio su SES, DNS, ricezione e inoltro
    python aws/configura_posta.py sito         la demo spedisce con SES (dopo il rilascio del codice)
    python aws/configura_posta.py produzione   chiede ad AWS di uscire dalla sandbox
    python aws/configura_posta.py prova        un'email di prova a demo@, che deve arrivare in Gmail

`conferma`
  1. Il dominio come identita' SES, con le tre firme DKIM nel DNS, il MAIL FROM
     su mail.responsarsm.com (MX e SPF), l'SPF del dominio e un DMARC in sola
     osservazione. Sono i record che tengono le nostre email fuori dallo spam.
  2. La DESTINAZIONE dell'inoltro come indirizzo verificato: in sandbox SES
     spedisce solo a indirizzi verificati, e AWS manda un link da cliccare.
  3. La ricezione: un bucket S3 per i messaggi (si cancellano dopo 90 giorni),
     la Lambda aws/inoltro_posta.py che li rispedisce alla DESTINAZIONE, la
     regola SES che li riceve per tutto il dominio, e il record MX.
`sito`
  Il ruolo del container puo' spedire dal dominio, e la definizione del task
  manda la demo da demo@responsarsm.com a demo@responsarsm.com (che l'inoltro
  porta in Gmail) invece che dalla Gmail con la password per le app. Si ferma
  se l'immagine in produzione non contiene ancora il codice che usa SES.
Tutto si puo' rilanciare: cio' che c'e' gia' non si rifa'.
"""
import io
import json
import pathlib
import subprocess
import sys
import time
import urllib.request
import zipfile

import boto3
from botocore.exceptions import ClientError

DOMINIO = "responsarsm.com"
REGIONE = "eu-central-1"
DESTINAZIONE = "rinaldisimone8@gmail.com"     # la casella dove arriva tutta la posta del dominio
INOLTRO = f"inoltro@{DOMINIO}"                 # il mittente degli inoltri
DEMO_MITTENTE = f"Responsa <demo@{DOMINIO}>"
DEMO_DESTINATARI = f"demo@{DOMINIO}"
MAIL_FROM = f"mail.{DOMINIO}"
FUNZIONE = "graphresponsa-inoltro-posta"
INSIEME, REGOLA = "graphresponsa", "inoltro"
CLUSTER, SERVIZIO = "graphresponsa-cluster", "graphresponsa-api"
SITO = f"https://{DOMINIO}"
ETICHETTE = [{"Key": "Progetto", "Value": "GraphResponsa"}, {"Key": "Ambiente", "Value": "dev"}]
RADICE = pathlib.Path(__file__).resolve().parent.parent
COMANDO = sys.argv[1] if len(sys.argv) > 1 else ""
if COMANDO not in ("", "conferma", "sito", "produzione", "prova"):
    raise SystemExit(__doc__)

s = boto3.Session(profile_name="root", region_name=REGIONE)
CONTO = s.client("sts").get_caller_identity()["Account"]
BUCKET = f"graphresponsa-posta-{CONTO}"
ses2, ses1 = s.client("sesv2"), s.client("ses")
r53, s3, iam, lam, logs, ecs, ecr = (s.client(x) for x in ("route53", "s3", "iam", "lambda", "logs", "ecs", "ecr"))
ARN_IDENTITA = f"arn:aws:ses:{REGIONE}:{CONTO}:identity/{DOMINIO}"
ARN_REGOLA = f"arn:aws:ses:{REGIONE}:{CONTO}:receipt-rule-set/{INSIEME}:receipt-rule/{REGOLA}"
ZONA = next(z["Id"].split("/")[-1] for z in r53.list_hosted_zones_by_name(DNSName=DOMINIO)["HostedZones"]
            if z["Name"] == DOMINIO + ".")


def identita(nome):
    try:
        return ses2.get_email_identity(EmailIdentity=nome)
    except ses2.exceptions.NotFoundException:
        return None


def dns(nome, tipo, valori, ttl=300):
    r53.change_resource_record_sets(HostedZoneId=ZONA, ChangeBatch={"Changes": [{"Action": "UPSERT", "ResourceRecordSet": {
        "Name": nome, "Type": tipo, "TTL": ttl, "ResourceRecords": [{"Value": v} for v in valori]}}]})


def txt_attuali(nome):
    r = r53.list_resource_record_sets(HostedZoneId=ZONA, StartRecordName=nome, StartRecordType="TXT", MaxItems="1")
    righe = [x for x in r["ResourceRecordSets"] if x["Name"].rstrip(".") == nome and x["Type"] == "TXT"]
    return [v["Value"] for v in righe[0]["ResourceRecords"]] if righe else []


def esiste(funzione, *a, eccezioni=("NoSuchEntity", "ResourceNotFoundException", "404", "NoSuchBucket"), **k):
    try:
        return funzione(*a, **k)
    except ClientError as e:
        if e.response["Error"]["Code"] in eccezioni:
            return None
        raise


# ---- Controlli: sempre, e senza argomenti solo questi.
print("== Situazione")
dom = identita(DOMINIO)
conto = ses2.get_account()
print(f"  SES {REGIONE}: {'produzione' if conto['ProductionAccessEnabled'] else 'sandbox'}, "
      f"{int(conto['SendQuota']['Max24HourSend'])} email al giorno, richiesta "
      f"{(conto.get('Details') or {}).get('ReviewDetails', {}).get('Status') or 'mai fatta'}")
print(f"  dominio: {'assente' if not dom else 'DKIM ' + dom['DkimAttributes']['Status'] + ', MAIL FROM ' + dom.get('MailFromAttributes', {}).get('MailFromDomainStatus', '-')}")
dest = identita(DESTINAZIONE)
print(f"  destinazione dell'inoltro {DESTINAZIONE}: {'non verificata' if not dest else ('verificata' if dest['VerifiedForSendingStatus'] else 'in attesa del clic nel link')}")
print(f"  bucket {BUCKET}: {'c' + chr(39) + 'e' if esiste(s3.head_bucket, Bucket=BUCKET) is not None else 'assente'}")
print(f"  Lambda {FUNZIONE}: {'c' + chr(39) + 'e' if esiste(lam.get_function, FunctionName=FUNZIONE) else 'assente'}")
attivo = (ses1.describe_active_receipt_rule_set().get("Metadata") or {}).get("Name")
print(f"  regole di ricezione attive: {attivo or 'nessuna'}")
td = ecs.describe_task_definition(taskDefinition=ecs.describe_services(cluster=CLUSTER, services=[SERVIZIO])
                                  ["services"][0]["taskDefinition"], include=["TAGS"])
contenitore = td["taskDefinition"]["containerDefinitions"][0]
ambiente = {e["name"]: e["value"] for e in contenitore.get("environment", [])}
print(f"  demo in produzione: da {ambiente.get('DEMO_MITTENTE')} a {ambiente.get('DEMO_DESTINATARI')}, "
      f"{'con' if any(x['name'] == 'DEMO_SMTP_PASSWORD' for x in contenitore.get('secrets', [])) else 'senza'} la password SMTP")
if not COMANDO:
    raise SystemExit("\nControlli fatti, niente e' stato cambiato. Vedi l'uso in testa al file.")


def conferma():
    # ---- 1. Il dominio su SES e i record che lo autenticano.
    print("\n== 1. Il dominio su SES")
    if not identita(DOMINIO):
        ses2.create_email_identity(EmailIdentity=DOMINIO, Tags=ETICHETTE)
        print("  identita' creata")
    firma = identita(DOMINIO)["DkimAttributes"]
    zona_dkim = firma.get("SigningHostedZone") or "dkim.amazonses.com"
    for t in firma["Tokens"]:
        dns(f"{t}._domainkey.{DOMINIO}", "CNAME", [f"{t}.{zona_dkim}"])
    print(f"  {len(firma['Tokens'])} firme DKIM nel DNS")
    ses2.put_email_identity_mail_from_attributes(EmailIdentity=DOMINIO, MailFromDomain=MAIL_FROM,
                                                 BehaviorOnMxFailure="USE_DEFAULT_VALUE")
    dns(MAIL_FROM, "MX", [f"10 feedback-smtp.{REGIONE}.amazonses.com"])
    dns(MAIL_FROM, "TXT", ['"v=spf1 include:amazonses.com ~all"'])
    print(f"  MAIL FROM {MAIL_FROM}: MX e SPF")
    # L'SPF del dominio si aggiunge ai TXT che ci sono gia' (verifiche di altri servizi), non li sostituisce.
    altri = [v for v in txt_attuali(DOMINIO) if "v=spf1" not in v]
    dns(DOMINIO, "TXT", altri + ['"v=spf1 include:amazonses.com ~all"'])
    dns(f"_dmarc.{DOMINIO}", "TXT", [f'"v=DMARC1; p=none; rua=mailto:dmarc@{DOMINIO}"'])
    print("  SPF del dominio e DMARC (p=none: si osserva, non si scarta ancora)")

    # ---- 2. La destinazione dell'inoltro, verificata finche' si e' in sandbox.
    print("\n== 2. La destinazione dell'inoltro")
    if not identita(DESTINAZIONE):
        ses2.create_email_identity(EmailIdentity=DESTINAZIONE, Tags=ETICHETTE)
        print(f"  AWS ha mandato a {DESTINAZIONE} un link di verifica: va cliccato")
    else:
        print("  gia' chiesta" + (" e verificata" if identita(DESTINAZIONE)["VerifiedForSendingStatus"] else ": manca il clic nel link"))

    # ---- 3. La ricezione: bucket, Lambda, regola, MX.
    print("\n== 3. La ricezione")
    if esiste(s3.head_bucket, Bucket=BUCKET) is None:
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGIONE})
        print(f"  bucket {BUCKET} creato")
    s3.put_public_access_block(Bucket=BUCKET, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_tagging(Bucket=BUCKET, Tagging={"TagSet": ETICHETTE})
    s3.put_bucket_lifecycle_configuration(Bucket=BUCKET, LifecycleConfiguration={"Rules": [{
        "ID": "posta-dopo-90-giorni", "Filter": {"Prefix": "in/"}, "Status": "Enabled", "Expiration": {"Days": 90}}]})
    s3.put_bucket_policy(Bucket=BUCKET, Policy=json.dumps({"Version": "2012-10-17", "Statement": [{
        "Sid": "SesScriveLaPosta", "Effect": "Allow", "Principal": {"Service": "ses.amazonaws.com"},
        "Action": "s3:PutObject", "Resource": f"arn:aws:s3:::{BUCKET}/in/*",
        "Condition": {"StringEquals": {"aws:SourceAccount": CONTO}, "ArnLike": {"aws:SourceArn": ARN_REGOLA}}}]}))
    print("  bucket privato, posta cancellata dopo 90 giorni, SES puo' solo scriverci")

    fiducia = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
                                                         "Action": "sts:AssumeRole"}]}
    ruolo = esiste(iam.get_role, RoleName=FUNZIONE)
    if not ruolo:
        ruolo = iam.create_role(RoleName=FUNZIONE, AssumeRolePolicyDocument=json.dumps(fiducia), Tags=ETICHETTE,
                                Description="Inoltro della posta di responsarsm.com")
        print("  ruolo della Lambda creato")
    iam.put_role_policy(RoleName=FUNZIONE, PolicyName="InoltroPosta", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{BUCKET}/in/*"},
            # In sandbox SES controlla i permessi anche sull'identita' del destinatario
            # verificato: senza la Gmail qui, l'inoltro falliva con AccessDenied (02/10).
            {"Effect": "Allow", "Action": ["ses:SendEmail", "ses:SendRawEmail"],
             "Resource": [ARN_IDENTITA, f"arn:aws:ses:{REGIONE}:{CONTO}:identity/{DESTINAZIONE}"]},
            {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": f"arn:aws:logs:{REGIONE}:{CONTO}:log-group:/aws/lambda/{FUNZIONE}:*"}]}))
    gruppo = f"/aws/lambda/{FUNZIONE}"
    esiste(logs.create_log_group, logGroupName=gruppo, eccezioni=("ResourceAlreadyExistsException",))
    logs.put_retention_policy(logGroupName=gruppo, retentionInDays=30)

    pacco = io.BytesIO()
    with zipfile.ZipFile(pacco, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(RADICE / "aws" / "inoltro_posta.py", "inoltro_posta.py")
    variabili = {"Variables": {"DESTINAZIONE": DESTINAZIONE, "INOLTRO": INOLTRO, "BUCKET": BUCKET, "PREFISSO": "in/"}}
    if esiste(lam.get_function, FunctionName=FUNZIONE):
        lam.update_function_code(FunctionName=FUNZIONE, ZipFile=pacco.getvalue())
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNZIONE)
        lam.update_function_configuration(FunctionName=FUNZIONE, Environment=variabili)
        print("  Lambda aggiornata")
    else:
        for tentativo in range(12):   # un ruolo appena creato impiega qualche secondo a essere usabile
            try:
                lam.create_function(FunctionName=FUNZIONE, Runtime="python3.13", Role=ruolo["Role"]["Arn"],
                                    Handler="inoltro_posta.gestore", Code={"ZipFile": pacco.getvalue()},
                                    Timeout=30, MemorySize=256, Architectures=["arm64"], Environment=variabili,
                                    Description="Inoltra la posta di responsarsm.com", Tags={e["Key"]: e["Value"] for e in ETICHETTE})
                break
            except lam.exceptions.InvalidParameterValueException:
                time.sleep(5)
        else:
            raise SystemExit("  la Lambda non si crea: il ruolo non e' ancora usabile. Rilancia fra un minuto.")
        print("  Lambda creata")
    lam.get_waiter("function_active_v2").wait(FunctionName=FUNZIONE)
    arn_funzione = lam.get_function(FunctionName=FUNZIONE)["Configuration"]["FunctionArn"]
    esiste(lam.add_permission, FunctionName=FUNZIONE, StatementId="SesInoltro", Action="lambda:InvokeFunction",
           Principal="ses.amazonaws.com", SourceAccount=CONTO, SourceArn=ARN_REGOLA, eccezioni=("ResourceConflictException",))

    esiste(ses1.create_receipt_rule_set, RuleSetName=INSIEME, eccezioni=("AlreadyExists",))
    regola = {"Name": REGOLA, "Enabled": True, "TlsPolicy": "Optional", "ScanEnabled": True, "Recipients": [DOMINIO],
              "Actions": [{"S3Action": {"BucketName": BUCKET, "ObjectKeyPrefix": "in/"}},
                          {"LambdaAction": {"FunctionArn": arn_funzione, "InvocationType": "Event"}}]}
    if esiste(ses1.describe_receipt_rule, RuleSetName=INSIEME, RuleName=REGOLA, eccezioni=("RuleDoesNotExist",)):
        ses1.update_receipt_rule(RuleSetName=INSIEME, Rule=regola)
    else:
        ses1.create_receipt_rule(RuleSetName=INSIEME, Rule=regola)
    attivo = (ses1.describe_active_receipt_rule_set().get("Metadata") or {}).get("Name")
    if attivo and attivo != INSIEME:
        raise SystemExit(f"  e' gia' attivo l'insieme di regole {attivo!r}: non lo sostituisco. Avvisa Claude.")
    ses1.set_active_receipt_rule_set(RuleSetName=INSIEME)
    dns(DOMINIO, "MX", [f"10 inbound-smtp.{REGIONE}.amazonaws.com"])
    print(f"  regola attiva per tutto @{DOMINIO}: S3, poi la Lambda; MX verso SES {REGIONE}")

    # ---- Verifiche.
    print("\n== Verifiche (DKIM puo' metterci qualche minuto)")
    for _ in range(40):
        d = identita(DOMINIO)
        stato_dkim, stato_mf = d["DkimAttributes"]["Status"], d.get("MailFromAttributes", {}).get("MailFromDomainStatus")
        if stato_dkim == "SUCCESS" and stato_mf == "SUCCESS":
            break
        time.sleep(15)
    print(f"  DKIM {stato_dkim}, MAIL FROM {stato_mf}, pronto a spedire: {d['VerifiedForSendingStatus']}")
    if stato_dkim != "SUCCESS":
        print("  Non ancora verificato: rilancia lo stesso comando fra qualche minuto per controllare.")


def sito():
    print("\n== Il sito spedisce la demo con SES")
    d = identita(DOMINIO)
    if not (d and d["VerifiedForSendingStatus"]):
        raise SystemExit("  il dominio non e' ancora verificato su SES: prima `conferma`")
    # L'immagine in produzione deve contenere il codice che sa usare SES: senza,
    # togliere la password SMTP fermerebbe le email della demo.
    con_ses = subprocess.run(["git", "log", "-1", "--format=%h", "-S", "_ses()", "--", "src/servizio/demo.py"],
                             cwd=RADICE, capture_output=True, text=True).stdout.strip()
    immagini = sorted(ecr.describe_images(repositoryName="graphresponsa")["imageDetails"], key=lambda x: x["imagePushedAt"])
    commit = next((t for t in immagini[-1].get("imageTags", []) if t != "latest"), None)
    dentro = commit and subprocess.run(["git", "merge-base", "--is-ancestor", con_ses, commit], cwd=RADICE).returncode == 0
    if not (con_ses and dentro):
        raise SystemExit(f"  l'immagine piu' recente ({commit}) non contiene ancora il codice SES ({con_ses or '?'}): "
                         "prima committa e lancia .\\aws\\rilascia-backend.ps1")
    print(f"  l'immagine {commit} contiene il codice SES ({con_ses})")
    ruolo = td["taskDefinition"]["taskRoleArn"].split("/")[-1]
    iam.put_role_policy(RoleName=ruolo, PolicyName="PostaSes", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["ses:SendEmail", "ses:SendRawEmail"],
                                                "Resource": ARN_IDENTITA}]}))
    print(f"  il ruolo {ruolo} puo' spedire da {DOMINIO}")

    nuova = dict(td["taskDefinition"])
    for campo in ("taskDefinitionArn", "revision", "status", "requiresAttributes", "compatibilities",
                  "registeredAt", "registeredBy", "deregisteredAt"):
        nuova.pop(campo, None)
    c = dict(nuova["containerDefinitions"][0])
    amb = {e["name"]: e["value"] for e in c.get("environment", [])}
    amb.update(DEMO_MITTENTE=DEMO_MITTENTE, DEMO_DESTINATARI=DEMO_DESTINATARI)
    c["environment"] = [{"name": k, "value": v} for k, v in sorted(amb.items())]
    c["secrets"] = [x for x in c.get("secrets", []) if x["name"] != "DEMO_SMTP_PASSWORD"]
    nuova["containerDefinitions"] = [c] + nuova["containerDefinitions"][1:]
    if td.get("tags"):
        nuova["tags"] = td["tags"]
    registrata = ecs.register_task_definition(**nuova)["taskDefinition"]["taskDefinitionArn"]
    ecs.update_service(cluster=CLUSTER, service=SERVIZIO, taskDefinition=registrata)
    print(f"  {registrata.split('/')[-1]}: demo da {DEMO_MITTENTE} a {DEMO_DESTINATARI}, senza password SMTP. Rilascio in corso")
    inizio = time.time()
    while time.time() - inizio < 600:
        sv = ecs.describe_services(cluster=CLUSTER, services=[SERVIZIO])["services"][0]
        primo = next(x for x in sv["deployments"] if x["status"] == "PRIMARY")
        if primo["rolloutState"] == "COMPLETED" and len(sv["deployments"]) == 1:
            break
        if primo["rolloutState"] == "FAILED":
            raise SystemExit("  rilascio fallito: il task di prima continua a servire. Avvisa Claude.")
        time.sleep(20)
    with urllib.request.urlopen(f"{SITO}/salute", timeout=20) as r:
        print(f"  rilascio completato, /salute {r.status}")


def produzione():
    print("\n== Richiesta di uscita dalla sandbox")
    d = identita(DOMINIO)
    if not (d and d["VerifiedForSendingStatus"]):
        raise SystemExit("  prima il dominio verificato (`conferma`): chi esamina la richiesta lo controlla")
    richiesta = dict(
        MailType="TRANSACTIONAL", WebsiteURL=SITO, ContactLanguage="EN", ProductionAccessEnabled=True,
        AdditionalContactEmailAddresses=[DESTINAZIONE],
        UseCaseDescription=(
            "Responsa (https://responsarsm.com) is a legal research service for the law of the Republic of San "
            "Marino. Our customers are law firms and public offices. Users cannot sign up by themselves: our team "
            "creates each account in Amazon Cognito after the customer has agreed to use the service.\n\n"
            "We send only transactional email, from our verified domain responsarsm.com (Easy DKIM, SPF through "
            "the custom MAIL FROM domain mail.responsarsm.com, DMARC):\n"
            "1. Amazon Cognito account email: the temporary password when we create a user's account, and when a "
            "registered user asks for a new password on our sign-in page. Example: subject 'Responsa: la tua "
            "password temporanea', a short Italian text with the temporary password and a link to "
            "https://responsarsm.com. This is why we need production access: these messages go to our users' "
            "own addresses, which we cannot verify one by one.\n"
            "2. A notification to our own team: when someone fills in the 'Book a demo' form on our website we "
            "send one email to our own address demo@responsarsm.com, with the requester as Reply-To. We never "
            "email the requester automatically.\n"
            "3. Inbound email for our domain is received by SES and forwarded only to our own team mailbox, a "
            "verified identity. Messages that SES marks as spam or virus are not forwarded.\n\n"
            "We do not send marketing, newsletters or any bulk email, and we never use purchased, rented or "
            "scraped lists. Expected volume: about 10 emails per day, under 300 per month, never above 50 per "
            "day.\n\n"
            "Bounces and complaints: the account-level suppression list is enabled for both, and email feedback "
            "forwarding is enabled, so every bounce or complaint reaches our team mailbox. We then correct the "
            "address or disable the account in Cognito. Once production access is granted we will configure "
            "Amazon Cognito to send through this SES identity."))
    try:
        ses2.put_account_details(**richiesta)
    except ses2.exceptions.ConflictException:
        # Dopo un rifiuto l'API non accetta un nuovo invio (visto il 04/10): si risponde al caso,
        # dalla console, e il Support Center via API vuole un piano di supporto a pagamento.
        caso = ((ses2.get_account().get("Details") or {}).get("ReviewDetails") or {}).get("CaseId")
        print(f"  AWS non accetta un nuovo invio dopo il rifiuto. Rispondi al caso {caso} nel Support "
              f"Center, da root: https://support.console.aws.amazon.com/support/home#/case/?displayId={caso}\n"
              "  Testo da incollare:\n")
        print(richiesta["UseCaseDescription"])
        return
    stato = (ses2.get_account().get("Details") or {}).get("ReviewDetails", {})
    print(f"  richiesta inviata: {stato.get('Status')} (caso {stato.get('CaseId')}). AWS risponde di solito entro un giorno.")


def prova():
    print("\n== Email di prova")
    r = ses2.send_email(FromEmailAddress=DEMO_MITTENTE, Destination={"ToAddresses": [DEMO_DESTINATARI]},
                        Content={"Simple": {"Subject": {"Data": "Prova della posta di Responsa", "Charset": "UTF-8"},
                                            "Body": {"Text": {"Data": "Se questa email e' arrivata in Gmail, la posta "
                                                              "del dominio funziona: spedita da SES, ricevuta da SES, "
                                                              "inoltrata dalla Lambda.", "Charset": "UTF-8"}}}})
    print(f"  spedita ({r['MessageId']}) a {DEMO_DESTINATARI}: deve arrivare in {DESTINAZIONE} entro un minuto "
          "(guarda anche nello spam)")


{"conferma": conferma, "sito": sito, "produzione": produzione, "prova": prova}[COMANDO]()
