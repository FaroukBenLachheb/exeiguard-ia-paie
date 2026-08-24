"""
compliance-validation/app/rule_engine/rules/rg10_coherence_contrat.py

RG-10 - Cohérence contrat / identification du dossier.

Source : Code du travail, art. L1221-2 (le CDI est la forme normale et
générale de la relation de travail ; il ne comporte pas de terme) +
gouvernance des données, dérivée des anomalies réelles observées en D.4
(cf. shared/schemas/evp.py sur le fallback matricule/nom/prénom).

(a) Un CDI ne doit jamais avoir d'EVP portant une date de fin de contrat.
    Déjà garanti par EVPMensuel.cdi_sans_date_fin (Pydantic) en amont :
    cette règle remonte l'information au niveau du Rule Engine pour
    traçabilité/explication humaine ; elle ne peut structurellement
    jamais être violée par un dossier déjà validé par Pydantic.

(b) L'identifiant utilisé pour rattacher l'EVP au dossier ne doit pas être
    le seul matricule sans corroboration nom/prénom, et le prénom EVP doit
    être cohérent avec le prénom du contrat. EVPMensuel.prenom étant un
    champ requis (non optionnel), la première moitié de ce contrôle est
    elle aussi garantie par construction ; le rapprochement EVP.prenom /
    contrat.prenom reste, lui, une vérification réellement effectuée ici.
"""

from shared.schemas import DossierSalarie

from .base import ResultatRegle

REGLE_ID = "RG-10"
SOURCE = "Code du travail, art. L1221-2 (CDI sans terme) + gouvernance des données"


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat
    evp = dossier.dernier_evp()

    if evp is None:
        return ResultatRegle(
            regle_id=REGLE_ID,
            conforme=True,
            message="Règle non applicable : aucun EVP disponible dans le dossier.",
            source=SOURCE,
        )

    problemes = []

    # (a) CDI sans date de fin (déjà garanti par EVPMensuel.cdi_sans_date_fin,
    # remonté ici pour traçabilité).
    if contrat.type_contrat == "CDI" and evp.fin_contrat is not None:
        problemes.append(f"CDI avec une date de fin d'EVP renseignée ({evp.fin_contrat})")

    # (b) identifiant EVP non corroboré (matricule seul, sans nom/prénom).
    if evp.matricule and not (evp.nom or evp.prenom):
        problemes.append("EVP identifié par le seul matricule, sans nom/prénom")

    # Cohérence du prénom EVP avec le contrat.
    if (
        evp.prenom
        and contrat.prenom
        and evp.prenom.strip().lower() != contrat.prenom.strip().lower()
    ):
        problemes.append(
            f"prénom EVP ('{evp.prenom}') incohérent avec le prénom contrat "
            f"('{contrat.prenom}')"
        )

    conforme = not problemes
    if conforme:
        message = (
            f"EVP rattaché de façon cohérente au dossier (prénom '{evp.prenom}' "
            f"corroboré par le contrat), aucune incohérence CDI/date de fin."
        )
    else:
        message = "Incohérence(s) détectée(s) : " + " ; ".join(problemes)

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
