"""
Inoltra la posta che arriva a @responsarsm.com a una casella esterna.

SES riceve per tutto il dominio (record MX verso inbound-smtp.eu-central-1),
salva il messaggio intero in S3 e chiama questa funzione. Qui lo si rilegge e
lo si rispedisce alla DESTINAZIONE (la Gmail del team).

Non si puo' rispedire com'e': il From e' di chi ha scritto, e SES spedisce
solo da identita' verificate. Il messaggio parte quindi da INOLTRO, un
indirizzo del dominio, con il nome di chi ha scritto nel From ("Giulia
Terenzi via Responsa") e il suo indirizzo nel Reply-To: rispondere dalla Gmail
scrive a lui. Il corpo e gli allegati restano quelli originali.

Non si rispediscono i messaggi che SES giudica spam o con un virus: in Gmail
un "Segnala spam" su un inoltro diventerebbe un reclamo contro il nostro
account SES, e i reclami decidono se SES ci lascia spedire. Restano comunque
nel bucket per 90 giorni, quindi un messaggio buono giudicato male si
recupera. Non si rispedisce nemmeno cio' che e' gia' passato di qui: un
inoltro che torna al dominio girerebbe in tondo.
"""
import email
import email.policy
import email.utils
import os

MARCHIO = "X-Responsa-Inoltrato"
# Intestazioni che non possono sopravvivere alla rispedizione: la firma DKIM
# del mittente non torna piu' (si cambia il From), Return-Path e Sender
# parlano dell'invio originale, il Message-ID lo assegna SES.
DA_TOGLIERE = ("DKIM-Signature", "Return-Path", "Sender", "Message-ID")


def riscrivi(grezzo: bytes, inoltro: str) -> bytes | None:
    """Il messaggio pronto da rispedire, o None se non va rispedito."""
    m = email.message_from_bytes(grezzo, policy=email.policy.compat32)
    if m.get(MARCHIO):
        return None
    nome, indirizzo = email.utils.parseaddr(m.get("From", ""))
    if indirizzo.lower() == email.utils.parseaddr(inoltro)[1].lower():
        return None

    for intestazione in DA_TOGLIERE:
        del m[intestazione]
    if not m.get("Reply-To") and indirizzo:
        m["Reply-To"] = indirizzo
    del m["From"]
    m["From"] = email.utils.formataddr((f"{nome or indirizzo or 'Sconosciuto'} via Responsa",
                                        email.utils.parseaddr(inoltro)[1]), charset="utf-8")
    m[MARCHIO] = "1"
    return m.as_bytes(policy=email.policy.compat32.clone(linesep="\r\n"))


def gestore(evento, contesto):
    """Il punto d'ingresso della Lambda: una notifica di SES per messaggio."""
    import boto3

    destinazione = os.environ["DESTINAZIONE"]
    inoltro = os.environ["INOLTRO"]
    bucket = os.environ["BUCKET"]
    prefisso = os.environ.get("PREFISSO", "in/")
    s3 = boto3.client("s3")
    ses = boto3.client("sesv2")
    for record in evento.get("Records", []):
        dati = record["ses"]
        ricevuta = dati["receipt"]
        giudizi = {nome: ricevuta.get(f"{nome}Verdict", {}).get("status") for nome in ("virus", "spam")}
        if "FAIL" in giudizi.values():
            print(f"non inoltrato ({', '.join(n for n, g in giudizi.items() if g == 'FAIL')}), "
                  f"resta nel bucket: {prefisso}{dati['mail']['messageId']}")
            continue
        grezzo = s3.get_object(Bucket=bucket, Key=prefisso + dati["mail"]["messageId"])["Body"].read()
        pronto = riscrivi(grezzo, inoltro)
        if pronto is None:
            print(f"non rispedito (gia' inoltrato o dal nostro indirizzo): {dati['mail']['messageId']}")
            continue
        ses.send_email(Destination={"ToAddresses": [destinazione]}, Content={"Raw": {"Data": pronto}})
        print(f"inoltrato {dati['mail']['messageId']} a {destinazione}")
