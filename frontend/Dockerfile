# Dockerfile — service frontend (Streamlit)
#
# Conteneurise l'interface Streamlit (frontend/app.py), jusqu'ici lancee
# en Python natif sur l'hote (cf. commentaire "Lancement local" en tete
# de app.py). Dernier service applicatif du pipeline a passer en
# conteneur ; suit le meme pattern que les Dockerfiles deja en place
# (orchestrateur, extracteur-evp, compliance-validation, integration-sage,
# rag) : voir docs/architecture/dependances-partagees.md.
#
# Dependances partagees (shared/) : contrairement a rag/, qui n'importe
# rien de shared/schemas a ce jour, frontend/app.py importe REELLEMENT
# `from shared.schemas import ContratTravail, StatutSalarie` (validation
# du contrat saisi a l'ecran 0 avec le vrai modele Pydantic, voir
# commentaire en tete de app.py). shared/requirements.txt est donc bien
# installe ici, pas seulement frontend/requirements.txt.
#
# Difference de structure avec les services FastAPI : ceux-ci exposent un
# package "app/" lance via uvicorn (WORKDIR=/app, "app" et "shared" cote
# a cote). frontend/app.py est un script unique lance via `streamlit
# run`, et fait lui-meme un sys.path.insert(0, ROOT) ou ROOT = le parent
# du dossier contenant app.py (cf. app.py) pour retomber sur shared/. La
# structure frontend/ + shared/ est donc preservee telle quelle sous
# /app (pas aplatie), et WORKDIR passe a /app/frontend juste avant le
# CMD : necessaire aussi pour que Streamlit trouve
# frontend/.streamlit/config.toml, qu'il cherche relatif au repertoire
# courant du processus (pas relatif au script lance).
#
# tests/fixtures/ (chargement de cas de test EVP dans l'UI, cf.
# lister_fixtures() dans app.py) n'est PAS copie dans l'image : ce n'est
# pas necessaire au fonctionnement du service (app.py degrade
# proprement si le dossier est absent, lister_fixtures() renvoie alors
# une liste vide) et ce ne sont pas des donnees de prod.

FROM python:3.11-slim

WORKDIR /app

COPY frontend/requirements.txt ./requirements.txt
COPY shared/requirements.txt ./shared-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r shared-requirements.txt

COPY frontend/ ./frontend/
COPY shared/ ./shared/

WORKDIR /app/frontend

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=2)" || exit 1

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
