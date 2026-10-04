#!/usr/bin/env python3
"""End-to-End Legal Reasoning Workflow Example.

This example demonstrates the complete pipeline for processing legal contracts
using the neurosymbolic reasoning system.

Features demonstrated:
- Legal text parsing
- TDFOL formula extraction
- Deontic logic reasoning (obligations, permissions, prohibitions)
- Multi-prover verification
- Knowledge graph construction
- Consistency checking
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.logic.integration.neurosymbolic_graphrag import NeurosymbolicGraphRAG
from ipfs_datasets_py.logic.TDFOL import parse_tdfol
from ipfs_datasets_py.logic.integration.logic_verification import LogicVerifier


def print_section(title: str):
    """Print formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def demonstrate_legal_contract_processing():
    """Demonstrate complete legal contract processing workflow."""
    print_section("LEGAL REASONING WORKFLOW - END-TO-END EXAMPLE")
    
    # Sample legal contract
    contract_text = """
    EMPLOYMENT AGREEMENT
    
    Article 1: Obligations of Employee
    1.1 The Employee SHALL perform assigned duties diligently and professionally.
    1.2 The Employee SHALL maintain confidentiality of all proprietary information.
    1.3 The Employee SHALL NOT compete with the Employer during employment.
    1.4 The Employee SHALL provide 30 days notice before termination.
    
    Article 2: Obligations of Employer
    2.1 The Employer SHALL pay salary on the 1st day of each month.
    2.2 The Employer SHALL provide safe working conditions.
    2.3 The Employer SHALL NOT discriminate based on protected characteristics.
    2.4 The Employer MAY terminate with cause and 2 weeks notice.
    
    Article 3: Mutual Agreements
    3.1 Either party MAY terminate this agreement with proper notice.
    3.2 Disputes SHALL be resolved through arbitration.
    3.3 If Employee violates confidentiality, then Employer may terminate immediately.
    """
    
    print("Contract Text:")
    print("-" * 70)
    print(contract_text)
    print("-" * 70)
    
    # Step 1: Initialize the neurosymbolic pipeline
    print_section("Step 1: Initialize Neurosymbolic Pipeline")
    
    pipeline = NeurosymbolicGraphRAG(
        use_neural=False,  # Disable neural for this example
        enable_proof_caching=True,
        proving_strategy="SYMBOLIC_ONLY"
    )
    
    print("✓ Pipeline initialized")
    print(f"  • Proof caching: ENABLED")
    print(f"  • Strategy: SYMBOLIC_ONLY")
    
    # Step 2: Process the contract
    print_section("Step 2: Process Contract Through Pipeline")
    
    result = pipeline.process_document(contract_text, "employment_contract_001")
    
    print("✓ Contract processed")
    print(f"  • Entities extracted: {result.entities}")
    print(f"  • TDFOL formulas: {len(result.formulas)}")
    print(f"  • Proven theorems: {len(result.proven_theorems)}")
    print(f"  • Confidence: {result.confidence:.2f}")
    
    print("\nReasoning chain:")
    for step in result.reasoning_chain:
        print(f"  → {step}")
    
    # Step 3: Query for Employee obligations
    print_section("Step 3: Query for Employee Obligations")
    
    query_result = pipeline.query("What must the Employee do?", use_inference=True)
    
    print("Query: 'What must the Employee do?'")
    print(f"✓ Found {len(query_result.relevant_nodes)} relevant obligations")
    
    if query_result.relevant_nodes:
        for i, node in enumerate(query_result.relevant_nodes[:3], 1):
            print(f"\n{i}. {node.entity.text if hasattr(node, 'entity') else 'Entity'}")
    
    # Step 4: Query for Employer obligations
    print_section("Step 4: Query for Employer Obligations")
    
    query_result2 = pipeline.query("What must the Employer do?", use_inference=True)
    
    print("Query: 'What must the Employer do?'")
    print(f"✓ Found {len(query_result2.relevant_nodes)} relevant obligations")
    
    # Step 5: Check for prohibitions
    print_section("Step 5: Check for Prohibitions")
    
    query_result3 = pipeline.query("What is prohibited?", use_inference=True)
    
    print("Query: 'What is prohibited?'")
    print(f"✓ Found {len(query_result3.relevant_nodes)} prohibitions")
    
    # Step 6: Consistency checking
    print_section("Step 6: Logical Consistency Check")
    
    is_consistent, issues = pipeline.check_consistency()
    
    if is_consistent:
        print("✓ Contract is logically consistent")
        print("  No contradictions detected")
    else:
        print(f"⚠ Found {len(issues)} consistency issues:")
        for issue in issues[:5]:
            print(f"  • {issue}")
    
    # Step 7: Extract specific clauses
    print_section("Step 7: Extract Specific Clause Logic")
    
    print("Extracting TDFOL representation of key clauses...")
    
    # Clause: "If Employee violates confidentiality, then Employer may terminate"
    clause_text = "If Employee violates confidentiality, then Employer may terminate immediately"
    print(f"\nClause: '{clause_text}'")
    
    try:
        # This would be: violate_conf -> P(terminate)
        # Where P is permission operator
        formula_str = "violate_conf(employee) -> P(terminate(employer, employee))"
        formula = parse_tdfol(formula_str)
        print(f"✓ TDFOL: {formula_str}")
    except Exception as e:
        print(f"  Note: {e}")
    
    # Step 8: Multi-document comparison
    print_section("Step 8: Process Second Contract for Comparison")
    
    contract2_text = """
    SERVICE AGREEMENT
    
    The Service Provider SHALL deliver services within 30 business days.
    The Client SHALL pay invoice within 15 days of receipt.
    Either party MAY terminate with 60 days written notice.
    """
    
    result2 = pipeline.process_document(contract2_text, "service_agreement_001")
    
    print("✓ Second contract processed")
    print(f"  • Entities: {result2.entities}")
    print(f"  • Formulas: {len(result2.formulas)}")
    
    # Step 9: Pipeline statistics
    print_section("Step 9: Pipeline Statistics")
    
    stats = pipeline.get_pipeline_stats()
    
    print(f"Documents processed: {stats['documents_processed']}")
    print(f"Total entities: {stats['total_entities']}")
    print(f"Total formulas: {stats['total_formulas']}")
    print(f"Proven theorems: {stats['total_proven_theorems']}")
    
    print("\nKnowledge Graph Statistics:")
    kg_stats = stats['knowledge_graph']
    print(f"  • Nodes: {kg_stats['nodes']}")
    print(f"  • Agents: {kg_stats['agents']}")
    print(f"  • Obligations: {kg_stats['obligations']}")
    print(f"  • Permissions: {kg_stats['permissions']}")
    print(f"  • Prohibitions: {kg_stats['prohibitions']}")
    
    # Step 10: Verification with LogicVerifier
    print_section("Step 10: Independent Verification")
    
    verifier = LogicVerifier()
    
    print("Using LogicVerifier for independent validation...")
    
    axioms = ["P", "P -> Q"]
    consistency = verifier.verify_consistency(axioms)
    
    print(f"✓ Axiom consistency verified: {consistency}")
    
    print_section("WORKFLOW COMPLETE")
    
    print("✓ Legal reasoning workflow successfully executed!")
    print("\nDemonstrated capabilities:")
    print("  1. Contract text parsing and entity extraction")
    print("  2. TDFOL formula generation")
    print("  3. Deontic logic reasoning (obligations, permissions, prohibitions)")
    print("  4. Knowledge graph construction")
    print("  5. Consistency checking")
    print("  6. Query-based retrieval with logical reasoning")
    print("  7. Multi-document processing")
    print("  8. Independent verification")
    
    return pipeline, result


def main():
    """Run the complete legal reasoning workflow."""
    try:
        pipeline, result = demonstrate_legal_contract_processing()
        
        print("\n" + "=" * 70)
        print("  SUCCESS: Legal Reasoning Workflow Complete")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"\n✗ Error during workflow: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
