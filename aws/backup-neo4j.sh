#!/bin/bash
# ==============================================================================
# Script di Backup Automatico del Knowledge Graph Neo4j su Amazon S3
# Da eseguire tramite Cron (es. ogni notte alle 03:00)
# ==============================================================================
set -e

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="/tmp/neo4j_backups"
BUCKET_NAME=${S3_BACKUP_BUCKET:-"graphresponsa-backups"}

mkdir -p "$BACKUP_DIR"

echo "=== Inizio Backup Neo4j ($TIMESTAMP) ==="

# Esegue il dump del database all'interno del container Docker
docker exec graphresponsa-neo4j neo4j-admin database dump neo4j --to-path=/var/lib/neo4j/import/

# Sposta l'archivio compresso nella cartella temporanea
DUMP_FILE="$BACKUP_DIR/neo4j_dump_$TIMESTAMP.dump"
docker cp graphresponsa-neo4j:/var/lib/neo4j/import/neo4j.dump "$DUMP_FILE"
docker exec graphresponsa-neo4j rm /var/lib/neo4j/import/neo4j.dump

# Caricamento sicuro su Bucket Amazon S3
if command -v aws &> /dev/null; then
    echo "Caricamento su S3 ($BUCKET_NAME)..."
    aws s3 cp "$DUMP_FILE" "s3://$BUCKET_NAME/backups/neo4j_dump_$TIMESTAMP.dump"
    echo "Backup S3 completato."
fi

# Pulizia file temporanei locali più vecchi di 7 giorni
rm -f "$DUMP_FILE"
echo "=== Backup completato con successo ==="
