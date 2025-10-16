"""New York state law scraper.

Scrapes laws from the New York State Senate website
(https://www.nysenate.gov/).
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class NewYorkScraper(BaseStateScraper):
    """Scraper for New York state laws."""
    
    def get_base_url(self) -> str:
        """Get base URL for NY Senate."""
        return "https://www.nysenate.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of New York consolidated laws.
        
        New York has numerous consolidated laws.
        """
        base_url = self.get_base_url()
        
        codes = [
            {"name": "Abandoned Property Law", "url": f"{base_url}/legislation/laws/ABP", "type": "ABP"},
            {"name": "Banking Law", "url": f"{base_url}/legislation/laws/BNK", "type": "BNK"},
            {"name": "Business Corporation Law", "url": f"{base_url}/legislation/laws/BSC", "type": "BSC"},
            {"name": "Civil Practice Law and Rules", "url": f"{base_url}/legislation/laws/CVP", "type": "CVP"},
            {"name": "Civil Rights Law", "url": f"{base_url}/legislation/laws/CVR", "type": "CVR"},
            {"name": "Criminal Procedure Law", "url": f"{base_url}/legislation/laws/CPL", "type": "CPL"},
            {"name": "Domestic Relations Law", "url": f"{base_url}/legislation/laws/DOM", "type": "DOM"},
            {"name": "Education Law", "url": f"{base_url}/legislation/laws/EDN", "type": "EDN"},
            {"name": "Election Law", "url": f"{base_url}/legislation/laws/ELN", "type": "ELN"},
            {"name": "Environmental Conservation Law", "url": f"{base_url}/legislation/laws/ENV", "type": "ENV"},
            {"name": "Executive Law", "url": f"{base_url}/legislation/laws/EXC", "type": "EXC"},
            {"name": "Family Court Act", "url": f"{base_url}/legislation/laws/FCA", "type": "FCA"},
            {"name": "General Business Law", "url": f"{base_url}/legislation/laws/GBS", "type": "GBS"},
            {"name": "General Obligations Law", "url": f"{base_url}/legislation/laws/GOB", "type": "GOB"},
            {"name": "Insurance Law", "url": f"{base_url}/legislation/laws/ISC", "type": "ISC"},
            {"name": "Judiciary Law", "url": f"{base_url}/legislation/laws/JUD", "type": "JUD"},
            {"name": "Labor Law", "url": f"{base_url}/legislation/laws/LAB", "type": "LAB"},
            {"name": "Penal Law", "url": f"{base_url}/legislation/laws/PEN", "type": "PEN"},
            {"name": "Public Health Law", "url": f"{base_url}/legislation/laws/PBH", "type": "PBH"},
            {"name": "Real Property Law", "url": f"{base_url}/legislation/laws/RPP", "type": "RPP"},
            {"name": "Tax Law", "url": f"{base_url}/legislation/laws/TAX", "type": "TAX"},
            {"name": "Vehicle and Traffic Law", "url": f"{base_url}/legislation/laws/VAT", "type": "VAT"},
            {"name": "Workers' Compensation Law", "url": f"{base_url}/legislation/laws/WKC", "type": "WKC"},
        ]
        
        return codes
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific New York law.
        
        Args:
            code_name: Name of the law
            code_url: URL to the law
            
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
            
            # Parse NY Senate's structure
            # The actual implementation would need detailed parsing of their specific HTML structure
            
            # Find section/article links
            section_links = soup.find_all('a', href=re.compile(r'.*/legislation/laws/.*', re.IGNORECASE))
            
            for link in section_links[:100]:  # Limit for demo
                section_text = link.get_text(strip=True)
                section_url = link.get('href', '')
                
                if not section_url.startswith('http'):
                    section_url = f"{self.get_base_url()}{section_url}"
                
                # Extract section number
                section_number = self._extract_section_number(section_text)
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}" if section_number else section_text,
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_text,
                    source_url=section_url,
                    legal_area=self._identify_legal_area(code_name),
                    official_cite=f"NY {code_name} § {section_number}" if section_number else None,
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes


# Register the scraper
StateScraperRegistry.register("NY", NewYorkScraper)
