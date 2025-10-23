"""California state law scraper.

Scrapes laws from the California Legislative Information website
(https://leginfo.legislature.ca.gov/).
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class CaliforniaScraper(BaseStateScraper):
    """Scraper for California state laws."""
    
    def get_base_url(self) -> str:
        """Get base URL for California Legislative Information."""
        return "https://leginfo.legislature.ca.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of California codes.
        
        California has 29 codes organized by subject matter.
        """
        base_url = self.get_base_url()
        
        codes = [
            {"name": "Business and Professions Code", "url": f"{base_url}/faces/codes.xhtml", "type": "BPC"},
            {"name": "Civil Code", "url": f"{base_url}/faces/codes.xhtml", "type": "CIV"},
            {"name": "Code of Civil Procedure", "url": f"{base_url}/faces/codes.xhtml", "type": "CCP"},
            {"name": "Commercial Code", "url": f"{base_url}/faces/codes.xhtml", "type": "COM"},
            {"name": "Corporations Code", "url": f"{base_url}/faces/codes.xhtml", "type": "CORP"},
            {"name": "Education Code", "url": f"{base_url}/faces/codes.xhtml", "type": "EDC"},
            {"name": "Elections Code", "url": f"{base_url}/faces/codes.xhtml", "type": "ELEC"},
            {"name": "Evidence Code", "url": f"{base_url}/faces/codes.xhtml", "type": "EVID"},
            {"name": "Family Code", "url": f"{base_url}/faces/codes.xhtml", "type": "FAM"},
            {"name": "Financial Code", "url": f"{base_url}/faces/codes.xhtml", "type": "FIN"},
            {"name": "Fish and Game Code", "url": f"{base_url}/faces/codes.xhtml", "type": "FGC"},
            {"name": "Food and Agricultural Code", "url": f"{base_url}/faces/codes.xhtml", "type": "FAC"},
            {"name": "Government Code", "url": f"{base_url}/faces/codes.xhtml", "type": "GOV"},
            {"name": "Harbors and Navigation Code", "url": f"{base_url}/faces/codes.xhtml", "type": "HNC"},
            {"name": "Health and Safety Code", "url": f"{base_url}/faces/codes.xhtml", "type": "HSC"},
            {"name": "Insurance Code", "url": f"{base_url}/faces/codes.xhtml", "type": "INS"},
            {"name": "Labor Code", "url": f"{base_url}/faces/codes.xhtml", "type": "LAB"},
            {"name": "Military and Veterans Code", "url": f"{base_url}/faces/codes.xhtml", "type": "MVC"},
            {"name": "Penal Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PEN"},
            {"name": "Probate Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PROB"},
            {"name": "Public Contract Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PCC"},
            {"name": "Public Resources Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PRC"},
            {"name": "Public Utilities Code", "url": f"{base_url}/faces/codes.xhtml", "type": "PUC"},
            {"name": "Revenue and Taxation Code", "url": f"{base_url}/faces/codes.xhtml", "type": "RTC"},
            {"name": "Streets and Highways Code", "url": f"{base_url}/faces/codes.xhtml", "type": "SHC"},
            {"name": "Unemployment Insurance Code", "url": f"{base_url}/faces/codes.xhtml", "type": "UIC"},
            {"name": "Vehicle Code", "url": f"{base_url}/faces/codes.xhtml", "type": "VEH"},
            {"name": "Water Code", "url": f"{base_url}/faces/codes.xhtml", "type": "WAT"},
            {"name": "Welfare and Institutions Code", "url": f"{base_url}/faces/codes.xhtml", "type": "WIC"},
        ]
        
        return codes
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific California code.
        
        Args:
            code_name: Name of the code (e.g., "Penal Code")
            code_url: URL to the code
            
        Returns:
            List of normalized statutes
        """
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
            
            # Parse the page to find sections
            # California's leginfo website has a specific structure
            # This is a simplified version - full implementation would need more detailed parsing
            
            # Extract legal area from code name
            legal_area = self._identify_legal_area(code_name)
            
            # Find all section links (try multiple patterns)
            section_links = soup.find_all('a', href=re.compile(r'.*section.*', re.IGNORECASE))
            if not section_links:
                # Try finding any links that might be sections
                section_links = soup.find_all('a', href=True, limit=100)
            
            for i, link in enumerate(section_links[:100]):  # Limit for demo purposes
                section_text = link.get_text(strip=True)
                section_url = link.get('href', '')
                
                if not section_text or len(section_text) < 3:
                    continue
                
                if not section_url.startswith('http'):
                    from urllib.parse import urljoin
                    section_url = urljoin(code_url, section_url)
                
                # Extract section number
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
                    official_cite=f"Cal. {code_name} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes


# Register the scraper
StateScraperRegistry.register("CA", CaliforniaScraper)
