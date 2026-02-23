"""
Session 64 – QUICKSTART.md API accuracy + MASTER_STATUS Feature Coverage Matrix tests.

Tests verify:
1. QUICKSTART.md: five stale API examples fixed (rel.source→rel.source_id,
   engine.execute→engine.execute_cypher, result iter→result.items,
   backend.store(kg)→backend.store(kg.to_dict()), HybridSearch→HybridSearchEngine,
   top_k→k, combine_strategy removed, result.entity.name→result.node_id)
2. MASTER_STATUS.md: Feature Completeness Matrix coverage % updated from 40-85% → 99-100%
3. Three-doc version agreement: MASTER_STATUS/ROADMAP/CHANGELOG all on v3.22.18
"""

import re
from pathlib import Path

import pytest

# ── paths ────────────────────────────────────────────────────────────────────
_KG = Path(__file__).parents[3] / "ipfs_datasets_py" / "knowledge_graphs"
_QS = _KG / "QUICKSTART.md"
_MS = _KG / "MASTER_STATUS.md"
_RR = _KG / "ROADMAP.md"
_CL = _KG / "CHANGELOG_KNOWLEDGE_GRAPHS.md"


def _qs():
    return _QS.read_text(encoding="utf-8")


def _ms():
    return _MS.read_text(encoding="utf-8")


# ── TestQuickstartRelAttributes ──────────────────────────────────────────────

class TestQuickstartRelAttributes:
    """rel.source / rel.target are non-existent; must use .source_id/.target_id."""

    def test_rel_source_id_present(self):
        assert "rel.source_id" in _qs(), "QUICKSTART must use rel.source_id"

    def test_rel_target_id_present(self):
        assert "rel.target_id" in _qs(), "QUICKSTART must use rel.target_id"

    def test_rel_source_direct_absent(self):
        content = _qs()
        # allow "source_id", "source_entity" — just not a bare "rel.source "
        assert "rel.source " not in content and "rel.source\n" not in content, (
            "QUICKSTART must not use bare rel.source (no such attribute)"
        )

    def test_rel_target_direct_absent(self):
        content = _qs()
        assert "rel.target " not in content and "rel.target\n" not in content, (
            "QUICKSTART must not use bare rel.target (no such attribute)"
        )

    def test_source_entity_attr_shown(self):
        assert "rel.source_entity" in _qs() or "source_id" in _qs(), (
            "QUICKSTART must reference source_entity or source_id"
        )


# ── TestQuickstartEngineAPI ──────────────────────────────────────────────────

class TestQuickstartEngineAPI:
    """execute_cypher is the correct method; engine.execute() doesn't exist."""

    def test_execute_cypher_present(self):
        assert "execute_cypher" in _qs(), (
            "QUICKSTART must use engine.execute_cypher()"
        )

    def test_engine_execute_bare_absent(self):
        # Should not have "engine.execute(" without "execute_cypher" or "_query"
        content = _qs()
        bare_execute = re.findall(r"engine\.execute\s*\(", content)
        assert len(bare_execute) == 0, (
            f"QUICKSTART must not use bare engine.execute(); found {bare_execute}"
        )

    def test_result_items_present(self):
        assert "result.items" in _qs(), (
            "QUICKSTART must iterate result.items (QueryResult has .items, not __iter__)"
        )

    def test_add_knowledge_graph_absent(self):
        assert "add_knowledge_graph" not in _qs(), (
            "QUICKSTART must not call backend.add_knowledge_graph() — no such method"
        )


# ── TestQuickstartIPFSStoreAPI ───────────────────────────────────────────────

class TestQuickstartIPFSStoreAPI:
    """backend.store() takes bytes/str/dict, not a KnowledgeGraph object."""

    def test_store_dict_call_present(self):
        content = _qs()
        assert "kg.to_dict()" in content or "store(kg.to_dict())" in content, (
            "QUICKSTART IPFS example must call backend.store(kg.to_dict())"
        )

    def test_retrieve_json_or_data_present(self):
        content = _qs()
        # retrieve_json returns dict; retrieve returns bytes
        assert "retrieve_json" in content or "retrieve" in content, (
            "QUICKSTART must show retrieve / retrieve_json"
        )

    def test_retrieved_entities_from_dict(self):
        content = _qs()
        # The retrieve example should reference dict data, not retrieved_kg.entities
        assert "retrieved_kg.entities" not in content, (
            "QUICKSTART must not show retrieved_kg.entities — retrieve() returns bytes, not KG"
        )


