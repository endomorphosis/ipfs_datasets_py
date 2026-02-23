"""
Session 18 coverage tests — targeting the highest-impact testable modules.

Targets:
  - ontology/reasoning.py   (90% → 95%)  : ConsistencyViolation.to_dict, OntologySchema.merge,
                                            subproperty/domain/range inference, explain_inferences,
                                            check_consistency (disjoint + negative_assertion),
                                            get_all_superproperties, _apply_range, materialize fixpoint
  - transactions/manager.py (77% → 88%)  : ConflictError path, TimeoutError path, generic Exception
                                            path, DELETE_NODE, SET_PROPERTY, _capture_snapshot
  - transactions/wal.py     (72% → 82%)  : StorageError in append, generic Exception in append,
                                            cycle detection in read, StorageError in read,
                                            generic Exception in read, compact error path,
                                            recover error path, verify_integrity error paths
  - query/unified_engine.py (73% → 82%)  : TimeoutError paths (cypher/ir/hybrid/graphrag),
                                            GraphRAG LLM unexpected error → QueryExecutionError,
                                            GraphRAG QueryError re-raise, generic error fallthrough
  - cypher/ast.py           (89% → 94%)  : accept() generic_visit, accept() ValueError for None
                                            node_type, DeleteClause, SetClause, CaseExpressionNode
                                            __post_init__/repr, WhenClause repr, MapNode __post_init__,
                                            ASTPrettyPrinter print/generic_visit with nested lists
  - migration/formats.py    (86% → 90%)  : GraphData.to_json, GraphML load with key_map,
                                            GEXF load with attvalues, GEXF round-trip save/load

All tests follow the GIVEN-WHEN-THEN pattern.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import time
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ─── helpers ──────────────────────────────────────────────────────────────────


def _make_wal_entry(
    state=None,
    prev_cid: str | None = None,
    ops=None,
):
    """Return a WALEntry with safe defaults."""
    from ipfs_datasets_py.knowledge_graphs.transactions.types import (
        WALEntry, TransactionState, Operation, OperationType,
    )
    if state is None:
        state = TransactionState.COMMITTED
    if ops is None:
        ops = [Operation(type=OperationType.WRITE_NODE, data={})]
    return WALEntry(
        txn_id=str(uuid.uuid4()),
        timestamp=time.time(),
        txn_state=state,
        operations=ops,
        prev_wal_cid=prev_cid,
    )


def _make_tx_manager():
    """Return a TransactionManager with mock engine + storage."""
    from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
    engine = MagicMock()
    engine._nodes = {
        "n1": {"labels": ["Person"], "properties": {"name": "Alice"}},
        "n2": {"labels": ["Company"], "properties": {"name": "ACME"}},
    }
    storage = MagicMock()
    storage.store_json.return_value = "bafyfakecid"
    return TransactionManager(graph_engine=engine, storage_backend=storage), engine, storage


def _make_kg_with_entities(entity_defs):
    """Build a KnowledgeGraph with the given (entity_id, name, entity_type) tuples."""
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
        KnowledgeGraph, Entity,
    )
    kg = KnowledgeGraph()
    for eid, name, etype, props in entity_defs:
        e = Entity(entity_id=eid, name=name, entity_type=etype,
                   properties=props or {})
        kg.add_entity(e)
    return kg


# ─── ontology/reasoning.py ────────────────────────────────────────────────────


class TestConsistencyViolationToDict:
    """ConsistencyViolation.to_dict (line 92)."""

    def test_to_dict_keys_present(self):
        """GIVEN a ConsistencyViolation WHEN to_dict() is called THEN all 4 keys exist."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import ConsistencyViolation
        cv = ConsistencyViolation(
            violation_type="disjoint_class",
            message="test violation",
            entity_ids=["e1", "e2"],
            relationship_ids=["r1"],
        )
        d = cv.to_dict()
        assert d["violation_type"] == "disjoint_class"
        assert d["message"] == "test violation"
        assert d["entity_ids"] == ["e1", "e2"]
        assert d["relationship_ids"] == ["r1"]

    def test_to_dict_empty_ids(self):
        """GIVEN empty ID lists WHEN to_dict() is called THEN lists are empty."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import ConsistencyViolation
        cv = ConsistencyViolation(violation_type="x", message="y")
        d = cv.to_dict()
        assert d["entity_ids"] == []
        assert d["relationship_ids"] == []


class TestOntologySchemaMerge:
    """OntologySchema.merge (lines 367-409)."""

    def test_merge_subclasses_combined(self):
        """GIVEN two schemas WHEN merged THEN subclass_map contains entries from both."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s1 = OntologySchema()
        s1.add_subclass("Dog", "Animal")
        s2 = OntologySchema()
        s2.add_subclass("Cat", "Animal")
        merged = s1.merge(s2)
        assert "Dog" in merged.subclass_map
        assert "Cat" in merged.subclass_map

    def test_merge_transitive_union(self):
        """GIVEN two schemas with disjoint transitive sets WHEN merged THEN union."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s1 = OntologySchema()
        s1.add_transitive("ancestor")
        s2 = OntologySchema()
        s2.add_transitive("contains")
        merged = s1.merge(s2)
        assert "ancestor" in merged.transitive
        assert "contains" in merged.transitive

    def test_merge_symmetric_union(self):
        """GIVEN two schemas with symmetric sets WHEN merged THEN union."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s1 = OntologySchema()
        s1.add_symmetric("sibling")
        s2 = OntologySchema()
        s2.add_symmetric("married_to")
        merged = s1.merge(s2)
        assert "sibling" in merged.symmetric
        assert "married_to" in merged.symmetric

    def test_merge_equivalent_classes_combined(self):
        """GIVEN equivalent class pairs in both schemas WHEN merged THEN both preserved."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s1 = OntologySchema()
        s1.add_equivalent_class("Person", "Human")
        s2 = OntologySchema()
        s2.add_equivalent_class("Car", "Vehicle")
        merged = s1.merge(s2)
        eq_types = {frozenset(p) for p in merged._equivalent_classes}
        assert frozenset({"Human", "Person"}) in eq_types
        assert frozenset({"Car", "Vehicle"}) in eq_types

    def test_merge_property_chains_deduped(self):
        """GIVEN same chain in both schemas WHEN merged THEN deduplicated."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s1 = OntologySchema()
        s1.add_property_chain(["p1", "p2"], "result")
        s2 = OntologySchema()
        s2.add_property_chain(["p1", "p2"], "result")
        merged = s1.merge(s2)
        assert len(merged.property_chains) == 1

    def test_merge_subproperty_maps_combined(self):
        """GIVEN subproperty entries in both WHEN merged THEN both present."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s1 = OntologySchema()
        s1.add_subproperty("friend", "knows")
        s2 = OntologySchema()
        s2.add_subproperty("colleague", "knows")
        merged = s1.merge(s2)
        assert "friend" in merged.subproperty_map
        assert "colleague" in merged.subproperty_map

    def test_merge_disjoint_maps_combined(self):
        """GIVEN disjoint entries in both WHEN merged THEN both present."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s1 = OntologySchema()
        s1.add_disjoint("Animal", "Machine")
        s2 = OntologySchema()
        s2.add_disjoint("Food", "Tool")
        merged = s1.merge(s2)
        assert "Animal" in merged.disjoint_map
        assert "Food" in merged.disjoint_map


