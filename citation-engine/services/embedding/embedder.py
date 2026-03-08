from sentence_transformers import SentenceTransformer
from functools import lru_cache
from shared.config import get_settings
import numpy as np

settings = get_settings()


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Load once, reuse everywhere."""
    return SentenceTransformer(settings.embedding_model)


def embed(texts: list[str]) -> list[list[float]]:
    """
    multilingual-e5-large expects a prefix:
      - "query: ..." for search input
      - "passage: ..." for documents being indexed
    """
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    return embed([f"query: {text}"])[0]


def embed_passage(text: str) -> list[float]:
    return embed([f"passage: {text}"])[0]


def embed_passages(texts: list[str]) -> list[list[float]]:
    prefixed = [f"passage: {t}" for t in texts]
    return embed(prefixed)
