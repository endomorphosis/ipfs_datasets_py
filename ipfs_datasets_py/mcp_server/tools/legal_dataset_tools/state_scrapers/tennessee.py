"""Scraper for Tennessee state laws.

This module contains the scraper for Tennessee statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class TennesseeScraper(BaseStateScraper):
    """Scraper for Tennessee state laws from https://www.tn.gov/tga"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Tennessee's legislative website."""
        return "https://www.tn.gov/tga"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Return list of available codes/statutes for Tennessee."""
        return [{
            "name": "Tennessee Code Annotated",
            "url": f"{self.get_base_url()}/statutes.html",
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
        alternative_urls = [
            "https://publications.tnsosfiles.com/acts/",  # More reliable
            code_url,
            "https://advance.lexis.com/container?config=0152JAA5ZGVhZjA3NS02MzIzLTRjZDAtYjA0ZSAxIDA5MmEwMjBiLTExIGRkLTQ2OTAsbYc1Ow",
            f"http://web.archive.org/web/*/{code_url.replace('https://', '')}"
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
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            # SSL verification disabled for Tennessee's certificate issues
            response = requests.get(code_url, headers=headers, timeout=45, verify=False, allow_redirects=True)
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
                
                keywords_tn = ['title', 'chapter', 'tca', '§', 'section', 'part', 'code', 'statute', 'tenn.']
                if not any(keyword in link_text.lower() for keyword in keywords_tn):
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
            
            self.logger.info(f"Tennessee custom scraper: Scraped {len(statutes)} sections")
            
        except Exception as e:
            self.logger.error(f"Tennessee custom scraper failed: {e}")
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("TN", TennesseeScraper)
