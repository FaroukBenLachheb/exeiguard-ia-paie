"""orchestrateur/app/schemas.py — schémas des requêtes/réponses API.

Renommé volontairement (pas "models.py") pour éviter toute collision
d'import avec db/models.py (SQLAlchemy) une fois les deux dans sys.path.
"""

from typing import Any, Optional

from pydantic import BaseModel


class CreationDossierRequest(BaseModel):
    matricule: Optional[str] = None
    # Optionnel désormais (JOUR 4, écran 0 "salarié déjà connu") : soit un
    # contrat complet (ContratTravail.model_dump() côté client), soit
    # `matricule_reference` seul, auquel cas le contrat est recopié
    # depuis le dernier dossier connu portant ce matricule (cf.
    # orchestrateur/app/main.py::creer_dossier). Au moins l'un des deux
    # est requis - vérifié dans la route, pas ici, pour renvoyer un 400
    # explicite plutôt qu'une 422 générique de validation Pydantic.
    contrat: Optional[dict[str, Any]] = None
    matricule_reference: Optional[str] = None
    evp: Optional[dict[str, Any]] = None  # EVPMensuel.model_dump(), optionnel à la création


class SalarieConnu(BaseModel):
    matricule: str
    prenom: str
    nom: Optional[str]
    contrat: dict[str, Any]
    dernier_dossier_id: str


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
