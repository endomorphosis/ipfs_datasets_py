"""
Session 16 coverage improvement tests.

Targets:
  - jsonld/validation.py  (81% → 94%+): SchemaValidator, SHACLValidator, SemanticValidator
  - lineage/metrics.py    (81% → 93%+): LineageMetrics, ImpactAnalyzer, DependencyAnalyzer
  - lineage/enhanced.py   (79% → 90%+): SemanticAnalyzer, BoundaryDetector, ConfidenceScorer
  - neo4j_compat/driver.py (71% → 85%+): IPFSDriver, GraphDatabase, create_driver
  - reasoning/helpers.py  (80% → 88%+): _infer_path_relation, _generate_llm_answer paths
  - lineage/visualization.py (65% → 72%+): LineageVisualizer (matplotlib / missing-plotly)

All tests follow GIVEN-WHEN-THEN format.
"""

import io
import os
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# JSON-LD validation
# ─────────────────────────────────────────────────────────────────────────────
class TestSchemaValidatorWithJsonschema:
    """SchemaValidator when jsonschema is installed."""

    def _make(self):
        from ipfs_datasets_py.knowledge_graphs.jsonld.validation import SchemaValidator
        return SchemaValidator()

    def test_valid_data_passes(self):
        """GIVEN valid data WHEN validated against matching schema THEN valid=True."""
        sv = self._make()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = sv.validate({"name": "Alice"}, schema)
        assert result.valid
        assert result.errors == []

    def test_invalid_type_fails(self):
        """GIVEN wrong type WHEN validated THEN valid=False and error reported."""
        sv = self._make()
        schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
        result = sv.validate({"age": "twenty"}, schema)
        assert not result.valid
        assert any("age" in e for e in result.errors)

    def test_required_property_missing(self):
        """GIVEN missing required property WHEN validated THEN error recorded."""
        sv = self._make()
        schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
        result = sv.validate({}, schema)
        assert not result.valid

    def test_autodetect_schema_by_type(self):
        """GIVEN @type in data and matching registered schema WHEN validated THEN schema used."""
        sv = self._make()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        sv.register_schema("Person", schema)
        result = sv.validate({"@type": "Person", "name": "Bob"})
        assert result.valid

    def test_autodetect_no_match_returns_warning(self):
        """GIVEN @type with no registered schema WHEN validated THEN warning added."""
        sv = self._make()
        result = sv.validate({"@type": "UnknownType", "name": "x"})
        assert result.valid  # no schema → pass with warning
        assert any("schema" in w.lower() or "detect" in w.lower() for w in result.warnings)

    def test_no_schema_no_type_returns_warning(self):
        """GIVEN data with no @type and no schema WHEN validated THEN warning added."""
        sv = self._make()
        result = sv.validate({"key": "value"})
        assert result.valid
        assert any("schema" in w.lower() or "detect" in w.lower() for w in result.warnings)


class TestSchemaValidatorWithoutJsonschema:
    """SchemaValidator when jsonschema is not available."""

    def test_no_jsonschema_returns_warning(self):
        """GIVEN jsonschema absent WHEN validated THEN valid=True with warning."""
        from ipfs_datasets_py.knowledge_graphs.jsonld.validation import SchemaValidator
        import ipfs_datasets_py.knowledge_graphs.jsonld.validation as mod
        with patch.object(mod, "HAVE_JSONSCHEMA", False):
            sv = SchemaValidator()
            result = sv.validate({"key": "value"}, {"type": "object"})
        assert result.valid
        assert any("jsonschema" in w.lower() for w in result.warnings)


