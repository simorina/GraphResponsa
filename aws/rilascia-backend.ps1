<#
.SYNOPSIS
    Rilascia il backend di graphResponsa: immagine su ECR, riavvio del servizio ECS.

.DESCRIPTION
    Quattro passi - accesso al registro, costruzione, caricamento, riavvio - piu'
    l'attesa del rollout e le verifiche. L'immagine prende due etichette:
    `latest`, che il servizio usa, e il commit corrente, che serve a tornare
    indietro. Senza la seconda un rilascio sbagliato si annulla solo
    ricostruendo l'immagine di prima, e nel frattempo il servizio e' rotto.

    Il frontend NON viene toccato: sta su S3 dietro CloudFront e si rilascia a
    parte (vedi in fondo, dopo le verifiche).

.PARAMETER SoloVerifica
    Non costruisce e non carica niente: mostra cosa c'e' in produzione adesso,
    cosa verrebbe rilasciato e l'esito delle verifiche. Da usare prima.

.PARAMETER Forza
    Procede anche con modifiche non committate. Senza, si ferma: un'immagine
    che non corrisponde a un commit non si sa piu' cosa contenga.

.EXAMPLE
    .\aws\rilascia-backend.ps1 -SoloVerifica
    .\aws\rilascia-backend.ps1
#>
[CmdletBinding()]
param(
    [switch]$SoloVerifica,
    [switch]$Forza,
    [string]$Regione  = 'eu-central-1',
    [string]$Registro = '392900064778.dkr.ecr.eu-central-1.amazonaws.com',
    [string]$Immagine = 'graphresponsa',
    [string]$Cluster  = 'graphresponsa-cluster',
    [string]$Servizio = 'graphresponsa-api',
    [string]$Sito     = 'https://ds1t1vk405e45.cloudfront.net'
)

$ErrorActionPreference = 'Stop'

function Passo($testo) { Write-Host "`n== $testo" -ForegroundColor Cyan }
function Bene($testo)  { Write-Host "   $testo" -ForegroundColor Green }
function Nota($testo)  { Write-Host "   $testo" }
function Fermati($testo) { Write-Host "`n   $testo" -ForegroundColor Red; exit 1 }

# Il comando nativo non solleva eccezioni: l'esito si legge da $LASTEXITCODE.
function Esegui($descrizione) {
    $argomenti = $args
    & $argomenti[0] @($argomenti[1..($argomenti.Length - 1)])
    if ($LASTEXITCODE -ne 0) { Fermati "$descrizione non riuscito (codice $LASTEXITCODE)." }
}

Set-Location (Join-Path $PSScriptRoot '..')

Passo 'Prerequisiti'
foreach ($c in 'docker', 'aws', 'git') {
    if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { Fermati "Manca $c." }
}
docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { Fermati 'Docker non risponde: avvia Docker Desktop.' }
$identita = aws sts get-caller-identity --query 'Arn' --output text
if ($LASTEXITCODE -ne 0) { Fermati 'Credenziali AWS non valide.' }
Bene "docker attivo, AWS come $identita"

Passo 'Stato del repository'
$ramo = git rev-parse --abbrev-ref HEAD
$commit = git rev-parse --short HEAD
$sporco = git status --porcelain
if ($sporco) {
    Nota 'Modifiche non committate:'
    $sporco | Select-Object -First 8 | ForEach-Object { Nota "     $_" }
    if (-not $Forza -and -not $SoloVerifica) {
        Fermati 'Committa o usa -Forza: un''immagine che non corrisponde a un commit non e'' ricostruibile.'
    }
}
Bene "ramo $ramo, commit $commit"

Passo 'In produzione adesso'
$attuale = aws ecs describe-services --cluster $Cluster --services $Servizio `
    --query 'services[0].deployments[0].[taskDefinition,rolloutState,runningCount,updatedAt]' --output text
Nota $attuale
$ultime = aws ecr describe-images --repository-name $Immagine `
    --query 'sort_by(imageDetails,&imagePushedAt)[-5:].[imageTags[0],imagePushedAt]' --output text
Nota 'Ultime immagini nel registro (la prima colonna e'' l''etichetta per il ritorno indietro):'
$ultime -split "`n" | ForEach-Object { Nota "     $_" }

