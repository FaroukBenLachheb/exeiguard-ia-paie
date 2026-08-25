"""
compliance-validation/app/rule_engine/rules/rg01_heures_mensuelles.py

RG-01 - Cohérence heures hebdomadaires / heures mensuelles.

Source : Code du travail, art. L3121-27 (durée légale du travail effectif
= 35 heures par semaine pour un temps complet).

La conversion hebdomadaire -> mensuelle standard est heures_hebdo * 52 / 12
(52 semaines/an, 12 mois/an), soit 35 * 52 / 12 = 151.67h/mois arrondi.
C'est aussi la valeur par défaut de ContratTravail.heures_mensuelles
(shared/schemas/contrat.py).

Limite connue : ContratTravail ne porte pas de champ heures_hebdomadaires
explicite (seul heures_mensuelles existe) - cette règle compare donc
heures_mensuelles à la conversion mensuelle du temps plein légal (35h/
semaine), qui est la seule référence "heures hebdo" disponible sans
donnée supplémentaire. C'est exactement ce qui permet de détecter
l'anomalie réelle documentée sur cas_13/14/15 (Jordan, Julien, Karim,
tests/fixtures/) : le contrat affiche 139.00h/mois (mentionné en texte
"38h30 hebdomadaire" dans le document réel, non modélisé en tant que tel)
alors que le bulletin réel utilise 151,67h comme tous les autres salariés
- incohérence volontairement préservée telle quelle dans les fixtures
(cf. scripts/generate_fixtures.py et
docs/architecture/onboarding-technique.md).

Vérifié contre docs/architecture/references/convention_collective_syntec.pdf
(texte intégral, avenant n°46 du 16 juillet 2021) : aucun enrichissement
trouvé. Le texte de base ne donne aucune valeur horaire hebdomadaire
explicite (Art. 6.1/7.1 renvoient à un accord de branche distinct du 22
juin 1999 pour l'aménagement du temps de travail, sans figure chiffrée
dans ce document) - le sourcing reste donc Code du travail seul.
"""

from __future__ import annotations

from shared.schemas import DossierSalarie

from .base import ResultatRegle

REGLE_ID = "RG-01"
SOURCE = "Code du travail, art. L3121-27 (durée légale : 35h/semaine)"

HEURES_HEBDO_LEGALES = 35.0
HEURES_MENSUELLES_LEGALES = round(HEURES_HEBDO_LEGALES * 52 / 12, 2)  # 151.67
TOLERANCE_HEURES = 0.5


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat
    messages: list[str] = []
    conforme = True

    ecart_contrat = abs(contrat.heures_mensuelles - HEURES_MENSUELLES_LEGALES)
    if ecart_contrat > TOLERANCE_HEURES:
        conforme = False
        messages.append(
            f"Contrat : heures_mensuelles déclarées ({contrat.heures_mensuelles}h) "
            f"incohérentes avec la conversion légale de 35h/semaine "
            f"({HEURES_MENSUELLES_LEGALES}h/mois), écart de {ecart_contrat:.2f}h "
            f"> tolérance {TOLERANCE_HEURES}h."
        )
    else:
        messages.append(
            f"Contrat : heures_mensuelles ({contrat.heures_mensuelles}h) cohérentes "
            f"avec la conversion légale de 35h/semaine ({HEURES_MENSUELLES_LEGALES}h/mois)."
        )

    evp = dossier.dernier_evp()
    if evp is not None and evp.heure_mensuel is not None:
        ecart_evp = abs(evp.heure_mensuel - contrat.heures_mensuelles)
        if ecart_evp > TOLERANCE_HEURES:
            conforme = False
            messages.append(
                f"EVP : heures mensuelles utilisées ({evp.heure_mensuel}h) "
                f"incohérentes avec le contrat ({contrat.heures_mensuelles}h)."
            )
        else:
            messages.append(
                f"EVP : heures mensuelles utilisées ({evp.heure_mensuel}h) "
                f"cohérentes avec le contrat."
            )

    return ResultatRegle(
        regle_id=REGLE_ID,
        conforme=conforme,
        message=" ".join(messages),
        source=SOURCE,
    )
