"""
compliance-validation/tests/test_rule_engine.py

Teste chacune des 10 règles du Rule Engine (RG-01 à RG-10) contre les 29
cas de tests/fixtures/ (aucune donnée inventée : tout est chargé depuis
les fixtures existantes, générées par scripts/generate_fixtures.py).
cas_21 à cas_24 ont été ajoutés pour exercer les seuils désormais précis
sourcés sur le texte intégral de la CCN SYNTEC (Articles 3.4 et 5.1,
point 2, cf. docs/architecture/references/convention_collective_syntec.pdf).
cas_25 à cas_29 comblent les derniers trous de couverture identifiés lors
d'un audit empirique dédié (RG-06 ETAM <2 ans et coefficient 400/450/500,
RG-07 palier 15 ans, RG-08 et RG-09 non conformes).

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


def test_rg06_conforme_demission_etam_moins_deux_ans_preavis_1_mois():
    # cas_25 : branche ETAM < 2 ans (1 mois), jamais exercée par cas_18
    # (qui porte une ancienneté >= 2 ans).
    r = _resultat("cas_25_demission_etam_moins_deux_ans", "RG-06")
    assert r.conforme is True
    assert "1 mois (ETAM" in r.message


def test_rg06_conforme_licenciement_etam_coefficient_450_preavis_fixe():
    # cas_26 : cas spécial "coefficients 400/450/500, quelle que soit
    # l'ancienneté" de l'Article 4.2 - ancienneté volontairement < 2 ans
    # (8 mois) pour prouver que c'est le coefficient qui prime, formalisé
    # en fixture après avoir été confirmé par un diagnostic scratch non
    # commité lors du test de généralisation précédent.
    r = _resultat("cas_26_licenciement_etam_coefficient_450", "RG-06")
    assert r.conforme is True
    assert "coefficient 450, quelle que soit l'ancienneté" in r.message


# Pas de test pour la branche "type_rupture hors périmètre Article 4.2"
# (rupture_conventionnelle / fin_periode_essai) : cf. analyse de
# couverture, aucune fixture de ce type n'existe encore.


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


def test_rg07_palier_quinze_ans_trois_jours():
    r = _resultat("cas_27_anciennete_quinze_ans", "RG-07")
    assert "15 ans atteint" in r.message
    assert "dus : 3." in r.message


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

def test_rg08_conforme_valeur_par_defaut_accord_soft_it():
    r = _resultat("cas_01_didier_reel", "RG-08")
    assert r.conforme is True


def test_rg08_non_conforme_rtt_divergent():
    # cas_28 : rtt_par_an=8, volontairement divergent des 10 jours de
    # l'accord Soft IT (pas une observation terrain, cf. commentaire dans
    # scripts/generate_fixtures.py).
    r = _resultat("cas_28_rtt_non_conforme", "RG-08")
    assert r.conforme is False


# ---------------------------------------------------------------------------
# RG-09 - Délai et organisme de justification d'absence (accord Soft IT)
# ---------------------------------------------------------------------------

def test_rg09_conforme_valeur_par_defaut_accord_soft_it():
    r = _resultat("cas_01_didier_reel", "RG-09")
    assert r.conforme is True


def test_rg09_non_conforme_delai_divergent():
    # cas_29 : delai_justification_absence_heures=48, volontairement
    # divergent des 24h (Article 9.1 CCN SYNTEC / accord Soft IT), pas une
    # observation terrain (cf. commentaire dans scripts/generate_fixtures.py).
    r = _resultat("cas_29_delai_justification_non_conforme", "RG-09")
    assert r.conforme is False


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
# ANALYSE DE COUVERTURE - RG-01 à RG-10 sur les 29 cas de tests/fixtures/
# ---------------------------------------------------------------------------
#
# Résultats obtenus en exécutant evaluer_toutes_les_regles() sur les 29
# fixtures (vérifié programmatiquement, pas estimé à la main). Mise à jour
# après l'audit de couverture dédié qui a suivi le sourcing complet sur le
# texte intégral de la CCN SYNTEC
# (docs/architecture/references/convention_collective_syntec.pdf, avenant
# n°46 du 16 juillet 2021) : cas_25 à cas_29 comblent 5 des gaps identifiés.
# Chaque branche listée ci-dessous est explicitement marquée "exercée par
# cas_XX" ou "gap restant, raison : ...".
#
# RG-01 (heures hebdo/mensuelles) - sourcing inchangé (Code du travail
# seul, aucun enrichissement CCN trouvé, cf. docstring du module) :
#   - CONFORME  : exercée par cas_01 (et 24 autres cas, heures_mensuelles=
#     151.67h).
#   - NON CONF. : exercée par cas_13/14/15 (139.00h/mois, incohérence
#     réelle documentée).
#   - Branche EVP (evp.heure_mensuel) : gap restant, raison : aucune des
#     29 fixtures ne renseigne EVPMensuel.heure_mensuel (toujours None) -
#     hors périmètre de cet audit (focalisé sur RG-06/07/08/09).
#
# RG-02 (rémunération mensuelle/annuelle) - sourcing enrichi (Article 7.1
# CCN SYNTEC + Code du travail) :
#   - CONFORME  : exercée par les 29 cas.
#   - NON CONF. : gap structurel, raison : ContratTravail.
#     coherence_remuneration_mensuelle applique déjà la même tolérance (2€)
#     à l'ingestion, un contrat qui violerait RG-02 serait rejeté par
#     Pydantic avant de pouvoir devenir une fixture - PAS un manque à
#     combler, une garantie déjà assurée en amont.
#
# RG-03 (classification position/coefficient) - sourcing enrichi (Article
# 7.2 + Article 3.2 CCN SYNTEC ; grilles position->coefficient toujours
# hors Annexes I/II, absentes du document, cf. README des références) :
#   - CONFORME  : exercée par cas_01 (CADRE, 2.2/130) et cas_06 (ETAM,
#     1.1/240), parmi 19 cas au total.
#   - NON CONF. : exercée par cas_14_julien_reel (2.1/275 réel), cas_16 et
#     cas_17 (2.1/130, découvert incidemment sur des fixtures conçues pour
#     RG-04).
#   - Branche "position absente, coefficient DANS les bornes" : exercée
#     par cas_21/22/25/26 (ETAM, coefficients 245/300/245/450 dans les
#     bornes ETAM 240-500).
#   - Branche "position absente, coefficient HORS bornes" : gap restant,
#     raison : aucune fixture ne porte un coefficient hors 95-270 (cadre)
#     ou 240-500 (ETAM) - hors périmètre de cet audit.
#   - Statut StatutSalarie.NON_CADRE : gap restant, raison : aucune
#     fixture n'utilise ce statut (seuls CADRE et ETAM apparaissent).
#
# RG-04 (période d'essai, Article 3.4 CCN SYNTEC) :
#   - CONFORME cadre (2-4 mois) : exercée par cas_02, cas_03, cas_09,
#     cas_12, cas_16.
#   - NON CONF. cadre (>4 mois) : exercée par cas_17.
#   - CONFORME ETAM 240-250 (2 mois) : exercée par cas_21.
#   - NON CONF. ETAM 275-500 (>3 mois) : exercée par cas_22.
#   - Branche "hors bornes connues" : gap restant, raison : aucune fixture
#     ne porte un coefficient hors grille - hors périmètre de cet audit.
#
# RG-05 (contrepartie non-concurrence) - sourcing inchangé (jurisprudence +
# accord Soft IT, aucun enrichissement CCN trouvé : le terme "concurrence"
# n'apparaît nulle part dans le texte intégral) :
#   - CONFORME  : CONFIRMÉ exercée par cas_01_didier_reel et
#     cas_02_sindhuja_reel (clause=True, duree=12, indemnite=6) - vérifié
#     empiriquement lors de l'audit de cette itération ; déjà testé par
#     test_rg05_conforme_contrepartie_presente avant cet audit, donc AUCUNE
#     nouvelle fixture nécessaire ici (contrairement à ce que suggérerait
#     une lecture rapide de l'analyse précédente).
#   - Non applicable (sans clause) : exercée par cas_03, cas_06, cas_11,
#     cas_21, cas_22, cas_25, cas_26.
#   - NON CONF. : gap restant, raison : aucune fixture n'a
#     clause_non_concurrence=True avec une contrepartie absente/nulle -
#     PAS structurellement impossible (Pydantic n'impose aucune contrainte
#     sur indemnite_non_concurrence_mois_salaire même si
#     clause_non_concurrence=True), mais explicitement HORS PÉRIMÈTRE de
#     cette itération (la liste de fixtures demandée ne comportait pas de
#     cas RG-05 non conforme) : reste à combler dans une itération future.
#   - Branche "alerte valeurs Soft IT différentes" : gap restant, même
#     raison (toutes les fixtures utilisent exactement 6/12 mois).
#
# RG-06 (préavis rupture, Article 4.2 CCN SYNTEC) :
#   - CONFORME ETAM >= 2 ans (2 mois) : exercée par cas_18.
#   - NON CONF. cadre (préavis insuffisant) : exercée par cas_19.
#   - CONFORME ETAM < 2 ans (1 mois) : exercée par cas_25 (nouveau -
#     ancienneté 12 mois, préavis 1 mois).
#   - CONFORME ETAM coefficient 400/450/500 ("quelle que soit
#     l'ancienneté") : exercée par cas_26 (nouveau - coefficient 450,
#     ancienneté 8 mois < 2 ans, préavis 2 mois ; confirme que c'est bien
#     le coefficient qui prime, pas l'ancienneté).
#   - Branche "type_rupture hors périmètre Article 4.2"
#     (rupture_conventionnelle / fin_periode_essai) : gap restant, raison :
#     aucune fixture de ce type n'existe - la liste de fixtures demandée
#     pour cette itération ne le couvrait pas.
#   - Branche NON CONFORME pour ETAM (préavis ETAM insuffisant) : gap
#     restant, raison : cas_18/25/26 sont tous conformes côté ETAM, seul
#     cas_19 (cadre) est non conforme.
#
# RG-07 (congés d'ancienneté, Article 5.1 point 2, informative) :
#   - Toujours conforme=True par construction (règle informative).
#   - Palier 5 ans (1 jour) : exercée par cas_20.
#   - Palier 10 ans (2 jours) : exercée par cas_23.
#   - Palier 15 ans (3 jours) : exercée par cas_27 (nouveau).
#   - Palier 20 ans (4 jours) : exercée par cas_24.
#   - Aucun palier (0 jour) : exercée par cas_01 et la majorité des autres
#     cas (ancienneté < 5 ans).
#   - Les 4 paliers CCN SYNTEC (5/10/15/20 ans) sont désormais TOUS
#     exercés : plus aucun gap sur cette règle.
#
# RG-08 (RTT accord Soft IT) - sourcing inchangé (aucun enrichissement CCN
# trouvé, aucun nombre de jours RTT dans le texte de base) :
#   - CONFORME  : exercée par cas_01 (et 27 autres cas, rtt_par_an=10).
#   - NON CONF. : exercée par cas_28 (nouveau - rtt_par_an=8, volontairement
#     divergent, pas une observation terrain).
#   - Plus aucun gap sur cette règle.
#
# RG-09 (délai/organisme justification absence, Article 9.1 CCN SYNTEC +
# accord Soft IT) - sourcing enrichi, distingue les deux origines dans le
# message :
#   - CONFORME  : exercée par cas_01 (et 27 autres cas, 24h / "H Cube").
#   - NON CONF. : exercée par cas_29 (nouveau - delai=48h, volontairement
#     divergent, pas une observation terrain).
#   - Branche "organisme non renseigné" (indépendante du délai) : gap
#     restant, raison : aucune fixture n'a organisme_justification_absence
#     vide/None - hors périmètre de cet audit.
#   - Plus aucun gap sur la branche délai de cette règle.
#
# RG-10 (cohérence contrat/EVP) - sourcing enrichi (Article 7.4 CCN SYNTEC
# sur les mentions obligatoires nom/prénom du bulletin de paie) :
#   - CONFORME  : exercée par les 29 cas (prénom EVP toujours identique au
#     contrat, jamais de CDI avec date de fin d'EVP).
#   - Non applicable (pas d'EVP) : exercée par test_rg10_non_applicable_sans_evp
#     (dossier construit à partir de cas_01, sans evp_historique).
#   - NON CONF. : gap structurel, raison : EVPMensuel.prenom est un champ
#     requis (jamais None), et dans generate_fixtures.py la même variable
#     `prenom` alimente systématiquement contrat ET evp, donc les deux ne
#     peuvent pas diverger par construction des fixtures ; la détection
#     d'un matricule EVP seul sans nom/prénom est, elle, structurellement
#     impossible (EVPMensuel.identifiant_minimal_present + prenom non
#     optionnel). Seule la branche "prénom EVP != prénom contrat" pourrait
#     en théorie être non-conforme, mais aucune fixture ne le permet - ce
#     serait une fixture "corrompue" au sens propre, pas un cas réaliste.
#
# RÉSUMÉ FINAL - gaps réels restants (hors garanties structurelles) :
#   - RG-01 : branche evp.heure_mensuel non exercée.
#   - RG-03/RG-04 : branche "coefficient hors bornes connues" non exercée.
#   - RG-03 : statut NON_CADRE non exercé.
#   - RG-05 : branche NON CONFORME (contrepartie absente) et branche
#     "alerte valeurs Soft IT différentes" non exercées - EXPLICITEMENT
#     laissées hors périmètre de cette itération (pas dans la liste de
#     fixtures demandée), à traiter dans une itération dédiée à RG-05.
#   - RG-06 : branche "type_rupture hors périmètre" (rupture
#     conventionnelle / fin de période d'essai) et branche NON CONFORME
#     côté ETAM non exercées.
#   - RG-09 : branche "organisme non renseigné" non exercée.
# Gaps structurellement impossibles à combler par une fixture (garanties
# déjà assurées ailleurs, pas des manques) : RG-02 non-conforme (Pydantic),
# RG-10 non-conforme sur le point matricule seul (Pydantic).
# Gaps désormais COMBLÉS par cas_25-29 : RG-06 ETAM<2ans, RG-06 coefficient
# 400/450/500, RG-07 palier 15 ans, RG-08 non conforme, RG-09 non conforme.
# Aucun de ces gaps restants n'est masqué : chaque règle listée ci-dessus
# documente explicitement ce qui est exercé et ce qui ne l'est pas, plutôt
# que de se contenter de vérifier silencieusement un seul cas conforme.
