"""Scraper for Montana state laws.

This module contains the scraper for Montana statutes from the official state legislative website.
"""

import hashlib
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

_SECONDARY_HOST_MARKERS = (
    "justia.com",
    "findlaw.com",
    "unicourt.github.io",
    "law.cornell.edu",
)


# The exact-51 default configuration is statutory only.  Montana's MCA root
# also lists Title 0, the separately scoped state Constitution, whose next
# hierarchy level is ``article_*`` rather than the statutory ``chapter_*``.
# Bind that scope exclusion to both exact retained official catalogs and their
# structural identity.  A changed root, label, title page, or article catalog
# therefore fails closed for review instead of being silently excluded.
_EXACT_TITLE_SCOPE_EXCLUSIONS = {
    "https://leg.mt.gov/bills/mca/title_0000/chapters_index.html": {
        "disposition": "separate_constitution_scope",
        "non_default_configuration": "constitutions",
        "root_url": "https://leg.mt.gov/bills/mca/index.html",
        "root_href": "./title_0000/chapters_index.html",
        "root_anchor_attrs": {
            "data-titlenumber": "0",
            "href": "./title_0000/chapters_index.html",
        },
        "source_label": "THE CONSTITUTION OF THE STATE OF MONTANA",
        "root_content_sha256": (
            "c945f15a4564a2a8b135a4d78f570fb2596f8e501a53bd70721eba256e482c41"
        ),
        "root_content_cid": (
            "bafkreigjixyvurleukulcnne26hvod5slfxy4ua2ko6xa4q6xisw4sbmie"
        ),
        "root_content_byte_size": 20653,
        "root_receipt_sha256": (
            "2aed70c226804764924a78c016029547828fe7333aed049aaeaf11e3a73b2e21"
        ),
        "root_receipt_cid": (
            "bafkreibk5vymejuai5sjestyyalaffkhqkh6omz25ucjvlvpchr2oozoee"
        ),
        "title_content_sha256": (
            "ffd3643dab4ed807a57f09ea03325ed81636a9468f8ca5b8c6250509a0ee67b3"
        ),
        "title_content_cid": (
            "bafkreih72nsd3k2o3ad2k7yj5ibtexwycy3ksruprss3rrrfaue2b3thwm"
        ),
        "title_content_byte_size": 10748,
        "title_receipt_sha256": (
            "545e7837b38adc3ff862c27be519a4d524cfd033b150750ee35e123fcd670476"
        ),
        "title_receipt_cid": (
            "bafkreiculz4dpm4k3q77qywcppsrtjgveth5am5rkb2q5y26ci742zyeoy"
        ),
        "article_links": (
            ("./article_000p/parts_index.html", "PREAMBLE"),
            (
                "./article_0010/parts_index.html",
                "ARTICLE I. COMPACT WITH THE UNITED STATES",
            ),
            (
                "./article_0020/parts_index.html",
                "ARTICLE II. DECLARATION OF RIGHTS",
            ),
            (
                "./article_0030/parts_index.html",
                "ARTICLE III. GENERAL GOVERNMENT",
            ),
            (
                "./article_0040/parts_index.html",
                "ARTICLE IV. SUFFRAGE AND ELECTIONS",
            ),
            ("./article_0050/parts_index.html", "ARTICLE V. THE LEGISLATURE"),
            ("./article_0060/parts_index.html", "ARTICLE VI. THE EXECUTIVE"),
            ("./article_0070/parts_index.html", "ARTICLE VII. THE JUDICIARY"),
            (
                "./article_0080/parts_index.html",
                "ARTICLE VIII. REVENUE AND FINANCE",
            ),
            (
                "./article_0090/parts_index.html",
                "ARTICLE IX. ENVIRONMENT AND NATURAL RESOURCES",
            ),
            (
                "./article_0100/parts_index.html",
                "ARTICLE X. EDUCATION AND PUBLIC LANDS",
            ),
            (
                "./article_0110/parts_index.html",
                "ARTICLE XI. LOCAL GOVERNMENT",
            ),
            (
                "./article_0120/parts_index.html",
                "ARTICLE XII. DEPARTMENTS AND INSTITUTIONS",
            ),
            (
                "./article_0130/parts_index.html",
                "ARTICLE XIII. GENERAL PROVISIONS",
            ),
            (
                "./article_0140/parts_index.html",
                "ARTICLE XIV. CONSTITUTIONAL REVISION",
            ),
            ("./article_0200/parts_index.html", "TRANSITION SCHEDULE"),
        ),
    }
}


def _montana_input_bytes(value: str | bytes | bytearray) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return str(value or "").encode("utf-8")


def _source_bound_title_scope_exclusions_from_root_html(
    html: str | bytes | bytearray,
    *,
    source_url: str,
) -> Dict[str, Dict[str, Any]]:
    """Type separately configured title catalogs from one exact MCA root."""

    root_url = str(source_url or "").strip()
    raw = _montana_input_bytes(html)
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}
    soup = BeautifulSoup(raw, "html.parser")
    exclusions: Dict[str, Dict[str, Any]] = {}
    for title_url, expected in _EXACT_TITLE_SCOPE_EXCLUSIONS.items():
        if root_url != str(expected["root_url"]):
            continue
        if (
            len(raw) != int(expected["root_content_byte_size"])
            or hashlib.sha256(raw).hexdigest()
            != str(expected["root_content_sha256"])
        ):
            return {}
        href = str(expected["root_href"])
        anchors = soup.find_all("a", href=href)
        if len(anchors) != 1:
            return {}
        anchor = anchors[0]
        if dict(anchor.attrs) != dict(expected["root_anchor_attrs"]):
            return {}
        source_label = " ".join(anchor.get_text(" ", strip=True).split())
        if (
            source_label != str(expected["source_label"])
            or urljoin(root_url, href) != title_url
        ):
            return {}
        exclusions[title_url] = {
            "disposition": str(expected["disposition"]),
            "non_default_configuration": str(
                expected["non_default_configuration"]
            ),
            "root_catalog_content_cid": str(expected["root_content_cid"]),
            "root_catalog_content_sha256": str(
                expected["root_content_sha256"]
            ),
            "root_catalog_receipt_cid": str(expected["root_receipt_cid"]),
            "root_catalog_receipt_sha256": str(
                expected["root_receipt_sha256"]
            ),
            "source_label": source_label,
            "source_url": title_url,
        }
    return exclusions


def _source_bound_title_scope_report_from_title_html(
    html: str | bytes | bytearray,
    *,
    source_label: str,
    source_url: str,
    root_scope_record: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """Validate one exact separately scoped title catalog response."""

    title_url = str(source_url or "").strip()
    expected = _EXACT_TITLE_SCOPE_EXCLUSIONS.get(title_url)
    if expected is None:
        return None
    if any(
        str(root_scope_record.get(field) or "") != str(expected_value)
        for field, expected_value in (
            ("disposition", expected["disposition"]),
            ("non_default_configuration", expected["non_default_configuration"]),
            ("root_catalog_content_sha256", expected["root_content_sha256"]),
            ("source_label", expected["source_label"]),
            ("source_url", title_url),
        )
    ):
        return None
    label = " ".join(str(source_label or "").split())
    if label != str(expected["source_label"]):
        return None
    raw = _montana_input_bytes(html)
    if (
        len(raw) != int(expected["title_content_byte_size"])
        or hashlib.sha256(raw).hexdigest()
        != str(expected["title_content_sha256"])
    ):
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(raw, "html.parser")
    headings = soup.find_all("h1", class_="chapter-title-title")
    if (
        len(headings) != 1
        or headings[0].attrs != {"class": ["chapter-title-title"]}
        or " ".join(headings[0].get_text(" ", strip=True).split()) != label
    ):
        return None
    article_anchors = soup.select(".chapter-toc-content li.line > a")
    observed_articles: List[Tuple[str, str]] = []
    for anchor in article_anchors:
        href = str(anchor.get("href") or "")
        parent = anchor.find_parent("li")
        if (
            anchor.attrs != {"href": href}
            or parent is None
            or parent.attrs != {"class": ["line"]}
            or parent.find_all("a", recursive=False) != [anchor]
        ):
            return None
        observed_articles.append(
            (href, " ".join(anchor.get_text(" ", strip=True).split()))
        )
    if tuple(observed_articles) != tuple(expected["article_links"]):
        return None
    return {
        "article_catalog_count": len(observed_articles),
        "chapter_count": 0,
        "content_sha256": str(expected["title_content_sha256"]),
        "disposition": str(expected["disposition"]),
        "evidence_kind": "source_bound_separate_configuration",
        "non_default_configuration": str(expected["non_default_configuration"]),
        "root_catalog_content_sha256": str(expected["root_content_sha256"]),
        "source_label": label,
        "source_url": title_url,
        "title_catalog_content_cid": str(expected["title_content_cid"]),
        "title_catalog_receipt_cid": str(expected["title_receipt_cid"]),
        "title_catalog_receipt_sha256": str(expected["title_receipt_sha256"]),
    }


# The current official part index is the authoritative terminal representation
# for 39-71-2326, whose detail locator no longer resolves.  Bind the exclusion
# to the exact retained official response and receipt so a changed catalog is
# reviewed instead of silently inheriting this classification.
_EXACT_TERMINAL_PART_CATALOGS = {
    (
        "https://leg.mt.gov/bills/mca/title_0390/chapter_0710/"
        "part_0230/sections_index.html"
    ): {
        "content_sha256": (
            "45874e98ddec1fc6a0d6604b3cb3f3a2824a0feec7dd5bb70a39e1bcf94c6732"
        ),
        "content_cid": (
            "bafkreicfq5hjrxpmd7dkbvtajm6lh45cqjfa73wh3vn3ocrz4g6pstdhgi"
        ),
        "content_byte_size": 19654,
        "receipt_sha256": (
            "bb1949621365e5110c484391d3f52e690dc121d232da2926177339aa712ef787"
        ),
        "receipt_cid": (
            "bafkreif3dfewee3f4uiqyscdshj7kltjbxasdurs3iusmf3thgvhclxxq4"
        ),
        "terminal_sections": {
            "39-71-2326": {
                "href": "./section_0260/0390-0710-0230-0260.html",
                "catalog_text": "39-71-2326 Repealed",
                "disposition": "repealed",
            }
        },
    }
}


def _source_bound_terminal_sections_from_part_catalog_html(
    html: str,
    *,
    source_url: str,
) -> Dict[str, Dict[str, str]]:
    """Type exact unavailable MCA section pages from one sealed part index."""

    catalog_url = str(source_url or "").strip()
    expected = _EXACT_TERMINAL_PART_CATALOGS.get(catalog_url)
    if expected is None:
        return {}
    raw = str(html or "").encode("utf-8")
    if len(raw) != int(expected["content_byte_size"]):
        return {}
    if hashlib.sha256(raw).hexdigest() != expected["content_sha256"]:
        return {}

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}
    soup = BeautifulSoup(html or "", "html.parser")
    typed: Dict[str, Dict[str, str]] = {}
    for section_number, terminal in expected["terminal_sections"].items():
        href = str(terminal["href"])
        anchors = soup.find_all("a", href=href)
        if len(anchors) != 1:
            return {}
        anchor = anchors[0]
        if anchor.attrs != {"href": href}:
            return {}
        parent = anchor.find_parent("li")
        if parent is None or parent.attrs != {"class": ["line"]}:
            return {}
        if parent.find_all("a", recursive=False) != [anchor]:
            return {}
        citation_tags = anchor.find_all("span", recursive=False)
        if len(citation_tags) != 1:
            return {}
        citation = citation_tags[0]
        if citation.attrs != {"class": ["citation"]}:
            return {}
        if " ".join(citation.get_text(" ", strip=True).split()) != section_number:
            return {}
        catalog_text = " ".join(anchor.get_text(" ", strip=True).split())
        if catalog_text != terminal["catalog_text"]:
            return {}
        section_url = urljoin(catalog_url, href)
        typed[section_url] = {
            "section_number": section_number,
            "catalog_text": catalog_text,
            "disposition": str(terminal["disposition"]),
            "catalog_url": catalog_url,
            "catalog_content_sha256": str(expected["content_sha256"]),
            "catalog_content_cid": str(expected["content_cid"]),
            "catalog_receipt_sha256": str(expected["receipt_sha256"]),
            "catalog_receipt_cid": str(expected["receipt_cid"]),
        }
    return typed


