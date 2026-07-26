"""Compatibility coverage for serialized graph guided-path delegation."""

from __future__ import annotations

import numpy as np

from ipfs_datasets_py.processors.serialization.dataset_serialization import (
    GraphNode,
    VectorAugmentedGraphDataset,
)


def test_serialized_graph_guided_paths_use_canonical_semantic_traversal():
    dataset = object.__new__(VectorAugmentedGraphDataset)
    nodes = {
        "seed": GraphNode("seed", "concept", {"name": "seed"}),
        "wrong": GraphNode("wrong", "topic", {"name": "wrong"}),
        "right": GraphNode("right", "topic", {"name": "right"}),
        "dead": GraphNode("dead", "document", {"name": "dead"}),
        "goal": GraphNode("goal", "document", {"name": "goal"}),
    }
    nodes["seed"].add_edge("NEXT", nodes["wrong"], {"relevance": 1.0})
    nodes["seed"].add_edge("NEXT", nodes["right"], {"relevance": 1.0})
    nodes["wrong"].add_edge("NEXT", nodes["dead"], {"relevance": 1.0})
    nodes["right"].add_edge("NEXT", nodes["goal"], {"relevance": 1.0})
    dataset.nodes = nodes
    dataset._node_to_vector_idx = {
        node_id: index for index, node_id in enumerate(nodes)
    }

    class VectorIndex:
        _faiss_available = False
        _vectors = [
            np.asarray([0.0, 1.0], dtype=np.float32),
            np.asarray([0.0, 1.0], dtype=np.float32),
            np.asarray([0.8, 0.2], dtype=np.float32),
            np.asarray([0.0, 1.0], dtype=np.float32),
            np.asarray([1.0, 0.0], dtype=np.float32),
        ]

    dataset.vector_index = VectorIndex()

    paths = dataset._find_guided_paths(
        start_node=nodes["seed"],
        start_similarity=0.0,
        query_vector=np.asarray([1.0, 0.0], dtype=np.float32),
        target_node_types=["document"],
        guidance_properties={"relevance": 1.0},
        max_paths=4,
        max_depth=4,
    )

    assert paths[0]["end_node"].id == "goal"
    assert [node.id for node in paths[0]["path"]] == [
        "seed",
        "right",
        "goal",
    ]
    assert paths[0]["semantic_score"] == 1.0
    assert paths[0]["semantic_traversal"]["has_embedding"] is True
