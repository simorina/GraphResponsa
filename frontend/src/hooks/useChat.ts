import { useState, useRef } from 'react';
import { Message, Fonte } from '../types';
import { token } from '../auth/cognito';

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversazione, setConversazione] = useState<string>(
    () => localStorage.getItem('gr_conv_id') || ''
  );
  const [sessionTitle, setSessionTitle] = useState('Nuova consultazione');

  const abortControllerRef = useRef<AbortController | null>(null);

  const resetChat = () => {
    if (loading && abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setMessages([]);
    setInput('');
    setLoading(false);
    setConversazione('');
    localStorage.removeItem('gr_conv_id');
    setSessionTitle('Nuova consultazione');
  };

  /** Riapre una consultazione passata: i messaggi arrivano dal checkpoint. */
  const apriConversazione = (id: string, messaggi: {role:'user'|'assistant'; content:string; fonti?: Fonte[]}[]) => {
    if (loading && abortControllerRef.current) abortControllerRef.current.abort();
    setMessages(messaggi.map((m) => ({ ...m, fonti: m.fonti ?? [], isStreaming: false })));
    setConversazione(id);
    localStorage.setItem('gr_conv_id', id);
    const prima = messaggi.find((m) => m.role === 'user')?.content ?? 'Consultazione';
    setSessionTitle(prima.length > 35 ? prima.slice(0, 35) + '…' : prima);
    setLoading(false);
  };

  const stopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setLoading(false);
  };

  const sendMessage = async (textToSend?: string) => {
    const query = (textToSend || input).trim();
    if (!query || loading) return;

    setInput('');

    // User Message
    const userMsg: Message = {
      role: 'user',
      content: query,
      timestamp: new Date(),
    };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);

    if (messages.length === 0) {
      const title = query.length > 35 ? query.substring(0, 35) + '...' : query;
      setSessionTitle(title);
    }

    // Assistant Message Placeholder
    const assistantIndex = newMessages.length;
    const assistantMsg: Message = {
      role: 'assistant',
      content: '',
      thoughts: [],
      fonti: [],
      fine: null,
      error: null,
      isStreaming: true,
    };
    setMessages([...newMessages, assistantMsg]);
    setLoading(true);

    abortControllerRef.current = new AbortController();

    try {
      // Senza il token il backend risponde 401 e non chiama Anthropic: e' cio'
      // che impedisce a un estraneo di spendere la chiave dell'esercente.
      const t = await token();
      const response = await fetch('/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(t ? { Authorization: `Bearer ${t}` } : {}),
        },
        body: JSON.stringify({
          domanda: query,
          conversazione: conversazione || null,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        // 429 non e' un guasto: e' il tetto di spesa o di frequenza che scatta,
        // e il messaggio del server spiega quale. Va mostrato com'e'.
        if (response.status === 429 || response.status === 403) {
          const d = await response.json().catch(() => null);
          throw new Error(d?.detail || 'Limite raggiunto.');
        }
        if (response.status === 401) {
          throw new Error('Sessione scaduta. Ricarica la pagina per rientrare.');
        }
        throw new Error(`Il server ha risposto ${response.status}.`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('Readable stream not available');

      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;

          const jsonStr = trimmed.replace(/^data:\s*/, '');
          if (!jsonStr) continue;

          try {
            const event = JSON.parse(jsonStr);

            setMessages((prev) => {
              const updated = [...prev];
              const current = { ...updated[assistantIndex] };

              if (event.tipo === 'testo') {
                current.content = (current.content || '') + event.testo;
              } else if (event.tipo === 'strumento') {
                current.thoughts = [
                  ...(current.thoughts || []),
                  {
                    type: 'call',
                    name: event.nome,
                    args: event.argomenti,
                    time: new Date(),
                  },
                ];
              } else if (event.tipo === 'risultato') {
                current.thoughts = [
                  ...(current.thoughts || []),
                  {
                    type: 'result',
                    name: event.nome,
                    count: event.quante,
                    error: event.errore,
                  },
                ];
              } else if (event.tipo === 'fonti') {
                current.fonti = event.fonti || [];
              } else if (event.tipo === 'fine') {
                current.fine = event;
                current.isStreaming = false;
                if (event.conversazione) {
                  setConversazione(event.conversazione);
                  localStorage.setItem('gr_conv_id', event.conversazione);
                }
              } else if (event.tipo === 'errore') {
                current.error = event.messaggio;
                current.isStreaming = false;
              }

              updated[assistantIndex] = current;
              return updated;
            });
          } catch (e) {
            console.error('JSON parse error:', e);
          }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setMessages((prev) => {
          const updated = [...prev];
          if (updated[assistantIndex]) {
            updated[assistantIndex].error = err.message || 'Errore di connessione';
            updated[assistantIndex].isStreaming = false;
          }
          return updated;
        });
      }
    } finally {
      setLoading(false);
      setMessages((prev) => {
        const updated = [...prev];
        if (updated[assistantIndex]) {
          updated[assistantIndex].isStreaming = false;
        }
        return updated;
      });
    }
  };

  return {
    apriConversazione,
    conversazione,
    messages,
    input,
    setInput,
    loading,
    sessionTitle,
    sendMessage,
    resetChat,
    stopGeneration,
  };
}
