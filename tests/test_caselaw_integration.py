"""
Tests for Caselaw Access Project GraphRAG Integration

This module tests the complete integration of the Caselaw Access Project
dataset with the GraphRAG pipeline and dashboard functionality.
"""

import pytest
import sys
import os
from pathlib import Path

# Add the project directory to the path
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))


class TestCaselawDatasetLoader:
    """Test the Caselaw dataset loader"""
    
    def test_import_dataset_loader(self):
        """Test that we can import the dataset loader"""
        from ipfs_datasets_py.caselaw_dataset import CaselawDatasetLoader
        loader = CaselawDatasetLoader()
        assert loader is not None
        assert loader.dataset_name == "justicedao/Caselaw_Access_Project_embeddings"
    
    def test_load_mock_dataset(self):
        """Test loading mock dataset"""
        from ipfs_datasets_py.caselaw_dataset import CaselawDatasetLoader
        
        loader = CaselawDatasetLoader()
        result = loader.load_dataset(split="train", max_samples=5)
        
        assert result['status'] == 'success'
        assert result['source'] == 'mock'  # Should use mock data due to network issues
        assert result['count'] == 5
        assert len(result['dataset']) == 5
        
        # Check structure of first case
        case = result['dataset'][0]
        required_fields = ['id', 'title', 'court', 'year', 'text', 'topic']
        for field in required_fields:
            assert field in case
    
    def test_dataset_info(self):
        """Test dataset information retrieval"""
        from ipfs_datasets_py.caselaw_dataset import CaselawDatasetLoader
        
        loader = CaselawDatasetLoader()
        info = loader.get_dataset_info()
        
        assert 'name' in info
        assert 'description' in info
        assert 'fields' in info
        assert 'recommended_queries' in info
        
        # Check that we have the expected fields
        assert 'id' in info['fields']
        assert 'title' in info['fields']
        assert 'embedding' in info['fields']
    
    def test_convenience_function(self):
        """Test the convenience function for loading datasets"""
        from ipfs_datasets_py.caselaw_dataset import load_caselaw_dataset
        
        result = load_caselaw_dataset(max_samples=3)
        assert result['status'] == 'success'
        assert result['count'] == 3


class TestCaselawGraphRAGProcessor:
    """Test the GraphRAG processor for legal documents"""
    
    def test_import_processor(self):
        """Test importing the GraphRAG processor"""
        from ipfs_datasets_py.caselaw_graphrag import CaselawGraphRAGProcessor
        processor = CaselawGraphRAGProcessor()
        assert processor is not None
    
    def test_legal_entity_extraction(self):
        """Test legal entity extraction"""
        from ipfs_datasets_py.caselaw_graphrag import LegalEntityExtractor
        
        extractor = LegalEntityExtractor()
        
        # Test with sample legal text
        text = """
        In Brown v. Board of Education, 347 U.S. 483 (1954), the Supreme Court 
        held that racial segregation violated the Equal Protection Clause of the 
        Fourteenth Amendment. Justice Warren delivered the opinion of the Court.
        """
        
        entities = extractor.extract_entities(text)
        
        assert 'case_citation' in entities
        assert 'case_names' in entities
        assert 'court_names' in entities
        assert 'judges' in entities
        
        # Should find the citation
        assert len(entities['case_citation']) > 0
        assert '347 U.S. 483' in entities['case_citation'][0]
    
    def test_process_dataset(self):
        """Test processing a dataset through the GraphRAG pipeline"""
        from ipfs_datasets_py.caselaw_graphrag import CaselawGraphRAGProcessor
        
        processor = CaselawGraphRAGProcessor()
        result = processor.process_dataset(max_samples=5)
        
        assert result['status'] == 'success'
        assert 'knowledge_graph' in result
        assert 'processing_summary' in result
        
        # Check knowledge graph structure
        kg = result['knowledge_graph']
        assert 'nodes' in kg
        assert 'edges' in kg
        assert 'statistics' in kg
        
        # Should have case nodes
        case_nodes = [n for n in kg['nodes'] if n.get('type') == 'case']
        assert len(case_nodes) == 5
        
        # Should have some edges
        assert len(kg['edges']) > 0
    
    def test_query_knowledge_graph(self):
        """Test querying the knowledge graph"""
        from ipfs_datasets_py.caselaw_graphrag import CaselawGraphRAGProcessor
        
        processor = CaselawGraphRAGProcessor()
        # First process some data
        processor.process_dataset(max_samples=5)
        
        # Test querying
        results = processor.query_knowledge_graph("civil rights", max_results=3)
        assert isinstance(results, list)
        
        # Should find some civil rights cases
        assert len(results) > 0
        
        # Check result structure
        if results:
            result = results[0]
            assert 'case' in result
            assert 'relevance_score' in result
            assert 'match_type' in result
    
    def test_factory_function(self):
        """Test the factory function"""
        from ipfs_datasets_py.caselaw_graphrag import create_caselaw_graphrag_processor
        
        processor = create_caselaw_graphrag_processor()
        assert processor is not None


