"""
compliance-validation/app/rule_engine/rules/base.py

Modèle de résultat partagé par toutes les règles du Rule Engine (RG-01 à
RG-10). Chaque module rgXX_*.py expose une fonction
`evaluer(dossier: DossierSalarie) -> ResultatRegle` indépendante des
autres règles.
"""

from pydantic import BaseModel


class ResultatRegle(BaseModel):
    regle_id: str  # ex: "RG-01"
    conforme: bool
    message: str  # explication humaine du résultat (conforme ou non)
    source: str  # référence réglementaire précise (article, CCN, accord...)
