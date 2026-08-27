from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana import (
    MontanaScraper,
)


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
    *,
    errors: list[str | None] | None = None,
) -> StateLawPageMultiFetchResult:
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=list(errors if errors is not None else [None] * len(urls)),
        transport_receipts=[None] * len(urls),
        parser_input_envelopes=[None] * len(urls),
        stats={"requested_pages": len(urls)},
    )


def _section_payload(section_number: str) -> bytes:
    body = (
        f"Official Montana statutory text for section {section_number}. "
        "This public-law provision supplies substantive normalized text. "
    ) * 4
    return (
        "<html><body><main>"
        f"<h1>{section_number}. Official heading.</h1>"
        f"<p>{body}</p>"
        "</main></body></html>"
    ).encode()


def test_montana_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "montana_section",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.montana."
        "MontanaScraper@sha256:"
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
async def test_montana_plural_wave_explicitly_disables_archive_reinventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    urls = [
        "https://leg.mt.gov/bills/mca/one.html",
        "https://leg.mt.gov/bills/mca/two.html",
    ]
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _retrying(
        requested_urls,
        **kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, [b"one", b"two"])

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _retrying,
    )

    assert await scraper._fetch_montana_frontier_batch(
        urls,
        frontier_name="section",
    ) == [b"one", b"two"]
    assert calls[0][0] == urls
    assert calls[0][1]["repeat_grouped_archive_inventory_on_residual"] is False
    assert calls[0][1]["wayback_prefix_inventory"] is True


