"""
Test suite for enhanced cross-document lineage tracking and integration.

This module tests the enhanced cross-document lineage functionality, including
the integration between data provenance and cross-document lineage tracking.
"""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import networkx as nx
import json

# Import the modules to test
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
from ipfs_datasets_py.cross_document_lineage_enhanced import (
    CrossDocumentLineageEnhancer,
    DetailedLineageIntegrator
)


class TestCrossDocumentLineageEnhancer(unittest.TestCase):
    """Tests for the CrossDocumentLineageEnhancer class."""
    
    def setUp(self):
        """Set up test environment."""
        # Mock IPLD provenance storage
        self.mock_storage = MagicMock()
        self.mock_storage.record_cids = {}
        
        # Create an enhancer instance with the mock storage
        self.enhancer = CrossDocumentLineageEnhancer(self.mock_storage)
        
    def test_link_cross_document_provenance(self):
        """Test creating enhanced cross-document links."""
        # Mock storage methods
        self.mock_storage.record_cids = {
            "record1": "cid1",
            "record2": "cid2"
        }
        
        # Configure mocks
        record1 = MagicMock()
        record1.metadata = {"document_id": "doc1"}
        record2 = MagicMock()
        record2.metadata = {"document_id": "doc2"}
        
        self.mock_storage.load_record.side_effect = lambda cid: record1 if cid == "cid1" else record2
        self.mock_storage.link_cross_document_provenance.return_value = "link_cid"
        
        # Create a link
        link_cid = self.enhancer.link_cross_document_provenance(
            source_record_id="record1",
            target_record_id="record2",
            link_type="derived_from",
            confidence=0.9,
            semantic_context={"category": "content", "description": "Test link"},
            boundary_type="dataset"
        )
        
        # Verify link was created
        self.assertEqual(link_cid, "link_cid")
        self.mock_storage.link_cross_document_provenance.assert_called_once()
        
        # Verify properties were passed correctly
        call_args = self.mock_storage.link_cross_document_provenance.call_args[1]
        self.assertEqual(call_args["source_record_id"], "record1")
        self.assertEqual(call_args["target_record_id"], "record2")
        self.assertEqual(call_args["link_type"], "derived_from")
        
        # Check that properties were enhanced
        properties = call_args["properties"]
        self.assertEqual(properties["confidence"], 0.9)
        self.assertEqual(properties["semantic_context"]["category"], "content")
        self.assertEqual(properties["boundary_type"], "dataset")
        self.assertEqual(properties["source_document_id"], "doc1")
        self.assertEqual(properties["target_document_id"], "doc2")
        self.assertIn("created_at", properties)
        
    def test_build_enhanced_cross_document_lineage_graph(self):
        """Test building enhanced lineage graph."""
        # Mock base graph building
        base_graph = nx.DiGraph()
        base_graph.add_node("record1", document_id="doc1", record_type="source")
        base_graph.add_node("record2", document_id="doc2", record_type="transformation")
        base_graph.add_edge("record1", "record2", relation="input_to", cross_document=True)
        
        self.mock_storage.build_cross_document_lineage_graph.return_value = base_graph
        
        # Mock enhancer methods with no-op implementations
        self.enhancer._enhance_lineage_graph = lambda g: g
        
        # Build the enhanced graph
        enhanced_graph = self.enhancer.build_enhanced_cross_document_lineage_graph(
            record_ids=["record1"],
            max_depth=2,
            include_semantic_analysis=True
        )
        
        # Verify the graph was built and base methods were called
        self.assertIsInstance(enhanced_graph, nx.DiGraph)
        self.mock_storage.build_cross_document_lineage_graph.assert_called_once()
        
    def test_visualize_enhanced_cross_document_lineage(self):
        """Test visualization of enhanced lineage."""
        # Create a simple test graph
        test_graph = nx.DiGraph()
        test_graph.add_node("record1", document_id="doc1", record_type="source")
        test_graph.add_node("record2", document_id="doc2", record_type="transformation")
        test_graph.add_edge("record1", "record2", relation="input_to", cross_document=True)
        
        # Mock storage and matplotlib to avoid rendering
        with patch('matplotlib.pyplot.savefig') as mock_savefig, \
             patch.object(self.enhancer, '_visualize_with_matplotlib') as mock_mpl_viz:
            
            # Configure the mock to return a dummy result
            mock_mpl_viz.return_value = "test_viz_result"
            
            # Call visualization with the test graph
            result = self.enhancer.visualize_enhanced_cross_document_lineage(
                lineage_graph=test_graph,
                highlight_cross_document=True,
                highlight_boundaries=True,
                layout="spring",
                show_clusters=True,
                show_metrics=True,
                format="png"
            )
            
            # Verify the visualization method was called
            mock_mpl_viz.assert_called_once()
            self.assertEqual(result, "test_viz_result")
            
    def test_analyze_cross_document_lineage(self):
        """Test analysis of cross-document lineage."""
        # Create a test graph
        test_graph = nx.DiGraph()
        test_graph.add_node("record1", document_id="doc1", record_type="source", timestamp=1000)
        test_graph.add_node("record2", document_id="doc2", record_type="transformation", timestamp=2000)
        test_graph.add_node("record3", document_id="doc3", record_type="result", timestamp=3000)
        test_graph.add_edge("record1", "record2", relation="input_to", cross_document=True)
        test_graph.add_edge("record2", "record3", relation="output_to", cross_document=True)
        test_graph.graph['documents'] = {"doc1": {}, "doc2": {}, "doc3": {}}
        
        # Perform analysis
        analysis = self.enhancer.analyze_cross_document_lineage(
            lineage_graph=test_graph,
            include_semantic_analysis=True,
            include_impact_analysis=True
        )
        
        # Verify basic analysis results
        self.assertIn('basic_metrics', analysis)
        self.assertEqual(analysis['basic_metrics']['node_count'], 3)
        self.assertEqual(analysis['basic_metrics']['edge_count'], 2)
        self.assertEqual(analysis['basic_metrics']['document_count'], 3)
        
        # Verify time analysis
        self.assertIn('time_analysis', analysis)
        self.assertEqual(analysis['time_analysis']['earliest_timestamp'], 1000)
        self.assertEqual(analysis['time_analysis']['latest_timestamp'], 3000)
        self.assertEqual(analysis['time_analysis']['time_span_seconds'], 2000)


