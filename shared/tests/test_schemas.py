"""
Tests des schémas Pydantic basés sur les données RÉELLES des documents
Soft IT (contrats, EVP, bulletins de Didier et Sindhuja - mai/juin 2026).

Objectif : valider que les schémas D.0 acceptent des données réelles sans
erreur, et que les validations de cohérence détectent bien les incohérences.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from shared.schemas import (
    AbsencePeriode,
    BulletinSalaire,
    ContratTravail,
    DossierSalarie,
    EVPMensuel,
    LigneCotisation,
    StatutSalarie,
    TypeAbsence,
    TypeContrat,
)


# ---------------------------------------------------------------------------
# Fixtures basées sur le contrat réel de Didier
# ---------------------------------------------------------------------------

def contrat_didier() -> ContratTravail:
    return ContratTravail(
        prenom="Didier",
        nationalite="Française",
        poste="Ingénieur Système Windows",
        date_effet=date(2025, 7, 1),
        type_contrat="CDI",
        convention_collective="SYNTEC",
        statut=StatutSalarie.CADRE,
        position="2.2",
        coefficient=130,
        remuneration_annuelle_brute=53000,
        remuneration_mensuelle_brute=4417,
        heures_mensuelles=151.67,
        periode_essai_mois=None,
        rtt_par_an=10,
        periode_reference_conges="01/06 au 31/05",
        clause_non_concurrence=True,
        duree_non_concurrence_mois=12,
        indemnite_non_concurrence_mois_salaire=6,
        clause_formation=False,
        lieu_travail="au sein de la société ou en télétravail",
        delai_justification_absence_heures=24,
        organisme_justification_absence="H Cube",
        date_signature=date(2025, 6, 30),
        lieu_signature="Paris",
    )


def contrat_sindhuja() -> ContratTravail:
    return ContratTravail(
        prenom="Sindhuja",
        nationalite="Indienne",
        poste="Consultante GRC",
        date_effet=date(2025, 11, 3),
        type_contrat="CDI",
        convention_collective="SYNTEC",
        statut=StatutSalarie.CADRE,
        position="3.2",
        coefficient=210,
        remuneration_annuelle_brute=70000,
        remuneration_mensuelle_brute=5833,
        heures_mensuelles=151.67,
        periode_essai_mois=4,
        periode_essai_renouvelable=True,
        rtt_par_an=10,
        periode_reference_conges="01/06 au 31/05",
        clause_non_concurrence=True,
        duree_non_concurrence_mois=12,
        indemnite_non_concurrence_mois_salaire=6,
        clause_formation=True,
        duree_engagement_formation_mois=12,
        lieu_travail="au sein de la société ou en télétravail",
        delai_justification_absence_heures=24,
        organisme_justification_absence="H Cube",
        date_signature=date(2025, 10, 23),
        lieu_signature="Paris",
    )


def test_contrat_didier_valide():
    contrat = contrat_didier()
    assert contrat.coefficient == 130
    assert contrat.periode_essai_mois is None


def test_contrat_sindhuja_valide():
    contrat = contrat_sindhuja()
    assert contrat.clause_formation is True
    assert contrat.periode_essai_mois == 4


def test_incoherence_remuneration_detectee():
    """Le mensuel doit correspondre à annuel/12 (tolérance 1€ d'arrondi)."""
    with pytest.raises(ValidationError):
        ContratTravail(
            prenom="Test",
            poste="Testeur",
            date_effet=date(2026, 1, 1),
            type_contrat="CDI",
            convention_collective="SYNTEC",
            statut=StatutSalarie.CADRE,
            position="1.1",
            coefficient=100,
            remuneration_annuelle_brute=53000,
            remuneration_mensuelle_brute=3000,  # incohérent volontairement
            rtt_par_an=10,
            periode_reference_conges="01/06 au 31/05",
            lieu_travail="site",
            date_signature=date(2026, 1, 1),
        )


def test_clause_non_concurrence_sans_duree_rejetee():
    with pytest.raises(ValidationError):
        ContratTravail(
            prenom="Test",
            poste="Testeur",
            date_effet=date(2026, 1, 1),
            type_contrat="CDI",
            convention_collective="SYNTEC",
            statut=StatutSalarie.CADRE,
            position="1.1",
            coefficient=100,
            remuneration_annuelle_brute=36000,
            remuneration_mensuelle_brute=3000,
            rtt_par_an=10,
            periode_reference_conges="01/06 au 31/05",
            lieu_travail="site",
            date_signature=date(2026, 1, 1),
            clause_non_concurrence=True,  # sans duree_non_concurrence_mois -> erreur
        )


# ---------------------------------------------------------------------------
# EVP réel (fichier Excel juin 2026)
# ---------------------------------------------------------------------------

def test_evp_didier_reel():
    evp = EVPMensuel(
        periode=date(2026, 6, 1),
        matricule=None,  # vide dans le fichier réel
        prenom="Didier",
        poste="Administrateur Système",
        type_contrat=TypeContrat.CDI,
        debut_contrat=date(2025, 7, 1),
        salaire_an=53000,
        mutuelle="Seul",
        nb_ticket_restaurant=16,
        pass_navigo=False,
        absences=[
            AbsencePeriode(type=TypeAbsence.RTT, nb_jours=2, dates_brutes="15 et 25/05")
        ],
    )
    assert evp.matricule is None
    assert evp.absences[0].nb_jours == 2


def test_evp_sans_identifiant_rejete():
    with pytest.raises(ValidationError):
        EVPMensuel(
            periode=date(2026, 6, 1),
            matricule=None,
            prenom="",  # aucun identifiant exploitable
            poste="Testeur",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2026, 1, 1),
            salaire_an=40000,
        )