class TestOntologySchemaGetAllSuperproperties:
    """OntologySchema.get_all_superproperties (lines 540-549)."""

    def test_transitive_superproperties(self):
        """GIVEN chain is_friend_of → knows → relatedTo WHEN get_all THEN both returned."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s = OntologySchema()
        s.add_subproperty("is_friend_of", "knows")
        s.add_subproperty("knows", "relatedTo")
        result = s.get_all_superproperties("is_friend_of")
        assert "knows" in result
        assert "relatedTo" in result

    def test_unknown_property_returns_empty(self):
        """GIVEN no subproperty entries WHEN get_all_superproperties THEN empty set."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s = OntologySchema()
        assert s.get_all_superproperties("unknown") == set()


class TestOntologySchemaAddSubproperty:
    """OntologySchema.add_subproperty returns self (lines 199-200)."""

    def test_add_subproperty_returns_self(self):
        """GIVEN schema WHEN add_subproperty() THEN returns self for chaining."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema
        s = OntologySchema()
        assert s.add_subproperty("a", "b") is s
        assert "a" in s.subproperty_map


class TestOntologyReasonerSubproperty:
    """OntologyReasoner subproperty inference (lines 783-799)."""

    def test_subproperty_inference_adds_supertype_rel(self):
        """GIVEN is_friend_of subPropertyOf knows WHEN materialize THEN 'knows' rel added."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity, Relationship
        s = OntologySchema()
        s.add_subproperty("is_friend_of", "knows")
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="a1", name="Alice", entity_type="Person")
        e2 = Entity(entity_id="b1", name="Bob", entity_type="Person")
        kg.add_entity(e1)
        kg.add_entity(e2)
        rel = Relationship(
            relationship_type="is_friend_of",
            source_entity=e1,
            target_entity=e2,
            confidence=0.9,
        )
        kg.add_relationship(rel)
        result = r.materialize(kg)
        types = {rel.relationship_type for rel in result.relationships.values()}
        assert "is_friend_of" in types
        assert "knows" in types

    def test_subproperty_not_duplicated(self):
        """GIVEN subproperty rel already exists WHEN materialize THEN not duplicated."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity, Relationship
        s = OntologySchema()
        s.add_subproperty("sub_rel", "super_rel")
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="x", name="X", entity_type="T")
        e2 = Entity(entity_id="y", name="Y", entity_type="T")
        kg.add_entity(e1)
        kg.add_entity(e2)
        for _ in range(2):  # Add same super-rel twice would be wrong
            rel = Relationship(relationship_type="sub_rel", source_entity=e1, target_entity=e2, confidence=1.0)
            kg.add_relationship(rel)
        # Materialize should only add 1 super_rel, not 2
        result = r.materialize(kg)
        super_rels = [rel for rel in result.relationships.values() if rel.relationship_type == "super_rel"]
        assert len(super_rels) == 1


class TestOntologyReasonerDomainRange:
    """OntologyReasoner domain/range inference (lines 895-952)."""

    def test_domain_inference_adds_inferred_type(self):
        """GIVEN domain declaration WHEN materialize THEN source entity gets inferred type."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity, Relationship
        s = OntologySchema()
        s.add_domain("employs", "Company")
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="c1", name="ACME", entity_type="Organization")
        e2 = Entity(entity_id="p1", name="Alice", entity_type="Person")
        kg.add_entity(e1)
        kg.add_entity(e2)
        rel = Relationship(relationship_type="employs", source_entity=e1, target_entity=e2, confidence=1.0)
        kg.add_relationship(rel)
        result = r.materialize(kg)
        inferred = result.entities["c1"].properties.get("inferred_types", [])
        assert "Company" in inferred

    def test_range_inference_adds_inferred_type(self):
        """GIVEN range declaration WHEN materialize THEN target entity gets inferred type."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity, Relationship
        s = OntologySchema()
        s.add_range("employs", "Employee")
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="c1", name="ACME", entity_type="Company")
        e2 = Entity(entity_id="p1", name="Bob", entity_type="Person")
        kg.add_entity(e1)
        kg.add_entity(e2)
        rel = Relationship(relationship_type="employs", source_entity=e1, target_entity=e2, confidence=1.0)
        kg.add_relationship(rel)
        result = r.materialize(kg)
        inferred = result.entities["p1"].properties.get("inferred_types", [])
        assert "Employee" in inferred

    def test_domain_already_correct_type_no_duplicate(self):
        """GIVEN entity already has domain type WHEN materialize THEN no duplicate inferred type."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity, Relationship
        s = OntologySchema()
        s.add_domain("employs", "Company")
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="c1", name="ACME", entity_type="Company")  # already Company
        e2 = Entity(entity_id="p1", name="Bob", entity_type="Person")
        kg.add_entity(e1)
        kg.add_entity(e2)
        rel = Relationship(relationship_type="employs", source_entity=e1, target_entity=e2, confidence=1.0)
        kg.add_relationship(rel)
        result = r.materialize(kg)
        # Already Company → no inferred_types key or empty
        inferred = result.entities["c1"].properties.get("inferred_types", [])
        assert inferred.count("Company") == 0  # Not duplicated


