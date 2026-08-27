"""Production graph-to-HF-layout bridge tests for state laws."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_adjacency import (
    EDGE_AUTHORITY,
    EDGE_TYPE_BM25_NEIGHBOR,
    VIRTUAL_TERM_DOCUMENT_EDGE_TYPE,
    LexicalGraphConfig,
    StateLawsLexicalGraphOverlay,
    build_state_laws_lexical_graph,
    build_state_laws_lexical_graph_from_rows,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (
    fixture_bm25_config,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25_physical import (
    write_state_laws_bm25_physical_layout_from_iterable,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph import (
    LEGAL_AUTHORITY,
    GraphEdgeClass,
    GraphEdgeType,
    GraphNodeType,
    StateLawsGraphEdge,
    StateLawsGraphNode,
    StateLawsGraphProjection,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graph_physical import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    BM25_RETRIEVAL_METHOD,
    CANONICAL_GRAPH_INDEX_PATHS,
    LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY,
    PERFORMS_NETWORK_IO,
    PHYSICAL_ROW_ENCODING,
    SCHEMA_VERSION,
    STREAMING_GRAPH_WRITER_PRODUCTION_READY,
    Bm25EndpointResolutionError,
    Bm25SemanticPromotionError,
    Bm25VocabularyParityError,
    DurableTermDocumentExpansionError,
    GraphEdgeIdentityCollisionError,
    MissingCanonicalGraphIndexError,
    StateLawsStreamingGraphPhysicalWriteResult,
    adapt_state_laws_graph_projection,
    prove_bm25_vocabulary_parity,
    prove_physical_bm25_vocabulary_parity,
    write_state_laws_graph_layout,
    write_state_laws_streaming_graph_layout,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    _assert_bm25_graph_parity,
)
from ipfs_datasets_py.retrieval.hf_graphrag.graph import (
    GRAPH_ADJACENCY_SCHEMA_VERSION,
    GRAPH_EDGE_SCHEMA_VERSION,
    GRAPH_NODE_SCHEMA_VERSION,
    GraphEdge,
    GraphNode,
)
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_graph import (
    StreamingGraphConfig,
    StreamingGraphWriteResult,
)


def _cid(seed: str) -> str:
    return "sha256:" + (seed * 64)[:64]


LEGAL_A = "state:OR:ors:1:1:1.1;edition=2024-official"
LEGAL_B = "state:OR:ors:1:1:1.2;edition=2024-official"
PARENT_A = _cid("a")
PARENT_B = _cid("b")
CHUNK_A = _cid("1")
CHUNK_B = _cid("2")


class _OneShot:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.iterations = 0

    def __iter__(self) -> Iterator[object]:
        self.iterations += 1
        if self.iterations > 1:
            raise AssertionError("streaming graph source was traversed twice")
        yield from self.values


def _bm25_rows() -> list[dict[str, object]]:
    common = "public records disclosure agency statute official law access request"
    return [
        {
            "body": common + " inspection",
            "chunk_cid": CHUNK_A,
            "disposition": "admitted",
            "entry_cid": PARENT_A,
            "heading": "Public records inspection",
            "jurisdiction_code": "OR",
            "legal_id": LEGAL_A,
            "section": "1.1",
            "title": "1",
        },
        {
            "body": common + " copying",
            "chunk_cid": CHUNK_B,
            "disposition": "admitted",
            "entry_cid": PARENT_B,
            "heading": "Public records copying",
            "jurisdiction_code": "OR",
            "legal_id": LEGAL_B,
            "section": "1.2",
            "title": "1",
        },
    ]


def _overlay(*, bm25_config=None) -> StateLawsLexicalGraphOverlay:
    result = build_state_laws_lexical_graph_from_rows(
        _bm25_rows(),
        bm25_config=bm25_config,
        lexical_config=LexicalGraphConfig(
            neighbor_k=1,
            max_neighbors_per_document=1,
        ),
    )
    assert result.neighbor_edge_count == 2
    return result


def _streaming_bm25(tmp_path: Path):
    return write_state_laws_bm25_physical_layout_from_iterable(
        iter(_bm25_rows()),
        tmp_path,
        config=fixture_bm25_config(
            max_records_in_memory=2,
            max_rows_per_shard=2,
            postings_per_cell=2,
        ),
    )


def _projection(
    *,
    include_second_section: bool = True,
    legal_edge_cid: str = "",
) -> StateLawsGraphProjection:
    jurisdiction = StateLawsGraphNode(
        node_type=GraphNodeType.JURISDICTION,
        node_key="jurisdiction:OR",
        label="Oregon",
        payload={"jurisdiction_code": "OR"},
    )
    code = StateLawsGraphNode(
        node_type=GraphNodeType.CODE,
        node_key="code:OR:ors",
        label="Oregon Revised Statutes",
    )
    section_a = StateLawsGraphNode(
        node_type=GraphNodeType.SECTION,
        node_key=f"section:{LEGAL_A}",
        label="ORS 1.1",
        legal_id=LEGAL_A,
        entry_cid=PARENT_A,
    )
    section_b = StateLawsGraphNode(
        node_type=GraphNodeType.SECTION,
        node_key=f"section:{LEGAL_B}",
        label="ORS 1.2",
        legal_id=LEGAL_B,
        entry_cid=PARENT_B,
    )
    legal_edge = StateLawsGraphEdge(
        edge_type=GraphEdgeType.CONTAINS,
        source_node_cid=jurisdiction.node_cid,
        target_node_cid=code.node_cid,
        edge_class=GraphEdgeClass.STRUCTURAL,
        edge_cid=legal_edge_cid,
    )
    nodes = [jurisdiction, code, section_a]
    if include_second_section:
        nodes.append(section_b)
    return StateLawsGraphProjection(nodes=tuple(nodes), edges=(legal_edge,))


def _read_parquet_rows(paths: list[Path]) -> tuple[list[str], list[dict]]:
    pq = pytest.importorskip("pyarrow.parquet")
    columns: list[str] = []
    rows: list[dict] = []
    for path in paths:
        table = pq.read_table(path)
        if not columns:
            columns = table.column_names
        rows.extend(table.to_pylist())
    return columns, rows


def test_adaptation_preserves_identities_authority_and_bm25_parity() -> None:
    overlay = _overlay()
    projection = _projection()
    adapted = adapt_state_laws_graph_projection(projection, overlay=overlay)

    assert SCHEMA_VERSION == "state-laws-graph-physical/v1"
    assert PHYSICAL_ROW_ENCODING == "direct_parquet_columns"
    assert {node.node_cid for node in adapted.nodes} == {
        node.node_cid for node in projection.nodes
    }
    assert {edge.edge_cid for edge in adapted.edges} == {
        edge.edge_cid for edge in projection.edges
    } | {edge.edge_cid for edge in overlay.neighbor_edges}

    edges = {edge.edge_cid: edge for edge in adapted.edges}
    legal = edges[projection.edges[0].edge_cid]
    assert legal.edge_type == GraphEdgeType.CONTAINS.value
    assert legal.properties["authority"] == LEGAL_AUTHORITY
    assert legal.properties["legal_authority"] is True

    for neighbor in overlay.neighbor_edges:
        durable = edges[neighbor.edge_cid]
        assert durable.edge_type == EDGE_TYPE_BM25_NEIGHBOR
        assert durable.source_node_cid in {node.node_cid for node in projection.nodes}
        assert durable.target_node_cid in {node.node_cid for node in projection.nodes}
        assert durable.properties["authority"] == EDGE_AUTHORITY
        assert durable.properties["legal_authority"] is False
        assert durable.properties["proof_authority"] is False
        assert durable.retrieval_method == neighbor.retrieval_method

    assert VIRTUAL_TERM_DOCUMENT_EDGE_TYPE not in {
        edge.edge_type for edge in adapted.edges
    }
    proof = adapted.vocabulary_parity.to_dict()
    assert proof["bm25_vocabulary_matches_overlay_exactly"] is True
    assert proof["postings_parity_asserted"] is True
    assert proof["term_count"] == overlay.index.term_count
    assert proof["document_count"] == overlay.index.document_count
    assert proof["durable_term_document_edge_count"] == 0
    assert proof["full_term_document_expansion_performed"] is False
    assert proof["vocabulary_sha256"]
    assert adapted.report()["checks"]["bm25_neighbors_non_authoritative"] is True


def test_overlay_is_optional_and_does_not_invent_vocabulary_proof() -> None:
    projection = _projection()
    adapted = adapt_state_laws_graph_projection(projection)
    assert adapted.edge_count == len(projection.edges)
    assert adapted.overlay_neighbor_edge_cids == ()
    assert adapted.vocabulary_parity.enabled is False
    assert (
        prove_bm25_vocabulary_parity(None).to_dict()[
            "bm25_vocabulary_matches_overlay_exactly"
        ]
        is False
    )


def test_streaming_physical_bm25_proves_graph_parity_without_overlay(
    tmp_path: Path,
) -> None:
    bm25 = _streaming_bm25(tmp_path)
    proof = prove_physical_bm25_vocabulary_parity(bm25)
    fragment = bm25.to_manifest_fragment()["bm25"]
    assert proof.production_ready is True
    assert proof.evidence_source == "streaming_physical_postings"
    assert proof.index_root_cid == fragment["index_root_cid"]
    assert proof.bm25_config_digest == fragment["config_digest"]
    assert proof.vocabulary_sha256 == fragment["vocabulary_sha256"]
    assert proof.document_frequency_sha256 == fragment["document_frequency_sha256"]
    assert proof.term_document_pair_count == bm25.counts["bm25_postings"]
    assert proof.to_dict()["bm25_vocabulary_matches_physical_postings_exactly"] is True
    assert (
        proof.to_dict()["bm25_document_frequencies_match_physical_postings_exactly"]
        is True
    )

    adapted = adapt_state_laws_graph_projection(_projection(), bm25=bm25)
    assert adapted.overlay_neighbor_edge_cids == ()
    assert adapted.vocabulary_parity == proof
    assert adapted.report()["checks"]["bm25_physical_vocabulary_proof"] is True
    assert (
        adapted.report()["checks"]["optional_bm25_neighbors_production_ready"] is True
    )

    result = write_state_laws_graph_layout(_projection(), tmp_path, bm25=bm25)
    assert LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY is False
    assert result.physical.production_ready is False
    assert result.production_ready is False
    assert result.manifest_fragment()["production_ready"] is False
    assert result.manifest_fragment()["legacy_materialized"] is True


def test_streaming_state_writer_reuses_shared_writer_with_one_shot_inputs(
    tmp_path: Path,
) -> None:
    bm25 = _streaming_bm25(tmp_path)

    class CountingEvidence:
        def __init__(self) -> None:
            self.manifest_calls = 0
            self.vocabulary_replays = 0

        @property
        def production_ready(self) -> bool:
            return bm25.production_ready

        def to_manifest_fragment(self):
            self.manifest_calls += 1
            return bm25.to_manifest_fragment()

        def iter_vocabulary_document_frequencies(self):
            self.vocabulary_replays += 1
            yield from bm25.iter_vocabulary_document_frequencies()

    evidence = CountingEvidence()
    projection = _projection()
    nodes = _OneShot(list(projection.nodes))
    edges = _OneShot(list(projection.edges))
    result = write_state_laws_streaming_graph_layout(
        nodes,
        edges,
        tmp_path,
        bm25=evidence,
        config=StreamingGraphConfig(
            max_rows_per_shard=2,
            max_pointers_per_page=1,
            max_pointers_per_shard=2,
            max_records_in_memory=2,
        ),
    )

    assert nodes.iterations == 1
    assert edges.iterations == 1
    assert evidence.manifest_calls == 1
    assert evidence.vocabulary_replays == 1
    assert isinstance(result, StateLawsStreamingGraphPhysicalWriteResult)
    assert isinstance(result.physical, StreamingGraphWriteResult)
    assert result.production_ready is True
    assert STREAMING_GRAPH_WRITER_PRODUCTION_READY is True
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert PERFORMS_NETWORK_IO is False
    assert not hasattr(result, "nodes")
    assert not hasattr(result, "edges")

    fragment = result.manifest_fragment()
    graph = fragment["graph"]
    required_checks = {
        "bm25_physical_vocabulary_proof",
        "bm25_neighbors_non_authoritative",
        "direct_parquet_columns",
        "edge_identities_exact",
        "endpoint_integrity",
        "node_identities_exact",
        "optional_bm25_neighbors_production_ready",
        "term_document_edges_not_materialized",
        "two_way_adjacency_required",
    }
    assert set(graph["checks"]) == required_checks
    assert all(graph["checks"].values())
    assert graph["streaming_production_path"] is True
    assert graph["node_count"] == len(projection.nodes)
    assert graph["edge_count"] == len(projection.edges)
    assert graph["vocabulary_parity"]["evidence_source"] == (
        "streaming_physical_postings"
    )
    assert (
        graph["vocabulary_parity"]["bm25_vocabulary_matches_physical_postings_exactly"]
        is True
    )
    assert (
        graph["vocabulary_parity"][
            "bm25_document_frequencies_match_physical_postings_exactly"
        ]
        is True
    )
    assert graph["vocabulary_parity"]["durable_term_document_edge_count"] == 0
    assert "vocabulary" not in fragment["compact_proofs"]["bm25_vocabulary"]
    release_proof = _assert_bm25_graph_parity(
        bm25.to_manifest_fragment(),
        fragment,
        counts={
            "bm25_documents": bm25.counts["bm25_documents"],
            "bm25_terms": bm25.counts["bm25_terms"],
        },
    )
    assert release_proof == graph["vocabulary_parity"]
    assert set(fragment["indexes"]) == set(CANONICAL_GRAPH_INDEX_PATHS)
    assert sorted(result.key_evidence["entry_cids"]) == [PARENT_A, PARENT_B]
    assert all(
        descriptor.row_count <= 2 for descriptor in result.physical.data_descriptors
    )
    assert all(
        receipt["peak_resident_records"] <= receipt["max_records_in_memory"]
        for receipt in result.physical.sort_receipts.values()
    )
    result.verify()
    assert evidence.manifest_calls == 1
    assert evidence.vocabulary_replays == 1


def test_streaming_state_writer_accepts_shared_rows(tmp_path: Path) -> None:
    bm25 = _streaming_bm25(tmp_path)
    nodes = _OneShot(
        [
            GraphNode("shared-a", GraphNodeType.SECTION.value, entry_cid=PARENT_A),
            {
                "entry_cid": PARENT_B,
                "node_cid": "shared-b",
                "node_type": GraphNodeType.SECTION.value,
            },
        ]
    )
    edges = _OneShot(
        [
            {
                "edge_cid": "shared-edge",
                "edge_type": GraphEdgeType.CONTAINS.value,
                "properties": {
                    "authority": LEGAL_AUTHORITY,
                    "edge_class": GraphEdgeClass.STRUCTURAL.value,
                    "legal_authority": True,
                },
                "source_node_cid": "shared-a",
                "target_node_cid": "shared-b",
            }
        ]
    )
    result = write_state_laws_streaming_graph_layout(
        nodes,
        edges,
        tmp_path,
        bm25=bm25,
        config=StreamingGraphConfig(
            max_rows_per_shard=1,
            max_pointers_per_page=1,
            max_pointers_per_shard=1,
            max_records_in_memory=2,
        ),
    )

    assert result.production_ready is True
    assert result.legal_edge_count == 1
    assert result.non_authoritative_edge_count == 0
    assert nodes.iterations == 1
    assert edges.iterations == 1
    assert sorted(result.key_evidence["entry_cids"]) == [PARENT_A, PARENT_B]


def test_streaming_shared_similarity_edge_requires_non_authoritative_semantics(
    tmp_path: Path,
) -> None:
    bm25 = _streaming_bm25(tmp_path)
    nodes = [
        GraphNode("shared-a", GraphNodeType.SECTION.value, entry_cid=PARENT_A),
        GraphNode("shared-b", GraphNodeType.SECTION.value, entry_cid=PARENT_B),
    ]
    invalid = GraphEdge(
        "shared-bm25",
        GraphEdgeType.BM25_NEIGHBOR_OF.value,
        "shared-a",
        "shared-b",
        retrieval_method=BM25_RETRIEVAL_METHOD,
    )
    with pytest.raises(Bm25SemanticPromotionError, match="non-authoritative"):
        write_state_laws_streaming_graph_layout(
            iter(nodes),
            iter([invalid]),
            tmp_path,
            bm25=bm25,
            config=StreamingGraphConfig(max_records_in_memory=2),
        )


def test_physical_bm25_digest_drift_fails_closed(tmp_path: Path) -> None:
    bm25 = _streaming_bm25(tmp_path)

    class TamperedEvidence:
        production_ready = True

        def to_manifest_fragment(self):
            fragment = copy.deepcopy(bm25.to_manifest_fragment())
            fragment["bm25"]["vocabulary_sha256"] = "0" * 64
            fragment["bm25"]["physical_vocabulary_proof"]["vocabulary_sha256"] = (
                "0" * 64
            )
            return fragment

        def iter_vocabulary_document_frequencies(self):
            return bm25.iter_vocabulary_document_frequencies()

    with pytest.raises(Bm25VocabularyParityError, match="digest"):
        prove_physical_bm25_vocabulary_parity(TamperedEvidence())


def test_optional_legacy_neighbors_reconcile_to_physical_vocabulary(
    tmp_path: Path,
) -> None:
    bm25 = _streaming_bm25(tmp_path)
    overlay = _overlay(bm25_config=bm25.config)
    adapted = adapt_state_laws_graph_projection(
        _projection(),
        bm25=bm25,
        overlay=overlay,
    )
    proof = adapted.vocabulary_parity
    assert proof.index_root_cid == bm25.layout.index_root_cid
    assert proof.production_ready is True
    assert proof.optional_neighbor_edges_source == "legacy_in_memory_overlay"
    assert proof.optional_neighbor_edges_production_ready is False
    assert proof.neighbor_edge_count == overlay.neighbor_edge_count

    result = write_state_laws_graph_layout(
        _projection(),
        tmp_path,
        bm25=bm25,
        overlay=overlay,
    )
    assert result.production_ready is False
    assert result.manifest_fragment()["production_ready"] is False


def test_unmapped_bm25_endpoint_fails_instead_of_dropping_neighbor() -> None:
    with pytest.raises(Bm25EndpointResolutionError, match="does not resolve"):
        adapt_state_laws_graph_projection(
            _projection(include_second_section=False),
            overlay=_overlay(),
        )


def test_durable_term_document_expansion_is_refused() -> None:
    index = _overlay().index
    expansion_enabled = build_state_laws_lexical_graph(
        index,
        config=LexicalGraphConfig(
            materialize_neighbors=False,
            materialize_term_document_edges=True,
            allow_full_postings_expansion=True,
        ),
    )
    with pytest.raises(DurableTermDocumentExpansionError):
        adapt_state_laws_graph_projection(
            _projection(),
            overlay=expansion_enabled,
        )


def test_projection_overlay_edge_cid_collision_fails_closed() -> None:
    overlay = _overlay()
    colliding_cid = overlay.neighbor_edges[0].edge_cid
    projection = _projection(legal_edge_cid=colliding_cid)
    with pytest.raises(GraphEdgeIdentityCollisionError, match="different"):
        adapt_state_laws_graph_projection(projection, overlay=overlay)


def test_writer_refuses_an_edgeless_non_queryable_layout(tmp_path: Path) -> None:
    node = StateLawsGraphNode(
        node_type=GraphNodeType.JURISDICTION,
        node_key="jurisdiction:OR",
        label="Oregon",
    )
    projection = StateLawsGraphProjection(nodes=(node,), edges=())
    with pytest.raises(MissingCanonicalGraphIndexError, match="durable edge"):
        write_state_laws_graph_layout(projection, tmp_path)
    assert not (tmp_path / "data/graph").exists()


def test_writer_emits_direct_columns_bounded_two_way_layout_and_indexes(
    tmp_path: Path,
) -> None:
    overlay = _overlay()
    projection = _projection()
    result = write_state_laws_graph_layout(
        projection,
        tmp_path,
        overlay=overlay,
        max_rows_per_shard=2,
        max_pointers_per_page=1,
        max_pointers_per_shard=2,
    )

    fragment = result.manifest_fragment()
    assert set(fragment["indexes"]) == set(CANONICAL_GRAPH_INDEX_PATHS)
    for name, relative_path in CANONICAL_GRAPH_INDEX_PATHS.items():
        assert fragment["indexes"][name]["relative_path"] == relative_path
        assert (tmp_path / relative_path).is_file()

    node_paths = sorted((tmp_path / "data/graph/nodes").glob("*.parquet"))
    edge_paths = sorted((tmp_path / "data/graph/edges").glob("*.parquet"))
    out_paths = sorted((tmp_path / "data/graph/adjacency/out").glob("*.parquet"))
    in_paths = sorted((tmp_path / "data/graph/adjacency/in").glob("*.parquet"))
    assert node_paths and edge_paths and out_paths and in_paths

    node_columns, node_rows = _read_parquet_rows(node_paths)
    edge_columns, edge_rows = _read_parquet_rows(edge_paths)
    out_columns, out_rows = _read_parquet_rows(out_paths)
    in_columns, in_rows = _read_parquet_rows(in_paths)

    assert "record_json" not in node_columns
    assert "record_json" not in edge_columns
    assert "record_json" not in out_columns
    assert "record_json" not in in_columns
    assert set(node_columns) == {
        "entry_cid",
        "label",
        "node_cid",
        "node_type",
        "schema_version",
    }
    assert set(edge_columns) == {
        "edge_cid",
        "edge_type",
        "retrieval_method",
        "schema_version",
        "score",
        "source_node_cid",
        "target_node_cid",
    }
    assert {row["schema_version"] for row in node_rows} == {GRAPH_NODE_SCHEMA_VERSION}
    assert {row["schema_version"] for row in edge_rows} == {GRAPH_EDGE_SCHEMA_VERSION}
    assert {row["schema_version"] for row in out_rows + in_rows} == {
        GRAPH_ADJACENCY_SCHEMA_VERSION
    }

    assert {row["node_cid"] for row in node_rows} == {
        node.node_cid for node in projection.nodes
    }
    expected_edge_cids = {edge.edge_cid for edge in projection.edges} | {
        edge.edge_cid for edge in overlay.neighbor_edges
    }
    assert {row["edge_cid"] for row in edge_rows} == expected_edge_cids
    assert {
        edge_cid for row in out_rows for edge_cid in row["edge_cids"]
    } == expected_edge_cids
    assert {
        edge_cid for row in in_rows for edge_cid in row["edge_cids"]
    } == expected_edge_cids
    assert all(len(row["edge_cids"]) <= 1 for row in out_rows + in_rows)
    assert all(
        descriptor.row_count <= 2 for descriptor in result.physical.data_descriptors
    )
    assert (
        fragment["graph"]["vocabulary_parity"]["durable_term_document_edge_count"] == 0
    )
