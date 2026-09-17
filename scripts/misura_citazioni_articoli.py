"""
Misura (nessun fix) di quattro modi in cui una riga "Art. N" che non e'
un'intestazione propria del documento diventa comunque un articolo.

Le intestazioni si ripercorrono come fa 02_parse.parse(): RE_ARTICOLO sulla
riga, stop alla formula di promulgazione una volta visto un articolo.

  P1 citazione   - blocchi di intestazioni che rompono la sequenza locale,
                   con almeno una prova: "contesto" (frase di modifica o
                   citazione prima del salto: estrai_citazioni, cioe'
                   RE_CITAZIONE + RE_BERSAGLIO, piu' i verbi di novella) o
                   "rientro" (dopo il blocco la numerazione riprende da dove
                   si era interrotta). Escluse le intestazioni di P2b e P3.
  P2 doppione    - due intestazioni consecutive con lo stesso numero.
                   "a_capo" se la seconda inizia minuscola o la riga prima
                   non chiude la frase.
  P2b minuscola  - intestazione riconosciuta che inizia minuscola
                   ("articolo 20."): testo andato a capo.
  P3 indice      - le prime >=3 righe "Art..." (anche non riconosciute) con
                   poco testo in mezzo, i cui numeri ricompaiono dopo.
                   Occorrenze: intestazioni riconosciute dentro l'indice.
  P4 convenzione - >=5 righe "Art..." prima della promulgazione, numerazione
                   che riparte da 1 dopo la prima intestazione, e fra le due
                   una frase di ratifica che nomina un trattato.

Uso:
    .venv/Scripts/python.exe scripts/misura_citazioni_articoli.py
"""
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
_argv, sys.argv = sys.argv, sys.argv[:1]
import baseline_from_s3 as b  # noqa: E402  (applica il monkeypatch S3)
sys.argv = _argv

p02 = b.p02
RA = p02.RE_ARTICOLO
RE_PERMISSIVA = re.compile(r"^Art(?:icolo)?\.?\s*(\d+)", re.I)
RE_NOVELLA = re.compile(
    r"\b(?:inserit|introdott|aggiunt|sostituit|riformulat)\w*"
    r"|\bcos[iì]'?\s+(?:modificat|sostituit|riformulat)\w*"
    r"|\b(?:il|la|i|le)\s+seguent[ei]\b"
    r"|[:“\"«]\s*$", re.I)
RE_MENZIONE = re.compile(r"\bart(?:icol[oi])?\.?\s*(\d+)", re.I)
RE_RATIFICA = re.compile(r"ratific|piena\s+ed?\s+intera\s+esecuzione|recepit", re.I)
RE_TRATTATO = re.compile(r"\b(?:Convenzione|Trattato|Accordo|Protocollo|Parti\s+contraenti|Stati\s+membri)\b")
TESTO_INDICE = 300  # caratteri massimi fra due voci di un indice (rubriche e TITOLO/CAPO in mezzo)
RIGHE_INDICE = 6
RE_PAROLA_INDICE = re.compile(r"^\s*(?:INDICE|SOMMARIO)\b", re.I)


def contesto(righe, i, n_righe=4, max_chr=400):
    out, j = [], i - 1
    while j >= 0 and len(out) < n_righe:
        if righe[j].strip():
            out.append(righe[j].strip())
        j -= 1
    return " ".join(reversed(out))[-max_chr:]


def intestazioni(righe):
    """(indice riga, base int|None, suffisso, riga) come le vede parse(), e l'indice di taglio."""
    teste, taglio = [], len(righe)
    for i, r in enumerate(righe):
        s = r.strip()
        if not s:
            continue
        if teste and p02._cerca_promulgazione(righe, i):
            taglio = i
            break
        m = RA.match(s)
        if m:
            base = int(m.group(1)) if m.group(1).isdigit() else None
            teste.append((i, base, (m.group(2) or "").lower(), s))
    return teste, taglio