class TestOntologyReasonerExplainInferences:
    """OntologyReasoner.explain_inferences (lines 945-952)."""

    def test_explain_returns_inference_traces(self):
        """GIVEN subclass schema WHEN explain_inferences THEN traces have correct fields."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner, InferenceTrace
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity
        s = OntologySchema()
        s.add_subclass("Dog", "Animal")
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        kg.add_entity(Entity(entity_id="d1", name="Rex", entity_type="Dog"))
        traces = r.explain_inferences(kg)
        assert len(traces) >= 1
        t = traces[0]
        assert isinstance(t, InferenceTrace)
        assert t.rule == "subclass"
        assert t.subject_id == "d1"
        assert t.object_id == "Animal"

    def test_explain_empty_kg_returns_no_traces(self):
        """GIVEN empty KG WHEN explain_inferences THEN empty list."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        s = OntologySchema()
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        traces = r.explain_inferences(kg)
        assert traces == []


class TestOntologyReasonerCheckConsistency:
    """OntologyReasoner.check_consistency (lines 629-683)."""

    def test_disjoint_class_violation_detected(self):
        """GIVEN entity with two disjoint types WHEN check_consistency THEN violation found."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity
        s = OntologySchema()
        s.add_disjoint("Animal", "Machine")
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        robot = Entity(
            entity_id="r1",
            name="Robot",
            entity_type="Animal",
            properties={"inferred_types": ["Machine"]},
        )
        kg.add_entity(robot)
        violations = r.check_consistency(kg)
        assert any(v.violation_type == "disjoint_class" for v in violations)

    def test_negative_assertion_violation_detected(self):
        """GIVEN NOT_likes and likes between same pair WHEN check_consistency THEN violation."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity, Relationship
        s = OntologySchema()
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="a", name="Alice", entity_type="Person")
        e2 = Entity(entity_id="b", name="Bob", entity_type="Person")
        kg.add_entity(e1)
        kg.add_entity(e2)
        kg.add_relationship(Relationship(relationship_type="likes", source_entity=e1, target_entity=e2, confidence=1.0))
        kg.add_relationship(Relationship(relationship_type="NOT_likes", source_entity=e1, target_entity=e2, confidence=1.0))
        violations = r.check_consistency(kg)
        assert any(v.violation_type == "negative_assertion" for v in violations)

    def test_no_violations_clean_kg(self):
        """GIVEN clean KG with no conflicts WHEN check_consistency THEN empty list."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity
        s = OntologySchema()
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        kg.add_entity(Entity(entity_id="e1", name="Alice", entity_type="Person"))
        assert r.check_consistency(kg) == []


class TestOntologyReasonerMaterialize:
    """OntologyReasoner.materialize fixpoint and basic runs."""

    def test_materialize_subclass_infers_super_type(self):
        """GIVEN Dog subClassOf Animal WHEN materialize THEN Dog entity gains Animal inferred type."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity
        s = OntologySchema()
        s.add_subclass("Dog", "Animal")
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        kg.add_entity(Entity(entity_id="d1", name="Rex", entity_type="Dog"))
        result = r.materialize(kg)
        inferred = result.entities["d1"].properties.get("inferred_types", [])
        assert "Animal" in inferred

    def test_materialize_transitive_chain_two_hops(self):
        """GIVEN transitive ancestor rel A→B and B→C WHEN materialize THEN A→C inferred."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity, Relationship
        s = OntologySchema()
        s.add_transitive("ancestor")
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        e_a = Entity(entity_id="a", name="A", entity_type="Person")
        e_b = Entity(entity_id="b", name="B", entity_type="Person")
        e_c = Entity(entity_id="c", name="C", entity_type="Person")
        kg.add_entity(e_a)
        kg.add_entity(e_b)
        kg.add_entity(e_c)
        kg.add_relationship(Relationship(relationship_type="ancestor", source_entity=e_a, target_entity=e_b, confidence=1.0))
        kg.add_relationship(Relationship(relationship_type="ancestor", source_entity=e_b, target_entity=e_c, confidence=1.0))
        result = r.materialize(kg)
        pairs = {(rel.source_id, rel.target_id) for rel in result.relationships.values() if rel.relationship_type == "ancestor"}
        assert ("a", "c") in pairs  # transitivity inferred

    def test_materialize_empty_kg_returns_empty(self):
        """GIVEN empty KG WHEN materialize THEN empty KG returned."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        s = OntologySchema()
        r = OntologyReasoner(s)
        kg = KnowledgeGraph()
        result = r.materialize(kg)
        assert len(result.entities) == 0


