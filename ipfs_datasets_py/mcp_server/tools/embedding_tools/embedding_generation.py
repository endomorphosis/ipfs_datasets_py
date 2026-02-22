"""
Embedding Generation Tools — thin MCP shim.

All business logic lives in ipfs_datasets_py.embeddings.generation_engine.
"""
from __future__ import annotations

from ipfs_datasets_py.embeddings.generation_engine import (  # noqa: F401
    generate_embedding,
    generate_batch_embeddings,
    generate_embeddings_from_file,
)


def get_available_tools():
    """Return the list of available embedding tools for MCP registration."""
    return [
        {"name": "generate_embedding", "description": "Generate a single text embedding", "function": generate_embedding},
        {"name": "generate_batch_embeddings", "description": "Generate embeddings for multiple texts", "function": generate_batch_embeddings},
        {"name": "generate_embeddings_from_file", "description": "Generate embeddings from a file", "function": generate_embeddings_from_file},
    ]


# ---------------------------------------------------------------------------
# Backward-compatible legacy class shims
# ---------------------------------------------------------------------------

class EmbeddingGenerationTool:
    """Legacy MCP tool wrapper for embedding generation (backward compat)."""

    name = "generate_embedding"
    description = "Generates a vector embedding for the given text."

    async def execute(self, text: str, **kwargs) -> dict:  # type: ignore[override]
        return await generate_embedding(text, **kwargs)


class BatchEmbeddingTool:
    """Legacy MCP tool wrapper for batch embedding generation (backward compat)."""

    name = "generate_batch_embeddings"
    description = "Generates vector embeddings for a list of texts."

    async def execute(self, texts: list, **kwargs) -> dict:  # type: ignore[override]
        return await generate_batch_embeddings(texts, **kwargs)
