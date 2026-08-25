"""
compliance-validation/app/rule_engine/rules/rg06_preavis.py

RG-06 - Durée minimale de préavis en cas de rupture du contrat.

Source : Article 4.2 de la CCN SYNTEC (IDCC 1486), texte intégral vérifié
dans docs/architecture/references/convention_collective_syntec.pdf
(avenant n°46 du 16 juillet 2021) :

  "Les durées suivantes s'appliquent en cas de licenciement ou de
  démission :
   - pour les ETAM : de moins de deux (2) ans d'ancienneté : un (1)
     mois, de plus de deux (2) ans d'ancienneté : deux (2) mois, classés
     aux coefficients hiérarchiques conventionnels 400, 450 et 500,
     quelle que soit leur ancienneté acquise : deux (2) mois ;
   - pour les ingénieurs et cadres : trois (3) mois."

Portée : l'Article 4.2 ne s'applique EXPLICITEMENT qu'en cas de
licenciement ou de démission. L'Article 4.1 précise par ailleurs qu'il
n'y a "pas de préavis" en cas de faute grave/lourde ou d'inaptitude non
professionnelle, et que la rupture conventionnelle suit son propre régime
("les conditions et l'indemnisation minimale prévues par les dispositions
légales et/ou conventionnelles", Art. 4.1) - hors du périmètre de
l'Article 4.2. Cette règle ne s'applique donc qu'aux ruptures de type
"demission" ou "licenciement" (cf. RuptureContrat.type_rupture) ; les
type_rupture "rupture_conventionnelle" et "fin_periode_essai" (régie par
le délai de prévenance de l'Article 3.4, pas par l'Article 4.2) sont
explicitement hors périmètre.
"""

from datetime import date

from shared.schemas import DossierSalarie, StatutSalarie

from .base import ResultatRegle

REGLE_ID = "RG-06"
SOURCE = "Article 4.2 de la CCN SYNTEC (IDCC 1486)"

TYPES_RUPTURE_COUVERTS = ("demission", "licenciement")

PREAVIS_CADRE_MOIS = 3
PREAVIS_ETAM_MOINS_2_ANS_MOIS = 1
PREAVIS_ETAM_2_ANS_OU_PLUS_MOIS = 2
# Coefficients ETAM couverts par la clause "quelle que soit leur
# ancienneté acquise : deux (2) mois" de l'Article 4.2.
COEFFICIENTS_ETAM_PREAVIS_FIXE = (400, 450, 500)
PREAVIS_ETAM_COEFFICIENT_ELEVE_MOIS = 2
SEUIL_ANCIENNETE_ETAM_MOIS = 24


def _mois_entre(debut: date, fin: date) -> int:
    """Nombre de mois calendaires complets entre `debut` et `fin` (fin >= debut).

    Un mois n'est compté que si le jour du mois de `fin` a atteint celui de
    `debut` (mois "complet") : cohérent avec la façon dont les dates de ce
    projet sont générées (cf. scripts/generate_fixtures.py::_decale_mois,
    toujours au 1er du mois).
    """
    mois = (fin.year - debut.year) * 12 + (fin.month - debut.month)
    if fin.day < debut.day:
        mois -= 1
    return mois


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    if dossier.rupture is None:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message="Règle non applicable : aucune rupture de contrat renseignée.",
            source=SOURCE,
        )

    contrat = dossier.contrat
    rupture = dossier.rupture

    if rupture.type_rupture not in TYPES_RUPTURE_COUVERTS:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message=(
                f"Règle non applicable : l'Article 4.2 ne couvre que le "
                f"licenciement et la démission, pas '{rupture.type_rupture}' "
                f"(régi par un régime distinct, cf. Article 4.1 / Article 3.4)."
            ),
            source=SOURCE,
        )

    anciennete_mois = _mois_entre(contrat.date_effet, rupture.date_notification)
    preavis_effectif_mois = _mois_entre(
        rupture.date_notification, rupture.date_fin_contrat_effective
    )

    if contrat.statut == StatutSalarie.CADRE:
        preavis_min_mois = PREAVIS_CADRE_MOIS
        detail_seuil = f"{preavis_min_mois} mois (ingénieurs et cadres)"
    elif contrat.statut == StatutSalarie.ETAM:
        if contrat.coefficient in COEFFICIENTS_ETAM_PREAVIS_FIXE:
            preavis_min_mois = PREAVIS_ETAM_COEFFICIENT_ELEVE_MOIS
            detail_seuil = (
                f"{preavis_min_mois} mois (ETAM coefficient {contrat.coefficient}, "
                f"quelle que soit l'ancienneté)"
            )
        else:
            preavis_min_mois = (
                PREAVIS_ETAM_2_ANS_OU_PLUS_MOIS
                if anciennete_mois >= SEUIL_ANCIENNETE_ETAM_MOIS
                else PREAVIS_ETAM_MOINS_2_ANS_MOIS
            )
            detail_seuil = (
                f"{preavis_min_mois} mois (ETAM, ancienneté {anciennete_mois} mois)"
            )
    else:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message=(
                f"Règle non applicable : préavis minimum non sourcé pour le "
                f"statut {contrat.statut} (TODO)."
            ),
            source=SOURCE,
        )

    conforme = preavis_effectif_mois >= preavis_min_mois
    if conforme:
        message = (
            f"Préavis de {preavis_effectif_mois} mois conforme au minimum requis : "
            f"{detail_seuil}."
        )
    else:
        message = (
            f"Préavis de {preavis_effectif_mois} mois inférieur au minimum requis : "
            f"{detail_seuil}."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
