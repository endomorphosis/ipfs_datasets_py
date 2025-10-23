"""Generic state law scraper.

This scraper can be used for states that don't have a specific
implementation yet. It uses a combination of strategies to scrape
state laws from various sources.
"""

from typing import List, Dict, Optional
import re
from .base_scraper import BaseStateScraper, NormalizedStatute, StatuteMetadata


class GenericStateScraper(BaseStateScraper):
    """Generic scraper that works with multiple state law sources."""
    
    def __init__(self, state_code: str, state_name: str):
        """Initialize generic scraper.
        
        Args:
            state_code: Two-letter state code
            state_name: Full state name
        """
        super().__init__(state_code, state_name)
        self.sources = self._get_available_sources()
    
    def _get_available_sources(self) -> List[Dict[str, str]]:
        """Get available sources for this state.
        
        Returns:
            List of source URLs
        """
        state_lower = self.state_code.lower()
        
        sources = [
            {
                "name": "Justia",
                "base_url": f"https://law.justia.com/codes/{state_lower}/",
                "priority": 3
            },
            {
                "name": "FindLaw",
                "base_url": f"https://codes.findlaw.com/{state_lower}/",
                "priority": 2
            },
            {
                "name": "Official State Website",
                "base_url": f"https://legislature.{state_lower}.gov/",
                "priority": 1
            }
        ]
        
        # Sort by priority (1 = highest)
        sources.sort(key=lambda x: x['priority'])
        
        return sources
    
    def get_base_url(self) -> str:
        """Get base URL for this state."""
        if self.sources:
            return self.sources[0]['base_url']
        return ""
    
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of codes for this state.
        
        This is a generic implementation that tries to discover
        codes from the available sources.
        """
        codes = []
        
        try:
            import requests
            from bs4 import BeautifulSoup
            
            for source in self.sources:
                try:
                    url = source['base_url']
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                    
                    response = requests.get(url, headers=headers, timeout=30)
                    response.raise_for_status()
                    
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Look for code/title links
                    for link in soup.find_all('a', href=True):
                        text = link.get_text(strip=True)
                        href = link.get('href', '')
                        
                        # Filter for likely code links
                        if any(keyword in text.lower() for keyword in ['code', 'title', 'chapter', 'statute']):
                            if len(text) > 5 and len(text) < 100:
                                codes.append({
                                    "name": text,
                                    "url": href if href.startswith('http') else f"{url}{href}",
                                    "source": source['name']
                                })
                    
                    # If we found codes, stop trying other sources
                    if codes:
                        self.logger.info(f"Found {len(codes)} codes from {source['name']}")
                        break
                        
                except Exception as e:
                    self.logger.warning(f"Failed to get codes from {source['name']}: {e}")
                    continue
            
        except ImportError:
            self.logger.error("Required libraries not available")
        
        return codes[:50]  # Limit to 50 codes
    
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code using generic parsing.
        
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
            
            # Generic parsing - look for section-like structures
            section_patterns = [
                re.compile(r'section[s]?', re.IGNORECASE),
                re.compile(r'§', re.IGNORECASE),
                re.compile(r'\d+-\d+', re.IGNORECASE),
            ]
            
            links = soup.find_all('a', href=True)
            
            for link in links[:100]:  # Limit for performance
                text = link.get_text(strip=True)
                href = link.get('href', '')
                
                # Check if this looks like a section link
                is_section = any(pattern.search(text) for pattern in section_patterns)
                
                if is_section and len(text) > 3:
                    section_url = href if href.startswith('http') else f"{code_url.rsplit('/', 1)[0]}/{href}"
                    section_number = self._extract_section_number(text)
                    
                    statute = NormalizedStatute(
                        state_code=self.state_code,
                        state_name=self.state_name,
                        statute_id=f"{code_name} § {section_number}" if section_number else text,
                        code_name=code_name,
                        section_number=section_number,
                        section_name=text,
                        source_url=section_url,
                        legal_area=self._identify_legal_area(code_name),
                        official_cite=f"{self.state_code} {code_name} § {section_number}" if section_number else None,
                        metadata=StatuteMetadata()
                    )
                    
                    statutes.append(statute)
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes
