"""Unit tests for LCR-005 frontier-closure and no-truncation audits."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_audit_module():
    script_path = (
        _repo_root()
        / "scripts"
        / "ops"
        / "legal_data"
        / "audit_state_laws_full_corpus.py"
    )
    spec = importlib.util.spec_from_file_location(
        "audit_state_laws_full_corpus", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit():
    return _load_audit_module()


@pytest.fixture(scope="module")
def fixture_payload(audit):
    return audit.load_fixture()


def test_fixture_exists_and_has_schema(audit) -> None:
    path = audit.default_fixture_path()
    assert path.is_file(), f"missing fixture: {path}"
    payload = audit.load_fixture(path)
    assert payload["schema"] == audit.FIXTURE_SCHEMA
    assert payload["task_id"] == "LCR-005"
    assert isinstance(payload["cases"], list) and payload["cases"]
    assert isinstance(payload["static_ast_snippets"], list) and payload["static_ast_snippets"]


def test_expected_jurisdiction_codes_cover_50_states_and_dc(audit) -> None:
    codes = audit.expected_jurisdiction_codes()
    assert len(codes) == 51
    assert "DC" in codes
    assert len(set(codes)) == 51
    for code in ("AL", "CA", "IA", "NY", "TX", "WA", "DC"):
        assert code in codes


def test_audit_catches_one_state_combined_overwrite(audit, fixture_payload) -> None:
    case = next(
        item
        for item in fixture_payload["cases"]
        if item["case_id"] == "one_state_combined_overwrite"
    )
    result = audit.audit_live_receipt_case(case)
    assert result.status == "fail"
    assert "one_state_combined_overwrite" in result.kinds
    assert result.section == "live_receipts"


def test_audit_catches_all_known_false_success_examples(audit, fixture_payload) -> None:
    expected = set(
        fixture_payload["known_false_success_examples"]["registry_truncation_success"]
    )
    caught: set[str] = set()
    for case in fixture_payload["cases"]:
        if not str(case.get("case_id", "")).startswith("false_success_registry_"):
            continue
        result = audit.audit_live_receipt_case(case)
        assert result.status == "fail", case["case_id"]
        assert "false_success_truncation" in result.kinds, case["case_id"]
        jurisdiction = case["receipt"]["jurisdiction"]
        caught.add(jurisdiction)
    assert caught == expected


def test_closed_ok_receipt_passes(audit, fixture_payload) -> None:
    case = next(item for item in fixture_payload["cases"] if item["case_id"] == "closed_ok_mn")
    result = audit.audit_live_receipt_case(case)
    assert result.status == "pass"
    assert result.findings == []
    assert result.kinds == []


@pytest.mark.parametrize(
    "authority",
    [None, "recovery", "unverified", "cache", "direct_insecure_tls"],
    ids=["missing", "recovery", "unverified", "cache", "direct-insecure-tls"],
)
def test_live_audit_requires_explicit_official_authority(
    audit, fixture_payload, authority
) -> None:
    original = next(
        item for item in fixture_payload["cases"] if item["case_id"] == "closed_ok_mn"
    )
    case = json.loads(json.dumps(original))
    case["case_id"] = f"authority-{authority or 'missing'}"
    case["receipt"]["official_source"] = True
    if authority is None:
        case["receipt"].pop("source_authority_class", None)
    else:
        case["receipt"]["source_authority_class"] = authority

    result = audit.audit_live_receipt_case(case)

    assert result.status == "fail"
    assert "unofficial_source_domain" in result.kinds
    assert any(
        "explicit official source authority" in finding.detail
        for finding in result.findings
    )


def test_open_frontier_and_continuation_links_fail(audit, fixture_payload) -> None:
    case = next(item for item in fixture_payload["cases"] if item["case_id"] == "open_frontier_hi")
    result = audit.audit_live_receipt_case(case)
    assert result.status == "fail"
    for kind in (
        "open_frontier",
        "enumerator_not_closed",
        "unvisited_continuation_links",
    ):
        assert kind in result.kinds


def test_disposition_arithmetic_mismatch_fails(audit, fixture_payload) -> None:
    case = next(
        item
        for item in fixture_payload["cases"]
        if item["case_id"] == "disposition_arithmetic_mismatch"
    )
    result = audit.audit_live_receipt_case(case)
    assert result.status == "fail"
    assert "disposition_arithmetic_mismatch" in result.kinds


def test_sample_cap_partial_checkpoint_and_boundary_probes_fail(
    audit, fixture_payload
) -> None:
    case = next(
        item
        for item in fixture_payload["cases"]
        if item["case_id"] == "sample_cap_partial_checkpoint"
    )
    result = audit.audit_live_receipt_case(case)
    assert result.status == "fail"
    for kind in (
        "sample_cap_present",
        "runtime_cap_present",
        "partial_checkpoint_promoted",
        "missing_boundary_probes",
    ):
        assert kind in result.kinds


def test_bundle_response_errors_and_unofficial_source_fail(
    audit, fixture_payload
) -> None:
    case = next(
        item
        for item in fixture_payload["cases"]
        if item["case_id"] == "bundle_and_response_errors"
    )
    result = audit.audit_live_receipt_case(case)
    assert result.status == "fail"
    for kind in (
        "bundle_count_mismatch",
        "response_errors_unresolved",
        "failed_final_nonzero",
        "unofficial_source_domain",
    ):
        assert kind in result.kinds


def test_exact_state_set_requires_dc(audit, fixture_payload) -> None:
    missing = next(
        item for item in fixture_payload["cases"] if item["case_id"] == "exact_set_missing_dc"
    )
    ok = next(
        item for item in fixture_payload["cases"] if item["case_id"] == "exact_set_ok_51"
    )
    missing_result = audit.audit_live_receipt_case(missing)
    ok_result = audit.audit_live_receipt_case(ok)
    assert missing_result.status == "fail"
    assert "exact_state_set_mismatch" in missing_result.kinds
    assert ok_result.status == "pass"
    assert ok_result.kinds == []


def test_static_ast_guards_flag_unguarded_seed_return(audit, fixture_payload) -> None:
    unguarded = next(
        item
        for item in fixture_payload["static_ast_snippets"]
        if item["case_id"] == "unguarded_seed_return"
    )
    guarded = next(
        item
        for item in fixture_payload["static_ast_snippets"]
        if item["case_id"] == "guarded_seed_return"
    )
    bad = audit.audit_static_snippet_case(unguarded)
    good = audit.audit_static_snippet_case(guarded)
    assert bad.status == "fail"
    assert "unguarded_seed_or_recovery_return" in bad.kinds
    assert bad.section == "static_ast_guards"
    assert good.status == "pass"
    assert good.kinds == []
    assert good.section == "static_ast_guards"


def test_fixture_audit_reports_static_and_live_separately(audit) -> None:
    report = audit.run_fixture_audit()
    assert "static_ast_guards" in report
    assert "live_receipts" in report
    assert report["static_ast_guards"]["status"] == "pass"
    assert report["live_receipts"]["status"] == "pass"
    assert report["acceptance"]["static_ast_guards_reported_separately"] is True
    assert report["acceptance"]["live_receipts_reported_separately"] is True
    assert report["acceptance"]["caught_one_state_combined_overwrite"] is True
    assert set(report["acceptance"]["caught_false_success_codes"]) == {
        "CO",
        "GA",
        "LA",
        "MA",
        "NJ",
    }
    assert report["acceptance"]["missing_false_success_codes"] == []
    assert report["acceptance"]["classification_mismatches"] == []
    assert report["status"] == "pass"
    assert report["network_required"] is False


def test_check_fixture_report_passes(audit) -> None:
    report = audit.run_fixture_audit()
    result = audit.check_fixture_report(report)
    assert result["ok"] is True
    assert result["static_ast_guards_status"] == "pass"
    assert result["live_receipts_status"] == "pass"


def test_check_fixture_report_fails_when_overwrite_not_caught(audit) -> None:
    report = audit.run_fixture_audit()
    report["acceptance"]["caught_one_state_combined_overwrite"] = False
    report["acceptance"]["gate_ok"] = False
    report["status"] = "fail"
    with pytest.raises(audit.FullCorpusAuditError, match="one-state combined overwrite"):
        audit.check_fixture_report(report)


def test_cli_fixture_only_check_exits_zero(audit) -> None:
    code = audit.main(["--fixture-only", "--check"])
    assert code == 0


def test_cli_check_without_fixture_only_fails(audit) -> None:
    code = audit.main(["--check"])
    assert code == 1


def test_cli_print_json_includes_separate_sections(audit, capsys) -> None:
    code = audit.main(["--fixture-only", "--check", "--print-json"])
    assert code == 0
    captured = capsys.readouterr()
    # JSON is on stdout; summary may share stdout before JSON.
    # Parse the last JSON object from stdout.
    text = captured.out.strip()
    start = text.find("{")
    assert start >= 0
    payload = json.loads(text[start:])
    assert "static_ast_guards" in payload
    assert "live_receipts" in payload
    assert payload["acceptance"]["caught_one_state_combined_overwrite"] is True


def test_audit_jurisdiction_receipt_detects_false_success_threshold(audit) -> None:
    result = audit.audit_jurisdiction_receipt(
        case_id="nj_false",
        receipt={
            "jurisdiction": "NJ",
            "status": "success",
            "source_domain": "lis.njleg.state.nj.us",
            "official_source": True,
            "mode": "full",
            "runtime_caps": None,
            "sample_cap": None,
            "checkpoint": {
                "partial": False,
                "promoted_success": False,
                "completion_basis": "source_frontier",
            },
            "frontier": {
                "closed": True,
                "enumerator_closed": True,
                "unvisited_continuation_links": [],
                "expected_index_units": 1,
                "visited_index_units": 1,
            },
            "bundles": {"expected_count": 1, "fetched_count": 1},
            "boundary_probes": {
                "first_hierarchy_unit": "t1",
                "last_hierarchy_unit": "t1",
                "pagination_total": 1,
                "bundle_total": 1,
            },
            "response_errors": [],
            "disposition": {
                "discovered": 1,
                "fetched": 1,
                "excluded": 0,
                "quarantined": 0,
                "failed_final": 0,
                "duplicates": 0,
            },
            "row_count": 1,
        },
    )
    assert result.status == "fail"
    assert "false_success_truncation" in result.kinds
