import React, { useRef, useEffect } from 'react';
import { ArrowUp, Square } from 'lucide-react';
import type { StatsState } from '../types';

interface InputBarProps {
  input: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  loading: boolean;
  stats: StatsState;
}

const nf = new Intl.NumberFormat('it-IT');

function copertura(stats: StatsState): string {
  if (stats.fase === 'pronto') {
    const { conTesto, articoli } = stats.dati;
    return `${nf.format(conTesto)} norme · ${nf.format(articoli)} articoli`;
  }
  if (stats.fase === 'errore') return 'copertura non verificabile';
  return 'lettura archivio…';
}

export const InputBar: React.FC<InputBarProps> = ({
  input,
  onChange,
  onSubmit,
  onStop,
  loading,
  stats,
}) => {
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!loading) onSubmit();
    }
  };

  const pronto = input.trim().length > 0 && !loading;

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-canvas via-canvas/95 to-transparent px-4 pb-4 pt-12 md:px-6">
      <div className="pointer-events-auto mx-auto max-w-3xl">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!loading) onSubmit();
          }}
          /* Il contorno di focus sta QUI e non sul textarea: un outline segue la
             forma dell'elemento che riceve il focus, e il textarea non e'
             arrotondato - l'arrotondamento e' di questo contenitore. Il
             risultato era un rettangolo dentro una scatola smussata.
             L'indicatore non si toglie, si sposta: chi naviga da tastiera deve
             continuare a vedere dov'e'. */
          className="rounded-[26px] border border-campo bg-canvas shadow-[0_12px_32px_-14px_rgba(12,27,38,0.28)] transition-[border-color,box-shadow] duration-200 hover:border-ink-3 focus-within:border-azzurro focus-within:ring-4 focus-within:ring-azzurro-3/70"
        >
          <textarea
            ref={areaRef}
            value={input}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Poni un quesito sulla normativa sammarinese…"
            className="max-h-52 w-full resize-none bg-transparent px-5 pb-1.5 pt-4 text-[15.5px] leading-relaxed text-ink placeholder-ink-3 focus:outline-none focus-visible:outline-none"
            style={{ minHeight: '48px' }}
          />

          <div className="flex items-center justify-between gap-3 px-3 pb-2.5 pt-1">
            <div className="flex min-w-0 items-center gap-2 pl-1.5">
              <span
                className={`h-[7px] w-[7px] shrink-0 rounded-full ${
                  stats.fase === 'pronto'
                    ? 'bg-alloro'
                    : stats.fase === 'errore'
                      ? 'bg-rosso'
                      : 'pulse-dot bg-ink-3'
                }`}
              />
              <span className="truncate font-mono text-[11.5px] tracking-[0.03em] text-ink-2">
                {copertura(stats)}
              </span>
            </div>

            {loading ? (
              <button
                type="button"
                onClick={onStop}
                title="Interrompi"
                aria-label="Interrompi la consultazione"
                className="flex h-9 shrink-0 items-center gap-2 rounded-full bg-ink px-3.5 text-[13px] font-medium text-white transition-colors duration-200 hover:bg-ink-2 active:translate-y-px"
              >
                <Square className="h-2.5 w-2.5 fill-current" strokeWidth={0} />
                Interrompi
              </button>
            ) : (
              <button
                type="submit"
                disabled={!pronto}
                title="Invia il quesito"
                aria-label="Invia il quesito"
                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                  pronto
                    ? 'bg-azzurro text-white shadow-[0_4px_12px_-4px_rgba(10,107,159,0.7)] hover:-translate-y-px hover:bg-azzurro-scuro active:translate-y-0'
                    : 'cursor-not-allowed bg-raise-2 text-ink-3'
                }`}
              >
                <ArrowUp className="h-4 w-4" strokeWidth={1.75} />
              </button>
            )}
          </div>
        </form>

        <p className="mt-2.5 text-center text-[12px] leading-relaxed text-ink-2">
          Strumento di supporto all'analisi. Riscontrare i testi sul Bollettino Ufficiale.
        </p>
      </div>
    </div>
  );
};
