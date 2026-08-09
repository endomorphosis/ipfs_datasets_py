"""Unit tests for the U.S. Code Sparse GraphRAG v2 release schema (USCIR-002).

Acceptance: schema rejects positional durable identity, mutable model/release
references, ambiguous 4,096 fields, absolute artifact paths, invalid digests,
and missing admission/provenance fields.
"""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    ADR_PATH,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    RELEASE_PROFILE,
    SCHEMA_VERSION,
    AdjacencyRecord,
    AmbiguousBoundError,
    ArtifactDescriptor,
    ArtifactFamily,
    ArtifactPathError,
    BoundKind,
    CentroidRecord,
    CorpusRecord,
    GraphEdgeRecord,
    GraphNodeRecord,
    InvalidDigestError,
    LocatorRecord,
    MissingAdmissionProvenanceError,
    MutableReferenceError,
    PhysicalBoundError,
    PositionalIdentityError,
    PostingRecord,
    ReceiptRecord,
    RecoveryRecord,
    ReleaseManifest,
    VectorRecord,
    VerificationResult,
    content_sha256,
    example_corpus_payload,
    example_manifest_payload,
    is_immutable_revision,
    normalize_relative_artifact_path,
    normalize_sha256,
    physical_bounds_policy,
    reject_positional_durable_identity,
    require_immutable_model_ref,
    require_immutable_revision,
    validate_admission_provenance_fields,
    validate_bound_declaration,
    validate_centroid_capacity,
    validate_digest,
    validate_durable_identity_fields,
    validate_entry_cid,
    validate_legal_id,
    validate_physical_pointer_count,
    validate_physical_row_count,
    validate_release_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _digest(label: str) -> str:
    return content_sha256(label)


def _git_sha(seed: str = "model") -> str:
    # 40-char hex from a digest prefix (stable, looks like a Hub commit).
    return _digest(seed)[:40]


# ---------------------------------------------------------------------------
# Schema metadata / happy paths
# ---------------------------------------------------------------------------


def test_schema_constants_match_sealed_policy():
    assert SCHEMA_VERSION == "uscode-sparse-graphrag-release-schema-v2"
    assert RELEASE_PROFILE == "publicus-ir-graphrag/v2"
    assert ADR_PATH.endswith("uscode_sparse_graphrag_schema.md")
    bounds = physical_bounds_policy()
    assert bounds["max_rows_per_physical_shard"] == 4096
    assert bounds["max_posting_pointers_per_row"] == 4096
    assert bounds["max_adjacency_pointers_per_row"] == 4096
    assert bounds["max_rows_per_vector_centroid"] == 8192
    assert bounds["max_vector_shards_per_centroid"] == 2


def test_example_corpus_round_trips():
    payload = example_corpus_payload()
    record = CorpusRecord.from_mapping(payload)
    encoded = record.to_dict()
    again = CorpusRecord.from_mapping(encoded)
    assert again == record
    assert again.entry_cid == payload["entry_cid"]
    assert again.legal_id == "usc:us:35:101"
    assert again.admission_status.value == "admitted"
    assert again.document_index == 0  # release-local only


def test_example_manifest_round_trips():
    payload = example_manifest_payload()
    manifest = ReleaseManifest.from_mapping(payload)
    encoded = manifest.to_dict()
    again = ReleaseManifest.from_mapping(encoded)
    assert again.dataset_repo_id == "justicedao/ipfs_uscode"
    assert again.release_profile == RELEASE_PROFILE
    assert again.max_rows_per_physical_shard == MAX_ROWS_PER_PHYSICAL_SHARD
    assert len(again.artifacts) == 1
    assert again.artifacts[0].relative_path == "data/corpus/part-000000.parquet"
    assert len(again.manifest_digest) == 64