# ── TestQuickstartHybridSearch ───────────────────────────────────────────────

class TestQuickstartHybridSearch:
    """HybridSearchEngine is the correct class (not HybridSearch); API arg fixes."""

    def test_hybrid_search_engine_class_present(self):
        assert "HybridSearchEngine" in _qs(), (
            "QUICKSTART must use HybridSearchEngine, not HybridSearch"
        )

    def test_hybrid_search_bare_absent(self):
        content = _qs()
        # Allow "HybridSearchEngine" but not standalone "HybridSearch("
        assert "HybridSearch(" not in content.replace("HybridSearchEngine(", ""), (
            "QUICKSTART must not reference bare HybridSearch() class"
        )

    def test_top_k_absent(self):
        assert "top_k=" not in _qs(), (
            "QUICKSTART must not use top_k= — correct kwarg is k="
        )

    def test_k_arg_present(self):
        assert re.search(r"\bk\s*=\s*\d", _qs()), (
            "QUICKSTART must use k=N argument in HybridSearchEngine.search()"
        )

    def test_combine_strategy_absent(self):
        assert "combine_strategy" not in _qs(), (
            "QUICKSTART must not use combine_strategy= — no such argument"
        )

    def test_result_node_id_present(self):
        assert "result.node_id" in _qs(), (
            "QUICKSTART must use result.node_id (HybridSearchResult has node_id not entity)"
        )

    def test_result_entity_name_absent(self):
        assert "result.entity.name" not in _qs(), (
            "QUICKSTART must not use result.entity.name — HybridSearchResult has no entity attr"
        )


# ── TestMasterStatusCoverageMatrix ───────────────────────────────────────────

class TestMasterStatusCoverageMatrix:
    """Feature Completeness Matrix coverage % must reflect current 99-100% reality."""

    def test_stale_85_percent_absent_in_core_table(self):
        content = _ms()
        # Find the Feature Completeness Matrix section
        matrix_start = content.find("### Core Features (All Complete")
        matrix_end = content.find("## Recent Major Changes", matrix_start)
        matrix_section = content[matrix_start:matrix_end]
        assert "| 85%" not in matrix_section, (
            "Feature Completeness Matrix must not have stale 85% entries"
        )

    def test_stale_40_percent_absent(self):
        content = _ms()
        matrix_start = content.find("### Core Features (All Complete")
        matrix_end = content.find("## Recent Major Changes", matrix_start)
        matrix_section = content[matrix_start:matrix_end]
        assert "| 40%" not in matrix_section, (
            "Feature Completeness Matrix must not have stale 40% migration entries"
        )

    def test_stale_70_percent_absent_in_core_features(self):
        content = _ms()
        matrix_start = content.find("### Core Features (All Complete")
        matrix_end = content.find("### Migration & Compatibility", matrix_start)
        core_section = content[matrix_start:matrix_end]
        assert "| 70%" not in core_section, (
            "Core feature rows must not show stale 70% coverage"
        )

    def test_100_percent_present_in_cypher_rows(self):
        content = _ms()
        # After the fix, all Cypher rows should show 100%
        cypher_section_start = content.find("### Query Capabilities")
        cypher_section_end = content.find("### Advanced Features", cypher_section_start)
        cypher_section = content[cypher_section_start:cypher_section_end]
        assert "100%" in cypher_section, (
            "Cypher rows in Feature Matrix should show 100% coverage"
        )

    def test_100_percent_in_migration_table(self):
        content = _ms()
        mig_start = content.find("### Migration & Compatibility")
        mig_end = content.find("## Recent Major Changes", mig_start)
        mig_section = content[mig_start:mig_end]
        assert "100%" in mig_section, (
            "Migration table must show 100% after s29+ coverage work"
        )


# ── TestThreeDocVersionAgreement ─────────────────────────────────────────────

class TestThreeDocVersionAgreement:
    """MASTER_STATUS, ROADMAP, and CHANGELOG must all agree on v3.22.18."""

    def test_master_status_version(self):
        content = _ms()
        assert "3.22.18" in content, "MASTER_STATUS must reference v3.22.18"

    def test_roadmap_version(self):
        content = _RR.read_text(encoding="utf-8")
        assert "3.22.18" in content, "ROADMAP must reference v3.22.18"

    def test_changelog_version(self):
        content = _CL.read_text(encoding="utf-8")
        assert "3.22.18" in content, "CHANGELOG must have a v3.22.18 section"
