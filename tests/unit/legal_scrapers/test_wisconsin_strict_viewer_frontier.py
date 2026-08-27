from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin import (
    WisconsinScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin_chapter import (
    close_wisconsin_section_windows,
    parse_wisconsin_chapter_frontier_window,
    parse_wisconsin_section_window,
)


def _html(body: str, *, title: str = "Wisconsin Legislature: Statutes") -> bytes:
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<div id='document'>{body}</div><!--{'x' * 1_200}--></body></html>"
    ).encode()


def _toc(section: str, heading: str = "Provision") -> str:
    return (
        f"<div class='qstoc_entry'><a href='/document/statutes/{section}'>"
        f"{section}</a> {heading}</div>"
    )


def _block(
    section: str,
    text: str,
    *,
    path: str,
    title: str = "Operative provision.",
) -> str:
    return (
        f"<div class='qsatxt_1sect level3' data-section='{section}' "
        f"data-path='{path}'><a class='reference' href='/document/statutes/{section}'>"
        f"{section}</a><span class='qsnum_sect'>{section}</span>"
        f"<span class='qstitle_sect'>{title}</span>{text}</div>"
    )


def _down(href: str) -> str:
    return f"<div class='navigation'><a href='{href}'>Down</a></div>"


def _aligned(urls: list[str], pages: dict[str, bytes]) -> StateLawPageMultiFetchResult:
    payloads = [pages.get(url, b"") for url in urls]
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=payloads,
        errors=[None if payload else "missing synthetic retained page" for payload in payloads],
        transport_receipts=[
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(payload).hexdigest() if payload else "",
                "source_transport": "direct",
            }
            for url, payload in zip(urls, payloads, strict=True)
        ],
        parser_input_envelopes=[None] * len(urls),
        stats={
            "requested_pages": len(urls),
            "common_crawl": {
                "range_fetch_calls": 1 if len(urls) > 1 else 0,
                "range_fetches_avoided": max(0, len(urls) - 1),
            },
        },
    )


class _Ledger:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = dict(pages)
        self.requests: list[str] = []

    def refresh_existing_entries(self) -> None:
        return None

    def replay_retained_parser_input(self, *, official_url: str, sanitized_request):
        assert sanitized_request["method"] == "GET"
        self.requests.append(official_url)
        payload = self.pages.get(official_url)
        if payload is None:
            return None
        return SimpleNamespace(
            envelope=SimpleNamespace(body=payload),
            transport_receipt={
                "official_url": official_url,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "source_transport": "retained_acquisition_replay",
            },
        )


def _synthetic_pages(scraper: WisconsinScraper) -> dict[str, bytes]:
    base = scraper.get_base_url()
    chapter_1 = f"{base}/document/statutes/1"
    chapter_2 = f"{base}/document/statutes/2"
    chapter_2_next = f"{base}/statutes/statutes/2/_60?down=1"
    section_201_next = f"{base}/statutes/statutes/2/01/_60?down=1"
    pages = {
        scraper.OFFICIAL_ENTRY_URL: _html(
            "<p><a href='/document/statutes/1'>Chapter 1 - Government</a></p>"
            "<p><a href='/document/statutes/2'>Chapter 2 - Administration</a></p>",
            title="Wisconsin Legislature: Statutes",
        ),
        chapter_1: _html(
            _toc("1.01")
            + _toc("1.02", "[Repealed]")
            + _block(
                "1.01",
                "This official Wisconsin provision contains enough complete statutory text.",
                path="/statutes/statutes/1/01",
            ),
            title="Wisconsin Legislature: Chapter 1",
        ),
        chapter_2: _html(
            _toc("2.01")
            + _down("/statutes/statutes/2/_60?down=1"),
            title="Wisconsin Legislature: Chapter 2",
        ),
        chapter_2_next: _html(
            _toc("2.02")
            + _block(
                "2.01",
                "The chapter body begins only after the final source-derived TOC entry.",
                path="/statutes/statutes/2/01",
            ),
            title="Wisconsin Legislature: Chapter 2",
        ),
        f"{base}/document/statutes/1.01": _html(
            _block(
                "1.01",
                "This complete official section governs public administration in Wisconsin.",
                path="/statutes/statutes/1/01",
            )
            + _block(
                "1.02",
                "The next section proves that the requested section body has ended.",
                path="/statutes/statutes/1/02",
            ),
            title="Wisconsin Legislature: 1.01",
        ),
        f"{base}/document/statutes/1.02": _html(
            _block(
                "1.02",
                "",
                path="/statutes/statutes/1/02",
                title="[Repealed]",
            ),
            title="Wisconsin Legislature: 1.02",
        ),
        f"{base}/document/statutes/2.01": _html(
            _block(
                "2.01",
                "The first retained window begins a long operative statutory provision",
                path="/statutes/statutes/2/01/1",
            )
            + _down("/statutes/statutes/2/01/_60?down=1"),
            title="Wisconsin Legislature: 2.01",
        ),
        section_201_next: _html(
            _block(
                "2.01",
                "and this second retained window completes that provision without truncation.",
                path="/statutes/statutes/2/01/2",
                title="",
            )
            + _block(
                "2.02",
                "The next section is a source-bound completion sentinel.",
                path="/statutes/statutes/2/02",
            ),
            title="Wisconsin Legislature: 2.01",
        ),
        f"{base}/document/statutes/2.02": _html(
            _block(
                "2.02",
                "This separate official Wisconsin section is complete at the document boundary.",
                path="/statutes/statutes/2/02",
            ),
            title="Wisconsin Legislature: 2.02",
        ),
    }
    return pages


