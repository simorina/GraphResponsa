"""
Benchmark di valutazione su 100 quesiti giuridici sammarinesi.
Testa la precisione, il recupero delle fonti, l'uso dei tool e la vigenza temporale.
"""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from agente.agente import rispondi

DOMANDE_100 = [
    # --- 1. Diritto del Lavoro e Sindacale (L. 7/1961 e successive) ---
    "Quali sono le condizioni per la registrazione delle organizzazioni sindacali secondo la Legge 7/1961?",
    "Quanti articoli ha la Legge 7/1961 sulla tutela del lavoro e dei lavoratori?",
    "Cosa prevede l'articolo 9 della Legge 7/1961 in merito all'efficacia erga omnes dei contratti collettivi?",
    "Quali sono i doveri del prestatore di lavoro stabiliti dalla Legge 7/1961?",
    "Come viene disciplinato il lavoro a distanza (smart working) a San Marino nella Legge 202/2020?",
    "Quali sono i permessi retribuiti per l'allattamento previsti per le lavoratrici madri?",
    "In quali casi è consentito il recesso dal contratto di lavoro a tempo indeterminato secondo la normativa sammarinese?",
    "Qual è il compito della Commissione permanente conciliativa nella Legge 7/1961?",
    "Come è regolata l'assunzione obbligatoria tramite l'Ufficio del Lavoro a San Marino?",
    "Quali sanzioni sono previste per il datore di lavoro che non compila il libretto di lavoro?",

    # --- 2. Codice della Strada, Sanzioni & Vigenza (DD 81/2008, DD 162/2021, DD 53/2026, DD 111/2024) ---
    "Quali sono le sanzioni e le soglie vigenti per la guida in stato di ebbrezza a San Marino?",
    "Cosa succede se un neopatentato viene fermato con un tasso alcolemico superiore a zero a San Marino?",
    "Qual è la sanzione vigente per chi circola senza la prescritta revisione periodica del veicolo?",
    "Quali sono le norme per l'uso dei seggiolini per bambini a bordo dei veicoli nel Codice della Strada sammarinese?",
    "Cosa prevede la normativa vigente per l'eccesso di velocità oltre i 40 km/h rispetto al limite?",
    "Come funziona la patente a punti nella Repubblica di San Marino?",
    "Quali sono i requisiti per la guida di veicoli con targa estera da parte di residenti a San Marino?",
    "Quali sanzioni comporta l'uso dello smartphone alla guida senza vivavoce?",
    "Come viene sanzionata la guida senza copertura assicurativa RCA?",
    "Quali sono i limiti di velocità generali sulle strade della Repubblica di San Marino?",

    # --- 3. Diritto Costituzionale & Ordinamento dello Stato (L. 59/1974 e riforme) ---
    "Quali sono i diritti fondamentali garantiti dalla Dichiarazione dei Diritti del 1974 (Legge 59/1974)?",
    "Come sono eletti i Capitani Reggenti e qual è la durata del loro mandato semestrale?",
    "Quali sono le attribuzioni e le competenze del Consiglio Grande e Generale?",
    "Qual è il ruolo e la composizione del Congresso di Stato a San Marino?",
    "Come funziona il Collegio Garante della Costituzionalità delle Norme?",
    "Quali sono le maggioranze richieste per l'approvazione di una Legge Costituzionale o Qualificata?",
    "Come è regolato l'istituto dell'Arengo e la presentazione delle istanze d'Arengo?",
    "Qual è la funzione e la struttura del Consiglio dei XII?",
    "Come si acquista la cittadinanza sammarinese per naturalizzazione?",
    "Quali sono le cause di ineleggibilità e incompatibilità per i membri del Consiglio Grande e Generale?",

    # --- 4. Diritto Societario & Commerciale (L. 47/2006 e riforme) ---
    "Qual è il capitale sociale minimo per la costituzione di una Società a Responsabilità Limitata (S.r.l.) a San Marino?",
    "Qual è il capitale sociale minimo per una Società per Azioni (S.p.A.) secondo la Legge 47/2006?",
    "Come è regolata la responsabilità degli amministratori verso la società nel diritto societario sammarinese?",
    "Quali sono i requisiti per la validità delle deliberazioni dell'assemblea dei soci in una S.r.l.?",
    "Come funziona l'istituto del Trust nell'ordinamento sammarinese secondo la Legge 42/2010?",
    "Quali sono i compiti del Collegio Sindacale o del Sindaco Unico nelle società di capitali?",
    "Come avviene lo scioglimento e la liquidazione di una società a San Marino?",
    "Cosa prevede la normativa sulle start-up ad alto contenuto tecnologico a San Marino?",
    "Quali sono le regole per il trasferimento di quote sociali di una S.r.l.?",
    "Come è disciplinata la fusione e la scissione tra società nell'ordinamento sammarinese?",

    # --- 5. Diritto Tributario, Fiscale & Doganale (L. 166/2013 e riforme) ---
    "Come sono strutturati gli scaglioni e le aliquote dell'Imposta Generale sui Redditi (IGR) per le persone fisiche?",
    "Qual è l'aliquota ordinaria dell'imposta sulle società (IGR) a San Marino?",
    "Come funziona l'imposta sulle importazioni (Monofase) nella Repubblica di San Marino?",
    "Quali sono le principali deduzioni fiscali per spese di produzione del reddito e carichi di famiglia nell'IGR?",
    "Come viene applicata la ritenuta alla fonte sui dividendi distribuiti a persone fisiche residenti?",
    "Quali sono le sanzioni per l'omessa o infedele dichiarazione dei redditi a San Marino?",
    "Come funziona il regime forfettario o agevolato per le nuove attività economiche?",
    "Quali sono le regole di fatturazione elettronica per gli scambi commerciali tra San Marino e l'Italia?",
    "Come viene tassato il reddito da lavoro autonomo e libero professionale nell'IGR?",
    "Quali sono i termini di versamento e di presentazione della dichiarazione dei redditi annuale?",

    # --- 6. Diritto Penale & Procedura Penale (Codice Penale 1865, riforme e L. 92/2008) ---
    "Quali sono i gradi di pena per i reati puniti con l'arresto o la prigionia nel Codice Penale sammarinese?",
    "Come è punito il reato di riciclaggio e autoriciclaggio secondo la Legge 92/2008 e successive modifiche?",
    "Quali sono le sanzioni per la corruzione di pubblici ufficiali nel codice penale sammarinese?",
    "Come è regolata la legittima difesa nell'ordinamento penale di San Marino?",
    "Quali sono le misure cautelari personali applicabili nel procedimento penale sammarinese?",
    "Come è disciplinato il reato di truffa nel Codice Penale di San Marino?",
    "Come viene nominato l'avvocato d'ufficio e quali sono le sue prerogative (es. Decreto Delegato 71/2025)?",
    "Quali sono i presupposti per la concessione della sospensione condizionale della pena a San Marino?",
    "Come funziona il Tribunale Commissariale e il ruolo del Giudice Inquirente?",
    "Quali sono le pene accessorie previste dal Codice Penale per i delitti contro la Pubblica Amministrazione?",

    # --- 7. Sanità, Previdenza & Sicurezza Sociale (L. 42/1955, L. 157/2022) ---
    "Come è organizzato l'Istituto per la Sicurezza Sociale (ISS) della Repubblica di San Marino?",
    "Quali sono i requisiti per la pensione di vecchiaia dopo la riforma previdenziale (Legge 157/2022)?",
    "Come viene calcolata l'indennità temporanea di malattia per i lavoratori dipendenti?",
    "Quali sono le prestazioni erogate dal Fondo Servizi Sociali per gli assegni familiari?",
    "Come funziona la tutela in caso di infortuni sul lavoro e malattie professionali a San Marino?",
    "Quali sono i contributi previdenziali a carico del datore di lavoro e del dipendente?",
    "Come è regolata la rendita ai superstiti (pensione di reversibilità) nell'ordinamento previdenziale?",
    "Quali sono i criteri per il riconoscimento dell'invalidità civile e delle indennità di accompagnamento?",
    "Come funziona la cassa integrazione guadagni (CIG) a San Marino?",
    "Quali sono i servizi sanitari garantiti a titolo gratuito a tutti i cittadini residenti assistiti ISS?",

    # --- 8. Edilizia, Urbanistica & Ambiente (L. 107/2015 Testo Unico) ---
    "Quali sono i titoli edilizi previsti dal Testo Unico dell'Edilizia (Legge 107/2015)?",
    "In quali casi è sufficiente la Comunicazione di Inizio Lavori (CIL) per interventi edilizi?",
    "Quali sono le sanzioni previste per gli abusi edilizi e le opere eseguite in assenza di concessione?",
    "Come funziona la Commissione per le Politiche Territoriali (CPT)?",
    "Quali sono i vincoli paesaggistici e ambientali per l'edificazione nel centro storico di San Marino (Patrimonio UNESCO)?",
    "Come si ottiene il certificato di agibilità o conformità edilizia di un immobile?",
    "Quali requisiti di efficienza energetica devono rispettare i nuovi edifici secondo la normativa sammarinese?",
    "Come è disciplinata la procedura per le sanatorie edilizie straordinarie?",
    "Quali sono le distanze minime dai confini e tra fabbricati prescritte nelle zone residenziali?",
    "Come funziona l'espropriazione per pubblica utilità nell'ordinamento sammarinese?",

    # --- 9. Privacy, Digitale & Innovazione (L. 171/2018, DD 173/2024) ---
    "Quali sono i diritti dell'interessato in materia di protezione dati personali nella Legge 171/2018 (GDPR sammarinese)?",
    "Come è regolata la figura del Responsabile della Protezione dei Dati (DPO/RPD) a San Marino?",
    "Quali sono le sanzioni per la violazione delle norme sul trattamento dei dati personali?",
    "Come funziona la firma digitale e i servizi fiduciari secondo il Decreto Delegato 173/2024 (eIDAS)?",
    "Qual è il valore giuridico del documento informatico e della trasmissione telematica certificata (Domicilio Digitale)?",
    "Quali sono i requisiti per la notifica di un data breach all'Autorità Garante per la Privacy di San Marino?",
    "Come è regolata la tecnologia a registro distribuito (Blockchain) e gli asset virtuali nel Decreto Delegato 86/2019?",
    "Quali sono le basi giuridiche per il trasferimento di dati personali verso Paesi terzi non UE?",
    "Come viene disciplinata la videosorveglianza sui luoghi di lavoro secondo la normativa privacy sammarinese?",
    "Quali sono i compiti e i poteri dell'Autorità Garante per la Protezione dei Dati Personali?",

    # --- 10. Immigrazione, Soggiorno & Ordinamento Giudiziario ---
    "Quali sono i requisiti per ottenere un permesso di soggiorno ordinario per motivi di lavoro a San Marino?",
    "Come funziona la residenza atipica a regime fiscale agevolato per soggetti facoltosi (Legge 118/2010)?",
    "Quali sono le condizioni per il ricongiungimento familiare dei cittadini stranieri residenti?",
    "Come è strutturato l'ordinamento giudiziario sammarinese dopo la riforma del 2021 (Legge Qualificata 1/2021)?",
    "Qual è il ruolo del Dirigente del Tribunale Unico di San Marino?",
    "Come sono disciplinati i Giudici d'Appello e il Terzo Grado di giudizio?",
    "Quali sono i requisiti per l'iscrizione all'Albo degli Avvocati e Notai della Repubblica di San Marino?",
    "Come viene disciplinata la mediazione civile e commerciale obbligatoria?",
    "Quali sono le condizioni per l'estradizione e il mandato di arresto internazionale a San Marino?",
    "Come funziona il gratuito patrocinio a spese dello Stato per i non abbienti nei procedimenti giudiziari?"
]


