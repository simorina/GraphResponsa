import React from 'react';
import { ChevronRight, Search, BookOpen, Layers, Link2, Library, Crosshair, Circle } from 'lucide-react';
import type { ThoughtStep } from '../types';

interface ThinkingTrailProps {
  thoughts: ThoughtStep[];
  isStreaming?: boolean;
}

type Passo = {
  icona: React.ElementType;
  azione: string;
  oggetto: string;
  quante?: number;
  unita: string;
  errore?: string | null;
  concluso: boolean;
};

function descrivi(nome: string, args: Record<string, any>) {
  switch (nome) {
    case 'cerca_testo':
      return {
        icona: Search,
        azione: 'Ricerca nel testo',
        oggetto: args.query ? `«${args.query}»` : 'termini normativi',
        unita: 'commi',
      };
    case 'leggi_articolo':
      return {
        icona: BookOpen,
        azione: 'Lettura integrale',
        oggetto: args.norma_id ? `${args.norma_id} · art. ${args.numero ?? '?'}` : 'articolo',
        unita: 'commi',
      };
    case 'struttura_norma':
      return {
        icona: Layers,
        azione: 'Indice della norma',
        oggetto: args.norma_id ?? 'atto',
        unita: 'articoli',
      };
    case 'trova_norma':
      return {
        icona: Crosshair,
        azione: 'Individuazione estremi',
        oggetto:
          args.numero && args.anno
            ? `n. ${args.numero}/${args.anno}`
            : args.testo
              ? `«${args.testo}»`
              : 'atto',
        unita: 'norme',
      };
    case 'citazioni_da':
      return {
        icona: Link2,
        azione: 'Rinvii in uscita',
        oggetto: args.norma_id ?? 'atto',
        unita: 'norme',
      };
    case 'chi_cita':
      return {
        icona: Link2,
        azione: 'Rinvii in entrata',
        oggetto: args.norma_id ?? 'atto',
        unita: 'norme',
      };
    case 'elenco_norme':
      return {
        icona: Library,
        azione: 'Copertura archivio',
        oggetto: [args.tipo, args.anno].filter(Boolean).join(' · ') || 'intero corpus',
        unita: 'norme',
      };
    default:
      return { icona: Circle, azione: nome, oggetto: '', unita: 'esiti' };
  }
}

/** Accoppia ogni chiamata al risultato che la segue: un passaggio, una riga. */
function componi(thoughts: ThoughtStep[]): Passo[] {
  const passi: Passo[] = [];
  for (const t of thoughts) {
    if (t.type === 'call') {
      const d = descrivi(t.name, t.args ?? {});
      passi.push({ ...d, concluso: false });
    } else {
      const ultimo = [...passi].reverse().find((p) => !p.concluso);
      if (ultimo) {
        ultimo.concluso = true;
        ultimo.quante = t.count;
        ultimo.errore = t.error;
      }
    }
  }
  return passi;
}

export const ThinkingTrail: React.FC<ThinkingTrailProps> = ({ thoughts, isStreaming }) => {
  const passi = componi(thoughts);
  if (passi.length === 0) return null;

  const inCorso = isStreaming && passi.some((p) => !p.concluso);

  return (
    <details className="group mb-4 overflow-hidden rounded-xl border border-line bg-panel">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-ink-3 transition-colors duration-200 hover:text-ink-2">
        <ChevronRight
          className="h-3 w-3 shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-open:rotate-90"
          strokeWidth={2}
        />
        <span className="text-[12.5px]">
          {inCorso ? 'Consultazione dell’archivio in corso' : 'Percorso di consultazione'}
        </span>
        <span className="font-mono text-[10.5px] tabular-nums text-ink-3">
          {String(passi.length).padStart(2, '0')}
        </span>
        {inCorso && <span className="pulse-dot h-1 w-1 rounded-full bg-dorato-2" />}
      </summary>

      <ol className="space-y-2.5 border-t border-line px-3.5 py-3">
        {passi.map((p, i) => {
          const Icona = p.icona;
          return (
            <li
              key={i}
              className="slide-in flex items-baseline gap-2.5 text-[12px]"
              style={{ ['--i' as string]: i }}
            >
              <Icona
                className={`h-3 w-3 shrink-0 translate-y-[2px] ${p.errore ? 'text-rosso' : 'text-alloro-2'}`}
                strokeWidth={1.5}
              />
              <span className="shrink-0 text-ink-2">{p.azione}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-ink-3">
                {p.oggetto}
              </span>
              <span className="shrink-0 font-mono text-[10.5px] tabular-nums">
                {p.errore ? (
                  <span className="text-rosso">nessun esito</span>
                ) : p.concluso ? (
                  <span className="text-ink-3">
                    {p.quante ?? 0} {p.unita}
                  </span>
                ) : (
                  <span className="text-dorato-2">…</span>
                )}
              </span>
            </li>
          );
        })}
      </ol>
    </details>
  );
};
