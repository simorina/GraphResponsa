import React, { useCallback, useEffect, useRef, useState } from 'react';
import { X, FileText } from 'lucide-react';
import type { Fonte } from '../types';
import { useChiusuraIndietro } from '../hooks/useMobile';

interface SourceDrawerProps {
  source: Fonte | null;
  onClose: () => void;
}

/** Pannello laterale: il comma resta accanto alla risposta, non la copre. */

/**
 * Il PDF dove la fonte si legge davvero. Con l'articolo il server sceglie il
 * documento dell'articolo - per il Codice Penale il testo coordinato, non la
 * legge di emanazione - e con la pagina il visualizzatore si apre li'.
 */
function urlDocumento(source: Fonte): string {
  const articolo = String(source.articolo ?? '-');
  // L'articolo nel percorso, non in ?articolo=: la cache di CloudFront su
  // /documenti/* ignora i parametri e confonderebbe l'articolo con l'atto.
  const percorso = articolo && articolo !== '-' ? `/${encodeURIComponent(articolo)}` : '';
  const pagina = source.pagina ? `#page=${source.pagina}` : '';
  return `/documenti/${encodeURIComponent(source.norma)}${percorso}${pagina}`;
}

/** Oltre questo trascinamento il foglio si chiude invece di tornare su. */
const SOGLIA_CHIUSURA = 104;
/** Oltre questa velocita' (px al millisecondo) basta il gesto, non la distanza. */
const SCATTO = 0.55;

