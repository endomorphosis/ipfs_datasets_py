from __future__ import annotations

import hashlib
import inspect
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import nebraska
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska import (
    NebraskaScraper,
)


CHAPTER_URL = (
    "https://nebraskalegislature.gov/laws/browse-chapters.php?chapter=1"
)
SECOND_CHAPTER_URL = (
    "https://nebraskalegislature.gov/laws/browse-chapters.php?chapter=2"
)
SECTION_URLS = [
    f"https://nebraskalegislature.gov/laws/statutes.php?statute=1-{number}"
    for number in range(101, 106)
]
SECOND_SECTION_URLS = [
    f"https://nebraskalegislature.gov/laws/statutes.php?statute=2-{number}"
    for number in range(201, 203)
]
TERMINAL_SECTIONS = {
    "2-970": "Repealed. Laws 2026, LB807, § 6.",
    "2-1004": "Repealed. Laws 1988, LB 874, § 49.",
    "2-1007": "Repealed. Laws 1988, LB 874, § 49.",
    "2-1008": "Repealed. Laws 1988, LB 874, § 49.",
    "2-1034": "Repealed. Laws 1988, LB 874, § 49.",
    "2-1529": "Repealed. Laws 1983, LB 36, § 5.",
    "2-1549.02": "Repealed. Laws 1977, LB 510, § 10.",
    "2-1549.03": "Repealed. Laws 1977, LB 510, § 10.",
    "2-1550": "Repealed. Laws 1977, LB 510, § 10.",
    "2-1554": "Repealed. Laws 1977, LB 510, § 10.",
}


def _section_payload(section_number: str) -> bytes:
    body = (
        f"Official Nebraska statutory text for section {section_number}. "
        "This public-law provision supplies substantive normalized text. "
    ) * 4
    return (
        "<html><body><div class='statute'>"
        f"<h2>{section_number}.</h2>"
        f"<h3>Official heading for {section_number}.</h3>"
        f"<p>{body}</p>"
        "</div></body></html>"
    ).encode()


def _chapter_payload(section_numbers: list[str]) -> bytes:
    links = "".join(
        (
            "<a href='/laws/statutes.php?statute="
            f"{section_number}'>{section_number}</a>"
        )
        for section_number in section_numbers
    )
    return f"<html><body>{links}</body></html>".encode()


def _chapter_catalog_payload() -> bytes:
    def _row(section_number: str, summary: str) -> str:
        escaped_summary = summary.replace("§", "&sect;")
        href = f"/laws/statutes.php?statute={section_number}"
        return (
            '<tr><td class="row">'
            f'<span><a href="{href}">'
            '<span class="sr-only">View Statute </span>'
            f"{section_number}</a></span>"
            f"<span>{escaped_summary}</span>"
            f'<span><a href="{href}&amp;print=true">Print</a></span>'
            "</td></tr>"
        )

    rows = "".join(
        _row(section_number, summary)
        for section_number, summary in TERMINAL_SECTIONS.items()
    )
    rows += _row("2-971", "Active official provision.")
    return f"<html><body><table>{rows}</table></body></html>".encode()


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


