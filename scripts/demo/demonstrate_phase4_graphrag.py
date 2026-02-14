#!/usr/bin/env python3
"""Demo script for Phase 4: Logic-Enhanced GraphRAG.

This script demonstrates the complete logic-enhanced RAG pipeline:
1. Logic-aware entity extraction
2. Knowledge graph construction
3. Theorem augmentation
4. Consistency checking
5. Logical query reasoning
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ipfs_datasets_py.search.logic_integration import LogicEnhancedRAG


def print_section(title: str):
    """Print section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def demo_legal_contract():
    """Demonstrate processing a legal contract."""
    print_section("DEMO: Legal Contract Processing")
    
    contract = """
    Service Level Agreement
    
    Provider Obligations:
    - The Provider must deliver services within 14 business days
    - The Provider shall maintain 99.9% uptime
    - The Provider must respond to incidents within 2 hours
    
    Client Obligations:
    - The Client must pay fees within 30 days of invoice
    - The Client shall provide necessary access credentials
    
    Permissions:
    - Either party may terminate with 90 days written notice
    - The Client may request service modifications
    
    Prohibitions:
    - The Provider must not disclose confidential client information
    - The Client must not reverse engineer the Provider's systems
    
    Conditional Terms:
    - If payment is more than 60 days late, then Provider may suspend services
    - When contract expires, all data must be returned immediately
    """
    
    # Initialize RAG system
    print("1. Initializing Logic-Enhanced RAG System...")
    rag = LogicEnhancedRAG(use_neural=False)
    print("   ✓ RAG system initialized\n")
    
    # Ingest contract
    print("2. Ingesting contract document...")
    result = rag.ingest_document(contract, "sla_001")
    print(f"   ✓ Extracted {result['entities_extracted']} logical entities")
    print(f"   ✓ Created {result['nodes_created']} knowledge graph nodes")
    print(f"   ✓ Found {result['relationships_extracted']} relationships")
    
    # Check consistency
    if result['is_consistent']:
        print(f"   ✓ Knowledge graph is logically consistent\n")
    else:
        print(f"   ⚠ Found {len(result['inconsistencies'])} inconsistencies:")
        for inc in result['inconsistencies']:
            print(f"      - {inc}")
        print()
    
    # Query 1: Provider obligations
    print("3. Querying: 'What must the Provider do?'")
    result1 = rag.query("Provider must deliver services")
    print(f"   Found {len(result1.relevant_nodes)} relevant nodes")
    print(f"   Confidence: {result1.confidence:.2f}")
    print("   Reasoning chain:")
    for step in result1.reasoning_chain:
        print(f"      • {step}")
    print()
    
    # Query 2: Client obligations
    print("4. Querying: 'What must the Client do?'")
    result2 = rag.query("Client must pay")
    print(f"   Found {len(result2.relevant_nodes)} relevant nodes")
    print(f"   Confidence: {result2.confidence:.2f}")
    if result2.relevant_nodes:
        print("   Top result:")
        node = result2.relevant_nodes[0]
        print(f"      • {node.entity.text} (type: {node.entity.entity_type.value})")
    print()
    
    # Query 3: Prohibitions
    print("5. Querying: 'What is prohibited?'")
    result3 = rag.query("must not disclose")
    print(f"   Found {len(result3.relevant_nodes)} relevant nodes")
    if result3.relevant_nodes:
        for node in result3.relevant_nodes[:3]:
            print(f"      • {node.entity.text}")
    print()
    
    # Query 4: Conditional logic
    print("6. Querying: 'What happens if payment is late?'")
    result4 = rag.query("if payment late then")
    print(f"   Found {len(result4.relevant_nodes)} relevant nodes")
    if result4.relevant_nodes:
        for node in result4.relevant_nodes[:2]:
            print(f"      • {node.entity.text}")
    print()
    
    # Export knowledge graph
    print("7. Exporting knowledge graph...")
    graph_export = rag.export_knowledge_graph()
    print(f"   ✓ Nodes: {len(graph_export['nodes'])}")
    print(f"   ✓ Edges: {len(graph_export['edges'])}")
    print(f"   ✓ Theorems: {len(graph_export['theorems'])}")
    print()
    
    # Get statistics
    print("8. System Statistics:")
    stats = rag.get_stats()
    print(f"   • Documents ingested: {stats['documents_ingested']}")
    print(f"   • Total nodes: {stats['nodes']}")
    print(f"   • Agents: {stats['agents']}")
    print(f"   • Obligations: {stats['obligations']}")
    print(f"   • Permissions: {stats['permissions']}")
    print(f"   • Prohibitions: {stats['prohibitions']}")


