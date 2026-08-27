"""Strict Illinois chapter/act/FullText frontier regressions."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.illinois import (
    IllinoisScraper,
)


CHAPTERS = [
    {
        "url": (
            "https://www.ilga.gov/Legislation/ILCS/Acts?ChapterID=2&"
            "ChapterNumber=5&Chapter=GENERAL%20PROVISIONS&MajorTopic=GOVERNMENT"
        ),
        "label": "CHAPTER 5 GENERAL PROVISIONS",
        "chapter_id": "2",
        "chapter_number": "5",
        "chapter_name": "GENERAL PROVISIONS",
        "major_topic": "GOVERNMENT",
    },
    {
        "url": (
            "https://www.ilga.gov/Legislation/ILCS/Acts?ChapterID=3&"
            "ChapterNumber=10&Chapter=ELECTIONS&MajorTopic=GOVERNMENT"
        ),
        "label": "CHAPTER 10 ELECTIONS",
        "chapter_id": "3",
        "chapter_number": "10",
        "chapter_name": "ELECTIONS",
        "major_topic": "GOVERNMENT",
    },
]


def _article_url(act_id: str, chapter_id: str) -> str:
    return (
        "https://www.ilga.gov/Legislation/ILCS/Articles?"
        f"ActID={act_id}&ChapterID={chapter_id}"
    )


def _full_url(act_id: str, chapter_id: str) -> str:
    return (
        "https://www.ilga.gov/legislation/ILCS/details?"
        f"ActID={act_id}&ChapterID={chapter_id}&SeqStart=&ChapAct=FullText"
    )


def _chapter_html(*rows: tuple[str, str, str]) -> bytes:
    anchors = "".join(
        f'<a href="{_article_url(act_id, chapter_id)}">{label}</a>'
        for act_id, chapter_id, label in rows
    )
    return f"<html><body><main>{anchors}</main></body></html>".encode()


def _act_html(*sections: tuple[str, str]) -> bytes:
    body = "".join(
        '<div align="justify">'
        f"<code>({cite})</code><p>Sec. {cite.rsplit('/', 1)[-1]}. {text}</p>"
        "</div>"
        for cite, text in sections
    )
    return f"<html><body><main>{body}</main></body></html>".encode()


def _public_act_html(
    *,
    public_act_number: str,
    bill_number: str,
    act_name: str,
    effective_date: str,
    sections: tuple[str, ...],
) -> bytes:
    section_nodes: list[str] = []
    for section in sections:
        section_nodes.extend(
            [
                f"<code>Section {section}.</code>",
                (
                    "<code>Short title.</code>"
                    if section == sections[0]
                    else f"<code>Provision {section}.</code>"
                ),
                (
                    f"<code>This Act may be cited as the {act_name}</code>"
                    if section == sections[0]
                    else f"<code>Official operative text for Section {section}.</code>"
                ),
            ]
        )
    year, month, day = effective_date.split("-")
    return (
        "<html><body><div id=\"billtextanchor\">"
        f"<p>Public Act {public_act_number}</p>"
        f"<p>{bill_number} Enrolled</p>"
        f"{''.join(section_nodes)}"
        "</div>"
        f"<div><span>Effective Date:</span> {int(month)}/{int(day)}/{year}</div>"
        "</body></html>"
    ).encode()


def _receipt(url: str, payload: bytes) -> dict[str, str]:
    return {
        "official_url": url,
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "source_transport": "direct",
    }


def _batch(
    requested: list[str],
    payload_by_url: dict[str, bytes],
    *,
    urls: list[str] | None = None,
    missing_at: int | None = None,
) -> StateLawPageMultiFetchResult:
    payloads = [payload_by_url[url] for url in requested]
    errors: list[str | None] = [None] * len(requested)
    receipts: list[dict[str, str] | None] = [
        _receipt(url, payload) for url, payload in zip(requested, payloads)
    ]
    if missing_at is not None:
        payloads[missing_at] = b""
        errors[missing_at] = "retained/direct/archive miss"
        receipts[missing_at] = None
    return StateLawPageMultiFetchResult(
        urls=list(requested if urls is None else urls),
        payloads=payloads,
        errors=errors,
        transport_receipts=receipts,
        parser_input_envelopes=[None] * len(requested),
        stats={
            "common_crawl_inventory_queries": 1,
            "direct_initial_successes": len(requested),
            "common_crawl": {
                "naive_range_fetches": 7,
                "range_fetch_calls": 3,
                "range_fetches_avoided": 4,
            },
        },
    )


def _disable_checkpoints(scraper: IllinoisScraper) -> None:
    scraper._write_partial_checkpoint = lambda *_args, **_kwargs: False


@pytest.mark.anyio
async def test_strict_illinois_batches_exact_frontier_in_canonical_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chapter_payloads = {
        CHAPTERS[0]["url"]: _chapter_html(
            ("101", "2", "5 ILCS 10/ First Act."),
            ("102", "2", "5 ILCS 20/ Second Act."),
        ),
        CHAPTERS[1]["url"]: _chapter_html(
            ("201", "3", "10 ILCS 30/ (Repealed by P.A. 90-1.)"),
        ),
    }
    full_payloads = {
        _full_url("101", "2"): _act_html(
            (
                "5 ILCS 10/1",
                "First owned provision has complete official legal text and "
                "references (5 ILCS 20/1) without inventing another row.",
            ),
            ("5 ILCS 10/2", "Second owned provision has official legal text."),
        ),
        _full_url("102", "2"): _act_html(
            ("5 ILCS 20/1", "Third provision has official legal text."),
        ),
        _full_url("201", "3"): b"<html><body>Official repealed Act.</body></html>",
    }
    payloads = {**chapter_payloads, **full_payloads}
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _discover(_code_url: str) -> list[dict[str, str]]:
        return [dict(chapter) for chapter in CHAPTERS]

    async def _plural(urls, **kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        return _batch(requested, payloads)

    scraper = IllinoisScraper("IL", "Illinois")
    _disable_checkpoints(scraper)
    monkeypatch.setenv("STATE_SCRAPER_IL_FULL_ACT_BATCH_SIZE", "2")
    monkeypatch.setenv("STATE_SCRAPER_IL_FULL_ACT_CONCURRENCY", "7")
    monkeypatch.setattr(scraper, "_discover_chapter_links", _discover)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    statutes = await scraper._scrape_strict_full_code(
        code_name="Illinois Compiled Statutes",
        code_url=scraper.OFFICIAL_ENTRY_URL,
    )

    expected_full_urls = list(full_payloads)
    assert [requested for requested, _kwargs in calls] == [
        [chapter["url"] for chapter in CHAPTERS],
        expected_full_urls[:2],
        expected_full_urls[2:],
    ]
    assert all(
        kwargs["prefer_direct"] is True
        and kwargs["common_crawl_domain_terms"] == ["www.ilga.gov"]
        and kwargs["common_crawl_mime_terms"] == ["html"]
        for _requested, kwargs in calls
    )
    assert [row.official_cite for row in statutes] == [
        "5 ILCS 10/1",
        "5 ILCS 10/2",
        "5 ILCS 20/1",
    ]
    assert "5 ILCS 20/1" in statutes[0].full_text
    assert len({row.statute_id for row in statutes}) == len(statutes)
    assert all(
        row.structured_data["transport_receipt"]["official_url"]
        == row.source_url
        for row in statutes
    )
    frontier = scraper._last_illinois_full_frontier
    assert frontier["closed"] is True
    assert frontier["chapters_discovered"] == 2
    assert frontier["acts_discovered"] == 3
    assert frontier["article_page_requests_avoided"] == 3
    assert frontier["statute_bearing_acts"] == 2
    assert frontier["terminal_acts_excluded"] == 1
    assert frontier["terminal_dispositions"][0]["disposition"] == "repealed"
    assert frontier["warc_naive_range_fetches"] == 21
    assert frontier["warc_range_fetch_calls"] == 9
    assert frontier["warc_range_fetches_avoided"] == 12


@pytest.mark.anyio
async def test_pending_ilcs_public_acts_share_one_aligned_plural_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chapter = dict(CHAPTERS[0])
    acts = (
        ("101", "5 ILCS 10/ First Pending Act."),
        ("102", "5 ILCS 20/ Second Pending Act."),
    )
    public_act_urls = [
        "https://www.ilga.gov/Legislation/PublicActs/View/104-0101",
        "https://www.ilga.gov/Legislation/PublicActs/View/104-0102",
    ]
    public_act_document_url = (
        "https://www.ilga.gov/documents/legislation/PublicActs/104/"
        "104-0102.htm"
    )
    payloads = {
        chapter["url"]: _chapter_html(
            *[(act_id, "2", label) for act_id, label in acts]
        ),
        _full_url("101", "2"): (
            b"<html><body>Official empty pending ILCS shell one.</body></html>"
        ),
        _full_url("102", "2"): (
            b"<html><body>Official empty pending ILCS shell two.</body></html>"
        ),
        public_act_urls[0]: _public_act_html(
            public_act_number="104-0101",
            bill_number="HB1001",
            act_name="First Pending Act.",
            effective_date="2027-01-01",
            sections=("1",),
        ),
        public_act_urls[1]: (
            "<html><body><h1>Public Act 104-0102</h1>"
            '<div id="billtextanchor">The full text is too large. '
            '<a href="/documents/legislation/PublicActs/104/104-0102.htm">'
            "click here</a></div><div>Effective Date: 2/1/2027</div>"
            "</body></html>"
        ).encode(),
        public_act_document_url: (
            "<html><body><p>Public Act 104-0102</p>"
            "<p>SB1002 Enrolled</p><table><tr><td>"
            "<code>&#160;&#160;&#160;&#160;</code><code>Section 5.</code>"
            "<code>Short title.</code>"
            "<code>This Act may be cited as the Second Pending Act.</code>"
            "</td></tr></table></body></html>"
        ).encode(),
    }
    mappings = {
        ("2", "101"): {
            "chapter_number": "5",
            "chap_act": "5 ILCS 10/",
            "act_name": "First Pending Act.",
            "public_act_number": "104-0101",
            "bill_number": "HB1001",
            "effective_date": "2027-01-01",
            "section_numbers": ("1",),
            "public_act_section_numbers": ("1",),
            "url": public_act_urls[0],
        },
        ("2", "102"): {
            "chapter_number": "5",
            "chap_act": "5 ILCS 20/",
            "act_name": "Second Pending Act.",
            "public_act_number": "104-0102",
            "bill_number": "SB1002",
            "effective_date": "2027-02-01",
            "section_numbers": ("5",),
            "public_act_section_numbers": ("5",),
            "url": public_act_urls[1],
            "document_url": public_act_document_url,
        },
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _discover(_code_url: str) -> list[dict[str, str]]:
        return [chapter]

    async def _plural(urls, **kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        return _batch(requested, payloads)

    scraper = IllinoisScraper("IL", "Illinois")
    _disable_checkpoints(scraper)
    monkeypatch.setenv("STATE_SCRAPER_IL_FULL_ACT_BATCH_SIZE", "2")
    monkeypatch.setattr(scraper, "_PENDING_ILCS_PUBLIC_ACTS", mappings)
    monkeypatch.setattr(scraper, "_discover_chapter_links", _discover)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    statutes = await scraper._scrape_strict_full_code(
        code_name="Illinois Compiled Statutes",
        code_url=scraper.OFFICIAL_ENTRY_URL,
    )

    assert [requested for requested, _kwargs in calls] == [
        [chapter["url"]],
        [_full_url("101", "2"), _full_url("102", "2")],
        [*public_act_urls, public_act_document_url],
    ]
    assert calls[-1][1]["prefer_direct"] is True
    assert calls[-1][1]["common_crawl_domain_terms"] == ["www.ilga.gov"]
    assert [row.official_cite for row in statutes] == [
        "5 ILCS 10/1",
        "5 ILCS 20/5",
    ]
    assert [row.structured_data["act_frontier_index"] for row in statutes] == [
        1,
        2,
    ]
    assert all(
        row.structured_data["transport_receipt"]["official_url"]
        == row.source_url
        and row.structured_data["ilcs_fulltext_transport_receipt"][
            "official_url"
        ]
        == _full_url(str(100 + position), "2")
        for position, row in enumerate(statutes, start=1)
    )
    assert statutes[1].structured_data[
        "public_act_landing_transport_receipt"
    ]["official_url"] == public_act_urls[1]
    frontier = scraper._last_illinois_full_frontier
    assert frontier["closed"] is True
    assert frontier["full_act_pages_classified"] == 2
    assert frontier["pending_public_act_pages_requested"] == 3
    assert frontier["pending_public_act_pages_fetched"] == 3
    assert frontier["pending_public_act_pages_classified"] == 2
    assert frontier["statute_bearing_acts"] == 2
    assert frontier["terminal_acts_excluded"] == 0


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["reordered", "missing"])
async def test_illinois_aligned_batch_fails_closed_on_order_or_miss(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    urls = [chapter["url"] for chapter in CHAPTERS]
    payloads = {url: b"<html><body>official</body></html>" for url in urls}

    async def _plural(requested_urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        if failure == "reordered":
            return _batch(requested, payloads, urls=list(reversed(requested)))
        return _batch(requested, payloads, missing_at=1)

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    pattern = "URL identity or order" if failure == "reordered" else "page missing"
    with pytest.raises(RuntimeError, match=pattern):
        await scraper._fetch_illinois_page_batch(
            urls,
            purpose="chapter_pages",
            timeout_seconds=5,
            max_concurrency=2,
        )


@pytest.mark.anyio
async def test_strict_illinois_rejects_zero_act_chapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    _disable_checkpoints(scraper)

    async def _discover(_code_url: str) -> list[dict[str, str]]:
        return [dict(CHAPTERS[0])]

    async def _plural(urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return _batch(
            requested,
            {requested[0]: b"<html><body>official navigation only</body></html>"},
        )

    monkeypatch.setattr(scraper, "_discover_chapter_links", _discover)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    with pytest.raises(RuntimeError, match="no admissible act locators"):
        await scraper._scrape_strict_full_code(
            code_name="Illinois Compiled Statutes",
            code_url=scraper.OFFICIAL_ENTRY_URL,
        )
    assert scraper._last_illinois_full_frontier["closed"] is False


@pytest.mark.anyio
async def test_strict_illinois_rejects_untyped_sectionless_act_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    _disable_checkpoints(scraper)
    chapter = dict(CHAPTERS[0])
    chapter_payload = _chapter_html(
        ("101", "2", "5 ILCS 10/ (Repealed pursuant to P.A. 90-1.)"),
    )
    full_url = _full_url("101", "2")
    payloads = {
        chapter["url"]: chapter_payload,
        full_url: b"<html><body>Official sectionless Act.</body></html>",
    }

    async def _discover(_code_url: str) -> list[dict[str, str]]:
        return [chapter]

    async def _plural(urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return _batch(requested, payloads)

    monkeypatch.setattr(scraper, "_discover_chapter_links", _discover)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    with pytest.raises(RuntimeError, match="no owned sections"):
        await scraper._scrape_strict_full_code(
            code_name="Illinois Compiled Statutes",
            code_url=scraper.OFFICIAL_ENTRY_URL,
        )


@pytest.mark.anyio
async def test_strict_illinois_rejects_nonunique_final_section_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    _disable_checkpoints(scraper)
    chapter = dict(CHAPTERS[0])
    payloads = {
        chapter["url"]: _chapter_html(
            ("101", "2", "5 ILCS 10/ First variant."),
            ("102", "2", "5 ILCS 10/ Concurrent variant."),
        ),
        _full_url("101", "2"): _act_html(
            ("5 ILCS 10/1", "First official variant text."),
        ),
        _full_url("102", "2"): _act_html(
            ("5 ILCS 10/1", "Concurrent official variant text."),
        ),
    }

    async def _discover(_code_url: str) -> list[dict[str, str]]:
        return [chapter]

    async def _plural(urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return _batch(requested, payloads)

    monkeypatch.setattr(scraper, "_discover_chapter_links", _discover)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    with pytest.raises(RuntimeError, match="identities are not unique"):
        await scraper._scrape_strict_full_code(
            code_name="Illinois Compiled Statutes",
            code_url=scraper.OFFICIAL_ENTRY_URL,
        )


def test_strict_illinois_rejects_duplicate_act_locators() -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    duplicate = _article_url("101", "2")
    html = (
        f'<a href="{duplicate}">5 ILCS 10/ First Act.</a>'
        f'<a href="{duplicate}">5 ILCS 10/ First Act.</a>'
    )
    with pytest.raises(RuntimeError, match="repeats an act locator"):
        scraper._parse_act_links_html(
            html,
            chapter_url=CHAPTERS[0]["url"],
            strict=True,
        )


def test_illinois_discovery_percent_encodes_official_query_spaces() -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    chapters = scraper._parse_chapter_links_html(
        """
        <a href="/Legislation/ILCS/Acts?ChapterID=5&amp;ChapterNumber=20&amp;Chapter=EXECUTIVE BRANCH&amp;MajorTopic=GOVERNMENT">
          CHAPTER 20 EXECUTIVE BRANCH
        </a>
        """,
        index_url=scraper.OFFICIAL_ENTRY_URL,
    )

    assert chapters == [
        {
            "url": (
                "https://www.ilga.gov/Legislation/ILCS/Acts?ChapterID=5&"
                "ChapterNumber=20&Chapter=EXECUTIVE%20BRANCH&MajorTopic=GOVERNMENT"
            ),
            "label": "CHAPTER 20 EXECUTIVE BRANCH",
            "chapter_id": "5",
            "chapter_number": "20",
            "chapter_name": "EXECUTIVE BRANCH",
            "major_topic": "GOVERNMENT",
        }
    ]


def test_illinois_catalog_alignment_normalizes_raw_official_query_spaces() -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    raw_source_url = CHAPTERS[0]["url"].replace("%20", " ")
    scraper._state_law_first_official_frontier_observation = {
        "fetch": SimpleNamespace(rows=[{"source_url": raw_source_url}])
    }

    assert scraper._validate_discovered_chapters([CHAPTERS[0]]) == [
        CHAPTERS[0]["url"]
    ]


def test_illinois_nonoperative_dispositions_are_exact_and_typed() -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    assert scraper._nonoperative_act_disposition(
        {"act_name": "(Repealed by P.A. 90-1.)"}
    ) == {
        "disposition": "repealed",
        "authority": "P.A. 90-1.",
        "source_label": "(Repealed by P.A. 90-1.)",
    }
    toxin_free_toddler_label = (
        "Toxin-Free Toddler Act. (Repealed by P.A. 97-1101, Sec. 98; see "
        "FDA final rule at 77 Federal Register 41899-41902 (July 17, 2012) "
        "amending 21 CFR 177.1580 to prohibit the use of polycarbonate "
        "resins in infant feeding bottles and spill-proof cups)"
    )
    assert scraper._nonoperative_act_disposition(
        {"act_name": toxin_free_toddler_label}
    ) == {
        "disposition": "repealed",
        "authority": (
            "P.A. 97-1101, Sec. 98; see FDA final rule at 77 Federal "
            "Register 41899-41902 (July 17, 2012) amending 21 CFR "
            "177.1580 to prohibit the use of polycarbonate resins in infant "
            "feeding bottles and spill-proof cups"
        ),
        "source_label": toxin_free_toddler_label,
    }
    moved = scraper._nonoperative_act_disposition(
        {
            "act_name": (
                "(Moved to 50 ILCS 835/; see Section 98 of P.A. 100-1129)"
            )
        }
    )
    assert moved is not None
    assert moved["disposition"] == "moved"
    assert moved["destination"] == "50 ILCS 835/"
    assert moved["authority"] == "Section 98 of P.A. 100-1129"
    moved_without_authority = scraper._nonoperative_act_disposition(
        {
            "act_name": (
                "Domestic Violence Shelters Act. (Moved to 20 ILCS 1310/)"
            )
        }
    )
    assert moved_without_authority == {
        "disposition": "moved",
        "destination": "20 ILCS 1310/",
        "source_label": (
            "Domestic Violence Shelters Act. (Moved to 20 ILCS 1310/)"
        ),
    }
    assert scraper._nonoperative_act_disposition(
        {"act_name": "Repealed pursuant to P.A. 90-1."}
    ) is None
    assert scraper._nonoperative_act_disposition(
        {"act_name": "Moved to 20 ILCS 1310/"}
    ) is None
    assert scraper._nonoperative_act_disposition(
        {"act_name": "(Moved to 20 ILCS 1310/; consult P.A. 90-1)"}
    ) is None
    assert scraper._nonoperative_act_disposition(
        {"act_name": "(Moved to 20 ILCS 1310/) pending"}
    ) is None


@pytest.mark.parametrize(
    "label",
    [
        (
            "Toxin-Free Toddler Act. (Repealed by P.A. 97-1101 "
            "(rule (July 17, 2012)))"
        ),
        (
            "Toxin-Free Toddler Act. (Repealed by P.A. 97-1101 "
            "(July 17, 2012)"
        ),
        (
            "Toxin-Free Toddler Act. (Repealed by P.A. 97-1101 "
            "(July 17, 2012)) pending"
        ),
        "Toxin-Free Toddler Act. Repealed by P.A. 97-1101 (July 17, 2012)",
        "Toxin-Free Toddler Act. (Repealed by () )",
    ],
)
def test_illinois_balanced_repeal_authority_drift_fails_closed(
    label: str,
) -> None:
    assert (
        IllinoisScraper("IL", "Illinois")._nonoperative_act_disposition(
            {"act_name": label}
        )
        is None
    )


@pytest.mark.anyio
async def test_bounded_illinois_keeps_lazy_article_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    chapter = dict(CHAPTERS[0])
    act = {
        "url": _article_url("101", "2"),
        "act_id": "101",
        "chapter_id": "2",
        "chap_act": "5 ILCS 10/",
        "act_name": "First Act.",
    }
    calls: list[str] = []

    async def _chapters(_code_url: str) -> list[dict[str, str]]:
        calls.append("chapters")
        return [chapter]

    async def _acts(_chapter_url: str) -> list[dict[str, str]]:
        calls.append("acts")
        return [act]

    async def _parse(**_kwargs) -> list[NormalizedStatute]:
        calls.append("parse")
        return [
            NormalizedStatute(
                state_code="IL",
                state_name="Illinois",
                statute_id="IL-5-10-1",
                section_number="10/1",
                full_text="Official bounded Illinois text.",
                source_url=_full_url("101", "2"),
                official_cite="5 ILCS 10/1",
            )
        ]

    async def _unexpected_plural(*_args, **_kwargs):
        raise AssertionError("bounded Illinois path must remain lazy")

    monkeypatch.setattr(scraper, "_full_corpus_enabled", lambda: True)
    monkeypatch.setattr(scraper, "_discover_chapter_links", _chapters)
    monkeypatch.setattr(scraper, "_discover_act_links", _acts)
    monkeypatch.setattr(scraper, "_parse_full_act", _parse)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _unexpected_plural,
    )

    rows = await scraper.scrape_code(
        "Illinois Compiled Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=1,
    )
    assert calls == ["chapters", "acts", "parse"]
    assert [row.official_cite for row in rows] == ["5 ILCS 10/1"]


@pytest.mark.anyio
async def test_illinois_single_page_path_enables_archival_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    observed: dict[str, Any] = {}

    async def _fetch(url: str, **kwargs) -> bytes:
        observed["url"] = url
        observed.update(kwargs)
        return b"<html><body>official</body></html>"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _fetch)
    result = await scraper._fetch_official_il_html(scraper.OFFICIAL_ENTRY_URL)
    assert result.startswith("<html>")
    assert observed["allow_archival_fallback"] is True
    assert observed["media_type"] == "text/html"
