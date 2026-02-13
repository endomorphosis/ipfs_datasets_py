"""
Basic example demonstrating GraphRAG Ontology Optimizer usage.

This example shows how to use the ontology optimizer to generate, evaluate,
and refine knowledge graph ontologies from arbitrary data.

Usage:
    python scripts/demo/demonstrate_ontology_optimizer.py
"""

import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def example_basic_generation():
    """Example 1: Basic ontology generation."""
    print("\n" + "="*60)
    print("Example 1: Basic Ontology Generation")
    print("="*60 + "\n")
    
    from ipfs_datasets_py.optimizers.graphrag import (
        OntologyGenerator,
        OntologyGenerationContext,
        ExtractionStrategy,
        DataType
    )
    
    # Sample data
    sample_text = """
    Alice must pay Bob $100 by Friday. Bob is obligated to deliver
    the goods to Alice within 30 days. If Bob fails to deliver,
    Alice may cancel the agreement.
    """
    
    # Setup generator
    generator = OntologyGenerator(use_ipfs_accelerate=False)  # Rule-based for demo
    
    # Create context
    context = OntologyGenerationContext(
        data_source='sample_contract.txt',
        data_type=DataType.TEXT,
        domain='legal',
        extraction_strategy=ExtractionStrategy.RULE_BASED
    )
    
    # Generate ontology
    print("Generating ontology from sample text...")
    ontology = generator.generate_ontology(sample_text, context)
    
    print(f"✓ Generated ontology:")
    print(f"  - Entities: {len(ontology['entities'])}")
    print(f"  - Relationships: {len(ontology['relationships'])}")
    print(f"  - Domain: {ontology['domain']}")
    print(f"  - Confidence: {ontology['metadata']['confidence']:.2f}")


def example_quality_evaluation():
    """Example 2: Ontology quality evaluation."""
    print("\n" + "="*60)
    print("Example 2: Ontology Quality Evaluation")
    print("="*60 + "\n")
    
    from ipfs_datasets_py.optimizers.graphrag import (
        OntologyGenerator,
        OntologyCritic,
        OntologyGenerationContext,
        ExtractionStrategy,
        DataType
    )
    
    # Generate sample ontology
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = OntologyGenerationContext(
        data_source='sample.txt',
        data_type=DataType.TEXT,
        domain='legal',
        extraction_strategy=ExtractionStrategy.RULE_BASED
    )
    
    sample_text = "Alice owns property X. Bob rents property X from Alice."
    ontology = generator.generate_ontology(sample_text, context)
    
    # Evaluate with critic
    print("Evaluating ontology quality...")
    critic = OntologyCritic(use_llm=False)  # Rule-based for demo
    score = critic.evaluate_ontology(ontology, context, sample_text)
    
    print(f"✓ Quality Evaluation:")
    print(f"  - Overall Score: {score.overall:.2f}")
    print(f"  - Completeness: {score.completeness:.2f}")
    print(f"  - Consistency: {score.consistency:.2f}")
    print(f"  - Clarity: {score.clarity:.2f}")
    print(f"  - Granularity: {score.granularity:.2f}")
    print(f"  - Domain Alignment: {score.domain_alignment:.2f}")
    
    if score.strengths:
        print(f"\n  Strengths:")
        for strength in score.strengths:
            print(f"    ✓ {strength}")
    
    if score.weaknesses:
        print(f"\n  Weaknesses:")
        for weakness in score.weaknesses:
            print(f"    ✗ {weakness}")
    
    if score.recommendations:
        print(f"\n  Recommendations:")
        for rec in score.recommendations:
            print(f"    → {rec}")


def example_logic_validation():
    """Example 3: Logical consistency validation."""
    print("\n" + "="*60)
    print("Example 3: Logical Consistency Validation")
    print("="*60 + "\n")
    
    from ipfs_datasets_py.optimizers.graphrag import (
        OntologyGenerator,
        LogicValidator,
        OntologyGenerationContext,
        ExtractionStrategy,
        DataType
    )
    
    # Generate sample ontology
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = OntologyGenerationContext(
        data_source='sample.txt',
        data_type=DataType.TEXT,
        domain='legal',
        extraction_strategy=ExtractionStrategy.RULE_BASED
    )
    
    sample_text = "Alice must pay Bob. Bob must receive payment from Alice."
    ontology = generator.generate_ontology(sample_text, context)
    
    # Validate logic
    print("Validating logical consistency...")
    validator = LogicValidator(use_cache=True)
    result = validator.check_consistency(ontology)
    
    print(f"✓ Validation Result:")
    print(f"  - Consistent: {result.is_consistent}")
    print(f"  - Confidence: {result.confidence:.2f}")
    print(f"  - Prover: {result.prover_used}")
    print(f"  - Time: {result.time_ms:.2f}ms")
    
    if result.contradictions:
        print(f"\n  Contradictions Found:")
        for contradiction in result.contradictions:
            print(f"    ✗ {contradiction}")
        
        # Get fix suggestions
        fixes = validator.suggest_fixes(ontology, result.contradictions)
        print(f"\n  Suggested Fixes:")
        for fix in fixes:
            print(f"    → {fix['description']}")
    else:
        print(f"\n  ✓ No contradictions detected!")


