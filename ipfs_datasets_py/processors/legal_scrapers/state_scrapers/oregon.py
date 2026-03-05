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

import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
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
                "name": "Oregon Administrative Rules",
                "url": OregonAdministrativeRulesScraper.seed_chapter_url(),
                "type": "Regulation",
            },
        ]

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
        candidate_urls = [code_url, ORCP_PRIMARY_URL, ORCP_EXPANDED_URL]
        discovered = await self._discover_other_rules_entries(["civil procedure", "orcp"])
        candidate_urls.extend(row["url"] for row in discovered)
        candidate_urls = _dedupe_keep_order(candidate_urls)

        statutes: List[NormalizedStatute] = []
        for candidate in candidate_urls:
            parsed = await self._generic_scrape(code_name, candidate, "ORCP", max_sections=700)
            statutes.extend(parsed)

            page_bytes = await self._fetch_page_content_with_archival_fallback(candidate, timeout_seconds=90)
            if page_bytes:
                html = page_bytes.decode("utf-8", errors="replace")
                statutes.extend(self._extract_orcp_rules_from_html(html, candidate, code_name))

        if not statutes:
            statutes = await self._playwright_scrape(
                code_name,
                ORCP_PRIMARY_URL,
                "ORCP",
                wait_for_selector="a[href*='ORCP'], a[href*='orcp'], a[href*='.pdf']",
                timeout=50000,
                max_sections=700,
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
            parsed = await self._generic_scrape(code_name, row["url"], "ORCrP", max_sections=500)
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
                max_sections=240,
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
            max_sections=500,
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
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Oregon's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        lower_name = str(code_name or "").lower()
        lower_url = str(code_url or "").lower()

        if "local court rules" in lower_name or "/rules/pages/slr.aspx" in lower_url:
            self.logger.info("Oregon: using dedicated local-court-rules scraper path")
            return await self._scrape_local_court_rules(code_name, code_url or LOCAL_RULES_INDEX_URL)

        if "civil procedure" in lower_name or lower_url.endswith("/pages/orcp.aspx") or lower_url.endswith("/siteassets/orcp.html"):
            self.logger.info("Oregon: using dedicated ORCP scraper path")
            return await self._scrape_civil_procedure_rules(code_name, code_url or ORCP_PRIMARY_URL)

        if "criminal procedure" in lower_name:
            self.logger.info("Oregon: using dedicated ORCrP scraper path")
            return await self._scrape_criminal_procedure_rules(code_name)

        if "administrative" in lower_name or "displaychapterrules.action" in lower_url:
            self.logger.info("Oregon: using dedicated OAR scraper")
            oar_scraper = OregonAdministrativeRulesScraper(self)
            oar_statutes = await oar_scraper.scrape(code_name=code_name, code_url=code_url)
            if oar_statutes:
                self.logger.info(f"Oregon OAR: parsed {len(oar_statutes)} rules")
                return oar_statutes
            self.logger.warning("Oregon OAR scraper produced no rules; falling back to generic parser")
            return await self._generic_scrape(code_name, code_url, "OAR", max_sections=400)

        citation_format = "Or. Rev. Stat."
        if not REQUESTS_AVAILABLE:
            self.logger.warning("requests/bs4 unavailable for Oregon parser; falling back to Playwright link scrape")
            return await self._playwright_scrape(
                code_name,
                code_url,
                citation_format,
                wait_for_selector="a[href*='ors']",
                timeout=45000,
                max_sections=250,
            )

        legal_area = self._identify_legal_area(code_name)
        statutes: List[NormalizedStatute] = []

        try:
            chapter_urls: List[str] = []

            seed_bytes = await self._fetch_page_content_with_archival_fallback(code_url, timeout_seconds=90)
            if seed_bytes:
                try:
                    soup = BeautifulSoup(seed_bytes, "html.parser")
                    discovered: List[str] = []
                    for anchor in soup.find_all("a", href=True):
                        href = str(anchor.get("href") or "")
                        absolute = urljoin(code_url, href)
                        if ORS_LINK_RE.search(absolute):
                            discovered.append(absolute)
                    chapter_urls = _dedupe_keep_order(discovered)
                except Exception:
                    chapter_urls = []

            if not chapter_urls:
                chapter_urls = await self._discover_chapter_urls(code_url)

            self.logger.info(f"Oregon: discovered {len(chapter_urls)} ORS chapter pages")

            for chapter_url in chapter_urls:
                try:
                    chapter_bytes = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=90)
                    if not chapter_bytes:
                        self.logger.warning(f"Oregon chapter fetch failed (no content): {chapter_url}")
                        continue

                    chapter_html = chapter_bytes.decode("utf-8", errors="replace")
                    statutes.extend(
                        self._parse_chapter_html(
                            html=chapter_html,
                            chapter_url=chapter_url,
                            code_name=code_name,
                            citation_format=citation_format,
                            legal_area=legal_area,
                        )
                    )
                except Exception as chapter_exc:
                    self.logger.warning(f"Oregon chapter parse error for {chapter_url}: {chapter_exc}")
                    continue
        except Exception as exc:
            self.logger.error(f"Oregon scrape failed: {exc}")

        if statutes:
            self.logger.info(f"Oregon: parsed {len(statutes)} structured ORS sections")
            return statutes

        self.logger.warning("Oregon parser produced no structured sections; using Playwright fallback")
        return await self._playwright_scrape(
            code_name,
            code_url,
            citation_format,
            wait_for_selector="a[href*='ors']",
            timeout=45000,
            max_sections=250,
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
