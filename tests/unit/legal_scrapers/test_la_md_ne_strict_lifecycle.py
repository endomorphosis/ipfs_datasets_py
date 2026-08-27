from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    canonical_json_bytes,
)
from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    _filter_strict_full_text_statutes,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import (
    LouisianaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.maryland import (
    MarylandScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska import (
    NebraskaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.nebraska_section import (
    classify_nebraska_terminal_section_html,
    parse_nebraska_section_html,
    section_links,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.strict_frontier_closure import (
    replay_exact_retained_state_input,
    replay_exact_retained_state_record,
)


class _MemoryLedger:
    def __init__(
        self,
        inputs: list[tuple[str, Mapping[str, Any], bytes, Mapping[str, Any]]],
    ) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.refresh_calls = 0
        self._retained: dict[tuple[str, bytes], Any] = {}
        self.entries: list[Any] = []
        for endpoint, request, body, pagination in inputs:
            content = SimpleNamespace(sha256=hashlib.sha256(body).hexdigest())
            receipt = SimpleNamespace(
                content=content,
                endpoint=endpoint,
                pagination=dict(pagination),
                sanitized_request=dict(request),
            )
            retained = SimpleNamespace(
                envelope=SimpleNamespace(body=body),
                receipt=receipt,
                transport_receipt={
                    "content_sha256": content.sha256,
                    "official_url": endpoint,
                    "source_transport": "retained_acquisition_replay",
                },
            )
            key = (endpoint, canonical_json_bytes(dict(request)))
            self._retained[key] = retained
            self.entries.append(retained)

    def refresh_existing_entries(self) -> int:
        self.refresh_calls += 1
        return 0

    def replay_retained_parser_input(
        self,
        *,
        official_url: str,
        sanitized_request: Mapping[str, Any],
    ) -> Any:
        request = dict(sanitized_request)
        self.requests.append((official_url, request))
        return self._retained.get(
            (official_url, canonical_json_bytes(request))
        )


def test_shared_retained_record_reuses_verified_envelope_without_refresh() -> None:
    url = "https://example.gov/law/1"
    request = {"method": "GET", "url": url}
    ledger = _MemoryLedger([(url, request, b"official bytes", {})])
    scraper = SimpleNamespace(_state_law_acquisition_ledger=ledger)

    retained = replay_exact_retained_state_record(
        scraper,
        official_url=url,
        sanitized_request=request,
        frontier_name="shared state leaf",
        refresh=False,
    )
    assert retained.envelope.body == b"official bytes"
    assert retained.transport_receipt["official_url"] == url
    assert ledger.refresh_calls == 0
    assert replay_exact_retained_state_input(
        scraper,
        official_url=url,
        sanitized_request=request,
        frontier_name="shared state leaf",
    ) == b"official bytes"
    assert ledger.refresh_calls == 1


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
) -> StateLawPageMultiFetchResult:
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=[None] * len(urls),
        transport_receipts=[
            {
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            }
            for url, body in zip(urls, payloads, strict=True)
        ],
        parser_input_envelopes=[
            SimpleNamespace(body=body) for body in payloads
        ],
        stats={
            "requested_pages": len(urls),
            "common_crawl": {
                "range_fetch_calls": 1,
                "range_fetches_avoided": max(0, len(urls) - 1),
            },
        },
    )


def _projection(scraper: Any, rows: list[Any]) -> dict[str, Any]:
    return build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction=scraper.state_code,
    )


def _capture_closure(
    monkeypatch: pytest.MonkeyPatch,
    scraper: Any,
    tmp_path: Path,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _retain(completion_receipt: Mapping[str, Any], **kwargs: Any) -> Path:
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / f"{scraper.state_code.lower()}-closure.json"

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: [f"{scraper.state_code.lower()}-official"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: f"{scraper.state_code.lower()}-test@sha256:" + ("a" * 64),
    )
    return captured


def _la_page(label: str, document_id: str, body: str) -> bytes:
    return f"""
    <form id="aspnetForm" action="./Law.aspx?d={document_id}">
      <input id="ctl00_PageBody_ButtonPrevious" />
      <span id="ctl00_PageBody_LabelName">{label}</span>
      <input id="ctl00_PageBody_ButtonNext" />
      <a id="ctl00_PageBody_linkPrint" href="LawPrint.aspx?d={document_id}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{body}</span>
    </form>
    """.encode()


@pytest.mark.anyio
async def test_louisiana_closure_replays_toc_leaves_and_public_rights(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    scraper = LouisianaScraper("LA", "Louisiana")
    toc_url = (
        "https://legis.la.gov/legis/Laws_Toc.aspx?folder=75&level=Parent"
    )
    urls = [
        "https://legis.la.gov/legis/Law.aspx?d=1001",
        "https://legis.la.gov/legis/Law.aspx?d=1002",
    ]
    root = (
        "<a href=\"javascript:__doPostBack(&#39;ctl00$PageBody$"
        "ListViewTOC1$ctrl0$LinkButton1a&#39;,&#39;&#39;)\">Title 1</a>"
    ).encode()
    post = (
        "<a href='Law.aspx?d=1001'>RS 1:1</a>"
        "<a href='Law.aspx?d=1002'>RS 1:2</a>"
        "<div class='parallel-presentation'>"
        "<a href='Law.aspx?d=1001'>RS 1:1</a>"
        "<a href='Law.aspx?d=1002'>RS 1:2</a>"
        "</div>"
    ).encode()
    pages = {
        urls[0]: _la_page(
            "RS 1:1",
            "1001",
            "<div id='WPMainDoc'><p>§1. Operative provision</p><p>"
            + (
                "This operative Louisiana provision supplies complete official "
                "public-law text for exact normalization and indexing. " * 5
            )
            + "</p></div>",
        ),
        urls[1]: _la_page("RS 1:2", "1002", "<p>§2. Repealed.</p>"),
    }
    get_request = {
        "headers": {
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
        },
        "method": "GET",
        "url": toc_url,
    }
    post_request = {
        "headers": {
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        "method": "POST",
        "request_body_length": 10,
        "request_body_sha256": "b" * 64,
        "url": toc_url,
    }
    ledger = _MemoryLedger(
        [
            (toc_url, get_request, root, {"kind": "aspnet_toc", "step": "root"}),
            (
                toc_url,
                post_request,
                post,
                {"kind": "aspnet_postback", "page_count": 1, "page_index": 1},
            ),
            *[
                (url, {"method": "GET", "url": url}, pages[url], {})
                for url in urls
            ],
        ]
    )
    scraper._state_law_acquisition_ledger = ledger

    async def _plural(requested_urls: list[str], **_kwargs: Any):
        requested = list(requested_urls)
        return _aligned_result(requested, [pages[url] for url in requested])

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)
    captured = _capture_closure(monkeypatch, scraper, tmp_path)

    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=urls,
        max_statutes=None,
    )
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=_projection(scraper, rows),
    )

    assert retained_path == tmp_path / "la-closure.json"
    assert [row.section_number for row in rows] == ["1"]
    assert captured["completion"]["disposition"] == {
        "discovered": 2,
        "duplicates": 0,
        "excluded": 1,
        "failed_final": 0,
        "fetched": 1,
        "quarantined": 0,
    }
    assert captured["completion"]["rights"]["basis"] == (
        "public_law_no_state_copyright"
    )
    assert captured["completion"]["replay"]["network_requests"] == 0


def test_louisiana_retained_toc_rejects_ambiguous_page_order() -> None:
    scraper = LouisianaScraper("LA", "Louisiana")
    toc_url = (
        "https://legis.la.gov/legis/Laws_Toc.aspx?folder=75&level=Parent"
    )
    root = (
        "<a href=\"javascript:__doPostBack(&#39;ctl00$PageBody$"
        "ListViewTOC1$ctrl0$LinkButton1a&#39;,&#39;&#39;)\">Title 1</a>"
    ).encode()
    post = b"<a href='Law.aspx?d=1001'>RS 1:1</a>"
    ledger = _MemoryLedger(
        [
            (
                toc_url,
                {"method": "GET", "url": toc_url},
                root,
                {"kind": "aspnet_toc", "step": "root"},
            ),
            (
                toc_url,
                {
                    "method": "POST",
                    "request_body_sha256": "a" * 64,
                    "url": toc_url,
                },
                post,
                {"kind": "aspnet_postback", "page_count": 1, "page_index": 1},
            ),
            (
                toc_url,
                {
                    "method": "POST",
                    "request_body_sha256": "b" * 64,
                    "url": toc_url,
                },
                post,
                {"kind": "aspnet_postback", "page_count": 1, "page_index": 1},
            ),
        ]
    )
    scraper._state_law_acquisition_ledger = ledger

    with pytest.raises(RuntimeError, match="pagination is ambiguous"):
        scraper._retained_louisiana_toc_reports()


def _md_body(section: str, *, terminal: bool = False) -> bytes:
    if terminal:
        return f"<div id='StatuteText'><div>§ {section}. Repealed</div></div>".encode()
    text = (
        "This operative Maryland provision supplies complete official "
        "public-law text for exact normalization and indexing. "
    ) * 3
    return (
        f"<div id='StatuteText'><div>§ {section}. Operative provision.</div>"
        f"<p>{text}</p></div>"
    ).encode()


@pytest.mark.anyio
async def test_maryland_closure_replays_api_hierarchy_and_terminal_leaf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    scraper = MarylandScraper("MD", "Maryland")
    article = {"DisplayText": "Education - (GED)", "Value": "ged"}
    section_rows = [
        {"DisplayText": "1-101", "Value": "1-101"},
        {"DisplayText": "1-102", "Value": "1-102"},
    ]
    articles_url = (
        "https://mgaleg.maryland.gov/mgawebsite/api/Laws/GetArticles"
        "?enactments=false"
    )
    sections_url = (
        "https://mgaleg.maryland.gov/mgawebsite/api/Laws/GetSections"
        "?articleCode=ged&enactments=false"
    )
    section_urls = [
        "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText"
        f"?article=GED&section={section}&enactments=false"
        for section in ("1-101", "1-102")
    ]
    bodies = {
        section_urls[0]: _md_body("1-101"),
        section_urls[1]: _md_body("1-102", terminal=True),
    }
    ledger = _MemoryLedger(
        [
            (
                articles_url,
                {"method": "GET", "url": articles_url},
                json.dumps([article]).encode(),
                {},
            ),
            (
                sections_url,
                {"method": "GET", "url": sections_url},
                json.dumps(section_rows).encode(),
                {},
            ),
            *[
                (url, {"method": "GET", "url": url}, bodies[url], {})
                for url in section_urls
            ],
        ]
    )
    scraper._state_law_acquisition_ledger = ledger

    async def _articles() -> list[dict[str, str]]:
        return [article]

    async def _sections(**_kwargs: Any) -> list[tuple[str, str]]:
        return [("1-101", "1-101"), ("1-102", "1-102")]

    async def _catalogs(
        requested_urls: list[str],
        **_kwargs: Any,
    ) -> dict[str, object]:
        assert list(requested_urls) == [sections_url]
        return {sections_url: list(section_rows)}

    async def _plural(requested_urls: list[str], **_kwargs: Any):
        requested = list(requested_urls)
        return _aligned_result(requested, [bodies[url] for url in requested])

    monkeypatch.setattr(scraper, "_list_article_payload", _articles)
    monkeypatch.setattr(scraper, "_list_section_codes", _sections)
    monkeypatch.setattr(
        scraper,
        "_fetch_maryland_section_catalog_frontier",
        _catalogs,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)
    captured = _capture_closure(monkeypatch, scraper, tmp_path)

    rows = await scraper._scrape_api_sections("Maryland Code", max_statutes=None)
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=_projection(scraper, rows),
    )

    assert retained_path == tmp_path / "md-closure.json"
    assert [row.section_number for row in rows] == ["1-101"]
    assert captured["completion"]["disposition"]["excluded"] == 1
    assert captured["completion"]["rights"]["basis"] == (
        "public_law_no_state_copyright"
    )
    assert captured["completion"]["transport"]["per_page_archive_loop"] is False


