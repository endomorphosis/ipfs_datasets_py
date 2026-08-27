from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.vermont import (
    VermontScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.vermont_section import (
    parse_vermont_section_html,
    source_bound_terminal_disposition,
    terminal_disposition_from_label,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.west_virginia import (
    WestVirginiaScraper,
)


def _aligned_batch(urls: list[str], pages: dict[str, bytes]) -> StateLawPageMultiFetchResult:
    payloads = [pages.get(url, b"") for url in urls]
    errors = [None if payload else "missing synthetic page" for payload in payloads]
    receipts = [
        {
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "official_url": url,
            "source_transport": "synthetic-test",
        }
        if payload
        else None
        for url, payload in zip(urls, payloads, strict=True)
    ]
    envelopes = [SimpleNamespace(body=payload) if payload else None for payload in payloads]
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=payloads,
        errors=errors,
        transport_receipts=receipts,
        parser_input_envelopes=envelopes,
        stats={"requested_pages": len(urls)},
    )


def _bind_synthetic_plural_fetch(
    monkeypatch: pytest.MonkeyPatch,
    scraper: Any,
    pages: dict[str, bytes],
) -> list[list[str]]:
    calls: list[list[str]] = []
    kwargs_calls: list[dict[str, Any]] = []

    async def _plural(urls, **kwargs):
        requested = list(urls)
        calls.append(requested)
        kwargs_calls.append(dict(kwargs))
        ledger = getattr(scraper, "_state_law_acquisition_ledger", None)
        if ledger is not None:
            payloads = [pages.get(url, b"") for url in requested]
            retained_rows = [
                ledger.retain_parser_input(
                    official_url=url,
                    body=payload,
                    transport_receipt={
                        "content_sha256": hashlib.sha256(payload).hexdigest(),
                        "official_url": url,
                        "source_transport": "direct",
                    },
                    media_type="text/html",
                    sanitized_request={"method": "GET", "url": url},
                    network_used=True,
                )
                if payload
                else None
                for url, payload in zip(requested, payloads, strict=True)
            ]
            return StateLawPageMultiFetchResult(
                urls=requested,
                payloads=payloads,
                errors=[
                    None if payload else "missing synthetic page"
                    for payload in payloads
                ],
                transport_receipts=[
                    dict(retained.transport_receipt) if retained is not None else None
                    for retained in retained_rows
                ],
                parser_input_envelopes=[
                    retained.envelope if retained is not None else None
                    for retained in retained_rows
                ],
                stats={
                    "network_requested_pages": len(requested),
                    "requested_pages": len(requested),
                    "successful_pages": sum(bool(payload) for payload in payloads),
                },
            )
        return _aligned_batch(requested, pages)

    async def _single_page_fetch_is_forbidden(*_args, **_kwargs):
        raise AssertionError("strict hierarchy must not use a singleton fetch seam")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_content_with_archival_fallback",
        _single_page_fetch_is_forbidden,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_args, **_kwargs: True)
    scraper._synthetic_plural_fetch_kwargs = kwargs_calls
    return calls


