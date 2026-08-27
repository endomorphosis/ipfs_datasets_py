"""Strict North Carolina active-section residual reconciliation."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    north_carolina_chapter as nc_chapter,
)

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina import (
    NorthCarolinaByChapterIncompleteError,
    NorthCarolinaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.north_carolina_chapter import (
    chapter_sections_url,
    chapter_url,
    chapter_section_index_frontier,
    north_carolina_section_page_identity,
    parse_north_carolina_section_html,
    section_url,
    source_bound_empty_chapter_disposition,
    source_bound_terminal_disposition_from_section_html,
)


def _fresh_receipt(html: str, *, final_url: str) -> dict[str, object]:
    payload = html.encode()
    return {
        "html": html,
        "provider": "fresh_live_https",
        "http_status": 200,
        "final_url": final_url,
        "final_host": "www.ncleg.gov",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "response_sha256": hashlib.sha256(payload).hexdigest(),
        "decoded_sha256": hashlib.sha256(payload).hexdigest(),
        "error_type": "",
        "error_message": "",
    }


def _residual_batch(
    urls: list[str],
    payloads: list[bytes],
) -> StateLawPageMultiFetchResult:
    observed_at = datetime.now(timezone.utc).isoformat()
    receipts = []
    envelopes = []
    for url, payload in zip(urls, payloads, strict=True):
        digest = hashlib.sha256(payload).hexdigest()
        transport = {
            "content_sha256": digest,
            "official_url": url,
            "source_transport": "direct",
        }
        receipts.append(dict(transport))
        envelopes.append(
            {
                "acquisition": {
                    "body_sha256": digest,
                    "receipt": {
                        "endpoint": url,
                        "content": {"sha256": digest},
                        "metadata": {"transport_receipt": transport},
                        "receipt_sha256": "a" * 64,
                        "retrieved_at": observed_at,
                    },
                }
            }
        )
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=[None] * len(urls),
        transport_receipts=receipts,
        parser_input_envelopes=envelopes,
        stats={},
    )


def _toc_html(chapters: tuple[str, ...] = ("1",)) -> str:
    links = "".join(
        f"<div class='row'><a href='/Laws/GeneralStatuteSections/Chapter{chapter}'>"
        f"Chapter {chapter}</a><span>Current chapter</span></div>"
        for chapter in chapters
    )
    return f"<html><body>{links}</body></html>"


def _section_index_html(*, terminal_only: bool = False) -> str:
    if terminal_only:
        rows = """
        <div class="row">
          <a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-1.html">HTML</a>
          <span>§ 1-1. Repealed by Session Laws 2000-1.</span>
        </div>
        <div class="row">
          <a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-2.html">HTML</a>
          <span>§ 1-2. Recodified as G.S. 2-1.</span>
        </div>
        """
    else:
        rows = """
        <div class="row">
          <a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-1.html">HTML</a>
          <span>§ 1-1. First current section.</span>
        </div>
        <div class="row">
          <a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-2.html">HTML</a>
          <span>§ 1-2. Second current section.</span>
        </div>
        <div class="row">
          <a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-3.html">HTML</a>
          <span>§ 1-3. Transferred to G.S. 2-3.</span>
        </div>
        """
    return f"<html><body>{rows}</body></html>"


def _chapter_html() -> str:
    return """
    <html><body>
      <p>§ 1-1. First current section.</p>
      <p>This first current statutory body is deliberately long enough for the
      shared North Carolina chapter parser to retain it without truncation.</p>
      <p>§ 1-999. Stale extra section.</p>
      <p>This stale extra statutory block is deliberately long enough to prove
      that the independent active frontier, not the chapter dump, controls.</p>
    </body></html>
    """


def _empty_terminal_index_html() -> str:
    return """
    <html><head><title>General Statute Sections - North Carolina General Assembly</title></head>
    <body><li class="breadcrumb-item active">Chapter 1</li>
      <h1 class="section-title">Chapter 1 - Former Civil Procedure.</h1>
      <p>§§ 1-1 through 1-2: Repealed by Session Laws 2000-1.</p>
    </body></html>
    """


def _section_html(
    section: str = "1-2",
    *,
    chapter: str = "1",
    body: str = (
        "This second current statutory body is deliberately long enough for "
        "the shared North Carolina parser to retain it as operative law."
    ),
) -> str:
    return f"""
    <!DOCTYPE html>
    <html><head><title>G.S. {section}</title></head><body>
      <h3><a name="GSDocumentHeader">Chapter {chapter}.</a></h3>
      <h3>Civil Procedure.</h3>
      <p>§ {section}. Second current section.</p>
      <p>{body}</p>
    </body></html>
    """


def test_north_carolina_section_inventory_types_recodified_and_transferred() -> None:
    records = chapter_section_index_frontier(
        _section_index_html(),
        chapter="1",
    )

    assert [row["section_number"] for row in records] == ["1-1", "1-2", "1-3"]
    assert [row["disposition"] for row in records] == [
        "active",
        "active",
        "inactive",
    ]


def test_north_carolina_section_inventory_excludes_other_terminal_labels() -> None:
    html = """
    <html><body>
      <div class="row"><a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-1.html"></a><span>§ 1-1. Deleted.</span></div>
      <div class="row"><a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-2.html"></a><span>§ 1-2. Omitted.</span></div>
      <div class="row"><a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-3.html"></a><span>§ 1-3. Superseded by G.S. 1-9.</span></div>
      <div class="row"><a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-4.html"></a><span>§ 1-4. Recodifed as G.S. 1-10.</span></div>
      <div class="row"><a href="/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-5.html"></a><span>§ 1-5. (Contingently repealed - see note) Current text.</span></div>
    </body></html>
    """

    records = chapter_section_index_frontier(html, chapter="1")

    assert [row["disposition"] for row in records] == [
        "inactive",
        "inactive",
        "inactive",
        "inactive",
        "active",
    ]


def test_north_carolina_exact_section_parser_is_source_bound() -> None:
    source_url = section_url("1", "1-2")
    html = _section_html()

    assert north_carolina_section_page_identity(html) == ("1", "1-2")
    row = parse_north_carolina_section_html(
        html,
        chapter="1",
        section="1-2",
        source_url=source_url,
    )
    assert row is not None
    assert row.chapter_number == "1"
    assert row.section_number == "1-2"
    assert row.source_url == source_url
    assert row.structured_data["source_kind"] == (
        "official_north_carolina_bysection_html"
    )
    assert "deliberately long enough" in str(row.full_text)

    assert parse_north_carolina_section_html(
        html.replace("G.S. 1-2", "G.S. 1-9", 1),
        chapter="1",
        section="1-2",
        source_url=source_url,
    ) is None


def test_north_carolina_exact_section_parser_accepts_source_bound_nc_variants() -> None:
    temporal_html = """
    <html><head><title>G.S. 105-1.1</title></head><body>
      <p>§ 105-1.1. (Effective until July 1, 2026) Earlier version.</p>
      <p>This earlier statutory version has enough operative body text to parse.</p>
      <p>§ 105-1.1. (Effective July 1, 2026) Current version.</p>
      <p>This current statutory version has enough operative body text to parse.</p>
    </body></html>
    """
    source = section_url("105", "105-1.1")

    assert north_carolina_section_page_identity(temporal_html) == (
        "105",
        "105-1.1",
    )
    current = parse_north_carolina_section_html(
        temporal_html,
        chapter="105",
        section="105-1.1",
        source_url=source,
        as_of_date=date(2026, 8, 25),
    )
    assert current is not None
    assert current.section_name.startswith("(Effective July 1, 2026)")
    assert current.structured_data["effective_variant_selection"] == (
        "source_observation_date"
    )

    punctuation_html = """
    <html><head><title>G.S. 143-215.74H</title></head><body>
      <p>§ 143.215.74H. Assistance.</p>
      <p>This official punctuation variant has enough operative body to parse.</p>
    </body></html>
    """
    assert north_carolina_section_page_identity(punctuation_html) == (
        "143",
        "143-215.74H",
    )
    punctuation_row = parse_north_carolina_section_html(
        punctuation_html,
        chapter="143",
        section="143-215.74H",
        source_url=section_url("143", "143-215.74H"),
        as_of_date=date(2026, 8, 25),
    )
    assert punctuation_row is not None
    assert punctuation_row.section_number == "143-215.74H"


@pytest.mark.parametrize(
    ("chapter", "section", "published_heading"),
    [
        ("20", "20-123.2", "§ 20-123.2 Speedometer."),
        ("106", "106-245.30", "§ 106-245.30 Legislative findings."),
        ("78A", "78A-13", "§ 78A -13. Disclosures required."),
    ],
)
def test_north_carolina_residual_identity_preserves_official_citation_variants(
    chapter: str,
    section: str,
    published_heading: str,
) -> None:
    html = f"""
    <html><head><title>G.S. {section}</title></head><body>
      <p>{published_heading}</p>
      <p>This operative statutory body is long enough to establish the exact
      retained section identity without changing its decimal citation.</p>
    </body></html>
    """

    row = parse_north_carolina_section_html(
        html,
        chapter=chapter,
        section=section,
        source_url=section_url(chapter, section),
    )

    assert row is not None
    assert row.section_number == section


def test_north_carolina_statutory_site_map_language_is_not_navigation() -> None:
    section = "18B-1001.5"
    html = f"""
    <html><head><title>G.S. {section}</title></head><body>
      <p>§ {section}. Authorization of common area entertainment permit.</p>
      <p>The applicant shall submit a plat or site map with the designated
      consumption areas clearly marked before the permit may issue.</p>
    </body></html>
    """

    row = parse_north_carolina_section_html(
        html,
        chapter="18B",
        section=section,
        source_url=section_url("18B", section),
    )

    assert row is not None
    assert "site map" in row.full_text


def test_north_carolina_heading_only_terminal_is_exactly_source_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        '<html><head><title>G.S. 1-9</title></head><body><p>'
        '<a name="GSDocumentHeader"></a>'
        "<span>§ 1-9. (See Editor's note) Sample terminal.</span>"
        "</p></body></html>"
    )
    key = ("1", "1-9")
    specification = {
        "content_sha256": hashlib.sha256(html.encode()).hexdigest(),
        "heading": "§ 1-9. (See Editor's note) Sample terminal.",
        "disposition": "editor_note_only",
    }
    monkeypatch.setitem(
        nc_chapter._EXACT_HEADING_ONLY_SECTION_TERMINALS,
        key,
        specification,
    )

    assert source_bound_terminal_disposition_from_section_html(
        html,
        chapter="1",
        section="1-9",
        source_url=section_url("1", "1-9"),
    ) == "editor_note_only"
    assert source_bound_terminal_disposition_from_section_html(
        html,
        chapter="1",
        section="1-9",
        source_url=section_url("1", "1-8"),
    ) is None
    assert source_bound_terminal_disposition_from_section_html(
        html.replace("Sample terminal", "Changed terminal"),
        chapter="1",
        section="1-9",
        source_url=section_url("1", "1-9"),
    ) is None

    shape_drift = html.replace("</body>", "<div>unexpected</div></body>")
    monkeypatch.setitem(
        nc_chapter._EXACT_HEADING_ONLY_SECTION_TERMINALS,
        key,
        {
            **specification,
            "content_sha256": hashlib.sha256(shape_drift.encode()).hexdigest(),
        },
    )
    assert source_bound_terminal_disposition_from_section_html(
        shape_drift,
        chapter="1",
        section="1-9",
        source_url=section_url("1", "1-9"),
    ) is None


def test_north_carolina_temporal_parser_selects_current_school_year_variant() -> None:
    html = """
    <html><head><title>G.S. 115C-83.6</title></head><body>
      <p>§ 115C-83.6. (Applicable before the beginning of the 2022-2023 school year) Earlier rule.</p>
      <p>This earlier school-year rule has enough operative statutory body text.</p>
      <p>§ 115C-83.6. (Applicable beginning with the 2022-2023 school year) Current rule.</p>
      <p>This current school-year rule has enough operative statutory body text.</p>
    </body></html>
    """

    row = parse_north_carolina_section_html(
        html,
        chapter="115C",
        section="115C-83.6",
        source_url=section_url("115C", "115C-83.6"),
        as_of_date=date(2026, 8, 25),
    )

    assert row is not None
    assert row.section_name.startswith("(Applicable beginning with")
    assert parse_north_carolina_section_html(
        html,
        chapter="1",
        section="1-2",
        source_url=section_url("1", "1-9"),
    ) is None


def test_north_carolina_empty_chapter_requires_two_source_bound_terminal_pages() -> None:
    chapter_html = """
    <html><head><title>Chapter 115</title></head><body>
      <h3>Chapter 115.</h3><h3>Elementary and Secondary Education.</h3>
      <p>§§ 115-1 through 115-410: Repealed by Session Laws 1981, c. 423.</p>
    </body></html>
    """
    index_html = """
    <html><head><title>General Statute Sections - North Carolina General Assembly</title></head>
    <body><li class="breadcrumb-item active">Chapter 115</li>
      <h1 class="section-title">Chapter 115 - Elementary and Secondary Education.</h1>
      <p>§§ 115-1 through 115-410: Repealed by Session Laws 1981, c. 423.</p>
    </body></html>
    """
    chapter_url = (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
        "Chapter_115.html"
    )
    index_url = "https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter115"

    assert source_bound_empty_chapter_disposition(
        chapter_html,
        index_html,
        chapter="115",
        chapter_source_url=chapter_url,
        section_index_source_url=index_url,
    ) == "repealed"
    assert source_bound_empty_chapter_disposition(
        chapter_html,
        index_html.replace("Chapter 115 -", "Chapter 116 -"),
        chapter="115",
        chapter_source_url=chapter_url,
        section_index_source_url=index_url,
    ) is None


@pytest.mark.anyio
async def test_north_carolina_residual_batch_uses_shared_grouped_warc_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    urls = [section_url("1", "1-1"), section_url("1", "1-2")]
    calls: list[tuple[list[str], dict[str, object]]] = []

    async def _batch(self, requested, **kwargs):
        calls.append((list(requested), dict(kwargs)))
        payloads = [_section_html(section).encode() for section in ("1-1", "1-2")]
        return _residual_batch(list(requested), payloads)

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _batch,
    )

    batch = await scraper._fetch_north_carolina_section_frontier_batch(
        urls,
        frontier_name="test",
    )

    assert len(batch.payloads) == 2
    assert calls[0][0] == urls
    assert calls[0][1]["prefer_direct"] is True
    assert calls[0][1]["common_crawl_domain_terms"] == ("www.ncleg.gov",)
    assert calls[0][1]["common_crawl_url_terms"] == (
        "/EnactedLegislation/Statutes/HTML/BySection/",
    )
    assert calls[0][1]["residual_retry_attempts"] == 1


@pytest.mark.anyio
async def test_north_carolina_full_run_replays_retained_frontier_before_network(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restart reuses TOC/chapter/index and plural-fetches only the miss."""

    evidence_root = tmp_path / "evidence"
    ledger = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="NC",
        parser_name="NorthCarolinaScraper",
    )
    retained_html = {
        NorthCarolinaScraper.OFFICIAL_TOC_URL: _toc_html(),
        chapter_url("1"): _chapter_html(),
        chapter_sections_url("1"): _section_index_html(),
    }
    observed_at = datetime.now(timezone.utc)
    for url, html in retained_html.items():
        payload = html.encode()
        ledger.retain_parser_input(
            official_url=url,
            body=payload,
            transport_receipt={
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            },
            retrieved_at=observed_at,
            response_status=200,
            media_type="text/html",
            sanitized_request={"method": "GET", "url": url},
            network_used=True,
        )
    retained_receipts_before = {
        item.receipt.receipt_sha256 for item in ledger.entries
    }
    retained_objects_before = {
        item.body_path.name for item in ledger.entries
    }

    scraper = NorthCarolinaScraper("NC", "North Carolina")
    scraper.attach_state_law_acquisition_ledger(ledger)
    fresh_network_calls: list[str] = []
    plural_calls: list[tuple[list[str], dict[str, object]]] = []

    async def _forbidden_fresh(self, url: str, **kwargs):
        fresh_network_calls.append(url)
        raise AssertionError("retained NC identity reached the live fetcher")

    async def _plural(self, urls, **kwargs):
        plural_calls.append((list(urls), dict(kwargs)))
        return _residual_batch(list(urls), [_section_html().encode()])

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_fresh_official_response_receipt",
        _forbidden_fresh,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path / "checkpoint"))
    monkeypatch.setenv(
        "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY",
        "test-only-north-carolina-retained-replay-hmac-key",
    )

    rows = await scraper._scrape_official_bychapter_html(
        "North Carolina General Statutes"
    )

    assert fresh_network_calls == []
    assert len(plural_calls) == 1
    assert plural_calls[0][0] == [section_url("1", "1-2")]
    assert plural_calls[0][1]["common_crawl_domain_terms"] == ("www.ncleg.gov",)
    assert plural_calls[0][1]["common_crawl_url_terms"] == (
        "/EnactedLegislation/Statutes/HTML/BySection/",
    )
    assert [row.section_number for row in rows] == ["1-1", "1-2"]
    checkpoint = json.loads(
        (tmp_path / "checkpoint" / "STATE-NC-partial.json").read_text()
    )
    chapter_evidence = checkpoint["progress"]["bychapter_chapter_evidence"][0]
    assert datetime.fromisoformat(chapter_evidence["observed_at"]) == observed_at
    assert datetime.fromisoformat(
        chapter_evidence["section_frontier_observed_at"]
    ) == observed_at
    assert datetime.fromisoformat(
        checkpoint["progress"]["bychapter_frontier_evidence"]["observed_at"]
    ) == observed_at
    ledger.refresh_existing_entries()
    assert {item.receipt.receipt_sha256 for item in ledger.entries} == (
        retained_receipts_before
    )
    assert {item.body_path.name for item in ledger.entries} == (
        retained_objects_before
    )
    assert scraper.get_fetch_analytics_snapshot()["providers"] == {
        "retained_acquisition_replay": 3
    }


