"""
Session 76 — test suite for:
  1. GraphNeuralNetworkAdapter  (query/gnn.py)
  2. KGZKProver / KGZKVerifier  (query/zkp.py)
  3. Doc integrity: DEFERRED_FEATURES P11 §23+§24, ROADMAP v3.22.30, MASTER_STATUS

All tests are pure-Python; no external ML frameworks required.
"""

import hashlib
import math
import os

import pytest

# ── Paths ───────────────────────────────────────────────────────────────────
_KG_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "ipfs_datasets_py", "knowledge_graphs",
)


def _read(rel: str) -> str:
    with open(os.path.join(_KG_DIR, rel), encoding="utf-8") as fh:
        return fh.read()


# ── Fixture: tiny KG ────────────────────────────────────────────────────────
@pytest.fixture()
def tiny_kg():
    """Returns (kg, alice_id, bob_id, carol_id) — all IDs are strings."""
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

    kg = KnowledgeGraph("session76_test")
    alice = kg.add_entity("person", "Alice",   confidence=0.9)
    bob   = kg.add_entity("person", "Bob",     confidence=0.8)
    carol = kg.add_entity("org",    "ACME",    confidence=1.0,
                           properties={"size": "large"})
    kg.add_relationship("works_at", alice, carol)
    kg.add_relationship("knows",    alice, bob)
    return kg, alice.entity_id, bob.entity_id, carol.entity_id


# ═══════════════════════════════════════════════════════════════════════════
#  1. GNN — GNNLayerType / GNNConfig / NodeEmbedding
# ═══════════════════════════════════════════════════════════════════════════
class TestGNNLayerTypeAndConfig:
    def test_layer_type_values(self):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GNNLayerType
        assert GNNLayerType.GRAPH_CONV.value == "graph_conv"
        assert GNNLayerType.GRAPH_SAGE.value == "graph_sage"
        assert GNNLayerType.GRAPH_ATTENTION.value == "graph_attention"

    def test_gnn_config_defaults(self):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GNNConfig
        cfg = GNNConfig()
        assert cfg.embedding_dim == 64
        assert cfg.num_layers == 2
        assert cfg.normalize is True
        assert cfg.activation == "relu"

    def test_gnn_config_custom(self):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GNNConfig, GNNLayerType
        cfg = GNNConfig(embedding_dim=32, num_layers=3,
                        layer_type=GNNLayerType.GRAPH_CONV, normalize=False)
        assert cfg.embedding_dim == 32
        assert cfg.num_layers == 3
        assert cfg.normalize is False

    def test_node_embedding_dim(self):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import NodeEmbedding
        emb = NodeEmbedding(entity_id="e1", features=[0.1, 0.2, 0.3], layer=1)
        assert emb.dim == 3