def test_validate_release_record_dispatches_all_families():
    corpus = validate_release_record("corpus", example_corpus_payload())
    assert corpus["legal_id"] == "usc:us:35:101"

    posting = validate_release_record(
        "posting",
        {
            "term": "patent",
            "entry_cids": [_digest("e1"), _digest("e2")],
            "term_shard_id": "bm25-term-0001",
        },
    )
    assert posting["term"] == "patent"
    assert len(posting["entry_cids"]) == 2

    model_rev = _git_sha("vec-model")
    vector = validate_release_record(
        "vector",
        {
            "entry_cid": _digest("vec-entry"),
            "vector_space_id": f"minilm@{model_rev}",
            "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            "model_revision": model_rev,
            "dimension": 3,
            "embedding": [0.0, 1.0, 0.0],
        },
    )
    assert vector["dimension"] == 3

    centroid = validate_release_record(
        "centroid",
        {
            "centroid_id": "c0",
            "vector_space_id": f"minilm@{model_rev}",
            "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            "model_revision": model_rev,
            "dimension": 2,
            "centroid": [1.0, 0.0],
            "row_count": 100,
            "shard_count": 1,
            "shard_descriptors": ["data/vectors/centroid-000-part-000000.parquet"],
        },
    )
    assert centroid["shard_count"] == 1

    node = validate_release_record(
        "graph_node",
        {
            "node_cid": _digest("node-1"),
            "node_type": "section",
            "legal_id": "usc:us:35:101",
        },
    )
    assert node["node_type"] == "section"

    edge = validate_release_record(
        "graph_edge",
        {
            "edge_cid": _digest("edge-1"),
            "edge_type": "CITES",
            "source_node_cid": _digest("node-1"),
            "target_node_cid": _digest("node-2"),
        },
    )
    assert edge["edge_type"] == "CITES"

    adjacency = validate_release_record(
        "adjacency",
        {
            "node_cid": _digest("node-1"),
            "direction": "out",
            "edge_cids": [_digest("edge-1")],
        },
    )
    assert adjacency["direction"] == "out"

    locator = validate_release_record(
        "locator",
        {
            "locator_id": "loc-corpus-0",
            "relative_path": "data/corpus/part-000000.parquet",
            "sha256": _digest("artifact"),
            "family": "corpus",
            "first_key": "a",
            "last_key": "z",
            "row_count": 10,
        },
    )
    assert locator["row_count"] == 10

    receipt = validate_release_record(
        "receipt",
        {
            "receipt_id": "receipt-title-35",
            "release_point": "us/pl/118/45",
            "manifest_digest": _digest("manifest"),
            "source_revision": _git_sha("src"),
        },
    )
    assert receipt["release_point"] == "us/pl/118/45"

    recovery = validate_release_record(
        "recovery",
        {
            "recovery_id": "recovery-9",
            "reason": "heterogeneous recovery JSON without CID",
            "source_path": "recovery/raw-9.json",
            "raw_digest": _digest("raw-9"),
        },
    )
    assert recovery["admission_status"] == "recovery"

    manifest = validate_release_record("manifest", example_manifest_payload())
    assert manifest["schema_version"] == SCHEMA_VERSION


def test_records_are_immutable():
    record = CorpusRecord.from_mapping(example_corpus_payload())
    with pytest.raises(FrozenInstanceError):
        record.legal_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Positional durable identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    ["row-0", "row-12", "row-N", "row_3", "document_index_4", "idx-9", "pos-1"],
)
def test_rejects_positional_durable_identity_tokens(token: str):
    with pytest.raises(PositionalIdentityError):
        reject_positional_durable_identity(token, name="entry_cid")
    with pytest.raises(PositionalIdentityError):
        validate_entry_cid(token)


def test_rejects_document_index_as_sole_durable_identity():
    with pytest.raises(PositionalIdentityError):
        validate_durable_identity_fields(
            {
                "document_index": 42,
                # missing entry_cid / legal_id
            }
        )


def test_rejects_positional_entry_cid_on_corpus_row():
    payload = example_corpus_payload()
    payload["entry_cid"] = "row-7"
    with pytest.raises(PositionalIdentityError):
        CorpusRecord.from_mapping(payload)


def test_rejects_positional_legal_id():
    with pytest.raises(PositionalIdentityError):
        validate_legal_id("row-99")
    payload = example_corpus_payload()
    payload["legal_id"] = "document_index_3"
    with pytest.raises(PositionalIdentityError):
        CorpusRecord.from_mapping(payload)


def test_document_index_allowed_only_as_release_local_companion():
    identity = validate_durable_identity_fields(
        {
            "entry_cid": _digest("ok"),
            "legal_id": "usc:us:18:1001",
            "document_index": 15,
        }
    )
    assert identity["entry_cid"] == _digest("ok")
    payload = example_corpus_payload()
    payload["document_index"] = 15
    record = CorpusRecord.from_mapping(payload)
    assert record.document_index == 15


def test_vector_record_rejects_positional_entry_cid():
    with pytest.raises(PositionalIdentityError):
        VectorRecord(
            entry_cid="row-0",
            vector_space_id="space@%s" % (_git_sha(),),
            model_id="org/model",
            model_revision=_git_sha(),
            dimension=1,
            embedding=(1.0,),
        )


