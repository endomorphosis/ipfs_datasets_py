"""
Legal Scraper Registry for Auto-Discovery and Routing

This module provides a centralized registry for all legal scrapers,
enabling auto-discovery, routing, and fallback chain coordination.

Author: Generated for Phase 11 Task 11.2
Date: 2026-02-16
"""

import inspect
import logging
from abc import ABC
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Type, Any, Callable
import importlib
import sys

# Import monitoring
try:
    from ..infrastructure.monitoring import monitor
    MONITORING_AVAILABLE = True
except ImportError:
    def monitor(func):
        return func
    MONITORING_AVAILABLE = False

logger = logging.getLogger(__name__)


class ScraperType(Enum):
    """Types of legal scrapers."""
    FEDERAL = "federal"
    STATE = "state"
    MUNICIPAL = "municipal"
    COMMON_CRAWL = "common_crawl"
    GENERIC = "generic"


class ScraperCapability(Enum):
    """Capabilities that scrapers can provide."""
    WARC_PARSING = "warc_parsing"
    GRAPHRAG_EXTRACTION = "graphrag_extraction"
    ASYNC_BATCH = "async_batch"
    RATE_LIMITING = "rate_limiting"
    CACHING = "caching"
    FALLBACK_SUPPORT = "fallback_support"


@dataclass
class ScraperInfo:
    """Information about a registered scraper."""
    name: str
    scraper_type: ScraperType
    scraper_class: Type
    capabilities: List[ScraperCapability]
    priority: int  # Lower number = higher priority
    description: str
    supports_sources: List[str]  # List of source identifiers it can handle
    
    def can_handle(self, source: str) -> bool:
        """Check if this scraper can handle the given source."""
        if not self.supports_sources:
            return True  # Generic scraper
        return any(s in source.lower() for s in self.supports_sources)


