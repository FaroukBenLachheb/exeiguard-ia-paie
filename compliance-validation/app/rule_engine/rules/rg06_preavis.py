"""
compliance-validation/app/rule_engine/rules/rg06_preavis.py

RG-06 - Durée minimale de préavis en cas de rupture du contrat.

Source : CCN SYNTEC (IDCC 1486), dispositions relatives au délai-congé
(préavis) : ETAM = 1 mois si ancienneté < 2 ans, 2 mois si ancienneté >=
2 ans ; Cadres = 3 mois (indépendamment de l'ancienneté, à ce stade de
sourcing).

Ne s'applique qu'aux dossiers avec une rupture de contrat renseignée
(dossier.rupture non None) - cf. shared/schemas/rupture.py.
"""

from datetime import date

from shared.schemas import DossierSalarie, StatutSalarie

from .base import ResultatRegle

REGLE_ID = "RG-06"
SOURCE = "CCN SYNTEC (IDCC 1486), délai-congé (préavis)"

PREAVIS_CADRE_MOIS = 3
PREAVIS_ETAM_MOINS_2_ANS_MOIS = 1
PREAVIS_ETAM_2_ANS_OU_PLUS_MOIS = 2
SEUIL_ANCIENNETE_ETAM_MOIS = 24


def _mois_entre(debut: date, fin: date) -> int:
    """Nombre de mois calendaires complets entre `debut` et `fin` (fin >= debut).

    Un mois n'est compté que si le jour du mois de `fin` a atteint celui de
    `debut` (mois "complet") : cohérent avec la façon dont les dates de ce
    projet sont générées (cf. scripts/generate_fixtures.py::_decale_mois,
    toujours au 1er du mois).
    """
    mois = (fin.year - debut.year) * 12 + (fin.month - debut.month)
    if fin.day < debut.day:
        mois -= 1
    return mois


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    if dossier.rupture is None:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message="Règle non applicable : aucune rupture de contrat renseignée.",
            source=SOURCE,
        )

    contrat = dossier.contrat
    rupture = dossier.rupture

    anciennete_mois = _mois_entre(contrat.date_effet, rupture.date_notification)
    preavis_effectif_mois = _mois_entre(
        rupture.date_notification, rupture.date_fin_contrat_effective
    )

    if contrat.statut == StatutSalarie.CADRE:
        preavis_min_mois = PREAVIS_CADRE_MOIS
    elif contrat.statut == StatutSalarie.ETAM:
        preavis_min_mois = (
            PREAVIS_ETAM_2_ANS_OU_PLUS_MOIS
            if anciennete_mois >= SEUIL_ANCIENNETE_ETAM_MOIS
            else PREAVIS_ETAM_MOINS_2_ANS_MOIS
        )
    else:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message=(
                f"Règle non applicable : préavis minimum non sourcé pour le "
                f"statut {contrat.statut} (TODO)."
            ),
            source=SOURCE,
        )

    conforme = preavis_effectif_mois >= preavis_min_mois
    if conforme:
        message = (
            f"Préavis de {preavis_effectif_mois} mois conforme au minimum requis "
            f"({preavis_min_mois} mois, statut {contrat.statut}, ancienneté "
            f"{anciennete_mois} mois)."
        )
    else:
        message = (
            f"Préavis de {preavis_effectif_mois} mois inférieur au minimum requis "
            f"({preavis_min_mois} mois, statut {contrat.statut}, ancienneté "
            f"{anciennete_mois} mois) selon la CCN SYNTEC."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
