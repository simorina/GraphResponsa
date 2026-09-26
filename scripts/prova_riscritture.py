"""Le prove del riconoscimento delle novelle (strumenti._riscrive), sui commi
veri del grafo.

    .venv\\Scripts\\python.exe scripts\\prova_riscritture.py

Non tocca ne' il grafo ne' le API: sono stringhe e funzioni pure. Il flag
`riscrive` dice all'agente quale atto successivo ha cambiato un articolo, e
sbagliarlo in un senso fa contare modifiche mai avvenute (la L. 128/1997 sulla
L. 30/1977, 25/09/2026), nell'altro fa tacere un'abrogazione.
"""
import os
import pathlib
import sys

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RADICE), str(RADICE / "src")]
os.environ["TABELLA_CHECKPOINT"] = ""
os.environ["TABELLA_SCRITTURE"] = ""

from src.agente.strumenti import _riscrive  # noqa: E402

CODICE_PENALE = (17, "emanazione del nuovo codice penale")

L_128_1997 = (
    "Il primo comma dell'articolo 42 della Legge 22 dicembre 1972 n.41 è così modificato: \"Dal 1° "
    "gennaio 1998 il dipendente assente per malattia ha diritto al percepimento dell'indennità per "
    "inabilità temporanea al lavoro prevista dall'articolo 1 della Legge 7 giugno 1977 n.30 ed erogata "
    "secondo le modalità previste dagli articoli 2 e 3 della Legge 7 giugno 1977 n.30. Superato il "
    "180° giorno di malattia il dipendente si intende collocato in aspettativa per malattia per un "
    "massimo di un anno con diritto a percepire l'86% dell'indennità economica succitata.\". Fermo "
    "restando quanto previsto dal primo comma dell'articolo 53 della Legge 22 dicembre 1972 n.41, "
    "l'Amministrazione può effettuare le eventuali operazioni di compensazione tra la retribuzione "
    "corrisposta e l'indennità dovuta.")

L_71_2014 = (
    "Sono abrogati: - Legge 11 settembre 1961 n.27 “Legge per la tutela dell’apprendistato”; - "
    "articoli 10, 11, 12, 20 e 25 del Decreto-Legge 5 ottobre 2011 n.156 “Interventi urgenti per la "
    "semplificazione e l’efficienza del mercato del lavoro” e l’articolo 5 del Decreto Delegato 26 "
    "luglio 2010 n.132; - Legge 24 luglio 1987 n.89 “Normativa in materia di formazione "
    "professionale” e Legge 4 marzo 1993 n.36 “Integrazioni e modifiche della Legge 24 luglio 1987 "
    "n.89 “Normativa in materia di formazione professionale” fatto salvo quanto previsto "
    "all’articolo 22 della presente legge; - gli articoli 20, 25, 26 e 27 della Legge 31 marzo 2010 "
    "n.73 “Riforma degli ammortizzatori sociali e nuove misure economiche per l’occupazione e "
    "l’occupabilità”; - Decreto-Legge 6 marzo 2013 n.19 “Disposizioni urgenti a tutela dei "
    "lavoratori coinvolti in procedure di riduzione di personale”.")

L_125_2014 = (
    "Sono abrogate tutte le norme in contrasto con la presente legge ed in particolare: - la Legge 30 "
    "novembre 1992 n.87; - la Legge 16 gennaio 2001 n.9; - il Decreto Delegato 10 agosto 2012 n.129. "
    "- articolo 60 Allegato A della Legge 5 dicembre 2011 n. 188. - articolo 99 della Legge 22 "
    "dicembre 2010 n.194.")

DD_110_2024 = (
    "Il comma 1, dell’articolo 44 della Legge n.157/2022 è così sostituito: “1. Con l’entrata in "
    "vigore della presente legge sono definitivamente abrogati: a) l’articolo 32, comma 6 della Legge "
    "11 febbraio 1983 n.15; b) l’articolo 11 della Legge 20 novembre 1987 n.138; c) l’articolo 22 "
    "della Legge 20 dicembre 1990 n.156.”.")

L_158_2011 = (
    "A decorrere dal 1° gennaio 2012 l’articolo 33 della Legge 11 febbraio 1983 n.15 viene abrogato e "
    "così sostituito: “I superstiti di cui all’articolo 15 della Legge 11 febbraio 1983 n.15 hanno "
    "diritto ad una prestazione da calcolarsi sull’importo della pensione spettante al “dante causa” "
    "pensionato od assicurato, al momento del decesso.”")

DL_154_2020 = (
    "Nel Titolo Quarto del Libro Secondo del Codice Penale, dopo l'articolo 340 è inserito il "
    "seguente Capitolo I-bis: “Capitolo I-bis REATI DI TERRORISMO Art. 340-bis (Finalità di "
    "terrorismo) Sono considerate con finalità di terrorismo le condotte che, per loro natura o "
    "contesto, possono arrecare un grave danno a un Paese, fermo quanto previsto all'articolo 1.”")

