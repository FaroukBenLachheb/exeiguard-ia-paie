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
import os

import httpx

from .contrat_parser import ChampExtrait

SEUIL_FALLBACK_LLM = 0.6

# Mêmes noms de variable d'environnement que rag/app/config.py
# (OLLAMA_HOST/OLLAMA_PORT), pour rester cohérent avec le reste du
# projet - cf. .env.example.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "llm-server")
OLLAMA_PORT = os.environ.get("OLLAMA_PORT", "11434")
OLLAMA_MODEL_FALLBACK = os.environ.get("OLLAMA_MODEL_FALLBACK", "mistral:7b-instruct-q4_K_M")
OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_FALLBACK_TIMEOUT", "30.0"))

# Score attribué à un champ complété par le LLM : toujours < SEUIL_FALLBACK_LLM
# (jamais 1.0, réservé à l'extraction déterministe avec libellé exact) pour
# qu'un champ complété par le LLM reste visuellement distinct côté UI même
# une fois rempli (cf. frontend/app.py, "Complété par le modèle de langage").
SCORE_COMPLETE_PAR_LLM = 0.55

_PROMPT_TEMPLATE = """Tu es un assistant qui complète UNIQUEMENT les champs suivants d'un contrat de travail français, à partir du texte fourni. Réponds STRICTEMENT en JSON, une entrée par champ demandé, sous la forme :
{{"nom_du_champ": {{"valeur": ..., "citation": "phrase exacte du contrat justifiant la valeur"}}}}

Si un champ est introuvable dans le texte, mets "valeur": null et "citation": null. N'invente aucune valeur absente du texte. Ne réponds RIEN d'autre que ce JSON.

Champs à compléter : {champs}

Texte du contrat :
\"\"\"
{texte}
\"\"\"

JSON :"""


def champs_a_completer(champs: dict[str, ChampExtrait], seuil: float = SEUIL_FALLBACK_LLM) -> list[str]:
    return [nom for nom, c in champs.items() if c.confiance < seuil]


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

    prompt = _PROMPT_TEMPLATE.format(champs=", ".join(a_completer), texte=texte_contrat[:6000])

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

    fusionnes = dict(champs)
    completes: list[str] = []
    for nom in a_completer:
        entree = resultat.get(nom)
        if not isinstance(entree, dict):
            continue
        valeur = entree.get("valeur")
        if valeur is None:
            continue
        citation = entree.get("citation")
        raison = f"Complété par le modèle de langage ({OLLAMA_MODEL_FALLBACK})"
        if citation:
            raison += f" — citation : {citation!r}"
        fusionnes[nom] = ChampExtrait(valeur, SCORE_COMPLETE_PAR_LLM, raison)
        completes.append(nom)

    return fusionnes, True, completes
