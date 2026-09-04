import React from 'react';
import { Briefcase, Landmark, Sparkle, Clock } from 'lucide-react';
import { Sigillo } from './Sigillo';

interface EmptyStateProps {
  onSelectPrompt: (prompt: string) => void;
}

const SUGGERIMENTI = [
  {
    icona: Briefcase,
    materia: 'Lavoro',
    titolo: 'Lavoro agile',
    riga: 'Tutele, dotazioni e recesso nella L. 202/2020',
    prompt:
      'Quali tutele, dotazioni tecnologiche e regole di recesso prevede la Legge 202/2020 per il lavoro agile a San Marino?',
  },
  {
    icona: Landmark,
    materia: 'Costituzionale',
    titolo: 'Capitani Reggenti',
    riga: 'Requisiti e incompatibilità nella LC 185/2005',
    prompt:
      'Quali sono i requisiti di eleggibilità e le incompatibilità con la carica di Capitano Reggente previsti dalla Legge Costituzionale 185/2005 e Qualificata 186/2005?',
  },
  {
    icona: Sparkle,
    materia: 'Impresa',
    titolo: 'Giovani imprenditori',
    riga: "Agevolazioni IGR e prestiti d'onore nella L. 178/2015",
    prompt:
      "Quali agevolazioni, incentivi fiscali (IGR 4%) e prestiti d'onore prevede la Legge 178/2015 a sostegno dei giovani imprenditori a San Marino?",
  },
  {
    icona: Clock,
    materia: 'Storico',
    titolo: 'Elettorato femminile',
    riga: 'Con quale legge le donne ottennero il voto',
    prompt:
      "In quale anno e con quale legge le donne a San Marino hanno ottenuto per la prima volta l'estensione del diritto di voto?",
  },
];

export const EmptyState: React.FC<EmptyStateProps> = ({ onSelectPrompt }) => (
  <div className="flex flex-col items-center px-1 pb-4 pt-10 text-center md:pt-20">
    {/* Il verde dei monti sotto il sigillo, cerchiato d’oro */}
    <div className="rise mb-6 flex h-14 w-14 items-center justify-center rounded-2xl border border-dorato-2/45 bg-gradient-to-b from-canvas to-alloro-3/55 shadow-[0_2px_10px_-5px_rgba(62,107,74,0.4)]">
      <Sigillo className="h-7 w-7" />
    </div>

    <h1
      className="rise max-w-[22ch] text-[26px] font-normal leading-[1.22] tracking-[-0.03em] text-ink md:text-[31px]"
      style={{ ['--i' as string]: 1 }}
    >
      Cosa vuoi sapere della{' '}
      <span className="font-editorial italic text-azzurro">normativa sammarinese</span>?
    </h1>

    <p
      className="rise mt-4 max-w-[52ch] text-[14px] leading-relaxed text-ink-2"
      style={{ ['--i' as string]: 2 }}
    >
      Ogni risposta arriva dai testi ufficiali del Consiglio Grande e Generale,
      con articolo e comma allegati. Se l'archivio non ce l'ha, te lo dice.
    </p>

    <div className="mt-10 grid w-full grid-cols-1 gap-2.5 sm:grid-cols-2">
      {SUGGERIMENTI.map((s, i) => {
        const Icona = s.icona;
        return (
          <button
            key={s.titolo}
            onClick={() => onSelectPrompt(s.prompt)}
            className="rise group flex items-start gap-3 rounded-xl border border-line bg-canvas p-3.5 text-left shadow-[0_1px_2px_rgba(16,33,45,0.04)] transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px hover:border-alloro-2 hover:shadow-[0_4px_14px_-6px_rgba(62,107,74,0.32)] active:translate-y-0 active:shadow-none"
            style={{ ['--i' as string]: 3 + i }}
          >
            <Icona
              className="mt-[3px] h-4 w-4 shrink-0 text-alloro-2 transition-colors duration-200 group-hover:text-alloro"
              strokeWidth={1.5}
            />
            <span className="min-w-0">
              <span className="flex items-baseline gap-2">
                <span className="text-[13.5px] font-medium text-ink">{s.titolo}</span>
                <span className="text-[11px] text-dorato">
                  {s.materia}
                </span>
              </span>
              <span className="mt-1 block text-[12.5px] leading-snug text-ink-2">{s.riga}</span>
            </span>
          </button>
        );
      })}
    </div>
  </div>
);
