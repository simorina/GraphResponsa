/**
 * Il tema, chiaro o scuro, scelto a mano.
 *
 * Si parte sempre chiari, anche col sistema in modo scuro: e' una scelta di
 * chi usa Responsa, e un'interfaccia che cambia colore da sola quando il
 * telefono passa alla notte sorprende. Lo scuro si accende dal cassetto, e il
 * browser se lo ricorda.
 *
 * La pagina d'accesso e' sempre chiara, qualunque sia la scelta: per questo
 * mostrare un tema (mostraTema) e salvare la preferenza (applicaTema) sono due
 * cose distinte. L'accesso mostra il chiaro senza toccare la scelta, e al
 * rientro torna lo scuro.
 *
 * Il tema vive come attributo su <html> (data-tema="scuro"). I colori sono
 * token CSS, e il blocco del tema scuro li ridefinisce, uguale per telefono
 * e desktop.
 * L'attributo lo mette gia' uno script in index.html prima del primo disegno:
 * se lo mettesse React, chi ha scelto lo scuro vedrebbe un lampo bianco a ogni
 * apertura.
 */
import { useCallback, useState } from 'react';

export type Tema = 'chiaro' | 'scuro';

const CHIAVE = 'gr_tema';

/** Il colore della barra del browser col tema scuro: il fondo della pagina. */
const BARRA_SCURA = '#0f171d';

/** Il tema che si vede adesso. */
export function temaAttuale(): Tema {
  return document.documentElement.dataset.tema === 'scuro' ? 'scuro' : 'chiaro';
}

/** Il tema scelto da chi usa Responsa: vale dentro l'app. */
export function temaSalvato(): Tema {
  try {
    return localStorage.getItem(CHIAVE) === 'scuro' ? 'scuro' : 'chiaro';
  } catch {
    return 'chiaro';
  }
}

/** Sceglie il tema: lo mostra e lo ricorda. */
export function applicaTema(tema: Tema): void {
  try {
    localStorage.setItem(CHIAVE, tema);
  } catch {
    /* archiviazione negata: il tema vale per questa scheda */
  }
  mostraTema(tema);
}

/** Mostra un tema senza toccare la scelta salvata. */
export function mostraTema(tema: Tema): void {
  const radice = document.documentElement;
  if (tema === 'scuro') radice.dataset.tema = 'scuro';
  else delete radice.dataset.tema;

  // La barra del browser. Vince il primo meta theme-color, quindi quello dello
  // scuro va in cima e si toglie tornando al chiaro: sotto resta quello del
  // chiaro, scritto in index.html.
  document.querySelectorAll('meta[name="theme-color"][data-tema]').forEach((m) => m.remove());
  if (tema === 'scuro') {
    const m = document.createElement('meta');
    m.name = 'theme-color';
    m.content = BARRA_SCURA;
    m.dataset.tema = 'scuro';
    document.head.prepend(m);
  }
}

/** Il tema attuale e la funzione che lo inverte. */
export function useTema(): [Tema, () => void] {
  const [tema, setTema] = useState<Tema>(temaSalvato);
  const cambia = useCallback(() => {
    const nuovo: Tema = temaSalvato() === 'scuro' ? 'chiaro' : 'scuro';
    applicaTema(nuovo);
    setTema(nuovo);
  }, []);
  return [tema, cambia];
}