class LegalScraperRegistry:
    """
    Registry for all legal scrapers with auto-discovery and routing.
    
    Features:
    - Auto-discovers scrapers from legal_scrapers package
    - Routes requests to appropriate scraper
    - Manages fallback chains
    - Tracks scraper capabilities
    - Provides scraper selection logic
    
    Example:
        registry = LegalScraperRegistry()
        registry.auto_discover()
        
        # Get scraper for federal source
        scraper = registry.get_scraper_for_source("congress.gov")
        
        # Get all federal scrapers
        federal_scrapers = registry.get_scrapers_by_type(ScraperType.FEDERAL)
    """
    
    def __init__(self):
        """Initialize the registry."""
        self._scrapers: Dict[str, ScraperInfo] = {}
        self._type_index: Dict[ScraperType, List[str]] = {
            st: [] for st in ScraperType
        }
        self._capability_index: Dict[ScraperCapability, List[str]] = {
            cap: [] for cap in ScraperCapability
        }
        
    def register(
        self,
        name: str,
        scraper_class: Type,
        scraper_type: ScraperType,
        capabilities: List[ScraperCapability] = None,
        priority: int = 50,
        description: str = "",
        supports_sources: List[str] = None
    ) -> None:
        """
        Register a scraper manually.
        
        Args:
            name: Unique name for the scraper
            scraper_class: The scraper class
            scraper_type: Type of scraper
            capabilities: List of capabilities
            priority: Priority (lower = higher priority)
            description: Description of the scraper
            supports_sources: List of source identifiers it handles
        """
        if capabilities is None:
            capabilities = []
        if supports_sources is None:
            supports_sources = []
            
        info = ScraperInfo(
            name=name,
            scraper_type=scraper_type,
            scraper_class=scraper_class,
            capabilities=capabilities,
            priority=priority,
            description=description,
            supports_sources=supports_sources
        )
        
        self._scrapers[name] = info
        self._type_index[scraper_type].append(name)
        
        for cap in capabilities:
            self._capability_index[cap].append(name)
            
        logger.info(f"Registered scraper: {name} (type={scraper_type.value}, priority={priority})")
    
    @monitor
    def auto_discover(self) -> int:
        """
        Auto-discover and register scrapers from the legal_scrapers package.
        
        Returns:
            Number of scrapers discovered
        """
        count = 0
        
        # Get the legal_scrapers package directory
        current_dir = Path(__file__).parent
        
        # Import and register known scrapers
        scrapers_to_register = [
            # Federal scrapers
            {
                "name": "us_code",
                "module": "us_code_scraper",
                "class_name": None,  # Will look for main scraper class
                "type": ScraperType.FEDERAL,
                "priority": 10,
                "sources": ["uscode.house.gov", "congress.gov/uscode"],
                "capabilities": [ScraperCapability.ASYNC_BATCH]
            },
            {
                "name": "federal_register",
                "module": "federal_register_scraper",
                "class_name": None,
                "type": ScraperType.FEDERAL,
                "priority": 10,
                "sources": ["federalregister.gov"],
                "capabilities": [ScraperCapability.ASYNC_BATCH]
            },
            {
                "name": "recap_archive",
                "module": "recap_archive_scraper",
                "class_name": None,
                "type": ScraperType.FEDERAL,
                "priority": 15,
                "sources": ["courtlistener.com", "recap"],
                "capabilities": [ScraperCapability.ASYNC_BATCH]
            },
            # State scrapers
            {
                "name": "state_laws",
                "module": "state_laws_scraper",
                "class_name": None,
                "type": ScraperType.STATE,
                "priority": 20,
                "sources": ["state", "legislature"],
                "capabilities": [ScraperCapability.ASYNC_BATCH]
            },
            # Municipal scrapers
            {
                "name": "municode",
                "module": "municipal_law_database_scrapers.municode_scraper",
                "class_name": "MunicodeScraper",
                "type": ScraperType.MUNICIPAL,
                "priority": 20,
                "sources": ["municode.com"],
                "capabilities": [ScraperCapability.ASYNC_BATCH]
            },
            {
                "name": "ecode360",
                "module": "municipal_law_database_scrapers.ecode360_scraper",
                "class_name": "Ecode360Scraper",
                "type": ScraperType.MUNICIPAL,
                "priority": 20,
                "sources": ["ecode360.com"],
                "capabilities": [ScraperCapability.ASYNC_BATCH]
            },
            {
                "name": "american_legal",
                "module": "municipal_law_database_scrapers.american_legal_scraper",
                "class_name": "AmericanLegalScraper",
                "type": ScraperType.MUNICIPAL,
                "priority": 20,
                "sources": ["american-legal.net", "amlegal.com"],
                "capabilities": [ScraperCapability.ASYNC_BATCH]
            },
            # Common Crawl scraper (highest priority for fallback)
            {
                "name": "common_crawl",
                "module": "common_crawl_scraper",
                "class_name": "CommonCrawlLegalScraper",
                "type": ScraperType.COMMON_CRAWL,
                "priority": 5,  # Highest priority
                "sources": [],  # Can handle any source
                "capabilities": [
                    ScraperCapability.WARC_PARSING,
                    ScraperCapability.GRAPHRAG_EXTRACTION,
                    ScraperCapability.ASYNC_BATCH,
                    ScraperCapability.FALLBACK_SUPPORT,
                    ScraperCapability.CACHING
                ]
            }
        ]
        
        for scraper_def in scrapers_to_register:
            try:
                # Import the module
                module_path = f"ipfs_datasets_py.processors.legal_scrapers.{scraper_def['module']}"
                module = importlib.import_module(module_path)
                
                # Try to find the scraper class
                scraper_class = None
                if scraper_def.get("class_name"):
                    scraper_class = getattr(module, scraper_def["class_name"], None)
                else:
                    # Look for a class ending with "Scraper"
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if name.endswith("Scraper") and not name.startswith("Base"):
                            scraper_class = obj
                            break
                
                if scraper_class:
                    self.register(
                        name=scraper_def["name"],
                        scraper_class=scraper_class,
                        scraper_type=scraper_def["type"],
                        capabilities=scraper_def.get("capabilities", []),
                        priority=scraper_def["priority"],
                        description=f"{scraper_def['name']} scraper",
                        supports_sources=scraper_def.get("sources", [])
                    )
                    count += 1
                else:
                    logger.warning(f"Could not find scraper class in {scraper_def['module']}")
                    
            except Exception as e:
                logger.warning(f"Failed to register {scraper_def['name']}: {e}")
                continue
        
        logger.info(f"Auto-discovered {count} scrapers")
        return count
    
    @monitor
    def get_scraper_for_source(
        self,
        source: str,
        required_capabilities: List[ScraperCapability] = None
    ) -> Optional[Type]:
        """
        Get the best scraper for a given source.
        
        Args:
            source: Source URL or identifier
            required_capabilities: Required capabilities
            
        Returns:
            Scraper class or None
        """
        if required_capabilities is None:
            required_capabilities = []
        
        # Find all scrapers that can handle this source
        candidates = []
        for name, info in self._scrapers.items():
            # Check if scraper can handle the source
            if not info.can_handle(source):
                continue
            
            # Check required capabilities
            if required_capabilities:
                if not all(cap in info.capabilities for cap in required_capabilities):
                    continue
            
            candidates.append((info.priority, name, info))
        
        if not candidates:
            logger.warning(f"No scraper found for source: {source}")
            return None
        
        # Sort by priority (lower number = higher priority)
        candidates.sort(key=lambda x: x[0])
        
        selected = candidates[0][2]
        logger.info(f"Selected scraper '{selected.name}' for source: {source}")
        
        return selected.scraper_class
    
    def get_scrapers_by_type(self, scraper_type: ScraperType) -> List[ScraperInfo]:
        """Get all scrapers of a given type."""
        names = self._type_index.get(scraper_type, [])
        return [self._scrapers[name] for name in names if name in self._scrapers]
    
    def get_scrapers_by_capability(
        self,
        capability: ScraperCapability
    ) -> List[ScraperInfo]:
        """Get all scrapers with a given capability."""
        names = self._capability_index.get(capability, [])
        return [self._scrapers[name] for name in names if name in self._scrapers]
    
    def get_all_scrapers(self) -> List[ScraperInfo]:
        """Get all registered scrapers."""
        return list(self._scrapers.values())
    
    def get_scraper_info(self, name: str) -> Optional[ScraperInfo]:
        """Get information about a specific scraper."""
        return self._scrapers.get(name)
    
    @monitor
    def create_fallback_chain(
        self,
        source: str,
        max_fallbacks: int = 3
    ) -> List[Type]:
        """
        Create a fallback chain for a given source.
        
        Args:
            source: Source URL or identifier
            max_fallbacks: Maximum number of fallbacks
            
        Returns:
            List of scraper classes in priority order
        """
        # Find all scrapers that can handle this source
        candidates = []
        for name, info in self._scrapers.items():
            if info.can_handle(source):
                candidates.append((info.priority, info.scraper_class))
        
        # Sort by priority
        candidates.sort(key=lambda x: x[0])
        
        # Return top N scrapers
        chain = [scraper for _, scraper in candidates[:max_fallbacks]]
        
        logger.info(f"Created fallback chain with {len(chain)} scrapers for: {source}")
        return chain
    
    def list_scrapers(self) -> List[ScraperInfo]:
        """Get list of all registered scrapers.
        
        Returns:
            List of ScraperInfo objects for all registered scrapers.
        """
        return list(self._scrapers.values())
    
    def format_scraper_list(self) -> str:
        """Get a formatted string listing all registered scrapers.
        
        Returns:
            Formatted string representation of all scrapers.
        """
        lines = ["Registered Legal Scrapers:", "=" * 60]
        
        for scraper_type in ScraperType:
            scrapers = self.get_scrapers_by_type(scraper_type)
            if scrapers:
                lines.append(f"\n{scraper_type.value.upper()}:")
                for info in sorted(scrapers, key=lambda x: x.priority):
                    caps = ", ".join(c.value for c in info.capabilities)
                    lines.append(f"  - {info.name} (priority={info.priority})")
                    if caps:
                        lines.append(f"    Capabilities: {caps}")
                    if info.supports_sources:
                        sources = ", ".join(info.supports_sources[:3])
                        lines.append(f"    Sources: {sources}")
        
        lines.append(f"\nTotal: {len(self._scrapers)} scrapers registered")
        return "\n".join(lines)


