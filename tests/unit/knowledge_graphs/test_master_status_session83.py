"""
Tests for Session 83: 3 new MCP tools for GNN, ZKP, and Federation.

Session 83 (v3.22.37):
- graph_gnn_embed.py   — compute GNN node embeddings via GraphNeuralNetworkAdapter
- graph_zkp_prove.py   — generate ZK proofs via KGZKProver + KGWitnessBuilder
- graph_federate_query.py — query across federated KGs via FederatedKnowledgeGraph
- 3 new KnowledgeGraphManager methods: gnn_embed / zkp_prove / federate_query
- graph_tools/__init__.py updated (19→22 tools), README.md updated
"""

from __future__ import annotations

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
_README_GT = (
    _BASE / "ipfs_datasets_py" / "mcp_server" / "tools" / "graph_tools" / "README.md"
)


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _make_kg(name="test_session83"):
    """Build a small test KnowledgeGraph with 3 entities + 2 relationships."""
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
        KnowledgeGraph,
        Entity,
        Relationship,
    )

    kg = KnowledgeGraph(name=name)
    alice = Entity(entity_id="alice", entity_type="person", name="alice")
    bob = Entity(entity_id="bob", entity_type="person", name="bob")
    acme = Entity(entity_id="acme", entity_type="org", name="acme")
    for e in (alice, bob, acme):
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
    return kg


