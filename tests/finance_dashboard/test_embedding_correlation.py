"""
Tests for Vector Embedding & Latent Space Correlation Analysis.

This module tests the embedding generation, multimodal fusion, and
correlation analysis with market movements.
"""

import pytest
from datetime import datetime
import json
import numpy as np


def test_imports():
    """
    GIVEN the embedding_correlation module
    WHEN importing core components
    THEN all imports should succeed
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
            DocumentEmbedding,
            MarketEmbeddingCorrelation,
            VectorEmbeddingAnalyzer,
            analyze_embedding_market_correlation,
            find_predictive_embedding_patterns
        )
        
        assert DocumentEmbedding is not None
        assert MarketEmbeddingCorrelation is not None
        assert VectorEmbeddingAnalyzer is not None
        
    except ImportError as e:
        pytest.fail(f"Import failed: {e}")


def test_document_embedding_creation():
    """
    GIVEN document embedding data
    WHEN creating a DocumentEmbedding
    THEN embedding should be created with correct attributes
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        DocumentEmbedding
    )
    
    text_emb = np.random.randn(768)
    img_emb1 = np.random.randn(512)
    img_emb2 = np.random.randn(512)
    
    doc_emb = DocumentEmbedding(
        doc_id="doc_001",
        source="reuters",
        url="https://example.com/article",
        published_date=datetime(2024, 1, 15),
        text_embedding=text_emb,
        image_embeddings=[img_emb1, img_emb2],
        embedding_model="test-model"
    )
    
    assert doc_emb.doc_id == "doc_001"
    assert doc_emb.text_embedding.shape == (768,)
    assert len(doc_emb.image_embeddings) == 2


def test_analyzer_initialization():
    """
    GIVEN VectorEmbeddingAnalyzer initialization
    WHEN creating analyzer instance
    THEN analyzer should initialize correctly
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        VectorEmbeddingAnalyzer
    )
    
    analyzer = VectorEmbeddingAnalyzer(
        text_model="test-model",
        image_model="test-image-model",
        enable_multimodal=True
    )
    
    assert analyzer.text_model_name == "test-model"
    assert analyzer.enable_multimodal is True
    assert isinstance(analyzer.embeddings, dict)


def test_text_embedding_generation():
    """
    GIVEN text content
    WHEN generating text embedding
    THEN should return normalized vector
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        VectorEmbeddingAnalyzer
    )
    
    analyzer = VectorEmbeddingAnalyzer()
    
    text = "Technology company announces breakthrough product"
    embedding = analyzer.generate_text_embedding(text, "doc_001")
    
    assert embedding.shape == (768,)  # Standard dimension
    # Check normalization
    norm = np.linalg.norm(embedding)
    assert abs(norm - 1.0) < 0.01  # Should be normalized


def test_image_embedding_generation():
    """
    GIVEN image data
    WHEN generating image embedding
    THEN should return normalized vector
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        VectorEmbeddingAnalyzer
    )
    
    analyzer = VectorEmbeddingAnalyzer()
    
    image_url = "https://example.com/image.jpg"
    embedding = analyzer.generate_image_embedding(image_url, "doc_001")
    
    assert embedding.shape == (512,)  # CLIP dimension
    # Check normalization
    norm = np.linalg.norm(embedding)
    assert abs(norm - 1.0) < 0.01


def test_embedding_fusion_weighted_average():
    """
    GIVEN text and image embeddings
    WHEN fusing with weighted average
    THEN should return properly weighted fused embedding
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        VectorEmbeddingAnalyzer
    )
    
    analyzer = VectorEmbeddingAnalyzer()
    
    text_emb = np.random.randn(768)
    text_emb = text_emb / np.linalg.norm(text_emb)
    
    img_emb1 = np.random.randn(512)
    img_emb1 = img_emb1 / np.linalg.norm(img_emb1)
    
    img_emb2 = np.random.randn(512)
    img_emb2 = img_emb2 / np.linalg.norm(img_emb2)
    
    fused = analyzer.fuse_embeddings(
        text_emb,
        [img_emb1, img_emb2],
        fusion_method="weighted_average"
    )
    
    assert fused.shape == (768,)  # Same as text dimension
    # Check normalization
    norm = np.linalg.norm(fused)
    assert abs(norm - 1.0) < 0.01