def demo_inconsistency_detection():
    """Demonstrate detection of logical inconsistencies."""
    print_section("DEMO: Logical Inconsistency Detection")
    
    inconsistent_contract = """
    Employee Agreement
    
    The Employee must share project data with the team.
    The Employee must not share project data with anyone.
    """
    
    print("Processing contract with contradictory clauses...\n")
    
    rag = LogicEnhancedRAG(use_neural=False)
    result = rag.ingest_document(inconsistent_contract, "employee_001")
    
    print(f"Entities extracted: {result['entities_extracted']}")
    print(f"Consistent: {result['is_consistent']}")
    
    if not result['is_consistent']:
        print(f"\n⚠ Detected {len(result['inconsistencies'])} inconsistencies:")
        for inc in result['inconsistencies']:
            print(f"   • {inc}")


def demo_theorem_augmentation():
    """Demonstrate theorem augmentation."""
    print_section("DEMO: Theorem Augmentation")
    
    print("Adding logical theorems to knowledge graph...\n")
    
    rag = LogicEnhancedRAG(use_neural=False)
    
    # Add some basic theorems
    print("1. Adding theorems:")
    theorems = [
        ("payment_obligation", "late_payment(X) -> may_suspend(X)"),
        ("delivery_rule", "must_deliver(X) -> owes_delivery(X)"),
        ("confidentiality_rule", "confidential(X) -> must_not_disclose(X)")
    ]
    
    for name, formula in theorems:
        success = rag.add_theorem(name, formula, auto_prove=False)
        status = "✓" if success else "✗"
        print(f"   {status} {name}: {formula}")
    
    print("\n2. Ingesting document that uses these concepts...")
    doc = "The Provider must deliver services. Client data is confidential."
    rag.ingest_document(doc, "service_doc")
    
    print("\n3. Querying with theorem inference...")
    result = rag.query("deliver services", use_inference=True)
    print(f"   Found {len(result.related_theorems)} related theorems")
    
    # Show theorem stats
    print("\n4. Theorem statistics:")
    stats = rag.get_stats()
    print(f"   • Total theorems: {stats.get('total_theorems', 0)}")
    print(f"   • Proven theorems: {stats.get('proven_theorems', 0)}")


def demo_entity_extraction():
    """Demonstrate entity extraction capabilities."""
    print_section("DEMO: Entity Extraction Capabilities")
    
    from ipfs_datasets_py.search.logic_integration import LogicAwareEntityExtractor
    
    extractor = LogicAwareEntityExtractor(use_neural=False)
    
    text = """
    Alice must pay Bob $1000 within 30 days.
    Carol may access the system with manager approval.
    Dave must not share passwords.
    If the deadline is missed, then penalties apply.
    The agreement is valid for 12 months.
    """
    
    print(f"Text to analyze:\n{text}\n")
    
    print("Extracting entities...\n")
    entities = extractor.extract_entities(text)
    
    # Group by type
    from collections import defaultdict
    by_type = defaultdict(list)
    for entity in entities:
        by_type[entity.entity_type.value].append(entity.text)
    
    print("Extracted entities by type:")
    for entity_type, texts in sorted(by_type.items()):
        print(f"\n  {entity_type.upper()}:")
        for text in texts:
            print(f"    • {text}")
    
    print(f"\n  Total: {len(entities)} entities extracted")


def main():
    """Run all demos."""
    print("\n" + "═" * 70)
    print("  PHASE 4: LOGIC-ENHANCED GRAPHRAG - DEMONSTRATION")
    print("═" * 70)
    
    try:
        # Demo 1: Entity extraction
        demo_entity_extraction()
        
        # Demo 2: Legal contract processing
        demo_legal_contract()
        
        # Demo 3: Inconsistency detection
        demo_inconsistency_detection()
        
        # Demo 4: Theorem augmentation
        demo_theorem_augmentation()
        
        print_section("DEMONSTRATION COMPLETE")
        print("✓ All features demonstrated successfully!")
        print("\nPhase 4 GraphRAG Integration is fully operational.\n")
        
    except Exception as e:
        print(f"\n✗ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
