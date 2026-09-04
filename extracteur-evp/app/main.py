"""
extracteur-evp/app/main.py

Service extracteur-evp : GET /health, et POST /extraire qui parse un
fichier EVP mensuel (.xlsx) et score la confiance de chaque ligne
extraite. Réutilise app/parsers/excel_parser.py (parse_evp_file) et
app/confidence_scoring.py (score_ligne_evp) tels quels : aucune logique
métier réimplémentée ici, ce module se contente de brancher ce code déjà
testé sur une route HTTP.
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
