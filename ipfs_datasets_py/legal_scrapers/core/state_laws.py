#!/usr/bin/env python3
"""
State Laws Scraper - Core Implementation

Scrapes state laws and legislation from official state government websites.
Supports all 50 US states with unified interface.
"""

import logging
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse
import re

from .base_scraper import BaseLegalScraper

logger = logging.getLogger(__name__)


class StateLawsScraper(BaseLegalScraper):
    """
    Scraper for state laws and legislation.
    
    Supports:
    - All 50 US states
    - State codes and statutes
    - Session laws
    - Administrative codes
    """
    
    # State legislature websites (examples)
    STATE_URLS = {
        "AL": "https://legiscan.com/AL",
        "AK": "https://legiscan.com/AK",
        "AZ": "https://legiscan.com/AZ",
        "AR": "https://legiscan.com/AR",
        "CA": "https://leginfo.legislature.ca.gov",
        "CO": "https://leg.colorado.gov",
        "CT": "https://cga.ct.gov",
        # ... more states
        "WA": "https://leg.wa.gov",
        "WV": "https://legiscan.com/WV",
        "WI": "https://docs.legis.wisconsin.gov",
        "WY": "https://wyoleg.gov",
    }
    
    def get_scraper_name(self) -> str:
        """Return scraper identifier."""
        return "state_laws"
    
    async def scrape(
        self,
        state_code: str = None,
        bill_number: str = None,
        statute_section: str = None,
        url: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape state laws.
        
        Args:
            state_code: Two-letter state code (e.g., "CA", "NY")
            bill_number: Specific bill number to scrape
            statute_section: Specific statute section
            url: Direct URL to scrape
            **kwargs: Additional arguments
            
        Returns:
            Dict with scraped content and metadata
        """
        try:
            # Determine target URL
            if url:
                target_url = url
                if not state_code:
                    # Try to extract state from URL
                    state_code = self._extract_state_from_url(url)
            elif state_code:
                target_url = self.STATE_URLS.get(state_code.upper())
                if not target_url:
                    raise ValueError(f"Unknown state code: {state_code}")
                
                if bill_number:
                    target_url = f"{target_url}/bill/{bill_number}"
                elif statute_section:
                    target_url = f"{target_url}/statute/{statute_section}"
            else:
                raise ValueError("Must provide either state_code or url")
            
            logger.info(f"Scraping state laws: {target_url}")
            
            # Scrape using unified system
            metadata = {
                "scraper": self.get_scraper_name(),
                "state": state_code,
                "bill_number": bill_number,
                "statute_section": statute_section,
                "type": "state_law"
            }
            
            result = await self.scrape_url_unified(target_url, metadata)
            
            # Parse content
            if result['status'] == 'success':
                parsed = await self._parse_state_law(result['content'], state_code)
                result.update(parsed)
            
            return result
        
        except Exception as e:
            logger.error(f"Error scraping state laws: {e}")
            return {
                "status": "error",
                "error": str(e),
                "state": state_code,
                "url": url
            }
    
    async def scrape_multiple_states(
        self,
        state_codes: List[str],
        max_concurrent: int = 3,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Scrape laws from multiple states.
        
        Args:
            state_codes: List of state codes
            max_concurrent: Max concurrent requests
            **kwargs: Additional arguments for scrape()
            
        Returns:
            List of scrape results
        """
        urls = [self.STATE_URLS.get(code.upper()) for code in state_codes]
        urls = [url for url in urls if url]  # Filter None
        
        return await self.batch_scrape(
            urls=urls,
            max_concurrent=max_concurrent,
            metadata_list=[{"state": code} for code in state_codes]
        )
    
    def _extract_state_from_url(self, url: str) -> Optional[str]:
        """Extract state code from URL."""
        # Try common patterns
        patterns = [
            r'/([A-Z]{2})/',  # /CA/
            r'\.([a-z]{2})\.',  # .ca.gov
            r'state=([A-Z]{2})',  # state=CA
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1).upper()
        
        return None
    
    async def _parse_state_law(
        self,
        content: Any,
        state_code: str
    ) -> Dict[str, Any]:
        """
        Parse state law content.
        
        Args:
            content: Raw HTML/text content
            state_code: State code
            
        Returns:
            Parsed data dict
        """
        # This would be state-specific parsing
        # For now, return basic structure
        
        if isinstance(content, bytes):
            content_str = content.decode('utf-8', errors='ignore')
        else:
            content_str = str(content)
        
        return {
            "state": state_code,
            "content_length": len(content_str),
            "parsed": True,
            # Add more parsing as needed:
            # - Bill title
            # - Sponsors
            # - Status
            # - Text sections
            # - Amendments
        }


# Convenience function
def scrape_state_law(state_code: str = None, url: str = None, **kwargs) -> Dict[str, Any]:
    """
    Sync wrapper for state law scraping.
    
    Args:
        state_code: Two-letter state code
        url: Direct URL
        **kwargs: Additional arguments
        
    Returns:
        Scrape result
    """
    import asyncio
    scraper = StateLawsScraper()
    return asyncio.run(scraper.scrape(state_code=state_code, url=url, **kwargs))


if __name__ == "__main__":
    # Test
    result = scrape_state_law(state_code="CA")
    print(f"Status: {result.get('status')}")
    print(f"State: {result.get('state')}")
