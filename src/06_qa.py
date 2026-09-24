"""
06 - QA di baseline: misura la qualita' del parsing SENZA modificarlo.

Serve a rispondere "quanti documenti sono impattati da ciascun problema noto",
non a correggerli. Va eseguito prima di un fix per fissare una baseline, e di
nuovo dopo per vedere il delta esatto (diff dei due .jsonl o dei due .json).

Non tocca data/raw|parsed ne' il grafo: legge soltanto.

Le regex "vere" (RE_ARTICOLO, RE_COMMA, ...) si importano da 02_parse.py
invece di essere ricopiate, cosi' restano sincronizzate con cio' che il
parser fa davvero oggi. Le regex "permissive" definite qui sotto servono solo
a misurare cosa il parser NON cattura (es. "Art. 5-bis" con trattino) - non
sostituiscono mai il riconoscimento reale.

Uso:
    .venv/Scripts/python.exe src/06_qa.py
    .venv/Scripts/python.exe src/06_qa.py --parsed data/parsed_baseline_2026-09-12 \
        --raw data/raw_baseline_2026-09-12 --out data/qa_report_baseline_2026-09-12

Produce <out>.json (aggregati + top-20 per metrica + conteggi di impatto per
problema), <out>.md (stessa cosa, leggibile) e <out>.jsonl (una riga per
documento, con tutte le metriche grezze: e' il file da confrontare fra due
esecuzioni per misurare il progresso di un fix).
"""

import argparse
import importlib.util
import json
import re
import sys
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(__file__).resolve().parent


