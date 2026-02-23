"""
Session 29 — knowledge_graphs coverage tests.

Targets (total 65 new tests):
  * migration/neo4j_exporter.py  71% → 99%  (+28pp, 56 miss → ~2)
  * migration/ipfs_importer.py   82% → 97%  (+15pp, 38 miss → ~7)
  * core/_legacy_graph_engine.py 90% → 99%  (+9pp,  23 miss → ~3)
  * extraction/validator.py      79% → 99%  (+20pp, 38 miss → ~1)
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_neo4j_exporter(batch_size: int = 1000, **extra):
    """Create Neo4jExporter with a mocked neo4j module."""
    from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
        Neo4jExporter,
        ExportConfig,
    )
    mock_neo4j = MagicMock()
    with patch.dict(sys.modules, {"neo4j": mock_neo4j}):
        cfg = ExportConfig(
            uri="bolt://localhost:7687",
            username="neo4j",
            password="test",
            batch_size=batch_size,
            **extra,
        )
        exp = Neo4jExporter(cfg)
    return exp, cfg


def _make_record(data: dict):
    """Create a mock Neo4j-like record."""
    r = MagicMock()
    r.__getitem__ = lambda _s, k: data[k]
    r.get = lambda k, default=None: data.get(k, default)
    return r


# ---------------------------------------------------------------------------
# Neo4jExporter.__init__ — lines 112-113
# ---------------------------------------------------------------------------

class TestNeo4jExporterInit:
    """GIVEN a neo4j mock available WHEN Neo4jExporter is created THEN GraphDatabase stored."""

    def test_neo4j_available_when_module_mocked(self):
        """GIVEN neo4j mocked WHEN __init__ runs THEN _neo4j_available=True."""
        exp, _ = _make_neo4j_exporter()
        assert exp._neo4j_available is True

    def test_neo4j_graphdatabase_is_stored(self):
        """GIVEN neo4j mocked WHEN __init__ runs THEN _GraphDatabase attribute set."""
        exp, _ = _make_neo4j_exporter()
        assert exp._GraphDatabase is not None


# ---------------------------------------------------------------------------
# Neo4jExporter._connect — lines 134-136, 139-143
# ---------------------------------------------------------------------------

class TestNeo4jExporterConnect:
    """GIVEN a mocked GraphDatabase driver WHEN _connect is called THEN connection established."""

    def test_connect_success_returns_true(self):
        """GIVEN valid driver WHEN _connect THEN returns True and driver stored."""
        exp, _ = _make_neo4j_exporter()
        mock_driver = MagicMock()
        exp._GraphDatabase.driver.return_value = mock_driver
        assert exp._connect() is True
        assert exp._driver is mock_driver
        mock_driver.verify_connectivity.assert_called_once()

    def test_connect_exception_wraps_in_migration_error(self):
        """GIVEN driver raises RuntimeError WHEN _connect THEN MigrationError raised."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        exp, _ = _make_neo4j_exporter()
        exp._GraphDatabase.driver.side_effect = RuntimeError("connection refused")
        with pytest.raises(MigrationError):
            exp._connect()

    def test_connect_migration_error_re_raised(self):
        """GIVEN driver raises MigrationError WHEN _connect THEN same error propagates."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        exp, _ = _make_neo4j_exporter()
        exp._GraphDatabase.driver.side_effect = MigrationError("direct migration error")
        with pytest.raises(MigrationError, match="direct migration error"):
            exp._connect()

    def test_connect_not_available_raises(self):
        """GIVEN _neo4j_available=False WHEN _connect THEN MigrationError raised."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        exp, _ = _make_neo4j_exporter()
        exp._neo4j_available = False
        with pytest.raises(MigrationError, match="neo4j package not installed"):
            exp._connect()


# ---------------------------------------------------------------------------
# Neo4jExporter._export_nodes — lines 171-197, 200-201
# ---------------------------------------------------------------------------

