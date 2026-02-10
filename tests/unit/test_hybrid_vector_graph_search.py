import numpy as np

from ipfs_datasets_py.logic.integrations.graphrag_integration import HybridVectorGraphSearch


class _ToyDataset:
    def __init__(self):
        # Simple chain: A -> B -> C
        self._nodes = {
            "A": {"id": "A", "type": "entity"},
            "B": {"id": "B", "type": "entity"},
            "C": {"id": "C", "type": "entity"},
        }
        self._rels = {
            "A": [{"source": "A", "target": "B", "type": "rel", "weight": 1.0}],
            "B": [{"source": "B", "target": "C", "type": "rel", "weight": 1.0}],
            "C": [],
        }

        # Embeddings chosen so A is close to query, B is far.
        self._emb = {
            "A": np.array([1.0, 0.0], dtype=float),
            "B": np.array([0.0, 1.0], dtype=float),
            "C": np.array([0.0, 1.0], dtype=float),
        }

    def search_vectors(self, query_embedding, top_k=10, min_score=0.0):
        # Pretend vector search only returns A.
        return [{"id": "A", "score": 0.9}]

    def get_node(self, node_id):
        return self._nodes[node_id]

    def get_node_relationships(self, node_id):
        return self._rels.get(node_id, [])

    def get_node_embedding(self, node_id):
        return self._emb.get(node_id)


def test_hybrid_search_builds_multi_hop_paths():
    dataset = _ToyDataset()
    search = HybridVectorGraphSearch(dataset, max_graph_hops=2, min_score_threshold=0.0)

    query = np.array([1.0, 0.0], dtype=float)
    results = search.hybrid_search(query_embedding=query, top_k=10)

    by_id = {r["id"]: r for r in results}
    assert "B" in by_id
    assert "C" in by_id

    assert len(by_id["B"].get("path", [])) == 1
    assert len(by_id["C"].get("path", [])) == 2


def test_graph_discovered_nodes_do_not_inherit_seed_vector_score():
    dataset = _ToyDataset()
    search = HybridVectorGraphSearch(dataset, max_graph_hops=1, min_score_threshold=0.0)

    query = np.array([1.0, 0.0], dtype=float)
    results = search.hybrid_search(query_embedding=query, top_k=10)

    by_id = {r["id"]: r for r in results}
    assert "A" in by_id
    assert "B" in by_id

    # B is discovered via graph; its vector_score should be computed from its
    # own embedding (orthogonal to query => similarity ~0), not inherited (0.9).
    assert by_id["B"]["source"] == "graph"
    assert by_id["B"]["vector_score"] < 0.2
