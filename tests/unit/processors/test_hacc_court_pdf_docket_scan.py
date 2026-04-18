from __future__ import annotations

import json
from pathlib import Path

from reportlab.pdfgen import canvas
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_data_hacc import (
    analyze_pdf_for_court_case,
    load_scan_manifest,
    scan_hacc_pdfs_for_dockets,
    summarize_scan_manifest,
)
import ipfs_datasets_py.processors.legal_data_hacc.court_pdf_docket_scan as scan_module


def _write_pdf(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    y_position = 800
    for line in lines:
        pdf.drawString(72, y_position, line)
        y_position -= 16
    pdf.save()


def test_analyze_pdf_for_court_case_uses_ocr_fallback(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned_case.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 mock")

    monkeypatch.setattr(scan_module, "_extract_text_from_pdf", lambda path: "")
    monkeypatch.setattr(
        scan_module,
        "_extract_pdf_ocr_text",
        lambda path, max_pages=5: "IN THE UNITED STATES DISTRICT COURT\nCase No. 1:24-cv-9999\nDoe v. Example\nComplaint",
    )

    result = analyze_pdf_for_court_case(pdf_path)

    assert result.is_likely_court_case is True
    assert result.extraction_method == "ocr"
    assert result.case_number == "1:24-cv-9999"
    assert result.matched_court_headers


def test_analyze_pdf_for_court_case_detects_state_probate_caption(tmp_path: Path) -> None:
    pdf_path = tmp_path / "probate_motion.pdf"
    _write_pdf(
        pdf_path,
        [
            "IN THE CIRCUIT COURT OF THE STATE OF OREGON",
            "FOR THE COUNTY OF CLACKAMAS",
            "PROBATE DEPARTMENT",
            "In the Matter of:",
            "Jane Kay Cortez, Protected Person.",
            "Case No. 26PR00641",
            "Motion to dismiss",
        ],
    )

    result = analyze_pdf_for_court_case(pdf_path)

    assert result.is_likely_court_case is True
    assert result.case_number == "26PR00641"
    assert result.case_name == "In the Matter of Jane Kay Cortez, Protected Person."
    assert result.confidence >= 0.85
    assert any("CIRCUIT COURT" in header.upper() for header in result.matched_court_headers)


def test_analyze_pdf_for_court_case_rejects_implausible_case_number(tmp_path: Path) -> None:
    pdf_path = tmp_path / "memo.pdf"
    _write_pdf(
        pdf_path,
        [
            "Memorandum of Law",
            "Case No. Order",
            "Support: Example v. Example",
        ],
    )

    result = analyze_pdf_for_court_case(pdf_path)

    assert result.case_number == ""
    assert result.is_likely_court_case is False


def test_scan_hacc_pdfs_for_dockets_collects_court_pdfs_into_dataset(tmp_path: Path) -> None:
    scan_root = tmp_path / "hacc"
    _write_pdf(
        scan_root / "case_a" / "complaint.pdf",
        [
            "IN THE UNITED STATES DISTRICT COURT",
            "FOR THE DISTRICT OF EXAMPLE",
            "Case No. 2:25-cv-4004",
            "Roe v. Example Holdings",
            "Complaint for damages",
        ],
    )
    _write_pdf(
        scan_root / "case_a" / "motion.pdf",
        [
            "IN THE UNITED STATES DISTRICT COURT",
            "FOR THE DISTRICT OF EXAMPLE",
            "Case No. 2:25-cv-4004",
            "Roe v. Example Holdings",
            "Motion for extension of time",
        ],
    )
    _write_pdf(
        scan_root / "other" / "research_note.pdf",
        [
            "Housing notes",
            "This is not a pleading and has no court header.",
        ],
    )
    _write_pdf(
        scan_root / ".git" / "ignored.pdf",
        [
            "IN THE UNITED STATES DISTRICT COURT",
            "Case No. 9:99-cv-9999",
        ],
    )
    _write_pdf(
        scan_root / "statefiles" / "pytest-of-user" / "pytest-0" / "generated_case.pdf",
        [
            "IN THE UNITED STATES DISTRICT COURT",
            "Case No. 7:77-cv-7777",
            "Generated v. Artifact",
        ],
    )
    _write_pdf(
        scan_root / "statefiles" / "complaint-site-playwright-abcd1234" / "formal-complaint.pdf",
        [
            "Generated browser artifact",
        ],
    )

    output_dir = tmp_path / "output"
    manifest = scan_hacc_pdfs_for_dockets(
        scan_root,
        output_dir=output_dir,
        include_vector_index=False,
        include_formal_logic=False,
        include_router_enrichment=False,
    )

    assert manifest["pdf_count"] == 3
    assert manifest["matched_pdf_count"] == 2
    assert manifest["candidate_case_count"] == 1
    assert manifest["scan_started_at"].endswith("Z")
    assert manifest["scan_completed_at"].endswith("Z")
    assert manifest["scan_status"] == "completed"
    assert manifest["manifest_path"] == str((output_dir / "scan_manifest.json"))
    assert manifest["scan_parameters"]["glob_pattern"] == "*.pdf"
    assert manifest["scan_parameters"]["include_bm25"] is True
    assert manifest["skipped_pdf_count"] == 3
    assert Path(manifest["manifest_path"]).exists()

    case_payload = manifest["cases"][0]
    assert case_payload["status"] == "completed"
    dataset_path = Path(case_payload["dataset_path"])
    assert dataset_path.exists()
    assert dataset_path.suffix == ".parquet"
    assert case_payload["dataset_format"] == "parquet"
    assert case_payload["dataset_row_count"] >= 3
    assert case_payload["dataset_section_counts"]["documents"] == 2
    dataset_rows = pq.read_table(dataset_path).to_pylist()
    dataset_core = next(row for row in dataset_rows if row["section"] == "dataset_core")
    dataset = json.loads(dataset_core["payload_json"])
    assert dataset["docket_id"] == "2:25-cv-4004"
    assert dataset["case_name"] == "Roe v. Example Holdings"
    assert dataset["metadata"]["scan_root"] == str(scan_root)
    assert dataset["metadata"]["scan_started_at"].endswith("Z")
    assert dataset["metadata"]["scan_status"] == "completed"
    assert dataset["metadata"]["collected_pdf_count"] == 2
    assert len(dataset["metadata"]["collected_pdf_paths"]) == 2
    assert dataset["metadata"]["matched_relative_paths"] == ["case_a/complaint.pdf", "case_a/motion.pdf"]
    assert dataset["metadata"]["scan_confidence_summary"]["average_confidence"] >= 0.85
    assert dataset["metadata"]["scan_case_graph"]["summary"]["entity_count"] >= 1
    document_rows = [json.loads(row["payload_json"]) for row in dataset_rows if row["section"] == "documents"]
    assert len(document_rows) == 2
    assert document_rows[0]["metadata"]["scan_detection"]["confidence"] >= 0.85
    assert document_rows[0]["metadata"]["scan_detection"]["is_likely_court_case"] is True
    assert document_rows[0]["metadata"]["scan_detection"]["text_length"] > 0
    assert document_rows[0]["metadata"]["scan_detection"]["header_match_count"] >= 1
    assert document_rows[0]["metadata"]["relative_path"] == "case_a/complaint.pdf"
    assert document_rows[0]["metadata"]["source_file"]["file_size_bytes"] > 0
    assert document_rows[0]["metadata"]["source_file"]["page_count"] >= 1
    assert document_rows[0]["metadata"]["case_detection"]["case_number"] == "2:25-cv-4004"
    assert document_rows[0]["metadata"]["document_knowledge_graph_summary"]["node_count"] >= 1
    assert document_rows[0]["metadata"]["text_extraction"]["max_ocr_pages"] == 5
    assert document_rows[0]["metadata"]["document_knowledge_graph"]["summary"]["node_count"] >= 1
    assert Path(case_payload["collected_pdf_root"]).exists()
    assert list((output_dir / "collected_pdfs").rglob("*.pdf"))


def test_manifest_summary_helper_reads_condensed_status(tmp_path: Path) -> None:
    manifest_path = tmp_path / "scan_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "scan_status": "running",
                "scan_started_at": "2025-01-01T00:00:00Z",
                "scan_completed_at": "",
                "scan_root": "/scan/root",
                "output_dir": "/scan/out",
                "manifest_path": str(manifest_path),
                "pdf_count": 200,
                "matched_pdf_count": 3,
                "skipped_pdf_count": 5,
                "candidate_case_count": 2,
                "ocr_available": False,
                "cases": [
                    {
                        "status": "candidate",
                        "case_number": "1:24-cv-1111",
                        "case_name": "Doe v. Example",
                        "court": "United States District Court",
                        "document_count": 2,
                        "matched_relative_paths": ["a.pdf", "b.pdf"],
                        "dataset_path": "/ignored.json",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    summary = summarize_scan_manifest(load_scan_manifest(manifest_path))

    assert summary["scan_status"] == "running"
    assert summary["candidate_case_count"] == 2
    assert summary["sample_cases"][0]["status"] == "candidate"
    assert summary["sample_cases"][0]["matched_relative_paths"] == ["a.pdf", "b.pdf"]