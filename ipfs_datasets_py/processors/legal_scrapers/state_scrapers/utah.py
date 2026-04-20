"""Scraper for Utah state laws.

This module contains the scraper for Utah statutes from the official state legislative website.
"""

import re
from typing import List, Dict, Optional
from urllib.parse import urljoin
from urllib.parse import quote
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class UtahScraper(BaseStateScraper):
    """Scraper for Utah state laws from https://le.utah.gov"""
    _UT_CHAPTER_RE = re.compile(
        r"Chapter\s+([0-9]+[A-Za-z]?)\s+(.+?)(?=\s+Chapter\s+[0-9]+[A-Za-z]?\s+|\s+<< Previous Title|\s+Download Options|$)",
        re.IGNORECASE,
    )
    
    def get_base_url(self) -> str:
        """Return the base URL for Utah's legislative website."""
        return "https://le.utah.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Utah."""
        return [{
            "name": "Utah Code",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Utah's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._bounded_return_threshold(40)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))

        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[:return_threshold]

        live_title_stubs = await self._scrape_live_title_stubs(code_name, max_statutes=max(10, return_threshold))
        live_chapter_stubs = await self._scrape_live_chapter_stubs(
            code_name,
            title_limit=max(1, min(12, return_threshold)),
            per_title_limit=max(1, min(10, return_threshold)),
        )

        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/xcode/code.html",
            f"{self.get_base_url()}/xcode/",
            f"{self.get_base_url()}/xcode/Title01/",
            "https://law.justia.com/codes/utah/",
            "https://web.archive.org/web/20250101000000/https://law.justia.com/codes/utah/",
        ]
        for archived in await self._discover_archived_title_urls(limit=max(10, return_threshold)):
            if archived not in candidate_urls:
                candidate_urls.append(archived)

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        _merge(live_title_stubs)
        _merge(live_chapter_stubs)
        if len(merged) >= return_threshold:
            return merged

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            statutes = await self._generic_scrape(code_name, candidate, "Utah Code Ann.", max_sections=return_threshold)
            _merge(statutes)
            if len(merged) >= return_threshold:
                return merged

        return merged

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-S203_2025050720250507.html",
            "https://le.utah.gov/xcode/Title76/Chapter5/C76-5-S202_2025050720250507.html",
        ]
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            except Exception:
                payload = b""
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            content = soup.select_one("#content") or soup.find("body")
            text = self._normalize_legal_text(content.get_text(" ", strip=True) if content else "")
            match = re.search(r"\b(\d{1,3}-\d{1,3}-\d+[A-Za-z-]*)\.\s+(.+)", text)
            if not match or len(text) < 280:
                continue
            section_number = match.group(1)
            section_name = self._normalize_legal_text(match.group(2))[:220]
            # Drop the global breadcrumb/nav prefix so records start at the section.
            start_idx = text.find(f"{section_number}.")
            body = self._normalize_legal_text(text[start_idx:] if start_idx >= 0 else text)
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    title_number=section_number.split("-", 1)[0],
                    section_number=section_number,
                    section_name=section_name,
                    full_text=body[:14000],
                    source_url=url,
                    legal_area=self._identify_legal_area(body[:1200]),
                    official_cite=f"Utah Code § {section_number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_utah_code_section_html",
                        "discovery_method": "official_seed_current_version",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _scrape_live_chapter_stubs(
        self,
        code_name: str,
        title_limit: int = 10,
        per_title_limit: int = 8,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        title_rows = await self._scrape_live_title_stubs(code_name, max_statutes=max(1, int(title_limit)))
        out: List[NormalizedStatute] = []
        seen = set()
        for title_row in title_rows[:title_limit]:
            title_url = str(title_row.source_url or "").strip()
            if not title_url:
                continue
            try:
                payload = await self._fetch_page_content_with_archival_fallback(title_url, timeout_seconds=35)
                if not payload:
                    continue
            except Exception:
                continue

            soup = BeautifulSoup(payload, "html.parser")
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if not text:
                continue

            title_number = self._extract_title_number(str(title_row.section_number or ""))
            count = 0
            for match in self._UT_CHAPTER_RE.finditer(text):
                if count >= per_title_limit:
                    break
                chapter_no = match.group(1).strip()
                chapter_name = self._normalize_legal_text(match.group(2))[:220]
                if not chapter_name:
                    continue
                key = f"{title_number}:{chapter_no}:{chapter_name}".lower()
                if key in seen:
                    continue
                seen.add(key)
                count += 1
                out.append(
                    NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § Title {title_number} Chapter {chapter_no}",
                        code_name=code_name,
                        section_number=f"Title {title_number} Chapter {chapter_no}",
                        section_name=f"Chapter {chapter_no} {chapter_name}"[:220],
                        full_text=f"Utah Code Title {title_number} Chapter {chapter_no} {chapter_name}",
                        source_url=title_url,
                        legal_area=self._identify_legal_area(chapter_name),
                        official_cite=f"Utah Code Title {title_number} Chapter {chapter_no}",
                        metadata=StatuteMetadata(),
                    )
                )
        return out

    def _extract_title_number(self, value: str) -> str:
        match = re.search(r"title\s+([0-9]+[A-Z]?)", str(value or ""), re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return self._normalize_legal_text(value) or "UNKNOWN"

    async def _scrape_live_title_stubs(self, code_name: str, max_statutes: int = 60) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        url = f"{self.get_base_url()}/xcode/code.html"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=35)
            if not payload:
                return []
        except Exception:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        out: List[NormalizedStatute] = []
        seen = set()
        title_re = re.compile(r"title\s+([0-9]+[A-Z]?)", re.IGNORECASE)

        for a in soup.find_all("a", href=True):
            if len(out) >= max_statutes:
                break
            href = str(a.get("href") or "").strip()
            text = str(a.get_text(" ", strip=True) or "").strip()
            full_url = urljoin(url, href)
            if "/xcode/title" not in full_url.lower():
                continue

            match = title_re.search(text) or title_re.search(full_url)
            if not match:
                continue
            title_number = match.group(1).upper()
            key = title_number.lower()
            if key in seen:
                continue
            seen.add(key)

            title_name = text[:200] if text else f"Title {title_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § Title {title_number}",
                    code_name=code_name,
                    section_number=f"Title {title_number}",
                    section_name=title_name,
                    full_text=f"Utah Code {title_name}: {full_url}",
                    source_url=full_url,
                    legal_area=self._identify_legal_area(title_name),
                    official_cite=f"Utah Code Title {title_number}",
                    metadata=StatuteMetadata(),
                )
            )

        return out

    async def _discover_archived_title_urls(self, limit: int = 180) -> List[str]:
        cdx_url = (
            "https://web.archive.org/cdx/search/cdx"
            "?url=le.utah.gov/xcode/Title*"
            "&output=json&filter=statuscode:200"
            f"&limit={max(1, int(limit))}"
        )

        try:
            payload = await self._fetch_page_content_with_archival_fallback(cdx_url, timeout_seconds=35)
            rows = self._parse_json_rows(payload)
        except Exception:
            return []

        out: List[str] = []
        seen = set()
        for row in rows:
            if len(row) < 3:
                continue
            ts = str(row[1] or "").strip()
            original = str(row[2] or "").strip()
            if not ts or not original:
                continue
            lower_original = original.lower()
            if "/xcode/title" not in lower_original:
                continue
            replay = f"https://web.archive.org/web/{ts}/{quote(original, safe=':/?=&._-')}"
            if replay in seen:
                continue
            seen.add(replay)
            out.append(replay)
            if len(out) >= limit:
                break

        return out


# Register this scraper with the registry
StateScraperRegistry.register("UT", UtahScraper)