class TestSHACLValidator:
    """SHACLValidator comprehensive tests."""

    def _make(self):
        from ipfs_datasets_py.knowledge_graphs.jsonld.validation import SHACLValidator
        return SHACLValidator()

    def test_no_shape_returns_warning(self):
        """GIVEN no shape WHEN validated THEN warning."""
        sv = self._make()
        result = sv.validate({"key": "value"})
        assert result.valid
        assert any("shape" in w.lower() for w in result.warnings)

    def test_targetClass_match_passes(self):
        """GIVEN matching targetClass WHEN validated THEN valid."""
        sv = self._make()
        shape = {"targetClass": "Person"}
        result = sv.validate({"@type": "Person"}, shape)
        assert result.valid

    def test_targetClass_mismatch_fails(self):
        """GIVEN mismatching targetClass WHEN validated THEN error."""
        sv = self._make()
        shape = {"targetClass": "Person"}
        result = sv.validate({"@type": "Organization"}, shape)
        assert not result.valid

    def test_minCount_property_present(self):
        """GIVEN minCount=1 and property present WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "name", "minCount": 1}]}
        result = sv.validate({"name": "Alice"}, shape)
        assert result.valid

    def test_minCount_property_missing_fails(self):
        """GIVEN minCount=1 and property absent WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "name", "minCount": 1}]}
        result = sv.validate({}, shape)
        assert not result.valid

    def test_minCount_list_too_short_fails(self):
        """GIVEN minCount=3 and list with 1 element WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "items", "minCount": 3}]}
        result = sv.validate({"items": ["a"]}, shape)
        assert not result.valid

    def test_maxCount_exceeded_fails(self):
        """GIVEN maxCount=2 and list with 3 elements WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "tags", "maxCount": 2}]}
        result = sv.validate({"tags": ["x", "y", "z"]}, shape)
        assert not result.valid

    def test_maxCount_ok_passes(self):
        """GIVEN maxCount=3 and list with 2 items WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "tags", "maxCount": 3}]}
        result = sv.validate({"tags": ["x", "y"]}, shape)
        assert result.valid

    def test_hasValue_scalar_match_passes(self):
        """GIVEN hasValue=42 and matching scalar WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "score", "hasValue": 42}]}
        result = sv.validate({"score": 42}, shape)
        assert result.valid

    def test_hasValue_scalar_mismatch_fails(self):
        """GIVEN hasValue=42 and value=99 WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "score", "hasValue": 42}]}
        result = sv.validate({"score": 99}, shape)
        assert not result.valid

    def test_hasValue_list_contains_passes(self):
        """GIVEN hasValue=42 and list containing 42 WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "tags", "hasValue": 42}]}
        result = sv.validate({"tags": [10, 42, 99]}, shape)
        assert result.valid

    def test_hasValue_list_missing_fails(self):
        """GIVEN hasValue=42 and list without 42 WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "tags", "hasValue": 42}]}
        result = sv.validate({"tags": [10, 99]}, shape)
        assert not result.valid

    def test_hasValue_property_absent_fails(self):
        """GIVEN hasValue constraint and property absent WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "required_val", "hasValue": "yes"}]}
        result = sv.validate({}, shape)
        assert not result.valid

    def test_datatype_string_passes(self):
        """GIVEN xsd:string and string value WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "name", "datatype": "xsd:string"}]}
        result = sv.validate({"name": "Alice"}, shape)
        assert result.valid

    def test_datatype_integer_wrong_fails(self):
        """GIVEN xsd:integer and string value WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "age", "datatype": "xsd:integer"}]}
        result = sv.validate({"age": "twenty"}, shape)
        assert not result.valid

    def test_class_constraint_passes(self):
        """GIVEN class constraint matching @type WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "address", "class": "Address"}]}
        result = sv.validate({"address": {"@type": "Address", "street": "Main"}}, shape)
        assert result.valid

    def test_class_constraint_fails(self):
        """GIVEN class constraint with wrong @type WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "address", "class": "Address"}]}
        result = sv.validate({"address": {"@type": "Location", "street": "Main"}}, shape)
        assert not result.valid

    def test_class_constraint_list_fails(self):
        """GIVEN class constraint and list item has wrong @type WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "items", "class": "Product"}]}
        result = sv.validate({"items": [{"@type": "Widget"}]}, shape)
        assert not result.valid

    def test_pattern_constraint_passes(self):
        """GIVEN matching regex pattern WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "email", "pattern": r"^[^@]+@[^@]+$"}]}
        result = sv.validate({"email": "user@example.com"}, shape)
        assert result.valid

    def test_pattern_constraint_fails(self):
        """GIVEN non-matching regex WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "email", "pattern": r"^[^@]+@[^@]+$"}]}
        result = sv.validate({"email": "not-an-email"}, shape)
        assert not result.valid

    def test_in_constraint_passes(self):
        """GIVEN value in allowed enum WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "status", "in": ["active", "inactive"]}]}
        result = sv.validate({"status": "active"}, shape)
        assert result.valid

    def test_in_constraint_fails(self):
        """GIVEN value not in allowed enum WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "status", "in": ["active", "inactive"]}]}
        result = sv.validate({"status": "pending"}, shape)
        assert not result.valid

    def test_node_nested_shape_passes(self):
        """GIVEN nested node constraint with matching nested data WHEN validated THEN valid."""
        sv = self._make()
        nested_shape = {"property": [{"path": "street", "minCount": 1}]}
        shape = {"property": [{"path": "address", "node": nested_shape}]}
        result = sv.validate({"address": {"street": "123 Main"}}, shape)
        assert result.valid

    def test_node_nested_shape_fails(self):
        """GIVEN nested node constraint with missing required property WHEN validated THEN error."""
        sv = self._make()
        nested_shape = {"property": [{"path": "street", "minCount": 1}]}
        shape = {"property": [{"path": "address", "node": nested_shape}]}
        result = sv.validate({"address": {}}, shape)
        assert not result.valid

    def test_minLength_passes(self):
        """GIVEN minLength=3 and string of length 5 WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "code", "minLength": 3}]}
        result = sv.validate({"code": "ABCDE"}, shape)
        assert result.valid

    def test_minLength_fails(self):
        """GIVEN minLength=3 and string of length 1 WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "code", "minLength": 3}]}
        result = sv.validate({"code": "A"}, shape)
        assert not result.valid

    def test_maxLength_fails(self):
        """GIVEN maxLength=5 and string of length 10 WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "tag", "maxLength": 5}]}
        result = sv.validate({"tag": "toolong123"}, shape)
        assert not result.valid

    def test_minInclusive_passes(self):
        """GIVEN minInclusive=0 and value=5 WHEN validated THEN valid."""
        sv = self._make()
        shape = {"property": [{"path": "score", "minInclusive": 0}]}
        result = sv.validate({"score": 5}, shape)
        assert result.valid

    def test_minInclusive_fails(self):
        """GIVEN minInclusive=0 and value=-1 WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "score", "minInclusive": 0}]}
        result = sv.validate({"score": -1}, shape)
        assert not result.valid

    def test_maxInclusive_fails(self):
        """GIVEN maxInclusive=100 and value=101 WHEN validated THEN error."""
        sv = self._make()
        shape = {"property": [{"path": "pct", "maxInclusive": 100}]}
        result = sv.validate({"pct": 101}, shape)
        assert not result.valid

    def test_and_composition_passes(self):
        """GIVEN sh:and all satisfied WHEN validated THEN valid."""
        sv = self._make()
        shape = {
            "and": [
                {"targetClass": "Item"},
                {"property": [{"path": "id", "minCount": 1}]},
            ]
        }
        result = sv.validate({"@type": "Item", "id": "x1"}, shape)
        assert result.valid

    def test_and_composition_fails(self):
        """GIVEN sh:and one not satisfied WHEN validated THEN error."""
        sv = self._make()
        shape = {
            "and": [
                {"targetClass": "Item"},
                {"property": [{"path": "id", "minCount": 1}]},
            ]
        }
        result = sv.validate({"@type": "Widget"}, shape)  # wrong type
        assert not result.valid

    def test_or_composition_passes(self):
        """GIVEN sh:or one satisfied WHEN validated THEN valid."""
        sv = self._make()
        shape = {
            "or": [
                {"targetClass": "Person"},
                {"targetClass": "Organization"},
            ]
        }
        result = sv.validate({"@type": "Person"}, shape)
        assert result.valid

    def test_or_composition_fails(self):
        """GIVEN sh:or none satisfied WHEN validated THEN error."""
        sv = self._make()
        shape = {
            "or": [
                {"targetClass": "Person"},
                {"targetClass": "Organization"},
            ]
        }
        result = sv.validate({"@type": "Robot"}, shape)
        assert not result.valid

    def test_not_composition_fails_when_matching(self):
        """GIVEN sh:not and data matches the NOT shape WHEN validated THEN error."""
        sv = self._make()
        shape = {"not": {"targetClass": "Banned"}}
        result = sv.validate({"@type": "Banned"}, shape)
        assert not result.valid

    def test_not_composition_passes_when_not_matching(self):
        """GIVEN sh:not and data does NOT match the NOT shape WHEN validated THEN valid."""
        sv = self._make()
        shape = {"not": {"targetClass": "Banned"}}
        result = sv.validate({"@type": "Allowed"}, shape)
        assert result.valid

    def test_warning_severity_adds_warning_not_error(self):
        """GIVEN severity=Warning in constraint WHEN violation THEN warning not error."""
        sv = self._make()
        shape = {"property": [{"path": "note", "minCount": 1, "severity": "Warning"}]}
        result = sv.validate({}, shape)
        assert result.valid  # warnings don't make it invalid
        assert result.warnings

    def test_autodetect_shape_by_type(self):
        """GIVEN shape registered for targetClass WHEN data has matching @type THEN shape used."""
        sv = self._make()
        shape = {"targetClass": "Product", "property": [{"path": "sku", "minCount": 1}]}
        sv.register_shape("product_shape", shape)
        result = sv.validate({"@type": "Product"})  # no sku → should fail
        assert not result.valid


class TestSemanticValidator:
    """SemanticValidator composite tests."""

    def _make(self):
        from ipfs_datasets_py.knowledge_graphs.jsonld.validation import SemanticValidator
        return SemanticValidator()

    def test_both_pass_returns_valid(self):
        """GIVEN both schema and SHACL valid WHEN validated THEN combined valid."""
        sv = self._make()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        shape = {"property": [{"path": "name", "minCount": 1}]}
        result = sv.validate({"name": "Alice"}, schema=schema, shape=shape)
        assert result.valid
        assert not result.errors

    def test_schema_fails_propagates(self):
        """GIVEN schema fails WHEN combined THEN combined errors include schema errors."""
        sv = self._make()
        schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
        result = sv.validate({"age": "old"}, schema=schema)
        assert not result.valid
        assert result.errors

    def test_shacl_fails_propagates(self):
        """GIVEN SHACL fails WHEN combined THEN combined errors include SHACL errors."""
        sv = self._make()
        shape = {"property": [{"path": "required_field", "minCount": 1}]}
        result = sv.validate({}, shape=shape)
        assert not result.valid
        assert result.errors

    def test_register_schema_and_shape(self):
        """GIVEN registered schema and shape WHEN used THEN delegation works."""
        sv = self._make()
        sv.register_schema("MySchema", {"type": "object"})
        sv.register_shape("MyShape", {"targetClass": "Item"})
        # No direct assertion needed — checking no AttributeError raised
        assert sv.schema_validator.schemas.get("MySchema") is not None
        assert sv.shacl_validator.shapes.get("MyShape") is not None


# ─────────────────────────────────────────────────────────────────────────────
# Lineage metrics
# ─────────────────────────────────────────────────────────────────────────────
def _make_tracker_with_chain():
    """Build a 3-node tracker: ds1 → transform1 → ds2."""
    from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
    t = LineageTracker()
    t.track_node("ds1", node_type="dataset", metadata={"system": "A"})
    t.track_node("transform1", node_type="transformation", metadata={"system": "B"})
    t.track_node("ds2", node_type="dataset", metadata={"system": "B"})
    t.track_link("ds1", "transform1", "derived_from")
    t.track_link("transform1", "ds2", "derived_from")
    return t


class TestLineageMetrics:
    """LineageMetrics coverage of compute_path_statistics, node absent branch."""

    def test_compute_basic_stats_keys(self):
        """GIVEN chain graph WHEN compute_basic_stats THEN expected keys present."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import LineageMetrics
        t = _make_tracker_with_chain()
        lm = LineageMetrics(t.graph)
        stats = lm.compute_basic_stats()
        assert "node_count" in stats
        assert "link_count" in stats
        assert stats["node_count"] == 3
        assert stats["link_count"] == 2

    def test_compute_node_metrics_absent_returns_empty(self):
        """GIVEN nonexistent node_id WHEN compute_node_metrics THEN returns empty dict."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import LineageMetrics
        t = _make_tracker_with_chain()
        lm = LineageMetrics(t.graph)
        result = lm.compute_node_metrics("nonexistent")
        assert result == {}

    def test_compute_node_metrics_root_node(self):
        """GIVEN root node WHEN compute_node_metrics THEN in_degree=0, out_degree=1."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import LineageMetrics
        t = _make_tracker_with_chain()
        lm = LineageMetrics(t.graph)
        m = lm.compute_node_metrics("ds1")
        assert m["in_degree"] == 0
        assert m["out_degree"] == 1

    def test_find_root_nodes(self):
        """GIVEN chain graph WHEN find_root_nodes THEN returns ['ds1']."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import LineageMetrics
        t = _make_tracker_with_chain()
        lm = LineageMetrics(t.graph)
        roots = lm.find_root_nodes()
        assert "ds1" in roots

    def test_find_leaf_nodes(self):
        """GIVEN chain graph WHEN find_leaf_nodes THEN returns ['ds2']."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import LineageMetrics
        t = _make_tracker_with_chain()
        lm = LineageMetrics(t.graph)
        leaves = lm.find_leaf_nodes()
        assert "ds2" in leaves

    def test_compute_path_statistics_returns_stats(self):
        """GIVEN chain graph WHEN compute_path_statistics THEN min/max/avg path length present."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import LineageMetrics
        t = _make_tracker_with_chain()
        lm = LineageMetrics(t.graph)
        stats = lm.compute_path_statistics()
        assert "min_path_length" in stats
        assert "max_path_length" in stats
        assert "avg_path_length" in stats
        assert stats["min_path_length"] == 2  # ds1 → transform1 → ds2

    def test_compute_path_statistics_empty_graph(self):
        """GIVEN empty graph WHEN compute_path_statistics THEN zeros returned."""
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import LineageMetrics
        t = LineageTracker()
        lm = LineageMetrics(t.graph)
        stats = lm.compute_path_statistics()
        assert stats["total_paths_analyzed"] == 0


class TestImpactAnalyzer:
    """ImpactAnalyzer downstream, upstream, critical nodes."""

    def test_analyze_downstream_impact_keys(self):
        """GIVEN chain WHEN analyze_downstream_impact THEN expected keys."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import ImpactAnalyzer
        t = _make_tracker_with_chain()
        ia = ImpactAnalyzer(t)
        result = ia.analyze_downstream_impact("ds1", max_depth=3)
        assert "node_id" in result
        assert "total_downstream" in result
        assert result["node_id"] == "ds1"
        assert result["total_downstream"] >= 2

    def test_analyze_upstream_dependencies_keys(self):
        """GIVEN chain WHEN analyze_upstream_dependencies for leaf THEN expected keys."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import ImpactAnalyzer
        t = _make_tracker_with_chain()
        ia = ImpactAnalyzer(t)
        result = ia.analyze_upstream_dependencies("ds2")
        assert "node_id" in result
        assert "total_dependencies" in result
        assert result["node_id"] == "ds2"
        assert result["total_dependencies"] >= 1

    def test_find_critical_nodes_returns_list(self):
        """GIVEN graph WHEN find_critical_nodes THEN list returned."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import ImpactAnalyzer
        t = _make_tracker_with_chain()
        ia = ImpactAnalyzer(t)
        critical = ia.find_critical_nodes()
        assert isinstance(critical, list)


