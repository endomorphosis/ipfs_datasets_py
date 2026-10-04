#!/usr/bin/env python3
"""Demonstration of Logic Theorem Optimizer System.

This script demonstrates the complete logic theorem optimizer system,
showing how to extract logical statements from arbitrary data using
SGD-based optimization.
"""

import sys
import logging
from typing import List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def demonstrate_basic_extraction():
    """Demonstrate basic logic extraction from text."""
    print("\n" + "="*70)
    print("1. BASIC LOGIC EXTRACTION")
    print("="*70)
    
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        LogicExtractor,
        LogicExtractionContext,
        ExtractionMode,
        DataType
    )
    
    # Create extractor
    extractor = LogicExtractor(model="gpt-4")
    
    # Sample data
    data = "All employees must complete training within 30 days"
    
    # Create context
    context = LogicExtractionContext(
        data=data,
        data_type=DataType.TEXT,
        extraction_mode=ExtractionMode.TDFOL,
        domain="legal"
    )
    
    # Extract
    print(f"\nInput: {data}")
    print("\nExtracting logical statements...")
    
    result = extractor.extract(context)
    
    if result.success:
        print(f"\n✓ Extraction successful!")
        print(f"  Extracted {len(result.statements)} statement(s)\n")
        
        for i, stmt in enumerate(result.statements, 1):
            print(f"  Statement {i}:")
            print(f"    Formula: {stmt.formula}")
            print(f"    Explanation: {stmt.natural_language}")
            print(f"    Confidence: {stmt.confidence:.2f}")
            print(f"    Formalism: {stmt.formalism}")
    else:
        print(f"\n✗ Extraction failed:")
        for error in result.errors:
            print(f"  - {error}")
    
    return extractor


def demonstrate_critic_evaluation(extractor):
    """Demonstrate critic evaluation of extracted logic."""
    print("\n" + "="*70)
    print("2. CRITIC EVALUATION")
    print("="*70)
    
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        LogicCritic,
        CriticDimensions,
        LogicExtractionContext,
        DataType
    )
    
    # Create critic
    critic = LogicCritic(use_provers=['z3'])
    
    # Extract some statements
    data = "Employees must complete training. Managers may approve exceptions."
    context = LogicExtractionContext(data=data, data_type=DataType.TEXT)
    result = extractor.extract(context)
    
    if not result.success:
        print("Extraction failed, skipping evaluation")
        return critic
    
    print(f"\nEvaluating {len(result.statements)} statement(s)...")
    
    # Evaluate
    score = critic.evaluate(result)
    
    print(f"\n✓ Evaluation complete!")
    print(f"\n  Overall Score: {score.overall:.2f}/1.00")
    print(f"\n  Dimension Scores:")
    
    for dim_score in score.dimension_scores:
        print(f"    {dim_score.dimension.value:20s}: {dim_score.score:.2f} - {dim_score.feedback}")
    
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
        for i, rec in enumerate(score.recommendations, 1):
            print(f"    {i}. {rec}")
    
    return critic


def demonstrate_single_session(extractor, critic):
    """Demonstrate a single theorem session with iterative refinement."""
    print("\n" + "="*70)
    print("3. SINGLE THEOREM SESSION")
    print("="*70)
    
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        TheoremSession,
        SessionConfig
    )
    
    # Create session
    config = SessionConfig(
        max_rounds=5,
        convergence_threshold=0.85
    )
    
    session = TheoremSession(extractor, critic, config)
    
    # Run session
    data = "All contractors must sign agreements before accessing facilities"
    
    print(f"\nInput: {data}")
    print(f"Max rounds: {config.max_rounds}")
    print(f"Convergence threshold: {config.convergence_threshold}")
    print("\nRunning extraction session with iterative refinement...\n")
    
    result = session.run(data)
    
    print(f"\n✓ Session complete!")
    print(f"\n  Success: {result.success}")
    print(f"  Converged: {result.converged}")
    print(f"  Rounds: {result.num_rounds}")
    print(f"  Time: {result.total_time:.2f}s")
    
    if result.success:
        print(f"  Final Score: {result.critic_score.overall:.2f}")
        print(f"  Statements: {len(result.extraction_result.statements)}")
        
        # Show round history
        print(f"\n  Round History:")
        for round_info in result.round_history:
            if round_info.get('extraction_success'):
                print(f"    Round {round_info['round']}: score={round_info['critic_score']:.2f}, "
                      f"statements={round_info['num_statements']}")
    
    return session


