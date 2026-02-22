"""
Session 40 — knowledge_graphs coverage push.

Targets (deps now installed: libipld, ipld-car, multiformats, dag-cbor, plotly):
  migration/formats.py       lines 914, 921-930, 950-951  (_builtin_save_car /
                              _builtin_load_car with real libraries)
  migration/neo4j_exporter.py lines 309-310  (exception in _export_schema
                              SHOW CONSTRAINTS block)
  extraction/_wikipedia_helpers.py line 424  (update_validation_trace in
                              ValueError/KeyError except branch)
  (lineage/visualization.py line 28 now auto-covered: plotly installed)

GIVEN-WHEN-THEN style, consistent with existing session test files.
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# A – _builtin_save_car / _builtin_load_car (real deps, lines 914, 921-930,
#     950-951 in formats.py)
# ---------------------------------------------------------------------------

class TestBuiltinCarSaveLoad:
    """Test CAR format save/load with all real deps (libipld, ipld_car, multiformats)."""

    def _simple_graph(self):
        """Build a minimal GraphData with one node for round-trip tests."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData,
            NodeData,
        )
        node = NodeData(id="n1", labels=["Person"], properties={"name": "Alice", "age": 30})
        return GraphData(nodes=[node], relationships=[], schema=None)

    def test_save_car_covers_real_encode_path(self, tmp_path):
        """
        GIVEN libipld, ipld_car, multiformats are installed
        WHEN _builtin_save_car is called
        THEN it writes a non-empty .car file (lines 914, 921-930 executed)
        """
        from ipfs_datasets_py.knowledge_graphs.migration.formats import _builtin_save_car
        filepath = str(tmp_path / "test.car")
        graph = self._simple_graph()

        _builtin_save_car(graph, filepath)

        assert os.path.exists(filepath)
        assert os.path.getsize(filepath) > 0

    def test_load_car_round_trip(self, tmp_path):
        """
        GIVEN a .car file written by _builtin_save_car
        WHEN _builtin_load_car is called
        THEN the loaded GraphData round-trips the original node (lines 950-951)
        """
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            _builtin_load_car,
            _builtin_save_car,
        )
        filepath = str(tmp_path / "roundtrip.car")
        graph = self._simple_graph()

        _builtin_save_car(graph, filepath)
        loaded = _builtin_load_car(filepath)

        assert len(loaded.nodes) == 1
        assert loaded.nodes[0].id == "n1"
        assert loaded.nodes[0].properties["name"] == "Alice"

    def test_save_car_no_libipld_raises_import_error(self):
        """
        GIVEN libipld is absent (patched out)
        WHEN _builtin_save_car is called
        THEN ImportError with helpful message is raised
        """
        from ipfs_datasets_py.knowledge_graphs.migration.formats import _builtin_save_car
        graph = self._simple_graph()

        fake_import = types.ModuleType("libipld")
        original = sys.modules.get("libipld")
        try:
            # Simulate import failure by temporarily blocking the import
            sys.modules["libipld"] = None  # type: ignore[assignment]
            with pytest.raises(ImportError, match="libipld"):
                _builtin_save_car(graph, "/tmp/should_not_exist.car")
        finally:
            if original is None:
                sys.modules.pop("libipld", None)
            else:
                sys.modules["libipld"] = original

    def test_load_car_with_empty_blocks_falls_through_to_ipld_car(self, tmp_path):
        """
        GIVEN libipld.decode_car returns empty blocks dict
        WHEN _builtin_load_car is called
        THEN it falls through and tries ipld_car path
        """
        from ipfs_datasets_py.knowledge_graphs.migration.formats import _builtin_load_car

        # Write some bytes to a temp file
        filepath = str(tmp_path / "empty_blocks.car")
        with open(filepath, "wb") as f:
            f.write(b"\x00" * 16)  # arbitrary bytes

        mock_libipld = MagicMock()
        mock_libipld.decode_car.return_value = ({}, {})  # empty blocks

        with patch.dict(sys.modules, {"libipld": mock_libipld}):
            with pytest.raises(Exception):
                # Will raise either ValueError("no blocks") or ImportError/etc.
                # The key is that libipld.decode_car was called and we fell through.
                _builtin_load_car(filepath)

        mock_libipld.decode_car.assert_called_once()


# ---------------------------------------------------------------------------
# B – neo4j_exporter._export_schema exception on SHOW CONSTRAINTS (lines 309-310)
# ---------------------------------------------------------------------------

