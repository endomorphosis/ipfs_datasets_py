#!/usr/bin/env python3
"""
Comprehensive Legal Document Debugger Demo

This script demonstrates the complete temporal deontic logic RAG system
functioning as a legal debugger, similar to how a compiler debugger works for code.
"""

import sys
import os
from datetime import datetime, timedelta
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


def create_comprehensive_legal_corpus():
    """Create a comprehensive corpus of legal theorems from various domains."""
    print("📚 Building Comprehensive Legal Theorem Corpus")
    print("="*70)
    
    rag_store = TemporalDeonticRAGStore()
    
    # Employment Law Theorems
    employment_theorems = [
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.PROHIBITION,
                proposition="terminate employment without cause during probationary period",
                agent=LegalAgent("employer", "Employer", "organization"),
                source_text="Employer cannot terminate without cause during first 90 days"
            ),
            "temporal_scope": (datetime(2019, 1, 1), None),
            "jurisdiction": "Federal",
            "legal_domain": "employment",
            "source_case": "Employment Protection Act (2019)",
            "precedent_strength": 0.95
        },
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.OBLIGATION,
                proposition="provide minimum 2 weeks notice before employment termination",
                agent=LegalAgent("employee", "Employee", "person"),
                source_text="Employee must give 2 weeks notice"
            ),
            "temporal_scope": (datetime(2018, 1, 1), None),
            "jurisdiction": "State",
            "legal_domain": "employment",
            "source_case": "Standard Employment Practices (2018)",
            "precedent_strength": 0.80
        }
    ]
    
    # Contract Law Theorems
    contract_theorems = [
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.OBLIGATION,
                proposition="provide written notice 30 days before contract termination",
                agent=LegalAgent("party", "Contract Party", "person"),
                source_text="Written notice required 30 days prior to termination"
            ),
            "temporal_scope": (datetime(2020, 1, 1), None),
            "jurisdiction": "Federal", 
            "legal_domain": "contract",
            "source_case": "Commercial Contract Standards (2020)",
            "precedent_strength": 0.90
        },
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.PROHIBITION,
                proposition="modify contract terms without mutual written consent",
                agent=LegalAgent("party", "Contract Party", "person"),
                source_text="No unilateral contract modifications allowed"
            ),
            "temporal_scope": (datetime(2017, 6, 1), None),
            "jurisdiction": "Federal",
            "legal_domain": "contract", 
            "source_case": "Contract Modification Rules (2017)",
            "precedent_strength": 0.88
        }
    ]
    
    # Privacy/Confidentiality Theorems
    privacy_theorems = [
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.PROHIBITION,
                proposition="disclose confidential client information to unauthorized third parties",
                agent=LegalAgent("professional", "Professional", "person"),
                source_text="Strict confidentiality must be maintained"
            ),
            "temporal_scope": (datetime(2015, 1, 1), None),
            "jurisdiction": "Federal",
            "legal_domain": "privacy",
            "source_case": "Professional Confidentiality Standards (2015)",
            "precedent_strength": 0.98
        },
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.PERMISSION,
                proposition="access confidential information solely for authorized business purposes",
                agent=LegalAgent("employee", "Authorized Employee", "person"),
                source_text="Limited access for business purposes only"
            ),
            "temporal_scope": (datetime(2018, 3, 1), datetime(2028, 3, 1)),
            "jurisdiction": "Federal",
            "legal_domain": "privacy",
            "source_case": "Data Access Regulations (2018)",
            "precedent_strength": 0.85
        }
    ]
    
    # Professional Services Theorems
    professional_theorems = [
        {
            "formula": DeonticFormula(
                operator=DeonticOperator.OBLIGATION,
                proposition="maintain professional liability insurance minimum $1M coverage",
                agent=LegalAgent("consultant", "Professional Consultant", "person"),
                source_text="$1M minimum professional liability insurance required"
            ),
            "temporal_scope": (datetime(2021, 1, 1), None),
            "jurisdiction": "State",
            "legal_domain": "professional_services",
            "source_case": "Professional Standards Act (2021)",
            "precedent_strength": 0.92
        }
    ]
    
    all_theorems = employment_theorems + contract_theorems + privacy_theorems + professional_theorems
    
    print(f"Adding {len(all_theorems)} theorems to corpus...")
    
    for i, theorem_data in enumerate(all_theorems, 1):
        theorem_id = rag_store.add_theorem(**theorem_data)
        domain = theorem_data['legal_domain']
        case = theorem_data['source_case']
        print(f"  {i:2d}. [{domain:15s}] {case[:40]}... → {theorem_id[:8]}")
    
    stats = rag_store.get_statistics()
    print(f"\n📊 Corpus Statistics:")
    print(f"  Total theorems: {stats['total_theorems']}")
    print(f"  Jurisdictions: {stats['jurisdictions']}")
    print(f"  Legal domains: {stats['legal_domains']}")
    print(f"  Avg precedent strength: {stats['avg_precedent_strength']:.2f}")
    
    return rag_store


