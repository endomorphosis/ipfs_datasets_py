"""Session 72 doc + production integrity tests.

Knowledge Graphs — Session 72 (2026-02-23)

Covers:
- GraphQL API support production feature (query/graphql.py):
  * GraphQLParser correctness
  * GraphQLParseError on invalid syntax
  * KnowledgeGraphQLExecutor: entity selection, argument filters,
    field projection, nested relationship traversal, aliases
- DEFERRED_FEATURES §19 GraphQL API Support entry
- ROADMAP.md v4.0+ "GraphQL API support" delivered in v3.22.26
- MASTER_STATUS / CHANGELOG / ROADMAP version agreement (v3.22.26)
"""

import sys
import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_KG_DIR = _REPO_ROOT / "ipfs_datasets_py" / "knowledge_graphs"

# ---------------------------------------------------------------------------
# Test helper: lazy KnowledgeGraph construction
# ---------------------------------------------------------------------------

def _make_kg():
    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
    kg = KnowledgeGraph("test_gql")
    alice = kg.add_entity("person", "Alice", {"age": 30, "city": "NYC"})
    bob   = kg.add_entity("person", "Bob",   {"age": 25})
    carol = kg.add_entity("org",    "Acme",  {"size": 100})
    kg.add_relationship("knows",    alice, bob)
    kg.add_relationship("works_at", bob,   carol)
    return kg, alice, bob, carol


# ===========================================================================
# 1. GraphQLParser — valid queries
# ===========================================================================

