# Vector Embedding & Latent Space Correlation Analysis

## Overview

This module provides advanced correlation analysis between vector embeddings from financial news (text and images) and market movements. It goes beyond traditional sentiment analysis by analyzing latent spaces to discover deeper patterns and predictive signals.

## Key Concepts

### What Are Vector Embeddings?

Vector embeddings are dense numerical representations of content (text, images) that capture semantic meaning in high-dimensional space. Similar content has similar embeddings, enabling:
- Semantic similarity search
- Pattern discovery
- Latent factor extraction
- Predictive signal identification

### Multimodal Analysis

Combines embeddings from multiple modalities:
- **Text Embeddings**: Capture semantic content of articles (768-dim from transformers)
- **Image Embeddings**: Capture visual information (512-dim from CLIP)
- **Fused Embeddings**: Combined representation for richer analysis

### Latent Space Correlation

Rather than explicit sentiment (positive/negative), this analyzes:
- **Latent Factors**: Hidden dimensions in embedding space
- **Embedding Clusters**: Thematic groups with similar market impact
- **Temporal Patterns**: How embedding patterns predict market movements
- **Cross-Modal Signals**: Information from text+image combinations

## Architecture

```
News Articles (Text + Images)
         ↓
    Embedding Generation
    ├─ Text Encoder (Transformer)
    └─ Image Encoder (CLIP)
         ↓
    Multimodal Fusion
         ↓
    Latent Space Analysis
    ├─ Clustering
    ├─ Factor Extraction
    └─ Pattern Discovery
         ↓
    Correlation with Market Data
    ├─ Price Changes
    ├─ Volume Changes
    └─ Volatility
         ↓
    Predictive Signals
```

## Features

### 1. Text Embedding Generation

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
    VectorEmbeddingAnalyzer
)

analyzer = VectorEmbeddingAnalyzer(
    text_model="sentence-transformers/all-mpnet-base-v2",
    image_model="openai/clip-vit-base-patch32",
    enable_multimodal=True
)

# Generate text embedding
article = {
    "article_id": "art_001",
    "title": "Tech company announces breakthrough",
    "content": "The company unveiled...",
    "source": "reuters",
    "published_date": "2024-01-15T10:00:00Z"
}

doc_embedding = analyzer.embed_document(article)
print(f"Text embedding shape: {doc_embedding.text_embedding.shape}")  # (768,)
```

### 2. Image Embedding Extraction

```python
# Article with images
article_with_images = {
    "article_id": "art_002",
    "title": "CEO presents new product",
    "content": "At the launch event...",
    "images": [
        "https://example.com/image1.jpg",
        "https://example.com/image2.jpg"
    ],
    "source": "bloomberg",
    "published_date": "2024-01-16T14:30:00Z"
}

doc_embedding = analyzer.embed_document(article_with_images)
print(f"Number of image embeddings: {len(doc_embedding.image_embeddings)}")
print(f"Fused embedding shape: {doc_embedding.fused_embedding.shape}")
```

### 3. Multimodal Fusion

Multiple fusion strategies available:

**Weighted Average** (default):
```python
# Text gets 60% weight, images split remaining 40%
fused = analyzer.fuse_embeddings(
    text_embedding=text_emb,
    image_embeddings=[img_emb1, img_emb2],
    fusion_method="weighted_average"
)
```

**Concatenation**:
```python
# Simply concatenate all embeddings
fused = analyzer.fuse_embeddings(
    text_embedding=text_emb,
    image_embeddings=[img_emb1, img_emb2],
    fusion_method="concatenate"
)
```

### 4. Market Correlation Analysis

```python
# Stock data after article publication
stock_data = {
    "symbol": "TECH",
    "price_before": 100.0,  # Price before article
    "price_after": 105.5,   # Price 24h after
    "volume_before": 1000000,
    "volume_after": 1500000
}

# Correlate embedding with market movement
correlation = analyzer.correlate_with_market(
    doc_embedding=doc_embedding,
    stock_data=stock_data,
    time_window=24  # hours
)