def test_document_embedding_creation_from_article():
    """
    GIVEN an article with text and images
    WHEN embedding the document
    THEN should create complete DocumentEmbedding
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        VectorEmbeddingAnalyzer
    )
    
    analyzer = VectorEmbeddingAnalyzer(enable_multimodal=True)
    
    article = {
        "article_id": "art_001",
        "title": "Tech breakthrough announced",
        "content": "The company revealed a revolutionary new technology...",
        "images": ["img1.jpg", "img2.jpg"],
        "source": "reuters",
        "published_date": "2024-01-15T10:00:00Z"
    }
    
    doc_emb = analyzer.embed_document(article)
    
    assert doc_emb.doc_id == "art_001"
    assert doc_emb.text_embedding is not None
    assert len(doc_emb.image_embeddings) == 2
    assert doc_emb.fused_embedding is not None


def test_market_correlation_calculation():
    """
    GIVEN document embedding and market data
    WHEN calculating correlation
    THEN should return MarketEmbeddingCorrelation with metrics
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        VectorEmbeddingAnalyzer,
        DocumentEmbedding
    )
    
    analyzer = VectorEmbeddingAnalyzer()
    
    # Create document embedding
    doc_emb = DocumentEmbedding(
        doc_id="doc_001",
        source="reuters",
        url="https://example.com/article",
        published_date=datetime(2024, 1, 15),
        fused_embedding=np.random.randn(768)
    )
    
    # Stock data
    stock_data = {
        "symbol": "TECH",
        "price_before": 100.0,
        "price_after": 105.5,
        "volume_before": 1000000,
        "volume_after": 1500000
    }
    
    correlation = analyzer.correlate_with_market(
        doc_emb,
        stock_data,
        time_window=24
    )
    
    assert correlation.symbol == "TECH"
    assert correlation.price_change == 5.5
    assert correlation.volume_change == 50.0
    assert 0 <= correlation.correlation_score <= 1


def test_similarity_search():
    """
    GIVEN analyzer with multiple embeddings
    WHEN searching for similar documents
    THEN should return ranked results
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        VectorEmbeddingAnalyzer
    )
    
    analyzer = VectorEmbeddingAnalyzer()
    
    # Create several document embeddings
    articles = [
        {
            "article_id": f"art_{i:03d}",
            "title": f"Article {i}",
            "content": f"Content for article {i}",
            "source": "reuters",
            "published_date": "2024-01-15T10:00:00Z"
        }
        for i in range(10)
    ]
    
    for article in articles:
        analyzer.embed_document(article)
    
    # Search for similar
    query_embedding = analyzer.embeddings["art_000"].fused_embedding
    similar = analyzer.find_similar_embeddings(
        query_embedding,
        top_k=5,
        threshold=0.0
    )
    
    assert len(similar) <= 5
    # First result should be the query itself with similarity ~1.0
    if similar:
        assert similar[0][1] >= 0.99


def test_embedding_clustering():
    """
    GIVEN multiple document embeddings
    WHEN clustering
    THEN should return cluster assignments
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        VectorEmbeddingAnalyzer
    )
    
    analyzer = VectorEmbeddingAnalyzer()
    
    # Create embeddings
    articles = [
        {
            "article_id": f"art_{i:03d}",
            "title": f"Article {i}",
            "content": f"Content {i}",
            "source": "reuters",
            "published_date": "2024-01-15T10:00:00Z"
        }
        for i in range(20)
    ]
    
    for article in articles:
        analyzer.embed_document(article)
    
    # Cluster
    clusters = analyzer.cluster_embeddings(n_clusters=5)
    
    assert len(clusters) == 5
    # All documents should be assigned
    total_docs = sum(len(docs) for docs in clusters.values())
    assert total_docs == 20


