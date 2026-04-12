import json
from pathlib import Path

try:
    from PyPDF2 import PdfReader
except Exception:  # pragma: no cover - dependency fallback
    from pypdf import PdfReader  # type: ignore

from ipfs_datasets_py.processors.legal_data import (
    DEFAULT_EXHIBIT_CAPTION,
    StateCourtPleadingConfig,
    build_state_court_filing_packet,
    build_state_court_filing_packet_from_manifest,
    parse_exhibit_cover_source,
    render_exhibit_cover_from_markdown,
    render_exhibit_tab_from_markdown,
    render_state_court_pdf_batch,
    render_state_court_markdown_to_pdf,
    render_text_lines_pdf,
)


def test_render_text_lines_pdf_creates_multi_page_pdf(tmp_path: Path):
    pdf_path = tmp_path / "text_render.pdf"
    render_text_lines_pdf(pdf_path, "Test Render", [f"Line {index}" for index in range(120)], footer_label="Test Footer")
    reader = PdfReader(str(pdf_path))
    assert len(reader.pages) >= 2


def test_render_exhibit_cover_and_tab_from_markdown(tmp_path: Path):
    md_path = tmp_path / "exhibit_a_cover_page.md"
    md_path.write_text(
        "\n".join(
            [
                "`EXHIBIT LABEL` `Exhibit A`",
                "`SECTION` `Shared Motion / Probate / Sanctions Binder`",
                "`SHORT TITLE` `Sheriff Service Photograph`",
                "`STATUS` `Court-ready source attached`",
                "`SOURCE FILE` `/tmp/solomon_service.heic`",
                "`RELIED ON BY`",
                "1. Motion to show cause.",
                "2. Sanctions memorandum.",
                "`PROPOSITION(S) THIS EXHIBIT IS OFFERED TO SUPPORT`",
                "1. Solomon Barber had notice.",
                "`AUTHENTICITY / FOUNDATION NOTE` `Photograph taken by Benjamin Barber.`",
                "`LIMITATION NOTE` `Offered for service and notice only.`",
            ]
        ),
        encoding="utf-8",
    )

    tab_pdf = tmp_path / "tab.pdf"
    cover_pdf = tmp_path / "cover.pdf"
    render_exhibit_tab_from_markdown(md_path, tab_pdf, caption_config=DEFAULT_EXHIBIT_CAPTION)
    render_exhibit_cover_from_markdown(md_path, cover_pdf, caption_config=DEFAULT_EXHIBIT_CAPTION)

    assert parse_exhibit_cover_source(md_path) == "/tmp/solomon_service.heic"
    assert len(PdfReader(str(tab_pdf)).pages) == 1
    assert len(PdfReader(str(cover_pdf)).pages) == 1


def test_render_state_court_markdown_to_pdf_creates_pleading_pdf(tmp_path: Path):
    md_path = tmp_path / "motion_to_show_cause.md"
    md_path.write_text(
        "\n".join(
            [
                "Case No. 26FE0586",
                "",
                "MOTION TO SHOW CAUSE",
                "",
                "## Background",
                "1. Plaintiff issued a writ.",
                "2. Defendants objected and raised preclusion.",
                "",
                "### Requested Relief",
                "- Quash collateral proceedings.",
                "- Set a show cause hearing.",
            ]
        ),
        encoding="utf-8",
    )
    pdf_path = tmp_path / "motion_to_show_cause.pdf"
    config = StateCourtPleadingConfig(
        contact_block_html="Benjamin Jay Barber, pro se<br/>Defendant",
        court_name="IN THE CLACKAMAS COUNTY JUSTICE COURT",
        state_name="STATE OF OREGON",
        caption_left_html="HOUSING AUTHORITY OF CLACKAMAS COUNTY,<br/>Plaintiff,<br/><br/>v.<br/><br/>BENJAMIN BARBER,<br/>Defendant.",
        filed_date="April 12, 2026",
        signature_doc_keywords=("motion",),
        declaration_doc_keywords=("declaration",),
    )

    render_state_court_markdown_to_pdf(md_path, pdf_path, config=config)
    reader = PdfReader(str(pdf_path))
    assert len(reader.pages) == 1
    extracted_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "MOTION TO SHOW CAUSE" in extracted_text
    assert "Case No. 26FE0586" in extracted_text


def test_render_state_court_pdf_batch_creates_multiple_outputs(tmp_path: Path):
    md_a = tmp_path / "motion_a.md"
    md_b = tmp_path / "motion_b.md"
    md_a.write_text("Case No. 1\n\nMOTION A\n", encoding="utf-8")
    md_b.write_text("Case No. 2\n\nMOTION B\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    config = StateCourtPleadingConfig(
        contact_block_html="Benjamin Jay Barber, pro se<br/>Defendant",
        court_name="IN THE CLACKAMAS COUNTY JUSTICE COURT",
        state_name="STATE OF OREGON",
        caption_left_html="Plaintiff v. Defendant",
        filed_date="April 12, 2026",
        signature_doc_keywords=("motion",),
        declaration_doc_keywords=("declaration",),
    )
    outputs = render_state_court_pdf_batch([md_a, md_b], output_dir, config=config)
    assert [path.name for path in outputs] == ["motion_a.pdf", "motion_b.pdf"]
    assert all(path.exists() for path in outputs)


def test_build_state_court_filing_packet_merges_rendered_outputs(tmp_path: Path):
    md_a = tmp_path / "motion_a.md"
    md_b = tmp_path / "motion_b.md"
    md_a.write_text("Case No. 1\n\nMOTION A\n", encoding="utf-8")
    md_b.write_text("Case No. 2\n\nMOTION B\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    packet_pdf = tmp_path / "packet.pdf"
    config = StateCourtPleadingConfig(
        contact_block_html="Benjamin Jay Barber, pro se<br/>Defendant",
        court_name="IN THE CLACKAMAS COUNTY JUSTICE COURT",
        state_name="STATE OF OREGON",
        caption_left_html="Plaintiff v. Defendant",
        filed_date="April 12, 2026",
        signature_doc_keywords=("motion",),
        declaration_doc_keywords=("declaration",),
    )
    payload = build_state_court_filing_packet([md_a, md_b], output_dir, packet_pdf, config=config)
    assert payload["document_count"] == 2
    assert Path(str(payload["packet_path"])).exists()
    assert len(PdfReader(str(packet_pdf)).pages) == 2


def test_build_state_court_filing_packet_from_manifest(tmp_path: Path):
    md_a = tmp_path / "motion_a.md"
    md_b = tmp_path / "motion_b.md"
    md_a.write_text("Case No. 1\n\nMOTION A\n", encoding="utf-8")
    md_b.write_text("Case No. 2\n\nMOTION B\n", encoding="utf-8")
    manifest = tmp_path / "packet_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": ["motion_a.md", "motion_b.md"],
                "output_dir": "out",
                "packet_output_path": "out/packet.pdf",
                "config": {
                    "contact_block_html": "Benjamin Jay Barber, pro se<br/>Defendant",
                    "court_name": "IN THE CLACKAMAS COUNTY JUSTICE COURT",
                    "state_name": "STATE OF OREGON",
                    "caption_left_html": "Plaintiff v. Defendant",
                    "filed_date": "April 12, 2026",
                    "signature_doc_keywords": ["motion"],
                    "declaration_doc_keywords": ["declaration"]
                },
            }
        ),
        encoding="utf-8",
    )
    payload = build_state_court_filing_packet_from_manifest(manifest)
    assert payload["document_count"] == 2
    assert Path(str(payload["packet_path"])).exists()
