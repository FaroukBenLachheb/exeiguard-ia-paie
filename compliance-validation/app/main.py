"""
compliance-validation/app/main.py

Service compliance-validation : GET /health, et POST /evaluer qui
exécute les 10 règles du Rule Engine (RG-01 à RG-10) sur un
DossierSalarie reçu en JSON. Réutilise
app/rule_engine/engine.py:evaluer_toutes_les_regles tel quel : aucune
règle réimplémentée ici, ce module se contente de brancher ce code déjà
testé sur une route HTTP. La validation du corps de requête contre le
schéma DossierSalarie (dossier incomplet/invalide -> 422) est déléguée à
FastAPI/Pydantic, sans code de validation supplémentaire.
"""

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder

from shared.schemas import DossierSalarie

from .rule_engine.engine import evaluer_toutes_les_regles

app = FastAPI(title="Compliance Validation", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "compliance-validation"}


@app.post("/evaluer")
def evaluer(dossier: DossierSalarie) -> dict:
    resultats = evaluer_toutes_les_regles(dossier)
    return {"matricule": dossier.matricule, "resultats": jsonable_encoder(resultats)}
