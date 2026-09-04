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
          className="rounded-[26px] border border-line-2 bg-canvas shadow-[0_10px_30px_-14px_rgba(16,33,45,0.20)] transition-colors duration-200 focus-within:border-azzurro-2"
        >
          <textarea
            ref={areaRef}
            value={input}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Poni un quesito sulla normativa sammarinese…"
            className="max-h-52 w-full resize-none bg-transparent px-5 pb-1.5 pt-4 text-[15px] leading-relaxed text-ink placeholder-ink-3 focus:outline-none"
            style={{ minHeight: '48px' }}
          />

          <div className="flex items-center justify-between gap-3 px-3 pb-2.5 pt-1">
            <div className="flex min-w-0 items-center gap-2 pl-1.5">
              <span
                className={`h-[5px] w-[5px] shrink-0 rounded-full ${
                  stats.fase === 'pronto'
                    ? 'bg-alloro'
                    : stats.fase === 'errore'
                      ? 'bg-rosso'
                      : 'pulse-dot bg-ink-3'
                }`}
              />
              <span className="truncate font-mono text-[10.5px] tracking-[0.05em] text-ink-3">
                {copertura(stats)}
              </span>
            </div>

            {loading ? (
              <button
                type="button"
                onClick={onStop}
                title="Interrompi"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line-2 bg-raise text-ink-2 transition-colors duration-200 hover:border-azzurro-2 hover:text-ink active:translate-y-px"
              >
                <Square className="h-2.5 w-2.5 fill-current" strokeWidth={0} />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!pronto}
                title="Invia il quesito"
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                  pronto
                    ? 'bg-azzurro text-white hover:-translate-y-px active:translate-y-0'
                    : 'cursor-not-allowed bg-raise text-ink-3'
                }`}
              >
                <ArrowUp className="h-4 w-4" strokeWidth={2.2} />
              </button>
            )}
          </div>
        </form>

        <p className="mt-2.5 text-center text-[11px] leading-relaxed text-ink-3">
          Strumento di supporto all'analisi. Riscontrare i testi sul Bollettino Ufficiale.
        </p>
      </div>
    </div>
  );
};