def test_cluster_market_impact_analysis():
    """
    GIVEN clusters and correlations
    WHEN analyzing cluster impact
    THEN should return impact metrics per cluster
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        VectorEmbeddingAnalyzer,
        DocumentEmbedding,
        MarketEmbeddingCorrelation
    )
    
    analyzer = VectorEmbeddingAnalyzer()
    
    # Create mock correlations
    for i in range(10):
        doc_emb = DocumentEmbedding(
            doc_id=f"doc_{i}",
            source="reuters",
            url=f"https://example.com/art{i}",
            published_date=datetime(2024, 1, 15),
            fused_embedding=np.random.randn(768)
        )
        doc_emb.metadata["cluster_id"] = i % 3  # 3 clusters
        
        analyzer.embeddings[f"doc_{i}"] = doc_emb
        
        corr = MarketEmbeddingCorrelation(
            correlation_id=f"corr_{i}",
            doc_embedding=doc_emb,
            symbol="TECH",
            time_window=24,
            price_change=float(i % 5),
            volume_change=float(i % 10),
            correlation_score=0.5 + (i % 5) * 0.1
        )
        analyzer.correlations.append(corr)
    
    # Create clusters
    clusters = {
        0: [f"doc_{i}" for i in range(0, 10, 3)],
        1: [f"doc_{i}" for i in range(1, 10, 3)],
        2: [f"doc_{i}" for i in range(2, 10, 3)]
    }
    
    # Analyze impact
    impacts = analyzer.analyze_cluster_market_impact(clusters)
    
    assert len(impacts) > 0
    for cluster_id, impact in impacts.items():
        assert "avg_price_change" in impact
        assert "avg_volume_change" in impact
        assert "avg_correlation_score" in impact


def test_mcp_tool_analyze_correlation():
    """
    GIVEN the analyze_embedding_market_correlation MCP tool
    WHEN calling with valid data
    THEN should return JSON response
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        analyze_embedding_market_correlation
    )
    
    news_data = json.dumps([
        {
            "article_id": "art_001",
            "title": "Tech company announces breakthrough",
            "content": "Revolutionary new product unveiled...",
            "images": ["img1.jpg"],
            "source": "reuters",
            "published_date": "2024-01-15T10:00:00Z"
        }
    ])
    
    stock_data = json.dumps([
        {
            "symbol": "TECH",
            "price_before": 100.0,
            "price_after": 105.5,
            "volume_before": 1000000,
            "volume_after": 1500000
        }
    ])
    
    result = analyze_embedding_market_correlation(
        news_articles_json=news_data,
        stock_data_json=stock_data,
        enable_multimodal=True,
        time_window=24,
        n_clusters=3
    )
    
    # Should return valid JSON
    data = json.loads(result)
    assert "success" in data
    assert data["success"] is True


def test_mcp_tool_find_patterns():
    """
    GIVEN the find_predictive_embedding_patterns MCP tool
    WHEN calling it
    THEN should return JSON response
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        find_predictive_embedding_patterns
    )
    
    historical_data = json.dumps({
        "embeddings": [],
        "market_outcomes": []
    })
    
    result = find_predictive_embedding_patterns(
        historical_embeddings_json=historical_data,
        min_correlation=0.5,
        lookback_days=30
    )
    
    # Should return valid JSON
    data = json.loads(result)
    assert "success" in data


def test_document_embedding_to_dict():
    """
    GIVEN a DocumentEmbedding
    WHEN converting to dict
    THEN should have all required fields
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        DocumentEmbedding
    )
    
    doc_emb = DocumentEmbedding(
        doc_id="doc_001",
        source="reuters",
        url="https://example.com/article",
        published_date=datetime(2024, 1, 15),
        text_embedding=np.random.randn(768),
        image_embeddings=[np.random.randn(512)],
        fused_embedding=np.random.randn(768),
        embedding_model="test-model"
    )
    
    result_dict = doc_emb.to_dict()
    
    assert result_dict["doc_id"] == "doc_001"
    assert result_dict["has_text_embedding"] is True
    assert result_dict["text_embedding_dim"] == 768
    assert result_dict["num_image_embeddings"] == 1


def test_correlation_to_dict():
    """
    GIVEN a MarketEmbeddingCorrelation
    WHEN converting to dict
    THEN should have all required fields
    """
    from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
        DocumentEmbedding,
        MarketEmbeddingCorrelation
    )
    
    doc_emb = DocumentEmbedding(
        doc_id="doc_001",
        source="reuters",
        url="https://example.com/article",
        published_date=datetime(2024, 1, 15),
        fused_embedding=np.random.randn(768)
    )
    
    corr = MarketEmbeddingCorrelation(
        correlation_id="corr_001",
        doc_embedding=doc_emb,
        symbol="TECH",
        time_window=24,
        price_change=5.5,
        volume_change=50.0,
        correlation_score=0.75,
        latent_factors={"factor_1": 0.5}
    )
    
    result_dict = corr.to_dict()
    
    assert result_dict["correlation_id"] == "corr_001"
    assert result_dict["symbol"] == "TECH"
    assert result_dict["market_impact"]["price_change_pct"] == 5.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
