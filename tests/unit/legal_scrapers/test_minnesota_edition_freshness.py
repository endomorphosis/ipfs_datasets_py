from __future__ import annotations

import hashlib
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota import (
    MinnesotaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.minnesota_section import (
    classify_minnesota_terminal_section_html,
    minnesota_statutes_edition_from_html,
    parse_minnesota_section_html,
)


CURRENT_EDITION = MinnesotaScraper.OFFICIAL_EDITION


def _page(body: str, *, edition: str = CURRENT_EDITION) -> bytes:
    return (
        "<html><body>"
        f"<div id='header'><h1>{edition}</h1></div>"
        f"{body}"
        "</body></html>"
    ).encode()


def test_minnesota_edition_is_bound_only_to_one_exact_header_heading() -> None:
    assert (
        minnesota_statutes_edition_from_html(
            _page("<p>2018 Minnesota Statutes</p>").decode()
        )
        == CURRENT_EDITION
    )
    assert (
        minnesota_statutes_edition_from_html(
            _page("", edition="2024 Minnesota Statutes").decode()
        )
        == "2024 Minnesota Statutes"
    )
    assert (
        minnesota_statutes_edition_from_html(
            "<h1>2025 Minnesota Statutes</h1>"
        )
        == ""
    )
    assert (
        minnesota_statutes_edition_from_html(
            "<div id='header'><h1>2025 Minnesota Statutes</h1></div>"
            "<div id='header'><h1>2025 Minnesota Statutes</h1></div>"
        )
        == ""
    )


def test_minnesota_exact_parser_requires_current_edition_and_source_identity() -> None:
    source_url = "https://www.revisor.mn.gov/statutes/cite/1.01"
    operative = _page(
        "<div class='section' id='stat.1.01'>"
        "<h1 class='shn'>1.01 SHORT LAW.</h1><p>It applies.</p></div>"
    ).decode()

    assert parse_minnesota_section_html(
        operative,
        source_url=source_url,
        expected_edition=CURRENT_EDITION,
        require_source_identity=True,
    ) is not None
    assert parse_minnesota_section_html(
        operative.replace(CURRENT_EDITION, "2024 Minnesota Statutes"),
        source_url=source_url,
        expected_edition=CURRENT_EDITION,
        require_source_identity=True,
    ) is None
    assert parse_minnesota_section_html(
        operative.replace("stat.1.01", "stat.9.99"),
        source_url=source_url,
        expected_edition=CURRENT_EDITION,
        require_source_identity=True,
    ) is None


def test_minnesota_exact_builder_does_not_generic_admit_terminal_notice() -> None:
    source_url = "https://www.revisor.mn.gov/statutes/cite/1.02"
    terminal = _page(
        "<nav>" + ("Minnesota statutes navigation and publication links. " * 8)
        + "</nav><div class='sr' id='stat.1.02'><b>1.02</b> "
        "[Repealed, 2025 c 1 s 1]</div>"
    ).decode()
    scraper = MinnesotaScraper("MN", "Minnesota")

    assert scraper._build_statute_from_section_html(
        "Minnesota Statutes",
        source_url,
        terminal,
        expected_edition=CURRENT_EDITION,
        strict_source_bound=True,
    ) is None
    classified = classify_minnesota_terminal_section_html(
        terminal,
        source_url=source_url,
        expected_edition=CURRENT_EDITION,
    )
    assert classified is not None
    assert classified["disposition"] == "repealed"


def test_minnesota_terminal_classifier_accepts_source_bound_multiline_markers() -> None:
    source_url = "https://www.revisor.mn.gov/statutes/cite/1.03"
    payload = _page(
        "<div class='sr_by_subd' id='stat.1.03'><h1>1.03</h1>"
        "<div class='subd' id='stat.1.03.1'>"
        "<p>(a) [Renumbered 2.01, subdivision 1]</p>"
        "<p class='r'>(b) [Repealed by amendment, 2025 c 1 s 1]</p>"
        "</div></div>"
    ).decode()

    classified = classify_minnesota_terminal_section_html(
        payload,
        source_url=source_url,
        expected_edition=CURRENT_EDITION,
    )

    assert classified is not None
    assert classified["disposition"] == "renumbered+repealed"
    assert classified["source_blocks"] == 2


@pytest.mark.parametrize(
    ("reference", "expected"),
    (
        ("[Deleted, 1995 c 233 art 2 s 56]", "deleted"),
        ("[Uncodified, 2019 c 54 art 1 s 33]", "uncodified"),
        ("Renumbered [142B.79]", "renumbered"),
        (
            "[CITY OF BLOOMINGTON; LOCAL.] [2013 c 111 art 5 s 80]",
            "local_or_special",
        ),
        ("MS 1998[Repealed, 1999 c 205 art 5 s 22]", "repealed"),
    ),
)
def test_minnesota_terminal_classifier_accepts_exact_revisor_marker_variants(
    reference: str,
    expected: str,
) -> None:
    source_url = "https://www.revisor.mn.gov/statutes/cite/1.04"
    payload = _page(
        "<div class='sr' id='stat.1.04'><b>1.04</b>"
        f" {reference}</div>"
    ).decode()

    classified = classify_minnesota_terminal_section_html(
        payload,
        source_url=source_url,
        expected_edition=CURRENT_EDITION,
    )

    assert classified is not None
    assert classified["disposition"] == expected


def test_minnesota_terminal_classifier_rejects_untyped_or_misbound_reference() -> None:
    source_url = "https://www.revisor.mn.gov/statutes/cite/1.05"
    untyped = _page(
        "<div class='sr' id='stat.1.05'><b>1.05</b> [Editorial note]</div>"
    ).decode()
    wrong_subdivision = _page(
        "<div class='sr_by_subd' id='stat.1.05'>"
        "<div class='subd' id='stat.9.99.1'><p>[Repealed, 2025 c 1 s 1]"
        "</p></div></div>"
    ).decode()

    assert classify_minnesota_terminal_section_html(
        untyped,
        source_url=source_url,
        expected_edition=CURRENT_EDITION,
    ) is None
    assert classify_minnesota_terminal_section_html(
        wrong_subdivision,
        source_url=source_url,
        expected_edition=CURRENT_EDITION,
    ) is None


@pytest.mark.anyio
async def test_minnesota_plural_fetch_rejects_historical_edition_even_if_aligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    url = "https://www.revisor.mn.gov/statutes/cite/1.01"
    historical = _page(
        "<div class='section' id='stat.1.01'><h1 class='shn'>"
        "1.01 OLD LAW.</h1><p>Historical body.</p></div>",
        edition="2024 Minnesota Statutes",
    )
    current = historical.replace(b"2024 Minnesota Statutes", CURRENT_EDITION.encode())
    captured: dict[str, Any] = {}

    async def _aligned(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        captured.update(kwargs)
        requested = list(urls)
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[historical],
            errors=[None],
            transport_receipts=[None],
            parser_input_envelopes=[None],
            stats={"requested_pages": 1},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _aligned,
    )

    with pytest.raises(RuntimeError, match="historical Minnesota Statutes edition"):
        await scraper._fetch_minnesota_frontier_batch(
            [url],
            frontier_name="section",
            expected_edition=CURRENT_EDITION,
        )

    validator = captured["content_validator"]
    assert validator(historical) is False
    assert validator(current) is True


@pytest.mark.anyio
async def test_minnesota_current_root_rejects_historical_archive_edition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    historical_root = _page(
        "<table id='chapters_table'><tr><td>"
        "<a href='/statutes/cite/1'>1</a></td><td>Chapter one</td></tr></table>",
        edition="2024 Minnesota Statutes",
    )

    async def _historical(_url: str, **_kwargs: Any) -> bytes:
        return historical_root

    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _historical,
    )

    with pytest.raises(RuntimeError, match="historical statutes edition"):
        await scraper._discover_chapter_urls(max_chapters=None)


