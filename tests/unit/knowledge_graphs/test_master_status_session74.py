"""
Session 74 — Federated Knowledge Graphs tests.

Validates:
1. FederatedKnowledgeGraph: add_graph / get_graph / list_graphs / num_graphs
2. EntityResolutionStrategy: all three modes
3. resolve_entities: exact_name, type_and_name, property_match
4. get_entity_cluster / query_entity
5. execute_across: normal case, error handling, merge counts
6. to_merged_graph: entity deduplication, property merging, relationship remapping
7. Module exports (query/__init__.py)
8. Doc integrity (DEFERRED_FEATURES, ROADMAP, MASTER_STATUS, CHANGELOG)
9. Version agreement
"""
import os
import sys
import unittest

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_KG_ROOT = os.path.join(_REPO_ROOT, "ipfs_datasets_py", "knowledge_graphs")

sys.path.insert(0, _REPO_ROOT)


def _read(relpath: str) -> str:
    with open(os.path.join(_KG_ROOT, relpath), encoding="utf-8") as fh:
        return fh.read()


def _read_tests(relpath: str) -> str:
    with open(os.path.join(_REPO_ROOT, "tests", relpath), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Import the production module
# ---------------------------------------------------------------------------
from ipfs_datasets_py.knowledge_graphs.query.federation import (
    FederatedKnowledgeGraph,
    EntityResolutionStrategy,
    EntityMatch,
    FederationQueryResult,
)
from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _make_two_graphs():
    """Two independent graphs with Alice appearing in both."""
    kg_a = KnowledgeGraph(name="hr")
    alice_a = kg_a.add_entity("person", "Alice", properties={"dept": "eng"})
    bob_a = kg_a.add_entity("person", "Bob")
    kg_a.add_relationship("manages", alice_a, bob_a)

    kg_b = KnowledgeGraph(name="crm")
    alice_b = kg_b.add_entity("person", "Alice", properties={"region": "west"})
    acme = kg_b.add_entity("company", "Acme")
    kg_b.add_relationship("works_at", alice_b, acme)

    return kg_a, kg_b, alice_a, alice_b, bob_a, acme


def _make_fed():
    kg_a, kg_b, *_ = _make_two_graphs()
    fed = FederatedKnowledgeGraph()
    fed.add_graph(kg_a, name="hr")
    fed.add_graph(kg_b, name="crm")
    return fed, kg_a, kg_b


# ---------------------------------------------------------------------------
# 1. Graph registration API
# ---------------------------------------------------------------------------

class TestGraphRegistration(unittest.TestCase):
    def test_add_graph_returns_zero_indexed_int(self):
        fed = FederatedKnowledgeGraph()
        kg = KnowledgeGraph(name="test")
        idx = fed.add_graph(kg)
        self.assertEqual(idx, 0)

    def test_add_multiple_graphs_increments_index(self):
        fed = FederatedKnowledgeGraph()
        i0 = fed.add_graph(KnowledgeGraph(name="g0"))
        i1 = fed.add_graph(KnowledgeGraph(name="g1"))
        i2 = fed.add_graph(KnowledgeGraph(name="g2"))
        self.assertEqual([i0, i1, i2], [0, 1, 2])

    def test_num_graphs_reflects_count(self):
        fed = FederatedKnowledgeGraph()
        self.assertEqual(fed.num_graphs, 0)
        fed.add_graph(KnowledgeGraph())
        self.assertEqual(fed.num_graphs, 1)
        fed.add_graph(KnowledgeGraph())
        self.assertEqual(fed.num_graphs, 2)

    def test_get_graph_returns_registered_kg(self):
        fed = FederatedKnowledgeGraph()
        kg = KnowledgeGraph(name="mykg")
        fed.add_graph(kg)
        self.assertIs(fed.get_graph(0), kg)

    def test_list_graphs_returns_index_name_pairs(self):
        fed = FederatedKnowledgeGraph()
        fed.add_graph(KnowledgeGraph(name="alpha"), name="Alpha")
        fed.add_graph(KnowledgeGraph(name="beta"), name="Beta")
        result = fed.list_graphs()
        self.assertEqual(result, [(0, "Alpha"), (1, "Beta")])

    def test_add_graph_default_name_from_kg_name(self):
        fed = FederatedKnowledgeGraph()
        kg = KnowledgeGraph(name="custom_name")
        fed.add_graph(kg)
        self.assertEqual(fed.list_graphs(), [(0, "custom_name")])


# ---------------------------------------------------------------------------
# 2. EntityResolutionStrategy enum
# ---------------------------------------------------------------------------

class TestEntityResolutionStrategy(unittest.TestCase):
    def test_all_three_strategies_exist(self):
        strategies = list(EntityResolutionStrategy)
        self.assertIn(EntityResolutionStrategy.EXACT_NAME, strategies)
        self.assertIn(EntityResolutionStrategy.TYPE_AND_NAME, strategies)
        self.assertIn(EntityResolutionStrategy.PROPERTY_MATCH, strategies)

    def test_strategy_is_str_enum(self):
        self.assertIsInstance(EntityResolutionStrategy.TYPE_AND_NAME, str)

    def test_get_fingerprint_exact_name(self):
        kg = KnowledgeGraph()
        e = kg.add_entity("person", "Alice")
        fp = FederatedKnowledgeGraph.get_entity_fingerprint(
            e, EntityResolutionStrategy.EXACT_NAME
        )
        self.assertEqual(fp, "alice")

    def test_get_fingerprint_type_and_name(self):
        kg = KnowledgeGraph()
        e = kg.add_entity("person", "Alice")
        fp = FederatedKnowledgeGraph.get_entity_fingerprint(
            e, EntityResolutionStrategy.TYPE_AND_NAME
        )
        self.assertEqual(fp, "person:alice")

    def test_different_types_different_fingerprints(self):
        kg = KnowledgeGraph()
        ep = kg.add_entity("person", "Alice")
        ec = kg.add_entity("company", "Alice")
        fp_p = FederatedKnowledgeGraph.get_entity_fingerprint(ep, EntityResolutionStrategy.TYPE_AND_NAME)
        fp_c = FederatedKnowledgeGraph.get_entity_fingerprint(ec, EntityResolutionStrategy.TYPE_AND_NAME)
        self.assertNotEqual(fp_p, fp_c)

    def test_same_type_and_name_same_fingerprint(self):
        kg1 = KnowledgeGraph()
        kg2 = KnowledgeGraph()
        e1 = kg1.add_entity("person", "Alice")
        e2 = kg2.add_entity("person", "Alice")
        fp1 = FederatedKnowledgeGraph.get_entity_fingerprint(e1, EntityResolutionStrategy.TYPE_AND_NAME)
        fp2 = FederatedKnowledgeGraph.get_entity_fingerprint(e2, EntityResolutionStrategy.TYPE_AND_NAME)
        self.assertEqual(fp1, fp2)


# ---------------------------------------------------------------------------
# 3. resolve_entities
# ---------------------------------------------------------------------------

class TestResolveEntities(unittest.TestCase):
    def test_no_graphs_returns_empty(self):
        fed = FederatedKnowledgeGraph()
        self.assertEqual(fed.resolve_entities(), [])

    def test_one_graph_returns_empty(self):
        fed = FederatedKnowledgeGraph()
        fed.add_graph(KnowledgeGraph())
        self.assertEqual(fed.resolve_entities(), [])

    def test_exact_match_by_type_and_name(self):
        fed, _, _ = _make_fed()
        matches = fed.resolve_entities(EntityResolutionStrategy.TYPE_AND_NAME)
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertIsInstance(m, EntityMatch)
        self.assertEqual(m.kg_a_index, 0)
        self.assertEqual(m.kg_b_index, 1)
        self.assertEqual(m.strategy, EntityResolutionStrategy.TYPE_AND_NAME)
        self.assertAlmostEqual(m.score, 1.0)

    def test_exact_name_matches_despite_type_difference(self):
        """EXACT_NAME ignores entity_type — person:Alice should match company:Alice."""
        kg_a = KnowledgeGraph()
        kg_a.add_entity("person", "Alice")
        kg_b = KnowledgeGraph()
        kg_b.add_entity("company", "Alice")
        fed = FederatedKnowledgeGraph()
        fed.add_graph(kg_a)
        fed.add_graph(kg_b)
        matches = fed.resolve_entities(EntityResolutionStrategy.EXACT_NAME)
        self.assertEqual(len(matches), 1)

    def test_type_and_name_does_not_cross_type_boundary(self):
        """TYPE_AND_NAME: person:Alice ≠ company:Alice."""
        kg_a = KnowledgeGraph()
        kg_a.add_entity("person", "Alice")
        kg_b = KnowledgeGraph()
        kg_b.add_entity("company", "Alice")
        fed = FederatedKnowledgeGraph()
        fed.add_graph(kg_a)
        fed.add_graph(kg_b)
        matches = fed.resolve_entities(EntityResolutionStrategy.TYPE_AND_NAME)
        self.assertEqual(len(matches), 0)

    def test_property_match_requires_shared_property(self):
        """PROPERTY_MATCH: matching (type,name) but no overlapping props → no match."""
        kg_a = KnowledgeGraph()
        kg_a.add_entity("person", "Alice", properties={"dept": "eng"})
        kg_b = KnowledgeGraph()
        kg_b.add_entity("person", "Alice", properties={"region": "west"})
        fed = FederatedKnowledgeGraph()
        fed.add_graph(kg_a)
        fed.add_graph(kg_b)
        # No shared property → no match
        matches = fed.resolve_entities(EntityResolutionStrategy.PROPERTY_MATCH)
        self.assertEqual(len(matches), 0)

    def test_property_match_with_shared_property(self):
        """PROPERTY_MATCH: matching (type,name) with a shared prop → match."""
        kg_a = KnowledgeGraph()
        kg_a.add_entity("person", "Alice", properties={"dept": "eng", "country": "US"})
        kg_b = KnowledgeGraph()
        kg_b.add_entity("person", "Alice", properties={"country": "US"})
        fed = FederatedKnowledgeGraph()
        fed.add_graph(kg_a)
        fed.add_graph(kg_b)
        matches = fed.resolve_entities(EntityResolutionStrategy.PROPERTY_MATCH)
        self.assertEqual(len(matches), 1)

    def test_multiple_matches_across_three_graphs(self):
        """Three graphs, Alice appears in all → 3 pairs (0-1, 0-2, 1-2)."""
        graphs = []
        for _ in range(3):
            kg = KnowledgeGraph()
            kg.add_entity("person", "Alice")
            graphs.append(kg)
        fed = FederatedKnowledgeGraph()
        for kg in graphs:
            fed.add_graph(kg)
        matches = fed.resolve_entities()
        self.assertEqual(len(matches), 3)


# ---------------------------------------------------------------------------
# 4. get_entity_cluster / query_entity
# ---------------------------------------------------------------------------

class TestEntityLookup(unittest.TestCase):
    def test_get_entity_cluster_finds_all_occurrences(self):
        fed, _, _ = _make_fed()
        cluster = fed.get_entity_cluster("person:alice")
        self.assertEqual(len(cluster), 2)
        indices = {gi for gi, _ in cluster}
        self.assertEqual(indices, {0, 1})

    def test_get_entity_cluster_returns_empty_for_absent(self):
        fed, _, _ = _make_fed()
        cluster = fed.get_entity_cluster("person:nobody")
        self.assertEqual(cluster, [])

    def test_query_entity_by_name(self):
        fed, _, _ = _make_fed()
        hits = fed.query_entity(name="Alice")
        self.assertEqual(len(hits), 2)

    def test_query_entity_by_type(self):
        fed, _, _ = _make_fed()
        hits = fed.query_entity(entity_type="company")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0], 1)  # from kg_b

    def test_query_entity_by_type_and_name(self):
        fed, _, _ = _make_fed()
        hits = fed.query_entity(name="Alice", entity_type="person")
        self.assertEqual(len(hits), 2)

    def test_query_entity_no_match(self):
        fed, _, _ = _make_fed()
        hits = fed.query_entity(name="Nobody")
        self.assertEqual(hits, [])

    def test_query_entity_no_filters_returns_all(self):
        fed, kg_a, kg_b = _make_fed()
        total = len(kg_a.entities) + len(kg_b.entities)
        hits = fed.query_entity()
        self.assertEqual(len(hits), total)


