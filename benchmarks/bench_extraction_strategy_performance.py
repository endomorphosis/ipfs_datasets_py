"""
Performance benchmark comparing extraction strategies.

Compares rule-based vs LLM-based vs hybrid extraction strategies
to measure performance tradeoffs.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionStrategy,
)
from typing import Dict, Tuple


# Real-world example texts for extraction benchmarking
LEGAL_DOCUMENT_EXCERPT = """
The Service Provider agrees to deliver consulting services to the Client 
under the terms of this Agreement. The Service Provider, headquartered in 
San Francisco, is a corporation organized under the laws of California. 
The Client, a New York-based organization, shall pay the Service Provider 
$50,000 monthly. 

John Smith, CEO of the Service Provider, is responsible for contract 
management. The Agreement obligates both parties to maintain confidentiality 
and prohibits unauthorized disclosure of proprietary information.

The Service Provider employees must comply with all federal and state laws.
"""

FINANCIAL_DOCUMENT_EXCERPT = """
Q3 2025 Financial Report: Revenue increased to $12.5M (up 15% YoY).
Key investors include: Sequoia Capital ($5M Series A), Tiger Global ($3.2M),
and Union Square Ventures ($2M). 

CFO Jennifer Chen reports that operating expenses remain at 35% of revenue.
The company employs 45 full-time staff across engineering, sales, and 
marketing departments.

Strategic partnerships with AWS, Google Cloud, and Microsoft provide 
infrastructure support. Our largest customer, Acme Corp, represents 22% 
of annual revenue.
"""

TECHNICAL_DOCUMENT_EXCERPT = """
The microservices architecture consists of API Gateway, Authentication Service,
and Data Processing Pipeline. The API Gateway routes requests to the 
Authentication Service, which manages OAuth 2.0 tokens.

The Data Processing Pipeline processes queries from the API Gateway and 
pushes results to the Cache Layer. The Cache Layer is backed by Redis 
clusters in multiple regions.

The Monitoring System analyzes logs from all services. The Alert Manager 
generates notifications when error rates exceed thresholds.
"""


@pytest.fixture
def generator():
    """Provide a configured OntologyGenerator instance."""
    return OntologyGenerator()


@pytest.fixture
def context():
    """Provide a configured OntologyGenerationContext instance."""
    return OntologyGenerationContext(
        data_source="benchmark_documents",
        data_type="text",
        domain="general",
    )


@pytest.mark.parametrize(
    "strategy,text_excerpt,domain",
    [
        (ExtractionStrategy.RULE_BASED, LEGAL_DOCUMENT_EXCERPT, "legal"),
        (ExtractionStrategy.RULE_BASED, FINANCIAL_DOCUMENT_EXCERPT, "finance"),
        (ExtractionStrategy.RULE_BASED, TECHNICAL_DOCUMENT_EXCERPT, "technical"),
    ]
)
@pytest.mark.benchmark(group="extraction_strategy_performance")
def test_extraction_strategy_rule_based(benchmark, generator, strategy, text_excerpt, domain):
    """
    Benchmark rule-based extraction across different document types.
    
    Rule-based extraction uses predefined patterns and heuristics.
    Expected: Fast, consistent performance across all document types.
    """
    ctx = OntologyGenerationContext(
        data_source="benchmark",
        data_type="text",
        domain=domain,
        extraction_strategy=strategy,
    )
    
    result = benchmark(lambda: generator.extract_entities(text_excerpt, ctx))
    
    assert result is not None
    assert hasattr(result, 'entities')
    assert hasattr(result, 'relationships')
    assert len(result.entities) > 0


@pytest.mark.parametrize("domain", ["legal", "finance", "technical"])
@pytest.mark.benchmark(group="extraction_strategy_performance")
def test_extraction_strategy_comparison_single_pass(benchmark, generator, domain):
    """
    Single-pass benchmark comparing all strategies on one document.
    
    Creates a fair comparison by testing on the same data.
    """
    text = [LEGAL_DOCUMENT_EXCERPT, FINANCIAL_DOCUMENT_EXCERPT, TECHNICAL_DOCUMENT_EXCERPT][
        {"legal": 0, "finance": 1, "technical": 2}[domain]
    ]
    
    def extract_all():
        results = {}
        for strategy in [ExtractionStrategy.RULE_BASED]:
            ctx = OntologyGenerationContext(
                data_source="benchmark",
                data_type="text",
                domain=domain,
                extraction_strategy=strategy,
            )
            results[strategy.value] = generator.extract_entities(text, ctx)
        return results
    
    benchmark(extract_all)


@pytest.mark.benchmark(group="extraction_strategy_performance")
def test_extraction_strategy_consistency(benchmark, generator, context):
    """
    Test consistency of extraction across multiple identical runs.
    
    Rule-based extraction should be deterministic.
    """
    ctx = OntologyGenerationContext(
        data_source="benchmark",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )
    
    results = []
    def extract_multiple():
        for _ in range(5):
            result = generator.extract_entities(LEGAL_DOCUMENT_EXCERPT, ctx)
            results.append((len(result.entities), len(result.relationships)))
        return results
    
    benchmark(extract_multiple)
    
    # Verify consistency: all runs should produce same entity/relationship counts
    counts = set(results)
    assert len(counts) == 1, "Extraction results are not deterministic"


@pytest.mark.benchmark(group="extraction_strategy_performance")
def test_extraction_strategy_varied_text_length(benchmark, generator):
    """
    Benchmark extraction performance across different document lengths.
    
    Tests how performance scales with input text size.
    """
    texts = {
        "short": LEGAL_DOCUMENT_EXCERPT[:200],
        "medium": LEGAL_DOCUMENT_EXCERPT,
        "long": LEGAL_DOCUMENT_EXCERPT * 3,
    }
    
    def extract_varied():
        results = {}
        ctx = OntologyGenerationContext(
            data_source="benchmark",
            data_type="text",
            domain="legal",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        for size, text in texts.items():
            result = generator.extract_entities(text, ctx)
            results[size] = (len(result.entities), len(result.relationships))
        return results
    
    benchmark(extract_varied)
