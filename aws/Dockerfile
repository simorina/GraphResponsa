# Immagine del solo servizio web.
#
# Il frontend NON entra qui: viene compilato a parte e caricato su S3, servito
# da CloudFront. Cosi' aggiornare la UI non richiede di ricostruire e
# ridistribuire il backend, e l'immagine resta di solo Python.

FROM python:3.12-slim

# Non gira come root: se qualcuno esce dal processo, esce con pochi poteri.
RUN useradd --create-home --shell /bin/false responsa

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Le dipendenze prima del codice: cambiano di rado, e cosi' lo strato resta
# in cache fra una compilazione e l'altra.
COPY requirements-servizio.txt .
RUN pip install --no-cache-dir -r requirements-servizio.txt

COPY src/ ./src/

USER responsa

EXPOSE 8000

# Un solo worker: l'agente e' legato all'attesa delle API, non alla CPU, e
# ampliare si fa aggiungendo task su Fargate, non processi nel container.
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
