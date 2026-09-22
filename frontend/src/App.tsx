import { useState, useEffect, useCallback } from 'react';
import { PanelLeft, SquarePen } from 'lucide-react';
import { Accesso } from './components/Accesso';
import { configurato, token } from './auth/cognito';
import { Sidebar } from './components/Sidebar';
import { MessageList } from './components/MessageList';
import { InputBar } from './components/InputBar';
import { SourceDrawer } from './components/SourceDrawer';
import { useChat } from './hooks/useChat';
import { useConversazioni, caricaConversazione } from './hooks/useConversazioni';
import { Sigillo } from './components/Sigillo';
import type { StatsState, Fonte } from './types';

type Sessione = 'verifica' | 'dentro' | 'fuori';

// Il segno che in questa sessione del browser l'accesso e' gia' stato chiesto.
const ACCESSO_CHIESTO = 'gr_accesso_chiesto';

export function App() {
  // Su telefono la barra laterale copre la chat: si parte chiusi, e la si apre
  // quando serve. Prima si partiva aperti ovunque, e la prima cosa da fare
  // entrando da telefono era chiuderla.
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);
  const [stats, setStats] = useState<StatsState>({ fase: 'attesa' });
  const [fonteAperta, setFonteAperta] = useState<Fonte | null>(null);
  const [sessione, setSessione] = useState<Sessione>('verifica');

  const { stato: storico, ricarica } = useConversazioni();

  const {
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
  } = useChat();

  // Al caricamento si guarda solo se esiste gia' una sessione valida:
  // non c'e' nessun giro di ritorno da gestire, l'accesso avviene qui dentro.
  //
  // In sviluppo il cancello si vede comunque, una volta per sessione del
  // browser: altrimenti la sessione salvata viene rinnovata in silenzio e non
  // si prova mai il percorso d'accesso, che e' il primo che un utente
  // incontra. I ricaricamenti successivi non richiedono di nuovo le
  // credenziali, perche' sviluppare ricaricando ogni due minuti sarebbe una
  // tortura.
  useEffect(() => {
    let vivo = true;
    (async () => {
      if (!configurato()) {          // sviluppo senza Cognito: nessuna identita'
        if (vivo) setSessione('dentro');
        return;
      }
      if (import.meta.env.DEV && !sessionStorage.getItem(ACCESSO_CHIESTO)) {
        if (vivo) setSessione('fuori');
        return;
      }
      const t = await token();       // rinnova se sta per scadere
      if (vivo) setSessione(t ? 'dentro' : 'fuori');
    })();
    return () => {
      vivo = false;
    };
  }, []);

  useEffect(() => {
    if (sessione !== 'dentro') return;
    const ctrl = new AbortController();
    fetch('/stato', { signal: ctrl.signal })
      .then((r) => r.json())
      .then((d) => setStats(d?.ok ? { fase: 'pronto', dati: d } : { fase: 'errore' }))
      .catch((e) => {
        if (e.name !== 'AbortError') setStats({ fase: 'errore' });
      });
    return () => ctrl.abort();
  }, [sessione]);

  // Lo storico si rilegge quando una consultazione finisce: e' l'unico momento
  // in cui puo' essere cambiato. Un aggiornamento a intervalli sarebbe traffico
  // per niente.
  useEffect(() => {
    if (sessione === 'dentro' && !loading) ricarica();
  }, [sessione, loading, ricarica]);

  const apri = useCallback(async (id: string) => {
    try {
      apriConversazione(id, await caricaConversazione(id));
      if (window.innerWidth < 768) setSidebarOpen(false);
    } catch {
      /* una consultazione non ricostruibile non deve rompere la pagina */
    }
  }, [apriConversazione]);

  const chiudiSidebarSuMobile = useCallback(() => {
    if (window.innerWidth < 768) setSidebarOpen(false);
  }, []);

  if (sessione === 'verifica') {
    return (
      <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-5 bg-canvas">
        <Sigillo className="h-9 w-9" animato />
        <div className="skeleton h-[5px] w-24 rounded-full" />
      </div>
    );
  }

  if (sessione === 'fuori') {
    return (
      <Accesso
        onEntrato={() => {
          sessionStorage.setItem(ACCESSO_CHIESTO, '1');
          setSessione('dentro');
        }}
      />
    );
  }

  return (
    <div className="flex h-[100dvh] w-full overflow-hidden bg-canvas">
      <Sidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen((v) => !v)}
        onNewChat={resetChat}
        conversazioneAperta={conversazione || null}
        onApri={apri}
        voci={storico.fase === 'pronto' ? storico.voci : []}
        consumi={storico.fase === 'pronto' ? storico.consumi : null}
        utente={storico.fase === 'pronto' ? storico.utente : null}
        caricando={storico.fase === 'attesa'}
        stats={stats}
      />

      {sidebarOpen && (
        <button
          aria-label="Chiudi il menu"
          onClick={() => setSidebarOpen(false)}
          className="veil-in fixed inset-0 z-30 bg-ink/20 backdrop-blur-[2px] md:hidden"
        />
      )}

      <main className="relative flex h-full min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between border-b border-line bg-canvas/85 px-4 backdrop-blur-md md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              onClick={() => setSidebarOpen((v) => !v)}
              className="-ml-1.5 rounded-lg p-1.5 text-ink-2 transition-colors duration-200 hover:bg-panel hover:text-ink active:translate-y-px"
              title={sidebarOpen ? 'Nascondi il pannello' : 'Mostra il pannello'}
              aria-label={sidebarOpen ? 'Nascondi il pannello' : 'Mostra il pannello'}
            >
              <PanelLeft className="h-[18px] w-[18px]" strokeWidth={1.75} />
            </button>

            <div className="flex min-w-0 items-center gap-2.5 md:hidden">
              <Sigillo className="h-[17px] w-[17px]" />
              <span className="text-[14.5px] font-semibold tracking-[-0.015em] text-ink">
                Responsa
              </span>
            </div>

            {/* Su schermo largo, di cosa si sta parlando: con piu' consultazioni
                aperte nella giornata, e' la prima cosa che si cerca. */}
            {messages.length > 0 && (
              <span className="hidden min-w-0 truncate text-[14px] font-medium text-ink md:block" title={sessionTitle}>
                {sessionTitle}
              </span>
            )}

          </div>

          <button
            onClick={resetChat}
            className="rounded-lg p-1.5 text-ink-2 transition-colors duration-200 hover:bg-panel hover:text-ink active:translate-y-px md:hidden"
            title="Nuova consultazione"
            aria-label="Nuova consultazione"
          >
            <SquarePen className="h-[18px] w-[18px]" strokeWidth={1.75} />
          </button>
        </header>

        <MessageList
          messages={messages}
          onSelectPrompt={(p) => {
            chiudiSidebarSuMobile();
            sendMessage(p);
          }}
          onSelectSource={setFonteAperta}
          loading={loading}
          conversazione={conversazione || null}
        />

        <InputBar
          input={input}
          onChange={setInput}
          onSubmit={() => sendMessage()}
          onStop={stopGeneration}
          loading={loading}
          stats={stats}
        />
      </main>

      <SourceDrawer source={fonteAperta} onClose={() => setFonteAperta(null)} />
    </div>
  );
}

export default App;
