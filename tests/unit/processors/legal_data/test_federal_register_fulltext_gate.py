"""Unit tests for Federal full-text attempt exhaustion and sealing (LCR-085).

Acceptance: METADATA_ONLY, ABSTRACT_ONLY, MISSING_BODY_OFFICIAL, exclusion, or
quarantine cannot pass without an allowed reason and complete attempt evidence
proving every official alternative has authorized absence. Any available or
retrieved official body that is not fetched, response- and content-hash
verified from captured bytes, successfully parsed, and admitted as full text
remains unresolved/failed-final and blocks publication. Exact v2 identity,
zero-skew verifier time, and complete LCR-049 frontier are required.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_fulltext_gate import (
    ALLOWED_NON_BODY_REASONS,
    AUTHORIZING_IDENTITY,
    CANONICAL_FULLTEXT_FRONTIER,
    FIXTURE_SCHEMA_VERSION,
    FIXTURE_VERIFIER_CLOCK_UTC,
    GOAL_ID,
    MODE_LIVE,
    PRODUCER,
    PROGRAM_ID,
    REQUIRED_FULL_TEXT_AUTHORITIES,
    SCHEMA_VERSION,
    TASK_ID,
    ZERO_FUTURE_SKEW,
    AllowedNonBodyReason,
    AttemptStatus,
    DispositionAdmissionError,
    ExhaustionError,
    FailedFinalAdmissionError,
    FailureKind,
    FulltextAttemptReceipt,
    FulltextDisposition,
    GateVerdict,
    MissingHashError,
    ParserResult,
    SealTimestampError,
    UnresolvedBodyError,
    assert_fixture_expectations,
    assert_fulltext_admission,
    build_default_fulltext_fixture_payload,
    default_fulltext_fixture_path,
    evaluate_fixture_case,
    evaluate_fulltext_attempt_receipt,
    evaluate_fulltext_fixture,
    example_closed_fulltext_receipt,
    example_exhausted_non_body_document,
    example_full_text_document,
    expand_fulltext_fixture_cases,
    fixture_verifier_now,
    load_fulltext_fixture_payload,
    public_helper_rejects_skew_override,
    require_strict_utc_z_timestamp,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    DEFAULT_OBSERVATION_CUTOFF,
    OFFICIAL_FULL_TEXT_SOURCES,
    MutableCutoffError,
    OfficialAuthority,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "federal_register_fulltext_attempt_receipts.json"
)

_NOW = fixture_verifier_now()


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_fulltext_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def fixture_cases(fixture_payload: dict) -> list[dict]:
    return expand_fulltext_fixture_cases(fixture_payload)


# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "federal-register-fulltext-gate-v2"
    assert FIXTURE_SCHEMA_VERSION == "federal-register-fulltext-attempt-receipts-v2"
    assert TASK_ID == "LCR-085"
    assert GOAL_ID == "LCR-G147"
    assert PRODUCER == "federal_register_fulltext_gate.py@2"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert AUTHORIZING_IDENTITY["mode"] == MODE_LIVE
    assert ZERO_FUTURE_SKEW.total_seconds() == 0
    assert FIXTURE_VERIFIER_CLOCK_UTC == "2026-08-10T12:00:00Z"
    assert DEFAULT_OBSERVATION_CUTOFF == "2026-08-10T00:00:00Z"
    assert fixture_verifier_now().year == 2026
    assert public_helper_rejects_skew_override()


def test_required_authorities_and_frontier() -> None:
    assert OfficialAuthority.FEDERAL_REGISTER in REQUIRED_FULL_TEXT_AUTHORITIES
    assert OfficialAuthority.GOVINFO in REQUIRED_FULL_TEXT_AUTHORITIES
    assert "FederalRegister.gov" in OFFICIAL_FULL_TEXT_SOURCES
    assert "GovInfo" in OFFICIAL_FULL_TEXT_SOURCES
    assert AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value in ALLOWED_NON_BODY_REASONS
    assert CANONICAL_FULLTEXT_FRONTIER == (
        (OfficialAuthority.FEDERAL_REGISTER, "html"),
        (OfficialAuthority.GOVINFO, "pdf"),
    )


def test_strict_utc_z_timestamp_rules() -> None:
    assert require_strict_utc_z_timestamp("2026-08-10T00:00:00Z") == (
        "2026-08-10T00:00:00Z"
    )
    with pytest.raises(SealTimestampError):
        require_strict_utc_z_timestamp("")
    with pytest.raises(SealTimestampError):
        require_strict_utc_z_timestamp(None)
    with pytest.raises(SealTimestampError):
        require_strict_utc_z_timestamp("2026-08-10T00:00:00+00:00")
    with pytest.raises(SealTimestampError):
        require_strict_utc_z_timestamp("2026-08-10T00:00:00")
    with pytest.raises(SealTimestampError):
        require_strict_utc_z_timestamp("not-a-timestamp")


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_fulltext_fixture_is_present_and_compact() -> None:
    assert _FIXTURE_PATH.is_file()
    assert default_fulltext_fixture_path().name == (
        "federal_register_fulltext_attempt_receipts.json"
    )
    size = _FIXTURE_PATH.stat().st_size
    assert size < 96_000
    on_disk = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert on_disk["task_id"] == TASK_ID
    assert on_disk["goal_id"] == GOAL_ID
    assert on_disk["observation_cutoff"] == DEFAULT_OBSERVATION_CUTOFF
    assert on_disk["verifier_clock"] == FIXTURE_VERIFIER_CLOCK_UTC
    assert on_disk.get("generator") == "build_default_fulltext_fixture_payload"
    payload = load_fulltext_fixture_payload(_FIXTURE_PATH)
    assert "cases" in payload
    case_ids = {case["case_id"] for case in payload["cases"]}
    required = {
        "full_text_and_metadata_ok",
        "abstract_only_exhausted_ok",
        "missing_body_exhausted_ok",
        "excluded_exhausted_ok",
        "quarantined_exhausted_ok",
        "incomplete_exhaustion",
        "missing_allowed_reason",
        "body_not_admitted",
        "exclusion_erases_failure",
        "failed_final",
        "pending",
        "missing_hash",
        "missing_cutoff_sealed_at",
        "malformed_timestamp",
        "non_utc_timestamp",
        "mutable_cutoff",
        "future_cutoff",
        "cutoff_seal_after_observation",
        "receipt_before_last_attempt",
        "timestamp_after_verifier",
        "hashless_antibot_pair",
        "skew_four_minute_fifty_nine",
        "fixture_mode_non_authorizing",
    }
    assert required.issubset(case_ids)
    if "case_ids" in on_disk:
        assert set(on_disk["case_ids"]) == case_ids


def test_default_builder_matches_on_disk_case_ids() -> None:
    built = build_default_fulltext_fixture_payload()
    on_disk = load_fulltext_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["task_id"] == on_disk["task_id"]
    built_ids = [c["case_id"] for c in built["cases"]]
    disk_ids = [c["case_id"] for c in on_disk["cases"]]
    assert built_ids == disk_ids


def test_fixture_cases_expand_and_meet_expectations(
    fixture_cases: list[dict],
) -> None:
    assert len(fixture_cases) >= 20
    results = evaluate_fulltext_fixture(path=_FIXTURE_PATH, now=_NOW)
    assert all(row["passed"] for row in results), results
    assert_fixture_expectations(path=_FIXTURE_PATH, now=_NOW)


# ---------------------------------------------------------------------------
# Closed receipt passes
# ---------------------------------------------------------------------------


def test_closed_receipt_passes_gate() -> None:
    receipt = example_closed_fulltext_receipt()
    result = evaluate_fulltext_attempt_receipt(receipt, now=_NOW)
    assert result.passed, result.findings
    assert result.verdict is GateVerdict.PASS
    assert result.failed_final_count == 0
    assert result.pending_count == 0
    assert result.admitted_full_text_count >= 1
    closed = assert_fulltext_admission(receipt, now=_NOW)
    assert closed.passed


def test_receipt_dataclass_round_trip() -> None:
    raw = example_closed_fulltext_receipt()
    receipt = FulltextAttemptReceipt.from_mapping(raw)
    assert receipt.observation_cutoff == DEFAULT_OBSERVATION_CUTOFF
    assert receipt.task_id == TASK_ID
    assert receipt.producer == PRODUCER
    assert receipt.mode == MODE_LIVE
    assert len(receipt.documents) == 2
    result = evaluate_fulltext_attempt_receipt(receipt, now=_NOW)
    assert result.passed, result.findings
    again = evaluate_fulltext_attempt_receipt(receipt.to_dict(), now=_NOW)
    assert again.passed


def test_non_body_dispositions_pass_with_exhaustion_and_reason() -> None:
    for disposition, reason in (
        (
            FulltextDisposition.METADATA_ONLY.value,
            AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value,
        ),
        (
            FulltextDisposition.ABSTRACT_ONLY.value,
            AllowedNonBodyReason.OFFICIAL_ABSTRACT_ONLY.value,
        ),
        (
            FulltextDisposition.MISSING_BODY_OFFICIAL.value,
            AllowedNonBodyReason.OFFICIAL_BODY_UNAVAILABLE.value,
        ),
        (
            FulltextDisposition.EXCLUDED.value,
            AllowedNonBodyReason.RIGHTS_OR_SCOPE_EXCLUSION.value,
        ),
        (
            FulltextDisposition.QUARANTINED.value,
            AllowedNonBodyReason.CONTENT_QUARANTINE.value,
        ),
    ):
        raw = example_closed_fulltext_receipt(receipt_id=f"ok-{disposition}")
        raw["documents"] = [
            example_exhausted_non_body_document(
                document_number="2026-04700",
                disposition=disposition,
                allowed_reason=reason,
            )
        ]
        result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
        assert result.passed, (disposition, result.failure_kinds, result.findings)


# ---------------------------------------------------------------------------
# Acceptance: reject each failure mode
# ---------------------------------------------------------------------------


def test_rejects_incomplete_authority_exhaustion() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-no-govinfo")
    doc = example_exhausted_non_body_document(document_number="2026-04710")
    doc["attempts"] = [doc["attempts"][0]]
    raw["documents"] = [doc]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.INCOMPLETE_EXHAUSTION.value in result.failure_kinds
    with pytest.raises(ExhaustionError):
        assert_fulltext_admission(raw, now=_NOW)


def test_rejects_non_body_without_allowed_reason() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-no-reason")
    doc = example_exhausted_non_body_document(document_number="2026-04711")
    doc.pop("allowed_reason", None)
    raw["documents"] = [doc]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.MISSING_ALLOWED_REASON.value in result.failure_kinds
    with pytest.raises(DispositionAdmissionError):
        assert_fulltext_admission(raw, now=_NOW)


def test_rejects_usable_body_not_admitted() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-body-open")
    doc = example_full_text_document(document_number="2026-04712")
    doc["disposition"] = FulltextDisposition.METADATA_ONLY.value
    doc["allowed_reason"] = AllowedNonBodyReason.OFFICIAL_METADATA_ONLY.value
    doc["attempts"][0]["status"] = AttemptStatus.PARSED.value
    doc.pop("admitted_content_hash", None)
    doc.pop("admitted_body_bytes", None)
    raw["documents"] = [doc]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert (
        FailureKind.BODY_NOT_ADMITTED.value in result.failure_kinds
        or FailureKind.EXCLUSION_ERASES_FAILURE.value in result.failure_kinds
    )
    with pytest.raises(UnresolvedBodyError):
        assert_fulltext_admission(raw, now=_NOW)


def test_exclusion_cannot_erase_unresolved_body() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-excl-erase")
    doc = example_full_text_document(document_number="2026-04713")
    doc["disposition"] = FulltextDisposition.EXCLUDED.value
    doc["allowed_reason"] = AllowedNonBodyReason.RIGHTS_OR_SCOPE_EXCLUSION.value
    doc["attempts"][0]["status"] = AttemptStatus.FETCHED.value
    doc.pop("admitted_content_hash", None)
    doc.pop("admitted_body_bytes", None)
    raw["documents"] = [doc]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.EXCLUSION_ERASES_FAILURE.value in result.failure_kinds
    with pytest.raises(UnresolvedBodyError):
        assert_fulltext_admission(raw, now=_NOW)


def test_rejects_failed_final() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-failed-final")
    raw["documents"] = [
        {
            "document_number": "2026-04714",
            "publication_date": "2026-03-27",
            "disposition": FulltextDisposition.FAILED_FINAL.value,
            "attempts": [
                {
                    "attempt_id": "2026-04714-fr-html",
                    "authority": OfficialAuthority.FEDERAL_REGISTER.value,
                    "content_format": "html",
                    "url": "https://www.federalregister.gov/documents/2026-04714",
                    "observed_at": "2026-08-10T02:00:00Z",
                    "status": AttemptStatus.FAILED.value,
                    "response_hash": "1" * 64,
                    "retry_count": 3,
                    "terminal_reason": "permanent_error",
                    "parser_result": ParserResult.PARSE_ERROR.value,
                    "body_available": False,
                    "body_usable": False,
                    "http_status": 500,
                    "media_type": "text/html",
                },
                example_full_text_document(document_number="2026-04714")["attempts"][1],
            ],
        }
    ]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.FAILED_FINAL.value in result.failure_kinds
    with pytest.raises(FailedFinalAdmissionError):
        assert_fulltext_admission(raw, now=_NOW)


def test_rejects_pending() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-pending")
    raw["documents"] = [
        {
            "document_number": "2026-04715",
            "publication_date": "2026-03-28",
            "disposition": FulltextDisposition.PENDING.value,
            "attempts": [
                {
                    "attempt_id": "2026-04715-fr-html",
                    "authority": OfficialAuthority.FEDERAL_REGISTER.value,
                    "content_format": "html",
                    "url": "https://www.federalregister.gov/documents/2026-04715",
                    "observed_at": "2026-08-10T02:00:00Z",
                    "status": AttemptStatus.PENDING.value,
                    "retry_count": 0,
                    "terminal_reason": "",
                    "parser_result": ParserResult.NOT_RUN.value,
                    "body_available": False,
                    "body_usable": False,
                    "media_type": "text/html",
                },
                example_full_text_document(document_number="2026-04715")["attempts"][1],
            ],
        }
    ]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.PENDING.value in result.failure_kinds
    with pytest.raises(FailedFinalAdmissionError):
        assert_fulltext_admission(raw, now=_NOW)


def test_rejects_missing_hash() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-missing-hash")
    doc = example_full_text_document(document_number="2026-04716")
    doc["attempts"][0].pop("response_hash", None)
    doc["attempts"][0].pop("content_hash", None)
    doc["admitted_content_hash"] = None
    raw["documents"] = [doc]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.MISSING_HASH.value in result.failure_kinds
    with pytest.raises(MissingHashError):
        assert_fulltext_admission(raw, now=_NOW)


def test_rejects_missing_cutoff_sealed_at() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-missing-seal")
    raw["cutoff_sealed_at"] = ""
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.MISSING_TIMESTAMP.value in result.failure_kinds
    with pytest.raises(SealTimestampError):
        assert_fulltext_admission(raw, now=_NOW)


def test_rejects_malformed_timestamp() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-malformed")
    raw["receipt_created_at"] = "not-a-timestamp"
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.MALFORMED_TIMESTAMP.value in result.failure_kinds


def test_rejects_non_utc_timestamp() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-non-utc")
    raw["receipt_created_at"] = "2026-08-10T11:00:00+00:00"
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.NON_UTC_TIMESTAMP.value in result.failure_kinds


def test_rejects_mutable_cutoff() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-mutable")
    raw["observation_cutoff"] = "latest"
    with pytest.raises(MutableCutoffError):
        FulltextAttemptReceipt.from_mapping(raw)
    case = {
        "case_id": "t-mutable",
        "expected_status": "fail",
        "expected_kinds": ["mutable_cutoff"],
        "receipt": raw,
    }
    result = evaluate_fixture_case(case, now=_NOW)
    assert not result.passed
    assert FailureKind.MUTABLE_CUTOFF.value in result.failure_kinds


def test_rejects_future_cutoff() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-future")
    raw["observation_cutoff"] = "2026-12-31T00:00:00Z"
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.FUTURE_CUTOFF.value in result.failure_kinds


def test_rejects_cutoff_sealed_after_first_observation() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-seal-after")
    raw["cutoff_sealed_at"] = "2026-08-10T03:00:00Z"
    raw["documents"] = [
        example_full_text_document(fr_observed_at="2026-08-10T01:00:00Z")
    ]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.CUTOFF_SEAL_AFTER_OBSERVATION.value in result.failure_kinds
    with pytest.raises(SealTimestampError):
        assert_fulltext_admission(raw, now=_NOW)


def test_rejects_receipt_created_before_last_attempt() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-receipt-before")
    raw["receipt_created_at"] = "2026-08-10T01:30:00Z"
    raw["documents"] = [
        example_full_text_document(fr_observed_at="2026-08-10T02:00:00Z")
    ]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.RECEIPT_BEFORE_LAST_ATTEMPT.value in result.failure_kinds
    with pytest.raises(SealTimestampError):
        assert_fulltext_admission(raw, now=_NOW)


def test_rejects_timestamp_after_verifier_clock() -> None:
    raw = example_closed_fulltext_receipt(receipt_id="t-after-clock")
    raw["receipt_created_at"] = "2026-08-10T18:00:00Z"
    raw["documents"] = [
        example_full_text_document(fr_observed_at="2026-08-10T01:00:00Z")
    ]
    result = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    assert not result.passed
    assert FailureKind.TIMESTAMP_AFTER_VERIFIER.value in result.failure_kinds
    with pytest.raises(SealTimestampError):
        assert_fulltext_admission(raw, now=_NOW)


def test_each_fixture_adversarial_case_fails_with_expected_kind(
    fixture_cases: list[dict],
) -> None:
    by_id = {case["case_id"]: case for case in fixture_cases}
    for case_id, expected_kind in (
        ("incomplete_exhaustion", "incomplete_exhaustion"),
        ("missing_allowed_reason", "missing_allowed_reason"),
        ("body_not_admitted", "exclusion_erases_failure"),
        ("exclusion_erases_failure", "exclusion_erases_failure"),
        ("failed_final", "failed_final"),
        ("pending", "pending"),
        ("missing_hash", "missing_hash"),
        ("missing_cutoff_sealed_at", "missing_timestamp"),
        ("malformed_timestamp", "malformed_timestamp"),
        ("non_utc_timestamp", "non_utc_timestamp"),
        ("mutable_cutoff", "mutable_cutoff"),
        ("future_cutoff", "future_cutoff"),
        ("cutoff_seal_after_observation", "cutoff_seal_after_observation"),
        ("receipt_before_last_attempt", "receipt_before_last_attempt"),
        ("timestamp_after_verifier", "timestamp_after_verifier"),
        ("hashless_antibot_pair", "non_exhaustive_negative"),
        ("skew_four_minute_fifty_nine", "timestamp_after_verifier"),
        ("fixture_mode_non_authorizing", "fixture_mode"),
    ):
        case = by_id[case_id]
        result = evaluate_fixture_case(case, now=_NOW)
        assert result.verdict is GateVerdict.FAIL, case_id
        assert expected_kind in result.failure_kinds, (
            case_id,
            result.failure_kinds,
            [f.message for f in result.findings],
        )


def test_pass_fixture_cases_pass(fixture_cases: list[dict]) -> None:
    for case_id in (
        "full_text_and_metadata_ok",
        "abstract_only_exhausted_ok",
        "missing_body_exhausted_ok",
        "excluded_exhausted_ok",
        "quarantined_exhausted_ok",
    ):
        case = next(c for c in fixture_cases if c["case_id"] == case_id)
        result = evaluate_fixture_case(case, now=_NOW)
        assert result.passed, (case_id, result.failure_kinds)


def test_deep_copy_mutation_does_not_affect_example() -> None:
    a = example_closed_fulltext_receipt()
    b = copy.deepcopy(a)
    b["documents"][0]["disposition"] = FulltextDisposition.FAILED_FINAL.value
    assert a["documents"][0]["disposition"] == FulltextDisposition.FULL_TEXT.value
    assert evaluate_fulltext_attempt_receipt(a, now=_NOW).passed


def test_omitted_verifier_time_fails() -> None:
    raw = example_closed_fulltext_receipt()
    result = evaluate_fulltext_attempt_receipt(raw, now=None)
    assert not result.passed
    assert FailureKind.MISSING_VERIFIER_TIME.value in result.failure_kinds
