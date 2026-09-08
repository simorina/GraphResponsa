import type { Fonte } from '../types';
import { useCallback, useEffect, useState } from 'react';
import { token } from '../auth/cognito';

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
