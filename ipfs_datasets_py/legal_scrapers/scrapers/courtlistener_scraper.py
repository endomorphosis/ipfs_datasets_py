"""CourtListener scraper with fallback to direct court websites.

This scraper provides a unified interface to search and retrieve court documents,
first attempting to fetch from CourtListener API, then falling back to direct
court website scraping if the citation is not found.

CourtListener provides:
- Federal court opinions and dockets
- State court opinions
- Oral arguments
- Judges database
- RECAP Archive (PACER documents)

Fallback sources:
- Supreme Court: supremecourt.gov
- Circuit Courts: Individual circuit websites
- State Courts: Individual state court websites
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)

# CourtListener API base URL
COURTLISTENER_API_BASE = "https://www.courtlistener.com/api/rest/v3"

# Court jurisdiction mappings
FEDERAL_COURTS = {
    "scotus": {"name": "Supreme Court", "url": "https://www.supremecourt.gov"},
    "ca1": {"name": "First Circuit", "url": "https://www.ca1.uscourts.gov"},
    "ca2": {"name": "Second Circuit", "url": "https://www.ca2.uscourts.gov"},
    "ca3": {"name": "Third Circuit", "url": "https://www.ca3.uscourts.gov"},
    "ca4": {"name": "Fourth Circuit", "url": "https://www.ca4.uscourts.gov"},
    "ca5": {"name": "Fifth Circuit", "url": "https://www.ca5.uscourts.gov"},
    "ca6": {"name": "Sixth Circuit", "url": "https://www.ca6.uscourts.gov"},
    "ca7": {"name": "Seventh Circuit", "url": "https://www.ca7.uscourts.gov"},
    "ca8": {"name": "Eighth Circuit", "url": "https://www.ca8.uscourts.gov"},
    "ca9": {"name": "Ninth Circuit", "url": "https://www.ca9.uscourts.gov"},
    "ca10": {"name": "Tenth Circuit", "url": "https://www.ca10.uscourts.gov"},
    "ca11": {"name": "Eleventh Circuit", "url": "https://www.ca11.uscourts.gov"},
    "cadc": {"name": "D.C. Circuit", "url": "https://www.cadc.uscourts.gov"},
    "cafc": {"name": "Federal Circuit", "url": "https://www.cafc.uscourts.gov"}
}


class CourtListenerScraper:
    """Scraper for CourtListener with fallback to direct court websites."""
    
    def __init__(self, api_token: Optional[str] = None, unified_scraper=None):
        """Initialize the scraper.
        
        Args:
            api_token: Optional CourtListener API token for higher rate limits
            unified_scraper: UnifiedScraper instance for fallback scraping
        """
        self.api_token = api_token
        self.unified_scraper = unified_scraper
        self.headers = {}
        if api_token:
            self.headers["Authorization"] = f"Token {api_token}"
    
    async def search_opinions(
        self,
        query: Optional[str] = None,
        citation: Optional[str] = None,
        court: Optional[str] = None,
        judge: Optional[str] = None,
        filed_after: Optional[str] = None,
        filed_before: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Search for court opinions on CourtListener with fallback.
        
        Args:
            query: Free text search query
            citation: Specific citation to search for (e.g., "410 U.S. 113")
            court: Court identifier (e.g., "scotus", "ca9")
            judge: Judge name to filter by
            filed_after: Date in YYYY-MM-DD format
            filed_before: Date in YYYY-MM-DD format
            limit: Maximum number of results
            
        Returns:
            Dictionary with results and metadata
        """
        # First try CourtListener API
        try:
            results = await self._search_courtlistener_api(
                query=query,
                citation=citation,
                court=court,
                judge=judge,
                filed_after=filed_after,
                filed_before=filed_before,
                limit=limit
            )
            
            if results.get("count", 0) > 0:
                logger.info(f"Found {results['count']} results on CourtListener")
                return results
                
        except Exception as e:
            logger.warning(f"CourtListener API search failed: {e}")
        
        # Fallback to direct court website scraping
        if citation or court:
            logger.info("Falling back to direct court website scraping")
            return await self._fallback_to_direct_scraping(
                citation=citation,
                court=court,
                query=query
            )
        
        return {"count": 0, "results": [], "source": "none"}
    
    async def _search_courtlistener_api(
        self,
        query: Optional[str] = None,
        citation: Optional[str] = None,
        court: Optional[str] = None,
        judge: Optional[str] = None,
        filed_after: Optional[str] = None,
        filed_before: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Search CourtListener API."""
        if not self.unified_scraper:
            raise ValueError("UnifiedScraper required for API requests")
        
        url = f"{COURTLISTENER_API_BASE}/search/"
        params = {"type": "o", "format": "json"}  # o = opinions
        
        if query:
            params["q"] = query
        if citation:
            params["citation"] = citation
        if court:
            params["court"] = court
        if judge:
            params["judge"] = judge
        if filed_after:
            params["filed_after"] = filed_after
        if filed_before:
            params["filed_before"] = filed_before
        params["page_size"] = min(limit, 100)
        
        result = await self.unified_scraper.scrape_url(
            url=url,
            params=params,
            headers=self.headers,
            method="GET"
        )
        
        if result.get("status") == "success":
            return {
                "count": result.get("data", {}).get("count", 0),
                "results": result.get("data", {}).get("results", []),
                "source": "courtlistener_api"
            }
        
        raise Exception(f"API request failed: {result.get('error')}")
    
    async def _fallback_to_direct_scraping(
        self,
        citation: Optional[str] = None,
        court: Optional[str] = None,
        query: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fallback to scraping directly from court websites."""
        if not self.unified_scraper:
            return {"count": 0, "results": [], "source": "no_scraper"}
        
        results = []
        
        # Determine which court to scrape
        if court and court in FEDERAL_COURTS:
            court_info = FEDERAL_COURTS[court]
            logger.info(f"Scraping {court_info['name']} at {court_info['url']}")
            
            try:
                result = await self.unified_scraper.scrape_url(
                    url=court_info['url'],
                    content_addressed=True,
                    extract_links=True
                )
                
                if result.get("status") == "success":
                    # Parse the court website for opinions
                    # This is court-specific and would need custom logic per court
                    results.append({
                        "court": court,
                        "source_url": court_info['url'],
                        "content": result.get("content"),
                        "cid": result.get("cid")
                    })
            except Exception as e:
                logger.error(f"Failed to scrape {court}: {e}")
        
        return {
            "count": len(results),
            "results": results,
            "source": "direct_scraping",
            "citation_searched": citation,
            "court_searched": court
        }
    
    async def get_dockets(
        self,
        court: Optional[str] = None,
        case_name: Optional[str] = None,
        docket_number: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Search for court dockets."""
        if not self.unified_scraper:
            return {"count": 0, "results": [], "source": "no_scraper"}
        
        url = f"{COURTLISTENER_API_BASE}/dockets/"
        params = {"format": "json"}
        
        if court:
            params["court"] = court
        if case_name:
            params["case_name"] = case_name
        if docket_number:
            params["docket_number"] = docket_number
        params["page_size"] = min(limit, 100)
        
        try:
            result = await self.unified_scraper.scrape_url(
                url=url,
                params=params,
                headers=self.headers,
                method="GET"
            )
            
            if result.get("status") == "success":
                return {
                    "count": result.get("data", {}).get("count", 0),
                    "results": result.get("data", {}).get("results", []),
                    "source": "courtlistener_api"
                }
        except Exception as e:
            logger.error(f"Failed to fetch dockets: {e}")
        
        return {"count": 0, "results": [], "source": "error"}
    
    async def get_judges(
        self,
        name_search: Optional[str] = None,
        court: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Search for judges in the database."""
        if not self.unified_scraper:
            return {"count": 0, "results": [], "source": "no_scraper"}
        
        url = f"{COURTLISTENER_API_BASE}/people/"
        params = {"format": "json"}
        
        if name_search:
            params["name"] = name_search
        if court:
            params["court"] = court
        params["page_size"] = min(limit, 100)
        
        try:
            result = await self.unified_scraper.scrape_url(
                url=url,
                params=params,
                headers=self.headers,
                method="GET"
            )
            
            if result.get("status") == "success":
                return {
                    "count": result.get("data", {}).get("count", 0),
                    "results": result.get("data", {}).get("results", []),
                    "source": "courtlistener_api"
                }
        except Exception as e:
            logger.error(f"Failed to fetch judges: {e}")
        
        return {"count": 0, "results": [], "source": "error"}


# Convenience functions for common use cases
async def search_supreme_court_cases(
    citation: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    api_token: Optional[str] = None
) -> Dict[str, Any]:
    """Search Supreme Court cases with fallback."""
    from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
    
    unified_scraper = UnifiedScraper()
    scraper = CourtListenerScraper(api_token=api_token, unified_scraper=unified_scraper)
    
    return await scraper.search_opinions(
        court="scotus",
        citation=citation,
        query=query,
        limit=limit
    )


async def search_circuit_court_cases(
    circuit: str,
    citation: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    api_token: Optional[str] = None
) -> Dict[str, Any]:
    """Search Circuit Court cases with fallback.
    
    Args:
        circuit: Circuit identifier (e.g., "ca9" for Ninth Circuit)
    """
    from ipfs_datasets_py.legal_scrapers.unified_scraper import UnifiedScraper
    
    unified_scraper = UnifiedScraper()
    scraper = CourtListenerScraper(api_token=api_token, unified_scraper=unified_scraper)
    
    return await scraper.search_opinions(
        court=circuit,
        citation=citation,
        query=query,
        limit=limit
    )
