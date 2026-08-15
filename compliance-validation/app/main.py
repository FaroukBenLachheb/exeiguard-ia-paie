"""
compliance-validation/app/main.py

Squelette du service compliance-validation : expose uniquement GET
/health en attendant l'implementation du moteur de regles (rule engine
+ RAG, phases D.4+). Permet a la stack docker-compose de demarrer et
d'etre testee de bout en bout des maintenant.
"""

from fastapi import FastAPI

app = FastAPI(title="Compliance Validation", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "compliance-validation"}
