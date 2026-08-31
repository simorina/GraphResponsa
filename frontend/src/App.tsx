import React, { useState, useEffect } from 'react';
import { PanelLeft, SquarePen, Shield } from 'lucide-react';
import { Sidebar } from './components/Sidebar';
import { MessageList } from './components/MessageList';
import { InputBar } from './components/InputBar';
import { SourceModal } from './components/SourceModal';
import { useChat } from './hooks/useChat';
import { GraphStats, Fonte } from './types';

export function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [selectedSource, setSelectedSource] = useState<Fonte | null>(null);

  const {
    messages,
    input,
    setInput,
    loading,
    sessionTitle,
    sendMessage,
    resetChat,
    stopGeneration,
  } = useChat();

  useEffect(() => {
    fetch('/stato')
      .then((r) => r.json())
      .then((data) => {
        if (data.ok) setStats(data);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="flex h-screen w-full bg-[#060a14] text-[#f1f5f9]">
      {/* Sidebar (Claude / ChatGPT style with San Marino Palette) */}
      <Sidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        onNewChat={resetChat}
        currentTitle={sessionTitle}
        stats={stats}
      />

      {/* Main Chat Canvas */}
      <main className="flex-1 flex flex-col h-full overflow-hidden relative bg-[#080e1c]">
        {/* Top Header */}
        <header className="h-14 border-b border-[#142038] px-4 flex items-center justify-between bg-[#080e1c]/80 backdrop-blur-md z-10 shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="p-1.5 text-[#64748b] hover:text-[#f8fafc] hover:bg-[#111c33] rounded-lg transition-colors"
              title="Menu laterale"
            >
              <PanelLeft className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2.5">
              <span className="font-serif text-lg font-normal tracking-wide text-white">
                Graph<span className="italic text-[#38bdf8]">Responsa</span>
              </span>
              <span className="hidden sm:inline-flex items-center gap-1 px-2.5 py-0.5 text-[10px] font-medium tracking-wide uppercase bg-[#0c162b] text-[#38bdf8] rounded-full border border-[#1b2f54]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#0072ce]"></span>
                Repubblica di San Marino
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={resetChat}
              className="sm:hidden p-1.5 text-[#64748b] hover:text-[#f8fafc] hover:bg-[#111c33] rounded-lg"
              title="Nuova consultazione"
            >
              <SquarePen className="w-5 h-5" />
            </button>
          </div>
        </header>

        {/* Message Stream */}
        <MessageList
          messages={messages}
          onSelectPrompt={(p) => sendMessage(p)}
          onSelectSource={(s) => setSelectedSource(s)}
          loading={loading}
        />

        {/* Floating Input Bar */}
        <InputBar
          input={input}
          onChange={setInput}
          onSubmit={() => sendMessage()}
          onStop={stopGeneration}
          loading={loading}
        />

        {/* Source Drawer / Modal */}
        <SourceModal
          source={selectedSource}
          onClose={() => setSelectedSource(null)}
        />
      </main>
    </div>
  );
}

export default App;
