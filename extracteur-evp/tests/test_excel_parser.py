"""
extracteur-evp/tests/test_excel_parser.py

Tests du parser Excel EVP (app/parsers/excel_parser.py) sur des classeurs
construits en mémoire avec des données SYNTHÉTIQUES reproduisant fidèlement
la structure du fichier réel (colonnes, lignes d'en-tête groupées, types de
cellules) - jamais les données de data-confidentielles/EXEIGUARD-DATA-TEST/
(non versionnées, cf. .gitignore).

Les 3 anomalies réelles documentées dans la consigne D.4 sont chacune
couvertes par un test dédié :
  - matricule EVP non fiable (numéro de ligne, jamais un identifiant Sage)
  - colonne DATES tantôt texte libre, tantôt datetime Excel natif
  - colonne numérique à 0 (valeur réelle) vs vide (non renseignée)
"""

from datetime import date, datetime

import openpyxl
import pytest

from app.parsers.excel_parser import (
    ABSENCE_COLUMNS,
    COL_ACOMPTE,
    COL_DEBUT_CONTRAT,
    COL_FIN_CONTRAT,
    COL_HEURE_MENSUEL,
    COL_HEURES_SUP,
    COL_MATRICULE,
    COL_MUTUELLE,
    COL_NB_TICKET_RESTAURANT,
    COL_NOM,
    COL_PASS_NAVIGO,
    COL_POSTE,
    COL_PRENOM,
    COL_PRIME,
    COL_REMARQUES,
    COL_SALAIRE_AN,
    COL_TYPE_CONTRAT,
    parse_evp_file,
)
from shared.schemas import TypeAbsence

NB_COLONNES = 28


def _ligne_vide() -> list:
    return [None] * NB_COLONNES


def _ligne_salarie(
    *,
    matricule=None,
    nom=None,
    prenom="Test",
    poste="Développeur Backend",
    type_contrat="CDI",
    debut_contrat=date(2025, 3, 1),
    fin_contrat=None,
    heure_mensuel=None,
    salaire_an=42000,
    mutuelle="Seul",
    nb_ticket_restaurant=16,
    pass_navigo="OUI",
    prime=None,
    acompte=None,
    heures_sup=None,
    absence_type: TypeAbsence | None = None,
    absence_nb_jours=None,
    absence_dates=None,
    absences: list[tuple] | None = None,
    remarques=None,
) -> list:
    """`absence_type`/`absence_nb_jours`/`absence_dates` positionnent une
    seule absence ; `absences` (liste de tuples (type, nb_jours, dates))
    permet d'en positionner plusieurs sur la même ligne, comme dans le
    fichier réel (cf. test_cp_et_rtt_non_confondus_sur_la_meme_ligne)."""
    row = _ligne_vide()
    row[COL_MATRICULE] = matricule
    row[COL_NOM] = nom
    row[COL_PRENOM] = prenom
    row[COL_POSTE] = poste
    row[COL_TYPE_CONTRAT] = type_contrat
    row[COL_DEBUT_CONTRAT] = debut_contrat
    row[COL_FIN_CONTRAT] = fin_contrat
    row[COL_HEURE_MENSUEL] = heure_mensuel
    row[COL_SALAIRE_AN] = salaire_an
    row[COL_MUTUELLE] = mutuelle
    row[COL_NB_TICKET_RESTAURANT] = nb_ticket_restaurant
    row[COL_PASS_NAVIGO] = pass_navigo
    row[COL_PRIME] = prime
    row[COL_ACOMPTE] = acompte
    row[COL_HEURES_SUP] = heures_sup
    row[COL_REMARQUES] = remarques

    if absence_type is not None:
        col_jours, col_dates = ABSENCE_COLUMNS[absence_type]
        row[col_jours] = absence_nb_jours
        row[col_dates] = absence_dates

    for type_, nb_jours, dates in absences or []:
        col_jours, col_dates = ABSENCE_COLUMNS[type_]
        row[col_jours] = nb_jours
        row[col_dates] = dates

    return row


def _ecrire_classeur(tmp_path, lignes, periode=date(2026, 6, 1)) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = periode.strftime("%m%Y")

    ws.append(["VARIABLES SOFT IT"] + [None] * (NB_COLONNES - 1))
    ws.append(["DATE", periode] + [None] * (NB_COLONNES - 2))
    ws.append(_ligne_vide())  # ligne d'en-tête groupée (non exploitée par le parser)
    ws.append(
        [
            "MATRICULE", "NOM", "PRENOM", "POSTE", "TYPE DE CONTRAT", "DEBUT CONTRAT",
            "FIN DE CONTRAT", "HEURE MENSUEL", "SALAIRE/AN", "MUTUELLE",
            "NB TICKET RESTAURANT", "PASS NAVIGO", "PRIME", "ACOMPTE", "HEURES SUP",
            "NB DE JOUR", "DATES", "NB DE JOUR", "DATES", "NB DE JOUR", "DATES",
            "NB DE JOUR", "DATES", "NB DE JOUR", "DATES", None, None, "REMARQUES",
        ]
    )
    ws.append(_ligne_vide())
    for ligne in lignes:
        ws.append(ligne)

    chemin = tmp_path / "evp_synthetique.xlsx"
    wb.save(chemin)
    return str(chemin)


