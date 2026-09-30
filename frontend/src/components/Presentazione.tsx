import React, { memo, useEffect, useRef, useState } from 'react';
import {
  ArrowDown, ArrowRight, ArrowUpRight, BookOpenText, Building2, FileText, Gavel, Landmark,
  Link2, Scale, ScrollText, Search, ShieldCheck, UserRound,
} from 'lucide-react';
import { Sigillo } from './Sigillo';
import { PrismGradient } from './PrismGradient';

/**
 * La pagina di presentazione: cosa e' Responsa, per chi non ha ancora fatto
 * l'accesso. Stessa lingua visiva dell'accesso - il prisma blu notte, il
 * sigillo, le etichette in maiuscoletto, il corsivo editoriale - perche' i due
 * schermi si passano la mano con "Accedi".
 *
 * Le cifre e gli esempi sono veri, letti dal grafo il 30/09/2026: una pagina
 * che spiega uno strumento di consultazione delle fonti non puo' inventarne.
 */

const PRISMA = ['#061f2f', '#3f9fd2', '#e3f1fa'] as const;

const NUMERI = [
  { valore: '11.110', etichetta: 'atti con il testo integrale', nota: 'leggi, decreti, regolamenti' },
  { valore: '77.387', etichetta: 'articoli', nota: 'ognuno con i suoi commi' },
  { valore: '177.369', etichetta: 'commi', nota: 'l’unità che Responsa cita' },
  { valore: '68.267', etichetta: 'rinvii fra atti', nota: 'le norme che si richiamano' },
];

// La composizione dell'archivio per tipo d'atto; "altri" raccoglie decreti
// consiliari, decreti-legge, leggi qualificate e costituzionali, statuti.
const COMPOSIZIONE = [
  { tipo: 'Decreti', n: 4387, colore: 'bg-[#061f2f]' },
  { tipo: 'Decreti delegati', n: 2320, colore: 'bg-azzurro-scuro' },
  { tipo: 'Leggi', n: 1871, colore: 'bg-azzurro' },
  { tipo: 'Decreti reggenziali', n: 444, colore: 'bg-azzurro-2' },
  { tipo: 'Regolamenti', n: 361, colore: 'bg-[#8fc3e3]' },
  { tipo: 'Altri atti', n: 1727, colore: 'bg-line-2' },
];
const TOTALE = COMPOSIZIONE.reduce((s, c) => s + c.n, 0);

// A mano e non con toLocaleString: per le quattro cifre il raggruppamento
// italiano non e' garantito da tutti i browser ("4387" invece di "4.387").
const migliaia = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.');

const PASSI = [
  {
    titolo: 'Chiedi come a un collega',
    testo: 'Scrivi la domanda in italiano, con parole tue. Non servono numeri di legge né parole chiave: se li conosci, aiutano.',
    icona: Search,
  },
  {
    titolo: 'Responsa consulta l’archivio',
    testo: 'Cerca negli atti, apre gli articoli pertinenti, segue i rinvii fra le norme e controlla se un atto successivo li ha modificati o abrogati.',
    icona: BookOpenText,
  },
  {
    titolo: 'Ricevi la risposta, con le fonti',
    testo: 'Ogni affermazione porta il suo riferimento, articolo e comma. Un clic apre il testo citato: la verifica resta tua.',
    icona: Scale,
  },
];

const LIMITI = [
  {
    titolo: 'Non è un parere legale',
    testo: 'Le risposte orientano e citano le fonti. Per una decisione, leggi i testi citati e rivolgiti a un professionista.',
  },
  {
    titolo: 'Non è un testo consolidato',
    testo: 'L’archivio conserva gli atti come furono pubblicati. Le modifiche si segnalano quando risultano dagli atti: l’assenza di un segnale non prova che una norma sia in vigore.',
  },
  {
    titolo: 'Non è aperto a tutti',
    testo: 'L’accesso è riservato: le credenziali sono personali e le rilascia l’amministratore.',
  },
];

const PUBBLICO = [
  { icona: Gavel, titolo: 'Professionisti', testo: 'Avvocati, notai, commercialisti: il riferimento esatto, e il testo per controllarlo.' },
  { icona: Building2, titolo: 'Uffici pubblici', testo: 'Chi applica le norme ogni giorno e deve sapere quale versione vale.' },
  { icona: UserRound, titolo: 'Chi ha una domanda precisa', testo: 'Un termine, un requisito, un obbligo: detto in chiaro, con la fonte accanto.' },
];

