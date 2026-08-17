"""
extracteur-evp/tests/conftest.py

Rend le package `app` (extracteur-evp/app/) et `shared` (racine du dépôt)
importables depuis les tests. Nécessaire car le dossier `extracteur-evp`
contient un tiret et ne peut donc pas être importé comme package Python
(`import extracteur-evp` est invalide) : on ajoute son contenu au path
plutôt que d'en faire un package.
"""

import sys
from pathlib import Path

_EXTRACTEUR_EVP_DIR = Path(__file__).resolve().parents[1]
_ROOT = _EXTRACTEUR_EVP_DIR.parent

for _p in (_ROOT, _EXTRACTEUR_EVP_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
