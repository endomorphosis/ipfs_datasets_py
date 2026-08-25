"""Official California CAML bulk export adapter tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california_bulk import (
    caml_to_text,
    parse_california_bulk_zip,
    session_zip_url,
)


def test_session_zip_url_is_official_downloads_host() -> None:
    url = session_zip_url("2025")
    assert url.startswith("https://downloads.leginfo.legislature.ca.gov/")
    assert url.endswith("pubinfo_2025.zip")
    assert "justia" not in url


def test_caml_fraction_is_not_concatenated() -> None:
    xml = (
        '<caml:Content xmlns:caml="urn:caml">'
        "<p>four-fifths (<caml:Fraction>"
        "<caml:Numerator>4</caml:Numerator>"
        "<caml:Denominator>5</caml:Denominator>"
        "</caml:Fraction>)</p>"
        "</caml:Content>"
    )
    text, unknown = caml_to_text(xml)
    assert "4/5" in text
    assert "(45)" not in text
    assert "caml:fraction" not in unknown


def test_parse_bulk_zip_emits_official_labor_code(tmp_path: Path) -> None:
    caml = (
        '<caml:Content xmlns:caml="urn:caml">'
        "<p>(a) Notwithstanding any agreement to the contrary, "
        "an employee may recover unpaid minimum wages.</p>"
        "</caml:Content>"
    )
    table = "id\t`LAB`\t`1194.`\t\t\t\t\t\t\t\t\t\t\t\t`LAB_1194.lob`\t\t\t`2025`"
    zip_path = tmp_path / "pubinfo_2025.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("LAW_SECTION_TBL.dat", table + "\n")
        archive.writestr("LAB_1194.lob", caml)
    rows = parse_california_bulk_zip(
        zip_path,
        code_type="LAB",
        code_name="Labor Code",
        max_statutes=4,
    )
    assert len(rows) == 1
    assert rows[0].section_number == "1194"
    assert "minimum wages" in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert rows[0].structured_data["source_kind"] == "official_california_bulk_caml"
    assert "leginfo.legislature.ca.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url