class TestDependencyAnalyzer:
    """DependencyAnalyzer cycle detection, chains, depth."""

    def test_detect_circular_no_cycles(self):
        """GIVEN acyclic graph WHEN detect_circular_dependencies THEN empty list."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import DependencyAnalyzer
        t = _make_tracker_with_chain()
        da = DependencyAnalyzer(t)
        assert da.detect_circular_dependencies() == []

    def test_detect_circular_with_cycle(self):
        """GIVEN cyclic graph WHEN detect_circular_dependencies THEN cycle(s) returned."""
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import DependencyAnalyzer
        t = LineageTracker()
        t.track_node("a", node_type="dataset", metadata={})
        t.track_node("b", node_type="dataset", metadata={})
        t.track_link("a", "b", "derived_from")
        t.track_link("b", "a", "derived_from")  # cycle
        da = DependencyAnalyzer(t)
        cycles = da.detect_circular_dependencies()
        assert len(cycles) > 0

    def test_find_dependency_chains_upstream(self):
        """GIVEN chain graph WHEN find_dependency_chains upstream THEN chains contain ds1."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import DependencyAnalyzer
        t = _make_tracker_with_chain()
        da = DependencyAnalyzer(t)
        chains = da.find_dependency_chains("ds2", direction="upstream")
        # At least one chain should reach ds1
        assert any("ds1" in chain for chain in chains)

    def test_find_dependency_chains_downstream(self):
        """GIVEN chain graph WHEN find_dependency_chains downstream from root THEN chains contain ds2."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import DependencyAnalyzer
        t = _make_tracker_with_chain()
        da = DependencyAnalyzer(t)
        chains = da.find_dependency_chains("ds1", direction="downstream")
        assert any("ds2" in chain for chain in chains)

    def test_compute_dependency_depth_leaf(self):
        """GIVEN leaf node WHEN compute_dependency_depth THEN depth >= 2."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import DependencyAnalyzer
        t = _make_tracker_with_chain()
        da = DependencyAnalyzer(t)
        depth = da.compute_dependency_depth("ds2")
        assert depth >= 2

    def test_compute_dependency_depth_root(self):
        """GIVEN root node WHEN compute_dependency_depth THEN depth == 0."""
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import DependencyAnalyzer
        t = _make_tracker_with_chain()
        da = DependencyAnalyzer(t)
        depth = da.compute_dependency_depth("ds1")
        assert depth == 0