def _ne_body(section: str, *, terminal: bool = False) -> bytes:
    headnote = (
        "Repealed. Laws 2020, LB 1, § 1."
        if terminal
        else "Operative Nebraska provision."
    )
    paragraph = "" if terminal else (
        "<p>This operative Nebraska provision supplies complete official "
        "public-law text for exact normalization and indexing.</p>"
    )
    return (
        "<html><body><div id='stat_panel'><div class='statute'>"
        f"<h2>{section}.</h2><h3>{headnote}</h3>{paragraph}"
        "</div></div></body></html>"
    ).encode()


_NEBRASKA_CALENDAR_PROVISIONS = (
    (
        "38-1,102",
        "Appeal; procedure.",
        "Both parties to disciplinary proceedings under the Uniform "
        "Credentialing Act shall have the right of appeal, and the appeal "
        "shall be in accordance with the Administrative Procedure Act. The "
        "case shall be heard at a time fixed by the district court. It shall "
        "be advanced and take precedence over all other cases upon the court "
        "calendar except worker's compensation and criminal cases.",
    ),
    (
        "38-28,117",
        "Pharmacy; hospital pharmacy; inspection; requirements.",
        "Effective January 1, 2025, any self-inspection of a pharmacy or a "
        "hospital pharmacy shall be made using a form authorized by the board. "
        "The board shall authorize the form for use beginning January 1, 2025, "
        "on or before November 1, 2024, and such form shall remain in effect "
        "for a period of at least one year. Any updates to the form for "
        "subsequent years shall be authorized on or before November 1 of that "
        "year. If the board fails to authorize the form on or before November "
        "1 of any year, any inspection of a pharmacy or hospital pharmacy for "
        "the following calendar year shall be conducted by the board or "
        "department, as applicable.",
    ),
    (
        "44-3,107",
        "Equity securities insider trading; statement of certain owners; "
        "form; required; filing.",
        "Every domestic stock insurer shall file with the Director of "
        "Insurance, on such forms as the director may require, a separate "
        "statement for each person who is directly or indirectly the "
        "beneficial owner of more than ten percent of any class of any equity "
        "security of such insurer, and for each person who is a director or an "
        "officer of such insurer. The statement of the amount of all equity "
        "securities of such insurer, directly or indirectly owned by the "
        "individuals enumerated above, shall be filed with the director on or "
        "before January 1, 1970; within ten days after a person becomes an "
        "officer, director, or such beneficial owner; and within ten days "
        "after the close of each calendar month thereafter, if there has been "
        "a change in such ownership.",
    ),
    (
        "60-3,212",
        "Snowmobiles; refund of fees; when.",
        "Upon transfer of ownership of any snowmobile or in case of loss of "
        "possession because of fire, natural disaster, theft, dismantlement, "
        "or junking, its registration shall expire, and the registered owner "
        "may, by returning the registration certificate and after making "
        "affidavit of such transfer or loss to the county official who issued "
        "the certificate, receive a refund of that part of the unused fees "
        "based on the number of unexpired months remaining in the registration "
        "period, except that when such snowmobile is transferred within the "
        "same calendar month in which acquired, no refund shall be allowed for "
        "such month.",
    ),
    (
        "66-4,143",
        "Materiel administrator; submit report; contents.",
        "(1) The materiel administrator of the Department of Administrative "
        "Services shall on or before the tenth day of the fifth calendar month "
        "following the end of a semiannual period submit to the Department of "
        "Revenue a report providing the total cost and number of gallons of "
        "motor fuels purchased by the State of Nebraska during the preceding "
        "month. In providing such information, the materiel administrator "
        "shall total only those purchases which were fifty or more gallons and "
        "shall separately identify the amount of any state or federal tax "
        "which was included in the price paid. (2) The Department of Revenue "
        "shall provide any assistance the materiel administrator may need in "
        "performing his or her duties under this section.",
    ),
    (
        "77-27,166",
        "Submission of certified debt; when effective; Lottery Division of "
        "the Department of Revenue; duties.",
        "(1) The Department of Health and Human Services may submit any "
        "certified debt of twenty-five dollars or more to the Department of "
        "Revenue except when the validity of the debt is legitimately in "
        "dispute. The submission of debts of past due support shall be a "
        "continuous submission process that allows the amount of past due "
        "support to fluctuate up or down depending on the actual amount owed. "
        "Any submission shall be effective only to initiate setoff for a claim "
        "against a refund that would be made for the calendar year subsequent "
        "to the year in which such submission is made. (2) The Lottery "
        "Division of the Department of Revenue shall review all current debts "
        "on the records of the Department of Health and Human Services at the "
        "time of redeeming a lottery ticket for a state lottery prize to "
        "certify a debt owed by a winner of a state lottery prize.",
    ),
    (
        "77-27,222",
        "Internal Revenue Code amendment; Tax Commissioner; duties; report.",
        "(1) Within sixty days after an amendment of the Internal Revenue Code "
        "is enacted, the Tax Commissioner shall prepare and submit to the "
        "Governor, the Legislative Fiscal Analyst, the Speaker of the "
        "Legislature, and the chairpersons of the Executive Board of the "
        "Legislative Council, the Revenue Committee of the Legislature, and "
        "the Appropriations Committee of the Legislature a report that "
        "outlines: (a) The changes in the Internal Revenue Code; and (b) The "
        "impact of those changes on state revenue and on various classes and "
        "types of taxpayers. (2) Subsection (1) of this section does not apply "
        "to an amendment of the Internal Revenue Code if the Tax Commissioner "
        "determines that the impact of the amendment on state income tax "
        "revenue for the fiscal year that begins during the calendar year in "
        "which the amendment is enacted will be less than five million "
        "dollars.",
    ),
    (
        "81-2,254",
        "Single event food vendor, defined.",
        "Single event food vendor shall mean a temporary food establishment "
        "that operates at no more than one event per calendar year for a "
        "period of no more than four days.",
    ),
    (
        "81-6,114",
        "Hospital and ambulatory surgical center; reports required.",
        "(1) Every hospital or ambulatory surgical center licensed under the "
        "Health Care Facility Licensure Act shall annually report the "
        "following outpatient surgical and related information to the "
        "department no later than May 1 of each year for the preceding "
        "calendar year in a format as prescribed by the department in rule "
        "and regulation: (a) The name of the reporting facility; (b) The "
        "facility portion of billed charges for each patient served at such "
        "facility; (c) The county and state of residence by zip code for each "
        "patient served at such facility; (d) The primary outpatient surgical "
        "procedure performed for each patient at such facility; (e) The "
        "primary payor for each patient served at such facility; and (f) Such "
        "other outpatient surgical information as voluntarily reported by "
        "such facilities. (2) The department may impose a late fee for failure "
        "to report such information as required by this section.",
    ),
    (
        "83-4,121",
        "Disciplinary proceeding; when commenced; exception.",
        "No disciplinary proceeding shall be commenced more than eight "
        "calendar days after the infraction or the discovery of such "
        "infraction unless the committed person is unable or unavailable for "
        "any reason to participate in a disciplinary proceeding.",
    ),
)


