"""Unit tests for canonical state-law corpus materialization (LCR-024).

Acceptance:

* Every source item and row has exactly one disposition.
* Admitted rows have complete official provenance and non-placeholder text.
* Combined count equals the deduped union of 51 admitted shards (compact
  2-statute receipts unless a receipt says otherwise).
* Tests are hermetic: no network, no Hub upload, no tokens.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    CANONICAL_COUNT_FAMILIES,
    DEFAULT_RELEASE_POINT,
    DEFAULT_STATUTES_PER_SHARD,
    FIXTURE_SCHEMA_VERSION,
    GOAL_ID,
    PARSER_VERSION,
    PRODUCER,
    REPORT_SCHEMA,
    SCHEMA_VERSION,
    TASK_ID,
    CombinedCountError,
    DispositionError,
    IncompleteIdentityError,
    PlaceholderTextError,
    RecoveryContaminationError,
    RowDisposition,
    SourceItemDisposition,
    StateLawsCorpusError,
    StateLawsCorpusMaterializer,
    assess_text_quality,
    assert_admitted_rows_complete,
    assert_combined_count_equals_deduped_union,
    assert_every_row_has_exactly_one_disposition,
    assert_every_source_item_has_exactly_one_disposition,
    assert_no_secrets_or_home_paths,
    assert_recovery_quarantine_excluded_from_canonical_counts,
    build_corpus_admission_report,
    build_explicit_statute_row,
    classify_source_row,
    default_report_path,
    expected_compact_admitted_count,
    fixture_statute_text,
    looks_placeholder,
    materialize_state_laws_corpus,
    scrub_local_path,
    scrub_local_paths_in_text,
    stream_verified_state_outputs,
    write_admission_report,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    AdmissionStatus,
    CorpusRecord,
    RecoveryRecord,
    SourceAuthorityClass,
)


@pytest.fixture(scope="module")
def corpus():
    return materialize_state_laws_corpus()


@pytest.fixture(scope="module")
def expected_count() -> int:
    return expected_compact_admitted_count()


# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "state-laws-corpus-v1"
    assert FIXTURE_SCHEMA_VERSION == "state-laws-admission-ledger-v1"
    assert REPORT_SCHEMA == "ipfs_datasets_py/legal-corpora-reindex-admission@1"
    assert TASK_ID == "LCR-024"
    assert GOAL_ID == "LCR-G030"
    assert PRODUCER == "state_laws_corpus.py"
    assert PARSER_VERSION == "state-laws-parser/v2"
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert len(DEFAULT_RELEASE_POINT) == 64
    assert DEFAULT_RELEASE_POINT != "latest"
    for family in ("corpus", "bm25", "vector", "graph"):
        assert family in CANONICAL_COUNT_FAMILIES


def test_mutable_release_point_rejected() -> None:
    with pytest.raises(StateLawsCorpusError):
        StateLawsCorpusMaterializer(release_point="latest")


# ---------------------------------------------------------------------------
# Compact receipts stream to 51 shards
# ---------------------------------------------------------------------------


def test_stream_yields_exact_51_shards_including_dc() -> None:
    shards = list(stream_verified_state_outputs())
    codes = [shard.jurisdiction for shard in shards]
    assert len(shards) == EXPECTED_JURISDICTION_COUNT
    assert len(set(codes)) == EXPECTED_JURISDICTION_COUNT
    assert "DC" in codes
    assert set(codes) == set(CANONICAL_JURISDICTION_ORDER)
    for shard in shards:
        expected = shard.statutes_count or DEFAULT_STATUTES_PER_SHARD
        fetched = sum(
            1
            for item in shard.source_items
            if item.disposition is SourceItemDisposition.FETCHED
        )
        assert fetched == expected
        assert len(shard.candidate_rows) == expected


def test_expected_compact_count_is_deduped_union_of_shards() -> None:
    total = expected_compact_admitted_count()
    shards = list(stream_verified_state_outputs())
    assert total == sum(shard.statutes_count for shard in shards)
    assert total == EXPECTED_JURISDICTION_COUNT * DEFAULT_STATUTES_PER_SHARD


# ---------------------------------------------------------------------------
# Every source item and row has exactly one disposition
# ---------------------------------------------------------------------------


def test_every_source_item_and_row_has_exactly_one_disposition(corpus) -> None:
    row_map = assert_every_row_has_exactly_one_disposition(corpus.ledger)
    item_map = assert_every_source_item_has_exactly_one_disposition(corpus.source_items)
    assert len(row_map) == len(corpus.ledger)
    assert len(item_map) == len(corpus.source_items)
    assert len(row_map) == len(set(row_map))
    assert len(item_map) == len(set(item_map))


def test_duplicate_row_id_rejected() -> None:
    rows = [
        build_explicit_statute_row("OR", "123.456", row_id="dup-row"),
        build_explicit_statute_row("OR", "123.457", row_id="dup-row"),
    ]
    with pytest.raises(DispositionError):
        materialize_state_laws_corpus(rows, from_cohort_receipts=False)


def test_duplicate_ledger_disposition_rejected() -> None:
    entries = [
        {"row_id": "same", "disposition": "admitted"},
        {"row_id": "same", "disposition": "quarantined"},
    ]
    with pytest.raises(DispositionError):
        assert_every_row_has_exactly_one_disposition(entries)


# ---------------------------------------------------------------------------
# Admitted rows: provenance + non-placeholder text + combined count
# ---------------------------------------------------------------------------


def test_admitted_rows_have_complete_official_provenance(corpus, expected_count) -> None:
    assert len(corpus.admitted_rows) == expected_count
    assert_admitted_rows_complete(corpus.admitted_rows)
    for row in corpus.admitted_rows:
        record = CorpusRecord.from_mapping(row)
        assert record.admission_status is AdmissionStatus.ADMITTED
        assert record.entry_cid
        assert record.legal_id.startswith("state:")
        assert record.source_cid
        assert record.official_source_url.lower().startswith(("http://", "https://"))
        assert record.acquisition_receipt_id
        assert record.parser_version == PARSER_VERSION
        assert record.source_checksum
        assert record.release_point
        assert record.verification_result.value == "verified"
        assert record.source_authority_class is SourceAuthorityClass.OFFICIAL
        assert record.jurisdiction in CANONICAL_JURISDICTION_ORDER
        quality = assess_text_quality(record.text)
        assert quality.contaminated is False
        assert quality.statutory_signal is True
        assert quality.placeholder_detected is False
        assert "shall" in record.text.lower()


def test_combined_count_equals_deduped_union_of_51_shards(corpus, expected_count) -> None:
    assert_combined_count_equals_deduped_union(corpus)
    assert corpus.combined_admitted_count() == expected_count
    assert len(corpus.default_jurisdiction_codes()) == EXPECTED_JURISDICTION_COUNT
    assert corpus.default_jurisdiction_codes()[-1] == "DC"
    assert corpus.default_jurisdiction_codes().count("DC") == 1
    per_counts = [item for item in corpus.shard_admitted_counts.values()]
    assert sum(per_counts) == expected_count
    legal_ids = [row["legal_id"] for row in corpus.admitted_rows]
    assert len(legal_ids) == len(set(legal_ids))


def test_dc_is_admitted_with_two_statutes(corpus) -> None:
    dc_rows = [row for row in corpus.admitted_rows if row["jurisdiction"] == "DC"]
    assert len(dc_rows) == 2
    for row in dc_rows:
        assert "dc-official-code" in row["legal_id"]
        assert row["official_source_url"].startswith("https://code.dccouncil.gov")


# ---------------------------------------------------------------------------
# Dedup current vs history, quarantine, recovery
# ---------------------------------------------------------------------------


def test_logical_duplicate_does_not_inflate_combined_count(corpus, expected_count) -> None:
    original = dict(corpus.admitted_rows[0])
    extra = build_explicit_statute_row(
        original["jurisdiction"],
        original["section"],
        title=original.get("title"),
        chapter=original.get("chapter"),
        text=original["text"],
        official_source_url=original["official_source_url"],
        code_family=original["code_family"],
        row_id="extra-logical-duplicate",
    )
    mixed = materialize_state_laws_corpus(extra_rows=[extra])
    assert mixed.combined_admitted_count() == expected_count
    assert mixed.disposition_counts[RowDisposition.DUPLICATE.value] >= 1
    assert_combined_count_equals_deduped_union(mixed)


def test_changed_text_version_archives_history_and_keeps_one_current(
    corpus, expected_count
) -> None:
    original = dict(corpus.admitted_rows[0])
    extra = build_explicit_statute_row(
        original["jurisdiction"],
        original["section"],
        title=original.get("title"),
        chapter=original.get("chapter"),
        text=original["text"] + " Amended current text shall supersede the prior version.",
        official_source_url=original["official_source_url"],
        code_family=original["code_family"],
        row_id="extra-changed-text",
    )
    mixed = materialize_state_laws_corpus(extra_rows=[extra])
    assert mixed.combined_admitted_count() == expected_count
    assert mixed.disposition_counts[RowDisposition.HISTORY.value] >= 1
    assert len(mixed.history_rows) >= 1
    assert_recovery_quarantine_excluded_from_canonical_counts(mixed)
    for family in ("corpus", "bm25", "vector", "graph"):
        assert mixed.family_counts.to_dict()[family] == expected_count


def test_explicit_history_kind_is_isolated_from_canonical_counts(expected_count) -> None:
    extra = build_explicit_statute_row(
        "OR",
        "123.456",
        kind="history",
        row_id="extra-history-kind",
        official_source_url="https://www.oregonlegislature.gov/bills_laws/ors/ors123.html",
        code_family="oregon-revised-statutes",
    )
    mixed = materialize_state_laws_corpus(extra_rows=[extra])
    assert mixed.combined_admitted_count() == expected_count
    assert mixed.disposition_counts[RowDisposition.HISTORY.value] >= 1
    assert_recovery_quarantine_excluded_from_canonical_counts(mixed)


def test_placeholder_and_secondary_rows_are_quarantined(expected_count) -> None:
    placeholder = build_explicit_statute_row(
        "CA",
        "99",
        text="Lorem ipsum dolor sit amet. Placeholder text. Coming soon.",
        row_id="extra-placeholder",
        official_source_url="https://leginfo.legislature.ca.gov/faces/codes.xhtml",
        code_family="california-codes",
    )
    secondary = build_explicit_statute_row(
        "NY",
        "1",
        row_id="extra-secondary",
        official_source_url="https://law.justia.com/codes/new-york/1",
        source_authority_class="secondary",
        code_family="new-york-consolidated-laws",
    )
    mixed = materialize_state_laws_corpus(extra_rows=[placeholder, secondary])
    assert mixed.combined_admitted_count() == expected_count
    assert mixed.disposition_counts[RowDisposition.QUARANTINED.value] >= 2
    for row in mixed.quarantine_rows:
        record = RecoveryRecord.from_mapping(row)
        assert record.admission_status is not AdmissionStatus.ADMITTED
    assert_recovery_quarantine_excluded_from_canonical_counts(mixed)


def test_recovery_rows_cannot_enter_search_families(expected_count) -> None:
    extra = {
        "row_id": "extra-recovery-workflow",
        "is_recovery": True,
        "jurisdiction": "WA",
        "source_path": "/home/operator/workspaces/state-laws-recovery/raw/job-1/dump.json",
        "reason": "heterogeneous recovery workflow",
    }
    mixed = materialize_state_laws_corpus(extra_rows=[extra])
    assert mixed.combined_admitted_count() == expected_count
    assert mixed.disposition_counts[RowDisposition.RECOVERY.value] >= 1
    dumped = json.dumps([row for row in mixed.recovery_rows])
    assert "/home/" not in dumped
    for row in mixed.recovery_rows:
        record = RecoveryRecord.from_mapping(row)
        assert record.admission_status is not AdmissionStatus.ADMITTED
        if record.source_path is not None:
            assert not record.source_path.startswith("/")
    assert_recovery_quarantine_excluded_from_canonical_counts(mixed)


def test_unknown_jurisdiction_is_quarantined(expected_count) -> None:
    extra = {
        "row_id": "extra-unsupported-pr",
        "jurisdiction": "PR",
        "section": "1",
        "code_family": "laws-of-puerto-rico",
        "text": "Puerto Rico is not in the exact 51-set and shall not be admitted.",
        "official_source_url": "https://www.justia.com/codes/puerto-rico/",
    }
    mixed = materialize_state_laws_corpus(extra_rows=[extra])
    assert mixed.combined_admitted_count() == expected_count
    assert mixed.disposition_counts[RowDisposition.QUARANTINED.value] >= 1


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def test_classify_placeholder_and_secondary() -> None:
    dirty = "Skip to main content. Cookie banner. Lorem ipsum. All rights reserved."
    assert looks_placeholder(dirty) is True
    assert assess_text_quality(dirty).contaminated is True
    assert classify_source_row({"text": dirty, "jurisdiction": "CA"}) is (
        RowDisposition.QUARANTINED
    )
    clean = fixture_statute_text("OR", "1")
    assert looks_placeholder(clean) is False
    assert (
        classify_source_row(
            {
                "jurisdiction": "OR",
                "section": "1",
                "text": clean,
                "official_source_url": "https://www.oregonlegislature.gov/x",
            }
        )
        is RowDisposition.ADMITTED
    )
    assert (
        classify_source_row(
            {
                "jurisdiction": "CA",
                "official_source_url": "https://codes.findlaw.com/ca/1",
                "text": clean,
            }
        )
        is RowDisposition.QUARANTINED
    )
    assert classify_source_row({"is_recovery": True}) is RowDisposition.RECOVERY
    assert classify_source_row({"kind": "history", "jurisdiction": "OR"}) is (
        RowDisposition.HISTORY
    )


def test_incomplete_admitted_row_fails_closed() -> None:
    rows = [
        {
            "row_id": "broken-admit",
            "disposition": "admitted",
            "jurisdiction": "OR",
            "text": fixture_statute_text("OR", "1"),
        }
    ]
    result = materialize_state_laws_corpus(rows, from_cohort_receipts=False)
    assert result.disposition_counts[RowDisposition.ADMITTED.value] == 0
    assert result.disposition_counts[RowDisposition.QUARANTINED.value] == 1


def test_assert_admitted_rows_complete_rejects_placeholder() -> None:
    with pytest.raises((IncompleteIdentityError, PlaceholderTextError, Exception)):
        assert_admitted_rows_complete(
            [
                {
                    "entry_cid": "a" * 64,
                    "legal_id": "state:OR:oregon-revised-statutes:1",
                    "source_cid": "b" * 64,
                    "jurisdiction": "OR",
                    "code_family": "oregon-revised-statutes",
                    "section": "1",
                    "admission_status": "admitted",
                    "admission_reason": "bad",
                    "release_point": DEFAULT_RELEASE_POINT,
                    "source_checksum": "c" * 64,
                    "verification_result": "verified",
                    "acquisition_time": "2026-08-10T12:00:00Z",
                    "official_source_url": "https://www.oregonlegislature.gov/x",
                    "acquisition_receipt_id": "scrape-or",
                    "parser_version": PARSER_VERSION,
                    "text": "lorem ipsum placeholder",
                    "schema_version": "state-laws-sparse-graphrag-release-schema-v2",
                }
            ]
        )


# ---------------------------------------------------------------------------
# Path scrubbing / hermetic report
# ---------------------------------------------------------------------------


def test_scrub_absolute_paths() -> None:
    assert "recovery" in (scrub_local_path("/tmp/recovery/raw-1.json") or "")
    cleaned = scrub_local_paths_in_text("failed at /home/operator/secret/cache.json")
    assert "/home/" not in cleaned
    assert "[scrubbed-local-path]" in cleaned


def test_admission_report_is_hermetic_and_matches_acceptance(corpus, tmp_path: Path) -> None:
    report = build_corpus_admission_report(corpus)
    assert report["task_id"] == TASK_ID
    assert report["goal_id"] == GOAL_ID
    assert report["schema"] == REPORT_SCHEMA
    assert report["status"] == "pass"
    assert report["acceptance"]["every_source_item_has_one_disposition"] is True
    assert report["acceptance"]["every_row_has_one_disposition"] is True
    assert report["acceptance"]["admitted_rows_have_complete_official_provenance"] is True
    assert report["acceptance"]["admitted_rows_non_placeholder_text"] is True
    assert report["acceptance"]["combined_count_equals_deduped_union"] is True
    assert report["acceptance"]["exact_51"] is True
    assert report["acceptance"]["includes_dc"] is True
    assert report["acceptance"]["no_hub_upload"] is True
    assert report["acceptance"]["no_token_material"] is True
    assert report["combined"]["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert report["combined"]["admitted_row_count"] == corpus.combined_admitted_count()
    dumped = json.dumps(report)
    assert "/home/" not in dumped
    assert "hf_" not in dumped
    assert "Bearer " not in dumped
    assert_no_secrets_or_home_paths(report)
    target = tmp_path / "admission.json"
    write_admission_report(target, corpus=corpus)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["combined"]["admitted_row_count"] == report["combined"]["admitted_row_count"]
    for item in loaded["inputs"]["cohort_receipts"]:
        assert not str(item["path"]).startswith("/")
        assert str(item["path"]).startswith("docs/reports/")


def test_committed_admission_report_round_trip(corpus) -> None:
    path = default_report_path()
    write_admission_report(path, corpus=corpus)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["task_id"] == "LCR-024"
    assert payload["combined"]["admitted_row_count"] == corpus.combined_admitted_count()
    assert payload["combined"]["jurisdiction_count"] == 51
    assert "DC" in payload["jurisdictions"]
    dumped = path.read_text(encoding="utf-8")
    assert "/home/" not in dumped
    assert "hf_" not in dumped


def test_recovery_contamination_assertion() -> None:
    with pytest.raises(RecoveryContaminationError):
        class _Fake:
            admitted_rows = [object()] * 5
            history_rows = [object()] * 2
            recovery_rows = [object()] * 1
            quarantine_rows = []
            family_counts = type(
                "C",
                (),
                {"to_dict": staticmethod(lambda: {
                    "corpus": 8, "bm25": 8, "vector": 8, "graph": 8,
                    "recovery": 3, "quarantine": 0,
                })},
            )()
        assert_recovery_quarantine_excluded_from_canonical_counts(_Fake())


def test_combined_count_mismatch_detected(corpus) -> None:
    class _Fake:
        admitted_rows = [{"legal_id": "a"}, {"legal_id": "a"}]
        shard_admitted_counts = {"AL": 2}

        def combined_admitted_count(self) -> int:
            return 2

    with pytest.raises(CombinedCountError):
        assert_combined_count_equals_deduped_union(_Fake())
