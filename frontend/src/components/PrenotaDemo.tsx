import React, { useRef, useState } from 'react';
import {
  AlertTriangle, ArrowRight, AtSign, Building2, CalendarCheck, Check, CircleAlert, CircleCheck,
  MessageSquareText, MonitorPlay, UserRound, BadgeCheck,
} from 'lucide-react';

/**
 * "Prenota una demo": il modulo per chi non ha ancora un account.
 *
 * La richiesta va al backend (POST /richiesta-demo), che la salva e la manda
 * per email alla casella commerciale: vedi src/servizio/demo.py. Qui ci sono i
 * controlli che si possono fare prima di inviare, e gli stati che chi compila
 * deve vedere: in corso, ricevuta, non riuscita.
 */

const RE_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

const PUNTI = [
  { icona: MonitorPlay, testo: 'Una dimostrazione dal vivo, sulle domande del tuo lavoro.' },
  { icona: BadgeCheck, testo: 'Vedi come cita le fonti e come segnala le norme cambiate.' },
  { icona: CalendarCheck, testo: 'Ti scriviamo per fissare giorno e ora: poi decidi con calma.' },
];

type Stato = 'modulo' | 'invio' | 'ricevuta';

// Le stesse misure dei campi dell'accesso: 16px, altrimenti Safari su iPhone
// ingrandisce la pagina a ogni tocco.
const classiCampo =
  'w-full rounded-xl border bg-canvas px-3.5 text-[16px] text-ink placeholder-ink-3 shadow-[inset_0_1px_2px_rgba(12,27,38,0.05)] ' +
  'transition-[border-color,box-shadow] duration-200 focus:outline-none focus:ring-4 disabled:opacity-60';
const bordo = (errato: boolean) =>
  errato ? 'border-rosso focus:ring-rosso-2' : 'border-campo hover:border-ink-3 focus:border-azzurro focus:ring-azzurro-3/70';

const Etichetta: React.FC<{ per: string; children: React.ReactNode; facoltativo?: boolean }> = ({ per, children, facoltativo }) => (
  <label htmlFor={per} className="flex items-baseline justify-between text-[13.5px] font-semibold text-ink">
    {children}
    {facoltativo && <span className="text-[12px] font-normal text-ink-3">facoltativo</span>}
  </label>
);

const Errore: React.FC<{ id: string; testo: string | null }> = ({ id, testo }) =>
  testo ? (
    <p id={id} className="frase-in flex items-center gap-1.5 text-[12.5px] font-medium text-rosso">
      <CircleAlert className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
      {testo}
    </p>
  ) : null;

