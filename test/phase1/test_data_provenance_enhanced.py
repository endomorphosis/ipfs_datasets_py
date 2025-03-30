"""
Tests for the Enhanced Data Provenance Tracking module.

This module contains comprehensive tests for the enhanced data provenance tracking system,
ensuring that advanced lineage tracking features work correctly.
"""

import os
import json
import tempfile
import unittest
import time
from datetime import datetime
from unittest.mock import patch, MagicMock
import networkx as nx
import base64

from ipfs_datasets_py.data_provenance import (
    ProvenanceRecordType, ProvenanceRecord, SourceRecord
)

from ipfs_datasets_py.data_provenance_enhanced import (
    EnhancedProvenanceManager, ProvenanceMetrics, 
    VerificationRecord, AnnotationRecord, 
    ModelTrainingRecord, ModelInferenceRecord
)


class TestEnhancedProvenanceRecords(unittest.TestCase):
    """Tests for the enhanced provenance record types."""
    
    def test_verification_record(self):
        """Test VerificationRecord creation and serialization."""
        record = VerificationRecord(
            id="verify001",
            verification_type="schema",
            schema={"type": "object", "properties": {"name": {"type": "string"}}},
            validation_rules=[{"field": "name", "rule": "required"}],
            pass_count=95,
            fail_count=5,
            error_samples=[{"id": 1, "error": "name is required"}],
            description="Schema validation",
            is_valid=False
        )
        
        # Test basic attributes
        self.assertEqual(record.id, "verify001")
        self.assertEqual(record.verification_type, "schema")
        self.assertEqual(record.pass_count, 95)
        self.assertEqual(record.fail_count, 5)
        self.assertEqual(len(record.error_samples), 1)
        self.assertEqual(record.is_valid, False)
        
        # Test serialization/deserialization
        record_dict = record.to_dict()
        self.assertEqual(record_dict["id"], "verify001")
        self.assertEqual(record_dict["verification_type"], "schema")
        
        # Test round-trip conversion
        new_record = VerificationRecord.from_dict(record_dict)
        self.assertEqual(new_record.id, record.id)
        self.assertEqual(new_record.verification_type, record.verification_type)
        self.assertEqual(new_record.pass_count, record.pass_count)
    
    def test_annotation_record(self):
        """Test AnnotationRecord creation and serialization."""
        record = AnnotationRecord(
            id="anno001",
            annotation_type="comment",
            content="This dataset needs further cleaning",
            author="user123",
            tags=["todo", "cleanup", "important"],
            description="Dataset quality note"
        )
        
        # Test basic attributes
        self.assertEqual(record.id, "anno001")
        self.assertEqual(record.annotation_type, "comment")
        self.assertEqual(record.content, "This dataset needs further cleaning")
        self.assertEqual(record.author, "user123")
        self.assertEqual(record.tags, ["todo", "cleanup", "important"])
        
        # Test serialization/deserialization
        record_dict = record.to_dict()
        self.assertEqual(record_dict["id"], "anno001")
        self.assertEqual(record_dict["annotation_type"], "comment")
        
        # Test round-trip conversion
        new_record = AnnotationRecord.from_dict(record_dict)
        self.assertEqual(new_record.id, record.id)
        self.assertEqual(new_record.content, record.content)
        self.assertEqual(new_record.tags, record.tags)
    
    def test_model_training_record(self):
        """Test ModelTrainingRecord creation and serialization."""
        record = ModelTrainingRecord(
            id="train001",
            model_type="classifier",
            model_framework="sklearn",
            hyperparameters={"max_depth": 5, "n_estimators": 100},
            metrics={"accuracy": 0.95, "f1": 0.92},
            execution_time=120.5,
            model_size=1024 * 1024,
            model_hash="sha256:abc123",
            description="Random Forest training"
        )
        
        # Test basic attributes
        self.assertEqual(record.id, "train001")
        self.assertEqual(record.model_type, "classifier")
        self.assertEqual(record.model_framework, "sklearn")
        self.assertEqual(record.hyperparameters["max_depth"], 5)
        self.assertEqual(record.metrics["accuracy"], 0.95)
        self.assertEqual(record.execution_time, 120.5)
        self.assertEqual(record.model_size, 1024 * 1024)
        self.assertEqual(record.model_hash, "sha256:abc123")
        
        # Test serialization/deserialization
        record_dict = record.to_dict()
        self.assertEqual(record_dict["id"], "train001")
        self.assertEqual(record_dict["model_type"], "classifier")
        
        # Test round-trip conversion
        new_record = ModelTrainingRecord.from_dict(record_dict)
        self.assertEqual(new_record.id, record.id)
        self.assertEqual(new_record.hyperparameters, record.hyperparameters)
        self.assertEqual(new_record.metrics, record.metrics)
    
    def test_model_inference_record(self):
        """Test ModelInferenceRecord creation and serialization."""
        record = ModelInferenceRecord(
            id="infer001",
            model_id="model001",
            model_version="1.0",
            batch_size=32,
            output_type="predictions",
            performance_metrics={"latency_ms": 25.5, "throughput": 100},
            description="Model inference"
        )
        
        # Test basic attributes
        self.assertEqual(record.id, "infer001")
        self.assertEqual(record.model_id, "model001")
        self.assertEqual(record.model_version, "1.0")
        self.assertEqual(record.batch_size, 32)
        self.assertEqual(record.output_type, "predictions")
        self.assertEqual(record.performance_metrics["latency_ms"], 25.5)
        
        # Test serialization/deserialization
        record_dict = record.to_dict()
        self.assertEqual(record_dict["id"], "infer001")
        self.assertEqual(record_dict["model_id"], "model001")
        
        # Test round-trip conversion
        new_record = ModelInferenceRecord.from_dict(record_dict)
        self.assertEqual(new_record.id, record.id)
        self.assertEqual(new_record.model_version, record.model_version)
        self.assertEqual(new_record.performance_metrics, record.performance_metrics)