@pytest.mark.anyio
async def test_north_carolina_residual_batch_fails_closed_on_alignment_and_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NorthCarolinaScraper("NC", "North Carolina")
    url = section_url("1", "1-1")

    async def _unaligned(self, requested, **kwargs):
        return StateLawPageMultiFetchResult(
            urls=list(requested),
            payloads=[],
            errors=[],
            transport_receipts=[],
            parser_input_envelopes=[],
            stats={},
        )

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _unaligned,
    )
    with pytest.raises(RuntimeError, match="unaligned"):
        await scraper._fetch_north_carolina_section_frontier_batch(
            [url],
            frontier_name="test",
        )
    with pytest.raises(RuntimeError, match="noncanonical"):
        await scraper._fetch_north_carolina_section_frontier_batch(
            ["https://example.invalid/GS_1-1.html"],
            frontier_name="test",
        )


def test_north_carolina_archived_residual_uses_capture_date_and_exact_bytes() -> None:
    url = section_url("1", "1-1")
    payload = _section_html("1-1").encode()
    digest = hashlib.sha256(payload).hexdigest()
    transport = {
        "archive_timestamp": "20240102030405",
        "content_sha256": digest,
        "official_url": url,
        "source_transport": "common_crawl",
    }
    envelope = {
        "acquisition": {
            "body_sha256": digest,
            "receipt": {
                "endpoint": url,
                "content": {"sha256": digest},
                "metadata": {"transport_receipt": transport},
                "receipt_sha256": "b" * 64,
                "retrieved_at": "2026-08-25T00:00:00+00:00",
            },
        }
    }

    context = NorthCarolinaScraper._north_carolina_section_evidence_context(
        source_url=url,
        payload=payload,
        transport_receipt=transport,
        parser_input_envelope=envelope,
    )

    assert context["as_of_date"] == date(2024, 1, 2)
    assert context["source_transport"] == "common_crawl"
    with pytest.raises(RuntimeError, match="changed parser bytes"):
        NorthCarolinaScraper._north_carolina_section_evidence_context(
            source_url=url,
            payload=payload + b"tampered",
            transport_receipt=transport,
            parser_input_envelope=envelope,
        )


