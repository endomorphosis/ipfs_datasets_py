#!/usr/bin/env python3
"""
General Municipal Code Scraper - Core Implementation

Generic scraper for municipal codes from various platforms.
Works as fallback when specific platform scrapers don't apply.
"""

import logging
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse

from .base_scraper import BaseLegalScraper

logger = logging.getLogger(__name__)


class MunicipalCodeScraper(BaseLegalScraper):
    """
    Generic municipal code scraper.
    
    Works with:
    - General municipal websites
    - Unknown code platforms
    - Custom municipality sites
    """
    
    # Known platforms to delegate to
    PLATFORM_PATTERNS = {
        "municode.com": "municode",
        "ecode360.com": "ecode360",
        "generalcode.com": "generalcode",
        "codepublishing.com": "codepublishing",
        "sterlingcodifiers.com": "sterlingcodifiers",
    }
    
    def get_scraper_name(self) -> str:
        """Return scraper identifier."""
        return "municipal_code"
    
    async def scrape(
        self,
        url: str,
        municipality_name: str = None,
        state: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Scrape municipal code from any platform.
        
        Args:
            url: URL to scrape
            municipality_name: Name of municipality
            state: State code
            **kwargs: Additional arguments
            
        Returns:
            Dict with scraped content and metadata
        """
        try:
            # Detect platform
            platform = self._detect_platform(url)
            
            logger.info(f"Scraping municipal code: {url}")
            if platform:
                logger.info(f"  Detected platform: {platform}")
            
            # Scrape using unified system
            metadata = {
                "scraper": self.get_scraper_name(),
                "municipality": municipality_name,
                "state": state,
                "platform": platform or "unknown",
                "type": "municipal_code"
            }
            
            result = await self.scrape_url_unified(url, metadata)
            
            # Parse content
            if result['status'] == 'success':
                parsed = await self._parse_municipal_code(
                    result['content'],
                    platform,
                    municipality_name
                )
                result.update(parsed)
            
            return result
        
        except Exception as e:
            logger.error(f"Error scraping municipal code: {e}")
            return {
                "status": "error",
                "error": str(e),
                "url": url,
                "municipality": municipality_name
            }
    
    async def scrape_multiple(
        self,
        urls: List[str],
        municipalities: List[str] = None,
        max_concurrent: int = 5,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Batch scrape multiple municipal codes.
        
        Args:
            urls: List of URLs
            municipalities: List of municipality names
            max_concurrent: Max concurrent requests
            **kwargs: Additional arguments
            
        Returns:
            List of scrape results
        """
        if not municipalities:
            municipalities = [None] * len(urls)
        
        return await self.batch_scrape(
            urls=urls,
            max_concurrent=max_concurrent,
            metadata_list=[
                {"municipality": muni}
                for muni in municipalities
            ]
        )
    
    def _detect_platform(self, url: str) -> Optional[str]:
        """Detect code platform from URL."""
        domain = urlparse(url).netloc.lower()
        
        for pattern, platform in self.PLATFORM_PATTERNS.items():
            if pattern in domain:
                return platform
        
        return None
    
    async def _parse_municipal_code(
        self,
        content: Any,
        platform: str = None,
        municipality: str = None
    ) -> Dict[str, Any]:
        """
        Parse municipal code content.
        
        Args:
            content: Raw HTML content
            platform: Detected platform
            municipality: Municipality name
            
        Returns:
            Parsed data dict
        """
        if isinstance(content, bytes):
            content_str = content.decode('utf-8', errors='ignore')
        else:
            content_str = str(content)
        
        return {
            "municipality": municipality,
            "platform": platform or "unknown",
            "content_length": len(content_str),
            "parsed": True,
            # Generic parsing would go here
        }


# Convenience function
def scrape_municipal_code(
    url: str,
    municipality_name: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Sync wrapper for municipal code scraping.
    
    Args:
        url: URL to scrape
        municipality_name: Municipality name
        **kwargs: Additional arguments
        
    Returns:
        Scrape result
    """
    import asyncio
    scraper = MunicipalCodeScraper()
    return asyncio.run(scraper.scrape(
        url=url,
        municipality_name=municipality_name,
        **kwargs
    ))


if __name__ == "__main__":
    # Test
    result = scrape_municipal_code(
        url="https://example.gov/code",
        municipality_name="Example City"
    )
    print(f"Status: {result.get('status')}")
    print(f"Platform: {result.get('platform')}")
