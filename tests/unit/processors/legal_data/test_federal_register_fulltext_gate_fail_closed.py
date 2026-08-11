"""Fail-closed mutation matrix for Federal full-text gate (LCR-085).

Denies every demonstrated or adjacent exploit against exhaustion, byte binding,
identity, and verifier time. Public helpers share one evaluator with a
verifier-owned clock, fixed zero skew, and no tolerance override.
"""

from __future__ import annotations

import copy
import inspect
from datetime import timedelta
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_fulltext_gate import (
    AUTHORIZING_IDENTITY,
    GOAL_ID,
    IDENTITY_FIELDS,
    MODE_FIXTURE,
    MODE_LIVE,
    PRODUCER,
    PROGRAM_ID,
    SCHEMA_VERSION,
    TASK_ID,
    ZERO_FUTURE_SKEW,
    AttemptStatus,
    ByteBindingError,
    ContentFormat,
    FailureKind,
    FulltextDisposition,
    IdentityError,
    ParserResult,
    VerifierClockError,
    assert_fixture_expectations,
    assert_fulltext_admission,
    evaluate_fixture_case,
    evaluate_fulltext_attempt_receipt,
    evaluate_fulltext_fixture,
    example_closed_fulltext_receipt,
    example_exhausted_non_body_document,
    example_full_text_document,
    fixture_verifier_now,
    public_helper_rejects_skew_override,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    OfficialAuthority,
    content_sha256,
)

_NOW = fixture_verifier_now()


def _eval(receipt: dict[str, Any], *, now=_NOW, **kwargs: Any):
    return evaluate_fulltext_attempt_receipt(receipt, now=now, **kwargs)


def _closed(**kwargs: Any) -> dict[str, Any]:
    return example_closed_fulltext_receipt(**kwargs)


# ---------------------------------------------------------------------------
# Public helper parity / zero skew
# ---------------------------------------------------------------------------


def test_public_helpers_reject_tolerance_override_parameter() -> None:
    assert public_helper_rejects_skew_override()
    for fn in (
        evaluate_fulltext_attempt_receipt,
        assert_fulltext_admission,
        evaluate_fixture_case,
        evaluate_fulltext_fixture,
        assert_fixture_expectations,
    ):
        params = inspect.signature(fn).parameters
        assert "max_future_skew" not in params
        assert "tolerance" not in params
        assert "skew" not in params


def test_caller_supplied_nonzero_skew_is_rejected() -> None:
    raw = _closed(receipt_id="skew-override")
    result = _eval(raw, max_future_skew=timedelta(minutes=5))
    assert not result.passed
    assert FailureKind.CALLER_SKEW.value in result.failure_kinds
    with pytest.raises(VerifierClockError):
        assert_fulltext_admission(raw, now=_NOW, max_future_skew=timedelta(seconds=1))


def test_explicit_zero_skew_kwarg_does_not_widen() -> None:
    raw = _closed(receipt_id="skew-zero")
    result = _eval(raw, max_future_skew=ZERO_FUTURE_SKEW)
    assert result.passed, result.findings


def test_timestamp_one_microsecond_after_verifier_fails() -> None:
    raw = _closed(receipt_id="skew-1us")
    raw["receipt_created_at"] = "2026-08-10T12:00:00.000001Z"
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.TIMESTAMP_AFTER_VERIFIER.value in result.failure_kinds


def test_four_minute_fifty_nine_second_case_fails() -> None:
    raw = _closed(receipt_id="skew-4m59")
    raw["receipt_created_at"] = "2026-08-10T12:04:59Z"
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.TIMESTAMP_AFTER_VERIFIER.value in result.failure_kinds


def test_omitted_verifier_time_fails_on_every_authorizing_helper() -> None:
    raw = _closed(receipt_id="no-clock")
    result = evaluate_fulltext_attempt_receipt(raw, now=None)
    assert not result.passed
    assert FailureKind.MISSING_VERIFIER_TIME.value in result.failure_kinds
    with pytest.raises(VerifierClockError):
        assert_fulltext_admission(raw, now=None)