# ---------------------------------------------------------------------------
# Cas nominal
# ---------------------------------------------------------------------------

def test_ligne_nominale_parsee_et_validee(tmp_path):
    chemin = _ecrire_classeur(
        tmp_path, [_ligne_salarie(matricule=1, prenom="Lucie", salaire_an=42000)]
    )
    resultats = parse_evp_file(chemin)

    assert len(resultats) == 1
    ligne = resultats[0]
    assert ligne.evp is not None
    assert not ligne.erreurs
    assert ligne.evp.prenom == "Lucie"
    assert ligne.evp.salaire_an == 42000.0
    assert ligne.evp.periode == date(2026, 6, 1)


def test_lignes_vides_en_fin_de_tableau_ignorees(tmp_path):
    chemin = _ecrire_classeur(tmp_path, [_ligne_salarie(matricule=1, prenom="Lucie")])
    resultats = parse_evp_file(chemin)
    assert len(resultats) == 1  # les lignes vides après (cf. _ecrire_classeur) ne sont pas comptées


# ---------------------------------------------------------------------------
# Anomalie 1 : matricule EVP non fiable
# ---------------------------------------------------------------------------

def test_matricule_evp_jamais_transmis_au_modele(tmp_path):
    """Le matricule EVP (simple numéro de ligne) ne doit jamais devenir
    EVPMensuel.matricule : seul nom/prénom identifie la ligne."""
    chemin = _ecrire_classeur(
        tmp_path, [_ligne_salarie(matricule=1, prenom="Lucie", nom=None)]
    )
    resultats = parse_evp_file(chemin)
    ligne = resultats[0]

    assert ligne.raw_matricule == "1"  # conservé à part, pour audit uniquement
    assert ligne.evp.matricule is None  # jamais utilisé comme identifiant


def test_identification_par_nom_prenom_sans_matricule(tmp_path):
    """Une ligne sans aucun matricule doit rester exploitable via prénom seul."""
    chemin = _ecrire_classeur(
        tmp_path, [_ligne_salarie(matricule=None, prenom="Lucie", nom=None)]
    )
    resultats = parse_evp_file(chemin)
    ligne = resultats[0]

    assert ligne.raw_matricule is None
    assert ligne.evp is not None
    assert ligne.evp.prenom == "Lucie"


# ---------------------------------------------------------------------------
# Anomalie 2 : colonne DATES texte libre vs datetime Excel natif
# ---------------------------------------------------------------------------

def test_dates_absence_texte_libre_preservees(tmp_path):
    chemin = _ecrire_classeur(
        tmp_path,
        [
            _ligne_salarie(
                matricule=1,
                prenom="Lucie",
                absence_type=TypeAbsence.RTT,
                absence_nb_jours=3,
                absence_dates="22, 25 et 26/05",
            )
        ],
    )
    ligne = parse_evp_file(chemin)[0]

    assert ligne.evp is not None
    assert len(ligne.evp.absences) == 1
    assert ligne.evp.absences[0].dates_brutes == "22, 25 et 26/05"
    assert ligne.evp.absences[0].nb_jours == 3


def test_dates_absence_datetime_natif_normalise_en_chaine(tmp_path):
    """Une cellule DATES saisie comme datetime Excel natif (et non comme
    texte) doit être normalisée en chaîne JJ/MM/AAAA avant validation
    Pydantic (AbsencePeriode.dates_brutes est typé `str`)."""
    chemin = _ecrire_classeur(
        tmp_path,
        [
            _ligne_salarie(
                matricule=1,
                prenom="Lucie",
                absence_type=TypeAbsence.CP,
                absence_nb_jours=1,
                absence_dates=datetime(2026, 5, 7),
            )
        ],
    )
    ligne = parse_evp_file(chemin)[0]

    assert ligne.evp is not None
    assert len(ligne.evp.absences) == 1
    assert ligne.evp.absences[0].type == TypeAbsence.CP
    assert ligne.evp.absences[0].dates_brutes == "07/05/2026"  # chaîne, pas un datetime


