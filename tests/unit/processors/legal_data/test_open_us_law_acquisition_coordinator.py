"""Unit tests for OUL-006 acquisition coordination and jurisdiction leases.

Acceptance: Receipts from the separate state-laws supervisor are accepted
only after byte and frontier verification; live jurisdiction leases prevent
duplicate scraping, and missing or invalid jurisdictions are scheduled
exactly once without trusting synthetic two-row reports.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    ACTION_REPAIR,
    ACTION_REUSE,
    ACTION_SCHEDULE,
    ACTION_WAIT,
    CANONICAL_JURISDICTION_ORDER,
    COHORT_JURISDICTIONS,
    EXPECTED_JURISDICTION_COUNT,
    GOAL_ID,
    OUL_HOLDER,
    PROGRAM_ID,
    PRODUCER,
    SCHEMA_VERSION,
    SEALED_AT,
    STATE_LAWS_HOLDER,
    TASK_ID,
    DuplicateLeaseError,
    DuplicateScheduleError,
    LeaseRegistry,
    LeaseReportError,
    LiveEvidenceRequiredError,
    build_acquisition_leases_payload,
    check_committed_leases,
    cohort_codes,
    cohort_letter,
    cohort_task_id,
    coordinate_jurisdictions,
    default_lease_report_path,
    encode_acquisition_leases,
    evaluate_prior_receipt,
    is_completion_ledger_claim,
    is_synthetic_two_row_report,
    lease_id_for,
    require_live_verified_receipts,
    require_scheduled_exactly_once,
    sha256_bytes,
    sha256_json,
    unique_schedule,
    validate_acquisition_leases,
    verify_receipt_bytes,
    verify_receipt_frontier,
    write_acquisition_leases,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (
    CANONICAL_JURISDICTIONS,
    closed_jurisdiction_receipt,
    sha256_text,
)


def _load_cli_module():
    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ops"
        / "legal_data"
        / "coordinate_open_us_law_scrapes.py"
    )
    spec = importlib.util.spec_from_file_location(
        "coordinate_open_us_law_scrapes_oul006", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


main = _load_cli_module().main


# ---------------------------------------------------------------------------
# Identity / set
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "open-us-law-acquisition-leases-v1"
    assert TASK_ID == "OUL-006"
    assert GOAL_ID == "OUL-G010"
    assert PROGRAM_ID == "open-us-law-reindex-v1"
    assert PRODUCER == "open_us_law_acquisition_coordinator.py"
    assert EXPECTED_JURISDICTION_COUNT == 51
    assert SEALED_AT.endswith("Z")


def test_cohort_map_covers_exact_51_once() -> None:
    union: list[str] = []
    for letter, codes in COHORT_JURISDICTIONS.items():
        assert codes == cohort_codes(letter)
        union.extend(codes)
        for code in codes:
            assert cohort_letter(code) == letter
            assert cohort_task_id(code).startswith("OUL-")
    assert union.count("DC") == 1
    assert set(union) == CANONICAL_JURISDICTIONS
    assert len(union) == 51


# ---------------------------------------------------------------------------
# Receipt builders
# ---------------------------------------------------------------------------


def _closed(code: str = "MN", **extra: object) -> dict:
    return closed_jurisdiction_receipt(code, **extra)


def _two_row(code: str = "MA") -> dict:
    return {
        "jurisdiction": code,
        "status": "success",
        "row_count": 2,
        "statutes_count": 2,
        "official_source": True,
        "source_domain": "malegislature.gov",
        "disposition": {
            "discovered": 2,
            "fetched": 2,
            "excluded": 0,
            "quarantined": 0,
            "failed_final": 0,
        },
        "frontier": {
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": 2,
            "visited_index_units": 2,
            "unvisited_continuation_links": [],
        },
        "index_keys": {"canonical_keys": [f"{code.lower()}:1", f"{code.lower()}:2"]},
    }


def _ledger(code: str = "CO", statutes_count: int = 5) -> dict:
    return {
        "jurisdiction": code,
        "status": "success",
        "statutes_count": statutes_count,
        "completion_mode": "shared_registry_promoted_baseline_2026-05-25",
        "ledger_only": True,
    }


def _with_body(code: str, body: bytes, fetched: int = 8) -> dict:
    receipt = _closed(
        code,
        fetched=fetched,
        discovered=fetched,
        excluded=0,
        quarantined=0,
    )
    digest = sha256_bytes(body)
    receipt["hashes"]["admitted_body_sha256"] = digest
    receipt["replay"]["admitted_body_sha256"] = digest
    return receipt


# ---------------------------------------------------------------------------
# Two-row / ledger classifiers
# ---------------------------------------------------------------------------


def test_synthetic_two_row_report_is_detected_and_not_trusted() -> None:
    report = _two_row("MS")
    assert is_synthetic_two_row_report(report) is True
    admission = evaluate_prior_receipt(report)
    assert admission.accepted is False
    assert "synthetic_two_row" in admission.rejection_kinds


def test_closed_receipt_with_more_than_two_rows_is_not_two_row() -> None:
    receipt = _closed("OR", fetched=8)
    assert is_synthetic_two_row_report(receipt) is False


def test_completion_ledger_is_not_a_receipt() -> None:
    claim = _ledger("GA")
    assert is_completion_ledger_claim(claim) is True
    admission = evaluate_prior_receipt(claim)
    assert admission.accepted is False
    assert "untrusted_completion_ledger" in admission.rejection_kinds


# ---------------------------------------------------------------------------
# Byte and frontier verification
# ---------------------------------------------------------------------------


def test_byte_verification_requires_replayable_hashes() -> None:
    receipt = _closed("WA")
    verdict = verify_receipt_bytes(receipt)
    assert verdict.ok is True
    assert verdict.replay_matched is True
    stripped = copy.deepcopy(receipt)
    stripped["hashes"]["admitted_body_sha256"] = ""
    stripped["replay"]["admitted_body_sha256"] = ""
    failed = verify_receipt_bytes(stripped)
    assert failed.ok is False


def test_byte_verification_rejects_hash_mismatch_and_tampered_body() -> None:
    body = b"official-minnesota-statute-body"
    receipt = _with_body("MN", body)
    assert verify_receipt_bytes(receipt, body_bytes=body).ok is True
    tampered = verify_receipt_bytes(receipt, body_bytes=b"tampered-body")
    assert tampered.ok is False
    mismatched = copy.deepcopy(receipt)
    mismatched["replay"]["admitted_body_sha256"] = "0" * 64
    assert verify_receipt_bytes(mismatched).ok is False


def test_frontier_verification_requires_closed_replayed_digest() -> None:
    receipt = _closed("OR")
    verdict = verify_receipt_frontier(receipt)
    assert verdict.ok is True
    assert verdict.closed is True
    open_frontier = closed_jurisdiction_receipt("OR", frontier_closed=False)
    assert verify_receipt_frontier(open_frontier).ok is False
    mismatched = copy.deepcopy(receipt)
    mismatched["replay"]["frontier_digest_sha256"] = "1" * 64
    assert verify_receipt_frontier(mismatched).ok is False


def test_receipt_accepted_only_after_byte_and_frontier_verification() -> None:
    body = b"official-oregon-statute-body"
    receipt = _with_body("OR", body, fetched=12)
    admission = evaluate_prior_receipt(receipt, body_bytes=body)
    assert admission.accepted is True
    assert admission.byte_verification is not None
    assert admission.frontier_verification is not None
    assert admission.byte_verification.ok is True
    assert admission.frontier_verification.ok is True

    rejected = evaluate_prior_receipt(receipt, body_bytes=b"wrong")
    assert rejected.accepted is False
    assert "byte_verification_failed" in rejected.rejection_kinds


def test_fixture_transport_is_never_accepted() -> None:
    receipt = _closed("CA", transport_kind="fixture")
    admission = evaluate_prior_receipt(receipt)
    assert admission.accepted is False
    assert "fixture_or_synthetic_transport" in admission.rejection_kinds


# ---------------------------------------------------------------------------
# Coordination / leases
# ---------------------------------------------------------------------------


def test_missing_and_invalid_jurisdictions_are_scheduled_exactly_once() -> None:
    plan = coordinate_jurisdictions(
        receipts={"MA": _two_row("MA"), "MS": _two_row("MS")},
        ledger_claims={"CO": _ledger("CO")},
    )
    assert len(plan.leases) == 51
    assert plan.scheduled_codes.count("MA") == 1
    assert plan.scheduled_codes.count("MS") == 1
    assert plan.scheduled_codes.count("CO") == 1
    assert plan.scheduled_codes.count("RI") == 1
    assert "MA" in plan.repair_codes
    assert "MS" in plan.repair_codes
    assert "CO" in plan.repair_codes
    assert plan.lease_for("MA").action == ACTION_REPAIR
    assert plan.lease_for("RI").action == ACTION_SCHEDULE
    assert len(plan.scheduled_codes) == len(set(plan.scheduled_codes)) == 51
    assert plan.reused_codes == ()
    assert plan.waiting_codes == ()


def test_verified_receipt_is_reused_and_not_scheduled() -> None:
    body = b"official-minnesota-statute-body"
    plan = coordinate_jurisdictions(
        receipts={"MN": _with_body("MN", body, fetched=20)},
        body_bytes={"MN": body},
    )
    assert "MN" in plan.reused_codes
    assert "MN" not in plan.scheduled_codes
    lease = plan.lease_for("MN")
    assert lease.action == ACTION_REUSE
    assert lease.prior_receipt_accepted is True
    assert lease.byte_verified is True
    assert lease.frontier_verified is True
    assert lease.holder == OUL_HOLDER
    assert len(plan.scheduled_codes) == 50


def test_live_foreign_lease_prevents_duplicate_scrape() -> None:
    plan = coordinate_jurisdictions(
        receipts={"TX": _two_row("TX")},
        live_foreign_leases=[
            {
                "jurisdiction_code": "TX",
                "holder": STATE_LAWS_HOLDER,
                "status": "active",
            }
        ],
    )
    lease = plan.lease_for("TX")
    assert lease.action == ACTION_WAIT
    assert lease.holder == STATE_LAWS_HOLDER
    assert lease.status == "wait"
    assert "TX" in plan.waiting_codes
    assert "TX" not in plan.scheduled_codes
    assert "TX" not in plan.reused_codes


def test_verified_receipt_wins_over_live_foreign_lease() -> None:
    body = b"official-utah-statute-body"
    plan = coordinate_jurisdictions(
        receipts={"UT": _with_body("UT", body, fetched=9)},
        body_bytes={"UT": body},
        live_foreign_leases=[
            {"jurisdiction_code": "UT", "holder": STATE_LAWS_HOLDER, "status": "active"}
        ],
    )
    assert plan.lease_for("UT").action == ACTION_REUSE
    assert "UT" not in plan.waiting_codes
    assert "UT" not in plan.scheduled_codes


def test_lease_registry_rejects_duplicate_scrape_lease() -> None:
    registry = LeaseRegistry()
    first = coordinate_jurisdictions().lease_for("GA")
    registry.acquire(first)
    with pytest.raises(DuplicateLeaseError):
        registry.acquire(
            coordinate_jurisdictions(
                live_foreign_leases=[
                    {
                        "jurisdiction_code": "GA",
                        "holder": STATE_LAWS_HOLDER,
                        "status": "active",
                    }
                ]
            ).lease_for("GA")
        )
    assert registry.duplicate_attempts == 1


def test_unique_schedule_and_require_exactly_once() -> None:
    ordered, duplicates = unique_schedule(["MA", "AL", "MA", "RI"])
    assert ordered == ("MA", "AL", "RI")
    assert duplicates == 1
    assert require_scheduled_exactly_once(["AL", "RI"]) == ("AL", "RI")
    with pytest.raises(DuplicateScheduleError):
        require_scheduled_exactly_once(["MA", "MA"])


def test_forbidden_default_jurisdiction_is_not_accepted() -> None:
    receipt = _closed("PR", fetched=20)
    admission = evaluate_prior_receipt(receipt)
    assert admission.accepted is False
    assert "forbidden_default_jurisdiction" in admission.rejection_kinds


def test_lease_ids_are_deterministic() -> None:
    assert lease_id_for("OR", OUL_HOLDER, ACTION_SCHEDULE) == lease_id_for(
        "OR", OUL_HOLDER, ACTION_SCHEDULE
    )
    assert lease_id_for("OR", OUL_HOLDER, ACTION_SCHEDULE) != lease_id_for(
        "OR", STATE_LAWS_HOLDER, ACTION_WAIT
    )


# ---------------------------------------------------------------------------
# Report / committed artifact
# ---------------------------------------------------------------------------


def test_build_payload_covers_exact_51_and_rejects_two_row_defaults() -> None:
    payload = build_acquisition_leases_payload(coordinate_jurisdictions())
    assert payload["jurisdiction_count"] == 51
    assert payload["authorizing_for_publication"] is False
    assert payload["task_id"] == TASK_ID
    assert len(payload["leases"]) == 51
    assert payload["leases"][-1]["jurisdiction_code"] == "DC"
    assert payload["required_jurisdiction_codes"] == list(CANONICAL_JURISDICTION_ORDER)
    assert set(payload["scheduled_jurisdiction_codes"]) == CANONICAL_JURISDICTIONS
    assert payload["accepted_receipts"] == []
    assert payload["checks"]["synthetic_two_row_rejected"] is True
    projection = validate_acquisition_leases(payload)
    assert projection["exact_51"] is True
    assert projection["dc_counted_once"] is True


def test_validate_rejects_accepted_two_row_and_duplicate_schedule() -> None:
    payload = build_acquisition_leases_payload(coordinate_jurisdictions())
    mutated = copy.deepcopy(payload)
    mutated["accepted_receipts"] = [
        {
            "byte_verified": True,
            "frontier_verified": True,
            "jurisdiction_code": "MA",
            "row_count": 2,
            "source_kind": "state_laws_cohort_report",
            "source_label": "fixture",
        }
    ]
    mutated["report_digest_sha256"] = sha256_json(
        {key: value for key, value in mutated.items() if key != "report_digest_sha256"}
    )
    with pytest.raises(LeaseReportError):
        validate_acquisition_leases(mutated)

    dup = copy.deepcopy(payload)
    dup["scheduled_jurisdiction_codes"] = list(dup["scheduled_jurisdiction_codes"]) + ["AL"]
    dup["scheduled_scrapes"] = list(dup["scheduled_scrapes"]) + [
        dict(dup["scheduled_scrapes"][0])
    ]
    dup["report_digest_sha256"] = sha256_json(
        {key: value for key, value in dup.items() if key != "report_digest_sha256"}
    )
    with pytest.raises(DuplicateScheduleError):
        validate_acquisition_leases(dup)


def test_require_live_fails_when_no_verified_receipts() -> None:
    payload = build_acquisition_leases_payload(coordinate_jurisdictions())
    with pytest.raises(LiveEvidenceRequiredError):
        require_live_verified_receipts(payload, cohort="A")
    body = b"official-alabama-statute-body"
    live = build_acquisition_leases_payload(
        coordinate_jurisdictions(
            receipts={"AL": _with_body("AL", body, fetched=30)},
            body_bytes={"AL": body},
        )
    )
    with pytest.raises(LiveEvidenceRequiredError):
        require_live_verified_receipts(live, cohort="A")
    require_live_verified_receipts(
        build_acquisition_leases_payload(
            coordinate_jurisdictions(
                receipts={
                    code: _with_body(code, f"body-{code}".encode(), fetched=11)
                    for code in cohort_codes("A")
                },
                body_bytes={code: f"body-{code}".encode() for code in cohort_codes("A")},
            )
        ),
        cohort="A",
    )


def test_write_and_check_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "acquisition_leases.json"
    payload = build_acquisition_leases_payload(coordinate_jurisdictions())
    write_acquisition_leases(path, payload)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["report_digest_sha256"] == payload["report_digest_sha256"]
    validate_acquisition_leases(loaded)


def test_committed_report_matches_builder_and_passes_invariants() -> None:
    path = default_lease_report_path()
    assert path.is_file(), f"missing committed report: {path}"
    report = check_committed_leases()
    assert report["status"] == "passed"
    assert report["exact_51"] is True
    assert report["dc_counted_once"] is True
    assert report["jurisdiction_count"] == 51
    assert report["authorizing_for_publication"] is False
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert committed["two_row_reports_rejected"] >= 1
    assert "MA" in committed["scheduled_jurisdiction_codes"]
    assert "MS" in committed["scheduled_jurisdiction_codes"]
    assert committed["accepted_receipts"] == []
    kinds = {
        kind
        for row in committed["rejected_prior_evidence"]
        for kind in row.get("rejection_kinds") or []
    }
    assert "synthetic_two_row" in kinds
    assert "untrusted_completion_ledger" in kinds
    scheduled = committed["scheduled_jurisdiction_codes"]
    assert scheduled.count("DC") == 1
    assert len(scheduled) == len(set(scheduled)) == 51


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_no_mutate_check_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--no-mutate", "--check"]) == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert "exact_51=True" in out


def test_cli_write_rejected_with_no_mutate() -> None:
    assert main(["--no-mutate", "--write"]) == 2


def test_cli_requires_check_or_write() -> None:
    assert main([]) == 2


def test_cli_require_live_fails_without_verified_receipts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--no-mutate", "--check", "--cohort", "A", "--require-live"]) == 1
    err = capsys.readouterr()
    text = err.err + err.out
    assert "require-live" in text.lower() or "FAILED" in text


def test_cli_check_json_is_secret_free(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--no-mutate", "--check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    serialized = json.dumps(payload)
    assert "hf_" not in serialized
    assert "Bearer " not in serialized
    assert "/home/" not in serialized


def test_cli_unknown_cohort_fails() -> None:
    assert main(["--no-mutate", "--check", "--cohort", "Z"]) == 1


def test_sha256_helpers_are_stable() -> None:
    assert sha256_bytes(b"abc") == sha256_text("abc")
    encoded = encode_acquisition_leases({"k": 1})
    assert encoded.endswith(b"\n")
    assert json.loads(encoded) == {"k": 1}
