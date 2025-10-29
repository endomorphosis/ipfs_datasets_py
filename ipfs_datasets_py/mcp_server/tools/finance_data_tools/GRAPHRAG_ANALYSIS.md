# GraphRAG News Analysis for Executive-Performance Correlation

## Overview

The GraphRAG News Analyzer enables hypothesis testing and correlation analysis between executive characteristics and company performance using knowledge graphs built from financial news archives.

## Key Features

### 1. Executive Profile Extraction
- **Automatic extraction** from news archives (AP, Reuters, Bloomberg)
- **Attributes extracted**:
  - Gender (male, female, non-binary)
  - Personality traits (introvert, extrovert, analytical, visionary)
  - Educational background
  - Career history and tenure
  - News sentiment scores
  - Leadership style indicators

### 2. Company Performance Linking
- Links executives to their companies
- Tracks stock performance during tenure
- Calculates returns, volatility, market cap changes
- Temporal alignment of news and market data

### 3. Hypothesis Testing Framework
- **Compare executive groups**:
  - Male vs Female CEOs
  - Introvert vs Extrovert leaders
  - MBA vs Engineering backgrounds
  - Long tenure vs Short tenure
- **Statistical analysis** with confidence levels
- **Evidence-based conclusions**

### 4. GraphRAG Integration
- Knowledge graph construction
- Entity linking and deduplication
- Cross-document reasoning
- Relationship extraction

## Usage Examples

### Example 1: Male vs Female CEO Performance

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
    GraphRAGNewsAnalyzer
)

# Initialize analyzer
analyzer = GraphRAGNewsAnalyzer()

# Extract executive profiles from news
news_articles = [
    {
        "title": "Tech CEO Jane Smith leads company to record profits",
        "content": "CEO Jane Smith announced today... she has transformed...",
        "source": "reuters",
        "published_date": "2023-01-15"
    },
    # ... more articles
]

executives = analyzer.extract_executive_profiles(news_articles)
print(f"Found {len(executives)} executives")

# Link to stock performance
stock_performance = [
    {
        "symbol": "TECH",
        "name": "Tech Company",
        "return_percentage": 45.2,
        "volatility": 12.3
    },
    # ... more companies
]

# Test hypothesis
result = analyzer.test_hypothesis(
    hypothesis="Female CEOs outperform male CEOs",
    attribute_name="gender",
    group_a_value="female",
    group_b_value="male",
    metric="return_percentage"
)

print(f"Result: {result.conclusion}")
print(f"Female CEO average return: {result.group_a_mean:.2f}%")
print(f"Male CEO average return: {result.group_b_mean:.2f}%")
print(f"Difference: {result.difference:.2f}%")
print(f"Statistical significance (p-value): {result.p_value}")
```

### Example 2: Personality Traits Analysis

```python
# Test introvert vs extrovert CEOs
result = analyzer.test_hypothesis(
    hypothesis="Introverted CEOs show lower volatility",
    attribute_name="personality_traits",
    group_a_value="introvert",
    group_b_value="extrovert",
    metric="volatility"
)

print(result.conclusion)
```

### Example 3: Using MCP Tools

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
    analyze_executive_performance
)
import json

# Prepare data
news_data = json.dumps([
    {"title": "...", "content": "...", "source": "ap"},
    # ... more articles
])

stock_data = json.dumps([
    {"symbol": "AAPL", "return_percentage": 25.5, "volatility": 15.2},
    # ... more companies
])

# Analyze
result = analyze_executive_performance(
    news_articles_json=news_data,
    stock_data_json=stock_data,
    hypothesis="Female CEOs outperform male CEOs",
    attribute="gender",
    group_a="female",
    group_b="male"
)

analysis = json.loads(result)
print(json.dumps(analysis, indent=2))
```

## Data Structures

### ExecutiveProfile

