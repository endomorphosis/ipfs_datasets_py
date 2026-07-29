"""KGP-004: Immutable graph revision manifest contract tests.

Validates bounded, versioned, canonical graph and shard descriptors with
parent, schema/ontology, graph kind, counts, partitions, indexes, provenance,
checksums, codecs, storage profile, and optional root CID.

Rejection matrix: ambiguous IDs, unsafe paths, noncanonical values, unknown
required fields, invalid counts, and checksum/CID mismatch.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from typing import Any, Dict

import pytest

from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    CODECS,
    MANIFEST_SCHEMA_VERSION,
    STORAGE_PROFILES,
    ContentChecksum,
    GraphCounts,
    GraphRevisionManifest,
    IndexDescriptor,
    ManifestIntegrityError,
    ManifestValidationError,
    PartitionDescriptor,
    ProvenanceDescriptor,
    ShardDescriptor,
    build_graph_revision_manifest,
    canonical_json_bytes,
    cid_v1_from_sha256_hex,
    sha256_hex,
)


def _ck(data: bytes = b"partition-payload") -> ContentChecksum:
    return ContentChecksum.of_bytes(data)


def _partition(
    partition_id: str = "part-nodes",
    *,
    kind: str = "nodes",
    path: str = "partitions/nodes.parquet",
    row_count: int = 10,
    payload: bytes = b"nodes-v1",
) -> PartitionDescriptor:
    checksum = _ck(payload)
    return PartitionDescriptor(
        partition_id=partition_id,
        kind=kind,
        path=path,
        codec="parquet",
        checksum=checksum,
        row_count=row_count,
        size_bytes=len(payload),
        cid=checksum.as_cid(),
        schema_version="1",
    )


def _index(
    index_id: str = "idx-entity-type",
    *,
    fields: tuple[str, ...] = ("entity_type",),
    payload: bytes = b"index-v1",
) -> IndexDescriptor:
    checksum = _ck(payload)
    return IndexDescriptor(
        index_id=index_id,
        kind="type",
        path="indexes/entity_type.bloom",
        codec="bloom-v1",
        checksum=checksum,
        fields=fields,
        size_bytes=len(payload),
        cid=checksum.as_cid(),
    )


def _shard(
    shard_id: str = "shard-000",
    *,
    partition_ids: tuple[str, ...] = ("part-nodes",),
    payload: bytes = b"shard-car-v1",
    path: str = "shards/000.car",
) -> ShardDescriptor:
    checksum = _ck(payload)
    return ShardDescriptor(
        shard_id=shard_id,
        codec="car",
        checksum=checksum,
        size_bytes=len(payload),
        path=path,
        cid=checksum.as_cid(),
        partition_ids=partition_ids,
        row_count=10,
    )


def _provenance(**overrides: Any) -> ProvenanceDescriptor:
    base = dict(
        producer_id="producer:kg-publisher",
        producer_version="1.0.0",
        source="test-fixture",
        created_at="2026-07-29T12:00:00Z",
        repository_revision="commit:abc123",
        extra={"pipeline": "unit"},
    )
    base.update(overrides)
    return ProvenanceDescriptor(**base)


def _manifest(**overrides: Any) -> GraphRevisionManifest:
    partitions = overrides.pop(
        "partitions",
        (
            _partition("part-edges", kind="edges", path="partitions/edges.parquet", row_count=20, payload=b"edges"),
            _partition("part-nodes", kind="nodes", path="partitions/nodes.parquet", row_count=10, payload=b"nodes"),
        ),
    )
    # Ensure partition list is sorted by id for canonical construction helpers.
    partitions = tuple(sorted(partitions, key=lambda p: p.partition_id))
    indexes = overrides.pop(
        "indexes",
        (_index(),),
    )
    indexes = tuple(sorted(indexes, key=lambda i: i.index_id))
    shards = overrides.pop(
        "shards",
        (
            _shard(
                partition_ids=tuple(sorted(p.partition_id for p in partitions)),
            ),
        ),
    )
    shards = tuple(sorted(shards, key=lambda s: s.shard_id))
    counts = overrides.pop(
        "counts",
        GraphCounts(node_count=10, edge_count=20, document_count=0),
    )
    kwargs: Dict[str, Any] = dict(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-0001",
        parent_revision=None,
        schema_id="kg.entity-relationship",
        schema_version="1",
        ontology_id="ontology:skills",
        ontology_version="2026.07",
        graph_kind="platform-graph",
        storage_profile="hybrid",
        codec="dag-cbor",
        counts=counts,
        partitions=partitions,
        indexes=indexes,
        shards=shards,
        provenance=_provenance(),
        include_root_cid=True,
    )
    kwargs.update(overrides)
    return build_graph_revision_manifest(**kwargs)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_manifest_schema_version_and_profiles() -> None:
    assert MANIFEST_SCHEMA_VERSION == "kg-revision-manifest/v1"
    assert STORAGE_PROFILES == frozenset({"parquet", "ipfs_ipld", "ipfs_kit", "hybrid"})
    assert "parquet" in CODECS
    assert "dag-cbor" in CODECS
    assert "car" in CODECS


def test_build_manifest_is_immutable_and_round_trips() -> None:
    manifest = _manifest(parent_revision="rev-0000")
    assert manifest.manifest_version == MANIFEST_SCHEMA_VERSION
    assert manifest.parent_revision == "rev-0000"
    assert manifest.graph_kind == "platform-graph"
    assert manifest.storage_profile == "hybrid"
    assert manifest.codec == "dag-cbor"
    assert manifest.counts.node_count == 10
    assert manifest.counts.edge_count == 20
    assert len(manifest.partitions) == 2
    assert len(manifest.indexes) == 1
    assert len(manifest.shards) == 1
    assert manifest.root_cid is not None
    assert manifest.root_cid.startswith("b")
    assert manifest.checksum.algorithm == "sha256"
    assert len(manifest.checksum.hex_digest) == 64

    # Deterministic identity.
    again = _manifest(parent_revision="rev-0000")
    assert again.checksum.hex_digest == manifest.checksum.hex_digest
    assert again.root_cid == manifest.root_cid
    assert again.to_json() == manifest.to_json()

    # JSON round-trip.
    restored = GraphRevisionManifest.from_json(manifest.to_json())
    assert restored == manifest
    assert restored.to_dict() == manifest.to_dict()

    # Dict round-trip with explicit key set.
    restored_dict = GraphRevisionManifest.from_dict(manifest.to_dict())
    assert restored_dict == manifest

    with pytest.raises(FrozenInstanceError):
        manifest.revision_id = "mutated"  # type: ignore[misc]


def test_canonical_json_is_key_sorted_and_compact() -> None:
    manifest = _manifest()
    encoded = manifest.to_json()
    # Compact separators, sorted keys at top level.
    assert " " not in encoded or all(c in encoded for c in encoded)  # smoke
    assert encoded == json.dumps(
        json.loads(encoded),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    # Reordering partitions input is normalized via build only if already sorted;
    # identity bytes equal for equal content.
    assert canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_build_classmethod_matches_function() -> None:
    via_fn = _manifest(revision_id="rev-class")
    via_cls = GraphRevisionManifest.build(
        tenant="acme",
        graph_id="skills",
        revision_id="rev-class",
        schema_id="kg.entity-relationship",
        schema_version="1",
        ontology_id="ontology:skills",
        ontology_version="2026.07",
        graph_kind="platform-graph",
        storage_profile="hybrid",
        codec="dag-cbor",
        counts=GraphCounts(node_count=10, edge_count=20),
        partitions=(
            _partition("part-edges", kind="edges", path="partitions/edges.parquet", row_count=20, payload=b"edges"),
            _partition("part-nodes", kind="nodes", path="partitions/nodes.parquet", row_count=10, payload=b"nodes"),
        ),
        indexes=(_index(),),
        shards=(
            _shard(partition_ids=("part-edges", "part-nodes")),
        ),
        provenance=_provenance(),
    )
    assert via_fn.checksum == via_cls.checksum
    assert via_fn.root_cid == via_cls.root_cid


def test_optional_root_cid_can_be_omitted() -> None:
    manifest = _manifest(include_root_cid=False)
    assert manifest.root_cid is None
    assert manifest.checksum.hex_digest
    # Still round-trips with explicit null root_cid.
    restored = GraphRevisionManifest.from_dict(manifest.to_dict())
    assert restored.root_cid is None
    assert restored.checksum == manifest.checksum


def test_descriptor_fields_cover_acceptance_surface() -> None:
    manifest = _manifest(parent_revision="rev-parent")
    payload = manifest.to_dict()
    for key in (
        "manifest_version",
        "tenant",
        "graph_id",
        "revision_id",
        "parent_revision",
        "schema_id",
        "schema_version",
        "ontology_id",
        "ontology_version",
        "graph_kind",
        "storage_profile",
        "codec",
        "counts",
        "partitions",
        "indexes",
        "shards",
        "provenance",
        "checksum",
        "root_cid",
    ):
        assert key in payload
    assert payload["parent_revision"] == "rev-parent"
    assert payload["counts"]["node_count"] == 10
    assert payload["partitions"][0]["checksum"]["algorithm"] == "sha256"
    assert payload["indexes"][0]["fields"] == ["entity_type"]
    assert payload["shards"][0]["codec"] == "car"
    assert payload["provenance"]["producer_id"] == "producer:kg-publisher"


# ---------------------------------------------------------------------------
# Ambiguous IDs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant", ""),
        ("tenant", "ACME"),
        ("tenant", "has space"),
        ("graph_id", "Bad_ID"),
        ("graph_id", "../escape"),
        ("revision_id", ""),
        ("revision_id", " bad"),
        ("revision_id", "//double"),
        ("graph_kind", "Not_Slug"),
        ("schema_id", ""),
        ("ontology_id", " has-space"),
    ],
)
def test_rejects_ambiguous_ids(field: str, value: str) -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        _manifest(**{field: value})
    assert excinfo.value.code == "AMBIGUOUS_ID"


def test_rejects_parent_equal_revision() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        _manifest(revision_id="rev-same", parent_revision="rev-same")
    assert excinfo.value.code == "AMBIGUOUS_ID"


def test_rejects_duplicate_partition_ids() -> None:
    p = _partition("dup")
    with pytest.raises(ManifestValidationError) as excinfo:
        _manifest(
            partitions=(p, p),
            counts=GraphCounts(node_count=10, edge_count=0),
            shards=(),
        )
    assert excinfo.value.code == "AMBIGUOUS_ID"


def test_rejects_shard_unknown_partition_ref() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        _manifest(
            partitions=(_partition("part-nodes"),),
            counts=GraphCounts(node_count=10, edge_count=0),
            shards=(_shard(partition_ids=("missing-part",)),),
        )
    assert excinfo.value.code == "AMBIGUOUS_ID"


def test_rejects_shard_without_path_or_cid() -> None:
    checksum = _ck(b"x")
    with pytest.raises(ManifestValidationError) as excinfo:
        ShardDescriptor(
            shard_id="s1",
            codec="car",
            checksum=checksum,
            size_bytes=1,
            path=None,
            cid=None,
        )
    assert excinfo.value.code == "AMBIGUOUS_ID"


# ---------------------------------------------------------------------------
# Unsafe paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/nodes.parquet",
        "../escape.parquet",
        "foo/../bar.parquet",
        "foo//bar.parquet",
        "./relative.parquet",
        "windows\\path.parquet",
        "~/home.parquet",
        "",
    ],
)
def test_rejects_unsafe_partition_paths(path: str) -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        _partition(path=path)
    assert excinfo.value.code in {"UNSAFE_PATH", "AMBIGUOUS_ID", "NONCANONICAL_VALUE"}


def test_rejects_unsafe_index_and_shard_paths() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        _index()
        IndexDescriptor(
            index_id="i1",
            kind="btree",
            path="/etc/passwd",
            codec="btree-v1",
            checksum=_ck(b"i"),
            fields=("a",),
            size_bytes=1,
        )
    assert excinfo.value.code == "UNSAFE_PATH"

    with pytest.raises(ManifestValidationError) as excinfo:
        ShardDescriptor(
            shard_id="s1",
            codec="car",
            checksum=_ck(b"s"),
            size_bytes=1,
            path="../../secret.car",
        )
    assert excinfo.value.code == "UNSAFE_PATH"


# ---------------------------------------------------------------------------
# Noncanonical values
# ---------------------------------------------------------------------------


def test_rejects_unknown_storage_profile() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        _manifest(storage_profile="mongo")
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_unknown_codec() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        _manifest(codec="protobuf")
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_unknown_partition_kind() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        PartitionDescriptor(
            partition_id="p1",
            kind="mystery",
            path="p.parquet",
            codec="parquet",
            checksum=_ck(b"p"),
            row_count=1,
            size_bytes=1,
        )
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_unsorted_index_fields() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        IndexDescriptor(
            index_id="i1",
            kind="composite",
            path="indexes/comp.btree",
            codec="btree-v1",
            checksum=_ck(b"i"),
            fields=("z_field", "a_field"),
            size_bytes=1,
        )
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_unsorted_partitions() -> None:
    parts = (
        _partition("z-part", kind="nodes", row_count=10, payload=b"z"),
        _partition("a-part", kind="edges", path="partitions/edges.parquet", row_count=20, payload=b"a"),
    )
    with pytest.raises(ManifestValidationError) as excinfo:
        build_graph_revision_manifest(
            tenant="acme",
            graph_id="skills",
            revision_id="rev-1",
            schema_id="kg.er",
            schema_version="1",
            ontology_id="ont:x",
            ontology_version="1",
            graph_kind="platform-graph",
            storage_profile="parquet",
            codec="parquet",
            counts=GraphCounts(node_count=10, edge_count=20),
            partitions=parts,
            provenance=_provenance(),
        )
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_bad_checksum_hex() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        ContentChecksum(algorithm="sha256", hex_digest="ZZ")
    assert excinfo.value.code == "NONCANONICAL_VALUE"

    with pytest.raises(ManifestValidationError) as excinfo:
        ContentChecksum(algorithm="sha256", hex_digest="A" * 64)  # uppercase
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_bad_created_at() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        _provenance(created_at="yesterday")
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_unsupported_manifest_version() -> None:
    manifest = _manifest()
    data = manifest.to_dict()
    data["manifest_version"] = "kg-revision-manifest/v0"
    # Replace checksum so we hit version check first via from_dict.
    with pytest.raises(ManifestValidationError) as excinfo:
        GraphRevisionManifest.from_dict(data)
    assert excinfo.value.code == "NONCANONICAL_VALUE"


# ---------------------------------------------------------------------------
# Unknown required fields
# ---------------------------------------------------------------------------


def test_rejects_missing_required_top_level_field() -> None:
    manifest = _manifest()
    data = manifest.to_dict()
    del data["graph_kind"]
    with pytest.raises(ManifestValidationError) as excinfo:
        GraphRevisionManifest.from_dict(data)
    assert excinfo.value.code == "UNKNOWN_REQUIRED_FIELD"
    assert "graph_kind" in excinfo.value.message


def test_rejects_unknown_top_level_field() -> None:
    manifest = _manifest()
    data = manifest.to_dict()
    data["extra_unexpected"] = True
    with pytest.raises(ManifestValidationError) as excinfo:
        GraphRevisionManifest.from_dict(data)
    assert excinfo.value.code == "UNKNOWN_REQUIRED_FIELD"
    assert "extra_unexpected" in excinfo.value.message


def test_rejects_missing_partition_fields() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        PartitionDescriptor.from_dict(
            {
                "partition_id": "p1",
                "kind": "nodes",
                # missing path, codec, checksum, row_count, size_bytes
            }
        )
    assert excinfo.value.code == "UNKNOWN_REQUIRED_FIELD"


def test_rejects_unknown_partition_field() -> None:
    p = _partition()
    data = p.to_dict()
    data["mystery"] = 1
    with pytest.raises(ManifestValidationError) as excinfo:
        PartitionDescriptor.from_dict(data)
    assert excinfo.value.code == "UNKNOWN_REQUIRED_FIELD"


# ---------------------------------------------------------------------------
# Invalid counts
# ---------------------------------------------------------------------------


def test_rejects_negative_counts() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        GraphCounts(node_count=-1, edge_count=0)
    assert excinfo.value.code == "INVALID_COUNT"


def test_rejects_non_integer_counts() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        GraphCounts(node_count=1.5, edge_count=0)  # type: ignore[arg-type]
    assert excinfo.value.code == "INVALID_COUNT"

    with pytest.raises(ManifestValidationError) as excinfo:
        GraphCounts(node_count=True, edge_count=0)  # type: ignore[arg-type]
    assert excinfo.value.code == "INVALID_COUNT"


def test_rejects_partition_row_count_mismatch() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        _manifest(
            partitions=(
                _partition("part-nodes", kind="nodes", row_count=10, payload=b"n"),
            ),
            counts=GraphCounts(node_count=99, edge_count=0),
            shards=(),
        )
    assert excinfo.value.code == "INVALID_COUNT"


def test_rejects_negative_size_bytes() -> None:
    with pytest.raises(ManifestValidationError) as excinfo:
        PartitionDescriptor(
            partition_id="p1",
            kind="nodes",
            path="p.parquet",
            codec="parquet",
            checksum=_ck(b"p"),
            row_count=1,
            size_bytes=-1,
        )
    assert excinfo.value.code == "INVALID_COUNT"


# ---------------------------------------------------------------------------
# Checksum / CID mismatch
# ---------------------------------------------------------------------------


def test_rejects_descriptor_checksum_cid_mismatch() -> None:
    checksum = _ck(b"payload-a")
    other_cid = cid_v1_from_sha256_hex(sha256_hex(b"payload-b"))
    with pytest.raises(ManifestIntegrityError) as excinfo:
        PartitionDescriptor(
            partition_id="p1",
            kind="nodes",
            path="p.parquet",
            codec="parquet",
            checksum=checksum,
            row_count=1,
            size_bytes=1,
            cid=other_cid,
        )
    assert excinfo.value.code == "CHECKSUM_CID_MISMATCH"


def test_rejects_manifest_checksum_mismatch() -> None:
    manifest = _manifest()
    data = manifest.to_dict()
    data["checksum"] = ContentChecksum.from_sha256_hex("ab" * 32).to_dict()
    data["root_cid"] = None
    with pytest.raises(ManifestIntegrityError) as excinfo:
        GraphRevisionManifest.from_dict(data)
    assert excinfo.value.code == "CHECKSUM_CID_MISMATCH"


def test_rejects_root_cid_mismatch() -> None:
    manifest = _manifest()
    data = manifest.to_dict()
    # Keep valid checksum but swap root_cid to another valid CID shape.
    data["root_cid"] = cid_v1_from_sha256_hex("cd" * 32)
    with pytest.raises(ManifestIntegrityError) as excinfo:
        GraphRevisionManifest.from_dict(data)
    assert excinfo.value.code == "CHECKSUM_CID_MISMATCH"


def test_root_cid_matches_checksum_derivation() -> None:
    manifest = _manifest()
    assert manifest.root_cid == manifest.checksum.as_cid()
    assert manifest.root_cid == cid_v1_from_sha256_hex(manifest.checksum.hex_digest)


# ---------------------------------------------------------------------------
# Empty / minimal graphs
# ---------------------------------------------------------------------------


def test_empty_graph_manifest() -> None:
    manifest = build_graph_revision_manifest(
        tenant="t1",
        graph_id="g1",
        revision_id="rev-empty",
        schema_id="kg.empty",
        schema_version="1",
        ontology_id="ontology:none",
        ontology_version="0",
        graph_kind="empty",
        storage_profile="parquet",
        codec="json",
        counts=GraphCounts(node_count=0, edge_count=0),
        provenance=_provenance(),
        partitions=(),
        indexes=(),
        shards=(),
    )
    assert manifest.counts.node_count == 0
    assert GraphRevisionManifest.from_json(manifest.to_json()) == manifest


def test_content_checksum_labeled_and_from_sha256_prefix() -> None:
    ck = ContentChecksum(algorithm="sha256", hex_digest="sha256:" + ("ab" * 32))
    assert ck.hex_digest == "ab" * 32
    assert ck.labeled() == "sha256:" + ("ab" * 32)
    assert ck.as_cid().startswith("bafkrei") or ck.as_cid().startswith("b")
