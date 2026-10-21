# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# Immagine di AIladoc. Il contesto di build è la RADICE del progetto:
#   docker build -f docker/Dockerfile -t meticulo/ailadoc:dev .
# Le esclusioni dal contesto sono in docker/Dockerfile.dockerignore (letto da BuildKit).
#
# Anteprima di PowerPoint/Word/LibreOffice come PDF (aggiunge ~400 MB).
# Per un'immagine leggera: docker build -f docker/Dockerfile --build-arg OFFICE_PREVIEW=false .
ARG OFFICE_PREVIEW=true
ARG MERMAID_VERSION=11.4.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    DATA_DIR=/data \
    OFFICE_PREVIEW=${OFFICE_PREVIEW}

RUN set -eux; \
    apt-get update; \
    if [ "$OFFICE_PREVIEW" = "true" ]; then \
      apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        fonts-dejavu fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea fonts-noto-core; \
    fi; \
    rm -rf /var/lib/apt/lists/*; \
    useradd --uid 1000 --create-home --home-dir /home/app app; \
    mkdir -p /data && chown app:app /data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY sample-docs ./sample-docs
# Mermaid servito in locale (nessuna dipendenza da CDN a runtime)
ADD --chmod=644 https://cdn.jsdelivr.net/npm/mermaid@${MERMAID_VERSION}/dist/mermaid.min.js ./app/static/vendor/mermaid.min.js
# leggibile dall'utente non-root anche se i sorgenti hanno permessi 600
RUN chmod -R a+rX /app

USER app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
