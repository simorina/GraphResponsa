"""
Snapshot integrale del Knowledge Graph di San Marino.

Estrae e disegna ogni nodo e ogni arco in una galassia ad altissima densita'.

Tutti i conteggi vengono dal database, nessuno e' scritto nel codice: una
legenda con numeri fissi diventa falsa al primo caricamento, e un'infografica
che dichiara cifre sbagliate e' peggio di nessuna infografica.

Uso:
    python src/snapshot_grafo_completo.py
"""

import math
import os
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection, PathCollection
from matplotlib.gridspec import GridSpec
import numpy as np
from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")


# Un settore angolare per etichetta. Devono esserci TUTTE: quelle che
# mancano finiscono nel grigio indistinto di "Altro", e i regolamenti o le
# notifiche sparirebbero dalla mappa pur essendo migliaia.
SECTOR_MAP = {
    # Vertice dell'ordinamento: al centro, in oro
    "LeggeCostituzionale":          (0.0, 0.0, "#f59e0b", 0),
    "LeggeQualificata":             (0.0, 0.0, "#f59e0b", 0),
    "LeggeRevisioneCostituzionale": (0.0, 0.0, "#f59e0b", 0),
    # Corone esterne, un arco ciascuna
    "Legge":              (0.15, 1.05, "#38bdf8", 1),
    "DecretoDelegato":    (1.10, 2.10, "#818cf8", 2),
    "Decreto":            (2.15, 3.45, "#0ea5e9", 3),
    "DecretoLegge":       (3.50, 4.10, "#ec4899", 4),
    "DecretoConsiliare":  (4.15, 4.65, "#a855f7", 5),
    "DecretoReggenziale": (4.70, 5.15, "#10b981", 6),
    "Regolamento":        (5.20, 5.60, "#f472b6", 7),
    "Notifica":           (5.65, 5.90, "#fbbf24", 8),
    "ErrataCorrige":      (5.95, 6.10, "#94a3b8", 9),
    "Ordinanza":          (6.12, 6.22, "#2dd4bf", 10),
    "Statuto":            (6.24, 6.28, "#e879f9", 11),
    "Verbale":            (6.24, 6.28, "#fb923c", 12),
    "NonDefinito":        (5.90, 5.95, "#64748b", 13),
    "Altro":              (5.90, 5.95, "#64748b", 13),
}



def estrai_tutto_il_grafo():
    """Estrae l'intero grafo da Neo4j con coordinate e relazioni."""
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])
    )
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    
    t0 = time.time()
    print("1/4 Norme...")
    with driver.session(database=db) as s:
        # Si usa l'etichetta Cypher, non n.tipo: il campo grezzo del portale ha
        # decine di varianti e refusi ("Decreto  Delegato", "Decreto - Legga"),
        # mentre la label e' gia' normalizzata da norma_label().
        norme = s.run("""
            MATCH (n:Norma)
            WITH n, [l IN labels(n) WHERE l <> 'Norma'][0] AS etichetta
            RETURN n.id AS id, coalesce(etichetta, 'Altro') AS tipo,
                   coalesce(n.anno, 2000) AS anno, coalesce(n.numero, 1) AS numero,
                   coalesce(n.caricata, false) AS caricata
        """).data()

        print("2/4 Articoli e allegati...")
        articoli = s.run("""
            MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)
            RETURN a.id AS id, n.id AS normaId, coalesce(a.ordine, 0) AS ordine
        """).data()
        
        allegati = s.run("""
            MATCH (n:Norma)-[:HA_ALLEGATO]->(al:Allegato)
            RETURN al.id AS id, n.id AS normaId
        """).data()

        print("3/4 Commi...")
        commi = s.run("""
            MATCH (a:Articolo)-[:HA_COMMA]->(c:Comma)
            RETURN c.id AS id, a.id AS artId, coalesce(c.numero, '1') AS numero
        """).data()

        print("4/4 Citazioni...")
        citazioni = s.run("""
            MATCH (source)-[r:CITA]->(target:Norma)
            RETURN source.id AS daId, target.id AS versoId, 'CITA' AS tipo
            UNION ALL
            MATCH (source:Comma)-[r:CITA_ARTICOLO]->(target:Articolo)
            RETURN source.id AS daId, target.id AS versoId, 'CITA_ARTICOLO' AS tipo
        """).data()

    driver.close()
    print(f"Estrazione completata in {time.time() - t0:.2f}s!")
    return {
        "norme": norme,
        "articoli": articoli,
        "allegati": allegati,
        "commi": commi,
        "citazioni": citazioni
    }


