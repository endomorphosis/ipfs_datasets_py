"""Session 73 doc + production integrity tests.

Knowledge Graphs — Session 73 (2026-02-23)

Covers:
- KnowledgeGraphVisualizer production feature (extraction/visualization.py):
  * to_dot(): Graphviz DOT format
  * to_mermaid(): Mermaid.js notation
  * to_d3_json(): D3.js force-directed graph JSON
  * to_ascii(): ASCII-art tree (flat roster + rooted DFS)
- KnowledgeGraph convenience methods: to_dot / to_mermaid / to_d3_json / to_ascii
- extraction/__init__.py: KnowledgeGraphVisualizer exported in __all__
- DEFERRED_FEATURES §20 Advanced Visualization Tools entry
- ROADMAP.md v4.0+ "Advanced visualization tools" delivered in v3.22.27
- MASTER_STATUS / CHANGELOG / ROADMAP version agreement (v3.22.27)
"""

import json
import sys
import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_KG_DIR = _REPO_ROOT / "ipfs_datasets_py" / "knowledge_graphs"

# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------

def _make_kg():
    """Build a 3-entity, 2-relationship test graph."""
    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
    kg = KnowledgeGraph("social")
    alice = kg.add_entity("person", "Alice", {"age": 30})
    bob   = kg.add_entity("person", "Bob",   {"age": 25})
    acme  = kg.add_entity("org",    "Acme Corp")
    kg.add_relationship("knows",    alice, bob)
    kg.add_relationship("works_at", bob,   acme)
    return kg, alice, bob, acme


# ===========================================================================
# 1. to_dot()
# ===========================================================================

