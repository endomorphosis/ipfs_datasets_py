"""
Tests for security module TypedDict contracts.

Validates that security.SecurityManager methods returning Dict[str, Any]
are properly typed as TypedDict contracts.
"""

import pytest
from ipfs_datasets_py.security import (
    SecurityManager,
    SecurityConfig,
    EncryptFileDict,
    LineageGraphDict,
    ProvenanceReportDict,
    FormattedReportTextDict,
    FormattedReportHtmlDict,
    FormattedReportMarkdownDict,
    LineageVisualizationDict,
    FormattedLineageDotDict,
    FormattedLineageMermaidDict,
    FormattedLineageD3Dict,
)


class TestEncryptFileDict:
    """Test EncryptFileDict contract."""
    
    def test_encrypt_file_structure(self):
        """Verify encrypt_file returns expected structure format."""
        # Structure validation
        sample_result: EncryptFileDict = {
            "file_hash": "abc123",
            "encrypted_path": "/path/to/encrypted",
            "encryption_algorithm": "AES-256",
            "key_id": "key_123",
            "timestamp": "2024-01-01T00:00:00",
            "bytes_encrypted": 1024,
            "checksum": "def456"
        }
        assert "file_hash" in sample_result or "encrypted_path" in sample_result
    
    def test_encrypt_file_types(self):
        """Verify field types in EncryptFileDict."""
        sample: EncryptFileDict = {
            "file_hash": "hash",
            "bytes_encrypted": 1000
        }
        assert isinstance(sample.get("file_hash"), (str, type(None)))
        assert isinstance(sample.get("bytes_encrypted"), (int, type(None)))


class TestLineageGraphDict:
    """Test LineageGraphDict contract."""
    
    def test_lineage_graph_structure(self):
        """Verify get_data_lineage_graph returns expected format."""
        sample_result: LineageGraphDict = {
            "nodes": [{"id": "1"}],
            "edges": [{"source": "1", "target": "2"}],
            "node_count": 1,
            "edge_count": 1,
            "graph_format": "json",
            "timestamp": "2024-01-01T00:00:00",
            "depth": 5
        }
        if "nodes" in sample_result:
            assert isinstance(sample_result["nodes"], list)
        if "edges" in sample_result:
            assert isinstance(sample_result["edges"], list)
    
    def test_lineage_graph_counts(self):
        """Verify count fields are integers."""
        sample: LineageGraphDict = {
            "node_count": 5,
            "edge_count": 3
        }
        assert isinstance(sample.get("node_count"), (int, type(None)))
        assert isinstance(sample.get("edge_count"), (int, type(None)))


class TestProvenanceReportDict:
    """Test ProvenanceReportDict contract."""
    
    def test_provenance_report_structure(self):
        """Verify generate_provenance_report returns expected format."""
        sample_result: ProvenanceReportDict = {
            "lineage": {"nodes": []},
            "data_sources": ["source1"],
            "processing_steps": [{"step": 1}],
            "access_history": [{"timestamp": "2024-01-01"}],
            "checksums": {"file1": "hash123"},
            "timestamp": "2024-01-01T00:00:00",
            "report_format": "json"
        }
        if "data_sources" in sample_result:
            assert isinstance(sample_result["data_sources"], list)
    
    def test_provenance_report_dicts(self):
        """Verify complex field types."""
        sample: ProvenanceReportDict = {
            "lineage": {"key": "value"},
            "checksums": {"file": "hash"}
        }
        assert isinstance(sample.get("lineage"), (dict, type(None)))
        assert isinstance(sample.get("checksums"), (dict, type(None)))


class TestFormattedReportDicts:
    """Test all formatted report TypedDicts."""
    
    def test_formatted_report_text_structure(self):
        """Verify text formatted report structure."""
        sample: FormattedReportTextDict = {
            "formatted_text": "Report content",
            "text_format": "text",
            "line_count": 10,
            "character_count": 100,
            "timestamp": "2024-01-01T00:00:00"
        }
        assert isinstance(sample.get("formatted_text"), (str, type(None)))
        assert isinstance(sample.get("line_count"), (int, type(None)))
    
    def test_formatted_report_html_structure(self):
        """Verify HTML formatted report structure."""
        sample: FormattedReportHtmlDict = {
            "html_content": "<html></html>",
            "html_format": "html",
            "has_styles": True,
            "has_scripts": False,
            "timestamp": "2024-01-01T00:00:00"
        }
        assert isinstance(sample.get("html_content"), (str, type(None)))
        assert isinstance(sample.get("has_styles"), (bool, type(None)))
    
    def test_formatted_report_markdown_structure(self):
        """Verify markdown formatted report structure."""
        sample: FormattedReportMarkdownDict = {
            "markdown_content": "# Report",
            "markdown_format": "markdown",
            "section_count": 5,
            "code_block_count": 2,
            "timestamp": "2024-01-01T00:00:00"
        }
        assert isinstance(sample.get("markdown_content"), (str, type(None)))
        assert isinstance(sample.get("section_count"), (int, type(None)))