def _source_bound_nebraska_calendar_row(
    scraper: NebraskaScraper,
    section_number: str,
    section_name: str,
    full_text: str,
) -> Any:
    source_url = (
        "https://nebraskalegislature.gov/laws/statutes.php?statute="
        f"{section_number}"
    )
    html = _ne_body(section_number).decode().replace(
        "Operative Nebraska provision.",
        section_name,
    ).replace(
        "This operative Nebraska provision supplies complete official "
        "public-law text for exact normalization and indexing.",
        full_text,
    )
    return scraper._build_statute_from_section_html(
        "Nebraska Revised Statutes",
        source_url,
        html,
        discovery_method="official_chapter_index_sections",
        strict=True,
    )


def test_nebraska_terminal_parser_is_identity_bound_and_body_defeated() -> None:
    url = "https://nebraskalegislature.gov/laws/statutes.php?statute=1-102"
    terminal = _ne_body("1-102", terminal=True).decode()
    operative = terminal.replace(
        "</h3>",
        "</h3><p>This operative paragraph defeats terminal classification.</p>",
    )

    assert classify_nebraska_terminal_section_html(terminal, source_url=url) == (
        "repealed"
    )
    assert parse_nebraska_section_html(terminal, source_url=url) is None
    assert classify_nebraska_terminal_section_html(operative, source_url=url) is None
    assert parse_nebraska_section_html(
        _ne_body("1-999").decode(),
        source_url=url,
    ) is None


