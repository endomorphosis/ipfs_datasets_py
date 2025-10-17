"""Scraper for Missouri state laws.

This module contains the scraper for Missouri statutes from the official state legislative website.
"""

from typing import List, Dict
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class MissouriScraper(BaseStateScraper):
    """Scraper for Missouri state laws from http://www.moga.mo.gov"""
    
    def get_base_url(self) -> str:
        """Return the base URL for Missouri's legislative website."""
        return "http://www.moga.mo.gov"
    
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
        
        Missouri's site often has connectivity issues.
        This scraper tries multiple approaches:
        1. Direct connection with extended timeout
        2. HTTPS upgrade attempt
        3. Internet Archive fallback
        4. Alternative .gov domain attempts
        """
        try:
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        # Try alternative URLs if main URL fails
        alternative_urls = [
            code_url,
            code_url.replace('http://', 'https://'),
            "https://revisor.mo.gov/main/Home.aspx",
            f"http://web.archive.org/web/*/{code_url.replace('http://', '')}"
        ]
        
        for attempt_url in alternative_urls:
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                self.logger.info(f"Missouri: Trying URL: {attempt_url}")
                # Extended timeout and retry logic for slow Missouri servers
                response = requests.get(attempt_url, headers=headers, timeout=60, allow_redirects=True)
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
                    
                    # Missouri RSMo patterns - relaxed matching
                    keywords_mo = ['chapter', 'rsmo', '§', 'section', 'title', 'part', 'code', 'statute', 'mo.']
                    if not any(keyword in link_text.lower() for keyword in keywords_mo):
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
                
                self.logger.info(f"Missouri custom scraper: Scraped {len(statutes)} sections from {attempt_url}")
                
                # If we got results, break out of the alternative URL loop
                if statutes:
                    break
                    
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                self.logger.warning(f"Missouri: Connection issue with {attempt_url}: {e}")
                continue
            except requests.exceptions.HTTPError as e:
                self.logger.warning(f"Missouri: HTTP error with {attempt_url}: {e}")
                continue
            except Exception as e:
                self.logger.warning(f"Missouri: Error with {attempt_url}: {e}")
                continue
        
        # Fallback to generic scraper if no data found after all attempts
        if not statutes:
            self.logger.warning("Missouri custom scraper found no data after trying all URLs")
            self.logger.info("For Missouri, the site may be temporarily down. Try:")
            self.logger.info("  1. Internet Archive: web.archive.org")
            self.logger.info("  2. Alternative site: revisor.mo.gov")
            self.logger.info("  3. Wait and retry later")
            return []
        
        return statutes


# Register this scraper with the registry
StateScraperRegistry.register("MO", MissouriScraper)
