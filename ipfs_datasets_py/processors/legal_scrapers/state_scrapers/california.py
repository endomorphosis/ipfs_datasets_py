"""California state law scraper.

Scrapes laws from the California Legislative Information website
(https://leginfo.legislature.ca.gov/).
"""

from typing import List, Dict, Optional
import re
from urllib.parse import urljoin, urlparse, parse_qs
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata
from .registry import StateScraperRegistry


class CaliforniaScraper(BaseStateScraper):
    """Scraper for California state laws."""

    CODE_TYPE_MAP = {
        "Business and Professions Code": "BPC",
        "Civil Code": "CIV",
        "Code of Civil Procedure": "CCP",
        "Commercial Code": "COM",
        "Corporations Code": "CORP",
        "Education Code": "EDC",
        "Elections Code": "ELEC",
        "Evidence Code": "EVID",
        "Family Code": "FAM",
        "Financial Code": "FIN",
        "Fish and Game Code": "FGC",
        "Food and Agricultural Code": "FAC",
        "Government Code": "GOV",
        "Harbors and Navigation Code": "HNC",
        "Health and Safety Code": "HSC",
        "Insurance Code": "INS",
        "Labor Code": "LAB",
        "Military and Veterans Code": "MVC",
        "Penal Code": "PEN",
        "Probate Code": "PROB",
        "Public Contract Code": "PCC",
        "Public Resources Code": "PRC",
        "Public Utilities Code": "PUC",
        "Revenue and Taxation Code": "RTC",
        "Streets and Highways Code": "SHC",
        "Unemployment Insurance Code": "UIC",
        "Vehicle Code": "VEH",
        "Water Code": "WAT",
        "Welfare and Institutions Code": "WIC",
    }
    
    def get_base_url(self) -> str:
        """Get base URL for California Legislative Information."""
        return "https://leginfo.legislature.ca.gov"
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of California codes.
        
        California has 29 codes organized by subject matter.
        """
        base_url = self.get_base_url()
        
        codes = [
            {"name": "Business and Professions Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=BPC", "type": "BPC"},
            {"name": "Civil Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=CIV", "type": "CIV"},
            {"name": "Code of Civil Procedure", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=CCP", "type": "CCP"},
            {"name": "Commercial Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=COM", "type": "COM"},
            {"name": "Corporations Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=CORP", "type": "CORP"},
            {"name": "Education Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=EDC", "type": "EDC"},
            {"name": "Elections Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=ELEC", "type": "ELEC"},
            {"name": "Evidence Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=EVID", "type": "EVID"},
            {"name": "Family Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FAM", "type": "FAM"},
            {"name": "Financial Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FIN", "type": "FIN"},
            {"name": "Fish and Game Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FGC", "type": "FGC"},
            {"name": "Food and Agricultural Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=FAC", "type": "FAC"},
            {"name": "Government Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=GOV", "type": "GOV"},
            {"name": "Harbors and Navigation Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=HNC", "type": "HNC"},
            {"name": "Health and Safety Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=HSC", "type": "HSC"},
            {"name": "Insurance Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=INS", "type": "INS"},
            {"name": "Labor Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=LAB", "type": "LAB"},
            {"name": "Military and Veterans Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=MVC", "type": "MVC"},
            {"name": "Penal Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PEN", "type": "PEN"},
            {"name": "Probate Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PROB", "type": "PROB"},
            {"name": "Public Contract Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PCC", "type": "PCC"},
            {"name": "Public Resources Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PRC", "type": "PRC"},
            {"name": "Public Utilities Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=PUC", "type": "PUC"},
            {"name": "Revenue and Taxation Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=RTC", "type": "RTC"},
            {"name": "Streets and Highways Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=SHC", "type": "SHC"},
            {"name": "Unemployment Insurance Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=UIC", "type": "UIC"},
            {"name": "Vehicle Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=VEH", "type": "VEH"},
            {"name": "Water Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=WAT", "type": "WAT"},
            {"name": "Welfare and Institutions Code", "url": f"{base_url}/faces/codedisplayexpand.xhtml?tocCode=WIC", "type": "WIC"},
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
            from bs4 import BeautifulSoup
        except ImportError as e:
            self.logger.error(f"Required library not available: {e}")
            return []
        
        statutes = []
        code_type = self.CODE_TYPE_MAP.get(code_name)
        if not code_type:
            self.logger.warning(f"No code type mapping for {code_name}")
            return statutes
        
        try:
            page_bytes = await self._fetch_page_content_with_archival_fallback(
                code_url,
                timeout_seconds=30,
            )
            if not page_bytes:
                return []

            soup = BeautifulSoup(page_bytes, 'html.parser')
            
            # Parse the page to find sections
            # California's leginfo website has a specific structure
            # This is a simplified version - full implementation would need more detailed parsing
            
            # Extract legal area from code name
            legal_area = self._identify_legal_area(code_name)
            
            section_links = soup.find_all('a', href=True)
            seen_sections = set()

            for link in section_links:
                section_text = link.get_text(strip=True)
                section_url = link.get('href', '')

                if not section_url:
                    continue

                if not section_url.startswith('http'):
                    section_url = urljoin(code_url, section_url)

                parsed = urlparse(section_url)
                if "codes_displayText.xhtml" not in parsed.path:
                    continue

                query = parse_qs(parsed.query)
                law_codes = query.get("lawCode") or query.get("lawcode") or []
                if not law_codes or law_codes[0].upper() != code_type:
                    continue

                if not section_text or not re.search(r"\d", section_text):
                    continue

                section_number = self._extract_section_number(section_text)
                if not section_number:
                    continue
                if section_number in seen_sections:
                    continue
                seen_sections.add(section_number)

                section_name = section_text[:200]
                if section_number not in section_name:
                    section_name = f"Section {section_number}: {section_name}"[:200]
                
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=section_name,
                    full_text=f"Section {section_number}: {section_text}",
                    source_url=section_url,
                    legal_area=legal_area,
                    official_cite=f"Cal. {code_name} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)

                if len(statutes) >= 250:
                    break
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes


# Register the scraper
StateScraperRegistry.register("CA", CaliforniaScraper)
