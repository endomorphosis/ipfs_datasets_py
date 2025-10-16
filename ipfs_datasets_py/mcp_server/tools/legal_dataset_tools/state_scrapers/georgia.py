"""Scraper for Georgia state laws.

This module contains the scraper for Georgia statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class GeorgiaScraper(BaseStateScraper):
    """Scraper for Georgia state laws from http://www.legis.ga.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Georgia's legislative website."""
        return "http://www.legis.ga.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Georgia."""
        return [{
            "name": "Official Code of Georgia",
            "url": f"{self.get_base_url()}/legislation/laws.html",
            "type": "Code"
        }]
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code from Georgia's legislative website.
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL of the code
            
        Returns:
            List of NormalizedStatute objects
        """
        return await self._custom_scrape_georgia(code_name, code_url, "Ga. Code Ann.")
    
    async def _custom_scrape_georgia(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Custom scraper for Georgia's legislative website."""
        try:
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(code_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            links = soup.find_all('a', href=True)
            
            section_count = 0
            for link in links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_href = link.get('href', '')
                
                if not link_text or len(link_text) < 5:
                    continue
                
                # Georgia Code patterns - relaxed matching
                keywords_ga = ['title', 'chapter', '§', 'section', 'part', 'code', 'statute', 'article', 'ga.']
                if not any(keyword in link_text.lower() for keyword in keywords_ga):
                    continue
                
                full_url = urljoin(code_url, link_href)
                section_number = self._extract_section_number(link_text) or f"Section-{section_count + 1}"
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
            
            self.logger.info(f"Georgia custom scraper: Scraped {len(statutes)} sections")
            
            # Fallback to generic scraper if no data found
            if not statutes:
                self.logger.info("Georgia custom scraper found no data, falling back to generic scraper")
                return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
            
        except Exception as e:
            self.logger.error(f"Georgia custom scraper failed: {e}")
            return await self._generic_scrape(code_name, code_url, citation_format, max_sections)
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("GA", GeorgiaScraper)
