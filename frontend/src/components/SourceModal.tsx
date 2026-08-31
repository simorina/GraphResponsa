import React from 'react';
import { FileText, X } from 'lucide-react';
import { Fonte } from '../types';

interface SourceModalProps {
  source: Fonte | null;
  onClose: () => void;
}

export const SourceModal: React.FC<SourceModalProps> = ({ source, onClose }) => {
  if (!source) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#0b1326] border border-[#1e345b] rounded-2xl max-w-2xl w-full max-h-[80vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Modal Header */}
        <div className="p-4 border-b border-[#16233d] flex items-center justify-between bg-[#080e1c]">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-[#38bdf8]" />
            <span className="font-mono text-sm font-semibold text-white">{source.norma}</span>
            <span className="text-xs text-[#94a3b8]">
              • Art. {source.articolo}, Comma {source.comma}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-[#131e36] text-[#94a3b8] hover:text-white rounded-lg transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto space-y-4">
          {source.titoloNorma && (
            <div className="text-xs font-semibold uppercase tracking-wider text-[#38bdf8]">
              {source.titoloNorma}
            </div>
          )}
          {source.rubrica && (
            <div className="text-sm font-medium text-white pb-2 border-b border-[#16233d]">
              Rubrica: {source.rubrica}
            </div>
          )}
          <div className="font-serif text-base text-[#f1f5f9] leading-relaxed whitespace-pre-wrap bg-[#060a14] p-4 rounded-xl border border-[#15233d]">
            {source.testo}
          </div>
        </div>

        {/* Modal Footer */}
        <div className="p-3.5 border-t border-[#16233d] bg-[#080e1c] flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-[#142038] hover:bg-[#1d2d4d] border border-[#223354] text-sm text-[#f1f5f9] rounded-xl transition-colors font-medium"
          >
            Chiudi
          </button>
        </div>
      </div>
    </div>
  );
};
