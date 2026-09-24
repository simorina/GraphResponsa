"""Le prove dei due controlli sulle citazioni, sui testi veri prodotti dai
modelli il 23 e 24/09/2026.

    .venv\\Scripts\\python.exe scripts\\prova_citazioni.py

Non tocca ne' il grafo ne' le API: sono stringhe e funzioni pure. Serve a non
riaprire i buchi gia' chiusi - una fonte inventata che passa il controllo, o un
allarme falso su un testo di legge citato per esteso.
"""
import os
import pathlib
import sys

RADICE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RADICE), str(RADICE / "src")]
# Prima dell'import dell'agente: le prove non devono toccare i checkpoint veri.
os.environ["TABELLA_CHECKPOINT"] = ""
os.environ["TABELLA_SCRITTURE"] = ""

from src.agente.agente import (_citazioni_discordi,          # noqa: E402
                               _citazioni_non_verificate)

# Gli atti che gli strumenti hanno davvero restituito nella consultazione.
VISTE = ("DD-80-2015 DD-173-2014 D-32-1996 D-101-1999 D-86-1995 D-63-1995 "
         "DD-88-2022 R-2-2025 R-3-2026 L-68-1989 L-87-2026 L-64-2025")

# (nome, testo, quante segnalazioni attese)
DISCORDI = [
    # Qwen3.7-Plus, 24/09: l'art. 33 del D. 63/1995 non esiste, il decreto
    # finisce al 18, e il 18 comma 2 parla della composizione del Consiglio.
    ("articolo inventato", "- Ingegneri e Architetti – D. 63/1995, art. 33"
     "{{cita:D-63-1995:18:2}}", 1),
    ("atto e articolo sbagliati insieme", "- D. 43/1995 (Ingegneri e Architetti), "
     "art. 33{{cita:D-63-1995:18:2}}", 2),
    ("atto sbagliato, articolo giusto", "- DD. 145/2014 (Periti Industriali), "
     "art. 31{{cita:DD-173-2014:31:4}}", 1),
    ("secondo articolo inventato", "- D. 86/1995 (Geologi), art. 33"
     "{{cita:D-86-1995:8:2}}", 1),
    # Forme corrette: qui il controllo deve tacere.
    ("la forma prescritta dalle istruzioni", "...L. 87/2026, art. 7, comma 2"
     "{{cita:L-87-2026:7:2}}, che stabilisce...", 0),
    ("articolo d'allegato, prosa con l'id del grafo",
     "- Infermieri – D.D. 88/2022, art. all2-30, "
     "comma 4{{cita:DD-88-2022:all2-30:4}}", 0),
    # DeepSeek-V4.1-Flash, 24/09: la prosa scrive il numero dell'articolo e il
    # marcatore l'id del grafo. Dicono la stessa cosa.
    ("articolo d'allegato, prosa con il numero",
     "Dottori Commercialisti (DD. 29 dicembre 2010 n. 201, allegato, art. 36, "
     "comma 3{{cita:DD-201-2010:all-36:3}})", 0),
    # Il decreto ratificato: il numero in prosa (n. 20, l'atto originario) non
    # e' quello del marcatore (D-32-1996, la ratifica che ne porta il testo).
    ("atto ratificato, numeri diversi di diritto",
     "Medici Chirurghi e Odontoiatri (D. 23 febbraio 1996 n. 20, art. 59"
     "{{cita:D-32-1996:59:-}})", 0),
    # DeepSeek-V4.1-Flash, batteria del 24/09: due falsi allarmi nati dal
    # guardare indietro oltre il marcatore precedente.
    ("rinvio interno al testo di legge, senza atto vicino",
     "e' punito con le pene del primo comma dell'art. 57 "
     "{{cita:DD-58-2009:6:1}}", 0),
    ("l'atto prima appartiene al marcatore prima",
     "si applicano le disposizioni della L. 166/2013{{cita:L-166-2013:-:-}} "
     "vigenti prima (art. 54, comma 2{{cita:L-141-2025:54:2}})", 0),
    ("righe di Qwen che reggono",
     "- D.D. 173/2014, art. 31, comma 3{{cita:DD-173-2014:31:3}}\n"
     "- D.D. 80/2015, art. 38, comma 3{{cita:DD-80-2015:38:3}}\n"
     "- Regolamento R. 2/2025, art. 6, comma 1{{cita:R-2-2025:6:1}}", 0),
    ("righe di Sonnet",
     "- per i Geometri: ricorso entro trenta giorni {{cita:DD-80-2015:38:3}}\n"
     "- per i Medici, stessa regola {{cita:D-32-1996:59:1}}", 0),
    ("atto intero, marcatore senza articolo",
     "La materia e' disciplinata dalla L. 64/2025{{cita:L-64-2025:-:-}}", 0),
    ("zero non significativo", "Vedi l'art. 07, comma 2{{cita:L-87-2026:7:2}}", 0),
    ("articolo a meta' frase, non attaccato",
     "L'art. 12 rinvia alla disciplina generale, che si applica"
     "{{cita:L-87-2026:7:2}}", 0),
    ("atto nominato in una frase precedente",
     "La L. 100/2020 ha riformato la materia. Il termine resta di trenta giorni"
     "{{cita:L-50-2019:3:1}}", 0),
    ("data che somiglia a una norma",
     "In vigore fino al 31/12/2026, art. 7, comma 2{{cita:L-87-2026:7:2}}", 0),
    # DeepSeek-V4-Pro, 24/09: qui "articolo precedente" e' testo di legge
    # citato fra virgolette, non un riferimento. Faceva scattare un falso.
    ("testo di legge citato, non un riferimento",
     "ricorso gerarchico immediato \"entro il termine perentorio di trenta "
     "giorni dalla comunicazione\" di cui all'ultimo comma dell'articolo "
     "precedente{{cita:DD-88-2022:all2-30:4}}", 0),
]

# (nome, testo, segnalazioni attese)
NON_VERIFICATE = [
    ("atti tutti consultati",
     "- per i Geometri, trenta giorni {{cita:DD-80-2015:38:3}}\n"
     "- per i Geologi, ancora trenta giorni {{cita:D-86-1995:8:2}}", []),
    # "D. 43/1995" sfuggiva: TIPO non conosceva "d." da sola.
    ("decreto mai consultato, in forma breve",
     "- D. 43/1995 (Ingegneri e Architetti), art. 33{{cita:D-63-1995:18:2}}",
     ["43/1995"]),
    ("decreto consultato, in forma breve",
     "Il termine e' fissato dal D. 86/1995, art. 8, comma 2{{cita:D-86-1995:8:2}}",
     []),
    ("una data non e' una norma",
     "La promozione vale fino al 31/12/2026 e poi il prezzo raddoppia.", []),
]


def prova():
    errori = 0
    print("prosa contro marcatore")
    for nome, testo, attese in DISCORDI:
        esito = _citazioni_discordi(testo)
        ok = len(esito) == attese
        errori += not ok
        print(f'  {"OK " if ok else "NO "} {nome:<42} {len(esito)}/{attese} '
              f'{esito if esito else ""}')

    print("\natti mai consultati")
    for nome, testo, atteso in NON_VERIFICATE:
        esito = _citazioni_non_verificate(testo, VISTE)
        ok = esito == atteso
        errori += not ok
        print(f'  {"OK " if ok else "NO "} {nome:<42} {esito} (atteso {atteso})')

    print("\nfallite:", errori)
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(prova())
