"""Behavior and structural reuse guards for legal graph projections."""

from __future__ import annotations

import inspect
from types import ModuleType

import pytest

from ipfs_datasets_py.processors.legal_data import (
    legal_graph_core as core,
)
from ipfs_datasets_py.processors.legal_data import (
    open_us_law_graph as open_us_law,
)
from ipfs_datasets_py.processors.legal_data import (
    state_laws_graph as state_laws,
)

ADAPTERS = (
    (
        state_laws,
        state_laws.StateLawsGraphProjection,
        state_laws.StateLawsGraphNode,
        state_laws.StateLawsGraphEdge,
    ),
    (
        open_us_law,
        open_us_law.OpenUsLawGraphProjection,
        open_us_law.OpenUsLawGraphNode,
        open_us_law.OpenUsLawGraphEdge,
    ),
)

SHARED_PROJECTION_METHODS = {
    "__post_init__": core.validate_graph_projection,
    "assert_coverage": core.assert_graph_projection_coverage,
    "assert_semantics_disjoint": core.assert_graph_projection_semantics_disjoint,
    "coverage_node_types": core.graph_projection_coverage_node_types,
    "legal_edges": core.graph_projection_legal_edges,
    "missing_coverage_node_types": core.graph_projection_missing_coverage_node_types,
    "node_by_cid": core.graph_projection_node_by_cid,
    "node_by_key": core.graph_projection_node_by_key,
    "similarity_edges": core.graph_projection_similarity_edges,
    "to_dict": core.graph_projection_to_dict,
}


@pytest.mark.parametrize(
    ("module", "projection_type", "node_type", "edge_type"),
    ADAPTERS,
    ids=("state_laws", "open_us_law"),
)
def test_projection_adapters_bind_shared_production_mechanics(
    module: ModuleType,
    projection_type: type,
    node_type: type,
    edge_type: type,
) -> None:
    del node_type, edge_type
    bindings = projection_type._projection_bindings
    assert isinstance(bindings, core.GraphProjectionBindings)
    assert bindings.record_bindings is module._GRAPH_RECORD_BINDINGS
    assert bindings.required_coverage_node_types == module.REQUIRED_COVERAGE_NODE_TYPES
    assert bindings.require_non_negative_int is module._require_non_negative_int
    assert bindings.record_bindings.projection_error_type is module.GraphProjectionError
    assert bindings.record_bindings.collision_error_type is (
        module.LegalSimilarityCollisionError
    )

    for name, implementation in SHARED_PROJECTION_METHODS.items():
        assert projection_type.__dict__[name] is implementation


@pytest.mark.parametrize(
    ("module", "projection_type", "node_type", "edge_type"),
    ADAPTERS,
    ids=("state_laws", "open_us_law"),
)
def test_projection_normalization_preserves_order_counts_and_root_cid(
    module: ModuleType,
    projection_type: type,
    node_type: type,
    edge_type: type,
) -> None:
    jurisdiction = node_type(
        node_type=module.GraphNodeType.JURISDICTION,
        node_key="jurisdiction:OR",
        label="Oregon",
    )
    code = node_type(
        node_type=module.GraphNodeType.CODE,
        node_key="code:OR:ors",
        label="Oregon Revised Statutes",
    )
    contains = edge_type(
        edge_type=module.GraphEdgeType.CONTAINS,
        source_node_cid=jurisdiction.node_cid,
        target_node_cid=code.node_cid,
        edge_class=module.DEFAULT_EDGE_CLASS[module.GraphEdgeType.CONTAINS],
    )

    projection = projection_type(
        nodes=(jurisdiction, code),
        edges=(contains,),
        skipped_row_count=2,
    )

    assert projection.nodes == tuple(
        sorted(
            (jurisdiction, code),
            key=lambda item: (item.node_type.value, item.node_key, item.node_cid),
        )
    )
    assert projection.legal_edge_count == 1
    assert projection.similarity_edge_count == 0
    assert projection.unresolved_count == 0
    assert projection.graph_cid == module.sha256_cid(
        {
            "citation_parser_version": projection.citation_parser_version,
            "edge_cids": [contains.edge_cid],
            "node_cids": [item.node_cid for item in projection.nodes],
            "ontology_version": projection.ontology_version,
            "schema_version": projection.schema_version,
            "skipped_row_count": 2,
        }
    )
    assert list(projection.to_dict()) == [
        "citation_parser_version",
        "edges",
        "graph_cid",
        "legal_edge_count",
        "nodes",
        "ontology_version",
        "schema_version",
        "similarity_edge_count",
        "skipped_row_count",
        "unresolved_count",
    ]


@pytest.mark.parametrize(
    ("module", "projection_type", "node_type", "edge_type"),
    ADAPTERS,
    ids=("state_laws", "open_us_law"),
)
def test_projection_integrity_failures_keep_dataset_exception_types_and_messages(
    module: ModuleType,
    projection_type: type,
    node_type: type,
    edge_type: type,
) -> None:
    source = node_type(
        node_type=module.GraphNodeType.JURISDICTION,
        node_key="jurisdiction:OR",
        label="Oregon",
    )
    target = node_type(
        node_type=module.GraphNodeType.CODE,
        node_key="code:OR:ors",
        label="Oregon Revised Statutes",
    )
    contains = edge_type(
        edge_type=module.GraphEdgeType.CONTAINS,
        source_node_cid=source.node_cid,
        target_node_cid=target.node_cid,
        edge_class=module.DEFAULT_EDGE_CLASS[module.GraphEdgeType.CONTAINS],
    )

    with pytest.raises(
        module.GraphProjectionError,
        match="duplicate node_cid in projection",
    ):
        projection_type(nodes=(source, source), edges=())
    with pytest.raises(
        module.GraphProjectionError,
        match=f"dangling edge {contains.edge_cid}: missing endpoint",
    ):
        projection_type(nodes=(source,), edges=(contains,))
    with pytest.raises(
        module.__dict__[f"{projection_type.__name__.removesuffix('Projection')}Error"],
        match="skipped_row_count must be >= 0",
    ):
        projection_type(nodes=(), edges=(), skipped_row_count=-1)


@pytest.mark.parametrize("module", (state_laws, open_us_law))
def test_public_disjoint_assertion_is_a_thin_dataset_error_adapter(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = inspect.getsource(module.assert_legal_similarity_disjoint)
    assert "assert_legal_similarity_disjoint_core(" in source
    assert "overlap =" not in source
    assert "for edge_type" not in source

    similarity = next(iter(module.SIMILARITY_EDGE_TYPES))
    monkeypatch.setattr(
        module,
        "LEGAL_EDGE_TYPES",
        module.LEGAL_EDGE_TYPES | {similarity},
    )
    with pytest.raises(
        module.LegalSimilarityCollisionError,
        match="legal and similarity edge types must be disjoint",
    ):
        module.assert_legal_similarity_disjoint()


# ``find_graph_paths`` and ``match_expected_paths`` intentionally remain in the
# adapters: they package sealed fixture recipes and dataset path-key aliases,
# rather than normalizing production graph artifacts.
