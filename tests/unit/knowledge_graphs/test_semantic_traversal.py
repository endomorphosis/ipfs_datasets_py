"""Tests for reusable embedding-guided graph traversal."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.knowledge_graphs.query.semantic_traversal import (
    EmbeddingGuidedTraversal,
    ObjectGraphNeighborProvider,
    SemanticTraversalConfig,
    TraversalEdge,
    cosine_similarity,
)
from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import HybridSearchEngine


class DictGraphProvider:
    def __init__(self, graph):
        self.graph = graph
        self.calls = []

    def get_neighbors(
        self,
        node_id,
        *,
        direction,
        relationship_types,
        limit,
    ):
        self.calls.append((node_id, direction, tuple(relationship_types), limit))
        return [
            TraversalEdge(node_id, target, relationship_type="NEXT")
            for target in self.graph.get(node_id, ())
        ]


class DictEmbeddingProvider:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def get_embeddings(self, node_ids):
        self.calls.append(tuple(node_ids))
        return {
            node_id: self.vectors[node_id]
            for node_id in node_ids
            if node_id in self.vectors
        }


def test_semantic_beam_selects_the_branch_that_progresses_toward_query():
    graph = DictGraphProvider(
        {
            "seed": ["lexically-near", "toward-goal"],
            "lexically-near": ["dead-end"],
            "toward-goal": ["goal"],
        }
    )
    embeddings = DictEmbeddingProvider(
        {
            "seed": [0.0, 1.0],
            "lexically-near": [0.1, 0.9],
            "toward-goal": [0.8, 0.2],
            "dead-end": [0.0, 1.0],
            "goal": [1.0, 0.0],
        }
    )
    traversal = EmbeddingGuidedTraversal(
        graph,
        embeddings,
        SemanticTraversalConfig(max_depth=2, beam_width=1),
    )

    result = traversal.traverse(["seed"], [1.0, 0.0])

    assert result.hop_distances == {"seed": 0, "toward-goal": 1, "goal": 2}
    assert "lexically-near" not in result.candidates
    assert result.candidates["toward-goal"].semantic_progress > 0
    assert result.paths[0].node_ids == ("seed", "toward-goal")
    assert result.diagnostics.beam_pruned == 1


def test_embeddings_are_requested_in_batches_per_frontier_depth():
    graph = DictGraphProvider(
        {
            "seed": ["a", "b", "c"],
            "a": ["a1"],
            "b": ["b1"],
            "c": ["c1"],
        }
    )
    vectors = {
        "seed": [1.0, 0.0],
        "a": [1.0, 0.0],
        "b": [0.8, 0.2],
        "c": [0.7, 0.3],
        "a1": [1.0, 0.0],
        "b1": [0.8, 0.2],
        "c1": [0.7, 0.3],
    }
    embeddings = DictEmbeddingProvider(vectors)

    result = EmbeddingGuidedTraversal(
        graph,
        embeddings,
        SemanticTraversalConfig(max_depth=2, beam_width=3),
    ).traverse(["seed"], [1.0, 0.0])

    assert embeddings.calls == [
        ("seed",),
        ("a", "b", "c"),
        ("a1", "b1", "c1"),
    ]
    assert result.diagnostics.embedding_calls == 3
    assert result.diagnostics.embeddings_found == 7


def test_missing_embeddings_fall_back_to_relationship_score_and_mark_approximate():
    graph = DictGraphProvider({"seed": ["without-vector"]})
    embeddings = DictEmbeddingProvider({"seed": [1.0, 0.0]})

    result = EmbeddingGuidedTraversal(
        graph,
        embeddings,
        SemanticTraversalConfig(max_depth=1),
    ).traverse(["seed"], [1.0, 0.0])

    candidate = result.candidates["without-vector"]
    assert candidate.has_embedding is False
    assert candidate.semantic_proximity == 0.0
    assert candidate.relationship_score == 1.0
    assert result.approximate is True
    assert result.diagnostics.embeddings_missing == 1


def test_hard_node_edge_degree_and_backend_budgets_are_enforced():
    graph = DictGraphProvider(
        {
            "seed": ["a", "b", "c", "d"],
            "a": ["a1"],
            "b": ["b1"],
        }
    )
    embeddings = DictEmbeddingProvider(
        {
            node_id: [1.0, 0.0]
            for node_id in ("seed", "a", "b", "c", "d", "a1", "b1")
        }
    )

    result = EmbeddingGuidedTraversal(
        graph,
        embeddings,
        SemanticTraversalConfig(
            max_depth=3,
            max_nodes=3,
            max_edges=3,
            max_degree=2,
            max_backend_calls=1,
            beam_width=2,
        ),
    ).traverse(["seed"], [1.0, 0.0])

    assert len(result.candidates) <= 3
    assert result.diagnostics.edges_scanned <= 3
    assert result.diagnostics.backend_calls <= 1
    assert result.diagnostics.stop_reason in {"max_nodes", "max_backend_calls"}
    assert result.approximate is True


def test_ties_are_deterministic_regardless_of_provider_order():
    vectors = {
        "seed": [1.0, 0.0],
        "a": [0.5, 0.5],
        "b": [0.5, 0.5],
    }
    config = SemanticTraversalConfig(max_depth=1, beam_width=1)

    first = EmbeddingGuidedTraversal(
        DictGraphProvider({"seed": ["b", "a"]}),
        DictEmbeddingProvider(vectors),
        config,
    ).traverse(["seed"], [1.0, 0.0])
    second = EmbeddingGuidedTraversal(
        DictGraphProvider({"seed": ["a", "b"]}),
        DictEmbeddingProvider(vectors),
        config,
    ).traverse(["seed"], [1.0, 0.0])

    assert first.hop_distances == second.hop_distances
    assert "a" in first.hop_distances
    assert "b" not in first.hop_distances


def test_object_graph_adapter_supports_bidirectional_relationships():
    class RelationshipBackend:
        def get_relationships(self, node_id, direction="out"):
            assert direction == "both"
            return [
                {
                    "start_node": "incoming",
                    "end_node": node_id,
                    "type": "LINK",
                    "properties": {"weight": 0.75},
                },
                {
                    "start_node": node_id,
                    "end_node": "outgoing",
                    "type": "LINK",
                },
            ]

    edges = list(
        ObjectGraphNeighborProvider(RelationshipBackend()).get_neighbors(
            "center",
            direction="adaptive",
            relationship_types=("LINK",),
            limit=10,
        )
    )

    assert [edge.target_id for edge in edges] == ["incoming", "outgoing"]
    assert edges[0].weight == 0.75


def test_cosine_and_config_reject_invalid_inputs():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0
    with pytest.raises(ValueError, match="direction"):
        SemanticTraversalConfig(direction="sideways")
    with pytest.raises(ValueError, match="query_embedding"):
        EmbeddingGuidedTraversal(
            DictGraphProvider({}),
            DictEmbeddingProvider({}),
        ).traverse(["seed"], [])


def test_hybrid_search_engine_composes_semantic_traversal_without_changing_bfs_default():
    graph = DictGraphProvider(
        {
            "seed": ["wrong", "right"],
            "right": ["goal"],
            "wrong": ["dead-end"],
        }
    )
    embeddings = DictEmbeddingProvider(
        {
            "seed": [0.0, 1.0],
            "wrong": [0.0, 1.0],
            "right": [0.8, 0.2],
            "goal": [1.0, 0.0],
            "dead-end": [0.0, 1.0],
        }
    )

    class VectorStore:
        def embed_query(self, query):
            assert query == "find the goal"
            return [1.0, 0.0]

        def search(self, query_embedding, k):
            return [("seed", 0.8)]

    engine = HybridSearchEngine(
        backend=None,
        vector_store=VectorStore(),
        neighbor_provider=graph,
        embedding_provider=embeddings,
    )

    results = engine.search(
        "find the goal",
        k=10,
        max_hops=2,
        traversal_strategy="semantic-beam",
        semantic_config=SemanticTraversalConfig(max_depth=2, beam_width=1),
    )

    assert engine._last_semantic_traversal is not None
    assert engine._last_semantic_traversal.hop_distances == {
        "seed": 0,
        "right": 1,
        "goal": 2,
    }
    assert {result.node_id for result in results} == {"seed", "right", "goal"}
    right = next(result for result in results if result.node_id == "right")
    assert right.metadata["semantic_traversal"]["semantic_progress"] > 0

    # A subsequent default call still uses the established BFS implementation.
    engine.expand_graph(["seed"], max_hops=0)
    assert engine._last_semantic_traversal is None


def test_hybrid_search_cache_separates_semantic_configs_and_supplied_vectors():
    engine = HybridSearchEngine(backend=None)
    first = SemanticTraversalConfig(beam_width=1)
    second = SemanticTraversalConfig(beam_width=2)

    assert repr(first) != repr(second)
    assert engine._embedding_fingerprint([1.0, 0.0]) != (
        engine._embedding_fingerprint([0.0, 1.0])
    )


def test_hybrid_expand_graph_rejects_unknown_strategy_and_missing_query_vector():
    engine = HybridSearchEngine(backend=None)
    with pytest.raises(ValueError, match="unknown traversal_strategy"):
        engine.expand_graph(["seed"], traversal_strategy="random-walk")
    with pytest.raises(ValueError, match="query_embedding"):
        engine.expand_graph(["seed"], traversal_strategy="semantic")
