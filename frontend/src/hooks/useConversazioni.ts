import type { Fonte } from '../types';
import { useCallback, useEffect, useState } from 'react';
import { configurato, token } from '../auth/cognito';

export interface VoceConversazione {
  conversazione: string;
  titolo: string;
  aggiornata: string;
  messaggi: number;
}

export interface Consumi {
  richiesteOggi: number;
  limiteGiorno: number;
  costoMese: number;
  limiteMese: number;
  /** Istanti assoluti in cui i due contatori ripartono (mezzanotte di Roma,
   *  primo del mese). Sono istanti e non durate perche' la pagina resta
   *  aperta per ore: il conto alla rovescia lo rifa' il browser. */
  azzeraGiorno: string;
  azzeraMese: string;
}

export interface Profilo {
  nome: string;
  email: string;
}

type Stato =
  | { fase: 'attesa' }
  | { fase: 'pronto'; voci: VoceConversazione[]; consumi: Consumi | null; utente: Profilo | null }
  | { fase: 'errore' };

/**
 * Lo storico delle consultazioni, dal backend.
 *
 * Prima la barra laterale mostrava solo la conversazione in corso e dichiarava
 * che lo storico si azzera al riavvio: da quando i checkpoint stanno su
 * DynamoDB non e' piu' vero, ed era la cosa peggiore che l'interfaccia potesse
 * dire - un'informazione falsa sul funzionamento del sistema.
 */
export function useConversazioni() {
  const [stato, setStato] = useState<Stato>({ fase: 'attesa' });

  const ricarica = useCallback(async (segnale?: AbortSignal) => {
    try {
      const t = await token();
      // Senza token non si chiama: l'effetto di montaggio parte prima
      // dell'accesso, e il server risponderebbe 401 - un errore in console a
      // ogni caricamento, e la barra laterale in stato di errore invece che in
      // attesa. Con Cognito spento (sviluppo senza identita') `token()` da'
      // null ma la chiamata va fatta lo stesso: li' l'utente e' `locale`.
      if (configurato() && !t) {
        setStato({ fase: 'attesa' });
        return;
      }
      const r = await fetch('/conversazioni', {
        signal: segnale,
        headers: t ? { Authorization: `Bearer ${t}` } : {},
      });
      if (!r.ok) throw new Error(String(r.status));
      const d = await r.json();
      setStato({
        fase: 'pronto',
        voci: d.conversazioni ?? [],
        consumi: d.consumi ?? null,
        utente: d.utente ?? null,
      });
    } catch (e: any) {
      if (e?.name !== 'AbortError') setStato({ fase: 'errore' });
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    ricarica(ctrl.signal);
    return () => ctrl.abort();
  }, [ricarica]);

  return { stato, ricarica };
}

/** I messaggi di una consultazione passata, ricostruiti dal checkpoint. */
export async function caricaConversazione(id: string) {
  const t = await token();
  const r = await fetch(`/conversazioni/${id}`, {
    headers: t ? { Authorization: `Bearer ${t}` } : {},
  });
  if (!r.ok) throw new Error(`Il server ha risposto ${r.status}.`);
  const d = await r.json();
  // Le fonti arrivano insieme al testo: senza, il renderer scarta i marcatori
  // e ricaricando la pagina le citazioni sparivano dalla risposta.
  return (d.messaggi ?? []) as {
    role: 'user' | 'assistant';
    content: string;
    fonti?: Fonte[];
  }[];
}
