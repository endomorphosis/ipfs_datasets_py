"""
Tests for the Data Provenance Tracking module.

This module contains comprehensive tests for the data provenance tracking system,
ensuring that data lineage is properly recorded and reported.
"""

import os
import json
import tempfile
import unittest
import time
from datetime import datetime
from unittest.mock import patch, MagicMock
import networkx as nx

from ipfs_datasets_py.data_provenance import (
    ProvenanceManager, ProvenanceContext, ProvenanceRecordType,
    SourceRecord, TransformationRecord, MergeRecord,
    QueryRecord, ResultRecord
)


class TestProvenanceRecords(unittest.TestCase):
    """Tests for the various provenance record types."""

    def test_source_record(self):
        """Test SourceRecord creation and serialization."""
        record = SourceRecord(
            id="src001",
            record_type=ProvenanceRecordType.SOURCE,
            description="Test source data",
            source_type="file",
            location="/path/to/data.csv",
            format="csv",
            size=1024,
            hash="sha256:abc123"
        )

        # Test basic attributes
        self.assertEqual(record.id, "src001")
        self.assertEqual(record.record_type, ProvenanceRecordType.SOURCE)
        self.assertEqual(record.description, "Test source data")
        self.assertEqual(record.source_type, "file")
        self.assertEqual(record.location, "/path/to/data.csv")
        self.assertEqual(record.format, "csv")
        self.assertEqual(record.size, 1024)
        self.assertEqual(record.hash, "sha256:abc123")

        # Test serialization/deserialization
        record_dict = record.to_dict()
        self.assertEqual(record_dict["id"], "src001")
        self.assertEqual(record_dict["record_type"], "source")

        # Test round-trip
        new_record = SourceRecord.from_dict(record_dict)
        self.assertEqual(new_record.id, record.id)
        self.assertEqual(new_record.record_type, record.record_type)

    def test_transformation_record(self):
        """Test TransformationRecord creation and serialization."""
        record = TransformationRecord(
            id="transform001",
            record_type=ProvenanceRecordType.TRANSFORMATION,
            description="Data transformation",
            transformation_type="preprocessing",
            tool="pandas",
            version="1.5.3",
            parameters={"dropna": True, "normalize": True},
            input_ids=["src001"],
            output_ids=["transformed001"],
            execution_time=2.5,
            success=True
        )

        # Test basic attributes
        self.assertEqual(record.id, "transform001")
        self.assertEqual(record.record_type, ProvenanceRecordType.TRANSFORMATION)
        self.assertEqual(record.transformation_type, "preprocessing")
        self.assertEqual(record.tool, "pandas")
        self.assertEqual(record.version, "1.5.3")
        self.assertEqual(record.parameters["dropna"], True)
        self.assertEqual(record.execution_time, 2.5)
        self.assertEqual(record.success, True)

        # Test serialization/deserialization
        record_dict = record.to_dict()
        self.assertEqual(record_dict["id"], "transform001")
        self.assertEqual(record_dict["record_type"], "transformation")

        # Test round-trip
        new_record = TransformationRecord.from_dict(record_dict)
        self.assertEqual(new_record.id, record.id)
        self.assertEqual(new_record.record_type, record.record_type)
        self.assertEqual(new_record.transformation_type, record.transformation_type)

    def test_merge_record(self):
        """Test MergeRecord creation and serialization."""
        record = MergeRecord(
            id="merge001",
            record_type=ProvenanceRecordType.MERGE,
            description="Data merge",
            merge_type="join",
            merge_keys=["id"],
            merge_strategy="left",
            input_ids=["src001", "src002"],
            output_ids=["merged001"]
        )

        # Test basic attributes
        self.assertEqual(record.id, "merge001")
        self.assertEqual(record.record_type, ProvenanceRecordType.MERGE)
        self.assertEqual(record.merge_type, "join")
        self.assertEqual(record.merge_keys, ["id"])
        self.assertEqual(record.merge_strategy, "left")

        # Test serialization/deserialization
        record_dict = record.to_dict()
        self.assertEqual(record_dict["id"], "merge001")
        self.assertEqual(record_dict["record_type"], "merge")

        # Test round-trip
        new_record = MergeRecord.from_dict(record_dict)
        self.assertEqual(new_record.id, record.id)
        self.assertEqual(new_record.record_type, record.record_type)
        self.assertEqual(new_record.merge_type, record.merge_type)

    def test_query_record(self):
        """Test QueryRecord creation and serialization."""
        record = QueryRecord(
            id="query001",
            record_type=ProvenanceRecordType.QUERY,
            description="Data query",
            query_type="sql",
            query_text="SELECT * FROM data WHERE value > 10",
            query_parameters={"threshold": 10},
            input_ids=["src001"],
            execution_time=0.5,
            result_count=100
        )

        # Test basic attributes
        self.assertEqual(record.id, "query001")
        self.assertEqual(record.record_type, ProvenanceRecordType.QUERY)
        self.assertEqual(record.query_type, "sql")
        self.assertEqual(record.query_text, "SELECT * FROM data WHERE value > 10")
        self.assertEqual(record.query_parameters["threshold"], 10)
        self.assertEqual(record.execution_time, 0.5)
        self.assertEqual(record.result_count, 100)

        # Test serialization/deserialization
        record_dict = record.to_dict()
        self.assertEqual(record_dict["id"], "query001")
        self.assertEqual(record_dict["record_type"], "query")

        # Test round-trip
        new_record = QueryRecord.from_dict(record_dict)
        self.assertEqual(new_record.id, record.id)
        self.assertEqual(new_record.record_type, record.record_type)
        self.assertEqual(new_record.query_type, record.query_type)

    def test_result_record(self):
        """Test ResultRecord creation and serialization."""
        record = ResultRecord(
            id="result001",
            record_type=ProvenanceRecordType.RESULT,
            description="Query result",
            result_type="data_frame",
            size=1024,
            record_count=100,
            fields=["id", "name", "value"],
            sample="id,name,value\n1,a,10\n2,b,20",
            input_ids=["query001"],
            output_ids=["result001"]
        )

        # Test basic attributes
        self.assertEqual(record.id, "result001")
        self.assertEqual(record.record_type, ProvenanceRecordType.RESULT)
        self.assertEqual(record.result_type, "data_frame")
        self.assertEqual(record.size, 1024)
        self.assertEqual(record.record_count, 100)
        self.assertEqual(record.fields, ["id", "name", "value"])
        self.assertIn("id,name,value", record.sample)

        # Test serialization/deserialization
        record_dict = record.to_dict()
        self.assertEqual(record_dict["id"], "result001")
        self.assertEqual(record_dict["record_type"], "result")

        # Test round-trip
        new_record = ResultRecord.from_dict(record_dict)
        self.assertEqual(new_record.id, record.id)
        self.assertEqual(new_record.record_type, record.record_type)
        self.assertEqual(new_record.result_type, record.result_type)


