"""
Un modello piu' grande risolve gli errori, o sono le domande a essere dure?

Il benchmark intero con Sonnet costerebbe una trentina di dollari, perche' sul
caso di prova ha fatto otto chiamate agli strumenti dove Haiku ne fa una, e la
storia accumulata cresce a ogni giro: $0,3284 contro $0,0135, ventiquattro
volte. Un sottoinsieme a caso non servirebbe: per distinguere qualche punto di
differenza servono tutte e cento le domande.

Qui si spende dove l'informazione sta: SOLO le domande che il modello attuale
ha sbagliato o risolto a meta'. Se il modello piu' grande le recupera, il collo
di bottiglia e' il modello e vale la pena progettare la versione economica. Se
non ne recupera nessuna, il limite e' altrove - nelle domande, nella verita' di
riferimento, o nell'archivio - e un modello piu' caro non lo sposta.

Il limite di questa prova, dichiarato: non dice se il modello grande
ROMPEREBBE domande che il piccolo risolve. E' un primo segnale, non un verdetto.

    .venv/Scripts/python.exe scripts/prova_modello.py claude-sonnet-5
    .venv/Scripts/python.exe scripts/prova_modello.py claude-sonnet-5 5
"""

import csv
import importlib.util
import json
import os
import re
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


def benchmark():
    """Giudice e controllo delle fonti dal benchmark, per non averne due versioni."""
    sp = importlib.util.spec_from_file_location("b", ROOT / "scripts" / "esegui_benchmark.py")
    m = importlib.util.module_from_spec(sp)
    try:
        sp.loader.exec_module(m)
    except SystemExit:
        pass
    return m


def consulta(domanda):
    from agente.agente import rispondi
    testo, strumenti, costo = "", 0, 0.0
    for ev in rispondi(domanda, str(uuid.uuid4())):
        if ev["tipo"] == "testo":
            testo = ev["testo"]
        elif ev["tipo"] == "strumento":
            strumenti += 1
        elif ev["tipo"] == "fine":
            costo = float(ev.get("costo", 0))
        elif ev["tipo"] == "errore":
            return None, strumenti, 0.0
    return testo, strumenti, costo


def main():
    modello = next((a for a in sys.argv[1:] if a.startswith("claude-")), None)
    if not modello:
        raise SystemExit("Serve il modello: es. claude-sonnet-5")
    os.environ["MODELLO"] = modello
    limite = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)

    from langchain_anthropic import ChatAnthropic
    b = benchmark()
    giudice = ChatAnthropic(model="claude-haiku-4-5", max_tokens=300,
                            api_key=os.environ["ANTHROPIC_API_KEY"])

    esiti = list(csv.DictReader(open(OUT / "benchmark_esiti_locale.csv", encoding="utf-8-sig"),
                                delimiter=";"))
    falliti = [r for r in esiti if r["esito"] in ("errata", "parziale")]
    if limite:
        falliti = falliti[:limite]
    equiv = b.atti_equivalenti([r["riferimento"] for r in falliti])

    import agente.agente as A
    print(f"Modello: {A.MODELLO}   domande fallite dal modello attuale: {len(falliti)}\n")

    recuperate = costo_tot = 0
    for r in falliti:
        testo, n, costo = consulta(r["domanda"])
        costo_tot += costo
        if testo is None:
            print(f"  [errore    ] {r['id']}"); continue
        x = giudice.invoke([("system", b.GIUDICE), ("human",
            f"DOMANDA:\n{r['domanda']}\n\nATTESA:\n{r['risposta']}\n\nASSISTENTE:\n{testo[:2500]}")])
        t = x.content if isinstance(x.content, str) else "".join(
            c.get("text", "") for c in x.content if isinstance(c, dict))
        g = re.search(r"\{.*\}", t, re.S)
        nuovo = json.loads(g.group(0)).get("esito", "errata") if g else "errata"
        fonte = b.cita_giusto(testo, r["riferimento"], equiv.get(r["riferimento"], ()))
        recuperate += nuovo == "corretta"
        segno = "RECUPERATA" if nuovo == "corretta" else nuovo
        print(f"  [{segno:<10}] {r['id']}  era {r['esito']:<9} {n} strum. "
              f"${costo:.4f}  fonte {fonte}  {r['domanda'][:40]}")

    print(f"\n  recuperate: {recuperate}/{len(falliti)}")
    print(f"  costo di questa prova: ${costo_tot:.2f}"
          f"   (proiezione su 100 domande: ${costo_tot/max(1,len(falliti))*100:.0f})")


if __name__ == "__main__":
    main()
