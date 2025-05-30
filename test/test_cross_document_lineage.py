#!/usr/bin/env python3
"""
Enhanced tests for the cross-document lineage tracking module.

This module provides comprehensive tests for the cross-document lineage tracking
capabilities with enhanced data provenance and audit logging integration.
"""

import os
import unittest
import tempfile
import networkx as nx
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for testing
import datetime
import json
import uuid
import hmac
import hashlib
import base64
import io
import numpy as np
from unittest.mock import MagicMock, patch
import sys

# Add the parent directory to the Python path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import to check availability
try:
    from ipfs_datasets_py.ipld.storage import IPLDStorage
    from ipfs_datasets_py.ipld.dag_pb import DAGNode, DAGLink
    IPLD_AVAILABLE = True
except ImportError:
    IPLD_AVAILABLE = False

# Try importing the audit system
try:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditLogger, AuditEvent, AuditLevel, AuditCategory
    )
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False

# Try importing from the enhanced provenance module
try:
    from ipfs_datasets_py.data_provenance_enhanced import (
        EnhancedProvenanceManager,
        ProvenanceCryptoVerifier,
        SourceRecord,
        TransformationRecord,
        VerificationRecord,
        IPLDProvenanceStorage
    )
    from ipfs_datasets_py.cross_document_lineage import (
        CrossDocumentLineageTracker,
        LinkType,
        CrossDocumentLink,
        integrate_with_provenance_manager
    )
    from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator

    ENHANCED_PROVENANCE_AVAILABLE = True
except ImportError as e:
    print(f"Enhanced provenance modules not available: {e}")
    ENHANCED_PROVENANCE_AVAILABLE = False

    # Create mock classes if needed
    class LinkType:
        DERIVED_FROM = "derived_from"
        INFLUENCED_BY = "influenced_by"
        CITED_BY = "cited_by"
        REFERS_TO = "refers_to"
        SEMANTICALLY_SIMILAR = "semantically_similar"

    class CrossDocumentLink:
        def __init__(self, link_id, source_record_id, target_record_id, link_type, confidence=1.0, properties=None, timestamp=None, signature=None):
            self.link_id = link_id
            self.source_record_id = source_record_id
            self.target_record_id = target_record_id
            self.link_type = link_type
            self.confidence = confidence
            self.properties = properties or {}
            self.timestamp = timestamp or datetime.datetime.now().timestamp()
            self.signature = signature

        def to_dict(self):
            return {
                "link_id": self.link_id,
                "source_record_id": self.source_record_id,
                "target_record_id": self.target_record_id,
                "link_type": self.link_type,
                "confidence": self.confidence,
                "properties": self.properties,
                "timestamp": self.timestamp,
                "signature": self.signature
            }

        @classmethod
        def from_dict(cls, data):
            return cls(**data)

    class CrossDocumentLineageTracker:
        def __init__(self, provenance_storage=None, audit_logger=None, crypto_verifier=None, min_confidence_threshold=0.7, link_verification=True):
            self.provenance_storage = provenance_storage
            self.audit_logger = audit_logger
            self.crypto_verifier = crypto_verifier
            self.min_confidence_threshold = min_confidence_threshold
            self.link_verification = link_verification
            self._link_cache = {}

        def create_link(self, source_record_id, target_record_id, link_type, confidence=1.0, properties=None, audit_event=True):
            link_id = f"link-{uuid.uuid4()}"
            link = CrossDocumentLink(
                link_id=link_id,
                source_record_id=source_record_id,
                target_record_id=target_record_id,
                link_type=link_type if isinstance(link_type, str) else link_type.value,
                confidence=confidence,
                properties=properties or {}
            )
            self._link_cache[link_id] = link
            return link_id

        def get_links_for_record(self, record_id, link_types=None, min_confidence=None, direction="both"):
            links = []
            for link in self._link_cache.values():
                if direction in ["outgoing", "both"] and link.source_record_id == record_id:
                    links.append(link)
                elif direction in ["incoming", "both"] and link.target_record_id == record_id:
                    links.append(link)
            return links

        def build_lineage_graph(self, record_ids, max_depth=3, link_types=None, min_confidence=0.7, include_internal_links=True):
            graph = nx.DiGraph()
            for record_id in record_ids:
                graph.add_node(record_id, record_type="unknown", description=f"Record {record_id}")
            return graph

        def analyze_lineage(self, record_ids, max_depth=3, link_types=None, min_confidence=0.7, include_internal_links=True):
            return {
                "basic_metrics": {
                    "node_count": len(record_ids),
                    "edge_count": 0,
                    "cross_document_edge_count": 0,
                    "cross_document_ratio": 0.0
                }
            }

        def visualize_lineage(self, record_ids=None, lineage_graph=None, max_depth=3, link_types=None, min_confidence=0.7, include_internal_links=True, highlight_cross_document=True, layout="hierarchical", show_metrics=True, file_path=None, format="png", width=1200, height=800):
            if file_path:
                return None
            return "mock_visualization"

        def export_lineage(self, record_ids=None, lineage_graph=None, max_depth=3, link_types=None, min_confidence=0.7, include_internal_links=True, format="json", file_path=None, include_records=False):
            if file_path:
                return None
            return {
                "nodes": [{"id": record_id} for record_id in (record_ids or [])],
                "edges": [],
                "metadata": {"node_count": len(record_ids or [])}
            }

    def integrate_with_provenance_manager(provenance_manager=None, audit_logger=None):
        return CrossDocumentLineageTracker()


