from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Any, Sequence

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut import (
    ConnecticutScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.connecticut_chapter import (
    chapters_from_title,
    connecticut_section_frontier,
)


def _official_index_html(scraper: ConnecticutScraper) -> bytes:
    rows: list[str] = []
    inactive = set(scraper.OFFICIAL_INACTIVE_TITLE_NUMBERS)
    reserved = set(scraper.OFFICIAL_RESERVED_TITLE_NUMBERS)
    for token in scraper.OFFICIAL_TITLE_NUMBERS:
        designation = f"<span class='toc_ttl_desig'>Title {token}</span>"
        if token in reserved:
            linked_designation = designation
            name = "Reserved for future use"
        else:
            filename = PurePosixPath(scraper.official_title_url(token)).name
            linked_designation = f"<a href='{filename}'>{designation}</a>"
            name = (
                "All sections transferred or repealed"
                if token in inactive
                else "Current statutory provisions"
            )
        rows.append(
            "<tr><td>"
            f"{linked_designation}</td>"
            f"<td><span class='toc_ttl_name'>{name}</span></td></tr>"
        )
    return (
        "<html><body>"
        f"<h2>Revised to {scraper.OFFICIAL_BASE_REVISION_DATE}</h2>"
        f"<a href='{scraper.OFFICIAL_SUPPLEMENT_ENTRY_PATH}'>"
        "Readers should refer to the 2026 Supplement</a>"
        "<table>" + "".join(rows) + "</table></body></html>"
    ).encode()


def _official_supplement_index_html(scraper: ConnecticutScraper) -> bytes:
    rows: list[str] = []
    for token in scraper.OFFICIAL_SUPPLEMENT_TITLE_NUMBERS:
        filename = PurePosixPath(scraper.official_supplement_title_url(token)).name
        rows.append(
            "<tr><td>"
            f"<a href='{filename}'><span class='toc_ttl_desig'>"
            f"Title {token}</span></a></td>"
            "<td><span class='toc_ttl_name'>Supplement changes</span></td></tr>"
        )
    return (
        "<html><body><h1>2026 Supplement to the General Statutes of "
        "Connecticut</h1>"
        f"<h2>Revised to {scraper.OFFICIAL_SUPPLEMENT_REVISION_DATE}</h2>"
        "<a href='/current/pub/titles.htm'>This 2026 Supplement is intended "
        "to be used in conjunction with the General Statutes of Connecticut</a>"
        "<table>" + "".join(rows) + "</table></body></html>"
    ).encode()


def _record(url: str, payload: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "url": url,
        "payload": payload,
        "error": "",
        "content_sha256": digest,
        "transport_receipt": {
            "content_sha256": digest,
            "official_url": url,
            "source_transport": "direct",
        },
    }


def _active_chapter_html(number: str = "1-1") -> bytes:
    return (
        "<html><body>"
        "<p class='toc_catchln'><a href='#sec_"
        f"{number}'>Sec. {number}. Short title.</a></p>"
        "<p><span class='catchln' id='sec_"
        f"{number}'>Sec. {number}. Short title.</span> "
        "This chapter shall be known as the Connecticut evidence act.</p>"
        "<table class='nav_tbl'><tr><td>navigation</td></tr></table>"
        "</body></html>"
    ).encode()


def _inactive_chapter_html(number: str = "2-1") -> bytes:
    return (
        "<html><body>"
        "<p class='toc_catchln'><a href='#sec_"
        f"{number}'>Sec. {number}. (Repealed.)</a></p>"
        "<p><span class='catchln' id='sec_"
        f"{number}'>Sec. {number}. (Repealed.)</span></p>"
        "</body></html>"
    ).encode()


def _inactive_grouped_chapter_html() -> bytes:
    return b"""
    <html><body>
      <p class="toc_catchln"><a href="#secs_1-56h_to_1-56k">
        Secs. 1-56h to 1-56k. Former springing powers.
      </a></p>
      <p><span class="catchln" id="secs_1-56h_to_1-56k">
        Secs. 1-56h to 1-56k. Former springing powers.
      </span> Sections 1-56h to 1-56k, inclusive, are repealed,
      effective October 1, 2016.</p>
      <p class="toc_catchln"><a href="#secs_1-56l_to_1-56q">
        Secs. 1-56l to 1-56q.
      </a> Reserved</p>
      <p><span class="catchln" id="secs_1-56l_to_1-56q">
        Secs. 1-56l to 1-56q.
      </span> Reserved for future use.</p>
    </body></html>
    """


def _overlay_row(section: str, chapter_url: str) -> NormalizedStatute:
    return NormalizedStatute(
        state_code="CT",
        state_name="Connecticut",
        statute_id=f"Connecticut General Statutes § {section}",
        code_name="Connecticut General Statutes",
        section_number=section,
        section_name=f"Section {section}",
        full_text=f"Operative text for section {section}.",
        source_url=f"{chapter_url}#sec_{section}",
    )


def _group_tombstone(
    scraper: ConnecticutScraper,
    number: str,
) -> dict[str, Any]:
    evidence = scraper._OFFICIAL_SUPPLEMENT_GROUP_TOMBSTONE_EXPANSIONS[number]
    digest = str(evidence["content_sha256"])
    chapter_url = str(evidence["chapter_url"])
    return {
        "section_number": number,
        "chapter_url": chapter_url,
        "content_sha256": digest,
        "transport_receipt": {
            "content_sha256": digest,
            "official_url": chapter_url,
            "source_transport": "direct",
        },
    }


# Exact locator/catchline structure retained in official chap_319a.htm body
# SHA-256 12600b721582c2ff8883527912383921b3849ac9a71db2e73ba057fc3bfecec2.
_TRUE_17A_175 = b"""
<html><body>
  <p class="toc_catchln"><a href="#sec_17a-175">
    Sec. 17a-175. (Formerly Sec. 17-81a). Compact.
  </a></p>
  <p><span class="catchln" id="sec_17a-175">
    Sec. 17a-175. (Formerly Sec. 17-81a). Compact.
  </span> The Interstate Compact on the Placement of Children is hereby
  enacted into law and entered into with all other jurisdictions legally
  joining therein in form substantially as follows:</p>
  <p class="Text-center">INTERSTATE COMPACT ON THE PLACEMENT OF CHILDREN</p>
  <p>Article I governs placement of children.</p>
  <table class="nav_tbl"><tr><td>navigation</td></tr></table>
</body></html>
"""


# Exact stale locator, TOC, catchline, and introductory paragraph retained in
# official chap_319i.htm body SHA-256
# 76a4e6ebe4ea419c0840baef209230806c0f8e2072f14eb5d9ba2603f29f7ca4.
_STALE_ANCHOR_17A_615 = b"""
<html><body>
  <p class="toc_catchln"><a href="#sec_17a-175">
    Sec. 17a-615. (Formerly Sec. 17-258). Interstate Compact on Mental Health.
  </a></p>
  <p><span class="catchln" id="sec_17a-175">Sec. 17a-615. (Formerly Sec.
  17-258). Interstate Compact on Mental Health.</span> The Interstate Compact
  on Mental Health is hereby enacted into law and entered into by this state
  with all other states legally joining therein in the form substantially as
  follows:</p>
  <p class="Text-center">INTERSTATE COMPACT ON MENTAL HEALTH</p>
  <p>The contracting states solemnly agree that Article I applies.</p>
  <table class="nav_tbl"><tr><td>navigation</td></tr></table>
</body></html>
"""


def test_connecticut_official_catalog_closes_exact_dynamic_frontier() -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")

    rows = scraper.enumerate_official_title_catalog(
        _official_index_html(scraper),
        page_url=scraper.OFFICIAL_ENTRY_URL,
    )
    reserved = scraper._assert_connecticut_title_catalog_closed(rows)

    assert len(rows) == 83
    assert [row["title_number"] for row in rows] == list(
        scraper.OFFICIAL_TITLE_NUMBERS
    )
    assert sum(row["unit_disposition"] == "active" for row in rows) == 72
    assert sum(row["unit_disposition"] == "inactive" for row in rows) == 9
    assert sum(bool(row["official_link_present"]) for row in rows) == 81
    assert reserved == {"2a", "2b"}


def test_connecticut_supplement_catalog_closes_exact_current_frontier() -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    html = _official_supplement_index_html(scraper)

    rows = scraper.enumerate_official_title_catalog(
        html,
        page_url=scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL,
    )
    scraper._assert_connecticut_supplement_catalog_closed(
        rows,
        html_text=html.decode(),
        page_url=scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL,
    )

    assert len(rows) == 59
    assert [row["title_number"] for row in rows] == list(
        scraper.OFFICIAL_SUPPLEMENT_TITLE_NUMBERS
    )
    assert all(row["unit_disposition"] == "active" for row in rows)
    assert all(row["official_link_present"] is True for row in rows)


def test_connecticut_title_42a_discovers_exact_article_frontier() -> None:
    title_url = "https://www.cga.ct.gov/current/pub/title_42a.htm"
    html = """<html><body>
      <a href="art_001.htm">Article 1</a>
      <a href="art_001.htm">General Provisions</a>
      <a href="art_002a.htm">Article 2A</a>
      <a href="titles.htm">Return to List of Titles</a>
    </body></html>"""

    assert chapters_from_title(html, base_url=title_url) == [
        ("https://www.cga.ct.gov/current/pub/art_001.htm", "1"),
        ("https://www.cga.ct.gov/current/pub/art_002a.htm", "2a"),
    ]


def test_connecticut_grouped_inactive_ranges_are_frontier_units() -> None:
    assert connecticut_section_frontier(
        _inactive_grouped_chapter_html().decode()
    ) == [
        {
            "anchor_id": "secs_1-56h_to_1-56k",
            "disposition": "inactive",
            "section_number": "1-56h_to_1-56k",
        },
        {
            "anchor_id": "secs_1-56l_to_1-56q",
            "disposition": "inactive",
            "section_number": "1-56l_to_1-56q",
        },
    ]


def test_connecticut_exact_grouped_supplement_tombstones_close_base() -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._last_connecticut_full_frontier = {
        "base_frontier_closed": True,
        "supplement_frontier_closed": True,
    }
    unaffected = _overlay_row(
        "1-1", "https://www.cga.ct.gov/current/pub/chap_001.htm"
    )
    base_rows = [unaffected]
    for evidence in scraper._OFFICIAL_SUPPLEMENT_GROUP_TOMBSTONE_EXPANSIONS.values():
        base_rows.extend(
            _overlay_row(str(section), str(evidence["base_chapter_url"]))
            for section in evidence["sections"]
        )
    tombstones = [
        _group_tombstone(scraper, number)
        for number in scraper._OFFICIAL_SUPPLEMENT_GROUP_TOMBSTONE_EXPANSIONS
    ]

    rows = scraper._overlay_connecticut_supplement(
        base_rows,
        [],
        tombstones=tombstones,
    )

    assert [row.section_number for row in rows] == ["1-1"]
    frontier = scraper._last_connecticut_full_frontier
    assert frontier["supplement_tombstones_applied"] == 19
    assert frontier["supplement_group_tombstone_notices_applied"] == 4
    assert frontier["supplement_group_tombstone_sections_applied"] == 19
    assert frontier["combined_sections_emitted"] == 1
    assert frontier["currentness_closed"] is True


@pytest.mark.parametrize("drift_field", ["chapter_url", "receipt_url", "digest"])
def test_connecticut_grouped_supplement_tombstone_rejects_evidence_drift(
    drift_field: str,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._last_connecticut_full_frontier = {
        "base_frontier_closed": True,
        "supplement_frontier_closed": True,
    }
    number = "10-511_and_10-511a"
    evidence = scraper._OFFICIAL_SUPPLEMENT_GROUP_TOMBSTONE_EXPANSIONS[number]
    base_rows = [
        _overlay_row(str(section), str(evidence["base_chapter_url"]))
        for section in evidence["sections"]
    ]
    tombstone = _group_tombstone(scraper, number)
    if drift_field == "chapter_url":
        tombstone["chapter_url"] += "?drift=1"
    elif drift_field == "receipt_url":
        tombstone["transport_receipt"]["official_url"] += "?drift=1"
    else:
        digest = "0" * 64
        tombstone["content_sha256"] = digest
        tombstone["transport_receipt"]["content_sha256"] = digest

    with pytest.raises(RuntimeError, match="exact retained official evidence"):
        scraper._overlay_connecticut_supplement(
            base_rows,
            [],
            tombstones=[tombstone],
        )


@pytest.mark.parametrize("failure", ["missing", "wrong_source"])
def test_connecticut_grouped_supplement_tombstone_requires_exact_base(
    failure: str,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._last_connecticut_full_frontier = {
        "base_frontier_closed": True,
        "supplement_frontier_closed": True,
    }
    number = "22a-27s_and_22a-27t"
    evidence = scraper._OFFICIAL_SUPPLEMENT_GROUP_TOMBSTONE_EXPANSIONS[number]
    base_rows = [
        _overlay_row(str(section), str(evidence["base_chapter_url"]))
        for section in evidence["sections"]
    ]
    if failure == "missing":
        base_rows.pop()
    else:
        base_rows[-1].source_url = (
            "https://www.cga.ct.gov/current/pub/chap_wrong.htm#sec_22a-27t"
        )

    with pytest.raises(RuntimeError, match="exact closed base sections"):
        scraper._overlay_connecticut_supplement(
            base_rows,
            [],
            tombstones=[_group_tombstone(scraper, number)],
        )


def test_connecticut_exact_stale_anchor_preserves_both_active_compacts() -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    true_url = "https://www.cga.ct.gov/current/pub/chap_319a.htm"
    stale_url = "https://www.cga.ct.gov/current/pub/chap_319i.htm"

    true_record = _record(true_url, _TRUE_17A_175)
    stale_record = _record(stale_url, _STALE_ANCHOR_17A_615)
    true_rows = scraper._parse_connecticut_chapter_payload(
        _TRUE_17A_175,
        code_name="Connecticut General Statutes",
        chapter_url=true_url,
        citation_format="Conn. Gen. Stat.",
        provenance=true_record,
    )
    corrected_rows = scraper._parse_connecticut_chapter_payload(
        _STALE_ANCHOR_17A_615,
        code_name="Connecticut General Statutes",
        chapter_url=stale_url,
        citation_format="Conn. Gen. Stat.",
        provenance=stale_record,
    )

    assert [row.section_number for row in true_rows] == ["17a-175"]
    assert [row.section_number for row in corrected_rows] == ["17a-615"]
    assert corrected_rows[0].source_url == f"{stale_url}#sec_17a-175"
    assert "Interstate Compact on Mental Health" in corrected_rows[0].full_text
    assert connecticut_section_frontier(
        _STALE_ANCHOR_17A_615.decode(),
        chapter_url=stale_url,
    ) == [
        {
            "anchor_id": "sec_17a-175",
            "disposition": "active",
            "section_number": "17a-615",
        }
    ]
    assert {row.section_number for row in true_rows + corrected_rows} == {
        "17a-175",
        "17a-615",
    }


@pytest.mark.anyio
async def test_connecticut_strict_crawl_closes_stale_anchor_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    scraper._last_connecticut_full_frontier = {
        "closed": False,
        "catalog_units_discovered": 83,
    }
    true_url = "https://www.cga.ct.gov/current/pub/chap_319a.htm"
    stale_url = "https://www.cga.ct.gov/current/pub/chap_319i.htm"

    async def _discover(*args: Any, **kwargs: Any) -> list[str]:
        return [true_url, stale_url]

    async def _frontier(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            _record(true_url, _TRUE_17A_175),
            _record(stale_url, _STALE_ANCHOR_17A_615),
        ]

    monkeypatch.setattr(scraper, "_discover_chapter_urls", _discover)
    monkeypatch.setattr(scraper, "_fetch_connecticut_frontier_pages", _frontier)
    monkeypatch.setattr(
        scraper,
        "_write_partial_checkpoint",
        lambda *args, **kwargs: None,
    )

    rows = await scraper._custom_scrape_connecticut(
        "Connecticut General Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        "Conn. Gen. Stat.",
        max_sections=1_000_000,
    )

    assert [row.section_number for row in rows] == ["17a-175", "17a-615"]
    assert scraper._last_connecticut_full_frontier["base_frontier_closed"] is True


@pytest.mark.parametrize(
    ("old", "new", "chapter_url"),
    [
        (
            b"Interstate Compact on Mental Health.",
            b"Interstate Compact for Mental Health.",
            "https://www.cga.ct.gov/current/pub/chap_319i.htm",
        ),
        (
            b"is hereby enacted into law",
            b"is hereby repealed",
            "https://www.cga.ct.gov/current/pub/chap_319i.htm",
        ),
        (
            b"sec_17a-175",
            b"sec_17a-176",
            "https://www.cga.ct.gov/current/pub/chap_319i.htm",
        ),
        (
            b"17a-615",
            b"17a-616",
            "https://www.cga.ct.gov/current/pub/chap_319i.htm",
        ),
        (
            b"The Interstate Compact\n  on Mental Health is hereby enacted "
            b"into law and entered into by this state\n  with all other states "
            b"legally joining therein in the form substantially as\n  follows:",
            b"Repealed.",
            "https://www.cga.ct.gov/current/pub/chap_319i.htm",
        ),
        (
            b"Interstate Compact on Mental Health.",
            b"Interstate Compact on Mental Health.",
            "https://www.cga.ct.gov/current/pub/chap_319a.htm",
        ),
    ],
)
def test_connecticut_stale_anchor_reconciliation_rejects_any_drift(
    old: bytes,
    new: bytes,
    chapter_url: str,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    payload = _STALE_ANCHOR_17A_615.replace(old, new, 1)
    record = _record(chapter_url, payload)

    with pytest.raises(ValueError, match="anchor/catchline identity conflict"):
        scraper._parse_connecticut_chapter_payload(
            payload,
            code_name="Connecticut General Statutes",
            chapter_url=chapter_url,
            citation_format="Conn. Gen. Stat.",
            provenance=record,
        )


@pytest.mark.parametrize(
    "body",
    [
        "This grouped heading contains currently operative provisions.",
        "Reserved funds are appropriated for future use.",
        "Transferred property remains governed by this section.",
        "The obsolete-equipment program remains effective.",
    ],
)
def test_connecticut_grouped_active_text_is_not_an_inactive_frontier(
    body: str,
) -> None:
    html = f"""
    <p><span class="catchln" id="secs_1-1_to_1-2">
      Secs. 1-1 to 1-2. Current provisions.
    </span> {body}</p>
    """

    assert connecticut_section_frontier(html) == []


def test_connecticut_official_catalog_never_synthesizes_missing_index() -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")

    assert scraper.official_title_catalog() == []
    with pytest.raises(RuntimeError, match="catalog enumeration did not close"):
        scraper._assert_connecticut_title_catalog_closed(
            scraper.enumerate_official_title_catalog(
                b"<a href='title_01.htm'>Title 1</a>",
                page_url=scraper.OFFICIAL_ENTRY_URL,
            )
        )


def test_connecticut_fetch_official_requires_exact_live_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    monkeypatch.setattr(
        scraper,
        "_official_http_get",
        lambda url, timeout_seconds=12: (
            _official_supplement_index_html(scraper)
            if url == scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL
            else _official_index_html(scraper)
        ),
    )

    fetched = scraper.fetch_official("CT")

    assert len(fetched.rows) == 83
    assert fetched.frontier["linkless_reserved_units"] == ["2a", "2b"]
    assert fetched.frontier["supplement_index_units"] == 59
    assert fetched.frontier["currentness_closed"] is True
    assert fetched.frontier["current_as_of"] == "2026-01-01"
    assert fetched.rows[0]["supplement_source_url"].startswith(
        "https://www.cga.ct.gov/2026/sup/"
    )

    monkeypatch.setattr(scraper, "_official_http_get", lambda *args, **kwargs: b"")
    with pytest.raises(RuntimeError, match="index was unavailable"):
        scraper.fetch_official("CT")


@pytest.mark.anyio
async def test_connecticut_frontier_pages_use_shared_batched_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    urls = [
        "https://www.cga.ct.gov/current/pub/title_01.htm",
        "https://www.cga.ct.gov/current/pub/title_02.htm",
        "https://www.cga.ct.gov/current/pub/title_02c.htm",
    ]
    calls: list[list[str]] = []
    call_options: list[dict[str, Any]] = []

    async def _batch(
        requested: Sequence[str],
        **kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        chunk = list(requested)
        calls.append(chunk)
        call_options.append(dict(kwargs))
        payloads = [f"official:{url}".encode() for url in chunk]
        receipts = [_record(url, payload)["transport_receipt"] for url, payload in zip(chunk, payloads)]
        return StateLawPageMultiFetchResult(
            urls=chunk,
            payloads=payloads,
            errors=[None] * len(chunk),
            transport_receipts=receipts,
            parser_input_envelopes=[object()] * len(chunk),
            stats={"range_fetches_avoided": 2},
        )

    monkeypatch.setenv("STATE_SCRAPER_CT_BATCH_SIZE", "2")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _batch,
    )

    records = await scraper._fetch_connecticut_frontier_pages(
        urls,
        purpose="titles",
    )

    assert calls == [urls[:2], urls[2:]]
    assert all(options["prefer_direct"] is True for options in call_options)
    assert [record["url"] for record in records] == urls
    assert all(scraper._connecticut_record_provenance(record, required=True) for record in records)
    assert scraper._last_connecticut_batch_stats["titles"]["batch_count"] == 2


@pytest.mark.anyio
async def test_connecticut_strict_catalog_roots_use_one_base_plural_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    requested_roots = [
        scraper.OFFICIAL_ENTRY_URL,
        scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL,
    ]
    payload_by_url = {
        scraper.OFFICIAL_ENTRY_URL: _official_index_html(scraper),
        scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL: (
            _official_supplement_index_html(scraper)
        ),
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(
        urls: Sequence[str],
        **kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        payloads = [payload_by_url[url] for url in requested]
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=[
                _record(url, payload)["transport_receipt"]
                for url, payload in zip(requested, payloads, strict=True)
            ],
            parser_input_envelopes=[object()] * len(requested),
            stats={"requested_pages": len(requested)},
        )

    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError("strict Connecticut roots must not use singleton fetch")

    monkeypatch.setenv("STATE_SCRAPER_CT_BATCH_SIZE", "1")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_fetch_connecticut_page", _forbid_singleton)

    base = await scraper._connecticut_catalog_root_record(
        scraper.OFFICIAL_ENTRY_URL
    )
    supplement = await scraper._connecticut_catalog_root_record(
        scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL
    )

    assert bytes(base["payload"]) == payload_by_url[scraper.OFFICIAL_ENTRY_URL]
    assert bytes(supplement["payload"]) == payload_by_url[
        scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL
    ]
    assert calls == [
        (
            requested_roots,
            {
                "timeout_seconds": 35,
                "media_type": "text/html",
                "max_concurrency": 2,
                "prefer_direct": True,
                "common_crawl_domain_terms": [scraper.OFFICIAL_DOMAIN],
                "common_crawl_mime_terms": ["html"],
            },
        )
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("malformation", "expected"),
    [
        ("short", "unaligned acquisition rows"),
        ("reordered", "changed URL order or identity"),
        ("miss", "catalog-root frontier is incomplete"),
    ],
)
async def test_connecticut_strict_catalog_root_batch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
    expected: str,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    roots = [
        scraper.OFFICIAL_ENTRY_URL,
        scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL,
    ]
    payloads = [
        _official_index_html(scraper),
        _official_supplement_index_html(scraper),
    ]

    async def _malformed(
        urls: Sequence[str],
        **_kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        result = StateLawPageMultiFetchResult(
            urls=requested,
            payloads=list(payloads),
            errors=[None, None],
            transport_receipts=[
                _record(url, payload)["transport_receipt"]
                for url, payload in zip(requested, payloads, strict=True)
            ],
            parser_input_envelopes=[object(), object()],
            stats={},
        )
        if malformation == "short":
            result.parser_input_envelopes = [object()]
        elif malformation == "reordered":
            result.urls = list(reversed(requested))
        else:
            result.payloads[1] = b""
            result.errors[1] = "archive miss"
        return result

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _malformed,
    )

    with pytest.raises(RuntimeError, match=expected):
        await scraper._connecticut_catalog_root_record(roots[0])


@pytest.mark.anyio
async def test_connecticut_strict_title_discovery_fetches_and_excludes_exact_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    index = _official_index_html(scraper)
    requested_title_urls: list[str] = []
    root_batches: list[list[str]] = []

    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError("strict Connecticut roots must be plural")

    async def _frontier(
        urls: Sequence[str],
        *,
        purpose: str,
        timeout_seconds: int = 35,
    ) -> list[dict[str, Any]]:
        if purpose == "catalog_roots":
            root_batches.append(list(urls))
            return [
                _record(scraper.OFFICIAL_ENTRY_URL, index),
                _record(
                    scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL,
                    _official_supplement_index_html(scraper),
                ),
            ]
        assert purpose == "titles"
        requested_title_urls.extend(urls)
        records: list[dict[str, Any]] = []
        inactive = set(scraper.OFFICIAL_INACTIVE_TITLE_NUMBERS)
        for position, url in enumerate(urls, start=1):
            match = scraper._TITLE_NUMBER_RE.search(url)
            assert match is not None
            token = match.group(1).lstrip("0") or "0"
            payload = (
                b"<html><body>inactive title</body></html>"
                if token in inactive
                else (
                    "<html><body><a class='toc_ch_link' "
                    f"href='chap_x{position:03d}.htm'>Chapter X{position}</a>"
                    "</body></html>"
                ).encode()
            )
            records.append(_record(url, payload))
        return records

    monkeypatch.setattr(scraper, "_fetch_connecticut_page", _forbid_singleton)
    monkeypatch.setattr(scraper, "_fetch_connecticut_frontier_pages", _frontier)

    chapters = await scraper._discover_chapter_urls(
        scraper.OFFICIAL_ENTRY_URL,
        limit=1_000_000,
    )

    assert len(requested_title_urls) == 81
    assert root_batches == [[
        scraper.OFFICIAL_ENTRY_URL,
        scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL,
    ]]
    assert len(chapters) == 72
    frontier = scraper._last_connecticut_full_frontier
    assert frontier["catalog_units_discovered"] == 83
    assert frontier["active_title_units"] == 72
    assert frontier["inactive_title_units"] == 9
    assert frontier["title_units_excluded"] == 11
    assert frontier["title_pages_requested"] == 81
    assert frontier["title_pages_fetched"] == 81
    assert frontier["title_pages_excluded"] == 9
    assert frontier["title_pages_failed"] == []


@pytest.mark.anyio
async def test_connecticut_strict_catalog_rejects_originless_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    index = _official_index_html(scraper)

    async def _frontier(
        urls: Sequence[str],
        *,
        purpose: str,
        timeout_seconds: int = 35,
    ) -> list[dict[str, Any]]:
        assert purpose == "catalog_roots"
        del timeout_seconds
        return [
            {
                "url": url,
                "payload": (
                    index
                    if url == scraper.OFFICIAL_ENTRY_URL
                    else _official_supplement_index_html(scraper)
                ),
                "error": "",
                "content_sha256": "",
                "transport_receipt": {},
            }
            for url in urls
        ]

    monkeypatch.setattr(scraper, "_fetch_connecticut_frontier_pages", _frontier)

    with pytest.raises(RuntimeError, match="exact transport binding"):
        await scraper._discover_chapter_urls(
            scraper.OFFICIAL_ENTRY_URL,
            limit=1_000_000,
        )


@pytest.mark.anyio
async def test_connecticut_strict_chapters_close_parser_and_provenance_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    scraper._last_connecticut_full_frontier = {
        "closed": False,
        "catalog_units_discovered": 83,
    }
    active_url = "https://www.cga.ct.gov/current/pub/chap_001.htm"
    inactive_url = "https://www.cga.ct.gov/current/pub/chap_002.htm"
    batch_calls: list[tuple[str, list[str]]] = []

    async def _discover(
        code_url: str,
        limit: int = 120,
        *,
        catalog_kind: str = "base",
    ) -> list[str]:
        assert catalog_kind == "base"
        return [active_url, inactive_url]

    async def _frontier(
        urls: Sequence[str],
        *,
        purpose: str,
        timeout_seconds: int = 35,
    ) -> list[dict[str, Any]]:
        batch_calls.append((purpose, list(urls)))
        return [
            _record(active_url, _active_chapter_html()),
            _record(inactive_url, _inactive_chapter_html()),
        ]

    async def _sequential(*args: Any, **kwargs: Any) -> list[Any]:
        raise AssertionError("strict Connecticut chapters must use the shared batch")

    monkeypatch.setattr(scraper, "_discover_chapter_urls", _discover)
    monkeypatch.setattr(scraper, "_fetch_connecticut_frontier_pages", _frontier)
    monkeypatch.setattr(scraper, "_extract_chapter_sections", _sequential)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *args, **kwargs: None)

    rows = await scraper._custom_scrape_connecticut(
        "Connecticut General Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        "Conn. Gen. Stat.",
        max_sections=1_000_000,
    )

    assert batch_calls == [("chapters", [active_url, inactive_url])]
    assert [row.section_number for row in rows] == ["1-1"]
    assert len(rows[0].structured_data["content_sha256"]) == 64
    assert rows[0].structured_data["transport_receipt"]["official_url"] == active_url
    frontier = scraper._last_connecticut_full_frontier
    assert frontier["chapter_pages_discovered"] in (None, 2)
    assert frontier["chapter_pages_requested"] == 2
    assert frontier["chapter_pages_fetched"] == 2
    assert frontier["chapter_pages_excluded"] == 1
    assert frontier["chapter_pages_failed"] == []
    assert frontier["active_sections_discovered"] == 1
    assert frontier["inactive_sections_excluded"] == 1
    assert frontier["sections_emitted"] == 1
    assert frontier["base_frontier_closed"] is True
    assert frontier["closed"] is False
    assert frontier["currentness_closed"] is False


@pytest.mark.anyio
async def test_connecticut_strict_scrape_replays_exact_runtime_batch_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    index = _official_index_html(scraper)
    supplement_index = _official_supplement_index_html(scraper)
    runtime_batches: list[tuple[str, int]] = []
    chapter_payloads: dict[str, bytes] = {}

    async def _frontier(
        urls: Sequence[str],
        *,
        purpose: str,
        timeout_seconds: int = 35,
    ) -> list[dict[str, Any]]:
        runtime_batches.append((purpose, len(urls)))
        if purpose == "catalog_roots":
            return [
                _record(scraper.OFFICIAL_ENTRY_URL, index),
                _record(scraper.OFFICIAL_SUPPLEMENT_ENTRY_URL, supplement_index),
            ]
        if purpose == "titles":
            records: list[dict[str, Any]] = []
            inactive = set(scraper.OFFICIAL_INACTIVE_TITLE_NUMBERS)
            for position, url in enumerate(urls, start=1):
                match = scraper._TITLE_NUMBER_RE.search(url)
                assert match is not None
                token = match.group(1).lstrip("0") or "0"
                if token in inactive:
                    payload = b"<html><body>inactive title</body></html>"
                else:
                    chapter_url = (
                        "https://www.cga.ct.gov/current/pub/"
                        f"chap_x{position:03d}.htm"
                    )
                    payload = (
                        "<html><body><a class='toc_ch_link' "
                        f"href='{chapter_url.rsplit('/', 1)[-1]}'>"
                        f"Chapter X{position}</a></body></html>"
                    ).encode()
                    chapter_payloads[chapter_url] = _active_chapter_html(
                        f"x{position:03d}-1"
                    )
                records.append(_record(url, payload))
            return records
        if purpose == "supplement_titles":
            records = []
            for position, url in enumerate(urls, start=1):
                chapter_url = (
                    "https://www.cga.ct.gov/2026/sup/"
                    f"chap_s{position:03d}.htm"
                )
                payload = (
                    "<html><body><a class='toc_ch_link' "
                    f"href='{chapter_url.rsplit('/', 1)[-1]}'>"
                    f"Supplement Chapter S{position}</a></body></html>"
                ).encode()
                if position == 1:
                    chapter_payloads[chapter_url] = _active_chapter_html("x001-1")
                elif position == 2:
                    chapter_payloads[chapter_url] = _inactive_chapter_html("x002-1")
                else:
                    chapter_payloads[chapter_url] = _active_chapter_html(
                        f"s{position:03d}-1"
                    )
                records.append(_record(url, payload))
            return records
        assert purpose in {"chapters", "supplement_chapters"}
        return [_record(url, chapter_payloads[url]) for url in urls]

    for variable in (
        "CONNECTICUT_CHAPTER_HTML",
        "CONNECTICUT_CONSTITUTION_HTML",
        "CONNECTICUT_TITLES_HTML",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError("strict Connecticut roots must be plural")

    monkeypatch.setattr(scraper, "_fetch_connecticut_page", _forbid_singleton)
    monkeypatch.setattr(scraper, "_fetch_connecticut_frontier_pages", _frontier)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *args, **kwargs: None)

    rows = await scraper.scrape_code(
        "Connecticut General Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert runtime_batches == [
        ("catalog_roots", 2),
        ("titles", 81),
        ("chapters", 72),
        ("supplement_titles", 59),
        ("supplement_chapters", 59),
    ]
    assert len(rows) == 128
    assert len({row.section_number for row in rows}) == 128
    assert "x002-1" not in {row.section_number for row in rows}
    replacement = next(row for row in rows if row.section_number == "x001-1")
    assert replacement.structured_data["connecticut_overlay_action"] == (
        "supplement_replacement"
    )
    assert replacement.source_url.startswith("https://www.cga.ct.gov/2026/sup/")
    assert all(len(row.structured_data["content_sha256"]) == 64 for row in rows)
    frontier = scraper._last_connecticut_full_frontier
    assert frontier["catalog_units_discovered"] == 83
    assert frontier["title_pages_fetched"] == 81
    assert frontier["chapter_pages_fetched"] == 72
    assert frontier["base_active_sections_discovered"] == 72
    assert frontier["base_sections_emitted"] == 72
    assert frontier["supplement_catalog_units_discovered"] == 59
    assert frontier["supplement_title_pages_fetched"] == 59
    assert frontier["supplement_chapter_pages_fetched"] == 59
    assert frontier["supplement_active_sections_discovered"] == 58
    assert frontier["supplement_tombstones_applied"] == 1
    assert frontier["supplement_replacements_applied"] == 1
    assert frontier["supplement_additions_applied"] == 57
    assert frontier["combined_sections_emitted"] == 128
    assert frontier["sections_emitted"] == 128
    assert frontier["active_sections_discovered"] == 128
    assert frontier["current_as_of"] == "2026-01-01"
    assert frontier["currentness_closed"] is True
    assert frontier["closed"] is True


def test_connecticut_strict_parser_rejects_originless_bytes() -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True

    with pytest.raises(RuntimeError, match="exact transport binding"):
        scraper._parse_connecticut_chapter_payload(
            _active_chapter_html(),
            code_name="Connecticut General Statutes",
            chapter_url="https://www.cga.ct.gov/current/pub/chap_001.htm",
            citation_format="Conn. Gen. Stat.",
            provenance={},
        )


def test_connecticut_strict_parser_fails_on_active_section_without_body() -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    url = "https://www.cga.ct.gov/current/pub/chap_003.htm"
    payload = (
        "<p class='toc_catchln'><a href='#sec_3-1'>Sec. 3-1. Empty.</a></p>"
        "<p><span class='catchln' id='sec_3-1'>Sec. 3-1. Empty.</span></p>"
    ).encode()
    provenance = _record(url, payload)

    with pytest.raises(RuntimeError, match="identity diverged"):
        scraper._parse_connecticut_chapter_payload(
            payload,
            code_name="Connecticut General Statutes",
            chapter_url=url,
            citation_format="Conn. Gen. Stat.",
            provenance={
                "content_sha256": provenance["content_sha256"],
                "transport_receipt": provenance["transport_receipt"],
            },
        )


def test_connecticut_mixed_frontier_keeps_linkless_repeal_tombstone() -> None:
    html = (
        _active_chapter_html("1-1").decode().replace(
            "</body>",
            "<p class='toc_catchln'><b>Sec. 1-2. Repealed.</b></p></body>",
        )
    )

    frontier = connecticut_section_frontier(html)

    assert frontier == [
        {
            "anchor_id": "sec_1-1",
            "disposition": "active",
            "section_number": "1-1",
        },
        {
            "anchor_id": "sec_1-2",
            "disposition": "inactive",
            "section_number": "1-2",
        },
    ]


def test_connecticut_strict_parser_rejects_empty_chapter_frontier() -> None:
    scraper = ConnecticutScraper("CT", "Connecticut")
    scraper._connecticut_strict_full_run = True
    url = "https://www.cga.ct.gov/2026/sup/chap_999.htm"
    payload = b"<html><body><h1>Chapter 999</h1></body></html>"
    provenance = _record(url, payload)

    with pytest.raises(RuntimeError, match="exposed no section frontier"):
        scraper._parse_connecticut_chapter_payload(
            payload,
            code_name="Connecticut General Statutes",
            chapter_url=url,
            citation_format="Conn. Gen. Stat.",
            provenance={
                "content_sha256": provenance["content_sha256"],
                "transport_receipt": provenance["transport_receipt"],
            },
        )