# ---------------------------------------------------------------------------
# Identity mutation matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_identity_field_omitted_fails(field: str) -> None:
    raw = _closed(receipt_id=f"omit-{field}")
    del raw[field]
    result = _eval(raw)
    assert not result.passed
    assert (
        FailureKind.IDENTITY.value in result.failure_kinds
        or FailureKind.FIXTURE_MODE.value in result.failure_kinds
    )


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_identity_field_empty_fails(field: str) -> None:
    raw = _closed(receipt_id=f"empty-{field}")
    raw[field] = ""
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.IDENTITY.value in result.failure_kinds or (
        field == "mode" and FailureKind.FIXTURE_MODE.value in result.failure_kinds
    )


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("schema_version", "federal-register-fulltext-gate-v1"),
        ("schema_version", "federal-register-fulltext-gate-v2-alias"),
        ("producer", "federal_register_fulltext_gate.py"),
        ("producer", "federal_register_fulltext_gate.py@1"),
        ("program_id", "legal-corpora-reindex"),
        ("task_id", "LCR-075"),
        ("goal_id", "LCR-G110"),
        ("mode", "fixture"),
        ("mode", "test"),
    ],
)
def test_identity_field_wrong_or_aliased_fails(field: str, wrong: str) -> None:
    raw = _closed(receipt_id=f"wrong-{field}")
    raw[field] = wrong
    result = _eval(raw)
    assert not result.passed
    kinds = set(result.failure_kinds)
    assert kinds & {
        FailureKind.IDENTITY.value,
        FailureKind.FIXTURE_MODE.value,
    }


def test_all_identity_fields_removed_together_fails() -> None:
    raw = _closed(receipt_id="no-identity")
    for field in IDENTITY_FIELDS:
        raw.pop(field, None)
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.IDENTITY.value in result.failure_kinds


def test_every_v1_receipt_fails() -> None:
    raw = _closed(receipt_id="v1-receipt")
    raw["schema_version"] = "federal-register-fulltext-gate-v1"
    raw["producer"] = "federal_register_fulltext_gate.py"
    raw["task_id"] = "LCR-075"
    raw["goal_id"] = "LCR-G110"
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.IDENTITY.value in result.failure_kinds


def test_fixture_mode_cannot_authorize() -> None:
    raw = _closed(receipt_id="fixture-mode", mode=MODE_FIXTURE)
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.FIXTURE_MODE.value in result.failure_kinds
    with pytest.raises(IdentityError):
        assert_fulltext_admission(raw, now=_NOW)


def test_positive_control_has_exact_v2_live_identity() -> None:
    raw = _closed()
    for name, expected in AUTHORIZING_IDENTITY.items():
        assert raw[name] == expected
    assert raw["mode"] == MODE_LIVE
    assert raw["schema_version"] == SCHEMA_VERSION
    assert raw["producer"] == PRODUCER
    assert raw["program_id"] == PROGRAM_ID
    assert raw["task_id"] == TASK_ID
    assert raw["goal_id"] == GOAL_ID
    assert _eval(raw).passed


# ---------------------------------------------------------------------------
# Non-exhaustive negatives
# ---------------------------------------------------------------------------


def test_two_hashless_failed_anti_bot_attempts_fail() -> None:
    raw = _closed(receipt_id="hashless-antibot")
    raw["documents"] = [
        {
            "document_number": "2026-04801",
            "publication_date": "2026-04-10",
            "disposition": FulltextDisposition.METADATA_ONLY.value,
            "allowed_reason": "official_metadata_only",
            "attempts": [
                {
                    "attempt_id": "2026-04801-fr-html",
                    "authority": OfficialAuthority.FEDERAL_REGISTER.value,
                    "content_format": "html",
                    "url": "https://www.federalregister.gov/documents/2026-04801",
                    "observed_at": "2026-08-10T02:00:00Z",
                    "status": AttemptStatus.FAILED.value,
                    "retry_count": 2,
                    "terminal_reason": "anti_bot",
                    "parser_result": ParserResult.ANTI_BOT.value,
                    "body_available": False,
                    "body_usable": False,
                    "http_status": 403,
                    "media_type": "text/html",
                },
                {
                    "attempt_id": "2026-04801-govinfo-pdf",
                    "authority": OfficialAuthority.GOVINFO.value,
                    "content_format": "pdf",
                    "url": "https://www.govinfo.gov/app/details/FR-2026-04801",
                    "observed_at": "2026-08-10T02:05:00Z",
                    "status": AttemptStatus.FAILED.value,
                    "retry_count": 2,
                    "terminal_reason": "anti_bot",
                    "parser_result": ParserResult.ANTI_BOT.value,
                    "body_available": False,
                    "body_usable": False,
                    "http_status": 403,
                    "media_type": "application/pdf",
                },
            ],
        }
    ]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.NON_EXHAUSTIVE_NEGATIVE.value in result.failure_kinds


