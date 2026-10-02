"""Le prove dell'inoltro della posta (aws/inoltro_posta.py). Nessuna chiamata di rete:
S3 e SES sono sostituiti da oggetti che registrano cosa ricevono.

    .venv\\Scripts\\python.exe scripts\\prova_inoltro.py
"""
import base64
import email
import email.header
import email.policy
import pathlib
import sys
import types

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "aws"))

import inoltro_posta as I  # noqa: E402

INOLTRO = "inoltro@responsarsm.com"
PDF = b"%PDF-1.4 finto\x00\x01\x02" * 40

SEMPLICE = (b"Return-Path: <giulia@studio.sm>\r\n"
            b"DKIM-Signature: v=1; a=rsa-sha256; d=studio.sm; s=x; b=abc\r\n"
            b"Message-ID: <123@studio.sm>\r\n"
            b"From: Giulia Terenzi <giulia@studio.sm>\r\n"
            b"To: demo@responsarsm.com\r\n"
            b"Subject: Vorrei una demo\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n"
            b"Buongiorno, siamo uno studio di tre avvocati.\r\n")


def allegato():
    m = email.message.EmailMessage()
    m["From"] = "=?utf-8?q?Nicol=C3=B2_Bianchi?= <nicolo@ente.sm>"
    m["To"] = "info@responsarsm.com"
    m["Reply-To"] = "segreteria@ente.sm"
    m["Subject"] = "Delibera"
    m.set_content("In allegato la delibera.")
    m.add_attachment(PDF, maintype="application", subtype="pdf", filename="delibera.pdf")
    return m.as_bytes()


def da(grezzo):
    return email.message_from_bytes(grezzo, policy=email.policy.default)


errori = 0


def controlla(nome, ok, dettaglio=""):
    global errori
    errori += not ok
    print(f'  {"OK " if ok else "NO "} {nome:<62} {"" if ok else dettaglio}')


print("messaggio semplice")
r = I.riscrivi(SEMPLICE, INOLTRO)
m = da(r)
controlla("From: il nome di chi scrive, dal nostro indirizzo",
          m["From"] == "Giulia Terenzi via Responsa <inoltro@responsarsm.com>", str(m["From"]))
controlla("Reply-To: chi ha scritto", m["Reply-To"] == "giulia@studio.sm", str(m["Reply-To"]))
controlla("tolte firma DKIM, Return-Path e Message-ID",
          not any(m[h] for h in ("DKIM-Signature", "Return-Path", "Message-ID")))
controlla("destinatario originale e oggetto intatti", m["To"] == "demo@responsarsm.com" and m["Subject"] == "Vorrei una demo")
controlla("corpo intatto", "siamo uno studio di tre avvocati" in m.get_content())
controlla("righe in CRLF, come vuole SMTP", b"\r\n" in r and b"\n" not in r.replace(b"\r\n", b""))

print("\nnome con accenti, Reply-To gia' presente, allegato")
m = da(I.riscrivi(allegato(), INOLTRO))
controlla("il nome con l'accento arriva intero", m["From"].addresses[0].display_name == "Nicolò Bianchi via Responsa",
          str(m["From"]))
controlla("il Reply-To di chi scrive si rispetta", m["Reply-To"] == "segreteria@ente.sm", str(m["Reply-To"]))
pdf = [p for p in m.iter_attachments() if p.get_filename() == "delibera.pdf"]
controlla("l'allegato arriva identico, byte per byte", bool(pdf) and pdf[0].get_content() == PDF)

print("\nspam e giri in tondo")
m = da(I.riscrivi(SEMPLICE, INOLTRO, spam=True))
controlla("lo spam si segna nell'oggetto", m["Subject"] == "[SPAM] Vorrei una demo", str(m["Subject"]))
controlla("un messaggio gia' inoltrato non riparte", I.riscrivi(I.riscrivi(SEMPLICE, INOLTRO), INOLTRO) is None)
proprio = SEMPLICE.replace(b"From: Giulia Terenzi <giulia@studio.sm>", b"From: Responsa <inoltro@responsarsm.com>")
controlla("un messaggio dal nostro indirizzo di inoltro non riparte", I.riscrivi(proprio, INOLTRO) is None)
anonimo = SEMPLICE.replace(b"From: Giulia Terenzi <giulia@studio.sm>", b"From: mario@x.sm")
controlla("senza nome si usa l'indirizzo",
          da(I.riscrivi(anonimo, INOLTRO))["From"] == '"mario@x.sm via Responsa" <inoltro@responsarsm.com>'
          or da(I.riscrivi(anonimo, INOLTRO))["From"].addresses[0].display_name == "mario@x.sm via Responsa")

print("\nla Lambda, con S3 e SES finti")
spediti, letti = [], []


class S3:
    def get_object(self, Bucket, Key):
        letti.append((Bucket, Key))
        return {"Body": types.SimpleNamespace(read=lambda: SEMPLICE)}


class Ses:
    def send_email(self, **k):
        spediti.append(k)


sys.modules["boto3"] = types.SimpleNamespace(client=lambda nome: S3() if nome == "s3" else Ses())
I.os.environ.update(DESTINAZIONE="squadra@gmail.com", INOLTRO=INOLTRO, BUCKET="posta", PREFISSO="in/")


def evento(id_, virus="PASS", spam="PASS"):
    return {"Records": [{"ses": {"mail": {"messageId": id_},
                                 "receipt": {"virusVerdict": {"status": virus}, "spamVerdict": {"status": spam}}}}]}


I.gestore(evento("abc"), None)
controlla("legge il messaggio dalla chiave giusta", letti == [("posta", "in/abc")], str(letti))
controlla("lo spedisce solo alla destinazione",
          len(spediti) == 1 and spediti[0]["Destination"] == {"ToAddresses": ["squadra@gmail.com"]})
controlla("...con il From riscritto", b"via Responsa <inoltro@responsarsm.com>" in spediti[0]["Content"]["Raw"]["Data"])
spediti.clear()
I.gestore(evento("def", virus="FAIL"), None)
controlla("con un virus non spedisce niente", not spediti)
I.gestore(evento("ghi", spam="FAIL"), None)
controlla("lo spam si inoltra segnato", len(spediti) == 1 and b"[SPAM]" in spediti[0]["Content"]["Raw"]["Data"])

print("\nfallite:", errori)
sys.exit(1 if errori else 0)
