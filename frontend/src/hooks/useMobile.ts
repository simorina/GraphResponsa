import { useEffect, useState } from 'react';

/** La soglia oltre cui l'interfaccia smette di essere "da telefono". */
const STRETTO = '(max-width: 767px)';

/**
 * Se lo schermo e' stretto, e lo resta anche quando il telefono ruota.
 *
 * Prima la larghezza si leggeva una volta sola con `window.innerWidth`: girando
 * il telefono la barra laterale restava chiusa su uno schermo ormai largo, o
 * copriva la chat su uno ormai stretto, e l'unico rimedio era ricaricare.
 */
export function useSchermoStretto(): boolean {
  const [stretto, setStretto] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(STRETTO).matches);

  useEffect(() => {
    const m = window.matchMedia(STRETTO);
    const cambia = (e: MediaQueryListEvent) => setStretto(e.matches);
    m.addEventListener('change', cambia);
    setStretto(m.matches);
    return () => m.removeEventListener('change', cambia);
  }, []);

  return stretto;
}

/**
 * Il tasto indietro chiude il pannello, invece di uscire dall'applicazione.
 *
 * Su Android il tasto indietro e' il gesto con cui si chiude qualunque cosa si
 * sia aperta, ed e' anche il bordo su cui si striscia. Senza questo, con una
 * fonte aperta si usciva da Responsa: si tornava indietro di una pagina intera
 * perdendo la consultazione. Si lascia un segno nella cronologia all'apertura e
 * lo si consuma alla chiusura, cosi' avanti e indietro restano in pari.
 */
export function useChiusuraIndietro(aperto: boolean, chiudi: () => void) {
  useEffect(() => {
    if (!aperto) return;
    window.history.pushState({ pannello: true }, '');

    const torna = () => chiudi();
    window.addEventListener('popstate', torna);

    return () => {
      window.removeEventListener('popstate', torna);
      // Chiuso in un altro modo - il velo, la X, il trascinamento - il segno
      // resterebbe li' e il primo "indietro" non farebbe nulla di visibile.
      // Il listener e' gia' staccato, quindi questo passo non richiama chiudi().
      if (window.history.state?.pannello) window.history.back();
    };
  }, [aperto, chiudi]);
}
