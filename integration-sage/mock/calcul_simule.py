"""
integration-sage/mock/calcul_simule.py

*** MOCK DE DEMONSTRATION — AUCUNE VALEUR REGLEMENTAIRE ***
Ce module ne calcule PAS un vrai bulletin de paie. Il produit un objet
BulletinSalaire structurellement valide (mêmes champs, mêmes contraintes
que le schéma partagé shared/schemas/bulletin.py) à partir d'une formule
FACTICE et volontairement grossière (net_a_payer = remuneration_mensuelle_
brute * 0.78, cotisations à taux plats arbitraires) : ces montants ne
reflètent aucune règle de cotisation SYNTEC/URSSAF réelle et ne doivent
jamais être présentés comme un bulletin de paie exploitable.

Objectif unique : permettre au pipeline A1->A6 d'avancer jusqu'à A6 en
démonstration, sans accès à l'API Sage réelle (cf. integration-sage/README.md
pour les points d'intégration réels prévus). Le calcul est déterministe
(mêmes entrées -> mêmes sorties), pas aléatoire, pour rester reproductible
en démo.
"""

from __future__ import annotations

import calendar
from datetime import date

from shared.schemas import BulletinSalaire, DossierSalarie, LigneCotisation

# Taux FACTICES, choisis uniquement pour produire un bulletin plausible en
# démo. Aucune source réglementaire : ne pas réutiliser ces valeurs pour un
# calcul de paie réel.
TAUX_NET_SUR_BRUT = 0.78
TAUX_COTISATIONS_SALARIALES = 0.22
TAUX_COTISATIONS_PATRONALES = 0.42


def calculer_bulletin_simule(dossier: DossierSalarie) -> BulletinSalaire:
    """Construit un BulletinSalaire factice mais déterministe à partir du
    contrat et du dernier EVP connus du dossier. Ne réalise aucun appel
    réseau, aucune I/O : pure fonction de calcul, cohérente avec le
    caractère "mock" de ce module."""
    contrat = dossier.contrat
    evp = dossier.dernier_evp()
    periode_debut = evp.periode if evp else date.today().replace(day=1)
    dernier_jour_du_mois = calendar.monthrange(periode_debut.year, periode_debut.month)[1]
    periode_fin = periode_debut.replace(day=dernier_jour_du_mois)

    brut = contrat.remuneration_mensuelle_brute
    cotisations_salariales = round(brut * TAUX_COTISATIONS_SALARIALES, 2)
    cotisations_patronales = round(brut * TAUX_COTISATIONS_PATRONALES, 2)
    net_avant_ir = round(brut * TAUX_NET_SUR_BRUT, 2)

    return BulletinSalaire(
        periode_debut=periode_debut,
        periode_fin=periode_fin,
        matricule=dossier.matricule,
        date_entree=contrat.date_effet,
        date_premiere_entree=contrat.date_effet,
        emploi=contrat.poste,
        qualification=f"{contrat.statut.value} Position {contrat.position} / Coeff {contrat.coefficient}",
        convention_collective=contrat.convention_collective,
        salaire_base_mensuel=brut,
        total_remuneration_brute=brut,
        cotisations=[
            LigneCotisation(
                libelle="Cotisations salariales (mock, taux plat factice)",
                base=brut,
                taux=TAUX_COTISATIONS_SALARIALES,
                montant_salarial=cotisations_salariales,
                montant_patronal=cotisations_patronales,
            ),
        ],
        total_cotisations_salariales=cotisations_salariales,
        total_cotisations_patronales=cotisations_patronales,
        montant_net_social=net_avant_ir,
        net_a_payer_avant_ir=net_avant_ir,
        impot_revenu_base=net_avant_ir,
        impot_revenu_taux=0.0,
        impot_revenu_montant=0.0,
        impot_revenu_cumul=0.0,
        net_a_payer=net_avant_ir,
        date_paiement=periode_fin,
        mode_reglement="Virement (mock)",
        heures_payees_cumul=contrat.heures_mensuelles,
        remuneration_brute_cumul=brut,
    )
