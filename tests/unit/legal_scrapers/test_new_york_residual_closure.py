"""LCR-103: New York exact residual proofs and URLs.

This module pins the corrected 212-row audit, the retained official proof
chains, the current-variant parser rule, and the exhausted 28-URL Senate
wave. Unproved decisions remain unresolved and publication remains
forbidden.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    seed_retained_evidence_generation,
    seed_retained_evidence_union,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    new_york_law_pdf as ny_pdf,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york import (
    NewYorkScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_isolated_worker import (
    IsolatedRetainedReplayWorkerError,
    build_host_retained_replay_command,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.strict_frontier_closure import (
    retain_exact_state_frontier_closure,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_PATH = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "new_york_residual_closure_v1.md"
)

OFFICIAL_DOMAIN = "www.nysenate.gov"
OFFICIAL_PDF_DOMAIN = "legislation.nysenate.gov"
OFFICIAL_ENTRY = "https://www.nysenate.gov/legislation/laws"
OFFICIAL_CONSOLIDATED = "https://www.nysenate.gov/legislation/laws/CONSOLIDATED"
AGM28_URL = (
    "https://agriculture.ny.gov/system/files/documents/2023/02/"
    "urbanruralconsumeraccessreport.pdf"
)
AGM28_SHA256 = "6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d"
AGM28_SELECTOR_KEY = "AGM:28"
CATALOG_LAW_COUNT = 94
SOURCE_SECTIONS = 37441
OPERATIVE_SECTIONS = 36475
TERMINAL_BEFORE_AGM = 751
TERMINAL_AFTER_AGM = 752
UNRESOLVED_BEFORE_AGM = 215
UNRESOLVED_AFTER_AGM = 214
CLOSED_LAWS_BEFORE_AGM = 68
CLOSED_LAWS_AFTER_AGM = 69
EVENT_ROWS_BEFORE_AGM = 183
EVENT_ROWS_AFTER_AGM = 182
MISSING_NOTE_ROWS = 4
TOC_BODY_ROWS = 26
SUPPLEMENTAL_RESIDUAL_ROWS = 30
EXTRA_TOC_VARIANTS = 7
ENUMERABLE_URL_RESIDUAL = 28
AUDITED_OPERATIVE = 36477
AUDITED_TERMINAL = 752
AUDITED_UNRESOLVED = 212
AUDITED_CLOSED_LAWS = 70
AUDITED_EVENT_ROWS = 183
AUDITED_SENATE_ROWS = 29
PROJECTED_OPERATIVE = 36498
PROJECTED_TERMINAL = 770
PROJECTED_UNRESOLVED = 173
PROJECTED_CLOSED_LAWS = 73
PROJECTED_EVENT_ROWS = 146
PROJECTED_SENATE_ROWS = 27
SEED_V20_DIRECT = 95
SEED_V21_AGM = 1
SEED_SELECTED = 96
SEED_PROJECTION_SHA256 = (
    "46dce4a3aecf32f3fe21dd743da8f958b1bec8bbc84f5ec680e49f2c13807f76"
)
V20_VERIFIED_BYTES = 75151982
CATALOG_CODE_SHA256 = (
    "792d08fe5168ff6b429d13076fa843a8e5987c4b670339e1a2c6ca70420d590c"
)
UNRESOLVED_SHA_BEFORE_AGM = (
    "4e8865cc8dbfe4706e0fbe931e31df60a4e4f7e20e88ee9f628507c354b22dc3"
)
UNRESOLVED_SHA_AFTER_AGM_PREFIX = "d6b209ac65ab"
RESIDUAL_SHA256 = (
    "b03131cd20eb808d159427e548a732a078fc7b3f94291a2c5fff8a4cd206dde0"
)
RESIDUAL_SHA256_PREFIX = "b03131cd20eb"
SOURCE_BUNDLE = (
    "f68d2672e24092c93810dd0f168a098a855d7879bea746faa63f676ef3ccdd75"
)
SOURCE_BUNDLE_PREFIX = "f68d2672e240"
RESIDUAL_WAVE_NAME = "source-derived-supplemental-sections-1-28"
SIGNED_BILL_WAVE_NAME = "signed-assembly-bill-records-1-2"
AGM28_WAVE_NAME = "agm-28-lifecycle-selector"
CATALOG_WAVE_NAME = "consolidated-catalog"
PDF_WAVE_PREFIX = "full-law-pdfs-"
FIRST_RESIDUAL_URL = "https://www.nysenate.gov/legislation/laws/EPT/3-6.5"
INVENTED_SENATE_URL = "https://www.nysenate.gov/legislation/laws/ZZZ/999.99"
PUBLIC_LAW_URL = "https://newyork.public.law/laws/n.y._penal_law_section_125.25"
INVENTED_AGENCY_PROOF_URL = (
    "https://dos.ny.gov/system/files/documents/2026/08/gmu-856-ceased.csv"
)
VARIANT_IDENTITIES = (
    ("EDN", "2023-b", "*2"),
    ("GMU", "371-a", "*2"),
    ("TAX", "1262-l", "*2"),
    ("VAT", "235", "*2"),
    ("VAT", "235", "*3"),
    ("VAT", "1180-i", "*5"),
    ("VAT", "1180-i", "*6"),
)
SIGNED_BILL_CASES = (
    {
        "code": "CPL",
        "law_name": "Criminal Procedure",
        "section": "150.30",
        "pdf_sha256": (
            "5d80d8879e7a76ab1fb26963368e5a112d5dd16cebb693502b41fad127af3ade"
        ),
        "url": ny_pdf.CPL15030_SIGNED_BILL_RECORD_URL,
        "selector": "CPL:150.30:signed-bill-record",
        "bill_number": "A02009C",
        "signed_date": "04/12/2019",
        "signed_chapter": "59",
        "part": "JJJ",
        "next_part": "KKK",
        "repeal": "Section 150.30 of the criminal procedure law is REPEALED.",
        "effective": "§ 25. This act shall take effect on January 1, 2020.",
        "projection_sha256": ny_pdf.CPL15030_SIGNED_BILL_PROJECTION_SHA256,
        "before": (585, 5, 1, False),
        "after": (585, 6, 0, True),
    },
    {
        "code": "EDN",
        "law_name": "Education",
        "section": "666",
        "pdf_sha256": (
            "acb97e009f4b5028f16b91c554243844da8b6428e23cadbedb7f8eca4148432b"
        ),
        "url": ny_pdf.EDN666_SIGNED_BILL_RECORD_URL,
        "selector": "EDN:666:signed-bill-record",
        "bill_number": "A03006C",
        "signed_date": "05/09/2025",
        "signed_chapter": "56",
        "part": "D",
        "next_part": "E",
        "repeal": "Section 666 of the education law is REPEALED.",
        "effective": (
            "§ 6. This act shall take effect immediately and shall apply to "
            "academic years 2025-2026 and thereafter."
        ),
        "projection_sha256": ny_pdf.EDN666_SIGNED_BILL_PROJECTION_SHA256,
        "before": (1941, 6, 3, False),
        "after": (1941, 7, 2, False),
    },
)
RETAINED_WAVE_D_OBJECT_ROOT = (
    Path.home()
    / ".ipfs_datasets"
    / "state_laws"
    / "legal-corpora-reindex-20260828-ny-wave-d-evidence-nz5JAZ"
    / "NY"
    / "objects"
)
RETAINED_RESOLVER_CASES = (
    {
        "code": "EPT",
        "law_name": "Estates, Powers and Trusts",
        "section": "3-6.5",
        "pdf_sha256": (
            "f9176c690fedaade9769beca8a23246e2af371cdf3e2ceaea27bb71ade6cf479"
        ),
        "page_sha256": ny_pdf.EPT365_SENATE_SECTION_SHA256,
        "url": ny_pdf.EPT365_SENATE_SECTION_URL,
        "residual": {
            "section_number": "3-6.5",
            "toc_variant": "",
            "reason": "ambiguous_lifecycle_status",
            "detail": "missing_lifecycle_note:",
        },
        "before": (362, 7, 1, False),
        "after": (362, 8, 0, True),
        "action": "terminal",
        "disposition": "future_effective",
        "revision": "2026-02-27",
        "drift_from": b"December 12, 2027",
        "drift_to": b"December 12, 2028",
        "drift_conjunct": "explicit_effective_date",
    },
    {
        "code": "GMU",
        "law_name": "General Municipal",
        "section": "902",
        "pdf_sha256": (
            "56ee2480b30cf406829f0a1fa6be468777b2acea9bc007224c75c29e0ed023a5"
        ),
        "page_sha256": ny_pdf.GMU902_SENATE_SECTION_SHA256,
        "url": ny_pdf.GMU902_SENATE_SECTION_URL,
        "residual": {
            "section_number": "902",
            "toc_variant": "",
            "reason": "ambiguous_lifecycle_status",
            "detail": "missing_lifecycle_note:",
        },
        "before": (963, 20, 109, False),
        "after": (964, 20, 108, False),
        "action": "operative",
        "disposition": "source_page_current_with_alternate_never_effective",
        "revision": "2015-03-20",
        "drift_from": b"be perpetual in duration",
        "drift_to": b"remain active in duration",
        "drift_conjunct": "operative_variant_is_perpetual",
    },
    {
        "code": "PAR",
        "law_name": "Parks, Recreation and Historic Preservation",
        "section": "27.09",
        "pdf_sha256": (
            "13d0f8cd7ef7fa8cc25e6b2a6da3315d5a9bc2104b3c2f3436ddf0ad310f210c"
        ),
        "page_sha256": ny_pdf.PAR2709_SENATE_SECTION_SHA256,
        "url": ny_pdf.PAR2709_SENATE_SECTION_URL,
        "residual": {
            "section_number": "27.09",
            "toc_variant": "",
            "reason": "toc_section_missing_body_identity",
            "detail": "toc_offset=326281",
        },
        "before": (170, 0, 1, False),
        "after": (171, 0, 0, True),
        "action": "operative",
        "disposition": "source_page_supplied_missing_pdf_body",
        "revision": "2014-09-22",
        "drift_from": b"subsequently<br />reversed",
        "drift_to": b"later<br />reversed",
        "drift_conjunct": "substantive_source_body",
    },
)


def _newline_residual_sha256(urls: list[str] | tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(urls).encode("utf-8")).hexdigest()


def _derived_supplemental_urls() -> list[str]:
    derived: list[str] = []
    for law_code, section, _variant, _reason in (
        NewYorkScraper.STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS
    ):
        url = ny_pdf.public_section_url(str(law_code), str(section))
        if url not in derived:
            derived.append(url)
    return derived


def _aligned_result(
    urls: list[str],
    payloads: list[bytes],
    *,
    errors: list[str | None] | None = None,
) -> StateLawPageMultiFetchResult:
    requested = list(urls)
    bodies = list(payloads)
    aligned_errors = list(errors or [None] * len(requested))
    return StateLawPageMultiFetchResult(
        urls=requested,
        payloads=bodies,
        errors=aligned_errors,
        transport_receipts=[
            {
                "official_url": url,
                "content_sha256": hashlib.sha256(body).hexdigest() if body else "",
                "source_transport": "direct",
            }
            for url, body in zip(requested, bodies, strict=True)
        ],
        parser_input_envelopes=[None] * len(requested),
        stats={
            "requested_pages": len(requested),
            "common_crawl": {
                "range_fetch_calls": 1 if len(requested) > 1 else 0,
                "range_fetches_avoided": max(0, len(requested) - 1),
            },
        },
    )


def _senate_section_fixture(*, head: str, content: str, revision: str) -> bytes:
    return (
        "<html><body>"
        f"<div class='nys-openleg-head-container'>{head}</div>"
        f"<div class='nys-openleg-content-container'>{content}</div>"
        "<div class='nys-openleg-history-container'>"
        f"Viewing most recent revision (from {revision})"
        "</div>"
        "</body></html>"
    ).encode()


def _signed_bill_fixture(case: dict[str, Any]) -> bytes:
    return (
        "<html><body>"
        "<h3 id='jump_to_Actions'>Actions</h3><table>"
        f"<tr><td>BILL NO</td><td>{case['bill_number']}</td></tr>"
        f"<tr><td>{case['signed_date']}</td>"
        f"<td>SIGNED CHAP.{case['signed_chapter']}</td></tr>"
        "</table>"
        "<h3 id='jump_to_Text'>Text</h3><pre>"
        f"1 PART {case['part']} 2 Section 1. {case['repeal']} "
        f"3 {case['effective']} "
        f"4 PART {case['next_part']} 5 Section 1. Next part."
        "</pre>"
        + (" stable official Assembly record padding" * 3_200)
        + "</body></html>"
    ).encode()


def _env_assembly_fixture(*, resolution: bool) -> bytes:
    if resolution:
        bill_number = "A07454"
        same_as = "S05227"
        actions = (
            "<tr><td>05/27/2025</td><td>passed assembly</td></tr>"
            "<tr><td>06/06/2025</td><td>PASSED SENATE</td></tr>"
            "<tr><td>06/25/2025</td><td>delivered to secretary of state</td></tr>"
        )
        bill_text = (
            "§ 1. The lands at the Mount Van Hoevenberg Olympic Sports Complex. "
            "§ 2. Resolved (if the Senate concur), That the foregoing amendment "
            "be submitted to the people for approval at the general election to "
            "be held in the year 2025 in accordance with the provisions of the "
            "election law."
        )
    else:
        bill_number = "A03628"
        same_as = "S08047"
        actions = (
            "<tr><td>10/27/2025</td><td>SIGNED CHAP.488</td></tr>"
        )
        bill_text = (
            "§ 9-2301. Legislative purpose and intent. "
            + ("Implementation purpose and forest preserve protection. " * 4)
            + "§ 9-2302. Definitions. "
            + ("The terms used in this title have the following meanings. " * 4)
            + "§ 9-2303. Construction, operation, and maintenance of the Mount "
            "Van Hoevenberg Olympic Sports Complex. "
            + ("Development must conform to the governing management plan. " * 4)
            + "§ 9-2304. Land to be acquired for inclusion in the forest "
            "preserve in the Adirondack park. "
            + ("The state shall acquire land for the forest preserve. " * 4)
            + "§ 2. This act shall take effect on the same date and in the same "
            "manner as a \"CONCURRENT RESOLUTION OF THE SENATE AND ASSEMBLY "
            "proposing an amendment to section 1 of article 14 of the "
            "constitution, in relation to the Mount Van Hoevenberg Olympic Sports "
            "Complex in Essex County\" takes effect, in accordance with section "
            "1 of article 19 of the constitution."
        )
    return (
        "<html><body>"
        "<h3 id='jump_to_Summary'>Summary</h3><table>"
        f"<tr><td>BILL NO</td><td>{bill_number}</td></tr>"
        f"<tr><td>SAME AS</td><td>SAME AS {same_as}</td></tr>"
        "</table>"
        "<h3 id='jump_to_Actions'>Actions</h3><table>"
        f"<tr><td>BILL NO</td><td>{bill_number}</td></tr>{actions}"
        "</table>"
        f"<h3 id='jump_to_Text'>Text</h3><pre>{bill_text}</pre>"
        + (" stable official Assembly record padding" * 400)
        + "</body></html>"
    ).encode()


def _env_proof_fixture_inputs() -> list[ny_pdf.NewYorkSupplementalProofInput]:
    article14_content = (
        "SECTION 1 Forest preserve. Notwithstanding the foregoing provisions, "
        "the construction, operation, and maintenance to international standards "
        "for Nordic skiing and biathlon trails is authorized on not more than "
        "three hundred twenty-three acres within one thousand thirty-nine acres "
        "of forest preserve lands, and the state must acquire at least two "
        "thousand five hundred acres of forest land."
        + (" constitutional source padding" * 40)
    )
    article19_content = (
        "SECTION 1 Amendments to constitution. If the people approve and ratify, "
        "such amendment or amendments shall become a part of the constitution "
        "on the first day of January next after such approval."
        + (" constitutional source padding" * 40)
    )
    payload_by_url = {
        ny_pdf.ENV2025_CONCURRENT_RESOLUTION_URL: _env_assembly_fixture(
            resolution=True
        ),
        ny_pdf.ENV2025_IMPLEMENTATION_RECORD_URL: _env_assembly_fixture(
            resolution=False
        ),
        ny_pdf.ENV2025_ARTICLE14_SECTION1_URL: _senate_section_fixture(
            head="SECTION 1 Forest preserve",
            content=article14_content,
            revision="2026-01-09",
        ),
        ny_pdf.ENV2025_ARTICLE19_SECTION1_URL: _senate_section_fixture(
            head="SECTION 1 Amendments to constitution",
            content=article19_content,
            revision="2014-09-22",
        ),
    }
    return [
        ny_pdf.NewYorkSupplementalProofInput.bind(
            selector_key=ny_pdf.ENV2025_PROOF_SELECTOR_BY_URL[url],
            proof_kind=(
                "official_assembly_bill_record"
                if "assembly.ny.gov" in url
                else "official_constitution_section"
            ),
            official_url=url,
            media_type="text/html",
            payload=payload,
        )
        for url, payload in payload_by_url.items()
    ]


def _mhy82_state_register_fixture_text() -> str:
    return (
        "NYS Register/August 20, 2025 Rule Making Activities "
        "Office for People with Developmental Disabilities NOTICE OF ADOPTION "
        "Support Decision Making I.D. No. PDD-31-24-00014-A Filing No. 691 "
        "Filing Date: 2025-07-30 Effective Date: 2025-08-20 "
        "Action taken: Addition of Part 634; amendment of Parts 624, 629, 633, "
        "635, 636, 670; and repeal of section 681.13 of Title 14 NYCRR. "
        "Statutory authority: Mental Hygiene Law, sections 13.07, 13.09(b), "
        "13.15(a), 16.00 and art. 82 Subject: Support Decision Making. "
        "Substance of final rule: The enclosed regulations to be adopted at 14 "
        "NYCRR Part 634 contain rules necessary to implement New York Mental "
        "Hygiene Law (MHL) Article 82."
    )


def _mac_termination_fixture_text() -> str:
    return (
        "THE CITY OF NEW YORK NOTES TO FINANCIAL STATEMENTS JUNE 30, 2010 and "
        "2009 Municipal Assistance Corporation for The City Of New York (MAC). "
        "The Act provides that MAC shall continue for a term ending the later "
        "of July 1, 2008 or one year after all its liabilities have been fully "
        "paid and discharged. On September 24, 2008, MAC had all of its "
        "liabilities paid and discharged and MAC’s Board made the necessary "
        "statutory findings for dissolution and termination and set the date "
        "of termination at September 30, 2009. Upon the termination of the "
        "existence of MAC, all of its rights and property passed to and were "
        "vested in the State of New York."
    )


def _rss1204a_bill_fixture_text() -> str:
    return (
        "5837 2011-2012 Regular Sessions I N S E N A T E "
        "1 Section 1. The retirement and social security law is amended by "
        "adding 2 a new section 1204-a to read as follows: "
        "EACH PARTICIPATING EMPLOYER SHALL 5 PICK UP THE MEMBER CONTRIBUTIONS "
        "REQUIRED TO BE MADE UNDER SECTION TWELVE HUNDRED FOUR. "
        "INCOME TAX TREATMENT UNDER SECTION 414(H) OF THE INTERNAL REVENUE CODE. "
        "S 7. This act shall take effect at the beginning of the first payroll "
        "30 period following sixty days after the retirement system covered by "
        "this 31 act shall receive an Internal Revenue Service ruling stating "
        "that the 32 employee contributions covered by this act are not includible "
        "in the 33 gross income of the employee. The state comp- 37 troller shall "
        "notify the legislative bill drafting commission upon the 38 occurrence "
        "of such ruling. Tier 5 members of the New York State and Local Police "
        "and Fire Retirement System."
    )


def _rss1204a_osc_fixture() -> bytes:
    article = (
        "<article>Subject New Deduction Code 616 PAF Retirement Before Tax "
        "(PAF BTX) and new Deduction Code 618 PAF Arrears Before Tax "
        "(PAF ARBTX) Date Issued October 15, 2013 Purpose To notify agencies "
        "of codes established for members of the New York State Police and "
        "Fireman Retirement System (PFRS). Affected Employees Members of PFRS "
        "in Tiers 3, 5 and 6 Background An Internal Revenue Service (IRS) "
        "ruling dated July 9, 2013 states the mandatory contributions qualify. "
        "Effective October 1, 2013, the mandatory contributions made by Tier "
        "3, 5 and 6 PFRS members will be tax deferred for Federal income tax "
        "purposes under Internal Revenue Code Section 414(h).</article>"
    )
    return (
        "<html><body><h1>State Agencies Bulletin No. 1275</h1>"
        + article
        + (" stable official OSC bulletin padding" * 400)
        + "</body></html>"
    ).encode()


def _retained_wave_d_object(content_sha256: str) -> bytes:
    path = RETAINED_WAVE_D_OBJECT_ROOT / f"{content_sha256}.bin"
    if not path.is_file():
        pytest.skip("retained New York Wave-D evidence is not present")
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == content_sha256
    return payload


class _RetainedInputLedger:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = dict(payloads)
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def refresh_existing_entries(self) -> None:
        return None

    def replay_retained_parser_input(self, *, official_url: str, sanitized_request):
        self.requests.append((official_url, dict(sanitized_request)))
        payload = self.payloads.get(official_url)
        if payload is None:
            return None
        return SimpleNamespace(
            envelope=SimpleNamespace(body=payload),
            transport_receipt={
                "official_url": official_url,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "source_transport": "retained_acquisition_replay",
            },
        )


def _canonical_projection(scraper: NewYorkScraper, rows) -> dict[str, Any]:
    return build_canonical_state_law_output_projection(
        [scraper._enrich_statute_structure(row).to_dict() for row in rows],
        jurisdiction=scraper.state_code,
    )


def _ordered_code_sha256(*codes: str) -> str:
    return hashlib.sha256(
        json.dumps(list(codes), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _report_text() -> str:
    payload = REPORT_PATH.read_text(encoding="utf-8")
    if not payload.strip():
        raise AssertionError("New York residual closure report is empty")
    return payload


def _report_table(report: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw_line in report.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        field, value = cells
        if field in {"Field", "---", "Step"} or set(field) == {"-"}:
            continue
        rows[field] = value.strip("`")
    return rows


def test_new_york_residual_closure_report_records_corrected_audit_and_projection() -> None:
    report = _report_text()
    table = _report_table(report)
    supplemental_urls = list(NewYorkScraper.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS)

    assert table["jurisdiction"] == "NY"
    assert table["official domain"] == OFFICIAL_DOMAIN
    assert table["official_pdf_domain"] == OFFICIAL_PDF_DOMAIN
    assert table["official_assembly_domain"] == "assembly.ny.gov"
    assert table["official entry"] == OFFICIAL_ENTRY
    assert table["official_consolidated_url"] == OFFICIAL_CONSOLIDATED
    assert table["corrected_audited_identity"] == (
        "37441 = 36477 operative + 752 terminal + 212 unresolved"
    )
    assert table["corrected_audited_closed_laws"] == str(AUDITED_CLOSED_LAWS)
    assert table["corrected_audited_event_rows"] == str(AUDITED_EVENT_ROWS)
    assert table["corrected_audited_senate_version_rows"] == str(
        AUDITED_SENATE_ROWS
    )
    assert table["agm28_lifecycle_report_url"] == AGM28_URL
    assert table["agm28_lifecycle_report_sha256"] == AGM28_SHA256
    assert table["agm28_direct_status"] == "HTTP 200; exact digest matched"
    assert table["signed_bill_proof_count"] == "2"
    assert table["signed_bill_wave_name"] == SIGNED_BILL_WAVE_NAME
    assert table["projected_identity_after_bounded_direct_wave"] == (
        "37441 = 36477 operative + 755 terminal + 209 unresolved"
    )
    assert table["projected_closed_laws"] == str(PROJECTED_CLOSED_LAWS)
    assert table["remaining_event_rows"] == str(PROJECTED_EVENT_ROWS)
    assert table["remaining_senate_version_rows"] == str(PROJECTED_SENATE_ROWS)
    assert table["remaining_unresolved_rows"] == str(PROJECTED_UNRESOLVED)
    assert table["remaining_senate_wave_url_count"] == str(
        ENUMERABLE_URL_RESIDUAL
    )
    assert table["remaining_senate_wave_name"] == RESIDUAL_WAVE_NAME
    assert table["remaining_senate_wave_sha256"] == RESIDUAL_SHA256
    assert table["current_bundle_sealed"] == "false"
    assert table["publication_authorized"] == "false"
    assert table["hub_mutation"] == "forbidden"
    assert table["host_retained_replay_network_requests"] == "0 required"

    assert PROJECTED_OPERATIVE + PROJECTED_TERMINAL + PROJECTED_UNRESOLVED == (
        SOURCE_SECTIONS
    )
    assert PROJECTED_EVENT_ROWS + PROJECTED_SENATE_ROWS == PROJECTED_UNRESOLVED
    assert MISSING_NOTE_ROWS + TOC_BODY_ROWS == SUPPLEMENTAL_RESIDUAL_ROWS
    assert SUPPLEMENTAL_RESIDUAL_ROWS - 2 == ENUMERABLE_URL_RESIDUAL
    assert len(supplemental_urls) == ENUMERABLE_URL_RESIDUAL
    assert supplemental_urls[0] == FIRST_RESIDUAL_URL
    assert _newline_residual_sha256(supplemental_urls) == RESIDUAL_SHA256

    lowered = " ".join(report.casefold().split())
    assert "not sealed" in lowered
    assert "not publication-authorized" in lowered
    assert "current-page absence is not proof" in lowered
    assert "per-page archive" in lowered
    assert "--retained-replay-only" in report
    assert "--no-incremental-state-publish" in report
    assert SIGNED_BILL_WAVE_NAME in report
    assert FIRST_RESIDUAL_URL in report
    assert AGM28_URL in report
    assert RESIDUAL_SHA256 in report
    assert ny_pdf.CPL15030_SIGNED_BILL_RECORD_URL in report
    assert ny_pdf.EDN666_SIGNED_BILL_RECORD_URL in report
    assert INVENTED_SENATE_URL not in report
    assert PUBLIC_LAW_URL not in report
    assert INVENTED_AGENCY_PROOF_URL not in report
    for url in supplemental_urls:
        assert url in report


def test_new_york_supplemental_wave_is_source_derived_from_pinned_residual_rows() -> None:
    scraper = NewYorkScraper("NY", "New York")
    rows = list(scraper.STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS)
    pinned = list(scraper.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS)
    derived = _derived_supplemental_urls()

    assert scraper.OFFICIAL_DOMAIN == OFFICIAL_DOMAIN
    assert scraper.OFFICIAL_PDF_DOMAIN == OFFICIAL_PDF_DOMAIN
    assert scraper.OFFICIAL_ENTRY_URL == OFFICIAL_ENTRY
    assert scraper.OFFICIAL_CONSOLIDATED_URL == OFFICIAL_CONSOLIDATED
    assert scraper.STRICT_MINIMUM_CONSOLIDATED_LAWS == CATALOG_LAW_COUNT
    assert scraper.STRICT_CURRENT_CONSOLIDATED_CODE_SHA256 == CATALOG_CODE_SHA256
    assert ny_pdf.AGM28_LIFECYCLE_REPORT_URL == AGM28_URL
    assert ny_pdf.AGM28_LIFECYCLE_REPORT_SHA256 == AGM28_SHA256
    assert ny_pdf.AGM28_LIFECYCLE_SELECTOR_KEY == AGM28_SELECTOR_KEY
    assert ny_pdf.EPT365_SENATE_SECTION_URL == FIRST_RESIDUAL_URL
    assert ny_pdf.EPT365_SENATE_SECTION_SHA256 == (
        "7dc2b7e182e4d36cd358d87384c34981061c7b74156739d12442c6c118c040ff"
    )
    assert ny_pdf.GMU902_SENATE_SECTION_SHA256 == (
        "fc117a03232e1ae39b983d8b982caf318147e574af8488500502beb042f253a0"
    )
    assert ny_pdf.PAR2709_SENATE_SECTION_SHA256 == (
        "76f0a5cfe5313182d5969e5a4c82faeab2aff9f6d2a09a125a35e008006a3b09"
    )
    assert len(rows) == SUPPLEMENTAL_RESIDUAL_ROWS
    assert len(pinned) == ENUMERABLE_URL_RESIDUAL == len(set(pinned))
    assert derived == pinned
    assert pinned[0] == FIRST_RESIDUAL_URL
    assert INVENTED_SENATE_URL not in pinned
    assert PUBLIC_LAW_URL not in pinned
    assert all(urlparse(url).hostname == OFFICIAL_DOMAIN for url in pinned)
    assert all("/legislation/laws/" in url for url in pinned)
    note_rows = [row for row in rows if row[3] == "missing_lifecycle_note"]
    toc_rows = [row for row in rows if row[3] == "toc_section_missing_body_identity"]
    assert len(note_rows) == MISSING_NOTE_ROWS
    assert len(toc_rows) == TOC_BODY_ROWS
    extra = [(row[0], row[1], row[2]) for row in rows if row[2]]
    assert extra == list(VARIANT_IDENTITIES)
    assert len(extra) == EXTRA_TOC_VARIANTS
    assert scraper.STRICT_CURRENT_SUPPLEMENTAL_URL_SHA256 == RESIDUAL_SHA256
    assert _newline_residual_sha256(pinned) == RESIDUAL_SHA256
    assert NewYorkScraper._new_york_exact_supplemental_urls(
        [
            SimpleNamespace(
                law_code=law_code,
                unclassified_sections=[
                    {
                        "section_number": section,
                        "toc_variant": variant,
                        "reason": (
                            "ambiguous_lifecycle_status"
                            if reason == "missing_lifecycle_note"
                            else reason
                        ),
                        "detail": (
                            "missing_lifecycle_note:"
                            if reason == "missing_lifecycle_note"
                            else "toc_offset=1"
                        ),
                    }
                ],
            )
            for law_code, section, variant, reason in rows
        ]
    ) == pinned


def test_new_york_signed_bill_wave_is_exact_official_and_source_derived() -> None:
    rows = list(NewYorkScraper.STRICT_CURRENT_SIGNED_BILL_PROOF_ROWS)
    urls = [row[3] for row in rows]

    assert [(row[0], row[1]) for row in rows] == [
        ("CPL", "150.30"),
        ("EDN", "666"),
    ]
    assert [row[2] for row in rows] == [case["selector"] for case in SIGNED_BILL_CASES]
    assert urls == [case["url"] for case in SIGNED_BILL_CASES]
    assert all(urlparse(url).hostname == "assembly.ny.gov" for url in urls)
    assert _newline_residual_sha256(urls) == (
        NewYorkScraper.STRICT_CURRENT_SIGNED_BILL_PROOF_URL_SHA256
    )

    reports = [
        SimpleNamespace(
            law_code=case["code"],
            unclassified_sections=[
                {
                    "section_number": case["section"],
                    "toc_variant": "",
                    "reason": "toc_section_missing_body_identity",
                }
            ],
        )
        for case in SIGNED_BILL_CASES
    ]
    assert NewYorkScraper._new_york_exact_signed_bill_proof_rows(reports) == rows


def test_new_york_env_wave_is_exact_official_and_source_derived() -> None:
    rows = list(NewYorkScraper.STRICT_CURRENT_ENV_PROOF_ROWS)
    urls = [row[2] for row in rows]
    assert urls == list(ny_pdf.ENV2025_PROOF_SELECTOR_BY_URL)
    assert _newline_residual_sha256(urls) == (
        NewYorkScraper.STRICT_CURRENT_ENV_PROOF_URL_SHA256
    )
    assert all(
        urlparse(url).hostname in {"assembly.ny.gov", "www.nysenate.gov"}
        for url in urls
    )
    report = SimpleNamespace(
        law_code="ENV",
        unclassified_sections=[
            {
                "section_number": section,
                "toc_variant": "",
                "reason": "ambiguous_lifecycle_status",
                "detail": "event_conditioned_effective: exact source note",
            }
            for section in ("9-2301", "9-2302", "9-2303", "9-2304")
        ],
    )
    assert NewYorkScraper._new_york_exact_env_proof_rows([report]) == rows


@pytest.mark.parametrize(
    "section",
    ("9-2301", "9-2302", "9-2303", "9-2304"),
)
def test_new_york_env_resolver_closes_exact_event_rows(section: str) -> None:
    proofs = _env_proof_fixture_inputs()
    outcome = ny_pdf.NewYorkSupplementalProofRegistry(proofs).resolve_residual(
        law_code="ENV",
        residual={
            "section_number": section,
            "toc_variant": "",
            "reason": "ambiguous_lifecycle_status",
            "detail": "event_conditioned_effective: exact source note",
        },
    )
    assert outcome["status"] == "resolved"
    assert outcome["decision_action"] == "operative"
    assert outcome["decision"]["effective_date"] == "2026-01-01"
    assert outcome["source_projection_sha256"] == (
        ny_pdf.ENV2025_PROOF_PROJECTION_SHA256
    )
    assert len(outcome["proof_bundle"]) == 4
    assert all(outcome["conjuncts"].values())


def test_new_york_env_resolver_fails_closed_on_constitution_drift() -> None:
    proofs = _env_proof_fixture_inputs()
    drifted = []
    for proof in proofs:
        payload = proof.payload
        if proof.official_url == ny_pdf.ENV2025_ARTICLE14_SECTION1_URL:
            payload = payload.replace(
                b"three hundred twenty-three acres",
                b"three hundred twenty-four acres",
            )
        drifted.append(
            ny_pdf.NewYorkSupplementalProofInput.bind(
                selector_key=proof.selector_key,
                proof_kind=proof.proof_kind,
                official_url=proof.official_url,
                media_type=proof.media_type,
                payload=payload,
            )
        )
    outcome = ny_pdf.NewYorkSupplementalProofRegistry(drifted).resolve_residual(
        law_code="ENV",
        residual={
            "section_number": "9-2301",
            "toc_variant": "",
            "reason": "ambiguous_lifecycle_status",
            "detail": "event_conditioned_effective: exact source note",
        },
    )
    assert outcome["status"] == "unknown"
    assert outcome["decision_action"] is None
    assert outcome["conjuncts"]["exact_source_projection_sha256"] is False
    assert "decision" not in outcome


def test_new_york_event_wave_is_exact_official_and_source_derived() -> None:
    rows = list(NewYorkScraper.STRICT_CURRENT_EVENT_PROOF_ROWS)
    urls = [row[4] for row in rows]
    assert [row[:2] for row in rows] == [
        ("MHY", "mhy_2022_ch481_regulations"),
        ("PBA", "mac_liability_discharge"),
        ("RSS", "rss_2011_ch525_condition"),
        ("RSS", "rss_2011_ch525_condition"),
    ]
    assert urls == [
        ny_pdf.MHY82_STATE_REGISTER_URL,
        ny_pdf.MAC_TERMINATION_REPORT_URL,
        ny_pdf.RSS1204A_ENACTED_BILL_URL,
        ny_pdf.RSS1204A_OSC_BULLETIN_URL,
    ]
    assert _newline_residual_sha256(urls) == (
        NewYorkScraper.STRICT_CURRENT_EVENT_PROOF_URL_SHA256
    )
    assert [urlparse(url).hostname for url in urls] == [
        "dos.ny.gov",
        "www.nyc.gov",
        "legislation.nysenate.gov",
        "www.osc.ny.gov",
    ]
    reports = [
        SimpleNamespace(
            law_code="MHY",
            unclassified_sections=[
                {
                    "section_number": section,
                    "toc_variant": "",
                    "reason": "ambiguous_lifecycle_status",
                    "detail": "event_conditioned_effective: exact source note",
                }
                for section in ny_pdf.MHY82_SECTIONS
            ],
        ),
        SimpleNamespace(
            law_code="PBA",
            unclassified_sections=[
                {
                    "section_number": section,
                    "toc_variant": "",
                    "reason": "ambiguous_lifecycle_status",
                    "detail": "event_conditioned_expiration: exact source note",
                }
                for section in ny_pdf.MAC_TITLE_SECTIONS
            ],
        ),
        SimpleNamespace(
            law_code="RSS",
            unclassified_sections=[
                {
                    "section_number": "1204-a",
                    "toc_variant": "",
                    "reason": "ambiguous_lifecycle_status",
                    "detail": "event_conditioned_effective: exact source note",
                }
            ],
        ),
    ]
    assert NewYorkScraper._new_york_exact_event_proof_rows(reports) == rows


@pytest.mark.parametrize("section", ("82.01", "82.15"))
def test_new_york_mhy82_resolver_closes_exact_event_rows(
    monkeypatch,
    section: str,
) -> None:
    payload = b"%PDF synthetic MHY Article 82 adoption"
    text = _mhy82_state_register_fixture_text()
    monkeypatch.setattr(
        ny_pdf,
        "_new_york_official_pdf_projection_text",
        lambda _payload: text,
    )
    projection_sha256 = (
        ny_pdf._new_york_mhy82_state_register_projection_sha256(payload)
    )
    monkeypatch.setattr(
        ny_pdf,
        "MHY82_STATE_REGISTER_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(
        ny_pdf,
        "MHY82_STATE_REGISTER_PROJECTION_SHA256",
        projection_sha256,
    )
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key=ny_pdf.MHY82_STATE_REGISTER_SELECTOR_KEY,
        proof_kind="official_state_register_adoption",
        official_url=ny_pdf.MHY82_STATE_REGISTER_URL,
        media_type="application/pdf",
        payload=payload,
    )
    outcome = ny_pdf.NewYorkSupplementalProofRegistry([proof]).resolve_residual(
        law_code="MHY",
        residual={
            "section_number": section,
            "toc_variant": "",
            "reason": "ambiguous_lifecycle_status",
            "detail": "event_conditioned_effective: exact source note",
            "_supplemental_source_full_text": (
                f"§ {section}. Supported decision-making source body. " * 3
            ),
            "_supplemental_source_section_name": "Supported decision making",
        },
    )
    assert outcome["status"] == "resolved"
    assert outcome["decision_action"] == "operative"
    assert outcome["decision"]["effective_date"] == "2025-11-18"
    assert outcome["source_projection_sha256"] == projection_sha256
    assert all(outcome["conjuncts"].values())


@pytest.mark.parametrize("section", ("3030", "3041"))
def test_new_york_mac_resolver_closes_exact_event_rows(
    monkeypatch,
    section: str,
) -> None:
    payload = b"%PDF synthetic MAC audited financial report"
    text = _mac_termination_fixture_text()
    monkeypatch.setattr(
        ny_pdf,
        "_new_york_official_pdf_projection_text",
        lambda _payload: text,
    )
    projection_sha256 = ny_pdf._new_york_mac_termination_projection_sha256(
        payload
    )
    monkeypatch.setattr(
        ny_pdf,
        "MAC_TERMINATION_REPORT_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(
        ny_pdf,
        "MAC_TERMINATION_REPORT_PROJECTION_SHA256",
        projection_sha256,
    )
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key=ny_pdf.MAC_TERMINATION_REPORT_SELECTOR_KEY,
        proof_kind="official_government_financial_report",
        official_url=ny_pdf.MAC_TERMINATION_REPORT_URL,
        media_type="application/pdf",
        payload=payload,
    )
    outcome = ny_pdf.NewYorkSupplementalProofRegistry([proof]).resolve_residual(
        law_code="PBA",
        residual={
            "section_number": section,
            "toc_variant": "",
            "reason": "ambiguous_lifecycle_status",
            "detail": "event_conditioned_expiration: exact source note",
        },
    )
    assert outcome["status"] == "resolved"
    assert outcome["decision_action"] == "terminal"
    assert outcome["decision"]["disposition"] == "expired"
    assert outcome["decision"]["effective_date"] == "2009-09-30"
    assert outcome["source_projection_sha256"] == projection_sha256
    assert all(outcome["conjuncts"].values())


def test_new_york_event_resolvers_fail_closed_on_semantic_drift(
    monkeypatch,
) -> None:
    payload = b"%PDF synthetic drifted MAC report"
    original_text = _mac_termination_fixture_text()
    monkeypatch.setattr(
        ny_pdf,
        "_new_york_official_pdf_projection_text",
        lambda _payload: original_text,
    )
    expected_projection = ny_pdf._new_york_mac_termination_projection_sha256(
        payload
    )
    monkeypatch.setattr(
        ny_pdf,
        "_new_york_official_pdf_projection_text",
        lambda _payload: original_text.replace(
            "September 30, 2009",
            "September 30, 2010",
        ),
    )
    monkeypatch.setattr(
        ny_pdf,
        "MAC_TERMINATION_REPORT_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(
        ny_pdf,
        "MAC_TERMINATION_REPORT_PROJECTION_SHA256",
        expected_projection,
    )
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key=ny_pdf.MAC_TERMINATION_REPORT_SELECTOR_KEY,
        proof_kind="official_government_financial_report",
        official_url=ny_pdf.MAC_TERMINATION_REPORT_URL,
        media_type="application/pdf",
        payload=payload,
    )
    outcome = ny_pdf.NewYorkSupplementalProofRegistry([proof]).resolve_residual(
        law_code="PBA",
        residual={
            "section_number": "3030",
            "toc_variant": "",
            "reason": "ambiguous_lifecycle_status",
            "detail": "event_conditioned_expiration: exact source note",
        },
    )
    assert outcome["status"] == "unknown"
    assert outcome["decision_action"] is None
    assert outcome["conjuncts"]["exact_source_projection_sha256"] is False
    assert "decision" not in outcome


def test_new_york_rss1204a_resolver_closes_exact_event_row(monkeypatch) -> None:
    bill_payload = b"%PDF synthetic S5837"
    bulletin_payload = _rss1204a_osc_fixture()
    monkeypatch.setattr(
        ny_pdf,
        "_new_york_official_pdf_projection_text",
        lambda _payload: _rss1204a_bill_fixture_text(),
    )
    bill_projection = ny_pdf._new_york_rss1204a_bill_projection_sha256(
        bill_payload
    )
    bulletin_projection = ny_pdf._new_york_rss1204a_osc_projection_sha256(
        bulletin_payload
    )
    bundle_projection = ny_pdf._new_york_rss1204a_bundle_projection_sha256(
        bill_payload,
        bulletin_payload,
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_ENACTED_BILL_SHA256",
        hashlib.sha256(bill_payload).hexdigest(),
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_OSC_BULLETIN_SHA256",
        hashlib.sha256(bulletin_payload).hexdigest(),
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_ENACTED_BILL_PROJECTION_SHA256",
        bill_projection,
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_OSC_BULLETIN_PROJECTION_SHA256",
        bulletin_projection,
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_PROOF_BUNDLE_PROJECTION_SHA256",
        bundle_projection,
    )
    proofs = [
        ny_pdf.NewYorkSupplementalProofInput.bind(
            selector_key=ny_pdf.RSS1204A_ENACTED_BILL_SELECTOR_KEY,
            proof_kind="official_enacted_bill_text",
            official_url=ny_pdf.RSS1204A_ENACTED_BILL_URL,
            media_type="application/pdf",
            payload=bill_payload,
        ),
        ny_pdf.NewYorkSupplementalProofInput.bind(
            selector_key=ny_pdf.RSS1204A_OSC_BULLETIN_SELECTOR_KEY,
            proof_kind="official_comptroller_payroll_bulletin",
            official_url=ny_pdf.RSS1204A_OSC_BULLETIN_URL,
            media_type="text/html",
            payload=bulletin_payload,
        ),
    ]
    outcome = ny_pdf.NewYorkSupplementalProofRegistry(proofs).resolve_residual(
        law_code="RSS",
        residual={
            "section_number": "1204-a",
            "toc_variant": "",
            "reason": "ambiguous_lifecycle_status",
            "detail": "event_conditioned_effective: See ch 525/2011 § 7",
            "_supplemental_source_full_text": (
                "* § 1204-a. Pick up of member contributions by employer. "
                "Each participating employer shall pick up contributions and "
                "shall receive income tax treatment under section 414(h) of "
                "the Internal Revenue Code. "
                + ("Source-bound statutory body. " * 5)
            ),
            "_supplemental_source_section_name": (
                "Pick up of member contributions by employer"
            ),
        },
    )
    assert outcome["status"] == "resolved"
    assert outcome["decision_action"] == "operative"
    assert outcome["decision"]["effective_date"] == "2013-10-01"
    assert outcome["source_projection_sha256"] == bundle_projection
    assert len(outcome["proof_bundle"]) == 2
    assert all(outcome["conjuncts"].values())


def test_new_york_rss1204a_resolver_fails_closed_on_semantic_drift(
    monkeypatch,
) -> None:
    bill_payload = b"%PDF synthetic S5837"
    bulletin_payload = _rss1204a_osc_fixture()
    bill_text = _rss1204a_bill_fixture_text()
    original_article = ny_pdf._new_york_rss1204a_osc_article_text(
        bulletin_payload
    )
    monkeypatch.setattr(
        ny_pdf,
        "_new_york_official_pdf_projection_text",
        lambda _payload: bill_text,
    )
    bill_projection = ny_pdf._new_york_rss1204a_bill_projection_sha256(
        bill_payload
    )
    bulletin_projection = ny_pdf._new_york_rss1204a_osc_projection_sha256(
        bulletin_payload
    )
    bundle_projection = ny_pdf._new_york_rss1204a_bundle_projection_sha256(
        bill_payload,
        bulletin_payload,
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_ENACTED_BILL_SHA256",
        hashlib.sha256(bill_payload).hexdigest(),
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_OSC_BULLETIN_SHA256",
        hashlib.sha256(bulletin_payload).hexdigest(),
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_ENACTED_BILL_PROJECTION_SHA256",
        bill_projection,
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_OSC_BULLETIN_PROJECTION_SHA256",
        bulletin_projection,
    )
    monkeypatch.setattr(
        ny_pdf,
        "RSS1204A_PROOF_BUNDLE_PROJECTION_SHA256",
        bundle_projection,
    )
    monkeypatch.setattr(
        ny_pdf,
        "_new_york_rss1204a_osc_article_text",
        lambda _payload: original_article.replace(
            "Effective October 1, 2013",
            "Effective October 1, 2014",
        ),
    )
    proofs = [
        ny_pdf.NewYorkSupplementalProofInput.bind(
            selector_key=ny_pdf.RSS1204A_ENACTED_BILL_SELECTOR_KEY,
            proof_kind="official_enacted_bill_text",
            official_url=ny_pdf.RSS1204A_ENACTED_BILL_URL,
            media_type="application/pdf",
            payload=bill_payload,
        ),
        ny_pdf.NewYorkSupplementalProofInput.bind(
            selector_key=ny_pdf.RSS1204A_OSC_BULLETIN_SELECTOR_KEY,
            proof_kind="official_comptroller_payroll_bulletin",
            official_url=ny_pdf.RSS1204A_OSC_BULLETIN_URL,
            media_type="text/html",
            payload=bulletin_payload,
        ),
    ]
    outcome = ny_pdf.evaluate_new_york_rss1204a_proof_bundle(
        proofs,
        section="1204-a",
        source_full_text=(
            "* § 1204-a. Pick up of member contributions by employer. "
            "Each participating employer shall receive income tax treatment "
            "under section 414(h) of the Internal Revenue Code. "
            + ("Source-bound statutory body. " * 5)
        ),
        source_section_name="Pick up of member contributions by employer",
    )
    assert outcome["status"] == "unknown"
    assert outcome["decision_action"] is None
    assert outcome["conjuncts"]["exact_bulletin_projection_sha256"] is False
    assert "decision" not in outcome


def test_new_york_event_pdf_validator_accepts_dos_warning_prefix() -> None:
    payload = b"\n**** Ghostscript warning\n%PDF-1.4\n" + (b"x" * 100_001)
    assert NewYorkScraper._is_valid_new_york_event_proof_pdf(payload)


def test_new_york_event_html_validator_accepts_exact_osc_bulletin() -> None:
    assert NewYorkScraper._is_valid_new_york_event_proof_html(
        _rss1204a_osc_fixture()
    )


def test_new_york_dated_current_variant_controls_undated_legacy(
    monkeypatch,
) -> None:
    law_text = """
    ARTICLE 23
    TEMPORARY RELEASE PROGRAMS
    Section 851. Definitions.
            852. Establishment of temporary release.
      * § 851. Definitions. The current dated version has a complete source
      body and remains operative for the release-date snapshot.
      * NB Effective until September 1, 2027
      * § 851. Definitions. The future version has a complete source body and
      will replace the dated current version.
      * NB Effective September 1, 2027
      * § 851. Definitions. The legacy version has a complete source body and
      depends on expirations of several prior session-law provisions.
      * NB Effective only upon the expiration of §42 of ch. 60/1994, §10 of
      ch. 339/1972 and §3 of ch. 554/1986
      § 852. Establishment of temporary release. This following source section
      has a complete operative body for exact source reconciliation.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (law_text, 1),
    )
    parsed = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-law",
        law_code="COR",
        law_name="Correction",
    )
    assert parsed.closed is True
    section = next(row for row in parsed.statutes if row.section_number == "851")
    assert "current dated version" in section.full_text
    assert section.structured_data["lifecycle_disposition"] == (
        "effective_until"
    )
    assert parsed.unclassified_sections == []
    assert {
        row["disposition"] for row in parsed.lifecycle_alternate_sections
    } == {"future_effective", "event_conditioned_effective"}