class TestProvenanceMetrics(unittest.TestCase):
    """Tests for the ProvenanceMetrics class."""
    
    def setUp(self):
        """Set up a test graph for metrics calculations."""
        self.graph = nx.DiGraph()
        
        # Create a simple DAG for testing
        self.graph.add_node("source1", record_type="source")
        self.graph.add_node("transform1", record_type="transformation")
        self.graph.add_node("transform2", record_type="transformation")
        self.graph.add_node("merge1", record_type="merge")
        self.graph.add_node("result1", record_type="result")
        
        self.graph.add_edge("source1", "transform1")
        self.graph.add_edge("transform1", "transform2")
        self.graph.add_edge("transform1", "merge1")
        self.graph.add_edge("transform2", "merge1")
        self.graph.add_edge("merge1", "result1")
    
    def test_calculate_data_impact(self):
        """Test calculating data impact."""
        # Source node should have high impact (affects all downstream nodes)
        source_impact = ProvenanceMetrics.calculate_data_impact(self.graph, "source1")
        
        # Result node should have low impact (no downstream nodes)
        result_impact = ProvenanceMetrics.calculate_data_impact(self.graph, "result1")
        
        # Transformation node should have medium impact
        transform_impact = ProvenanceMetrics.calculate_data_impact(self.graph, "transform1")
        
        # Verify relationships
        self.assertGreater(source_impact, transform_impact)
        self.assertGreater(transform_impact, result_impact)
        self.assertEqual(result_impact, 0)  # No descendants
    
    def test_calculate_centrality(self):
        """Test calculating centrality metrics."""
        # Get centrality for all nodes
        centrality = ProvenanceMetrics.calculate_centrality(self.graph)
        
        # Check each node has a centrality score
        for node in self.graph.nodes():
            self.assertIn(node, centrality)
        
        # Merge node should have high centrality (sits on many paths)
        self.assertGreater(centrality["merge1"], centrality["source1"])
        self.assertGreater(centrality["merge1"], centrality["result1"])
        
        # Filter by node type
        transformation_centrality = ProvenanceMetrics.calculate_centrality(
            self.graph, node_type="transformation"
        )
        
        # Only transformation nodes should be included
        self.assertEqual(len(transformation_centrality), 2)
        self.assertIn("transform1", transformation_centrality)
        self.assertIn("transform2", transformation_centrality)
    
    def test_calculate_complexity(self):
        """Test calculating complexity metrics."""
        complexity = ProvenanceMetrics.calculate_complexity(self.graph, "result1")
        
        # Check basic metrics
        self.assertEqual(complexity["node_count"], 5)
        self.assertEqual(complexity["edge_count"], 5)
        self.assertEqual(complexity["max_depth"], 4)  # source1 -> transform1 -> transform2 -> merge1 -> result1
        self.assertEqual(complexity["transformation_count"], 2)
        self.assertEqual(complexity["merge_count"], 1)
        
        # Test with non-existent node
        error_complexity = ProvenanceMetrics.calculate_complexity(self.graph, "nonexistent")
        self.assertIn("error", error_complexity)