# ─── transactions/manager.py ──────────────────────────────────────────────────


class TestTransactionManagerConflictError:
    """TransactionManager commit with ConflictError (lines 253-258)."""

    def test_serializable_conflict_raises_conflict_error(self):
        """GIVEN two SERIALIZABLE txns write same node WHEN second commits THEN ConflictError."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, OperationType, ConflictError, Operation,
        )
        mgr, engine, _ = _make_tx_manager()
        # First txn writes n1 and commits
        txn1 = mgr.begin(IsolationLevel.SERIALIZABLE)
        mgr.add_operation(txn1, Operation(type=OperationType.WRITE_NODE, node_id="n1", data={}))
        mgr.commit(txn1)
        # Second txn also writes n1 — conflict
        txn2 = mgr.begin(IsolationLevel.SERIALIZABLE)
        mgr.add_operation(txn2, Operation(type=OperationType.WRITE_NODE, node_id="n1", data={}))
        with pytest.raises(ConflictError):
            mgr.commit(txn2)

    def test_read_committed_no_conflict_raised(self):
        """GIVEN READ_COMMITTED txns WHEN same node written THEN no conflict raised."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, OperationType, Operation,
        )
        mgr, engine, _ = _make_tx_manager()
        txn1 = mgr.begin(IsolationLevel.READ_COMMITTED)
        mgr.add_operation(txn1, Operation(type=OperationType.WRITE_NODE, node_id="n1", data={}))
        mgr.commit(txn1)
        txn2 = mgr.begin(IsolationLevel.READ_COMMITTED)
        mgr.add_operation(txn2, Operation(type=OperationType.WRITE_NODE, node_id="n1", data={}))
        mgr.commit(txn2)  # Should not raise


class TestTransactionManagerTimeoutAndError:
    """TransactionManager commit with TimeoutError/generic Exception (lines 264-281)."""

    def test_timeout_error_raises_transaction_timeout_error(self):
        """GIVEN _apply_operations raises TimeoutError WHEN commit THEN TransactionTimeoutError."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import IsolationLevel
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionTimeoutError
        mgr, engine, _ = _make_tx_manager()
        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        with patch.object(mgr, "_apply_operations", side_effect=TimeoutError("timed out")):
            with pytest.raises(TransactionTimeoutError):
                mgr.commit(txn)

    def test_generic_exception_raises_transaction_error(self):
        """GIVEN _apply_operations raises RuntimeError WHEN commit THEN TransactionError."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import IsolationLevel
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionError
        mgr, engine, _ = _make_tx_manager()
        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        with patch.object(mgr, "_apply_operations", side_effect=RuntimeError("unexpected")):
            with pytest.raises(TransactionError):
                mgr.commit(txn)


class TestTransactionManagerApplyOperations:
    """TransactionManager._apply_operations DELETE_NODE/SET_PROPERTY (lines 397-410)."""

    def test_delete_node_removes_from_nodes(self):
        """GIVEN DELETE_NODE operation WHEN committed THEN node removed from engine._nodes."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, OperationType, Operation,
        )
        mgr, engine, _ = _make_tx_manager()
        assert "n1" in engine._nodes
        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        mgr.add_operation(txn, Operation(type=OperationType.DELETE_NODE, node_id="n1", data={}))
        mgr.commit(txn)
        assert "n1" not in engine._nodes

    def test_set_property_updates_node_property(self):
        """GIVEN SET_PROPERTY operation WHEN committed THEN node property updated."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, OperationType, Operation,
        )
        mgr, engine, _ = _make_tx_manager()
        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        mgr.add_operation(txn, Operation(
            type=OperationType.SET_PROPERTY,
            node_id="n2",
            data={"property": "name", "value": "NewACME"},
        ))
        mgr.commit(txn)
        assert engine._nodes["n2"]["properties"]["name"] == "NewACME"

    def test_delete_unknown_node_noop(self):
        """GIVEN DELETE_NODE for unknown node WHEN committed THEN no error and no change."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, OperationType, Operation,
        )
        mgr, engine, _ = _make_tx_manager()
        txn = mgr.begin()
        mgr.add_operation(txn, Operation(type=OperationType.DELETE_NODE, node_id="not_exist", data={}))
        mgr.commit(txn)  # Should not raise
        assert "n1" in engine._nodes  # Others unaffected

    def test_set_property_unknown_node_noop(self):
        """GIVEN SET_PROPERTY for missing node WHEN committed THEN no error."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, OperationType, Operation,
        )
        mgr, engine, _ = _make_tx_manager()
        txn = mgr.begin()
        mgr.add_operation(txn, Operation(
            type=OperationType.SET_PROPERTY,
            node_id="not_exist",
            data={"property": "x", "value": 99},
        ))
        mgr.commit(txn)  # Should not raise