```python
@dataclass
class ExecutiveProfile:
    person_id: str              # Unique identifier
    name: str                   # Full name
    gender: str                 # "male", "female", "non-binary", "unknown"
    personality_traits: List[str]  # ["introvert", "analytical", ...]
    education: Dict[str, str]   # {"degree": "MBA", "school": "Harvard"}
    companies: List[str]        # Associated companies
    positions: List[str]        # Positions held
    tenure_start: datetime      # Start date
    tenure_end: datetime        # End date (None if current)
    news_mentions: int          # Number of news articles
    sentiment_score: float      # Average sentiment (-1.0 to 1.0)
    attributes: Dict[str, Any]  # Additional custom attributes
```

### CompanyPerformance

```python
@dataclass
class CompanyPerformance:
    company_id: str
    symbol: str                 # Stock ticker
    name: str                   # Company name
    executive_id: str           # Linked executive
    start_date: datetime
    end_date: datetime
    start_price: float
    end_price: float
    return_percentage: float    # Total return %
    volatility: float           # Price volatility
    market_cap_change: float    # Market cap change
    metrics: Dict[str, float]   # Additional metrics
```

### HypothesisTest

```python
@dataclass
class HypothesisTest:
    hypothesis_id: str
    hypothesis: str             # Hypothesis statement
    group_a_label: str          # "Female CEOs"
    group_b_label: str          # "Male CEOs"
    group_a_samples: int        # Sample size
    group_b_samples: int
    group_a_mean: float         # Average performance
    group_b_mean: float
    difference: float           # Performance difference
    p_value: float              # Statistical significance
    confidence_level: float     # Confidence (0.0-1.0)
    conclusion: str             # Result summary
    supporting_evidence: List   # Supporting data points
```

## Hypothesis Testing Workflow

```
1. Data Collection
   ├─ Scrape news archives (AP, Reuters, Bloomberg)
   ├─ Extract executive mentions and attributes
   └─ Collect stock performance data

2. Profile Building
   ├─ Identify unique executives
   ├─ Extract characteristics (gender, traits, education)
   ├─ Build entity profiles with confidence scores
   └─ Link to companies and positions

3. Performance Linking
   ├─ Match executives to companies
   ├─ Align tenure periods with stock data
   ├─ Calculate performance metrics
   └─ Create executive-company relationships

4. Knowledge Graph Construction
   ├─ Create entity nodes (executives, companies)
   ├─ Create relationship edges (leads, founded, etc.)
   ├─ Add temporal constraints
   └─ Integrate with GraphRAG system

5. Hypothesis Testing
   ├─ Group executives by attribute
   ├─ Calculate group statistics
   ├─ Compute significance (p-value)
   ├─ Generate conclusion
   └─ Collect supporting evidence

6. Results & Visualization
   ├─ Statistical summary
   ├─ Knowledge graph visualization
   ├─ Evidence chains
   └─ Actionable insights
```

## Advanced Features

### Custom Attribute Extraction

```python
# Add custom attribute extractors
analyzer = GraphRAGNewsAnalyzer()

# Extract age from articles
def extract_age(article_content):
    import re
    match = re.search(r'(\d+)-year-old', article_content)
    return int(match.group(1)) if match else None

# Apply to profiles
for article in news_articles:
    profiles = analyzer.extract_executive_profiles([article])
    for profile in profiles:
        age = extract_age(article['content'])
        if age:
            profile.attributes['age'] = age
```

### Multi-Attribute Hypotheses

```python
# Test multiple attributes
hypotheses = [
    ("gender", "female", "male"),
    ("personality_traits", "introvert", "extrovert"),
    ("education.degree", "MBA", "Engineering")
]

results = []
for attr, group_a, group_b in hypotheses:
    result = analyzer.test_hypothesis(
        hypothesis=f"{group_a} vs {group_b} on {attr}",
        attribute_name=attr,
        group_a_value=group_a,
        group_b_value=group_b
    )
    results.append(result)

# Compare results
for r in results:
    print(f"{r.hypothesis}: {r.conclusion}")
```

### Knowledge Graph Queries

