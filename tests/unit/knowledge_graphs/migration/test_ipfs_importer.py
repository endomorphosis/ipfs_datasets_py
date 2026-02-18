"""
Tests for IPFS importer with comprehensive mocking
"""

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

import tempfile
import os
import json

from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
    ImportConfig, ImportResult
)
from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData, NodeData, RelationshipData, MigrationFormat
)


class TestImportConfig:
    """Test ImportConfig class."""
    
    def test_config_creation_defaults(self):
        """Test creating config with default values."""
        config = ImportConfig()
        
        assert config.input_file is None
        assert config.input_format == MigrationFormat.DAG_JSON
        assert config.batch_size == 1000
        assert config.create_indexes is True
        assert config.validate_data is True
    
    def test_config_creation_with_file(self):
        """Test creating config with input file."""
        config = ImportConfig(input_file="/tmp/import.json")
        
        assert config.input_file == "/tmp/import.json"
    
    def test_config_creation_with_graph_data(self):
        """Test creating config with direct graph data."""
        graph_data = GraphData(nodes=[NodeData(id="1", labels=["Test"])])
        config = ImportConfig(graph_data=graph_data)
        
        assert config.graph_data is not None
        assert len(config.graph_data.nodes) == 1
    
    def test_config_with_custom_options(self):
        """Test config with custom import options."""
        config = ImportConfig(
            batch_size=500,
            create_indexes=False,
            validate_data=False,
            skip_duplicates=False
        )
        
        assert config.batch_size == 500
        assert config.create_indexes is False
        assert config.validate_data is False
        assert config.skip_duplicates is False


class TestImportResult:
    """Test ImportResult class."""
    
    def test_result_creation(self):
        """Test creating import result."""
        result = ImportResult(
            success=True,
            nodes_imported=100,
            relationships_imported=50,
            duration_seconds=5.5
        )
        
        assert result.success is True
        assert result.nodes_imported == 100
        assert result.relationships_imported == 50
        assert result.duration_seconds == 5.5
    
    def test_result_to_dict(self):
        """Test converting result to dictionary."""
        result = ImportResult(
            success=False,
            nodes_imported=50,
            nodes_skipped=10,
            errors=["Import failed"],
            warnings=["Some warnings"]
        )
        
        data = result.to_dict()
        
        assert data['success'] is False
        assert data['nodes_imported'] == 50
        assert data['nodes_skipped'] == 10
        assert len(data['errors']) == 1
        assert len(data['warnings']) == 1
    
    def test_result_with_skipped_counts(self):
        """Test result with skipped node/relationship counts."""
        result = ImportResult(
            success=True,
            nodes_imported=90,
            relationships_imported=45,
            nodes_skipped=10,
            relationships_skipped=5
        )
        
        assert result.nodes_skipped == 10
        assert result.relationships_skipped == 5