# ─────────────────────────────────────────────────────────────────────────────
# Lineage enhanced
# ─────────────────────────────────────────────────────────────────────────────
class TestSemanticAnalyzer:
    """SemanticAnalyzer semantic similarity and pattern detection."""

    def _make_tracker(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        t = LineageTracker()
        t.track_node("n1", node_type="dataset", entity_id="e1", metadata={"color": "red"})
        t.track_node("n2", node_type="dataset", entity_id="e1", metadata={"color": "red"})
        t.track_node("n3", node_type="transformation", entity_id=None, metadata={})
        t.track_link("n1", "n3", "derived_from")
        return t

    def test_same_type_boosts_similarity(self):
        """GIVEN two dataset nodes WHEN calculate_semantic_similarity THEN score > 0."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import SemanticAnalyzer
        t = self._make_tracker()
        sa = SemanticAnalyzer()
        n1 = t.graph.get_node("n1")
        n2 = t.graph.get_node("n2")
        score = sa.calculate_semantic_similarity(n1, n2)
        assert score > 0.0

    def test_same_entity_id_boosts_similarity(self):
        """GIVEN both nodes share entity_id WHEN similarity THEN score >= 0.6."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import SemanticAnalyzer
        t = self._make_tracker()
        sa = SemanticAnalyzer()
        n1 = t.graph.get_node("n1")
        n2 = t.graph.get_node("n2")
        score = sa.calculate_semantic_similarity(n1, n2)
        assert score >= 0.6  # same type + same entity_id

    def test_different_type_lowers_similarity(self):
        """GIVEN dataset vs transformation WHEN similarity THEN score < same-type score."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import SemanticAnalyzer
        t = self._make_tracker()
        sa = SemanticAnalyzer()
        n1 = t.graph.get_node("n1")
        n3 = t.graph.get_node("n3")
        score = sa.calculate_semantic_similarity(n1, n3)
        assert score < 0.5  # no type match, no entity_id match, no metadata overlap

    def test_detect_semantic_patterns(self):
        """GIVEN graph with outgoing edge WHEN detect_semantic_patterns THEN dict returned."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import SemanticAnalyzer
        t = self._make_tracker()
        sa = SemanticAnalyzer()
        patterns = sa.detect_semantic_patterns(t.graph, "n1")
        assert isinstance(patterns, dict)

    def test_categorize_relationship(self):
        """GIVEN relationship type string WHEN categorize_relationship THEN non-empty string."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import SemanticAnalyzer
        sa = SemanticAnalyzer()
        cat = sa.categorize_relationship("derived_from")
        assert isinstance(cat, str)
        assert len(cat) > 0


class TestBoundaryDetector:
    """BoundaryDetector system, organization, format, temporal boundaries."""

    def _make_nodes(self, meta1, meta2, time_delta=0):
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageNode
        ts = time.time()
        n1 = LineageNode(node_id="a", node_type="dataset", entity_id=None,
                         record_type=None, metadata=meta1, timestamp=ts)
        n2 = LineageNode(node_id="b", node_type="dataset", entity_id=None,
                         record_type=None, metadata=meta2, timestamp=ts + time_delta)
        return n1, n2

    def test_system_boundary_detected(self):
        """GIVEN different system values WHEN detect_boundary THEN returns 'system'."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import BoundaryDetector
        n1, n2 = self._make_nodes({"system": "PROD"}, {"system": "TEST"})
        bd = BoundaryDetector()
        assert bd.detect_boundary(n1, n2) == "system"

    def test_organization_boundary_detected(self):
        """GIVEN different organization values WHEN detect_boundary THEN returns 'organization'."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import BoundaryDetector
        n1, n2 = self._make_nodes({"organization": "OrgA"}, {"organization": "OrgB"})
        bd = BoundaryDetector()
        assert bd.detect_boundary(n1, n2) == "organization"

    def test_format_boundary_detected(self):
        """GIVEN different format values WHEN detect_boundary THEN returns 'format'."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import BoundaryDetector
        n1, n2 = self._make_nodes({"format": "csv"}, {"format": "parquet"})
        bd = BoundaryDetector()
        assert bd.detect_boundary(n1, n2) == "format"

    def test_temporal_boundary_detected(self):
        """GIVEN timestamps >1 day apart WHEN detect_boundary THEN returns 'temporal'."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import BoundaryDetector
        n1, n2 = self._make_nodes({}, {}, time_delta=90000)  # 25 hours
        bd = BoundaryDetector()
        assert bd.detect_boundary(n1, n2) == "temporal"

    def test_no_boundary_when_same(self):
        """GIVEN same metadata WHEN detect_boundary THEN returns None (or temporal if close)."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import BoundaryDetector
        n1, n2 = self._make_nodes({"system": "A"}, {"system": "A"}, time_delta=1)
        bd = BoundaryDetector()
        result = bd.detect_boundary(n1, n2)
        assert result is None

    def test_classify_risk_organization_is_high(self):
        """GIVEN 'organization' boundary WHEN classify_boundary_risk THEN 'high'."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import BoundaryDetector
        bd = BoundaryDetector()
        assert bd.classify_boundary_risk("organization") == "high"

    def test_classify_risk_security_is_high(self):
        """GIVEN 'security' boundary WHEN classify_boundary_risk THEN 'high'."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import BoundaryDetector
        bd = BoundaryDetector()
        assert bd.classify_boundary_risk("security") == "high"

    def test_classify_risk_system_is_medium(self):
        """GIVEN 'system' boundary WHEN classify_boundary_risk THEN 'medium'."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import BoundaryDetector
        bd = BoundaryDetector()
        assert bd.classify_boundary_risk("system") == "medium"

    def test_classify_risk_temporal_is_low(self):
        """GIVEN 'temporal' boundary WHEN classify_boundary_risk THEN 'low'."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import BoundaryDetector
        bd = BoundaryDetector()
        assert bd.classify_boundary_risk("temporal") == "low"


class TestConfidenceScorer:
    """ConfidenceScorer path confidence and propagation."""

    def test_path_confidence_single_node(self):
        """GIVEN path with one node WHEN calculate_path_confidence THEN returns 1.0."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import ConfidenceScorer
        t = _make_tracker_with_chain()
        cs = ConfidenceScorer()
        assert cs.calculate_path_confidence(t.graph, ["ds1"]) == 1.0

    def test_path_confidence_multi_hop(self):
        """GIVEN 3-node path with default confidence WHEN calculate_path_confidence THEN 1.0."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import ConfidenceScorer
        t = _make_tracker_with_chain()
        cs = ConfidenceScorer()
        # Default edge confidence = 1.0, so product = 1.0
        score = cs.calculate_path_confidence(t.graph, ["ds1", "transform1", "ds2"])
        assert score == 1.0

    def test_propagate_confidence_root_has_1(self):
        """GIVEN root node WHEN propagate_confidence THEN root confidence = 1.0."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import ConfidenceScorer
        t = _make_tracker_with_chain()
        cs = ConfidenceScorer()
        scores = cs.propagate_confidence(t, "ds1", max_hops=2)
        assert scores["ds1"] == 1.0

    def test_propagate_confidence_includes_downstream(self):
        """GIVEN chain WHEN propagate_confidence THEN downstream nodes included."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import ConfidenceScorer
        t = _make_tracker_with_chain()
        cs = ConfidenceScorer()
        scores = cs.propagate_confidence(t, "ds1", max_hops=2)
        assert "transform1" in scores
        assert "ds2" in scores


# ─────────────────────────────────────────────────────────────────────────────
# Neo4j compat driver
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_driver():
    """Create an IPFSDriver with mocked RouterDeps and IPLDBackend."""
    from ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver import IPFSDriver
    with patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.RouterDeps") as rd, \
         patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.IPLDBackend") as be:
        rd.return_value = MagicMock()
        be.return_value = MagicMock()
        driver = IPFSDriver("ipfs://localhost:5001", auth=("user", "token"))
        yield driver


