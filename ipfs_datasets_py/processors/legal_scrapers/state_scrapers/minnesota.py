"""Scraper for Minnesota state laws.

This module contains the scraper for Minnesota statutes from the official state legislative website.
"""

import asyncio
from typing import List, Dict
import re
import urllib.request
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MinnesotaScraper(BaseStateScraper):
    """Scraper for Minnesota state laws from https://www.revisor.mn.gov"""

    _MN_CHAPTER_URL_RE = re.compile(r"/statutes/cite/([0-9A-Za-z]+)$", re.IGNORECASE)
    _MN_SECTION_URL_RE = re.compile(r"/statutes/cite/[0-9A-Za-z]+\.[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*$", re.IGNORECASE)
    _MN_SECTION_NUMBER_RE = re.compile(r"/statutes/cite/([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)$", re.IGNORECASE)
    _MN_SECTION_ROW_RE = re.compile(r"^(?P<section>[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)+)\s+(?P<title>.+)$")
    _MN_CHAPTER_RANGE_RE = re.compile(r"\b(?P<start>\d{1,3}[A-Za-z]?)\s*-\s*(?P<end>\d{1,3}[A-Za-z]?)\b")

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._MN_SECTION_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Minnesota's legislative website."""
        return "https://www.revisor.mn.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Minnesota."""
        return [{
            "name": "Minnesota Statutes",
            "url": f"{self.get_base_url()}/statutes/cite/609.02",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: int | None = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Minnesota's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        candidate_urls = [
            code_url,
            f"{self.get_base_url()}/statutes/cite/609.02",
            f"{self.get_base_url()}/statutes/",
            f"{self.get_base_url()}/statutes/cite/645.44",
            "https://law.justia.com/codes/minnesota/",
        ]

        seen = set()
        merged: List[NormalizedStatute] = []
        merged_keys = set()
        limit = self._effective_scrape_limit(max_statutes, default=420)
        enough = min(80, limit or 80)

        def _merge(items: List[NormalizedStatute]) -> None:
            for statute in items:
                if limit is not None and len(merged) >= limit:
                    return
                key = str(statute.statute_id or statute.source_url or "").strip().lower()
                if not key or key in merged_keys:
                    continue
                merged_keys.add(key)
                merged.append(statute)

        if self._MN_SECTION_URL_RE.search(str(code_url or "")):
            direct_seed = await self._build_statute_from_section_page(code_name, code_url)
            if direct_seed is not None:
                _merge([direct_seed])
                if len(merged) >= enough:
                    return merged

        chapter_statutes = await self._scrape_chapter_sections(code_name, max_statutes=limit or 1000000)
        _merge(chapter_statutes)
        if len(merged) >= enough:
            return merged

        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Minn. Stat.",
                        max_sections=limit or 1000000,
                        wait_for_selector="a[href*='/statutes/cite/'], a[href*='/statutes/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    _merge(statutes)
                    if len(merged) >= enough:
                        return merged
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Minn. Stat.", max_sections=limit or 1000000)
            statutes = self._filter_section_level(statutes)
            _merge(statutes)
            if len(merged) >= enough:
                return merged

        return merged

    async def _scrape_chapter_sections(self, code_name: str, max_statutes: int) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        limit = max(1, int(max_statutes or 1))
        chapter_budget = min(limit, 320 if self._full_corpus_enabled() else 24)
        chapter_urls = await self._discover_chapter_urls(max_chapters=max(1, chapter_budget))
        if not chapter_urls:
            chapter_urls = [
                f"{self.get_base_url()}/statutes/cite/609",
                f"{self.get_base_url()}/statutes/cite/645",
                f"{self.get_base_url()}/statutes/cite/518",
                f"{self.get_base_url()}/statutes/cite/518B",
                f"{self.get_base_url()}/statutes/cite/169A",
                f"{self.get_base_url()}/statutes/cite/8",
                f"{self.get_base_url()}/statutes/cite/13",
                f"{self.get_base_url()}/statutes/cite/144",
                f"{self.get_base_url()}/statutes/cite/325F",
            ]

        section_urls: List[str] = []
        seen_urls = set()
        for chapter_url in chapter_urls:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(chapter_url, timeout_seconds=35)
            except Exception:
                continue
            if not payload:
                continue
            soup = BeautifulSoup(payload, "html.parser")
            for section_url in self._extract_section_urls_from_chapter_page(soup):
                if section_url in seen_urls:
                    continue
                seen_urls.add(section_url)
                section_urls.append(section_url)
                if len(section_urls) >= limit:
                    break
            if len(section_urls) >= limit:
                break

        if not section_urls:
            return []

        statutes: List[NormalizedStatute] = []
        for section_url in section_urls[:limit]:
            try:
                result = await self._build_statute_from_section_page(code_name, section_url)
            except Exception:
                continue
            if result is None:
                continue
            statutes.append(result)
            if len(statutes) >= limit:
                break

        return statutes

    async def _discover_chapter_urls(self, max_chapters: int) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        index_url = f"{self.get_base_url()}/statutes/"
        try:
            payload = await self._fetch_page_content_with_archival_fallback(index_url, timeout_seconds=35)
        except Exception:
            return []
        if not payload:
            return []

        soup = BeautifulSoup(payload, "html.parser")
        chapter_urls: List[str] = []
        seen = set()

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            match = self._MN_CHAPTER_URL_RE.search(href)
            if not match:
                continue
            chapter_token = match.group(1)
            if "." in chapter_token:
                continue
            full_url = href if href.startswith("http") else f"{self.get_base_url()}{href}"
            if full_url in seen:
                continue
            seen.add(full_url)
            chapter_urls.append(full_url)
            if len(chapter_urls) >= max(1, int(max_chapters)):
                return chapter_urls

        page_text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
        for match in self._MN_CHAPTER_RANGE_RE.finditer(page_text):
            for chapter_token in self._expand_chapter_range(match.group("start"), match.group("end")):
                full_url = f"{self.get_base_url()}/statutes/cite/{chapter_token}"
                if full_url in seen:
                    continue
                seen.add(full_url)
                chapter_urls.append(full_url)
                if len(chapter_urls) >= max(1, int(max_chapters)):
                    return chapter_urls

        return chapter_urls

    def _expand_chapter_range(self, start_token: str, end_token: str) -> List[str]:
        def _split(token: str) -> tuple[int, str]:
            match = re.match(r"^(\d{1,3})([A-Za-z]?)$", str(token or "").strip())
            if not match:
                return 0, ""
            return int(match.group(1)), match.group(2).upper()

        start_num, start_suffix = _split(start_token)
        end_num, end_suffix = _split(end_token)
        if start_num <= 0 or end_num <= 0 or end_num < start_num:
            return []

        if start_num == end_num:
            suffixes = [""]
            if start_suffix or end_suffix:
                begin_ord = ord(start_suffix or "A")
                end_ord = ord(end_suffix or start_suffix or "A")
                suffixes = [chr(code) for code in range(begin_ord, end_ord + 1)]
                if start_suffix == "":
                    suffixes.insert(0, "")
            return [f"{start_num}{suffix}" for suffix in suffixes]

        out = [f"{start_num}{start_suffix}" if start_suffix else str(start_num)]
        for value in range(start_num + 1, end_num):
            out.append(str(value))
        out.append(f"{end_num}{end_suffix}" if end_suffix else str(end_num))
        return out

    def _extract_section_urls_from_chapter_page(self, soup) -> List[str]:
        urls: List[str] = []

        # Minnesota chapter pages expose the authoritative section list in table rows,
        # which is more reliable than inferring coverage from the link structure alone.
        for row in soup.find_all("tr"):
            text = " ".join(row.get_text(" ", strip=True).split())
            if not text:
                continue
            match = self._MN_SECTION_ROW_RE.match(text)
            if not match:
                continue
            urls.append(f"{self.get_base_url()}/statutes/cite/{match.group('section')}")

        if urls:
            return urls

        for link in soup.find_all("a", href=True):
            href = str(link.get("href") or "").strip()
            if not href.startswith("/statutes/cite/"):
                continue
            full_url = href if href.startswith("http") else f"{self.get_base_url()}{href}"
            if self._MN_SECTION_URL_RE.search(full_url):
                urls.append(full_url)

        return urls

    async def _build_statute_from_section_page(self, code_name: str, section_url: str) -> NormalizedStatute | None:
        html_text = await self._request_text_direct(section_url, timeout=18)
        if not html_text:
            try:
                payload = await self._fetch_page_content_with_archival_fallback(section_url, timeout_seconds=35)
            except Exception:
                return None
            if not payload:
                return None
            html_text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        if not html_text:
            return None

        match = self._MN_SECTION_NUMBER_RE.search(section_url)
        section_number = match.group(1) if match else section_url.rsplit("/", 1)[-1]
        text = self._extract_best_content_text(html_text)
        heading_pattern = re.compile(
            rf"\b{re.escape(section_number)}\b\s+[A-Z][A-Z0-9 ,;:'()\-/&]+\.",
            re.IGNORECASE,
        )
        heading_match = heading_pattern.search(text)
        if heading_match:
            text = text[heading_match.start():]
        text = re.split(r"\bHistory:\b", text, maxsplit=1)[0].strip()
        text = re.split(r"\b(?:Official Publication of the State of Minnesota|About the Legislature|General Contact|Get Connected)\b", text, maxsplit=1)[0].strip()
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 160:
            return None

        heading = f"Minnesota Statutes {section_number}"
        title_match = re.search(r"\b%s\b\s+([A-Z][A-Z0-9 ,;:'()\-/&]{4,120})\." % re.escape(section_number), text)
        if title_match:
            heading = f"{section_number} {title_match.group(1).title()}"

        return NormalizedStatute(
            state_code=self.state_code,
            state_name=self.state_name,
            statute_id=f"{code_name} § {section_number}",
            code_name=code_name,
            section_number=section_number,
            section_name=heading[:200],
            full_text=text[:14000],
            source_url=section_url,
            legal_area=self._identify_legal_area(heading),
            official_cite=f"Minn. Stat. § {section_number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_minnesota_statutes_html",
                "discovery_method": "official_seed_or_section_page",
                "skip_hydrate": True,
            },
        )

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""

# Register this scraper with the registry
StateScraperRegistry.register("MN", MinnesotaScraper)
