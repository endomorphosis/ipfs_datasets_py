import numpy as np

from ipfs_datasets_py.search.graphrag_integration import HybridVectorGraphSearch, GraphRAGFactory


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


def test_hybrid_search_rescore_limit_caps_graph_vector_scoring():
    class _CountingDataset(_ToyDataset):
        def __init__(self):
            super().__init__()
            # Make a slightly larger chain: A -> B -> C -> D
            self._nodes["D"] = {"id": "D", "type": "entity"}
            self._rels["C"] = [{"source": "C", "target": "D", "type": "rel", "weight": 1.0}]
            self._rels["D"] = []
            self._emb["B"] = np.array([0.9, 0.1], dtype=float)
            self._emb["C"] = np.array([0.8, 0.2], dtype=float)
            self._emb["D"] = np.array([0.7, 0.3], dtype=float)
            self.embedding_calls = 0

        def get_node_embedding(self, node_id):
            self.embedding_calls += 1
            return super().get_node_embedding(node_id)

    dataset = _CountingDataset()
    search = HybridVectorGraphSearch(
        dataset,
        max_graph_hops=3,
        min_score_threshold=0.0,
        max_vector_rescore=1,
    )

    query = np.array([1.0, 0.0], dtype=float)
    results = search.hybrid_search(query_embedding=query, top_k=10)

    by_id = {r["id"]: r for r in results}
    assert "B" in by_id and "C" in by_id and "D" in by_id

    # Only one graph-discovered node should have its vector_score computed.
    rescored = [nid for nid in ["B", "C", "D"] if by_id[nid].get("vector_score", 0.0) > 0.0]
    assert len(rescored) == 1

    stats = search.get_last_query_stats()
    assert stats.get("vector_rescore_limit") == 1
    assert stats.get("vector_rescored") == 1


def test_factory_wires_rescore_limit_to_hybrid_search():
    class _CountingDataset(_ToyDataset):
        def __init__(self):
            super().__init__()
            # Make a slightly larger chain: A -> B -> C -> D
            self._nodes["D"] = {"id": "D", "type": "entity"}
            self._rels["C"] = [{"source": "C", "target": "D", "type": "rel", "weight": 1.0}]
            self._rels["D"] = []
            self._emb["B"] = np.array([0.9, 0.1], dtype=float)
            self._emb["C"] = np.array([0.8, 0.2], dtype=float)
            self._emb["D"] = np.array([0.7, 0.3], dtype=float)

        def get_node_embedding(self, node_id):
            return super().get_node_embedding(node_id)

    dataset = _CountingDataset()
    search = GraphRAGFactory.create_hybrid_search(
        dataset,
        max_graph_hops=3,
        min_score_threshold=0.0,
        max_vector_rescore=1,
    )

    query = np.array([1.0, 0.0], dtype=float)
    results = search.hybrid_search(query_embedding=query, top_k=10)
    by_id = {r["id"]: r for r in results}
    assert "B" in by_id and "C" in by_id and "D" in by_id

    rescored = [nid for nid in ["B", "C", "D"] if by_id[nid].get("vector_score", 0.0) > 0.0]
    assert len(rescored) == 1

    stats = search.get_last_query_stats()
    assert stats.get("vector_rescore_limit") == 1
    assert stats.get("vector_rescored") == 1


def test_max_neighbors_per_node_caps_and_tiebreaks_deterministically():
    class _FanoutDataset(_ToyDataset):
        def __init__(self):
            super().__init__()
            # Fan-out from A to multiple neighbors with a tie on weight.
            self._nodes.update(
                {
                    "D": {"id": "D", "type": "entity"},
                    "E": {"id": "E", "type": "entity"},
                }
            )
            self._rels["A"] = [
                {"source": "A", "target": "B", "type": "rel", "weight": 1.0},
                {"source": "A", "target": "C", "type": "rel", "weight": 1.0},
                {"source": "A", "target": "D", "type": "rel", "weight": 0.9},
                {"source": "A", "target": "E", "type": "rel", "weight": 0.8},
            ]
            self._rels["B"] = []
            self._rels["C"] = []
            self._rels["D"] = []
            self._rels["E"] = []

            # Provide embeddings for rescoring; values don't matter for this test.
            self._emb.update(
                {
                    "D": np.array([0.0, 1.0], dtype=float),
                    "E": np.array([0.0, 1.0], dtype=float),
                }
            )

        def search_vectors(self, query_embedding, top_k=10, min_score=0.0):
            return [{"id": "A", "score": 0.9}]

    dataset = _FanoutDataset()

    # With cap=1, only one neighbor should be expanded from A. Since B and C tie
    # on weight, deterministic tie-break picks the lower id ("B").
    search1 = GraphRAGFactory.create_hybrid_search(
        dataset,
        max_graph_hops=1,
        min_score_threshold=0.0,
        use_bidirectional_traversal=False,
        max_neighbors_per_node=1,
    )
    query = np.array([1.0, 0.0], dtype=float)
    results1 = search1.hybrid_search(query_embedding=query, top_k=10)
    ids1 = {r["id"] for r in results1}
    assert ids1 == {"A", "B"}

    # With cap=2, both tied top neighbors (B, C) are included.
    search2 = GraphRAGFactory.create_hybrid_search(
        dataset,
        max_graph_hops=1,
        min_score_threshold=0.0,
        use_bidirectional_traversal=False,
        max_neighbors_per_node=2,
    )
    results2 = search2.hybrid_search(query_embedding=query, top_k=10)
    ids2 = {r["id"] for r in results2}
    assert {"A", "B", "C"}.issubset(ids2)
    assert "D" not in ids2 and "E" not in ids2