class TestIPFSDriverInit:
    """IPFSDriver constructor and URI parsing."""

    def test_daemon_mode_parsed(self, mock_driver):
        """GIVEN ipfs:// URI WHEN driver created THEN mode=daemon."""
        assert mock_driver._mode == "daemon"
        assert mock_driver._ipfs_endpoint == "localhost:5001"

    def test_embedded_mode_parsed(self):
        """GIVEN ipfs+embedded:// URI WHEN driver created THEN mode=embedded."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver import IPFSDriver
        with patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.RouterDeps"), \
             patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.IPLDBackend"):
            d = IPFSDriver("ipfs+embedded:///./data")
            assert d._mode == "embedded"

    def test_invalid_scheme_raises(self):
        """GIVEN unsupported URI scheme WHEN driver created THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver import IPFSDriver
        with patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.RouterDeps"), \
             patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.IPLDBackend"):
            with pytest.raises(ValueError, match="Unsupported URI scheme"):
                IPFSDriver("bolt://localhost:7687")

    def test_have_deps_false_raises_import_error(self):
        """GIVEN HAVE_DEPS=False WHEN IPFSDriver created THEN ImportError raised."""
        import ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver as mod
        with patch.object(mod, "HAVE_DEPS", False):
            with pytest.raises(ImportError):
                mod.IPFSDriver("ipfs://localhost:5001")


