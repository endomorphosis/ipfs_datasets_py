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

FRONT_SHEET_MD = """# Exhibit Binder Front Sheet

This is a small synthetic front sheet.
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


def test_legal_pdf_cli_build_exhibit_binder_json_is_clean(tmp_path: Path, capsys):
    covers_dir = tmp_path / "covers"
    exhibits_dir = tmp_path / "exhibits"
    covers_dir.mkdir(parents=True)
    exhibits_dir.mkdir(parents=True)

    source_path = exhibits_dir / "Exhibit_A_sample.txt"
    source_path.write_text("sample source text\n", encoding="utf-8")

    (covers_dir / "EXHIBIT_BINDER_FRONT_SHEET.md").write_text(FRONT_SHEET_MD, encoding="utf-8")
    (covers_dir / "Exhibit_A_tab_divider.md").write_text(TAB_MD, encoding="utf-8")
    (covers_dir / "Exhibit_A_cover_sheet.md").write_text(COVER_MD.format(source=source_path), encoding="utf-8")

    manifest_path = tmp_path / "exhibit_binder_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "family": "Core Exhibit Binder",
                "front_sheet_markdown": "covers/EXHIBIT_BINDER_FRONT_SHEET.md",
                "working_dir": "compiled",
                "output_pdf": "compiled/binder.pdf",
                "exhibits_root": "exhibits",
                "exhibits": [
                    {
                        "code": "A",
                        "title": "Sample Exhibit",
                        "divider_markdown": "covers/Exhibit_A_tab_divider.md",
                        "cover_markdown": "covers/Exhibit_A_cover_sheet.md"
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-exhibit-binder-from-manifest",
            "--manifest-path",
            str(manifest_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-exhibit-binder-from-manifest"
    assert payload["exhibit_count"] == 1
    assert Path(payload["output_pdf"]).exists()
    assert Path(payload["front_pdf"]).exists()
    assert Path(payload["table_pdf"]).exists()
    assert len(payload["packet_paths"]) == 1


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


def test_legal_pdf_cli_build_courtstyle_packet_default_json_is_clean(capsys, monkeypatch):
    marker = {"called": False}

    def _fake_builder() -> None:
        marker["called"] = True

    monkeypatch.setattr(
        legal_pdf_cli,
        "_load_legal_data_exports",
        lambda quiet=False: {"build_default_courtstyle_packet": _fake_builder},
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-courtstyle-packet-default",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-courtstyle-packet-default"
    assert payload["status"] == "ok"
    assert marker["called"] is True


def test_legal_pdf_cli_build_court_ready_binder_index_default_json_is_clean(capsys, monkeypatch):
    expected = Path("/tmp/court_ready_index.pdf")

    monkeypatch.setattr(
        legal_pdf_cli,
        "_load_legal_data_exports",
        lambda quiet=False: {"build_default_court_ready_binder_index": lambda: expected},
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-court-ready-binder-index-default",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-court-ready-binder-index-default"
    assert payload["output_path"] == str(expected)


def test_legal_pdf_cli_build_official_form_drafts_default_json_is_clean(capsys, monkeypatch):
    expected = [Path("/tmp/js44.pdf"), Path("/tmp/ao440.pdf")]

    monkeypatch.setattr(
        legal_pdf_cli,
        "_load_legal_data_exports",
        lambda quiet=False: {"build_default_official_form_drafts": lambda: expected},
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-official-form-drafts-default",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-official-form-drafts-default"
    assert payload["output_paths"] == [str(path) for path in expected]


def test_legal_pdf_cli_build_filing_specific_binders_default_json_is_clean(capsys, monkeypatch):
    expected = [Path("/tmp/eviction_set.pdf"), Path("/tmp/show_cause_set.pdf")]

    monkeypatch.setattr(
        legal_pdf_cli,
        "_load_legal_data_exports",
        lambda quiet=False: {"build_default_filing_specific_binders": lambda: expected},
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-filing-specific-binders-default",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-filing-specific-binders-default"
    assert payload["output_paths"] == [str(path) for path in expected]


def test_legal_pdf_cli_build_court_ready_binder_index_default_with_config_json_is_clean(capsys, monkeypatch):
    marker = {"config_path": None}

    def _fake_builder(config_path: str):
        marker["config_path"] = config_path
        return {"config_path": config_path, "output_path": "/tmp/custom_index.pdf"}

    monkeypatch.setattr(
        legal_pdf_cli,
        "_load_legal_data_exports",
        lambda quiet=False: {"build_court_ready_binder_index_from_config": _fake_builder},
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-court-ready-binder-index-default",
            "--config-path",
            "/tmp/custom_index_config.json",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-court-ready-binder-index-default"
    assert payload["output_path"] == "/tmp/custom_index.pdf"
    assert marker["config_path"] == "/tmp/custom_index_config.json"


def test_legal_pdf_cli_build_official_form_drafts_default_with_config_json_is_clean(capsys, monkeypatch):
    marker = {"config_path": None}

    def _fake_builder(config_path: str):
        marker["config_path"] = config_path
        return {"config_path": config_path, "output_paths": ["/tmp/js44.pdf", "/tmp/ao440.pdf"], "output_count": 2}

    monkeypatch.setattr(
        legal_pdf_cli,
        "_load_legal_data_exports",
        lambda quiet=False: {"build_official_form_drafts_from_config": _fake_builder},
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-official-form-drafts-default",
            "--config-path",
            "/tmp/custom_forms_config.json",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-official-form-drafts-default"
    assert payload["output_count"] == 2
    assert marker["config_path"] == "/tmp/custom_forms_config.json"


def test_legal_pdf_cli_build_filing_specific_binders_default_with_config_json_is_clean(capsys, monkeypatch):
    marker = {"config_path": None}

    def _fake_builder(config_path: str):
        marker["config_path"] = config_path
        return {"config_path": config_path, "output_paths": ["/tmp/set_a.pdf"], "set_count": 1}

    monkeypatch.setattr(
        legal_pdf_cli,
        "_load_legal_data_exports",
        lambda quiet=False: {"build_filing_specific_binders_from_config": _fake_builder},
    )

    result = legal_pdf_cli.main(
        [
            "--action",
            "build-filing-specific-binders-default",
            "--config-path",
            "/tmp/custom_sets_config.json",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["action"] == "build-filing-specific-binders-default"
    assert payload["set_count"] == 1
    assert marker["config_path"] == "/tmp/custom_sets_config.json"
