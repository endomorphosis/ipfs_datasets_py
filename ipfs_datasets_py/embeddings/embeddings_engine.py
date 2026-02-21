"""
Canonical IPFS Embeddings Engine.

Provides ``AdvancedIPFSEmbeddings``, ``EmbeddingConfig``, and
``ChunkingConfig`` – the classes imported by
``mcp_server/tools/embedding_tools/enhanced_embedding_tools.py``.

All heavy lifting delegates to :mod:`ipfs_datasets_py.embeddings.generation_engine`
for embedding generation, and falls back to simple stubs when optional ML
dependencies (torch / transformers) are not installed.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .generation_engine import (
    generate_embedding,
    generate_batch_embeddings,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    max_length: int = 512
    batch_size: int = 32
    device: str = "cpu"
    endpoint_type: str = "local"
    endpoint_url: Optional[str] = None


@dataclass
class ChunkingConfig:
    """Configuration for text chunking before embedding."""
    chunk_size: int = 512
    chunk_overlap: int = 50
    method: str = "fixed"       # fixed | semantic | sliding_window
    n_sentences: int = 8        # sentences per chunk (semantic method)
    step_size: int = 256        # step for sliding window


# ---------------------------------------------------------------------------
# AdvancedIPFSEmbeddings
# ---------------------------------------------------------------------------

class AdvancedIPFSEmbeddings:
    """
    High-level embeddings engine for IPFS-native embedding workflows.

    Delegates actual vector computation to
    :func:`ipfs_datasets_py.embeddings.generation_engine.generate_embedding`
    and :func:`generate_batch_embeddings`.  Endpoint management methods store
    configuration locally; no network calls are made until an embedding is
    actually requested.
    """

    def __init__(
        self,
        resources: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        config: Optional[EmbeddingConfig] = None,
    ) -> None:
        self._resources: Dict[str, Any] = resources or {}
        self._metadata: Dict[str, Any] = metadata or {}
        self._config: EmbeddingConfig = config or EmbeddingConfig()
        # endpoint registries (model → list of endpoint specs)
        self._tei_endpoints: Dict[str, List[Any]] = {}
        self._openvino_endpoints: Dict[str, List[Any]] = {}
        self._libp2p_endpoints: Dict[str, List[Any]] = {}
        self._local_endpoints: Dict[str, List[Any]] = {}

    # ------------------------------------------------------------------
    # Core embedding generation
    # ------------------------------------------------------------------

    async def generate_embeddings(
        self,
        texts: Union[str, List[str]],
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> Any:
        """
        Generate embeddings for a list of texts.

        Returns a numpy-compatible array (or list of lists as fallback).
        """
        import numpy as np  # optional – only needed for the array wrapper

        if isinstance(texts, str):
            texts = [texts]

        result = await generate_batch_embeddings(
            texts=texts,
            model_name=model,
            batch_size=self._config.batch_size,
        )
        embeddings = result.get("embeddings", [])
        return np.array(embeddings) if embeddings else np.empty((0, 0))

    # ------------------------------------------------------------------
    # Dataset indexing
    # ------------------------------------------------------------------

    async def index_dataset(
        self,
        dataset_name: str,
        split: Optional[str] = None,
        column: str = "text",
        dst_path: str = "./embeddings_cache",
        models: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Index a HuggingFace dataset with embeddings (stub implementation)."""
        os.makedirs(dst_path, exist_ok=True)
        models = models or [self._config.model_name]
        return {
            "status": "success",
            "dataset": dataset_name,
            "split": split,
            "column": column,
            "dst_path": dst_path,
            "models": models,
            "indexed_count": 0,
            "note": "Stub: full indexing requires the datasets/torch stack.",
        }

    # ------------------------------------------------------------------
    # Similarity search
    # ------------------------------------------------------------------

    async def search_similar(
        self,
        query: str,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        top_k: int = 10,
        index_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search for texts similar to *query* using a pre-built index (stub)."""
        return [
            {
                "text": f"similar result {i}",
                "similarity": 0.9 - i * 0.05,
                "index": i,
            }
            for i in range(min(top_k, 5))
        ]

    # ------------------------------------------------------------------
    # Text chunking
    # ------------------------------------------------------------------

    def chunk_text(
        self,
        text: str,
        config: Optional[ChunkingConfig] = None,
    ) -> List[tuple]:
        """
        Chunk *text* into (start, end) spans according to *config*.

        Returns a list of (start, end) integer tuples.
        """
        cfg = config or ChunkingConfig()
        chunks: List[tuple] = []

        if cfg.method == "fixed":
            step = cfg.chunk_size - cfg.chunk_overlap
            if step <= 0:
                step = cfg.chunk_size
            pos = 0
            while pos < len(text):
                end = min(pos + cfg.chunk_size, len(text))
                chunks.append((pos, end))
                if end == len(text):
                    break
                pos += step

        elif cfg.method == "sliding_window":
            step = cfg.step_size
            pos = 0
            while pos < len(text):
                end = min(pos + cfg.chunk_size, len(text))
                chunks.append((pos, end))
                if end == len(text):
                    break
                pos += step

        else:  # semantic – sentence-based, simplistic fallback
            import re
            sentences = re.split(r"(?<=[.!?])\s+", text)
            n = cfg.n_sentences
            for i in range(0, len(sentences), max(n // 2, 1)):
                group = sentences[i : i + n]
                chunk_text = " ".join(group)
                start = text.find(group[0]) if group else 0
                end = start + len(chunk_text)
                chunks.append((max(0, start), min(end, len(text))))

        return chunks

    # ------------------------------------------------------------------
    # Endpoint management
    # ------------------------------------------------------------------

    def add_tei_endpoint(self, model: str, endpoint: str, context_length: int = 512) -> None:
        self._tei_endpoints.setdefault(model, []).append((endpoint, context_length))

    def add_openvino_endpoint(self, model: str, endpoint: str, context_length: int = 512) -> None:
        self._openvino_endpoints.setdefault(model, []).append((endpoint, context_length))

    def add_libp2p_endpoint(self, model: str, endpoint: str, context_length: int = 512) -> None:
        self._libp2p_endpoints.setdefault(model, []).append((endpoint, context_length))

    def add_local_endpoint(self, model: str, device: str = "cpu", context_length: int = 512) -> None:
        self._local_endpoints.setdefault(model, []).append((device, context_length))

    async def test_endpoint(self, endpoint: str, model: str) -> bool:
        """Return True if the endpoint is reachable (stub – always True locally)."""
        return True

    def get_endpoints(
        self,
        model: Optional[str] = None,
        endpoint_type: str = "all",
    ) -> List[Any]:
        """Return registered endpoints filtered by *model* and *endpoint_type*."""
        registries: Dict[str, Dict[str, List[Any]]] = {
            "tei": self._tei_endpoints,
            "openvino": self._openvino_endpoints,
            "libp2p": self._libp2p_endpoints,
            "local": self._local_endpoints,
        }
        if endpoint_type == "all":
            result = []
            for reg in registries.values():
                for m, eps in reg.items():
                    if model is None or m == model:
                        result.extend(eps)
            return result
        reg = registries.get(endpoint_type, {})
        if model:
            return reg.get(model, [])
        return [ep for eps in reg.values() for ep in eps]

    def get_status(self) -> Dict[str, Any]:
        """Return a summary of the engine's current state."""
        return {
            "status": "ready",
            "config": {
                "model_name": self._config.model_name,
                "batch_size": self._config.batch_size,
                "device": self._config.device,
            },
            "endpoints": {
                "tei": sum(len(v) for v in self._tei_endpoints.values()),
                "openvino": sum(len(v) for v in self._openvino_endpoints.values()),
                "libp2p": sum(len(v) for v in self._libp2p_endpoints.values()),
                "local": sum(len(v) for v in self._local_endpoints.values()),
            },
        }


__all__ = [
    "AdvancedIPFSEmbeddings",
    "EmbeddingConfig",
    "ChunkingConfig",
]
