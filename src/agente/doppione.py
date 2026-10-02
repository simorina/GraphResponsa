"""
Il doppione: quando il gateway tarda a cominciare, parte una seconda richiesta
identica, e vince la prima che risponde.

Il gateway mette in coda le richieste prima di cominciare a generare, e la coda
e' lunga e capricciosa. Misurata il 02/10 su deepseek-v4.1-flash con una
domanda di una riga e il ragionamento spento: da 2,6 a 27 secondi prima del
primo token. Nei checkpoint di produzione questa attesa era un terzo del tempo
di una risposta, e si paga a ogni chiamata - da quattro a undici per domanda.

Due richieste identiche partite insieme aspettano in modo in buona parte
indipendente: su otto coppie, la mediana dell'attesa di una richiesta sola e'
stata 13,1 secondi, quella della piu' rapida delle due 7,4. Quando l'attesa e'
lunga per tutti - due coppie su otto - il doppione non aiuta, ma nemmeno
peggiora.

Si raddoppia solo cio' che tarda: la seconda richiesta parte se la prima non ha
prodotto nulla entro `ritardo_doppione` secondi. Appena una delle due comincia
a rispondere l'altra si chiude, e con lei la connessione, cosi' il gateway
smette di generare. Le due non si mescolano mai: i frammenti che arrivano a chi
chiama sono tutti di una sola.

Il costo e' l'ingresso del doppione, che sul gateway si rilegge in buona parte
dalla cache: per DeepSeek una frazione di centesimo a domanda.
"""
import logging
import queue
import threading
import time

from langchain_openai import ChatOpenAI

# Una riga quando parte il doppione e una quando la gara finisce: nei log di
# produzione dicono quanto spesso serve e se ripaga.
log = logging.getLogger("graphresponsa.doppione")


class ChatConDoppione(ChatOpenAI):
    """ChatOpenAI che lancia una richiesta gemella quando il primo frammento tarda.

    Vale solo in streaming: e' il primo frammento a dire che la coda e' finita.
    Va costruito con `streaming=True`, cosi' anche una chiamata normale passa
    da `_stream`.
    """

    ritardo_doppione: float = 3.0
    """Secondi senza alcun frammento prima di lanciare il doppione; 0 lo spegne."""

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.ritardo_doppione or self.ritardo_doppione <= 0:
            yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
            return

        genitore = super()._stream
        coda: queue.Queue = queue.Queue()
        fermi = {"a": threading.Event(), "b": threading.Event()}

        def corri(chi):
            # I callback dei token restano al chiamante: li chiama solo per chi
            # vince, altrimenti l'utente vedrebbe le due risposte intrecciate.
            flusso = genitore(messages, stop=stop, **kwargs)
            try:
                for pezzo in flusso:
                    if fermi[chi].is_set():
                        return
                    coda.put((chi, pezzo, None))
                coda.put((chi, None, None))
            except BaseException as e:  # noqa: BLE001 - passa al chiamante
                coda.put((chi, None, e))
            finally:
                flusso.close()

        partiti = ["a"]
        threading.Thread(target=corri, args=("a",), daemon=True).start()
        scadenza = time.monotonic() + self.ritardo_doppione
        finiti, errori = set(), {}
        vincitore = primo = None
        try:
            while vincitore is None:
                attesa = None if "b" in partiti else max(0.0, scadenza - time.monotonic())
                try:
                    chi, pezzo, errore = coda.get(timeout=attesa)
                except queue.Empty:
                    partiti.append("b")
                    threading.Thread(target=corri, args=("b",), daemon=True).start()
                    log.info("doppione: %s tace da %.1fs, parte la richiesta gemella",
                             self.model_name, self.ritardo_doppione)
                    continue
                if pezzo is not None:
                    vincitore, primo = chi, pezzo
                    break
                # Finito senza dare nulla: per un errore o con una risposta vuota.
                finiti.add(chi)
                if errore is not None:
                    errori[chi] = errore
                if any(c not in finiti for c in partiti):
                    continue
                # Nessuno ha risposto. Se il primo e' caduto prima della scadenza
                # il doppione non e' mai partito, e va bene cosi': un rifiuto del
                # filtro o una richiesta non valida si ripeterebbero uguali.
                if errori:
                    raise errori.get("a") or next(iter(errori.values()))
                return

            for altro in partiti:
                if altro != vincitore:
                    fermi[altro].set()
            if "b" in partiti:
                log.info("doppione: vince %s, primo frammento a %.1fs",
                         "la gemella" if vincitore == "b" else "la prima",
                         time.monotonic() - scadenza + self.ritardo_doppione)
            if run_manager:
                run_manager.on_llm_new_token(primo.text, chunk=primo)
            yield primo
            while True:
                chi, pezzo, errore = coda.get()
                if chi != vincitore:
                    continue
                if errore is not None:
                    raise errore
                if pezzo is None:
                    return
                if run_manager:
                    run_manager.on_llm_new_token(pezzo.text, chunk=pezzo)
                yield pezzo
        finally:
            # Se chi legge smette prima della fine, le richieste ancora aperte si
            # chiudono al prossimo frammento invece di generare per niente.
            for evento in fermi.values():
                evento.set()