/** Porta in vista una sezione senza sporcare l'indirizzo: il frammento
 *  dell'URL serve gia' a distinguere la presentazione dall'accesso. */
function vaiA(id: string) {
  return (e: React.MouseEvent) => {
    e.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
}

/** Gli elementi con data-rivela entrano quando arrivano in vista, una volta. */
function useRivela(radice: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = radice.current;
    if (!el) return;
    const voci = el.querySelectorAll<HTMLElement>('[data-rivela]');
    if (!('IntersectionObserver' in window)) {
      voci.forEach((v) => v.classList.add('visibile'));
      return;
    }
    const osservatore = new IntersectionObserver((righe) => {
      for (const r of righe) {
        if (r.isIntersecting) {
          r.target.classList.add('visibile');
          osservatore.unobserve(r.target);
        }
      }
    }, { rootMargin: '0px 0px -12% 0px', threshold: 0.12 });
    voci.forEach((v) => osservatore.observe(v));
    return () => osservatore.disconnect();
  }, [radice]);
}

const Etichetta: React.FC<{ children: React.ReactNode; chiara?: boolean }> = ({ children, chiara }) => (
  <div className={`flex items-center gap-2.5 font-mono text-[11px] uppercase tracking-[0.16em] ${chiara ? 'text-white/75' : 'text-ink-3'}`}>
    <span className={`h-px w-6 ${chiara ? 'bg-white/70' : 'bg-azzurro'}`} />
    {children}
  </div>
);

const Citazione: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="mx-0.5 inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-azzurro/25 bg-azzurro-3/45 px-1.5 py-[1px] align-[1px] font-mono text-[10.5px] font-medium text-azzurro-scuro">
    <ScrollText className="h-3 w-3" strokeWidth={1.75} />
    {children}
  </span>
);

const Accedi: React.FC<{ onAccedi: () => void; chiaro?: boolean; grande?: boolean }> = ({ onAccedi, chiaro, grande }) => (
  <button
    type="button"
    onClick={onAccedi}
    className={`lucido group inline-flex items-center justify-center gap-2 overflow-hidden rounded-xl font-semibold transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] focus-visible:outline-none focus-visible:ring-4 active:scale-[0.985] ${
      grande ? 'h-[52px] px-6 text-[15px]' : 'h-10 px-4 text-[14px]'
    } ${
      chiaro
        ? 'bg-canvas text-ink shadow-[0_10px_30px_-14px_rgba(6,31,47,0.9)] hover:-translate-y-px focus-visible:ring-white/40'
        : 'bg-azzurro text-canvas shadow-[0_6px_18px_-10px_rgba(10,107,159,0.9)] hover:-translate-y-px hover:bg-azzurro-scuro focus-visible:ring-azzurro-3'
    }`}
  >
    Accedi
    <ArrowRight className="h-4 w-4 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-x-0.5" strokeWidth={1.75} />
  </button>
);

// ─── La consultazione dimostrativa ──────────────────────────────────────────
// Un esempio vero: l'art. 204-bis del Codice penale, testo coordinato al 27
// febbraio 2026, modificato dal D.D. 193/2021. Gira da sola in un componente
// suo, cosi' i suoi aggiornamenti non ridisegnano il resto della pagina.

const DOMANDA = 'Cosa rischia chi usa la carta di pagamento di un altro?';
const LETTURE = [
  { icona: Search, testo: 'Cerco negli atti' },
  { icona: ScrollText, testo: 'Leggo il Codice penale, art. 204-bis' },
  { icona: Landmark, testo: 'Controllo le modifiche successive' },
];

