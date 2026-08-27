from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import (
    LouisianaScraper,
)


LAW_URLS = [
    f"https://legis.la.gov/legis/Law.aspx?d={document_id}"
    for document_id in (1001, 1002, 1003, 2001, 2002)
]


def _law_payload(url: str) -> bytes:
    document_id = url.rsplit("=", 1)[-1]
    section_number = (
        f"1:{int(document_id) - 1000}"
        if document_id.startswith("1")
        else f"2:{int(document_id) - 2000}"
    )
    body = (
        f"Official Louisiana statutory text for section {section_number}. "
        "This complete public-law provision supplies substantive normalized text. "
    ) * 5
    return f"""
    <form id="aspnetForm" action="./Law.aspx?d={document_id}">
      <input id="ctl00_PageBody_ButtonPrevious" />
      <span id="ctl00_PageBody_LabelName">RS {section_number}</span>
      <input id="ctl00_PageBody_ButtonNext" />
      <a id="ctl00_PageBody_linkPrint" href="LawPrint.aspx?d={document_id}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument"><div id="WPMainDoc">
        <p>&sect;{section_number}. Official provision.</p><p>{body}</p>
      </div></span>
    </form>
    """.encode()


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
    *,
    errors: list[str | None] | None = None,
    returned_urls: list[str] | None = None,
) -> StateLawPageMultiFetchResult:
    aligned_errors = list(errors if errors is not None else [None] * len(urls))
    receipts = [
        (
            {
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            }
            if payload and error is None
            else None
        )
        for url, payload, error in zip(urls, payloads, aligned_errors, strict=True)
    ]
    return StateLawPageMultiFetchResult(
        urls=list(urls if returned_urls is None else returned_urls),
        payloads=list(payloads),
        errors=aligned_errors,
        transport_receipts=receipts,
        parser_input_envelopes=[
            SimpleNamespace(body=payload) if payload else None for payload in payloads
        ],
        stats={
            "direct_initial_successes": sum(
                bool(payload) and error is None
                for payload, error in zip(payloads, aligned_errors, strict=True)
            ),
            "common_crawl": {
                "range_fetch_calls": 1,
                "naive_range_fetches": len(urls),
                "range_fetches_avoided": max(0, len(urls) - 1),
            },
        },
    )


def test_louisiana_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "louisiana_law",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana."
        "LouisianaScraper@sha256:"
    )

    archival_source = inspect.getsourcefile(dependencies[1])
    assert archival_source is not None
    archival_path = Path(archival_source).resolve()
    original_read_bytes = Path.read_bytes

    def _read_mutated_dependency(path: Path) -> bytes:
        payload = original_read_bytes(path)
        if path.resolve() == archival_path:
            return payload + b"\n# synthetic producer-affecting mutation\n"
        return payload

    monkeypatch.setattr(Path, "read_bytes", _read_mutated_dependency)

    assert scraper._state_law_frontier_source_software_version() != baseline


def test_louisiana_title_postbacks_decode_only_exact_anchor_hrefs() -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    target_1 = "ctl00$PageBody$ListViewTOC1$ctrl0$LinkButton1a"
    target_2 = "ctl00$PageBody$ListViewTOC1$ctrl1$LinkButton1a"
    html = f"""
      <script>javascript:__doPostBack('{target_1}','')</script>
      <div data-href="javascript:__doPostBack('{target_1}','')"></div>
      <a href="https://example.invalid/?next=javascript:__doPostBack(
          '{target_1}','')">forged prefix</a>
      <a href="javascript:__doPostBack(&#39;{target_1}&#39;,&#39;&#39;)">
        encoded title
      </a>
      <a href="javascript:__doPostBack('{target_1}','')">duplicate title</a>
      <a href="javascript:__doPostBack('{target_2}','')">second title</a>
      <a href="javascript:__doPostBack(
          'ctl00$PageBody$ListViewTOC1$ctrl2$LinkButton1b','')">wrong control</a>
    """

    assert scraper._title_postback_targets(html) == [target_1, target_2]


@pytest.mark.anyio
async def test_louisiana_toc_preserves_cross_parent_source_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    root = b"""
      <input name="__VIEWSTATE" value="retained-view-state" />
      <a href="javascript:__doPostBack('ctl00$PageBody$ListViewTOC1$ctrl0$LinkButton1a','')">Title 1</a>
      <a href="javascript:__doPostBack('ctl00$PageBody$ListViewTOC1$ctrl1$LinkButton1a','')">Title 2</a>
    """
    parent_pages = {
        1: b"<a href='Law.aspx?d=1001'>1:1</a><a href='Law.aspx?d=1002'>1:2</a>",
        2: b"<a href='Law.aspx?d=2001'>2:1</a><a href='Law.aspx?d=2002'>2:2</a>",
    }
    calls: list[tuple[str, int]] = []

    async def _fetch(_url: str, **kwargs: Any) -> bytes:
        method = str(kwargs.get("method") or "GET")
        page_index = int(dict(kwargs.get("pagination") or {}).get("page_index") or 0)
        calls.append((method, page_index))
        return root if method == "GET" else parent_pages[page_index]

    async def _close(_session: object) -> None:
        return None

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_new_stateful_parser_input_session", lambda **_k: object())
    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _fetch)
    monkeypatch.setattr(scraper, "_close_stateful_parser_input_session", _close)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)

    observed = await scraper._discover_live_toc_title_pages(limit=None)

    assert observed == [LAW_URLS[0], LAW_URLS[1], LAW_URLS[3], LAW_URLS[4]]
    assert calls == [("GET", 0), ("POST", 1), ("POST", 2)]


