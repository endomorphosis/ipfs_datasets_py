"""
Tests for Session 84: graph_analytics + graph_link_predict MCP tools (v3.22.38).

Session 84 (v3.22.38):
- graph_analytics.py  — comprehensive KG analytics (quality, completion, topology)
- graph_link_predict.py — GNN link-prediction score between two entities
- 2 new KnowledgeGraphManager methods: analytics / link_predict
- graph_tools/__init__.py updated (22→24 tools), README.md updated
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import types

import pytest

# Stub anyio so graph_tools can be imported without it installed.
if "anyio" not in sys.modules:
    sys.modules["anyio"] = types.ModuleType("anyio")

_BASE = pathlib.Path(__file__).parent.parent.parent.parent
_KG_ROOT = _BASE / "ipfs_datasets_py" / "knowledge_graphs"
_MASTER = _KG_ROOT / "MASTER_STATUS.md"
_CHANGELOG = _KG_ROOT / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
_ROADMAP = _KG_ROOT / "ROADMAP.md"
_README_GT = (
    _BASE / "ipfs_datasets_py" / "mcp_server" / "tools" / "graph_tools" / "README.md"
)


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_kg(name="session84_kg"):
    """Build a 4-entity KG with 3 relationships."""
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
        KnowledgeGraph,
        Entity,
        Relationship,
    )

    kg = KnowledgeGraph(name=name)
    alice = Entity(entity_id="alice", entity_type="person", name="alice", confidence=0.9)
    bob = Entity(entity_id="bob", entity_type="person", name="bob", confidence=0.8)
    acme = Entity(entity_id="acme", entity_type="org", name="acme", confidence=1.0)
    solo = Entity(entity_id="solo", entity_type="person", name="solo", confidence=0.7)

    for e in (alice, bob, acme, solo):
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
            relationship_type="works_at",
            source_entity=alice,
            target_entity=acme,
        )
    )
    kg.add_relationship(
        Relationship(
            relationship_id="r3",
            relationship_type="works_at",
            source_entity=bob,
            target_entity=acme,
        )
    )
    return kg


# ===========================================================================
# 1. graph_analytics MCP tool
# ===========================================================================
class TestGraphAnalyticsTool:
    """Tests for the graph_analytics MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        assert callable(graph_analytics)

    def test_empty_graph_success(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        r = asyncio.run(graph_analytics())
        assert isinstance(r, dict)
        assert r["status"] == "success"

    def test_entity_count(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(graph_analytics(kg_data=kg.to_dict()))
        assert r["entity_count"] == 4

    def test_relationship_count(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(graph_analytics(kg_data=kg.to_dict()))
        assert r["relationship_count"] == 3

    def test_quality_metrics_present(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(graph_analytics(kg_data=kg.to_dict(), include_quality_metrics=True))
        assert "quality_metrics" in r
        assert isinstance(r["quality_metrics"], dict)

    def test_quality_metrics_keys(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(graph_analytics(kg_data=kg.to_dict()))
        qm = r["quality_metrics"]
        for key in ("entity_count", "relationship_count", "relationship_density",
                    "avg_entity_confidence", "avg_relationship_confidence"):
            assert key in qm, f"{key!r} missing from quality_metrics"

    def test_completion_analysis_present(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_analytics(kg_data=kg.to_dict(), include_completion_analysis=True)
        )
        assert "missing_relationships" in r
        assert "isolated_entities" in r
        assert "has_completion_suggestions" in r

    def test_isolated_entities_found(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(graph_analytics(kg_data=kg.to_dict()))
        # "solo" has no relationships
        assert "solo" in r["isolated_entities"]

    def test_topology_present(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(graph_analytics(kg_data=kg.to_dict(), include_topology=True))
        assert "topology" in r
        topo = r["topology"]
        assert "entity_type_distribution" in topo
        assert "relationship_type_distribution" in topo
        assert "degree_stats" in topo

    def test_topology_entity_types(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(graph_analytics(kg_data=kg.to_dict()))
        topo = r["topology"]
        # 3 persons + 1 org
        assert topo["entity_type_distribution"].get("person", 0) == 3
        assert topo["entity_type_distribution"].get("org", 0) == 1

    def test_topology_degree_stats_keys(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(graph_analytics(kg_data=kg.to_dict()))
        ds = r["topology"]["degree_stats"]
        for k in ("min", "max", "avg"):
            assert k in ds, f"{k!r} missing from degree_stats"

    def test_no_quality_metrics_when_disabled(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        r = asyncio.run(graph_analytics(include_quality_metrics=False))
        assert "quality_metrics" not in r

    def test_no_completion_when_disabled(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        r = asyncio.run(graph_analytics(include_completion_analysis=False))
        assert "missing_relationships" not in r

    def test_no_topology_when_disabled(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        r = asyncio.run(graph_analytics(include_topology=False))
        assert "topology" not in r

    def test_missing_relationships_list(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(graph_analytics(kg_data=kg.to_dict()))
        assert isinstance(r["missing_relationships"], list)

    def test_max_completion_suggestions_respected(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_analytics import (
            graph_analytics,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_analytics(kg_data=kg.to_dict(), max_completion_suggestions=2)
        )
        assert len(r["missing_relationships"]) <= 2


# ===========================================================================
# 2. graph_link_predict MCP tool
# ===========================================================================
class TestGraphLinkPredictTool:
    """Tests for the graph_link_predict MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        assert callable(graph_link_predict)

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        r = asyncio.run(graph_link_predict("alice", "bob"))
        assert isinstance(r, dict)

    def test_has_status(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(graph_link_predict("alice", "bob", kg_data=kg.to_dict()))
        assert r["status"] == "success"

    def test_entity_ids_in_result(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(graph_link_predict("alice", "bob", kg_data=kg.to_dict()))
        assert r["entity_a_id"] == "alice"
        assert r["entity_b_id"] == "bob"

    def test_score_is_float(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(graph_link_predict("alice", "bob", kg_data=kg.to_dict()))
        assert isinstance(r["score"], float)

    def test_prediction_field(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(graph_link_predict("alice", "bob", kg_data=kg.to_dict()))
        assert r["prediction"] in ("likely", "unlikely")

    def test_missing_entity_score_zero(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_link_predict("alice", "nonexistent_entity", kg_data=kg.to_dict())
        )
        assert r["score"] == 0.0

    def test_layer_type_returned(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_link_predict("alice", "bob", kg_data=kg.to_dict(), layer_type="graph_conv")
        )
        assert r["layer_type"] == "graph_conv"

    def test_embedding_dim_returned(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_link_predict("alice", "bob", kg_data=kg.to_dict(), embedding_dim=32)
        )
        assert r["embedding_dim"] == 32

    def test_num_layers_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_link_predict("alice", "bob", kg_data=kg.to_dict(), num_layers=3)
        )
        assert r["status"] == "success"
        assert isinstance(r["score"], float)

    def test_top_candidates_returns_list(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_link_predict(
                "alice",
                "bob",
                kg_data=kg.to_dict(),
                top_candidates=["bob", "acme", "solo"],
                top_k=3,
            )
        )
        assert "top_predictions" in r
        assert isinstance(r["top_predictions"], list)
        assert len(r["top_predictions"]) <= 3

    def test_top_predictions_have_score(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_link_predict(
                "alice",
                "bob",
                kg_data=kg.to_dict(),
                top_candidates=["bob", "acme", "solo"],
            )
        )
        for pred in r["top_predictions"]:
            assert "entity_id" in pred
            assert "score" in pred
            assert isinstance(pred["score"], float)

    def test_no_top_candidates_no_top_predictions(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_link_predict import (
            graph_link_predict,
        )
        kg = _make_kg()
        r = asyncio.run(graph_link_predict("alice", "bob", kg_data=kg.to_dict()))
        assert "top_predictions" not in r


# ===========================================================================
# 3. KnowledgeGraphManager new methods
# ===========================================================================
class TestKnowledgeGraphManagerSession84:
    """Tests for analytics / link_predict KnowledgeGraphManager methods."""

    def _manager(self):
        from ipfs_datasets_py.core_operations.knowledge_graph_manager import (
            KnowledgeGraphManager,
        )
        return KnowledgeGraphManager()

    def test_analytics_method_exists(self):
        assert hasattr(self._manager(), "analytics")

    def test_link_predict_method_exists(self):
        assert hasattr(self._manager(), "link_predict")

    def test_analytics_returns_dict(self):
        r = asyncio.run(self._manager().analytics())
        assert isinstance(r, dict)
        assert "status" in r

    def test_link_predict_returns_dict(self):
        r = asyncio.run(self._manager().link_predict("a", "b"))
        assert isinstance(r, dict)
        assert "status" in r

    def test_analytics_with_kg(self):
        kg = _make_kg()
        r = asyncio.run(self._manager().analytics(kg_data=kg.to_dict()))
        assert r["entity_count"] == 4
        assert r["relationship_count"] == 3

    def test_link_predict_with_kg(self):
        kg = _make_kg()
        r = asyncio.run(
            self._manager().link_predict("alice", "bob", kg_data=kg.to_dict())
        )
        assert r["status"] == "success"
        assert "score" in r

    def test_analytics_quality_metrics_has_avg_confidence(self):
        kg = _make_kg()
        r = asyncio.run(self._manager().analytics(kg_data=kg.to_dict()))
        qm = r["quality_metrics"]
        assert "avg_entity_confidence" in qm
        assert 0.0 <= qm["avg_entity_confidence"] <= 1.0


# ===========================================================================
# 4. graph_tools __init__.py exports — 24 tools
# ===========================================================================
class TestGraphToolsExports84:
    """Tests for the updated graph_tools __init__.py (22→24 tools)."""

    def test_new_tools_in_init(self):
        init_text = (
            _BASE
            / "ipfs_datasets_py"
            / "mcp_server"
            / "tools"
            / "graph_tools"
            / "__init__.py"
        ).read_text(encoding="utf-8")
        for name in ("graph_analytics", "graph_link_predict"):
            assert f'"{name}"' in init_text, f"{name!r} missing from __init__.py"

    def test_total_tools_at_least_24(self):
        import re
        init_text = (
            _BASE
            / "ipfs_datasets_py"
            / "mcp_server"
            / "tools"
            / "graph_tools"
            / "__init__.py"
        ).read_text(encoding="utf-8")
        tool_names = re.findall(r'"(graph_\w+|query_knowledge_graph)"', init_text)
        assert len(tool_names) >= 24, f"Expected >=24 tools, got {len(tool_names)}"


# ===========================================================================
# 5. Documentation integrity
# ===========================================================================
class TestDocumentationIntegrity84:
    def test_master_status_has_v3_22_38(self):
        assert "3.22.38" in _read(_MASTER), "MASTER_STATUS.md should mention v3.22.38"

    def test_roadmap_has_v3_22_38(self):
        assert "3.22.38" in _read(_ROADMAP), "ROADMAP.md should mention v3.22.38"

    def test_changelog_has_session_84(self):
        content = _read(_CHANGELOG)
        assert "3.22.38" in content or "session84" in content.lower() or "Session 84" in content

    def test_readme_has_graph_analytics(self):
        assert "graph_analytics" in _read(_README_GT)

    def test_readme_has_graph_link_predict(self):
        assert "graph_link_predict" in _read(_README_GT)