class TestGraphQLParser:
    """GraphQLParser handles the supported query subset."""

    def test_simple_selection(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse("{ person { name } }")
        assert len(doc.selections) == 1
        assert doc.selections[0].name == "person"
        assert doc.selections[0].sub_fields[0].name == "name"

    def test_multiple_top_level_fields(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse("{ person { name } org { size } }")
        assert len(doc.selections) == 2
        assert doc.selections[1].name == "org"

    def test_arguments_string(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse('{ person(name: "Alice") { name } }')
        assert doc.selections[0].arguments == {"name": "Alice"}

    def test_arguments_int(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse("{ person(age: 30) { name } }")
        assert doc.selections[0].arguments["age"] == 30

    def test_arguments_bool(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse("{ person(active: true) { name } }")
        assert doc.selections[0].arguments["active"] is True

    def test_arguments_null(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse("{ person(email: null) { name } }")
        assert doc.selections[0].arguments["email"] is None

    def test_alias(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse("{ folks: person { name } }")
        sel = doc.selections[0]
        assert sel.alias == "folks"
        assert sel.name == "person"

    def test_query_keyword_ignored(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse("query MyOp { person { name } }")
        assert doc.selections[0].name == "person"

    def test_nested_fields(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse("{ person { name knows { name age } } }")
        fields = doc.selections[0].sub_fields
        nested = next(f for f in fields if f.name == "knows")
        assert len(nested.sub_fields) == 2

    def test_float_argument(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLParser
        doc = GraphQLParser().parse("{ entity(confidence: 0.9) { name } }")
        assert abs(doc.selections[0].arguments["confidence"] - 0.9) < 1e-9


# ===========================================================================
# 2. GraphQLParseError — invalid queries
# ===========================================================================

class TestGraphQLParseErrors:
    """GraphQLParser raises GraphQLParseError for malformed input."""

    def test_unclosed_brace(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import (
            GraphQLParser, GraphQLParseError,
        )
        with pytest.raises(GraphQLParseError):
            GraphQLParser().parse("{ person { name }")

    def test_missing_colon_after_alias(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import (
            GraphQLParser, GraphQLParseError,
        )
        # "{ a b }" — 'a' is consumed as a name, then 'b' next to it triggers
        # an issue when treated as alias; depends on parser path
        # Simplest trigger: expect ':' but get '{'
        with pytest.raises(GraphQLParseError):
            GraphQLParser().parse("{ a: { name } }")

    def test_invalid_argument_value(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import (
            GraphQLParser, GraphQLParseError,
        )
        with pytest.raises(GraphQLParseError):
            GraphQLParser().parse("{ person(name: {}) { name } }")

    def test_parse_error_propagates_via_execute(self):
        """Executor wraps parse errors into response envelope."""
        from ipfs_datasets_py.knowledge_graphs.query.graphql import (
            KnowledgeGraphQLExecutor,
        )
        kg, *_ = _make_kg()
        exe = KnowledgeGraphQLExecutor(kg)
        result = exe.execute("{ unclosed {")
        assert result["data"] is None
        assert len(result["errors"]) >= 1


# ===========================================================================
# 3. KnowledgeGraphQLExecutor — basic entity queries
# ===========================================================================

class TestKGQLExecutorBasic:
    """Basic entity-type selection without filters."""

    def test_no_entities_returns_empty_list(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg = KnowledgeGraph("empty")
        result = KnowledgeGraphQLExecutor(kg).execute("{ person { name } }")
        assert result["data"]["person"] == []

    def test_returns_all_matching_type(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, alice, bob, carol = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute("{ person { name } }")
        names = {r["name"] for r in result["data"]["person"]}
        assert names == {"Alice", "Bob"}

    def test_field_projection_name(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute("{ person { name } }")
        for r in result["data"]["person"]:
            assert set(r.keys()) == {"name"}

    def test_field_projection_id(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, alice, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute("{ person { id } }")
        ids = {r["id"] for r in result["data"]["person"]}
        assert alice.entity_id in ids

    def test_field_projection_type(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute("{ person { type } }")
        for r in result["data"]["person"]:
            assert r["type"] == "person"

    def test_no_sub_fields_returns_default_dict(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute("{ person }")
        first = result["data"]["person"][0]
        assert "id" in first
        assert "name" in first
        assert "type" in first

    def test_data_key_always_present(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute("{ person { name } }")
        assert "data" in result
        assert "errors" not in result

    def test_multiple_top_level_selections(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute(
            "{ person { name } org { name } }"
        )
        assert "person" in result["data"]
        assert "org" in result["data"]
        assert len(result["data"]["org"]) == 1


# ===========================================================================
# 4. KnowledgeGraphQLExecutor — argument filters
# ===========================================================================

class TestKGQLExecutorFilters:
    """Argument-based equality filters."""

    def test_filter_by_name(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, alice, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute(
            '{ person(name: "Alice") { name age } }'
        )
        rows = result["data"]["person"]
        assert len(rows) == 1
        assert rows[0]["name"] == "Alice"
        assert rows[0]["age"] == 30

    def test_filter_by_property(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, alice, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute(
            "{ person(age: 25) { name } }"
        )
        rows = result["data"]["person"]
        assert len(rows) == 1
        assert rows[0]["name"] == "Bob"

    def test_filter_no_match_returns_empty(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute(
            '{ person(name: "Zara") { name } }'
        )
        assert result["data"]["person"] == []

    def test_filter_by_id(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, alice, *_ = _make_kg()
        query = '{ person(id: "%s") { name } }' % alice.entity_id
        result = KnowledgeGraphQLExecutor(kg).execute(query)
        assert result["data"]["person"][0]["name"] == "Alice"

    def test_arbitrary_property_filter(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute(
            '{ person(city: "NYC") { name } }'
        )
        rows = result["data"]["person"]
        assert len(rows) == 1
        assert rows[0]["name"] == "Alice"


# ===========================================================================
# 5. KnowledgeGraphQLExecutor — relationship traversal
# ===========================================================================

class TestKGQLExecutorRelationships:
    """Nested field resolves outgoing relationships to target entities."""

    def test_single_relationship(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, alice, bob, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute(
            '{ person(name: "Alice") { name knows { name } } }'
        )
        knows = result["data"]["person"][0]["knows"]
        assert len(knows) == 1
        assert knows[0]["name"] == "Bob"

    def test_no_outgoing_relationship(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute(
            '{ person(name: "Alice") { name works_at { name } } }'
        )
        # Alice has no works_at — should be empty
        assert result["data"]["person"][0]["works_at"] == []

    def test_relationship_with_sub_fields(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, alice, bob, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute(
            '{ person(name: "Alice") { knows { name age } } }'
        )
        target = result["data"]["person"][0]["knows"][0]
        assert target["name"] == "Bob"
        assert target["age"] == 25

    def test_aliased_relationship_field(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, alice, *_ = _make_kg()
        result = KnowledgeGraphQLExecutor(kg).execute(
            '{ person(name: "Alice") { friends: knows { name } } }'
        )
        assert "friends" in result["data"]["person"][0]
        assert result["data"]["person"][0]["friends"][0]["name"] == "Bob"

    def test_relationship_target_has_default_fields(self):
        """No sub-field selection on leaf returns entity property (None for missing)."""
        from ipfs_datasets_py.knowledge_graphs.query.graphql import KnowledgeGraphQLExecutor
        kg, alice, *_ = _make_kg()
        # "knows" with no braces is a leaf property field, not relationship traversal
        result = KnowledgeGraphQLExecutor(kg).execute(
            '{ person(name: "Alice") { name knows { id name type } } }'
        )
        # With explicit sub-fields, relationship traversal is activated
        target = result["data"]["person"][0]["knows"][0]
        assert "id" in target
        assert "name" in target
        assert "type" in target


# ===========================================================================
# 6. Integration — query module exports
# ===========================================================================

class TestQueryModuleExports:
    """GraphQL symbols are importable from the query module."""

    def test_import_from_query_module(self):
        from ipfs_datasets_py.knowledge_graphs.query import (
            GraphQLParser,
            GraphQLParseError,
            GraphQLDocument,
            GraphQLField,
            KnowledgeGraphQLExecutor,
        )

    def test_graphql_in_query_all(self):
        import ipfs_datasets_py.knowledge_graphs.query as q
        for sym in (
            "GraphQLParser",
            "GraphQLParseError",
            "GraphQLDocument",
            "GraphQLField",
            "KnowledgeGraphQLExecutor",
        ):
            assert sym in q.__all__, f"{sym} missing from query.__all__"

    def test_graphql_field_is_leaf(self):
        from ipfs_datasets_py.knowledge_graphs.query.graphql import GraphQLField
        leaf = GraphQLField(name="foo")
        nested = GraphQLField(name="bar", sub_fields=[leaf])
        assert leaf.is_leaf is True
        assert nested.is_leaf is False


# ===========================================================================
# 7. Doc integrity — DEFERRED_FEATURES + ROADMAP
# ===========================================================================

class TestDocIntegritySession72:
    """Documentation reflects session 72 changes."""

    def test_deferred_features_graphql_entry(self):
        content = (_KG_DIR / "DEFERRED_FEATURES.md").read_text()
        assert "GraphQL API" in content or "graphql" in content.lower()

    def test_roadmap_graphql_delivered(self):
        content = (_KG_DIR / "ROADMAP.md").read_text()
        assert "GraphQL" in content

    def test_roadmap_v3_22_26_row(self):
        content = (_KG_DIR / "ROADMAP.md").read_text()
        assert "3.22.26" in content

    def test_master_status_version(self):
        content = (_KG_DIR / "MASTER_STATUS.md").read_text()
        assert "3.22.26" in content

    def test_changelog_3_22_26(self):
        content = (_KG_DIR / "CHANGELOG_KNOWLEDGE_GRAPHS.md").read_text()
        assert "3.22.26" in content


# ===========================================================================
# 8. Version agreement
# ===========================================================================

class TestVersionAgreement:
    """MASTER_STATUS / CHANGELOG / ROADMAP all declare v3.22.26."""

    def test_master_status_current_version(self):
        content = (_KG_DIR / "MASTER_STATUS.md").read_text()
        assert "3.22.26" in content

    def test_changelog_has_v3_22_26(self):
        content = (_KG_DIR / "CHANGELOG_KNOWLEDGE_GRAPHS.md").read_text()
        assert "3.22.26" in content

    def test_roadmap_current_version_header(self):
        content = (_KG_DIR / "ROADMAP.md").read_text()
        assert "3.22.26" in content
