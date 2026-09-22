import React from 'react';
import { ArrowUpRight } from 'lucide-react';

interface EmptyStateProps {
  onSelectPrompt: (prompt: string) => void;
}

const SUGGERIMENTI = [
  {
    materia: 'Lavoro',
    titolo: 'Lavoro agile',
    riga: 'Tutele, dotazioni e recesso nella L. 202/2020',
    prompt:
      'Quali tutele, dotazioni tecnologiche e regole di recesso prevede la Legge 202/2020 per il lavoro agile a San Marino?',
  },
  {
    materia: 'Costituzionale',
    titolo: 'Capitani Reggenti',
    riga: 'Requisiti e incompatibilità nella LC 185/2005',
    prompt:
      'Quali sono i requisiti di eleggibilità e le incompatibilità con la carica di Capitano Reggente previsti dalla Legge Costituzionale 185/2005 e Qualificata 186/2005?',
  },
  {
    materia: 'Impresa',
    titolo: 'Giovani imprenditori',
    riga: "Agevolazioni IGR e prestiti d'onore nella L. 178/2015",
    prompt:
      "Quali agevolazioni, incentivi fiscali (IGR 4%) e prestiti d'onore prevede la Legge 178/2015 a sostegno dei giovani imprenditori a San Marino?",
  },
  {
    materia: 'Storico',
    titolo: 'Elettorato femminile',
    riga: 'Con quale legge le donne ottennero il voto',
    prompt:
      "In quale anno e con quale legge le donne a San Marino hanno ottenuto per la prima volta l'estensione del diritto di voto?",
  },
];

/**
 * La pagina vuota come l'indice di un repertorio: il titolo a sinistra, sotto
 * i quesiti d'esempio in righe numerate separate da un filetto. Prima era
 * tutto centrato con quattro schede in griglia - la composizione che hanno
 * tutte le chat, e che non diceva niente di un archivio di leggi. Lo stemma
 * sopra il titolo non c'e' piu': sta gia' nella barra laterale e in testata,
 * e spingeva l'ultimo quesito sotto l'area di scrittura.
 */
export const EmptyState: React.FC<EmptyStateProps> = ({ onSelectPrompt }) => (
  <div className="px-1 pb-4 pt-8 md:pt-14">
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
);
