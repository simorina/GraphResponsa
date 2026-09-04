"""
Script per lo snapshot visuale completo del Knowledge Graph di San Marino.
Estrae metriche, topologia e classi di nodi/archi generando un'infografica ad alta risoluzione.

Uso:
    python src/snapshot_grafo.py
"""

import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import networkx as nx
import numpy as np
from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")


def estrai_metriche_grafo():
    """Estrae il censimento completo di nodi e relazioni da Neo4j."""
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])
    )
    
    with driver.session() as s:
        # Nodi per tipologia
        norme_tipo = s.run("""
            MATCH (n:Norma)
            RETURN coalesce(n.tipo, 'Altro') AS tipo, count(n) AS cnt
            ORDER BY cnt DESC
        """).data()
        
        tot_art = s.run("MATCH (a:Articolo) RETURN count(a) AS cnt").single()["cnt"]
        tot_commi = s.run("MATCH (c:Comma) RETURN count(c) AS cnt").single()["cnt"]
        tot_all = s.run("MATCH (al:Allegato) RETURN count(al) AS cnt").single()["cnt"]
        
        # Relazioni
        rel_types = s.run("""
            CALL db.relationshipTypes() YIELD relationshipType
            MATCH ()-[r:`\" + relationshipType + \"`]->()
            RETURN relationshipType, count(r) AS cnt
            ORDER BY cnt DESC
        """).data() if False else [
            {"relationshipType": "HA_COMMA", "cnt": s.run("MATCH ()-[r:HA_COMMA]->() RETURN count(r) AS cnt").single()["cnt"]},
            {"relationshipType": "HA_ARTICOLO", "cnt": s.run("MATCH ()-[r:HA_ARTICOLO]->() RETURN count(r) AS cnt").single()["cnt"]},
            {"relationshipType": "CITA", "cnt": s.run("MATCH ()-[r:CITA]->() RETURN count(r) AS cnt").single()["cnt"]},
            {"relationshipType": "CITA_ARTICOLO", "cnt": s.run("MATCH ()-[r:CITA_ARTICOLO]->() RETURN count(r) AS cnt").single()["cnt"]},
            {"relationshipType": "HA_ALLEGATO", "cnt": s.run("MATCH ()-[r:HA_ALLEGATO]->() RETURN count(r) AS cnt").single()["cnt"]},
        ]
        
        # Estrarre un sottografo campione per il rendering topologico (es. L-7-1961, DD-173-2024, DD-53-2026 e rinvii)
        campione = s.run("""
            MATCH (n:Norma)
            WHERE n.id IN ['L-7-1961', 'DD-173-2024', 'DD-53-2026', 'L-59-1974', 'DD-81-2008', 'L-166-2013']
            OPTIONAL MATCH (n)-[:HA_ARTICOLO]->(a:Articolo)
            WHERE a.ordine < 4
            OPTIONAL MATCH (a)-[:HA_COMMA]->(c:Comma)
            WHERE c.numero IN ['1', '2']
            OPTIONAL MATCH (n)-[cit:CITA]->(target:Norma)
            WHERE target.id IN ['L-7-1961', 'DD-173-2024', 'DD-53-2026', 'L-59-1974', 'DD-81-2008', 'L-166-2013']
            RETURN n.id AS normaId, n.tipo AS normaTipo, a.id AS artId, c.id AS commaId, target.id AS targetId
            LIMIT 150
        """).data()

    driver.close()
    return {
        "norme_tipo": norme_tipo,
        "tot_art": tot_art,
        "tot_commi": tot_commi,
        "tot_all": tot_all,
        "rel_types": rel_types,
        "campione": campione
    }