def demo_legal_debugger():
    """Demonstrate the legal debugger with various document scenarios."""
    print("\n" + "="*70)
    print("🔍 LEGAL DOCUMENT DEBUGGER DEMONSTRATION")
    print("Like a Compiler Debugger for Legal Documents")
    print("="*70)
    
    # Build the legal theorem corpus
    rag_store = create_comprehensive_legal_corpus()
    checker = DocumentConsistencyChecker(rag_store=rag_store)
    
    # Test Case 1: Clean Document (No Issues)
    print("\n" + "─"*70)
    print("📄 TEST CASE 1: Clean Professional Services Contract")
    print("─"*70)
    
    clean_document = """
    PROFESSIONAL CONSULTING AGREEMENT
    
    1. TERMINATION NOTICE: The Consultant agrees to provide written notice 
       at least 45 days before contract termination to ensure proper transition.
       
    2. INSURANCE: Consultant must maintain professional liability insurance 
       with minimum coverage of $2,000,000 throughout the contract period.
       
    3. CONFIDENTIALITY: Consultant may access confidential client information 
       solely for authorized business purposes related to this engagement.
       
    4. NON-DISCLOSURE: Consultant shall not disclose any confidential client 
       information to unauthorized third parties under any circumstances.
       
    5. CONTRACT MODIFICATIONS: Any changes to this agreement require 
       mutual written consent from both parties.
    """
    
    analysis1 = checker.check_document(
        document_text=clean_document,
        document_id="professional_consulting_v1.0",
        temporal_context=datetime(2023, 8, 15),
        jurisdiction="Federal",
        legal_domain="professional_services"
    )
    
    print_legal_debug_report(analysis1, checker)
    
    # Test Case 2: Document with Critical Errors
    print("\n" + "─"*70)
    print("📄 TEST CASE 2: Employment Contract with Critical Conflicts")
    print("─"*70)
    
    problematic_document = """
    EMPLOYMENT AGREEMENT
    
    1. TERMINATION: Company may terminate this employment immediately 
       without cause at any time during the first 6 months.
       
    2. NOTICE: Employee is not required to provide any notice before 
       leaving the company and may quit without advance warning.
       
    3. CONFIDENTIALITY SHARING: Employee may share confidential company 
       information with external consultants and business partners 
       without restriction to facilitate business development.
       
    4. CONTRACT CHANGES: Company reserves the right to modify this 
       agreement unilaterally without employee consent.
       
    5. INSURANCE: No professional liability insurance required.
    """
    
    analysis2 = checker.check_document(
        document_text=problematic_document,
        document_id="employment_contract_v2.1_BROKEN",
        temporal_context=datetime(2023, 9, 1),
        jurisdiction="Federal", 
        legal_domain="employment"
    )
    
    print_legal_debug_report(analysis2, checker)
    
    # Test Case 3: Temporal Conflicts (Legacy Document)
    print("\n" + "─"*70)
    print("📄 TEST CASE 3: Legacy Contract with Temporal Issues")
    print("─"*70)
    
    legacy_document = """
    LEGACY CONSULTING CONTRACT (Effective 2016)
    
    1. NOTICE PERIOD: Consultant shall provide 15 days written notice 
       before contract termination (legacy standard).
       
    2. INSURANCE: Professional liability insurance requirement set at 
       $500,000 minimum coverage (2016 standards).
       
    3. CONFIDENTIALITY: Client information confidentiality obligations 
       expire after 3 years from contract end date.
       
    4. MODIFICATIONS: Contract may be modified with verbal agreement 
       between parties (pre-2017 practice).
    """
    
    analysis3 = checker.check_document(
        document_text=legacy_document,
        document_id="legacy_consulting_2016",
        temporal_context=datetime(2016, 8, 1),  # Old temporal context
        jurisdiction="Federal",
        legal_domain="professional_services"
    )
    
    print_legal_debug_report(analysis3, checker)
    
    # Summary Statistics
    print("\n" + "="*70)
    print("📊 LEGAL DEBUGGER SUMMARY REPORT")
    print("="*70)
    
    all_analyses = [analysis1, analysis2, analysis3]
    test_cases = ["Clean Contract", "Problematic Employment", "Legacy Contract"]
    
    total_issues = 0
    total_conflicts = 0
    
    for i, (analysis, case_name) in enumerate(zip(all_analyses, test_cases), 1):
        debug_report = checker.generate_debug_report(analysis)
        consistency = analysis.consistency_result
        
        status_icon = "✅" if debug_report.total_issues == 0 else "❌"
        confidence_color = "🟢" if analysis.confidence_score > 0.8 else "🟡" if analysis.confidence_score > 0.5 else "🔴"
        
        print(f"\n{i}. {status_icon} {case_name}")
        print(f"   Issues: {debug_report.critical_errors} critical, {debug_report.warnings} warnings")
        print(f"   Confidence: {confidence_color} {analysis.confidence_score:.2f}")
        print(f"   Conflicts: {len(consistency.conflicts) if consistency else 0} logical, {len(consistency.temporal_conflicts) if consistency else 0} temporal")
        print(f"   Processing: {analysis.processing_time:.3f}s")
        
        total_issues += debug_report.total_issues
        if consistency:
            total_conflicts += len(consistency.conflicts) + len(consistency.temporal_conflicts)
    
    print(f"\n📈 Overall Statistics:")
    print(f"   Documents analyzed: {len(all_analyses)}")
    print(f"   Total issues found: {total_issues}")
    print(f"   Total conflicts detected: {total_conflicts}")
    print(f"   Success rate: {(len([a for a in all_analyses if len(checker.generate_debug_report(a).issues) == 0]) / len(all_analyses) * 100):.1f}%")


