"""
compliance-validation/app/rule_engine/rules/rg04_periode_essai.py

RG-04 - Durée de la période d'essai.

Source : Article 3.4 de la CCN SYNTEC (IDCC 1486), texte intégral vérifié
dans docs/architecture/references/convention_collective_syntec.pdf
(avenant n°46 du 16 juillet 2021) :

  "La durée de la période d'essai et de son renouvellement est la
  suivante :
   - du coefficient 240 au coefficient 250 inclus de la grille de
     classification des emplois ETAM, la période d'essai est de deux (2)
     mois maximum. Elle peut être renouvelée pour une durée de deux (2)
     mois maximum ;
   - du coefficient 275 au coefficient 500 inclus de la grille de
     classification des emplois ETAM, la période d'essai est de trois
     (3) mois maximum. Elle peut être renouvelée pour une durée de trois
     (3) mois maximum ;
   - du coefficient 95 au coefficient 270 de la grille de classification
     des emplois ingénieurs et cadres, la période d'essai est de quatre
     (4) mois. Elle peut être renouvelée pour une durée de quatre (4)
     mois maximum."

Les trois bornes sont donc distinguées par COEFFICIENT (pas par
`position`), avec un statut (ETAM/CADRE) pour lever toute ambiguïté sur
la grille applicable, car les bornes ETAM (240-250 et 275-500) et cadre
(95-270) se chevauchent numériquement dans l'absolu (ex: un coefficient
250 ne peut exister que côté ETAM, mais le nombre 250 seul ne le dit pas).

Limite connue : ContratTravail.periode_essai_mois ne modélise que la
durée totale déclarée (pas une durée initiale et une durée de
renouvellement séparées) ; cette règle vérifie donc periode_essai_mois
contre le plafond de l'Article 3.4, sans vérifier séparément la durée du
renouvellement (non modélisée).
"""

from shared.schemas import DossierSalarie, StatutSalarie

from .base import ResultatRegle

REGLE_ID = "RG-04"
SOURCE = "Article 3.4 de la CCN SYNTEC (IDCC 1486)"

# (coefficient_min, coefficient_max, periode_essai_max_mois)
_BORNES_ETAM = (
    (240, 250, 2),
    (275, 500, 3),
)
_BORNES_CADRE = (
    (95, 270, 4),
)


def _seuil_mois(statut: StatutSalarie, coefficient: int) -> int | None:
    bornes = _BORNES_ETAM if statut == StatutSalarie.ETAM else (
        _BORNES_CADRE if statut == StatutSalarie.CADRE else ()
    )
    for coef_min, coef_max, seuil in bornes:
        if coef_min <= coefficient <= coef_max:
            return seuil
    return None


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat

    if contrat.periode_essai_mois is None:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message="Règle non applicable : aucune période d'essai renseignée.",
            source=SOURCE,
        )

    seuil = _seuil_mois(contrat.statut, contrat.coefficient)
    if seuil is None:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message=(
                f"Règle non applicable : coefficient {contrat.coefficient} (statut "
                f"{contrat.statut}) hors des bornes de l'Article 3.4 de la CCN "
                f"SYNTEC (ETAM 240-250 ou 275-500, Cadres 95-270)."
            ),
            source=SOURCE,
        )

    conforme = contrat.periode_essai_mois <= seuil
    if conforme:
        message = (
            f"Période d'essai de {contrat.periode_essai_mois} mois conforme au "
            f"maximum de {seuil} mois pour le coefficient {contrat.coefficient} "
            f"(statut {contrat.statut}), Article 3.4 de la CCN SYNTEC (IDCC 1486)."
        )
    else:
        message = (
            f"Période d'essai de {contrat.periode_essai_mois} mois supérieure au "
            f"maximum de {seuil} mois pour le coefficient {contrat.coefficient} "
            f"(statut {contrat.statut}), Article 3.4 de la CCN SYNTEC (IDCC 1486)."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