def _projection(scraper: WisconsinScraper, rows):
    return build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="WI",
    )


def test_wisconsin_window_parser_excludes_body_citations_from_toc() -> None:
    html = _html(
        _toc("66.01")
        + "<div><a href='/document/statutes/66.99'>body citation only</a></div>"
        + _block(
            "66.01",
            "A complete statutory body that is long enough for normalized output.",
            path="/statutes/statutes/66/01",
        ),
        title="Wisconsin Legislature: Chapter 66",
    ).decode()
    window = parse_wisconsin_chapter_frontier_window(
        html,
        chapter="66",
        page_url="https://docs.legis.wisconsin.gov/document/statutes/66",
    )
    assert [row[0] for row in window.section_rows] == ["66.01"]
    assert window.body_started is True
    assert window.residuals == ()


def test_wisconsin_toc_uses_leading_identity_not_title_cross_references() -> None:
    html = _html(
        "<div class='qstoc_entry'>"
        "<a href='/document/statutes/134.32'>134.32</a> "
        "Penalty for violations of "
        "<a href='/document/statutes/134.25'>s. 134.25</a> to "
        "<a href='/document/statutes/134.31'>s. 134.31</a>."
        "</div>"
        "<div class='qstoc_entry'>134.39 "
        "A source-listed operative section whose self-link is omitted.</div>"
    ).decode()
    window = parse_wisconsin_chapter_frontier_window(
        html,
        chapter="134",
        page_url="https://docs.legis.wisconsin.gov/document/statutes/134",
    )

    assert [row[0] for row in window.section_rows] == ["134.32", "134.39"]
    assert [row[2] for row in window.section_rows] == [
        "https://docs.legis.wisconsin.gov/document/statutes/134.32",
        "https://docs.legis.wisconsin.gov/document/statutes/134.39",
    ]
    assert window.residuals == ()


def test_wisconsin_short_nonempty_source_body_is_operative() -> None:
    window = parse_wisconsin_section_window(
        _html(
            _block(
                "46.017",
                "The department may sue and be sued.",
                path="/statutes/statutes/46/017",
                title="Legal actions.",
            ),
            title="Wisconsin Legislature: 46.017",
        ).decode(),
        section_number="46.017",
        page_url="https://docs.legis.wisconsin.gov/document/statutes/46.017",
    )
    parsed = close_wisconsin_section_windows(
        [window],
        section_number="46.017",
        traversal_closed=True,
    )

    assert parsed.closed is True
    assert parsed.statute is not None
    assert parsed.statute.full_text == "The department may sue and be sued."
    assert parsed.terminal_section is None


def test_wisconsin_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WisconsinScraper("WI", "Wisconsin")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "wisconsin_chapter",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.wisconsin."
        "WisconsinScraper@sha256:"
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