def test_nebraska_parser_admits_identity_bound_direct_text_only() -> None:
    url = "https://nebraskalegislature.gov/laws/statutes.php?statute=29-4808"
    operative_text = (
        "Sections 29-4801 to 29-4807 apply on and after July 1, 2027."
    )
    html = (
        "<html><body><div id='stat_panel'><div class='statute'>"
        "<h2>29-4808.</h2>"
        "<h3>Veteran justice program; veteran sentencing considerations; "
        "training; reports; applicability of provisions.</h3>"
        f"\n {operative_text}<div><h2>Source</h2>"
        "<ul class='fa-ul'><li>Laws 2025, LB150, § 40.</li></ul></div>"
        "</div></div>"
        "<nav>Chapter 29 Index and unrelated site navigation.</nav>"
        "</body></html>"
    )

    parsed = parse_nebraska_section_html(html, source_url=url)

    assert parsed is not None
    assert parsed.section_number == "29-4808"
    assert parsed.full_text == operative_text
    assert "Source" not in parsed.full_text
    assert "LB150" not in parsed.full_text
    assert classify_nebraska_terminal_section_html(html, source_url=url) is None
    assert parse_nebraska_section_html(
        html,
        source_url=url.replace("29-4808", "29-4807"),
    ) is None


def test_nebraska_direct_text_defeats_terminal_headnote() -> None:
    url = "https://nebraskalegislature.gov/laws/statutes.php?statute=1-102"
    html = _ne_body("1-102", terminal=True).decode().replace(
        "</h3>",
        "</h3>Operative text controls despite the terminal-looking headnote.",
    )

    assert classify_nebraska_terminal_section_html(html, source_url=url) is None
    parsed = parse_nebraska_section_html(html, source_url=url)
    assert parsed is not None
    assert parsed.full_text == (
        "Operative text controls despite the terminal-looking headnote."
    )