@pytest.mark.parametrize(
    "case",
    SIGNED_BILL_CASES,
    ids=lambda case: f"{case['code']}-{case['section']}",
)
def test_new_york_signed_bill_resolvers_reconcile_exact_rows(
    case: dict[str, Any],
) -> None:
    payload = _signed_bill_fixture(case)
    assert NewYorkScraper._is_valid_new_york_assembly_signed_bill_html(payload)
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key=str(case["selector"]),
        proof_kind="official_signed_bill_record",
        official_url=str(case["url"]),
        media_type="text/html",
        payload=payload,
    )
    registry = ny_pdf.NewYorkSupplementalProofRegistry([proof])
    pdf_payload = _retained_wave_d_object(str(case["pdf_sha256"]))

    before = ny_pdf.parse_new_york_law_pdf(
        pdf_payload,
        law_code=str(case["code"]),
        law_name=str(case["law_name"]),
    )
    after = ny_pdf.parse_new_york_law_pdf(
        pdf_payload,
        law_code=str(case["code"]),
        law_name=str(case["law_name"]),
        supplemental_proof_registry=registry,
    )

    assert (
        len(before.statutes),
        len(before.terminal_sections),
        len(before.unclassified_sections),
        before.closed,
    ) == case["before"]
    assert (
        len(after.statutes),
        len(after.terminal_sections),
        len(after.unclassified_sections),
        after.closed,
    ) == case["after"]
    resolved = [
        row
        for row in after.supplemental_proof_attempts
        if row.get("status") == "resolved"
    ]
    assert len(resolved) == 1
    outcome = resolved[0]
    assert outcome["decision_action"] == "terminal"
    assert outcome["decision"]["disposition"] == "repealed"
    assert outcome["source_projection_sha256"] == case["projection_sha256"]
    assert all(outcome["conjuncts"].values())
    terminal = [
        row
        for row in after.terminal_sections
        if row.get("source_record_id")
        == f"{case['code']}:{case['section']}"
    ]
    assert len(terminal) == 1
    assert terminal[0]["source_url"] == case["url"]


