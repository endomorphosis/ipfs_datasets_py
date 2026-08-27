"""Scraper for Oregon state laws.

This implementation parses Oregon Revised Statutes (ORS) chapter pages and
builds section-level records with rich structure, including:
- preambles
- subsection trees
- citation extraction
- trailing legislative history extraction
- per-section JSON-LD (US Code style fields)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .oregon_admin_rules import OregonAdministrativeRulesScraper
from .registry import StateScraperRegistry

try:
    from bs4 import BeautifulSoup

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

ORS_LINK_RE = re.compile(r"ors(\d{3}[a-z]?)\.html$", re.IGNORECASE)
ORS_TERMINAL_DISPOSITION_RE = re.compile(
    r"\b(renumbered|repealed|reserved|expired|transferred|former provisions?)\b",
    re.IGNORECASE,
)
ORS_VARIANT_NOTE_RE = re.compile(r"^Note(?:\s+\d+)?:", re.IGNORECASE)
ORS_CALENDAR_DATE_RE = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+"
    r"(?P<day>\d{1,2}),\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
ORS_CONDITIONAL_SECTION_EVENT_KEYS = {
    "187.110": "permanent_daylight_time",
    "195.308": "private_forest_accord_rollback",
    "196.800": "clean_water_act_404_assumption",
    "196.810": "clean_water_act_404_assumption",
    "196.850": "clean_water_act_404_assumption",
    "196.895": "clean_water_act_404_assumption",
    "196.921": "clean_water_act_404_assumption",
    "196.990": "clean_water_act_404_assumption",
    "291.055": "puc_hb3148_rules",
    "317a.100": "puc_hb3148_rules",
    "323.806": "tobacco_amendment_judgment",
    "390.835": "clean_water_act_404_assumption",
    "403.205": "puc_hb3148_rules",
    "411.847": "snap_hot_foods_federal_approval",
    "421.628": "clean_water_act_404_assumption",
    "433.321": "cmv_bloodspot_panel",
    "459.047": "clean_water_act_404_assumption",
    "469.992": "radioactive_material_regulatory_change",
    "496.252": "private_forest_accord_rollback",
    "496.254": "private_forest_accord_rollback",
    "527.620": "private_forest_accord_rollback",
    "527.630": "private_forest_accord_rollback",
    "527.680": "private_forest_accord_rollback",
    "527.685": "private_forest_accord_rollback",
    "527.714": "private_forest_accord_rollback",
    "527.990": "private_forest_accord_rollback",
    "527.992": "private_forest_accord_rollback",
    "610.060": "private_forest_accord_rollback",
    "610.105": "private_forest_accord_rollback",
}
ORS_CONDITIONAL_EVENT_NOTE_MARKERS = {
    "permanent_daylight_time": ("chapter 421, oregon laws 2019",),
    "private_forest_accord_rollback": ("certain conditions are met",),
    "clean_water_act_404_assumption": (
        "dependent upon further approval by the legislative assembly",
    ),
    "puc_hb3148_rules": (
        "public utility commission adopts necessary rules",
    ),
    "tobacco_amendment_judgment": (
        "final judgment that invalidates the amendments",
    ),
    "snap_hot_foods_federal_approval": (
        "receipt of any federal approval that is necessary",
    ),
    "cmv_bloodspot_panel": (
        "adds cytomegalovirus to the newborn bloodspot screening panel",
    ),
    "radioactive_material_regulatory_change": (
        "exempts from regulation or changes the regulatory status",
    ),
}

# Current-law selectors are intentionally separate from the ORS chapter
# frontier.  The chapter bytes already carry the exact conditional language;
# fetching those locators again would duplicate retained work.  Each entry
# below therefore names only independent official evidence for whether the
# source-printed alternate is operative at the observation point.  Selectors
# are exact and fail closed when an official page changes its wording.
ORS_CONDITIONAL_EVENT_SELECTOR_SPECS: Dict[str, Dict[str, Any]] = {
    "permanent_daylight_time": {
        "status": "not_occurred",
        "alternate_active": False,
        "event_date": None,
        "operative_date": None,
        "conclusion": (
            "California and Washington retain seasonal time; the joint "
            "year-round daylight-time trigger has not occurred."
        ),
        "sources": (
            {
                "url": (
                    "https://app.leg.wa.gov/RCW/default.aspx?cite=1.20.051"
                ),
                "require_all": (
                    "Daylight saving time. (Contingent repeal.)",
                    "second Sunday in March",
                    "first Sunday in November",
                    "returned to Pacific Standard Time",
                ),
            },
            {
                "url": (
                    "https://app.leg.wa.gov/RCW/default.aspx?cite=1.20.055"
                ),
                "require_all": (
                    "Pacific daylight time. (Contingent effective date.)",
                    "take effect on the first Sunday in November following "
                    "the effective date of federal authorization",
                ),
            },
            {
                "url": (
                    "https://leginfo.legislature.ca.gov/faces/"
                    "codes_displaySection.xhtml?sectionNum=6808.&lawCode=GOV"
                ),
                "require_all": (
                    "California Code, GOV 6808.",
                    "The standard time within the state is that of the fifth "
                    "zone designated by federal law as Pacific standard time",
                    "second Sunday of March",
                    "first Sunday of November",
                    "if federal law authorizes the state to provide for the "
                    "year-round application of daylight saving time",
                ),
            },
            {
                "url": (
                    "https://www.nist.gov/pml/time-and-frequency-division/"
                    "popular-links/daylight-saving-time-dst"
                ),
                "require_all": (
                    "During 2026, daylight saving time is in effect from "
                    "March 8 at 2 a.m.",
                    "to November 1 at 2 a.m.",
                    "ends at 2:00 a.m. on the first Sunday of November",
                ),
            },
        ),
    },
    "tobacco_amendment_judgment": {
        "status": "occurred",
        "alternate_active": True,
        "event_date": "2024-06-07",
        "operative_delay_days": 31,
        "operative_date": "2024-07-08",
        "conclusion": (
            "The invalidating General Judgment was entered June 7, 2024; "
            "Oregon DOJ currently administers the restored escrow branch."
        ),
        "sources": (
            {
                "url": (
                    "https://trportal-api.courts.oregon.gov/courts/cms/"
                    "docketentrydocuments?documentLinkUUID="
                    "5fb5d84d-5f47-43e6-97d3-900b68430103&"
                    "thisExactPhrase=June%207%2C%202024&size=10"
                ),
                "require_all": (
                    '"documentName":"Initiating Document - Notice of Appeal"',
                    '"official":true',
                    '"caseNumber":"A184673"',
                    '"caseTitle":"Xcaliber International LTD, LLC v. State of Oregon"',
                    "appeal from the General Judgment (judgment) entered in "
                    "this case on June 7, 2024",
                    "June 7, 2024, the date of entry of the judgment being appealed",
                ),
            },
            {
                "url": (
                    "https://trportal-api.courts.oregon.gov/courts/cms/"
                    "docketentrydocuments?documentLinkUUID="
                    "83899511-71e9-4b3a-abbf-e20b3434ee5a&"
                    "thisExactPhrase=declared%20it%20invalid&size=10"
                ),
                "require_all": (
                    '"documentName":"Brief - Answering"',
                    '"official":true',
                    '"caseNumber":"A184673"',
                    "trial court determined that HB 2128 amounts to a bill "
                    "for raising revenue enacted without the required supermajorities",
                    "declared it invalid on those grounds",
                ),
            },
            {
                "url": (
                    "https://trportal-api.courts.oregon.gov/courts/cms/cases?"
                    "caseHeader.caseNumber=A184673&"
                    "caseHeader.caseNumberSearchType=10463&size=20"
                ),
                "require_all": (
                    '"caseStatus":"Under Advisement"',
                    '"originatingCaseNumber":"23CV52166"',
                ),
            },
            {
                "url": (
                    "https://www.doj.state.or.us/oregon-department-of-justice/"
                    "publications-forms/tobacco-legislation/"
                ),
                "require_all": (
                    "Escrow Compliance Certificate and Affidavit",
                    "all non-participating manufacturers",
                    "must file quarterly and annual escrow compliance certificates",
                    "make any required deposits to their qualified escrow funds",
                ),
                "absent_raw_terms": ("equity assessment",),
            },
            {
                "url": (
                    "https://www.doj.state.or.us/wp-content/uploads/2026/02/"
                    "2026-Annual-and-Quarterly-Escrow-Compliance-Certificate.pdf"
                ),
                "require_all": (
                    "2026 Escrow Compliance Certificate and Affidavit",
                    "Revised: February 17, 2026",
                    "SALES YEAR: 2026",
                    "Calculation of Deposit Amount",
                    "$0.0188482",
                    "$0.0474464",
                    "proof of deposit of the proper escrow payment",
                ),
            },
        ),
    },
    "snap_hot_foods_federal_approval": {
        # No official approval receipt/date is published.  These positive
        # current-status selectors establish only that the alternate program
        # is not yet operative, without falsely claiming the event did not occur.
        "status": "unknown",
        "alternate_active": False,
        "event_date": None,
        "operative_date": None,
        "conclusion": (
            "ODHS affirmatively describes the program as still in development, "
            "and USDA's exhaustive operating-state list excludes Oregon."
        ),
        "sources": (
            {
                "url": (
                    "https://www.oregon.gov/odhs/agency/Pages/ssp-rmp.aspx"
                ),
                "require_all": (
                    "We're developing a pilot program to expand access to hot meals",
                    "would let eligible SNAP participants",
                    "Right now, we're developing the program",
                    "We plan to test it in select areas in Oregon",
                ),
            },
            {
                "url": (
                    "https://www.fna.usda.gov/snap/retailer/"
                    "restaurant-meals-program"
                ),
                "require_all": (
                    "States that Operate a Restaurant Meals Program",
                    "Arizona",
                    "California",
                    "Illinois",
                    "Maryland",
                    "Massachusetts",
                    "Michigan",
                    "New York",
                    "Rhode Island",
                    "Virginia",
                    "Page updated: August 07, 2026",
                ),
                "absent_raw_terms": ("<strong>Oregon</strong>",),
            },
        ),
    },
    "radioactive_material_regulatory_change": {
        "status": "not_occurred",
        "alternate_active": False,
        "event_date": None,
        "operative_date": None,
        "conclusion": (
            "The current Oregon compiler keeps the alternate prospective; "
            "the NRC records that the intended below-regulatory-concern policy "
            "was placed under moratorium and then revoked."
        ),
        "sources": (
            {
                "url": (
                    "https://www.nrc.gov/sites/default/files/doc_library/cdn/"
                    "legacy/reading-rm/doc-collections/commission/secys/1999/"
                    "secy1999-098/1999-098scy.pdf"
                ),
                "require_all": (
                    "Below Regulatory Concern (BRC) Policy Statement on "
                    "July 3, 1990",
                    "instituted a moratorium on the BRC Policy in July 1991",
                    "in October 1992",
                    "Energy Policy Act of 1992",
                    "revoked the BRC Policy Statement",
                ),
            },
        ),
    },
    "puc_hb3148_rules": {
        "status": "not_occurred",
        "alternate_active": False,
        "event_date": None,
        "operative_date": None,
        "conclusion": (
            "The April 2026 order completed only Phase I; the official current "
            "rulemaking inventory still identifies the necessary device-benefit "
            "implementation as Phase II."
        ),
        "context": {
            "phase_i_approved": "2026-03-31",
            "phase_i_effective": "2026-04-01",
            "statutory_deadline": "2026-12-01",
            "confidence": "high",
        },
        "sources": (
            {
                "url": (
                    "https://www.oregon.gov/puc/about-us/Pages/Rulemakings.aspx"
                ),
                "require_all": (
                    "AR 675 -- (Phase II) -- In the Matter of Rulemaking to "
                    "Implement 2025 HB 3148 Relating to One-Time Device Benefit "
                    "for Low-Income Customers",
                    "AR 675 -- (Phase I) -- In the Matter of Rulemaking to "
                    "Implement 2025 HB 3148 Relating to the Availability of "
                    "Residential Telecommunication Services for Low-Income "
                    "Customers and Amendment to No-Match Provision (rules "
                    "effective April 1, 2026)",
                    "Page last updated: 08/20/2026",
                ),
                "require_any": ("Draft Rulemakings", "Formal Rulemakings"),
                "absent_terms": (
                    "AR 675 -- (Phase II) -- In the Matter of Rulemaking to "
                    "Implement 2025 HB 3148 Relating to One-Time Device Benefit "
                    "for Low-Income Customers (rules effective",
                ),
            },
            {
                "url": (
                    "https://edocs.puc.state.or.us/efdocs/HAH/"
                    "ar675hah344856035.pdf"
                ),
                "require_all": (
                    "Phase II of the rulemaking process for HB 3148 will include "
                    "implementing the provision of HB 3148 that provides a "
                    "one-time personal computing device benefit of up to $100",
                    "Staff's express purpose for this phase of the rulemaking "
                    "was limited to three purposes",
                    "Staff will continue implementation of HB 3148 via a second "
                    "phase of rulemaking",
                ),
                "require_any": (
                    "one-time personal computing device benefit",
                    "Phase II",
                ),
            },
        ),
    },
    "cmv_bloodspot_panel": {
        "status": "not_occurred",
        "alternate_active": False,
        "event_date": None,
        "operative_date": None,
        "conclusion": (
            "OHA currently requires targeted risk/sign screening, while its "
            "exhaustive bloodspot panel omits CMV and routes requested residual "
            "bloodspots to a reference laboratory."
        ),
        "context": {
            "targeted_protocol_adopted": "2026-01-01",
            "hospital_start_deadline": "2026-04-01",
            "confidence": "high",
        },
        "sources": (
            {
                "url": (
                    "https://www.oregon.gov/oha/PH/HEALTHYPEOPLEFAMILIES/"
                    "BABIES/HEALTHSCREENING/HEARINGSCREENING/Pages/"
                    "Cytomegalovirus-%28CMV%29.aspx"
                ),
                "require_all": (
                    "expanded targeted congenital cytomegalovirus (cCMV) screening",
                    "assessing each newborn for known risk factors and clinical "
                    "signs of cCMV",
                    "as necessary, based on the presence of one or more of the "
                    "risk factors or clinical signs, conduct CMV testing",
                    "no later than April 1, 2026",
                    "OHA Congenital Cytomegalovirus (cCMV) Screening Protocol "
                    "(January 2026)",
                ),
            },
            {
                "url": (
                    "https://www.oregon.gov/oha/PH/LABORATORYSERVICES/"
                    "NEWBORNSCREENING/Documents/Conditions%20on%20the%20Oregon%20"
                    "Newborn%20Bloodspot%20Screening%20Panel%20%28pdf%29.pdf"
                ),
                "require_all": (
                    "Medical Conditions on the Oregon Newborn Bloodspot Screening Panel",
                    "Updated November 2025",
                    "Spinal muscular atrophy (SMA)",
                    "X-linked adrenoleukodystrophy (X-ALD)",
                ),
                "absent_terms": ("Cytomegalovirus", "CMV"),
            },
            {
                "url": (
                    "https://www.oregon.gov/oha/PH/LABORATORYSERVICES/"
                    "NEWBORNSCREENING/Pages/specimen-use.aspx"
                ),
                "require_all": (
                    "OSPHL will transfer residual bloodspot specimens to a "
                    "reference laboratory for CMV testing at the request of the "
                    "parent or legal guardian of the infant and the ordering "
                    "medical provider",
                ),
                "require_any": (
                    "Request for Specimen Transfer for CMV Testing at a Reference "
                    "Laboratory Form",
                ),
            },
        ),
    },
    "clean_water_act_404_assumption": {
        "status": "not_occurred",
        "alternate_active": False,
        "event_date": None,
        "operative_date": None,
        "conclusion": (
            "EPA's exhaustive current list limits assumed Section 404 programs "
            "to Michigan and New Jersey, and Oregon DEQ identifies the Corps as "
            "the current Oregon authorization administrator."
        ),
        "context": {
            "epa_status_date": "2026-08-14",
            "confidence": "very_high",
        },
        "sources": (
            {
                "url": (
                    "https://www.epa.gov/cwa404g/"
                    "tribal-and-state-section-404-assumption-efforts"
                ),
                "require_all": (
                    "there are only two states -- Michigan and New Jersey -- "
                    "that currently implement Section 404 programs for assumable "
                    "waters within their jurisdiction",
                    "The U.S. Army Corps of Engineers is primarily responsible "
                    "for issuing Section 404 dredged and fill permits in the "
                    "remaining regions of the United States",
                    "Last updated on August 14, 2026",
                ),
            },
            {
                "url": (
                    "https://www.oregon.gov/deq/programs/pages/"
                    "interstate-bridge-replacement.aspx"
                ),
                "require_all": (
                    "DEQ received a request for a Section 401 water quality "
                    "certification on Feb. 17, 2026",
                    "This certification is part of the federal 404 authorization "
                    "process administered by the U.S. Army Corps of Engineers",
                    "The U.S. Army Corps of Engineers is the lead regulatory "
                    "agency for the 404 authorization process",
                ),
            },
        ),
    },
    "private_forest_accord_rollback": {
        "status": "not_occurred",
        "alternate_active": False,
        "event_date": None,
        "operative_date": None,
        "conclusion": (
            "ODF's dated workflow keeps the HCP, biological opinion and "
            "incidental-take permit pending; its statutory permit/finding report "
            "is likewise marked not started."
        ),
        "context": {
            "no_itp_deadline": "2027-12-31",
            "no_itp_branch_operative_date": "2028-06-01",
            "confidence": "medium_high",
        },
        "sources": (
            {
                "url": (
                    "https://www.oregon.gov/odf/board/documents/ampc/"
                    "20260413-ampc-presentation-oregon-private-forest-accord-"
                    "aquatic-habitat-conservation-plan.pdf"
                ),
                "require_all": (
                    "Oregon PFA Aquatic HCP",
                    "April 13, 2026",
                    "Where are we now?",
                    "Dec 2025 submitted",
                    "Services Review",
                    "Final HCP",
                    "Biological Opinion",
                    "Incidental Take Permit",
                    "December 2027",
                ),
            },
            {
                "url": (
                    "https://www.oregon.gov/odf/aboutodf/Documents/"
                    "2025-pfa-progress-report.pdf"
                ),
                "require_all": (
                    "Private Forest Accord Implementation: 2025 Progress Report",
                    "Report to the legislative committees whether ITPs were "
                    "issued by 12/31/2027 & if a petition was received from a "
                    "PFA Report author",
                    "Not Started",
                    "2/1/2028 or earlier",
                ),
                "require_any": (
                    "Submit a proposed draft HCP",
                    "requires the pursuit of incidental take permits (ITPs) "
                    "through a habitat conservation plan (HCP)",
                ),
            },
        ),
    },
}

ORS_CITATION_RE = re.compile(r"\b\d{1,3}[a-z]?\.\d{3,4}[a-z]?\b", re.IGNORECASE)
OR_LAWS_CITATION_RE = re.compile(r"\bOr\.?\s+Laws\s+\d{4},\s+c\.?\s*\d+\b", re.IGNORECASE)
USC_CITATION_RE = re.compile(r"\b\d+\s+U\.?\s*S\.?\s*C\.?\s*(?:§+\s*)?\d[\w\-.()]*", re.IGNORECASE)
SECTION_REF_RE = re.compile(
    r"\b(?:section|sec\.?|§{1,2})\s+[\w\-.(),\sand]+(?:\s+of\s+(?:this\s+chapter|ORS\s+chapter\s+\d+))?\b",
    re.IGNORECASE,
)
COURT_RULES_LIST_API_URL = (
    "https://www.courts.oregon.gov/rules/_api/web/lists/"
    "getbytitle(%27Other%20Rules%27)/items"
    "?$top=5000&$select=Title,EncodedAbsUrl"
)
LOCAL_RULES_INDEX_URL = "https://www.courts.oregon.gov/rules/Pages/slr.aspx"
ORCP_PRIMARY_URL = "https://www.oregonlegislature.gov/bills_laws/Pages/orcp.aspx"
ORCP_EXPANDED_URL = "https://www.oregonlegislature.gov/bills_laws/SiteAssets/ORCP.html"
LOCAL_RULE_LINK_RE = re.compile(r"/courts/.+/Pages/(?:rules|Rules|CourtRules|Court-Rules)\.aspx", re.IGNORECASE)
ORCP_RULE_HEADING_RE = re.compile(r"\bRule\s+([0-9]{1,3}[A-Za-z]?)\s*[-:]\s*(.+)", re.IGNORECASE)
LOCAL_RULE_DOC_PATH_RE = re.compile(r"\.(?:pdf|doc|docx)(?:$|[?#])|/documents/|/documentlibrary/", re.IGNORECASE)
LOCAL_RULE_TEXT_RE = re.compile(r"\brules?\b|\bslr\b|supplementary local", re.IGNORECASE)


def _norm_space(text: str) -> str:
    text = str(text or "")
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = text.replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_ors_selector_text(text: str) -> str:
    """Normalize official selector text without weakening exact phrases."""

    normalized = unicodedata.normalize("NFKC", str(text or ""))
    # The official Oregon appellate search API inserts these deterministic
    # query-highlight sentinels inside matched document text.
    normalized = re.sub(r"\[h\d+[se]\]", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])",
        "",
        normalized,
    )
    return _norm_space(normalized).casefold()


def _dedupe_keep_order(items: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        value = _norm_space(str(item or ""))
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _lineify(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines: List[str] = []
    for raw_line in text.splitlines():
        line = _norm_space(raw_line)
        if line:
            lines.append(line)
    return lines


def _ors_conditional_event_keys_in_html(html: str) -> List[str]:
    """Return conditional keys whose exact compiler note occurs in one page."""

    without_markup = re.sub(r"<[^>]+>", " ", str(html or ""))
    lowered = _norm_space(without_markup).casefold()
    return sorted(
        event_key
        for event_key, markers in ORS_CONDITIONAL_EVENT_NOTE_MARKERS.items()
        if markers and all(marker.casefold() in lowered for marker in markers)
    )


def _chapter_slug_from_url(url: str) -> Optional[str]:
    match = ORS_LINK_RE.search(str(url or ""))
    if not match:
        return None
    return match.group(1).lower()


def _chapter_number_display(chapter_slug: str) -> str:
    digits = "".join(ch for ch in chapter_slug if ch.isdigit())
    suffix = "".join(ch for ch in chapter_slug if ch.isalpha())
    if not digits:
        return chapter_slug
    return f"{int(digits)}{suffix}"


def _extract_chapter_title(lines: Sequence[str], chapter_display: str) -> str:
    pattern = re.compile(
        rf"^chapter\s+{re.escape(chapter_display)}\b\s*[\-\u2013\u2014\u00ad\u00a0\s:]*\s*(.*)$",
        re.IGNORECASE,
    )
    candidates: List[str] = []
    prefix = list(lines[:200])
    for index, line in enumerate(prefix):
        candidates.append(line)
        if line.casefold() == "chapter" and index + 1 < len(prefix):
            # Some Word exports split "Chapter" and its numbered title into
            # adjacent paragraphs.  Rejoin only this exact source structure.
            candidates.append(f"{line} {prefix[index + 1]}")
    for line in candidates:
        match = pattern.match(line)
        if match:
            value = _norm_space(match.group(1))
            if value:
                return value
    return ""


def _extract_edition_year(lines: Sequence[str]) -> Optional[int]:
    prefix = list(lines[:300])
    for index, line in enumerate(prefix):
        candidates = [line]
        if index + 1 < len(prefix):
            # Most current Word exports split the edition header across two
            # adjacent paragraphs (``2025`` / ``EDITION``).
            candidates.append(f"{line} {prefix[index + 1]}")
        for candidate in candidates:
            match = re.search(
                r"\b(20\d{2})\s+edition\b",
                candidate,
                flags=re.IGNORECASE,
            )
            if match:
                try:
                    return int(match.group(1))
                except Exception:
                    return None
    return None


def _ors_chapter_matches_edition(html: str, expected_year: int) -> bool:
    """Reject an explicitly stale chapter while allowing unlabeled templates."""

    observed_year = _extract_edition_year(_lineify(html))
    return observed_year is None or observed_year == int(expected_year)


def _section_start_regex(chapter_display: str) -> re.Pattern[str]:
    # Uniform Commercial Code chapters 72A, 74A, 77, 78 and 79A print
    # four-digit article/section numbers (for example 79A.1010); ordinary ORS
    # chapters use three digits.  Both are source identities, not a heuristic.
    return re.compile(
        rf"^\s*({re.escape(chapter_display)}\.\d{{3,4}}[a-z]?)\b\s*(.*)$",
        re.IGNORECASE,
    )


def _section_sort_key(section_id: str) -> Tuple[int, str]:
    match = re.match(r"^([0-9]+)\.([0-9]+)([a-z]?)$", str(section_id or ""), flags=re.IGNORECASE)
    if not match:
        return (10**9, str(section_id or ""))
    return (int(match.group(2)), (match.group(3) or "").lower())


def _parse_ors_calendar_date(value: str) -> Optional[date]:
    """Parse one source-printed ORS calendar date without guessing."""

    match = ORS_CALENDAR_DATE_RE.search(str(value or ""))
    if match is None:
        return None
    try:
        return datetime.strptime(
            f"{match.group('month')} {match.group('day')} {match.group('year')}",
            "%B %d %Y",
        ).date()
    except ValueError:
        return None


def _ors_variant_interval(
    *,
    note: str,
    section_number: str,
    conditional_outcomes: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Return the exact interval printed for one convenience-text variant.

    Oregon places alternate statutory text immediately after a source-labelled
    ``Note`` paragraph.  Only explicit calendar intervals are resolved here;
    contingent events, academic years, tax years, and unlabeled duplicates stay
    unresolved so strict corpus production fails closed.
    """

    normalized = _norm_space(note)
    if ORS_VARIANT_NOTE_RE.match(normalized) is None:
        return None
    if re.search(rf"\b{re.escape(section_number)}\b", normalized, re.IGNORECASE) is None:
        return None

    event_key = ORS_CONDITIONAL_SECTION_EVENT_KEYS.get(section_number.casefold())
    event_outcome = (
        conditional_outcomes.get(event_key)
        if event_key is not None and isinstance(conditional_outcomes, Mapping)
        else None
    )
    lowered = normalized.casefold()
    event_markers = ORS_CONDITIONAL_EVENT_NOTE_MARKERS.get(event_key or "", ())
    event_note = bool(event_markers) and all(
        marker in lowered for marker in event_markers
    )
    if event_note and isinstance(event_outcome, Mapping):
        status = str(event_outcome.get("status") or "").strip().casefold()
        alternate_active = event_outcome.get("alternate_active")
        if status not in {"occurred", "not_occurred", "unknown"} or not isinstance(
            alternate_active,
            bool,
        ):
            return None
        evidence_digests = event_outcome.get("selector_evidence_sha256")
        receipt_digests = event_outcome.get("selector_receipt_sha256", ())
        source_urls = event_outcome.get("selector_source_urls")
        if (
            not isinstance(evidence_digests, Sequence)
            or isinstance(evidence_digests, (str, bytes, bytearray))
            or not evidence_digests
            or not isinstance(source_urls, Sequence)
            or isinstance(source_urls, (str, bytes, bytearray))
            or not source_urls
            or not isinstance(receipt_digests, Sequence)
            or isinstance(receipt_digests, (str, bytes, bytearray))
        ):
            return None
        event_context: Dict[str, Any] = {
            "event_key": event_key,
            "event_status": status,
            "event_observed_at": str(
                event_outcome.get("observed_at") or ""
            ).strip(),
            "event_date": str(event_outcome.get("event_date") or "").strip()
            or None,
            "operative_date": str(
                event_outcome.get("operative_date") or ""
            ).strip()
            or None,
            "selector_evidence_sha256": [
                str(item).strip().casefold() for item in evidence_digests
            ],
            "selector_receipt_sha256": [
                str(item).strip().casefold() for item in receipt_digests
            ],
            "selector_source_urls": [str(item).strip() for item in source_urls],
            "selector_decision_sha256": str(
                event_outcome.get("selector_decision_sha256") or ""
            ).strip().casefold(),
            "selector_conclusion": str(
                event_outcome.get("selector_conclusion") or ""
            ).strip(),
            "selector_context": dict(
                event_outcome.get("selector_context")
                if isinstance(event_outcome.get("selector_context"), Mapping)
                else {}
            ),
        }
        if not alternate_active:
            return {
                "effective_start": None,
                "effective_end": None,
                "interval_kind": "conditional_event_not_met",
                "forced_inactive": True,
                **event_context,
            }

        operative_date = _coerce_ors_as_of(
            str(event_outcome.get("operative_date") or "")
        )
        if operative_date is None:
            return None
        event_end_match = re.search(
            r"\buntil\s+(?P<end>"
            r"(?:January|February|March|April|May|June|July|August|September|"
            r"October|November|December)\s+\d{1,2},\s+20\d{2})",
            normalized,
            re.IGNORECASE,
        )
        event_end = (
            _parse_ors_calendar_date(event_end_match.group("end"))
            if event_end_match is not None
            else None
        )
        if event_end is not None and operative_date >= event_end:
            return None
        return {
            "effective_start": operative_date,
            "effective_end": event_end,
            "interval_kind": (
                "conditional_event_from_until"
                if event_end is not None
                else "conditional_event_on_and_after"
            ),
            **event_context,
        }

    calendar = (
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},\s+20\d{2}"
    )
    from_until = re.search(
        rf"text\s+that\s+is\s+operative\s+from\s+(?P<start>{calendar})\s*,?\s+"
        rf"until\s+(?P<end>{calendar})",
        normalized,
        re.IGNORECASE,
    )
    if from_until is not None:
        start = _parse_ors_calendar_date(from_until.group("start"))
        end = _parse_ors_calendar_date(from_until.group("end"))
        if start is None or end is None or start >= end:
            return None
        return {
            "effective_start": start,
            "effective_end": end,
            "interval_kind": "from_until",
        }

    on_after = re.search(
        rf"text\s+that\s+is\s+operative\s+on\s+and\s+after\s+"
        rf"(?P<start>{calendar}|that\s+date)",
        normalized,
        re.IGNORECASE,
    )
    if on_after is not None:
        printed_start = on_after.group("start")
        start = _parse_ors_calendar_date(printed_start)
        if start is None and printed_start.casefold() == "that date":
            operative = re.search(
                rf"become\s+operative(?:\s+on)?\s+(?P<start>{calendar})",
                normalized,
                re.IGNORECASE,
            )
            start = (
                _parse_ors_calendar_date(operative.group("start"))
                if operative is not None
                else None
            )
        if start is None:
            return None
        return {
            "effective_start": start,
            "effective_end": None,
            "interval_kind": "on_and_after",
        }

    until = re.search(
        rf"text\s+that\s+is\s+operative\s+until\s+(?P<end>{calendar})",
        normalized,
        re.IGNORECASE,
    )
    if until is not None:
        end = _parse_ors_calendar_date(until.group("end"))
        if end is None:
            return None
        return {
            "effective_start": None,
            "effective_end": end,
            "interval_kind": "until",
        }

    future_application = re.search(
        rf"text\s+that\s+applies\b.*?\bon\s+or\s+after\s+"
        rf"(?P<start>{calendar})",
        normalized,
        re.IGNORECASE,
    )
    if future_application is not None:
        start = _parse_ors_calendar_date(future_application.group("start"))
        if start is None:
            return None
        return {
            "effective_start": start,
            "effective_end": None,
            "interval_kind": "application_on_and_after",
        }

    if (
        "as it existed before the amendments" in lowered
        or re.search(
            r"text\s+that\s+applies\b.*\b(?:prior\s+to|filed\s+before|"
            r"beginning\s+before)",
            normalized,
            re.IGNORECASE,
        )
        is not None
    ):
        return {
            "effective_start": None,
            "effective_end": None,
            "interval_kind": "source_labelled_prior_application",
            "forced_inactive": True,
        }

    repeal = re.search(
        rf"\b{re.escape(section_number)}\s+is\s+repealed\s+"
        rf"(?P<end>{calendar})",
        normalized,
        re.IGNORECASE,
    )
    if repeal is not None:
        end = _parse_ors_calendar_date(repeal.group("end"))
        if end is None:
            return None
        return {
            "effective_start": None,
            "effective_end": end,
            "interval_kind": "before_repeal",
        }
    return None