class TestProvenanceManager(unittest.TestCase):
    """Tests for the ProvenanceManager class."""

    def setUp(self):
        """Set up the test environment."""
        self.provenance_manager = ProvenanceManager(
            storage_path=None,  # In-memory only
            enable_ipld_storage=False,
            default_agent_id="test_agent",
            tracking_level="detailed"
        )

    def test_record_source(self):
        """Test recording a data source."""
        source_id = self.provenance_manager.record_source(
            data_id="data001",
            source_type="file",
            location="/path/to/data.csv",
            format="csv",
            description="Test data source",
            size=1024,
            hash="sha256:abc123"
        )

        # Verify record was created
        self.assertIn(source_id, self.provenance_manager.records)
        record = self.provenance_manager.records[source_id]
        self.assertEqual(record.record_type, ProvenanceRecordType.SOURCE)
        self.assertEqual(record.source_type, "file")
        self.assertEqual(record.location, "/path/to/data.csv")

        # Verify graph node was created
        self.assertTrue(self.provenance_manager.graph.has_node(source_id))
        node_attrs = self.provenance_manager.graph.nodes[source_id]
        self.assertEqual(node_attrs["record_type"], "source")

        # Verify entity's latest record was updated
        self.assertEqual(self.provenance_manager.entity_latest_record["data001"], source_id)

    def test_transformation_flow(self):
        """Test the complete transformation flow."""
        # Record source
        source_id = self.provenance_manager.record_source(
            data_id="raw_data_001",
            source_type="file",
            location="/path/to/data.csv",
            format="csv",
            description="Raw data file"
        )

        # Begin transformation
        transform_id = self.provenance_manager.begin_transformation(
            description="Clean data",
            transformation_type="preprocessing",
            tool="pandas",
            version="1.5.3",
            input_ids=["raw_data_001"],
            parameters={"dropna": True}
        )

        # End transformation
        self.provenance_manager.end_transformation(
            transformation_id=transform_id,
            output_ids=["clean_data_001"],
            success=True
        )

        # Verify transformation record
        self.assertIn(transform_id, self.provenance_manager.records)
        record = self.provenance_manager.records[transform_id]
        self.assertEqual(record.record_type, ProvenanceRecordType.TRANSFORMATION)
        self.assertEqual(record.input_ids, ["raw_data_001"])
        self.assertEqual(record.output_ids, ["clean_data_001"])
        self.assertEqual(record.success, True)
        self.assertIsNotNone(record.execution_time)

        # Verify graph connections
        self.assertTrue(self.provenance_manager.graph.has_edge(source_id, transform_id))

        # Verify entity's latest record was updated
        self.assertEqual(self.provenance_manager.entity_latest_record["clean_data_001"], transform_id)

    def test_provenance_context(self):
        """Test the ProvenanceContext context manager."""
        # Record source
        source_id = self.provenance_manager.record_source(
            data_id="raw_data_001",
            source_type="file",
            location="/path/to/data.csv",
            format="csv",
            description="Raw data file"
        )

        # Use context manager for transformation
        with ProvenanceContext(
            provenance_manager=self.provenance_manager,
            description="Clean data with context",
            transformation_type="preprocessing",
            tool="pandas",
            version="1.5.3",
            input_ids=["raw_data_001"],
            parameters={"dropna": True}
        ) as context:
            # Simulate processing (just wait a bit)
            time.sleep(0.1)

            # Set output IDs
            context.set_output_ids(["clean_data_002"])

        # Verify transformation was recorded
        self.assertIsNotNone(context.transformation_id)
        self.assertIn(context.transformation_id, self.provenance_manager.records)

        record = self.provenance_manager.records[context.transformation_id]
        self.assertEqual(record.record_type, ProvenanceRecordType.TRANSFORMATION)
        self.assertEqual(record.input_ids, ["raw_data_001"])
        self.assertEqual(record.output_ids, ["clean_data_002"])
        self.assertEqual(record.success, True)
        self.assertIsNotNone(record.execution_time)

        # Verify error handling
        try:
            with ProvenanceContext(
                provenance_manager=self.provenance_manager,
                description="Failing transformation",
                transformation_type="preprocessing",
                input_ids=["raw_data_001"]
            ) as context:
                # Raise an exception
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify transformation failure was recorded
        self.assertIsNotNone(context.transformation_id)
        record = self.provenance_manager.records[context.transformation_id]
        self.assertEqual(record.success, False)
        self.assertEqual(record.error_message, "Test error")

    def test_query_flow(self):
        """Test the complete query flow."""
        # Record source
        source_id = self.provenance_manager.record_source(
            data_id="query_data_001",
            source_type="database",
            location="postgresql://host/db",
            format="table",
            description="Database table"
        )

        # Record query
        query_id = self.provenance_manager.record_query(
            input_ids=["query_data_001"],
            query_type="sql",
            query_text="SELECT * FROM data WHERE value > 10",
            description="Filter data",
            query_parameters={"threshold": 10}
        )

        # Record query result
        result_id = self.provenance_manager.record_query_result(
            query_id=query_id,
            output_id="query_result_001",
            result_count=100,
            result_type="data_frame",
            size=1024,
            fields=["id", "name", "value"]
        )

        # Verify query record
        self.assertIn(query_id, self.provenance_manager.records)
        query_record = self.provenance_manager.records[query_id]
        self.assertEqual(query_record.record_type, ProvenanceRecordType.QUERY)
        self.assertEqual(query_record.input_ids, ["query_data_001"])
        self.assertEqual(query_record.output_ids, ["query_result_001"])
        self.assertEqual(query_record.result_count, 100)
        self.assertIsNotNone(query_record.execution_time)

        # Verify result record
        self.assertIn(result_id, self.provenance_manager.records)
        result_record = self.provenance_manager.records[result_id]
        self.assertEqual(result_record.record_type, ProvenanceRecordType.RESULT)
        self.assertEqual(result_record.input_ids, [query_id])
        self.assertEqual(result_record.output_ids, ["query_result_001"])
        self.assertEqual(result_record.result_type, "data_frame")
        self.assertEqual(result_record.record_count, 100)

        # Verify graph connections
        self.assertTrue(self.provenance_manager.graph.has_edge(source_id, query_id))
        self.assertTrue(self.provenance_manager.graph.has_edge(query_id, result_id))

        # Verify entity's latest record was updated
        self.assertEqual(self.provenance_manager.entity_latest_record["query_result_001"], result_id)

    def test_merge_and_checkpoint(self):
        """Test merge operation and checkpoint."""
        # Record source 1
        source1_id = self.provenance_manager.record_source(
            data_id="merge_data_001",
            source_type="file",
            location="/path/to/data1.csv",
            format="csv",
            description="First data file"
        )

        # Record source 2
        source2_id = self.provenance_manager.record_source(
            data_id="merge_data_002",
            source_type="file",
            location="/path/to/data2.csv",
            format="csv",
            description="Second data file"
        )

        # Record merge
        merge_id = self.provenance_manager.record_merge(
            input_ids=["merge_data_001", "merge_data_002"],
            output_id="merged_data_001",
            merge_type="join",
            description="Merge two datasets",
            merge_keys=["id"],
            merge_strategy="inner",
            parameters={"how": "inner", "on": "id"}
        )

        # Record checkpoint
        checkpoint_id = self.provenance_manager.record_checkpoint(
            data_id="merged_data_001",
            description="Checkpoint after merge",
            checkpoint_type="snapshot"
        )

        # Verify merge record
        self.assertIn(merge_id, self.provenance_manager.records)
        merge_record = self.provenance_manager.records[merge_id]
        self.assertEqual(merge_record.record_type, ProvenanceRecordType.MERGE)
        self.assertEqual(set(merge_record.input_ids), {"merge_data_001", "merge_data_002"})
        self.assertEqual(merge_record.output_ids, ["merged_data_001"])
        self.assertEqual(merge_record.merge_type, "join")
        self.assertEqual(merge_record.merge_keys, ["id"])
        self.assertEqual(merge_record.merge_strategy, "inner")

        # Verify checkpoint record
        self.assertIn(checkpoint_id, self.provenance_manager.records)
        checkpoint_record = self.provenance_manager.records[checkpoint_id]
        self.assertEqual(checkpoint_record.record_type, ProvenanceRecordType.CHECKPOINT)
        self.assertEqual(checkpoint_record.input_ids, ["merged_data_001"])
        self.assertEqual(checkpoint_record.output_ids, ["merged_data_001"])
        self.assertEqual(checkpoint_record.parameters["checkpoint_type"], "snapshot")

        # Verify graph connections
        self.assertTrue(self.provenance_manager.graph.has_edge(source1_id, merge_id))
        self.assertTrue(self.provenance_manager.graph.has_edge(source2_id, merge_id))
        self.assertTrue(self.provenance_manager.graph.has_edge(merge_id, "merged_data_001"))

        # Verify entity's latest record was updated
        self.assertEqual(self.provenance_manager.entity_latest_record["merged_data_001"], checkpoint_id)

    def test_export_import(self):
        """Test exporting and importing provenance data."""
        # Record some provenance data
        source_id = self.provenance_manager.record_source(
            data_id="export_data_001",
            source_type="file",
            location="/path/to/export.csv",
            format="csv",
            description="Data for export test"
        )

        transform_id = self.provenance_manager.begin_transformation(
            description="Transform for export",
            transformation_type="preprocessing",
            tool="pandas",
            input_ids=["export_data_001"]
        )

        self.provenance_manager.end_transformation(
            transformation_id=transform_id,
            output_ids=["transformed_data_001"],
            success=True
        )

        # Export to dictionary
        export_dict = self.provenance_manager.export_provenance_to_dict()
        self.assertIn("records", export_dict)
        self.assertIn("entity_latest_record", export_dict)
        self.assertIn("metadata", export_dict)
        self.assertEqual(len(export_dict["records"]), 2)  # source and transformation

        # Export to JSON string
        json_str = self.provenance_manager.export_provenance_to_json()
        self.assertIsInstance(json_str, str)

        # Create a new provenance manager and import data
        new_manager = ProvenanceManager()
        new_manager.import_provenance_from_json(json_str)

        # Verify imported data
        self.assertEqual(len(new_manager.records), 2)
        self.assertIn(source_id, new_manager.records)
        self.assertIn(transform_id, new_manager.records)
        self.assertEqual(new_manager.entity_latest_record["transformed_data_001"], transform_id)

        # Export to file
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as temp_file:
            temp_path = temp_file.name

        try:
            self.provenance_manager.export_provenance_to_json(temp_path)

            # Create another new manager and import from file
            another_manager = ProvenanceManager()
            another_manager.import_provenance_from_file(temp_path)

            # Verify imported data
            self.assertEqual(len(another_manager.records), 2)
            self.assertIn(source_id, another_manager.records)
            self.assertIn(transform_id, another_manager.records)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_lineage_and_visualization(self):
        """Test data lineage querying and visualization."""
        # Create a chain of transformations
        source_id = self.provenance_manager.record_source(
            data_id="lineage_data_001",
            source_type="file",
            location="/path/to/lineage.csv",
            format="csv",
            description="Data for lineage test"
        )

        transform1_id = self.provenance_manager.begin_transformation(
            description="First transformation",
            transformation_type="preprocessing",
            tool="pandas",
            input_ids=["lineage_data_001"]
        )

        self.provenance_manager.end_transformation(
            transformation_id=transform1_id,
            output_ids=["lineage_data_002"],
            success=True
        )

        transform2_id = self.provenance_manager.begin_transformation(
            description="Second transformation",
            transformation_type="feature_extraction",
            tool="scikit-learn",
            input_ids=["lineage_data_002"]
        )

        self.provenance_manager.end_transformation(
            transformation_id=transform2_id,
            output_ids=["lineage_data_003"],
            success=True
        )

        # Get lineage for final data
        lineage = self.provenance_manager.get_data_lineage("lineage_data_003")
        self.assertEqual(lineage["record_id"], transform2_id)
        self.assertEqual(len(lineage["parents"]), 1)
        parent = lineage["parents"][0]
        self.assertEqual(parent["record_id"], transform1_id)
        self.assertEqual(len(parent["parents"]), 1)
        grandparent = parent["parents"][0]
        self.assertEqual(grandparent["record_id"], source_id)

        # Test visualization
        with patch('matplotlib.pyplot.savefig') as mock_savefig:
            # In-memory visualization
            self.provenance_manager.visualize_provenance(
                data_ids=["lineage_data_003"],
                max_depth=3,
                return_base64=False
            )
            mock_savefig.assert_not_called()

            # File visualization
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_path = temp_file.name

            try:
                self.provenance_manager.visualize_provenance(
                    data_ids=["lineage_data_003"],
                    max_depth=3,
                    file_path=temp_path
                )
                mock_savefig.assert_called_once()
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

            # Base64 visualization
            mock_savefig.reset_mock()
            result = self.provenance_manager.visualize_provenance(
                data_ids=["lineage_data_003"],
                max_depth=3,
                return_base64=True
            )
            mock_savefig.assert_called_once()
            self.assertIsInstance(result, str)

    def test_audit_report(self):
        """Test generating audit reports."""
        # Record some provenance data for the report
        self.provenance_manager.record_source(
            data_id="report_data_001",
            source_type="file",
            location="/path/to/report.csv",
            format="csv",
            description="Data for report test"
        )

        transform_id = self.provenance_manager.begin_transformation(
            description="Transform for report",
            transformation_type="preprocessing",
            tool="pandas",
            input_ids=["report_data_001"],
            parameters={"dropna": True}
        )

        self.provenance_manager.end_transformation(
            transformation_id=transform_id,
            output_ids=["report_data_002"],
            success=True
        )

        # Generate text report
        text_report = self.provenance_manager.generate_audit_report(
            data_ids=["report_data_001", "report_data_002"],
            include_parameters=True,
            format="text"
        )
        self.assertIsInstance(text_report, str)
        self.assertIn("Data Provenance Audit Report", text_report)
        self.assertIn("report_data_001", text_report)
        self.assertIn("report_data_002", text_report)
        self.assertIn("dropna", text_report)

        # Generate JSON report
        json_report = self.provenance_manager.generate_audit_report(
            data_ids=["report_data_001", "report_data_002"],
            include_parameters=True,
            format="json"
        )
        report_data = json.loads(json_report)
        self.assertIn("records", report_data)
        self.assertEqual(len(report_data["records"]), 2)

        # Generate HTML report
        html_report = self.provenance_manager.generate_audit_report(
            data_ids=["report_data_001", "report_data_002"],
            include_parameters=True,
            format="html"
        )
        self.assertIsInstance(html_report, str)
        self.assertIn("<!DOCTYPE html>", html_report)
        self.assertIn("Data Provenance Audit Report", html_report)
        self.assertIn("report_data_001", html_report)
        self.assertIn("report_data_002", html_report)

        # Generate Markdown report
        md_report = self.provenance_manager.generate_audit_report(
            data_ids=["report_data_001", "report_data_002"],
            include_parameters=True,
            format="md"
        )
        self.assertIsInstance(md_report, str)
        self.assertIn("# Data Provenance Audit Report", md_report)
        self.assertIn("report_data_001", md_report)
        self.assertIn("report_data_002", md_report)


class TestProvenanceIntegrationWithIPLD(unittest.TestCase):
    """Integration tests with IPLD storage (mock)."""

    @patch('ipfs_datasets_py.data_provenance.ProvenanceManager._store_in_ipld')
    def test_ipld_integration(self, mock_store_in_ipld):
        """Test integration with IPLD storage."""
        # Mock IPLD storage to return a random CID
        mock_store_in_ipld.return_value = "bafy1234abcd"

        # Create provenance manager with IPLD storage enabled
        manager = ProvenanceManager(
            enable_ipld_storage=True,
            default_agent_id="ipld_test"
        )

        # Record some provenance data
        source_id = manager.record_source(
            data_id="ipld_data_001",
            source_type="file",
            location="/path/to/ipld.csv",
            format="csv",
            description="Data for IPLD test"
        )

        # Verify IPLD storage was called
        mock_store_in_ipld.assert_called()

        # Verify CID was set on the record
        record = manager.records[source_id]
        self.assertEqual(record.cid, "bafy1234abcd")


if __name__ == '__main__':
    unittest.main()
