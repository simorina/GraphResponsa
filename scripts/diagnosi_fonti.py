"""
Perche' l'atto atteso non compare nella risposta? Quattro cause, quattro rimedi.

Dopo aver corretto il controllo (52,6% -> 74,7%) resta un quarto di casi in cui
l'atto atteso non si trova nella risposta. "Fonte sbagliata" pero' non e' una
diagnosi: puo' voler dire cose molto diverse, e solo una si ripara nell'agente.

  recupero      l'atto non e' mai uscito dalla ricerca: e' un problema di
                retrieval, non di scrittura. L'agente non poteva citarlo.
  non_letto     la ricerca l'ha restituito ma l'agente non l'ha aperto ne'
                citato: ha risposto con un altro passo.
  altro_atto    ha citato un atto diverso. Puo' essere legittimo - due norme
                che dicono la stessa cosa - oppure un errore vero.
  non_cita      non ha citato niente: la risposta e' corretta nel merito ma
                priva di ancoraggio, che e' il difetto peggiore per chi legge.

Si riesegue la domanda salvando la risposta INTERA - il primo giro la troncava
a 1500 caratteri, e una citazione oltre quella soglia risultava assente.

    .venv/Scripts/python.exe scripts/diagnosi_fonti.py        # tutte
    .venv/Scripts/python.exe scripts/diagnosi_fonti.py 10     # le prime dieci
"""

import csv
import importlib.util
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def controllo():
    """cita_giusto() dal benchmark, per non averne due versioni divergenti."""
    sp = importlib.util.spec_from_file_location("b", ROOT / "scripts" / "esegui_benchmark.py")
    m = importlib.util.module_from_spec(sp)
    try:
        sp.loader.exec_module(m)
    except SystemExit:
        pass
    return m.cita_giusto


def consulta(domanda):
    from agente.agente import rispondi
    testo, viste, strumenti = "", set(), []
    for ev in rispondi(domanda, str(uuid.uuid4())):
        if ev["tipo"] == "testo":
            testo = ev["testo"]
        elif ev["tipo"] == "strumento":
            strumenti.append((ev["nome"], ev.get("argomenti")))
        elif ev["tipo"] == "fonti":
            viste = {f["norma"] for f in ev["fonti"] if f.get("norma")}
        elif ev["tipo"] == "errore":
            return None, set(), strumenti
    return testo, viste, strumenti


def main():
    limite = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)
    cita_giusto = controllo()

    esiti = list(csv.DictReader(open(OUT / "benchmark_esiti.csv", encoding="utf-8-sig"),
                                delimiter=";"))
    # solo quelle che falliscono ANCHE col controllo corretto
    casi = [x for x in esiti
            if x["esito"] != "errore" and x["riferimento"]
            and cita_giusto(x["risposta_agente"], x["riferimento"]) is False]
    if limite:
        casi = casi[:limite]
    print(f"Riesamino {len(casi)} casi con la risposta intera\n")

    conteggio = {"recupero": 0, "non_letto": 0, "altro_atto": 0,
                 "non_cita": 0, "in_realta_ok": 0, "errore": 0}
    dettaglio = []
    for x in casi:
        atteso = x["riferimento"].split()[0]
        testo, viste, strumenti = consulta(x["domanda"])
        if testo is None:
            conteggio["errore"] += 1
            continue

        if cita_giusto(testo, x["riferimento"]):
            causa = "in_realta_ok"      # c'era, ma oltre i 1500 caratteri
        elif atteso not in viste:
            causa = "recupero"
        elif not any(ch in testo for ch in ("/19", "/20")) and "art" not in testo.lower():
            causa = "non_cita"
        elif atteso in viste:
            causa = "non_letto"
        else:
            causa = "altro_atto"
        conteggio[causa] += 1
        dettaglio.append({"id": x["id"], "causa": causa, "atteso": atteso,
                          "viste": sorted(viste)[:6], "domanda": x["domanda"],
                          "risposta": testo})
        print(f"  [{causa:<12}] {x['id']}  atteso {atteso:<14} "
              f"{'trovato dalla ricerca' if atteso in viste else 'MAI restituito'}")

    (OUT / "diagnosi_fonti.json").write_text(
        json.dumps(dettaglio, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n  " + "-" * 52)
    for k, v in sorted(conteggio.items(), key=lambda x: -x[1]):
        if v:
            print(f"  {k:<14} {v:>3}")
    print(f"\n  Dettaglio: {OUT / 'diagnosi_fonti.json'}")


if __name__ == "__main__":
    main()
