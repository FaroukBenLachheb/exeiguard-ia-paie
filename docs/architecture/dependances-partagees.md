# Dependances partagees entre services (shared/, db/)

Ce projet est un monorepo multi-services (orchestrateur, extracteur-evp,
compliance-validation, integration-sage, rag, ...) construits chacun dans
leur propre image Docker, mais qui partagent du code Python qui n'est pas
(encore) packagable/installable via pip :

- `shared/schemas/` : modeles Pydantic communs (EVPMensuel, BulletinSalaire,
  ContratTravail, DossierSalarie, ...), destines a etre importes par
  plusieurs services au fur et a mesure de leur developpement.
- `db/` : `database.py` et `models.py` (SQLAlchemy), utilises aujourd'hui
  par l'orchestrateur.

## Le pattern a suivre pour tout nouveau service (D.5+)

Quand un service a besoin de `shared/` et/ou `db/`, son Dockerfile doit :

1. **Builder avec le contexte a la racine du depot**, pas le sous-dossier du
   service (voir `docker-compose.dev.yml` : `context: .`, `dockerfile:
   <service>/Dockerfile`). Sans ca, `COPY shared/ ...` ne peut pas
   fonctionner : `shared/` n'existe pas depuis le sous-dossier du service.

2. **Installer les dependances des deux requirements.txt** (celui du
   service et celui du dossier partage), pas uniquement celui du service :

   ```dockerfile
   COPY <service>/requirements.txt ./requirements.txt
   COPY shared/requirements.txt ./shared-requirements.txt
   RUN pip install --no-cache-dir -r requirements.txt -r shared-requirements.txt
   ```

3. **Copier le(s) dossier(s) partages a cote de `app/`** dans l'image, et
   pas seulement le code du service :

   ```dockerfile
   COPY <service>/app/ ./app/
   COPY shared/ ./shared/
   # + COPY db/ ./db/ si le service a aussi besoin de db/database.py / db/models.py
   ```

4. **Rendre le dossier partage importable** en ajoutant `/app/shared` au
   `PYTHONPATH` de l'image :

   ```dockerfile
   ENV PYTHONPATH=/app/shared
   ```

   Une fois l'image construite, le code applicatif peut simplement faire :

   ```python
   from schemas import EVPMensuel
   ```

   sans avoir a repeter un `sys.path.insert(...)` dans chaque module qui en
   a besoin.

## Pourquoi PYTHONPATH pour shared/, mais sys.path.insert pour db/ ?

`orchestrateur/app/main.py` importe `db/database.py` et `db/models.py` via
un `sys.path.insert(0, ...)` en tete de fichier, avec deux chemins
candidats (cas conteneur `/app/db`, cas depot local `<repo>/db`) : c'est
utile car, a ce jour, seul l'orchestrateur importe `db/`, et ce mecanisme
doit marcher aussi bien en conteneur qu'en execution locale directe
(`uvicorn app.main:app` depuis `orchestrateur/`) sans dependre d'une
variable d'environnement externe.

`shared/schemas`, en revanche, est destine des le depart a etre importe
par **plusieurs services** (extracteur-evp, compliance-validation,
integration-sage, rag). Repeter le meme bloc `sys.path.insert` avec ses
chemins candidats dans chaque `app/main.py` (et dans chaque module qui en
a besoin) serait la meme duplication decouverte service par service que ce
document essaie justement d'eviter. `ENV PYTHONPATH=/app/shared` centralise
ca dans le Dockerfile, une fois par service, sans toucher au code
applicatif. Pour du developpement/tests en local (hors conteneur), definir
`PYTHONPATH` a la main (ou utiliser `shared/venv` et un `pip install -e`
futur si `shared/` est un jour packageable) reste necessaire — voir
`shared/tests/test_schemas.py` pour comment les tests l'importent
aujourd'hui.

## Verifier qu'un import shared/ fonctionne dans une image construite

```bash
docker run --rm <image> python -c "from schemas import EVPMensuel; print('OK')"
```

(Le `PYTHONPATH=/app/shared` de l'image rend le `sys.path.insert` manuel
inutile ici ; il ne reste utile que pour executer un `python -c` isole
contre une image qui n'aurait pas encore ce `ENV`, par exemple pendant un
diagnostic.)

## Fichier .dockerignore

Le contexte de build etant la racine du depot, un `.dockerignore` racine
est necessaire pour eviter que `COPY shared/ ...` n'embarque aussi
`shared/venv/` (environnement virtuel local, non commite mais present sur
disque) dans les images. Voir `.dockerignore` a la racine.
