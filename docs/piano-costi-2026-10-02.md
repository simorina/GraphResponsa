# Piano dei costi AWS e ALB interno — 2 ottobre 2026

Il 2 ottobre la spesa AWS è stata ridotta da 60 a 52 dollari al mese, e sono
stati rivisti budget e avvisi. Resta un passo: sostituire l'ALB pubblico con
un **ALB interno**, raggiunto da CloudFront tramite una *VPC origin*. Toglie il
backend da internet e fa risparmiare altri 7,3 dollari al mese. Il piano è
costruito per non fermare il servizio in nessun momento.

- **Stato:** fasi 1–3 fatte il 2 ottobre, e tutto il traffico API passa
  dall'ALB interno. Manca la fase 4, prevista per lunedì 5 ottobre.
- **Chi lo esegue:** Claude Code, dalla sessione di Simone, con il profilo AWS
  `root`.
- **Quando:** ogni fase parte solo con il via di Simone.

## Avanzamento

| Fase | Stato |
|---|---|
| 1 — Costruzione in parallelo | **fatta** il 2/10 alle 14:40 |
| 2 — Container su entrambi gli ALB | **fatta** il 2/10 alle 15:01 |
| 3 — Spostamento del traffico | **fatta** il 2/10 alle 15:10 |
| 4 — Spegnimento del vecchio | prevista lunedì 5/10, se fino ad allora è tutto tranquillo |

Le fasi 2 e 3 le ha lanciate Simone, con gli script preparati da Claude Code.
Il controllo dei permessi di Claude Code blocca le modifiche alle risorse
condivise anche quando c'è l'autorizzazione in chat, e così sarà anche per la
fase 4.

Verifiche dopo la fase 3:

- gli 8 percorsi API di CloudFront puntano a `origineAlbInterno`, e l'ALB
  pubblico non è più usato da CloudFront;
- l'ALB interno riceve le richieste senza errori 5xx;
- il container è sano in entrambi i gruppi di bersagli;
- l'autoscaling conta le richieste sull'ALB interno;
- l'ALB interno accetta solo gli IP di CloudFront e il traffico passa. Il
  backend vede arrivare CloudFront come prima, e l'IP del visitatore resta al
  penultimo posto di `X-Forwarded-For`.

Resta da fare una domanda vera dall'app, per verificare lo streaming.

Risorse create nella fase 1, tutte con i tag `Progetto=GraphResponsa` e
`Ambiente=dev`:

- sottoreti private `subnet-05dd345164dcc503b` (10.42.11.0/24, eu-central-1a)
  e `subnet-0dc1698fe78c53f54` (10.42.12.0/24, eu-central-1b), con la tabella
  `rtb-04c388b45b6cad4e9`, che ha solo la rotta locale;
- gruppo di sicurezza `sg-0c900ac46ff040ebf` (`graphresponsa-alb-interno`), con
  la porta 80 aperta solo agli IP di CloudFront (lista gestita `pl-a3a144ca`);
- ALB interno `graphresponsa-alb-interno`, con il gruppo di bersagli
  `graphresponsa-interno`, il listener sulla porta 80 e la regola
  sull'intestazione;
- una regola in più sul gruppo del container, che apre la porta 8000 all'ALB
  interno;
- VPC origin `vo_4oitXznIoooBgwwyeH8VW0`.

Fino alla fase 4 restano accesi due ALB, cioè circa 0,65 $ al giorno in più.
Fino ad allora si torna indietro in pochi minuti con
`python fase3_sposta.py indietro`.

---

## 1. Quanto si spende

Spesa AWS al mese, prima dei crediti:

| | Senza IVA | Con IVA al 22% |
|---|---|---|
| Prima del 2 ottobre | 60 $ | 73 $ |
| Oggi, con la CPU dimezzata | 52 $ | 63 $ |
| Con l'ALB interno | 44,5 $ | **54 $** |

I 44,5 $ finali si dividono così: ALB 20, Fargate 12, IP pubblici 7, dischi 4,
segreti 1.

- **Crediti.** Restano 115,68 $ e finora coprono tutto: ad agosto e settembre il
  conto netto è stato zero. Con l'ALB interno durano fino a metà dicembre circa.
