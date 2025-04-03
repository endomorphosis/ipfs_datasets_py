"""
Tests for the integrated audit logging and data provenance functionality.

This module tests the integration between audit logging and data provenance systems,
focusing on bidirectional tracing, cross-referencing, and consolidated compliance reporting.
"""

import os
import json
import unittest
import datetime
from unittest.mock import MagicMock, patch
import networkx as nx

# Try to import the required modules, using mock objects if imports fail
try:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditLogger, AuditEvent, AuditCategory, AuditLevel
    )
    from ipfs_datasets_py.audit.compliance import (
        ComplianceStandard, ComplianceRequirement, ComplianceReport, ComplianceReporter
    )
    from ipfs_datasets_py.audit.integration import (
        AuditProvenanceIntegrator, IntegratedComplianceReporter,
        ProvenanceAuditSearchIntegrator, generate_integrated_compliance_report
    )
    
    # Import provenance-related classes if available
    try:
        from ipfs_datasets_py.data_provenance_enhanced import (
            EnhancedProvenanceManager, ProvenanceContext, IPLDProvenanceStorage,
            SourceRecord, TransformationRecord, VerificationRecord
        )
        PROVENANCE_AVAILABLE = True
    except ImportError:
        PROVENANCE_AVAILABLE = False
        
    # Create mock classes for missing dependencies
    if not PROVENANCE_AVAILABLE:
        class EnhancedProvenanceManager:
            def __init__(self):
                self.storage = MagicMock()
                
            def query_records(self, **kwargs):
                return []
                
            def record_source(self, **kwargs):
                return "mock-source-record-id"
                
            def record_transformation(self, **kwargs):
                return "mock-transformation-record-id"
                
            def record_verification(self, **kwargs):
                return "mock-verification-record-id"
                
            def add_metadata_to_record(self, **kwargs):
                pass
        
        class IPLDProvenanceStorage:
            def build_cross_document_lineage_graph(self, **kwargs):
                # Return a simple mock graph
                G = nx.DiGraph()
                G.add_node("record1", record_type="source")
                G.add_node("record2", record_type="transformation")
                G.add_edge("record1", "record2")
                return G
                
            def analyze_cross_document_lineage(self, graph=None, **kwargs):
                return {
                    "node_count": 2,
                    "edge_count": 1,
                    "document_count": 1,
                    "critical_paths_count": 1,
                    "hub_records": ["record1"],
                    "cross_document_connections": 1,
                    "metrics": {
                        "centrality": {"record1": 0.8},
                        "connectivity": 1.0
                    }
                }
        
        class SourceRecord:
            def __init__(self, record_id="source1", source_id="src1", source_type="dataset", 
                        source_uri="", timestamp=None, metadata=None):
                self.record_id = record_id
                self.source_id = source_id
                self.source_type = source_type
                self.source_uri = source_uri
                self.timestamp = timestamp or datetime.datetime.now().isoformat()
                self.metadata = metadata or {}
                self.record_type = "source"
        
        class TransformationRecord:
            def __init__(self, record_id="transform1", input_ids=None, output_id="out1", 
                        transformation_type="process", timestamp=None, metadata=None):
                self.record_id = record_id
                self.input_ids = input_ids or ["src1"]
                self.output_id = output_id
                self.transformation_type = transformation_type
                self.timestamp = timestamp or datetime.datetime.now().isoformat()
                self.metadata = metadata or {}
                self.record_type = "transformation"
        
        class VerificationRecord:
            def __init__(self, record_id="verify1", data_id="data1", verification_type="checksum", 
                        result=None, timestamp=None, metadata=None):
                self.record_id = record_id
                self.data_id = data_id
                self.verification_type = verification_type
                self.result = result or {"verified": True}
                self.timestamp = timestamp or datetime.datetime.now().isoformat()
                self.metadata = metadata or {}
                self.record_type = "verification"
                
        class ProvenanceContext:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)
    
    MODULES_AVAILABLE = True
    
except ImportError:
    MODULES_AVAILABLE = False