@pytest.mark.parametrize(
    "case",
    SIGNED_BILL_CASES,
    ids=lambda case: f"{case['code']}-{case['section']}",
)
def test_new_york_signed_bill_resolvers_fail_closed_on_source_drift(
    case: dict[str, Any],
) -> None:
    payload = _signed_bill_fixture(case)
    drifted = payload.replace(
        str(case["repeal"]).encode(),
        str(case["repeal"]).replace("REPEALED", "AMENDED").encode(),
    )
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key=str(case["selector"]),
        proof_kind="official_signed_bill_record",
        official_url=str(case["url"]),
        media_type="text/html",
        payload=drifted,
    )
    outcome = ny_pdf.NewYorkSupplementalProofRegistry([proof]).resolve_residual(
        law_code=str(case["code"]),
        residual={
            "section_number": str(case["section"]),
            "toc_variant": "",
            "reason": "toc_section_missing_body_identity",
            "detail": "toc_offset=1",
        },
    )

    assert outcome["status"] == "unknown"
    assert outcome["decision_action"] is None
    assert outcome["conjuncts"]["same_part_repeal_clause"] is False
    assert outcome["conjuncts"]["exact_source_projection_sha256"] is False
    assert "decision" not in outcome


def test_new_york_signed_bill_proof_manifest_replays_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = SIGNED_BILL_CASES[0]
    code = str(case["code"])
    pdf_url = ny_pdf.full_law_pdf_url(code)
    proof_url = str(case["url"])
    pdf_payload = _retained_wave_d_object(str(case["pdf_sha256"]))
    proof_payload = _signed_bill_fixture(case)
    catalog = (
        "<html><head><title>Consolidated Laws of New York</title></head><body>"
        "<a href='/legislation/laws/CPL'>CPL Criminal Procedure</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()
    payload_by_url = {
        NewYorkScraper.OFFICIAL_CONSOLIDATED_URL: catalog,
        pdf_url: pdf_payload,
        proof_url: proof_payload,
    }
    live_requests: list[list[str]] = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        live_requests.append(requested)
        payloads = [payload_by_url[url] for url in requested]
        assert all(kwargs["content_validator"](body) for body in payloads)
        return _aligned_result(requested, payloads)

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict New York must not use a per-page archive loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 1)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256(code),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )
    scraper = NewYorkScraper("NY", "New York")

    rows = asyncio.run(
        scraper.scrape_code(
            "New York Consolidated Laws",
            NewYorkScraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
    )

    assert len(rows) == 585
    assert live_requests == [
        [scraper.OFFICIAL_CONSOLIDATED_URL],
        [pdf_url],
        [proof_url],
    ]
    manifest = scraper._last_new_york_full_frontier[
        "supplemental_proof_manifest"
    ]
    assert manifest == [
        {
            "content_sha256": hashlib.sha256(proof_payload).hexdigest(),
            "media_type": "text/html",
            "official_url": proof_url,
            "proof_kind": "official_signed_bill_record",
            "schema_version": ny_pdf.SUPPLEMENTAL_PROOF_SCHEMA_VERSION,
            "selector_key": case["selector"],
        }
    ]

    ledger = _RetainedInputLedger(payload_by_url)
    scraper._state_law_acquisition_ledger = ledger
    captured: dict[str, Any] = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "ny-retained-signed-bill-closure.json"

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["ny-senate-laws"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "ny-signed-bill-test@sha256:" + ("d" * 64),
    )
    retained_path = asyncio.run(
        scraper.produce_state_law_frontier_closure(
            canonical_output_projection=_canonical_projection(scraper, rows),
        )
    )

    assert retained_path == tmp_path / "ny-retained-signed-bill-closure.json"
    assert [request[0] for request in ledger.requests] == [
        scraper.OFFICIAL_CONSOLIDATED_URL,
        proof_url,
        pdf_url,
    ]
    assert captured["completion"]["replay"]["network_requests"] == 0

    ledger.payloads[proof_url] = proof_payload.replace(
        b"SIGNED CHAP.59",
        b"SIGNED CHAP.60",
    )
    with pytest.raises(RuntimeError, match="retained signed-bill proof changed"):
        asyncio.run(
            scraper.produce_state_law_frontier_closure(
                canonical_output_projection=_canonical_projection(scraper, rows),
            )
        )


def test_new_york_senate_section_validator_rejects_retained_soft_not_found_shape() -> None:
    substantive = _senate_section_fixture(
        head="SECTION 3-6.5 Caution to the testator",
        content=(
            "* § 3-6.5 Caution to the testator "
            + ("Retained official section body. " * 80)
        ),
        revision="2026-02-27",
    )
    soft_not_found = (
        b"<html><body><div class='nys-openleg-content-container'>"
        + (b"New York State Senate /legislation/laws/ " * 40)
        + b"</div><div class='nys-openleg-not-found'>"
        + b"The requested entry could not be found."
        + b"</div></body></html>"
    )
    branded_shell = (
        b"<html><body>New York State Senate /legislation/laws/ "
        + (b"navigation shell " * 100)
        + b"</body></html>"
    )
    drifted_content_marker = substantive.replace(
        b"nys-openleg-content-container",
        b"nys-openleg-content-container-v2",
    )

    assert NewYorkScraper._is_valid_new_york_senate_section_html(substantive)
    assert not NewYorkScraper._is_valid_new_york_senate_section_html(
        soft_not_found
    )
    assert not NewYorkScraper._is_valid_new_york_senate_section_html(
        branded_shell
    )
    assert not NewYorkScraper._is_valid_new_york_senate_section_html(
        drifted_content_marker
    )


@pytest.mark.parametrize(
    "case",
    RETAINED_RESOLVER_CASES,
    ids=lambda case: f"{case['code']}-{case['section']}",
)
def test_new_york_exact_retained_senate_resolvers_reconcile_supported_rows(
    case: dict[str, Any],
) -> None:
    pdf_payload = _retained_wave_d_object(str(case["pdf_sha256"]))
    page_payload = _retained_wave_d_object(str(case["page_sha256"]))
    code = str(case["code"])
    section = str(case["section"])
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key=f"{code}:{section}:source-page",
        proof_kind="official_senate_section",
        official_url=str(case["url"]),
        media_type="text/html",
        payload=page_payload,
    )
    registry = ny_pdf.NewYorkSupplementalProofRegistry([proof])

    before = ny_pdf.parse_new_york_law_pdf(
        pdf_payload,
        law_code=code,
        law_name=str(case["law_name"]),
    )
    after = ny_pdf.parse_new_york_law_pdf(
        pdf_payload,
        law_code=code,
        law_name=str(case["law_name"]),
        supplemental_proof_registry=registry,
    )

    assert (
        len(before.statutes),
        len(before.terminal_sections),
        len(before.unclassified_sections),
        before.closed,
    ) == case["before"]
    assert (
        len(after.statutes),
        len(after.terminal_sections),
        len(after.unclassified_sections),
        after.closed,
    ) == case["after"]
    assert after.source_section_count == (
        len(after.statutes)
        + len(after.terminal_sections)
        + len(after.unclassified_sections)
    )
    resolved = [
        row
        for row in after.supplemental_proof_attempts
        if row.get("status") == "resolved"
    ]
    assert len(resolved) == 1
    outcome = resolved[0]
    assert outcome["decision_action"] == case["action"]
    assert outcome["decision"]["disposition"] == case["disposition"]
    assert outcome["source_revision_date"] == case["revision"]
    assert outcome["proof"]["content_sha256"] == case["page_sha256"]
    assert all(outcome["conjuncts"].values())
    source_record_id = f"{code}:{section}"
    if case["action"] == "terminal":
        terminal = [
            row
            for row in after.terminal_sections
            if row.get("source_record_id") == source_record_id
        ]
        assert len(terminal) == 1
        assert terminal[0]["source_url"] == case["url"]
    else:
        statutes = [
            row
            for row in after.statutes
            if row.structured_data.get("source_record_id") == source_record_id
        ]
        assert len(statutes) == 1
        assert statutes[0].source_url == case["url"]
        assert statutes[0].structured_data["supplemental_proof_sha256"] == (
            case["page_sha256"]
        )


