"""State laws scraper for building state statutory law datasets.

This tool scrapes state statutes and regulations from various state
legislative websites and legal databases.
"""
import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# US States and territories
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"
}


async def list_state_jurisdictions() -> Dict[str, Any]:
    """Get list of all US state jurisdictions.
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - states: Dictionary mapping state codes to names
            - count: Number of states/territories
            - error: Error message (if failed)
    """
    try:
        return {
            "status": "success",
            "states": US_STATES,
            "count": len(US_STATES),
            "note": "Includes all 50 US states and DC"
        }
    except Exception as e:
        logger.error(f"Failed to get state jurisdictions: {e}")
        return {
            "status": "error",
            "error": str(e),
            "states": {},
            "count": 0
        }


async def scrape_state_laws(
    states: Optional[List[str]] = None,
    legal_areas: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 2.0,
    max_statutes: Optional[int] = None
) -> Dict[str, Any]:
    """Scrape state statutes and build a structured dataset.
    
    Args:
        states: List of state codes to scrape (e.g., ["CA", "NY", "TX"]).
                If None or ["all"], scrapes all states.
        legal_areas: Specific areas of law to focus on (e.g., ["criminal", "civil", "family"])
        output_format: Output format - "json" or "parquet"
        include_metadata: Include statute metadata (effective dates, amendments, etc.)
        rate_limit_delay: Delay between requests in seconds (default 2.0, higher for state sites)
        max_statutes: Maximum number of statutes to scrape
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - data: Scraped state statutes
            - metadata: Scraping metadata
            - output_format: Format of the data
            - error: Error message (if failed)
    """
    try:
        # Validate and process states
        if states is None or "all" in states:
            selected_states = list(US_STATES.keys())
        else:
            selected_states = [s.upper() for s in states if s.upper() in US_STATES]
            if not selected_states:
                return {
                    "status": "error",
                    "error": "No valid states specified",
                    "data": [],
                    "metadata": {}
                }
        
        logger.info(f"Starting state laws scraping for states: {selected_states}")
        start_time = time.time()
        
        # Import required libraries
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError as ie:
            return {
                "status": "error",
                "error": f"Required library not available: {ie}. Install with: pip install requests beautifulsoup4",
                "data": [],
                "metadata": {}
            }
        
        scraped_statutes = []
        statutes_count = 0
        errors = []
        
        # State code sources mapping - using Justia as a reliable aggregator
        state_sources = {
            state_code: {
                "name": US_STATES[state_code],
                "justia_url": f"https://law.justia.com/codes/{state_code.lower()}/",
                "official_url": _get_official_state_url(state_code)
            }
            for state_code in US_STATES.keys()
        }
        
        # Scrape each selected state
        for state_code in selected_states:
            if max_statutes and statutes_count >= max_statutes:
                logger.info(f"Reached max_statutes limit of {max_statutes}")
                break
            
            state_name = US_STATES[state_code]
            logger.info(f"Scraping {state_code}: {state_name}")
            
            try:
                # Fetch state code overview from Justia
                state_info = state_sources[state_code]
                justia_url = state_info["justia_url"]
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                response = requests.get(justia_url, headers=headers, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract code titles/sections
                statutes = []
                code_links = soup.find_all('a', href=True)
                
                for link in code_links:
                    href = link.get('href', '')
                    text = link.get_text(strip=True)
                    
                    # Look for statute/code links
                    if text and len(text) > 10 and (
                        '/codes/' in href or 
                        'title' in text.lower() or 
                        'chapter' in text.lower() or
                        'article' in text.lower()
                    ):
                        # Filter by legal area if specified
                        if legal_areas:
                            area_match = any(area.lower() in text.lower() for area in legal_areas)
                            if not area_match:
                                continue
                        
                        statute = {
                            "statute_number": text[:100],
                            "title": text[:200],
                            "url": href if href.startswith('http') else f"https://law.justia.com{href}",
                            "legal_area": _identify_legal_area(text, legal_areas),
                        }
                        
                        if include_metadata:
                            statute["scraped_at"] = datetime.now().isoformat()
                            statute["source"] = "Justia"
                        
                        statutes.append(statute)
                        statutes_count += 1
                        
                        if max_statutes and statutes_count >= max_statutes:
                            break
                
                statute_data = {
                    "state_code": state_code,
                    "state_name": state_name,
                    "title": f"{state_name} Code",
                    "source": "Justia Legal Database",
                    "source_url": justia_url,
                    "official_url": state_info["official_url"],
                    "scraped_at": datetime.now().isoformat(),
                    "statutes": statutes[:max_statutes] if max_statutes else statutes
                }
                
                scraped_statutes.append(statute_data)
                logger.info(f"Successfully scraped {len(statutes)} statutes for {state_name}")
                
            except Exception as e:
                error_msg = f"Failed to scrape {state_name}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                
                # Add minimal data even on error
                statute_data = {
                    "state_code": state_code,
                    "state_name": state_name,
                    "error": str(e),
                    "scraped_at": datetime.now().isoformat(),
                    "statutes": []
                }
                scraped_statutes.append(statute_data)
            
            # Rate limiting to be respectful to servers
            time.sleep(rate_limit_delay)
        
        elapsed_time = time.time() - start_time
        
        metadata = {
            "states_scraped": selected_states,
            "states_count": len(selected_states),
            "statutes_count": statutes_count,
            "legal_areas": legal_areas or ["all"],
            "elapsed_time_seconds": elapsed_time,
            "scraped_at": datetime.now().isoformat(),
            "sources": "Justia Legal Database (https://law.justia.com)",
            "rate_limit_delay": rate_limit_delay,
            "include_metadata": include_metadata,
            "errors": errors if errors else None
        }
        
        logger.info(f"Completed state laws scraping: {statutes_count} statutes in {elapsed_time:.2f}s")
        
        return {
            "status": "success" if not errors else "partial_success",
            "data": scraped_statutes,
            "metadata": metadata,
            "output_format": output_format,
        }
        
    except Exception as e:
        logger.error(f"State laws scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {}
        }


def _get_official_state_url(state_code: str) -> str:
    """Get official state legislature URL for a given state code."""
    # Mapping of state codes to their official legislative websites
    official_urls = {
        "CA": "https://leginfo.legislature.ca.gov/",
        "NY": "https://www.nysenate.gov/",
        "TX": "https://capitol.texas.gov/",
        "FL": "http://www.leg.state.fl.us/",
        "IL": "https://www.ilga.gov/",
        "PA": "https://www.legis.state.pa.us/",
        "OH": "https://www.legislature.ohio.gov/",
        "GA": "http://www.legis.ga.gov/",
        "NC": "https://www.ncleg.gov/",
        "MI": "https://www.legislature.mi.gov/",
    }
    
    return official_urls.get(state_code, f"https://legislature.{state_code.lower()}.gov/")


def _identify_legal_area(text: str, legal_areas: Optional[List[str]] = None) -> str:
    """Identify the legal area from statute title text."""
    text_lower = text.lower()
    
    # Common legal area keywords
    area_keywords = {
        "criminal": ["criminal", "penal", "crime", "felony", "misdemeanor"],
        "civil": ["civil", "tort", "liability", "damages"],
        "family": ["family", "marriage", "divorce", "custody", "child support"],
        "employment": ["employment", "labor", "worker", "wage", "unemployment"],
        "environmental": ["environmental", "pollution", "conservation", "wildlife"],
        "business": ["business", "corporation", "commercial", "contract", "sales"],
        "property": ["property", "real estate", "land", "conveyance"],
        "tax": ["tax", "taxation", "revenue", "assessment"],
        "health": ["health", "medical", "healthcare", "insurance"],
        "education": ["education", "school", "university", "student"],
    }
    
    # Check if user specified legal areas
    if legal_areas:
        for area in legal_areas:
            if area.lower() in text_lower:
                return area
    
    # Auto-detect legal area
    for area, keywords in area_keywords.items():
        for keyword in keywords:
            if keyword in text_lower:
                return area
    
    return "general"