def demonstrate_batch_processing(extractor, critic):
    """Demonstrate batch processing with the harness."""
    print("\n" + "="*70)
    print("4. BATCH PROCESSING")
    print("="*70)
    
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        LogicHarness,
        HarnessConfig
    )
    
    # Create harness
    config = HarnessConfig(
        parallelism=2,  # Use 2 parallel workers
        max_retries=2
    )
    
    harness = LogicHarness(extractor, critic, config)
    
    # Sample data
    data_samples = [
        "All employees must complete training",
        "Managers may approve exceptions",
        "Contractors should sign agreements",
        "Documents must be archived within 7 days",
        "Users can access resources during business hours"
    ]
    
    print(f"\nProcessing {len(data_samples)} data samples...")
    print(f"Parallelism: {config.parallelism}")
    print(f"Max retries: {config.max_retries}\n")
    
    # Run batch
    result = harness.run_sessions(data_samples)
    
    print(f"\n✓ Batch processing complete!")
    print(f"\n  Total Sessions: {result.total_sessions}")
    print(f"  Successful: {result.successful_sessions}")
    print(f"  Failed: {result.failed_sessions}")
    print(f"  Success Rate: {result.successful_sessions / result.total_sessions:.1%}")
    print(f"\n  Average Score: {result.average_score:.2f}")
    print(f"  Best Score: {result.best_score:.2f}")
    print(f"  Worst Score: {result.worst_score:.2f}")
    print(f"\n  Total Time: {result.total_time:.2f}s")
    
    if result.metrics:
        print(f"\n  Additional Metrics:")
        if 'convergence_rate' in result.metrics:
            print(f"    Convergence Rate: {result.metrics['convergence_rate']:.1%}")
        if 'avg_rounds' in result.metrics:
            print(f"    Avg Rounds: {result.metrics['avg_rounds']:.1f}")
        if 'avg_statements' in result.metrics:
            print(f"    Avg Statements: {result.metrics['avg_statements']:.1f}")
    
    return result


def demonstrate_optimization(extractor, critic):
    """Demonstrate SGD-based optimization."""
    print("\n" + "="*70)
    print("5. SGD OPTIMIZATION")
    print("="*70)
    
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        LogicOptimizer,
        LogicHarness
    )
    
    # Create components
    optimizer = LogicOptimizer(
        convergence_threshold=0.85,
        min_improvement_rate=0.01
    )
    
    harness = LogicHarness(extractor, critic)
    
    # Sample data
    data_samples = [
        "All employees must complete training",
        "Managers may approve exceptions",
        "Documents must be archived"
    ]
    
    print(f"\nRunning SGD optimization cycles...")
    print(f"Data samples: {len(data_samples)}")
    print(f"Convergence threshold: {optimizer.convergence_threshold}")
    print()
    
    # Run multiple cycles
    num_cycles = 3
    
    for cycle in range(num_cycles):
        print(f"\n--- Cycle {cycle + 1}/{num_cycles} ---")
        
        # Run batch
        batch_result = harness.run_sessions(data_samples)
        
        # Analyze
        report = optimizer.analyze_batch(batch_result.session_results)
        
        print(f"\n  Average Score: {report.average_score:.2f}")
        print(f"  Trend: {report.trend}")
        print(f"  Convergence Status: {report.convergence_status}")
        
        if report.insights:
            print(f"\n  Insights:")
            for insight in report.insights:
                print(f"    • {insight}")
        
        if report.recommendations:
            print(f"\n  Recommendations:")
            for i, rec in enumerate(report.recommendations[:3], 1):
                print(f"    {i}. {rec}")
        
        # Check convergence
        if report.convergence_status == "converged":
            print(f"\n  ✓ Optimization converged after {cycle + 1} cycles!")
            break
    
    # Show final status
    params = optimizer.get_optimization_parameters()
    print(f"\n  Final Status:")
    print(f"    Iterations: {params['iterations_completed']}")
    print(f"    Final Score: {optimizer.score_history[-1]:.2f}")


