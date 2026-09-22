import React, { useRef, useState } from 'react';
import {
  ArrowRight, AlertTriangle, ArrowBigUp, AtSign, Check, CircleAlert, CircleCheck, Eye, EyeOff,
  KeyRound, LockKeyhole, ShieldCheck,
} from 'lucide-react';
import { Sigillo } from './Sigillo';
import { PrismGradient } from './PrismGradient';
import {
  accedi,
  impostaNuovaPassword,
  ErroreAccesso,
  type NuovaPasswordRichiesta,
} from '../auth/cognito';

/**
 * Il prisma dietro la citazione (Prism Gradient di componentry): i colori
 * dell'originale - nero, blu elettrico, bianco - diventano il blu notte,
 * l'azzurro della bandiera e il suo riflesso chiaro.
 */
const PRISMA = ['#061f2f', '#3f9fd2', '#e3f1fa'] as const;

// Abbastanza per dire "manca la @" o "manca il dominio" prima di chiedere a
// Cognito; la verifica vera la fa lui.
const RE_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/** I requisiti della password del pool, spuntati mentre si scrive. */
const REQUISITI: { testo: string; ok: (p: string) => boolean }[] = [
  { testo: 'Almeno 12 caratteri', ok: (p) => p.length >= 12 },
  { testo: 'Una maiuscola', ok: (p) => /[A-Z]/.test(p) },
  { testo: 'Una minuscola', ok: (p) => /[a-z]/.test(p) },
  { testo: 'Un numero', ok: (p) => /\d/.test(p) },
];

// Da telefono il fuoco automatico apre subito la tastiera, che copre la fascia
// e meta' del modulo prima ancora che si sia letto cosa chiede.
const SCHERMO_LARGO =
  typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches;

interface AccessoProps {
  onEntrato: () => void;
}

/**
 * Etichetta sopra, il campo, e sotto l'errore e l'aiuto: l'errore sta accanto
 * a cio' che lo ha causato, non in un riquadro in fondo al modulo.
 */
const Campo: React.FC<{
  id: string;
  etichetta: string;
  azione?: React.ReactNode;
  errore?: string | null;
  sotto?: React.ReactNode;
  children: React.ReactNode;
}> = ({ id, etichetta, azione, errore, sotto, children }) => (
  <div className="flex flex-col gap-2">
    <div className="flex items-baseline justify-between gap-3">
      <label htmlFor={id} className="text-[13.5px] font-semibold text-ink">
        {etichetta}
      </label>
      {azione}
    </div>
    {children}
    {/* L'errore e l'aiuto insieme, non l'uno al posto dell'altro: chi ha
        lasciato vuota la password e chiede come recuperarla deve vedere
        entrambe le cose. */}
    {errore && (
      <p id={`${id}-errore`} className="frase-in flex items-center gap-1.5 text-[12.5px] font-medium text-rosso">
        <CircleAlert className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
        {errore}
      </p>
    )}
    {sotto}
  </div>
);

/**
 * Il campo come capsula unica: l'icona in una fascia sua, separata da un
 * filetto, il testo, e in coda cio' che serve (la spunta, l'occhio). Il bordo
 * e l'alone del fuoco stanno sulla capsula e non sull'input, cosi' abbracciano
 * anche icona e pulsanti.
 */
const Capsula: React.FC<{
  icona: React.ElementType;
  invalida?: boolean;
  coda?: React.ReactNode;
  children: React.ReactNode;
}> = ({ icona: Icona, invalida, coda, children }) => (
  <div
    className={`group flex h-[52px] items-center overflow-hidden rounded-xl border bg-canvas shadow-[inset_0_1px_2px_rgba(12,27,38,0.05)] transition-[border-color,box-shadow] duration-200 focus-within:ring-4 ${
      invalida
        ? 'border-rosso focus-within:ring-rosso-2'
        : 'border-campo hover:border-ink-3 focus-within:border-azzurro focus-within:ring-azzurro-3/70'
    }`}
  >
    <span
      aria-hidden
      className={`flex h-full w-11 shrink-0 items-center justify-center border-r transition-colors duration-200 ${
        invalida
          ? 'border-rosso/30 text-rosso'
          : 'border-line text-ink-3 group-focus-within:border-azzurro-3 group-focus-within:text-azzurro'
      }`}
    >
      <Icona className="h-4 w-4" strokeWidth={1.75} />
    </span>
    {children}
    {coda}
  </div>
);