@pytest.mark.parametrize(
    "case",
    RETAINED_RESOLVER_CASES,
    ids=lambda case: f"{case['code']}-{case['section']}",
)
def test_new_york_retained_senate_resolvers_fail_closed_on_source_drift(
    case: dict[str, Any],
) -> None:
    retained = _retained_wave_d_object(str(case["page_sha256"]))
    drift_from = bytes(case["drift_from"])
    assert drift_from in retained
    drifted = retained.replace(drift_from, bytes(case["drift_to"]))
    assert drifted != retained
    code = str(case["code"])
    section = str(case["section"])
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key=f"{code}:{section}:source-page",
        proof_kind="official_senate_section",
        official_url=str(case["url"]),
        media_type="text/html",
        payload=drifted,
    )

    outcome = ny_pdf.NewYorkSupplementalProofRegistry([proof]).resolve_residual(
        law_code=code,
        residual=dict(case["residual"]),
    )

    assert outcome["status"] == "unknown"
    assert outcome["decision_action"] is None
    assert outcome["reason"] == "source_bound_conjunction_failed"
    assert outcome["conjuncts"]["exact_retained_page_sha256"] is False
    assert outcome["conjuncts"][str(case["drift_conjunct"])] is False
    assert "decision" not in outcome


def test_new_york_retained_senate_proof_manifest_replays_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = RETAINED_RESOLVER_CASES[0]
    pdf_payload = _retained_wave_d_object(str(case["pdf_sha256"]))
    page_payload = _retained_wave_d_object(str(case["page_sha256"]))
    pdf_url = ny_pdf.full_law_pdf_url("EPT")
    section_url = str(case["url"])
    catalog = (
        "<html><head><title>Consolidated Laws of New York</title></head><body>"
        "<a href='/legislation/laws/EPT'>"
        "EPT Estates, Powers and Trusts</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()
    payload_by_url = {
        NewYorkScraper.OFFICIAL_CONSOLIDATED_URL: catalog,
        pdf_url: pdf_payload,
        section_url: page_payload,
    }
    live_requests: list[list[str]] = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        live_requests.append(requested)
        payloads = [payload_by_url[url] for url in requested]
        assert all(kwargs["content_validator"](body) for body in payloads)
        return _aligned_result(requested, payloads)

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict New York must not use a per-page archive loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 1)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256("EPT"),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS",
        (("EPT", "3-6.5", "", "missing_lifecycle_note"),),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS",
        (section_url,),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_URL_SHA256",
        _newline_residual_sha256((section_url,)),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )
    scraper = NewYorkScraper("NY", "New York")

    rows = asyncio.run(
        scraper.scrape_code(
            "New York Consolidated Laws",
            NewYorkScraper.OFFICIAL_ENTRY_URL,
            max_statutes=None,
        )
    )

    assert len(rows) == 362
    assert live_requests == [
        [scraper.OFFICIAL_CONSOLIDATED_URL],
        [pdf_url],
        [section_url],
    ]
    manifest = scraper._last_new_york_full_frontier[
        "supplemental_proof_manifest"
    ]
    assert manifest == [
        {
            "content_sha256": case["page_sha256"],
            "media_type": "text/html",
            "official_url": section_url,
            "proof_kind": "official_senate_section",
            "schema_version": ny_pdf.SUPPLEMENTAL_PROOF_SCHEMA_VERSION,
            "selector_key": "EPT:3-6.5:source-page",
        }
    ]
    assert scraper._last_new_york_strict_closure[
        "supplemental_proof_input_count"
    ] == 1

    ledger = _RetainedInputLedger(payload_by_url)
    scraper._state_law_acquisition_ledger = ledger
    captured: dict[str, Any] = {}

    def _retain(completion_receipt, **kwargs):
        captured["completion"] = dict(completion_receipt)
        captured["kwargs"] = dict(kwargs)
        return tmp_path / "ny-retained-supplemental-closure.json"

    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    monkeypatch.setattr(
        scraper,
        "_catalog_acquisition_path_ids_for_source",
        lambda _url: ["ny-senate-laws"],
    )
    monkeypatch.setattr(
        scraper,
        "_state_law_frontier_source_software_version",
        lambda: "ny-retained-test@sha256:" + ("c" * 64),
    )
    projection = _canonical_projection(scraper, rows)

    retained_path = asyncio.run(
        scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )
    )

    assert retained_path == tmp_path / "ny-retained-supplemental-closure.json"
    assert [request[0] for request in ledger.requests] == [
        scraper.OFFICIAL_CONSOLIDATED_URL,
        section_url,
        pdf_url,
    ]
    assert captured["completion"]["replay"]["network_requests"] == 0
    assert captured["kwargs"]["replayed_frontier"] == (
        scraper._last_new_york_full_frontier["frontier"]
    )

    ledger.payloads[section_url] = page_payload.replace(
        b"December 12, 2027",
        b"December 12, 2028",
    )
    with pytest.raises(
        RuntimeError,
        match="retained supplemental proof changed",
    ):
        asyncio.run(
            scraper.produce_state_law_frontier_closure(
                canonical_output_projection=projection,
            )
        )


