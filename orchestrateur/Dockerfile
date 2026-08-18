# Dockerfile — service orchestrateur
#
# Construit l'image FastAPI de l'orchestrateur. A ce stade du projet,
# orchestrateur/app/main.py importe directement db/database.py et
# db/models.py (imports absolus non packages, voir le commentaire dans
# app/main.py) : le dossier db/ est donc copie dans l'image en plus de
# app/, a cote, pour que ces imports fonctionnent une fois le conteneur
# demarre. Ce contexte de build doit etre la racine du depot (pas
# orchestrateur/) pour que db/ soit accessible.
#
# Dependances partagees (shared/) : voir
# docs/architecture/dependances-partagees.md pour le pattern commun aux
# Dockerfiles applicatifs (orchestrateur, extracteur-evp,
# compliance-validation, integration-sage). shared/ est copie a cote de
# app/, shared/requirements.txt est installe en plus du requirements.txt
# du service, et PYTHONPATH inclut /app/shared pour que
# `from schemas import ...` fonctionne sans sys.path.insert dans le code
# applicatif.

FROM python:3.11-slim

WORKDIR /app

COPY orchestrateur/requirements.txt ./requirements.txt
COPY shared/requirements.txt ./shared-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r shared-requirements.txt

COPY orchestrateur/app/ ./app/
COPY db/ ./db/
COPY shared/ ./shared/

ENV PYTHONPATH=/app/shared

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
