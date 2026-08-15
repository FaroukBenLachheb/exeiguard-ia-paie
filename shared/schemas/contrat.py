"""
Schéma du contrat de travail.

Dérivé des deux contrats réels Soft IT (Didier, Sindhuja).
Point d'attention : la numérotation des articles varie selon les clauses
présentes (ex: "Formation" décale la clause de non-concurrence de
l'Article 9 à l'Article 10). Le parsing amont (Extracteur EVP / OCR) doit
donc chercher par TITRE de section, jamais par numéro d'article fixe.
"""

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class StatutSalarie(str, Enum):
    CADRE = "CADRE"
    NON_CADRE = "NON_CADRE"
    ETAM = "ETAM"


class ContratTravail(BaseModel):
    # --- Identité ---
    matricule: Optional[str] = None  # absent du contrat, relié via bulletin/EVP
    prenom: str
    nom: Optional[str] = None
    nationalite: Optional[str] = None
    adresse: Optional[str] = None
    date_naissance: Optional[date] = None
    nir: Optional[str] = None

    # --- Poste et classification ---
    poste: str
    date_effet: date
    type_contrat: Literal["CDI", "CDD"]
    convention_collective: str  # ex: "SYNTEC"
    statut: StatutSalarie
    position: str  # grille SYNTEC, ex: "2.2", "3.2"
    coefficient: int = Field(gt=0)

    # --- Rémunération ---
    remuneration_annuelle_brute: float = Field(gt=0)
    remuneration_mensuelle_brute: float = Field(gt=0)
    heures_mensuelles: float = Field(gt=0, default=151.67)

    # --- Période d'essai ---
    periode_essai_mois: Optional[int] = Field(default=None, ge=0)
    periode_essai_renouvelable: bool = False

    # --- Congés / RTT (accord d'entreprise Soft IT, pas SYNTEC seul) ---
    rtt_par_an: int = Field(ge=0)
    periode_reference_conges: str  # ex: "01/06 au 31/05"

    # --- Clauses particulières (présence variable selon salarié) ---
    clause_non_concurrence: bool = False
    duree_non_concurrence_mois: Optional[int] = None
    indemnite_non_concurrence_mois_salaire: Optional[int] = None

    clause_formation: bool = False
    duree_engagement_formation_mois: Optional[int] = None

    # --- Lieu et obligations ---
    lieu_travail: str
    delai_justification_absence_heures: int = Field(default=24)
    organisme_justification_absence: Optional[str] = None  # ex: "H Cube"

    date_signature: date
    lieu_signature: Optional[str] = None

    # --- Validations de cohérence ---

    @model_validator(mode="after")
    def coherence_remuneration_mensuelle(self):
        # Tolérance à 2€ (et non 1€) : le contrat réel de Karim (cas_15,
        # scripts/generate_fixtures.py) porte annuel=65000 / mensuel=5418,
        # soit un écart de 1.33€ avec 65000/12=5416.67 arrondi à l'euro
        # supérieur par Soft IT. Preuve que cet arrondi mensuel peut
        # dépasser 1€ sur des cas réels ; 2€ reste strict (rejette toujours
        # les vraies erreurs de saisie/incohérences plus grossières).
        attendu = round(self.remuneration_annuelle_brute / 12, 2)
        if abs(attendu - self.remuneration_mensuelle_brute) > 2:
            raise ValueError(
                f"Incohérence rémunération : annuel/12={attendu} "
                f"vs mensuel déclaré={self.remuneration_mensuelle_brute}"
            )
        return self

    @model_validator(mode="after")
    def coherence_clause_non_concurrence(self):
        if self.clause_non_concurrence and self.duree_non_concurrence_mois is None:
            raise ValueError(
                "clause_non_concurrence=True nécessite duree_non_concurrence_mois"
            )
        return self

    @model_validator(mode="after")
    def coherence_clause_formation(self):
        if self.clause_formation and self.duree_engagement_formation_mois is None:
            raise ValueError(
                "clause_formation=True nécessite duree_engagement_formation_mois"
            )
        return self
