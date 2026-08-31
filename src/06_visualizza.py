"""
06 - Visualizzazione grafica interattiva del Knowledge Graph.

Estrae dal database Neo4j le norme (leggi, decreti, ecc.), i relativi articoli,
i commi e i collegamenti di citazione, generando una web application interattiva
(out/grafo.html) con Vis.js per esplorare:
  - Tutte le Norme caricate e i relativi Articoli
  - Clustering dinamico che si espande su zoom o doppio-click
  - Ottimizzazione fisica (60 FPS, zero lag)

Uso:
    python src/06_visualizza.py
"""

import html
import json
import os
import sys
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comune import norma_label

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"


def estrai_dati_grafo():
    """Estrae tutte le entita' e relazioni necessarie per la visualizzazione."""
    load_dotenv(ROOT / ".env")
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    with driver.session(database=db) as s:
        # 1. Norme
        norme = [r.data() for r in s.run("""
            MATCH (n:Norma)
            RETURN n.id AS id, n.tipo AS tipo, n.numero AS numero, n.anno AS anno,
                   coalesce(n.titolo, n.tipo + ' n.' + toString(n.numero) + '/' + toString(n.anno)) AS titolo,
                   toString(n.dataEntrataVigore) AS dataEntrataVigore,
                   toString(n.dataPubblicazione) AS dataPubblicazione,
                   toString(n.data) AS data,
                   n.caricata AS caricata,
                   n.urlScheda AS urlScheda,
                   n.urlDocumento AS urlDocumento
        """)]

        # 2. Articoli
        articoli = [r.data() for r in s.run("""
            MATCH (n:Norma)-[:HA_ARTICOLO]->(a:Articolo)
            RETURN a.id AS id, a.numero AS numero, a.rubrica AS rubrica,
                   n.id AS normaId, a.titolo AS titolo, a.capo AS capo,
                   a.titoloRubrica AS titoloRubrica, a.capoRubrica AS capoRubrica,
                   a.ordine AS ordine, a.testo AS testo
            ORDER BY n.id, a.ordine
        """)]

        # 3. Commi
        commi = [r.data() for r in s.run("""
            MATCH (a:Articolo)-[:HA_COMMA]->(c:Comma)
            RETURN c.id AS id, c.numero AS numero, c.testo AS testo,
                   a.id AS articoloId, c.numerazioneAnomala AS numerazioneAnomala,
                   c.commaImplicito AS commaImplicito
        """)]

        # 4. Citazioni
        citazioni = [r.data() for r in s.run("""
            MATCH (cm:Comma)-[r:CITA]->(target:Norma)
            MATCH (art:Articolo)-[:HA_COMMA]->(cm)
            RETURN cm.id AS daComma, art.id AS daArticolo, target.id AS versoNorma,
                   r.testoCitazione AS testo, r.articoloCitato AS articoloCitato
            UNION ALL
            MATCH (n:Norma)-[r:CITA]->(target:Norma)
            RETURN n.id AS daComma, n.id AS daArticolo, target.id AS versoNorma,
                   r.testoCitazione AS testo, r.articoloCitato AS articoloCitato
        """)]

    driver.close()
    return {
        "norme": norme,
        "articoli": articoli,
        "commi": commi,
        "citazioni": citazioni,
    }


