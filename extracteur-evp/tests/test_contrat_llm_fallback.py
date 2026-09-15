"""
extracteur-evp/tests/test_contrat_llm_fallback.py

Non-régression du bug trouvé en test réel sur le contrat de Julien
(cf. tests/fixtures/cas_14_julien_reel.json) : le fallback LLM avait
fusionné "CADRE" (vraie valeur du champ statut) dans clause_formation,
et "139.00" (vraie valeur du champ heures_mensuelles) dans
duree_engagement_formation_mois. Diagnostic : la fusion elle-même
(app.parsers.contrat_llm_fallback.completer_via_llm) itère déjà sur
resultat.get(nom) par CLÉ nommée, jamais par position/ordre - mais rien
ne validait le TYPE de la valeur renvoyée par le LLM avant de la
fusionner, donc une valeur sémantiquement décalée (mais syntaxiquement
valide pour un autre champ) filait telle quelle jusqu'à ContratTravail
et y provoquait un crash Pydantic brut côté utilisateur.

Ces tests couvrent : la fusion par clé même quand le JSON du LLM revient
dans un ordre différent de celui demandé, le rejet (par champ, pas
globalement) d'une valeur dont le type ne correspond pas au champ visé,
et l'ignorance journalisée d'une clé inconnue renvoyée par le LLM.
"""

import json

import pytest

from app.parsers.contrat_llm_fallback import SCORE_COMPLETE_PAR_LLM, completer_via_llm
from app.parsers.contrat_parser import ChampExtrait

SCORE_NON_TROUVE = 0.0
SEUIL_CONFIANCE_HAUTE = 0.95


def _champ_haute_confiance(valeur):
    return ChampExtrait(valeur, 1.0, "extraction déterministe")


def _champs_type_julien(**a_completer_avec_confiance_basse):
    """Reconstruit un dict de champs proche du cas réel Julien (cf.
    tests/fixtures/cas_14_julien_reel.json) : la plupart des champs sont
    déjà extraits en déterministe avec confiance 1.0 (statut="CADRE",
    heures_mensuelles=139.0 compris) - seuls les champs passés en kwargs
    sont à faible confiance, donc seuls ceux-là partent au LLM."""
    champs = {
        "prenom": _champ_haute_confiance("Julien"),
        "statut": _champ_haute_confiance("CADRE"),
        "heures_mensuelles": _champ_haute_confiance(139.0),
        "poste": _champ_haute_confiance("Ingénieur Système Windows"),
    }
    for nom, valeur_basse_confiance in a_completer_avec_confiance_basse.items():
        champs[nom] = ChampExtrait(valeur_basse_confiance, 0.5, "confiance insuffisante")
    return champs


class _ReponseFausse:
    def __init__(self, corps_json: dict):
        self._corps_json = corps_json

    def raise_for_status(self):
        pass

    def json(self):
        return {"response": json.dumps(self._corps_json)}


class _ClientFaux:
    """Simule httpx.Client : renvoie toujours la même réponse JSON,
    quelle que soit la requête POST - permet de contrôler précisément la
    réponse du LLM sans dépendre d'un vrai Ollama."""

    def __init__(self, corps_json: dict):
        self._corps_json = corps_json

    def post(self, *args, **kwargs):
        return _ReponseFausse(self._corps_json)

    def close(self):
        pass


def test_fusion_par_cle_meme_si_le_llm_reordonne_les_champs():
    """Le JSON retourné par le LLM liste les champs dans un ordre
    DIFFÉRENT de celui envoyé dans le prompt (duree_engagement_formation_mois
    avant clause_formation, nom en dernier) : chaque valeur doit quand
    même atterrir sur sa propre clé, jamais sur celle d'un voisin par
    proximité d'ordre."""
    champs = _champs_type_julien(clause_formation=None, duree_engagement_formation_mois=None, nom=None)

    reponse_reordonnee = {
        "duree_engagement_formation_mois": {"valeur": 12, "citation": "engagement de 12 mois"},
        "clause_formation": {"valeur": "true", "citation": "clause de dédit-formation prévue"},
        "nom": {"valeur": None, "citation": None},
    }

    fusionnes, llm_utilise, completes = completer_via_llm(
        "texte du contrat", champs, client=_ClientFaux(reponse_reordonnee)
    )

    assert llm_utilise is True
    assert fusionnes["clause_formation"].valeur is True
    assert fusionnes["duree_engagement_formation_mois"].valeur == 12
    # Les champs déjà à haute confiance (dont statut="CADRE" et
    # heures_mensuelles=139.0, jamais envoyés au LLM) restent inchangés -
    # exactement le bug réel : ces valeurs ne doivent JAMAIS se retrouver
    # dans clause_formation/duree_engagement_formation_mois.
    assert fusionnes["statut"].valeur == "CADRE"
    assert fusionnes["heures_mensuelles"].valeur == 139.0
    assert fusionnes["clause_formation"].valeur != "CADRE"
    assert fusionnes["duree_engagement_formation_mois"].valeur != 139.0
    assert set(completes) == {"clause_formation", "duree_engagement_formation_mois"}


