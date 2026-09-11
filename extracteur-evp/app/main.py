"""
extracteur-evp/app/main.py

Service extracteur-evp :
  GET  /health
  POST /extraire          - parse un fichier EVP mensuel (.xlsx) et score
                             la confiance de chaque ligne extraite.
  POST /extraire-contrat  - parse un contrat de travail (.pdf) par
                             libellé de section, score la confiance de
                             chaque champ, et complète via un fallback
                             LLM (Ollama) les champs sous le seuil de
                             confiance (cf. app/parsers/contrat_parser.py
                             et app/parsers/contrat_llm_fallback.py).

Réutilise app/parsers/excel_parser.py (parse_evp_file) et
app/confidence_scoring.py (score_ligne_evp) tels quels : aucune logique
métier réimplémentée ici, ce module se contente de brancher ce code déjà
testé sur une route HTTP. Même principe pour /extraire-contrat.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder

# Import de confidence_scoring avant excel_parser : confidence_scoring.py
# insère la racine du dépôt dans sys.path (nécessaire pour `from
# shared.schemas import ...`) avant d'importer lui-même excel_parser, ce
# qui garantit que ce dernier trouve `shared` peu importe l'ordre réel
# d'exécution des imports ci-dessous.
from .confidence_scoring import score_ligne_evp
from .parsers.excel_parser import parse_evp_file
from .parsers.contrat_parser import contrat_et_confiances, extraire_contrat, extraire_texte_pdf
from .parsers.contrat_llm_fallback import completer_via_llm

app = FastAPI(title="Extracteur EVP", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "extracteur-evp"}


@app.post("/extraire")
async def extraire(fichier: UploadFile = File(...)) -> dict:
    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(contenu)
        chemin_tmp = Path(tmp.name)

    try:
        try:
            lignes = parse_evp_file(chemin_tmp)
        except Exception as exc:  # noqa: BLE001 - frontière API : tout échec de
            # parsing (classeur corrompu, pas un .xlsx, structure inattendue,
            # cellule DATE manquante...) doit devenir un 400 explicite, pas
            # une 500 générique.
            raise HTTPException(
                status_code=400,
                detail=f"Fichier EVP illisible ou mal formé : {exc}",
            ) from None
    finally:
        chemin_tmp.unlink(missing_ok=True)

    lignes_json = []
    for ligne in lignes:
        score = score_ligne_evp(ligne)
        lignes_json.append(
            {**jsonable_encoder(ligne), "score_confiance": jsonable_encoder(score)}
        )

    return {
        "fichier": fichier.filename,
        "nb_lignes": len(lignes_json),
        "lignes": lignes_json,
    }


@app.post("/extraire-contrat")
async def extraire_contrat_route(fichier: UploadFile = File(...)) -> dict:
    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(contenu)
        chemin_tmp = Path(tmp.name)

    try:
        try:
            champs = extraire_contrat(chemin_tmp)
            texte_contrat = extraire_texte_pdf(chemin_tmp)
        except Exception as exc:  # noqa: BLE001 - frontière API : tout échec de
            # parsing (PDF corrompu, illisible, non textuel...) doit devenir un
            # 400 explicite, pas une 500 générique.
            raise HTTPException(
                status_code=400,
                detail=f"Contrat PDF illisible ou mal formé : {exc}",
            ) from None
    finally:
        chemin_tmp.unlink(missing_ok=True)

    # Fallback LLM sur les seuls champs sous le seuil de confiance
    # (SEUIL_FALLBACK_LLM dans contrat_llm_fallback.py) : dégrade
    # proprement (llm_utilise=False) si Ollama est injoignable, cf.
    # docstring de completer_via_llm.
    champs, llm_utilise, champs_completes = completer_via_llm(texte_contrat, champs)

    contrat, confiances = contrat_et_confiances(champs)

    return {
        "fichier": fichier.filename,
        "contrat": jsonable_encoder(contrat),
        "confiance_par_champ": confiances,
        "llm_utilise": llm_utilise,
        "champs_completes_par_llm": champs_completes,
    }
