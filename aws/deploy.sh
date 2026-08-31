#!/bin/bash
# ==============================================================================
# Script di Deployment & Aggiornamento Automatico per GraphResponsa su AWS
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR/.."

echo "=== 1. Controllo file di configurazione (.env) ==="
if [ ! -f "aws/.env.prod" ]; then
    if [ -f ".env" ]; then
        echo "Copia del file .env esistente in aws/.env.prod..."
        cp .env aws/.env.prod
    else
        echo "ERRORE: Manca il file aws/.env.prod!"
        echo "Copia aws/.env.prod.example in aws/.env.prod e compila le chiavi API."
        exit 1
    fi
fi

echo "=== 2. Aggiornamento codice sorgente da GitHub ==="
git pull origin main || true

echo "=== 3. Build dei container Docker e avvio stack di produzione ==="
docker compose --env-file aws/.env.prod -f aws/docker-compose.prod.yaml build --pull
docker compose --env-file aws/.env.prod -f aws/docker-compose.prod.yaml up -d

echo "=== 4. Verifica dello stato dei servizi ==="
sleep 5
docker compose --env-file aws/.env.prod -f aws/docker-compose.prod.yaml ps

echo "=============================================================================="
echo " Deployment completato con successo!"
echo " L'applicazione GraphResponsa e Neo4j Community sono attivi su Docker."
echo "=============================================================================="
