"""
Sparse Embedding Engine — reusable core for sparse vector operations.

Domain models, enums, and the mock sparse embedding service.
Extracted from mcp_server/tools/sparse_embedding_tools/sparse_embedding_tools.py
so that tests, CLI tools, and the MCP layer can all share the same implementation.

Reusable by:
- MCP server tools: from ipfs_datasets_py.embeddings.sparse_embedding_engine import ...
- CLI commands
- Direct Python imports
"""

from __future__ import annotations

import logging
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SparseModel(Enum):
    """Supported sparse embedding model types."""

    SPLADE = "splade"
    BM25 = "bm25"
    TFIDF = "tfidf"
    BOW = "bow"
    COLBERT = "colbert"


@dataclass
class SparseEmbedding:
    """Represents a sparse embedding vector."""

    indices: List[int]
    values: List[float]
    dimension: int
    sparsity: float
    model: str
    metadata: Dict[str, Any]


class MockSparseEmbeddingService:
    """Mock sparse embedding service for testing and development."""

    def __init__(self) -> None:
        self.indexed_collections: Dict[str, Any] = {}
        self.models: Dict[str, Dict[str, int]] = {
            SparseModel.SPLADE.value: {"dimension": 30522, "vocab_size": 30522},
            SparseModel.BM25.value: {"dimension": 10000, "vocab_size": 10000},
            SparseModel.TFIDF.value: {"dimension": 5000, "vocab_size": 5000},
            SparseModel.BOW.value: {"dimension": 2000, "vocab_size": 2000},
        }
        self.stats: Dict[str, int] = {
            "embeddings_generated": 0,
            "searches_performed": 0,
            "collections_indexed": 0,
            "total_documents": 0,
        }

    def generate_sparse_embedding(
        self,
        text: str,
        model: str = "splade",
        top_k: int = 100,
        normalize: bool = True,
    ) -> SparseEmbedding:
        """Generate a deterministic mock sparse embedding for *text*."""
        model_info = self.models.get(model, self.models[SparseModel.SPLADE.value])
        num_terms = min(top_k, len(text.split()) * 3)
        dimension = model_info["dimension"]

        np.random.seed(hash(text) % 2_147_483_647)
        indices = sorted(np.random.choice(dimension, num_terms, replace=False))
        values = np.random.exponential(0.5, num_terms)

        if normalize:
            norm = float(np.sqrt(np.sum(values ** 2)))
            if norm > 0:
                values = values / norm

        sparsity = 1.0 - (len(indices) / dimension)
        self.stats["embeddings_generated"] += 1

        return SparseEmbedding(
            indices=indices.tolist() if hasattr(indices, "tolist") else list(indices),
            values=values.tolist(),
            dimension=dimension,
            sparsity=sparsity,
            model=model,
            metadata={
                "text_length": len(text),
                "num_terms": num_terms,
                "generated_at": datetime.now().isoformat(),
            },
        )

    def index_sparse_embeddings(
        self,
        collection_name: str,
        documents: List[Dict[str, Any]],
        model: str = "splade",
        index_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build and store a mock sparse index for *collection_name*."""
        config = index_config or {}
        indexed_docs: List[Dict[str, Any]] = []
        total_terms: set = set()

        for i, doc in enumerate(documents):
            text = doc.get("text", "")
            embedding = self.generate_sparse_embedding(text, model)
            indexed_docs.append(
                {
                    "id": doc.get("id", f"doc_{i}"),
                    "text": text,
                    "embedding": embedding,
                    "metadata": doc.get("metadata", {}),
                }
            )
            total_terms.update(embedding.indices)

        avg_sparsity = float(
            np.mean([d["embedding"].sparsity for d in indexed_docs])
        ) if indexed_docs else 0.0

        collection_stats: Dict[str, Any] = {
            "document_count": len(indexed_docs),
            "unique_terms": len(total_terms),
            "average_sparsity": avg_sparsity,
            "index_size_mb": len(indexed_docs) * 0.5,
            "created_at": datetime.now().isoformat(),
        }

        self.indexed_collections[collection_name] = {
            "documents": indexed_docs,
            "model": model,
            "config": config,
            "stats": collection_stats,
        }

        self.stats["collections_indexed"] += 1
        self.stats["total_documents"] += len(indexed_docs)
        return collection_stats

    def sparse_search(
        self,
        query: str,
        collection_name: str,
        model: str = "splade",
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        search_config: Optional[Dict[str, Any]] = None,  # noqa: ARG002
    ) -> List[Dict[str, Any]]:
        """Return top-k mock sparse search results from *collection_name*."""
        if collection_name not in self.indexed_collections:
            return []

        documents = self.indexed_collections[collection_name]["documents"]
        query_embedding = self.generate_sparse_embedding(query, model)
        query_indices = set(query_embedding.indices)

        results: List[Dict[str, Any]] = []
        for doc in documents:
            doc_embedding: SparseEmbedding = doc["embedding"]
            doc_indices = set(doc_embedding.indices)
            intersection = query_indices & doc_indices

            if not intersection:
                continue

            similarity = len(intersection) / max(len(query_indices), len(doc_indices))
            similarity += float(np.random.normal(0, 0.1))
            similarity = max(0.0, min(1.0, similarity))

            if filters:
                doc_meta = doc.get("metadata", {})
                if any(doc_meta.get(k) != v for k, v in filters.items()):
                    continue

            results.append(
                {
                    "id": doc["id"],
                    "text": doc["text"],
                    "score": similarity,
                    "sparse_score_breakdown": {
                        "term_overlap": len(intersection),
                        "query_terms": len(query_indices),
                        "doc_terms": len(doc_indices),
                        "jaccard_similarity": len(intersection)
                        / len(query_indices | doc_indices),
                    },
                    "metadata": doc.get("metadata", {}),
                    "embedding_stats": {
                        "sparsity": doc_embedding.sparsity,
                        "dimension": doc_embedding.dimension,
                        "model": doc_embedding.model,
                    },
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        self.stats["searches_performed"] += 1
        return results[:top_k]

    def get_service_stats(self) -> Dict[str, Any]:
        """Return accumulated service statistics."""
        return {
            **self.stats,
            "indexed_collections": list(self.indexed_collections.keys()),
            "available_models": list(self.models.keys()),
        }


# Module-level singleton used by the MCP tools layer.
_default_service: Optional[MockSparseEmbeddingService] = None


def get_default_sparse_service() -> MockSparseEmbeddingService:
    """Return (creating if needed) the module-level singleton service."""
    global _default_service
    if _default_service is None:
        _default_service = MockSparseEmbeddingService()
    return _default_service


__all__ = [
    "SparseModel",
    "SparseEmbedding",
    "MockSparseEmbeddingService",
    "get_default_sparse_service",
]
