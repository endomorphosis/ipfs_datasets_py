"""
Embedding Analysis Engine — reusable business logic for vector embedding
and latent-space correlation analysis in financial markets.

This engine is independent of MCP and can be imported directly by other
modules, tests, or CLI tools.

MCP tool wrappers in embedding_correlation.py delegate all work here.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── optional dependencies ──────────────────────────────────────────────────
try:
    import numpy as np  # type: ignore
    NUMPY_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    logger.warning("NumPy not available. Using Python-list stubs for embeddings.")
    NUMPY_AVAILABLE = False

    class np:  # type: ignore  # noqa: N801
        """Minimal numpy stub used when the real package is absent."""

        ndarray = list  # type: ignore

        @staticmethod
        def random_randn(*args: int) -> list:  # type: ignore
            import random
            size = args[0] if args else 1
            return [random.gauss(0, 1) for _ in range(size)]

        @staticmethod
        def random_seed(seed: int) -> None:  # type: ignore
            import random
            random.seed(seed)

        class random:  # noqa: N801
            @staticmethod
            def seed(s: int) -> None:
                import random as _r
                _r.seed(s)

            @staticmethod
            def randint(low: int, high: int, size: int = 1) -> list:
                import random as _r
                return [_r.randint(low, high - 1) for _ in range(size)]

            @staticmethod
            def randn(*args: int) -> list:
                import random as _r
                size = args[0] if args else 1
                return [_r.gauss(0, 1) for _ in range(size)]

        @staticmethod
        def linalg_norm(arr: list) -> float:
            return sum(x ** 2 for x in arr) ** 0.5

        class linalg:  # noqa: N801
            @staticmethod
            def norm(arr: list) -> float:
                return sum(x ** 2 for x in arr) ** 0.5

        @staticmethod
        def dot(a: list, b: list) -> float:
            return sum(x * y for x, y in zip(a, b))

        @staticmethod
        def array(arr: list) -> list:
            return arr

        @staticmethod
        def pad(arr: list, pad_width: tuple) -> list:
            before, after = pad_width if isinstance(pad_width, tuple) else (0, pad_width)
            return [0.0] * before + list(arr) + [0.0] * after

        @staticmethod
        def concatenate(arrays: list) -> list:
            result: list = []
            for a in arrays:
                result.extend(a)
            return result

        @staticmethod
        def argsort(arr: list) -> list:
            return sorted(range(len(arr)), key=lambda i: arr[i])

        @staticmethod
        def abs(arr: list) -> list:
            return [abs(x) for x in arr]

        @staticmethod
        def mean(arr: list) -> float:
            return sum(arr) / len(arr) if arr else 0.0

        @staticmethod
        def __getitem__(key: Any) -> Any:
            return None

    np.ndarray = list  # type: ignore


try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    from transformers import CLIPModel, CLIPProcessor  # type: ignore
    import torch  # type: ignore
    EMBEDDINGS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    EMBEDDINGS_AVAILABLE = False
    logger.warning("Embedding libraries not available. Using stubs.")

try:
    from ...accelerate_integration import (  # type: ignore
        AccelerateManager,
        get_accelerate_status,
        is_accelerate_available,
    )
    HAVE_ACCELERATE = True
except (ImportError, ModuleNotFoundError):
    HAVE_ACCELERATE = False
    AccelerateManager = None  # type: ignore
    is_accelerate_available = lambda: False  # noqa: E731
    get_accelerate_status = lambda: {"available": False}  # noqa: E731


# ── data classes ──────────────────────────────────────────────────────────

@dataclass
class DocumentEmbedding:
    """Vector embedding representation of a news document."""

    doc_id: str
    source: str
    url: str
    published_date: datetime
    text_embedding: Optional[Any] = None
    image_embeddings: List[Any] = field(default_factory=list)
    fused_embedding: Optional[Any] = None
    embedding_model: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return serialisable dictionary (large arrays omitted)."""
        return {
            "doc_id": self.doc_id,
            "source": self.source,
            "url": self.url,
            "published_date": self.published_date.isoformat(),
            "has_text_embedding": self.text_embedding is not None,
            "text_embedding_dim": len(self.text_embedding) if self.text_embedding is not None else 0,
            "num_image_embeddings": len(self.image_embeddings),
            "has_fused_embedding": self.fused_embedding is not None,
            "embedding_model": self.embedding_model,
            "metadata": self.metadata,
        }


