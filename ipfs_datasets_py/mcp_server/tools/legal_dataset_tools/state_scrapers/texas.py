"""Texas state law scraper.

Scrapes laws from the Texas Legislature Online website
(https://statutes.capitol.texas.gov/).
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class TexasScraper(BaseStateScraper):
    """Scraper for Texas state laws."""
    
    def get_base_url(self) -> str:
        """Get base URL for Texas statutes."""
        return "https://statutes.capitol.texas.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of Texas codes.
        
        Texas organizes its laws into codes.
        """
        base_url = self.get_base_url()
        
        codes = [
            {"name": "Agriculture Code", "url": f"{base_url}/Docs/AG/htm/AG.1.htm", "type": "AG"},
            {"name": "Alcoholic Beverage Code", "url": f"{base_url}/Docs/AL/htm/AL.1.htm", "type": "AL"},
            {"name": "Business and Commerce Code", "url": f"{base_url}/Docs/BC/htm/BC.1.htm", "type": "BC"},
            {"name": "Civil Practice and Remedies Code", "url": f"{base_url}/Docs/CP/htm/CP.1.htm", "type": "CP"},
            {"name": "Code of Criminal Procedure", "url": f"{base_url}/Docs/CR/htm/CR.1.htm", "type": "CR"},
            {"name": "Education Code", "url": f"{base_url}/Docs/ED/htm/ED.1.htm", "type": "ED"},
            {"name": "Election Code", "url": f"{base_url}/Docs/EL/htm/EL.1.htm", "type": "EL"},
            {"name": "Family Code", "url": f"{base_url}/Docs/FA/htm/FA.1.htm", "type": "FA"},
            {"name": "Finance Code", "url": f"{base_url}/Docs/FI/htm/FI.1.htm", "type": "FI"},
            {"name": "Government Code", "url": f"{base_url}/Docs/GV/htm/GV.1.htm", "type": "GV"},
            {"name": "Health and Safety Code", "url": f"{base_url}/Docs/HS/htm/HS.1.htm", "type": "HS"},
            {"name": "Human Resources Code", "url": f"{base_url}/Docs/HR/htm/HR.1.htm", "type": "HR"},
            {"name": "Insurance Code", "url": f"{base_url}/Docs/IN/htm/IN.1.htm", "type": "IN"},
            {"name": "Labor Code", "url": f"{base_url}/Docs/LA/htm/LA.1.htm", "type": "LA"},
            {"name": "Local Government Code", "url": f"{base_url}/Docs/LG/htm/LG.1.htm", "type": "LG"},
            {"name": "Natural Resources Code", "url": f"{base_url}/Docs/NR/htm/NR.1.htm", "type": "NR"},
            {"name": "Occupations Code", "url": f"{base_url}/Docs/OC/htm/OC.1.htm", "type": "OC"},
            {"name": "Parks and Wildlife Code", "url": f"{base_url}/Docs/PW/htm/PW.1.htm", "type": "PW"},
            {"name": "Penal Code", "url": f"{base_url}/Docs/PE/htm/PE.1.htm", "type": "PE"},
            {"name": "Property Code", "url": f"{base_url}/Docs/PR/htm/PR.1.htm", "type": "PR"},
            {"name": "Tax Code", "url": f"{base_url}/Docs/TX/htm/TX.1.htm", "type": "TX"},
            {"name": "Transportation Code", "url": f"{base_url}/Docs/TN/htm/TN.1.htm", "type": "TN"},
            {"name": "Utilities Code", "url": f"{base_url}/Docs/UT/htm/UT.1.htm", "type": "UT"},
            {"name": "Water Code", "url": f"{base_url}/Docs/WA/htm/WA.1.htm", "type": "WA"},
        ]
        
        return codes
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific Texas code.
        
        Args:
            code_name: Name of the code
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
            
            # Parse Texas Legislature's structure
            # Texas uses a specific HTML structure for their statutes
            
            # Extract legal area
            legal_area = self._identify_legal_area(code_name)
            
            # Find section links
            section_links = soup.find_all('a', href=re.compile(r'.*\.htm', re.IGNORECASE))
            if not section_links:
                # Try finding any links
                section_links = soup.find_all('a', href=True, limit=100)
            
            for i, link in enumerate(section_links[:100]):  # Limit for demo
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
                    official_cite=f"Tex. {code_name} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes


# Register the scraper
StateScraperRegistry.register("TX", TexasScraper)
