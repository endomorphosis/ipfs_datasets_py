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

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .oregon_admin_rules import OregonAdministrativeRulesScraper
from .registry import StateScraperRegistry

try:
    import requests
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

    def _make_session(self) -> "requests.Session":
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "ipfs-datasets-oregon-scraper/2.0",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            }
        )
        return session

    def _discover_chapter_urls(self, session: "requests.Session", seed_url: str) -> List[str]:
        try:
            response = session.get(seed_url, timeout=60)
            if int(response.status_code) != 200:
                self.logger.warning(f"Oregon seed request failed ({response.status_code}): {seed_url}")
                return [seed_url]
            soup = BeautifulSoup(response.text, "html.parser")
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
        if "administrative" in str(code_name or "").lower() or "displayChapterRules.action" in str(code_url or ""):
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
            session = self._make_session()
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
                chapter_urls = self._discover_chapter_urls(session, code_url)

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
