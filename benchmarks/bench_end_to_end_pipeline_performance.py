"""
End-to-end pipeline performance benchmark.

Measures the full pipeline: extraction → evaluation → refinement → validation.
Helps identify bottlenecks in the complete optimization flow.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


TEST_DOCUMENT_SMALL = """
Alice and Bob are software engineers. They work for TechCorp, 
a San Francisco-based tech company. Alice manages Bob. Both hold 
stock options in TechCorp.
"""

TEST_DOCUMENT_MEDIUM = """
Alice, Bob, and Charlie are core team members at TechCorp.
Alice is the VP of Engineering and manages both Bob and Charlie.
Bob leads the backend team and coordinates with Charlie's frontend team.
Sarah is the CTO and manages Alice.

TechCorp has offices in San Francisco (HQ), New York, and London.
The company was founded in 2015 by David and Emma.
It raised Series A funding from Sequoia Capital and has 45 employees.

Key products include CloudSync (data synchronization) and DataVault (security).
Customers include Acme Corp, Global Finance Inc, and StartupXYZ.
"""

TEST_DOCUMENT_LARGE = TEST_DOCUMENT_MEDIUM + """ 
Additional business details: Revenue in 2024 was $5.2M (up 40% YoY).
Operating costs are 32% of revenue. The company has contracts with AWS, 
Google Cloud, and Microsoft for infrastructure.

Partnership agreements exist with DataCorp (data enrichment) and 
SecureNet (cybersecurity). Competitors include DataSystems Inc and 
CloudTech Solutions.

Technical stack: Python (backend), React (frontend), PostgreSQL (primary storage),
Redis (caching), Kafka (event streaming), Kubernetes (orchestration).

The product roadmap includes AI/ML features (Q3 2025), mobile app (Q4 2025),
and enterprise SaaS tier (Q1 2026).
"""


@pytest.fixture
def generator():
    """Provide OntologyGenerator."""
    return OntologyGenerator()


@pytest.fixture
def critic():
    """Provide OntologyCritic."""
    return OntologyCritic()


@pytest.fixture
def mediator():
    """Provide OntologyMediator."""
    return OntologyMediator()


@pytest.fixture
def context_small():
    """Create context for small document."""
    return OntologyGenerationContext(
        data_source="test_document",
        data_type="text",
        domain="business",
    )


@pytest.fixture
def context_medium():
    """Create context for medium document."""
    return OntologyGenerationContext(
        data_source="test_document_medium",
        data_type="text",
        domain="business",
    )


@pytest.fixture
def context_large():
    """Create context for large document."""
    return OntologyGenerationContext(
        data_source="test_document_large",
        data_type="text",
        domain="business",
    )


@pytest.mark.parametrize("doc_size,doc_text", 
    [
        ("small", TEST_DOCUMENT_SMALL),
        ("medium", TEST_DOCUMENT_MEDIUM),
        ("large", TEST_DOCUMENT_LARGE),
    ]
)
@pytest.mark.benchmark(group="end_to_end_pipeline")
def test_pipeline_extract_evaluate(benchmark, generator, critic, doc_size, doc_text):
    """
    Benchmark extraction + evaluation stages.
    
    Represents the minimal pipeline (generate + critique).
    """
    ctx = OntologyGenerationContext(
        data_source=f"test_{doc_size}",
        data_type="text",
        domain="business",
    )
    
    def run_extract_evaluate():
        extraction = generator.extract_entities(doc_text, ctx)
        # Create simple ontology dict
        ontology = {
            "entities": extraction.entities,
            "relationships": extraction.relationships,
        }
        score = critic.evaluate_ontology(ontology, ctx)
        return ontology, score
    
    result = benchmark(run_extract_evaluate)
    ontology, score = result
    assert ontology is not None
    assert score is not None


@pytest.mark.parametrize("doc_size,doc_text",
    [
        ("small", TEST_DOCUMENT_SMALL),
        ("medium", TEST_DOCUMENT_MEDIUM),
    ]
)
@pytest.mark.benchmark(group="end_to_end_pipeline")
def test_pipeline_extract_evaluate_refine(benchmark, generator, critic, mediator, doc_size, doc_text):
    """
    Benchmark full extraction + evaluation + refinement pipeline.
    
    More realistic workflow with optimization loop.
    """
    ctx = OntologyGenerationContext(
        data_source=f"test_{doc_size}",
        data_type="text",
        domain="business",
    )
    
    def run_full_pipeline():
        # Extraction
        extraction = generator.extract_entities(doc_text, ctx)
        ontology = {
            "entities": extraction.entities,
            "relationships": extraction.relationships,
        }
        
        # Initial evaluation
        score = critic.evaluate_ontology(ontology, ctx)
        
        # Refinement (single pass)
        refined = mediator.refine_ontology(ontology, score, ctx)
        
        # Re-evaluation
        refined_score = critic.evaluate_ontology(refined, ctx)
        
        return refined, refined_score
    
    result = benchmark(run_full_pipeline)
    ontology, score = result
    assert ontology is not None
    assert score is not None


@pytest.mark.benchmark(group="end_to_end_pipeline")
def test_pipeline_mixed_sizes(benchmark, generator, critic, mediator):
    """
    Run pipeline on mixed document sizes in succession.
    
    Tests performance with varied input complexity.
    """
    sizes = [
        ("small", TEST_DOCUMENT_SMALL),
        ("medium", TEST_DOCUMENT_MEDIUM),
        ("small", TEST_DOCUMENT_SMALL),  # repeat small
    ]
    
    def run_mixed_pipeline():
        results = []
        for size_name, doc_text in sizes:
            ctx = OntologyGenerationContext(
                data_source=f"test_{size_name}",
                data_type="text",
                domain="business",
            )
            
            extraction = generator.extract_entities(doc_text, ctx)
            ontology = {
                "entities": extraction.entities,
                "relationships": extraction.relationships,
            }
            score = critic.evaluate_ontology(ontology, ctx)
            refined = mediator.refine_ontology(ontology, score, ctx)
            
            results.append((len(ontology["entities"]), len(ontology["relationships"])))
        
        return results
    
    benchmark(run_mixed_pipeline)


@pytest.mark.benchmark(group="end_to_end_pipeline")
def test_pipeline_repeated_refinement(benchmark, generator, critic, mediator):
    """
    Benchmark multiple refinement passes on the same ontology.
    
    Tests how performance scales with optimization iterations.
    """
    ctx = OntologyGenerationContext(
        data_source="test_medium",
        data_type="text",
        domain="business",
    )
    
    def run_multi_pass_refinement():
        extraction = generator.extract_entities(TEST_DOCUMENT_MEDIUM, ctx)
        ontology = {
            "entities": extraction.entities,
            "relationships": extraction.relationships,
        }
        
        # Multiple refinement passes
        score = critic.evaluate_ontology(ontology, ctx)
        for i in range(3):
            ontology = mediator.refine_ontology(ontology, score, ctx)
            score = critic.evaluate_ontology(ontology, ctx)
        
        return ontology, score
    
    benchmark(run_multi_pass_refinement)