if ($SoloVerifica) {
    Passo 'Verifiche sul servizio vivo'
    try {
        $r = Invoke-WebRequest -Uri "$Sito/salute" -UseBasicParsing -TimeoutSec 20
        Bene "/salute risponde $($r.StatusCode)"
    } catch { Nota "/salute non risponde: $($_.Exception.Message)" }
    Write-Host "`nNiente costruito e niente caricato (-SoloVerifica)." -ForegroundColor Yellow
    exit 0
}

Passo 'Accesso al registro ECR'
$password = aws ecr get-login-password --region $Regione
if ($LASTEXITCODE -ne 0) { Fermati 'Impossibile ottenere la password del registro.' }
$password | docker login --username AWS --password-stdin $Registro
if ($LASTEXITCODE -ne 0) { Fermati 'Accesso al registro non riuscito.' }
Bene 'autenticato'

Passo "Costruzione dell'immagine ($commit)"
Esegui 'docker build' docker build -f aws/Dockerfile -t "$Registro/${Immagine}:latest" -t "$Registro/${Immagine}:$commit" .
Bene 'immagine costruita'

Passo 'Caricamento su ECR'
Esegui 'docker push latest' docker push "$Registro/${Immagine}:latest"
Esegui 'docker push commit' docker push "$Registro/${Immagine}:$commit"
Bene "caricate le etichette latest e $commit"

Passo 'Riavvio del servizio'
aws ecs update-service --cluster $Cluster --service $Servizio --force-new-deployment --query 'service.serviceName' --output text | Out-Null
if ($LASTEXITCODE -ne 0) { Fermati 'Riavvio non riuscito.' }
Bene 'riavvio richiesto'

Passo 'Attesa del rollout (fino a 10 minuti)'
$scadenza = (Get-Date).AddMinutes(10)
$stato = ''
while ((Get-Date) -lt $scadenza) {
    $riga = aws ecs describe-services --cluster $Cluster --services $Servizio `
        --query 'services[0].deployments[0].[rolloutState,runningCount,desiredCount]' --output text
    $stato = ($riga -split "\s+")[0]
    Nota "$(Get-Date -Format HH:mm:ss)  $riga"
    if ($stato -eq 'COMPLETED') { break }
    if ($stato -eq 'FAILED') { Fermati 'Rollout fallito: guarda i log del servizio su CloudWatch.' }
    Start-Sleep -Seconds 20
}
if ($stato -ne 'COMPLETED') { Fermati 'Rollout non completato entro dieci minuti.' }
Bene 'rollout completato'

Passo 'Verifiche'
$esito = 0
try {
    $r = Invoke-WebRequest -Uri "$Sito/salute" -UseBasicParsing -TimeoutSec 20
    if ($r.StatusCode -eq 200) { Bene '/salute 200' } else { Nota "/salute $($r.StatusCode)"; $esito = 1 }
} catch { Nota "/salute non risponde: $($_.Exception.Message)"; $esito = 1 }

try {
    Invoke-WebRequest -Uri "$Sito/chat" -Method POST -Body '{}' -ContentType 'application/json' `
        -UseBasicParsing -TimeoutSec 20 | Out-Null
    Nota '/chat senza credenziali ha risposto 2xx: il cancello e'' aperto, da guardare subito.'
    $esito = 1
} catch {
    $codice = $_.Exception.Response.StatusCode.value__
    if ($codice -eq 401) { Bene '/chat senza credenziali 401' } else { Nota "/chat ha risposto $codice"; $esito = 1 }
}

Write-Host ''
if ($esito -eq 0) {
    Write-Host "Rilasciato $commit." -ForegroundColor Green
} else {
    Write-Host "Rilasciato $commit, ma una verifica non torna: leggi sopra." -ForegroundColor Yellow
}
Write-Host ''
Write-Host 'Per tornare indietro:' -ForegroundColor Yellow
Write-Host "   docker pull $Registro/${Immagine}:<etichetta precedente>"
Write-Host "   docker tag  $Registro/${Immagine}:<etichetta precedente> $Registro/${Immagine}:latest"
Write-Host "   docker push $Registro/${Immagine}:latest"
Write-Host "   aws ecs update-service --cluster $Cluster --service $Servizio --force-new-deployment"
Write-Host ''
Write-Host 'Il frontend e'' un rilascio a parte:' -ForegroundColor Yellow
Write-Host '   cd frontend; npm run build'
Write-Host '   aws s3 sync dist/ s3://graphresponsa-frontend-392900064778 --delete'
Write-Host '   aws cloudfront create-invalidation --distribution-id E32NXP50437VPI --paths "/*"'