const Consultazione = memo(function Consultazione() {
  const ferma = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // 0: si scrive la domanda; 1-3: le letture; 4: la risposta.
  const [passo, setPasso] = useState(ferma ? 4 : 0);
  const [lettere, setLettere] = useState(ferma ? DOMANDA.length : 0);

  useEffect(() => {
    if (ferma) return;
    let timer: ReturnType<typeof setTimeout>;
    if (passo === 0) {
      timer = lettere < DOMANDA.length
        ? setTimeout(() => setLettere((n) => n + 1), 34)
        : setTimeout(() => setPasso(1), 650);
    } else if (passo < 4) {
      timer = setTimeout(() => setPasso((p) => p + 1), 1150);
    } else {
      // La risposta resta il tempo di leggerla, poi si ricomincia.
      timer = setTimeout(() => { setLettere(0); setPasso(0); }, 9000);
    }
    return () => clearTimeout(timer);
  }, [passo, lettere, ferma]);

  return (
    <div className="relative w-full max-w-[30rem] rounded-2xl border border-white/50 bg-canvas/95 p-5 shadow-[0_40px_90px_-40px_rgba(2,12,20,0.95),inset_0_1px_0_rgba(255,255,255,0.8)] backdrop-blur sm:p-6">
      <div className="flex items-center justify-between border-b border-line pb-3.5">
        <div className="flex items-center gap-2">
          <Sigillo className="h-4 w-4" />
          <span className="text-[13px] font-semibold tracking-[-0.01em] text-ink">Responsa</span>
        </div>
        <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-3">
          <span className="battito" style={{ ['--dim' as string]: '6px' }} />
          {passo < 4 ? 'In consultazione' : 'Risposta pronta'}
        </span>
      </div>

      {/* La domanda */}
      <div className="mt-4 flex justify-end">
        <p className="max-w-[88%] rounded-2xl rounded-br-md bg-panel px-3.5 py-2.5 text-[14px] leading-snug text-ink">
          <span className={passo === 0 ? 'cursore' : undefined}>{DOMANDA.slice(0, lettere)}</span>
          {/* Lo spazio della domanda intera c'e' da subito: la scheda non
              cambia altezza mentre si scrive. */}
          <span aria-hidden className="invisible">{DOMANDA.slice(lettere)}</span>
        </p>
      </div>

      {/* Le letture: compaiono una dopo l'altra, restano spuntate */}
      <ul className="mt-4 space-y-2" aria-label="Cosa sta facendo Responsa">
        {LETTURE.map((l, i) => {
          const Icona = l.icona;
          const fatto = passo > i + 1 || passo === 4;
          const inCorso = passo === i + 1;
          return (
            <li
              key={l.testo}
              className={`flex items-center gap-2.5 text-[12.5px] transition-[opacity,transform] duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                passo > i ? 'translate-y-0 opacity-100' : 'translate-y-1 opacity-0'
              }`}
            >
              <span className={`flex h-5 w-5 items-center justify-center rounded-full border ${fatto ? 'border-azzurro/30 bg-azzurro-3/50 text-azzurro' : 'border-line-2 text-ink-3'}`}>
                <Icona className="h-3 w-3" strokeWidth={1.75} />
              </span>
              <span className={inCorso ? 'testo-vivo text-ink-2' : 'text-ink-2'}>{l.testo}</span>
            </li>
          );
        })}
      </ul>

      {/* La risposta */}
      <div
        className={`mt-4 border-t border-line pt-4 transition-[opacity,transform] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] ${
          passo === 4 ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-2 opacity-0'
        }`}
        aria-live="polite"
      >
        <p className="text-[14px] leading-[1.65] text-ink">
          Chi usa fraudolentemente uno strumento di pagamento diverso dai contanti
          «senza esserne legittimo titolare» è punito con la{' '}
          <strong className="font-semibold">prigionia di secondo grado</strong> e con la{' '}
          <strong className="font-semibold">multa a giorni di secondo grado</strong>
          <Citazione>C.p. art. 204-bis, c. 1</Citazione>.
        </p>
        <p className="mt-2.5 text-[13px] leading-[1.6] text-ink-2">
          L’articolo è stato modificato dal D.D. 193/2021
          <Citazione>D.D. 193/2021, art. 3</Citazione>: il testo citato è quello
          coordinato al 27 febbraio 2026.
        </p>
      </div>
    </div>
  );
});

// ─── Le figure delle tre sezioni ───────────────────────────────────────────