@pytest.mark.anyio
async def test_nebraska_unbounded_index_unions_cross_chapter_descendants_in_one_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    chapter_urls = [CHAPTER_URL, SECOND_CHAPTER_URL]
    requested_sections = [*SECTION_URLS[:3], *SECOND_SECTION_URLS]
    plural_calls: list[tuple[list[str], dict[str, Any]]] = []
    checkpoints: list[tuple[list[str], dict[str, Any]]] = []

    async def _chapters() -> list[str]:
        return list(chapter_urls)

    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("uncapped Nebraska must not fetch catalog/detail singletons")

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append((requested, dict(kwargs)))
        if requested == chapter_urls:
            return _aligned_result(
                requested,
                [
                    _chapter_payload(["1-101", "1-102", "1-103"]),
                    _chapter_payload(["2-201", "2-202"]),
                ],
            )
        return _aligned_result(
            requested,
            [
                _section_payload(url.rsplit("=", 1)[-1])
                for url in requested
            ],
        )

    def _checkpoint(statutes, **kwargs: Any) -> bool:
        checkpoints.append(
            ([str(row.source_url or "") for row in statutes], dict(kwargs))
        )
        return True

    monkeypatch.setenv("STATE_SCRAPER_NE_SECTION_BATCH_SIZE", "8")
    monkeypatch.setenv("STATE_SCRAPER_NE_SECTION_CONCURRENCY", "3")
    monkeypatch.setattr(
        scraper,
        "_load_partial_checkpoint_statutes",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(scraper, "_load_partial_checkpoint_progress", lambda: {})
    monkeypatch.setattr(scraper, "_discover_chapter_urls", _chapters)
    monkeypatch.setattr(scraper, "_request_text_direct", _forbid_singleton)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)

    statutes = await scraper._scrape_official_index(
        "Nebraska Revised Statutes",
        max_statutes=None,
    )

    assert plural_calls == [
        (
            chapter_urls,
            {
                "headers": {"User-Agent": "Mozilla/5.0"},
                "timeout_seconds": 30,
                "content_validator": plural_calls[0][1]["content_validator"],
                "media_type": "text/html",
                "max_concurrency": 8,
                "prefer_direct": True,
                "common_crawl_domain_terms": ("nebraskalegislature.gov",),
                "common_crawl_url_terms": ("/laws/browse-chapters.php",),
                "common_crawl_mime_terms": ("html",),
                "wayback_prefix_inventory": True,
            },
        ),
        (
            requested_sections,
            {
                "timeout_seconds": 20,
                "media_type": "text/html",
                "max_concurrency": 3,
                "prefer_direct": True,
                "common_crawl_domain_terms": ("nebraskalegislature.gov",),
                "common_crawl_url_terms": ("/laws/statutes.php",),
                "common_crawl_mime_terms": ("html",),
                "wayback_prefix_inventory": True,
            },
        )
    ]
    assert plural_calls[0][1]["content_validator"](
        _chapter_payload(["1-101"])
    ) is True
    assert [row.source_url for row in statutes] == requested_sections
    assert [row.section_number for row in statutes] == [
        "1-101",
        "1-102",
        "1-103",
        "2-201",
        "2-202",
    ]
    section_checkpoints = [
        (urls, kwargs)
        for urls, kwargs in checkpoints
        if kwargs["stage_label"] == "nebraska:section-scan"
    ]
    assert len(section_checkpoints) == 1
    assert section_checkpoints[0][0] == requested_sections
    assert section_checkpoints[0][1]["extra"]["sections_scanned"] == 5
    assert section_checkpoints[0][1]["extra"]["chapters_scanned"] == 2
    assert checkpoints[-1][1]["stage_label"] == "nebraska:complete"