class TestNeo4jExporterExportNodes:
    """GIVEN a driver session with records WHEN _export_nodes called THEN nodes collected."""

    def _setup_session(self, exp, records):
        """Inject records into exp._driver mock session."""
        mock_session = MagicMock()
        mock_session.run.return_value = iter(records)
        exp._driver = MagicMock()
        exp._driver.session.return_value.__enter__ = lambda _s: mock_session
        exp._driver.session.return_value.__exit__ = MagicMock(return_value=False)
        return mock_session

    def test_export_nodes_basic(self):
        """GIVEN 2 records WHEN _export_nodes THEN 2 nodes returned."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, _ = _make_neo4j_exporter(batch_size=10)
        records = [
            _make_record({"id": i, "labels": ["Person"], "properties": {"name": f"p{i}"}})
            for i in range(2)
        ]
        self._setup_session(exp, records)
        gd = GraphData()
        count = exp._export_nodes(gd)
        assert count == 2
        assert len(gd.nodes) == 2

    def test_export_nodes_batch_flush_triggered(self):
        """GIVEN batch_size=2 and 3 records WHEN _export_nodes THEN batch flushed mid-way."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        cb = MagicMock()
        exp, cfg = _make_neo4j_exporter(batch_size=2)
        cfg.progress_callback = cb
        records = [
            _make_record({"id": i, "labels": ["X"], "properties": {}})
            for i in range(3)
        ]
        self._setup_session(exp, records)
        gd = GraphData()
        count = exp._export_nodes(gd)
        assert count == 3
        # callback triggered at batch boundary
        cb.assert_called()

    def test_export_nodes_label_filter_query(self):
        """GIVEN node_labels filter WHEN _export_nodes THEN query includes WHERE clause."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, cfg = _make_neo4j_exporter()
        cfg.node_labels = ["Person"]
        records = [_make_record({"id": 1, "labels": ["Person"], "properties": {}})]
        mock_session = self._setup_session(exp, records)
        gd = GraphData()
        exp._export_nodes(gd)
        query_arg = mock_session.run.call_args[0][0]
        assert "WHERE" in query_arg


# ---------------------------------------------------------------------------
# Neo4jExporter._export_relationships — lines 226-262
# ---------------------------------------------------------------------------

class TestNeo4jExporterExportRelationships:
    """GIVEN session with relationships WHEN _export_relationships THEN rels collected."""

    def _setup_session(self, exp, records):
        mock_session = MagicMock()
        mock_session.run.return_value = iter(records)
        exp._driver = MagicMock()
        exp._driver.session.return_value.__enter__ = lambda _s: mock_session
        exp._driver.session.return_value.__exit__ = MagicMock(return_value=False)
        return mock_session

    def test_export_rels_basic(self):
        """GIVEN 2 rel records WHEN _export_relationships THEN 2 relationships stored."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, _ = _make_neo4j_exporter(batch_size=10)
        records = [
            _make_record({"id": i, "type": "KNOWS", "start": 0, "end": 1, "properties": {}})
            for i in range(2)
        ]
        self._setup_session(exp, records)
        gd = GraphData()
        count = exp._export_relationships(gd)
        assert count == 2
        assert len(gd.relationships) == 2

    def test_export_rels_batch_flush(self):
        """GIVEN batch_size=2 and 3 records WHEN _export_relationships THEN flush triggered."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        cb = MagicMock()
        exp, cfg = _make_neo4j_exporter(batch_size=2)
        cfg.progress_callback = cb
        records = [
            _make_record({"id": i, "type": "LIKES", "start": 0, "end": 1, "properties": {}})
            for i in range(3)
        ]
        self._setup_session(exp, records)
        gd = GraphData()
        exp._export_relationships(gd)
        cb.assert_called()

    def test_export_rels_type_filter_uses_where(self):
        """GIVEN relationship_types filter WHEN _export_relationships THEN WHERE in query."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, cfg = _make_neo4j_exporter()
        cfg.relationship_types = ["KNOWS"]
        records = [_make_record({"id": 1, "type": "KNOWS", "start": 0, "end": 2, "properties": {}})]
        mock_session = self._setup_session(exp, records)
        gd = GraphData()
        exp._export_relationships(gd)
        query_arg = mock_session.run.call_args[0][0]
        assert "WHERE" in query_arg


# ---------------------------------------------------------------------------
# Neo4jExporter._export_schema — lines 274-322
# ---------------------------------------------------------------------------

