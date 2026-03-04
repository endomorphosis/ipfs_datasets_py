"""Scraper for Missouri state laws.

This module contains the scraper for Missouri statutes from the official state legislative website.
"""

from typing import List, Dict
from urllib.parse import parse_qs, urljoin, urlparse
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MissouriScraper(BaseStateScraper):
    """Scraper for Missouri state laws from http://www.moga.mo.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Missouri's legislative website."""
        return "https://revisor.mo.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Missouri."""
        return [{
            "name": "Missouri Revised Statutes",
            "url": f"{self.get_base_url()}/main/Home.aspx",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Missouri's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Use custom scraper with Missouri-specific patterns
        return await self._custom_scrape_missouri(code_name, code_url, "Mo. Rev. Stat.")
    
    async def _custom_scrape_missouri(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Missouri's legislative website.
        
        Use the Missouri Revisor site and gather section links from chapter pages.
        This avoids very slow fallback URL chains that can cause global timeout.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        }

        try:
            home_url = f"{self.get_base_url()}/main/Home.aspx"
            home_bytes = await self._fetch_page_content_with_archival_fallback(
                home_url,
                timeout_seconds=20,
            )
            if not home_bytes:
                return []
            soup = BeautifulSoup(home_bytes, 'html.parser')
        except Exception as e:
            self.logger.warning(f"Missouri: failed to load home page: {e}")
            return []

        chapter_urls = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if 'OneChapter.aspx?chapter=' not in href:
                continue
            full = urljoin(home_url, href)
            if full not in chapter_urls:
                chapter_urls.append(full)

        # Keep crawl bounded to avoid state-level timeout.
        chapter_urls = chapter_urls[:8]
        seen_sections = set()

        for chapter_url in chapter_urls:
            if len(statutes) >= max_sections:
                break
            chapter_vals = parse_qs(urlparse(chapter_url).query).get('chapter') or []
            chapter_number = (chapter_vals[0].strip() if chapter_vals else '')
            try:
                chapter_bytes = await self._fetch_page_content_with_archival_fallback(
                    chapter_url,
                    timeout_seconds=20,
                )
                if not chapter_bytes:
                    continue
                chap_soup = BeautifulSoup(chapter_bytes, 'html.parser')
            except Exception:
                continue

            for link in chap_soup.find_all('a', href=True):
                if len(statutes) >= max_sections:
                    break
                href = link.get('href', '')
                if 'OneSection.aspx?section=' not in href:
                    continue

                full_url = urljoin(chapter_url, href)
                parsed = urlparse(full_url)
                section_vals = parse_qs(parsed.query).get('section') or []
                section_number = (section_vals[0].strip() if section_vals else '')
                if not section_number:
                    continue
                if section_number in seen_sections:
                    continue
                seen_sections.add(section_number)

                link_text = link.get_text(' ', strip=True) or f"Section {section_number}"
                section_name = link_text[:200]
                if section_number not in section_name:
                    section_name = f"Section {section_number}: {section_name}"[:200]

                legal_area = self._identify_legal_area(link_text or code_name)
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name,
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata()
                )
                statutes.append(statute)

        # Missouri sometimes serves heavily collapsed chapter pages where only one
        # repeated section link is visible. Use chapter links as a bounded fallback.
        if len(statutes) < 10:
            for chapter_url in chapter_urls:
                if len(statutes) >= max_sections:
                    break
                chapter_vals = parse_qs(urlparse(chapter_url).query).get('chapter') or []
                chapter_number = (chapter_vals[0].strip() if chapter_vals else '')
                if not chapter_number or chapter_number in seen_sections:
                    continue
                seen_sections.add(chapter_number)

                chapter_label = f"Chapter {chapter_number}"
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {chapter_number}",
                    code_name=code_name,
                    section_number=chapter_number,
                    section_name=chapter_label,
                    full_text=f"{chapter_label}: Missouri Revised Statutes chapter",
                    legal_area=self._identify_legal_area(chapter_label),
                    source_url=chapter_url,
                    official_cite=f"{citation_format} ch. {chapter_number}",
                    metadata=StatuteMetadata(),
                )
                statutes.append(statute)

        self.logger.info(f"Missouri custom scraper: Scraped {len(statutes)} sections")
        if not statutes:
            self.logger.warning("Missouri custom scraper found no section-level links")
            return []
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("MO", MissouriScraper)