@pytest.mark.anyio
async def test_wisconsin_plural_policy_is_ordered_and_does_not_reinventory_residuals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WisconsinScraper("WI", "Wisconsin")
    urls = [
        f"{scraper.get_base_url()}/document/statutes/1.01",
        f"{scraper.get_base_url()}/document/statutes/2.01",
    ]
    pages = {url: _html(_block(url.rsplit('/', 1)[-1], "Body.", path=url)) for url in urls}
    calls: list[tuple[list[str], dict]] = []

    async def _plural(requested_urls, **kwargs):
        requested = list(requested_urls)
        calls.append((requested, dict(kwargs)))
        return _aligned(requested, pages)

    monkeypatch.setenv("STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS", "0")
    monkeypatch.setenv("STATE_SCRAPER_WI_FRONTIER_RESIDUAL_RETRY_ATTEMPTS", "2")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    result = await scraper._fetch_wisconsin_frontier_batch(
        urls,
        frontier_name="section-body-wave-1",
        content_validator=scraper._is_valid_wisconsin_viewer,
        prefer_direct=True,
    )

    assert result.urls == urls
    assert calls[0][0] == urls
    assert calls[0][1]["residual_retry_attempts"] == 2
    assert calls[0][1]["repeat_grouped_archive_inventory_on_residual"] is False
    assert calls[0][1]["wayback_prefix_inventory"] is True
    assert calls[0][1]["common_crawl_domain_terms"] == (
        "docs.legis.wisconsin.gov",
    )
    assert calls[0][1]["common_crawl_url_terms"] == (
        "/statutes/statutes",
        "/document/statutes/",
    )

    with pytest.raises(RuntimeError, match="off-domain"):
        await scraper._fetch_wisconsin_frontier_batch(
            ["https://example.invalid/document/statutes/1.01"],
            frontier_name="section-body-wave-invalid",
            content_validator=scraper._is_valid_wisconsin_viewer,
            prefer_direct=True,
        )


@pytest.mark.anyio
async def test_wisconsin_explicit_bound_preserves_legacy_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    scraper = WisconsinScraper("WI", "Wisconsin")
    observed: dict[str, object] = {}

    async def _legacy(code_name: str, max_statutes=None):
        observed["code_name"] = code_name
        observed["limit"] = max_statutes
        return [SimpleNamespace(section_number="1.01")]

    async def _forbid_strict(*_args, **_kwargs):
        raise AssertionError("an explicit bound must not enter exact acquisition")

    monkeypatch.setattr(scraper, "_scrape_official_index", _legacy)
    monkeypatch.setattr(scraper, "_scrape_wisconsin_strict_frontier", _forbid_strict)

    rows = await scraper.scrape_code(
        "Wisconsin Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=2,
    )

    assert [row.section_number for row in rows] == ["1.01"]
    assert observed == {"code_name": "Wisconsin Statutes", "limit": 2}


def test_wisconsin_exact_section_windows_reconcile_terminal_and_operatives() -> None:
    first = parse_wisconsin_section_window(
        _html(
            _block(
                "2.01",
                "The first half of a complete official statutory provision",
                path="/statutes/statutes/2/01/1",
            )
            + _down("/statutes/statutes/2/01/_60?down=1"),
            title="Wisconsin Legislature: 2.01",
        ).decode(),
        section_number="2.01",
        page_url="https://docs.legis.wisconsin.gov/document/statutes/2.01",
    )
    second = parse_wisconsin_section_window(
        _html(
            _block(
                "2.01",
                "and the retained continuation completes it without truncation.",
                path="/statutes/statutes/2/01/2",
                title="",
            )
            + _block(
                "2.02",
                "The next section proves the exact target boundary.",
                path="/statutes/statutes/2/02",
            ),
            title="Wisconsin Legislature: 2.01",
        ).decode(),
        section_number="2.01",
        page_url="https://docs.legis.wisconsin.gov/statutes/statutes/2/01/_60?down=1",
    )
    parsed = close_wisconsin_section_windows(
        [first, second],
        section_number="2.01",
        source_url="https://docs.legis.wisconsin.gov/document/statutes/2.01",
        traversal_closed=True,
    )
    assert parsed.closed is True
    assert parsed.statute is not None
    assert "without truncation" in parsed.statute.full_text
    assert parsed.source_block_count == 2

    terminal_window = parse_wisconsin_section_window(
        _html(
            _block(
                "2.09",
                "",
                path="/statutes/statutes/2/09",
                title="[Reserved]",
            ),
            title="Wisconsin Legislature: 2.09",
        ).decode(),
        section_number="2.09",
        page_url="https://docs.legis.wisconsin.gov/document/statutes/2.09",
    )
    terminal = close_wisconsin_section_windows(
        [terminal_window],
        section_number="2.09",
        traversal_closed=True,
    )
    assert terminal.closed is True
    assert terminal.statute is None
    assert terminal.terminal_section["disposition"] == "reserved"