class TestDetailedLineageIntegrator(unittest.TestCase):
    """Tests for the DetailedLineageIntegrator class."""
    
    def setUp(self):
        """Set up test environment."""
        # Create a mock provenance manager
        self.mock_provenance_manager = MagicMock()
        self.mock_provenance_manager.get_provenance_graph.return_value = nx.DiGraph()
        
        # Create a mock lineage enhancer
        self.mock_lineage_enhancer = MagicMock()
        self.mock_lineage_enhancer.storage = MagicMock()
        
        # Create the integrator
        self.integrator = DetailedLineageIntegrator(
            provenance_manager=self.mock_provenance_manager,
            lineage_enhancer=self.mock_lineage_enhancer
        )
        
    def test_integrate_provenance_with_lineage(self):
        """Test integration of provenance graph with lineage graph."""
        # Create test graphs
        provenance_graph = nx.DiGraph()
        provenance_graph.add_node("record1", record_type="source")
        provenance_graph.add_node("record2", record_type="transformation")
        provenance_graph.add_edge("record1", "record2", relation="input_to")
        
        lineage_graph = nx.DiGraph()
        lineage_graph.add_node("record2", record_type="transformation")
        lineage_graph.add_node("record3", record_type="result")
        lineage_graph.add_edge("record2", "record3", relation="output_to", cross_document=True)
        
        # Create integrated graph
        integrated_graph = self.integrator.integrate_provenance_with_lineage(
            provenance_graph=provenance_graph,
            lineage_graph=lineage_graph
        )
        
        # Verify the integrated graph contains all nodes and edges
        self.assertEqual(len(integrated_graph.nodes()), 3)
        self.assertEqual(len(integrated_graph.edges()), 2)
        self.assertTrue(integrated_graph.has_node("record1"))
        self.assertTrue(integrated_graph.has_node("record2"))
        self.assertTrue(integrated_graph.has_node("record3"))
        self.assertTrue(integrated_graph.has_edge("record1", "record2"))
        self.assertTrue(integrated_graph.has_edge("record2", "record3"))
        
        # Verify source information
        self.assertEqual(integrated_graph.nodes["record1"]["source"], "provenance")
        self.assertEqual(integrated_graph.nodes["record2"]["source"], "both")
        self.assertEqual(integrated_graph.nodes["record3"]["source"], "lineage")
        self.assertEqual(integrated_graph.edges["record1", "record2"]["source"], "provenance")
        self.assertEqual(integrated_graph.edges["record2", "record3"]["source"], "lineage")
        
        # Verify integration metadata
        self.assertIn('integration', integrated_graph.graph)
        self.assertEqual(integrated_graph.graph['integration']['provenance_nodes'], 2)
        self.assertEqual(integrated_graph.graph['integration']['lineage_nodes'], 2)
        self.assertEqual(integrated_graph.graph['integration']['integrated_nodes'], 3)
        
    def test_enrich_lineage_semantics(self):
        """Test enrichment of lineage semantics."""
        # Create test graph
        test_graph = nx.DiGraph()
        test_graph.add_node("source1", record_type="source")
        test_graph.add_node("transform1", record_type="transformation")
        test_graph.add_edge("source1", "transform1", relation="input_to")
        
        # Enrich the graph
        enriched_graph = self.integrator.enrich_lineage_semantics(test_graph)
        
        # Verify enrichment was performed
        self.assertEqual(enriched_graph.edges["source1", "transform1"]["semantic_category"], "input")
        self.assertIn("semantic_context", enriched_graph.edges["source1", "transform1"])
        self.assertIn("confidence", enriched_graph.edges["source1", "transform1"])
        self.assertIn("semantic_relationships", enriched_graph.graph)
        
    def test_create_unified_lineage_report(self):
        """Test creation of unified lineage report."""
        # Create a test graph
        test_graph = nx.DiGraph()
        test_graph.add_node("source1", record_type="source", document_id="doc1")
        test_graph.add_node("transform1", record_type="transformation", document_id="doc2")
        test_graph.add_node("result1", record_type="result", document_id="doc2")
        test_graph.add_edge("source1", "transform1", relation="input_to", cross_document=True)
        test_graph.add_edge("transform1", "result1", relation="output_to")
        test_graph.graph['documents'] = {"doc1": {}, "doc2": {}}
        
        # Mock lineage enhancer visualization
        self.mock_lineage_enhancer.visualize_enhanced_cross_document_lineage.return_value = "viz_result"
        
        # Create the report
        with tempfile.NamedTemporaryFile(suffix=".json") as temp_file:
            report = self.integrator.create_unified_lineage_report(
                integrated_graph=test_graph,
                include_visualization=True,
                output_path=temp_file.name
            )
            
            # Verify report structure
            self.assertIn('generated_at', report)
            self.assertEqual(report['record_count'], 3)
            self.assertEqual(report['relationship_count'], 2)
            self.assertIn('structure', report)
            self.assertEqual(report['structure']['node_count'], 3)
            self.assertEqual(report['structure']['edge_count'], 2)
            
            # Verify visualization was called
            self.mock_lineage_enhancer.visualize_enhanced_cross_document_lineage.assert_called_once()


