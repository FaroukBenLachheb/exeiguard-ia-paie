"""
rag/app/config.py

Configuration partagée par l'ingestion (rag/app/ingestion/ingest.py) et
l'endpoint de recherche (rag/app/main.py).

Valeurs par défaut alignées sur .env.example (OLLAMA_HOST=llm-server,
OLLAMA_PORT=11434, hostnames internes au réseau docker-compose). Pour le
sprint D.6 (partiel), les scripts tournent en Python directement sur
l'hôte de la VM (pas de Dockerfile rag/, cf. consigne), donc `llm-server`
et `qdrant` (noms DNS internes au réseau Docker) ne sont PAS résolvables
depuis l'hôte : docker-compose.yml publie donc leurs ports sur
127.0.0.1 uniquement (pas d'exposition publique), et OLLAMA_HOST /
QDRANT_HOST doivent être surchargés en "localhost" au lancement sur la VM,
ex :
    OLLAMA_HOST=localhost QDRANT_HOST=localhost python rag/app/ingestion/ingest.py
"""

import os

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "llm-server")
OLLAMA_PORT = os.environ.get("OLLAMA_PORT", "11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
# Modèle de synthèse (bonus optionnel, cf. rag/app/main.py::_synthetiser) :
# même modèle que OLLAMA_MODEL_COMPLIANCE dans .env.example (déjà prévu
# pour le raisonnement compliance/RAG).
OLLAMA_MODEL_SYNTHESE = os.environ.get("OLLAMA_MODEL_SYNTHESE", "qwen2.5:14b-instruct-q4_K_M")
OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))

COLLECTION_NAME = "syntec_convention"
