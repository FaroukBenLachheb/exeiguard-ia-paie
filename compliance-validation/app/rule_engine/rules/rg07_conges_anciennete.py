"""
compliance-validation/app/rule_engine/rules/rg07_conges_anciennete.py

RG-07 - Congés d'ancienneté (règle informative).

Source : Article 5.1, point 2 de la CCN SYNTEC (IDCC 1486), texte
intégral vérifié dans
docs/architecture/references/convention_collective_syntec.pdf (avenant
n°46 du 16 juillet 2021) :

  "En fonction de l'ancienneté acquise à la date d'ouverture de la
  période de prise des congés payés applicable dans l'entreprise, soit
  le 1er mai à défaut de stipulation différente, il est accordé :
   - après une période de cinq (5) années d'ancienneté : un (1) jour
     ouvré supplémentaire ;
   - après une période de dix (10) années d'ancienneté : deux (2) jours
     ouvrés supplémentaires ;
   - après une période de quinze (15) années d'ancienneté : trois (3)
     jours ouvrés supplémentaires ;
   - après une période de vingt (20) années d'ancienneté : quatre (4)
     jours ouvrés supplémentaires."

Règle informative : elle calcule un droit, elle ne rejette jamais un
dossier (conforme=True systématique).

Limite connue : l'Article 5.1 calcule l'ancienneté "à la date d'ouverture
de la période de prise des congés payés applicable dans l'entreprise,
soit le 1er mai à défaut de stipulation différente". L'accord
d'entreprise Soft IT fixe une période différente
(periode_reference_conges="01/06 au 31/05", cf.
scripts/generate_fixtures.py::ACCORD_SOFT_IT), ce qui constitue
précisément une "stipulation différente" au sens de l'article. Cette
règle utilise la période du dernier EVP disponible (ou la date du jour à
défaut) comme date de référence, une approximation raisonnable qui ne
recalcule pas la date d'ouverture exacte de la période Soft IT
(periode_reference_conges est un champ texte libre, non structuré en
date, cf. shared/schemas/contrat.py) : à affiner si un calcul au jour
près est requis.
"""

from datetime import date

from shared.schemas import DossierSalarie

from .base import ResultatRegle

REGLE_ID = "RG-07"
SOURCE = "Article 5.1, point 2 de la CCN SYNTEC (IDCC 1486)"

# (annees_ancienneté, jours_ouvrés_dus), du plus élevé au plus bas.
PALIERS = (
    (20, 4),
    (15, 3),
    (10, 2),
    (5, 1),
)


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

    jours_dus = 0
    palier_atteint = None
    for annees, jours in PALIERS:
        if anciennete_annees >= annees:
            palier_atteint = annees
            jours_dus = jours
            break

    if palier_atteint is None:
        message = (
            f"Ancienneté de {anciennete_annees} an(s) ({anciennete_mois} mois) : "
            f"aucun palier de congés d'ancienneté atteint (premier palier à 5 ans, "
            f"Article 5.1 point 2 CCN SYNTEC). Jours de congés d'ancienneté dus : 0."
        )
    else:
        message = (
            f"Ancienneté de {anciennete_annees} an(s) ({anciennete_mois} mois) : "
            f"palier {palier_atteint} ans atteint (Article 5.1 point 2 CCN "
            f"SYNTEC). Jours de congés d'ancienneté dus : {jours_dus}."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=True, message=message, source=SOURCE)