# ---------------------------------------------------------------------------
# 5. execute_across
# ---------------------------------------------------------------------------

class TestExecuteAcross(unittest.TestCase):
    def test_returns_federation_query_result(self):
        fed, _, _ = _make_fed()
        result = fed.execute_across(lambda kg: list(kg.entities.values()))
        self.assertIsInstance(result, FederationQueryResult)

    def test_per_graph_results_count(self):
        fed, _, _ = _make_fed()
        result = fed.execute_across(lambda kg: list(kg.entities.values()))
        self.assertEqual(len(result.per_graph_results), 2)

    def test_merged_entities_concatenated(self):
        fed, kg_a, kg_b = _make_fed()
        result = fed.execute_across(lambda kg: list(kg.entities.values()))
        total = len(kg_a.entities) + len(kg_b.entities)
        self.assertEqual(result.total_matches, total)

    def test_error_captured_not_raised(self):
        fed, _, _ = _make_fed()
        def bad_fn(kg):
            raise ValueError("oops")
        result = fed.execute_across(bad_fn)
        self.assertEqual(len(result.query_errors), 2)

    def test_partial_error_still_returns_ok_results(self):
        fed, _, _ = _make_fed()
        call_count = [0]
        def sometimes_bad(kg):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first graph fails")
            return list(kg.entities.values())
        result = fed.execute_across(sometimes_bad)
        self.assertEqual(len(result.query_errors), 1)
        self.assertEqual(len(result.per_graph_results), 1)


