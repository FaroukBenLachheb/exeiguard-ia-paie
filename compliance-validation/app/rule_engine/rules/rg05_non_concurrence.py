"""
compliance-validation/app/rule_engine/rules/rg05_non_concurrence.py

RG-05 - Contrepartie financière de la clause de non-concurrence.

Source : droit du travail général - jurisprudence constante de la Cour de
cassation (Cass. soc., 10 juillet 2002, n°00-45.135, et jurisprudence
constante depuis) : une clause de non-concurrence est nulle si elle ne
comporte pas de contrepartie financière. + accord d'entreprise Soft IT
(indemnite_non_concurrence_mois_salaire = 6 mois de salaire,
duree_non_concurrence_mois = 12 mois, cf.
scripts/generate_fixtures.py::ACCORD_SOFT_IT).

Deux niveaux de vérification :
- rejet (non-conforme) si clause_non_concurrence=True sans contrepartie
  financière renseignée (risque de nullité de la clause) ;
- alerte informative (n'affecte pas `conforme`) si une contrepartie est
  bien présente mais diverge des valeurs Soft IT habituelles (6 mois
  d'indemnité / 12 mois de durée) : un écart n'est pas en soi une
  non-conformité légale, seul l'accord d'entreprise fixe ces valeurs de
  référence et une clause peut légitimement s'en écarter au cas par cas.
"""

from shared.schemas import DossierSalarie

from .base import ResultatRegle

REGLE_ID = "RG-05"
SOURCE = (
    "Jurisprudence Cass. soc. (contrepartie financière obligatoire) "
    "+ accord d'entreprise Soft IT"
)

INDEMNITE_SOFT_IT_MOIS = 6
DUREE_SOFT_IT_MOIS = 12


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat

    if not contrat.clause_non_concurrence:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message="Règle non applicable : pas de clause de non-concurrence.",
            source=SOURCE,
        )

    if not contrat.indemnite_non_concurrence_mois_salaire:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=False,
            message=(
                "Clause de non-concurrence sans contrepartie financière "
                "renseignée (indemnite_non_concurrence_mois_salaire absent ou "
                "nul) : risque de nullité de la clause."
            ),
            source=SOURCE,
        )

    alertes = []
    if contrat.indemnite_non_concurrence_mois_salaire != INDEMNITE_SOFT_IT_MOIS:
        alertes.append(
            f"indemnité {contrat.indemnite_non_concurrence_mois_salaire} mois "
            f"!= référence Soft IT {INDEMNITE_SOFT_IT_MOIS} mois"
        )
    if contrat.duree_non_concurrence_mois != DUREE_SOFT_IT_MOIS:
        alertes.append(
            f"durée {contrat.duree_non_concurrence_mois} mois != référence "
            f"Soft IT {DUREE_SOFT_IT_MOIS} mois"
        )

    if alertes:
        message = (
            "Contrepartie financière présente, mais écart avec les valeurs "
            "habituelles Soft IT (alerte, pas un rejet) : " + " ; ".join(alertes)
        )
    else:
        message = (
            f"Contrepartie financière présente "
            f"({contrat.indemnite_non_concurrence_mois_salaire} mois de salaire), "
            f"conforme aux valeurs Soft IT."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=True, message=message, source=SOURCE)
