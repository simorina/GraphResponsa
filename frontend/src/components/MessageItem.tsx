import React, { useState } from 'react';
import { Copy, Check, AlertTriangle } from 'lucide-react';
import { marked } from 'marked';
import type { Message, Fonte } from '../types';
import { inserisciCitazioniInline, rimuoviMarcatori, trovaFonteDaDataset } from '../citazioni';
import { ThinkingTrail } from './ThinkingTrail';
import { Avanzamento } from './Avanzamento';
import { Sigillo } from './Sigillo';
import { Riscontro } from './Riscontro';

interface MessageItemProps {
  message: Message;
  indice: number;
  domandaPrecedente: string;
  conversazione: string | null;
  onSelectSource: (source: Fonte) => void;
}

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
      await navigator.clipboard.writeText(rimuoviMarcatori(message.content));
      setCopiato(true);
      setTimeout(() => setCopiato(false), 1800);
    } catch {
      /* clipboard negata: nessun riscontro, nessun crash */
    }
  };

  if (message.role === 'user') {
    return (
      <div className="flex justify-end py-3">
        <div className="max-w-[85%] select-text whitespace-pre-wrap rounded-3xl rounded-br-lg border border-line bg-raise px-4 py-2.5 text-[15px] leading-relaxed text-ink">
          {message.content}
        </div>
      </div>
    );
  }

  const fonti = message.fonti ?? [];

  const gestisciClickCitazione = (e: React.MouseEvent<HTMLDivElement>) => {
    const bottone = (e.target as HTMLElement).closest('.cita-inline') as HTMLElement | null;
    if (!bottone) return;
    const trovata = trovaFonteDaDataset(bottone.dataset, fonti);
    if (trovata) onSelectSource(trovata);
  };

  return (
    <div className="group/msg flex items-start gap-3.5 py-3 md:gap-4">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line-2 bg-canvas shadow-[0_1px_2px_rgba(12,27,38,0.06)]">
        <Sigillo className="h-[17px] w-[17px]" />
      </div>

      <div className="min-w-0 flex-1">
        {/* Durante l'attesa lo stato dal vivo; consegnata la risposta, il
            percorso si chiude e resta a disposizione di chi vuole verificarlo. */}
        {message.isStreaming && !message.content ? (
          <Avanzamento thoughts={message.thoughts ?? []} inizio={message.timestamp} />
        ) : message.thoughts && message.thoughts.length > 0 ? (
          <ThinkingTrail thoughts={message.thoughts} durata={message.durata} />
        ) : null}

        {message.content ? (
          <div
            className="prose-legal select-text"
            onClick={gestisciClickCitazione}
            dangerouslySetInnerHTML={{
              __html: marked.parse(inserisciCitazioniInline(message.content, fonti)) as string,
            }}
          />
        ) : null}

        {message.error && (
          <div role="alert" className="mt-4 flex items-start gap-2.5 rounded-xl border border-rosso/40 bg-rosso-2 px-3.5 py-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rosso" strokeWidth={1.75} />
            <div className="min-w-0">
              <div className="mb-0.5 text-[13px] font-semibold text-rosso">
                Consultazione interrotta
              </div>
              <p className="break-words text-[13px] leading-relaxed text-ink">
                {message.error}
              </p>
            </div>
          </div>
        )}

        {!message.isStreaming && message.content && (
          <div className="mt-3 flex flex-col items-start gap-1">
            <div className="flex items-center gap-1">
            <button
              onClick={copia}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] text-ink-3 transition-all duration-200 hover:bg-panel hover:text-ink active:translate-y-px"
            >
              {copiato ? (
                <>
                  <Check className="h-3.5 w-3.5 text-azzurro" strokeWidth={1.75} />
                  <span className="text-azzurro">Copiato</span>
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5" strokeWidth={1.75} />
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