@pytest.mark.parametrize(
    "status,parser",
    [
        (AttemptStatus.SKIPPED.value, ParserResult.NOT_RUN.value),
        (AttemptStatus.NO_BODY.value, ParserResult.ERROR_PAGE.value),
        (AttemptStatus.NO_BODY.value, ParserResult.NAVIGATION.value),
        (AttemptStatus.NO_BODY.value, ParserResult.UNSUPPORTED_FORMAT.value),
    ],
)
def test_skipped_error_page_navigation_unsupported_are_non_exhaustive(
    status: str, parser: str
) -> None:
    raw = _closed(receipt_id=f"neg-{status}-{parser}")
    doc = example_exhausted_non_body_document(document_number="2026-04810")
    attempt = doc["attempts"][0]
    attempt["status"] = status
    attempt["parser_result"] = parser
    # Keep declared hashes but these outcomes cannot prove absence.
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert (
        FailureKind.NON_EXHAUSTIVE_NEGATIVE.value in result.failure_kinds
        or FailureKind.INCOMPLETE_EXHAUSTION.value in result.failure_kinds
    )


# ---------------------------------------------------------------------------
# Frontier / authority / format binding
# ---------------------------------------------------------------------------


def test_missing_frontier_entry_fails() -> None:
    raw = _closed(receipt_id="missing-frontier")
    doc = example_exhausted_non_body_document(document_number="2026-04820")
    doc["attempts"] = [doc["attempts"][0]]
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.INCOMPLETE_EXHAUSTION.value in result.failure_kinds


def test_extra_frontier_entry_fails() -> None:
    raw = _closed(receipt_id="extra-frontier")
    doc = example_exhausted_non_body_document(document_number="2026-04821")
    extra = copy.deepcopy(doc["attempts"][0])
    extra["attempt_id"] = "2026-04821-fr-xml"
    extra["content_format"] = ContentFormat.XML.value
    extra["media_type"] = "application/xml"
    extra["url"] = "https://www.federalregister.gov/documents/2026-04821.xml"
    # Rebuild absence hashes for mutated identity
    extra["request_bytes"] = "fr-fulltext-bytes:request:2026-04821-fr-xml"
    extra["response_bytes"] = "fr-fulltext-bytes:response-absence:2026-04821-fr-xml"
    extra["request_hash"] = content_sha256(extra["request_bytes"])
    extra["response_hash"] = content_sha256(extra["response_bytes"])
    doc["attempts"] = list(doc["attempts"]) + [extra]
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.EXTRA_FRONTIER.value in result.failure_kinds


def test_duplicate_ledger_key_fails() -> None:
    raw = _closed(receipt_id="dup-key")
    doc = example_exhausted_non_body_document(document_number="2026-04822")
    dup = copy.deepcopy(doc["attempts"][0])
    dup["attempt_id"] = "2026-04822-fr-html-shadow"
    doc["attempts"] = [doc["attempts"][0], dup, doc["attempts"][1]]
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.DUPLICATE_LEDGER_KEY.value in result.failure_kinds


def test_authority_url_on_other_official_host_fails() -> None:
    raw = _closed(receipt_id="host-swap")
    doc = example_exhausted_non_body_document(document_number="2026-04823")
    # FR authority pointing at GovInfo host.
    doc["attempts"][0]["url"] = "https://www.govinfo.gov/app/details/FR-2026-04823"
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.AUTHORITY_HOST_MISMATCH.value in result.failure_kinds


def test_format_media_type_mismatch_fails() -> None:
    raw = _closed(receipt_id="media-mismatch")
    doc = example_full_text_document(document_number="2026-04824")
    doc["attempts"][0]["media_type"] = "application/pdf"  # html format, pdf media
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.FORMAT_MEDIA_MISMATCH.value in result.failure_kinds


# ---------------------------------------------------------------------------
# Byte binding / hash matrix
# ---------------------------------------------------------------------------


def test_response_hash_without_content_hash_fails() -> None:
    raw = _closed(receipt_id="resp-only")
    doc = example_full_text_document(document_number="2026-04830")
    doc["attempts"][0].pop("content_hash", None)
    doc["admitted_content_hash"] = None
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.MISSING_HASH.value in result.failure_kinds


