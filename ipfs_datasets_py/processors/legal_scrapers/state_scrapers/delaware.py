"""Scraper for Delaware state laws.

Delaware Code Online uses heavy JavaScript rendering.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from ...playwright_limiter import acquire_playwright_slot
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class DelawareScraper(BaseStateScraper):
    """Scraper for Delaware state laws from https://delcode.delaware.gov

    NOTE: Delaware's website is heavily JavaScript-rendered.
    This scraper requires Playwright or returns limited results.
    """

    _DE_CHAPTER_URL_RE = re.compile(
        r"/title\d+/c[0-9][0-9a-z_]*/index\.html$",
        re.IGNORECASE,
    )
    _DE_TITLE_URL_RE = re.compile(r"/title\d+/index\.html$", re.IGNORECASE)
    _DE_TITLE_NUMBER_RE = re.compile(r"/title(\d+)/", re.IGNORECASE)
    _DE_CHAPTER_NUMBER_RE = re.compile(r"/c([0-9][0-9a-z_]*)/", re.IGNORECASE)
    _DE_SECTION_HEAD_RE = re.compile(
        r"§\s*([0-9A-Za-z][0-9A-Za-z,._\-]*)\s*\.\s*(.+)",
        re.IGNORECASE,
    )
    # Retained Delaware pages occasionally preserve an inactive locator with
    # no body and only its exact ordered session-law history.  Keep each
    # exception bound to the exact source, section, heading, and links; a
    # generic heading/history rule could conceal an active heading-only
    # section after upstream markup drift.
    _DE_EXACT_INACTIVE_SESSION_LAW_HISTORIES: ClassVar[
        dict[str, dict[str, Any]]
    ] = {
        # Title 14, Chapter 17 body SHA-256
        # 159693e0c55e2d4cfcb6b440dc1154903e7b1a8f7d1f309f92849ca3d57f2cbc.
        "/title14/c017/index.html": {
            "section_id": "1724",
            "heading": "§ 1724. Academic Achievement Awards Pilot Program.",
            "anchors": (
                (
                    "https://legis.delaware.gov/SessionLaws?volume=77&chapter=196",
                    "77 Del. Laws, c. 196, § 2",
                ),
                (
                    "https://legis.delaware.gov/SessionLaws?volume=1&chapter=2011",
                    "expired, eff. Oct. 1, 2011",
                ),
            ),
        },
        # Title 18, Chapter 70 body SHA-256
        # 632e38d30c6d19d9d6ade8da9a9b3951ceb56a0102646d40cc7b8a1a51a050d8
        # expressly transfers this former locator to active § 2501I of Title
        # 6.  The retained target body SHA-256 is
        # 0cad2afd8d4cb7d39052f960c83a3f79f3cfff7aa7ad24e1faa6c6a7ba979f55.
        "/title18/c070/index.html": {
            "section_id": "7001",
            "heading": (
                "§ 7001. Sealed container defense in product liability "
                "[Transferred to § 2501I of Title 6]."
            ),
            "anchors": (
                (
                    "https://legis.delaware.gov/SessionLaws?volume=66&chapter=45",
                    "66 Del. Laws, c. 45, § 1",
                ),
                (
                    "https://legis.delaware.gov/SessionLaws?volume=70&chapter=186",
                    "70 Del. Laws, c. 186, § 1",
                ),
            ),
        },
        # Title 21, Chapter 71 body SHA-256
        # 3ea1009aa37ed527d9bd770aefabb7ce7ae4771c85a9d2a39348e0360224d2db
        # retains § 7102 only as an exact omitted locator.  The current
        # authenticated Title 21 PDF independently prints the same heading
        # and sole 72 Del. Laws, c. 456, § 1 history with no provision text.
        "/title21/c071/index.html": {
            "section_id": "7102",
            "heading": "§ 7102. [Omitted].",
            "anchors": (
                (
                    "https://legis.delaware.gov/SessionLaws?volume=72&chapter=456",
                    "72 Del. Laws, c. 456, § 1",
                ),
            ),
        },
        # Title 30, Chapter 54, Subchapter I body SHA-256
        # a8729f94aa04be556a69a69bccd166e0abeb3f2b5cfc9476f18504b845dc8e11
        # retains § 5415 as a heading-only former distribution provision.
        # Its complete ordered history expressly expired the provision on
        # July 1, 1988.  Keep this exception exact rather than treating every
        # Delaware ``expired by`` history as a terminal disposition.
        "/title30/c054/sc01/index.html": {
            "section_id": "5415",
            "heading": "§ 5415. Distribution of tax receipts.",
            "anchors": (
                (
                    "https://legis.delaware.gov/SessionLaws?volume=66&chapter=94",
                    "66 Del. Laws, c. 94, § 1",
                ),
                (
                    "https://legis.delaware.gov/SessionLaws?volume=66&chapter=94",
                    (
                        "expired by 66 Del. Laws, c. 94, § 2, eff. July 1, "
                        "1988"
                    ),
                ),
            ),
        },
    }
    # Title 30, Chapter 20D is retained as a complete expired-code frontier:
    # the official parent labels it ``[Expired]`` and the retained chapter
    # body (SHA-256
    # a0473a14210c770b0c3fe71c3e3c616c9048971d915171ca934a8b5d6fddc4ff)
    # publishes ten heading-only former locators.  Each locator ends in the
    # same express Jan. 1, 2022 expiration history.  Bind the reconciliation
    # to the complete page boundary so a generic ``expired by`` rule cannot
    # hide a changed or newly substantive section.
    _DE_EXACT_INACTIVE_CHAPTER_HISTORIES: ClassVar[
        dict[str, dict[str, Any]]
    ] = {
        "/title30/c020d/index.html": {
            "headings": (
                ("h1", "TITLE 30"),
                ("h4", "State Taxes"),
                ("h2", "Income, Inheritance and Estate Taxes"),
                (
                    "h3",
                    (
                        "CHAPTER 20D. Angel Investor Job Creation and "
                        "Innovation Act [Expired]"
                    ),
                ),
                ("h4", ""),
            ),
            "sections": (
                (
                    "20D-101",
                    "§ 20D-101. Definitions.",
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=374",
                            "81 Del. Laws, c. 374, § 53",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
                (
                    "20D-102",
                    "§ 20D-102. Certification of qualified small businesses.",
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
                (
                    "20D-103",
                    "§ 20D-103. Certification of qualified investors.",
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
                (
                    "20D-104",
                    "§ 20D-104. Certification of qualified funds.",
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
                (
                    "20D-105",
                    "§ 20D-105. Tax credit allowed.",
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
                (
                    "20D-106",
                    (
                        "§ 20D-106. Issuance of tentative and final tax "
                        "credit certificates."
                    ),
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
                (
                    "20D-107",
                    "§ 20D-107. Required reports.",
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
                (
                    "20D-108",
                    "§ 20D-108. Revocation of tax credits.",
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
                (
                    "20D-109",
                    "§ 20D-109. Data privacy.",
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
                (
                    "20D-110",
                    (
                        "§ 20D-110. Angel Investor Job Creation and "
                        "Innovation Act Administration Fund."
                    ),
                    (
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            "81 Del. Laws, c. 244, § 3",
                        ),
                        (
                            "https://legis.delaware.gov/SessionLaws?volume=81&chapter=244",
                            (
                                "expired by 81 Del. Laws, c. 244, § 5, "
                                "eff. Jan. 1, 2022"
                            ),
                        ),
                    ),
                ),
            ),
        },
    }
    # Delaware's 2026 banking-code update left the former Subchapter VII
    # locator as a citation-only editorial placeholder and published the
    # amended sections at the sibling ``sc07_1`` locator.  This is not a
    # general empty-page exemption: admission below also requires the exact
    # official amendment citation and the replacement link in the same parent
    # frontier.
    _DE_SUPERSEDED_EMPTY_INDEXES: ClassVar[dict[str, dict[str, Any]]] = {
        "/title5/c007/sc07/index.html": {
            "replacement_path": "/title5/c007/sc07_1/index.html",
            "heading": "Subchapter VII. Merger or Consolidation with Out-Of-State Banks",
            "session_law_volume": "85",
            "session_law_chapter": "337",
            "session_law_section": "12",
        },
        # The retained Title 29, Chapter 102 body (SHA-256
        # 74269ed2f55864fb8004ca5fdacd65bbe749cf4c2c1c79e1b45cd5596e2c1fc8)
        # is the citation-only pre-amendment locator.  Its immediate official
        # parent also publishes c102_1, whose active §§ 10201-10219 implement
        # 85 Del. Laws, c. 263.  Require the exact complete source heading
        # boundary, amendment citation, and sibling replacement together.
        "/title29/c102/index.html": {
            "replacement_path": "/title29/c102_1/index.html",
            "headings": (
                ("h1", "TITLE 29"),
                ("h4", "State Government"),
                ("h2", "General Regulations for State Agencies"),
                (
                    "h3",
                    "CHAPTER 102. Delaware Legislative Oversight and Sunset Act",
                ),
                ("h4", ""),
            ),
            "session_law_volume": "85",
            "session_law_chapter": "263",
            "session_law_section": "5",
            "requires_empty_section_navigation": True,
        },
    }
    # The official Title 16 frontier retains Chapter 9A as an exact omitted,
    # citation-only locator.  Retained page body SHA-256:
    # 231b794859b15e45b9b411f6bba713a665a835ae80a648b55fb6af6ca229e077.
    # Admission requires the complete parent/page heading boundary, empty
    # section navigation, and the exact official session-law citation.
    _DE_OMITTED_CITATION_ONLY_INDEXES: ClassVar[
        dict[str, dict[str, Any]]
    ] = {
        "/title16/c009a/index.html": {
            "parent_heading": "Chapter 9A. [Omitted.]",
            "headings": (
                ("h1", "TITLE 16"),
                ("h4", "Health and Safety"),
                ("h2", "Regulatory Provisions Concerning Public Health"),
                ("h3", "CHAPTER 9A. [Omitted.]"),
                ("h4", ""),
            ),
            "citation_url": (
                "https://legis.delaware.gov/SessionLaws?volume=81&chapter=257"
            ),
            "citation_text": "81 Del. Laws, c. 257, § 1",
        }
    }
    # Title 16, Chapter 105 is the Code's unique citation-only relocation
    # stub.  Its retained body (SHA-256
    # b157b2d0597eeed61813c8402beba2b4fe973ada658a037b0b22c8eeed1f961b)
    # directs readers to the enacted §§ 1180-1183 frontier under Chapter 11,
    # Subchapter VIII (retained target body SHA-256
    # 9a778b1e17720a9cb0d3ca36cf4630d34bd0d22bf60aa2611165ec4230fc81c2).
    _DE_RELOCATED_CITATION_ONLY_INDEXES: ClassVar[
        dict[str, dict[str, Any]]
    ] = {
        "/title16/c105/index.html": {
            "parent_heading": (
                "Chapter 105. Nursing Facility Quality Assessment Fund"
            ),
            "headings": (
                ("h1", "TITLE 16"),
                ("h4", "Health and Safety"),
                ("h2", "Community Firearm Recovery Program"),
                (
                    "h3",
                    "CHAPTER 105. Nursing Facility Quality Assessment Fund",
                ),
                ("h4", ""),
            ),
            "target_url": (
                "https://delcode.delaware.gov/title16/c011/sc08/index.html"
            ),
            "citation_text": (
                "See subchapter VIII of Chapter 11 of this title, §§ 1180 of "
                "this title et seq., for the Nursing Facility Quality "
                "Assessment Fund as enacted by 78 Del. Laws, c. 286, § 2, "
                "effective June 28, 2012."
            ),
        }
    }
    # Title 19 retains the former Chapter 26 locator after the same enacted
    # provisions moved to active Title 18, Chapter 26.  The retained source
    # body (SHA-256
    # 4178618295fb5aa5b50bebcc4109b0d0c5cc9efeb788ec84a88e0c1c938d2e36)
    # is structurally empty.  The current authenticated Title 19 PDF likewise
    # prints this heading alone on page 125 and immediately begins Part III on
    # the next page.  The retained active Title 18 target body (SHA-256
    # ee9b6d54eb7fcad0272f90b7ec3ba866541366584bf5030d70dee62ddb2e36b4)
    # publishes 23 active sections through § 2624 (with § 2622 repealed) and
    # preserves the originating 69 Del. Laws, c. 163 history.  Admission
    # remains bound to every exact source boundary.
    _DE_AUTHENTICATED_EMPTY_RELOCATED_INDEXES: ClassVar[
        dict[str, dict[str, Any]]
    ] = {
        "/title19/c026/index.html": {
            "parent_heading": "Chapter 26. Workmen's Compensation Rating",
            "headings": (
                ("h1", "TITLE 19"),
                ("h4", "Labor"),
                ("h2", "Workers' Compensation"),
                ("h3", "CHAPTER 26. Workmen's Compensation Rating"),
                ("h4", ""),
            ),
            "target_url": (
                "https://delcode.delaware.gov/title18/c026/index.html"
            ),
        }
    }
    # Delaware's authenticated publications preserve a few heading-only
    # editorial locators after an act vacated the underlying unit in full.
    # 70 Del. Laws, c. 86, § 3 replaced UCC Article 3 with text ending at Part
    # 6.  81 Del. Laws, c. 1, § 2 deleted Title 12, Chapter 11, Subchapters II,
    # III, and IV and enacted the reorganized law under Subchapter II.  The
    # current Title 12 publication retains the former III and IV headings.
    # Admission is limited to the exact paths and heading sequences below;
    # ``_verified_legislatively_vacated_index`` also requires a truly empty
    # CodeBody and discovery in the immediate official parent frontier.
    _DE_LEGISLATIVELY_VACATED_EMPTY_INDEXES: Dict[str, Tuple[str, ...]] = {
        "/title6/c003/sc07/index.html": (
            "TITLE 6",
            "Commerce and Trade",
            "SUBTITLE I",
            "Uniform Commercial Code",
            "ARTICLE 3. Negotiable Instruments",
            "Part 7",
            "Advice of International Sight Draft",
        ),
        "/title6/c003/sc08/index.html": (
            "TITLE 6",
            "Commerce and Trade",
            "SUBTITLE I",
            "Uniform Commercial Code",
            "ARTICLE 3. Negotiable Instruments",
            "Part 8",
            "Miscellaneous",
        ),
        "/title12/c011/sc03/index.html": (
            "TITLE 12",
            "Decedents’ Estates and Fiduciary Relations",
            "Descent and Distribution; Escheat",
            "CHAPTER 11. Escheats",
            "Subchapter III. Unclaimed Life Insurance Funds",
        ),
        "/title12/c011/sc04/index.html": (
            "TITLE 12",
            "Decedents’ Estates and Fiduciary Relations",
            "Descent and Distribution; Escheat",
            "CHAPTER 11. Escheats",
            "Subchapter IV. Other Unclaimed Property",
        ),
        # The official Title 14 frontier retains Chapter 94 only as an exact
        # heading-level transfer marker; the enacted text now lives in
        # Chapter 81.  Retained body SHA-256:
        # 61793cf66a801c28e7a7f4c6af037fc56478608843649dcd50248e1d5b0caf95.
        "/title14/c094/index.html": (
            "TITLE 14",
            "Education",
            "Hazing",
            "CHAPTER 94. Education Privacy Act "
            "[Transferred to Chapter 81 of this title.]",
            "",
        ),
    }
    # The currently effective Title 13, Chapter 8 publication is an editorial
    # index at ``c008_1`` whose nine enacted subchapter pages deliberately live
    # below the sibling physical directory ``c008/scNN_1``.  A generic sibling
    # traversal would be unsafe, so this exception is bound to the exact
    # official parent/page headings and complete retained child frontier.  The
    # future-effective ``c008`` locator must also be present in the immediate
    # title frontier, proving that ``c008_1`` is the official current-version
    # index rather than an arbitrary off-tree redirect.
    _DE_REDIRECTED_DESCENDANT_INDEXES: ClassVar[dict[str, dict[str, Any]]] = {
        "/title13/c008_1/index.html": {
            "parent_heading": (
                "Chapter 8. Uniform Parentage Act "
                "[Effective until Dec. 6, 2026]."
            ),
            "page_heading": (
                "Uniform Parentage Act [Effective until Dec. 6, 2026]."
            ),
            "breadcrumb": "Title 13 > Chapter 8",
            "required_sibling_path": "/title13/c008/index.html",
            "children": (
                (
                    "/title13/c008/sc01_1/index.html",
                    (
                        "Subchapter I. General Provisions "
                        "[Effective until Dec. 6, 2026]."
                    ),
                ),
                (
                    "/title13/c008/sc02_1/index.html",
                    (
                        "Subchapter II. Parent-Child Relationship "
                        "[Effective until Dec. 6, 2026]."
                    ),
                ),
                (
                    "/title13/c008/sc03_1/index.html",
                    (
                        "Subchapter III. Voluntary Acknowledgement of Paternity "
                        "[Effective until Dec. 6, 2026]."
                    ),
                ),
                (
                    "/title13/c008/sc04_1/index.html",
                    (
                        "Subchapter IV. Registry of Paternity "
                        "[Effective until Dec. 6, 2026]."
                    ),
                ),
                (
                    "/title13/c008/sc05_1/index.html",
                    (
                        "Subchapter V. Genetic Testing "
                        "[Effective until Dec. 6, 2026]."
                    ),
                ),
                (
                    "/title13/c008/sc06_1/index.html",
                    (
                        "Subchapter VI. Proceeding to Adjudicate Parentage "
                        "[Effective until Dec. 6, 2026]."
                    ),
                ),
                (
                    "/title13/c008/sc07_1/index.html",
                    (
                        "Subchapter VII. Child of Assisted Reproduction "
                        "[Effective until Dec. 6, 2026]."
                    ),
                ),
                (
                    "/title13/c008/sc08_1/index.html",
                    (
                        "Subchapter VIII. Gestational Carrier Agreement Act "
                        "[Effective until Dec. 6, 2026]."
                    ),
                ),
                (
                    "/title13/c008/sc09_1/index.html",
                    (
                        "Subchapter IX. Miscellaneous Provisions "
                        "[Effective until Dec. 6, 2026]."
                    ),
                ),
            ),
        }
    }
    OFFICIAL_DOMAIN = "delcode.delaware.gov"
    OFFICIAL_ENTRY_PATH = "/index.html"
    OFFICIAL_ENTRY_URL = "https://delcode.delaware.gov/index.html"
    OFFICIAL_TITLE_COUNT = 31

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            name = str(statute.section_name or "")
            source = str(statute.source_url or "")
            if source.lower().endswith(".pdf"):
                continue
            # Accept real section captures and skip title-level landing pages.
            if re.search(r"§\s*\d", name, re.IGNORECASE) or re.search(
                r"\b\d+\.[0-9A-Za-z\-]*", name
            ):
                filtered.append(statute)
                continue
            if re.search(r"#\d+[A-Za-z\-]*$", source):
                filtered.append(statute)
                continue
            if self._DE_CHAPTER_URL_RE.search(source) and re.search(
                r"^Chapter\s+\d+", name, re.IGNORECASE
            ):
                if str(statute.section_number or "").startswith("Section-"):
                    m = re.search(r"Chapter\s+(\d+[A-Za-z\-]*)", name, re.IGNORECASE)
                    if m:
                        statute.section_number = m.group(1)
                filtered.append(statute)
                continue
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for Delaware's legislative website."""
        return "https://delcode.delaware.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Delaware."""
        return [
            {"name": "Delaware Code", "url": f"{self.get_base_url()}/index.html", "type": "Code"}
        ]

    async def _fetch_official_de_html(self, url: str, timeout_seconds: int = 6) -> str:
        timeout = max(1, int(timeout_seconds or 6))
        payload = await self._fetch_parser_input_with_transport(
            url,
            headers={
                "User-Agent": "ipfs-datasets-delaware-code-scraper/2.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            timeout_seconds=timeout,
            allow_archival_fallback=True,
            media_type="text/html",
            provider="requests_direct",
        )
        return payload.decode("utf-8", errors="replace") if payload else ""

    def _title_number_from_url(self, url: str) -> str:
        match = self._DE_TITLE_NUMBER_RE.search(str(url or ""))
        return match.group(1) if match else ""

    def _chapter_number_from_url(self, url: str) -> str:
        match = self._DE_CHAPTER_NUMBER_RE.search(str(url or ""))
        if not match:
            return ""
        value = match.group(1)
        digits = re.match(r"0*(\d+)(.*)", value, re.IGNORECASE)
        if not digits:
            return value.upper()
        return f"{int(digits.group(1))}{digits.group(2).upper()}"

    async def _discover_title_links(self) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/index.html"
        html = await self._fetch_official_de_html(index_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            href = urljoin(index_url, str(anchor.get("href") or "").strip())
            if not self._DE_TITLE_URL_RE.search(href):
                continue
            if not label.lower().startswith("title "):
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append((href, label))
        return out

    async def _discover_chapter_links(
        self,
        title_url: str,
        *,
        _html: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = _html
        if html is None:
            html = await self._fetch_official_de_html(title_url)
        if not html:
            return []
        from .delaware_chapter import title_link_rows

        structured = title_link_rows(html, base_url=title_url)
        chapter_rows = [
            (row["url"], row["name"])
            for row in structured
            if self._DE_CHAPTER_URL_RE.search(str(row.get("url") or ""))
        ]
        if chapter_rows:
            return chapter_rows
        soup = BeautifulSoup(html, "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
            href = urljoin(title_url, str(anchor.get("href") or "").strip())
            if not self._DE_CHAPTER_URL_RE.search(href):
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append((href, label))
        return out

    async def _fetch_de_html_frontier(
        self,
        urls: List[str],
        *,
        frontier_name: str,
    ) -> Dict[str, tuple[str, Dict[str, Any], str]]:
        """Fetch one exact Delaware hierarchy wave through grouped recovery."""

        requested = list(urls)
        if not requested:
            return {}
        if len(set(requested)) != len(requested):
            self._fail_full_corpus(
                "Delaware hierarchy frontier contains duplicate URLs",
                frontier_name=frontier_name,
            )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=1,
            timeout_seconds=25,
            headers={
                "User-Agent": "ipfs-datasets-delaware-code-scraper/2.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            content_validator=lambda payload: b"<" in payload[:8192] and b">" in payload[:8192],
            media_type="text/html",
            max_concurrency=8,
            prefer_direct=True,
            wayback_prefix_inventory=True,
        )
        if list(batch.urls) != requested or any(
            len(vector) != len(requested)
            for vector in (
                batch.payloads,
                batch.errors,
                batch.transport_receipts,
                batch.parser_input_envelopes,
            )
        ):
            self._fail_full_corpus(
                "Delaware hierarchy frontier returned unaligned acquisition rows",
                frontier_name=frontier_name,
            )
        failures = [
            {"url": url, "error": error or "empty parser input"}
            for url, payload, error in zip(
                batch.urls, batch.payloads, batch.errors, strict=True
            )
            if error is not None or not payload
        ]
        if failures:
            self._fail_full_corpus(
                "Delaware hierarchy frontier is incomplete",
                frontier_name=frontier_name,
                unresolved_exact_urls=failures,
            )
        out: Dict[str, tuple[str, Dict[str, Any], str]] = {}
        for url, payload, receipt in zip(
            batch.urls,
            batch.payloads,
            batch.transport_receipts,
            strict=True,
        ):
            body = bytes(payload)
            canonical_receipt = dict(receipt) if isinstance(receipt, Mapping) else {}
            provenance = (
                {
                    "content_sha256": hashlib.sha256(body).hexdigest(),
                    "transport_receipt": canonical_receipt,
                }
                if canonical_receipt
                else {}
            )
            out[url] = (
                body.decode("utf-8", errors="replace"),
                provenance,
                str(canonical_receipt.get("source_transport") or "shared_plural"),
            )
        return out

    async def _parse_chapter_sections(
        self,
        *,
        code_name: str,
        chapter_url: str,
        chapter_label: str,
        max_statutes: Optional[int] = None,
        _sibling_frontier_urls: Optional[set[str]] = None,
        _html: Optional[str] = None,
        _page_row_provenance: Optional[Mapping[str, Any]] = None,
        _retrieval_provider: str = "",
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = _html
        if html is None:
            html = await self._fetch_official_de_html(chapter_url)
        if not html:
            if self._full_corpus_enabled() and max_statutes is None:
                self._fail_full_corpus(
                    "Delaware official chapter was unavailable",
                    chapter_url=chapter_url,
                )
            return []
        page_row_provenance = dict(
            _page_row_provenance
            if _page_row_provenance is not None
            else self._last_parser_input_row_provenance()
        )
        if getattr(self, "_state_law_acquisition_ledger", None) is not None:
            receipt = page_row_provenance.get("transport_receipt")
            receipt_url = (
                str(receipt.get("official_url") or "").strip()
                if isinstance(receipt, dict)
                else ""
            )
            if (
                not page_row_provenance
                or receipt_url != str(chapter_url).strip()
            ):
                self._fail_full_corpus(
                    "Delaware chapter rows lack an exact official-byte binding",
                    chapter_url=chapter_url,
                )
        soup = BeautifulSoup(html, "html.parser")
        section_nodes = soup.select("div.Section")
        parsed_chapter_url = urlparse(chapter_url)
        redirected_evidence = (
            self._DE_REDIRECTED_DESCENDANT_INDEXES.get(parsed_chapter_url.path)
            if (parsed_chapter_url.hostname or "").lower() == self.OFFICIAL_DOMAIN
            else None
        )
        if redirected_evidence is not None:
            descendant_pages = self._verified_redirected_descendant_index_links(
                soup,
                page_url=chapter_url,
                chapter_label=chapter_label,
                sibling_frontier_urls=_sibling_frontier_urls or set(),
            )
            if (
                self._full_corpus_enabled()
                and max_statutes is None
                and not descendant_pages
            ):
                self._fail_full_corpus(
                    "Delaware redirected descendant frontier did not close",
                    chapter_url=chapter_url,
                )
        else:
            descendant_pages = self._discover_descendant_index_links(
                html,
                page_url=chapter_url,
            )
        descendant_urls = {url for url, _label in descendant_pages}
        superseded_by_replacement = self._superseded_descendant_pairs(
            descendant_urls
        )
        if self._full_corpus_enabled() and max_statutes is None:
            self._assert_superseded_descendant_pairs_closed(descendant_urls)
        from .delaware_chapter import (
            normalize_delaware_section_number,
            parse_delaware_chapter_html,
        )

        parsed = parse_delaware_chapter_html(
            html,
            source_url=chapter_url,
            code_name=code_name,
            title_number=self._title_number_from_url(chapter_url),
            chapter_number=self._chapter_number_from_url(chapter_url),
            max_statutes=max_statutes,
        )
        statutes: List[NormalizedStatute] = list(parsed)
        for row in statutes:
            row.chapter_name = chapter_label or row.chapter_name

        title_number = self._title_number_from_url(chapter_url)
        chapter_number = self._chapter_number_from_url(chapter_url)
        title_head = soup.select_one("#TitleHead")
        title_name = ""
        if title_head is not None:
            headings = [
                re.sub(r"\s+", " ", h.get_text(" ", strip=True) or "").strip()
                for h in title_head.find_all(["h1", "h2", "h3", "h4"])
            ]
            title_name = " ".join(
                [
                    h
                    for h in headings
                    if h
                    and not h.upper().startswith("TITLE ")
                    and not h.upper().startswith("CHAPTER ")
                ]
            )[:200]

        for section in section_nodes if not parsed else []:
            if max_statutes is not None and len(statutes) >= max_statutes:
                break
            head = section.select_one(".SectionHead")
            if head is None:
                continue
            head_text = re.sub(r"\s+", " ", head.get_text(" ", strip=True) or "").strip()
            match = self._DE_SECTION_HEAD_RE.search(head_text)
            if not match:
                continue
            if self._official_section_is_inactive_without_body(
                section,
                heading=head_text,
                page_url=chapter_url,
            ):
                continue
            section_number = normalize_delaware_section_number(match.group(1))
            section_name = match.group(2).strip()
            section_id = str(head.get("id") or section_number).strip()
            full_url = f"{chapter_url}#{section_id}"
            body_parts = [
                self._normalize_legal_text(child.get_text(" ", strip=True))
                for child in section.find_all("p", recursive=False)
            ]
            full_text = self._normalize_legal_text(
                " ".join(part for part in body_parts if part)
            )
            if not full_text:
                continue

            statutes.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"DE-{title_number}-{section_number}",
                    code_name=code_name,
                    title_number=title_number,
                    title_name=title_name or None,
                    chapter_number=chapter_number,
                    chapter_name=chapter_label,
                    section_number=section_number,
                    section_name=section_name[:200],
                    short_title=section_name[:200],
                    full_text=full_text,
                    legal_area=self._identify_legal_area(section_name),
                    source_url=full_url,
                    official_cite=f"{title_number} Del. C. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_delaware_code_html",
                        "source_authority_class": "official",
                        "discovery_method": "official_title_chapter_index",
                        "chapter_url": chapter_url,
                        "skip_hydrate": True,
                    },
                )
            )

        provider = _retrieval_provider or self._current_fetch_provider() or "unknown"
        for statute in statutes:
            structured_data = dict(statute.structured_data or {})
            if page_row_provenance:
                structured_data.update(
                    {
                        "content_sha256": page_row_provenance["content_sha256"],
                        "transport_receipt": dict(
                            page_row_provenance["transport_receipt"]
                        ),
                    }
                )
            structured_data.update(
                {
                    "retrieval_provider": provider,
                    "retrieval_transport": (
                        "live_https"
                        if provider == "requests_direct"
                        else "durable_cache_or_web_archiving"
                    ),
                }
            )
            statute.structured_data = structured_data

        direct_statutes = list(statutes)
        descendant_statutes: List[NormalizedStatute] = []
        visited_descendants = 0
        descendant_inputs: Dict[str, tuple[str, Dict[str, Any], str]] = {}
        if self._full_corpus_enabled() and max_statutes is None and descendant_pages:
            descendant_inputs = await self._fetch_de_html_frontier(
                [url for url, _label in descendant_pages],
                frontier_name=f"descendants of {chapter_url}",
            )
        for descendant_url, descendant_label in descendant_pages:
            if max_statutes is not None and (
                len(statutes) + len(descendant_statutes) >= max_statutes
            ):
                break
            remaining = (
                None
                if max_statutes is None
                else max(0, max_statutes - len(statutes) - len(descendant_statutes))
            )
            descendant_input = descendant_inputs.get(descendant_url)
            child_rows = await self._parse_chapter_sections(
                code_name=code_name,
                chapter_url=descendant_url,
                chapter_label=descendant_label,
                max_statutes=remaining,
                _sibling_frontier_urls=descendant_urls,
                _html=(descendant_input[0] if descendant_input is not None else None),
                _page_row_provenance=(
                    descendant_input[1] if descendant_input is not None else None
                ),
                _retrieval_provider=(
                    descendant_input[2] if descendant_input is not None else ""
                ),
            )
            superseded_url = superseded_by_replacement.get(descendant_url, "")
            if superseded_url:
                for row in child_rows:
                    structured_data = dict(row.structured_data or {})
                    structured_data["official_supersedes_empty_index_url"] = (
                        superseded_url
                    )
                    row.structured_data = structured_data
            descendant_statutes.extend(child_rows)
            visited_descendants += 1
        for statute in descendant_statutes:
            structured_data = dict(statute.structured_data or {})
            structured_data.setdefault("official_parent_chapter_url", chapter_url)
            ancestor_urls = list(structured_data.get("official_ancestor_index_urls") or [])
            if chapter_url not in ancestor_urls:
                ancestor_urls.insert(0, chapter_url)
            structured_data["official_ancestor_index_urls"] = ancestor_urls
            structured_data["official_descendant_frontier_closed"] = bool(
                max_statutes is None
                and visited_descendants == len(descendant_pages)
                and self._full_corpus_enabled()
            )
            structured_data["official_descendant_pages_visited"] = visited_descendants
            statute.structured_data = structured_data
        statutes.extend(descendant_statutes)

        if self._full_corpus_enabled() and max_statutes is None:
            terminal_empty = bool(
                re.search(
                    r"\b(repealed|reserved|expired)\b",
                    chapter_label,
                    re.IGNORECASE,
                )
            )
            terminal_empty = terminal_empty or bool(
                self._verified_superseding_index_url(
                    soup,
                    page_url=chapter_url,
                    sibling_frontier_urls=_sibling_frontier_urls or set(),
                )
            )
            terminal_empty = terminal_empty or self._verified_legislatively_vacated_index(
                soup,
                page_url=chapter_url,
                sibling_frontier_urls=_sibling_frontier_urls or set(),
            )
            terminal_empty = terminal_empty or (
                self._verified_omitted_citation_only_index(
                    soup,
                    page_url=chapter_url,
                    chapter_label=chapter_label,
                    sibling_frontier_urls=_sibling_frontier_urls or set(),
                )
            )
            terminal_empty = terminal_empty or (
                self._verified_relocated_citation_only_index(
                    soup,
                    page_url=chapter_url,
                    chapter_label=chapter_label,
                    sibling_frontier_urls=_sibling_frontier_urls or set(),
                )
            )
            terminal_empty = terminal_empty or (
                self._verified_authenticated_empty_relocated_index(
                    soup,
                    page_url=chapter_url,
                    chapter_label=chapter_label,
                    sibling_frontier_urls=_sibling_frontier_urls or set(),
                )
            )
            if not section_nodes and not descendant_pages and not terminal_empty:
                self._fail_full_corpus(
                    "Delaware chapter page exposed no section frontier",
                    chapter_url=chapter_url,
                )
            parity = self._delaware_section_frontier_parity(
                section_nodes,
                direct_statutes,
                page_url=chapter_url,
            )
            missing_sections = list(parity["missing_sections"])
            if missing_sections:
                self._fail_full_corpus(
                    "Delaware chapter parser omitted active official sections",
                    chapter_url=chapter_url,
                    missing_sections=missing_sections,
                )
            unexpected_sections = list(parity["unexpected_sections"])
            if unexpected_sections:
                self._fail_full_corpus(
                    "Delaware chapter parser emitted sections outside the active official frontier",
                    chapter_url=chapter_url,
                    unexpected_sections=unexpected_sections,
                )
        return statutes

    def _delaware_section_frontier_parity(
        self,
        section_nodes: List[Any],
        statutes: List[NormalizedStatute],
        *,
        page_url: str = "",
    ) -> Dict[str, Any]:
        """Return the exact frontier-vs-parser identity comparison used live."""

        from .delaware_chapter import normalize_delaware_section_number

        active_section_numbers: set[str] = set()
        for section in section_nodes:
            head = section.select_one(".SectionHead")
            head_text = (
                re.sub(r"\s+", " ", head.get_text(" ", strip=True) or "").strip()
                if head is not None
                else ""
            )
            match = self._DE_SECTION_HEAD_RE.search(head_text)
            if match and not self._official_section_is_inactive_without_body(
                section,
                heading=head_text,
                page_url=page_url,
            ):
                number = normalize_delaware_section_number(match.group(1))
                if number:
                    active_section_numbers.add(number)
        parsed_numbers = {
            normalize_delaware_section_number(row.section_number)
            for row in statutes
            if normalize_delaware_section_number(row.section_number)
        }
        return {
            "active_sections": sorted(active_section_numbers),
            "parsed_sections": sorted(parsed_numbers),
            "missing_sections": sorted(active_section_numbers - parsed_numbers),
            "unexpected_sections": sorted(parsed_numbers - active_section_numbers),
        }

    def _official_section_is_inactive_without_body(
        self,
        section: Any,
        *,
        heading: str,
        page_url: str = "",
    ) -> bool:
        """Recognize an official inactive disposition that has no legal body.

        Delaware normally places ``repealed``/``reserved``/``expired`` in the
        section heading.  Some current pages instead leave the heading
        unmarked, omit every direct body paragraph, and state the disposition
        in an official session-law history link.
        """

        if re.search(
            r"\[(?:repealed|reserved|expired|transferred)\s*\.?\]",
            str(heading or ""),
            re.IGNORECASE,
        ):
            return True
        direct_paragraphs = [
            self._normalize_legal_text(node.get_text(" ", strip=True) or "")
            for node in section.find_all("p", recursive=False)
        ]
        direct_paragraphs = [value for value in direct_paragraphs if value]
        if direct_paragraphs:
            from .delaware_chapter import is_delaware_inactive_disposition_only

            return len(direct_paragraphs) == 1 and (
                is_delaware_inactive_disposition_only(direct_paragraphs[0])
            )
        for anchor in section.find_all("a", href=True, recursive=False):
            citation_url = urlparse(
                urljoin(self.get_base_url(), str(anchor.get("href") or "").strip())
            )
            if (
                (citation_url.hostname or "").lower() != "legis.delaware.gov"
                or citation_url.path.rstrip("/").lower() != "/sessionlaws"
            ):
                continue
            disposition = re.sub(
                r"\s+",
                " ",
                anchor.get_text(" ", strip=True) or "",
            ).strip()
            if re.match(
                r"^(?:expired (?:by operation of|under)|repealed by) "
                r"\d+ Del\. Laws, c\. \d+,?\s*§\s*\d+",
                disposition,
                re.IGNORECASE,
            ):
                return True
        return (
            self._verified_exact_inactive_session_law_history(
                section,
                heading=heading,
                page_url=page_url,
            )
            or self._verified_exact_inactive_chapter_history(
                section,
                heading=heading,
                page_url=page_url,
            )
        )

    def _verified_exact_inactive_session_law_history(
        self,
        section: Any,
        *,
        heading: str,
        page_url: str,
    ) -> bool:
        """Admit a retained heading-only disposition with an exact history."""

        parsed_page = urlparse(str(page_url or "").strip())
        if (
            parsed_page.scheme.lower() != "https"
            or (parsed_page.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed_page.query
            or parsed_page.fragment
        ):
            return False
        expected = self._DE_EXACT_INACTIVE_SESSION_LAW_HISTORIES.get(
            parsed_page.path
        )
        if expected is None:
            return False
        if str(page_url).strip() != urljoin(self.get_base_url(), parsed_page.path):
            return False

        direct_tags = section.find_all(recursive=False)
        expected_tag_names = ["div", *(["a"] * len(expected["anchors"]))]
        if [tag.name for tag in direct_tags] != expected_tag_names:
            return False
        head = direct_tags[0]
        if "SectionHead" not in set(head.get("class") or []):
            return False
        observed_heading = self._normalize_legal_text(
            head.get_text(" ", strip=True) or ""
        )
        if (
            str(head.get("id") or "").strip() != expected["section_id"]
            or observed_heading != expected["heading"]
            or self._normalize_legal_text(heading) != observed_heading
        ):
            return False

        direct_text = "".join(
            str(node) for node in section.find_all(string=True, recursive=False)
        )
        if re.sub(r"[\s;\u00a0]+", "", direct_text):
            return False
        observed_anchors = tuple(
            (
                str(anchor.get("href") or "").strip(),
                self._normalize_legal_text(
                    anchor.get_text(" ", strip=True) or ""
                ),
            )
            for anchor in direct_tags[1:]
        )
        return observed_anchors == expected["anchors"]

    def _verified_exact_inactive_chapter_history(
        self,
        section: Any,
        *,
        heading: str,
        page_url: str,
    ) -> bool:
        """Admit one locator only when its complete expired page is exact."""

        parsed_page = urlparse(str(page_url or "").strip())
        if (
            parsed_page.scheme.lower() != "https"
            or (parsed_page.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed_page.query
            or parsed_page.fragment
        ):
            return False
        expected = self._DE_EXACT_INACTIVE_CHAPTER_HISTORIES.get(
            parsed_page.path
        )
        if expected is None:
            return False
        if str(page_url).strip() != urljoin(self.get_base_url(), parsed_page.path):
            return False

        document = section
        while getattr(document, "parent", None) is not None:
            document = document.parent
        observed_headings = tuple(
            (
                node.name,
                self._normalize_legal_text(
                    node.get_text(" ", strip=True) or ""
                ),
            )
            for node in document.select(
                "#TitleHead h1, #TitleHead h2, #TitleHead h3, #TitleHead h4"
            )
        )
        if observed_headings != expected["headings"]:
            return False

        expected_sections = expected["sections"]
        section_navigation = document.select_one("ul.chaptersections")
        if section_navigation is None:
            return False
        navigation_anchors = section_navigation.find_all("a")
        if any(not anchor.has_attr("href") for anchor in navigation_anchors):
            return False
        observed_navigation = tuple(
            (
                str(anchor.get("href") or "").strip(),
                self._normalize_legal_text(
                    anchor.get_text(" ", strip=True) or ""
                ),
            )
            for anchor in navigation_anchors
        )
        expected_navigation = tuple(
            (f"#{section_id}", f"§ {section_id}")
            for section_id, _expected_heading, _anchors in expected_sections
        )
        if observed_navigation != expected_navigation:
            return False

        observed_sections = document.select("#CodeBody div.Section")
        if len(observed_sections) != len(expected_sections):
            return False
        current_section_is_exact = False
        for observed_section, expected_section in zip(
            observed_sections,
            expected_sections,
        ):
            expected_id, expected_heading, expected_anchors = expected_section
            direct_tags = observed_section.find_all(recursive=False)
            expected_tag_names = [
                "div",
                *(["a"] * len(expected_anchors)),
            ]
            if [tag.name for tag in direct_tags] != expected_tag_names:
                return False
            head = direct_tags[0]
            if "SectionHead" not in set(head.get("class") or []):
                return False
            observed_heading = self._normalize_legal_text(
                head.get_text(" ", strip=True) or ""
            )
            if (
                str(head.get("id") or "").strip() != expected_id
                or observed_heading != expected_heading
            ):
                return False
            direct_text = "".join(
                str(node)
                for node in observed_section.find_all(
                    string=True,
                    recursive=False,
                )
            )
            if re.sub(r"[\s;\u00a0]+", "", direct_text):
                return False
            observed_anchors = tuple(
                (
                    str(anchor.get("href") or "").strip(),
                    self._normalize_legal_text(
                        anchor.get_text(" ", strip=True) or ""
                    ),
                )
                for anchor in direct_tags[1:]
            )
            if observed_anchors != expected_anchors:
                return False
            if observed_section is section:
                current_section_is_exact = (
                    self._normalize_legal_text(heading) == observed_heading
                )
        return current_section_is_exact

    def _superseded_descendant_pairs(
        self,
        descendant_urls: set[str],
    ) -> Dict[str, str]:
        """Map a discovered replacement locator to its superseded sibling."""

        pairs: Dict[str, str] = {}
        for old_path, evidence in self._DE_SUPERSEDED_EMPTY_INDEXES.items():
            old_url = urljoin(self.get_base_url(), old_path)
            replacement_url = urljoin(
                self.get_base_url(),
                evidence["replacement_path"],
            )
            if old_url in descendant_urls and replacement_url in descendant_urls:
                pairs[replacement_url] = old_url
        return pairs

    def _assert_superseded_descendant_pairs_closed(
        self,
        descendant_urls: set[str],
    ) -> None:
        """Fail closed if an obsolete Delaware index loses its replacement."""

        for old_path, evidence in self._DE_SUPERSEDED_EMPTY_INDEXES.items():
            old_url = urljoin(self.get_base_url(), old_path)
            replacement_url = urljoin(
                self.get_base_url(),
                evidence["replacement_path"],
            )
            if old_url in descendant_urls and replacement_url not in descendant_urls:
                self._fail_full_corpus(
                    "Delaware superseded index replacement was absent from its official parent frontier",
                    superseded_index_url=old_url,
                    expected_replacement_url=replacement_url,
                )

    def _verified_superseding_index_url(
        self,
        soup: Any,
        *,
        page_url: str,
        sibling_frontier_urls: set[str],
    ) -> str:
        """Verify an exact Delaware citation-only superseded index.

        The exception is deliberately evidence-bound.  A page must be the
        cataloged official path, expose no section or descendant, retain the
        exact old heading and amendment-history citation, and have its exact
        replacement URL in the parent page's discovered sibling frontier.
        """

        parsed_page = urlparse(str(page_url or "").strip())
        if (
            parsed_page.scheme.lower() != "https"
            or (parsed_page.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed_page.query
            or parsed_page.fragment
        ):
            return ""
        evidence = self._DE_SUPERSEDED_EMPTY_INDEXES.get(parsed_page.path)
        if not evidence:
            return ""
        canonical_page_url = urljoin(self.get_base_url(), parsed_page.path)
        replacement_url = urljoin(
            self.get_base_url(),
            evidence["replacement_path"],
        )
        if (
            str(page_url).strip() != canonical_page_url
            or canonical_page_url not in sibling_frontier_urls
            or replacement_url not in sibling_frontier_urls
        ):
            return ""
        if soup.select_one("div.Section") is not None:
            return ""
        if self._discover_descendant_index_links(str(soup), page_url=page_url):
            return ""
        if evidence.get("requires_empty_section_navigation"):
            section_navigation = soup.select_one("ul.chaptersections")
            if (
                section_navigation is None
                or section_navigation.find(True) is not None
                or self._normalize_legal_text(
                    section_navigation.get_text(" ", strip=True) or ""
                )
            ):
                return ""

        expected_headings = evidence.get("headings")
        if expected_headings is not None:
            title_head = soup.select_one("#TitleHead")
            if title_head is None:
                return ""
            observed_headings = tuple(
                (
                    node.name,
                    self._normalize_legal_text(
                        node.get_text(" ", strip=True) or ""
                    ),
                )
                for node in title_head.find_all(
                    re.compile(r"^h[1-4]$"),
                    recursive=False,
                )
            )
            if observed_headings != expected_headings:
                return ""
        else:
            heading_node = soup.select_one("#TitleHead h4:last-of-type")
            heading = (
                re.sub(
                    r"\s+",
                    " ",
                    heading_node.get_text(" ", strip=True) or "",
                ).strip()
                if heading_node is not None
                else ""
            )
            if heading.casefold() != evidence["heading"].casefold():
                return ""

        code_body = soup.select_one("#CodeBody")
        if code_body is None:
            return ""
        anchors = code_body.find_all("a", href=True)
        if len(anchors) != 1 or code_body.find_all(True) != anchors:
            return ""
        citation_url = urlparse(
            urljoin(page_url, str(anchors[0].get("href") or "").strip())
        )
        query = parse_qs(citation_url.query)
        if (
            (citation_url.hostname or "").lower() != "legis.delaware.gov"
            or citation_url.path.rstrip("/").lower() != "/sessionlaws"
            or query.get("volume") != [evidence["session_law_volume"]]
            or query.get("chapter") != [evidence["session_law_chapter"]]
        ):
            return ""
        citation_text = re.sub(
            r"\s+",
            " ",
            code_body.get_text(" ", strip=True) or "",
        ).strip()
        expected_citation = (
            rf"{re.escape(evidence['session_law_volume'])} Del\. Laws, "
            rf"c\. {re.escape(evidence['session_law_chapter'])},\s*§\s*"
            rf"{re.escape(evidence['session_law_section'])}\s*;?"
        )
        if not re.fullmatch(expected_citation, citation_text, re.IGNORECASE):
            return ""
        return replacement_url

    def _verified_legislatively_vacated_index(
        self,
        soup: Any,
        *,
        page_url: str,
        sibling_frontier_urls: set[str],
    ) -> bool:
        """Verify an exact heading-only locator vacated in full by statute."""

        parsed_page = urlparse(str(page_url or ""))
        if (parsed_page.hostname or "").lower() != self.OFFICIAL_DOMAIN:
            return False
        expected_headings = self._DE_LEGISLATIVELY_VACATED_EMPTY_INDEXES.get(
            parsed_page.path
        )
        if not expected_headings:
            return False
        canonical_page_url = urljoin(self.get_base_url(), parsed_page.path)
        if canonical_page_url not in sibling_frontier_urls:
            return False
        if soup.select_one("div.Section") is not None:
            return False
        if self._discover_descendant_index_links(str(soup), page_url=page_url):
            return False

        title_head = soup.select_one("#TitleHead")
        if title_head is None:
            return False
        observed_headings = tuple(
            re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
            for node in title_head.find_all(re.compile(r"^h[1-4]$"))
        )
        if tuple(value.casefold() for value in observed_headings) != tuple(
            value.casefold() for value in expected_headings
        ):
            return False

        code_body = soup.select_one("#CodeBody")
        if code_body is None or code_body.find(True) is not None:
            return False
        return not re.sub(
            r"\s+",
            " ",
            code_body.get_text(" ", strip=True) or "",
        ).strip()

    def _verified_omitted_citation_only_index(
        self,
        soup: Any,
        *,
        page_url: str,
        chapter_label: str,
        sibling_frontier_urls: set[str],
    ) -> bool:
        """Verify Delaware's exact citation-only omitted chapter locator."""

        parsed_page = urlparse(str(page_url or "").strip())
        if (
            parsed_page.scheme.lower() != "https"
            or (parsed_page.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed_page.query
            or parsed_page.fragment
        ):
            return False
        expected = self._DE_OMITTED_CITATION_ONLY_INDEXES.get(parsed_page.path)
        if expected is None:
            return False
        canonical_page_url = urljoin(self.get_base_url(), parsed_page.path)
        if (
            str(page_url).strip() != canonical_page_url
            or canonical_page_url not in sibling_frontier_urls
            or self._normalize_legal_text(chapter_label)
            != expected["parent_heading"]
            or soup.select_one("div.Section") is not None
            or self._discover_descendant_index_links(
                str(soup),
                page_url=page_url,
            )
        ):
            return False

        section_navigation = soup.select_one("ul.chaptersections")
        if (
            section_navigation is None
            or section_navigation.find(True) is not None
            or self._normalize_legal_text(
                section_navigation.get_text(" ", strip=True) or ""
            )
        ):
            return False
        title_head = soup.select_one("#TitleHead")
        if title_head is None:
            return False
        observed_headings = tuple(
            (
                node.name,
                self._normalize_legal_text(
                    node.get_text(" ", strip=True) or ""
                ),
            )
            for node in title_head.find_all(
                re.compile(r"^h[1-4]$"),
                recursive=False,
            )
        )
        if observed_headings != expected["headings"]:
            return False

        code_body = soup.select_one("#CodeBody")
        if code_body is None:
            return False
        direct_tags = code_body.find_all(recursive=False)
        if [tag.name for tag in direct_tags] != ["a"]:
            return False
        anchor = direct_tags[0]
        if code_body.find_all(True) != [anchor]:
            return False
        if (
            str(anchor.get("href") or "").strip() != expected["citation_url"]
            or self._normalize_legal_text(
                anchor.get_text(" ", strip=True) or ""
            )
            != expected["citation_text"]
        ):
            return False
        direct_text = "".join(
            str(node) for node in code_body.find_all(string=True, recursive=False)
        )
        return not re.sub(r"[\s;\u00a0]+", "", direct_text)

    def _verified_relocated_citation_only_index(
        self,
        soup: Any,
        *,
        page_url: str,
        chapter_label: str,
        sibling_frontier_urls: set[str],
    ) -> bool:
        """Verify Delaware's exact citation-only relocated chapter stub."""

        parsed_page = urlparse(str(page_url or "").strip())
        if (
            parsed_page.scheme.lower() != "https"
            or (parsed_page.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed_page.query
            or parsed_page.fragment
        ):
            return False
        expected = self._DE_RELOCATED_CITATION_ONLY_INDEXES.get(parsed_page.path)
        if expected is None:
            return False
        canonical_page_url = urljoin(self.get_base_url(), parsed_page.path)
        if (
            str(page_url).strip() != canonical_page_url
            or canonical_page_url not in sibling_frontier_urls
            or self._normalize_legal_text(chapter_label)
            != expected["parent_heading"]
            or soup.select_one("div.Section") is not None
            or self._discover_descendant_index_links(
                str(soup),
                page_url=page_url,
            )
        ):
            return False

        section_navigation = soup.select_one("ul.chaptersections")
        if (
            section_navigation is None
            or section_navigation.find(True) is not None
            or self._normalize_legal_text(
                section_navigation.get_text(" ", strip=True) or ""
            )
        ):
            return False
        title_head = soup.select_one("#TitleHead")
        if title_head is None:
            return False
        observed_headings = tuple(
            (
                node.name,
                self._normalize_legal_text(
                    node.get_text(" ", strip=True) or ""
                ),
            )
            for node in title_head.find_all(
                re.compile(r"^h[1-4]$"),
                recursive=False,
            )
        )
        if observed_headings != expected["headings"]:
            return False

        code_body = soup.select_one("#CodeBody")
        if code_body is None:
            return False
        direct_tags = code_body.find_all(recursive=False)
        if [tag.name for tag in direct_tags] != ["p"]:
            return False
        paragraph = direct_tags[0]
        if (
            set(paragraph.get("class") or []) != {"subsection"}
            or paragraph.find(True) is not None
            or self._normalize_legal_text(
                paragraph.get_text(" ", strip=True) or ""
            )
            != expected["citation_text"]
        ):
            return False
        direct_text = "".join(
            str(node) for node in code_body.find_all(string=True, recursive=False)
        )
        return not self._normalize_legal_text(direct_text)

    def _verified_authenticated_empty_relocated_index(
        self,
        soup: Any,
        *,
        page_url: str,
        chapter_label: str,
        sibling_frontier_urls: set[str],
    ) -> bool:
        """Verify one exact empty locator independently closed by the PDF."""

        parsed_page = urlparse(str(page_url or "").strip())
        if (
            parsed_page.scheme.lower() != "https"
            or (parsed_page.hostname or "").lower() != self.OFFICIAL_DOMAIN
            or parsed_page.query
            or parsed_page.fragment
        ):
            return False
        expected = self._DE_AUTHENTICATED_EMPTY_RELOCATED_INDEXES.get(
            parsed_page.path
        )
        if expected is None:
            return False
        canonical_page_url = urljoin(self.get_base_url(), parsed_page.path)
        if (
            str(page_url).strip() != canonical_page_url
            or canonical_page_url not in sibling_frontier_urls
            or self._normalize_legal_text(chapter_label)
            != expected["parent_heading"]
            or soup.select_one("div.Section") is not None
            or self._discover_descendant_index_links(
                str(soup),
                page_url=page_url,
            )
        ):
            return False

        section_navigation = soup.select_one("ul.chaptersections")
        if (
            section_navigation is None
            or section_navigation.find(True) is not None
            or self._normalize_legal_text(
                section_navigation.get_text(" ", strip=True) or ""
            )
        ):
            return False
        title_head = soup.select_one("#TitleHead")
        if title_head is None:
            return False
        observed_headings = tuple(
            (
                node.name,
                self._normalize_legal_text(
                    node.get_text(" ", strip=True) or ""
                ),
            )
            for node in title_head.find_all(
                re.compile(r"^h[1-4]$"),
                recursive=False,
            )
        )
        if observed_headings != expected["headings"]:
            return False

        code_body = soup.select_one("#CodeBody")
        return bool(
            code_body is not None
            and code_body.find(True) is None
            and not self._normalize_legal_text(
                code_body.get_text(" ", strip=True) or ""
            )
        )

    def _discover_descendant_index_links(
        self,
        html: str,
        *,
        page_url: str,
    ) -> List[Tuple[str, str]]:
        """Discover the immediate official index children of a chapter page.

        Delaware's UCC articles are chapter landing pages whose enacted text is
        partitioned into ``scNN/index.html`` part pages.  Only immediate child
        indexes under the current official directory are admitted, which also
        prevents breadcrumb and sibling cycles.
        """

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        parsed_page = urlparse(page_url)
        current_path = parsed_page.path
        if not current_path.lower().endswith("/index.html"):
            return []
        current_prefix = current_path[: -len("index.html")]
        soup = BeautifulSoup(html or "", "html.parser")
        out: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            candidate = urljoin(page_url, str(anchor.get("href") or "").strip())
            parsed_candidate = urlparse(candidate)
            if (parsed_candidate.hostname or "").lower() != self.OFFICIAL_DOMAIN:
                continue
            if not parsed_candidate.path.startswith(current_prefix):
                continue
            relative_path = parsed_candidate.path[len(current_prefix) :]
            if not re.fullmatch(r"[^/]+/index\.html", relative_path, re.IGNORECASE):
                continue
            canonical = candidate.split("#", 1)[0]
            if canonical in seen:
                continue
            seen.add(canonical)
            label = re.sub(
                r"\s+",
                " ",
                anchor.get_text(" ", strip=True) or "",
            ).strip()
            out.append((canonical, label or relative_path.split("/", 1)[0]))
        return out

    def _verified_redirected_descendant_index_links(
        self,
        soup: Any,
        *,
        page_url: str,
        chapter_label: str,
        sibling_frontier_urls: set[str],
    ) -> List[Tuple[str, str]]:
        """Verify one exact official index whose children use a sibling path."""

        parsed_page = urlparse(str(page_url or ""))
        if (parsed_page.hostname or "").lower() != self.OFFICIAL_DOMAIN:
            return []
        evidence = self._DE_REDIRECTED_DESCENDANT_INDEXES.get(parsed_page.path)
        if evidence is None:
            return []
        canonical_page_url = urljoin(self.get_base_url(), parsed_page.path)
        required_sibling_url = urljoin(
            self.get_base_url(),
            str(evidence["required_sibling_path"]),
        )
        if (
            canonical_page_url not in sibling_frontier_urls
            or required_sibling_url not in sibling_frontier_urls
        ):
            return []
        observed_parent_heading = re.sub(
            r"\s+", " ", str(chapter_label or "")
        ).strip()
        if observed_parent_heading.casefold() != str(
            evidence["parent_heading"]
        ).casefold():
            return []
        if soup.select_one("div.Section") is not None:
            return []

        page_headings = [
            re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
            for node in soup.select("#content h2")
        ]
        if [value.casefold() for value in page_headings] != [
            str(evidence["page_heading"]).casefold()
        ]:
            return []
        breadcrumbs = {
            re.sub(r"\s+", " ", node.get_text(" ", strip=True) or "").strip()
            for node in soup.select("#content .breadcrumb.delcrumb")
        }
        if str(evidence["breadcrumb"]) not in breadcrumbs:
            return []

        observed_children: List[Tuple[str, str]] = []
        for container in soup.select("#content div.title-links"):
            anchors = container.find_all("a", href=True, recursive=False)
            if len(anchors) != 1:
                return []
            anchor = anchors[0]
            candidate = urljoin(
                page_url,
                str(anchor.get("href") or "").strip(),
            ).split("#", 1)[0]
            label = re.sub(
                r"\s+",
                " ",
                anchor.get_text(" ", strip=True) or "",
            ).strip()
            observed_children.append((candidate, label))
        expected_children = [
            (urljoin(self.get_base_url(), path), label)
            for path, label in evidence["children"]
        ]
        if [
            (url.casefold(), label.casefold())
            for url, label in observed_children
        ] != [
            (url.casefold(), label.casefold())
            for url, label in expected_children
        ]:
            return []
        return observed_children

    def _qualify_concurrent_source_records(
        self,
        statutes: List[NormalizedStatute],
    ) -> List[NormalizedStatute]:
        """Give concurrent official HTML records distinct stable identities.

        Delaware publishes current, future-effective, conditional, and
        predecessor versions under the same printed citation.  Sometimes the
        records share one page and duplicate HTML ``id``; sometimes they use
        sibling official paths.  The printed citation therefore cannot be
        the canonical source-record identity.  Qualify only actual collision
        groups, using exact official row content and its byte-bound source
        locator.  An ambiguous or unbound collision remains fail closed.
        """

        from ...legal_data.state_laws_source_provenance import (
            StateLawTransportReceiptError,
            verify_state_law_transport_receipt,
        )

        grouped: Dict[str, List[NormalizedStatute]] = {}
        for statute in statutes:
            base_id = str(statute.statute_id or "").strip()
            if not base_id:
                self._fail_full_corpus(
                    "Delaware concurrent source record lacks a base identity"
                )
            grouped.setdefault(base_id, []).append(statute)

        for base_id, records in grouped.items():
            if len(records) < 2:
                continue
            derived_ids: set[str] = set()
            for statute in records:
                source_url = str(statute.source_url or "").strip()
                parsed_source = urlparse(source_url)
                structured_data = dict(statute.structured_data or {})
                source_kind = str(
                    structured_data.get("source_kind") or ""
                ).strip()
                digest = str(
                    structured_data.get("content_sha256") or ""
                ).strip().lower()
                receipt = structured_data.get("transport_receipt")
                receipt_url = (
                    str(receipt.get("official_url") or "").strip()
                    if isinstance(receipt, dict)
                    else ""
                )
                receipt_digest = (
                    str(receipt.get("content_sha256") or "").strip().lower()
                    if isinstance(receipt, dict)
                    else ""
                )
                source_without_fragment = source_url.split("#", 1)[0]
                verified_receipt = False
                if isinstance(receipt, dict):
                    try:
                        verify_state_law_transport_receipt(
                            receipt,
                            official_url=source_without_fragment,
                            content_sha256=digest,
                        )
                    except StateLawTransportReceiptError:
                        pass
                    else:
                        verified_receipt = True
                if (
                    parsed_source.scheme.lower() != "https"
                    or parsed_source.netloc != self.OFFICIAL_DOMAIN
                    or parsed_source.query
                    or not parsed_source.fragment
                    or source_kind != "official_delaware_section_html"
                    or not re.fullmatch(r"[a-f0-9]{64}", digest)
                    or receipt_url != source_without_fragment
                    or receipt_digest != digest
                    or not verified_receipt
                ):
                    self._fail_full_corpus(
                        "Delaware concurrent source record lacks exact official evidence",
                        statute_id=base_id,
                        source_url=source_url,
                    )
                if structured_data.get("source_record_id") not in (None, ""):
                    self._fail_full_corpus(
                        "Delaware concurrent source record identity was already declared",
                        statute_id=base_id,
                        source_url=source_url,
                    )

                identity_material = {
                    "chapter_number": str(statute.chapter_number or ""),
                    "full_text_sha256": hashlib.sha256(
                        str(statute.full_text or "").encode("utf-8")
                    ).hexdigest(),
                    "official_cite": str(statute.official_cite or ""),
                    "section_name": str(statute.section_name or ""),
                    "section_number": str(statute.section_number or ""),
                    "source_url": source_url,
                    "state_code": self.state_code,
                    "title_number": str(statute.title_number or ""),
                }
                identity_sha256 = hashlib.sha256(
                    json.dumps(
                        identity_material,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()
                source_record_id = f"delaware-html-{identity_sha256}"
                if source_record_id in derived_ids:
                    self._fail_full_corpus(
                        "Delaware concurrent source records are not distinguishable",
                        statute_id=base_id,
                    )
                derived_ids.add(source_record_id)
                statute.statute_id = f"{base_id}:record:{identity_sha256}"
                structured_data.update(
                    {
                        "concurrent_source_record_count": len(records),
                        "printed_statute_id": base_id,
                        "source_record_id": source_record_id,
                        "source_record_identity_sha256": identity_sha256,
                    }
                )
                statute.structured_data = structured_data
        return statutes

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape Delaware Code.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=None)
        strict_full = bool(limit is None and self._full_corpus_enabled())
        frontier: Dict[str, Any] = {
            "closed": False,
            "expected_title_units": self.OFFICIAL_TITLE_COUNT,
            "visited_title_units": 0,
            "discovered_chapter_units": 0,
            "visited_chapter_units": 0,
            "unvisited_chapter_urls": [],
            "errors": [],
        }
        self._last_full_corpus_frontier = frontier
        from .delaware_constitution import (
            configured_constitution_html_path,
            parse_delaware_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_delaware_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Delaware Constitution",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .delaware_chapter import configured_chapter_html_path, parse_delaware_chapter_html

        local_chapter = configured_chapter_html_path()
        if local_chapter is not None:
            local_rows = parse_delaware_chapter_html(
                local_chapter.read_text(encoding="utf-8", errors="replace"),
                source_url="https://delcode.delaware.gov/title11/c005/index.html",
                code_name=code_name,
                title_number="11",
                chapter_number="5",
                max_statutes=limit,
            )
            if local_rows:
                if strict_full:
                    self._assert_full_title_coverage(
                        local_rows,
                        context="configured Delaware chapter HTML",
                    )
                return local_rows if limit is None else local_rows[: int(limit)]
        from .delaware_chapter import parse_configured_delaware_title

        title_rows = parse_configured_delaware_title(
            code_name=code_name or "Delaware Code",
            max_statutes=limit,
        )
        if title_rows:
            if strict_full:
                self._assert_full_title_coverage(
                    title_rows,
                    context="configured Delaware title input",
                )
            return title_rows if limit is None else title_rows[: int(limit)]
        if limit is None and max_statutes is not None:
            try:
                limit = max(1, int(max_statutes))
            except Exception:
                limit = None
        statutes: List[NormalizedStatute] = []
        title_links = await self._discover_title_links()
        if not title_links and self._DE_CHAPTER_URL_RE.search(str(code_url or "")):
            title_links = [(urljoin(code_url, "../../index.html"), "")]

        if strict_full:
            expected_titles = {
                str(number) for number in range(1, self.OFFICIAL_TITLE_COUNT + 1)
            }
            discovered_title_list = [
                self._title_number_from_url(url) for url, _label in title_links
            ]
            discovered_titles = {number for number in discovered_title_list if number}
            missing_titles = sorted(expected_titles - discovered_titles, key=int)
            unexpected_titles = sorted(discovered_titles - expected_titles, key=int)
            duplicate_titles = sorted(
                {
                    number
                    for number in discovered_titles
                    if discovered_title_list.count(number) > 1
                },
                key=int,
            )
            if (
                missing_titles
                or unexpected_titles
                or duplicate_titles
                or len(discovered_title_list) != self.OFFICIAL_TITLE_COUNT
            ):
                self._fail_full_corpus(
                    "Delaware official title enumeration did not close",
                    missing_titles=missing_titles,
                    unexpected_titles=unexpected_titles,
                    duplicate_titles=duplicate_titles,
                    discovered_title_count=len(discovered_title_list),
                )

        title_inputs: Dict[str, tuple[str, Dict[str, Any], str]] = {}
        chapter_links_by_title: Dict[str, List[Tuple[str, str]]] = {}
        chapter_inputs: Dict[str, tuple[str, Dict[str, Any], str]] = {}
        if strict_full:
            title_inputs = await self._fetch_de_html_frontier(
                [url for url, _label in title_links],
                frontier_name="title catalog",
            )
            all_chapter_urls: List[str] = []
            for title_url, _title_label in title_links:
                chapter_links = await self._discover_chapter_links(
                    title_url,
                    _html=title_inputs[title_url][0],
                )
                if not chapter_links:
                    self._fail_full_corpus(
                        "Delaware official title returned no chapter frontier",
                        title_url=title_url,
                    )
                chapter_links_by_title[title_url] = chapter_links
                all_chapter_urls.extend(url for url, _label in chapter_links)
            chapter_inputs = await self._fetch_de_html_frontier(
                all_chapter_urls,
                frontier_name="chapter catalog",
            )

        for title_url, _title_label in title_links:
            if limit is not None and len(statutes) >= limit:
                break
            chapter_links = chapter_links_by_title.get(title_url)
            if chapter_links is None:
                chapter_links = await self._discover_chapter_links(title_url)
            if strict_full and not chapter_links:
                self._fail_full_corpus(
                    "Delaware official title returned no chapter frontier",
                    title_url=title_url,
                )
            frontier["discovered_chapter_units"] = int(
                frontier["discovered_chapter_units"]
            ) + len(chapter_links)
            frontier["unvisited_chapter_urls"].extend(url for url, _label in chapter_links)
            chapter_frontier_urls = {url for url, _label in chapter_links}
            for chapter_url, chapter_label in chapter_links:
                if limit is not None and len(statutes) >= limit:
                    break
                remaining = None if limit is None else max(0, limit - len(statutes))
                chapter_input = chapter_inputs.get(chapter_url)
                chapter_rows = await self._parse_chapter_sections(
                    code_name=code_name,
                    chapter_url=chapter_url,
                    chapter_label=chapter_label,
                    max_statutes=remaining,
                    _sibling_frontier_urls=chapter_frontier_urls,
                    _html=(chapter_input[0] if chapter_input is not None else None),
                    _page_row_provenance=(
                        chapter_input[1] if chapter_input is not None else None
                    ),
                    _retrieval_provider=(
                        chapter_input[2] if chapter_input is not None else ""
                    ),
                )
                statutes.extend(chapter_rows)
                frontier["visited_chapter_units"] = int(
                    frontier["visited_chapter_units"]
                ) + 1
                try:
                    frontier["unvisited_chapter_urls"].remove(chapter_url)
                except ValueError:
                    pass
            frontier["visited_title_units"] = int(frontier["visited_title_units"]) + 1

        if strict_full:
            if frontier["unvisited_chapter_urls"]:
                self._fail_full_corpus(
                    "Delaware full-corpus traversal left chapter URLs unvisited"
                )
            if not statutes:
                self._fail_full_corpus("Delaware full-corpus traversal emitted no statutes")
            frontier["closed"] = True
            for statute in statutes:
                structured_data = dict(statute.structured_data or {})
                structured_data.update(
                    {
                        "official_frontier_closed": True,
                        "official_title_units_visited": int(frontier["visited_title_units"]),
                        "official_chapter_units_visited": int(
                            frontier["visited_chapter_units"]
                        ),
                    }
                )
                statute.structured_data = structured_data
            statutes = self._qualify_concurrent_source_records(statutes)
        return statutes[:limit] if limit is not None else statutes

    def _assert_full_title_coverage(
        self,
        statutes: List[NormalizedStatute],
        *,
        context: str,
    ) -> None:
        expected = {str(number) for number in range(1, self.OFFICIAL_TITLE_COUNT + 1)}
        observed = {
            str(row.title_number or "").lstrip("0") or "0" for row in statutes
        }
        missing = sorted(expected - observed, key=int)
        unexpected = sorted(observed - expected, key=int)
        if missing or unexpected:
            self._fail_full_corpus(
                f"{context} did not close the official title frontier",
                missing_titles=missing,
                unexpected_titles=unexpected,
                row_count=len(statutes),
            )

    def _fail_full_corpus(self, message: str, **evidence: Any) -> None:
        frontier = dict(getattr(self, "_last_full_corpus_frontier", {}) or {})
        frontier["closed"] = False
        frontier.update(evidence)
        errors = list(frontier.get("errors") or [])
        errors.append(message)
        frontier["errors"] = errors
        self._last_full_corpus_frontier = frontier
        details = " ".join(f"{key}={value}" for key, value in sorted(evidence.items()))
        raise RuntimeError(f"{message}{': ' + details if details else ''}")

    async def _scrape_with_playwright(
        self, code_name: str, code_url: str, citation_format: str, max_sections: int = 120
    ) -> List[NormalizedStatute]:
        """Scrape Delaware using Playwright for JavaScript rendering."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        statutes = []

        async with acquire_playwright_slot():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    self.logger.info(f"Delaware: Loading {code_url}")
                    await page.goto(code_url, wait_until="networkidle", timeout=60000)
                    await page.wait_for_selector('a[href*="title"], div.title-links', timeout=10000)

                    content = await page.content()
                    soup = BeautifulSoup(content, "html.parser")

                    links = soup.find_all("a", href=True)
                    title_links = [
                        l
                        for l in links
                        if not l.get("href", "").lower().endswith(".pdf")
                        and (
                            self._DE_CHAPTER_URL_RE.search(l.get("href", ""))
                            or "§" in l.get_text(strip=True)
                            or re.search(r"\b\d+\.[0-9A-Za-z\-]*", l.get_text(strip=True))
                        )
                    ][:40]

                    self.logger.info(f"Delaware: Found {len(title_links)} title links")

                    section_count = 0
                    for link in title_links:
                        if section_count >= max_sections:
                            break

                        link_text = link.get_text(strip=True)
                        link_href = link.get("href", "")

                        if len(link_text) < 3:
                            continue

                        full_url = urljoin(code_url, link_href)
                        section_number = (
                            self._extract_section_number(link_text)
                            or f"Section-{section_count + 1}"
                        )
                        legal_area = self._identify_legal_area(link_text)

                        statute = NormalizedStatute(
                            state_code=self.state_code,
                            state_name=self.state_name,
                            statute_id=f"{code_name} § {section_number}",
                            code_name=code_name,
                            section_number=section_number,
                            section_name=link_text[:200],
                            full_text=f"Title {section_number}: {link_text}",
                            legal_area=legal_area,
                            source_url=full_url,
                            official_cite=f"{citation_format} § {section_number}",
                            metadata=StatuteMetadata(),
                        )

                        statutes.append(statute)
                        section_count += 1

                    self.logger.info(f"Delaware Playwright: Scraped {len(statutes)} sections")

                finally:
                    try:
                        await page.close()
                    finally:
                        await browser.close()

        return statutes

    async def _custom_scrape_delaware(
        self, code_name: str, code_url: str, citation_format: str, max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Delaware (basic fallback without Playwright)."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []

        statutes = []

        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                return []

            soup = BeautifulSoup(page_bytes, "html.parser")

            # Delaware uses JavaScript rendering, so this will find few/no links
            links = soup.find_all("a", href=True)
            self.logger.info(
                f"Delaware: Found {len(links)} links (JS-rendered page - likely incomplete)"
            )

            section_count = 0
            for link in links:
                if section_count >= max_sections:
                    break

                link_text = link.get_text(strip=True)
                link_href = link.get("href", "")

                if not link_text or len(link_text) < 5 or link_href.endswith(".pdf"):
                    continue

                # Accept chapter/index and section-like entries, but skip PDFs.
                if link_href.lower().endswith(".pdf"):
                    continue
                is_candidate = (
                    bool(self._DE_CHAPTER_URL_RE.search(link_href))
                    or ("§" in link_text)
                    or bool(re.search(r"\b\d+\.[0-9A-Za-z\-]*", link_text))
                )
                if not is_candidate:
                    continue

                full_url = urljoin(code_url, link_href)

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = f"Section-{section_count + 1}"

                legal_area = self._identify_legal_area(link_text)

                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=link_text[:200],
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata(),
                )

                statutes.append(statute)
                section_count += 1

            self.logger.info(
                f"Delaware custom scraper: Scraped {len(statutes)} sections (JavaScript rendering required for full results)"
            )

        except Exception as e:
            self.logger.error(f"Delaware custom scraper failed: {e}")

        return statutes

    def official_title_url(self, title_number: int) -> str:
        return f"{self.get_base_url()}/title{int(title_number)}/index.html"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Delaware Code title catalog."""

        rows: List[Dict[str, Any]] = []
        for number in range(1, self.OFFICIAL_TITLE_COUNT + 1):
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"de:title-{number}",
                    "title_number": str(number),
                    "name": f"Title {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Delaware Code Title {number} official catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))

        def _request() -> bytes:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ipfs-datasets-delaware-official-catalog/1.0",
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    },
                )
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    return bytes(response.read() or b"")
            except Exception:
                try:
                    request = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "ipfs-datasets-delaware-official-catalog/1.0",
                            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    context = ssl._create_unverified_context()
                    with urllib.request.urlopen(
                        request, timeout=timeout, context=context
                    ) as response:
                        return bytes(response.read() or b"")
                except Exception:
                    return b""

        return _request()

    def _parse_official_title_links(self, html: bytes) -> Dict[str, str]:
        found: Dict[str, str] = {}
        if not html:
            return found
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return found
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(self.OFFICIAL_ENTRY_URL, href)
            match = self._DE_TITLE_NUMBER_RE.search(absolute)
            if not match:
                continue
            number = match.group(1).lstrip("0") or "0"
            if number not in found:
                found[number] = (
                    absolute
                    if absolute.endswith("index.html")
                    else self.official_title_url(int(number))
                )
        return found

    def fetch_official(self, code: str = "DE"):
        """Acquire the exhaustive official Delaware Code title catalog.

        Live HTTPS retains the official title index. Every Delaware Code title
        is enumerated with an official delcode URL. This hook never returns
        fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "DE").strip().upper() or "DE"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
        if len(rows) < 3:
            raise RuntimeError("delaware official catalog enumeration is incomplete")
        request = (
            f"GET {self.OFFICIAL_ENTRY_PATH} HTTP/1.1\n"
            f"host: {self.OFFICIAL_DOMAIN}\n"
        ).encode("utf-8")
        catalog = {
            "jurisdiction": normalized,
            "official_domain": self.OFFICIAL_DOMAIN,
            "entry_url": self.OFFICIAL_ENTRY_URL,
            "units": rows,
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


# Register this scraper with the registry
StateScraperRegistry.register("DE", DelawareScraper)
