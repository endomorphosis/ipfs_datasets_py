"""Unit tests for live GovInfo annual CFR Title 37 acquisition (PATLAW-181)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "acquire_cfr_title37_full.py"
)


def _load_module():
    name = "acquire_cfr_title37_full_live_unit"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def acq():
    return _load_module()


def _mini_volume_xml(*sections: tuple[str, str, str]) -> bytes:
    """Build a compact CFRDOC with SECTION/SECTNO/SUBJECT/P nodes."""

    parts = [
        '<?xml version="1.0"?>',
        '<CFRDOC>',
        '<AMDDATE>July 1, 2024</AMDDATE>',
    ]
    for sectno, subject, body in sections:
        parts.append("<SECTION>")
        parts.append(f"<SECTNO>§\u2009{sectno}</SECTNO>")
        parts.append(f"<SUBJECT>{subject}</SUBJECT>")
        parts.append(f"<P>{body}</P>")
        parts.append("</SECTION>")
    parts.append("</CFRDOC>")
    return "\n".join(parts).encode("utf-8")


def test_parse_cfr_volume_xml_extracts_sections_and_date(acq) -> None:
    xml = _mini_volume_xml(
        ("1.56", "Duty to disclose", "Material information must be disclosed."),
        ("1.97", "Filing of IDS", "An information disclosure statement may be filed."),
    )
    sections, metadata, direct = acq.parse_cfr_volume_xml(xml)
    assert set(sections) == {"1.56", "1.97"}
    assert direct == {"1.56", "1.97"}
    assert "disclosed" in sections["1.56"]
    assert metadata["date_issued"] == "2024-07-01"
    assert "July 1, 2024" in metadata["amddate_raw"]


def test_extract_section_number_normalizes_sectno_labels(acq) -> None:
    assert acq.extract_section_number("§\u20091.56") == "1.56"
    assert acq.extract_section_number("1.97") == "1.97"
    assert acq.extract_section_number("Sec. 42.100") == "42.100"


def test_expand_section_range_token_fans_out_reserved_spans(acq) -> None:
    assert acq.expand_section_range_token("1.106-1.108") == [
        "1.106",
        "1.107",
        "1.108",
    ]
    assert acq.expand_section_range_token("11.61-11.63") == [
        "11.61",
        "11.62",
        "11.63",
    ]
    assert acq.expand_section_range_token("1.56") == ["1.56"]


def test_parse_reserved_range_sectno_marks_each_catalog_leaf(acq) -> None:
    xml = (
        '<?xml version="1.0"?><CFRDOC><AMDDATE>July 1, 2024</AMDDATE>'
        "<SECTION><SECTNO>§§\u20091.106-1.108</SECTNO>"
        "<SUBJECT>[Reserved]</SUBJECT>"
        "<P>§§\u20091.106-1.108 [Reserved]</P>"
        "</SECTION>"
        "<SECTION><SECTNO>§\u20091.56</SECTNO>"
        "<SUBJECT>Duty to disclose</SUBJECT>"
        "<P>Candor and good faith are required in dealing with the Office.</P>"
        "</SECTION></CFRDOC>"
    ).encode("utf-8")
    sections, _meta, direct = acq.parse_cfr_volume_xml(xml)
    assert set(sections) >= {"1.106", "1.107", "1.108", "1.56"}
    assert "Reserved" in sections["1.107"]
    # Range leaves are expansions; only standalone SECTNO is direct.
    assert "1.56" in direct
    assert "1.107" not in direct


def test_live_acquisition_with_fake_http_maps_catalog_presence(acq, tmp_path: Path) -> None:
    vol1 = _mini_volume_xml(
        (
            "1.56",
            "Duty to disclose information material to patentability",
            "Each individual associated with the filing and prosecution of a "
            "patent application has a duty of candor and good faith.",
        ),
        (
            "1.97",
            "Filing of information disclosure statement",
            "An information disclosure statement shall be considered if filed.",
        ),
        (
            "41.50",
            "Decisions and other actions by the Board",
            "The Board may affirm or reverse in whole or in part.",
        ),
    )
    calls: list[str] = []

    def fake_get(url: str, timeout: float) -> bytes:
        calls.append(url)
        if "vol1" in url:
            return vol1
        raise acq.LiveAcquisitionUnavailableError("no further volumes")

    result = acq.acquire_from_govinfo_live(
        year=2024,
        stage=True,
        output_dir=tmp_path / "out",
        http_get=fake_get,
        delay_seconds=0.0,
        max_volumes=2,
    )

    assert result.source_kind == "govinfo-annual-live"
    assert result.package_id == "CFR-2024-title37"
    assert result.manifest.counts is not None
    assert result.manifest.counts.total_sections == acq.title37_section_count()
    assert result.manifest.counts.present_sections == 3
    assert result.manifest.counts.gap_sections == (
        acq.title37_section_count() - 3
    )
    assert set(result.section_texts) == {"1.56", "1.97", "41.50"}
    assert result.manifest.edition_identity.date_issued == "2024-07-01"
    assert (tmp_path / "out" / acq.MANIFEST_FILENAME).is_file()
    assert (tmp_path / "out" / "sections" / "1-56.txt").is_file()
    assert any("vol1" in url for url in calls)
    assert result.receipt.get("live_network") is True
    assert result.package_meta["volume_count"] == 1


def test_live_requires_year_pin(acq) -> None:
    with pytest.raises(acq.MissingEditionIdentityError):
        acq.acquire_cfr_title37_full(live=True, year=None)


def test_live_rejects_html_payload(acq) -> None:
    def fake_get(url: str, timeout: float) -> bytes:
        return b"<!DOCTYPE html><html><body>missing</body></html>"

    with pytest.raises(acq.LiveAcquisitionUnavailableError):
        acq.acquire_from_govinfo_live(
            year=2024,
            http_get=fake_get,
            delay_seconds=0.0,
        )


def test_cli_live_path_uses_fake_http_via_module(acq, tmp_path: Path, monkeypatch) -> None:
    vol1 = _mini_volume_xml(
        (
            "1.56",
            "Duty to disclose",
            "Candor and good faith in dealing with the Office are required.",
        ),
    )

    def fake_get(url: str, timeout: float) -> bytes:
        if "vol1" in url:
            return vol1
        raise acq.LiveAcquisitionUnavailableError("stop")

    monkeypatch.setattr(acq, "default_http_get", fake_get)
    rc = acq.main(
        [
            "--live",
            "--year",
            "2024",
            "--stage",
            "--output-dir",
            str(tmp_path / "cli-out"),
            "--no-print-summary",
        ]
    )
    assert rc == 0
    assert (tmp_path / "cli-out" / acq.MANIFEST_FILENAME).is_file()
