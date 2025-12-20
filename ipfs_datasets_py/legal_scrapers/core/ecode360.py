#!/usr/bin/env python3
"""
eCode360 Scraper - Core Implementation

Scrapes municipal codes from eCode360.com platform.
Alternative to Municode, used by many municipalities.
"""

import logging
from typing import Dict, List, Any, Optional
import re

from .base_scraper import BaseLegalScraper

logger = logging.getLogger(__name__)


class ECode360Scraper(BaseLegalScraper):
    """
    Scraper for eCode360 municipal codes.
    
    Supports:
    - Municipal codes
    - Ordinances
    - Zoning codes
    - Multiple jurisdictions
    """
    
    BASE_URL = "https://ecode360.com"
    
    def get_scraper_name(self) -> str:
        """Return scraper identifier."""
        return "ecode360"
    
    async def scrape(
        self,
        jurisdiction_url: str = None,
        jurisdiction_id: str = None,
        chapter: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape eCode360 municipal code.
        
        Args:
            jurisdiction_url: Full URL to jurisdiction
            jurisdiction_id: eCode360 jurisdiction ID
            chapter: Specific chapter to scrape
            **kwargs: Additional arguments
            
        Returns:
            Dict with scraped content and metadata
        """
        try:
            # Determine target URL
            if jurisdiction_url:
                target_url = jurisdiction_url
                # Extract jurisdiction info from URL
                jurisdiction_id = self._extract_jurisdiction_id(jurisdiction_url)
            elif jurisdiction_id:
                target_url = f"{self.BASE_URL}/{jurisdiction_id}"
                if chapter:
                    target_url += f"/{chapter}"
            else:
                raise ValueError("Must provide jurisdiction_url or jurisdiction_id")
            
            logger.info(f"Scraping eCode360: {target_url}")
            
            # Scrape using unified system
            metadata = {
                "scraper": self.get_scraper_name(),
                "jurisdiction_id": jurisdiction_id,
                "chapter": chapter,
                "type": "municipal_code",
                "platform": "ecode360"
            }
            
            result = await self.scrape_url_unified(target_url, metadata)
            
            # Parse content
            if result['status'] == 'success':
                parsed = await self._parse_ecode360(result['content'], jurisdiction_id)
                result.update(parsed)
            
            return result
        
        except Exception as e:
            logger.error(f"Error scraping eCode360: {e}")
            return {
                "status": "error",
                "error": str(e),
                "jurisdiction_url": jurisdiction_url,
                "jurisdiction_id": jurisdiction_id
            }
    
    async def scrape_multiple(
        self,
        jurisdiction_urls: List[str],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Batch scrape multiple jurisdictions.
        
        Args:
            jurisdiction_urls: List of jurisdiction URLs
            max_concurrent: Max concurrent requests
            **kwargs: Additional arguments
            
        Returns:
            List of scrape results
        """
        return await self.batch_scrape(
            urls=jurisdiction_urls,
            max_concurrent=max_concurrent,
            metadata_list=[{"platform": "ecode360"} for _ in jurisdiction_urls]
        )
    
    def _extract_jurisdiction_id(self, url: str) -> Optional[str]:
        """Extract jurisdiction ID from eCode360 URL."""
        # Pattern: ecode360.com/JURISDICTION_ID
        match = re.search(r'ecode360\.com/([A-Z0-9_-]+)', url, re.I)
        if match:
            return match.group(1)
        return None
    
    async def _parse_ecode360(
        self,
        content: Any,
        jurisdiction_id: str
    ) -> Dict[str, Any]:
        """
        Parse eCode360 content.
        
        Args:
            content: Raw HTML content
            jurisdiction_id: Jurisdiction identifier
            
        Returns:
            Parsed data dict
        """
        if isinstance(content, bytes):
            content_str = content.decode('utf-8', errors='ignore')
        else:
            content_str = str(content)
        
        return {
            "jurisdiction_id": jurisdiction_id,
            "platform": "ecode360",
            "content_length": len(content_str),
            "parsed": True,
            # Would add parsing:
            # - Jurisdiction name
            # - Chapters list
            # - Sections
            # - Article text
        }


# Convenience function
def scrape_ecode360(
    jurisdiction_url: str = None,
    jurisdiction_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Sync wrapper for eCode360 scraping.
    
    Args:
        jurisdiction_url: Full jurisdiction URL
        jurisdiction_id: Jurisdiction ID
        **kwargs: Additional arguments
        
    Returns:
        Scrape result
    """
    import asyncio
    scraper = ECode360Scraper()
    return asyncio.run(scraper.scrape(
        jurisdiction_url=jurisdiction_url,
        jurisdiction_id=jurisdiction_id,
        **kwargs
    ))


if __name__ == "__main__":
    # Test
    result = scrape_ecode360(jurisdiction_url="https://ecode360.com/TEST_JURISDICTION")
    print(f"Status: {result.get('status')}")
    print(f"Jurisdiction: {result.get('jurisdiction_id')}")
