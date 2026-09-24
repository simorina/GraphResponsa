import React from 'react';
import { ArrowUpRight, Briefcase, Landmark, Sprout, Vote } from 'lucide-react';
import { Sigillo } from './Sigillo';

interface EmptyStateProps {
  onSelectPrompt: (prompt: string) => void;
  /** Il nome di chi consulta, per il saluto sul telefono. */
  nomeUtente?: string | null;
}

const SUGGERIMENTI = [
  {
    materia: 'Lavoro',
    titolo: 'Lavoro agile',
    icona: Briefcase,
    riga: 'Tutele, dotazioni e recesso nella L. 202/2020',
    prompt:
      'Quali tutele, dotazioni tecnologiche e regole di recesso prevede la Legge 202/2020 per il lavoro agile a San Marino?',
  },
  {
    materia: 'Costituzionale',
    titolo: 'Capitani Reggenti',
    icona: Landmark,
    riga: 'Requisiti e incompatibilità nella LC 185/2005',
    prompt:
      'Quali sono i requisiti di eleggibilità e le incompatibilità con la carica di Capitano Reggente previsti dalla Legge Costituzionale 185/2005 e Qualificata 186/2005?',
  },
  {
    materia: 'Impresa',
    titolo: 'Giovani imprenditori',
    icona: Sprout,
    riga: "Agevolazioni IGR e prestiti d'onore nella L. 178/2015",
    prompt:
      "Quali agevolazioni, incentivi fiscali (IGR 4%) e prestiti d'onore prevede la Legge 178/2015 a sostegno dei giovani imprenditori a San Marino?",
  },
  {
    materia: 'Storico',
    titolo: 'Elettorato femminile',
    icona: Vote,
    riga: 'Con quale legge le donne ottennero il voto',
    prompt:
      "In quale anno e con quale legge le donne a San Marino hanno ottenuto per la prima volta l'estensione del diritto di voto?",
  },
];

/** Il saluto secondo l'ora, col nome se c'e': "Buonasera, Simone". */
function saluto(nome?: string | null): string {
  const ora = new Date().getHours();
  const parte = ora >= 5 && ora < 13 ? 'Buongiorno' : ora >= 13 && ora < 18 ? 'Buon pomeriggio' : 'Buonasera';
  const primo = (nome ?? '').trim().split(/\s+/)[0];
  return primo ? `${parte}, ${primo}` : `${parte}`;
}

/**
 * La pagina vuota.
 *
 * Sul telefono segue l'app di Claude: il sigillo e il saluto in mezzo allo
 * schermo, in serif, e i quesiti d'esempio come pillole che scorrono di lato
 * subito sopra l'area di scrittura - dove sta gia' il pollice. Un elenco
 * verticale di quattro righe, sul telefono, spingeva l'ultima sotto la
 * tastiera appena la si apriva.
 *
 * Sul desktop resta l'indice di un repertorio: il titolo a sinistra, sotto i
 * quesiti in righe numerate separate da un filetto.
 */
export const EmptyState: React.FC<EmptyStateProps> = ({ onSelectPrompt, nomeUtente }) => (
  <div className="flex flex-1 flex-col md:block md:px-1 md:pb-4 md:pt-14">
    {/* ── Telefono ─────────────────────────────────────────────── */}
    <div className="flex flex-1 flex-col items-center justify-center px-2 pb-6 text-center md:hidden">
      <Sigillo className="rise h-11 w-11" />
      <h1
        className="rise mt-5 font-editorial text-[31px] font-normal leading-[1.15] tracking-[-0.01em] text-ink"
        style={{ ['--i' as string]: 1 }}
      >
        {saluto(nomeUtente)}
      </h1>
      <p
        className="rise mt-2.5 max-w-[30ch] text-[15px] leading-relaxed text-ink-2"
        style={{ ['--i' as string]: 2 }}
      >
        Chiedimi della normativa sammarinese: rispondo citando articolo e comma.
      </p>
    </div>

    {/* Le pillole scorrono di lato fino al bordo dello schermo: il margine
        negativo le porta oltre l'imbottitura della colonna, e lo scatto le
        ferma sempre allineate. */}
    <div
      className="rise -mx-4 flex snap-x snap-mandatory scroll-px-4 gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] md:hidden [&::-webkit-scrollbar]:hidden"
      style={{ ['--i' as string]: 3 }}
    >
      {SUGGERIMENTI.map((s) => {
        const Icona = s.icona;
        return (
          <button
            key={s.titolo}
            onClick={() => onSelectPrompt(s.prompt)}
            className="flex h-11 shrink-0 snap-start items-center gap-2 rounded-full border border-line-2 bg-foglio pl-3.5 pr-4 text-[14.5px] font-medium text-ink transition-colors duration-200 active:bg-raise"
          >
            <Icona className="h-4 w-4 text-ink-3" strokeWidth={1.75} />
            {s.titolo}
          </button>
        );
      })}
    </div>

    {/* ── Desktop: invariato ───────────────────────────────────── */}
    <div className="hidden md:block">
      <h1
        className="rise max-w-[18ch] text-[30px] font-medium leading-[1.1] tracking-[-0.035em] text-ink md:text-[40px]"
        style={{ ['--i' as string]: 1 }}
      >
        Cosa vuoi sapere della <span className="text-azzurro">normativa sammarinese</span>?
      </h1>

      <p
        className="rise mt-4 max-w-[56ch] text-[15.5px] leading-relaxed text-ink-2"
        style={{ ['--i' as string]: 2 }}
      >
        Ogni risposta arriva dai testi ufficiali del Consiglio Grande e Generale,
        con articolo e comma allegati. Se l'archivio non ce l'ha, te lo dice.
      </p>

      <div className="rise mt-10" style={{ ['--i' as string]: 3 }}>
        <div className="mb-1 flex items-center gap-3">
          <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3">
            Per cominciare
          </span>
          <span className="h-px flex-1 bg-line" />
        </div>

        <ul className="divide-y divide-line border-b border-line">
          {SUGGERIMENTI.map((s, i) => (
            <li key={s.titolo} className="slide-in" style={{ ['--i' as string]: 4 + i }}>
              <button
                onClick={() => onSelectPrompt(s.prompt)}
                className="group -mx-3 grid w-[calc(100%+1.5rem)] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-4 rounded-lg px-3 py-3.5 text-left transition-colors duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:bg-panel active:translate-y-px"
              >
                <span className="font-mono text-[12px] tabular-nums text-ink-3 transition-colors duration-200 group-hover:text-azzurro">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span className="min-w-0">
                  <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
                    <span className="text-[15px] font-semibold text-ink transition-colors duration-200 group-hover:text-azzurro">
                      {s.titolo}
                    </span>
                    <span className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink-3">
                      {s.materia}
                    </span>
                  </span>
                  <span className="mt-0.5 block text-[13.5px] leading-snug text-ink-2">{s.riga}</span>
                </span>
                <ArrowUpRight
                  className="h-4 w-4 text-ink-3 transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-azzurro"
                  strokeWidth={1.75}
                />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  </div>
);
