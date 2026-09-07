"""
Misura quanto l'agente e' incostante: stessa domanda, risposte diverse.

Il difetto e' reale ma finora l'avevo solo visto, non contato. Sulla stessa
domanda - "chi puo' accedere al bonus prima casa" - il servizio ha dato una
volta la disciplina vigente e una volta quella scaduta, e in un altro giro ha
coperto uno dei due regimi invece di entrambi.

Qui si ripete ogni domanda piu' volte e si misura quanto le risposte differiscono
su cio' che conta:

  fatti      i dati che DEVONO comparire (una cifra, un'eta', un id di norma):
             o ci sono in tutte le esecuzioni, o l'agente e' incostante su quel
             punto. E' la misura che pesa di piu'.
  atti       quali norme vengono citate: due risposte che citano atti diversi
             mandano il lettore in due posti diversi.
  chiamate   quanti strumenti invoca: la dispersione dice se la traiettoria e'
             stabile o se ogni volta prende una strada nuova.

Non si giudica se la risposta e' giusta - a quello serve il benchmark - ma se
e' SEMPRE LA STESSA. Un assistente giuridico che oscilla non e' affidabile
nemmeno quando ha ragione, perche' chi legge non sa quale delle due versioni
ha ricevuto.

    .venv/Scripts/python.exe scripts/misura_incostanza.py         # 3 giri
    .venv/Scripts/python.exe scripts/misura_incostanza.py 5       # 5 giri
"""

import json
import re
import statistics
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

RE_ATTO = re.compile(
    r"(?:legge|l\.|lq\.?|lc\.?|d\.l\.|dl\.?|d\.d\.|dd\.?|decreto|regolamento|reg\.|r\.)"
    r"[\s ]*(?:n[.°]?[\s ]*)?(\d{1,4})[\s ]*/[\s ]*((?:19|20)\d{2})",
    re.IGNORECASE)

# Ogni domanda porta i fatti che una risposta completa deve contenere. Sono
# scelti perche' verificati sul testo in archivio, non perche' comodi.
DOMANDE = [
    ("chi puo accedere al bonus prima casa?",
     {"eta 40 anni": ("quaranta", "40 anni"),
      "scadenza 2026": ("31 dicembre 2026", "2026"),
      "requisito non possedere": ("non possiedano", "non possedere", "non essere titolar"),
      "gia usufruito": ("gia usufruito", "già usufruito")}),
    ("quanto pago per una multa da divieto di sosta?",
     {"un importo in euro": ("€", "euro")}),
    ("chi e' considerato non autosufficiente?",
     {"cura della persona": ("cura della propria persona", "provvedere alla cura"),
      "vita di relazione": ("vita di relazione",)}),
    ("quanto tempo ho per fare ricorso contro un risultato elettorale?",
     {"trenta giorni": ("trenta giorni", "30 giorni"),
      "perentorio": ("perentori",)}),
    ("che documenti servono per sposarsi?",
     {"atto di nascita": ("atto di nascita",),
      "pubblicazioni": ("pubblicazion",)}),
    ("quanti giorni di malattia posso prendere?",
     {"riferimento a un atto": ("art",)}),
]


def consulta(domanda):
    from agente.agente import rispondi
    testo, strumenti, costo = "", [], 0.0
    for ev in rispondi(domanda, str(uuid.uuid4())):
        if ev["tipo"] == "testo":
            testo = ev["testo"]
        elif ev["tipo"] == "strumento":
            strumenti.append(ev["nome"])
        elif ev["tipo"] == "fine":
            costo = float(ev.get("costo", 0))
        elif ev["tipo"] == "errore":
            return {"testo": "", "strumenti": [], "costo": 0, "errore": ev["messaggio"][:50]}
    return {"testo": testo, "strumenti": strumenti, "costo": costo, "errore": None}


def main():
    giri = next((int(a) for a in sys.argv[1:] if a.isdigit()), 3)
    print(f"{len(DOMANDE)} domande x {giri} giri\n")

    esiti, righe = [], []
    for domanda, fatti in DOMANDE:
        prove = [consulta(domanda) for _ in range(giri)]
        vive = [p for p in prove if not p["errore"]]

        # Un fatto e' stabile se compare in tutte le esecuzioni, o in nessuna.
        # Se compare in alcune e non in altre, li' l'agente e' incostante.
        instabili = []
        for nome, varianti in fatti.items():
            presenze = sum(any(v.lower() in p["testo"].lower() for v in varianti)
                           for p in vive)
            if vive and 0 < presenze < len(vive):
                instabili.append(f"{nome} {presenze}/{len(vive)}")

        atti = [frozenset(RE_ATTO.findall(p["testo"])) for p in vive]
        atti_uguali = len(set(atti)) == 1 if atti else False
        chiamate = [len(p["strumenti"]) for p in vive]

        esiti.append({"domanda": domanda, "instabili": instabili,
                      "atti_uguali": atti_uguali, "chiamate": chiamate,
                      "errori": len(prove) - len(vive)})
        stato = "STABILE" if not instabili and atti_uguali else "OSCILLA"
        print(f"  [{stato}] {domanda[:46]:<48} chiamate {chiamate}")
        if instabili:
            print(f"            fatti incostanti: {', '.join(instabili)}")
        if not atti_uguali and len(set(atti)) > 1:
            print(f"            cita atti diversi fra i giri: {[sorted(a) for a in atti]}")
        righe += vive

    stabili = sum(1 for e in esiti if not e["instabili"] and e["atti_uguali"])
    tutti_instabili = [f for e in esiti for f in e["instabili"]]
    print(f"\n  domande stabili: {stabili}/{len(esiti)}")
    print(f"  fatti incostanti in totale: {len(tutti_instabili)}")
    disp = [statistics.pstdev(e["chiamate"]) for e in esiti if len(e["chiamate"]) > 1]
    if disp:
        print(f"  dispersione delle chiamate: {statistics.mean(disp):.2f} di media")
    if righe:
        print(f"  costo del giro: ${sum(r['costo'] for r in righe):.2f}")


if __name__ == "__main__":
    main()