def test_valeur_type_invalide_rejetee_sans_faire_planter_les_autres_champs():
    """Reproduction du bug réel (cas Julien) : le LLM renvoie "CADRE"
    (valeur d'un autre champ, booléen) pour clause_formation. Doit être
    rejeté (valeur=None, confiance=0, message clair) SANS empêcher la
    fusion normale de duree_engagement_formation_mois à côté."""
    champs = _champs_type_julien(clause_formation=None, duree_engagement_formation_mois=None, nom=None)

    reponse_decalee = {
        "clause_formation": {"valeur": "CADRE", "citation": "Statut : Cadre"},
        "duree_engagement_formation_mois": {"valeur": "139.00", "citation": "139,00 heures"},
        "nom": {"valeur": None, "citation": None},
    }

    fusionnes, llm_utilise, completes = completer_via_llm(
        "texte du contrat", champs, client=_ClientFaux(reponse_decalee)
    )

    assert llm_utilise is True
    champ_rejete = fusionnes["clause_formation"]
    assert champ_rejete.valeur is None
    assert champ_rejete.confiance == SCORE_NON_TROUVE
    assert "compléter manuellement" in champ_rejete.raison

    # "139.00" reste convertible en nombre (int(139.00) = 139) : le
    # garde-fou de type ne prétend pas détecter une incohérence
    # sémantique, seulement empêcher un crash Pydantic de type - la
    # valeur est donc fusionnée mais avec la confiance réduite du LLM,
    # jamais 1.0 (cf. SCORE_COMPLETE_PAR_LLM).
    assert fusionnes["duree_engagement_formation_mois"].valeur == 139
    assert fusionnes["duree_engagement_formation_mois"].confiance == SCORE_COMPLETE_PAR_LLM

    assert "clause_formation" not in completes
    assert "duree_engagement_formation_mois" in completes


def test_cle_inconnue_du_llm_ignoree_sans_planter():
    """Une clé renvoyée par le LLM qui ne correspond à aucun champ demandé
    (nom mal orthographié ou hors périmètre) est ignorée, jamais fusionnée
    par erreur sur un champ voisin."""
    champs = _champs_type_julien(nom=None)

    reponse_avec_cle_inconnue = {
        "nom": {"valeur": "DUPONT", "citation": "DUPONT"},
        "champ_qui_nexiste_pas": {"valeur": "quelque chose", "citation": None},
    }

    fusionnes, llm_utilise, completes = completer_via_llm(
        "texte du contrat", champs, client=_ClientFaux(reponse_avec_cle_inconnue)
    )

    assert llm_utilise is True
    assert fusionnes["nom"].valeur == "DUPONT"
    assert "champ_qui_nexiste_pas" not in fusionnes
    assert completes == ["nom"]


def test_reponse_json_qui_nest_pas_un_objet_est_ignoree_proprement():
    """Une réponse JSON syntaxiquement valide mais qui n'est pas un objet
    (ex. une liste) ne doit jamais faire planter la fusion - dégradation
    propre comme pour un JSON invalide (cf. docstring module)."""
    champs = _champs_type_julien(nom=None)

    class _ClientListeInvalide(_ClientFaux):
        def post(self, *args, **kwargs):
            class _Reponse:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"response": json.dumps(["pas", "un", "objet"])}

            return _Reponse()

    fusionnes, llm_utilise, completes = completer_via_llm(
        "texte du contrat", champs, client=_ClientListeInvalide({})
    )

    assert llm_utilise is False
    assert completes == []
    assert fusionnes["nom"].valeur is None
