"""
rag/app/embeddings.py

Client minimal pour l'API d'embeddings Ollama (POST /api/embeddings),
partagé entre l'ingestion (rag/app/ingestion/ingest.py, appels
synchrones) et l'endpoint de recherche (rag/app/main.py, appel unique par
requête HTTP, async pour rester cohérent avec FastAPI).
"""

from __future__ import annotations

import httpx

from .config import OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL


def get_embedding(texte: str, client: httpx.Client) -> list[float]:
    reponse = client.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": OLLAMA_EMBED_MODEL, "prompt": texte},
    )
    reponse.raise_for_status()
    return reponse.json()["embedding"]


async def get_embedding_async(texte: str, client: httpx.AsyncClient) -> list[float]:
    reponse = await client.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": OLLAMA_EMBED_MODEL, "prompt": texte},
    )
    reponse.raise_for_status()
    return reponse.json()["embedding"]