def _coerce_ors_as_of(value: Optional[Union[str, date, datetime]]) -> Optional[date]:
    """Coerce an explicit retained-evidence date; never use wall-clock time."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None

class OregonScraper(BaseStateScraper):
    """Scraper for Oregon state laws from https://www.oregonlegislature.gov"""

    OFFICIAL_DOMAIN = "www.oregonlegislature.gov"
    OFFICIAL_ENTRY_PATH = "/bills_laws/Pages/ORS.aspx"
    OFFICIAL_ENTRY_URL = "https://www.oregonlegislature.gov/bills_laws/Pages/ORS.aspx"
    OFFICIAL_CHAPTER_PATH = "/bills_laws/ors/"
    NONOFFICIAL_SEED_DISPOSITION = "nonofficial_oregon_seed"
    MISSING_LINK_DISPOSITION = "missing_official_source_link"
    last_official_quarantines: List[Dict[str, str]] = []
    _SECONDARY_HOST_MARKERS = (
        "justia.com",
        "findlaw.com",
        "unicourt.github.io",
        "law.cornell.edu",
        "huggingface.co",
        "open-us-law-bucket",
    )
    _ORS_CHAPTER_HREF_RE = re.compile(
        r"/bills_laws/ors/ors(?P<chapter>\d{3}[a-z]?)\.html",
        re.IGNORECASE,
    )
    _ORS_CHAPTER_FILE_RE = re.compile(r"^ors(?P<chapter>\d{3}[a-z]?)\.html$", re.IGNORECASE)
    _ORS_CITE_RE = re.compile(
        r"\b(?:ORS|Or(?:egon)?\.?\s*Rev(?:ised)?\.?\s*Stat(?:utes)?\.?)\s*(?P<chapter>\d{1,3}[A-Za-z]?)(?:\.(?P<section>\d+[A-Za-z]?))?\b",
        re.IGNORECASE,
    )
    _ORS_SECTION_RE = re.compile(
        r"\b(?P<chapter>\d{1,3}[A-Za-z]?)\."
        r"(?P<section>\d{3,4}[A-Za-z]?)\b"
    )
    _ORS_MIRROR_CHAPTER_RE = re.compile(
        r"(?:ors|or-rev-st(?:-sect)?|chapter)[-_ /]?(?P<chapter>\d{1,3}[A-Za-z]?)",
        re.IGNORECASE,
    )
    _ORS_CHAPTER_LABEL_RE = re.compile(
        r"\b(?:chapter|ch\.?)\s*(?P<chapter>\d{1,3}[A-Za-z]?)\b",
        re.IGNORECASE,
    )
    _ORS_VOLUME_RE = re.compile(r"\bVolume\s+(?P<volume>\d{1,2})\b", re.IGNORECASE)
    OFFICIAL_VOLUMES = (
        ("1", "Courts; Oregon Rules of Civil Procedure", "1"),
        ("2", "Business Organizations; Commercial Code", "56"),
        ("3", "Landlord and Tenant; Domestic Relations; Probate", "90"),
        ("4", "Criminal Procedure; Crimes", "131"),
        ("5", "State Government; Public Officers", "171"),
        ("6", "Local Government", "201"),
        ("7", "Public Facilities; Planning; Finance", "271"),
        ("8", "Revenue and Taxation", "305"),
        ("9", "Education and Culture", "326"),
        ("10", "Highways; Military Affairs; Emergency Services", "366"),
        ("11", "Human Services", "406"),
        ("12", "Public Health; Housing; Environment", "431"),
        ("13", "Wildlife; Forestry; Water", "496"),
        ("14", "Agriculture; Food; Animals", "561"),
        ("15", "Trade Regulations; Labor", "646"),
        ("16", "Occupations and Professions", "670"),
        ("17", "Financial Institutions; Insurance", "705"),
        ("18", "Public Utilities; Maritime", "756"),
        ("19", "Vehicle Code; Aeronautics; Watercraft", "801"),
    )
    OFFICIAL_VOLUME_COUNT = 19
    DEFAULT_NONOFFICIAL_SEED_ROWS = (
        {
            "statute_id": "ORS 161.205",
            "section_number": "161.205",
            "source_url": "https://law.justia.com/codes/oregon/ors-161-205.html",
            "text": "Use of physical force generally",
        },
        {
            "statute_id": "Oregon Revised Statutes 163.005",
            "source_url": "https://codes.findlaw.com/or/title-16-crimes-and-punishments/or-rev-st-sect-163-005.html",
            "text": "Criminal homicide",
        },
        {
            "name": "Unlabeled Oregon bucket remnant",
            "source_url": "",
            "text": "legacy snapshot row with no citation",
        },
    )

    def get_base_url(self) -> str:
        """Return the base URL for Oregon's legislative website."""
        return "https://www.oregonlegislature.gov"

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind strict closure to both official SharePoint parser modules."""

        from . import oregon_chapter, oregon_session_laws

        return (oregon_chapter, oregon_session_laws)

    def _is_source_bound_operative_statute_record(
        self,
        statute: NormalizedStatute,
    ) -> bool:
        """Protect exactly retained Oregon rows from generic nav heuristics.

        Valid ORS prose frequently contains generic navigation words such as
        ``court``, ``report`` and ``governor``.  The shared quality heuristic
        cannot distinguish those provisions from page chrome by vocabulary
        alone, so require the complete strict-frontier binding before treating
        an otherwise nav-like row as operative.
        """

        if not isinstance(statute, NormalizedStatute):
            return False
        closure = getattr(self, "_last_oregon_strict_closure", None)
        if not isinstance(closure, Mapping) or closure.get("closed") is not True:
            return False
        structured = dict(statute.structured_data or {})
        if structured.get("skip_hydrate") is not True:
            return False
        content_sha256 = str(structured.get("content_sha256") or "").strip()
        receipt_sha256 = str(
            structured.get("parser_input_receipt_sha256") or ""
        ).strip()
        if (
            re.fullmatch(r"[a-f0-9]{64}", content_sha256) is None
            or re.fullmatch(r"[a-f0-9]{64}", receipt_sha256) is None
            or not self._host_is_official(str(statute.source_url or ""))
        ):
            return False

        source_kind = str(structured.get("source_kind") or "").strip()
        section_number = str(statute.section_number or "").strip()
        if source_kind == "official_oregon_revised_statutes_html":
            chapter_url = str(structured.get("chapter_url") or "").strip()
            return bool(
                section_number
                and str(statute.statute_id or "").strip().casefold()
                == f"ors {section_number}".casefold()
                and structured.get("discovery_method")
                == "official_ors_sharepoint_title_inventory"
                and self._host_is_official(chapter_url)
                and str(statute.source_url or "").split("#", 1)[0]
                == chapter_url
            )

        if source_kind == "official_oregon_session_law_pdf":
            locator = structured.get("official_locator")
            parity = structured.get("currentness_parity")
            canonical_url = (
                str(locator.get("canonical_url") or "").strip()
                if isinstance(locator, Mapping)
                else ""
            )
            return bool(
                section_number
                and str(statute.statute_id or "").startswith("Or. Laws ")
                and str(statute.official_cite or "") == str(statute.statute_id or "")
                and structured.get("source_authority_class") == "official"
                and structured.get("document_kind") == "session_law"
                and structured.get("discovery_method")
                == "official_oregon_laws_sharepoint_inventory"
                and isinstance(parity, Mapping)
                and parity.get("closed") is True
                and self._host_is_official(canonical_url)
                and str(statute.source_url or "").split("#", 1)[0]
                == canonical_url
            )
        return False

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Oregon."""
        revised_statutes = {
            "name": "Oregon Revised Statutes",
            "url": self.OFFICIAL_ENTRY_URL,
            "type": "Code",
        }
        if self._full_corpus_enabled():
            # Court rules and administrative rules have dedicated corpora.  A
            # production state-laws crawl must not silently duplicate them in
            # the ORS artifact, and must begin at the edition index rather
            # than treating Chapter 1 as though it were the full frontier.
            return [revised_statutes]
        return [
            revised_statutes,
            {
                "name": "Oregon Rules of Civil Procedure",
                "url": ORCP_PRIMARY_URL,
                "type": "CourtRule",
            },
            {
                "name": "Oregon Rules of Criminal Procedure",
                "url": f"{self.get_base_url()}/bills_laws/ors/ors131.html",
                "type": "CourtRule",
            },
            {
                "name": "Oregon Local Court Rules",
                "url": LOCAL_RULES_INDEX_URL,
                "type": "CourtRule",
            },
            {
                "name": "Oregon Administrative Rules",
                "url": OregonAdministrativeRulesScraper.seed_chapter_url(),
                "type": "Regulation",
            },
        ]

    async def _fetch_rule_page_html_with_direct_fallback(
        self,
        url: str,
        *,
        expected_terms: Sequence[str],
        timeout_seconds: int = 90,
    ) -> str:
        payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout_seconds)
        html = payload.decode("utf-8", errors="replace") if payload else ""
        lowered_html = html.lower()
        normalized_terms = [str(term or "").strip().lower() for term in expected_terms if str(term or "").strip()]
        if lowered_html and all(term in lowered_html for term in normalized_terms):
            return html

        def _has_expected_terms(raw: bytes) -> bool:
            direct_lowered = raw.decode("utf-8", errors="replace").lower()
            return bool(direct_lowered) and all(
                term in direct_lowered for term in normalized_terms
            )

        direct_payload = await self._fetch_parser_input_with_transport(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout_seconds=timeout_seconds,
            content_validator=_has_expected_terms,
            # The shared archival chain already ran immediately above; this
            # is the historical bounded direct retry.
            allow_archival_fallback=False,
            media_type="text/html",
            provider="direct",
        )
        if not direct_payload:
            return html
        return direct_payload.decode("utf-8", errors="replace")

    async def _discover_other_rules_entries(self, title_terms: Sequence[str]) -> List[Dict[str, str]]:
        if not title_terms:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(COURT_RULES_LIST_API_URL, timeout_seconds=45)
        if not payload:
            return []

        try:
            decoded = json.loads(payload.decode("utf-8", errors="replace"))
            rows = decoded.get("value") or []
        except Exception:
            return []

        lowered_terms = [_norm_space(term).lower() for term in title_terms if _norm_space(term)]
        out: List[Dict[str, str]] = []
        for row in rows:
            title = _norm_space(str((row or {}).get("Title") or ""))
            url = _norm_space(str((row or {}).get("EncodedAbsUrl") or ""))
            if not title or not url:
                continue
            title_lower = title.lower()
            if any(term in title_lower for term in lowered_terms):
                out.append({"title": title, "url": url})

        deduped: List[Dict[str, str]] = []
        seen_urls = set()
        for row in out:
            key = row["url"].lower()
            if key in seen_urls:
                continue
            seen_urls.add(key)
            deduped.append(row)
        return deduped

    def _finalize_rule_statutes(
        self,
        statutes: Sequence[NormalizedStatute],
        *,
        code_name: str,
        citation_prefix: str,
        legal_area: str,
        county_name: Optional[str] = None,
    ) -> List[NormalizedStatute]:
        out: List[NormalizedStatute] = []
        seen = set()
        for statute in statutes:
            section_number = _norm_space(str(statute.section_number or ""))
            section_name = _norm_space(str(statute.section_name or statute.short_title or ""))
            key = (str(statute.source_url or "").lower(), section_number.lower(), section_name.lower())
            if key in seen:
                continue
            seen.add(key)

            statute.code_name = code_name
            statute.legal_area = legal_area
            statute.section_name = section_name or statute.section_name
            statute.short_title = section_name or statute.short_title
            statute.section_number = section_number or statute.section_number

            if county_name:
                statute.title_name = f"{county_name} County Circuit Court"
                statute.chapter_name = f"{county_name} County"
                statute.structured_data = {**(statute.structured_data or {}), "county": county_name}

            cite_number = _norm_space(str(statute.section_number or ""))
            if cite_number and cite_number.lower() != "section":
                statute.official_cite = f"{citation_prefix} {cite_number}"
            else:
                statute.official_cite = citation_prefix

            suffix = cite_number or section_name or str(len(out) + 1)
            statute.statute_id = f"{citation_prefix} {suffix}".strip()
            out.append(statute)

        return out

    def _build_rule_stub_statute(
        self,
        *,
        code_name: str,
        legal_area: str,
        citation_prefix: str,
        section_number: str,
        section_name: str,
        source_url: str,
        county_name: Optional[str] = None,
    ) -> NormalizedStatute:
        cleaned_number = _norm_space(section_number)
        cleaned_name = _norm_space(section_name) or f"{citation_prefix} {cleaned_number}"
        text = f"{citation_prefix} {cleaned_number}: {cleaned_name}".strip()
        cite = f"{citation_prefix} {cleaned_number}".strip()

        statute = NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=cite,
            code_name=code_name,
            section_number=cleaned_number,
            section_name=cleaned_name,
            short_title=cleaned_name,
            full_text=text,
            summary=cleaned_name,
            legal_area=legal_area,
            source_url=str(source_url or ""),
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={"citations": {}, "source_kind": "document_link"},
        )

        if county_name:
            statute.title_name = f"{county_name} County Circuit Court"
            statute.chapter_name = f"{county_name} County"
            statute.structured_data = {**(statute.structured_data or {}), "county": county_name}

        statute.structured_data["jsonld"] = self._build_state_jsonld(
            statute,
            text=text,
            preamble=cleaned_name,
            citations={},
            legislative_history={},
            subsections=[],
            parser_warnings=[],
        )
        return statute

    def _extract_orcp_rules_from_html(self, html: str, source_url: str, code_name: str) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        seen = set()
        for line in _lineify(html):
            match = ORCP_RULE_HEADING_RE.search(line)
            if not match:
                continue
            rule_number = _norm_space(match.group(1))
            rule_title = _norm_space(match.group(2))
            if not rule_number or not rule_title:
                continue

            key = f"{rule_number.lower()}::{rule_title.lower()}"
            if key in seen:
                continue
            seen.add(key)

            rule_url = f"{source_url}#rule-{rule_number.lower()}"
            statutes.append(
                self._build_rule_stub_statute(
                    code_name=code_name,
                    legal_area="civil_procedure",
                    citation_prefix="ORCP",
                    section_number=rule_number,
                    section_name=rule_title,
                    source_url=rule_url,
                )
            )
        return statutes

    def _extract_local_rule_documents_from_html(
        self,
        *,
        county_name: str,
        county_url: str,
        html: str,
        code_name: str,
    ) -> List[NormalizedStatute]:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return []

        statutes: List[NormalizedStatute] = []
        county_path_hint = ""
        try:
            county_path_hint = "/" + str(urlparse(county_url).path or "").strip("/").split("/Pages/")[0].lower() + "/"
        except Exception:
            county_path_hint = ""

        seen = set()
        index = 0
        for anchor in soup.find_all("a", href=True):
            href = _norm_space(str(anchor.get("href") or ""))
            text = _norm_space(anchor.get_text(" ", strip=True))
            if not href:
                continue
            absolute = urljoin(county_url, href)
            lower_abs = absolute.lower()
            lower_text = text.lower()

            if not lower_abs.startswith("https://www.courts.oregon.gov/"):
                continue
            if county_path_hint and county_path_hint not in lower_abs:
                continue

            looks_like_rule_doc = bool(LOCAL_RULE_DOC_PATH_RE.search(lower_abs) or LOCAL_RULE_TEXT_RE.search(lower_text))
            if not looks_like_rule_doc:
                continue

            label = text or Path(urlparse(absolute).path).name or "Local Rule Document"
            key = f"{lower_abs}::{label.lower()}"
            if key in seen:
                continue
            seen.add(key)
            index += 1

            statutes.append(
                self._build_rule_stub_statute(
                    code_name=code_name,
                    legal_area="court_rules",
                    citation_prefix=f"{county_name} County Local Rule",
                    section_number=f"doc-{index}",
                    section_name=label,
                    source_url=absolute,
                    county_name=county_name,
                )
            )

        return statutes

    async def _scrape_civil_procedure_rules(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        statutes: List[NormalizedStatute] = []
        primary_candidates = _dedupe_keep_order([code_url, ORCP_PRIMARY_URL, ORCP_EXPANDED_URL])
        for candidate in primary_candidates:
            payload = await self._fetch_parser_input_with_transport(
                candidate,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout_seconds=90,
                allow_archival_fallback=False,
                media_type="text/html",
                provider="direct",
            )
            html = payload.decode("utf-8", errors="replace") if payload else ""

            if not html:
                html = await self._fetch_rule_page_html_with_direct_fallback(
                    candidate,
                    expected_terms=["rules of civil procedure"],
                    timeout_seconds=90,
                )
            if html:
                extracted = self._extract_orcp_rules_from_html(html, candidate, code_name)
                if extracted:
                    statutes.extend(extracted)
        if statutes:
            return self._finalize_rule_statutes(
                statutes,
                code_name=code_name,
                citation_prefix="ORCP",
                legal_area="civil_procedure",
            )

        candidate_urls = list(primary_candidates)
        discovered = await self._discover_other_rules_entries(["civil procedure", "orcp"])
        candidate_urls.extend(row["url"] for row in discovered)
        candidate_urls = _dedupe_keep_order(candidate_urls)

        for candidate in candidate_urls:
            parsed = await self._generic_scrape(
                code_name,
                candidate,
                "ORCP",
                max_sections=(self._effective_scrape_limit(None, default=700) or 1000000),
            )
            statutes.extend(parsed)

        if not statutes:
            statutes = await self._playwright_scrape(
                code_name,
                ORCP_PRIMARY_URL,
                "ORCP",
                wait_for_selector="a[href*='ORCP'], a[href*='orcp'], a[href*='.pdf']",
                timeout=50000,
                max_sections=(self._effective_scrape_limit(None, default=700) or 1000000),
            )

        return self._finalize_rule_statutes(
            statutes,
            code_name=code_name,
            citation_prefix="ORCP",
            legal_area="civil_procedure",
        )

    def _parse_chapter_selection(self) -> List[str]:
        raw = os.getenv("OREGON_CRIMINAL_PROCEDURE_CHAPTERS", "131-136").strip()
        if not raw:
            raw = "131-136"

        chapters: List[int] = []
        for part in raw.split(","):
            token = part.strip()
            if not token:
                continue
            if "-" in token:
                left, right = token.split("-", 1)
                try:
                    lo = int(left.strip())
                    hi = int(right.strip())
                except Exception:
                    continue
                if hi < lo:
                    lo, hi = hi, lo
                chapters.extend(range(lo, hi + 1))
                continue
            try:
                chapters.append(int(token))
            except Exception:
                continue

        if not chapters:
            chapters = list(range(131, 137))
        return [f"{value:03d}" for value in sorted(set(chapters))]

    async def _scrape_criminal_procedure_rules(self, code_name: str) -> List[NormalizedStatute]:
        # Prefer court-rules entries when available, then fall back to ORS criminal-procedure chapters.
        discovered = await self._discover_other_rules_entries(["criminal procedure", "orcrp", "rules of procedure"])
        statutes: List[NormalizedStatute] = []

        for row in discovered:
            parsed = await self._generic_scrape(
                code_name,
                row["url"],
                "ORCrP",
                max_sections=(self._effective_scrape_limit(None, default=500) or 1000000),
            )
            statutes.extend(parsed)

        if not statutes:
            for chapter in self._parse_chapter_selection():
                chapter_url = f"{self.get_base_url()}/bills_laws/ors/ors{chapter}.html"
                chapter_bytes = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=90)
                if not chapter_bytes:
                    continue
                chapter_html = chapter_bytes.decode("utf-8", errors="replace")
                statutes.extend(
                    self._parse_chapter_html(
                        html=chapter_html,
                        chapter_url=chapter_url,
                        code_name=code_name,
                        citation_format="ORCrP",
                        legal_area="criminal_procedure",
                    )
                )

        return self._finalize_rule_statutes(
            statutes,
            code_name=code_name,
            citation_prefix="ORCrP",
            legal_area="criminal_procedure",
        )

    async def _discover_local_court_rule_targets(self, index_url: str) -> List[Tuple[str, str]]:
        if not REQUESTS_AVAILABLE:
            return []

        payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=60)
        if not payload:
            return []

        try:
            soup = BeautifulSoup(payload, "html.parser")
        except Exception:
            return []

        targets: List[Tuple[str, str]] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if not LOCAL_RULE_LINK_RE.search(href):
                continue
            county_name = _norm_space(anchor.get_text(" ", strip=True))
            if not county_name:
                continue
            targets.append((county_name, urljoin(index_url, href)))

        # Optional county allow-list for faster focused runs.
        counties_raw = os.getenv("OREGON_LOCAL_RULE_COUNTIES", "").strip()
        if counties_raw:
            allowed = {part.strip().lower() for part in counties_raw.split(",") if part.strip()}
            targets = [row for row in targets if row[0].lower() in allowed]

        max_counties_raw = os.getenv("OREGON_LOCAL_RULE_MAX_COUNTIES", "").strip()
        if max_counties_raw:
            try:
                max_counties = max(1, int(max_counties_raw))
                targets = targets[:max_counties]
            except Exception:
                pass

        deduped: List[Tuple[str, str]] = []
        seen = set()
        for county_name, county_url in targets:
            key = county_url.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append((county_name, county_url))
        return deduped

    async def _scrape_local_court_rules(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        targets = await self._discover_local_court_rule_targets(code_url)
        statutes: List[NormalizedStatute] = []

        for county_name, county_url in targets:
            county_code_name = f"{code_name} ({county_name} County)"
            parsed = await self._generic_scrape(
                county_code_name,
                county_url,
                "OR Local Rule",
                max_sections=(self._effective_scrape_limit(None, default=240) or 1000000),
            )
            page_bytes = await self._fetch_page_content_with_archival_fallback(county_url, timeout_seconds=90)
            if page_bytes:
                county_html = page_bytes.decode("utf-8", errors="replace")
                parsed.extend(
                    self._extract_local_rule_documents_from_html(
                        county_name=county_name,
                        county_url=county_url,
                        html=county_html,
                        code_name=code_name,
                    )
                )
            statutes.extend(
                self._finalize_rule_statutes(
                    parsed,
                    code_name=code_name,
                    citation_prefix=f"{county_name} County Local Rule",
                    legal_area="court_rules",
                    county_name=county_name,
                )
            )

        if statutes:
            return statutes

        fallback = await self._playwright_scrape(
            code_name,
            code_url,
            "OR Local Rule",
            wait_for_selector="a[href*='/courts/'][href*='rules']",
            timeout=50000,
            max_sections=(self._effective_scrape_limit(None, default=500) or 1000000),
        )
        return self._finalize_rule_statutes(
            fallback,
            code_name=code_name,
            citation_prefix="OR Local Rule",
            legal_area="court_rules",
        )

    async def _discover_chapter_urls(self, seed_url: str) -> List[str]:
        try:
            seed_bytes = await self._fetch_page_content_with_archival_fallback(seed_url, timeout_seconds=60)
            if not seed_bytes:
                self.logger.warning(f"Oregon seed request failed (no content): {seed_url}")
                return [seed_url]
            soup = BeautifulSoup(seed_bytes, "html.parser")
        except Exception as exc:
            self.logger.warning(f"Oregon chapter discovery failed: {exc}")
            return [seed_url]

        chapter_urls: List[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            absolute = urljoin(seed_url, href)
            if ORS_LINK_RE.search(absolute):
                chapter_urls.append(absolute)

        chapter_urls = _dedupe_keep_order(chapter_urls)
        if seed_url not in chapter_urls and ORS_LINK_RE.search(seed_url):
            chapter_urls.append(seed_url)

        return sorted(chapter_urls, key=lambda url: _chapter_sort_key(_chapter_slug_from_url(url) or ""))

    def _parse_chapter_html(
        self,
        *,
        html: str,
        chapter_url: str,
        code_name: str,
        citation_format: str,
        legal_area: str,
        legal_as_of: Optional[Union[str, date, datetime]] = None,
        conditional_outcomes: Optional[
            Mapping[str, Mapping[str, Any]]
        ] = None,
    ) -> List[NormalizedStatute]:
        self._last_oregon_terminal_sections = []
        self._last_oregon_lifecycle_exclusions = []
        self._last_oregon_unclassified_sections = []
        self._last_oregon_duplicate_section_identities = []
        self._last_oregon_toc_section_identities = []
        self._last_oregon_section_occurrence_count = 0
        lines = _lineify(html)
        if not lines:
            return []

        chapter_slug = _chapter_slug_from_url(chapter_url)
        if not chapter_slug:
            return []

        chapter_display = _chapter_number_display(chapter_slug)
        chapter_title = _extract_chapter_title(lines, chapter_display)
        year_value = _extract_edition_year(lines)
        start_re = _section_start_regex(chapter_display)

        sections_raw: List[Dict[str, Any]] = []
        terminal_sections: List[Dict[str, Any]] = []
        lifecycle_exclusions: List[Dict[str, Any]] = []
        unclassified_sections: List[Dict[str, Any]] = []
        section_identity_counts: Dict[str, int] = {}
        toc_section_identities: List[str] = []
        current_id: Optional[str] = None
        current_printed_id: Optional[str] = None
        current_title: str = ""
        buffer: List[str] = []
        pending_note: Optional[str] = None
        current_variant_note: Optional[str] = None
        occurrence_index = 0

        def _terminal_disposition(title: str, body: str) -> Optional[str]:
            normalized_title = _norm_space(title)
            normalized_body = _norm_space(body)
            # Terminal headings state their disposition at the beginning.
            # A lifecycle word inside an ordinary substantive heading (for
            # example, "security interests in transferred collateral") is
            # not a terminal notice.
            title_match = ORS_TERMINAL_DISPOSITION_RE.match(normalized_title)
            title_is_terminal_notice = (
                title_match is not None and not normalized_body
            )
            body_is_terminal_notice = (
                normalized_body.startswith("[")
                and normalized_body.endswith("]")
                and ORS_TERMINAL_DISPOSITION_RE.search(normalized_body) is not None
            )
            historical_number_notice = (
                re.fullmatch(
                    r"\((?:Original|Reassigned)\)\s+\[.*\brenumbered\b.*\]",
                    normalized_body,
                    re.IGNORECASE,
                )
                is not None
            )
            chapter_is_former = "former provision" in chapter_title.lower()
            if (
                not title_is_terminal_notice
                and not body_is_terminal_notice
                and not historical_number_notice
                and not chapter_is_former
            ):
                return None
            disposition_text = " ".join(
                (normalized_title, normalized_body, chapter_title)
            ).lower()
            for disposition in (
                "renumbered",
                "repealed",
                "reserved",
                "expired",
                "transferred",
            ):
                if disposition in disposition_text:
                    return disposition
            return "former_provisions"

        def flush() -> None:
            nonlocal current_id, current_printed_id, current_title, buffer
            nonlocal current_variant_note
            nonlocal occurrence_index
            if not current_id:
                return

            occurrence_index += 1
            full_text = _norm_space("\n".join(buffer))
            disposition = _terminal_disposition(current_title, full_text)
            if disposition is not None:
                section_number = current_id.lower()
                terminal_sections.append(
                    {
                        "section_number": section_number,
                        "disposition": disposition,
                        "source_url": f"{chapter_url}#section-{section_number}",
                        "source_text": _norm_space(
                            " ".join((current_title, full_text))
                        ),
                        "_occurrence_index": occurrence_index,
                        "_printed_section_number": current_printed_id,
                        "_variant_note": current_variant_note,
                    }
                )
                current_id = None
                current_printed_id = None
                current_title = ""
                buffer = []
                current_variant_note = None
                return
            parsed_history = self._extract_legislative_history(full_text)
            clean_text = self._normalize_legal_text(str(parsed_history.get("cleaned_text") or full_text))
            if not clean_text:
                section_number = current_id.lower()
                unclassified_sections.append(
                    {
                        "section_number": section_number,
                        "source_url": f"{chapter_url}#section-{section_number}",
                        "source_text": _norm_space(
                            " ".join((current_title, full_text))
                        ),
                        "_occurrence_index": occurrence_index,
                        "_printed_section_number": current_printed_id,
                        "_variant_note": current_variant_note,
                    }
                )
                current_id = None
                current_printed_id = None
                current_title = ""
                buffer = []
                current_variant_note = None
                return
            preamble = self._extract_preamble(clean_text, max_chars=600)
            subsections = self._parse_subsections(clean_text)
            parser_warnings = self._validate_subsection_tree(subsections)
            citations = self._extract_citations_from_text(
                full_text,
                clean_text,
                extra_patterns={
                    "ors_citations": ORS_CITATION_RE,
                    "session_laws": OR_LAWS_CITATION_RE,
                    "usc_citations": USC_CITATION_RE,
                    "section_references": SECTION_REF_RE,
                },
            )

            section_number = current_id.lower()
            section_name = _norm_space(current_title) or f"ORS {section_number}"

            section_row = {
                "chapter_number": chapter_display,
                "chapter_title": chapter_title,
                "section_number": section_number,
                "section_name": section_name,
                "text": clean_text,
                "preamble": preamble,
                "citations": citations,
                "legislative_history": {
                    "enactment_citation_blocks": parsed_history.get("history_citation_blocks", []),
                    "history_citations": parsed_history.get("history_citations", []),
                },
                "subsections": subsections,
                "parser_warnings": parser_warnings,
                "year": year_value,
                "source_url": f"{chapter_url}#section-{section_number}",
                "_occurrence_index": occurrence_index,
                "_printed_section_number": current_printed_id,
                "_variant_note": current_variant_note,
            }
            sections_raw.append(section_row)

            current_id = None
            current_printed_id = None
            current_title = ""
            buffer = []
            current_variant_note = None

        # The first portion of each official Word-exported chapter is a table
        # of contents whose entries look exactly like section headings.  The
        # operative headings are distinguished in the source DOM by a bold
        # element at the start of a paragraph.  Parsing those blocks avoids
        # admitting TOC snippets as statutory text while preserving every
        # following paragraph until the next operative/terminal section.
        soup = BeautifulSoup(html, "html.parser")
        body_started = False
        paragraphs = list(soup.find_all("p"))
        consumed_split_continuations: set[int] = set()
        for paragraph_index, paragraph in enumerate(paragraphs):
            if paragraph_index in consumed_split_continuations:
                continue
            heading = paragraph.find(["b", "strong"])
            heading_text = _norm_space(
                heading.get_text(" ", strip=True) if heading is not None else ""
            )
            match = start_re.match(heading_text)
            split_continuation = None
            split_continuation_heading = None
            split_continuation_index: Optional[int] = None
            paragraph_text = _norm_space(paragraph.get_text(" ", strip=True))
            if match is None:
                plain_match = start_re.match(paragraph_text)
                plain_identity = (
                    plain_match.group(1).casefold()
                    if plain_match is not None
                    else ""
                )
                # A few official Word exports wrap a long substantive heading
                # across adjacent paragraphs: the identity and first title
                # line are plain text, while the continuation alone is bold.
                # The same identity must already have appeared in the TOC, so
                # a statutory citation at the start of body prose cannot open
                # a synthetic section.
                if plain_identity and plain_identity in toc_section_identities:
                    for candidate_index in range(
                        paragraph_index + 1,
                        len(paragraphs),
                    ):
                        candidate = paragraphs[candidate_index]
                        candidate_text = _norm_space(
                            candidate.get_text(" ", strip=True)
                        )
                        if not candidate_text:
                            continue
                        candidate_heading = candidate.find(["b", "strong"])
                        candidate_heading_text = _norm_space(
                            candidate_heading.get_text(" ", strip=True)
                            if candidate_heading is not None
                            else ""
                        )
                        combined_match = start_re.match(
                            _norm_space(
                                f"{paragraph_text} {candidate_heading_text}"
                            )
                        )
                        if (
                            candidate_heading is not None
                            and start_re.match(candidate_heading_text) is None
                            and combined_match is not None
                            and combined_match.group(1).casefold()
                            == plain_identity
                        ):
                            match = combined_match
                            split_continuation = candidate
                            split_continuation_heading = candidate_heading
                            split_continuation_index = candidate_index
                        break
            if match is not None:
                body_started = True
                next_identity = match.group(1).casefold()
                canonical_identity = next_identity
                variant_note: Optional[str] = None
                if pending_note is not None and current_id is not None:
                    if current_id.casefold() == next_identity:
                        variant_note = pending_note
                    else:
                        mismatched_interval = _ors_variant_interval(
                            note=pending_note,
                            section_number=current_id.casefold(),
                            conditional_outcomes=conditional_outcomes,
                        )
                        known_printed_identity_mismatch = (
                            current_id.casefold() == "279c.800"
                            and next_identity == "279c.805"
                            and not _norm_space(match.group(2) or "").strip(
                                " .:;-\u2013\u2014"
                            )
                        )
                        if (
                            mismatched_interval is not None
                            and known_printed_identity_mismatch
                        ):
                            # The 2025 ORS Chapter 279C export labels the
                            # pre-July-2026 convenience text for 279C.800 as
                            # 279C.805.  The immediately preceding Note names
                            # the authoritative identity and exact interval;
                            # retain the printed mismatch as evidence instead
                            # of losing 279C.800 or duplicating 279C.805.
                            variant_note = pending_note
                            canonical_identity = current_id.casefold()
                        else:
                            buffer.append(pending_note)
                    pending_note = None
                flush()
                current_id = canonical_identity
                current_printed_id = next_identity
                identity_key = current_id.casefold()
                section_identity_counts[identity_key] = (
                    section_identity_counts.get(identity_key, 0) + 1
                )
                current_title = match.group(2) or ""
                current_variant_note = variant_note
                initial_body_parts: List[str] = []
                body_paragraph = split_continuation or paragraph
                body_heading = (
                    split_continuation_heading
                    if split_continuation is not None
                    else heading
                )
                for node in body_paragraph.find_all(string=True):
                    if body_heading is not None and body_heading in node.parents:
                        continue
                    value = _norm_space(str(node))
                    if value:
                        initial_body_parts.append(value)
                buffer = initial_body_parts
                if split_continuation_index is not None:
                    consumed_split_continuations.add(split_continuation_index)
                continue
            if not body_started:
                toc_match = start_re.match(paragraph_text)
                if toc_match is not None:
                    toc_section_identities.append(toc_match.group(1).casefold())
                    continue
            if current_id:
                if paragraph_text and ORS_VARIANT_NOTE_RE.match(paragraph_text):
                    if pending_note is not None:
                        buffer.append(pending_note)
                    pending_note = paragraph_text
                    continue
                if paragraph_text and not re.fullmatch(r"[_\-]{5,}", paragraph_text):
                    if pending_note is not None:
                        buffer.append(pending_note)
                        pending_note = None
                    buffer.append(paragraph_text)

        if pending_note is not None and current_id is not None:
            buffer.append(pending_note)
            pending_note = None
        flush()

        # A small, closed set of official "Former Provisions" chapters prints
        # every repealed/expired identity in one collective Note and has no
        # per-section headings.  Treat each source-listed identity as a typed
        # terminal occurrence; otherwise these pages look falsely empty and
        # hundreds of historical section identities disappear from the exact
        # frontier algebra.
        if occurrence_index == 0 and "former provision" in chapter_title.casefold():
            note_start = next(
                (
                    index
                    for index, line in enumerate(lines)
                    if ORS_VARIANT_NOTE_RE.match(line)
                ),
                None,
            )
            collective_note = (
                _norm_space(" ".join(lines[note_start:]))
                if note_start is not None
                else ""
            )
            lowered_collective_note = collective_note.casefold()
            collective_terminal = bool(
                re.search(
                    r"\b(?:repealed by|expired and stood repealed|"
                    r"were in effect until)\b",
                    lowered_collective_note,
                )
            )
            collective_identities = _dedupe_keep_order(
                re.findall(
                    rf"\b{re.escape(chapter_display)}\.\d{{3,4}}[a-z]?\b",
                    collective_note,
                    flags=re.IGNORECASE,
                )
            )
            if collective_terminal and collective_identities:
                disposition = (
                    "expired"
                    if "expired and stood repealed" in lowered_collective_note
                    or "were in effect until" in lowered_collective_note
                    else "repealed"
                )
                for printed_identity in collective_identities:
                    occurrence_index += 1
                    section_number = printed_identity.casefold()
                    section_identity_counts[section_number] = 1
                    terminal_sections.append(
                        {
                            "section_number": section_number,
                            "disposition": disposition,
                            "source_url": (
                                f"{chapter_url}#section-{section_number}"
                            ),
                            "source_text": collective_note,
                            "_occurrence_index": occurrence_index,
                            "_printed_section_number": section_number,
                            "_variant_note": None,
                        }
                    )
        as_of_date = _coerce_ors_as_of(legal_as_of)
        resolved_duplicate_identities: set[str] = set()

        occurrences_by_identity: Dict[
            str, List[Tuple[str, Dict[str, Any]]]
        ] = {}
        for kind, rows in (
            ("operative", sections_raw),
            ("terminal", terminal_sections),
            ("unclassified", unclassified_sections),
        ):
            for row in rows:
                identity = str(row.get("section_number") or "").casefold()
                occurrences_by_identity.setdefault(identity, []).append((kind, row))
        for occurrences in occurrences_by_identity.values():
            occurrences.sort(key=lambda item: int(item[1]["_occurrence_index"]))

        for section_id, count in section_identity_counts.items():
            if count <= 1 or as_of_date is None:
                continue
            occurrences = occurrences_by_identity.get(section_id, [])
            if len(occurrences) != count or not occurrences:
                continue
            if occurrences[0][1].get("_variant_note"):
                continue

            alternate_intervals: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
            for kind, row in occurrences[1:]:
                note = str(row.get("_variant_note") or "")
                interval = _ors_variant_interval(
                    note=note,
                    section_number=section_id,
                    conditional_outcomes=conditional_outcomes,
                )
                if interval is None:
                    alternate_intervals = []
                    break
                alternate_intervals.append((kind, row, interval))
            if len(alternate_intervals) != len(occurrences) - 1:
                historical_labels = [
                    str(row.get("source_text") or "").casefold()
                    for _kind, row in occurrences
                ]
                historical_reused_number = (
                    len(occurrences) == 2
                    and all(kind == "terminal" for kind, _row in occurrences)
                    and all(
                        str(row.get("disposition") or "") == "renumbered"
                        for _kind, row in occurrences
                    )
                    and "(original)" in historical_labels[0]
                    and "(reassigned)" in historical_labels[1]
                )
                if not historical_reused_number:
                    continue
                alternate_intervals = [
                    (
                        occurrences[1][0],
                        occurrences[1][1],
                        {
                            "effective_start": None,
                            "effective_end": None,
                            "interval_kind": "historical_reused_number",
                            "forced_inactive": True,
                        },
                    )
                ]

            active_alternates = [
                (kind, row, interval)
                for kind, row, interval in alternate_intervals
                if not bool(interval.get("forced_inactive"))
                and (
                    interval["effective_start"] is None
                    or interval["effective_start"] <= as_of_date
                )
                and (
                    interval["effective_end"] is None
                    or as_of_date < interval["effective_end"]
                )
            ]
            if len(active_alternates) > 1:
                continue

            selected_kind, selected_row = (
                (active_alternates[0][0], active_alternates[0][1])
                if active_alternates
                else occurrences[0]
            )
            excluded_rows: List[Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]] = []
            for kind, row in occurrences:
                if row is selected_row:
                    continue
                interval = next(
                    (
                        candidate_interval
                        for _candidate_kind, candidate_row, candidate_interval
                        in alternate_intervals
                        if candidate_row is row
                    ),
                    None,
                )
                excluded_rows.append((kind, row, interval))

            selected_variants: List[Dict[str, Any]] = []
            for kind, row, interval in excluded_rows:
                text_value = str(
                    row.get("text")
                    if kind == "operative"
                    else row.get("source_text")
                    or ""
                )
                effective_start = (
                    interval.get("effective_start") if interval is not None else None
                )
                effective_end = (
                    interval.get("effective_end") if interval is not None else None
                )
                if effective_start is not None and as_of_date < effective_start:
                    exclusion_disposition = "future_effective_variant"
                elif effective_end is not None and as_of_date >= effective_end:
                    exclusion_disposition = "superseded_variant"
                elif interval is not None and bool(
                    interval.get("forced_inactive")
                ):
                    forced_interval_kind = interval.get("interval_kind")
                    if forced_interval_kind == "historical_reused_number":
                        exclusion_disposition = (
                            "historical_reused_number_variant"
                        )
                    elif forced_interval_kind == "conditional_event_not_met":
                        exclusion_disposition = "inactive_conditional_variant"
                    else:
                        exclusion_disposition = "source_labelled_prior_variant"
                elif interval is None and active_alternates:
                    active_interval = active_alternates[0][2]
                    exclusion_disposition = (
                        "superseded_variant"
                        if active_interval.get("effective_start") is not None
                        else "future_effective_variant"
                    )
                else:
                    exclusion_disposition = "nonselected_dated_variant"
                exclusion = {
                    "section_number": section_id,
                    "disposition": exclusion_disposition,
                    "source_url": (
                        f"{chapter_url}#section-{section_id}-variant-"
                        f"{int(row['_occurrence_index'])}"
                    ),
                    "source_note": str(row.get("_variant_note") or ""),
                    "source_text_sha256": hashlib.sha256(
                        text_value.encode("utf-8")
                    ).hexdigest(),
                    "source_text_byte_size": len(text_value.encode("utf-8")),
                    "source_occurrence_kind": kind,
                    "source_occurrence_index": int(row["_occurrence_index"]),
                    "printed_section_number": str(
                        row.get("_printed_section_number") or section_id
                    ).casefold(),
                    "effective_start": (
                        effective_start.isoformat()
                        if isinstance(effective_start, date)
                        else None
                    ),
                    "effective_end": (
                        effective_end.isoformat()
                        if isinstance(effective_end, date)
                        else None
                    ),
                    "interval_kind": (
                        str(interval.get("interval_kind") or "")
                        if interval is not None
                        else "edition_default"
                    ),
                    "legal_as_of": as_of_date.isoformat(),
                }
                event_context_interval = interval
                if event_context_interval is None and active_alternates:
                    event_context_interval = active_alternates[0][2]
                if event_context_interval is not None:
                    for event_field in (
                        "event_key",
                        "event_status",
                        "event_observed_at",
                        "event_date",
                        "operative_date",
                        "selector_evidence_sha256",
                        "selector_receipt_sha256",
                        "selector_source_urls",
                        "selector_decision_sha256",
                        "selector_conclusion",
                        "selector_context",
                    ):
                        if event_field in event_context_interval:
                            exclusion[event_field] = event_context_interval[
                                event_field
                            ]
                lifecycle_exclusions.append(exclusion)
                selected_variants.append(
                    {
                        key: exclusion[key]
                        for key in (
                            "disposition",
                            "effective_start",
                            "effective_end",
                            "interval_kind",
                            "source_note",
                            "source_occurrence_index",
                            "source_text_sha256",
                            "event_key",
                            "event_status",
                            "event_observed_at",
                            "event_date",
                            "operative_date",
                            "selector_evidence_sha256",
                            "selector_receipt_sha256",
                            "selector_source_urls",
                            "selector_decision_sha256",
                            "selector_conclusion",
                            "selector_context",
                        )
                        if key in exclusion
                    }
                )
                if kind == "operative":
                    sections_raw.remove(row)
                elif kind == "terminal":
                    terminal_sections.remove(row)
                else:
                    unclassified_sections.remove(row)

            selected_row["_lifecycle_variants"] = selected_variants
            selected_row["_selected_legal_as_of"] = as_of_date.isoformat()
            selected_row["_selected_occurrence_kind"] = selected_kind
            resolved_duplicate_identities.add(section_id)

        for rows in (sections_raw, terminal_sections, unclassified_sections):
            for row in rows:
                row.pop("_occurrence_index", None)
                row.pop("_printed_section_number", None)
                row.pop("_variant_note", None)
                if "_lifecycle_variants" in row:
                    row["lifecycle_variants"] = row.pop("_lifecycle_variants")
                    row["selected_legal_as_of"] = row.pop(
                        "_selected_legal_as_of"
                    )
                    row["selected_occurrence_kind"] = row.pop(
                        "_selected_occurrence_kind"
                    )
        self._last_oregon_terminal_sections = terminal_sections
        self._last_oregon_lifecycle_exclusions = lifecycle_exclusions
        self._last_oregon_unclassified_sections = unclassified_sections
        self._last_oregon_duplicate_section_identities = sorted(
            section_id
            for section_id, count in section_identity_counts.items()
            if count > 1 and section_id not in resolved_duplicate_identities
        )
        self._last_oregon_toc_section_identities = toc_section_identities
        self._last_oregon_section_occurrence_count = occurrence_index

        by_section_id: Dict[str, Dict[str, Any]] = {}
        for row in sections_raw:
            sec_id = str(row.get("section_number") or "")
            prev = by_section_id.get(sec_id)
            if prev is None or len(str(row.get("text") or "")) > len(str(prev.get("text") or "")):
                by_section_id[sec_id] = row

        statutes: List[NormalizedStatute] = []
        for section_id in sorted(by_section_id.keys(), key=_section_sort_key):
            row = by_section_id[section_id]
            history_citations = row.get("legislative_history", {}).get("history_citations") or []
            metadata = StatuteMetadata(
                enacted_year=str(row.get("year")) if row.get("year") is not None else None,
                history=[str(item) for item in row.get("legislative_history", {}).get("enactment_citation_blocks") or []],
            )

            structured_data = {
                "preamble": row.get("preamble"),
                "citations": row.get("citations"),
                "legislative_history": row.get("legislative_history"),
                "subsections": row.get("subsections"),
                "parser_warnings": row.get("parser_warnings"),
                "history_citations": history_citations,
                "lifecycle_variants": row.get("lifecycle_variants") or [],
                "selected_legal_as_of": row.get("selected_legal_as_of"),
                "selected_occurrence_kind": row.get(
                    "selected_occurrence_kind"
                ),
                "source_kind": "official_oregon_revised_statutes_html",
                "discovery_method": "official_ors_chapter_html",
                "skip_hydrate": True,
            }
            statute = NormalizedStatute(
                state_code=self.state_code,
                state_name=self.state_name,
                statute_id=f"ORS {section_id}",
                code_name=code_name,
                title_number=chapter_display,
                title_name=chapter_title or f"ORS Chapter {chapter_display}",
                chapter_number=chapter_display,
                chapter_name=chapter_title or None,
                section_number=section_id,
                section_name=str(row.get("section_name") or ""),
                short_title=str(row.get("section_name") or ""),
                full_text=str(row.get("text") or ""),
                summary=str(row.get("preamble") or ""),
                legal_area=legal_area,
                keywords=_dedupe_keep_order(
                    [
                        *(row.get("citations", {}).get("ors_citations") or []),
                        *(row.get("citations", {}).get("section_references") or []),
                    ]
                )[:200],
                source_url=str(row.get("source_url") or chapter_url),
                official_cite=f"{citation_format} § {section_id}",
                metadata=metadata,
                structured_data=structured_data,
            )
            statute.structured_data["jsonld"] = self._build_state_jsonld(
                statute,
                text=str(row.get("text") or ""),
                preamble=str(row.get("preamble") or ""),
                citations=row.get("citations") or {},
                legislative_history=row.get("legislative_history") or {},
                subsections=row.get("subsections") or [],
                parser_warnings=row.get("parser_warnings") or [],
            )
            statutes.append(statute)

        return statutes

    @staticmethod
    def _oregon_frontier_digest(
        rows: Sequence[Tuple[str, bytes]],
    ) -> str:
        """Digest an ordered URL/parser-input frontier without joining bodies."""

        digest = hashlib.sha256()
        for official_url, payload in rows:
            digest.update(str(official_url).encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(bytes(payload)).digest())
        return digest.hexdigest()

    def _oregon_input_evidence_context(
        self,
        *,
        source_url: str,
        payload: bytes,
        transport_receipt: Optional[Dict[str, Any]],
        parser_input_envelope: Any,
    ) -> Dict[str, Any]:
        """Verify an aligned retained input when strict evidence is attached."""

        body = bytes(payload)
        content_sha256 = hashlib.sha256(body).hexdigest()
        envelope = parser_input_envelope
        if not isinstance(envelope, Mapping):
            to_dict = getattr(envelope, "to_dict", None)
            if callable(to_dict):
                envelope = to_dict()
        if isinstance(envelope, Mapping) and isinstance(
            envelope.get("parser_input_envelope"), Mapping
        ):
            envelope = envelope["parser_input_envelope"]

        acquisition = (
            envelope.get("acquisition", {})
            if isinstance(envelope, Mapping)
            else {}
        )
        receipt = (
            acquisition.get("receipt", {})
            if isinstance(acquisition, Mapping)
            else {}
        )
        ledger_attached = getattr(self, "_state_law_acquisition_ledger", None) is not None
        if not isinstance(receipt, Mapping) or not receipt:
            if ledger_attached:
                raise RuntimeError(
                    "Oregon strict parser input lacks its retained acquisition receipt: "
                    f"{source_url}"
                )
            return {
                "content_sha256": content_sha256,
                "parser_input_receipt_sha256": "",
                "source_retrieved_at": "",
                "source_transport": "",
                "source_transport_chain": [],
                "transport_receipt": {},
            }

        endpoint = str(receipt.get("endpoint") or "").strip()
        retained_sha256 = str(
            (receipt.get("content") or {}).get("sha256")
            if isinstance(receipt.get("content"), Mapping)
            else ""
        ).strip().lower()
        envelope_sha256 = str(acquisition.get("body_sha256") or "").strip().lower()
        if (
            endpoint.rstrip("/") != source_url.rstrip("/")
            or retained_sha256 != content_sha256
            or envelope_sha256 != content_sha256
        ):
            raise RuntimeError(
                "Oregon retained acquisition evidence changed parser input identity: "
                f"{source_url}"
            )

        retained_transport = (receipt.get("metadata") or {}).get(
            "transport_receipt", {}
        ) if isinstance(receipt.get("metadata"), Mapping) else {}
        if not isinstance(retained_transport, Mapping) or not retained_transport:
            raise RuntimeError(
                "Oregon retained parser input lacks transport evidence: "
                f"{source_url}"
            )
        from ...legal_data.state_laws_source_provenance import (
            StateLawTransportReceiptError,
            verify_state_law_transport_receipt,
        )

        try:
            verified = verify_state_law_transport_receipt(
                retained_transport,
                official_url=source_url,
                content_sha256=content_sha256,
            )
            if isinstance(transport_receipt, Mapping) and transport_receipt:
                aligned = verify_state_law_transport_receipt(
                    transport_receipt,
                    official_url=source_url,
                    content_sha256=content_sha256,
                )
                if aligned != verified:
                    raise StateLawTransportReceiptError(
                        "unaligned_transport_receipt",
                        "retained and aligned Oregon receipts disagree",
                    )
        except StateLawTransportReceiptError as exc:
            raise RuntimeError(
                "Oregon parser input transport identity is incomplete: "
                f"{source_url}"
            ) from exc

        receipt_sha256 = str(receipt.get("receipt_sha256") or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", receipt_sha256) is None:
            raise RuntimeError(
                "Oregon retained parser input lacks an exact receipt digest: "
                f"{source_url}"
            )
        return {
            "content_sha256": content_sha256,
            "parser_input_receipt_sha256": receipt_sha256,
            "source_retrieved_at": str(receipt.get("retrieved_at") or "").strip(),
            "source_transport": verified.leaf_transport,
            "source_transport_chain": list(verified.transport_chain),
            "transport_receipt": verified.to_dict(),
        }

    @staticmethod
    def _valid_ors_event_selector_payload(payload: bytes) -> bool:
        """Accept a complete PDF or a substantive retained text response."""

        body = bytes(payload or b"")
        if body.startswith(b"%PDF-"):
            from .oregon_session_laws import valid_full_oregon_law_pdf

            return valid_full_oregon_law_pdf(body)
        if len(body) < 100 or b"\x00" in body:
            return False
        decoded = body.decode("utf-8-sig", errors="replace").strip()
        return bool(decoded and len(_norm_space(decoded)) >= 80)

    @staticmethod
    def _ors_event_selector_search_text(payload: bytes) -> Tuple[str, str]:
        """Return normalized visible and raw text for exact selector checks."""

        body = bytes(payload or b"")
        if body.startswith(b"%PDF-"):
            from .oregon_session_laws import pdftotext_raw

            raw = pdftotext_raw(body)
            return (
                _normalize_ors_selector_text(raw),
                unicodedata.normalize("NFKC", raw).casefold(),
            )

        raw = body.decode("utf-8-sig", errors="strict")
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if parsed is not None:
            def _json_strings(value: Any) -> List[str]:
                if isinstance(value, Mapping):
                    out: List[str] = []
                    for key in sorted(value, key=lambda item: str(item)):
                        out.extend(_json_strings(value[key]))
                    return out
                if isinstance(value, Sequence) and not isinstance(
                    value,
                    (str, bytes, bytearray),
                ):
                    out = []
                    for item in value:
                        out.extend(_json_strings(item))
                    return out
                return [str(value)] if isinstance(value, str) else []

            stable = "\n".join(_json_strings(parsed))
            return (
                _normalize_ors_selector_text(stable),
                unicodedata.normalize("NFKC", raw).casefold(),
            )
        soup = BeautifulSoup(raw, "html.parser")
        visible = soup.get_text(" ", strip=True)
        return (
            _normalize_ors_selector_text(visible),
            unicodedata.normalize("NFKC", raw).casefold(),
        )

    async def _acquire_ors_conditional_event_outcomes(
        self,
        required_event_keys: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Resolve every required current-law event from one plural frontier."""

        required = sorted(
            {
                str(event_key or "").strip()
                for event_key in required_event_keys
                if str(event_key or "").strip()
            }
        )
        if not required:
            self._last_oregon_event_selector_batch_stats = {}
            return {}
        unknown = sorted(
            set(required) - set(ORS_CONDITIONAL_EVENT_SELECTOR_SPECS)
        )
        if unknown:
            raise RuntimeError(
                "Oregon conditional current-law selectors are missing: "
                f"{unknown}"
            )

        source_specs_by_url: Dict[str, List[Mapping[str, Any]]] = {}
        ordered_urls: List[str] = []
        for event_key in required:
            event_spec = ORS_CONDITIONAL_EVENT_SELECTOR_SPECS[event_key]
            raw_sources = event_spec.get("sources")
            if (
                not isinstance(raw_sources, Sequence)
                or isinstance(raw_sources, (str, bytes, bytearray))
                or not raw_sources
            ):
                raise RuntimeError(
                    "Oregon conditional selector has no official sources: "
                    f"{event_key}"
                )
            for raw_source in raw_sources:
                if not isinstance(raw_source, Mapping):
                    raise RuntimeError(
                        "Oregon conditional selector source is not a mapping: "
                        f"{event_key}"
                    )
                source_url = str(raw_source.get("url") or "").strip()
                parsed = urlparse(source_url)
                if (
                    parsed.scheme.casefold() != "https"
                    or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                ):
                    raise RuntimeError(
                        "Oregon conditional selector source is not an exact HTTPS "
                        f"locator: event={event_key} url={source_url!r}"
                    )
                if source_url not in source_specs_by_url:
                    source_specs_by_url[source_url] = []
                    ordered_urls.append(source_url)
                source_specs_by_url[source_url].append(raw_source)

        batch = await self._fetch_oregon_plural_frontier(
            ordered_urls,
            frontier_name="conditional-event-selector",
            content_validator=self._valid_ors_event_selector_payload,
            common_crawl_url_terms=None,
            common_crawl_domain_terms=None,
            accept=(
                "text/html,application/hal+json,application/json,"
                "application/pdf;q=0.9,*/*;q=0.5"
            ),
            media_type="application/octet-stream",
            common_crawl_mime_terms=("html", "text", "json", "pdf"),
        )
        retained: Dict[str, Dict[str, Any]] = {}
        for source_url, payload, receipt, envelope in zip(
            batch.urls,
            batch.payloads,
            batch.transport_receipts,
            batch.parser_input_envelopes,
            strict=True,
        ):
            evidence = self._oregon_input_evidence_context(
                source_url=source_url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            visible_text, raw_text = self._ors_event_selector_search_text(
                payload
            )
            retained[source_url] = {
                "evidence": evidence,
                "raw_text": raw_text,
                "visible_text": visible_text,
            }

        outcomes: Dict[str, Dict[str, Any]] = {}
        for event_key in required:
            event_spec = ORS_CONDITIONAL_EVENT_SELECTOR_SPECS[event_key]
            matched_by_url: Dict[str, List[str]] = {}
            evidence_digests: List[str] = []
            receipt_digests: List[str] = []
            source_urls: List[str] = []
            observed_values: List[str] = []
            for raw_source in event_spec["sources"]:
                source_url = str(raw_source["url"])
                source = retained[source_url]
                visible_text = str(source["visible_text"])
                raw_text = str(source["raw_text"])
                required_terms = [
                    _normalize_ors_selector_text(str(term))
                    for term in raw_source.get("require_all", ())
                    if _norm_space(str(term))
                ]
                any_terms = [
                    _normalize_ors_selector_text(str(term))
                    for term in raw_source.get("require_any", ())
                    if _norm_space(str(term))
                ]
                missing = [
                    term
                    for term in required_terms
                    if term not in visible_text and term not in raw_text
                ]
                if missing or (
                    any_terms
                    and not any(
                        term in visible_text or term in raw_text
                        for term in any_terms
                    )
                ):
                    raise RuntimeError(
                        "Oregon conditional selector wording changed: "
                        f"event={event_key} url={source_url} missing={missing} "
                        f"require_any_matched={not any_terms or any(term in visible_text or term in raw_text for term in any_terms)}"
                    )
                forbidden = [
                    str(term).casefold()
                    for term in raw_source.get("absent_raw_terms", ())
                    if str(term)
                ]
                present_forbidden = [
                    term for term in forbidden if term in raw_text
                ]
                if present_forbidden:
                    raise RuntimeError(
                        "Oregon conditional selector contains a forbidden current "
                        f"state: event={event_key} url={source_url} "
                        f"terms={present_forbidden}"
                    )
                forbidden_visible = [
                    _normalize_ors_selector_text(str(term))
                    for term in raw_source.get("absent_terms", ())
                    if _normalize_ors_selector_text(str(term))
                ]
                present_forbidden_visible = [
                    term
                    for term in forbidden_visible
                    if term in visible_text or term in raw_text
                ]
                if present_forbidden_visible:
                    raise RuntimeError(
                        "Oregon conditional selector contains a forbidden current "
                        f"state: event={event_key} url={source_url} "
                        f"terms={present_forbidden_visible}"
                    )
                matched_by_url[source_url] = [
                    *required_terms,
                    *(
                        [
                            next(
                                term
                                for term in any_terms
                                if term in visible_text or term in raw_text
                            )
                        ]
                        if any_terms
                        else []
                    ),
                ]
                evidence = source["evidence"]
                content_digest = str(
                    evidence.get("content_sha256") or ""
                ).strip().casefold()
                receipt_digest = str(
                    evidence.get("parser_input_receipt_sha256") or ""
                ).strip().casefold()
                if re.fullmatch(r"[0-9a-f]{64}", content_digest) is None:
                    raise RuntimeError(
                        "Oregon conditional selector lacks a content digest: "
                        f"{source_url}"
                    )
                if (
                    getattr(self, "_state_law_acquisition_ledger", None)
                    is not None
                    and re.fullmatch(r"[0-9a-f]{64}", receipt_digest) is None
                ):
                    raise RuntimeError(
                        "Oregon conditional selector lacks a receipt digest: "
                        f"{source_url}"
                    )
                evidence_digests.append(content_digest)
                if receipt_digest:
                    receipt_digests.append(receipt_digest)
                source_urls.append(source_url)
                observed = str(
                    evidence.get("source_retrieved_at") or ""
                ).strip()
                if observed:
                    observed_values.append(observed)

            status = str(event_spec.get("status") or "").strip().casefold()
            alternate_active = event_spec.get("alternate_active")
            if status not in {"occurred", "not_occurred", "unknown"} or not isinstance(
                alternate_active,
                bool,
            ):
                raise RuntimeError(
                    "Oregon conditional selector has an invalid disposition: "
                    f"{event_key}"
                )
            event_date = str(event_spec.get("event_date") or "").strip()
            operative_date = str(
                event_spec.get("operative_date") or ""
            ).strip()
            delay_days = event_spec.get("operative_delay_days")
            if delay_days is not None:
                parsed_event_date = _coerce_ors_as_of(event_date)
                if parsed_event_date is None or isinstance(delay_days, bool):
                    raise RuntimeError(
                        "Oregon conditional selector cannot derive its operative "
                        f"date: {event_key}"
                    )
                derived_operative_date = (
                    parsed_event_date + timedelta(days=int(delay_days))
                ).isoformat()
                if operative_date and operative_date != derived_operative_date:
                    raise RuntimeError(
                        "Oregon conditional selector operative date changed its "
                        f"source arithmetic: {event_key}"
                    )
                operative_date = derived_operative_date
            if alternate_active and _coerce_ors_as_of(operative_date) is None:
                raise RuntimeError(
                    "Oregon active conditional selector lacks an operative date: "
                    f"{event_key}"
                )
            outcome: Dict[str, Any] = {
                "status": status,
                "alternate_active": alternate_active,
                "event_date": event_date or None,
                "operative_date": operative_date or None,
                "observed_at": max(observed_values, default=""),
                "selector_conclusion": str(
                    event_spec.get("conclusion") or ""
                ).strip(),
                "selector_context": dict(
                    event_spec.get("context")
                    if isinstance(event_spec.get("context"), Mapping)
                    else {}
                ),
                "selector_evidence_sha256": evidence_digests,
                "selector_receipt_sha256": receipt_digests,
                "selector_source_urls": source_urls,
                "selector_term_matches": matched_by_url,
            }
            outcome["selector_decision_sha256"] = hashlib.sha256(
                json.dumps(
                    outcome,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            outcomes[event_key] = outcome

        self._last_oregon_event_selector_batch_stats = dict(batch.stats or {})
        self._last_oregon_conditional_event_outcomes = outcomes
        return outcomes

    async def _fetch_oregon_plural_frontier(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        content_validator: Any,
        common_crawl_url_terms: Optional[Sequence[str]],
        common_crawl_domain_terms: Optional[Sequence[str]] = None,
        accept: Optional[str] = (
            "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
        ),
        media_type: str = "text/html",
        common_crawl_mime_terms: Sequence[str] = ("html", "text"),
    ) -> Any:
        """Acquire one exact Oregon frontier through the grouped-WARC path."""

        requested = list(urls)
        if not requested or len(requested) != len(set(requested)):
            raise RuntimeError(
                f"Oregon {frontier_name} frontier is empty or contains duplicate URLs"
            )
        retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_OR_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=3,
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=retry_attempts,
            timeout_seconds=90,
            headers={
                **({"Accept": accept} if accept else {}),
                "User-Agent": "ipfs-datasets-oregon-statutes/2.0",
            },
            content_validator=content_validator,
            media_type=media_type,
            max_concurrency=max(
                1,
                min(
                    32,
                    self._env_int(
                        "STATE_SCRAPER_OR_FRONTIER_CONCURRENCY",
                        default=8,
                    ),
                ),
            ),
            prefer_direct=True,
            common_crawl_domain_terms=(
                tuple(common_crawl_domain_terms)
                if common_crawl_domain_terms is not None
                else None
            ),
            common_crawl_url_terms=(
                tuple(common_crawl_url_terms)
                if common_crawl_url_terms is not None
                else None
            ),
            common_crawl_mime_terms=tuple(common_crawl_mime_terms),
            wayback_prefix_inventory=True,
        )
        aligned_lengths = {
            len(batch.urls),
            len(batch.payloads),
            len(batch.errors),
            len(batch.transport_receipts),
            len(batch.parser_input_envelopes),
        }
        if aligned_lengths != {len(requested)} or list(batch.urls) != requested:
            raise RuntimeError(
                f"Oregon {frontier_name} frontier returned unaligned URL identities"
            )
        failures = [
            {"url": url, "error": error or "invalid or empty parser input"}
            for url, payload, error in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                strict=True,
            )
            if error is not None or not payload or not content_validator(bytes(payload))
        ]
        if failures:
            raise RuntimeError(
                f"Oregon {frontier_name} frontier is incomplete after residual-only "
                f"retries: {failures}"
            )
        batch.payloads = [bytes(payload) for payload in batch.payloads]
        return batch

    async def _fetch_strict_ors_catalog(self, seed_url: str) -> bytes:
        """Acquire and verify the one-row ORS catalog through the plural seam."""

        from .oregon_chapter import decode_oregon_html, ors_sharepoint_title_groups

        def _valid_catalog(payload: bytes) -> bool:
            try:
                return bool(
                    ors_sharepoint_title_groups(decode_oregon_html(payload))
                )
            except Exception:
                return False

        batch = await self._fetch_oregon_plural_frontier(
            [seed_url],
            frontier_name="catalog",
            content_validator=_valid_catalog,
            common_crawl_url_terms=("/bills_laws/pages/ors.aspx",),
            # The retained v1 catalog predates the plural seam and has the
            # canonical header-free GET identity.  Keep that request identity
            # so restarts replay its bytes rather than reacquiring them.
            accept=None,
        )
        payload = bytes(batch.payloads[0])
        self._oregon_input_evidence_context(
            source_url=seed_url,
            payload=payload,
            transport_receipt=batch.transport_receipts[0],
            parser_input_envelope=batch.parser_input_envelopes[0],
        )
        self._last_oregon_catalog_batch_stats = dict(batch.stats or {})
        return payload

    async def _scrape_strict_oregon_session_laws(
        self,
        *,
        legal_area: str,
    ) -> List[NormalizedStatute]:
        """Close the exact post-edition Oregon Laws overlay with plural fetches."""

        from .oregon_chapter import decode_oregon_html
        from .oregon_session_laws import (
            LAWS_MOBILE_URL,
            expected_oregon_law_chapter_count,
            normalized_oregon_law_sections,
            oregon_current_law_sessions,
            oregon_law_chapter_locators,
            oregon_resolution_inventory_url,
            oregon_resolution_locators,
            oregon_supplement_inventory_url,
            oregon_supplement_locators,
            parse_oregon_affected_pdf,
            parse_oregon_enacted_pdf,
            parse_oregon_law_pdf,
            reconcile_oregon_session_evidence,
            valid_full_oregon_law_pdf,
        )

        def _valid_landing(payload: bytes) -> bool:
            try:
                return len(
                    oregon_current_law_sessions(decode_oregon_html(payload))
                ) == 2
            except Exception:
                return False

        landing_batch = await self._fetch_oregon_plural_frontier(
            [LAWS_MOBILE_URL],
            frontier_name="session-law-catalog",
            content_validator=_valid_landing,
            common_crawl_url_terms=("/bills_laws/Pages/Laws_Mobile.aspx",),
        )
        landing_payload = landing_batch.payloads[0]
        landing_evidence = self._oregon_input_evidence_context(
            source_url=LAWS_MOBILE_URL,
            payload=landing_payload,
            transport_receipt=landing_batch.transport_receipts[0],
            parser_input_envelope=landing_batch.parser_input_envelopes[0],
        )
        sessions = oregon_current_law_sessions(
            decode_oregon_html(landing_payload)
        )
        if (
            len(sessions) != 2
            or sum(row.declared_chapter_count for row in sessions)
            != expected_oregon_law_chapter_count()
        ):
            raise RuntimeError("Oregon Laws current-session catalog did not close")

        group_urls = [row.inventory_url for row in sessions]

        def _valid_law_group(payload: bytes) -> bool:
            try:
                html = decode_oregon_html(payload)
            except Exception:
                return False
            return bool(
                re.search(
                    r"/bills_laws/lawsstatutes/(?:2025S1OrLaw|2026orlaw)"
                    r"\d{4}\.pdf",
                    html,
                    flags=re.IGNORECASE,
                )
            )

        group_batch = await self._fetch_oregon_plural_frontier(
            group_urls,
            frontier_name="session-law-group",
            content_validator=_valid_law_group,
            common_crawl_url_terms=("/bills_laws/_layouts/15/inplview.aspx",),
        )
        locators: List[Any] = []
        group_frontier_rows: List[Tuple[str, bytes]] = []
        for session, group_url, payload, receipt, envelope in zip(
            sessions,
            group_batch.urls,
            group_batch.payloads,
            group_batch.transport_receipts,
            group_batch.parser_input_envelopes,
            strict=True,
        ):
            self._oregon_input_evidence_context(
                source_url=group_url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            session_locators = oregon_law_chapter_locators(
                decode_oregon_html(payload), session
            )
            if len(session_locators) != session.declared_chapter_count:
                raise RuntimeError(
                    "Oregon Laws group changed its source-declared count: "
                    f"{session.label}"
                )
            locators.extend(session_locators)
            group_frontier_rows.append((group_url, payload))

        chapter_urls = [row.canonical_url for row in locators]
        if (
            len(chapter_urls) != expected_oregon_law_chapter_count()
            or len(chapter_urls) != len(set(chapter_urls))
            or any(not self._host_is_official(url) for url in chapter_urls)
        ):
            raise RuntimeError("Oregon Laws chapter PDF frontier is not exact")

        chapter_batch = await self._fetch_oregon_plural_frontier(
            chapter_urls,
            frontier_name="session-law-pdf",
            content_validator=valid_full_oregon_law_pdf,
            common_crawl_url_terms=("/bills_laws/lawsstatutes/",),
            accept="application/pdf,*/*;q=0.5",
            media_type="application/pdf",
            common_crawl_mime_terms=("pdf",),
        )
        rows: List[NormalizedStatute] = []
        parsed_laws: List[Any] = []
        seen_identities: Dict[str, str] = {}
        chapter_frontier_rows: List[Tuple[str, bytes]] = []
        per_session_section_counts: Dict[str, int] = {
            session.key: 0 for session in sessions
        }
        for locator, chapter_url, payload, receipt, envelope in zip(
            locators,
            chapter_batch.urls,
            chapter_batch.payloads,
            chapter_batch.transport_receipts,
            chapter_batch.parser_input_envelopes,
            strict=True,
        ):
            if chapter_url != locator.canonical_url:
                raise RuntimeError("Oregon Laws PDF URL/locator alignment changed")
            evidence = self._oregon_input_evidence_context(
                source_url=chapter_url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            parsed = parse_oregon_law_pdf(payload, locator=locator)
            parsed_laws.append(parsed)
            chapter_rows = normalized_oregon_law_sections(
                parsed,
                legal_area=legal_area,
            )
            if not chapter_rows:
                raise RuntimeError(
                    f"Oregon Laws chapter emitted no sections: {chapter_url}"
                )
            for row in chapter_rows:
                base_source_url = str(row.source_url or "").split("#", 1)[0]
                identity = str(row.statute_id or "").strip().casefold()
                if base_source_url != chapter_url or not identity:
                    raise RuntimeError(
                        "Oregon Laws normalized row changed source identity: "
                        f"{chapter_url}"
                    )
                prior_url = seen_identities.get(identity)
                if prior_url is not None:
                    raise RuntimeError(
                        "Oregon Laws repeated a canonical section identity: "
                        f"{row.statute_id} first={prior_url} second={chapter_url}"
                    )
                seen_identities[identity] = chapter_url
                data = dict(row.structured_data or {})
                data.update(
                    {
                        "content_sha256": evidence["content_sha256"],
                        "parser_input_receipt_sha256": evidence[
                            "parser_input_receipt_sha256"
                        ],
                        "source_retrieved_at": evidence["source_retrieved_at"],
                        "source_transport": evidence["source_transport"],
                        "source_transport_chain": evidence[
                            "source_transport_chain"
                        ],
                        "transport_receipt": evidence["transport_receipt"],
                    }
                )
                row.structured_data = data
                rows.append(row)
                per_session_section_counts[locator.session_key] += 1
            chapter_frontier_rows.append((chapter_url, payload))

        supplement_group_urls = [
            oregon_supplement_inventory_url(session) for session in sessions
        ]
        resolution_group_urls = [
            oregon_resolution_inventory_url(session) for session in sessions
        ]
        evidence_group_urls = [*supplement_group_urls, *resolution_group_urls]

        def _valid_evidence_group(payload: bytes) -> bool:
            try:
                html = decode_oregon_html(payload)
            except Exception:
                return False
            return bool(
                re.search(
                    r"/bills_laws/lawsstatutes/(?:"
                    r"2025S1(?:OrLaw(?:Enacted|AR)|hcr\d+)|"
                    r"2026(?:OrLaw(?:Enacted|AR)|[hs]cr\d+))\.pdf",
                    html,
                    flags=re.IGNORECASE,
                )
            )

        evidence_group_batch = await self._fetch_oregon_plural_frontier(
            evidence_group_urls,
            frontier_name="session-law-parity-group",
            content_validator=_valid_evidence_group,
            common_crawl_url_terms=("/bills_laws/_layouts/15/inplview.aspx",),
        )
        evidence_group_frontier_rows: List[Tuple[str, bytes]] = []
        evidence_group_context: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        supplement_locators: List[Any] = []
        resolution_locators: List[Any] = []
        group_requests = [
            *(('supplement', session) for session in sessions),
            *(('resolution', session) for session in sessions),
        ]
        for (kind, session), group_url, payload, receipt, envelope in zip(
            group_requests,
            evidence_group_batch.urls,
            evidence_group_batch.payloads,
            evidence_group_batch.transport_receipts,
            evidence_group_batch.parser_input_envelopes,
            strict=True,
        ):
            expected_url = (
                oregon_supplement_inventory_url(session)
                if kind == "supplement"
                else oregon_resolution_inventory_url(session)
            )
            if group_url != expected_url:
                raise RuntimeError(
                    "Oregon Laws parity group URL/session alignment changed"
                )
            evidence = self._oregon_input_evidence_context(
                source_url=group_url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            evidence_group_context[(kind, session.key)] = evidence
            html = decode_oregon_html(payload)
            if kind == "supplement":
                supplement_locators.extend(
                    oregon_supplement_locators(html, session)
                )
            else:
                resolution_locators.extend(
                    oregon_resolution_locators(html, session)
                )
            evidence_group_frontier_rows.append((group_url, payload))

        table_locators = [
            row
            for row in supplement_locators
            if row.document_kind in {"enacted_table", "affected_table"}
        ]
        table_urls = [row.canonical_url for row in table_locators]
        if (
            len(table_urls) != 4
            or len(table_urls) != len(set(table_urls))
            or any(not self._host_is_official(url) for url in table_urls)
            or len(resolution_locators) != 10
        ):
            raise RuntimeError(
                "Oregon Laws parity-table/resolution frontier is not exact"
            )

        table_batch = await self._fetch_oregon_plural_frontier(
            table_urls,
            frontier_name="session-law-parity-pdf",
            content_validator=valid_full_oregon_law_pdf,
            common_crawl_url_terms=("/bills_laws/lawsstatutes/",),
            accept="application/pdf,*/*;q=0.5",
            media_type="application/pdf",
            common_crawl_mime_terms=("pdf",),
        )
        enacted_entries: List[Any] = []
        affected_references: List[Any] = []
        table_frontier_rows: List[Tuple[str, bytes]] = []
        table_evidence: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        for locator, table_url, payload, receipt, envelope in zip(
            table_locators,
            table_batch.urls,
            table_batch.payloads,
            table_batch.transport_receipts,
            table_batch.parser_input_envelopes,
            strict=True,
        ):
            if table_url != locator.canonical_url:
                raise RuntimeError("Oregon Laws parity PDF URL/locator alignment changed")
            evidence = self._oregon_input_evidence_context(
                source_url=table_url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            table_evidence[(locator.session_key, locator.document_kind)] = evidence
            if locator.document_kind == "enacted_table":
                enacted_entries.extend(
                    parse_oregon_enacted_pdf(
                        payload,
                        session_key=locator.session_key,
                    )
                )
            elif locator.document_kind == "affected_table":
                affected_references.extend(
                    parse_oregon_affected_pdf(
                        payload,
                        session_key=locator.session_key,
                    )
                )
            else:  # pragma: no cover - exact locator filter above
                raise RuntimeError("unexpected Oregon Laws parity document kind")
            table_frontier_rows.append((table_url, payload))

        reconciliation = reconcile_oregon_session_evidence(
            parsed_laws,
            enacted_entries,
            affected_references,
        )
        table_locator_by_key = {
            (row.session_key, row.document_kind): row for row in table_locators
        }
        resolutions_by_session = {
            session.key: [
                row for row in resolution_locators if row.session_key == session.key
            ]
            for session in sessions
        }
        for row in rows:
            data = dict(row.structured_data or {})
            session_key = str(data.get("session_key") or "")
            chapter_number = int(data.get("chapter_number") or 0)
            section_number = str(data.get("section_number") or "").upper()
            chapter_key = (session_key, chapter_number)
            section_key = (*chapter_key, section_number)
            enacted = reconciliation.enacted_by_chapter.get(chapter_key)
            if enacted is None:
                raise RuntimeError(
                    f"Oregon Laws normalized row has no enacted-table join: {chapter_key}"
                )
            enacted_locator = table_locator_by_key[(session_key, "enacted_table")]
            affected_locator = table_locator_by_key[(session_key, "affected_table")]
            actions = reconciliation.actions_by_section.get(section_key, ())
            resolution_group_evidence = evidence_group_context[
                ("resolution", session_key)
            ]
            data["currentness_parity"] = {
                "closed": True,
                "enacted_table": {
                    "declared_url": enacted_locator.declared_url,
                    "canonical_url": enacted_locator.canonical_url,
                    "content_sha256": table_evidence[
                        (session_key, "enacted_table")
                    ]["content_sha256"],
                    "bill_number": enacted.bill_number,
                    "chapter_number": enacted.chapter_number,
                    "effective_date": enacted.effective_date,
                    "notes": list(enacted.notes),
                },
                "affected_table": {
                    "declared_url": affected_locator.declared_url,
                    "canonical_url": affected_locator.canonical_url,
                    "content_sha256": table_evidence[
                        (session_key, "affected_table")
                    ]["content_sha256"],
                    "references": [
                        {
                            "table_kind": action.table_kind,
                            "target": action.target,
                            "action": action.action,
                            "law_chapter_number": action.law_chapter_number,
                            "law_section_number": action.law_section_number,
                            "bill_number": action.bill_number,
                            "emergency_marker": action.emergency_marker,
                        }
                        for action in actions
                    ],
                },
                "resolution_scope_exclusion": {
                    "reason": "nonstatutory_resolution",
                    "inventory_content_sha256": resolution_group_evidence[
                        "content_sha256"
                    ],
                    "document_count": len(resolutions_by_session[session_key]),
                    "documents": [
                        {
                            "identity": locator.identity,
                            "declared_url": locator.declared_url,
                            "canonical_url": locator.canonical_url,
                        }
                        for locator in resolutions_by_session[session_key]
                    ],
                },
            }
            row.structured_data = data

        source_document_disposition = {
            "discovered": len(chapter_frontier_rows) + len(resolution_locators),
            "fetched": len(chapter_frontier_rows),
            "excluded": len(resolution_locators),
            "failed_final": 0,
            "duplicates": 0,
            "quarantined": 0,
        }
        if source_document_disposition["discovered"] != sum(
            source_document_disposition[key]
            for key in (
                "fetched",
                "excluded",
                "failed_final",
                "duplicates",
                "quarantined",
            )
        ):
            raise RuntimeError("Oregon Laws source-document algebra did not close")
        resolution_identity_digest = hashlib.sha256(
            json.dumps(
                [
                    {
                        "identity": row.identity,
                        "canonical_url": row.canonical_url,
                        "disposition": row.document_kind,
                    }
                    for row in resolution_locators
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        closure = {
            "closed": (
                len(chapter_frontier_rows)
                == expected_oregon_law_chapter_count()
                and len(rows) == len(seen_identities)
                and all(count > 0 for count in per_session_section_counts.values())
                and bool(reconciliation.summary.get("closed"))
                and len(table_frontier_rows) == 4
                and len(resolution_locators) == 10
            ),
            "catalog_url": LAWS_MOBILE_URL,
            "catalog_content_sha256": landing_evidence["content_sha256"],
            "session_group_count": len(sessions),
            "session_group_frontier_sha256": self._oregon_frontier_digest(
                group_frontier_rows
            ),
            "declared_chapter_count": expected_oregon_law_chapter_count(),
            "chapter_pdf_count": len(chapter_frontier_rows),
            "chapter_pdf_frontier_sha256": self._oregon_frontier_digest(
                chapter_frontier_rows
            ),
            "section_count": len(rows),
            "unique_section_identity_count": len(seen_identities),
            "per_session_section_counts": dict(per_session_section_counts),
            "parity_group_count": len(evidence_group_frontier_rows),
            "parity_group_frontier_sha256": self._oregon_frontier_digest(
                evidence_group_frontier_rows
            ),
            "parity_pdf_count": len(table_frontier_rows),
            "parity_pdf_frontier_sha256": self._oregon_frontier_digest(
                table_frontier_rows
            ),
            "reconciliation": dict(reconciliation.summary),
            "resolution_document_count": len(resolution_locators),
            "resolution_identity_digest_sha256": resolution_identity_digest,
            "resolution_exclusions": [
                {
                    "identity": row.identity,
                    "declared_url": row.declared_url,
                    "canonical_url": row.canonical_url,
                    "disposition": row.document_kind,
                }
                for row in resolution_locators
            ],
            "source_document_disposition": source_document_disposition,
            "failed_final": 0,
            "duplicates": 0,
            "quarantined": 0,
        }
        if not closure["closed"]:
            raise RuntimeError("Oregon Laws section frontier did not close exactly")
        self._last_oregon_session_law_closure = closure
        self._last_oregon_session_catalog_batch_stats = dict(
            landing_batch.stats or {}
        )
        self._last_oregon_session_group_batch_stats = dict(group_batch.stats or {})
        self._last_oregon_session_pdf_batch_stats = dict(chapter_batch.stats or {})
        self._last_oregon_session_parity_group_batch_stats = dict(
            evidence_group_batch.stats or {}
        )
        self._last_oregon_session_parity_pdf_batch_stats = dict(
            table_batch.stats or {}
        )
        self._last_oregon_session_boundary_first = chapter_urls[0]
        self._last_oregon_session_boundary_last = chapter_urls[-1]
        return rows

    async def _scrape_strict_ors_title_inventory(
        self,
        *,
        code_name: str,
        legal_area: str,
        seed_url: str,
        seed_bytes: bytes,
        title_groups: Sequence[Any],
        record_primary: bool = True,
        write_checkpoints: bool = True,
    ) -> List[NormalizedStatute]:
        """Close the collapsed 19-volume ORS catalog with two plural fetches."""

        from .oregon_chapter import (
            decode_oregon_html,
            ors_chapter_links,
        )

        groups = list(title_groups)
        volumes = {int(group.volume_index) for group in groups}
        if not groups or volumes != set(range(1, 20)):
            raise RuntimeError(
                "Oregon collapsed ORS catalog does not expose every volume 1-19"
            )
        expected_edition_year = _extract_edition_year(
            _lineify(decode_oregon_html(seed_bytes))
        )
        if expected_edition_year is None:
            raise RuntimeError(
                "Oregon official ORS catalog does not identify its edition"
            )
        group_urls = [str(group.inventory_url) for group in groups]
        if any(not self._host_is_official(url) for url in group_urls):
            raise RuntimeError("Oregon title-group catalog changed official host")

        def _valid_group(payload: bytes) -> bool:
            try:
                return bool(ors_chapter_links(decode_oregon_html(payload)))
            except Exception:
                return False

        group_batch = await self._fetch_oregon_plural_frontier(
            group_urls,
            frontier_name="title-group",
            content_validator=_valid_group,
            common_crawl_url_terms=("/bills_laws/_layouts/15/inplview.aspx",),
        )
        chapter_urls: List[str] = []
        group_frontier_rows: List[Tuple[str, bytes]] = []
        for group, group_url, payload, receipt, envelope in zip(
            groups,
            group_batch.urls,
            group_batch.payloads,
            group_batch.transport_receipts,
            group_batch.parser_input_envelopes,
            strict=True,
        ):
            self._oregon_input_evidence_context(
                source_url=group_url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            links = ors_chapter_links(decode_oregon_html(payload))
            if len(links) != int(group.declared_chapter_count):
                raise RuntimeError(
                    "Oregon title-group chapter count changed: "
                    f"group={group.label!r} declared={group.declared_chapter_count} "
                    f"parsed={len(links)}"
                )
            urls = [url for _number, _name, url in links]
            if len(urls) != len(set(urls)) or any(
                not self._host_is_official(url) for url in urls
            ):
                raise RuntimeError(
                    "Oregon title-group response contains duplicate or nonofficial chapters"
                )
            chapter_urls.extend(urls)
            group_frontier_rows.append((group_url, payload))

        declared_chapter_count = sum(
            int(group.declared_chapter_count) for group in groups
        )
        if (
            len(chapter_urls) != declared_chapter_count
            or len(chapter_urls) != len(set(chapter_urls))
        ):
            raise RuntimeError(
                "Oregon collapsed title groups do not reconcile to unique chapter URLs"
            )

        def _valid_chapter(payload: bytes) -> bool:
            try:
                html = decode_oregon_html(payload)
            except Exception:
                return False
            return bool(
                re.search(r"<p\b", html, flags=re.IGNORECASE)
                and re.search(
                    r"\b\d{1,3}[a-z]?\.\d{3,4}[a-z]?\b",
                    html,
                    flags=re.IGNORECASE,
                )
                and _ors_chapter_matches_edition(
                    html,
                    expected_edition_year,
                )
            )

        chapter_batch = await self._fetch_oregon_plural_frontier(
            chapter_urls,
            frontier_name="chapter",
            content_validator=_valid_chapter,
            common_crawl_url_terms=("/bills_laws/ors/",),
        )
        chapter_edition_years = [
            _extract_edition_year(
                _lineify(decode_oregon_html(payload))
            )
            for payload in chapter_batch.payloads
        ]
        if any(
            edition_year is not None
            and edition_year != expected_edition_year
            for edition_year in chapter_edition_years
        ):
            raise RuntimeError(
                "Oregon chapter frontier contains an explicitly stale edition"
            )
        required_conditional_event_keys: set[str] = set()
        for payload in chapter_batch.payloads:
            required_conditional_event_keys.update(
                _ors_conditional_event_keys_in_html(
                    decode_oregon_html(payload)
                )
            )
        conditional_outcomes = (
            await self._acquire_ors_conditional_event_outcomes(
                sorted(required_conditional_event_keys)
            )
            if required_conditional_event_keys
            else {}
        )
        if set(conditional_outcomes) != required_conditional_event_keys:
            raise RuntimeError(
                "Oregon conditional event selectors did not close exactly: "
                f"required={sorted(required_conditional_event_keys)} "
                f"resolved={sorted(conditional_outcomes)}"
            )
        statutes: List[NormalizedStatute] = []
        terminal_sections: List[Dict[str, Any]] = []
        lifecycle_exclusions: List[Dict[str, Any]] = []
        seen_section_identities: Dict[str, str] = {}
        chapter_frontier_rows: List[Tuple[str, bytes]] = []
        toc_section_identity_count = 0
        for chapter_index, (
            chapter_url,
            payload,
            receipt,
            envelope,
        ) in enumerate(
            zip(
                chapter_batch.urls,
                chapter_batch.payloads,
                chapter_batch.transport_receipts,
                chapter_batch.parser_input_envelopes,
                strict=True,
            ),
            start=1,
        ):
            evidence = self._oregon_input_evidence_context(
                source_url=chapter_url,
                payload=payload,
                transport_receipt=receipt,
                parser_input_envelope=envelope,
            )
            chapter_html = decode_oregon_html(payload)
            chapter_rows = self._parse_chapter_html(
                html=chapter_html,
                chapter_url=chapter_url,
                code_name=code_name,
                citation_format="Or. Rev. Stat.",
                legal_area=legal_area,
                legal_as_of=evidence["source_retrieved_at"],
                conditional_outcomes=conditional_outcomes,
            )
            chapter_terminals = [
                dict(row) for row in self._last_oregon_terminal_sections
            ]
            chapter_lifecycle_exclusions = [
                dict(row) for row in self._last_oregon_lifecycle_exclusions
            ]
            unclassified = list(self._last_oregon_unclassified_sections)
            duplicate_identities = list(
                self._last_oregon_duplicate_section_identities
            )
            toc_identities = list(self._last_oregon_toc_section_identities)
            duplicate_toc_identities = sorted(
                section_id
                for section_id in set(toc_identities)
                if toc_identities.count(section_id) > 1
            )
            classified_chapter_identities = {
                str(row.section_number or "").casefold() for row in chapter_rows
            } | {
                str(row.get("section_number") or "").casefold()
                for row in chapter_terminals
            }
            missing_toc_identities = sorted(
                set(toc_identities) - classified_chapter_identities
            )
            source_occurrence_count = int(
                self._last_oregon_section_occurrence_count
            )
            classified_occurrence_count = (
                len(chapter_rows)
                + len(chapter_terminals)
                + len(chapter_lifecycle_exclusions)
                + len(unclassified)
            )
            occurrence_algebra_mismatch = (
                source_occurrence_count != classified_occurrence_count
            )
            if (
                unclassified
                or duplicate_identities
                or duplicate_toc_identities
                or missing_toc_identities
                or occurrence_algebra_mismatch
            ):
                raise RuntimeError(
                    "Oregon chapter section algebra is not exact: "
                    f"url={chapter_url} unclassified={unclassified} "
                    f"duplicates={duplicate_identities} "
                    f"duplicate_toc={duplicate_toc_identities} "
                    f"missing_toc={missing_toc_identities} "
                    f"source_occurrences={source_occurrence_count} "
                    f"classified_occurrences={classified_occurrence_count}"
                )
            if not chapter_rows and not chapter_terminals:
                raise RuntimeError(
                    "Oregon chapter exposes neither an operative section nor a "
                    f"typed terminal disposition: {chapter_url}"
                )

            chapter_slug = _chapter_slug_from_url(chapter_url) or ""
            chapter_prefix = _chapter_number_display(chapter_slug).casefold() + "."
            for terminal in chapter_terminals:
                section_number = str(terminal.get("section_number") or "").casefold()
                if not section_number.startswith(chapter_prefix):
                    raise RuntimeError(
                        "Oregon terminal section changed requested chapter identity: "
                        f"{chapter_url}"
                    )
                prior_url = seen_section_identities.get(section_number)
                if prior_url is not None:
                    raise RuntimeError(
                        "Oregon frontier repeated a terminal section identity: "
                        f"section={section_number} first={prior_url} second={chapter_url}"
                    )
                seen_section_identities[section_number] = chapter_url
                terminal.update(
                    {
                        "content_sha256": evidence["content_sha256"],
                        "parser_input_receipt_sha256": evidence[
                            "parser_input_receipt_sha256"
                        ],
                        "source_retrieved_at": evidence["source_retrieved_at"],
                        "source_transport": evidence["source_transport"],
                        "source_transport_chain": evidence[
                            "source_transport_chain"
                        ],
                    }
                )
                terminal_sections.append(terminal)

            for exclusion in chapter_lifecycle_exclusions:
                section_number = str(
                    exclusion.get("section_number") or ""
                ).casefold()
                if not section_number.startswith(chapter_prefix):
                    raise RuntimeError(
                        "Oregon lifecycle exclusion changed requested chapter identity: "
                        f"{chapter_url}"
                    )
                exclusion.update(
                    {
                        "content_sha256": evidence["content_sha256"],
                        "parser_input_receipt_sha256": evidence[
                            "parser_input_receipt_sha256"
                        ],
                        "source_retrieved_at": evidence["source_retrieved_at"],
                        "source_transport": evidence["source_transport"],
                        "source_transport_chain": evidence[
                            "source_transport_chain"
                        ],
                    }
                )
                lifecycle_exclusions.append(exclusion)

            for row in chapter_rows:
                section_number = str(row.section_number or "").casefold()
                if not section_number.startswith(chapter_prefix):
                    raise RuntimeError(
                        "Oregon normalized section changed requested chapter identity: "
                        f"section={section_number} url={chapter_url}"
                    )
                if str(row.source_url or "").split("#", 1)[0] != chapter_url:
                    raise RuntimeError(
                        "Oregon normalized section changed its official source URL: "
                        f"{chapter_url}"
                    )
                prior_url = seen_section_identities.get(section_number)
                if prior_url is not None:
                    raise RuntimeError(
                        "Oregon frontier repeated a canonical statute identity: "
                        f"section={section_number} first={prior_url} second={chapter_url}"
                    )
                seen_section_identities[section_number] = chapter_url
                data = dict(row.structured_data or {})
                data.update(
                    {
                        "chapter_url": chapter_url,
                        "content_sha256": evidence["content_sha256"],
                        "discovery_method": "official_ors_sharepoint_title_inventory",
                        "parser_input_receipt_sha256": evidence[
                            "parser_input_receipt_sha256"
                        ],
                        "source_retrieved_at": evidence["source_retrieved_at"],
                        "source_transport": evidence["source_transport"],
                        "source_transport_chain": evidence[
                            "source_transport_chain"
                        ],
                        "transport_receipt": evidence["transport_receipt"],
                    }
                )
                row.structured_data = data
                statutes.append(row)
            chapter_frontier_rows.append((chapter_url, payload))
            toc_section_identity_count += len(toc_identities)

            if write_checkpoints and (
                chapter_index % 50 == 0 or chapter_index == len(chapter_urls)
            ):
                self._write_partial_checkpoint(
                    statutes,
                    code_name=code_name,
                    stage_label="oregon:strict_chapter_frontier",
                    force=True,
                    extra={
                        "chapter_pages_completed": chapter_index,
                        "chapter_pages_total": len(chapter_urls),
                        "operative_sections_admitted": len(statutes),
                        "terminal_sections_excluded": len(terminal_sections),
                        "lifecycle_variants_excluded": len(
                            lifecycle_exclusions
                        ),
                    },
                )

        ors_operative_section_count = len(statutes)
        session_law_rows = await self._scrape_strict_oregon_session_laws(
            legal_area=legal_area,
        )
        session_closure = getattr(
            self,
            "_last_oregon_session_law_closure",
            None,
        )
        if not isinstance(session_closure, Mapping) or not session_closure.get(
            "closed"
        ):
            raise RuntimeError("Oregon Laws overlay did not retain exact closure")
        session_identities = {
            str(row.statute_id or "").strip().casefold() for row in session_law_rows
        }
        if (
            len(session_identities) != len(session_law_rows)
            or any(not identity for identity in session_identities)
        ):
            raise RuntimeError("Oregon Laws overlay identities are not unique")
        statutes.extend(session_law_rows)

        closed = (
            len(chapter_frontier_rows) == declared_chapter_count
            and len(seen_section_identities)
            == ors_operative_section_count + len(terminal_sections)
            and len(session_law_rows)
            == int(session_closure["unique_section_identity_count"])
            and set(conditional_outcomes)
            == required_conditional_event_keys
        )
        self._last_oregon_group_batch_stats = dict(group_batch.stats or {})
        self._last_oregon_chapter_batch_stats = dict(chapter_batch.stats or {})
        self._last_oregon_terminal_sections = terminal_sections
        self._last_oregon_lifecycle_exclusions = lifecycle_exclusions
        self._last_oregon_unclassified_sections = []
        strict_closure = {
            "closed": closed,
            "catalog_content_sha256": hashlib.sha256(seed_bytes).hexdigest(),
            "catalog_url": seed_url,
            "title_group_count": len(groups),
            "title_group_frontier_sha256": self._oregon_frontier_digest(
                group_frontier_rows
            ),
            "declared_chapter_count": declared_chapter_count,
            "chapter_page_count": len(chapter_frontier_rows),
            "ors_expected_edition_year": expected_edition_year,
            "ors_explicit_edition_chapter_count": sum(
                edition_year is not None
                for edition_year in chapter_edition_years
            ),
            "ors_unlabelled_edition_chapter_count": sum(
                edition_year is None
                for edition_year in chapter_edition_years
            ),
            "chapter_frontier_sha256": self._oregon_frontier_digest(
                chapter_frontier_rows
            ),
            "ors_operative_section_count": ors_operative_section_count,
            "session_law_section_count": len(session_law_rows),
            "operative_section_count": len(statutes),
            "terminal_section_count": len(terminal_sections),
            "lifecycle_variant_exclusion_count": len(lifecycle_exclusions),
            "conditional_event_count": len(conditional_outcomes),
            "conditional_event_keys": sorted(conditional_outcomes),
            "conditional_event_outcomes": {
                event_key: dict(conditional_outcomes[event_key])
                for event_key in sorted(conditional_outcomes)
            },
            "conditional_event_selector_source_count": len(
                {
                    source_url
                    for outcome in conditional_outcomes.values()
                    for source_url in outcome["selector_source_urls"]
                }
            ),
            "unclassified_section_count": 0,
            "duplicate_section_identity_count": 0,
            "source_section_identity_count": (
                len(seen_section_identities) + len(session_identities)
            ),
            "source_section_occurrence_count": (
                len(seen_section_identities)
                + len(lifecycle_exclusions)
                + len(session_identities)
            ),
            "toc_section_identity_count": toc_section_identity_count,
            "session_law": dict(session_closure),
        }
        if not closed:
            raise RuntimeError("Oregon strict ORS frontier did not close exactly")
        disposition = {
            "discovered": (
                len(statutes)
                + len(terminal_sections)
                + len(lifecycle_exclusions)
            ),
            "fetched": len(statutes),
            "excluded": len(terminal_sections) + len(lifecycle_exclusions),
            "failed_final": 0,
            "duplicates": 0,
            "quarantined": 0,
        }
        if disposition["discovered"] != sum(
            disposition[key]
            for key in (
                "fetched",
                "excluded",
                "failed_final",
                "duplicates",
                "quarantined",
            )
        ):
            raise RuntimeError("Oregon strict section disposition algebra did not close")
        from ...legal_data.open_us_law_live_evidence import compute_frontier_digest

        frontier = {
            "algebra_closed": True,
            "bundle_closed": False,
            "chapter_frontier_sha256": strict_closure[
                "chapter_frontier_sha256"
            ],
            "chapter_page_count": len(chapter_frontier_rows),
            "ors_expected_edition_year": expected_edition_year,
            "ors_explicit_edition_chapter_count": sum(
                edition_year is not None
                for edition_year in chapter_edition_years
            ),
            "ors_unlabelled_edition_chapter_count": sum(
                edition_year is None
                for edition_year in chapter_edition_years
            ),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": disposition["discovered"],
            "pagination_closed": True,
            "schema_version": "oregon-strict-sharepoint-current-overlay-v4",
            "scope_closed": True,
            "source_section_identity_count": (
                len(seen_section_identities) + len(session_identities)
            ),
            "source_section_occurrence_count": (
                len(seen_section_identities)
                + len(lifecycle_exclusions)
                + len(session_identities)
            ),
            "ors_lifecycle_variant_exclusion_count": len(
                lifecycle_exclusions
            ),
            "ors_lifecycle_variant_exclusions": list(lifecycle_exclusions),
            "ors_conditional_event_outcomes": {
                event_key: dict(conditional_outcomes[event_key])
                for event_key in sorted(conditional_outcomes)
            },
            "session_law_chapter_count": int(
                session_closure["chapter_pdf_count"]
            ),
            "session_law_chapter_frontier_sha256": str(
                session_closure["chapter_pdf_frontier_sha256"]
            ),
            "session_law_group_count": int(
                session_closure["session_group_count"]
            ),
            "session_law_group_frontier_sha256": str(
                session_closure["session_group_frontier_sha256"]
            ),
            "session_law_section_count": len(session_law_rows),
            "session_law_parity_group_count": int(
                session_closure["parity_group_count"]
            ),
            "session_law_parity_group_frontier_sha256": str(
                session_closure["parity_group_frontier_sha256"]
            ),
            "session_law_parity_pdf_count": int(
                session_closure["parity_pdf_count"]
            ),
            "session_law_parity_pdf_frontier_sha256": str(
                session_closure["parity_pdf_frontier_sha256"]
            ),
            "session_law_resolution_document_count": int(
                session_closure["resolution_document_count"]
            ),
            "session_law_resolution_identity_digest_sha256": str(
                session_closure["resolution_identity_digest_sha256"]
            ),
            "session_law_resolution_exclusions": list(
                session_closure["resolution_exclusions"]
            ),
            "session_law_source_document_disposition": dict(
                session_closure["source_document_disposition"]
            ),
            "title_group_count": len(groups),
            "title_group_frontier_sha256": strict_closure[
                "title_group_frontier_sha256"
            ],
            "toc_exhausted": True,
            "toc_section_identity_count": toc_section_identity_count,
            "unvisited_continuation_links": [],
            "visited_index_units": disposition["discovered"],
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        observation = {
            "boundary_first": chapter_urls[0],
            "boundary_last": str(
                getattr(
                    self,
                    "_last_oregon_session_boundary_last",
                    chapter_urls[-1],
                )
            ),
            "closure": strict_closure,
            "frontier": frontier,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        target = (
            "_last_oregon_full_frontier"
            if record_primary
            else "_last_oregon_replayed_frontier"
        )
        setattr(self, target, observation)
        self._last_oregon_strict_closure = strict_closure
        return statutes

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay retained ORS and Oregon Laws inputs and seal exact algebra."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError(
                "Oregon frontier closure requires an attached acquisition ledger"
            )
        first = getattr(self, "_last_oregon_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Oregon strict chapter frontier was not retained before output"
            )

        from .oregon_chapter import (
            decode_oregon_html,
            ors_sharepoint_title_groups,
        )

        seed_bytes = await self._fetch_strict_ors_catalog(self.OFFICIAL_ENTRY_URL)
        if not seed_bytes:
            raise RuntimeError("Oregon retained catalog cannot be replayed")
        title_groups = ors_sharepoint_title_groups(
            decode_oregon_html(seed_bytes)
        )
        if not title_groups:
            raise RuntimeError("Oregon replayed catalog has no title groups")
        replay_rows = await self._scrape_strict_ors_title_inventory(
            code_name="Oregon Revised Statutes",
            legal_area=self._identify_legal_area("Oregon Revised Statutes"),
            seed_url=self.OFFICIAL_ENTRY_URL,
            seed_bytes=bytes(seed_bytes),
            title_groups=title_groups,
            record_primary=False,
            write_checkpoints=False,
        )
        replay = getattr(self, "_last_oregon_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("Oregon strict chapter replay was not retained")

        from ...legal_data.open_us_law_acquisition_coordinator import (
            canonical_json_bytes,
        )
        from ...legal_data.state_laws_completeness import (
            closed_jurisdiction_receipt,
        )
        from ...legal_data.state_laws_multifetch_acquisition import (
            build_canonical_state_law_output_projection,
        )

        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("Oregon strict frontier observations are incomplete")
        if canonical_json_bytes(first_frontier) != canonical_json_bytes(
            replayed_frontier
        ):
            raise RuntimeError("Oregon first and replayed exact frontiers differ")

        replay_projection = build_canonical_state_law_output_projection(
            [self._enrich_statute_structure(row).to_dict() for row in replay_rows],
            jurisdiction="OR",
        )
        output_keys_raw = canonical_output_projection.get("canonical_keys")
        if not isinstance(output_keys_raw, Sequence) or isinstance(
            output_keys_raw, (str, bytes, bytearray)
        ):
            raise RuntimeError("Oregon canonical output lacks exact identities")
        output_keys = [str(item).strip() for item in output_keys_raw]
        replay_keys = [
            str(item).strip()
            for item in replay_projection.get("canonical_keys", [])
        ]
        if (
            not output_keys
            or any(not item for item in output_keys)
            or len(output_keys) != len(set(output_keys))
            or output_keys != replay_keys
        ):
            missing = sorted(set(replay_keys) - set(output_keys))
            extra = sorted(set(output_keys) - set(replay_keys))
            raise RuntimeError(
                "Oregon final canonical identities do not exactly match the "
                "independently replayed chapter frontier: "
                f"expected={len(replay_keys)} actual={len(output_keys)} "
                f"missing={missing[:3]} extra={extra[:3]}"
            )

        disposition = first_frontier.get("disposition")
        if not isinstance(disposition, Mapping):
            raise RuntimeError("Oregon strict frontier lacks disposition algebra")
        if int(disposition.get("fetched") or -1) != len(output_keys):
            raise RuntimeError(
                "Oregon strict fetched count changed after final output filtering"
            )
        completion = closed_jurisdiction_receipt(
            "OR",
            discovered=int(disposition["discovered"]),
            fetched=int(disposition["fetched"]),
            excluded=int(disposition["excluded"]),
            quarantined=int(disposition["quarantined"]),
            failed_final=int(disposition["failed_final"]),
            duplicates=int(disposition["duplicates"]),
            source_domain=self.OFFICIAL_DOMAIN,
            canonical_keys=output_keys,
            derived_keys=output_keys,
        )
        completion.update(
            {
                "boundary_probes": {
                    "bundle_total": 0,
                    "first_hierarchy_unit": str(first.get("boundary_first") or ""),
                    "last_hierarchy_unit": str(first.get("boundary_last") or ""),
                    "pagination_total": int(
                        first_frontier.get("title_group_count") or 0
                    ),
                },
                "canonical_row_count": len(output_keys),
                "frontier": dict(first_frontier),
                "legal_as_of": (
                    "2025 Oregon Revised Statutes edition overlaid with "
                    "Oregon Laws 2025 Special Session 1 and 2026 Regular Session"
                ),
                "observed_at": str(first.get("observed_at") or ""),
                "replay": {
                    "closed": True,
                    "first_frontier_digest": str(
                        first_frontier.get("frontier_digest_sha256") or ""
                    ),
                    "second_frontier_digest": str(
                        replayed_frontier.get("frontier_digest_sha256") or ""
                    ),
                },
                "rights": {
                    "basis": "public_law_no_state_copyright",
                    "decision": "admit",
                    "scope": "statutory_text",
                },
                "transport": {
                    "fixture": False,
                    "kind": "shared_archive_aware_plural_html_and_pdf",
                    "synthetic": False,
                },
            }
        )
        frontier_digest = str(
            first_frontier.get("frontier_digest_sha256") or ""
        )
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=dict(replayed_frontier),
            canonical_output_projection=canonical_output_projection,
            release_point=f"sha256:{frontier_digest}",
            official_source_url=self.OFFICIAL_ENTRY_URL,
            acquisition_path_ids=self._catalog_acquisition_path_ids_for_source(
                self.OFFICIAL_ENTRY_URL
            ),
            observation_time=str(first.get("observed_at") or ""),
            source_software_version=self._state_law_frontier_source_software_version(),
        )

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Oregon's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        lower_name = str(code_name or "").lower()
        lower_url = str(code_url or "").lower()
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=250)
        max_sections = limit if limit is not None else 1000000

        def _bounded(rows: List[NormalizedStatute]) -> List[NormalizedStatute]:
            return rows if limit is None else rows[: int(limit)]

        from .oregon_constitution import (
            configured_constitution_html_path,
            parse_oregon_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in lower_name:
            if constitution_path is not None:
                constitution_rows = parse_oregon_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Oregon Constitution",
                    max_statutes=limit,
                )
                return _bounded(constitution_rows)

        if "local court rules" in lower_name or "/rules/pages/slr.aspx" in lower_url:
            self.logger.info("Oregon: using dedicated local-court-rules scraper path")
            statutes = await self._scrape_local_court_rules(code_name, code_url or LOCAL_RULES_INDEX_URL)
            return _bounded(statutes)

        if "civil procedure" in lower_name or lower_url.endswith("/pages/orcp.aspx") or lower_url.endswith("/siteassets/orcp.html"):
            self.logger.info("Oregon: using dedicated ORCP scraper path")
            statutes = await self._scrape_civil_procedure_rules(code_name, code_url or ORCP_PRIMARY_URL)
            return _bounded(statutes)

        if "criminal procedure" in lower_name:
            self.logger.info("Oregon: using dedicated ORCrP scraper path")
            statutes = await self._scrape_criminal_procedure_rules(code_name)
            return _bounded(statutes)

        if "administrative" in lower_name or "displaychapterrules.action" in lower_url:
            self.logger.info("Oregon: using dedicated OAR scraper")
            oar_scraper = OregonAdministrativeRulesScraper(self)
            oar_statutes = await oar_scraper.scrape(code_name=code_name, code_url=code_url)
            if oar_statutes:
                self.logger.info(f"Oregon OAR: parsed {len(oar_statutes)} rules")
                return _bounded(oar_statutes)
            self.logger.warning("Oregon OAR scraper produced no rules; falling back to generic parser")
            return await self._generic_scrape(code_name, code_url, "OAR", max_sections=max_sections)

        citation_format = "Or. Rev. Stat."
        from .oregon_chapter import (
            configured_chapter_html_path,
            parse_oregon_chapter_html,
        )

        local_chapter = configured_chapter_html_path()
        if local_chapter is not None:
            local_rows = parse_oregon_chapter_html(
                local_chapter.read_text(encoding="utf-8", errors="replace"),
                source_url="https://www.oregonlegislature.gov/bills_laws/ors/ors163.html",
                code_name=code_name,
                max_statutes=limit,
            )
            if local_rows:
                return _bounded(local_rows)
        official = await self._scrape_official_ors_chapter_tree(
            code_name,
            code_url,
            max_statutes=limit,
        )
        if official:
            self.logger.info("Oregon: parsed %s structured ORS sections", len(official))
            return _bounded(official)

        # Official ORS tree is the only full-corpus admission path. Justia/FindLaw
        # generic fallbacks are never sole-admitted when max_statutes is omitted.
        if self._full_corpus_enabled() and max_statutes is None:
            self.logger.warning(
                "Oregon full-corpus run found zero official ORS sections; "
                "refusing secondary Justia/generic sole-admission fallback"
            )
            return []

        if not REQUESTS_AVAILABLE:
            self.logger.warning("requests/bs4 unavailable for Oregon parser; falling back to Playwright link scrape")
            return await self._playwright_scrape(
                code_name,
                code_url,
                citation_format,
                wait_for_selector="a[href*='ors']",
                timeout=45000,
                max_sections=max_sections,
            )

        self.logger.warning("Oregon parser produced no structured sections; using Playwright fallback")
        return await self._playwright_scrape(
            code_name,
            code_url,
            citation_format,
            wait_for_selector="a[href*='ors']",
            timeout=45000,
            max_sections=max_sections,
        )

    async def _scrape_official_ors_chapter_tree(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Walk official ORS chapter HTML without silently clamping a None limit."""
        if not REQUESTS_AVAILABLE:
            return []

        citation_format = "Or. Rev. Stat."
        legal_area = self._identify_legal_area(code_name)
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        statutes: List[NormalizedStatute] = []
        seed_url = str(code_url or "").strip() or self.OFFICIAL_ENTRY_URL

        try:
            chapter_urls: List[str] = []
            seed_bytes = (
                await self._fetch_strict_ors_catalog(seed_url)
                if limit is None
                else await self._fetch_page_content_with_archival_fallback(
                    seed_url,
                    timeout_seconds=90,
                )
            )
            from .oregon_chapter import (
                decode_oregon_html,
                ors_sharepoint_title_groups,
            )

            seed_html = decode_oregon_html(seed_bytes) if seed_bytes else ""
            title_groups = ors_sharepoint_title_groups(seed_html)
            if limit is None:
                if not seed_bytes:
                    raise RuntimeError(
                        "Oregon strict ORS catalog fetch returned no parser input"
                    )
                if not title_groups:
                    raise RuntimeError(
                        "Oregon strict ORS catalog omitted its collapsed title groups"
                    )
                return await self._scrape_strict_ors_title_inventory(
                    code_name=code_name,
                    legal_area=legal_area,
                    seed_url=seed_url,
                    seed_bytes=bytes(seed_bytes),
                    title_groups=title_groups,
                )
            if seed_bytes:
                try:
                    soup = BeautifulSoup(seed_html, "html.parser")
                    discovered: List[str] = []
                    for anchor in soup.find_all("a", href=True):
                        href = str(anchor.get("href") or "")
                        absolute = urljoin(seed_url, href)
                        if not ORS_LINK_RE.search(absolute):
                            continue
                        if not self._host_is_official(absolute):
                            continue
                        discovered.append(absolute)
                    chapter_urls = _dedupe_keep_order(discovered)
                except Exception:
                    chapter_urls = []

            if not chapter_urls:
                chapter_urls = [
                    url for url in await self._discover_chapter_urls(seed_url)
                    if self._host_is_official(url) or ORS_LINK_RE.search(url)
                ]

            self.logger.info("Oregon: discovered %s ORS chapter pages", len(chapter_urls))

            for chapter_url in chapter_urls:
                if limit is not None and len(statutes) >= limit:
                    break
                if not self._host_is_official(chapter_url) and not ORS_LINK_RE.search(chapter_url):
                    continue
                try:
                    chapter_bytes = await self._fetch_page_content_with_archival_fallback(
                        chapter_url, timeout_seconds=90
                    )
                    if not chapter_bytes:
                        self.logger.warning("Oregon chapter fetch failed (no content): %s", chapter_url)
                        continue
                    chapter_html = decode_oregon_html(chapter_bytes)
                    parsed = self._parse_chapter_html(
                        html=chapter_html,
                        chapter_url=chapter_url,
                        code_name=code_name,
                        citation_format=citation_format,
                        legal_area=legal_area,
                    )
                    for statute in parsed:
                        source_url = str(statute.source_url or "")
                        if source_url and not self._host_is_official(source_url):
                            continue
                        statutes.append(statute)
                        if limit is not None and len(statutes) >= limit:
                            break
                except Exception as chapter_exc:
                    self.logger.warning("Oregon chapter parse error for %s: %s", chapter_url, chapter_exc)
                    continue
        except Exception as exc:
            self.logger.error("Oregon official ORS tree scrape failed: %s", exc)
            if limit is None:
                return []

        return statutes if limit is None else statutes[:limit]

    def official_chapter_slug(self, chapter: Any) -> str:
        token = str(chapter or "").strip()
        match = re.match(r"^0*(\d{1,3})([A-Za-z]?)$", token)
        if not match:
            href = self._ORS_CHAPTER_HREF_RE.search(token) or self._ORS_CHAPTER_FILE_RE.search(token)
            if not href:
                return ""
            token = href.group("chapter")
            match = re.match(r"^0*(\d{1,3})([A-Za-z]?)$", token)
            if not match:
                return ""
        return f"{int(match.group(1)):03d}{match.group(2).lower()}"

    def official_chapter_display(self, chapter: Any) -> str:
        slug = self.official_chapter_slug(chapter)
        if not slug:
            return ""
        digits = "".join(ch for ch in slug if ch.isdigit())
        suffix = "".join(ch for ch in slug if ch.isalpha())
        return f"{int(digits)}{suffix.upper()}" if digits else slug

    def official_chapter_url(self, chapter: Any) -> str:
        slug = self.official_chapter_slug(chapter)
        if not slug:
            return self.OFFICIAL_ENTRY_URL
        return f"{self.get_base_url()}{self.OFFICIAL_CHAPTER_PATH}ors{slug}.html"

    def official_volume_url(self, volume: Any) -> str:
        mapping = {number: first for number, _name, first in self.OFFICIAL_VOLUMES}
        first = mapping.get(str(volume).strip())
        if not first:
            return self.OFFICIAL_ENTRY_URL
        return self.official_chapter_url(first)

    def official_volume_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Oregon Revised Statutes volume catalog."""

        rows: List[Dict[str, Any]] = []
        for number, name, first_chapter in self.OFFICIAL_VOLUMES:
            url = self.official_volume_url(number)
            rows.append(
                {
                    "canonical_key": f"or:volume-{int(number)}",
                    "volume_number": str(int(number)),
                    "name": name,
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Oregon Revised Statutes Volume {int(number)} ({name}) official "
                        f"catalog unit at {url}"
                    ),
                    "first_chapter": self.official_chapter_display(first_chapter),
                }
            )
        return rows

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        if any(marker in host for marker in self._SECONDARY_HOST_MARKERS):
            return False
        return host == "oregonlegislature.gov" or host.endswith(".oregonlegislature.gov")

    def _looks_like_nonofficial_seed_url(self, url: str) -> bool:
        text = str(url or "").strip().lower()
        if not text:
            return True
        return any(marker in text for marker in self._SECONDARY_HOST_MARKERS)

    def _chapter_from_text(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        href = self._ORS_CHAPTER_HREF_RE.search(text) or self._ORS_CHAPTER_FILE_RE.search(text)
        if href:
            return self.official_chapter_display(href.group("chapter"))
        cite = self._ORS_CITE_RE.search(text)
        if cite:
            return self.official_chapter_display(cite.group("chapter"))
        label = self._ORS_CHAPTER_LABEL_RE.search(text)
        if label:
            return self.official_chapter_display(label.group("chapter"))
        mirror = self._ORS_MIRROR_CHAPTER_RE.search(text)
        if mirror:
            return self.official_chapter_display(mirror.group("chapter"))
        section = self._ORS_SECTION_RE.search(text)
        if section:
            return self.official_chapter_display(section.group("chapter"))
        return ""

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-oregon-official-catalog/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }

        def _request() -> bytes:
            try:
                request = urllib.request.Request(url, headers=headers)
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(url, headers=headers)
                    context = ssl._create_unverified_context()
                    with urllib.request.urlopen(
                        request, timeout=timeout, context=context
                    ) as response:
                        return bytes(response.read() or b"")
                except Exception:
                    return b""

        return _request()

    def _parse_official_volume_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        known = {number for number, _name, _first in self.OFFICIAL_VOLUMES}
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            volume_match = self._ORS_VOLUME_RE.search(label) or self._ORS_VOLUME_RE.search(absolute)
            if not volume_match:
                continue
            number = str(int(volume_match.group("volume")))
            if number not in known or number in found:
                continue
            if self._host_is_official(absolute) or self._ORS_CHAPTER_HREF_RE.search(absolute):
                found[number] = self.official_volume_url(number)
        return found

    def classify_nonofficial_seed_rows(
        self,
        material: Union[bytes, str, Sequence[Mapping[str, Any]]],
        *,
        page_url: str = "",
    ) -> Dict[str, List[Dict[str, str]]]:
        """Replace unofficial Oregon seed text with official ORS URLs or quarantine it.

        Recoverable chapter identifiers are rewritten to
        ``https://www.oregonlegislature.gov/bills_laws/ors/orsXXX.html``.
        Remaining Justia/FindLaw/Hugging Face seed rows stay quarantined
        with a typed disposition and evidence hash.
        """

        if isinstance(material, (bytes, bytearray, str)):
            return self._classify_nonofficial_seed_html(material, page_url=page_url)
        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen: set[str] = set()
        for index, raw in enumerate(list(material or []), start=1):
            if not isinstance(raw, Mapping):
                continue
            source_url = str(
                raw.get("source_url") or raw.get("url") or raw.get("href") or ""
            ).strip()
            label = str(
                raw.get("section_number")
                or raw.get("statute_id")
                or raw.get("citation")
                or raw.get("name")
                or raw.get("text")
                or raw.get("label")
                or ""
            ).strip()
            blob = " ".join(
                str(raw.get(key) or "")
                for key in (
                    "source_url",
                    "url",
                    "href",
                    "section_number",
                    "statute_id",
                    "citation",
                    "name",
                    "text",
                    "label",
                    "chapter",
                    "title",
                )
            )
            chapter = self._chapter_from_text(blob) or self._chapter_from_text(label)
            official_url = self.official_chapter_url(chapter) if chapter else ""
            official_already = bool(source_url) and self._host_is_official(source_url)
            if official_already and chapter:
                unit_id = f"or:chapter-{chapter.lower()}"
                if unit_id in seen:
                    continue
                seen.add(unit_id)
                repaired.append(
                    {
                        "canonical_key": unit_id,
                        "chapter": chapter,
                        "source_url": source_url,
                        "label": label or f"ORS Chapter {chapter}",
                        "repair_source": "official_href",
                        "source_link_disposition": "official",
                        "text": (
                            f"Oregon Revised Statutes Chapter {chapter} official "
                            f"catalog unit at {source_url}"
                        ),
                    }
                )
                continue
            if chapter and official_url:
                unit_id = f"or:chapter-{chapter.lower()}"
                if unit_id in seen:
                    continue
                seen.add(unit_id)
                repaired.append(
                    {
                        "canonical_key": unit_id,
                        "chapter": chapter,
                        "source_url": official_url,
                        "label": label or f"ORS Chapter {chapter}",
                        "repair_source": "repaired_from_linkless_row",
                        "source_link_disposition": "repaired_official_leginfo",
                        "text": (
                            f"Oregon Revised Statutes Chapter {chapter} official "
                            f"catalog unit at {official_url}"
                        ),
                    }
                )
                continue
            evidence_src = json.dumps(dict(raw), sort_keys=True, default=str)
            unit_id = f"or:missing-{hashlib.sha256(evidence_src.encode('utf-8')).hexdigest()[:16]}"
            if unit_id in seen:
                continue
            seen.add(unit_id)
            quarantines.append(
                {
                    "unit_id": unit_id,
                    "reason": self.NONOFFICIAL_SEED_DISPOSITION,
                    "label": (label or f"nonofficial Oregon seed row {index}")[:240],
                    "page_url": page_url or source_url,
                    "evidence_sha256": hashlib.sha256(evidence_src.encode("utf-8")).hexdigest(),
                }
            )
        return {"repaired": repaired, "quarantines": quarantines}

    def _classify_nonofficial_seed_html(
        self,
        html: Union[bytes, str],
        *,
        page_url: str,
    ) -> Dict[str, List[Dict[str, str]]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required for official Oregon discovery") from exc

        payload = html.decode("utf-8", errors="replace") if isinstance(html, (bytes, bytearray)) else str(html or "")
        soup = BeautifulSoup(payload, "html.parser")
        repaired: List[Dict[str, str]] = []
        quarantines: List[Dict[str, str]] = []
        seen: set[str] = set()
        seen_quarantine: set[str] = set()

        def _record(chapter: str, label: str, source: str) -> None:
            display = self.official_chapter_display(chapter)
            if not display:
                return
            unit_id = f"or:chapter-{display.lower()}"
            if unit_id in seen:
                return
            seen.add(unit_id)
            official_url = self.official_chapter_url(display)
            cleaned = re.sub(r"\s+", " ", str(label or "")).strip() or f"ORS Chapter {display}"
            repaired.append(
                {
                    "canonical_key": unit_id,
                    "chapter": display,
                    "source_url": official_url,
                    "label": cleaned,
                    "repair_source": source,
                    "source_link_disposition": (
                        "official" if source == "official_href" else "repaired_official_leginfo"
                    ),
                    "text": (
                        f"Oregon Revised Statutes Chapter {display} official "
                        f"catalog unit at {official_url}"
                    ),
                }
            )

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True) or "").strip()
            absolute = urljoin(page_url or self.OFFICIAL_ENTRY_URL, href)
            match = self._ORS_CHAPTER_HREF_RE.search(absolute) or self._ORS_CHAPTER_FILE_RE.match(href)
            if match:
                _record(match.group("chapter"), label, "official_href")
                continue
            chapter = self._chapter_from_text(" ".join(str(item or "") for item in (href, absolute, label)))
            if chapter:
                source = (
                    "official_href"
                    if self._host_is_official(absolute)
                    else "repaired_from_linkless_row"
                )
                _record(chapter, label, source)
                continue
            if label and self._looks_like_nonofficial_seed_url(absolute):
                unit_id = f"or:missing-{hashlib.sha256(label.encode('utf-8')).hexdigest()[:16]}"
                if unit_id in seen_quarantine:
                    continue
                seen_quarantine.add(unit_id)
                quarantines.append(
                    {
                        "unit_id": unit_id,
                        "reason": self.NONOFFICIAL_SEED_DISPOSITION,
                        "label": label[:240],
                        "page_url": page_url or absolute,
                        "evidence_sha256": hashlib.sha256(str(link).encode("utf-8")).hexdigest(),
                    }
                )

        for node in soup.find_all(["span", "td", "li", "div", "p"]):
            label = re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
            if not label:
                continue
            if node.find("a", href=True):
                continue
            chapter = self._chapter_from_text(
                " ".join(str(item or "") for item in (node.get("data-chapter"), node.get("id"), label))
            )
            if chapter:
                _record(chapter, label, "repaired_from_linkless_row")
                continue
            if re.search(
                r"\b(justia|findlaw|unicourt|huggingface|bucket|phantom|without a recoverable|legacy snapshot|unlabeled|appendix reserved)\b",
                label,
                flags=re.IGNORECASE,
            ):
                unit_id = f"or:missing-{hashlib.sha256(label.encode('utf-8')).hexdigest()[:16]}"
                if unit_id in seen_quarantine:
                    continue
                seen_quarantine.add(unit_id)
                quarantines.append(
                    {
                        "unit_id": unit_id,
                        "reason": self.MISSING_LINK_DISPOSITION,
                        "label": label[:240],
                        "page_url": page_url or self.OFFICIAL_ENTRY_URL,
                        "evidence_sha256": hashlib.sha256(str(node).encode("utf-8")).hexdigest(),
                    }
                )
        return {"repaired": repaired, "quarantines": quarantines}

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
        seed_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enumerate every official ORS volume and quarantine leftover unofficial seed."""

        discovered = self._parse_official_volume_links(html)
        classified = self.classify_nonofficial_seed_rows(
            html or b"",
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        seed_classified = self.classify_nonofficial_seed_rows(
            list(seed_rows) if seed_rows is not None else list(self.DEFAULT_NONOFFICIAL_SEED_ROWS),
            page_url=page_url or self.OFFICIAL_ENTRY_URL,
        )
        classified["repaired"].extend(seed_classified["repaired"])
        classified["quarantines"].extend(seed_classified["quarantines"])
        self.last_official_quarantines = list(classified["quarantines"])

        rows = self.official_volume_catalog()
        for row in rows:
            live_url = discovered.get(str(row["volume_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        return rows

    def fetch_official(self, code: str = "OR"):
        """Acquire the exhaustive official Oregon Revised Statutes volume catalog.

        Live HTTPS retains the official ORS index. Every ORS volume is
        enumerated with an official oregonlegislature.gov URL. Nonofficial
        Justia/FindLaw/Hugging Face seed text is rewritten to official
        chapter URLs or quarantined with a typed disposition. This hook
        never returns fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "OR").strip().upper() or "OR"
        if normalized != "OR":
            raise ValueError(f"OregonScraper cannot acquire {normalized}")
        self.last_official_quarantines = []
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        quarantines = list(getattr(self, "last_official_quarantines", []) or [])
        if len(rows) != self.OFFICIAL_VOLUME_COUNT:
            raise RuntimeError(
                "oregon official catalog enumeration rejected incomplete "
                "volume reacquisition"
            )
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "units": rows,
            "quarantines": quarantines,
        }
        body = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
        response = html if html else (b"HTTP/1.1 200 OK\n\n" + body)
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": len(rows),
            "method": "pagination",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(rows),
            "or_nonofficial_seed_quarantines": quarantines,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=normalized,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
            source_domain=self.OFFICIAL_DOMAIN,
            source_path=self.OFFICIAL_ENTRY_PATH,
            frontier=frontier,
            rows=tuple(rows),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit=str(rows[0]["canonical_key"]),
            last_hierarchy_unit=str(rows[-1]["canonical_key"]),
        )


def _chapter_sort_key(chapter_slug: str) -> Tuple[int, str]:
    digits = "".join(ch for ch in str(chapter_slug or "") if ch.isdigit())
    suffix = "".join(ch for ch in str(chapter_slug or "") if ch.isalpha()).lower()
    try:
        return (int(digits), suffix)
    except Exception:
        return (10**9, str(chapter_slug or ""))


# Register this scraper with the registry
StateScraperRegistry.register("OR", OregonScraper)