class TestCrossDocumentLineage(unittest.TestCase):
    """Tests for the enhanced cross-document lineage tracking capabilities."""

    def setUp(self):
        """Set up test environment."""
        self.temp_files = []

        # Create mock components
        self.mock_audit_logger = MagicMock()
        self.mock_audit_logger.log_event.return_value = "audit-event-123"
        self.mock_audit_logger.get_instance.return_value = self.mock_audit_logger
        self.mock_audit_logger.default_user = "test-user"

        # Create a mock crypto verifier
        self.mock_crypto_verifier = MagicMock()
        self.mock_crypto_verifier.sign_data.return_value = "mock-signature"
        self.mock_crypto_verifier.verify_signature.return_value = True

        # Create a mock IPLD storage
        self.mock_ipld_storage = MagicMock()
        self.mock_ipld_storage.store_json.return_value = "mock-cid"
        self.mock_ipld_storage.load_json.return_value = {"id": "test-record", "record_type": "source"}

        # Create a mock provenance storage
        self.mock_provenance_storage = MagicMock()
        self.mock_provenance_storage.store_json.return_value = "mock-cid"
        self.mock_provenance_storage.record_cids = {}
        self.mock_provenance_storage.load_record.return_value = None

        # Create a mock provenance manager
        self.mock_provenance_manager = MagicMock()
        self.mock_provenance_manager.storage = self.mock_provenance_storage
        self.mock_provenance_manager.crypto_verifier = self.mock_crypto_verifier

        # Create a lineage tracker instance for testing
        self.lineage_tracker = CrossDocumentLineageTracker(
            provenance_storage=self.mock_provenance_storage,
            audit_logger=self.mock_audit_logger,
            crypto_verifier=self.mock_crypto_verifier
        )

        # Create test data
        self.source_record_id = "source-123"
        self.target_record_id = "target-456"

    def tearDown(self):
        """Clean up after tests."""
        # Remove any temporary files
        for file_path in self.temp_files:
            if os.path.exists(file_path):
                os.unlink(file_path)

    def test_create_link(self):
        """Test creating cross-document links."""
        # Create a link
        link_id = self.lineage_tracker.create_link(
            source_record_id=self.source_record_id,
            target_record_id=self.target_record_id,
            link_type=LinkType.DERIVED_FROM,
            confidence=0.95,
            properties={"reason": "semantic similarity"},
            audit_event=True
        )

        # Verify link creation
        self.assertIsNotNone(link_id)
        self.assertTrue(link_id in self.lineage_tracker._link_cache)

        # Verify link properties
        link = self.lineage_tracker._link_cache[link_id]
        self.assertEqual(link.source_record_id, self.source_record_id)
        self.assertEqual(link.target_record_id, self.target_record_id)
        self.assertEqual(link.link_type, "derived_from")  # Converted to string
        self.assertEqual(link.confidence, 0.95)
        self.assertEqual(link.properties.get("reason"), "semantic similarity")

        # Verify crypto signing
        self.mock_crypto_verifier.sign_data.assert_called_once()
        self.assertIsNotNone(link.signature)

        # Verify audit logging
        self.mock_audit_logger.log_event.assert_called_once()
        call_args = self.mock_audit_logger.log_event.call_args[1]
        self.assertEqual(call_args["category"], AuditCategory.PROVENANCE)
        self.assertEqual(call_args["action"], "create_cross_document_link")
        self.assertEqual(call_args["resource_type"], "cross_document_link")

        # Verify storage
        self.mock_provenance_storage.store_json.assert_called_once()

    def test_get_links_for_record(self):
        """Test retrieving links for a record."""
        # Create test links
        link1_id = self.lineage_tracker.create_link(
            source_record_id=self.source_record_id,
            target_record_id=self.target_record_id,
            link_type=LinkType.DERIVED_FROM,
            confidence=0.9
        )

        link2_id = self.lineage_tracker.create_link(
            source_record_id="other-source",
            target_record_id=self.source_record_id,
            link_type=LinkType.CITED_BY,
            confidence=0.8
        )

        link3_id = self.lineage_tracker.create_link(
            source_record_id=self.source_record_id,
            target_record_id="other-target",
            link_type=LinkType.REFERS_TO,
            confidence=0.6  # Below default threshold
        )

        # Get all links for source record
        links = self.lineage_tracker.get_links_for_record(
            record_id=self.source_record_id,
            direction="both"
        )

        # Should find 2 links (link3 is below threshold)
        self.assertEqual(len(links), 2)

        # Get only outgoing links
        outgoing = self.lineage_tracker.get_links_for_record(
            record_id=self.source_record_id,
            direction="outgoing"
        )

        # Should find 1 link (link1)
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0].target_record_id, self.target_record_id)

        # Get only incoming links
        incoming = self.lineage_tracker.get_links_for_record(
            record_id=self.source_record_id,
            direction="incoming"
        )

        # Should find 1 link (link2)
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0].source_record_id, "other-source")

        # Get links with filter by link type
        filtered = self.lineage_tracker.get_links_for_record(
            record_id=self.source_record_id,
            link_types=[LinkType.DERIVED_FROM]
        )

        # Should find 1 link (link1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].link_type, "derived_from")

        # Get links with modified confidence threshold
        all_links = self.lineage_tracker.get_links_for_record(
            record_id=self.source_record_id,
            min_confidence=0.5  # Lower threshold to include link3
        )

        # Should find 3 links now
        self.assertEqual(len(all_links), 3)

    def test_build_lineage_graph(self):
        """Test building a lineage graph."""
        # Create test links
        self.lineage_tracker.create_link(
            source_record_id=self.source_record_id,
            target_record_id=self.target_record_id,
            link_type=LinkType.DERIVED_FROM,
            confidence=0.9
        )

        self.lineage_tracker.create_link(
            source_record_id=self.target_record_id,
            target_record_id="third-record",
            link_type=LinkType.INFLUENCED_BY,
            confidence=0.8
        )

        # Mock get_links_for_record to return actual links from cache
        original_method = self.lineage_tracker.get_links_for_record
        self.lineage_tracker.get_links_for_record = lambda *args, **kwargs: original_method(*args, **kwargs)

        # Build the graph
        graph = self.lineage_tracker.build_lineage_graph(
            record_ids=[self.source_record_id],
            max_depth=2
        )

        # Verify the graph structure
        self.assertIsInstance(graph, nx.DiGraph)
        self.assertEqual(len(graph.nodes), 3)  # All 3 records should be in graph
        self.assertEqual(len(graph.edges), 2)  # Both links should be included

        # Verify the node attributes
        for node in graph.nodes:
            self.assertIn("record_type", graph.nodes[node])

        # Verify the edge attributes
        for u, v, data in graph.edges(data=True):
            self.assertIn("relation", data)
            self.assertIn("cross_document", data)
            if u == self.source_record_id and v == self.target_record_id:
                self.assertEqual(data["relation"], "derived_from")
                self.assertTrue(data["cross_document"])

    @patch("networkx.DiGraph")
    def test_analyze_lineage(self, mock_digraph):
        """Test analyzing lineage."""
        # Set up mock graph
        mock_graph = MagicMock()
        mock_graph.nodes.return_value = [self.source_record_id, self.target_record_id, "third-record"]
        mock_graph.edges.return_value = [(self.source_record_id, self.target_record_id),
                                       (self.target_record_id, "third-record")]
        mock_digraph.return_value = mock_graph

        # Set up mock for edge attributes
        mock_edge_data = {}
        mock_edge_data[(self.source_record_id, self.target_record_id)] = {
            "relation": "derived_from",
            "cross_document": True,
            "confidence": 0.9
        }
        mock_edge_data[(self.target_record_id, "third-record")] = {
            "relation": "influenced_by",
            "cross_document": True,
            "confidence": 0.8
        }
        mock_graph.edges.return_value = mock_edge_data.keys()
        mock_graph.nodes.return_value = {self.source_record_id: {}, self.target_record_id: {}, "third-record": {}}

        def mock_edges_data(data=True):
            return [(u, v, data) for (u, v), data in mock_edge_data.items()]

        mock_graph.edges.data = mock_edges_data

        # Mock the build_lineage_graph method
        original_build = self.lineage_tracker.build_lineage_graph
        self.lineage_tracker.build_lineage_graph = MagicMock(return_value=mock_graph)

        # Analyze lineage
        analysis = self.lineage_tracker.analyze_lineage(
            record_ids=[self.source_record_id],
            max_depth=2
        )

        # Verify analysis result structure
        self.assertIsInstance(analysis, dict)
        self.assertIn("basic_metrics", analysis)

        # Verify basic metrics
        basic_metrics = analysis["basic_metrics"]
        self.assertIn("node_count", basic_metrics)
        self.assertIn("edge_count", basic_metrics)
        self.assertIn("cross_document_edge_count", basic_metrics)
        self.assertIn("cross_document_ratio", basic_metrics)

        # Restore original method
        self.lineage_tracker.build_lineage_graph = original_build

    def test_visualize_lineage(self):
        """Test visualizing lineage."""
        # Mock the build_lineage_graph method to return a simple graph
        mock_graph = nx.DiGraph()
        mock_graph.add_node(self.source_record_id, record_type="source", description="Source Record")
        mock_graph.add_node(self.target_record_id, record_type="target", description="Target Record")
        mock_graph.add_edge(self.source_record_id, self.target_record_id,
                           relation="derived_from", cross_document=True, confidence=0.9)

        original_build = self.lineage_tracker.build_lineage_graph
        self.lineage_tracker.build_lineage_graph = MagicMock(return_value=mock_graph)

        # Test visualization to file
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp_path = tmp.name
            self.temp_files.append(tmp_path)

        # Generate visualization
        result = self.lineage_tracker.visualize_lineage(
            record_ids=[self.source_record_id],
            file_path=tmp_path,
            format="png"
        )

        # Verify result is None when saving to file
        self.assertIsNone(result)

        # Verify file was created
        self.assertTrue(os.path.exists(tmp_path))

        # Test visualization as return value (without file output)
        result = self.lineage_tracker.visualize_lineage(
            record_ids=[self.source_record_id],
            format="json"
        )

        # Verify JSON result
        self.assertIsInstance(result, dict)
        self.assertIn("nodes", result)
        self.assertIn("edges", result)
        self.assertIn("metadata", result)

        # Restore original method
        self.lineage_tracker.build_lineage_graph = original_build

    def test_export_lineage(self):
        """Test exporting lineage."""
        # Mock the build_lineage_graph method to return a simple graph
        mock_graph = nx.DiGraph()
        mock_graph.add_node(self.source_record_id, record_type="source", description="Source Record")
        mock_graph.add_node(self.target_record_id, record_type="target", description="Target Record")
        mock_graph.add_edge(self.source_record_id, self.target_record_id,
                           relation="derived_from", cross_document=True, confidence=0.9)

        original_build = self.lineage_tracker.build_lineage_graph
        self.lineage_tracker.build_lineage_graph = MagicMock(return_value=mock_graph)

        # Test JSON export to file
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
            tmp_path = tmp.name
            self.temp_files.append(tmp_path)

        # Export to file
        result = self.lineage_tracker.export_lineage(
            record_ids=[self.source_record_id],
            file_path=tmp_path,
            format="json"
        )

        # Verify result is None when saving to file
        self.assertIsNone(result)

        # Verify file was created and contains valid JSON
        self.assertTrue(os.path.exists(tmp_path))
        with open(tmp_path, 'r') as f:
            data = json.load(f)
            self.assertIn("nodes", data)
            self.assertIn("edges", data)

        # Test JSON export as return value
        result = self.lineage_tracker.export_lineage(
            record_ids=[self.source_record_id],
            format="json"
        )

        # Verify JSON result
        self.assertIsInstance(result, dict)
        self.assertIn("nodes", result)
        self.assertIn("edges", result)

        # Restore original method
        self.lineage_tracker.build_lineage_graph = original_build

    def test_verify_link(self):
        """Test verifying link signatures."""
        # Create a link with a signature
        link = CrossDocumentLink(
            link_id="test-link",
            source_record_id=self.source_record_id,
            target_record_id=self.target_record_id,
            link_type="derived_from",
            confidence=0.9,
            properties={"reason": "test"},
            signature="test-signature"
        )

        # Verify with valid signature
        self.mock_crypto_verifier.verify_signature.return_value = True
        is_valid = self.lineage_tracker.verify_link(link)
        self.assertTrue(is_valid)

        # Verify with invalid signature
        self.mock_crypto_verifier.verify_signature.return_value = False
        is_valid = self.lineage_tracker.verify_link(link)
        self.assertFalse(is_valid)

        # Test with no crypto verifier
        lineage_tracker = CrossDocumentLineageTracker(
            provenance_storage=self.mock_provenance_storage,
            audit_logger=self.mock_audit_logger,
            crypto_verifier=None
        )
        is_valid = lineage_tracker.verify_link(link)
        self.assertTrue(is_valid)  # Should return True if verification is not possible

    def test_integrate_with_provenance_manager(self):
        """Test integration with provenance manager."""
        # Test integration factory function
        lineage_tracker = integrate_with_provenance_manager(
            provenance_manager=self.mock_provenance_manager,
            audit_logger=self.mock_audit_logger
        )

        # Verify the tracker was created correctly
        self.assertIsInstance(lineage_tracker, CrossDocumentLineageTracker)
        self.assertEqual(lineage_tracker.provenance_storage, self.mock_provenance_storage)
        self.assertEqual(lineage_tracker.audit_logger, self.mock_audit_logger)
        self.assertEqual(lineage_tracker.crypto_verifier, self.mock_crypto_verifier)


