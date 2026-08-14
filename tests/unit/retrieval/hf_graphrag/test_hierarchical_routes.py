"""Unit tests for integrity-bound hierarchical routes (OUL-026).

Acceptance: routing indexes can page beyond 4,096 descriptors, builders
stream bounded partitions, route pages are integrity-bound, and legacy
US Code, patent, CVE, and SkillCenter layouts remain readable.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.hierarchical_routes import (
    HIERARCHICAL_ROUTE_SCHEMA_VERSION,
    LEGACY_LAYOUT_DOMAINS,
    MAX_DESCRIPTORS_PER_ROUTE_PAGE,
    ROUTE_PAGE_SCHEMA_VERSION,
    HierarchicalRouteIndex,
    LegacyLayoutError,
    MissingRouteKeyError,
    RouteDescriptor,
    RouteIntegrityError,
    RoutePageError,
    RouteRangeError,
    build_hierarchical_routes,
    example_legacy_layout_payload,
    hierarchical_routes,
    locate_covering_page,
    page_route_descriptors,
    read_legacy_cve_layout,
    read_legacy_patent_layout,
    read_legacy_route_layout,
    read_legacy_skillcenter_layout,
    read_legacy_uscode_layout,
    seal_streamed_route_pages,
    stream_bounded_descriptor_partitions,
    stream_route_pages,
    verify_route_page,
)
from ipfs_datasets_py.retrieval.hf_graphrag.locators import (
    KIND_CORPUS,
    LocatorRow,
    build_locator_rows_from_keys,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    COMPACT_INDEX_SCHEMA_VERSION,
    MAX_ROUTING_ROWS_PER_INDEX,
    CompactIndexRow,
    PhysicalBoundError,
    content_sha256,
    example_compact_index_payload,
)


def _descriptor(
    first: str,
    last: str,
    *,
    shard_id: int,
    kind: str = KIND_CORPUS,
    path: str | None = None,
    row_count: int = 2,
) -> dict[str, object]:
    relative = path or f"data/{kind}/part-{shard_id:06d}.parquet"
    return {
        "first_key": first,
        "kind": kind,
        "last_key": last,
        "relative_path": relative,
        "row_count": row_count,
        "schema_version": COMPACT_INDEX_SCHEMA_VERSION,
        "sha256": content_sha256(f"route-test:{relative}"),
        "shard_id": shard_id,
        "size_bytes": 128 + shard_id,
    }


def _leaf_rows(count: int, *, kind: str = KIND_CORPUS) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for shard_id in range(count):
        first = f"k-{shard_id:08d}"
        last = f"k-{shard_id:08d}-z"
        rows.append(_descriptor(first, last, shard_id=shard_id, kind=kind))
    return rows


def test_physical_route_page_bound_is_4096() -> None:
    assert MAX_DESCRIPTORS_PER_ROUTE_PAGE == 4096
    assert MAX_DESCRIPTORS_PER_ROUTE_PAGE == MAX_ROUTING_ROWS_PER_INDEX
    assert HIERARCHICAL_ROUTE_SCHEMA_VERSION == "hf-graphrag-hierarchical-route/v1"
    assert ROUTE_PAGE_SCHEMA_VERSION == "hf-graphrag-route-page/v1"


def test_page_route_descriptors_exceeds_single_index_page() -> None:
    rows = _leaf_rows(9)
    pages = page_route_descriptors(rows, max_rows_per_page=4)
    assert len(pages) == 3
    assert [len(page) for page in pages] == [4, 4, 1]
    assert all(len(page) <= 4 for page in pages)
    with pytest.raises(PhysicalBoundError, match="exceeds physical routing bound"):
        page_route_descriptors(rows, max_rows_per_page=4097)


def test_hierarchical_routes_page_beyond_4096_descriptors() -> None:
    leaf_count = MAX_DESCRIPTORS_PER_ROUTE_PAGE + 1
    rows = _leaf_rows(leaf_count)
    index = hierarchical_routes(rows, kind=KIND_CORPUS)
    assert index.leaf_count == leaf_count
    assert index.height >= 2
    assert index.page_count >= 3
    assert all(len(page) <= MAX_DESCRIPTORS_PER_ROUTE_PAGE for page in index.pages)
    assert max(len(page) for page in index.leaf_pages) == MAX_DESCRIPTORS_PER_ROUTE_PAGE
    first = index.locate("k-00000000")
    last = index.locate(f"k-{leaf_count - 1:08d}")
    assert first.leaf.shard_id == 0
    assert last.leaf.shard_id == leaf_count - 1
    assert len(first.path) == index.height
    assert index.is_legacy is False


def test_builders_stream_bounded_route_partitions() -> None:
    rows = _leaf_rows(10)
    streamed = list(
        stream_route_pages(rows, kind=KIND_CORPUS, max_rows_per_page=3)
    )
    assert [len(page) for page in streamed] == [3, 3, 3, 1]
    assert all(len(page) <= 3 for page in streamed)
    for page in streamed:
        verify_route_page(page)
    sealed = seal_streamed_route_pages(streamed, kind=KIND_CORPUS, max_rows_per_page=3)
    assert sealed.leaf_count == 10
    assert sealed.locate("k-00000007").leaf.shard_id == 7

    already = list(
        stream_bounded_descriptor_partitions(
            [RouteDescriptor.from_mapping(row) for row in rows],
            max_rows_per_page=4,
            already_sorted=True,
            kind=KIND_CORPUS,
        )
    )
    assert [len(part) for part in already] == [4, 4, 2]


def test_route_pages_are_integrity_bound() -> None:
    rows = _leaf_rows(5)
    index = build_hierarchical_routes(rows, kind=KIND_CORPUS, max_rows_per_page=2)
    assert index.height >= 2
    for page in index.pages:
        verify_route_page(page)
        assert page.sha256 == page.compute_digest()
        assert page.size_bytes == len(
            __import__("json").dumps(
                page.payload_for_digest(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        assert page.schema_version == ROUTE_PAGE_SCHEMA_VERSION
        if page is not index.root:
            assert page.parent_route_digest is not None
            assert len(page.parent_route_digest) == 64
    # Parent descriptors bind the child page digest.
    for page in index.pages:
        if page.is_leaf_page:
            continue
        for descriptor in page.descriptors:
            child = index.page_by_digest(descriptor.sha256)
            assert child.parent_route_digest == page.sha256
            assert child.first_key == descriptor.first_key
            assert child.last_key == descriptor.last_key


def test_tampered_page_digest_fails_closed() -> None:
    rows = _leaf_rows(3)
    index = build_hierarchical_routes(rows, kind=KIND_CORPUS, max_rows_per_page=2)
    page = index.leaf_pages[0]
    tampered = page.to_dict()
    tampered["sha256"] = content_sha256("tampered-route-page")
    with pytest.raises(RouteIntegrityError, match="digest mismatch"):
        HierarchicalRouteIndex.from_mapping(
            {
                "kind": KIND_CORPUS,
                "pages": [tampered, *[item.to_dict() for item in index.pages[1:]]],
                "root": index.root.to_dict(),
                "schema_version": HIERARCHICAL_ROUTE_SCHEMA_VERSION,
            }
        )


def test_lookup_walks_only_covering_path() -> None:
    rows = _leaf_rows(8)
    index = build_hierarchical_routes(rows, kind=KIND_CORPUS, max_rows_per_page=3)
    hit = index.locate("k-00000005")
    assert hit.leaf.relative_path == "data/corpus/part-000005.parquet"
    assert hit.path[0].sha256 == index.root_digest
    assert hit.path[-1].is_leaf_page
    assert all(page.contains("k-00000005") for page in hit.path)
    covering = locate_covering_page(index, "k-00000005")
    assert covering.is_leaf_page
    assert covering.contains("k-00000005")
    artifacts = index.containing_artifacts(["k-00000000", "k-00000007"])
    assert [row.shard_id for row in artifacts] == [0, 7]
    with pytest.raises(MissingRouteKeyError):
        index.locate("missing-key")
    assert index.covers("k-00000002") is True
    assert index.covers("zzz") is False


def test_overlapping_ranges_fail_closed() -> None:
    rows = [
        _descriptor("a", "m", shard_id=0),
        _descriptor("m", "z", shard_id=1),
    ]
    with pytest.raises(RouteRangeError, match="overlap"):
        build_hierarchical_routes(rows, kind=KIND_CORPUS)


def test_oversize_page_is_rejected() -> None:
    rows = _leaf_rows(5)
    with pytest.raises((RoutePageError, PhysicalBoundError)):
        build_hierarchical_routes(
            rows, kind=KIND_CORPUS, max_rows_per_page=MAX_DESCRIPTORS_PER_ROUTE_PAGE + 1
        )


def test_empty_index_is_height_one_and_misses() -> None:
    index = build_hierarchical_routes((), kind=KIND_CORPUS)
    assert index.height == 1
    assert index.leaf_count == 0
    assert index.is_legacy is True
    with pytest.raises(MissingRouteKeyError, match="empty"):
        index.locate("anything")


def test_single_page_is_legacy_compatible() -> None:
    rows = _leaf_rows(3)
    index = build_hierarchical_routes(rows, kind=KIND_CORPUS)
    assert index.is_legacy is True
    assert index.height == 1
    assert index.page_count == 1
    assert index.locate("k-00000001").leaf.shard_id == 1
    flattened = index.as_legacy_rows()
    assert len(flattened) == 3
    assert flattened[0]["first_key"] == "k-00000000"


def test_fingerprint_is_deterministic() -> None:
    rows = _leaf_rows(6)
    first = build_hierarchical_routes(reversed(rows), kind=KIND_CORPUS, max_rows_per_page=2)
    second = build_hierarchical_routes(rows, kind=KIND_CORPUS, max_rows_per_page=2)
    assert first.fingerprint() == second.fingerprint()
    assert first.to_dict() == second.to_dict()
    assert len(first.root_digest) == 64


def test_compact_index_and_locator_rows_round_trip() -> None:
    compact = CompactIndexRow.from_mapping(example_compact_index_payload())
    from_compact = RouteDescriptor.from_compact_index_row(compact)
    assert from_compact.to_compact_index_row().first_key == compact.first_key
    locators = build_locator_rows_from_keys(
        ["a", "b", "c", "d"],
        kind=KIND_CORPUS,
        data_dir="data/corpus",
        max_rows_per_shard=2,
    )
    index = build_hierarchical_routes(locators, kind=KIND_CORPUS)
    assert isinstance(locators[0], LocatorRow)
    assert index.locate("c").leaf.relative_path == "data/corpus/part-000001.parquet"


@pytest.mark.parametrize("domain", sorted(LEGACY_LAYOUT_DOMAINS - {"cve"}))
def test_legacy_single_page_layouts_remain_readable(domain: str) -> None:
    payload = example_legacy_layout_payload(domain=domain, kind=KIND_CORPUS, row_count=2)
    readers = {
        "uscode": read_legacy_uscode_layout,
        "patent": read_legacy_patent_layout,
        "cvefixes": read_legacy_cve_layout,
        "skillcenter": read_legacy_skillcenter_layout,
    }
    index = readers[domain](payload, kind=KIND_CORPUS)
    assert index.is_legacy is True
    assert index.height == 1
    assert index.leaf_count == 2
    hit = index.locate(f"{domain}-key-000000")
    assert hit.leaf.shard_id == 0
    assert index.locate(f"{domain}-key-000001-z").leaf.shard_id == 1


def test_legacy_uscode_alias_fields_are_accepted() -> None:
    digest = content_sha256("uscode-legacy-row")
    payload = {
        "schema_version": "uscode-sparse-graphrag-release-schema-v2",
        "rows": [
            {
                "cid": "bafkreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku",
                "end_document_index": 1,
                "first_key": "usc-a",
                "kind": "corpus",
                "last_key": "usc-b",
                "path": "data/corpus/part-000000.parquet",
                "row_count": 2,
                "schema_version": "hf-graphrag-bm25-shard-meta/v1",
                "sha256": digest,
                "shard_id": 0,
                "size_bytes": 64,
                "start_document_index": 0,
            }
        ],
    }
    index = read_legacy_uscode_layout(payload)
    assert index.is_legacy is True
    assert index.locate("usc-a").relative_path == "data/corpus/part-000000.parquet"
    assert index.locate("usc-b").leaf.content_cid is not None


def test_legacy_patent_term_range_aliases() -> None:
    digest = content_sha256("patent-legacy-row")
    payload = {
        "schema_version": "publicus-ir-graphrag/v1",
        "compact_index_rows": [
            {
                "first_term": "claim",
                "kind": "bm25_postings",
                "last_term": "priority",
                "relative_path": "data/bm25/postings/part-000000.parquet",
                "row_count": 2,
                "sha256": digest,
                "shard_id": 0,
                "size_bytes": 32,
            }
        ],
    }
    index = read_legacy_patent_layout(payload)
    assert index.locate("claim").leaf.shard_id == 0
    assert index.locate("priority").leaf.last_key == "priority"


def test_legacy_cve_and_skillcenter_envelopes() -> None:
    cve = {
        "schema_version": "cvefixes-hf-shard-meta/v1",
        "indexes": [
            {
                "first_key": "cve-2024-0001",
                "kind": "corpus",
                "last_key": "cve-2024-0002",
                "relative_path": "data/corpus/part-000000.parquet",
                "row_count": 2,
                "sha256": content_sha256("cve-row"),
                "shard_id": 0,
                "size_bytes": 16,
            }
        ],
    }
    skill = {
        "schema_version": "skillcenter-huggingface-release/v3",
        "index": {
            "schema_version": "skillcenter-hf-shard-meta/v1",
            "rows": [
                {
                    "first_key": "skill-a",
                    "kind": "corpus",
                    "last_key": "skill-b",
                    "relative_path": "data/corpus/part-000000.parquet",
                    "row_count": 2,
                    "sha256": content_sha256("skill-row"),
                    "shard_id": 0,
                    "size_bytes": 16,
                }
            ],
        },
    }
    cve_index = read_legacy_cve_layout(cve, kind="corpus")
    skill_index = read_legacy_skillcenter_layout(skill)
    assert cve_index.locate("cve-2024-0001").leaf.shard_id == 0
    assert skill_index.locate("skill-b").leaf.shard_id == 0


def test_legacy_raw_row_list_is_readable() -> None:
    rows = [_descriptor("aa", "mm", shard_id=0), _descriptor("nn", "zz", shard_id=1)]
    index = read_legacy_route_layout(rows, kind=KIND_CORPUS, domain="uscode")
    assert index.is_legacy is True
    assert index.locate("bb").leaf.shard_id == 0


def test_unsupported_legacy_schema_fails_closed() -> None:
    with pytest.raises(LegacyLayoutError, match="unsupported legacy layout schema"):
        read_legacy_route_layout(
            {"schema_version": "unknown-layout/v0", "rows": [_descriptor("a", "b", shard_id=0)]}
        )


def test_hierarchical_envelope_round_trips() -> None:
    index = build_hierarchical_routes(_leaf_rows(5), kind=KIND_CORPUS, max_rows_per_page=2)
    restored = read_legacy_route_layout(index.to_dict())
    assert restored.fingerprint() == index.fingerprint()
    assert restored.locate("k-00000003").leaf.shard_id == 3
