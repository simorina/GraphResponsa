"""
Le richieste di demo dalla pagina di presentazione.

Due strade, e nessuna delle due basta da sola: la richiesta si salva in
DynamoDB (TABELLA_DEMO), dove resta anche se la posta si perde, e parte
un'email alla casella commerciale (DEMO_DESTINATARI), perche' una richiesta
che nessuno legge in giornata e' un contatto perso.

L'email parte via SMTP dalla casella del mittente (DEMO_MITTENTE), non da
Amazon SES: per ora e' una casella Gmail, e con Gmail serve una "password per
le app" (DEMO_SMTP_PASSWORD, nei segreti), non quella dell'account. Server e
porta si cambiano con DEMO_SMTP_HOST e DEMO_SMTP_PORT quando la casella
diventera' un'altra.

L'email ha come Reply-To l'indirizzo di chi chiede: rispondere dalla casella
commerciale scrive direttamente a lui.

Il modulo e' pubblico, quindi due difese: un campo nascosto che solo i bot
compilano, e un limite per IP. Oltre il limite, e col campo trappola pieno, la
risposta e' la stessa di una richiesta accolta: dire "rifiutata" insegnerebbe
al bot cosa cambiare.
"""
import logging
import os
import smtplib
import ssl
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from email.message import EmailMessage

from . import archivio

log = logging.getLogger(__name__)

MITTENTE = os.environ.get("DEMO_MITTENTE", "")
DESTINATARI = [d.strip() for d in os.environ.get("DEMO_DESTINATARI", MITTENTE).split(",") if d.strip()]
SMTP_HOST = os.environ.get("DEMO_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("DEMO_SMTP_PORT", "587"))
SMTP_PASSWORD = os.environ.get("DEMO_SMTP_PASSWORD", "")

PER_IP = (5, 60 * 60)            # richieste, finestra in secondi
TOTALE = (60, 24 * 60 * 60)      # tetto complessivo al giorno

_lucchetto = threading.Lock()
_per_ip: dict[str, deque] = {}
_totale: deque = deque()


class Indisponibile(Exception):
    """La richiesta non e' stata ne' salvata ne' spedita: va detto a chi la manda."""


def _entro_i_limiti(ip: str, adesso: float) -> bool:
    with _lucchetto:
        while _totale and adesso - _totale[0] > TOTALE[1]:
            _totale.popleft()
        coda = _per_ip.setdefault(ip, deque())
        while coda and adesso - coda[0] > PER_IP[1]:
            coda.popleft()
        for k in [k for k, c in _per_ip.items() if not c and k != ip]:
            del _per_ip[k]
        if len(_totale) >= TOTALE[0] or len(coda) >= PER_IP[0]:
            return False
        _totale.append(adesso)
        coda.append(adesso)
        return True


def _testo_email(r: dict) -> str:
    righe = [
        "Nuova richiesta di demo dalla pagina di presentazione.",
        "",
        f"Nome:         {r['nome']}",
        f"Email:        {r['email']}",
        f"Ente/studio:  {r.get('ente') or '-'}",
        f"Ruolo:        {r.get('ruolo') or '-'}",
        f"Ricevuta:     {r['creata']}",
        "",
        "Cosa vorrebbe chiedere a Responsa:",
        r.get("messaggio") or "-",
        "",
        "Rispondendo a questa email si scrive direttamente al richiedente.",
    ]
    return "\n".join(righe)


def _messaggio(r: dict) -> EmailMessage:
    m = EmailMessage()
    m["Subject"] = (f"Richiesta demo: {r['nome']}" + (f" ({r['ente']})" if r.get("ente") else ""))[:200]
    m["From"] = MITTENTE
    m["To"] = ", ".join(DESTINATARI)
    m["Reply-To"] = r["email"]
    m.set_content(_testo_email(r))
    return m


def _manda_email(r: dict, smtp=None) -> bool:
    """Spedisce l'avviso. `smtp` si passa solo dalle prove, al posto del server."""
    if not (MITTENTE and DESTINATARI and SMTP_PASSWORD):
        return False
    if smtp is not None:
        smtp.send_message(_messaggio(r))
        return True
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(MITTENTE, SMTP_PASSWORD)
        s.send_message(_messaggio(r))
    return True


def registra(nome: str, email: str, ente: str, ruolo: str, messaggio: str, ip: str,
             trappola: str = "", smtp=None) -> None:
    """Salva la richiesta e avvisa la casella commerciale.

    Solleva Indisponibile solo se non e' riuscita nessuna delle due cose: se
    una delle due va a buon fine la richiesta non e' persa, e l'altra si
    segnala nei log.
    """
    if trappola.strip():
        log.info("richiesta demo: campo trappola compilato, ignorata")
        return
    if not _entro_i_limiti(ip or "?", time.monotonic()):
        log.info("richiesta demo: oltre i limiti per %s", ip)
        return

    # Nome, ente e ruolo finiscono nell'oggetto dell'email: un "a capo" li'
    # dentro aggiungerebbe intestazioni (un Bcc verso chiunque). Una riga sola.
    def riga(s: str) -> str:
        return " ".join((s or "").split())

    richiesta = {
        "richiesta": str(uuid.uuid4()),
        "creata": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nome": riga(nome)[:120],
        "email": riga(email)[:254],
        "ente": riga(ente)[:160],
        "ruolo": riga(ruolo)[:80],
        "messaggio": (messaggio or "").strip()[:2000],
        "ip": (ip or "")[:64],
    }

    salvata = spedita = False
    try:
        salvata = archivio.salva_richiesta_demo(richiesta)
    except Exception as e:  # noqa: BLE001
        log.error("richiesta demo: salvataggio non riuscito: %s", e)
    try:
        spedita = _manda_email(richiesta, smtp=smtp)
    except Exception as e:  # noqa: BLE001
        log.error("richiesta demo: email non spedita: %s", e)

    if not (salvata or spedita):
        # In sviluppo, senza tabella e senza mittente, non e' un guasto: non
        # c'e' dove mandarla. Altrove si'.
        if not (archivio.T_DEMO or (MITTENTE and SMTP_PASSWORD)):
            log.warning("richiesta demo non conservata: ne' TABELLA_DEMO ne' la posta sono configurate")
            return
        raise Indisponibile("richiesta non salvata e non spedita")
    log.info("richiesta demo registrata (salvata=%s, spedita=%s)", salvata, spedita)
