"""
Vector Store Management Engine — reusable core module.

Contains ``VectorStoreManager`` extracted from ``vector_store_management.py``.
Import this module directly to use vector-store operations outside of the MCP
tool layer.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional backend imports
# ---------------------------------------------------------------------------

try:
    import faiss  # type: ignore
    FAISS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    FAISS_AVAILABLE = False
    faiss = None  # type: ignore

try:
    from qdrant_client import QdrantClient  # type: ignore
    from qdrant_client.http import models as qdrant_models  # type: ignore
    QDRANT_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    QDRANT_AVAILABLE = False
    QdrantClient = None  # type: ignore
    qdrant_models = None  # type: ignore

try:
    from elasticsearch import Elasticsearch  # type: ignore
    ELASTICSEARCH_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    ELASTICSEARCH_AVAILABLE = False
    Elasticsearch = None  # type: ignore

try:
    from ipfs_datasets_py.embeddings.embeddings_engine import AdvancedIPFSEmbeddings  # type: ignore
    EMBEDDINGS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    EMBEDDINGS_AVAILABLE = False
    AdvancedIPFSEmbeddings = None  # type: ignore

_INDEXES_DIR = "./vector_indexes"


class VectorStoreManager:
    """
    Manages vector store indexes across FAISS, Qdrant, and Elasticsearch backends.

    All methods that require embedding generation or I/O are async; pure
    routing/listing methods are sync.
    """

    def __init__(self, indexes_dir: str = _INDEXES_DIR) -> None:
        """Initialise the manager with the on-disk FAISS index directory."""
        self.indexes_dir = indexes_dir

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        backend: str = "faiss",
        vector_dim: int = 384,
        distance_metric: str = "cosine",
        index_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a vector index on the requested backend."""
        if backend == "faiss":
            return await self._create_faiss_index(
                index_name, documents, vector_dim, distance_metric, index_config
            )
        if backend == "qdrant":
            return await self._create_qdrant_index(
                index_name, documents, vector_dim, distance_metric, index_config
            )
        if backend == "elasticsearch":
            return await self._create_elasticsearch_index(
                index_name, documents, vector_dim, distance_metric, index_config
            )
        return {
            "status": "error",
            "error": f"Unsupported backend: {backend}",
            "supported_backends": ["faiss", "qdrant", "elasticsearch"],
        }

    async def _create_faiss_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        vector_dim: int,
        distance_metric: str,
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create a FAISS vector index."""
        if not FAISS_AVAILABLE:
            return {
                "status": "error",
                "error": "FAISS not available. Install with: pip install faiss-cpu",
            }
        if not EMBEDDINGS_AVAILABLE:
            return {"status": "error", "error": "Embeddings engine not available"}
        try:
            import numpy as np  # type: ignore

            index = (
                faiss.IndexFlatIP(vector_dim)
                if distance_metric in ("cosine", "dot_product")
                else faiss.IndexFlatL2(vector_dim)
            )
            texts = [doc.get("text", "") for doc in documents]
            resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
            engine = AdvancedIPFSEmbeddings(resources, {})
            embeddings = await engine.generate_embeddings(texts, "thenlper/gte-small")
            if distance_metric == "cosine":
                faiss.normalize_L2(embeddings)
            index.add(embeddings)

            index_dir = os.path.join(self.indexes_dir, index_name)
            os.makedirs(index_dir, exist_ok=True)
            faiss.write_index(index, os.path.join(index_dir, "index.faiss"))
            metadata: Dict[str, Any] = {
                "index_name": index_name,
                "backend": "faiss",
                "vector_dim": vector_dim,
                "distance_metric": distance_metric,
                "document_count": len(documents),
                "documents": documents,
            }
            with open(os.path.join(index_dir, "metadata.json"), "w") as fh:
                json.dump(metadata, fh, indent=2)
            return {
                "status": "success",
                "index_name": index_name,
                "backend": "faiss",
                "vector_dim": vector_dim,
                "document_count": len(documents),
                "index_path": index_dir,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error creating FAISS index: {e}")
            return {"status": "error", "error": str(e), "backend": "faiss"}

    async def _create_qdrant_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        vector_dim: int,
        distance_metric: str,
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create a Qdrant collection."""
        if not QDRANT_AVAILABLE:
            return {
                "status": "error",
                "error": "Qdrant client not available. Install with: pip install qdrant-client",
            }
        if not EMBEDDINGS_AVAILABLE:
            return {"status": "error", "error": "Embeddings engine not available"}
        try:
            url = (config or {}).get("url", "localhost")
            port = (config or {}).get("port", 6333)
            client = QdrantClient(host=url, port=port)
            distance_map = {
                "cosine": qdrant_models.Distance.COSINE,
                "euclidean": qdrant_models.Distance.EUCLID,
                "dot_product": qdrant_models.Distance.DOT,
            }
            client.create_collection(
                collection_name=index_name,
                vectors_config=qdrant_models.VectorParams(
                    size=vector_dim,
                    distance=distance_map.get(distance_metric, qdrant_models.Distance.COSINE),
                ),
            )
            texts = [doc.get("text", "") for doc in documents]
            resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
            engine = AdvancedIPFSEmbeddings(resources, {})
            embeddings = await engine.generate_embeddings(texts, "thenlper/gte-small")
            points = [
                qdrant_models.PointStruct(
                    id=i,
                    vector=emb.tolist(),
                    payload={"text": doc.get("text", ""), "metadata": doc.get("metadata", {})},
                )
                for i, (doc, emb) in enumerate(zip(documents, embeddings))
            ]
            client.upsert(collection_name=index_name, points=points)
            return {
                "status": "success",
                "index_name": index_name,
                "backend": "qdrant",
                "vector_dim": vector_dim,
                "document_count": len(documents),
                "collection_name": index_name,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error creating Qdrant index: {e}")
            return {"status": "error", "error": str(e), "backend": "qdrant"}

    async def _create_elasticsearch_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
        vector_dim: int,
        distance_metric: str,
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create an Elasticsearch vector index."""
        if not ELASTICSEARCH_AVAILABLE:
            return {
                "status": "error",
                "error": "Elasticsearch not available. Install with: pip install elasticsearch",
            }
        if not EMBEDDINGS_AVAILABLE:
            return {"status": "error", "error": "Embeddings engine not available"}
        try:
            es_url = (config or {}).get("url", "localhost:9200")
            es = Elasticsearch([es_url])
            mapping = {
                "mappings": {
                    "properties": {
                        "text": {"type": "text"},
                        "vector": {
                            "type": "dense_vector",
                            "dims": vector_dim,
                            "index": True,
                            "similarity": "cosine" if distance_metric == "cosine" else "l2_norm",
                        },
                        "metadata": {"type": "object"},
                    }
                }
            }
            es.indices.create(index=index_name, body=mapping)
            texts = [doc.get("text", "") for doc in documents]
            resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
            engine = AdvancedIPFSEmbeddings(resources, {})
            embeddings = await engine.generate_embeddings(texts, "thenlper/gte-small")
            for i, (doc, emb) in enumerate(zip(documents, embeddings)):
                es.index(
                    index=index_name,
                    id=i,
                    body={
                        "text": doc.get("text", ""),
                        "vector": emb.tolist(),
                        "metadata": doc.get("metadata", {}),
                    },
                )
            es.indices.refresh(index=index_name)
            return {
                "status": "success",
                "index_name": index_name,
                "backend": "elasticsearch",
                "vector_dim": vector_dim,
                "document_count": len(documents),
                "es_index": index_name,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error creating Elasticsearch index: {e}")
            return {"status": "error", "error": str(e), "backend": "elasticsearch"}

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_index(
        self,
        index_name: str,
        query: str,
        backend: str = "faiss",
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Search a vector index for similar documents."""
        if backend == "faiss":
            return await self._search_faiss_index(index_name, query, top_k, config)
        if backend in ("qdrant", "elasticsearch"):
            return {
                "status": "error",
                "error": f"Backend '{backend}' search is not implemented in this build",
                "index_name": index_name,
                "backend": backend,
            }
        return {"status": "error", "error": f"Unsupported backend: {backend}"}

    async def _search_faiss_index(
        self,
        index_name: str,
        query: str,
        top_k: int,
        config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Search a FAISS index."""
        if not FAISS_AVAILABLE:
            return {"status": "error", "error": "FAISS not available"}
        if not EMBEDDINGS_AVAILABLE:
            return {"status": "error", "error": "Embeddings engine not available"}
        try:
            index_dir = os.path.join(self.indexes_dir, index_name)
            faiss_path = os.path.join(index_dir, "index.faiss")
            if not os.path.exists(faiss_path):
                return {"status": "error", "error": f"FAISS index not found: {index_name}"}
            index = faiss.read_index(faiss_path)
            with open(os.path.join(index_dir, "metadata.json")) as fh:
                metadata = json.load(fh)
            resources = {"local_endpoints": [["thenlper/gte-small", "cpu", 512]]}
            engine = AdvancedIPFSEmbeddings(resources, {})
            qemb = await engine.generate_embeddings([query], "thenlper/gte-small")
            q_vec = qemb[0].reshape(1, -1)
            if metadata.get("distance_metric") == "cosine":
                faiss.normalize_L2(q_vec)
            scores, indices = index.search(q_vec, top_k)
            docs = metadata.get("documents", [])
            results = [
                {"document": docs[idx], "score": float(score), "index": int(idx)}
                for score, idx in zip(scores[0], indices[0])
                if idx < len(docs)
            ]
            return {
                "status": "success",
                "query": query,
                "results": results,
                "total_results": len(results),
                "backend": "faiss",
                "index_name": index_name,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error searching FAISS index: {e}")
            return {"status": "error", "error": str(e), "backend": "faiss"}

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_indexes(self, backend: str = "all") -> Dict[str, Any]:
        """List available vector indexes (FAISS only in this build)."""
        try:
            indexes: Dict[str, Any] = {}
            if backend in ("all", "faiss"):
                faiss_indexes: List[Dict[str, Any]] = []
                if os.path.exists(self.indexes_dir):
                    for item in os.listdir(self.indexes_dir):
                        item_path = os.path.join(self.indexes_dir, item)
                        faiss_path = os.path.join(item_path, "index.faiss")
                        if os.path.isdir(item_path) and os.path.exists(faiss_path):
                            meta_path = os.path.join(item_path, "metadata.json")
                            if os.path.exists(meta_path):
                                with open(meta_path) as fh:
                                    meta = json.load(fh)
                                faiss_indexes.append({
                                    "name": item,
                                    "backend": "faiss",
                                    "vector_dim": meta.get("vector_dim"),
                                    "document_count": meta.get("document_count"),
                                    "distance_metric": meta.get("distance_metric"),
                                })
                indexes["faiss"] = faiss_indexes
            return {"status": "success", "backend": backend, "indexes": indexes}
        except OSError as e:
            logger.error(f"Error listing vector indexes: {e}")
            return {"status": "error", "error": str(e), "backend": backend}

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_index(
        self,
        index_name: str,
        backend: str = "faiss",
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Delete a vector index."""
        try:
            if backend == "faiss":
                index_dir = os.path.join(self.indexes_dir, index_name)
                if os.path.exists(index_dir):
                    shutil.rmtree(index_dir)
                    return {
                        "status": "success",
                        "message": f"FAISS index {index_name} deleted",
                        "backend": "faiss",
                    }
                return {
                    "status": "error",
                    "error": f"FAISS index {index_name} not found",
                    "backend": "faiss",
                }

            if backend == "qdrant":
                if not QDRANT_AVAILABLE:
                    return {"status": "error", "error": "Qdrant client not available"}
                url = (config or {}).get("url", "localhost")
                port = (config or {}).get("port", 6333)
                client = QdrantClient(host=url, port=port)
                client.delete_collection(collection_name=index_name)
                return {
                    "status": "success",
                    "message": f"Qdrant collection {index_name} deleted",
                    "backend": "qdrant",
                }

            if backend == "elasticsearch":
                if not ELASTICSEARCH_AVAILABLE:
                    return {"status": "error", "error": "Elasticsearch not available"}
                es_url = (config or {}).get("url", "localhost:9200")
                es = Elasticsearch([es_url])
                es.indices.delete(index=index_name)
                return {
                    "status": "success",
                    "message": f"Elasticsearch index {index_name} deleted",
                    "backend": "elasticsearch",
                }

            return {"status": "error", "error": f"Unsupported backend: {backend}"}

        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Error deleting vector index: {e}")
            return {
                "status": "error",
                "error": str(e),
                "index_name": index_name,
                "backend": backend,
            }


__all__ = [
    "VectorStoreManager",
    "FAISS_AVAILABLE",
    "QDRANT_AVAILABLE",
    "ELASTICSEARCH_AVAILABLE",
    "EMBEDDINGS_AVAILABLE",
]
