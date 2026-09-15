"""
extracteur-evp/app/parsers/contrat_llm_fallback.py

Fallback LLM (Ollama, mistral:7b-instruct-q4_K_M par défaut, cf.
.env.example::OLLAMA_MODEL_FALLBACK) pour les seuls champs du contrat que
l'extraction déterministe (contrat_parser.py) n'a pas su localiser avec
une confiance suffisante (< SEUIL_FALLBACK_LLM). Le LLM n'assiste QUE sur
ces champs précis : un champ déjà extrait avec une confiance suffisante
n'est jamais relu ni remplacé - conforme au principe du projet
(déterministe = source de vérité, LLM = complément, jamais décisionnel).

Dégradation : si Ollama est injoignable, trop lent, ou répond un contenu
non exploitable, cette fonction ne lève JAMAIS d'exception - elle
retourne l'extraction déterministe telle quelle (champs manquants à
None, llm_utilise=False). Le pipeline ne doit pas planter faute de LLM
disponible.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, get_args

import httpx

from .contrat_parser import ChampExtrait

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.schemas.contrat import ContratTravail  # noqa: E402

logger = logging.getLogger(__name__)

SEUIL_FALLBACK_LLM = 0.6

# Mêmes noms de variable d'environnement que rag/app/config.py
# (OLLAMA_HOST/OLLAMA_PORT), pour rester cohérent avec le reste du
# projet - cf. .env.example.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "llm-server")
OLLAMA_PORT = os.environ.get("OLLAMA_PORT", "11434")
OLLAMA_MODEL_FALLBACK = os.environ.get("OLLAMA_MODEL_FALLBACK", "mistral:7b-instruct-q4_K_M")
OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_FALLBACK_TIMEOUT", "60.0"))

# Score attribué à un champ complété par le LLM : toujours < SEUIL_FALLBACK_LLM
# (jamais 1.0, réservé à l'extraction déterministe avec libellé exact) pour
# qu'un champ complété par le LLM reste visuellement distinct côté UI même
# une fois rempli (cf. frontend/app.py, "Complété par le modèle de langage").
SCORE_COMPLETE_PAR_LLM = 0.55

_PROMPT_TEMPLATE = """Tu es un assistant qui complète UNIQUEMENT les champs suivants d'un contrat de travail français, à partir du texte fourni. Réponds STRICTEMENT en JSON avec EXACTEMENT ces clés (jamais d'autre nom, jamais de reformulation), sous la forme :
{{"nom_du_champ": {{"valeur": ..., "citation": "phrase exacte du contrat justifiant la valeur"}}}}

Chaque valeur doit correspondre STRICTEMENT au type indiqué entre parenthèses pour son champ - ne recopie jamais la valeur d'un autre champ ni une information trouvée ailleurs dans le texte sans rapport avec le champ demandé.

Si un champ est introuvable dans le texte, mets "valeur": null et "citation": null. N'invente aucune valeur absente du texte. Ne réponds RIEN d'autre que ce JSON.

Champs à compléter (nom du champ : type attendu) :
{champs}

Texte du contrat :
\"\"\"
{texte}
\"\"\"

JSON :"""

# Libellé du type attendu par champ, inséré dans le prompt pour ancrer
# chaque clé demandée à son propre type (cf. docstring module : sans ce
# rappel explicite par champ, un modèle quantifié faible peut associer
# à une clé une valeur bien réelle du contrat mais qui appartient en fait
# à un autre champ). Dérivé de ContratTravail (shared/schemas/contrat.py),
# jamais dupliqué en dur, pour ne jamais diverger du schéma réel.
_LIBELLES_TYPE = {
    bool: "booléen, true ou false uniquement",
    int: "nombre entier",
    float: "nombre (entier ou décimal)",
    str: "texte court",
}


def _type_attendu(nom_champ: str) -> type | None:
    """Type Python attendu par ContratTravail pour ce champ (Optional[X]
    déballé en X), ou None si le champ n'existe pas sur le schéma."""
    champ = ContratTravail.model_fields.get(nom_champ)
    if champ is None:
        return None
    annotation = champ.annotation
    args = get_args(annotation)
    if args and type(None) in args:
        autres = [a for a in args if a is not type(None)]
        annotation = autres[0] if len(autres) == 1 else annotation
    return annotation


def _description_champs_pour_prompt(noms: list[str]) -> str:
    lignes = []
    for nom in noms:
        attendu = _type_attendu(nom)
        libelle = _LIBELLES_TYPE.get(attendu, "texte") if attendu is not None else "texte"
        lignes.append(f"- {nom} : {libelle}")
    return "\n".join(lignes)


def champs_a_completer(champs: dict[str, ChampExtrait], seuil: float = SEUIL_FALLBACK_LLM) -> list[str]:
    return [nom for nom, c in champs.items() if c.confiance < seuil]


_VALEURS_BOOL_VRAI = {"true", "vrai", "oui", "yes"}
_VALEURS_BOOL_FAUX = {"false", "faux", "non", "no"}


def _normaliser_bool(valeur: object) -> Optional[bool]:
    if isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, str):
        normalisee = valeur.strip().lower()
        if normalisee in _VALEURS_BOOL_VRAI:
            return True
        if normalisee in _VALEURS_BOOL_FAUX:
            return False
    return None