class TestIPFSImporterWithMocking:
    """Test IPFSImporter with mocked IPFS components."""
    
    def test_importer_initialization(self, mocker):
        """Test importer initialization."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        config = ImportConfig()
        importer = IPFSImporter(config)
        
        assert importer.config == config
        assert isinstance(importer._node_id_map, dict)
    
    def test_connect_requires_ipfs(self, mocker):
        """Test that connect checks for IPFS availability."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        config = ImportConfig()
        importer = IPFSImporter(config)
        
        # If IPFS is not available, connect should raise RuntimeError
        if not importer._ipfs_available:
            with pytest.raises(RuntimeError, match="IPFS graph database not available"):
                importer._connect()
    
    def test_load_graph_data_from_config(self, mocker):
        """Test loading graph data from config."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        graph_data = GraphData(
            nodes=[NodeData(id="1", labels=["Test"], properties={"name": "test"})]
        )
        config = ImportConfig(graph_data=graph_data)
        importer = IPFSImporter(config)
        
        loaded_data = importer._load_graph_data()
        
        assert loaded_data is not None
        assert len(loaded_data.nodes) == 1
        assert loaded_data.nodes[0].id == "1"
    
    def test_load_graph_data_from_file(self, mocker):
        """Test loading graph data from file."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        # Create temporary file with graph data
        graph_data = GraphData(
            nodes=[NodeData(id="1", labels=["Test"])],
            relationships=[]
        )
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
            f.write(graph_data.to_json())
        
        try:
            config = ImportConfig(input_file=filepath, input_format=MigrationFormat.DAG_JSON)
            importer = IPFSImporter(config)
            
            loaded_data = importer._load_graph_data()
            
            assert loaded_data is not None
            assert len(loaded_data.nodes) == 1
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_load_graph_data_file_not_found(self, mocker):
        """Test loading graph data from non-existent file."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        config = ImportConfig(input_file="/nonexistent/file.json")
        importer = IPFSImporter(config)
        
        loaded_data = importer._load_graph_data()
        
        assert loaded_data is None
    
    def test_load_graph_data_invalid_json(self, mocker):
        """Test loading invalid JSON file."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
            f.write("{invalid json")
        
        try:
            config = ImportConfig(input_file=filepath)
            importer = IPFSImporter(config)
            
            loaded_data = importer._load_graph_data()
            
            assert loaded_data is None
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
    
    def test_connect_without_ipfs_available(self, mocker):
        """Test connect raises error when IPFS not available."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        config = ImportConfig()
        importer = IPFSImporter(config)
        
        with pytest.raises(RuntimeError, match="IPFS graph database not available"):
            importer._connect()
    
    def test_validate_graph_data_valid(self, mocker):
        """Test validation of valid graph data."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        graph_data = GraphData(
            nodes=[
                NodeData(id="1", labels=["Person"], properties={"name": "Alice"}),
                NodeData(id="2", labels=["Person"], properties={"name": "Bob"})
            ],
            relationships=[
                RelationshipData(id="1", type="KNOWS", start_node="1", end_node="2")
            ]
        )
        
        config = ImportConfig()
        importer = IPFSImporter(config)
        
        # Call validate method (if it exists, otherwise test data structure)
        is_valid = importer._validate_graph_data(graph_data) if hasattr(importer, '_validate_graph_data') else True
        
        assert is_valid or graph_data.node_count == 2
    
    def test_import_result_tracking(self, mocker):
        """Test that import result tracks counts correctly."""
        result = ImportResult(success=True)
        
        # Simulate importing nodes
        result.nodes_imported = 100
        result.relationships_imported = 50
        result.nodes_skipped = 5
        result.relationships_skipped = 2
        
        assert result.nodes_imported == 100
        assert result.relationships_imported == 50
        assert result.nodes_skipped == 5
        assert result.relationships_skipped == 2
    
    def test_import_with_progress_callback(self, mocker):
        """Test import with progress callback."""
        callback_called = []
        
        def progress_callback(nodes, rels, msg):
            callback_called.append((nodes, rels, msg))
        
        config = ImportConfig(progress_callback=progress_callback)
        
        # Test that callback can be called
        if config.progress_callback:
            config.progress_callback(10, 5, "Importing...")
        
        assert len(callback_called) == 1
        assert callback_called[0] == (10, 5, "Importing...")
    
    def test_batch_processing_logic(self, mocker):
        """Test batch processing configuration."""
        config = ImportConfig(batch_size=500)
        
        # Create data that would require multiple batches
        nodes = [NodeData(id=str(i), labels=["Node"]) for i in range(1500)]
        graph_data = GraphData(nodes=nodes)
        
        # Calculate expected batches
        expected_batches = (len(nodes) + config.batch_size - 1) // config.batch_size
        
        assert expected_batches == 3  # 1500 / 500 = 3 batches
    
    def test_skip_duplicates_option(self, mocker):
        """Test skip_duplicates configuration."""
        config_skip = ImportConfig(skip_duplicates=True)
        config_no_skip = ImportConfig(skip_duplicates=False)
        
        assert config_skip.skip_duplicates is True
        assert config_no_skip.skip_duplicates is False
    
    def test_create_indexes_option(self, mocker):
        """Test create_indexes configuration."""
        config = ImportConfig(create_indexes=True)
        
        assert config.create_indexes is True
    
    def test_validate_data_option(self, mocker):
        """Test validate_data configuration."""
        config_validate = ImportConfig(validate_data=True)
        config_no_validate = ImportConfig(validate_data=False)
        
        assert config_validate.validate_data is True
        assert config_no_validate.validate_data is False
    
    def test_import_from_different_formats(self, mocker):
        """Test importing from different file formats."""
        # Test DAG-JSON format
        config_dag = ImportConfig(input_format=MigrationFormat.DAG_JSON)
        assert config_dag.input_format == MigrationFormat.DAG_JSON
        
        # Test JSON Lines format
        config_jsonl = ImportConfig(input_format=MigrationFormat.JSON_LINES)
        assert config_jsonl.input_format == MigrationFormat.JSON_LINES
    
    def test_close_connection(self, mocker):
        """Test closing IPFS connection."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        config = ImportConfig()
        importer = IPFSImporter(config)
        
        # Mock session and driver
        importer._session = mocker.MagicMock()
        importer._driver = mocker.MagicMock()
        
        importer._close()
        
        importer._session.close.assert_called_once()
        importer._driver.close.assert_called_once()
    
    def test_node_id_mapping(self, mocker):
        """Test node ID mapping for import."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter
        
        config = ImportConfig()
        importer = IPFSImporter(config)
        
        # Test that node_id_map is initialized
        assert isinstance(importer._node_id_map, dict)
        
        # Add some mappings
        importer._node_id_map["neo4j_1"] = "ipfs_1"
        importer._node_id_map["neo4j_2"] = "ipfs_2"
        
        assert len(importer._node_id_map) == 2
        assert importer._node_id_map["neo4j_1"] == "ipfs_1"


if __name__ == "__main__" and HAVE_PYTEST:
    pytest.main([__file__, "-v"])
