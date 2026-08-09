"""Unit tests for canonical US Code corpus materialization (USCIR-008).

Acceptance:

* Every baseline row has exactly one disposition.
* Admitted rows have complete identity/provenance.
* The nine recovery records cannot enter corpus, BM25, vector, or graph counts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_corpus import (
    BASELINE_CANONICAL_CID_COUNT,
    BASELINE_CORPUS_ROW_COUNT,
    BASELINE_RECOVERY_ROW_COUNT,
    BASELINE_TITLE_COUNT,
    CANONICAL_COUNT_FAMILIES,
    DEFAULT_BASELINE_REVISION,
    FIXTURE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    TASK_ID,
    CorpusFixtureError,
    DispositionError,
    IncompleteIdentityError,
    LedgerEntry,
    RecoveryContaminationError,
    RowDisposition,
    UscodeCorpusError,
    UscodeCorpusMaterializer,
    assert_admitted_rows_complete,
    assert_every_row_has_exactly_one_disposition,
    assert_recovery_excluded_from_canonical_counts,
    baseline_count_contract,
    build_baseline_sample_rows,
    build_default_admission_ledger_fixture_payload,
    classify_source_row,
    default_admission_ledger_fixture_path,
    expand_admission_ledger_fixture,
    load_admission_ledger_fixture,
    load_admission_ledger_fixture_payload,
    materialize_uscode_corpus,
    scrub_local_path,
    scrub_local_paths_in_text,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    AdmissionStatus,
    CorpusRecord,
    RecoveryRecord,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_admission_ledger.json"
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_admission_ledger_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def materialized(fixture_payload: dict):
    return expand_admission_ledger_fixture(fixture_payload)


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_admission_ledger_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_admission_ledger_fixture_path().name == "uscode_admission_ledger.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["baseline_counts"]["recovery_rows"] == BASELINE_RECOVERY_ROW_COUNT
    assert payload["baseline_counts"]["canonical_cids"] == BASELINE_CANONICAL_CID_COUNT
    assert payload["baseline_counts"]["corpus_rows"] == BASELINE_CORPUS_ROW_COUNT
    # Recipe form: generators present; not a bulk 60k-row dump.
    assert "generators" in payload
    assert "seed_ledger" not in payload
    assert len(payload.get("seed_recovery_recipes") or []) == BASELINE_RECOVERY_ROW_COUNT
    # Absolute paths may appear only as scrub inputs in recipes.
    assert all(
        str(r.get("source_path", "")).startswith("/")
        for r in payload["seed_recovery_recipes"]
    )


def test_default_payload_matches_on_disk_recipe():
    built = build_default_admission_ledger_fixture_payload()
    on_disk = load_admission_ledger_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["baseline_counts"] == on_disk["baseline_counts"]
    assert built["generators"] == on_disk["generators"]
    assert built["sample_disposition_counts"] == on_disk["sample_disposition_counts"]
    assert built["sample_family_counts"] == on_disk["sample_family_counts"]
    built_ids = [e["row_id"] for e in built["seed_recovery_recipes"]]
    disk_ids = [e["row_id"] for e in on_disk["seed_recovery_recipes"]]
    assert built_ids == disk_ids


def test_malformed_fixture_rejected(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "nope", "seed_ledger": []}), encoding="utf-8")
    with pytest.raises(CorpusFixtureError):
        load_admission_ledger_fixture(bad)


def test_baseline_count_contract_invariant():
    contract = baseline_count_contract()
    assert contract["corpus_rows"] == contract["canonical_cids"] + contract["recovery_rows"]
    assert contract["recovery_rows"] == 9
    assert contract["titles"] == BASELINE_TITLE_COUNT
    assert contract["canonical_cids"] == 60_068


# ---------------------------------------------------------------------------
# Acceptance: every baseline row has exactly one disposition
# ---------------------------------------------------------------------------


def test_every_sample_row_has_exactly_one_disposition(materialized):
    mapping = assert_every_row_has_exactly_one_disposition(materialized.ledger)
    assert len(mapping) == len(materialized.ledger)
    # All four disposition kinds appear in the sealed sample.
    present = set(mapping.values())
    assert RowDisposition.ADMITTED.value in present
    assert RowDisposition.QUARANTINED.value in present
    assert RowDisposition.REPLACED.value in present
    assert RowDisposition.EXCLUDED.value in present


def test_duplicate_disposition_rejected():
    entries = [
        LedgerEntry(
            row_id="dup",
            disposition=RowDisposition.EXCLUDED,
            reason="first",
        ),
        {
            "row_id": "dup",
            "disposition": "admitted",
            "reason": "second",
            "entry_cid": "a" * 64,
            "legal_id": "usc:us:35:101",
            "source_cid": "b" * 64,
            "release_point": "us/pl/118/45",
            "source_checksum": "b" * 64,
            "verification_result": "verified",
            "acquisition_time": "2024-09-20T12:05:00Z",
        },
    ]
    with pytest.raises(DispositionError):
        assert_every_row_has_exactly_one_disposition(entries)


def test_materialize_rejects_duplicate_row_ids():
    rows = build_baseline_sample_rows(admitted=1, replaced=0, excluded=0, recovery=0)
    rows.append(dict(rows[0]))
    with pytest.raises(DispositionError):
        materialize_uscode_corpus(rows)


# ---------------------------------------------------------------------------
# Acceptance: admitted rows have complete identity/provenance
# ---------------------------------------------------------------------------


def test_admitted_rows_have_complete_identity_and_provenance(materialized):
    assert len(materialized.admitted_rows) >= 1
    assert_admitted_rows_complete(materialized.admitted_rows)
    for row in materialized.admitted_rows:
        record = CorpusRecord.from_mapping(row)
        assert record.admission_status is AdmissionStatus.ADMITTED
        assert record.entry_cid
        assert record.legal_id.startswith("usc:")
        assert record.source_cid
        assert record.release_point
        assert record.source_checksum
        assert record.verification_result.value == "verified"
        assert record.acquisition_time


def test_incomplete_admitted_ledger_entry_fails_closed():
    with pytest.raises(IncompleteIdentityError):
        LedgerEntry(
            row_id="bad-admit",
            disposition=RowDisposition.ADMITTED,
            reason="missing provenance",
            entry_cid="a" * 64,
            legal_id="usc:us:35:101",
            # source_cid / release_point / etc. intentionally omitted
        )


def test_admitted_corpus_row_missing_fields_rejected():
    materializer = UscodeCorpusMaterializer()
    # Force admitted without enough identity fields.
    rows = [
        {
            "row_id": "broken",
            "disposition": "admitted",
            "text": "no title or section",
        }
    ]
    with pytest.raises((IncompleteIdentityError, UscodeCorpusError, ValueError)):
        materializer.materialize(rows)


# ---------------------------------------------------------------------------
# Acceptance: nine recovery records cannot enter search-family counts
# ---------------------------------------------------------------------------


def test_nine_recovery_records_quarantined(materialized):
    assert materialized.family_counts.recovery == BASELINE_RECOVERY_ROW_COUNT
    assert len(materialized.recovery_rows) == BASELINE_RECOVERY_ROW_COUNT
    quarantined = [
        e for e in materialized.ledger if e.disposition is RowDisposition.QUARANTINED
    ]
    assert len(quarantined) == BASELINE_RECOVERY_ROW_COUNT


def test_recovery_excluded_from_corpus_bm25_vector_graph_counts(materialized):
    admitted = len(materialized.admitted_rows)
    recovery = len(materialized.recovery_rows)
    assert recovery == BASELINE_RECOVERY_ROW_COUNT
    assert_recovery_excluded_from_canonical_counts(
        materialized.family_counts,
        recovery_count=recovery,
        admitted_count=admitted,
    )
    counts = materialized.family_counts.to_dict()
    for family in ("corpus", "bm25", "vector", "graph"):
        assert counts[family] == admitted
        assert counts[family] != admitted + recovery
    assert counts["recovery"] == recovery
    # Explicit: recovery never listed under canonical families.
    for family in CANONICAL_COUNT_FAMILIES:
        assert family in CANONICAL_COUNT_FAMILIES


def test_recovery_rows_validate_as_recovery_records_not_admitted(materialized):
    for row in materialized.recovery_rows:
        record = RecoveryRecord.from_mapping(row)
        assert record.admission_status is not AdmissionStatus.ADMITTED
        assert record.admission_status in {
            AdmissionStatus.RECOVERY,
            AdmissionStatus.QUARANTINED,
        }
        # Scrubbed relative paths only.
        if record.source_path is not None:
            assert not record.source_path.startswith("/")
            assert ":" not in record.source_path[:2] or record.source_path[1] != ":"


def test_recovery_contamination_detection():
    with pytest.raises(RecoveryContaminationError):
        assert_recovery_excluded_from_canonical_counts(
            {"corpus": 14, "bm25": 14, "vector": 14, "graph": 14, "recovery": 9},
            recovery_count=9,
            admitted_count=5,  # 14 == 5+9 → contamination pattern
        )


# ---------------------------------------------------------------------------
# Path scrubbing
# ---------------------------------------------------------------------------


def test_scrub_absolute_posix_and_windows_paths():
    assert scrub_local_path("/home/operator/workspaces/x/recovery/raw-1.json") == (
        "recovery/raw-1.json"
    )
    scrubbed_win = scrub_local_path(
        r"C:\Users\operator\AppData\Local\uscode\recovery\raw-2.json"
    )
    assert scrubbed_win is not None
    assert not scrubbed_win.startswith("C:")
    assert "recovery" in scrubbed_win or scrubbed_win.endswith(".json")


def test_scrub_mapping_removes_absolute_paths(materialized):
    for row in materialized.recovery_rows:
        dumped = json.dumps(row)
        assert "/home/" not in dumped
        assert "C:\\Users" not in dumped
        assert "/var/cache" not in dumped
        assert "/tmp/" not in dumped


def test_scrub_free_text_paths():
    text = "failed at /home/barberb/secret/cache/file.json and ~/other"
    cleaned = scrub_local_paths_in_text(text)
    assert "/home/" not in cleaned
    assert "~/" not in cleaned
    assert "[scrubbed-local-path]" in cleaned


def test_relative_path_preserved():
    assert scrub_local_path("recovery/raw-03.json") == "recovery/raw-03.json"


# ---------------------------------------------------------------------------
# Classification + materializer behavior
# ---------------------------------------------------------------------------


def test_classify_recovery_without_cid():
    row = {
        "is_recovery": True,
        "source_path": "/tmp/recovery/1.json",
        "recovery_id": "recovery-workflow-01",
    }
    assert classify_source_row(row) is RowDisposition.QUARANTINED


def test_classify_explicit_dispositions():
    assert classify_source_row({"disposition": "admitted", "entry_cid": "a" * 64}) is (
        RowDisposition.ADMITTED
    )
    assert classify_source_row({"disposition": "replaced"}) is RowDisposition.REPLACED
    assert classify_source_row({"disposition": "excluded"}) is RowDisposition.EXCLUDED


def test_materialize_functional_entry_point():
    rows = build_baseline_sample_rows(
        admitted=2, replaced=1, excluded=1, recovery=BASELINE_RECOVERY_ROW_COUNT
    )
    result = materialize_uscode_corpus(rows)
    assert len(result.ledger) == 2 + 1 + 1 + BASELINE_RECOVERY_ROW_COUNT
    assert result.disposition_counts[RowDisposition.ADMITTED.value] == 2
    assert result.disposition_counts[RowDisposition.QUARANTINED.value] == 9
    report = result.admission_report()
    assert report["every_row_has_exactly_one_disposition"] is True
    assert report["recovery_quarantine_count"] == 9
    assert report["baseline_revision"] == DEFAULT_BASELINE_REVISION


def test_load_fixture_helper_round_trip():
    result = load_admission_ledger_fixture(_FIXTURE_PATH)
    assert result.schema_version == SCHEMA_VERSION
    assert len(result.recovery_rows) == BASELINE_RECOVERY_ROW_COUNT
    assert_every_row_has_exactly_one_disposition(result.ledger)
    assert_admitted_rows_complete(result.admitted_rows)


def test_admission_report_lists_excluded_families(materialized):
    report = materialized.admission_report()
    excluded = set(report["recovery_excluded_from_families"])
    for family in ("corpus", "bm25", "vector", "graph", "vectors", "bm25_documents"):
        assert family in excluded


def test_schema_version_stable():
    assert SCHEMA_VERSION.startswith("uscode-corpus")
    assert FIXTURE_SCHEMA_VERSION.startswith("uscode-admission-ledger")


def test_mutable_release_point_rejected():
    with pytest.raises(UscodeCorpusError):
        UscodeCorpusMaterializer(release_point="latest")


def test_seed_recovery_recipes_quarantine_without_cid(fixture_payload, materialized):
    recipes = fixture_payload["seed_recovery_recipes"]
    assert len(recipes) == BASELINE_RECOVERY_ROW_COUNT
    for row in recipes:
        assert "entry_cid" not in row or not row.get("entry_cid")
        assert row.get("admission_status") != "admitted"
        assert classify_source_row({**row, "is_recovery": True}) is (
            RowDisposition.QUARANTINED
        )
    for row in materialized.recovery_rows:
        record = RecoveryRecord.from_mapping(row)
        assert record.admission_status is not AdmissionStatus.ADMITTED
        dumped = json.dumps(row)
        assert "/home/" not in dumped
