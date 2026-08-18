# Dockerfile — service integration-sage
#
# Squelette en attendant l'implementation metier (integration Sage,
# mock puis reelle, phases D.4+). Suffisant pour demarrer dans
# docker-compose et exposer GET /health, en attendant le vrai code.
#
# Dependances partagees (shared/) : voir
# docs/architecture/dependances-partagees.md pour le pattern commun aux
# Dockerfiles applicatifs. shared/ est copie a cote de app/,
# shared/requirements.txt est installe en plus du requirements.txt du
# service, et PYTHONPATH inclut /app/shared pour que
# `from schemas import ...` fonctionne sans sys.path.insert dans le code
# applicatif (utile des que ce service importera shared/schemas, phases
# D.4+).

FROM python:3.11-slim

WORKDIR /app

COPY integration-sage/requirements.txt ./requirements.txt
COPY shared/requirements.txt ./shared-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r shared-requirements.txt

COPY integration-sage/app/ ./app/
COPY shared/ ./shared/

ENV PYTHONPATH=/app/shared

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