export const PrenotaDemo: React.FC = () => {
  const [nome, setNome] = useState('');
  const [email, setEmail] = useState('');
  const [ente, setEnte] = useState('');
  const [ruolo, setRuolo] = useState('');
  const [messaggio, setMessaggio] = useState('');
  const [consenso, setConsenso] = useState(false);
  const [trappola, setTrappola] = useState('');
  const [stato, setStato] = useState<Stato>('modulo');
  const [errori, setErrori] = useState<{ nome?: string; email?: string; consenso?: string }>({});
  const [erroreInvio, setErroreInvio] = useState<string | null>(null);

  const campoNome = useRef<HTMLInputElement>(null);
  const campoEmail = useRef<HTMLInputElement>(null);

  const invia = async (e: React.FormEvent) => {
    e.preventDefault();
    setErroreInvio(null);
    const nuovi = {
      nome: nome.trim().length < 2 ? 'Scrivi nome e cognome.' : undefined,
      email: !email.trim() ? 'Inserisci l’email.' : !RE_EMAIL.test(email.trim()) ? 'Indirizzo email non valido.' : undefined,
      consenso: !consenso ? 'Serve il consenso per poterti ricontattare.' : undefined,
    };
    setErrori(nuovi);
    if (nuovi.nome) return campoNome.current?.focus();
    if (nuovi.email) return campoEmail.current?.focus();
    if (nuovi.consenso) return;

    setStato('invio');
    try {
      const r = await fetch('/richiesta-demo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, email, ente, ruolo, messaggio, consenso, sito: trappola }),
      });
      if (!r.ok) throw new Error(String(r.status));
      setStato('ricevuta');
    } catch (err) {
      setStato('modulo');
      setErroreInvio(err instanceof TypeError
        ? 'Nessuna connessione: controlla la rete e riprova.'
        : 'Non siamo riusciti a registrare la richiesta. Riprova tra poco.');
    }
  };

  const bloccato = stato === 'invio';

  return (
    <section id="demo" className="scroll-mt-6 border-t border-line">
      <div className="mx-auto grid max-w-[1240px] grid-cols-1 gap-12 px-5 py-20 sm:px-10 md:py-28 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:gap-20 lg:px-16">
        <div data-rivela className="lg:pt-4">
          <div className="flex items-center gap-2.5 font-mono text-[11px] uppercase tracking-[0.16em] text-ink-3">
            <span className="h-px w-6 bg-azzurro" />
            Prenota una demo
          </div>
          <h2 className="mt-5 max-w-[16ch] text-[34px] font-medium leading-[1.08] tracking-[-0.035em] text-ink sm:text-[42px]">
            Vedilo al lavoro sulle <span className="text-azzurro">tue domande</span>.
          </h2>
          <p className="mt-5 max-w-[46ch] text-[15.5px] leading-relaxed text-ink-2">
            Ti mostriamo Responsa con i casi che incontri ogni giorno: le norme che
            consulti, le domande che ti fanno. Scegli tu cosa chiedere.
          </p>
          <ul className="mt-8 space-y-4">
            {PUNTI.map((p) => {
              const Icona = p.icona;
              return (
                <li key={p.testo} className="flex items-start gap-3.5">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-line bg-panel text-azzurro">
                    <Icona className="h-[18px] w-[18px]" strokeWidth={1.5} />
                  </span>
                  <span className="pt-1.5 text-[15px] leading-snug text-ink">{p.testo}</span>
                </li>
              );
            })}
          </ul>
        </div>

        <div data-rivela style={{ ['--i' as string]: 1 }}
          className="faro rounded-2xl border border-line bg-canvas p-6 shadow-[0_32px_64px_-36px_rgba(6,31,47,0.38)] sm:p-8">
          {stato === 'ricevuta' ? (
            <div className="frase-in flex min-h-[26rem] flex-col items-start justify-center" role="status">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-alloro-3 text-alloro">
                <CircleCheck className="h-6 w-6" strokeWidth={1.75} />
              </span>
              <h3 className="mt-5 text-[24px] font-medium tracking-[-0.02em] text-ink">Richiesta ricevuta.</h3>
              <p className="mt-2 max-w-[40ch] text-[15px] leading-relaxed text-ink-2">
                Grazie{nome.trim() ? `, ${nome.trim().split(' ')[0]}` : ''}. Ti scriviamo a{' '}
                <span className="font-medium text-ink [overflow-wrap:anywhere]">{email.trim()}</span> per
                fissare giorno e ora della demo.
              </p>
            </div>
          ) : (
            <form onSubmit={invia} noValidate className="flex flex-col gap-5">
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <div className="flex flex-col gap-2">
                  <Etichetta per="demo-nome">Nome e cognome</Etichetta>
                  <div className="relative">
                    <UserRound aria-hidden className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" strokeWidth={1.75} />
                    <input ref={campoNome} id="demo-nome" autoComplete="name" value={nome} disabled={bloccato}
                      onChange={(e) => { setNome(e.target.value); if (errori.nome) setErrori({ ...errori, nome: undefined }); }}
                      aria-invalid={!!errori.nome} aria-describedby={errori.nome ? 'demo-nome-errore' : undefined}
                      className={`${classiCampo} ${bordo(!!errori.nome)} h-[52px] pl-10`} />
                  </div>
                  <Errore id="demo-nome-errore" testo={errori.nome ?? null} />
                </div>
                <div className="flex flex-col gap-2">
                  <Etichetta per="demo-email">Email</Etichetta>
                  <div className="relative">
                    <AtSign aria-hidden className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" strokeWidth={1.75} />
                    <input ref={campoEmail} id="demo-email" type="email" inputMode="email" autoComplete="email"
                      autoCapitalize="none" spellCheck={false} value={email} disabled={bloccato} placeholder="nome@studio.sm"
                      onChange={(e) => { setEmail(e.target.value); if (errori.email) setErrori({ ...errori, email: undefined }); }}
                      aria-invalid={!!errori.email} aria-describedby={errori.email ? 'demo-email-errore' : undefined}
                      className={`${classiCampo} ${bordo(!!errori.email)} h-[52px] pl-10`} />
                  </div>
                  <Errore id="demo-email-errore" testo={errori.email ?? null} />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <div className="flex flex-col gap-2">
                  <Etichetta per="demo-ente" facoltativo>Studio, ente o azienda</Etichetta>
                  <div className="relative">
                    <Building2 aria-hidden className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" strokeWidth={1.75} />
                    <input id="demo-ente" autoComplete="organization" value={ente} disabled={bloccato}
                      onChange={(e) => setEnte(e.target.value)}
                      className={`${classiCampo} ${bordo(false)} h-[52px] pl-10`} />
                  </div>
                </div>
                <div className="flex flex-col gap-2">
                  <Etichetta per="demo-ruolo" facoltativo>Ruolo</Etichetta>
                  <input id="demo-ruolo" autoComplete="organization-title" value={ruolo} disabled={bloccato}
                    placeholder="Avvocato, funzionario…"
                    onChange={(e) => setRuolo(e.target.value)}
                    className={`${classiCampo} ${bordo(false)} h-[52px]`} />
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <Etichetta per="demo-messaggio" facoltativo>Cosa vorresti chiedere a Responsa?</Etichetta>
                <div className="relative">
                  <MessageSquareText aria-hidden className="pointer-events-none absolute left-3.5 top-3.5 h-4 w-4 text-ink-3" strokeWidth={1.75} />
                  <textarea id="demo-messaggio" rows={3} value={messaggio} disabled={bloccato} maxLength={2000}
                    placeholder="Una materia, un caso, le norme che usi di più"
                    onChange={(e) => setMessaggio(e.target.value)}
                    className={`${classiCampo} ${bordo(false)} resize-none py-3 pl-10 leading-relaxed`} />
                </div>
              </div>

              {/* La trappola per i bot: fuori dallo schermo, fuori dal tab e
                  dall'autocompletamento. Chi la compila non e' una persona. */}
              <div aria-hidden className="absolute -left-[9999px] top-auto h-px w-px overflow-hidden">
                <label htmlFor="demo-sito">Sito web</label>
                <input id="demo-sito" tabIndex={-1} autoComplete="off" value={trappola}
                  onChange={(e) => setTrappola(e.target.value)} />
              </div>

              <div className="flex flex-col gap-2">
                <label className="flex cursor-pointer items-start gap-3 text-[13.5px] leading-relaxed text-ink-2">
                  <span className="relative mt-0.5 flex h-5 w-5 shrink-0">
                    <input type="checkbox" checked={consenso} disabled={bloccato}
                      onChange={(e) => { setConsenso(e.target.checked); if (errori.consenso) setErrori({ ...errori, consenso: undefined }); }}
                      aria-invalid={!!errori.consenso}
                      className={`peer h-5 w-5 cursor-pointer appearance-none rounded-md border bg-canvas transition-colors duration-150 checked:border-azzurro checked:bg-azzurro focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-azzurro-3 ${errori.consenso ? 'border-rosso' : 'border-campo'}`} />
                    <Check aria-hidden className="pointer-events-none absolute inset-0 m-auto h-3.5 w-3.5 text-canvas opacity-0 peer-checked:opacity-100" strokeWidth={3} />
                  </span>
                  <span>Acconsento a essere ricontattato per la demo. Useremo questi dati solo per questo.</span>
                </label>
                <Errore id="demo-consenso-errore" testo={errori.consenso ?? null} />
              </div>

              {erroreInvio && (
                <div role="alert" className="scuoti flex items-start gap-2.5 rounded-xl border border-rosso/45 bg-rosso-2 px-3.5 py-3">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rosso" strokeWidth={1.75} />
                  <p className="text-[13.5px] font-medium leading-relaxed text-ink">{erroreInvio}</p>
                </div>
              )}

              <button type="submit" disabled={bloccato}
                className="lucido group mt-1 flex h-[52px] items-center justify-center gap-2 overflow-hidden rounded-xl bg-azzurro px-4 text-[15px] font-semibold text-canvas shadow-[0_6px_18px_-10px_rgba(10,107,159,0.9)] transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px hover:bg-azzurro-scuro focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-azzurro-3 active:scale-[0.985] disabled:cursor-wait disabled:opacity-80">
                {bloccato ? (
                  <span className="flex items-center gap-2.5">
                    <span className="battito" style={{ ['--battito' as string]: '#fff' }} />
                    Invio in corso…
                  </span>
                ) : (
                  <>
                    Prenota la demo
                    <ArrowRight className="h-4 w-4 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-x-0.5" strokeWidth={1.75} />
                  </>
                )}
              </button>
            </form>
          )}
        </div>
      </div>
    </section>
  );
};