# ---------------------------------------------------------------------------
# 6. to_merged_graph
# ---------------------------------------------------------------------------

class TestToMergedGraph(unittest.TestCase):
    def test_returns_knowledge_graph(self):
        fed, _, _ = _make_fed()
        merged = fed.to_merged_graph()
        self.assertIsInstance(merged, KnowledgeGraph)

    def test_entity_deduplication(self):
        """Alice appears in both graphs → only once in merged."""
        fed, kg_a, kg_b = _make_fed()
        merged = fed.to_merged_graph()
        # kg_a: Alice, Bob (2) + kg_b: Alice (dup), Acme (1) → 3 unique
        self.assertEqual(len(merged.entities), 3)

    def test_property_merging(self):
        """Merged Alice should have both dept and region."""
        fed, _, _ = _make_fed()
        merged = fed.to_merged_graph()
        alice_list = merged.get_entities_by_name("Alice")
        self.assertEqual(len(alice_list), 1)
        alice = alice_list[0]
        self.assertIn("dept", alice.properties)
        self.assertIn("region", alice.properties)

    def test_relationship_count(self):
        """manages + works_at — no deduplication needed."""
        fed, _, _ = _make_fed()
        merged = fed.to_merged_graph()
        self.assertEqual(len(merged.relationships), 2)

    def test_merged_graph_name_default(self):
        fed, _, _ = _make_fed()
        merged = fed.to_merged_graph()
        self.assertIn("hr", merged.name)
        self.assertIn("crm", merged.name)

    def test_merged_graph_custom_name(self):
        fed, _, _ = _make_fed()
        merged = fed.to_merged_graph(merged_name="mymerged")
        self.assertEqual(merged.name, "mymerged")

    def test_empty_federation_returns_empty_graph(self):
        fed = FederatedKnowledgeGraph()
        merged = fed.to_merged_graph()
        self.assertEqual(len(merged.entities), 0)
        self.assertEqual(len(merged.relationships), 0)

    def test_single_graph_merge_is_copy(self):
        kg = KnowledgeGraph()
        kg.add_entity("person", "Alice")
        fed = FederatedKnowledgeGraph()
        fed.add_graph(kg)
        merged = fed.to_merged_graph()
        self.assertEqual(len(merged.entities), 1)


