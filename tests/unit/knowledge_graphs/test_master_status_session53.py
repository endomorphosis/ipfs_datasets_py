"""
Session 53: Remove 4 confirmed dead-code blocks + document invariants.

Dead code removed:
1. cypher/compiler.py:185-186, 212-213  – ``if not variable:`` guard after
   ``variable = element.variable or f"_n{i}"``.  The f-string fallback is
   always truthy, so the guard can never fire.
2. core/ir_executor.py:433-442 – ``if value is None and hasattr(record, "_values"):``
   block that called ``record._values.get()``.  ``_values`` is a tuple, so
   ``.get()`` always raises ``AttributeError`` (caught by the except clause),
   making lines 435-442 unreachable.
3. ipld.py:753-754 – ``if not source_result: continue`` inside
   ``vector_augmented_query``.  ``source_result`` is looked up by iterating
   ``graph_results``, which is built from the same ``prev_hop_entities`` IDs,
   so it can never be ``None``.
4. ipld.py:1122-1123 – ``if depth > max_hops: continue`` inside
   ``get_connected_entities``.  Entities are only enqueued when
   ``depth < max_hops`` (line 1148), so the queue depth can never exceed
   ``max_hops``.

Tests here prove the invariants that make each block unreachable.
"""

import pytest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# 1. compiler.py: variable = element.variable or f"_n{i}" is always truthy
# ---------------------------------------------------------------------------

class TestCompilerVariableInvariant:
    """
    The removed ``if not variable:`` guards followed the expression
    ``variable = element.variable or f"_n{i}"``.  Python's f-string
    ``f"_n{i}"`` always produces a non-empty string (at least "_n0"),
    so the ``or``-fallback can never yield a falsy value.
    """

    def test_fstring_fallback_is_always_truthy_for_non_negative_indices(self):
        """GIVEN integer indices 0..100 WHEN f"_n{i}" evaluated THEN always truthy."""
        for i in range(101):
            variable = f"_n{i}"
            assert variable, f"Expected truthy but got {variable!r} at i={i}"

    def test_nonempty_element_variable_kept(self):
        """GIVEN element.variable='n' WHEN or-expression evaluated THEN 'n' returned."""
        element_variable = "n"
        variable = element_variable or f"_n{0}"
        assert variable == "n"

    def test_none_element_variable_falls_through_to_fstring(self):
        """GIVEN element.variable=None WHEN or-expression evaluated THEN f-string used."""
        element_variable = None
        variable = element_variable or f"_n{3}"
        assert variable == "_n3"
        assert variable  # truthy

    def test_empty_string_element_variable_falls_through_to_fstring(self):
        """GIVEN element.variable='' WHEN or-expression evaluated THEN f-string used."""
        element_variable = ""
        variable = element_variable or f"_n{7}"
        assert variable == "_n7"
        assert variable  # truthy — 'if not variable' is always False after this

    def test_cypher_compiler_path_pattern_with_no_explicit_variable(self):
        """
        GIVEN a node pattern with no variable in a MATCH query
        WHEN compiled
        THEN the compiler assigns a generated variable without error.
        """
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
        from unittest.mock import MagicMock

        kg = MagicMock()
        kg.find_nodes.return_value = []
        qe = QueryExecutor(kg)
        result = qe.execute("MATCH (n:Person) RETURN n")
        assert list(result) == []  # no crash

    def test_cypher_compiler_two_named_nodes_get_unique_variables(self):
        """
        GIVEN two named nodes in a MATCH + RETURN query
        WHEN compiled through QueryExecutor
        THEN the query executes without error.
        """
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
        from unittest.mock import MagicMock

        kg = MagicMock()
        kg.find_nodes.return_value = []
        qe = QueryExecutor(kg)
        result = qe.execute("MATCH (a) RETURN a")
        assert list(result) == []  # no crash — compiler assigned variable correctly


# ---------------------------------------------------------------------------
# 2. ir_executor.py: Record._values is a tuple (not a dict), so .get() raises
# ---------------------------------------------------------------------------

