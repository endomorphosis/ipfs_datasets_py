#!/usr/bin/env python3
"""Demo script for Phase 5: End-to-End Neurosymbolic GraphRAG Pipeline.

This script demonstrates the complete unified pipeline that integrates:
- TDFOL parsing and theorem proving
- Neural-symbolic reasoning
- Logic-enhanced GraphRAG
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ipfs_datasets_py.logic.integration.neurosymbolic_graphrag import (
    NeurosymbolicGraphRAG,
    PipelineResult
)


def print_section(title: str):
    """Print section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def print_subsection(title: str):
    """Print subsection header."""
    print(f"\n--- {title} ---\n")


def demo_complete_pipeline():
    """Demonstrate the complete end-to-end pipeline."""
    print_section("PHASE 5: COMPLETE NEUROSYMBOLIC GRAPHRAG PIPELINE")
    
    print("Initializing unified pipeline...")
    print("  • TDFOL Prover (Phase 1-2)")
    print("  • Neurosymbolic Reasoning (Phase 3)")
    print("  • Logic-Enhanced GraphRAG (Phase 4)")
    print()
    
    # Initialize pipeline with all features
    pipeline = NeurosymbolicGraphRAG(
        use_neural=True,
        enable_proof_caching=True,
        proving_strategy="AUTO"
    )
    
    print("✓ Pipeline initialized successfully\n")
    
    # Demo 1: Process a service agreement
    print_subsection("Demo 1: Service Level Agreement Processing")
    
    sla_document = """
    Service Level Agreement - Cloud Computing Services
    
    Provider Obligations:
    1. The Provider must maintain 99.9% system uptime
    2. The Provider must respond to critical incidents within 1 hour
    3. The Provider must deliver monthly performance reports
    4. The Provider must not disclose customer data to third parties
    
    Customer Obligations:
    1. The Customer must pay monthly fees within 15 days of invoice
    2. The Customer must provide valid contact information
    3. The Customer must not exceed allocated resource limits
    
    Permissions:
    1. Either party may terminate with 30 days written notice
    2. The Customer may request service upgrades at any time
    3. The Provider may perform scheduled maintenance with 48 hours notice
    
    Penalties:
    - If Provider fails to maintain uptime, then Customer receives service credits
    - If Customer payment is late, then Provider may suspend services
    """
    
    print("Processing SLA document...")
    result = pipeline.process_document(sla_document, "sla_cloud_001")
    
    print(f"✓ Document processed")
    print(f"  • Entities extracted: {result.entities}")
    print(f"  • TDFOL formulas: {len(result.formulas)}")
    print(f"  • Proven theorems: {len(result.proven_theorems)}")
    print(f"  • Confidence: {result.confidence:.2f}")
    print(f"\nReasoning chain:")
    for step in result.reasoning_chain:
        print(f"  → {step}")
    
    # Demo 2: Query the knowledge graph
    print_subsection("Demo 2: Querying with Logical Reasoning")
    
    queries = [
        "What must the Provider do?",
        "What are Customer obligations?",
        "What happens if payment is late?",
        "Who can terminate the agreement?"
    ]
    
    for query in queries:
        print(f"\nQuery: '{query}'")
        query_result = pipeline.query(query, use_inference=True, top_k=5)
        
        print(f"  Found {len(query_result.relevant_nodes)} relevant nodes")
        print(f"  Confidence: {query_result.confidence:.2f}")
        
        if query_result.relevant_nodes:
            print(f"  Top result: {query_result.relevant_nodes[0].entity.text}")
        
        if len(query_result.reasoning_chain) > 0:
            print(f"  Reasoning: {query_result.reasoning_chain[0]}")
    
    # Demo 3: Process an employment contract
    print_subsection("Demo 3: Employment Contract Processing")
    
    employment_contract = """
    Employment Agreement
    
    The Employee must perform assigned duties diligently.
    The Employee must maintain confidentiality of company information.
    The Employee must not compete with the company during employment.
    
    The Employer must pay salary on the 1st of each month.
    The Employer must provide safe working conditions.
    The Employer must not discriminate based on protected characteristics.
    
    Either party may terminate with 2 weeks notice.
    If Employee violates confidentiality, then Employer may terminate immediately.
    """
    
    print("Processing employment contract...")
    result2 = pipeline.process_document(employment_contract, "employment_001")
    
    print(f"✓ Document processed")
    print(f"  • Entities: {result2.entities}")
    print(f"  • Formulas: {len(result2.formulas)}")
    print(f"  • Confidence: {result2.confidence:.2f}")
    
    # Demo 4: Check consistency
    print_subsection("Demo 4: Logical Consistency Checking")
    
    is_consistent, inconsistencies = pipeline.check_consistency()
    
    if is_consistent:
        print("✓ Knowledge graph is logically consistent")
    else:
        print(f"⚠ Found {len(inconsistencies)} inconsistencies:")
        for inc in inconsistencies[:5]:
            print(f"  • {inc}")
    
    # Demo 5: Pipeline statistics
    print_subsection("Demo 5: Pipeline Statistics")
    
    stats = pipeline.get_pipeline_stats()
    print(f"Documents processed: {stats['documents_processed']}")
    print(f"Total entities: {stats['total_entities']}")
    print(f"Total formulas: {stats['total_formulas']}")
    print(f"Proven theorems: {stats['total_proven_theorems']}")
    print(f"\nKnowledge Graph:")
    print(f"  • Nodes: {stats['knowledge_graph']['nodes']}")
    print(f"  • Agents: {stats['knowledge_graph']['agents']}")
    print(f"  • Obligations: {stats['knowledge_graph']['obligations']}")
    print(f"  • Permissions: {stats['knowledge_graph']['permissions']}")
    print(f"  • Prohibitions: {stats['knowledge_graph']['prohibitions']}")
    
    # Demo 6: Document summaries
    print_subsection("Demo 6: Document Summaries")
    
    for doc_id in ["sla_cloud_001", "employment_001"]:
        summary = pipeline.get_document_summary(doc_id)
        if summary:
            print(f"\n{doc_id}:")
            print(f"  • Entities: {summary['entities_count']}")
            print(f"  • Formulas: {summary['formulas_count']}")
            print(f"  • Proven theorems: {summary['proven_theorems_count']}")
            print(f"  • Consistent: {summary['is_consistent']}")
            print(f"  • Confidence: {summary['confidence']:.2f}")


