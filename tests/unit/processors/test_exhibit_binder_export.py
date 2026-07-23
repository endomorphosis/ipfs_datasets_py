from pathlib import Path

try:
    from PyPDF2 import PdfReader
except Exception:  # pragma: no cover - dependency fallback
    from pypdf import PdfReader  # type: ignore

from ipfs_datasets_py.processors.legal_data import (
    build_exhibit_binder,
    pdf_page_count,
    render_binder_title_pdf,
    render_family_divider_pdf,
    source_to_pdf,
)


def test_render_binder_title_and_family_divider(tmp_path: Path):
    title_pdf = tmp_path / "title.pdf"
    divider_pdf = tmp_path / "divider.pdf"

    render_binder_title_pdf(title_pdf, lean_mode=True)
    render_family_divider_pdf(divider_pdf, "Shared Motion / Probate / Sanctions Binder", ["Exhibit A", "Exhibit B"])

    assert len(PdfReader(str(title_pdf)).pages) == 1
    assert len(PdfReader(str(divider_pdf)).pages) == 1


def test_source_to_pdf_renders_text_and_eml(tmp_path: Path):
    text_source = tmp_path / "source.txt"
    text_source.write_text("Line one\nLine two\n", encoding="utf-8")
    text_pdf = tmp_path / "source_text.pdf"

    eml_source = tmp_path / "message.eml"
    eml_source.write_text(
        "\n".join(
            [
                "From: sender@example.com",
                "To: receiver@example.com",
                "Subject: Test message",
                "Date: Sun, 12 Apr 2026 12:00:00 +0000",
                "Content-Type: text/plain; charset=utf-8",
                "",
                "Hello from the body.",
            ]
        ),
        encoding="utf-8",
    )
    eml_pdf = tmp_path / "source_eml.pdf"

    source_to_pdf(str(text_source), output_path=text_pdf, label="Exhibit A", family="Test Family")
    source_to_pdf(str(eml_source), output_path=eml_pdf, label="Exhibit B", family="Test Family")

    assert len(PdfReader(str(text_pdf)).pages) == 1
    assert len(PdfReader(str(eml_pdf)).pages) == 1


def test_build_exhibit_binder_merges_front_table_and_packets(tmp_path: Path):
    front_pdf = tmp_path / "front.pdf"
    table_pdf = tmp_path / "table.pdf"
    packet_pdf = tmp_path / "packet.pdf"
    render_binder_title_pdf(front_pdf, lean_mode=False)
    render_family_divider_pdf(table_pdf, "Test Family", ["Exhibit A"])
    render_family_divider_pdf(packet_pdf, "Packet", ["Exhibit A"])

    output_pdf = tmp_path / "binder.pdf"
    build_exhibit_binder(front_pdf=front_pdf, table_pdf=table_pdf, packet_pdfs=[packet_pdf], output_pdf=output_pdf)

    assert output_pdf.exists()
    assert pdf_page_count(output_pdf) == 3
