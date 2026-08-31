import React from 'react';
import { Plus, MessageSquare, PanelLeft, Landmark, FileText, CheckCircle2, ChevronRight, Shield, BookOpen } from 'lucide-react';
import { GraphStats } from '../types';

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  onNewChat: () => void;
  currentTitle: string;
  stats?: GraphStats | null;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onToggle,
  onNewChat,
  currentTitle,
}) => {
  return (
    <aside
      className={`fixed md:static inset-y-0 left-0 z-40 flex flex-col bg-[#070b14] border-r border-[#152035] transition-all duration-300 ease-in-out select-none ${
        isOpen
          ? 'w-64 translate-x-0'
          : '-translate-x-full md:translate-x-0 md:w-0 overflow-hidden border-r-0'
      }`}
    >
      {/* Top action: Nuova consultazione */}
      <div className="p-3 flex items-center justify-between gap-2 border-b border-[#131c30]">
        <button
          onClick={onNewChat}
          className="flex items-center gap-2 flex-1 px-3 py-2 text-sm font-medium bg-[#0f172a] hover:bg-[#16233d] text-[#f8fafc] rounded-xl border border-[#1e2f4f] transition-all duration-150 active:scale-[0.98] shadow-sm"
        >
          <Plus className="w-4 h-4 text-[#38bdf8]" />
          <span>Nuova consultazione</span>
        </button>

        <button
          onClick={onToggle}
          className="p-2 text-[#64748b] hover:text-[#f8fafc] hover:bg-[#0f172a] rounded-xl transition-colors"
          title="Chiudi menu"
        >
          <PanelLeft className="w-4 h-4" />
        </button>
      </div>

      {/* Navigation and chat history */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        <div>
          <div className="px-2 mb-1.5 text-[11px] font-semibold text-[#64748b] uppercase tracking-wider">
            Consultazioni Recenti
          </div>
          <div className="group flex items-center justify-between px-3 py-2 text-sm text-[#f1f5f9] bg-[#0d162a] hover:bg-[#121e38] rounded-xl border border-[#192b4d] transition-colors cursor-pointer">
            <div className="flex items-center gap-2.5 min-w-0">
              <MessageSquare className="w-4 h-4 text-[#38bdf8] shrink-0" />
              <span className="truncate font-normal text-xs">{currentTitle}</span>
            </div>
            <ChevronRight className="w-3.5 h-3.5 text-[#475569] opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        </div>

        {/* Informazioni Istituzionali */}
        <div>
          <div className="px-2 mb-1.5 text-[11px] font-semibold text-[#64748b] uppercase tracking-wider">
            Fonte Ufficiale
          </div>
          <div className="p-3 bg-[#0a1122] rounded-xl border border-[#16243d] space-y-2 text-xs text-[#94a3b8]">
            <div className="flex items-center justify-between">
              <span className="text-[#64748b] flex items-center gap-1.5">
                <Landmark className="w-3.5 h-3.5 text-[#38bdf8]" /> Ente:
              </span>
              <span className="text-[#f8fafc] font-medium text-[11px]">Consiglio G. e G.</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#64748b]">Copertura:</span>
              <span className="text-[#38bdf8] font-medium text-[11px]">Patrimonio Normativo</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#64748b]">Stato Dati:</span>
              <span className="text-emerald-400 font-medium text-[11px] flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Ufficiale & Vigente
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Footer / Garanzia e Tutela Istituzionale */}
      <div className="p-3 border-t border-[#131c30] bg-[#05080f]">
        <div className="text-[10px] text-[#64748b] mb-2 flex items-center justify-between uppercase tracking-wider font-semibold">
          <span className="flex items-center gap-1.5 text-[#38bdf8]">
            <Shield className="w-3.5 h-3.5 text-[#0072ce]" /> CERTIFICAZIONE FONTI
          </span>
          <span className="flex h-2 w-2 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
        </div>
        <div className="p-2.5 bg-[#0b1326] rounded-xl border border-[#16243d] text-[11px] space-y-1.5">
          <div className="text-[#f8fafc] font-medium flex items-center gap-1.5">
            <BookOpen className="w-3.5 h-3.5 text-[#38bdf8]" />
            Archivio Normativo Integrale
          </div>
          <div className="text-[#94a3b8] text-[10px] leading-relaxed">
            Risposte ancorate ai testi ufficiali promulgati dai Capitani Reggenti.
          </div>
        </div>
      </div>
    </aside>
  );
};