/** La vita di un articolo: chi l'ha toccato, e quale testo si cita oggi. */
const Cronologia: React.FC = () => {
  const voci = [
    { anno: '2013', atto: 'L. 102/2013, art. 2', cosa: 'sostituisce l’articolo' },
    { anno: '2021', atto: 'D.D. 193/2021, art. 3', cosa: 'lo modifica' },
    { anno: '2026', atto: 'Testo coordinato', cosa: 'al 27 febbraio 2026: è quello che Responsa cita', ora: true },
  ];
  return (
    <div className="faro rounded-2xl border border-line bg-canvas p-6 shadow-[0_32px_64px_-36px_rgba(6,31,47,0.38)] sm:p-7">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-ink-3">Codice penale</div>
          <div className="mt-1 text-[17px] font-semibold tracking-[-0.02em] text-ink">Art. 204-bis</div>
          <div className="mt-0.5 text-[13px] leading-snug text-ink-2">
            Uso indebito di strumenti di pagamento diversi dai contanti
          </div>
        </div>
        <FileText className="mt-1 h-5 w-5 shrink-0 text-azzurro" strokeWidth={1.5} />
      </div>
      <ol className="relative mt-6 space-y-5 border-l border-line-2 pl-6">
        {voci.map((v, i) => (
          <li key={v.anno} data-rivela style={{ ['--i' as string]: i + 1 }} className="relative">
            <span
              className={`absolute -left-[31px] top-1 h-3 w-3 rounded-full border-2 ${
                v.ora ? 'border-azzurro bg-azzurro shadow-[0_0_0_4px_var(--color-azzurro-3)]' : 'border-line-2 bg-canvas'
              }`}
            />
            <div className="font-mono text-[11px] text-ink-3">{v.anno}</div>
            <div className="text-[14px] text-ink">
              <span className="font-semibold">{v.atto}</span> <span className="text-ink-2">{v.cosa}</span>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
};

/** Il pannello della fonte, come si apre nell'applicazione. */
const Fonte: React.FC = () => (
  <div className="faro overflow-hidden rounded-2xl border border-line bg-canvas shadow-[0_32px_64px_-36px_rgba(6,31,47,0.38)]">
    <div className="flex items-center justify-between border-b border-line bg-panel px-5 py-3.5">
      <div className="min-w-0">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-ink-3">Codice penale</div>
        <div className="text-[14px] font-semibold text-ink">Art. 204-bis · comma 1</div>
      </div>
      <span className="rounded-md border border-alloro/30 bg-alloro-3 px-2 py-0.5 font-mono text-[10.5px] text-alloro">
        coordinato 27/02/2026
      </span>
    </div>
    <div className="px-5 py-5">
      <p className="font-editorial text-[16.5px] leading-[1.6] text-ink">
        1. Chiunque utilizza fraudolentemente strumenti di pagamento diversi dai contanti,
        di tipo materiale o immateriale, contraffatti o falsificati, o comunque{' '}
        <mark className="evidenzia rounded-sm bg-transparent px-0.5 text-ink">senza esserne legittimo titolare</mark>,
        è punito con la prigionia di secondo grado e con la multa a giorni di secondo grado.
      </p>
      <div className="mt-5 flex items-center justify-between border-t border-line pt-4 text-[12.5px]">
        <span className="text-ink-3">Commi 1–4 nell’articolo</span>
        <span className="inline-flex items-center gap-1 font-medium text-azzurro">
          Documento ufficiale <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={1.75} />
        </span>
      </div>
    </div>
  </div>
);

/**
 * La rete attorno alla L. 44/2015 sull'edilizia sovvenzionata, com'e' nel
 * grafo: tre leggi l'hanno modificata, due atti del 2026 vi rinviano, e lei
 * richiama la L. 110/1994.
 */
const Rete: React.FC = () => {
  const centro = { x: 200, y: 150 };
  const nodi = [
    { x: 70, y: 52, nome: 'L. 64/2025', tipo: 'modifica' },
    { x: 330, y: 50, nome: 'L. 132/2023', tipo: 'modifica' },
    { x: 355, y: 170, nome: 'L. 171/2022', tipo: 'modifica' },
    { x: 290, y: 262, nome: 'L. 87/2026', tipo: 'rinvio' },
    { x: 92, y: 262, nome: 'R. 5/2026', tipo: 'rinvio' },
    { x: 40, y: 160, nome: 'L. 110/1994', tipo: 'richiamata' },
  ];
  return (
    <div className="faro rounded-2xl border border-line bg-canvas p-5 shadow-[0_32px_64px_-36px_rgba(6,31,47,0.38)] sm:p-6" data-rivela>
      <svg viewBox="0 0 400 300" className="rete h-auto w-full" role="img"
        aria-label="La Legge 44 del 2015 al centro: la modificano le leggi 64/2025, 132/2023 e 171/2022; vi rinviano la legge 87/2026 e il regolamento 5/2026; richiama la legge 110/1994.">
        {nodi.map((n, i) => (
          <line
            key={n.nome}
            x1={centro.x} y1={centro.y} x2={n.x} y2={n.y}
            // Il disegno tratto per tratto usa stroke-dasharray, e cancellerebbe
            // il tratteggio dei rinvii: quelli entrano in dissolvenza.
            className={n.tipo === 'modifica' ? 'rete-tratto' : 'rete-dissolvi'}
            style={{ ['--i' as string]: i, ['--lung' as string]: 200 }}
            stroke={n.tipo === 'modifica' ? 'var(--color-azzurro)' : 'var(--color-line-2)'}
            strokeWidth={n.tipo === 'modifica' ? 1.75 : 1.25}
            strokeDasharray={n.tipo === 'modifica' ? undefined : '4 5'}
          />
        ))}
        {nodi.map((n) => (
          <g key={`${n.nome}-nodo`}>
            <circle cx={n.x} cy={n.y} r={5} fill={n.tipo === 'modifica' ? 'var(--color-azzurro)' : 'var(--color-canvas)'}
              stroke={n.tipo === 'modifica' ? 'var(--color-azzurro)' : 'var(--color-ink-3)'} strokeWidth={1.5} />
            <text x={n.x} y={n.y + (n.y < centro.y ? -12 : 20)} textAnchor="middle"
              className="fill-ink font-mono text-[11px]">{n.nome}</text>
          </g>
        ))}
        <circle cx={centro.x} cy={centro.y} r={30} fill="#061f2f" />
        <circle cx={centro.x} cy={centro.y} r={38} fill="none" stroke="var(--color-azzurro-3)" strokeWidth={6} className="respira-anello" />
        <text x={centro.x} y={centro.y - 2} textAnchor="middle" className="fill-white font-mono text-[11px] font-medium">L. 44</text>
        <text x={centro.x} y={centro.y + 12} textAnchor="middle" className="fill-white/70 font-mono text-[9.5px]">2015</text>
      </svg>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 border-t border-line pt-3.5 text-[12px] text-ink-2">
        <span className="flex items-center gap-2"><span className="h-[2px] w-5 bg-azzurro" />la modifica</span>
        <span className="flex items-center gap-2"><span className="h-0 w-5 border-t border-dashed border-ink-3" />vi rinvia o è richiamata</span>
      </div>
    </div>
  );
};

// ─── La pagina ─────────────────────────────────────────────────────────────

export const Presentazione: React.FC<{ onAccedi: () => void }> = ({ onAccedi }) => {
  const radice = useRef<HTMLDivElement>(null);
  useRivela(radice);

  return (
    <div ref={radice} className="min-h-[100dvh] bg-canvas text-ink">
      {/* ═══ Apertura: testo a sinistra, il prisma con la consultazione a destra ═══ */}
      <section className="grid min-h-[100dvh] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.92fr)]">
        <div className="flex flex-col px-5 pb-10 pt-6 sm:px-10 lg:px-16 lg:pb-12 lg:pt-10">
          <header className="rise flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-line-2 bg-canvas shadow-[0_2px_8px_-4px_rgba(12,27,38,0.18)]">
                <Sigillo className="h-5 w-5" animato />
              </div>
              <div>
                <div className="text-[16px] font-semibold tracking-[-0.02em] text-ink">Responsa</div>
                <div className="whitespace-nowrap font-mono text-[9.5px] uppercase tracking-[0.12em] text-ink-2 sm:text-[10.5px] sm:tracking-[0.14em]">
                  Repubblica di San Marino
                </div>
              </div>
            </div>
            <div className="lg:hidden"><Accedi onAccedi={onAccedi} /></div>
          </header>

          <div className="flex flex-1 flex-col justify-center py-12 lg:py-16">
            <div className="rise" style={{ ['--i' as string]: 1 }}>
              <Etichetta>
                Diritto sammarinese<span className="hidden sm:inline"> · intelligenza artificiale</span>
              </Etichetta>
            </div>
            <h1
              className="rise mt-5 max-w-[15ch] text-[42px] font-medium leading-[1.04] tracking-[-0.04em] text-ink sm:text-[54px] xl:text-[60px]"
              style={{ ['--i' as string]: 2 }}
            >
              La legge di San Marino, <span className="text-azzurro">articolo per articolo</span>.
            </h1>
            <p
              className="rise mt-6 max-w-[52ch] text-[16.5px] leading-relaxed text-ink-2"
              style={{ ['--i' as string]: 3 }}
            >
              Responsa consulta leggi, decreti e regolamenti della Repubblica e risponde
              alle tue domande citando articolo e comma. Ogni citazione si apre sul testo
              dell’atto: quello che leggi, lo puoi controllare.
            </p>
            <div className="rise mt-9 flex flex-wrap items-center gap-3" style={{ ['--i' as string]: 4 }}>
              <Accedi onAccedi={onAccedi} grande />
              <a
                href="#come"
                onClick={vaiA('come')}
                className="group inline-flex h-[52px] items-center gap-2 rounded-xl px-4 text-[15px] font-medium text-ink-2 transition-colors duration-200 hover:bg-panel hover:text-ink"
              >
                Come funziona
                <ArrowDown className="h-4 w-4 transition-transform duration-300 group-hover:translate-y-0.5" strokeWidth={1.75} />
              </a>
            </div>
          </div>

          <dl className="rise grid grid-cols-3 gap-4 border-t border-line pt-5 sm:max-w-[34rem]" style={{ ['--i' as string]: 5 }}>
            {[
              ['11.110', 'atti'],
              ['177.369', 'commi'],
              ['1600–2026', 'quattro secoli'],
            ].map(([v, e]) => (
              <div key={e}>
                <dt className="sr-only">{e}</dt>
                <dd className="font-mono text-[15px] font-medium tracking-[-0.01em] text-ink sm:text-[17px]">{v}</dd>
                <dd className="mt-0.5 text-[12px] text-ink-3">{e}</dd>
              </div>
            ))}
          </dl>
        </div>

        <aside className="relative overflow-hidden">
          <div className="absolute inset-0">
            <PrismGradient colori={PRISMA} speed={0.6} noise={{ opacity: 0.18, scale: 0.8 }} />
          </div>
          <div aria-hidden className="absolute inset-0 bg-[linear-gradient(160deg,rgba(6,31,47,0.25)_0%,rgba(6,31,47,0.55)_55%,rgba(6,31,47,0.85)_100%)]" />
          <div className="relative flex h-full flex-col px-5 py-10 sm:px-10 lg:px-12 lg:py-10">
            <nav className="hidden items-center justify-end gap-7 lg:flex" aria-label="Sezioni">
              {[['come', 'Come funziona'], ['archivio', 'L’archivio'], ['limiti', 'Limiti']].map(([id, t]) => (
                <a key={id} href={`#${id}`} onClick={vaiA(id)}
                  className="text-[13.5px] font-medium text-white/80 transition-colors duration-200 hover:text-white">
                  {t}
                </a>
              ))}
              <Accedi onAccedi={onAccedi} chiaro />
            </nav>
            <div className="flex flex-1 items-center justify-center py-4 lg:py-10">
              <div className="rise w-full max-w-[30rem] lg:-ml-16 xl:-ml-24" style={{ ['--i' as string]: 3 }}>
                <Consultazione />
              </div>
            </div>
            <div className="rise hidden items-center gap-3 lg:flex" style={{ ['--i' as string]: 5 }}>
              <span className="font-mono text-[10.5px] uppercase tracking-[0.42em] text-white/70">Libertas</span>
              <span className="h-px w-16 bg-white/40" />
            </div>
          </div>
        </aside>
      </section>

      {/* ═══ Come funziona ═══ */}
      <section id="come" className="scroll-mt-6 border-t border-line">
        <div className="mx-auto grid max-w-[1240px] grid-cols-1 gap-12 px-5 py-20 sm:px-10 md:py-28 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-20 lg:px-16">
          <div className="lg:sticky lg:top-16 lg:self-start" data-rivela>
            <Etichetta>Come funziona</Etichetta>
            <h2 className="mt-5 max-w-[16ch] text-[34px] font-medium leading-[1.08] tracking-[-0.035em] sm:text-[42px]">
              Dalla domanda al <span className="text-azzurro">comma</span>, in tre passaggi.
            </h2>
            <p className="mt-5 max-w-[44ch] text-[15.5px] leading-relaxed text-ink-2">
              Non è un motore di ricerca che restituisce un elenco di atti. Legge gli
              articoli che servono e ti dice cosa prevedono, con il riferimento accanto.
            </p>
          </div>
          <ol className="divide-y divide-line border-y border-line">
            {PASSI.map((p, i) => {
              const Icona = p.icona;
              return (
                <li key={p.titolo} data-rivela style={{ ['--i' as string]: i }} className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 py-8 sm:gap-x-10 sm:py-10">
                  <span className="font-mono text-[13px] text-ink-3">0{i + 1}</span>
                  <div>
                    <div className="flex items-center gap-3">
                      <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-line bg-panel text-azzurro">
                        <Icona className="h-[18px] w-[18px]" strokeWidth={1.5} />
                      </span>
                      <h3 className="text-[20px] font-semibold tracking-[-0.02em] text-ink sm:text-[22px]">{p.titolo}</h3>
                    </div>
                    <p className="mt-3 max-w-[54ch] text-[15.5px] leading-relaxed text-ink-2">{p.testo}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </section>

      {/* ═══ Tre cose che fa diversamente, a zig-zag ═══ */}
      <section className="bg-panel/60">
        <div className="mx-auto max-w-[1240px] space-y-24 px-5 py-20 sm:px-10 md:space-y-32 md:py-28 lg:px-16">
          {[
            {
              etichetta: 'Vigenza',
              titolo: <>Il testo che vale <span className="text-azzurro">oggi</span>.</>,
              testo: 'L’archivio conserva gli atti come furono pubblicati, e una norma può essere stata riscritta più volte. Responsa collega ogni articolo agli atti successivi che lo toccano: quando rispondi su una norma modificata lo dice e cita la modifica, e un atto abrogato lo segnala prima di tutto.',
              figura: <Cronologia />,
            },
            {
              etichetta: 'Fonti',
              titolo: <>Ogni citazione <span className="text-azzurro">si apre</span>.</>,
              testo: 'Accanto a ogni affermazione c’è il suo riferimento. Un clic apre il comma citato, con l’articolo intero intorno e il documento ufficiale a un passo. Se un atto non è in archivio, Responsa lo dice invece di citarlo a memoria.',
              figura: <Fonte />,
            },
            {
              etichetta: 'Rinvii',
              titolo: <>Segue le norme che si <span className="text-azzurro">richiamano</span>.</>,
              testo: 'Un decreto applica una legge, un articolo rimanda a un altro, una definizione vale per tutto l’atto. L’archivio tiene 68.267 rinvii fra atti, e Responsa li segue quando la risposta dipende da una norma richiamata.',
              figura: <Rete />,
            },
          ].map((s, i) => (
            <div key={s.etichetta}
              className={`grid grid-cols-1 items-center gap-10 md:grid-cols-2 lg:gap-20 ${i % 2 ? 'md:[&>*:first-child]:order-2' : ''}`}>
              <div data-rivela>
                <Etichetta>{s.etichetta}</Etichetta>
                <h3 className="mt-5 max-w-[16ch] text-[30px] font-medium leading-[1.1] tracking-[-0.035em] text-ink sm:text-[36px]">
                  {s.titolo}
                </h3>
                <p className="mt-5 max-w-[48ch] text-[15.5px] leading-relaxed text-ink-2">{s.testo}</p>
              </div>
              <div data-rivela style={{ ['--i' as string]: 1 }} className={i % 2 ? 'md:mr-6' : 'md:ml-6'}>
                {s.figura}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ═══ L'archivio ═══ */}
      <section id="archivio" className="scroll-mt-6 border-t border-line">
        <div className="mx-auto max-w-[1240px] px-5 py-20 sm:px-10 md:py-28 lg:px-16">
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-end" data-rivela>
            <div>
              <Etichetta>L’archivio</Etichetta>
              <h2 className="mt-5 max-w-[18ch] text-[34px] font-medium leading-[1.08] tracking-[-0.035em] sm:text-[42px]">
                Dagli Statuti del 1600 agli atti di <span className="text-azzurro">quest’anno</span>.
              </h2>
            </div>
            <p className="max-w-[46ch] text-[15.5px] leading-relaxed text-ink-2 lg:justify-self-end">
              I testi vengono dal portale del Consiglio Grande e Generale, divisi in
              articoli e commi e collegati fra loro dai rinvii. È su questo che Responsa
              cerca, legge e cita.
            </p>
          </div>

          <dl className="mt-14 grid grid-cols-2 gap-x-6 gap-y-10 border-t border-line pt-10 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
            {NUMERI.map((n, i) => (
              <div key={n.etichetta} data-rivela style={{ ['--i' as string]: i }}>
                <dt className="sr-only">{n.etichetta}</dt>
                <dd className={`font-medium tabular-nums tracking-[-0.025em] text-ink ${i === 0 ? 'text-[36px] sm:text-[44px] lg:text-[64px]' : 'text-[36px] sm:text-[44px]'} leading-none`}>
                  {n.valore}
                </dd>
                <dd className="mt-3 text-[14px] font-medium text-ink">{n.etichetta}</dd>
                <dd className="mt-0.5 text-[13px] text-ink-3">{n.nota}</dd>
              </div>
            ))}
          </dl>

          <div className="mt-14" data-rivela>
            <div className="flex h-3 w-full overflow-hidden rounded-full" role="img"
              aria-label={COMPOSIZIONE.map((c) => `${c.tipo}: ${migliaia(c.n)}`).join(', ')}>
              {COMPOSIZIONE.map((c) => (
                <span key={c.tipo} className={`${c.colore} h-full`} style={{ width: `${(c.n / TOTALE) * 100}%` }} />
              ))}
            </div>
            <ul className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
              {COMPOSIZIONE.map((c) => (
                <li key={c.tipo} className="flex items-start gap-2.5">
                  <span className={`${c.colore} mt-1.5 h-2 w-2 shrink-0 rounded-full`} />
                  <span>
                    <span className="block text-[13px] text-ink">{c.tipo}</span>
                    <span className="block font-mono text-[12px] text-ink-3">{migliaia(c.n)}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ═══ Per chi, e i limiti ═══ */}
      <section id="limiti" className="scroll-mt-6 border-t border-line bg-panel/60">
        <div className="mx-auto grid max-w-[1240px] grid-cols-1 gap-16 px-5 py-20 sm:px-10 md:py-28 lg:grid-cols-2 lg:gap-24 lg:px-16">
          <div data-rivela>
            <Etichetta>Per chi</Etichetta>
            <h2 className="mt-5 text-[30px] font-medium leading-[1.1] tracking-[-0.035em] sm:text-[36px]">
              Per chi lavora con le norme.
            </h2>
            <ul className="mt-8 divide-y divide-line border-y border-line">
              {PUBBLICO.map((p) => {
                const Icona = p.icona;
                return (
                  <li key={p.titolo} className="flex gap-4 py-5">
                    <Icona className="mt-0.5 h-5 w-5 shrink-0 text-azzurro" strokeWidth={1.5} />
                    <div>
                      <div className="text-[15.5px] font-semibold text-ink">{p.titolo}</div>
                      <p className="mt-1 text-[14.5px] leading-relaxed text-ink-2">{p.testo}</p>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
          <div data-rivela style={{ ['--i' as string]: 1 }}>
            <Etichetta>Limiti</Etichetta>
            <h2 className="mt-5 text-[30px] font-medium leading-[1.1] tracking-[-0.035em] sm:text-[36px]">
              Quello che Responsa non è.
            </h2>
            <ul className="mt-8 divide-y divide-line border-y border-line">
              {LIMITI.map((l) => (
                <li key={l.titolo} className="flex gap-4 py-5">
                  <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-ink-3" strokeWidth={1.5} />
                  <div>
                    <div className="text-[15.5px] font-semibold text-ink">{l.titolo}</div>
                    <p className="mt-1 text-[14.5px] leading-relaxed text-ink-2">{l.testo}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ═══ Chiusura: il prisma, e l'accesso ═══ */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0">
          <PrismGradient colori={PRISMA} speed={0.45} noise={{ opacity: 0.18, scale: 0.8 }} />
        </div>
        <div aria-hidden className="absolute inset-0 bg-[linear-gradient(100deg,#061f2f_0%,rgba(6,31,47,0.9)_45%,rgba(6,31,47,0.35)_100%)]" />
        <div className="relative mx-auto grid max-w-[1240px] grid-cols-1 gap-10 px-5 py-20 sm:px-10 md:py-28 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,0.7fr)] lg:items-end lg:px-16">
          <div data-rivela>
            <Etichetta chiara>Area riservata</Etichetta>
            <p className="mt-6 max-w-[20ch] font-editorial text-[36px] italic leading-[1.15] tracking-[-0.01em] text-white sm:text-[48px]">
              Le norme della Repubblica, a una domanda di distanza.
            </p>
          </div>
          <div data-rivela style={{ ['--i' as string]: 1 }} className="lg:justify-self-end">
            <Accedi onAccedi={onAccedi} chiaro grande />
            <p className="mt-4 flex max-w-[30ch] items-start gap-2 text-[13px] leading-relaxed text-white/75">
              <Link2 className="mt-[3px] h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
              Le credenziali sono personali e le rilascia l’amministratore.
            </p>
          </div>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1240px] flex-col gap-4 px-5 py-8 text-[12.5px] text-ink-3 sm:flex-row sm:items-center sm:justify-between sm:px-10 lg:px-16">
          <div className="flex items-center gap-2.5">
            <Sigillo className="h-4 w-4" />
            <span className="font-medium text-ink-2">Responsa</span>
            <span aria-hidden>·</span>
            <span>Repubblica di San Marino</span>
          </div>
          <span className="font-mono text-[10.5px] uppercase tracking-[0.42em]">Libertas</span>
        </div>
      </footer>
    </div>
  );
};
