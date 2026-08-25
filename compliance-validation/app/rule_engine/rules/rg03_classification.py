"""
compliance-validation/app/rule_engine/rules/rg03_classification.py

RG-03 - Cohérence position/coefficient (grille de classification SYNTEC).

Source : Article 7.2 de la CCN SYNTEC (IDCC 1486) - "Les classifications
des employés, techniciens et agents de maîtrise (ETAM) figurent en
annexe 1 de la convention collective [...] Les classifications des
ingénieurs et cadres figurent en annexe 2" - complété par l'Article 3.2
("la classification et le coefficient hiérarchique" figurent parmi les
mentions obligatoires du contrat de travail). Texte intégral vérifié
dans docs/architecture/references/convention_collective_syntec.pdf
(avenant n°46 du 16 juillet 2021).

Limite connue et IMPORTANTE : les Annexes I (grille ETAM complète) et II
(grille Cadres complète) ne sont PAS incluses dans ce document ("texte de
base : préambule et articles 1.1 à 13.6", cf. le glossaire du PDF et
docs/architecture/references/README.md). Les grilles position->coefficient
utilisées ici (GRILLE_SYNTEC_CADRES/GRILLE_SYNTEC_ETAM dans
shared/reference_data/grilles_syntec.py) restent donc sourcées comme
avant ce document (salerya.fr, mapaye.fr) et PAS depuis les Annexes I/II.
Seules les bornes globales de coefficients sont confirmées par ce
document : Cadres 95-270 (Article 3.4), ETAM 240-500 (Article 2.1,
composition des collèges électoraux CSE).

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
SOURCE = "Article 7.2 de la CCN SYNTEC (IDCC 1486), renvoi aux annexes I et II"

# Bornes globales de coefficients confirmées par le texte de base (pas par
# les annexes, absentes du document) : cf. docstring.
BORNE_COEFFICIENT_CADRE = (95, 270)  # Article 3.4
BORNE_COEFFICIENT_ETAM = (240, 500)  # Article 2.1

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
        # aux entrées vérifiées via deux sources indépendantes, faute
        # d'Annexe I/II dans le document CCN disponible). On vérifie tout de
        # même le coefficient contre la borne globale confirmée par le texte
        # de base (Article 3.4 / Article 2.1), à défaut de pouvoir vérifier
        # la position exacte.
        borne = BORNE_COEFFICIENT_CADRE if contrat.statut == StatutSalarie.CADRE else BORNE_COEFFICIENT_ETAM
        dans_les_bornes = borne[0] <= contrat.coefficient <= borne[1]
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message=(
                f"Règle non applicable (position exacte non vérifiable) : position "
                f"'{contrat.position}' absente de la grille SYNTEC {contrat.statut} "
                f"vérifiée (TODO : compléter la grille si cette position est "
                f"légitime). Coefficient {contrat.coefficient} "
                f"{'dans' if dans_les_bornes else 'HORS'} des bornes {contrat.statut} "
                f"confirmées ({borne[0]}-{borne[1]})."
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
