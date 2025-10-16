"""Base scraper class and normalized schema for state law scrapers.

This module provides:
1. A normalized schema for state laws across all states
2. A base scraper class that all state-specific scrapers inherit from
3. Common utilities for parsing and normalizing state law data
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


@dataclass
class StatuteMetadata:
    """Metadata for a statute."""
    effective_date: Optional[str] = None
    last_amended: Optional[str] = None
    enacted_year: Optional[str] = None
    repealed: bool = False
    superseded_by: Optional[str] = None
    legislative_session: Optional[str] = None
    bill_number: Optional[str] = None
    history: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class NormalizedStatute:
    """Normalized representation of a state statute.
    
    This schema is consistent across all states, allowing for easy
    comparison and analysis of laws from different jurisdictions.
    """
    # Identification
    state_code: str  # e.g., "CA", "NY"
    state_name: str  # e.g., "California", "New York"
    statute_id: str  # Unique identifier within the state (e.g., "Penal Code § 187")
    
    # Hierarchy (for organizing statutes)
    code_name: Optional[str] = None  # e.g., "Penal Code", "Vehicle Code"
    title_number: Optional[str] = None  # Title or Part number
    title_name: Optional[str] = None  # Title or Part name
    chapter_number: Optional[str] = None
    chapter_name: Optional[str] = None
    section_number: Optional[str] = None
    section_name: Optional[str] = None
    
    # Content
    short_title: Optional[str] = None
    full_text: Optional[str] = None  # The actual text of the statute
    summary: Optional[str] = None
    
    # Classification
    legal_area: Optional[str] = None  # e.g., "criminal", "civil", "family"
    topics: List[str] = field(default_factory=list)  # e.g., ["murder", "homicide"]
    keywords: List[str] = field(default_factory=list)
    
    # Source information
    source_url: str = ""  # URL to official source
    official_cite: Optional[str] = None  # Official citation format
    
    # Metadata
    metadata: Optional[StatuteMetadata] = None
    
    # Scraping metadata
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())
    scraper_version: str = "1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.metadata:
            data['metadata'] = self.metadata.to_dict()
        return data
    
    def get_citation(self) -> str:
        """Get a standardized citation for this statute."""
        parts = []
        if self.state_code:
            parts.append(self.state_code)
        if self.code_name:
            parts.append(self.code_name)
        if self.section_number:
            parts.append(f"§ {self.section_number}")
        return " ".join(parts) if parts else self.statute_id


class BaseStateScraper(ABC):
    """Base class for state-specific law scrapers.
    
    Each state scraper inherits from this class and implements
    state-specific parsing logic while outputting normalized data.
    """
    
    def __init__(self, state_code: str, state_name: str):
        """Initialize the scraper.
        
        Args:
            state_code: Two-letter state code (e.g., "CA")
            state_name: Full state name (e.g., "California")
        """
        self.state_code = state_code
        self.state_name = state_name
        self.logger = logging.getLogger(f"{__name__}.{state_code}")
    
    @abstractmethod
    def get_base_url(self) -> str:
        """Get the base URL for the state's legislative website.
        
        Returns:
            Base URL string
        """
        pass
    
    @abstractmethod
    def get_code_list(self) -> List[Dict[str, str]]:
        """Get list of available codes/titles for this state.
        
        Returns:
            List of dicts with 'name', 'url', and optionally 'code_type' keys
        """
        pass
    
    @abstractmethod
    async def scrape_code(self, code_name: str, code_url: str) -> List[NormalizedStatute]:
        """Scrape a specific code (e.g., Penal Code, Vehicle Code).
        
        Args:
            code_name: Name of the code to scrape
            code_url: URL to the code
            
        Returns:
            List of NormalizedStatute objects
        """
        pass
    
    async def scrape_all(
        self,
        legal_areas: Optional[List[str]] = None,
        max_statutes: Optional[int] = None,
        rate_limit_delay: float = 2.0
    ) -> List[NormalizedStatute]:
        """Scrape all available codes for this state.
        
        Args:
            legal_areas: Filter by legal areas
            max_statutes: Maximum number of statutes to scrape
            rate_limit_delay: Delay between requests in seconds
            
        Returns:
            List of NormalizedStatute objects
        """
        import time
        
        all_statutes = []
        codes = self.get_code_list()
        
        self.logger.info(f"Scraping {len(codes)} codes for {self.state_name}")
        
        for code_info in codes:
            if max_statutes and len(all_statutes) >= max_statutes:
                break
            
            code_name = code_info['name']
            code_url = code_info['url']
            
            # Filter by legal area if specified
            if legal_areas:
                code_area = self._identify_legal_area(code_name)
                if code_area not in legal_areas:
                    continue
            
            try:
                self.logger.info(f"Scraping {code_name}...")
                statutes = await self.scrape_code(code_name, code_url)
                
                if max_statutes:
                    remaining = max_statutes - len(all_statutes)
                    statutes = statutes[:remaining]
                
                all_statutes.extend(statutes)
                self.logger.info(f"Scraped {len(statutes)} statutes from {code_name}")
                
            except Exception as e:
                self.logger.error(f"Failed to scrape {code_name}: {e}")
            
            # Rate limiting
            time.sleep(rate_limit_delay)
        
        return all_statutes
    
    def _identify_legal_area(self, text: str) -> str:
        """Identify legal area from text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Legal area string
        """
        text_lower = text.lower()
        
        area_keywords = {
            "criminal": ["criminal", "penal", "crime", "felony", "misdemeanor"],
            "civil": ["civil", "tort", "liability", "damages"],
            "family": ["family", "marriage", "divorce", "custody", "child"],
            "employment": ["employment", "labor", "worker", "wage"],
            "environmental": ["environmental", "pollution", "conservation"],
            "business": ["business", "corporation", "commercial", "contract"],
            "property": ["property", "real estate", "land"],
            "tax": ["tax", "revenue", "assessment"],
            "health": ["health", "medical", "healthcare"],
            "education": ["education", "school"],
            "traffic": ["traffic", "vehicle", "motor", "driving"],
            "probate": ["probate", "estate", "will", "trust"],
        }
        
        for area, keywords in area_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                return area
        
        return "general"
    
    def _extract_section_number(self, text: str) -> Optional[str]:
        """Extract section number from text.
        
        Args:
            text: Text containing section reference
            
        Returns:
            Section number or None
        """
        import re
        
        # Common patterns: "Section 123", "§ 123", "§123", "Sec. 123"
        patterns = [
            r'§\s*(\d+[\.\-\w]*)',
            r'Section\s+(\d+[\.\-\w]*)',
            r'Sec\.\s*(\d+[\.\-\w]*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    async def _generic_scrape(
        self,
        code_name: str,
        code_url: str,
        citation_format: str,
        max_sections: int = 100
    ) -> List[NormalizedStatute]:
        """Generic scraper implementation that can be used by most states.
        
        This method provides a common scraping pattern that works for many
        state legislative websites. Individual scrapers can override scrape_code()
        for more sophisticated parsing.
        
        Args:
            code_name: Name of the code (e.g., "Penal Code")
            code_url: URL to scrape
            citation_format: Citation format (e.g., "Cal. Penal Code")
            max_sections: Maximum number of sections to scrape
            
        Returns:
            List of NormalizedStatute objects
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
            
            # Extract legal area from code name
            legal_area = self._identify_legal_area(code_name)
            
            # Try to find section links (common patterns across many state websites)
            section_links = soup.find_all('a', href=True, limit=max_sections)
            
            section_count = 0
            for link in section_links:
                if section_count >= max_sections:
                    break
                
                link_text = link.get_text(strip=True)
                link_url = link.get('href', '')
                
                # Skip if link doesn't look like a section reference
                if not link_text or len(link_text) < 3:
                    continue
                
                # Make URL absolute if needed
                if link_url.startswith('/'):
                    from urllib.parse import urljoin
                    link_url = urljoin(code_url, link_url)
                elif not link_url.startswith('http'):
                    continue
                
                # Extract section number
                section_number = self._extract_section_number(link_text)
                if not section_number:
                    section_number = f"Section-{section_count + 1}"
                
                # Create normalized statute
                statute = NormalizedStatute(
                    state_code=self.state_code,
                    state_name=self.state_name,
                    statute_id=f"{code_name} § {section_number}",
                    code_name=code_name,
                    section_number=section_number,
                    section_name=link_text[:200],  # Limit length
                    full_text=f"Section {section_number}: {link_text}",
                    legal_area=legal_area,
                    source_url=link_url,
                    official_cite=f"{citation_format} § {section_number}",
                    metadata=StatuteMetadata()
                )
                
                statutes.append(statute)
                section_count += 1
            
            self.logger.info(f"Scraped {len(statutes)} sections from {code_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to scrape {code_name}: {e}")
        
        return statutes
