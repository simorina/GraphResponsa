import React, { useEffect } from 'react';
import { X } from 'lucide-react';
import type { Fonte } from '../types';

interface SourceDrawerProps {
  source: Fonte | null;
  onClose: () => void;
}

/** Pannello laterale: il comma resta accanto alla risposta, non la copre. */
export const SourceDrawer: React.FC<SourceDrawerProps> = ({ source, onClose }) => {
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
        className="veil-in fixed inset-0 z-40 bg-ink/20 backdrop-blur-[2px]"
      />

      <aside
        role="dialog"
        aria-modal="true"
        className="drawer-in fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-line-2 bg-canvas shadow-[-20px_0_50px_-28px_rgba(16,33,45,0.28)]"
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <div className="mb-1 text-[12px] font-medium text-dorato">Testo ufficiale</div>
            <div className="font-mono text-[13px] text-ink">
              {source.norma}
              <span className="text-ink-3"> · art. </span>
              {source.articolo}
              <span className="text-ink-3"> · comma </span>
              {source.comma}
            </div>
          </div>
          <button
            onClick={onClose}
            className="-mr-1.5 -mt-1 rounded-md p-1.5 text-ink-3 transition-colors duration-200 hover:bg-raise hover:text-ink active:translate-y-px"
            title="Chiudi (Esc)"
          >
            <X className="h-4 w-4" strokeWidth={1.5} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
          {source.titoloNorma && (
            <p className="mb-5 max-w-[52ch] border-l-2 border-alloro-2 py-0.5 pl-3.5 text-[12.5px] leading-relaxed text-ink-3">
              {source.titoloNorma}
            </p>
          )}

          {source.rubrica && (
            <h2 className="mb-4 text-[15px] font-medium tracking-[-0.015em] text-ink">
              {source.rubrica}
            </h2>
          )}

          <div className="select-text whitespace-pre-wrap font-editorial text-[16.5px] leading-[1.72] text-[#223849]">
            {source.testo}
          </div>
        </div>

        <div className="shrink-0 border-t border-line px-6 py-3">
          <p className="text-[11.5px] text-ink-3">
            Estratto dall'archivio · verificare sul Bollettino Ufficiale
          </p>
        </div>
      </aside>
    </>
  );
};
