"""
"Fonte sbagliata" non e' una diagnosi: separa l'errore dalla fonte alternativa.

Sul benchmark restano 23 casi in cui l'atto atteso non compare nella risposta,
e dodici di questi hanno il merito CORRETTO: risposta giusta, citazione che non
torna. Prima di chiamarli errori bisogna chiedersi una cosa sola: l'atto che
l'agente ha citato contiene lo stesso dato?

In questo ordinamento capita spesso che due atti dicano la stessa cosa senza
avere il testo identico - una legge e il suo regolamento attuativo, una norma e
la novella che la riscrive - e la verita' di riferimento ne nomina uno solo.
Citare l'altro non e' sbagliato.

Il criterio e' meccanico e verificabile: si estraggono dalla risposta ATTESA i
dati distintivi - cifre, importi, durate, numeri di articolo - e si cerca se
compaiono nel testo dell'atto che l'agente ha citato. Se ci sono, quell'atto
dice davvero la stessa cosa e la citazione regge. Se non ci sono, e' un errore.

Non serve interrogare il modello: le risposte sono gia' registrate.

    .venv/Scripts/python.exe scripts/analizza_fonti_sbagliate.py
"""

import csv
import importlib.util
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# Un dato distintivo: una cifra di almeno due caratteri, un importo, una
# percentuale. Le parole no: "giorni" compare ovunque, "trenta giorni" no - ma
# i numeri scritti in lettere si perdono, e su quelli il criterio tace.
RE_DATO = re.compile(r"\d[\d.,]*\s*(?:%|euro|€|giorni|mesi|anni)?", re.IGNORECASE)


def dati_distintivi(testo):
    fuori = []
    for m in RE_DATO.finditer(testo or ""):
        d = m.group(0).strip().rstrip(".,")
        cifra = re.sub(r"[^\d]", "", d)
        if len(cifra) >= 2:            # "3" ricorre ovunque, "30" molto meno
            fuori.append(cifra)
    return sorted(set(fuori), key=len, reverse=True)[:4]


def atti_citati(risposta, citazioni):
    fuori = []
    for i, e in enumerate(citazioni):
        for m in e.finditer(risposta or ""):
            n, a = (m.group(2), m.group(1)) if i == 2 else (m.group(1), m.group(2))
            if (n, a) not in fuori:
                fuori.append((n, a))
    return fuori


def main():
    from agente.agente import CITAZIONI
    from agente.strumenti import grafo

    sp = importlib.util.spec_from_file_location("b", ROOT / "scripts" / "esegui_benchmark.py")
    b = importlib.util.module_from_spec(sp)
    try:
        sp.loader.exec_module(b)
    except SystemExit:
        pass

    righe = list(csv.DictReader(open(OUT / "benchmark_esiti_locale.csv", encoding="utf-8-sig"),
                                delimiter=";"))
    casi = [r for r in righe if r["fonte_giusta"] == "False"]
    print(f"Analizzo {len(casi)} casi con fonte non riconosciuta\n")

    conta = {"alternativa_valida": 0, "errore_vero": 0, "nessuna_citazione": 0,
             "senza_dati": 0}
    for r in casi:
        dati = dati_distintivi(r["risposta"])
        citati = atti_citati(r["risposta_agente"], CITAZIONI)
        if not citati:
            conta["nessuna_citazione"] += 1
            print(f"  [nessuna citazione ] {r['id']}  atteso {r['riferimento'].split()[0]}")
            continue
        if not dati:
            conta["senza_dati"] += 1
            print(f"  [non giudicabile   ] {r['id']}  la risposta attesa non ha cifre")
            continue

        # I dati attesi compaiono nel testo di uno degli atti citati?
        trovati = grafo().query("""
            UNWIND $citati AS c
            MATCH (n:Norma) WHERE n.numero = toInteger(c[0]) AND n.anno = toInteger(c[1])
            MATCH (n)-[:HA_ARTICOLO]->(:Articolo)-[:HA_COMMA]->(cm:Comma)
            WITH n, collect(cm.testo) AS testi
            RETURN n.id AS id, reduce(t = '', x IN testi | t + ' ' + coalesce(x, '')) AS testo
        """, {"citati": [[n, a] for n, a in citati]})

        regge = [t["id"] for t in trovati
                 if sum(1 for d in dati if d in (t["testo"] or "")) >= max(1, len(dati) // 2)]
        if regge:
            conta["alternativa_valida"] += 1
            print(f"  [ALTERNATIVA VALIDA] {r['id']}  atteso {r['riferimento'].split()[0]:<14} "
                  f"ha citato {regge[:2]} che contiene {dati[:2]}")
        else:
            conta["errore_vero"] += 1
            print(f"  [errore vero       ] {r['id']}  atteso {r['riferimento'].split()[0]:<14} "
                  f"ha citato {[f'{n}/{a}' for n, a in citati][:3]}, senza {dati[:2]}")

    print("\n  " + "-" * 54)
    for k, v in sorted(conta.items(), key=lambda x: -x[1]):
        if v:
            print(f"  {k:<20} {v:>3}")
    valide = conta["alternativa_valida"]
    tot = len(righe) - sum(1 for r in righe if r["fonte_giusta"] not in ("True", "False"))
    giuste = sum(1 for r in righe if r["fonte_giusta"] == "True")
    print(f"\n  fonte misurata      {giuste}/{tot} ({giuste/tot*100:.1f}%)")
    print(f"  contando le alternative valide  {giuste + valide}/{tot} "
          f"({(giuste + valide)/tot*100:.1f}%)")


if __name__ == "__main__":
    main()