def test_nebraska_displayed_locator_allows_space_before_final_period() -> None:
    url = "https://nebraskalegislature.gov/laws/statutes.php?statute=38-507"
    operative = _ne_body("38-507").decode().replace(
        "<h2>38-507.</h2>",
        "<h2>38-507 .\n</h2>",
    )
    terminal = _ne_body("38-507", terminal=True).decode().replace(
        "<h2>38-507.</h2>",
        "<h2>38-507 .\n</h2>",
    )

    parsed = parse_nebraska_section_html(operative, source_url=url)
    assert parsed is not None
    assert parsed.section_number == "38-507"
    assert classify_nebraska_terminal_section_html(
        terminal,
        source_url=url,
    ) == "repealed"


@pytest.mark.parametrize(
    ("section_number", "section_name", "full_text"),
    _NEBRASKA_CALENDAR_PROVISIONS,
)
def test_nebraska_source_bound_calendar_provisions_survive_shared_filter(
    section_number: str,
    section_name: str,
    full_text: str,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    row = _source_bound_nebraska_calendar_row(
        scraper,
        section_number,
        section_name,
        full_text,
    )

    assert row is not None
    assert _filter_strict_full_text_statutes(
        [row],
        min_full_text_chars=1,
    ) == ([], 1)
    assert scraper._is_source_bound_operative_statute_record(row) is True
    assert scraper._is_low_quality_statute_record(row) is False
    assert _filter_strict_full_text_statutes(
        [row],
        min_full_text_chars=1,
        source_bound_operative_checker=(
            scraper._is_source_bound_operative_statute_record
        ),
    ) == ([row], 0)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("state_code", "NV"),
        ("state_name", "Not Nebraska"),
        ("code_name", "Nebraska Administrative Code"),
        ("statute_id", "Nebraska Revised Statutes § 38-1,103"),
        ("official_cite", "Neb. Rev. Stat. § 38-1,103"),
        ("chapter_number", "39"),
        ("section_number", "38-1,103"),
        (
            "source_url",
            "https://example.gov/laws/statutes.php?statute=38-1,102",
        ),
        (
            "section_name",
            "Official viewer Skip navigation Home Documents",
        ),
        (
            "full_text",
            "Official statute viewer. Skip navigation Home Documents Login "
            "Contact Us",
        ),
        ("full_text", "Repealed. Laws 2020, LB 1, § 1."),
        ("full_text", "Section Section-1: Navigation scaffold"),
    ),
)
def test_nebraska_source_bound_admission_rejects_forged_rows(
    field: str,
    value: str,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    row = _source_bound_nebraska_calendar_row(
        scraper,
        *_NEBRASKA_CALENDAR_PROVISIONS[0],
    )
    assert row is not None
    forged = copy.deepcopy(row)
    setattr(forged, field, value)

    assert scraper._is_source_bound_operative_statute_record(forged) is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_kind", "official-looking-html"),
        ("source_authority_class", "aggregator"),
        ("discovery_method", "generic_link_crawl"),
        ("skip_hydrate", False),
    ),
)
def test_nebraska_source_bound_admission_rejects_forged_provenance(
    field: str,
    value: Any,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    row = _source_bound_nebraska_calendar_row(
        scraper,
        *_NEBRASKA_CALENDAR_PROVISIONS[0],
    )
    assert row is not None
    forged = copy.deepcopy(row)
    forged.structured_data[field] = value

    assert scraper._is_source_bound_operative_statute_record(forged) is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("@id", "urn:state:ne:statute:forged"),
        ("name", "Forged title"),
        ("sectionName", "Forged title"),
        ("sectionNumber", "38-1,103"),
        (
            "sourceUrl",
            "https://nebraskalegislature.gov/laws/statutes.php?statute=38-1,103",
        ),
        ("stateCode", "NV"),
        ("stateName", "Not Nebraska"),
        ("text", "Forged normalized text"),
    ),
)
def test_nebraska_source_bound_admission_rejects_jsonld_drift(
    field: str,
    value: str,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    raw = _source_bound_nebraska_calendar_row(
        scraper,
        *_NEBRASKA_CALENDAR_PROVISIONS[0],
    )
    assert raw is not None
    assert scraper._is_source_bound_operative_statute_record(raw) is True
    row = scraper._enrich_statute_structure(raw)
    assert scraper._is_source_bound_operative_statute_record(row) is True
    forged = copy.deepcopy(row)
    forged.structured_data["jsonld"][field] = value

    assert scraper._is_source_bound_operative_statute_record(forged) is False


@pytest.mark.parametrize("value", ("forged", [], 7, False))
def test_nebraska_source_bound_admission_rejects_non_mapping_jsonld(
    value: Any,
) -> None:
    scraper = NebraskaScraper("NE", "Nebraska")
    row = _source_bound_nebraska_calendar_row(
        scraper,
        *_NEBRASKA_CALENDAR_PROVISIONS[0],
    )
    assert row is not None
    row.structured_data["jsonld"] = value

    assert scraper._is_source_bound_operative_statute_record(row) is False


@pytest.mark.parametrize(
    ("headnote", "expected"),
    (
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
    ),
)
def test_nebraska_exact_no_body_lifecycle_notes_are_terminal(
    headnote: str,
    expected: str,
) -> None:
    url = "https://nebraskalegislature.gov/laws/statutes.php?statute=1-102"
    terminal = _ne_body("1-102", terminal=True).decode().replace(
        "Repealed. Laws 2020, LB 1, § 1.",
        headnote,
    )
    operative = terminal.replace(
        "</h3>",
        "</h3><p>An exact operative body defeats lifecycle-note typing.</p>",
    )

    assert classify_nebraska_terminal_section_html(
        terminal,
        source_url=url,
    ) == expected
    assert parse_nebraska_section_html(terminal, source_url=url) is None
    assert classify_nebraska_terminal_section_html(operative, source_url=url) is None
    assert parse_nebraska_section_html(operative, source_url=url) is not None


def test_nebraska_catalog_uses_only_primary_row_locator() -> None:
    html = """
    <table><tr><td class='row'>
      <span><a href='/laws/statutes.php?statute=14-3,100'>
        <span class='sr-only'>View Statute </span>14-3,100
      </a></span>
      <span>Transferred to section
        <a href='/laws/statutes.php?statute=32-1057'>32-1057</a>.
      </span>
      <span><a href='/laws/statutes.php?statute=14-3,100&print=true'>Print</a></span>
    </td></tr></table>
    """

    assert section_links(html) == [
        (
            "14-3,100",
            "Transferred to section 32-1057 .",
            "https://nebraskalegislature.gov/laws/statutes.php?statute=14-3,100",
        )
    ]
    expired_url = (
        "https://nebraskalegislature.gov/laws/statutes.php?statute=18-1732"
    )
    expired = _ne_body("18-1732").decode().replace(
        "Operative Nebraska provision.</h3><p>This operative Nebraska provision "
        "supplies complete official public-law text for exact normalization and "
        "indexing.</p>",
        "Expiration of act.</h3>",
    )
    assert classify_nebraska_terminal_section_html(
        expired,
        source_url=expired_url,
    ) == "expired"

    deleted_url = (
        "https://nebraskalegislature.gov/laws/statutes.php?statute=25-1286"
    )
    deleted = _ne_body("25-1286").decode().replace(
        "Operative Nebraska provision.</h3><p>This operative Nebraska provision "
        "supplies complete official public-law text for exact normalization and "
        "indexing.</p>",
        "Deleted.</h3>",
    )
    assert classify_nebraska_terminal_section_html(
        deleted,
        source_url=deleted_url,
    ) == "deleted"
    assert parse_nebraska_section_html(deleted, source_url=deleted_url) is None


@pytest.mark.anyio
async def test_nebraska_closure_replays_catalogs_and_excludes_terminal_stub(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    scraper = NebraskaScraper("NE", "Nebraska")
    root_url = scraper.OFFICIAL_ENTRY_URL
    chapter_url = (
        "https://nebraskalegislature.gov/laws/browse-chapters.php?chapter=1"
    )
    section_urls = [
        "https://nebraskalegislature.gov/laws/statutes.php?statute=1-101",
        "https://nebraskalegislature.gov/laws/statutes.php?statute=1-102",
    ]
    root = (
        "<a href='/laws/browse-chapters.php?chapter=1'>Chapter 1</a>"
    ).encode()
    chapter = (
        "<a href='/laws/statutes.php?statute=1-101'>1-101</a>"
        "<a href='/laws/statutes.php?statute=1-102'>1-102</a>"
    ).encode()
    bodies = {
        section_urls[0]: _ne_body("1-101"),
        section_urls[1]: _ne_body("1-102", terminal=True),
    }
    ledger = _MemoryLedger(
        [
            (root_url, {"method": "GET", "url": root_url}, root, {}),
            (
                chapter_url,
                {"method": "GET", "url": chapter_url},
                chapter,
                {},
            ),
            *[
                (url, {"method": "GET", "url": url}, bodies[url], {})
                for url in section_urls
            ],
        ]
    )
    scraper._state_law_acquisition_ledger = ledger

    async def _chapters() -> list[str]:
        return [chapter_url]

    async def _chapter_frontier(requested_urls: list[str]) -> list[bytes]:
        assert list(requested_urls) == [chapter_url]
        return [chapter]

    async def _plural(requested_urls: list[str], **_kwargs: Any):
        requested = list(requested_urls)
        return _aligned_result(requested, [bodies[url] for url in requested])

    monkeypatch.setattr(scraper, "_discover_chapter_urls", _chapters)
    monkeypatch.setattr(
        scraper,
        "_fetch_nebraska_chapter_frontier_batch",
        _chapter_frontier,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _plural,
    )
    monkeypatch.setattr(scraper, "_load_partial_checkpoint_statutes", lambda **_k: [])
    monkeypatch.setattr(scraper, "_load_partial_checkpoint_progress", lambda: {})
    monkeypatch.setattr(scraper, "_write_partial_checkpoint", lambda *_a, **_k: True)
    captured = _capture_closure(monkeypatch, scraper, tmp_path)

    rows = await scraper._scrape_official_index(
        "Nebraska Revised Statutes",
        max_statutes=None,
    )
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=_projection(scraper, rows),
    )

    assert retained_path == tmp_path / "ne-closure.json"
    assert [row.section_number for row in rows] == ["1-101"]
    assert captured["completion"]["disposition"] == {
        "discovered": 2,
        "duplicates": 0,
        "excluded": 1,
        "failed_final": 0,
        "fetched": 1,
        "quarantined": 0,
    }
    assert captured["completion"]["rights"] == {
        "basis": "public_law_no_state_copyright",
        "decision": "admit",
        "scope": "statutory_text",
    }
    assert captured["completion"]["replay"]["network_requests"] == 0
    assert captured["completion"]["transport"]["leaf_frontier_requested_pages"] == 2
    assert captured["completion"]["transport"]["grouped_warc_recovery"] is True
    assert captured["completion"]["transport"]["per_page_archive_loop"] is False
    assert captured["completion"]["transport"]["residual_only_retries"] is True
    assert captured["completion"]["transport"]["wayback_prefix_inventory"] is True
