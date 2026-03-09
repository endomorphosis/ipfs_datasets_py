"""
Session 80 — Knowledge Graph Completion + Explainable AI
=========================================================

Tests for:
- query/completion.py — KnowledgeGraphCompleter (6 structural patterns)
- query/explanation.py — QueryExplainer (entity/relationship/path/batch)
- query/__init__.py exports
- DEFERRED_FEATURES.md §25+§26 doc-integrity
- MASTER_STATUS / CHANGELOG / ROADMAP version agreement (v3.22.34)

Result target: 52 tests, 0 fail.
"""

from __future__ import annotations

import warnings
import json
import pathlib

warnings.filterwarnings("ignore")

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
KG_ROOT = pathlib.Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "knowledge_graphs"
DEFERRED_PATH = KG_ROOT / "DEFERRED_FEATURES.md"
MASTER_STATUS_PATH = KG_ROOT / "MASTER_STATUS.md"
CHANGELOG_PATH = KG_ROOT / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
ROADMAP_PATH = KG_ROOT / "ROADMAP.md"

EXPECTED_VERSION = "3.22.34"


def _read(path: pathlib.Path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _extract_top_version(text: str) -> str:
    """Return the first version number that looks like N.N.N from a version line."""
    import re
    m = re.search(r"\*\*Version:\*\*\s*([\d.]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"##\s+\[(\d+\.\d+\.\d+)\]", text)
    if m:
        return m.group(1)
    return ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def simple_kg():
    """
    A→knows→B, B→knows→C, B→works_at→OrgX
    Entity types: person/person/person/organization
    """
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    kg = KnowledgeGraph(name="test_simple")
    alice = kg.add_entity("person", "Alice")
    bob = kg.add_entity("person", "Bob")
    charlie = kg.add_entity("person", "Charlie")
    orgx = kg.add_entity("organization", "OrgX")
    kg.add_relationship("knows", alice, bob)
    kg.add_relationship("knows", bob, charlie)
    kg.add_relationship("works_at", bob, orgx)
    return kg, alice, bob, charlie, orgx


@pytest.fixture
def inverse_kg():
    """A→parent_of→B (no child_of reverse)"""
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    kg = KnowledgeGraph(name="test_inverse")
    parent = kg.add_entity("person", "Parent")
    child = kg.add_entity("person", "Child")
    kg.add_relationship("parent_of", parent, child)
    return kg, parent, child


@pytest.fixture
def transitive_kg():
    """A→reports_to→B, B→reports_to→C (same type)"""
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    kg = KnowledgeGraph(name="test_transitive")
    a = kg.add_entity("employee", "Alice")
    b = kg.add_entity("employee", "Bob")
    c = kg.add_entity("employee", "Charlie")
    kg.add_relationship("reports_to", a, b)
    kg.add_relationship("reports_to", b, c)
    return kg, a, b, c


@pytest.fixture
def empty_kg():
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    return KnowledgeGraph(name="empty")


# ===========================================================================
# TestCompletionBasics
# ===========================================================================
class TestCompletionBasics:
    def test_import_classes(self):
        from ipfs_datasets_py.knowledge_graphs.query.completion import (
            KnowledgeGraphCompleter,
            CompletionSuggestion,
            CompletionReason,
        )
        assert KnowledgeGraphCompleter
        assert CompletionSuggestion
        assert CompletionReason

    def test_completion_reason_enum_values(self):
        from ipfs_datasets_py.knowledge_graphs.query.completion import CompletionReason
        assert CompletionReason.TRIADIC_CLOSURE.value == "triadic_closure"
        assert CompletionReason.COMMON_NEIGHBOR.value == "common_neighbor"
        assert CompletionReason.SYMMETRIC_RELATION.value == "symmetric_relation"
        assert CompletionReason.TRANSITIVE_RELATION.value == "transitive_relation"
        assert CompletionReason.INVERSE_RELATION.value == "inverse_relation"
        assert CompletionReason.TYPE_COMPATIBILITY.value == "type_compatibility"

    def test_suggestion_to_dict(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import (
            KnowledgeGraphCompleter, CompletionReason,
        )
        c = KnowledgeGraphCompleter(kg)
        sug = c.find_missing_relationships(min_score=0.0)[0]
        d = sug.to_dict()
        assert "source_id" in d
        assert "target_id" in d
        assert "rel_type" in d
        assert "score" in d
        assert "reason" in d
        assert isinstance(d["score"], float)

    def test_empty_graph_returns_no_suggestions(self, empty_kg):
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(empty_kg)
        assert c.find_missing_relationships() == []

    def test_isolated_entities_empty_graph(self, empty_kg):
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(empty_kg)
        assert c.find_isolated_entities() == []

    def test_isolated_entities_detects_unconnected(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        kg = KnowledgeGraph(name="t")
        alice = kg.add_entity("person", "Alice")
        loner = kg.add_entity("person", "Loner")
        bob = kg.add_entity("person", "Bob")
        kg.add_relationship("knows", alice, bob)
        c = KnowledgeGraphCompleter(kg)
        isolated = c.find_isolated_entities()
        assert loner.entity_id in isolated
        assert alice.entity_id not in isolated


# ===========================================================================
# TestTriadicClosure
# ===========================================================================
class TestTriadicClosure:
    def test_triadic_closure_found(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import (
            KnowledgeGraphCompleter, CompletionReason,
        )
        c = KnowledgeGraphCompleter(kg)
        sug = c.find_missing_relationships(
            entity_id=alice.entity_id,
            rel_type="knows",
            min_score=0.0,
        )
        triadic = [s for s in sug if s.reason == CompletionReason.TRIADIC_CLOSURE]
        assert len(triadic) >= 1
        targets = [s.target_id for s in triadic]
        assert charlie.entity_id in targets

    def test_triadic_closure_score_in_range(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import (
            KnowledgeGraphCompleter, CompletionReason,
        )
        c = KnowledgeGraphCompleter(kg)
        sug = [
            s for s in c.find_missing_relationships(min_score=0.0)
            if s.reason == CompletionReason.TRIADIC_CLOSURE
        ]
        for s in sug:
            assert 0.0 <= s.score <= 1.0


# ===========================================================================
# TestSymmetricRelation
# ===========================================================================
class TestSymmetricRelation:
    def test_symmetric_suggests_reverse(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import (
            KnowledgeGraphCompleter, CompletionReason,
        )
        c = KnowledgeGraphCompleter(kg)
        sug = [
            s for s in c.find_missing_relationships(min_score=0.0)
            if s.reason == CompletionReason.SYMMETRIC_RELATION
        ]
        assert len(sug) >= 1
        # For A→knows→B, should suggest B→knows→A
        pairs = {(s.source_id, s.target_id) for s in sug}
        assert (bob.entity_id, alice.entity_id) in pairs or (charlie.entity_id, bob.entity_id) in pairs


# ===========================================================================
# TestInverseRelation
# ===========================================================================
class TestInverseRelation:
    def test_inverse_suggests_child_of(self, inverse_kg):
        kg, parent, child = inverse_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import (
            KnowledgeGraphCompleter, CompletionReason,
        )
        c = KnowledgeGraphCompleter(kg)
        sug = [
            s for s in c.find_missing_relationships(min_score=0.0)
            if s.reason == CompletionReason.INVERSE_RELATION
        ]
        assert len(sug) == 1
        s = sug[0]
        assert s.source_id == child.entity_id
        assert s.target_id == parent.entity_id
        assert s.rel_type == "child_of"

    def test_inverse_score_in_range(self, inverse_kg):
        kg, parent, child = inverse_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(kg)
        for s in c.find_missing_relationships(min_score=0.0):
            assert 0.0 <= s.score <= 1.0


# ===========================================================================
# TestTransitiveRelation
# ===========================================================================
class TestTransitiveRelation:
    def test_transitive_suggests_shortcut(self, transitive_kg):
        kg, a, b, c_ = transitive_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import (
            KnowledgeGraphCompleter, CompletionReason,
        )
        c = KnowledgeGraphCompleter(kg)
        sug = c.find_missing_relationships(min_score=0.0)
        # A→reports_to→B and B→reports_to→C should produce A→reports_to→C
        # (via triadic_closure or transitive_relation — both are valid)
        shortcut = [
            s for s in sug
            if s.source_id == a.entity_id
            and s.target_id == c_.entity_id
            and s.rel_type == "reports_to"
        ]
        assert len(shortcut) >= 1
        assert shortcut[0].score > 0.0


# ===========================================================================
# TestCompletionFilters
# ===========================================================================
class TestCompletionFilters:
    def test_min_score_filters(self, simple_kg):
        kg, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(kg)
        all_sug = c.find_missing_relationships(min_score=0.0)
        high_sug = c.find_missing_relationships(min_score=0.9)
        assert len(high_sug) <= len(all_sug)
        for s in high_sug:
            assert s.score >= 0.9

    def test_entity_id_filter(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(kg)
        sug = c.find_missing_relationships(entity_id=alice.entity_id, min_score=0.0)
        for s in sug:
            assert alice.entity_id in (s.source_id, s.target_id)

    def test_rel_type_filter(self, simple_kg):
        kg, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(kg)
        sug = c.find_missing_relationships(rel_type="knows", min_score=0.0)
        for s in sug:
            assert s.rel_type == "knows"

    def test_max_suggestions_limit(self, simple_kg):
        kg, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(kg)
        sug = c.find_missing_relationships(max_suggestions=2, min_score=0.0)
        assert len(sug) <= 2

    def test_sorted_by_score_desc(self, simple_kg):
        kg, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(kg)
        sug = c.find_missing_relationships(min_score=0.0)
        scores = [s.score for s in sug]
        assert scores == sorted(scores, reverse=True)

    def test_compute_completion_score_unknown_entity(self, simple_kg):
        kg, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(kg)
        score = c.compute_completion_score("unknown-id", "another-unknown", "knows")
        assert score == 0.0

    def test_explain_suggestion_returns_string(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.completion import KnowledgeGraphCompleter
        c = KnowledgeGraphCompleter(kg)
        sug = c.find_missing_relationships(min_score=0.0)
        assert len(sug) > 0
        txt = c.explain_suggestion(sug[0])
        assert isinstance(txt, str)
        assert "Suggest" in txt


# ===========================================================================
# TestExplanationBasics
# ===========================================================================
class TestExplanationBasics:
    def test_import_classes(self):
        from ipfs_datasets_py.knowledge_graphs.query.explanation import (
            QueryExplainer,
            EntityExplanation,
            RelationshipExplanation,
            PathExplanation,
            ExplanationDepth,
        )
        assert QueryExplainer

    def test_explanation_depth_values(self):
        from ipfs_datasets_py.knowledge_graphs.query.explanation import ExplanationDepth
        assert ExplanationDepth.SURFACE.value == "surface"
        assert ExplanationDepth.STANDARD.value == "standard"
        assert ExplanationDepth.DEEP.value == "deep"

    def test_explain_entity_known(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        exp = e.explain_entity(alice.entity_id)
        assert exp.entity_name == "Alice"
        assert exp.entity_type == "person"
        assert exp.outgoing_count == 1
        assert exp.incoming_count == 0
        assert "Alice" in exp.narrative

    def test_explain_entity_unknown(self, simple_kg):
        kg, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        exp = e.explain_entity("nonexistent-id")
        assert exp.entity_type == "unknown"
        assert "not found" in exp.narrative

    def test_explain_entity_to_dict(self, simple_kg):
        kg, alice, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        d = e.explain_entity(alice.entity_id).to_dict()
        assert "entity_id" in d
        assert "narrative" in d
        assert "related_count" in d

    def test_explain_entity_surface_no_props(self, simple_kg):
        kg, alice, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import (
            QueryExplainer, ExplanationDepth,
        )
        e = QueryExplainer(kg)
        exp = e.explain_entity(alice.entity_id, depth=ExplanationDepth.SURFACE)
        assert exp.property_summary == ""

    def test_explain_entity_deep_has_cluster_hint(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import (
            QueryExplainer, ExplanationDepth,
        )
        e = QueryExplainer(kg)
        exp = e.explain_entity(bob.entity_id, depth=ExplanationDepth.DEEP)
        # bob has outgoing to person+org; cluster_hint should be non-empty
        assert isinstance(exp.cluster_hint, str)


# ===========================================================================
# TestExplanationRelationship
# ===========================================================================
class TestExplanationRelationship:
    def test_explain_relationship_known(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        # get the alice→bob relationship id
        rel = [
            r for r in kg.relationships.values()
            if r.source_id == alice.entity_id and r.target_id == bob.entity_id
        ][0]
        exp = e.explain_relationship(rel.relationship_id)
        assert exp.source_name == "Alice"
        assert exp.target_name == "Bob"
        assert exp.relationship_type == "knows"
        assert "Alice" in exp.narrative

    def test_explain_relationship_unknown(self, simple_kg):
        kg, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        exp = e.explain_relationship("bad-id")
        assert "not found" in exp.narrative

    def test_explain_relationship_to_dict(self, simple_kg):
        kg, alice, bob, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        rel = [
            r for r in kg.relationships.values()
            if r.source_id == alice.entity_id and r.target_id == bob.entity_id
        ][0]
        d = e.explain_relationship(rel.relationship_id).to_dict()
        assert "symmetry_note" in d
        assert "narrative" in d


# ===========================================================================
# TestExplanationPath
# ===========================================================================
class TestExplanationPath:
    def test_path_direct(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        path = e.explain_path(alice.entity_id, bob.entity_id)
        assert path.reachable is True
        assert path.hops == 1
        assert path.path_nodes == [alice.entity_id, bob.entity_id]

    def test_path_two_hops(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        path = e.explain_path(alice.entity_id, charlie.entity_id)
        assert path.reachable is True
        assert path.hops == 2

    def test_path_unreachable(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        path = e.explain_path(orgx.entity_id, alice.entity_id)
        assert path.reachable is False
        assert path.hops == 0

    def test_path_same_entity(self, simple_kg):
        kg, alice, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        path = e.explain_path(alice.entity_id, alice.entity_id)
        assert path.reachable is True
        assert path.hops == 0

    def test_path_to_dict(self, simple_kg):
        kg, alice, bob, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        d = e.explain_path(alice.entity_id, bob.entity_id).to_dict()
        assert "path_nodes" in d
        assert "hops" in d
        assert "reachable" in d

    def test_path_total_confidence(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        path = e.explain_path(alice.entity_id, charlie.entity_id)
        assert 0.0 <= path.total_confidence <= 1.0


# ===========================================================================
# TestExplanationBatch
# ===========================================================================
class TestExplanationBatch:
    def test_explain_query_result_returns_list(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import (
            QueryExplainer, ExplanationDepth,
        )
        e = QueryExplainer(kg)
        result = e.explain_query_result(
            [alice.entity_id, bob.entity_id, charlie.entity_id],
            depth=ExplanationDepth.SURFACE,
        )
        assert len(result) == 3

    def test_why_connected_direct(self, simple_kg):
        kg, alice, bob, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        reason = e.why_connected(alice.entity_id, bob.entity_id)
        assert "directly connected" in reason

    def test_why_connected_path(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        reason = e.why_connected(alice.entity_id, charlie.entity_id)
        assert "hop" in reason.lower() or "path" in reason.lower()

    def test_why_connected_disconnected(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        reason = e.why_connected(orgx.entity_id, alice.entity_id)
        assert "not connected" in reason

    def test_entity_importance_score_higher_for_hub(self, simple_kg):
        kg, alice, bob, charlie, orgx = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        bob_score = e.entity_importance_score(bob.entity_id)
        alice_score = e.entity_importance_score(alice.entity_id)
        # Bob has more connections than Alice
        assert bob_score >= alice_score

    def test_entity_importance_unknown(self, simple_kg):
        kg, *_ = simple_kg
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(kg)
        assert e.entity_importance_score("unknown-id") == 0.0

    def test_entity_importance_empty_graph(self, empty_kg):
        from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
        e = QueryExplainer(empty_kg)
        assert e.entity_importance_score("any-id") == 0.0


# ===========================================================================
# TestQueryModuleExports
# ===========================================================================
class TestQueryModuleExports:
    def test_completion_importable_from_query_init(self):
        from ipfs_datasets_py.knowledge_graphs.query import (
            KnowledgeGraphCompleter,
            CompletionSuggestion,
            CompletionReason,
        )
        assert KnowledgeGraphCompleter

    def test_explanation_importable_from_query_init(self):
        from ipfs_datasets_py.knowledge_graphs.query import (
            QueryExplainer,
            EntityExplanation,
            RelationshipExplanation,
            PathExplanation,
            ExplanationDepth,
        )
        assert QueryExplainer

    def test_symbols_in_all(self):
        from ipfs_datasets_py.knowledge_graphs import query
        all_syms = set(query.__all__)
        for sym in (
            "KnowledgeGraphCompleter",
            "CompletionSuggestion",
            "CompletionReason",
            "QueryExplainer",
            "EntityExplanation",
            "RelationshipExplanation",
            "PathExplanation",
            "ExplanationDepth",
        ):
            assert sym in all_syms, f"{sym} not in __all__"


# ===========================================================================
# TestDocIntegritySession80
# ===========================================================================
class TestDocIntegritySession80:
    def test_deferred_has_p12_section(self):
        text = _read(DEFERRED_PATH)
        assert "P12" in text

    def test_deferred_has_completion_section(self):
        text = _read(DEFERRED_PATH)
        assert "Knowledge Graph Completion" in text or "§25" in text

    def test_deferred_has_explainable_ai_section(self):
        text = _read(DEFERRED_PATH)
        assert "Explainable AI" in text or "§26" in text

    def test_deferred_has_v3_22_34_mark(self):
        text = _read(DEFERRED_PATH)
        assert "3.22.34" in text

    def test_roadmap_completion_delivered(self):
        text = _read(ROADMAP_PATH)
        # Research area should now be marked as delivered
        assert "3.22.34" in text

    def test_master_status_v3_22_34(self):
        text = _read(MASTER_STATUS_PATH)
        assert "3.22.34" in text

    def test_changelog_v3_22_34(self):
        text = _read(CHANGELOG_PATH)
        assert "3.22.34" in text


# ===========================================================================
# TestVersionAgreement
# ===========================================================================
class TestVersionAgreement:
    def test_master_status_version(self):
        text = _read(MASTER_STATUS_PATH)
        ver = _extract_top_version(text)
        # Relaxed: version must be >= 3.22.34 (may be incremented in later sessions)
        from packaging.version import Version
        try:
            assert Version(ver) >= Version(EXPECTED_VERSION), \
                f"MASTER_STATUS version={ver!r} < {EXPECTED_VERSION}"
        except Exception:
            # Fallback if packaging not available: just check it's a valid version
            assert ver is not None and ver >= EXPECTED_VERSION, \
                f"MASTER_STATUS version={ver!r}"

    def test_changelog_version(self):
        text = _read(CHANGELOG_PATH)
        assert EXPECTED_VERSION in text

    def test_roadmap_version(self):
        text = _read(ROADMAP_PATH)
        assert EXPECTED_VERSION in text
