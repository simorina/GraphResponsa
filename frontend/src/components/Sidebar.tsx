import React, { useEffect, useState } from 'react';
import { SquarePen, PanelLeft, LogOut, ArrowUpRight } from 'lucide-react';
import type { StatsState } from '../types';
import type { VoceConversazione, Consumi, Profilo } from '../hooks/useConversazioni';
import { Sigillo } from './Sigillo';
import { esci } from '../auth/cognito';

/**
 * Quanto manca, in forma breve: "3g 4h", "4h 12m", "38m".
 *
 * Un istante gia' passato non e' un errore: il contatore si azzera al primo
 * messaggio dopo la mezzanotte, non alla mezzanotte esatta, e fra i due
 * momenti la pagina mostrerebbe un tempo negativo.
 */
function mancante(iso: string, adesso: number): string {
  const ms = new Date(iso).getTime() - adesso;
  if (!isFinite(ms) || ms <= 0) return 'a momenti';
  const minuti = Math.floor(ms / 60_000);
  const giorni = Math.floor(minuti / 1440);
  const ore = Math.floor((minuti % 1440) / 60);
  if (giorni > 0) return `${giorni}g ${ore}h`;
  if (ore > 0) return `${ore}h ${minuti % 60}m`;
  return `${minuti}m`;
}

/** Una delle due barre di consumo: nome e valore in alto, la barra, e sotto
 *  quando riparte.
 *
 *  Il valore lo decide chi la usa perche' le due barre misurano cose diverse:
 *  i messaggi si contano ("12/50", e sapere che ne restano 38 e' cio' che
 *  serve), la spesa si guarda in proporzione al tetto - la cifra esatta in
 *  dollari non direbbe niente a chi non sa quanto costa una domanda. */
const Barra: React.FC<{
  nome: string;
  valore: string;
  frazione: number;
  riparte: string;
}> = ({ nome, valore, frazione, riparte }) => {
  const pieno = Math.min(1, Math.max(0, frazione)) || 0;
  return (
    <div className="mb-3">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-[12.5px] font-medium text-ink-2">{nome}</span>
        <span className="font-mono text-[12.5px] font-medium tabular-nums text-ink">{valore}</span>
      </div>
      <div className="h-[5px] overflow-hidden rounded-full bg-raise-2">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
            pieno > 0.9 ? 'bg-rosso' : pieno > 0.7 ? 'bg-dorato' : 'bg-azzurro'
          }`}
          style={{ width: `${pieno * 100}%` }}
        />
      </div>
      <div className="mt-1 text-[11.5px] text-ink-3">riparte fra {riparte}</div>
    </div>
  );
};

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

  // L'orologio avanza da solo: il server manda l'istante dell'azzeramento, non
  // quanto manca, perche' una durata calcolata la' invecchia mentre si guarda
  // la pagina. Mezzo minuto basta: si mostrano i minuti.
  const [adesso, setAdesso] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setAdesso(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

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
            <span className="text-[14.5px] font-semibold tracking-[-0.015em] text-ink">
              Responsa
            </span>
          </div>
          <button
            onClick={onToggle}
            className="rounded-lg p-1.5 text-ink-2 transition-colors duration-200 hover:bg-raise hover:text-ink active:translate-y-px"
            title="Nascondi il pannello"
            aria-label="Nascondi il pannello"
          >
            <PanelLeft className="h-[17px] w-[17px]" strokeWidth={1.75} />
          </button>
        </div>

        <div className="px-3">
          <button
            onClick={onNewChat}
            className="group flex w-full items-center gap-2.5 rounded-xl border border-line-2 bg-canvas px-3 py-2.5 text-[14px] font-semibold text-ink shadow-[0_1px_2px_rgba(12,27,38,0.06)] transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:border-azzurro hover:shadow-[0_3px_10px_-2px_rgba(12,27,38,0.12)] active:translate-y-px active:shadow-none"
          >
            <SquarePen
              className="h-4 w-4 text-azzurro transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-px"
              strokeWidth={1.75}
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
            <p className="px-2 text-[13px] leading-relaxed text-ink-2">
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
                          ? 'border-l-[3px] border-azzurro bg-canvas shadow-[0_1px_3px_rgba(12,27,38,0.08)]'
                          : 'border-l-[3px] border-transparent hover:bg-raise'
                      }`}
                      style={{ ['--i' as string]: Math.min(i, 10) }}
                    >
                      <span
                        className={`truncate text-[13.5px] leading-snug ${
                          attiva ? 'font-semibold text-ink' : 'text-ink-2 group-hover:text-ink'
                        }`}
                      >
                        {v.titolo || 'Consultazione'}
                      </span>
                      <span className="font-mono text-[11px] text-ink-3">
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
          {/* I due tetti, sempre visibili: misurano cose diverse e nessuno dei
              due implica l'altro. Una domanda che costringe l'agente a otto
              ricerche resta un messaggio solo ma spende otto volte i token,
              quindi si puo' finire la spesa del mese con la giornata ancora
              quasi intatta - e senza entrambe le barre non si capirebbe
              perche' il servizio si e' fermato. */}
          {consumi && (
            <div className="mb-3">
              <Barra
                nome="Consultazioni giornaliere"
                valore={`${consumi.richiesteOggi}/${consumi.limiteGiorno}`}
                frazione={consumi.richiesteOggi / consumi.limiteGiorno}
                riparte={mancante(consumi.azzeraGiorno, adesso)}
              />
              <Barra
                nome="Consumo mensile"
                valore={`${Math.round(
                  Math.min(1, consumi.costoMese / consumi.limiteMese || 0) * 100
                )}%`}
                frazione={consumi.costoMese / consumi.limiteMese}
                riparte={mancante(consumi.azzeraMese, adesso)}
              />
            </div>
          )}

          <div className="mb-3 space-y-[3px]">
            {[
              ['Norme', d?.conTesto],
              ['Articoli', d?.articoli],
              ['Commi', d?.commi],
            ].map(([voce, val]) => (
              <div key={voce as string} className="flex items-baseline justify-between gap-3">
                <span className="text-[12px] text-ink-3">{voce}</span>
                {val == null ? (
                  <span className="skeleton h-[10px] w-11" />
                ) : (
                  <span className="font-mono text-[12px] tabular-nums text-ink-2">
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
            className="group inline-flex items-center gap-1 text-[12px] text-ink-2 transition-colors duration-200 hover:text-azzurro"
          >
            Consiglio Grande e Generale
            <ArrowUpRight
              className="h-3 w-3 shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-px group-hover:translate-x-px"
              strokeWidth={1.75}
            />
          </a>

          {utente && (
            <div className="mt-3.5 flex items-center justify-between gap-2 border-t border-line pt-3">
              <span className="truncate text-[12.5px] font-medium text-ink-2" title={utente.email}>
                {utente.email}
              </span>
              <button
                onClick={esci}
                title="Esci"
                aria-label="Esci"
                className="shrink-0 rounded-lg p-1.5 text-ink-2 transition-colors duration-200 hover:bg-rosso-2 hover:text-rosso active:translate-y-px"
              >
                <LogOut className="h-4 w-4" strokeWidth={1.75} />
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};
