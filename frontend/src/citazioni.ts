import type { Fonte } from './types';

/**
 * Il modello scrive la citazione in prosa e, subito dopo, questo marcatore
 * macchina con gli id esatti dello strumento (non quelli scritti in prosa):
 * {{cita:normaId:articolo:comma}}. Qui si traduce in un riferimento cliccabile,
 * o si scarta se non corrisponde a nessuna fonte davvero consultata - un
 * marcatore inventato non deve mai produrre un link.
 */
const MARCATORE = /\{\{cita:([^:{}]+):([^:{}]*):([^:{}]*)\}\}/g;

function normalizzaComma(c: unknown): string {
  return c === null || c === undefined || c === '' ? '-' : String(c);
}

/**
 * Il numero d'articolo si scrive in piu' modi: l'archivio memorizza "19 bis"
 * con lo spazio, il modello scrive volentieri "19-bis". Sono lo stesso
 * articolo, e confrontarli alla lettera faceva sparire una citazione buona.
 */
function normalizzaArticolo(a: unknown): string {
  if (a === null || a === undefined || a === '') return '-';
  return String(a).toLowerCase().replace(/[\s.\-–]+/g, '');
}

function escapeAttributo(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function inserisciCitazioniInline(testo: string, fonti: Fonte[]): string {
  return testo.replace(MARCATORE, (_m, norma: string, articolo: string, comma: string) => {
    const trovata = fonti.find(
      (f) =>
        String(f.norma) === norma &&
        normalizzaArticolo(f.articolo) === normalizzaArticolo(articolo) &&
        normalizzaComma(f.comma) === normalizzaComma(comma)
    );
    if (!trovata) return '';
    const etichetta = normalizzaComma(comma) === '-' ? articolo : `${articolo}.${comma}`;
    return (
      ` <button type="button" class="cita-inline mx-0.5 inline-flex cursor-pointer items-baseline ` +
      `rounded-md border border-line bg-alloro-3/30 px-1 align-baseline font-mono text-[10px] ` +
      `font-medium text-alloro no-underline transition-colors duration-150 hover:border-dorato-2 ` +
      `hover:bg-alloro-3/60" data-norma="${escapeAttributo(norma)}" ` +
      `data-articolo="${escapeAttributo(articolo)}" data-comma="${escapeAttributo(comma)}">` +
      `[${escapeAttributo(etichetta)}]</button>`
    );
  });
}

/** Risolve il badge cliccato nella fonte corrispondente, per il click delegato sul contenitore. */
export function trovaFonteDaDataset(dataset: DOMStringMap, fonti: Fonte[]): Fonte | undefined {
  const { norma, articolo, comma } = dataset;
  if (!norma || articolo === undefined) return undefined;
  return fonti.find(
    (f) =>
      String(f.norma) === norma &&
      normalizzaArticolo(f.articolo) === normalizzaArticolo(articolo) &&
      normalizzaComma(f.comma) === normalizzaComma(comma)
  );
}

/** Testo semplice, per i riscontri e altri usi non interattivi: via i marcatori macchina. */
export function rimuoviMarcatori(testo: string): string {
  return testo.replace(MARCATORE, '');
}
