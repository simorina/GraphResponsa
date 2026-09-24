import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDown } from 'lucide-react';
import type { Message, Fonte } from '../types';
import { MessageItem } from './MessageItem';
import { EmptyState } from './EmptyState';

interface MessageListProps {
  messages: Message[];
  onSelectPrompt: (prompt: string) => void;
  onSelectSource: (source: Fonte) => void;
  loading: boolean;
  conversazione: string | null;
}

/**
 * Quanto si puo' stare staccati dal fondo continuando a considerarsi "in
 * fondo". Un margine serve: mentre la risposta cresce, il fondo si sposta di
 * qualche pixel per conto suo.
 */
const A_FONDO = 130;

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  onSelectPrompt,
  onSelectSource,
  loading,
  conversazione,
}) => {
  const scatolaRef = useRef<HTMLDivElement>(null);
  const fondoRef = useRef<HTMLDivElement>(null);
  const [aFondo, setAFondo] = useState(true);
  const vuoto = messages.length === 0;

  const scendi = useCallback((liscio = true) => {
    fondoRef.current?.scrollIntoView({
      behavior: liscio ? 'smooth' : 'auto',
      block: 'end',
    });
  }, []);

  // Si guarda dove sta l'occhio, non dove sta il testo. Il listener e'
  // passivo: dichiarare che non si chiama preventDefault lascia al browser lo
  // scorrimento sul filo del dito, senza aspettare noi.
  useEffect(() => {
    const el = scatolaRef.current;
    if (!el) return;
    const guarda = () => {
      const distanza = el.scrollHeight - el.scrollTop - el.clientHeight;
      setAFondo(distanza < A_FONDO);
    };
    guarda();
    el.addEventListener('scroll', guarda, { passive: true });
    return () => el.removeEventListener('scroll', guarda);
  }, [vuoto]);

  /**
   * Si scende da soli solo se l'occhio era gia' in fondo.
   *
   * Prima si scendeva a ogni evento, sempre. Su telefono era la cosa peggiore
   * dell'interfaccia: mentre la risposta si scriveva, chi tornava indietro a
   * rileggere un comma veniva strappato in fondo dopo un istante, e non c'era
   * modo di leggere fino alla fine. L'eccezione e' la domanda appena inviata:
   * quella va vista, e chi l'ha scritta si aspetta di finire in fondo.
   */
  useEffect(() => {
    if (vuoto) return;
    const miaDomanda = messages[messages.length - 1]?.role === 'user';
    if (miaDomanda || aFondo) scendi(!miaDomanda);
    // `aFondo` di proposito NON e' fra le dipendenze: deve decidere al momento
    // dell'evento, non far scattare una discesa quando cambia da solo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, loading, vuoto, scendi]);

  /**
   * Quando la tastiera sale, la finestra si accorcia sotto ai piedi della
   * lista: l'ultimo messaggio finisce dietro ai tasti, e chi scrive perde di
   * vista proprio la riga a cui sta rispondendo. `interactive-widget` nel
   * viewport fa accorciare la pagina invece di farla scorrere sotto, ma non
   * riporta nessuno in fondo: quello tocca a noi, e solo se in fondo ci si
   * era. Il salto e' secco, non liscio: la tastiera e' gia' un movimento, e
   * due movimenti insieme si leggono come uno scatto.
   */
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv || vuoto) return;
    const risali = () => {
      const el = scatolaRef.current;
      if (!el) return;
      if (el.scrollHeight - el.scrollTop - el.clientHeight < A_FONDO) scendi(false);
    };
    vv.addEventListener('resize', risali);
    return () => vv.removeEventListener('resize', risali);
  }, [vuoto, scendi]);

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scatolaRef}
        className="h-full overflow-y-auto overscroll-contain pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] md:px-6"
      >
        <div className="mx-auto max-w-3xl pb-56 pt-4 md:pb-44">
          {vuoto ? (
            <EmptyState onSelectPrompt={onSelectPrompt} />
          ) : (
            <div className="space-y-3">
              {messages.map((msg, index) => (
                <MessageItem
                  key={index}
                  message={msg}
                  indice={index}
                  domandaPrecedente={messages[index - 1]?.content ?? ''}
                  conversazione={conversazione}
                  onSelectSource={onSelectSource}
                />
              ))}
            </div>
          )}
          <div ref={fondoRef} className="h-px" />
        </div>
      </div>

      {/* Il ritorno in fondo, solo quando si e' risaliti. Sta sopra l'area di
          scrittura e sotto il pollice, dove la mano gia' e'. */}
      {!vuoto && !aFondo && (
        <button
          onClick={() => scendi()}
          className="frase-in absolute bottom-[calc(7.5rem+env(safe-area-inset-bottom))] left-1/2 z-20 flex h-10 -translate-x-1/2 items-center gap-1.5 rounded-full border border-line-2 bg-canvas px-4 text-[13px] font-medium text-ink shadow-[0_10px_28px_-12px_rgba(12,27,38,0.4)] transition-transform duration-200 active:scale-[0.96] md:bottom-[7rem]"
          aria-label="Torna in fondo alla conversazione"
        >
          <ArrowDown className="h-4 w-4" strokeWidth={2} />
          {loading ? 'Sta rispondendo' : 'Torna in fondo'}
        </button>
      )}
    </div>
  );
};
