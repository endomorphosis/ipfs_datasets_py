"""Unit tests for LCR-022 exact-51 full-scrape coverage aggregation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from scripts.ops.legal_data.certify_state_laws_full_scrape import (
    COHORT_LETTERS,
    EXPECTED_JURISDICTION_COUNT,
    REPORT_SCHEMA,
    TASK_ID,
    FullScrapeCertifyError,
    acceptance_projection,
    aggregate_full_scrape,
    canonical_jurisdictions,
    check_coverage_report,
    default_receipt_dir,
    default_report_path,
    load_coverage_report,
    load_json_object,
    main,
    write_coverage_report,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _committed_receipts() -> Dict[str, Dict[str, Any]]:
    receipt_dir = default_receipt_dir(_repo_root())
    loaded: Dict[str, Dict[str, Any]] = {}
    for letter in COHORT_LETTERS:
        path = receipt_dir / f"cohort_{letter.lower()}.json"
        loaded[letter] = load_json_object(path)
    return loaded


def _write_receipts(tmp_path: Path, receipts: Dict[str, Dict[str, Any]]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    for letter, payload in receipts.items():
        (tmp_path / f"cohort_{letter.lower()}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return tmp_path


def test_canonical_set_is_exact_51_including_dc() -> None:
    codes = canonical_jurisdictions()
    assert len(codes) == EXPECTED_JURISDICTION_COUNT == 51
    assert len(set(codes)) == 51
    assert codes[-1] == "DC"
    assert "DC" in codes
    for code in ("AL", "CA", "NY", "TX", "WA", "WI", "WY", "DC"):
        assert code in codes


def test_committed_receipts_aggregate_to_pass() -> None:
    report = aggregate_full_scrape(require_jurisdictions=51, repo_root=_repo_root())
    assert report["status"] == "pass"
    assert report["schema"] == REPORT_SCHEMA
    assert report["task_id"] == TASK_ID
    assert report["observed_jurisdiction_count"] == 51
    assert report["includes_dc"] is True
    assert report["missing_jurisdictions"] == []
    assert report["extra_jurisdictions"] == []
    assert report["duplicate_jurisdictions"] == []
    assert report["production_upload"] is False
    assert report["findings"] == []
    assert report["totals"]["failed_final"] == 0
    assert report["totals"]["success_count"] == 51
    assert set(report["matrix"]) == set(report["canonical_jurisdictions"])
    assert "DC" in report["matrix"]
    check_coverage_report(report)
    serialized = json.dumps(report)
    assert "/home/" not in serialized
    assert "hf_" not in serialized or "hf_token" not in serialized.lower()


def test_committed_report_round_trip_matches_acceptance() -> None:
    path = default_report_path(_repo_root())
    assert path.is_file(), f"frozen coverage report missing: {path}"
    on_disk = load_coverage_report(path)
    live = aggregate_full_scrape(require_jurisdictions=51, repo_root=_repo_root())
    check_coverage_report(on_disk)
    check_coverage_report(live)
    assert acceptance_projection(on_disk) == acceptance_projection(live)
    assert on_disk["canonical_jurisdictions"] == live["canonical_jurisdictions"]
    assert on_disk["observed_jurisdiction_count"] == 51
    assert "DC" in on_disk["matrix"]


def test_missing_jurisdiction_fails() -> None:
    receipts = _committed_receipts()
    del receipts["M"]["jurisdiction_receipts"]["DC"]
    del receipts["M"]["state_results"]["DC"]
    receipts["M"]["states"] = ["WI", "WY"]
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert "DC" in report["missing_jurisdictions"]
    assert any("DC" in item and "missing" in item for item in report["findings"])
    with pytest.raises(FullScrapeCertifyError):
        check_coverage_report(report)


def test_duplicate_jurisdiction_fails() -> None:
    receipts = _committed_receipts()
    duplicate = json.loads(json.dumps(receipts["A"]["jurisdiction_receipts"]["AL"]))
    receipts["B"]["jurisdiction_receipts"]["AL"] = duplicate
    receipts["B"]["state_results"]["AL"] = json.loads(
        json.dumps(receipts["A"]["state_results"]["AL"])
    )
    receipts["B"]["states"] = list(receipts["B"]["states"]) + ["AL"]
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert "AL" in report["duplicate_jurisdictions"]
    assert any("duplicate" in item for item in report["findings"])


def test_failed_final_nonzero_fails() -> None:
    receipts = _committed_receipts()
    receipts["A"]["jurisdiction_receipts"]["AK"]["failed_final"] = 3
    receipts["A"]["jurisdiction_receipts"]["AK"]["disposition"]["failed_final"] = 3
    receipts["A"]["jurisdiction_receipts"]["AK"]["disposition"]["discovered"] = 5
    receipts["A"]["state_results"]["AK"]["failed_final"] = 3
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert report["acceptance"]["failed_final_zero"] is False
    assert any("failed_final=3" in item for item in report["findings"])


def test_production_upload_fails() -> None:
    receipts = _committed_receipts()
    receipts["C"]["production_upload"] = True
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert report["production_upload"] is True
    assert report["acceptance"]["no_production_upload"] is False
    assert any("production_upload" in item for item in report["findings"])


def test_non_success_status_fails() -> None:
    receipts = _committed_receipts()
    receipts["B"]["jurisdiction_receipts"]["CA"]["status"] = "partial_success"
    receipts["B"]["state_results"]["CA"]["status"] = "partial_success"
    receipts["B"]["status"] = "partial_success"
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert report["acceptance"]["all_success"] is False
    assert any("status=partial_success" in item for item in report["findings"])


def test_open_frontier_fails() -> None:
    receipts = _committed_receipts()
    receipts["D"]["jurisdiction_receipts"]["IL"]["frontier"]["closed"] = False
    receipts["D"]["state_results"]["IL"]["frontier_closed"] = False
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert report["acceptance"]["closed_frontier"] is False
    assert any("open frontier" in item or "frontier.closed" in item for item in report["findings"])


def test_secondary_source_fails() -> None:
    receipts = _committed_receipts()
    receipts["F"]["jurisdiction_receipts"]["MA"]["official_source"] = False
    receipts["F"]["jurisdiction_receipts"]["MA"]["source_authority_class"] = "secondary"
    receipts["F"]["jurisdiction_receipts"]["MA"]["source_domain"] = "www.justia.com"
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert report["acceptance"]["official_source_only"] is False
    assert any("secondary" in item or "unofficial" in item for item in report["findings"])


def test_stale_keys_and_truncation_fail() -> None:
    receipts = _committed_receipts()
    receipts["K"]["jurisdiction_receipts"]["TX"]["index_keys"]["stale_keys"] = ["tx:stale"]
    receipts["K"]["jurisdiction_receipts"]["TX"]["index_keys"]["parity_ok"] = False
    receipts["K"]["jurisdiction_receipts"]["TX"]["sample_cap"] = 25
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert report["acceptance"]["no_stale_keys"] is False
    assert report["acceptance"]["no_truncation"] is False


def test_home_path_and_token_material_fail(tmp_path: Path) -> None:
    receipts = _committed_receipts()
    receipts["A"]["debug_path"] = "/home/runner/work/secret.json"
    receipts["B"]["hf_token"] = "hf_abcdefghijklmnop"
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert any("/home/" in item for item in report["findings"])
    assert any("token" in item for item in report["findings"])
    with pytest.raises(FullScrapeCertifyError, match="home|token"):
        write_coverage_report(report, tmp_path / "should-not-write.json")


def test_require_jurisdictions_cannot_redefine_downward() -> None:
    receipts = _committed_receipts()
    report = aggregate_full_scrape(receipts=receipts, require_jurisdictions=50)
    assert report["status"] == "fail"
    assert any("require-jurisdictions=50" in item for item in report["findings"])
    assert any("downward redefinition" in item for item in report["findings"])


def test_missing_cohort_receipt_file_fails(tmp_path: Path) -> None:
    receipts = _committed_receipts()
    del receipts["M"]
    _write_receipts(tmp_path, receipts)
    report = aggregate_full_scrape(receipt_dir=tmp_path, require_jurisdictions=51)
    assert report["status"] == "fail"
    assert any("cohort M" in item and "missing" in item for item in report["findings"])
    assert "DC" in report["missing_jurisdictions"]


def test_write_and_cli_check_on_tmp_receipts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    receipts = _committed_receipts()
    receipt_dir = _write_receipts(tmp_path / "receipts", receipts)
    report_path = tmp_path / "full_scrape_coverage.json"
    write_code = main(
        [
            "--require-jurisdictions",
            "51",
            "--receipt-dir",
            str(receipt_dir),
            "--report",
            str(report_path),
            "--write",
        ]
    )
    assert write_code == 0
    assert report_path.is_file()
    text = report_path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "/home/" not in text
    check_code = main(
        [
            "--require-jurisdictions",
            "51",
            "--check",
            "--receipt-dir",
            str(receipt_dir),
            "--report",
            str(report_path),
        ]
    )
    captured = capsys.readouterr()
    assert check_code == 0
    assert "RESULT: PASS" in captured.out
    assert "jurisdictions: 51" in captured.out
    assert "includes_dc: True" in captured.out


def test_cli_check_fails_on_failed_final(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    receipts = _committed_receipts()
    receipts["G"]["jurisdiction_receipts"]["MO"]["failed_final"] = 1
    receipts["G"]["jurisdiction_receipts"]["MO"]["disposition"]["failed_final"] = 1
    receipts["G"]["jurisdiction_receipts"]["MO"]["disposition"]["discovered"] = 3
    receipts["G"]["state_results"]["MO"]["failed_final"] = 1
    receipt_dir = _write_receipts(tmp_path / "receipts", receipts)
    report_path = tmp_path / "coverage.json"
    code = main(
        [
            "--require-jurisdictions",
            "51",
            "--check",
            "--receipt-dir",
            str(receipt_dir),
            "--report",
            str(report_path),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "RESULT: FAIL" in captured.err


def test_cli_require_51_check_against_committed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["--require-jurisdictions", "51", "--check"])
    captured = capsys.readouterr()
    assert code == 0
    assert "RESULT: PASS" in captured.out
    assert "jurisdictions: 51" in captured.out


def test_script_does_not_upload_or_contact_hub() -> None:
    source = (
        _repo_root()
        / "scripts"
        / "ops"
        / "legal_data"
        / "certify_state_laws_full_scrape.py"
    ).read_text(encoding="utf-8")
    assert "huggingface_hub" not in source
    assert "HfApi" not in source
    assert "upload_file" not in source
    assert "upload_folder" not in source
    assert "no Hub upload" in source


def test_aggregator_does_not_mutate_input_receipts() -> None:
    receipts = _committed_receipts()
    original = json.dumps(receipts["M"]["jurisdiction_receipts"]["DC"], sort_keys=True)
    aggregate_full_scrape(receipts=receipts, require_jurisdictions=51)
    assert json.dumps(receipts["M"]["jurisdiction_receipts"]["DC"], sort_keys=True) == original
