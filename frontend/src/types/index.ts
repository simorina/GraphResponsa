export interface Fonte {
  norma: string;
  titoloNorma?: string;
  articolo: string | number;
  rubrica?: string;
  comma: string | number;
  testo: string;
}

export interface ThoughtStep {
  type: 'call' | 'result';
  name: string;
  args?: Record<string, any>;
  count?: number;
  error?: string | null;
  time?: Date;
}

export interface FineInfo {
  tokenIn: number;
  tokenOut: number;
  costo: number;
  conversazione: string;
}

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  thoughts?: ThoughtStep[];
  fonti?: Fonte[];
  fine?: FineInfo | null;
  error?: string | null;
  isStreaming?: boolean;
  timestamp?: Date;
}

export interface GraphStats {
  ok: boolean;
  conTesto: number;
  soloCitate: number;
  totaleNorme: number;
  articoli: number;
  commi: number;
  allegati?: number;
  totaleNodi: number;
  totaleRelazioni: number;
}
