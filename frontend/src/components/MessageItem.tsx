import React, { useState } from 'react';
import { Copy, Check, AlertTriangle } from 'lucide-react';
import { marked } from 'marked';
import type { Message, Fonte } from '../types';
import { ThinkingTrail } from './ThinkingTrail';
import { Sigillo } from './Sigillo';
import { Riscontro } from './Riscontro';

interface MessageItemProps {
  message: Message;
  indice: number;
  domandaPrecedente: string;
  conversazione: string | null;
  onSelectSource: (source: Fonte) => void;
}

/** Segnaposto nella forma di un paragrafo, non un cerchietto che gira. */
const Attesa: React.FC = () => (
  <div className="space-y-2.5 py-1" aria-label="Composizione della risposta in corso">
    <div className="skeleton h-[11px] w-[92%]" />
    <div className="skeleton h-[11px] w-[78%]" />
    <div className="skeleton h-[11px] w-[85%]" />
    <div className="skeleton h-[11px] w-[41%]" />
  </div>
);

export const MessageItem: React.FC<MessageItemProps> = ({
  message,
  indice,
  domandaPrecedente,
  conversazione,
  onSelectSource,
}) => {
  const [copiato, setCopiato] = useState(false);

  const copia = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiato(true);
      setTimeout(() => setCopiato(false), 1800);
    } catch {
      /* clipboard negata: nessun riscontro, nessun crash */
    }
  };

  if (message.role === 'user') {
    return (
      <div className="flex justify-end py-3">
        <div className="max-w-[85%] select-text rounded-3xl rounded-br-lg bg-raise px-4 py-2.5 text-[15px] leading-relaxed text-ink">
          {message.content}
        </div>
      </div>
    );
  }

  const fonti = message.fonti ?? [];

  return (
    <div className="group/msg flex items-start gap-3.5 py-3 md:gap-4">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-dorato-2/45 bg-gradient-to-b from-canvas to-alloro-3/55">
        <Sigillo className="h-[15px] w-[15px]" />
      </div>

      <div className="min-w-0 flex-1">
        {message.thoughts && message.thoughts.length > 0 && (
          <ThinkingTrail thoughts={message.thoughts} isStreaming={message.isStreaming} />
        )}

        {message.content ? (
          <div
            className="prose-legal select-text"
            dangerouslySetInnerHTML={{ __html: marked.parse(message.content) as string }}
          />
        ) : message.isStreaming ? (
          <Attesa />
        ) : null}

        {message.isStreaming && message.content && (
          <span className="caret ml-0.5 inline-block h-[15px] w-[7px] translate-y-[2px] bg-dorato-2 align-baseline" />
        )}

        {message.error && (
          <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-[#e8cec7] bg-rosso-2 px-3.5 py-3">
            <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-rosso" strokeWidth={1.5} />
            <div className="min-w-0">
              <div className="mb-0.5 text-[12px] font-medium text-rosso">
                Consultazione interrotta
              </div>
              <p className="break-words font-mono text-[11.5px] leading-relaxed text-ink-2">
                {message.error}
              </p>
            </div>
          </div>
        )}

        {fonti.length > 0 && (
          <div className="mt-5 border-t border-line pt-3.5">
            <div className="mb-2.5 text-[12.5px] font-medium text-ink-2">
              Disposizioni citate <span className="font-mono text-ink-3">{fonti.length}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {fonti.map((f, i) => (
                <button
                  key={`${f.norma}-${f.articolo}-${f.comma}-${i}`}
                  onClick={() => onSelectSource(f)}
                  title={f.titoloNorma || undefined}
                  className="slide-in flex items-baseline gap-1.5 rounded-lg border border-line bg-canvas px-2.5 py-1 font-mono text-[11px] transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px hover:border-dorato-2 hover:bg-alloro-3/40 active:translate-y-0"
                  style={{ ['--i' as string]: Math.min(i, 12) }}
                >
                  <span className="text-ink-2">{f.norma}</span>
                  <span className="text-alloro">
                    {f.articolo}
                    <span className="text-ink-3">.</span>
                    {f.comma}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {!message.isStreaming && message.content && (
          <div className="mt-3 flex flex-col items-start gap-1">
            <div className="flex items-center gap-1">
            <button
              onClick={copia}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11.5px] text-ink-3 opacity-0 transition-all duration-200 hover:bg-canvas hover:text-ink-2 focus-visible:opacity-100 group-hover/msg:opacity-100 active:translate-y-px"
            >
              {copiato ? (
                <>
                  <Check className="h-3.5 w-3.5 text-alloro" strokeWidth={1.8} />
                  <span className="text-alloro">Copiato</span>
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5" strokeWidth={1.5} />
                  Copia
                </>
              )}
            </button>

            <Riscontro
              conversazione={conversazione}
              indiceMessaggio={indice}
              domanda={domandaPrecedente}
              risposta={message.content}
              fonti={fonti}
            />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
