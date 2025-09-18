#!/usr/bin/env python3
"""
Test script for Caselaw Access Project GraphRAG integration

This script tests the complete pipeline from dataset loading to dashboard functionality.
"""

import sys
import os
from pathlib import Path

# Add the project directory to the path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

def test_dataset_loader():
    """Test the dataset loader functionality"""
    print("🔬 Testing Caselaw Dataset Loader...")
    
    try:
        from ipfs_datasets_py.caselaw_dataset import CaselawDatasetLoader
        
        loader = CaselawDatasetLoader()
        result = loader.load_dataset(split="train", max_samples=5)
        
        print(f"✅ Dataset loaded: {result['count']} cases from {result['source']}")
        
        if result["dataset"]:
            sample = result["dataset"][0]
            print(f"📄 Sample case: {sample['title']} ({sample['year']})")
            print(f"🏛️ Court: {sample['court']}")
            print(f"📋 Topic: {sample['topic']}")
            print(f"✨ Summary: {sample['summary'][:100]}...")
        
        dataset_info = loader.get_dataset_info()
        print(f"📊 Dataset info: {dataset_info['description']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Dataset loader test failed: {e}")
        return False

def test_graphrag_processor():
    """Test the GraphRAG processor"""
    print("\n🧠 Testing GraphRAG Processor...")
    
    try:
        from ipfs_datasets_py.caselaw_graphrag import CaselawGraphRAGProcessor
        
        processor = CaselawGraphRAGProcessor()
        result = processor.process_dataset(max_samples=10)
        
        if result['status'] == 'success':
            print(f"✅ GraphRAG processing successful")
            print(f"📊 Knowledge graph: {result['knowledge_graph']['statistics']['total_nodes']} nodes, {result['knowledge_graph']['statistics']['total_edges']} edges")
            print(f"🏛️ Courts: {list(result['processing_summary']['court_types'])}")
            print(f"⚖️ Topics: {result['processing_summary']['legal_topics']}")
            
            # Test querying
            query_results = processor.query_knowledge_graph("civil rights")
            print(f"🔍 Query 'civil rights' found {len(query_results)} relevant cases")
            
            if query_results:
                top_result = query_results[0]
                print(f"📄 Top result: {top_result['case']['title']} (score: {top_result['relevance_score']})")
            
            return True
        else:
            print(f"❌ GraphRAG processing failed: {result.get('message', 'Unknown error')}")
            return False
            
    except Exception as e:
        print(f"❌ GraphRAG processor test failed: {e}")
        return False

def test_dashboard_creation():
    """Test dashboard creation (without running the server)"""
    print("\n📊 Testing Dashboard Creation...")
    
    try:
        from ipfs_datasets_py.caselaw_dashboard import CaselawDashboard
        
        dashboard = CaselawDashboard(debug=False)
        
        # Test data initialization
        init_result = dashboard.initialize_data(max_samples=5)
        
        if init_result['status'] == 'success':
            print(f"✅ Dashboard initialized with {init_result['data']['dataset_info']['count']} cases")
            
            # Test search functionality
            if dashboard.processed_data:
                results = dashboard.processor.query_knowledge_graph("Supreme Court")
                print(f"🔍 Dashboard search test: found {len(results)} Supreme Court cases")
            
            return True
        else:
            print(f"❌ Dashboard initialization failed: {init_result['message']}")
            return False
            
    except Exception as e:
        print(f"❌ Dashboard creation test failed: {e}")
        return False

def test_integration_end_to_end():
    """Test the complete integration end-to-end"""
    print("\n🚀 Testing End-to-End Integration...")
    
    try:
        # Import all components
        from ipfs_datasets_py.caselaw_dataset import load_caselaw_dataset
        from ipfs_datasets_py.caselaw_graphrag import create_caselaw_graphrag_processor
        from ipfs_datasets_py.caselaw_dashboard import create_caselaw_dashboard
        
        # Load dataset
        dataset_result = load_caselaw_dataset(max_samples=10)
        print(f"✅ Dataset loaded: {dataset_result['count']} cases")
        
        # Process with GraphRAG
        processor = create_caselaw_graphrag_processor()
        graphrag_result = processor.process_dataset(max_samples=10)
        print(f"✅ GraphRAG processing: {graphrag_result['processing_summary']['entities_extracted']} entities, {graphrag_result['processing_summary']['relationships_found']} relationships")
        
        # Create dashboard
        dashboard = create_caselaw_dashboard()
        dashboard_result = dashboard.initialize_data(max_samples=10)
        print(f"✅ Dashboard ready: {dashboard_result['data']['dataset_info']['count']} cases loaded")
        
        # Test queries
        test_queries = [
            "civil rights",
            "Supreme Court", 
            "constitutional law",
            "criminal procedure"
        ]
        
        for query in test_queries:
            results = processor.query_knowledge_graph(query, max_results=3)
            print(f"🔍 Query '{query}': {len(results)} results")
        
        print("✅ End-to-end integration test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ End-to-end integration test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🏛️ Caselaw Access Project GraphRAG Integration Test Suite")
    print("=" * 60)
    
    tests = [
        ("Dataset Loader", test_dataset_loader),
        ("GraphRAG Processor", test_graphrag_processor),
        ("Dashboard Creation", test_dashboard_creation),
        ("End-to-End Integration", test_integration_end_to_end)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Results Summary:")
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} - {test_name}")
        if result:
            passed += 1
    
    print(f"\n🎯 Overall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("🎉 All tests passed! The Caselaw GraphRAG integration is ready.")
        print("\n🚀 To start the dashboard:")
        print("python -c \"from ipfs_datasets_py.caselaw_dashboard import create_caselaw_dashboard; create_caselaw_dashboard().run()\"")
    else:
        print("⚠️ Some tests failed. Please check the errors above.")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())