print(f"Price change: {correlation.price_change:.2f}%")
print(f"Volume change: {correlation.volume_change:.2f}%")
print(f"Correlation score: {correlation.correlation_score:.3f}")
print(f"Latent factors: {correlation.latent_factors}")
```

### 5. Clustering & Pattern Discovery

```python
# Cluster documents by embedding similarity
clusters = analyzer.cluster_embeddings(
    n_clusters=10,
    method="kmeans"
)

print(f"Found {len(clusters)} clusters")
for cluster_id, doc_ids in clusters.items():
    print(f"  Cluster {cluster_id}: {len(doc_ids)} documents")

# Analyze market impact by cluster
cluster_impacts = analyzer.analyze_cluster_market_impact(clusters)

for cluster_id, impact in cluster_impacts.items():
    print(f"\nCluster {cluster_id}:")
    print(f"  Avg price change: {impact['avg_price_change']:.2f}%")
    print(f"  Avg volume change: {impact['avg_volume_change']:.2f}%")
    print(f"  Avg correlation: {impact['avg_correlation_score']:.3f}")
```

### 6. Similarity Search

```python
# Find similar articles
query_embedding = doc_embedding.fused_embedding
similar_docs = analyzer.find_similar_embeddings(
    query_embedding=query_embedding,
    top_k=10,
    threshold=0.7
)

for doc, similarity in similar_docs:
    print(f"{doc.doc_id}: similarity={similarity:.3f}")
```

## MCP Tool Usage

### Analyze Embedding-Market Correlation

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
    analyze_embedding_market_correlation
)
import json

# Prepare data
news_data = json.dumps([
    {
        "article_id": "art_001",
        "title": "Tech breakthrough announced",
        "content": "Company reveals...",
        "images": ["url1.jpg", "url2.jpg"],
        "source": "reuters",
        "published_date": "2024-01-15T10:00:00Z"
    },
    # ... more articles
])

stock_data = json.dumps([
    {
        "symbol": "TECH",
        "price_before": 100.0,
        "price_after": 105.5,
        "volume_before": 1000000,
        "volume_after": 1500000
    },
    # ... more stocks
])

# Analyze correlations
result = analyze_embedding_market_correlation(
    news_articles_json=news_data,
    stock_data_json=stock_data,
    enable_multimodal=True,
    time_window=24,
    n_clusters=10
)

analysis = json.loads(result)
print(json.dumps(analysis, indent=2))
```

**Output**:
```json
{
  "success": true,
  "analysis": {
    "embeddings_created": 50,
    "correlations_analyzed": 500,
    "clusters_found": 10,
    "multimodal_enabled": true,
    "time_window_hours": 24
  },
  "correlations": [...],
  "clusters": {
    "0": {
      "doc_count": 15,
      "impact": {
        "avg_price_change": 2.5,
        "avg_volume_change": 15.3,
        "avg_correlation_score": 0.72
      }
    },
    ...
  },
  "top_correlations": [
    {
      "correlation_id": "art_001_TECH_24h",
      "correlation_score": 0.85,
      "market_impact": {
        "price_change_pct": 5.5,
        "volume_change_pct": 50.0
      },
      "latent_factors": {
        "factor_42": 0.85,
        "factor_127": -0.62,
        ...
      }
    },
    ...
  ]
}
```

### Find Predictive Patterns

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
    find_predictive_embedding_patterns
)

# Analyze historical data for patterns
historical_data = json.dumps({
    "embeddings": [...],
    "market_outcomes": [...]
})

patterns = find_predictive_embedding_patterns(
    historical_embeddings_json=historical_data,
    min_correlation=0.5,
    lookback_days=30
)

