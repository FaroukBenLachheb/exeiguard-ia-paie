"""
compliance-validation/app/rule_engine/rules/rg04_periode_essai.py

RG-04 - Durée de la période d'essai (cadres).

Source : CCN SYNTEC (IDCC 1486) + Code du travail, art. L1221-19 (durée
maximale de la période d'essai initiale pour un cadre : 4 mois). Les deux
plafonds convergent à 4 mois pour un cadre ; l'art. L1221-21 impose
d'appliquer au salarié la durée la plus courte (la plus favorable) en cas
de divergence entre accord de branche et Code du travail, donc le plafond
effectif retenu ici reste 4 mois quoi qu'il arrive.

Limite connue : seul le plafond cadre (4 mois) est sourcé avec certitude
à ce stade. Le plafond ETAM/agent de maîtrise (Code du travail : 3 mois
en droit commun) n'a pas été confronté à la CCN SYNTEC spécifique -> TODO
avant d'étendre cette règle aux statuts ETAM/NON_CADRE.
"""

from shared.schemas import DossierSalarie, StatutSalarie

from .base import ResultatRegle

REGLE_ID = "RG-04"
SOURCE = "CCN SYNTEC (IDCC 1486) + Code du travail, art. L1221-19 (cadres : 4 mois max)"

PERIODE_ESSAI_MAX_CADRE_MOIS = 4


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat

    if contrat.periode_essai_mois is None:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message="Règle non applicable : aucune période d'essai renseignée.",
            source=SOURCE,
        )

    if contrat.statut != StatutSalarie.CADRE:
        # cf. docstring : seuil ETAM/NON_CADRE non sourcé à ce stade.
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message=(
                f"Règle non applicable : seuil de période d'essai non sourcé pour "
                f"le statut {contrat.statut} (TODO)."
            ),
            source=SOURCE,
        )

    conforme = contrat.periode_essai_mois <= PERIODE_ESSAI_MAX_CADRE_MOIS
    if conforme:
        message = (
            f"Période d'essai de {contrat.periode_essai_mois} mois conforme au "
            f"maximum cadre de {PERIODE_ESSAI_MAX_CADRE_MOIS} mois."
        )
    else:
        message = (
            f"Période d'essai de {contrat.periode_essai_mois} mois supérieure au "
            f"maximum cadre de {PERIODE_ESSAI_MAX_CADRE_MOIS} mois (CCN SYNTEC + "
            f"Code du travail)."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
