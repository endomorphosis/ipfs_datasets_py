from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import (
    MississippiDelegatedCorpusBlockedError,
    MississippiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi_section import (
    parse_mississippi_section_html_strict,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_carolina import (
    SouthCarolinaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.south_carolina_chapter import (
    parse_south_carolina_chapter_html_strict,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.tennessee import (
    TennesseeScraper,
)


def _receipt(url: str, payload: bytes) -> dict[str, str]:
    return {
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "official_url": url,
        "source_transport": "direct",
    }


def _envelope(url: str, payload: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "acquisition": {
            "body_sha256": digest,
            "receipt": {
                "content": {"sha256": digest},
                "endpoint": url,
                "receipt_sha256": "a" * 64,
            },
        }
    }


def _batch(
    urls: list[str],
    payload_by_url: dict[str, bytes],
    *,
    with_envelopes: bool = True,
) -> StateLawPageMultiFetchResult:
    payloads = [payload_by_url[url] for url in urls]
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=payloads,
        errors=[None] * len(urls),
        transport_receipts=[
            _receipt(url, payload)
            for url, payload in zip(urls, payloads, strict=True)
        ],
        parser_input_envelopes=(
            [
                _envelope(url, payload)
                for url, payload in zip(urls, payloads, strict=True)
            ]
            if with_envelopes
            else [None] * len(urls)
        ),
        stats={
            "network_requested_pages": 0,
            "requested_pages": len(urls),
            "retained_replay_pages": len(urls),
        },
    )


def _sc_master(scraper: SouthCarolinaScraper) -> bytes:
    links = "".join(
        f"<a href='/code/title{int(number)}.php'>Title {int(number)}</a>"
        for number, _name in scraper.OFFICIAL_TITLES
    )
    return f"<html><body>{links}</body></html>".encode()


def _sc_title(scraper: SouthCarolinaScraper, title: str) -> bytes:
    chapter_url = (
        f"/code/t{int(title):02d}c001.php"
    )
    return (
        "<html><body><div id='contentsection'>"
        f"<div>Title {int(title)} - TEST</div>"
        f"<a href='{chapter_url}'>CHAPTER 1</a>"
        "</div></body></html>"
    ).encode()


def _sc_chapter(title: str) -> bytes:
    unit = "ARTICLE" if int(title) == 62 else "CHAPTER"
    return (
        "<html><body><div id='contentsection'>"
        f"<div>Title {int(title)} - TEST</div><div>{unit} 1</div>"
        f"<span style='font-weight: bold;'>SECTION {int(title)}-1-1.</span>"
        " TEST SECTION.<br/>"
        "This official South Carolina provision supplies an operative body."
        "<br/>HISTORY: synthetic retained-parser fixture."
        "</div></body></html>"
    ).encode()


def test_south_carolina_strict_parser_types_versions_containers_and_terminals() -> None:
    html = """
    <html><body><div id="contentsection">
      <div>Title 1 - TEST</div><div>CHAPTER 1</div>
      <span style="font-weight: bold;">SECTION 1-1-10.</span>
      First version.<br/>Section effective until January 1, 2027.<br/>
      This first concurrent version remains source-bound and operative.<br/>
      <span style="font-weight: bold;">SECTION 1-1-10.</span>
      Second version.<br/>Section effective January 1, 2027.<br/>
      This second concurrent version also remains source-bound and operative.<br/>
      <span style="font-weight: bold;">SECTION 1-1-20.</span>
      Split heading only.<br/>
      <span style="font-weight: bold;">SECTION 1-1-20.</span>
      Operative continuation.<br/>This is the actual operative split section.<br/>
      <span style="font-weight: bold;">SECTION 1-1-30.</span>
      Repealed.<br/>HISTORY: repealed by official act.<br/>
    </div></body></html>
    """

    rows, report = parse_south_carolina_chapter_html_strict(
        html,
        source_url="https://www.scstatehouse.gov/code/t01c001.php",
        code_name="South Carolina Code of Laws",
        title_number="1",
        chapter_number="1",
    )

    assert report["closed"] is True
    assert report["candidate_sections"] == 5
    assert report["operative_sections"] == 3
    assert report["terminal_sections"] == 2
    assert {row["disposition"] for row in report["terminal_dispositions"]} == {
        "repealed",
        "split_heading_container",
    }
    assert len({row.statute_id for row in rows}) == 3
    assert len(
        {row.structured_data["canonical_section_key"] for row in rows}
    ) == 3


def test_south_carolina_strict_parser_closes_unbolded_and_empty_terminal_pages() -> None:
    raw_rows, raw_report = parse_south_carolina_chapter_html_strict(
        "<html><body><div id='contentsection'>Title 13 - TEST<br/>"
        "CHAPTER 13<br/>\nSECTION 13-13-10. Compact agreement.\n"
        "The interstate compact is enacted as operative South Carolina law."
        "</div></body></html>",
        source_url="https://www.scstatehouse.gov/code/t13c013.php",
        code_name="South Carolina Code of Laws",
        title_number="13",
        chapter_number="13",
    )
    terminal_rows, terminal_report = parse_south_carolina_chapter_html_strict(
        "<html><body><div id='contentsection'>Title 5 - TEST "
        "CHAPTER 23 Zoning and Planning [Repealed] "
        "Repealed by an official act.</div></body></html>",
        source_url="https://www.scstatehouse.gov/code/t05c023.php",
        code_name="South Carolina Code of Laws",
        title_number="5",
        chapter_number="23",
    )

    assert len(raw_rows) == 1
    assert raw_report["closed"] is True
    assert raw_report["candidate_sections"] == 1
    assert terminal_rows == []
    assert terminal_report["closed"] is True
    assert terminal_report["chapter_disposition"] == "repealed_chapter"


@pytest.mark.anyio
async def test_south_carolina_full_route_uses_two_exact_plural_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SouthCarolinaScraper("SC", "South Carolina")
    payloads = {scraper.OFFICIAL_ENTRY_URL: _sc_master(scraper)}
    for title, _name in scraper.OFFICIAL_TITLES:
        payloads[scraper.official_title_url(title)] = _sc_title(scraper, title)
        chapter_url = (
            f"{scraper.get_base_url()}/code/t{int(title):02d}c001.php"
        )
        payloads[chapter_url] = _sc_chapter(title)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(urls: list[str], **kwargs: Any) -> StateLawPageMultiFetchResult:
        calls.append((list(urls), dict(kwargs)))
        return _batch(list(urls), payloads)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: None)

    rows = await scraper.scrape_code(
        "South Carolina Code of Laws",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert len(calls) == 2
    assert calls[0][0] == [
        scraper.OFFICIAL_ENTRY_URL,
        *[
            scraper.official_title_url(number)
            for number, _name in scraper.OFFICIAL_TITLES
        ],
    ]
    assert len(calls[1][0]) == scraper.OFFICIAL_TITLE_COUNT == 63
    assert all(call[1]["wayback_prefix_inventory"] is True for call in calls)
    assert all(call[1]["prefer_direct"] is True for call in calls)
    assert len(rows) == 63
    report = scraper.last_south_carolina_full_corpus_report
    assert report["closed"] is True
    assert report["title_count"] == report["chapter_count"] == 63
    assert report["candidate_sections"] == report["operative_sections"] == 63
    assert report["parser_residual_count"] == 0


def test_mississippi_strict_section_leaf_algebra() -> None:
    source = (
        "https://billstatus.ls.state.ms.us/documents/2024/html/"
        "code_sections/097/00030019.htm"
    )
    rows, report = parse_mississippi_section_html_strict(
        "<html><body><h1>97-3-19 - Test offense</h1>"
        "<p>This source-bound provision contains operative statutory text.</p>"
        "</body></html>",
        source_url=source,
    )
    terminal_rows, terminal_report = parse_mississippi_section_html_strict(
        "<html><body><h1>97-3-19 - Repealed.</h1></body></html>",
        source_url=source,
    )

    assert len(rows) == 1
    assert report["closed"] is True
    assert rows[0].structured_data["canonical_section_key"] == "ms:97-3-19"
    assert terminal_rows == []
    assert terminal_report["closed"] is True
    assert terminal_report["terminal_sections"] == 1


def _ms_catalog_payloads(scraper: MississippiScraper) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    root_links: list[str] = []
    for title in sorted(scraper.OFFICIAL_TITLE_NAMES):
        title_url = scraper.official_title_url(title)
        root_links.append(f"<a href='{title:03d}/'>Title {title}</a>")
        filename = "00010001.htm"
        payloads[title_url] = (
            f"<html><body><h1>Title {title}</h1>"
            f"<a href='{filename}'>Section {title}-1-1</a>"
            "</body></html>"
        ).encode()
        section_url = f"{title_url}{filename}"
        payloads[section_url] = (
            f"<html><body><h1>{title}-1-1 - TEST SECTION</h1>"
            "<p>This official Mississippi statutory leaf is operative.</p>"
            "</body></html>"
        ).encode()
    payloads[scraper.OFFICIAL_BILLSTATUS_CODE_ROOT] = (
        f"<html><body>{''.join(root_links)}</body></html>"
    ).encode()
    return payloads


@pytest.mark.anyio
async def test_mississippi_full_route_blocks_after_exact_delegated_toc_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    probe_calls: list[str] = []
    checkpoints: list[dict[str, Any]] = []

    async def _probe(*, code_name: str) -> dict[str, Any]:
        probe_calls.append(code_name)
        return {
            "schema_version": "mississippi-delegated-catalog-probe/v1",
            "status": "complete",
            "disposition": "delegated_toc_closed_body_frontier_unacquired",
            "frontier": {
                "toc_frontier_closed": True,
                "expected_root_count": 51,
                "title_count": 50,
                "document_body_count": 0,
                "body_frontier_closed": False,
            },
            "full_corpus_admissible": False,
        }

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_probe_delegated_mississippi_code", _probe)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        lambda *_a, **_k: pytest.fail("dead bill-status frontier was requested"),
    )
    monkeypatch.setattr(
        scraper,
        "_write_partial_checkpoint",
        lambda *_a, **kwargs: checkpoints.append(dict(kwargs)),
    )

    with pytest.raises(
        MississippiDelegatedCorpusBlockedError,
        match="delegated_toc_closed_body_frontier_unacquired",
    ) as captured:
        await scraper.scrape_code(
            "Mississippi Code",
            scraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )

    assert probe_calls == ["Mississippi Code"]
    assert captured.value.evidence["frontier"]["toc_frontier_closed"] is True
    assert checkpoints[0]["stage_label"] == (
        "mississippi:delegated-body-frontier-blocked"
    )
    report = scraper.last_mississippi_full_corpus_report
    assert report["closed"] is False
    assert report["frontier"]["document_body_count"] == 0


@pytest.mark.anyio
async def test_mississippi_full_route_preserves_incomplete_delegated_root_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = MississippiScraper("MS", "Mississippi")

    async def _probe(*, code_name: str) -> dict[str, Any]:
        assert code_name == "Mississippi Code"
        return {
            "status": "partial_toc",
            "disposition": "delegated_locator_frontier_unavailable",
            "frontier": {
                "toc_frontier_closed": False,
                "root_membership_error": "missing Title 99",
            },
            "full_corpus_admissible": False,
        }

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(scraper, "_probe_delegated_mississippi_code", _probe)
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: None)

    with pytest.raises(
        MississippiDelegatedCorpusBlockedError,
        match="delegated_locator_frontier_unavailable",
    ) as captured:
        await scraper.scrape_code(
            "Mississippi Code",
            scraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
    assert captured.value.evidence["frontier"]["root_membership_error"] == (
        "missing Title 99"
    )


@pytest.mark.anyio
async def test_tennessee_full_mode_rejects_secondary_leaf_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("STATE_SCRAPER_TN_ALLOW_JUSTIA_FALLBACK", "1")

    with pytest.raises(RuntimeError, match="General Assembly-delegated Lexis"):
        await scraper.scrape_code(
            "Tennessee Code Annotated",
            scraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )


def test_tennessee_current_source_delegation_and_title_labels() -> None:
    scraper = TennesseeScraper("TN", "Tennessee")

    assert scraper.CURRENT_GENERAL_ASSEMBLY_PUBLICATIONS_URL == (
        "https://wapp.capitol.tn.gov/apps/WebPublications/"
    )
    assert scraper.AUTHORIZED_CODE_ENTRY_URL == (
        "https://www.lexisnexis.com/hottopics/tncode"
    )
    assert scraper.AUTHORIZED_CODE_CONTAINER_URL == (
        "https://advance.lexis.com/container?config="
        "014CJAA5ZGVhZjA3NS02MmMzLTRlZWQtOGJjNC00YzQ1MmZlNzc2YWYK"
        "AFBvZENhdGFsb2e9zYpNUjTRaIWVfyrur9ud"
    )
    assert scraper.AUTHORIZED_TOC_ENDPOINT == (
        "/r/tocprovider/6gf5kkk/toc/6gf5kkk"
    )
    assert scraper.get_code_list()[0]["url"] == scraper.AUTHORIZED_CODE_ENTRY_URL

    titles = dict(scraper.OFFICIAL_TITLES)
    assert len(titles) == scraper.OFFICIAL_TITLE_COUNT == 71
    assert {
        number: titles[number]
        for number in ("14", "15", "19", "33", "48", "51", "52", "64")
    } == {
        "14": "COVID-19",
        "15": "Holidays and Days of Special Observance",
        "19": "[Reserved]",
        "33": (
            "Mental Health and Substance Abuse and Intellectual and "
            "Developmental Disabilities"
        ),
        "48": "Securities, Corporations And Associations",
        "51": "[Reserved]",
        "52": "Department of Disability and Aging",
        "64": "Regional Authorities",
    }
    assert "all 69 deepest TOC responses" in scraper.STRICT_FULL_BLOCKER
    assert "ledger-replayed" in scraper.STRICT_FULL_BLOCKER


def test_tennessee_strict_catalog_rejects_synthetic_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TennesseeScraper("TN", "Tennessee")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        scraper,
        "_official_http_get",
        lambda _url, timeout_seconds=12: b"<html><body>TGA statutes</body></html>",
    )

    with pytest.raises(RuntimeError, match="exact 71-title catalog"):
        scraper.fetch_official("TN")


@pytest.mark.skipif(
    not os.environ.get("STATE_LAWS_TEST_SC_RETAINED_FETCH_ROOT"),
    reason="set STATE_LAWS_TEST_SC_RETAINED_FETCH_ROOT for the parser oracle",
)
@pytest.mark.anyio
async def test_retained_south_carolina_frontier_is_an_offline_oracle_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(os.environ["STATE_LAWS_TEST_SC_RETAINED_FETCH_ROOT"])
    scraper = SouthCarolinaScraper("SC", "South Carolina")
    payload_by_url: dict[str, bytes] = {}
    for metadata_path in root.glob("shard*/output/cache/fetch/objects/*.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if metadata.get("state_code") != "SC":
            continue
        payload = metadata_path.with_suffix(".bin").read_bytes()
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        payload_by_url[str(metadata["url"])] = payload

    async def _plural(urls: list[str], **_kwargs: Any) -> StateLawPageMultiFetchResult:
        return _batch(list(urls), payload_by_url, with_envelopes=False)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: None)

    rows = await scraper.scrape_code(
        "South Carolina Code of Laws",
        scraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )
    report = scraper.last_south_carolina_full_corpus_report

    assert len(payload_by_url) == 1_368
    assert len(rows) == report["operative_sections"] == 30_502
    assert report["title_count"] == 63
    assert report["chapter_count"] == 1_304
    assert report["section_bearing_chapter_count"] == 1_292
    assert report["terminal_chapter_count"] == 12
    assert report["candidate_sections"] == 30_871
    assert report["terminal_sections"] == 369
    assert report["parser_residual_count"] == 0
