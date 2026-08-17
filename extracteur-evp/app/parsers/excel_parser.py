"""
extracteur-evp/app/parsers/excel_parser.py

Parse un fichier EVP mensuel au format observé sur les fichiers réels
Soft IT (data-confidentielles/EXEIGUARD-DATA-TEST/*.xlsx, non versionnés,
cf. .gitignore) et retourne une liste de `ParsedEVPLigne` (un par salarié).

Structure de fichier observée (feuille unique) :
  ligne 1 : titre ("VARIABLES SOFT IT")
  ligne 2 : "DATE" en colonne A, date de la période en colonne B
  ligne 3 : en-têtes groupées des blocs d'absence (fusionnées sur 2 colonnes,
            libellé porté par la cellule NB DE JOUR du bloc) - lue
            dynamiquement pour localiser chaque bloc (cf. _detecter_colonnes_absence),
            AUCUN index de colonne fixe n'est utilisé pour cette identification
  ligne 4 : en-têtes de colonnes (cf. constantes COL_*)
  ligne 5 : vide
  lignes 6+ : une ligne par salarié, jusqu'à la première ligne sans nom/prénom

Anomalies réelles gérées explicitement (cf. shared/schemas/evp.py) :
  - MATRICULE EVP non fiable : c'est un simple numéro de ligne (1, 2, 3...),
    jamais le matricule Sage réel. Il n'est donc JAMAIS utilisé pour
    identifier une ligne ni transmis à EVPMensuel.matricule ; il est
    seulement conservé à part (`ParsedEVPLigne.raw_matricule`) pour audit.
    L'identification repose uniquement sur (nom, prénom).
  - Colonnes DATES (une par bloc d'absence) : tantôt du texte libre
    ("22, 25 et 26/05"), tantôt un datetime Excel natif -> les deux sont
    normalisés vers la même représentation "JJ/MM/AAAA" avant validation
    Pydantic (AbsencePeriode.dates_brutes est typé `str`).
  - Colonnes numériques (ex: NB TICKET RESTAURANT) : une cellule vide (non
    renseignée) et une valeur 0 (valeur réelle) sont distinguées via
    `ParsedEVPLigne.nb_ticket_restaurant_renseigne`, car EVPMensuel modélise
    ce champ en `int` simple (non `Optional`) et ne peut donc pas porter
    cette distinction lui-même.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import openpyxl
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.schemas import AbsencePeriode, EVPMensuel, TypeAbsence, TypeContrat  # noqa: E402

# --- Position des colonnes (0-based), ligne d'en-tête = ligne 4 ------------
COL_MATRICULE = 0
COL_NOM = 1
COL_PRENOM = 2
COL_POSTE = 3
COL_TYPE_CONTRAT = 4
COL_DEBUT_CONTRAT = 5
COL_FIN_CONTRAT = 6
COL_HEURE_MENSUEL = 7
COL_SALAIRE_AN = 8
COL_MUTUELLE = 9
COL_NB_TICKET_RESTAURANT = 10
COL_PASS_NAVIGO = 11
COL_PRIME = 12
COL_ACOMPTE = 13
COL_HEURES_SUP = 14
COL_REMARQUES = 27

# Chaque bloc d'absence occupe 2 colonnes consécutives (NB DE JOUR, DATES),
# identifiées par le libellé de la ligne d'en-tête groupée (ligne 3), JAMAIS
# par un index de colonne fixe : l'ordre des blocs, leur position (une
# colonne peut être insérée avant) ou même leur présence peuvent varier
# d'un fichier à l'autre (cf. _detecter_colonnes_absence).
#
# Les motifs ci-dessous sont volontairement tolérants sur l'orthographe :
# le fichier réel porte la faute de frappe "ABSCENCES" (au lieu de
# "ABSENCES") sur 4 des 5 blocs - faute assumée telle quelle dans la
# source, jamais "corrigée" avant comparaison. Le matching se fait sur un
# libellé normalisé (accents retirés, casse ignorée, espaces compactés) et
# cherche un sous-motif discriminant, insensible à ce genre de coquille
# puisqu'il ne porte pas sur "ABS(C)ENCES" mais sur la partie spécifique
# du libellé (ex: "RTT", "MALADIE"...).
MOTIFS_LABEL_ABSENCE: dict[TypeAbsence, str] = {
    TypeAbsence.CP: "CONGES PAYES",
    TypeAbsence.RTT: "RTT",
    TypeAbsence.MALADIE: "MALADIE",
    TypeAbsence.CONGE_SANS_SOLDE: "SANS SOLDE",
    TypeAbsence.INJUSTIFIEE: "INJUSTIFI",
}

GROUP_HEADER_ROW = 3
HEADER_ROW = 4
DATA_START_ROW = 6


@dataclass
class ParsedEVPLigne:
    """Résultat du parsing d'une ligne EVP (un salarié, un mois)."""

    ligne_excel: int
    evp: Optional[EVPMensuel]
    raw_matricule: Optional[str]
    nb_ticket_restaurant_renseigne: bool
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)