def calcola_layout_galassia(dati):
    """Calcola le coordinate 2D di ogni nodo."""
    t0 = time.time()
    print("Calcolo delle coordinate...")
    
    pos = {}      # id -> (x, y)
    colori = {}   # id -> hex color
    categorie = {} # id -> categoria
    
    # Ripartizione settoriale per tipologia di atto normativo
    # 1. Posiziona le Norme (Hubs)
    np.random.seed(42)
    for n in dati["norme"]:
        nid = n["id"]
        tipo = n["tipo"]
        
        # Estrazione sicura di anno e numero (supporta anche '6-EC')
        import re
        nums_anno = re.findall(r'\d+', str(n.get("anno", "")))
        anno = int(nums_anno[0]) if nums_anno else 2000
        anno = max(1854, min(2026, anno))
        
        nums_num = re.findall(r'\d+', str(n.get("numero", "")))
        num = int(nums_num[0]) if nums_num else 1
        
        # Mappa tipo a settore angolare
        info_settore = SECTOR_MAP.get(tipo, SECTOR_MAP["Altro"])
        theta_min, theta_max, col, sec_id = info_settore
        
        if sec_id == 0:  # Centro costituzionale
            r = np.random.uniform(0.02, 0.12)
            theta = np.random.uniform(0, 2 * math.pi)
        else:
            # Raggio proporzionale all'anno (dal 1854 al 2026 dal centro verso l'esterno)
            progressione_temporale = (anno - 1850) / 180.0
            r = 0.18 + progressione_temporale * 0.78 + np.random.uniform(-0.02, 0.02)
            # Angolo proporzionale al numero e dispersione
            theta = theta_min + ((num % 100) / 100.0) * (theta_max - theta_min) + np.random.uniform(-0.04, 0.04)
        
        x = r * math.cos(theta)
        y = r * math.sin(theta)
        pos[nid] = (x, y)
        colori[nid] = col
        categorie[nid] = tipo

    # 2. Posiziona gli Articoli (Orbite di 1° livello)
    for a in dati["articoli"]:
        aid = a["id"]
        nid = a["normaId"]
        try:
            ordine = int(a.get("ordine", 0) or 0)
        except Exception:
            ordine = 0
        if nid in pos:
            nx, ny = pos[nid]
            # Angolo dell'articolo attorno alla norma
            a_theta = (ordine * 0.45) % (2 * math.pi)
            a_r = 0.025 + min(0.06, (ordine % 10) * 0.005) + np.random.uniform(0.001, 0.008)
            ax = nx + a_r * math.cos(a_theta)
            ay = ny + a_r * math.sin(a_theta)
            pos[aid] = (ax, ay)
            colori[aid] = "#34d399"  # Verde Smeraldo chiaro
            categorie[aid] = "Articolo"

    # 3. Posiziona gli Allegati
    for al in dati["allegati"]:
        alid = al["id"]
        nid = al["normaId"]
        if nid in pos:
            nx, ny = pos[nid]
            ax = nx + np.random.uniform(-0.03, 0.03)
            ay = ny + np.random.uniform(-0.03, 0.03)
            pos[alid] = (ax, ay)
            colori[alid] = "#fbbf24"  # Giallo
            categorie[alid] = "Allegato"

    # 4. Posiziona i Commi (Micro-orbite di 2° livello)
    for c in dati["commi"]:
        cid = c["id"]
        aid = c["artId"]
        num_str = str(c["numero"])
        c_num = int(num_str) if num_str.isdigit() else 1
        if aid in pos:
            ax, ay = pos[aid]
            c_theta = (c_num * 1.1) % (2 * math.pi)
            c_r = 0.012 + np.random.uniform(0.001, 0.005)
            cx = ax + c_r * math.cos(c_theta)
            cy = ay + c_r * math.sin(c_theta)
            pos[cid] = (cx, cy)
            colori[cid] = "#64748b"  # Grigio ardesia
            categorie[cid] = "Comma"

    print(f"Posizionati {len(pos):,d} nodi in {time.time() - t0:.2f}s!")
    return pos, colori, categorie