class TestEnhancedProvenanceManager(unittest.TestCase):
    """Tests for the EnhancedProvenanceManager class."""
    
    def setUp(self):
        """Set up an enhanced provenance manager for testing."""
        self.provenance_manager = EnhancedProvenanceManager(
            storage_path=None,  # In-memory
            enable_ipld_storage=False,
            default_agent_id="test_agent",
            tracking_level="detailed",
            visualization_engine="matplotlib"
        )
        
        # Create some initial test data
        self.source_id = self.provenance_manager.record_source(
            data_id="data001",
            source_type="file",
            location="/path/to/data.csv",
            description="Initial test data"
        )
    
    def test_record_verification(self):
        """Test recording a verification event."""
        verification_id = self.provenance_manager.record_verification(
            data_id="data001",
            verification_type="schema",
            schema={"type": "object", "properties": {"name": {"type": "string"}}},
            validation_rules=[{"field": "name", "rule": "required"}],
            pass_count=95,
            fail_count=5,
            error_samples=[{"id": 1, "error": "name is required"}],
            description="Schema validation"
        )
        
        # Verify record was created
        self.assertIn(verification_id, self.provenance_manager.records)
        record = self.provenance_manager.records[verification_id]
        self.assertIsInstance(record, VerificationRecord)
        self.assertEqual(record.verification_type, "schema")
        self.assertEqual(record.pass_count, 95)
        self.assertEqual(record.fail_count, 5)
        self.assertEqual(record.is_valid, False)  # fail_count > 0
        
        # Verify graph connection
        self.assertTrue(self.provenance_manager.graph.has_edge(self.source_id, verification_id))
        self.assertEqual(self.provenance_manager.graph[self.source_id][verification_id]["type"], "verifies")
        
        # Verify semantic indexing
        self.assertIn("verification", self.provenance_manager.semantic_index)
        self.assertIn(verification_id, self.provenance_manager.semantic_index["verification"])
        self.assertIn("schema", self.provenance_manager.semantic_index)
        self.assertIn(verification_id, self.provenance_manager.semantic_index["schema:schema"])
        
        # Verify temporal indexing
        found = False
        for bucket, records in self.provenance_manager.time_index.items():
            if verification_id in records:
                found = True
                break
        self.assertTrue(found, "Record should be indexed by time")
    
    def test_record_annotation(self):
        """Test recording an annotation event."""
        annotation_id = self.provenance_manager.record_annotation(
            data_id="data001",
            content="This dataset needs further cleaning",
            annotation_type="comment",
            author="user123",
            tags=["todo", "cleanup"],
            description="Dataset quality note"
        )
        
        # Verify record was created
        self.assertIn(annotation_id, self.provenance_manager.records)
        record = self.provenance_manager.records[annotation_id]
        self.assertIsInstance(record, AnnotationRecord)
        self.assertEqual(record.content, "This dataset needs further cleaning")
        self.assertEqual(record.annotation_type, "comment")
        self.assertEqual(record.author, "user123")
        self.assertEqual(record.tags, ["todo", "cleanup"])
        
        # Verify graph connection
        self.assertTrue(self.provenance_manager.graph.has_edge(self.source_id, annotation_id))
        self.assertEqual(self.provenance_manager.graph[self.source_id][annotation_id]["type"], "annotates")
        
        # Verify semantic indexing
        self.assertIn("annotation", self.provenance_manager.semantic_index)
        self.assertIn(annotation_id, self.provenance_manager.semantic_index["annotation"])
        self.assertIn("tag:todo", self.provenance_manager.semantic_index)
        self.assertIn(annotation_id, self.provenance_manager.semantic_index["tag:todo"])
        self.assertIn("author:user123", self.provenance_manager.semantic_index)
        self.assertIn(annotation_id, self.provenance_manager.semantic_index["author:user123"])
    
    def test_record_model_training(self):
        """Test recording a model training event."""
        training_id = self.provenance_manager.record_model_training(
            input_ids=["data001"],
            output_id="model001",
            model_type="classifier",
            model_framework="sklearn",
            hyperparameters={"max_depth": 5, "n_estimators": 100},
            metrics={"accuracy": 0.95, "f1": 0.92},
            model_size=1024 * 1024,
            model_hash="sha256:abc123",
            description="Random Forest training"
        )
        
        # Verify record was created
        self.assertIn(training_id, self.provenance_manager.records)
        record = self.provenance_manager.records[training_id]
        self.assertIsInstance(record, ModelTrainingRecord)
        self.assertEqual(record.model_type, "classifier")
        self.assertEqual(record.model_framework, "sklearn")
        self.assertEqual(record.hyperparameters["max_depth"], 5)
        self.assertEqual(record.metrics["accuracy"], 0.95)
        self.assertIsNotNone(record.execution_time)
        self.assertEqual(record.model_size, 1024 * 1024)
        self.assertEqual(record.model_hash, "sha256:abc123")
        
        # Verify graph connections
        self.assertTrue(self.provenance_manager.graph.has_edge(self.source_id, training_id))
        self.assertTrue(self.provenance_manager.graph.has_edge(training_id, "model001"))
        
        # Verify entity's latest record was updated
        self.assertEqual(self.provenance_manager.entity_latest_record["model001"], training_id)
    
    def test_record_model_inference(self):
        """Test recording a model inference event."""
        # First add a model
        training_id = self.provenance_manager.record_model_training(
            input_ids=["data001"],
            output_id="model001",
            model_type="classifier",
            model_framework="sklearn",
            description="Test model"
        )
        
        # Now record inference using this model
        inference_id = self.provenance_manager.record_model_inference(
            model_id="model001",
            input_ids=["data001"],
            output_id="predictions001",
            model_version="1.0",
            batch_size=32,
            output_type="predictions",
            performance_metrics={"latency_ms": 25.5, "throughput": 100},
            description="Model inference"
        )
        
        # Verify record was created
        self.assertIn(inference_id, self.provenance_manager.records)
        record = self.provenance_manager.records[inference_id]
        self.assertIsInstance(record, ModelInferenceRecord)
        self.assertEqual(record.model_id, "model001")
        self.assertEqual(record.model_version, "1.0")
        self.assertEqual(record.batch_size, 32)
        self.assertEqual(record.output_type, "predictions")
        self.assertEqual(record.performance_metrics["latency_ms"], 25.5)
        self.assertIsNotNone(record.execution_time)
        
        # Verify graph connections
        self.assertTrue(self.provenance_manager.graph.has_edge(training_id, inference_id))  # Model to inference
        self.assertTrue(self.provenance_manager.graph.has_edge(self.source_id, inference_id))  # Input data to inference
        self.assertTrue(self.provenance_manager.graph.has_edge(inference_id, "predictions001"))  # Inference to output
        
        # Verify entity's latest record was updated
        self.assertEqual(self.provenance_manager.entity_latest_record["predictions001"], inference_id)
    
    def test_semantic_search(self):
        """Test semantic search functionality."""
        # Add records with various attributes for testing search
        self.provenance_manager.record_verification(
            data_id="data001",
            verification_type="schema",
            description="Schema validation of customer data",
            pass_count=100,
            fail_count=0
        )
        
        self.provenance_manager.record_annotation(
            data_id="data001",
            content="This dataset contains customer information",
            annotation_type="note",
            tags=["customer", "important"]
        )
        
        self.provenance_manager.record_model_training(
            input_ids=["data001"],
            output_id="model001",
            model_type="regression",
            description="Predictive model for customer spend"
        )
        
        # Search for "customer" (should match all records)
        customer_results = self.provenance_manager.semantic_search("customer")
        self.assertGreaterEqual(len(customer_results), 3)
        
        # Search for "schema validation" (should match verification record)
        schema_results = self.provenance_manager.semantic_search("schema validation")
        self.assertEqual(len(schema_results), 1)
        self.assertEqual(schema_results[0]["record_type"], "transformation")
        
        # Search for "regression model" (should match training record)
        model_results = self.provenance_manager.semantic_search("regression model")
        self.assertEqual(len(model_results), 1)
        
        # Search for "important tag" (should match annotation record)
        tag_results = self.provenance_manager.semantic_search("important tag")
        self.assertEqual(len(tag_results), 1)
        
        # Search with limit
        limited_results = self.provenance_manager.semantic_search("customer", limit=1)
        self.assertEqual(len(limited_results), 1)
    
    def test_temporal_query(self):
        """Test temporal query functionality."""
        # Create records at different times
        with patch('time.time') as mock_time:
            # First record: Jan 1, 2023
            mock_time.return_value = 1672531200  # 2023-01-01
            record1_id = self.provenance_manager.record_annotation(
                data_id="data001",
                content="First annotation",
                annotation_type="note"
            )
            
            # Second record: Feb 1, 2023
            mock_time.return_value = 1675209600  # 2023-02-01
            record2_id = self.provenance_manager.record_annotation(
                data_id="data001",
                content="Second annotation",
                annotation_type="comment"
            )
            
            # Third record: Mar 1, 2023
            mock_time.return_value = 1677628800  # 2023-03-01
            record3_id = self.provenance_manager.record_verification(
                data_id="data001",
                verification_type="integrity",
                description="Integrity check"
            )
        
        # Query for January 2023
        jan_results = self.provenance_manager.temporal_query(
            start_time=1672531200,  # 2023-01-01
            end_time=1675209599,    # 2023-01-31 23:59:59
            time_bucket="daily"
        )
        self.assertEqual(len(jan_results), 1)
        self.assertEqual(jan_results[0]["record_id"], record1_id)
        
        # Query for Q1 2023
        q1_results = self.provenance_manager.temporal_query(
            start_time=1672531200,  # 2023-01-01
            end_time=1680307199,    # 2023-03-31 23:59:59
            time_bucket="monthly"
        )
        self.assertEqual(len(q1_results), 3)
        
        # Query by record type
        annotation_results = self.provenance_manager.temporal_query(
            start_time=1672531200,  # 2023-01-01
            end_time=1680307199,    # 2023-03-31 23:59:59
            record_types=["annotation"]
        )
        self.assertEqual(len(annotation_results), 2)
        
        verification_results = self.provenance_manager.temporal_query(
            start_time=1672531200,  # 2023-01-01
            end_time=1680307199,    # 2023-03-31 23:59:59
            record_types=["verification"]
        )
        self.assertEqual(len(verification_results), 0)  # Verification was added as transformation
    
    def test_calculate_data_metrics(self):
        """Test data metrics calculation."""
        # Create a more complex provenance chain
        data_id = "metrics_data"
        source_id = self.provenance_manager.record_source(
            data_id=data_id,
            source_type="database",
            location="postgresql://host/db",
            description="Metrics test data"
        )
        
        with patch('time.time') as mock_time:
            # First transformation (1 day later)
            mock_time.return_value = time.time() + 86400
            transform1_id = self.provenance_manager.begin_transformation(
                description="First transformation",
                transformation_type="preprocessing",
                input_ids=[data_id]
            )
            self.provenance_manager.end_transformation(
                transformation_id=transform1_id,
                output_ids=[f"{data_id}_t1"],
                success=True
            )
            
            # Verification (2 days later)
            mock_time.return_value = time.time() + 2*86400
            verify_id = self.provenance_manager.record_verification(
                data_id=f"{data_id}_t1",
                verification_type="quality",
                pass_count=95,
                fail_count=5,
                description="Quality check"
            )
            
            # Second transformation (3 days later)
            mock_time.return_value = time.time() + 3*86400
            transform2_id = self.provenance_manager.begin_transformation(
                description="Second transformation",
                transformation_type="feature_extraction",
                input_ids=[f"{data_id}_t1"]
            )
            self.provenance_manager.end_transformation(
                transformation_id=transform2_id,
                output_ids=[f"{data_id}_t2"],
                success=True
            )
        
        # Calculate metrics
        metrics = self.provenance_manager.calculate_data_metrics(f"{data_id}_t2")
        
        # Verify complexity metrics
        self.assertIn("complexity", metrics)
        self.assertGreaterEqual(metrics["complexity"]["node_count"], 4)
        self.assertGreaterEqual(metrics["complexity"]["edge_count"], 3)
        
        # Verify impact metrics
        self.assertIn("impact", metrics)
        
        # Verify time metrics
        self.assertIn("first_timestamp", metrics)
        self.assertIn("last_timestamp", metrics)
        self.assertIn("age_seconds", metrics)
        self.assertIn("update_frequency", metrics)
        
        # Verify record type counts
        self.assertIn("record_type_counts", metrics)
        self.assertIn("source", metrics["record_type_counts"])
        self.assertIn("transformation", metrics["record_type_counts"])
        
        # Verify verification metrics
        self.assertIn("verification", metrics)
        self.assertEqual(metrics["verification"]["verifications"], 0)  # None for this specific data_id
    
    @patch('matplotlib.pyplot.savefig')
    def test_visualize_provenance_enhanced(self, mock_savefig):
        """Test enhanced provenance visualization."""
        # Create some test data for visualization
        data_id = "viz_data"
        source_id = self.provenance_manager.record_source(
            data_id=data_id,
            source_type="file",
            location="/path/to/viz.csv",
            description="Visualization test data"
        )
        
        transform_id = self.provenance_manager.begin_transformation(
            description="Data transformation",
            transformation_type="preprocessing",
            input_ids=[data_id],
            parameters={"option1": True}
        )
        self.provenance_manager.end_transformation(
            transformation_id=transform_id,
            output_ids=[f"{data_id}_transformed"],
            success=True
        )
        
        # Test default visualization (matplotlib)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_path = temp_file.name
            
        try:
            result = self.provenance_manager.visualize_provenance_enhanced(
                data_ids=[f"{data_id}_transformed"],
                max_depth=3,
                include_parameters=True,
                file_path=temp_path,
                format="png"
            )
            mock_savefig.assert_called_once()
            self.assertIsNone(result)  # Should return None when saving to file
            
            # Test base64 return
            mock_savefig.reset_mock()
            result = self.provenance_manager.visualize_provenance_enhanced(
                data_ids=[f"{data_id}_transformed"],
                max_depth=3,
                return_base64=True,
                format="png"
            )
            mock_savefig.assert_called_once()
            self.assertIsInstance(result, str)  # Should return a base64 string
            
            # Try decode the base64 string
            try:
                base64.b64decode(result)
                decode_success = True
            except:
                decode_success = False
            self.assertTrue(decode_success, "Result should be a valid base64-encoded string")
            
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


if __name__ == '__main__':
    unittest.main()