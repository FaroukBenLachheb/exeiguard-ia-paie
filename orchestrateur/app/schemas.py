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
    # Requis uniquement pour action="extraire_evp" : contenu du fichier EVP
    # .xlsx encodé en base64. Choix retenu (vs. chemin de fichier côté
    # conteneur) car il voyage dans le même JSON que le reste de la requête
    # de transition, sans dépendre d'un volume partagé entre l'appelant et
    # le conteneur orchestrateur — le plus simple à appeler depuis un
    # client HTTP externe (curl, frontend) comme depuis l'orchestrateur
    # lui-même, qui le retransmet tel quel (décodé) en upload multipart à
    # extracteur-evp.
    evp_fichier_base64: Optional[str] = None


class TransitionResponse(BaseModel):
    id: str
    etat_precedent: str
    etat: str
    triggers_disponibles: list[str]
