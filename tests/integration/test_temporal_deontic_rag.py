#!/usr/bin/env python3
"""
Simple test script for the Temporal Deontic Logic RAG system
"""

import sys
import os
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), "ipfs_datasets_py"))

from ipfs_datasets_py.logic.integration.deontic_logic_core import (
    DeonticFormula,
    DeonticOperator,
    LegalAgent,
)
from ipfs_datasets_py.logic.integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
from ipfs_datasets_py.logic.integration.document_consistency_checker import (
    DocumentConsistencyChecker,
)


def test_temporal_deontic_rag():
    """Test the temporal deontic logic RAG system."""
    print("🚀 Testing Temporal Deontic Logic RAG System")
    print("=" * 60)

    # Create a RAG store
    print("📚 Creating RAG store...")
    rag_store = TemporalDeonticRAGStore()

    # Add some sample theorems
    print("➕ Adding sample theorems...")

    # Theorem 1: Contract termination notice requirement
    theorem1 = DeonticFormula(
        operator=DeonticOperator.OBLIGATION,
        proposition="provide written notice 30 days before contract termination",
        agent=LegalAgent("party", "Contract Party", "person"),
        confidence=0.95,
        source_text="Contractor must provide written notice 30 days before termination",
    )

    theorem_id1 = rag_store.add_theorem(
        formula=theorem1,
        temporal_scope=(datetime(2020, 1, 1), None),
        jurisdiction="Federal",
        legal_domain="contract",
        source_case="Sample Contract Case (2020)",
        precedent_strength=0.9,
    )

    # Theorem 2: Confidentiality prohibition
    theorem2 = DeonticFormula(
        operator=DeonticOperator.PROHIBITION,
        proposition="disclose confidential client information to third parties",
        agent=LegalAgent("consultant", "Professional Consultant", "person"),
        confidence=0.98,
        source_text="Consultant shall not disclose confidential client information",
    )

    theorem_id2 = rag_store.add_theorem(
        formula=theorem2,
        temporal_scope=(datetime(2015, 1, 1), None),
        jurisdiction="Federal",
        legal_domain="professional_services",
        source_case="Confidentiality Case (2015)",
        precedent_strength=0.98,
    )

    print(f"✅ Added theorems: {theorem_id1[:8]}..., {theorem_id2[:8]}...")

    # Test RAG retrieval
    print("\n🔍 Testing RAG retrieval...")

    query_formula = DeonticFormula(
        operator=DeonticOperator.OBLIGATION,
        proposition="provide advance notice before termination",
        agent=LegalAgent("party", "Contract Party", "person"),
    )

    relevant_theorems = rag_store.retrieve_relevant_theorems(
        query_formula=query_formula, temporal_context=datetime(2023, 6, 1), top_k=5
    )

    print(f"📋 Found {len(relevant_theorems)} relevant theorems:")
    for i, theorem in enumerate(relevant_theorems, 1):
        print(f"  {i}. {theorem.formula.operator.value}: {theorem.formula.proposition[:50]}...")

    # Test document consistency checking
    print("\n📄 Testing document consistency checking...")

    checker = DocumentConsistencyChecker(rag_store=rag_store)

    # Test a document that should be consistent
    consistent_doc = """
    CONSULTING AGREEMENT
    
    1. The Consultant must provide written notice 45 days before 
       contract termination to allow for transition planning.
       
    2. The Consultant shall not disclose confidential client 
       information to any third parties without written consent.
    """

    analysis = checker.check_document(
        document_text=consistent_doc,
        document_id="test_consulting_agreement",
        temporal_context=datetime(2023, 6, 1),
        jurisdiction="Federal",
        legal_domain="professional_services",
    )

    print(f"📊 Analysis results:")
    print(f"  Document ID: {analysis.document_id}")
    print(f"  Formulas extracted: {len(analysis.extracted_formulas)}")
    print(f"  Issues found: {len(analysis.issues_found)}")
    print(f"  Confidence score: {analysis.confidence_score:.2f}")
    print(f"  Processing time: {analysis.processing_time:.2f}s")

    if analysis.consistency_result:
        print(
            f"  Consistency: {'✅ PASS' if analysis.consistency_result.is_consistent else '❌ FAIL'}"
        )
        print(f"  Logical conflicts: {len(analysis.consistency_result.conflicts)}")
        print(f"  Temporal conflicts: {len(analysis.consistency_result.temporal_conflicts)}")

    # Generate debug report
    debug_report = checker.generate_debug_report(analysis)
    print(f"\n📋 Debug Report Summary:")
    print(f"  Total issues: {debug_report.total_issues}")
    print(f"  Critical errors: {debug_report.critical_errors}")
    print(f"  Warnings: {debug_report.warnings}")
    print(f"  Suggestions: {debug_report.suggestions}")

    if debug_report.issues:
        print(f"  Issues:")
        for issue in debug_report.issues:
            print(
                f"    - {issue.get('severity', 'unknown').upper()}: {issue.get('message', 'No message')}"
            )

    # Test conflicting document
    print("\n⚠️  Testing conflicting document...")

    conflicting_doc = """
    EMPLOYMENT CONTRACT
    
    1. Employee may disclose confidential client information to third parties
       without any restrictions for business development purposes.
       
    2. No advance notice is required when terminating employment contracts.
    
    3. Employee shall not provide written notice 30 days before contract termination.
    """

    conflict_analysis = checker.check_document(
        document_text=conflicting_doc,
        document_id="test_conflicting_contract",
        temporal_context=datetime(2023, 6, 1),
        jurisdiction="Federal",
        legal_domain="employment",
    )

    conflict_report = checker.generate_debug_report(conflict_analysis)
    print(f"📊 Conflict Analysis:")
    print(f"  Issues found: {conflict_report.total_issues}")
    print(
        f"  Consistency: {'✅ PASS' if conflict_analysis.consistency_result and conflict_analysis.consistency_result.is_consistent else '❌ FAIL'}"
    )

    if conflict_report.issues:
        print(f"  Sample issues:")
        for issue in conflict_report.issues[:3]:  # Show first 3 issues
            print(
                f"    - {issue.get('severity', 'unknown').upper()}: {issue.get('message', 'No message')}"
            )

    # Show RAG store statistics
    print(f"\n📈 RAG Store Statistics:")
    stats = rag_store.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\n✅ Test completed successfully!")
    print("The system demonstrates legal document consistency checking")
    print("like a debugger, identifying conflicts with existing legal theorems.")


if __name__ == "__main__":
    try:
        test_temporal_deontic_rag()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
