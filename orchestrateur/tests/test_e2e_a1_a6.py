"""
orchestrateur/tests/test_e2e_a1_a6.py

Valide le critère de la Phase 3 du guide :
"un dossier fictif traverse A1->A6 via appels API manuels (Postman/curl),
chaque transition apparaît dans audit_log."

Utilise TestClient (appels HTTP réels sur l'app FastAPI, pas des appels
Python directs) pour rester fidèle à "via appels API".
Utilise le cas réel Didier (cas_01_didier_reel.json) comme donnée d'entrée.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "orchestrateur" / "app"))
sys.path.insert(0, str(ROOT / "db"))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from database import SessionLocal, init_db  # noqa: E402
from models import AuditLog  # noqa: E402

# `on_event("startup")` ne se déclenche qu'à l'intérieur d'un contexte
# `with TestClient(app) as client:` (nécessaire pour exécuter init_db()).
init_db()  # filet de sécurité explicite, indépendant du cycle de vie FastAPI
client = TestClient(app)

FIXTURE = ROOT / "tests" / "fixtures" / "cas_01_didier_reel.json"

# Séquence nominale A1 -> A6 -> TERMINE (sans passer par les boucles)
SEQUENCE_NOMINALE = [
    ("extraire_evp", "orchestrateur"),
    ("valider_transmission", "gestionnaire"),
    ("calcul_termine", "orchestrateur"),
    ("valider_bulletin", "responsable_validation"),
    ("autoriser_paiement", "responsable_validation"),
    ("cloturer", "orchestrateur"),
]


def test_parcours_complet_a1_a6():
    cas = json.loads(FIXTURE.read_text(encoding="utf-8"))

    # --- POST /dossiers ---
    resp = client.post(
        "/dossiers",
        json={"matricule": "0004", "contrat": cas["contrat"], "evp": cas["evp"]},
    )
    assert resp.status_code == 201, resp.text
    dossier = resp.json()
    assert dossier["etat"] == "A1"
    dossier_id = dossier["id"]

    etats_traverses = ["A1"]

    # --- Traversée A1 -> A6 -> TERMINE via POST /transition ---
    for action, acteur in SEQUENCE_NOMINALE:
        resp = client.post(
            f"/dossiers/{dossier_id}/transition",
            json={"action": action, "acteur": acteur, "commentaire": f"test e2e: {action}"},
        )
        assert resp.status_code == 200, f"Echec sur {action}: {resp.text}"
        etats_traverses.append(resp.json()["etat"])

    assert etats_traverses == ["A1", "A2", "A3", "A4", "A5", "A6", "TERMINE"]

    # --- GET /etat final ---
    resp = client.get(f"/dossiers/{dossier_id}/etat")
    assert resp.status_code == 200
    assert resp.json()["etat"] == "TERMINE"
    assert resp.json()["triggers_disponibles"] == []  # état terminal, aucune transition possible

    # --- Vérification directe en base : chaque transition dans audit_log ---
    session = SessionLocal()
    try:
        entries = (
            session.query(AuditLog)
            .filter_by(dossier_id=dossier_id)
            .order_by(AuditLog.horodatage)
            .all()
        )
        # 1 création + 6 transitions = 7 entrées
        assert len(entries) == 7, [e.action for e in entries]
        assert entries[0].action == "creation_dossier"
        for entry, (action, acteur) in zip(entries[1:], SEQUENCE_NOMINALE):
            assert entry.acteur == acteur
            assert entry.resultat == "succes"
            assert entry.action.startswith("transition_etat:")
            assert entry.details_json["action"] == action  # trigger déclenché, tracé en détail
            assert entry.horodatage is not None
    finally:
        session.close()


def test_transition_invalide_rejetee_et_journalisee():
    """Une transition impossible depuis l'état courant doit renvoyer 409
    et être journalisée avec resultat='echec' (traçabilité même des refus)."""
    cas = json.loads(FIXTURE.read_text(encoding="utf-8"))
    resp = client.post(
        "/dossiers", json={"matricule": "0099", "contrat": cas["contrat"], "evp": cas["evp"]}
    )
    dossier_id = resp.json()["id"]

    # Depuis A1, "valider_bulletin" (transition A4->A5) est impossible
    resp = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={"action": "valider_bulletin", "acteur": "gestionnaire"},
    )
    assert resp.status_code == 409

    session = SessionLocal()
    try:
        entry = (
            session.query(AuditLog)
            .filter_by(dossier_id=dossier_id, resultat="echec")
            .one()
        )
        assert "transition_refusee" in entry.action
    finally:
        session.close()


def test_boucle_a2_3_puis_retour_a1():
    """Boucle A2.3 -> A1 (écart détecté puis correction), cf. guide §1.3."""
    cas = json.loads(FIXTURE.read_text(encoding="utf-8"))
    resp = client.post(
        "/dossiers", json={"matricule": "0100", "contrat": cas["contrat"], "evp": cas["evp"]}
    )
    dossier_id = resp.json()["id"]

    for action, acteur, etat_attendu in [
        ("extraire_evp", "orchestrateur", "A2"),
        ("detecter_ecart", "gestionnaire", "A2_3"),
        ("corriger_evp", "gestionnaire", "A1"),
    ]:
        resp = client.post(
            f"/dossiers/{dossier_id}/transition", json={"action": action, "acteur": acteur}
        )
        assert resp.status_code == 200
        assert resp.json()["etat"] == etat_attendu