print(json.loads(patterns))
```

## Use Cases

### 1. Beyond Sentiment Analysis

Traditional sentiment only captures positive/negative. Embedding analysis captures:
- **Topic patterns**: Which topics (embedded as vectors) correlate with moves
- **Visual cues**: CEO body language, product images, charts in articles
- **Subtle signals**: Embedding dimensions that don't map to obvious features

```python
# Traditional sentiment: "This is positive news"
# Embedding analysis: "Articles in cluster 5 with high factor_42 
#                      consistently precede 3%+ moves within 24h"
```

### 2. Image-Based Signals

Extract predictive signals from article images:
```python
# Images that might predict market reaction:
# - CEO facial expressions during announcements
# - Product reveal images (quality, innovation signals)
# - Charts and graphs shown in articles
# - Factory/store photos (activity level)
# - Event photos (attendance, energy)

# The CLIP model embeds these into vectors that can correlate with outcomes
```

### 3. Temporal Pattern Discovery

```python
# Example pattern:
# Articles published 9-11am with high embedding similarity to cluster 3
# show 2x higher correlation with same-day price moves than other times

# Find these patterns:
patterns = analyzer.find_temporal_patterns(
    embeddings=doc_embeddings,
    market_data=stock_data
)
```

### 4. Cross-Company Correlation

```python
# Find when news about Company A correlates with moves in Company B
# Based on embedding similarity (not explicit mentions)

analyzer.find_cross_company_correlations(
    min_similarity=0.8,
    min_correlation=0.5
)
```

## Advanced Features

### Latent Factor Interpretation

```python
# Extract and interpret latent factors
doc_embedding = analyzer.embed_document(article)
latent_factors = analyzer._extract_latent_factors(
    doc_embedding.fused_embedding,
    top_k=10
)

# Interpret factors by finding common terms in high-scoring docs
for factor_name, value in latent_factors.items():
    similar_docs = analyzer.find_docs_with_high_factor(factor_name)
    common_terms = extract_common_terms(similar_docs)
    print(f"{factor_name}: {common_terms}")
```

### Embedding Space Visualization

```python
# Project to 2D for visualization (use UMAP or t-SNE in production)
import matplotlib.pyplot as plt

embeddings_2d = reduce_dimensionality(
    [emb.fused_embedding for emb in analyzer.embeddings.values()],
    method="umap"
)

# Color by market impact
colors = [corr.price_change for corr in analyzer.correlations]

plt.scatter(embeddings_2d[:, 0], embeddings_2d[:, 1], c=colors, cmap='RdYlGn')
plt.colorbar(label='Price Change %')
plt.title('News Embedding Space Colored by Market Impact')
plt.show()
```

### Time-Series Analysis

```python
# Track how embedding patterns evolve over time
embedding_timeseries = analyzer.create_embedding_timeseries(
    symbol="TECH",
    start_date="2024-01-01",
    end_date="2024-06-01"
)

# Correlate with price timeseries
correlation_over_time = analyzer.compute_rolling_correlation(
    embedding_timeseries,
    price_timeseries,
    window="7d"
)
```

## Production Implementation

### Install Dependencies

```bash
# Embedding models
pip install sentence-transformers transformers torch

# For CLIP image embeddings
pip install Pillow requests

# For clustering and analysis
pip install scikit-learn scipy numpy

# For visualization
pip install umap-learn matplotlib seaborn
```

### Model Selection

**Text Models** (by use case):
- General news: `sentence-transformers/all-mpnet-base-v2` (768-dim)
- Financial domain: `ProsusAI/finbert` (768-dim, finance-tuned)
- Large scale: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, faster)

**Image Models**:
- Standard: `openai/clip-vit-base-patch32` (512-dim)
- High quality: `openai/clip-vit-large-patch14` (768-dim)
- Efficient: `openai/clip-vit-base-patch16` (512-dim)

### Performance Optimization

```python
# Batch processing
analyzer.embed_documents_batch(
    articles=article_list,
    batch_size=32,
    use_gpu=True
)

# Caching
analyzer.enable_embedding_cache(
    cache_dir="/path/to/cache",
    cache_embeddings=True
)