def _vermont_pages() -> dict[str, bytes]:
    scraper = VermontScraper("VT", "Vermont")
    root_links = []
    pages: dict[str, bytes] = {}
    for number, name in scraper.OFFICIAL_TITLES:
        title_slug = scraper.official_title_slug(number)
        title_url = scraper.official_title_url(number)
        chapter_url = (
            f"https://{scraper.OFFICIAL_DOMAIN}/statutes/chapter/{title_slug}/001"
        )
        section_url = (
            f"https://{scraper.OFFICIAL_DOMAIN}/statutes/section/"
            f"{title_slug}/001/00001"
        )
        root_links.append(
            f"<a href='/statutes/title/{title_slug}'>Title {number}: {name}</a>"
        )
        pages[title_url] = (
            "<html><head><title>Vermont Statutes</title></head><body>"
            f"<a href='/statutes/chapter/{title_slug}/001'>Chapter 001: Test</a>"
            "</body></html>"
        ).encode()
        if number == "1":
            subchapter_url = (
                f"https://{scraper.OFFICIAL_DOMAIN}/statutes/subchapter/01/001/001"
            )
            pages[chapter_url] = (
                "<html><head><title>Vermont Statutes</title></head><body>"
                "<a href='/statutes/subchapter/01/001/001'>Subchapter 001: Test</a>"
                "</body></html>"
            ).encode()
            pages[subchapter_url] = (
                "<html><head><title>Vermont Statutes</title></head><body>"
                "<a href='/statutes/section/01/001/00001'>§ 1. Test</a>"
                "</body></html>"
            ).encode()
        else:
            pages[chapter_url] = (
                "<html><head><title>Vermont Statutes</title></head><body>"
                f"<a href='/statutes/section/{title_slug}/001/00001'>§ 1. Test</a>"
                "</body></html>"
            ).encode()
        pages[section_url] = (
            "<html><head><title>Vermont Statutes</title></head><body>"
            "<ul class='item-list statutes-detail'><li>"
            "<p><b>§ 1. Synthetic operative section</b></p>"
            "<p>This Vermont statute supplies operative synthetic legal text "
            "for exact offline frontier testing and contains enough words to parse.</p>"
            "</li></ul></body></html>"
        ).encode()
    pages[scraper.OFFICIAL_ENTRY_URL] = (
        "<html><head><title>Vermont Statutes</title></head><body>"
        + "".join(root_links)
        + "</body></html>"
    ).encode()
    return pages


def _west_virginia_pages(*, terminal_article: bool = False) -> dict[str, bytes]:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    options = []
    pages: dict[str, bytes] = {}
    for chapter, name in scraper.OFFICIAL_CHAPTERS:
        chapter_url = scraper.official_chapter_url(chapter)
        article_url = f"https://{scraper.OFFICIAL_DOMAIN}/{chapter}-1/"
        section_url = f"https://{scraper.OFFICIAL_DOMAIN}/{chapter}-1-1/"
        options.append(f"<option value='{chapter}'>CHAPTER {chapter}. {name}</option>")
        article_label = (
            "ARTICLE 1. REPEALED." if terminal_article and chapter == "1" else "ARTICLE 1. TEST."
        )
        article_markup = (
            f"<div class='art-head'>{article_label}</div>"
            if terminal_article and chapter == "1"
            else f"<div class='art-head'><a href='/{chapter}-1/'>{article_label}</a></div>"
        )
        pages[chapter_url] = (
            "<html><head><title>West Virginia Code</title></head><body>"
            f"<h3>CHAPTER {chapter}. {name}</h3>"
            f"{article_markup}"
            "</body></html>"
        ).encode()
        if terminal_article and chapter == "1":
            continue
        pages[article_url] = (
            "<html><head><title>West Virginia Code</title></head><body>"
            f"<h3>CHAPTER {chapter}. TEST.</h3>"
            "<div class='art-head'>ARTICLE 1. TEST.</div>"
            f"<div class='sec-head'><a href='/{chapter}-1-1/'>"
            f"§{chapter}-1-1. Synthetic section.</a></div>"
            "<div id='all-sections' class='sec-head' data-id='ah-1' "
            "data-mode='hide'>Display all Article 1 Sections</div>"
            "</body></html>"
        ).encode()
        pages[section_url] = (
            "<html><head><title>West Virginia Code</title></head><body>"
            f"<h3>CHAPTER {chapter}. TEST.</h3>"
            "<div class='art-head'>ARTICLE 1. TEST.</div>"
            "<div class='sectiontext'>"
            f"<h4>§{chapter}-1-1. Synthetic operative section.</h4>"
            "<p>This West Virginia Code provision contains operative synthetic "
            "legal text for an exact offline hierarchy test. It is intentionally "
            "long enough to satisfy the retained section parser without fallback. "
            "The provision continues with additional enforceable words and clauses.</p>"
            "</div></body></html>"
        ).encode()
    pages[scraper.OFFICIAL_ENTRY_URL] = (
        "<html><head><title>West Virginia Code</title></head><body>"
        "<select id='sel-chapter'>"
        + "".join(options)
        + "</select></body></html>"
    ).encode()
    return pages


