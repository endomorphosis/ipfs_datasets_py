"""
Vector Embedding & Latent Space Correlation Analysis for Financial Markets.
(MCP tool wrapper — business logic lives in embedding_analysis_engine.py)

MCP tool functions in this module:
- analyze_embedding_market_correlation
- find_predictive_embedding_patterns
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Re-export engine types so existing importers keep working without changes.
from .embedding_analysis_engine import (  # noqa: F401
    DocumentEmbedding,
    MarketEmbeddingCorrelation,
    VectorEmbeddingAnalyzer,
)


# ── MCP Tool Functions ─────────────────────────────────────────────────────

def analyze_embedding_market_correlation(
    news_articles_json: str,
    stock_data_json: str,
    enable_multimodal: bool = True,
    time_window: int = 24,
    n_clusters: int = 10,
) -> str:
    """Analyse correlation between news embeddings and market movements.

    Args:
        news_articles_json: JSON string with news articles.
        stock_data_json: JSON string with stock data.
        enable_multimodal: Enable text + image embedding fusion.
        time_window: Time window in hours for market impact.
        n_clusters: Number of clusters for pattern discovery.

    Returns:
        JSON string with correlation analysis results.
    """
    try:
        articles = json.loads(news_articles_json)
        stock_data = json.loads(stock_data_json)

        analyzer = VectorEmbeddingAnalyzer(enable_multimodal=enable_multimodal)

        embeddings_created = 0
        for article in articles:
            try:
                analyzer.embed_document(article)
                embeddings_created += 1
            except (KeyError, ValueError, TypeError) as exc:
                logger.error("Failed to embed article: %s", exc)

        correlations = []
        for article in articles:
            doc_id = article.get("article_id", article.get("url"))
            if doc_id not in analyzer.embeddings:
                continue
            doc_emb = analyzer.embeddings[doc_id]
            for stock in stock_data:
                try:
                    corr = analyzer.correlate_with_market(doc_emb, stock, time_window=time_window)
                    correlations.append(corr.to_dict())
                except (KeyError, ValueError, TypeError) as exc:
                    logger.error("Correlation failed: %s", exc)

        clusters = analyzer.cluster_embeddings(n_clusters=n_clusters)
        cluster_impacts = analyzer.analyze_cluster_market_impact(clusters)

        result = {
            "success": True,
            "analysis": {
                "embeddings_created": embeddings_created,
                "correlations_analyzed": len(correlations),
                "clusters_found": len(clusters),
                "multimodal_enabled": enable_multimodal,
                "time_window_hours": time_window,
            },
            "correlations": correlations[:100],
            "clusters": {
                str(k): {"doc_count": len(v), "impact": cluster_impacts.get(k, {})}
                for k, v in clusters.items()
            },
            "top_correlations": sorted(
                correlations,
                key=lambda x: abs(x.get("correlation_score", 0)),
                reverse=True,
            )[:10],
        }
        return json.dumps(result, indent=2)

    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.error("Embedding correlation analysis failed: %s", exc, exc_info=True)
        return json.dumps({"success": False, "error": str(exc)})


def find_predictive_embedding_patterns(
    historical_embeddings_json: str,
    min_correlation: float = 0.5,
    lookback_days: int = 30,
) -> str:
    """Find predictive patterns in embedding latent spaces.

    Args:
        historical_embeddings_json: JSON with historical embedding-market pairs.
        min_correlation: Minimum correlation threshold.
        lookback_days: Days of history to analyse.

    Returns:
        JSON string with discovered patterns.
    """
    try:
        json.loads(historical_embeddings_json)  # validate input
        result = {
            "success": True,
            "note": "Placeholder. Implement ML pattern discovery in production.",
            "parameters": {
                "min_correlation": min_correlation,
                "lookback_days": lookback_days,
            },
            "patterns_found": 0,
            "recommendations": [
                "Train LSTM on embedding sequences + market data",
                "Use attention mechanisms to identify important latent dimensions",
                "Cluster embeddings and find cluster-specific price patterns",
                "Apply causal inference to embedding features",
            ],
        }
        return json.dumps(result, indent=2)

    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.error("Pattern discovery failed: %s", exc, exc_info=True)
        return json.dumps({"success": False, "error": str(exc)})


__all__ = [
    "DocumentEmbedding",
    "MarketEmbeddingCorrelation",
    "VectorEmbeddingAnalyzer",
    "analyze_embedding_market_correlation",
    "find_predictive_embedding_patterns",
]
