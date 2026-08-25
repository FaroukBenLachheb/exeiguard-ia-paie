"""orchestrateur/app/schemas.py — schémas des requêtes/réponses API.

Renommé volontairement (pas "models.py") pour éviter toute collision
d'import avec db/models.py (SQLAlchemy) une fois les deux dans sys.path.
"""

from typing import Any, Optional

from pydantic import BaseModel


class CreationDossierRequest(BaseModel):
    matricule: Optional[str] = None
    contrat: dict[str, Any]  # ContratTravail.model_dump() côté client
    evp: Optional[dict[str, Any]] = None  # EVPMensuel.model_dump(), optionnel à la création


class DossierResponse(BaseModel):
    id: str
    matricule: Optional[str]
    prenom: str
    etat: str
    triggers_disponibles: list[str]


class TransitionRequest(BaseModel):
    action: str  # ex: "extraire_evp", "detecter_ecart"...
    acteur: str  # ex: "gestionnaire", "orchestrateur", "responsable_validation"
    commentaire: Optional[str] = None


class TransitionResponse(BaseModel):
    id: str
    etat_precedent: str
    etat: str
    triggers_disponibles: list[str]