TEMPLATE_HTML = r"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <title>graphResponsa — Knowledge Graph Normativa</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/vis-network.min.js"></script>
  <style>
    :root {
      --bg: #0d1117;
      --panel-bg: #161b22;
      --border: #30363d;
      --text: #e6edf3;
      --text-muted: #8b949e;
      --accent: #58a6ff;
      --accent-hover: #79b8ff;
      --color-legge: #1f6feb;
      --color-decreto-del: #8957e5;
      --color-decreto: #0969da;
      --color-cost: #da3633;
      --color-articolo: #238636;
      --color-comma: #bf8700;
      --color-stub: #6e7781;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font: 13.5px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    header {
      padding: 9px 16px;
      background: var(--panel-bg);
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      z-index: 10;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14.5px;
      font-weight: 600;
      color: var(--text);
    }
    .brand span {
      background: #238636;
      color: #fff;
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 12px;
      font-weight: 500;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    select, input, button {
      background: #21262d;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 5px 9px;
      border-radius: 6px;
      font-size: 12.5px;
      outline: none;
      transition: border-color 0.15s, background 0.15s;
    }
    select:focus, input:focus {
      border-color: var(--accent);
    }
    button {
      cursor: pointer;
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 4px;
    }
    button.btn-action {
      background: #21262d;
      border-color: var(--border);
    }
    button.btn-action:hover {
      background: #30363d;
      border-color: var(--accent);
    }
    .toggle-group {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 12px;
      color: var(--text-muted);
      background: #0d1117;
      padding: 4px 8px;
      border-radius: 6px;
      border: 1px solid var(--border);
    }
    .toggle-group label {
      display: flex;
      align-items: center;
      gap: 4px;
      cursor: pointer;
      user-select: none;
    }
    .toggle-group input[type="checkbox"] {
      cursor: pointer;
      accent-color: var(--accent);
      margin: 0;
    }
    #main-container {
      flex: 1;
      display: flex;
      position: relative;
      min-height: 0;
    }
    #rete {
      flex: 1;
      height: 100%;
      background: var(--bg);
    }
    #sidebar {
      width: 380px;
      background: var(--panel-bg);
      border-left: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      height: 100%;
      overflow-y: auto;
      transition: transform 0.2s ease;
      z-index: 5;
    }
    #sidebar.hidden {
      display: none;
    }
    .sidebar-header {
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
    }
    .sidebar-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--text);
      margin: 0;
    }
    .sidebar-close {
      background: none;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 15px;
      padding: 0 4px;
    }
    .sidebar-close:hover { color: var(--text); }
    .sidebar-body {
      padding: 14px;
      font-size: 12.5px;
      flex: 1;
    }
    .badge {
      display: inline-block;
      padding: 2px 7px;
      border-radius: 4px;
      font-size: 10.5px;
      font-weight: 600;
      margin-bottom: 6px;
      text-transform: uppercase;
    }
    .badge-legge { background: #1f6feb22; color: #58a6ff; border: 1px solid #1f6feb; }
    .badge-dd { background: #8957e522; color: #bc8cff; border: 1px solid #8957e5; }
    .badge-articolo { background: #23863622; color: #3fb950; border: 1px solid #238636; }
    .badge-comma { background: #bf870022; color: #d29922; border: 1px solid #bf8700; }
    .badge-stub { background: #6e778122; color: #8b949e; border: 1px solid #6e7781; }
    .meta-row {
      margin-bottom: 7px;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: var(--text-muted);
    }
    .meta-val {
      color: var(--text);
      font-weight: 500;
      text-align: right;
    }
    .section-title {
      font-size: 11.5px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin: 14px 0 6px 0;
      border-bottom: 1px solid var(--border);
      padding-bottom: 3px;
    }
    .comma-item {
      background: #0d1117;
      border: 1px solid var(--border);
      border-radius: 5px;
      padding: 8px;
      margin-bottom: 6px;
    }
    .comma-num {
      font-weight: 600;
      color: #d29922;
      margin-bottom: 3px;
      font-size: 11.5px;
    }
    .cit-list {
      list-style: none;
      padding: 0;
      margin: 0;
    }
    .cit-item {
      background: #0d1117;
      border: 1px solid var(--border);
      border-radius: 5px;
      padding: 7px;
      margin-bottom: 5px;
      font-size: 11.5px;
      cursor: pointer;
    }
    .cit-item:hover {
      border-color: var(--accent);
    }
    #footer-bar {
      padding: 5px 16px;
      background: var(--panel-bg);
      border-top: 1px solid var(--border);
      font-size: 11.5px;
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .legend {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .legend-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      display: inline-block;
    }
    #zoom-indicator {
      background: #21262d;
      padding: 2px 7px;
      border-radius: 4px;
      color: var(--accent);
      font-weight: 500;
    }
  </style>
</head>
<body>

<header>
  <div class="brand">
    🏛️ graphResponsa <span>LOD & Cluster</span>
  </div>

  <div class="controls">
    <!-- Selettore modalita' di vista -->
    <select id="sel-vista" onchange="aggiornaGrafo()">
      <option value="cluster_auto">⚡ Dinamico (Clustering su Zoom)</option>
      <option value="norme_articoli">📑 Tutte le Norme & Articoli Espansi</option>
      <option value="focus_norma">🎯 Singola Norma (Albero Gerarchico)</option>
      <option value="citazioni">🕸️ Rete Globale Citazioni</option>
    </select>

    <!-- Dropdown Norma -->
    <select id="sel-norma" onchange="cambiaNorma()" style="max-width: 250px;">
      <option value="">Tutte le norme caricate (29)</option>
    </select>

    <!-- Pulsanti di cluster rapido -->
    <button class="btn-action" onclick="comprimiTuttiCluster()" title="Raggruppa tutti gli articoli dentro le rispettive norme">📦 Raggruppa</button>
    <button class="btn-action" onclick="espandiTuttiCluster()" title="Espandi tutti i cluster di articoli">📂 Espandi</button>

    <!-- Toggles e Spaziatura -->
    <div class="toggle-group">
      <label title="Regola la distanza tra i nodi">↔️ Spaziatura: <input type="range" id="rng-spaziatura" min="150" max="650" value="280" oninput="cambiaSpaziatura(this.value)" style="width: 85px; cursor: pointer;"></label>
      <label title="Espandi/comprimi automaticamente gli articoli in base allo zoom"><input type="checkbox" id="chk-auto-zoom" checked> Auto-Zoom</label>
      <label title="Mostra anche i nodi Comma"><input type="checkbox" id="chk-commi" onchange="aggiornaGrafo()"> Commi</label>
      <label title="Mostra frecce di citazione"><input type="checkbox" id="chk-citazioni" checked onchange="aggiornaGrafo()"> Citazioni</label>
      <label title="Mostra norme citate non ancora in archivio"><input type="checkbox" id="chk-stub" onchange="aggiornaGrafo()"> Stub</label>
    </div>

    <!-- Ricerca -->
    <input type="text" id="txt-cerca" placeholder="🔍 Cerca articolo o legge..." oninput="cercaNodo(this.value)" style="width: 190px;">
  </div>
</header>

<div id="main-container">
  <div id="rete"></div>

  <!-- Sidebar dettagli -->
  <div id="sidebar" class="hidden">
    <div class="sidebar-header">
      <div>
        <span id="side-badge" class="badge"></span>
        <h3 id="side-title" class="sidebar-title"></h3>
      </div>
      <button class="sidebar-close" onclick="chiudiSidebar()">✕</button>
    </div>
    <div class="sidebar-body" id="side-body"></div>
  </div>
</div>

<div id="footer-bar">
  <div class="legend">
    <span class="legend-item"><span class="legend-dot" style="background:var(--color-legge)"></span> Legge</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--color-decreto-del)"></span> Decreto Delegato</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--color-decreto)"></span> Decreto</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--color-articolo)"></span> Articolo</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--color-comma)"></span> Comma</span>
    <span class="legend-item"><span class="legend-dot" style="background:var(--color-stub)"></span> Stub</span>
  </div>
  <div style="display:flex; align-items:center; gap:12px;">
    <span id="zoom-indicator">Zoom: 100%</span>
    <span id="stats-info">Inizializzazione...</span>
  </div>
</div>

<script>
const DATA = __GRAFO_DATA__;

let network = null;
let nodiDataSet = new vis.DataSet([]);
let latiDataSet = new vis.DataSet([]);
let clusterAperti = new Set();
let zoomTimeout = null;

// Popola il menu a tendina delle norme
function popolaMenuNorme() {
  const sel = document.getElementById("sel-norma");
  sel.innerHTML = '<option value="">Tutte le norme caricate (' + DATA.norme.filter(n => n.caricata).length + ')</option>';
  
  const caricate = DATA.norme.filter(n => n.caricata).sort((a, b) => {
    const artA = DATA.articoli.filter(art => art.normaId === a.id).length;
    const artB = DATA.articoli.filter(art => art.normaId === b.id).length;
    return artB - artA;
  });

  caricate.forEach(n => {
    const nArt = DATA.articoli.filter(a => a.normaId === n.id).length;
    const opt = document.createElement("option");
    opt.value = n.id;
    opt.textContent = `${n.id} - ${n.tipo} n.${n.numero}/${n.anno} (${nArt} art.)`;
    sel.appendChild(opt);
  });
}

function cambiaNorma() {
  const normaId = document.getElementById("sel-norma").value;
  if (normaId) {
    document.getElementById("sel-vista").value = "focus_norma";
  }
  aggiornaGrafo();
}

function getColoreNorma(tipo, caricata) {
  if (!caricata) return { background: '#21262d', border: '#6e7781', text: '#8b949e' };
  const t = (tipo || '').toLowerCase();
  if (t.includes('costituzionale') || t.includes('qualificata')) {
    return { background: '#da3633', border: '#f85149', text: '#ffffff' };
  }
  if (t.includes('delegato')) {
    return { background: '#8957e5', border: '#a371f7', text: '#ffffff' };
  }
  if (t.includes('decreto')) {
    return { background: '#0969da', border: '#388bfd', text: '#ffffff' };
  }
  return { background: '#1f6feb', border: '#58a6ff', text: '#ffffff' };
}

function costruisciGrafo() {
  const vista = document.getElementById("sel-vista").value;
  const normaSelezionata = document.getElementById("sel-norma").value;
  const mostraCommi = document.getElementById("chk-commi").checked;
  const mostraCitazioni = document.getElementById("chk-citazioni").checked;
  const mostraStub = document.getElementById("chk-stub").checked;

  const nodiMap = new Map();
  const latiMap = new Map();

  function aggiungiLato(from, to, opt = {}) {
    const key = `${from}->${to}:${opt.title || ''}`;
    if (!latiMap.has(key)) {
      latiMap.set(key, { from, to, ...opt });
    }
  }

  // 1. Filtra Norme
  let normeFiltrate = DATA.norme.filter(n => {
    if (normaSelezionata && n.id !== normaSelezionata && vista === "focus_norma") return false;
    if (!mostraStub && !n.caricata) return false;
    return true;
  });

  const idNormePresenti = new Set(normeFiltrate.map(n => n.id));

  // 2. Aggiungi nodi Norma
  normeFiltrate.forEach(n => {
    const col = getColoreNorma(n.tipo, n.caricata);
    const nArt = DATA.articoli.filter(a => a.normaId === n.id).length;
    nodiMap.set(n.id, {
      id: n.id,
      label: `${n.id}\n${n.tipo} n.${n.numero}/${n.anno}`,
      title: `${n.titolo}\n(${nArt} articoli)`,
      shape: 'box',
      margin: 9,
      color: { background: col.background, border: col.border },
      font: { color: col.text, size: 12.5, bold: true },
      borderWidth: n.caricata ? 2 : 1,
      shapeProperties: { borderDashes: !n.caricata },
      level: 0,
      tipoNodo: 'norma',
      normaId: n.id,
      raw: n
    });
  });

  // 3. Aggiungi Articoli
  if (vista !== "citazioni") {
    DATA.articoli.forEach(a => {
      if (!idNormePresenti.has(a.normaId)) return;
      
      const rubricaText = a.rubrica ? ` - ${a.rubrica.length > 30 ? a.rubrica.substring(0, 30) + '...' : a.rubrica}` : '';
      const collocazione = [a.titolo, a.capo].filter(Boolean).join(' / ');

      nodiMap.set(a.id, {
        id: a.id,
        label: `Art.${a.numero}${rubricaText ? '\n' + a.rubrica.substring(0, 22) + '...' : ''}`,
        title: `Art.${a.numero} (${a.normaId})\n${a.rubrica || 'Senza rubrica'}\n[${collocazione}]`,
        shape: 'ellipse',
        color: { background: '#238636', border: '#2ea043' },
        font: { color: '#ffffff', size: 10.5 },
        borderWidth: 1.2,
        level: 1,
        tipoNodo: 'articolo',
        normaId: a.normaId,
        raw: a
      });

      // Arco Norma -> Articolo
      aggiungiLato(a.normaId, a.id, {
        color: { color: '#30363d', highlight: '#58a6ff' },
        width: 1.2,
        length: 240,
        arrows: { to: { enabled: true, scaleFactor: 0.35 } },
        title: 'HA_ARTICOLO'
      });

      // 4. Aggiungi Commi se richiesto
      if (mostraCommi) {
        const commiArt = DATA.commi.filter(c => c.articoloId === a.id);
        commiArt.forEach(c => {
          nodiMap.set(c.id, {
            id: c.id,
            label: `c.${c.numero}`,
            title: `Art.${a.numero} comma ${c.numero}\n${c.testo}`,
            shape: 'dot',
            size: 7,
            color: { background: '#bf8700', border: '#d29922' },
            font: { color: '#e6edf3', size: 9 },
            level: 2,
            tipoNodo: 'comma',
            normaId: a.normaId,
            raw: c
          });

          aggiungiLato(a.id, c.id, {
            color: { color: '#21262d', highlight: '#d29922' },
            width: 1,
            length: 130,
            arrows: { to: { enabled: true, scaleFactor: 0.3 } },
            title: 'HA_COMMA'
          });
        });
      }
    });
  }

  // 5. Aggiungi Citazioni
  if (mostraCitazioni) {
    DATA.citazioni.forEach(cit => {
      const sorgente = nodiMap.has(cit.daArticolo) ? cit.daArticolo : 
                       (nodiMap.has(cit.daComma) ? cit.daComma : null);

      if (vista === "citazioni") {
        const srcNorma = DATA.articoli.find(a => a.id === cit.daArticolo)?.normaId || cit.daArticolo;
        if (nodiMap.has(srcNorma) && (nodiMap.has(cit.versoNorma) || mostraStub)) {
          if (!nodiMap.has(cit.versoNorma)) {
            const stubNorm = DATA.norme.find(n => n.id === cit.versoNorma);
            if (stubNorm) {
              const col = getColoreNorma(stubNorm.tipo, false);
              nodiMap.set(stubNorm.id, {
                id: stubNorm.id,
                label: stubNorm.id,
                title: stubNorm.titolo,
                shape: 'box',
                color: { background: col.background, border: col.border },
                font: { color: col.text, size: 11 },
                shapeProperties: { borderDashes: true },
                tipoNodo: 'norma',
                raw: stubNorm
              });
            }
          }
          if (nodiMap.has(cit.versoNorma)) {
            aggiungiLato(srcNorma, cit.versoNorma, {
              color: { color: '#8b949e44', highlight: '#f0883e' },
              dashes: true,
              length: 320,
              arrows: { to: { enabled: true, scaleFactor: 0.4 } },
              title: `Cita: ${cit.testo || cit.versoNorma}`
            });
          }
        }
      } else if (sorgente) {
        if (!nodiMap.has(cit.versoNorma) && mostraStub) {
          const stubNorm = DATA.norme.find(n => n.id === cit.versoNorma);
          if (stubNorm) {
            const col = getColoreNorma(stubNorm.tipo, false);
            nodiMap.set(stubNorm.id, {
              id: stubNorm.id,
              label: `${stubNorm.id}\n${stubNorm.tipo || ''}`,
              title: `${stubNorm.titolo} (non caricata)`,
              shape: 'box',
              color: { background: col.background, border: col.border },
              font: { color: col.text, size: 11 },
              shapeProperties: { borderDashes: true },
              tipoNodo: 'norma',
              raw: stubNorm
            });
          }
        }
        if (nodiMap.has(cit.versoNorma)) {
          aggiungiLato(sorgente, cit.versoNorma, {
            color: { color: '#e3b34166', highlight: '#f0883e' },
            dashes: [4, 4],
            width: 1.1,
            length: 280,
            arrows: { to: { enabled: true, scaleFactor: 0.4 } },
            title: `Cita: ${cit.testo || cit.versoNorma}`
          });
        }
      }
    });
  }

  const nodiArray = Array.from(nodiMap.values());
  const latiArray = Array.from(latiMap.values());

  aggiornaStats(nodiArray, latiArray);

  return { nodi: nodiArray, lati: latiArray, isTree: vista === "focus_norma" };
}

function aggiornaStats(nodi, lati) {
  const nNorme = nodi.filter(n => n.tipoNodo === 'norma').length;
  const nArt = nodi.filter(n => n.tipoNodo === 'articolo').length;
  const nCom = nodi.filter(n => n.tipoNodo === 'comma').length;
  document.getElementById("stats-info").textContent = 
    `Nodi: ${nNorme} Norme, ${nArt} Articoli, ${nCom} Commi | ${lati.length} Relazioni`;
}

function applicaClustering() {
  if (!network) return;
  const vista = document.getElementById("sel-vista").value;
  if (vista === "focus_norma" || vista === "citazioni" || vista === "norme_articoli") {
    return; // Nelle viste esplicite mantieni tutti gli articoli visibili
  }

  // Raggruppa gli articoli per ciascuna norma
  DATA.norme.filter(n => n.caricata).forEach(norma => {
    const clusterId = "cluster_" + norma.id;
    if (clusterAperti.has(clusterId)) return;

    const clusterOptions = {
      joinCondition: function(nodeOptions) {
        return nodeOptions.tipoNodo === 'articolo' && nodeOptions.normaId === norma.id;
      },
      processProperties: function(clusterOptions, childNodes) {
        const col = getColoreNorma(norma.tipo, norma.caricata);
        clusterOptions.label = `${norma.id}\n📁 ${childNodes.length} articoli`;
        clusterOptions.shape = 'box';
        clusterOptions.margin = 10;
        clusterOptions.color = { background: col.background, border: col.border };
        clusterOptions.font = { color: col.text, size: 12, bold: true };
        clusterOptions.borderWidth = 2;
        clusterOptions.shadow = { enabled: true, color: 'rgba(0,0,0,0.5)', size: 8 };
        clusterOptions.tipoNodo = 'cluster_articoli';
        clusterOptions.normaId = norma.id;
        clusterOptions.raw = norma;
        return clusterOptions;
      },
      clusterNodeProperties: {
        id: clusterId,
        allowSingleNodeCluster: false
      }
    };
    network.cluster(clusterOptions);
  });
}

function comprimiTuttiCluster() {
  clusterAperti.clear();
  document.getElementById("sel-vista").value = "cluster_auto";
  aggiornaGrafo();
}

function espandiTuttiCluster() {
  document.getElementById("sel-vista").value = "norme_articoli";
  aggiornaGrafo();
}

function renderNetwork(nodi, lati, isTree) {
  const container = document.getElementById('rete');
  nodiDataSet = new vis.DataSet(nodi);
  latiDataSet = new vis.DataSet(lati);

  const vista = document.getElementById("sel-vista").value;

  const options = {
    nodes: {
      font: { face: 'system-ui, -apple-system, sans-serif' }
    },
    edges: {
      smooth: { type: isTree ? 'cubicBezier' : 'continuous', forceDirection: isTree ? 'vertical' : 'none' }
    },
    layout: isTree ? {
      hierarchical: {
        enabled: true,
        direction: 'UD',
        sortMethod: 'directed',
        levelSeparation: 220,
        nodeSpacing: 220,
        treeSpacing: 300
      }
    } : {
      improvedLayout: false
    },
    physics: isTree ? { enabled: false } : {
      enabled: true,
      stabilization: {
        enabled: true,
        iterations: 140,
        updateInterval: 25
      },
      barnesHut: {
        gravitationalConstant: -28000,
        centralGravity: 0.04,
        springLength: 260,
        springConstant: 0.015,
        damping: 0.5,
        avoidOverlap: 1
      },
      minVelocity: 0.75
    },
    interaction: {
      hover: true,
      tooltipDelay: 80,
      hideEdgesOnDrag: true, // 60 FPS durante il pan
      hideEdgesOnZoom: true, // 60 FPS durante lo zoom
      navigationButtons: true,
      keyboard: true
    }
  };

  if (network) {
    network.destroy();
  }

  network = new vis.Network(container, { nodes: nodiDataSet, edges: latiDataSet }, options);

  // OTTIMIZZAZIONE FISICA: Disabilita la simulazione continua non appena il grafo si stabilizza
  network.on("stabilizationIterationsDone", function () {
    if (!isTree) {
      network.setOptions({ physics: { enabled: false } });
    }
  });

  // Applica il clustering iniziale se in modalita' dinamica
  if (vista === "cluster_auto") {
    setTimeout(applicaClustering, 100);
  }

  // GESTIONE ZOOM DINAMICO (Level of Detail LOD)
  network.on("zoom", function (params) {
    const scale = params.scale;
    document.getElementById("zoom-indicator").textContent = `Zoom: ${Math.round(scale * 100)}%`;

    const autoZoom = document.getElementById("chk-auto-zoom").checked;
    if (!autoZoom || vista !== "cluster_auto") return;

    clearTimeout(zoomTimeout);
    zoomTimeout = setTimeout(() => {
      if (scale >= 0.75) {
        // Zoom ravvicinato: apri cluster nell'area di visualizzazione
        const center = network.getViewPosition();
        DATA.norme.filter(n => n.caricata).forEach(n => {
          const cId = "cluster_" + n.id;
          if (network.isCluster(cId)) {
            network.openCluster(cId);
            clusterAperti.add(cId);
          }
        });
      } else if (scale <= 0.42) {
        // Zoom lontano: raggruppa
        clusterAperti.clear();
        applicaClustering();
      }
    }, 150);
  });

  // DOPPIO CLICK O CLICK PER ESPANDERE CLUSTER O VEDERE DETTAGLI
  network.on("doubleClick", function (params) {
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      if (network.isCluster(nodeId)) {
        network.openCluster(nodeId);
        clusterAperti.add(nodeId);
      } else {
        const node = nodiDataSet.get(nodeId);
        if (node && node.tipoNodo === "norma") {
          document.getElementById("sel-norma").value = nodeId;
          document.getElementById("sel-vista").value = "focus_norma";
          aggiornaGrafo();
        }
      }
    }
  });

  network.on("click", function (params) {
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      if (network.isCluster(nodeId)) {
        // Mostra dettagli della norma del cluster
        const cProps = network.clustering.findNode(nodeId);
        mostraDettagliNodo(nodeId.replace("cluster_", ""));
      } else {
        mostraDettagliNodo(nodeId);
      }
    }
  });
}

