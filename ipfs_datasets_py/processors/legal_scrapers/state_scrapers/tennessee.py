"""Scraper for Tennessee state laws.

This module contains the scraper for Tennessee statutes from the official state legislative website.
"""

import re
import warnings
from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry

# Suppress SSL warnings for tn.gov
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


class TennesseeScraper(BaseStateScraper):
    """Scraper for Tennessee state laws from https://www.tn.gov/tga"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Tennessee's legislative website."""
        return "https://www.tn.gov/tga"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Tennessee."""
        return [{
            "name": "Tennessee Code Annotated",
            "url": "https://www.capitol.tn.gov/legislation/archives.html",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Tennessee's legislative website.
        
        Tennessee's site frequently has connection issues.
        This scraper tries multiple approaches:
        1. HTTP with SSL bypass for reliable sources
        2. Playwright for JavaScript rendering
        3. Internet Archive
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        # Try alternative URLs if main URL fails
        # Note: Tennessee's SSL certificate often has issues, use verify=False in requests
        # Tennessee URLs with extended timeout and SSL verification disabled
        alternative_urls = [
            "https://www.capitol.tn.gov/legislation/archives.html",
            "https://publications.tnsosfiles.com/acts/",
            code_url,
            "http://web.archive.org/web/20230101000000*/tn.gov/*/statutes*"
        ]
        
        # Try custom scraper with SSL bypass first
        for url_attempt in alternative_urls[:2]:
            try:
                self.logger.info(f"Tennessee: Attempting custom scrape with {url_attempt}")
                statutes = await self._custom_scrape_tennessee(
                    code_name,
                    url_attempt,
                    "Tenn. Code Ann.",
                    max_sections=50
                )
                if statutes:
                    return statutes
            except Exception as e:
                self.logger.warning(f"Tennessee custom scrape failed for {url_attempt}: {e}")
        
        # Fallback to HTTP scraper with all alternative URLs
        self.logger.info("Tennessee: Using fallback HTTP scraper")
        for url_attempt in alternative_urls:
            try:
                self.logger.info(f"Tennessee: Attempting HTTP scrape with {url_attempt}")
                result = await self._custom_scrape_tennessee(code_name, url_attempt, "Tenn. Code Ann.")
                if result:
                    return result
            except Exception as e:
                self.logger.warning(f"Tennessee: HTTP scrape failed for {url_attempt}: {e}")
                continue
        
        # If all attempts failed, return empty list with guidance
        self.logger.error("Tennessee: All scraping attempts failed")
        self.logger.info("For Tennessee, the site may be temporarily down. Try:")
        self.logger.info("  1. Wait and retry later")
        self.logger.info("  2. Use publications.tnsosfiles.com")
        self.logger.info("  3. Access via Internet Archive")
        return []


    async def _custom_scrape_tennessee(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Tennessee with SSL bypass."""
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=45,
            )
            if not page_bytes:
                return []

            soup = BeautifulSoup(page_bytes, 'html.parser')
            links = soup.find_all('a', href=True)
            
            section_count = 0
            statute_number_re = re.compile(r"\b\d{1,2}-\d{1,3}-\d+[A-Za-z-]*\b")
            chapter_re = re.compile(r"\b(?:chapter|ch\.?|title|section|sec\.?)\s*\d+", re.IGNORECASE)
            ga_re = re.compile(r"\b\d{2,3}(?:st|nd|rd|th)?\b", re.IGNORECASE)
            nav_terms = {
                "my bills",
                "browse bills",
                "bills and resolutions",
                "subject index",
                "bill information",
            }

            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                if not link_text or len(link_text) < 3:
                    continue
                
                lower_text = link_text.lower()
                lower_href = link_href.lower()
                if any(term in lower_text for term in nav_terms):
                    continue

                has_statute_pattern = bool(statute_number_re.search(link_text) or statute_number_re.search(link_href))
                has_chapter_pattern = bool(chapter_re.search(link_text) or chapter_re.search(link_href))
                has_session_pattern = ("special session" in lower_text) and bool(ga_re.search(link_text))
                has_legislative_doc_path = (
                    "archives/joint/publications" in lower_href
                    or "acts-and-resolutions" in lower_href
                    or "archives/" in lower_href and "specialsession" in lower_href
                )

                if not (has_statute_pattern or has_chapter_pattern or has_session_pattern or has_legislative_doc_path):
                    continue
                
                full_url = urljoin(code_url, link_href)

                section_number = self._extract_section_number(link_text)
                if not section_number:
                    # Derive a stable numeric identifier from URL/query text when possible.
                    href_match = statute_number_re.search(link_href) or ga_re.search(link_text)
                    if href_match:
                        section_number = href_match.group(0)

                if not section_number:
                    continue

                legal_area = self._identify_legal_area(link_text)
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=link_text[:200],
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=full_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
                section_count += 1
            
            self.logger.info(f"Tennessee custom scraper: Scraped {len(statutes)} sections")
            
        except Exception as e:
            self.logger.error(f"Tennessee custom scraper failed: {e}")
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("TN", TennesseeScraper)
