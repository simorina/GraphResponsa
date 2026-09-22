import React from 'react';
import {
  ChevronRight, Search, BookOpen, Layers, Link2, Library, Crosshair, Circle, Check,
} from 'lucide-react';
import type { ThoughtStep } from '../types';
import { estremi } from '../norme';

const SINGOLARE: Record<string, string> = {
  commi: 'comma', articoli: 'articolo', norme: 'norma', esiti: 'esito',
};

/** "1 norma", "8 commi": il plurale fisso stonava proprio sul caso piu' comune. */
export function quantita(n: number, unita: string): string {
  return `${n} ${n === 1 ? SINGOLARE[unita] ?? unita : unita}`;
}

export type Passo = {
  nome: string;
  args: Record<string, any>;
  icona: React.ElementType;
  azione: string;
  oggetto: string;
  quante?: number;
  unita: string;
  errore?: string | null;
  concluso: boolean;
};

function articolo(args: Record<string, any>) {
  const norma = estremi(args.norma_id);
  if (!norma) return 'articolo';
  return args.numero ? `art. ${args.numero} · ${norma}` : norma;
}

export function descrivi(nome: string, args: Record<string, any>) {
  switch (nome) {
    case 'cerca_testo':
      return {
        icona: Search,
        azione: 'Ricerca nel testo',
        oggetto: args.query ? `«${args.query}»` : 'termini normativi',
        unita: 'commi',
      };
    case 'leggi_articolo':
      return { icona: BookOpen, azione: 'Lettura integrale', oggetto: articolo(args), unita: 'commi' };
    case 'struttura_norma':
      return {
        icona: Layers,
        azione: 'Indice della norma',
        oggetto: estremi(args.norma_id) || 'atto',
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
        oggetto: estremi(args.norma_id) || 'atto',
        unita: 'norme',
      };
    case 'chi_cita':
      return {
        icona: Link2,
        azione: 'Rinvii in entrata',
        oggetto: estremi(args.norma_id) || 'atto',
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
export function componi(thoughts: ThoughtStep[]): Passo[] {
  const passi: Passo[] = [];
  for (const t of thoughts) {
    if (t.type === 'call') {
      const args = t.args ?? {};
      passi.push({ nome: t.name, args, ...descrivi(t.name, args), concluso: false });
    } else {
      // Le chiamate in parallelo tornano nell'ordine in cui sono partite: il
      // risultato va alla prima ancora aperta, non all'ultima.
      const aperto = passi.find((p) => !p.concluso && p.nome === t.name)
        ?? passi.find((p) => !p.concluso);
      if (aperto) {
        aperto.concluso = true;
        aperto.quante = t.count;
        aperto.errore = t.error;
      }
    }
  }
  return passi;
}

/** L'elenco dei passaggi: lo stesso dal vivo e a risposta finita. */
export const ElencoPassi: React.FC<{ passi: Passo[]; vivo?: boolean }> = ({ passi, vivo }) => (
  <ol className="space-y-2">
    {passi.map((p, i) => {
      const Icona = p.icona;
      return (
        <li
          key={i}
          className="slide-in flex items-center gap-2.5 text-[12.5px]"
          style={{ ['--i' as string]: vivo ? 0 : i }}
        >
          <span
            className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md ${
              p.errore
                ? 'bg-rosso-2 text-rosso'
                : p.concluso
                  ? 'bg-raise text-ink-2'
                  : 'bg-azzurro-3/60 text-azzurro'
            }`}
          >
            {p.concluso && !p.errore && vivo ? (
              <Check className="h-3 w-3" strokeWidth={1.75} />
            ) : (
              <Icona className="h-3 w-3" strokeWidth={1.75} />
            )}
          </span>
          {/* Da telefono l'icona basta a dire il tipo: lo spazio va all'oggetto. */}
          <span className="hidden shrink-0 font-medium text-ink-2 sm:inline">{p.azione}</span>
          <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink-3" title={p.oggetto}>
            {p.oggetto}
          </span>
          <span className="shrink-0 font-mono text-[11.5px] tabular-nums">
            {p.errore ? (
              <span className="text-rosso">nessun esito</span>
            ) : p.concluso ? (
              <span className="text-ink-2">{quantita(p.quante ?? 0, p.unita)}</span>
            ) : (
              <span className="battito" style={{ ['--dim' as string]: '6px' }} aria-label="in corso" />
            )}
          </span>
        </li>
      );
    })}
  </ol>
);

interface ThinkingTrailProps {
  thoughts: ThoughtStep[];
  /** Secondi dalla domanda alla risposta, se misurati in questa sessione. */
  durata?: number;
}

/** Il percorso a risposta consegnata: chiuso, si apre per chi vuole verificarlo. */
export const ThinkingTrail: React.FC<ThinkingTrailProps> = ({ thoughts, durata }) => {
  const passi = componi(thoughts);
  if (passi.length === 0) return null;

  return (
    <details className="group mb-4 overflow-hidden rounded-xl border border-line bg-panel">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 text-ink-2 transition-colors duration-200 hover:text-ink">
        <ChevronRight
          className="h-3.5 w-3.5 shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-open:rotate-90"
          strokeWidth={1.75}
        />
        <span className="text-[13px] font-medium">Percorso di consultazione</span>
        <span className="font-mono text-[11.5px] tabular-nums text-ink-3">
          {passi.length} {passi.length === 1 ? 'passaggio' : 'passaggi'}
          {durata ? ` · ${Math.round(durata)} s` : ''}
        </span>
      </summary>

      <div className="border-t border-line px-3.5 py-3">
        <ElencoPassi passi={passi} />
      </div>
    </details>
  );
};
