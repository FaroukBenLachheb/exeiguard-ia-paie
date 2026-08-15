"""
orchestrateur/app/main.py

Point d'entree FastAPI du service orchestrateur.

Import de db/ : a ce stade du projet, db/database.py et db/models.py
utilisent des imports absolus ("from models import Base", voir
db/database.py et le meme contournement dans db/migrations/env.py et
db/test_insertion.py). db/ n'est pas encore package comme un module
Python installable partage entre services (prevu pour une phase
ulterieure). En attendant, on ajoute le dossier db/ a sys.path ici pour
pouvoir importer database.py et models.py depuis l'orchestrateur.

Consequence pour le conteneur : orchestrateur/Dockerfile doit copier le
dossier db/ en plus de orchestrateur/app/, a cote (meme niveau que app/
dans le WORKDIR), sinon cet import echoue au demarrage.
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

_HERE = Path(__file__).resolve()

# Cas conteneur : WORKDIR /app avec ./app (ce fichier) et ./db copies cote
# a cote (voir orchestrateur/Dockerfile). Cas depot local : orchestrateur/app
# (ce fichier) et db/ cote a cote a la racine du depot.
for _candidate in (_HERE.parent.parent / "db", _HERE.parent.parent.parent / "db"):
    if _candidate.is_dir():
        sys.path.insert(0, str(_candidate))
        break

from fastapi import FastAPI  # noqa: E402

from database import init_db  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Orchestrateur", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "orchestrateur"}
