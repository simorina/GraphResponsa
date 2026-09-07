"""
Esegue il benchmark contro l'agente in produzione e ne misura l'esito.

Si interroga il servizio vero, attraverso CloudFront, con un utente creato per
l'occasione: e' l'unico modo di misurare cio' che vede un utente, invece di una
copia locale del codice.

Due metriche distinte, e la seconda conta piu' della prima:

  merito    la risposta contiene il fatto atteso?
  fonte     l'agente ha citato la norma giusta?

Un assistente giuridico che dice la cosa esatta citando la norma sbagliata non
e' meta' corretto: e' inservibile, perche' chi legge non puo' verificare.

    python scripts/esegui_benchmark.py           # tutte e 100, in produzione
    python scripts/esegui_benchmark.py 10        # solo le prime 10, per provare
    python scripts/esegui_benchmark.py --locale  # contro il codice locale

Il modo --locale invoca l'agente nel processo invece di passare da CloudFront.
Serve a misurare una modifica prima di distribuirla: stesse domande, stesso
giudice, cambia solo il codice sotto. Non consuma il tetto giornaliero di
consultazioni, che altrimenti tronca la misura a meta'.
"""

import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
load_dotenv(ROOT / ".env")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

BASE = "https://ds1t1vk405e45.cloudfront.net"
POOL = "eu-central-1_MBFp8Z9Oq"
CLIENT = "10d7o76gk7r5ch0pacuramn5gj"
UTENTE = "benchmark@graphresponsa.test"
PAROLA = "Benchmark2026Titano"

GIUDICE = """Confronti la risposta di un assistente giuridico con la risposta attesa.

Giudica UNA cosa sola: il fatto atteso c'e' o non c'e'?

  corretta    il fatto atteso c'e', anche detto con altre parole
  parziale    va nella direzione giusta ma IL DATO PRECISO MANCA
  errata      dice altro, contraddice, oppure dichiara di non sapere

"parziale" significa che manca qualcosa di atteso, mai che ci sia qualcosa in
piu'. Se il fatto atteso c'e', la risposta e' CORRETTA - punto - e non importa
quanto sia lunga, quante altre norme citi, quanti casi aggiunga o quanto sia
articolata. La risposta attesa e' un estratto di un solo comma, quindi e' NORMALE
che una buona risposta dica molto di piu': l'assistente ha letto l'atto intero.

Errori da non commettere, osservati davvero su questo benchmark:

  - "Contiene il fatto atteso ma aggiunge dettagli non richiesti" -> CORRETTA.
    Nessun dettaglio in piu' rende una risposta parziale.
  - "Identifica i tre regimi ma con criteri diversi da quelli attesi" -> se i
    tre regimi ci sono, CORRETTA: la formulazione non deve coincidere.
  - "Risponde in modo piu' ampio della domanda" -> CORRETTA.

Declassa a parziale solo se, cercando il dato atteso nella risposta, NON lo
trovi. Declassa a errata solo se trovi il contrario.

Per le domande su materie NON disciplinate, la risposta corretta e' dichiarare
che l'archivio non contiene la disciplina. Se l'assistente inventa una risposta,
e' errata.

ATTENZIONE ALLA VIGENZA. La risposta attesa e' tratta da un singolo comma, che
puo' essere stato nel frattempo modificato. Se l'assistente riporta il dato
atteso E aggiunge che una norma successiva l'ha cambiato, la risposta e'
CORRETTA: e' piu' completa di quella attesa, non in contrasto. E' corretta
anche se espone il dato vigente citando quello atteso come previgente.

Rispondi SOLO: {"esito": "corretta"|"parziale"|"errata", "motivo": "in dieci parole"}
"""


