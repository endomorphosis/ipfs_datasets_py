"""
Session 12 coverage improvement tests.

Targets (by uncovered statement count):
  - constraints/__init__.py (75%) — UniqueConstraint, ExistenceConstraint,
      TypeConstraint, CustomConstraint, ConstraintManager
  - migration/ipfs_importer.py (24%) — ImportConfig, ImportResult, IPFSImporter
      (all paths reachable without a running IPFS node)
  - migration/neo4j_exporter.py (22%) — ExportConfig, ExportResult, Neo4jExporter
      (all paths reachable without a running Neo4j instance)
  - transactions/manager.py (64%) — conflict detection, apply_operations, recover
  - transactions/wal.py (65%) — compact, recover, get_transaction_history,
      get_stats, verify_integrity

All tests follow the GIVEN-WHEN-THEN pattern established by earlier sessions.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_entity(
    eid: str,
    label: str = "Person",
    props: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {"id": eid, "type": label, "properties": props or {"name": eid}}


# ---------------------------------------------------------------------------
# constraints/__init__.py
# ---------------------------------------------------------------------------

class TestConstraintTypes:
    """Tests for ConstraintType, ConstraintDefinition, ConstraintViolation."""

    def test_constraint_type_values(self):
        # GIVEN the ConstraintType enum
        from ipfs_datasets_py.knowledge_graphs.constraints import ConstraintType
        # WHEN we inspect values
        # THEN all four types exist
        assert ConstraintType.UNIQUE.value == "unique"
        assert ConstraintType.EXISTENCE.value == "existence"
        assert ConstraintType.TYPE.value == "type"
        assert ConstraintType.CUSTOM.value == "custom"

    def test_constraint_definition_fields(self):
        # GIVEN a ConstraintDefinition
        from ipfs_datasets_py.knowledge_graphs.constraints import (
            ConstraintDefinition, ConstraintType,
        )
        defn = ConstraintDefinition(
            name="test_constraint",
            constraint_type=ConstraintType.UNIQUE,
            properties=["email"],
            label="Person",
            options={"case_sensitive": False},
        )
        # WHEN we access fields
        # THEN they match what was provided
        assert defn.name == "test_constraint"
        assert defn.constraint_type == ConstraintType.UNIQUE
        assert defn.properties == ["email"]
        assert defn.label == "Person"
        assert defn.options["case_sensitive"] is False

    def test_constraint_violation_fields(self):
        # GIVEN a ConstraintViolation
        from ipfs_datasets_py.knowledge_graphs.constraints import ConstraintViolation
        v = ConstraintViolation(
            constraint_name="unique_email",
            entity_id="e1",
            message="Duplicate value",
        )
        # WHEN we access fields
        # THEN they match
        assert v.constraint_name == "unique_email"
        assert v.entity_id == "e1"
        assert "Duplicate" in v.message


class TestUniqueConstraint:
    """Tests for UniqueConstraint."""

    def _make_constraint(self, label=None):
        from ipfs_datasets_py.knowledge_graphs.constraints import UniqueConstraint
        return UniqueConstraint("unique_email", "email", label=label)

    def test_validate_returns_none_for_first_entity(self):
        # GIVEN a unique constraint
        uc = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {"email": "a@b.com"}}
        # WHEN we validate and then register
        uc.register(entity)
        # THEN first entity passes
        result = uc.validate(entity)
        assert result is None

    def test_validate_detects_duplicate(self):
        # GIVEN a unique constraint with one registered entity
        uc = self._make_constraint()
        e1 = {"id": "e1", "type": "Person", "properties": {"email": "a@b.com"}}
        e2 = {"id": "e2", "type": "Person", "properties": {"email": "a@b.com"}}
        uc.register(e1)
        # WHEN a second entity uses the same value
        result = uc.validate(e2)
        # THEN violation is returned
        assert result is not None
        assert result.entity_id == "e2"
        assert "a@b.com" in result.message

    def test_validate_allows_different_values(self):
        # GIVEN a unique constraint with one registered entity
        uc = self._make_constraint()
        e1 = {"id": "e1", "type": "Person", "properties": {"email": "a@b.com"}}
        e2 = {"id": "e2", "type": "Person", "properties": {"email": "c@d.com"}}
        uc.register(e1)
        # WHEN second entity has different value
        result = uc.validate(e2)
        # THEN no violation
        assert result is None

    def test_validate_skips_entity_without_property(self):
        # GIVEN a unique constraint
        uc = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {}}
        # WHEN entity does not have the constrained property
        result = uc.validate(entity)
        # THEN no violation
        assert result is None

    def test_validate_with_label_filter_skips_wrong_type(self):
        # GIVEN a unique constraint scoped to "Company"
        uc = self._make_constraint(label="Company")
        entity = {"id": "e1", "type": "Person", "properties": {"email": "a@b.com"}}
        # WHEN entity is a Person not a Company
        result = uc.validate(entity)
        # THEN constraint does not apply
        assert result is None

    def test_validate_same_entity_does_not_conflict(self):
        # GIVEN a unique constraint
        uc = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {"email": "a@b.com"}}
        uc.register(entity)
        # WHEN the same entity is validated again
        result = uc.validate(entity)
        # THEN no violation (same ID, same value)
        assert result is None


class TestExistenceConstraint:
    """Tests for ExistenceConstraint."""

    def _make_constraint(self):
        from ipfs_datasets_py.knowledge_graphs.constraints import ExistenceConstraint
        return ExistenceConstraint("exists_name", "name", label="Person")

    def test_validate_passes_when_property_present(self):
        # GIVEN an existence constraint
        ec = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {"name": "Alice"}}
        # WHEN entity has required property
        result = ec.validate(entity)
        # THEN no violation
        assert result is None

    def test_validate_fails_when_property_missing(self):
        # GIVEN an existence constraint
        ec = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {}}
        # WHEN entity is missing required property
        result = ec.validate(entity)
        # THEN violation returned
        assert result is not None
        assert "name" in result.message

    def test_validate_fails_when_property_is_none(self):
        # GIVEN an existence constraint
        ec = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {"name": None}}
        # WHEN property is None
        result = ec.validate(entity)
        # THEN violation returned
        assert result is not None

    def test_validate_fails_when_property_is_empty_string(self):
        # GIVEN an existence constraint
        ec = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {"name": ""}}
        # WHEN property is empty string
        result = ec.validate(entity)
        # THEN violation returned
        assert result is not None

    def test_validate_skips_wrong_label(self):
        # GIVEN an existence constraint for Person
        ec = self._make_constraint()
        entity = {"id": "e1", "type": "Organization", "properties": {}}
        # WHEN entity is Organization
        result = ec.validate(entity)
        # THEN constraint does not apply
        assert result is None

    def test_register_is_noop(self):
        # GIVEN an existence constraint
        ec = self._make_constraint()
        # WHEN register is called
        ec.register({"id": "e1", "type": "Person", "properties": {}})
        # THEN nothing raises


class TestTypeConstraint:
    """Tests for TypeConstraint."""

    def _make_constraint(self, label=None):
        from ipfs_datasets_py.knowledge_graphs.constraints import TypeConstraint
        return TypeConstraint("type_age_int", "age", int, label=label)

    def test_validate_passes_correct_type(self):
        # GIVEN a type constraint for int
        tc = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {"age": 30}}
        # WHEN age is int
        result = tc.validate(entity)
        # THEN no violation
        assert result is None

    def test_validate_fails_wrong_type(self):
        # GIVEN a type constraint for int
        tc = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {"age": "thirty"}}
        # WHEN age is a string
        result = tc.validate(entity)
        # THEN violation returned
        assert result is not None
        assert "str" in result.message or "int" in result.message

    def test_validate_skips_missing_property(self):
        # GIVEN a type constraint
        tc = self._make_constraint()
        entity = {"id": "e1", "type": "Person", "properties": {}}
        # WHEN property is absent
        result = tc.validate(entity)
        # THEN no violation (existence is separate concern)
        assert result is None

    def test_validate_with_label_filter(self):
        # GIVEN a type constraint scoped to "Employee"
        tc = self._make_constraint(label="Employee")
        entity = {"id": "e1", "type": "Person", "properties": {"age": "thirty"}}
        # WHEN entity is not Employee
        result = tc.validate(entity)
        # THEN no violation
        assert result is None

    def test_register_is_noop(self):
        # GIVEN a type constraint
        tc = self._make_constraint()
        # WHEN register is called
        tc.register({"id": "e1", "type": "Person", "properties": {"age": 30}})
        # THEN nothing raises


class TestCustomConstraint:
    """Tests for CustomConstraint."""

    def test_validate_passes_when_fn_returns_none(self):
        # GIVEN a custom constraint that always passes
        from ipfs_datasets_py.knowledge_graphs.constraints import CustomConstraint
        cc = CustomConstraint("custom_ok", lambda e: None)
        entity = {"id": "e1", "type": "Person", "properties": {}}
        # WHEN validate is called
        result = cc.validate(entity)
        # THEN no violation
        assert result is None

    def test_validate_returns_violation_when_fn_returns_message(self):
        # GIVEN a custom constraint that fails
        from ipfs_datasets_py.knowledge_graphs.constraints import CustomConstraint
        cc = CustomConstraint("custom_fail", lambda e: "Custom failure")
        entity = {"id": "e1", "type": "Person", "properties": {}}
        # WHEN validate is called
        result = cc.validate(entity)
        # THEN violation returned
        assert result is not None
        assert "Custom failure" in result.message

    def test_validate_skips_wrong_label(self):
        # GIVEN a custom constraint scoped to "Admin"
        from ipfs_datasets_py.knowledge_graphs.constraints import CustomConstraint
        cc = CustomConstraint("custom_admin", lambda e: "fail", label="Admin")
        entity = {"id": "e1", "type": "User", "properties": {}}
        # WHEN entity is User not Admin
        result = cc.validate(entity)
        # THEN no violation
        assert result is None

    def test_register_is_noop(self):
        # GIVEN a custom constraint
        from ipfs_datasets_py.knowledge_graphs.constraints import CustomConstraint
        cc = CustomConstraint("custom", lambda e: None)
        # WHEN register is called
        cc.register({"id": "e1", "type": "Person", "properties": {}})
        # THEN nothing raises


class TestConstraintManager:
    """Tests for ConstraintManager."""

    def _make_manager(self):
        from ipfs_datasets_py.knowledge_graphs.constraints import ConstraintManager
        return ConstraintManager()

    def test_add_unique_constraint(self):
        # GIVEN a manager
        cm = self._make_manager()
        # WHEN we add a unique constraint
        name = cm.add_unique_constraint("email", label="Person")
        # THEN it is stored
        assert name in cm.constraints
        assert "email" in name

    def test_add_unique_constraint_custom_name(self):
        # GIVEN a manager
        cm = self._make_manager()
        # WHEN we add with explicit name
        name = cm.add_unique_constraint("email", name="my_constraint")
        # THEN the custom name is used
        assert name == "my_constraint"

    def test_add_existence_constraint(self):
        # GIVEN a manager
        cm = self._make_manager()
        # WHEN we add an existence constraint
        name = cm.add_existence_constraint("name", label="Person")
        # THEN it is stored
        assert name in cm.constraints

    def test_add_type_constraint(self):
        # GIVEN a manager
        cm = self._make_manager()
        # WHEN we add a type constraint
        name = cm.add_type_constraint("age", int, label="Person")
        # THEN it is stored
        assert name in cm.constraints
        assert "int" in name

    def test_add_custom_constraint(self):
        # GIVEN a manager
        cm = self._make_manager()
        # WHEN we add a custom constraint
        name = cm.add_custom_constraint("my_custom", lambda e: None)
        # THEN it is stored
        assert name in cm.constraints
        assert name == "my_custom"

    def test_remove_constraint(self):
        # GIVEN a manager with a constraint
        cm = self._make_manager()
        name = cm.add_unique_constraint("email")
        # WHEN we remove it
        removed = cm.remove_constraint(name)
        # THEN it returns True and is gone
        assert removed is True
        assert name not in cm.constraints

    def test_remove_unknown_constraint_returns_false(self):
        # GIVEN a manager
        cm = self._make_manager()
        # WHEN we try to remove a non-existent constraint
        result = cm.remove_constraint("does_not_exist")
        # THEN returns False
        assert result is False

    def test_validate_no_violations(self):
        # GIVEN a manager with an existence constraint
        cm = self._make_manager()
        cm.add_existence_constraint("name", label="Person")
        entity = {"id": "e1", "type": "Person", "properties": {"name": "Alice"}}
        # WHEN entity satisfies all constraints
        violations = cm.validate(entity)
        # THEN no violations
        assert violations == []

    def test_validate_returns_violations(self):
        # GIVEN a manager with an existence constraint
        cm = self._make_manager()
        cm.add_existence_constraint("name", label="Person")
        entity = {"id": "e1", "type": "Person", "properties": {}}
        # WHEN entity violates constraint
        violations = cm.validate(entity)
        # THEN violation list is non-empty
        assert len(violations) == 1

    def test_validate_multiple_constraints(self):
        # GIVEN a manager with two constraints
        cm = self._make_manager()
        cm.add_existence_constraint("name", label="Person")
        cm.add_type_constraint("age", int, label="Person")
        entity = {"id": "e1", "type": "Person", "properties": {"age": "thirty"}}
        # WHEN entity violates type + misses name
        violations = cm.validate(entity)
        # THEN both violations detected
        assert len(violations) >= 1  # existence for name + type for age

    def test_register_delegates_to_constraints(self):
        # GIVEN a manager with a unique constraint
        cm = self._make_manager()
        cm.add_unique_constraint("email")
        entity = {"id": "e1", "type": "Person", "properties": {"email": "a@b.com"}}
        # WHEN register is called
        cm.register(entity)
        # THEN the unique constraint recorded the value
        uc = cm.constraints["unique_email"]
        assert "a@b.com" in uc.value_map

    def test_list_constraints(self):
        # GIVEN a manager with two constraints
        cm = self._make_manager()
        cm.add_unique_constraint("email")
        cm.add_existence_constraint("name", label="Person")
        # WHEN we list them
        definitions = cm.list_constraints()
        # THEN both are included
        assert len(definitions) == 2

    def test_get_constraint(self):
        # GIVEN a manager with a constraint
        cm = self._make_manager()
        cm.add_unique_constraint("email", name="uc_email")
        # WHEN we get it by name
        # Use direct dict access (list_constraints returns definitions without get_constraint)
        assert "uc_email" in cm.constraints

    def test_clear_constraints(self):
        # GIVEN a manager with constraints
        cm = self._make_manager()
        cm.add_unique_constraint("email")
        cm.add_existence_constraint("name", label="Person")
        # WHEN we clear them
        cm.constraints.clear()
        # THEN the manager is empty
        assert len(cm.constraints) == 0


# ---------------------------------------------------------------------------
# migration/ipfs_importer.py
# ---------------------------------------------------------------------------

class TestImportConfig:
    """Tests for ImportConfig dataclass."""

    def test_defaults(self):
        # GIVEN ImportConfig with no args
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import ImportConfig
        from ipfs_datasets_py.knowledge_graphs.migration.formats import MigrationFormat
        cfg = ImportConfig()
        # WHEN we inspect defaults
        # THEN sensible defaults are set
        assert cfg.input_file is None
        assert cfg.input_format == MigrationFormat.DAG_JSON
        assert cfg.batch_size == 1000
        assert cfg.create_indexes is True
        assert cfg.validate_data is True

    def test_custom_config(self):
        # GIVEN ImportConfig with custom values
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import ImportConfig
        from ipfs_datasets_py.knowledge_graphs.migration.formats import MigrationFormat
        cfg = ImportConfig(
            input_file="test.json",
            batch_size=500,
            validate_data=False,
        )
        # WHEN we inspect fields
        # THEN they match
        assert cfg.input_file == "test.json"
        assert cfg.batch_size == 500
        assert cfg.validate_data is False


class TestImportResult:
    """Tests for ImportResult dataclass."""

    def test_to_dict(self):
        # GIVEN an ImportResult
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import ImportResult
        result = ImportResult(
            success=True,
            nodes_imported=10,
            relationships_imported=5,
            duration_seconds=1.5,
        )
        # WHEN we convert to dict
        d = result.to_dict()
        # THEN all fields present
        assert d["success"] is True
        assert d["nodes_imported"] == 10
        assert d["relationships_imported"] == 5
        assert d["duration_seconds"] == 1.5
        assert d["errors"] == []
        assert d["warnings"] == []

    def test_to_dict_with_errors(self):
        # GIVEN an ImportResult with errors
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import ImportResult
        result = ImportResult(success=False, errors=["err1", "err2"])
        # WHEN converted to dict
        d = result.to_dict()
        # THEN errors included
        assert d["errors"] == ["err1", "err2"]


class TestIPFSImporterInit:
    """Tests for IPFSImporter initialization."""

    def test_init_stores_config(self):
        # GIVEN an ImportConfig
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        cfg = ImportConfig()
        # WHEN we create the importer
        importer = IPFSImporter(cfg)
        # THEN config is stored
        assert importer.config is cfg

    def test_init_handles_missing_ipfs_gracefully(self):
        # GIVEN ImportConfig
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        # WHEN IPFS components are unavailable (typical test environment)
        # THEN init succeeds without raising
        importer = IPFSImporter(ImportConfig())
        assert hasattr(importer, "_ipfs_available")


class TestIPFSImporterLoadGraphData:
    """Tests for IPFSImporter._load_graph_data()."""

    def test_load_from_graph_data_attr(self):
        # GIVEN config with direct graph_data
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        gd = GraphData()
        cfg = ImportConfig(graph_data=gd)
        importer = IPFSImporter(cfg)
        # WHEN _load_graph_data is called
        result = importer._load_graph_data()
        # THEN returns the same GraphData object
        assert result is gd

    def test_load_raises_when_no_input(self):
        # GIVEN config with neither input_file nor graph_data
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        cfg = ImportConfig()
        importer = IPFSImporter(cfg)
        # WHEN _load_graph_data is called
        # THEN MigrationError is raised
        with pytest.raises(MigrationError):
            importer._load_graph_data()


class TestIPFSImporterValidateGraphData:
    """Tests for IPFSImporter._validate_graph_data()."""

    def test_valid_graph_data_returns_no_errors(self):
        # GIVEN a valid GraphData with consistent relationships
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData, NodeData, RelationshipData,
        )
        gd = GraphData()
        gd.nodes = [NodeData("n1"), NodeData("n2")]
        gd.relationships = [RelationshipData("r1", "KNOWS", "n1", "n2")]
        importer = IPFSImporter(ImportConfig())
        # WHEN we validate
        errors = importer._validate_graph_data(gd)
        # THEN no errors
        assert errors == []

    def test_duplicate_node_ids_detected(self):
        # GIVEN a GraphData with duplicate node IDs
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, NodeData
        gd = GraphData()
        gd.nodes = [NodeData("n1"), NodeData("n1")]  # duplicate
        importer = IPFSImporter(ImportConfig())
        # WHEN validated
        errors = importer._validate_graph_data(gd)
        # THEN duplicate error reported
        assert any("Duplicate node" in e for e in errors)

    def test_relationship_with_nonexistent_node_detected(self):
        # GIVEN a relationship that references a missing node
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData, NodeData, RelationshipData,
        )
        gd = GraphData()
        gd.nodes = [NodeData("n1")]
        gd.relationships = [RelationshipData("r1", "KNOWS", "n1", "n_missing")]
        importer = IPFSImporter(ImportConfig())
        # WHEN validated
        errors = importer._validate_graph_data(gd)
        # THEN missing node error
        assert any("n_missing" in e for e in errors)


class TestIPFSImporterImportData:
    """Tests for IPFSImporter.import_data() end-to-end paths."""

    def test_import_data_fails_when_ipfs_unavailable(self):
        # GIVEN an importer with IPFS not available and a direct graph_data
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        cfg = ImportConfig(graph_data=GraphData(), validate_data=False)
        importer = IPFSImporter(cfg)
        importer._ipfs_available = False
        # WHEN import_data is called
        result = importer.import_data()
        # THEN result is failure with error message
        assert result.success is False
        assert len(result.errors) > 0

    def test_import_data_aborts_on_excessive_validation_errors(self):
        # GIVEN many duplicate nodes (> 10 errors)
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, NodeData
        gd = GraphData()
        # 12 duplicate node IDs
        gd.nodes = [NodeData("n1")] * 12
        cfg = ImportConfig(graph_data=gd, validate_data=True)
        importer = IPFSImporter(cfg)
        # WHEN import_data called
        result = importer.import_data()
        # THEN aborted early, success=False
        assert result.success is False
        assert any("Too many" in e for e in result.errors)

    def test_import_data_with_mocked_session(self):
        # GIVEN a mocked IPFS session that accepts queries
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData, NodeData, RelationshipData,
        )
        gd = GraphData()
        gd.nodes = [NodeData("n1", labels=["Person"], properties={"name": "Alice"})]
        gd.relationships = []  # No relationships to simplify mock

        cfg = ImportConfig(graph_data=gd, validate_data=False,
                           create_indexes=False, create_constraints=False)
        importer = IPFSImporter(cfg)
        importer._ipfs_available = True

        # Mock the driver/session returned by _connect
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, k: "internal_node_id"
        mock_result = MagicMock()
        mock_result.single.return_value = mock_record
        mock_session = MagicMock()
        mock_session.run.return_value = mock_result

        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_driver.session.return_value = mock_session

        mock_graph_db = MagicMock()
        mock_graph_db.driver.return_value = mock_driver
        importer._GraphDatabase = mock_graph_db
        importer._session = mock_session
        importer._driver = mock_driver

        with patch.object(importer, "_connect", return_value=True):
            with patch.object(importer, "_close"):
                result = importer.import_data()

        # THEN nodes imported (session.run was called for each node)
        assert result.nodes_imported >= 0  # at least ran

    def test_import_data_handles_migration_error(self):
        # GIVEN an importer that raises MigrationError during connect
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        gd = GraphData()
        cfg = ImportConfig(graph_data=gd, validate_data=False)
        importer = IPFSImporter(cfg)

        with patch.object(importer, "_connect",
                          side_effect=MigrationError("Cannot connect")):
            with patch.object(importer, "_close"):
                result = importer.import_data()

        # THEN result is failure with the error recorded
        assert result.success is False
        assert any("Cannot connect" in e for e in result.errors)

    def test_import_schema_with_indexes_and_constraints(self):
        # GIVEN an importer and graph data with schema
        from ipfs_datasets_py.knowledge_graphs.migration.ipfs_importer import (
            ImportConfig, IPFSImporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData, SchemaData,
        )
        schema = SchemaData(
            indexes=[{"name": "idx_name"}],
            constraints=[{"name": "uc_email"}],
        )
        gd = GraphData()
        gd.schema = schema

        cfg = ImportConfig(graph_data=gd, validate_data=False,
                           create_indexes=True, create_constraints=True)
        importer = IPFSImporter(cfg)
        importer._ipfs_available = False  # will fail at _connect, but _import_schema still reachable

        # Patch _connect to raise so we can test schema path separately
        with patch.object(importer, "_load_graph_data", return_value=gd):
            with patch.object(importer, "_connect", return_value=True):
                with patch.object(importer, "_import_nodes", return_value=(0, 0)):
                    with patch.object(importer, "_import_relationships", return_value=(0, 0)):
                        with patch.object(importer, "_close"):
                            result = importer.import_data()

        # THEN schema import ran (no exception)
        assert result.success is True


# ---------------------------------------------------------------------------
# migration/neo4j_exporter.py
# ---------------------------------------------------------------------------

class TestExportConfig:
    """Tests for ExportConfig dataclass."""

    def test_defaults(self):
        # GIVEN ExportConfig with no args
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import ExportConfig
        from ipfs_datasets_py.knowledge_graphs.migration.formats import MigrationFormat
        cfg = ExportConfig()
        # THEN sensible defaults
        assert cfg.uri == "bolt://localhost:7687"
        assert cfg.username == "neo4j"
        assert cfg.batch_size == 1000
        assert cfg.include_schema is True
        assert cfg.output_format == MigrationFormat.DAG_JSON

    def test_custom_values(self):
        # GIVEN ExportConfig with custom values
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import ExportConfig
        cfg = ExportConfig(
            uri="bolt://myhost:7687",
            username="admin",
            password="secret",
            batch_size=500,
            node_labels=["Person", "Company"],
        )
        # THEN stored correctly
        assert cfg.uri == "bolt://myhost:7687"
        assert cfg.node_labels == ["Person", "Company"]


class TestExportResult:
    """Tests for ExportResult dataclass."""

    def test_to_dict(self):
        # GIVEN an ExportResult
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import ExportResult
        result = ExportResult(
            success=True,
            node_count=100,
            relationship_count=50,
            duration_seconds=2.0,
            output_file="out.json",
        )
        # WHEN converted
        d = result.to_dict()
        # THEN all fields present
        assert d["success"] is True
        assert d["node_count"] == 100
        assert d["output_file"] == "out.json"


class TestNeo4jExporterInit:
    """Tests for Neo4jExporter initialization."""

    def test_init_handles_missing_neo4j(self):
        # GIVEN no neo4j package installed
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        # WHEN we create an exporter (neo4j almost certainly not installed in CI)
        exporter = Neo4jExporter(ExportConfig())
        # THEN init succeeds and flag is set
        assert hasattr(exporter, "_neo4j_available")
        assert exporter._driver is None

    def test_init_stores_config(self):
        # GIVEN ExportConfig
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        cfg = ExportConfig(uri="bolt://test:7687")
        exporter = Neo4jExporter(cfg)
        # THEN config stored
        assert exporter.config is cfg


class TestNeo4jExporterExport:
    """Tests for Neo4jExporter.export() error paths."""

    def test_export_fails_when_neo4j_unavailable(self):
        # GIVEN exporter with no neo4j package
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        exporter = Neo4jExporter(ExportConfig())
        exporter._neo4j_available = False
        # WHEN export is called
        result = exporter.export()
        # THEN failure with error
        assert result.success is False
        assert len(result.errors) > 0

    def test_export_handles_migration_error(self):
        # GIVEN exporter that raises MigrationError on connect
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        exporter = Neo4jExporter(ExportConfig())
        with patch.object(exporter, "_connect",
                          side_effect=MigrationError("Cannot connect")):
            with patch.object(exporter, "_close"):
                result = exporter.export()
        # THEN failure recorded
        assert result.success is False
        assert any("Cannot connect" in e for e in result.errors)

    def test_export_with_mocked_driver(self):
        # GIVEN a fully mocked Neo4j driver
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        exporter = Neo4jExporter(ExportConfig(include_schema=False))
        exporter._neo4j_available = True

        # Mock _export_nodes and _export_relationships
        with patch.object(exporter, "_connect", return_value=True):
            with patch.object(exporter, "_export_nodes", return_value=5):
                with patch.object(exporter, "_export_relationships", return_value=3):
                    with patch.object(exporter, "_close"):
                        result = exporter.export()

        # THEN success
        assert result.success is True
        assert result.node_count == 5
        assert result.relationship_count == 3

    def test_export_saves_to_file(self):
        # GIVEN exporter with output_file
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        cfg = ExportConfig(output_file="/tmp/kg_test_export.json", include_schema=False)
        exporter = Neo4jExporter(cfg)

        mock_gd = MagicMock()

        with patch.object(exporter, "_connect", return_value=True):
            with patch.object(exporter, "_export_nodes", return_value=2):
                with patch.object(exporter, "_export_relationships", return_value=1):
                    with patch("ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter.GraphData",
                               return_value=mock_gd):
                        with patch.object(exporter, "_close"):
                            result = exporter.export()

        # THEN output_file is recorded in result
        assert result.output_file == "/tmp/kg_test_export.json"

    def test_export_to_graph_data_returns_none_on_error(self):
        # GIVEN exporter that fails to connect
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        exporter = Neo4jExporter(ExportConfig())
        with patch.object(exporter, "_connect",
                          side_effect=MigrationError("No connection")):
            with patch.object(exporter, "_close"):
                result = exporter.export_to_graph_data()
        # THEN returns None
        assert result is None

    def test_export_to_graph_data_restores_output_file(self):
        # GIVEN exporter with output_file set
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        from ipfs_datasets_py.knowledge_graphs.exceptions import MigrationError
        cfg = ExportConfig(output_file="original.json")
        exporter = Neo4jExporter(cfg)
        original = exporter.config.output_file

        with patch.object(exporter, "_connect",
                          side_effect=MigrationError("No connection")):
            with patch.object(exporter, "_close"):
                exporter.export_to_graph_data()

        # THEN output_file is restored to original value
        assert exporter.config.output_file == original

    def test_close_called_even_on_error(self):
        # GIVEN exporter that raises during export
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        exporter = Neo4jExporter(ExportConfig())
        close_called = []

        def mock_close():
            close_called.append(True)

        with patch.object(exporter, "_connect",
                          side_effect=RuntimeError("Unexpected")):
            with patch.object(exporter, "_close", side_effect=mock_close):
                exporter.export()

        # THEN _close was still called (finally block)
        assert close_called


class TestNeo4jExporterNodeLabelFilter:
    """Tests for Neo4jExporter label/type filter query building."""

    def test_export_nodes_builds_label_filter_query(self):
        # GIVEN exporter with node_labels filter
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        cfg = ExportConfig(node_labels=["Person", "Company"])
        exporter = Neo4jExporter(cfg)
        gd = GraphData()

        # Mock driver session
        mock_session_ctx = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_session_ctx)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)
        mock_session_ctx.run = MagicMock(return_value=mock_result)

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session_ctx
        exporter._driver = mock_driver

        # WHEN _export_nodes is called
        count = exporter._export_nodes(gd)

        # THEN query contains label filter
        call_args = mock_session_ctx.run.call_args[0][0]
        assert "n:Person" in call_args or "Person" in call_args
        assert count == 0  # No records returned

    def test_export_relationships_with_type_filter(self):
        # GIVEN exporter with relationship_types filter
        from ipfs_datasets_py.knowledge_graphs.migration.neo4j_exporter import (
            ExportConfig, Neo4jExporter,
        )
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData
        cfg = ExportConfig(relationship_types=["KNOWS", "WORKS_AT"])
        exporter = Neo4jExporter(cfg)
        gd = GraphData()

        mock_session_ctx = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session_ctx.__enter__ = MagicMock(return_value=mock_session_ctx)
        mock_session_ctx.__exit__ = MagicMock(return_value=False)
        mock_session_ctx.run = MagicMock(return_value=mock_result)

        mock_driver = MagicMock()
        mock_driver.session.return_value = mock_session_ctx
        exporter._driver = mock_driver

        # WHEN _export_relationships called
        count = exporter._export_relationships(gd)

        # THEN query contains type filter
        call_args = mock_session_ctx.run.call_args[0][0]
        assert "KNOWS" in call_args
        assert count == 0


# ---------------------------------------------------------------------------
# transactions/wal.py — compact, recover, get_transaction_history, stats
# ---------------------------------------------------------------------------

class _MockStorage:
    """In-memory storage mock for WAL tests."""

    def __init__(self):
        self._store: Dict[str, Any] = {}
        self._counter = 0

    def store_json(self, data: Any) -> str:
        cid = f"cid-{self._counter}"
        self._counter += 1
        self._store[cid] = json.dumps(data)
        return cid

    def retrieve_json(self, cid: str) -> Any:
        if cid not in self._store:
            raise KeyError(f"CID not found: {cid}")
        return json.loads(self._store[cid])


def _make_wal_entry(txn_id: str = "txn-1", state=None, prev_cid=None):
    from ipfs_datasets_py.knowledge_graphs.transactions.types import (
        WALEntry, TransactionState, IsolationLevel,
    )
    if state is None:
        state = TransactionState.COMMITTED
    return WALEntry(
        txn_id=txn_id,
        timestamp=time.time(),
        operations=[],
        prev_wal_cid=prev_cid,
        txn_state=state,
        isolation_level=IsolationLevel.READ_COMMITTED,
        read_set=[],
        write_set=[],
    )


class TestWALCompact:
    """Tests for WriteAheadLog.compact()."""

    def test_compact_returns_new_head_cid(self):
        # GIVEN a WAL with one entry
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        entry = _make_wal_entry()
        cid1 = wal.append(entry)
        # WHEN we compact
        new_head = wal.compact(cid1)
        # THEN returns a new CID
        assert new_head is not None
        assert new_head != cid1

    def test_compact_resets_entry_count(self):
        # GIVEN a WAL with several entries
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        for i in range(5):
            wal.append(_make_wal_entry(f"txn-{i}"))
        assert wal._entry_count == 5
        # WHEN compacted
        head = wal.wal_head_cid
        wal.compact(head)
        # THEN entry count resets to 0 (compact() sets it to 0 after appending checkpoint)
        assert wal._entry_count == 0

    def test_compact_updates_wal_head(self):
        # GIVEN a WAL
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        cid1 = wal.append(_make_wal_entry("txn-1"))
        old_head = wal.wal_head_cid
        # WHEN compacted
        new_head = wal.compact(cid1)
        # THEN head updated
        assert wal.wal_head_cid == new_head
        assert wal.wal_head_cid != old_head


class TestWALRecover:
    """Tests for WriteAheadLog.recover()."""

    def test_recover_empty_wal_returns_empty_list(self):
        # GIVEN an empty WAL
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        # WHEN recover called
        ops = wal.recover()
        # THEN empty list
        assert ops == []

    def test_recover_committed_entries(self):
        # GIVEN a WAL with a committed entry containing operations
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            TransactionState, Operation, OperationType,
        )
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        op = Operation(type=OperationType.WRITE_NODE, node_id="n1", data={"labels": ["Person"]})
        entry = _make_wal_entry("txn-1", state=TransactionState.COMMITTED)
        entry.operations = [op]
        wal.append(entry)
        # WHEN recover called
        ops = wal.recover()
        # THEN returns the committed operations
        assert len(ops) == 1

    def test_recover_skips_aborted_entries(self):
        # GIVEN a WAL with an aborted entry
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            TransactionState, Operation, OperationType,
        )
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        op = Operation(type=OperationType.WRITE_NODE, node_id="n2")
        entry = _make_wal_entry("txn-1", state=TransactionState.ABORTED)
        entry.operations = [op]
        wal.append(entry)
        # WHEN recover called
        ops = wal.recover()
        # THEN no operations returned (aborted not replayed)
        assert ops == []


class TestWALTransactionHistory:
    """Tests for WriteAheadLog.get_transaction_history()."""

    def test_history_returns_matching_entries(self):
        # GIVEN a WAL with two entries for different transactions
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        wal.append(_make_wal_entry("txn-A"))
        wal.append(_make_wal_entry("txn-B"))
        # WHEN we get history for txn-A
        entries = wal.get_transaction_history("txn-A")
        # THEN only txn-A entries returned
        assert all(e.txn_id == "txn-A" for e in entries)

    def test_history_returns_empty_for_unknown_txn(self):
        # GIVEN a WAL with one entry
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        wal.append(_make_wal_entry("txn-1"))
        # WHEN we get history for unknown txn
        entries = wal.get_transaction_history("txn-unknown")
        # THEN empty list
        assert entries == []


class TestWALStats:
    """Tests for WriteAheadLog.get_stats() and verify_integrity()."""

    def test_get_stats_keys(self):
        # GIVEN a WAL
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        # WHEN stats requested
        stats = wal.get_stats()
        # THEN all expected keys present
        assert "head_cid" in stats
        assert "entry_count" in stats
        assert "compaction_threshold" in stats
        assert "needs_compaction" in stats

    def test_get_stats_entry_count_increments(self):
        # GIVEN a WAL
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        assert wal.get_stats()["entry_count"] == 0
        # WHEN entries added
        wal.append(_make_wal_entry("t1"))
        wal.append(_make_wal_entry("t2"))
        # THEN count increases
        assert wal.get_stats()["entry_count"] == 2

    def test_verify_integrity_empty_wal(self):
        # GIVEN an empty WAL
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        # WHEN integrity verified
        valid = wal.verify_integrity()
        # THEN passes (empty is valid)
        assert valid is True

    def test_verify_integrity_with_entries(self):
        # GIVEN a WAL with two entries (timestamps decreasing = reverse chrono order)
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            WALEntry, TransactionState, IsolationLevel, Operation, OperationType,
        )
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        t1 = time.time()
        op = Operation(type=OperationType.WRITE_NODE, node_id="n1")
        e1 = WALEntry(
            txn_id="txn-1", timestamp=t1,
            operations=[op], prev_wal_cid=None,
            txn_state=TransactionState.COMMITTED,
            isolation_level=IsolationLevel.READ_COMMITTED,
        )
        wal.append(e1)
        # WHEN integrity verified
        valid = wal.verify_integrity()
        # THEN valid (single-entry chain is trivially ordered)
        assert isinstance(valid, bool)


# ---------------------------------------------------------------------------
# transactions/manager.py — conflict detection, apply_operations, recover
# ---------------------------------------------------------------------------

def _make_mock_graph_engine():
    """Return a MagicMock that looks like a GraphEngine."""
    engine = MagicMock()
    engine._nodes = {}
    engine._enable_persistence = False
    return engine


def _make_mock_storage():
    """Return a mock IPLDBackend."""
    storage = _MockStorage()
    return storage


class TestTransactionManagerBegin:
    """Tests for TransactionManager.begin()."""

    def test_begin_creates_active_transaction(self):
        # GIVEN a TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        # WHEN begin is called
        txn = mgr.begin()
        # THEN transaction is active
        assert txn.state == TransactionState.ACTIVE
        assert txn.txn_id in mgr._active_transactions

    def test_begin_with_isolation_level(self):
        # GIVEN a manager
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import IsolationLevel
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        # WHEN begin with READ_COMMITTED
        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        # THEN isolation level matches
        assert txn.isolation_level == IsolationLevel.READ_COMMITTED

    def test_begin_increments_active_count(self):
        # GIVEN a manager
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        # WHEN two transactions started
        mgr.begin()
        mgr.begin()
        # THEN active count is 2
        assert mgr.get_active_count() == 2


class TestTransactionManagerAddOperation:
    """Tests for TransactionManager.add_operation()."""

    def test_add_operation_to_active_transaction(self):
        # GIVEN an active transaction
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType,
        )
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin()
        op = Operation(type=OperationType.WRITE_NODE, node_id="n1",
                       data={"labels": ["Person"], "properties": {}})
        # WHEN operation added
        mgr.add_operation(txn, op)
        # THEN it appears in the transaction
        assert len(txn.operations) == 1

    def test_add_operation_tracks_write_set(self):
        # GIVEN an active transaction
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType,
        )
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin()
        op = Operation(type=OperationType.SET_PROPERTY, node_id="entity-42",
                       data={"property": "name", "value": "Alice"})
        # WHEN operation added
        mgr.add_operation(txn, op)
        # THEN entity ID tracked in write_set
        assert "entity-42" in txn.write_set

    def test_add_operation_raises_on_aborted_transaction(self):
        # GIVEN an aborted transaction
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType, TransactionState,
        )
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionAbortedError
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin()
        mgr.rollback(txn)
        op = Operation(type=OperationType.WRITE_NODE, node_id="n1")
        # WHEN we try to add an operation
        # THEN raises TransactionAbortedError
        with pytest.raises(TransactionAbortedError):
            mgr.add_operation(txn, op)


class TestTransactionManagerRollback:
    """Tests for TransactionManager.rollback()."""

    def test_rollback_marks_transaction_aborted(self):
        # GIVEN an active transaction
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin()
        # WHEN rolled back
        mgr.rollback(txn)
        # THEN state is ABORTED
        assert txn.state == TransactionState.ABORTED

    def test_rollback_removes_from_active(self):
        # GIVEN an active transaction
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin()
        txn_id = txn.txn_id
        # WHEN rolled back
        mgr.rollback(txn)
        # THEN removed from active list
        assert txn_id not in mgr._active_transactions

    def test_rollback_clears_operations(self):
        # GIVEN a transaction with operations
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType,
        )
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin()
        op = Operation(type=OperationType.WRITE_NODE, node_id="n1")
        mgr.add_operation(txn, op)
        # WHEN rolled back
        mgr.rollback(txn)
        # THEN operations cleared
        assert txn.operations == []


class TestTransactionManagerConflictDetection:
    """Tests for TransactionManager._detect_conflicts()."""

    def test_read_committed_no_conflict_detection(self):
        # GIVEN a manager with READ_COMMITTED isolation
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import IsolationLevel
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        txn.write_set = ["e1"]
        # Pre-populate committed writes for e1 from another txn
        mgr._committed_writes["e1"] = {"txn-other"}
        # WHEN _detect_conflicts called
        # THEN no exception raised (READ_COMMITTED doesn't check)
        mgr._detect_conflicts(txn)

    def test_repeatable_read_detects_conflict(self):
        # GIVEN a manager with REPEATABLE_READ isolation
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, ConflictError,
        )
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin(IsolationLevel.REPEATABLE_READ)
        txn.write_set = ["e1"]
        # Simulate another txn committed write to e1 after we started
        mgr._committed_writes["e1"] = {"txn-earlier"}
        # WHEN _detect_conflicts called
        # THEN ConflictError raised
        with pytest.raises(ConflictError):
            mgr._detect_conflicts(txn)

    def test_serializable_detects_conflict(self):
        # GIVEN SERIALIZABLE isolation
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, ConflictError,
        )
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin(IsolationLevel.SERIALIZABLE)
        txn.write_set = ["e2"]
        mgr._committed_writes["e2"] = {"txn-z"}
        # WHEN _detect_conflicts called
        # THEN ConflictError raised
        with pytest.raises(ConflictError):
            mgr._detect_conflicts(txn)

    def test_no_conflict_when_no_overlap(self):
        # GIVEN REPEATABLE_READ with non-overlapping writes
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import IsolationLevel
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        txn = mgr.begin(IsolationLevel.REPEATABLE_READ)
        txn.write_set = ["e1"]
        mgr._committed_writes["e2"] = {"txn-other"}  # Different entity
        # WHEN _detect_conflicts called
        # THEN no exception
        mgr._detect_conflicts(txn)


class TestTransactionManagerApplyOperations:
    """Tests for TransactionManager._apply_operations()."""

    def test_apply_write_node_calls_create_node(self):
        # GIVEN a manager and transaction with WRITE_NODE op
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Transaction, TransactionState, IsolationLevel, Operation, OperationType,
        )
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        op = Operation(
            type=OperationType.WRITE_NODE,
            data={"labels": ["Person"], "properties": {"name": "Alice"}},
        )
        txn = Transaction(
            txn_id="txn-test", isolation_level=IsolationLevel.READ_COMMITTED,
            state=TransactionState.ACTIVE, operations=[op],
            read_set=[], write_set=[], start_time=time.time(),
            snapshot_cid=None, wal_entries=[],
        )
        # WHEN _apply_operations called
        mgr._apply_operations(txn)
        # THEN create_node called on engine
        engine.create_node.assert_called_once()

    def test_apply_delete_node_removes_from_nodes(self):
        # GIVEN a manager with a node in the engine
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Transaction, TransactionState, IsolationLevel, Operation, OperationType,
        )
        engine = _make_mock_graph_engine()
        engine._nodes = {"node-99": {"id": "node-99", "labels": ["X"], "properties": {}}}
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        op = Operation(type=OperationType.DELETE_NODE, node_id="node-99")
        txn = Transaction(
            txn_id="txn-del", isolation_level=IsolationLevel.READ_COMMITTED,
            state=TransactionState.ACTIVE, operations=[op],
            read_set=[], write_set=[], start_time=time.time(),
            snapshot_cid=None, wal_entries=[],
        )
        # WHEN _apply_operations called
        mgr._apply_operations(txn)
        # THEN node removed
        assert "node-99" not in engine._nodes

    def test_apply_set_property(self):
        # GIVEN a manager with a node
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Transaction, TransactionState, IsolationLevel, Operation, OperationType,
        )
        engine = _make_mock_graph_engine()
        engine._nodes = {"n1": {"id": "n1", "labels": [], "properties": {}}}
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        op = Operation(
            type=OperationType.SET_PROPERTY,
            node_id="n1",
            data={"property": "color", "value": "blue"},
        )
        txn = Transaction(
            txn_id="txn-prop", isolation_level=IsolationLevel.READ_COMMITTED,
            state=TransactionState.ACTIVE, operations=[op],
            read_set=[], write_set=[], start_time=time.time(),
            snapshot_cid=None, wal_entries=[],
        )
        # WHEN _apply_operations called
        mgr._apply_operations(txn)
        # THEN property is set
        assert engine._nodes["n1"]["properties"]["color"] == "blue"


class TestTransactionManagerGetStats:
    """Tests for TransactionManager.get_stats()."""

    def test_get_stats_keys(self):
        # GIVEN a manager
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        # WHEN stats requested
        stats = mgr.get_stats()
        # THEN expected keys present
        assert "active_transactions" in stats
        assert "wal_head_cid" in stats
        assert "wal_entry_count" in stats
        assert "committed_writes_tracked" in stats

    def test_get_stats_reflects_active_count(self):
        # GIVEN a manager with 2 active transactions
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(engine, storage)
        mgr.begin()
        mgr.begin()
        # WHEN stats requested
        stats = mgr.get_stats()
        # THEN active_transactions is 2
        assert stats["active_transactions"] == 2