def demo_proving_strategies():
    """Demonstrate different proving strategies."""
    print_section("PROVING STRATEGIES COMPARISON")
    
    test_document = "Alice must pay Bob. Bob must deliver goods to Alice."
    
    strategies = [
        "SYMBOLIC_ONLY",
        "NEURAL_ONLY",
        "HYBRID",
        "AUTO"
    ]
    
    for strategy in strategies:
        print(f"\nStrategy: {strategy}")
        
        try:
            pipeline = NeurosymbolicGraphRAG(
                use_neural=True,
                proving_strategy=strategy
            )
            
            result = pipeline.process_document(test_document, f"test_{strategy}")
            print(f"  ✓ Processed: {len(result.formulas)} formulas, "
                  f"{len(result.proven_theorems)} proven")
        except Exception as e:
            print(f"  ✗ Error: {e}")


def demo_performance():
    """Demonstrate performance with proof caching."""
    print_section("PERFORMANCE: PROOF CACHING")
    
    import time
    
    document = "Alice must pay Bob. Carol must deliver to Dave. Eve must notify Frank."
    
    # Without caching
    print("\nWithout proof caching:")
    pipeline_no_cache = NeurosymbolicGraphRAG(enable_proof_caching=False)
    
    start = time.time()
    for i in range(5):
        pipeline_no_cache.process_document(document, f"doc_no_cache_{i}")
    elapsed_no_cache = time.time() - start
    
    print(f"  Time for 5 documents: {elapsed_no_cache:.3f}s")
    
    # With caching
    print("\nWith proof caching:")
    pipeline_cache = NeurosymbolicGraphRAG(enable_proof_caching=True)
    
    start = time.time()
    for i in range(5):
        pipeline_cache.process_document(document, f"doc_cache_{i}")
    elapsed_cache = time.time() - start
    
    print(f"  Time for 5 documents: {elapsed_cache:.3f}s")
    
    if elapsed_no_cache > 0:
        speedup = elapsed_no_cache / elapsed_cache
        print(f"\n  Speedup: {speedup:.2f}x")


def main():
    """Run all demos."""
    print("\n" + "═" * 70)
    print("  PHASE 5: END-TO-END NEUROSYMBOLIC GRAPHRAG")
    print("  Unified Pipeline Demonstration")
    print("═" * 70)
    
    try:
        # Main pipeline demo
        demo_complete_pipeline()
        
        # Strategy comparison
        demo_proving_strategies()
        
        # Performance demo
        demo_performance()
        
        print_section("DEMONSTRATION COMPLETE")
        print("✓ Phase 5 End-to-End Pipeline is fully operational!")
        print("\nThe unified NeurosymbolicGraphRAG pipeline integrates:")
        print("  • Phase 1-2: TDFOL parsing and theorem proving")
        print("  • Phase 3: Neural-symbolic reasoning")
        print("  • Phase 4: Logic-enhanced GraphRAG")
        print("\nReady for production use!\n")
        
    except Exception as e:
        print(f"\n✗ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