@pytest.mark.anyio
async def test_nebraska_known_chapter_frontier_uses_one_plural_base_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    chapter_urls = [
        scraper.official_chapter_url(number)
        for number in (1, 2, 3)
    ]
    payloads = [
        _chapter_payload([f"{number}-101"])
        for number in (1, 2, 3)
    ]
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        return _aligned_result(requested, list(payloads))

    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("strict Nebraska chapters must not use singleton fetch")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_request_text_direct", _forbid_singleton)

    observed = await scraper._fetch_nebraska_chapter_frontier_batch(
        chapter_urls
    )

    assert observed == payloads
    assert len(calls) == 1
    assert calls[0][0] == chapter_urls
    assert calls[0][1]["common_crawl_url_terms"] == (
        "/laws/browse-chapters.php",
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("malformation", "expected"),
    [
        ("short", "unaligned acquisition rows"),
        ("reordered", "changed URL order or identity"),
        ("miss", "frontier is incomplete"),
    ],
)
async def test_nebraska_chapter_frontier_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
    expected: str,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    urls = [
        scraper.official_chapter_url(1),
        scraper.official_chapter_url(2),
    ]
    payloads = [
        _chapter_payload(["1-101"]),
        _chapter_payload(["2-101"]),
    ]

    async def _malformed(requested_urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        result = _aligned_result(requested, list(payloads))
        if malformation == "short":
            result.parser_input_envelopes = [None]
        elif malformation == "reordered":
            result.urls = list(reversed(requested))
        else:
            result.payloads[1] = b""
            result.errors[1] = "archive miss"
        return result

    monkeypatch.setenv(
        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
        "0",
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _malformed,
    )

    with pytest.raises(RuntimeError, match=expected):
        await scraper._fetch_nebraska_chapter_frontier_batch(urls)


@pytest.mark.anyio
async def test_nebraska_unbounded_sections_use_one_wave_and_bounded_parse_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    calls: list[list[str]] = []
    progress: list[tuple[int, int, list[str]]] = []

    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("uncapped Nebraska must not use singleton section fetches")

    async def _plural(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append(requested)
        return _aligned_result(
            requested,
            [
                _section_payload(url.rsplit("=", 1)[-1])
                for url in requested
            ],
        )

    def _progress(
        scanned: int,
        total: int,
        rows,
    ) -> None:
        progress.append(
            (scanned, total, [str(row.source_url or "") for row in rows])
        )

    monkeypatch.setenv("STATE_SCRAPER_NE_SECTION_BATCH_SIZE", "2")
    monkeypatch.setattr(scraper, "_request_text_direct", _forbid_singleton)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    statutes = await scraper._scrape_section_urls(
        "Nebraska Revised Statutes",
        list(SECTION_URLS),
        max_statutes=None,
        discovery_method="official_chapter_index_sections",
        progress_hook=_progress,
    )

    assert calls == [SECTION_URLS]
    assert [row.source_url for row in statutes] == SECTION_URLS
    assert progress == [
        (2, 5, SECTION_URLS[:2]),
        (4, 5, SECTION_URLS[:4]),
        (5, 5, SECTION_URLS),
    ]


def test_nebraska_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "nebraska_section",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska."
        "NebraskaScraper@sha256:"
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
@pytest.mark.parametrize(
    ("malformation", "expected"),
    [
        ("typed", "frontier is incomplete"),
        ("empty", "frontier is incomplete"),
        ("short", "unaligned acquisition rows"),
        ("reordered", "changed URL order or identity"),
    ],
)
async def test_nebraska_unbounded_section_frontier_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
    expected: str,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    monkeypatch.setenv(
        "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
        "0",
    )
    urls = SECTION_URLS[:2]
    payloads = [_section_payload("1-101"), _section_payload("1-102")]

    async def _malformed(requested_urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(requested_urls)
        if malformation == "typed":
            return _aligned_result(
                requested,
                payloads,
                errors=[None, "TimeoutError: residual fallback deadline exceeded"],
            )
        if malformation == "empty":
            return _aligned_result(requested, [payloads[0], b""])
        if malformation == "reordered":
            return _aligned_result(
                requested,
                payloads,
                returned_urls=list(reversed(requested)),
            )
        result = _aligned_result(requested, payloads)
        result.parser_input_envelopes = [None]
        return result

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _malformed,
    )

    with pytest.raises(RuntimeError, match=expected):
        await scraper._scrape_section_urls(
            "Nebraska Revised Statutes",
            urls,
            max_statutes=None,
            discovery_method="official_chapter_index_sections",
        )


@pytest.mark.anyio
async def test_nebraska_bounded_sections_keep_singleton_fetch_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    singleton_calls: list[str] = []

    async def _single(url: str, timeout: int = 20) -> str:
        singleton_calls.append(url)
        return _section_payload(url.rsplit("=", 1)[-1]).decode()

    async def _forbid_plural(*_args: Any, **_kwargs: Any):
        raise AssertionError("bounded Nebraska must keep its singleton path")

    monkeypatch.setattr(scraper, "_request_text_direct", _single)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _forbid_plural,
    )

    statutes = await scraper._scrape_section_urls(
        "Nebraska Revised Statutes",
        SECTION_URLS[:2],
        max_statutes=2,
        discovery_method="bounded_probe",
    )

    assert singleton_calls == SECTION_URLS[:2]
    assert {row.source_url for row in statutes} == set(SECTION_URLS[:2])


def test_nebraska_source_bound_catalog_terminal_rejects_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_url = (
        "https://nebraskalegislature.gov/laws/browse-chapters.php?chapter=fixture"
    )
    payload = _chapter_catalog_payload()
    monkeypatch.setattr(
        nebraska,
        "_EXACT_TERMINAL_CHAPTER_CATALOGS",
        {
            catalog_url: {
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "terminal_sections": dict(TERMINAL_SECTIONS),
                "disposition": "repealed",
            }
        },
    )

    typed = nebraska._source_bound_terminal_sections_from_chapter_catalog_html(
        payload.decode(),
        source_url=catalog_url,
    )
    assert typed == {
        (
            "https://nebraskalegislature.gov/laws/statutes.php?statute="
            f"{section_number}"
        ): {
            "section_number": section_number,
            "catalog_text": catalog_text,
            "disposition": "repealed",
            "catalog_url": catalog_url,
            "catalog_content_sha256": hashlib.sha256(payload).hexdigest(),
        }
        for section_number, catalog_text in TERMINAL_SECTIONS.items()
    }
    assert (
        nebraska._source_bound_terminal_sections_from_chapter_catalog_html(
            payload.decode(),
            source_url=f"{catalog_url}&copy=1",
        )
        == {}
    )
    assert (
        nebraska._source_bound_terminal_sections_from_chapter_catalog_html(
            payload.decode().replace("LB807", "LB808"),
            source_url=catalog_url,
        )
        == {}
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    (
        ("Repealed. Laws 1997, LB 53, § 52.", "repealed"),
        ("Transferred to section 43-1401 .", "transferred"),
        ("Transferred to sections 87-101 and 87-102 .", "transferred"),
        ("Unconstitutional.", "unconstitutional"),
        ("Omitted.", "omitted"),
        ("Expired.", "expired"),
        ("Deleted.", "deleted"),
        ("Act, expired.", "expired"),
        (
            "Note: This section was transferred in 1991 from section 66-471. "
            "Laws 1985, LB 346, section 9 provided for a repeal of section "
            "66-471 with an operative date of January 1, 1993.",
            "repealed",
        ),
        (
            "Note: According to the provisions of section 80-507, the act "
            "comprising this article expired by its own limitation on June "
            "30, 1947. The entire article has therefor been omitted.",
            "expired",
        ),
        ("Repeal of former law; effect.", ""),
        ("Act expired.", ""),
        ("Note: This section was transferred in 1991.", ""),
        ("Transfer of cemetery; powers and duties.", ""),
        ("Reservation of power to amend or repeal.", ""),
        ("Licenses; expiration; renewal.", ""),
        ("Organization under unconstitutional law; procedure.", ""),
    ),
)
def test_nebraska_catalog_terminal_vocabulary_is_anchored(
    label: str,
    expected: str,
) -> None:
    assert (
        nebraska._source_bound_terminal_disposition_from_chapter_label(label)
        == expected
    )


def test_nebraska_current_official_catalog_types_all_exact_terminal_labels() -> None:
    def _row(section_number: str, summary: str) -> str:
        href = f"/laws/statutes.php?statute={section_number}"
        return (
            '<tr><td class="row">'
            f'<span><a href="{href}">{section_number}</a></span>'
            f"<span>{summary}</span>"
            f'<span><a href="{href}&amp;print=true">Print</a></span>'
            "</td></tr>"
        )

    rows = (
        _row("1-101", "Repealed. Laws 1997, LB 53, &sect; 52.")
        + _row("1-102", "Transferred to section 43-1401 .")
        + _row("1-103", "Unconstitutional.")
        + _row("1-104", "Omitted.")
        + _row("1-105", "Expired.")
        + _row("1-106", "Deleted.")
        + _row("1-107", "Repeal of former law; effect.")
        + _row("1-108", "Transfer of cemetery; powers and duties.")
        + _row("1-109", "Act, expired.")
        + _row(
            "1-110",
            "Note: This section was transferred in 1991 from section 66-471. "
            "Laws 1985, LB 346, section 9 provided for a repeal of section "
            "66-471 with an operative date of January 1, 1993.",
        )
        + _row(
            "1-111",
            "Note: According to the provisions of section 80-507, the act "
            "comprising this article expired by its own limitation on June "
            "30, 1947. The entire article has therefor been omitted.",
        )
    )
    payload = f"<html><body><table>{rows}</table></body></html>"
    digest = hashlib.sha256(payload.encode()).hexdigest()

    typed = nebraska._source_bound_terminal_sections_from_chapter_catalog_html(
        payload,
        source_url=CHAPTER_URL,
    )

    assert {
        record["section_number"]: record["disposition"]
        for record in typed.values()
    } == {
        "1-101": "repealed",
        "1-102": "transferred",
        "1-103": "unconstitutional",
        "1-104": "omitted",
        "1-105": "expired",
        "1-106": "deleted",
        "1-109": "expired",
        "1-110": "repealed",
        "1-111": "expired",
    }
    assert {record["catalog_content_sha256"] for record in typed.values()} == {
        digest
    }
    assert {record["catalog_url"] for record in typed.values()} == {CHAPTER_URL}

    for invalid_url in (
        CHAPTER_URL.replace("https://", "http://"),
        f"{CHAPTER_URL}&copy=1",
        CHAPTER_URL.replace("nebraskalegislature.gov", "example.test"),
        CHAPTER_URL.replace("nebraskalegislature.gov", "nebraskalegislature.gov:bad"),
        CHAPTER_URL.replace("chapter=1", "chapter=fixture"),
    ):
        assert (
            nebraska._source_bound_terminal_sections_from_chapter_catalog_html(
                payload,
                source_url=invalid_url,
            )
            == {}
        )

    assert (
        nebraska._source_bound_terminal_sections_from_chapter_catalog_html(
            payload.replace("&amp;print=true", "&amp;download=true"),
            source_url=CHAPTER_URL,
        )
        == {}
    )


@pytest.mark.parametrize(
    "dom_drift",
    ("detail_anchor_position", "summary", "print_anchor"),
)
def test_nebraska_source_bound_catalog_terminal_rejects_dom_drift(
    monkeypatch: pytest.MonkeyPatch,
    dom_drift: str,
) -> None:
    catalog_url = (
        "https://nebraskalegislature.gov/laws/browse-chapters.php?chapter=fixture"
    )
    payload = _chapter_catalog_payload().decode()
    href = "/laws/statutes.php?statute=2-1529"
    if dom_drift == "detail_anchor_position":
        payload = payload.replace(
            (
                f'<span><a href="{href}"><span class="sr-only">'
                "View Statute </span>2-1529</a></span>"
            ),
            f'<span>2-1529</span><a href="{href}">2-1529</a>',
        )
    elif dom_drift == "summary":
        payload = payload.replace(
            "Repealed. Laws 1983, LB 36, &sect; 5.",
            "Repealed. Laws 1983, LB 36, &sect; 6.",
        )
    else:
        payload = payload.replace(
            f'{href}&amp;print=true">Print</a>',
            f'{href}&amp;download=true">Print</a>',
        )
    assert payload != _chapter_catalog_payload().decode()
    monkeypatch.setattr(
        nebraska,
        "_EXACT_TERMINAL_CHAPTER_CATALOGS",
        {
            catalog_url: {
                "content_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "terminal_sections": {
                    "2-1529": TERMINAL_SECTIONS["2-1529"],
                },
                "disposition": "repealed",
            }
        },
    )

    assert (
        nebraska._source_bound_terminal_sections_from_chapter_catalog_html(
            payload,
            source_url=catalog_url,
        )
        == {}
    )


