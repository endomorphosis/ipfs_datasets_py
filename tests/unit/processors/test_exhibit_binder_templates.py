from pathlib import Path

try:
    from PyPDF2 import PdfReader
except Exception:  # pragma: no cover - dependency fallback
    from pypdf import PdfReader  # type: ignore

from ipfs_datasets_py.processors.legal_data import (
    DEFAULT_BINDER_COURT_CONFIG,
    render_exhibit_binder_front_sheet,
    render_table_of_exhibits_pdf,
)


def test_render_exhibit_binder_front_sheet_and_table(tmp_path: Path):
    front_md = tmp_path / "front.md"
    front_md.write_text(
        "\n".join(
            [
                "IN THE CLACKAMAS COUNTY JUSTICE COURT",
                "STATE OF OREGON",
                "Case No. 26FE0586",
                "",
                "## Defendants' Exhibit Binder",
                "",
                "- Exhibit packets attached.",
                "1. Service evidence.",
            ]
        ),
        encoding="utf-8",
    )
    front_pdf = tmp_path / "front.pdf"
    table_pdf = tmp_path / "table.pdf"

    render_exhibit_binder_front_sheet(front_md, front_pdf, config=DEFAULT_BINDER_COURT_CONFIG)
    render_table_of_exhibits_pdf(
        table_pdf,
        exhibit_order=["A", "B"],
        exhibit_titles={"A": "First Exhibit", "B": "Second Exhibit"},
        starts={"A": 2, "B": 5},
        counts={"A": 3, "B": 1},
        config=DEFAULT_BINDER_COURT_CONFIG,
    )

    assert len(PdfReader(str(front_pdf)).pages) == 1
    assert len(PdfReader(str(table_pdf)).pages) == 1
