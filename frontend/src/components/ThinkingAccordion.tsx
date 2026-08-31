import React from 'react';
import { ChevronDown, Sparkles, CheckCircle2, Search, BookOpen, Layers, Link2 } from 'lucide-react';
import { ThoughtStep } from '../types';

interface ThinkingAccordionProps {
  thoughts: ThoughtStep[];
  isStreaming?: boolean;
}

function formatToolStep(name: string, args: Record<string, any>) {
  switch (name) {
    case 'cerca_testo':
      return {
        icon: Search,
        title: 'Ricerca archivio',
        detail: args.query ? `"${args.query}"` : 'Ricerca concetti normativi',
      };
    case 'leggi_articolo':
      return {
        icon: BookOpen,
        title: 'Consultazione articolo',
        detail: args.norma_id
          ? `${args.norma_id} • Art. ${args.numero || '1'}`
          : 'Lettura comma per comma',
      };
    case 'struttura_norma':
      return {
        icon: Layers,
        title: 'Analisi struttura atto',
        detail: args.norma_id ? `Indice ${args.norma_id}` : 'Verifica articoli e rubriche',
      };
    case 'trova_norma':
      return {
        icon: Search,
        title: 'Individuazione norma',
        detail: args.titolo || (args.numero && args.anno ? `Atto n.${args.numero}/${args.anno}` : 'Risoluzione estremi'),
      };
    case 'citazioni_da':
    case 'chi_cita':
      return {
        icon: Link2,
        title: 'Verifica rinvii e vigenza',
        detail: args.norma_id ? `Collegamenti di ${args.norma_id}` : 'Rinvii normativi',
      };
    default:
      return {
        icon: Sparkles,
        title: 'Consultazione banca dati',
        detail: 'Elaborazione riferimenti',
      };
  }
}

export const ThinkingAccordion: React.FC<ThinkingAccordionProps> = ({
  thoughts,
  isStreaming,
}) => {
  const callCount = thoughts.filter((t) => t.type === 'call').length;

  return (
    <details className="group border border-[#1a2b47] bg-[#0b1426]/70 rounded-2xl overflow-hidden text-xs transition-all duration-150">
      <summary className="cursor-pointer px-3.5 py-2 flex items-center justify-between text-[#94a3b8] hover:text-[#f1f5f9] select-none transition-colors">
        <div className="flex items-center gap-2">
          <Sparkles className="w-3.5 h-3.5 text-[#38bdf8]" />
          <span className="font-medium text-[#cbd5e1] text-[12px]">
            Consultazione e verifica delle fonti normative
          </span>
          {isStreaming && (
            <span className="flex h-1.5 w-1.5 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-sky-500"></span>
            </span>
          )}
        </div>
        <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180 text-[#64748b]" />
      </summary>

      <div className="px-3.5 py-2.5 border-t border-[#16233b] space-y-2 text-[12px] bg-[#070e1c]">
        {thoughts.map((th, idx) => {
          if (th.type === 'call') {
            const formatted = formatToolStep(th.name, th.args || {});
            const Icon = formatted.icon;
            return (
              <div key={idx} className="flex items-center gap-2 text-[#cbd5e1]">
                <Icon className="w-3.5 h-3.5 text-[#38bdf8] shrink-0" />
                <span className="text-[#f1f5f9] font-medium">{formatted.title}</span>
                <span className="text-[#64748b] text-[11px] truncate">({formatted.detail})</span>
              </div>
            );
          } else {
            return (
              <div key={idx} className="flex items-center gap-1.5 text-emerald-400 text-[11px] pl-5">
                <CheckCircle2 className="w-3 h-3 shrink-0" />
                <span className="text-[#64748b]">
                  Verifica delle disposizioni completata
                </span>
              </div>
            );
          }
        })}
      </div>
    </details>
  );
};
