from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah import (
    UtahScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.utah_title_xml import (
    parse_utah_title_xml_frontier_document,
    root_versioned_html_url,
    title_xml_frontier_from_root_html,
)

WRAPPER = """
<html><script>
var versionArr = [['C_2026082520260825.html', 'Current Version']];
var versionDefault = "C_2026082520260825";
</script></html>
"""
ROOT_URL = "https://le.utah.gov/xcode/C_2026082520260825.html"
ROOT = """
<html><body><table id="childtbl">
<tr><td><a href="Title3/3.html?v=C3_1800010118000101">Title 3</a></td>
<td>Uniform Agricultural Cooperative Association Act</td></tr>
<tr><td><a href="Title16/16.html?v=C16_1800010118000101">Title 16</a></td>
<td>Corporations <i>(Superseded 10/1/2026)</i></td></tr>
<tr><td><a href="Title16/16.html?v=C16_2026050620261001">Title 16</a></td>
<td>Business Entities <i>(Effective 10/1/2026)</i></td></tr>
</table></body></html>
"""
TITLE3_XML = b"""
<title number="3"><catchline>Uniform Agricultural Cooperative Association Act</catchline>
<chapter number="3-1"><catchline>General Provisions</catchline>
<section number="3-1-1"><histories><history>Enacted by Chapter 1, 2025 General Session</history>
<modyear>2025</modyear></histories><catchline>Policy.</catchline>
This is complete operative Utah statutory text for the first synthetic title.</section>
</chapter></title>
"""
TITLE16_OLD_XML = b"""
<title number="16"><enddate type="SC">10/1/2026</enddate><catchline>Corporations</catchline>
<chapter number="16-1"><catchline>Corporation Provisions</catchline>
<section number="16-1-1"><enddate type="SC">10/1/2026</enddate>
<catchline>Current provision.</catchline>This complete provision remains operative until October.</section>
<section number="16-1-1"><effdate>10/1/2026</effdate>
<catchline>Replacement provision.</catchline>This complete replacement is not effective yet.</section>
</chapter></title>
"""
TITLE16_NEW_XML = b"""
<title number="16"><effdate>10/1/2026</effdate><catchline>Business Entities</catchline></title>
"""


def _aligned_result(
    urls: list[str],
    payload_by_url: dict[str, bytes],
    *,
    retained_replay: bool = False,
) -> StateLawPageMultiFetchResult:
    payloads = [payload_by_url.get(url, b"") for url in urls]
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=payloads,
        errors=[None if payload else "missing synthetic page" for payload in payloads],
        transport_receipts=[
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "source_transport": "synthetic-test",
            }
            if payload
            else None
            for url, payload in zip(urls, payloads, strict=True)
        ],
        parser_input_envelopes=[
            SimpleNamespace(body=payload) if payload else None for payload in payloads
        ],
        stats={
            "requested_pages": len(urls),
            "network_requested_pages": 0 if retained_replay else len(urls),
            "retained_replay_pages": len(urls) if retained_replay else 0,
            "common_crawl": {
                "range_fetch_calls": 0,
                "range_fetches_avoided": 0,
            },
        },
    )


def test_root_inventory_is_source_derived_and_temporally_exact() -> None:
    assert root_versioned_html_url(WRAPPER) == ROOT_URL

    before = title_xml_frontier_from_root_html(
        ROOT,
        root_url=ROOT_URL,
        as_of_date="2026-08-25",
    )
    assert len(before) == 3
    assert [(row.title_number, row.disposition) for row in before] == [
        ("3", "active"),
        ("16", "active"),
        ("16", "not_yet_effective"),
    ]
    assert before[0].xml_url == (
        "https://le.utah.gov/xcode/Title3/C3_1800010118000101.xml"
    )
    assert before[1].superseded_date == "2026-10-01"
    assert before[2].effective_date == "2026-10-01"

    after = title_xml_frontier_from_root_html(
        ROOT,
        root_url=ROOT_URL,
        as_of_date="2026-10-01",
    )
    assert [(row.title_number, row.disposition) for row in after] == [
        ("3", "active"),
        ("16", "superseded"),
        ("16", "active"),
    ]

    duplicate_active = ROOT.replace("(Effective 10/1/2026)", "")
    with pytest.raises(ValueError, match="multiple active versions"):
        title_xml_frontier_from_root_html(
            duplicate_active,
            root_url=ROOT_URL,
            as_of_date="2026-08-25",
        )