class TestCrossDocumentAuditIntegration(unittest.TestCase):
    """Tests for integration between cross-document lineage and audit logging."""

    @unittest.skipIf(not ENHANCED_PROVENANCE_AVAILABLE or not AUDIT_AVAILABLE,
                    "Enhanced provenance or audit modules not available")
    def setUp(self):
        """Set up test environment."""
        self.temp_files = []

        # Create a temporary file for provenance storage
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
            self.storage_path = tmp.name
            self.temp_files.append(self.storage_path)

        # Create a temporary file for audit log
        with tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False) as tmp:
            self.audit_log_path = tmp.name
            self.temp_files.append(self.audit_log_path)

        # Initialize AuditLogger
        self.audit_logger = AuditLogger.get_instance()
        self.audit_logger.configure({
            "default_user": "test-user",
            "min_level": AuditLevel.DEBUG
        })

        # Initialize provenance manager
        self.provenance_manager = EnhancedProvenanceManager(
            storage_path=self.storage_path,
            enable_ipld_storage=False,
            default_agent_id="test-agent",
            tracking_level="detailed",
            enable_crypto_verification=True
        )

        # Create integrator
        self.integrator = AuditProvenanceIntegrator(
            audit_logger=self.audit_logger,
            provenance_manager=self.provenance_manager
        )

        # Initialize lineage tracker
        self.lineage_tracker = integrate_with_provenance_manager(
            provenance_manager=self.provenance_manager,
            audit_logger=self.audit_logger
        )

        # Create test data
        self.source_id = f"test-source-{uuid.uuid4()}"
        self.source_record_id = self.provenance_manager.record_source(
            source_id=self.source_id,
            source_type="dataset",
            source_uri="test-uri",
            format="csv",
            description="Test source record"
        )

        self.target_id = f"test-target-{uuid.uuid4()}"
        self.target_record_id = self.provenance_manager.record_source(
            source_id=self.target_id,
            source_type="dataset",
            source_uri="test-uri-2",
            format="json",
            description="Test target record"
        )

    def tearDown(self):
        """Clean up after tests."""
        # Remove any temporary files
        for file_path in self.temp_files:
            if os.path.exists(file_path):
                os.unlink(file_path)

    def test_integrated_link_creation(self):
        """Test creating a link with integrated audit logging."""
        # Create a cross-document link
        link_id = self.lineage_tracker.create_link(
            source_record_id=self.source_record_id,
            target_record_id=self.target_record_id,
            link_type=LinkType.DERIVED_FROM,
            confidence=0.9,
            properties={"reason": "test integration"},
            audit_event=True
        )

        # Verify link was created
        self.assertIsNotNone(link_id)

        # Retrieve the link
        links = self.lineage_tracker.get_links_for_record(
            record_id=self.source_record_id,
            direction="outgoing"
        )

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].link_id, link_id)

        # Verify audit log contains the event
        events = self.audit_logger.get_recent_events(
            count=10,
            categories=[AuditCategory.PROVENANCE],
            actions=["create_cross_document_link"]
        )

        self.assertGreaterEqual(len(events), 1)

        # Find the specific event for our link
        link_event = None
        for event in events:
            if event.details and "source_record_id" in event.details:
                if event.details["source_record_id"] == self.source_record_id:
                    link_event = event
                    break

        self.assertIsNotNone(link_event)
        self.assertEqual(link_event.resource_id, link_id)
        self.assertEqual(link_event.resource_type, "cross_document_link")

    def test_lineage_analysis_with_audit(self):
        """Test lineage analysis with audit integration."""
        # Create links between records
        link1_id = self.lineage_tracker.create_link(
            source_record_id=self.source_record_id,
            target_record_id=self.target_record_id,
            link_type=LinkType.DERIVED_FROM,
            confidence=0.85
        )

        # Create a third record
        third_id = f"test-third-{uuid.uuid4()}"
        third_record_id = self.provenance_manager.record_source(
            source_id=third_id,
            source_type="dataset",
            source_uri="test-uri-3",
            format="parquet",
            description="Test third record"
        )

        # Link the second to the third
        link2_id = self.lineage_tracker.create_link(
            source_record_id=self.target_record_id,
            target_record_id=third_record_id,
            link_type=LinkType.INFLUENCED_BY,
            confidence=0.9
        )

        # Perform lineage analysis
        analysis = self.lineage_tracker.analyze_lineage(
            record_ids=[self.source_record_id],
            max_depth=3
        )

        # Verify analysis contains expected data
        self.assertIn("basic_metrics", analysis)
        basic_metrics = analysis["basic_metrics"]
        self.assertGreaterEqual(basic_metrics["node_count"], 3)  # At least our 3 records
        self.assertGreaterEqual(basic_metrics["edge_count"], 2)  # At least our 2 links

        # Create a temporary file for visualization
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as tmp:
            viz_path = tmp.name
            self.temp_files.append(viz_path)

        # Generate visualization
        self.lineage_tracker.visualize_lineage(
            record_ids=[self.source_record_id],
            max_depth=3,
            file_path=viz_path,
            format="html"
        )

        self.assertTrue(os.path.exists(viz_path))

        # Export lineage to JSON
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
            export_path = tmp.name
            self.temp_files.append(export_path)

        self.lineage_tracker.export_lineage(
            record_ids=[self.source_record_id],
            max_depth=3,
            file_path=export_path,
            format="json",
            include_records=True
        )

        self.assertTrue(os.path.exists(export_path))

        # Check if exported JSON is valid
        with open(export_path, 'r') as f:
            export_data = json.load(f)
            self.assertIn("nodes", export_data)
            self.assertIn("edges", export_data)
            self.assertGreaterEqual(len(export_data["nodes"]), 3)
            self.assertGreaterEqual(len(export_data["edges"]), 2)

    def test_link_verification(self):
        """Test link verification with cryptographic signatures."""
        # Get the crypto verifier from the provenance manager
        crypto_verifier = self.provenance_manager.crypto_verifier

        # Create a link with signing
        link_id = self.lineage_tracker.create_link(
            source_record_id=self.source_record_id,
            target_record_id=self.target_record_id,
            link_type=LinkType.SEMANTICALLY_SIMILAR,
            confidence=0.92,
            properties={"verified": True}
        )

        # Retrieve the link
        links = self.lineage_tracker.get_links_for_record(
            record_id=self.source_record_id
        )
        self.assertEqual(len(links), 1)
        link = links[0]

        # Verify the signature
        is_valid = self.lineage_tracker.verify_link(link)
        self.assertTrue(is_valid)

        # Create a tampered link
        tampered_link = CrossDocumentLink(
            link_id=link.link_id,
            source_record_id=link.source_record_id,
            target_record_id=link.target_record_id,
            link_type=link.link_type,
            confidence=0.5,  # Changed from 0.92
            properties=link.properties,
            timestamp=link.timestamp,
            signature=link.signature  # Keep original signature
        )

        # Verify the tampered link - should fail if cryptographic verification is working
        if crypto_verifier and hasattr(crypto_verifier, 'verify_signature'):
            # Only test if we have a real crypto verifier
            is_valid = self.lineage_tracker.verify_link(tampered_link)
            self.assertFalse(is_valid)

    def test_cross_document_insights(self):
        """Test generating insights from cross-document lineage."""
        # Create a more complex lineage structure for better insights

        # Create several more records
        record_ids = []
        for i in range(5):
            record_id = f"test-record-{i}-{uuid.uuid4()}"
            source_record_id = self.provenance_manager.record_source(
                source_id=record_id,
                source_type="dataset",
                source_uri=f"test-uri-{i}",
                format="csv",
                description=f"Test record {i}"
            )
            record_ids.append(source_record_id)

        # Create links between records
        for i in range(len(record_ids) - 1):
            link_type = LinkType.DERIVED_FROM if i % 2 == 0 else LinkType.INFLUENCED_BY
            self.lineage_tracker.create_link(
                source_record_id=record_ids[i],
                target_record_id=record_ids[i + 1],
                link_type=link_type,
                confidence=0.8 + (i * 0.02)
            )

        # Create a few cross-links
        self.lineage_tracker.create_link(
            source_record_id=record_ids[0],
            target_record_id=record_ids[2],
            link_type=LinkType.REFERS_TO,
            confidence=0.75
        )

        self.lineage_tracker.create_link(
            source_record_id=record_ids[1],
            target_record_id=record_ids[3],
            link_type=LinkType.CITED_BY,
            confidence=0.82
        )

        # Perform analysis with insights
        analysis = self.lineage_tracker.analyze_lineage(
            record_ids=[record_ids[0]],
            max_depth=4
        )

        # Verify insights are generated
        self.assertIn("insights", analysis)
        self.assertIsInstance(analysis["insights"], list)
        self.assertGreater(len(analysis["insights"]), 0)

        # Check structure of insights
        for insight in analysis["insights"]:
            self.assertIn("type", insight)
            self.assertIn("level", insight)
            self.assertIn("message", insight)


if __name__ == '__main__':
    unittest.main()