function aggiornaGrafo() {
  const dati = costruisciGrafo();
  renderNetwork(dati.nodi, dati.lati, dati.isTree);
}

function mostraDettagliNodo(nodeId) {
  let node = nodiDataSet.get(nodeId);
  if (!node) {
    const n = DATA.norme.find(x => x.id === nodeId);
    if (n) node = { tipoNodo: 'norma', raw: n, id: n.id };
    const a = DATA.articoli.find(x => x.id === nodeId);
    if (a) node = { tipoNodo: 'articolo', raw: a, id: a.id };
  }
  if (!node) return;

  const sidebar = document.getElementById("sidebar");
  const badge = document.getElementById("side-badge");
  const title = document.getElementById("side-title");
  const body = document.getElementById("side-body");

  sidebar.classList.remove("hidden");

  if (node.tipoNodo === "norma" || node.tipoNodo === "cluster_articoli") {
    const n = node.raw;
    badge.className = "badge " + (n.caricata ? "badge-legge" : "badge-stub");
    badge.textContent = n.tipo || "NORMA";
    title.textContent = n.id;

    const articoliNorma = DATA.articoli.filter(a => a.normaId === n.id);
    const citFatte = DATA.citazioni.filter(c => c.daNorma === n.id || (DATA.articoli.find(a => a.id === c.daArticolo)?.normaId === n.id));
    const citRicevute = DATA.citazioni.filter(c => c.versoNorma === n.id);

    body.innerHTML = `
      <div style="font-size:13px; font-weight:600; margin-bottom:10px; color:var(--text);">${htmlEscape(n.titolo)}</div>
      
      <div class="meta-row"><span>Numero / Anno:</span><span class="meta-val">n.${n.numero} del ${n.anno}</span></div>
      <div class="meta-row"><span>Data Atto:</span><span class="meta-val">${n.data || '-'}</span></div>
      <div class="meta-row"><span>Entrata in Vigore:</span><span class="meta-val">${n.dataEntrataVigore || '-'}</span></div>
      <div class="meta-row"><span>Stato Archivio:</span><span class="meta-val">${n.caricata ? '✅ Testo completo' : '⚠️ Stub citato'}</span></div>
      <div class="meta-row"><span>Numero Articoli:</span><span class="meta-val">${articoliNorma.length}</span></div>

      <div style="margin: 12px 0 6px 0;">
        <button style="width:100%; justify-content:center;" onclick="focusSingolaNorma('${n.id}')">
          🎯 Esplora Albero Gerarchico (${n.id})
        </button>
      </div>

      <div class="section-title">Articoli (${articoliNorma.length})</div>
      <div style="max-height: 180px; overflow-y: auto; display: flex; flex-wrap: wrap; gap: 5px;">
        ${articoliNorma.map(a => `
          <button style="padding:3px 7px; font-size:11px; background:#21262d; border-color:#30363d;" onclick="selezionaNodo('${a.id}')">
            Art.${a.numero}
          </button>
        `).join('')}
      </div>

      ${citFatte.length > 0 ? `
        <div class="section-title">Norme Citate (${citFatte.length})</div>
        <ul class="cit-list">
          ${citFatte.slice(0, 6).map(c => `
            <li class="cit-item" onclick="selezionaNodo('${c.versoNorma}')">
              <b>${c.versoNorma}</b>: ${htmlEscape(c.testo || 'Citazione')}
            </li>
          `).join('')}
        </ul>
      ` : ''}

      ${citRicevute.length > 0 ? `
        <div class="section-title">Citata Da (${citRicevute.length} volte)</div>
        <div style="font-size:11.5px; color:var(--text-muted);">Citata da altre leggi o commi nel corpus.</div>
      ` : ''}
    `;
  } else if (node.tipoNodo === "articolo") {
    const a = node.raw;
    badge.className = "badge badge-articolo";
    badge.textContent = `ARTICOLO ${a.numero}`;
    title.textContent = `${a.normaId} / Art. ${a.numero}`;

    const commiArt = DATA.commi.filter(c => c.articoloId === a.id);
    const citazioniArt = DATA.citazioni.filter(c => c.daArticolo === a.id);

    body.innerHTML = `
      <div style="font-size:13px; font-weight:600; margin-bottom:8px; color:#3fb950;">
        ${a.rubrica ? `(${htmlEscape(a.rubrica)})` : '<em>Senza rubrica</em>'}
      </div>
      
      <div class="meta-row">
        <span>Norma di appartenenza:</span>
        <span class="meta-val"><a href="javascript:void(0)" onclick="selezionaNodo('${a.normaId}')" style="color:var(--accent); text-decoration:none;">${a.normaId}</a></span>
      </div>
      ${a.titolo ? `<div class="meta-row"><span>Titolo:</span><span class="meta-val">${htmlEscape(a.titolo)} ${a.titoloRubrica ? '- ' + htmlEscape(a.titoloRubrica) : ''}</span></div>` : ''}
      ${a.capo ? `<div class="meta-row"><span>Capo:</span><span class="meta-val">${htmlEscape(a.capo)} ${a.capoRubrica ? '- ' + htmlEscape(a.capoRubrica) : ''}</span></div>` : ''}

      <div class="section-title">Commi (${commiArt.length})</div>
      <div style="max-height: 250px; overflow-y: auto;">
        ${commiArt.length > 0 ? commiArt.map(c => `
          <div class="comma-item">
            <div class="comma-num">Comma ${c.numero} ${c.numerazioneAnomala ? '<span style="color:#f85149; font-size:9.5px;">[Numerazione anomala]</span>' : ''}</div>
            <div style="color:var(--text); font-size:12px;">${htmlEscape(c.testo)}</div>
          </div>
        `).join('') : `<div style="color:var(--text-muted); font-size:11.5px;">Testo articolo: ${htmlEscape(a.testo || '-')}</div>`}
      </div>

      ${citazioniArt.length > 0 ? `
        <div class="section-title">Citazioni Effettuate (${citazioniArt.length})</div>
        <ul class="cit-list">
          ${citazioniArt.map(c => `
            <li class="cit-item" onclick="selezionaNodo('${c.versoNorma}')">
              <b>${c.versoNorma}</b>: ${htmlEscape(c.testo || 'Citazione')}
            </li>
          `).join('')}
        </ul>
      ` : ''}
    `;
  } else if (node.tipoNodo === "comma") {
    const c = node.raw;
    badge.className = "badge badge-comma";
    badge.textContent = `COMMA ${c.numero}`;
    title.textContent = `${c.articoloId} c.${c.numero}`;

    body.innerHTML = `
      <div class="meta-row">
        <span>Articolo:</span>
        <span class="meta-val"><a href="javascript:void(0)" onclick="selezionaNodo('${c.articoloId}')" style="color:var(--accent); text-decoration:none;">${c.articoloId}</a></span>
      </div>
      <div class="section-title">Testo del Comma</div>
      <div class="comma-item" style="font-size:12.5px; color:var(--text);">
        ${htmlEscape(c.testo)}
      </div>
    `;
  }
}

