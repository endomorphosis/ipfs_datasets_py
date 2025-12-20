"""
Legal scrapers package - provides access to all legal data scrapers.

This package consolidates all legal scraping functionality:
- State law scrapers (all 50 states + DC)
- Municipal code scrapers (Municode, eCode360, American Legal)
- Federal scrapers (US Code, Federal Register, RECAP)
- Unified interface with automatic fallbacks
"""

from pathlib import Path
import sys

# Add parent paths for imports
_package_root = Path(__file__).parent.parent.parent
if str(_package_root) not in sys.path:
    sys.path.insert(0, str(_package_root))

__all__ = [
    "get_state_scraper",
    "get_municipal_scraper",
    "get_federal_scraper",
    "get_court_scraper",
    "list_available_scrapers",
]


def get_state_scraper(state_code: str):
    """
    Get state-specific scraper for the given state code.
    
    Args:
        state_code: Two-letter state code (e.g., "CA", "NY", "TX")
    
    Returns:
        State scraper instance with unified interface
    """
    from .state_scrapers import get_scraper_for_state
    return get_scraper_for_state(state_code)


def get_municipal_scraper(provider: str = "municode"):
    """
    Get municipal code scraper for the specified provider.
    
    Args:
        provider: Provider name ("municode", "ecode360", "american_legal")
    
    Returns:
        Municipal scraper instance with unified interface
    """
    if provider.lower() == "municode":
        from .municipal_scrapers import municode_scraper
        return municode_scraper
    elif provider.lower() == "ecode360":
        from .municipal_scrapers import ecode360_scraper
        return ecode360_scraper
    elif provider.lower() == "american_legal":
        from .municipal_scrapers import american_legal_scraper
        return american_legal_scraper
    else:
        raise ValueError(f"Unknown municipal scraper provider: {provider}")


def get_federal_scraper(scraper_type: str):
    """
    Get federal scraper of the specified type.
    
    Args:
        scraper_type: Type of federal scraper ("us_code", "federal_register", "recap")
    
    Returns:
        Federal scraper instance with unified interface
    """
    if scraper_type.lower() == "us_code":
        from . import us_code_scraper
        return us_code_scraper
    elif scraper_type.lower() == "federal_register":
        from . import federal_register_scraper
        return federal_register_scraper
    elif scraper_type.lower() == "recap":
        from ..core import recap
        return recap
    else:
        raise ValueError(f"Unknown federal scraper type: {scraper_type}")


def get_court_scraper(court_type: str = "courtlistener", api_token: str = None):
    """
    Get court scraper with fallback capabilities.
    
    Args:
        court_type: Type of court scraper ("courtlistener", "recap", "supreme_court")
        api_token: Optional API token for CourtListener
    
    Returns:
        Court scraper instance with unified interface and fallback
    """
    from .courtlistener_scraper import CourtListenerScraper
    from ..unified_scraper import UnifiedScraper
    
    unified_scraper = UnifiedScraper()
    
    if court_type.lower() in ["courtlistener", "supreme_court", "circuit_court"]:
        return CourtListenerScraper(api_token=api_token, unified_scraper=unified_scraper)
    elif court_type.lower() == "recap":
        from ..core import recap
        return recap
    else:
        raise ValueError(f"Unknown court scraper type: {court_type}")


def list_available_scrapers():
    """
    List all available scrapers in the system.
    
    Returns:
        Dict with categories of available scrapers
    """
    try:
        from .state_scrapers.registry import StateScraperRegistry
        state_list = StateScraperRegistry.get_all_registered_states()
    except Exception as e:
        # Fallback: list all US states
        state_list = [
            "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
            "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
            "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
            "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
            "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"
        ]
    
    municipal_list = ["municode", "ecode360", "american_legal"]
    federal_list = ["us_code", "federal_register", "recap"]
    court_list = ["courtlistener", "supreme_court", "circuit_court", "recap"]
    
    return {
        "state_scrapers": state_list,
        "municipal_scrapers": municipal_list,
        "federal_scrapers": federal_list,
        "court_scrapers": court_list,
        "total_count": len(state_list) + len(municipal_list) + len(federal_list) + len(court_list)
    }
