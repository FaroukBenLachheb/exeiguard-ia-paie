"""
Schéma pivot : DossierSalarie = combinaison du référentiel contractuel
(statique) et de l'historique EVP/bulletins (mensuel).

C'est ce modèle qui alimente les deux invocations du Moteur Compliance &
Validation :
- A2 (pré-calcul) : dernier EVP comparé au contrat
- A4 (post-calcul) : dernier bulletin comparé au bulletin M-1 et au contrat
"""

from typing import Optional

from pydantic import BaseModel, Field

from .bulletin import BulletinSalaire
from .contrat import ContratTravail
from .evp import EVPMensuel


class DossierSalarie(BaseModel):
    matricule: str
    contrat: ContratTravail
    evp_historique: list[EVPMensuel] = Field(default_factory=list)
    bulletins_historique: list[BulletinSalaire] = Field(default_factory=list)

    def dernier_evp(self) -> Optional[EVPMensuel]:
        return self.evp_historique[-1] if self.evp_historique else None

    def dernier_bulletin(self) -> Optional[BulletinSalaire]:
        return self.bulletins_historique[-1] if self.bulletins_historique else None

    def bulletin_precedent(self) -> Optional[BulletinSalaire]:
        """Utile pour les deltas M-1 calculés en A4."""
        if len(self.bulletins_historique) < 2:
            return None
        return self.bulletins_historique[-2]
