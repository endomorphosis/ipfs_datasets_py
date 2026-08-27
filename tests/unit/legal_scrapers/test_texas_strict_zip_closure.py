from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas import (
    TexasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas_chapter import (
    parse_texas_chapter_html_strict,
)


def _section_html(
    code: str,
    *,
    chapter: str = "1",
    section: str = "1.001",
    heading: str = "OFFICIAL TEST SECTION",
    body: str = "",
) -> str:
    substantive = body or (
        "This official Texas statutory section contains enough retained legal "
        "text to prove an operative source-bound parser row without a cap."
    )
    return (
        "<html><body><pre>"
        f'<p class="center">CHAPTER {chapter}. TEST CHAPTER</p>'
        f'<p class="left" style="text-indent:7ex;">'
        f'<a href="https://statutes.capitol.texas.gov/Docs/{code}/htm/'
        f'{code}.{chapter}.htm#{section}">'
        f"Sec. {section}. {heading}.</a> {substantive}</p>"
        "</pre></body></html>"
    )


def _zip_bytes(*members: tuple[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for member_name, html in members:
            archive.writestr(member_name, html)
    return buffer.getvalue()


def _direct_receipt(url: str, payload: bytes) -> dict[str, str]:
    return {
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "official_url": url,
        "source_transport": "direct",
    }


def _parser_envelope(url: str, payload: bytes) -> dict[str, Any]:
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


def _manifest_bytes(
    scraper: TexasScraper,
    *,
    omit: set[str] | None = None,
    extra_rows: list[dict[str, str]] | None = None,
) -> bytes:
    omitted = set(omit or set())
    rows = [
        {
            "code": code,
            "CodeName": name,
            "Html": f"/Zips/{code}.htm.zip",
        }
        for code, name, _reason in scraper.OFFICIAL_DOWNLOAD_EXCLUSIONS
        if code not in omitted
    ]
    rows.extend(
        {
            "code": code,
            "CodeName": name,
            "Html": f"/Zips/{code}.htm.zip",
        }
        for code, name in scraper.OFFICIAL_CODES
        if code not in omitted
    )
    rows.extend(extra_rows or [])
    return json.dumps({"StatuteCode": rows}, sort_keys=True).encode()


def _full_zip_batch(scraper: TexasScraper) -> StateLawPageMultiFetchResult:
    urls = [
        scraper.OFFICIAL_DOWNLOADS_URL,
        *[scraper.official_zip_url(code) for code, _name in scraper.OFFICIAL_CODES],
    ]
    payloads = [
        _manifest_bytes(scraper),
        *[
            _zip_bytes(
                (
                    f"{code.lower()}.1.htm",
                    _section_html(code, section="1.001"),
                )
            )
            for code, _name in scraper.OFFICIAL_CODES
        ],
    ]
    return StateLawPageMultiFetchResult(
        urls=urls,
        payloads=payloads,
        errors=[None] * len(urls),
        transport_receipts=[
            _direct_receipt(url, payload)
            for url, payload in zip(urls, payloads, strict=True)
        ],
        parser_input_envelopes=[
            _parser_envelope(url, payload)
            for url, payload in zip(urls, payloads, strict=True)
        ],
        stats={
            "network_requested_pages": 0,
            "requested_pages": len(urls),
            "retained_replay_pages": len(urls),
        },
    )


class _RetainedLedger:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = dict(payloads)
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def refresh_existing_entries(self) -> None:
        return None

    def replay_retained_parser_input(
        self,
        *,
        official_url: str,
        sanitized_request: dict[str, Any],
    ) -> Any:
        self.requests.append((official_url, dict(sanitized_request)))
        payload = self.payloads.get(official_url)
        if payload is None:
            return None
        return SimpleNamespace(
            envelope=SimpleNamespace(body=payload),
            transport_receipt=_direct_receipt(official_url, payload),
        )


def test_strict_chapter_parser_closes_internal_article_and_concurrent_sections() -> (
    None
):
    html = """
    <html><body>
      <p class="center">CHAPTER 11. HABEAS CORPUS</p>
      <p class="left" style="text-indent:7ex;">Art. 11.071. PROCEDURE IN DEATH PENALTY CASE.</p>
      <p class="center">Text of section effective until January 01, 2027</p>
      <p class="left" style="text-indent:7ex;">Sec. 1. FIRST APPLICATION. This first internal section contains enough operative statutory text for strict parsing.</p>
      <p class="center">Text of section effective on January 01, 2027</p>
      <p class="left" style="text-indent:7ex;">Sec. 1. CONCURRENT APPLICATION. This distinct concurrent section also contains enough operative statutory text for strict parsing.</p>
      <p class="left" style="text-indent:7ex;">Art. 11.08. APPLICANT. The applicant for the writ must be restrained in liberty under an official criminal accusation.</p>
      <p class="left" style="text-indent:7ex;">Art. 11.09. [Repealed].</p>
    </body></html>
    """

    rows, report = parse_texas_chapter_html_strict(
        html,
        code_name="Code of Criminal Procedure",
        code_abbrev="CR",
        member_name="cr.11.htm",
        source_url="https://statutes.capitol.texas.gov/Docs/CR/htm/cr.11.htm",
        zip_url="https://tcss.legis.texas.gov/resources/Zips/CR.htm.zip",
    )

    assert report["closed"] is True
    assert report["candidate_sections"] == 5
    assert report["operative_sections"] == 3
    assert report["terminal_sections"] == 2
    assert {item["disposition"] for item in report["terminal_dispositions"]} == {
        "internal_section_container",
        "repealed",
    }
    assert rows[0].section_number == "art. 11.071 sec. 1"
    assert rows[1].section_number == "art. 11.071 sec. 1"
    assert rows[0].statute_id != rows[1].statute_id
    assert rows[0].structured_data["temporal_variant_kind"] == "until"
    assert rows[1].structured_data["temporal_variant_kind"] == "on"
    keys = [row.structured_data["canonical_section_key"] for row in rows]
    assert len(keys) == len(set(keys))


def test_strict_chapter_parser_fails_unlabeled_duplicate_variant_closed() -> None:
    rows, report = parse_texas_chapter_html_strict(
        "<html><body>"
        "<p class='left'>Sec. 1. FIRST VERSION. This first version has "
        "complete official statutory body text.</p>"
        "<p class='left'>Sec. 1. SECOND VERSION. This second version also has "
        "complete official statutory body text.</p>"
        "</body></html>",
        code_name="Test Code",
        code_abbrev="TX",
        member_name="tx.1.htm",
        source_url="https://statutes.capitol.texas.gov/Docs/TX/htm/tx.1.htm",
        zip_url="https://tcss.legis.texas.gov/resources/Zips/TX.htm.zip",
    )

    assert rows == []
    assert report["closed"] is False
    assert report["candidate_sections"] == 2
    assert len(report["parser_residuals"]) == 2
    assert {row["reason"] for row in report["parser_residuals"]} == {
        "ambiguous_unlabeled_or_repeated_source_variant"
    }


def test_strict_chapter_parser_binds_official_another_subchapter_context() -> None:
    rows, report = parse_texas_chapter_html_strict(
        "<html><body>"
        "<p class='left'>Sec. 10. FIRST SUBCHAPTER VERSION. This first "
        "concurrent statutory version contains complete official body text.</p>"
        "<p>For another Subchapter B, consisting of Sec. 10, added by Acts "
        "2025, 89th Leg., R.S., Ch. 1, see Sec. 10 et seq., post.</p>"
        "<p class='left'>Sec. 10. SECOND SUBCHAPTER VERSION. This second "
        "concurrent statutory version contains complete official body text.</p>"
        "</body></html>",
        code_name="Test Code",
        code_abbrev="TX",
        member_name="tx.10.htm",
        source_url="https://statutes.capitol.texas.gov/Docs/TX/htm/tx.10.htm",
        zip_url="https://tcss.legis.texas.gov/resources/Zips/TX.htm.zip",
    )

    assert report["closed"] is True
    assert len(rows) == 2
    assert rows[0].structured_data["concurrent_variant_role"] == (
        "primary_unlabeled_concurrent_source_occurrence"
    )
    assert (
        rows[1]
        .structured_data["concurrent_variant_label"]
        .startswith("For another Subchapter B")
    )
    assert (
        rows[0].structured_data["canonical_section_key"]
        != (rows[1].structured_data["canonical_section_key"])
    )


def test_strict_chapter_parser_binds_official_as_added_internal_variants() -> None:
    rows, report = parse_texas_chapter_html_strict(
        "<html><body>"
        "<p class='left'>Art. 42.01. JUDGMENT.</p>"
        "<p class='center'>Text of section as added by Acts 2025, 89th "
        "Leg., R.S., Ch. 339 (S.B. 9), Sec. 13</p>"
        "<p class='left' style='text-indent:7ex;'>Sec. 17. FIRST "
        "CONCURRENT PROVISION. This official internal section contains "
        "complete operative statutory text.</p>"
        "<p class='center'>Text of section as added by Acts 2025, 89th "
        "Leg., R.S., Ch. 539 (H.B. 108), Sec. 1</p>"
        "<p class='left' style='text-indent:7ex;'>Sec. 17. SECOND "
        "CONCURRENT PROVISION. This other official internal section also "
        "contains complete operative statutory text.</p>"
        "</body></html>",
        code_name="Code of Criminal Procedure",
        code_abbrev="CR",
        member_name="cr.42.htm",
        source_url="https://statutes.capitol.texas.gov/Docs/CR/htm/cr.42.htm",
        zip_url="https://tcss.legis.texas.gov/resources/Zips/CR.htm.zip",
    )

    assert report["closed"] is True
    assert len(rows) == 2
    assert {row.structured_data["source_variant_kind"] for row in rows} == {
        "as_added"
    }
    assert len({row.statute_id for row in rows}) == 2
    assert len(
        {row.structured_data["canonical_section_key"] for row in rows}
    ) == 2


def test_strict_chapter_parser_uses_distinct_official_source_anchors() -> None:
    rows, report = parse_texas_chapter_html_strict(
        "<html><body>"
        "<p class='left'><a name='211.052'></a>"
        "<a name='194830.201067'></a></p>"
        "<p class='left' style='text-indent:7ex;'>Sec. 211.052. FIRST "
        "OFFICIAL VERSION. This official statutory variant contains "
        "complete operative source text.</p>"
        "<p class='left'><a name='211.052'></a>"
        "<a name='194838.201068'></a></p>"
        "<p class='left' style='text-indent:7ex;'>Sec. 211.052. SECOND "
        "OFFICIAL VERSION. This other official statutory variant contains "
        "complete operative source text.</p>"
        "</body></html>",
        code_name="Local Government Code",
        code_abbrev="LG",
        member_name="lg.211.htm",
        source_url="https://statutes.capitol.texas.gov/Docs/LG/htm/lg.211.htm",
        zip_url="https://tcss.legis.texas.gov/resources/Zips/LG.htm.zip",
    )

    assert report["closed"] is True
    assert len(rows) == 2
    assert {row.structured_data["source_anchor_identity"] for row in rows} == {
        "194830.201067",
        "194838.201068",
    }
    assert {
        row.structured_data["source_variant_disambiguation"] for row in rows
    } == {"official_tlc_named_source_anchor"}
    assert len(
        {row.structured_data["canonical_section_key"] for row in rows}
    ) == 2


def test_strict_chapter_parser_preserves_parenthesized_article_identity() -> None:
    rows, report = parse_texas_chapter_html_strict(
        "<html><body>"
        "<p class='left'><a name='6243e'></a>"
        "<a name='80805.69761'></a></p>"
        "<p class='left'><a href='#6243e'>Art. 6243e. FIRST "
        "RETIREMENT ACT.</a></p>"
        "<p class='left'>Sec. 1. SHORT TITLE. This first official act "
        "contains complete operative statutory text.</p>"
        "<p class='left'><a name='6243e.2(1)'></a>"
        "<a name='80807.194937'></a></p>"
        "<p class='left'><a href='#6243e.2(1)'>Art. 6243e.2(1). SECOND "
        "RETIREMENT ACT.</a></p>"
        "<p class='left'>Sec. 1. DEFINITIONS. This separately numbered "
        "official act also contains complete operative statutory text.</p>"
        "</body></html>",
        code_name="Vernon's Civil Statutes",
        code_abbrev="CV",
        member_name="cv.109.0.htm",
        source_url=(
            "https://statutes.capitol.texas.gov/Docs/CV/htm/CV.109.0.htm"
        ),
        zip_url="https://tcss.legis.texas.gov/resources/Zips/CV.htm.zip",
    )

    assert report["closed"] is True
    assert report["parser_residuals"] == []
    assert report["candidate_sections"] == 4
    assert report["terminal_sections"] == 2
    assert len(rows) == 2
    assert [row.structured_data["parent_article"] for row in rows] == [
        "6243e",
        "6243e.2(1)",
    ]
    assert [row.section_number for row in rows] == [
        "art. 6243e sec. 1",
        "art. 6243e.2(1) sec. 1",
    ]
    assert len(
        {row.structured_data["canonical_section_key"] for row in rows}
    ) == 2


def test_source_bound_texas_article_section_survives_shared_quality_heuristic() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
        _filter_strict_full_text_statutes,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.texas import (
        TexasScraper,
    )

    rows, report = parse_texas_chapter_html_strict(
        "<html><body>"
        "<p class='left'>Art. 42.032. CONDUCT RECORD.</p>"
        "<p class='left'>Sec. 7. The sheriff shall keep a conduct record "
        "and a calendar card for each defendant showing all forfeitures "
        "of commutation time and the reasons for each forfeiture.</p>"
        "</body></html>",
        code_name="Code of Criminal Procedure",
        code_abbrev="CR",
        member_name="cr.42.htm",
        source_url="https://statutes.capitol.texas.gov/Docs/CR/htm/cr.42.htm",
        zip_url="https://tcss.legis.texas.gov/resources/Zips/CR.htm.zip",
    )

    assert report["closed"] is True
    assert len(rows) == 1
    row = rows[0]
    assert row.section_number == "art. 42.032 sec. 7"
    assert _filter_strict_full_text_statutes(
        [row],
        min_full_text_chars=1,
    ) == ([], 1)

    scraper = TexasScraper("TX", "Texas")
    assert scraper._is_source_bound_operative_statute_record(row)
    assert _filter_strict_full_text_statutes(
        [row],
        min_full_text_chars=1,
        source_bound_operative_checker=(
            scraper._is_source_bound_operative_statute_record
        ),
    ) == ([row], 0)


def test_strict_chapter_parser_retains_section_without_catchline() -> None:
    rows, report = parse_texas_chapter_html_strict(
        "<html><body><p class='left'>Sec. 1. This compact provision begins "
        "with operative text and intentionally has no uppercase catchline.</p>"
        "</body></html>",
        code_name="Health and Safety Code",
        code_abbrev="HS",
        member_name="hs.403.htm",
        source_url="https://statutes.capitol.texas.gov/Docs/HS/htm/hs.403.htm",
        zip_url="https://tcss.legis.texas.gov/resources/Zips/HS.htm.zip",
    )

    assert report["closed"] is True
    assert report["candidate_sections"] == report["operative_sections"] == 1
    assert rows[0].full_text.startswith("This compact provision")


def test_strict_chapter_parser_types_explicit_blank_article_terminal() -> None:
    rows, report = parse_texas_chapter_html_strict(
        "<html><body><p class='left'>Art. 21.49-5. [BLANK].</p></body></html>",
        code_name="Insurance Code - Not Codified",
        code_abbrev="I1",
        member_name="i1.21.htm",
        source_url="https://statutes.capitol.texas.gov/Docs/I1/htm/i1.21.htm",
        zip_url="https://tcss.legis.texas.gov/resources/Zips/I1.htm.zip",
    )

    assert rows == []
    assert report["closed"] is True
    assert report["candidate_sections"] == report["terminal_sections"] == 1
    assert report["terminal_dispositions"][0]["disposition"] == "blank"


def test_strict_zip_member_inventory_types_superseded_and_repealed_members() -> None:
    scraper = TexasScraper("TX", "Texas")
    payload = _zip_bytes(
        ("pe.1.htm", _section_html("PE")),
        ("pe.22_old.htm", _section_html("PE", chapter="22", section="22.01")),
        (
            "pe.99.htm",
            "<html><body><p>Text of chapter as repealed by Acts 2009, "
            "81st Leg., effective September 1, 2009</p></body></html>",
        ),
    )
    digest = hashlib.sha256(payload).hexdigest()

    rows, report = scraper._parse_texas_full_zip_member_inventory(
        code_abbrev="PE",
        code_name="Penal Code",
        zip_url=scraper.official_zip_url("PE"),
        payload=payload,
        evidence={"content_sha256": digest},
    )

    assert len(rows) == 1
    assert report["closed"] is True
    assert report["member_count"] == 3
    assert report["operative_member_count"] == 1
    assert report["terminal_member_count"] == 2
    assert report["residual_member_count"] == 0
    assert {row["disposition"] for row in report["terminal_members"]} == {
        "repealed_chapter_without_sections",
        "superseded_official_member_copy",
    }


def test_strict_zip_member_inventory_fails_unknown_member_closed() -> None:
    scraper = TexasScraper("TX", "Texas")
    payload = _zip_bytes(
        ("pe.1.htm", _section_html("PE")),
        ("README.txt", "unclassified bundle content"),
    )

    with pytest.raises(RuntimeError, match="completion algebra failed"):
        scraper._parse_texas_full_zip_member_inventory(
            code_abbrev="PE",
            code_name="Penal Code",
            zip_url=scraper.official_zip_url("PE"),
            payload=payload,
            evidence={"content_sha256": hashlib.sha256(payload).hexdigest()},
        )


def test_strict_zip_member_inventory_accepts_decimal_fraction_member() -> None:
    scraper = TexasScraper("TX", "Texas")
    payload = _zip_bytes(
        (
            "cv.71.6-1_2.htm",
            _section_html(
                "CV",
                chapter="71.6-1_2",
                section="71.601",
            ),
        )
    )

    rows, report = scraper._parse_texas_full_zip_member_inventory(
        code_abbrev="CV",
        code_name="Vernon's Civil Statutes",
        zip_url=scraper.official_zip_url("CV"),
        payload=payload,
        evidence={"content_sha256": hashlib.sha256(payload).hexdigest()},
    )

    assert report["closed"] is True
    assert report["member_count"] == 1
    assert rows[0].chapter_number == "71.6-1_2"


@pytest.mark.anyio
async def test_full_corpus_uses_one_exact_manifest_and_statute_zip_plural_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TexasScraper("TX", "Texas")
    batch = _full_zip_batch(scraper)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _plural(urls: list[str], **kwargs: Any) -> StateLawPageMultiFetchResult:
        calls.append((list(urls), dict(kwargs)))
        return batch

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.delenv("TEXAS_CHAPTER_HTML", raising=False)
    monkeypatch.delenv("TEXAS_CONSTITUTION_HTML", raising=False)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    rows = await scraper.scrape_all(
        max_statutes=None,
        rate_limit_delay=0,
        hydrate_statute_text=False,
    )

    expected_urls = [
        scraper.OFFICIAL_DOWNLOADS_URL,
        *[scraper.official_zip_url(code) for code, _name in scraper.OFFICIAL_CODES],
    ]
    assert len(calls) == 1
    assert calls[0][0] == expected_urls
    assert calls[0][1]["prefer_direct"] is True
    assert calls[0][1]["wayback_prefix_inventory"] is True
    assert calls[0][1]["common_crawl_domain_terms"] == (
        scraper.OFFICIAL_ZIP_HOST,
        scraper.OFFICIAL_DOMAIN,
    )
    assert calls[0][1]["common_crawl_url_terms"] == (
        "/resources/Zips/",
        scraper.OFFICIAL_DOWNLOADS_PATH,
    )
    assert len(rows) == scraper.OFFICIAL_CODE_COUNT == 30
    canonical_keys = [row.structured_data["canonical_section_key"] for row in rows]
    assert len(canonical_keys) == len(set(canonical_keys))
    assert all(
        row.structured_data["parser_input_receipt_sha256"] == "a" * 64 for row in rows
    )
    report = scraper.last_texas_full_corpus_report
    assert report["closed"] is True
    assert report["candidate_sections"] == 30
    assert report["operative_sections"] == 30
    assert report["terminal_sections"] == 0
    assert report["download_manifest_unit_count"] == 31
    assert report["download_scope_exclusions"] == [
        {
            "code": "CN",
            "reason": "separate_constitutional_corpus",
            "source_code_name": "The Texas Constitution",
            "source_order": 0,
            "zip_url": scraper.official_zip_url("CN"),
        }
    ]
    assert report["frontier"]["scope_closed"] is True
    assert report["batch_stats"]["retained_replay_pages"] == 31
    assert report["batch_stats"]["network_requested_pages"] == 0


@pytest.mark.anyio
async def test_exact_zip_frontier_fails_after_one_plural_call_on_a_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TexasScraper("TX", "Texas")
    batch = _full_zip_batch(scraper)
    batch.payloads[-1] = b""
    batch.errors[-1] = "all direct/archive transports missed"
    calls = 0

    async def _plural(urls: list[str], **kwargs: Any) -> StateLawPageMultiFetchResult:
        nonlocal calls
        del urls, kwargs
        calls += 1
        return batch

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )

    with pytest.raises(RuntimeError, match="incomplete after residual-only retries"):
        await scraper._fetch_texas_full_zip_frontier()
    assert calls == 1


@pytest.mark.anyio
async def test_full_mode_refuses_a_statute_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TexasScraper("TX", "Texas")
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")

    with pytest.raises(RuntimeError, match="refuses caps"):
        await scraper.scrape_all(max_statutes=1, rate_limit_delay=0)


def test_zip_evidence_context_rejects_nonreplaying_envelope() -> None:
    scraper = TexasScraper("TX", "Texas")
    url = scraper.official_zip_url("PE")
    payload = _zip_bytes(("pe.1.htm", _section_html("PE")))
    envelope = _parser_envelope(url, payload)
    envelope["acquisition"]["body_sha256"] = "0" * 64

    with pytest.raises(RuntimeError, match="does not replay exact bytes"):
        scraper._texas_zip_evidence_context(
            source_url=url,
            payload=payload,
            transport_receipt=_direct_receipt(url, payload),
            parser_input_envelope=envelope,
        )


def test_strict_catalog_observation_rejects_missing_download_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TexasScraper("TX", "Texas")
    downloads = _manifest_bytes(scraper, omit={"WA"})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        scraper,
        "_official_http_get",
        lambda url, timeout_seconds=12: (
            downloads if url == scraper.OFFICIAL_DOWNLOADS_URL else b"<html></html>"
        ),
    )

    with pytest.raises(RuntimeError, match=r"missing=\['WA'\]"):
        scraper.fetch_official("TX")


def test_strict_catalog_observation_binds_exact_downloads_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = TexasScraper("TX", "Texas")
    downloads = _manifest_bytes(scraper)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        scraper,
        "_official_http_get",
        lambda url, timeout_seconds=12: (
            downloads if url == scraper.OFFICIAL_DOWNLOADS_URL else b"<html></html>"
        ),
    )

    fetch = scraper.fetch_official("TX")

    assert fetch.response_bytes == downloads
    assert fetch.source_path == scraper.OFFICIAL_DOWNLOADS_PATH
    assert (
        fetch.frontier["tx_downloads_content_sha256"]
        == hashlib.sha256(downloads).hexdigest()
    )
    assert fetch.frontier["tx_zip_urls"] == [
        scraper.official_zip_url(code) for code, _name in scraper.OFFICIAL_CODES
    ]
    assert fetch.frontier["tx_download_code_count"] == 31
    assert fetch.frontier["tx_excluded_non_statute"][0]["code"] == "CN"