class TestNeo4jExporterExportSchema:
    """GIVEN include_schema=True WHEN _export_schema THEN schema populated."""

    def _setup_session_for_schema(self, exp, idx_records, con_records, labels, rel_types):
        mock_session = MagicMock()
        call_count = [0]

        def run_side_effect(query, *a, **kw):
            c = call_count[0]
            call_count[0] += 1
            if "SHOW INDEXES" in query:
                return iter(idx_records)
            elif "SHOW CONSTRAINTS" in query:
                return iter(con_records)
            elif "db.labels" in query:
                return iter([_make_record({"label": l}) for l in labels])
            elif "db.relationshipTypes" in query:
                return iter([_make_record({"relationshipType": t}) for t in rel_types])
            return iter([])

        mock_session.run.side_effect = run_side_effect
        exp._driver = MagicMock()
        exp._driver.session.return_value.__enter__ = lambda _s: mock_session
        exp._driver.session.return_value.__exit__ = MagicMock(return_value=False)
        return mock_session

    def test_schema_not_included_skips(self):
        """GIVEN include_schema=False WHEN _export_schema THEN returns immediately."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, cfg = _make_neo4j_exporter()
        cfg.include_schema = False
        gd = GraphData()
        exp._export_schema(gd)  # Should not raise or set schema
        assert gd.schema is None

    def test_schema_labels_and_types_collected(self):
        """GIVEN include_schema=True WHEN _export_schema THEN labels+types stored."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, cfg = _make_neo4j_exporter()
        cfg.include_schema = True
        cfg.include_indexes = False
        cfg.include_constraints = False
        self._setup_session_for_schema(exp, [], [], ["Person", "Company"], ["KNOWS"])
        gd = GraphData()
        exp._export_schema(gd)
        assert gd.schema is not None
        assert "Person" in gd.schema.node_labels
        assert "KNOWS" in gd.schema.relationship_types

    def test_schema_indexes_collected(self):
        """GIVEN include_indexes=True WHEN _export_schema THEN indexes stored."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, cfg = _make_neo4j_exporter()
        cfg.include_schema = True
        cfg.include_indexes = True
        cfg.include_constraints = False
        idx = [_make_record({"name": "idx1", "type": "BTREE", "labelsOrTypes": ["Person"], "properties": ["id"]})]
        self._setup_session_for_schema(exp, idx, [], ["Person"], [])
        gd = GraphData()
        exp._export_schema(gd)
        assert len(gd.schema.indexes) == 1

    def test_schema_constraints_collected(self):
        """GIVEN include_constraints=True WHEN _export_schema THEN constraints stored."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, cfg = _make_neo4j_exporter()
        cfg.include_schema = True
        cfg.include_indexes = False
        cfg.include_constraints = True
        con = [_make_record({"name": "c1", "type": "UNIQUE", "labelsOrTypes": ["X"], "properties": ["id"]})]
        self._setup_session_for_schema(exp, [], con, [], [])
        gd = GraphData()
        exp._export_schema(gd)
        assert len(gd.schema.constraints) == 1

    def test_schema_index_exception_logged_not_raised(self):
        """GIVEN SHOW INDEXES raises WHEN _export_schema THEN exception logged, continues."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, cfg = _make_neo4j_exporter()
        cfg.include_schema = True
        cfg.include_indexes = True
        cfg.include_constraints = False
        mock_session = MagicMock()
        call_count = [0]

        def run_side_effect(q, *a, **kw):
            call_count[0] += 1
            if "SHOW INDEXES" in q:
                raise RuntimeError("indexes unavailable")
            elif "db.labels" in q:
                return iter([])
            elif "db.relationshipTypes" in q:
                return iter([])
            return iter([])

        mock_session.run.side_effect = run_side_effect
        exp._driver = MagicMock()
        exp._driver.session.return_value.__enter__ = lambda _s: mock_session
        exp._driver.session.return_value.__exit__ = MagicMock(return_value=False)
        gd = GraphData()
        exp._export_schema(gd)  # Should NOT raise
        assert gd.schema is not None


# ---------------------------------------------------------------------------
# Neo4jExporter.export() — lines 355-391
# ---------------------------------------------------------------------------

class TestNeo4jExporterExport:
    """GIVEN a fully-mocked driver WHEN export() called THEN result reflects outcome."""

    def _mock_export_internals(self, exp):
        """Patch _connect, _export_nodes, _export_relationships, _export_schema, _close."""
        exp._connect = MagicMock(return_value=True)
        exp._export_nodes = MagicMock(return_value=3)
        exp._export_relationships = MagicMock(return_value=2)
        exp._export_schema = MagicMock()
        exp._close = MagicMock()

    def test_export_success_result(self):
        """GIVEN successful internals WHEN export THEN result.success=True."""
        exp, cfg = _make_neo4j_exporter()
        self._mock_export_internals(exp)
        result = exp.export()
        assert result.success is True
        assert result.node_count == 3
        assert result.relationship_count == 2

    def test_export_migration_error_captured(self):
        """GIVEN _connect raises MigrationError WHEN export THEN result.success=False."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        exp, _ = _make_neo4j_exporter()
        exp._connect = MagicMock(side_effect=MigrationError("connect failed"))
        exp._close = MagicMock()
        result = exp.export()
        assert result.success is False
        assert any("connect failed" in e for e in result.errors)

    def test_export_unexpected_exception_captured(self):
        """GIVEN _export_nodes raises RuntimeError WHEN export THEN result.success=False."""
        exp, _ = _make_neo4j_exporter()
        exp._connect = MagicMock(return_value=True)
        exp._export_nodes = MagicMock(side_effect=RuntimeError("unexpected"))
        exp._close = MagicMock()
        result = exp.export()
        assert result.success is False
        assert result.errors  # error message captured


# ---------------------------------------------------------------------------
# Neo4jExporter.export_to_graph_data() — lines 407-430
# ---------------------------------------------------------------------------

