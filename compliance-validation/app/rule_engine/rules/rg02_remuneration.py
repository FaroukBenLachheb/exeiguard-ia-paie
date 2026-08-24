"""
compliance-validation/app/rule_engine/rules/rg02_remuneration.py

RG-02 - Cohérence rémunération mensuelle / annuelle.

Source : principe de mensualisation (Code du travail, art. L3242-1) - la
rémunération mensuelle doit être stable et correspondre à 1/12e de la
rémunération annuelle brute.

Réutilise TOLERANCE_REMUNERATION_MENSUELLE_EUR défini dans
shared/schemas/contrat.py (ContratTravail.coherence_remuneration_mensuelle)
au lieu de dupliquer une valeur différente : ce Rule Engine doit détecter
la même classe d'incohérence que la validation Pydantic amont, avec la
même marge (2€, justifiée par le cas réel Karim/cas_15 : écart de 1.33€
dû à un arrondi mensuel Soft IT supérieur à l'ancienne tolérance de 1€).

Conséquence : comme cette tolérance est déjà appliquée par Pydantic à
l'ingestion (ContratTravail refuse tout contrat qui la dépasse), aucun
dossier chargé depuis tests/fixtures/ ne peut jamais être non-conforme à
cette règle - cf. l'analyse de couverture dans
compliance-validation/tests/test_rule_engine.py.
"""

from shared.schemas import DossierSalarie
from shared.schemas.contrat import TOLERANCE_REMUNERATION_MENSUELLE_EUR

from .base import ResultatRegle

REGLE_ID = "RG-02"
SOURCE = "Principe de mensualisation (Code du travail, art. L3242-1)"


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat
    attendu = round(contrat.remuneration_annuelle_brute / 12, 2)
    ecart = abs(attendu - contrat.remuneration_mensuelle_brute)
    conforme = ecart <= TOLERANCE_REMUNERATION_MENSUELLE_EUR

    if conforme:
        message = (
            f"Rémunération mensuelle ({contrat.remuneration_mensuelle_brute}€) "
            f"cohérente avec annuel/12 ({attendu}€), écart {ecart:.2f}€."
        )
    else:
        message = (
            f"Rémunération mensuelle ({contrat.remuneration_mensuelle_brute}€) "
            f"incohérente avec annuel/12 ({attendu}€), écart {ecart:.2f}€ "
            f"> tolérance {TOLERANCE_REMUNERATION_MENSUELLE_EUR}€."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
