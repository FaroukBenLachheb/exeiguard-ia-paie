# Dockerfile — service orchestrateur
#
# Construit l'image FastAPI de l'orchestrateur. A ce stade du projet,
# orchestrateur/app/main.py importe directement db/database.py et
# db/models.py (imports absolus non packages, voir le commentaire dans
# app/main.py) : le dossier db/ est donc copie dans l'image en plus de
# app/, a cote, pour que ces imports fonctionnent une fois le conteneur
# demarre. Ce contexte de build doit etre la racine du depot (pas
# orchestrateur/) pour que db/ soit accessible.

FROM python:3.11-slim

WORKDIR /app

COPY orchestrateur/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY orchestrateur/app/ ./app/
COPY db/ ./db/

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