def parse_evp_file(path: str | Path) -> list[ParsedEVPLigne]:
    """Parse un fichier EVP .xlsx et retourne une ligne par salarié trouvé."""
    wb = openpyxl.load_workbook(Path(path), data_only=True)
    ws = wb.active

    periode = _periode_depuis_entete(ws)
    colonnes_absence = _detecter_colonnes_absence(ws)

    resultats: list[ParsedEVPLigne] = []
    for row_idx, row in enumerate(
        ws.iter_rows(min_row=DATA_START_ROW, values_only=True), start=DATA_START_ROW
    ):
        prenom = row[COL_PRENOM] if COL_PRENOM < len(row) else None
        nom = row[COL_NOM] if COL_NOM < len(row) else None
        if not prenom and not nom:
            continue  # ligne vide : fin du tableau
        resultats.append(_parse_ligne(row_idx, row, periode, colonnes_absence))

    return resultats


def _detecter_colonnes_absence(ws) -> dict[TypeAbsence, tuple[int, int]]:
    """Localise dynamiquement, pour ce classeur, les colonnes (NB DE JOUR,
    DATES) de chaque bloc d'absence en lisant les libellés de la ligne
    d'en-tête groupée (GROUP_HEADER_ROW). Un type d'absence dont le libellé
    n'est pas trouvé est simplement absent du dict retourné (aucune erreur :
    cf. test correspondant, un mois sans certaines colonnes doit rester
    parsable)."""
    libelles = [c.value for c in ws[GROUP_HEADER_ROW]]
    resultat: dict[TypeAbsence, tuple[int, int]] = {}
    for idx, valeur in enumerate(libelles):
        type_absence = _label_vers_type_absence(valeur)
        if type_absence is None or idx + 1 >= len(libelles):
            continue
        resultat[type_absence] = (idx, idx + 1)
    return resultat


def _normaliser_libelle(valeur: Any) -> str:
    if valeur is None:
        return ""
    s = unicodedata.normalize("NFKD", str(valeur))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def _label_vers_type_absence(valeur: Any) -> Optional[TypeAbsence]:
    libelle = _normaliser_libelle(valeur)
    if not libelle:
        return None
    for type_absence, motif in MOTIFS_LABEL_ABSENCE.items():
        if motif in libelle:
            return type_absence
    return None


def _periode_depuis_entete(ws) -> date:
    cell = ws.cell(row=2, column=2).value  # libellé "DATE" en A2, valeur en B2
    if isinstance(cell, datetime):
        d = cell.date()
    elif isinstance(cell, date):
        d = cell
    else:
        raise ValueError(f"Cellule DATE (B2) invalide ou absente : {cell!r}")
    return d.replace(day=1)


