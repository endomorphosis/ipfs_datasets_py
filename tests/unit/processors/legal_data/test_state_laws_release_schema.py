"""Unit tests for the state-law Sparse GraphRAG v2 release schema (LCR-004).

Acceptance: schema requires entry_cid/legal_id/source_cid, official provenance,
exact model/revision, relative paths, bounded rows/pointers, semantic-family
closure, and immutable pins.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    ADR_PATH,
    CANONICAL_JURISDICTIONS,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    EXPECTED_JURISDICTION_COUNT,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    REQUIRED_IDENTITY_FIELDS,
    REQUIRED_PROVENANCE_FIELDS,
    REQUIRED_SEMANTIC_FAMILIES,
    SCHEMA_VERSION,
    TASK_ID,
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
    JurisdictionSetError,
    LocatorRecord,
    MissingAdmissionProvenanceError,
    MutableReferenceError,
    OfficialProvenanceError,
    PhysicalBoundError,
    PositionalIdentityError,
    PostingRecord,
    PublicationRecord,
    ReceiptRecord,
    RecoveryRecord,
    ReleaseManifest,
    RollbackRecord,
    SemanticFamilyClosureError,
    SourceAuthorityClass,
    SourceReceiptRecord,
    StateLawsReleaseSchemaError,
    VectorRecord,
    content_sha256,
    example_corpus_payload,
    example_manifest_payload,
    example_publication_payload,
    example_rollback_payload,
    example_source_receipt_payload,
    is_immutable_revision,
    normalize_relative_artifact_path,
    normalize_sha256,
    physical_bounds_policy,
    reject_positional_durable_identity,
    require_immutable_model_ref,
    require_immutable_revision,
    required_semantic_families,
    validate_admission_provenance_fields,
    validate_bound_declaration,
    validate_centroid_capacity,
    validate_digest,
    validate_durable_identity_fields,
    validate_entry_cid,
    validate_jurisdiction_set,
    validate_legal_id,
    validate_physical_pointer_count,
    validate_physical_row_count,
    validate_release_record,
    validate_semantic_family_closure,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _digest(label: str) -> str:
    return content_sha256(label)


def _git_sha(seed: str = "model") -> str:
    return _digest(seed)[:40]


# ---------------------------------------------------------------------------
# Schema metadata / happy paths
# ---------------------------------------------------------------------------


def test_schema_constants_match_sealed_policy():
    assert SCHEMA_VERSION == "state-laws-sparse-graphrag-release-schema-v2"
    assert RELEASE_PROFILE == "state-laws-ir-graphrag/v2"
    assert ADR_PATH.endswith("legal_corpora_reindex_schema.md")
    assert DEFAULT_DATASET_REPO_ID == "justicedao/ipfs_state_laws"
    assert PREVIOUS_PUBLIC_PIN == "42f0546acc7c6cd55627eaf51fb820d5613b9021"
    assert DEFAULT_EMBEDDING_MODEL_ID == "thenlper/gte-small"
    assert DEFAULT_EMBEDDING_MODEL_REVISION == (
        "17e1f347d17fe144873b1201da91788898c639cd"
    )
    assert TASK_ID == "LCR-004"
    assert len(CANONICAL_JURISDICTIONS) == EXPECTED_JURISDICTION_COUNT == 51
    assert "DC" in CANONICAL_JURISDICTIONS
    assert "CA" in CANONICAL_JURISDICTIONS
    bounds = physical_bounds_policy()
    assert bounds["max_rows_per_physical_shard"] == 4096
    assert bounds["max_posting_pointers_per_row"] == 4096
    assert bounds["max_adjacency_pointers_per_row"] == 4096
    assert bounds["max_rows_per_vector_centroid"] == 8192
    assert bounds["max_vector_shards_per_centroid"] == 2
    assert REQUIRED_IDENTITY_FIELDS == frozenset(
        {"entry_cid", "legal_id", "source_cid"}
    )
    for field_name in (
        "source_cid",
        "release_point",
        "source_checksum",
        "verification_result",
        "acquisition_time",
        "official_source_url",
        "acquisition_receipt_id",
        "parser_version",
        "jurisdiction",
        "code_family",
    ):
        assert field_name in REQUIRED_PROVENANCE_FIELDS


def test_example_corpus_round_trips():
    payload = example_corpus_payload()
    record = CorpusRecord.from_mapping(payload)
    encoded = record.to_dict()
    again = CorpusRecord.from_mapping(encoded)
    assert again == record
    assert again.entry_cid == payload["entry_cid"]
    assert again.legal_id == "state:OR:ors:123:456"
    assert again.source_cid == payload["source_cid"]
    assert again.jurisdiction == "OR"
    assert again.admission_status.value == "admitted"
    assert again.source_authority_class is SourceAuthorityClass.OFFICIAL
    assert again.document_index == 0


def test_corpus_explicit_relation_arrays_round_trip_exactly_and_default_empty():
    legacy = CorpusRecord.from_mapping(example_corpus_payload())
    assert (
        legacy.public_laws,
        legacy.cites,
        legacy.amends,
        legacy.repeals,
        legacy.transfers,
    ) == ((), (), (), (), ())

    payload = example_corpus_payload()
    payload.update(
        {
            "public_laws": ["Pub. L. 117-58", "Pub. L. 112-29"],
            "cites": ["state:OR:ors:123:457"],
            "amends": ["state:OR:ors:123:458"],
            "repeals": ["state:OR:ors:123:459"],
            "transfers": ["state:OR:ors:123:460", "state:OR:ors:123:460"],
        }
    )

    record = CorpusRecord.from_mapping(payload)
    encoded = record.to_dict()

    assert encoded["public_laws"] == payload["public_laws"]
    assert encoded["cites"] == payload["cites"]
    assert encoded["amends"] == payload["amends"]
    assert encoded["repeals"] == payload["repeals"]
    assert encoded["transfers"] == payload["transfers"]
    assert CorpusRecord.from_mapping(encoded) == record


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    (
        ("public_laws", "Pub. L. 117-58"),
        ("cites", {"target": "state:OR:ors:123:457"}),
        ("amends", [""]),
    ),
)
def test_corpus_relation_evidence_must_be_an_array_of_non_empty_strings(
    field_name: str,
    invalid: object,
) -> None:
    payload = example_corpus_payload()
    payload[field_name] = invalid
    with pytest.raises(StateLawsReleaseSchemaError, match=field_name):
        CorpusRecord.from_mapping(payload)


def test_example_manifest_round_trips_with_family_closure():
    payload = example_manifest_payload()
    manifest = ReleaseManifest.from_mapping(payload)
    encoded = manifest.to_dict()
    again = ReleaseManifest.from_mapping(encoded)
    assert again.dataset_repo_id == DEFAULT_DATASET_REPO_ID
    assert again.release_profile == RELEASE_PROFILE
    assert again.model_id == DEFAULT_EMBEDDING_MODEL_ID
    assert again.model_revision == DEFAULT_EMBEDDING_MODEL_REVISION
    assert again.max_rows_per_physical_shard == MAX_ROWS_PER_PHYSICAL_SHARD
    assert again.present_families() >= REQUIRED_SEMANTIC_FAMILIES
    assert len(again.manifest_digest) == 64


def test_example_source_receipt_round_trips():
    payload = example_source_receipt_payload()
    record = SourceReceiptRecord.from_mapping(payload)
    again = SourceReceiptRecord.from_mapping(record.to_dict())
    assert again == record
    assert again.frontier_closed is True
    assert again.failed_final == 0
    assert again.discovered == (
        again.fetched + again.excluded + again.quarantined + again.failed_final
    )


def test_example_publication_and_rollback_round_trips():
    publication = PublicationRecord.from_mapping(example_publication_payload())
    assert publication.additive_only is True
    assert publication.previous_revision == PREVIOUS_PUBLIC_PIN
    again_pub = PublicationRecord.from_mapping(publication.to_dict())
    assert again_pub == publication

    rollback = RollbackRecord.from_mapping(example_rollback_payload())
    again_rb = RollbackRecord.from_mapping(rollback.to_dict())
    assert again_rb == rollback
    assert again_rb.to_revision == PREVIOUS_PUBLIC_PIN


def test_validate_release_record_dispatches_all_families():
    corpus = validate_release_record("corpus", example_corpus_payload())
    assert corpus["legal_id"] == "state:OR:ors:123:456"

    source_receipt = validate_release_record(
        "source_receipt", example_source_receipt_payload()
    )
    assert source_receipt["jurisdiction"] == "OR"

    posting = validate_release_record(
        "posting",
        {
            "term": "statute",
            "entry_cids": [_digest("e1"), _digest("e2")],
            "term_shard_id": "bm25-term-0001",
        },
    )
    assert posting["term"] == "statute"

    model_rev = DEFAULT_EMBEDDING_MODEL_REVISION
    vector = validate_release_record(
        "vector",
        {
            "entry_cid": _digest("vec-entry"),
            "vector_space_id": f"gte-small@{model_rev}",
            "model_id": DEFAULT_EMBEDDING_MODEL_ID,
            "model_revision": model_rev,
            "dimension": 3,
            "embedding": [0.0, 1.0, 0.0],
            "jurisdiction": "OR",
        },
    )
    assert vector["dimension"] == 3

    centroid = validate_release_record(
        "centroid",
        {
            "centroid_id": "c0",
            "vector_space_id": f"gte-small@{model_rev}",
            "model_id": DEFAULT_EMBEDDING_MODEL_ID,
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
            "legal_id": "state:or:ors:123:456",
            "jurisdiction": "OR",
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
            "relative_path": "data/corpus/jurisdiction=OR/part-000000.parquet",
            "sha256": _digest("artifact"),
            "family": "corpus",
            "first_key": "a",
            "last_key": "z",
            "row_count": 10,
            "jurisdiction": "OR",
        },
    )
    assert locator["row_count"] == 10

    receipt = validate_release_record(
        "receipt",
        {
            "receipt_id": "receipt-build-1",
            "release_point": "state-laws/v2/2026-08-10",
            "manifest_digest": _digest("manifest"),
            "source_revision": _git_sha("src"),
        },
    )
    assert receipt["release_point"] == "state-laws/v2/2026-08-10"

    recovery = validate_release_record(
        "recovery",
        {
            "recovery_id": "recovery-9",
            "reason": "secondary source without official authority",
            "source_path": "recovery/raw-9.json",
            "raw_digest": _digest("raw-9"),
            "jurisdiction": "OR",
        },
    )
    assert recovery["admission_status"] == "recovery"

    publication = validate_release_record(
        "publication", example_publication_payload()
    )
    assert publication["public_revision"] == "a" * 40

    rollback = validate_release_record("rollback", example_rollback_payload())
    assert rollback["to_revision"] == PREVIOUS_PUBLIC_PIN

    manifest = validate_release_record("manifest", example_manifest_payload())
    assert manifest["schema_version"] == SCHEMA_VERSION


def test_records_are_immutable():
    record = CorpusRecord.from_mapping(example_corpus_payload())
    with pytest.raises(FrozenInstanceError):
        record.legal_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# entry_cid / legal_id / source_cid identity
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


def test_requires_entry_cid_legal_id_and_source_cid():
    with pytest.raises(MissingAdmissionProvenanceError) as excinfo:
        validate_durable_identity_fields(
            {
                "legal_id": "state:or:ors:1:1",
                "source_cid": _digest("src"),
            }
        )
    assert "entry_cid" in str(excinfo.value)

    with pytest.raises(MissingAdmissionProvenanceError) as excinfo:
        validate_durable_identity_fields(
            {
                "entry_cid": _digest("e"),
                "source_cid": _digest("src"),
            }
        )
    assert "legal_id" in str(excinfo.value)

    with pytest.raises(MissingAdmissionProvenanceError) as excinfo:
        validate_durable_identity_fields(
            {
                "entry_cid": _digest("e"),
                "legal_id": "state:or:ors:1:1",
            }
        )
    assert "source_cid" in str(excinfo.value)


def test_rejects_document_index_as_sole_durable_identity():
    with pytest.raises(PositionalIdentityError):
        validate_durable_identity_fields({"document_index": 42})


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


def test_legal_id_requires_state_shape_and_known_jurisdiction():
    with pytest.raises(Exception):
        validate_legal_id("usc:us:35:101")
    with pytest.raises(JurisdictionSetError):
        validate_legal_id("state:xx:code:1:2")
    assert validate_legal_id("state:dc:dc_code:1:101").startswith("state:DC:")


def test_document_index_allowed_only_as_release_local_companion():
    identity = validate_durable_identity_fields(
        {
            "entry_cid": _digest("ok"),
            "legal_id": "state:or:ors:18:1001",
            "source_cid": _digest("src-ok"),
            "document_index": 15,
        }
    )
    assert identity["entry_cid"] == _digest("ok")
    assert identity["source_cid"] == _digest("src-ok")


# ---------------------------------------------------------------------------
# Official provenance
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
        "official_source_url",
        "acquisition_receipt_id",
        "parser_version",
        "jurisdiction",
        "code_family",
        "entry_cid",
        "legal_id",
    ],
)
def test_rejects_missing_admission_or_provenance_fields(missing_field: str):
    payload = example_corpus_payload()
    payload[missing_field] = ""
    with pytest.raises((MissingAdmissionProvenanceError, Exception)):
        CorpusRecord.from_mapping(payload)


def test_rejects_secondary_source_on_admitted_row():
    payload = example_corpus_payload()
    payload["source_authority_class"] = "secondary"
    with pytest.raises(OfficialProvenanceError):
        CorpusRecord.from_mapping(payload)


def test_rejects_non_http_official_url():
    payload = example_corpus_payload()
    payload["official_source_url"] = "/local/path/to/statute.html"
    with pytest.raises(OfficialProvenanceError):
        CorpusRecord.from_mapping(payload)


def test_excluded_row_requires_admission_but_not_full_provenance():
    result = validate_admission_provenance_fields(
        {
            "admission_status": "excluded",
            "admission_reason": "navigation-only index page",
        }
    )
    assert result["admission_status"] == "excluded"


def test_source_receipt_rejects_unreconciled_counts():
    payload = example_source_receipt_payload()
    payload["discovered"] = 50
    with pytest.raises(Exception):
        SourceReceiptRecord.from_mapping(payload)


def test_source_receipt_rejects_closed_frontier_with_failures():
    payload = example_source_receipt_payload()
    payload["failed_final"] = 1
    payload["fetched"] = 94
    payload["frontier_closed"] = True
    with pytest.raises(Exception):
        SourceReceiptRecord.from_mapping(payload)


def test_recovery_cannot_be_marked_admitted():
    with pytest.raises(Exception):
        RecoveryRecord(
            recovery_id="r-bad",
            reason="should not admit",
            admission_status="admitted",
        )


# ---------------------------------------------------------------------------
# Exact model / revision and immutable pins
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
            model_id=DEFAULT_EMBEDDING_MODEL_ID,
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


def test_publication_requires_immutable_pins():
    payload = example_publication_payload()
    payload["public_revision"] = "main"
    with pytest.raises(MutableReferenceError):
        PublicationRecord.from_mapping(payload)


def test_publication_rejects_non_additive_or_wrong_repo():
    payload = example_publication_payload()
    payload["additive_only"] = False
    with pytest.raises(Exception):
        PublicationRecord.from_mapping(payload)
    payload = example_publication_payload()
    payload["dataset_repo_id"] = "other/org"
    with pytest.raises(Exception):
        PublicationRecord.from_mapping(payload)


def test_rollback_requires_distinct_immutable_pins():
    payload = example_rollback_payload()
    payload["from_revision"] = payload["to_revision"]
    with pytest.raises(Exception):
        RollbackRecord.from_mapping(payload)
    payload = example_rollback_payload()
    payload["to_revision"] = "latest"
    with pytest.raises(MutableReferenceError):
        RollbackRecord.from_mapping(payload)


# ---------------------------------------------------------------------------
# Relative paths
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
        normalize_relative_artifact_path(
            "data/corpus/jurisdiction=OR/part-000000.parquet"
        )
        == "data/corpus/jurisdiction=OR/part-000000.parquet"
    )
    assert (
        normalize_relative_artifact_path("receipts/scrape/jurisdiction-OR.json")
        == "receipts/scrape/jurisdiction-OR.json"
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


def test_source_receipt_and_recovery_reject_absolute_paths():
    payload = example_source_receipt_payload()
    payload["relative_path"] = "/home/operator/receipt.json"
    with pytest.raises(ArtifactPathError):
        SourceReceiptRecord.from_mapping(payload)
    with pytest.raises(ArtifactPathError):
        RecoveryRecord(
            recovery_id="r1",
            reason="legacy",
            source_path="/home/operator/raw.json",
        )


# ---------------------------------------------------------------------------
# Bounded rows / pointers
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
            relative_path="data/corpus/jurisdiction=OR/part-000000.parquet",
            media_type="application/vnd.apache.parquet",
            sha256=_digest("a"),
            size_bytes=10,
            schema_id="state-laws-corpus-v2",
            family=ArtifactFamily.CORPUS,
            row_count=MAX_ROWS_PER_PHYSICAL_SHARD + 1,
            jurisdiction="OR",
        )


# ---------------------------------------------------------------------------
# Semantic-family closure
# ---------------------------------------------------------------------------


def test_required_semantic_families_are_closed_set():
    names = required_semantic_families()
    assert "corpus" in names
    assert "bm25_documents" in names
    assert "bm25_postings" in names
    assert "vectors" in names
    assert "centroids" in names
    assert "graph_nodes" in names
    assert "graph_edges" in names
    assert "graph_adjacency_out" in names
    assert "graph_adjacency_in" in names
    assert "locator_index" in names
    assert "manifest" in names
    assert "recovery" not in names


def test_semantic_family_closure_accepts_complete_set():
    result = validate_semantic_family_closure(REQUIRED_SEMANTIC_FAMILIES)
    assert result["closed"] is True
    assert result["missing"] == []


def test_semantic_family_closure_rejects_missing_family():
    incomplete = set(REQUIRED_SEMANTIC_FAMILIES) - {ArtifactFamily.GRAPH_ADJACENCY_IN}
    with pytest.raises(SemanticFamilyClosureError) as excinfo:
        validate_semantic_family_closure(incomplete)
    assert "graph_adjacency_in" in str(excinfo.value)


def test_manifest_enforces_semantic_family_closure_by_default():
    payload = example_manifest_payload()
    # Drop adjacency-in family.
    payload["artifacts"] = [
        item
        for item in payload["artifacts"]
        if item["family"] != ArtifactFamily.GRAPH_ADJACENCY_IN.value
    ]
    with pytest.raises(SemanticFamilyClosureError):
        ReleaseManifest.from_mapping(payload)


def test_manifest_can_skip_closure_when_explicitly_disabled_for_partial_fixtures():
    payload = example_manifest_payload(enforce_semantic_family_closure=False)
    payload["artifacts"] = payload["artifacts"][:2]
    manifest = ReleaseManifest.from_mapping(payload)
    assert manifest.enforce_semantic_family_closure is False


def test_manifest_with_exact_jurisdiction_set():
    payload = example_manifest_payload(include_all_jurisdictions=True)
    manifest = ReleaseManifest.from_mapping(payload)
    assert len(manifest.jurisdictions) == 51
    assert set(manifest.jurisdictions) == CANONICAL_JURISDICTIONS


def test_jurisdiction_set_rejects_missing_or_extra():
    incomplete = sorted(CANONICAL_JURISDICTIONS - {"DC"})
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(incomplete)
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(list(CANONICAL_JURISDICTIONS) + ["PR"])


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "digest",
    [
        "not-a-digest",
        "sha256:xyz",
        "sha256:" + "g" * 64,
        "ab" * 10,
        "ZZZZ" + "a" * 60,
        "sha256:",
    ],
)
def test_rejects_invalid_digests(digest: str):
    with pytest.raises(InvalidDigestError):
        validate_digest(digest)


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


# ---------------------------------------------------------------------------
# Graph / adjacency smoke structure
# ---------------------------------------------------------------------------


def test_graph_node_and_edge_round_trip():
    node = GraphNodeRecord(
        node_cid=_digest("n1"),
        node_type="section",
        legal_id="state:or:ors:42:1983",
        jurisdiction="OR",
        label="ORS 42.1983",
        payload={"code_family": "ors"},
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
        direction="incoming",
        edge_cids=(_digest("e1"),),
    )
    assert record.direction == "in"
    record_out = AdjacencyRecord(
        node_cid=_digest("n"),
        direction="outgoing",
        edge_cids=(_digest("e1"),),
    )
    assert record_out.direction == "out"


def test_require_source_rights_binding_matches_receipt_digest():
    from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
        SOURCE_RIGHTS_RECEIPT_RELPATH,
        SourceRightsBindingError,
        require_source_rights_binding,
    )

    digest = _digest("rights")
    catalog = _digest("catalog")
    manifest = {
        "source_rights_receipt_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
        "source_rights_receipt_digest": digest,
        "source_rights_catalog_digest": catalog,
    }
    require_source_rights_binding(
        manifest,
        receipt_digest=digest,
        catalog_digest=catalog,
        dataset_card_text=f"digest {digest}",
    )
    with pytest.raises(SourceRightsBindingError):
        require_source_rights_binding(
            {"source_rights_receipt_digest": _digest("other")},
            receipt_digest=digest,
        )