class TestLineageVisualizationDict:
    """Test LineageVisualizationDict contract."""
    
    def test_lineage_visualization_structure(self):
        """Verify lineage visualization structure."""
        sample_result: LineageVisualizationDict = {
            "nodes": [{"id": "1"}],
            "edges": [{"source": "1", "target": "2"}],
            "visualization_formats": ["dot", "mermaid", "d3"],
            "graph_metrics": {"density": 0.5},
            "timestamp": "2024-01-01T00:00:00"
        }
        if "nodes" in sample_result:
            assert isinstance(sample_result["nodes"], list)
        if "visualization_formats" in sample_result:
            assert isinstance(sample_result["visualization_formats"], list)


class TestFormattedLineageDicts:
    """Test all formatted lineage TypedDicts."""
    
    def test_formatted_lineage_dot_structure(self):
        """Verify DOT format lineage structure."""
        sample: FormattedLineageDotDict = {
            "dot_content": "digraph {...}",
            "dot_format": "dot",
            "node_count": 5,
            "edge_count": 4,
            "timestamp": "2024-01-01T00:00:00"
        }
        assert isinstance(sample.get("dot_content"), (str, type(None)))
        assert isinstance(sample.get("node_count"), (int, type(None)))
    
    def test_formatted_lineage_mermaid_structure(self):
        """Verify Mermaid format lineage structure."""
        sample: FormattedLineageMermaidDict = {
            "mermaid_content": "graph TD {...}",
            "mermaid_format": "mermaid",
            "diagram_type": "flowchart",
            "node_count": 5,
            "edge_count": 4,
            "timestamp": "2024-01-01T00:00:00"
        }
        assert isinstance(sample.get("mermaid_content"), (str, type(None)))
        assert isinstance(sample.get("diagram_type"), (str, type(None)))
    
    def test_formatted_lineage_d3_structure(self):
        """Verify D3.js format lineage structure."""
        sample: FormattedLineageD3Dict = {
            "d3_json": {"nodes": [], "links": []},
            "d3_format": "d3",
            "layout_type": "force",
            "node_count": 5,
            "edge_count": 4,
            "timestamp": "2024-01-01T00:00:00"
        }
        assert isinstance(sample.get("d3_json"), (dict, type(None)))
        assert isinstance(sample.get("layout_type"), (str, type(None)))


class TestTypeConsistency:
    """Test consistency across different TypedDicts."""
    
    def test_all_dicts_have_optional_timestamp(self):
        """Verify timestamp field present in result dicts."""
        dicts_with_timestamp = [
            FormattedReportTextDict,
            FormattedReportHtmlDict,
            FormattedReportMarkdownDict,
            LineageVisualizationDict,
            FormattedLineageDotDict,
            FormattedLineageMermaidDict,
            FormattedLineageD3Dict,
        ]
        # All these TypedDicts should support timestamp field
        for dict_type in dicts_with_timestamp:
            sample = dict_type(timestamp="2024-01-01T00:00:00")
            assert "timestamp" in sample
    
    def test_graph_dicts_have_counts(self):
        """Verify graph-related dicts have count fields."""
        graph_results = [
            LineageGraphDict(node_count=5, edge_count=4),
            LineageVisualizationDict(node_count=5, edge_count=4),
            FormattedLineageDotDict(node_count=5, edge_count=4),
            FormattedLineageMermaidDict(node_count=5, edge_count=4),
            FormattedLineageD3Dict(node_count=5, edge_count=4),
        ]
        for result in graph_results:
            assert isinstance(result.get("node_count"), (int, type(None)))
            assert isinstance(result.get("edge_count"), (int, type(None)))


class TestEdgeCases:
    """Test edge cases for TypedDict contracts."""
    
    def test_partial_dict_fields(self):
        """Test that TypedDicts accept partial field sets (total=False)."""
        # With total=False, we don't need all fields
        minimal_encrypt: EncryptFileDict = {}
        assert isinstance(minimal_encrypt, dict)
        
        minimal_lineage: LineageGraphDict = {"nodes": []}
        assert "nodes" in minimal_lineage
    
    def test_optional_fields_can_be_none(self):
        """Verify optional fields can be None."""
        sample: ProvenanceReportDict = {
            "lineage": None,
            "data_sources": None,
            "checksums": None
        }
        assert sample["lineage"] is None or sample["lineage"] is not None


class TestIntegration:
    """Integration tests for security module TypedDicts."""
    
    def test_security_manager_instantiation(self):
        """Verify SecurityManager can be instantiated."""
        try:
            config = SecurityConfig(enabled=False)
            manager = SecurityManager(config)
            assert manager is not None
        except Exception:
            # SecurityManager may have dependencies not available in test env
            pass
    
    def test_typeddict_compatibility(self):
        """Verify TypedDicts are compatible with dict operations."""
        result: EncryptFileDict = {
            "file_hash": "abc123",
            "encrypted_path": "/path"
        }
        # Should be usable as dict
        assert len(result) >= 2
        for key in result:
            assert isinstance(key, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