# ---------------------------------------------------------------------------
# 7. Module exports
# ---------------------------------------------------------------------------

class TestFederationModuleExports(unittest.TestCase):
    def test_import_from_query_init(self):
        from ipfs_datasets_py.knowledge_graphs.query import (
            FederatedKnowledgeGraph as FKGL,
            EntityResolutionStrategy as ERS,
            EntityMatch as EM,
            FederationQueryResult as FQR,
        )
        self.assertIs(FKGL, FederatedKnowledgeGraph)
        self.assertIs(ERS, EntityResolutionStrategy)
        self.assertIs(EM, EntityMatch)
        self.assertIs(FQR, FederationQueryResult)

    def test_symbols_in_all(self):
        import ipfs_datasets_py.knowledge_graphs.query as q_mod
        for sym in [
            "FederatedKnowledgeGraph",
            "EntityResolutionStrategy",
            "EntityMatch",
            "FederationQueryResult",
        ]:
            self.assertIn(sym, q_mod.__all__)

    def test_federation_result_is_dataclass(self):
        from dataclasses import fields
        fnames = {f.name for f in fields(FederationQueryResult)}
        self.assertIn("per_graph_results", fnames)
        self.assertIn("query_errors", fnames)

    def test_entity_match_is_dataclass(self):
        from dataclasses import fields
        fnames = {f.name for f in fields(EntityMatch)}
        self.assertIn("entity_a_id", fnames)
        self.assertIn("entity_b_id", fnames)
        self.assertIn("kg_a_index", fnames)
        self.assertIn("score", fnames)


