import React, { useEffect, useState } from 'react';
import type { ThoughtStep } from '../types';
import { componi, ElencoPassi, type Passo } from './ThinkingTrail';
import { conArticolo } from '../norme';

/**
 * Cosa sta facendo l'agente, detto in una frase che cambia col lavoro.
 *
 * Il server manda in diretta ogni chiamata a uno strumento e ogni risultato,
 * ma il testo della risposta arriva intero alla fine. Fra un evento e l'altro
 * quindi c'e' silenzio, e senza una frase lo scheletro di un paragrafo resta
 * fermo per venti secondi e si legge come un blocco.
 *
 * Le frasi sui passaggi sono certe: dicono la chiamata che e' partita. Le due
 * sui silenzi - prima del primo strumento e dopo l'ultimo risultato - sono
 * una stima fatta sul tempo trascorso. Dopo un risultato il modello o chiama
 * un altro strumento, e lo fa in pochi secondi, o scrive la risposta, che ne
 * richiede di piu': passata la soglia, e' la seconda.
 */

/** Oltre questi secondi di silenzio dopo un risultato, il modello sta scrivendo. */
const SOGLIA_SCRITTURA = 6;
/** Oltre questi, si avverte che una risposta ampia richiede tempo. */
const SOGLIA_PAZIENZA = 28;

function inCorso(p: Passo): string {
  const a = p.args;
  switch (p.nome) {
    case 'cerca_testo':
      return a.query ? `Sto cercando «${a.query}» nei testi di legge` : 'Sto cercando nei testi di legge';
    case 'leggi_articolo': {
      if (!conArticolo(a.norma_id, 'di')) return 'Sto leggendo l’articolo per intero';
      return a.numero
        ? `Sto leggendo l’articolo ${a.numero} ${conArticolo(a.norma_id, 'di')}`
        : `Sto leggendo ${conArticolo(a.norma_id, 'nessuna')}`;
    }
    case 'struttura_norma':
      return `Sto aprendo l’indice ${conArticolo(a.norma_id, 'di') || 'della norma'}`;
    case 'trova_norma':
      if (a.numero && a.anno) return `Sto individuando la norma n. ${a.numero}/${a.anno}`;
      return a.testo ? `Sto individuando la norma «${a.testo}»` : 'Sto individuando la norma';
    case 'citazioni_da':
      return `Sto seguendo i rinvii ${conArticolo(a.norma_id, 'di') || 'della norma'}`;
    case 'chi_cita':
      return `Sto cercando chi rinvia ${conArticolo(a.norma_id, 'a') || 'alla norma'}`;
    case 'elenco_norme':
      return 'Sto scorrendo l’elenco delle norme';
    default:
      return 'Sto consultando l’archivio';
  }
}

function frase(thoughts: ThoughtStep[], passi: Passo[], silenzio: number, trascorsi: number): string {
  const aperti = passi.filter((p) => !p.concluso);
  if (aperti.length) {
    const prima = inCorso(aperti[0]);
    if (aperti.length === 1) return prima;
    return aperti.length === 2
      ? `${prima} e un’altra ricerca`
      : `${prima} e altre ${aperti.length - 1} ricerche`;
  }

  if (passi.length === 0) {
    if (trascorsi < 2.5) return 'Sto leggendo la domanda';
    if (trascorsi < 12) return 'Sto scegliendo dove cercare nell’archivio';
    return 'Sto preparando la risposta';
  }

  if (silenzio < SOGLIA_SCRITTURA) {
    // L'ultimo giro di risultati: quelli arrivati dopo l'ultima chiamata.
    const ultimaChiamata = thoughts.map((t) => t.type).lastIndexOf('call');
    const trovati = thoughts
      .slice(ultimaChiamata + 1)
      .reduce((s, t) => s + (t.error ? 0 : t.count ?? 0), 0);
    if (trovati === 0) return 'Nessun esito qui: sto valutando dove altro cercare';
    return `Sto valutando ${trovati} ${trovati === 1 ? 'risultato' : 'risultati'}`;
  }
  return 'Sto scrivendo la risposta';
}

interface AvanzamentoProps {
  thoughts: ThoughtStep[];
  inizio?: Date;
}

export const Avanzamento: React.FC<AvanzamentoProps> = ({ thoughts, inizio }) => {
  // Mezzo secondo basta: il contatore mostra secondi interi, e le soglie delle
  // frasi sono di qualche secondo.
  const [adesso, setAdesso] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setAdesso(Date.now()), 500);
    return () => clearInterval(t);
  }, []);

  const passi = componi(thoughts);
  const partenza = inizio ? inizio.getTime() : adesso;
  const ultimoEvento = thoughts.length
    ? thoughts[thoughts.length - 1].time?.getTime() ?? partenza
    : partenza;
  const trascorsi = Math.max(0, (adesso - partenza) / 1000);
  const silenzio = Math.max(0, (adesso - ultimoEvento) / 1000);

  const testo = frase(thoughts, passi, silenzio, trascorsi);
  const scrive = testo === 'Sto scrivendo la risposta';

  return (
    <div className="rise overflow-hidden rounded-xl border border-line-2 bg-panel">
      <div className="flex items-center gap-3 px-4 py-3">
        <span className="flex h-4 w-4 shrink-0 items-center justify-center" aria-hidden>
          <span className="battito" />
        </span>
        {/* La chiave e' la frase: quando cambia, la riga rientra animata. */}
        <p
          key={testo}
          role="status"
          aria-live="polite"
          className="frase-in line-clamp-2 min-w-0 flex-1 text-[14px] font-medium leading-snug"
          title={testo}
        >
          <span className="testo-vivo">{testo}…</span>
        </p>
        <span className="shrink-0 font-mono text-[12px] tabular-nums text-ink-3">
          {Math.floor(trascorsi)} s
        </span>
      </div>

      {passi.length > 0 && (
        <div className="border-t border-line px-4 py-3">
          <ElencoPassi passi={passi} vivo />
        </div>
      )}

      {scrive && trascorsi > SOGLIA_PAZIENZA && (
        <p className="frase-in border-t border-line px-4 py-2.5 text-[12.5px] text-ink-2">
          Le risposte più articolate richiedono qualche secondo in più: il testo arriva intero, già con le citazioni.
        </p>
      )}

      {scrive && (
        <div className="space-y-2.5 border-t border-line bg-canvas px-4 py-4" aria-hidden>
          <div className="skeleton h-[10px] w-[92%]" />
          <div className="skeleton h-[10px] w-[78%]" />
          <div className="skeleton h-[10px] w-[85%]" />
          <div className="skeleton h-[10px] w-[41%]" />
        </div>
      )}
    </div>
  );
};