function focusSingolaNorma(normaId) {
  document.getElementById("sel-norma").value = normaId;
  document.getElementById("sel-vista").value = "focus_norma";
  aggiornaGrafo();
}

function selezionaNodo(nodeId) {
  // Se il nodo fa parte di un cluster chiuso, apri il cluster prima di selezionarlo
  const articolo = DATA.articoli.find(a => a.id === nodeId);
  if (articolo) {
    const cId = "cluster_" + articolo.normaId;
    if (network && network.isCluster(cId)) {
      network.openCluster(cId);
      clusterAperti.add(cId);
    }
  }

  if (nodiDataSet.get(nodeId)) {
    network.selectNodes([nodeId]);
    network.focus(nodeId, { scale: 1.2, animation: true });
    mostraDettagliNodo(nodeId);
  } else {
    const norma = DATA.norme.find(n => n.id === nodeId);
    if (norma) {
      document.getElementById("sel-norma").value = nodeId;
      document.getElementById("sel-vista").value = "focus_norma";
      aggiornaGrafo();
      setTimeout(() => selezionaNodo(nodeId), 300);
    }
  }
}

function cercaNodo(query) {
  if (!query || query.trim().length < 2) return;
  const q = query.trim().toLowerCase();
  
  const trovato = DATA.articoli.find(a => 
    a.id.toLowerCase().includes(q) || 
    (a.rubrica && a.rubrica.toLowerCase().includes(q)) ||
    (a.testo && a.testo.toLowerCase().includes(q))
  ) || DATA.norme.find(n => 
    n.id.toLowerCase().includes(q) || 
    (n.titolo && n.titolo.toLowerCase().includes(q))
  );

  if (trovato) {
    selezionaNodo(trovato.id);
  }
}