# ---------------------------------------------------------------------------
# 8. Doc integrity
# ---------------------------------------------------------------------------

class TestDocIntegritySession74(unittest.TestCase):
    def test_deferred_features_has_federated_section(self):
        content = _read("DEFERRED_FEATURES.md")
        self.assertIn("Federated Knowledge Graph", content)

    def test_deferred_features_has_p9(self):
        content = _read("DEFERRED_FEATURES.md")
        self.assertIn("P9", content)

    def test_deferred_features_marks_implemented(self):
        content = _read("DEFERRED_FEATURES.md")
        # Should have v3.22.28 somewhere in the federation section
        self.assertIn("3.22.28", content)

    def test_roadmap_federation_delivered(self):
        content = _read("ROADMAP.md")
        self.assertIn("Federated knowledge graphs", content)
        self.assertIn("3.22.28", content)

    def test_master_status_version_3_22_28(self):
        content = _read("MASTER_STATUS.md")
        self.assertIn("3.22.28", content)

    def test_changelog_has_3_22_28(self):
        content = _read("CHANGELOG_KNOWLEDGE_GRAPHS.md")
        self.assertIn("3.22.28", content)


# ---------------------------------------------------------------------------
# 9. Version agreement
# ---------------------------------------------------------------------------

class TestVersionAgreement(unittest.TestCase):
    def _extract_top_version(self, path: str) -> str:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                for marker in ["**Version:**", "## [", "| 3.", "Current Version"]:
                    if marker in line:
                        for part in line.split():
                            if "3.22." in part:
                                return part.strip("*|[]():")
        return ""

    def test_master_status_version(self):
        content = _read("MASTER_STATUS.md")
        self.assertIn("3.22.28", content)

    def test_changelog_version(self):
        content = _read("CHANGELOG_KNOWLEDGE_GRAPHS.md")
        self.assertIn("3.22.28", content)

    def test_roadmap_version(self):
        content = _read("ROADMAP.md")
        self.assertIn("3.22.28", content)


if __name__ == "__main__":
    unittest.main()