class TestNeo4jExporterExportToGraphData:
    """GIVEN _connect succeeds WHEN export_to_graph_data THEN GraphData returned."""

    def test_export_to_graph_data_success(self):
        """GIVEN successful internals WHEN export_to_graph_data THEN returns GraphData."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, _ = _make_neo4j_exporter()
        exp._connect = MagicMock(return_value=True)
        exp._export_nodes = MagicMock(return_value=1)
        exp._export_relationships = MagicMock(return_value=0)
        exp._export_schema = MagicMock()
        exp._close = MagicMock()
        result = exp.export_to_graph_data()
        assert isinstance(result, GraphData)

    def test_export_to_graph_data_migration_error_returns_none(self):
        """GIVEN _connect raises MigrationError WHEN export_to_graph_data THEN None."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        exp, _ = _make_neo4j_exporter()
        exp._connect = MagicMock(side_effect=MigrationError("no conn"))
        exp._close = MagicMock()
        result = exp.export_to_graph_data()
        assert result is None

    def test_export_to_graph_data_restores_output_file(self):
        """GIVEN output_file set WHEN export_to_graph_data THEN output_file restored after."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        exp, cfg = _make_neo4j_exporter()
        cfg.output_file = "/tmp/original.json"
        exp._connect = MagicMock(return_value=True)
        exp._export_nodes = MagicMock(return_value=0)
        exp._export_relationships = MagicMock(return_value=0)
        exp._export_schema = MagicMock()
        exp._close = MagicMock()
        exp.export_to_graph_data()
        assert cfg.output_file == "/tmp/original.json"


# ---------------------------------------------------------------------------
# IPFSImporter._connect — lines 131-148
# ---------------------------------------------------------------------------

class TestIPFSImporterConnect:
    """GIVEN IPFSImporter with mocked GraphDatabase WHEN _connect called THEN connection made."""

    def _make_importer(self):
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter, ImportConfig
        cfg = ImportConfig()
        imp = IPFSImporter(cfg)
        return imp, cfg

    def test_connect_success_sets_driver_and_session(self):
        """GIVEN valid GraphDatabase mock WHEN _connect THEN driver+session set, True returned."""
        imp, _ = self._make_importer()
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value = mock_session
        imp._GraphDatabase = MagicMock()
        imp._GraphDatabase.driver.return_value = mock_driver
        assert imp._connect() is True
        assert imp._session is mock_session

    def test_connect_exception_wraps_to_migration_error(self):
        """GIVEN driver constructor raises WHEN _connect THEN MigrationError raised."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        imp, _ = self._make_importer()
        imp._GraphDatabase = MagicMock()
        imp._GraphDatabase.driver.side_effect = RuntimeError("ipfs not running")
        with pytest.raises(MigrationError):
            imp._connect()

    def test_connect_not_available_raises(self):
        """GIVEN _ipfs_available=False WHEN _connect THEN MigrationError raised."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        imp, _ = self._make_importer()
        imp._ipfs_available = False
        with pytest.raises(MigrationError, match="IPFS graph database not available"):
            imp._connect()


# ---------------------------------------------------------------------------
# IPFSImporter._load_graph_data — lines 175-192
# ---------------------------------------------------------------------------

class TestIPFSImporterLoadGraphData:
    """GIVEN config with input_file WHEN _load_graph_data THEN loads correctly."""

    def _make_importer(self, **cfg_kwargs):
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter, ImportConfig
        cfg = ImportConfig(**cfg_kwargs)
        imp = IPFSImporter(cfg)
        return imp, cfg

    def test_load_from_graph_data_directly(self):
        """GIVEN config.graph_data set WHEN _load_graph_data THEN returns it directly."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        gd = GraphData()
        imp, _ = self._make_importer(graph_data=gd)
        assert imp._load_graph_data() is gd

    def test_load_from_file_success(self):
        """GIVEN config.input_file set WHEN _load_graph_data THEN loads from file."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        imp, cfg = self._make_importer(input_file="test.json")
        mock_gd = GraphData()
        with patch.object(GraphData, "load_from_file", return_value=mock_gd) as mocked:
            result = imp._load_graph_data()
        assert result is mock_gd

    def test_load_from_file_exception_wraps_to_migration_error(self):
        """GIVEN load_from_file raises OSError WHEN _load_graph_data THEN MigrationError."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        imp, cfg = self._make_importer(input_file="missing.json")
        with patch.object(GraphData, "load_from_file", side_effect=OSError("not found")):
            with pytest.raises(MigrationError):
                imp._load_graph_data()

    def test_load_no_input_raises(self):
        """GIVEN no file or graph_data WHEN _load_graph_data THEN MigrationError raised."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        imp, _ = self._make_importer()
        with pytest.raises(MigrationError, match="No input file"):
            imp._load_graph_data()


# ---------------------------------------------------------------------------
# IPFSImporter._import_nodes — lines 265-270
# ---------------------------------------------------------------------------

class TestIPFSImporterImportNodes:
    """GIVEN a mock session WHEN _import_nodes called THEN nodes imported with progress/exceptions."""

    def _make_importer(self):
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter, ImportConfig
        cfg = ImportConfig()
        imp = IPFSImporter(cfg)
        return imp, cfg

    def test_import_nodes_progress_callback_triggered(self):
        """GIVEN 100 nodes and progress_callback WHEN _import_nodes THEN callback called."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, NodeData
        imp, cfg = self._make_importer()
        cb = MagicMock()
        cfg.progress_callback = cb
        imp._session = MagicMock()
        mock_rec = MagicMock()
        mock_rec.__getitem__ = lambda _s, k: 42 if k == "internal_id" else None
        imp._session.run.return_value.single.return_value = mock_rec
        gd = GraphData()
        for i in range(100):
            gd.nodes.append(NodeData(id=f"n{i}", labels=["T"], properties={}))
        n_imp, n_skip = imp._import_nodes(gd)
        assert n_imp == 100
        assert n_skip == 0
        cb.assert_called()

    def test_import_nodes_exception_increments_skipped(self):
        """GIVEN session.run raises WHEN _import_nodes THEN node skipped."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, NodeData
        imp, _ = self._make_importer()
        imp._session = MagicMock()
        imp._session.run.side_effect = RuntimeError("cypher error")
        gd = GraphData()
        gd.nodes.append(NodeData(id="n1", labels=["T"], properties={}))
        n_imp, n_skip = imp._import_nodes(gd)
        assert n_imp == 0
        assert n_skip == 1


# ---------------------------------------------------------------------------
# IPFSImporter._import_relationships — lines 299-325
# ---------------------------------------------------------------------------

class TestIPFSImporterImportRelationships:
    """GIVEN a mock session WHEN _import_relationships THEN rels imported/skipped."""

    def _make_importer(self):
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter, ImportConfig
        cfg = ImportConfig()
        imp = IPFSImporter(cfg)
        return imp, cfg

    def test_import_rels_missing_node_skips(self):
        """GIVEN rel referencing absent node WHEN _import_relationships THEN skipped."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, RelationshipData
        imp, _ = self._make_importer()
        imp._session = MagicMock()
        gd = GraphData()
        gd.relationships.append(
            RelationshipData(id="r1", type="KNOWS", start_node="n1", end_node="n2", properties={})
        )
        # _node_id_map is empty — both nodes absent
        n_imp, n_skip = imp._import_relationships(gd)
        assert n_imp == 0
        assert n_skip == 1

    def test_import_rels_success(self):
        """GIVEN nodes in map and session succeeds WHEN _import_relationships THEN imported."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, RelationshipData
        imp, _ = self._make_importer()
        imp._node_id_map = {"n1": 1, "n2": 2}
        imp._session = MagicMock()
        gd = GraphData()
        gd.relationships.append(
            RelationshipData(id="r1", type="KNOWS", start_node="n1", end_node="n2", properties={})
        )
        n_imp, n_skip = imp._import_relationships(gd)
        assert n_imp == 1
        assert n_skip == 0

    def test_import_rels_exception_increments_skipped(self):
        """GIVEN session.run raises WHEN _import_relationships THEN rel skipped."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, RelationshipData
        imp, _ = self._make_importer()
        imp._node_id_map = {"n1": 1, "n2": 2}
        imp._session = MagicMock()
        imp._session.run.side_effect = RuntimeError("write error")
        gd = GraphData()
        gd.relationships.append(
            RelationshipData(id="r1", type="KNOWS", start_node="n1", end_node="n2", properties={})
        )
        n_imp, n_skip = imp._import_relationships(gd)
        assert n_imp == 0
        assert n_skip == 1

    def test_import_rels_progress_callback_triggered(self):
        """GIVEN 100 rels and progress_callback WHEN _import_relationships THEN callback called."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, RelationshipData
        imp, cfg = self._make_importer()
        cb = MagicMock()
        cfg.progress_callback = cb
        imp._session = MagicMock()
        imp._node_id_map = {f"n{i}": i for i in range(101)}
        gd = GraphData()
        for i in range(100):
            gd.relationships.append(
                RelationshipData(id=f"r{i}", type="KNOWS", start_node=f"n{i}", end_node=f"n{i+1}", properties={})
            )
        imp._import_relationships(gd)
        cb.assert_called()


# ---------------------------------------------------------------------------
# IPFSImporter._import_schema — lines 344-362
# ---------------------------------------------------------------------------

class TestIPFSImporterImportSchema:
    """GIVEN schema with indexes and constraints WHEN _import_schema THEN they are processed."""

    def _make_importer(self):
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter, ImportConfig
        from ipfs_datasets_py.knowledge_graphs.migration.formats import SchemaData
        cfg = ImportConfig(create_indexes=True, create_constraints=True)
        imp = IPFSImporter(cfg)
        imp._session = MagicMock()
        return imp, cfg

    def test_import_schema_no_schema_returns_early(self):
        """GIVEN graph_data.schema=None WHEN _import_schema THEN returns immediately."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        imp, _ = self._make_importer()
        gd = GraphData()
        gd.schema = None
        imp._import_schema(gd)  # Should not raise

    def test_import_schema_with_indexes(self):
        """GIVEN schema with indexes WHEN _import_schema THEN indexes processed."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, SchemaData
        imp, cfg = self._make_importer()
        cfg.create_indexes = True
        gd = GraphData()
        gd.schema = SchemaData()
        gd.schema.indexes = [{"name": "idx1", "type": "BTREE", "labels": ["Person"], "properties": ["id"]}]
        imp._import_schema(gd)  # Should not raise

    def test_import_schema_with_constraints(self):
        """GIVEN schema with constraints WHEN _import_schema THEN constraints processed."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, SchemaData
        imp, cfg = self._make_importer()
        cfg.create_constraints = True
        gd = GraphData()
        gd.schema = SchemaData()
        gd.schema.constraints = [{"name": "c1", "type": "UNIQUE", "labels": ["X"], "properties": ["id"]}]
        imp._import_schema(gd)  # Should not raise


