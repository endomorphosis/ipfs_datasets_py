import json
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from ipfs_datasets_py.cli import legal_pdf_cli


TAB_MD = """`EXHIBIT LABEL` `Exhibit A`
`SECTION` `Primary Binder`
`SHORT TITLE` `Divider A`
`STATUS` `Ready`
"""

COVER_MD = """`EXHIBIT LABEL` `Exhibit A`
`SHORT TITLE` `Source A`
`SOURCE FILE` `{source}`
`RELIED ON BY`
1. Test motion.
`PROPOSITION(S) THIS EXHIBIT IS OFFERED TO SUPPORT`
1. Test fact.
`AUTHENTICITY / FOUNDATION NOTE` `Foundation.`
`LIMITATION NOTE` `Limitation.`
"""

MOTION_MD = """# Motion To Test Packet

Case No. TEST-123

MOTION TO TEST PACKET

This is a short motion paragraph for packet rendering.
"""

MEMO_MD = """# Memorandum In Support

Case No. TEST-123

MEMORANDUM IN SUPPORT

This is a short memorandum paragraph for packet rendering.
"""


def _write_sample_pdf(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.drawString(72, 720, "sample")
    pdf.save()


def test_legal_pdf_cli_validate_manifest_json_is_clean(tmp_path: Path, capsys):
    manifest_path = tmp_path / "full_evidence_binder_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "exhibit_covers_root": "covers",
                "working_dir": "build",
                "output_pdf": "build/full_binder.pdf",
                "families": [
                    {
                        "name": "Primary Binder",
                        "cover_dirs": ["primary"],
                        "labels": ["Exhibit A"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "validate-manifest",
            "--manifest-path",
            str(manifest_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["valid"] is True
    assert payload["manifest_type"] == "full-evidence-binder"


def test_legal_pdf_cli_count_pages_json_is_clean(tmp_path: Path, capsys):
    pdf_path = tmp_path / "sample.pdf"
    _write_sample_pdf(pdf_path)

    result = legal_pdf_cli.main(
        [
            "--action",
            "count-pages",
            "--input-path",
            str(pdf_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "count-pages"
    assert payload["input_path"] == str(pdf_path)
    assert payload["page_count"] == 1


def test_legal_pdf_cli_build_full_evidence_binder_json_is_clean(tmp_path: Path, capsys):
    covers_dir = tmp_path / "covers" / "primary"
    covers_dir.mkdir(parents=True)
    source_path = tmp_path / "source.txt"
    source_path.write_text("sample source text\n", encoding="utf-8")

    (covers_dir / "exhibit_A_tab_cover_page.md").write_text(TAB_MD, encoding="utf-8")
    (covers_dir / "exhibit_A_cover_page.md").write_text(COVER_MD.format(source=source_path), encoding="utf-8")

    manifest_path = tmp_path / "full_evidence_binder_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "exhibit_covers_root": "covers",
                "working_dir": "build",
                "generated_dir": "build/generated_pdfs",
                "build_manifest_output": "build/manifest.txt",
                "output_pdf": "build/full_binder.pdf",
                "families": [
                    {
                        "name": "Primary Binder",
                        "cover_dirs": ["primary"],
                        "labels": ["Exhibit A"],
                        "output_pdf": "build/primary_binder.pdf",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-full-evidence-binder-from-manifest",
            "--manifest-path",
            str(manifest_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-full-evidence-binder-from-manifest"
    assert payload["family_count"] == 1
    assert payload["lean_mode"] is False
    assert Path(payload["output_pdf"]).exists()
    assert Path(payload["family_outputs"]["Primary Binder"]).exists()


def test_legal_pdf_cli_build_state_court_filing_packet_json_is_clean(tmp_path: Path, capsys):
    motion_path = tmp_path / "motion.md"
    memo_path = tmp_path / "memorandum.md"
    motion_path.write_text(MOTION_MD, encoding="utf-8")
    memo_path.write_text(MEMO_MD, encoding="utf-8")

    manifest_path = tmp_path / "state_court_packet_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "documents": ["motion.md", "memorandum.md"],
                "output_dir": "rendered_pdfs",
                "packet_output_path": "rendered_pdfs/filing_packet.pdf",
                "config": {
                    "contact_block_html": "Benjamin Jay Barber, pro se<br/>Defendant",
                    "court_name": "IN THE CLACKAMAS COUNTY JUSTICE COURT",
                    "state_name": "STATE OF OREGON",
                    "caption_left_html": "PLAINTIFF,<br/>v.<br/>DEFENDANT.",
                    "case_number_line": "Case No. TEST-123",
                    "filed_date": "April 12, 2026",
                    "signature_doc_keywords": ["motion", "memorandum"],
                    "declaration_doc_keywords": ["declaration"]
                }
            }
        ),
        encoding="utf-8",
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-court-filing-packet-from-manifest",
            "--manifest-path",
            str(manifest_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-court-filing-packet-from-manifest"
    assert Path(payload["packet_path"]).exists()
    assert len(payload["rendered_paths"]) == 2
