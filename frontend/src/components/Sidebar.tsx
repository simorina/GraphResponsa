import React from 'react';
import { SquarePen, PanelLeft, LogOut, ArrowUpRight } from 'lucide-react';
import type { StatsState } from '../types';
import type { VoceConversazione, Consumi, Profilo } from '../hooks/useConversazioni';
import { Sigillo } from './Sigillo';
import { esci } from '../auth/cognito';

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  onNewChat: () => void;
  conversazioneAperta: string | null;
  onApri: (id: string) => void;
  voci: VoceConversazione[];
  consumi: Consumi | null;
  utente: Profilo | null;
  caricando: boolean;
  stats: StatsState;
}

const nf = new Intl.NumberFormat('it-IT');

/** "oggi", "ieri", "12 mar" - una data intera occupa spazio e non aggiunge nulla. */
function quando(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  const giorni = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (giorni <= 0) return 'oggi';
  if (giorni === 1) return 'ieri';
  if (giorni < 7) return `${giorni} giorni fa`;
  return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onToggle,
  onNewChat,
  conversazioneAperta,
  onApri,
  voci,
  consumi,
  utente,
  caricando,
  stats,
}) => {
  const d = stats.fase === 'pronto' ? stats.dati : null;
  const quota = consumi ? consumi.richiesteOggi / consumi.limiteGiorno : 0;

  return (
    <aside
      className={`fixed inset-y-0 left-0 z-40 flex h-[100dvh] flex-col border-r border-line bg-panel transition-[width,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] md:static ${
        isOpen
          ? 'w-[272px] translate-x-0'
          : 'w-[272px] -translate-x-full md:w-0 md:translate-x-0 md:overflow-hidden md:border-r-0'
      }`}
    >
      <div className="flex h-full w-[272px] flex-col">
        <div className="flex h-14 shrink-0 items-center justify-between px-3">
          <div className="flex items-center gap-2.5 pl-1.5">
            <Sigillo className="h-[18px] w-[18px]" />
            <span className="text-[13.5px] font-medium tracking-[-0.015em] text-ink">
              Graph<span className="text-azzurro">Responsa</span>
            </span>
          </div>
          <button
            onClick={onToggle}
            className="rounded-lg p-1.5 text-ink-3 transition-colors duration-200 hover:bg-raise hover:text-ink active:translate-y-px"
            title="Nascondi il pannello"
          >
            <PanelLeft className="h-[17px] w-[17px]" strokeWidth={1.5} />
          </button>
        </div>

        <div className="px-3">
          <button
            onClick={onNewChat}
            className="group flex w-full items-center gap-2.5 rounded-xl border border-line bg-canvas px-3 py-2 text-[13.5px] font-medium text-ink shadow-[0_1px_2px_rgba(16,33,45,0.04)] transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:border-dorato-2/60 hover:shadow-[0_2px_8px_rgba(16,33,45,0.08)] active:translate-y-px active:shadow-none"
          >
            <SquarePen
              className="h-[15px] w-[15px] text-dorato transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-px"
              strokeWidth={1.5}
            />
            Nuova consultazione
          </button>
        </div>

        {/* Storico vero, dal grafo delle conversazioni su DynamoDB */}
        <div className="flex-1 overflow-y-auto px-3 py-4">
          {caricando ? (
            <div className="space-y-2 px-1">
              {[82, 64, 71, 58].map((w, i) => (
                <div key={i} className="skeleton h-[13px]" style={{ width: `${w}%` }} />
              ))}
            </div>
          ) : voci.length === 0 ? (
            <p className="px-2 text-[12.5px] leading-relaxed text-ink-3">
              Le consultazioni che apri restano qui, anche dopo aver chiuso il
              browser.
            </p>
          ) : (
            <ul className="space-y-0.5">
              {voci.map((v, i) => {
                const attiva = v.conversazione === conversazioneAperta;
                return (
                  <li key={v.conversazione}>
                    <button
                      onClick={() => onApri(v.conversazione)}
                      className={`slide-in group flex w-full flex-col gap-0.5 rounded-xl px-3 py-2 text-left transition-colors duration-200 ${
                        attiva
                          ? 'border-l-2 border-alloro-2 bg-alloro-3/45'
                          : 'border-l-2 border-transparent hover:bg-raise'
                      }`}
                      style={{ ['--i' as string]: Math.min(i, 10) }}
                    >
                      <span
                        className={`truncate text-[13px] leading-snug ${
                          attiva ? 'text-ink' : 'text-ink-2 group-hover:text-ink'
                        }`}
                      >
                        {v.titolo || 'Consultazione'}
                      </span>
                      <span className="font-mono text-[10px] text-ink-3">
                        {quando(v.aggiornata)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="shrink-0 border-t border-line px-4 py-3.5">
          {/* Quota: compare solo quando comincia a contare davvero. Un contatore
              sempre acceso e' rumore; a due terzi diventa un'informazione. */}
          {consumi && quota > 0.6 && (
            <div className="mb-3">
              <div className="mb-1.5 flex items-baseline justify-between">
                <span className="text-[11.5px] text-ink-2">Consultazioni oggi</span>
                <span className="font-mono text-[11.5px] tabular-nums text-ink">
                  {consumi.richiesteOggi}
                  <span className="text-ink-3">/{consumi.limiteGiorno}</span>
                </span>
              </div>
              <div className="h-[3px] overflow-hidden rounded-full bg-raise-2">
                <div
                  className={`h-full rounded-full transition-[width] duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                    quota > 0.9 ? 'bg-rosso' : 'bg-dorato-2'
                  }`}
                  style={{ width: `${Math.min(100, quota * 100)}%` }}
                />
              </div>
            </div>
          )}

          <div className="mb-3 space-y-[3px]">
            {[
              ['Norme', d?.conTesto],
              ['Articoli', d?.articoli],
              ['Commi', d?.commi],
            ].map(([voce, val]) => (
              <div key={voce as string} className="flex items-baseline justify-between gap-3">
                <span className="text-[11.5px] text-ink-3">{voce}</span>
                {val == null ? (
                  <span className="skeleton h-[10px] w-11" />
                ) : (
                  <span className="font-mono text-[11.5px] tabular-nums text-ink-2">
                    {nf.format(val as number)}
                  </span>
                )}
              </div>
            ))}
          </div>

          <a
            href="https://www.consigliograndeegenerale.sm"
            target="_blank"
            rel="noreferrer"
            className="group inline-flex items-center gap-1 text-[11.5px] text-ink-3 transition-colors duration-200 hover:text-alloro"
          >
            Consiglio Grande e Generale
            <ArrowUpRight
              className="h-3 w-3 shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-px group-hover:translate-x-px"
              strokeWidth={1.5}
            />
          </a>

          {utente && (
            <div className="mt-3.5 flex items-center justify-between gap-2 border-t border-line pt-3">
              <span className="truncate text-[11.5px] text-ink-2" title={utente.email}>
                {utente.email}
              </span>
              <button
                onClick={esci}
                title="Esci"
                className="shrink-0 rounded-lg p-1.5 text-ink-3 transition-colors duration-200 hover:bg-raise hover:text-rosso active:translate-y-px"
              >
                <LogOut className="h-3.5 w-3.5" strokeWidth={1.5} />
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};
