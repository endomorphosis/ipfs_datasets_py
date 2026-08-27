from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    get_official_source_catalog,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska import (
    AlaskaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alaska_section import (
    parse_alaska_statute_html,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado import (
    ColoradoScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.colorado_title import (
    parse_colorado_title_html,
    title_download_rows,
)


def _ak_section(number: str, *, body: str | None = None) -> str:
    text = body or (f"Official Alaska statutory body for section {number}. " * 5)
    return (
        f'<b><a name="{number}"> </a>Sec. {number}. Complete section {number}.</b>'
        f"{text}<br><br>"
    )


def _co_body_html(number: str, *, body: str | None = None) -> str:
    text = body or (f"Official Colorado statutory body for section {number}. " * 5)
    return (
        "<div class='WordSection2'>"
        f"<p style='margin-left:1.25in'>{number}. Table of contents copy.</p>"
        "</div>"
        "<div class='WordSection3'>"
        "<p style='text-indent:.15in;page-break-after:avoid'>"
        f"<b><span>{number}.</span></b><span> <b>Complete section.</b></span>"
        "</p>"
        f"<p>{text}</p>"
        "<p><b>Source:</b> L. 2026: p. 1.</p>"
        "<p><b>ANNOTATION</b></p>"
        "<p>Editorial annotation must not enter statutory text.</p>"
        "</div>"
    )


def _co_download_page(numbers: list[str]) -> bytes:
    rows = []
    for number in numbers:
        token = number if "." in number else number.zfill(2)
        rows.append(
            "<tr>"
            f"<th>Title {number} — Test title {number}</th>"
            f'<td><a href="https://olls.info/crs/crs2026-title-{token}.htm">HTM</a></td>'
            "</tr>"
        )
    return ("<html><body><table>" + "".join(rows) + "</table></body></html>").encode()


def test_alaska_parser_splits_every_anchored_heading_and_keeps_long_body() -> None:
    long_body = "Long Alaska subsection text remains complete. " * 500
    html = (
        "<div class='statute'>"
        + _ak_section("01.05.006")
        + "</div><p>"
        + '<b><a name="01.05.010"> </a>Sec. 01.05.010. [Repealed, ch. 1 SLA 1963.]</b>'
        + _ak_section("01.05.011", body=long_body)
        + "</p>"
    )

    rows = parse_alaska_statute_html(html)

    assert [row.section_number for row in rows] == ["01.05.006", "01.05.011"]
    assert rows[0].full_text.endswith("01.05.006.")
    assert len(rows[1].full_text) == len(long_body.strip())
    assert len(rows[1].full_text) > 14_000


@pytest.mark.anyio
async def test_alaska_bounded_traversal_passes_lastsec_as_exclusive_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fetch(self, sec_start: str, timeout_seconds: int = 8):
        calls.append(sec_start)
        if sec_start == "1":
            return _ak_section("01.05.006") + _ak_section("01.05.011"), "01.05.011"
        if sec_start == "01.05.011":
            return _ak_section("01.05.016"), "01.05.016"
        return "", ""

    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _fetch)
    scraper = AlaskaScraper("AK", "Alaska")
    rows = await scraper.scrape_code(
        "Alaska Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=3,
    )

    assert calls == ["1", "01.05.011"]
    assert [row.section_number for row in rows] == [
        "01.05.006",
        "01.05.011",
        "01.05.016",
    ]


@pytest.mark.anyio
async def test_alaska_full_traversal_closes_all_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = []
    for title, _name in AlaskaScraper.OFFICIAL_TITLES:
        sections.append(_ak_section(f"{int(title):02d}.01.001"))
    page = "".join(sections)

    async def _fetch(self, sec_start: str, timeout_seconds: int = 8):
        if sec_start == "1":
            return page, "47.01.001"
        assert sec_start == "47.01.001"
        return "", ""

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _fetch)
    scraper = AlaskaScraper("AK", "Alaska")
    rows = await scraper.scrape_code(
        "Alaska Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert len(rows) == len(AlaskaScraper.OFFICIAL_TITLES)
    assert {str(int(row.title_number or "0")) for row in rows} == {
        number for number, _name in AlaskaScraper.OFFICIAL_TITLES
    }


@pytest.mark.anyio
async def test_alaska_full_traversal_rejects_cycle_and_underfill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        "1": (_ak_section("01.05.006"), "01.05.006"),
        "01.05.006": (_ak_section("01.05.011"), "01.05.006"),
    }

    async def _cycle(self, sec_start: str, timeout_seconds: int = 8):
        return responses.get(sec_start, ("", ""))

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _cycle)
    scraper = AlaskaScraper("AK", "Alaska")
    with pytest.raises(RuntimeError, match="LastSec did not advance"):
        await scraper.scrape_code("Alaska Statutes", scraper.OFFICIAL_ENTRY_URL)

    async def _underfill(self, sec_start: str, timeout_seconds: int = 8):
        if sec_start == "1":
            return _ak_section("01.05.006"), "47.90.070"
        return "", ""

    monkeypatch.setattr(AlaskaScraper, "_fetch_statute_chunk", _underfill)
    with pytest.raises(RuntimeError, match="missing_titles"):
        await scraper.scrape_code("Alaska Statutes", scraper.OFFICIAL_ENTRY_URL)


