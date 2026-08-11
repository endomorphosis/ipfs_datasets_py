"""Integration tests for public legal corpus production vector index (PATLAW-172).

Acceptance:

* Snapshot binds embedding model pin and corpus root
* Private text cannot enter
* Rebuild is stable under fixed model / corpus pins
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.embedding_runtime import (
    PINNED_DIMENSION,
    LocalEmbeddingRuntime,
    pinned_runtime_identity,
)
from ipfs_datasets_py.processors.domains.patent.index_snapshot_contracts import (
    IndexFamily,
    KNOWN_MODEL_PINS,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (
    build_default_public_legal_recipe,
    PublicLegalCorpusMaterializer,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_vector_builder import (
    DEFAULT_CREATED_UTC,
    DEFAULT_MODEL_PIN,
    DEFAULT_TENANT_ID,
    EMBEDDING_RECEIPT_FILENAME,
    GOAL_ID,
    INTERFACE,
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    SNAPSHOT_FILENAME,
    TASK_ID,
    VECTORS_FILENAME,
    VECTOR_ROOT_FILENAME,
    BuildMode,
    PrivateTextRejectedError,
    PublicLegalVectorBuilder,
    PublicLegalVectorManifest,
    assert_public_only_for_vector,
    build_public_legal_vector_index,
    builds_are_byte_identical,
    default_model_identity,
    load_manifest,
    model_identity_from_runtime,
    validate_build,
    validate_build_stable,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recipe() -> dict:
    return build_default_public_legal_recipe()


@pytest.fixture(scope="module")
def corpus(recipe: dict):
    return PublicLegalCorpusMaterializer(require_all_families=True).materialize_from_recipe(
        recipe
    )


@pytest.fixture(scope="module")
def builder() -> PublicLegalVectorBuilder:
    return PublicLegalVectorBuilder(require_all_families=True)


@pytest.fixture(scope="module")
def baseline(builder: PublicLegalVectorBuilder, recipe: dict):
    return builder.build(recipe=recipe, created_utc=DEFAULT_CREATED_UTC)


# ---------------------------------------------------------------------------
# Schema / pin surface
# ---------------------------------------------------------------------------


def test_schema_pins():
    assert SCHEMA_VERSION == "patent.public_legal_vector.v1"
    assert INTERFACE == "PublicLegalVectorBuilder@1"
    assert TASK_ID == "PATLAW-172"
    assert GOAL_ID == "PATLAW-G211"
    assert DEFAULT_MODEL_PIN in KNOWN_MODEL_PINS


def test_default_model_identity_binds_runtime_and_known_pin():
    model = default_model_identity()
    runtime = pinned_runtime_identity()
    assert model.model_pin == DEFAULT_MODEL_PIN
    assert model.dimension == runtime.dimension == PINNED_DIMENSION
    assert model.model_id == runtime.model_id
    assert model.config_cid == runtime.config_cid
    assert model.model_cid == runtime.model_cid


# ---------------------------------------------------------------------------
# Acceptance: binds model pin + corpus root
# ---------------------------------------------------------------------------


def test_snapshot_binds_model_pin_and_corpus_root(baseline, corpus):
    manifest = baseline.manifest
    assert manifest.model_pin == DEFAULT_MODEL_PIN
    assert manifest.model_pin in KNOWN_MODEL_PINS
    assert manifest.corpus_root_cid == corpus.corpus_root_cid
    assert manifest.corpus_digest_sha256 == corpus.corpus_digest_sha256
    assert manifest.dimension == PINNED_DIMENSION
    assert manifest.partition == "public"
    assert manifest.document_count == len(corpus.documents) == len(baseline.rows)
    assert IndexFamily.VECTOR.value in manifest.families

    # Contract snapshot also carries model + corpus identities.
    snap = baseline.snapshot
    assert snap.manifest.identities.model is not None
    assert snap.manifest.identities.model.model_pin == DEFAULT_MODEL_PIN
    assert snap.manifest.identities.corpus.corpus_cid == corpus.corpus_root_cid
    assert snap.manifest.identities.corpus.corpus_digest == corpus.corpus_digest_sha256
    assert list(snap.manifest.families) == [IndexFamily.VECTOR]
    assert snap.manifest.partition.value == "public"
    assert snap.manifest.tenant_id == DEFAULT_TENANT_ID


def test_vector_root_artifact_binds_pins(builder, recipe, tmp_path: Path):
    result = builder.build(
        recipe=recipe,
        stage=True,
        output_dir=tmp_path / "vector-index",
        created_utc=DEFAULT_CREATED_UTC,
    )
    root_path = Path(result.output_dir) / VECTOR_ROOT_FILENAME
    payload = json.loads(root_path.read_text(encoding="utf-8"))
    assert payload["model_pin"] == DEFAULT_MODEL_PIN
    assert payload["corpus_root_cid"] == result.corpus_root_cid
    assert payload["index_root_cid"] == result.index_root_cid
    assert payload["dimension"] == PINNED_DIMENSION
    assert payload["task_id"] == TASK_ID


def test_each_row_binds_model_pin_and_source_join(baseline):
    for row in baseline.rows:
        assert row.model_pin == DEFAULT_MODEL_PIN
        assert row.dimension == PINNED_DIMENSION
        assert row.source_cid
        assert row.source_version
        assert row.vector_digest
        assert len(row.vector) == PINNED_DIMENSION
        assert row.classification == "public_official"


# ---------------------------------------------------------------------------
# Acceptance: private text cannot enter
# ---------------------------------------------------------------------------


def test_private_classification_fails_closed(builder, recipe):
    private_classes = (
        "confidential_application",
        "privileged_work_product",
        "restricted_export_review",
        "credential_or_payment",
        "unknown",
        "mixed",
    )
    for classification in private_classes:
        bad = copy.deepcopy(recipe)
        bad["documents"][0]["classification"] = classification
        with pytest.raises(PrivateTextRejectedError):
            builder.build(recipe=bad, created_utc=DEFAULT_CREATED_UTC)


def test_assert_public_only_rejects_private_mapping(recipe):
    docs = copy.deepcopy(recipe["documents"])
    docs[0]["classification"] = "confidential_application"
    with pytest.raises(PrivateTextRejectedError):
        assert_public_only_for_vector(docs)


def test_public_partition_only_on_manifest(baseline):
    assert baseline.manifest.partition == "public"
    for rec in baseline.snapshot.records:
        assert rec.disclosure.value == "public_official"


# ---------------------------------------------------------------------------
# Acceptance: rebuild stable under fixed model/corpus pins
# ---------------------------------------------------------------------------


def test_rebuild_is_stable_under_fixed_pins(builder, recipe, baseline):
    first = builder.build(recipe=recipe, created_utc=DEFAULT_CREATED_UTC)
    second = builder.build(recipe=copy.deepcopy(recipe), created_utc=DEFAULT_CREATED_UTC)
    third = build_public_legal_vector_index(
        recipe=recipe,
        created_utc=DEFAULT_CREATED_UTC,
    )

    assert first.index_root_cid == second.index_root_cid == baseline.index_root_cid
    assert (
        first.index_digest_sha256
        == second.index_digest_sha256
        == baseline.index_digest_sha256
    )
    assert first.model_pin == second.model_pin == DEFAULT_MODEL_PIN
    assert first.corpus_root_cid == second.corpus_root_cid == baseline.corpus_root_cid
    assert builds_are_byte_identical(first, second)
    assert builds_are_byte_identical(first, third)

    # Per-document vector digests are stable.
    first_digests = {r.document_id: r.vector_digest for r in first.rows}
    second_digests = {r.document_id: r.vector_digest for r in second.rows}
    assert first_digests == second_digests


def test_validate_build_stable_helper(baseline, recipe):
    receipt = validate_build_stable(
        baseline, recipe=recipe, created_utc=DEFAULT_CREATED_UTC
    )
    assert receipt["ok"] is True
    assert receipt["rebuild_stable"] is True
    assert receipt["model_pin"] == DEFAULT_MODEL_PIN
    assert receipt["corpus_root_cid"] == baseline.corpus_root_cid
    assert receipt["rebuild_index_root_cid"] == baseline.index_root_cid


def test_document_order_does_not_affect_index_cid(builder, recipe, baseline):
    shuffled = copy.deepcopy(recipe)
    shuffled["documents"] = list(reversed(shuffled["documents"]))
    result = builder.build(recipe=shuffled, created_utc=DEFAULT_CREATED_UTC)
    assert result.index_root_cid == baseline.index_root_cid
    assert [r.document_id for r in result.rows] == sorted(
        r.document_id for r in result.rows
    )


def test_dry_run_and_stage_share_index_cid(builder, recipe, baseline, tmp_path: Path):
    staged = builder.build(
        recipe=recipe,
        stage=True,
        output_dir=tmp_path / "vector",
        created_utc=DEFAULT_CREATED_UTC,
    )
    assert staged.index_root_cid == baseline.index_root_cid
    assert staged.mode is BuildMode.STAGE
    assert staged.output_dir is not None
    out = Path(staged.output_dir)
    for name in (
        MANIFEST_FILENAME,
        VECTORS_FILENAME,
        VECTOR_ROOT_FILENAME,
        SNAPSHOT_FILENAME,
        EMBEDDING_RECEIPT_FILENAME,
    ):
        assert (out / name).is_file(), name


# ---------------------------------------------------------------------------
# Manifest round-trip / validation
# ---------------------------------------------------------------------------


def test_manifest_round_trip(baseline):
    restored = PublicLegalVectorManifest.from_dict(baseline.manifest.to_dict())
    assert restored.index_root_cid == baseline.index_root_cid
    assert restored.model_pin == baseline.model_pin
    assert restored.corpus_root_cid == baseline.corpus_root_cid
    assert restored.compute_index_digest() == baseline.manifest.index_digest_sha256


def test_load_staged_manifest(builder, recipe, tmp_path: Path):
    staged = builder.build(
        recipe=recipe,
        stage=True,
        output_dir=tmp_path / "vector",
        created_utc=DEFAULT_CREATED_UTC,
    )
    loaded = load_manifest(Path(staged.output_dir) / MANIFEST_FILENAME)
    assert loaded.index_root_cid == staged.index_root_cid
    assert loaded.model_pin == DEFAULT_MODEL_PIN


def test_validate_build_receipt(baseline):
    receipt = validate_build(baseline)
    assert receipt["ok"] is True
    assert receipt["task_id"] == TASK_ID
    assert receipt["document_count"] == len(baseline.rows)


def test_build_from_materialization(builder, corpus, baseline):
    result = builder.build_from_materialization(
        corpus, created_utc=DEFAULT_CREATED_UTC
    )
    assert result.index_root_cid == baseline.index_root_cid
    assert result.corpus_root_cid == corpus.corpus_root_cid


def test_module_level_default_fixture():
    result = build_public_legal_vector_index(created_utc=DEFAULT_CREATED_UTC)
    assert result.model_pin == DEFAULT_MODEL_PIN
    assert result.dimension == PINNED_DIMENSION
    assert len(result.rows) >= 8
    assert result.manifest.document_count == len(result.rows)


def test_snapshot_source_joins_are_non_empty(baseline):
    baseline.snapshot.verify_source_joins()
    for rec in baseline.snapshot.records:
        assert len(rec.source_joins) >= 1
        assert rec.family is IndexFamily.VECTOR


def test_model_identity_from_runtime_matches_builder():
    runtime = LocalEmbeddingRuntime()
    model = model_identity_from_runtime(runtime.identity)
    assert model.model_pin == DEFAULT_MODEL_PIN
    assert model.dimension == runtime.identity.dimension
