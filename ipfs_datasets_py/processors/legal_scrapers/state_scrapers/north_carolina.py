"""Scraper for North Carolina state laws.

This module contains the scraper for North Carolina statutes from the official state legislative website.
"""

from typing import List, Dict, Optional
import re
import urllib.request
from urllib.parse import urljoin
from .base_scraper import BaseStateScraper, NormalizedStatute
from .registry import StateScraperRegistry


class NorthCarolinaScraper(BaseStateScraper):
    """Scraper for North Carolina state laws from https://www.ncleg.gov"""

    _NC_SECTION_URL_RE = re.compile(r"/enactedlegislation/statutes/html/bysection/chapter_[0-9A-Za-z]+/gs_[0-9A-Za-z\-\.]+\.html$", re.IGNORECASE)
    _NC_CHAPTER_URL_RE = re.compile(r"/laws/generalstatutesections/chapter[0-9A-Za-z]+$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._NC_SECTION_URL_RE.search(source) or self._NC_CHAPTER_URL_RE.search(source):
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for North Carolina's legislative website."""
        return "https://www.ncleg.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for North Carolina."""
        return [{
            "name": "North Carolina General Statutes",
            "url": f"{self.get_base_url()}/Laws/GeneralStatutes",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from North Carolina's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return_threshold = self._effective_scrape_limit(max_statutes, default=160) or 1000000
        official = await self._scrape_official_index(
            code_name,
            max_statutes=None if return_threshold == 1000000 else int(return_threshold),
        )
        if official:
            return official[: int(return_threshold)]

        candidate_urls = [
            f"{self.get_base_url()}/Laws/GeneralStatuteSections/Chapter1",
            f"{self.get_base_url()}/Laws/GeneralStatutesTOC",
            code_url,
            f"{self.get_base_url()}/Laws/GeneralStatutes",
            f"{self.get_base_url()}/Laws",
            # Archive fallback candidate when live endpoints fluctuate.
            "https://web.archive.org/web/20251017000000/https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter1",
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        if not self._full_corpus_enabled():
            direct = await self._scrape_direct_seed_sections(code_name, max_statutes=return_threshold)
            if direct:
                return direct[: int(return_threshold)]
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "N.C. Gen. Stat.",
                        max_sections=max(10, return_threshold),
                        wait_for_selector="a[href*='/BySection/'][href*='GS_'], a[href*='/GeneralStatuteSections/']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= int(return_threshold):
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "N.C. Gen. Stat.", max_sections=max(10, return_threshold))
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= int(return_threshold):
                return statutes

        return best_statutes

    async def _scrape_official_index(
        self,
        code_name: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        chapter_urls = await self._discover_chapter_urls()
        self.logger.info("North Carolina official index: discovered %s chapter urls", len(chapter_urls))
        statutes: List[NormalizedStatute] = []
        limit = max(1, int(max_statutes)) if max_statutes is not None else None
        for chapter_index, chapter_url in enumerate(chapter_urls, start=1):
            if limit is not None and len(statutes) >= limit:
                break
            remaining = None if limit is None else max(0, limit - len(statutes))
            if remaining is not None and remaining <= 0:
                break
            section_urls = await self._discover_section_urls(chapter_url, limit=remaining)
            parsed = await self._scrape_section_urls(
                code_name,
                section_urls,
                max_statutes=remaining,
            )
            statutes.extend(parsed)
            if chapter_index == 1 or chapter_index % 25 == 0 or chapter_index == len(chapter_urls):
                self.logger.info(
                    "North Carolina official index: chapter=%s/%s sections=%s statutes_so_far=%s",
                    chapter_index,
                    len(chapter_urls),
                    len(section_urls),
                    len(statutes),
                )
        return statutes[:limit] if limit is not None else statutes

    async def _discover_chapter_urls(self) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        toc_url = f"{self.get_base_url()}/Laws/GeneralStatutesTOC"
        html = await self._request_text_direct(toc_url, timeout=30)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href.startswith("/Laws/GeneralStatuteSections/Chapter"):
                continue
            absolute = urljoin(toc_url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
        return out

    async def _discover_section_urls(self, chapter_url: str, limit: Optional[int] = None) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        html = await self._request_text_direct(chapter_url, timeout=40)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href.startswith("/EnactedLegislation/Statutes/HTML/BySection/Chapter_") or not href.endswith(".html"):
                continue
            absolute = urljoin(chapter_url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
            if limit is not None and len(out) >= int(limit):
                break
        return out

    async def _scrape_section_urls(
        self,
        code_name: str,
        section_urls: List[str],
        *,
        max_statutes: Optional[int],
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
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 80:
                continue
            section_number_match = re.search(r"§\s*([0-9A-Za-z\-\.]+)\.", text)
            section_number = section_number_match.group(1).strip() if section_number_match else ""
            if not section_number:
                derived = source_url.rsplit("/", 1)[-1]
                derived = re.sub(r"^GS_", "", derived, flags=re.IGNORECASE)
                derived = re.sub(r"\.html$", "", derived, flags=re.IGNORECASE)
                section_number = derived.replace("_", "-")
            section_name_match = re.search(rf"§\s*{re.escape(section_number)}\.\s*([^\.]{{2,220}})", text)
            section_name = self._normalize_legal_text(section_name_match.group(1)) if section_name_match else f"G.S. {section_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text[:14000],
                    legal_area=self._identify_legal_area(section_name or text[:800]),
                    source_url=source_url,
                    official_cite=f"N.C. Gen. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_north_carolina_general_statutes_html",
                        "discovery_method": "official_toc_chapter_section_html",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

    async def _scrape_direct_seed_sections(self, code_name: str, max_statutes: int = 1) -> List[NormalizedStatute]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            ("1-1", f"{self.get_base_url()}/EnactedLegislation/Statutes/HTML/BySection/Chapter_1/GS_1-1.html"),
            ("14-17", f"{self.get_base_url()}/EnactedLegislation/Statutes/HTML/BySection/Chapter_14/GS_14-17.html"),
        ]
        out: List[NormalizedStatute] = []
        for section_number, source_url in seeds[: max(1, int(max_statutes or 1))]:
            html = await self._request_text_direct(source_url, timeout=18)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = self._normalize_legal_text(soup.get_text(" ", strip=True))
            if len(text) < 80:
                continue
            name_match = re.search(rf"§\s*{re.escape(section_number)}[.;]?\s*([^§]{{4,180}}?)(?:\.|$)", text)
            section_name = name_match.group(1).strip() if name_match else f"G.S. {section_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name[:200],
                    full_text=text[:14000],
                    legal_area=self._identify_legal_area(section_name),
                    source_url=source_url,
                    official_cite=f"N.C. Gen. Stat. § {section_number}",
                    structured_data={
                        "source_kind": "official_north_carolina_general_statutes_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out

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
StateScraperRegistry.register("NC", NorthCarolinaScraper)