- **IVA.** L'account è in Italia e su AWS non c'è una partita IVA registrata.
  Quando finiscono i crediti, quindi, AWS aggiunge il 22%. Con una partita IVA
  registrata su AWS l'IVA non viene addebitata e si gestisce con l'inversione
  contabile.
- **Macchina del grafo (t4g.small).** Oggi è gratuita grazie a una prova di AWS.
  Se la prova finisce, costa 14 $ al mese in più (17 $ con IVA).
- **Fuori da AWS.** DeepSeek costa circa 0,8 centesimi a domanda: 1.000 domande
  al mese sono circa 8 $. Voyage costa pochi centesimi.

## 2. Già fatto il 2 ottobre

- **Backend da 0,5 a 0,25 vCPU**, memoria invariata a 1 GB: −8,4 $ al mese.
  - In 14 giorni, solo 21 minuti su 20.159 avevano superato il 25% della CPU di
    allora, quasi tutti all'avvio dopo un rilascio.
  - L'attesa prima dei controlli di salute passa da 60 a 120 secondi, perché con
    meno CPU l'avvio è più lento.
  - In produzione come task `graphresponsa-api:5`.
- **Budget mensile** `My Monthly Cost Budget`: da 35 a 60 $. Avvisa al 90% e al
  100% dello speso e al 100% del previsto.
- **Nuovo budget** `Crediti AWS esauriti`: avvisa quando in un mese si pagano
  davvero più di 1 $, cioè quando i crediti sono finiti.
- **Anomalie di spesa:** la soglia passa da «100 $ e +40%» a 5 $ di impatto, con
  un avviso al giorno.
- **Tag di costo** `Progetto` e `Ambiente` attivati: Cost Explorer divide i costi
  per progetto.
- **Lorenzo e Matteo** avevano già i permessi sui costi, tramite il gruppo
  `GraphResponsaDevelopers`. Se la console Fatturazione risponde «accesso
  negato», root deve attivare *IAM user and role access to Billing information*
  nelle impostazioni dell'account.

La modifica a `aws/infrastruttura.yaml` (CPU 256, attesa 120 secondi) non è
ancora committata.

## 3. Perché un ALB interno

Oggi:

```
Browser ──HTTPS──▶ CloudFront ──HTTP, indirizzo pubblico──▶ ALB pubblico ──▶ container Fargate
```

Dopo:

```
Browser ──HTTPS──▶ CloudFront ──VPC origin, rete AWS──▶ ALB interno ──▶ container Fargate
```

I motivi sono due:

- **Sicurezza.** Da CloudFront all'ALB il traffico viaggia in HTTP non cifrato.
  Ci passano domande, risposte, token di accesso e l'intestazione segreta che
  protegge l'ALB. L'ALB ha un indirizzo pubblico e chiunque può raggiungerlo:
  lo ferma solo quell'intestazione. Con la VPC origin l'ALB non è più
  raggiungibile da internet, e il tratto resta dentro la rete di AWS.
- **Costo.** L'ALB interno costa quanto quello pubblico, ma non ha i 2 IP
  pubblici: −7,3 $ al mese.

Per gli utenti, il codice, il frontend e lo script di rilascio non cambia niente.

## 4. E se comprate un dominio?

Il piano resta valido, perché le due cose sono indipendenti.

- **Il dominio sta davanti a CloudFront.** È l'indirizzo che vedono gli utenti,
  con un certificato gratuito di AWS.
- **La VPC origin sta dietro CloudFront.** È la strada con cui CloudFront
  raggiunge il backend, e il dominio non la tocca.
- **Un dominio permetterebbe un'alternativa parziale.** Con un certificato
  sull'ALB pubblico il tratto CloudFront → ALB sarebbe cifrato. Ma l'ALB
  resterebbe esposto su internet e i 2 IP pubblici resterebbero da pagare.
  L'ALB interno risolve tutte e due le cose.
- **Se il dominio arriva dopo, il lavoro sull'ALB non va rifatto.** Volendo, si
  può mettere un certificato anche sull'ALB interno, per cifrare pure il tratto
  dentro AWS.

