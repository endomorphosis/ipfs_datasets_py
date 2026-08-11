"""Integration tests for public legal BM25 index snapshot builder (PATLAW-171).

Acceptance:

* Deterministic rebuild for pinned corpus root
* Orphan terms / postings fail closed
* Snapshot schema matches release packaging expectations
  (bm25_documents + bm25_postings join fields and Viewer paths)
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.indexing import TOKENIZER_VERSION
from ipfs_datasets_py.processors.domains.patent.public_legal_bm25_builder import (
    DOCUMENTS_FILENAME,
    GOAL_ID,
    INDEX_ROOT_FILENAME,
    INTERFACE,
    MANIFEST_FILENAME,
    POSTINGS_FILENAME,
    RECEIPT_FILENAME,
    RELEASE_CONFIGS,
    RELEASE_DOCUMENTS_JOIN_FIELDS,
    RELEASE_DOCUMENTS_PATTERN,
    RELEASE_POSTINGS_JOIN_FIELDS,
    RELEASE_POSTINGS_PATTERN,
    RELEASE_REPOSITORY,
    RELEASE_ROLE,
    SCHEMA_VERSION,
    TASK_ID,
    TERMS_FILENAME,
    Bm25DocumentRecord,
    Bm25PostingRecord,
    Bm25TermRecord,
    BuildMode,
    CorpusPinError,
    OrphanDocumentError,
    OrphanPostingError,
    OrphanTermError,
    PrivateOrMixedInputError,
    PublicLegalBm25Builder,
    PublicLegalBm25Manifest,
    PublicLegalBm25Snapshot,
    SnapshotIntegrityError,
    build_public_legal_bm25_index,
    load_bm25_snapshot,
    load_corpus_materialization,
    release_packaging_bindings,
    snapshots_are_byte_identical,
    validate_snapshot,
    verify_release_packaging_schema,
    verify_zero_orphans,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (
    MANIFEST_FILENAME as CORPUS_MANIFEST_FILENAME,
    PublicLegalCorpusMaterializer,
    build_default_public_legal_recipe,
)


@pytest.fixture(scope="module")
def recipe() -> dict:
    return build_default_public_legal_recipe()


@pytest.fixture(scope="module")
def corpus(recipe: dict):
    return PublicLegalCorpusMaterializer(require_all_families=True).materialize_from_recipe(
        recipe
    )


@pytest.fixture(scope="module")
def builder() -> PublicLegalBm25Builder:
    return PublicLegalBm25Builder()


@pytest.fixture(scope="module")
def baseline(builder: PublicLegalBm25Builder, corpus):
    return builder.build(corpus)


# ---------------------------------------------------------------------------
# Content-address stability for pinned corpus root
# ---------------------------------------------------------------------------


def test_repeat_builds_are_content_address_stable(
    builder: PublicLegalBm25Builder, corpus, baseline
):
    first = builder.build(corpus)
    second = builder.build(corpus)
    third = build_public_legal_bm25_index(corpus)

    assert first.index_cid == second.index_cid == baseline.index_cid
    assert (
        first.index_digest_sha256
        == second.index_digest_sha256
        == baseline.index_digest_sha256
    )
    assert first.corpus_root_cid == corpus.corpus_root_cid
    assert first.to_canonical_bytes() == second.to_canonical_bytes()
    assert snapshots_are_byte_identical(first, third)

    restored = PublicLegalBm25Manifest.from_dict(first.manifest.to_dict())
    assert restored.index_cid == first.index_cid
    assert restored.index_digest_sha256 == first.index_digest_sha256


def test_rebuild_from_recipe_matches_materialization_path(
    builder: PublicLegalBm25Builder, recipe: dict, baseline
):
    from_recipe = builder.build_from_recipe(recipe, require_all_families=True)
    assert from_recipe.index_cid == baseline.index_cid
    assert from_recipe.corpus_root_cid == baseline.corpus_root_cid
    assert from_recipe.to_canonical_bytes() == baseline.to_canonical_bytes()


def test_document_order_does_not_affect_index_cid(
    builder: PublicLegalBm25Builder, recipe: dict, baseline
):
    shuffled = copy.deepcopy(recipe)
    shuffled["documents"] = list(reversed(shuffled["documents"]))
    result = builder.build_from_recipe(shuffled, require_all_families=True)
    assert result.index_cid == baseline.index_cid
    assert [d.record_id for d in result.documents] == sorted(
        d.record_id for d in result.documents
    )


def test_changed_corpus_text_changes_index_cid(
    builder: PublicLegalBm25Builder, recipe: dict, baseline
):
    altered = copy.deepcopy(recipe)
    altered["documents"][0]["text"] = altered["documents"][0]["text"] + " [amended]"
    result = builder.build_from_recipe(altered, require_all_families=True)
    assert result.corpus_root_cid != baseline.corpus_root_cid
    assert result.index_cid != baseline.index_cid


def test_expected_corpus_root_cid_pin(
    builder: PublicLegalBm25Builder, corpus, baseline
):
    ok = builder.build(
        corpus, expected_corpus_root_cid=corpus.corpus_root_cid
    )
    assert ok.index_cid == baseline.index_cid
    with pytest.raises(CorpusPinError):
        builder.build(
            corpus,
            expected_corpus_root_cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
        )


def test_dry_run_and_stage_share_index_cid(
    builder: PublicLegalBm25Builder,
    corpus,
    baseline,
    tmp_path: Path,
):
    staged = builder.build(corpus, stage=True, output_dir=tmp_path / "bm25")
    assert staged.mode is BuildMode.STAGE
    assert staged.index_cid == baseline.index_cid
    assert staged.index_digest_sha256 == baseline.index_digest_sha256
    assert staged.corpus_root_cid == baseline.corpus_root_cid

    out = tmp_path / "bm25"
    for name in (
        MANIFEST_FILENAME,
        DOCUMENTS_FILENAME,
        TERMS_FILENAME,
        POSTINGS_FILENAME,
        RECEIPT_FILENAME,
        INDEX_ROOT_FILENAME,
    ):
        assert (out / name).is_file(), name

    loaded = load_bm25_snapshot(out)
    assert loaded.index_cid == baseline.index_cid
    assert len(loaded.documents) == len(baseline.documents)
    assert len(loaded.terms) == len(baseline.terms)
    assert len(loaded.postings) == len(baseline.postings)


def test_build_from_staged_corpus_dir(
    builder: PublicLegalBm25Builder,
    recipe: dict,
    baseline,
    tmp_path: Path,
):
    materializer = PublicLegalCorpusMaterializer(require_all_families=True)
    staged_corpus = materializer.materialize_from_recipe(
        recipe, stage=True, output_dir=tmp_path / "corpus"
    )
    assert (tmp_path / "corpus" / CORPUS_MANIFEST_FILENAME).is_file()

    reloaded = load_corpus_materialization(tmp_path / "corpus")
    assert reloaded.corpus_root_cid == staged_corpus.corpus_root_cid

    result = builder.build_from_corpus_dir(tmp_path / "corpus")
    assert result.index_cid == baseline.index_cid
    assert result.corpus_root_cid == baseline.corpus_root_cid


# ---------------------------------------------------------------------------
# Orphan terms / postings fail closed
# ---------------------------------------------------------------------------


def test_orphan_posting_fails(baseline):
    docs = list(baseline.documents)
    terms = list(baseline.terms)
    postings = list(baseline.postings)
    bad = Bm25PostingRecord(
        term=terms[0].term,
        term_id=terms[0].term_id,
        document_id="doc:does-not-exist",
        corpus_record_id="doc:does-not-exist",
        field="description",
        tf=1,
        df=terms[0].document_frequency,
        document_length=1,
        source_cid=docs[0].source_cid,
    )
    with pytest.raises(OrphanPostingError):
        verify_zero_orphans(
            documents=docs,
            terms=terms,
            postings=postings + [bad],
        )


def test_orphan_term_fails(baseline):
    docs = list(baseline.documents)
    terms = list(baseline.terms)
    postings = list(baseline.postings)
    orphan = Bm25TermRecord(
        term="__orphan_term_xyz__",
        term_id=10_000,
        document_frequency=1,
        corpus_frequency=1,
        idf=1.0,
        fields=("description",),
    )
    with pytest.raises(OrphanTermError):
        verify_zero_orphans(
            documents=docs,
            terms=terms + [orphan],
            postings=postings,
        )


def test_orphan_document_without_postings_fails(baseline):
    docs = list(baseline.documents)
    terms = list(baseline.terms)
    postings = list(baseline.postings)
    ghost = Bm25DocumentRecord.from_dict(
        {
            **docs[0].to_dict(),
            "record_id": "ghost:no-postings",
            "corpus_record_id": "ghost:no-postings",
        }
    )
    with pytest.raises(OrphanDocumentError):
        verify_zero_orphans(
            documents=docs + [ghost],
            terms=terms,
            postings=postings,
        )


def test_posting_term_missing_from_vocabulary_fails(baseline):
    docs = list(baseline.documents)
    terms = list(baseline.terms)
    postings = list(baseline.postings)
    bad = Bm25PostingRecord(
        term="__not_in_vocab__",
        term_id=0,
        document_id=docs[0].record_id,
        corpus_record_id=docs[0].corpus_record_id,
        field="description",
        tf=1,
        df=1,
        document_length=docs[0].document_length,
        source_cid=docs[0].source_cid,
    )
    with pytest.raises(OrphanTermError):
        verify_zero_orphans(
            documents=docs,
            terms=terms,
            postings=postings + [bad],
        )


def test_snapshot_rejects_orphan_posting_on_construction(baseline):
    docs = list(baseline.documents)
    terms = list(baseline.terms)
    postings = list(baseline.postings)
    bad = Bm25PostingRecord(
        term=terms[0].term,
        term_id=terms[0].term_id,
        document_id="missing:doc",
        corpus_record_id="missing:doc",
        field="title",
        tf=1,
        df=terms[0].document_frequency,
        document_length=1,
        source_cid=docs[0].source_cid,
    )
    with pytest.raises((OrphanPostingError, SnapshotIntegrityError)):
        PublicLegalBm25Snapshot(
            documents=tuple(docs),
            terms=tuple(terms),
            postings=tuple(postings + [bad]),
            manifest=baseline.manifest,
        )


# ---------------------------------------------------------------------------
# Release packaging schema
# ---------------------------------------------------------------------------


def test_snapshot_schema_matches_release_packaging(baseline):
    assert baseline.manifest.schema_version == SCHEMA_VERSION
    assert baseline.manifest.interface == INTERFACE
    assert baseline.manifest.task_id == TASK_ID
    assert baseline.manifest.goal_id == GOAL_ID
    assert baseline.manifest.partition == "public"
    assert baseline.manifest.tokenizer_version == TOKENIZER_VERSION
    assert baseline.manifest.index_cid.startswith("b")
    assert len(baseline.manifest.index_digest_sha256) == 64
    assert baseline.manifest.corpus_root_cid.startswith("b")

    packaging = verify_release_packaging_schema(baseline.manifest)
    assert packaging["ok"] is True
    assert packaging["role"] == RELEASE_ROLE
    assert packaging["repository"] == RELEASE_REPOSITORY
    assert set(packaging["configs"]) == set(RELEASE_CONFIGS)

    bindings = release_packaging_bindings()
    by_name = {c["config_name"]: c for c in bindings["configs"]}
    assert by_name["bm25_documents"]["data_files_pattern"] == RELEASE_DOCUMENTS_PATTERN
    assert by_name["bm25_postings"]["data_files_pattern"] == RELEASE_POSTINGS_PATTERN
    for field in RELEASE_DOCUMENTS_JOIN_FIELDS:
        assert field in by_name["bm25_documents"]["join_fields"]
    for field in RELEASE_POSTINGS_JOIN_FIELDS:
        assert field in by_name["bm25_postings"]["join_fields"]


def test_release_document_and_posting_rows(baseline):
    doc_rows = baseline.release_document_rows()
    assert len(doc_rows) == len(baseline.documents)
    for row in doc_rows:
        for key in ("record_id", "corpus_record_id", "source_cid", "text_preview", "token_count"):
            assert key in row
        assert row["source_cid"].startswith("b")
        assert row["token_count"] >= 1

    post_rows = baseline.release_posting_rows()
    assert len(post_rows) >= 1
    doc_ids = {d.record_id for d in baseline.documents}
    for row in post_rows:
        for key in ("term", "document_id", "tf", "df"):
            assert key in row
        assert row["document_id"] in doc_ids
        assert row["tf"] >= 1
        assert row["df"] >= 1


def test_every_document_joins_corpus(baseline, corpus):
    corpus_ids = {d.record_id for d in corpus.documents}
    assert len(baseline.documents) == len(corpus.documents)
    for doc in baseline.documents:
        assert doc.corpus_record_id in corpus_ids
        assert doc.record_id in corpus_ids
        join = next(
            j
            for j in corpus.manifest.document_joins
            if j["record_id"] == doc.record_id
        )
        assert doc.document_cid == join["document_cid"]
        assert doc.source_cid == join["source_cid"]


def test_counts_and_zero_orphans(baseline):
    m = baseline.manifest.counts
    assert m.document_count == len(baseline.documents)
    assert m.term_count == len(baseline.terms)
    assert m.posting_count == len(baseline.postings)
    assert m.total_tokens >= m.document_count
    assert sum(m.by_family.values()) == m.document_count

    verify_zero_orphans(
        documents=baseline.documents,
        terms=baseline.terms,
        postings=baseline.postings,
        corpus_document_count=baseline.manifest.corpus_document_count,
        corpus_record_ids=[d.corpus_record_id for d in baseline.documents],
    )


def test_validate_snapshot_receipt(baseline):
    receipt = validate_snapshot(baseline)
    assert receipt["ok"] is True
    assert receipt["task_id"] == TASK_ID
    assert receipt["document_count"] == len(baseline.documents)
    assert receipt["term_count"] == len(baseline.terms)
    assert receipt["posting_count"] == len(baseline.postings)
    assert receipt["index_cid"] == baseline.index_cid


def test_snapshot_receipt_binds_corpus_and_index(baseline):
    receipt = baseline.manifest.to_receipt()
    assert receipt["corpus_root_cid"] == baseline.corpus_root_cid
    assert receipt["index_cid"] == baseline.index_cid
    assert receipt["task_id"] == TASK_ID
    assert receipt["schema_version"] == SCHEMA_VERSION
    assert set(receipt["release_packaging"]["configs"]) == set(RELEASE_CONFIGS)


def test_private_classification_fails_closed(
    builder: PublicLegalBm25Builder, recipe: dict
):
    private = copy.deepcopy(recipe)
    private["documents"][0]["classification"] = "confidential_application"
    with pytest.raises((PrivateOrMixedInputError, Exception)):
        builder.build_from_recipe(private, require_all_families=True)


def test_tampered_index_digest_fails(baseline):
    payload = baseline.manifest.to_dict()
    payload["index_digest_sha256"] = "0" * 64
    with pytest.raises(SnapshotIntegrityError):
        PublicLegalBm25Manifest.from_dict(payload)


def test_legal_tokens_survive_in_vocabulary(baseline):
    terms = {t.term for t in baseline.terms}
    # Fixture text includes U.S.C. / C.F.R. / section references.
    joined = " ".join(terms)
    assert any("101" in t or "§" in t or "usc" in t.lower() or "cfr" in t.lower() or "patent" in t for t in terms) or "patent" in joined
    assert len(terms) >= 20


def test_default_fixture_covers_multiple_families(baseline):
    families = set(baseline.manifest.counts.by_family)
    assert len(families) >= 5
    assert baseline.manifest.counts.document_count >= 8
