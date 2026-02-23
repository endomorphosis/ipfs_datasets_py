"""
Tests for Session 81: 5 new MCP tools for query/extraction features.

Session 81 (v3.22.35):
- graph_graphql_query.py   — execute GraphQL via KnowledgeGraphQLExecutor
- graph_visualize.py       — export KG as DOT/Mermaid/D3/ASCII
- graph_complete_suggestions.py — suggest missing relationships
- graph_explain.py         — explainable AI explanations
- graph_provenance_verify.py — verify provenance chain integrity
- 5 new KnowledgeGraphManager methods
- graph_tools/__init__.py + README.md updated
"""

import asyncio
import pathlib
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Stub anyio so the graph_tools package can be imported without it installed.
# ---------------------------------------------------------------------------
if "anyio" not in sys.modules:
    sys.modules["anyio"] = types.ModuleType("anyio")

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
_BASE = pathlib.Path(__file__).parent.parent.parent.parent
_KG_ROOT = _BASE / "ipfs_datasets_py" / "knowledge_graphs"
_MASTER = _KG_ROOT / "MASTER_STATUS.md"
_CHANGELOG = _KG_ROOT / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
_ROADMAP = _KG_ROOT / "ROADMAP.md"
_README_GT = (_BASE / "ipfs_datasets_py" / "mcp_server" / "tools" /
              "graph_tools" / "README.md")


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_kg():
    """Build a small test KnowledgeGraph with 3 entities + 2 relationships."""
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
        KnowledgeGraph, Entity, Relationship,
    )
    kg = KnowledgeGraph(name="test_session81")
    alice = Entity(entity_id="alice", entity_type="person", name="alice")
    bob = Entity(entity_id="bob", entity_type="person", name="bob")
    charlie = Entity(entity_id="charlie", entity_type="person", name="charlie")
    for e in (alice, bob, charlie):
        kg.add_entity(e)
    kg.add_relationship(
        Relationship(
            relationship_id="r1",
            relationship_type="knows",
            source_entity=alice,
            target_entity=bob,
        )
    )
    kg.add_relationship(
        Relationship(
            relationship_id="r2",
            relationship_type="knows",
            source_entity=bob,
            target_entity=charlie,
        )
    )
    return kg


