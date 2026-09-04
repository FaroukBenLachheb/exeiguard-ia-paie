# rag/ — recherche semantique CCN SYNTEC (RAG)

`POST /rag/query {"question": "..."}` recherche les 3 passages les plus
proches dans Qdrant (collection `syntec_convention`) et les retourne avec
leur reference d'article exacte. Bonus optionnel `?synthese=true` (appel
LLM Ollama, voir `app/main.py::_synthetiser`).

## Conteneurise depuis le 2026-09-03 (rag/Dockerfile)

Le service tourne desormais en conteneur Docker (`rag/Dockerfile`,
service compose `rag`), comme les autres services applicatifs. **Ce
n'etait pas le cas jusque-la** : entre le sprint D.6 (commit `20eac05`,
25/08) et cette conteneurisation, `rag/Dockerfile` etait un placeholder
et le service tournait en Python natif sur l'hote de la VM (lance
manuellement via `nohup`), avec `OLLAMA_HOST`/`QDRANT_HOST` surcharges en
`localhost` a la main - une fragilite connue (deux instances possibles
si le processus natif n'etait pas arrete avant de demarrer le
conteneur, cf. historique git de ce fichier et de `rag/app/config.py`).

Consequences pratiques :

- Plus besoin de `venv` manuel ni d'exporter
  `OLLAMA_HOST=localhost` / `QDRANT_HOST=localhost` : les valeurs par
  defaut de `app/config.py` (`llm-server`, `qdrant` - noms de service
  Docker) fonctionnent directement une fois dans le reseau
  docker-compose.
- Demarrage : `docker compose -f docker-compose.dev.yml up -d rag` (dev)
  ou `docker compose up -d rag` (VM cible, `docker-compose.yml`).
- Le port 8000 n'est jamais publie sur l'hote (`expose`, pas `ports`) :
  accessible uniquement depuis les autres conteneurs du reseau compose,
  meme logique que extracteur-evp / compliance-validation /
  integration-sage.

## Corpus (CCN SYNTEC)

Le PDF source
(`docs/architecture/references/convention_collective_syntec.pdf`) n'est
**pas** copie dans l'image : il n'est necessaire qu'a l'ingestion
manuelle (`app/ingestion/ingest.py`), jamais au demarrage du conteneur.
Il est monte en lecture seule par docker-compose au chemin absolu que
calcule `ingest.py`, soit `/docs/architecture/references/` dans le
conteneur. Pour ré-ingerer (ou ingerer pour la premiere fois dans un
environnement neuf) :

```bash
docker compose exec rag python app/ingestion/ingest.py
```

`app/corpus/` (a la racine de `rag/`) reste vide (`.gitkeep`) : ce n'est
pas le corpus reellement utilise, cf. commentaire dans
`docs/architecture/etat_technique_20260826.md`.

## Developpement local hors conteneur

Toujours possible pour deboguer (voir
`docs/architecture/onboarding-technique.md`, section "Un seul service en
local, hors Docker"), a condition de surcharger `OLLAMA_HOST`/
`QDRANT_HOST` en `localhost` (ports publies sur `127.0.0.1` par
`docker-compose.yml`/`docker-compose.dev.yml` pour `llm-server` et
`qdrant`) :

```bash
cd rag
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt -r ../shared/requirements.txt
set OLLAMA_HOST=localhost
set QDRANT_HOST=localhost
uvicorn app.main:app --reload --port 8000
```
