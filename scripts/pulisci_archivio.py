"""
Toglie da data/raw/ le cartelle che non servono a nessuno.

Due categorie, entrambe verificate prima di cancellare:

  **fabbricate** - lasciate da verify_all_8214_decreti.py, che quando la sua
  regex sul titolo non agganciava ripiegava su `numero = schedaId`, e per
  giunta scaricava da `documento<ID>.pdf` invece di `documento<ID>.html`.
  Risultato: una cartella con la sola scheda.json, id senza senso e nessun PDF.

  **doppioni stantii** - cartelle con prefisso 'X' (tipo non riconosciuto
  all'epoca) superate da una cartella con il tipo giusto. Si cancellano solo
  se la gemella esiste, punta alla STESSA scheda del portale e ha un PDF delle
  STESSE dimensioni: senza queste tre condizioni non sono doppioni, sono atti.

    python scripts/pulisci_archivio.py            # mostra cosa farebbe
    python scripts/pulisci_archivio.py --applica  # lo fa davvero
"""

import json
import re
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PARSED = ROOT / "data" / "parsed"
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)

RE_SCHEDA = re.compile(r"scheda(\d+)\.html")


def profilo(cartella: Path):
    """Legge quel poco che serve a decidere: scheda di origine e peso del PDF."""
    f = cartella / "scheda.json"
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    m = RE_SCHEDA.search(d.get("urlScheda") or "")
    pdf = cartella / "testo.pdf"
    return {
        "id": d.get("id"),
        "scheda": m.group(1) if m else None,
        "pdf": pdf.stat().st_size if pdf.exists() else 0,
    }


def main():
    applica = "--applica" in sys.argv

    cartelle = {c.name: profilo(c) for c in RAW.iterdir() if c.is_dir()}
    cartelle = {k: v for k, v in cartelle.items() if v}
    print(f"Cartelle leggibili in data/raw/: {len(cartelle)}\n")

    # --- 1. Fabbricate: il numero nell'id e' lo schedaId, e manca il PDF ---
    fabbricate = []
    for nome, p in cartelle.items():
        pezzi = (p["id"] or "").split("-")
        if len(pezzi) >= 3 and p["scheda"] and pezzi[1] == p["scheda"] and p["pdf"] == 0:
            fabbricate.append(nome)

    # --- 2. Doppioni stantii con prefisso X ---
    per_scheda = {}
    for nome, p in cartelle.items():
        if p["scheda"] and not nome.startswith("X-"):
            per_scheda.setdefault(p["scheda"], []).append((nome, p))

    doppioni, sospetti = [], []
    for nome, p in cartelle.items():
        if not nome.startswith("X-") or not p["scheda"]:
            continue
        gemelle = per_scheda.get(p["scheda"], [])
        # Tre condizioni insieme: stessa scheda, PDF non vuoto, peso identico.
        buona = next((g for g, gp in gemelle if cartelle[g]["pdf"] == p["pdf"] and p["pdf"] > 0), None)
        if buona:
            doppioni.append((nome, buona))
        else:
            sospetti.append((nome, [g for g, _ in gemelle]))

    print(f"  Fabbricate, senza PDF          : {len(fabbricate)}")
    print(f"  Doppioni X con gemella identica: {len(doppioni)}")
    print(f"  X senza gemella (NON toccate)  : {len(sospetti)}")
    print()
    for nome, buona in doppioni[:4]:
        print(f"    {nome:<20} == {buona}")
    if sospetti:
        print(f"\n  Restano, perche' non hanno un equivalente sicuro:")
        for nome, g in sospetti[:6]:
            print(f"    {nome:<20} gemelle trovate: {g or 'nessuna'}")

    esito = {"fabbricate": fabbricate,
             "doppioni": [{"da_togliere": a, "resta": b} for a, b in doppioni],
             "sospetti": [{"cartella": a, "gemelle": g} for a, g in sospetti]}
    (OUT / "pulizia_archivio.json").write_text(
        json.dumps(esito, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRapporto: {OUT / 'pulizia_archivio.json'}")

    if not applica:
        print("\nProva a vuoto. Per eseguire davvero: --applica")
        return

    tolte = 0
    for nome in fabbricate + [a for a, _ in doppioni]:
        shutil.rmtree(RAW / nome, ignore_errors=True)
        (PARSED / f"{nome}.json").unlink(missing_ok=True)
        tolte += 1
        if tolte % 2000 == 0:
            print(f"  ...{tolte} rimosse")

    print(f"\nCartelle rimosse: {tolte}")
    print(f"Restano in data/raw/: {sum(1 for c in RAW.iterdir() if c.is_dir())}")


if __name__ == "__main__":
    main()