@pytest.mark.anyio
async def test_louisiana_unbounded_cross_parent_union_uses_one_plural_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    calls: list[tuple[list[str], dict[str, Any]]] = []
    checkpoints: list[dict[str, Any]] = []

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, [_law_payload(url) for url in requested])

    def _checkpoint(*_args: Any, **kwargs: Any) -> bool:
        checkpoints.append(dict(kwargs))
        return True

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_LA_FRONTIER_BATCH_SIZE", "2")
    monkeypatch.setenv("STATE_SCRAPER_LA_FRONTIER_CONCURRENCY", "3")
    monkeypatch.setenv("STATE_SCRAPER_LA_FRONTIER_RESIDUAL_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)

    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=list(LAW_URLS),
        max_statutes=None,
    )

    assert len(calls) == 1
    assert calls[0][0] == LAW_URLS
    assert calls[0][1] == {
        "residual_retry_attempts": 2,
        "repeat_grouped_archive_inventory_on_residual": False,
        "timeout_seconds": 45,
        "media_type": "text/html",
        "max_concurrency": 3,
        "prefer_direct": True,
        "common_crawl_domain_terms": ("legis.la.gov",),
        "common_crawl_url_terms": ("/legis/Law.aspx",),
        "common_crawl_mime_terms": ("html",),
        "wayback_prefix_inventory": True,
    }
    assert [row.source_url for row in rows] == LAW_URLS
    frontier = scraper._last_louisiana_full_frontier
    assert frontier["closed"] is True
    assert frontier["frontier_batches"] == 1
    assert frontier["frontier_pages"] == len(LAW_URLS)
    assert frontier["leaf_acquisition_wave_count"] == 1
    assert frontier["law_pages_requested"] == len(LAW_URLS)
    assert checkpoints[-1]["stage_label"] == "louisiana-law-page-complete"


@pytest.mark.anyio
async def test_louisiana_plural_wave_retries_only_residual_without_archive_reinventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    urls = LAW_URLS[:3]
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(requested_urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append((requested, dict(kwargs)))
        if len(calls) == 1:
            return _aligned_result(
                requested,
                [_law_payload(requested[0]), b"", _law_payload(requested[2])],
                errors=[None, "temporary archive miss", None],
            )
        return _aligned_result(requested, [_law_payload(requested[0])])

    monkeypatch.setenv("STATE_SCRAPER_LA_FRONTIER_RESIDUAL_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    result = await scraper._fetch_louisiana_law_frontier(
        urls,
        max_concurrency=4,
    )

    assert [requested for requested, _kwargs in calls] == [urls, [urls[1]]]
    assert calls[0][1]["wayback_prefix_inventory"] is True
    assert "archive_recovery_enabled" not in calls[0][1]
    assert calls[1][1]["archive_recovery_enabled"] is False
    assert result.errors == [None, None, None]
    assert result.stats["residual_retry_rounds_executed"] == 1
    assert result.stats["residual_retry_requested_pages"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("malformation", "expected"),
    [
        ("short", "unaligned acquisition rows"),
        ("reordered", "changed URL order or identity"),
    ],
)
async def test_louisiana_plural_wave_fails_closed_on_alignment_or_order_drift(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
    expected: str,
) -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    urls = LAW_URLS[:2]

    async def _malformed(requested_urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        result = _aligned_result(requested, [_law_payload(url) for url in requested])
        if malformation == "short":
            result.parser_input_envelopes = [None]
        else:
            result.urls = list(reversed(requested))
        return result

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _malformed,
    )

    with pytest.raises(RuntimeError, match=expected):
        await scraper._fetch_louisiana_law_frontier(urls, max_concurrency=2)


@pytest.mark.anyio
async def test_louisiana_bounded_probe_keeps_singleton_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    urls = LAW_URLS[:2]
    singleton_calls: list[str] = []

    async def _single(*, law_url: str, **_kwargs: Any) -> str:
        singleton_calls.append(law_url)
        return _law_payload(law_url).decode()

    async def _forbid_plural(*_args: Any, **_kwargs: Any):
        raise AssertionError("bounded Louisiana must keep its singleton path")

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    monkeypatch.setattr(scraper, "_request_text", _single)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _forbid_plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)

    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=urls,
        max_statutes=2,
    )

    assert singleton_calls == urls
    assert [row.source_url for row in rows] == urls
