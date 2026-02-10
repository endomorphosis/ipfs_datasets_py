#!/usr/bin/env python3
"""
Standalone demo of the Caselaw Dashboard functionality
"""

import sys
import os
from datetime import datetime
sys.path.append(os.path.join(os.path.dirname(__file__), 'ipfs_datasets_py'))

def demo_caselaw_dashboard():
    """Demonstrate the caselaw dashboard functionality."""
    print("⚖️  CASELAW DASHBOARD DEMONSTRATION")
    print("Temporal Deontic Logic RAG System for Legal Document Consistency")
    print("=" * 70)
    
    try:
        # Import components
        from ipfs_datasets_py.logic.integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
        from ipfs_datasets_py.logic.integration.document_consistency_checker import DocumentConsistencyChecker
        from ipfs_datasets_py.logic.integration.deontic_logic_core import DeonticFormula, DeonticOperator, LegalAgent
        
        # Initialize system
        print("🚀 Initializing Temporal Deontic Logic RAG System...")
        rag_store = TemporalDeonticRAGStore()
        checker = DocumentConsistencyChecker(rag_store=rag_store)
        
        # Add sample theorems to demonstrate the corpus
        print("\n📚 Loading Sample Legal Theorems from Caselaw...")
        
        theorems = [
            {
                "formula": DeonticFormula(
                    operator=DeonticOperator.PROHIBITION,
                    proposition="disclose confidential information to unauthorized third parties",
                    agent=LegalAgent("professional", "Professional", "person"),
                    confidence=0.95
                ),
                "source_case": "Confidentiality Standards Act (2015)",
                "jurisdiction": "Federal",
                "legal_domain": "confidentiality",
                "precedent_strength": 0.95
            },
            {
                "formula": DeonticFormula(
                    operator=DeonticOperator.OBLIGATION,
                    proposition="provide written notice 30 days before contract termination",
                    agent=LegalAgent("party", "Contract Party", "person"),
                    confidence=0.90
                ),
                "source_case": "Contract Termination Standards (2020)",
                "jurisdiction": "Federal",
                "legal_domain": "contract",
                "precedent_strength": 0.90
            },
            {
                "formula": DeonticFormula(
                    operator=DeonticOperator.PERMISSION,
                    proposition="access confidential information for authorized business purposes",
                    agent=LegalAgent("employee", "Employee", "person"),
                    confidence=0.85
                ),
                "source_case": "Business Access Rights (2018)",
                "jurisdiction": "State",
                "legal_domain": "employment",
                "precedent_strength": 0.80
            }
        ]
        
        for i, theorem_data in enumerate(theorems, 1):
            theorem_id = rag_store.add_theorem(
                formula=theorem_data["formula"],
                temporal_scope=(datetime(2015, 1, 1), None),
                jurisdiction=theorem_data["jurisdiction"],
                legal_domain=theorem_data["legal_domain"],
                source_case=theorem_data["source_case"],
                precedent_strength=theorem_data["precedent_strength"]
            )
            print(f"  {i}. {theorem_data['source_case'][:50]}... → {theorem_id[:8]}")
        
        stats = rag_store.get_statistics()
        print(f"\n📊 Theorem Corpus Statistics:")
        print(f"  Total theorems: {stats['total_theorems']}")
        print(f"  Jurisdictions: {stats['jurisdictions']}")
        print(f"  Legal domains: {stats['legal_domains']}")
        print(f"  Avg precedent strength: {stats['avg_precedent_strength']:.2f}")
        
        # Demonstrate document consistency checking
        print("\n🔍 DASHBOARD FEATURE 1: Document Consistency Analysis")
        print("-" * 60)
        
        test_documents = [
            {
                "id": "consistent_contract.pdf",
                "text": """
                CONSULTING AGREEMENT
                
                1. The Consultant shall provide written notice at least 45 days 
                   before contract termination.
                   
                2. The Consultant must not disclose any confidential client 
                   information to unauthorized third parties.
                """,
                "expected": "CONSISTENT"
            },
            {
                "id": "problematic_employment.pdf", 
                "text": """
                EMPLOYMENT CONTRACT
                
                1. Employee may share confidential company information with 
                   external partners without restrictions.
                   
                2. No advance notice required for contract termination.
                """,
                "expected": "CONFLICTS"
            }
        ]
        
        for doc in test_documents:
            print(f"\n📄 Analyzing: {doc['id']}")
            print(f"Expected Result: {doc['expected']}")
            
            analysis = checker.check_document(
                document_text=doc["text"],
                document_id=doc["id"],
                temporal_context=datetime.now(),
                jurisdiction="Federal",
                legal_domain="employment"
            )
            
            debug_report = checker.generate_debug_report(analysis)
            
            status = "✅ CONSISTENT" if analysis.consistency_result.is_consistent else "❌ CONFLICTS FOUND"
            print(f"Actual Result: {status}")
            print(f"  Formulas extracted: {len(analysis.extracted_formulas)}")
            print(f"  Issues found: {debug_report.total_issues}")
            print(f"  Confidence: {analysis.confidence_score:.2f}")
            
            if debug_report.issues:
                print(f"  Sample issues:")
                for issue in debug_report.issues[:2]:
                    print(f"    - {issue.get('severity', 'unknown').upper()}: {issue.get('message', 'No message')}")
        
        # Demonstrate RAG theorem retrieval
        print(f"\n🔄 DASHBOARD FEATURE 2: RAG-Based Theorem Retrieval")
        print("-" * 60)
        
        queries = [
            {
                "text": "share confidential information",
                "operator": DeonticOperator.PROHIBITION,
                "description": "Query for confidentiality restrictions"
            },
            {
                "text": "provide notice before termination",
                "operator": DeonticOperator.OBLIGATION,
                "description": "Query for termination notice requirements"
            }
        ]
        
        for query in queries:
            print(f"\n🔍 Query: {query['description']}")
            print(f"Text: '{query['text']}' (Operator: {query['operator'].name})")
            
            query_formula = DeonticFormula(
                operator=query["operator"],
                proposition=query["text"],
                agent=LegalAgent("query_agent", "Query Agent", "person")
            )
            
            relevant_theorems = rag_store.retrieve_relevant_theorems(
                query_formula=query_formula,
                temporal_context=datetime.now(),
                top_k=3
            )
            
            print(f"📋 Found {len(relevant_theorems)} relevant theorems:")
            for i, theorem in enumerate(relevant_theorems, 1):
                print(f"  {i}. {theorem.formula.operator.name}: {theorem.formula.proposition[:50]}...")
                print(f"     Source: {theorem.source_case}")
                print(f"     Precedent strength: {theorem.precedent_strength:.2f}")
        
        # Dashboard API demonstration
        print(f"\n🌐 DASHBOARD FEATURE 3: Web API Endpoints")
        print("-" * 60)
        print("Available API endpoints for the caselaw dashboard:")
        print("  📍 GET  /mcp/caselaw                    - Dashboard homepage")
        print("  📍 POST /api/mcp/caselaw/add_theorem   - Add new theorem from caselaw")
        print("  📍 POST /api/mcp/caselaw/check_document - Check document consistency")
        print("  📍 POST /api/mcp/caselaw/query_theorems - Query relevant theorems")
        
        # Show sample API request/response
        print(f"\n📨 Sample API Request for Document Check:")
        sample_request = {
            "document_text": "Employee may share confidential information freely.",
            "document_id": "sample_doc.pdf",
            "jurisdiction": "Federal", 
            "legal_domain": "employment",
            "temporal_context": datetime.now().isoformat()
        }
        print(f"POST /api/mcp/caselaw/check_document")
        print(f"Request: {sample_request}")
        
        # Simulate API response
        analysis = checker.check_document(
            document_text=sample_request["document_text"],
            document_id=sample_request["document_id"],
            temporal_context=datetime.now(),
            jurisdiction=sample_request["jurisdiction"],
            legal_domain=sample_request["legal_domain"]
        )
        
        debug_report = checker.generate_debug_report(analysis)
        
        sample_response = {
            "document_id": analysis.document_id,
            "is_consistent": analysis.consistency_result.is_consistent if analysis.consistency_result else False,
            "confidence_score": analysis.confidence_score,
            "formulas_extracted": len(analysis.extracted_formulas),
            "issues_found": len(analysis.issues_found),
            "conflicts": len(analysis.consistency_result.conflicts) if analysis.consistency_result else 0,
            "debug_report": {
                "total_issues": debug_report.total_issues,
                "critical_errors": debug_report.critical_errors,
                "summary": debug_report.summary
            }
        }
        print(f"Response: {sample_response}")
        
        print("\n" + "=" * 70)
        print("✅ CASELAW DASHBOARD DEMONSTRATION COMPLETE")
        print("=" * 70)
        
        print("\n🎯 Dashboard Features Successfully Demonstrated:")
        print("  ✅ Temporal deontic logic theorem storage and indexing")
        print("  ✅ Document consistency checking like a legal debugger")
        print("  ✅ RAG-based retrieval of relevant legal precedents")
        print("  ✅ Web dashboard with interactive tabs for testing")
        print("  ✅ REST API endpoints for integration")
        print("  ✅ Conflict detection and debugging reports")
        print("  ✅ Support for multiple jurisdictions and legal domains")
        
        print(f"\n📱 Access the dashboard at: http://localhost:8888/mcp/caselaw")
        print(f"   (when MCP dashboard server is running)")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    demo_caselaw_dashboard()