# Global registry instance
_global_registry: Optional[LegalScraperRegistry] = None


def get_registry() -> LegalScraperRegistry:
    """
    Get the global scraper registry instance.
    
    Auto-discovers scrapers on first call.
    
    Returns:
        Global registry instance
    """
    global _global_registry
    
    if _global_registry is None:
        _global_registry = LegalScraperRegistry()
        _global_registry.auto_discover()
    
    return _global_registry


def reset_registry() -> None:
    """Reset the global registry (useful for testing)."""
    global _global_registry
    _global_registry = None


# Convenience functions
def get_scraper_for_source(source: str, **kwargs) -> Optional[Type]:
    """Get the best scraper for a source."""
    return get_registry().get_scraper_for_source(source, **kwargs)


def list_all_scrapers() -> List[ScraperInfo]:
    """List all registered scrapers.
    
    Returns:
        List of ScraperInfo objects.
    """
    return get_registry().list_scrapers()


if __name__ == "__main__":
    # CLI interface for testing
    import argparse
    
    parser = argparse.ArgumentParser(description="Legal Scraper Registry")
    parser.add_argument("--list", action="store_true", help="List all scrapers")
    parser.add_argument("--source", help="Find scraper for source")
    parser.add_argument("--type", help="List scrapers by type")
    
    args = parser.parse_args()
    
    registry = get_registry()
    
    if args.list:
        print(registry.format_scraper_list())
    
    elif args.source:
        scraper_class = registry.get_scraper_for_source(args.source)
        if scraper_class:
            print(f"Best scraper for '{args.source}': {scraper_class.__name__}")
            chain = registry.create_fallback_chain(args.source)
            print(f"\nFallback chain ({len(chain)} scrapers):")
            for i, sc in enumerate(chain, 1):
                print(f"  {i}. {sc.__name__}")
        else:
            print(f"No scraper found for: {args.source}")
    
    elif args.type:
        try:
            scraper_type = ScraperType(args.type.lower())
            scrapers = registry.get_scrapers_by_type(scraper_type)
            print(f"\n{scraper_type.value.upper()} Scrapers ({len(scrapers)}):")
            for info in scrapers:
                print(f"  - {info.name} (priority={info.priority})")
        except ValueError:
            print(f"Invalid type. Valid types: {', '.join(st.value for st in ScraperType)}")
    
    else:
        print("Use --list, --source <url>, or --type <type>")
        print(f"Available types: {', '.join(st.value for st in ScraperType)}")
