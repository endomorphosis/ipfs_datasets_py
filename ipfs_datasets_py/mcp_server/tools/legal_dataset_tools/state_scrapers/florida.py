"""Florida state law scraper.

Scrapes laws from the Florida Legislature website
(http://www.leg.state.fl.us/).
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class FloridaScraper(BaseStateScraper):
    """Scraper for Florida state laws."""
    
    def get_base_url(self) -> str:
        """Get base URL for Florida statutes."""
        return "http://www.leg.state.fl.us"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of Florida statutes."""
        base_url = self.get_base_url()
        
        codes = [
            {"name": "Florida Statutes", "url": f"{base_url}/Statutes/", "type": "FS"},
        ]
        
        return codes
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape Florida statutes."""
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(code_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Parse Florida's structure
            legal_area = self._identify_legal_area(code_name)
            
            section_links = soup.find_all('a', href=re.compile(r'.*statutes.*', re.IGNORECASE))
            if not section_links:
                section_links = soup.find_all('a', href=True, limit=100)
            
            for i, link in enumerate(section_links[:100]):
                section_text = link.get_text(strip=True)
                section_url = link.get('href', '')
                
                if not section_text or len(section_text) < 3:
                    continue
                
                if not section_url.startswith('http'):
                    from urllib.parse import urljoin
                    section_url = urljoin(code_url, section_url)
                
                section_number = self._extract_section_number(section_text)
                if not section_number:
                    section_number = f"{i+1}"
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_text[:200],
                    full_text=f"Section {section_number}: {section_text}",  # Added full_text
                    source_url=section_url,
                    legal_area=legal_area,
                    official_cite=f"Fla. Stat. § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes


# Register the scraper
StateScraperRegistry.register("FL", FloridaScraper)
