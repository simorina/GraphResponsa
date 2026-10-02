"""Le prove di "Prenota una demo": salvataggio, email, difese del modulo pubblico.

    .venv\\Scripts\\python.exe scripts\\prova_demo.py

Non tocca DynamoDB ne' la posta: il salvataggio e il server SMTP sono
sostituiti da oggetti che registrano cosa ricevono.
"""
import os
import pathlib
import sys

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RADICE), str(RADICE / "src")]
os.environ["TABELLA_CHECKPOINT"] = ""
os.environ["TABELLA_SCRITTURE"] = ""

from servizio import archivio, demo  # noqa: E402


class SmtpFinto:
    def __init__(self):
        self.messaggi = []

    def send_message(self, m):
        self.messaggi.append(m)


salvate = []
guasto = {"salva": False, "smtp": False}


def salva_finto(r):
    if guasto["salva"]:
        raise RuntimeError("DynamoDB giu'")
    salvate.append(r)
    return True


class SmtpRotto:
    def send_message(self, m):
        raise OSError("SMTP giu'")


class SesFinto:
    def __init__(self):
        self.inviate = []

    def send_email(self, **k):
        self.inviate.append(k)


class SesRotto:
    def send_email(self, **k):
        raise OSError("SES giu'")


archivio.salva_richiesta_demo = salva_finto
archivio.T_DEMO = "tabella-prova"
demo.MITTENTE = "mittente@esempio.sm"
demo.DESTINATARI = ["commerciale@esempio.sm"]
demo.SMTP_PASSWORD = "finta"


def azzera():
    salvate.clear()
    demo._per_ip.clear()
    demo._totale.clear()
    guasto.update(salva=False, smtp=False)


