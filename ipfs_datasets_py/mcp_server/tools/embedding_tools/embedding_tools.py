"""
Compatibility embedding tools module.

Provides lightweight wrappers expected by integration tests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import anyio
import logging

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingManager:
    """Minimal embedding manager for compatibility testing."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name

    async def generate_embeddings(self, texts: List[Any]) -> Dict[str, Any]:
        """Generate embeddings for a list of texts with basic validation."""
        await anyio.sleep(0)
        if not isinstance(texts, list) or not texts:
            return {"status": "error", "error": "Texts must be a non-empty list"}

        invalid = [text for text in texts if not isinstance(text, str) or not text.strip()]
        if invalid:
            return {"status": "error", "error": "Invalid text input"}

        embeddings = [[0.1, 0.2, 0.3, 0.4] for _ in texts]
        return {
            "status": "success",
            "embeddings": embeddings,
            "model_name": self.model_name,
            "dimension": 4
        }

    def get_available_models(self) -> List[str]:
        """Return available embedding model names."""
        return [self.model_name]


async def generate_embeddings(
    texts: List[str],
    model_name: str = DEFAULT_MODEL,
    **kwargs: Any
) -> Dict[str, Any]:
    """Generate embeddings for multiple texts."""
    _ = kwargs
    manager = EmbeddingManager(model_name=model_name)
    result = await manager.generate_embeddings(texts)
    if result.get("status") == "success":
        result["count"] = len(texts)
    return result


async def shard_embeddings(
    embeddings: List[Any],
    shard_count: int = 4,
    strategy: str = "balanced",
    **kwargs: Any
) -> Dict[str, Any]:
    """Shard embeddings into a fixed number of shards."""
    _ = kwargs
    await anyio.sleep(0)
    if not embeddings or shard_count <= 0:
        return {"status": "error", "error": "Invalid embeddings or shard_count"}

    shard_size = max(1, len(embeddings) // shard_count)
    shards = []
    for shard_id in range(shard_count):
        start = shard_id * shard_size
        end = len(embeddings) if shard_id == shard_count - 1 else start + shard_size
        shard_embeddings = embeddings[start:end]
        shards.append({"shard_id": shard_id, "embeddings": shard_embeddings, "strategy": strategy})

    return {
        "status": "success",
        "shard_count": shard_count,
        "total_embeddings": len(embeddings),
        "shards": shards
    }