class TestIntegrationWithProvenanceManager(unittest.TestCase):
    """Tests for integration with EnhancedProvenanceManager."""
    
    def setUp(self):
        """Set up an enhanced provenance manager for testing."""
        # Patch IPLD storage to avoid actual storage operations
        self.ipld_storage_patcher = patch('ipfs_datasets_py.data_provenance_enhanced.IPLDStorage')
        self.mock_ipld_storage_class = self.ipld_storage_patcher.start()
        self.mock_ipld_storage = MagicMock()
        self.mock_ipld_storage_class.return_value = self.mock_ipld_storage
        
        # Create provenance manager with mocked storage
        self.provenance_manager = EnhancedProvenanceManager(
            storage_path=None,  # In-memory
            enable_ipld_storage=True,  # Enable IPLD storage (mocked)
            default_agent_id="test_agent",
            tracking_level="detailed"
        )
        
        # Add some test records
        self.source_id = self.provenance_manager.record_source(
            data_id="data001",
            source_type="file",
            location="/path/to/test.csv",
            description="Test source data"
        )
        
        self.transform_id = self.provenance_manager.begin_transformation(
            input_ids=["data001"],
            transformation_type="preprocessing",
            description="Test transformation"
        )
        
        self.result_id = self.provenance_manager.end_transformation(
            transformation_id=self.transform_id,
            output_ids=["data002"],
            success=True
        )
        
    def tearDown(self):
        """Tear down test environment."""
        self.ipld_storage_patcher.stop()
        
    @patch('ipfs_datasets_py.cross_document_lineage_enhanced.CrossDocumentLineageEnhancer')
    @patch('ipfs_datasets_py.cross_document_lineage_enhanced.DetailedLineageIntegrator')
    def test_create_cross_document_lineage(self, mock_integrator_class, mock_enhancer_class):
        """Test creating cross-document lineage with the provenance manager."""
        # Configure mocks
        mock_enhancer = MagicMock()
        mock_enhancer_class.return_value = mock_enhancer
        
        mock_integrator = MagicMock()
        mock_integrator_class.return_value = mock_integrator
        
        # Mock the integrate_provenance_with_lineage method
        integrated_graph = nx.DiGraph()
        mock_integrator.integrate_provenance_with_lineage.return_value = integrated_graph
        
        # Mock the enrich_lineage_semantics method
        enriched_graph = nx.DiGraph()
        mock_integrator.enrich_lineage_semantics.return_value = enriched_graph
        
        # Mock the create_unified_lineage_report method
        expected_report = {"test": "report"}
        mock_integrator.create_unified_lineage_report.return_value = expected_report
        
        # Mock the analyze_data_flow_patterns method
        flow_patterns = {"test": "patterns"}
        mock_integrator.analyze_data_flow_patterns.return_value = flow_patterns
        
        # Call the method under test
        with tempfile.NamedTemporaryFile(suffix=".json") as temp_file:
            report = self.provenance_manager.create_cross_document_lineage(
                output_path=temp_file.name,
                include_visualization=True
            )
            
            # Verify enhancer was created with the correct storage
            mock_enhancer_class.assert_called_once()
            
            # Verify integrator was created with the correct parameters
            mock_integrator_class.assert_called_once_with(
                provenance_manager=self.provenance_manager,
                lineage_enhancer=mock_enhancer
            )
            
            # Verify integration methods were called
            mock_integrator.integrate_provenance_with_lineage.assert_called_once()
            mock_integrator.enrich_lineage_semantics.assert_called_once_with(integrated_graph)
            mock_integrator.create_unified_lineage_report.assert_called_once()
            mock_integrator.analyze_data_flow_patterns.assert_called_once_with(enriched_graph)
            
            # Verify report was returned
            self.assertEqual(report, expected_report)


if __name__ == "__main__":
    unittest.main()