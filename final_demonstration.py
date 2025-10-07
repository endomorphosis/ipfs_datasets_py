#!/usr/bin/env python3
"""
Final Demonstration: Temporal Deontic Logic RAG System

This script provides a concise demonstration of the key capabilities
of the temporal deontic logic RAG system for legal document debugging.
"""

import sys
import os
from datetime import datetime
sys.path.append(os.path.join(os.path.dirname(__file__), 'ipfs_datasets_py'))

from ipfs_datasets_py.logic_integration.deontic_logic_core import (
    DeonticFormula, DeonticOperator, LegalAgent
)
from ipfs_datasets_py.logic_integration.temporal_deontic_rag_store import (
    TemporalDeonticRAGStore
)
from ipfs_datasets_py.logic_integration.document_consistency_checker import (
    DocumentConsistencyChecker
)


def main():
    """Main demonstration of the temporal deontic logic RAG system."""
    
    print("⚖️  TEMPORAL DEONTIC LOGIC RAG SYSTEM")
    print("Legal Document Consistency Checker (Like a Debugger)")
    print("="*65)
    
    # Step 1: Create theorem corpus from "caselaw"
    print("\n📚 Step 1: Loading Temporal Deontic Logic Theorems from Caselaw")
    print("-"*65)
    
    rag_store = TemporalDeonticRAGStore()
    
    # Add key legal theorems
    theorems = [
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.PROHIBITION,
                proposition="disclose confidential information to third parties",
                agent=LegalAgent("professional", "Professional", "person")
            ),
            "temporal_scope": (datetime(2015, 1, 1), None),
            "jurisdiction": "Federal",
            "legal_domain": "confidentiality",
            "source_case": "Confidentiality Standards Act (2015)",
            "precedent_strength": 0.95
        },
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.OBLIGATION,
                proposition="provide written notice 30 days before termination",
                agent=LegalAgent("party", "Contract Party", "person")
            ),
            "temporal_scope": (datetime(2020, 1, 1), None),
            "jurisdiction": "Federal",
            "legal_domain": "contract",
            "source_case": "Contract Termination Standards (2020)",
            "precedent_strength": 0.90
        }
    ]
    
    for theorem in theorems:
        theorem_id = rag_store.add_theorem(**theorem)
        print(f"✅ Loaded: {theorem['source_case']}")
    
    print(f"📊 Corpus: {rag_store.get_statistics()['total_theorems']} theorems loaded")
    
    # Step 2: Create document consistency checker
    print("\n🔍 Step 2: Initializing Legal Document Debugger")
    print("-"*65)
    
    checker = DocumentConsistencyChecker(rag_store=rag_store)
    print("✅ Document consistency checker ready")
    
    # Step 3: Test consistent document
    print("\n📄 Step 3: Testing Consistent Legal Document")
    print("-"*65)
    
    good_document = """
    CONSULTING AGREEMENT
    
    1. The Consultant shall provide written notice at least 45 days 
       before contract termination.
       
    2. The Consultant must not disclose any confidential client 
       information to unauthorized third parties.
    """
    
    analysis_good = checker.check_document(
        document_text=good_document,
        document_id="good_contract.pdf",
        temporal_context=datetime(2023, 6, 1),
        jurisdiction="Federal",
        legal_domain="contract"
    )
    
    print(f"Document: good_contract.pdf")
    print(f"Result: {'✅ CONSISTENT' if analysis_good.consistency_result.is_consistent else '❌ CONFLICTS FOUND'}")
    print(f"Issues: {len(analysis_good.issues_found)} found")
    print(f"Confidence: {analysis_good.confidence_score:.2f}")
    
    # Step 4: Test conflicting document  
    print("\n🚨 Step 4: Testing Document with Legal Conflicts")
    print("-"*65)
    
    bad_document = """
    EMPLOYMENT CONTRACT
    
    1. Employee may share confidential company information with 
       external partners without restrictions.
       
    2. No advance notice required for contract termination.
    """
    
    analysis_bad = checker.check_document(
        document_text=bad_document,
        document_id="problematic_contract.pdf", 
        temporal_context=datetime(2023, 6, 1),
        jurisdiction="Federal",
        legal_domain="employment"
    )
    
    print(f"Document: problematic_contract.pdf")
    print(f"Result: {'✅ CONSISTENT' if analysis_bad.consistency_result.is_consistent else '❌ CONFLICTS FOUND'}")
    print(f"Issues: {len(analysis_bad.issues_found)} found")
    print(f"Confidence: {analysis_bad.confidence_score:.2f}")
    
    # Show detailed conflicts
    if analysis_bad.consistency_result.conflicts:
        print("\n🔍 Detected Conflicts:")
        for i, conflict in enumerate(analysis_bad.consistency_result.conflicts, 1):
            print(f"  {i}. {conflict.get('description', 'Conflict detected')}")
    
    # Step 5: Show RAG retrieval in action
    print("\n🔄 Step 5: RAG Theorem Retrieval Demo")
    print("-"*65)
    
    query_formula = DeonticFormula(
        operator=DeonticOperator.PERMISSION,
        proposition="share confidential information",
        agent=LegalAgent("employee", "Employee", "person")
    )
    
    relevant_theorems = rag_store.retrieve_relevant_theorems(
        query_formula=query_formula,
        temporal_context=datetime(2023, 6, 1),
        top_k=3
    )
    
    print(f"Query: 'Can employee share confidential information?'")
    print(f"Retrieved {len(relevant_theorems)} relevant theorems:")
    
    for i, theorem in enumerate(relevant_theorems, 1):
        print(f"  {i}. {theorem.formula.operator.value}: {theorem.formula.proposition[:50]}...")
        print(f"     Source: {theorem.source_case}")
        print(f"     Strength: {theorem.precedent_strength:.2f}")
    
    # Summary
    print("\n" + "="*65)
    print("✅ DEMONSTRATION COMPLETE")
    print("="*65)
    
    print("\n🎯 Key Capabilities Demonstrated:")
    print("  ✅ Temporal deontic logic theorem storage and indexing")
    print("  ✅ RAG-based retrieval of relevant legal precedents")
    print("  ✅ Document consistency checking against theorem corpus")
    print("  ✅ Conflict detection between document and existing law")
    print("  ✅ Debugger-style reporting of legal issues")
    print("  ✅ Temporal and jurisdictional filtering")
    
    print(f"\n📈 Performance Metrics:")
    print(f"  Processing time: {analysis_good.processing_time + analysis_bad.processing_time:.3f}s")
    print(f"  Documents analyzed: 2")
    print(f"  Conflicts detected: {len(analysis_bad.consistency_result.conflicts)}")
    print(f"  Theorems in corpus: {rag_store.get_statistics()['total_theorems']}")
    
    print("\n💡 This system works like a legal debugger, checking documents")
    print("   against temporal deontic logic theorems derived from caselaw,")
    print("   similar to how a compiler checks code against syntax rules.")


if __name__ == "__main__":
    main()