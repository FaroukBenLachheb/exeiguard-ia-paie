"""
integration-sage/tests/conftest.py

Rend le package `app` (integration-sage/app/), `mock`
(integration-sage/mock/) et `shared` (racine du dépôt) importables depuis
les tests. Même pattern que extracteur-evp/tests/conftest.py et
compliance-validation/tests/conftest.py : "integration-sage" contient un
tiret et ne peut donc pas être importé comme package Python, on ajoute
son contenu au path plutôt que d'en faire un package.

Purge de `sys.modules['app']` (et sous-modules) avant l'insertion dans
sys.path : chaque service applicatif expose un package local nommé `app`
au même niveau. Sans cette purge, un `import app...` déjà mis en cache
par la suite de tests d'un autre service (lorsque toutes les suites sont
collectées ensemble depuis la racine du dépôt) ferait résoudre `app` vers
le mauvais service.
"""

import sys
from pathlib import Path

_INTEGRATION_SAGE_DIR = Path(__file__).resolve().parents[1]
_ROOT = _INTEGRATION_SAGE_DIR.parent

for _module_name in list(sys.modules):
    if _module_name == "app" or _module_name.startswith("app."):
        del sys.modules[_module_name]
    if _module_name == "mock" or _module_name.startswith("mock."):
        del sys.modules[_module_name]

for _p in (_ROOT, _INTEGRATION_SAGE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
