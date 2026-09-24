import React, { useRef, useEffect } from 'react';
import { ArrowUp, Square } from 'lucide-react';
import type { StatsState } from '../types';
import { useSchermoStretto } from '../hooks/useMobile';

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
  const bloccoRef = useRef<HTMLDivElement>(null);
  const stretto = useSchermoStretto();

  /**
   * Quanto spazio occupa, dal suo bordo alto al fondo dello schermo, e lo
   * dice alla pagina come --altezza-compositore.
   *
   * La lista lo usa per il vuoto in fondo, e la freccia "torna in fondo" per
   * appoggiarcisi sopra. Prima entrambe usavano valori fissi, e l'altezza vera
   * cambia: il testo che va a capo, la tastiera che sale, il telefono che
   * ruota. Col valore fisso la freccia finiva sopra il riquadro.
   */
  useEffect(() => {
    const el = bloccoRef.current;
    if (!el) return;
    const pubblica = () => {
      const alto = window.innerHeight - el.getBoundingClientRect().top;
      document.documentElement.style.setProperty('--altezza-compositore', `${Math.round(alto)}px`);
    };
    pubblica();
    const osservatore = new ResizeObserver(pubblica);
    osservatore.observe(el);
    window.addEventListener('resize', pubblica);
    return () => {
      osservatore.disconnect();
      window.removeEventListener('resize', pubblica);
    };
  }, []);

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
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-canvas via-canvas/95 to-transparent max-md:from-60% pb-[max(1rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-12 md:px-6">
      <div ref={bloccoRef} className="pointer-events-auto mx-auto max-w-3xl">
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
          className="rounded-[26px] border border-campo bg-foglio shadow-[0_12px_32px_-14px_rgba(12,27,38,0.28)] transition-[border-color,box-shadow] duration-200 hover:border-ink-3 focus-within:border-azzurro focus-within:ring-4 focus-within:ring-azzurro-3/70 max-md:grid max-md:grid-cols-[minmax(0,1fr)_auto] max-md:items-end"
        >
          <textarea
            ref={areaRef}
            value={input}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder={stretto ? 'Chiedi a Responsa…' : 'Poni un quesito sulla normativa sammarinese…'}
            className="max-h-52 w-full resize-none bg-transparent px-5 pb-1.5 pt-4 text-[16px] leading-relaxed text-ink placeholder-ink-3 focus:outline-none focus-visible:outline-none max-md:py-3.5 max-md:pl-5 max-md:pr-2"
            style={{ minHeight: '48px' }}
          />

          <div className="flex items-center justify-between gap-3 px-3 pb-2.5 pt-1 max-md:justify-end max-md:p-[5px]">
            <div className="flex min-w-0 items-center gap-2 pl-1.5 max-md:hidden">
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
                className="flex h-11 shrink-0 items-center gap-2 rounded-full bg-ink px-4 text-[13.5px] font-medium text-canvas transition-colors duration-200 hover:bg-ink-2 active:scale-[0.97] max-md:w-11 max-md:justify-center max-md:px-0 md:h-9 md:px-3.5"
              >
                <Square className="h-2.5 w-2.5 fill-current max-md:h-3 max-md:w-3" strokeWidth={0} />
                <span className="max-md:sr-only">Interrompi</span>
              </button>
            ) : (
              <button
                type="submit"
                disabled={!pronto}
                title="Invia il quesito"
                aria-label="Invia il quesito"
                className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] md:h-9 md:w-9 ${
                  pronto
                    ? 'bg-azzurro text-canvas shadow-[0_4px_12px_-4px_rgba(10,107,159,0.7)] hover:-translate-y-px hover:bg-azzurro-scuro active:translate-y-0 max-md:shadow-none'
                    : 'cursor-not-allowed bg-raise-2 text-ink-3'
                }`}
              >
                <ArrowUp className="h-4 w-4 max-md:h-5 max-md:w-5" strokeWidth={stretto ? 2.25 : 1.75} />
              </button>
            )}
          </div>
        </form>

        <p className="mt-2.5 text-center text-[12px] leading-relaxed text-ink-2 max-md:mt-2 max-md:text-[11.5px] max-md:text-ink-3">
          <span className="sm:hidden">Riscontrare i testi sul Bollettino Ufficiale.</span>
          <span className="hidden sm:inline">
            Strumento di supporto all'analisi. Riscontrare i testi sul Bollettino Ufficiale.
          </span>
        </p>
      </div>
    </div>
  );
};
