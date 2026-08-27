"""Unit tests for LCR-023 acquisition evidence gap refill."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    get_official_source_catalog,
)
from scripts.ops.legal_data.certify_state_laws_full_scrape import aggregate_full_scrape
from scripts.ops.legal_data.state_laws_acquisition_gap_refill import (
    COHORT_LETTERS,
    EXPECTED_JURISDICTION_COUNT,
    REPORT_SCHEMA,
    TASK_ID,
    WORK_KIND_CODE_FAMILY,
    WORK_KIND_FRONTIER,
    WORK_KIND_JURISDICTION,
    AcquisitionGapRefillError,
    acceptance_projection,
    build_acceptance_report,
    check_acceptance_report,
    classify_gaps,
    classify_kind,
    default_coverage_path,
    default_receipt_dir,
    load_acceptance_report,
    load_json_object,
    main,
    map_gaps_to_work,
    write_acceptance_report,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _raw_committed_coverage() -> Dict[str, Any]:
    return load_json_object(default_coverage_path(_repo_root()))


def _raw_committed_receipts() -> Dict[str, Dict[str, Any]]:
    receipt_dir = default_receipt_dir(_repo_root())
    loaded: Dict[str, Dict[str, Any]] = {}
    for letter in COHORT_LETTERS:
        path = receipt_dir / f"cohort_{letter.lower()}.json"
        loaded[letter] = load_json_object(path)
    return loaded


def _committed_receipts() -> Dict[str, Dict[str, Any]]:
    """Promote compact fixtures into explicit synthetic live evidence."""

    receipts = _raw_committed_receipts()
    for payload in receipts.values():
        payload["evidence_mode"] = "live_full_corpus"
        payload["proves_software_contract_only"] = False
        payload.pop("statutes_sample_counts", None)
        for entry in (payload.get("jurisdiction_receipts") or {}).values():
            row_count = int(entry.get("row_count") or 0)
            content = entry.get("content") or {}
            entry["evidence_mode"] = "live_full_corpus"
            entry["source_artifact"] = {
                "row_count": row_count,
                "sha256": content.get("content_digest"),
            }
    return receipts


def _committed_coverage() -> Dict[str, Any]:
    """Build a passing synthetic coverage matrix for focused unit cases."""

    return aggregate_full_scrape(
        receipts=_committed_receipts(),
        require_jurisdictions=EXPECTED_JURISDICTION_COUNT,
        repo_root=_repo_root(),
    )


def _write_receipts(tmp_path: Path, receipts: Dict[str, Dict[str, Any]]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    for letter, payload in receipts.items():
        (tmp_path / f"cohort_{letter.lower()}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return tmp_path


def _write_coverage(tmp_path: Path, coverage: Dict[str, Any]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "full_scrape_coverage.json"
    path.write_text(
        json.dumps(coverage, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def test_synthetic_live_coverage_closes_with_51_passing_and_zero_work() -> None:
    coverage = _committed_coverage()
    report = build_acceptance_report(
        coverage,
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
    )
    assert report["status"] == "pass"
    assert report["schema"] == REPORT_SCHEMA
    assert report["task_id"] == TASK_ID
    assert report["passing_receipt_count"] == EXPECTED_JURISDICTION_COUNT == 51
    assert len(report["passing_current_receipts"]) == 51
    codes = [row["jurisdiction"] for row in report["passing_current_receipts"]]
    assert len(set(codes)) == 51
    assert "DC" in codes
    assert report["remaining_gaps"] == []
    assert report["remaining_gap_count"] == 0
    assert report["ready_work"] == []
    assert report["ready_work_count"] == 0
    assert report["unresolved_findings"] == []
    assert report["downstream_admission_blocked"] is False
    assert report["acceptance"]["exact_51_passing_receipts"] is True
    assert report["acceptance"]["zero_unresolved_findings"] is True
    assert report["acceptance"]["no_hub_upload"] is True
    check_acceptance_report(report)
    serialized = json.dumps(report)
    assert "/home/" not in serialized
    assert "hf_" not in serialized or "hf_token" not in serialized.lower()


def test_committed_compact_coverage_remains_blocked() -> None:
    report = build_acceptance_report(
        _raw_committed_coverage(),
        coverage_path=default_coverage_path(_repo_root()),
        receipt_dir=default_receipt_dir(_repo_root()),
        repo_root=_repo_root(),
    )

    assert report["status"] == "fail"
    assert report["passing_receipt_count"] == 0
    assert report["remaining_gap_count"] > 0
    assert report["ready_work_count"] > 0
    assert report["downstream_admission_blocked"] is True
    with pytest.raises(AcquisitionGapRefillError):
        check_acceptance_report(report)


def test_synthetic_report_names_content_ids_of_all_inputs() -> None:
    report = build_acceptance_report(
        _committed_coverage(),
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
    )
    inputs = report["inputs"]
    assert inputs["coverage_matrix"]["content_id"].startswith("sha256:")
    assert inputs["official_source_catalog"]["content_id"].startswith("sha256:")
    assert len(inputs["cohort_receipts"]) == 13
    letters = [item["cohort"] for item in inputs["cohort_receipts"]]
    assert letters == list(COHORT_LETTERS)
    for item in inputs["cohort_receipts"]:
        assert item["content_id"].startswith("sha256:")
        assert "/home/" not in item["path"]
    for row in report["passing_current_receipts"]:
        assert row["content_digest"]
        assert str(row["content_digest"]).startswith("sha256:")
        assert row["code_family_ids"]


def test_open_frontier_maps_to_frontier_child_work() -> None:
    coverage = _committed_coverage()
    coverage["status"] = "fail"
    coverage["findings"] = ["IL: open frontier"]
    coverage["matrix"]["IL"]["frontier_closed"] = False
    coverage["matrix"]["IL"]["complete"] = False
    coverage["acceptance"]["closed_frontier"] = False
    gaps = classify_gaps(coverage)
    assert any(
        item["jurisdiction"] == "IL" and item["kind"] == WORK_KIND_FRONTIER for item in gaps
    )
    catalog = get_official_source_catalog()
    work = map_gaps_to_work(gaps, catalog=catalog, coverage=coverage)
    assert work
    frontier = [item for item in work if item["jurisdiction"] == "IL" and item["kind"] == WORK_KIND_FRONTIER]
    assert frontier
    assert frontier[0]["code_family_id"]
    assert frontier[0]["replacement_receipt_required"] is True
    assert frontier[0]["status"] == "ready"
    report = build_acceptance_report(
        coverage,
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
    )
    assert report["status"] == "fail"
    assert report["remaining_gap_count"] >= 1
    assert report["ready_work_count"] >= 1
    assert report["downstream_admission_blocked"] is True
    with pytest.raises(AcquisitionGapRefillError):
        check_acceptance_report(report)


def test_missing_jurisdiction_maps_to_jurisdiction_child_work() -> None:
    coverage = _committed_coverage()
    del coverage["matrix"]["DC"]
    coverage["jurisdictions"] = [
        row for row in coverage["jurisdictions"] if row.get("jurisdiction") != "DC"
    ]
    coverage["missing_jurisdictions"] = ["DC"]
    coverage["findings"] = ["DC: missing from cohort union"]
    coverage["status"] = "fail"
    coverage["includes_dc"] = False
    coverage["observed_jurisdiction_count"] = 50
    gaps = classify_gaps(coverage)
    assert any(item["jurisdiction"] == "DC" and item["kind"] == WORK_KIND_JURISDICTION for item in gaps)
    report = build_acceptance_report(
        coverage,
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
    )
    assert report["status"] == "fail"
    assert report["passing_receipt_count"] == 50
    dc_work = [item for item in report["ready_work"] if item["jurisdiction"] == "DC"]
    assert dc_work
    assert dc_work[0]["kind"] == WORK_KIND_JURISDICTION
    assert dc_work[0]["code_family_id"] == "dc-official-code"


def test_stale_keys_map_to_code_family_child_work() -> None:
    coverage = _committed_coverage()
    coverage["status"] = "fail"
    coverage["findings"] = ["TX: stale or drifted index keys"]
    coverage["matrix"]["TX"]["stale_keys"] = ["tx:stale"]
    coverage["matrix"]["TX"]["index_parity_ok"] = False
    coverage["matrix"]["TX"]["complete"] = False
    assert classify_kind("TX: stale or drifted index keys") == WORK_KIND_CODE_FAMILY
    report = build_acceptance_report(
        coverage,
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
    )
    family_work = [
        item
        for item in report["ready_work"]
        if item["jurisdiction"] == "TX" and item["kind"] == WORK_KIND_CODE_FAMILY
    ]
    assert family_work
    assert family_work[0]["code_family_id"] == "texas-statutes"


def test_failed_final_maps_to_frontier_work() -> None:
    coverage = _committed_coverage()
    coverage["status"] = "fail"
    coverage["findings"] = ["MO: failed_final=1"]
    coverage["matrix"]["MO"]["failed_final"] = 1
    coverage["matrix"]["MO"]["complete"] = False
    report = build_acceptance_report(
        coverage,
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
    )
    assert any(
        item["jurisdiction"] == "MO" and item["kind"] == WORK_KIND_FRONTIER
        for item in report["ready_work"]
    )


def test_absence_of_ready_work_with_gaps_fails_closed() -> None:
    coverage = _committed_coverage()
    coverage["status"] = "fail"
    coverage["findings"] = ["CA: open frontier"]
    coverage["matrix"]["CA"]["frontier_closed"] = False
    coverage["matrix"]["CA"]["complete"] = False
    with pytest.raises(AcquisitionGapRefillError, match="absence of ready work"):
        build_acceptance_report(
            coverage,
            receipts=_committed_receipts(),
            repo_root=_repo_root(),
            ready_work=[],
        )
    synthetic = {
        "schema": REPORT_SCHEMA,
        "task_id": TASK_ID,
        "status": "fail",
        "passing_current_receipts": [],
        "passing_receipt_count": 0,
        "unresolved_findings": ["CA: open frontier"],
        "remaining_gaps": [{"kind": WORK_KIND_FRONTIER, "jurisdiction": "CA"}],
        "ready_work": [],
        "acceptance": {},
        "inputs": {},
    }
    with pytest.raises(AcquisitionGapRefillError, match="absence of ready work"):
        check_acceptance_report(synthetic)


def test_absence_of_ready_work_with_zero_gaps_is_success() -> None:
    report = build_acceptance_report(
        _committed_coverage(),
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
        ready_work=[],
        gaps=[],
    )
    assert report["status"] == "pass"
    assert report["ready_work"] == []
    assert report["remaining_gaps"] == []
    check_acceptance_report(report)


def test_home_path_and_token_material_fail(tmp_path: Path) -> None:
    coverage = _committed_coverage()
    coverage["debug_path"] = "/home/runner/work/secret.json"
    with pytest.raises(AcquisitionGapRefillError, match="home|token"):
        build_acceptance_report(
            coverage,
            receipts=_committed_receipts(),
            repo_root=_repo_root(),
        )
    coverage = _committed_coverage()
    coverage["hf_token"] = "hf_abcdefghijklmnop"
    with pytest.raises(AcquisitionGapRefillError, match="token"):
        build_acceptance_report(
            coverage,
            receipts=_committed_receipts(),
            repo_root=_repo_root(),
        )


def test_write_refuses_home_paths(tmp_path: Path) -> None:
    report = build_acceptance_report(
        _committed_coverage(),
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
    )
    poisoned = dict(report)
    poisoned["note"] = "/home/runner/secret"
    with pytest.raises(AcquisitionGapRefillError, match="home|token"):
        write_acceptance_report(poisoned, tmp_path / "should-not-write.json")
    assert not (tmp_path / "should-not-write.json").exists()


def test_hermetic_tmp_receipts_and_mutated_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipts = _committed_receipts()
    receipt_dir = _write_receipts(tmp_path / "receipts", receipts)
    coverage = _committed_coverage()
    coverage["status"] = "fail"
    coverage["findings"] = ["WA: truncated by sample/runtime cap"]
    coverage["matrix"]["WA"]["sample_cap"] = 25
    coverage["matrix"]["WA"]["complete"] = False
    coverage_path = _write_coverage(tmp_path / "coverage", coverage)
    report_path = tmp_path / "full_scrape_acceptance.json"
    code = main(
        [
            "--coverage",
            str(coverage_path),
            "--receipt-dir",
            str(receipt_dir),
            "--report",
            str(report_path),
            "--check",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "RESULT: FAIL" in captured.err
    live = build_acceptance_report(
        coverage,
        coverage_path=coverage_path,
        receipt_dir=receipt_dir,
        repo_root=_repo_root(),
    )
    assert live["status"] == "fail"
    assert any(item["jurisdiction"] == "WA" and item["kind"] == WORK_KIND_FRONTIER for item in live["ready_work"])
    serialized = json.dumps(live)
    assert "/home/" not in serialized


def test_write_and_cli_check_on_tmp_passing_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipts = _committed_receipts()
    receipt_dir = _write_receipts(tmp_path / "receipts", receipts)
    coverage_path = _write_coverage(tmp_path / "coverage", _committed_coverage())
    report_path = tmp_path / "full_scrape_acceptance.json"
    write_code = main(
        [
            "--coverage",
            str(coverage_path),
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
    on_disk = load_acceptance_report(report_path)
    assert on_disk["passing_receipt_count"] == 51
    assert on_disk["remaining_gaps"] == []
    check_code = main(
        [
            "--coverage",
            str(coverage_path),
            "--receipt-dir",
            str(receipt_dir),
            "--report",
            str(report_path),
            "--check",
        ]
    )
    captured = capsys.readouterr()
    assert check_code == 0
    assert "RESULT: PASS" in captured.out
    assert "passing_receipts: 51" in captured.out
    assert "remaining_gaps: 0" in captured.out
    assert acceptance_projection(on_disk) == acceptance_projection(
        build_acceptance_report(
            _committed_coverage(),
            coverage_path=coverage_path,
            receipt_dir=receipt_dir,
            repo_root=_repo_root(),
        )
    )


def test_cli_check_against_committed(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--check"])
    captured = capsys.readouterr()
    assert code == 1
    assert "RESULT: FAIL" in captured.err
    assert '"passing_receipt_count": 0' in captured.out


def test_script_does_not_upload_or_contact_hub() -> None:
    source = (
        _repo_root()
        / "scripts"
        / "ops"
        / "legal_data"
        / "state_laws_acquisition_gap_refill.py"
    ).read_text(encoding="utf-8")
    assert "huggingface_hub" not in source
    assert "HfApi" not in source
    assert "upload_file" not in source
    assert "upload_folder" not in source
    assert "no Hub upload" in source


def test_refill_does_not_mutate_coverage_or_receipts() -> None:
    coverage = _committed_coverage()
    original_coverage = json.dumps(coverage, sort_keys=True)
    receipts = _committed_receipts()
    original_dc = json.dumps(receipts["M"]["jurisdiction_receipts"]["DC"], sort_keys=True)
    build_acceptance_report(
        coverage,
        receipts=receipts,
        repo_root=_repo_root(),
    )
    assert json.dumps(coverage, sort_keys=True) == original_coverage
    assert json.dumps(receipts["M"]["jurisdiction_receipts"]["DC"], sort_keys=True) == original_dc


def test_secondary_source_is_jurisdiction_work() -> None:
    coverage = _committed_coverage()
    coverage["status"] = "fail"
    coverage["findings"] = ["MA: secondary-only or unofficial source"]
    coverage["matrix"]["MA"]["official_source"] = False
    coverage["matrix"]["MA"]["source_authority_class"] = "secondary"
    coverage["matrix"]["MA"]["complete"] = False
    report = build_acceptance_report(
        coverage,
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
    )
    assert any(
        item["jurisdiction"] == "MA" and item["kind"] == WORK_KIND_JURISDICTION
        for item in report["ready_work"]
    )


@pytest.mark.parametrize(
    "authority",
    [None, "recovery", "unverified", "cache", "direct_insecure_tls"],
    ids=["missing", "recovery", "unverified", "cache", "direct-insecure-tls"],
)
def test_non_official_authority_is_jurisdiction_work(
    authority: str | None,
) -> None:
    coverage = _committed_coverage()
    cell = coverage["matrix"]["MA"]
    cell["official_source"] = True
    cell["complete"] = True
    if authority is None:
        cell.pop("source_authority_class", None)
    else:
        cell["source_authority_class"] = authority

    report = build_acceptance_report(
        coverage,
        receipts=_committed_receipts(),
        repo_root=_repo_root(),
    )

    assert report["status"] == "fail"
    assert report["downstream_admission_blocked"] is True
    assert not any(
        row["jurisdiction"] == "MA" for row in report["passing_current_receipts"]
    )
    assert any(
        item["jurisdiction"] == "MA" and item["kind"] == WORK_KIND_JURISDICTION
        for item in report["ready_work"]
    )