def demonstrate_ontology_stabilizer():
    """Demonstrate ontology consistency checking."""
    print("\n" + "="*70)
    print("6. ONTOLOGY STABILIZER")
    print("="*70)
    
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        KnowledgeGraphStabilizer,
        OntologyConsistencyChecker,
        LogicExtractor,
        LogicExtractionContext
    )
    
    # Define ontology
    ontology = {
        'terms': ['Employee', 'Training', 'Manager', 'Document', 'Archive'],
        'relations': ['must', 'may', 'should', 'complete', 'approve'],
        'types': ['Agent', 'Action', 'Resource']
    }
    
    print("\nOntology:")
    print(f"  Terms: {len(ontology['terms'])}")
    print(f"  Relations: {len(ontology['relations'])}")
    print(f"  Types: {len(ontology['types'])}")
    
    # Create stabilizer
    stabilizer = KnowledgeGraphStabilizer(ontology, strict_mode=True)
    
    # Create checker
    checker = OntologyConsistencyChecker(ontology)
    
    # Extract some statements
    extractor = LogicExtractor()
    
    statements_data = [
        "All employees must complete training",
        "Managers may approve exceptions",
        "Documents must be archived"
    ]
    
    print(f"\nExtracting {len(statements_data)} statements and checking consistency...\n")
    
    all_statements = []
    for data in statements_data:
        context = LogicExtractionContext(data=data)
        result = extractor.extract(context)
        if result.success:
            all_statements.extend(result.statements)
    
    # Check consistency
    report = checker.check_statements(all_statements)
    
    print("✓ Consistency check complete!")
    print(f"\n  Consistent: {report.is_consistent}")
    print(f"  Coverage: {report.coverage:.2%}")
    
    if report.violations:
        print(f"\n  Violations ({len(report.violations)}):")
        for violation in report.violations:
            print(f"    ✗ {violation}")
    
    if report.warnings:
        print(f"\n  Warnings ({len(report.warnings)}):")
        for warning in report.warnings[:3]:  # Show first 3
            print(f"    ⚠ {warning}")
    
    if report.recommendations:
        print(f"\n  Recommendations ({len(report.recommendations)}):")
        for rec in report.recommendations[:3]:  # Show first 3
            print(f"    • {rec}")
    
    # Add to stabilizer
    print(f"\nAdding statements to knowledge graph...")
    added = stabilizer.add_statements(all_statements)
    
    print(f"\n  Statements added: {added}/{len(all_statements)}")
    print(f"  Stability score: {stabilizer.get_stability_score():.2f}")
    
    # Show statistics
    stats = stabilizer.get_statistics()
    print(f"\n  Statistics:")
    print(f"    Total statements: {stats['num_statements']}")
    print(f"    Current stability: {stats['current_stability']:.2f}")
    print(f"    Ontology size: {stats['ontology_size']['terms']} terms, "
          f"{stats['ontology_size']['relations']} relations")


def main():
    """Main demonstration function."""
    print("\n" + "="*70)
    print("LOGIC THEOREM OPTIMIZER DEMONSTRATION")
    print("="*70)
    print("\nThis demonstration shows the complete logic theorem optimizer system,")
    print("inspired by the adversarial harness pattern from complaint-generator.")
    
    try:
        # 1. Basic extraction
        extractor = demonstrate_basic_extraction()
        
        # 2. Critic evaluation
        critic = demonstrate_critic_evaluation(extractor)
        
        # 3. Single session
        demonstrate_single_session(extractor, critic)
        
        # 4. Batch processing
        batch_result = demonstrate_batch_processing(extractor, critic)
        
        # 5. SGD optimization
        demonstrate_optimization(extractor, critic)
        
        # 6. Ontology stabilizer
        demonstrate_ontology_stabilizer()
        
        print("\n" + "="*70)
        print("DEMONSTRATION COMPLETE")
        print("="*70)
        print("\n✓ All components demonstrated successfully!")
        print("\nFor more information, see:")
        print("  - README.md in this directory")
        print("  - Individual component documentation")
        print("  - Examples in the repository")
        print()
        
    except Exception as e:
        logger.error(f"Demonstration failed: {e}", exc_info=True)
        print(f"\n✗ Demonstration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