```python
# Build knowledge graph
kg = analyzer.build_knowledge_graph()

# Query executives by attribute
female_execs = [
    e for e in kg.entities
    if e.entity_type == "executive" 
    and e.properties.get("gender") == "female"
]

# Find companies led by female executives
female_led_companies = [
    r.target_entity for r in kg.relationships
    if r.relationship_type == "leads"
    and r.source_entity.properties.get("gender") == "female"
]

print(f"Found {len(female_led_companies)} companies led by female executives")
```

## Integration with Existing Tools

### With News Scrapers

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.news_scrapers import (
    fetch_financial_news
)
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.graphrag_news_analyzer import (
    GraphRAGNewsAnalyzer
)

# Scrape news
news_json = fetch_financial_news(
    topic="CEO leadership",
    start_date="2020-01-01",
    end_date="2024-01-01",
    sources="reuters,bloomberg",
    max_articles=1000
)
news_articles = json.loads(news_json)["articles"]

# Analyze executives
analyzer = GraphRAGNewsAnalyzer()
executives = analyzer.extract_executive_profiles(news_articles)
```

### With Stock Scrapers

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.stock_scrapers import (
    fetch_stock_data
)

# Get stock data for companies
companies = ["AAPL", "MSFT", "GOOGL", "META"]
performance_data = []

for symbol in companies:
    stock_json = fetch_stock_data(
        symbol=symbol,
        start_date="2020-01-01",
        end_date="2024-01-01"
    )
    # Process and add to performance_data
```

### With Financial Theorems

```python
from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
    FinancialTheoremLibrary
)

# Use theorems to validate hypotheses
library = FinancialTheoremLibrary()

# Create custom theorem for executive transitions
# (Similar to merger theorem but for leadership changes)
```

## Production Deployment

### Prerequisites

```bash
# Install NLP dependencies
pip install spacy transformers
python -m spacy download en_core_web_lg

# Install statistical analysis
pip install scipy pandas numpy

# Install graph libraries
pip install networkx
```

### Configuration

```python
# config.py
GRAPHRAG_CONFIG = {
    "enable_graphrag": True,
    "min_confidence": 0.7,
    "nlp_model": "en_core_web_lg",
    "personality_model": "cardiffnlp/twitter-roberta-base-sentiment",
    "gender_detection": "ner_based",  # or "pronoun_based"
    "min_news_mentions": 3,
    "statistical_test": "t_test",  # or "mann_whitney"
    "significance_level": 0.05
}
```

### Error Handling

```python
try:
    result = analyzer.test_hypothesis(...)
except InsufficientDataError as e:
    print(f"Not enough data: {e}")
except AttributeExtractionError as e:
    print(f"Failed to extract attributes: {e}")
```

## Limitations & Future Work

### Current Limitations
- Basic entity extraction (needs advanced NLP)
- Simple statistical tests (needs scipy integration)
- Placeholder attribute inference (needs ML models)
- Limited archive scraping (needs full implementation)

### Planned Enhancements
- **Phase 1**: Integrate spaCy/transformers for entity extraction
- **Phase 2**: Add personality detection models
- **Phase 3**: Implement advanced statistical tests (t-test, ANOVA)
- **Phase 4**: Full archive.org integration
- **Phase 5**: Causal inference (not just correlation)
- **Phase 6**: Real-time monitoring and alerts

## Research Applications

This tool enables research into:
1. **Gender diversity impact** on company performance
2. **Personality traits** and leadership effectiveness
3. **Educational background** correlations
4. **Leadership tenure** effects on volatility
5. **Communication style** impact (from news tone)
6. **Industry-specific** executive characteristics
7. **Market conditions** interaction with leadership

## Citation

When using this tool for research, please cite:
```
GraphRAG News Analyzer for Financial Markets
Part of IPFS Datasets Python - Finance Dashboard Enhancement
https://github.com/endomorphosis/ipfs_datasets_py
```

## Support

For issues or feature requests:
- GitHub Issues: [ipfs_datasets_py/issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- Documentation: See main project README
- Examples: `tests/finance_dashboard/test_graphrag_analysis.py`
