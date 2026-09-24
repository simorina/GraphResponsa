/**
 * Accesso a Cognito con email e password, senza Hosted UI.
 *
 * Si parla direttamente con l'API di Cognito Identity Provider: sono due
 * chiamate JSON, e non serve nessuna libreria. La password viaggia su TLS.
 * SRP eviterebbe di mandarla del tutto, ma richiederebbe crittografia nel
 * browser per un guadagno marginale visto che TLS e' comunque obbligatorio.
 *
 * Al backend si manda l'ID token, non l'access token: Cognito mette il client
 * in `aud` solo nel primo, ed e' quello che `identita.py` verifica.
 */

const CLIENT = import.meta.env.VITE_COGNITO_CLIENT as string;
const REGIONE = (import.meta.env.VITE_COGNITO_REGIONE as string) || 'eu-central-1';
const ENDPOINT = `https://cognito-idp.${REGIONE}.amazonaws.com/`;

const CHIAVE_TOKEN = 'gr_sessione';

/**
 * Se un errore viene dalla rete e non da un server che ha risposto.
 *
 * `fetch` senza connessione non restituisce una risposta: lancia un TypeError,
 * con un testo diverso per browser - "Failed to fetch" in Chrome, "Load
 * failed" in Safari, "NetworkError when attempting to fetch resource" in
 * Firefox.
 */
export function erroreDiRete(e: unknown): boolean {
  return e instanceof TypeError && /fetch|network|load failed/i.test(e.message);
}

/** I rifiuti che chiudono davvero la sessione: il rinnovo e' revocato o
 *  scaduto, o l'utente non puo' piu' entrare. Tutto il resto - rete assente,
 *  Cognito in difficolta', troppe richieste - e' passeggero. */
const SESSIONE_FINITA = new Set([
  'NotAuthorizedException',
  'UserNotFoundException',
  'UserNotConfirmedException',
  'PasswordResetRequiredException',
]);

/** Il rinnovo non e' riuscito per ragioni passeggere: la sessione resta. */
const PASSEGGERO = Symbol('rinnovo passeggero');

export interface Sessione {
  idToken: string;
  refreshToken: string;
  scadenza: number;
}

/** Il primo accesso con la password temporanea richiede di sceglierne una nuova. */
export interface NuovaPasswordRichiesta {
  tipo: 'nuova_password';
  sessione: string;
  email: string;
}

export function configurato(): boolean {
  return Boolean(CLIENT);
}

// --- Trasporto ----------------------------------------------------------

async function chiama(azione: string, corpo: Record<string, unknown>) {
  const r = await fetch(ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `AWSCognitoIdentityProviderService.${azione}`,
    },
    body: JSON.stringify(corpo),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const tipo = (d.__type || '').split('#').pop();
    throw new ErroreAccesso(tipo, d.message || 'Accesso non riuscito.');
  }
  return d;
}

export class ErroreAccesso extends Error {
  constructor(public tipo: string, messaggio: string) {
    super(messaggio);
  }

  /**
   * Il messaggio da mostrare.
   *
   * Credenziali sbagliate e utente inesistente danno la stessa frase di
   * proposito: distinguerli direbbe a un estraneo quali indirizzi sono
   * registrati.
   */
  get leggibile(): string {
    switch (this.tipo) {
      case 'NotAuthorizedException':
      case 'UserNotFoundException':
        return 'Email o password non corrette.';
      case 'PasswordResetRequiredException':
        return 'La password va reimpostata. Contatta l’amministratore.';
      case 'UserNotConfirmedException':
        return 'Account non ancora confermato.';
      case 'TooManyRequestsException':
      case 'LimitExceededException':
        return 'Troppi tentativi. Attendi qualche minuto.';
      case 'InvalidPasswordException':
        return 'La password non rispetta i requisiti richiesti.';
      default:
        return this.message;
    }
  }
}

// --- Sessione -----------------------------------------------------------

function leggi(): Sessione | null {
  try {
    const grezzo = localStorage.getItem(CHIAVE_TOKEN);
    return grezzo ? (JSON.parse(grezzo) as Sessione) : null;
  } catch {
    return null;
  }
}

function scrivi(s: Sessione | null) {
  try {
    if (s) localStorage.setItem(CHIAVE_TOKEN, JSON.stringify(s));
    else localStorage.removeItem(CHIAVE_TOKEN);
  } catch {
    /* archiviazione negata: la sessione resta valida solo per questa scheda */
  }
}

