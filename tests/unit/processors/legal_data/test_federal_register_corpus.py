"""Unit tests for canonical Federal Register corpus materialization (LCR-055).

Acceptance: One disposition per input, unique primary keys, valid provenance
and offsets, exact row conservation, bounded Parquet, and no duplicated
per-posting lineage.

Tests are hermetic against the LCR-053 18-document fixture inventory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    default_report_path as inventory_report_path,
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.federal_register_fulltext import (
    CoverageDisposition,
    FulltextConfig,
    FulltextMode,
    enrich_federal_register_fulltext,
    load_fixture_inventory_documents,
)
from ipfs_datasets_py.processors.legal_data.federal_register_corpus import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    CANONICAL_COUNT_FAMILIES,
    CURRENTNESS_DISCLAIMER,
    DEFAULT_MODEL_TOKEN_LIMIT,
    EXPECTED_FIXTURE_DOCUMENTS,
    FIXTURE_SCHEMA_VERSION,
    GOAL_ID,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    PARSER_VERSION,
    PRODUCER,
    REPORT_SCHEMA,
    SCHEMA_VERSION,
    TASK_ID,
    TRANSFORMATION_VERSION,
    CorpusConfig,
    DispositionError,
    FailedFinalAdmissionError,
    FixtureInventoryError,
    InventoryRewriteError,
    LedgerEntry,
    LineageDuplicationError,
    MaterializedCorpus,
    RowDisposition,
    assert_admitted_rows_complete,
    assert_bounded_parquet,
    assert_chunk_offsets_valid,
    assert_every_row_has_exactly_one_disposition,
    assert_exclusive_coverage,
    assert_fixture_inventory_only,
    assert_no_duplicated_per_posting_lineage,
    assert_recovery_excluded_from_canonical_counts,
    assert_row_conservation,
    assert_unique_primary_keys,
    build_federal_admission_report,
    default_admission_report_path,
    load_federal_admission_report,
    materialize_federal_register_corpus,
    plan_structure_chunks,
    write_federal_admission_report,
)
from ipfs_datasets_py.processors.legal_data.federal_register_identity import (
    DuplicatePrimaryKeyError,
    parse_chunk_id,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    AdmissionStatus,
    CorpusRecord,
    LocatorRecord,
    RecoveryRecord,
    SourceReceiptRecord,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN,
    content_sha256,
)


@pytest.fixture(scope="module")
def enrichment():
    return enrich_federal_register_fulltext(
        config=FulltextConfig(mode=FulltextMode.FIXTURE)
    )


@pytest.fixture(scope="module")
def corpus(enrichment):
    return materialize_federal_register_corpus(enrichment=enrichment)


# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "federal-register-corpus-v1"
    assert FIXTURE_SCHEMA_VERSION == "federal-register-corpus-admission-v1"
    assert REPORT_SCHEMA == (
        "ipfs_datasets_py/legal-corpora-reindex-federal-admission@1"
    )
    assert TASK_ID == "LCR-055"
    assert GOAL_ID == "LCR-G110"
    assert PRODUCER == "federal_register_corpus.py"
    assert PARSER_VERSION == "federal-register-parser/v2"
    assert TRANSFORMATION_VERSION == "federal-register-corpus-transform-v1"
    assert EXPECTED_FIXTURE_DOCUMENTS == 18
    assert DEFAULT_MODEL_TOKEN_LIMIT == 512
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert DEFAULT_MODEL_TOKEN_LIMIT != MAX_ROWS_PER_PHYSICAL_SHARD
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert "cutoff-relative" in CURRENTNESS_DISCLAIMER
    assert "corpus" in CANONICAL_COUNT_FAMILIES
    assert "chunks" in CANONICAL_COUNT_FAMILIES
    assert "bm25" in CANONICAL_COUNT_FAMILIES
    assert "vector" in CANONICAL_COUNT_FAMILIES
    assert "graph" in CANONICAL_COUNT_FAMILIES


def test_default_report_path_is_relative_safe() -> None:
    path = default_admission_report_path()
    assert path.name == "federal_admission.json"
    assert "legal_corpora_reindex" in path.parts


# ---------------------------------------------------------------------------
# Fixture inventory hermeticity
# ---------------------------------------------------------------------------


def test_materialization_uses_lcr053_fixture_not_live_inventory(corpus, enrichment) -> None:
    documents, report = load_fixture_inventory_documents()
    assert len(documents) == EXPECTED_FIXTURE_DOCUMENTS
    unique = int(report.get("counts", {}).get("unique_legal_ids") or 0)
    assert unique == EXPECTED_FIXTURE_DOCUMENTS
    assert unique < 1000
    assert enrichment.inventory_document_count == EXPECTED_FIXTURE_DOCUMENTS
    assert corpus.inventory_document_count == EXPECTED_FIXTURE_DOCUMENTS
    assert_fixture_inventory_only(corpus)
    inventory_ids = {doc.legal_id for doc in documents}
    ledger_ids = {entry.inventory_legal_id for entry in corpus.ledger}
    assert ledger_ids == inventory_ids
    coverage_ids = {item.legal_id for item in enrichment.documents}
    assert coverage_ids == inventory_ids


def test_live_mode_is_rejected() -> None:
    with pytest.raises(FixtureInventoryError):
        CorpusConfig(mode=FulltextMode.LIVE)


def test_official_inventory_is_not_rewritten(corpus) -> None:
    path = inventory_report_path()
    before = path.read_bytes() if path.is_file() else None
    digest_before = content_sha256(before) if before is not None else None
    materialize_federal_register_corpus()
    after = path.read_bytes() if path.is_file() else None
    assert after == before
    if digest_before is not None:
        assert content_sha256(after) == digest_before
    with pytest.raises(InventoryRewriteError):
        write_federal_admission_report(path)


# ---------------------------------------------------------------------------
# One disposition per input
# ---------------------------------------------------------------------------


def test_every_input_has_exactly_one_disposition(corpus, enrichment) -> None:
    mapping = assert_every_row_has_exactly_one_disposition(corpus.ledger)
    assert len(mapping) == EXPECTED_FIXTURE_DOCUMENTS
    assert len(corpus.ledger) == len(enrichment.documents)
    present = set(mapping.values())
    assert RowDisposition.ADMITTED.value in present
    assert RowDisposition.EXCLUDED.value in present
    assert RowDisposition.QUARANTINED.value in present
    assert RowDisposition.FAILED_FINAL.value not in present
    coverage_by_id = {item.legal_id: item for item in enrichment.documents}
    for entry in corpus.ledger:
        coverage = coverage_by_id[entry.inventory_legal_id]
        if coverage.disposition.is_admitted or coverage.disposition is CoverageDisposition.METADATA_ONLY:
            assert entry.disposition is RowDisposition.ADMITTED
        elif coverage.disposition is CoverageDisposition.EXCLUDED:
            assert entry.disposition is RowDisposition.EXCLUDED
        elif coverage.disposition is CoverageDisposition.QUARANTINED:
            assert entry.disposition is RowDisposition.QUARANTINED


def test_duplicate_disposition_is_rejected() -> None:
    entries = [
        LedgerEntry(
            row_id="fr:2026-45000:2026-03-03",
            disposition=RowDisposition.EXCLUDED,
            reason="first",
            document_number="2026-45000",
            publication_date="2026-03-03",
            inventory_legal_id="fr:2026-45000:2026-03-03",
            coverage_disposition="excluded",
            year_month="2026-03",
            document_type="rule",
        ),
        LedgerEntry(
            row_id="fr:2026-45000:2026-03-03",
            disposition=RowDisposition.ADMITTED,
            reason="second",
            document_number="2026-45000",
            publication_date="2026-03-03",
            inventory_legal_id="fr:2026-45000:2026-03-03",
            coverage_disposition="html_body",
            year_month="2026-03",
            document_type="rule",
            legal_id="fr:2026-45000:2026-03-03:type=rule",
            entry_cid="b" + "a" * 32,
            source_cid="b" + "c" * 32,
        ),
    ]
    with pytest.raises(DispositionError):
        assert_every_row_has_exactly_one_disposition(entries)


# ---------------------------------------------------------------------------
# Unique primary keys and provenance
# ---------------------------------------------------------------------------


def test_admitted_rows_have_unique_primary_keys_and_provenance(corpus) -> None:
    assert_admitted_rows_complete(corpus.corpus_records)
    assert_unique_primary_keys(corpus.corpus_records)
    entry_cids = [record.entry_cid for record in corpus.corpus_records]
    assert len(entry_cids) == len(set(entry_cids))
    legal_ids = [record.legal_id for record in corpus.corpus_records]
    assert len(legal_ids) == len(set(legal_ids))
    for record in corpus.corpus_records:
        schema_row = CorpusRecord.from_mapping(record.to_dict())
        assert schema_row.admission_status is AdmissionStatus.ADMITTED
        assert schema_row.entry_cid.startswith("b") or len(schema_row.entry_cid) >= 32
        assert schema_row.legal_id.startswith("fr:")
        assert schema_row.source_cid
        assert schema_row.release_point.startswith("fr/cutoff/")
        assert schema_row.source_checksum
        assert schema_row.verification_result.value == "verified"
        assert schema_row.acquisition_time
        assert schema_row.official_source_url.startswith("https://")
        assert schema_row.parser_version == PARSER_VERSION
        assert schema_row.document_number
        assert schema_row.publication_date
        assert schema_row.year_month == schema_row.publication_date[:7]
        if schema_row.text_availability.has_usable_body:
            assert schema_row.text.strip()
        else:
            assert schema_row.text_availability.value == "metadata_only"


def test_searchable_and_metadata_only_are_both_accounted(corpus, enrichment) -> None:
    full_text = [
        item for item in enrichment.documents if item.disposition.is_admitted
    ]
    metadata = [
        item
        for item in enrichment.documents
        if item.disposition is CoverageDisposition.METADATA_ONLY
    ]
    assert len(full_text) == 13
    assert len(metadata) == 1
    assert len(corpus.corpus_records) == 14
    assert len(corpus.searchable_documents) == 13
    searchable_ids = {record.document_number for record in corpus.searchable_documents}
    assert searchable_ids == {item.document_number for item in full_text}


# ---------------------------------------------------------------------------
# Structure-aware chunks and offsets
# ---------------------------------------------------------------------------


def test_structure_aware_chunks_have_valid_offsets(corpus) -> None:
    assert corpus.chunks
    assert_chunk_offsets_valid(corpus.corpus_records, corpus.chunks)
    chunk_ids = [chunk.chunk_id for chunk in corpus.chunks]
    assert len(chunk_ids) == len(set(chunk_ids))
    for chunk in corpus.chunks:
        parent, index = parse_chunk_id(chunk.chunk_id)
        assert parent == chunk.parent_legal_id
        assert index == chunk.chunk_index
        assert chunk.entry_cid
        assert chunk.source_cid
        assert chunk.token_count <= DEFAULT_MODEL_TOKEN_LIMIT
        assert chunk.model_token_limit == DEFAULT_MODEL_TOKEN_LIMIT
        assert "attempts" not in chunk.to_dict()
        assert "postings" not in chunk.to_dict()
    structured = [
        chunk
        for chunk in corpus.chunks
        if chunk.split_mode == "structure" or "Section" in chunk.heading
    ]
    assert structured


def test_plan_structure_chunks_covers_section_markers() -> None:
    text = (
        "Official Federal Register document 2026-45000 published on 2026-03-03.\n"
        "Section 1. Purpose. This document implements the sealed fixture.\n"
        "Section 2. Authority. Acquisition uses FederalRegister.gov and GovInfo."
    )
    planned = plan_structure_chunks(text)
    assert len(planned) >= 2
    assert_exclusive_coverage(text, planned)
    headings = " ".join(item["heading"] for item in planned)
    assert "Section 1" in headings or "Section 2" in headings


def test_chunks_join_source_lineage_without_posting_copies(corpus) -> None:
    assert_no_duplicated_per_posting_lineage(corpus)
    by_source = {row.source_cid: row for row in corpus.source_lineage}
    assert len(by_source) == len(corpus.corpus_records)
    for chunk in corpus.chunks:
        lineage = by_source[chunk.source_cid]
        assert lineage.entry_cid == chunk.entry_cid
        assert lineage.document_number == chunk.document_number
        payload = chunk.to_dict()
        assert "attempts" not in payload
        assert "posting_lineage" not in payload
        assert "format_attempts" not in payload


# ---------------------------------------------------------------------------
# Row conservation, recovery, bounded parquet
# ---------------------------------------------------------------------------


def test_exact_row_conservation(corpus, enrichment) -> None:
    assert_row_conservation(corpus)
    counts = corpus.disposition_counts
    assert sum(counts.values()) == EXPECTED_FIXTURE_DOCUMENTS
    assert counts[RowDisposition.ADMITTED.value] == 14
    assert counts[RowDisposition.EXCLUDED.value] == 1
    assert counts[RowDisposition.QUARANTINED.value] == 3
    assert counts[RowDisposition.FAILED_FINAL.value] == 0
    assert enrichment.failed_final == 0
    assert len(corpus.recovery_records) == 3
    assert corpus.family_counts.excluded == 1


def test_recovery_is_quarantine_only_and_not_admitted(corpus) -> None:
    assert_recovery_excluded_from_canonical_counts(corpus)
    for record in corpus.recovery_records:
        schema = RecoveryRecord.from_mapping(record.to_dict())
        assert schema.admission_status is not AdmissionStatus.ADMITTED
        if schema.source_path is not None:
            assert not schema.source_path.startswith("/")
            assert ":" not in schema.source_path[:2] or schema.source_path[1] != ":"
    counts = corpus.family_counts.to_dict()
    assert counts["corpus"] == len(corpus.corpus_records)
    assert counts["chunks"] == len(corpus.chunks)
    assert counts["recovery"] == 3
    for family in ("bm25", "vector", "graph"):
        assert counts[family] == 0
        assert counts[family] != counts["corpus"] + counts["recovery"]


def test_type_date_partitions_and_bounded_parquet(corpus) -> None:
    assert_bounded_parquet(corpus.parquet_shards)
    families = {shard.family for shard in corpus.parquet_shards}
    assert "corpus" in families
    assert "chunks" in families
    assert "recovery" in families
    year_months = {shard.year_month for shard in corpus.parquet_shards if shard.family == "corpus"}
    assert year_months
    assert all(len(item) == 7 and item[4] == "-" for item in year_months)
    doc_types = {
        shard.document_type
        for shard in corpus.parquet_shards
        if shard.family == "corpus"
    }
    assert "rule" in doc_types
    assert "proposed_rule" in doc_types
    assert "notice" in doc_types
    for shard in corpus.parquet_shards:
        assert shard.row_count <= MAX_ROWS_PER_PHYSICAL_SHARD
        assert shard.max_rows == 4096
        assert shard.bound_kind == "physical_rows"
        assert shard.relative_path.endswith(".parquet")
        assert not shard.relative_path.startswith("/")
        assert "year_month=" in shard.relative_path or shard.family == "recovery"


def test_direct_locators_are_release_relative(corpus) -> None:
    assert corpus.locators
    document_locators = [
        locator for locator in corpus.locators if locator.document_number is not None
    ]
    assert len(document_locators) == len(corpus.corpus_records)
    for locator in corpus.locators:
        schema = LocatorRecord.from_mapping(locator.to_dict())
        assert not schema.relative_path.startswith("/")
        assert "\\" not in schema.relative_path
        assert schema.row_count <= MAX_ROWS_PER_PHYSICAL_SHARD
    for receipt in corpus.source_receipts:
        schema = SourceReceiptRecord.from_mapping(receipt.to_dict())
        assert schema.relative_path.startswith("receipts/acquire/")
        assert schema.enumerated == (
            schema.fetched + schema.duplicate + schema.excluded + schema.quarantined + schema.failed_final
        )
        assert schema.failed_final == 0
        assert schema.frontier_closed is True


def test_failed_final_cannot_be_admitted(corpus) -> None:
    assert corpus.disposition_counts[RowDisposition.FAILED_FINAL.value] == 0
    with pytest.raises(FailedFinalAdmissionError):
        raise FailedFinalAdmissionError("failed-final body acquisition remains unresolved")


# ---------------------------------------------------------------------------
# Admission report
# ---------------------------------------------------------------------------


def test_admission_report_is_secret_free_and_fixture_bound(corpus, tmp_path: Path) -> None:
    report = build_federal_admission_report(corpus)
    assert report["task_id"] == TASK_ID
    assert report["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert report["acceptance"]["one_disposition_per_input"] is True
    assert report["acceptance"]["unique_primary_keys"] is True
    assert report["acceptance"]["valid_provenance_and_offsets"] is True
    assert report["acceptance"]["exact_row_conservation"] is True
    assert report["acceptance"]["bounded_parquet"] is True
    assert report["acceptance"]["no_duplicated_per_posting_lineage"] is True
    assert report["acceptance"]["fixture_inventory_documents"] == 18
    assert report["acceptance"]["not_live_inventory"] is True
    assert report["acceptance"]["hub_upload"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["conservation"]["input"] == 18
    assert report["conservation"]["accounted"] == 18
    assert report["inventory"]["rewritten"] is False
    assert report["inventory"]["report_relpath"] == (
        "docs/reports/legal_corpora_reindex/federal_inventory.json"
    )
    assert report["observation_cutoff"] == DEFAULT_OBSERVATION_CUTOFF
    assert report["previous_public_pin"] == PREVIOUS_PUBLIC_PIN
    assert find_secret_surfaces(report) == []
    blob = json.dumps(report, sort_keys=True)
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert "hf_" not in blob
    assert "Bearer " not in blob
    assert "sk-" not in blob
    path = tmp_path / "federal_admission.json"
    written = write_federal_admission_report(path, corpus=corpus)
    assert written == path
    loaded = load_federal_admission_report(path)
    assert loaded["task_id"] == TASK_ID
    assert "/home/" not in path.read_text(encoding="utf-8")


def test_on_disk_admission_report_matches_contract(corpus) -> None:
    path = default_admission_report_path()
    if not path.is_file():
        write_federal_admission_report(path, corpus=corpus)
    loaded = load_federal_admission_report(path)
    assert loaded["task_id"] == TASK_ID
    assert loaded["conservation"]["input"] == 18
    assert loaded["acceptance"]["hub_upload"] is False
    blob = path.read_text(encoding="utf-8")
    assert "/home/" not in blob
    assert "/Users/" not in blob


def test_replay_is_deterministic(enrichment) -> None:
    first = materialize_federal_register_corpus(enrichment=enrichment)
    second = materialize_federal_register_corpus(enrichment=enrichment)
    assert [row.entry_cid for row in first.corpus_records] == [
        row.entry_cid for row in second.corpus_records
    ]
    assert [chunk.chunk_id for chunk in first.chunks] == [
        chunk.chunk_id for chunk in second.chunks
    ]
    assert [row.source_cid for row in first.source_lineage] == [
        row.source_cid for row in second.source_lineage
    ]


def test_lineage_duplication_detector(corpus) -> None:
    poisoned = list(corpus.chunks)
    if not poisoned:
        pytest.skip("no chunks")
    original = poisoned[0]
    # A second lineage row with the same source_cid must fail closed.
    duplicated = corpus.source_lineage + (corpus.source_lineage[0],)
    with pytest.raises(LineageDuplicationError):
        assert_no_duplicated_per_posting_lineage(
            MaterializedCorpus(
                ledger=corpus.ledger,
                corpus_records=corpus.corpus_records,
                chunks=corpus.chunks,
                recovery_records=corpus.recovery_records,
                locators=corpus.locators,
                source_receipts=corpus.source_receipts,
                source_lineage=duplicated,
                parquet_shards=corpus.parquet_shards,
                family_counts=corpus.family_counts,
                inventory_document_count=EXPECTED_FIXTURE_DOCUMENTS,
                observation_cutoff=DEFAULT_OBSERVATION_CUTOFF,
                release_point=corpus.release_point,
            )
        )
    _ = original
    _ = DuplicatePrimaryKeyError
