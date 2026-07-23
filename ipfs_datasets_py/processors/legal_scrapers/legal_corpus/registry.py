"""Jurisdiction registry for legal corpus implementations."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .interfaces import LegalCorpusJurisdiction


_REGISTRY: dict[str, LegalCorpusJurisdiction] = {}
_BUILTIN_IMPORTS = {
    "nl": "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.jurisdiction",
    "netherlands": "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.jurisdiction",
    "netherlands_laws": "ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.jurisdiction",
}


def _normalize_key(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _registration_keys(jurisdiction: LegalCorpusJurisdiction) -> set[str]:
    spec = jurisdiction.spec
    keys = {
        spec.jurisdiction_id,
        spec.country_code,
        spec.slug,
        spec.display_name,
        *spec.aliases,
    }
    return {_normalize_key(key) for key in keys if _normalize_key(key)}


def register_jurisdiction(jurisdiction: LegalCorpusJurisdiction) -> LegalCorpusJurisdiction:
    """Register a jurisdiction implementation under its spec aliases."""

    for key in _registration_keys(jurisdiction):
        _REGISTRY[key] = jurisdiction
    return jurisdiction


def _load_builtin(key: str) -> None:
    module_name = _BUILTIN_IMPORTS.get(_normalize_key(key))
    if module_name:
        import_module(module_name)


def get_jurisdiction(key: str) -> LegalCorpusJurisdiction:
    """Return a registered jurisdiction, lazy-loading built-ins when needed."""

    normalized = _normalize_key(key)
    if normalized not in _REGISTRY:
        _load_builtin(normalized)
    if normalized not in _REGISTRY:
        available = ", ".join(available_jurisdictions()) or "none"
        raise KeyError(f"Unknown legal corpus jurisdiction {key!r}. Available: {available}.")
    return _REGISTRY[normalized]


def available_jurisdictions() -> list[str]:
    """Return registered jurisdiction keys."""

    return sorted(_REGISTRY)


def registry_snapshot() -> dict[str, Any]:
    """Return a serializable registry summary for diagnostics."""

    return {
        key: {
            "slug": jurisdiction.spec.slug,
            "jurisdiction_id": jurisdiction.spec.jurisdiction_id,
            "display_name": jurisdiction.spec.display_name,
            "country_code": jurisdiction.spec.country_code,
        }
        for key, jurisdiction in sorted(_REGISTRY.items())
    }


__all__ = ["available_jurisdictions", "get_jurisdiction", "register_jurisdiction", "registry_snapshot"]
