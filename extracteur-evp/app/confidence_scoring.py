"""
extracteur-evp/app/confidence_scoring.py

Score de confiance par ligne EVP parsée (extracteur-evp/app/parsers/excel_parser.py).

Le score ne mesure pas la validité Pydantic (déjà garantie en amont par
EVPMensuel) mais la fiabilité de l'EXTRACTION : une ligne parfaitement
valide peut mériter un score réduit si une partie de l'information est
probablement restée en texte libre dans REMARQUES plutôt que dans les
colonnes structurées (ex: "Prime Astreintes : 450 €" observé sur des cas
réels) - c'est le signal qui doit déclencher, plus tard, un fallback LLM
pour extraire cette information (Phase D.5+).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_EXTRACTEUR_EVP_DIR = Path(__file__).resolve().parents[1]  # extracteur-evp/ (nom non importable : tiret)
_ROOT = _EXTRACTEUR_EVP_DIR.parent  # racine du dépôt
for _p in (_ROOT, _EXTRACTEUR_EVP_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.schemas import ContratTravail  # noqa: E402

from .parsers.excel_parser import ParsedEVPLigne  # noqa: E402

SCORE_MAX = 1.0
SCORE_MIN = 0.0
SCORE_BASE = 0.5  # ligne structurée valide, sans signal positif ni négatif

BONUS_MATRICULE_ET_NOM_PRENOM_COHERENTS = 0.10
PENALITE_REMARQUE_SUSPECTE = 0.25
PENALITE_INCOHERENCE_SALAIRE_CONTRAT = 0.30
PENALITE_PAR_AVERTISSEMENT = 0.05
TOLERANCE_ECART_SALAIRE = 1.0  # écart (€) toléré entre EVP.salaire_an et le contrat

# Signale qu'une REMARQUE contient probablement un montant ou une donnée
# chiffrée (prime, heures) non reportée dans les colonnes structurées.
# Vu sur des cas réels : "Prime Astreintes : 450 €", "Prime Durée de
# mission 1500 € Brut", "17 heures supplémentaires...".
MOTIF_REMARQUE_SUSPECTE = re.compile(
    r"(\d+[.,]?\d*\s?€)|(\bprime\b)|(\bheures?\b)", re.IGNORECASE
)


@dataclass
class ScoreConfiance:
    valeur: float
    raisons: list[str] = field(default_factory=list)


def score_ligne_evp(
    ligne: ParsedEVPLigne, contrat_reference: Optional[ContratTravail] = None
) -> ScoreConfiance:
    if ligne.evp is None:
        return ScoreConfiance(
            valeur=SCORE_MIN,
            raisons=[f"Ligne EVP invalide, non exploitable : {'; '.join(ligne.erreurs)}"],
        )

    score = SCORE_BASE
    raisons: list[str] = []

    if ligne.raw_matricule and (ligne.evp.nom or ligne.evp.prenom):
        score += BONUS_MATRICULE_ET_NOM_PRENOM_COHERENTS
        raisons.append(
            "Matricule EVP présent en complément du nom/prénom (identification renforcée)"
        )
    else:
        raisons.append(
            "Pas de matricule EVP exploitable : identification basée uniquement sur nom/prénom"
        )

    if ligne.evp.remarques and MOTIF_REMARQUE_SUSPECTE.search(ligne.evp.remarques):
        score -= PENALITE_REMARQUE_SUSPECTE
        raisons.append(
            "REMARQUES contient probablement un montant/une donnée non reportée dans les "
            f"colonnes structurées (candidat fallback LLM) : {ligne.evp.remarques!r}"
        )

    if contrat_reference is not None:
        ecart = abs(ligne.evp.salaire_an - contrat_reference.remuneration_annuelle_brute)
        if ecart > TOLERANCE_ECART_SALAIRE:
            score -= PENALITE_INCOHERENCE_SALAIRE_CONTRAT
            raisons.append(
                f"salaire_an EVP ({ligne.evp.salaire_an}) incohérent avec le contrat de "
                f"référence ({contrat_reference.remuneration_annuelle_brute}), écart={ecart}"
            )
        else:
            raisons.append("salaire_an cohérent avec le contrat de référence")

    for avertissement in ligne.avertissements:
        score -= PENALITE_PAR_AVERTISSEMENT
        raisons.append(f"Avertissement parsing : {avertissement}")

    score = max(SCORE_MIN, min(SCORE_MAX, score))
    return ScoreConfiance(valeur=round(score, 2), raisons=raisons)