def analizza(nid):
    righe = b._righe_pdf_s3(f"raw/{nid}/testo.pdf")
    b._cache.pop(f"raw/{nid}/testo.pdf", None)
    teste, taglio = intestazioni(righe)
    r = {"id": nid, "n_teste": len(teste), "p4": 0}
    r.update(analizza_p4(nid, righe))
    if not teste:
        return r

    def testo_fra(a, z):
        return sum(len(x.strip()) for x in righe[a + 1:z])

    def compatto(a, z):
        return testo_fra(a, z) <= TESTO_INDICE and sum(1 for x in righe[a + 1:z] if x.strip()) <= RIGHE_INDICE

    # --- P2b: intestazione minuscola ("... ai sensi dell' / articolo 20."):
    # le intestazioni vere iniziano maiuscole, questa e' testo andato a capo ---
    minuscole = [s for _, _, _, s in teste if s[0].islower()]
    r["p2b"] = len(minuscole)
    r["p2b_esempi"] = minuscole[:5]

    # --- P3: indice iniziale ---
    # Separatori: anche le voci d'indice che RE_ARTICOLO non riconosce
    # ("Articolo 8 - Revoca della registrazione"), altrimenti il testo fra
    # due voci riconosciute sembra lungo.
    corpo = righe[:taglio]
    perm = [(i, int(m.group(1))) for i, x in enumerate(corpo)
            if (m := RE_PERMISSIVA.match(x.strip())) and x.strip()[0] == "A"]
    p3, fine_indice = 0, -1
    if len(perm) >= 3:
        run = 1
        while run < len(perm) and compatto(perm[run - 1][0], perm[run][0]):
            run += 1
        fine = perm[run - 1][0]
        voci = {n for _, n in perm[:run]}
        dopo = {n for i, n in perm[run:]}
        if run >= 3 and len(voci & dopo) >= 0.6 * len(voci):
            fine_indice = fine
            # occorrenze: intestazioni riconosciute dentro l'indice, cioe' articoli doppi
            p3 = sum(1 for i, *_ in teste if i <= fine_indice)
            r["p3_voci_indice"] = run
            r["p3_parola_indice"] = any(RE_PAROLA_INDICE.match(x) for x in righe[:perm[0][0]])
    r["p3"] = p3

    # le intestazioni dell'indice (P3) e quelle minuscole (P2b) restano fuori
    teste_p1 = [t for t in teste if not t[3][0].islower() and t[0] > fine_indice]

    # --- P1: intestazioni citate ---
    # Una intestazione "salta" se non prosegue la sequenza in corso e il salto
    # non e' spiegato da una riga "Art..." non riconosciuta con il numero
    # mancante (rubrica sulla stessa riga: e' un altro problema). Due prove:
    #   contesto - prima del salto c'e' una frase di modifica/citazione; vale
    #              per la sola intestazione che salta
    #   rientro  - piu' avanti la numerazione riprende da dove si era
    #              interrotta (...6, 11..29, 7...): vale per tutto il blocco
    # "confermata": l'intestazione ha il numero dell'articolo citato nel contesto.
    per_contesto, per_rientro, salti = set(), set(), set()
    conf = 0
    main, salvato, blocco, prec = 0, None, [], -1

    def spiegato(m, n, da, a):
        return n > m + 1 and any(da < k < a and m < nn < n for k, nn in perm)

    for i, n, suff, s in teste_p1:
        if n is None:          # "Articolo unico": riparte la sequenza propria
            main, salvato, blocco = 0, None, []
        elif (n == main + 1 or (suff and n == main) or (main == 0 and n == 1)
              or spiegato(main, n, prec, i)):
            main = n           # prosegue (anche dentro un blocco: e' la sua sequenza)
            if salvato is not None:
                blocco.append(i)
        elif salvato is not None and (n == salvato + 1 or (suff and n == salvato)):
            per_rientro.update(blocco)
            main, salvato, blocco = n, None, []
        else:
            salti.add(i)
            ctx = contesto(righe, i, n_righe=8, max_chr=600)
            cit = p02.estrai_citazioni(ctx, nid)
            if cit or RE_NOVELLA.search(ctx):
                per_contesto.add(i)
                citati = {c["articoloCitato"] for c in cit} | set(RE_MENZIONE.findall(ctx))
                conf += str(n) in citati
            if salvato is None:
                salvato = main
            blocco.append(i)
            main = n
        prec = i
    senza_prova = salti - per_contesto - per_rientro

    p1 = per_contesto | per_rientro
    riga_di = {i: s for i, _, _, s in teste}
    r["p1"] = len(p1)
    r["p1_contesto"] = len(per_contesto)
    r["p1_rientro"] = len(per_rientro)
    r["p1_entrambe"] = len(per_contesto & per_rientro)
    r["p1_confermate"] = conf
    r["p1_esempi"] = [riga_di[i] for i in sorted(p1)[:6]]
    r["salti"] = len(salti)
    r["salti_senza_prova"] = len(senza_prova)

    # --- P2: consecutive con lo stesso numero ---
    p2, p2_capo = 0, 0
    for (i0, n0, s0, _), (i1, n1, s1, riga) in zip(teste, teste[1:]):
        if n0 is not None and (n0, s0) == (n1, s1):
            p2 += 1
            prima = contesto(righe, i1, 1)
            if riga[0].islower() or (prima and not prima.endswith((".", ":", ";", ")", "”", '"'))):
                p2_capo += 1
    r["p2"], r["p2_a_capo"] = p2, p2_capo
    ids = Counter((n, s) for _, n, s, _ in teste if n is not None)
    r["doppioni_totali"] = sum(v - 1 for v in ids.values() if v > 1)

    return r