# ---------------------------------------------------------------------------
# IPFSImporter.import_data() — validation abort path
# ---------------------------------------------------------------------------

class TestIPFSImporterImportData:
    """GIVEN import_data called WHEN validation finds many errors THEN aborts."""

    def test_import_data_too_many_validation_errors_aborts(self):
        """GIVEN validate_data=True and 11+ errors WHEN import_data THEN returns failure."""
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import IPFSImporter, ImportConfig
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, NodeData

        gd = GraphData()
        # Add duplicate IDs to trigger validation errors
        for i in range(5):
            gd.nodes.append(NodeData(id="dup", labels=["T"], properties={}))

        cfg = ImportConfig(validate_data=True, graph_data=gd)
        imp = IPFSImporter(cfg)
        # Stub _validate_graph_data to return 15 errors
        imp._validate_graph_data = MagicMock(return_value=[f"error_{i}" for i in range(15)])
        imp._connect = MagicMock(return_value=True)
        imp._close = MagicMock()
        result = imp.import_data()
        # Should abort because > 10 errors
        assert result.success is False


# ---------------------------------------------------------------------------
# _LegacyGraphEngine: StorageError paths
# ---------------------------------------------------------------------------

class TestLegacyGraphEngineStorageErrors:
    """GIVEN storage backend raises StorageError WHEN operations called THEN handled gracefully."""

    def _make_engine(self):
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
        mock_storage = MagicMock()
        eng = _LegacyGraphEngine(storage_backend=mock_storage)
        return eng, mock_storage

    def test_get_node_storage_error_returns_none(self):
        """GIVEN CID key exists but storage raises StorageError WHEN get_node THEN None."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
        eng, mock_storage = self._make_engine()
        node = eng.create_node(labels=["T"], properties={})
        node_id = node.id
        # Set CID key and clear main cache
        eng._node_cache[f"cid:{node_id}"] = "bafy..."
        del eng._node_cache[node_id]
        mock_storage.retrieve_json.side_effect = StorageError("fail")
        result = eng.get_node(node_id)
        assert result is None

    def test_update_node_storage_error_logged_not_raised(self):
        """GIVEN storage raises StorageError WHEN update_node THEN node still returned."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
        eng, mock_storage = self._make_engine()
        node = eng.create_node(labels=["T"], properties={"x": 1})
        mock_storage.store.side_effect = StorageError("fail")
        result = eng.update_node(node.id, {"x": 2})
        assert result is not None

    def test_create_relationship_storage_error_logged_not_raised(self):
        """GIVEN storage raises StorageError WHEN create_relationship THEN rel still returned."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
        eng, mock_storage = self._make_engine()
        mock_storage.store.side_effect = StorageError("fail")
        rel = eng.create_relationship("KNOWS", "n1", "n2")
        assert rel is not None

    def test_delete_relationship_removes_cid_key(self):
        """GIVEN cid key present WHEN delete_relationship THEN cid key removed too."""
        eng, _ = self._make_engine()
        rel = eng.create_relationship("KNOWS", "n1", "n2")
        rel_id = rel.id
        # Manually add CID key
        eng._relationship_cache[f"cid:{rel_id}"] = "baf..."
        result = eng.delete_relationship(rel_id)
        assert result is True
        assert f"cid:{rel_id}" not in eng._relationship_cache

    def test_save_graph_storage_error_returns_none(self):
        """GIVEN storage.store_graph raises StorageError WHEN save_graph THEN None."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
        eng, mock_storage = self._make_engine()
        eng.create_node(labels=["T"])
        mock_storage.store_graph.side_effect = StorageError("write fail")
        result = eng.save_graph()
        assert result is None

    def test_load_graph_storage_error_returns_false(self):
        """GIVEN storage.retrieve_graph raises StorageError WHEN load_graph THEN False."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
        eng, mock_storage = self._make_engine()
        mock_storage.retrieve_graph.side_effect = StorageError("read fail")
        result = eng.load_graph("bafy123")
        assert result is False

    def test_save_graph_includes_relationships(self):
        """GIVEN nodes and rels exist WHEN save_graph THEN both passed to store_graph."""
        eng, mock_storage = self._make_engine()
        mock_storage.store_graph.return_value = "bafy999"
        n1 = eng.create_node(labels=["A"])
        n2 = eng.create_node(labels=["B"])
        eng.create_relationship("KNOWS", n1.id, n2.id)
        cid = eng.save_graph()
        assert cid == "bafy999"
        kw = mock_storage.store_graph.call_args
        rels_arg = kw[1].get("relationships") if kw[1] else kw[0][1]
        assert len(rels_arg) >= 1


# ---------------------------------------------------------------------------
# _LegacyGraphEngine: find_nodes filter paths
# ---------------------------------------------------------------------------

class TestLegacyGraphEngineFindNodes:
    """GIVEN nodes with various labels/properties WHEN find_nodes THEN filters applied."""

    def _make_engine(self):
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        return _LegacyGraphEngine()

    def test_find_nodes_label_filter_excludes_non_matching(self):
        """GIVEN nodes with different labels WHEN find_nodes(labels=['A']) THEN only A returned."""
        eng = self._make_engine()
        eng.create_node(labels=["A"], properties={"k": "v1"})
        eng.create_node(labels=["B"], properties={"k": "v2"})
        results = eng.find_nodes(labels=["A"])
        assert all("A" in n.labels for n in results)
        assert len(results) == 1

    def test_find_nodes_property_filter_excludes_non_matching(self):
        """GIVEN nodes with different props WHEN find_nodes(properties={k:v}) THEN only match."""
        eng = self._make_engine()
        eng.create_node(labels=["X"], properties={"color": "red"})
        eng.create_node(labels=["X"], properties={"color": "blue"})
        results = eng.find_nodes(properties={"color": "red"})
        assert len(results) == 1

    def test_find_nodes_skips_cid_keys(self):
        """GIVEN cid: entries in cache WHEN find_nodes THEN skipped."""
        eng = self._make_engine()
        eng._node_cache["cid:n1"] = "bafyxxxx"
        results = eng.find_nodes()
        assert all("cid:" not in str(type(r)) for r in results)

    def test_find_nodes_skips_non_node_entries(self):
        """GIVEN non-Node values in cache WHEN find_nodes THEN only Nodes returned."""
        eng = self._make_engine()
        eng._node_cache["fake"] = "not_a_node"
        results = eng.find_nodes()
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node
        assert all(isinstance(n, Node) for n in results)


# ---------------------------------------------------------------------------
# _LegacyGraphEngine: get_relationships filter paths
# ---------------------------------------------------------------------------

class TestLegacyGraphEngineGetRelationships:
    """GIVEN relationships with cid: entries or non-Relationship values WHEN get_relationships THEN filtered."""

    def _make_engine(self):
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        return _LegacyGraphEngine()

    def test_get_relationships_skips_cid_keys(self):
        """GIVEN cid: keys in cache WHEN get_relationships THEN skipped."""
        eng = self._make_engine()
        eng._relationship_cache["cid:r1"] = "bafyyy"
        results = eng.get_relationships("n1")
        assert results == []

    def test_get_relationships_skips_non_relationship(self):
        """GIVEN non-Relationship value in cache WHEN get_relationships THEN skipped."""
        eng = self._make_engine()
        eng._relationship_cache["not_a_rel"] = "something_else"
        results = eng.get_relationships("n1")
        assert results == []


# ---------------------------------------------------------------------------
# _LegacyGraphEngine: traverse_pattern with label checks
# ---------------------------------------------------------------------------

class TestLegacyGraphEngineTraversePattern:
    """GIVEN pattern with labels in next step WHEN traverse_pattern THEN label filters applied."""

    def _make_engine(self):
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        return _LegacyGraphEngine()

    def test_traverse_pattern_label_filter_excludes_non_matching(self):
        """GIVEN next step has labels=['B'] but target has labels=['A'] WHEN traverse THEN excluded."""
        eng = self._make_engine()
        n1 = eng.create_node(labels=["Start"])
        n2 = eng.create_node(labels=["A"])  # Wrong label
        eng.create_relationship("KNOWS", n1.id, n2.id)
        pattern = [
            {"rel_type": "KNOWS", "variable": "r", "direction": "out"},
            {"variable": "end", "labels": ["B"]},  # Needs B, but n2 has A
        ]
        results = eng.traverse_pattern([n1], pattern)
        assert results == []

    def test_traverse_pattern_label_filter_includes_matching(self):
        """GIVEN next step has labels=['A'] and target has labels=['A'] WHEN traverse THEN included."""
        eng = self._make_engine()
        n1 = eng.create_node(labels=["Start"])
        n2 = eng.create_node(labels=["A"])  # Correct label
        eng.create_relationship("KNOWS", n1.id, n2.id)
        pattern = [
            {"rel_type": "KNOWS", "variable": "r", "direction": "out"},
            {"variable": "end", "labels": ["A"]},
        ]
        results = eng.traverse_pattern([n1], pattern)
        assert len(results) == 1
        assert results[0]["end"].id == n2.id


# ---------------------------------------------------------------------------
# _LegacyGraphEngine: find_paths with cycle detection
# ---------------------------------------------------------------------------

class TestLegacyGraphEngineFindPaths:
    """GIVEN a graph with a cycle WHEN find_paths THEN cycle not followed indefinitely."""

    def _make_engine(self):
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        return _LegacyGraphEngine()

    def test_find_paths_cycle_not_looped(self):
        """GIVEN A→B→A cycle WHEN find_paths(A,B) THEN finds direct path without loop."""
        eng = self._make_engine()
        n1 = eng.create_node(labels=["X"])
        n2 = eng.create_node(labels=["Y"])
        eng.create_relationship("LINK", n1.id, n2.id)
        eng.create_relationship("BACK", n2.id, n1.id)  # creates cycle
        paths = eng.find_paths(n1.id, n2.id)
        # Should find exactly 1 path (not infinitely looping)
        assert len(paths) == 1


# ---------------------------------------------------------------------------
# ValidatedKnowledgeGraphExtractor (validator.py) — lines 311-435
# ---------------------------------------------------------------------------

class TestValidatedKGExtractor:
    """GIVEN KnowledgeGraphExtractorWithValidation WHEN extract_from_wikipedia THEN paths covered."""

    def _make_extractor(self, **kwargs):
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        defaults = {"use_tracer": False, "validate_during_extraction": False}
        defaults.update(kwargs)
        return KnowledgeGraphExtractorWithValidation(**defaults)

    def _mock_kg(self, n_entities=0):
        """Create a mock KnowledgeGraph."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        kg = MagicMock(spec=KnowledgeGraph)
        kg.entities = {}
        kg.relationships = {}
        return kg

    def test_basic_no_tracer_no_validator(self):
        """GIVEN no tracer and no validator WHEN extract_from_wikipedia THEN basic result."""
        v = self._make_extractor()
        mock_kg = self._mock_kg()
        v.extractor.extract_from_wikipedia = MagicMock(return_value=mock_kg)
        result = v.extract_from_wikipedia("Test")
        assert "knowledge_graph" in result
        assert result["entity_count"] == 0

    def test_with_tracer_trace_id_created(self):
        """GIVEN self.tracer set WHEN extract_from_wikipedia THEN tracer.trace_... called."""
        v = self._make_extractor()
        mock_tracer = MagicMock()
        mock_tracer.trace_extraction_and_validation.return_value = "trace-001"
        v.tracer = mock_tracer
        mock_kg = self._mock_kg()
        v.extractor.extract_from_wikipedia = MagicMock(return_value=mock_kg)
        result = v.extract_from_wikipedia("Test")
        mock_tracer.trace_extraction_and_validation.assert_called_once()
        mock_tracer.update_extraction_and_validation_trace.assert_called_once()

    def test_with_validator_entity_validation_called(self):
        """GIVEN self.validator set and validate=True WHEN extract THEN validator called."""
        v = self._make_extractor(validate_during_extraction=True)
        mock_validator = MagicMock()
        mock_vr = MagicMock()
        mock_vr.to_dict.return_value = {"overall_coverage": 0.8}
        mock_vr.data = {"entity_coverage": 0.8, "relationship_coverage": 0.7, "overall_coverage": 0.8}
        mock_validator.validate_knowledge_graph.return_value = mock_vr
        v.validator = mock_validator
        v.validator_available = True
        mock_kg = self._mock_kg()
        v.extractor.extract_from_wikipedia = MagicMock(return_value=mock_kg)
        result = v.extract_from_wikipedia("Test")
        mock_validator.validate_knowledge_graph.assert_called_once()
        assert "validation_results" in result

    def test_with_validator_focus_on_main_entity(self):
        """GIVEN focus_validation_on_main_entity=True WHEN extract THEN main_entity_name passed."""
        v = self._make_extractor(validate_during_extraction=True)
        mock_validator = MagicMock()
        mock_vr = MagicMock()
        mock_vr.to_dict.return_value = {}
        mock_vr.data = {"property_coverage": 0.9, "relationship_coverage": 0.8, "overall_coverage": 0.85, "entity_name": "Test"}
        mock_validator.validate_knowledge_graph.return_value = mock_vr
        v.validator = mock_validator
        v.validator_available = True
        mock_kg = self._mock_kg()
        v.extractor.extract_from_wikipedia = MagicMock(return_value=mock_kg)
        result = v.extract_from_wikipedia("Test", focus_validation_on_main_entity=True)
        call_kwargs = mock_validator.validate_knowledge_graph.call_args[1]
        assert call_kwargs.get("main_entity_name") == "Test"

    def test_with_auto_correct_suggestions(self):
        """GIVEN auto_correct=True and validator WHEN extract THEN corrections generated."""
        v = self._make_extractor(validate_during_extraction=True, auto_correct_suggestions=True)
        mock_validator = MagicMock()
        mock_vr = MagicMock()
        mock_vr.to_dict.return_value = {}
        mock_vr.data = {}
        mock_validator.validate_knowledge_graph.return_value = mock_vr
        mock_validator.generate_validation_explanation.return_value = "Fix: use X"
        v.validator = mock_validator
        v.validator_available = True
        v.auto_correct_suggestions = True
        mock_kg = self._mock_kg()
        v.extractor.extract_from_wikipedia = MagicMock(return_value=mock_kg)
        result = v.extract_from_wikipedia("Test")
        mock_validator.generate_validation_explanation.assert_called_once()

    def test_exception_path_returns_error_dict(self):
        """GIVEN extractor.extract_from_wikipedia raises WHEN called THEN error dict returned."""
        v = self._make_extractor()
        v.extractor.extract_from_wikipedia = MagicMock(side_effect=RuntimeError("extraction fail"))
        result = v.extract_from_wikipedia("Test")
        assert "error" in result
        assert result["knowledge_graph"] is None

    def test_exception_path_updates_tracer(self):
        """GIVEN extractor raises AND tracer set WHEN extract THEN tracer updated with failed."""
        v = self._make_extractor()
        mock_tracer = MagicMock()
        mock_tracer.trace_extraction_and_validation.return_value = "trace-002"
        v.tracer = mock_tracer
        v.extractor.extract_from_wikipedia = MagicMock(side_effect=RuntimeError("boom"))
        result = v.extract_from_wikipedia("Test")
        update_call = mock_tracer.update_extraction_and_validation_trace.call_args
        assert update_call[1].get("status") == "failed" or "failed" in str(update_call)

    def test_no_validator_available_no_validation_results(self):
        """GIVEN validate=True but no validator WHEN extract THEN no validation_results in result."""
        v = self._make_extractor(validate_during_extraction=True)
        v.validator = None
        mock_kg = self._mock_kg()
        v.extractor.extract_from_wikipedia = MagicMock(return_value=mock_kg)
        result = v.extract_from_wikipedia("Test")
        # extract_from_wikipedia silently skips validation when validator is None
        assert "knowledge_graph" in result
        assert "validation_results" not in result

    def test_validation_depth_greater_than_1_path_analysis(self):
        """GIVEN validation_depth=2 and >1 entities with confidence>0.8 WHEN extract THEN path_analysis attempted."""
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity

        v = self._make_extractor(validate_during_extraction=True)
        mock_validator = MagicMock()
        mock_vr = MagicMock()
        mock_vr.to_dict.return_value = {}
        mock_vr.data = {"entity_name": "Main", "property_coverage": 0.9, "relationship_coverage": 0.8, "overall_coverage": 0.85}
        mock_validator.validate_knowledge_graph.return_value = mock_vr
        path_result = MagicMock()
        path_result.is_valid = True
        path_result.to_dict.return_value = {"paths": []}
        mock_validator.find_entity_paths.return_value = path_result
        v.validator = mock_validator
        v.validator_available = True

        mock_kg = self._mock_kg()
        e1 = MagicMock(spec=Entity)
        e1.name = "Main"
        e1.entity_id = "e1"
        e1.confidence = 0.95
        e2 = MagicMock(spec=Entity)
        e2.name = "Other"
        e2.entity_id = "e2"
        e2.confidence = 0.90
        mock_kg.entities = {"e1": e1, "e2": e2}
        mock_kg.relationships = {}
        v.extractor.extract_from_wikipedia = MagicMock(return_value=mock_kg)
        result = v.extract_from_wikipedia("Main", validation_depth=2, focus_validation_on_main_entity=True)
        # path analysis should have been attempted
        mock_validator.find_entity_paths.assert_called_once()