# ===========================================================================
# 1. MCP tool: graph_gnn_embed
# ===========================================================================
class TestGraphGNNEmbedTool:
    """Tests for the graph_gnn_embed MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        assert callable(graph_gnn_embed)

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        r = asyncio.run(graph_gnn_embed())
        assert isinstance(r, dict)

    def test_has_status(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        r = asyncio.run(graph_gnn_embed())
        assert "status" in r

    def test_empty_graph_success(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        r = asyncio.run(graph_gnn_embed())
        assert r["status"] == "success"
        assert r["entity_count"] == 0
        assert r["embeddings"] == {}

    def test_with_kg_data(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        kg = _make_kg()
        r = asyncio.run(graph_gnn_embed(kg_data=kg.to_dict()))
        assert r["status"] == "success"
        assert r["entity_count"] == 3

    def test_embeddings_keys_match_entity_ids(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        kg = _make_kg()
        r = asyncio.run(graph_gnn_embed(kg_data=kg.to_dict()))
        assert set(r["embeddings"].keys()) == {"alice", "bob", "acme"}

    def test_embeddings_are_float_lists(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        kg = _make_kg()
        r = asyncio.run(graph_gnn_embed(kg_data=kg.to_dict()))
        for eid, vec in r["embeddings"].items():
            assert isinstance(vec, list), f"{eid}: not a list"
            assert all(isinstance(v, (int, float)) for v in vec), f"{eid}: non-numeric"

    def test_top_k_similar(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_gnn_embed(kg_data=kg.to_dict(), entity_ids=["alice"], top_k_similar=2)
        )
        assert "alice" in r["similar"]
        assert isinstance(r["similar"]["alice"], list)

    def test_layer_type_graph_conv(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        kg = _make_kg()
        r = asyncio.run(graph_gnn_embed(kg_data=kg.to_dict(), layer_type="graph_conv"))
        assert r["status"] == "success"
        assert r["layer_type"] == "graph_conv"

    def test_layer_type_attention(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_gnn_embed(kg_data=kg.to_dict(), layer_type="graph_attention")
        )
        assert r["status"] == "success"

    def test_embedding_dim_in_result(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_gnn_embed import (
            graph_gnn_embed,
        )
        kg = _make_kg()
        r = asyncio.run(graph_gnn_embed(kg_data=kg.to_dict(), embedding_dim=32))
        assert r["embedding_dim"] == 32


# ===========================================================================
# 2. MCP tool: graph_zkp_prove
# ===========================================================================
class TestGraphZKPProveTool:
    """Tests for the graph_zkp_prove MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        assert callable(graph_zkp_prove)

    def test_entity_exists_default(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(
            graph_zkp_prove(
                proof_type="entity_exists",
                entity_type="person",
                entity_name="Alice",
            )
        )
        assert isinstance(r, dict)
        assert r["status"] == "success"

    def test_proof_type_in_result(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(
            graph_zkp_prove(
                proof_type="entity_exists",
                entity_type="person",
                entity_name="Alice",
            )
        )
        assert r["proof_type"] == "entity_exists"

    def test_proof_is_dict(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(
            graph_zkp_prove(proof_type="entity_exists", entity_type="org", entity_name="ACME")
        )
        assert isinstance(r["proof"], dict)

    def test_valid_is_bool(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(
            graph_zkp_prove(proof_type="entity_exists", entity_type="person", entity_name="Bob")
        )
        assert isinstance(r["valid"], bool)

    def test_path_exists_proof(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(
            graph_zkp_prove(
                proof_type="path_exists",
                path_start_type="person",
                path_end_type="org",
            )
        )
        assert r["status"] == "success"
        assert r["proof"] is not None

    def test_query_count_proof(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(
            graph_zkp_prove(
                proof_type="query_answer_count",
                min_count=3,
                actual_count=5,
            )
        )
        assert r["status"] == "success"

    def test_build_tdfol_witness_false(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(
            graph_zkp_prove(proof_type="entity_exists", entity_type="person", entity_name="X")
        )
        assert "tdfol_witness" not in r

    def test_build_tdfol_witness_true(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(
            graph_zkp_prove(
                proof_type="entity_exists",
                entity_type="person",
                entity_name="Alice",
                entity_id="eid_001",
                build_tdfol_witness=True,
            )
        )
        assert r["status"] == "success"
        assert "tdfol_witness" in r
        assert isinstance(r["tdfol_witness"], dict)

    def test_tdfol_witness_has_theorem(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(
            graph_zkp_prove(
                proof_type="entity_exists",
                entity_type="person",
                entity_name="Alice",
                entity_id="eid_001",
                build_tdfol_witness=True,
            )
        )
        assert "theorem" in r["tdfol_witness"]

    def test_unknown_proof_type_returns_error(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        r = asyncio.run(graph_zkp_prove(proof_type="invalid_proof_type"))
        assert r["status"] == "error"

    def test_with_kg_data(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_zkp_prove import (
            graph_zkp_prove,
        )
        kg = _make_kg()
        r = asyncio.run(
            graph_zkp_prove(
                proof_type="entity_exists",
                entity_type="person",
                entity_name="alice",
                kg_data=kg.to_dict(),
            )
        )
        assert r["status"] == "success"


# ===========================================================================
# 3. MCP tool: graph_federate_query
# ===========================================================================
class TestGraphFederateQueryTool:
    """Tests for the graph_federate_query MCP tool."""

    def test_import(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_federate_query import (
            graph_federate_query,
        )
        assert callable(graph_federate_query)

    def test_empty_graphs_success(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_federate_query import (
            graph_federate_query,
        )
        r = asyncio.run(graph_federate_query())
        assert r["status"] == "success"
        assert r["graph_count"] == 0

    def test_with_two_graphs(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_federate_query import (
            graph_federate_query,
        )
        kg1 = _make_kg("kg_a")
        kg2 = _make_kg("kg_b")
        r = asyncio.run(
            graph_federate_query(graphs=[kg1.to_dict(), kg2.to_dict()])
        )
        assert r["status"] == "success"
        assert r["graph_count"] == 2

    def test_entity_matches_returned(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_federate_query import (
            graph_federate_query,
        )
        kg1 = _make_kg("kg_a")
        kg2 = _make_kg("kg_b")
        r = asyncio.run(
            graph_federate_query(graphs=[kg1.to_dict(), kg2.to_dict()])
        )
        assert "entity_matches" in r
        assert isinstance(r["entity_matches"], list)

    def test_query_entity_name(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_federate_query import (
            graph_federate_query,
        )
        kg1 = _make_kg("kg_a")
        kg2 = _make_kg("kg_b")
        r = asyncio.run(
            graph_federate_query(
                graphs=[kg1.to_dict(), kg2.to_dict()],
                query_entity_name="alice",
            )
        )
        assert "query_hits" in r
        assert len(r["query_hits"]) >= 1

    def test_merge_mode(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_federate_query import (
            graph_federate_query,
        )
        kg1 = _make_kg("kg_a")
        kg2 = _make_kg("kg_b")
        r = asyncio.run(
            graph_federate_query(graphs=[kg1.to_dict(), kg2.to_dict()], merge=True)
        )
        assert r["status"] == "success"
        assert "merged_entity_count" in r
        assert "merged_relationship_count" in r

    def test_resolution_strategy_exact_name(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_federate_query import (
            graph_federate_query,
        )
        kg1 = _make_kg("kg_a")
        r = asyncio.run(
            graph_federate_query(
                graphs=[kg1.to_dict()],
                resolution_strategy="exact_name",
            )
        )
        assert r["status"] == "success"
        assert r["resolution_strategy"] == "exact_name"

    def test_no_merge_no_merged_keys(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_federate_query import (
            graph_federate_query,
        )
        kg1 = _make_kg("kg_a")
        r = asyncio.run(graph_federate_query(graphs=[kg1.to_dict()], merge=False))
        assert "merged_entity_count" not in r


# ===========================================================================
# 4. KnowledgeGraphManager — new methods
# ===========================================================================
class TestKnowledgeGraphManagerNewMethods:
    """Tests for the 3 new KnowledgeGraphManager methods."""

    def _manager(self):
        from ipfs_datasets_py.core_operations.knowledge_graph_manager import (
            KnowledgeGraphManager,
        )
        return KnowledgeGraphManager()

    def test_gnn_embed_method_exists(self):
        assert hasattr(self._manager(), "gnn_embed")

    def test_zkp_prove_method_exists(self):
        assert hasattr(self._manager(), "zkp_prove")

    def test_federate_query_method_exists(self):
        assert hasattr(self._manager(), "federate_query")

    def test_gnn_embed_returns_dict(self):
        mgr = self._manager()
        r = asyncio.run(mgr.gnn_embed())
        assert isinstance(r, dict)
        assert "status" in r

    def test_zkp_prove_returns_dict(self):
        mgr = self._manager()
        r = asyncio.run(mgr.zkp_prove(proof_type="entity_exists", entity_type="person", entity_name="Alice"))
        assert isinstance(r, dict)
        assert "status" in r

    def test_federate_query_returns_dict(self):
        mgr = self._manager()
        r = asyncio.run(mgr.federate_query())
        assert isinstance(r, dict)
        assert "status" in r

    def test_gnn_embed_with_kg(self):
        mgr = self._manager()
        kg = _make_kg()
        r = asyncio.run(mgr.gnn_embed(kg_data=kg.to_dict()))
        assert r["entity_count"] == 3

    def test_zkp_prove_valid(self):
        mgr = self._manager()
        r = asyncio.run(
            mgr.zkp_prove(
                proof_type="entity_exists",
                entity_type="person",
                entity_name="Alice",
            )
        )
        assert "valid" in r

    def test_federate_query_with_kg(self):
        mgr = self._manager()
        kg = _make_kg()
        r = asyncio.run(mgr.federate_query(graphs=[kg.to_dict()]))
        assert r["graph_count"] == 1


# ===========================================================================
# 5. graph_tools __init__.py exports — 22 tools
# ===========================================================================
class TestGraphToolsExports:
    """Tests for the updated graph_tools __init__.py."""

    def test_three_new_tools_in_all(self):
        # Import from the real package (relative imports work correctly)
        import sys
        import importlib
        # Make sure the package is importable with PYTHONPATH set
        _gt_path = str(_BASE)
        if _gt_path not in sys.path:
            sys.path.insert(0, _gt_path)
        # Import __all__ from the actual module file
        all_text = (_BASE / "ipfs_datasets_py" / "mcp_server" / "tools" / "graph_tools" / "__init__.py").read_text(encoding="utf-8")
        for name in ("graph_gnn_embed", "graph_zkp_prove", "graph_federate_query"):
            assert f'"{name}"' in all_text, f"{name!r} missing from __init__.py __all__"

    def test_total_tools_count(self):
        all_text = (_BASE / "ipfs_datasets_py" / "mcp_server" / "tools" / "graph_tools" / "__init__.py").read_text(encoding="utf-8")
        # Count quoted names in __all__
        import re
        tool_names = re.findall(r'"(graph_\w+|query_knowledge_graph)"', all_text)
        assert len(tool_names) >= 22, f"Expected >=22 tools, got {len(tool_names)}: {tool_names}"


# ===========================================================================
# 6. Documentation integrity
# ===========================================================================
class TestDocumentationIntegrity:
    def test_master_status_has_v3_22_37(self):
        content = _read(_MASTER)
        assert "3.22.37" in content, "MASTER_STATUS.md should mention v3.22.37"

    def test_roadmap_has_v3_22_37(self):
        content = _read(_ROADMAP)
        assert "3.22.37" in content, "ROADMAP.md should mention v3.22.37"

    def test_changelog_has_session_83(self):
        content = _read(_CHANGELOG)
        assert "83" in content or "session83" in content.lower()

    def test_readme_has_gnn_embed(self):
        content = _read(_README_GT)
        assert "graph_gnn_embed" in content

    def test_readme_has_zkp_prove(self):
        content = _read(_README_GT)
        assert "graph_zkp_prove" in content

    def test_readme_has_federate_query(self):
        content = _read(_README_GT)
        assert "graph_federate_query" in content