Il passaggio al dominio è un lavoro a parte: certificato, CloudFront, indirizzi
del sito nelle email e negli script. Il dominio costa circa 10–15 $ l'anno per
un .com, più 0,50 $ al mese se il DNS sta su Route 53.

## 5. Verifiche già fatte

- Francoforte supporta le VPC origin in entrambe le zone che usiamo
  (`euc1-az2`, `euc1-az3`).
- Le VPC origin accettano un timeout di lettura fino a 120 secondi e un
  keepalive fino a 300. Restano 120 e 60 come oggi, che servono allo streaming.
- Sui percorsi API non ci sono funzioni Lambda@Edge, che con le VPC origin non
  funzionano.
- Nessun file del progetto usa l'indirizzo dell'ALB. Dall'ALB attuale dipende
  solo l'autoscaling: la politica `graphresponsa-cpu` e i suoi due allarmi.
- Sull'ALB non c'è un WAF.

## 6. Il piano

Le modifiche si fanno via API, come quelle delle ultime settimane. Aggiornare lo
stack CloudFormation così com'è è proprio la cosa che rischierebbe di rompere
(vedi «Dopo», in fondo a questa sezione).

### Fase 1 — Costruzione in parallelo

Gli utenti non se ne accorgono.

1. Due sottoreti private, con una tabella di routing senza uscita verso
   internet:
   - `10.42.11.0/24` in eu-central-1a;
   - `10.42.12.0/24` in eu-central-1b.
2. Un gruppo di sicurezza per l'ALB interno, all'inizio senza ingressi.
3. L'ALB interno, nelle sottoreti private, con:
   - lo stesso timeout di inattività di oggi, 300 secondi;
   - un gruppo di bersagli uguale all'attuale: porta 8000, controllo su
     `/salute` ogni 30 secondi, sano dopo 2 risposte, malato dopo 3 errori, 30
     secondi di drenaggio;
   - lo stesso filtro: risponde 403 a chi non porta l'intestazione
     `X-Origine-Verificata`. Il valore si copia dalla regola attuale, senza
     scriverlo mai in chiaro.
4. La VPC origin di CloudFront sull'ALB interno, che richiede fino a 15 minuti.
   La porta 80 dell'ALB interno è aperta solo agli IP di CloudFront (lista
   gestita `pl-a3a144ca`), una delle due configurazioni indicate da AWS. Ha un
   vantaggio: se il traffico passa, l'ALB vede arrivare CloudFront come oggi.
   La catena `X-Forwarded-For`, da cui il backend ricava l'IP del visitatore
   per i limiti, resta quindi uguale.
5. Il gruppo di sicurezza del container accetta anche il nuovo ALB. La regola
   vecchia resta.

**Per tornare indietro:** si cancella ciò che è stato creato. Gli utenti non
vengono toccati.

### Fase 2 — Il container si collega a entrambi gli ALB

Va fatta in un momento senza demo.

1. Aggiorno il servizio ECS perché registri il container in tutti e due i
   gruppi di bersagli. Funziona come un rilascio: il task nuovo deve risultare
   sano su entrambi prima che il vecchio venga spento.
2. Verifico che il rilascio sia completato, che il container sia sano in
   entrambi i gruppi e che `/salute` risponda 200.

**Rischio:** come in ogni rilascio, una risposta lunga in corso proprio in quel
momento può interrompersi.

**Per tornare indietro:** si rimette il servizio con il solo gruppo vecchio. Se
il task nuovo non diventa sano, il vecchio continua a servire.

### Fase 3 — Spostamento del traffico, un percorso alla volta

In CloudFront aggiungo l'origine `origineAlbInterno`: è la VPC origin, con
lettura a 120 secondi, keepalive a 60 e la stessa intestazione segreta. Poi
sposto i percorsi a gruppi. Dopo ogni passo aspetto la propagazione, che
richiede pochi minuti. Nel frattempo funzionano entrambe le strade, perché i due
ALB portano allo stesso container.