@unittest.skipIf(not MODULES_AVAILABLE, "Required modules not available")
class TestAuditProvenanceIntegration(unittest.TestCase):
    """Test the integration between audit logging and data provenance systems."""
    
    def setUp(self):
        """Set up test environment."""
        # Create mock audit logger and provenance manager
        self.audit_logger = MagicMock()
        self.provenance_manager = MagicMock()
        
        # Create integrator instance
        self.integrator = AuditProvenanceIntegrator(
            audit_logger=self.audit_logger,
            provenance_manager=self.provenance_manager
        )
        
        # Set up mock behaviors
        self.audit_logger.log.return_value = "test-event-id"
        
        self.provenance_manager.record_source.return_value = "test-source-record-id"
        self.provenance_manager.record_transformation.return_value = "test-transform-record-id"
        self.provenance_manager.record_verification.return_value = "test-verify-record-id"
    
    def test_audit_from_provenance_source_record(self):
        """Test generating audit event from a source provenance record."""
        # Create a test source record
        source_record = SourceRecord(
            record_id="test-source-1",
            source_id="dataset-123",
            source_type="dataset",
            source_uri="ipfs://bafy..."
        )
        
        # Generate audit event from provenance record
        event_id = self.integrator.audit_from_provenance_record(source_record)
        
        # Verify audit event was created
        self.assertEqual(event_id, "test-event-id")
        self.audit_logger.log.assert_called_once()
        
        # Verify correct parameters were passed
        args, kwargs = self.audit_logger.log.call_args
        self.assertEqual(kwargs["category"], AuditCategory.PROVENANCE)
        self.assertEqual(kwargs["action"], "data_source_access")
        self.assertEqual(kwargs["resource_id"], "dataset-123")
        self.assertEqual(kwargs["resource_type"], "data_source")
        self.assertIn("provenance_record_id", kwargs["details"])
        self.assertEqual(kwargs["details"]["provenance_record_id"], "test-source-1")
    
    def test_audit_from_provenance_transformation_record(self):
        """Test generating audit event from a transformation provenance record."""
        # Create a test transformation record
        transform_record = TransformationRecord(
            record_id="test-transform-1",
            input_ids=["dataset-123", "dataset-456"],
            output_id="processed-789",
            transformation_type="normalize"
        )
        
        # Generate audit event from provenance record
        event_id = self.integrator.audit_from_provenance_record(transform_record)
        
        # Verify audit event was created
        self.assertEqual(event_id, "test-event-id")
        self.audit_logger.log.assert_called_once()
        
        # Verify correct parameters were passed
        args, kwargs = self.audit_logger.log.call_args
        self.assertEqual(kwargs["category"], AuditCategory.PROVENANCE)
        self.assertEqual(kwargs["action"], "data_transformation")
        self.assertEqual(kwargs["resource_id"], "processed-789")
        self.assertEqual(kwargs["resource_type"], "transformed_data")
        self.assertIn("input_ids", kwargs["details"])
        self.assertEqual(kwargs["details"]["input_ids"], ["dataset-123", "dataset-456"])
        self.assertEqual(kwargs["details"]["transformation_type"], "normalize")
    
    def test_provenance_from_audit_event_data_access(self):
        """Test generating provenance record from a data access audit event."""
        # Create a test audit event
        event = AuditEvent(
            event_id="test-audit-1",
            timestamp=datetime.datetime.now().isoformat(),
            level=AuditLevel.INFO,
            category=AuditCategory.DATA_ACCESS,
            action="read",
            user="test-user",
            resource_id="dataset-123",
            resource_type="dataset",
            details={"uri": "ipfs://bafy..."}
        )
        
        # Generate provenance record from audit event
        record_id = self.integrator.provenance_from_audit_event(event)
        
        # Verify provenance record was created
        self.assertEqual(record_id, "test-source-record-id")
        self.provenance_manager.record_source.assert_called_once()
        
        # Verify correct parameters were passed
        args, kwargs = self.provenance_manager.record_source.call_args
        self.assertEqual(kwargs["source_id"], "dataset-123")
        self.assertEqual(kwargs["source_type"], "dataset")
        self.assertEqual(kwargs["source_uri"], "ipfs://bafy...")
        self.assertIn("audit_event_id", kwargs["metadata"])
        self.assertEqual(kwargs["metadata"]["audit_event_id"], "test-audit-1")
    
    def test_provenance_from_audit_event_data_modification(self):
        """Test generating provenance record from a data modification audit event."""
        # Create a test audit event
        event = AuditEvent(
            event_id="test-audit-2",
            timestamp=datetime.datetime.now().isoformat(),
            level=AuditLevel.INFO,
            category=AuditCategory.DATA_MODIFICATION,
            action="transform",
            user="test-user",
            resource_id="processed-789",
            resource_type="dataset",
            details={
                "input_ids": ["dataset-123", "dataset-456"],
                "transformation_type": "normalize",
                "parameters": {"option1": "value1"}
            }
        )
        
        # Generate provenance record from audit event
        record_id = self.integrator.provenance_from_audit_event(event)
        
        # Verify provenance record was created
        self.assertEqual(record_id, "test-transform-record-id")
        self.provenance_manager.record_transformation.assert_called_once()
        
        # Verify correct parameters were passed
        args, kwargs = self.provenance_manager.record_transformation.call_args
        self.assertEqual(kwargs["input_ids"], ["dataset-123", "dataset-456"])
        self.assertEqual(kwargs["output_id"], "processed-789")
        self.assertEqual(kwargs["transformation_type"], "normalize")
        self.assertEqual(kwargs["parameters"], {"option1": "value1"})
        self.assertIn("audit_event_id", kwargs["metadata"])
        self.assertEqual(kwargs["metadata"]["audit_event_id"], "test-audit-2")
    
    def test_link_audit_to_provenance(self):
        """Test linking an audit event to a provenance record."""
        # Link audit event to provenance record
        result = self.integrator.link_audit_to_provenance(
            audit_event_id="test-audit-3", 
            provenance_record_id="test-record-3"
        )
        
        # Verify link was created
        self.assertTrue(result)
        self.provenance_manager.add_metadata_to_record.assert_called_once()
        
        # Verify correct parameters were passed
        args, kwargs = self.provenance_manager.add_metadata_to_record.call_args
        self.assertEqual(kwargs["record_id"], "test-record-3")
        self.assertEqual(kwargs["metadata"], {"linked_audit_event_id": "test-audit-3"})
        
        # Verify audit event was logged
        self.audit_logger.log.assert_called_once()
        args, kwargs = self.audit_logger.log.call_args
        self.assertEqual(kwargs["category"], AuditCategory.PROVENANCE)
        self.assertEqual(kwargs["action"], "link_audit_provenance")
        self.assertEqual(kwargs["details"]["audit_event_id"], "test-audit-3")
        self.assertEqual(kwargs["details"]["provenance_record_id"], "test-record-3")
    
    def test_setup_audit_event_listener(self):
        """Test setting up an audit event listener for automatic provenance creation."""
        # Mock the add_event_listener method
        self.audit_logger.add_event_listener = MagicMock()
        
        # Set up the event listener
        result = self.integrator.setup_audit_event_listener()
        
        # Verify listener was set up
        self.assertTrue(result)
        
        # Verify add_event_listener was called for each relevant category
        expected_categories = [AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION, 
                             AuditCategory.COMPLIANCE]
        self.assertEqual(self.audit_logger.add_event_listener.call_count, 3)
        
        for i, call_args in enumerate(self.audit_logger.add_event_listener.call_args_list):
            args, kwargs = call_args
            self.assertEqual(args[1], expected_categories[i])