def test_minnesota_retained_replay_rechecks_root_edition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MinnesotaScraper("MN", "Minnesota")
    root_url = scraper.OFFICIAL_ENTRY_URL
    historical_root = _page(
        "<table id='chapters_table'><tr><td>"
        "<a href='/statutes/cite/1'>1</a></td><td>Chapter one</td></tr></table>",
        edition="2024 Minnesota Statutes",
    )
    digest = hashlib.sha256(historical_root).hexdigest()

    monkeypatch.setattr(
        scraper,
        "_replay_minnesota_retained_inputs",
        lambda urls, **_kwargs: [historical_root for _url in urls],
    )

    with pytest.raises(RuntimeError, match="historical statutes edition"):
        scraper._replay_minnesota_source_frontier(
            {
                "catalog_report": {
                    "catalog_mode": "direct_chapter_table",
                    "chapter_count": 1,
                    "content_sha256": digest,
                    "edition": CURRENT_EDITION,
                    "source_url": root_url,
                },
                "chapter_reports": [
                    {
                        "content_sha256": "0" * 64,
                        "edition": CURRENT_EDITION,
                        "source_section_count": 1,
                        "source_url": "https://www.revisor.mn.gov/statutes/cite/1",
                    }
                ],
                "section_reports": [
                    {
                        "canonical_identity": "1.01",
                        "content_sha256": "1" * 64,
                        "disposition": "operative",
                        "edition": CURRENT_EDITION,
                        "source_url": (
                            "https://www.revisor.mn.gov/statutes/cite/1.01"
                        ),
                    }
                ],
                "toc_part_reports": [],
            }
        )
