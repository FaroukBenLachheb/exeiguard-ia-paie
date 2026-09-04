"""
extracteur-evp/tests/test_main_integration.py

Test d'intégration de la route POST /extraire (app/main.py) : appels HTTP
réels via TestClient (même pattern que
orchestrateur/tests/test_e2e_a1_a6.py), distinct des tests unitaires du
parser (test_excel_parser.py, inchangés) qui appellent parse_evp_file()
directement en Python.

Aucune fixture .xlsx réelle n'existe dans tests/fixtures/ (les fichiers
EVP réels Soft IT sont confidentiels, cf. data-confidentielles/, non
versionnés) : le classeur nominal est donc construit ici avec la même
structure réelle que celle documentée dans excel_parser.py et déjà
exercée par test_excel_parser.py::test_ligne_nominale_parsee_et_validee
(mêmes constantes COL_*, même disposition de lignes), pas une structure
inventée.
"""

from datetime import date

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.parsers.excel_parser import (
    COL_DEBUT_CONTRAT,
    COL_MATRICULE,
    COL_NB_TICKET_RESTAURANT,
    COL_NOM,
    COL_PASS_NAVIGO,
    COL_POSTE,
    COL_PRENOM,
    COL_SALAIRE_AN,
    COL_TYPE_CONTRAT,
)

client = TestClient(app)

NB_COLONNES = 28


def _classeur_evp_nominal(tmp_path) -> str:
    row = [None] * NB_COLONNES
    row[COL_MATRICULE] = 1
    row[COL_NOM] = None
    row[COL_PRENOM] = "Lucie"
    row[COL_POSTE] = "Développeur Backend"
    row[COL_TYPE_CONTRAT] = "CDI"
    row[COL_DEBUT_CONTRAT] = date(2025, 3, 1)
    row[COL_SALAIRE_AN] = 42000
    row[COL_NB_TICKET_RESTAURANT] = 16
    row[COL_PASS_NAVIGO] = "OUI"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["VARIABLES SOFT IT"] + [None] * (NB_COLONNES - 1))
    ws.append(["DATE", date(2026, 6, 1)] + [None] * (NB_COLONNES - 2))
    ws.append([None] * NB_COLONNES)  # ligne 3 : en-têtes groupées absences (aucun bloc ici)
    ws.append([None] * NB_COLONNES)  # ligne 4 : en-têtes de colonnes
    ws.append([None] * NB_COLONNES)  # ligne 5 : vide
    ws.append(row)

    chemin = tmp_path / "evp_nominal.xlsx"
    wb.save(chemin)
    return str(chemin)


def test_extraire_cas_nominal_renvoie_lignes_et_scores(tmp_path):
    chemin = _classeur_evp_nominal(tmp_path)

    with open(chemin, "rb") as f:
        resp = client.post(
            "/extraire",
            files={
                "fichier": (
                    "evp_nominal.xlsx",
                    f,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["nb_lignes"] == 1
    assert len(payload["lignes"]) == 1

    ligne = payload["lignes"][0]
    assert ligne["erreurs"] == []
    assert ligne["evp"]["prenom"] == "Lucie"
    assert ligne["evp"]["salaire_an"] == 42000.0
    assert "score_confiance" in ligne
    assert 0.0 <= ligne["score_confiance"]["valeur"] <= 1.0
    assert ligne["score_confiance"]["raisons"]


def test_extraire_fichier_illisible_renvoie_400():
    resp = client.post(
        "/extraire",
        files={"fichier": ("pas_un_excel.xlsx", b"ceci n'est pas un fichier xlsx", "text/plain")},
    )
    assert resp.status_code == 400
    assert "illisible" in resp.json()["detail"] or "mal form" in resp.json()["detail"]


def test_extraire_fichier_vide_renvoie_400():
    resp = client.post(
        "/extraire",
        files={"fichier": ("vide.xlsx", b"", "application/octet-stream")},
    )
    assert resp.status_code == 400