@pytest.mark.anyio
async def test_north_carolina_full_run_reconciles_only_missing_active_sections(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched_residuals: list[list[str]] = []

    async def _fresh(self, url: str, *, timeout: int = 30):
        html = (
            _section_index_html()
            if url.endswith("GeneralStatuteSections/Chapter1")
            else _toc_html()
        )
        return _fresh_receipt(html, final_url=url)

    async def _chapter(self, number: str, *, timeout: int = 40):
        return _fresh_receipt(
            _chapter_html(),
            final_url=(
                "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/"
                f"ByChapter/Chapter_{number}.html"
            ),
        )

    async def _residual(self, urls, *, frontier_name: str):
        fetched_residuals.append(list(urls))
        return _residual_batch(list(urls), [_section_html().encode()])

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(NorthCarolinaScraper, "_fetch_official_https_fresh", _fresh)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _chapter,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_north_carolina_section_frontier_batch",
        _residual,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv(
        "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY",
        "test-only-north-carolina-residual-hmac-key",
    )

    rows = await NorthCarolinaScraper(
        "NC",
        "North Carolina",
    )._scrape_official_bychapter_html("North Carolina General Statutes")

    assert fetched_residuals == [[section_url("1", "1-2")]]
    assert [row.section_number for row in rows] == ["1-1", "1-2"]
    assert rows[0].source_url.endswith("/ByChapter/Chapter_1.html")
    assert rows[1].source_url == section_url("1", "1-2")
    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    progress = checkpoint["progress"]
    evidence = progress["bychapter_chapter_evidence"][0]
    assert checkpoint["stage_label"] == "north-carolina:bychapter-complete"
    assert progress["bychapter_completion_schema"].endswith("@4")
    assert progress["bychapter_resolved_count"] == 1
    assert progress["bychapter_unresolved_count"] == 0
    assert progress["bychapter_residual_section_frontier_count"] == 1
    assert progress["bychapter_residual_sections_scanned"] == 1
    assert progress["bychapter_residual_sections_parsed"] == 1
    assert evidence["disposition"] == "official_reconciled"
    assert evidence["active_section_numbers"] == ["1-1", "1-2"]
    assert evidence["inactive_section_numbers"] == ["1-3"]
    assert evidence["parsed_section_numbers"] == ["1-1", "1-2"]

    async def _forbidden_chapter(self, number: str, *, timeout: int = 40):
        raise AssertionError("authenticated reconciled chapter must not be refetched")

    async def _forbidden_residual(self, urls, *, frontier_name: str):
        raise AssertionError("authenticated residual rows must not be refetched")

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _forbidden_chapter,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_north_carolina_section_frontier_batch",
        _forbidden_residual,
    )
    resumed_rows = await NorthCarolinaScraper(
        "NC",
        "North Carolina",
    )._scrape_official_bychapter_html("North Carolina General Statutes")
    assert [row.section_number for row in resumed_rows] == ["1-1", "1-2"]
    resumed = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    assert resumed["progress"]["bychapter_authenticated_resume_count"] == 1