# ---------------------------------------------------------------------------
# Mutable model / release references
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "revision",
    ["latest", "main", "master", "HEAD", "head", "develop", "refs/heads/main"],
)
def test_rejects_mutable_revisions(revision: str):
    assert is_immutable_revision(revision) is False
    with pytest.raises(MutableReferenceError):
        require_immutable_revision(revision)


def test_accepts_immutable_revisions():
    git_sha = _git_sha("pinned")
    digest = _digest("pinned-model")
    assert is_immutable_revision(git_sha)
    assert is_immutable_revision(digest)
    assert is_immutable_revision(f"sha256:{digest}")
    assert require_immutable_revision(git_sha) == git_sha


def test_rejects_mutable_model_ref_on_vector_record():
    with pytest.raises(MutableReferenceError):
        VectorRecord(
            entry_cid=_digest("e"),
            vector_space_id="space@latest",
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            model_revision="latest",
            dimension=1,
            embedding=(0.5,),
        )


def test_rejects_mutable_model_id_token():
    with pytest.raises(MutableReferenceError):
        require_immutable_model_ref(model_id="latest", model_revision=_git_sha())


def test_rejects_mutable_source_revision_on_manifest():
    payload = example_manifest_payload()
    payload["source_revision"] = "main"
    with pytest.raises(MutableReferenceError):
        ReleaseManifest.from_mapping(payload)


def test_rejects_mutable_release_point_on_receipt():
    with pytest.raises(MutableReferenceError):
        ReceiptRecord(
            receipt_id="r1",
            release_point="latest",
            manifest_digest=_digest("m"),
        )


def test_rejects_mutable_release_point_on_admitted_corpus():
    payload = example_corpus_payload()
    payload["release_point"] = "latest"
    with pytest.raises(MutableReferenceError):
        CorpusRecord.from_mapping(payload)


# ---------------------------------------------------------------------------
# Ambiguous 4,096 fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    ["chunk_size", "window_size", "max_tokens", "token_window", "context_window"],
)
def test_rejects_ambiguous_4096_on_tokenish_fields(field_name: str):
    with pytest.raises(AmbiguousBoundError):
        validate_bound_declaration(field_name=field_name, value=4096)


def test_accepts_explicit_physical_4096_fields():
    name, value, kind = validate_bound_declaration(
        field_name="max_rows_per_physical_shard",
        value=4096,
        bound_kind=BoundKind.PHYSICAL_ROWS,
    )
    assert name == "max_rows_per_physical_shard"
    assert value == MAX_ROWS_PER_PHYSICAL_SHARD
    assert kind is BoundKind.PHYSICAL_ROWS


def test_accepts_token_ceiling_when_kind_declared():
    name, value, kind = validate_bound_declaration(
        field_name="model_token_ceiling",
        value=4096,
        bound_kind=BoundKind.MODEL_TOKENS,
    )
    assert kind is BoundKind.MODEL_TOKENS
    assert value == 4096
    assert name == "model_token_ceiling"


def test_rejects_unknown_field_with_bare_4096():
    with pytest.raises(AmbiguousBoundError):
        validate_bound_declaration(field_name="mystery_limit", value=4096)


def test_physical_row_and_pointer_bounds_enforced():
    assert validate_physical_row_count(4096) == 4096
    with pytest.raises(PhysicalBoundError):
        validate_physical_row_count(4097)
    assert validate_physical_pointer_count(4096) == 4096
    with pytest.raises(PhysicalBoundError):
        validate_physical_pointer_count(4097)


def test_posting_record_rejects_oversized_pointer_list():
    cids = tuple(_digest(f"p{i}") for i in range(MAX_POSTING_POINTERS_PER_ROW + 1))
    with pytest.raises(PhysicalBoundError):
        PostingRecord(term="x", entry_cids=cids, term_shard_id="s0")


def test_adjacency_record_rejects_oversized_pointer_list():
    edges = tuple(
        _digest(f"e{i}") for i in range(MAX_ADJACENCY_POINTERS_PER_ROW + 1)
    )
    with pytest.raises(PhysicalBoundError):
        AdjacencyRecord(node_cid=_digest("n"), direction="in", edge_cids=edges)


def test_centroid_capacity_bounds():
    validate_centroid_capacity(row_count=8192, shard_count=2)
    with pytest.raises(PhysicalBoundError):
        validate_centroid_capacity(
            row_count=MAX_ROWS_PER_VECTOR_CENTROID + 1, shard_count=2
        )
    with pytest.raises(PhysicalBoundError):
        validate_centroid_capacity(
            row_count=100, shard_count=MAX_VECTOR_SHARDS_PER_CENTROID + 1
        )


