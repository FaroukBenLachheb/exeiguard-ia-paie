# Dockerfile — service rag
#
# Conteneurise le service de recherche semantique CCN SYNTEC (D.6
# partiel, commit 20eac05), jusqu'ici lance en Python natif sur l'hote de
# la VM (nohup, OLLAMA_HOST/QDRANT_HOST surcharges en "localhost" -
# fragilite connue, cf. rag/app/config.py et docs/architecture/references/
# et rag/README.md). Suit exactement le meme pattern que les Dockerfiles
# applicatifs deja en place (orchestrateur, extracteur-evp,
# compliance-validation, integration-sage).
#
# Dependances partagees (shared/) : voir
# docs/architecture/dependances-partagees.md pour le pattern commun.
# shared/ est copie a cote de app/, shared/requirements.txt est installe
# en plus du requirements.txt du service, et PYTHONPATH inclut
# /app/shared pour que `from schemas import ...` fonctionne sans
# sys.path.insert dans le code applicatif (rag n'importe pas encore
# shared/schemas a ce jour, mais suit le meme pattern que les autres
# services pour rester coherent des que ce sera le cas).
#
# Corpus CCN SYNTEC (docs/architecture/references/convention_collective_
# syntec.pdf) : PAS copie dans l'image (ce n'est pas du code applicatif,
# et seul rag/app/ingestion/ingest.py - lance manuellement, pas au
# demarrage du conteneur - en a besoin). Monte en volume en lecture seule
# par docker-compose.yml / docker-compose.dev.yml, au chemin absolu que
# calcule ingest.py (_RAG_DIR.parent / "docs/architecture/references/...")
# une fois WORKDIR=/app, soit /docs/architecture/references dans le
# conteneur.

FROM python:3.11-slim

WORKDIR /app

COPY rag/requirements.txt ./requirements.txt
COPY shared/requirements.txt ./shared-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r shared-requirements.txt

COPY rag/app/ ./app/
COPY shared/ ./shared/

ENV PYTHONPATH=/app/shared

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
