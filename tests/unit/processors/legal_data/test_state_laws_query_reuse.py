"""Reuse guards for the public state-law query adapter."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data import (
    state_laws_query,
    state_laws_sparse_graphrag,
)
from ipfs_datasets_py.retrieval.hf_graphrag import query as shared_query


@pytest.mark.parametrize(
    ("adapter_name", "shared_name"),
    (
        ("cosine_similarity", "cosine_similarity"),
        ("rankings_are_compatible", "rankings_are_compatible"),
        (
            "select_entry_locator_pages_for_keys",
            "select_entry_locator_pages_for_keys",
        ),
        ("parse_entry_locator_locations", "parse_entry_locator_locations"),
        ("_late_fuse_rankings", "late_fuse_rankings"),
        ("_lexical_ranges_would_miss_keys", "lexical_ranges_would_miss_keys"),
        ("_normalize_late_fusion_settings", "normalize_late_fusion_settings"),
        (
            "_normalize_semantic_beam_settings",
            "normalize_semantic_beam_settings",
        ),
        ("_route_centroid_paths", "route_centroid_paths"),
        ("_hydrate_frontier_vectors", "hydrate_frontier_vectors"),
        ("_semantic_beam_walk", "semantic_beam_walk"),
    ),
)
def test_state_query_binds_shared_primitives_exactly(
    adapter_name: str, shared_name: str
) -> None:
    """The adapter must retain object-identity bindings to shared mechanics."""

    assert getattr(state_laws_query, adapter_name) is getattr(
        shared_query, shared_name
    )


def test_public_query_aliases_are_imports_not_state_reimplementations() -> None:
    path = Path(state_laws_query.__file__ or "")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not definitions.intersection(
        {
            "cosine_similarity",
            "rankings_are_compatible",
            "select_entry_locator_pages_for_keys",
            "parse_entry_locator_locations",
        }
    )


def test_state_adapter_delegates_frontier_and_semantic_loops() -> None:
    frontier_source = inspect.getsource(
        state_laws_query.StateLawsQueryClient.fetch_frontier_vectors
    )
    semantic_source = inspect.getsource(
        state_laws_query.StateLawsQueryClient.semantic_graph_walk
    )
    assert "_hydrate_frontier_vectors(" in frontier_source
    assert "_semantic_beam_walk(" in semantic_source
    assert "fetch_adjacency(" not in semantic_source


def test_state_ontology_callbacks_remain_in_the_adapter() -> None:
    source = inspect.getsource(
        state_laws_query.StateLawsQueryClient.semantic_graph_walk
    )
    assert "annotate_edge=annotate_edge_authority" in source
    assert "is_similarity_edge=is_similarity_edge_type" in source
    assert "is_authoritative_edge=is_legal_edge_type" in source


def test_shared_fusion_matches_state_compatibility_wrapper() -> None:
    bm25 = [{"entry_cid": "a", "normalized_score": 1.0}]
    vectors = [
        {"entry_cid": "a", "normalized_score": 0.5},
        {"entry_cid": "b", "normalized_score": 1.0},
    ]
    config = state_laws_query.FusionConfig(
        method="weighted", bm25_weight=0.6, vector_weight=0.4
    )
    adapter = state_laws_query.fuse_hybrid_results(
        bm25, vectors, config=config, top_k=2
    )
    shared = shared_query.late_fuse_rankings(
        bm25,
        vectors,
        method=config.method,
        bm25_weight=config.bm25_weight,
        vector_weight=config.vector_weight,
        rrf_k=config.rrf_k,
        stage=config.stage,
        top_k=2,
    )
    assert adapter == shared


def test_public_sparse_wrapper_resolves_state_adapter_instead_of_forking_it() -> None:
    assert (
        state_laws_sparse_graphrag.resolve_export("StateLawsQueryClient")
        is state_laws_query.StateLawsQueryClient
    )
    assert (
        state_laws_sparse_graphrag.resolve_export("FusionConfig")
        is state_laws_query.FusionConfig
    )
    assert (
        state_laws_sparse_graphrag.resolve_export("SemanticBeamConfig")
        is state_laws_query.SemanticBeamConfig
    )


def test_query_contract_paths_stay_non_authorizing() -> None:
    for module in (state_laws_query, state_laws_sparse_graphrag):
        assert module.AUTHORIZES_PUBLICATION is False
        assert module.AUTHORIZES_RELEASE is False
        assert module.AUTHORIZES_HUB_UPLOAD is False
