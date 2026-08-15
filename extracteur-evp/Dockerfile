# Dockerfile — service extracteur-evp
#
# Squelette en attendant l'implementation metier (OCR + parsing EVP,
# phases D.4+). Suffisant pour demarrer dans docker-compose et exposer
# GET /health, en attendant le vrai code.

FROM python:3.11-slim

WORKDIR /app

COPY extracteur-evp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY extracteur-evp/app/ ./app/

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