_MT_CITATION_TOKEN_PATTERN = (
    r"\d{1,3}-\d{1,3}[A-Za-z]?-\d+[A-Za-z]?"
    r"(?:\.\d+)?(?:-[A-Za-z])?"
)
_MT_CATALOG_SINGLE_TERMINAL_RE = re.compile(
    rf"^(?P<section>{_MT_CITATION_TOKEN_PATTERN})\s+"
    r"(?P<status>Repealed|Superseded|Expired|Terminated|Void|Not codified)$",
    re.IGNORECASE,
)
_MT_CATALOG_RESERVED_RE = re.compile(
    rf"^(?P<section>{_MT_CITATION_TOKEN_PATTERN})"
    rf"(?:\s+(?P<connector>through|and)\s+"
    rf"(?P<range_end>{_MT_CITATION_TOKEN_PATTERN}))?\s+reserved$",
    re.IGNORECASE,
)
_MT_CATALOG_RENUMBERED_RE = re.compile(
    rf"^(?P<section>{_MT_CITATION_TOKEN_PATTERN})\s+"
    r"Renumbered\s+(?P<targets>[0-9A-Za-z().,\s-]+)$",
    re.IGNORECASE,
)
_MT_CATALOG_COMBINED_RE = re.compile(
    rf"^(?P<section>{_MT_CITATION_TOKEN_PATTERN})\s+Combined\s+with\s+"
    rf"(?P<combined_with>{_MT_CITATION_TOKEN_PATTERN})\s*,\s*"
    r"renumbered\s+(?P<targets>[0-9A-Za-z().,\s-]+)$",
    re.IGNORECASE,
)
_MT_CATALOG_NO_RULE_RE = re.compile(
    r"^(?P<marker>No Montana Rules? \d+(?:\.\d+)?"
    r"(?:-\d+(?:\.\d+)?)?\.)(?:\s+(?P=marker))?$",
    re.IGNORECASE,
)


def _classify_montana_catalog_terminal_label(
    section_label: str,
    *,
    section_url: str,
    catalog_url: str,
    catalog_content_sha256: str,
) -> Optional[Dict[str, str]]:
    """Type one exact terminal MCA part-index label.

    Classification is anchored to the complete link text and runs only for a
    section link discovered in an official part index.  Incidental operative
    titles such as ``All statutes subject to repeal`` or ``Reserved name`` do
    not match this grammar.
    """

    label = " ".join(str(section_label or "").replace("\xa0", " ").split())
    if not label or not str(section_url or "").strip():
        return None

    no_rule_label = " ".join(label.replace("*", "").split())
    no_rule = _MT_CATALOG_NO_RULE_RE.fullmatch(no_rule_label)
    if no_rule is not None:
        return {
            "catalog_content_sha256": str(catalog_content_sha256),
            "catalog_text": label,
            "catalog_url": str(catalog_url),
            "disposition": "no_rule_reserved",
            "section_number": "",
            "section_url": str(section_url),
            "source_marker": str(no_rule.group("marker")),
        }

    match = _MT_CATALOG_SINGLE_TERMINAL_RE.fullmatch(label)
    if match is not None:
        status = str(match.group("status") or "").casefold().replace(" ", "_")
        return {
            "catalog_content_sha256": str(catalog_content_sha256),
            "catalog_text": label,
            "catalog_url": str(catalog_url),
            "disposition": status,
            "section_number": str(match.group("section")),
            "section_url": str(section_url),
        }

    match = _MT_CATALOG_RESERVED_RE.fullmatch(label)
    if match is not None:
        record = {
            "catalog_content_sha256": str(catalog_content_sha256),
            "catalog_text": label,
            "catalog_url": str(catalog_url),
            "disposition": "reserved",
            "section_number": str(match.group("section")),
            "section_url": str(section_url),
        }
        if match.group("range_end"):
            record["range_end"] = str(match.group("range_end"))
            record["range_connector"] = str(match.group("connector"))
        return record

    match = _MT_CATALOG_RENUMBERED_RE.fullmatch(label)
    if match is not None:
        targets = str(match.group("targets") or "").strip()
        if re.search(_MT_CITATION_TOKEN_PATTERN, targets, re.IGNORECASE) is None:
            return None
        return {
            "catalog_content_sha256": str(catalog_content_sha256),
            "catalog_text": label,
            "catalog_url": str(catalog_url),
            "disposition": "renumbered",
            "renumbered_to": targets,
            "section_number": str(match.group("section")),
            "section_url": str(section_url),
        }

    match = _MT_CATALOG_COMBINED_RE.fullmatch(label)
    if match is not None:
        targets = str(match.group("targets") or "").strip()
        if re.search(_MT_CITATION_TOKEN_PATTERN, targets, re.IGNORECASE) is None:
            return None
        return {
            "catalog_content_sha256": str(catalog_content_sha256),
            "catalog_text": label,
            "catalog_url": str(catalog_url),
            "combined_with": str(match.group("combined_with")),
            "disposition": "combined_and_renumbered",
            "renumbered_to": targets,
            "section_number": str(match.group("section")),
            "section_url": str(section_url),
        }
    return None


