import { useState, useEffect, useCallback } from 'react';
import { PanelLeft, SquarePen } from 'lucide-react';
import { Accesso } from './components/Accesso';
import { autenticato, configurato, token } from './auth/cognito';
import { Sidebar } from './components/Sidebar';
import { MessageList } from './components/MessageList';
import { InputBar } from './components/InputBar';
import { SourceDrawer } from './components/SourceDrawer';
import { useChat } from './hooks/useChat';
import { useChiusuraIndietro, useSchermoStretto } from './hooks/useMobile';
import { mostraTema, temaSalvato } from './tema';
import { useConversazioni, caricaConversazione } from './hooks/useConversazioni';
import { Sigillo } from './components/Sigillo';
import type { StatsState, Fonte } from './types';

type Sessione = 'verifica' | 'dentro' | 'fuori';

// Il segno che in questa sessione del browser l'accesso e' gia' stato chiesto.
const ACCESSO_CHIESTO = 'gr_accesso_chiesto';

export function App() {
  const stretto = useSchermoStretto();
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
      // Senza rete il rinnovo non riesce ma la sessione resta salvata: si
      // entra lo stesso, e le richieste ripartono quando la rete torna.
      // Mostrare l'accesso sarebbe falso - si e' gia' dentro - e inutile,
      // perche' senza rete non si accede comunque.
      if (vivo) setSessione(t || autenticato() ? 'dentro' : 'fuori');
    })();
    return () => {
      vivo = false;
    };
  }, []);

  // La pagina d'accesso e' sempre chiara; dentro l'app vale il tema scelto.
  // Serve anche qui e non solo in index.html: la sessione salvata puo'
  // rivelarsi scaduta (rinnovo rifiutato) e si finisce sull'accesso dopo che
  // lo scuro era gia' stato messo.
  useEffect(() => {
    if (sessione === 'fuori') mostraTema('chiaro');
    else if (sessione === 'dentro') mostraTema(temaSalvato());
  }, [sessione]);

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
      if (stretto) setSidebarOpen(false);
    } catch {
      /* una consultazione non ricostruibile non deve rompere la pagina */
    }
  }, [apriConversazione, stretto]);

  const chiudiSidebarSuMobile = useCallback(() => {
    if (stretto) setSidebarOpen(false);
  }, [stretto]);

  // Il tasto indietro chiude il pannello che copre la chat, e solo quando la
  // copre davvero: da tablet in su sta accanto e non c'e' nulla da chiudere.
  useChiusuraIndietro(stretto && sidebarOpen, chiudiSidebarSuMobile);

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
          className="veil-in fixed inset-0 z-30 bg-velo/40 md:hidden"
        />
      )}

      <main className="relative flex h-full min-w-0 flex-1 flex-col">
        {/* Sul telefono, come nell'app di Claude: il menu a sinistra, al
            centro di cosa si sta parlando (il nome, a pagina vuota), a destra
            la nuova consultazione. Niente filetto: la testata sta fuori
            dall'area che scorre, e non c'e' niente da separare. I bordi di
            sicurezza valgono anche di lato: col telefono in orizzontale il
            notch sta a sinistra e si mangerebbe il primo pulsante. */}
        <header className="sticky top-0 z-20 grid h-14 shrink-0 grid-cols-[2.75rem_minmax(0,1fr)_2.75rem] items-center gap-2 bg-canvas pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] md:flex md:justify-between md:gap-0 md:border-b md:border-line md:bg-canvas/85 md:px-6 md:backdrop-blur-md">
          <div className="flex min-w-0 items-center gap-3">
            {/* A barra aperta, sul desktop, il comando per chiuderla sta gia'
                nella barra stessa: qui ne compariva un secondo identico, a un
                palmo dal primo. Come in Claude, la testata lo mostra solo a
                barra chiusa, per riaprirla. Sul telefono resta sempre: la
                barra copre la pagina, e da chiusa questo e' l'unico modo di
                aprirla. */}
            <button
              onClick={() => setSidebarOpen((v) => !v)}
              className={`-ml-1.5 flex h-11 w-11 items-center justify-center rounded-lg text-ink-2 transition-colors duration-200 hover:bg-panel hover:text-ink active:translate-y-px sm:h-9 sm:w-9 ${
                sidebarOpen ? 'md:hidden' : ''
              }`}
              title={sidebarOpen ? 'Nascondi il pannello' : 'Mostra il pannello'}
              aria-label={sidebarOpen ? 'Nascondi il pannello' : 'Mostra il pannello'}
            >
              <PanelLeft className="h-[18px] w-[18px]" strokeWidth={1.75} />
            </button>

            {/* Su schermo largo, di cosa si sta parlando: con piu' consultazioni
                aperte nella giornata, e' la prima cosa che si cerca. */}
            {messages.length > 0 && (
              <span className="hidden min-w-0 truncate text-[14px] font-medium text-ink md:block" title={sessionTitle}>
                {sessionTitle}
              </span>
            )}

          </div>

          <div className="flex min-w-0 items-center justify-center gap-2 md:hidden">
            {messages.length > 0 ? (
              <span className="truncate text-[15px] font-semibold tracking-[-0.01em] text-ink" title={sessionTitle}>
                {sessionTitle}
              </span>
            ) : (
              <>
                <Sigillo className="h-[18px] w-[18px]" />
                <span className="text-[15.5px] font-semibold tracking-[-0.015em] text-ink">
                  Responsa
                </span>
              </>
            )}
          </div>

          <button
            onClick={resetChat}
            className="-mr-1.5 flex h-11 w-11 items-center justify-center justify-self-end rounded-lg text-ink-2 transition-colors duration-200 hover:bg-panel hover:text-ink active:translate-y-px md:hidden"
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
          nomeUtente={storico.fase === 'pronto' ? storico.utente?.nome ?? null : null}
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