def test_cdi_avec_date_fin_rejete():
    with pytest.raises(ValidationError):
        EVPMensuel(
            periode=date(2026, 6, 1),
            prenom="Test",
            poste="Testeur",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2026, 1, 1),
            fin_contrat=date(2026, 12, 31),  # incohérent pour un CDI
            salaire_an=40000,
        )


# ---------------------------------------------------------------------------
# Bulletin réel (Didier, mai 2026)
# ---------------------------------------------------------------------------

def bulletin_didier() -> BulletinSalaire:
    return BulletinSalaire(
        periode_debut=date(2026, 5, 1),
        periode_fin=date(2026, 5, 31),
        matricule="0004",
        date_entree=date(2025, 7, 1),
        date_premiere_entree=date(2023, 2, 1),  # reprise d'ancienneté
        emploi="Ingénieur Système Windows",
        qualification="Cadre Position 2.2 / Coeff - 130",
        convention_collective="Bureau d'études techniques, cabinets d'ingénieurs-conseils, sociétés de conseils",
        salaire_base_mensuel=4416.67,
        total_remuneration_brute=4469.42,
        total_cotisations_salariales=998.73,
        total_cotisations_patronales=1920.42,
        montant_net_social=3470.69,
        titres_restaurant=90.00,
        pass_navigo=None,  # absent chez Didier (EVP: PASS_NAVIGO=NON)
        jours_cp_acquis=2.12,
        jours_rtt_acquis=0.83,
        jours_rtt_pris=4.00,
        net_a_payer_avant_ir=3380.69,
        impot_revenu_base=3653.52,
        impot_revenu_taux=8.4,
        impot_revenu_montant=306.90,
        impot_revenu_cumul=1534.50,
        net_a_payer=3073.79,
        date_paiement=date(2026, 5, 31),
        mode_reglement="Virement",
        heures_payees_cumul=758.35,
        remuneration_brute_cumul=22347.10,
        cp_n1_acquis=25.00,
        cp_n1_pris=21.00,
        cp_n1_solde=4.00,
        cp_n_acquis=25.00,
        rtt_acquis=8.04,
        rtt_pris=6.00,
        rtt_solde=2.04,
    )


def test_bulletin_didier_reel():
    bulletin = bulletin_didier()
    assert bulletin.net_a_payer == 3073.79
    assert bulletin.pass_navigo is None
    # date_entree != date_premiere_entree -> reprise d'ancienneté, cas limite réel
    assert bulletin.date_entree != bulletin.date_premiere_entree


# ---------------------------------------------------------------------------
# Dossier salarié consolidé
# ---------------------------------------------------------------------------

def test_dossier_salarie_didier():
    dossier = DossierSalarie(
        matricule="0004",
        contrat=contrat_didier(),
        bulletins_historique=[bulletin_didier()],
    )
    assert dossier.dernier_bulletin().net_a_payer == 3073.79
    assert dossier.bulletin_precedent() is None  # un seul bulletin en historique
