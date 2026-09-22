<#
.SYNOPSIS
    Rilascia il sito di graphResponsa: costruzione, caricamento su S3, invalidazione CloudFront.

.DESCRIPTION
    Il sito e' un pacchetto statico: CloudFront serve `index.html` e i file in
    `assets/` dal bucket, e gira su ALB solo le chiamate all'API. Il
    caricamento avviene in due passaggi, e l'ordine conta:

      1. prima `assets/`, i cui nomi contengono l'impronta del contenuto
         (`index-DqKQ2diL.js`): non cambiano mai a parita' di contenuto, quindi
         si fanno tenere in cache per un anno;
      2. poi `index.html`, che ha sempre lo stesso nome e punta ai file nuovi:
         si marca `no-cache`, altrimenti un browser continuerebbe a chiedere il
         pacchetto vecchio.

    Caricare prima l'indice e poi gli assets lascerebbe, per qualche secondo,
    una pagina che chiede file non ancora arrivati.

    Il backend NON viene toccato: si rilascia con rilascia-backend.ps1.

.PARAMETER SoloVerifica
    Costruisce e mostra cosa cambierebbe nel bucket (`--dryrun`), senza
    caricare niente e senza invalidare.

.PARAMETER SaltaCostruzione
    Usa `frontend/dist` com'e', senza ricostruirlo. Per ripetere un
    caricamento fallito a meta'.

.EXAMPLE
    .\aws\rilascia-frontend.ps1 -SoloVerifica
    .\aws\rilascia-frontend.ps1
#>
[CmdletBinding()]
param(
    [switch]$SoloVerifica,
    [switch]$SaltaCostruzione,
    [switch]$Forza,
    [string]$Bucket        = 'graphresponsa-frontend-392900064778',
    [string]$Distribuzione = 'E32NXP50437VPI',
    [string]$Sito          = 'https://ds1t1vk405e45.cloudfront.net'
)

# 'Continue' e non 'Stop': in Windows PowerShell 5.1, con 'Stop', la prima
# riga che un comando nativo scrive su stderr diventa un'eccezione - prima che
# lo script possa leggere $LASTEXITCODE e dire cosa manca. Ogni comando nativo
# qui e' controllato uno per uno, e le chiamate web stanno in try/catch.
$ErrorActionPreference = 'Continue'

function Passo($testo) { Write-Host "`n== $testo" -ForegroundColor Cyan }
function Bene($testo)  { Write-Host "   $testo" -ForegroundColor Green }
function Nota($testo)  { Write-Host "   $testo" }
function Fermati($testo) { Write-Host "`n   $testo" -ForegroundColor Red; exit 1 }

Set-Location (Join-Path $PSScriptRoot '..')

Passo 'Prerequisiti'
foreach ($c in 'npm', 'aws', 'git') {
    if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { Fermati "Manca $c." }
}
$identita = aws sts get-caller-identity --query 'Arn' --output text
if ($LASTEXITCODE -ne 0) { Fermati 'Credenziali AWS non valide.' }
Bene "AWS come $identita"

Passo 'Stato del repository'
$ramo = git rev-parse --abbrev-ref HEAD
$commit = git rev-parse --short HEAD
$sporco = git status --porcelain -- frontend
if ($sporco) {
    Nota 'Modifiche non committate sotto frontend/:'
    $sporco | Select-Object -First 8 | ForEach-Object { Nota "     $_" }
    if (-not $Forza -and -not $SoloVerifica) { Fermati 'Committa, o usa -Forza.' }
}
Bene "ramo $ramo, commit $commit"

if (-not $SaltaCostruzione) {
    Passo 'Costruzione del sito'
    Push-Location frontend
    if (-not (Test-Path node_modules)) {
        Nota 'node_modules assente: installo le dipendenze (npm ci)'
        npm ci
        if ($LASTEXITCODE -ne 0) { Pop-Location; Fermati 'npm ci non riuscito.' }
    }
    # `npm run build` e' `tsc && vite build`: un errore di tipi ferma qui, prima
    # che un pacchetto rotto arrivi sul bucket.
    npm run build
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fermati 'Costruzione non riuscita.' }
    Pop-Location
    Bene 'costruito in frontend/dist'
}

if (-not (Test-Path 'frontend/dist/index.html')) { Fermati 'Manca frontend/dist/index.html.' }
$peso = (Get-ChildItem frontend/dist -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Nota ("pacchetto: {0} file, {1:N1} MB" -f (Get-ChildItem frontend/dist -Recurse -File).Count, $peso)

Passo 'Cosa cambierebbe nel bucket'
aws s3 sync frontend/dist "s3://$Bucket" --delete --dryrun
if ($LASTEXITCODE -ne 0) { Fermati 'Confronto col bucket non riuscito.' }

if ($SoloVerifica) {
    Write-Host "`nNiente caricato e niente invalidato (-SoloVerifica)." -ForegroundColor Yellow
    exit 0
}

Passo 'Caricamento: prima gli assets, poi la pagina'
aws s3 sync frontend/dist "s3://$Bucket" --delete --exclude 'index.html' `
    --cache-control 'public,max-age=31536000,immutable'
if ($LASTEXITCODE -ne 0) { Fermati 'Caricamento degli assets non riuscito.' }
aws s3 cp frontend/dist/index.html "s3://$Bucket/index.html" `
    --cache-control 'no-cache' --content-type 'text/html; charset=utf-8'
if ($LASTEXITCODE -ne 0) { Fermati 'Caricamento di index.html non riuscito.' }
Bene 'bucket aggiornato'

Passo 'Invalidazione della cache CloudFront'
$invalidazione = aws cloudfront create-invalidation --distribution-id $Distribuzione `
    --paths '/*' --query 'Invalidation.Id' --output text
if ($LASTEXITCODE -ne 0) { Fermati 'Invalidazione non riuscita.' }
Nota "invalidazione $invalidazione in corso (qualche minuto)"
aws cloudfront wait invalidation-completed --distribution-id $Distribuzione --id $invalidazione
if ($LASTEXITCODE -ne 0) { Nota 'Attesa interrotta: la propagazione prosegue per conto suo.' }
else { Bene 'invalidazione completata' }

Passo 'Verifiche'
$esito = 0
try {
    $r = Invoke-WebRequest -Uri $Sito -UseBasicParsing -TimeoutSec 30
    if ($r.StatusCode -eq 200) { Bene "la pagina risponde 200" } else { Nota "la pagina risponde $($r.StatusCode)"; $esito = 1 }
    # Il nome del pacchetto e' nell'HTML: se e' quello appena costruito, la
    # pagina servita e' la nuova e non una copia in cache.
    $atteso = (Get-ChildItem frontend/dist/assets -Filter '*.js' | Select-Object -First 1).Name
    if ($r.Content -match [regex]::Escape($atteso)) { Bene "serve il pacchetto nuovo ($atteso)" }
    else { Nota "la pagina non nomina ${atteso}: potrebbe essere ancora in cache"; $esito = 1 }
} catch { Nota "la pagina non risponde: $($_.Exception.Message)"; $esito = 1 }

Write-Host ''
if ($esito -eq 0) { Write-Host "Sito rilasciato ($commit)." -ForegroundColor Green }
else { Write-Host "Sito rilasciato ($commit), ma una verifica non torna: leggi sopra." -ForegroundColor Yellow }
