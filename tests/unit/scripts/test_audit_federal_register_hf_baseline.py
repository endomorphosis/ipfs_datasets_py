"""Unit tests for LCR-048 pinned Federal Register baseline audit freeze."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ops.legal_data.audit_federal_register_hf_baseline import (
    ADVERTISED_DOCUMENT_COUNT,
    DATE_RANGE_COUNT,
    DATE_RANGE_END,
    DATE_RANGE_START,
    DATASET_REPO_ID,
    EMPTY_TEXT_ROW_COUNT,
    INCLUDE_FULL_TEXT,
    MATERIALIZED_ROW_COUNT,
    PINNED_REVISION,
    POST_ENDPOINT_DELTA_DOCUMENTS_MIN,
    RECOVERY_PLACEHOLDER_ROW_COUNT,
    REPORT_SCHEMA,
    REPOSITORY_FILE_COUNT,
    BaselineAuditError,
    acceptance_projection,
    build_fixture_baseline_report,
    check_baseline_report,
    default_report_path,
    expected_acceptance,
    expected_count_mismatch,
    expected_date_range,
    load_baseline_report,
    main,
    validate_baseline_report,
    write_baseline_report,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_expected_count_mismatch_is_five_recovery_placeholders() -> None:
    mismatch = expected_count_mismatch()
    assert mismatch == {
        "advertised_documents": 993_703,
        "materialized_rows": 993_708,
        "delta": 5,
        "recovery_placeholders": 5,
    }
    assert (
        mismatch["materialized_rows"] - mismatch["advertised_documents"]
        == mismatch["delta"]
        == RECOVERY_PLACEHOLDER_ROW_COUNT
    )


def test_expected_date_range_matches_plan() -> None:
    date_range = expected_date_range()
    assert date_range == {
        "start": "1994-01-01",
        "end": "2026-03-02",
        "date_range_count": 255,
        "inclusive": True,
    }


def test_fixture_report_acceptance_matches_sealed_inventory() -> None:
    report = build_fixture_baseline_report()
    acceptance = acceptance_projection(report)
    assert acceptance == expected_acceptance()
    assert acceptance == {
        "advertised_documents": 993_703,
        "materialized_rows": 993_708,
        "count_mismatch_delta": 5,
        "count_mismatch_present": True,
        "date_range_start": "1994-01-01",
        "date_range_end": "2026-03-02",
        "date_range_count": 255,
        "include_full_text": False,
        "missing_full_text": True,
        "missing_dataset_card": True,
        "legacy_layout": True,
        "pinned_revision": PINNED_REVISION,
        "repository_files": 555,
        "empty_text_rows": 358_455,
        "recovery_placeholder_rows": 5,
    }


def test_fixture_report_reproduces_plan_baseline_findings() -> None:
    report = build_fixture_baseline_report()
    assert report["schema"] == REPORT_SCHEMA
    assert report["dataset"]["repo_id"] == DATASET_REPO_ID
    assert report["dataset"]["revision"] == PINNED_REVISION
    assert report["dataset"]["revision_pinned"] is True
    assert report["dataset"]["has_dataset_card"] is False
    assert report["network_required"] is False
    assert report["unsuitable_as_source_of_truth"] is True

    counts = report["counts"]
    assert counts["repository_files"] == REPOSITORY_FILE_COUNT
    assert counts["advertised_documents"] == ADVERTISED_DOCUMENT_COUNT
    assert counts["materialized_rows"] == MATERIALIZED_ROW_COUNT
    assert counts["recovery_placeholder_rows"] == RECOVERY_PLACEHOLDER_ROW_COUNT
    assert counts["empty_text_rows"] == EMPTY_TEXT_ROW_COUNT
    assert counts["date_ranges"] == DATE_RANGE_COUNT
    assert counts["post_endpoint_delta_documents_min"] == POST_ENDPOINT_DELTA_DOCUMENTS_MIN

    mismatch = report["count_mismatch"]
    assert mismatch["advertised_documents"] == 993_703
    assert mismatch["materialized_rows"] == 993_708
    assert mismatch["delta"] == 5
    assert mismatch["mismatch_present"] is True

    date_range = report["date_range"]
    assert date_range["start"] == DATE_RANGE_START == "1994-01-01"
    assert date_range["end"] == DATE_RANGE_END == "2026-03-02"
    assert date_range["date_range_count"] == 255

    full_text = report["full_text"]
    assert full_text["include_full_text"] is INCLUDE_FULL_TEXT is False
    assert full_text["missing_full_text_contract"] is True
    assert full_text["empty_text_rows"] == 358_455
    assert full_text["abstract_cap_characters"] == 500

    card = report["dataset_card"]
    assert card["present"] is False
    assert card["missing"] is True
    assert card["declares_coherent_release_contract"] is False

    layout = report["legacy_layout"]
    assert layout["present"] is True
    assert layout["descriptor_complete_v2"] is False
    assert layout["root_level_jsonld"] is True
    assert layout["one_row_group_parquet"] is True
    assert layout["raw_json_shards"] is True
    assert layout["gte_small_faiss_metadata"] is True
    assert "metadata.json" in layout["artifacts"]
    assert "federal_register.parquet" in layout["artifacts"]
    assert "federal_register_gte_small.faiss" in layout["artifacts"]

    assert report["source_urls"]["all_parquet_source_url_empty"] is True
    assert report["recovery"]["placeholder_rows"] == 5
    assert report["recovery"]["must_quarantine"] is True
    assert report["post_endpoint_delta"]["legacy_endpoint"] == "2026-03-02"
    assert report["post_endpoint_delta"]["delta_start_inclusive"] == "2026-03-03"
    assert report["post_endpoint_delta"]["official_api_documents_min"] == 11_784
    assert len(report["code_hazards"]) >= 4

    anomaly_codes = {item["code"] for item in report["identity_anomalies"]}
    assert "ADVERTISED_VS_MATERIALIZED_COUNT_MISMATCH" in anomaly_codes
    assert "MISSING_FULL_TEXT_CONTRACT" in anomaly_codes
    assert "MISSING_DATASET_CARD" in anomaly_codes
    assert "LEGACY_LAYOUT" in anomaly_codes
    assert "EMPTY_SOURCE_URLS" in anomaly_codes
    assert "RECOVERY_PLACEHOLDER_ROWS" in anomaly_codes
    assert "POST_ENDPOINT_GAP" in anomaly_codes


def test_check_baseline_report_passes_for_fixture() -> None:
    report = build_fixture_baseline_report()
    result = check_baseline_report(report)
    assert result["ok"] is True
    assert result["pinned_revision"] == PINNED_REVISION
    assert result["mismatches"] == []


def test_validate_detects_count_tampering() -> None:
    report = build_fixture_baseline_report()
    report["counts"]["materialized_rows"] = 1
    report["acceptance"]["materialized_rows"] = 1
    report["count_mismatch"]["materialized_rows"] = 1
    mismatches = validate_baseline_report(report)
    assert any("materialized_rows" in item for item in mismatches)
    with pytest.raises(BaselineAuditError, match="baseline report check failed"):
        check_baseline_report(report)


def test_validate_detects_revision_tampering() -> None:
    report = build_fixture_baseline_report()
    report["dataset"]["revision"] = "main"
    report["acceptance"]["pinned_revision"] = "main"
    mismatches = validate_baseline_report(report)
    assert any("revision" in item or "pinned_revision" in item for item in mismatches)


def test_validate_detects_date_range_tampering() -> None:
    report = build_fixture_baseline_report()
    report["date_range"]["end"] = "2026-08-10"
    report["acceptance"]["date_range_end"] = "2026-08-10"
    mismatches = validate_baseline_report(report)
    assert any("date_range_end" in item for item in mismatches)


def test_validate_detects_full_text_contract_tampering() -> None:
    report = build_fixture_baseline_report()
    report["full_text"]["include_full_text"] = True
    report["full_text"]["missing_full_text_contract"] = False
    report["acceptance"]["include_full_text"] = True
    report["acceptance"]["missing_full_text"] = False
    mismatches = validate_baseline_report(report)
    assert any(
        "include_full_text" in item or "missing_full_text" in item
        for item in mismatches
    )


def test_validate_detects_legacy_layout_tampering() -> None:
    report = build_fixture_baseline_report()
    report["legacy_layout"]["present"] = False
    report["acceptance"]["legacy_layout"] = False
    mismatches = validate_baseline_report(report)
    assert any("legacy_layout" in item for item in mismatches)


def test_validate_detects_dataset_card_tampering() -> None:
    report = build_fixture_baseline_report()
    report["dataset_card"]["present"] = True
    report["dataset_card"]["missing"] = False
    report["dataset"]["has_dataset_card"] = True
    report["acceptance"]["missing_dataset_card"] = False
    mismatches = validate_baseline_report(report)
    assert any(
        "dataset_card" in item or "missing_dataset_card" in item
        for item in mismatches
    )


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
    out = tmp_path / "federal_baseline.json"
    write_baseline_report(report, out)
    reloaded = load_baseline_report(out)
    assert acceptance_projection(reloaded) == expected_acceptance()
    check_baseline_report(reloaded)
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    parsed = json.loads(text)
    assert parsed["counts"]["advertised_documents"] == 993_703
    assert parsed["acceptance"]["materialized_rows"] == 993_708


def test_main_fixture_only_check_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--fixture-only", "--check"])
    captured = capsys.readouterr()
    assert code == 0
    assert "ok=True" in captured.out
    assert PINNED_REVISION in captured.out
    assert "advertised=993703" in captured.out
    assert "materialized=993708" in captured.out
    assert "delta=5" in captured.out
    assert "date_range=1994-01-01..2026-03-02" in captured.out
    assert "include_full_text=False" in captured.out
    assert "missing_full_text=True" in captured.out
    assert "missing_dataset_card=True" in captured.out
    assert "legacy_layout=True" in captured.out
    assert "count_mismatch_present=True" in captured.out


def test_main_check_without_fixture_only_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["--check"])
    captured = capsys.readouterr()
    assert code == 1
    assert "fixture-only" in captured.err


def test_main_write_and_check_tmp(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "federal_baseline.json"
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
    report["counts"]["advertised_documents"] = 0
    report["acceptance"]["advertised_documents"] = 0
    report["count_mismatch"]["advertised_documents"] = 0
    write_baseline_report(report, out)
    code = main(["--fixture-only", "--check", "--report", str(out)])
    captured = capsys.readouterr()
    assert code == 1
    assert "error:" in captured.err


def test_constants_match_plan_acceptance_table() -> None:
    assert PINNED_REVISION == "720668ae016cc400916dda884c9005e03618edfa"
    assert DATASET_REPO_ID == "justicedao/ipfs_federal_register"
    assert ADVERTISED_DOCUMENT_COUNT == 993_703
    assert MATERIALIZED_ROW_COUNT == 993_708
    assert RECOVERY_PLACEHOLDER_ROW_COUNT == 5
    assert DATE_RANGE_START == "1994-01-01"
    assert DATE_RANGE_END == "2026-03-02"
    assert DATE_RANGE_COUNT == 255
    assert INCLUDE_FULL_TEXT is False
    assert EMPTY_TEXT_ROW_COUNT == 358_455
    assert REPOSITORY_FILE_COUNT == 555
    assert POST_ENDPOINT_DELTA_DOCUMENTS_MIN == 11_784


def test_machine_checkable_sections_present() -> None:
    """Effects clause: files, Viewer, counts, partitions, embeddings, hazards."""
    report = build_fixture_baseline_report()
    required: list[str] = [
        "counts",
        "metadata",
        "date_range",
        "count_mismatch",
        "full_text",
        "dataset_card",
        "legacy_layout",
        "source_urls",
        "recovery",
        "post_endpoint_delta",
        "viewer",
        "code_hazards",
        "identity_anomalies",
        "blocking_issues",
        "acceptance",
    ]
    for key in required:
        assert key in report, f"missing machine-checkable section {key}"
    assert report["count_mismatch"]["mismatch_present"] is True
    assert report["full_text"]["missing_full_text_contract"] is True
    assert report["dataset_card"]["missing"] is True
    assert report["legacy_layout"]["present"] is True
    assert report["dataset"]["revision"] == PINNED_REVISION