export const SourceDrawer: React.FC<SourceDrawerProps> = ({ source, onClose }) => {
  // Quanto il foglio e' stato tirato giu'. null = nessuno lo sta toccando.
  const [tirato, setTirato] = useState<number | null>(null);
  const presa = useRef({ da: 0, quando: 0 });

  const inizia = useCallback((e: React.PointerEvent) => {
    // Solo dove il foglio sale dal basso: da sm in su e' un pannello laterale
    // e il gesto non avrebbe senso.
    if (window.matchMedia('(min-width: 640px)').matches) return;
    presa.current = { da: e.clientY, quando: e.timeStamp };
    setTirato(0);
    e.currentTarget.setPointerCapture(e.pointerId);
  }, []);

  const muovi = useCallback((e: React.PointerEvent) => {
    if (tirato === null) return;
    const dy = e.clientY - presa.current.da;
    // Verso l'alto il foglio non sale: resiste, come un cassetto a fine corsa.
    setTirato(dy > 0 ? dy : dy / 6);
  }, [tirato]);

  const lascia = useCallback((e: React.PointerEvent) => {
    if (tirato === null) return;
    const dy = e.clientY - presa.current.da;
    const velocita = dy / Math.max(1, e.timeStamp - presa.current.quando);
    setTirato(null);
    if (dy > SOGLIA_CHIUSURA || velocita > SCATTO) onClose();
  }, [tirato, onClose]);

  useChiusuraIndietro(!!source, onClose);

  useEffect(() => {
    if (!source) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [source, onClose]);

  if (!source) return null;

  return (
    <>
      <button
        aria-label="Chiudi la fonte"
        onClick={onClose}
        className="veil-in fixed inset-0 z-40 bg-velo/20 backdrop-blur-[2px] max-md:bg-velo/45 max-md:backdrop-blur-none"
      />

      <aside
        role="dialog"
        aria-modal="true"
        style={tirato === null
          ? undefined
          // Solo transform: e' l'unica proprieta' che il browser sposta sulla
          // scheda grafica senza ridisegnare il foglio a ogni pixel.
          : { transform: `translate3d(0, ${Math.max(0, tirato)}px, 0)`, transition: 'none' }}
        className="foglio-in fixed inset-x-0 bottom-0 top-auto z-50 flex max-h-[88dvh] flex-col rounded-t-[26px] border-t border-line-2 bg-canvas shadow-[0_-18px_50px_-28px_rgba(16,33,45,0.35)] sm:drawer-in sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-full sm:max-w-lg sm:rounded-none sm:border-l sm:border-t-0 sm:shadow-[-20px_0_50px_-28px_rgba(16,33,45,0.28)]"
      >
        {/* La presa e' la fascia, non il cordoncino: un bersaglio da 4px non
            si prende col pollice. touch-action: none dice al browser di non
            scorrere mentre trasciniamo noi. */}
        <div
          onPointerDown={inizia}
          onPointerMove={muovi}
          onPointerUp={lascia}
          onPointerCancel={lascia}
          className="flex h-8 shrink-0 cursor-grab touch-none items-center justify-center active:cursor-grabbing sm:hidden"
          aria-hidden
        >
          <div className={`h-1 w-10 rounded-full transition-colors duration-200 ${
            tirato === null ? 'bg-line-2' : 'bg-ink-3'
          }`} />
        </div>

        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <div className="mb-1 font-mono text-[11px] uppercase tracking-[0.12em] text-ink-3">Testo ufficiale</div>
            <div className="font-mono text-[14px] font-medium text-ink">
              {source.norma}
              {/* Citato l'atto intero, articolo e comma sono "-": si mostrava
                  "art. - · comma -", che non dice niente e sembra un guasto. */}
              {String(source.articolo) !== '-' && (
                <>
                  <span className="text-ink-3"> · art. </span>
                  {source.articolo}
                </>
              )}
              {String(source.comma) !== '-' && (
                <>
                  <span className="text-ink-3"> · comma </span>
                  {source.comma}
                </>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="-mr-2 -mt-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-ink-2 transition-colors duration-200 hover:bg-raise hover:text-ink active:translate-y-px sm:h-9 sm:w-9"
            title="Chiudi (Esc)"
            aria-label="Chiudi la fonte"
          >
            <X className="h-5 w-5" strokeWidth={1.75} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-6 sm:px-6">
          {(source.abrogata || source.passoAbrogato || source.novellataDa?.length || source.ancheIn?.length) ? (
            <div className="mb-5 flex flex-col gap-2">
              {source.passoAbrogato ? (
                <div className="rounded-md border border-rosso bg-rosso-2 px-3.5 py-2.5">
                  <div className="mb-1 text-[12.5px] font-semibold text-rosso">
                    Questo passo è stato abrogato
                  </div>
                  <div className="text-[13px] leading-relaxed text-ink">
                    {source.passoAbrogatoDa?.length
                      ? <>Soppresso da <span className="font-mono">{source.passoAbrogatoDa.join(' · ')}</span>. L'atto che lo contiene resta in vigore, questo passo no.</>
                      : <>L'atto che lo contiene resta in vigore, questo passo no.</>}
                  </div>
                </div>
              ) : null}
              {source.abrogata ? (
                <div className="rounded-md border border-rosso bg-rosso-2 px-3.5 py-2.5">
                  <div className="mb-1 text-[12.5px] font-semibold text-rosso">
                    Atto abrogato — non è diritto vigente
                  </div>
                  <div className="text-[13px] leading-relaxed text-ink">
                    {source.abrogataDa?.length
                      ? <>Abrogato da <span className="font-mono">{source.abrogataDa.join(' · ')}</span>. Il testo resta consultabile a fini storici.</>
                      : <>Il testo resta consultabile a fini storici.</>}
                  </div>
                </div>
              ) : null}
              {source.novellataDa?.length ? (
                <div className="rounded-md border border-rosso/50 bg-rosso-2 px-3.5 py-2.5">
                  <div className="mb-1 text-[12.5px] font-semibold text-rosso">
                    Modificato da un atto successivo
                  </div>
                  <div className="font-mono text-[12.5px] text-ink">
                    {source.novellataDa.join(' · ')}
                  </div>
                </div>
              ) : null}
              {source.ancheIn?.length ? (
                <div className="rounded-md border border-line bg-raise px-3.5 py-2.5">
                  <div className="mb-1 text-[12.5px] font-semibold text-ink-2">
                    Stesso testo anche in
                  </div>
                  <div className="font-mono text-[12.5px] text-ink">
                    {source.ancheIn.join(' · ')}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {source.titoloNorma && (
            <p className="mb-5 max-w-[52ch] border-l-2 border-line-2 py-0.5 pl-3.5 text-[13.5px] leading-relaxed text-ink-2">
              {source.titoloNorma}
            </p>
          )}

          {source.rubrica && (
            <h2 className="mb-4 text-[16px] font-semibold tracking-[-0.015em] text-ink">
              {source.rubrica}
            </h2>
          )}

          <div className="select-text whitespace-pre-wrap font-editorial text-[17px] leading-[1.72] text-ink">
            {source.testo}
          </div>
        </div>

        <div className="shrink-0 border-t border-line px-5 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:px-6">
          {source.haDocumento && (
            <button
              onClick={() => window.open(urlDocumento(source), '_blank', 'noopener,noreferrer')}
              className="mb-2 flex items-center gap-1.5 rounded-lg border border-line-2 px-3 py-2 text-[13px] font-semibold text-ink transition-colors duration-200 hover:border-azzurro hover:bg-azzurro-3/40"
            >
              <FileText className="h-4 w-4" strokeWidth={1.75} />
              Apri PDF completo
            </button>
          )}
          <p className="text-[12px] text-ink-2">
            Estratto dall'archivio · verificare sul Bollettino Ufficiale
          </p>
        </div>
      </aside>
    </>
  );
};
