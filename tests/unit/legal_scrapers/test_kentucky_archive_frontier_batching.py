from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any
from unittest.mock import ANY

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky import (
    KentuckyScraper,
)

CHAPTER_URLS = [
    "https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=1",
    "https://apps.legislature.ky.gov/law/statutes/chapter.aspx?id=2",
]
SECTION_URLS = [
    "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=101",
    "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=102",
    "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=201",
]


def _chapter_payload(*section_rows: tuple[int, str]) -> bytes:
    links = "".join(
        f"<a href='statute.aspx?id={source_id}'>{label}</a>"
        for source_id, label in section_rows
    )
    return f"<html><body><h1>Kentucky Revised Statutes</h1>{links}</body></html>".encode()


def _section_payload(section_number: str) -> bytes:
    return (
        "<html><body>"
        f"KRS {section_number} Official statutory text for section {section_number}. "
        "This provision is retained from the official Kentucky source."
        "</body></html>"
    ).encode()


def _disable_checkpoints(scraper: KentuckyScraper) -> None:
    scraper._write_partial_checkpoint = lambda *_args, **_kwargs: False


def _chapter_unit(
    url: str,
    label: str,
    number: str,
    *,
    container: bool = False,
    kind: str = "chapter",
    parent_label: str | None = None,
) -> dict[str, object]:
    return {
        "chapter_label": parent_label or label,
        "chapter_number": number,
        "is_structural_container": container,
        "unit_kind": kind,
        "unit_label": label,
        "url": url,
    }


@pytest.mark.anyio
async def test_kentucky_frontier_uses_grouped_archive_wave_and_residual_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(urls, **kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        payloads = [_section_payload(str(index)) for index, _url in enumerate(requested, 1)]
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=payloads,
            errors=[None] * len(requested),
            transport_receipts=[None] * len(requested),
            parser_input_envelopes=[None] * len(requested),
            stats={"requested_pages": len(requested)},
        )

    monkeypatch.setenv("STATE_SCRAPER_KY_FRONTIER_CONCURRENCY", "3")
    monkeypatch.setenv(
        "STATE_SCRAPER_KY_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
        "2",
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    payloads = await scraper._fetch_official_ky_frontier(
        SECTION_URLS[:2],
        frontier_name="section",
        timeout_seconds=17,
        content_validator=lambda payload: payload.startswith(b"<html>"),
    )

    assert len(payloads) == 2
    assert calls == [
        (
            SECTION_URLS[:2],
            {
                "residual_retry_attempts": 2,
                "repeat_grouped_archive_inventory_on_residual": False,
                "timeout_seconds": 17,
                "content_validator": ANY,
                "max_concurrency": 3,
                "prefer_direct": True,
                "common_crawl_domain_terms": ("apps.legislature.ky.gov",),
                "common_crawl_url_terms": ("/law/statutes/",),
                "common_crawl_mime_terms": ("html", "pdf"),
                "wayback_prefix_inventory": True,
            },
        )
    ]


@pytest.mark.anyio
async def test_kentucky_frontier_retries_only_unresolved_without_new_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(urls, **kwargs: Any) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        if len(calls) == 1:
            return StateLawPageMultiFetchResult(
                urls=requested,
                payloads=[_section_payload("1.010"), b""],
                errors=[None, "direct and grouped archive miss"],
                transport_receipts=[None, None],
                parser_input_envelopes=[None, None],
                stats={"network_requested_pages": 2},
            )
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[_section_payload("1.020")],
            errors=[None],
            transport_receipts=[None],
            parser_input_envelopes=[None],
            stats={"network_requested_pages": 1},
        )

    monkeypatch.setenv(
        "STATE_SCRAPER_KY_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
        "1",
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )

    payloads = await scraper._fetch_official_ky_frontier(
        SECTION_URLS[:2],
        frontier_name="section",
        timeout_seconds=20,
        content_validator=lambda payload: payload.startswith(b"<html>"),
    )

    assert payloads == [
        _section_payload("1.010"),
        _section_payload("1.020"),
    ]
    assert [requested for requested, _kwargs in calls] == [
        SECTION_URLS[:2],
        SECTION_URLS[1:2],
    ]
    assert calls[0][1]["wayback_prefix_inventory"] is True
    assert "archive_recovery_enabled" not in calls[0][1]
    assert calls[1][1]["archive_recovery_enabled"] is False