# ═══════════════════════════════════════════════════════════════════════════
#  2. GNN — Feature extraction
# ═══════════════════════════════════════════════════════════════════════════
class TestGNNFeatureExtraction:
    def test_feature_keys_match_entities(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        features = adapter.extract_node_features()
        assert set(features.keys()) == set(kg.entities.keys())

    def test_feature_vector_length_consistent(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        features = adapter.extract_node_features()
        lengths = [len(v) for v in features.values()]
        assert len(set(lengths)) == 1  # all same length

    def test_empty_graph_returns_empty(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg = KnowledgeGraph("empty")
        adapter = GraphNeuralNetworkAdapter(kg)
        assert adapter.extract_node_features() == {}

    def test_confidence_in_features(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        features = adapter.extract_node_features()
        alice_feat = features[alice_id]
        assert any(abs(f - 0.9) < 1e-9 for f in alice_feat)


# ═══════════════════════════════════════════════════════════════════════════
#  3. GNN — Message passing
# ═══════════════════════════════════════════════════════════════════════════
class TestGNNMessagePassing:
    def test_output_keys_same_as_input(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        raw = adapter.extract_node_features()
        out = adapter.message_passing(raw, num_iterations=1)
        assert set(out.keys()) == set(raw.keys())

    def test_zero_iterations_still_returns_features(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        raw = adapter.extract_node_features()
        out = adapter.message_passing(raw, num_iterations=0)
        assert set(out.keys()) == set(raw.keys())

    def test_graph_sage_layer(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import (
            GraphNeuralNetworkAdapter, GNNConfig, GNNLayerType,
        )
        kg, alice_id, bob_id, carol_id = tiny_kg
        cfg = GNNConfig(layer_type=GNNLayerType.GRAPH_SAGE, num_layers=1, normalize=False)
        adapter = GraphNeuralNetworkAdapter(kg, cfg)
        raw = adapter.extract_node_features()
        out = adapter.message_passing(raw, num_iterations=1)
        assert len(out) == len(raw)

    def test_graph_conv_layer(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import (
            GraphNeuralNetworkAdapter, GNNConfig, GNNLayerType,
        )
        kg, alice_id, bob_id, carol_id = tiny_kg
        cfg = GNNConfig(layer_type=GNNLayerType.GRAPH_CONV, num_layers=1, normalize=False)
        adapter = GraphNeuralNetworkAdapter(kg, cfg)
        raw = adapter.extract_node_features()
        out = adapter.message_passing(raw, num_iterations=1)
        assert len(out) == len(raw)

    def test_attention_layer(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import (
            GraphNeuralNetworkAdapter, GNNConfig, GNNLayerType,
        )
        kg, alice_id, bob_id, carol_id = tiny_kg
        cfg = GNNConfig(layer_type=GNNLayerType.GRAPH_ATTENTION, num_layers=1, normalize=False)
        adapter = GraphNeuralNetworkAdapter(kg, cfg)
        raw = adapter.extract_node_features()
        out = adapter.message_passing(raw, num_iterations=1)
        assert len(out) == len(raw)


# ═══════════════════════════════════════════════════════════════════════════
#  4. GNN — Embeddings + similarity
# ═══════════════════════════════════════════════════════════════════════════
class TestGNNEmbeddingsAndSimilarity:
    def test_compute_embeddings_returns_node_embeddings(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import (
            GraphNeuralNetworkAdapter, NodeEmbedding,
        )
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        embs = adapter.compute_embeddings()
        assert all(isinstance(v, NodeEmbedding) for v in embs.values())

    def test_embeddings_cached(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        embs1 = adapter.compute_embeddings()
        embs2 = adapter.compute_embeddings()
        assert embs1 is embs2  # same object → cached

    def test_embeddings_normalized_unit_length(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter, GNNConfig
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg, GNNConfig(normalize=True))
        embs = adapter.compute_embeddings(force_recompute=True)
        for emb in embs.values():
            norm = math.sqrt(sum(x * x for x in emb.features))
            assert abs(norm - 1.0) < 0.01 or norm < 1e-9

    def test_link_prediction_self_score_max(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        score = adapter.link_prediction_score(alice_id, alice_id)
        assert abs(score - 1.0) < 0.01

    def test_link_prediction_unknown_entity_zero(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        score = adapter.link_prediction_score("nonexistent", alice_id)
        assert score == 0.0

    def test_find_similar_entities_count(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        similar = adapter.find_similar_entities(alice_id, top_k=2)
        assert len(similar) <= 2
        assert all(isinstance(s, tuple) and len(s) == 2 for s in similar)

    def test_find_similar_entities_sorted_descending(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        similar = adapter.find_similar_entities(alice_id, top_k=10)
        scores = [s for _, s in similar]
        assert scores == sorted(scores, reverse=True)

    def test_find_similar_entities_excludes_self(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        similar = adapter.find_similar_entities(alice_id, top_k=10)
        ids = [eid for eid, _ in similar]
        assert alice_id not in ids


# ═══════════════════════════════════════════════════════════════════════════
#  5. GNN — Export helpers
# ═══════════════════════════════════════════════════════════════════════════
class TestGNNExportHelpers:
    def test_adjacency_dict_keys_are_entity_ids(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        adj = adapter.to_adjacency_dict()
        assert set(adj.keys()) == set(kg.entities.keys())

    def test_adjacency_follows_relationship_direction(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        adj = adapter.to_adjacency_dict()
        # alice → carol (works_at) and alice → bob (knows)
        assert carol_id in adj[alice_id] or bob_id in adj[alice_id]

    def test_export_node_features_array_shape(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.gnn import GraphNeuralNetworkAdapter
        kg, alice_id, bob_id, carol_id = tiny_kg
        adapter = GraphNeuralNetworkAdapter(kg)
        ids, matrix = adapter.export_node_features_array()
        assert len(ids) == len(kg.entities)
        assert len(matrix) == len(ids)
        assert len(set(len(row) for row in matrix)) == 1  # uniform width


# ═══════════════════════════════════════════════════════════════════════════
#  6. ZKP — KGProofType / KGProofStatement
# ═══════════════════════════════════════════════════════════════════════════
class TestKGProofTypeAndStatement:
    def test_proof_type_values(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGProofType
        assert KGProofType.ENTITY_EXISTS.value == "entity_exists"
        assert KGProofType.ENTITY_PROPERTY.value == "entity_property"
        assert KGProofType.PATH_EXISTS.value == "path_exists"
        assert KGProofType.QUERY_ANSWER_COUNT.value == "query_answer_count"

    def test_proof_statement_to_from_dict(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGProofStatement
        kg, alice_id, bob_id, carol_id = tiny_kg
        prover = KGZKProver(kg)
        stmt = prover.prove_entity_exists("person", "Alice")
        assert stmt is not None
        d = stmt.to_dict()
        restored = KGProofStatement.from_dict(d)
        assert restored.commitment == stmt.commitment
        assert restored.nullifier == stmt.nullifier
        assert restored.proof_type == stmt.proof_type


# ═══════════════════════════════════════════════════════════════════════════
#  7. ZKP — KGZKProver
# ═══════════════════════════════════════════════════════════════════════════
class TestKGZKProver:
    def test_prove_entity_exists_success(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_entity_exists("person", "Alice")
        assert stmt is not None
        assert stmt.commitment.startswith("zk_commit_")
        assert stmt.nullifier.startswith("zk_null_")

    def test_prove_entity_exists_none_for_unknown(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_entity_exists("person", "Charlie")
        assert stmt is None

    def test_prove_entity_exists_does_not_reveal_id(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_entity_exists("person", "Alice")
        assert alice_id not in stmt.commitment
        assert alice_id not in stmt.nullifier

    def test_prove_entity_property_success(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice_id, bob_id, carol_id = tiny_kg
        value_hash = hashlib.sha256("large".encode()).hexdigest()
        stmt = KGZKProver(kg).prove_entity_property(carol_id, "size", value_hash)
        assert stmt is not None

    def test_prove_entity_property_wrong_hash(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_entity_property(carol_id, "size", "wrong_hash")
        assert stmt is None

    def test_prove_path_exists_success(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_path_exists("person", "org", max_hops=2)
        assert stmt is not None
        assert stmt.public_inputs["start_type"] == "person"
        assert stmt.public_inputs["end_type"] == "org"

    def test_prove_path_exists_none_when_unreachable(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_path_exists("org", "person", max_hops=1)
        assert stmt is None  # no reverse edges

    def test_prove_query_answer_count_success(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_query_answer_count(2, "entity")
        assert stmt is not None

    def test_prove_query_answer_count_fails_when_too_few(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_query_answer_count(100, "entity")
        assert stmt is None


# ═══════════════════════════════════════════════════════════════════════════
#  8. ZKP — KGZKVerifier
# ═══════════════════════════════════════════════════════════════════════════
class TestKGZKVerifier:
    def test_valid_statement_passes(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_entity_exists("person", "Alice")
        assert KGZKVerifier().verify_statement(stmt)

    def test_none_statement_fails(self):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKVerifier
        assert KGZKVerifier().verify_statement(None) is False

    def test_replay_protection(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
        kg, alice_id, bob_id, carol_id = tiny_kg
        stmt = KGZKProver(kg).prove_entity_exists("person", "Alice")
        verifier = KGZKVerifier()
        assert verifier.verify_statement(stmt) is True
        assert verifier.verify_statement(stmt) is False  # replay

    def test_verify_batch(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
        kg, alice_id, bob_id, carol_id = tiny_kg
        prover = KGZKProver(kg)
        stmts = [
            prover.prove_entity_exists("person", "Alice"),
            prover.prove_entity_exists("person", "Bob"),
            None,
        ]
        results = KGZKVerifier().verify_batch(stmts)
        assert results[0] is True
        assert results[1] is True
        assert results[2] is False

    def test_batch_prove(self, tiny_kg):
        from ipfs_datasets_py.knowledge_graphs.query.zkp import KGZKProver, KGZKVerifier
        kg, alice_id, bob_id, carol_id = tiny_kg
        prover = KGZKProver(kg)
        requests = [
            {"type": "entity_exists", "entity_type": "person", "name": "Alice"},
            {"type": "query_answer_count", "min_count": 1, "query_type": "entity"},
            {"type": "entity_exists", "entity_type": "person", "name": "Unknown"},
        ]
        results = prover.batch_prove(requests)
        assert results[0] is not None
        assert results[1] is not None
        assert results[2] is None


# ═══════════════════════════════════════════════════════════════════════════
#  9. Module exports
# ═══════════════════════════════════════════════════════════════════════════
class TestQueryModuleExports:
    def test_gnn_symbols_importable(self):
        from ipfs_datasets_py.knowledge_graphs.query import (
            GraphNeuralNetworkAdapter, GNNConfig, GNNLayerType, NodeEmbedding,
        )

    def test_zkp_symbols_importable(self):
        from ipfs_datasets_py.knowledge_graphs.query import (
            KGZKProver, KGZKVerifier, KGProofStatement, KGProofType,
        )

    def test_gnn_symbols_in_all(self):
        import importlib
        qmod = importlib.import_module("ipfs_datasets_py.knowledge_graphs.query")
        for sym in ("GraphNeuralNetworkAdapter", "GNNConfig", "GNNLayerType", "NodeEmbedding"):
            assert sym in qmod.__all__, f"{sym!r} missing from __all__"

    def test_zkp_symbols_in_all(self):
        import importlib
        qmod = importlib.import_module("ipfs_datasets_py.knowledge_graphs.query")
        for sym in ("KGZKProver", "KGZKVerifier", "KGProofStatement", "KGProofType"):
            assert sym in qmod.__all__, f"{sym!r} missing from __all__"


# ═══════════════════════════════════════════════════════════════════════════
#  10. Doc integrity
# ═══════════════════════════════════════════════════════════════════════════
class TestDocIntegritySession76:
    def test_deferred_features_has_p11(self):
        text = _read("DEFERRED_FEATURES.md")
        assert "P11" in text

    def test_deferred_features_has_gnn_section(self):
        text = _read("DEFERRED_FEATURES.md")
        assert "§23" in text or "Graph Neural Networks" in text

    def test_deferred_features_has_zkp_section(self):
        text = _read("DEFERRED_FEATURES.md")
        assert "§24" in text or "Zero-Knowledge" in text

    def test_roadmap_gnn_delivered(self):
        text = _read("ROADMAP.md")
        assert "Graph neural networks integration" in text
        assert "Delivered" in text

    def test_roadmap_zkp_delivered(self):
        text = _read("ROADMAP.md")
        assert "Zero-knowledge proof support" in text
        assert "✅" in text

    def test_roadmap_v3_22_30_row(self):
        text = _read("ROADMAP.md")
        assert "3.22.30" in text

    def test_master_status_v3_22_30(self):
        text = _read("MASTER_STATUS.md")
        assert "3.22.30" in text

    def test_changelog_v3_22_30(self):
        text = _read("CHANGELOG_KNOWLEDGE_GRAPHS.md")
        assert "3.22.30" in text


# ═══════════════════════════════════════════════════════════════════════════
#  11. Version agreement
# ═══════════════════════════════════════════════════════════════════════════
class TestVersionAgreement:
    def _top_version(self, rel: str) -> str:
        with open(os.path.join(_KG_DIR, rel), encoding="utf-8") as fh:
            for line in fh:
                for part in line.split():
                    if part.startswith("3.22."):
                        return part.rstrip(".")
        return ""

    def test_master_status_version(self):
        v = self._top_version("MASTER_STATUS.md")
        assert v == "3.22.30", f"Expected 3.22.30, got {v!r}"

    def test_changelog_version(self):
        text = _read("CHANGELOG_KNOWLEDGE_GRAPHS.md")
        assert "3.22.30" in text

    def test_roadmap_current_version(self):
        text = _read("ROADMAP.md")
        assert "3.22.30" in text

