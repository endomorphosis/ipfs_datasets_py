from __future__ import annotations

import json
from pathlib import Path

from reportlab.pdfgen import canvas

from ipfs_datasets_py.processors.legal_data_hacc import analyze_pdf_for_court_case, scan_hacc_pdfs_for_dockets
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
    assert manifest["scan_parameters"]["glob_pattern"] == "*.pdf"
    assert manifest["scan_parameters"]["include_bm25"] is True
    assert manifest["skipped_pdf_count"] == 1
    assert Path(manifest["manifest_path"]).exists()

    case_payload = manifest["cases"][0]
    dataset_path = Path(case_payload["dataset_path"])
    assert dataset_path.exists()
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert dataset["docket_id"] == "2:25-cv-4004"
    assert dataset["case_name"] == "Roe v. Example Holdings"
    assert len(dataset["documents"]) == 2
    assert dataset["metadata"]["scan_root"] == str(scan_root)
    assert dataset["metadata"]["scan_started_at"].endswith("Z")
    assert dataset["metadata"]["collected_pdf_count"] == 2
    assert len(dataset["metadata"]["collected_pdf_paths"]) == 2
    assert dataset["metadata"]["matched_relative_paths"] == ["case_a/complaint.pdf", "case_a/motion.pdf"]
    assert dataset["metadata"]["scan_confidence_summary"]["average_confidence"] >= 0.85
    assert dataset["metadata"]["scan_case_graph"]["summary"]["entity_count"] >= 1
    assert dataset["documents"][0]["metadata"]["scan_detection"]["confidence"] >= 0.85
    assert dataset["documents"][0]["metadata"]["scan_detection"]["is_likely_court_case"] is True
    assert dataset["documents"][0]["metadata"]["scan_detection"]["text_length"] > 0
    assert dataset["documents"][0]["metadata"]["relative_path"] == "case_a/complaint.pdf"
    assert dataset["documents"][0]["metadata"]["case_detection"]["case_number"] == "2:25-cv-4004"
    assert dataset["documents"][0]["metadata"]["document_knowledge_graph_summary"]["node_count"] >= 1
    assert dataset["documents"][0]["metadata"]["document_knowledge_graph"]["summary"]["node_count"] >= 1
    assert Path(case_payload["collected_pdf_root"]).exists()
    assert list((output_dir / "collected_pdfs").rglob("*.pdf"))