class TestIPFSDriverSession:
    """IPFSDriver.session() and closed-driver checks."""

    def test_session_returns_ipfs_session(self, mock_driver):
        """GIVEN open driver WHEN session() THEN IPFSSession returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.session import IPFSSession
        sess = mock_driver.session()
        assert isinstance(sess, IPFSSession)

    def test_session_with_database(self, mock_driver):
        """GIVEN database= specified WHEN session() THEN session created for that db."""
        sess = mock_driver.session(database="analytics")
        assert sess._database == "analytics"

    def test_session_on_closed_driver_raises(self, mock_driver):
        """GIVEN closed driver WHEN session() THEN RuntimeError raised."""
        mock_driver.close()
        with pytest.raises(RuntimeError, match="closed"):
            mock_driver.session()


class TestIPFSDriverLifecycle:
    """IPFSDriver close, context manager, properties."""

    def test_closed_property_before_close(self, mock_driver):
        """GIVEN open driver WHEN closed property THEN False."""
        assert mock_driver.closed is False

    def test_closed_property_after_close(self, mock_driver):
        """GIVEN driver WHEN closed THEN closed=True."""
        mock_driver.close()
        assert mock_driver.closed is True

    def test_double_close_no_error(self, mock_driver):
        """GIVEN closed driver WHEN close() again THEN no exception."""
        mock_driver.close()
        mock_driver.close()  # should be no-op

    def test_context_manager_closes(self):
        """GIVEN driver used as context manager WHEN exited THEN closed."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver import IPFSDriver
        with patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.RouterDeps"), \
             patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.IPLDBackend"):
            with IPFSDriver("ipfs://localhost:5001") as d:
                assert not d.closed
            assert d.closed

    def test_get_pool_stats_returns_dict(self, mock_driver):
        """GIVEN driver WHEN get_pool_stats() THEN dict returned."""
        stats = mock_driver.get_pool_stats()
        assert isinstance(stats, dict)
        assert "max_size" in stats

    def test_verify_authentication_with_auth(self, mock_driver):
        """GIVEN driver with auth WHEN verify_authentication THEN True."""
        assert mock_driver.verify_authentication() is True

    def test_verify_authentication_without_auth(self):
        """GIVEN driver without auth WHEN verify_authentication THEN False."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver import IPFSDriver
        with patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.RouterDeps"), \
             patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.IPLDBackend"):
            d = IPFSDriver("ipfs://localhost:5001", auth=None)
            assert d.verify_authentication() is False

    def test_verify_connectivity_closed_raises(self, mock_driver):
        """GIVEN closed driver WHEN verify_connectivity THEN RuntimeError."""
        mock_driver.close()
        with pytest.raises(RuntimeError, match="closed"):
            mock_driver.verify_connectivity()

    def test_get_database_backend_caches(self, mock_driver):
        """GIVEN same database requested twice WHEN _get_database_backend THEN same object."""
        b1 = mock_driver._get_database_backend("mydb")
        b2 = mock_driver._get_database_backend("mydb")
        assert b1 is b2

    def test_get_database_backend_creates_new(self, mock_driver):
        """GIVEN different database names WHEN _get_database_backend THEN different objects."""
        b1 = mock_driver._get_database_backend("db1")
        b2 = mock_driver._get_database_backend("db2")
        # They're both mocks so just confirm they're in the cache
        assert "db1" in mock_driver._backend_cache
        assert "db2" in mock_driver._backend_cache


class TestGraphDatabase:
    """GraphDatabase.driver() and close_all_drivers()."""

    def test_driver_factory_returns_ipfs_driver(self):
        """GIVEN GraphDatabase.driver() call WHEN mocked THEN IPFSDriver returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver import GraphDatabase, IPFSDriver
        with patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.RouterDeps"), \
             patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.IPLDBackend"):
            d = GraphDatabase.driver("ipfs://localhost:5001", auth=("u", "t"))
            assert isinstance(d, IPFSDriver)
            d.close()

    def test_close_all_drivers_no_error(self):
        """GIVEN close_all_drivers() call WHEN invoked THEN no exception raised."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver import GraphDatabase
        GraphDatabase.close_all_drivers()  # should be no-op

    def test_create_driver_function(self):
        """GIVEN create_driver convenience function WHEN called THEN IPFSDriver returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver import create_driver, IPFSDriver
        with patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.RouterDeps"), \
             patch("ipfs_datasets_py.knowledge_graphs.neo4j_compat.driver.IPLDBackend"):
            d = create_driver("ipfs://localhost:5001", auth=("u", "t"))
            assert isinstance(d, IPFSDriver)
            d.close()