class TestCaselawDashboard:
    """Test the dashboard functionality"""
    
    def test_import_dashboard(self):
        """Test importing the dashboard"""
        from ipfs_datasets_py.caselaw_dashboard import CaselawDashboard
        dashboard = CaselawDashboard()
        assert dashboard is not None
    
    def test_initialize_data(self):
        """Test dashboard data initialization"""
        from ipfs_datasets_py.caselaw_dashboard import CaselawDashboard
        
        dashboard = CaselawDashboard()
        result = dashboard.initialize_data(max_samples=5)
        
        assert result['status'] == 'success'
        assert 'data' in result
        assert dashboard.processed_data is not None
    
    def test_factory_function(self):
        """Test the dashboard factory function"""
        from ipfs_datasets_py.caselaw_dashboard import create_caselaw_dashboard
        
        dashboard = create_caselaw_dashboard()
        assert dashboard is not None


class TestMainModuleIntegration:
    """Test integration with the main module"""
    
    def test_import_from_main_module(self):
        """Test importing caselaw functionality from main module"""
        import ipfs_datasets_py
        
        # Check that the integration is available
        assert hasattr(ipfs_datasets_py, 'HAVE_CASELAW_INTEGRATION')
        assert ipfs_datasets_py.HAVE_CASELAW_INTEGRATION is True
        
        # Test imports
        assert hasattr(ipfs_datasets_py, 'CaselawDatasetLoader')
        assert hasattr(ipfs_datasets_py, 'load_caselaw_dataset')
        assert hasattr(ipfs_datasets_py, 'CaselawGraphRAGProcessor')
        assert hasattr(ipfs_datasets_py, 'create_caselaw_graphrag_processor')
        assert hasattr(ipfs_datasets_py, 'CaselawDashboard')
        assert hasattr(ipfs_datasets_py, 'create_caselaw_dashboard')
    
    def test_create_components_from_main(self):
        """Test creating components from main module"""
        import ipfs_datasets_py
        
        # Test creating components
        loader = ipfs_datasets_py.CaselawDatasetLoader()
        assert loader is not None
        
        processor = ipfs_datasets_py.create_caselaw_graphrag_processor()
        assert processor is not None
        
        dashboard = ipfs_datasets_py.create_caselaw_dashboard()
        assert dashboard is not None
    
    def test_end_to_end_workflow(self):
        """Test the complete end-to-end workflow"""
        import ipfs_datasets_py
        
        # Step 1: Load dataset
        dataset_result = ipfs_datasets_py.load_caselaw_dataset(max_samples=3)
        assert dataset_result['status'] == 'success'
        assert dataset_result['count'] == 3
        
        # Step 2: Process with GraphRAG
        processor = ipfs_datasets_py.create_caselaw_graphrag_processor()
        graphrag_result = processor.process_dataset(max_samples=3)
        assert graphrag_result['status'] == 'success'
        
        # Step 3: Create dashboard
        dashboard = ipfs_datasets_py.create_caselaw_dashboard()
        dashboard_result = dashboard.initialize_data(max_samples=3)
        assert dashboard_result['status'] == 'success'
        
        # Step 4: Test search functionality
        search_results = processor.query_knowledge_graph("Supreme Court")
        assert isinstance(search_results, list)


class TestRegressionAndCompatibility:
    """Test that our changes don't break existing functionality"""
    
    def test_existing_imports_still_work(self):
        """Test that existing imports are not broken"""
        import ipfs_datasets_py
        
        # Test that basic functionality still works
        if hasattr(ipfs_datasets_py, 'load_dataset') and ipfs_datasets_py.load_dataset:
            # If HuggingFace datasets is available, this should work
            assert callable(ipfs_datasets_py.load_dataset)
    
    def test_existing_modules_accessible(self):
        """Test that existing modules are still accessible"""
        import ipfs_datasets_py
        
        # Test that existing components are available
        assert hasattr(ipfs_datasets_py, 'llm')
        assert hasattr(ipfs_datasets_py, 'rag')


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])