def test_nebraska_source_bound_catalog_replays_retained_contract() -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_NE_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Nebraska acquisition evidence")

    catalog_url = (
        "https://nebraskalegislature.gov/laws/browse-chapters.php?chapter=2"
    )
    expected = nebraska._EXACT_TERMINAL_CHAPTER_CATALOGS[catalog_url]
    assert expected["terminal_sections"] == TERMINAL_SECTIONS
    jurisdiction_root = Path(evidence_root) / "NE"
    payload = (
        jurisdiction_root / "objects" / f'{expected["content_sha256"]}.bin'
    ).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == expected["content_sha256"]

    typed = nebraska._source_bound_terminal_sections_from_chapter_catalog_html(
        payload.decode(),
        source_url=catalog_url,
    )
    assert {record["section_number"] for record in typed.values()} == set(
        TERMINAL_SECTIONS
    )
    assert {record["disposition"] for record in typed.values()} == {"repealed"}


@pytest.mark.anyio
async def test_nebraska_unbounded_index_excludes_exact_catalog_terminals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_url = (
        "https://nebraskalegislature.gov/laws/browse-chapters.php?chapter=fixture"
    )
    terminal_urls = [
        (
            "https://nebraskalegislature.gov/laws/statutes.php?statute="
            f"{section_number}"
        )
        for section_number in TERMINAL_SECTIONS
    ]
    active_url = (
        "https://nebraskalegislature.gov/laws/statutes.php?statute=2-971"
    )
    catalog_payload = _chapter_catalog_payload()
    checkpoints: list[dict[str, Any]] = []
    plural_calls: list[list[str]] = []

    monkeypatch.setattr(
        nebraska,
        "_EXACT_TERMINAL_CHAPTER_CATALOGS",
        {
            catalog_url: {
                "content_sha256": hashlib.sha256(catalog_payload).hexdigest(),
                "terminal_sections": dict(TERMINAL_SECTIONS),
                "disposition": "repealed",
            }
        },
    )
    scraper = NebraskaScraper("NE", "Nebraska")

    async def _chapters() -> list[str]:
        return [catalog_url]

    async def _forbid_singleton(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("strict Nebraska chapters must be fetched plurally")

    async def _plural(urls, **_kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append(requested)
        if requested == [catalog_url]:
            return _aligned_result(requested, [catalog_payload])
        return _aligned_result(requested, [_section_payload("2-971")])

    def _checkpoint(_rows, **kwargs: Any) -> bool:
        checkpoints.append(dict(kwargs))
        return True

    monkeypatch.setattr(scraper, "_load_partial_checkpoint_statutes", lambda **_kwargs: [])
    monkeypatch.setattr(scraper, "_load_partial_checkpoint_progress", lambda: {})
    monkeypatch.setattr(scraper, "_discover_chapter_urls", _chapters)
    monkeypatch.setattr(scraper, "_request_text_direct", _forbid_singleton)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", _checkpoint)

    rows = await scraper._scrape_official_index(
        "Nebraska Revised Statutes",
        max_statutes=None,
    )

    assert [row.source_url for row in rows] == [active_url]
    assert plural_calls == [[catalog_url], [active_url]]
    assert not set(terminal_urls).intersection(plural_calls[1])
    assert checkpoints[-1]["stage_label"] == "nebraska:complete"
    assert checkpoints[-1]["extra"]["terminal_sections_excluded"] == 10
    assert checkpoints[-1]["extra"]["terminal_section_urls"] == sorted(
        terminal_urls
    )
    assert checkpoints[-1]["extra"]["terminal_disposition_counts"] == {
        "repealed": 10
    }
