import React, { useState } from 'react';
import { Sparkles, Bookmark, Copy, Check, AlertCircle, ThumbsUp, ThumbsDown } from 'lucide-react';
import { marked } from 'marked';
import { Message, Fonte } from '../types';
import { ThinkingAccordion } from './ThinkingAccordion';

interface MessageItemProps {
  message: Message;
  index: number;
  onSelectSource: (source: Fonte) => void;
}

export const MessageItem: React.FC<MessageItemProps> = ({
  message,
  index,
  onSelectSource,
}) => {
  const [copied, setCopied] = useState(false);
  const [liked, setLiked] = useState<'up' | 'down' | null>(null);

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (message.role === 'user') {
    return (
      <div className="flex justify-end py-1">
        <div className="max-w-[80%] bg-[#0e1f3d] text-[#f8fafc] px-4 py-2.5 rounded-3xl rounded-tr-md shadow-sm border border-[#1d3560] text-[15px] leading-relaxed">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-4 py-2 group">
      {/* Institutional Assistant Avatar */}
      <div className="w-8 h-8 rounded-xl bg-gradient-to-b from-[#112244] to-[#0a1426] border border-[#1e3a6a] flex items-center justify-center text-[#38bdf8] shrink-0 mt-0.5 shadow-sm">
        <Sparkles className="w-4 h-4" />
      </div>

      <div className="flex-1 space-y-3.5 min-w-0">
        {/* Reasoning / Consultation Accordion */}
        {message.thoughts && message.thoughts.length > 0 && (
          <ThinkingAccordion
            thoughts={message.thoughts}
            isStreaming={message.isStreaming}
          />
        )}

        {/* Markdown Content */}
        {message.content ? (
          <div
            className="prose-legal"
            dangerouslySetInnerHTML={{
              __html: marked.parse(message.content) as string,
            }}
          />
        ) : message.isStreaming ? (
          <div className="flex items-center gap-2 text-sm text-[#94a3b8] italic py-1">
            <span className="inline-block w-2 h-2 rounded-full bg-[#38bdf8] animate-ping"></span>
            Elaborazione della risposta sulla base della normativa vigente...
          </div>
        ) : null}

        {/* Error Notification */}
        {message.error && (
          <div className="p-3.5 bg-red-950/40 border border-red-800/60 rounded-2xl text-red-200 text-xs flex items-start gap-2.5 shadow-sm">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-red-400" />
            <div>{message.error}</div>
          </div>
        )}

        {/* Citation Pills / Fonti Ufficiali */}
        {message.fonti && message.fonti.length > 0 && (
          <div className="pt-2 border-t border-[#16233b] space-y-2">
            <div className="text-[11px] font-semibold text-[#64748b] uppercase tracking-wider flex items-center gap-1.5">
              <Bookmark className="w-3 h-3 text-[#38bdf8]" />
              <span>Disposizioni e articoli citati</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {message.fonti.slice(0, 10).map((f, fIdx) => (
                <button
                  key={fIdx}
                  onClick={() => onSelectSource(f)}
                  className="px-2.5 py-1 text-xs bg-[#0b1426] hover:bg-[#12203d] border border-[#1b2f52] hover:border-[#0072ce] text-[#38bdf8] rounded-xl transition-all flex items-center gap-1.5 shadow-sm hover:shadow-md"
                >
                  <span className="font-mono font-medium">{f.norma}</span>
                  <span className="text-[#94a3b8]">
                    Art. {f.articolo} c.{f.comma}
                  </span>
                </button>
              ))}
              {message.fonti.length > 10 && (
                <span className="text-xs text-[#64748b] self-center">
                  altri riferimenti
                </span>
              )}
            </div>
          </div>
        )}

        {/* Action Toolbar without developer token/cost stats */}
        {!message.isStreaming && message.content && (
          <div className="pt-1 flex items-center justify-end text-xs text-[#64748b] select-none">
            <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
              <button
                onClick={handleCopy}
                className="p-1.5 hover:bg-[#11192e] text-[#94a3b8] hover:text-[#f8fafc] rounded-lg transition-colors flex items-center gap-1 text-[11px]"
                title="Copia testo"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-emerald-400">Copiato</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>Copia</span>
                  </>
                )}
              </button>

              <button
                onClick={() => setLiked(liked === 'up' ? null : 'up')}
                className={`p-1.5 hover:bg-[#11192e] rounded-lg transition-colors ${liked === 'up' ? 'text-[#38bdf8]' : 'text-[#94a3b8] hover:text-[#f8fafc]'}`}
                title="Risposta utile"
              >
                <ThumbsUp className="w-3.5 h-3.5" />
              </button>

              <button
                onClick={() => setLiked(liked === 'down' ? null : 'down')}
                className={`p-1.5 hover:bg-[#11192e] rounded-lg transition-colors ${liked === 'down' ? 'text-red-400' : 'text-[#94a3b8] hover:text-[#f8fafc]'}`}
                title="Risposta non utile"
              >
                <ThumbsDown className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
