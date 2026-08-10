"""Unit tests for the cutoff-bound Federal Register completeness oracle (LCR-049).

Acceptance: Rejects open pages, overlapping/gapped date partitions, mutable
cutoffs, metadata represented as body text, failed-final items, unexplained
count drift, and stale success registries.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_completeness import (
    SCHEMA_VERSION as COMPLETENESS_SCHEMA_VERSION,
    CompletenessVerdict,
    CompletionReceipt,
    CountDriftError,
    DatePartitionError,
    FailedFinalError,
    FailureKind,
    FederalRegisterCompletenessError,
    MetadataAsBodyError,
    OpenPageError,
    PageStatus,
    StaleSuccessRegistryError,
    assert_completion_closed,
    assert_fixture_expectations,
    build_default_completion_fixture_payload,
    evaluate_completion_fixture,
    evaluate_completion_receipt,
    evaluate_fixture_case,
    example_closed_receipt,
    expand_completion_fixture_cases,
    load_completion_fixture_payload,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    CURRENTNESS_DISCLAIMER,
    DEFAULT_OBSERVATION_CUTOFF,
    FEDERAL_REGISTER_DOCUMENTS_API,
    FIXTURE_SCHEMA_VERSION,
    LEGACY_BASELINE_END_INCLUSIVE,
    LEGACY_DELTA_START_INCLUSIVE,
    METADATA_AS_BODY_CHAR_THRESHOLD,
    OFFICIAL_FULL_TEXT_SOURCES,
    OFFICIAL_INVENTORY_SOURCE,
    PREVIOUS_PUBLIC_PIN,
    SCHEMA_VERSION as POLICY_SCHEMA_VERSION,
    TASK_ID,
    BodyTextDisposition,
    FederalRegisterSourcePolicy,
    MutableCutoffError,
    OfficialAuthority,
    OfficialAuthorityError,
    build_legal_id,
    clear_source_policy_cache,
    default_completion_fixture_path,
    default_source_policy,
    is_mutable_cutoff,
    official_authority_catalog,
    require_immutable_observation_cutoff,
    validate_body_text_disposition_fields,
    validate_document_number,
    validate_official_url,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "federal_register_completion_receipts.json"
)


@pytest.fixture(autouse=True)
def _clear_policy_cache() -> None:
    clear_source_policy_cache()
    yield
    clear_source_policy_cache()


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_completion_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def fixture_cases(fixture_payload: dict) -> list[dict]:
    return expand_completion_fixture_cases(fixture_payload)


# ---------------------------------------------------------------------------
# Source policy
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert POLICY_SCHEMA_VERSION == "federal-register-source-policy-v1"
    assert COMPLETENESS_SCHEMA_VERSION == "federal-register-completeness-v1"
    assert FIXTURE_SCHEMA_VERSION == "federal-register-completion-receipts-v1"
    assert TASK_ID == "LCR-049"
    assert DEFAULT_OBSERVATION_CUTOFF == "2026-08-10T00:00:00Z"
    assert LEGACY_DELTA_START_INCLUSIVE == "2026-03-03"
    assert LEGACY_BASELINE_END_INCLUSIVE == "2026-03-02"


def test_official_authorities_are_federal_register_api_and_govinfo() -> None:
    catalog = official_authority_catalog()
    assert catalog["inventory_source"] == OFFICIAL_INVENTORY_SOURCE
    assert "FederalRegister.gov" in OFFICIAL_FULL_TEXT_SOURCES
    assert "GovInfo" in OFFICIAL_FULL_TEXT_SOURCES
    assert catalog["inventory_url"] == FEDERAL_REGISTER_DOCUMENTS_API
    policy = default_source_policy()
    assert policy.inventory_authority is OfficialAuthority.FEDERAL_REGISTER_API
    assert OfficialAuthority.GOVINFO in policy.full_text_authorities
    assert OfficialAuthority.FEDERAL_REGISTER in policy.full_text_authorities
    assert policy.observation_cutoff == DEFAULT_OBSERVATION_CUTOFF
    assert "cutoff-relative" in policy.currentness_disclaimer.lower()
    assert policy.currentness_disclaimer == CURRENTNESS_DISCLAIMER


def test_mutable_cutoffs_are_rejected() -> None:
    assert is_mutable_cutoff("latest")
    assert is_mutable_cutoff("current")
    assert is_mutable_cutoff("live")
    assert is_mutable_cutoff("main")
    assert is_mutable_cutoff("HEAD")
    assert not is_mutable_cutoff(DEFAULT_OBSERVATION_CUTOFF)
    assert not is_mutable_cutoff("2026-08-10")

    for token in ("latest", "current", "live", "now", "main", "HEAD"):
        with pytest.raises(MutableCutoffError):
            require_immutable_observation_cutoff(token)

    pinned = require_immutable_observation_cutoff("2026-08-10")
    assert pinned == "2026-08-10T00:00:00Z"

    with pytest.raises(MutableCutoffError):
        FederalRegisterSourcePolicy(observation_cutoff="latest")


def test_document_identity_and_official_urls() -> None:
    assert validate_document_number("2026-04567") == "2026-04567"
    with pytest.raises(Exception):
        validate_document_number("row-12")
    legal_id = build_legal_id("2026-04567", "2026-03-15")
    assert legal_id == "fr:2026-04567:2026-03-15"
    assert validate_official_url(FEDERAL_REGISTER_DOCUMENTS_API).startswith("https://")
    with pytest.raises(OfficialAuthorityError):
        validate_official_url("https://example.com/docs")


def test_metadata_cannot_be_represented_as_body_text() -> None:
    validate_body_text_disposition_fields(
        disposition=BodyTextDisposition.FULL_TEXT,
        text="Official body text of the rule.",
    )
    with pytest.raises(Exception):
        validate_body_text_disposition_fields(
            disposition=BodyTextDisposition.FULL_TEXT,
            text="",
        )
    with pytest.raises(Exception):
        validate_body_text_disposition_fields(
            disposition=BodyTextDisposition.METADATA_ONLY,
            text="Y" * (METADATA_AS_BODY_CHAR_THRESHOLD + 1),
        )


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_completion_fixture_is_present_and_compact() -> None:
    assert _FIXTURE_PATH.is_file()
    assert default_completion_fixture_path().name == (
        "federal_register_completion_receipts.json"
    )
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["observation_cutoff"] == DEFAULT_OBSERVATION_CUTOFF
    assert "cases" in payload
    case_ids = {case["case_id"] for case in payload["cases"]}
    required = {
        "closed_ok",
        "open_page",
        "overlapping_partition",
        "gapped_partition",
        "mutable_cutoff",
        "metadata_as_body",
        "failed_final",
        "count_drift",
        "stale_success_registry",
    }
    assert required.issubset(case_ids)


def test_default_builder_matches_on_disk_case_ids() -> None:
    built = build_default_completion_fixture_payload()
    on_disk = load_completion_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["task_id"] == on_disk["task_id"]
    built_ids = [c["case_id"] for c in built["cases"]]
    disk_ids = [c["case_id"] for c in on_disk["cases"]]
    assert built_ids == disk_ids


def test_fixture_cases_expand_and_meet_expectations(
    fixture_cases: list[dict],
) -> None:
    assert len(fixture_cases) >= 9
    results = evaluate_completion_fixture(path=_FIXTURE_PATH)
    assert all(row["passed"] for row in results), results
    assert_fixture_expectations(path=_FIXTURE_PATH)


# ---------------------------------------------------------------------------
# Closed receipt passes
# ---------------------------------------------------------------------------


def test_closed_receipt_passes_oracle() -> None:
    receipt = example_closed_receipt()
    result = evaluate_completion_receipt(receipt)
    assert result.passed
    assert result.verdict is CompletenessVerdict.PASS
    assert result.open_page_count == 0
    assert result.failed_final == 0
    assert result.enumerated == result.official_total
    assert result.accounted == result.enumerated
    closed = assert_completion_closed(receipt)
    assert closed.passed


def test_completion_receipt_dataclass_round_trip() -> None:
    raw = example_closed_receipt()
    receipt = CompletionReceipt.from_mapping(raw)
    assert receipt.observation_cutoff == DEFAULT_OBSERVATION_CUTOFF
    assert receipt.previous_public_pin == PREVIOUS_PUBLIC_PIN
    assert len(receipt.partitions) == 2
    assert receipt.accounted == receipt.enumerated
    assert receipt.open_page_count == 0
    result = evaluate_completion_receipt(receipt)
    assert result.passed
    # to_dict re-evaluates cleanly
    again = evaluate_completion_receipt(receipt.to_dict())
    assert again.passed


# ---------------------------------------------------------------------------
# Acceptance: reject each failure mode
# ---------------------------------------------------------------------------


def test_rejects_open_pages() -> None:
    raw = example_closed_receipt(receipt_id="t-open-page")
    raw["partitions"][0]["pages"][0]["status"] = "open"
    raw["partitions"][0]["pages"][0].pop("response_hash", None)
    raw["frontier_closed"] = False
    result = evaluate_completion_receipt(raw)
    assert not result.passed
    assert FailureKind.OPEN_PAGE.value in result.failure_kinds
    with pytest.raises(OpenPageError):
        assert_completion_closed(raw)


def test_rejects_overlapping_date_partitions() -> None:
    raw = example_closed_receipt(receipt_id="t-overlap")
    raw["partitions"][1]["start_date"] = "2026-03-15"
    result = evaluate_completion_receipt(raw)
    assert not result.passed
    assert FailureKind.OVERLAPPING_PARTITION.value in result.failure_kinds
    with pytest.raises(DatePartitionError):
        assert_completion_closed(raw)


def test_rejects_gapped_date_partitions() -> None:
    raw = example_closed_receipt(receipt_id="t-gap")
    raw["partitions"][1]["start_date"] = "2026-04-05"
    result = evaluate_completion_receipt(raw)
    assert not result.passed
    assert FailureKind.GAPPED_PARTITION.value in result.failure_kinds
    with pytest.raises(DatePartitionError):
        assert_completion_closed(raw)


def test_rejects_mutable_cutoffs_on_receipt() -> None:
    raw = example_closed_receipt(receipt_id="t-mutable")
    raw["observation_cutoff"] = "latest"
    with pytest.raises(MutableCutoffError):
        CompletionReceipt.from_mapping(raw)
    # Fixture-style evaluation captures mutable cutoff as a finding.
    case = {
        "case_id": "t-mutable",
        "expected_status": "fail",
        "expected_kinds": ["mutable_cutoff"],
        "receipt": raw,
    }
    result = evaluate_fixture_case(case)
    assert not result.passed
    assert FailureKind.MUTABLE_CUTOFF.value in result.failure_kinds


def test_rejects_metadata_represented_as_body_text() -> None:
    raw = example_closed_receipt(receipt_id="t-meta-body")
    raw["documents"] = [
        {
            "document_number": "2026-45000",
            "publication_date": "2026-03-10",
            "disposition": BodyTextDisposition.METADATA_ONLY.value,
            "text": "Z" * (METADATA_AS_BODY_CHAR_THRESHOLD + 20),
        }
    ]
    # May fail at parse or evaluation; both are reject paths.
    try:
        result = evaluate_completion_receipt(raw)
        assert not result.passed
        assert FailureKind.METADATA_AS_BODY.value in result.failure_kinds
    except MetadataAsBodyError:
        pass


def test_rejects_failed_final_items() -> None:
    raw = example_closed_receipt(receipt_id="t-failed-final")
    raw["failed_final"] = 1
    raw["fetched"] = raw["enumerated"] - 1
    raw["partitions"][0]["failed_final"] = 1
    raw["partitions"][0]["fetched"] = raw["partitions"][0]["enumerated"] - 1
    result = evaluate_completion_receipt(raw)
    assert not result.passed
    assert FailureKind.FAILED_FINAL.value in result.failure_kinds
    with pytest.raises(FailedFinalError):
        assert_completion_closed(raw)


def test_rejects_unexplained_count_drift() -> None:
    raw = example_closed_receipt(receipt_id="t-drift")
    raw["official_total"] = raw["enumerated"] + 7
    raw["unexplained_count_drift"] = 7
    result = evaluate_completion_receipt(raw)
    assert not result.passed
    assert FailureKind.COUNT_DRIFT.value in result.failure_kinds
    with pytest.raises(CountDriftError):
        assert_completion_closed(raw)


def test_rejects_stale_success_registries() -> None:
    raw = example_closed_receipt(receipt_id="t-stale")
    raw["success_registry"] = [
        {
            "entry_id": "stale-1",
            "status": "success",
            "partition_id": "p-2026-03",
            "frontier_closed": False,
            "failed_final": 0,
            "open_pages": 3,
        }
    ]
    result = evaluate_completion_receipt(raw)
    assert not result.passed
    assert FailureKind.STALE_SUCCESS_REGISTRY.value in result.failure_kinds
    with pytest.raises(StaleSuccessRegistryError):
        assert_completion_closed(raw)


def test_partition_api_total_drift_is_count_drift() -> None:
    raw = example_closed_receipt(receipt_id="t-part-drift")
    raw["partitions"][0]["api_total"] = raw["partitions"][0]["enumerated"] + 2
    result = evaluate_completion_receipt(raw)
    assert not result.passed
    assert FailureKind.COUNT_DRIFT.value in result.failure_kinds


def test_reconciliation_arithmetic_required() -> None:
    raw = example_closed_receipt(receipt_id="t-arith")
    raw["fetched"] = raw["enumerated"] - 2  # breaks accounted identity
    # Keep failed_final at 0 so the only issue is reconciliation.
    result = evaluate_completion_receipt(raw)
    assert not result.passed
    assert FailureKind.RECONCILIATION.value in result.failure_kinds


def test_page_status_open_detection() -> None:
    assert PageStatus.coerce("open").is_open
    assert PageStatus.coerce("pending").is_open
    assert PageStatus.coerce("failed").is_open
    assert PageStatus.coerce("verified").is_closed
    assert PageStatus.coerce("fetched").is_closed


def test_each_fixture_adversarial_case_fails_with_expected_kind(
    fixture_cases: list[dict],
) -> None:
    by_id = {case["case_id"]: case for case in fixture_cases}
    for case_id, expected_kind in (
        ("open_page", "open_page"),
        ("overlapping_partition", "overlapping_partition"),
        ("gapped_partition", "gapped_partition"),
        ("mutable_cutoff", "mutable_cutoff"),
        ("metadata_as_body", "metadata_as_body"),
        ("failed_final", "failed_final"),
        ("count_drift", "count_drift"),
        ("stale_success_registry", "stale_success_registry"),
    ):
        case = by_id[case_id]
        result = evaluate_fixture_case(case)
        assert result.verdict is CompletenessVerdict.FAIL, case_id
        assert expected_kind in result.failure_kinds, (
            case_id,
            result.failure_kinds,
            [f.message for f in result.findings],
        )


def test_closed_ok_fixture_case_passes(fixture_cases: list[dict]) -> None:
    case = next(c for c in fixture_cases if c["case_id"] == "closed_ok")
    result = evaluate_fixture_case(case)
    assert result.passed
    assert result.failure_kinds == ()


def test_deep_copy_mutation_does_not_affect_example() -> None:
    a = example_closed_receipt()
    b = copy.deepcopy(a)
    b["failed_final"] = 9
    assert a["failed_final"] == 0
    assert evaluate_completion_receipt(a).passed