def test_colorado_referral_discovery_accepts_only_delegated_htm_links() -> None:
    html = """
    <table>
      <tr><th>Colorado Constitution</th><td><a href="https://olls.info/crs/crs2026-title-00.htm">HTM</a></td></tr>
      <tr><th>Title 25.5 — Health Care Policy and Financing</th><td><a href="https://olls.info/crs/crs2026-title-25.5.htm">HTM</a></td></tr>
      <tr><th>Title 26 — Human Services Code</th><td><a href="https://olls.info/crs/crs2026-title-26.htm">HTM</a></td></tr>
      <tr><th>Title 27 — Behavioral Health</th><td><a href="https://evil.example/crs/crs2026-title-27.htm">HTM</a></td></tr>
    </table>
    """

    rows = title_download_rows(
        html,
        page_url=ColoradoScraper.OFFICIAL_CRS_TITLES_DOWNLOAD_URL,
    )

    assert rows == [
        (
            "25.5",
            "Health Care Policy and Financing",
            "https://olls.info/crs/crs2026-title-25.5.htm",
            "2026",
        ),
        (
            "26",
            "Human Services Code",
            "https://olls.info/crs/crs2026-title-26.htm",
            "2026",
        ),
    ]


def test_colorado_dom_parser_uses_body_occurrence_and_preserves_full_text() -> None:
    long_body = "Complete Colorado statutory subsection text. " * 500
    html = (
        "<html><body>"
        + _co_body_html("25.5-1-101", body=long_body)
        + _co_body_html("25.5-1-102")
        + "</body></html>"
    )

    rows = parse_colorado_title_html(
        html,
        source_url="https://olls.info/crs/crs2026-title-25.5.htm",
    )

    assert [row.section_number for row in rows] == ["25.5-1-101", "25.5-1-102"]
    assert len(rows[0].full_text) == len(long_body.strip())
    assert len(rows[0].full_text) > 14_000
    assert "Table of contents copy" not in rows[0].full_text
    assert "L. 2026" not in rows[0].full_text
    assert "Editorial annotation" not in rows[0].full_text


@pytest.mark.anyio
async def test_colorado_bounded_mode_allows_partial_official_title_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _co_download_page(["18"])
    title_url = "https://olls.info/crs/crs2026-title-18.htm"
    payloads = {
        ColoradoScraper.OFFICIAL_CRS_TITLES_DOWNLOAD_URL: page,
        title_url: ("<html><body>" + _co_body_html("18-1-101") + "</body></html>").encode(
            "cp1252"
        ),
    }

    async def _request(self, url: str, timeout_seconds: int = 45) -> bytes:
        return payloads.get(url, b"")

    monkeypatch.setattr(ColoradoScraper, "_request_bytes_direct", _request)
    scraper = ColoradoScraper("CO", "Colorado")
    rows = await scraper.scrape_code(
        "Colorado Revised Statutes",
        scraper.OFFICIAL_CRS_TITLES_DOWNLOAD_URL,
        max_statutes=1,
    )

    assert [row.section_number for row in rows] == ["18-1-101"]
    assert rows[0].structured_data["delegated_download_host"] == "olls.info"


