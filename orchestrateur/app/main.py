"""
orchestrateur/app/main.py

API de l'Orchestrateur (Phase 3). Expose :
  POST /dossiers                    -> créer un dossier, état initial A1
  GET  /dossiers/{id}/etat          -> état courant + triggers disponibles
  POST /dossiers/{id}/transition    -> déclencher une transition

Chaque transition (réussie ou refusée) est journalisée dans audit_log —
c'est le principe directeur "traçabilité complète" du guide, appliqué au
niveau le plus bas du pipeline.

Point d'attention pour la Phase 9 (assemblage Docker) : ce service importe
directement les modèles SQLAlchemy du dossier top-level `db/`. En
conteneurisation, prévoir soit un contexte de build incluant `db/` dans
l'image orchestrateur, soit l'extraction de models.py/database.py dans un
package partagé (sur le même principe que shared/schemas). Pour le
développement local (D.3), l'import direct suffit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Rend db/models.py et db/database.py importables. Deux chemins candidats
# testés dans l'ordre : cas conteneur (WORKDIR /app, app/ et db/ copiés
# côte à côte -> /app/app/main.py, db/ à parents[1]) puis cas dépôt local
# (<repo>/orchestrateur/app/main.py, db/ à parents[2]). Bug corrigé le
# 26/08/2026 : la version initiale ne testait que parents[2], ce qui
# résolvait en "/db" (inexistant) dans le conteneur et faisait planter le
# service au démarrage (ModuleNotFoundError: No module named 'database').
_HERE = Path(__file__).resolve()
# Bug #2 corrigé le 26/08/2026 : "from state_machine import ..." / "from
# schemas import ..." ci-dessous sont des imports bare (pas relatifs), qui
# supposent que le répertoire contenant main.py lui-même est sur
# sys.path. Faux par défaut en conteneur (uvicorn app.main:app charge ce
# fichier comme sous-module du package "app" ; seul /app est sur
# sys.path, pas /app/app) -> ModuleNotFoundError: No module named
# 'state_machine'. Confirmé par exécution réelle du conteneur reconstruit.
sys.path.insert(0, str(_HERE.parent))
for _candidate in (_HERE.parents[1] / "db", _HERE.parents[2] / "db"):
    if _candidate.is_dir():
        sys.path.insert(0, str(_candidate))
        break

from fastapi import FastAPI, HTTPException  # noqa: E402
from transitions import MachineError  # noqa: E402

from database import SessionLocal, init_db  # noqa: E402
from models import AuditLog, Dossier  # noqa: E402

from state_machine import DossierStateMachine  # noqa: E402
from schemas import (  # noqa: E402  (schémas API, distincts de db/models.py)
    CreationDossierRequest,
    DossierResponse,
    TransitionRequest,
    TransitionResponse,
)

app = FastAPI(title="Exeiguard - Orchestrateur", version="0.1.0")


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


def _audit(session, dossier_id: str, acteur: str, action: str, resultat: str, details: dict | None = None):
    session.add(
        AuditLog(
            dossier_id=dossier_id,
            acteur=acteur,
            action=action,
            resultat=resultat,
            details_json=details,
        )
    )
    session.commit()


@app.post("/dossiers", response_model=DossierResponse, status_code=201)
def creer_dossier(payload: CreationDossierRequest):
    session = SessionLocal()
    try:
        import datetime as dt

        periode_str = (payload.evp or {}).get("periode")
        periode = (
            dt.date.fromisoformat(periode_str)
            if periode_str
            else dt.date.today().replace(day=1)
        )

        dossier = Dossier(
            matricule=payload.matricule,
            prenom=payload.contrat.get("prenom", "inconnu"),
            nom=payload.contrat.get("nom"),
            periode=periode,
            etat="A1",
            contrat_json=payload.contrat,
        )
        session.add(dossier)
        session.commit()
        session.refresh(dossier)

        _audit(session, dossier.id, "orchestrateur", "creation_dossier", "succes")

        sm = DossierStateMachine(etat_initial=dossier.etat)
        return DossierResponse(
            id=dossier.id,
            matricule=dossier.matricule,
            prenom=dossier.prenom,
            etat=dossier.etat,
            triggers_disponibles=sm.triggers_disponibles(),
        )
    finally:
        session.close()


@app.get("/dossiers/{dossier_id}/etat", response_model=DossierResponse)
def obtenir_etat(dossier_id: str):
    session = SessionLocal()
    try:
        dossier = session.get(Dossier, dossier_id)
        if dossier is None:
            raise HTTPException(status_code=404, detail="Dossier introuvable")
        sm = DossierStateMachine(etat_initial=dossier.etat)
        return DossierResponse(
            id=dossier.id,
            matricule=dossier.matricule,
            prenom=dossier.prenom,
            etat=dossier.etat,
            triggers_disponibles=sm.triggers_disponibles(),
        )
    finally:
        session.close()


@app.post("/dossiers/{dossier_id}/transition", response_model=TransitionResponse)
def transitionner(dossier_id: str, payload: TransitionRequest):
    session = SessionLocal()
    try:
        dossier = session.get(Dossier, dossier_id)
        if dossier is None:
            raise HTTPException(status_code=404, detail="Dossier introuvable")

        etat_precedent = dossier.etat
        sm = DossierStateMachine(etat_initial=etat_precedent)

        try:
            nouvel_etat = sm.declencher(payload.action)
        except MachineError as exc:
            _audit(
                session,
                dossier_id,
                payload.acteur,
                f"transition_refusee:{payload.action}",
                "echec",
                {"raison": str(exc), "etat_courant": etat_precedent},
            )
            raise HTTPException(
                status_code=409,
                detail=f"Transition '{payload.action}' impossible depuis l'état {etat_precedent}",
            )

        dossier.etat = nouvel_etat
        session.commit()

        _audit(
            session,
            dossier_id,
            payload.acteur,
            f"transition_etat:{etat_precedent}->{nouvel_etat}",
            "succes",
            {"action": payload.action, "commentaire": payload.commentaire},
        )

        sm2 = DossierStateMachine(etat_initial=nouvel_etat)
        return TransitionResponse(
            id=dossier_id,
            etat_precedent=etat_precedent,
            etat=nouvel_etat,
            triggers_disponibles=sm2.triggers_disponibles(),
        )
    finally:
        session.close()