class TestKnowledgeGraphVisualizerDOT:
    """KnowledgeGraphVisualizer.to_dot() generates valid Graphviz DOT."""

    def test_empty_graph_produces_dot(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("empty")
        dot = KnowledgeGraphVisualizer(kg).to_dot()
        assert dot.startswith("digraph")
        assert "}" in dot

    def test_single_entity_in_dot(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        e = kg.add_entity("person", "Alice")
        dot = KnowledgeGraphVisualizer(kg).to_dot()
        assert e.entity_id in dot

    def test_entity_name_in_label(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice")
        dot = KnowledgeGraphVisualizer(kg).to_dot()
        assert "Alice" in dot

    def test_entity_type_in_label(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice")
        dot = KnowledgeGraphVisualizer(kg).to_dot()
        assert "person" in dot

    def test_relationship_edge_in_dot(self):
        kg, alice, bob, _ = _make_kg()
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphVisualizer
        dot = KnowledgeGraphVisualizer(kg).to_dot()
        assert "->" in dot
        assert "knows" in dot

    def test_custom_graph_name(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        dot = KnowledgeGraphVisualizer(kg).to_dot(graph_name="MyCustomName")
        assert "MyCustomName" in dot

    def test_undirected_graph_uses_graph_keyword(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice")
        kg.add_entity("person", "Bob")
        r = kg.add_relationship("knows", list(kg.entities.values())[0], list(kg.entities.values())[1])
        dot = KnowledgeGraphVisualizer(kg).to_dot(directed=False)
        assert dot.startswith("graph")
        assert "--" in dot
        assert "digraph" not in dot
        assert "->" not in dot

    def test_special_chars_escaped(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        kg.add_entity("type", 'Name "with" quotes')
        dot = KnowledgeGraphVisualizer(kg).to_dot()
        # Should not break DOT syntax — double-quote escaped
        assert '\\"' in dot


# ===========================================================================
# 2. to_mermaid()
# ===========================================================================

class TestKnowledgeGraphVisualizerMermaid:
    """KnowledgeGraphVisualizer.to_mermaid() generates valid Mermaid.js."""

    def test_starts_with_graph_keyword(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        mmd = KnowledgeGraphVisualizer(kg).to_mermaid()
        assert mmd.startswith("graph")

    def test_default_direction_lr(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        mmd = KnowledgeGraphVisualizer(kg).to_mermaid()
        assert "graph LR" in mmd

    def test_custom_direction_tb(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        mmd = KnowledgeGraphVisualizer(kg).to_mermaid(direction="TB")
        assert "graph TB" in mmd

    def test_entity_node_present(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        e = kg.add_entity("person", "Alice")
        mmd = KnowledgeGraphVisualizer(kg).to_mermaid()
        assert e.entity_id in mmd
        assert "Alice" in mmd

    def test_relationship_edge_present(self):
        kg, alice, bob, _ = _make_kg()
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphVisualizer
        mmd = KnowledgeGraphVisualizer(kg).to_mermaid()
        assert "-->" in mmd
        assert "knows" in mmd

    def test_max_entities_truncation(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        for i in range(5):
            kg.add_entity("node", f"N{i}")
        mmd = KnowledgeGraphVisualizer(kg).to_mermaid(max_entities=2)
        # Only 2 entity node declarations
        node_lines = [ln for ln in mmd.splitlines() if "[\"" in ln]
        assert len(node_lines) == 2

    def test_relationship_excluded_when_entity_excluded(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        a = kg.add_entity("person", "A")
        b = kg.add_entity("person", "B")
        kg.add_relationship("knows", a, b)
        # Limit to 1 entity — the relationship should be excluded
        mmd = KnowledgeGraphVisualizer(kg).to_mermaid(max_entities=1)
        assert "-->" not in mmd


# ===========================================================================
# 3. to_d3_json()
# ===========================================================================

class TestKnowledgeGraphVisualizerD3JSON:
    """KnowledgeGraphVisualizer.to_d3_json() generates valid D3 data."""

    def test_nodes_key_present(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        d3 = KnowledgeGraphVisualizer(kg).to_d3_json()
        assert "nodes" in d3

    def test_links_key_present(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        d3 = KnowledgeGraphVisualizer(kg).to_d3_json()
        assert "links" in d3

    def test_node_fields(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice", {"x": 1})
        d3 = KnowledgeGraphVisualizer(kg).to_d3_json()
        node = d3["nodes"][0]
        assert node["name"] == "Alice"
        assert node["type"] == "person"
        assert "id" in node
        assert "confidence" in node
        assert "properties" in node
        assert node["properties"].get("x") == 1

    def test_link_fields(self):
        kg, alice, bob, _ = _make_kg()
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphVisualizer
        d3 = KnowledgeGraphVisualizer(kg).to_d3_json()
        link = next(ln for ln in d3["links"] if ln["type"] == "knows")
        assert link["source"] == alice.entity_id
        assert link["target"] == bob.entity_id
        assert "confidence" in link
        assert "properties" in link

    def test_empty_graph(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("empty")
        d3 = KnowledgeGraphVisualizer(kg).to_d3_json()
        assert d3["nodes"] == []
        assert d3["links"] == []

    def test_max_nodes_truncation(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        for i in range(5):
            kg.add_entity("node", f"N{i}")
        d3 = KnowledgeGraphVisualizer(kg).to_d3_json(max_nodes=3)
        assert len(d3["nodes"]) == 3

    def test_valid_json_round_trip(self):
        kg, _, _, _ = _make_kg()
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphVisualizer
        d3 = KnowledgeGraphVisualizer(kg).to_d3_json()
        serialised = json.dumps(d3)
        restored = json.loads(serialised)
        assert len(restored["nodes"]) == 3
        assert len(restored["links"]) == 2


# ===========================================================================
# 4. to_ascii()
# ===========================================================================

class TestKnowledgeGraphVisualizerASCII:
    """KnowledgeGraphVisualizer.to_ascii() generates readable ASCII output."""

    def test_header_contains_graph_name(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("my_graph")
        ascii_str = KnowledgeGraphVisualizer(kg).to_ascii()
        assert "my_graph" in ascii_str

    def test_header_contains_entity_count(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice")
        ascii_str = KnowledgeGraphVisualizer(kg).to_ascii()
        assert "1 entity" in ascii_str

    def test_header_contains_relationship_count(self):
        kg, _, _, _ = _make_kg()
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphVisualizer
        ascii_str = KnowledgeGraphVisualizer(kg).to_ascii()
        assert "2 relationships" in ascii_str

    def test_entity_name_present(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice")
        ascii_str = KnowledgeGraphVisualizer(kg).to_ascii()
        assert "Alice" in ascii_str

    def test_relationship_shown_in_flat(self):
        kg, _, _, _ = _make_kg()
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphVisualizer
        ascii_str = KnowledgeGraphVisualizer(kg).to_ascii()
        assert "knows" in ascii_str
        assert "→" in ascii_str

    def test_rooted_tree_uses_root_entity(self):
        kg, alice, bob, _ = _make_kg()
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphVisualizer
        ascii_str = KnowledgeGraphVisualizer(kg).to_ascii(root_entity_id=alice.entity_id)
        assert "Alice" in ascii_str
        assert "knows" in ascii_str

    def test_empty_graph_returns_header_only(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("empty")
        ascii_str = KnowledgeGraphVisualizer(kg).to_ascii()
        assert ascii_str == "empty (0 entities, 0 relationships)"

    def test_max_depth_limits_traversal(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        # Build a chain: A→B→C→D (depth 3)
        kg = KnowledgeGraph("chain")
        a = kg.add_entity("node", "A")
        b = kg.add_entity("node", "B")
        c = kg.add_entity("node", "C")
        d = kg.add_entity("node", "D")
        kg.add_relationship("next", a, b)
        kg.add_relationship("next", b, c)
        kg.add_relationship("next", c, d)
        # max_depth=1 from A: should show B but not C or D
        ascii_str = KnowledgeGraphVisualizer(kg).to_ascii(
            root_entity_id=a.entity_id, max_depth=1
        )
        # C appears in the flat roster but not reachable from A in 1 hop
        assert "B" in ascii_str


# ===========================================================================
# 5. KnowledgeGraph convenience methods
# ===========================================================================

class TestKGConvenienceMethods:
    """KnowledgeGraph.to_dot/to_mermaid/to_d3_json/to_ascii delegate correctly."""

    def test_kg_to_dot(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice")
        dot = kg.to_dot()
        assert "digraph" in dot
        assert "Alice" in dot

    def test_kg_to_mermaid(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice")
        mmd = kg.to_mermaid()
        assert "graph LR" in mmd
        assert "Alice" in mmd

    def test_kg_to_d3_json(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice")
        d3 = kg.to_d3_json()
        assert isinstance(d3, dict)
        assert d3["nodes"][0]["name"] == "Alice"

    def test_kg_to_ascii(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "Alice")
        ascii_str = kg.to_ascii()
        assert isinstance(ascii_str, str)
        assert "Alice" in ascii_str

    def test_kg_convenience_kwargs_forwarded(self):
        """Ensure kwargs (directed=False, direction='TB') reach the visualizer."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("g")
        kg.add_entity("person", "A")
        kg.add_entity("person", "B")
        entities = list(kg.entities.values())
        kg.add_relationship("knows", entities[0], entities[1])
        dot_undir = kg.to_dot(directed=False)
        assert "graph" in dot_undir and "digraph" not in dot_undir
        mmd_tb = kg.to_mermaid(direction="TB")
        assert "graph TB" in mmd_tb


# ===========================================================================
# 6. extraction module exports
# ===========================================================================

class TestVisualizerExports:
    """KnowledgeGraphVisualizer is properly exported from extraction."""

    def test_importable_from_extraction(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphVisualizer
        assert KnowledgeGraphVisualizer is not None

    def test_in_all(self):
        import ipfs_datasets_py.knowledge_graphs.extraction as pkg
        assert "KnowledgeGraphVisualizer" in pkg.__all__

    def test_instantiable(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            KnowledgeGraph, KnowledgeGraphVisualizer,
        )
        kg = KnowledgeGraph("g")
        vis = KnowledgeGraphVisualizer(kg)
        assert vis.kg is kg


# ===========================================================================
# 7. Documentation integrity
# ===========================================================================

class TestDocIntegritySession73:
    """Deferred features + roadmap docs reflect session 73 deliverables."""

    def test_deferred_features_has_visualization_section(self):
        content = (_KG_DIR / "DEFERRED_FEATURES.md").read_text()
        assert "Advanced Visualization Tools" in content

    def test_deferred_features_has_p8_section(self):
        content = (_KG_DIR / "DEFERRED_FEATURES.md").read_text()
        assert "P8" in content

    def test_deferred_features_visualization_implemented(self):
        content = (_KG_DIR / "DEFERRED_FEATURES.md").read_text()
        assert "✅ Implemented" in content
        assert "3.22.27" in content

    def test_roadmap_visualization_delivered(self):
        content = (_KG_DIR / "ROADMAP.md").read_text()
        assert "Advanced visualization tools" in content
        assert "3.22.27" in content or "Delivered in v3.22.27" in content

    def test_master_status_version_327(self):
        content = (_KG_DIR / "MASTER_STATUS.md").read_text()
        assert "3.22.27" in content

    def test_changelog_has_327_section(self):
        content = (_KG_DIR / "CHANGELOG_KNOWLEDGE_GRAPHS.md").read_text()
        assert "3.22.27" in content


# ===========================================================================
# 8. Version agreement
# ===========================================================================

class TestVersionAgreement:
    """MASTER_STATUS / CHANGELOG / ROADMAP all agree on v3.22.27."""

    def test_master_status_version(self):
        content = (_KG_DIR / "MASTER_STATUS.md").read_text()
        assert "3.22.27" in content

    def test_changelog_latest_version(self):
        content = (_KG_DIR / "CHANGELOG_KNOWLEDGE_GRAPHS.md").read_text()
        assert "3.22.27" in content

    def test_roadmap_current_version(self):
        content = (_KG_DIR / "ROADMAP.md").read_text()
        assert "3.22.27" in content