def test_new_york_adapter_does_not_dump_event_proof_urls_or_use_per_page_senate_loop() -> None:
    adapter = inspect.getsource(NewYorkScraper)
    pdf_frontier = inspect.getsource(
        NewYorkScraper._scrape_official_senate_pdf_frontier
    )
    scrape_source = inspect.getsource(NewYorkScraper.scrape_code)
    registry_source = inspect.getsource(ny_pdf.NewYorkSupplementalProofRegistry)
    resolve_source = inspect.getsource(
        ny_pdf.NewYorkSupplementalProofRegistry.resolve_residual
    )

    assert INVENTED_SENATE_URL not in adapter
    assert PUBLIC_LAW_URL not in adapter
    assert INVENTED_AGENCY_PROOF_URL not in adapter
    assert str(SOURCE_SECTIONS) not in adapter
    assert str(UNRESOLVED_AFTER_AGM) not in adapter
    assert UNRESOLVED_SHA_BEFORE_AGM not in adapter
    assert SEED_PROJECTION_SHA256 not in adapter
    assert "_new_york_exact_supplemental_urls" in pdf_frontier
    assert RESIDUAL_WAVE_NAME in pdf_frontier
    assert "_fetch_new_york_frontier_batch" in pdf_frontier
    assert "_build_official_senate_section" not in pdf_frontier
    assert "public.law" in scrape_source.casefold()
    assert "refusing public.law/Justia sole-admission fallback" in scrape_source
    assert "register_resolver" not in registry_source
    assert "source_bound_resolver_not_implemented" in resolve_source
    assert "decision_action" in resolve_source
    assert '"status": "unknown"' in resolve_source
    senate_url_literals = adapter.count("https://www.nysenate.gov/legislation/laws/")
    assert senate_url_literals >= ENUMERABLE_URL_RESIDUAL
    assert senate_url_literals < 40