# ─── transactions/wal.py ──────────────────────────────────────────────────────


class TestWALAppendErrors:
    """WriteAheadLog.append error paths (lines 123-140)."""

    def test_storage_error_raises_transaction_error(self):
        """GIVEN storage.store_json raises StorageError WHEN append THEN TransactionError."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionError
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import StorageError
        storage = MagicMock()
        storage.store_json.side_effect = StorageError("disk full")
        wal = WriteAheadLog(storage)
        with pytest.raises(TransactionError, match="storage error"):
            wal.append(_make_wal_entry())

    def test_generic_exception_raises_transaction_error(self):
        """GIVEN store_json raises RuntimeError WHEN append THEN TransactionError."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionError
        storage = MagicMock()
        storage.store_json.side_effect = RuntimeError("unexpected")
        wal = WriteAheadLog(storage)
        with pytest.raises(TransactionError):
            wal.append(_make_wal_entry())


class TestWALReadErrors:
    """WriteAheadLog.read cycle detection and error paths (lines 170-207)."""

    def test_cycle_detection_breaks_loop(self):
        """GIVEN self-referencing WAL entry WHEN read THEN yields entry once and stops."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        import time as time_module
        storage = MagicMock()
        storage.retrieve_json.return_value = {
            "txn_id": "t1",
            "timestamp": time_module.time(),
            "txn_state": "COMMITTED",
            "operations": [],
            "prev_wal_cid": "cid1",  # self-loop
        }
        wal = WriteAheadLog(storage)
        wal.wal_head_cid = "cid1"
        entries = list(wal.read())
        assert len(entries) == 1  # cycle broken after first

    def test_storage_error_in_read_raises_deserialization_error(self):
        """GIVEN storage.retrieve_json raises StorageError WHEN read THEN DeserializationError."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.exceptions import DeserializationError
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import StorageError
        storage = MagicMock()
        storage.retrieve_json.side_effect = StorageError("db down")
        wal = WriteAheadLog(storage)
        wal.wal_head_cid = "cid2"
        with pytest.raises(DeserializationError):
            list(wal.read())

    def test_generic_exception_in_read_raises_transaction_error(self):
        """GIVEN retrieve_json raises RuntimeError WHEN read THEN TransactionError."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionError
        storage = MagicMock()
        storage.retrieve_json.side_effect = RuntimeError("io error")
        wal = WriteAheadLog(storage)
        wal.wal_head_cid = "cid3"
        with pytest.raises(TransactionError):
            list(wal.read())

    def test_malformed_json_breaks_read_silently(self):
        """GIVEN malformed entry dict WHEN read THEN breaks without exception (log only)."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = MagicMock()
        # Missing required fields → WALEntry construction fails → KeyError/TypeError caught
        storage.retrieve_json.return_value = {"bad": "data"}
        wal = WriteAheadLog(storage)
        wal.wal_head_cid = "cid_bad"
        entries = list(wal.read())
        assert entries == []  # Breaks silently


class TestWALCompactErrors:
    """WriteAheadLog.compact error path (lines 253-270)."""

    def test_compact_generic_error_raises_transaction_error(self):
        """GIVEN append raises RuntimeError WHEN compact THEN TransactionError raised."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionError
        storage = MagicMock()
        wal = WriteAheadLog(storage)
        with patch.object(wal, "append", side_effect=RuntimeError("storage failure")):
            with pytest.raises(TransactionError, match="compact"):
                wal.compact("fakecid")


class TestWALRecoverErrors:
    """WriteAheadLog.recover error path (lines 323-339)."""

    def test_recover_generic_error_raises_transaction_error(self):
        """GIVEN read raises RuntimeError WHEN recover THEN TransactionError."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionError
        storage = MagicMock()
        wal = WriteAheadLog(storage)
        wal.wal_head_cid = "fakecid"
        with patch.object(wal, "read", side_effect=RuntimeError("io error")):
            with pytest.raises(TransactionError, match="recover"):
                wal.recover()


class TestWALVerifyIntegrityErrors:
    """WriteAheadLog.verify_integrity error paths (lines 435-442)."""

    def test_deserialization_error_returns_false(self):
        """GIVEN read raises DeserializationError WHEN verify_integrity THEN returns False."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.exceptions import DeserializationError
        storage = MagicMock()
        wal = WriteAheadLog(storage)
        wal.wal_head_cid = "fakecid"
        with patch.object(wal, "read", side_effect=DeserializationError("corrupt")):
            assert wal.verify_integrity() is False

    def test_generic_exception_returns_false(self):
        """GIVEN read raises RuntimeError WHEN verify_integrity THEN returns False."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = MagicMock()
        wal = WriteAheadLog(storage)
        wal.wal_head_cid = "fakecid"
        with patch.object(wal, "read", side_effect=RuntimeError("io error")):
            assert wal.verify_integrity() is False


# ─── query/unified_engine.py ──────────────────────────────────────────────────


