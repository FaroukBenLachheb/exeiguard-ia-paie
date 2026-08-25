"""
Schéma du bulletin de salaire (sortie du mock Sage en PoC, sortie Sage réelle en prod).


Dérivé des deux bulletins réels Soft IT (Didier, Sindhuja) — mai 2026.
Point d'attention observé : certaines lignes sont conditionnelles
(ex: "Pass Navigo" absent chez Didier, présent chez Sindhuja car son EVP
porte PASS_NAVIGO=OUI). Ne pas figer une liste de lignes obligatoires.
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class LigneCotisation(BaseModel):
    """Une ligne générique du tableau de cotisations ou d'éléments de rémunération."""

    libelle: str
    base: Optional[float] = None
    taux: Optional[float] = None
    montant_salarial: Optional[float] = None
    montant_patronal: Optional[float] = None


class BulletinSalaire(BaseModel):
    # --- En-tête ---
    periode_debut: date
    periode_fin: date
    matricule: str
    nir: Optional[str] = None
    date_entree: date
    date_premiere_entree: date  # peut différer de date_entree (reprise d'ancienneté)
    emploi: str
    qualification: str  # ex: "Cadre Position 2.2 / Coeff - 130"
    convention_collective: str

    # --- Rémunération ---
    salaire_base_mensuel: float = Field(gt=0)
    complement_salaire: Optional[float] = None
    absences: list[LigneCotisation] = Field(default_factory=list)
    total_remuneration_brute: float = Field(gt=0)

    # --- Cotisations ---
    cotisations: list[LigneCotisation] = Field(default_factory=list)
    total_cotisations_salariales: float
    total_cotisations_patronales: float

    montant_net_social: float
    titres_restaurant: Optional[float] = None
    pass_navigo: Optional[float] = None  # ligne conditionnelle, cf. docstring

    jours_cp_acquis: float = 0
    jours_rtt_acquis: float = 0
    jours_rtt_pris: float = 0

    # --- Net et impôt ---
    net_a_payer_avant_ir: float
    impot_revenu_base: float
    impot_revenu_taux: float
    impot_revenu_montant: float
    impot_revenu_cumul: float

    net_a_payer: float = Field(gt=0)
    date_paiement: date
    mode_reglement: str

    # --- Cumuls et soldes congés (bloc bas de bulletin) ---
    heures_payees_cumul: float
    remuneration_brute_cumul: float
    cp_n1_acquis: float = 0
    cp_n1_pris: float = 0
    cp_n1_solde: float = 0
    cp_n_acquis: float = 0
    rtt_acquis: float = 0
    rtt_pris: float = 0
    rtt_solde: float = 0