def prova():
    errori = 0

    def controlla(nome, ok, dettaglio=""):
        nonlocal errori
        errori += not ok
        print(f'  {"OK " if ok else "NO "} {nome:<58} {dettaglio}')

    print("richiesta valida")
    azzera()
    smtp = SmtpFinto()
    demo.registra("Giulia Terenzi", "giulia@studio.sm", "Studio Terenzi", "Avvocata",
                  "Vorrei vedere come cita le norme sul lavoro.", "81.2.3.4", smtp=smtp)
    m = smtp.messaggi[0] if smtp.messaggi else None
    controlla("salvata una volta, con i campi", len(salvate) == 1 and salvate[0]["ente"] == "Studio Terenzi")
    controlla("email spedita alla casella commerciale", m is not None and m["To"] == "commerciale@esempio.sm")
    controlla("mittente configurato", m is not None and m["From"] == "mittente@esempio.sm")
    controlla("Reply-To: chi ha chiesto la demo", m is not None and m["Reply-To"] == "giulia@studio.sm")
    controlla("oggetto con nome ed ente", m is not None and m["Subject"] == "Richiesta demo: Giulia Terenzi (Studio Terenzi)")
    controlla("il messaggio e' nel corpo", m is not None and "norme sul lavoro" in m.get_content())

    print("\ndifese")
    azzera()
    smtp = SmtpFinto()
    demo.registra("Bot", "bot@spam.xx", "", "", "", "9.9.9.9", trappola="http://spam", smtp=smtp)
    controlla("campo trappola compilato: nulla salvato, nulla spedito", not salvate and not smtp.messaggi)

    azzera()
    smtp = SmtpFinto()
    for i in range(demo.PER_IP[0] + 1):
        demo.registra(f"Persona {i}", f"p{i}@x.sm", "", "", "", "5.5.5.5", smtp=smtp)
    controlla(f"stesso IP oltre {demo.PER_IP[0]} richieste l'ora: fermato",
              len(salvate) == demo.PER_IP[0], f"{len(salvate)} salvate")

    azzera()
    smtp = SmtpFinto()
    demo.registra("Mario\r\nBcc: vittima@altrove.sm", "mario@x.sm", "Ente\nX", "", "", "6.6.6.6", smtp=smtp)
    m = smtp.messaggi[0] if smtp.messaggi else None
    controlla("a capo nel nome: nessuna intestazione iniettata",
              m is not None and m["Bcc"] is None and "\n" not in m["Subject"], str(m["Subject"]) if m else "")

    print("\nguasti")
    azzera()
    guasto["salva"] = True
    smtp = SmtpFinto()
    try:
        demo.registra("Anna", "anna@x.sm", "", "", "", "7.7.7.7", smtp=smtp)
        ok = len(smtp.messaggi) == 1
    except demo.Indisponibile:
        ok = False
    controlla("DynamoDB giu', email partita: nessun errore all'utente", ok)

    azzera()
    try:
        demo.registra("Anna", "anna@x.sm", "", "", "", "7.7.7.8", smtp=SmtpRotto())
        ok = len(salvate) == 1
    except demo.Indisponibile:
        ok = False
    controlla("posta giu', richiesta salvata: nessun errore all'utente", ok)

    azzera()
    guasto["salva"] = True
    try:
        demo.registra("Anna", "anna@x.sm", "", "", "", "7.7.7.9", smtp=SmtpRotto())
        ok = False
    except demo.Indisponibile:
        ok = True
    controlla("entrambi giu': Indisponibile (-> 503)", ok)

    print("\nSES, la strada di produzione (nessuna password SMTP)")
    demo.SMTP_PASSWORD = ""
    try:
        azzera()
        ses = SesFinto()
        demo.registra("Giulia Terenzi", "giulia@studio.sm", "Studio Terenzi", "Avvocata",
                      "Vorrei vedere come cita le norme sul lavoro.", "81.2.3.5", ses=ses)
        k = ses.inviate[0] if ses.inviate else {}
        semplice = k.get("Content", {}).get("Simple", {})
        controlla("spedita con SES, una volta", len(ses.inviate) == 1)
        controlla("dal mittente configurato alla casella commerciale",
                  k.get("FromEmailAddress") == "mittente@esempio.sm"
                  and k.get("Destination") == {"ToAddresses": ["commerciale@esempio.sm"]})
        controlla("Reply-To: chi ha chiesto la demo", k.get("ReplyToAddresses") == ["giulia@studio.sm"])
        controlla("oggetto con nome ed ente",
                  semplice.get("Subject", {}).get("Data") == "Richiesta demo: Giulia Terenzi (Studio Terenzi)")
        controlla("il messaggio e' nel corpo", "norme sul lavoro" in semplice.get("Body", {}).get("Text", {}).get("Data", ""))

        azzera()
        try:
            demo.registra("Anna", "anna@x.sm", "", "", "", "7.7.7.10", ses=SesRotto())
            ok = len(salvate) == 1
        except demo.Indisponibile:
            ok = False
        controlla("SES giu', richiesta salvata: nessun errore all'utente", ok)

        azzera()
        guasto["salva"] = True
        try:
            demo.registra("Anna", "anna@x.sm", "", "", "", "7.7.7.11", ses=SesRotto())
            ok = False
        except demo.Indisponibile:
            ok = True
        controlla("SES e DynamoDB giu': Indisponibile (-> 503)", ok)
    finally:
        demo.SMTP_PASSWORD = "finta"

    print("\nendpoint")
    from fastapi.testclient import TestClient  # noqa: E402
    import server  # noqa: E402

    ricevute = []
    originale = demo.registra
    client = TestClient(server.app)
    buona = {"nome": "Giulia Terenzi", "email": "giulia@studio.sm", "ente": "Studio Terenzi",
             "ruolo": "Avvocata", "messaggio": "", "consenso": True, "sito": ""}
    try:
        demo.registra = lambda *a, **k: ricevute.append((a, k))
        r = client.post("/richiesta-demo", json=buona)
        controlla("richiesta valida: {ok: true}", r.status_code == 200 and r.json() == {"ok": True}, r.text)
        r = client.post("/richiesta-demo", json={**buona, "consenso": False})
        controlla("senza consenso: 422", r.status_code == 422)
        r = client.post("/richiesta-demo", json={**buona, "email": "non-una-email"})
        controlla("email non valida: 422", r.status_code == 422)
        r = client.post("/richiesta-demo", json={**buona, "nome": "A"})
        controlla("nome troppo corto: 422", r.status_code == 422)

        def giu(*a, **k):
            raise demo.Indisponibile("giu'")
        demo.registra = giu
        r = client.post("/richiesta-demo", json=buona)
        controlla("non registrata: 503", r.status_code == 503)
    finally:
        demo.registra = originale

    print("\nfallite:", errori)
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(prova())
