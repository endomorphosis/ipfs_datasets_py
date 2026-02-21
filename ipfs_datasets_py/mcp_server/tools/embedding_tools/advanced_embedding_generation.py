"""
Advanced / Multimodal Embedding Generation Tools — thin MCP shim.

All business logic lives in ipfs_datasets_py.embeddings.generation_engine.
The ``generate_embedding`` function already supports multimodal dict payloads.
"""
from __future__ import annotations

from ipfs_datasets_py.embeddings.generation_engine import (  # noqa: F401
    generate_embedding,
    generate_batch_embeddings,
    generate_embeddings_from_file,
)
