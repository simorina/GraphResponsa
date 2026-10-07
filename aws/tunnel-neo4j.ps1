<#
.SYNOPSIS
    Apre un tunnel dal PC al Neo4j su EC2, per server.py e gli script della pipeline.

.DESCRIPTION
    Neo4j non e' raggiungibile da internet: la porta 7687 accetta solo i task
    del backend. Dal PC ci si arriva con il port forwarding di Session
    Manager, che non apre nessuna porta sull'istanza: il traffico passa
    dentro la sessione autenticata con le credenziali AWS.

    Finche' questa finestra resta aperta:
        bolt://localhost:7687   -> Neo4j (nel .env: NEO4J_URI=bolt://localhost:7687)
    e, con -Browser, anche
        http://localhost:7474   -> Neo4j Browser

    Windows riserva a rotazione intervalli di porte (Hyper-V, Docker Desktop,
    WSL), e se uno contiene la 7687 il plugin non puo' aprirla: la sessione
    risulta Connected su AWS, ma non compare mai "Port 7687 opened" e nessuno
    ascolta (successo il 07/10/2026, con 7635-7734 riservata). Si vede con
        netsh interface ipv4 show excludedportrange protocol=tcp
    In quel caso -PortaLocale apre il tunnel su un'altra porta, e per il .env
    o per una prova si imposta NEO4J_URI=bolt://localhost:<porta>.

    Serve il Session Manager plugin dell'AWS CLI, installato oppure estratto in
    %LOCALAPPDATA%\SessionManagerPlugin\bin (dall'archivio ufficiale
    https://s3.amazonaws.com/session-manager-downloads/plugin/latest/windows/SessionManagerPlugin.zip,
    file interno package.zip, cartella bin).

.EXAMPLE
    .\aws\tunnel-neo4j.ps1
    .\aws\tunnel-neo4j.ps1 -Browser
    .\aws\tunnel-neo4j.ps1 -PortaLocale 17687
#>
[CmdletBinding()]
param(
    [switch]$Browser,
    [int]$PortaLocale = 7687,
    [string]$Istanza = 'i-036be3456051b2a6c',
    [string]$Regione = 'eu-central-1',
    [string]$Profilo = ''
)

$ErrorActionPreference = 'Continue'
$profiloArg = @()
if ($Profilo) { $profiloArg = @('--profile', $Profilo) }

# Il plugin puo' stare anche fuori dal PATH, estratto dall'archivio ufficiale
# senza installazione (e senza diritti di amministratore): lo si cerca li'.
$locale = Join-Path $env:LOCALAPPDATA 'SessionManagerPlugin\bin'
if ((Test-Path (Join-Path $locale 'session-manager-plugin.exe')) -and ($env:PATH -notlike "*$locale*")) {
    $env:PATH = "$locale;$env:PATH"
}

if (-not (Get-Command session-manager-plugin -ErrorAction SilentlyContinue)) {
    Write-Host 'Manca il Session Manager plugin dell''AWS CLI: installalo dal link in testa a questo file.' -ForegroundColor Red
    exit 1
}

# Si aspettano i processi aws che questo script apre, non il plugin: il plugin
# parte un attimo dopo, e aspettarlo per nome faceva uscire lo script subito,
# lasciando il tunnel aperto e senza un modo pulito di chiuderlo.
$processi = @()
function Apri($porta, $locale = $porta) {
    $parametri = "portNumber=$porta,localPortNumber=$locale"
    $script:processi += Start-Process -NoNewWindow -PassThru aws -ArgumentList (@('ssm', 'start-session',
        '--region', $Regione, '--target', $Istanza, '--document-name', 'AWS-StartPortForwardingSession',
        '--parameters', $parametri) + $profiloArg)
}

Write-Host "Tunnel verso Neo4j ($Istanza): bolt://localhost:$PortaLocale" -ForegroundColor Cyan
Apri 7687 $PortaLocale
if ($Browser) {
    Write-Host 'Neo4j Browser: http://localhost:7474' -ForegroundColor Cyan
    Apri 7474
}
Write-Host 'Chiudi questa finestra (o Ctrl+C) per chiudere il tunnel.'
try {
    Wait-Process -Id $processi.Id -ErrorAction SilentlyContinue
}
finally {
    # Chiudendo si chiudono anche i plugin figli, che altrimenti resterebbero
    # in ascolto sulla porta anche senza la finestra.
    foreach ($p in $processi) {
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)" |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
}
