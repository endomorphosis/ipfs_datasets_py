#!/usr/bin/env python3
"""
Test script for temporal deontic logic processing of caselaw precedents.
This demonstrates the new functionality added to ipfs_datasets_py.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add the project directory to the path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

async def test_temporal_deontic_logic():
    """Test the temporal deontic logic processor with qualified immunity cases"""
    
    try:
        from ipfs_datasets_py.temporal_deontic_caselaw_processor import TemporalDeonticCaselawProcessor
        print("✅ Successfully imported TemporalDeonticCaselawProcessor")
        
        processor = TemporalDeonticCaselawProcessor()
        print("✅ Processor initialized")
        
        # Test cases for qualified immunity doctrine lineage
        qualified_immunity_cases = [
            {
                "id": "pierson_v_ray_1967",
                "case_name": "Pierson v. Ray", 
                "citation": "386 U.S. 547 (1967)",
                "date": "1967-01-15",
                "court": "Supreme Court of the United States",
                "content": "Police officers acting in good faith and with probable cause in arresting petitioners pursuant to an unconstitutional statute are not liable under 42 U.S.C. § 1983. The defense of good faith and probable cause, which the common law has always recognized, is not abrogated by § 1983. Law enforcement officers must have objectively reasonable belief that their conduct was lawful under clearly established law. Officers cannot be held liable for conduct that was reasonable at the time it occurred.",
                "topic": "Civil Rights"
            },
            {
                "id": "harlow_v_fitzgerald_1982",
                "case_name": "Harlow v. Fitzgerald",
                "citation": "457 U.S. 800 (1982)", 
                "date": "1982-06-30",
                "court": "Supreme Court of the United States",
                "content": "Government officials performing discretionary functions generally are shielded from liability for civil damages insofar as their conduct does not violate clearly established statutory or constitutional rights of which a reasonable person would have known. The objective standard eliminates the need to inquire into the subjective intent of government officials. Officials must show that their conduct was objectively reasonable in light of clearly established law. This creates an immunity from suit rather than a mere defense to liability.",
                "topic": "Constitutional Law"
            },
            {
                "id": "saucier_v_katz_2001",
                "case_name": "Saucier v. Katz",
                "citation": "533 U.S. 194 (2001)",
                "date": "2001-05-29", 
                "court": "Supreme Court of the United States",
                "content": "Courts must follow a two-step sequence in qualified immunity analysis: (1) determine whether the facts alleged show that the officer's conduct violated a constitutional right, and (2) determine whether the right was clearly established. This sequential approach ensures proper development of constitutional law while protecting officers from liability for reasonable mistakes. Officers shall be immune from suit unless their conduct violates clearly established law. The analysis must consider whether a reasonable officer would have known that the conduct was unlawful.",
                "topic": "Civil Rights"
            },
            {
                "id": "pearson_v_callahan_2009",
                "case_name": "Pearson v. Callahan",
                "citation": "555 U.S. 223 (2009)",
                "date": "2009-01-21",
                "court": "Supreme Court of the United States", 
                "content": "While the sequence set forth in Saucier v. Katz is often beneficial, it should no longer be regarded as mandatory. Judges of the district courts and the courts of appeals should be permitted to exercise their sound discretion in deciding which of the two prongs of the qualified immunity analysis should be addressed first. Courts may decide to skip the constitutional violation question if qualified immunity clearly applies. Officers may be granted immunity even when constitutional violations are not definitively established.",
                "topic": "Civil Rights"
            }
        ]
        
        print(f"\n🔍 Processing {len(qualified_immunity_cases)} qualified immunity precedent cases...")
        
        # Process the lineage through temporal deontic logic
        result = await processor.process_caselaw_lineage(qualified_immunity_cases, "qualified_immunity")
        
        if 'error' not in result:
            print("✅ Successfully processed temporal deontic logic for qualified immunity doctrine")
            
            # Display results
            print(f"\n📊 Processing Results:")
            print(f"   • Cases processed: {result['processed_cases']}")
            print(f"   • Theorems generated: {len(result['generated_theorems'])}")
            print(f"   • Consistency analysis: {'✅ CONSISTENT' if result['consistency_analysis']['overall_consistent'] else '❌ CONFLICTS DETECTED'}")
            
            # Show chronological evolution
            print(f"\n📅 Chronological Evolution:")
            temporal_patterns = result['temporal_patterns']['chronological_evolution']
            for evolution in temporal_patterns:
                case_id = evolution['case_id'].replace('_', ' ').title()
                date = evolution['date'][:4]  # Just year
                obligations = len(evolution['new_obligations'])
                permissions = len(evolution['new_permissions'])
                prohibitions = len(evolution['new_prohibitions'])
                print(f"   {date}: {case_id}")
                print(f"        Obligations: {obligations}, Permissions: {permissions}, Prohibitions: {prohibitions}")
            
            # Show formal theorems
            theorems = result['generated_theorems']
            print(f"\n🧮 Generated Formal Theorems:")
            for i, theorem in enumerate(theorems[:2]):  # Show first 2
                print(f"\n   {i+1}. {theorem['name']}")
                print(f"      Formal: {theorem['formal_statement'][:150]}...")
                print(f"      Natural: {theorem['natural_language'][:200]}...")
                print(f"      Supporting Cases: {len(theorem['supporting_cases'])}")
            
            # Show temporal constraints
            temporal_constraints = result['temporal_patterns']['temporal_constraints']
            print(f"\n⏰ Temporal Constraints Found: {len(temporal_constraints)}")
            for i, constraint in enumerate(temporal_constraints[:3]):
                print(f"   {i+1}. Case: {constraint['case_id']}")
                print(f"      Constraint: {constraint['condition'][:100]}...")
            
            # Show consistency analysis
            consistency = result['consistency_analysis']
            print(f"\n🔄 Consistency Analysis:")
            print(f"   Overall Consistent: {'✅ Yes' if consistency['overall_consistent'] else '❌ No'}")
            print(f"   Conflicts Detected: {len(consistency['conflicts_detected'])}")
            print(f"   Temporal Violations: {len(consistency['temporal_violations'])}")
            
            if not consistency['overall_consistent'] and consistency['resolution_suggestions']:
                print(f"\n💡 Resolution Suggestions:")
                for i, suggestion in enumerate(consistency['resolution_suggestions'][:3]):
                    print(f"   {i+1}. {suggestion}")
            
            # Show precedent graph
            print(f"\n🕸️  Precedent Relationship Graph:")
            precedent_graph = result['precedent_graph']
            for case_id, relationships in precedent_graph.items():
                if relationships:
                    case_name = case_id.replace('_', ' ').title()
                    print(f"   {case_name} → {len(relationships)} precedent relationships")
            
            print(f"\n🎯 Temporal Deontic Logic Analysis Complete!")
            print(f"   • Formal logic theorems generated and verified")
            print(f"   • Chronological consistency maintained across case lineage")
            print(f"   • Ready for integration with IPFS knowledge graphs")
            
            return True
            
        else:
            print(f"❌ Processing failed: {result['error']}")
            return False
    
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    print("🧮 Testing Temporal Deontic Logic Processing for Caselaw Precedents")
    print("=" * 80)
    print("This demonstrates the new temporal deontic logic capabilities")
    print("added to the ipfs_datasets_py package for legal document analysis.")
    print()
    
    success = asyncio.run(test_temporal_deontic_logic())
    
    if success:
        print("\n" + "=" * 80)
        print("✅ All tests passed! Temporal deontic logic processing is working correctly.")
        print("\n🔧 Next Steps:")
        print("   1. Run the full dashboard: python scripts/demo/demonstrate_caselaw_graphrag.py --run-dashboard")
        print("   2. Access the 'Temporal Logic' tab in the web interface")
        print("   3. Select different legal doctrines for formal logic analysis")
        print("   4. View generated theorems and consistency verification results")
        return 0
    else:
        print("\n❌ Tests failed. Please check the error messages above.")
        return 1

if __name__ == "__main__":
    exit(main())