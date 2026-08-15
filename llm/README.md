# llm/ — service LLM (Ollama)

Sert les modeles LLM utilises par le pipeline (fallback d'extraction EVP,
raisonnement compliance/RAG) via [Ollama](https://ollama.com), sur la VM
cible OVH (GPU NVIDIA L4 24 Go). Remplace le plan initial "llama.cpp
CPU-only" suite au changement d'infrastructure ; vLLM a ete ecarte
(decision actee).

Le service compose s'appelle `llm-server` (voir docker-compose.dev.yml et
docker-compose.yml) et tourne l'image `ollama/ollama:latest`.

## Modeles

Deux modeles sont utilises (voir `OLLAMA_MODEL_FALLBACK` /
`OLLAMA_MODEL_COMPLIANCE` dans `.env.example`) :

- `mistral:7b-instruct-q4_K_M` — fallback d'extraction EVP quand le
  parsing direct echoue ou a un score de confiance insuffisant (voir
  `source_extraction` dans `db/models.py`).
- `qwen2.5:14b-instruct-q4_K_M` — raisonnement compliance / RAG (Moteur
  Compliance & Validation).

Une fois le service `llm-server` demarre, telecharger les modeles a
l'interieur du conteneur :

```bash
docker compose -f docker-compose.dev.yml exec llm-server ollama pull mistral:7b-instruct-q4_K_M
docker compose -f docker-compose.dev.yml exec llm-server ollama pull qwen2.5:14b-instruct-q4_K_M
```

Les modeles sont persistes dans le volume nomme `ollama_models`
(`/root/.ollama` dans le conteneur), pas sur le host directement : pas
besoin de les re-telecharger a chaque redemarrage du conteneur.

## Endpoint

Ollama expose un endpoint compatible OpenAI :

```
http://llm-server:11434/v1
```

Accessible uniquement depuis les autres conteneurs du reseau
docker-compose : le port 11434 n'est pas publie sur le host ni ouvert dans
le firewall de la VM. Utilisable avec n'importe quel client compatible
OpenAI (ex. le SDK Python `openai`) en pointant `base_url` vers cette
adresse ; `api_key` peut etre une valeur factice, Ollama ne la verifie pas.

## GPU

Sur la VM cible, la reservation GPU (`deploy.resources.reservations.devices`,
driver `nvidia`) necessite le NVIDIA Container Toolkit installe sur
l'hote. Elle est active dans `docker-compose.yml` (Phase 9) et commentee
dans `docker-compose.dev.yml` (pas de GPU en local).