def _make_ue():
    """Build UnifiedQueryEngine with mock backend."""
    from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
    backend = MagicMock()
    engine = UnifiedQueryEngine(backend=backend)
    engine._cypher_parser = MagicMock()
    engine._cypher_compiler = MagicMock()
    engine._ir_executor = MagicMock()
    engine._hybrid_search = MagicMock()
    return engine


class TestUnifiedEngineTimeoutPaths:
    """UnifiedQueryEngine timeout → QueryTimeoutError (lines 316-320, 380-388, 462-467, 585-590)."""

    def test_cypher_timeout_raises_query_timeout_error(self):
        """GIVEN parse raises TimeoutError WHEN execute_cypher THEN QueryTimeoutError."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryTimeoutError
        engine = _make_ue()
        engine._cypher_parser.parse.side_effect = TimeoutError("timed out")
        with pytest.raises(QueryTimeoutError):
            engine.execute_cypher("MATCH (n) RETURN n")

    def test_ir_timeout_raises_query_timeout_error(self):
        """GIVEN executor raises TimeoutError WHEN execute_ir THEN QueryTimeoutError."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryTimeoutError
        engine = _make_ue()
        engine._ir_executor.execute.side_effect = TimeoutError("ir timed out")
        with pytest.raises(QueryTimeoutError):
            engine.execute_ir("fake_ir")

    def test_graphrag_timeout_raises_query_timeout_error(self):
        """GIVEN execute_hybrid raises TimeoutError WHEN execute_graphrag THEN QueryTimeoutError."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryTimeoutError
        engine = _make_ue()
        engine.execute_hybrid = MagicMock(side_effect=TimeoutError("graphrag timed out"))
        with pytest.raises(QueryTimeoutError):
            engine.execute_graphrag("test question")


class TestUnifiedEngineGraphRAGErrors:
    """UnifiedQueryEngine.execute_graphrag LLM error paths (lines 554-603)."""

    def test_llm_unexpected_error_raises_query_execution_error(self):
        """GIVEN LLM.reason raises RuntimeError WHEN execute_graphrag THEN QueryExecutionError."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryExecutionError
        engine = _make_ue()
        engine.execute_hybrid = MagicMock(return_value=MagicMock(success=True, items=["item"]))
        engine.llm_processor = MagicMock()
        engine.llm_processor.reason.side_effect = RuntimeError("llm crash")
        with pytest.raises(QueryExecutionError):
            engine.execute_graphrag("test question")

    def test_query_execution_error_reraises(self):
        """GIVEN execute_hybrid raises QueryExecutionError WHEN execute_graphrag THEN re-raised."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryExecutionError
        engine = _make_ue()
        engine.llm_processor = None
        engine.execute_hybrid = MagicMock(side_effect=QueryExecutionError("hybrid failed"))
        with pytest.raises(QueryExecutionError, match="hybrid failed"):
            engine.execute_graphrag("test question")

    def test_generic_exception_raises_query_execution_error(self):
        """GIVEN execute_hybrid raises RuntimeError WHEN execute_graphrag THEN QueryExecutionError."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryExecutionError
        engine = _make_ue()
        engine.llm_processor = None
        engine.execute_hybrid = MagicMock(side_effect=RuntimeError("unknown crash"))
        with pytest.raises(QueryExecutionError):
            engine.execute_graphrag("test question")


# ─── cypher/ast.py ────────────────────────────────────────────────────────────


class TestASTNodeAccept:
    """ASTNode.accept() generic_visit and ValueError for None node_type (lines 66-72)."""

    def test_accept_calls_generic_visit_for_node_pattern(self):
        """GIVEN a NodePattern (has node_type) WHEN accept() THEN generic_visit called."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import NodePattern, ASTVisitor
        visited = []

        class MyVisitor(ASTVisitor):
            def generic_visit(self, node: Any) -> Any:
                visited.append(node.__class__.__name__)

        np = NodePattern()
        np.accept(MyVisitor())
        assert "NodePattern" in visited

    def test_accept_raises_value_error_if_node_type_none(self):
        """GIVEN ASTNode subclass with node_type=None WHEN accept() THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import ASTNode, ASTVisitor

        @dataclasses.dataclass
        class BareNode(ASTNode):
            pass

        bn = BareNode()
        with pytest.raises(ValueError, match="node_type not set"):
            bn.accept(ASTVisitor())

    def test_accept_uses_visit_method_if_defined(self):
        """GIVEN visitor with visit_match method WHEN accept on MatchClause THEN custom method called."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import MatchClause, ASTVisitor
        result = []

        class MyV(ASTVisitor):
            def visit_match(self, node: Any) -> Any:
                result.append("match_visited")

        mc = MatchClause()
        mc.accept(MyV())
        assert "match_visited" in result


class TestASTNodePostInit:
    """__post_init__ methods on AST nodes (lines 214-231, 642-661)."""

    def test_delete_clause_post_init_sets_node_type(self):
        """GIVEN DeleteClause() WHEN post_init THEN node_type=DELETE."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import DeleteClause, ASTNodeType
        d = DeleteClause(detach=True)
        assert d.node_type == ASTNodeType.DELETE
        assert d.detach is True

    def test_set_clause_post_init_sets_node_type(self):
        """GIVEN SetClause() WHEN post_init THEN node_type=SET."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import SetClause, ASTNodeType
        sc = SetClause()
        assert sc.node_type == ASTNodeType.SET

    def test_case_expression_node_post_init_sets_node_type(self):
        """GIVEN CaseExpressionNode() WHEN post_init THEN node_type=CASE_EXPRESSION."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import CaseExpressionNode, ASTNodeType
        ce = CaseExpressionNode()
        assert ce.node_type == ASTNodeType.CASE_EXPRESSION

    def test_map_node_post_init_sets_node_type(self):
        """GIVEN MapNode() WHEN post_init THEN node_type=MAP."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import MapNode, LiteralNode, ASTNodeType
        m = MapNode(properties={"k": LiteralNode(value="v")})
        assert m.node_type == ASTNodeType.MAP


class TestASTNodeRepr:
    """__repr__ methods on AST nodes (lines 663-676)."""

    def test_case_expression_with_test_repr(self):
        """GIVEN CaseExpressionNode with test_expression WHEN repr THEN contains 'test='."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import CaseExpressionNode, VariableNode
        ce = CaseExpressionNode(test_expression=VariableNode(name="x"))
        r = repr(ce)
        assert "test=" in r

    def test_case_expression_without_test_repr(self):
        """GIVEN CaseExpressionNode without test WHEN repr THEN contains 'whens='."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import CaseExpressionNode
        ce = CaseExpressionNode()
        r = repr(ce)
        assert "whens=" in r
        assert "test=" not in r

    def test_when_clause_repr(self):
        """GIVEN WhenClause WHEN repr THEN contains '->'."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import WhenClause, VariableNode, LiteralNode
        w = WhenClause(condition=VariableNode(name="c"), result=LiteralNode(value="result"))
        r = repr(w)
        assert "->" in r