def example_refinement_cycle():
    """Example 4: Multi-round refinement cycle."""
    print("\n" + "="*60)
    print("Example 4: Multi-Round Refinement Cycle")
    print("="*60 + "\n")
    
    from ipfs_datasets_py.optimizers.graphrag import (
        OntologyGenerator,
        OntologyCritic,
        OntologyMediator,
        OntologyGenerationContext,
        ExtractionStrategy,
        DataType
    )
    
    # Setup components
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    critic = OntologyCritic(use_llm=False)
    
    mediator = OntologyMediator(
        generator=generator,
        critic=critic,
        max_rounds=5,
        convergence_threshold=0.80
    )
    
    # Create context
    context = OntologyGenerationContext(
        data_source='legal_contract.txt',
        data_type=DataType.TEXT,
        domain='legal',
        extraction_strategy=ExtractionStrategy.HYBRID
    )
    
    sample_text = """
    Alice agrees to sell property X to Bob for $100,000.
    Bob must pay within 30 days. Alice must transfer title upon payment.
    If Bob fails to pay, Alice may retain the deposit and cancel the sale.
    """
    
    # Run refinement cycle
    print("Running refinement cycle...")
    state = mediator.run_refinement_cycle(sample_text, context)
    
    print(f"\n✓ Refinement Complete:")
    print(f"  - Total Rounds: {state.current_round}")
    print(f"  - Converged: {state.converged}")
    print(f"  - Total Time: {state.total_time_ms:.2f}ms")
    print(f"  - Final Score: {state.metadata['final_score']:.2f}")
    print(f"  - Improvement: {state.metadata['improvement']:+.2f}")
    print(f"  - Trend: {state.metadata['score_trend']}")
    
    print(f"\n  Score History:")
    for i, score in enumerate(state.critic_scores):
        print(f"    Round {i}: {score.overall:.2f}")


def example_batch_optimization():
    """Example 5: Batch optimization with SGD."""
    print("\n" + "="*60)
    print("Example 5: Batch Optimization with SGD")
    print("="*60 + "\n")
    
    from ipfs_datasets_py.optimizers.graphrag import (
        OntologyGenerator,
        OntologyCritic,
        OntologyMediator,
        OntologyOptimizer,
        OntologyGenerationContext,
        ExtractionStrategy,
        DataType
    )
    
    # Setup components
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    critic = OntologyCritic(use_llm=False)
    mediator = OntologyMediator(generator, critic, max_rounds=3)
    optimizer = OntologyOptimizer()
    
    # Sample data sources
    data_sources = [
        "Alice must pay Bob $100.",
        "Carol owns property X.",
        "David is obligated to deliver goods to Eve.",
    ]
    
    # Run multiple sessions
    print("Running batch of sessions...")
    results = []
    for i, data in enumerate(data_sources):
        print(f"\n  Session {i+1}/{len(data_sources)}...")
        context = OntologyGenerationContext(
            data_source=f'contract_{i}.txt',
            data_type=DataType.TEXT,
            domain='legal',
            extraction_strategy=ExtractionStrategy.RULE_BASED
        )
        state = mediator.run_refinement_cycle(data, context)
        results.append(state)
    
    # Analyze batch
    print("\n\nAnalyzing batch...")
    report = optimizer.analyze_batch(results)
    
    print(f"\n✓ Batch Analysis:")
    print(f"  - Average Score: {report.average_score:.2f}")
    print(f"  - Trend: {report.trend}")
    print(f"  - Best Score: {report.metadata['score_range'][1]:.2f}")
    print(f"  - Worst Score: {report.metadata['score_range'][0]:.2f}")
    print(f"  - Std Dev: {report.metadata['score_std']:.2f}")
    
    print(f"\n  Score Distribution:")
    for dim, score in report.score_distribution.items():
        print(f"    {dim}: {score:.2f}")
    
    print(f"\n  Recommendations:")
    for rec in report.recommendations:
        print(f"    → {rec}")


def main():
    """Run all examples."""
    print("\n" + "#"*60)
    print("# GraphRAG Ontology Optimizer Examples")
    print("#"*60)
    
    try:
        example_basic_generation()
    except Exception as e:
        logger.error(f"Example 1 failed: {e}")
    
    try:
        example_quality_evaluation()
    except Exception as e:
        logger.error(f"Example 2 failed: {e}")
    
    try:
        example_logic_validation()
    except Exception as e:
        logger.error(f"Example 3 failed: {e}")
    
    try:
        example_refinement_cycle()
    except Exception as e:
        logger.error(f"Example 4 failed: {e}")
    
    try:
        example_batch_optimization()
    except Exception as e:
        logger.error(f"Example 5 failed: {e}")
    
    print("\n" + "#"*60)
    print("# All Examples Complete!")
    print("#"*60 + "\n")


if __name__ == '__main__':
    main()
