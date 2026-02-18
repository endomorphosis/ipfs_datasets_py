"""
Tests for Neo4j exporter basic functionality (no Neo4j connection required)
"""

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
    ExportConfig, ExportResult
)


class TestExportConfig:
    """Test ExportConfig class."""
    
    def test_config_creation_defaults(self):
        """Test creating config with default values."""
        config = ExportConfig()
        
        assert config.uri == "bolt://localhost:7687"
        assert config.username == "neo4j"
        assert config.password == "password"
        assert config.database == "neo4j"
        assert config.batch_size == 1000
        assert config.include_schema is True
    
    def test_config_creation_custom(self):
        """Test creating config with custom values."""
        config = ExportConfig(
            uri="bolt://custom:7687",
            username="admin",
            password="secret",
            batch_size=500,
            include_schema=False
        )
        
        assert config.uri == "bolt://custom:7687"
        assert config.username == "admin"
        assert config.password == "secret"
        assert config.batch_size == 500
        assert config.include_schema is False
    
    def test_config_with_filters(self):
        """Test config with label and type filters."""
        config = ExportConfig(
            node_labels=["Person", "Organization"],
            relationship_types=["KNOWS", "WORKS_AT"]
        )
        
        assert config.node_labels == ["Person", "Organization"]
        assert config.relationship_types == ["KNOWS", "WORKS_AT"]
    
    def test_config_with_output_file(self):
        """Test config with output file specified."""
        config = ExportConfig(
            output_file="/tmp/export.json"
        )
        
        assert config.output_file == "/tmp/export.json"


class TestExportResult:
    """Test ExportResult class."""
    
    def test_result_creation(self):
        """Test creating export result."""
        result = ExportResult(
            success=True,
            node_count=100,
            relationship_count=50,
            duration_seconds=10.5
        )
        
        assert result.success is True
        assert result.node_count == 100
        assert result.relationship_count == 50
        assert result.duration_seconds == 10.5
    
    def test_result_to_dict(self):
        """Test converting result to dictionary."""
        result = ExportResult(
            success=False,
            node_count=0,
            relationship_count=0,
            errors=["Connection failed"],
            warnings=["Slow performance"]
        )
        
        data = result.to_dict()
        
        assert data['success'] is False
        assert data['node_count'] == 0
        assert len(data['errors']) == 1
        assert len(data['warnings']) == 1
    
    def test_result_with_output_file(self):
        """Test result with output file path."""
        result = ExportResult(
            success=True,
            output_file="/tmp/export.json"
        )
        
        assert result.output_file == "/tmp/export.json"
    
    def test_result_with_multiple_errors(self):
        """Test result with multiple errors."""
        result = ExportResult(
            success=False,
            errors=["Error 1", "Error 2", "Error 3"]
        )
        
        assert len(result.errors) == 3
        assert result.success is False


if __name__ == "__main__" and HAVE_PYTEST:
    pytest.main([__file__, "-v"])