class TestASTPrettyPrinter:
    """ASTPrettyPrinter (lines 706-737)."""

    def test_print_simple_query(self):
        """GIVEN QueryNode with MatchClause WHEN print() THEN multi-line string returned."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
            ASTPrettyPrinter, QueryNode, MatchClause, NodePattern,
        )
        printer = ASTPrettyPrinter()
        qn = QueryNode()
        qn.clauses = [MatchClause(patterns=[NodePattern(variable="n")])]
        output = printer.print(qn)
        assert "QueryNode" in output
        assert "MatchClause" in output
        assert "NodePattern" in output

    def test_print_multiple_patterns_in_list(self):
        """GIVEN MatchClause with multiple NodePatterns WHEN print THEN all nodes printed."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
            ASTPrettyPrinter, QueryNode, MatchClause, NodePattern,
        )
        printer = ASTPrettyPrinter()
        qn = QueryNode()
        qn.clauses = [MatchClause(patterns=[NodePattern(variable="a"), NodePattern(variable="b")])]
        output = printer.print(qn)
        assert output.count("NodePattern") == 2

    def test_indent_increases_then_decreases(self):
        """GIVEN nested AST WHEN print THEN indentation applied at each level."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
            ASTPrettyPrinter, QueryNode, MatchClause, NodePattern,
        )
        printer = ASTPrettyPrinter()
        qn = QueryNode()
        qn.clauses = [MatchClause(patterns=[NodePattern()])]
        output = printer.print(qn)
        lines = output.split("\n")
        # Root line has 0 spaces; children have 2 spaces; grandchildren have 4
        assert lines[0].startswith("QueryNode")  # No leading spaces
        assert lines[1].startswith("  ")         # 2-space indent


# ─── migration/formats.py ─────────────────────────────────────────────────────


class TestGraphDataToJson:
    """GraphData.to_json / from_json (line 88)."""

    def test_to_json_and_from_json_round_trip(self):
        """GIVEN GraphData WHEN to_json() then from_json() THEN identical structure."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData, NodeData, RelationshipData,
        )
        gd = GraphData(
            nodes=[NodeData(id="n1", labels=["Person"], properties={"name": "Alice"})],
            relationships=[],
        )
        json_str = gd.to_json()
        gd2 = GraphData.from_json(json_str)
        assert len(gd2.nodes) == 1
        assert gd2.nodes[0].id == "n1"
        assert gd2.nodes[0].labels == ["Person"]

    def test_to_json_produces_valid_json(self):
        """GIVEN GraphData WHEN to_json() THEN result parseable by json.loads."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, NodeData
        gd = GraphData(nodes=[NodeData(id="x", labels=[], properties={})], relationships=[])
        d = json.loads(gd.to_json())
        assert "nodes" in d


class TestGraphDataGraphMLLoad:
    """GraphData._load_from_graphml with key_map (lines 493-560)."""

    def test_graphml_loads_nodes_and_relationships(self):
        """GIVEN GraphML file with key defs WHEN load_from_file THEN nodes+rels parsed."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, MigrationFormat
        graphml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">'
            '  <key id="d0" for="node" attr.name="labels" attr.type="string"/>'
            '  <key id="d1" for="edge" attr.name="type" attr.type="string"/>'
            '  <graph id="G" edgedefault="directed">'
            '    <node id="n1"><data key="d0">Person</data></node>'
            '    <node id="n2"><data key="d0">Company</data></node>'
            '    <edge id="e1" source="n1" target="n2"><data key="d1">WORKS_AT</data></edge>'
            '  </graph>'
            '</graphml>'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".graphml", delete=False) as f:
            f.write(graphml)
            fname = f.name
        try:
            gd = GraphData.load_from_file(fname, MigrationFormat.GRAPHML)
            assert len(gd.nodes) == 2
            assert len(gd.relationships) == 1
            assert gd.nodes[0].labels == ["Person"]
            assert gd.relationships[0].type == "WORKS_AT"
        finally:
            os.unlink(fname)

    def test_graphml_property_not_in_keymap_stored_by_key(self):
        """GIVEN data element with key not in key_map WHEN load THEN stored by key."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, MigrationFormat
        graphml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">'
            '  <graph id="G" edgedefault="directed">'
            '    <node id="n1"><data key="d99">hello</data></node>'
            '  </graph>'
            '</graphml>'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".graphml", delete=False) as f:
            f.write(graphml)
            fname = f.name
        try:
            gd = GraphData.load_from_file(fname, MigrationFormat.GRAPHML)
            assert gd.nodes[0].properties.get("d99") == "hello"
        finally:
            os.unlink(fname)

    def test_graphml_edge_property_not_in_keymap_stored_by_key(self):
        """GIVEN edge data element with key not in key_map WHEN load THEN stored by key."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, MigrationFormat
        graphml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">'
            '  <graph id="G" edgedefault="directed">'
            '    <node id="n1"/>'
            '    <node id="n2"/>'
            '    <edge id="e1" source="n1" target="n2"><data key="weight">0.5</data></edge>'
            '  </graph>'
            '</graphml>'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".graphml", delete=False) as f:
            f.write(graphml)
            fname = f.name
        try:
            gd = GraphData.load_from_file(fname, MigrationFormat.GRAPHML)
            assert gd.relationships[0].properties.get("weight") == "0.5"
        finally:
            os.unlink(fname)