@pytest.mark.anyio
async def test_north_carolina_full_run_seals_and_resumes_terminal_residual(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_html = (
        '<html><head><title>G.S. 1-9</title></head><body><p>'
        '<a name="GSDocumentHeader"></a>'
        "<span>§ 1-9. (See Editor's note) Sample terminal.</span>"
        "</p></body></html>"
    )
    monkeypatch.setitem(
        nc_chapter._EXACT_HEADING_ONLY_SECTION_TERMINALS,
        ("1", "1-9"),
        {
            "content_sha256": hashlib.sha256(terminal_html.encode()).hexdigest(),
            "heading": "§ 1-9. (See Editor's note) Sample terminal.",
            "disposition": "editor_note_only",
        },
    )
    fetched_residuals: list[list[str]] = []

    async def _fresh(self, url: str, *, timeout: int = 30):
        html = (
            _section_index_html()
            .replace("1-2", "1-9")
            .replace("Second current section.", "(See Editor's note) Sample terminal.")
            if url.endswith("GeneralStatuteSections/Chapter1")
            else _toc_html()
        )
        return _fresh_receipt(html, final_url=url)

    async def _chapter(self, number: str, *, timeout: int = 40):
        return _fresh_receipt(_chapter_html(), final_url=chapter_url(number))

    async def _residual(self, urls, *, frontier_name: str):
        fetched_residuals.append(list(urls))
        return _residual_batch(list(urls), [terminal_html.encode()])

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(NorthCarolinaScraper, "_fetch_official_https_fresh", _fresh)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _chapter,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_north_carolina_section_frontier_batch",
        _residual,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv(
        "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY",
        "test-only-north-carolina-terminal-hmac-key",
    )

    rows = await NorthCarolinaScraper(
        "NC",
        "North Carolina",
    )._scrape_official_bychapter_html("North Carolina General Statutes")

    assert fetched_residuals == [[section_url("1", "1-9")]]
    assert [row.section_number for row in rows] == ["1-1"]
    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    progress = checkpoint["progress"]
    evidence = progress["bychapter_chapter_evidence"][0]
    assert progress["bychapter_residual_terminal_sections"] == [
        {
            "chapter_number": "1",
            "section_number": "1-9",
            "disposition": "editor_note_only",
        }
    ]
    assert evidence["active_section_numbers"] == ["1-1", "1-9"]
    assert evidence["parsed_section_numbers"] == ["1-1"]
    assert evidence["terminal_section_dispositions"] == [
        {"section_number": "1-9", "disposition": "editor_note_only"}
    ]
    assert evidence["section_active_count"] == 2
    assert evidence["parsed_statutes"] == 1

    async def _forbidden_chapter(self, number: str, *, timeout: int = 40):
        raise AssertionError("authenticated terminal residual must not refetch chapter")

    async def _forbidden_residual(self, urls, *, frontier_name: str):
        raise AssertionError("authenticated terminal residual must not be refetched")

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _forbidden_chapter,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_north_carolina_section_frontier_batch",
        _forbidden_residual,
    )
    resumed_rows = await NorthCarolinaScraper(
        "NC",
        "North Carolina",
    )._scrape_official_bychapter_html("North Carolina General Statutes")
    assert [row.section_number for row in resumed_rows] == ["1-1"]
    resumed = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    assert resumed["progress"]["bychapter_authenticated_resume_count"] == 1