class TestNeo4jExporterConstraintException:
    """Test _export_schema exception handling in SHOW CONSTRAINTS block."""

    def _make_exporter(self):
        """Build a Neo4jExporter with fully mocked neo4j module."""
        mock_neo4j = MagicMock()
        mock_driver = MagicMock()
        mock_neo4j.GraphDatabase.driver.return_value = mock_driver

        with patch.dict(sys.modules, {"neo4j": mock_neo4j}):
            from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
                ExportConfig,
                Neo4jExporter,
            )
            config = ExportConfig(
                include_schema=True,
                include_indexes=False,
                include_constraints=True,
            )
            exporter = Neo4jExporter.__new__(Neo4jExporter)
            exporter.config = config
            exporter._GraphDatabase = mock_neo4j.GraphDatabase
            exporter._driver = mock_driver

        return exporter, mock_driver

    def test_export_schema_exception_on_show_constraints_logged_as_warning(self):
        """
        GIVEN _export_schema is called and SHOW CONSTRAINTS raises RuntimeError
        WHEN _export_schema executes
        THEN the exception is caught and logged (lines 309-310 executed), no re-raise
        """
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData

        exporter, mock_driver = self._make_exporter()

        # Build a session mock where SHOW CONSTRAINTS raises RuntimeError
        mock_session = MagicMock()

        def run_side_effect(query, **kwargs):
            if "CONSTRAINTS" in query.upper():
                raise RuntimeError("constraints not supported in this edition")
            # For db.labels() and db.relationshipTypes()
            mock_result = MagicMock()
            mock_result.__iter__ = lambda self: iter([])
            return mock_result

        mock_session.run.side_effect = run_side_effect
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver.session.return_value = mock_session

        graph_data = GraphData(nodes=[], relationships=[], schema=None)

        import logging
        with patch("ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter.logger") as mock_log:
            exporter._export_schema(graph_data)

        # Line 310: logger.warning should have been called with constraint-related message
        warning_calls = [str(c) for c in mock_log.warning.call_args_list]
        assert any("constraint" in c.lower() or "Constraint" in c for c in warning_calls)

    def test_export_schema_constraint_exception_does_not_reraise(self):
        """
        GIVEN SHOW CONSTRAINTS raises an error
        WHEN _export_schema executes
        THEN no exception propagates to the caller
        """
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData

        exporter, mock_driver = self._make_exporter()

        mock_session = MagicMock()

        def run_side_effect(query, **kwargs):
            if "CONSTRAINTS" in query.upper():
                raise ValueError("unexpected constraint error")
            result = MagicMock()
            result.__iter__ = lambda s: iter([])
            return result

        mock_session.run.side_effect = run_side_effect
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_driver.session.return_value = mock_session

        graph_data = GraphData(nodes=[], relationships=[], schema=None)

        # Should NOT raise — exception is swallowed at lines 309-310
        exporter._export_schema(graph_data)


# ---------------------------------------------------------------------------
# C – _wikipedia_helpers.validate_against_wikidata line 424
#     (update_validation_trace in ValueError/KeyError except branch)
# ---------------------------------------------------------------------------

class TestWikipediaValidateTracerOnValueError:
    """Test that validate_against_wikidata calls tracer.update_validation_trace on ValueError."""

    def _make_extractor_with_tracer(self):
        """Build a KnowledgeGraphExtractor with mocked tracer."""
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        extractor = KnowledgeGraphExtractor(use_tracer=False)
        extractor.use_tracer = True
        extractor.tracer = MagicMock()
        extractor.tracer.trace_validation.return_value = "trace-123"
        return extractor

    def test_update_validation_trace_called_on_key_error(self):
        """
        GIVEN validate_against_wikidata is called and _get_wikidata_id raises KeyError
        WHEN the except (ValueError, KeyError, ...) branch executes
        THEN tracer.update_validation_trace is called (line 424)
        """
        extractor = self._make_extractor_with_tracer()

        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.name = "test-kg"

        # Patch _get_wikidata_id to raise KeyError (caught at line 412)
        with patch.object(
            extractor, "_get_wikidata_id", side_effect=KeyError("wikidata_id missing")
        ):
            with pytest.raises(Exception):
                extractor.validate_against_wikidata(kg, "Alice")

        # Line 424: tracer.update_validation_trace must have been called
        extractor.tracer.update_validation_trace.assert_called_once()
        call_kwargs = extractor.tracer.update_validation_trace.call_args[1]
        assert call_kwargs["trace_id"] == "trace-123"
        assert call_kwargs["status"] == "failed"

    def test_update_validation_trace_called_on_value_error(self):
        """
        GIVEN _get_wikidata_statements raises ValueError
        WHEN the except branch executes
        THEN tracer.update_validation_trace is called with status='failed' (line 424)
        """
        extractor = self._make_extractor_with_tracer()

        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import Entity
        kg = KnowledgeGraph()
        kg.name = "test-kg"
        e = Entity(entity_id="e1", entity_type="person", name="Alice")
        kg.entities["e1"] = e

        with patch.object(extractor, "_get_wikidata_id", return_value="Q123"), \
             patch.object(
                 extractor, "_get_wikidata_statements",
                 side_effect=ValueError("malformed response")
             ):
            with pytest.raises(Exception):
                extractor.validate_against_wikidata(kg, "Alice")

        extractor.tracer.update_validation_trace.assert_called_once()

    def test_validate_against_wikidata_no_tracer_no_trace_id(self):
        """
        GIVEN use_tracer is False (trace_id remains None)
        WHEN _get_wikidata_id raises KeyError
        THEN update_validation_trace is NOT called (line 423 guard fails)
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        extractor = KnowledgeGraphExtractor(use_tracer=False)
        mock_tracer = MagicMock()
        extractor.tracer = mock_tracer  # tracer set but use_tracer=False

        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.name = "test-kg"

        with patch.object(extractor, "_get_wikidata_id", side_effect=KeyError("nope")):
            with pytest.raises(Exception):
                extractor.validate_against_wikidata(kg, "Alice")

        mock_tracer.update_validation_trace.assert_not_called()