def test_artifact_descriptor_rejects_row_count_over_physical_bound():
    with pytest.raises(PhysicalBoundError):
        ArtifactDescriptor(
            relative_path="data/corpus/part-000000.parquet",
            media_type="application/vnd.apache.parquet",
            sha256=_digest("a"),
            size_bytes=10,
            schema_id="uscode-corpus-v2",
            family=ArtifactFamily.CORPUS,
            row_count=MAX_ROWS_PER_PHYSICAL_SHARD + 1,
        )


# ---------------------------------------------------------------------------
# Absolute / unsafe artifact paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/data/corpus.parquet",
        "/var/lib/release/manifest.json",
        "C:/Users/x/data.parquet",
        "data/../secrets.parquet",
        "data//double.parquet",
        "data\\windows.parquet",
        "~/datasets/x.parquet",
        ".cache/huggingface/x.parquet",
    ],
)
def test_rejects_absolute_or_unsafe_artifact_paths(path: str):
    with pytest.raises(ArtifactPathError):
        normalize_relative_artifact_path(path)


def test_accepts_relative_posix_artifact_paths():
    assert (
        normalize_relative_artifact_path("data/corpus/part-000000.parquet")
        == "data/corpus/part-000000.parquet"
    )
    assert (
        normalize_relative_artifact_path("indexes/vector_chunks.parquet")
        == "indexes/vector_chunks.parquet"
    )


def test_locator_and_descriptor_reject_absolute_paths():
    with pytest.raises(ArtifactPathError):
        LocatorRecord(
            locator_id="loc-1",
            relative_path="/abs/path.parquet",
            sha256=_digest("x"),
            family=ArtifactFamily.CORPUS,
            first_key="a",
            last_key="b",
            row_count=1,
        )
    with pytest.raises(ArtifactPathError):
        ArtifactDescriptor(
            relative_path="/etc/passwd",
            media_type="text/plain",
            sha256=_digest("x"),
            size_bytes=1,
            schema_id="x",
            family=ArtifactFamily.REPORT,
            row_count=0,
        )


def test_recovery_rejects_absolute_source_path():
    with pytest.raises(ArtifactPathError):
        RecoveryRecord(
            recovery_id="r1",
            reason="legacy",
            source_path="/home/operator/raw.json",
        )


def test_centroid_shard_descriptors_must_be_relative():
    model_rev = _git_sha("c")
    with pytest.raises(ArtifactPathError):
        CentroidRecord(
            centroid_id="c0",
            vector_space_id=f"space@{model_rev}",
            model_id="org/model",
            model_revision=model_rev,
            dimension=1,
            centroid=(1.0,),
            row_count=1,
            shard_count=1,
            shard_descriptors=("/abs/shard.parquet",),
        )


# ---------------------------------------------------------------------------
# Invalid digests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "digest",
    [
        "not-a-digest",
        "sha256:xyz",
        "sha256:" + "g" * 64,
        "ab" * 10,  # too short
        "ZZZZ" + "a" * 60,
        "sha256:",  # empty hex after prefix
    ],
)
def test_rejects_invalid_digests(digest: str):
    with pytest.raises(InvalidDigestError):
        validate_digest(digest)


def test_rejects_empty_digest():
    with pytest.raises(Exception):
        validate_digest("")


def test_accepts_valid_digests_and_normalizes():
    hex_digest = _digest("ok")
    assert normalize_sha256(hex_digest) == hex_digest
    assert normalize_sha256(f"sha256:{hex_digest}") == hex_digest
    assert validate_digest(f"sha256:{hex_digest}") == f"sha256:{hex_digest}"
    assert validate_digest(hex_digest) == hex_digest


def test_corpus_rejects_invalid_source_checksum():
    payload = example_corpus_payload()
    payload["source_checksum"] = "not-hex"
    with pytest.raises(InvalidDigestError):
        CorpusRecord.from_mapping(payload)


def test_manifest_rejects_invalid_build_config_cid():
    payload = example_manifest_payload()
    payload["build_config_cid"] = "latest-config"
    with pytest.raises((InvalidDigestError, MutableReferenceError)):
        ReleaseManifest.from_mapping(payload)