def analizza_p4(nid, righe):
    """
    Convenzione nel dispositivo: la numerazione riparte da 1 dopo la prima
    intestazione, e fra le due c'e' una frase di ratifica che nomina un
    trattato. Calcolato anche senza intestazioni riconosciute; il taglio e'
    la formula di promulgazione dopo la prima riga "Art...".
    """
    perm = []
    taglio = len(righe)
    for i, x in enumerate(righe):
        s = x.strip()
        if not s:
            continue
        if perm and p02._cerca_promulgazione(righe, i):
            taglio = i
            break
        m = RE_PERMISSIVA.match(s)
        if m and s[0] == "A":
            perm.append((i, int(m.group(1)), bool(RA.match(s))))
        elif s[0] == "A" and RA.match(s):   # "Articolo unico"
            perm.append((i, None, True))
    if len(perm) < 5:
        return {}
    primo = perm[0][0]
    ripartenze = [i for i, n, _ in perm if n == 1 and (i > primo or perm[0][1] is None)]
    if not ripartenze:
        return {}
    da = ripartenze[0]
    fra = " ".join(x.strip() for x in righe[primo:da])
    if not (RE_RATIFICA.search(fra) and RE_TRATTATO.search(fra)):
        return {}
    dopo = [x for x in perm if x[0] >= da]
    return {"p4": len(dopo), "p4_riconosciute": sum(1 for x in dopo if x[2]),
            "p4_taglio": taglio, "p4_righe": len(righe)}


def main():
    ids = b.elenco_documenti()
    with ThreadPoolExecutor(24) as ex:
        ris = list(ex.map(analizza, ids))
    out = ROOT / "data" / f"misura_citazioni_articoli_{date.today().isoformat()}.json"
    out.write_text(json.dumps(ris, ensure_ascii=False), encoding="utf-8")

    chiavi = {"P1 citazione": "p1", "P2 doppione": "p2", "P2b minuscola": "p2b",
              "P3 indice": "p3", "P4 convenzione": "p4"}
    insiemi = {}
    for nome, k in chiavi.items():
        docs = [x for x in ris if x.get(k)]
        insiemi[nome] = {x["id"] for x in docs}
        extra = ""
        if k == "p1":
            s = lambda c: f"{sum(x[c] for x in docs)} occ / {sum(1 for x in docs if x[c])} doc"
            extra = (f"\n   prova contesto {s('p1_contesto')}; prova rientro {s('p1_rientro')}; "
                     f"entrambe {s('p1_entrambe')}; numero = articolo citato {s('p1_confermate')}")
        if k == "p2":
            extra = f", a capo {sum(x['p2_a_capo'] for x in docs)} in {sum(1 for x in docs if x['p2_a_capo'])} doc"
        if k == "p3":
            extra = (f", voci d'indice totali {sum(x['p3_voci_indice'] for x in docs)}, "
                     f"con parola INDICE/SOMMARIO {sum(1 for x in docs if x['p3_parola_indice'])} doc")
        if k == "p4":
            dc = [x for x in docs if x["id"].startswith("DC-")]
            extra = (f", di cui DC {len(dc)} doc; righe gia' riconosciute come articoli "
                     f"{sum(x['p4_riconosciute'] for x in docs)}")
        print(f"\n{nome}: {len(docs)} documenti, {sum(x[k] for x in docs)} occorrenze{extra}")
        for x in sorted(docs, key=lambda x: -x[k])[:10]:
            det = {"p1": x.get("p1_esempi"), "p3": f"voci {x.get('p3_voci_indice')}", "p2b": x.get("p2b_esempi"),
                   "p4": f"riconosciute {x.get('p4_riconosciute')}"}.get(k, "")
            print(f"   {x['id']:<24} {x[k]:>4}  {det}")
    print(f"\nsalti di sequenza non spiegati: {sum(x.get('salti', 0) for x in ris)} "
          f"in {sum(1 for x in ris if x.get('salti'))} doc")
    print(f"di cui senza nessuna prova: {sum(x.get('salti_senza_prova', 0) for x in ris)} "
          f"in {sum(1 for x in ris if x.get('salti_senza_prova'))} doc")
    print(f"doppioni di id (anche non consecutivi): {sum(x.get('doppioni_totali', 0) for x in ris)} "
          f"in {sum(1 for x in ris if x.get('doppioni_totali'))} doc")

    nomi = list(insiemi)
    print("\nsovrapposizioni (documenti in comune):")
    print(" " * 16 + "".join(f"{n[:2]:>6}" for n in nomi))
    for a in nomi:
        print(f"{a:<16}" + "".join(f"{len(insiemi[a] & insiemi[c]):>6}" for c in nomi))
    unione = set().union(*insiemi.values())
    multi = Counter(sum(d in s for s in insiemi.values()) for d in unione)
    print(f"unione: {len(unione)} documenti; per numero di pattern: {dict(sorted(multi.items()))}")
    print(f"\n{out}")


if __name__ == "__main__":
    main()
