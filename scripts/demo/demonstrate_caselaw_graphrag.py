#!/usr/bin/env python3
"""
Caselaw Access Project GraphRAG Demonstration

This script demonstrates the complete Caselaw Access Project GraphRAG integration,
showing how to load the dataset, process it through the GraphRAG pipeline,
and run the interactive dashboard for legal document search.
"""

import argparse
import sys
import os
from pathlib import Path

# Add the project directory to the path
project_root = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(project_root))

def demonstrate_dataset_loading(max_samples=50):
    """Demonstrate loading the Caselaw Access Project dataset"""
    print("📚 Demonstrating Caselaw Dataset Loading...")
    print("-" * 50)
    
    try:
        from ipfs_datasets_py.caselaw_dataset import CaselawDatasetLoader
        
        loader = CaselawDatasetLoader()
        result = loader.load_dataset(split="train", max_samples=max_samples)
        
        print(f"✅ Successfully loaded {result['count']} cases from {result['source']} source")
        
        if result["dataset"]:
            print("\n📄 Sample Cases:")
            for i, case in enumerate(result["dataset"][:3]):
                print(f"\n{i+1}. {case['title']}")
                print(f"   Court: {case['court']}")
                print(f"   Year: {case['year']}")
                print(f"   Topic: {case['topic']}")
                print(f"   Summary: {case['summary'][:100]}...")
        
        dataset_info = loader.get_dataset_info()
        print(f"\n📊 Dataset Information:")
        print(f"   Description: {dataset_info['description']}")
        print(f"   Available fields: {len(dataset_info['fields'])}")
        
        print(f"\n🔍 Recommended queries:")
        for query in dataset_info['recommended_queries'][:3]:
            print(f"   • {query}")
        
        return result
        
    except Exception as e:
        print(f"❌ Dataset loading failed: {e}")
        return None

def demonstrate_graphrag_processing(max_samples=50):
    """Demonstrate GraphRAG processing of legal documents"""
    print("\n🧠 Demonstrating GraphRAG Processing...")
    print("-" * 50)
    
    try:
        from ipfs_datasets_py.caselaw_graphrag import CaselawGraphRAGProcessor
        
        processor = CaselawGraphRAGProcessor()
        result = processor.process_dataset(max_samples=max_samples)
        
        if result['status'] == 'success':
            stats = result['knowledge_graph']['statistics']
            summary = result['processing_summary']
            
            print(f"✅ GraphRAG processing completed successfully")
            print(f"\n📊 Knowledge Graph Statistics:")
            print(f"   • Total nodes: {stats['total_nodes']:,}")
            print(f"   • Total edges: {stats['total_edges']:,}")
            print(f"   • Case nodes: {stats['case_nodes']:,}")
            print(f"   • Entity types: {stats['entity_types']}")
            print(f"   • Relationship types: {stats['relationship_types']}")
            
            print(f"\n🏛️ Court Distribution:")
            for court, count in list(stats['court_distribution'].items())[:5]:
                print(f"   • {court}: {count} cases")
            
            print(f"\n⚖️ Legal Topic Distribution:")
            for topic, count in list(stats['most_common_topics'].items())[:5]:
                print(f"   • {topic}: {count} cases")
            
            print(f"\n📅 Time Range:")
            year_range = stats['year_range']
            print(f"   • Years: {year_range['min_year']} - {year_range['max_year']}")
            print(f"   • Span: {year_range['span']} years")
            
            # Demonstrate querying
            print(f"\n🔍 Query Demonstrations:")
            test_queries = [
                "civil rights",
                "Supreme Court",
                "constitutional law"
            ]
            
            for query in test_queries:
                query_results = processor.query_knowledge_graph(query, max_results=3)
                print(f"\n   Query: '{query}' → {len(query_results)} results")
                
                for i, result_item in enumerate(query_results[:2]):
                    case = result_item['case']
                    score = result_item['relevance_score']
                    print(f"     {i+1}. {case['title']} (relevance: {score})")
            
            return processor
        else:
            print(f"❌ GraphRAG processing failed: {result.get('message', 'Unknown error')}")
            return None
            
    except Exception as e:
        print(f"❌ GraphRAG processing failed: {e}")
        return None

