"""Scraper for Maine state laws.

This module contains the scraper for Maine statutes from the official state legislative website.
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute
from .base_scraper import StatuteMetadata
from .registry import StateScraperRegistry


class MaineScraper(BaseStateScraper):
    """Scraper for Maine state laws from http://legislature.maine.gov"""

    _ME_SECTION_URL_RE = re.compile(r"/statutes/[0-9A-Za-z\-]+/title[0-9A-Za-z\-]+sec[0-9A-Za-z\-]+\.html$", re.IGNORECASE)
    _ME_CHAPTER_INDEX_RE = re.compile(r"/title[0-9A-Za-z\-]+ch[0-9A-Za-z\-]+sec0\.html$", re.IGNORECASE)

    def _filter_section_level(self, statutes: List[NormalizedStatute]) -> List[NormalizedStatute]:
        filtered: List[NormalizedStatute] = []
        for statute in statutes:
            source = str(statute.source_url or "")
            if self._ME_SECTION_URL_RE.search(source) and not self._ME_CHAPTER_INDEX_RE.search(source):
                if str(statute.section_number or "").startswith("Section-"):
                    m = re.search(r"title[0-9A-Za-z\-]+sec([0-9A-Za-z\-]+)\.html$", source, re.IGNORECASE)
                    if m:
                        statute.section_number = m.group(1)
                filtered.append(statute)
        return filtered
    
    def get_base_url(self) -> str:
        """Return the base URL for Maine's legislative website."""
        return "http://legislature.maine.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Maine."""
        return [{
            "name": "Maine Revised Statutes",
            "url": f"{self.get_base_url()}/",
            "type": "Code"
        }]
    
    async def scrape_code(
        self,
        code_name: str,
        code_url: str,
        max_statutes: Optional[int] = None,
    ) -> List[NormalizedStatute]:
        """Scrape a specific code from Maine's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        direct_limit = self._effective_scrape_limit(max_statutes, default=2)
        direct = await self._scrape_direct_seed_sections(
            code_name,
            max_statutes=max(1, int(direct_limit or 2)),
        )
        if direct and not self._full_corpus_enabled():
            return direct[: max(1, int(direct_limit or len(direct)))]

        candidate_urls = [
            "https://legislature.maine.gov/statutes/1/title1ch1sec0.html",
            "https://legislature.maine.gov/statutes/17-A/title17-Ach1sec0.html",
            "https://legislature.maine.gov/statutes/",
            code_url,
        ]

        seen = set()
        best_statutes: List[NormalizedStatute] = []
        return_threshold = self._bounded_return_threshold(30)
        if max_statutes is not None:
            return_threshold = max(1, min(return_threshold, int(max_statutes)))
        for candidate in candidate_urls:
            if candidate in seen:
                continue
            seen.add(candidate)

            if self.has_playwright():
                try:
                    statutes = await self._playwright_scrape(
                        code_name,
                        candidate,
                        "Me. Rev. Stat.",
                        max_sections=max(10, return_threshold),
                        wait_for_selector="a[href*='sec'][href$='.html'], a[href*='ch'][href$='sec0.html']",
                        timeout=45000,
                    )
                    statutes = self._filter_section_level(statutes)
                    if len(statutes) > len(best_statutes):
                        best_statutes = statutes
                    if len(statutes) >= return_threshold:
                        return statutes
                except Exception:
                    pass

            statutes = await self._generic_scrape(code_name, candidate, "Me. Rev. Stat.", max_sections=max(10, return_threshold))
            statutes = self._filter_section_level(statutes)
            if len(statutes) > len(best_statutes):
                best_statutes = statutes
            if len(statutes) >= return_threshold:
                return statutes

        return best_statutes

    async def _scrape_direct_seed_sections(
        self,
        code_name: str,
        max_statutes: int = 2,
    ) -> List[NormalizedStatute]:
        """Parse official Maine section pages into full statute records."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        seeds = [
            "https://legislature.maine.gov/statutes/1/title1sec1.html",
            "https://legislature.maine.gov/statutes/17-A/title17-Asec1.html",
        ]
        out: List[NormalizedStatute] = []
        for url in seeds[: max(1, int(max_statutes or 1))]:
            raw = await self._fetch_page_content_with_archival_fallback(url, timeout_seconds=25)
            if not raw:
                continue
            try:
                html = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            heading = self._normalize_legal_text(
                (soup.select_one(".heading_section") or soup.find("title") or soup).get_text(" ", strip=True)
            )
            body_node = soup.select_one("div.row.section-content") or soup.select_one("div.MRSSection")
            body = self._normalize_legal_text(body_node.get_text(" ", strip=True) if body_node else "")
            if len(body) < 160:
                text_nodes = [
                    self._normalize_legal_text(node.get_text(" ", strip=True))
                    for node in soup.select("div.mrs-text, div.qhistory")
                ]
                body = self._normalize_legal_text(" ".join(text_nodes))
            if len(body) < 160:
                continue

            title_match = re.search(r"/title([0-9A-Za-z\-]+)sec", url, flags=re.IGNORECASE)
            section_match = re.search(r"sec([0-9A-Za-z\-]+)\.html$", url, flags=re.IGNORECASE)
            title_number = title_match.group(1) if title_match else None
            section_number = section_match.group(1) if section_match else (self._extract_section_number(heading) or "")
            section_name = re.sub(r"^§\s*[\w\-]+\.?\s*", "", heading).strip() or heading
            official_cite = f"Me. Rev. Stat. tit. {title_number}, § {section_number}" if title_number else f"Me. Rev. Stat. § {section_number}"
            out.append(
                NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} {official_cite}",
                    code_name=code_name,
                    title_number=title_number,
                    section_number=section_number,
                    section_name=section_name,
                    full_text=body,
                    legal_area=self._identify_legal_area(body[:1200]),
                    source_url=url,
                    official_cite=official_cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_maine_revised_statutes_html",
                        "discovery_method": "official_seed_section",
                        "skip_hydrate": True,
                    },
                )
            )
        return out


# Register this scraper with the registry
StateScraperRegistry.register("ME", MaineScraper)