def test_receipt_rejects_invalid_manifest_digest():
    with pytest.raises(InvalidDigestError):
        ReceiptRecord(
            receipt_id="r",
            release_point="us/pl/118/45",
            manifest_digest="nope",
        )


# ---------------------------------------------------------------------------
# Missing admission / provenance fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field",
    [
        "admission_status",
        "admission_reason",
        "source_cid",
        "release_point",
        "source_checksum",
        "verification_result",
        "acquisition_time",
        "entry_cid",
        "legal_id",
    ],
)
def test_rejects_missing_admission_or_provenance_fields(missing_field: str):
    payload = example_corpus_payload()
    payload[missing_field] = ""
    with pytest.raises(
        (MissingAdmissionProvenanceError, Exception)
    ):
        CorpusRecord.from_mapping(payload)


def test_validate_admission_provenance_requires_fields_when_admitted():
    with pytest.raises(MissingAdmissionProvenanceError):
        validate_admission_provenance_fields(
            {
                "admission_status": "admitted",
                "admission_reason": "ok",
                # provenance missing
            }
        )


def test_excluded_row_requires_admission_but_not_full_provenance():
    # Direct helper: excluded needs status+reason only.
    result = validate_admission_provenance_fields(
        {
            "admission_status": "excluded",
            "admission_reason": "uncodified slip law",
        }
    )
    assert result["admission_status"] == "excluded"


def test_recovery_cannot_be_marked_admitted():
    with pytest.raises(Exception):
        RecoveryRecord(
            recovery_id="r-bad",
            reason="should not admit",
            admission_status="admitted",
        )


def test_missing_identity_fields_surface_clearly():
    with pytest.raises(MissingAdmissionProvenanceError):
        validate_durable_identity_fields({"legal_id": "usc:us:1:1"})
    with pytest.raises(MissingAdmissionProvenanceError):
        validate_durable_identity_fields({"entry_cid": _digest("only-cid")})


# ---------------------------------------------------------------------------
# Graph / adjacency / locator smoke structure
# ---------------------------------------------------------------------------


def test_graph_node_and_edge_round_trip():
    node = GraphNodeRecord(
        node_cid=_digest("n1"),
        node_type="section",
        legal_id="usc:us:42:1983",
        label="42 U.S.C. § 1983",
        payload={"title": "42"},
    )
    edge = GraphEdgeRecord(
        edge_cid=_digest("e1"),
        edge_type="CITES",
        source_node_cid=node.node_cid,
        target_node_cid=_digest("n2"),
    )
    assert GraphNodeRecord.from_mapping(node.to_dict()) == node
    assert GraphEdgeRecord.from_mapping(edge.to_dict()) == edge


def test_adjacency_normalizes_direction_aliases():
    record = AdjacencyRecord(
        node_cid=_digest("n"),
        direction="outgoing",
        edge_cids=(_digest("e"),),
    )
    assert record.direction == "out"
    record_in = AdjacencyRecord(
        node_cid=_digest("n"),
        direction="incoming",
        edge_cids=(_digest("e"),),
    )
    assert record_in.direction == "in"


def test_manifest_sorts_and_dedupes_artifact_paths():
    payload = example_manifest_payload()
    first = copy.deepcopy(payload["artifacts"][0])
    second = copy.deepcopy(payload["artifacts"][0])
    second["relative_path"] = "data/bm25/documents/part-000000.parquet"
    second["sha256"] = _digest("bm25-docs")
    second["family"] = ArtifactFamily.BM25_DOCUMENTS.value
    # Insert second path first so sorting is observable.
    payload["artifacts"] = [second, first]
    manifest = ReleaseManifest.from_mapping(payload)
    paths = [item.relative_path for item in manifest.artifacts]
    assert paths == sorted(paths)
    assert paths[0] == "data/bm25/documents/part-000000.parquet"

    # Duplicate path fails closed.
    base = example_manifest_payload()
    dup = copy.deepcopy(base["artifacts"][0])
    base["artifacts"] = [dup, copy.deepcopy(dup)]
    with pytest.raises(Exception):
        ReleaseManifest.from_mapping(base)


def test_manifest_rejects_wrong_release_profile():
    payload = example_manifest_payload()
    payload["release_profile"] = "publicus-ir-graphrag/v1"
    with pytest.raises(Exception):
        ReleaseManifest.from_mapping(payload)


def test_verification_result_enum_on_corpus():
    payload = example_corpus_payload()
    payload["verification_result"] = "verified"
    record = CorpusRecord.from_mapping(payload)
    assert record.verification_result is VerificationResult.VERIFIED
