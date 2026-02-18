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


class TestNeo4jExporterWithMocking:
    """Test Neo4jExporter with mocked Neo4j driver."""
    
    def test_exporter_initialization_with_neo4j(self, mocker):
        """Test exporter initialization when neo4j is available."""
        # Mock neo4j import
        mock_graphdb = mocker.MagicMock()
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig()
        exporter = Neo4jExporter(config)
        
        assert exporter.config == config
        assert exporter._neo4j_available is True
    
    def test_exporter_initialization_without_neo4j(self, mocker):
        """Test exporter initialization when neo4j is not available."""
        # Mock neo4j import to raise ImportError
        def mock_import(name, *args, **kwargs):
            if name == 'neo4j':
                raise ImportError("No module named 'neo4j'")
            return mocker.DEFAULT
        
        mocker.patch('builtins.__import__', side_effect=mock_import)
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig()
        exporter = Neo4jExporter(config)
        
        assert exporter._neo4j_available is False
    
    def test_connect_success(self, mocker):
        """Test successful connection to Neo4j."""
        # Mock Neo4j driver
        mock_driver = mocker.MagicMock()
        mock_driver.verify_connectivity.return_value = None
        mock_graphdb = mocker.MagicMock()
        mock_graphdb.driver.return_value = mock_driver
        
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig()
        exporter = Neo4jExporter(config)
        result = exporter._connect()
        
        assert result is True
        mock_graphdb.driver.assert_called_once()
    
    def test_connect_failure(self, mocker):
        """Test connection failure to Neo4j."""
        # Mock Neo4j driver to raise exception
        mock_graphdb = mocker.MagicMock()
        mock_graphdb.driver.side_effect = Exception("Connection failed")
        
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig()
        exporter = Neo4jExporter(config)
        result = exporter._connect()
        
        assert result is False
    
    def test_connect_without_neo4j_installed(self, mocker):
        """Test connect raises error when neo4j not installed."""
        def mock_import(name, *args, **kwargs):
            if name == 'neo4j':
                raise ImportError("No module named 'neo4j'")
            return mocker.DEFAULT
        
        mocker.patch('builtins.__import__', side_effect=mock_import)
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig()
        exporter = Neo4jExporter(config)
        
        with pytest.raises(RuntimeError, match="neo4j package not installed"):
            exporter._connect()
    
    def test_export_nodes_basic(self, mocker):
        """Test basic node export."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, NodeData
        
        # Mock Neo4j session and results
        mock_record1 = {'id': 1, 'labels': ['Person'], 'properties': {'name': 'Alice'}}
        mock_record2 = {'id': 2, 'labels': ['Person'], 'properties': {'name': 'Bob'}}
        
        mock_result = mocker.MagicMock()
        mock_result.__iter__.return_value = iter([mock_record1, mock_record2])
        
        mock_session = mocker.MagicMock()
        mock_session.run.return_value = mock_result
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        
        mock_driver = mocker.MagicMock()
        mock_driver.session.return_value = mock_session
        
        mock_graphdb = mocker.MagicMock()
        mock_graphdb.driver.return_value = mock_driver
        
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig()
        exporter = Neo4jExporter(config)
        exporter._driver = mock_driver
        
        graph_data = GraphData()
        count = exporter._export_nodes(graph_data)
        
        assert count == 2
        assert len(graph_data.nodes) == 2
        assert graph_data.nodes[0].id == '1'
        assert graph_data.nodes[0].labels == ['Person']
    
    def test_export_nodes_with_label_filter(self, mocker):
        """Test node export with label filter."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        
        mock_result = mocker.MagicMock()
        mock_result.__iter__.return_value = iter([])
        
        mock_session = mocker.MagicMock()
        mock_session.run.return_value = mock_result
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        
        mock_driver = mocker.MagicMock()
        mock_driver.session.return_value = mock_session
        
        mock_graphdb = mocker.MagicMock()
        mock_graphdb.driver.return_value = mock_driver
        
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig(node_labels=["Person", "Organization"])
        exporter = Neo4jExporter(config)
        exporter._driver = mock_driver
        
        graph_data = GraphData()
        count = exporter._export_nodes(graph_data)
        
        # Verify label filter was used in query
        mock_session.run.assert_called_once()
        query = mock_session.run.call_args[0][0]
        assert "WHERE" in query
        assert "n:Person" in query or "Person" in query
    
    def test_export_nodes_with_batching(self, mocker):
        """Test node export with batch processing."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        
        # Create 2500 mock records to test batching (batch_size=1000)
        mock_records = [
            {'id': i, 'labels': ['Node'], 'properties': {'index': i}}
            for i in range(2500)
        ]
        
        mock_result = mocker.MagicMock()
        mock_result.__iter__.return_value = iter(mock_records)
        
        mock_session = mocker.MagicMock()
        mock_session.run.return_value = mock_result
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        
        mock_driver = mocker.MagicMock()
        mock_driver.session.return_value = mock_session
        
        mock_graphdb = mocker.MagicMock()
        mock_graphdb.driver.return_value = mock_driver
        
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig(batch_size=1000)
        exporter = Neo4jExporter(config)
        exporter._driver = mock_driver
        
        graph_data = GraphData()
        count = exporter._export_nodes(graph_data)
        
        assert count == 2500
        assert len(graph_data.nodes) == 2500
    
    def test_export_nodes_with_progress_callback(self, mocker):
        """Test node export with progress callback."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        
        mock_records = [
            {'id': i, 'labels': ['Node'], 'properties': {}}
            for i in range(1500)
        ]
        
        mock_result = mocker.MagicMock()
        mock_result.__iter__.return_value = iter(mock_records)
        
        mock_session = mocker.MagicMock()
        mock_session.run.return_value = mock_result
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        
        mock_driver = mocker.MagicMock()
        mock_driver.session.return_value = mock_session
        
        mock_graphdb = mocker.MagicMock()
        mock_graphdb.driver.return_value = mock_driver
        
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        callback_called = []
        def progress_callback(nodes, rels, msg):
            callback_called.append((nodes, rels, msg))
        
        config = ExportConfig(batch_size=1000, progress_callback=progress_callback)
        exporter = Neo4jExporter(config)
        exporter._driver = mock_driver
        
        graph_data = GraphData()
        count = exporter._export_nodes(graph_data)
        
        assert count == 1500
        assert len(callback_called) > 0  # Callback should be called during batching
    
    def test_export_relationships_basic(self, mocker):
        """Test basic relationship export."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        
        mock_records = [
            {'id': 1, 'type': 'KNOWS', 'start': 1, 'end': 2, 'properties': {'since': 2020}},
            {'id': 2, 'type': 'WORKS_WITH', 'start': 1, 'end': 3, 'properties': {}}
        ]
        
        mock_result = mocker.MagicMock()
        mock_result.__iter__.return_value = iter(mock_records)
        
        mock_session = mocker.MagicMock()
        mock_session.run.return_value = mock_result
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        
        mock_driver = mocker.MagicMock()
        mock_driver.session.return_value = mock_session
        
        mock_graphdb = mocker.MagicMock()
        mock_graphdb.driver.return_value = mock_driver
        
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig()
        exporter = Neo4jExporter(config)
        exporter._driver = mock_driver
        
        graph_data = GraphData()
        count = exporter._export_relationships(graph_data)
        
        assert count == 2
        assert len(graph_data.relationships) == 2
        assert graph_data.relationships[0].type == 'KNOWS'
    
    def test_export_relationships_with_type_filter(self, mocker):
        """Test relationship export with type filter."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        
        mock_result = mocker.MagicMock()
        mock_result.__iter__.return_value = iter([])
        
        mock_session = mocker.MagicMock()
        mock_session.run.return_value = mock_result
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        
        mock_driver = mocker.MagicMock()
        mock_driver.session.return_value = mock_session
        
        mock_graphdb = mocker.MagicMock()
        mock_graphdb.driver.return_value = mock_driver
        
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig(relationship_types=["KNOWS", "WORKS_AT"])
        exporter = Neo4jExporter(config)
        exporter._driver = mock_driver
        
        graph_data = GraphData()
        count = exporter._export_relationships(graph_data)
        
        # Verify type filter was used in query
        mock_session.run.assert_called_once()
        query = mock_session.run.call_args[0][0]
        assert "WHERE" in query
        assert "type(r)" in query
    
    def test_close_connection(self, mocker):
        """Test closing Neo4j connection."""
        mock_driver = mocker.MagicMock()
        mock_graphdb = mocker.MagicMock()
        mock_graphdb.driver.return_value = mock_driver
        
        mocker.patch.dict('sys.modules', {'neo4j': mocker.MagicMock(GraphDatabase=mock_graphdb)})
        
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import Neo4jExporter
        
        config = ExportConfig()
        exporter = Neo4jExporter(config)
        exporter._driver = mock_driver
        
        exporter._close()
        
        mock_driver.close.assert_called_once()


if __name__ == "__main__" and HAVE_PYTEST:
    pytest.main([__file__, "-v"])