def test_vermont_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = VermontScraper("VT", "Vermont")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "vermont_section",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
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


def test_vermont_strict_frontier_batches_every_known_layer_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = VermontScraper("VT", "Vermont")
    calls = _bind_synthetic_plural_fetch(monkeypatch, scraper, _vermont_pages())

    def _legacy_insecure_tls_fetch_is_forbidden(*_args, **_kwargs):
        raise AssertionError("strict frontier must not use the legacy TLS-bypass seam")

    monkeypatch.setattr(
        scraper,
        "_official_http_get",
        _legacy_insecure_tls_fetch_is_forbidden,
    )

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "Vermont Statutes",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert len(rows) == VermontScraper.OFFICIAL_TITLE_COUNT
    assert len({row.statute_id for row in rows}) == len(rows)
    assert [len(call) for call in calls] == [1, 46, 46, 1, 46]
    assert all(
        url.startswith(f"https://{scraper.OFFICIAL_DOMAIN}/statutes/")
        for call in calls
        for url in call
    )
    assert all(
        kwargs["prefer_direct"] is True
        and kwargs["wayback_prefix_inventory"] is True
        and kwargs["repeat_grouped_archive_inventory_on_residual"] is False
        and kwargs["common_crawl_domain_terms"] == (scraper.OFFICIAL_DOMAIN,)
        and kwargs["common_crawl_url_terms"] == ("/statutes/",)
        for kwargs in scraper._synthetic_plural_fetch_kwargs
    )
    frontier = scraper._last_vermont_full_frontier["frontier"]
    assert frontier["catalog_parity"] is True
    assert frontier["algebra_closed"] is True
    assert frontier["disposition"] == {
        "discovered": 46,
        "fetched": 46,
        "excluded": 0,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }


def test_vermont_strict_frontier_rejects_static_live_catalog_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = VermontScraper("VT", "Vermont")
    pages = _vermont_pages()
    root = pages[scraper.OFFICIAL_ENTRY_URL].decode()
    first_slug = scraper.official_title_slug(scraper.OFFICIAL_TITLES[0][0])
    root = root.replace(
        f"<a href='/statutes/title/{first_slug}'>Title 1: General Provisions</a>",
        "",
    )
    pages[scraper.OFFICIAL_ENTRY_URL] = root.encode()
    _bind_synthetic_plural_fetch(monkeypatch, scraper, pages)

    with pytest.raises(RuntimeError, match="catalog parity failed"):
        asyncio.run(
            scraper._scrape_strict_full_corpus_frontier(
                "Vermont Statutes",
                record_primary=True,
                write_checkpoints=False,
            )
        )


def test_vermont_strict_frontier_rejects_static_live_name_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = VermontScraper("VT", "Vermont")
    pages = _vermont_pages()
    root = pages[scraper.OFFICIAL_ENTRY_URL].decode().replace(
        "Title 1: General Provisions",
        "Title 1: General Provisions and Silent Drift",
    )
    pages[scraper.OFFICIAL_ENTRY_URL] = root.encode()
    _bind_synthetic_plural_fetch(monkeypatch, scraper, pages)

    with pytest.raises(RuntimeError, match="catalog parity failed"):
        asyncio.run(
            scraper._scrape_strict_full_corpus_frontier(
                "Vermont Statutes",
                record_primary=True,
                write_checkpoints=False,
            )
        )


def test_vermont_future_effective_repeal_remains_active() -> None:
    assert (
        terminal_disposition_from_label(
            "Chapter 25: Test [Repealed effective May 1, 2027]",
            observed_on=date(2026, 8, 25),
        )
        is None
    )
    assert (
        terminal_disposition_from_label(
            "Chapter 25: Test [Repealed effective May 1, 2027]",
            observed_on=date(2027, 5, 1),
        )
        == "repealed"
    )
    assert (
        terminal_disposition_from_label(
            "§ 850. Repealed. 2025, No. 57, § 23, eff. January 31, 2029.",
            observed_on=date(2026, 8, 26),
        )
        is None
    )
    assert (
        terminal_disposition_from_label(
            "§ 850. Repealed. 2025, No. 57, § 23, eff. January 31, 2029.",
            observed_on=date(2029, 1, 31),
        )
        == "repealed"
    )