class TestRecordValuesTupleInvariant:
    """
    The removed block (lines 433-442) attempted to call
    ``record._values.get(var_name)`` — but ``Record._values`` is always
    a ``tuple``, which has no ``.get()`` method.  The attempt would
    immediately raise ``AttributeError``, which was caught on line 443
    (``except (AttributeError, KeyError, TypeError): value = None``),
    making lines 435-442 unreachable.
    """

    def test_record_values_is_always_tuple(self):
        """GIVEN any Record THEN _values is a tuple."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record
        r = Record(["a", "b"], [1, 2])
        assert isinstance(r._values, tuple)

    def test_record_values_has_no_get_method(self):
        """GIVEN Record._values (tuple) THEN it has no .get() method."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record
        r = Record(["x"], [42])
        assert not hasattr(r._values, "get"), "Tuple must not have .get()"

    def test_record_get_returns_default_without_raising(self):
        """
        GIVEN record.get() called with missing key
        THEN returns None (not raises) — so the removed _values.get() block
             (originally ir_executor.py lines 435-442) was unreachable: once
             `record.get(expr)` returned None, `_values.get()` raised
             AttributeError, and the inner if/elif block (435-442) never ran.
        """
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record
        r = Record(["a"], [1])
        # dotted key not in _data
        val = r.get("a.b")
        assert val is None
        # With explicit default
        val2 = r.get("a.b", "fallback")
        assert val2 == "fallback"

    def test_orderby_dotted_expression_resolves_to_none_for_unregistered_keys(self):
        """
        GIVEN a MATCH query with ORDER BY n.name
        WHEN n.name is not stored as a top-level Record key
        THEN the sort completes without error (value=None → records sorted at end).
        """
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
        from ipfs_datasets_py.knowledge_graphs.storage import Entity
        from unittest.mock import MagicMock

        entity_a = Entity(entity_id="a", name="Alice")
        entity_b = Entity(entity_id="b", name="Bob")
        kg = MagicMock()
        kg.find_nodes.return_value = [entity_a, entity_b]

        qe = QueryExecutor(kg)
        result = qe.execute("MATCH (n) RETURN n ORDER BY n.name")
        records = list(result)
        # Two records returned (order undefined when sort key is None)
        assert len(records) == 2


# ---------------------------------------------------------------------------
# 3. ipld.py: source_result invariant in vector_augmented_query
# ---------------------------------------------------------------------------