@pytest.mark.anyio
async def test_wisconsin_strict_frontier_pluralizes_waves_and_replays_zero_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(WisconsinScraper, "STRICT_MINIMUM_CHAPTERS", 2)
    scraper = WisconsinScraper("WI", "Wisconsin")
    pages = _synthetic_pages(scraper)
    calls: list[tuple[list[str], dict]] = []

    async def _plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append((requested, {"retries": residual_retry_attempts, **kwargs}))
        result = _aligned(requested, pages)
        assert all(
            kwargs["content_validator"](payload)
            for payload in result.payloads
            if payload
        )
        return result

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict Wisconsin must not use a per-page archive loop")

    monkeypatch.setattr(
        WisconsinScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(
        WisconsinScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )
    rows = await scraper.scrape_code(
        "Wisconsin Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )
    assert [row.section_number for row in rows] == ["1.01", "2.01", "2.02"]
    assert [len(call[0]) for call in calls] == [1, 2, 1, 4, 1]
    assert calls[1][0] == [
        f"{scraper.get_base_url()}/document/statutes/1",
        f"{scraper.get_base_url()}/document/statutes/2",
    ]
    assert calls[3][0] == [
        f"{scraper.get_base_url()}/document/statutes/1.01",
        f"{scraper.get_base_url()}/document/statutes/1.02",
        f"{scraper.get_base_url()}/document/statutes/2.01",
        f"{scraper.get_base_url()}/document/statutes/2.02",
    ]
    assert all(call[1]["retries"] == 1 for call in calls)
    assert all(call[1]["wayback_prefix_inventory"] is True for call in calls)
    assert all(
        call[1]["repeat_grouped_archive_inventory_on_residual"] is False
        for call in calls
    )
    assert calls[0][1]["prefer_direct"] is True
    assert all(call[1]["prefer_direct"] is True for call in calls[1:])
    assert scraper._last_wisconsin_strict_closure["source_sections"] == 4
    assert scraper._last_wisconsin_strict_closure["terminal_sections"] == 1

    ledger = _Ledger(pages)
    scraper._state_law_acquisition_ledger = ledger
    captured: dict[str, object] = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "wi-closure.json"

    async def _forbid_plural(*_args, **_kwargs):
        raise AssertionError("retained Wisconsin replay must make zero network calls")

    def _forbid_legacy(*_args, **_kwargs):
        raise AssertionError("strict Wisconsin certification must not use fetch_official")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _forbid_plural,
    )
    monkeypatch.setattr(scraper, "fetch_official", _forbid_legacy)
    monkeypatch.setattr(scraper, "retain_state_law_frontier_closure_projection", _retain)
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["wi-legislature-statutes"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "wi-test@sha256:" + ("c" * 64),
    )
    projection = _projection(scraper, rows)
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )
    assert retained_path == tmp_path / "wi-closure.json"
    completion = captured["completion"]
    assert completion["disposition"] == {
        "discovered": 4,
        "fetched": 3,
        "excluded": 1,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    assert completion["rights"]["basis"] == "public_law_no_state_copyright"
    assert completion["replay"]["network_requests"] == 0
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    assert completion["transport"]["wayback_prefix_inventory"] is True
    assert completion["transport"]["source_ordered_cross_parent_union"] is True
    assert completion["transport"][
        "repeat_grouped_archive_inventory_on_residual"
    ] is False
    assert completion["transport"]["root_acquisition_wave_count"] == 1
    assert completion["transport"]["chapter_acquisition_wave_count"] == 2
    assert completion["transport"]["leaf_acquisition_wave_count"] == 2
    assert completion["transport"]["first_pass_request_batches"] == 5
    assert completion["transport"]["first_pass_requested_pages"] == 9
    assert set(ledger.requests) == set(pages)

    schema_ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "wi-schema-ledger",
        jurisdiction="WI",
        parser_name="WisconsinViewerParser",
    )
    schema_path = schema_ledger.retain_frontier_closure_projection(
        captured["completion"],
        **captured["kwargs"],
    )
    verified = schema_ledger.verify_retained_frontier_closure_projection(
        projection,
        closure_input_path=schema_path,
    )
    assert verified["canonical_row_count"] == 3


@pytest.mark.anyio
async def test_wisconsin_strict_frontier_fails_closed_on_missing_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(WisconsinScraper, "STRICT_MINIMUM_CHAPTERS", 2)
    scraper = WisconsinScraper("WI", "Wisconsin")
    pages = _synthetic_pages(scraper)
    pages.pop(f"{scraper.get_base_url()}/statutes/statutes/2/_60?down=1")

    async def _plural(self, urls, **_kwargs):
        return _aligned(list(urls), pages)

    monkeypatch.setattr(
        WisconsinScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    with pytest.raises(RuntimeError, match="unresolved exact URLs"):
        await scraper.scrape_code(
            "Wisconsin Statutes",
            scraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
