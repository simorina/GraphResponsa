import React, { useRef, useEffect } from 'react';
import { ArrowUp, Square, BookOpen } from 'lucide-react';

interface InputBarProps {
  input: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  loading: boolean;
}

export const InputBar: React.FC<InputBarProps> = ({
  input,
  onChange,
  onSubmit,
  onStop,
  loading,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-[#060a14] via-[#060a14]/95 to-transparent pt-6 pb-4 px-4">
      <div className="max-w-2xl mx-auto">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit();
          }}
          className="relative flex flex-col bg-[#0e172a] border border-[#1e2f50] focus-within:border-[#0072ce] focus-within:ring-1 focus-within:ring-[#0072ce]/50 rounded-3xl shadow-xl transition-all duration-200 overflow-hidden"
        >
          {/* Main Textarea */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Poni un quesito giuridico sulla normativa sammarinese..."
            rows={1}
            disabled={loading}
            className="w-full resize-none bg-transparent pt-3.5 pb-2 px-4 text-[#f8fafc] placeholder-[#64748b] text-[15px] focus:outline-none max-h-48 overflow-y-auto"
            style={{ minHeight: '44px' }}
          />

          {/* Bottom Toolbar */}
          <div className="flex items-center justify-between px-3 pb-2.5 pt-1 select-none">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#131f38] border border-[#1e3256] text-[11px] font-medium text-[#38bdf8]">
              <BookOpen className="w-3 h-3 text-[#0072ce]" />
              <span>Archivio Ufficiale (2.444 leggi)</span>
            </div>

            <div>
              {loading ? (
                <button
                  type="button"
                  onClick={onStop}
                  className="w-8 h-8 rounded-full bg-[#1e293b] hover:bg-[#334155] text-white flex items-center justify-center transition-colors shadow-sm"
                  title="Interrompi risposta"
                >
                  <Square className="w-3 h-3 fill-current text-[#38bdf8]" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim()}
                  className="w-8 h-8 rounded-full bg-[#0072ce] hover:bg-[#0284c7] disabled:bg-[#1a263d] text-white disabled:text-[#475569] flex items-center justify-center transition-all disabled:cursor-not-allowed shadow-md disabled:shadow-none active:scale-95"
                  title="Invia quesito"
                >
                  <ArrowUp className="w-4 h-4 stroke-[2.5]" />
                </button>
              )}
            </div>
          </div>
        </form>

        <div className="text-center mt-2.5 text-[11px] text-[#64748b]">
          GraphResponsa è un sistema di supporto all'analisi legale. Si raccomanda di verificare i testi ufficiali pubblicati sul Bollettino Ufficiale.
        </div>
      </div>
    </div>
  );
};