def test_new_york_residual_sha256_uses_newline_join_of_ordered_senate_urls() -> None:
    pinned = list(NewYorkScraper.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS)
    digest = _newline_residual_sha256(pinned)
    assert digest == RESIDUAL_SHA256
    assert digest == hashlib.sha256("\n".join(pinned).encode("utf-8")).hexdigest()
    json_digest = hashlib.sha256(
        json.dumps(pinned, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert json_digest != digest
    assert len(digest) == 64
    report = _report_text()
    assert '"\\n".join(urls)' in report
    assert "ensure_ascii=False" in report
    assert 'separators=(",", ":")' in report
    assert RESIDUAL_WAVE_NAME in report
    assert AGM28_WAVE_NAME in report
    assert CATALOG_WAVE_NAME in report
    assert PDF_WAVE_PREFIX in report


def test_new_york_one_domain_wave_disables_per_page_archive_and_reinventory() -> None:
    fetch_source = inspect.getsource(NewYorkScraper._fetch_new_york_frontier_batch)
    pdf_frontier = inspect.getsource(
        NewYorkScraper._scrape_official_senate_pdf_frontier
    )
    retry_source = inspect.getsource(
        NewYorkScraper._fetch_page_contents_with_archival_fallback_retrying_residuals
    )
    assert "wayback_prefix_inventory=True" in fetch_source
    assert "prefer_direct=True" in fetch_source
    assert "_fetch_page_contents_with_archival_fallback_retrying_residuals" in (
        fetch_source
    )
    assert "repeated a Common Crawl domain inventory" in fetch_source
    assert "repeated archive discovery on a residual retry" in fetch_source
    assert "archive.is" not in fetch_source.casefold()
    assert "repeat_grouped_archive_inventory_on_residual=True" not in fetch_source
    assert RESIDUAL_WAVE_NAME in pdf_frontier
    assert 'common_crawl_domains=(self.OFFICIAL_DOMAIN,)' in pdf_frontier or (
        "common_crawl_domains=(self.OFFICIAL_DOMAIN,)" in fetch_source
    )
    assert 'common_crawl_url_terms=("/legislation/laws/",)' in pdf_frontier
    assert "repeat_grouped_archive_inventory_on_residual: bool = False" in (
        retry_source
    )
    assert "no per-page archive loop" in retry_source

    closure_source = inspect.getsource(
        NewYorkScraper.produce_state_law_frontier_closure
    )
    assert '"per_page_archive_loop": False' in closure_source
    assert '"retained_replay_network_requests": 0' in closure_source
    assert '"grouped_warc_recovery": True' in closure_source
    assert '"kind": "shared_archive_aware_plural_pdf"' in closure_source


def test_new_york_seed_and_host_replay_forbid_hub_docker_and_unresolved_as_current(
    tmp_path: Path,
) -> None:
    seed_source = inspect.getsource(seed_retained_evidence_generation)
    union_source = inspect.getsource(seed_retained_evidence_union)
    assert 'allowed_source_transports: Sequence[str] = ("direct",)' in seed_source
    assert "No destination jurisdiction directory may already exist" in seed_source
    assert "multi-source retained evidence seed" in union_source.casefold() or (
        "Atomically union exact retained inputs" in union_source
    )
    assert "network_io_performed" in union_source

    command = build_host_retained_replay_command(
        argv=[
            "scripts/ops/legal_data/refresh_state_laws_corpus.py",
            "--states",
            "NY",
            "--scrape",
            "--retained-replay-only",
            "--strict-acquisition-evidence",
            "--no-incremental-state-publish",
        ],
        workdir=tmp_path,
    )
    joined = " ".join(command)
    assert "docker" not in command
    assert "--network" not in command
    assert "--publish-to-hf" not in command
    assert "--retained-replay-only" in command
    assert "--no-incremental-state-publish" in command
    assert "docker" not in joined.casefold()

    with pytest.raises(
        IsolatedRetainedReplayWorkerError,
        match="must not invoke docker",
    ):
        build_host_retained_replay_command(
            argv=["docker", "run", "--network", "none"],
            workdir=tmp_path,
        )

    report = " ".join(_report_text().casefold().split())
    assert "hub mutation" in report
    assert "docker-copying" in report or "docker-copy" in report
    assert "unresolved" in report
    assert "current law" in report
    assert "99-input corrected seed" in report


def test_new_york_closure_helper_still_requires_zero_network_seal_inputs() -> None:
    closure_source = inspect.getsource(retain_exact_state_frontier_closure)
    york_source = inspect.getsource(
        NewYorkScraper.produce_state_law_frontier_closure
    )
    replay_source = inspect.getsource(NewYorkScraper._replay_new_york_retained_input)
    assert "public_law_no_state_copyright" in closure_source
    assert "retained_replay_network_requests" in york_source
    assert york_source.index('"retained_replay_network_requests": 0') > 0
    assert "New York retained replay requires an attached ledger" in replay_source
    assert "without permitting network I/O" in inspect.getdoc(
        NewYorkScraper._replay_new_york_retained_input
    )
    exact_frontier = inspect.getsource(NewYorkScraper._new_york_exact_frontier)
    assert "conditional_event_selectors" in exact_frontier
    assert "did not prove occurrence" in exact_frontier


def test_new_york_compact_recipe_emits_twenty_eight_url_wave_not_invented_targets() -> None:
    derived = _derived_supplemental_urls()
    pinned = list(NewYorkScraper.STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS)
    assert derived == pinned
    assert derived[0] == FIRST_RESIDUAL_URL
    assert derived[-1] == "https://www.nysenate.gov/legislation/laws/VAT/1180-i"
    assert INVENTED_SENATE_URL not in derived
    assert PUBLIC_LAW_URL not in derived
    assert AGM28_URL not in derived
    assert OFFICIAL_CONSOLIDATED not in derived
    assert all(urlparse(url).query == "" for url in derived)
    assert all(urlparse(url).fragment == "" for url in derived)
    digest = _newline_residual_sha256(derived)
    assert digest == RESIDUAL_SHA256
    json_digest = hashlib.sha256(
        json.dumps(derived, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert not json_digest.startswith(RESIDUAL_SHA256_PREFIX)
    assert ny_pdf.public_section_url("EPT", "3-6.5") == FIRST_RESIDUAL_URL


def test_new_york_unimplemented_senate_page_resolver_stays_unknown_and_cannot_close_law(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    law_text = """
    ARTICLE 1
    UNPROVED EVENT
    Section 3-6.5. Conditional provision.
      * § 3-6.5. Conditional provision. This retained statutory body contains
      complete source text but depends upon an independently proved event.
      * NB Effective upon notification by the responsible state agency.
    """
    monkeypatch.setattr(
        ny_pdf,
        "extract_new_york_law_pdf_text",
        lambda _payload: (law_text, 1),
    )
    proof = ny_pdf.NewYorkSupplementalProofInput.bind(
        selector_key="EPT:3-6.5:source-page",
        proof_kind="official_senate_section",
        official_url=FIRST_RESIDUAL_URL,
        media_type="text/html",
        payload=b"<html>" + (b"official section page " * 80) + b"</html>",
    )
    registry = ny_pdf.NewYorkSupplementalProofRegistry([proof])
    parsed = ny_pdf.parse_new_york_law_pdf(
        b"%PDF-law",
        law_code="EPT",
        law_name="Estates, Powers and Trusts",
        supplemental_proof_registry=registry,
    )

    assert parsed.closed is False
    assert parsed.statutes == []
    assert parsed.terminal_sections == []
    assert len(parsed.unclassified_sections) == 1
    attempt = parsed.supplemental_proof_attempts[0]
    assert attempt["status"] == "unknown"
    assert attempt["proof_present"] is True
    assert attempt["decision_action"] is None
    assert attempt["reason"] == "source_bound_resolver_not_implemented"
    assert not hasattr(registry, "register_resolver")
    with pytest.raises(AttributeError):
        registry.register_resolver("EPT:3-6.5", lambda *_args, **_kwargs: None)  # type: ignore[attr-defined]


def test_new_york_compact_supplemental_wave_is_plural_and_stays_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = (
        "<html><body>Consolidated Laws of New York"
        "<a href='/legislation/laws/AAA'>AAA First Law</a>"
        "<a href='/legislation/laws/BBB'>BBB Second Law</a>"
        + (" " * 11_000)
        + "</body></html>"
    ).encode()
    pdf_by_url = {
        ny_pdf.full_law_pdf_url("AAA"): b"%PDF-AAA" + (b"a" * 1_100),
        ny_pdf.full_law_pdf_url("BBB"): b"%PDF-BBB" + (b"b" * 1_100),
    }
    supplemental_urls = (
        "https://www.nysenate.gov/legislation/laws/AAA/1",
        "https://www.nysenate.gov/legislation/laws/BBB/2",
    )
    section_html = {
        url: (
            b"<html><body><div class='nys-openleg-content-container'>"
            b"New York State Senate /legislation/laws/ "
            + (url.encode() + b" ") * 40
            + b"</div></body></html>"
        )
        for url in supplemental_urls
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []

    async def _fake_plural(self, urls, *, residual_retry_attempts, **kwargs):
        requested = list(urls)
        calls.append((requested, dict(kwargs)))
        payloads = []
        for url in requested:
            if url == self.OFFICIAL_CONSOLIDATED_URL:
                payloads.append(catalog)
            elif url in pdf_by_url:
                payloads.append(pdf_by_url[url])
            elif url in section_html:
                payloads.append(section_html[url])
            else:
                raise AssertionError(f"compact residual requested unknown URL {url}")
        assert all(kwargs["content_validator"](body) for body in payloads)
        return _aligned_result(requested, payloads)

    resolution_attempts: list[dict[str, Any]] = []

    def _fake_parse(
        _payload,
        *,
        law_code,
        law_name,
        supplemental_proof_registry,
        **_kwargs,
    ):
        row = (
            {
                "section_number": "1",
                "toc_variant": "",
                "reason": "ambiguous_lifecycle_status",
                "detail": "missing_lifecycle_note:",
            }
            if law_code == "AAA"
            else {
                "section_number": "2",
                "toc_variant": "*2",
                "reason": "toc_section_missing_body_identity",
                "detail": "toc_offset=1",
            }
        )
        resolution_attempts.append(
            supplemental_proof_registry.resolve_residual(
                law_code=law_code,
                residual=row,
            )
        )
        return SimpleNamespace(
            closed=False,
            law_code=law_code,
            law_name=law_name,
            source_section_count=1,
            statutes=[],
            terminal_sections=[],
            unclassified_sections=[row],
        )

    async def _forbid_single(*_args, **_kwargs):
        raise AssertionError("strict New York must not use a per-page archive loop")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(NewYorkScraper, "STRICT_MINIMUM_CONSOLIDATED_LAWS", 2)
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_CONSOLIDATED_CODE_SHA256",
        _ordered_code_sha256("AAA", "BBB"),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_RESIDUAL_ROWS",
        (
            ("AAA", "1", "", "missing_lifecycle_note"),
            ("BBB", "2", "*2", "toc_section_missing_body_identity"),
        ),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_SECTION_URLS",
        supplemental_urls,
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "STRICT_CURRENT_SUPPLEMENTAL_URL_SHA256",
        _newline_residual_sha256(supplemental_urls),
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _fake_plural,
    )
    monkeypatch.setattr(
        NewYorkScraper,
        "_fetch_page_content_with_archival_fallback",
        _forbid_single,
    )
    monkeypatch.setattr(ny_pdf, "parse_new_york_law_pdf", _fake_parse)
    scraper = NewYorkScraper("NY", "New York")

    with pytest.raises(RuntimeError, match="law=AAA"):
        asyncio.run(
            scraper.scrape_code(
                "New York Consolidated Laws",
                NewYorkScraper.OFFICIAL_ENTRY_URL,
                max_statutes=None,
            )
        )

    requested_waves = [call[0] for call in calls]
    assert requested_waves[0] == [scraper.OFFICIAL_CONSOLIDATED_URL]
    assert requested_waves[1] == list(pdf_by_url)
    assert requested_waves[-1] == list(supplemental_urls)
    assert INVENTED_SENATE_URL not in [url for wave in requested_waves for url in wave]
    assert PUBLIC_LAW_URL not in [url for wave in requested_waves for url in wave]
    assert AGM28_URL not in [url for wave in requested_waves for url in wave]
    supplemental_kwargs = calls[-1][1]
    assert supplemental_kwargs["common_crawl_domain_terms"] == (OFFICIAL_DOMAIN,)
    assert supplemental_kwargs["common_crawl_url_terms"] == ("/legislation/laws/",)
    assert supplemental_kwargs["wayback_prefix_inventory"] is True
    assert supplemental_kwargs["prefer_direct"] is True
    assert all(row["status"] == "unknown" for row in resolution_attempts)
    assert all(row["decision_action"] is None for row in resolution_attempts)
    stats = list(getattr(scraper, "_new_york_frontier_batch_stats", []))
    assert [row["frontier_name"] for row in stats][-1] == RESIDUAL_WAVE_NAME