@pytest.mark.anyio
async def test_montana_exact_tree_uses_complete_cross_parent_ordered_waves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    base = "https://leg.mt.gov/bills/mca"
    titles = [
        ("Title 1", f"{base}/title_0010/chapters_index.html"),
        ("Title 2", f"{base}/title_0020/chapters_index.html"),
    ]
    chapters = [
        f"{base}/title_0010/chapter_0010/parts_index.html",
        f"{base}/title_0010/chapter_0020/parts_index.html",
        f"{base}/title_0020/chapter_0010/parts_index.html",
        f"{base}/title_0020/chapter_0030/parts_index.html",
    ]
    parts = [
        f"{base}/title_0010/chapter_0010/part_0010/sections_index.html",
        f"{base}/title_0010/chapter_0010/part_0020/sections_index.html",
        f"{base}/title_0010/chapter_0020/part_0010/sections_index.html",
        f"{base}/title_0020/chapter_0010/part_0010/sections_index.html",
        f"{base}/title_0020/chapter_0030/part_0010/sections_index.html",
        f"{base}/title_0020/chapter_0030/part_0020/sections_index.html",
    ]
    active = [
        (
            "1-1-101",
            f"{base}/title_0010/chapter_0010/part_0010/section_0010/"
            "0010-0010-0010-0010.html",
        ),
        (
            "1-1-201",
            f"{base}/title_0010/chapter_0010/part_0020/section_0010/"
            "0010-0010-0020-0010.html",
        ),
        (
            "1-2-101",
            f"{base}/title_0010/chapter_0020/part_0010/section_0010/"
            "0010-0020-0010-0010.html",
        ),
        (
            "2-1-101",
            f"{base}/title_0020/chapter_0010/part_0010/section_0010/"
            "0020-0010-0010-0010.html",
        ),
        (
            "2-3-101",
            f"{base}/title_0020/chapter_0030/part_0010/section_0010/"
            "0020-0030-0010-0010.html",
        ),
        (
            "2-3-201",
            f"{base}/title_0020/chapter_0030/part_0020/section_0010/"
            "0020-0030-0020-0010.html",
        ),
    ]
    terminal_url = (
        f"{base}/title_0010/chapter_0010/part_0010/section_0020/"
        "0010-0010-0010-0020.html"
    )
    pages = {
        titles[0][1]: (
            "<a href='chapter_0010/parts_index.html'>Chapter 1</a>"
            "<a href='chapter_0020/parts_index.html'>Chapter 2</a>"
        ).encode(),
        titles[1][1]: (
            "<a href='chapter_0010/parts_index.html'>Chapter 1</a>"
            "<a href='chapter_0030/parts_index.html'>Chapter 3</a>"
        ).encode(),
        chapters[0]: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
            "<a href='part_0020/sections_index.html'>Part 2</a>"
        ).encode(),
        chapters[1]: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
        ).encode(),
        chapters[2]: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
        ).encode(),
        chapters[3]: (
            "<a href='part_0010/sections_index.html'>Part 1</a>"
            "<a href='part_0020/sections_index.html'>Part 2</a>"
        ).encode(),
        parts[0]: (
            "<a href='./section_0010/0010-0010-0010-0010.html'>"
            "1-1-101 Active</a>"
            "<a href='./section_0020/0010-0010-0010-0020.html'>"
            "1-1-102 Repealed</a>"
        ).encode(),
        parts[1]: (
            "<a href='./section_0010/0010-0010-0020-0010.html'>"
            "1-1-201 Active</a>"
        ).encode(),
        parts[2]: (
            "<a href='./section_0010/0010-0020-0010-0010.html'>"
            "1-2-101 Active</a>"
        ).encode(),
        parts[3]: (
            "<a href='./section_0010/0020-0010-0010-0010.html'>"
            "2-1-101 Active</a>"
        ).encode(),
        parts[4]: (
            "<a href='./section_0010/0020-0030-0010-0010.html'>"
            "2-3-101 Active</a>"
        ).encode(),
        parts[5]: (
            "<a href='./section_0010/0020-0030-0020-0010.html'>"
            "2-3-201 Active</a>"
        ).encode(),
        **{url: _section_payload(number) for number, url in active},
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []
    checkpoints: list[dict[str, Any]] = []

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        assert terminal_url not in requested
        return _aligned_result(requested, [pages[url] for url in requested])

    monkeypatch.setenv("STATE_SCRAPER_MT_FRONTIER_BATCH_SIZE", "2")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(
        scraper,
        "_write_partial_checkpoint",
        lambda *_args, **kwargs: checkpoints.append(dict(kwargs)) or True,
    )

    rows = await scraper._scrape_official_mca_html_frontier(
        "Montana Code Annotated",
        titles,
    )

    assert [requested for requested, _kwargs in calls] == [
        [url for _label, url in titles],
        chapters,
        parts,
        [url for _number, url in active],
    ]
    assert all(kwargs["wayback_prefix_inventory"] is True for _urls, kwargs in calls)
    assert [row.source_url for row in rows] == [url for _number, url in active]
    assert [row.section_number for row in rows] == [number for number, _url in active]
    assert [
        checkpoint["extra"]["sections_scanned"]
        for checkpoint in checkpoints
        if checkpoint["stage_label"] == "montana:section-progress"
    ] == [2, 4, 6]
    assert checkpoints[-1]["stage_label"] == "montana:complete"
    assert checkpoints[-1]["extra"]["terminal_sections_excluded"] == 1


@pytest.mark.anyio
async def test_montana_plural_retry_is_residual_only_and_disables_archive_reentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MontanaScraper("MT", "Montana")
    urls = [
        "https://leg.mt.gov/bills/mca/one.html",
        "https://leg.mt.gov/bills/mca/two.html",
        "https://leg.mt.gov/bills/mca/three.html",
    ]
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(requested_urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        calls.append((requested, dict(kwargs)))
        if len(calls) == 1:
            return _aligned_result(
                requested,
                [b"one", b"", b""],
                errors=[None, "temporary miss", "temporary miss"],
            )
        return _aligned_result(requested, [b"two", b"three"])

    monkeypatch.setenv("STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    payloads = await scraper._fetch_montana_frontier_batch(
        urls,
        frontier_name="section",
    )

    assert payloads == [b"one", b"two", b"three"]
    assert [requested for requested, _kwargs in calls] == [urls, urls[1:]]
    assert calls[0][1]["wayback_prefix_inventory"] is True
    assert "archive_recovery_enabled" not in calls[0][1]
    assert calls[1][1]["wayback_prefix_inventory"] is True
    assert calls[1][1]["archive_recovery_enabled"] is False