def credenziali():
    subprocess.run(["aws", "cognito-idp", "admin-create-user", "--user-pool-id", POOL,
                    "--username", UTENTE, "--user-attributes",
                    f"Name=email,Value={UTENTE}", "Name=email_verified,Value=true",
                    "--message-action", "SUPPRESS"], capture_output=True)
    subprocess.run(["aws", "cognito-idp", "admin-set-user-password", "--user-pool-id", POOL,
                    "--username", UTENTE, "--password", PAROLA, "--permanent"],
                   capture_output=True)
    r = subprocess.run(["aws", "cognito-idp", "initiate-auth", "--client-id", CLIENT,
                        "--auth-flow", "USER_PASSWORD_AUTH", "--auth-parameters",
                        f"USERNAME={UTENTE},PASSWORD={PAROLA}",
                        "--query", "AuthenticationResult.IdToken", "--output", "text"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def interroga(domanda, intestazioni):
    """Una consultazione, senza conversazione: ogni domanda parte pulita."""
    testo, strumenti, costo, t0 = "", [], 0.0, time.time()
    r = requests.post(f"{BASE}/chat", headers=intestazioni,
                      json={"domanda": domanda}, stream=True, timeout=300)
    if r.status_code != 200:
        return {"errore": f"HTTP {r.status_code}", "testo": "", "secondi": 0,
                "strumenti": [], "costo": 0}
    for riga in r.iter_lines(decode_unicode=True):
        if not riga or not riga.startswith("data:"):
            continue
        ev = json.loads(riga[5:].strip())
        if ev["tipo"] == "testo":
            testo += ev["testo"]
        elif ev["tipo"] == "strumento":
            strumenti.append(ev["nome"])
        elif ev["tipo"] == "fine":
            costo = float(ev.get("costo", 0))
    return {"testo": testo, "secondi": time.time() - t0,
            "strumenti": strumenti, "costo": costo, "errore": None}


def interroga_locale(domanda, agente):
    """La stessa consultazione, ma contro il codice di questo albero."""
    import uuid
    t0 = time.time()
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 16}
    try:
        out = agente.invoke({"messages": [("human", domanda)]}, cfg)
    except Exception as e:
        return {"errore": f"{type(e).__name__}: {e}"[:90], "testo": "",
                "secondi": 0, "strumenti": [], "costo": 0}
    strumenti, testo, ingresso, uscita = [], "", 0, 0
    letti = scritti = 0
    for m in out["messages"]:
        for tc in getattr(m, "tool_calls", None) or []:
            strumenti.append(tc["name"])
        u = getattr(m, "usage_metadata", None) or {}
        # `input_tokens` comprende i token riletti dalla cache, che costano un
        # decimo, e quelli scritti, che costano un quarto in piu'. Sommarli al
        # prezzo pieno gonfiava il costo misurato: il primo giro completo del
        # benchmark riportava $0,0306 a domanda per questo motivo.
        d = u.get("input_token_details") or {}
        letti += d.get("cache_read", 0)
        scritti += d.get("cache_creation", 0)
        ingresso += u.get("input_tokens", 0)
        uscita += u.get("output_tokens", 0)
        if m.__class__.__name__ == "AIMessage" and not getattr(m, "tool_calls", None):
            testo = m.content if isinstance(m.content, str) else "".join(
                b.get("text", "") for b in m.content if isinstance(b, dict))
    return {"testo": testo, "secondi": time.time() - t0, "strumenti": strumenti,
            "costo": ((ingresso - letti - scritti) + scritti * 1.25
                      + letti * 0.10) / 1e6 * 1.0 + uscita / 1e6 * 5.0,
            "daCache": letti, "errore": None}


def cita_giusto(risposta, riferimento):
    """
    La norma attesa compare nella risposta?

    L'id 'DD-79-2013' nel testo appare come 'Decreto Delegato 79/2013' o
    'DD 79/2013': si cerca la coppia numero/anno, che e' la parte che identifica
    l'atto e che un assistente non puo' azzeccare per caso.
    """
    if not riferimento:
        return None
    m = re.match(r"[A-Z]+-(-?\d+)-(\d+)", riferimento.split()[0])
    if not m:
        return None
    numero, anno = m.groups()
    return bool(re.search(rf"\b{re.escape(numero)}\s*/\s*{anno}\b", risposta) or
                re.search(rf"\bn\.?\s*{re.escape(numero)}\b.{{0,40}}\b{anno}\b", risposta))


def main():
    limite = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)
    locale = "--locale" in sys.argv
    righe = list(csv.DictReader(open(OUT / "benchmark_100.csv", encoding="utf-8-sig"),
                                delimiter=";"))
    if limite:
        righe = righe[:limite]
    # Le negative per prime: sono cinque e misurano il presidio
    # anti-allucinazione. In coda le mangiava il tetto giornaliero di
    # consultazioni, e la misura che conta di piu' era quella che si perdeva.
    righe.sort(key=lambda r: r["categoria"] != "negativa")

    from langchain_anthropic import ChatAnthropic
    giudice = ChatAnthropic(model="claude-haiku-4-5", max_tokens=300,
                            api_key=os.environ["ANTHROPIC_API_KEY"])

    if locale:
        sys.path.insert(0, str(ROOT / "src"))
        from agente.agente import agente as costruisci
        grafo = costruisci()
        chiedi = lambda d: interroga_locale(d, grafo)
        print(f"Eseguo {len(righe)} domande contro il codice locale\n")
    else:
        print("Utente di prova su Cognito...")
        token = credenziali()
        H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        chiedi = lambda d: interroga(d, H)
        print(f"Eseguo {len(righe)} domande contro {BASE}\n")

    esiti, t0 = [], time.time()
    for i, r in enumerate(righe, 1):
        e = chiedi(r["domanda"])
        if e["errore"]:
            esiti.append({**r, "esito": "errore", "motivo": e["errore"],
                          "risposta_agente": "", "secondi": 0, "costo": 0,
                          "fonte_giusta": None, "strumenti": ""})
            print(f"  [{i:>3}] ERRORE {e['errore']}")
            if "429" in e["errore"]:
                print("        tetto giornaliero raggiunto: il resto non e' misurabile oggi")
                break
            continue

        g = giudice.invoke([("system", GIUDICE),
                            ("human", f"DOMANDA:\n{r['domanda']}\n\n"
                                      f"ATTESA:\n{r['risposta']}\n\n"
                                      f"ASSISTENTE:\n{e['testo'][:2500]}")])
        t = g.content if isinstance(g.content, str) else "".join(
            b.get("text", "") for b in g.content if isinstance(b, dict))
        m = re.search(r"\{.*\}", t, re.S)
        d = json.loads(m.group(0)) if m else {"esito": "errata", "motivo": "giudizio illeggibile"}

        fonte = cita_giusto(e["testo"], r["riferimento"])
        esiti.append({**r, "esito": d.get("esito", "errata"), "motivo": d.get("motivo", ""),
                      "risposta_agente": e["testo"], "secondi": round(e["secondi"], 1),
                      "costo": e["costo"], "fonte_giusta": fonte,
                      "strumenti": " ".join(e["strumenti"])})
        segno = {"corretta": "OK", "parziale": "~~", "errata": "NO"}.get(d.get("esito"), "??")
        marchio = "" if fonte is None else (" fonte ok" if fonte else " FONTE NO")
        print(f"  [{i:>3}] {segno}{marchio}  {e['secondi']:4.0f}s  {r['domanda'][:58]}")

    dove = OUT / ("benchmark_esiti_locale.csv" if locale else "benchmark_esiti.csv")
    # Un giro parziale non deve cancellare un giro intero. E' successo: dodici
    # domande hanno sovrascritto le cento, e le risposte da riesaminare sono
    # andate perdute. Il giro corto scrive di fianco, con il proprio numero.
    if limite and dove.exists():
        import csv as _csv
        try:
            esistenti = sum(1 for _ in _csv.reader(open(dove, encoding="utf-8-sig"))) - 1
        except Exception:
            esistenti = 0
        if esistenti > len(esiti):
            dove = dove.with_name(dove.stem + f"_{len(esiti)}" + dove.suffix)
            print(f"  (giro parziale: scrivo in {dove.name} per non "
                  f"cancellare i {esistenti} risultati gia' presenti)")
    with open(dove, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(esiti[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(esiti)

    # --- Riepilogo ---
    import collections
    conteggio = collections.Counter(e["esito"] for e in esiti)
    n = len(esiti)
    print("\n" + "=" * 62)
    print(f"ESITO SU {n} DOMANDE")
    print("=" * 62)
    for k in ("corretta", "parziale", "errata", "errore"):
        if conteggio[k]:
            print(f"  {k:<10} {conteggio[k]:>4}   {conteggio[k]/n*100:5.1f}%")

    con_fonte = [e for e in esiti if e["fonte_giusta"] is not None]
    if con_fonte:
        giuste = sum(1 for e in con_fonte if e["fonte_giusta"])
        print(f"\n  fonte citata correttamente: {giuste}/{len(con_fonte)} "
              f"({giuste/len(con_fonte)*100:.1f}%)")
        entrambe = sum(1 for e in con_fonte if e["esito"] == "corretta" and e["fonte_giusta"])
        print(f"  merito E fonte insieme    : {entrambe}/{len(con_fonte)} "
              f"({entrambe/len(con_fonte)*100:.1f}%)")

    print("\n  per categoria:")
    for cat in ("contenuto", "struttura", "negativa"):
        sotto = [e for e in esiti if e["categoria"] == cat]
        if sotto:
            ok = sum(1 for e in sotto if e["esito"] == "corretta")
            print(f"    {cat:<10} {ok:>3}/{len(sotto):<3} corrette  ({ok/len(sotto)*100:5.1f}%)")

    tot_costo = sum(e["costo"] for e in esiti)
    tempi = sorted(e["secondi"] for e in esiti if e["secondi"])
    print(f"\n  costo totale  ${tot_costo:.2f}   media ${tot_costo/max(1,n):.4f} a domanda")
    if tempi:
        print(f"  tempo mediano {tempi[len(tempi)//2]:.0f}s   piu' lenta {tempi[-1]:.0f}s")
    print(f"  durata totale {(time.time()-t0)/60:.0f} min")
    print(f"\nDettaglio riga per riga: {dove}")


if __name__ == "__main__":
    main()