def test_download_manifest_rejects_unreviewed_official_bundle() -> None:
    scraper = TexasScraper("TX", "Texas")
    payload = _manifest_bytes(
        scraper,
        extra_rows=[
            {
                "code": "ZZ",
                "CodeName": "New Unreviewed Laws",
                "Html": "/Zips/ZZ.htm.zip",
            }
        ],
    )

    with pytest.raises(RuntimeError, match="unreviewed code: ZZ"):
        scraper._parse_texas_download_manifest(payload)


@pytest.mark.anyio
async def test_retained_manifest_and_all_statute_zips_seal_zero_network_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scraper = TexasScraper("TX", "Texas")
    batch = _full_zip_batch(scraper)

    async def _plural(
        urls: list[str],
        **kwargs: Any,
    ) -> StateLawPageMultiFetchResult:
        assert list(urls) == batch.urls
        assert kwargs["prefer_direct"] is True
        assert kwargs["wayback_prefix_inventory"] is True
        return batch

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    rows = await scraper.scrape_all(
        max_statutes=None,
        rate_limit_delay=0,
        hydrate_statute_text=False,
    )
    assert scraper._supports_shared_official_frontier_bridge() is False

    ledger = _RetainedLedger(dict(zip(batch.urls, batch.payloads, strict=True)))
    scraper._state_law_acquisition_ledger = ledger
    captured: dict[str, Any] = {}

    def _retain(completion_receipt: dict[str, Any], **kwargs: Any) -> Path:
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "tx-closure.json"

    def _forbid_catalog_reacquisition(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Texas certification must use retained parser inputs")

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["tx-tlc-statutes"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "tx-test@sha256:" + ("b" * 64),
    )
    monkeypatch.setattr(scraper, "fetch_official", _forbid_catalog_reacquisition)
    projection = build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="TX",
    )

    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert retained_path == tmp_path / "tx-closure.json"
    assert [request[0] for request in ledger.requests] == batch.urls
    assert all(request[1]["method"] == "GET" for request in ledger.requests)
    assert all("Accept" in request[1]["headers"] for request in ledger.requests)
    completion = captured["completion"]
    assert completion["disposition"] == {
        "discovered": 30,
        "fetched": 30,
        "excluded": 0,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    assert completion["rights"] == {
        "basis": "public_law_no_state_copyright",
        "decision": "admit",
        "scope": "statutory_text",
    }
    assert completion["replay"]["network_requests"] == 0
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    assert completion["boundary_probes"] == {
        "bundle_total": 30,
        "first_hierarchy_unit": scraper.official_zip_url("AG"),
        "last_hierarchy_unit": scraper.official_zip_url("CV"),
        "pagination_total": 31,
    }


@pytest.mark.skipif(
    not os.environ.get("STATE_LAWS_TEST_TX_RETAINED_FETCH_ROOT"),
    reason="set STATE_LAWS_TEST_TX_RETAINED_FETCH_ROOT for the regression oracle",
)
def test_retained_2026_05_zip_bytes_are_parser_oracles_only() -> None:
    root = Path(os.environ["STATE_LAWS_TEST_TX_RETAINED_FETCH_ROOT"])
    scraper = TexasScraper("TX", "Texas")
    code_names = dict(scraper.OFFICIAL_CODES)
    expected_missing = (
        ("WL", "Auxiliary Water Laws"),
        ("BO", "Business Organizations Code"),
        ("ES", "Estates Code"),
        ("I1", "Insurance Code - Not Codified"),
        ("SD", "Special District Local Laws Code"),
        ("CV", "Vernon's Civil Statutes"),
    )
    reports: dict[str, dict[str, Any]] = {}
    row_count = 0

    for metadata_path in sorted(root.glob("shard*/output/cache/fetch/objects/*.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        match = re.search(
            r"/Zips/(?P<code>[A-Z]{2})\.htm\.zip$",
            str(metadata.get("url") or ""),
        )
        if match is None or match.group("code") not in code_names:
            continue
        code = match.group("code")
        payload = metadata_path.with_suffix(".bin").read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        assert digest == metadata["sha256"]
        rows, report = scraper._parse_texas_full_zip_member_inventory(
            code_abbrev=code,
            code_name=code_names[code],
            zip_url=str(metadata["url"]),
            payload=payload,
            evidence={"content_sha256": digest},
        )
        assert report["closed"] is True
        reports[code] = report
        row_count += len(rows)

    observed_missing = tuple(
        (code, name)
        for code, name in scraper.OFFICIAL_CODES
        if code not in reports
    )
    assert observed_missing == expected_missing
    assert set(reports) == set(code_names).difference(dict(expected_missing))
    assert all(
        scraper.official_zip_url(code).startswith(
            f"https://{scraper.OFFICIAL_ZIP_HOST}/"
        )
        for code, _name in expected_missing
    )
    assert len(reports) == 24
    assert row_count == 87_819
    assert sum(report["member_count"] for report in reports.values()) == 3_440
    assert sum(report["candidate_sections"] for report in reports.values()) == 87_865
    assert sum(report["terminal_sections"] for report in reports.values()) == 46
    assert sum(report["terminal_member_count"] for report in reports.values()) == 8
