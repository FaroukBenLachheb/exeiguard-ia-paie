"""
integration-sage/app/main.py

Service integration-sage : GET /health, et POST /calculer qui simule le
calcul d'un bulletin de paie via mock/calcul_simule.py.

*** MOCK DE DEMONSTRATION — SANS VALEUR REGLEMENTAIRE ***
Ce service n'appelle aucune API Sage réelle : /calculer retourne un
BulletinSalaire construit par une formule factice et déterministe (voir
mock/calcul_simule.py), en attente d'un accès à l'API Sage réelle (cf.
integration-sage/README.md). Objectif unique : permettre au pipeline
A1->A6 d'avancer jusqu'à A6 en démonstration, sans réimplémenter un
moteur de paie.
"""

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from shared.schemas import DossierSalarie

from mock.calcul_simule import calculer_bulletin_simule

app = FastAPI(title="Integration Sage (mock)", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "integration-sage"}


@app.post("/calculer")
def calculer(dossier: DossierSalarie) -> dict:
    try:
        bulletin = calculer_bulletin_simule(dossier)
    except ValidationError as exc:
        # Frontière API : un BulletinSalaire structurellement invalide (ex:
        # contrat de reference incoherent) doit devenir un 422 explicite,
        # pas une 500 generique.
        raise HTTPException(status_code=422, detail=f"Calcul du bulletin simulé impossible : {exc}") from None
    return jsonable_encoder(bulletin)
