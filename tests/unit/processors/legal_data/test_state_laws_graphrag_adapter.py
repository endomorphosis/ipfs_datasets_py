"""Unit tests for the state-law Hub GraphRAG substrate adapter (LCR-026).

Acceptance: adapter rejects absent semantic families, fake centroid
placement, missing two-way adjacency, unsafe lineage duplication,
absolute paths, subset configs, and descriptor drift.

Hermetic: no network, no Hub upload, no tokens.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    DEFAULT_DATASET_REPO_ID,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    REQUIRED_SEMANTIC_FAMILIES,
    ArtifactFamily as StateArtifactFamily,
    content_sha256,
    example_manifest_payload,
    required_semantic_families,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graphrag_adapter import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_NETWORK,
    AUTHORIZES_PUBLICATION,
    DEFAULT_VIEWER_CONFIG,
    GOAL_ID,
    PRODUCER,
    REPORT_RELATIVE_PATH,
    REQUIRED_CENTROID_ASSIGNMENT,
    SCHEMA_VERSION,
    SUPPORTED_RELEASE_SCHEMAS,
    TASK_ID,
    AbsentSemanticFamilyError,
    AbsolutePathError,
    AdapterPinError,
    DescriptorDriftError,
    FakeCentroidPlacementError,
    MissingTwoWayAdjacencyError,
    StateLawsFilters,
    StateLawsGraphragAdapterError,
    SubsetConfigError,
    UnsafeLineageDuplicationError,
    adapt_state_release,
    assert_centroid_placement_is_real,
    assert_no_descriptor_drift,
    assert_no_home_paths_or_tokens,
    assert_no_unsafe_lineage_duplication,
    assert_not_subset_config,
    assert_relative_paths,
    assert_semantic_families_present,
    assert_two_way_adjacency,
    build_immutable_resolver,
    build_state_dual_locators,
    build_substrate_compatibility_report,
    default_writer_config,
    example_closed_adapter_payload,
    external_sort_state_family,
    family_relative_dir,
    iter_physical_shards,
    load_substrate_compatibility_report,
    map_state_family_to_shared,
    open_adapter,
    plan_bounded_shards,
    project_writer_row,
    require_relative_artifact_path,
    stream_state_family_partitions,
    to_locator_row,
    to_resolver_descriptor,
    to_shared_artifact_descriptor,
    to_shared_graph_edge,
    to_shared_graph_node,
    write_substrate_compatibility_report,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import KIND_CORPUS, KIND_VECTORS
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import MappingTransport
from ipfs_datasets_py.retrieval.hf_graphrag.schema import ArtifactFamily as SharedArtifactFamily


# tests/unit/processors/legal_data/this_file.py → repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_REPORT_PATH = _REPO_ROOT / REPORT_RELATIVE_PATH


def _digest(label: str) -> str:
    return content_sha256(label)


def _git_sha(seed: str = "adapter") -> str:
    return _digest(seed)[:40]


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "state-laws-graphrag-adapter/v1"
    assert TASK_ID == "LCR-026"
    assert GOAL_ID == "LCR-G030"
    assert PRODUCER == "state_laws_graphrag_adapter.py"
    assert DEFAULT_VIEWER_CONFIG == "state_statutes_exact_51"
    assert AUTHORIZES_HUB_UPLOAD is False
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_NETWORK is False
    adapter = open_adapter()
    assert adapter.dataset_repo_id == DEFAULT_DATASET_REPO_ID
    assert adapter.profile == RELEASE_PROFILE


def test_physical_writer_config_is_4096() -> None:
    config = default_writer_config()
    assert config.max_rows_per_shard == MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert config.max_pointers_per_row == 4096


# ---------------------------------------------------------------------------
# Family / descriptor / locator mapping
# ---------------------------------------------------------------------------


def test_state_families_map_onto_shared_vocabulary() -> None:
    assert map_state_family_to_shared("corpus") is SharedArtifactFamily.CORPUS
    assert (
        map_state_family_to_shared(StateArtifactFamily.GRAPH_ADJACENCY_IN)
        is SharedArtifactFamily.GRAPH_ADJACENCY_IN
    )
    assert (
        map_state_family_to_shared("source_receipt")
        is SharedArtifactFamily.RECEIPT
    )
    assert map_state_family_to_shared("recovery") is SharedArtifactFamily.REPORT
    directory = family_relative_dir("corpus", jurisdiction="or")
    assert directory == "data/corpus/jurisdiction=OR"
    assert family_relative_dir("vectors") == "data/vectors"
    assert "centroid-" not in family_relative_dir("bm25_postings")


def test_descriptor_maps_to_shared_and_resolver_contracts() -> None:
    digest = _digest("desc-or")
    payload = {
        "relative_path": "data/corpus/jurisdiction=OR/part-000000.parquet",
        "media_type": "application/vnd.apache.parquet",
        "sha256": digest,
        "size_bytes": 128,
        "schema_id": "state-laws-corpus-v2",
        "family": "corpus",
        "row_count": 2,
        "first_key": "aaa",
        "last_key": "zzz",
        "jurisdiction": "OR",
    }
    shared = to_shared_artifact_descriptor(payload)
    assert shared.family is SharedArtifactFamily.CORPUS
    assert shared.relative_path == payload["relative_path"]
    assert shared.metadata["jurisdiction"] == "OR"
    resolver = to_resolver_descriptor(shared)
    assert resolver.relative_path == shared.relative_path
    assert resolver.sha256 == digest
    assert resolver.size_bytes == 128


def test_locator_and_dual_cid_surface() -> None:
    first = _digest("cid-a")
    last = _digest("cid-z")
    if first > last:
        first, last = last, first
    corpus_row = to_locator_row(
        {
            "locator_id": "loc-corpus-0",
            "relative_path": "data/corpus/jurisdiction=OR/part-000000.parquet",
            "sha256": _digest("loc-corpus"),
            "family": "corpus",
            "first_key": first,
            "last_key": last,
            "row_count": 2,
            "size_bytes": 64,
        }
    )
    assert corpus_row.kind == KIND_CORPUS
    vector_row = {
        "locator_id": "loc-vector-0",
        "relative_path": "data/vectors/centroid-000-part-000000.parquet",
        "sha256": _digest("loc-vector"),
        "family": "vectors",
        "first_key": first,
        "last_key": last,
        "row_count": 2,
        "size_bytes": 64,
    }
    dual = build_state_dual_locators(
        corpus_records=[corpus_row],
        vector_records=[vector_row],
    )
    hit = dual.locate_corpus(first)
    assert hit.row.relative_path.endswith("part-000000.parquet")
    vec = dual.locate_vector(last)
    assert vec.row.kind == KIND_VECTORS


def test_filters_and_provenance_projection() -> None:
    filters = StateLawsFilters.from_mapping(
        {"jurisdiction": "or", "code_family": "ors", "section": "456"}
    )
    assert filters.jurisdiction == "OR"
    equals = filters.to_metadata_equals()
    assert equals["jurisdiction"] == "OR"
    assert equals["code_family"] == "ors"
    posting = project_writer_row(
        {"term": "statute", "entry_cids": [_digest("p1")]},
        "bm25_postings",
    )
    assert posting["term"] == "statute"


def test_graph_node_and_edge_mapping() -> None:
    node = to_shared_graph_node(
        {
            "node_cid": _digest("node-or"),
            "node_type": "jurisdiction",
            "entry_cid": _digest("entry-or"),
            "label": "Oregon",
        }
    )
    assert node.node_type == "jurisdiction"
    edge = to_shared_graph_edge(
        {
            "edge_cid": _digest("edge-contains"),
            "edge_type": "CONTAINS",
            "source_node_cid": _digest("node-or"),
            "target_node_cid": _digest("node-title"),
        }
    )
    assert edge.source_node_cid == _digest("node-or")


# ---------------------------------------------------------------------------
# Reject gates
# ---------------------------------------------------------------------------


def test_rejects_absent_semantic_families() -> None:
    present = {family.value for family in REQUIRED_SEMANTIC_FAMILIES}
    present.remove("graph_adjacency_in")
    with pytest.raises(AbsentSemanticFamilyError):
        assert_semantic_families_present({"families": present})
    closed = assert_semantic_families_present(
        {"families": required_semantic_families()}
    )
    assert closed["closed"] is True


def test_rejects_fake_centroid_placement() -> None:
    with pytest.raises(FakeCentroidPlacementError):
        assert_centroid_placement_is_real({"assignment": "hash-mod"})
    with pytest.raises(FakeCentroidPlacementError):
        assert_centroid_placement_is_real(
            {
                "assignment": REQUIRED_CENTROID_ASSIGNMENT,
                "vector_paths": ["data/vectors/part-000000.parquet"],
            }
        )
    with pytest.raises(FakeCentroidPlacementError):
        assert_centroid_placement_is_real(
            {
                "assignment": REQUIRED_CENTROID_ASSIGNMENT,
                "cluster_count": 4,
                "vector_paths": [
                    "data/vectors/centroid-000-part-000000.parquet",
                    "data/vectors/centroid-000-part-000001.parquet",
                ],
            }
        )
    with pytest.raises(FakeCentroidPlacementError):
        assert_centroid_placement_is_real(
            {
                "assignment": REQUIRED_CENTROID_ASSIGNMENT,
                "vector_row_count": MAX_ROWS_PER_VECTOR_CENTROID + 1,
                "vector_paths": ["data/vectors/centroid-000-part-000000.parquet"],
            }
        )
    assert_centroid_placement_is_real(
        {
            "assignment": REQUIRED_CENTROID_ASSIGNMENT,
            "cluster_count": 1,
            "vector_row_count": 2,
            "vector_paths": ["data/vectors/centroid-000-part-000000.parquet"],
        }
    )


def test_rejects_missing_two_way_adjacency() -> None:
    edge = _digest("edge-1")
    node_a = _digest("node-a")
    node_b = _digest("node-b")
    edges = [
        {
            "edge_cid": edge,
            "edge_type": "CONTAINS",
            "source_node_cid": node_a,
            "target_node_cid": node_b,
        }
    ]
    out_pages = [
        {
            "direction": "out",
            "edge_cids": [edge],
            "node_cid": node_a,
            "page_index": 0,
        }
    ]
    with pytest.raises(MissingTwoWayAdjacencyError):
        assert_two_way_adjacency(edges=edges, out_pages=out_pages, in_pages=[])
    with pytest.raises(MissingTwoWayAdjacencyError):
        assert_two_way_adjacency(
            families={"families": list(REQUIRED_SEMANTIC_FAMILIES - {StateArtifactFamily.GRAPH_ADJACENCY_OUT})}
        )
    receipt = assert_two_way_adjacency(
        edges=edges,
        out_pages=out_pages,
        in_pages=[
            {
                "direction": "in",
                "edge_cids": [edge],
                "node_cid": node_b,
                "page_index": 0,
            }
        ],
    )
    assert receipt["reconciled"] is True


def test_rejects_unsafe_lineage_duplication() -> None:
    with pytest.raises(UnsafeLineageDuplicationError):
        project_writer_row(
            {
                "term": "statute",
                "entry_cids": [_digest("p")],
                "official_source_url": "https://example.invalid/ors",
                "acquisition_receipt_id": "scrape-or",
                "parser_version": "state-laws-parser/v2",
            },
            "bm25_postings",
        )
    with pytest.raises(UnsafeLineageDuplicationError):
        assert_no_unsafe_lineage_duplication(
            {
                "source_lineage": [
                    {"source_cid": _digest("src")},
                    {"source_cid": _digest("src")},
                ]
            }
        )
    assert_no_unsafe_lineage_duplication(
        {
            "source_lineage": [{"source_cid": _digest("src")}],
            "postings": [{"term": "law", "entry_cids": [_digest("e")]}],
        }
    )


def test_rejects_absolute_paths() -> None:
    with pytest.raises(AbsolutePathError):
        require_relative_artifact_path("/home/operator/release/manifest.json")
    with pytest.raises(AbsolutePathError):
        require_relative_artifact_path("C:\\data\\corpus.parquet")
    with pytest.raises(AbsolutePathError):
        assert_relative_paths(
            {"relative_path": "/tmp/absolute/part-000000.parquet"}
        )
    assert (
        require_relative_artifact_path("data/corpus/jurisdiction=OR/part-000000.parquet")
        == "data/corpus/jurisdiction=OR/part-000000.parquet"
    )


def test_rejects_subset_configs() -> None:
    with pytest.raises(SubsetConfigError):
        assert_not_subset_config(
            {
                "name": "canonical_ia",
                "is_default": True,
                "split": "IA",
                "jurisdictions": ["IA"],
            }
        )
    with pytest.raises(SubsetConfigError):
        assert_not_subset_config(
            {
                "name": DEFAULT_VIEWER_CONFIG,
                "is_default": True,
                "jurisdictions": ["OR", "WA", "DC"],
            }
        )
    with pytest.raises(SubsetConfigError):
        assert_not_subset_config(
            {
                "name": "sample",
                "default": True,
                "families": ["corpus", "vectors"],
            }
        )
    ok = assert_not_subset_config(
        {
            "name": DEFAULT_VIEWER_CONFIG,
            "is_default": True,
            "jurisdictions": sorted(CANONICAL_JURISDICTIONS),
            "families": list(required_semantic_families()),
        }
    )
    assert ok["rejected_as_subset"] is False
    assert "DC" in CANONICAL_JURISDICTION_ORDER
    assert EXPECTED_JURISDICTION_COUNT == 51


def test_rejects_descriptor_drift() -> None:
    payload = b"state-laws-shard-bytes"
    digest = content_sha256(payload)
    descriptor = {
        "relative_path": "data/corpus/jurisdiction=OR/part-000000.parquet",
        "sha256": digest,
        "size_bytes": len(payload),
        "row_count": 2,
        "family": "corpus",
        "media_type": "application/vnd.apache.parquet",
        "schema_id": "state-laws-corpus-v2",
    }
    assert_no_descriptor_drift(descriptor, payload_bytes=payload, row_count=2)
    with pytest.raises(DescriptorDriftError):
        assert_no_descriptor_drift(descriptor, payload_bytes=b"tampered")
    with pytest.raises(DescriptorDriftError):
        assert_no_descriptor_drift(descriptor, row_count=99)
    with pytest.raises(DescriptorDriftError):
        assert_no_descriptor_drift(
            descriptor,
            other={
                "relative_path": descriptor["relative_path"],
                "sha256": _digest("other"),
                "size_bytes": len(payload),
            },
        )


# ---------------------------------------------------------------------------
# Bounded writers / streaming
# ---------------------------------------------------------------------------


def test_plan_bounded_shards_respects_physical_4096() -> None:
    rows = [
        {
            "entry_cid": _digest(f"row-{index}"),
            "jurisdiction": "OR",
            "legal_id": f"state:or:ors:1:{index}",
        }
        for index in range(5)
    ]
    planned = plan_bounded_shards(
        rows, family="corpus", jurisdiction="OR", max_rows=2
    )
    assert len(planned) == 3
    assert all(item.row_count <= 2 for item in planned)
    assert planned[0].relative_path.startswith("data/corpus/jurisdiction=OR/")
    assert planned[0].relative_path.endswith("part-000000.parquet")
    with pytest.raises(Exception):
        plan_bounded_shards(rows, family="corpus", jurisdiction="OR", max_rows=4097)


def test_external_sort_and_partition_stream(tmp_path: Path) -> None:
    records = [
        {
            "entry_cid": _digest("b"),
            "jurisdiction": "WA",
            "legal_id": "state:wa:rcw:1:2",
        },
        {
            "entry_cid": _digest("a"),
            "jurisdiction": "OR",
            "legal_id": "state:or:ors:1:1",
        },
        {
            "entry_cid": _digest("c"),
            "jurisdiction": "DC",
            "legal_id": "state:dc:dc_code:1:3",
        },
    ]
    output = tmp_path / "sorted.jsonl"
    receipt = external_sort_state_family(
        records,
        output,
        work_dir=tmp_path / "sort-work",
        family="corpus",
        max_records_in_memory=2,
    )
    assert receipt.interrupted is False
    lines = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    jurisdictions = [row["jurisdiction"] for row in lines]
    assert jurisdictions == sorted(jurisdictions)
    partitions = list(
        stream_state_family_partitions(
            records,
            family="corpus",
            work_dir=tmp_path / "stream-work",
            max_rows=2,
            max_records_in_memory=2,
        )
    )
    assert all(len(part) <= 2 for part in partitions)
    shards = list(iter_physical_shards(lines, max_rows=2))
    assert sum(len(part) for part in shards) == 3


# ---------------------------------------------------------------------------
# Immutable resolver (offline transport only)
# ---------------------------------------------------------------------------


def test_immutable_resolver_uses_injected_transport(tmp_path: Path) -> None:
    body = b'{"profile":"state-laws-ir-graphrag/v2"}'
    digest = content_sha256(body)
    transport = MappingTransport({"manifest.json": body})
    resolver = build_immutable_resolver(
        revision=_git_sha("resolver"),
        transport=transport,
        cache_dir=tmp_path / "cache",
    )
    assert RELEASE_PROFILE in resolver.supported_schemas
    resolved = resolver.resolve(
        "manifest.json",
        descriptor={
            "relative_path": "manifest.json",
            "sha256": digest,
            "size_bytes": len(body),
            "schema_id": RELEASE_PROFILE,
            "media_type": "application/json",
            "row_count": 0,
        },
    )
    assert resolved.sha256 == digest
    assert resolved.verified is True


def test_resolver_rejects_mutable_pin_and_live_hub(tmp_path: Path) -> None:
    with pytest.raises((AdapterPinError, StateLawsGraphragAdapterError)):
        build_immutable_resolver(
            revision="main",
            transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
        )
    with pytest.raises(StateLawsGraphragAdapterError):
        build_immutable_resolver(
            revision=_git_sha("live"),
            cache_dir=tmp_path / "cache",
        )
    with pytest.raises(StateLawsGraphragAdapterError):
        build_immutable_resolver(
            revision=_git_sha("nocache"),
            transport=MappingTransport({}),
        )


# ---------------------------------------------------------------------------
# Closed payload + compatibility report
# ---------------------------------------------------------------------------


def test_adapt_closed_payload_and_reject_each_hazard() -> None:
    receipt = adapt_state_release(example_closed_adapter_payload())
    assert set(receipt.families) >= {family.value for family in REQUIRED_SEMANTIC_FAMILIES}
    assert receipt.adjacency["reconciled"] is True
    assert receipt.filters["jurisdiction"] == "OR"

    missing = example_closed_adapter_payload()
    missing["artifacts"] = [
        item
        for item in missing["artifacts"]
        if item["family"] != "centroids"
    ]
    with pytest.raises(AbsentSemanticFamilyError):
        adapt_state_release(missing)

    fake = example_closed_adapter_payload()
    fake["assignment"] = "round-robin"
    with pytest.raises(FakeCentroidPlacementError):
        adapt_state_release(fake)

    subset = example_closed_adapter_payload()
    subset["default_config"]["jurisdictions"] = ["OR"]
    with pytest.raises(SubsetConfigError):
        adapt_state_release(subset)

    abs_payload = example_closed_adapter_payload()
    abs_payload["artifacts"][0]["relative_path"] = "/home/operator/data.parquet"
    with pytest.raises(AbsolutePathError):
        adapt_state_release(abs_payload)


def test_compatibility_report_is_hermetic_and_complete() -> None:
    write_substrate_compatibility_report(_REPORT_PATH)
    report = load_substrate_compatibility_report(_REPORT_PATH)
    dumped = json.dumps(report)
    assert "/home/" not in dumped
    assert "hf_" not in dumped.lower() or "hf_graphrag" in dumped
    assert_no_home_paths_or_tokens(report)
    assert report["task_id"] == TASK_ID
    assert report["goal_id"] == GOAL_ID
    assert report["acceptance"]["adapter_rejects_fake_centroid_placement"] is True
    assert report["acceptance"]["includes_dc"] is True
    assert report["acceptance"]["no_hub_upload"] is True
    assert report["jurisdiction_count"] == 51
    assert "DC" in report["jurisdiction_order"]
    assert RELEASE_PROFILE in report["supported_release_schemas"]
    assert report["rejections"]["subset_configs"] is True
    assert report["default_viewer_config"] == DEFAULT_VIEWER_CONFIG
    live = build_substrate_compatibility_report()
    assert live["task_id"] == TASK_ID
    assert live["known_shared_substrate_gaps"][0]["generated_defect"] is False
    assert PREVIOUS_PUBLIC_PIN == report["previous_public_pin"]
    assert all(
        not path.startswith("/")
        for path in report["shared_substrate_modules"]
    )


def test_supported_schemas_include_state_profile() -> None:
    assert RELEASE_PROFILE in SUPPORTED_RELEASE_SCHEMAS
    assert "state-laws-sparse-graphrag-release-schema-v2" in SUPPORTED_RELEASE_SCHEMAS


def test_example_manifest_is_adapter_closed() -> None:
    payload = example_manifest_payload()
    assert_semantic_families_present(payload)
    for artifact in payload["artifacts"]:
        require_relative_artifact_path(artifact["relative_path"])
