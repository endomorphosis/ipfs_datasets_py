import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import build_exhibit_binder_from_manifest


def test_build_exhibit_binder_from_manifest(tmp_path: Path):
    covers = tmp_path / "covers"
    exhibits = tmp_path / "exhibits"
    covers.mkdir()
    exhibits.mkdir()

    (covers / "EXHIBIT_BINDER_FRONT_SHEET.md").write_text("## Test Binder\n\n- Front matter\n", encoding="utf-8")
    (covers / "Exhibit_A_tab_cover_page.md").write_text("`EXHIBIT LABEL` `Exhibit A`\n`SECTION` `Test`\n`SHORT TITLE` `Divider`\n", encoding="utf-8")
    (covers / "Exhibit_A_cover_page.md").write_text(
        "\n".join(
            [
                "`EXHIBIT LABEL` `Exhibit A`",
                "`SHORT TITLE` `Source A`",
                "`SOURCE FILE` `ignored-by-manifest-inference`",
                "`RELIED ON BY`",
                "1. Motion.",
                "`PROPOSITION(S) THIS EXHIBIT IS OFFERED TO SUPPORT`",
                "1. Fact.",
                "`AUTHENTICITY / FOUNDATION NOTE` `Foundation.`",
                "`LIMITATION NOTE` `Limitation.`",
            ]
        ),
        encoding="utf-8",
    )
    (exhibits / "Exhibit_A_sample.txt").write_text("sample exhibit text\n", encoding="utf-8")

    manifest = tmp_path / "binder_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "front_sheet_markdown": "covers/EXHIBIT_BINDER_FRONT_SHEET.md",
                "working_dir": "compiled",
                "output_pdf": "compiled/binder.pdf",
                "exhibits_root": "exhibits",
                "exhibits": [
                    {
                        "code": "A",
                        "title": "Sample Exhibit",
                        "divider_markdown": "covers/Exhibit_A_tab_cover_page.md",
                        "cover_markdown": "covers/Exhibit_A_cover_page.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_exhibit_binder_from_manifest(manifest)
    assert payload["exhibit_count"] == 1
    assert Path(str(payload["output_pdf"])).exists()