def renderizza_snapshot_completo(dati, pos, colori):
    """Genera l'immagine a 300 DPI con ogni nodo e ogni arco."""
    t0 = time.time()
    print("Inizio rendering rasterizzato ad altissima risoluzione...")
    
    BG_COLOR = "#040711"
    PANEL_BG = "#080e1c"
    TEXT_MAIN = "#f8fafc"
    TEXT_MUTED = "#94a3b8"
    
    # 1. Costruzione segmenti archi
    linee_commi = []
    linee_articoli = []
    linee_allegati = []
    linee_cita = []
    linee_cita_art = []
    
    for a in dati["articoli"]:
        if a["normaId"] in pos and a["id"] in pos:
            linee_articoli.append([pos[a["normaId"]], pos[a["id"]]])
            
    for c in dati["commi"]:
        if c["artId"] in pos and c["id"] in pos:
            linee_commi.append([pos[c["artId"]], pos[c["id"]]])
            
    for al in dati["allegati"]:
        if al["normaId"] in pos and al["id"] in pos:
            linee_allegati.append([pos[al["normaId"]], pos[al["id"]]])
            
    for cit in dati["citazioni"]:
        da = cit["daId"]
        verso = cit["versoId"]
        if da in pos and verso in pos:
            if cit["tipo"] == "CITA":
                linee_cita.append([pos[da], pos[verso]])
            else:
                linee_cita_art.append([pos[da], pos[verso]])
                
    print(f"Segmenti costruiti: {len(linee_commi):,d} HA_COMMA, {len(linee_articoli):,d} HA_ARTICOLO, {len(linee_cita):,d} CITA, {len(linee_cita_art):,d} CITA_ARTICOLO, {len(linee_allegati):,d} HA_ALLEGATO.")
    
    # 2. Setup Canvas Matplotlib (24 x 14 pollici ad altissima densita')
    fig = plt.figure(figsize=(24, 14), facecolor=BG_COLOR)
    gs = GridSpec(1, 2, width_ratios=[2.4, 1.0], figure=fig, wspace=0.10)
    
    # --- Canvas Sinistro: La Galassia del Knowledge Graph ---
    ax_graph = fig.add_subplot(gs[0, 0], facecolor=BG_COLOR)
    ax_graph.set_title("MAPPA TOPOLOGICA: OGNI NODO E OGNI ARCO", 
                       color=TEXT_MAIN, fontsize=14, fontweight="bold", pad=15, loc="left")

    # Disegna Archi di Citazione (Chords dorati e rosa che attraversano la galassia)
    # Le citazioni attraversano tutto il disco: a 69.662 archi, l'opacita' che
    # andava bene per 21.000 satura l'immagine e nasconde i settori che la
    # mappa dovrebbe mostrare.
    lc_cita = LineCollection(linee_cita, colors="#f59e0b", linewidths=0.22, alpha=0.055, rasterized=True)
    ax_graph.add_collection(lc_cita)
    
    lc_cita_art = LineCollection(linee_cita_art, colors="#ec4899", linewidths=0.3, alpha=0.10, rasterized=True)
    ax_graph.add_collection(lc_cita_art)

    # Disegna Archi Strutturali
    lc_art = LineCollection(linee_articoli, colors="#34d399", linewidths=0.2, alpha=0.07, rasterized=True)
    ax_graph.add_collection(lc_art)
    
    lc_commi = LineCollection(linee_commi, colors="#475569", linewidths=0.12, alpha=0.045, rasterized=True)
    ax_graph.add_collection(lc_commi)

    # Ogni nodo, diviso per classe
    all_x = np.array([pos[k][0] for k in pos], dtype=np.float32)
    all_y = np.array([pos[k][1] for k in pos], dtype=np.float32)
    all_c = [colori[k] for k in pos]
    
    # Dimensioni differenziate per livello
    all_s = []
    for k in pos:
        col = colori[k]
        if col == "#64748b":      # Comma
            all_s.append(0.6)
        elif col == "#34d399":    # Articolo
            all_s.append(2.5)
        elif col in ("#f59e0b", "#fbbf24"):  # Costituzionale / Allegato
            all_s.append(22.0)
        else:                     # Norma
            all_s.append(12.0)
            
    ax_graph.scatter(all_x, all_y, s=all_s, c=all_c, alpha=0.75, edgecolors="none", rasterized=True)
    
    # Etichette dei poli cardinali normativi
    # Le etichette vanno dove i nodi stanno davvero. Posizioni fisse su un
    # layout calcolato diventano bugie appena il corpus cambia.
    import collections
    per_settore = collections.defaultdict(list)
    for n in dati["norme"]:
        if n["id"] in pos:
            per_settore[n["tipo"]].append(pos[n["id"]])

    DA_ETICHETTARE = {
        "Legge": "LEGGI",
        "Decreto": "DECRETI",
        "DecretoDelegato": "DECRETI DELEGATI",
        "DecretoLegge": "DECRETI-LEGGE",
        "DecretoConsiliare": "ATTI CONSILIARI",
        "DecretoReggenziale": "ATTI REGGENZIALI",
        "Regolamento": "REGOLAMENTI",
    }
    for tipo, testo in DA_ETICHETTARE.items():
        punti = per_settore.get(tipo)
        if not punti or len(punti) < 50:
            continue
        # Il baricentro del settore, spinto un po' verso l'esterno perche'
        # l'etichetta non copra i nodi che descrive.
        px = float(np.mean([q[0] for q in punti])) * 1.35
        py = float(np.mean([q[1] for q in punti])) * 1.35
        col = SECTOR_MAP.get(tipo, SECTOR_MAP["Altro"])[2]
        ax_graph.text(px, py, f"{testo}\n{len(punti):,d}".replace(",", "."),
                      color=col, fontsize=8.5, fontweight="bold", ha="center", va="center",
                      bbox=dict(boxstyle="round,pad=0.3", fc="#050811", ec=col, lw=0.8, alpha=0.9))

    vertice_punti = [q for t in ("LeggeCostituzionale", "LeggeQualificata",
                                 "LeggeRevisioneCostituzionale") for q in per_settore.get(t, [])]
    if vertice_punti:
        ax_graph.text(0.0, 0.0, f"VERTICE COSTITUZIONALE\n{len(vertice_punti)}",
                      color="#f59e0b", fontsize=8.5, fontweight="bold", ha="center", va="center",
                      bbox=dict(boxstyle="round,pad=0.3", fc="#050811", ec="#f59e0b", lw=0.8, alpha=0.9))

    ax_graph.set_xlim(-1.15, 1.15)
    ax_graph.set_ylim(-1.10, 1.15)
    ax_graph.axis("off")

    # --- Pannello Destro: Legenda Dettagliata delle Classi ---
    ax_legend = fig.add_subplot(gs[0, 1], facecolor=PANEL_BG)
    ax_legend.set_title("LEGENDA COMPLETA CLASSI & METRICHE", color=TEXT_MAIN, fontsize=13, fontweight="bold", pad=15, loc="left")
    ax_legend.axis("off")

    # Sezione 1: Nodi
    # Tutti i conteggi si ricavano qui dai dati appena estratti. Scriverli a
    # mano significa che al primo caricamento la legenda comincia a mentire.
    import collections
    per_tipo = collections.Counter(n["tipo"] for n in dati["norme"])
    n_commi, n_art, n_all = len(dati["commi"]), len(dati["articoli"]), len(dati["allegati"])
    n_nodi = len(pos)

    DESCRIZIONI = {
        "Comma": "Testo integrale dei commi atomici",
        "Articolo": "Articoli numerati con rubrica",
        "Decreto": "Decreti generali storici",
        "DecretoDelegato": "Decreti delegati governativi",
        "Legge": "Leggi approvate dal Consiglio",
        "DecretoLegge": "Provvedimenti d'urgenza",
        "DecretoConsiliare": "Atti emanati dal CGG",
        "DecretoReggenziale": "Atti promulgati dalla Reggenza",
        "Regolamento": "Regolamenti attuativi",
        "Notifica": "Notifiche delle Segreterie di Stato",
        "ErrataCorrige": "Rettifiche a testi pubblicati",
        "Ordinanza": "Ordinanze",
        "Statuto": "Corpi statutari storici",
        "Verbale": "Verbali",
        "NonDefinito": "Atti senza tipologia dichiarata",
        "Allegato": "Tabelle tecniche e cartografie",
    }

    ax_legend.text(0.03, 0.96, f"CLASSI DEI NODI ({n_nodi:,d} totali)".replace(",", "."),
                   color="#38bdf8", fontsize=10.5, fontweight="bold", transform=ax_legend.transAxes)

    node_entries = [
        ("Comma", n_commi, "#64748b"),
        ("Articolo", n_art, "#34d399"),
    ]
    # Le norme, dalla piu' numerosa alla meno; le costituzionali insieme.
    vertice = sum(per_tipo[t] for t in
                  ("LeggeCostituzionale", "LeggeQualificata", "LeggeRevisioneCostituzionale"))
    for tipo, quante in per_tipo.most_common():
        if tipo in ("LeggeCostituzionale", "LeggeQualificata", "LeggeRevisioneCostituzionale"):
            continue
        node_entries.append((tipo, quante, SECTOR_MAP.get(tipo, SECTOR_MAP["Altro"])[2]))
    node_entries.append(("Allegato", n_all, "#fbbf24"))
    if vertice:
        node_entries.append(("Costituzionali e Qualificate", vertice, "#f59e0b"))

    # Il pannello ha spazio per una quindicina di righe: le classi minori si
    # accorpano invece di uscire dal riquadro.
    if len(node_entries) > 14:
        coda = node_entries[13:]
        node_entries = node_entries[:13] + [("Altre classi minori", sum(c for _, c, _ in coda), "#475569")]

    passo = min(0.048, 0.52 / max(1, len(node_entries)))
    y = 0.91
    for name, cnt, col in node_entries:
        pct = (cnt / max(1, n_nodi)) * 100
        desc = DESCRIZIONI.get(name, "")
        ax_legend.text(0.04, y, "●", color=col, fontsize=14, fontweight="bold", transform=ax_legend.transAxes)
        ax_legend.text(0.10, y + 0.002, name, color=TEXT_MAIN, fontsize=9.0, fontweight="bold", transform=ax_legend.transAxes)
        ax_legend.text(0.68, y + 0.002, f"{cnt:,d}".replace(",", ".").rjust(9), color="#38bdf8",
                       fontsize=9.0, fontweight="bold", fontfamily="monospace", transform=ax_legend.transAxes)
        ax_legend.text(0.89, y + 0.002, f"({pct:4.1f}%)", color=TEXT_MUTED, fontsize=8.0, transform=ax_legend.transAxes)
        if desc:
            ax_legend.text(0.10, y - 0.019, desc, color=TEXT_MUTED, fontsize=7.2, transform=ax_legend.transAxes)
        y -= passo

    # Separatore
    ax_legend.plot([0.03, 0.97], [0.41, 0.41], color="#1e293b", linewidth=1.2, transform=ax_legend.transAxes)

    # Sezione 2: Archi
    n_cita, n_cita_art = len(linee_cita), len(linee_cita_art)
    n_archi = len(linee_commi) + len(linee_articoli) + n_cita + n_cita_art + len(linee_allegati)

    ax_legend.text(0.03, 0.38, f"CLASSI DEGLI ARCHI ({n_archi:,d} totali)".replace(",", "."),
                   color="#f59e0b", fontsize=10.5, fontweight="bold", transform=ax_legend.transAxes)

    rel_entries = [
        ("HA_COMMA", len(linee_commi), "#475569", "—", "Articolo -> Comma"),
        ("HA_ARTICOLO", len(linee_articoli), "#34d399", "—", "Norma -> Articolo"),
        ("CITA", n_cita, "#f59e0b", "--", "Rinvii fra norme, preambolo compreso"),
        ("CITA_ARTICOLO", n_cita_art, "#ec4899", "··", "Rinvio puntuale a un articolo"),
        ("HA_ALLEGATO", len(linee_allegati), "#fbbf24", "—", "Norma -> Allegato"),
    ]

    y = 0.33
    for rel_name, cnt, col, line_sym, desc in rel_entries:
        pct = (cnt / max(1, n_archi)) * 100
        ax_legend.text(0.04, y, line_sym, color=col, fontsize=12, fontweight="bold", transform=ax_legend.transAxes)
        ax_legend.text(0.10, y + 0.002, f":{rel_name}", color=TEXT_MAIN, fontsize=9.0, fontweight="bold", transform=ax_legend.transAxes)
        ax_legend.text(0.68, y + 0.002, f"{cnt:,d}".replace(",", ".").rjust(9), color="#38bdf8", fontsize=9.0, fontweight="bold", fontfamily="monospace", transform=ax_legend.transAxes)
        ax_legend.text(0.87, y + 0.002, f"({pct:4.1f}%)", color=TEXT_MUTED, fontsize=8.0, transform=ax_legend.transAxes)
        ax_legend.text(0.10, y - 0.020, f"{desc}", color=TEXT_MUTED, fontsize=7.5, transform=ax_legend.transAxes)
        y -= 0.048

    # Separatore e riepilogo
    ax_legend.plot([0.03, 0.97], [0.08, 0.08], color="#1e293b", linewidth=1.2, transform=ax_legend.transAxes)
    # Solo le norme con testo: gli stub nascono dal parsing delle citazioni e
    # ereditano i refusi del testo di partenza (esiste uno "L-194-2224").
    # anno = 0 significa "non dichiarato sulla scheda", non "anno zero":
    # entrerebbe nell'arco temporale e lo falserebbe di duemila anni.
    anni = [int(str(n["anno"])) for n in dati["norme"]
            if n.get("caricata") and str(n["anno"]).isdigit() and int(str(n["anno"])) >= 1500]
    arco = f"{min(anni)}-{max(anni)}" if anni else "n.d."
    ax_legend.text(0.04, 0.035, f"Corpus ufficiale della Repubblica di San Marino, {arco}",
                   color="#10b981", fontsize=8.5, fontweight="bold", transform=ax_legend.transAxes)
    ax_legend.text(0.04, 0.012, "Ogni nodo e ogni arco estratti da Neo4j Aura al momento della generazione.",
                   color=TEXT_MUTED, fontsize=7.5, transform=ax_legend.transAxes)

    # Intestazione
    mille = lambda v: f"{v:,d}".replace(",", ".")
    fig.suptitle("REPUBBLICA DI SAN MARINO - SNAPSHOT INTEGRALE DEL KNOWLEDGE GRAPH GIURIDICO\n"
                 f"{mille(n_nodi)} nodi  |  {mille(n_archi)} archi  |  "
                 f"{mille(len(dati['norme']))} atti censiti, {arco}",
                 color=TEXT_MAIN, fontsize=15, fontweight="bold", y=0.985)
    out_file = OUT / "snapshot_grafo_completo_all_nodes.png"
    plt.savefig(out_file, dpi=300, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close()
    
    print(f"\nSnapshot completo (100% nodi e archi) salvato in: {out_file} (tempo: {time.time() - t0:.2f}s)!")
    return out_file


if __name__ == "__main__":
    dati = estrai_tutto_il_grafo()
    pos, colori, categorie = calcola_layout_galassia(dati)
    renderizza_snapshot_completo(dati, pos, colori)
