"""
Schéma d'une rupture de contrat de travail.

Un DossierSalarie avec une rupture non nulle alimente les futures règles du
Rule Engine liées à la fin de contrat, notamment RG-06 (préavis de rupture) :
la durée effective de préavis (date_fin_contrat_effective - date_notification)
sera comparée aux minimas CCN SYNTEC / Code du travail selon le statut et
l'ancienneté du salarié.
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, model_validator


class RuptureContrat(BaseModel):
    type_rupture: Literal[
        "demission", "licenciement", "rupture_conventionnelle", "fin_periode_essai"
    ]
    date_notification: date
    date_fin_contrat_effective: date
    motif: Optional[str] = None

    @model_validator(mode="after")
    def coherence_dates(self):
        if self.date_fin_contrat_effective < self.date_notification:
            raise ValueError(
                "date_fin_contrat_effective ne peut pas être antérieure à "
                "date_notification"
            )
        return self
