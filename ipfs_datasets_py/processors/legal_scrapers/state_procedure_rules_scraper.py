"""State civil/criminal procedure-rules scraper orchestration.

This module reuses the state-laws scraping pipeline, then keeps only
records that match civil/criminal procedure rule patterns.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

try:
    from .canonical_legal_corpora import get_canonical_legal_corpus
except ImportError:  # pragma: no cover - file-based test imports
    import importlib.util
    import sys

    _CANONICAL_MODULE_PATH = Path(__file__).with_name("canonical_legal_corpora.py")
    _CANONICAL_SPEC = importlib.util.spec_from_file_location(
        "canonical_legal_corpora",
        _CANONICAL_MODULE_PATH,
    )
    if _CANONICAL_SPEC is None or _CANONICAL_SPEC.loader is None:
        raise
    _CANONICAL_MODULE = importlib.util.module_from_spec(_CANONICAL_SPEC)
    sys.modules.setdefault("canonical_legal_corpora", _CANONICAL_MODULE)
    _CANONICAL_SPEC.loader.exec_module(_CANONICAL_MODULE)
    get_canonical_legal_corpus = _CANONICAL_MODULE.get_canonical_legal_corpus
from .state_laws_scraper import US_STATES, list_state_jurisdictions, scrape_state_laws
from .state_scrapers.base_scraper import BaseStateScraper, NormalizedStatute

logger = logging.getLogger(__name__)

_RI_COURT_RULES_HUB_URL = "https://www.courts.ri.gov/Legal-Resources/Pages/court-rules.aspx"
_RI_COURT_RULES_PAGE_RE = re.compile(
    r"/Legal-Resources/Pages/(?:Supreme|Superior|Family|District|Workers'-Compensation|Rhode-Island-Traffic-Tribunal)-Court-Rules\.aspx$",
    re.IGNORECASE,
)
_RI_COURT_RULES_DOC_RE = re.compile(r"\.pdf(?:$|[?#])", re.IGNORECASE)
_RI_COURT_RULES_ALLOWED_DOC_PATH_RE = re.compile(r"^/(?:Courts/|Legal-Resources/Documents/)", re.IGNORECASE)
_RI_COURT_RULE_SIGNAL_RE = re.compile(
    r"\b(rule|rules|procedure|practice|evidence|tribunal|arbitration|domestic|juvenile|disciplinary)\b",
    re.IGNORECASE,
)
_RI_COURT_RULE_EXCLUDED_TEXT_RE = re.compile(
    r"\b(instructions?|forms?|notice\s+of\s+suit|complaint|answer|attorney)\b",
    re.IGNORECASE,
)
_MI_COURT_RULES_CHAPTERS: List[Dict[str, str]] = [
    {
        "name": "Michigan Court Rules Chapter 2. Civil Procedure",
        "url": "https://www.courts.michigan.gov/siteassets/rules-instructions-administrative-orders/"
        "michigan-court-rules/court-rules-book-ch-2-responsive-html5.zip/"
        "Court_Rules_Book_Ch_2/Court_Rules_Chapter_2/Court_Rules_Chapter_2.htm",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
    },
    {
        "name": "Michigan Court Rules Chapter 6. Criminal Procedure",
        "url": "https://www.courts.michigan.gov/siteassets/rules-instructions-administrative-orders/"
        "michigan-court-rules/court-rules-book-ch-6-responsive-html5.zip/"
        "Court_Rules_Book_Ch_6/Court_Rules_Chapter_6/Court_Rules_Chapter_6.htm",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
    },
]
_MI_RULE_HEADING_RE = re.compile(r"^Rule\s+(\d+\.\d{3}[A-Za-z]?)\s+(.+)$")
_MI_UPDATED_RE = re.compile(
    r"Chapter\s+Updated\s+with\s+MSC\s+Order\(s\)\s+Effective\s+on\s+(.+)$",
    re.IGNORECASE,
)
_CA_RULE_TITLES: List[Dict[str, str]] = [
    {
        "title_name": "Title Three. Civil Rules",
        "url": "https://courts.ca.gov/cms/rules/index/three",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
    },
    {
        "title_name": "Title Four. Criminal Rules",
        "url": "https://courts.ca.gov/cms/rules/index/four",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
    },
]
_CA_RULE_LINK_RE = re.compile(r"^/cms/rules/index/(three|four)/rule[0-9_]+(?:#.*)?$", re.IGNORECASE)
_CA_RULE_HEADING_RE = re.compile(r"^Rule\s+(\d+\.\d+)\.\s+(.+)$")
_CA_CURRENT_AS_OF_RE = re.compile(r"^Current\s+as\s+of\s+(.+)$", re.IGNORECASE)
_OH_RULE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "title_name": "Ohio Rules of Civil Procedure",
        "url": "https://www.supremecourt.ohio.gov/docs/LegalResources/Rules/civil/CivilProcedure.pdf",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "effective_date": "July 1, 2025",
    },
    {
        "title_name": "Ohio Rules of Criminal Procedure",
        "url": "https://www.supremecourt.ohio.gov/docs/LegalResources/Rules/criminal/CriminalProcedure.pdf",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "effective_date": "July 1, 2025",
    },
]
_OH_RULE_BLOCK_RE = re.compile(
    r"RULE\s+(\d+(?:\.\d+)?)\.\s+(.+?)(?=(?:\sRULE\s+\d+(?:\.\d+)?\.)|\Z)",
    re.DOTALL,
)
_AZ_RULE_DOCUMENTS: List[Dict[str, str]] = [
    {
        "title_name": "Arizona Rules of Civil Procedure",
        "url": "https://www.azcourts.gov/DesktopModules/ActiveForums/viewer.aspx?attachmentid=3200&moduleid=23621&portalid=0",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "effective_date": "2017 amendments restyled text reflected in official PDF",
        "start_marker": "Rule 1. Scope and Purpose",
    },
    {
        "title_name": "Arizona Rules of Criminal Procedure",
        "url": "https://rulesforum.azcourts.gov/DesktopModules/ActiveForums/viewer.aspx?attachmentid=4820&moduleid=9811&portalid=4",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "effective_date": "Attachment A official compiled criminal rules PDF",
        "start_marker": "Rule 1.1. Scope",
    },
]
_AZ_RULE_BLOCK_RE = re.compile(
    r"Rule\s+(\d+(?:\.\d+)?)\.\s+(.+?)(?=(?:\sRule\s+\d+(?:\.\d+)?\.)|\Z)",
    re.DOTALL,
)
_WA_RULE_LIST_PAGES: List[Dict[str, str]] = [
    {
        "title_name": "Washington Superior Court Civil Rules",
        "url": "https://www.courts.wa.gov/court_rules/?fa=court_rules.list&group=sup&set=CR",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
        "official_cite_prefix": "CR",
    },
    {
        "title_name": "Washington Superior Court Criminal Rules",
        "url": "https://www.courts.wa.gov/court_rules/?fa=court_rules.list&group=sup&set=CrR",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
        "official_cite_prefix": "CrR",
    },
]
_WA_RULE_SECTION_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?(?:[A-Za-z]+)?(?:\s+[A-Za-z]+)?$")
_WA_EFFECTIVE_DATE_RE = re.compile(r"\b(?:Adopted|Amended)\s+effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_NJ_RULE_PARTS: List[Dict[str, str]] = [
    {
        "section": "Part 3",
        "title_name": "New Jersey Court Rules Part III. Criminal Practice",
        "procedure_family": "criminal_procedure",
        "legal_area": "criminal_procedure",
    },
    {
        "section": "Part 4",
        "title_name": "New Jersey Court Rules Part IV. Civil Practice",
        "procedure_family": "civil_procedure",
        "legal_area": "civil_procedure",
    },
]
_NJ_EFFECTIVE_DATE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_NJ_RULE_TITLE_RE = re.compile(r"^([0-9]+:[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)*)-(.+)$")

_CIVIL_PATTERNS = [
    re.compile(r"rules?\s+of\s+civil\s+procedure", re.IGNORECASE),
    re.compile(r"civil\s+procedure", re.IGNORECASE),
    re.compile(r"code\s+of\s+civil\s+procedure", re.IGNORECASE),
    re.compile(r"civil\s+practice", re.IGNORECASE),
    re.compile(r"civil\s+actions?", re.IGNORECASE),
    re.compile(r"rules?\s+of\s+court", re.IGNORECASE),
]

_CRIMINAL_PATTERNS = [
    re.compile(r"rules?\s+of\s+criminal\s+procedure", re.IGNORECASE),
    re.compile(r"criminal\s+procedure", re.IGNORECASE),
    re.compile(r"code\s+of\s+criminal\s+procedure", re.IGNORECASE),
    re.compile(r"criminal\s+practice", re.IGNORECASE),
    re.compile(r"criminal\s+actions?", re.IGNORECASE),
]


def _signal_text(statute: Dict[str, Any]) -> str:
    fields: List[str] = []
    is_part_of = statute.get("isPartOf")
    if isinstance(is_part_of, dict):
        name = is_part_of.get("name")
        if isinstance(name, str):
            fields.append(name)

    for key in [
        "code_name",
        "name",
        "titleName",
        "chapterName",
        "sectionName",
        "legislationType",
        "official_cite",
        "section_name",
        "full_text",
        "text",
        "source_url",
    ]:
        value = statute.get(key)
        if isinstance(value, str):
            fields.append(value)

    return "\n".join(v for v in fields if v)


def _classify_procedure_family(statute: Dict[str, Any]) -> Optional[str]:
    signal = _signal_text(statute)
    civil = any(pattern.search(signal) for pattern in _CIVIL_PATTERNS)
    criminal = any(pattern.search(signal) for pattern in _CRIMINAL_PATTERNS)

    if civil and criminal:
        return "civil_and_criminal_procedure"
    if civil:
        return "civil_procedure"
    if criminal:
        return "criminal_procedure"
    return None


class _ProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courts.ri.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _MichiganProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courts.michigan.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _CaliforniaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://courts.ca.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _OhioProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.supremecourt.ohio.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _ArizonaProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.azcourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _WashingtonProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.courts.wa.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


class _NewJerseyProcedureRulesSupplementFetcher(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://www.njcourts.gov"

    def get_code_list(self) -> List[Dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        return []


def _extract_rhode_island_rule_links(html_text: str, page_url: str) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue

        text = " ".join(anchor.get_text(" ", strip=True).split())
        absolute_url = urljoin(page_url, href)
        parsed = urlparse(absolute_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() != "www.courts.ri.gov":
            continue

        is_rule_page = bool(_RI_COURT_RULES_PAGE_RE.search(parsed.path))
        is_pdf = bool(_RI_COURT_RULES_DOC_RE.search(absolute_url))
        if not is_rule_page and not is_pdf:
            continue
        if is_pdf and not _RI_COURT_RULES_ALLOWED_DOC_PATH_RE.search(parsed.path):
            continue

        signal_text = " ".join(
            value for value in [text, absolute_url.rsplit("/", 1)[-1].replace("-", " ")] if value
        )
        if not _RI_COURT_RULE_SIGNAL_RE.search(signal_text):
            continue
        if _RI_COURT_RULE_EXCLUDED_TEXT_RE.search(signal_text):
            continue

        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "label": text or Path(parsed.path).stem.replace("-", " "),
                "url": absolute_url,
                "kind": "pdf" if is_pdf else "page",
            }
        )

    return discovered


def _extract_washington_rule_links(
    html_text: str,
    *,
    page_url: str,
    procedure_family: str,
    legal_area: str,
    official_cite_prefix: str,
) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    discovered: List[Dict[str, str]] = []
    seen = set()

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 2:
            continue

        section_number = " ".join(cells[0].get_text(" ", strip=True).split())
        if not section_number or not _WA_RULE_SECTION_NUMBER_RE.match(section_number):
            continue

        anchor = cells[1].find("a", href=True)
        if anchor is None:
            continue

        href = str(anchor.get("href") or "").strip()
        section_name = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not section_name:
            continue

        absolute_url = urljoin(page_url, href)
        if not absolute_url.lower().endswith(".pdf"):
            continue

        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "section_number": section_number,
                "section_name": section_name,
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
                "official_cite_prefix": official_cite_prefix,
            }
        )

    return discovered


def _extract_new_jersey_rule_from_description(
    description_html: str,
    *,
    section_number: str,
    section_name: str,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(description_html or "", "html.parser")
    text_lines = [" ".join(line.split()) for line in soup.get_text("\n", strip=True).splitlines()]
    text_lines = [line for line in text_lines if line]
    if not text_lines:
        return None

    full_text = "\n".join(text_lines).strip()
    if len(full_text) < 40:
        return None

    effective_dates = [
        " ".join(match.group(1).split())
        for match in _NJ_EFFECTIVE_DATE_RE.finditer(full_text)
        if match.group(1)
    ]
    effective_date = effective_dates[-1] if effective_dates else None

    return NormalizedStatute(
        state_code="NJ",
        state_name=US_STATES["NJ"],
        statute_id=f"N.J. Ct. R. {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=source_url,
        official_cite=f"N.J. Ct. R. {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "njcourts_rules_api",
            "procedure_family": procedure_family,
        },
    )


def _derive_rhode_island_rule_locator(label: str, source_url: str, ordinal: int) -> str:
    normalized_label = re.sub(r"[^A-Za-z0-9]+", "-", str(label or "").strip()).strip("-")
    if normalized_label:
        return normalized_label[:120]
    stem = Path(urlparse(source_url).path).stem
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-")
    if stem:
        return stem[:120]
    return f"RI-RULE-{ordinal}"


def _extract_michigan_rules_from_html(
    html_text: str,
    *,
    chapter_url: str,
    code_name: str,
    procedure_family: str,
    legal_area: str,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    lines: List[str] = []
    for raw_line in soup.get_text("\n", strip=True).splitlines():
        line = " ".join(str(raw_line or "").split())
        if line:
            lines.append(line)

    if not lines:
        return []

    chapter_title = ""
    updated_effective_date = ""
    for line in lines[:40]:
        if not chapter_title and line.lower().startswith("chapter "):
            chapter_title = line
        if not updated_effective_date:
            match = _MI_UPDATED_RE.search(line)
            if match:
                updated_effective_date = " ".join(match.group(1).split())

    statutes: List[NormalizedStatute] = []
    current_number = ""
    current_name = ""
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current_number, current_name, buffer
        if not current_number or not current_name:
            current_number = ""
            current_name = ""
            buffer = []
            return

        full_text = "\n".join(buffer).strip()
        if len(full_text) < 40:
            current_number = ""
            current_name = ""
            buffer = []
            return

        statute = NormalizedStatute(
            state_code="MI",
            state_name=US_STATES["MI"],
            statute_id=f"MCR {current_number}",
            code_name=code_name,
            title_name=chapter_title or code_name,
            chapter_name=chapter_title or code_name,
            section_number=current_number,
            section_name=current_name,
            short_title=current_name,
            full_text=full_text,
            summary=current_name,
            source_url=f"{chapter_url}#rule-{current_number.lower()}",
            official_cite=f"MCR {current_number}",
            legal_area=legal_area,
            structured_data={
                "effective_date": updated_effective_date or None,
                "source_kind": "html_chapter",
            },
        )
        statutes.append(statute)
        current_number = ""
        current_name = ""
        buffer = []

    for line in lines:
        match = _MI_RULE_HEADING_RE.match(line)
        if match:
            flush()
            current_number = match.group(1).strip()
            current_name = match.group(2).strip()
            buffer = [line]
            continue
        if current_number:
            buffer.append(line)

    flush()

    deduped: List[NormalizedStatute] = []
    seen = set()
    for statute in statutes:
        key = (
            str(statute.section_number or "").lower(),
            str(statute.section_name or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(statute)

    return deduped


def _extract_california_rule_links(
    html_text: str,
    *,
    title_url: str,
    procedure_family: str,
    legal_area: str,
) -> tuple[List[Dict[str, str]], Optional[str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], None

    soup = BeautifulSoup(html_text, "html.parser")
    main = soup.select_one("main")
    if main is None:
        return [], None

    current_as_of = None
    for raw_line in main.get_text("\n", strip=True).splitlines():
        line = " ".join(str(raw_line or "").split())
        if not line:
            continue
        match = _CA_CURRENT_AS_OF_RE.match(line)
        if match:
            current_as_of = match.group(1).strip()
            break

    discovered: List[Dict[str, str]] = []
    seen = set()
    for anchor in main.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        text = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not text.startswith("Rule "):
            continue
        if not _CA_RULE_LINK_RE.match(href):
            continue

        absolute_url = urljoin(title_url, href)
        key = absolute_url.lower()
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            {
                "label": text,
                "url": absolute_url,
                "procedure_family": procedure_family,
                "legal_area": legal_area,
            }
        )

    return discovered, current_as_of


def _extract_california_rule_from_html(
    html_text: str,
    *,
    rule_url: str,
    code_name: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    current_as_of: Optional[str],
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html_text, "html.parser")
    main = soup.select_one("main")
    if main is None:
        return None

    lines = [" ".join(str(line or "").split()) for line in main.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    start_index = None
    section_number = ""
    section_name = ""
    for index, line in enumerate(lines):
        match = _CA_RULE_HEADING_RE.match(line)
        if match:
            start_index = index
            section_number = match.group(1).strip()
            section_name = match.group(2).strip()
            break

    if start_index is None or not section_number or not section_name:
        return None

    full_text = "\n".join(lines[start_index:]).strip()
    if len(full_text) < 80:
        return None

    return NormalizedStatute(
        state_code="CA",
        state_name=US_STATES["CA"],
        statute_id=f"Cal. Rules of Court, rule {section_number}",
        code_name=code_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=rule_url,
        official_cite=f"Cal. Rules of Court, rule {section_number}",
        legal_area=legal_area,
        structured_data={
            "current_as_of": current_as_of or None,
            "source_kind": "html_rule_page",
            "procedure_family": procedure_family,
        },
    )


async def _fetch_html_with_direct_fallback(
    fetcher: BaseStateScraper,
    url: str,
    *,
    validator,
    timeout_seconds: int = 120,
) -> str:
    payload = await fetcher._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout_seconds)
    html = payload.decode("utf-8", errors="replace") if payload else ""
    if validator(html):
        return html

    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    except Exception as exc:
        fetcher._record_fetch_event(provider="direct", success=False, error=str(exc))
        return html

    if response.status_code != 200 or not response.text:
        fetcher._record_fetch_event(provider="direct", success=False, error=f"http {response.status_code}")
        return html

    direct_html = response.text
    if not validator(direct_html):
        fetcher._record_fetch_event(provider="direct", success=False, error="validator_failed")
        return html

    fetcher._record_fetch_event(provider="direct", success=True)
    await fetcher._store_page_bytes_in_ipfs_cache(
        url=url,
        payload=response.content,
        provider="direct",
    )
    return direct_html


async def _fetch_pdf_bytes_with_direct_fallback(
    fetcher: BaseStateScraper,
    url: str,
    *,
    timeout_seconds: int = 180,
) -> bytes:
    payload = await fetcher._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout_seconds)
    if isinstance(payload, (bytes, bytearray)) and bytes(payload).startswith(b"%PDF-"):
        return bytes(payload)

    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    except Exception as exc:
        fetcher._record_fetch_event(provider="direct", success=False, error=str(exc))
        return b""

    if response.status_code != 200 or not response.content:
        fetcher._record_fetch_event(provider="direct", success=False, error=f"http {response.status_code}")
        return b""

    if not bytes(response.content).startswith(b"%PDF-"):
        fetcher._record_fetch_event(provider="direct", success=False, error="not_pdf")
        return b""

    fetcher._record_fetch_event(provider="direct", success=True)
    await fetcher._store_page_bytes_in_ipfs_cache(
        url=url,
        payload=response.content,
        provider="direct",
    )
    return bytes(response.content)


async def _fetch_json_with_direct_fallback(
    fetcher: BaseStateScraper,
    url: str,
    *,
    timeout_seconds: int = 120,
) -> Any:
    prefer_direct = "/njcourts_rules_of_court/" in url
    if not prefer_direct:
        payload = await fetcher._fetch_page_content_with_archival_fallback(url, timeout_seconds=timeout_seconds)
        if payload:
            try:
                return json.loads(payload.decode("utf-8", errors="replace"))
            except Exception:
                pass

    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
    except Exception as exc:
        fetcher._record_fetch_event(provider="direct", success=False, error=str(exc))
        return None

    if response.status_code != 200 or not response.text:
        fetcher._record_fetch_event(provider="direct", success=False, error=f"http {response.status_code}")
        return None

    try:
        parsed = response.json()
    except Exception:
        fetcher._record_fetch_event(provider="direct", success=False, error="invalid_json")
        return None

    fetcher._record_fetch_event(provider="direct", success=True)
    await fetcher._store_page_bytes_in_ipfs_cache(
        url=url,
        payload=response.content,
        provider="direct",
    )
    return parsed


def _extract_ohio_rules_from_text(
    text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    effective_date: Optional[str],
) -> List[NormalizedStatute]:
    normalized_text = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    body_start = normalized_text.find("TITLE I.")
    if body_start != -1:
        normalized_text = normalized_text[body_start:]
    statutes: List[NormalizedStatute] = []
    seen = set()
    for match in _OH_RULE_BLOCK_RE.finditer(normalized_text):
        section_number = str(match.group(1) or "").strip()
        body = str(match.group(2) or "").strip()
        if not section_number or not body:
            continue
        full_text = f"RULE {section_number}. {body}".strip()
        if len(full_text) < 80:
            continue

        section_name = body
        for marker in [". (", ". Effective Date", ". Staff Note", ". "]:
            marker_index = section_name.find(marker)
            if marker_index != -1:
                section_name = section_name[:marker_index]
                break
        section_name = section_name.strip().rstrip(".")
        if not section_name:
            continue

        key = (section_number.lower(), section_name.lower())
        if key in seen:
            continue
        seen.add(key)

        statutes.append(
            NormalizedStatute(
                state_code="OH",
                state_name=US_STATES["OH"],
                statute_id=f"{title_name} Rule {section_number}",
                code_name=title_name,
                title_name=title_name,
                chapter_name=title_name,
                section_number=section_number,
                section_name=section_name,
                short_title=section_name,
                full_text=full_text,
                summary=section_name,
                source_url=f"{source_url}#rule-{section_number.lower()}",
                official_cite=f"{title_name} Rule {section_number}",
                legal_area=legal_area,
                structured_data={
                    "effective_date": effective_date or None,
                    "source_kind": "pdf_rule_book",
                    "procedure_family": procedure_family,
                },
            )
        )

    return statutes


def _extract_arizona_rules_from_text(
    text: str,
    *,
    source_url: str,
    title_name: str,
    procedure_family: str,
    legal_area: str,
    effective_date: Optional[str],
    start_marker: str,
) -> List[NormalizedStatute]:
    normalized_text = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    start_index = normalized_text.rfind(start_marker)
    if start_index != -1:
        normalized_text = normalized_text[start_index:]

    statutes: List[NormalizedStatute] = []
    seen = set()
    for match in _AZ_RULE_BLOCK_RE.finditer(normalized_text):
        section_number = str(match.group(1) or "").strip()
        body = str(match.group(2) or "").strip()
        if not section_number or not body:
            continue
        full_text = f"Rule {section_number}. {body}".strip()
        if len(full_text) < 80:
            continue

        section_name = body
        for marker in [". (", ". [", ". Comment", ". Comment to", ". "]:
            marker_index = section_name.find(marker)
            if marker_index != -1:
                section_name = section_name[:marker_index]
                break
        section_name = section_name.strip().rstrip(".")
        if not section_name:
            continue

        key = (section_number.lower(), section_name.lower())
        if key in seen:
            continue
        seen.add(key)

        statutes.append(
            NormalizedStatute(
                state_code="AZ",
                state_name=US_STATES["AZ"],
                statute_id=f"{title_name} Rule {section_number}",
                code_name=title_name,
                title_name=title_name,
                chapter_name=title_name,
                section_number=section_number,
                section_name=section_name,
                short_title=section_name,
                full_text=full_text,
                summary=section_name,
                source_url=f"{source_url}#rule-{section_number.lower()}",
                official_cite=f"{title_name} Rule {section_number}",
                legal_area=legal_area,
                structured_data={
                    "effective_date": effective_date or None,
                    "source_kind": "pdf_rule_book",
                    "procedure_family": procedure_family,
                },
            )
        )

    return statutes


def _extract_washington_rule_from_text(
    text: str,
    *,
    source_url: str,
    title_name: str,
    section_number: str,
    section_name: str,
    official_cite_prefix: str,
    procedure_family: str,
    legal_area: str,
) -> Optional[NormalizedStatute]:
    normalized_text = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    if len(normalized_text) < 60:
        return None

    upper_cite = f"{official_cite_prefix} {section_number}".upper()
    body_start = normalized_text.upper().find(upper_cite)
    full_text = normalized_text[body_start:].strip() if body_start != -1 else normalized_text
    if len(full_text) < 60:
        return None

    effective_dates = [
        " ".join(match.group(1).split())
        for match in _WA_EFFECTIVE_DATE_RE.finditer(full_text)
        if match.group(1)
    ]
    effective_date = effective_dates[-1] if effective_dates else None

    return NormalizedStatute(
        state_code="WA",
        state_name=US_STATES["WA"],
        statute_id=f"{official_cite_prefix} {section_number}",
        code_name=title_name,
        title_name=title_name,
        chapter_name=title_name,
        section_number=section_number,
        section_name=section_name,
        short_title=section_name,
        full_text=full_text,
        summary=section_name,
        source_url=f"{source_url}#rule-{section_number.lower().replace(' ', '-')}",
        official_cite=f"{official_cite_prefix} {section_number}",
        legal_area=legal_area,
        structured_data={
            "effective_date": effective_date,
            "source_kind": "pdf_rule_page",
            "procedure_family": procedure_family,
        },
    )


def _merge_fetch_analytics(
    base_fetch_analytics_by_state: Dict[str, Dict[str, Any]],
    supplemental_fetch_analytics_by_state: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}

    for state_code in sorted(set(base_fetch_analytics_by_state) | set(supplemental_fetch_analytics_by_state)):
        base_metrics = base_fetch_analytics_by_state.get(state_code) or {}
        supplemental_metrics = supplemental_fetch_analytics_by_state.get(state_code) or {}

        attempted = int(base_metrics.get("attempted", 0) or 0) + int(supplemental_metrics.get("attempted", 0) or 0)
        success = int(base_metrics.get("success", 0) or 0) + int(supplemental_metrics.get("success", 0) or 0)
        fallback_count = int(base_metrics.get("fallback_count", 0) or 0) + int(
            supplemental_metrics.get("fallback_count", 0) or 0
        )
        cache_hits = int(base_metrics.get("cache_hits", 0) or 0) + int(supplemental_metrics.get("cache_hits", 0) or 0)
        cache_writes = int(base_metrics.get("cache_writes", 0) or 0) + int(
            supplemental_metrics.get("cache_writes", 0) or 0
        )

        providers: Dict[str, int] = {}
        for provider_metrics in [base_metrics.get("providers"), supplemental_metrics.get("providers")]:
            if not isinstance(provider_metrics, dict):
                continue
            for provider, count in provider_metrics.items():
                providers[str(provider)] = int(providers.get(str(provider), 0) or 0) + int(count or 0)

        merged[state_code] = {
            "attempted": attempted,
            "success": success,
            "success_ratio": round((success / attempted), 3) if attempted > 0 else 0.0,
            "fallback_count": fallback_count,
            "cache_hits": cache_hits,
            "cache_writes": cache_writes,
            "providers": providers,
            "last_error": supplemental_metrics.get("last_error") or base_metrics.get("last_error"),
        }

    return merged


async def _scrape_rhode_island_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _ProcedureRulesSupplementFetcher("RI", US_STATES["RI"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None

    discovered_pdfs: List[Dict[str, str]] = []
    queued_pages = [_RI_COURT_RULES_HUB_URL]
    seen_pages = set()
    seen_pdf_urls = set()

    while queued_pages:
        page_url = queued_pages.pop(0)
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)

        page_bytes = await fetcher._fetch_page_content_with_archival_fallback(page_url)
        page_text = page_bytes.decode("utf-8", errors="replace") if page_bytes else ""
        page_links = _extract_rhode_island_rule_links(page_text, page_url) if page_text else []
        if not page_links:
            try:
                response = requests.get(
                    page_url,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            except Exception as exc:
                fetcher._record_fetch_event(provider="direct", success=False, error=str(exc))
                continue
            if response.status_code != 200 or not response.content:
                fetcher._record_fetch_event(
                    provider="direct",
                    success=False,
                    error=f"http {response.status_code}",
                )
                continue
            page_bytes = response.content
            await fetcher._store_page_bytes_in_ipfs_cache(
                url=page_url,
                payload=page_bytes,
                provider="direct",
            )
            fetcher._record_fetch_event(provider="direct", success=True)
            page_text = page_bytes.decode("utf-8", errors="replace")
            page_links = _extract_rhode_island_rule_links(page_text, page_url)

        if not page_links:
            continue

        for link in page_links:
            if link["kind"] == "page":
                if link["url"] not in seen_pages:
                    queued_pages.append(link["url"])
                continue

            pdf_key = link["url"].lower()
            if pdf_key in seen_pdf_urls or pdf_key in existing_urls:
                continue
            seen_pdf_urls.add(pdf_key)
            discovered_pdfs.append(link)

    supplemental_rules: List[Dict[str, Any]] = []
    for ordinal, rule_doc in enumerate(discovered_pdfs, start=1):
        if remaining is not None and len(supplemental_rules) >= remaining:
            break

        raw_bytes = await fetcher._fetch_page_content_with_archival_fallback(rule_doc["url"])
        if not raw_bytes:
            continue

        document = await fetcher._extract_text_from_document_bytes(
            source_url=rule_doc["url"],
            raw_bytes=raw_bytes,
        )
        if not isinstance(document, dict):
            continue

        cleaned_text = fetcher._normalize_legal_text(str(document.get("text") or ""))
        if len(cleaned_text) < 160:
            continue

        family = _classify_procedure_family(
            {
                "name": rule_doc["label"],
                "sectionName": rule_doc["label"],
                "text": cleaned_text,
                "source_url": rule_doc["url"],
            }
        )
        if not family:
            continue

        locator = _derive_rhode_island_rule_locator(rule_doc["label"], rule_doc["url"], ordinal)
        statute = NormalizedStatute(
            state_code="RI",
            state_name=US_STATES["RI"],
            statute_id=f"Rhode Island Court Rule {locator}",
            code_name="Rhode Island Court Rules",
            title_name="Rhode Island Judiciary Court Rules",
            section_number=locator,
            section_name=rule_doc["label"],
            full_text=cleaned_text,
            source_url=rule_doc["url"],
            official_cite=rule_doc["label"],
            legal_area="criminal" if family == "criminal_procedure" else "civil",
            structured_data={
                "method_used": str(document.get("method") or ""),
                "source_content_type": str(document.get("content_type") or ""),
            },
        )
        statute = fetcher._enrich_statute_structure(statute)
        row = statute.to_dict()
        row["procedure_family"] = family
        supplemental_rules.append(row)
        existing_urls.add(rule_doc["url"].lower())

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_oregon_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from .state_scrapers.oregon import (
        LOCAL_RULES_INDEX_URL,
        ORCP_PRIMARY_URL,
        OregonScraper,
    )

    scraper = OregonScraper("OR", US_STATES["OR"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None

    async def _collect(
        code_name: str,
        code_url: str,
        method_name: str,
    ) -> List[NormalizedStatute]:
        nonlocal remaining
        if remaining is not None and remaining <= 0:
            return []

        scrape_method = getattr(scraper, method_name)
        rows = await scrape_method(code_name, code_url) if code_url else await scrape_method(code_name)
        deduped: List[NormalizedStatute] = []
        for row in rows:
            source_url = str(getattr(row, "source_url", "") or "").strip().lower()
            if source_url and source_url in existing_urls:
                continue
            if source_url:
                existing_urls.add(source_url)
            deduped.append(row)
            if remaining is not None:
                remaining -= 1
                if remaining <= 0:
                    break
        return deduped

    supplemental_statutes: List[NormalizedStatute] = []
    supplemental_statutes.extend(
        await _collect(
            "Oregon Rules of Civil Procedure",
            ORCP_PRIMARY_URL,
            "_scrape_civil_procedure_rules",
        )
    )
    supplemental_statutes.extend(
        await _collect(
            "Oregon Rules of Criminal Procedure",
            "",
            "_scrape_criminal_procedure_rules",
        )
    )
    supplemental_statutes.extend(
        await _collect(
            "Oregon Local Court Rules",
            LOCAL_RULES_INDEX_URL,
            "_scrape_local_court_rules",
        )
    )

    supplemental_rules: List[Dict[str, Any]] = []
    for statute in supplemental_statutes:
        enriched = scraper._enrich_statute_structure(statute).to_dict()
        family = _classify_procedure_family(enriched)
        if not family:
            legal_area = str(enriched.get("legal_area") or "").strip().lower()
            if "criminal" in legal_area:
                family = "criminal_procedure"
            elif any(token in legal_area for token in ["civil", "court_rules"]):
                family = "civil_procedure"
        if not family:
            continue
        enriched["procedure_family"] = family
        supplemental_rules.append(enriched)

    return supplemental_rules, scraper.get_fetch_analytics_snapshot()


async def _scrape_michigan_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _MichiganProcedureRulesSupplementFetcher("MI", US_STATES["MI"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for chapter in _MI_COURT_RULES_CHAPTERS:
        if remaining is not None and remaining <= 0:
            break

        chapter_url = str(chapter["url"])
        chapter_key = chapter_url.strip().lower()
        if chapter_key in existing_urls:
            continue

        raw_bytes = await fetcher._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=120)
        if not raw_bytes:
            continue

        html_text = raw_bytes.decode("utf-8", errors="replace")
        statutes = _extract_michigan_rules_from_html(
            html_text,
            chapter_url=chapter_url,
            code_name="Michigan Court Rules",
            procedure_family=str(chapter["procedure_family"]),
            legal_area=str(chapter["legal_area"]),
        )
        if not statutes:
            continue

        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(chapter["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            remaining = None if remaining is None else remaining - 1

        existing_urls.add(chapter_key)

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_california_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _CaliforniaProcedureRulesSupplementFetcher("CA", US_STATES["CA"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for title in _CA_RULE_TITLES:
        if remaining is not None and remaining <= 0:
            break

        title_html = await _fetch_html_with_direct_fallback(
            fetcher,
            str(title["url"]),
            validator=lambda html: len(
                _extract_california_rule_links(
                    html,
                    title_url=str(title["url"]),
                    procedure_family=str(title["procedure_family"]),
                    legal_area=str(title["legal_area"]),
                )[0]
            )
            > 0,
            timeout_seconds=120,
        )
        if not title_html:
            continue
        rule_links, current_as_of = _extract_california_rule_links(
            title_html,
            title_url=str(title["url"]),
            procedure_family=str(title["procedure_family"]),
            legal_area=str(title["legal_area"]),
        )

        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            rule_url = str(rule["url"])
            rule_key = rule_url.strip().lower()
            if rule_key in existing_urls:
                continue

            rule_html = await _fetch_html_with_direct_fallback(
                fetcher,
                rule_url,
                validator=lambda html: _extract_california_rule_from_html(
                    html,
                    rule_url=rule_url,
                    code_name="California Rules of Court",
                    title_name=str(title["title_name"]),
                    procedure_family=str(rule["procedure_family"]),
                    legal_area=str(rule["legal_area"]),
                    current_as_of=current_as_of,
                )
                is not None,
                timeout_seconds=120,
            )
            if not rule_html:
                continue

            statute = _extract_california_rule_from_html(
                rule_html,
                rule_url=rule_url,
                code_name="California Rules of Court",
                title_name=str(title["title_name"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
                current_as_of=current_as_of,
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(rule_key)
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_ohio_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _OhioProcedureRulesSupplementFetcher("OH", US_STATES["OH"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for document in _OH_RULE_DOCUMENTS:
        if remaining is not None and remaining <= 0:
            break

        source_url = str(document["url"])
        if source_url.lower() in existing_urls:
            continue

        raw_bytes = await fetcher._fetch_page_content_with_archival_fallback(source_url, timeout_seconds=180)
        if not raw_bytes:
            continue

        extracted = await fetcher._extract_text_from_document_bytes(
            source_url=source_url,
            raw_bytes=raw_bytes,
        )
        if not isinstance(extracted, dict):
            continue

        cleaned_text = fetcher._normalize_legal_text(str(extracted.get("text") or ""))
        if len(cleaned_text) < 400:
            continue

        statutes = _extract_ohio_rules_from_text(
            cleaned_text,
            source_url=source_url,
            title_name=str(document["title_name"]),
            procedure_family=str(document["procedure_family"]),
            legal_area=str(document["legal_area"]),
            effective_date=str(document.get("effective_date") or "") or None,
        )
        if not statutes:
            continue

        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(document["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            remaining = None if remaining is None else remaining - 1

        existing_urls.add(source_url.lower())

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_arizona_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _ArizonaProcedureRulesSupplementFetcher("AZ", US_STATES["AZ"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for document in _AZ_RULE_DOCUMENTS:
        if remaining is not None and remaining <= 0:
            break

        source_url = str(document["url"])
        if source_url.lower() in existing_urls:
            continue

        raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
            fetcher,
            source_url,
            timeout_seconds=180,
        )
        if not raw_bytes:
            continue

        extracted = await fetcher._extract_text_from_document_bytes(
            source_url=source_url,
            raw_bytes=raw_bytes,
        )
        if not isinstance(extracted, dict):
            continue

        cleaned_text = fetcher._normalize_legal_text(str(extracted.get("text") or ""))
        if len(cleaned_text) < 400:
            continue

        statutes = _extract_arizona_rules_from_text(
            cleaned_text,
            source_url=source_url,
            title_name=str(document["title_name"]),
            procedure_family=str(document["procedure_family"]),
            legal_area=str(document["legal_area"]),
            effective_date=str(document.get("effective_date") or "") or None,
            start_marker=str(document["start_marker"]),
        )
        if not statutes:
            continue

        for statute in statutes:
            if remaining is not None and remaining <= 0:
                break
            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(document["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            remaining = None if remaining is None else remaining - 1

        existing_urls.add(source_url.lower())

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_washington_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _WashingtonProcedureRulesSupplementFetcher("WA", US_STATES["WA"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    for list_page in _WA_RULE_LIST_PAGES:
        if remaining is not None and remaining <= 0:
            break

        list_url = str(list_page["url"])
        list_html = await _fetch_html_with_direct_fallback(
            fetcher,
            list_url,
            validator=lambda html: len(
                _extract_washington_rule_links(
                    html,
                    page_url=list_url,
                    procedure_family=str(list_page["procedure_family"]),
                    legal_area=str(list_page["legal_area"]),
                    official_cite_prefix=str(list_page["official_cite_prefix"]),
                )
            )
            > 0,
            timeout_seconds=120,
        )
        if not list_html:
            continue

        rule_links = _extract_washington_rule_links(
            list_html,
            page_url=list_url,
            procedure_family=str(list_page["procedure_family"]),
            legal_area=str(list_page["legal_area"]),
            official_cite_prefix=str(list_page["official_cite_prefix"]),
        )
        for rule in rule_links:
            if remaining is not None and remaining <= 0:
                break

            source_url = str(rule["url"])
            if source_url.lower() in existing_urls:
                continue

            raw_bytes = await _fetch_pdf_bytes_with_direct_fallback(
                fetcher,
                source_url,
                timeout_seconds=180,
            )
            if not raw_bytes:
                continue

            extracted = await fetcher._extract_text_from_document_bytes(
                source_url=source_url,
                raw_bytes=raw_bytes,
            )
            if not isinstance(extracted, dict):
                continue

            statute = _extract_washington_rule_from_text(
                str(extracted.get("text") or ""),
                source_url=source_url,
                title_name=str(list_page["title_name"]),
                section_number=str(rule["section_number"]),
                section_name=str(rule["section_name"]),
                official_cite_prefix=str(rule["official_cite_prefix"]),
                procedure_family=str(rule["procedure_family"]),
                legal_area=str(rule["legal_area"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


async def _scrape_new_jersey_court_rules_supplement(
    *,
    existing_source_urls: Optional[set[str]] = None,
    max_rules: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fetcher = _NewJerseyProcedureRulesSupplementFetcher("NJ", US_STATES["NJ"])
    existing_urls = {
        str(url or "").strip().lower()
        for url in (existing_source_urls or set())
        if str(url or "").strip()
    }
    remaining = int(max_rules) if max_rules and int(max_rules) > 0 else None
    supplemental_rules: List[Dict[str, Any]] = []

    tree_url = "https://www.njcourts.gov/njcourts_rules_of_court/tree"
    tree_data = await _fetch_json_with_direct_fallback(fetcher, tree_url, timeout_seconds=120)
    if not isinstance(tree_data, list):
        return supplemental_rules, fetcher.get_fetch_analytics_snapshot()

    part_lookup = {row["section"]: row for row in _NJ_RULE_PARTS}
    top_level_rules = [row for row in tree_data if str(row.get("section") or "") in part_lookup]

    for top_rule in top_level_rules:
        if remaining is not None and remaining <= 0:
            break

        section = str(top_rule.get("section") or "")
        rule_meta = part_lookup.get(section)
        if not rule_meta:
            continue

        rule_entries = [top_rule]
        if bool(top_rule.get("lazy")):
            subtree_url = f"https://www.njcourts.gov/njcourts_rules_of_court/subtree?tid={top_rule.get('key')}"
            subtree_data = await _fetch_json_with_direct_fallback(fetcher, subtree_url, timeout_seconds=120)
            if isinstance(subtree_data, list) and subtree_data:
                rule_entries = subtree_data

        for entry in rule_entries:
            if remaining is not None and remaining <= 0:
                break

            key = str(entry.get("key") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not key or not title:
                continue

            match = _NJ_RULE_TITLE_RE.match(title)
            if match:
                section_number = match.group(1).strip()
                section_name = match.group(2).strip()
            elif "-" in title:
                section_number, section_name = title.split("-", 1)
                section_number = section_number.strip()
                section_name = section_name.strip()
            else:
                continue
            if not section_number or not section_name:
                continue

            source_url = f"https://www.njcourts.gov/njcourts_rules_of_court/get-term?tid={key}"
            if source_url.lower() in existing_urls:
                continue

            term_data = await _fetch_json_with_direct_fallback(fetcher, source_url, timeout_seconds=120)
            description_html = ""
            if isinstance(term_data, dict):
                description_html = str(term_data.get("description") or "")
            if not description_html.strip():
                continue

            statute = _extract_new_jersey_rule_from_description(
                description_html,
                section_number=section_number,
                section_name=section_name,
                source_url=f"{source_url}#rule-{section_number.lower().replace(':', '-').replace(' ', '-')}",
                title_name=str(rule_meta["title_name"]),
                procedure_family=str(rule_meta["procedure_family"]),
                legal_area=str(rule_meta["legal_area"]),
            )
            if statute is None:
                continue

            enriched = fetcher._enrich_statute_structure(statute).to_dict()
            family = _classify_procedure_family(enriched) or str(rule_meta["procedure_family"])
            enriched["procedure_family"] = family
            supplemental_rules.append(enriched)
            existing_urls.add(source_url.lower())
            remaining = None if remaining is None else remaining - 1

    return supplemental_rules, fetcher.get_fetch_analytics_snapshot()


def _resolve_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return get_canonical_legal_corpus("state_court_rules").default_local_root()


def _write_jsonld_files(filtered_data: List[Dict[str, Any]], output_dir: Path) -> List[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []

    for state_block in filtered_data:
        state_code = str(state_block.get("state_code") or "").strip().upper()
        statutes = state_block.get("statutes") or []
        if not state_code or not isinstance(statutes, list):
            continue

        out_path = output_dir / f"STATE-{state_code}.jsonld"
        lines = 0
        with out_path.open("w", encoding="utf-8") as handle:
            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                payload = dict(statute)
                payload["procedure_family"] = _classify_procedure_family(statute)
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                lines += 1

        if lines > 0:
            written.append(str(out_path))
        else:
            out_path.unlink(missing_ok=True)

    return written


async def list_state_procedure_rule_jurisdictions() -> Dict[str, Any]:
    return await list_state_jurisdictions()


async def scrape_state_procedure_rules(
    states: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 2.0,
    max_rules: Optional[int] = None,
    output_dir: Optional[str] = None,
    write_jsonld: bool = True,
    strict_full_text: bool = False,
    min_full_text_chars: int = 300,
    hydrate_rule_text: bool = True,
    parallel_workers: int = 6,
    per_state_retry_attempts: int = 1,
    retry_zero_rule_states: bool = True,
    per_state_timeout_seconds: float = 480.0,
) -> Dict[str, Any]:
    try:
        selected_states = [s.upper() for s in (states or []) if s and str(s).upper() in US_STATES]
        if not selected_states or "ALL" in selected_states:
            selected_states = list(US_STATES.keys())

        start = time.time()
        base_result = await scrape_state_laws(
            states=selected_states,
            legal_areas=None,
            output_format=output_format,
            include_metadata=include_metadata,
            rate_limit_delay=rate_limit_delay,
            max_statutes=None,
            output_dir=None,
            write_jsonld=False,
            strict_full_text=strict_full_text,
            min_full_text_chars=min_full_text_chars,
            hydrate_statute_text=hydrate_rule_text,
            parallel_workers=parallel_workers,
            per_state_retry_attempts=per_state_retry_attempts,
            retry_zero_statute_states=retry_zero_rule_states,
            per_state_timeout_seconds=per_state_timeout_seconds,
        )

        raw_data = list(base_result.get("data") or [])
        filtered_data: List[Dict[str, Any]] = []
        rules_count = 0
        zero_rule_states: List[str] = []
        supplemental_fetch_analytics_by_state: Dict[str, Dict[str, Any]] = {}
        family_counts: Dict[str, int] = {
            "civil_procedure": 0,
            "criminal_procedure": 0,
            "civil_and_criminal_procedure": 0,
        }

        for state_block in raw_data:
            if not isinstance(state_block, dict):
                continue

            state_code = str(state_block.get("state_code") or "").upper()
            statutes = list(state_block.get("statutes") or [])
            procedure_statutes: List[Dict[str, Any]] = []
            seen_source_urls = {
                str(statute.get("source_url") or statute.get("sourceUrl") or "").strip().lower()
                for statute in statutes
                if isinstance(statute, dict)
            }

            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                family = _classify_procedure_family(statute)
                if not family:
                    continue
                enriched = dict(statute)
                enriched["procedure_family"] = family
                procedure_statutes.append(enriched)
                family_counts[family] = int(family_counts.get(family, 0)) + 1

            if state_code == "RI":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ri_supplement, ri_fetch_analytics = await _scrape_rhode_island_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ri_supplement:
                    procedure_statutes.extend(ri_supplement)
                    for rule in ri_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ri_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ri_fetch_analytics

            if state_code == "OR":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                or_supplement, or_fetch_analytics = await _scrape_oregon_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if or_supplement:
                    procedure_statutes.extend(or_supplement)
                    for rule in or_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if or_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = or_fetch_analytics

            if state_code == "MI":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                mi_supplement, mi_fetch_analytics = await _scrape_michigan_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if mi_supplement:
                    procedure_statutes.extend(mi_supplement)
                    for rule in mi_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if mi_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = mi_fetch_analytics

            if state_code == "CA":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                ca_supplement, ca_fetch_analytics = await _scrape_california_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if ca_supplement:
                    procedure_statutes.extend(ca_supplement)
                    for rule in ca_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if ca_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = ca_fetch_analytics

            if state_code == "OH":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                oh_supplement, oh_fetch_analytics = await _scrape_ohio_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if oh_supplement:
                    procedure_statutes.extend(oh_supplement)
                    for rule in oh_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if oh_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = oh_fetch_analytics

            if state_code == "AZ":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                az_supplement, az_fetch_analytics = await _scrape_arizona_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if az_supplement:
                    procedure_statutes.extend(az_supplement)
                    for rule in az_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if az_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = az_fetch_analytics

            if state_code == "WA":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                wa_supplement, wa_fetch_analytics = await _scrape_washington_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if wa_supplement:
                    procedure_statutes.extend(wa_supplement)
                    for rule in wa_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if wa_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = wa_fetch_analytics

            if state_code == "NJ":
                remaining_rule_budget = None
                if max_rules and max_rules > 0:
                    remaining_rule_budget = max(int(max_rules) - len(procedure_statutes), 0)
                nj_supplement, nj_fetch_analytics = await _scrape_new_jersey_court_rules_supplement(
                    existing_source_urls=seen_source_urls,
                    max_rules=remaining_rule_budget,
                )
                if nj_supplement:
                    procedure_statutes.extend(nj_supplement)
                    for rule in nj_supplement:
                        family = str(rule.get("procedure_family") or "").strip()
                        if family:
                            family_counts[family] = int(family_counts.get(family, 0)) + 1
                if nj_fetch_analytics:
                    supplemental_fetch_analytics_by_state[state_code] = nj_fetch_analytics

            if max_rules and max_rules > 0:
                procedure_statutes = procedure_statutes[: int(max_rules)]

            out_block = dict(state_block)
            out_block["title"] = f"{US_STATES.get(state_code, state_code)} Court Rules"
            out_block["source"] = "Official State Legislative/Judicial Sources"
            out_block["statutes"] = procedure_statutes
            out_block["rules_count"] = len(procedure_statutes)
            filtered_data.append(out_block)

            rules_count += len(procedure_statutes)
            if len(procedure_statutes) == 0 and state_code:
                zero_rule_states.append(state_code)

        canonical_corpus = get_canonical_legal_corpus("state_court_rules")
        jsonld_paths: List[str] = []
        jsonld_dir: Optional[str] = None
        if write_jsonld:
            output_root = _resolve_output_dir(output_dir)
            jsonld_root = canonical_corpus.jsonld_dir(str(output_root))
            jsonld_paths = _write_jsonld_files(filtered_data, jsonld_root)
            jsonld_dir = str(jsonld_root)

        elapsed = time.time() - start
        metadata = {
            "states_scraped": selected_states,
            "states_count": len(selected_states),
            "rules_count": rules_count,
            "canonical_dataset": canonical_corpus.key,
            "canonical_hf_dataset_id": canonical_corpus.hf_dataset_id,
            "family_counts": family_counts,
            "elapsed_time_seconds": elapsed,
            "scraped_at": datetime.now().isoformat(),
            "rate_limit_delay": rate_limit_delay,
            "parallel_workers": int(parallel_workers),
            "per_state_retry_attempts": int(per_state_retry_attempts),
            "retry_zero_rule_states": bool(retry_zero_rule_states),
            "strict_full_text": bool(strict_full_text),
            "min_full_text_chars": int(min_full_text_chars),
            "hydrate_rule_text": bool(hydrate_rule_text),
            "zero_rule_states": sorted(set(zero_rule_states)) if zero_rule_states else None,
            "jsonld_dir": jsonld_dir,
            "jsonld_files": jsonld_paths if jsonld_paths else None,
            "fetch_analytics_by_state": _merge_fetch_analytics(
                (base_result.get("metadata") or {}).get("fetch_analytics_by_state") or {},
                supplemental_fetch_analytics_by_state,
            ),
            "supplemental_fetch_analytics_by_state": supplemental_fetch_analytics_by_state or None,
            "base_status": base_result.get("status"),
            "base_metadata": base_result.get("metadata") if include_metadata else None,
        }

        status = "success"
        if base_result.get("status") in {"error", "partial_success"}:
            status = "partial_success"
        if rules_count == 0:
            status = "partial_success"

        return {
            "status": status,
            "data": filtered_data,
            "metadata": metadata,
            "output_format": output_format,
        }

    except Exception as exc:
        logger.error("State procedure-rules scraping failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "data": [],
            "metadata": {},
        }


__all__ = [
    "list_state_procedure_rule_jurisdictions",
    "scrape_state_procedure_rules",
]
