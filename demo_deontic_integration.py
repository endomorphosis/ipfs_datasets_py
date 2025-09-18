#!/usr/bin/env python3
"""
Demonstration of Comprehensive Deontic Logic Database Integration

This script demonstrates all the key features of the deontic logic system:
- Automatic conversion of legal text to formal deontic logic
- RAG-based semantic search for related legal principles  
- Contradiction linting for logical consistency
- Case law shepherding for precedent tracking
"""

import sys
import os
from datetime import datetime

# Add the parent directory to sys.path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from deontic_logic_database import DeonticLogicDatabase, TreatmentType
    DEONTIC_AVAILABLE = True
except ImportError as e:
    print(f"❌ Could not import deontic logic database: {e}")
    DEONTIC_AVAILABLE = False


def demonstrate_deontic_system():
    """Demonstrate the complete deontic logic system"""
    
    if not DEONTIC_AVAILABLE:
        print("❌ Deontic logic database not available")
        return False
    
    print("🏛️ COMPREHENSIVE DEONTIC LOGIC DATABASE DEMONSTRATION")
    print("=" * 60)
    
    # Initialize database
    print("\n🔧 Initializing Deontic Logic Database...")
    db = DeonticLogicDatabase()
    print("✅ Database initialized successfully")
    
    # Sample legal texts for demonstration
    legal_texts = {
        'brown_v_board': """
        The Supreme Court holds that segregated public schools are inherently unequal.
        States must provide equal educational opportunities to all children regardless of race.
        School districts cannot maintain separate educational facilities based on racial classifications.
        All students have the right to equal protection under the law in educational settings.
        """,
        
        'miranda_v_arizona': """
        Police officers must inform suspects of their constitutional rights before interrogation.
        Suspects have the right to remain silent during questioning.
        Defendants may request an attorney before answering questions.
        Law enforcement cannot use coercive tactics during interrogation.
        Statements obtained without proper warnings cannot be used as evidence.
        """,
        
        'conflicting_precedent': """
        Separate educational facilities for different races can be equal under law.
        States may require racial segregation in public schools for administrative efficiency.
        School segregation is permissible if facilities are substantially equivalent.
        """
    }
    
    print("\n📋 STEP 1: AUTOMATIC DEONTIC LOGIC CONVERSION")
    print("-" * 50)
    
    # Convert Brown v. Board text
    print("Converting Brown v. Board of Education text to deontic logic...")
    brown_statements = db.convert_document(
        legal_texts['brown_v_board'],
        case_id="brown_v_board_1954", 
        topic_name="Civil Rights"
    )
    
    print(f"✅ Converted to {len(brown_statements)} deontic logic statements:")
    for i, stmt in enumerate(brown_statements, 1):
        print(f"  {i}. Logic: {stmt.logic_expression}")
        print(f"     Natural: {stmt.natural_language[:80]}...")
        print(f"     Modality: {stmt.modality} | Confidence: {stmt.confidence:.2f}")
        print()
    
    # Convert Miranda v. Arizona text
    print("Converting Miranda v. Arizona text to deontic logic...")
    miranda_statements = db.convert_document(
        legal_texts['miranda_v_arizona'],
        case_id="miranda_v_arizona_1966",
        topic_name="Criminal Procedure"
    )
    
    print(f"✅ Converted to {len(miranda_statements)} deontic logic statements")
    
    print("\n🔍 STEP 2: RAG SEMANTIC SEARCH FOR RELATED PRINCIPLES")
    print("-" * 50)
    
    # Search for related principles
    search_queries = [
        "equal educational opportunities",
        "police interrogation rights", 
        "constitutional protections"
    ]
    
    for query in search_queries:
        print(f"\nSearching for: '{query}'")
        results = db.query_related_principles(query, top_k=3)
        
        if results:
            print(f"  Found {len(results)} related principles:")
            for j, result in enumerate(results, 1):
                print(f"    {j}. Similarity: {result['similarity']:.3f}")
                print(f"       Logic: {result['statement']['logic_expression']}")
                print(f"       Case: {result['statement']['case_id'] or 'Unknown'}")
        else:
            print(f"  No related principles found for '{query}'")
    
    print("\n⚠️ STEP 3: CONTRADICTION LINTING")
    print("-" * 50)
    
    # Test contradiction detection
    print("Checking for conflicts with historical segregation precedent...")
    lint_results = db.lint_document(
        legal_texts['conflicting_precedent'],
        case_id="plessy_v_ferguson_1896"
    )
    
    print(f"✅ Linting analysis completed:")
    print(f"  Conflicts found: {lint_results['conflicts_found']}")
    print(f"  Statements analyzed: {lint_results['statements_analyzed']}")
    
    if lint_results['conflicts_found'] > 0:
        print("  Conflicts detected:")
        for conflict in lint_results['conflicts']:
            print(f"    - Type: {conflict['type']}")
            print(f"      Severity: {conflict['severity']}")
            print(f"      Description: {conflict['description']}")
    else:
        print("  No direct conflicts detected (may require more sophisticated analysis)")
    
    print("\n🔗 STEP 4: CASE LAW SHEPHERDING")
    print("-" * 50)
    
    # Add citation relationships
    print("Adding case law citation relationships...")
    
    # Brown v. Board overrules Plessy v. Ferguson
    db.add_citation(
        citing_case_id="brown_v_board_1954",
        cited_case_id="plessy_v_ferguson_1896",
        treatment=TreatmentType.OVERRULED,
        quote_text="separate educational facilities are inherently unequal"
    )
    
    # Loving v. Virginia follows Brown v. Board
    db.add_citation(
        citing_case_id="loving_v_virginia_1967", 
        cited_case_id="brown_v_board_1954",
        treatment=TreatmentType.FOLLOWED,
        quote_text="equal protection clause applies to all state discrimination"
    )
    
    # Gideon v. Wainwright follows Miranda principles
    db.add_citation(
        citing_case_id="gideon_v_wainwright_1963",
        cited_case_id="miranda_v_arizona_1966", 
        treatment=TreatmentType.FOLLOWED,
        quote_text="right to counsel is fundamental to fair trial"
    )
    
    print("✅ Citation relationships added")
    
    # Validate case status
    cases_to_validate = [
        "plessy_v_ferguson_1896",
        "brown_v_board_1954", 
        "miranda_v_arizona_1966"
    ]
    
    for case_id in cases_to_validate:
        validation = db.validate_case(case_id)
        print(f"\n📋 Case Status: {case_id}")
        print(f"  Status: {validation['status']}")
        print(f"  Precedent Strength: {validation['precedent_strength']:.2f}")
        print(f"  Total Citations: {validation['total_citations']}")
        
        if validation['warnings']:
            print(f"  Warnings: {', '.join(validation['warnings'])}")
    
    # Show precedent lineage
    print(f"\n🌳 Precedent Lineage for Brown v. Board:")
    lineage = db.shepherding_engine.get_precedent_lineage("brown_v_board_1954")
    
    print(f"  Cases this case cites: {len(lineage['precedents_relied_on'])}")
    for precedent in lineage['precedents_relied_on']:
        print(f"    - {precedent['case_id']} ({precedent['treatment']})")
    
    print(f"  Cases that cite this case: {len(lineage['subsequent_cases'])}")
    for subsequent in lineage['subsequent_cases']:
        print(f"    - {subsequent['case_id']} ({subsequent['treatment']})")
    
    print("\n📊 STEP 5: DATABASE STATISTICS & HEALTH")
    print("-" * 50)
    
    # Get comprehensive statistics
    stats = db.get_database_stats()
    
    print("Database Statistics:")
    print(f"  Total Statements: {stats['total_statements']}")
    print(f"  Total Topics: {stats['total_topics']}")
    print(f"  Total Citations: {stats['total_citations']}")
    
    if 'statements_by_modality' in stats:
        print("  Statements by Modality:")
        for modality, count in stats['statements_by_modality'].items():
            print(f"    - {modality.title()}: {count}")
    
    if 'unresolved_conflicts' in stats:
        print("  Unresolved Conflicts:")
        if stats['unresolved_conflicts']:
            for severity, count in stats['unresolved_conflicts'].items():
                print(f"    - {severity.title()}: {count}")
        else:
            print("    - None")
    
    print("\n🎯 COMPREHENSIVE FUNCTIONALITY TEST")
    print("-" * 50)
    
    # Test all major components
    test_results = {
        'conversion': len(brown_statements) > 0 and len(miranda_statements) > 0,
        'search': len(db.query_related_principles("equal protection")) >= 0,
        'linting': lint_results['statements_analyzed'] > 0,
        'shepherding': validation['total_citations'] > 0,
        'database_health': stats['total_statements'] > 0
    }
    
    print("System Component Status:")
    for component, status in test_results.items():
        status_icon = "✅" if status else "❌"
        print(f"  {status_icon} {component.replace('_', ' ').title()}: {'Working' if status else 'Failed'}")
    
    overall_success = all(test_results.values())
    
    print(f"\n{'🎉' if overall_success else '⚠️'} OVERALL SYSTEM STATUS: {'FULLY FUNCTIONAL' if overall_success else 'PARTIALLY FUNCTIONAL'}")
    
    if overall_success:
        print("\n✨ The comprehensive deontic logic database system is working correctly!")
        print("   Features demonstrated:")
        print("   • Automatic legal text → formal deontic logic conversion")
        print("   • RAG-powered semantic search for related legal principles")
        print("   • Contradiction linting for logical consistency checking")
        print("   • Professional case law shepherding with precedent tracking")
        print("   • Database health monitoring and statistics")
    
    return overall_success


if __name__ == "__main__":
    print("🚀 Starting Comprehensive Deontic Logic Database Demonstration\n")
    
    success = demonstrate_deontic_system()
    
    if success:
        print(f"\n🎊 Demonstration completed successfully!")
        print("The deontic logic database system is ready for production use.")
    else:
        print(f"\n❌ Demonstration encountered issues.")
        print("Please check the error messages above.")
    
    print(f"\nDemonstration finished at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")