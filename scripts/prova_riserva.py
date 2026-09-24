"""La catena delle riserve, provata senza grafo e senza rete.

    .venv\\Scripts\\python.exe scripts\\prova_riserva.py

Il filtro sui contenuti del gateway Alibaba respinge richieste legittime, e lo
fa a intermittenza: il 24/09/2026 ha respinto "quali incentivi sono previsti
per i giovani imprenditori" due volte di fila su deepseek-v4.1-flash e poi
l'ha lasciata passare alla terza, e nello stesso pomeriggio ha respinto
deepseek-v4-pro-0813 su una domanda a cui lo stesso Pro aveva appena risposto.
Non e' il difetto di un modello: e' la piattaforma. Per questo la catena
finisce fuori dal gateway.

E' un percorso che si rompe in silenzio - nessuno se ne accorge finche' un
utente non incontra il filtro - quindi va provato.
"""
import os
import pathlib
import sys

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RADICE), str(RADICE / "src")]
os.environ["TABELLA_CHECKPOINT"] = ""
os.environ["TABELLA_SCRITTURE"] = ""
os.environ.setdefault("MODELLO", "deepseek-v4.1-flash")

from src.agente import agente as A  # noqa: E402

RIFIUTO = ("Error code: 400 - {'error': {'code': 'data_inspection_failed', "
           "'message': 'Input text data may contain inappropriate content.'}}")


class Finto:
    """Sta al posto del grafo: annota chi viene chiamato e con cosa."""

    chiamate = []

    def __init__(self, nome, rifiutano):
        self.nome, self.rifiutano = nome, rifiutano

    def stream(self, ingresso, config=None, stream_mode=None):
        Finto.chiamate.append((self.nome, ingresso))
        yield {"modello": {"messages": []}}
        if self.nome in self.rifiutano:
            raise RuntimeError(RIFIUTO)


def scorri(rifiutano):
    """Fa girare il flusso fingendo che questi modelli vengano respinti."""
    Finto.chiamate = []
    passaggi = []
    A.agente = lambda nome=None: Finto(nome or A.MODELLO, rifiutano)
    pezzi = list(A._flusso({"configurable": {"thread_id": "prova"}},
                           {"messages": [{"role": "user", "content": "ciao"}]},
                           passaggi.append))
    return [n for n, _ in Finto.chiamate], [i for _, i in Finto.chiamate], passaggi, pezzi


def prova():
    errori = 0
    vero = A.agente
    primo, *riserve = [A.MODELLO] + A.RISERVE

    def verifica(etichetta, esito, atteso):
        nonlocal errori
        ok = esito == atteso
        errori += not ok
        print(f'  {"OK " if ok else "NO "} {etichetta:<40} {esito}'
              f'{"" if ok else f"  (atteso {atteso})"}')

    # 1. si riconosce il rifiuto del filtro, e solo quello
    for etichetta, errore, atteso in [
            ("filtro dei contenuti", RuntimeError(RIFIUTO), True),
            ("connessione persa", RuntimeError("connection reset by peer"), False),
            ("tetto dei giri", RuntimeError("Recursion limit of 48 reached"), False)]:
        verifica(f"riconoscimento: {etichetta}", A._rifiuto_di_contenuto(errore), atteso)

    # 2. nessun rifiuto: si resta sul primo modello
    nomi, ingressi, passaggi, pezzi = scorri(set())
    verifica("senza rifiuti resta sul primo", nomi, [primo])
    verifica("nessun passaggio segnalato", passaggi, [])

    # 3. il primo viene respinto: subentra la prima riserva, dal checkpoint
    nomi, ingressi, passaggi, pezzi = scorri({primo})
    verifica("respinto il primo", nomi, [primo, riserve[0]])
    verifica("la riserva riprende dal checkpoint", ingressi[1:], [None])
    verifica("il passaggio porta il nome", passaggi, [riserve[0]])

    # 4. respinti primo e riserva: si esce dal gateway
    nomi, ingressi, passaggi, pezzi = scorri({primo, riserve[0]})
    verifica("respinti i primi due", nomi, [primo] + riserve)
    verifica("tutte riprendono dal checkpoint", ingressi[1:], [None] * len(riserve))
    verifica("i pezzi arrivano da tutti", len(pezzi), len(riserve) + 1)

    # 5. respinti tutti: l'errore arriva all'utente, non si finge nulla
    try:
        scorri({primo, *riserve})
        print("  NO  respinti tutti: l'errore e' stato inghiottito")
        errori += 1
    except RuntimeError:
        print("  OK  respinti tutti: l'errore viene rilanciato")

    # 6. un errore qualunque non fa scorrere la catena
    Finto.chiamate = []
    A.agente = lambda nome=None: FintoRotto(nome or A.MODELLO)
    try:
        list(A._flusso({"configurable": {"thread_id": "prova"}}, {"messages": []},
                       lambda _nome: None))
        print("  NO  un errore di rete e' stato inghiottito")
        errori += 1
    except RuntimeError:
        verifica("un errore di rete non cambia modello",
                 [n for n, _ in Finto.chiamate], [primo])

    A.agente = vero
    print("\nfallite:", errori)
    return 1 if errori else 0


class FintoRotto:
    def __init__(self, nome):
        Finto.chiamate.append((nome, None))
        self.nome = nome

    def stream(self, ingresso, config=None, stream_mode=None):
        raise RuntimeError("connection reset by peer")
        yield  # pragma: no cover


if __name__ == "__main__":
    sys.exit(prova())