def valuta_benchmark():
    risultati = []
    totale = len(DOMANDE_100)
    print(f"=== AVVIO BENCHMARK 100 QUESITI SU GRAPHRRESPONSA ===")
    print(f"Data: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Totale domande nel set: {totale}\n")

    successi = 0
    tot_fonti = 0
    tempo_totale = 0.0

    for idx, domanda in enumerate(DOMANDE_100, 1):
        t0 = time.time()
        print(f"[{idx:03d}/{totale}] Domanda: {domanda[:65]}...")

        tools_chiamati = []
        testo_accumulato = []
        fonti = []
        errore = None

        try:
            for ev in rispondi(domanda, conversazione=f"bench-{idx}"):
                tipo = ev.get("tipo")
                if tipo == "strumento":
                    tools_chiamati.append({"nome": ev.get("nome"), "args": ev.get("argomenti")})
                elif tipo == "fonti":
                    fonti = ev.get("dati", [])
                elif tipo == "testo":
                    testo_accumulato.append(ev.get("testo", ""))
                elif tipo == "errore":
                    errore = ev.get("testo")

            durata = round(time.time() - t0, 2)
            tempo_totale += durata
            risposta_finale = "".join(testo_accumulato).strip()

            valido = len(risposta_finale) > 50 and errore is None
            if valido:
                successi += 1
                tot_fonti += len(fonti)

            status = "OK" if valido else "KO"
            print(f"       -> [{status}] in {durata}s | Tools: {len(tools_chiamati)} | Fonti: {len(fonti)}")

            risultati.append({
                "indice": idx,
                "domanda": domanda,
                "valido": valido,
                "durata_secondi": durata,
                "num_tools": len(tools_chiamati),
                "tools": [t["nome"] for t in tools_chiamati],
                "num_fonti": len(fonti),
                "fonti": fonti[:5],
                "anteprima_risposta": risposta_finale[:300] + ("..." if len(risposta_finale) > 300 else ""),
                "errore": errore
            })

            # Salvataggio incrementale
            out_file = ROOT / "data" / "benchmark_results_100.json"
            out_file.write_text(json.dumps({
                "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                "totale_domande": totale,
                "completate": idx,
                "successi": successi,
                "dettaglio": risultati
            }, ensure_ascii=False, indent=2), encoding="utf-8")

        except Exception as e:
            durata = round(time.time() - t0, 2)
            print(f"       -> [ECCEZIONE] {e}")
            risultati.append({
                "indice": idx,
                "domanda": domanda,
                "valido": False,
                "durata_secondi": durata,
                "errore": str(e)
            })

    report = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "totale_domande": totale,
        "successi": successi,
        "tasso_successo_pct": round((successi / totale) * 100, 2),
        "media_tempo_secondi": round(tempo_totale / max(1, totale), 2),
        "media_fonti_per_risposta": round(tot_fonti / max(1, successi), 2),
        "dettaglio": risultati
    }

    out_file = ROOT / "data" / "benchmark_results_100.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "="*60)
    print("=== RISULTATI BENCHMARK 100 QUESITI ===")
    print(f"Tasso di Successo: {report['tasso_successo_pct']}% ({successi}/{totale})")
    print(f"Tempo Medio di Risposta: {report['media_tempo_secondi']}s")
    print(f"Media Fonti Ancorate per Risposta: {report['media_fonti_per_risposta']}")
    print(f"Report completo salvato in: {out_file}")
    print("="*60)


if __name__ == "__main__":
    valuta_benchmark()