def _parse_ligne(
    row_idx: int,
    row: tuple,
    periode: date,
    colonnes_absence: dict[TypeAbsence, tuple[int, int]],
) -> ParsedEVPLigne:
    avertissements: list[str] = []

    raw_matricule = _clean_str(_cell(row, COL_MATRICULE))

    ticket_restaurant_val = _cell(row, COL_NB_TICKET_RESTAURANT)
    nb_ticket_restaurant_renseigne = ticket_restaurant_val is not None

    absences = []
    for type_absence, (col_jours, col_dates) in colonnes_absence.items():
        nb_jours = _cell(row, col_jours)
        dates_brutes = _normalize_dates_brutes(_cell(row, col_dates))
        if nb_jours is None and dates_brutes is None:
            continue
        if nb_jours is None or dates_brutes is None:
            avertissements.append(
                f"{type_absence.value} : NB DE JOUR et DATES incohérents "
                "(l'une des deux colonnes est vide, pas l'autre)"
            )
            continue
        try:
            absences.append(
                AbsencePeriode(
                    type=type_absence, nb_jours=float(nb_jours), dates_brutes=dates_brutes
                )
            )
        except (ValidationError, ValueError, TypeError) as exc:
            avertissements.append(f"{type_absence.value} ignorée (invalide) : {exc}")

    try:
        evp = EVPMensuel(
            periode=periode,
            matricule=None,  # jamais le matricule EVP brut : non fiable (cf. docstring module)
            nom=_clean_str(_cell(row, COL_NOM)),
            prenom=_clean_str(_cell(row, COL_PRENOM)) or "",
            poste=_clean_str(_cell(row, COL_POSTE)) or "",
            type_contrat=_to_type_contrat(_cell(row, COL_TYPE_CONTRAT)),
            debut_contrat=_to_date(_cell(row, COL_DEBUT_CONTRAT)),
            fin_contrat=_to_date(_cell(row, COL_FIN_CONTRAT)),
            heure_mensuel=_to_optional_float(_cell(row, COL_HEURE_MENSUEL)),
            salaire_an=_to_optional_float(_cell(row, COL_SALAIRE_AN)),
            mutuelle=_clean_str(_cell(row, COL_MUTUELLE)),
            nb_ticket_restaurant=int(ticket_restaurant_val)
            if ticket_restaurant_val is not None
            else 0,
            pass_navigo=_to_bool_oui_non(_cell(row, COL_PASS_NAVIGO)),
            prime=_to_optional_float(_cell(row, COL_PRIME)),
            acompte=_to_optional_float(_cell(row, COL_ACOMPTE)),
            heures_sup=_to_optional_float(_cell(row, COL_HEURES_SUP)),
            absences=absences,
            remarques=_clean_str(_cell(row, COL_REMARQUES)),
        )
        erreurs: list[str] = []
    except (ValidationError, ValueError, TypeError) as exc:
        evp = None
        erreurs = [str(exc)]

    return ParsedEVPLigne(
        ligne_excel=row_idx,
        evp=evp,
        raw_matricule=raw_matricule,
        nb_ticket_restaurant_renseigne=nb_ticket_restaurant_renseigne,
        erreurs=erreurs,
        avertissements=avertissements,
    )


def _cell(row: tuple, index: int) -> Any:
    return row[index] if index < len(row) else None


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _to_type_contrat(value: Any) -> TypeContrat:
    s = (_clean_str(value) or "").upper()
    try:
        return TypeContrat(s)
    except ValueError:
        raise ValueError(f"Type de contrat EVP inconnu : {value!r}") from None


def _to_bool_oui_non(value: Any) -> bool:
    return (_clean_str(value) or "").upper() == "OUI"


def _to_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _normalize_dates_brutes(value: Any) -> Optional[str]:
    """Normalise une cellule DATES (texte libre ou datetime Excel natif)
    vers une chaîne cohérente, seule représentation acceptée par
    AbsencePeriode.dates_brutes (typé `str`)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return str(value)
