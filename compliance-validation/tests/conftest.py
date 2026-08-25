"""
compliance-validation/tests/conftest.py

Rend le package `app` (compliance-validation/app/) et `shared` (racine du
dépôt) importables depuis les tests. Nécessaire car le dossier
`compliance-validation` contient un tiret et ne peut donc pas être importé
comme package Python (`import compliance-validation` est invalide) : on
ajoute son contenu au path plutôt que d'en faire un package. Même pattern
que extracteur-evp/tests/conftest.py.
"""

import sys
from pathlib import Path

_COMPLIANCE_VALIDATION_DIR = Path(__file__).resolve().parents[1]
_ROOT = _COMPLIANCE_VALIDATION_DIR.parent

for _p in (_ROOT, _COMPLIANCE_VALIDATION_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