@pytest.mark.anyio
async def test_north_carolina_full_run_fails_closed_on_residual_identity_drift(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fresh(self, url: str, *, timeout: int = 30):
        html = (
            _section_index_html()
            if url.endswith("GeneralStatuteSections/Chapter1")
            else _toc_html()
        )
        return _fresh_receipt(html, final_url=url)

    async def _chapter(self, number: str, *, timeout: int = 40):
        return _fresh_receipt(
            _chapter_html(),
            final_url=(
                "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/"
                f"ByChapter/Chapter_{number}.html"
            ),
        )

    async def _wrong_residual(self, urls, *, frontier_name: str):
        return _residual_batch(list(urls), [_section_html("1-9").encode()])

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(NorthCarolinaScraper, "_fetch_official_https_fresh", _fresh)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _chapter,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_north_carolina_section_frontier_batch",
        _wrong_residual,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))

    with pytest.raises(NorthCarolinaByChapterIncompleteError):
        await NorthCarolinaScraper(
            "NC",
            "North Carolina",
        )._scrape_official_bychapter_html("North Carolina General Statutes")

    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    evidence = checkpoint["progress"]["bychapter_unresolved_dispositions"][0]
    assert checkpoint["statutes_count"] == 0
    assert evidence["disposition"] == "section_residual_reconciliation_failed"
    assert evidence["error_type"] == "ResidualSectionIdentityError"
    assert "failed exact chapter" in evidence["error_message"]