@pytest.mark.anyio
async def test_kentucky_replay_only_accepts_plain_and_legacy_request_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    plain_url, legacy_url = CHAPTER_URLS
    plain_body = _chapter_payload((101, ".010 Legislative intent."))
    legacy_body = _chapter_payload((201, ".010 Public administration."))
    accept = "text/html,application/pdf,*/*;q=0.8"
    seed = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="KY",
        parser_name="KentuckyScraper",
    )
    for url, body, sanitized_request in (
        (plain_url, plain_body, {"method": "GET", "url": plain_url}),
        (
            legacy_url,
            legacy_body,
            {
                "headers": {"Accept": accept},
                "method": "GET",
                "url": legacy_url,
            },
        ),
    ):
        seed.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt={
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            },
            retrieved_at="2026-08-26T00:00:00+00:00",
            sanitized_request=sanitized_request,
        )

    replay = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="KY",
        parser_name="KentuckyScraper",
        retained_replay_only=True,
    )
    scraper = KentuckyScraper("KY", "Kentucky")
    scraper.attach_state_law_acquisition_ledger(replay)

    async def _forbid_transport(*_args, **_kwargs):
        raise AssertionError("exact Kentucky replay must not enter transport")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _forbid_transport,
    )

    assert await scraper._fetch_official_ky_frontier(
        [plain_url, legacy_url],
        frontier_name="chapter-index",
        timeout_seconds=1,
        content_validator=scraper._looks_like_kentucky_chapter_payload,
    ) == [plain_body, legacy_body]
    assert scraper._replay_official_ky_frontier(
        [legacy_url, plain_url],
        frontier_name="chapter-index",
        content_validator=scraper._looks_like_kentucky_chapter_payload,
    ) == [legacy_body, plain_body]


