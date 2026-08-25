"""
rag/app/main.py

Endpoint de recherche RAG minimal sur le corpus CCN SYNTEC (D.6 partiel,
sprint "quelques heures avant réunion"). Pas de Dockerfile pour ce
service à ce stade (cf. consigne) : lancé directement via python sur
l'hôte de la VM, depuis rag/ :

    cd rag
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8003

POST /rag/query {"question": "..."} recherche les 3 passages les plus
proches dans Qdrant (collection "syntec_convention", indexée par
rag/app/ingestion/ingest.py) et les retourne avec leur référence
d'article exacte. Priorité donnée à la fiabilité de cette recherche
sémantique citée plutôt qu'à la synthèse LLM (bonus optionnel, activable
via ?synthese=true, cf. avertissement dans la docstring de
_synthetiser).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from qdrant_client import QdrantClient

from .config import (
    COLLECTION_NAME,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL_SYNTHESE,
    QDRANT_HOST,
    QDRANT_PORT,
)
from .embeddings import get_embedding_async

NB_PASSAGES = 3


class QueryRequest(BaseModel):
    question: str


class Passage(BaseModel):
    article: str
    titre: str
    texte: str
    source: str
    page: int
    score: float


class QueryResponse(BaseModel):
    passages: list[Passage]
    synthese: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=120.0)
    app.state.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="RAG SYNTEC", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "rag"}


async def _synthetiser(question: str, passages: list[Passage], http_client: httpx.AsyncClient) -> str:
    """Synthèse optionnelle via Ollama (bonus, cf. docstring du module).

    N'est appelée que si le client la demande explicitement
    (?synthese=true) : une panne ou une lenteur de ce modèle (14B, plus
    lourd que le modèle d'embeddings) ne doit jamais faire échouer la
    recherche sémantique elle-même, qui est le livrable prioritaire de ce
    sprint.
    """
    contexte = "\n\n".join(
        f"Article {p.article} — {p.titre} :\n{p.texte}" for p in passages
    )
    prompt = (
        "Réponds à la question en te basant UNIQUEMENT sur les articles "
        "de la CCN SYNTEC ci-dessous, en citant précisément le ou les "
        "numéros d'article utilisés.\n\n"
        f"{contexte}\n\nQuestion : {question}\nRéponse :"
    )
    reponse = await http_client.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": OLLAMA_MODEL_SYNTHESE, "prompt": prompt, "stream": False},
    )
    reponse.raise_for_status()
    return reponse.json()["response"].strip()


@app.post("/rag/query", response_model=QueryResponse)
async def query(payload: QueryRequest, synthese: bool = False) -> QueryResponse:
    http_client: httpx.AsyncClient = app.state.http_client
    qdrant: QdrantClient = app.state.qdrant

    vecteur = await get_embedding_async(payload.question, http_client)
    resultats = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=vecteur,
        limit=NB_PASSAGES,
    ).points

    passages = [
        Passage(
            article=r.payload["article"],
            titre=r.payload["titre"],
            texte=r.payload["texte"],
            source=r.payload["source"],
            page=r.payload["page"],
            score=r.score,
        )
        for r in resultats
    ]

    synthese_texte = None
    if synthese and passages:
        synthese_texte = await _synthetiser(payload.question, passages, http_client)

    return QueryResponse(passages=passages, synthese=synthese_texte)