# Parallel processing
analyzer.set_num_workers(4)
```

## Integration with Other Finance Tools

### With News Scrapers

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.news_scrapers import (
    fetch_financial_news
)
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
    VectorEmbeddingAnalyzer
)

# Scrape news
news_json = fetch_financial_news(
    topic="technology",
    start_date="2024-01-01",
    end_date="2024-01-31",
    sources="reuters,bloomberg",
    max_articles=1000
)
articles = json.loads(news_json)["articles"]

# Generate embeddings and analyze
analyzer = VectorEmbeddingAnalyzer()
for article in articles:
    doc_emb = analyzer.embed_document(article)
    # Correlate with market data...
```

### With GraphRAG Analyzer

Note: the GraphRAG core implementation is in `ipfs_datasets_py.knowledge_graphs.finance_graphrag`;
this MCP wrapper re-exports the same analyzer.

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
    GraphRAGNewsAnalyzer
)
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.embedding_correlation import (
    VectorEmbeddingAnalyzer
)

# Combine approaches
graphrag_analyzer = GraphRAGNewsAnalyzer()
embedding_analyzer = VectorEmbeddingAnalyzer()

# Extract executive profiles
executives = graphrag_analyzer.extract_executive_profiles(articles)

# Generate embeddings for same articles
for article in articles:
    doc_emb = embedding_analyzer.embed_document(article)

# Find which embedding clusters correlate with CEO characteristics
cluster_impacts = embedding_analyzer.cluster_embeddings()
executive_clusters = match_executives_to_clusters(executives, cluster_impacts)
```

## Research & Analysis

### Research Questions Answerable

1. **Do certain article themes predict market moves?**
   - Cluster articles, measure impact per cluster

2. **Do images add predictive value beyond text?**
   - Compare text-only vs multimodal correlation scores

3. **What latent factors matter most?**
   - Regression on latent factors vs market outcomes

4. **Are patterns stable over time?**
   - Rolling window analysis of embedding-market correlation

5. **Do patterns transfer across companies?**
   - Test if embedding patterns learned on AAPL work for MSFT

### Example Analysis Workflow

```python
# 1. Collect historical data
articles = scrape_news_archive(years=2)
market_data = get_historical_prices(years=2)

# 2. Generate embeddings
analyzer = VectorEmbeddingAnalyzer()
embeddings = [analyzer.embed_document(a) for a in articles]

# 3. Compute correlations
correlations = []
for emb in embeddings:
    corr = analyzer.correlate_with_market(emb, market_data)
    correlations.append(corr)

# 4. Find patterns
high_impact = [c for c in correlations if abs(c.price_change) > 3.0]
clusters = analyzer.cluster_embeddings([c.doc_embedding for c in high_impact])

# 5. Build predictive model
from sklearn.ensemble import RandomForestRegressor

X = [c.doc_embedding.fused_embedding for c in correlations]
y = [c.price_change for c in correlations]

model = RandomForestRegressor()
model.fit(X, y)

# 6. Make predictions
new_article = scrape_latest_news()
new_embedding = analyzer.embed_document(new_article)
predicted_impact = model.predict([new_embedding.fused_embedding])
```

## Limitations & Future Work

### Current Limitations
- Mock embeddings (need actual transformer models)
- Simple correlation calculation (need regression models)
- Basic clustering (need proper sklearn integration)
- Placeholder latent factor extraction (need PCA/ICA)

### Planned Enhancements
- **Phase 1**: Integrate actual embedding models (sentence-transformers, CLIP)
- **Phase 2**: Add sophisticated correlation methods (Granger causality, transfer entropy)
- **Phase 3**: Train predictive models (LSTM, attention-based)
- **Phase 4**: Add interpretability (SHAP, attention visualization)
- **Phase 5**: Real-time prediction API
- **Phase 6**: Causal inference (not just correlation)

## References

- **Sentence Transformers**: https://www.sbert.net/
- **CLIP**: https://github.com/openai/CLIP
- **Embedding Best Practices**: See `docs/embeddings_guide.md`
- **Latent Space Analysis**: See research papers in `docs/references/`

## Support

For issues:
- GitHub: [ipfs_datasets_py/issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- Documentation: Main project README
- Examples: `tests/finance_dashboard/test_embedding_correlation.py`