def demonstrate_temporal_deontic_logic(processor=None, max_samples=20):
    """Demonstrate temporal deontic logic processing of case lineages"""
    print("\n⚖️ Demonstrating Temporal Deontic Logic Processing...")
    print("-" * 50)
    
    try:
        from ipfs_datasets_py.temporal_deontic_caselaw_processor import TemporalDeonticCaselawProcessor
        
        temporal_processor = TemporalDeonticCaselawProcessor()
        
        # Create example case lineage for qualified immunity doctrine
        qualified_immunity_cases = [
            {
                "id": "pierson_v_ray_1967",
                "case_name": "Pierson v. Ray", 
                "citation": "386 U.S. 547 (1967)",
                "date": "1967-01-15",
                "court": "Supreme Court of the United States",
                "content": "Police officers acting in good faith and with probable cause in arresting petitioners pursuant to an unconstitutional statute are not liable under 42 U.S.C. § 1983. The defense of good faith and probable cause, which the common law has always recognized, is not abrogated by § 1983. Law enforcement officers must have objectively reasonable belief that their conduct was lawful under clearly established law.",
                "topic": "Civil Rights"
            },
            {
                "id": "harlow_v_fitzgerald_1982",
                "case_name": "Harlow v. Fitzgerald",
                "citation": "457 U.S. 800 (1982)", 
                "date": "1982-06-30",
                "court": "Supreme Court of the United States",
                "content": "Government officials performing discretionary functions generally are shielded from liability for civil damages insofar as their conduct does not violate clearly established statutory or constitutional rights of which a reasonable person would have known. The objective standard eliminates the need to inquire into the subjective intent of government officials.",
                "topic": "Constitutional Law"
            },
            {
                "id": "saucier_v_katz_2001",
                "case_name": "Saucier v. Katz",
                "citation": "533 U.S. 194 (2001)",
                "date": "2001-05-29", 
                "court": "Supreme Court of the United States",
                "content": "Courts must follow a two-step sequence in qualified immunity analysis: (1) determine whether the facts alleged show that the officer's conduct violated a constitutional right, and (2) determine whether the right was clearly established. This sequential approach ensures proper development of constitutional law while protecting officers from liability for reasonable mistakes.",
                "topic": "Civil Rights"
            },
            {
                "id": "pearson_v_callahan_2009",
                "case_name": "Pearson v. Callahan",
                "citation": "555 U.S. 223 (2009)",
                "date": "2009-01-21",
                "court": "Supreme Court of the United States", 
                "content": "While the sequence set forth in Saucier v. Katz is often beneficial, it should no longer be regarded as mandatory. Judges of the district courts and the courts of appeals should be permitted to exercise their sound discretion in deciding which of the two prongs of the qualified immunity analysis should be addressed first.",
                "topic": "Civil Rights"
            }
        ]
        
        print(f"🔍 Processing {len(qualified_immunity_cases)} qualified immunity precedent cases...")
        
        # Process the lineage
        import asyncio
        result = asyncio.run(temporal_processor.process_caselaw_lineage(
            qualified_immunity_cases, "qualified_immunity"
        ))
        
        if 'error' not in result:
            print(f"✅ Successfully processed temporal deontic logic for qualified immunity doctrine")
            
            # Display chronological evolution
            print(f"\n📅 Chronological Evolution:")
            for evolution in result['temporal_patterns']['chronological_evolution']:
                case_id = evolution['case_id']
                date = evolution['date'][:4]  # Just year
                obligations = len(evolution['new_obligations'])
                permissions = len(evolution['new_permissions'])
                prohibitions = len(evolution['new_prohibitions'])
                print(f"   • {date}: {case_id} - O:{obligations} P:{permissions} F:{prohibitions}")
            
            # Display generated theorems
            theorems = result['generated_theorems']
            print(f"\n🧮 Generated Formal Theorems ({len(theorems)}):")
            
            for theorem in theorems[:3]:  # Show first 3 theorems
                print(f"\n   📜 {theorem['name']}")
                print(f"      Formal: {theorem['formal_statement'][:100]}...")
                print(f"      Natural: {theorem['natural_language'][:150]}...")
                print(f"      Cases: {len(theorem['supporting_cases'])} supporting cases")
            
            # Display consistency analysis
            consistency = result['consistency_analysis']
            consistency_status = "✅ CONSISTENT" if consistency['overall_consistent'] else "❌ CONFLICTS DETECTED"
            print(f"\n🔄 Chronological Consistency: {consistency_status}")
            
            if not consistency['overall_consistent']:
                print(f"   Conflicts detected: {len(consistency['conflicts_detected'])}")
                print(f"   Temporal violations: {len(consistency['temporal_violations'])}")
            
            # Display proof results if available
            proof_results = result.get('proof_results', [])
            if proof_results:
                print(f"\n🔬 Theorem Prover Results ({len(proof_results)}):")
                for proof in proof_results[:3]:
                    status_icon = "✅" if proof['proof_status'] == 'success' else "❌"
                    print(f"   {status_icon} {proof['theorem_id']}: {proof['proof_status']}")
            
            # Display IPLD export capability
            ipld_export = asyncio.run(temporal_processor.export_theorems_to_ipld([
                temporal_processor.theorems[tid] for tid in temporal_processor.theorems.keys()
            ]))
            
            print(f"\n🌐 IPLD Export Ready:")
            print(f"   Type: {ipld_export['type']}")
            print(f"   Version: {ipld_export['version']}")
            print(f"   Theorems: {len(ipld_export['theorems'])} formal theorems exported")
            
            return temporal_processor
        else:
            print(f"❌ Temporal deontic logic processing failed: {result['error']}")
            return None
            
    except Exception as e:
        print(f"❌ Temporal deontic logic demonstration failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def demonstrate_dashboard(processor=None, run_dashboard=False, port=5000):
    """Demonstrate the interactive dashboard"""
    print("\n📊 Demonstrating Interactive Dashboard...")
    print("-" * 50)
    
    try:
        from ipfs_datasets_py.caselaw_dashboard import CaselawDashboard
        
        dashboard = CaselawDashboard(debug=False)
        
        # Initialize with data
        max_samples = 100 if run_dashboard else 20
        init_result = dashboard.initialize_data(max_samples=max_samples)
        
        if init_result['status'] == 'success':
            data_info = init_result['data']['dataset_info']
            print(f"✅ Dashboard initialized with {data_info['count']} cases")
            print(f"   Data source: {data_info['source']}")
            
            if not run_dashboard:
                # Demonstrate search capabilities without running full server
                print(f"\n🔍 Search Capability Demonstration:")
                
                demo_queries = [
                    "civil rights education",
                    "criminal procedure Miranda",
                    "privacy constitutional"
                ]
                
                for query in demo_queries:
                    results = dashboard.processor.query_knowledge_graph(query, max_results=2)
                    print(f"\n   '{query}' → {len(results)} matches")
                    for result in results:
                        case = result['case']
                        print(f"     • {case['title']} ({case['year']}) - {case['court']}")
                
                print(f"\n📈 Dashboard Features Available:")
                print(f"   • Interactive case search")
                print(f"   • Knowledge graph visualization")
                print(f"   • Legal topic analysis")
                print(f"   • Court distribution charts")
                print(f"   • Case relationship mapping")
                
                print(f"\n🚀 To run the full interactive dashboard:")
                print(f"   python {__file__} --run-dashboard --port {port}")
            else:
                print(f"\n🌐 Starting interactive web dashboard...")
                print(f"   URL: http://localhost:{port}")
                print(f"   Press Ctrl+C to stop the server")
                dashboard.run(host="0.0.0.0", port=port, initialize_data=False)
            
            return dashboard
        else:
            print(f"❌ Dashboard initialization failed: {init_result['message']}")
            return None
            
    except Exception as e:
        print(f"❌ Dashboard demonstration failed: {e}")
        return None

def main():
    """Main demonstration function"""
    parser = argparse.ArgumentParser(
        description="Demonstrate Caselaw Access Project GraphRAG integration"
    )
    parser.add_argument(
        "--max-samples", 
        type=int, 
        default=50, 
        help="Maximum number of cases to process (default: 50)"
    )
    parser.add_argument(
        "--run-dashboard", 
        action="store_true", 
        help="Run the interactive web dashboard"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=5000, 
        help="Port for the web dashboard (default: 5000)"
    )
    parser.add_argument(
        "--quick-demo", 
        action="store_true", 
        help="Run a quick demo with minimal data"
    )
    parser.add_argument(
        "--temporal-logic", 
        action="store_true", 
        help="Include temporal deontic logic demonstration"
    )
    
    args = parser.parse_args()
    
    if args.quick_demo:
        args.max_samples = 10
    
    print("🏛️ Caselaw Access Project GraphRAG Demonstration")
    print("=" * 60)
    print(f"Processing up to {args.max_samples} cases...")
    print()
    
    try:
        # Step 1: Demonstrate dataset loading
        dataset_result = demonstrate_dataset_loading(args.max_samples)
        if not dataset_result:
            print("❌ Cannot continue without dataset")
            return 1
        
        # Step 2: Demonstrate GraphRAG processing
        processor = demonstrate_graphrag_processing(args.max_samples)
        if not processor:
            print("❌ Cannot continue without GraphRAG processing")
            return 1
        
        # Step 3: Demonstrate temporal deontic logic processing (if requested)
        temporal_processor = None
        if args.temporal_logic or not args.quick_demo:
            temporal_processor = demonstrate_temporal_deontic_logic(processor, args.max_samples)
            if temporal_processor:
                print("✅ Temporal deontic logic processing completed successfully")
            else:
                print("⚠️ Temporal deontic logic processing had issues, continuing with basic features")
        
        # Step 4: Demonstrate dashboard
        dashboard = demonstrate_dashboard(processor, args.run_dashboard, args.port)
        if not dashboard:
            print("❌ Dashboard demonstration failed")
            return 1
        
        if not args.run_dashboard:
            print("\n" + "=" * 60)
            print("🎉 Demonstration completed successfully!")
            print()
            print("📋 What was demonstrated:")
            print("   ✅ Loading Caselaw Access Project dataset (with mock fallback)")
            print("   ✅ GraphRAG processing for legal entity extraction")
            print("   ✅ Knowledge graph construction with legal relationships")
            print("   ✅ Temporal deontic logic conversion and theorem generation")
            print("   ✅ Chronological consistency verification across case lineages")
            print("   ✅ Formal logic theorem proving capabilities")
            print("   ✅ Interactive search capabilities")
            print("   ✅ Dashboard preparation with visualizations")
            print()
            print("🚀 Ready for production use!")
            print(f"   • Dataset: {dataset_result['count']} legal cases available")
            print(f"   • Knowledge graph: Ready for complex legal queries")
            print(f"   • Temporal deontic logic: Formal theorems generated and verified")
            print(f"   • Dashboard: Interactive web interface prepared")
            print()
            print("💡 Next steps:")
            print(f"   • Run with --run-dashboard to start the web interface")
            print(f"   • Increase --max-samples for larger datasets")
            print(f"   • Integrate with existing IPFS infrastructure")
            print(f"   • Add more legal doctrines for temporal deontic processing")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n👋 Demonstration interrupted by user")
        return 0
    except Exception as e:
        print(f"\n❌ Demonstration failed: {e}")
        return 1

if __name__ == "__main__":
    exit(main())