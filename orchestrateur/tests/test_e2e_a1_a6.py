"""
orchestrateur/tests/test_e2e_a1_a6.py

Valide le critère de la Phase 3 du guide :
"un dossier fictif traverse A1->A6 via appels API manuels (Postman/curl),
chaque transition apparaît dans audit_log."

Utilise TestClient (appels HTTP réels sur l'app FastAPI, pas des appels
Python directs) pour rester fidèle à "via appels API".
Utilise le cas réel Didier (cas_01_didier_reel.json) comme donnée d'entrée.

JOUR 1 (câblage réel du pipeline) : les transitions extraire_evp,
valider_transmission, calcul_termine et valider_bulletin déclenchent
désormais un vrai appel HTTP sortant (httpx) vers extracteur-evp,
compliance-validation et integration-sage (cf. orchestrateur/app/main.py,
_APPELS_PAR_ACTION). Ce fichier NE reteste PAS la logique métier de ces
3 services (déjà couverte par leurs propres suites : 16/16 excel_parser,
28/28 rule engine, tests dédiés du mock integration-sage) : httpx.post est
remplacé ici par un double déterministe (cf. fixture `_stub_services_http`)
qui renvoie des réponses au même format que les vrais services, pour que
ce fichier reste un test hermétique et rapide de l'ORCHESTRATEUR
(légalité des transitions, persistance EVPEnregistrement/Controle/
Bulletin, refus sur échec, traçabilité audit_log). La preuve que les 3
vrais services répondent réellement à ces appels, avec le code actuel
construit en conteneur, est apportée séparément par la session de
vérification manuelle (docker compose + curl, cf. rapport de vérification
JOUR 1).
"""

import base64
import io
import json
import sys
from datetime import date, datetime
from pathlib import Path

import httpx
import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "orchestrateur" / "app"))
sys.path.insert(0, str(ROOT / "db"))

import main as main_module  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from database import SessionLocal, init_db  # noqa: E402
from models import AuditLog, Bulletin, Controle, EVPEnregistrement  # noqa: E402

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

# Position des colonnes (0-based), dupliquée depuis
# extracteur-evp/app/parsers/excel_parser.py::COL_* (import direct
# impossible ici : "extracteur-evp" contient un tiret, non importable
# comme package Python sans manipulation de sys.path propre à ce
# service). Uniquement les colonnes utilisées par ce stub de test.
NB_COLONNES = 28
COL_MATRICULE = 0
COL_NOM = 1
COL_PRENOM = 2
COL_POSTE = 3
COL_TYPE_CONTRAT = 4
COL_DEBUT_CONTRAT = 5
COL_SALAIRE_AN = 8
COL_NB_TICKET_RESTAURANT = 10
COL_PASS_NAVIGO = 11


def _classeur_evp_depuis_dict(evp: dict) -> bytes:
    """Construit un classeur .xlsx minimal exploitable par excel_parser.py à
    partir d'un dict EVPMensuel (même disposition réelle que documentée
    dans excel_parser.py : titre, ligne DATE, 2 lignes d'en-tête, ligne
    vide, puis les données)."""
    row = [None] * NB_COLONNES
    row[COL_MATRICULE] = 1
    row[COL_NOM] = evp.get("nom")
    row[COL_PRENOM] = evp["prenom"]
    row[COL_POSTE] = evp["poste"]
    row[COL_TYPE_CONTRAT] = evp["type_contrat"]
    row[COL_DEBUT_CONTRAT] = date.fromisoformat(evp["debut_contrat"])
    row[COL_SALAIRE_AN] = evp["salaire_an"]
    row[COL_NB_TICKET_RESTAURANT] = evp.get("nb_ticket_restaurant", 0)
    row[COL_PASS_NAVIGO] = "OUI" if evp.get("pass_navigo") else "NON"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["VARIABLES SOFT IT"] + [None] * (NB_COLONNES - 1))
    ws.append(["DATE", date.fromisoformat(evp["periode"])] + [None] * (NB_COLONNES - 2))
    ws.append([None] * NB_COLONNES)  # ligne 3 : en-têtes groupées absences (aucun bloc ici)
    ws.append([None] * NB_COLONNES)  # ligne 4 : en-têtes de colonnes
    ws.append([None] * NB_COLONNES)  # ligne 5 : vide
    ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _evp_fichier_base64(evp: dict) -> str:
    return base64.b64encode(_classeur_evp_depuis_dict(evp)).decode("ascii")


def _cell_date_iso(valeur) -> str | None:
    """openpyxl relit une cellule date comme `datetime` (pas `date`) une
    fois le classeur rechargé : normalise vers une chaîne ISO "date pure"
    dans les deux cas."""
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        return valeur.date().isoformat()
    return valeur.isoformat()