def test_vermont_catalog_collapses_same_url_temporal_presentation_rows() -> None:
    scraper = VermontScraper("VT", "Vermont")
    payload = (
        "<html><head><title>Vermont Statutes</title></head><body>"
        "<a href='/statutes/section/08/107/04051'>"
        "§ 4051. Medicare supplement policies [Effective January 1, 2026]</a>"
        "<a href='/statutes/section/08/107/04051'>"
        "§ 4051. Medicare supplement policies [Effective until January 1, 2026]</a>"
        "</body></html>"
    ).encode()

    units = scraper._vermont_hierarchy_units(
        payload,
        level="section",
        title_number="8",
        chapter_number="107",
    )

    assert units == [
        {
            "title": "8",
            "chapter": "107",
            "section": "4051",
            "source_label": (
                "§ 4051. Medicare supplement policies [Effective January 1, 2026]"
            ),
            "source_url": (
                "https://legislature.vermont.gov/statutes/section/08/107/04051"
            ),
        }
    ]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("§ 667. Redesignated. 2017, No. 83, § 118.", "redesignated"),
        ("§§ 907-910. [Omitted.]", "omitted"),
        ("§ 4003. [Eliminated.]", "eliminated"),
        (
            "§ 3-71. Exec. Order No. 3-71 [Intentionally left blank.]",
            "intentionally_left_blank",
        ),
    ],
)
def test_vermont_source_bound_terminal_vocabulary(
    label: str,
    expected: str,
) -> None:
    assert terminal_disposition_from_label(label) == expected


@pytest.mark.parametrize(
    "label",
    [
        "§ 551. Concurrent jurisdiction reserved",
        "§ 9-325. Priority of security interests in transferred collateral",
        (
            "§ 33-3. Exec. Order No. 33-3 "
            "[Positions Transferred to Human Services Agency]"
        ),
    ],
)
def test_vermont_terminal_vocabulary_rejects_operative_title_prose(
    label: str,
) -> None:
    assert terminal_disposition_from_label(label) is None


def test_vermont_short_operative_statute_is_not_silently_dropped() -> None:
    url = "https://legislature.vermont.gov/statutes/section/01/003/00141"
    row = parse_vermont_section_html(
        "<html><head><title>Vermont Statutes</title></head><body>"
        "<ul class='statutes-detail'><li><p><b>§ 141. Will</b></p>"
        "<p>“Will” shall include codicils.</p></li></ul></body></html>",
        source_url=url,
    )

    assert row is not None
    assert row.official_cite == "1 V.S.A. § 141"
    assert row.full_text == "“Will” shall include codicils."


def test_vermont_printed_prefixed_section_identity_survives_normalization() -> None:
    url = "https://legislature.vermont.gov/statutes/section/09A/001/00101"
    row = parse_vermont_section_html(
        "<html><head><title>Vermont Statutes</title></head><body>"
        "<ul class='statutes-detail'><li><p><b>§ 1—101. Short title</b></p>"
        "<p>This article may be cited as Uniform Commercial Code—General "
        "Provisions.</p></li></ul></body></html>",
        source_url=url,
    )

    assert row is not None
    assert row.section_number == "1-101"
    assert row.official_cite == "9A V.S.A. § 1-101"
    assert VermontScraper._vermont_printed_section_matches_locator(
        row.section_number,
        chapter_number="1",
        locator_section="101",
    )


def test_vermont_executive_order_identity_includes_order_series() -> None:
    url = "https://legislature.vermont.gov/statutes/section/03APPENDIX/006/00003"
    row = parse_vermont_section_html(
        "<html><head><title>Vermont Statutes</title></head><body>"
        "<ul class='statutes-detail'><li><p><b>Executive Order No. 6-3 "
        "(No. 10-00)</b></p><p>The Governor establishes this operative council "
        "by executive order.</p></li></ul></body></html>",
        source_url=url,
    )

    assert row is not None
    assert row.section_number == "6-3"
    assert row.official_cite == "3APPENDIX V.S.A. § 6-3"
    assert VermontScraper._vermont_printed_section_matches_locator(
        row.section_number,
        chapter_number="6",
        locator_section="3",
    )