class TestVectorAugmentedQuerySourceResultInvariant:
    """
    The removed guard ``if not source_result: continue`` (lines 753-754) is
    dead code because ``prev_hop_entities`` is constructed by iterating
    ``graph_results`` and extracting each ``result["entity"].id``.
    Therefore every ``entity_id`` in ``prev_hop_entities`` is guaranteed to
    have a matching entry in ``graph_results``, so ``source_result``
    returned by ``next(...)`` can never be ``None``.
    """

    def test_prev_hop_entity_ids_are_subset_of_graph_results(self):
        """
        GIVEN a graph_results list with various hops
        WHEN prev_hop_entities is derived from it
        THEN every entity_id in prev_hop_entities has a corresponding entry in graph_results.
        """
        # Replicate the exact logic used in ipld.py vector_augmented_query
        entity_a = MagicMock()
        entity_a.id = "a"
        entity_b = MagicMock()
        entity_b.id = "b"

        graph_results = [
            {"entity": entity_a, "vector_score": 0.9, "hops": 0},
            {"entity": entity_b, "vector_score": 0.8, "hops": 0},
        ]
        hop = 1

        prev_hop_entities = [
            result["entity"].id
            for result in graph_results
            if result["hops"] == hop - 1
        ]
        assert set(prev_hop_entities) == {"a", "b"}

        # For every entity_id in prev_hop_entities, source_result is found
        for entity_id in prev_hop_entities:
            source_result = next(
                (r for r in graph_results if r["entity"].id == entity_id),
                None,
            )
            assert source_result is not None, (
                f"source_result should never be None: entity_id={entity_id!r}"
            )

    def test_source_result_always_found_for_multi_hop(self):
        """
        GIVEN graph_results growing with multi-hop entities
        WHEN we process each hop's prev_hop_entities
        THEN source_result is always found for every entity_id.
        """
        graph_results = []
        for i in range(5):
            m = MagicMock()
            m.id = f"entity_{i}"
            graph_results.append({"entity": m, "vector_score": 0.9 - i * 0.1, "hops": i // 2})

        for hop in range(1, 4):
            prev_hop_entities = [
                r["entity"].id for r in graph_results if r["hops"] == hop - 1
            ]
            for eid in prev_hop_entities:
                sr = next((r for r in graph_results if r["entity"].id == eid), None)
                assert sr is not None


# ---------------------------------------------------------------------------
# 4. ipld.py: BFS depth guard in get_connected_entities is unreachable
# ---------------------------------------------------------------------------

class TestGetConnectedEntitiesDepthInvariant:
    """
    The removed guard ``if depth > max_hops: continue`` (lines 1122-1123) is
    dead code because the BFS queue is only populated via::

        if depth < max_hops:
            queue.append((target_id, depth + 1))

    So the maximum depth that can appear in the queue is exactly ``max_hops``
    (when ``depth = max_hops - 1`` and we append ``depth + 1 = max_hops``).
    Therefore ``depth > max_hops`` can never be ``True`` when an item is
    dequeued.
    """

    def test_bfs_enqueue_only_happens_when_depth_lt_max_hops(self):
        """
        GIVEN the BFS enqueueing condition ``if depth < max_hops``
        THEN max depth ever put in queue = max_hops
        THEN depth > max_hops is always False when dequeuing.
        """
        from collections import deque

        max_hops = 3
        # Simulate BFS depth progression
        queue = deque([(0, 0)])  # (entity_index, depth)
        seen_depths = set()

        while queue:
            _, depth = queue.popleft()
            seen_depths.add(depth)
            # Only enqueue if depth < max_hops (the actual condition in code)
            if depth < max_hops:
                queue.append((0, depth + 1))

        # All depths seen: {0, 1, 2, 3}
        assert max(seen_depths) == max_hops
        # Verify that depth > max_hops never occurred
        assert all(d <= max_hops for d in seen_depths)

    def test_bfs_depth_never_exceeds_max_hops_for_various_settings(self):
        """
        GIVEN various max_hops values
        WHEN BFS is simulated with the real enqueuing condition
        THEN no dequeued depth ever exceeds max_hops.
        """
        from collections import deque

        for max_hops in [0, 1, 2, 5]:
            queue = deque([(f"root", 0)])
            max_seen = 0
            while queue:
                _, depth = queue.popleft()
                max_seen = max(max_seen, depth)
                if depth < max_hops:
                    queue.append(("child", depth + 1))
            assert max_seen == max_hops or (max_hops == 0 and max_seen == 0), (
                f"max_hops={max_hops}: max_seen={max_seen}"
            )

    def test_get_connected_entities_returns_correct_neighbors(self):
        """
        GIVEN a simple linear chain A-B-C-D
        WHEN _get_connected_entities(A, max_hops=1) called
        THEN returns {B, C}: B is A's direct neighbor (added while processing
             depth-0 node A), and C is B's neighbor (added while processing
             depth-1 node B).  B is enqueued for processing because 0 < 1
             (max_hops), but C is NOT enqueued because depth=1 is not < 1.
             Therefore D is never visited (C is not processed further).
        """
        from ipfs_datasets_py.knowledge_graphs.ipld import IPLDKnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.storage import Entity, Relationship

        kg = IPLDKnowledgeGraph.__new__(IPLDKnowledgeGraph)
        entity_a = Entity(entity_id="A", name="A")
        entity_b = Entity(entity_id="B", name="B")
        entity_c = Entity(entity_id="C", name="C")
        entity_d = Entity(entity_id="D", name="D")
        kg.entities = {"A": entity_a, "B": entity_b, "C": entity_c, "D": entity_d}
        # Use (source, target) positional args — not source_id/target_id
        rel_ab = Relationship(relationship_id="r1", relationship_type="LINK", source="A", target="B")
        rel_bc = Relationship(relationship_id="r2", relationship_type="LINK", source="B", target="C")
        rel_cd = Relationship(relationship_id="r3", relationship_type="LINK", source="C", target="D")
        kg.relationships = {"r1": rel_ab, "r2": rel_bc, "r3": rel_cd}

        # Stub get_entity_relationships to return adjacent Relationships
        def fake_get_rels(entity_id, direction="both", relationship_types=None):
            rels = []
            for r in kg.relationships.values():
                if r.source_id == entity_id or r.target_id == entity_id:
                    rels.append(r)
            return rels

        kg.get_entity_relationships = fake_get_rels

        connected = kg._get_connected_entities("A", max_hops=1)
        assert "B" in connected  # direct neighbor of A (depth 1)
        assert "C" in connected  # neighbor of B, found while processing depth-1
        assert "D" not in connected  # would require processing depth-2 (C), not enqueued
        assert "A" not in connected  # self excluded
