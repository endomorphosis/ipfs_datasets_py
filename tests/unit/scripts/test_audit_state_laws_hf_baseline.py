"""Unit tests for LCR-001 pinned state-laws baseline audit freeze."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ops.legal_data.audit_state_laws_hf_baseline import (
    CID_OVERLAP_COUNT,
    DATASET_REPO_ID,
    JURISDICTION_COUNT,
    MISSING_SUMMARIES,
    PER_STATE_CANONICAL_TOTAL_ROWS,
    PINNED_REVISION,
    REGISTRY_JURISDICTION_COUNT,
    REPORT_SCHEMA,
    REPOSITORY_FILE_COUNT,
    STATE_PARQUET_FILENAME_COUNT,
    STATE_SUMMARY_COUNT,
    TRUNCATION_EXAMPLES,
    VIEWER_CANONICAL_LABEL,
    VIEWER_CANONICAL_ROW_COUNT,
    VIEWER_EMBEDDING_JURISDICTION_COUNT,
    VIEWER_EMBEDDING_ROW_COUNT,
    BaselineAuditError,
    acceptance_projection,
    build_fixture_baseline_report,
    check_baseline_report,
    default_report_path,
    expected_acceptance,
    expected_jurisdiction_codes,
    expected_missing_summaries,
    expected_truncation_examples,
    load_baseline_report,
    main,
    validate_baseline_report,
    write_baseline_report,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_expected_jurisdiction_codes_cover_50_states_and_dc() -> None:
    codes = expected_jurisdiction_codes()
    assert len(codes) == JURISDICTION_COUNT == 51
    assert "DC" in codes
    assert len(set(codes)) == 51
    # Spot-check a few states plus DC.
    for code in ("AL", "CA", "NY", "TX", "WA", "DC"):
        assert code in codes


def test_fixture_report_acceptance_matches_sealed_inventory() -> None:
    report = build_fixture_baseline_report()
    acceptance = acceptance_projection(report)
    assert acceptance == expected_acceptance()
    assert acceptance == {
        "ia_only_canonical": True,
        "viewer_canonical_rows": 47_204,
        "viewer_canonical_label": "IA",
        "stale_51_state_embeddings": True,
        "viewer_embedding_rows": 17_338,
        "viewer_embedding_jurisdictions": 51,
        "per_state_total_rows": 212_103,
        "truncation_examples": {
            "GA": 2,
            "HI": 4,
            "IN": 4,
            "MS": 1,
            "WA": 1,
            "WV": 1,
        },
        "zero_cid_overlap": True,
        "cid_overlap_count": 0,
        "missing_summaries": ["CA", "DC"],
        "state_summaries_present": 49,
        "pinned_revision": PINNED_REVISION,
        "repository_files": 2_116,
        "jurisdictions": 51,
    }


def test_fixture_report_reproduces_plan_baseline_findings() -> None:
    report = build_fixture_baseline_report()
    assert report["schema"] == REPORT_SCHEMA
    assert report["dataset"]["repo_id"] == DATASET_REPO_ID
    assert report["dataset"]["revision"] == PINNED_REVISION
    assert report["dataset"]["revision_pinned"] is True
    assert report["network_required"] is False
    assert report["unsuitable_as_source_of_truth"] is True

    counts = report["counts"]
    assert counts["repository_files"] == REPOSITORY_FILE_COUNT
    assert counts["jurisdictions"] == JURISDICTION_COUNT
    assert counts["state_parquet_filenames"] == STATE_PARQUET_FILENAME_COUNT
    assert counts["viewer_canonical_rows"] == VIEWER_CANONICAL_ROW_COUNT
    assert counts["viewer_embedding_rows"] == VIEWER_EMBEDDING_ROW_COUNT
    assert counts["viewer_embedding_jurisdictions"] == VIEWER_EMBEDDING_JURISDICTION_COUNT
    assert counts["per_state_canonical_total_rows"] == PER_STATE_CANONICAL_TOTAL_ROWS
    assert counts["state_summaries_present"] == STATE_SUMMARY_COUNT
    assert counts["cid_overlap_canonical_vs_embeddings"] == CID_OVERLAP_COUNT

    canonical = report["viewer"]["canonical_config"]
    assert canonical["ia_only"] is True
    assert canonical["all_rows_labeled_ia"] is True
    assert canonical["row_count"] == 47_204
    assert canonical["jurisdiction_labels"] == [VIEWER_CANONICAL_LABEL]

    embeddings = report["viewer"]["embedding_config"]
    assert embeddings["stale_sample"] is True
    assert embeddings["row_count"] == 17_338
    assert embeddings["jurisdiction_count"] == 51

    assert report["cid_overlap"]["zero_overlap"] is True
    assert report["cid_overlap"]["canonical_vs_embeddings"] == 0

    per_state = report["per_state_files"]
    assert per_state["total_rows"] == 212_103
    assert per_state["filename_count"] == 51
    assert per_state["includes_dc"] is True
    assert per_state["truncation_examples"] == expected_truncation_examples()
    assert "STATE-DC.parquet" in per_state["filenames"]

    summaries = report["summaries"]
    assert summaries["present_count"] == 49
    assert summaries["missing"] == list(MISSING_SUMMARIES) == ["CA", "DC"]

    registry = report["completed_state_registry"]
    assert registry["jurisdiction_count"] == REGISTRY_JURISDICTION_COUNT == 47
    assert registry["marks_truncated_as_success"] is True
    assert registry["truncation_examples"]["NJ"] == 1
    assert registry["truncation_examples"]["GA"] == 2

    assert report["manifest"]["contains_absolute_local_paths"] is True
    assert report["local_salvage"]["admitted_without_new_gates"] is False
    assert len(report["code_hazards"]) >= 4

    anomaly_codes = {item["code"] for item in report["identity_anomalies"]}
    assert "IA_ONLY_CANONICAL_VIEWER" in anomaly_codes
    assert "STALE_51_STATE_EMBEDDINGS" in anomaly_codes
    assert "ZERO_CID_OVERLAP" in anomaly_codes
    assert "PER_STATE_TRUNCATION" in anomaly_codes
    assert "MISSING_STATE_SUMMARIES" in anomaly_codes


def test_truncation_examples_match_plan() -> None:
    examples = expected_truncation_examples()
    assert examples == dict(TRUNCATION_EXAMPLES)
    assert examples == {
        "GA": 2,
        "HI": 4,
        "IN": 4,
        "MS": 1,
        "WA": 1,
        "WV": 1,
    }


def test_missing_summaries_are_ca_and_dc() -> None:
    missing = expected_missing_summaries()
    assert missing == ["CA", "DC"]
    assert STATE_SUMMARY_COUNT + len(missing) == JURISDICTION_COUNT


def test_check_baseline_report_passes_for_fixture() -> None:
    report = build_fixture_baseline_report()
    result = check_baseline_report(report)
    assert result["ok"] is True
    assert result["pinned_revision"] == PINNED_REVISION
    assert result["mismatches"] == []


def test_validate_detects_count_tampering() -> None:
    report = build_fixture_baseline_report()
    report["counts"]["per_state_canonical_total_rows"] = 1
    report["acceptance"]["per_state_total_rows"] = 1
    report["per_state_files"]["total_rows"] = 1
    mismatches = validate_baseline_report(report)
    assert any("per_state_total_rows" in item for item in mismatches)
    with pytest.raises(BaselineAuditError, match="baseline report check failed"):
        check_baseline_report(report)


def test_validate_detects_revision_tampering() -> None:
    report = build_fixture_baseline_report()
    report["dataset"]["revision"] = "main"
    report["acceptance"]["pinned_revision"] = "main"
    mismatches = validate_baseline_report(report)
    assert any("revision" in item or "pinned_revision" in item for item in mismatches)


def test_validate_detects_cid_overlap_tampering() -> None:
    report = build_fixture_baseline_report()
    report["cid_overlap"]["canonical_vs_embeddings"] = 12
    report["cid_overlap"]["zero_overlap"] = False
    report["acceptance"]["cid_overlap_count"] = 12
    report["acceptance"]["zero_cid_overlap"] = False
    report["counts"]["cid_overlap_canonical_vs_embeddings"] = 12
    mismatches = validate_baseline_report(report)
    assert any("cid_overlap" in item or "zero_cid_overlap" in item for item in mismatches)


def test_validate_detects_ia_only_tampering() -> None:
    report = build_fixture_baseline_report()
    report["viewer"]["canonical_config"]["ia_only"] = False
    report["acceptance"]["ia_only_canonical"] = False
    mismatches = validate_baseline_report(report)
    assert any("ia_only" in item for item in mismatches)


def test_frozen_report_on_disk_matches_acceptance() -> None:
    path = default_report_path(_repo_root())
    assert path.is_file(), f"frozen report missing: {path}"
    report = load_baseline_report(path)
    check_baseline_report(report)
    assert acceptance_projection(report) == expected_acceptance()
    assert report["schema"] == REPORT_SCHEMA
    assert report["dataset"]["revision"] == PINNED_REVISION


def test_write_and_reload_round_trip(tmp_path: Path) -> None:
    report = build_fixture_baseline_report()
    out = tmp_path / "baseline.json"
    write_baseline_report(report, out)
    reloaded = load_baseline_report(out)
    assert acceptance_projection(reloaded) == expected_acceptance()
    check_baseline_report(reloaded)
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text)
    assert parsed["counts"]["jurisdictions"] == 51
    assert parsed["acceptance"]["per_state_total_rows"] == 212_103


def test_main_fixture_only_check_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--fixture-only", "--check"])
    captured = capsys.readouterr()
    assert code == 0
    assert "ok=True" in captured.out
    assert PINNED_REVISION in captured.out
    assert "viewer_canonical=47204" in captured.out
    assert "viewer_embeddings=17338" in captured.out
    assert "per_state_total=212103" in captured.out
    assert "cid_overlap=0" in captured.out
    assert "ia_only_canonical=True" in captured.out
    assert "stale_51_state_embeddings=True" in captured.out
    assert "zero_cid_overlap=True" in captured.out
    assert "GA=2" in captured.out
    assert "missing_summaries=CA,DC" in captured.out


def test_main_check_without_fixture_only_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["--check"])
    captured = capsys.readouterr()
    assert code == 1
    assert "fixture-only" in captured.err


def test_main_write_and_check_tmp(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "baseline.json"
    write_code = main(["--fixture-only", "--write", "--report", str(out)])
    assert write_code == 0
    assert out.is_file()
    check_code = main(["--fixture-only", "--check", "--report", str(out)])
    captured = capsys.readouterr()
    assert check_code == 0
    assert "ok=True" in captured.out


def test_main_detects_tampered_on_disk_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "tampered.json"
    report = build_fixture_baseline_report()
    report["counts"]["viewer_embedding_rows"] = 0
    report["acceptance"]["viewer_embedding_rows"] = 0
    report["viewer"]["embedding_config"]["row_count"] = 0
    write_baseline_report(report, out)
    code = main(["--fixture-only", "--check", "--report", str(out)])
    captured = capsys.readouterr()
    assert code == 1
    assert "error:" in captured.err


def test_constants_match_plan_acceptance_table() -> None:
    assert PINNED_REVISION == "42f0546acc7c6cd55627eaf51fb820d5613b9021"
    assert DATASET_REPO_ID == "justicedao/ipfs_state_laws"
    assert VIEWER_CANONICAL_ROW_COUNT == 47_204
    assert VIEWER_EMBEDDING_ROW_COUNT == 17_338
    assert VIEWER_EMBEDDING_JURISDICTION_COUNT == 51
    assert PER_STATE_CANONICAL_TOTAL_ROWS == 212_103
    assert CID_OVERLAP_COUNT == 0
    assert STATE_SUMMARY_COUNT == 49
    assert list(MISSING_SUMMARIES) == ["CA", "DC"]
    assert REPOSITORY_FILE_COUNT == 2_116
    assert JURISDICTION_COUNT == 51
    assert TRUNCATION_EXAMPLES["GA"] == 2
    assert TRUNCATION_EXAMPLES["HI"] == 4
    assert TRUNCATION_EXAMPLES["IN"] == 4
    assert TRUNCATION_EXAMPLES["MS"] == 1
    assert TRUNCATION_EXAMPLES["WA"] == 1
    assert TRUNCATION_EXAMPLES["WV"] == 1


def test_machine_checkable_sections_present() -> None:
    """Effects clause: files, Viewer, per-state, CID overlap, manifests, summaries, salvage, hazards."""
    report = build_fixture_baseline_report()
    required: list[str] = [
        "counts",
        "jurisdictions",
        "viewer",
        "cid_overlap",
        "per_state_files",
        "summaries",
        "manifest",
        "completed_state_registry",
        "local_salvage",
        "code_hazards",
        "identity_anomalies",
        "blocking_issues",
        "acceptance",
    ]
    for key in required:
        assert key in report, f"missing machine-checkable section {key}"
    assert report["viewer"]["canonical_config"]["ia_only"] is True
    assert report["viewer"]["embedding_config"]["stale_sample"] is True
    assert report["cid_overlap"]["zero_overlap"] is True
    assert report["per_state_files"]["total_rows"] == 212_103
    assert report["summaries"]["missing"] == ["CA", "DC"]
    assert report["dataset"]["revision"] == PINNED_REVISION
