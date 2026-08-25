"""
compliance-validation/tests/test_rule_engine.py

Teste chacune des 10 règles du Rule Engine (RG-01 à RG-10) contre les 24
cas de tests/fixtures/ (aucune donnée inventée : tout est chargé depuis
les fixtures existantes, générées par scripts/generate_fixtures.py).
cas_21 à cas_24 ont été ajoutés pour exercer les seuils désormais précis
sourcés sur le texte intégral de la CCN SYNTEC (Articles 3.4 et 5.1,
point 2, cf. docs/architecture/references/convention_collective_syntec.pdf).

Pour chaque règle, on vérifie :
- au moins un cas CONFORME ;
- au moins un cas NON CONFORME, sauf quand ce n'est structurellement pas
  possible avec les fixtures actuelles (cf. analyse de couverture en bas
  de fichier) - dans ce cas le test documente explicitement l'absence
  plutôt que de la passer sous silence.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.schemas import ContratTravail, DossierSalarie, EVPMensuel, RuptureContrat

from app.rule_engine.engine import evaluer_toutes_les_regles

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES_DIR = _ROOT / "tests" / "fixtures"


def _charger(cas_id: str) -> DossierSalarie:
    data = json.loads((_FIXTURES_DIR / f"{cas_id}.json").read_text(encoding="utf-8"))
    contrat = ContratTravail(**data["contrat"])
    evp_historique = [EVPMensuel(**data["evp"])] if "evp" in data else []
    rupture = RuptureContrat(**data["rupture"]) if "rupture" in data else None
    return DossierSalarie(
        matricule=data["id"],
        contrat=contrat,
        evp_historique=evp_historique,
        rupture=rupture,
    )


def _resultat(cas_id: str, regle_id: str):
    dossier = _charger(cas_id)
    resultats = evaluer_toutes_les_regles(dossier)
    return next(r for r in resultats if r.regle_id == regle_id)


# ---------------------------------------------------------------------------
# evaluer_toutes_les_regles : garde générique
# ---------------------------------------------------------------------------

def test_evaluer_toutes_les_regles_retourne_les_10_regles():
    dossier = _charger("cas_01_didier_reel")
    resultats = evaluer_toutes_les_regles(dossier)
    ids = {r.regle_id for r in resultats}
    assert ids == {f"RG-{i:02d}" for i in range(1, 11)}
    for r in resultats:
        assert r.source  # jamais vide : chaque règle doit être sourcée


# ---------------------------------------------------------------------------
# RG-01 - Cohérence heures hebdomadaires / heures mensuelles
# ---------------------------------------------------------------------------

def test_rg01_conforme_heures_mensuelles_legales():
    r = _resultat("cas_01_didier_reel", "RG-01")
    assert r.conforme is True


def test_rg01_non_conforme_incoherence_reelle_139h():
    # cas_13/14/15 (Jordan/Julien/Karim) : contrat à 139.00h/mois, écart
    # réel documenté (cf. scripts/generate_fixtures.py), jamais "corrigé"
    # dans les fixtures.
    for cas_id in ("cas_13_jordan_reel", "cas_14_julien_reel", "cas_15_karim_reel"):
        r = _resultat(cas_id, "RG-01")
        assert r.conforme is False, cas_id


# ---------------------------------------------------------------------------
# RG-02 - Cohérence rémunération mensuelle / annuelle
# ---------------------------------------------------------------------------

def test_rg02_conforme_sur_tous_les_cas():
    # cf. analyse de couverture : aucun cas non-conforme n'est possible
    # via les fixtures, la même tolérance étant déjà appliquée par
    # ContratTravail à l'ingestion.
    for chemin in sorted(_FIXTURES_DIR.glob("*.json")):
        r = _resultat(chemin.stem, "RG-02")
        assert r.conforme is True, chemin.stem


# ---------------------------------------------------------------------------
# RG-03 - Cohérence position/coefficient (grille SYNTEC)
# ---------------------------------------------------------------------------

def test_rg03_conforme_grille_cadres_et_etam():
    r = _resultat("cas_01_didier_reel", "RG-03")  # CADRE, 2.2/130
    assert r.conforme is True
    r = _resultat("cas_06_etam_non_cadre", "RG-03")  # ETAM, 1.1/240
    assert r.conforme is True


def test_rg03_non_conforme_coefficient_incoherent():
    # cas_14 (Julien, réel) : position 2.1 mais coefficient 275, incohérent
    # avec la grille SYNTEC (attendu 115) - donnée réelle préservée telle
    # quelle, jamais corrigée dans les fixtures.
    r = _resultat("cas_14_julien_reel", "RG-03")
    assert r.conforme is False

    # cas_16/17 (synthétiques) : même profil position 2.1 / coefficient
    # 130, également incohérent avec la grille (attendu 115) - découvert
    # en exécutant la règle, pas construit pour ce test.
    for cas_id in ("cas_16_periode_essai_en_cours", "cas_17_periode_essai_hors_limite_legale"):
        r = _resultat(cas_id, "RG-03")
        assert r.conforme is False, cas_id


# ---------------------------------------------------------------------------
# RG-04 - Durée de la période d'essai (Article 3.4 CCN SYNTEC)
# ---------------------------------------------------------------------------

def test_rg04_conforme_periode_essai_cadre_dans_la_limite():
    r = _resultat("cas_16_periode_essai_en_cours", "RG-04")
    assert r.conforme is True


def test_rg04_non_conforme_periode_essai_cadre_hors_limite():
    r = _resultat("cas_17_periode_essai_hors_limite_legale", "RG-04")
    assert r.conforme is False


def test_rg04_conforme_periode_essai_etam_coefficient_bas():
    # cas_21 : ETAM coefficient 245, borne [240, 250] -> plafond 2 mois.
    r = _resultat("cas_21_periode_essai_etam_2mois_conforme", "RG-04")
    assert r.conforme is True


def test_rg04_non_conforme_periode_essai_etam_coefficient_haut():
    # cas_22 : ETAM coefficient 300, borne [275, 500] -> plafond 3 mois,
    # periode_essai_mois=4 dépasse ce plafond.
    r = _resultat("cas_22_periode_essai_etam_3mois_hors_limite", "RG-04")
    assert r.conforme is False


# ---------------------------------------------------------------------------
# RG-05 - Contrepartie financière de la clause de non-concurrence
# ---------------------------------------------------------------------------

def test_rg05_conforme_contrepartie_presente():
    r = _resultat("cas_01_didier_reel", "RG-05")
    assert r.conforme is True


def test_rg05_non_applicable_sans_clause():
    r = _resultat("cas_03_nominal_sans_absence", "RG-05")
    assert r.conforme is True
    assert "non applicable" in r.message


# Pas de test "non conforme" pour RG-05 : cf. analyse de couverture, aucun
# cas des fixtures actuelles n'a clause_non_concurrence=True avec une
# contrepartie absente/nulle.


# ---------------------------------------------------------------------------
# RG-06 - Préavis minimum en cas de rupture
# ---------------------------------------------------------------------------

def test_rg06_conforme_demission_etam_preavis_2_mois():
    r = _resultat("cas_18_demission_etam_avec_preavis", "RG-06")
    assert r.conforme is True


def test_rg06_non_conforme_licenciement_cadre_preavis_insuffisant():
    r = _resultat("cas_19_licenciement_cadre_preavis_insuffisant", "RG-06")
    assert r.conforme is False


# ---------------------------------------------------------------------------
# RG-07 - Congés d'ancienneté (règle informative)
# ---------------------------------------------------------------------------

def test_rg07_informative_toujours_conforme():
    for chemin in sorted(_FIXTURES_DIR.glob("*.json")):
        r = _resultat(chemin.stem, "RG-07")
        assert r.conforme is True, chemin.stem


def test_rg07_palier_cinq_ans_un_jour():
    r = _resultat("cas_20_anciennete_six_ans", "RG-07")
    assert "5 ans atteint" in r.message
    assert "dus : 1." in r.message


def test_rg07_palier_dix_ans_deux_jours():
    r = _resultat("cas_23_anciennete_dix_ans", "RG-07")
    assert "10 ans atteint" in r.message
    assert "dus : 2." in r.message


def test_rg07_palier_vingt_ans_quatre_jours():
    r = _resultat("cas_24_anciennete_vingt_ans", "RG-07")
    assert "20 ans atteint" in r.message
    assert "dus : 4." in r.message


def test_rg07_aucun_palier_pour_anciennete_courte():
    r = _resultat("cas_01_didier_reel", "RG-07")
    assert "aucun palier" in r.message
    assert "dus : 0." in r.message


# ---------------------------------------------------------------------------
# RG-08 - RTT par an (accord Soft IT)
# ---------------------------------------------------------------------------

def test_rg08_conforme_sur_tous_les_cas():
    # cf. analyse de couverture : tous les cas des fixtures utilisent la
    # valeur par défaut ACCORD_SOFT_IT (rtt_par_an=10), aucun cas
    # non-conforme disponible.
    for chemin in sorted(_FIXTURES_DIR.glob("*.json")):
        r = _resultat(chemin.stem, "RG-08")
        assert r.conforme is True, chemin.stem


# ---------------------------------------------------------------------------
# RG-09 - Délai et organisme de justification d'absence (accord Soft IT)
# ---------------------------------------------------------------------------

def test_rg09_conforme_sur_tous_les_cas():
    # cf. analyse de couverture : même situation que RG-08, tous les cas
    # utilisent les valeurs par défaut ACCORD_SOFT_IT.
    for chemin in sorted(_FIXTURES_DIR.glob("*.json")):
        r = _resultat(chemin.stem, "RG-09")
        assert r.conforme is True, chemin.stem


# ---------------------------------------------------------------------------
# RG-10 - Cohérence contrat / identification du dossier
# ---------------------------------------------------------------------------

def test_rg10_conforme_evp_corrobore_par_le_contrat():
    r = _resultat("cas_01_didier_reel", "RG-10")
    assert r.conforme is True


def test_rg10_non_applicable_sans_evp():
    # Aucun cas de fixtures n'est sans EVP à ce stade ; ce test documente
    # le comportement attendu en construisant un dossier minimal SANS
    # inventer de nouvelles données métier (mêmes valeurs de contrat que
    # cas_01, simplement sans historique EVP).
    data = json.loads((_FIXTURES_DIR / "cas_01_didier_reel.json").read_text(encoding="utf-8"))
    dossier = DossierSalarie(
        matricule=data["id"],
        contrat=ContratTravail(**data["contrat"]),
        evp_historique=[],
    )
    resultats = evaluer_toutes_les_regles(dossier)
    r = next(res for res in resultats if res.regle_id == "RG-10")
    assert r.conforme is True
    assert "non applicable" in r.message


# ---------------------------------------------------------------------------
# ANALYSE DE COUVERTURE - RG-01 à RG-10 sur les 24 cas de tests/fixtures/
# ---------------------------------------------------------------------------
#
# Résultats obtenus en exécutant evaluer_toutes_les_regles() sur les 24
# fixtures (vérifié programmatiquement, pas estimé à la main). Mise à jour
# suite au sourcing complet sur le texte intégral de la CCN SYNTEC
# (docs/architecture/references/convention_collective_syntec.pdf, avenant
# n°46 du 16 juillet 2021) et à l'ajout de cas_21 à cas_24.
#
# RG-01 (heures hebdo/mensuelles) - sourcing inchangé (Code du travail
# seul, aucun enrichissement CCN trouvé, cf. docstring du module) :
#   - CONFORME  : 21 cas, heures_mensuelles=151.67h
#   - NON CONF. : cas_13_jordan_reel, cas_14_julien_reel, cas_15_karim_reel
#                 (139.00h/mois, incohérence réelle documentée)
#   - Branche EVP (evp.heure_mensuel) : JAMAIS EXERCÉE. Aucune fixture ne
#     renseigne EVPMensuel.heure_mensuel (toujours None) -> gap de fixture
#     identifié, pas une garantie de correction de cette branche de code.
#
# RG-02 (rémunération mensuelle/annuelle) - sourcing enrichi (Article 7.1
# CCN SYNTEC + Code du travail) :
#   - CONFORME  : les 24 cas.
#   - NON CONF. : AUCUN CAS - structurellement impossible avec les
#     fixtures actuelles, car ContratTravail.coherence_remuneration_mensuelle
#     applique déjà la même tolérance (2€) à l'ingestion : un contrat qui
#     violerait RG-02 serait rejeté par Pydantic avant de pouvoir devenir
#     une fixture. Ce n'est pas un manque à combler par une fixture, c'est
#     une garantie déjà assurée en amont.
#
# RG-03 (classification position/coefficient) - sourcing enrichi (Article
# 7.2 + Article 3.2 CCN SYNTEC ; grilles position->coefficient toujours
# hors Annexes I/II, absentes du document, cf. README des références) :
#   - CONFORME  : 19 cas.
#   - NON CONF. : cas_14_julien_reel (2.1/275 réel, incohérent avec 115
#     attendu), cas_16_periode_essai_en_cours et
#     cas_17_periode_essai_hors_limite_legale (2.1/130, incohérent avec
#     115 attendu - découvert en exécutant la règle sur des fixtures
#     conçues pour RG-04, pas pour RG-03).
#   - Statut StatutSalarie.NON_CADRE : jamais exercé, aucune fixture ne
#     l'utilise (seuls CADRE et ETAM apparaissent) -> branche "grille non
#     sourcée" du code non testée.
#   - Branche "position absente de la grille, coefficient dans/hors bornes"
#     (nouvelle, cf. Article 2.1/3.4) : exercée par cas_21/cas_22 (ETAM,
#     coefficients 245/300 dans les bornes ETAM 240-500), mais jamais dans
#     sa variante "hors bornes" -> gap de fixture.
#
# RG-04 (période d'essai, Article 3.4 CCN SYNTEC) - réécrite avec les 3
# seuils exacts (ETAM 240-250 -> 2 mois, ETAM 275-500 -> 3 mois, Cadres
# 95-270 -> 4 mois), le TODO ETAM est supprimé :
#   - CONFORME  : cas_02, cas_03, cas_09, cas_12, cas_16 (cadres, 2 à 4
#     mois) + cas_21 (ETAM coefficient 245, 2 mois <= plafond 2 mois).
#   - NON CONF. : cas_17_periode_essai_hors_limite_legale (cadre, 6 mois
#     > 4) + cas_22_periode_essai_etam_3mois_hors_limite (ETAM coefficient
#     300, 4 mois > plafond 3 mois) - les DEUX bornes (cadre et ETAM haute)
#     sont désormais exercées dans les deux sens.
#   - Branche "hors bornes connues" (coefficient hors 240-250/275-500/95-
#     270) : jamais exercée, aucune fixture ne porte un coefficient hors
#     grille -> gap de fixture mineur.
#
# RG-05 (contrepartie non-concurrence) - sourcing inchangé (jurisprudence +
# accord Soft IT, aucun enrichissement CCN trouvé : le terme "concurrence"
# n'apparaît nulle part dans le texte intégral) :
#   - CONFORME  : 17 cas avec clause + contrepartie Soft IT (6/12 mois).
#   - Non applicable (sans clause) : cas_03, cas_06, cas_11, cas_21, cas_22.
#   - NON CONF. : AUCUN CAS - toujours un vrai gap de fixture (pas une
#     impossibilité structurelle : Pydantic n'impose aucune contrainte sur
#     indemnite_non_concurrence_mois_salaire même si
#     clause_non_concurrence=True), non comblé par cas_21-24 (hors
#     périmètre de cette itération, focalisée sur RG-04/06/07/09).
#   - Branche "alerte valeurs Soft IT différentes" : jamais exercée non
#     plus (toutes les fixtures utilisent exactement 6/12 mois).
#
# RG-06 (préavis rupture, Article 4.2 CCN SYNTEC) - réécrite avec : (a) le
# cas spécial ETAM coefficients 400/450/500 (2 mois quelle que soit
# l'ancienneté) et (b) la restriction explicite aux type_rupture
# "demission"/"licenciement" (l'Article 4.2 ne couvre pas la rupture
# conventionnelle ni la fin de période d'essai, cf. Article 4.1/3.4) :
#   - CONFORME  : cas_18_demission_etam_avec_preavis (ETAM, 2 mois, >= 2
#     ans d'ancienneté).
#   - NON CONF. : cas_19_licenciement_cadre_preavis_insuffisant (cadre, 1
#     mois au lieu de 3).
#   - Non applicable (pas de rupture) : les 22 autres cas.
#   - Branche ETAM < 2 ans (préavis 1 mois) : JAMAIS EXERCÉE, aucune
#     fixture de rupture ETAM avec ancienneté < 2 ans -> gap de fixture.
#   - Branche ETAM coefficient 400/450/500 (préavis fixe 2 mois) : JAMAIS
#     EXERCÉE, aucune fixture de rupture ETAM à ces coefficients -> gap de
#     fixture (c'est exactement le profil du test de généralisation de
#     l'Étape 4, hors dépôt).
#   - Branche "type_rupture hors périmètre Article 4.2" (nouvelle) :
#     JAMAIS EXERCÉE, aucune fixture rupture_conventionnelle ou
#     fin_periode_essai n'existe -> gap de fixture.
#
# RG-07 (congés d'ancienneté, Article 5.1 point 2, informative) - réécrite
# pour retourner le nombre de jours dus (plus seulement le palier) :
#   - Toujours conforme=True par construction (règle informative).
#   - Palier 5 ans (1 jour) : cas_20_anciennete_six_ans.
#   - Palier 10 ans (2 jours) : cas_23_anciennete_dix_ans (nouveau).
#   - Palier 20 ans (4 jours) : cas_24_anciennete_vingt_ans (nouveau).
#   - Palier 15 ans (3 jours) : JAMAIS EXERCÉ, aucune fixture n'atteint ce
#     seuil -> gap de fixture restant (les 3 autres paliers sont désormais
#     couverts).
#   - Aucun palier (0 jour) : les 21 autres cas (ancienneté < 5 ans).
#
# RG-08 (RTT accord Soft IT) - sourcing inchangé (aucun enrichissement CCN
# trouvé, aucun nombre de jours RTT dans le texte de base) :
#   - CONFORME  : les 24 cas (rtt_par_an=10 partout).
#   - NON CONF. : AUCUN CAS - gap de fixture réel, non comblé par cas_21-24.
#
# RG-09 (délai/organisme justification absence, Article 9.1 CCN SYNTEC +
# accord Soft IT) - sourcing enrichi, distingue désormais les deux
# origines dans le message :
#   - CONFORME  : les 24 cas (24h / "H Cube" partout).
#   - NON CONF. : AUCUN CAS - même situation que RG-08, gap de fixture.
#
# RG-10 (cohérence contrat/EVP) - sourcing enrichi (Article 7.4 CCN SYNTEC
# sur les mentions obligatoires nom/prénom du bulletin de paie) :
#   - CONFORME  : les 24 cas (prénom EVP toujours identique au contrat,
#     jamais de CDI avec date de fin d'EVP).
#   - NON CONF. : AUCUN CAS - largement structurel : EVPMensuel.prenom est
#     un champ requis (jamais None), et dans generate_fixtures.py la même
#     variable `prenom` alimente systématiquement contrat ET evp, donc les
#     deux ne peuvent pas diverger par construction des fixtures. La
#     détection d'un matricule EVP seul sans nom/prénom est, elle,
#     structurellement impossible (EVPMensuel.identifiant_minimal_present
#     + prenom non optionnel). Seule la branche "prénom EVP != prénom
#     contrat" pourrait en théorie être non-conforme, mais aucune fixture
#     ne le permet.
#   - test_rg10_non_applicable_sans_evp ci-dessus construit un dossier
#     sans evp_historique (à partir des données déjà existantes de
#     cas_01) pour exercer explicitement la branche "pas d'EVP", seule
#     branche de RG-10 qui restait totalement non testée.
#
# RÉSUMÉ - règles sans aucun cas NON CONFORME dans les fixtures actuelles :
#   RG-02 (impossible par construction, garanti par Pydantic en amont),
#   RG-05, RG-08, RG-09 (gaps de fixtures réels à combler),
#   RG-10 (impossible par construction sur le point EVP seul, gap réel
#   uniquement sur la divergence de prénom).
# RG-04, RG-06 et RG-07 ont gagné des cas NON CONFORME / des branches
# supplémentaires avec cas_21-24, mais gardent chacune au moins une
# branche non exercée (documentée ci-dessus : coefficient hors bornes
# pour RG-03/04, ETAM<2ans et coefficients 400/450/500 et type_rupture
# hors périmètre pour RG-06, palier 15 ans pour RG-07).
# Ces gaps ne sont pas masqués par les tests ci-dessus : chaque test lié
# les documente explicitement en commentaire plutôt que de se contenter
# de vérifier silencieusement le seul cas conforme.