def _bulletin_stub(matricule: str, contrat: dict) -> dict:
    return {
        "periode_debut": "2026-06-01",
        "periode_fin": "2026-06-30",
        "matricule": matricule,
        "date_entree": contrat["date_effet"],
        "date_premiere_entree": contrat["date_effet"],
        "emploi": contrat["poste"],
        "qualification": f"{contrat['statut']} Position {contrat['position']}",
        "convention_collective": contrat["convention_collective"],
        "salaire_base_mensuel": contrat["remuneration_mensuelle_brute"],
        "total_remuneration_brute": contrat["remuneration_mensuelle_brute"],
        "total_cotisations_salariales": 900.0,
        "total_cotisations_patronales": 1700.0,
        "montant_net_social": 3400.0,
        "net_a_payer_avant_ir": 3400.0,
        "impot_revenu_base": 3400.0,
        "impot_revenu_taux": 0.0,
        "impot_revenu_montant": 0.0,
        "impot_revenu_cumul": 0.0,
        "net_a_payer": 3400.0,
        "date_paiement": "2026-06-30",
        "mode_reglement": "Virement (stub test)",
        "heures_payees_cumul": contrat["heures_mensuelles"],
        "remuneration_brute_cumul": contrat["remuneration_mensuelle_brute"],
    }


@pytest.fixture(autouse=True)
def _stub_services_http(monkeypatch):
    """Remplace httpx.post par un double déterministe qui répond au même
    format que les vrais services (extracteur-evp, compliance-validation,
    integration-sage), sans requête réseau réelle. `calls` (liste) permet
    aux tests d'inspecter quels appels ont réellement été émis par
    l'orchestrateur (URL appelée), utile pour prouver que le câblage
    appelle bien le bon service à la bonne transition."""
    calls = []

    def _fake_post(url, *, json=None, files=None, timeout=None):
        calls.append(url)
        if url.startswith(main_module.EXTRACTEUR_EVP_URL):
            contenu = files["fichier"][1]
            wb = openpyxl.load_workbook(io.BytesIO(contenu), data_only=True)
            ws = wb.active
            row = list(ws.iter_rows(min_row=6, max_row=6, values_only=True))[0]
            evp = {
                "periode": _cell_date_iso(ws.cell(row=2, column=2).value),
                "matricule": None,
                "nom": row[1],
                "prenom": row[COL_PRENOM],
                "poste": row[3],
                "type_contrat": row[4],
                "debut_contrat": _cell_date_iso(row[5]),
                "fin_contrat": None,
                "heure_mensuel": None,
                "salaire_an": row[8],
                "mutuelle": None,
                "nb_ticket_restaurant": row[10] or 0,
                "pass_navigo": row[11] == "OUI",
                "prime": None,
                "acompte": None,
                "heures_sup": None,
                "absences": [],
                "remarques": None,
            }
            return httpx.Response(
                200,
                json={
                    "fichier": "evp.xlsx",
                    "nb_lignes": 1,
                    "lignes": [
                        {
                            "ligne_excel": 6,
                            "evp": evp,
                            "raw_matricule": "1",
                            "nb_ticket_restaurant_renseigne": True,
                            "erreurs": [],
                            "avertissements": [],
                            "score_confiance": {"valeur": 0.85, "raisons": ["stub test"]},
                        }
                    ],
                },
            )
        if url.startswith(main_module.COMPLIANCE_VALIDATION_URL):
            resultats = [
                {"regle_id": f"RG-{i:02d}", "conforme": True, "message": "stub conforme", "source": "rule_engine"}
                for i in range(1, 11)
            ]
            return httpx.Response(200, json={"matricule": json["matricule"], "resultats": resultats})
        if url.startswith(main_module.INTEGRATION_SAGE_URL):
            return httpx.Response(200, json=_bulletin_stub(json["matricule"], json["contrat"]))
        raise AssertionError(f"URL inattendue dans le stub httpx.post: {url}")

    monkeypatch.setattr(main_module.httpx, "post", _fake_post)
    return calls


