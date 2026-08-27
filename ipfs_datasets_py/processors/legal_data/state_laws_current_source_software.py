"""Current registered source-software identities for exact-51 state laws.

The helpers are local and deterministic.  They inspect source files for the
registered state scrapers; they do not crawl, fetch, index, publish, or write.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

from .state_laws_completeness import CANONICAL_JURISDICTION_ORDER


_CANONICAL_CODES: Final = frozenset(CANONICAL_JURISDICTION_ORDER)
_SOURCE_SOFTWARE_VERSION_RE: Final = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


def normalize_exact_51_source_software_versions(
    value: Mapping[str, Any],
) -> dict[str, str]:
    """Validate one exact content-addressed source identity per jurisdiction."""

    if not isinstance(value, Mapping):
        raise TypeError("current_source_software_versions must be a mapping")
    supplied_codes = set(value)
    if supplied_codes != _CANONICAL_CODES:
        missing_codes = sorted(_CANONICAL_CODES - supplied_codes)
        extra_codes = sorted(supplied_codes - _CANONICAL_CODES)
        raise ValueError(
            "current_source_software_versions must contain exact-51 keys; "
            f"missing={missing_codes}, extra={extra_codes}"
        )
    normalized: dict[str, str] = {}
    for code in CANONICAL_JURISDICTION_ORDER:
        version = str(value[code] or "").strip()
        if _SOURCE_SOFTWARE_VERSION_RE.fullmatch(version) is None:
            raise ValueError(
                "current source software version must be a qualified "
                f"content-addressed identity for {code}: {version!r}"
            )
        normalized[code] = version
    return normalized


def registered_exact_51_source_software_versions() -> dict[str, str]:
    """Resolve exact-51 scraper bundle identities without network I/O."""

    from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
        US_STATES,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        get_scraper_for_state,
    )

    versions: dict[str, str] = {}
    for code in CANONICAL_JURISDICTION_ORDER:
        scraper = get_scraper_for_state(code, US_STATES[code])
        if scraper is None:
            raise ValueError(f"no registered current scraper for jurisdiction {code}")
        versions[code] = scraper._state_law_frontier_source_software_version()
    return normalize_exact_51_source_software_versions(versions)
