from __future__ import annotations

import csv
import hashlib
import io
from datetime import date
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
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.virginia import (
    VirginiaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.virginia_csv import (
    VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION,
    VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE,
    VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_STATUS,
    VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_URL,
    parse_virginia_title_csv_closure,
    virginia_current_section_frontier,
    virginia_official_empty_placeholder_evidence,
    virginia_title_csv_url,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


_FIELDS = (
    "TitleNum",
    "TitleName",
    "SubTitleNum",
    "SubTitleName",
    "PartNum",
    "PartName",
    "ChapterNum",
    "ChapterName",
    "ArticleNum",
    "ArticleName",
    "SubPartNum",
    "SubPartName",
    "Section",
    "Title",
    "Body",
)


def _csv_payload(title: str, rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_FIELDS)
    writer.writeheader()
    for raw in rows:
        row = {field: "" for field in _FIELDS}
        row.update(
            {
                "TitleNum": title,
                "TitleName": f"Title {title} Test",
                "ChapterNum": "1",
                "ChapterName": "Test Chapter",
            }
        )
        row.update(raw)
        writer.writerow(row)
    return stream.getvalue().encode()


def _operative_body(marker: str) -> str:
    return (
        f"<p>{marker} supplies complete official Virginia statutory text for "
        "normalization and exact source reconciliation.</p>"
        "<p>2026, c. 1.</p>"
    )


def _official_empty_placeholder_csv(
    *,
    section: str = VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION,
    title: str = VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE,
    body: str = "",
) -> bytes:
    return _csv_payload(
        "19.2",
        [
            {
                "TitleName": "CRIMINAL PROCEDURE",
                "ChapterNum": "25",
                "ChapterName": "APPEALS BY THE COMMONWEALTH",
                "Section": section,
                "Title": title,
                "Body": body,
            }
        ],
    )


def _current_section_page(section: str, body: str) -> bytes:
    return (
        "<html><body><div id='va_code'>"
        f"<h2>§ {section}. Current section</h2>{body}"
        "</div></body></html>"
    ).encode()


def _multi_branch_current_section_page(
    section: str,
    *,
    document_title: str,
    branches: list[tuple[str, str]],
) -> bytes:
    rendered = "".join(
        f"<h2>§ {section} . {branch_title}.</h2>"
        f"<section class='body editable'>{body}</section>"
        for branch_title, body in branches
    )
    return (
        "<html><head>"
        f"<title>§ {section}. {document_title}</title>"
        "</head><body><div id='va_code'>"
        f"{rendered}"
        "</div></body></html>"
    ).encode()


def _official_empty_placeholder_page(
    *,
    section: str = VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION,
    title: str = VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE,
    body_markup: str = " \r\n\t",
    extra_branch: str = "",
) -> bytes:
    return (
        "<html><head>"
        f"<title>§ {section}. {title}</title>"
        "</head><body>"
        f"<input type='hidden' id='hidSegments' value='{section}' />"
        "<article id='vacode' class='content'>"
        "<span id='va_code' class='content'>"
        f"<h2><span id='v0'>§ {section}</span>. {title}.</h2>"
        "<section class='body editable' id='edit3886' "
        f"data-table='CoV' data-field='body'>{body_markup}</section>"
        f"{extra_branch}"
        "</span></article></body></html>"
    ).encode()


def _library_html(titles: list[tuple[str, str]]) -> bytes:
    rows = "".join(
        "<tr>"
        f"<td class='child'>Title {number}: {name}</td>"
        f"<td><a href='/CSV/CoVTitle_{number}.csv'>CSV</a></td>"
        "</tr>"
        for number, name in titles
    )
    return (
        "<html><head><title>Virginia Law Online Library</title></head><body>"
        "<h2>Virginia Law Online Library</h2><table>"
        + rows
        + "</table>"
        + (" " * 6_000)
        + "</body></html>"
    ).encode()


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
    *,
    errors: list[str | None] | None = None,
) -> StateLawPageMultiFetchResult:
    return StateLawPageMultiFetchResult(
        urls=list(urls),
        payloads=list(payloads),
        errors=list(errors or [None] * len(urls)),
        transport_receipts=[
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(body).hexdigest() if body else "",
                "source_transport": "direct",
            }
            for url, body in zip(urls, payloads, strict=True)
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


class _RetainedInputLedger:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = dict(payloads)
        self.plural_requests: list[list[tuple[str, dict]]] = []

    def refresh_existing_entries(self) -> None:
        return None

    def replay_retained_parser_input(self, **_kwargs):
        raise AssertionError("Virginia certification must use plural retained replay")

    def replay_retained_parser_inputs(self, *, requests):
        normalized = [(url, dict(request)) for url, request in requests]
        self.plural_requests.append(normalized)
        retained = []
        for official_url, _request in normalized:
            payload = self.payloads.get(official_url)
            if payload is None:
                raise RuntimeError(f"missing retained input: {official_url}")
            digest = hashlib.sha256(payload).hexdigest()
            retained.append(
                SimpleNamespace(
                    envelope=SimpleNamespace(body=payload),
                    receipt=SimpleNamespace(
                        content=SimpleNamespace(sha256=digest)
                    ),
                    transport_receipt={
                        "official_url": official_url,
                        "content_sha256": digest,
                        "source_transport": "retained_acquisition_replay",
                    },
                )
            )
        return tuple(retained)


def _canonical_projection(scraper: VirginiaScraper, rows):
    return build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction="VA",
    )


def test_virginia_csv_parser_closes_terminals_and_contingent_variants() -> None:
    payload = _csv_payload(
        "1",
        [
            {
                "Section": "1-1",
                "Title": "Operative section",
                "Body": _operative_body("Current section"),
            },
            {
                "Section": "1-2",
                "Title": "Repealed",
                "Body": "<p>Repealed by Acts 2020, c. 1.</p>",
            },
            {
                "Section": "1-3",
                "Title": "Reserved powers of the Commonwealth",
                "Body": _operative_body("Reserved powers remain operative"),
            },
            {
                "Section": "1-600",
                "Title": "(For contingent expiration date, see cl. 2) Coordinate system",
                "Body": _operative_body("Pre-contingency section"),
            },
            {
                "Section": "1-600",
                "Title": "(For contingent effective date, see cl. 2) Coordinate system",
                "Body": _operative_body("Post-contingency section"),
            },
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="1",
        expected_title_name="General Provisions",
        current_section_pages={
            "https://law.lis.virginia.gov/vacode/title1/chapter1/section1-600/": (
                _current_section_page(
                    "1-600", _operative_body("Pre-contingency section")
                )
            )
        },
    )

    assert report.closed is True
    assert report.source_record_count == 5
    assert [row.section_number for row in report.statutes] == ["1-1", "1-3", "1-600"]
    assert "Pre-contingency" in report.statutes[2].full_text
    assert [row["disposition"] for row in report.terminal_records] == [
        "repealed",
        "future_contingent_variant",
    ]
    assert report.statutes[2].structured_data["effective_variant_count"] == 2


def test_virginia_csv_parser_selects_document_titled_nested_body_branch() -> None:
    expiration_title = "(Contingent expiration date) Imposition of sales tax"
    effective_title = "(Contingent effective date) Imposition of sales tax"
    expiration_body = _operative_body("Expiration branch only")
    effective_body = _operative_body("Effective branch only")
    payload = _csv_payload(
        "58.1",
        [
            {
                "Section": "58.1-603",
                "Title": expiration_title,
                "Body": expiration_body,
            },
            {
                "Section": "58.1-603",
                "Title": effective_title,
                "Body": effective_body,
            },
        ],
    )
    source_url = (
        "https://law.lis.virginia.gov/vacode/title58.1/chapter1/section58.1-603/"
    )
    page = _multi_branch_current_section_page(
        "58.1-603",
        document_title=effective_title,
        branches=[
            (expiration_title, expiration_body),
            (effective_title, effective_body),
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="58.1",
        current_section_pages={source_url: page},
    )

    assert report.closed is True
    assert len(report.statutes) == 1
    statute = report.statutes[0]
    assert "Effective branch only" in statute.full_text
    assert "Expiration branch only" not in statute.full_text
    assert statute.structured_data["contingent_current_branch_count"] == 2
    assert (
        statute.structured_data["contingent_current_document_title"] == effective_title
    )
    assert statute.structured_data["contingent_current_branch_title"] == effective_title
    assert statute.structured_data["contingent_selected_role"] == "after"
    assert [row["disposition"] for row in report.terminal_records] == [
        "superseded_contingent_variant"
    ]


def test_virginia_csv_parser_aligns_source_evolved_contingent_branches() -> None:
    expiration_title = "(Contingent expiration date — see note) Exemptions"
    effective_title = "(Contingent effective date — see note) Exemptions"
    page_expiration_title = (
        "(For contingent expiration date, see Acts 2013, c. 766, cl. 14) "
        "Exemptions"
    )
    page_effective_title = (
        "(For contingent effective date, see Acts 2013, c. 766, cl. 14) "
        "Exemptions"
    )
    expiration_body = _operative_body("Expiration branch " * 40)
    effective_body = _operative_body("Effective branch " * 40)
    evolved_expiration_body = expiration_body.replace(
        "normalization", "current-source normalization"
    )
    evolved_effective_body = effective_body.replace(
        "normalization", "current-source normalization"
    )
    payload = _csv_payload(
        "58.1",
        [
            {
                "Section": "58.1-811",
                "Title": expiration_title,
                "Body": expiration_body,
            },
            {
                "Section": "58.1-811",
                "Title": effective_title,
                "Body": effective_body,
            },
        ],
    )
    source_url = (
        "https://law.lis.virginia.gov/vacode/title58.1/chapter1/section58.1-811/"
    )
    page = _multi_branch_current_section_page(
        "58.1-811",
        document_title=page_effective_title,
        branches=[
            (page_expiration_title, evolved_expiration_body),
            (page_effective_title, evolved_effective_body),
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="58.1",
        current_section_pages={source_url: page},
    )

    assert report.closed is True
    assert len(report.statutes) == 1
    statute = report.statutes[0]
    assert "current-source normalization" in statute.full_text
    assert statute.structured_data["contingent_selected_role"] == "after"
    assert (
        statute.structured_data["effective_variant_selection"]
        == "official_document_contingent_role_alignment"
    )
    assert (
        statute.structured_data["contingent_body_alignment"]
        == "mutual_unique_role_similarity_v1"
    )


def test_virginia_csv_parser_selects_pre_effective_calendar_successor() -> None:
    expiration_title = "(Contingent expiration date — see note) Current rule"
    effective_title = "(Contingent effective date — see note) Current rule"
    page_expiration_title = (
        "(For contingent expiration date, see Acts 2023, c. 738, cl. 2) "
        "Current rule"
    )
    page_effective_title = (
        "(For contingent effective date, see Acts 2023, c. 738, cl. 2) "
        "Current rule"
    )
    successor_title = "(Effective July 1, 2027) Future successor rule"
    expiration_body = _operative_body("Expiration branch " * 40)
    effective_body = _operative_body("Effective branch " * 40)
    evolved_effective_body = effective_body.replace(
        "normalization", "current-source normalization"
    )
    successor_body = _operative_body("Future successor " * 40)
    payload = _csv_payload(
        "15.2",
        [
            {
                "Section": "15.2-968.1",
                "Title": expiration_title,
                "Body": expiration_body,
            },
            {
                "Section": "15.2-968.1",
                "Title": effective_title,
                "Body": effective_body,
            },
        ],
    )
    source_url = (
        "https://law.lis.virginia.gov/vacode/title15.2/chapter1/"
        "section15.2-968.1/"
    )
    page = _multi_branch_current_section_page(
        "15.2-968.1",
        document_title=successor_title,
        branches=[
            (page_expiration_title, expiration_body),
            (page_effective_title, evolved_effective_body),
            (successor_title, successor_body),
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="15.2",
        observation_date=date(2026, 8, 26),
        current_section_pages={source_url: page},
    )
    no_date = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="15.2",
        current_section_pages={source_url: page},
    )
    successor_effective = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="15.2",
        observation_date=date(2027, 7, 1),
        current_section_pages={source_url: page},
    )

    assert report.closed is True
    statute = report.statutes[0]
    assert "current-source normalization" in statute.full_text
    assert "Future successor" not in statute.full_text
    assert (
        statute.structured_data["effective_variant_selection"]
        == "pre_effective_calendar_successor_contingent_alignment"
    )
    assert no_date.closed is False
    assert successor_effective.closed is False


def test_virginia_csv_parser_rejects_nested_branch_title_body_swap() -> None:
    expiration_title = "(Contingent expiration date) Imposition of sales tax"
    effective_title = "(Contingent effective date) Imposition of sales tax"
    expiration_body = _operative_body("Expiration branch only")
    effective_body = _operative_body("Effective branch only")
    payload = _csv_payload(
        "58.1",
        [
            {
                "Section": "58.1-603",
                "Title": expiration_title,
                "Body": expiration_body,
            },
            {
                "Section": "58.1-603",
                "Title": effective_title,
                "Body": effective_body,
            },
        ],
    )
    source_url = (
        "https://law.lis.virginia.gov/vacode/title58.1/chapter1/section58.1-603/"
    )
    page = _multi_branch_current_section_page(
        "58.1-603",
        document_title=effective_title,
        branches=[
            (expiration_title, effective_body),
            (effective_title, expiration_body),
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="58.1",
        current_section_pages={source_url: page},
    )

    assert report.closed is False
    assert report.statutes == []
    assert {row["reason"] for row in report.unclassified_records} == {
        "contingent_current_section_title_body_mismatch",
        "unused_current_section_page",
    }


def test_virginia_csv_parser_selects_calendar_and_taxable_year_variants() -> None:
    payload = _csv_payload(
        "1",
        [
            {
                "Section": "1-10",
                "Title": "(Effective until July 1, 2026) Old calendar text",
                "Body": _operative_body("Expired calendar branch"),
            },
            {
                "Section": "1-10",
                "Title": "(Effective July 1, 2026) Current calendar text",
                "Body": _operative_body("Current calendar branch"),
            },
            {
                "Section": "1-11",
                "Title": "(Effective until July 1, 2027) Current future-switch text",
                "Body": _operative_body("Current pre-switch branch"),
            },
            {
                "Section": "1-11",
                "Title": "(Effective July 1, 2027) Future calendar text",
                "Body": _operative_body("Future post-switch branch"),
            },
            {
                "Section": "1-12",
                "Title": (
                    "(Applicable to taxable years beginning on and after "
                    "January 1, 2019, but before January 1, 2028) Current tax text"
                ),
                "Body": _operative_body("Current taxable-year branch"),
            },
            {
                "Section": "1-12",
                "Title": (
                    "(Applicable to taxable years beginning January 1, 2028) "
                    "Future tax text"
                ),
                "Body": _operative_body("Future taxable-year branch"),
            },
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="1",
        observation_date=date(2026, 8, 26),
    )

    assert report.closed is True
    assert [row.section_number for row in report.statutes] == ["1-10", "1-11", "1-12"]
    assert "Current calendar branch" in report.statutes[0].full_text
    assert "Current pre-switch branch" in report.statutes[1].full_text
    assert "Current taxable-year branch" in report.statutes[2].full_text
    assert [row["disposition"] for row in report.terminal_records] == [
        "expired_calendar_variant",
        "future_calendar_variant",
        "future_taxable_year_variant",
    ]


def test_virginia_csv_parser_handles_source_declared_later_of_lower_bound() -> None:
    payload = _csv_payload(
        "55.1",
        [
            {
                "Section": "55.1-1245",
                "Title": (
                    "(Effective until the later of July 1, 2028, or seven years "
                    "after the COVID-19 pandemic state of emergency expires) Old"
                ),
                "Body": _operative_body("Current compound branch"),
            },
            {
                "Section": "55.1-1245",
                "Title": (
                    "(Effective the later of July 1, 2028, or 7 years after the "
                    "COVID-19 pandemic state of emergency expires) New"
                ),
                "Body": _operative_body("Later compound branch"),
            },
        ],
    )

    before = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="55.1",
        observation_date=date(2026, 8, 26),
    )
    unresolved = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="55.1",
        observation_date=date(2028, 7, 1),
    )

    assert before.closed is True
    assert "Current compound branch" in before.statutes[0].full_text
    assert unresolved.closed is False
    assert {row["reason"] for row in unresolved.unclassified_records} == {
        "compound_calendar_variant_trigger_not_source_resolved"
    }


def test_virginia_csv_parser_fails_closed_on_forged_calendar_pair() -> None:
    payload = _csv_payload(
        "1",
        [
            {
                "Section": "1-20",
                "Title": "(Effective until July 1, 2026) Old",
                "Body": _operative_body("Old"),
            },
            {
                "Section": "1-20",
                "Title": "(Effective July 1, 2027) Forged mismatch",
                "Body": _operative_body("Forged"),
            },
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="1",
        observation_date=date(2026, 8, 26),
    )

    assert report.closed is False
    assert {row["reason"] for row in report.unclassified_records} == {
        "incomplete_or_mismatched_calendar_variant_pair"
    }


def test_virginia_csv_parser_hydrates_only_identity_bound_empty_body() -> None:
    payload = _csv_payload(
        "19.2",
        [
            {
                "Section": "19.2-399",
                "Title": "Defense objections to be raised before trial",
                "Body": "",
            }
        ],
    )
    source_url = (
        "https://law.lis.virginia.gov/vacode/"
        "title19.2/chapter1/section19.2-399/"
    )
    body = _operative_body("Hydrated current section")

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="19.2",
        current_section_pages={
            source_url: _current_section_page("19.2-399", body)
        },
    )
    forged = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="19.2",
        current_section_pages={
            source_url: _current_section_page("19.2-400", body)
        },
    )

    assert report.closed is True
    assert "Hydrated current section" in report.statutes[0].full_text
    assert forged.closed is False
    assert {row["reason"] for row in forged.unclassified_records} == {
        "operative_current_section_identity_mismatch",
        "unused_current_section_page",
    }


def test_virginia_csv_parser_classifies_exact_official_empty_placeholder() -> None:
    payload = _official_empty_placeholder_csv()
    page = _official_empty_placeholder_page()

    assert virginia_current_section_frontier(
        payload,
        expected_title_number="19.2",
    ) == [
        (
            VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION,
            VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_URL,
            "official_empty_placeholder_witness",
        )
    ]
    page_evidence = virginia_official_empty_placeholder_evidence(page)
    assert page_evidence == {
        "source_status": VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_STATUS,
        "section_number": VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION,
        "section_title": VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE,
        "official_operative_body_text_length": 0,
        "official_operative_body_text_sha256": hashlib.sha256(b"").hexdigest(),
        "official_body_node_count": 1,
        "official_alternate_body_count": 0,
        "current_section_page_sha256": hashlib.sha256(page).hexdigest(),
    }
    assert VirginiaScraper._is_valid_virginia_current_section_page(page) is True
    assert (
        VirginiaScraper._is_valid_virginia_official_empty_placeholder_page(page)
        is True
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="19.2",
        expected_title_name="Criminal Procedure",
        source_bundle_url=virginia_title_csv_url("19.2"),
        current_section_pages={VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_URL: page},
    )

    assert report.closed is True
    assert report.source_record_count == 1
    assert report.statutes == []
    assert report.terminal_records == []
    assert report.unclassified_records == []
    assert len(report.source_status_records) == 1
    status = report.source_status_records[0]
    assert status["source_status"] == VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_STATUS
    assert status["section_number"] == VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION
    assert status["section_title"] == VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE
    assert status["official_operative_body_text_length"] == 0
    assert status["source_csv_body_text_length"] == 0
    assert status["current_section_page_sha256"] == hashlib.sha256(page).hexdigest()


@pytest.mark.parametrize(
    ("payload", "page", "page_is_exact_placeholder"),
    [
        (
            _official_empty_placeholder_csv(section="19.2-398.1"),
            _official_empty_placeholder_page(section="19.2-398.1"),
            False,
        ),
        (
            _official_empty_placeholder_csv(title="Different official title"),
            _official_empty_placeholder_page(),
            True,
        ),
        (
            _official_empty_placeholder_csv(),
            _official_empty_placeholder_page(title="Different official title"),
            False,
        ),
        (
            _official_empty_placeholder_csv(),
            _official_empty_placeholder_page(
                extra_branch=(
                    "<section class='body editable' id='edit9999' "
                    "data-table='CoV' data-field='body'> </section>"
                )
            ),
            False,
        ),
        (
            _official_empty_placeholder_csv(),
            _official_empty_placeholder_page().replace(
                b"<section class='body editable' id='edit3886' "
                b"data-table='CoV' data-field='body'> \r\n\t</section>",
                b"",
            ),
            False,
        ),
    ],
)
def test_virginia_official_empty_placeholder_rejects_ambiguity(
    payload: bytes,
    page: bytes,
    page_is_exact_placeholder: bool,
) -> None:
    evidence = virginia_official_empty_placeholder_evidence(page)
    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="19.2",
        expected_title_name="Criminal Procedure",
        source_bundle_url=virginia_title_csv_url("19.2"),
        current_section_pages={VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_URL: page},
    )

    assert bool(evidence) is page_is_exact_placeholder
    assert report.closed is False
    assert report.statutes == []
    assert report.terminal_records == []
    assert report.source_status_records == []
    assert report.unclassified_records


def test_virginia_csv_parser_fails_closed_on_unmarked_duplicate() -> None:
    payload = _csv_payload(
        "2.2",
        [
            {
                "Section": "2.2-1",
                "Title": "First version",
                "Body": _operative_body("First"),
            },
            {
                "Section": "2.2-1",
                "Title": "Second version",
                "Body": _operative_body("Second"),
            },
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="2.2",
    )

    assert report.closed is False
    assert report.statutes == []
    assert {row["reason"] for row in report.unclassified_records} == {
        "unresolved_duplicate_section_identity"
    }


def test_virginia_csv_parser_accounts_for_repeated_terminal_identity() -> None:
    payload = _csv_payload(
        "1",
        [
            {
                "Section": "1-9",
                "Title": "Repealed",
                "Body": "<p>Repealed by Acts 2020, c. 1.</p>",
            },
            {
                "Section": "1-9",
                "Title": "Reserved",
                "Body": "<p>Reserved.</p>",
            },
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="1",
    )

    assert report.closed is True
    assert report.source_record_count == 2
    assert report.statutes == []
    assert [row["disposition"] for row in report.terminal_records] == [
        "repealed",
        "reserved",
    ]


def test_virginia_csv_parser_fails_closed_on_mixed_terminal_duplicate() -> None:
    payload = _csv_payload(
        "1",
        [
            {
                "Section": "1-9",
                "Title": "Repealed",
                "Body": "<p>Repealed by Acts 2020, c. 1.</p>",
            },
            {
                "Section": "1-9",
                "Title": "Operative version",
                "Body": _operative_body("Unmarked concurrent text"),
            },
        ],
    )

    report = parse_virginia_title_csv_closure(
        payload,
        expected_title_number="1",
    )

    assert report.closed is False
    assert report.statutes == []
    assert report.terminal_records == []
    assert {row["reason"] for row in report.unclassified_records} == {
        "mixed_terminal_and_operative_duplicate_identity"
    }


def test_virginia_current_catalog_contract_requires_groupable_exact_76(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_SCRAPER_VA_FRONTIER_BATCH_SIZE", "1")
    scraper = VirginiaScraper("VA", "Virginia")

    assert scraper.STRICT_EXPECTED_TITLE_CSVS == 76
    assert scraper.STRICT_EXPECTED_CONTINGENT_SECTION_PAGES == 32
    assert scraper.STRICT_EXPECTED_BODY_HYDRATION_PAGES == 0
    assert scraper.STRICT_EXPECTED_OFFICIAL_EMPTY_PLACEHOLDER_PAGES == 1
    assert scraper.STRICT_EXPECTED_CURRENT_SECTION_PAGES == 33
    assert scraper.OFFICIAL_TITLE_COUNT == scraper.STRICT_EXPECTED_TITLE_CSVS
    assert {"8.6A", "67"}.isdisjoint(
        {number for number, _name in scraper.OFFICIAL_TITLES}
    )
    assert scraper._virginia_frontier_batch_size() == 2


def test_virginia_catalog_validator_accepts_complete_iis_document_without_html_tail() -> None:
    current = _library_html(list(VirginiaScraper.OFFICIAL_TITLES)).replace(
        b"</body></html>",
        b"</form>",
    )
    incomplete = _library_html(list(VirginiaScraper.OFFICIAL_TITLES[:-1])).replace(
        b"</body></html>",
        b"</form>",
    )
    forged = current.replace(
        b"href='/CSV/CoVTitle_1.csv'",
        b"href='https://forged.example/CSV/CoVTitle_1.csv'",
        1,
    )

    assert VirginiaScraper._is_valid_virginia_law_library(current) is True
    assert VirginiaScraper._is_valid_virginia_law_library(incomplete) is False
    assert VirginiaScraper._is_valid_virginia_law_library(forged) is False


@pytest.mark.anyio
async def test_virginia_strict_frontier_bundles_current_section_witnesses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog = _library_html([("1", "General Provisions")])
    csv_url = virginia_title_csv_url("1")
    pre_body = _operative_body("Pre-contingency branch")
    current_body = _operative_body("Canonical current branch")
    hydrated_body = _operative_body("Canonical hydrated body")
    csv_payload = _csv_payload(
        "1",
        [
            {
                "Section": "1-600",
                "Title": "(Contingent expiration date) Coordinate system",
                "Body": pre_body,
            },
            {
                "Section": "1-600",
                "Title": "(Contingent effective date) Coordinate system",
                "Body": current_body,
            },
            {
                "Section": "1-700",
                "Title": "Official row with missing CSV body",
                "Body": "",
            },
        ],
    )
    current_urls = {
        "https://law.lis.virginia.gov/vacode/title1/chapter1/section1-600/": (
            _current_section_page("1-600", current_body)
        ),
        "https://law.lis.virginia.gov/vacode/title1/chapter1/section1-700/": (
            _current_section_page("1-700", hydrated_body)
        ),
    }
    calls: list[list[str]] = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append(requested)
        payloads = [
            catalog
            if url == self.OFFICIAL_LIBRARY_URL
            else csv_payload
            if url == csv_url
            else current_urls[url]
            for url in requested
        ]
        assert all(kwargs["content_validator"](payload) for payload in payloads)
        return _aligned_result(requested, payloads)

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict Virginia must not use a per-page archive loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_TITLE_CSVS", 1)
    monkeypatch.setattr(
        VirginiaScraper, "STRICT_EXPECTED_CONTINGENT_SECTION_PAGES", 1
    )
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_BODY_HYDRATION_PAGES", 1)
    monkeypatch.setattr(
        VirginiaScraper, "STRICT_EXPECTED_OFFICIAL_EMPTY_PLACEHOLDER_PAGES", 0
    )
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_CURRENT_SECTION_PAGES", 2)
    monkeypatch.setattr(
        VirginiaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    monkeypatch.setattr(
        VirginiaScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )

    scraper = VirginiaScraper("VA", "Virginia")
    rows = await scraper.scrape_code(
        "Code of Virginia",
        VirginiaScraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == ["1-600", "1-700"]
    assert "Canonical current branch" in rows[0].full_text
    assert "Canonical hydrated body" in rows[1].full_text
    assert [len(call) for call in calls] == [1, 1, 2]
    assert calls[-1] == list(current_urls)
    closure = scraper._last_virginia_strict_closure
    assert closure["source_records"] == 3
    assert closure["operative_sections"] == 2
    assert closure["current_section_pages"] == 2
    assert closure["terminal_dispositions"] == {
        "superseded_contingent_variant": 1
    }

    retained_payloads = {
        scraper.OFFICIAL_LIBRARY_URL: catalog,
        csv_url: csv_payload,
        **current_urls,
    }
    ledger = _RetainedInputLedger(retained_payloads)
    scraper._state_law_acquisition_ledger = ledger
    captured = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "va-current-witness-closure.json"

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["va-lis-code"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "va-test@sha256:" + ("b" * 64),
    )
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=_canonical_projection(scraper, rows),
    )

    assert retained_path == tmp_path / "va-current-witness-closure.json"
    assert len(ledger.plural_requests) == 1
    assert [request[0] for request in ledger.plural_requests[0]] == [
        scraper.OFFICIAL_LIBRARY_URL,
        csv_url,
        *current_urls,
    ]
    completion = captured["completion"]
    assert completion["disposition"] == {
        "discovered": 3,
        "fetched": 2,
        "excluded": 1,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    assert completion["replay"]["network_requests"] == 0
    assert completion["transport"]["parser_input_count"] == 4
    assert completion["transport"]["retained_replay_pages"] == 4


@pytest.mark.anyio
async def test_virginia_official_empty_placeholder_closes_first_and_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog = _library_html([("19.2", "Criminal Procedure")])
    csv_url = virginia_title_csv_url("19.2")
    csv_payload = _csv_payload(
        "19.2",
        [
            {
                "TitleName": "CRIMINAL PROCEDURE",
                "ChapterNum": "25",
                "ChapterName": "APPEALS BY THE COMMONWEALTH",
                "Section": "19.2-398",
                "Title": "When appeal by the Commonwealth allowed",
                "Body": _operative_body("Current appeal section"),
            },
            {
                "TitleName": "CRIMINAL PROCEDURE",
                "ChapterNum": "25",
                "ChapterName": "APPEALS BY THE COMMONWEALTH",
                "Section": VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION,
                "Title": VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE,
                "Body": "",
            },
        ],
    )
    page = _official_empty_placeholder_page()
    retained_payloads = {
        VirginiaScraper.OFFICIAL_LIBRARY_URL: catalog,
        csv_url: csv_payload,
        VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_URL: page,
    }
    calls: list[list[str]] = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append(requested)
        payloads = [retained_payloads[url] for url in requested]
        assert all(kwargs["content_validator"](body) for body in payloads)
        return _aligned_result(requested, payloads)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_TITLE_CSVS", 1)
    monkeypatch.setattr(
        VirginiaScraper, "STRICT_EXPECTED_CONTINGENT_SECTION_PAGES", 0
    )
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_BODY_HYDRATION_PAGES", 0)
    monkeypatch.setattr(
        VirginiaScraper, "STRICT_EXPECTED_OFFICIAL_EMPTY_PLACEHOLDER_PAGES", 1
    )
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_CURRENT_SECTION_PAGES", 1)
    monkeypatch.setattr(
        VirginiaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )

    scraper = VirginiaScraper("VA", "Virginia")
    rows = await scraper.scrape_code(
        "Code of Virginia",
        VirginiaScraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == ["19.2-398"]
    assert calls == [
        [scraper.OFFICIAL_LIBRARY_URL],
        [csv_url],
        [VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_URL],
    ]
    closure = scraper._last_virginia_strict_closure
    assert closure["source_records"] == 2
    assert closure["operative_sections"] == 1
    assert closure["terminal_records"] == 0
    assert closure["source_status_record_count"] == 1
    assert closure["source_status_records"][0]["source_status"] == (
        VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_STATUS
    )
    assert closure["frontier"]["disposition"] == {
        "discovered": 2,
        "fetched": 1,
        "excluded": 1,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    assert closure["frontier"]["source_statuses"] == {
        VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_STATUS: 1
    }

    ledger = _RetainedInputLedger(retained_payloads)
    scraper._state_law_acquisition_ledger = ledger
    captured = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "va-empty-placeholder-closure.json"

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["va-lis-code"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "va-test@sha256:" + ("c" * 64),
    )
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=_canonical_projection(scraper, rows),
    )

    assert retained_path == tmp_path / "va-empty-placeholder-closure.json"
    assert len(ledger.plural_requests) == 1
    assert [request[0] for request in ledger.plural_requests[0]] == [
        scraper.OFFICIAL_LIBRARY_URL,
        csv_url,
        VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_URL,
    ]
    completion = captured["completion"]
    assert completion["disposition"] == closure["frontier"]["disposition"]
    assert completion["replay"]["network_requests"] == 0
    assert completion["transport"]["parser_input_count"] == 3
    assert completion["transport"]["retained_replay_pages"] == 3


@pytest.mark.anyio
async def test_virginia_strict_frontier_batches_csv_and_replays_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog = _library_html(
        [("1", "General Provisions"), ("2.2", "Administration of Government")]
    )
    csv_by_url = {
        virginia_title_csv_url("1"): _csv_payload(
            "1",
            [
                {
                    "Section": "1-1",
                    "Title": "First law",
                    "Body": _operative_body("First title law"),
                },
                {
                    "Section": "1-2",
                    "Title": "Reserved",
                    "Body": "<p>Reserved.</p>",
                },
            ],
        ),
        virginia_title_csv_url("2.2"): _csv_payload(
            "2.2",
            [
                {
                    "Section": "2.2-1",
                    "Title": "Second law",
                    "Body": _operative_body("Second title law"),
                }
            ],
        ),
    }
    calls = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append((requested, residual_retry_attempts, dict(kwargs)))
        payloads = [
            catalog if url == self.OFFICIAL_LIBRARY_URL else csv_by_url[url]
            for url in requested
        ]
        assert all(kwargs["content_validator"](payload) for payload in payloads)
        return _aligned_result(requested, payloads)

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict Virginia must not use a per-page archive loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_TITLE_CSVS", 2)
    monkeypatch.setattr(
        VirginiaScraper, "STRICT_EXPECTED_CONTINGENT_SECTION_PAGES", 0
    )
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_BODY_HYDRATION_PAGES", 0)
    monkeypatch.setattr(
        VirginiaScraper, "STRICT_EXPECTED_OFFICIAL_EMPTY_PLACEHOLDER_PAGES", 0
    )
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_CURRENT_SECTION_PAGES", 0)
    monkeypatch.setattr(VirginiaScraper, "OFFICIAL_TITLES", (("99", "Stale"),))
    monkeypatch.setattr(VirginiaScraper, "OFFICIAL_TITLE_COUNT", 1)
    monkeypatch.setattr(
        VirginiaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    monkeypatch.setattr(
        VirginiaScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )

    scraper = VirginiaScraper("VA", "Virginia")
    assert scraper._supports_shared_official_frontier_bridge() is False
    rows = await scraper.scrape_code(
        "Code of Virginia",
        VirginiaScraper.OFFICIAL_ENTRY_URL,
        max_statutes=None,
    )

    assert [row.section_number for row in rows] == ["1-1", "2.2-1"]
    assert [len(call[0]) for call in calls] == [1, 2]
    assert all(call[2]["prefer_direct"] is True for call in calls)
    assert all(call[2]["wayback_prefix_inventory"] is True for call in calls)
    frontier = scraper._last_virginia_strict_closure
    assert frontier["closed"] is True
    assert frontier["catalog_titles"] == 2
    assert frontier["source_records"] == 3
    assert frontier["terminal_dispositions"] == {"reserved": 1}

    retained_payloads = {scraper.OFFICIAL_LIBRARY_URL: catalog, **csv_by_url}
    ledger = _RetainedInputLedger(retained_payloads)
    scraper._state_law_acquisition_ledger = ledger
    captured = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "va-closure.json"

    def _forbid_legacy_catalog(*_args, **_kwargs):
        raise AssertionError("Virginia certification must not use fetch_official")

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["va-lis-code"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "va-test@sha256:" + ("a" * 64),
    )
    monkeypatch.setattr(scraper, "fetch_official", _forbid_legacy_catalog)

    projection = _canonical_projection(scraper, rows)
    retained_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert retained_path == tmp_path / "va-closure.json"
    assert len(ledger.plural_requests) == 1
    assert [request[0] for request in ledger.plural_requests[0]] == [
        scraper.OFFICIAL_LIBRARY_URL,
        *csv_by_url,
    ]
    assert all(
        request[1]["method"] == "GET"
        for request in ledger.plural_requests[0]
    )
    completion = captured["completion"]
    assert completion["disposition"] == {
        "discovered": 3,
        "fetched": 2,
        "excluded": 1,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    assert completion["rights"]["basis"] == "public_law_no_state_copyright"
    assert completion["replay"]["network_requests"] == 0
    assert completion["transport"]["grouped_warc_recovery"] is True
    assert completion["transport"]["per_page_archive_loop"] is False
    assert completion["transport"]["first_pass_requested_pages"] == 3
    assert completion["transport"]["retained_replay_batches"] == 1
    assert completion["transport"]["retained_replay_pages"] == 3
    assert completion["transport"]["retained_replay_network_requests"] == 0

    schema_ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "va-schema-ledger",
        jurisdiction="VA",
        parser_name="VirginiaTitleCsvParser",
    )
    schema_path = schema_ledger.retain_frontier_closure_projection(
        captured["completion"],
        **captured["kwargs"],
    )
    verified = schema_ledger.verify_retained_frontier_closure_projection(
        projection,
        closure_input_path=schema_path,
    )
    assert verified["canonical_row_count"] == 2


@pytest.mark.anyio
async def test_virginia_strict_frontier_rejects_partial_catalog_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _library_html([("1", "General Provisions")])
    calls: list[list[str]] = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append(requested)
        return _aligned_result(requested, [catalog])

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_TITLE_CSVS", 2)
    monkeypatch.setattr(
        VirginiaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    scraper = VirginiaScraper("VA", "Virginia")

    with pytest.raises(RuntimeError, match=r"law-library-catalog frontier is incomplete"):
        await scraper.scrape_code(
            "Code of Virginia",
            VirginiaScraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
    assert calls == [[scraper.OFFICIAL_LIBRARY_URL]]


@pytest.mark.anyio
async def test_virginia_strict_frontier_fails_closed_on_csv_residual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _library_html([("1", "General Provisions")])

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        if requested == [self.OFFICIAL_LIBRARY_URL]:
            return _aligned_result(requested, [catalog])
        return _aligned_result(requested, [b""], errors=["archive residual"])

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(VirginiaScraper, "STRICT_EXPECTED_TITLE_CSVS", 1)
    monkeypatch.setattr(
        VirginiaScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    scraper = VirginiaScraper("VA", "Virginia")

    with pytest.raises(RuntimeError, match="unresolved exact URLs"):
        await scraper.scrape_code(
            "Code of Virginia",
            VirginiaScraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