| Passo | Percorsi | Verifica |
|---|---|---|
| 1 | `/salute`, `/stato` | `/salute` risponde 200, `/stato` restituisce i numeri del grafo |
| 2 | `/documenti/*`, `/conversazioni*`, `/riscontro` | un PDF si apre; conversazioni e riscontri senza credenziali rispondono 401 |
| 3 | `/recupero-password`, `/richiesta-demo` | una richiesta vuota riceve 422 dal backend, senza mandare email né salvare righe |
| 4 | `/chat` | senza credenziali risponde 401; poi Simone fa una domanda vera dall'app e la risposta si scrive man mano |

Dopo il passo 4 sposto l'autoscaling sull'ALB interno. Altrimenti conterebbe le
richieste sull'ALB vecchio, dove non arriva più niente, e non aggiungerebbe mai
container.

**Per tornare indietro:** si rimettono i percorsi sull'origine vecchia, che resta
accesa e collegata. Bastano pochi minuti.

### Fase 4 — Spegnimento del vecchio, dopo 2–3 giorni senza problemi

1. Stacco il gruppo vecchio dal servizio ECS. È un altro rilascio senza fermo,
   da fare in un momento tranquillo.
2. Tolgo da CloudFront l'origine vecchia.
3. Cancello l'ALB pubblico con il suo listener, il suo gruppo di bersagli, il
   suo gruppo di sicurezza e la regola che gli apriva il container.
4. Dal giorno dopo, in Cost Explorer gli IP pubblici devono scendere da 4 a 2,
   cioè da circa 0,48 a 0,24 $ al giorno.

Da qui in poi tornare indietro non è più immediato, perché bisognerebbe
ricreare un ALB pubblico. Per questo si aspettano 2–3 giorni.

Lo script è `fase4_spegni_vecchio.py`. Senza argomenti fa solo i controlli e
non cambia niente: percorsi di CloudFront, bersagli sani, errori 5xx delle
ultime 72 ore e risposte del sito. Con `conferma` esegue i passi 1–3 e poi
verifica il risultato. Al primo dubbio si ferma.

### Dopo

- `aws/infrastruttura.yaml` descrive già il nuovo assetto (aggiornato il 2/10):
  sottoreti private, ALB interno, VPC origin e percorsi su `origineAlbInterno`.
- Lo stack CloudFormation `GraphResponsa-dev` resta da riallineare. È fermo al
  7 settembre (task `:2`, CPU 512) e da allora le modifiche sono state fatte
  fuori dallo stack. Aggiornato così com'è, rimetterebbe la configurazione di
  settembre. È un lavoro a parte.

## 7. Tempi e costi del passaggio

- **Fasi 1–3:** circa un'ora, quasi tutta di attesa per la VPC origin e le
  propagazioni di CloudFront.
- **Fase 4:** mezz'ora, 2–3 giorni dopo.
- **Sovrapposizione:** mentre ci sono due ALB si spendono circa 0,65 $ al
  giorno in più. Poi si risparmiano 7,3 $ al mese.

## 8. Cosa serve da Simone

- [x] Il via per la fase 1.
- [x] Le fasi 2 e 3, lanciate a mano il 2/10.
- [ ] Una domanda vera dall'app dopo lo spostamento di `/chat`.
- [ ] Lunedì 5/10, la fase 4: prima `python fase4_spegni_vecchio.py`, poi, se i
      controlli passano, `python fase4_spegni_vecchio.py conferma`.

Ogni script vuole una sessione AWS attiva: `aws login --profile root`.

## 9. Fuori da questo piano

- **Fargate Spot** (−8,5 $ al mese): sconsigliato. AWS può spegnere il task con
  2 minuti di preavviso, e con un solo task il sito cade.
- **Fargate su ARM** (−2,4 $ al mese): si può fare più avanti, costruendo
  l'immagine per arm64.
- **Tutto sulla EC2 del grafo** (−15/43 $ al mese): per ora no. Avremmo un solo
  punto di guasto, un fermo a ogni rilascio e probabilmente una macchina più
  grande.
- **Avanzi di un vecchio progetto:** il log `/aws/lambda/responsa-rag-backend-dev`
  e il bucket `responsa-kb-documents-dev`. Non costano niente e si cancellano
  su richiesta.
