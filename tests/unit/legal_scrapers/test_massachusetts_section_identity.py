"""Massachusetts punctuation-bearing section identity regressions."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    massachusetts_section,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts import (
    MassachusettsScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.massachusetts_section import (
    parse_massachusetts_section_html,
    section_links,
    section_number_from_url,
)


def _section_html(section_number: str) -> str:
    return f"""
    <html><body>
      <h2 class="genLawHeading">Section {section_number}: Official heading</h2>
      <div class="content">
        <p>Section {section_number}. This is complete official Massachusetts
        statutory text with enough operative language for parser admission.</p>
      </div>
    </body></html>
    """


@pytest.mark.parametrize(
    ("url_tail", "expected"),
    [
        ("3-101", "3-101"),
        ("3-102", "3-102"),
        ("25N%201~2", "25N 1/2"),
        ("25N%203~4", "25N 3/4"),
    ],
)
def test_massachusetts_section_parser_preserves_complete_url_identity(
    url_tail: str,
    expected: str,
) -> None:
    source_url = (
        "https://malegislature.gov/Laws/GeneralLaws/PartII/TitleII/"
        f"Chapter190B/Section{url_tail}"
    )

    row = parse_massachusetts_section_html(
        _section_html(expected),
        source_url=source_url,
    )

    assert section_number_from_url(source_url) == expected
    assert row is not None
    assert row.section_number == expected
    assert row.statute_id == f"Massachusetts General Laws ch. 190B § {expected}"
    assert row.official_cite == f"Mass. Gen. Laws ch. 190B, § {expected}"


def test_massachusetts_punctuation_sections_have_unique_canonical_projection() -> None:
    scraper = MassachusettsScraper("MA", "Massachusetts")
    cases = (
        ("3-101", "3-101"),
        ("3-102", "3-102"),
        ("25N%201~2", "25N 1/2"),
        ("25N%203~4", "25N 3/4"),
    )
    rows = []
    for url_tail, expected in cases:
        source_url = (
            "https://malegislature.gov/Laws/GeneralLaws/PartII/TitleII/"
            f"Chapter190B/Section{url_tail}"
        )
        parsed = parse_massachusetts_section_html(
            _section_html(expected),
            source_url=source_url,
        )
        assert parsed is not None
        rows.append(scraper._enrich_statute_structure(parsed).to_dict())

    projection = build_canonical_state_law_output_projection(
        rows,
        jurisdiction="MA",
    )

    assert projection["canonical_row_count"] == 4
    assert len(set(projection["canonical_keys"])) == 4
    assert projection["canonical_keys"] == [
        "urn:state:ma:statute:Massachusetts General Laws ch. 190B § 3-101",
        "urn:state:ma:statute:Massachusetts General Laws ch. 190B § 3-102",
        "urn:state:ma:statute:Massachusetts General Laws ch. 190B § 25N 1/2",
        "urn:state:ma:statute:Massachusetts General Laws ch. 190B § 25N 3/4",
    ]


def test_massachusetts_section_parser_is_bound_to_frontier_source_identity() -> None:
    scraper = MassachusettsScraper("MA", "Massachusetts")

    assert scraper.state_law_frontier_source_dependencies() == (
        massachusetts_section,
    )


def test_massachusetts_section_links_keep_punctuation_bearing_frontier_units() -> None:
    links = section_links(
        """
        <a href="/Laws/GeneralLaws/PartII/TitleII/Chapter190B/Section3-101">
          Section 3-101
        </a>
        <a href="/Laws/GeneralLaws/PartI/TitleXVI/Chapter111/Section25N%201~2">
          Section 25N 1/2
        </a>
        """
    )

    assert [number for _url, number in links] == ["3-101", "25N 1/2"]
    assert links[1][0].endswith("/Section25N%201~2")


@pytest.mark.parametrize(
    ("url_tail", "expected"),
    [
        ("3-101", "3-101"),
        ("3-102", "3-102"),
        ("25N%201~2", "25N 1/2"),
        ("25N%203~4", "25N 3/4"),
    ],
)
def test_massachusetts_fallback_parser_uses_complete_section_identity(
    monkeypatch: pytest.MonkeyPatch,
    url_tail: str,
    expected: str,
) -> None:
    monkeypatch.setattr(
        massachusetts_section,
        "parse_massachusetts_section_html",
        lambda *_args, **_kwargs: None,
    )
    scraper = MassachusettsScraper("MA", "Massachusetts")
    source_url = (
        "https://malegislature.gov/Laws/GeneralLaws/PartII/TitleII/"
        f"Chapter190B/Section{url_tail}"
    )

    row = scraper._parse_section_statute_html(
        "Massachusetts General Laws",
        source_url,
        _section_html(expected),
    )

    assert row is not None
    assert row.section_number == expected
    assert row.statute_id == f"Massachusetts General Laws ch. 190B § {expected}"
