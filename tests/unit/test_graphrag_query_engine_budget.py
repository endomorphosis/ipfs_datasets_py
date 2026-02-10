import numpy as np

from ipfs_datasets_py.graphrag.integrations.graphrag_integration import (
    GraphRAGQueryEngine,
    HybridVectorGraphSearch,
)


class _DummyDataset:
    def __init__(self):
        self._nodes = {
            "A": {"id": "A", "type": "document"},
            "B": {"id": "B", "type": "document"},
            "C": {"id": "C", "type": "document"},
        }
        self._embeddings = {
            "A": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "B": np.array([0.8, 0.2, 0.0], dtype=np.float32),
            "C": np.array([0.6, 0.4, 0.0], dtype=np.float32),
        }
        self._relationships = {
            "A": [{"source": "A", "target": "B", "type": "rel", "weight": 1.0}],
            "B": [{"source": "B", "target": "C", "type": "rel", "weight": 1.0}],
            "C": [],
        }

    def search_vectors(self, query_embedding, top_k=10, min_score=0.0):
        # Always seed from A.
        return [{"id": "A", "score": 0.9}]

    def get_node(self, node_id):
        return self._nodes[node_id]

    def get_node_relationships(self, node_id):
        return list(self._relationships.get(node_id, []))

    def get_node_embedding(self, node_id):
        return self._embeddings.get(node_id)


class _DummyVectorStore:
    def search(self, embedding, top_k=10, min_score=0.0):
        return []


class _DummyBudgetOptimizer:
    def __init__(self, max_nodes=1, max_edges=0):
        self._budget = {"max_nodes": max_nodes, "max_edges": max_edges}

    def allocate_budget(self, query, context=None):
        return dict(self._budget)


def _make_engine(*, query_optimizer=None):
    dataset = _DummyDataset()
    hybrid = HybridVectorGraphSearch(
        dataset,
        vector_weight=0.6,
        graph_weight=0.4,
        max_graph_hops=2,
        min_score_threshold=0.0,
    )
    return GraphRAGQueryEngine(
        dataset=dataset,
        vector_stores={"m": _DummyVectorStore()},
        graph_store=object(),
        hybrid_search=hybrid,
        query_optimizer=query_optimizer,
        enable_cross_document_reasoning=False,
        enable_query_rewriting=False,
        enable_budget_management=query_optimizer is not None,
    )


def test_query_engine_passes_max_graph_hops_override():
    engine = _make_engine()

    query_embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    out = engine.query(
        query_text="q",
        query_embeddings={"m": query_embedding},
        include_cross_document_reasoning=False,
        min_relevance=0.0,
        relationship_types=["rel"],
        max_graph_hops=1,
    )

    assert out["hybrid_stats"]["max_hops"] == 1
    ids = {r["id"] for r in out["hybrid_results"]}
    assert "B" in ids
    assert "C" not in ids  # would require a second hop


def test_query_engine_uses_budget_caps_for_nodes_and_edges():
    engine = _make_engine(query_optimizer=_DummyBudgetOptimizer(max_nodes=1, max_edges=0))

    query_embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    out = engine.query(
        query_text="q",
        query_embeddings={"m": query_embedding},
        include_cross_document_reasoning=False,
        min_relevance=0.0,
        relationship_types=["rel"],
    )

    assert out["hybrid_stats"]["max_nodes_visited"] == 1
    assert out["hybrid_stats"]["max_edges_traversed"] == 0

    ids = {r["id"] for r in out["hybrid_results"]}
    assert ids == {"A"}
