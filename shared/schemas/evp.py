"""
Schéma de l'EVP (Élément Variable de Paie) mensuel.

Dérivé du fichier réel : 06_-_Variables_Soft_It_Juin_2026_Bis.xlsx
Point d'attention observé sur le fichier réel : le champ MATRICULE est
souvent vide côté EVP -> la jointure avec le référentiel salarié doit
prévoir un fallback sur (nom, prenom).
"""

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class TypeAbsence(str, Enum):
    CP = "CP"
    RTT = "RTT"
    MALADIE = "MALADIE"
    CONGE_SANS_SOLDE = "CONGE_SANS_SOLDE"
    INJUSTIFIEE = "INJUSTIFIEE"


class TypeContrat(str, Enum):
    CDI = "CDI"
    CDD = "CDD"
    ALTERNANCE = "ALTERNANCE"
    STAGE = "STAGE"


class AbsencePeriode(BaseModel):
    """Une ligne d'absence telle que saisie dans l'EVP (groupée par type)."""

    type: TypeAbsence
    nb_jours: float = Field(ge=0)
    # Format libre observé dans le fichier réel : "15 et 25/05" (texte)
    # ou une date unique. A normaliser en liste de `date` lors du parsing,
    # mais on garde le texte brut ici pour ne rien perdre à l'extraction.
    dates_brutes: str


class EVPMensuel(BaseModel):
    """Une ligne EVP = un salarié pour un mois donné."""

    periode: date  # 1er jour du mois, ex: 2026-06-01
    matricule: Optional[str] = None
    nom: Optional[str] = None
    prenom: str

    poste: str
    type_contrat: TypeContrat
    debut_contrat: date
    fin_contrat: Optional[date] = None  # None attendu pour un CDI

    heure_mensuel: Optional[float] = None
    salaire_an: float = Field(gt=0)

    mutuelle: Optional[str] = None  # ex: "Seul", "Avec enfants"
    nb_ticket_restaurant: int = Field(ge=0, default=0)
    pass_navigo: bool = False

    prime: Optional[float] = Field(default=None, ge=0)
    acompte: Optional[float] = Field(default=None, ge=0)
    heures_sup: Optional[float] = Field(default=None, ge=0)

    absences: list[AbsencePeriode] = Field(default_factory=list)
    remarques: Optional[str] = None

    @model_validator(mode="after")
    def cdi_sans_date_fin(self):
        if self.type_contrat == TypeContrat.CDI and self.fin_contrat is not None:
            raise ValueError("Un CDI ne doit pas avoir de date de fin de contrat")
        return self

    @model_validator(mode="after")
    def identifiant_minimal_present(self):
        if not self.matricule and not (self.nom or self.prenom):
            raise ValueError(
                "Aucun identifiant exploitable (ni matricule, ni nom/prénom) "
                "pour rattacher cette ligne EVP à un salarié"
            )
        return self