def test_vermont_revoked_executive_order_is_source_bound_terminal() -> None:
    url = "https://legislature.vermont.gov/statutes/section/03APPENDIX/033/00003"
    html = (
        "<html><head><title>Vermont Statutes</title></head><body>"
        "<ul class='statutes-detail'><li><p><b>Executive Order No. 33-3 "
        "(No. 19-78)</b></p><p>Revoked and rescinded by Executive Order No. "
        "3-46 (codified as Executive Order 06-05).</p></li></ul></body></html>"
    )

    assert parse_vermont_section_html(html, source_url=url) is None
    assert source_bound_terminal_disposition(
        html,
        source_url=url,
        frontier_label=(
            "§ 33-3. Exec. Order No. 33-3 "
            "[Positions Transferred to Human Services Agency]"
        ),
        expected_level="section",
        observed_on=date(2026, 8, 26),
    ) == {
        "disposition": "revoked",
        "source_label": (
            "§ 33-3. Exec. Order No. 33-3 "
            "[Positions Transferred to Human Services Agency]"
        ),
        "source_url": url,
    }


def test_west_virginia_strict_frontier_batches_and_reconciles_terminal_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    calls = _bind_synthetic_plural_fetch(
        monkeypatch,
        scraper,
        _west_virginia_pages(terminal_article=True),
    )

    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "West Virginia Code",
            record_primary=True,
            write_checkpoints=False,
        )
    )

    assert len(rows) == WestVirginiaScraper.OFFICIAL_CHAPTER_COUNT - 1
    assert len({row.statute_id for row in rows}) == len(rows)
    assert [len(call) for call in calls] == [1, 139, 138, 138]
    assert all(
        kwargs["prefer_direct"] is True
        and kwargs["wayback_prefix_inventory"] is True
        and kwargs["common_crawl_domain_terms"] == (scraper.OFFICIAL_DOMAIN,)
        for kwargs in scraper._synthetic_plural_fetch_kwargs
    )
    frontier = scraper._last_west_virginia_full_frontier["frontier"]
    assert frontier["catalog_parity"] is True
    assert frontier["disposition"] == {
        "discovered": 139,
        "fetched": 138,
        "excluded": 1,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }


def test_west_virginia_strict_frontier_rejects_silent_article_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    pages = _west_virginia_pages()
    pages[f"https://{scraper.OFFICIAL_DOMAIN}/1-1/"] = (
        "<html><head><title>West Virginia Code</title></head><body>"
        "<h3>CHAPTER 1. TEST.</h3>"
        "<div class='art-head'>ARTICLE 1. OPERATIVE TEST.</div>"
        "</body></html>"
    ).encode()
    _bind_synthetic_plural_fetch(monkeypatch, scraper, pages)

    with pytest.raises(RuntimeError, match="no section frontier"):
        asyncio.run(
            scraper._scrape_strict_full_corpus_frontier(
                "West Virginia Code",
                record_primary=True,
                write_checkpoints=False,
            )
        )


def test_west_virginia_strict_frontier_rejects_disguised_unlinked_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    pages = _west_virginia_pages()
    article_url = f"https://{scraper.OFFICIAL_DOMAIN}/1-1/"
    pages[article_url] = pages[article_url].replace(
        b"Display all Article 1 Sections",
        b"\xc2\xa71-1-2. Operative-looking unlinked section.",
    )
    _bind_synthetic_plural_fetch(monkeypatch, scraper, pages)

    with pytest.raises(RuntimeError, match="operative-looking unlinked section"):
        asyncio.run(
            scraper._scrape_strict_full_corpus_frontier(
                "West Virginia Code",
                record_primary=True,
                write_checkpoints=False,
            )
        )