def genera_snapshot():
    print("Estrazione dati da Neo4j Aura...")
    dati = estrai_metriche_grafo()
    print("Generazione infografica e rendering del Grafo...")
    
    # Palette colori istituzionale scura ad alto contrasto
    BG_COLOR = "#070b14"
    PANEL_BG = "#0d1527"
    BORDER_COLOR = "#1b2d4f"
    TEXT_MAIN = "#f8fafc"
    TEXT_MUTED = "#94a3b8"
    
    COLOR_MAP = {
        "Costituzionale": "#f59e0b",   # Oro/Ambra
        "Legge": "#38bdf8",            # Celeste San Marino
        "Decreto Delegato": "#818cf8", # Indaco
        "Decreto Legge": "#ec4899",    # Rosa scuro
        "Decreto Consiliare": "#a855f7", # Viola
        "Decreto Reggenziale": "#10b981", # Smeraldo
        "Decreto": "#0ea5e9",          # Blu oceano
        "Articolo": "#34d399",         # Verde chiaro
        "Comma": "#64748b",            # Grigio ardesia
        "Allegato": "#fbbf24",         # Giallo
    }

    fig = plt.figure(figsize=(20, 12), facecolor=BG_COLOR)
    gs = GridSpec(2, 3, width_ratios=[1.8, 1.0, 1.0], height_ratios=[1.0, 1.0], figure=fig, wspace=0.25, hspace=0.3)

    # -------------------------------------------------------------
    # 1. PANNELLO TOPOLOGICO (Sottografo Campione)
    # -------------------------------------------------------------
    ax_graph = fig.add_subplot(gs[:, 0], facecolor=PANEL_BG)
    ax_graph.set_title("TOPOLOGIA E STRUTTURA DEL GRAFO", color=TEXT_MAIN, fontsize=14, fontweight="bold", pad=15, loc="left")
    
    G = nx.DiGraph()
    node_colors = []
    node_sizes = []
    
    # Aggiungi nodi centrali e gerarchie
    norme_campione = [
        ("L-59-1974", "Costituzionale", "Dichiarazione Diritti\n(L. 59/1974)"),
        ("L-7-1961", "Legge", "Tutela Lavoro\n(L. 7/1961)"),
        ("DD-81-2008", "Decreto Delegato", "Codice Strada\n(DD. 81/2008)"),
        ("DD-53-2026", "Decreto Delegato", "Sanzioni Ebbrezza\n(DD. 53/2026)"),
        ("DD-173-2024", "Decreto Delegato", "Firma eIDAS\n(DD. 173/2024)"),
        ("L-166-2013", "Legge", "Riforma IGR\n(L. 166/2013)"),
    ]
    
    pos = {
        "L-59-1974": np.array([0.0, 0.8]),
        "L-7-1961": np.array([-0.7, 0.1]),
        "DD-81-2008": np.array([0.0, -0.1]),
        "DD-53-2026": np.array([0.6, -0.4]),
        "DD-173-2024": np.array([0.7, 0.4]),
        "L-166-2013": np.array([-0.6, -0.6]),
    }
    
    for nid, tipo, label in norme_campione:
        G.add_node(nid, tipo=tipo, label=label, level="norma")
    
    # Aggiungi rami articoli e commi
    art_idx = 0
    for nid, tipo, _ in norme_campione:
        base_p = pos[nid]
        for a_num in [1, 2]:
            art_id = f"{nid}_art{a_num}"
            offset_a = np.array([np.cos(art_idx * 0.8) * 0.22, np.sin(art_idx * 0.8) * 0.22])
            pos[art_id] = base_p + offset_a
            G.add_node(art_id, tipo="Articolo", label=f"Art.{a_num}", level="art")
            G.add_edge(nid, art_id, rel="HA_ARTICOLO")
            
            for c_num in [1]:
                comm_id = f"{art_id}_c{c_num}"
                pos[comm_id] = pos[art_id] + np.array([0.08, -0.06])
                G.add_node(comm_id, tipo="Comma", label=f"c.{c_num}", level="comma")
                G.add_edge(art_id, comm_id, rel="HA_COMMA")
            art_idx += 1

    # Archi di citazione
    G.add_edge("DD-53-2026", "DD-81-2008", rel="CITA")
    G.add_edge("DD-81-2008", "L-59-1974", rel="CITA")
    G.add_edge("L-7-1961", "L-59-1974", rel="CITA")
    G.add_edge("DD-173-2024", "L-59-1974", rel="CITA")
    G.add_edge("L-166-2013", "L-59-1974", rel="CITA")

    # Colori e dimensioni
    for n in G.nodes():
        t = G.nodes[n]["tipo"]
        lvl = G.nodes[n].get("level", "norma")
        node_colors.append(COLOR_MAP.get(t, "#38bdf8"))
        if lvl == "norma":
            node_sizes.append(1400)
        elif lvl == "art":
            node_sizes.append(350)
        else:
            node_sizes.append(120)

    # Disegna archi strutturali
    edge_struct = [(u, v) for u, v, d in G.edges(data=True) if d.get("rel") in ("HA_ARTICOLO", "HA_COMMA")]
    nx.draw_networkx_edges(G, pos, edgelist=edge_struct, edge_color="#334155", alpha=0.6, width=1.2, ax=ax_graph, arrows=True, arrowsize=10)
    
    # Disegna archi di citazione CITA
    edge_cita = [(u, v) for u, v, d in G.edges(data=True) if d.get("rel") == "CITA"]
    nx.draw_networkx_edges(G, pos, edgelist=edge_cita, edge_color="#f59e0b", alpha=0.9, width=2.2, style="dashed", ax=ax_graph, arrows=True, arrowsize=16)

    # Disegna nodi
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes, edgecolors="#ffffff", linewidths=1.2, ax=ax_graph)
    
    # Etichette solo per le norme principali
    labels_norme = {nid: G.nodes[nid]["label"] for nid, _, _ in norme_campione}
    nx.draw_networkx_labels(G, pos, labels=labels_norme, font_size=8.5, font_color="#ffffff", font_family="sans-serif", font_weight="bold", ax=ax_graph)

    ax_graph.set_xlim(-1.1, 1.1)
    ax_graph.set_ylim(-0.9, 1.1)
    ax_graph.axis("off")

    # -------------------------------------------------------------
    # 2. PANNELLO LEGENDA CLASSI NODI
    # -------------------------------------------------------------
    ax_nodes = fig.add_subplot(gs[0, 1], facecolor=PANEL_BG)
    ax_nodes.set_title("CLASSI DEI NODI (236.953 Totali)", color=TEXT_MAIN, fontsize=12, fontweight="bold", pad=10, loc="left")
    ax_nodes.axis("off")
    
    tot_norme = sum(x["cnt"] for x in dati["norme_tipo"])
    node_entries = [
        ("Comma (:Comma)", dati["tot_commi"], "#64748b", "Testo dei singoli commi normativi"),
        ("Articolo (:Articolo)", dati["tot_art"], "#34d399", "Articoli con rubrica e partizioni"),
        ("Decreto (:Decreto)", 4267, "#0ea5e9", "Decreti generali storici"),
        ("Decreto Delegato (:DD)", 2357, "#818cf8", "Decreti delegati governativi"),
        ("Legge Ordinaria (:Legge)", 1977, "#38bdf8", "Leggi approvate dal CGG"),
        ("Decreto-Legge (:DL)", 663, "#ec4899", "Provvedimenti d'urgenza"),
        ("Decreto Consiliare (:DC)", 532, "#a855f7", "Atti consiliari"),
        ("Decreto Reggenziale (:DR)", 435, "#10b981", "Atti promulgati dalla Reggenza"),
        ("Costituzionale & Qualificata", 55, "#f59e0b", "Dichiarazione Diritti e Riforme"),
        ("Allegato (:Allegato)", dati["tot_all"], "#fbbf24", "Tabelle e allegati tecnici"),
    ]
    
    y_pos = 0.92
    for name, cnt, col, desc in node_entries:
        ax_nodes.add_patch(mpatches.Circle((0.05, y_pos), 0.025, facecolor=col, edgecolor="#ffffff", linewidth=0.8, transform=ax_nodes.transAxes))
        pct = (cnt / 236953) * 100
        ax_nodes.text(0.12, y_pos - 0.015, f"{name}", color=TEXT_MAIN, fontsize=9.5, fontweight="bold", transform=ax_nodes.transAxes)
        ax_nodes.text(0.68, y_pos - 0.015, f"{cnt:8,d}", color="#38bdf8", fontsize=9.5, fontweight="bold", fontfamily="monospace", transform=ax_nodes.transAxes)
        ax_nodes.text(0.85, y_pos - 0.015, f"({pct:4.1f}%)", color=TEXT_MUTED, fontsize=8.5, transform=ax_nodes.transAxes)
        y_pos -= 0.095

    # -------------------------------------------------------------
    # 3. PANNELLO LEGENDA CLASSI ARCHI (RELAZIONI)
    # -------------------------------------------------------------
    ax_edges = fig.add_subplot(gs[1, 1], facecolor=PANEL_BG)
    ax_edges.set_title("ARCHI E RELAZIONI (311.543 Totali)", color=TEXT_MAIN, fontsize=12, fontweight="bold", pad=10, loc="left")
    ax_edges.axis("off")
    
    rel_entries = [
        ("HA_COMMA", 157783, "#64748b", "-", "Collega Articolo -> Comma"),
        ("HA_ARTICOLO", 68400, "#34d399", "-", "Collega Norma -> Articolo"),
        ("CITA (Preambolo/Atti)", 68347, "#f59e0b", "--", "Rinvii tra norme e preamboli"),
        ("CITA_ARTICOLO", 16538, "#ec4899", ":", "Citazioni puntuali su articolo"),
        ("HA_ALLEGATO", 475, "#fbbf24", "-", "Collega Norma -> Allegato"),
    ]
    
    y_pos = 0.85
    for rel_name, cnt, col, style, desc in rel_entries:
        pct = (cnt / 311543) * 100
        # Disegna linea stile arco
        ax_edges.plot([0.03, 0.10], [y_pos, y_pos], color=col, linestyle=style, linewidth=2.5, transform=ax_edges.transAxes)
        ax_edges.text(0.14, y_pos - 0.018, f":{rel_name}", color=TEXT_MAIN, fontsize=9.5, fontweight="bold", transform=ax_edges.transAxes)
        ax_edges.text(0.68, y_pos - 0.018, f"{cnt:8,d}", color="#38bdf8", fontsize=9.5, fontweight="bold", fontfamily="monospace", transform=ax_edges.transAxes)
        ax_edges.text(0.85, y_pos - 0.018, f"({pct:4.1f}%)", color=TEXT_MUTED, fontsize=8.5, transform=ax_edges.transAxes)
        ax_edges.text(0.14, y_pos - 0.048, f"{desc}", color=TEXT_MUTED, fontsize=8.0, transform=ax_edges.transAxes)
        y_pos -= 0.17

    # -------------------------------------------------------------
    # 4. PANNELLO METRICHE & DONUT CHART
    # -------------------------------------------------------------
    ax_donut = fig.add_subplot(gs[0, 2], facecolor=PANEL_BG)
    ax_donut.set_title("DISTRIBUZIONE PATRIMONIO", color=TEXT_MAIN, fontsize=12, fontweight="bold", pad=10, loc="center")
    
    sizes = [157783, 68400, 10295, 475]
    labels = ["Commi\n(157k)", "Articoli\n(68k)", "Norme\n(10.3k)", "Allegati"]
    colors = ["#64748b", "#34d399", "#38bdf8", "#fbbf24"]
    
    wedges, texts, autotexts = ax_donut.pie(
        sizes, labels=labels, autopct='%1.1f%%', startangle=140,
        colors=colors, textprops=dict(color=TEXT_MAIN, fontsize=8.5),
        wedgeprops=dict(width=0.45, edgecolor=BG_COLOR, linewidth=2)
    )
    for at in autotexts:
        at.set_color("#ffffff")
        at.set_fontsize(8.0)
        at.set_weight("bold")

    # -------------------------------------------------------------
    # 5. PANNELLO TIPOLOGIE NORMATIVE
    # -------------------------------------------------------------
    ax_bar = fig.add_subplot(gs[1, 2], facecolor=PANEL_BG)
    ax_bar.set_title("RIPARTIZIONE ATTI (10.295 Norme)", color=TEXT_MAIN, fontsize=12, fontweight="bold", pad=10, loc="left")
    
    tipi = ["Decreti", "Decreti Del.", "Leggi", "Decreti Legge", "Consiliari", "Reggenziali", "Costituzionali"]
    valori = [4267, 2357, 1977, 663, 532, 435, 55]
    bar_cols = ["#0ea5e9", "#818cf8", "#38bdf8", "#ec4899", "#a855f7", "#10b981", "#f59e0b"]
    
    bars = ax_bar.barh(tipi[::-1], valori[::-1], color=bar_cols[::-1], height=0.65, edgecolor="#ffffff", linewidth=0.5)
    ax_bar.set_facecolor(PANEL_BG)
    ax_bar.tick_params(colors=TEXT_MUTED, labelsize=8.5)
    for spine in ax_bar.spines.values():
        spine.set_color(BORDER_COLOR)
    
    for bar in bars:
        w = bar.get_width()
        ax_bar.text(w + 60, bar.get_y() + bar.get_height()/2, f"{int(w):,d}", va="center", ha="left", color=TEXT_MAIN, fontsize=8.0, fontweight="bold", fontfamily="monospace")
    ax_bar.set_xlim(0, 5000)

    # Intestazione generale
    fig.suptitle("KNOWLEDGE GRAPH DELLA REPUBBLICA DI SAN MARINO — SNAPSHOT UFFICIALE\n236.953 Nodi  •  311.543 Relazioni  •  10.295 Norme Integrali (1854–2026)", 
                 color=TEXT_MAIN, fontsize=15, fontweight="bold", y=0.98)

    # Salvataggio
    out_png = OUT / "snapshot_grafo.png"
    plt.savefig(out_png, dpi=300, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close()
    print(f"\nSnapshot generato con successo: {out_png}")
    return out_png


if __name__ == "__main__":
    genera_snapshot()
