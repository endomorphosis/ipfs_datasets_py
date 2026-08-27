"""Kansas breadth-first official hierarchy and archive batching regressions."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kansas import (
    KansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_fetch import (
    ArchivalFetchClient,
)

ROOT_URL = "https://www.kslegislature.gov/laws/"
CHAPTER_URLS = [
    "https://www.kslegislature.gov/b2025_26/laws/001_000_0000_chapter/",
    "https://www.kslegislature.gov/b2025_26/laws/002_000_0000_chapter/",
]
ARTICLE_URLS = [
    f"{CHAPTER_URLS[0]}001_001_0000_article/",
    f"{CHAPTER_URLS[1]}002_001_0000_article/",
]
SECTION_PATHS = [
    ("001_000_0000_chapter/001_001_0000_article/001_001_0001_section/001_001_0001_k/"),
    ("001_000_0000_chapter/001_001_0000_article/001_001_0002_section/001_001_0002_k/"),
    ("002_000_0000_chapter/002_001_0000_article/002_001_0001_section/002_001_0001_k/"),
]
SECTION_URLS = [
    f"https://www.kslegislature.gov/b2025_26/laws/{path}" for path in SECTION_PATHS
]


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
    *,
    errors: list[str | None] | None = None,
    returned_urls: list[str] | None = None,
) -> StateLawPageMultiFetchResult:
    return StateLawPageMultiFetchResult(
        urls=list(urls if returned_urls is None else returned_urls),
        payloads=list(payloads),
        errors=list(errors if errors is not None else [None] * len(urls)),
        transport_receipts=[None] * len(urls),
        parser_input_envelopes=[None] * len(urls),
        stats={"requested_pages": len(urls)},
    )


def _root_html() -> str:
    return (
        "<table id='statute'>"
        "<tr><td><a href='/b2025_26/laws/001_000_0000_chapter/'>"
        "Chapter 1. - FIRST CHAPTER</a></td></tr>"
        "<tr><td><a href='/b2025_26/laws/002_000_0000_chapter/'>"
        "Chapter 2. - SECOND CHAPTER</a></td></tr>"
        "</table>"
    )


def _chapter_html(chapter: int) -> bytes:
    token = f"{chapter:03d}"
    return (
        "<table id='statute'><tr><td>"
        f"<a href='{token}_001_0000_article/'>"
        f"Article 1. - ARTICLE FOR CHAPTER {chapter}</a>"
        "</td></tr></table>"
    ).encode()


def _article_html(chapter: int, *section_numbers: int) -> bytes:
    token = f"{chapter:03d}"
    rows = "".join(
        "<tr><td>"
        f"<a href='../../{token}_000_0000_chapter/"
        f"{token}_001_0000_article/{token}_001_{section:04d}_section/"
        f"{token}_001_{section:04d}_k/'>"
        f"{chapter}-{100 + section} - Official section {chapter}-{100 + section}"
        "</a></td></tr>"
        for section in section_numbers
    )
    return f"<table id='statute'>{rows}</table>".encode()


def _section_html(section_number: str) -> bytes:
    body = (
        f"Official Kansas statutory text for section {section_number}. "
        "This enacted public-law provision supplies complete normalized text. "
    ) * 3
    return (
        "<html><body>"
        "<div class='statute-body'><table></table><table><tr><td>"
        f"<p><span class='stat_5f_number'>{section_number}.</span>"
        f"<span class='stat_5f_caption'>Official heading {section_number}.</span>"
        f"{body}</p>"
        "</td></tr></table></div>"
        "</body></html>"
    ).encode()


@pytest.mark.anyio
async def test_kansas_unbounded_tree_batches_known_levels_and_retained_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KansasScraper("KS", "Kansas")
    single_calls: list[str] = []
    plural_calls: list[tuple[list[str], dict[str, Any]]] = []
    checkpoints: list[dict[str, Any]] = []
    pages = {
        CHAPTER_URLS[0]: _chapter_html(1),
        CHAPTER_URLS[1]: _chapter_html(2),
        ARTICLE_URLS[0]: _article_html(1, 1, 2),
        ARTICLE_URLS[1]: _article_html(2, 1),
        SECTION_URLS[0]: _section_html("1-101"),
        SECTION_URLS[1]: _section_html("1-102"),
        SECTION_URLS[2]: _section_html("2-101"),
    }

    async def _single(url: str, timeout_seconds: int = 18) -> str:
        single_calls.append(url)
        assert url == ROOT_URL
        return _root_html()

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, [pages[url] for url in requested])

    def _checkpoint(*_args: Any, **kwargs: Any) -> bool:
        checkpoints.append(dict(kwargs))
        return True

    monkeypatch.delenv("KANSAS_SECTION_HTML", raising=False)
    monkeypatch.delenv("KANSAS_CONSTITUTION_HTML", raising=False)
    monkeypatch.setenv("STATE_SCRAPER_KS_FRONTIER_BATCH_SIZE", "2")
    monkeypatch.setenv("STATE_SCRAPER_KS_FRONTIER_CONCURRENCY", "3")
    monkeypatch.setattr(scraper, "_fetch_official_ks_html", _single)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)

    statutes = await scraper.scrape_code(
        "Kansas Statutes",
        ROOT_URL,
        max_statutes=None,
    )

    assert single_calls == [ROOT_URL]
    assert [requested for requested, _kwargs in plural_calls] == [
        CHAPTER_URLS,
        ARTICLE_URLS,
        SECTION_URLS[:2],
        SECTION_URLS[2:],
    ]
    assert all(
        kwargs
        == {
            "timeout_seconds": 18,
            "headers": {
                "User-Agent": "ipfs-datasets-kansas-statutes-scraper/2.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            "media_type": "text/html",
            "max_concurrency": 3,
            "prefer_direct": True,
            "common_crawl_domain_terms": ("www.kslegislature.gov",),
            "common_crawl_url_terms": ("/laws/",),
            "common_crawl_mime_terms": ("html",),
        }
        for _requested, kwargs in plural_calls
    )
    assert [row.source_url for row in statutes] == SECTION_URLS
    assert [row.section_number for row in statutes] == ["1-101", "1-102", "2-101"]
    assert [item["stage_label"] for item in checkpoints] == [
        "kansas:section-progress",
        "kansas:section-progress",
        "kansas:complete",
    ]
    assert checkpoints[0]["extra"]["sections_scanned"] == 2
    assert checkpoints[-1]["extra"]["sections_scanned"] == 3
    assert checkpoints[-1]["extra"]["discovered_sections"] == 3
    assert checkpoints[-1]["force"] is True


@pytest.mark.anyio
async def test_kansas_frontier_chunking_preserves_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KansasScraper("KS", "Kansas")
    urls = [f"https://www.kslegislature.gov/b2025_26/laws/page-{i}" for i in range(5)]
    calls: list[list[str]] = []

    async def _batch(requested, *, frontier_name: str) -> list[bytes]:
        assert frontier_name == "article-index"
        chunk = list(requested)
        calls.append(chunk)
        return [url.encode() for url in chunk]

    monkeypatch.setenv("STATE_SCRAPER_KS_FRONTIER_BATCH_SIZE", "2")
    monkeypatch.setattr(scraper, "_fetch_kansas_frontier_batch", _batch)

    payloads = await scraper._fetch_kansas_frontier_in_chunks(
        urls,
        frontier_name="article-index",
    )

    assert calls == [urls[:2], urls[2:4], urls[4:]]
    assert payloads == [url.encode() for url in urls]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("malformation", "expected"),
    [
        ("worker-error", "frontier is incomplete"),
        ("empty", "frontier is incomplete"),
        ("non-bytes", "frontier is incomplete"),
        ("short-urls", "unaligned acquisition rows"),
        ("short-payloads", "unaligned acquisition rows"),
        ("short-errors", "unaligned acquisition rows"),
        ("short-receipts", "unaligned acquisition rows"),
        ("short-envelopes", "unaligned acquisition rows"),
        ("reordered", "changed URL order or identity"),
    ],
)
async def test_kansas_frontier_fails_closed_on_worker_and_vector_drift(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
    expected: str,
) -> None:
    scraper = KansasScraper("KS", "Kansas")
    urls = [
        "https://www.kslegislature.gov/b2025_26/laws/one/",
        "https://www.kslegislature.gov/b2025_26/laws/two/",
    ]

    async def _malformed(
        requested_urls, **_kwargs: Any
    ) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        result = _aligned_result(requested, [b"one", b"two"])
        if malformation == "worker-error":
            result.errors[1] = "TimeoutError: archival recovery deadline exceeded"
        elif malformation == "empty":
            result.payloads[1] = b""
        elif malformation == "non-bytes":
            result.payloads[1] = "not bytes"  # type: ignore[list-item]
        elif malformation == "short-urls":
            result.urls = result.urls[:1]
        elif malformation == "short-payloads":
            result.payloads = result.payloads[:1]
        elif malformation == "short-errors":
            result.errors = result.errors[:1]
        elif malformation == "short-receipts":
            result.transport_receipts = result.transport_receipts[:1]
        elif malformation == "short-envelopes":
            result.parser_input_envelopes = result.parser_input_envelopes[:1]
        elif malformation == "reordered":
            result.urls = list(reversed(result.urls))
        return result

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _malformed,
    )

    with pytest.raises(RuntimeError, match=expected):
        await scraper._fetch_kansas_frontier_batch(
            urls,
            frontier_name="section",
        )


@pytest.mark.anyio
async def test_kansas_bounded_crawl_keeps_singleton_hierarchy_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KansasScraper("KS", "Kansas")
    calls: list[tuple[str, str]] = []

    async def _chapters(code_url: str) -> list[tuple[str, str]]:
        calls.append(("root", code_url))
        return [(CHAPTER_URLS[0], "Chapter 1. - FIRST CHAPTER")]

    async def _articles(chapter_url: str) -> list[tuple[str, str]]:
        calls.append(("chapter", chapter_url))
        return [(ARTICLE_URLS[0], "Article 1. - FIRST ARTICLE")]

    async def _sections(article_url: str) -> list[tuple[str, str]]:
        calls.append(("article", article_url))
        return [
            (SECTION_URLS[0], "1-101 - First"),
            (SECTION_URLS[1], "1-102 - Second"),
            ("https://www.kslegislature.gov/never-requested/", "1-103 - Third"),
        ]

    async def _section(**kwargs: str) -> NormalizedStatute:
        source_url = kwargs["section_url"]
        calls.append(("section", source_url))
        number = source_url.rsplit("_", 2)[0].rsplit("_", 1)[-1]
        return NormalizedStatute(
            state_code="KS",
            state_name="Kansas",
            statute_id=f"KS-{len(calls)}",
            code_name="Kansas Statutes",
            section_number=number,
            full_text="Official bounded Kansas statute text. " * 5,
            source_url=source_url,
        )

    async def _forbid_plural(*_args: Any, **_kwargs: Any):
        raise AssertionError("bounded Kansas must retain singleton traversal")

    monkeypatch.delenv("KANSAS_SECTION_HTML", raising=False)
    monkeypatch.delenv("KANSAS_CONSTITUTION_HTML", raising=False)
    monkeypatch.setattr(scraper, "_discover_chapter_links", _chapters)
    monkeypatch.setattr(scraper, "_discover_article_links", _articles)
    monkeypatch.setattr(scraper, "_discover_section_links", _sections)
    monkeypatch.setattr(scraper, "_parse_section_page", _section)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _forbid_plural,
    )

    statutes = await scraper.scrape_code(
        "Kansas Statutes",
        ROOT_URL,
        max_statutes=2,
    )

    assert [row.source_url for row in statutes] == SECTION_URLS[:2]
    assert calls == [
        ("root", ROOT_URL),
        ("chapter", CHAPTER_URLS[0]),
        ("article", ARTICLE_URLS[0]),
        ("section", SECTION_URLS[0]),
        ("section", SECTION_URLS[1]),
    ]


@pytest.mark.anyio
async def test_kansas_root_singleton_uses_canonical_archival_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KansasScraper("KS", "Kansas")
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _transport(url: str, **kwargs: Any) -> bytes:
        calls.append((url, dict(kwargs)))
        return b"<html><body>official root</body></html>"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _transport)

    html = await scraper._fetch_official_ks_html(ROOT_URL)

    assert html == "<html><body>official root</body></html>"
    assert calls[0][0] == ROOT_URL
    assert calls[0][1]["headers"] == {
        "User-Agent": "ipfs-datasets-kansas-statutes-scraper/2.0",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    assert calls[0][1]["allow_archival_fallback"] is True
    assert calls[0][1]["media_type"] == "text/html"


@pytest.mark.anyio
async def test_kansas_partition_replays_exact_dual_and_headerless_identities_without_network(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KansasScraper("KS", "Kansas")
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="KS",
        parser_name=type(scraper).__name__,
    )
    dual_url, headerless_only_url = CHAPTER_URLS
    canonical_body = b"canonical Kansas hierarchy page"
    shadow_headerless_body = b"older headerless observation of the dual URL"
    headerless_only_body = b"retained v6-only Kansas hierarchy page"

    def _retain(url: str, body: bytes, request: dict[str, object]) -> None:
        ledger.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt={
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            },
            retrieved_at="2026-08-25T07:25:00Z",
            sanitized_request=request,
        )

    _retain(
        dual_url,
        canonical_body,
        scraper._official_sanitized_request(dual_url),
    )
    _retain(
        dual_url,
        shadow_headerless_body,
        {"method": "GET", "url": dual_url},
    )
    _retain(
        headerless_only_url,
        headerless_only_body,
        {"method": "GET", "url": headerless_only_url},
    )
    scraper.attach_state_law_acquisition_ledger(ledger)

    async def _forbid_network(*_args: Any, **_kwargs: Any):
        raise AssertionError(
            "exact retained Kansas partitions must perform zero network"
        )

    monkeypatch.setattr(
        ArchivalFetchClient,
        "fetch_many_with_fallback",
        _forbid_network,
    )
    payloads = await scraper._fetch_kansas_frontier_batch(
        [dual_url, headerless_only_url],
        frontier_name="chapter-index",
    )

    assert payloads == [canonical_body, headerless_only_body]
    assert len(ledger.entries) == 3
    assert (
        ledger.replay_retained_parser_input(
            official_url=dual_url,
            sanitized_request=scraper._official_sanitized_request(dual_url),
        )
        is not None
    )
    assert (
        ledger.replay_retained_parser_input(
            official_url=dual_url,
            sanitized_request={"method": "GET", "url": dual_url},
        )
        is not None
    )
    assert (
        ledger.replay_retained_parser_input(
            official_url=headerless_only_url,
            sanitized_request=scraper._official_sanitized_request(headerless_only_url),
        )
        is None
    )


@pytest.mark.anyio
async def test_kansas_unbounded_empty_root_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KansasScraper("KS", "Kansas")

    async def _empty(_url: str) -> list[tuple[str, str]]:
        return []

    monkeypatch.delenv("KANSAS_SECTION_HTML", raising=False)
    monkeypatch.delenv("KANSAS_CONSTITUTION_HTML", raising=False)
    monkeypatch.setattr(scraper, "_discover_chapter_links", _empty)

    with pytest.raises(RuntimeError, match="no chapter frontier"):
        await scraper.scrape_code(
            "Kansas Statutes",
            ROOT_URL,
            max_statutes=None,
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("empty_stage", "expected"),
    [
        ("article", "no article links"),
        ("section", "no section links"),
    ],
)
async def test_kansas_unbounded_empty_hierarchy_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    empty_stage: str,
    expected: str,
) -> None:
    scraper = KansasScraper("KS", "Kansas")

    async def _chunks(
        _urls: list[str],
        *,
        frontier_name: str,
    ) -> list[bytes]:
        if frontier_name == "chapter-index":
            return [
                b"<table id='statute'></table>"
                if empty_stage == "article"
                else _chapter_html(1)
            ]
        assert frontier_name == "article-index"
        return [b"<table id='statute'></table>"]

    monkeypatch.setattr(scraper, "_fetch_kansas_frontier_in_chunks", _chunks)

    with pytest.raises(RuntimeError, match=expected):
        await scraper._scrape_official_frontier(
            code_name="Kansas Statutes",
            chapter_links=[(CHAPTER_URLS[0], "Chapter 1")],
        )


@pytest.mark.anyio
async def test_kansas_unbounded_unparseable_sections_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KansasScraper("KS", "Kansas")

    async def _chunks(
        _urls: list[str],
        *,
        frontier_name: str,
    ) -> list[bytes]:
        if frontier_name == "chapter-index":
            return [_chapter_html(1)]
        assert frontier_name == "article-index"
        return [_article_html(1, 1)]

    async def _sections(
        _urls: list[str],
        *,
        frontier_name: str,
    ) -> list[bytes]:
        assert frontier_name == "section"
        return [b"<html><body>not a statute</body></html>"]

    monkeypatch.setattr(scraper, "_fetch_kansas_frontier_in_chunks", _chunks)
    monkeypatch.setattr(scraper, "_fetch_kansas_frontier_batch", _sections)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)

    with pytest.raises(RuntimeError, match="unclassified residuals"):
        await scraper._scrape_official_frontier(
            code_name="Kansas Statutes",
            chapter_links=[(CHAPTER_URLS[0], "Chapter 1")],
        )


@pytest.mark.anyio
async def test_kansas_exact_frontier_replays_every_retained_hierarchy_input(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KansasScraper("KS", "Kansas")
    pages = {
        ROOT_URL: _root_html().encode(),
        CHAPTER_URLS[0]: _chapter_html(1),
        CHAPTER_URLS[1]: _chapter_html(2),
        ARTICLE_URLS[0]: _article_html(1, 1, 2),
        ARTICLE_URLS[1]: _article_html(2, 1),
        SECTION_URLS[0]: _section_html("1-101"),
        SECTION_URLS[1]: _section_html("1-102"),
        SECTION_URLS[2]: _section_html("2-101"),
    }
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "ks-evidence",
        jurisdiction="KS",
        parser_name=type(scraper).__name__,
    )
    for url, body in pages.items():
        ledger.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt={
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            },
            retrieved_at="2026-08-25T20:00:00Z",
            sanitized_request=scraper._official_sanitized_request(url),
        )
    scraper.attach_state_law_acquisition_ledger(ledger)

    async def _single(url: str, timeout_seconds: int = 18) -> str:
        assert url == ROOT_URL
        assert timeout_seconds == 18
        return pages[url].decode()

    async def _plural(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return _aligned_result(requested, [pages[url] for url in requested])

    async def _forbid_network(*_args: Any, **_kwargs: Any):
        raise AssertionError("Kansas retained closure must perform zero network")

    captured: dict[str, Any] = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "ks-closure.json"

    monkeypatch.delenv("KANSAS_SECTION_HTML", raising=False)
    monkeypatch.delenv("KANSAS_CONSTITUTION_HTML", raising=False)
    monkeypatch.setenv("STATE_SCRAPER_KS_FRONTIER_BATCH_SIZE", "2")
    monkeypatch.setattr(scraper, "_fetch_official_ks_html", _single)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)
    monkeypatch.setattr(
        ArchivalFetchClient,
        "fetch_many_with_fallback",
        _forbid_network,
    )
    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["ks-legislature-statutes"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "ks-test@sha256:" + ("a" * 64),
    )

    rows = await scraper.scrape_code(
        "Kansas Statutes",
        ROOT_URL,
        max_statutes=None,
    )
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="KS",
    )
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert retained_path == tmp_path / "ks-closure.json"
    assert captured["completion"]["disposition"] == {
        "discovered": 3,
        "fetched": 3,
        "excluded": 0,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    assert captured["completion"]["replay"]["network_requests"] == 0
    assert captured["completion"]["rights"]["basis"] == (
        "public_law_no_state_copyright"
    )
    assert captured["completion"]["transport"]["grouped_warc_recovery"] is True
    assert captured["completion"]["transport"]["per_page_archive_loop"] is False
