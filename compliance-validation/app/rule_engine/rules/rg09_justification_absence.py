"""
compliance-validation/app/rule_engine/rules/rg09_justification_absence.py

RG-09 - Délai et organisme de justification d'absence (accord Soft IT).

Source : accord d'entreprise Soft IT (cf.
scripts/generate_fixtures.py::ACCORD_SOFT_IT,
delai_justification_absence_heures=24,
organisme_justification_absence="H Cube").
"""

from shared.schemas import DossierSalarie

from .base import ResultatRegle

REGLE_ID = "RG-09"
SOURCE = "Accord d'entreprise Soft IT"

DELAI_JUSTIFICATION_HEURES_SOFT_IT = 24


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat
    problemes = []

    if contrat.delai_justification_absence_heures != DELAI_JUSTIFICATION_HEURES_SOFT_IT:
        problemes.append(
            f"délai {contrat.delai_justification_absence_heures}h != "
            f"{DELAI_JUSTIFICATION_HEURES_SOFT_IT}h attendu"
        )
    if not contrat.organisme_justification_absence:
        problemes.append("organisme_justification_absence non renseigné")

    conforme = not problemes
    if conforme:
        message = (
            f"Délai de justification ({contrat.delai_justification_absence_heures}h) "
            f"et organisme ({contrat.organisme_justification_absence}) conformes à "
            f"l'accord Soft IT."
        )
    else:
        message = "Non-conformité(s) accord Soft IT : " + " ; ".join(problemes)

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
