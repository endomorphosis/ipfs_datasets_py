import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import build_full_evidence_binder_from_manifest


TAB_MD = """`EXHIBIT LABEL` `Exhibit A`
`SECTION` `Test Family`
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


def test_build_full_evidence_binder_from_manifest(tmp_path: Path):
    exhibit_covers = tmp_path / "covers"
    family_dir = exhibit_covers / "family_a"
    family_dir.mkdir(parents=True)

    source_path = tmp_path / "source.txt"
    source_path.write_text("sample source text\n", encoding="utf-8")

    (family_dir / "exhibit_A_tab_cover_page.md").write_text(TAB_MD, encoding="utf-8")
    (family_dir / "exhibit_A_cover_page.md").write_text(COVER_MD.format(source=source_path), encoding="utf-8")

    manifest_path = tmp_path / "full_binder_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "exhibit_covers_root": "covers",
                "working_dir": "build",
                "generated_dir": "build/generated_pdfs",
                "build_manifest_output": "build/manifest.txt",
                "output_pdf": "full_binder.pdf",
                "families": [
                    {
                        "name": "Test Family",
                        "cover_dirs": ["family_a"],
                        "labels": ["Exhibit A"],
                        "output_pdf": "family_a.pdf",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_full_evidence_binder_from_manifest(manifest_path)
    assert payload["family_count"] == 1
    assert payload["lean_mode"] is False
    assert Path(str(payload["output_pdf"])).exists()
    assert Path(str(payload["build_manifest_output"])).exists()
    assert Path(str(payload["family_outputs"]["Test Family"])).exists()