def _normaliser_nombre(valeur: object) -> Optional[float]:
    # bool est une sous-classe d'int en Python (isinstance(True, int) est
    # vrai) : exclu explicitement pour ne jamais accepter un booléen comme
    # valeur numérique valide.
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    if isinstance(valeur, str):
        try:
            return float(valeur.strip().replace(",", "."))
        except ValueError:
            return None
    return None


def _valider_type_champ(nom_champ: str, valeur: object) -> tuple[object, bool]:
    """Valide `valeur` (renvoyée par le LLM) contre le type attendu par
    ContratTravail pour `nom_champ`, AVANT toute fusion (garde-fou
    indépendant de la fusion par clé ci-dessous - cf. docstring module).

    Retourne (valeur_normalisee, valide). Seuls les champs booléens et
    numériques sont contraints ici : un champ texte/date accepte tel quel
    ce que renvoie le LLM (validé plus tard par ContratTravail lui-même)."""
    attendu = _type_attendu(nom_champ)
    if attendu is bool:
        normalisee = _normaliser_bool(valeur)
        return normalisee, normalisee is not None
    if attendu in (int, float):
        normalisee = _normaliser_nombre(valeur)
        if normalisee is None:
            return None, False
        return (int(normalisee) if attendu is int else normalisee), True
    return valeur, True


def completer_via_llm(
    texte_contrat: str,
    champs: dict[str, ChampExtrait],
    client: httpx.Client | None = None,
) -> tuple[dict[str, ChampExtrait], bool, list[str]]:
    """Complète les champs à faible confiance via Ollama.

    Retourne (champs_fusionnes, llm_utilise, noms_des_champs_completes).
    `llm_utilise` est True dès qu'une réponse JSON exploitable a été
    obtenue d'Ollama (même si aucun champ n'a pu être rempli), False si
    Ollama n'a pas été sollicité (rien à compléter) ou si l'appel/le
    parsing a échoué.
    """
    a_completer = champs_a_completer(champs)
    if not a_completer:
        return dict(champs), False, []

    prompt = _PROMPT_TEMPLATE.format(
        champs=_description_champs_pour_prompt(a_completer), texte=texte_contrat[:6000]
    )

    http_client = client or httpx.Client(timeout=OLLAMA_TIMEOUT)
    try:
        try:
            reponse = http_client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": OLLAMA_MODEL_FALLBACK, "prompt": prompt, "stream": False, "format": "json"},
            )
            reponse.raise_for_status()
            brut = reponse.json()["response"]
        except (httpx.HTTPError, KeyError, ValueError):
            return dict(champs), False, []
    finally:
        if client is None:
            http_client.close()

    try:
        resultat = json.loads(brut)
    except json.JSONDecodeError:
        return dict(champs), False, []

    if not isinstance(resultat, dict):
        logger.warning(
            "Fallback LLM : réponse JSON exploitable mais pas un objet (%s) — ignorée", type(resultat).__name__
        )
        return dict(champs), False, []

    # Toute clé renvoyée par le LLM qui ne correspond à aucun champ demandé
    # (nom inconnu, mal orthographié, ou hors périmètre) est ignorée et
    # journalisée - jamais assignée à un champ par proximité/ordre (cf.
    # docstring module : la fusion ci-dessous n'itère QUE sur `a_completer`,
    # jamais sur les clés du JSON retourné).
    cles_inconnues = set(resultat) - set(a_completer)
    if cles_inconnues:
        logger.warning("Fallback LLM : clé(s) inconnue(s) ignorée(s) dans la réponse : %s", sorted(cles_inconnues))

    fusionnes = dict(champs)
    completes: list[str] = []
    for nom in a_completer:
        entree = resultat.get(nom)
        if not isinstance(entree, dict):
            continue
        valeur = entree.get("valeur")
        if valeur is None:
            continue

        # Garde-fou de type AVANT fusion, indépendant de la fusion par clé
        # ci-dessus : une valeur qui ne correspond pas au type attendu par
        # ContratTravail pour ce champ précis (ex. "CADRE" sur un champ
        # booléen) n'est JAMAIS fusionnée - elle ferait planter Pydantic
        # bien plus tard, avec une erreur technique brute côté utilisateur.
        # Appliqué champ par champ : un rejet ici n'affecte pas les autres
        # champs complétés dans la même réponse.
        valeur_validee, valide = _valider_type_champ(nom, valeur)
        if not valide:
            logger.warning(
                "Fallback LLM : valeur rejetée pour %r (type invalide pour ce champ) : %r", nom, valeur
            )
            fusionnes[nom] = ChampExtrait(
                None,
                0.0,
                "Le modèle de langage n'a pas pu déterminer ce champ avec certitude - à compléter manuellement",
            )
            continue

        citation = entree.get("citation")
        raison = f"Complété par le modèle de langage ({OLLAMA_MODEL_FALLBACK})"
        if citation:
            raison += f" — citation : {citation!r}"
        fusionnes[nom] = ChampExtrait(valeur_validee, SCORE_COMPLETE_PAR_LLM, raison)
        completes.append(nom)

    return fusionnes, True, completes