def test_title_xml_parser_classifies_temporal_and_cross_title_nodes() -> None:
    payload = b"""
    <title number="16"><enddate type="SC">10/1/2026</enddate><catchline>Corporations</catchline>
      <chapter number="16-1"><catchline>Corporation Provisions</catchline>
        <section number="16-1-1"><enddate>10/1/2026</enddate><catchline>Current.</catchline>
        This complete old section is operative before the transition.</section>
        <section number="16-1-1"><effdate>10/1/2026</effdate><catchline>Future.</catchline>
        This complete replacement section is not operative yet.</section>
        <section number="16-1-2"><catchline>Repealed.</catchline>Repealed.</section>
        <section number="3-1-1"><catchline>Embedded quotation.</catchline>
        This section belongs to another title and cannot enter Title 16.</section>
      </chapter>
    </title>
    """
    result = parse_utah_title_xml_frontier_document(
        payload,
        expected_title_number="16",
        expected_title_name="Corporations",
        source_url="https://le.utah.gov/xcode/Title16/C16_1800010118000101.xml",
        as_of_date="2026-08-25",
    )

    assert result.discovered_section_count == 4
    assert [row.section_number for row in result.rows] == ["16-1-1"]
    assert [row["disposition"] for row in result.terminal_sections] == [
        "not_yet_effective",
        "repealed",
    ]
    assert result.excluded_sections[0]["reason"] == "embedded_cross_title_section"
    assert result.duplicate_sections == ()
    assert result.residual_sections == ()
    assert result.rows[0].full_text.endswith("before the transition.")

    malformed = payload.replace(b'number="3-1-1"', b'number=""')
    residual = parse_utah_title_xml_frontier_document(
        malformed,
        expected_title_number="16",
        expected_title_name="Corporations",
        source_url="https://le.utah.gov/xcode/Title16/C16_1800010118000101.xml",
        as_of_date="2026-08-25",
    )
    assert residual.residual_sections[0]["reason"] == "missing_section_identity"