@pytest.mark.anyio
async def test_north_carolina_full_run_resolves_source_bound_terminal_chapter(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fresh(self, url: str, *, timeout: int = 30):
        html = (
            _empty_terminal_index_html()
            if url.endswith("GeneralStatuteSections/Chapter1")
            else _toc_html()
        )
        return _fresh_receipt(html, final_url=url)

    async def _chapter(self, number: str, *, timeout: int = 40):
        html = """
        <html><head><title>Chapter 1</title></head><body><h3>Chapter 1.</h3>
        <p>§§ 1-1 through 1-2: Repealed and recodified.</p>
        <p>This source-bound official terminal chapter body deliberately carries
        enough disposition history to pass the transport truncation guard while
        contributing no operative statute rows to the current corpus.</p>
        </body></html>
        """
        return _fresh_receipt(
            html,
            final_url=(
                "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/"
                f"ByChapter/Chapter_{number}.html"
            ),
        )

    async def _forbidden_residual(self, urls, *, frontier_name: str):
        raise AssertionError("inactive sections must not enter the residual frontier")

    monkeypatch.setattr(NorthCarolinaScraper, "OFFICIAL_CHAPTERS", (("1", "Civil"),))
    monkeypatch.setattr(NorthCarolinaScraper, "_fetch_official_https_fresh", _fresh)
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _chapter,
    )
    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_north_carolina_section_frontier_batch",
        _forbidden_residual,
    )
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv(
        "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY",
        "test-only-north-carolina-terminal-hmac-key",
    )

    rows = await NorthCarolinaScraper(
        "NC",
        "North Carolina",
    )._scrape_official_bychapter_html("North Carolina General Statutes")

    assert rows == []
    checkpoint = json.loads((tmp_path / "STATE-NC-partial.json").read_text())
    evidence = checkpoint["progress"]["bychapter_chapter_evidence"][0]
    assert checkpoint["stage_label"] == "north-carolina:bychapter-complete"
    assert checkpoint["progress"]["bychapter_done"] == ["1"]
    assert checkpoint["progress"]["bychapter_terminal_chapter_count"] == 1
    assert evidence["disposition"] == "official_terminal"
    assert evidence["resolved"] is True
    assert evidence["section_active_count"] == 0
    assert evidence["section_inactive_count"] == 0

    async def _forbidden_chapter(self, number: str, *, timeout: int = 40):
        raise AssertionError("authenticated terminal chapter must not be refetched")

    monkeypatch.setattr(
        NorthCarolinaScraper,
        "_fetch_official_bychapter_page_fresh",
        _forbidden_chapter,
    )
    resumed = await NorthCarolinaScraper(
        "NC",
        "North Carolina",
    )._scrape_official_bychapter_html("North Carolina General Statutes")
    assert resumed == []
