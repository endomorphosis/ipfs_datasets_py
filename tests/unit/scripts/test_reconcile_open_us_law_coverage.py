"""Unit tests for OUL-022 exact-51 coverage and bucket-delta reconciliation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.ops.legal_data.reconcile_open_us_law_coverage import (
    CLEAN_OFFICIAL_CODES,
    DISPOSITION_FAILED_FINAL,
    DISPOSITION_RECONCILED,
    DISPOSITION_UNKNOWN,
    EXCLUDED_DEFAULT_CODES,
    JURISDICTION_COUNT,
    REQUIRED_JURISDICTION_CODES,
    SCHEMA_VERSION,
    CoverageError,
    audit_coverage,
    build_coverage_payload,
    check_committed_coverage,
    classify_disposition,
    classify_bucket_path,
    default_coverage_path,
    encode_coverage,
    expected_jurisdiction_codes,
    is_clean_official_receipt,
    load_coverage,
    main,
    official_replacement_present,
    sha256_json,
    statute_code_from_path,
    validate_coverage,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _reseal(payload: dict) -> dict:
    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    payload["report_digest_sha256"] = sha256_json(body)
    return payload


def _mutated(payload: dict) -> dict:
    return _reseal(copy.deepcopy(payload))


def _disposition(
    *,
    discovered: int = 2,
    fetched: int = 2,
    excluded: int = 0,
    quarantined: int = 0,
    failed_final: int = 0,
    status: str | None = None,
) -> dict[str, object]:
    block: dict[str, object] = {
        "discovered": discovered,
        "fetched": fetched,
        "excluded": excluded,
        "quarantined": quarantined,
        "failed_final": failed_final,
    }
    if status is not None:
        block["status"] = status
    return block


def _official_receipt(
    code: str,
    *,
    clean_replacement: bool = False,
    contaminated: bool = False,
    failed_final: int = 0,
    frontier_closed: bool = True,
    authority: str = "official",
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "jurisdiction": code,
        "source_authority_class": authority,
        "source_domain": f"official.{code.lower()}.gov",
        "row_count": 2,
        "disposition": _disposition(failed_final=failed_final),
        "frontier": {
            "closed": frontier_closed,
            "frontier_digest_sha256": "a" * 64,
        },
        "hashes": {"admitted_body_sha256": "b" * 64},
        "text_quality": {"contaminated": contaminated},
    }
    if clean_replacement:
        frontier = receipt["frontier"]
        assert isinstance(frontier, dict)
        frontier[f"{code.lower()}_contaminated_bucket_replaced"] = True
        receipt["admitted_body"] = json.dumps(
            {
                "contaminated_bucket_replaced": True,
                "replacement_source": "official_clean_text",
                "jurisdiction": code,
            }
        )
    return receipt


def _row(code: str, **overrides: object) -> dict[str, object]:
    from scripts.ops.legal_data.reconcile_open_us_law_coverage import (
        COHORT_BY_JURISDICTION,
        COHORT_TASK_IDS,
    )

    cohort = COHORT_BY_JURISDICTION[code]
    replacement = code in CLEAN_OFFICIAL_CODES
    row: dict[str, object] = {
        "jurisdiction_code": code,
        "cohort": cohort,
        "task_id": COHORT_TASK_IDS[cohort],
        "in_default_set": True,
        "bucket_statute_present": code not in CLEAN_OFFICIAL_CODES,
        "bucket_delta": (
            "absent_required_statute_filled_by_official"
            if code in CLEAN_OFFICIAL_CODES
            else "bucket_seed_superseded_by_official_receipt"
        ),
        "clean_official": True,
        "official_replacement": replacement,
        "source_authority_class": "official",
        "source_domain": f"official.{code.lower()}.gov",
        "frontier_closed": True,
        "contaminated": False,
        "disposition_status": DISPOSITION_RECONCILED,
        "disposition": {
            "discovered": 2,
            "fetched": 2,
            "excluded": 0,
            "quarantined": 0,
            "failed_final": 0,
            "status": DISPOSITION_RECONCILED,
        },
        "row_count": 2,
        "admitted_body_sha256": "b" * 64,
        "frontier_digest_sha256": "a" * 64,
        "certification_ok": True,
    }
    row.update(overrides)
    return row


def _compact_payload() -> dict[str, object]:
    rows = [_row(code) for code in REQUIRED_JURISDICTION_CODES]
    payload: dict[str, object] = {
        "authorizing_for_publication": False,
        "bucket_deltas": {
            "all_reconciled": True,
            "unresolved": [],
            "absent_required_statute_codes": list(CLEAN_OFFICIAL_CODES),
            "live_default_statute_codes": [
                code for code in REQUIRED_JURISDICTION_CODES if code not in CLEAN_OFFICIAL_CODES
            ],
            "excluded_pr_paths": ["us_pr_statutes.parquet"],
            "excluded_federal_paths": ["us_federal_statutes.parquet"],
            "excluded_constitution_paths": ["us_ak_constitutions.parquet"],
            "withdrawn_paths_still_listed": [
                "us_ga_statutes.parquet",
                "us_nc_statutes.parquet",
            ],
            "stale_checksum": True,
            "deltas": [
                {
                    "id": "absent_required_statutes",
                    "reconciled": True,
                    "codes": list(CLEAN_OFFICIAL_CODES),
                    "resolution": "clean_official_replacement",
                }
            ],
        },
        "checks": {
            "clean_official_ga_nc_required": True,
            "dc_counted_once_required": True,
            "exact_51_required": True,
            "failed_final_forbidden": True,
            "pr_and_federal_excluded_from_default": True,
            "unknown_disposition_forbidden": True,
        },
        "clean_official_ga": True,
        "clean_official_nc": True,
        "code_version": "1",
        "cohorts": {},
        "configuration": "state_statutes_exact_51",
        "dc_counted_once": True,
        "default_exclusions": sorted(EXCLUDED_DEFAULT_CODES),
        "description": "compact fixture",
        "disposition": {
            "discovered": 102,
            "fetched": 102,
            "excluded": 0,
            "quarantined": 0,
            "failed_final": 0,
            "unknown": 0,
            "arithmetic_ok": True,
            "detail": "ok",
            "unknown_or_failed_final": 0,
        },
        "exact_51": True,
        "excluded_from_default": {
            "federal_paths": ["us_federal_statutes.parquet", "us_federal_constitutions.parquet"],
            "pr_paths": ["us_pr_statutes.parquet", "us_pr_constitutions.parquet"],
            "codes": ["PR", "FEDERAL"],
        },
        "goal_id": "OUL-G024",
        "jurisdiction_count": 51,
        "jurisdiction_codes": list(REQUIRED_JURISDICTION_CODES),
        "jurisdictions": rows,
        "missing_jurisdiction_codes": [],
        "open_gaps": [],
        "open_gap_count": 0,
        "producer": "reconcile_open_us_law_coverage.py@1",
        "program_id": "open-us-law-reindex-v1",
        "schema_version": SCHEMA_VERSION,
        "sealed_at": "2026-08-13T00:00:00Z",
        "status": "success",
        "task_id": "OUL-022",
    }
    return _reseal(payload)


def test_expected_jurisdiction_codes_are_exact_51_including_dc_once() -> None:
    codes = expected_jurisdiction_codes()
    assert codes == REQUIRED_JURISDICTION_CODES
    assert len(codes) == JURISDICTION_COUNT == 51
    assert len(set(codes)) == 51
    assert codes.count("DC") == 1
    assert "PR" not in codes
    assert "US" not in codes
    assert "FED" not in codes
    assert "FEDERAL" not in codes
    for code in ("AL", "CA", "GA", "NC", "NY", "TX", "WA", "DC"):
        assert code in codes


def test_statute_paths_exclude_federal_and_constitutions() -> None:
    assert statute_code_from_path("us_al_statutes.parquet") == "AL"
    assert statute_code_from_path("us_dc_statutes.parquet") == "DC"
    assert statute_code_from_path("us_ga_statutes.parquet") == "GA"
    assert statute_code_from_path("us_pr_statutes.parquet") == "PR"
    assert statute_code_from_path("us_federal_statutes.parquet") is None
    assert statute_code_from_path("us_ga_constitutions.parquet") is None
    classified_pr = classify_bucket_path("us_pr_statutes.parquet")
    classified_fed = classify_bucket_path("us_federal_statutes.parquet")
    classified_const = classify_bucket_path("us_ak_constitutions.parquet")
    assert classified_pr["in_default_set"] is False
    assert classified_fed["in_default_set"] is False
    assert classified_const["in_default_set"] is False
    assert classify_bucket_path("us_ak_statutes.parquet")["in_default_set"] is True


def test_clean_official_ga_and_nc_require_replacement_evidence() -> None:
    ga = _official_receipt("GA", clean_replacement=True)
    nc = _official_receipt("NC", clean_replacement=True)
    assert official_replacement_present("GA", ga) is True
    assert official_replacement_present("NC", nc) is True
    assert is_clean_official_receipt("GA", ga) is True
    assert is_clean_official_receipt("NC", nc) is True
    assert is_clean_official_receipt("GA", _official_receipt("GA")) is False
    assert is_clean_official_receipt(
        "GA", _official_receipt("GA", clean_replacement=True, contaminated=True)
    ) is False
    assert is_clean_official_receipt("AK", _official_receipt("AK")) is True


def test_classify_disposition_rejects_unknown_and_failed_final() -> None:
    assert classify_disposition({"disposition": _disposition()}) == DISPOSITION_RECONCILED
    assert (
        classify_disposition({"disposition": _disposition(failed_final=1, discovered=3, fetched=2)})
        == DISPOSITION_FAILED_FINAL
    )
    assert classify_disposition({}) == DISPOSITION_UNKNOWN
    assert classify_disposition({"disposition": {"status": "unknown"}}) == DISPOSITION_UNKNOWN
    assert classify_disposition({"disposition": {"discovered": 1}}) == DISPOSITION_UNKNOWN


def test_compact_payload_passes_require_51_and_no_open_gaps() -> None:
    payload = _compact_payload()
    projection = validate_coverage(payload, require_51=True, require_no_open_gaps=True)
    assert projection["exact_51"] is True
    assert projection["dc_counted_once"] is True
    assert projection["clean_official_ga"] is True
    assert projection["clean_official_nc"] is True
    assert projection["pr_excluded"] is True
    assert projection["federal_excluded"] is True
    assert projection["bucket_deltas_reconciled"] is True
    assert projection["unknown_or_failed_final"] == 0
    assert projection["open_gap_count"] == 0


def test_validate_rejects_pr_in_default_set() -> None:
    payload = _mutated(_compact_payload())
    payload["jurisdiction_codes"] = list(REQUIRED_JURISDICTION_CODES) + ["PR"]
    payload["jurisdiction_count"] = 52
    payload["jurisdictions"] = list(payload["jurisdictions"]) + [_row("AL", jurisdiction_code="PR")]
    _reseal(payload)
    with pytest.raises(CoverageError, match="excluded"):
        validate_coverage(payload, require_51=True)


def test_validate_rejects_missing_and_extra_codes() -> None:
    payload = _mutated(_compact_payload())
    codes = [code for code in REQUIRED_JURISDICTION_CODES if code != "WY"]
    payload["jurisdiction_codes"] = codes
    payload["jurisdictions"] = [
        item for item in payload["jurisdictions"] if item["jurisdiction_code"] != "WY"
    ]
    _reseal(payload)
    with pytest.raises(CoverageError, match="exact-51"):
        validate_coverage(payload, require_51=True)


def test_validate_rejects_unknown_disposition() -> None:
    payload = _mutated(_compact_payload())
    row = next(item for item in payload["jurisdictions"] if item["jurisdiction_code"] == "AL")
    row["disposition_status"] = DISPOSITION_UNKNOWN
    row["disposition"]["status"] = DISPOSITION_UNKNOWN
    _reseal(payload)
    with pytest.raises(CoverageError, match="unknown"):
        validate_coverage(payload, require_51=True)


def test_validate_rejects_failed_final_disposition() -> None:
    payload = _mutated(_compact_payload())
    row = next(item for item in payload["jurisdictions"] if item["jurisdiction_code"] == "TX")
    row["disposition_status"] = DISPOSITION_FAILED_FINAL
    row["disposition"]["status"] = DISPOSITION_FAILED_FINAL
    row["disposition"]["failed_final"] = 1
    row["disposition"]["discovered"] = 3
    payload["disposition"]["failed_final"] = 1
    payload["disposition"]["unknown_or_failed_final"] = 1
    _reseal(payload)
    with pytest.raises(CoverageError, match="failed-final"):
        validate_coverage(payload, require_51=True)


def test_validate_rejects_unofficial_ga() -> None:
    payload = _mutated(_compact_payload())
    row = next(item for item in payload["jurisdictions"] if item["jurisdiction_code"] == "GA")
    row["clean_official"] = False
    row["official_replacement"] = False
    payload["clean_official_ga"] = False
    _reseal(payload)
    with pytest.raises(CoverageError, match="GA"):
        validate_coverage(payload, require_51=True)


def test_validate_rejects_unreconciled_bucket_deltas() -> None:
    payload = _mutated(_compact_payload())
    payload["bucket_deltas"]["all_reconciled"] = False
    payload["bucket_deltas"]["unresolved"] = ["absent_required_statutes"]
    payload["bucket_deltas"]["deltas"][0]["reconciled"] = False
    _reseal(payload)
    with pytest.raises(CoverageError, match="bucket"):
        validate_coverage(payload, require_51=True)


def test_validate_rejects_digest_tamper() -> None:
    payload = _mutated(_compact_payload())
    payload["report_digest_sha256"] = "0" * 64
    with pytest.raises(CoverageError, match="report_digest_sha256"):
        validate_coverage(payload, require_51=True)


def test_validate_rejects_publication_authorization() -> None:
    payload = _mutated(_compact_payload())
    payload["authorizing_for_publication"] = True
    _reseal(payload)
    with pytest.raises(CoverageError, match="authorize publication"):
        validate_coverage(payload, require_51=True)


def test_require_no_open_gaps_fails_when_gaps_remain() -> None:
    payload = _mutated(_compact_payload())
    payload["open_gaps"] = [{"kind": "open_frontier", "jurisdiction_code": "AL", "terminal": False}]
    payload["open_gap_count"] = 1
    _reseal(payload)
    validate_coverage(payload, require_51=True, require_no_open_gaps=False)
    with pytest.raises(CoverageError, match="open gaps"):
        validate_coverage(payload, require_51=True, require_no_open_gaps=True)


def test_committed_report_matches_deterministic_builder() -> None:
    committed = default_coverage_path().read_bytes()
    generated = encode_coverage(build_coverage_payload())
    assert committed == generated


def test_committed_report_is_exact_51_with_clean_ga_nc() -> None:
    payload = load_coverage()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["jurisdiction_count"] == 51
    assert payload["jurisdiction_codes"] == list(REQUIRED_JURISDICTION_CODES)
    assert payload["exact_51"] is True
    assert payload["dc_counted_once"] is True
    assert payload["clean_official_ga"] is True
    assert payload["clean_official_nc"] is True
    assert payload["authorizing_for_publication"] is False
    assert payload["disposition"]["failed_final"] == 0
    assert payload["disposition"]["unknown"] == 0
    assert payload["bucket_deltas"]["all_reconciled"] is True
    assert payload["bucket_deltas"]["absent_required_statute_codes"] == ["GA", "NC"]
    assert payload["excluded_from_default"]["codes"] == ["PR", "FEDERAL"]
    assert payload["excluded_from_default"]["pr_paths"]
    assert payload["excluded_from_default"]["federal_paths"]
    ga = next(item for item in payload["jurisdictions"] if item["jurisdiction_code"] == "GA")
    nc = next(item for item in payload["jurisdictions"] if item["jurisdiction_code"] == "NC")
    assert ga["clean_official"] is True
    assert ga["official_replacement"] is True
    assert ga["bucket_statute_present"] is False
    assert nc["clean_official"] is True
    assert nc["official_replacement"] is True
    assert nc["bucket_statute_present"] is False
    dc = next(item for item in payload["jurisdictions"] if item["jurisdiction_code"] == "DC")
    assert dc["bucket_statute_present"] is True
    serialized = json.dumps(payload)
    assert "hf_" not in serialized
    assert "Bearer " not in serialized
    assert "/home/" not in serialized


def test_committed_check_passes_require_51() -> None:
    report = check_committed_coverage(require_51=True, require_no_open_gaps=True)
    assert report["status"] == "passed"
    assert report["exact_51"] is True
    assert report["dc_counted_once"] is True
    assert report["jurisdiction_count"] == 51
    assert report["clean_official_ga"] is True
    assert report["clean_official_nc"] is True
    assert report["bucket_deltas_reconciled"] is True
    assert report["unknown_or_failed_final"] == 0
    assert report["open_gap_count"] == 0
    assert report["authorizing_for_publication"] is False


def test_audit_report_never_authorizes_publication() -> None:
    report = audit_coverage(_compact_payload(), require_51=True)
    assert report["authorizing_for_publication"] is False
    assert report["status"] == "passed"


def test_cli_require_51_check_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--require-51", "--check"]) == 0
    captured = capsys.readouterr()
    assert "PASSED" in captured.out
    assert "exact_51=True" in captured.out
    assert "ga_official=True" in captured.out
    assert "nc_official=True" in captured.out
    assert "bucket_deltas_reconciled=True" in captured.out


def test_cli_require_no_open_gaps_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--require-51", "--require-no-open-gaps", "--check"]) == 0
    assert "PASSED" in capsys.readouterr().out


def test_cli_requires_check_and_require_51() -> None:
    assert main(["--require-51"]) == 2
    assert main(["--check"]) == 2


def test_cli_json_never_leaks_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--require-51", "--check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload)
    assert payload["status"] == "passed"
    assert payload["authorizing_for_publication"] is False
    assert "hf_" not in serialized
    assert "Bearer " not in serialized
    assert "/home/" not in serialized