@pytest.mark.anyio
async def test_kentucky_live_frontier_keeps_plain_get_in_shared_residual_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = CHAPTER_URLS[0]
    body = _chapter_payload((101, ".010 Legislative intent."))
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="KY",
        parser_name="KentuckyScraper",
    )
    ledger.retain_parser_input(
        official_url=url,
        body=body,
        transport_receipt={
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "official_url": url,
            "source_transport": "direct",
        },
        retrieved_at="2026-08-26T00:00:00+00:00",
        sanitized_request={"method": "GET", "url": url},
    )
    scraper = KentuckyScraper("KY", "Kentucky")
    scraper.attach_state_law_acquisition_ledger(ledger)
    calls: list[list[str]] = []

    async def _plural(urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        calls.append(requested)
        return StateLawPageMultiFetchResult(
            urls=requested,
            payloads=[body],
            errors=[None],
            transport_receipts=[None],
            parser_input_envelopes=[None],
            stats={"retained_replay_pages": 1},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    assert await scraper._fetch_official_ky_frontier(
        [url],
        frontier_name="chapter-index",
        timeout_seconds=1,
        content_validator=scraper._looks_like_kentucky_chapter_payload,
    ) == [body]
    assert calls == [[url]]


@pytest.mark.anyio
async def test_kentucky_frontier_rejects_reordered_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")

    async def _reordered(urls, **_kwargs) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return StateLawPageMultiFetchResult(
            urls=list(reversed(requested)),
            payloads=[_section_payload("1.010"), _section_payload("1.020")],
            errors=[None, None],
            transport_receipts=[None, None],
            parser_input_envelopes=[None, None],
            stats={},
        )

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _reordered,
    )

    with pytest.raises(RuntimeError, match="changed URL order or identity"):
        await scraper._fetch_official_ky_frontier(
            SECTION_URLS[:2],
            frontier_name="section",
            timeout_seconds=5,
        )


def test_kentucky_source_bundle_binds_parser_closure_and_plural_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert [dependency.__name__.rsplit(".", 1)[-1] for dependency in dependencies] == [
        "base_scraper",
        "state_archival_fetch",
        "strict_frontier_closure",
        "kentucky_section",
        "wayback_machine_engine",
    ]
    baseline = scraper._state_law_frontier_source_software_version()
    assert baseline.startswith(
        "ipfs_datasets_py.processors.legal_scrapers.state_scrapers.kentucky."
        "KentuckyScraper@sha256:"
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
async def test_kentucky_unbounded_tree_unions_cross_chapter_leaves_in_one_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    _disable_checkpoints(scraper)
    chapter_units = [
        _chapter_unit(CHAPTER_URLS[0], "CHAPTER 1 GENERAL PROVISIONS", "1"),
        _chapter_unit(CHAPTER_URLS[1], "CHAPTER 2 PUBLIC ADMINISTRATION", "2"),
    ]
    pages = {
        CHAPTER_URLS[0]: _chapter_payload(
            (101, ".010 Legislative intent."),
            (102, ".020 Definitions."),
        ),
        CHAPTER_URLS[1]: _chapter_payload((201, ".010 Public administration.")),
        SECTION_URLS[0]: _section_payload("1.010"),
        SECTION_URLS[1]: _section_payload("1.020"),
        SECTION_URLS[2]: _section_payload("2.010"),
    }
    calls: list[tuple[str, list[str]]] = []

    async def _discover() -> list[dict[str, object]]:
        return chapter_units

    async def _frontier(urls, *, frontier_name: str, **_kwargs) -> list[bytes]:
        requested = list(urls)
        calls.append((frontier_name, requested))
        return [pages[url] for url in requested]

    async def _extract(*, source_url: str, raw_bytes: bytes) -> dict[str, str]:
        assert raw_bytes == pages[source_url]
        section_number = {
            SECTION_URLS[0]: "1.010",
            SECTION_URLS[1]: "1.020",
            SECTION_URLS[2]: "2.010",
        }[source_url]
        return {
            "text": f"KRS {section_number} Complete official Kentucky statutory text.",
            "method": "test_html",
        }

    monkeypatch.setenv("STATE_SCRAPER_KY_SECTION_BATCH_SIZE", "2")
    monkeypatch.setattr(scraper, "_discover_chapter_units", _discover)
    monkeypatch.setattr(scraper, "_fetch_official_ky_frontier", _frontier)
    monkeypatch.setattr(scraper, "_extract_text_from_document_bytes", _extract)

    statutes = await scraper._scrape_official_krs_tree(
        "Kentucky Revised Statutes",
        max_statutes=None,
    )

    assert calls == [
        ("chapter-index", CHAPTER_URLS),
        ("section", SECTION_URLS),
    ]
    assert [row.section_number for row in statutes] == ["1.010", "1.020", "2.010"]
    assert [row.source_url for row in statutes] == SECTION_URLS
    assert [row.statute_id for row in statutes] == [
        "KRS-1.010:record:kentucky-statute-101",
        "KRS-1.020:record:kentucky-statute-102",
        "KRS-2.010:record:kentucky-statute-201",
    ]
    assert scraper._last_kentucky_full_frontier == {
        "chapters_discovered": 2,
        "chapters_scanned": 2,
        "closed": True,
        "concurrent_section_groups": 0,
        "concurrent_source_records": 0,
        "section_locators_discovered": 3,
        "section_locators_visited": 3,
        "statutes_emitted": 3,
        "structural_container_exclusions": [],
        "typed_empty_chapter_exclusions": [],
    }


@pytest.mark.anyio
async def test_kentucky_unbounded_tree_preserves_concurrent_official_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    _disable_checkpoints(scraper)
    chapter_units = [
        _chapter_unit(
            CHAPTER_URLS[1],
            "CHAPTER 2 CITIZENSHIP, EMBLEMS, HOLIDAYS, AND TIME",
            "2",
        )
    ]
    concurrent_urls = [SECTION_URLS[0], SECTION_URLS[1]]
    pages = {
        CHAPTER_URLS[1]: _chapter_payload(
            (101, ".015 Age of majority -- Exceptions. (Effective until January 1, 2027)"),
            (102, ".015 Age of majority -- Exceptions. (Effective January 1, 2027)"),
        ),
        SECTION_URLS[0]: _section_payload("2.015 current"),
        SECTION_URLS[1]: _section_payload("2.015 future"),
    }

    async def _frontier(urls, **_kwargs) -> list[bytes]:
        return [pages[url] for url in urls]

    async def _extract(*, source_url: str, raw_bytes: bytes) -> dict[str, str]:
        assert raw_bytes == pages[source_url]
        return {
            "text": f"KRS 2.015 Complete official source record {source_url}.",
            "method": "test_html",
        }

    monkeypatch.setattr(scraper, "_fetch_official_ky_frontier", _frontier)
    monkeypatch.setattr(scraper, "_extract_text_from_document_bytes", _extract)

    statutes = await scraper._scrape_official_krs_tree_batched(
        code_name="Kentucky Revised Statutes",
        chapter_units=chapter_units,
    )

    assert [row.section_number for row in statutes] == ["2.015", "2.015"]
    assert [row.source_url for row in statutes] == concurrent_urls
    assert [row.statute_id for row in statutes] == [
        "KRS-2.015:record:kentucky-statute-101",
        "KRS-2.015:record:kentucky-statute-102",
    ]
    assert {
        row.structured_data["source_record_id"] for row in statutes
    } == {"kentucky-statute-101", "kentucky-statute-102"}
    assert all(
        row.structured_data["printed_statute_id"] == "KRS-2.015"
        and row.structured_data["concurrent_source_record_count"] == 2
        for row in statutes
    )
    assert scraper._last_kentucky_full_frontier["concurrent_section_groups"] == 1
    assert scraper._last_kentucky_full_frontier["concurrent_source_records"] == 2


def test_kentucky_source_record_identity_rejects_locator_drift() -> None:
    scraper = KentuckyScraper("KY", "Kentucky")

    assert (
        scraper._source_record_id_from_section_url(SECTION_URLS[0])
        == "kentucky-statute-101"
    )
    for drifted in (
        "https://example.test/law/statutes/statute.aspx?id=101",
        "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=101&view=1",
        "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=101#body",
        "https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=abc",
    ):
        with pytest.raises(RuntimeError, match="exact official source-record identity"):
            scraper._source_record_id_from_section_url(drifted)


def test_kentucky_root_parser_keeps_nested_units_and_evidence_rules() -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    html = """
    <a href="chapter.aspx?id=39344">Chapter titles, centered headings, section
      catchlines, and explanatory notes are for informational purposes only and
      do not constitute any part of the law. For general laws governing
      construction of statutes, see KRS Chapter 446.</a>
    <a href="chapter.aspx?id=37087">CHAPTER 14A KENTUCKY BUSINESS ENTITY FILING ACT</a>
    <a href="chapter.aspx?id=37088">Subchapter 1. General Provisions</a>
    <a href="chapter.aspx?id=37089">Subchapter 2. Filing Requirements</a>
    <a href="chapter.aspx?id=37097">CHAPTER 15 DEPARTMENT OF LAW</a>
    <a href="chapter.aspx?id=39436">KENTUCKY RULES OF EVIDENCE</a>
    """

    units = scraper._chapter_units_from_html(html)

    assert [unit["unit_kind"] for unit in units] == [
        "chapter",
        "subchapter",
        "subchapter",
        "chapter",
        "rules",
    ]
    assert units[0]["is_structural_container"] is True
    assert units[1]["chapter_number"] == "14A"
    assert units[1]["chapter_label"] == (
        "CHAPTER 14A KENTUCKY BUSINESS ENTITY FILING ACT"
    )
    assert units[-1]["chapter_number"] == "KRE"


@pytest.mark.anyio
async def test_kentucky_unbounded_tree_traverses_structural_container_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    _disable_checkpoints(scraper)
    parent_label = "CHAPTER 14A KENTUCKY BUSINESS ENTITY FILING ACT"
    child_label = "Subchapter 1. General Provisions"
    chapter_units = [
        _chapter_unit(CHAPTER_URLS[0], parent_label, "14A", container=True),
        _chapter_unit(
            CHAPTER_URLS[1],
            child_label,
            "14A",
            kind="subchapter",
            parent_label=parent_label,
        ),
    ]
    pages = {
        CHAPTER_URLS[0]: b"<html><body>Kentucky Revised Statutes parent chapter.</body></html>",
        CHAPTER_URLS[1]: _chapter_payload((201, ".1-010 Short title.")),
        SECTION_URLS[2]: _section_payload("14A.1-010"),
    }

    async def _frontier(urls, **_kwargs) -> list[bytes]:
        return [pages[url] for url in urls]

    async def _extract(*, source_url: str, raw_bytes: bytes) -> dict[str, str]:
        assert raw_bytes == pages[source_url]
        return {
            "text": "KRS 14A.1-010 Complete official Kentucky statutory text.",
            "method": "test_html",
        }

    monkeypatch.setattr(scraper, "_fetch_official_ky_frontier", _frontier)
    monkeypatch.setattr(scraper, "_extract_text_from_document_bytes", _extract)

    statutes = await scraper._scrape_official_krs_tree_batched(
        code_name="Kentucky Revised Statutes",
        chapter_units=chapter_units,
    )

    assert len(statutes) == 1
    assert statutes[0].section_number == "14A.1-010"
    assert statutes[0].chapter_name == f"{parent_label} -- {child_label}"
    assert scraper._last_kentucky_full_frontier[
        "structural_container_exclusions"
    ] == [
        {
            "chapter_label": parent_label,
            "chapter_number": "14A",
            "disposition": "structural_container",
            "source_url": CHAPTER_URLS[0],
        }
    ]


@pytest.mark.anyio
async def test_kentucky_evidence_rule_keeps_distinct_citation_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")

    async def _extract(**_kwargs) -> dict[str, str]:
        return {
            "text": "Rule 101 Scope. These rules govern proceedings in Kentucky courts.",
            "method": "test_html",
        }

    monkeypatch.setattr(scraper, "_extract_text_from_document_bytes", _extract)
    statute = await scraper._build_statute_from_section_bytes(
        code_name="Kentucky Revised Statutes",
        section_url=SECTION_URLS[0],
        section_label=".101 Rule 101 Scope",
        section_number="KRE.101",
        chapter_url=CHAPTER_URLS[0],
        chapter_label="KENTUCKY RULES OF EVIDENCE",
        chapter_number="KRE",
        raw_bytes=_section_payload("KRE.101"),
        require_extracted_text=True,
    )

    assert statute is not None
    assert statute.statute_id == "KRE-101:record:kentucky-statute-101"
    assert statute.code_name == "Kentucky Rules of Evidence"
    assert statute.official_cite == "Ky. R. Evid. 101"
    assert statute.structured_data["source_kind"] == (
        "official_kentucky_rules_of_evidence_pdf"
    )


@pytest.mark.anyio
async def test_kentucky_unbounded_tree_requires_typed_empty_chapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    _disable_checkpoints(scraper)
    chapter_units = [
        _chapter_unit(CHAPTER_URLS[0], "CHAPTER 1 GENERAL PROVISIONS", "1")
    ]

    async def _frontier(urls, **_kwargs) -> list[bytes]:
        assert list(urls) == CHAPTER_URLS[:1]
        return [b"<html><body>Kentucky Revised Statutes chapter page.</body></html>"]

    monkeypatch.setattr(scraper, "_fetch_official_ky_frontier", _frontier)

    with pytest.raises(RuntimeError, match="no section frontier and no typed"):
        await scraper._scrape_official_krs_tree_batched(
            code_name="Kentucky Revised Statutes",
            chapter_units=chapter_units,
        )


@pytest.mark.anyio
async def test_kentucky_closure_replays_every_retained_page_without_network(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = KentuckyScraper("KY", "Kentucky")
    _disable_checkpoints(scraper)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="KY",
        parser_name="KentuckyScraper",
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    root_url = scraper._KY_STATUTES_BASE
    root_payload = (
        b"<html><body><h1>Kentucky Revised Statutes</h1>"
        b"<a href='chapter.aspx?id=1'>CHAPTER 1 GENERAL PROVISIONS</a>"
        b"<a href='chapter.aspx?id=2'>CHAPTER 2 PUBLIC ADMINISTRATION</a>"
        b"</body></html>"
    )
    pages = {
        root_url: root_payload,
        CHAPTER_URLS[0]: _chapter_payload(
            (101, ".010 Legislative intent."),
            (102, ".020 Definitions."),
        ),
        CHAPTER_URLS[1]: _chapter_payload((201, ".010 Public administration.")),
        SECTION_URLS[0]: _section_payload("1.010"),
        SECTION_URLS[1]: _section_payload("1.020"),
        SECTION_URLS[2]: _section_payload("2.010"),
    }
    initial_calls: list[tuple[str, list[str]]] = []

    async def _frontier(urls, *, frontier_name: str, content_validator, **_kwargs):
        requested = list(urls)
        initial_calls.append((frontier_name, requested))
        payloads = [pages[url] for url in requested]
        for url, payload in zip(requested, payloads, strict=True):
            assert content_validator(payload)
            ledger.retain_parser_input(
                official_url=url,
                body=payload,
                transport_receipt={
                    "content_sha256": hashlib.sha256(payload).hexdigest(),
                    "official_url": url,
                    "source_transport": "direct",
                },
                retrieved_at="2026-08-25T00:00:00+00:00",
                sanitized_request={"method": "GET", "url": url},
            )
        return payloads

    async def _extract(*, source_url: str, raw_bytes: bytes) -> dict[str, str]:
        assert raw_bytes == pages[source_url]
        section_number = {
            SECTION_URLS[0]: "1.010",
            SECTION_URLS[1]: "1.020",
            SECTION_URLS[2]: "2.010",
        }[source_url]
        return {
            "text": (
                f"KRS {section_number} Complete official Kentucky statutory text "
                "retained for exact replay and publication."
            ),
            "method": "test_html",
        }

    monkeypatch.setattr(scraper, "_fetch_official_ky_frontier", _frontier)
    monkeypatch.setattr(scraper, "_extract_text_from_document_bytes", _extract)
    rows = await scraper._scrape_official_krs_tree(
        "Kentucky Revised Statutes",
        max_statutes=None,
    )
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="KY",
    )

    async def _forbid_network(*_args, **_kwargs):
        raise AssertionError("Kentucky closure must not call the network fetch path")

    monkeypatch.setattr(scraper, "_fetch_official_ky_frontier", _forbid_network)
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["official-krs"],
    )
    closure_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    receipt = closure["completion_receipt"]

    assert initial_calls == [
        ("root-index", [root_url]),
        ("chapter-index", CHAPTER_URLS),
        ("section", SECTION_URLS),
    ]
    assert len(ledger.entries) == len(pages)
    assert receipt["disposition"] == {
        "discovered": 3,
        "duplicates": 0,
        "excluded": 0,
        "failed_final": 0,
        "fetched": 3,
        "quarantined": 0,
    }
    assert receipt["rights"]["basis"] == "public_law_no_state_copyright"
    assert receipt["frontier"]["leaf_acquisition_wave_count"] == 1
    assert receipt["frontier"]["request_batch_count"] == 3
    assert receipt["frontier"]["section_parse_batch_count"] == 1
    assert receipt["transport"]["grouped_warc_recovery"] is True
    assert receipt["transport"]["per_page_archive_loop"] is False
    assert receipt["transport"]["residual_only_retries"] is True
    assert receipt["transport"]["retained_replay_network_requests"] == 0
    assert receipt["frontier"] == closure["replayed_frontier"]