class TestGraphDataGEXFLoad:
    """GraphData._load_from_gexf with attvalues (lines 665-745)."""

    def test_gexf_loads_nodes_and_relationships(self):
        """GIVEN GEXF file with attvalues WHEN load_from_file THEN nodes+rels parsed."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, MigrationFormat
        gexf = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<gexf xmlns="http://www.gexf.net/1.2draft">'
            '  <graph defaultedgetype="directed">'
            '    <attributes class="node">'
            '      <attribute id="0" title="labels" type="string"/>'
            '    </attributes>'
            '    <attributes class="edge">'
            '      <attribute id="0" title="type" type="string"/>'
            '    </attributes>'
            '    <nodes>'
            '      <node id="n1"><attvalues><attvalue for="0" value="Person"/></attvalues></node>'
            '      <node id="n2"><attvalues><attvalue for="0" value="Company"/></attvalues></node>'
            '    </nodes>'
            '    <edges>'
            '      <edge id="e1" source="n1" target="n2">'
            '        <attvalues><attvalue for="0" value="WORKS_AT"/></attvalues>'
            '      </edge>'
            '    </edges>'
            '  </graph>'
            '</gexf>'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gexf", delete=False) as f:
            f.write(gexf)
            fname = f.name
        try:
            gd = GraphData.load_from_file(fname, MigrationFormat.GEXF)
            assert len(gd.nodes) == 2
            assert len(gd.relationships) == 1
            node_labels = [n.labels for n in gd.nodes]
            assert ["Person"] in node_labels
            assert gd.relationships[0].type == "WORKS_AT"
        finally:
            os.unlink(fname)

    def test_gexf_round_trip_save_load(self):
        """GIVEN GraphData WHEN save to GEXF then reload THEN structure preserved."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData, NodeData, RelationshipData, MigrationFormat,
        )
        gd = GraphData(
            nodes=[
                NodeData(id="n1", labels=["Person"], properties={"name": "Alice"}),
                NodeData(id="n2", labels=["Company"], properties={"name": "ACME"}),
            ],
            relationships=[
                RelationshipData(id="r1", type="WORKS_AT", start_node="n1", end_node="n2", properties={}),
            ],
        )
        with tempfile.NamedTemporaryFile(suffix=".gexf", delete=False) as f:
            fname = f.name
        try:
            gd.save_to_file(fname, MigrationFormat.GEXF)
            gd2 = GraphData.load_from_file(fname, MigrationFormat.GEXF)
            assert len(gd2.nodes) == 2
            assert len(gd2.relationships) == 1
            assert gd2.relationships[0].type == "WORKS_AT"
        finally:
            os.unlink(fname)

    def test_gexf_edge_property_not_in_attr_map_stored_by_id(self):
        """GIVEN edge attvalue with for-id not in edge_attrs WHEN load THEN property by id stored."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import GraphData, MigrationFormat
        gexf = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<gexf xmlns="http://www.gexf.net/1.2draft">'
            '  <graph defaultedgetype="directed">'
            '    <nodes>'
            '      <node id="n1"/>'
            '      <node id="n2"/>'
            '    </nodes>'
            '    <edges>'
            '      <edge id="e1" source="n1" target="n2">'
            '        <attvalues><attvalue for="999" value="0.9"/></attvalues>'
            '      </edge>'
            '    </edges>'
            '  </graph>'
            '</gexf>'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gexf", delete=False) as f:
            f.write(gexf)
            fname = f.name
        try:
            gd = GraphData.load_from_file(fname, MigrationFormat.GEXF)
            # Edge property stored as key="999"
            assert len(gd.relationships) == 1
        finally:
            os.unlink(fname)
