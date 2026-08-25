"""
rag/app/ingestion/ingest.py

Ingestion (embeddings + indexation Qdrant) du corpus CCN SYNTEC. Script
manuel, lancé une fois pour indexer le document complet :

    cd rag
    python app/ingestion/ingest.py

(ou depuis la racine du dépôt : python rag/app/ingestion/ingest.py)

Sur la VM, sans Dockerfile pour ce service (cf. consigne du sprint D.6
partiel), ce script tourne directement via python sur l'hôte : Ollama et
Qdrant doivent donc être joignables depuis l'hôte, pas seulement depuis
le réseau docker-compose - voir rag/app/config.py pour le detail
(OLLAMA_HOST/QDRANT_HOST à surcharger en "localhost").

Pour chaque chunk (un par article, cf. chunking.py) : génère un embedding
via Ollama sur le texte "Article X.X — Titre\n\n<corps>" (le titre fait
partie du texte embarqué, il aide la similarité sémantique sur des
questions qui reprennent des mots du titre), puis upsert dans la
collection Qdrant "syntec_convention" avec le payload {article, titre,
texte, source, page}.
"""

from __future__ import annotations

import sys
from pathlib import Path

_INGESTION_DIR = Path(__file__).resolve().parent
_RAG_DIR = _INGESTION_DIR.parents[1]  # rag/ (parent de app/)
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

import httpx  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.models import Distance, PointStruct, VectorParams  # noqa: E402

from app.config import COLLECTION_NAME, QDRANT_HOST, QDRANT_PORT  # noqa: E402
from app.embeddings import get_embedding  # noqa: E402
from app.ingestion.chunking import ArticleChunk, chunker_convention_syntec  # noqa: E402

_PDF = _RAG_DIR.parent / "docs" / "architecture" / "references" / "convention_collective_syntec.pdf"


def _texte_pour_embedding(chunk: ArticleChunk) -> str:
    return f"Article {chunk.article} — {chunk.titre}\n\n{chunk.texte}"


def ingerer(chemin_pdf: Path = _PDF) -> int:
    chunks = chunker_convention_syntec(chemin_pdf)
    if not chunks:
        raise RuntimeError(f"Aucun chunk extrait depuis {chemin_pdf} - vérifier le document.")

    qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    with httpx.Client(timeout=120.0) as http_client:
        # Premier embedding à part : sert à connaître la dimension du
        # vecteur avant de créer la collection Qdrant (dépend du modèle
        # Ollama configuré, cf. app/config.py::OLLAMA_EMBED_MODEL - pas
        # supposée en dur).
        premier_vecteur = get_embedding(_texte_pour_embedding(chunks[0]), http_client)
        dimension = len(premier_vecteur)

        qdrant.recreate_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )

        points = [
            PointStruct(
                id=1,
                vector=premier_vecteur,
                payload={
                    "article": chunks[0].article,
                    "titre": chunks[0].titre,
                    "texte": chunks[0].texte,
                    "source": chunks[0].source,
                    "page": chunks[0].page,
                },
            )
        ]
        for i, chunk in enumerate(chunks[1:], start=2):
            vecteur = get_embedding(_texte_pour_embedding(chunk), http_client)
            points.append(
                PointStruct(
                    id=i,
                    vector=vecteur,
                    payload={
                        "article": chunk.article,
                        "titre": chunk.titre,
                        "texte": chunk.texte,
                        "source": chunk.source,
                        "page": chunk.page,
                    },
                )
            )

        qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

    return len(points)


if __name__ == "__main__":
    nb = ingerer()
    print(f"{nb} chunks indexés dans la collection Qdrant '{COLLECTION_NAME}'.")
