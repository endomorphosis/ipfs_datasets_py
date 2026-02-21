"""
Enhanced Embedding Tools for MCP Server — thin re-export shim.

Business logic (AdvancedIPFSEmbeddings, EmbeddingConfig, ChunkingConfig)
lives in ipfs_datasets_py.embeddings.embeddings_engine.

Stand-alone embedding functions (generate_embedding, generate_batch_embeddings,
generate_embeddings_from_file) live in ipfs_datasets_py.embeddings.generation_engine.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.embeddings.embeddings_engine import (  # noqa: F401
        AdvancedIPFSEmbeddings,
        EmbeddingConfig,
        ChunkingConfig,
    )
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    AdvancedIPFSEmbeddings = None  # type: ignore[assignment]
    EmbeddingConfig = None  # type: ignore[assignment]
    ChunkingConfig = None  # type: ignore[assignment]

from ipfs_datasets_py.embeddings.generation_engine import (  # noqa: F401
    generate_embedding,
    generate_batch_embeddings,
    generate_embeddings_from_file,
)

# Backward-compat aliases
create_embeddings = generate_embedding
index_dataset = generate_batch_embeddings
search_embeddings = generate_embeddings_from_file


async def chunk_text(text: str, **kwargs: Any) -> Dict[str, Any]:
    """Chunk text using AdvancedIPFSEmbeddings.chunk_text."""
    if not EMBEDDINGS_AVAILABLE:
        return {"status": "error", "error": "Embeddings engine not available"}
    from ipfs_datasets_py.embeddings.embeddings_engine import AdvancedIPFSEmbeddings as _AE, ChunkingConfig as _CC
    eng = _AE()
    cfg = _CC(
        chunk_size=kwargs.get("chunk_size", 512),
        chunk_overlap=kwargs.get("chunk_overlap", 50),
        method=kwargs.get("method", "fixed"),
        n_sentences=kwargs.get("n_sentences", 8),
        step_size=kwargs.get("step_size", 256),
    )
    chunks = eng.chunk_text(text, cfg)
    return {
        "status": "success",
        "original_length": len(text),
        "chunk_count": len(chunks),
        "chunks": [{"text": text[s:e], "start": s, "end": e, "length": e - s} for s, e in chunks],
    }


async def manage_endpoints(action: str, model: str, endpoint: str, **kwargs: Any) -> Dict[str, Any]:
    """Manage embedding endpoints (delegates to AdvancedIPFSEmbeddings)."""
    if not EMBEDDINGS_AVAILABLE:
        return {"status": "error", "error": "Embeddings engine not available"}
    from ipfs_datasets_py.embeddings.embeddings_engine import AdvancedIPFSEmbeddings as _AE
    eng = _AE()
    endpoint_type = kwargs.get("endpoint_type", "tei")
    context_length = kwargs.get("context_length", 512)
    if action == "add":
        _add = getattr(eng, f"add_{endpoint_type}_endpoint", eng.add_tei_endpoint)
        _add(model, endpoint, context_length)
        return {"status": "success", "action": "added", "model": model, "endpoint": endpoint}
    if action == "test":
        available = await eng.test_endpoint(endpoint, model)
        return {"status": "success", "action": "tested", "model": model, "available": available}
    if action in ("list", "status"):
        return {"status": "success", "action": action, "endpoints": eng.get_endpoints(model, endpoint_type)}
    return {"status": "error", "error": f"Unknown action: {action}"}
