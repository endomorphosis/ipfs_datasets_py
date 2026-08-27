"""Exact retained-input lifecycle coverage for the 2026 Florida Statutes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida import (
    FloridaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.florida_chapter import (
    band_for,
    chapter_number_from_url,
    chapter_page_url,
    padded,
    section_page_url,
)


def _retain_html(
    ledger: StateLawMultiFetchAcquisitionLedger,
    scraper: FloridaScraper,
    *,
    url: str,
    body: bytes,
    retrieved_at: str,
) -> None:
    ledger.retain_parser_input(
        official_url=url,
        body=body,
        transport_receipt={
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "official_url": url,
            "source_transport": "direct",
        },
        retrieved_at=retrieved_at,
        media_type="text/html",
        sanitized_request={
            "headers": {"Accept": scraper._PARSER_ACCEPT},
            "method": "GET",
            "url": url,
        },
    )


def _retained_2026_fixture(
    tmp_path: Path,
) -> tuple[FloridaScraper, StateLawMultiFetchAcquisitionLedger]:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="FL",
        parser_name="FloridaScraper",
    )
    scraper = FloridaScraper("FL", "Florida")
    scraper.attach_state_law_acquisition_ledger(ledger)

    root_links = "".join(
        f"<a href='{scraper.official_title_url(roman)}'>Title {roman}</a>"
        for _number, roman, _name in scraper.OFFICIAL_TITLES
    )
    _retain_html(
        ledger,
        scraper,
        url=scraper.OFFICIAL_ENTRY_URL,
        body=f"<h1>The 2026 Florida Statutes</h1>{root_links}".encode(),
        retrieved_at="2026-08-25T20:00:00Z",
    )

    terminal_markers = (
        ("1.90", "[Repealed.]"),
        ("1.91", "[Reserved.]"),
        ("1.92", "[Expired.]"),
        ("1.93", "[Transferred.]"),
        ("1.94", "[Renumbered.]"),
        ("1.95", "[Former.]"),
    )
    for title_number, roman, title_name in scraper.OFFICIAL_TITLES:
        chapter = str(int(title_number))
        chapter_url = chapter_page_url(chapter)
        title_url = scraper.official_title_url(roman)
        chapter_contents = (
            f"index.cfm?App_mode=Display_Statute&amp;URL={band_for(chapter)}/"
            f"{padded(chapter)}/{padded(chapter)}ContentsIndex.html"
        )
        _retain_html(
            ledger,
            scraper,
            url=title_url,
            body=(
                f"<a href='{chapter_contents}'>Chapter {chapter}</a>"
            ).encode(),
            retrieved_at="2026-08-25T20:01:00Z",
        )

        active = (
            "<div class='Section'>"
            f"<span class='SectionNumber'>{chapter}.01</span>"
            "<span class='CatchlineText'>Operative law.</span>"
            f"<span class='SectionBody'>Florida law for title {title_number}.</span>"
            "</div>"
        )
        terminals = ""
        if title_number == "1":
            terminals = "".join(
                "<div class='Section'>"
                f"<span class='SectionNumber'>{section}</span>"
                f"<span class='CatchlineText'>{marker}</span>"
                "</div>"
                for section, marker in terminal_markers
            )
        chapter_html = (
            f"<div class='TitleNumber'>Title {roman}</div>"
            f"<div class='TitleName'>{title_name}</div>"
            f"<div class='ChapterNumber'>Chapter {chapter}</div>"
            f"<div class='ChapterName'>Fixture chapter {chapter}</div>"
            f"{active}{terminals}"
        ).encode()
        _retain_html(
            ledger,
            scraper,
            url=chapter_url,
            body=chapter_html,
            retrieved_at="2026-08-25T20:02:00Z",
        )
    return scraper, ledger


def test_florida_retained_2026_root_title_chapter_section_frontier_closes(
    tmp_path: Path,
) -> None:
    scraper, ledger = _retained_2026_fixture(tmp_path)

    rows, observation = scraper._replay_exact_retained_florida_frontier(
        "Florida Statutes",
        record_primary=True,
    )

    frontier = observation["frontier"]
    assert len(ledger.entries) == 99
    assert len(rows) == 49
    assert frontier["root_document_count"] == 1
    assert frontier["title_document_count"] == 49
    assert frontier["chapter_document_count"] == 49
    assert frontier["parser_input_count"] == 99
    assert frontier["source_section_count"] == 55
    assert frontier["disposition"] == {
        "discovered": 55,
        "duplicates": 0,
        "excluded": 6,
        "failed_final": 0,
        "fetched": 49,
        "quarantined": 0,
    }
    assert frontier["terminal_dispositions"] == {
        "expired": 1,
        "former": 1,
        "renumbered": 1,
        "repealed": 1,
        "reserved": 1,
        "transferred": 1,
    }
    assert observation["source_observation"] == {
        "first_retrieved_at": "2026-08-25T20:00:00Z",
        "last_retrieved_at": "2026-08-25T20:02:00Z",
        "unique_parser_input_count": 99,
    }
    assert observation["edition"] == "2026"
    assert observation["legal_as_of"] == "2026-07-01T00:00:00Z"
    assert observation["operative_canonical_keys"] == [
        f"urn:state:fl:statute:FL-{number}.01" for number in range(1, 50)
    ]
    assert set(observation["operative_canonical_keys"]).isdisjoint(
        observation["terminal_canonical_keys"]
    )


@pytest.mark.anyio
async def test_florida_closure_is_zero_network_ordered_and_policy_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper, _ledger = _retained_2026_fixture(tmp_path)
    rows, observation = scraper._replay_exact_retained_florida_frontier(
        "Florida Statutes",
        record_primary=True,
    )
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="FL",
    )
    retained: dict[str, object] = {}

    async def _forbid_network(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("Florida retained closure must make zero network calls")

    def _retain(completion: dict[str, object], **kwargs: object) -> Path:
        retained["completion"] = completion
        retained["kwargs"] = kwargs
        return tmp_path / "STATE-FL.frontier-closure.json"

    monkeypatch.setattr(scraper, "_fetch_parser_input_with_transport", _forbid_network)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
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
        lambda _url: ["fl-leg-statutes"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "florida-test@sha256:" + ("f" * 64),
    )

    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert retained_path == tmp_path / "STATE-FL.frontier-closure.json"
    completion = retained["completion"]
    assert isinstance(completion, dict)
    assert completion["disposition"] == observation["frontier"]["disposition"]
    assert completion["edition"] == "2026"
    assert completion["observed_at"] == "2026-08-25T20:02:00Z"
    assert completion["legal_as_of"] == "2026-07-01T00:00:00Z"
    assert completion["replay"]["network_requests"] == 0
    assert completion["rights"] == {
        "basis": "public_law_no_state_copyright",
        "decision": "admit",
        "scope": "statutory_text",
    }
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    assert completion["transport"]["retained_source_observation"] == (
        observation["source_observation"]
    )
    assert completion["boundary_probes"]["bundle_total"] == 99
    assert completion["boundary_probes"]["pagination_total"] == 98
    assert retained["kwargs"]["replayed_frontier"] == observation["frontier"]

    reordered = {
        **projection,
        "canonical_keys": list(reversed(projection["canonical_keys"])),
    }
    with pytest.raises(RuntimeError, match="canonical identities do not exactly match"):
        await scraper.produce_state_law_frontier_closure(
            canonical_output_projection=reordered,
        )


@pytest.mark.anyio
async def test_florida_strict_acquisition_batches_titles_and_chapters_by_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = FloridaScraper("FL", "Florida")
    batch_calls: list[tuple[str, list[str]]] = []

    async def _titles(_code_url: str) -> list[tuple[str, str]]:
        return [
            (scraper.official_title_url(roman), f"Title {roman}")
            for _number, roman, _name in scraper.OFFICIAL_TITLES
        ]

    async def _grouped(
        urls: list[str],
        *,
        frontier_name: str,
    ) -> dict[str, tuple[bytes, object, object]]:
        batch_calls.append((frontier_name, list(urls)))
        if frontier_name == "title-catalog":
            payloads: dict[str, tuple[bytes, object, object]] = {}
            for position, url in enumerate(urls, start=1):
                chapter = str(position)
                href = (
                    "index.cfm?App_mode=Display_Statute&amp;URL="
                    f"{band_for(chapter)}/{padded(chapter)}/"
                    f"{padded(chapter)}ContentsIndex.html"
                )
                payloads[url] = (
                    f"<a href='{href}'>Chapter {chapter}</a>".encode(),
                    object(),
                    object(),
                )
            return payloads
        return {
            url: (b"<html>chapter parser input</html>", object(), object())
            for url in urls
        }

    async def _parse(
        *,
        code_name: str,
        chapter_url: str,
        chapter_label: str,
        max_statutes: int | None = None,
        _acquired_payload: bytes | None = None,
        _acquired_transport_receipt: object = None,
        _acquired_parser_input_envelope: object = None,
    ) -> list[NormalizedStatute]:
        del chapter_label, max_statutes
        assert _acquired_payload == b"<html>chapter parser input</html>"
        assert _acquired_transport_receipt is not None
        assert _acquired_parser_input_envelope is not None
        chapter = chapter_number_from_url(chapter_url)
        return [
            NormalizedStatute(
                state_code="FL",
                state_name="Florida",
                statute_id=f"FL-{chapter}.01",
                code_name=code_name,
                chapter_number=chapter,
                section_number=f"{chapter}.01",
                section_name="Operative law",
                full_text="Florida law.",
                source_url=section_page_url(chapter, f"{chapter}.01"),
                official_cite=f"Fla. Stat. § {chapter}.01",
                structured_data={"source_authority_class": "official"},
            )
        ]

    async def _forbid_scalar(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("strict Florida hierarchy must not use a per-page loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_discover_title_links", _titles)
    monkeypatch.setattr(scraper, "_fetch_official_fl_html_frontier", _grouped)
    monkeypatch.setattr(scraper, "_discover_chapter_links", _forbid_scalar)
    monkeypatch.setattr(scraper, "_fetch_official_fl_html", _forbid_scalar)
    monkeypatch.setattr(scraper, "_parse_chapter_sections", _parse)

    rows = await scraper.scrape_code(
        "Florida Statutes",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert len(rows) == 49
    assert [(name, len(urls)) for name, urls in batch_calls] == [
        ("title-catalog", 49),
        ("chapter-page", 49),
    ]
    assert scraper._last_full_corpus_frontier["closed"] is True
