"""
integration-sage/app/main.py

Squelette du service integration-sage : expose uniquement GET /health
en attendant l'implementation de l'integration Sage (mock puis reel,
phases D.4+). Permet a la stack docker-compose de demarrer et d'etre
testee de bout en bout des maintenant.
"""

from fastapi import FastAPI

app = FastAPI(title="Integration Sage", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "integration-sage"}
