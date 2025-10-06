#!/usr/bin/env python3
"""
Temporal Deontic Logic RAG System Demo

This script demonstrates the temporal deontic logic RAG system for document
consistency checking, functioning like a debugger for legal documents.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore, TheoremMetadata
from logic_integration.document_consistency_checker import DocumentConsistencyChecker
from logic_integration.deontic_logic_core import (
    DeonticFormula, DeonticOperator, LegalAgent, LegalContext, TemporalCondition
)


def create_sample_theorem_corpus() -> TemporalDeonticRAGStore:
    """Create a sample corpus of temporal deontic logic theorems from mock caselaw."""
    print("📚 Creating sample theorem corpus from mock caselaw...")
    
    rag_store = TemporalDeonticRAGStore()
    
    # Sample theorems derived from mock legal cases
    theorems = [
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.OBLIGATION,
                proposition="provide written notice 30 days before contract termination",
                agent=LegalAgent("party", "Contract Party", "person"),
                confidence=0.95,
                source_text="Contractor must provide written notice 30 days before termination"
            ),
            "temporal_scope": (datetime(2020, 1, 1), None),  # Effective from 2020
            "jurisdiction": "Federal",
            "legal_domain": "contract",
            "source_case": "Smith v. Jones Contract Dispute (2020)",
            "precedent_strength": 0.9
        },
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.PROHIBITION,
                proposition="terminate contract without cause during first 6 months",
                agent=LegalAgent("employer", "Employer", "organization"),
                confidence=0.88,
                source_text="Employer shall not terminate without cause in first 6 months"
            ),
            "temporal_scope": (datetime(2019, 6, 1), None),
            "jurisdiction": "State",
            "legal_domain": "employment",
            "source_case": "Johnson v. ABC Corp (2019)",
            "precedent_strength": 0.85
        },
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.PERMISSION,
                proposition="access confidential information for business purposes",
                agent=LegalAgent("employee", "Employee", "person"),
                confidence=0.92,
                source_text="Employee may access confidential info for business purposes"
            ),
            "temporal_scope": (datetime(2018, 1, 1), datetime(2025, 12, 31)),
            "jurisdiction": "Federal",
            "legal_domain": "employment", 
            "source_case": "Confidentiality Standards Case (2018)",
            "precedent_strength": 0.75
        },
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.OBLIGATION,
                proposition="maintain professional liability insurance of minimum $1M",
                agent=LegalAgent("consultant", "Professional Consultant", "person"),
                confidence=0.94,
                source_text="Consultant must maintain $1M professional liability insurance"
            ),
            "temporal_scope": (datetime(2021, 1, 1), None),
            "jurisdiction": "State",
            "legal_domain": "professional_services",
            "source_case": "Professional Standards Act (2021)",
            "precedent_strength": 0.95
        },
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.PROHIBITION,
                proposition="disclose confidential client information to third parties",
                agent=LegalAgent("consultant", "Professional Consultant", "person"),
                confidence=0.98,
                source_text="Consultant shall not disclose confidential client information"
            ),
            "temporal_scope": (datetime(2015, 1, 1), None),
            "jurisdiction": "Federal",
            "legal_domain": "professional_services",
            "source_case": "Attorney-Client Privilege Extension (2015)",
            "precedent_strength": 0.98
        }
    ]
    
    # Add theorems to the RAG store
    for theorem_data in theorems:
        theorem_id = rag_store.add_theorem(**theorem_data)
        print(f"  ✅ Added theorem {theorem_id[:8]}: {theorem_data['formula'].proposition[:50]}...")
    
    stats = rag_store.get_statistics()
    print(f"📊 Corpus statistics: {stats['total_theorems']} theorems, "
          f"{stats['jurisdictions']} jurisdictions, {stats['legal_domains']} domains")
    
    return rag_store


def demo_document_consistency_checking():
    """Demonstrate document consistency checking like a legal debugger."""
    print("\n" + "="*80)
    print("🔍 TEMPORAL DEONTIC LOGIC RAG SYSTEM DEMO")
    print("Legal Document Consistency Checker (Like a Debugger)")
    print("="*80)
    
    # Create theorem corpus
    rag_store = create_sample_theorem_corpus()
    
    # Create document consistency checker
    checker = DocumentConsistencyChecker(rag_store=rag_store)
    
    print("\n📄 Testing document consistency against theorem corpus...")
    
    # Test Case 1: Consistent Document
    print("\n" + "-"*60)
    print("TEST CASE 1: Consistent Document")
    print("-"*60)
    
    consistent_document = """
    CONSULTING AGREEMENT
    
    1. The Consultant must maintain professional liability insurance 
       of minimum $2M coverage throughout the contract period.
       
    2. The Consultant shall provide written notice 45 days before 
       contract termination to allow for transition planning.
       
    3. The Consultant may access confidential client information 
       solely for legitimate business purposes related to this agreement.
       
    4. Upon termination, Consultant must return all confidential 
       information and cease access to client systems.
    """
    
    analysis1 = checker.check_document(
        document_text=consistent_document,
        document_id="consulting_agreement_v1",
        temporal_context=datetime(2023, 6, 1),
        jurisdiction="Federal",
        legal_domain="professional_services"
    )
    
    debug_report1 = checker.generate_debug_report(analysis1)
    print_debug_report(debug_report1)
    
    # Test Case 2: Document with Conflicts
    print("\n" + "-"*60)
    print("TEST CASE 2: Document with Logical Conflicts")
    print("-"*60)
    
    conflicting_document = """
    EMPLOYMENT CONTRACT
    
    1. Employee may access all confidential company information
       and share it with external consultants as needed.
       
    2. Company may terminate this employment contract immediately
       without cause during the probationary period of 6 months.
       
    3. Employee is not required to provide any notice before
       leaving the company.
       
    4. Employee must maintain confidentiality but may disclose
       information if it benefits business development.
    """
    
    analysis2 = checker.check_document(
        document_text=conflicting_document,
        document_id="employment_contract_v2",
        temporal_context=datetime(2023, 8, 1),
        jurisdiction="State",
        legal_domain="employment"
    )
    
    debug_report2 = checker.generate_debug_report(analysis2)
    print_debug_report(debug_report2)
    
    # Test Case 3: Temporal Conflict
    print("\n" + "-"*60)
    print("TEST CASE 3: Document with Temporal Conflicts")
    print("-"*60)
    
    temporal_conflict_document = """
    LEGACY CONTRACT (Effective 2017)
    
    1. Contractor must provide 15 days notice before termination.
    
    2. Professional liability insurance requirement is $500K minimum.
    
    3. Confidentiality obligations expire after 2 years.
    """
    
    analysis3 = checker.check_document(
        document_text=temporal_conflict_document,
        document_id="legacy_contract_2017",
        temporal_context=datetime(2017, 3, 1),  # Old temporal context
        jurisdiction="Federal",
        legal_domain="contract"
    )
    
    debug_report3 = checker.generate_debug_report(analysis3)
    print_debug_report(debug_report3)
    
    # Summary
    print("\n" + "="*80)
    print("📊 ANALYSIS SUMMARY")
    print("="*80)
    
    all_analyses = [analysis1, analysis2, analysis3]
    
    for i, analysis in enumerate(all_analyses, 1):
        print(f"\nDocument {i}: {analysis.document_id}")
        print(f"  Formulas extracted: {len(analysis.extracted_formulas)}")
        print(f"  Issues found: {len(analysis.issues_found)}")
        print(f"  Confidence score: {analysis.confidence_score:.2f}")
        print(f"  Processing time: {analysis.processing_time:.2f}s")
        
        if analysis.consistency_result:
            print(f"  Consistency: {'✅ PASS' if analysis.consistency_result.is_consistent else '❌ FAIL'}")
            print(f"  Logical conflicts: {len(analysis.consistency_result.conflicts)}")
            print(f"  Temporal conflicts: {len(analysis.consistency_result.temporal_conflicts)}")


def print_debug_report(debug_report):
    """Print a debug report in a compiler-like format."""
    print(f"\n📋 DEBUG REPORT for {debug_report.document_id}")
    print("=" * 50)
    
    print(debug_report.summary)
    
    if debug_report.issues:
        print(f"\nISSUES FOUND ({debug_report.total_issues}):")
        print("-" * 30)
        
        for i, issue in enumerate(debug_report.issues, 1):
            severity_icon = {
                "critical": "🚨",
                "error": "❌", 
                "medium": "⚠️",
                "warning": "⚠️",
                "low": "💡",
                "suggestion": "💡"
            }.get(issue.get("severity", ""), "ℹ️")
            
            print(f"{i}. {severity_icon} [{issue.get('severity', 'unknown').upper()}] "
                  f"{issue.get('category', 'general')}")
            print(f"   Message: {issue.get('message', 'No message')}")
            if issue.get('suggestion'):
                print(f"   Fix: {issue['suggestion']}")
            print()
    
    if debug_report.fix_suggestions:
        print("RECOMMENDATIONS:")
        print("-" * 20)
        for i, suggestion in enumerate(debug_report.fix_suggestions, 1):
            print(f"{i}. {suggestion}")
    
    print("=" * 50)


def demo_batch_processing():
    """Demonstrate batch processing of multiple documents."""
    print("\n" + "="*80)
    print("🔄 BATCH DOCUMENT PROCESSING DEMO")
    print("="*80)
    
    # Create theorem corpus and checker
    rag_store = create_sample_theorem_corpus()
    checker = DocumentConsistencyChecker(rag_store=rag_store)
    
    # Sample documents for batch processing
    documents = [
        ("""
        Contract A: Consultant must provide 30 days notice and maintain $1M insurance.
        Consultant may access confidential data for business purposes only.
        """, "contract_a"),
        
        ("""
        Contract B: Employee may terminate immediately without notice.
        Company prohibits access to confidential information but allows it for consultants.
        """, "contract_b"),
        
        ("""
        Contract C: Professional must maintain insurance and provide reasonable notice.
        Confidentiality must be maintained except when legally required to disclose.
        """, "contract_c")
    ]
    
    # Run batch analysis
    results = checker.batch_check_documents(
        documents, 
        temporal_context=datetime(2023, 9, 1),
        jurisdiction="Federal",
        legal_domain="contract"
    )
    
    # Print batch results
    print(f"\n📊 Batch processing completed: {len(results)} documents analyzed")
    
    for analysis in results:
        debug_report = checker.generate_debug_report(analysis)
        print(f"\n{analysis.document_id}: "
              f"{'✅ CLEAN' if debug_report.total_issues == 0 else f'❌ {debug_report.total_issues} issues'} "
              f"(confidence: {analysis.confidence_score:.2f})")


def demo_rag_retrieval():
    """Demonstrate RAG-style theorem retrieval."""
    print("\n" + "="*80)
    print("🔍 RAG THEOREM RETRIEVAL DEMO")
    print("="*80)
    
    # Create theorem corpus
    rag_store = create_sample_theorem_corpus()
    
    # Test queries
    test_queries = [
        DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="provide advance notice before termination",
            agent=LegalAgent("party", "Contract Party", "person")
        ),
        DeonticFormula(
            operator=DeonticOperator.PERMISSION,
            proposition="access company confidential information",
            agent=LegalAgent("employee", "Employee", "person")
        ),
        DeonticFormula(
            operator=DeonticOperator.PROHIBITION,
            proposition="terminate contract during probationary period",
            agent=LegalAgent("employer", "Employer", "organization")
        )
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n📋 Query {i}: {query.operator.value}({query.proposition})")
        print("-" * 50)
        
        relevant_theorems = rag_store.retrieve_relevant_theorems(
            query_formula=query,
            temporal_context=datetime(2023, 6, 1),
            top_k=3
        )
        
        if relevant_theorems:
            for j, theorem in enumerate(relevant_theorems, 1):
                print(f"{j}. {theorem.formula.operator.value}({theorem.formula.proposition[:60]}...)")
                print(f"   Source: {theorem.source_case}")
                print(f"   Jurisdiction: {theorem.jurisdiction}")
                print(f"   Precedent strength: {theorem.precedent_strength:.2f}")
                print()
        else:
            print("No relevant theorems found.")


if __name__ == "__main__":
    print("🚀 Starting Temporal Deontic Logic RAG System Demo")
    
    try:
        # Run all demos
        demo_document_consistency_checking()
        demo_batch_processing()
        demo_rag_retrieval()
        
        print("\n" + "="*80)
        print("✅ Demo completed successfully!")
        print("The system demonstrates legal document consistency checking")
        print("like a debugger, identifying conflicts with existing legal theorems.")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()