@unittest.skipIf(not MODULES_AVAILABLE, "Required modules not available")
class TestIntegratedComplianceReporting(unittest.TestCase):
    """Test the integrated compliance reporting functionality."""
    
    def setUp(self):
        """Set up test environment."""
        # Create mock storage for the provenance manager
        self.mock_storage = IPLDProvenanceStorage()
        
        # Create mock audit logger and provenance manager
        self.audit_logger = MagicMock()
        
        self.provenance_manager = MagicMock()
        self.provenance_manager.storage = self.mock_storage
        self.provenance_manager.query_records.return_value = [
            SourceRecord(record_id="record1"),
            TransformationRecord(record_id="record2", input_ids=["record1"])
        ]
        
        # Create test integrated compliance reporter
        self.reporter = IntegratedComplianceReporter(
            standard=ComplianceStandard.GDPR,
            audit_logger=self.audit_logger,
            provenance_manager=self.provenance_manager
        )
        
        # Add some test compliance requirements
        self.reporter.add_requirement(ComplianceRequirement(
            id="GDPR-Test1",
            standard=ComplianceStandard.GDPR,
            description="Test GDPR requirement 1",
            audit_categories=[AuditCategory.DATA_ACCESS],
            actions=["read", "query"]
        ))
        
        self.reporter.add_requirement(ComplianceRequirement(
            id="GDPR-Test2",
            standard=ComplianceStandard.GDPR,
            description="Test GDPR requirement 2",
            audit_categories=[AuditCategory.PROVENANCE],
            actions=["data_source_access"]
        ))
        
        # Mock get_audit_events to return test events
        self.reporter.get_audit_events = MagicMock(return_value=[
            AuditEvent(
                event_id="audit-1",
                timestamp=datetime.datetime.now().isoformat(),
                level=AuditLevel.INFO,
                category=AuditCategory.DATA_ACCESS,
                action="read",
                resource_id="dataset-123"
            )
        ])
    
    def test_generate_report_with_cross_document_analysis(self):
        """Test generating a compliance report with cross-document lineage analysis."""
        # Generate a report
        report = self.reporter.generate_report(
            start_time=(datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(),
            end_time=datetime.datetime.now().isoformat(),
            include_cross_document_analysis=True
        )
        
        # Verify report was generated with correct standard
        self.assertEqual(report.standard, ComplianceStandard.GDPR)
        
        # Verify requirements were processed
        self.assertEqual(len(report.requirements), 2)
        
        # Verify provenance data was added
        self.assertIn("provenance_record_count", report.details)
        self.assertEqual(report.details["provenance_record_count"], 2)
        
        # Verify cross-document lineage analysis was performed
        self.assertIn("cross_document_lineage", report.details)
        self.assertIn("graph_node_count", report.details["cross_document_lineage"])
        self.assertIn("metrics", report.details["cross_document_lineage"])
        
        # Verify compliance insights were added
        self.assertIn("provenance_insights", report.details)
    
    def test_generate_report_without_cross_document_analysis(self):
        """Test generating a compliance report without cross-document lineage analysis."""
        # Generate a report without cross-document analysis
        report = self.reporter.generate_report(
            include_cross_document_analysis=False
        )
        
        # Verify report was generated
        self.assertEqual(report.standard, ComplianceStandard.GDPR)
        
        # Verify provenance data was added
        self.assertIn("provenance_record_count", report.details)
        
        # Verify cross-document lineage analysis was not performed
        self.assertNotIn("cross_document_lineage", report.details)
    
    def test_generate_integrated_compliance_report_function(self):
        """Test the generate_integrated_compliance_report helper function."""
        # Mock functions used by generate_integrated_compliance_report
        orig_gdpr_reporter = __import__('ipfs_datasets_py.audit.compliance').audit.compliance.GDPRComplianceReporter
        
        try:
            # Replace GDPRComplianceReporter with a mock
            mock_gdpr_reporter = MagicMock()
            mock_gdpr_reporter.return_value.requirements = [
                ComplianceRequirement(
                    id="GDPR-Art30",
                    standard=ComplianceStandard.GDPR,
                    description="Records of processing activities",
                    audit_categories=[AuditCategory.DATA_ACCESS],
                    actions=["read"]
                )
            ]
            __import__('ipfs_datasets_py.audit.compliance').audit.compliance.GDPRComplianceReporter = mock_gdpr_reporter
            
            # Generate a report in JSON format
            result = generate_integrated_compliance_report(
                standard_name="GDPR",
                output_format="json"
            )
            
            # Verify result is JSON string
            self.assertIsInstance(result, str)
            
            # Verify it can be parsed as JSON
            parsed = json.loads(result)
            self.assertIn("standard", parsed)
            self.assertEqual(parsed["standard"], "GDPR")
            
        finally:
            # Restore original class
            __import__('ipfs_datasets_py.audit.compliance').audit.compliance.GDPRComplianceReporter = orig_gdpr_reporter


@unittest.skipIf(not MODULES_AVAILABLE, "Required modules not available")
class TestProvenanceAuditSearch(unittest.TestCase):
    """Test the integrated search functionality across audit logs and provenance records."""
    
    def setUp(self):
        """Set up test environment."""
        # Create mock audit logger and provenance manager
        self.audit_logger = MagicMock()
        self.provenance_manager = MagicMock()
        
        # Create search integrator
        self.search = ProvenanceAuditSearchIntegrator(
            audit_logger=self.audit_logger,
            provenance_manager=self.provenance_manager
        )
        
        # Mock search methods
        self.search._search_audit_logs = MagicMock(return_value=[
            {"event_id": "audit-1", "timestamp": datetime.datetime.now().isoformat(), 
             "category": "DATA_ACCESS", "action": "read", "resource_id": "dataset-123",
             "details": {"provenance_record_id": "prov-1"}},
            {"event_id": "audit-2", "timestamp": datetime.datetime.now().isoformat(), 
             "category": "DATA_MODIFICATION", "action": "transform", "resource_id": "dataset-456"}
        ])
        
        self.search._search_provenance_records = MagicMock(return_value=[
            {"record_id": "prov-1", "timestamp": datetime.datetime.now().isoformat(), 
             "record_type": "source", "source_id": "dataset-123", 
             "metadata": {"audit_event_id": "audit-1"}},
            {"record_id": "prov-2", "timestamp": datetime.datetime.now().isoformat(), 
             "record_type": "transformation", "input_ids": ["dataset-123"], "output_id": "dataset-456"}
        ])
    
    def test_search_with_correlation(self):
        """Test search with correlation between audit and provenance records."""
        # Perform a search
        query = {
            "timerange": {
                "start": (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat(),
                "end": datetime.datetime.now().isoformat()
            },
            "resource_type": "dataset"
        }
        
        results = self.search.search(
            query=query,
            include_audit=True,
            include_provenance=True,
            correlation_mode="auto"
        )
        
        # Verify search was performed
        self.search._search_audit_logs.assert_called_once_with(query)
        self.search._search_provenance_records.assert_called_once_with(query)
        
        # Verify results contain both audit and provenance data
        self.assertIn("audit_events", results)
        self.assertEqual(len(results["audit_events"]), 2)
        self.assertIn("provenance_records", results)
        self.assertEqual(len(results["provenance_records"]), 2)
        
        # Verify correlations were created
        self.assertIn("correlations", results)
        self.assertGreater(len(results["correlations"]), 0)
        
        # Verify explicit correlation exists
        explicit_correlations = [c for c in results["correlations"] if c["type"] == "explicit"]
        self.assertGreaterEqual(len(explicit_correlations), 1)
        
        # In auto mode, verify implicit correlations might exist
        if "implicit" in [c["type"] for c in results["correlations"]]:
            implicit_correlations = [c for c in results["correlations"] if c["type"] == "implicit"]
            self.assertGreaterEqual(len(implicit_correlations), 1)
    
    def test_search_audit_only(self):
        """Test search with only audit events."""
        # Perform a search with only audit events
        results = self.search.search(
            query={},
            include_audit=True,
            include_provenance=False
        )
        
        # Verify only audit search was performed
        self.search._search_audit_logs.assert_called_once()
        self.search._search_provenance_records.assert_not_called()
        
        # Verify results contain only audit data
        self.assertIn("audit_events", results)
        self.assertEqual(len(results["audit_events"]), 2)
        self.assertEqual(len(results["provenance_records"]), 0)
        self.assertEqual(len(results["correlations"]), 0)
    
    def test_search_provenance_only(self):
        """Test search with only provenance records."""
        # Perform a search with only provenance records
        results = self.search.search(
            query={},
            include_audit=False,
            include_provenance=True
        )
        
        # Verify only provenance search was performed
        self.search._search_audit_logs.assert_not_called()
        self.search._search_provenance_records.assert_called_once()
        
        # Verify results contain only provenance data
        self.assertEqual(len(results["audit_events"]), 0)
        self.assertIn("provenance_records", results)
        self.assertEqual(len(results["provenance_records"]), 2)
        self.assertEqual(len(results["correlations"]), 0)
    
    def test_search_without_correlation(self):
        """Test search without correlation."""
        # Perform a search without correlation
        results = self.search.search(
            query={},
            include_audit=True,
            include_provenance=True,
            correlation_mode="none"
        )
        
        # Verify both searches were performed
        self.search._search_audit_logs.assert_called_once()
        self.search._search_provenance_records.assert_called_once()
        
        # Verify results contain both data types but no correlations
        self.assertIn("audit_events", results)
        self.assertEqual(len(results["audit_events"]), 2)
        self.assertIn("provenance_records", results)
        self.assertEqual(len(results["provenance_records"]), 2)
        self.assertEqual(len(results["correlations"]), 0)


if __name__ == '__main__':
    unittest.main()