def test_west_virginia_strict_frontier_rejects_static_live_name_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    pages = _west_virginia_pages()
    root = pages[scraper.OFFICIAL_ENTRY_URL].decode().replace(
        "CHAPTER 1. The State and Its Subdivisions",
        "CHAPTER 1. The State and Its Subdivisions and Silent Drift",
    )
    pages[scraper.OFFICIAL_ENTRY_URL] = root.encode()
    _bind_synthetic_plural_fetch(monkeypatch, scraper, pages)

    with pytest.raises(RuntimeError, match="catalog parity failed"):
        asyncio.run(
            scraper._scrape_strict_full_corpus_frontier(
                "West Virginia Code",
                record_primary=True,
                write_checkpoints=False,
            )
        )


def test_vermont_closure_replays_exact_rows_and_retains_disposition(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = VermontScraper("VT", "Vermont")
    pages = _vermont_pages()
    calls = _bind_synthetic_plural_fetch(monkeypatch, scraper, pages)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="VT",
        parser_name="VermontScraper",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "Vermont Statutes",
            record_primary=True,
            write_checkpoints=False,
        )
    )
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="VT",
    )
    acquisition_call_count = len(calls)

    closure_path = asyncio.run(
        scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )
    )
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    assert closure["completion_receipt"]["disposition"]["fetched"] == 46
    assert closure["completion_receipt"]["rights"]["basis"] == (
        "public_law_no_state_copyright"
    )
    assert closure["completion_receipt"]["frontier"] == closure["replayed_frontier"]
    assert len(calls) == acquisition_call_count
    assert closure["completion_receipt"]["replay"]["network_requested_pages"] == 0
    assert closure["completion_receipt"]["transport"] == {
        "fixture": False,
        "grouped_warc_recovery": True,
        "kind": "shared_archive_aware_plural_html",
        "per_page_archive_loop": False,
        "primary_batch_count": 5,
        "primary_requested_pages": 140,
        "repeat_grouped_archive_inventory_on_residual": False,
        "residual_only_retries": True,
        "retained_replay_batch_count": 5,
        "retained_replay_network_requested_pages": 0,
        "retained_replay_pages": 140,
        "same_domain_plural_frontiers": True,
        "source_ordered_cross_parent_union": True,
        "synthetic": False,
        "wayback_prefix_inventory": True,
    }


def test_west_virginia_closure_replays_exact_rows_and_retains_disposition(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = WestVirginiaScraper("WV", "West Virginia")
    pages = _west_virginia_pages(terminal_article=True)
    _bind_synthetic_plural_fetch(monkeypatch, scraper, pages)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WV",
        parser_name="WestVirginiaScraper",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    rows = asyncio.run(
        scraper._scrape_strict_full_corpus_frontier(
            "West Virginia Code",
            record_primary=True,
            write_checkpoints=False,
        )
    )
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="WV",
    )
    acquisition_call_count = len(scraper._synthetic_plural_fetch_kwargs)

    closure_path = asyncio.run(
        scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )
    )
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    assert closure["completion_receipt"]["disposition"] == {
        "discovered": 139,
        "fetched": 138,
        "excluded": 1,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }
    assert closure["completion_receipt"]["rights"]["basis"] == (
        "public_law_no_state_copyright"
    )
    assert closure["completion_receipt"]["frontier"] == closure["replayed_frontier"]
    assert len(scraper._synthetic_plural_fetch_kwargs) == acquisition_call_count
    assert closure["completion_receipt"]["replay"]["network_requested_pages"] == 0
    assert closure["completion_receipt"]["transport"] == {
        "fixture": False,
        "grouped_warc_recovery": True,
        "kind": "shared_archive_aware_plural_html",
        "per_page_archive_loop": False,
        "primary_batch_count": 4,
        "primary_requested_pages": 416,
        "residual_only_retries": True,
        "retained_replay_batch_count": 4,
        "retained_replay_network_requested_pages": 0,
        "retained_replay_pages": 416,
        "same_domain_plural_frontiers": True,
        "synthetic": False,
        "wayback_prefix_inventory": True,
    }
