/**
 * Gli id del grafo ("DD-1-2018", "L-42-2010~2") scritti come li scrive un
 * giurista: "D.D. 1/2018", "L. 42/2010". L'id resta la chiave per tutto il
 * resto - qui si decide solo come si legge in una riga di stato.
 */
const SIGLE: Record<string, string> = {
  L: 'L.',
  LC: 'L.C.',
  LQ: 'L.Q.',
  DD: 'D.D.',
  DL: 'D.L.',
  DR: 'D.R.',
  DC: 'D.C.',
  D: 'D.',
  R: 'Reg.',
};

export function estremi(normaId: unknown): string {
  if (normaId === null || normaId === undefined || normaId === '') return '';
  // "~2" distingue le edizioni dello stesso atto: a chi legge non dice nulla.
  const id = String(normaId).split('~')[0];
  const m = /^([A-Z]+)-(\d+[a-z]*)-(\d{4})$/.exec(id);
  if (!m) return id;
  const [, tipo, numero, anno] = m;
  return `${SIGLE[tipo] ?? tipo} ${numero}/${anno}`;
}

// Legge, legge costituzionale, legge qualificata: femminili. Decreti e
// regolamento: maschili. "L'articolo 3 della D.D. 1/2018" suonava sbagliato
// a chiunque l'avesse letto ad alta voce.
const FEMMINILI = new Set(['L', 'LC', 'LQ']);
const FORME = {
  f: { di: 'della', a: 'alla', nessuna: 'la' },
  m: { di: 'del', a: 'al', nessuna: 'il' },
  atto: { di: 'dell’atto', a: 'all’atto', nessuna: 'l’atto' },
} as const;

/** Gli estremi con l'articolo giusto davanti: "del D.D. 1/2018", "alla L. 42/2010". */
export function conArticolo(normaId: unknown, prep: 'di' | 'a' | 'nessuna'): string {
  const e = estremi(normaId);
  if (!e) return '';
  const tipo = /^([A-Z]+)-/.exec(String(normaId))?.[1];
  const genere = !tipo || !(tipo in SIGLE) ? 'atto' : FEMMINILI.has(tipo) ? 'f' : 'm';
  return `${FORME[genere][prep]} ${e}`;
}
