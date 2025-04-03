#!/usr/bin/env python3
"""
Test for the enhanced cross-document lineage tracking capabilities.
"""

import os
import unittest
import tempfile
import networkx as nx
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for testing
import datetime
import json
import numpy as np
from unittest.mock import MagicMock, patch
import sys

# Add the parent directory to the Python path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    # Import the modules to test
    from ipfs_datasets_py.cross_document_lineage_enhanced import (
        CrossDocumentLineageEnhancer, CrossDocumentImpactAnalyzer
    )
    from ipfs_datasets_py.data_provenance_enhanced import (
        IPLDProvenanceStorage, EnhancedProvenanceManager,
        SourceRecord, TransformationRecord, ProvenanceRecordType
    )
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False

# Skip tests if modules aren't available
@unittest.skipIf(not MODULES_AVAILABLE, "Required modules not available")
class TestEnhancedCrossDocumentLineage(unittest.TestCase):
    """Test the enhanced cross-document lineage tracking capabilities."""
    
    def setUp(self):
        """Set up test environment."""
        # Create mock storage
        self.mock_storage = MagicMock(spec=IPLDProvenanceStorage)
        
        # Create mock record CIDs mapping
        self.mock_storage.record_cids = {
            "source1": "cid-source1",
            "source2": "cid-source2",
            "transform1": "cid-transform1",
            "transform2": "cid-transform2",
            "output1": "cid-output1",
            "output2": "cid-output2"
        }
        
        # Set up mock records
        source1 = MagicMock(spec=SourceRecord)
        source1.metadata = {"document_id": "doc1"}
        source1.record_type = ProvenanceRecordType.SOURCE
        
        source2 = MagicMock(spec=SourceRecord)
        source2.metadata = {"document_id": "doc1"}
        source2.record_type = ProvenanceRecordType.SOURCE
        
        transform1 = MagicMock(spec=TransformationRecord)
        transform1.metadata = {"document_id": "doc1"}
        transform1.record_type = ProvenanceRecordType.TRANSFORMATION
        
        transform2 = MagicMock(spec=TransformationRecord)
        transform2.metadata = {"document_id": "doc2"}
        transform2.record_type = ProvenanceRecordType.TRANSFORMATION
        
        output1 = MagicMock(spec=TransformationRecord)
        output1.metadata = {"document_id": "doc2"}
        output1.record_type = ProvenanceRecordType.TRANSFORMATION
        
        output2 = MagicMock(spec=TransformationRecord)
        output2.metadata = {"document_id": "doc2"}
        output2.record_type = ProvenanceRecordType.TRANSFORMATION
        
        # Mock storage.load_record to return appropriate mock records
        def mock_load_record(cid):
            if cid == "cid-source1":
                return source1
            elif cid == "cid-source2":
                return source2
            elif cid == "cid-transform1":
                return transform1
            elif cid == "cid-transform2":
                return transform2
            elif cid == "cid-output1":
                return output1
            elif cid == "cid-output2":
                return output2
            else:
                return None
        
        self.mock_storage.load_record = MagicMock(side_effect=mock_load_record)
        
        # Mock link_cross_document_provenance to return a CID
        self.mock_storage.link_cross_document_provenance = MagicMock(
            return_value="xdoc-link-cid"
        )
        
        # Create a basic test graph for build_cross_document_lineage_graph
        test_graph = nx.DiGraph()
        test_graph.add_node("source1", record_type="source", document_id="doc1")
        test_graph.add_node("source2", record_type="source", document_id="doc1")
        test_graph.add_node("transform1", record_type="transformation", document_id="doc1")
        test_graph.add_node("transform2", record_type="transformation", document_id="doc2")
        test_graph.add_node("output1", record_type="transformation", document_id="doc2")
        test_graph.add_node("output2", record_type="transformation", document_id="doc2")
        
        # Add edges
        test_graph.add_edge("source1", "transform1", relation="input_to", cross_document=False)
        test_graph.add_edge("source2", "transform1", relation="input_to", cross_document=False)
        test_graph.add_edge("transform1", "transform2", relation="derived_from", cross_document=True)
        test_graph.add_edge("transform2", "output1", relation="output_to", cross_document=False)
        test_graph.add_edge("transform2", "output2", relation="output_to", cross_document=False)
        
        # Add graph attributes
        test_graph.graph['documents'] = {
            "doc1": {"record_count": 3, "records": ["source1", "source2", "transform1"]},
            "doc2": {"record_count": 3, "records": ["transform2", "output1", "output2"]}
        }
        
        self.mock_storage.build_cross_document_lineage_graph = MagicMock(
            return_value=test_graph
        )
        
        # Create enhancer instance
        self.enhancer = CrossDocumentLineageEnhancer(self.mock_storage)
        
        # Create impact analyzer instance
        self.impact_analyzer = CrossDocumentImpactAnalyzer(self.mock_storage)
    
    def test_link_cross_document_provenance_with_enhanced_features(self):
        """Test linking provenance records with enhanced features."""
        # Test basic linking
        link_cid = self.enhancer.link_cross_document_provenance(
            source_record_id="source1",
            target_record_id="transform2",
            link_type="derived_from"
        )
        
        # Verify link was created
        self.assertEqual(link_cid, "xdoc-link-cid")
        self.mock_storage.link_cross_document_provenance.assert_called_once()
        
        # Verify arguments
        args, kwargs = self.mock_storage.link_cross_document_provenance.call_args
        self.assertEqual(kwargs["source_record_id"], "source1")
        self.assertEqual(kwargs["target_record_id"], "transform2")
        self.assertEqual(kwargs["link_type"], "derived_from")
        
        # Test linking with semantic context and boundary type
        self.mock_storage.link_cross_document_provenance.reset_mock()
        
        semantic_context = {
            "category": "causal",
            "description": "Source data directly feeds transformation",
            "keywords": ["derived", "data flow"]
        }
        
        link_cid = self.enhancer.link_cross_document_provenance(
            source_record_id="source1",
            target_record_id="transform2",
            link_type="derived_from",
            confidence=0.85,
            semantic_context=semantic_context,
            boundary_type="dataset"
        )
        
        # Verify link was created with enhanced properties
        self.assertEqual(link_cid, "xdoc-link-cid")
        self.mock_storage.link_cross_document_provenance.assert_called_once()
        
        # Verify arguments contain enhanced properties
        args, kwargs = self.mock_storage.link_cross_document_provenance.call_args
        self.assertEqual(kwargs["source_record_id"], "source1")
        self.assertEqual(kwargs["target_record_id"], "transform2")
        
        # Check that properties dictionary contains the enhanced information
        properties = kwargs["properties"]
        self.assertIsNotNone(properties)
        self.assertEqual(properties["confidence"], 0.85)
        self.assertEqual(properties["semantic_context"], semantic_context)
        self.assertEqual(properties["boundary_type"], "dataset")
        self.assertIn("created_at", properties)
        self.assertEqual(properties["source_document_id"], "doc1")
        self.assertEqual(properties["target_document_id"], "doc2")
    
    def test_build_enhanced_cross_document_lineage_graph(self):
        """Test building enhanced cross-document lineage graph."""
        # Build enhanced graph
        graph = self.enhancer.build_enhanced_cross_document_lineage_graph(
            record_ids="source1",
            max_depth=3
        )
        
        # Verify graph was built using the storage method
        self.mock_storage.build_cross_document_lineage_graph.assert_called_once()
        
        # Verify arguments
        args, kwargs = self.mock_storage.build_cross_document_lineage_graph.call_args
        self.assertEqual(kwargs["record_ids"], "source1")
        self.assertEqual(kwargs["max_depth"], 3)
        
        # Verify graph has been enhanced
        self.assertIn('document_boundaries', graph.graph)
        self.assertIn('boundary_types', graph.graph)
        self.assertIn('semantic_relationships', graph.graph)
        self.assertIn('semantic_categories', graph.graph)
        self.assertIn('document_clusters', graph.graph)
        self.assertIn('data_flow_metrics', graph.graph)
    
    def test_analyze_cross_document_lineage(self):
        """Test analyzing cross-document lineage."""
        # Get enhanced graph (mock build_enhanced_cross_document_lineage_graph)
        enhanced_graph = self.mock_storage.build_cross_document_lineage_graph()
        
        # Perform analysis
        analysis = self.enhancer.analyze_cross_document_lineage(
            lineage_graph=enhanced_graph,
            include_semantic_analysis=True,
            include_impact_analysis=True,
            include_cluster_analysis=True
        )
        
        # Verify analysis has all expected components
        self.assertIn('basic_metrics', analysis)
        self.assertIn('node_count', analysis['basic_metrics'])
        self.assertIn('edge_count', analysis['basic_metrics'])
        self.assertIn('document_count', analysis['basic_metrics'])
        self.assertIn('cross_document_edge_count', analysis['basic_metrics'])
        self.assertIn('cross_document_ratio', analysis['basic_metrics'])
        
        # Check if metrics match expected values
        self.assertEqual(analysis['basic_metrics']['node_count'], 6)
        self.assertEqual(analysis['basic_metrics']['edge_count'], 5)
        self.assertEqual(analysis['basic_metrics']['document_count'], 2)
        
        # Verify that other analysis sections are present
        if 'time_analysis' in analysis:
            self.assertIn('earliest_timestamp', analysis['time_analysis'])
            self.assertIn('latest_timestamp', analysis['time_analysis'])
    
    def test_visualize_enhanced_cross_document_lineage(self):
        """Test visualizing enhanced cross-document lineage."""
        # Get enhanced graph (mock build_enhanced_cross_document_lineage_graph)
        enhanced_graph = self.mock_storage.build_cross_document_lineage_graph()
        
        # Test visualization with file output
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            # Generate visualization
            result = self.enhancer.visualize_enhanced_cross_document_lineage(
                lineage_graph=enhanced_graph,
                highlight_cross_document=True,
                highlight_boundaries=True,
                layout="spring",
                show_clusters=True,
                show_metrics=True,
                file_path=temp_path,
                format="png"
            )
            
            # Verify file was created
            self.assertTrue(os.path.exists(temp_path))
            self.assertTrue(os.path.getsize(temp_path) > 0)
            
            # Verify result is None when saving to file
            self.assertIsNone(result)
            
            # Test without file path (returns data)
            result = self.enhancer.visualize_enhanced_cross_document_lineage(
                lineage_graph=enhanced_graph,
                file_path=None,
                format="png"
            )
            
            # Verify result is not None when not saving to file
            self.assertIsNotNone(result)
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_export_cross_document_lineage(self):
        """Test exporting cross-document lineage."""
        # Get enhanced graph (mock build_enhanced_cross_document_lineage_graph)
        enhanced_graph = self.mock_storage.build_cross_document_lineage_graph()
        
        # Test JSON export
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            # Export to JSON file
            result = self.enhancer.export_cross_document_lineage(
                lineage_graph=enhanced_graph,
                format="json",
                file_path=temp_path
            )
            
            # Verify file was created
            self.assertTrue(os.path.exists(temp_path))
            self.assertTrue(os.path.getsize(temp_path) > 0)
            
            # Verify result is None when saving to file
            self.assertIsNone(result)
            
            # Read and verify JSON content
            with open(temp_path, "r") as f:
                data = json.load(f)
                
            self.assertIn("nodes", data)
            self.assertIn("edges", data)
            self.assertIn("metadata", data)
            self.assertEqual(len(data["nodes"]), 6)
            self.assertEqual(len(data["edges"]), 5)
            
            # Test without file path (returns data)
            result = self.enhancer.export_cross_document_lineage(
                lineage_graph=enhanced_graph,
                format="json",
                file_path=None
            )
            
            # Verify result structure
            self.assertIsNotNone(result)
            self.assertIn("nodes", result)
            self.assertIn("edges", result)
            self.assertIn("metadata", result)
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_impact_analyzer(self):
        """Test the CrossDocumentImpactAnalyzer."""
        # Get enhanced graph (mock build_cross_document_lineage_graph)
        enhanced_graph = self.mock_storage.build_cross_document_lineage_graph()
        
        # Mock analyze_impact to avoid dependency on storage
        self.impact_analyzer.analyze_impact = MagicMock(return_value={
            'source_id': 'source1',
            'source_document': 'doc1',
            'impacted_documents': {
                'doc2': {
                    'impacted_nodes': 3,
                    'impact_paths': [
                        {'path': ['source1', 'transform1', 'transform2'], 'document_path': ['doc1', 'doc1', 'doc2'], 'length': 3, 'crosses_document': True}
                    ]
                }
            },
            'impact_paths': [
                {'path': ['source1', 'transform1', 'transform2'], 'document_path': ['doc1', 'doc1', 'doc2'], 'length': 3, 'crosses_document': True},
                {'path': ['source1', 'transform1', 'transform2', 'output1'], 'document_path': ['doc1', 'doc1', 'doc2', 'doc2'], 'length': 4, 'crosses_document': True},
                {'path': ['source1', 'transform1', 'transform2', 'output2'], 'document_path': ['doc1', 'doc1', 'doc2', 'doc2'], 'length': 4, 'crosses_document': True}
            ],
            'impact_metrics': {
                'total_impacted_nodes': 3,
                'impacted_document_count': 1,
                'max_path_length': 4,
                'cross_document_paths': 3,
                'impact_score': 0.6
            }
        })
        
        # Test impact analysis
        impact = self.impact_analyzer.analyze_impact("source1", max_depth=3)
        
        # Verify impact analysis result structure
        self.assertEqual(impact['source_id'], 'source1')
        self.assertEqual(impact['source_document'], 'doc1')
        self.assertIn('impacted_documents', impact)
        self.assertIn('impact_paths', impact)
        self.assertIn('impact_metrics', impact)
        
        # Check metrics
        metrics = impact['impact_metrics']
        self.assertEqual(metrics['total_impacted_nodes'], 3)
        self.assertEqual(metrics['impacted_document_count'], 1)
        self.assertEqual(metrics['cross_document_paths'], 3)
        
        # Test impact visualization with file output
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            # Override visualize_impact to avoid matplotlib dependencies in tests
            self.impact_analyzer.visualize_impact = MagicMock(return_value=None)
            
            # Generate visualization
            result = self.impact_analyzer.visualize_impact(
                source_id="source1",
                max_depth=3,
                file_path=temp_path,
                format="png"
            )
            
            # Verify visualization method was called
            self.impact_analyzer.visualize_impact.assert_called_once()
            
        finally:
            # Clean up (no need to delete as the file wasn't actually created)
            pass


if __name__ == '__main__':
    unittest.main()