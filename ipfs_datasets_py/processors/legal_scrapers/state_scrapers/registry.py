"""Registry for state-specific scrapers.

This module manages the registration and retrieval of state-specific
law scrapers.
"""

import hashlib
import inspect
from pathlib import Path
import sys
from typing import Any, Dict, Optional, Type
from .base_scraper import BaseStateScraper
import logging

logger = logging.getLogger(__name__)


class StateScraperRegistry:
    """Registry for state-specific scrapers."""

    _scrapers: Dict[str, Type[BaseStateScraper]] = {}
    _source_registration_attestations: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(cls, state_code: str, scraper_class: Type[BaseStateScraper]):
        """Register a scraper for a state.

        Args:
            state_code: Two-letter state code
            scraper_class: Scraper class to register
        """
        normalized_code = state_code.upper()
        source_file = inspect.getsourcefile(scraper_class)
        if not source_file:
            raise ValueError(
                f"registered scraper source is not inspectable for {normalized_code}"
            )
        source_path = Path(source_file).resolve()
        if source_path.is_symlink() or not source_path.is_file():
            raise ValueError(
                f"registered scraper source is not a regular file for {normalized_code}"
            )
        import_sha256 = ""
        package_module = sys.modules.get(
            "ipfs_datasets_py.processors.legal_scrapers"
        )
        if package_module is not None:
            package_snapshots = getattr(
                package_module,
                "STATE_LAWS_PRODUCER_IMPORT_SOURCE_SHA256",
                {},
            )
            import_sha256 = str(package_snapshots.get(str(source_path)) or "")
        if not import_sha256:
            # External/plugin scrapers are captured at the registration event.
            # The first registration of the same loaded class remains binding,
            # so re-registering it after a disk edit cannot bless new bytes.
            prior = cls._source_registration_attestations.get(normalized_code)
            if prior and prior.get("scraper_class") is scraper_class:
                import_sha256 = str(prior.get("import_source_sha256") or "")
            if not import_sha256:
                import_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        cls._scrapers[normalized_code] = scraper_class
        cls._source_registration_attestations[normalized_code] = {
            "scraper_class": scraper_class,
            "source_path": str(source_path),
            "import_source_sha256": import_sha256,
        }
        logger.debug(f"Registered scraper for {state_code}")

    @classmethod
    def get_source_registration_attestation(
        cls,
        state_code: str,
    ) -> Optional[Dict[str, Any]]:
        """Return a copy of the class/file binding captured at registration."""

        value = cls._source_registration_attestations.get(state_code.upper())
        return dict(value) if value is not None else None

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
    def get_scraper_class(cls, state_code: str) -> Optional[Type[BaseStateScraper]]:
        """Get scraper class for a state (alias for get_scraper).

        Args:
            state_code: Two-letter state code

        Returns:
            Scraper class or None if not registered
        """
        return cls.get_scraper(state_code)

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
