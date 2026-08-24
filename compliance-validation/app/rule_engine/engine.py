"""
compliance-validation/app/rule_engine/engine.py

Point d'entrée du Rule Engine (Phase D.5) : exécute les 10 règles RG-01 à
RG-10 sur un DossierSalarie et retourne tous les résultats (conformes et
non conformes) - chaque règle est indépendante, aucune n'interrompt les
autres.
"""

from shared.schemas import DossierSalarie

from .rules import (
    rg01_heures_mensuelles,
    rg02_remuneration,
    rg03_classification,
    rg04_periode_essai,
    rg05_non_concurrence,
    rg06_preavis,
    rg07_conges_anciennete,
    rg08_rtt,
    rg09_justification_absence,
    rg10_coherence_contrat,
)
from .rules.base import ResultatRegle

_MODULES_REGLES = (
    rg01_heures_mensuelles,
    rg02_remuneration,
    rg03_classification,
    rg04_periode_essai,
    rg05_non_concurrence,
    rg06_preavis,
    rg07_conges_anciennete,
    rg08_rtt,
    rg09_justification_absence,
    rg10_coherence_contrat,
)


def evaluer_toutes_les_regles(dossier: DossierSalarie) -> list[ResultatRegle]:
    return [module.evaluer(dossier) for module in _MODULES_REGLES]
