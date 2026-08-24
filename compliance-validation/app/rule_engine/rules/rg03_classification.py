"""
compliance-validation/app/rule_engine/rules/rg03_classification.py

RG-03 - Cohérence position/coefficient (grille de classification SYNTEC).

Source : CCN SYNTEC (IDCC 1486), grille de classification - Ingénieurs et
Cadres (positions 1.1 à 3.3) et grille ETAM (positions 1.1/1.2 vérifiées),
telles que consolidées dans shared/reference_data/grilles_syntec.py.

Choix d'implémentation : les grilles sont importées depuis
shared/reference_data/grilles_syntec.py, pas depuis
scripts/generate_fixtures.py, et ne sont pas redupliquées ici. C'est le
module créé précisément pour cet usage ("refactor: déplace les grilles
SYNTEC de scripts/ vers shared/reference_data/") : scripts/ n'est jamais
copié dans les images Docker, alors que shared/ l'est systématiquement
(PYTHONPATH=/app/shared, cf. docs/architecture/dependances-partagees.md).
Dupliquer les grilles ici recréerait exactement le risque de divergence
que ce déplacement visait à éliminer (cf. bugs cas_06/cas_18 corrigés en
amont sur cette même donnée).
"""

from shared.reference_data.grilles_syntec import GRILLE_SYNTEC_CADRES, GRILLE_SYNTEC_ETAM
from shared.schemas import DossierSalarie, StatutSalarie

from .base import ResultatRegle

REGLE_ID = "RG-03"
SOURCE = "CCN SYNTEC (IDCC 1486), grille de classification"

_GRILLES_PAR_STATUT = {
    StatutSalarie.CADRE: GRILLE_SYNTEC_CADRES,
    StatutSalarie.ETAM: GRILLE_SYNTEC_ETAM,
}


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat
    grille = _GRILLES_PAR_STATUT.get(contrat.statut)

    if grille is None:
        # StatutSalarie.NON_CADRE (ou tout futur statut) n'a pas de grille
        # SYNTEC vérifiée à ce stade (seules GRILLE_SYNTEC_CADRES et
        # GRILLE_SYNTEC_ETAM existent). TODO : sourcer la grille
        # correspondante avant d'étendre cette règle à ce statut.
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message=(
                f"Règle non applicable : aucune grille SYNTEC sourcée pour le "
                f"statut {contrat.statut} (TODO)."
            ),
            source=SOURCE,
        )

    coefficient_attendu = grille.get(contrat.position)
    if coefficient_attendu is None:
        # Position absente de la grille vérifiée (cf. shared/reference_data/
        # grilles_syntec.py : GRILLE_SYNTEC_ETAM est volontairement limitée
        # aux entrées vérifiées via deux sources indépendantes).
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message=(
                f"Règle non applicable : position '{contrat.position}' absente de "
                f"la grille SYNTEC {contrat.statut} vérifiée (TODO : compléter la "
                f"grille si cette position est légitime)."
            ),
            source=SOURCE,
        )

    conforme = contrat.coefficient == coefficient_attendu
    if conforme:
        message = (
            f"Coefficient {contrat.coefficient} cohérent avec la position "
            f"{contrat.position} (statut {contrat.statut})."
        )
    else:
        message = (
            f"Coefficient {contrat.coefficient} incohérent avec la position "
            f"{contrat.position} (statut {contrat.statut}) : coefficient attendu "
            f"{coefficient_attendu} selon la grille SYNTEC."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
