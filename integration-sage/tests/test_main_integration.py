"""
integration-sage/tests/test_main_integration.py

Test d'intégration de la route POST /calculer (app/main.py) : appels HTTP
réels via TestClient (même pattern que compliance-validation/tests/
test_main_integration.py et extracteur-evp/tests/test_main_integration.py).
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests" / "fixtures" / "cas_01_didier_reel.json"


def test_calculer_cas_nominal_renvoie_un_bulletin_valide():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload = {"matricule": data["id"], "contrat": data["contrat"], "evp_historique": [data["evp"]]}

    resp = client.post("/calculer", json=payload)

    assert resp.status_code == 200, resp.text
    bulletin = resp.json()
    assert bulletin["matricule"] == data["id"]
    assert bulletin["salaire_base_mensuel"] == data["contrat"]["remuneration_mensuelle_brute"]
    assert bulletin["net_a_payer"] > 0


def test_calculer_dossier_incomplet_renvoie_422():
    resp = client.post("/calculer", json={"matricule": "0001"})  # "contrat" manquant
    assert resp.status_code == 422


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