def test_content_hash_without_response_hash_fails() -> None:
    raw = _closed(receipt_id="content-only")
    doc = example_full_text_document(document_number="2026-04831")
    doc["attempts"][0].pop("response_hash", None)
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.MISSING_HASH.value in result.failure_kinds


def test_admitted_body_digest_differs_by_one_nibble_fails() -> None:
    raw = _closed(receipt_id="nibble")
    doc = example_full_text_document(document_number="2026-04832")
    digest = doc["admitted_content_hash"]
    # Flip last hex nibble.
    last = digest[-1]
    flipped = "0" if last != "0" else "1"
    doc["admitted_content_hash"] = digest[:-1] + flipped
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.HASH_MISMATCH.value in result.failure_kinds
    with pytest.raises(ByteBindingError):
        assert_fulltext_admission(raw, now=_NOW)


def test_admitted_body_bytes_mutated_while_hashes_unchanged_fails() -> None:
    raw = _closed(receipt_id="mutated-body")
    doc = example_full_text_document(document_number="2026-04833")
    doc["admitted_body_bytes"] = doc["admitted_body_bytes"] + "-mutated"
    doc["attempts"][0]["content_bytes"] = doc["attempts"][0]["content_bytes"] + "-mutated"
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.HASH_MISMATCH.value in result.failure_kinds


def test_negative_hashes_without_captured_bytes_fail() -> None:
    raw = _closed(receipt_id="absence-no-bytes")
    doc = example_exhausted_non_body_document(document_number="2026-04834")
    for attempt in doc["attempts"]:
        attempt.pop("request_bytes", None)
        attempt.pop("response_bytes", None)
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.BYTE_BINDING.value in result.failure_kinds


def test_absence_bytes_mutated_while_hashes_unchanged_fail() -> None:
    raw = _closed(receipt_id="absence-mutated")
    doc = example_exhausted_non_body_document(document_number="2026-04835")
    doc["attempts"][0]["response_bytes"] = doc["attempts"][0]["response_bytes"] + "X"
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.HASH_MISMATCH.value in result.failure_kinds


def test_usable_body_hidden_by_metadata_only_fails() -> None:
    raw = _closed(receipt_id="hidden-usable")
    doc = example_full_text_document(document_number="2026-04836")
    doc["disposition"] = FulltextDisposition.METADATA_ONLY.value
    doc["allowed_reason"] = "official_metadata_only"
    # Keep usable admitted-status attempt but claim metadata-only.
    # Force first attempt still usable but change status to not fully admitted path
    # under non-body disposition.
    doc["attempts"][0]["status"] = AttemptStatus.PARSED.value
    doc.pop("admitted_content_hash", None)
    doc.pop("admitted_body_bytes", None)
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.EXCLUSION_ERASES_FAILURE.value in result.failure_kinds


def test_usable_body_hidden_by_quarantine_fails() -> None:
    raw = _closed(receipt_id="hidden-quarantine")
    doc = example_full_text_document(document_number="2026-04837")
    doc["disposition"] = FulltextDisposition.QUARANTINED.value
    doc["allowed_reason"] = "content_quarantine"
    doc["attempts"][0]["status"] = AttemptStatus.FETCHED.value
    doc.pop("admitted_content_hash", None)
    doc.pop("admitted_body_bytes", None)
    raw["documents"] = [doc]
    result = _eval(raw)
    assert not result.passed
    assert FailureKind.EXCLUSION_ERASES_FAILURE.value in result.failure_kinds


def test_assert_and_evaluate_share_same_verdict() -> None:
    raw = _closed(receipt_id="parity-ok")
    evaluated = evaluate_fulltext_attempt_receipt(raw, now=_NOW)
    asserted = assert_fulltext_admission(raw, now=_NOW)
    assert evaluated.passed and asserted.passed
    assert evaluated.failure_kinds == asserted.failure_kinds

    bad = _closed(receipt_id="parity-bad")
    bad["mode"] = MODE_FIXTURE
    evaluated_bad = evaluate_fulltext_attempt_receipt(bad, now=_NOW)
    assert not evaluated_bad.passed
    with pytest.raises(IdentityError):
        assert_fulltext_admission(bad, now=_NOW)