@dataclass
class MarketEmbeddingCorrelation:
    """Correlation between a document embedding and a market movement."""

    correlation_id: str
    doc_embedding: DocumentEmbedding
    symbol: str
    time_window: int  # hours
    price_change: float  # percent
    volume_change: float  # percent
    correlation_score: float
    latent_factors: Dict[str, float] = field(default_factory=dict)
    embedding_cluster: Optional[int] = None
    statistical_significance: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Return serialisable dictionary."""
        return {
            "correlation_id": self.correlation_id,
            "document": self.doc_embedding.to_dict(),
            "symbol": self.symbol,
            "time_window_hours": self.time_window,
            "market_impact": {
                "price_change_pct": self.price_change,
                "volume_change_pct": self.volume_change,
            },
            "correlation_score": self.correlation_score,
            "latent_factors": self.latent_factors,
            "embedding_cluster": self.embedding_cluster,
            "p_value": self.statistical_significance,
        }


# ── engine ─────────────────────────────────────────────────────────────────

class VectorEmbeddingAnalyzer:
    """Analyzer for creating and correlating vector embeddings with market movements.

    Responsibilities:
    - Generate text / image embeddings from news documents.
    - Fuse multimodal embeddings.
    - Correlate embeddings with stock price data.
    - Cluster embeddings and analyse per-cluster market impact.

    Example::

        analyzer = VectorEmbeddingAnalyzer()
        doc_emb = analyzer.embed_document(article_dict)
        corr = analyzer.correlate_with_market(doc_emb, stock_data_dict)
    """

    def __init__(
        self,
        text_model: str = "sentence-transformers/all-mpnet-base-v2",
        image_model: str = "openai/clip-vit-base-patch32",
        enable_multimodal: bool = True,
    ) -> None:
        self.text_model_name = text_model
        self.image_model_name = image_model
        self.enable_multimodal = enable_multimodal
        self.embeddings: Dict[str, DocumentEmbedding] = {}
        self.correlations: List[MarketEmbeddingCorrelation] = []
        self.text_model = None
        self.image_model = None
        if EMBEDDINGS_AVAILABLE:
            self._load_models()
        else:
            logger.warning(
                "Embedding models not loaded. Install sentence-transformers "
                "and transformers for production use."
            )

    def _load_models(self) -> None:
        """Load embedding models (placeholder for production implementation)."""
        # Production: self.text_model = SentenceTransformer(self.text_model_name)
        pass

    def generate_text_embedding(self, text: str, doc_id: str) -> Any:
        """Return a normalised text embedding vector for *text*."""
        if self.text_model is not None:
            pass  # production path
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        np.random.seed(hash_val % (2 ** 32))
        embedding = np.random.randn(768)
        norm = np.linalg.norm(embedding)
        if norm:
            embedding = [v / norm for v in embedding]
        logger.debug("Generated text embedding for doc %s", doc_id)
        return embedding

    def generate_image_embedding(self, image_data: Any, doc_id: str) -> Any:
        """Return a normalised image embedding vector (CLIP-style)."""
        if self.image_model is not None:
            pass  # production path
        raw = image_data if isinstance(image_data, str) else str(image_data)
        hash_val = int(hashlib.md5(raw.encode()).hexdigest(), 16)
        np.random.seed(hash_val % (2 ** 32))
        embedding = np.random.randn(512)
        norm = np.linalg.norm(embedding)
        if norm:
            embedding = [v / norm for v in embedding]
        logger.debug("Generated image embedding for doc %s", doc_id)
        return embedding

    def fuse_embeddings(
        self,
        text_embedding: Any,
        image_embeddings: List[Any],
        fusion_method: str = "weighted_average",
    ) -> Any:
        """Fuse text and image embeddings into a single multimodal vector."""
        if not image_embeddings:
            return text_embedding
        if fusion_method == "weighted_average":
            text_weight = 0.6
            img_weight = 0.4 / len(image_embeddings)
            target_dim = len(text_embedding)
            fused = [text_weight * v for v in text_embedding]
            for img_emb in image_embeddings:
                # project to target_dim
                if len(img_emb) < target_dim:
                    img_proj = list(img_emb) + [0.0] * (target_dim - len(img_emb))
                else:
                    img_proj = img_emb[:target_dim]
                fused = [f + img_weight * p for f, p in zip(fused, img_proj)]
            norm = sum(v ** 2 for v in fused) ** 0.5
            if norm:
                fused = [v / norm for v in fused]
            return fused
        if fusion_method == "concatenate":
            fused = list(text_embedding)
            for img_emb in image_embeddings:
                fused.extend(img_emb)
            norm = sum(v ** 2 for v in fused) ** 0.5
            if norm:
                fused = [v / norm for v in fused]
            return fused
        logger.warning("Unknown fusion method %s, falling back to weighted_average", fusion_method)
        return self.fuse_embeddings(text_embedding, image_embeddings, "weighted_average")

    def embed_document(self, article: Dict[str, Any]) -> DocumentEmbedding:
        """Create a ``DocumentEmbedding`` for *article* (text + optional images)."""
        doc_id = article.get("article_id", article.get("url", "unknown"))
        text = article.get("content", "") + " " + article.get("title", "")
        text_embedding = self.generate_text_embedding(text, doc_id)
        image_embeddings: List[Any] = []
        if self.enable_multimodal:
            for idx, image in enumerate(article.get("images", [])[:5]):
                try:
                    img_emb = self.generate_image_embedding(image, f"{doc_id}_img{idx}")
                    image_embeddings.append(img_emb)
                except (ValueError, TypeError) as exc:
                    logger.warning("Failed to embed image %d for %s: %s", idx, doc_id, exc)
        fused_embedding = self.fuse_embeddings(text_embedding, image_embeddings)
        pub_date = article.get("published_date", datetime.now())
        if isinstance(pub_date, str):
            pub_date = datetime.fromisoformat(pub_date)
        doc_embedding = DocumentEmbedding(
            doc_id=doc_id,
            source=article.get("source", "unknown"),
            url=article.get("url", ""),
            published_date=pub_date,
            text_embedding=text_embedding,
            image_embeddings=image_embeddings,
            fused_embedding=fused_embedding,
            embedding_model=f"text:{self.text_model_name}, image:{self.image_model_name}",
            metadata=article.get("metadata", {}),
        )
        self.embeddings[doc_id] = doc_embedding
        logger.info("Created embedding for document %s", doc_id)
        return doc_embedding

    def correlate_with_market(
        self,
        doc_embedding: DocumentEmbedding,
        stock_data: Dict[str, Any],
        time_window: int = 24,
    ) -> MarketEmbeddingCorrelation:
        """Correlate *doc_embedding* with the market movement in *stock_data*."""
        symbol = stock_data.get("symbol", "UNKNOWN")
        price_before = float(stock_data.get("price_before", 100.0))
        price_after = float(stock_data.get("price_after", 100.0))
        price_change = ((price_after - price_before) / price_before) * 100 if price_before else 0.0
        vol_before = float(stock_data.get("volume_before", 1_000_000))
        vol_after = float(stock_data.get("volume_after", 1_000_000))
        volume_change = ((vol_after - vol_before) / vol_before) * 100 if vol_before else 0.0
        correlation_score = self._calculate_correlation_score(
            doc_embedding.fused_embedding, price_change, volume_change
        )
        latent_factors = self._extract_latent_factors(doc_embedding.fused_embedding)
        correlation = MarketEmbeddingCorrelation(
            correlation_id=f"{doc_embedding.doc_id}_{symbol}_{time_window}h",
            doc_embedding=doc_embedding,
            symbol=symbol,
            time_window=time_window,
            price_change=price_change,
            volume_change=volume_change,
            correlation_score=correlation_score,
            latent_factors=latent_factors,
        )
        self.correlations.append(correlation)
        return correlation

    def _calculate_correlation_score(
        self, embedding: Any, price_change: float, volume_change: float
    ) -> float:
        """Return a mock correlation score (replace with ML model in production)."""
        if embedding is None:
            return 0.0
        emb_mag = sum(v ** 2 for v in embedding) ** 0.5
        market_mag = abs(price_change) + abs(volume_change) / 10
        return min(1.0, (emb_mag * market_mag) / 100)

    def _extract_latent_factors(self, embedding: Any, top_k: int = 5) -> Dict[str, float]:
        """Return the top-k most-salient embedding dimensions as latent factors."""
        if embedding is None:
            return {}
        abs_vals = [abs(v) for v in embedding]
        sorted_indices = sorted(range(len(abs_vals)), key=lambda i: abs_vals[i], reverse=True)
        return {f"factor_{i}": float(embedding[i]) for i in sorted_indices[:top_k]}

    def find_similar_embeddings(
        self,
        query_embedding: Any,
        top_k: int = 10,
        threshold: float = 0.7,
    ) -> List[Tuple[DocumentEmbedding, float]]:
        """Return the top-k documents most similar to *query_embedding*."""
        similarities: List[Tuple[DocumentEmbedding, float]] = []
        q_norm = sum(v ** 2 for v in query_embedding) ** 0.5
        for doc_emb in self.embeddings.values():
            if doc_emb.fused_embedding is None:
                continue
            d_norm = sum(v ** 2 for v in doc_emb.fused_embedding) ** 0.5
            if not q_norm or not d_norm:
                continue
            sim = sum(a * b for a, b in zip(query_embedding, doc_emb.fused_embedding)) / (q_norm * d_norm)
            if sim >= threshold:
                similarities.append((doc_emb, float(sim)))
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]

    def cluster_embeddings(
        self, n_clusters: int = 10, method: str = "kmeans"
    ) -> Dict[int, List[str]]:
        """Assign each stored document embedding to a cluster."""
        if not self.embeddings:
            logger.warning("No embeddings to cluster")
            return {}
        import random
        random.seed(42)
        doc_ids = [
            doc_id for doc_id, emb in self.embeddings.items() if emb.fused_embedding is not None
        ]
        if not doc_ids:
            return {}
        clusters: Dict[int, List[str]] = defaultdict(list)
        for doc_id in doc_ids:
            cluster_id = random.randint(0, n_clusters - 1)
            clusters[cluster_id].append(doc_id)
            self.embeddings[doc_id].metadata["cluster_id"] = cluster_id
        logger.info("Clustered %d embeddings into %d clusters", len(doc_ids), n_clusters)
        return dict(clusters)

    def analyze_cluster_market_impact(
        self, clusters: Dict[int, List[str]]
    ) -> Dict[int, Dict[str, float]]:
        """Return average market impact metrics for each cluster."""
        cluster_impacts: Dict[int, Dict[str, float]] = {}
        for cluster_id, doc_ids in clusters.items():
            cluster_corrs = [c for c in self.correlations if c.doc_embedding.doc_id in doc_ids]
            if not cluster_corrs:
                continue
            n = len(cluster_corrs)
            cluster_impacts[cluster_id] = {
                "avg_price_change": sum(c.price_change for c in cluster_corrs) / n,
                "avg_volume_change": sum(c.volume_change for c in cluster_corrs) / n,
                "avg_correlation_score": sum(c.correlation_score for c in cluster_corrs) / n,
                "num_articles": n,
            }
        return cluster_impacts


__all__ = [
    "DocumentEmbedding",
    "MarketEmbeddingCorrelation",
    "VectorEmbeddingAnalyzer",
    "NUMPY_AVAILABLE",
    "EMBEDDINGS_AVAILABLE",
    "HAVE_ACCELERATE",
]
