import React, { useRef, useState } from 'react';
import { ArrowRight, AlertTriangle, Eye, EyeOff, KeyRound } from 'lucide-react';
import { Sigillo } from './Sigillo';
import {
  accedi,
  impostaNuovaPassword,
  ErroreAccesso,
  type NuovaPasswordRichiesta,
} from '../auth/cognito';

interface AccessoProps {
  onEntrato: () => void;
}

const classiInput =
  'w-full rounded-xl border border-line bg-canvas px-3.5 py-2.5 text-[14px] text-ink ' +
  'placeholder-ink-3 transition-colors duration-200 focus:border-azzurro focus:outline-none ' +
  'disabled:opacity-60';

const Campo: React.FC<{
  id: string;
  etichetta: string;
  aiuto?: string;
  children: React.ReactNode;
}> = ({ id, etichetta, aiuto, children }) => (
  <div className="flex flex-col gap-2">
    <label htmlFor={id} className="text-[12.5px] font-medium text-ink">
      {etichetta}
    </label>
    {children}
    {aiuto && <p className="text-[11.5px] leading-relaxed text-ink-3">{aiuto}</p>}
  </div>
);

export const Accesso: React.FC<AccessoProps> = ({ onEntrato }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [nuova, setNuova] = useState('');
  const [conferma, setConferma] = useState('');
  const [mostra, setMostra] = useState(false);
  const [sfida, setSfida] = useState<NuovaPasswordRichiesta | null>(null);
  const [errore, setErrore] = useState<string | null>(null);
  const [inCorso, setInCorso] = useState(false);

  const pannello = useRef<HTMLDivElement>(null);

  /** Le coordinate del puntatore finiscono in due variabili CSS, non nello
   *  stato di React: aggiornare lo stato a ogni movimento del mouse
   *  ridisegnerebbe il modulo decine di volte al secondo. */
  const seguiPuntatore = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = pannello.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty('--x', `${e.clientX - r.left}px`);
    el.style.setProperty('--y', `${e.clientY - r.top}px`);
  };

  const invia = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrore(null);

    if (sfida) {
      if (nuova !== conferma) return setErrore('Le due password non coincidono.');
      if (nuova.length < 12) return setErrore('La password deve avere almeno 12 caratteri.');
      setInCorso(true);
      try {
        await impostaNuovaPassword(sfida, nuova);
        onEntrato();
      } catch (err) {
        setErrore(err instanceof ErroreAccesso ? err.leggibile : 'Accesso non riuscito.');
      } finally {
        setInCorso(false);
      }
      return;
    }

    setInCorso(true);
    try {
      const esito = await accedi(email, password);
      if (esito === 'dentro') onEntrato();
      else setSfida(esito);          // primo accesso: password temporanea
    } catch (err) {
      setErrore(err instanceof ErroreAccesso ? err.leggibile : 'Accesso non riuscito.');
    } finally {
      setInCorso(false);
    }
  };

  return (
    <div className="grid min-h-[100dvh] grid-cols-1 bg-canvas lg:grid-cols-[minmax(0,1fr)_minmax(0,0.92fr)]">
      {/* ═══ Modulo ══════════════════════════════════════════════ */}
      <div className="flex items-center justify-center px-5 py-12 sm:px-10 lg:px-16">
        <div
          ref={pannello}
          onPointerMove={seguiPuntatore}
          className="faro w-full max-w-[24rem] rounded-2xl"
        >
          <div className="rise mb-9 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-dorato-2/45 bg-gradient-to-b from-canvas to-alloro-3/55">
              <Sigillo className="h-6 w-6" animato />
            </div>
            <div>
              <div className="text-[14px] font-medium tracking-[-0.02em] text-ink">
                Graph<span className="text-azzurro">Responsa</span>
              </div>
              <div className="font-mono text-[9.5px] uppercase tracking-[0.16em] text-ink-3">
                Repubblica di San Marino
              </div>
            </div>
          </div>

          <h1
            className="rise text-[25px] font-normal leading-[1.18] tracking-[-0.032em] text-ink"
            style={{ ['--i' as string]: 1 }}
          >
            {sfida ? (
              <>
                Scegli la tua <span className="font-editorial italic text-azzurro">password</span>.
              </>
            ) : (
              <>
                Bentornato in <span className="font-editorial italic text-azzurro">archivio</span>.
              </>
            )}
          </h1>

          <p
            className="rise mt-3 text-[13.5px] leading-relaxed text-ink-2"
            style={{ ['--i' as string]: 2 }}
          >
            {sfida
              ? 'La password temporanea è servita una volta sola. Da adesso userai questa.'
              : 'L’accesso è riservato: le credenziali le rilascia l’amministratore.'}
          </p>

          <form
            onSubmit={invia}
            className="rise mt-8 flex flex-col gap-5"
            style={{ ['--i' as string]: 3 }}
          >
            {!sfida ? (
              <>
                <Campo id="email" etichetta="Email">
                  <input
                    id="email"
                    type="email"
                    autoComplete="username"
                    required
                    autoFocus
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={inCorso}
                    placeholder="nome@dominio.sm"
                    className={classiInput}
                  />
                </Campo>

                <Campo id="password" etichetta="Password">
                  <div className="relative">
                    <input
                      id="password"
                      type={mostra ? 'text' : 'password'}
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      disabled={inCorso}
                      placeholder="••••••••••••"
                      className={`${classiInput} pr-11`}
                    />
                    <button
                      type="button"
                      onClick={() => setMostra((v) => !v)}
                      tabIndex={-1}
                      title={mostra ? 'Nascondi' : 'Mostra'}
                      className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-lg p-2 text-ink-3 transition-colors hover:bg-raise hover:text-ink"
                    >
                      {mostra ? (
                        <EyeOff className="h-4 w-4" strokeWidth={1.5} />
                      ) : (
                        <Eye className="h-4 w-4" strokeWidth={1.5} />
                      )}
                    </button>
                  </div>
                </Campo>
              </>
            ) : (
              <>
                <div className="flex items-start gap-2.5 rounded-xl border border-dorato-2/50 bg-[#fdf8ea] px-3.5 py-3">
                  <KeyRound className="mt-px h-3.5 w-3.5 shrink-0 text-dorato" strokeWidth={1.5} />
                  <p className="text-[12px] leading-relaxed text-ink-2">
                    Primo accesso per <span className="font-medium text-ink">{sfida.email}</span>.
                  </p>
                </div>

                <Campo
                  id="nuova"
                  etichetta="Nuova password"
                  aiuto="Almeno 12 caratteri, con maiuscole, minuscole e numeri."
                >
                  <input
                    id="nuova"
                    type={mostra ? 'text' : 'password'}
                    autoComplete="new-password"
                    required
                    autoFocus
                    value={nuova}
                    onChange={(e) => setNuova(e.target.value)}
                    disabled={inCorso}
                    className={classiInput}
                  />
                </Campo>

                <Campo id="conferma" etichetta="Ripeti la password">
                  <input
                    id="conferma"
                    type={mostra ? 'text' : 'password'}
                    autoComplete="new-password"
                    required
                    value={conferma}
                    onChange={(e) => setConferma(e.target.value)}
                    disabled={inCorso}
                    className={classiInput}
                  />
                </Campo>
              </>
            )}

            {errore && (
              <div
                role="alert"
                className="slide-in flex items-start gap-2.5 rounded-xl border border-[#e8cec7] bg-rosso-2 px-3.5 py-3"
              >
                <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-rosso" strokeWidth={1.5} />
                <p className="text-[12.5px] leading-relaxed text-ink-2">{errore}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={inCorso}
              className="group mt-1 flex items-center justify-center gap-2 overflow-hidden rounded-xl bg-azzurro px-4 py-2.5 text-[14px] font-medium text-white shadow-[0_6px_18px_-10px_rgba(13,122,178,0.9)] transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px hover:shadow-[0_10px_24px_-10px_rgba(13,122,178,0.85)] disabled:cursor-wait disabled:opacity-70 active:translate-y-0 active:shadow-none"
            >
              {inCorso ? (
                <span className="flex items-center gap-2">
                  <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-white" />
                  Verifica in corso…
                </span>
              ) : (
                <>
                  {sfida ? 'Imposta ed entra' : 'Accedi'}
                  <ArrowRight
                    className="h-4 w-4 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-x-0.5"
                    strokeWidth={1.8}
                  />
                </>
              )}
            </button>
          </form>

          <p
            className="rise mt-6 text-[11.5px] leading-relaxed text-ink-3"
            style={{ ['--i' as string]: 4 }}
          >
            Hai perso la password? L’amministratore può rigenerarla: non esiste
            un recupero automatico.
          </p>
        </div>
      </div>

      {/* ═══ Pannello editoriale ═════════════════════════════════ */}
      <aside className="relative hidden flex-col justify-between overflow-hidden border-l border-line bg-panel px-12 py-12 lg:flex">
        {/* Campo di luce lentissimo: due macchie che derivano, mai ferme. */}
        <div
          aria-hidden
          className="deriva pointer-events-none absolute -left-24 -top-24 h-[34rem] w-[34rem] rounded-full bg-alloro-3/70 blur-3xl"
        />
        <div
          aria-hidden
          style={{ animationDelay: '-13s' }}
          className="deriva pointer-events-none absolute -bottom-32 -right-20 h-[30rem] w-[30rem] rounded-full bg-azzurro-3/60 blur-3xl"
        />
        <Sigillo className="pointer-events-none absolute -right-20 top-14 h-[28rem] w-[28rem] opacity-[0.045]" />

        <div className="relative">
          <div className="flex items-center gap-3">
            <span className="h-px w-7 bg-dorato-2" />
            <span className="font-mono text-[9.5px] uppercase tracking-[0.2em] text-dorato">
              Consiglio Grande e Generale
            </span>
          </div>
          <p className="mt-7 max-w-[19ch] font-editorial text-[30px] leading-[1.22] tracking-[-0.015em] text-ink">
            Ogni risposta risale al comma che la sostiene.
          </p>
          <p className="mt-4 max-w-[36ch] text-[13px] leading-relaxed text-ink-2">
            E dove l’archivio possiede solo il riferimento e non il testo, lo
            dichiara invece di colmare il vuoto.
          </p>
        </div>

        <div className="relative">
          <div className="flex items-center gap-2">
            <span className="h-px flex-1 bg-dorato-2/40" />
            <span className="font-mono text-[9px] uppercase tracking-[0.42em] text-dorato">
              Libertas
            </span>
            <span className="h-px flex-1 bg-dorato-2/40" />
          </div>
        </div>
      </aside>
    </div>
  );
};
