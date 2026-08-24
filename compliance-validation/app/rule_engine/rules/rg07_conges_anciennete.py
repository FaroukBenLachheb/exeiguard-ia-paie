"""
compliance-validation/app/rule_engine/rules/rg07_conges_anciennete.py

RG-07 - Congés d'ancienneté (règle informative).

Source : CCN SYNTEC (IDCC 1486), congés d'ancienneté par palier (5/10/15/
20 ans). Règle informative : elle calcule un droit, elle ne rejette
jamais un dossier (conforme=True systématique).

Limite connue (TODO) : le nombre exact de jours de congés dus à chaque
palier n'est pas sourcé avec certitude à ce stade (aucune valeur
numérique vérifiée trouvée dans la documentation du projet). Pour
respecter le principe de ne jamais inventer un chiffre non sourcé, cette
règle calcule UNIQUEMENT le palier atteint (5/10/15/20 ans), pas le
nombre de jours - à compléter dès que le barème exact (jours par palier)
sera vérifié auprès d'une source CCN SYNTEC fiable.
"""

from datetime import date

from shared.schemas import DossierSalarie

from .base import ResultatRegle

REGLE_ID = "RG-07"
SOURCE = "CCN SYNTEC (IDCC 1486), congés d'ancienneté (paliers 5/10/15/20 ans)"

PALIERS_ANNEES = (20, 15, 10, 5)


def _mois_entre(debut: date, fin: date) -> int:
    mois = (fin.year - debut.year) * 12 + (fin.month - debut.month)
    if fin.day < debut.day:
        mois -= 1
    return mois


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat
    evp = dossier.dernier_evp()
    date_reference = evp.periode if evp is not None else date.today()

    anciennete_mois = _mois_entre(contrat.date_effet, date_reference)
    anciennete_annees = anciennete_mois // 12

    palier_atteint = next((p for p in PALIERS_ANNEES if anciennete_annees >= p), None)

    if palier_atteint is None:
        message = (
            f"Ancienneté de {anciennete_annees} an(s) ({anciennete_mois} mois) : "
            f"aucun palier de congés d'ancienneté CCN SYNTEC atteint (premier "
            f"palier à 5 ans)."
        )
    else:
        message = (
            f"Ancienneté de {anciennete_annees} an(s) ({anciennete_mois} mois) : "
            f"palier {palier_atteint} ans atteint. Nombre de jours de congés "
            f"d'ancienneté dus : TODO (barème exact non sourcé, cf. docstring "
            f"de ce module)."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=True, message=message, source=SOURCE)
