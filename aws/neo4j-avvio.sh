#!/bin/bash
# Avvio dell'istanza Neo4j Community su EC2 (user data, gira una volta al
# primo boot). Amazon Linux 2023 ARM, t4g.medium: 2 vCPU, 4 GB.
#
# Neo4j gira in Docker, immagine ufficiale Community 2026.09. Non la 5.26 LTS:
# le opzioni degli indici vettoriali che Aura usa (vector.quantization.type,
# vector.default_search_expansion_factor) esistono in Community solo dalla
# 2026.06/07, e senza l'espansione della ricerca la 5.26 ritrovava l'88% dei
# vicini veri contro il 100% di Aura (misurato il 22/09 su 5 domande).
# La password non
# sta in questo file ne' negli user data: si legge dal segreto
# graphresponsa/neo4j con il ruolo dell'istanza.
#
# Memoria, su 4 GB: 1 GB di heap, 1 GB di page cache, il resto al sistema,
# che tiene in cache i file dell'indice vettoriale (Lucene li legge dal disco
# attraverso la cache del sistema, non dalla page cache di Neo4j). Lo swap e'
# una riserva contro l'OOM killer durante la copia e la costruzione degli
# indici, non memoria su cui contare.
set -euxo pipefail
exec > >(tee -a /var/log/neo4j-avvio.log) 2>&1

dnf install -y docker jq python3-pip
systemctl enable --now docker

if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p /srv/neo4j/data /srv/neo4j/logs
pip3 install --quiet neo4j

TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300')
REGIONE=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region)

# Da qui niente traccia dei comandi: con `set -x` l'assegnazione della
# password finirebbe nel log di avvio (/var/log/cloud-init-output.log).
set +x
PW=$(aws secretsmanager get-secret-value --region "$REGIONE" --secret-id graphresponsa/neo4j \
       --query SecretString --output text | jq -r .NEO4J_PASSWORD)

# 7474 (Neo4j Browser) solo su localhost: ci si arriva con il port forwarding
# di Session Manager, mai dalla rete.
docker run -d --name neo4j --restart unless-stopped \
  -p 7687:7687 -p 127.0.0.1:7474:7474 \
  -v /srv/neo4j/data:/data -v /srv/neo4j/logs:/logs \
  -e NEO4J_AUTH="neo4j/${PW}" \
  -e NEO4J_server_memory_heap_initial__size=1g \
  -e NEO4J_server_memory_heap_max__size=1g \
  -e NEO4J_server_memory_pagecache_size=1g \
  -e NEO4J_db_tx__log_rotation_retention__policy="1G size" \
  neo4j:2026.09.0-community
set -x
unset PW
echo "neo4j avviato"
