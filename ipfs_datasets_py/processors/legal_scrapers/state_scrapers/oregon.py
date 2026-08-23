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

from ipfs_datasets_py.utils import anyio_compat as asyncio
import hashlib
import json
import os
import re
import ssl
import urllib.request
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

try:
    import requests
except ImportError:  # pragma: no cover - requests should normally be available
    requests = None

ORS_LINK_RE = re.compile(r"ors(\d{3}[a-z]?)\.html$", re.IGNORECASE)

ORS_CITATION_RE = re.compile(r"\b\d{1,3}\.\d{3}[a-z]?\b", re.IGNORECASE)
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
    for line in lines[:200]:
        match = pattern.match(line)
        if match:
            value = _norm_space(match.group(1))
            if value:
                return value
    return ""


def _extract_edition_year(lines: Sequence[str]) -> Optional[int]:
    for line in lines[:300]:
        match = re.search(r"\b(20\d{2})\s+edition\b", line, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
    return None


def _section_start_regex(chapter_display: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*({re.escape(chapter_display)}\.\d{{3}}[a-z]?)\b\s*(.*)$", re.IGNORECASE)


def _section_sort_key(section_id: str) -> Tuple[int, str]:
    match = re.match(r"^([0-9]+)\.([0-9]+)([a-z]?)$", str(section_id or ""), flags=re.IGNORECASE)
    if not match:
        return (10**9, str(section_id or ""))
    return (int(match.group(2)), (match.group(3) or "").lower())

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
    _ORS_SECTION_RE = re.compile(r"\b(?P<chapter>\d{1,3}[A-Za-z]?)\.(?P<section>\d{3}[A-Za-z]?)\b")
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
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Oregon."""
        return [
            {
                "name": "Oregon Revised Statutes",
                "url": f"{self.get_base_url()}/bills_laws/ors/ors001.html",
                "type": "Code",
            },
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

        if requests is None:
            return html

        try:
            response = await asyncio.to_thread(
                requests.get,
                url,
                timeout=timeout_seconds,
                headers={"User-Agent": "Mozilla/5.0"},
            )
        except Exception as exc:
            self._record_fetch_event(provider="direct", success=False, error=str(exc))
            return html

        if response.status_code != 200 or not response.text:
            self._record_fetch_event(provider="direct", success=False, error=f"http {response.status_code}")
            return html

        direct_html = response.text
        direct_lowered = direct_html.lower()
        if normalized_terms and not all(term in direct_lowered for term in normalized_terms):
            self._record_fetch_event(provider="direct", success=False, error="missing_expected_terms")
            return html

        self._record_fetch_event(provider="direct", success=True)
        await self._store_page_bytes_in_ipfs_cache(
            url=url,
            payload=response.content,
            provider="direct",
        )
        return direct_html

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
            html = ""
            if requests is not None:
                try:
                    response = requests.get(
                        candidate,
                        timeout=90,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                except Exception as exc:
                    self._record_fetch_event(provider="direct", success=False, error=str(exc))
                else:
                    if response.status_code == 200 and response.text:
                        html = response.text
                        self._record_fetch_event(provider="direct", success=True)
                        await self._store_page_bytes_in_ipfs_cache(
                            url=candidate,
                            payload=response.content,
                            provider="direct",
                        )
                    else:
                        self._record_fetch_event(provider="direct", success=False, error=f"http {response.status_code}")

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
    ) -> List[NormalizedStatute]:
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
        current_id: Optional[str] = None
        current_title: str = ""
        buffer: List[str] = []

        def flush() -> None:
            nonlocal current_id, current_title, buffer
            if not current_id:
                return

            full_text = _norm_space("\n".join(buffer))
            parsed_history = self._extract_legislative_history(full_text)
            clean_text = self._normalize_legal_text(str(parsed_history.get("cleaned_text") or full_text))
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
            }
            sections_raw.append(section_row)

            current_id = None
            current_title = ""
            buffer = []

        for line in lines:
            match = start_re.match(line)
            if match:
                flush()
                current_id = match.group(1)
                current_title = match.group(2) or ""
                buffer = []
                continue
            if current_id:
                buffer.append(line)

        flush()

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
        from .oregon_chapter import configured_chapter_html_path, parse_oregon_chapter_html

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
            seed_bytes = await self._fetch_page_content_with_archival_fallback(
                seed_url, timeout_seconds=90
            )
            if seed_bytes:
                try:
                    soup = BeautifulSoup(seed_bytes, "html.parser")
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
                    chapter_html = chapter_bytes.decode("utf-8", errors="replace")
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