def _carica_parser():
    """Importa 02_parse.py per le sue regex e funzioni, senza eseguirne main()."""
    spec = importlib.util.spec_from_file_location("parse02_qa", SRC / "02_parse.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_p02 = _carica_parser()
RE_ARTICOLO = _p02.RE_ARTICOLO
RE_PARTIZIONE = _p02.RE_PARTIZIONE
RE_COMMA = _p02.RE_COMMA
RE_COMMA_INLINE = _p02.RE_COMMA_INLINE
TAGLIO_COMMA_DEFAULT = _p02.TAGLIO_COMMA
righe_pdf = _p02.righe_pdf

# --------------------------------------------------------------------------
# Regex DIAGNOSTICHE: deliberatamente piu' permissive di quelle del parser,
# servono solo a contare cio' che RE_ARTICOLO/RE_COMMA non catturano.

_SUFFISSI = r"bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies"

RE_ART_PERMISSIVA = re.compile(
    rf"^(?:Art\.|Articolo)\s*(\d+|[Uu]nico)\s*[-.\s]*({_SUFFISSI})?\s*[-:.]?\s*$", re.I)

RE_COMMA_PERMISSIVA_TESTA = re.compile(rf"^(\d+)\s*[-\s]\s*({_SUFFISSI})\.?\s*$", re.I)
RE_COMMA_PERMISSIVA_INLINE = re.compile(rf"^(\d+)\s*[-\s]\s*({_SUFFISSI})\.\s+(\S.*)$", re.I)

RE_TIPI_MANCANTI = re.compile(
    r"\b(Statuto|Notifica|Ordinanza|Verbale|Errata\s+Corrige)\b[^\n.;]{0,40}?"
    r"n\.\s*\d+(?:\s*/\s*\d{4})?", re.I)


def _indici_articoli_grezzi(righe):
    """Indici delle righe che RE_ARTICOLO (quella VERA) riconosce come intestazione."""
    return [i for i, r in enumerate(righe) if RE_ARTICOLO.match(r.strip())]


def _prossima_non_vuota(righe, j):
    while j < len(righe) and not righe[j].strip():
        j += 1
    return j


def _pagine_pdf(path):
    try:
        doc = fitz.open(path)
        n = len(doc)
        doc.close()
        return n
    except Exception:
        return None


# --------------------------------------------------------------------------
# Metriche per singolo documento

def analizza_documento_da_path(nid, dati, pdf_path):
    """Wrapper per l'uso locale (CLI): legge il PDF dal filesystem, poi delega
    ad analizza_documento(), che e' la parte pura e non fa I/O da sola."""
    righe, pagine, errore = None, None, None
    if pdf_path and pdf_path.exists():
        try:
            righe = righe_pdf(pdf_path)
        except Exception as e:
            errore = f"lettura PDF fallita: {type(e).__name__}: {e}"
        pagine = _pagine_pdf(pdf_path)
    m = analizza_documento(nid, dati, righe, pagine)
    if errore:
        m["errore"] = errore
    return m


def analizza_documento(nid, dati, righe, pagine):
    """Nucleo puro: nessun I/O. 'righe' e 'pagine' vanno gia' forniti da chi
    chiama (letti da un file locale o, in streaming, direttamente da S3 senza
    mai toccare il disco) - cosi' la stessa funzione serve a entrambi i modi."""
    m = {"id": nid, "tipo": dati.get("tipo"), "errore": None}

    articoli = dati.get("articoli") or []
    dedotta = bool(articoli) and any(a.get("strutturaDedotta") for a in articoli)
    articoli_normali = [] if dedotta else articoli
    m["strutturaDedotta"] = dedotta
    m["n_articoli"] = len(articoli)

    testo_commi = []
    for a in articoli:
        for c in a.get("commi") or []:
            testo_commi.append((a.get("numero"), c.get("id"), c.get("testo") or ""))
    caratteri_commi = sum(len(t) for _, _, t in testo_commi)
    preambolo = dati.get("preambolo") or ""
    m["caratteri_totali"] = caratteri_commi + len(preambolo)

    # --- (e) documenti vuoti o quasi ---
    m["vuoto_o_quasi"] = (not articoli) and len(preambolo.strip()) < 30

    # --- (c) commi anomalamente lunghi, fuori dal ramo dedotto ---
    lunghi = []
    if not dedotta:
        for art_num, cid, t in testo_commi:
            if len(t) > TAGLIO_COMMA_DEFAULT:
                lunghi.append({"articolo": art_num, "commaId": cid, "lunghezza": len(t)})
    m["commi_lunghi"] = lunghi

    # --- (f) citazioni per tipo + tipi mai coperti dalla regex vera ---
    citazioni_tipi = Counter()
    for a in articoli:
        for cit in a.get("citazioni") or []:
            citazioni_tipi[cit.get("tipo")] += 1
    for cit in dati.get("citazioniPreambolo") or []:
        citazioni_tipi[cit.get("tipo")] += 1
    m["citazioni_per_tipo"] = dict(citazioni_tipi)

    testo_completo_commi = " ".join(t for _, _, t in testo_commi) + " " + preambolo
    m["citazioni_tipi_mancanti_stimate"] = len(RE_TIPI_MANCANTI.findall(testo_completo_commi))

    # righe/pagine del PDF grezzo arrivano da chi chiama: servono a (a)
    # parziale, (b), (d), (g), (h).
    m["pagine"] = pagine

    # --- (b) rapporto testo-estratto / pagine ---
    if pagine:
        m["caratteri_per_pagina"] = m["caratteri_totali"] / pagine
    else:
        m["caratteri_per_pagina"] = None

    if righe is None:
        m["max_numero_base"] = None
        m["gap_ratio"] = None
        m["art_bis_non_risolti"] = []
        m["comma_bis_non_risolti"] = []
        m["rubrica_presunta"] = {"rilevate": 0, "recuperate": 0, "perse": 0, "ambigue": 0}
        m["partizione_seguita_da_vuota"] = 0
        return m

    # --- (a) continuita' numerazione + (g) Art. N-bis non risolti ---
    max_base = 0
    art_bis_non_risolti = []
    indici_art_veri = []
    numeri_prodotti = {str(a.get("numero", "")).strip().lower() for a in articoli_normali}

    for i, riga in enumerate(righe):
        r = riga.strip()
        if not r:
            continue
        vera = RE_ARTICOLO.match(r)
        permissiva = RE_ART_PERMISSIVA.match(r)
        if vera:
            indici_art_veri.append(i)
            base = vera.group(1)
            if base.isdigit():
                max_base = max(max_base, int(base))
        elif permissiva:
            base, suff = permissiva.group(1), permissiva.group(2)
            if base.isdigit():
                max_base = max(max_base, int(base))
            atteso = f"{base} {suff.lower()}" if suff else base
            if atteso.lower() not in numeri_prodotti:
                art_bis_non_risolti.append({"riga": r[:80], "numeroBase": base,
                                            "suffisso": suff})
    m["art_bis_non_risolti"] = art_bis_non_risolti

    n_prodotti = len(articoli_normali)
    if dedotta or max_base == 0:
        m["max_numero_base"] = max_base or None
        m["gap_ratio"] = None
    else:
        m["max_numero_base"] = max_base
        m["gap_ratio"] = max(0.0, (max_base - n_prodotti) / max_base)

    # --- (h) comma N bis/ter non risolti, solo dentro un articolo ---
    comma_bis_non_risolti = []
    dentro_articolo = False
    for riga in righe:
        r = riga.strip()
        if not r:
            continue
        if RE_ARTICOLO.match(r) or RE_ART_PERMISSIVA.match(r):
            dentro_articolo = True
            continue
        if RE_PARTIZIONE.match(r):
            dentro_articolo = False
            continue
        if not dentro_articolo:
            continue
        if RE_COMMA.match(r) or RE_COMMA_INLINE.match(r):
            continue
        mt = RE_COMMA_PERMISSIVA_TESTA.match(r) or RE_COMMA_PERMISSIVA_INLINE.match(r)
        if mt:
            comma_bis_non_risolti.append({"riga": r[:80], "numero": mt.group(1),
                                          "suffisso": mt.group(2)})
    m["comma_bis_non_risolti"] = comma_bis_non_risolti

    # --- (d) copertura _rubricaPresunta: rigioco fedele solo se le
    # intestazioni "Art." grezze e gli articoli prodotti sono in corrispondenza
    # 1-a-1 (altrimenti il documento e' gia' collassato, vedi gap_ratio, e
    # abbinare per posizione darebbe numeri inventati). ---
    rilevate = recuperate = perse = ambigue = 0
    if not dedotta and len(indici_art_veri) == len(articoli_normali) and articoli_normali:
        for idx_riga, art in zip(indici_art_veri, articoli_normali):
            j = _prossima_non_vuota(righe, idx_riga + 1)
            if j >= len(righe):
                continue
            riga_dopo = righe[j].strip()
            if riga_dopo.startswith("("):
                continue  # rubrica vera, non presunta
            if (RE_ARTICOLO.match(riga_dopo) or RE_PARTIZIONE.match(riga_dopo)
                    or RE_COMMA.match(riga_dopo) or RE_COMMA_INLINE.match(riga_dopo)):
                continue
            if len(riga_dopo) <= 80 and riga_dopo.endswith((".", ":")):
                rilevate += 1
                presunto = riga_dopo.rstrip(".:").strip()
                rubrica = art.get("rubrica")
                if rubrica == presunto:
                    perse += 1
                elif rubrica is None:
                    recuperate += 1
                else:
                    ambigue += 1
    m["rubrica_presunta"] = {"rilevate": rilevate, "recuperate": recuperate,
                             "perse": perse, "ambigue": ambigue}

    # --- esposizione bug 1.8: intestazione di partizione seguita da riga vuota ---
    m["partizione_seguita_da_vuota"] = sum(
        1 for i, r in enumerate(righe)
        if RE_PARTIZIONE.match(r.strip()) and i + 1 < len(righe) and not righe[i + 1].strip())

    return m


# --------------------------------------------------------------------------
# Aggregazione

def aggrega(risultati, soglia_gap, soglia_chars_pagina, top_n):
    tot = len(risultati)
    agg = {"totale_documenti": tot}

    def top(lista, chiave, n=top_n, reverse=True):
        return sorted(lista, key=chiave, reverse=reverse)[:n]

    # (a)
    con_gap = [r for r in risultati if r["gap_ratio"] is not None]
    flagged_a = [r for r in con_gap if r["gap_ratio"] > soglia_gap]
    agg["a_continuita_articoli"] = {
        "documenti_valutabili": len(con_gap),
        "documenti_con_gap_ampio": len(flagged_a),
        "percentuale": round(100 * len(flagged_a) / tot, 2) if tot else 0,
        "top": [{"id": r["id"], "gap_ratio": round(r["gap_ratio"], 3),
                 "numero_max_rilevato": r["max_numero_base"], "articoli_prodotti": r["n_articoli"]}
                for r in top(flagged_a, lambda r: r["gap_ratio"])],
    }

    # (b)
    con_pagine = [r for r in risultati if r["caratteri_per_pagina"] is not None]
    illeggibili = [r for r in risultati if r["pagine"] is None]
    flagged_b = [r for r in con_pagine if r["caratteri_per_pagina"] < soglia_chars_pagina]
    agg["b_testo_vs_pagine"] = {
        "documenti_valutabili": len(con_pagine),
        "pdf_illeggibili": len(illeggibili),
        "documenti_sotto_soglia": len(flagged_b),
        "percentuale": round(100 * len(flagged_b) / tot, 2) if tot else 0,
        "top": [{"id": r["id"], "caratteri_per_pagina": round(r["caratteri_per_pagina"], 1),
                 "pagine": r["pagine"], "caratteri_totali": r["caratteri_totali"]}
                for r in top(flagged_b, lambda r: r["caratteri_per_pagina"], reverse=False)],
        "top_illeggibili": [r["id"] for r in illeggibili[:top_n]],
    }

    # (c)
    con_lunghi = [r for r in risultati if r["commi_lunghi"]]
    tot_commi_lunghi = sum(len(r["commi_lunghi"]) for r in con_lunghi)
    agg["c_commi_anomali"] = {
        "documenti_con_almeno_uno": len(con_lunghi),
        "commi_totali_sopra_soglia": tot_commi_lunghi,
        "percentuale_documenti": round(100 * len(con_lunghi) / tot, 2) if tot else 0,
        "top": [{"id": r["id"], "n_commi_lunghi": len(r["commi_lunghi"]),
                 "lunghezza_massima": max(c["lunghezza"] for c in r["commi_lunghi"])}
                for r in top(con_lunghi, lambda r: max(c["lunghezza"] for c in r["commi_lunghi"]))],
    }

    # (d)
    rilevate = sum(r["rubrica_presunta"]["rilevate"] for r in risultati)
    recuperate = sum(r["rubrica_presunta"]["recuperate"] for r in risultati)
    perse = sum(r["rubrica_presunta"]["perse"] for r in risultati)
    ambigue = sum(r["rubrica_presunta"]["ambigue"] for r in risultati)
    con_perse = [r for r in risultati if r["rubrica_presunta"]["perse"] > 0]
    agg["d_rubrica_presunta"] = {
        "occorrenze_rilevate": rilevate, "recuperate_come_comma": recuperate,
        "perse_solo_in_rubrica": perse, "ambigue": ambigue,
        "documenti_con_perdita": len(con_perse),
        "top": [{"id": r["id"], "perse": r["rubrica_presunta"]["perse"]}
                for r in top(con_perse, lambda r: r["rubrica_presunta"]["perse"])],
    }

    # (e)
    vuoti = [r for r in risultati if r["vuoto_o_quasi"]]
    agg["e_documenti_vuoti"] = {
        "totale": len(vuoti),
        "percentuale": round(100 * len(vuoti) / tot, 2) if tot else 0,
        "top": [r["id"] for r in vuoti[:top_n]],
    }

    # (f)
    tot_cit_per_tipo = Counter()
    tot_mancanti = 0
    for r in risultati:
        tot_cit_per_tipo.update(r["citazioni_per_tipo"])
        tot_mancanti += r["citazioni_tipi_mancanti_stimate"]
    tipi_mai_coperti = ["Statuto", "Notifica", "Ordinanza", "Verbale", "Errata Corrige"]
    con_mancanti = [r for r in risultati if r["citazioni_tipi_mancanti_stimate"] > 0]
    agg["f_copertura_tipi_citazione"] = {
        "citazioni_per_tipo_riconosciuto": dict(tot_cit_per_tipo),
        "tipi_sempre_a_zero_per_costruzione": {t: tot_cit_per_tipo.get(t, 0) for t in tipi_mai_coperti},
        "occorrenze_stimate_non_catturabili": tot_mancanti,
        "documenti_con_occorrenze_stimate": len(con_mancanti),
        "top": [{"id": r["id"], "occorrenze": r["citazioni_tipi_mancanti_stimate"]}
                for r in top(con_mancanti, lambda r: r["citazioni_tipi_mancanti_stimate"])],
    }

    # (g)
    con_g = [r for r in risultati if r["art_bis_non_risolti"]]
    tot_g = sum(len(r["art_bis_non_risolti"]) for r in con_g)
    agg["g_art_bis_non_risolti"] = {
        "documenti_impattati": len(con_g), "occorrenze_totali": tot_g,
        "percentuale": round(100 * len(con_g) / tot, 2) if tot else 0,
        "top": [{"id": r["id"], "occorrenze": len(r["art_bis_non_risolti"]),
                 "esempio": r["art_bis_non_risolti"][0]["riga"] if r["art_bis_non_risolti"] else None}
                for r in top(con_g, lambda r: len(r["art_bis_non_risolti"]))],
    }

    # (h)
    con_h = [r for r in risultati if r["comma_bis_non_risolti"]]
    tot_h = sum(len(r["comma_bis_non_risolti"]) for r in con_h)
    agg["h_comma_bis_non_risolti"] = {
        "documenti_impattati": len(con_h), "occorrenze_totali": tot_h,
        "percentuale": round(100 * len(con_h) / tot, 2) if tot else 0,
        "top": [{"id": r["id"], "occorrenze": len(r["comma_bis_non_risolti"]),
                 "esempio": r["comma_bis_non_risolti"][0]["riga"] if r["comma_bis_non_risolti"] else None}
                for r in top(con_h, lambda r: len(r["comma_bis_non_risolti"]))],
    }

    # bonus: esposizione 1.8 (partizione + riga vuota)
    con_18 = [r for r in risultati if r["partizione_seguita_da_vuota"] > 0]
    agg["bonus_1_8_partizione_riga_vuota"] = {
        "documenti_esposti": len(con_18),
        "occorrenze_totali": sum(r["partizione_seguita_da_vuota"] for r in con_18),
    }

    # --- mappa sui problemi della review ---
    impatto_1_4 = {r["id"] for r in flagged_a} | {r["id"] for r in con_lunghi}
    impatto_1_5 = {r["id"] for r in vuoti} | {r["id"] for r in flagged_b} | {r["id"] for r in illeggibili}
    agg["problemi_review"] = {
        "1.1_rubrica_presunta_persa": {"documenti_impattati": len(con_perse), "occorrenze": perse},
        "1.2_art_bis_trattino_non_risolto": {"documenti_impattati": len(con_g), "occorrenze": tot_g},
        "1.3_comma_bis_non_risolto": {"documenti_impattati": len(con_h), "occorrenze": tot_h},
        "1.4_collasso_strutturale_parziale": {"documenti_impattati": len(impatto_1_4)},
        "1.5_documenti_vuoti_o_pdf_scansionato": {"documenti_impattati": len(impatto_1_5)},
        "1.6_tipi_citazione_mai_estratti": {"documenti_con_occorrenze_stimate": len(con_mancanti),
                                            "occorrenze_stimate": tot_mancanti},
        "1.7_statuti_parser_alternativo": {"nota": "fuori scope: 02_parse.py salta le cartelle S-* "
                                          "per design, non misurabile da questa baseline"},
        "1.8_partizione_rubrica_riga_vuota_esposizione": {"documenti_esposti": len(con_18)},
    }

    return agg


def render_markdown(agg, parametri):
    r = agg
    L = []
    L.append(f"# Report QA baseline — {parametri['generato']}\n")
    L.append(f"Documenti analizzati: **{r['totale_documenti']}** "
             f"(parsed: `{parametri['parsed_dir']}`, raw: `{parametri['raw_dir']}`)\n")
    L.append("Parametri: soglia gap = {a}%, soglia caratteri/pagina = {b}, "
             "taglio comma = {c}\n".format(a=int(parametri['soglia_gap'] * 100),
                                           b=parametri['soglia_chars_pagina'],
                                           c=parametri['taglio_comma']))

    L.append("## Sintesi impatto per problema della review\n")
    L.append("| Problema | Documenti impattati | Occorrenze |")
    L.append("|---|---|---|")
    for k, v in r["problemi_review"].items():
        doc = v.get("documenti_impattati", v.get("documenti_esposti",
              v.get("documenti_con_occorrenze_stimate", "-")))
        occ = v.get("occorrenze", v.get("occorrenze_stimate", v.get("nota", "-")))
        L.append(f"| {k} | {doc} | {occ} |")
    L.append("")

    def sezione(titolo, chiave, campi_top):
        d = r[chiave]
        L.append(f"## {titolo}\n")
        for k, v in d.items():
            if k == "top" or k.startswith("top_"):
                continue
            L.append(f"- **{k}**: {v}")
        if d.get("top"):
            L.append("\n Top offenders:\n")
            for row in d["top"]:
                L.append("  - " + ", ".join(f"{c}={row.get(c)}" for c in campi_top if c in row))
        L.append("")

    sezione("(a) Continuità numerazione articoli", "a_continuita_articoli",
            ["id", "gap_ratio", "numero_max_rilevato", "articoli_prodotti"])
    sezione("(b) Rapporto testo estratto / pagine PDF", "b_testo_vs_pagine",
            ["id", "caratteri_per_pagina", "pagine", "caratteri_totali"])
    sezione("(c) Commi anomalamente lunghi", "c_commi_anomali",
            ["id", "n_commi_lunghi", "lunghezza_massima"])
    sezione("(d) Copertura rubrica presunta", "d_rubrica_presunta", ["id", "perse"])
    sezione("(e) Documenti vuoti o quasi", "e_documenti_vuoti", [])
    sezione("(f) Copertura tipi di citazione", "f_copertura_tipi_citazione",
            ["id", "occorrenze"])
    sezione("(g) \"Art. N-bis\" non risolti nel testo grezzo", "g_art_bis_non_risolti",
            ["id", "occorrenze", "esempio"])
    sezione("(h) \"comma N bis/ter\" non risolti nel testo grezzo", "h_comma_bis_non_risolti",
            ["id", "occorrenze", "esempio"])

    return "\n".join(L)


def esegui(parsed_dir, raw_dir, out_base, soglia_gap=0.20, soglia_chars_pagina=250,
          taglio_comma=None, top_n=20):
    parsed_dir, raw_dir, out_base = Path(parsed_dir), Path(raw_dir), Path(out_base)
    global TAGLIO_COMMA_DEFAULT
    if taglio_comma:
        TAGLIO_COMMA_DEFAULT = taglio_comma

    file_json = sorted(parsed_dir.glob("*.json"))
    if not file_json:
        raise RuntimeError(f"{parsed_dir} e' vuota: nessun documento da analizzare.")

    risultati, errori = [], []
    out_base.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_base.with_suffix(".jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as fjsonl:
        for idx, f in enumerate(file_json, 1):
            try:
                dati = json.loads(f.read_text(encoding="utf-8"))
                nid = dati.get("id", f.stem)
                pdf_path = raw_dir / nid / "testo.pdf"
                m = analizza_documento_da_path(nid, dati, pdf_path)
            except Exception as e:
                errori.append({"file": f.name, "errore": f"{type(e).__name__}: {e}",
                              "traceback": traceback.format_exc()[-800:]})
                continue
            risultati.append(m)
            fjsonl.write(json.dumps(m, ensure_ascii=False) + "\n")
            if idx % 500 == 0 or idx == len(file_json):
                print(f"  [{idx}/{len(file_json)}] analizzati...", flush=True)

    agg = aggrega(risultati, soglia_gap, soglia_chars_pagina, top_n)
    agg["documenti_con_errore_qa"] = len(errori)
    agg["errori_qa"] = errori[:20]

    parametri = {
        "generato": datetime.now().isoformat(timespec="seconds"),
        "parsed_dir": str(parsed_dir), "raw_dir": str(raw_dir),
        "soglia_gap": soglia_gap, "soglia_chars_pagina": soglia_chars_pagina,
        "taglio_comma": TAGLIO_COMMA_DEFAULT,
    }
    report = {"parametri": parametri, **agg}

    json_path = out_base.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = out_base.with_suffix(".md")
    md_path.write_text(render_markdown(agg, parametri), encoding="utf-8")

    print(f"\nQA completata su {len(risultati)} documenti ({len(errori)} errori).")
    print(f"  {json_path}")
    print(f"  {md_path}")
    print(f"  {jsonl_path}")
    return report


def main():
    ap = argparse.ArgumentParser(description="QA di baseline sul parsing (sola lettura).")
    ap.add_argument("--parsed", default=str(ROOT / "data" / "parsed"))
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--out", default=str(ROOT / "data" / "qa_report"))
    ap.add_argument("--soglia-gap", type=float, default=0.20)
    ap.add_argument("--soglia-chars-pagina", type=float, default=250)
    ap.add_argument("--taglio-comma", type=int, default=None)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    esegui(args.parsed, args.raw, args.out, soglia_gap=args.soglia_gap,
          soglia_chars_pagina=args.soglia_chars_pagina,
          taglio_comma=args.taglio_comma, top_n=args.top)


if __name__ == "__main__":
    main()
