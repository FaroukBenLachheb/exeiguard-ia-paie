"""
integration-sage/tests/test_calcul_simule.py

Tests unitaires de mock/calcul_simule.py (appel direct, pas HTTP) : le
calcul est FACTICE (cf. docstring du module) mais doit rester
déterministe et produire un BulletinSalaire structurellement valide à
partir d'un cas réel.
"""

import json
from pathlib import Path

from shared.schemas import DossierSalarie

from mock.calcul_simule import calculer_bulletin_simule

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests" / "fixtures" / "cas_01_didier_reel.json"


def _dossier_didier() -> DossierSalarie:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return DossierSalarie(matricule=data["id"], contrat=data["contrat"], evp_historique=[data["evp"]])


def test_calcul_deterministe_meme_entree_meme_sortie():
    dossier = _dossier_didier()
    b1 = calculer_bulletin_simule(dossier)
    b2 = calculer_bulletin_simule(dossier)
    assert b1 == b2


def test_calcul_utilise_le_brut_du_contrat():
    dossier = _dossier_didier()
    bulletin = calculer_bulletin_simule(dossier)
    assert bulletin.salaire_base_mensuel == dossier.contrat.remuneration_mensuelle_brute
    assert bulletin.total_remuneration_brute == dossier.contrat.remuneration_mensuelle_brute
    assert bulletin.net_a_payer > 0
    assert bulletin.net_a_payer < bulletin.total_remuneration_brute  # cotisations non nulles


def test_calcul_periode_alignee_sur_dernier_evp():
    dossier = _dossier_didier()
    bulletin = calculer_bulletin_simule(dossier)
    assert bulletin.periode_debut == dossier.dernier_evp().periode
    assert bulletin.periode_fin.month == bulletin.periode_debut.month