def test_cp_et_rtt_non_confondus_sur_la_meme_ligne(tmp_path):
    """Non-régression : la transcription manuelle D.1 avait classé en RTT
    des absences CP de Didier/Sindhuja (cas_01/cas_02 dans
    scripts/generate_fixtures.py, corrigé suite à cette détection par le
    parser D.4, cf. commit 11bb025). Reproduit le positionnement réel qui a
    causé la confusion : une ligne avec une absence dans le bloc CP
    (colonnes 15/16) ET une dans le bloc RTT (colonnes 17/18), comme le
    fichier Excel réel de Sindhuja (juin 2026) - les deux doivent rester
    correctement associées à leur type et leurs dates, sans être ni
    fusionnées ni permutées."""
    chemin = _ecrire_classeur(
        tmp_path,
        [
            _ligne_salarie(
                matricule=5,
                prenom="Lucie",
                absences=[
                    (TypeAbsence.CP, 1, "07/05/2026"),
                    (TypeAbsence.RTT, 1, "15/05/2026"),
                ],
            )
        ],
    )
    ligne = parse_evp_file(chemin)[0]

    assert ligne.evp is not None
    assert len(ligne.evp.absences) == 2

    par_type = {a.type: a for a in ligne.evp.absences}
    assert set(par_type) == {TypeAbsence.CP, TypeAbsence.RTT}
    assert par_type[TypeAbsence.CP].dates_brutes == "07/05/2026"
    assert par_type[TypeAbsence.CP].nb_jours == 1
    assert par_type[TypeAbsence.RTT].dates_brutes == "15/05/2026"
    assert par_type[TypeAbsence.RTT].nb_jours == 1


def test_absence_incoherente_nb_jours_sans_dates_devient_avertissement(tmp_path):
    chemin = _ecrire_classeur(
        tmp_path,
        [
            _ligne_salarie(
                matricule=1,
                prenom="Lucie",
                absence_type=TypeAbsence.MALADIE,
                absence_nb_jours=5,
                absence_dates=None,  # incohérent : jours renseignés, dates absentes
            )
        ],
    )
    ligne = parse_evp_file(chemin)[0]

    assert ligne.evp is not None
    assert ligne.evp.absences == []  # absence rejetée, pas remontée comme si elle était valide
    assert any("MALADIE" in a for a in ligne.avertissements)


# ---------------------------------------------------------------------------
# Anomalie 3 : 0 (valeur réelle) vs None (non renseigné)
# ---------------------------------------------------------------------------

def test_nb_ticket_restaurant_zero_explicite_distingue_de_non_renseigne(tmp_path):
    chemin = _ecrire_classeur(
        tmp_path,
        [
            _ligne_salarie(matricule=1, prenom="Julien", nb_ticket_restaurant=0),
            _ligne_salarie(matricule=2, prenom="Karim", nb_ticket_restaurant=None),
        ],
    )
    julien, karim = parse_evp_file(chemin)

    assert julien.nb_ticket_restaurant_renseigne is True
    assert julien.evp.nb_ticket_restaurant == 0

    assert karim.nb_ticket_restaurant_renseigne is False
    assert karim.evp.nb_ticket_restaurant == 0  # valeur par défaut du schéma (non Optional)


# ---------------------------------------------------------------------------
# Autres champs
# ---------------------------------------------------------------------------

def test_pass_navigo_oui_non_converti_en_bool(tmp_path):
    chemin = _ecrire_classeur(
        tmp_path,
        [
            _ligne_salarie(matricule=1, prenom="A", pass_navigo="OUI"),
            _ligne_salarie(matricule=2, prenom="B", pass_navigo="NON"),
        ],
    )
    a, b = parse_evp_file(chemin)
    assert a.evp.pass_navigo is True
    assert b.evp.pass_navigo is False


def test_remarques_avec_prime_texte_libre_preservees(tmp_path):
    chemin = _ecrire_classeur(
        tmp_path,
        [
            _ligne_salarie(
                matricule=1, prenom="Karim", remarques="Prime Durée de mission 1500 € Brut"
            )
        ],
    )
    ligne = parse_evp_file(chemin)[0]
    assert ligne.evp.prime is None  # jamais reconstruit depuis le texte libre
    assert "1500" in ligne.evp.remarques


def test_type_contrat_inconnu_rejete_comme_erreur(tmp_path):
    chemin = _ecrire_classeur(
        tmp_path, [_ligne_salarie(matricule=1, prenom="X", type_contrat="INTERIM")]
    )
    ligne = parse_evp_file(chemin)[0]
    assert ligne.evp is None
    assert ligne.erreurs


def test_periode_deduite_de_len_tete_date(tmp_path):
    chemin = _ecrire_classeur(
        tmp_path, [_ligne_salarie(matricule=1, prenom="X")], periode=date(2026, 5, 1)
    )
    ligne = parse_evp_file(chemin)[0]
    assert ligne.evp.periode == date(2026, 5, 1)