D_41_2005 = (
    "Ai sensi e agli effetti delle Leggi 13 ottobre 1984 n.91, 30 dicembre 1986 n.155, 22 gennaio "
    "1993 n.9, 18 dicembre 2003 n.165 è modificato il punto j) Dichiarazione della rendita catastale "
    "- Mod. IGR \"I\" dell'art.1 del Decreto 17 aprile 2002 n.54 e successive modifiche, ed approvato "
    "il modello allegato sotto la lettera \"A\" al presente Decreto.")

DC_37_2001 = (
    "Il valore nominale delle quote od azioni delle società od impresa unipersonale è di un EURO o "
    "suoi multipli\". e. L'ultimo comma dell'articolo 7 della Legge 29 novembre 1991 n. 149 è "
    "sostituito dal seguente: \"Il capitale sociale, in ogni caso, è frazionato in quote il cui "
    "valore nominale non può essere inferiore a quanto previsto dall'articolo 3 della Legge 29 "
    "novembre 1991 n. 149.\"")

L_35_1984 = (
    "Gli articoli 28 della Legge 16 marzo 1922 n. 10 e 3 della Legge 4 maggio 1977 n. 22 sono "
    "modificati come segue: \"Tutti i soggetti obbligati alla compilazione annuale del Bilancio di "
    "esercizio devono operare una ritenuta del 13%.\"")

# (nome, testo, numero dell'atto citato, titolo, articolo citato, atteso)
CASI = [
    # Il caso da cui e' partito tutto: rimandi dentro il testo nuovo.
    ("rimando nel testo nuovo (L.30/1977 art.2)", L_128_1997, 30, "", "2", False),
    ("rimando nel testo nuovo (L.30/1977 art.1)", L_128_1997, 30, "", "1", False),
    ("il bersaglio della stessa novella", L_128_1997, 41, "", "42", True),
    ("rimando fuori dalle virgolette", L_128_1997, 41, "", "53", False),
    ("stesso atto, articolo solo nominato", L_158_2011, 15, "", "15", False),
    ("abrogato e cosi' sostituito", L_158_2011, 15, "", "33", True),
    # Gli elenchi di abrogazioni: i bersagli vengono dopo i due punti.
    ("elenco dopo i due punti", "Sono abrogati: a) l’articolo 15 dell’Allegato A alla Legge "
     "n.188/2011; c) l’articolo 58 del Decreto 24 aprile 2003 n.53 come sostituito dall’articolo 6 "
     "del Decreto Delegato 29 aprile 2022 n.73.", 53, "", "58", True),
    ("elenco con virgolette annidate male", L_71_2014, 73, "", "20", True),
    ("elenco con i punti fra le voci", L_125_2014, 194, "", "99", True),
    ("abrogazione nel testo nuovo", DD_110_2024, 138, "", "11", True),
    ("il bersaglio che riscrive l'elenco", DD_110_2024, 157, "", "44", True),
    ("abrogazione di un atto intero, dopo", "Il presente decreto delegato, in applicazione "
     "dell’articolo 43, comma 3, della Legge 22 dicembre 2021 n.207, è diretto ad aggiornare le "
     "disposizioni. Esso sostituisce la Legge 24 novembre 1887, che pertanto è abrogata.",
     207, "", "43", False),
    # Gli atti nominati per nome, gli articoli inseriti.
    ("Codice Penale per nome", "L’articolo 204 bis del Codice Penale è così sostituito: “Art. 204 "
     "bis (Uso indebito di strumenti di pagamento)”", *CODICE_PENALE, "204-bis", True),
    ("articolo inserito, intitolato", DL_154_2020, *CODICE_PENALE, "340-bis", True),
    ("rimando minuscolo nel testo inserito", DL_154_2020, *CODICE_PENALE, "1", False),
    # Le forme che spezzavano la frase o rovesciavano le virgolette.
    ("intestazione chiusa dal punto", "All'articolo 5 della Legge 27 marzo 1981 n.26 sono "
     "apportate le modifiche che seguono. Il primo comma è abrogato e sostituito dal seguente: "
     "\"La superficie minima e' di 80 mq.\"", 26, "", "5", True),
    ("abbreviazione 'Mod.'", D_41_2005, 54, "", "1", True),
    ("comma che comincia in una citazione", DC_37_2001, 149, "", "7", True),
    ("...e il rimando che ne segue", DC_37_2001, 149, "", "3", False),
    ("numero d'atto non e' un articolo", L_35_1984, 22, "", "10", False),
    ("articolo in un elenco 'gli articoli X e Y'", L_35_1984, 22, "", "3", True),
    ("nessuna formula", "In riferimento al comma 1 dell’articolo 3-ter della Legge 13 ottobre 1984 "
     "n.91, i redditi prodotti all’estero sono imponibili.", 91, "", "3-ter", False),
]


def prova():
    errori = 0
    for nome, testo, numero, titolo, articolo, atteso in CASI:
        esito = _riscrive(testo, numero, titolo, articolo)
        ok = esito == atteso
        errori += not ok
        print(f'  {"OK " if ok else "NO "} {nome:<44} {esito} (atteso {atteso})')
    print("\nfallite:", errori)
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(prova())