@pytest.mark.anyio
async def test_strict_title_xml_frontier_plural_fetches_and_replays_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locators = title_xml_frontier_from_root_html(
        ROOT,
        root_url=ROOT_URL,
        as_of_date="2026-08-25",
    )
    payloads = {
        UtahScraper.OFFICIAL_ENTRY_URL: WRAPPER.encode(),
        ROOT_URL: ROOT.encode(),
        locators[0].xml_url: TITLE3_XML,
        locators[1].xml_url: TITLE16_OLD_XML,
        locators[2].xml_url: TITLE16_NEW_XML,
    }
    plural_calls: list[tuple[list[str], dict[str, object]]] = []

    async def _plural(
        urls: list[str],
        **kwargs: object,
    ) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        plural_calls.append((requested, dict(kwargs)))
        return _aligned_result(
            requested,
            payloads,
            retained_replay=scraper._state_law_acquisition_ledger is not None,
        )

    scraper = UtahScraper("UT", "Utah")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    rows = await scraper._scrape_strict_official_title_xml_frontier(
        code_name="Utah Code",
        as_of_date="2026-08-25",
    )

    assert len(plural_calls) == 3
    assert plural_calls[0][0] == [UtahScraper.OFFICIAL_ENTRY_URL]
    assert plural_calls[1][0] == [ROOT_URL]
    assert plural_calls[2][0] == [row.xml_url for row in locators]
    assert plural_calls[2][1]["media_type"] == "application/xml"
    assert [row.section_number for row in rows] == ["3-1-1", "16-1-1"]
    assert all(row.structured_data["content_sha256"] for row in rows)
    closure = scraper._last_utah_strict_closure
    assert closure["closed"] is True
    assert closure["source_title_row_count"] == 3
    assert closure["active_title_count"] == 2
    assert closure["terminal_title_count"] == 1
    assert closure["title_xml_transport_count"] == 3
    assert closure["document_disposition"] == {
        "discovered": 3,
        "fetched": 2,
        "excluded": 1,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }
    assert closure["section_disposition"] == {
        "discovered": 3,
        "fetched": 2,
        "excluded": 1,
        "failed_final": 0,
        "duplicates": 0,
        "quarantined": 0,
    }

    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="UT",
    )
    retained: dict[str, object] = {}

    def _evidence(**kwargs: object) -> dict[str, object]:
        body = bytes(kwargs["payload"])
        return {
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "parser_input_receipt_sha256": "a" * 64,
            "source_retrieved_at": "2026-08-25T00:00:00+00:00",
            "source_transport": "direct",
            "source_transport_chain": ["direct"],
            "transport_receipt": {},
        }

    def _retain(completion: dict[str, object], **kwargs: object) -> Path:
        retained["completion"] = completion
        retained["kwargs"] = kwargs
        return Path("/synthetic/STATE-UT.frontier-closure.json")

    scraper._state_law_acquisition_ledger = object()
    monkeypatch.setattr(scraper, "_utah_input_evidence_context", _evidence)
    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert retained_path == Path("/synthetic/STATE-UT.frontier-closure.json")
    assert len(plural_calls) == 6
    for index in range(3):
        assert plural_calls[3 + index][0] == plural_calls[index][0]
    completion = retained["completion"]
    assert completion["disposition"] == closure["section_disposition"]
    assert completion["frontier"] == retained["kwargs"]["replayed_frontier"]
    assert completion["rights"] == {
        "basis": "public_law_no_state_copyright",
        "decision": "admit",
        "scope": "statutory_text",
    }
    assert completion["replay"]["network_requests"] == 0
    assert completion["replay"]["retained_parser_inputs"] == 5
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    assert completion["transport"]["retained_replay_network_requests"] == 0
    assert completion["transport"]["retained_replay_pages"] == 5
    assert completion["transport"]["first_pass_batch_stats"]["title_xml"][
        "requested_pages"
    ] == 3
    assert completion["transport"]["replay_batch_stats"]["title_xml"] == {
        "requested_pages": 3,
        "network_requested_pages": 0,
        "retained_replay_pages": 3,
        "common_crawl": {
            "range_fetch_calls": 0,
            "range_fetches_avoided": 0,
        },
    }

    async def _network_replay(
        urls: list[str],
        **_kwargs: object,
    ) -> StateLawPageMultiFetchResult:
        requested = list(urls)
        return _aligned_result(requested, payloads, retained_replay=False)

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _network_replay,
    )
    with pytest.raises(RuntimeError, match="zero-network retained input parity"):
        await scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )


@pytest.mark.anyio
async def test_bounded_utah_path_does_not_invoke_strict_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = UtahScraper("UT", "Utah")
    expected = NormalizedStatute(
        state_code="UT",
        state_name="Utah",
        statute_id="Utah Code § 3-1-1",
        code_name="Utah Code",
        section_number="3-1-1",
        source_url="https://le.utah.gov/xcode/Title3/example.xml",
        full_text="Complete bounded official Utah statutory text.",
    )

    async def _strict(**_kwargs: object) -> list[object]:
        raise AssertionError("bounded Utah scrape must not invoke strict frontier")

    async def _bounded(_code_name: str, max_statutes: int) -> list[object]:
        assert max_statutes >= 10
        return [expected]

    monkeypatch.delenv("STATE_SCRAPER_FULL_CORPUS", raising=False)
    monkeypatch.setattr(scraper, "_scrape_strict_official_title_xml_frontier", _strict)
    monkeypatch.setattr(scraper, "_scrape_official_xml_code_tree", _bounded)

    rows = await scraper.scrape_code(
        "Utah Code",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=1,
    )
    assert rows == [expected]