def test_parcours_complet_a1_a6(_stub_services_http):
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
        body = {"action": action, "acteur": acteur, "commentaire": f"test e2e: {action}"}
        if action == "extraire_evp":
            body["evp_fichier_base64"] = _evp_fichier_base64(cas["evp"])
        resp = client.post(f"/dossiers/{dossier_id}/transition", json=body)
        assert resp.status_code == 200, f"Echec sur {action}: {resp.text}"
        etats_traverses.append(resp.json()["etat"])

    assert etats_traverses == ["A1", "A2", "A3", "A4", "A5", "A6", "TERMINE"]

    # --- Les 3 services ont bien été réellement appelés (pas juste un statut avancé) ---
    assert any(u.startswith(main_module.EXTRACTEUR_EVP_URL) for u in _stub_services_http)
    assert sum(u.startswith(main_module.COMPLIANCE_VALIDATION_URL) for u in _stub_services_http) == 2  # A2 + A4
    assert any(u.startswith(main_module.INTEGRATION_SAGE_URL) for u in _stub_services_http)

    # --- GET /etat final ---
    resp = client.get(f"/dossiers/{dossier_id}/etat")
    assert resp.status_code == 200
    assert resp.json()["etat"] == "TERMINE"
    assert resp.json()["triggers_disponibles"] == []  # état terminal, aucune transition possible

    session = SessionLocal()
    try:
        # --- EVPEnregistrement peuplé par le vrai appel à extracteur-evp ---
        evp_rows = session.query(EVPEnregistrement).filter_by(dossier_id=dossier_id).all()
        assert len(evp_rows) == 1
        assert evp_rows[0].evp_json["prenom"] == "Didier"
        assert evp_rows[0].score_confiance == 0.85

        # --- Controle : 10 lignes en A2, 10 de plus en A4 ---
        controles_a2 = session.query(Controle).filter_by(dossier_id=dossier_id, phase="A2").all()
        controles_a4 = session.query(Controle).filter_by(dossier_id=dossier_id, phase="A4").all()
        assert len(controles_a2) == 10
        assert len(controles_a4) == 10
        assert {c.regle_id for c in controles_a2} == {f"RG-{i:02d}" for i in range(1, 11)}

        # --- Bulletin peuplé par le vrai appel à integration-sage ---
        bulletins = session.query(Bulletin).filter_by(dossier_id=dossier_id).all()
        assert len(bulletins) == 1
        assert bulletins[0].bulletin_json["net_a_payer"] == 3400.0

        # --- audit_log : création + 6 transitions + appels inter-services ---
        entries = (
            session.query(AuditLog)
            .filter_by(dossier_id=dossier_id)
            .order_by(AuditLog.horodatage)
            .all()
        )
        actions = [e.action for e in entries]
        assert "creation_dossier" in actions
        assert "appel_extracteur_evp" in actions
        assert actions.count("appel_compliance_validation:A2") == 1
        assert actions.count("appel_compliance_validation:A4") == 1
        assert "appel_integration_sage" in actions
        assert sum(a.startswith("transition_etat:") for a in actions) == len(SEQUENCE_NOMINALE)
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
        body = {"action": action, "acteur": acteur}
        if action == "extraire_evp":
            body["evp_fichier_base64"] = _evp_fichier_base64(cas["evp"])
        resp = client.post(f"/dossiers/{dossier_id}/transition", json=body)
        assert resp.status_code == 200
        assert resp.json()["etat"] == etat_attendu


def test_extraire_evp_sans_fichier_refuse_la_transition():
    """Sans evp_fichier_base64, l'action extraire_evp doit être refusée
    (400) et NE DOIT PAS faire avancer l'état (pas d'avancement silencieux)."""
    cas = json.loads(FIXTURE.read_text(encoding="utf-8"))
    resp = client.post(
        "/dossiers", json={"matricule": "0101", "contrat": cas["contrat"], "evp": cas["evp"]}
    )
    dossier_id = resp.json()["id"]

    resp = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={"action": "extraire_evp", "acteur": "orchestrateur"},
    )
    assert resp.status_code == 400

    resp = client.get(f"/dossiers/{dossier_id}/etat")
    assert resp.json()["etat"] == "A1"  # inchangé


def test_echec_appel_service_refuse_la_transition(monkeypatch):
    """Si le service appelé répond en erreur, la transition doit être
    refusée (502) et l'état du dossier ne doit PAS avancer."""
    cas = json.loads(FIXTURE.read_text(encoding="utf-8"))
    resp = client.post(
        "/dossiers", json={"matricule": "0102", "contrat": cas["contrat"], "evp": cas["evp"]}
    )
    dossier_id = resp.json()["id"]

    def _fake_post_en_echec(url, **kwargs):
        return httpx.Response(500, text="erreur simulee")

    monkeypatch.setattr(main_module.httpx, "post", _fake_post_en_echec)

    resp = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "action": "extraire_evp",
            "acteur": "orchestrateur",
            "evp_fichier_base64": _evp_fichier_base64(cas["evp"]),
        },
    )
    assert resp.status_code == 502

    resp = client.get(f"/dossiers/{dossier_id}/etat")
    assert resp.json()["etat"] == "A1"  # inchangé : pas d'avancement silencieux sur un échec

    session = SessionLocal()
    try:
        entry = (
            session.query(AuditLog)
            .filter_by(dossier_id=dossier_id, action="appel_extracteur_evp", resultat="echec")
            .one()
        )
        assert entry.details_json["status_code"] == 500
    finally:
        session.close()
