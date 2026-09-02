"""
compliance-validation/tests/test_main_integration.py

Test d'intégration de la route POST /evaluer (app/main.py) : appels HTTP
réels via TestClient (même pattern que
orchestrateur/tests/test_e2e_a1_a6.py), distinct des tests unitaires du
Rule Engine (test_rule_engine.py, inchangés) qui appellent
evaluer_toutes_les_regles() directement en Python.

Le cas nominal charge la fixture réelle tests/fixtures/cas_01_didier_reel.json
(même fixture que test_rule_engine.py), envoyée telle quelle en JSON au
format du schéma DossierSalarie.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests" / "fixtures" / "cas_01_didier_reel.json"


def test_evaluer_cas_nominal_renvoie_les_10_regles():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload = {
        "matricule": data["id"],
        "contrat": data["contrat"],
        "evp_historique": [data["evp"]],
    }

    resp = client.post("/evaluer", json=payload)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matricule"] == data["id"]
    resultats = body["resultats"]
    assert len(resultats) == 10
    assert {r["regle_id"] for r in resultats} == {f"RG-{i:02d}" for i in range(1, 11)}
    for r in resultats:
        assert set(r) == {"regle_id", "conforme", "message", "source"}
        assert r["source"]


def test_evaluer_dossier_incomplet_renvoie_422():
    resp = client.post("/evaluer", json={"matricule": "0001"})  # "contrat" manquant
    assert resp.status_code == 422