@pytest.mark.anyio
async def test_colorado_full_mode_requires_and_parses_exact_title_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ColoradoScraper("CO", "Colorado")
    numbers = [str(number) for number, _name in scraper.OFFICIAL_CRS_TITLES]
    payloads: dict[str, bytes] = {
        scraper.OFFICIAL_CRS_TITLES_DOWNLOAD_URL: _co_download_page(numbers)
    }
    for number in numbers:
        token = number if "." in number else number.zfill(2)
        url = f"https://olls.info/crs/crs2026-title-{token}.htm"
        payloads[url] = (
            "<html><body>" + _co_body_html(f"{number}-1-101") + "</body></html>"
        ).encode("cp1252")

    direct_urls: list[str] = []
    plural_calls: list[list[str]] = []

    async def _request(self, url: str, timeout_seconds: int = 45) -> bytes:
        direct_urls.append(url)
        assert url == self.OFFICIAL_CRS_TITLES_DOWNLOAD_URL
        return payloads[url]

    async def _plural(self, urls, **_kwargs):
        requested = list(urls)
        plural_calls.append(requested)
        return SimpleNamespace(
            urls=requested,
            payloads=[payloads[url] for url in requested],
            errors=[None] * len(requested),
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={},
        )

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(ColoradoScraper, "_request_bytes_direct", _request)
    monkeypatch.setattr(
        ColoradoScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    rows = await scraper.scrape_code(
        "Colorado Revised Statutes",
        scraper.OFFICIAL_CRS_TITLES_DOWNLOAD_URL,
        max_statutes=None,
    )

    assert len(rows) == len(numbers) == 46
    assert {row.title_number for row in rows} == set(numbers)
    assert all(row.structured_data["edition"] == "2026" for row in rows)
    assert direct_urls == [scraper.OFFICIAL_CRS_TITLES_DOWNLOAD_URL]
    assert plural_calls == [[url for url in payloads if url != direct_urls[0]]]


@pytest.mark.anyio
async def test_colorado_full_mode_rejects_partial_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _request(self, url: str, timeout_seconds: int = 45) -> bytes:
        if url == self.OFFICIAL_CRS_TITLES_DOWNLOAD_URL:
            return _co_download_page(["1", "2"])
        return b""

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(ColoradoScraper, "_request_bytes_direct", _request)
    scraper = ColoradoScraper("CO", "Colorado")
    with pytest.raises(RuntimeError, match="partial or inconsistent"):
        await scraper.scrape_code(
            "Colorado Revised Statutes",
            scraper.OFFICIAL_CRS_TITLES_DOWNLOAD_URL,
            max_statutes=None,
        )


def test_colorado_source_catalog_seals_olls_as_official_referral_domain() -> None:
    colorado = get_official_source_catalog().get("CO")
    path = colorado.acquisition_paths[0]

    assert "olls.info" in path.allowed_domains
    assert path.entry_url == ColoradoScraper.OFFICIAL_CRS_TITLES_DOWNLOAD_URL
    assert "official referral page" in path.notes


def test_colorado_frontier_observation_parses_exact_referral_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ColoradoScraper("CO", "Colorado")
    numbers = [str(number) for number, _name in scraper.OFFICIAL_CRS_TITLES]
    page = _co_download_page(numbers)
    monkeypatch.setattr(scraper, "_official_http_get", lambda _url: page)

    fetched = scraper.fetch_official("CO")

    assert fetched.source_path == scraper.OFFICIAL_ENTRY_PATH
    assert fetched.body_bytes == page
    assert fetched.response_bytes == page
    assert fetched.edition == "2026"
    assert fetched.frontier["bundle_closed"] is True
    assert fetched.frontier["expected_index_units"] == 46
    assert len(fetched.rows) == 46
    assert all(
        str(row["source_url"]).startswith("https://olls.info/crs/crs2026-title-")
        for row in fetched.rows
    )