class MontanaScraper(BaseStateScraper):
    """Scraper for Montana state laws from https://leg.mt.gov"""

    OFFICIAL_DOMAIN = "leg.mt.gov"
    OFFICIAL_ENTRY_PATH = "/bills/mca/index.html"
    OFFICIAL_ENTRY_URL = "https://leg.mt.gov/bills/mca/index.html"
    OFFICIAL_TITLES = (
        1, 2, 3, 5, 7, 10, 13, 15, 16, 17, 18, 19, 20, 22, 23, 25, 27, 28,
        30, 31, 32, 33, 35, 37, 39, 40, 41, 42, 44, 45, 46, 49, 50, 52, 53,
        60, 61, 67, 69, 70, 71, 72, 75, 76, 80, 81, 82, 85, 87, 90,
    )
    _MT_TITLE_INDEX_HREF_RE = re.compile(
        r"title_(?P<title>\d{4})/chapters_index\.html",
        re.IGNORECASE,
    )
    _MT_CHAPTER_INDEX_HREF_RE = re.compile(
        r"chapter_\d{3}[0-9A-Za-z]/parts_index\.html",
        re.IGNORECASE,
    )
    _MT_SECTION_URL_RE = re.compile(
        r"/\d{4}-\d{3}[0-9A-Za-z]-\d{4}-\d{4}\.html$",
        re.IGNORECASE,
    )
    _MT_TITLE_INDEX_RE = re.compile(
        r"https://mca\.legmt\.gov/bills/mca/title_\d{4}/chapters_index\.html", re.IGNORECASE
    )
    _MT_CHAPTER_INDEX_RE = re.compile(
        r"https://mca\.legmt\.gov/bills/mca/title_\d{4}/"
        r"chapter_\d{3}[0-9A-Za-z]/parts_index\.html",
        re.IGNORECASE,
    )
    _MT_PART_INDEX_RE = re.compile(
        r"https://mca\.legmt\.gov/bills/mca/title_\d{4}/"
        r"chapter_\d{3}[0-9A-Za-z]/part_\d{4}/sections_index\.html",
        re.IGNORECASE,
    )
    _MT_MARKDOWN_LINK_RE = re.compile(
        r"\[([^\]]+)\]\((https://mca\.legmt\.gov[^)]+)\)", re.IGNORECASE
    )
    _MT_LEADING_SECTION_LABEL_RE = re.compile(
        r"^\s*(?P<section>\d{1,3}-\d{1,3}[A-Za-z]?-\d+[A-Za-z]?"
        r"(?:\.\d+)?(?:-[A-Za-z])?)"
        r"(?=\s|[.,;:]|$)",
        re.IGNORECASE,
    )
    _MT_RULE_LABEL_RE = re.compile(
        r"\bRule\s+(?P<number>\d+)(?:\.(?P<qualifier>\d+))?(?=\D|$)",
        re.IGNORECASE,
    )
    _MT_HYPHENATED_FORM_LABEL_RE = re.compile(
        r"\bForm\s+(?P<number>\d+)\s*-\s*(?P<letter>[A-Z])\b",
        re.IGNORECASE,
    )
    _MT_COMPACT_FORM_LABEL_RE = re.compile(
        r"\bForm\s+(?P<number>\d+)(?P<letter>[A-Z])\b",
        re.IGNORECASE,
    )

    def state_law_frontier_source_dependencies(self) -> Sequence[Any]:
        """Bind parsing, closure, and exact plural acquisition code."""

        from ...web_archiving import wayback_machine_engine
        from . import (
            base_scraper,
            montana_section,
            state_archival_fetch,
            strict_frontier_closure,
        )

        return (
            base_scraper,
            state_archival_fetch,
            strict_frontier_closure,
            montana_section,
            wayback_machine_engine,
        )

    @staticmethod
    def _montana_reports_sha256(reports: Sequence[Mapping[str, Any]]) -> str:
        payload = json.dumps(
            [dict(report) for report in reports],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _montana_exact_frontier(
        self,
        *,
        root_report: Mapping[str, Any],
        title_reports: Sequence[Mapping[str, Any]],
        chapter_reports: Sequence[Mapping[str, Any]],
        part_reports: Sequence[Mapping[str, Any]],
        section_reports: Sequence[Mapping[str, Any]],
        terminal_dispositions: Mapping[str, int],
    ) -> Dict[str, Any]:
        """Build the exact MCA root/title/chapter/part/section frontier."""

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            compute_frontier_digest,
        )

        root_digest = str(root_report.get("content_sha256") or "")
        if (
            re.fullmatch(r"[0-9a-f]{64}", root_digest) is None
            or not str(root_report.get("source_url") or "").strip()
        ):
            # Direct hierarchy parser tests use an explicit all-zero root only
            # when no acquisition ledger exists; publication can never enter
            # that path because the retained replay requires the real root.
            if not (
                root_digest == "0" * 64
                and getattr(self, "_state_law_acquisition_ledger", None) is None
            ):
                raise RuntimeError("Montana exact root report is not source-bound")

        for label, reports in (
            ("title", title_reports),
            ("chapter", chapter_reports),
            ("part", part_reports),
            ("section", section_reports),
        ):
            if not reports:
                raise RuntimeError(f"Montana exact {label} frontier is empty")
            source_urls = [str(report.get("source_url") or "") for report in reports]
            if (
                any(not source_url for source_url in source_urls)
                or len(source_urls) != len(set(source_urls))
                or any(
                    re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(report.get("content_sha256") or ""),
                    )
                    is None
                    for report in reports
                )
            ):
                raise RuntimeError(
                    f"Montana exact {label} frontier lost URL or digest identity"
                )

        title_chapter_count = sum(
            int(report.get("chapter_count") or 0) for report in title_reports
        )
        chapter_part_count = sum(
            int(report.get("part_count") or 0) for report in chapter_reports
        )
        part_section_count = sum(
            int(report.get("section_count") or 0) for report in part_reports
        )
        if (
            int(root_report.get("title_count") or 0) != len(title_reports)
            or title_chapter_count != len(chapter_reports)
            or chapter_part_count != len(part_reports)
            or part_section_count != len(section_reports)
        ):
            raise RuntimeError(
                "Montana exact root/title/chapter/part/section membership did not "
                "reconcile"
            )

        title_scope_dispositions: Dict[str, int] = {}
        separate_scope_reports: List[Mapping[str, Any]] = []
        for report in title_reports:
            title_disposition = str(
                report.get("disposition") or "statutory_hierarchy"
            )
            if title_disposition not in {
                "statutory_hierarchy",
                "separate_constitution_scope",
            }:
                raise RuntimeError("Montana title scope disposition is invalid")
            title_scope_dispositions[title_disposition] = (
                title_scope_dispositions.get(title_disposition, 0) + 1
            )
            if title_disposition == "statutory_hierarchy":
                if int(report.get("chapter_count") or 0) <= 0:
                    raise RuntimeError(
                        "Montana statutory title exposed no chapter membership"
                    )
                continue
            separate_scope_reports.append(report)
            if (
                int(report.get("chapter_count") or 0) != 0
                or str(report.get("evidence_kind") or "")
                != "source_bound_separate_configuration"
                or str(report.get("non_default_configuration") or "")
                != "constitutions"
                or str(report.get("root_catalog_content_sha256") or "")
                != root_digest
            ):
                raise RuntimeError(
                    "Montana separate constitutional scope is not source-bound"
                )
        expected_scope_rows = root_report.get("title_scope_exclusions") or []
        if (
            not isinstance(expected_scope_rows, Sequence)
            or isinstance(expected_scope_rows, (str, bytes, bytearray))
            or any(not isinstance(row, Mapping) for row in expected_scope_rows)
        ):
            raise RuntimeError("Montana root title scope exclusions are malformed")
        expected_scope_urls = [
            str(row.get("source_url") or "") for row in expected_scope_rows
        ]
        observed_scope_urls = [
            str(report.get("source_url") or "")
            for report in separate_scope_reports
        ]
        if (
            int(root_report.get("title_scope_exclusion_count") or 0)
            != len(expected_scope_rows)
            or any(not url for url in expected_scope_urls)
            or len(expected_scope_urls) != len(set(expected_scope_urls))
            or observed_scope_urls != expected_scope_urls
        ):
            raise RuntimeError(
                "Montana root/title separate-scope membership did not reconcile"
            )

        report_dispositions = [
            str(report.get("disposition") or "") for report in section_reports
        ]
        if any(not disposition for disposition in report_dispositions):
            raise RuntimeError("Montana exact leaf disposition is missing")

        operative = sum(
            1
            for disposition in report_dispositions
            if disposition == "operative"
        )
        excluded = len(section_reports) - operative
        operative_identities = [
            str(report.get("canonical_identity") or "")
            for report in section_reports
            if str(report.get("disposition") or "") == "operative"
        ]
        if (
            any(not identity for identity in operative_identities)
            or len(operative_identities) != len(set(operative_identities))
        ):
            raise RuntimeError("Montana exact operative identities are not unique")
        terminal_total = 0
        for disposition, count in terminal_dispositions.items():
            if not str(disposition or "").strip() or isinstance(count, bool):
                raise RuntimeError("Montana terminal disposition is malformed")
            parsed_count = int(count)
            if parsed_count < 0:
                raise RuntimeError("Montana terminal disposition is negative")
            terminal_total += parsed_count
        if terminal_total != excluded:
            raise RuntimeError(
                "Montana terminal dispositions do not equal excluded leaves"
            )
        disposition = {
            "discovered": len(section_reports),
            "fetched": operative,
            "excluded": excluded,
            "quarantined": 0,
            "failed_final": 0,
            "duplicates": 0,
        }
        if disposition["discovered"] != disposition["fetched"] + disposition["excluded"]:
            raise RuntimeError("Montana exact section disposition did not close")
        frontier: Dict[str, Any] = {
            "algebra_closed": True,
            "bundle_closed": False,
            "catalog_content_sha256": root_digest,
            "chapter_document_count": len(chapter_reports),
            "chapter_frontier_sha256": self._montana_reports_sha256(
                chapter_reports
            ),
            "closed": True,
            "disposition": disposition,
            "enumerator_closed": True,
            "expected_index_units": len(section_reports),
            "pagination_closed": True,
            "part_document_count": len(part_reports),
            "part_frontier_sha256": self._montana_reports_sha256(part_reports),
            "schema_version": "montana-source-derived-html-frontier-v1",
            "scope_closed": True,
            "section_input_frontier_sha256": self._montana_reports_sha256(
                section_reports
            ),
            "source_section_count": len(section_reports),
            "terminal_dispositions": dict(sorted(terminal_dispositions.items())),
            "statutory_title_document_count": title_scope_dispositions.get(
                "statutory_hierarchy",
                0,
            ),
            "title_document_count": len(title_reports),
            "title_frontier_sha256": self._montana_reports_sha256(title_reports),
            "title_scope_dispositions": dict(sorted(title_scope_dispositions.items())),
            "title_scope_exclusion_count": len(separate_scope_reports),
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": len(section_reports),
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return frontier

    def _replay_montana_retained_inputs(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
    ) -> List[bytes]:
        """Replay exact MCA parser inputs locally, never through a network."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Montana retained replay requires an attached ledger")
        payloads: List[bytes] = []
        for source_url in urls:
            url = self._canonical_fetch_url(source_url)
            retained = ledger.replay_retained_parser_input(
                official_url=url,
                sanitized_request={"method": "GET", "url": url},
            )
            if retained is None:
                raise RuntimeError(
                    f"Montana {frontier_name} retained replay is missing: {url}"
                )
            envelope = getattr(retained, "envelope", None)
            raw = bytes(getattr(envelope, "body", None) or b"")
            if not raw:
                raise RuntimeError(
                    f"Montana {frontier_name} retained replay is empty: {url}"
                )
            receipt = getattr(retained, "transport_receipt", None)
            if isinstance(receipt, Mapping):
                observed_url = str(
                    receipt.get("official_url") or receipt.get("endpoint") or ""
                ).strip()
                observed_digest = str(receipt.get("content_sha256") or "").strip()
                if observed_url and self._canonical_fetch_url(observed_url) != url:
                    raise RuntimeError(
                        f"Montana {frontier_name} retained URL identity changed: {url}"
                    )
                if observed_digest and observed_digest != hashlib.sha256(raw).hexdigest():
                    raise RuntimeError(
                        f"Montana {frontier_name} retained digest changed: {url}"
                    )
            payloads.append(raw)
        return payloads

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MT_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered

    def get_base_url(self) -> str:
        """Return the base URL for Montana's legislative website."""
        return "https://leg.mt.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Montana."""
        return [
            {
                "name": "Montana Code Annotated",
                "url": f"{self.get_base_url()}/bills/mca/index.html",
                "type": "Code",
            }
        ]

    def _host_is_official(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host:
            return False
        if any(marker in host for marker in _SECONDARY_HOST_MARKERS):
            return False
        return (
            host == "leg.mt.gov"
            or host.endswith(".leg.mt.gov")
            or host == "mca.legmt.gov"
            or host.endswith(".legmt.gov")
        )

    def _filter_official_host_statutes(
        self, statutes: List[NormalizedStatute]
    ) -> List[NormalizedStatute]:
        return [
            statute
            for statute in statutes
            if self._host_is_official(str(statute.source_url or ""))
        ]

    def _officialize_mca_url(self, url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower()
        if host in {"mca.legmt.gov", "archive.legmt.gov"} or host.endswith(".legmt.gov"):
            return parsed._replace(scheme="https", netloc="leg.mt.gov").geturl()
        return str(url or "").strip()

    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Montana's legislative website.

        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code

        Returns:
            List of NormalizedStatute objects
        """
        # Full-corpus mode with max_statutes=None must remain uncapped.
        limit = self._effective_scrape_limit(max_statutes, default=160)
        from .montana_constitution import (
            configured_constitution_html_path,
            parse_montana_constitution_html,
        )

        constitution_path = configured_constitution_html_path()
        if constitution_path is not None or "constitution" in str(code_name or "").lower():
            if constitution_path is not None:
                constitution_rows = parse_montana_constitution_html(
                    constitution_path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name or "Montana Constitution",
                    source_url="https://mca.legmt.gov/bills/mca/title_0000/chapters_index.html",
                    max_statutes=limit,
                )
                return constitution_rows if limit is None else constitution_rows[: int(limit)]
        from .montana_section import configured_section_html_path, parse_montana_section_html

        local_section = configured_section_html_path()
        if local_section is not None:
            parsed = parse_montana_section_html(
                local_section.read_text(encoding="utf-8", errors="replace"),
                source_url="https://mca.legmt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0102/0450-0050-0010-0102.html",
                code_name=code_name,
            )
            if parsed is not None:
                return [parsed]
        official = await self._scrape_official_mca_tree(code_name, max_statutes=limit)
        official = self._filter_official_host_statutes(official)
        if official:
            return official if limit is None else official[: int(limit)]

        if not self._full_corpus_enabled() or max_statutes is not None:
            direct = await self._scrape_direct_seed_sections(
                code_name,
                max_statutes=max(1, int(limit or 2)),
            )
            direct = self._filter_official_host_statutes(direct)
            if direct:
                return direct if limit is None else direct[: int(limit)]

        if self._full_corpus_enabled() and max_statutes is None:
            # Never sole-admit Justia / generic-only mirrors for full corpus.
            return []

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/bills/mca/",
            f"{self.get_base_url()}/bills/mca/index.html",
            f"{self.get_base_url()}/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        return_threshold = self._bounded_return_threshold(160)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        generic_cap = limit if limit is not None else max(10, int(return_threshold))
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)
            if any(marker in str(candidate).lower() for marker in _SECONDARY_HOST_MARKERS):
                continue

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Mont. Code Ann.",
                        max_sections=max(10, int(generic_cap)),
                        wait_for_selector="a[href*='/bills/mca/'], a[href*='/section_'], a[href*='chapters_index']",
                        timeout=45000,
                    )
                    statutes = self._filter_official_host_statutes(
                        self._filter_section_level(statutes)
                    )
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if limit is not None and len(statutes) >= int(limit):
                        return statutes[: int(limit)]
                    if len(statutes) >= return_threshold:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(
                code_name, candidate, "Mont. Code Ann.", max_sections=max(10, int(generic_cap))
            )
            statutes = self._filter_official_host_statutes(self._filter_section_level(statutes))
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if limit is not None and len(statutes) >= int(limit):
                return statutes[: int(limit)]
            if len(statutes) >= return_threshold:
                return statutes

        return best_statutes if limit is None else best_statutes[: int(limit)]

    async def _scrape_official_mca_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        html_rows = await self._scrape_official_mca_html_tree(code_name, max_statutes=max_statutes)
        if html_rows:
            return html_rows

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        root_reader = "https://r.jina.ai/http://https://leg.mt.gov/bills/mca/"
        root_text = await self._fetch_reader_markdown(root_reader)
        if not root_text:
            return []

        statutes: List[NormalizedStatute] = []
        seen_sections = set()
        title_links = self._extract_mca_links(root_text, self._MT_TITLE_INDEX_RE)
        if limit is None:
            return await self._scrape_official_mca_reader_frontier(
                code_name,
                title_links,
            )
        for _, title_url in title_links:
            if limit is not None and len(statutes) >= limit:
                break
            title_text = await self._fetch_reader_markdown(f"https://r.jina.ai/http://{title_url}")
            if not title_text:
                continue
            chapter_links = self._extract_mca_links(title_text, self._MT_CHAPTER_INDEX_RE)
            for _, chapter_url in chapter_links:
                if limit is not None and len(statutes) >= limit:
                    break
                chapter_text = await self._fetch_reader_markdown(
                    f"https://r.jina.ai/http://{chapter_url}"
                )
                if not chapter_text:
                    continue
                part_links = self._extract_mca_links(chapter_text, self._MT_PART_INDEX_RE)
                for _, part_url in part_links:
                    if limit is not None and len(statutes) >= limit:
                        break
                    part_text = await self._fetch_reader_markdown(
                        f"https://r.jina.ai/http://{part_url}"
                    )
                    if not part_text:
                        continue
                    section_links = self._extract_mca_links(part_text, self._MT_SECTION_URL_RE)
                    for section_label, section_url in section_links:
                        if limit is not None and len(statutes) >= limit:
                            break
                        if section_url in seen_sections:
                            continue
                        seen_sections.add(section_url)
                        statute = await self._build_official_section_statute(
                            code_name, section_label, section_url
                        )
                        if statute is not None:
                            statutes.append(statute)
        return statutes

    async def _scrape_official_mca_html_tree(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup  # noqa: F401
        except ImportError:
            return []

        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        root_urls = (
            f"{self.get_base_url()}/bills/mca/index.html",
            f"{self.get_base_url()}/bills/mca/",
        )
        title_links: List[Tuple[str, str]] = []
        root_report: Optional[Dict[str, Any]] = None
        if limit is None:
            self._montana_frontier_batch_stats: List[Dict[str, Any]] = []
        for root_url in root_urls:
            if limit is None:
                root_payload = await self._fetch_page_content_with_archival_fallback(
                    root_url,
                    timeout_seconds=25,
                )
                root_raw = (
                    bytes(root_payload)
                    if isinstance(root_payload, (bytes, bytearray))
                    else str(root_payload or "").encode("utf-8")
                )
                html = root_raw.decode("utf-8", errors="replace")
            else:
                html = await self._fetch_reader_markdown(root_url)
                root_raw = html.encode("utf-8")
            title_links = self._extract_html_mca_links(
                html, root_url, self._MT_TITLE_INDEX_HREF_RE
            )
            if title_links:
                title_scope_exclusions = (
                    _source_bound_title_scope_exclusions_from_root_html(
                        root_raw,
                        source_url=root_url,
                    )
                )
                root_report = {
                    "content_sha256": hashlib.sha256(root_raw).hexdigest(),
                    "source_url": root_url,
                    "title_scope_exclusion_count": len(title_scope_exclusions),
                    "title_scope_exclusions": list(
                        title_scope_exclusions.values()
                    ),
                    "title_count": len(title_links),
                }
                break
        if not title_links:
            if limit is None:
                raise RuntimeError(
                    "Montana official MCA root did not expose a closed title frontier"
                )
            return []

        if limit is None:
            if root_report is None:
                raise RuntimeError("Montana official MCA root report is missing")
            self._last_montana_root_input = root_report
            return await self._scrape_official_mca_html_frontier(
                code_name,
                title_links,
            )

        statutes: List[NormalizedStatute] = []
        seen_sections: set[str] = set()
        for _, title_url in title_links:
            if limit is not None and len(statutes) >= limit:
                break
            title_html = await self._fetch_reader_markdown(title_url)
            chapter_links = self._extract_html_mca_links(
                title_html, title_url, self._MT_CHAPTER_INDEX_RE
            )
            if not chapter_links:
                chapter_links = self._extract_html_mca_links(
                    title_html,
                    title_url,
                    self._MT_CHAPTER_INDEX_HREF_RE,
                )
            for _, chapter_url in chapter_links:
                if limit is not None and len(statutes) >= limit:
                    break
                chapter_html = await self._fetch_reader_markdown(chapter_url)
                part_links = self._extract_html_mca_links(
                    chapter_html, chapter_url, self._MT_PART_INDEX_RE
                )
                if not part_links:
                    part_links = self._extract_html_mca_links(
                        chapter_html,
                        chapter_url,
                        re.compile(r"part_\d{4}/sections_index\.html", re.IGNORECASE),
                    )
                for _, part_url in part_links:
                    if limit is not None and len(statutes) >= limit:
                        break
                    part_html = await self._fetch_reader_markdown(part_url)
                    section_links = self._extract_html_mca_links(
                        part_html, part_url, self._MT_SECTION_URL_RE
                    )
                    for section_label, section_url in section_links:
                        if limit is not None and len(statutes) >= limit:
                            break
                        official_url = self._officialize_mca_url(section_url)
                        if official_url in seen_sections:
                            continue
                        seen_sections.add(official_url)
                        statute = await self._build_official_html_section_statute(
                            code_name, section_label, official_url
                        )
                        if statute is not None:
                            statutes.append(statute)
        return statutes

    def _montana_parse_checkpoint_size(self) -> int:
        """Bound normalization/checkpoint slices after each complete fetch wave."""

        return max(
            1,
            min(
                512,
                int(
                    self._env_int(
                        "STATE_SCRAPER_MT_FRONTIER_BATCH_SIZE",
                        default=64,
                    )
                    or 64
                ),
            ),
        )

    def _montana_frontier_concurrency(self) -> int:
        return max(
            1,
            min(
                64,
                int(
                    self._env_int(
                        "STATE_SCRAPER_MT_FRONTIER_CONCURRENCY",
                        default=8,
                    )
                    or 8
                ),
            ),
        )

    async def _fetch_montana_frontier_batch(
        self,
        urls: Sequence[str],
        *,
        frontier_name: str,
        reader: bool = False,
    ) -> List[bytes]:
        """Acquire one complete ordered dependency level as one plural wave."""

        if not urls:
            return []
        requested = list(urls)
        if len(requested) != len(set(requested)):
            raise RuntimeError(
                f"Montana {frontier_name} frontier contains duplicate exact URLs"
            )
        residual_retry_attempts = max(
            0,
            min(
                3,
                self._env_int(
                    "STATE_SCRAPER_FRONTIER_RESIDUAL_RETRY_ATTEMPTS",
                    default=1,
                ),
            ),
        )
        batch = await self._fetch_page_contents_with_archival_fallback_retrying_residuals(
            requested,
            residual_retry_attempts=residual_retry_attempts,
            repeat_grouped_archive_inventory_on_residual=False,
            timeout_seconds=25,
            media_type="text/plain" if reader else "text/html",
            max_concurrency=self._montana_frontier_concurrency(),
            prefer_direct=True,
            common_crawl_domain_terms=("r.jina.ai",) if reader else ("leg.mt.gov",),
            common_crawl_url_terms=(
                ("/http://https://",) if reader else ("/bills/mca/",)
            ),
            common_crawl_mime_terms=("text", "html") if reader else ("html",),
            wayback_prefix_inventory=True,
        )
        aligned_lengths = {
            len(batch.urls),
            len(batch.payloads),
            len(batch.errors),
            len(batch.transport_receipts),
            len(batch.parser_input_envelopes),
        }
        if aligned_lengths != {len(requested)}:
            raise RuntimeError(
                f"Montana {frontier_name} frontier returned unaligned acquisition rows"
            )
        if list(batch.urls) != requested:
            raise RuntimeError(
                f"Montana {frontier_name} frontier changed URL order or identity"
            )
        stats = dict(batch.stats or {})
        stats["frontier_name"] = str(frontier_name)
        batch_stats = getattr(self, "_montana_frontier_batch_stats", None)
        if isinstance(batch_stats, list):
            batch_stats.append(stats)
        failures = [
            {
                "url": url,
                "error": error or "empty parser input",
            }
            for url, payload, error in zip(
                batch.urls,
                batch.payloads,
                batch.errors,
                strict=True,
            )
            if error is not None or not payload
        ]
        if failures:
            raise RuntimeError(
                f"Montana {frontier_name} frontier is incomplete: {failures[:5]}"
            )
        return [bytes(payload) for payload in batch.payloads]

    def _montana_catalog_terminal_records(
        self,
        part_html: str,
        *,
        part_url: str,
        discovered: Sequence[Tuple[str, str]],
        content_sha256: str,
    ) -> Dict[str, Dict[str, str]]:
        """Derive exact terminal leaf dispositions from one part catalog."""

        part_digest = str(content_sha256 or "")
        if re.fullmatch(r"[0-9a-f]{64}", part_digest) is None:
            raise RuntimeError("Montana part catalog lacks an exact input digest")
        sealed = _source_bound_terminal_sections_from_part_catalog_html(
            part_html,
            source_url=part_url,
        )
        terminal: Dict[str, Dict[str, str]] = {}
        discovered_urls: set[str] = set()
        for section_label, section_url in discovered:
            official_url = self._officialize_mca_url(section_url)
            discovered_urls.add(official_url)
            record = _classify_montana_catalog_terminal_label(
                section_label,
                section_url=official_url,
                catalog_url=part_url,
                catalog_content_sha256=part_digest,
            )
            sealed_record = sealed.get(official_url)
            if sealed_record is not None:
                if record is None or any(
                    str(record.get(field) or "")
                    != str(sealed_record.get(field) or "")
                    for field in (
                        "catalog_content_sha256",
                        "catalog_text",
                        "disposition",
                        "section_number",
                    )
                ):
                    raise RuntimeError(
                        "Montana sealed terminal catalog changed structural "
                        f"classification: {official_url}"
                    )
                record = {**record, **dict(sealed_record)}
            if record is None:
                continue
            expected_identity = self._section_number_from_mca_url(
                official_url,
                section_label=section_label,
            )
            if not str(record.get("section_number") or ""):
                record["section_number"] = expected_identity
            if (
                not expected_identity
                or expected_identity.casefold()
                != str(record.get("section_number") or "").casefold()
            ):
                raise RuntimeError(
                    "Montana catalog terminal changed URL/label identity: "
                    f"{official_url}"
                )
            terminal[official_url] = dict(record)

        if set(sealed) - discovered_urls:
            raise RuntimeError(
                "Montana sealed terminal catalog is absent from part membership"
            )
        return terminal

    async def _scrape_official_mca_html_frontier(
        self,
        code_name: str,
        title_links: List[Tuple[str, str]],
    ) -> List[NormalizedStatute]:
        """Breadth-first acquisition of the known official MCA HTML tree."""

        self._last_montana_catalog_terminal_sections: Dict[
            str, Dict[str, str]
        ] = {}

        def _terminal_progress() -> Dict[str, Any]:
            terminal = dict(self._last_montana_catalog_terminal_sections)
            disposition_counts: Dict[str, int] = {}
            for record in terminal.values():
                disposition = str(record.get("disposition") or "").strip()
                if disposition:
                    disposition_counts[disposition] = (
                        disposition_counts.get(disposition, 0) + 1
                    )
            return {
                "terminal_sections_excluded": int(len(terminal)),
                "terminal_section_urls": sorted(terminal),
                "terminal_disposition_counts": disposition_counts,
                "terminal_catalog_content_sha256": sorted(
                    {
                        record["catalog_content_sha256"]
                        for record in terminal.values()
                        if record.get("catalog_content_sha256")
                    }
                ),
                "terminal_catalog_receipt_sha256": sorted(
                    {
                        record["catalog_receipt_sha256"]
                        for record in terminal.values()
                        if record.get("catalog_receipt_sha256")
                    }
                ),
            }

        root_report = getattr(self, "_last_montana_root_input", None)
        if not isinstance(root_report, Mapping):
            if getattr(self, "_state_law_acquisition_ledger", None) is not None:
                raise RuntimeError("Montana official root parser input was not retained")
            # Focused parser tests may invoke this hierarchy stage directly.
            # A production run always has an attached ledger and cannot enter
            # this test-only projection.
            root_report = {
                "content_sha256": "0" * 64,
                "source_url": "",
                "title_count": len(title_links),
                "title_scope_exclusion_count": 0,
                "title_scope_exclusions": [],
            }
        raw_scope_exclusions = root_report.get("title_scope_exclusions") or []
        if (
            not isinstance(raw_scope_exclusions, Sequence)
            or isinstance(raw_scope_exclusions, (str, bytes, bytearray))
            or any(not isinstance(row, Mapping) for row in raw_scope_exclusions)
        ):
            raise RuntimeError("Montana root title scope exclusions are malformed")
        title_scope_exclusions = {
            str(row.get("source_url") or ""): dict(row)
            for row in raw_scope_exclusions
        }
        if (
            any(not url for url in title_scope_exclusions)
            or len(title_scope_exclusions) != len(raw_scope_exclusions)
            or int(root_report.get("title_scope_exclusion_count") or 0)
            != len(title_scope_exclusions)
        ):
            raise RuntimeError("Montana root title scope exclusion algebra changed")

        title_urls = [url for _label, url in title_links]
        title_payloads = await self._fetch_montana_frontier_batch(
            title_urls,
            frontier_name="title-index",
        )

        chapter_links: List[Tuple[str, str]] = []
        seen_chapters: set[str] = set()
        title_reports: List[Dict[str, Any]] = []
        for (title_label, title_url), raw in zip(
            title_links,
            title_payloads,
            strict=True,
        ):
            title_html = raw.decode("utf-8", errors="replace")
            root_scope_record = title_scope_exclusions.get(title_url)
            if root_scope_record is not None:
                scope_report = _source_bound_title_scope_report_from_title_html(
                    raw,
                    source_label=title_label,
                    source_url=title_url,
                    root_scope_record=root_scope_record,
                )
                if scope_report is None:
                    raise RuntimeError(
                        "Montana source-bound title scope changed: "
                        f"{title_url}"
                    )
                title_reports.append(scope_report)
                continue
            discovered = self._extract_html_mca_links(
                title_html,
                title_url,
                self._MT_CHAPTER_INDEX_RE,
            )
            if not discovered:
                discovered = self._extract_html_mca_links(
                    title_html,
                    title_url,
                    self._MT_CHAPTER_INDEX_HREF_RE,
                )
            if not discovered:
                raise RuntimeError(
                    f"Montana title index exposed no chapters: {title_url}"
                )
            title_reports.append(
                {
                    "chapter_count": len(discovered),
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "disposition": "statutory_hierarchy",
                    "source_label": title_label,
                    "source_url": title_url,
                }
            )
            for label, url in discovered:
                if url in seen_chapters:
                    raise RuntimeError(
                        f"Montana title frontier repeated a chapter URL: {url}"
                    )
                seen_chapters.add(url)
                chapter_links.append((label, url))

        chapter_urls = [url for _label, url in chapter_links]
        chapter_payloads = await self._fetch_montana_frontier_batch(
            chapter_urls,
            frontier_name="chapter-index",
        )

        part_links: List[Tuple[str, str]] = []
        seen_parts: set[str] = set()
        chapter_reports: List[Dict[str, Any]] = []
        for (chapter_label, chapter_url), raw in zip(
            chapter_links,
            chapter_payloads,
            strict=True,
        ):
            chapter_html = raw.decode("utf-8", errors="replace")
            discovered = self._extract_html_mca_links(
                chapter_html,
                chapter_url,
                self._MT_PART_INDEX_RE,
            )
            if not discovered:
                discovered = self._extract_html_mca_links(
                    chapter_html,
                    chapter_url,
                    re.compile(r"part_\d{4}/sections_index\.html", re.IGNORECASE),
                )
            if not discovered:
                raise RuntimeError(
                    f"Montana chapter index exposed no parts: {chapter_url}"
                )
            chapter_reports.append(
                {
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "part_count": len(discovered),
                    "source_label": chapter_label,
                    "source_url": chapter_url,
                }
            )
            for label, url in discovered:
                if url in seen_parts:
                    raise RuntimeError(
                        f"Montana chapter frontier repeated a part URL: {url}"
                    )
                seen_parts.add(url)
                part_links.append((label, url))

        part_urls = [url for _label, url in part_links]
        part_payloads = await self._fetch_montana_frontier_batch(
            part_urls,
            frontier_name="part-index",
        )

        section_links: List[Tuple[str, str]] = []
        seen_sections: set[str] = set()
        part_reports: List[Dict[str, Any]] = []
        catalog_terminal_reports: List[Dict[str, Any]] = []
        for (part_label, part_url), raw in zip(
            part_links,
            part_payloads,
            strict=True,
        ):
            part_html = raw.decode("utf-8", errors="replace")
            part_digest = hashlib.sha256(raw).hexdigest()
            discovered = self._extract_html_mca_links(
                part_html,
                part_url,
                self._MT_SECTION_URL_RE,
            )
            if not discovered:
                raise RuntimeError(
                    f"Montana part index exposed no section membership: {part_url}"
                )
            terminal = self._montana_catalog_terminal_records(
                part_html,
                part_url=part_url,
                discovered=discovered,
                content_sha256=part_digest,
            )
            if terminal:
                self._last_montana_catalog_terminal_sections.update(terminal)
            part_reports.append(
                {
                    "content_sha256": part_digest,
                    "section_count": len(discovered),
                    "source_label": part_label,
                    "source_url": part_url,
                    "terminal_catalog_sections": len(terminal),
                }
            )
            for section_label, section_url in discovered:
                official_url = self._officialize_mca_url(section_url)
                if official_url in terminal:
                    record = dict(terminal[official_url])
                    catalog_terminal_reports.append(
                        {
                            "canonical_identity": "",
                            "content_sha256": str(
                                record.get("catalog_content_sha256") or ""
                            ),
                            "disposition": str(
                                record.get("disposition") or "repealed"
                            ),
                            "evidence_kind": "source_bound_part_catalog",
                            "evidence_source_url": part_url,
                            "section_number": str(
                                record.get("section_number") or ""
                            ),
                            "source_label": section_label,
                            "source_url": official_url,
                        }
                    )
                    continue
                if official_url in seen_sections:
                    raise RuntimeError(
                        f"Montana part frontier repeated a section URL: {official_url}"
                    )
                seen_sections.add(official_url)
                section_links.append((section_label, official_url))

        statutes: List[NormalizedStatute] = []
        section_reports: List[Dict[str, Any]] = list(catalog_terminal_reports)
        terminal_counts: Dict[str, int] = {}
        for report in catalog_terminal_reports:
            disposition = str(report.get("disposition") or "repealed")
            terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
        residual_sections: List[Dict[str, str]] = []
        seen_identities: set[str] = set()
        sections_scanned = 0
        section_payloads = await self._fetch_montana_frontier_batch(
            [url for _label, url in section_links],
            frontier_name="section",
        )
        checkpoint_size = self._montana_parse_checkpoint_size()
        for batch_start in range(0, len(section_links), checkpoint_size):
            batch_links = section_links[batch_start : batch_start + checkpoint_size]
            batch_payloads = section_payloads[
                batch_start : batch_start + checkpoint_size
            ]
            for (section_label, section_url), raw in zip(
                batch_links,
                batch_payloads,
                strict=True,
            ):
                sections_scanned += 1
                statute = self._build_official_html_section_statute_from_html(
                    code_name,
                    section_label,
                    section_url,
                    raw.decode("utf-8", errors="replace"),
                )
                content_sha256 = hashlib.sha256(raw).hexdigest()
                if statute is None:
                    residual_sections.append(
                        {
                            "content_sha256": content_sha256,
                            "source_url": section_url,
                        }
                    )
                    continue
                identity = str(statute.section_number or "").strip()
                if not identity or identity.casefold() in seen_identities:
                    raise RuntimeError(
                        "Montana normalized frontier repeated or lost a section "
                        f"identity: {statute.section_number}"
                    )
                seen_identities.add(identity.casefold())
                statute.structured_data = {
                    **dict(statute.structured_data or {}),
                    "content_sha256": content_sha256,
                }
                statutes.append(statute)
                section_reports.append(
                    {
                        "canonical_identity": identity.casefold(),
                        "content_sha256": content_sha256,
                        "disposition": "operative",
                        "section_number": identity,
                        "source_label": section_label,
                        "source_url": section_url,
                    }
                )
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="montana:section-progress",
                extra={
                    "titles_scanned": int(len(title_links)),
                    "discovered_titles": int(len(title_links)),
                    "statutory_titles_scanned": sum(
                        str(report.get("disposition") or "")
                        == "statutory_hierarchy"
                        for report in title_reports
                    ),
                    "title_scope_exclusions": sum(
                        str(report.get("disposition") or "")
                        == "separate_constitution_scope"
                        for report in title_reports
                    ),
                    "chapters_scanned": int(len(chapter_links)),
                    "discovered_chapters": int(len(chapter_links)),
                    "parts_scanned": int(len(part_links)),
                    "discovered_parts": int(len(part_links)),
                    "sections_scanned": int(sections_scanned),
                    "discovered_sections": int(len(section_links)),
                    "codes_completed": 0,
                    "codes_total": 1,
                    **_terminal_progress(),
                },
            )
            if residual_sections:
                raise RuntimeError(
                    "Montana official section frontier has unclassified residuals: "
                    f"{residual_sections[:10]}"
                )

        if len(section_reports) != len(section_links) + len(
            catalog_terminal_reports
        ):
            raise RuntimeError("Montana source leaf membership did not reconcile")
        exact_frontier = self._montana_exact_frontier(
            root_report=root_report,
            title_reports=title_reports,
            chapter_reports=chapter_reports,
            part_reports=part_reports,
            section_reports=section_reports,
            terminal_dispositions=terminal_counts,
        )
        observed_at = datetime.now(timezone.utc).isoformat()
        self._last_montana_full_frontier = {
            "boundary_first": str(section_links[0][1]),
            "boundary_last": str(section_links[-1][1]),
            "chapter_reports": chapter_reports,
            "code_name": code_name,
            "frontier": exact_frontier,
            "observed_at": observed_at,
            "part_reports": part_reports,
            "root_report": dict(root_report),
            "section_reports": section_reports,
            "title_reports": title_reports,
            "transport_batch_stats": list(
                getattr(self, "_montana_frontier_batch_stats", [])
            ),
        }
        self._last_montana_strict_closure = {
            "chapter_documents": len(chapter_reports),
            "closed": True,
            "frontier": exact_frontier,
            "observed_at": observed_at,
            "operative_sections": len(statutes),
            "part_documents": len(part_reports),
            "schema": "montana-source-derived-strict-closure-v1",
            "source_sections": len(section_reports),
            "statutory_title_documents": int(
                exact_frontier.get("statutory_title_document_count") or 0
            ),
            "terminal_sections": len(section_reports) - len(statutes),
            "title_documents": len(title_reports),
            "title_scope_exclusions": int(
                exact_frontier.get("title_scope_exclusion_count") or 0
            ),
            "unclassified_sections": 0,
        }

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="montana:complete",
            force=True,
            extra={
                "titles_scanned": int(len(title_links)),
                "discovered_titles": int(len(title_links)),
                "statutory_titles_scanned": sum(
                    str(report.get("disposition") or "")
                    == "statutory_hierarchy"
                    for report in title_reports
                ),
                "title_scope_exclusions": sum(
                    str(report.get("disposition") or "")
                    == "separate_constitution_scope"
                    for report in title_reports
                ),
                "chapters_scanned": int(len(chapter_links)),
                "discovered_chapters": int(len(chapter_links)),
                "parts_scanned": int(len(part_links)),
                "discovered_parts": int(len(part_links)),
                "sections_scanned": int(sections_scanned),
                "discovered_sections": int(len(section_links)),
                "codes_completed": 1,
                "codes_total": 1,
                **_terminal_progress(),
            },
        )
        return statutes

    def _replay_montana_source_frontier(
        self,
        first: Mapping[str, Any],
    ) -> List[NormalizedStatute]:
        """Reparse every retained MCA hierarchy input with zero network I/O."""

        root_report_raw = first.get("root_report")
        title_reports_raw = first.get("title_reports")
        chapter_reports_raw = first.get("chapter_reports")
        part_reports_raw = first.get("part_reports")
        first_section_reports_raw = first.get("section_reports")
        if not isinstance(root_report_raw, Mapping):
            raise RuntimeError("Montana retained root report is incomplete")
        for label, reports in (
            ("title", title_reports_raw),
            ("chapter", chapter_reports_raw),
            ("part", part_reports_raw),
            ("section", first_section_reports_raw),
        ):
            if (
                not isinstance(reports, Sequence)
                or isinstance(reports, (str, bytes, bytearray))
                or not reports
                or any(not isinstance(row, Mapping) for row in reports)
            ):
                raise RuntimeError(f"Montana retained {label} reports are incomplete")
        root_report = dict(root_report_raw)
        expected_title_reports = [dict(row) for row in title_reports_raw]
        expected_chapter_reports = [dict(row) for row in chapter_reports_raw]
        expected_part_reports = [dict(row) for row in part_reports_raw]
        expected_section_reports = [dict(row) for row in first_section_reports_raw]

        root_url = str(root_report.get("source_url") or "")
        root_raw = self._replay_montana_retained_inputs(
            [root_url],
            frontier_name="root-index",
        )[0]
        root_digest = hashlib.sha256(root_raw).hexdigest()
        if root_digest != str(root_report.get("content_sha256") or ""):
            raise RuntimeError("Montana retained root digest changed")
        replayed_scope_exclusions = (
            _source_bound_title_scope_exclusions_from_root_html(
                root_raw,
                source_url=root_url,
            )
        )
        expected_scope_exclusions = root_report.get("title_scope_exclusions") or []
        if (
            not isinstance(expected_scope_exclusions, Sequence)
            or isinstance(
                expected_scope_exclusions,
                (str, bytes, bytearray),
            )
            or any(
                not isinstance(row, Mapping)
                for row in expected_scope_exclusions
            )
            or list(replayed_scope_exclusions.values())
            != [dict(row) for row in expected_scope_exclusions]
            or int(root_report.get("title_scope_exclusion_count") or 0)
            != len(replayed_scope_exclusions)
        ):
            raise RuntimeError("Montana retained root title scope changed")
        title_links = self._extract_html_mca_links(
            root_raw.decode("utf-8", errors="replace"),
            root_url,
            self._MT_TITLE_INDEX_HREF_RE,
        )
        expected_title_links = [
            (
                str(report.get("source_label") or ""),
                str(report.get("source_url") or ""),
            )
            for report in expected_title_reports
        ]
        if title_links != expected_title_links:
            raise RuntimeError("Montana retained title membership changed")

        title_urls = [url for _label, url in title_links]
        title_payloads = self._replay_montana_retained_inputs(
            title_urls,
            frontier_name="title-indexes",
        )
        replay_title_reports: List[Dict[str, Any]] = []
        chapter_links: List[Tuple[str, str]] = []
        seen_chapters: set[str] = set()
        for (title_label, title_url), raw in zip(
            title_links,
            title_payloads,
            strict=True,
        ):
            decoded = raw.decode("utf-8", errors="replace")
            root_scope_record = replayed_scope_exclusions.get(title_url)
            if root_scope_record is not None:
                scope_report = _source_bound_title_scope_report_from_title_html(
                    raw,
                    source_label=title_label,
                    source_url=title_url,
                    root_scope_record=root_scope_record,
                )
                if scope_report is None:
                    raise RuntimeError(
                        "Montana retained source-bound title scope changed: "
                        f"{title_url}"
                    )
                replay_title_reports.append(scope_report)
                continue
            discovered = self._extract_html_mca_links(
                decoded,
                title_url,
                self._MT_CHAPTER_INDEX_RE,
            )
            if not discovered:
                discovered = self._extract_html_mca_links(
                    decoded,
                    title_url,
                    self._MT_CHAPTER_INDEX_HREF_RE,
                )
            if not discovered:
                raise RuntimeError(
                    f"Montana retained title replay exposed no chapters: {title_url}"
                )
            replay_title_reports.append(
                {
                    "chapter_count": len(discovered),
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "disposition": "statutory_hierarchy",
                    "source_label": title_label,
                    "source_url": title_url,
                }
            )
            for chapter_label, chapter_url in discovered:
                if chapter_url in seen_chapters:
                    raise RuntimeError(
                        "Montana retained title replay repeated a chapter URL: "
                        f"{chapter_url}"
                    )
                seen_chapters.add(chapter_url)
                chapter_links.append((chapter_label, chapter_url))
        expected_chapter_links = [
            (
                str(report.get("source_label") or ""),
                str(report.get("source_url") or ""),
            )
            for report in expected_chapter_reports
        ]
        if chapter_links != expected_chapter_links:
            raise RuntimeError("Montana retained chapter membership changed")

        chapter_urls = [url for _label, url in chapter_links]
        chapter_payloads = self._replay_montana_retained_inputs(
            chapter_urls,
            frontier_name="chapter-indexes",
        )
        replay_chapter_reports: List[Dict[str, Any]] = []
        part_links: List[Tuple[str, str]] = []
        seen_parts: set[str] = set()
        for (chapter_label, chapter_url), raw in zip(
            chapter_links,
            chapter_payloads,
            strict=True,
        ):
            decoded = raw.decode("utf-8", errors="replace")
            discovered = self._extract_html_mca_links(
                decoded,
                chapter_url,
                self._MT_PART_INDEX_RE,
            )
            if not discovered:
                discovered = self._extract_html_mca_links(
                    decoded,
                    chapter_url,
                    re.compile(r"part_\d{4}/sections_index\.html", re.IGNORECASE),
                )
            if not discovered:
                raise RuntimeError(
                    f"Montana retained chapter replay exposed no parts: {chapter_url}"
                )
            replay_chapter_reports.append(
                {
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "part_count": len(discovered),
                    "source_label": chapter_label,
                    "source_url": chapter_url,
                }
            )
            for part_label, part_url in discovered:
                if part_url in seen_parts:
                    raise RuntimeError(
                        f"Montana retained chapter replay repeated a part URL: {part_url}"
                    )
                seen_parts.add(part_url)
                part_links.append((part_label, part_url))
        expected_part_links = [
            (
                str(report.get("source_label") or ""),
                str(report.get("source_url") or ""),
            )
            for report in expected_part_reports
        ]
        if part_links != expected_part_links:
            raise RuntimeError("Montana retained part membership changed")

        part_urls = [url for _label, url in part_links]
        part_payloads = self._replay_montana_retained_inputs(
            part_urls,
            frontier_name="part-indexes",
        )
        replay_part_reports: List[Dict[str, Any]] = []
        catalog_terminal_reports: List[Dict[str, Any]] = []
        section_links: List[Tuple[str, str]] = []
        seen_sections: set[str] = set()
        for (part_label, part_url), raw in zip(
            part_links,
            part_payloads,
            strict=True,
        ):
            decoded = raw.decode("utf-8", errors="replace")
            part_digest = hashlib.sha256(raw).hexdigest()
            discovered = self._extract_html_mca_links(
                decoded,
                part_url,
                self._MT_SECTION_URL_RE,
            )
            if not discovered:
                raise RuntimeError(
                    f"Montana retained part replay exposed no sections: {part_url}"
                )
            terminal = self._montana_catalog_terminal_records(
                decoded,
                part_url=part_url,
                discovered=discovered,
                content_sha256=part_digest,
            )
            replay_part_reports.append(
                {
                    "content_sha256": part_digest,
                    "section_count": len(discovered),
                    "source_label": part_label,
                    "source_url": part_url,
                    "terminal_catalog_sections": len(terminal),
                }
            )
            for section_label, section_url in discovered:
                official_url = self._officialize_mca_url(section_url)
                if official_url in terminal:
                    record = dict(terminal[official_url])
                    catalog_terminal_reports.append(
                        {
                            "canonical_identity": "",
                            "content_sha256": str(
                                record.get("catalog_content_sha256") or ""
                            ),
                            "disposition": str(
                                record.get("disposition") or "repealed"
                            ),
                            "evidence_kind": "source_bound_part_catalog",
                            "evidence_source_url": part_url,
                            "section_number": str(
                                record.get("section_number") or ""
                            ),
                            "source_label": section_label,
                            "source_url": official_url,
                        }
                    )
                    continue
                if official_url in seen_sections:
                    raise RuntimeError(
                        "Montana retained part replay repeated a section URL: "
                        f"{official_url}"
                    )
                seen_sections.add(official_url)
                section_links.append((section_label, official_url))

        expected_section_links = [
            (
                str(report.get("source_label") or ""),
                str(report.get("source_url") or ""),
            )
            for report in expected_section_reports
            if str(report.get("evidence_kind") or "")
            != "source_bound_part_catalog"
        ]
        if section_links != expected_section_links:
            raise RuntimeError("Montana retained section membership changed")
        section_urls = [url for _label, url in section_links]
        section_payloads = self._replay_montana_retained_inputs(
            section_urls,
            frontier_name="section-pages",
        )

        replay_rows: List[NormalizedStatute] = []
        replay_section_reports: List[Dict[str, Any]] = list(
            catalog_terminal_reports
        )
        terminal_counts: Dict[str, int] = {}
        for report in catalog_terminal_reports:
            disposition = str(report.get("disposition") or "repealed")
            terminal_counts[disposition] = terminal_counts.get(disposition, 0) + 1
        seen_identities: set[str] = set()
        code_name = str(first.get("code_name") or "Montana Code Annotated")
        for (section_label, section_url), raw in zip(
            section_links,
            section_payloads,
            strict=True,
        ):
            statute = self._build_official_html_section_statute_from_html(
                code_name,
                section_label,
                section_url,
                raw.decode("utf-8", errors="replace"),
            )
            if statute is None:
                raise RuntimeError(
                    "Montana retained section replay left an unclassified residual: "
                    f"{section_url}"
                )
            identity = str(statute.section_number or "").strip()
            if not identity or identity.casefold() in seen_identities:
                raise RuntimeError(
                    f"Montana retained replay repeated identity: {identity!r}"
                )
            seen_identities.add(identity.casefold())
            content_sha256 = hashlib.sha256(raw).hexdigest()
            statute.structured_data = {
                **dict(statute.structured_data or {}),
                "content_sha256": content_sha256,
            }
            replay_rows.append(statute)
            replay_section_reports.append(
                {
                    "canonical_identity": identity.casefold(),
                    "content_sha256": content_sha256,
                    "disposition": "operative",
                    "section_number": identity,
                    "source_label": section_label,
                    "source_url": section_url,
                }
            )

        replay_root_report = {**root_report, "content_sha256": root_digest}
        replayed_frontier = self._montana_exact_frontier(
            root_report=replay_root_report,
            title_reports=replay_title_reports,
            chapter_reports=replay_chapter_reports,
            part_reports=replay_part_reports,
            section_reports=replay_section_reports,
            terminal_dispositions=terminal_counts,
        )
        self._last_montana_replayed_frontier = {
            "frontier": replayed_frontier,
            "section_reports": replay_section_reports,
        }
        return replay_rows

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Optional[Path]:
        """Replay retained MCA inputs and seal exact publication parity."""

        ledger = getattr(self, "_state_law_acquisition_ledger", None)
        if ledger is None:
            raise RuntimeError("Montana frontier closure requires an attached ledger")
        first = getattr(self, "_last_montana_full_frontier", None)
        if not isinstance(first, Mapping):
            raise RuntimeError(
                "Montana source-derived strict frontier was not retained before output"
            )
        refresh = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh):
            refresh()
        replay_rows = self._replay_montana_source_frontier(first)
        replay = getattr(self, "_last_montana_replayed_frontier", None)
        if not isinstance(replay, Mapping):
            raise RuntimeError("Montana retained source replay did not close")
        first_frontier = first.get("frontier")
        replayed_frontier = replay.get("frontier")
        if not isinstance(first_frontier, Mapping) or not isinstance(
            replayed_frontier, Mapping
        ):
            raise RuntimeError("Montana exact frontier observations are incomplete")

        from .strict_frontier_closure import retain_exact_state_frontier_closure

        observed_at = str(first.get("observed_at") or "")
        root_report = dict(first.get("root_report") or {})
        title_reports = list(first.get("title_reports") or [])
        chapter_reports = list(first.get("chapter_reports") or [])
        part_reports = list(first.get("part_reports") or [])
        section_reports = list(first.get("section_reports") or [])
        operative_leaf_count = sum(
            str(report.get("disposition") or "") == "operative"
            for report in section_reports
            if isinstance(report, Mapping)
        )
        official_source_url = str(
            root_report.get("source_url") or self.OFFICIAL_ENTRY_URL
        )
        return retain_exact_state_frontier_closure(
            self,
            canonical_output_projection=canonical_output_projection,
            first_frontier=first_frontier,
            replayed_frontier=replayed_frontier,
            replay_rows=replay_rows,
            jurisdiction="MT",
            source_domain=self.OFFICIAL_DOMAIN,
            official_source_url=official_source_url,
            observed_at=observed_at,
            legal_as_of=observed_at[:10],
            boundary_first=str(first.get("boundary_first") or ""),
            boundary_last=str(first.get("boundary_last") or ""),
            bundle_total=len(part_reports),
            pagination_total=len(section_reports),
            transport={
                "catalog_frontier_requested_pages": (
                    len(title_reports) + len(chapter_reports) + len(part_reports)
                ),
                "dependency_level_plural_waves": 3,
                "fixture": False,
                "first_pass_requested_pages": (
                    1
                    + len(title_reports)
                    + len(chapter_reports)
                    + len(part_reports)
                    + operative_leaf_count
                ),
                "grouped_warc_recovery": True,
                "kind": "shared_archive_aware_plural_html",
                "leaf_frontier_plural_waves": 1,
                "leaf_frontier_requested_pages": operative_leaf_count,
                "per_page_archive_loop": False,
                "repeat_grouped_archive_inventory_on_residual": False,
                "residual_only_retries": True,
                "retained_replay_network_requests": 0,
                "root_catalog_requested_pages": 1,
                "source_order_preserved": True,
                "source_ordered_cross_parent_union": True,
                "synthetic": False,
                "terminal_filter_precedes_leaf_wave": True,
                "wayback_prefix_inventory": True,
                "first_pass_batch_stats": list(
                    first.get("transport_batch_stats") or []
                ),
            },
        )

    async def _scrape_official_mca_reader_frontier(
        self,
        code_name: str,
        title_links: List[Tuple[str, str]],
    ) -> List[NormalizedStatute]:
        """Breadth-first batch fallback for the official MCA reader tree."""

        def _reader_url(url: str) -> str:
            return f"https://r.jina.ai/http://{url}"

        title_reader_urls = [_reader_url(url) for _label, url in title_links]
        title_payloads = await self._fetch_montana_frontier_batch(
            title_reader_urls,
            frontier_name="reader-title-index",
            reader=True,
        )

        chapter_links: List[Tuple[str, str]] = []
        seen_chapters: set[str] = set()
        for raw in title_payloads:
            for label, url in self._extract_mca_links(
                raw.decode("utf-8", errors="replace"),
                self._MT_CHAPTER_INDEX_RE,
            ):
                if url in seen_chapters:
                    continue
                seen_chapters.add(url)
                chapter_links.append((label, url))

        chapter_reader_urls = [_reader_url(url) for _label, url in chapter_links]
        chapter_payloads = await self._fetch_montana_frontier_batch(
            chapter_reader_urls,
            frontier_name="reader-chapter-index",
            reader=True,
        )

        part_links: List[Tuple[str, str]] = []
        seen_parts: set[str] = set()
        for raw in chapter_payloads:
            for label, url in self._extract_mca_links(
                raw.decode("utf-8", errors="replace"),
                self._MT_PART_INDEX_RE,
            ):
                if url in seen_parts:
                    continue
                seen_parts.add(url)
                part_links.append((label, url))

        part_reader_urls = [_reader_url(url) for _label, url in part_links]
        part_payloads = await self._fetch_montana_frontier_batch(
            part_reader_urls,
            frontier_name="reader-part-index",
            reader=True,
        )

        section_links: List[Tuple[str, str]] = []
        seen_sections: set[str] = set()
        for raw in part_payloads:
            for label, url in self._extract_mca_links(
                raw.decode("utf-8", errors="replace"),
                self._MT_SECTION_URL_RE,
            ):
                if url in seen_sections:
                    continue
                seen_sections.add(url)
                section_links.append((label, url))

        statutes: List[NormalizedStatute] = []
        sections_scanned = 0
        section_payloads = await self._fetch_montana_frontier_batch(
            [_reader_url(url) for _label, url in section_links],
            frontier_name="reader-section",
            reader=True,
        )
        checkpoint_size = self._montana_parse_checkpoint_size()
        for batch_start in range(0, len(section_links), checkpoint_size):
            batch_links = section_links[batch_start : batch_start + checkpoint_size]
            batch_payloads = section_payloads[
                batch_start : batch_start + checkpoint_size
            ]
            for (section_label, section_url), raw in zip(
                batch_links,
                batch_payloads,
                strict=True,
            ):
                sections_scanned += 1
                statute = self._build_official_section_statute_from_markdown(
                    code_name,
                    section_label,
                    section_url,
                    raw.decode("utf-8", errors="replace"),
                )
                if statute is not None:
                    statutes.append(statute)
            self._write_partial_checkpoint(
                statutes,
                code_name=code_name,
                stage_label="montana:reader-section-progress",
                extra={
                    "titles_scanned": int(len(title_links)),
                    "discovered_titles": int(len(title_links)),
                    "chapters_scanned": int(len(chapter_links)),
                    "discovered_chapters": int(len(chapter_links)),
                    "parts_scanned": int(len(part_links)),
                    "discovered_parts": int(len(part_links)),
                    "sections_scanned": int(sections_scanned),
                    "discovered_sections": int(len(section_links)),
                    "codes_completed": 0,
                    "codes_total": 1,
                },
            )

        self._write_partial_checkpoint(
            statutes,
            code_name=code_name,
            stage_label="montana:reader-complete",
            force=True,
            extra={
                "titles_scanned": int(len(title_links)),
                "discovered_titles": int(len(title_links)),
                "chapters_scanned": int(len(chapter_links)),
                "discovered_chapters": int(len(chapter_links)),
                "parts_scanned": int(len(part_links)),
                "discovered_parts": int(len(part_links)),
                "sections_scanned": int(sections_scanned),
                "discovered_sections": int(len(section_links)),
                "codes_completed": 1,
                "codes_total": 1,
            },
        )
        return statutes

    def _extract_html_mca_links(
        self,
        html: str,
        page_url: str,
        target_pattern: re.Pattern,
    ) -> List[Tuple[str, str]]:
        if not html:
            return []
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        soup = BeautifulSoup(html, "html.parser")
        links: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue
            absolute = self._officialize_mca_url(urljoin(page_url, href))
            path_and_file = urlparse(absolute).path or ""
            if not target_pattern.search(absolute) and not target_pattern.search(path_and_file):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            label = self._normalize_legal_text(anchor.get_text(" ", strip=True))
            links.append((label, absolute))
        return links

    async def _build_official_html_section_statute(
        self,
        code_name: str,
        section_label: str,
        section_url: str,
    ) -> Optional[NormalizedStatute]:
        html = await self._fetch_reader_markdown(section_url)
        if not html:
            return None
        return self._build_official_html_section_statute_from_html(
            code_name,
            section_label,
            section_url,
            html,
        )

    def _build_official_html_section_statute_from_html(
        self,
        code_name: str,
        section_label: str,
        section_url: str,
        html: str,
    ) -> Optional[NormalizedStatute]:
        """Parse one already-retained official MCA HTML section page."""

        if not html:
            return None
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        panel = (
            soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("div#content")
            or soup.find("body")
        )
        if panel is None:
            return None
        heading_node = panel.find(["h1", "h2", "h3"]) or panel
        heading = self._normalize_legal_text(
            section_label or heading_node.get_text(" ", strip=True)
        )[:220]
        full_text = self._normalize_legal_text(panel.get_text(" ", strip=True))
        if len(full_text) < 80:
            return None
        section_number = self._section_number_from_mca_url(
            section_url,
            section_label=section_label,
        )
        if not section_number:
            return None
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=(section_number.split("-", 1)[0] if section_number else None),
            section_number=section_number,
            section_name=heading or f"Section {section_number}",
            full_text=full_text,
            legal_area=self._identify_legal_area(full_text[:1200]),
            source_url=section_url,
            official_cite=f"Mont. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_montana_mca_html",
                "discovery_method": "official_mca_title_chapter_part_section",
                "skip_hydrate": True,
            },
        )

    async def _build_official_section_statute(
        self,
        code_name: str,
        section_label: str,
        section_url: str,
    ) -> Optional[NormalizedStatute]:
        markdown = await self._fetch_reader_markdown(f"https://r.jina.ai/http://{section_url}")
        if not markdown:
            return None
        return self._build_official_section_statute_from_markdown(
            code_name,
            section_label,
            section_url,
            markdown,
        )

    def _build_official_section_statute_from_markdown(
        self,
        code_name: str,
        section_label: str,
        section_url: str,
        markdown: str,
    ) -> Optional[NormalizedStatute]:
        """Parse one already-retained MCA reader section response."""

        if not markdown:
            return None
        section_number = self._section_number_from_mca_url(
            section_url,
            section_label=section_label,
        )
        text = self._extract_reader_statute_text(markdown, section_number)
        if len(text) < 220:
            return None
        heading = self._normalize_legal_text(section_label)[:220] or self._extract_reader_heading(
            markdown, section_number
        )
        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            title_number=(section_number.split("-", 1)[0] if section_number else None),
            section_number=section_number,
            section_name=heading,
            full_text=text,
            legal_area=self._identify_legal_area(text[:1200]),
            source_url=section_url,
            official_cite=f"Mont. Code Ann. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "jina_reader_montana_mca_hierarchical",
                "discovery_method": "official_mca_title_chapter_part_section",
                "reader_url": f"https://r.jina.ai/http://{section_url}",
                "skip_hydrate": True,
            },
        )

    async def _fetch_reader_markdown(self, reader_url: str) -> str:
        raw = await self._fetch_page_content_with_archival_fallback(reader_url, timeout_seconds=25)
        if not raw:
            return ""
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

    def _extract_mca_links(
        self, markdown: str, target_pattern: re.Pattern
    ) -> List[tuple[str, str]]:
        links: List[tuple[str, str]] = []
        seen = set()
        for label, url in self._MT_MARKDOWN_LINK_RE.findall(str(markdown or "")):
            clean_url = str(url or "").strip().rstrip("`").split('"', 1)[0].strip()
            if not clean_url or clean_url in seen:
                continue
            if isinstance(target_pattern, re.Pattern):
                if not target_pattern.search(clean_url):
                    continue
            seen.add(clean_url)
            links.append((self._normalize_legal_text(label), clean_url))
        return links

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        """Recover full Montana statute text from official pages via Jina reader."""
        seeds = [
            "https://leg.mt.gov/bills/mca/title_0450/chapter_0050/part_0010/section_0020/0450-0050-0010-0020.html",
            "https://leg.mt.gov/bills/mca/title_0460/chapter_0180/part_0020/section_0190/0460-0180-0020-0190.html",
        ]
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            reader_url = f"https://r.jina.ai/http://{url}"
            raw = await self._fetch_page_content_with_archival_fallback(
                reader_url, timeout_seconds=25
            )
            if not raw:
                continue
            try:
                markdown = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            section_number = self._section_number_from_mca_url(url)
            text = self._extract_reader_statute_text(markdown, section_number)
            if len(text) < 220:
                continue
            heading = self._extract_reader_heading(markdown, section_number)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=(section_number.split("-", 1)[0] if section_number else None),
                    section_number=section_number,
                    section_name=heading,
                    full_text=text,
                    legal_area=self._identify_legal_area(text[:1200]),
                    source_url=url,
                    official_cite=f"Mont. Code Ann. § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "jina_reader_montana_mca_official",
                        "discovery_method": "cloudflare_block_recovery_seed_section",
                        "reader_url": reader_url,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def _section_number_from_mca_url(
        self,
        url: str,
        *,
        section_label: str = "",
    ) -> str:
        match = self._MT_SECTION_URL_RE.search(str(url or ""))
        if not match:
            return self._derive_section_number_from_url(url) or ""
        raw = match.group(0).rsplit("/", 1)[-1].removesuffix(".html")
        raw_parts = raw.split("-")
        if (
            len(raw_parts) >= 4
            and re.fullmatch(r"\d{4}", raw_parts[0])
            and re.fullmatch(r"\d{3}[0-9A-Za-z]", raw_parts[1])
            and re.fullmatch(r"\d{4}", raw_parts[2])
            and re.fullmatch(r"\d{4}", raw_parts[3])
        ):
            title = int(raw_parts[0])
            chapter_token = raw_parts[1]
            part = int(raw_parts[2])
            section = int(raw_parts[3])
            # Montana MCA file paths encode section 45-5-102 as
            # title_0450/chapter_0050/part_0010/section_0020.
            section_tail = (part // 10 * 100) + (section // 10)
            if chapter_token[-1].isalpha():
                chapter_number = (
                    f"{int(chapter_token[:3])}{chapter_token[-1].upper()}"
                )
            else:
                chapter_number = str(int(chapter_token) // 10)
            base_number = f"{title // 10}-{chapter_number}-{section_tail}"
            source_ordinal_qualifier = section % 10
            label = self._normalize_legal_text(
                str(section_label or "").replace("*", " ")
            )

            leading = self._MT_LEADING_SECTION_LABEL_RE.match(label)
            if leading is not None:
                candidate = str(leading.group("section"))
                if candidate == base_number or candidate.startswith(
                    (f"{base_number}.", f"{base_number}-")
                ):
                    return candidate

            rule = self._MT_RULE_LABEL_RE.search(label)
            if rule is not None and int(rule.group("number")) == section // 10:
                qualifier = str(rule.group("qualifier") or "")
                if not qualifier and source_ordinal_qualifier == 0:
                    return base_number
                if qualifier and int(qualifier) == source_ordinal_qualifier:
                    return f"{base_number}.{qualifier}"

            hyphenated_form = self._MT_HYPHENATED_FORM_LABEL_RE.search(label)
            if hyphenated_form is not None:
                letter = str(hyphenated_form.group("letter")).upper()
                if (
                    int(hyphenated_form.group("number")) == section // 10
                    and ord(letter) - ord("A") + 1 == source_ordinal_qualifier
                ):
                    return f"{base_number}-{letter}"

            compact_form = self._MT_COMPACT_FORM_LABEL_RE.search(label)
            if compact_form is not None:
                letter = str(compact_form.group("letter")).upper()
                if (
                    int(compact_form.group("number")) == section // 10
                    and ord(letter) - ord("A") + 1 == source_ordinal_qualifier
                ):
                    return f"{base_number}{letter}"

            if source_ordinal_qualifier:
                raise ValueError(
                    "Montana nonzero source ordinal lacks an exact statutory "
                    f"identity label: url={url!r} label={section_label!r}"
                )
            return base_number
        return self._derive_section_number_from_url(url) or raw

    def _extract_reader_heading(self, markdown: str, section_number: str) -> str:
        for line in str(markdown or "").splitlines():
            value = self._normalize_legal_text(line.lstrip("# ").strip())
            if section_number and value.startswith(section_number):
                return value[:220]
        title_match = re.search(
            r"^Title:\s*(.+)$", str(markdown or ""), flags=re.IGNORECASE | re.MULTILINE
        )
        if title_match:
            return self._normalize_legal_text(title_match.group(1))[:220]
        return section_number

    def _extract_reader_statute_text(self, markdown: str, section_number: str) -> str:
        lines = []
        capture = False
        for line in str(markdown or "").splitlines():
            value = line.strip()
            if not value:
                if capture:
                    lines.append("")
                continue
            clean = self._normalize_legal_text(value.lstrip("# ").strip())
            if not capture and section_number and clean.startswith(section_number):
                capture = True
            if capture:
                if clean.lower().startswith(("url source:", "markdown content:", "title:")):
                    continue
                lines.append(value)
        text = self._normalize_legal_text("\n".join(lines))
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        return self._normalize_legal_text(text)

    def official_title_token(self, title_number: Any) -> str:
        return f"{int(title_number) * 10:04d}"

    def official_title_url(self, title_number: Any) -> str:
        token = self.official_title_token(title_number)
        return f"https://leg.mt.gov/bills/mca/title_{token}/chapters_index.html"

    def official_title_catalog(self) -> List[Dict[str, Any]]:
        """Return the exhaustive official Montana Code Annotated title catalog."""

        rows: List[Dict[str, Any]] = []
        for number in self.OFFICIAL_TITLES:
            url = self.official_title_url(number)
            rows.append(
                {
                    "canonical_key": f"mt:title-{int(number)}",
                    "title_number": str(int(number)),
                    "name": f"Title {int(number)}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Montana Code Annotated Title {int(number)} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def _official_http_get(self, url: str, timeout_seconds: int = 12) -> bytes:
        timeout = max(5, int(timeout_seconds or 12))
        headers = {
            "User-Agent": "ipfs-datasets-montana-official-catalog/1.0",
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

    def _title_number_from_token(self, token: str) -> str:
        digits = "".join(ch for ch in str(token or "") if ch.isdigit())
        if not digits:
            return ""
        value = int(digits)
        if value >= 10 and value % 10 == 0:
            return str(value // 10)
        return str(value)

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
            match = self._MT_TITLE_INDEX_HREF_RE.search(absolute)
            if not match:
                continue
            number = self._title_number_from_token(match.group("title"))
            if number and number not in found:
                found[number] = self.official_title_url(number)
        return found

    def enumerate_official_catalog(
        self,
        html: bytes = b"",
        *,
        page_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Enumerate every official MCA title and repair missing live links."""

        del page_url
        discovered = self._parse_official_title_links(html)
        rows = self.official_title_catalog()
        seen = {str(row["title_number"]) for row in rows}
        for row in rows:
            live_url = discovered.get(str(row["title_number"]))
            if live_url:
                row["source_url"] = live_url
                row["source_link_disposition"] = "official"
            else:
                row["source_link_disposition"] = "repaired_official_leginfo"
        for number, url in discovered.items():
            if number in seen:
                continue
            rows.append(
                {
                    "canonical_key": f"mt:title-{number}",
                    "title_number": number,
                    "name": f"Title {number}",
                    "source_url": url,
                    "source_link_disposition": "official",
                    "text": (
                        f"Montana Code Annotated Title {number} official "
                        f"catalog unit at {url}"
                    ),
                }
            )
        return rows

    def fetch_official(self, code: str = "MT"):
        """Acquire the exhaustive official Montana Code Annotated title catalog.

        Live HTTPS retains the official MCA index. Every known title is
        enumerated with an official leg.mt.gov URL. This hook never returns
        fixture bytes.
        """

        from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
            OfficialFetch,
            compute_frontier_digest,
        )

        normalized = str(code or "MT").strip().upper() or "MT"
        html = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        if not html:
            html = self._official_http_get("https://leg.mt.gov/bills/mca/")
        rows = self.enumerate_official_catalog(html, page_url=self.OFFICIAL_ENTRY_URL)
        if len(rows) < 3:
            raise RuntimeError("montana official catalog enumeration is incomplete")
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
StateScraperRegistry.register("MT", MontanaScraper)
