"""
compliance-validation/app/rule_engine/rules/rg09_justification_absence.py

RG-09 - Délai et organisme de justification d'absence.

Deux sources distinctes, cumulatives :
- Article 9.1 de la CCN SYNTEC (IDCC 1486), texte intégral vérifié dans
  docs/architecture/references/convention_collective_syntec.pdf (avenant
  n°46 du 16 juillet 2021) : "Dès que possible, et au plus tard dans les
  24 heures, le salarié doit avertir son employeur du motif et de la
  durée probable de son absence." Cette base légale conventionnelle ne
  couvre EXPLICITEMENT que l'absence pour maladie ou accident (Titre 9
  "Maladie, accidents, parentalité").
- Accord d'entreprise Soft IT (cf. scripts/generate_fixtures.py::
  ACCORD_SOFT_IT, delai_justification_absence_heures=24,
  organisme_justification_absence="H Cube") : étend ce même délai de 24h
  à TOUTE absence (pas seulement maladie/accident), et ajoute l'obligation
  de passer par l'organisme H Cube - ces deux extensions n'ont pas de
  fondement dans la CCN elle-même.

ContratTravail.delai_justification_absence_heures et
organisme_justification_absence ne distinguent pas le type d'absence :
cette règle vérifie donc la valeur unique déclarée contre le délai commun
aux deux sources (24h), sans pouvoir isoler la portion strictement
"maladie/accident" (Art. 9.1) de l'extension Soft IT.
"""

from shared.schemas import DossierSalarie

from .base import ResultatRegle

REGLE_ID = "RG-09"
SOURCE = "Article 9.1 CCN SYNTEC (maladie/accident) + accord d'entreprise Soft IT (extension à toute absence)"

DELAI_JUSTIFICATION_HEURES = 24


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat
    problemes = []

    if contrat.delai_justification_absence_heures != DELAI_JUSTIFICATION_HEURES:
        problemes.append(
            f"délai {contrat.delai_justification_absence_heures}h != "
            f"{DELAI_JUSTIFICATION_HEURES}h attendu (Article 9.1 CCN SYNTEC pour "
            f"maladie/accident, étendu à toute absence par l'accord Soft IT)"
        )
    if not contrat.organisme_justification_absence:
        problemes.append(
            "organisme_justification_absence non renseigné (exigence accord Soft IT, "
            "sans fondement dans la CCN SYNTEC elle-même)"
        )

    conforme = not problemes
    if conforme:
        message = (
            f"Délai de justification ({contrat.delai_justification_absence_heures}h, "
            f"Article 9.1 CCN SYNTEC pour maladie/accident, étendu par l'accord Soft "
            f"IT à toute absence) et organisme ({contrat.organisme_justification_absence}, "
            f"accord Soft IT) conformes."
        )
    else:
        message = "Non-conformité(s) : " + " ; ".join(problemes)

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
