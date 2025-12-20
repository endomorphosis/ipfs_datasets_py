"""
Multi-source legal citation resolver.

Resolves legal citations using multiple sources with fallback:
1. CourtListener (primary) - comprehensive federal and state
2. State court websites (state-specific citations)
3. Google Scholar (fallback)
4. FindLaw/Justia (fallback)

Supports:
- U.S. Supreme Court citations
- Federal appellate citations
- Federal district citations
- State court citations
- Administrative citations
"""

import logging
import asyncio
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """Parsed legal citation."""
    volume: str
    reporter: str
    page: str
    pinpoint: Optional[str] = None
    court: Optional[str] = None
    year: Optional[str] = None
    raw: str = ""


class CitationResolver:
    """
    Multi-source citation resolver with intelligent fallbacks.
    
    Resolution cascade:
    1. CourtListener API (best for federal and many state courts)
    2. State court website (for state-specific citations)
    3. Google Scholar (public access, comprehensive)
    4. FindLaw/Justia (commercial, reliable)
    """
    
    # Reporter abbreviations mapping
    REPORTER_MAP = {
        # U.S. Supreme Court
        'us': 'U.S. Supreme Court',
        'u.s.': 'U.S. Supreme Court',
        's.ct.': 'U.S. Supreme Court',
        'sct': 'U.S. Supreme Court',
        'l.ed.': 'U.S. Supreme Court',
        'l.ed.2d': 'U.S. Supreme Court',
        
        # Federal Appellate
        'f.': 'Federal Reporter',
        'f.2d': 'Federal Reporter 2d',
        'f.3d': 'Federal Reporter 3d',
        'f.4th': 'Federal Reporter 4th',
        
        # Federal District
        'f.supp.': 'Federal Supplement',
        'f.supp.2d': 'Federal Supplement 2d',
        'f.supp.3d': 'Federal Supplement 3d',
        
        # State reporters (examples - expand as needed)
        'cal.': 'California Reports',
        'cal.2d': 'California Reports 2d',
        'cal.3d': 'California Reports 3d',
        'cal.4th': 'California Reports 4th',
        'cal.5th': 'California Reports 5th',
        'n.y.': 'New York Reports',
        'n.y.2d': 'New York Reports 2d',
        'n.y.3d': 'New York Reports 3d',
    }
    
    def __init__(self,
                 courtlistener_api_token: Optional[str] = None,
                 enable_google_scholar: bool = True,
                 enable_commercial: bool = True):
        """
        Initialize citation resolver.
        
        Args:
            courtlistener_api_token: CourtListener API token
            enable_google_scholar: Enable Google Scholar fallback
            enable_commercial: Enable FindLaw/Justia fallback
        """
        self.courtlistener_api_token = courtlistener_api_token
        self.enable_google_scholar = enable_google_scholar
        self.enable_commercial = enable_commercial
        
        # Initialize scrapers
        self.cl_scraper = None
        try:
            from .courtlistener import CourtListenerScraper
            self.cl_scraper = CourtListenerScraper(api_token=courtlistener_api_token)
        except ImportError as e:
            logger.warning(f"CourtListener not available: {e}")
        
        logger.info(f"CitationResolver initialized")
    
    def parse_citation(self, citation_str: str) -> Optional[Citation]:
        """
        Parse a legal citation string.
        
        Supports formats:
        - "123 U.S. 456" (volume reporter page)
        - "123 F.3d 456, 460" (with pinpoint)
        - "123 S.Ct. 456 (2020)" (with year)
        
        Args:
            citation_str: Citation string to parse
        
        Returns:
            Citation object or None if parsing fails
        """
        # Basic citation pattern: VOLUME REPORTER PAGE[, PINPOINT][ (YEAR)]
        pattern = r'(\d+)\s+([A-Za-z.\d]+)\s+(\d+)(?:,\s*(\d+))?(?:\s*\((\d{4})\))?'
        
        match = re.search(pattern, citation_str)
        if not match:
            logger.warning(f"Could not parse citation: {citation_str}")
            return None
        
        volume, reporter, page, pinpoint, year = match.groups()
        
        # Normalize reporter
        reporter_norm = reporter.lower().strip()
        court = self.REPORTER_MAP.get(reporter_norm, "Unknown")
        
        return Citation(
            volume=volume,
            reporter=reporter,
            page=page,
            pinpoint=pinpoint,
            court=court,
            year=year,
            raw=citation_str
        )
    
    async def resolve(self, citation_str: str) -> Dict[str, Any]:
        """
        Resolve a citation using all available sources.
        
        Args:
            citation_str: Citation string (e.g., "123 F.3d 456")
        
        Returns:
            Dict with resolution results including document metadata and URLs
        """
        logger.info(f"Resolving citation: {citation_str}")
        
        # Parse citation
        citation = self.parse_citation(citation_str)
        if not citation:
            return {
                "success": False,
                "error": "Could not parse citation",
                "citation": citation_str
            }
        
        results = {
            "success": False,
            "citation": citation_str,
            "parsed": {
                "volume": citation.volume,
                "reporter": citation.reporter,
                "page": citation.page,
                "court": citation.court,
                "year": citation.year
            },
            "sources": []
        }
        
        # Try CourtListener first
        if self.cl_scraper:
            try:
                cl_result = await self._resolve_courtlistener(citation)
                if cl_result.get("success"):
                    results["success"] = True
                    results["sources"].append({
                        "name": "CourtListener",
                        "data": cl_result
                    })
                    # If CourtListener found it, we're done
                    return results
            except Exception as e:
                logger.warning(f"CourtListener resolution failed: {e}")
        
        # Try state courts if it looks like a state citation
        if self._is_state_citation(citation):
            try:
                state_result = await self._resolve_state_court(citation)
                if state_result.get("success"):
                    results["success"] = True
                    results["sources"].append({
                        "name": "State Court",
                        "data": state_result
                    })
                    return results
            except Exception as e:
                logger.warning(f"State court resolution failed: {e}")
        
        # Try Google Scholar if enabled
        if self.enable_google_scholar:
            try:
                scholar_result = await self._resolve_google_scholar(citation)
                if scholar_result.get("success"):
                    results["success"] = True
                    results["sources"].append({
                        "name": "Google Scholar",
                        "data": scholar_result
                    })
                    return results
            except Exception as e:
                logger.warning(f"Google Scholar resolution failed: {e}")
        
        # Try commercial sources if enabled
        if self.enable_commercial:
            try:
                commercial_result = await self._resolve_commercial(citation)
                if commercial_result.get("success"):
                    results["success"] = True
                    results["sources"].append({
                        "name": "Commercial",
                        "data": commercial_result
                    })
                    return results
            except Exception as e:
                logger.warning(f"Commercial resolution failed: {e}")
        
        # All sources failed
        results["error"] = "Citation not found in any source"
        return results
    
    async def _resolve_courtlistener(self, citation: Citation) -> Dict[str, Any]:
        """
        Resolve citation using CourtListener.
        
        Args:
            citation: Parsed citation
        
        Returns:
            Dict with resolution results
        """
        if not self.cl_scraper:
            return {"success": False, "error": "CourtListener not available"}
        
        # Use CourtListener's citation search
        citation_query = f"{citation.volume} {citation.reporter} {citation.page}"
        result = await self.cl_scraper.resolve_citation(citation_query)
        
        return result
    
    def _is_state_citation(self, citation: Citation) -> bool:
        """
        Check if citation is likely a state court citation.
        
        Args:
            citation: Parsed citation
        
        Returns:
            True if likely state citation
        """
        reporter_lower = citation.reporter.lower()
        
        # Check for state-specific reporters
        state_indicators = ['cal.', 'n.y.', 'tex.', 'fla.', 'ill.', 'pa.', 
                           'ohio', 'mich.', 'mass.', 'wash.']
        
        return any(indicator in reporter_lower for indicator in state_indicators)
    
    async def _resolve_state_court(self, citation: Citation) -> Dict[str, Any]:
        """
        Resolve citation using state court website.
        
        Args:
            citation: Parsed citation
        
        Returns:
            Dict with resolution results
        """
        # TODO: Implement state court website scraping
        # This would involve:
        # 1. Detecting which state from reporter
        # 2. Accessing state court website
        # 3. Searching for the citation
        # 4. Extracting opinion document
        
        await asyncio.sleep(0.1)
        
        return {
            "success": False,
            "error": "State court website scraping not yet implemented",
            "note": "Would scrape state supreme/appellate court websites"
        }
    
    async def _resolve_google_scholar(self, citation: Citation) -> Dict[str, Any]:
        """
        Resolve citation using Google Scholar.
        
        Args:
            citation: Parsed citation
        
        Returns:
            Dict with resolution results
        """
        # TODO: Implement Google Scholar scraping
        # Google Scholar has comprehensive case law
        # scholar.google.com/scholar?q=citation
        
        await asyncio.sleep(0.1)
        
        return {
            "success": False,
            "error": "Google Scholar scraping not yet implemented",
            "note": "Would use scholar.google.com/scholar"
        }
    
    async def _resolve_commercial(self, citation: Citation) -> Dict[str, Any]:
        """
        Resolve citation using commercial sources (FindLaw, Justia).
        
        Args:
            citation: Parsed citation
        
        Returns:
            Dict with resolution results
        """
        # TODO: Implement commercial source scraping
        # FindLaw, Justia, and other commercial databases
        
        await asyncio.sleep(0.1)
        
        return {
            "success": False,
            "error": "Commercial source scraping not yet implemented",
            "note": "Would use FindLaw, Justia, etc."
        }
    
    async def batch_resolve(self, citations: List[str]) -> Dict[str, Any]:
        """
        Resolve multiple citations in parallel.
        
        Args:
            citations: List of citation strings
        
        Returns:
            Dict with results for all citations
        """
        logger.info(f"Batch resolving {len(citations)} citations")
        
        # Resolve in parallel
        tasks = [self.resolve(cit) for cit in citations]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            "success": True,
            "count": len(citations),
            "results": results
        }


# Convenience functions
async def resolve_citation(citation: str, **kwargs) -> Dict[str, Any]:
    """Resolve a single citation."""
    resolver = CitationResolver(**kwargs)
    return await resolver.resolve(citation)


async def batch_resolve_citations(citations: List[str], **kwargs) -> Dict[str, Any]:
    """Resolve multiple citations."""
    resolver = CitationResolver(**kwargs)
    return await resolver.batch_resolve(citations)
