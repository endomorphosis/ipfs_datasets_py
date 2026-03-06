from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "ops" / "legal_data" / "cleanup_procedural_rules_merged.py"
    spec = importlib.util.spec_from_file_location("cleanup_procedural_rules_merged", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_should_drop_asset_and_skip_labels() -> None:
    module = _load_module()

    drop, reason = module._should_drop(
        {
            "jurisdiction_code": "PA",
            "name": "Image 1: Arrow",
            "sourceUrl": "https://example.org/static/down.svg",
        },
        keep_ia_pdf_marker=True,
    )
    assert drop is True
    assert reason == "asset_url"

    drop, reason = module._should_drop(
        {
            "jurisdiction_code": "HI",
            "name": "Skip to Main Content",
            "sourceUrl": "https://example.org/rules",
        },
        keep_ia_pdf_marker=True,
    )
    assert drop is True
    assert reason == "skip_label"


def test_should_keep_iowa_pdf_marker_exception() -> None:
    module = _load_module()

    drop, reason = module._should_drop(
        {
            "jurisdiction_code": "IA",
            "name": "![Image 5: Click to view the PDF File",
            "sourceUrl": "https://www.legis.iowa.gov/images/pdf.png",
        },
        keep_ia_pdf_marker=True,
    )
    assert drop is False
    assert reason == ""

    drop, reason = module._should_drop(
        {
            "jurisdiction_code": "IA",
            "name": "![Image 5: Click to view the PDF File",
            "sourceUrl": "https://www.legis.iowa.gov/images/pdf.png",
        },
        keep_ia_pdf_marker=False,
    )
    assert drop is True
    assert reason == "asset_url"


def test_coverage_counts_full_partial_none() -> None:
    module = _load_module()

    rows = [
        {"jurisdiction_code": "AA", "procedure_family": "civil_procedure"},
        {"jurisdiction_code": "AA", "procedure_family": "criminal_procedure"},
        {"jurisdiction_code": "BB", "procedure_family": "civil_and_criminal_procedure"},
        {"jurisdiction_code": "CC", "procedure_family": "civil_procedure"},
        {"jurisdiction_code": "DD", "procedure_family": "other"},
    ]

    metrics = module._coverage(rows)
    assert metrics["records"] == 5
    assert metrics["states"] == 4
    assert metrics["full_both"] == 2
    assert metrics["partial"] == 1
    assert metrics["none"] == 1
    assert metrics["partial_states"] == ["CC"]


def test_main_in_place_with_backup_and_report(tmp_path, monkeypatch) -> None:
    module = _load_module()

    input_path = tmp_path / "merged.jsonl"
    output_path = tmp_path / "cleaned.jsonl"
    report_path = tmp_path / "report.json"
    backup_path = tmp_path / "backup.jsonl"

    rows = [
        {
            "jurisdiction_code": "IA",
            "procedure_family": "civil_procedure",
            "name": "![Image 5: Click to view the PDF File",
            "sourceUrl": "https://www.legis.iowa.gov/images/pdf.png",
        },
        {
            "jurisdiction_code": "IA",
            "procedure_family": "criminal_procedure",
            "name": "Iowa criminal chapter",
            "sourceUrl": "https://www.legis.iowa.gov/law/chapter.2.pdf",
        },
        {
            "jurisdiction_code": "IA",
            "procedure_family": "criminal_procedure",
            "name": "Image 1: Arrow",
            "sourceUrl": "https://example.org/static/down.svg",
        },
        {
            "jurisdiction_code": "IA",
            "procedure_family": "civil_procedure",
            "name": "Skip to Main Content",
            "sourceUrl": "https://example.org/rules",
        },
    ]
    input_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "cleanup_procedural_rules_merged.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--report-json",
            str(report_path),
            "--in-place",
            "--backup",
            str(backup_path),
        ],
    )

    rc = module.main()
    assert rc == 0

    # Input should be replaced with the cleaned output in in-place mode.
    input_rows = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(input_rows) == 2
    assert {r["procedure_family"] for r in input_rows} == {"civil_procedure", "criminal_procedure"}

    # Backup should preserve the original four-row input.
    backup_rows = [json.loads(line) for line in backup_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(backup_rows) == 4

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["in_place"] is True
    assert report["blocked_in_place"] is False
    assert report["removed_total"] == 2
    assert report["removed_by_reason"] == {"asset_url": 1, "skip_label": 1}


def test_main_in_place_blocks_on_coverage_regression(tmp_path, monkeypatch) -> None:
    module = _load_module()

    input_path = tmp_path / "merged.jsonl"
    output_path = tmp_path / "cleaned.jsonl"
    report_path = tmp_path / "report.json"
    backup_path = tmp_path / "backup.jsonl"

    rows = [
        {
            "jurisdiction_code": "IA",
            "procedure_family": "civil_procedure",
            "name": "![Image 5: Click to view the PDF File",
            "sourceUrl": "https://www.legis.iowa.gov/images/pdf.png",
        },
        {
            "jurisdiction_code": "IA",
            "procedure_family": "criminal_procedure",
            "name": "Iowa criminal chapter",
            "sourceUrl": "https://www.legis.iowa.gov/law/chapter.2.pdf",
        },
    ]
    input_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "cleanup_procedural_rules_merged.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--report-json",
            str(report_path),
            "--in-place",
            "--backup",
            str(backup_path),
            "--no-keep-ia-pdf-marker",
        ],
    )

    rc = module.main()
    assert rc == 2

    # In-place replacement should be blocked, so input stays unchanged and no backup is created.
    input_rows = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(input_rows) == 2
    assert backup_path.exists() is False

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["blocked_in_place"] is True
    assert report["coverage_check"]["regressed"] is True


def test_main_non_in_place_strict_coverage_regression(tmp_path, monkeypatch) -> None:
    module = _load_module()

    input_path = tmp_path / "merged.jsonl"
    output_path = tmp_path / "cleaned.jsonl"
    report_path = tmp_path / "report.json"
    rows = [
        {
            "jurisdiction_code": "IA",
            "procedure_family": "civil_procedure",
            "name": "![Image 5: Click to view the PDF File",
            "sourceUrl": "https://www.legis.iowa.gov/images/pdf.png",
        },
        {
            "jurisdiction_code": "IA",
            "procedure_family": "criminal_procedure",
            "name": "Iowa criminal chapter",
            "sourceUrl": "https://www.legis.iowa.gov/law/chapter.2.pdf",
        },
    ]
    input_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "cleanup_procedural_rules_merged.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--report-json",
            str(report_path),
            "--no-keep-ia-pdf-marker",
            "--require-equal-coverage",
        ],
    )

    rc = module.main()
    assert rc == 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["in_place"] is False
    assert report["enforce_coverage"] is True
    assert report["coverage_check"]["regressed"] is True
