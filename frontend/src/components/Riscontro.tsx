import React, { useState } from 'react';
import { ThumbsUp, ThumbsDown, Check, X } from 'lucide-react';
import { token } from '../auth/cognito';
import type { Fonte } from '../types';

interface RiscontroProps {
  conversazione: string | null;
  indiceMessaggio: number;
  domanda: string;
  risposta: string;
  fonti: Fonte[];
}

/**
 * I modi tipici in cui un assistente giuridico sbaglia.
 *
 * Servono a rendere i riscontri contabili: con il solo testo libero, a cento
 * riscontri non si sa piu' cosa si sta guardando. Cosi' invece si conta quante
 * volte l'agente ha inventato una fonte, che e' il difetto che le istruzioni
 * di sistema cercano di prevenire.
 */
const CATEGORIE = [
  { id: 'fonte_errata', etichetta: 'Fonte sbagliata o inesistente' },
  { id: 'non_vigente', etichetta: 'Norma non più vigente' },
  { id: 'fuori_tema', etichetta: 'Non ha risposto alla domanda' },
  { id: 'testo_inesatto', etichetta: 'Testo citato inesatto' },
  { id: 'altro', etichetta: 'Altro' },
];

export const Riscontro: React.FC<RiscontroProps> = ({
  conversazione,
  indiceMessaggio,
  domanda,
  risposta,
  fonti,
}) => {
  const [dato, setDato] = useState<'utile' | 'non_utile' | null>(null);
  const [apertoModulo, setApertoModulo] = useState(false);
  const [scelte, setScelte] = useState<string[]>([]);
  const [motivo, setMotivo] = useState('');
  const [invio, setInvio] = useState(false);

  const manda = async (
    giudizio: 'utile' | 'non_utile',
    categorie: string[] = [],
    testo = ''
  ) => {
    if (!conversazione) return;
    setInvio(true);
    try {
      const t = await token();
      await fetch('/riscontro', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(t ? { Authorization: `Bearer ${t}` } : {}),
        },
        body: JSON.stringify({
          conversazione,
          indiceMessaggio,
          giudizio,
          motivo: testo,
          categorie,
          domanda,
          // Il contesto va salvato col riscontro: fra un mese i checkpoint
          // saranno scaduti, e «non utile» da solo non e' analizzabile.
          estrattoRisposta: risposta.slice(0, 2000),
          fonti: fonti.map((f) => `${f.norma} art.${f.articolo} c.${f.comma}`),
        }),
      });
      setDato(giudizio);
      setApertoModulo(false);
    } catch {
      /* il riscontro non è il lavoro dell'utente: un errore qui non lo si scarica su di lui */
    } finally {
      setInvio(false);
    }
  };

  if (dato) {
    return (
      <span className="flex items-center gap-1.5 px-2 py-1 text-[11.5px] text-alloro">
        <Check className="h-3.5 w-3.5" strokeWidth={1.8} />
        {dato === 'utile' ? 'Grazie' : 'Grazie, ne terremo conto'}
      </span>
    );
  }

  return (
    <div className="w-full">
      <div className="flex items-center gap-0.5">
        <button
          onClick={() => manda('utile')}
          disabled={invio || !conversazione}
          title="Risposta utile"
          className="rounded-lg p-1.5 text-ink-3 transition-colors duration-200 hover:bg-alloro-3/60 hover:text-alloro disabled:opacity-40 active:translate-y-px"
        >
          <ThumbsUp className="h-3.5 w-3.5" strokeWidth={1.5} />
        </button>
        <button
          onClick={() => setApertoModulo((v) => !v)}
          disabled={invio || !conversazione}
          title="Risposta da correggere"
          className={`rounded-lg p-1.5 transition-colors duration-200 disabled:opacity-40 active:translate-y-px ${
            apertoModulo ? 'bg-rosso-2 text-rosso' : 'text-ink-3 hover:bg-rosso-2 hover:text-rosso'
          }`}
        >
          <ThumbsDown className="h-3.5 w-3.5" strokeWidth={1.5} />
        </button>
      </div>

      {apertoModulo && (
        <div className="rise mt-2.5 rounded-xl border border-line bg-panel p-3.5">
          <div className="mb-2.5 flex items-start justify-between gap-3">
            <p className="text-[12.5px] font-medium text-ink">
              Perché questa risposta non va?
            </p>
            <button
              onClick={() => setApertoModulo(false)}
              className="-mr-1 -mt-0.5 rounded-md p-1 text-ink-3 transition-colors hover:bg-raise hover:text-ink"
              title="Chiudi"
            >
              <X className="h-3.5 w-3.5" strokeWidth={1.5} />
            </button>
          </div>

          <div className="mb-3 flex flex-wrap gap-1.5">
            {CATEGORIE.map((c) => {
              const attiva = scelte.includes(c.id);
              return (
                <button
                  key={c.id}
                  onClick={() =>
                    setScelte((s) =>
                      s.includes(c.id) ? s.filter((x) => x !== c.id) : [...s, c.id]
                    )
                  }
                  className={`rounded-lg border px-2.5 py-1 text-[11.5px] transition-all duration-200 active:translate-y-px ${
                    attiva
                      ? 'border-azzurro bg-azzurro-3/60 text-ink'
                      : 'border-line bg-canvas text-ink-2 hover:border-line-2'
                  }`}
                >
                  {c.etichetta}
                </button>
              );
            })}
          </div>

          <textarea
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            rows={3}
            maxLength={2000}
            placeholder="Racconta cosa non torna: quale passaggio, quale fonte, cosa ti aspettavi…"
            className="w-full resize-none rounded-lg border border-line bg-canvas px-3 py-2 text-[13px] leading-relaxed text-ink placeholder-ink-3 transition-colors focus:border-azzurro focus:outline-none"
          />

          <div className="mt-2.5 flex items-center justify-between gap-3">
            {/* Non obbligatorio: costringere a scrivere fa perdere il riscontro. */}
            <span className="text-[11px] text-ink-3">
              Puoi inviare anche senza scrivere nulla.
            </span>
            <button
              onClick={() => manda('non_utile', scelte, motivo)}
              disabled={invio}
              className="shrink-0 rounded-lg bg-azzurro px-3.5 py-1.5 text-[12.5px] font-medium text-white transition-all duration-200 hover:-translate-y-px disabled:cursor-wait disabled:opacity-70 active:translate-y-0"
            >
              {invio ? 'Invio…' : 'Invia'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