function daRisultato(r: any, precedente?: Sessione | null): Sessione {
  return {
    idToken: r.IdToken,
    // Nel rinnovo Cognito non rimanda il refresh token: si tiene il vecchio.
    refreshToken: r.RefreshToken || precedente?.refreshToken || '',
    scadenza: Date.now() + (r.ExpiresIn ?? 3600) * 1000,
  };
}

// --- Accesso ------------------------------------------------------------

export async function accedi(
  email: string,
  password: string
): Promise<'dentro' | NuovaPasswordRichiesta> {
  const d = await chiama('InitiateAuth', {
    AuthFlow: 'USER_PASSWORD_AUTH',
    ClientId: CLIENT,
    AuthParameters: { USERNAME: email.trim(), PASSWORD: password },
  });

  if (d.ChallengeName === 'NEW_PASSWORD_REQUIRED') {
    return { tipo: 'nuova_password', sessione: d.Session, email: email.trim() };
  }
  if (!d.AuthenticationResult) {
    throw new ErroreAccesso('ChallengeNonGestita', 'Questo account richiede una verifica non supportata.');
  }
  scrivi(daRisultato(d.AuthenticationResult));
  return 'dentro';
}

export async function impostaNuovaPassword(
  richiesta: NuovaPasswordRichiesta,
  password: string
): Promise<void> {
  const d = await chiama('RespondToAuthChallenge', {
    ChallengeName: 'NEW_PASSWORD_REQUIRED',
    ClientId: CLIENT,
    Session: richiesta.sessione,
    ChallengeResponses: { USERNAME: richiesta.email, NEW_PASSWORD: password },
  });
  if (!d.AuthenticationResult) {
    throw new ErroreAccesso('ChallengeNonGestita', 'Non è stato possibile completare l’accesso.');
  }
  scrivi(daRisultato(d.AuthenticationResult));
}

async function rinnova(s: Sessione): Promise<Sessione | null | typeof PASSEGGERO> {
  if (!s.refreshToken) return null;
  try {
    const d = await chiama('InitiateAuth', {
      AuthFlow: 'REFRESH_TOKEN_AUTH',
      ClientId: CLIENT,
      AuthParameters: { REFRESH_TOKEN: s.refreshToken },
    });
    if (!d.AuthenticationResult) return null;
    const nuova = daRisultato(d.AuthenticationResult, s);
    scrivi(nuova);
    return nuova;
  } catch (e) {
    // Solo un rifiuto esplicito di Cognito chiude la sessione. Prima ogni
    // errore la chiudeva, compreso quello di rete: aprire l'app senza
    // connessione cancellava il rinnovo, e al ritorno della rete bisognava
    // rimettere la password.
    if (e instanceof ErroreAccesso && SESSIONE_FINITA.has(e.tipo)) return null;
    return PASSEGGERO;
  }
}

/**
 * Il token da mettere in Authorization, rinnovato se sta per scadere.
 * Restituisce null se non c'e' sessione: il chiamante mostra l'accesso.
 */
export async function token(): Promise<string | null> {
  if (!configurato()) return null;
  let s = leggi();
  if (!s) return null;

  // Un minuto di margine: un token che scade a meta' di una consultazione
  // lunga chiuderebbe lo stream senza spiegazioni.
  if (Date.now() > s.scadenza - 60_000) {
    const rinnovata = await rinnova(s);
    if (rinnovata === PASSEGGERO) {
      // La sessione resta dov'e' e si riprova alla prossima richiesta. Il
      // token vecchio vale finche' non scade davvero: il rinnovo parte un
      // minuto prima.
      return Date.now() < s.scadenza ? s.idToken : null;
    }
    if (!rinnovata) {
      scrivi(null);
      return null;
    }
    s = rinnovata;
  }
  return s.idToken;
}

export function autenticato(): boolean {
  return Boolean(leggi());
}

export function esci(): void {
  scrivi(null);
  window.location.reload();
}

/** Le rivendicazioni dell'ID token, per mostrare nome e mail senza chiamare il server. */
export function profilo(): { nome: string; email: string } | null {
  const s = leggi();
  if (!s) return null;
  try {
    const c = JSON.parse(atob(s.idToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return { nome: c.name || c['cognito:username'] || c.email || '', email: c.email || '' };
  } catch {
    return null;
  }
}