// 16 pixel e non meno: sotto, Safari su iPhone ingrandisce la pagina a ogni
// tocco sul campo, e poi la lascia ingrandita.
const classiInput =
  'h-full min-w-0 flex-1 bg-transparent px-3.5 text-[16px] text-ink placeholder-ink-3 ' +
  'focus:outline-none focus-visible:outline-none disabled:opacity-60';

export const Accesso: React.FC<AccessoProps> = ({ onEntrato }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [nuova, setNuova] = useState('');
  const [conferma, setConferma] = useState('');
  const [mostra, setMostra] = useState(false);
  const [sfida, setSfida] = useState<NuovaPasswordRichiesta | null>(null);
  const [inCorso, setInCorso] = useState(false);
  const [entrato, setEntrato] = useState(false);
  const [aiutoPassword, setAiutoPassword] = useState(false);

  // Errori dei singoli campi, sotto il campo; l'errore del server (credenziali
  // rifiutate, rete) nel riquadro sopra il pulsante.
  const [erroreEmail, setErroreEmail] = useState<string | null>(null);
  const [errorePassword, setErrorePassword] = useState<string | null>(null);
  const [errore, setErroreTesto] = useState<string | null>(null);
  const [scossa, setScossa] = useState(0);
  const setErrore = (testo: string | null) => {
    setErroreTesto(testo);
    if (testo) setScossa((n) => n + 1);   // lo scossone riparte anche sullo stesso messaggio
  };

  // Una password rifiutata per il Bloc Maiuscole e' l'errore piu' frustrante
  // da capire: lo si dice prima di inviare.
  const [maiuscole, setMaiuscole] = useState(false);
  const leggiMaiuscole = (e: React.KeyboardEvent) =>
    setMaiuscole(e.getModifierState?.('CapsLock') ?? false);

  const pannello = useRef<HTMLDivElement>(null);
  const campoPassword = useRef<HTMLInputElement>(null);
  const campoEmail = useRef<HTMLInputElement>(null);

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

  const emailValida = RE_EMAIL.test(email.trim());
  const requisitiOk = REQUISITI.every((r) => r.ok(nuova));
  const coincidono = conferma.length > 0 && conferma === nuova;

  /** Un attimo di conferma sul pulsante prima di cambiare pagina: senza, il
   *  modulo sparisce e non si capisce se l'accesso e' riuscito o e' saltato. */
  const entra = () => {
    setEntrato(true);
    setTimeout(onEntrato, 450);
  };

  const invia = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrore(null);

    if (sfida) {
      if (!requisitiOk) return setErrore('La nuova password non rispetta ancora tutti i requisiti.');
      if (nuova !== conferma) return setErrore('Le due password non coincidono.');
      setInCorso(true);
      try {
        await impostaNuovaPassword(sfida, nuova);
        entra();
      } catch (err) {
        setErrore(err instanceof ErroreAccesso ? err.leggibile : 'Accesso non riuscito.');
      } finally {
        setInCorso(false);
      }
      return;
    }

    // Controlli nostri al posto dei fumetti del browser: stesso tono del resto
    // della pagina, e il fuoco va al primo campo da sistemare.
    const eEmail = !email.trim() ? 'Inserisci l’email.' : !emailValida ? 'Indirizzo email non valido.' : null;
    const ePassword = !password ? 'Inserisci la password.' : null;
    setErroreEmail(eEmail);
    setErrorePassword(ePassword);
    if (eEmail) return campoEmail.current?.focus();
    if (ePassword) return campoPassword.current?.focus();

    setInCorso(true);
    try {
      const esito = await accedi(email.trim(), password);
      if (esito === 'dentro') entra();
      else setSfida(esito);          // primo accesso: password temporanea
    } catch (err) {
      setErrore(err instanceof ErroreAccesso ? err.leggibile : 'Accesso non riuscito.');
    } finally {
      setInCorso(false);
    }
  };

  const bloccato = inCorso || entrato;

  const occhio = (
    <button
      type="button"
      onClick={() => setMostra((v) => !v)}
      title={mostra ? 'Nascondi la password' : 'Mostra la password'}
      aria-label={mostra ? 'Nascondi la password' : 'Mostra la password'}
      aria-pressed={mostra}
      className="mr-1.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-ink-2 transition-colors duration-200 hover:bg-raise hover:text-ink active:scale-95"
    >
      {mostra ? <EyeOff className="h-4 w-4" strokeWidth={1.75} /> : <Eye className="h-4 w-4" strokeWidth={1.75} />}
    </button>
  );

  const avvisoMaiuscole = maiuscole ? (
    <p className="frase-in flex items-center gap-1.5 text-[12.5px] font-medium text-dorato">
      <ArrowBigUp className="h-4 w-4" strokeWidth={1.75} />
      Bloc Maiuscole attivo
    </p>
  ) : null;

  return (
    <div className="grid min-h-[100dvh] grid-cols-1 grid-rows-[auto_1fr] bg-canvas lg:grid-cols-[minmax(0,1fr)_minmax(0,0.92fr)] lg:grid-rows-1">
      {/* ═══ Fascia, solo su telefono e tablet ═══════════════════ */}
      <header className="relative h-[228px] overflow-hidden sm:h-[260px] lg:hidden">
        <div className="absolute inset-0">
          <PrismGradient colori={PRISMA} speed={0.6} noise={{ opacity: 0.18, scale: 0.8 }} />
        </div>
        <div aria-hidden className="absolute inset-0 bg-gradient-to-r from-[#061f2f]/95 via-[#061f2f]/55 to-transparent" />
        <div className="relative flex h-full flex-col justify-between px-5 pb-12 pt-6 sm:px-10">
          <div className="rise flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-canvas shadow-[0_6px_16px_-8px_rgba(6,31,47,0.8)]">
              <Sigillo className="h-5 w-5" animato />
            </div>
            <div>
              <div className="text-[15px] font-semibold tracking-[-0.02em] text-white">GraphResponsa</div>
              <div className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-white/75">
                Repubblica di San Marino
              </div>
            </div>
          </div>
          <p
            className="rise font-editorial text-[26px] italic leading-[1.15] tracking-[-0.01em] text-white sm:text-[30px]"
            style={{ ['--i' as string]: 1 }}
          >
            Da mihi factum,
            <br />
            dabo tibi ius.
          </p>
        </div>
      </header>

      {/* ═══ Modulo ══════════════════════════════════════════════ */}
      {/* Su telefono e' un foglio che sale sopra la fascia, con gli angoli
          arrotondati; da lg torna una colonna piana accanto al pannello. */}
      <div className="relative z-10 -mt-7 flex items-start justify-center rounded-t-[28px] bg-canvas px-5 pb-12 pt-9 shadow-[0_-12px_30px_-18px_rgba(6,31,47,0.45)] sm:px-10 lg:mt-0 lg:items-center lg:rounded-none lg:px-16 lg:py-12 lg:shadow-none">
        <div className="w-full max-w-[26rem]">
          <div className="rise mb-9 hidden items-center gap-3 lg:flex">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-line-2 bg-canvas shadow-[0_2px_8px_-4px_rgba(12,27,38,0.18)]">
              <Sigillo className="h-6 w-6" animato />
            </div>
            <div>
              <div className="text-[16px] font-semibold tracking-[-0.02em] text-ink">
                Graph<span className="text-azzurro">Responsa</span>
              </div>
              <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-2">
                Repubblica di San Marino
              </div>
            </div>
          </div>

          <div
            className="rise mb-3 flex items-center gap-2.5 font-mono text-[11px] uppercase tracking-[0.16em] text-ink-3"
            style={{ ['--i' as string]: 1 }}
          >
            <span className="h-px w-6 bg-azzurro" />
            {sfida ? 'Primo accesso' : 'Area riservata'}
          </div>
          <h1
            className="rise text-[30px] font-medium leading-[1.12] tracking-[-0.035em] text-ink"
            style={{ ['--i' as string]: 1 }}
          >
            {sfida ? (
              <>
                Scegli la tua <span className="text-azzurro">password</span>.
              </>
            ) : (
              <>
                Bentornato in <span className="text-azzurro">archivio</span>.
              </>
            )}
          </h1>

          <p
            className="rise mt-3 text-[15px] leading-relaxed text-ink-2"
            style={{ ['--i' as string]: 2 }}
          >
            {sfida
              ? 'La password temporanea è servita una volta sola. Da adesso userai questa.'
              : 'Le credenziali sono personali e le rilascia l’amministratore.'}
          </p>

          {/* La scheda del modulo: su schermo largo un piano rialzato con il
              bordo che si accende sotto il puntatore; su telefono il foglio
              bianco basta, e una scheda dentro il foglio sarebbe un doppione. */}
          <div
            ref={pannello}
            onPointerMove={seguiPuntatore}
            className="rise faro mt-8 lg:rounded-2xl lg:border lg:border-line lg:bg-canvas lg:p-6 lg:shadow-[0_32px_64px_-36px_rgba(6,31,47,0.38)]"
            style={{ ['--i' as string]: 3 }}
          >
            <form onSubmit={invia} noValidate className="flex flex-col gap-5">
              {!sfida ? (
                <>
                  <Campo id="email" etichetta="Email" errore={erroreEmail}>
                    <Capsula
                      icona={AtSign}
                      invalida={!!erroreEmail || !!errore}
                      coda={
                        emailValida && !erroreEmail && !errore ? (
                          <CircleCheck
                            aria-label="Indirizzo valido"
                            className="frase-in mr-3.5 h-4 w-4 shrink-0 text-azzurro"
                            strokeWidth={1.75}
                          />
                        ) : null
                      }
                    >
                      <input
                        ref={campoEmail}
                        id="email"
                        type="email"
                        inputMode="email"
                        autoComplete="username"
                        autoCapitalize="none"
                        autoCorrect="off"
                        spellCheck={false}
                        enterKeyHint="next"
                        autoFocus={SCHERMO_LARGO}
                        value={email}
                        onChange={(e) => {
                          setEmail(e.target.value);
                          if (erroreEmail && RE_EMAIL.test(e.target.value.trim())) setErroreEmail(null);
                          if (errore) setErrore(null);
                        }}
                        onBlur={() => {
                          if (email.trim() && !emailValida) setErroreEmail('Indirizzo email non valido.');
                        }}
                        onKeyDown={(e) => {
                          // Invio sull'email porta alla password, se e' ancora
                          // vuota: inviare a meta' darebbe solo un errore.
                          if (e.key === 'Enter' && !password) {
                            e.preventDefault();
                            campoPassword.current?.focus();
                          }
                        }}
                        disabled={bloccato}
                        placeholder="nome@dominio.sm"
                        aria-invalid={!!erroreEmail || !!errore}
                        aria-describedby={erroreEmail ? 'email-errore' : undefined}
                        className={classiInput}
                      />
                    </Capsula>
                  </Campo>

                  <Campo
                    id="password"
                    etichetta="Password"
                    errore={errorePassword}
                    azione={
                      <button
                        type="button"
                        onClick={() => setAiutoPassword((v) => !v)}
                        aria-expanded={aiutoPassword}
                        aria-controls="password-aiuto"
                        className="rounded text-[12.5px] font-medium text-azzurro underline-offset-4 transition-colors duration-200 hover:text-azzurro-scuro hover:underline"
                      >
                        Password smarrita?
                      </button>
                    }
                    sotto={
                      <>
                        {avvisoMaiuscole}
                        {aiutoPassword && (
                          <p
                            id="password-aiuto"
                            className="frase-in flex items-start gap-2 rounded-lg bg-panel px-3 py-2.5 text-[12.5px] leading-relaxed text-ink-2"
                          >
                            <KeyRound className="mt-[2px] h-3.5 w-3.5 shrink-0 text-azzurro" strokeWidth={1.75} />
                            La rigenera l’amministratore: non esiste un recupero
                            automatico.
                          </p>
                        )}
                      </>
                    }
                  >
                    <Capsula icona={LockKeyhole} invalida={!!errorePassword || !!errore} coda={occhio}>
                      <input
                        ref={campoPassword}
                        id="password"
                        type={mostra ? 'text' : 'password'}
                        autoComplete="current-password"
                        enterKeyHint="go"
                        value={password}
                        onChange={(e) => {
                          setPassword(e.target.value);
                          if (errorePassword && e.target.value) setErrorePassword(null);
                          if (errore) setErrore(null);
                        }}
                        onKeyUp={leggiMaiuscole}
                        onKeyDown={leggiMaiuscole}
                        onBlur={() => setMaiuscole(false)}
                        disabled={bloccato}
                        aria-invalid={!!errorePassword || !!errore}
                        aria-describedby={errorePassword ? 'password-errore' : undefined}
                        className={classiInput}
                      />
                    </Capsula>
                  </Campo>
                </>
              ) : (
                <>
                  <div className="flex items-start gap-2.5 rounded-xl border border-azzurro/25 bg-azzurro-3/30 px-3.5 py-3">
                    <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-azzurro" strokeWidth={1.75} />
                    <p className="text-[13px] leading-relaxed text-ink">
                      Primo accesso per <span className="font-medium text-ink">{sfida.email}</span>.
                    </p>
                  </div>

                  <Campo
                    id="nuova"
                    etichetta="Nuova password"
                    sotto={
                      <>
                        {avvisoMaiuscole}
                        {/* I requisiti si spuntano mentre si scrive: si sa
                            cosa manca prima di inviare, non dopo. */}
                        <ul className="grid grid-cols-2 gap-x-3 gap-y-1.5" aria-label="Requisiti della password">
                          {REQUISITI.map((r) => {
                            const ok = r.ok(nuova);
                            return (
                              <li
                                key={r.testo}
                                className={`flex items-center gap-1.5 text-[12.5px] transition-colors duration-200 ${ok ? 'text-ink' : 'text-ink-3'}`}
                              >
                                <span
                                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors duration-200 ${
                                    ok ? 'border-azzurro bg-azzurro text-white' : 'border-line-2 text-transparent'
                                  }`}
                                >
                                  <Check className="h-2.5 w-2.5" strokeWidth={3} />
                                </span>
                                {r.testo}
                              </li>
                            );
                          })}
                        </ul>
                      </>
                    }
                  >
                    <Capsula icona={LockKeyhole} invalida={!!errore && !requisitiOk} coda={occhio}>
                      <input
                        id="nuova"
                        type={mostra ? 'text' : 'password'}
                        autoComplete="new-password"
                        autoFocus={SCHERMO_LARGO}
                        value={nuova}
                        onChange={(e) => {
                          setNuova(e.target.value);
                          if (errore) setErrore(null);
                        }}
                        onKeyUp={leggiMaiuscole}
                        onKeyDown={leggiMaiuscole}
                        onBlur={() => setMaiuscole(false)}
                        disabled={bloccato}
                        className={classiInput}
                      />
                    </Capsula>
                  </Campo>

                  <Campo
                    id="conferma"
                    etichetta="Ripeti la password"
                    sotto={
                      conferma && !coincidono ? (
                        <p className="text-[12.5px] text-ink-3">Le due password non coincidono ancora.</p>
                      ) : null
                    }
                  >
                    <Capsula
                      icona={LockKeyhole}
                      invalida={!!errore && !coincidono}
                      coda={
                        coincidono ? (
                          <CircleCheck
                            aria-label="Le password coincidono"
                            className="frase-in mr-3.5 h-4 w-4 shrink-0 text-azzurro"
                            strokeWidth={1.75}
                          />
                        ) : null
                      }
                    >
                      <input
                        id="conferma"
                        type={mostra ? 'text' : 'password'}
                        autoComplete="new-password"
                        value={conferma}
                        onChange={(e) => {
                          setConferma(e.target.value);
                          if (errore) setErrore(null);
                        }}
                        disabled={bloccato}
                        className={classiInput}
                      />
                    </Capsula>
                  </Campo>
                </>
              )}

              {errore && (
                <div
                  key={scossa}
                  role="alert"
                  className="scuoti flex items-start gap-2.5 rounded-xl border border-rosso/45 bg-rosso-2 px-3.5 py-3"
                >
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rosso" strokeWidth={1.75} />
                  <p className="text-[13.5px] font-medium leading-relaxed text-ink">{errore}</p>
                </div>
              )}

              <button
                type="submit"
                disabled={bloccato}
                className={`lucido group mt-1 flex h-[52px] items-center justify-center gap-2 overflow-hidden rounded-xl px-4 text-[15px] font-semibold text-white transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] focus-visible:ring-4 focus-visible:ring-azzurro-3 active:scale-[0.985] ${
                  entrato
                    ? 'bg-azzurro-scuro'
                    : 'bg-azzurro shadow-[0_6px_18px_-10px_rgba(10,107,159,0.9)] hover:-translate-y-px hover:bg-azzurro-scuro hover:shadow-[0_10px_24px_-10px_rgba(10,107,159,0.85)] active:translate-y-0 active:shadow-none disabled:cursor-wait disabled:opacity-80'
                }`}
              >
                {entrato ? (
                  <span className="frase-in flex items-center gap-2">
                    <Check className="h-4 w-4" strokeWidth={2.25} />
                    Accesso consentito
                  </span>
                ) : inCorso ? (
                  <span className="flex items-center gap-2.5">
                    <span className="battito" style={{ ['--battito' as string]: '#fff' }} />
                    Verifica in corso…
                  </span>
                ) : (
                  <>
                    {sfida ? 'Imposta ed entra' : 'Accedi'}
                    <ArrowRight
                      className="h-4 w-4 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-x-0.5"
                      strokeWidth={1.75}
                    />
                  </>
                )}
              </button>
            </form>
          </div>

          <p
            className="rise mt-6 flex items-start gap-2.5 text-[12.5px] leading-relaxed text-ink-3"
            style={{ ['--i' as string]: 4 }}
          >
            <ShieldCheck className="mt-[2px] h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
            Connessione cifrata: le credenziali non viaggiano mai in chiaro.
          </p>
        </div>
      </div>

      {/* ═══ Pannello editoriale ═════════════════════════════════ */}
      <aside className="relative hidden overflow-hidden lg:block">
        <div className="absolute inset-0">
          <PrismGradient colori={PRISMA} speed={0.6} noise={{ opacity: 0.18, scale: 0.8 }} />
        </div>
        {/* Il prisma si muove e prima o poi un nastro chiaro passa dove sta il
            testo: la velatura tiene scura la colonna del testo e lascia il
            prisma libero sul lato destro. */}
        <div
          aria-hidden
          className="absolute inset-0 bg-[linear-gradient(100deg,#061f2f_0%,rgba(6,31,47,0.9)_38%,rgba(6,31,47,0)_74%)]"
        />

        <div className="relative flex h-full flex-col justify-between px-12 py-12 xl:px-16">
          <div>
            <div className="rise flex items-center gap-3">
              <span className="h-px w-7 bg-white/70" />
              <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-white/80">
                Responsa prudentium
              </span>
            </div>
            <p
              className="rise mt-7 max-w-[14ch] font-editorial text-[48px] italic leading-[1.06] tracking-[-0.02em] text-white xl:text-[56px]"
              style={{ ['--i' as string]: 1 }}
            >
              Da mihi factum,
              <br />
              dabo tibi ius.
            </p>
            <p
              className="rise mt-6 max-w-[40ch] text-[15.5px] leading-relaxed text-white/85"
              style={{ ['--i' as string]: 2 }}
            >
              Esponi il caso. Ogni risposta si fonda sulla norma, con articolo e
              comma di ciascuna fonte; dove il testo manca, lo dichiara invece
              di supplirvi.
            </p>
          </div>

          <div className="rise flex items-center gap-3" style={{ ['--i' as string]: 3 }}>
            <span className="font-mono text-[10.5px] uppercase tracking-[0.42em] text-white/70">
              Libertas
            </span>
            <span className="h-px w-16 bg-white/40" />
          </div>
        </div>
      </aside>
    </div>
  );
};
