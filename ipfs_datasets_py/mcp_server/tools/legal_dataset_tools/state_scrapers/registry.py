"""Registry for state-specific scrapers.

This module manages the registration and retrieval of state-specific
law scrapers.
"""

from typing import Dict, Optional, Type
from .base_scraper import BaseStateScraper
import logging

logger = logging.getLogger(__name__)


class StateScraperRegistry:
    """Registry for state-specific scrapers."""
    
    _scrapers: Dict[str, Type[BaseStateScraper]] = {}
    
    @classmethod
    def register(cls, state_code: str, scraper_class: Type[BaseStateScraper]):
        """Register a scraper for a state.
        
        Args:
            state_code: Two-letter state code
            scraper_class: Scraper class to register
        """
        cls._scrapers[state_code.upper()] = scraper_class
        logger.debug(f"Registered scraper for {state_code}")
    
    @classmethod
    def get_scraper(cls, state_code: str) -> Optional[Type[BaseStateScraper]]:
        """Get scraper class for a state.
        
        Args:
            state_code: Two-letter state code
            
        Returns:
            Scraper class or None if not registered
        """
        return cls._scrapers.get(state_code.upper())
    
    @classmethod
    def get_all_registered_states(cls) -> list:
        """Get list of all states with registered scrapers.
        
        Returns:
            List of state codes
        """
        return list(cls._scrapers.keys())
    
    @classmethod
    def has_scraper(cls, state_code: str) -> bool:
        """Check if a scraper exists for a state.
        
        Args:
            state_code: Two-letter state code
            
        Returns:
            True if scraper exists
        """
        return state_code.upper() in cls._scrapers


def get_scraper_for_state(state_code: str, state_name: str) -> Optional[BaseStateScraper]:
    """Get an initialized scraper instance for a state.
    
    Args:
        state_code: Two-letter state code
        state_name: Full state name
        
    Returns:
        Initialized scraper instance or None
    """
    scraper_class = StateScraperRegistry.get_scraper(state_code)
    if scraper_class:
        return scraper_class(state_code, state_name)
    return None