function chiudiSidebar() {
  document.getElementById("sidebar").classList.add("hidden");
  if (network) network.unselectAll();
}

function htmlEscape(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function cambiaSpaziatura(val) {
  const v = parseInt(val, 10);
  if (!network) return;
  const isTree = document.getElementById("sel-vista").value === "focus_norma";
  if (isTree) {
    network.setOptions({
      layout: {
        hierarchical: {
          levelSeparation: Math.round(v * 0.8),
          nodeSpacing: v,
          treeSpacing: Math.round(v * 1.3)
        }
      }
    });
  } else {
    network.setOptions({
      physics: {
        enabled: true,
        barnesHut: {
          springLength: v,
          gravitationalConstant: -v * 110,
          centralGravity: 0.04,
          avoidOverlap: 1
        }
      }
    });
    // Blocca la fisica dopo aver allontanato i nodi per preservare 60 FPS
    setTimeout(() => {
      network.setOptions({ physics: { enabled: false } });
    }, 1200);
  }
}

// Inizializzazione
popolaMenuNorme();
aggiornaGrafo();
</script>
</body>
</html>
"""


def main():
    print("Estrazione dati da Neo4j Aura...")
    dati_grafo = estrai_dati_grafo()
    print(f"  Norme: {len(dati_grafo['norme'])}, Articoli: {len(dati_grafo['articoli'])}, "
          f"Commi: {len(dati_grafo['commi'])}, Citazioni: {len(dati_grafo['citazioni'])}")

    OUT.mkdir(parents=True, exist_ok=True)
    json_data = json.dumps(dati_grafo, ensure_ascii=False)
    html_content = TEMPLATE_HTML.replace("__GRAFO_DATA__", json_data)

    output_path = OUT / "grafo.html"
    output_path.write_text(html_content, encoding="utf-8")
    print(f"\nGrafo ottimizzato generato con successo: {output_path}")


if __name__ == "__main__":
    main()

