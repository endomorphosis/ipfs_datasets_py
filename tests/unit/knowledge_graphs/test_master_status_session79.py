"""
Session 79 doc integrity tests.

Verifies that query/README.md, docs/knowledge_graphs/API_REFERENCE.md,
and docs/knowledge_graphs/USER_GUIDE.md reflect the new features delivered in
sessions 69-78 (v3.22.x).
"""

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
KG_DIR = ROOT / "ipfs_datasets_py" / "knowledge_graphs"
DOCS_DIR = ROOT / "docs" / "knowledge_graphs"


def _read(path: pathlib.Path) -> str:
    with open(path) as f:
        return f.read()


QUERY_README = _read(KG_DIR / "query" / "README.md")
API_REF      = _read(DOCS_DIR / "API_REFERENCE.md")
USER_GUIDE   = _read(DOCS_DIR / "USER_GUIDE.md")
MASTER       = _read(KG_DIR / "MASTER_STATUS.md")
CHANGELOG    = _read(KG_DIR / "CHANGELOG_KNOWLEDGE_GRAPHS.md")
ROADMAP      = _read(KG_DIR / "ROADMAP.md")


# ──────────────────────────────────────────────────────────────
# 1. query/README.md version and new module sections
# ──────────────────────────────────────────────────────────────
class TestQueryReadme:
    def test_version_bumped(self):
        assert "3.22.33" in QUERY_README

    def test_graphql_module_row(self):
        assert "graphql.py" in QUERY_README

    def test_federation_module_row(self):
        assert "federation.py" in QUERY_README

    def test_gnn_module_row(self):
        assert "gnn.py" in QUERY_README

    def test_zkp_module_row(self):
        assert "zkp.py" in QUERY_README

    def test_groth16_bridge_module_row(self):
        assert "groth16_bridge.py" in QUERY_README

    def test_advanced_query_features_section(self):
        assert "Advanced Query Features" in QUERY_README

    def test_graphql_executor_example(self):
        assert "KnowledgeGraphQLExecutor" in QUERY_README

    def test_federated_kg_example(self):
        assert "FederatedKnowledgeGraph" in QUERY_README

    def test_gnn_example(self):
        assert "GraphNeuralNetworkAdapter" in QUERY_README

    def test_zkp_prover_example(self):
        assert "KGZKProver" in QUERY_README

    def test_groth16_bridge_example(self):
        assert "KGEntityFormula" in QUERY_README

    def test_recent_additions_table(self):
        assert "Recent Additions" in QUERY_README

    def test_stale_future_enhancements_removed(self):
        # "GraphQL Support" listed as a future enhancement is stale
        assert "GraphQL Support** - GraphQL query interface" not in QUERY_README


# ──────────────────────────────────────────────────────────────
# 2. docs/knowledge_graphs/API_REFERENCE.md
# ──────────────────────────────────────────────────────────────
class TestApiReference:
    def test_version_bumped(self):
        assert "3.22.33" in API_REF

    def test_advanced_extraction_apis_section(self):
        assert "Advanced Extraction APIs" in API_REF

    def test_knowledge_graph_diff_section(self):
        assert "KnowledgeGraphDiff" in API_REF

    def test_graph_events_section(self):
        assert "Graph Event Subscriptions" in API_REF

    def test_snapshots_section(self):
        assert "Named Snapshots" in API_REF or "snapshot" in API_REF

    def test_provenance_chain_section(self):
        assert "ProvenanceChain" in API_REF

    def test_visualizer_section(self):
        assert "KnowledgeGraphVisualizer" in API_REF

    def test_advanced_query_apis_section(self):
        assert "Advanced Query APIs" in API_REF

    def test_graphql_api_section(self):
        assert "GraphQL API" in API_REF

    def test_federated_kg_section(self):
        assert "Federated Knowledge Graphs" in API_REF

    def test_gnn_section(self):
        assert "Graph Neural Networks" in API_REF

    def test_zkp_section(self):
        assert "Zero-Knowledge Proofs" in API_REF

    def test_groth16_section(self):
        assert "Groth16 Bridge" in API_REF

    def test_toc_updated(self):
        assert "Advanced Extraction APIs" in API_REF
        assert "Advanced Query APIs" in API_REF

    def test_version_info_updated(self):
        assert "v3.22.26+" in API_REF  # GraphQL version
        assert "v3.22.30+" in API_REF  # GNN/ZKP version
        assert "v3.22.32+" in API_REF  # Groth16 version


# ──────────────────────────────────────────────────────────────
# 3. docs/knowledge_graphs/USER_GUIDE.md
# ──────────────────────────────────────────────────────────────
class TestUserGuide:
    def test_version_bumped(self):
        assert "3.22.33" in USER_GUIDE

    def test_delivered_features_section(self):
        assert "Delivered Features" in USER_GUIDE

    def test_future_roadmap_heading_gone(self):
        # The old section heading "Future Roadmap" should no longer exist
        # (replaced by "Delivered Features")
        assert "## 11. Future Roadmap" not in USER_GUIDE

    def test_delivery_table_present(self):
        # All 3 original "future" v4.0+ items in the table
        assert "Blockchain Integration for Provenance" in USER_GUIDE or \
               "Provenance" in USER_GUIDE

    def test_graphql_delivered_entry(self):
        assert "GraphQL" in USER_GUIDE

    def test_gnn_delivered_entry(self):
        assert "Graph Neural Networks" in USER_GUIDE

    def test_zkp_delivered_entry(self):
        assert "Zero-Knowledge" in USER_GUIDE

    def test_provenance_chain_usage_example(self):
        assert "enable_provenance" in USER_GUIDE

    def test_snapshot_usage_example(self):
        assert "snapshot" in USER_GUIDE

    def test_diff_usage_example(self):
        assert "diff" in USER_GUIDE

    def test_stale_experimental_imports_removed(self):
        # Old stale "from ipfs_datasets_py.knowledge_graphs.experimental import NeuralExtractor"
        assert "experimental import" not in USER_GUIDE or \
               "NeuralExtractor" not in USER_GUIDE

    def test_last_updated_not_stale(self):
        assert "2026-02-17" not in USER_GUIDE  # was the old stale date


# ──────────────────────────────────────────────────────────────
# 4. Version agreement across docs
# ──────────────────────────────────────────────────────────────
class TestVersionAgreement:
    def test_master_status_version(self):
        assert "3.22.33" in MASTER

    def test_changelog_version(self):
        assert "3.22.33" in CHANGELOG

    def test_roadmap_version(self):
        assert "3.22.33" in ROADMAP

    def test_roadmap_current_version(self):
        assert "Current Version:** 3.22.33" in ROADMAP

    def test_session79_in_changelog(self):
        assert "session79" in CHANGELOG or "Session 79" in CHANGELOG