# ─────────────────────────────────────────────────────────────────────────────
# Reasoning helpers
# ─────────────────────────────────────────────────────────────────────────────
class TestReasoningHelpersInferPathRelation:
    """_infer_path_relation all branches."""

    def _get_mixin(self):
        from ipfs_datasets_py.knowledge_graphs.reasoning.helpers import ReasoningHelpersMixin
        return ReasoningHelpersMixin()

    def test_support_relation(self):
        """GIVEN ['support'] WHEN _infer_path_relation THEN SUPPORTING."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.types import InformationRelationType
        m = self._get_mixin()
        result = m._infer_path_relation(["support"])
        assert result == InformationRelationType.SUPPORTING

    def test_contradict_relation(self):
        """GIVEN ['contradict'] WHEN _infer_path_relation THEN CONTRADICTING."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.types import InformationRelationType
        m = self._get_mixin()
        result = m._infer_path_relation(["contradict"])
        assert result == InformationRelationType.CONTRADICTING

    def test_elaborate_relation(self):
        """GIVEN ['elaborat'] WHEN _infer_path_relation THEN ELABORATING."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.types import InformationRelationType
        m = self._get_mixin()
        result = m._infer_path_relation(["elaborating"])
        assert result == InformationRelationType.ELABORATING

    def test_prerequisite_relation(self):
        """GIVEN ['require'] WHEN _infer_path_relation THEN PREREQUISITE."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.types import InformationRelationType
        m = self._get_mixin()
        result = m._infer_path_relation(["require"])
        assert result == InformationRelationType.PREREQUISITE

    def test_consequence_relation(self):
        """GIVEN ['result'] WHEN _infer_path_relation THEN CONSEQUENCE."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.types import InformationRelationType
        m = self._get_mixin()
        result = m._infer_path_relation(["result"])
        assert result == InformationRelationType.CONSEQUENCE

    def test_default_complementary(self):
        """GIVEN unknown relation WHEN _infer_path_relation THEN COMPLEMENTARY."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.types import InformationRelationType
        m = self._get_mixin()
        result = m._infer_path_relation(["unknown_relation"])
        assert result == InformationRelationType.COMPLEMENTARY

    def test_empty_relations_complementary(self):
        """GIVEN empty list WHEN _infer_path_relation THEN COMPLEMENTARY."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.types import InformationRelationType
        m = self._get_mixin()
        result = m._infer_path_relation([])
        assert result == InformationRelationType.COMPLEMENTARY


class TestGenerateLLMAnswer:
    """_generate_llm_answer fallback paths."""

    def _get_reasoner(self):
        """Build a CrossDocumentReasoner with all optionals mocked out."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import CrossDocumentReasoner
        r = CrossDocumentReasoner.__new__(CrossDocumentReasoner)
        r.llm_service = None
        r._default_llm_router = None
        r.config = MagicMock()
        r._query_count = 0
        return r

    def test_no_api_key_no_router_returns_fallback(self):
        """GIVEN no env keys and no router WHEN _generate_llm_answer THEN string answer."""
        r = self._get_reasoner()
        with patch.dict(os.environ, {}, clear=True):
            # Remove any LLM keys that might be set
            env = {k: v for k, v in os.environ.items()
                   if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
            with patch.dict(os.environ, env, clear=True):
                answer, conf = r._generate_llm_answer("prompt text", "my query")
        assert isinstance(answer, str)
        assert len(answer) > 0
        assert 0.0 <= conf <= 1.0

    def test_router_path_used_when_available(self):
        """GIVEN router with route_request WHEN _generate_llm_answer THEN router used."""
        r = self._get_reasoner()
        mock_router = MagicMock()
        mock_router.route_request.return_value = "Router answer text here"
        r.llm_service = mock_router
        with patch.dict(os.environ, {}, clear=True):
            env = {k: v for k, v in os.environ.items()
                   if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
            with patch.dict(os.environ, env, clear=True):
                answer, conf = r._generate_llm_answer("prompt", "query")
        assert "Router answer" in answer
        assert conf >= 0.7

    def test_openai_key_but_package_unavailable_falls_through(self):
        """GIVEN OPENAI_API_KEY set but openai=None WHEN _generate_llm_answer THEN falls through."""
        r = self._get_reasoner()
        import ipfs_datasets_py.knowledge_graphs.reasoning.cross_document as parent_mod
        with patch.object(parent_mod, "openai", None), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"}):
            env = {k: v for k, v in os.environ.items()
                   if k not in ("ANTHROPIC_API_KEY",)}
            env["OPENAI_API_KEY"] = "fake-key"
            with patch.dict(os.environ, env, clear=True):
                answer, conf = r._generate_llm_answer("prompt", "query")
        # Should have fallen all the way through to rule-based fallback
        assert isinstance(answer, str)

    def test_anthropic_key_but_package_unavailable_falls_through(self):
        """GIVEN ANTHROPIC_API_KEY set but anthropic=None WHEN _generate_llm_answer THEN falls through."""
        r = self._get_reasoner()
        import ipfs_datasets_py.knowledge_graphs.reasoning.cross_document as parent_mod
        with patch.object(parent_mod, "anthropic", None), \
             patch.object(parent_mod, "openai", None), \
             patch.dict(os.environ, {}, clear=True):
            env = {"ANTHROPIC_API_KEY": "fake-key"}
            with patch.dict(os.environ, env, clear=True):
                answer, conf = r._generate_llm_answer("prompt", "query")
        assert isinstance(answer, str)


class TestGetLLMRouter:
    """_get_llm_router initialization paths."""

    def _get_reasoner(self):
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import CrossDocumentReasoner
        r = CrossDocumentReasoner.__new__(CrossDocumentReasoner)
        r.llm_service = None
        r._default_llm_router = None
        return r

    def test_returns_none_when_no_router(self):
        """GIVEN LLMRouter=None WHEN _get_llm_router THEN None returned."""
        r = self._get_reasoner()
        import ipfs_datasets_py.knowledge_graphs.reasoning.cross_document as parent_mod
        with patch.object(parent_mod, "LLMRouter", None):
            result = r._get_llm_router()
        assert result is None

    def test_llm_service_returned_when_has_route_request(self):
        """GIVEN llm_service with route_request WHEN _get_llm_router THEN service returned."""
        r = self._get_reasoner()
        mock_service = MagicMock()
        mock_service.route_request = MagicMock()
        r.llm_service = mock_service
        result = r._get_llm_router()
        assert result is mock_service

    def test_cached_default_router_returned(self):
        """GIVEN _default_llm_router already set WHEN _get_llm_router THEN cached returned."""
        r = self._get_reasoner()
        mock_router = MagicMock()
        r._default_llm_router = mock_router
        import ipfs_datasets_py.knowledge_graphs.reasoning.cross_document as parent_mod
        with patch.object(parent_mod, "LLMRouter", None):
            result = r._get_llm_router()
        assert result is mock_router

    def test_llm_router_init_failure_returns_none(self):
        """GIVEN LLMRouter() raises Exception WHEN _get_llm_router THEN None returned."""
        r = self._get_reasoner()
        import ipfs_datasets_py.knowledge_graphs.reasoning.cross_document as parent_mod
        failing_router = MagicMock(side_effect=RuntimeError("cannot connect"))
        with patch.object(parent_mod, "LLMRouter", failing_router):
            result = r._get_llm_router()
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Lineage visualization — plotly path (requires plotly) / matplotlib rendering
# ─────────────────────────────────────────────────────────────────────────────
class TestLineageVisualizerPlotly:
    """render_plotly path — test with mocked plotly."""

    def _make_visualizer_with_nodes(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        t = LineageTracker()
        t.track_node("a", node_type="dataset", metadata={})
        t.track_node("b", node_type="transformation", metadata={})
        t.track_node("c", node_type="other", metadata={})
        t.track_link("a", "b", "derived_from")
        t.track_link("b", "c", "derived_from")
        return LineageVisualizer(t.graph)

    def test_render_plotly_raises_if_plotly_unavailable(self):
        """GIVEN plotly not available WHEN render_plotly THEN ImportError raised."""
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as mod
        vis = self._make_visualizer_with_nodes()
        with patch.object(mod, "PLOTLY_AVAILABLE", False):
            with pytest.raises(ImportError, match="[Pp]lotly"):
                vis.render_plotly()

    def test_render_plotly_with_mocked_plotly(self):
        """GIVEN mocked plotly WHEN render_plotly THEN returns HTML string."""
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as mod
        vis = self._make_visualizer_with_nodes()
        mock_go = MagicMock()
        mock_fig = MagicMock()
        mock_fig.to_html.return_value = "<html>graph</html>"
        mock_go.Scatter.return_value = MagicMock()
        mock_go.Figure.return_value = mock_fig
        mock_go.Layout.return_value = MagicMock()
        with patch.object(mod, "PLOTLY_AVAILABLE", True), \
             patch.object(mod, "go", mock_go):
            result = vis.render_plotly()
        assert result == "<html>graph</html>"

    def test_render_plotly_with_output_path(self, tmp_path):
        """GIVEN mocked plotly and output_path WHEN render_plotly THEN returns None."""
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as mod
        vis = self._make_visualizer_with_nodes()
        outfile = str(tmp_path / "lineage.html")
        mock_go = MagicMock()
        mock_fig = MagicMock()
        mock_fig.to_html.return_value = "<html>graph</html>"
        mock_go.Scatter.return_value = MagicMock()
        mock_go.Figure.return_value = mock_fig
        mock_go.Layout.return_value = MagicMock()
        with patch.object(mod, "PLOTLY_AVAILABLE", True), \
             patch.object(mod, "go", mock_go):
            result = vis.render_plotly(output_path=outfile)
        assert result is None
        mock_fig.write_html.assert_called_once_with(outfile)

    def test_visualize_lineage_plotly_renderer(self):
        """GIVEN 'plotly' renderer WHEN visualize_lineage THEN plotly render called."""
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as mod
        t = LineageTracker()
        t.track_node("x", node_type="dataset", metadata={})
        mock_go = MagicMock()
        mock_fig = MagicMock()
        mock_fig.to_html.return_value = "<html></html>"
        mock_go.Scatter.return_value = MagicMock()
        mock_go.Figure.return_value = mock_fig
        mock_go.Layout.return_value = MagicMock()
        with patch.object(mod, "PLOTLY_AVAILABLE", True), \
             patch.object(mod, "go", mock_go):
            result = mod.visualize_lineage(t, renderer="plotly")
        assert result == "<html></html>"
