import React from 'react';
import { Scale, ArrowUpRight, Briefcase, Landmark, Sparkles, History, Shield } from 'lucide-react';

interface EmptyStateProps {
  onSelectPrompt: (prompt: string) => void;
}

const SUGGESTIONS = [
  {
    icon: Briefcase,
    category: 'Diritto del Lavoro',
    title: 'Smart Working & Requisiti',
    desc: 'Quali tutele e obblighi prevede la Legge 202/2020 per il lavoro agile a San Marino?',
    prompt:
      'Quali tutele, dotazioni tecnologiche e regole di recesso prevede la Legge 202/2020 per il lavoro agile a San Marino?',
  },
  {
    icon: Landmark,
    category: 'Diritto Costituzionale',
    title: 'Capitani Reggenti',
    desc: 'Quali sono i requisiti e le incompatibilità nella Legge Costituzionale 185/2005?',
    prompt:
      'Quali sono i requisiti di eleggibilità e le incompatibilità con la carica di Capitano Reggente previsti dalla Legge Costituzionale 185/2005 e Qualificata 186/2005?',
  },
  {
    icon: Sparkles,
    category: 'Impresa & Economia',
    title: 'Giovani Imprenditori',
    desc: 'Quali agevolazioni fiscali e prestiti d\'onore prevede la Legge 178/2015?',
    prompt:
      'Quali agevolazioni, incentivi fiscali (IGR 4%) e prestiti d\'onore prevede la Legge 178/2015 a sostegno dei giovani imprenditori a San Marino?',
  },
  {
    icon: History,
    category: 'Evoluzione Storica',
    title: 'Elettorato Femminile',
    desc: 'Con quale legge storica le donne hanno ottenuto il diritto di voto?',
    prompt:
      'In quale anno e con quale legge storica le donne a San Marino hanno ottenuto per la prima volta l\'estensione del diritto di voto?',
  },
];

export const EmptyState: React.FC<EmptyStateProps> = ({ onSelectPrompt }) => {
  return (
    <div className="pt-8 md:pt-14 text-center space-y-6">
      {/* Stemma Istituzionale */}
      <div className="relative inline-flex items-center justify-center">
        <div className="absolute inset-0 rounded-3xl bg-[#0072ce]/20 blur-xl"></div>
        <div className="relative inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-b from-[#112040] to-[#0a1226] border border-[#1e3a6a] shadow-xl text-[#38bdf8]">
          <Scale className="w-8 h-8" />
        </div>
      </div>

      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#0072ce]/15 border border-[#0072ce]/30 text-xs font-medium text-[#38bdf8]">
          <Shield className="w-3.5 h-3.5 text-[#d4a359]" />
          REPUBBLICA DI SAN MARINO
        </div>

        <h1 className="font-serif text-3xl md:text-5xl text-white font-normal tracking-tight">
          Banca Dati & <span className="italic text-[#38bdf8]">Assistente Giuridico</span>
        </h1>
        <p className="text-sm md:text-base text-[#94a3b8] max-w-xl mx-auto leading-relaxed">
          Consulta il patrimonio normativo sammarinese: leggi ordinarie, decreti delegati, riforme istituzionali e atti ufficiali con risposte motivate e citazioni dirette alle fonti vigenti.
        </p>
      </div>

      {/* Griglia Domande Frequenti */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 pt-6 text-left">
        {SUGGESTIONS.map((s, idx) => {
          const Icon = s.icon;
          return (
            <button
              key={idx}
              onClick={() => onSelectPrompt(s.prompt)}
              className="group p-4 bg-[#0d162a]/70 hover:bg-[#121e38] border border-[#192b4d] hover:border-[#0072ce] rounded-2xl transition-all duration-200 text-left flex flex-col justify-between space-y-2.5 shadow-sm hover:shadow-lg hover:shadow-[#0072ce]/10"
            >
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-mono text-[#38bdf8] uppercase tracking-wider font-medium">
                  {s.category}
                </span>
                <ArrowUpRight className="w-4 h-4 text-[#475569] group-hover:text-[#38bdf8] transition-colors" />
              </div>
              <div className="font-medium text-sm text-[#f1f5f9] group-hover:text-white">
                {s.title}
              </div>
              <div className="text-xs text-[#94a3b8] line-clamp-2 leading-relaxed">{s.desc}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