def print_legal_debug_report(analysis, checker):
    """Print a detailed legal debug report like a compiler error output."""
    debug_report = checker.generate_debug_report(analysis)
    consistency = analysis.consistency_result
    
    # Header
    print(f"\n🔍 LEGAL DEBUG REPORT: {analysis.document_id}")
    print("─" * 60)
    
    # Overall Status
    status_icon = "✅ PASS" if debug_report.total_issues == 0 else "❌ FAIL"
    confidence_bar = "█" * int(analysis.confidence_score * 10) + "░" * (10 - int(analysis.confidence_score * 10))
    
    print(f"Status: {status_icon}")
    print(f"Confidence: [{confidence_bar}] {analysis.confidence_score:.2f}")
    print(f"Processing Time: {analysis.processing_time:.3f}s")
    print(f"Formulas Extracted: {len(analysis.extracted_formulas)}")
    
    if consistency:
        print(f"Relevant Precedents: {len(consistency.relevant_theorems)}")
        print(f"Logical Conflicts: {len(consistency.conflicts)}")
        print(f"Temporal Conflicts: {len(consistency.temporal_conflicts)}")
    
    # Issues Section (like compiler errors)
    if debug_report.total_issues > 0:
        print(f"\n🚨 ISSUES FOUND ({debug_report.total_issues}):")
        print("─" * 40)
        
        for i, issue in enumerate(debug_report.issues, 1):
            severity_icons = {
                "critical": "🚨 CRITICAL ERROR",
                "error": "❌ ERROR", 
                "medium": "⚠️  WARNING",
                "warning": "⚠️  WARNING",
                "low": "💡 SUGGESTION",
                "suggestion": "💡 SUGGESTION"
            }
            
            severity = issue.get("severity", "unknown")
            icon = severity_icons.get(severity, "ℹ️  INFO")
            category = issue.get("category", "general")
            
            print(f"{i:2d}. {icon}")
            print(f"    Category: {category}")
            print(f"    Message: {issue.get('message', 'No message provided')}")
            if issue.get('suggestion'):
                print(f"    Fix: {issue['suggestion']}")
            
            # Show details if available
            if issue.get('details'):
                details = issue['details']
                if isinstance(details, dict):
                    for key, value in details.items():
                        if key != 'statement':  # Skip verbose formula statements
                            print(f"    {key}: {str(value)[:60]}{'...' if len(str(value)) > 60 else ''}")
            print()
    
    # Recommendations Section
    if debug_report.fix_suggestions:
        print("💡 RECOMMENDATIONS:")
        print("─" * 20)
        for i, suggestion in enumerate(debug_report.fix_suggestions, 1):
            print(f"{i}. {suggestion}")
    
    # Consistency Analysis
    if consistency and consistency.reasoning:
        print(f"\n📋 ANALYSIS REASONING:")
        print("─" * 25)
        reasoning_lines = consistency.reasoning.split('\n')
        for line in reasoning_lines:
            if line.strip():
                print(f"  {line}")
    
    print("─" * 60)


if __name__ == "__main__":
    print("⚖️  Legal Document Debugger - Comprehensive Demo")
    print("Temporal Deontic Logic RAG System for Legal Consistency")
    print()
    
    try:
        demo_legal_debugger()
        
        print("\n" + "="*70)
        print("✅ LEGAL DEBUGGER DEMO COMPLETED SUCCESSFULLY!")
        print()
        print("This system demonstrates how legal documents can be analyzed")
        print("like source code, with a debugger that identifies logical")
        print("conflicts, temporal issues, and consistency violations")
        print("against a corpus of legal theorems derived from caselaw.")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()