# ---------------------------------------------------------------------------
# 1. MCP tool: graph_graphql_query
# ---------------------------------------------------------------------------
class TestGraphGraphqlQueryTool:
    """Tests for graph_graphql_query MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_graphql_query import (
            graph_graphql_query,
        )
        assert callable(graph_graphql_query)

    def test_empty_kg_success(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_graphql_query import (
            graph_graphql_query,
        )
        r = asyncio.run(graph_graphql_query("{ person { id name } }"))
        assert r["status"] == "success"

    def test_returns_data_key(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_graphql_query import (
            graph_graphql_query,
        )
        r = asyncio.run(graph_graphql_query("{ person { id name } }"))
        assert "data" in r

    def test_entity_count_key(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_graphql_query import (
            graph_graphql_query,
        )
        r = asyncio.run(graph_graphql_query("{ person { id } }"))
        assert "entity_count" in r
        assert isinstance(r["entity_count"], int)

    def test_with_real_kg_data(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_graphql_query import (
            graph_graphql_query,
        )
        kg = _make_kg()
        r = asyncio.run(graph_graphql_query(
            "{ person { id name } }",
            kg_data=kg.to_dict(),
        ))
        assert r["status"] == "success"
        assert r["entity_count"] == 3

    def test_query_length_key(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_graphql_query import (
            graph_graphql_query,
        )
        q = "{ person { id } }"
        r = asyncio.run(graph_graphql_query(q))
        assert r["query_length"] == len(q)


# ---------------------------------------------------------------------------
# 2. MCP tool: graph_visualize
# ---------------------------------------------------------------------------
class TestGraphVisualizeTool:
    """Tests for graph_visualize MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_visualize import (
            graph_visualize,
        )
        assert callable(graph_visualize)

    def test_dot_format(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_visualize import (
            graph_visualize,
        )
        kg = _make_kg()
        r = asyncio.run(graph_visualize(format="dot", kg_data=kg.to_dict()))
        assert r["status"] == "success"
        assert r["format"] == "dot"
        assert "digraph" in r["output"]

    def test_mermaid_format(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_visualize import (
            graph_visualize,
        )
        kg = _make_kg()
        r = asyncio.run(graph_visualize(format="mermaid", kg_data=kg.to_dict()))
        assert r["status"] == "success"
        assert r["format"] == "mermaid"

    def test_d3_json_format(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_visualize import (
            graph_visualize,
        )
        kg = _make_kg()
        r = asyncio.run(graph_visualize(format="d3_json", kg_data=kg.to_dict()))
        assert r["status"] == "success"

    def test_ascii_format(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_visualize import (
            graph_visualize,
        )
        kg = _make_kg()
        r = asyncio.run(graph_visualize(format="ascii", kg_data=kg.to_dict()))
        assert r["status"] == "success"

    def test_entity_and_relationship_counts(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_visualize import (
            graph_visualize,
        )
        kg = _make_kg()
        r = asyncio.run(graph_visualize(format="dot", kg_data=kg.to_dict()))
        assert r["entity_count"] == 3
        assert r["relationship_count"] == 2

    def test_empty_kg(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_visualize import (
            graph_visualize,
        )
        r = asyncio.run(graph_visualize(format="dot"))
        assert r["status"] == "success"
        assert r["entity_count"] == 0


# ---------------------------------------------------------------------------
# 3. MCP tool: graph_complete_suggestions
# ---------------------------------------------------------------------------
class TestGraphCompleteSuggestionsTool:
    """Tests for graph_complete_suggestions MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_complete_suggestions import (
            graph_complete_suggestions,
        )
        assert callable(graph_complete_suggestions)

    def test_empty_kg(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_complete_suggestions import (
            graph_complete_suggestions,
        )
        r = asyncio.run(graph_complete_suggestions())
        assert r["status"] == "success"
        assert r["suggestion_count"] == 0

    def test_triadic_suggestions(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_complete_suggestions import (
            graph_complete_suggestions,
        )
        kg = _make_kg()
        r = asyncio.run(graph_complete_suggestions(
            kg_data=kg.to_dict(), min_score=0.1
        ))
        assert r["status"] == "success"
        assert r["suggestion_count"] >= 1  # triadic alice→charlie

    def test_suggestions_have_required_keys(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_complete_suggestions import (
            graph_complete_suggestions,
        )
        kg = _make_kg()
        r = asyncio.run(graph_complete_suggestions(
            kg_data=kg.to_dict(), min_score=0.1
        ))
        if r["suggestions"]:
            s = r["suggestions"][0]
            for key in ("source_id", "target_id", "rel_type", "score", "reason"):
                assert key in s, f"missing key: {key}"

    def test_min_score_filter(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_complete_suggestions import (
            graph_complete_suggestions,
        )
        kg = _make_kg()
        r = asyncio.run(graph_complete_suggestions(
            kg_data=kg.to_dict(), min_score=0.99
        ))
        assert r["status"] == "success"
        assert all(s["score"] >= 0.99 for s in r["suggestions"])

    def test_isolated_entity_count(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_complete_suggestions import (
            graph_complete_suggestions,
        )
        r = asyncio.run(graph_complete_suggestions())
        assert "isolated_entity_count" in r

    def test_max_suggestions(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_complete_suggestions import (
            graph_complete_suggestions,
        )
        kg = _make_kg()
        r = asyncio.run(graph_complete_suggestions(
            kg_data=kg.to_dict(), min_score=0.0, max_suggestions=1
        ))
        assert len(r["suggestions"]) <= 1


# ---------------------------------------------------------------------------
# 4. MCP tool: graph_explain
# ---------------------------------------------------------------------------
class TestGraphExplainTool:
    """Tests for graph_explain MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_explain import (
            graph_explain,
        )
        assert callable(graph_explain)

    def test_explain_entity_known(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_explain import (
            graph_explain,
        )
        kg = _make_kg()
        r = asyncio.run(graph_explain(
            explain_type="entity",
            entity_id="alice",
            kg_data=kg.to_dict(),
        ))
        assert r["status"] == "success"
        assert "narrative" in r
        assert "alice" in r["narrative"].lower()

    def test_explain_entity_unknown(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_explain import (
            graph_explain,
        )
        r = asyncio.run(graph_explain(
            explain_type="entity",
            entity_id="nobody",
        ))
        assert r["status"] == "success"
        assert "narrative" in r

    def test_explain_path(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_explain import (
            graph_explain,
        )
        kg = _make_kg()
        r = asyncio.run(graph_explain(
            explain_type="path",
            start_entity_id="alice",
            end_entity_id="charlie",
            kg_data=kg.to_dict(),
        ))
        assert r["status"] == "success"
        assert "hops" in r["explanation"] or "narrative" in r

    def test_explain_why_connected(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_explain import (
            graph_explain,
        )
        kg = _make_kg()
        r = asyncio.run(graph_explain(
            explain_type="why_connected",
            start_entity_id="alice",
            end_entity_id="charlie",
            kg_data=kg.to_dict(),
        ))
        assert r["status"] == "success"
        assert isinstance(r["narrative"], str)
        assert len(r["narrative"]) > 0

    def test_explain_missing_id_returns_error(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_explain import (
            graph_explain,
        )
        r = asyncio.run(graph_explain(explain_type="entity"))
        assert r["status"] == "error"

    def test_explain_returns_explanation_dict(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_explain import (
            graph_explain,
        )
        kg = _make_kg()
        r = asyncio.run(graph_explain(
            explain_type="entity",
            entity_id="bob",
            kg_data=kg.to_dict(),
        ))
        assert isinstance(r["explanation"], dict)

    def test_explain_type_echoed(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_explain import (
            graph_explain,
        )
        kg = _make_kg()
        r = asyncio.run(graph_explain(
            explain_type="entity",
            entity_id="alice",
            kg_data=kg.to_dict(),
        ))
        assert r["explain_type"] == "entity"


# ---------------------------------------------------------------------------
# 5. MCP tool: graph_provenance_verify
# ---------------------------------------------------------------------------
class TestGraphProvenanceVerifyTool:
    """Tests for graph_provenance_verify MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_provenance_verify import (
            graph_provenance_verify,
        )
        assert callable(graph_provenance_verify)

    def test_empty_chain_valid(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_provenance_verify import (
            graph_provenance_verify,
        )
        r = asyncio.run(graph_provenance_verify())
        assert r["status"] == "success"
        assert r["valid"] is True
        assert r["event_count"] == 0

    def test_returns_required_keys(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_provenance_verify import (
            graph_provenance_verify,
        )
        r = asyncio.run(graph_provenance_verify())
        for key in ("status", "valid", "event_count", "errors", "latest_cid", "depth"):
            assert key in r, f"missing key: {key}"

    def test_valid_jsonl_chain(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_provenance_verify import (
            graph_provenance_verify,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("alice", "person", "alice")
        chain.record_entity_created("bob", "person", "bob")
        r = asyncio.run(graph_provenance_verify(provenance_jsonl=chain.to_jsonl()))
        assert r["status"] == "success"
        assert r["valid"] is True
        assert r["event_count"] == 2
        assert r["depth"] == 2

    def test_empty_errors_on_valid(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_provenance_verify import (
            graph_provenance_verify,
        )
        r = asyncio.run(graph_provenance_verify())
        assert r["errors"] == []

    def test_latest_cid_none_for_empty(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_provenance_verify import (
            graph_provenance_verify,
        )
        r = asyncio.run(graph_provenance_verify())
        assert r["latest_cid"] is None

    def test_latest_cid_set_after_events(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_provenance_verify import (
            graph_provenance_verify,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("x", "thing", "x")
        r = asyncio.run(graph_provenance_verify(provenance_jsonl=chain.to_jsonl()))
        assert r["latest_cid"] is not None
        assert r["latest_cid"].startswith("bafk")


# ---------------------------------------------------------------------------
# 6. KnowledgeGraphManager — new methods
# ---------------------------------------------------------------------------
class TestKnowledgeGraphManagerNewMethods:
    """Tests for the 5 new methods added to KnowledgeGraphManager."""

    def _manager(self):
        from ipfs_datasets_py.core_operations.knowledge_graph_manager import (
            KnowledgeGraphManager,
        )
        return KnowledgeGraphManager()

    def test_graphql_query_method_exists(self):
        mgr = self._manager()
        assert hasattr(mgr, "graphql_query")

    def test_visualize_method_exists(self):
        mgr = self._manager()
        assert hasattr(mgr, "visualize")

    def test_suggest_completions_method_exists(self):
        mgr = self._manager()
        assert hasattr(mgr, "suggest_completions")

    def test_explain_entity_method_exists(self):
        mgr = self._manager()
        assert hasattr(mgr, "explain_entity")

    def test_verify_provenance_method_exists(self):
        mgr = self._manager()
        assert hasattr(mgr, "verify_provenance")

    def test_graphql_query_returns_dict(self):
        mgr = self._manager()
        r = asyncio.run(mgr.graphql_query("{ person { id } }"))
        assert isinstance(r, dict)
        assert "status" in r

    def test_visualize_returns_dict(self):
        mgr = self._manager()
        r = asyncio.run(mgr.visualize(format="dot"))
        assert isinstance(r, dict)
        assert "status" in r

    def test_suggest_completions_returns_dict(self):
        mgr = self._manager()
        r = asyncio.run(mgr.suggest_completions())
        assert isinstance(r, dict)
        assert "status" in r

    def test_verify_provenance_returns_dict(self):
        mgr = self._manager()
        r = asyncio.run(mgr.verify_provenance())
        assert isinstance(r, dict)
        assert "valid" in r


# ---------------------------------------------------------------------------
# 7. graph_tools __init__.py exports
# ---------------------------------------------------------------------------
class TestGraphToolsExports:
    """Tests for the updated graph_tools __init__.py."""

    def test_five_new_tools_in_all(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools import __init__ as init_mod
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "gt",
            str(pathlib.Path(__file__).parent.parent.parent.parent /
                "ipfs_datasets_py/mcp_server/tools/graph_tools/__init__.py"),
        )
        src = (pathlib.Path(__file__).parent.parent.parent.parent /
               "ipfs_datasets_py/mcp_server/tools/graph_tools/__init__.py").read_text()
        for name in (
            "graph_graphql_query",
            "graph_visualize",
            "graph_complete_suggestions",
            "graph_explain",
            "graph_provenance_verify",
        ):
            assert name in src, f"{name} not in __init__.py"

    def test_total_tool_count(self):
        import ast
        init_src = (pathlib.Path(__file__).parent.parent.parent.parent /
                    "ipfs_datasets_py/mcp_server/tools/graph_tools/__init__.py").read_text()
        tree = ast.parse(init_src)
        all_list = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        all_list = node.value
        assert all_list is not None, "__all__ not found in __init__.py"
        count = len(all_list.elts)
        assert count >= 19, f"Expected ≥19 tools in __all__, got {count}"


# ---------------------------------------------------------------------------
# 8. README for graph_tools
# ---------------------------------------------------------------------------
class TestGraphToolsReadme:
    """Tests for the updated graph_tools README.md."""

    def test_five_new_rows_present(self):
        content = _README_GT.read_text(encoding="utf-8")
        for name in (
            "graph_graphql_query",
            "graph_visualize",
            "graph_complete_suggestions",
            "graph_explain",
            "graph_provenance_verify",
        ):
            assert name in content, f"{name} not in README"

    def test_status_table_updated(self):
        content = _README_GT.read_text(encoding="utf-8")
        assert "v3.22.35" in content

    def test_old_tools_still_present(self):
        content = _README_GT.read_text(encoding="utf-8")
        for name in ("graph_srl_extract", "graph_distributed_execute", "graph_create"):
            assert name in content


# ---------------------------------------------------------------------------
# 9. Document integrity
# ---------------------------------------------------------------------------
class TestDocIntegritySession81:
    """Validate MASTER_STATUS, CHANGELOG, and ROADMAP reflect v3.22.35."""

    def test_master_status_version(self):
        assert "3.22.35" in _MASTER.read_text(encoding="utf-8")

    def test_master_status_session81(self):
        assert "session81" in _MASTER.read_text(encoding="utf-8")

    def test_changelog_version(self):
        assert "3.22.35" in _CHANGELOG.read_text(encoding="utf-8")

    def test_changelog_graphql_tool(self):
        assert "graph_graphql_query" in _CHANGELOG.read_text(encoding="utf-8")

    def test_changelog_visualize_tool(self):
        assert "graph_visualize" in _CHANGELOG.read_text(encoding="utf-8")

    def test_changelog_provenance_verify_tool(self):
        assert "graph_provenance_verify" in _CHANGELOG.read_text(encoding="utf-8")

    def test_roadmap_version(self):
        assert "3.22.35" in _ROADMAP.read_text(encoding="utf-8")

    def test_roadmap_row(self):
        content = _ROADMAP.read_text(encoding="utf-8")
        assert "3.22.35" in content
        assert "graph_graphql_query" in content


# ---------------------------------------------------------------------------
# 10. Version agreement
# ---------------------------------------------------------------------------
class TestVersionAgreement:
    """All three anchor docs must agree on v3.22.35."""

    def test_master_status_current_version(self):
        lines = _MASTER.read_text(encoding="utf-8").splitlines()
        version_lines = [l for l in lines if l.startswith("**Version:**")]
        assert version_lines, "No **Version:** line in MASTER_STATUS"
        assert "3.22.35" in version_lines[0]

    def test_changelog_first_section(self):
        lines = _CHANGELOG.read_text(encoding="utf-8").splitlines()
        h2_lines = [l for l in lines if l.startswith("## [")]
        assert h2_lines, "No ## [...] heading in CHANGELOG"
        assert "3.22.35" in h2_lines[0]

    def test_roadmap_current_version(self):
        lines = _ROADMAP.read_text(encoding="utf-8").splitlines()
        cv_lines = [l for l in lines if l.startswith("**Current Version:**")]
        assert cv_lines, "No **Current Version:** line in ROADMAP"
        assert "3.22.35" in cv_lines[0]
