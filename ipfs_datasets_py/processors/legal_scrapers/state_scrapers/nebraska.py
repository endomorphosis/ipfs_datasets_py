"""Scraper for Nebraska state laws.

This module contains the scraper for Nebraska statutes from the official state legislative website.
"""

import re
import urllib.request
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse, parse_qs
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NebraskaScraper(BaseStateScraper):
    """Scraper for Nebraska state laws from https://nebraskalegislature.gov"""

    _NE_CHAPTER_URL_RE = re.compile(r"/laws/browse-chapters\.php\?chapter=\d+[A-Za-z]?$", re.IGNORECASE)
    _NE_SECTION_NUMBER_RE = re.compile(r"^\d+[A-Za-z]?(?:-\d+[A-Za-z]?)+(?:\.\d+)?$")
    
    def get_base_url(self) -> str:
        """Return the base URL for Nebraska's legislative website."""
        return "https://nebraskalegislature.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Nebraska."""
        return [{
            "name": "Nebraska Revised Statutes",
            "url": f"{self.get_base_url()}/laws/browse-statutes.php",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Nebraska's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        limit = self._effective_scrape_limit(max_statutes, default=40) or 1000000
        official = await self._scrape_official_index(
            code_name,
            max_statutes=None if limit == 1000000 else int(limit),
        )
        if official:
            return official[: int(limit)]
        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=int(limit))
            if direct:
                return direct[: int(limit)]
        fallback_limit = max(10, int(limit if limit != 1000000 else 40))
        return await self._generic_scrape(code_name, code_url, "Neb. Rev. Stat.", max_sections=fallback_limit)

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        chapter_urls = await self._discover_chapter_urls()
        self.logger.info("Nebraska official index: discovered %s chapter urls", len(chapter_urls))
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, chapter_url in enumerate(chapter_urls, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            section_urls = await self._discover_section_urls(chapter_url)
            parsed = await self._scrape_section_urls(
                code_name,
                section_urls,
                max_statutes=(None if limit is None else max(0, limit - len(statutes))),
                discovery_method="official_chapter_index_sections",
            )
            statutes.extend(parsed)
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_urls):
                self.logger.info(
                    "Nebraska official index: chapter=%s/%s sections=%s statutes_so_far=%s",
                    chapter_index,
                    len(chapter_urls),
                    len(section_urls),
                    len(statutes),
                )
        return statutes[:limit] if limit is not None else statutes

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 2) -> List[NormalizedStatute]:
        seeds = [
            ("1-101", f"{self.get_base_url()}/laws/statutes.php?statute=1-101"),
            ("28-303", f"{self.get_base_url()}/laws/statutes.php?statute=28-303"),
        ]
        return await self._scrape_section_urls(
            code_name,
            [url for _, url in seeds[: max(1, int(max_statutes or 1))]],
            max_statutes=max_statutes,
            discovery_method="official_seed_section",
        )

    async def _discover_chapter_urls(self) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        browse_url = f"{self.get_base_url()}/laws/browse-statutes.php"
        html = await self._request_text_direct(browse_url, timeout=30)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            absolute = urljoin(browse_url, href)
            if not self._NE_CHAPTER_URL_RE.search(urlparse(absolute).path + ("?" + urlparse(absolute).query if urlparse(absolute).query else "")):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
        return out

    async def _discover_section_urls(self, chapter_url: str) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._request_text_direct(chapter_url, timeout=30)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if "statute=" not in href.lower() or "print=true" in href.lower():
                continue
            absolute = urljoin(chapter_url, href)
            section_number = self._section_number_from_url(absolute)
            if not self._NE_SECTION_NUMBER_RE.match(section_number):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[str],
        *,
        max_statutes: Optional[int],
        discovery_method: str,
    ) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        out: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for source_url in section_urls:
            if limit is not None and len(out) >= limit:
                break
            html = await self._request_text_direct(source_url, timeout=20)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            statute_panel = soup.select_one("div.statute") or soup.select_one("div.card-body")
            if statute_panel is None:
                continue
            for tag in statute_panel(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            section_number = self._normalize_legal_text((statute_panel.find("h2") or statute_panel).get_text(" ", strip=True)).rstrip(".")
            if not self._NE_SECTION_NUMBER_RE.match(section_number):
                section_number = self._section_number_from_url(source_url)
            if not self._NE_SECTION_NUMBER_RE.match(section_number):
                continue
            section_name = self._normalize_legal_text((statute_panel.find("h3") or statute_panel).get_text(" ", strip=True))
            full_text = self._normalize_legal_text(statute_panel.get_text(" ", strip=True))
            if len(full_text) < 40:
                continue
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=(section_name or f"Section {section_number}")[:200],
                    full_text=full_text[:14000],
                    legal_area=self._identify_legal_area(section_name or full_text[:800]),
                    source_url=source_url,
                    official_cite=f"Neb. Rev. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_nebraska_statutes_html",
                        "discovery_method": discovery_method,
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    def _section_number_from_url(self, url: str) -> str:
        try:
            value = str((parse_qs(urlparse(url).query).get("statute") or [""])[0]).strip()
        except Exception:
            return ""
        return value

    async def _request_text_direct(self, url: str, timeout: int = 18) -> str:
        def _request() -> str:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return ""

        try:
            import asyncio

            return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 2)
        except Exception:
            return ""


# Register this scraper with the registry
StateScraperRegistry.register("NE", NebraskaScraper)
