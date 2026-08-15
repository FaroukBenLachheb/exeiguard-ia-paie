"""
extracteur-evp/app/main.py

Squelette du service extracteur-evp : expose uniquement GET /health en
attendant l'implementation de l'extraction EVP (OCR + parsing, phases
D.4+). Permet a la stack docker-compose de demarrer et d'etre testee de
bout en bout des maintenant.
"""

from fastapi import FastAPI

app = FastAPI(title="Extracteur EVP", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "extracteur-evp"}
