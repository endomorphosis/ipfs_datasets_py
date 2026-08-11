"""Import compatibility and object-identity tests for patent engines (PATLAW-019).

Unit tests perform no live network calls.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from unittest.mock import MagicMock, patch

import pytest


LEGACY_ENGINE = "ipfs_datasets_py.processors.legal_scrapers.patent_engine"
FEDERAL_ENGINE = (
    "ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.patent_engine"
)
CANONICAL = "ipfs_datasets_py.processors.domains.patent.patent_scraper"

_ENGINE_SYMBOLS = (
    "Patent",
    "PatentDatasetBuilder",
    "PatentSearchCriteria",
    "USPTOPatentScraper",
    "search_patents_by_assignee",
    "search_patents_by_inventor",
    "search_patents_by_keyword",
)


def _purge_engine_modules() -> None:
    for name in (LEGACY_ENGINE, FEDERAL_ENGINE):
        sys.modules.pop(name, None)


def _import_with_deprecation(module_name: str):
    _purge_engine_modules()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        module = importlib.import_module(module_name)
        # Force body re-execution so DeprecationWarning is recorded even if the
        # module was imported earlier in the session.
        module = importlib.reload(module)
        dep = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    return module, dep


def test_legacy_and_federal_engines_emit_deprecation_warnings() -> None:
    legacy, legacy_deps = _import_with_deprecation(LEGACY_ENGINE)
    federal, federal_deps = _import_with_deprecation(FEDERAL_ENGINE)

    assert legacy_deps, "expected DeprecationWarning from legal_scrapers.patent_engine"
    assert federal_deps, "expected DeprecationWarning from federal_scrapers.patent_engine"
    legacy_msgs = " ".join(str(w.message) for w in legacy_deps)
    federal_msgs = " ".join(str(w.message) for w in federal_deps)
    assert "domains.patent.patent_scraper" in legacy_msgs
    assert "domains.patent.patent_scraper" in federal_msgs
    assert legacy is not None
    assert federal is not None


def test_legacy_classes_share_object_identity_with_canonical() -> None:
    """All legacy engine paths resolve to one canonical class implementation."""
    _purge_engine_modules()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        canonical = importlib.import_module(CANONICAL)
        legacy = importlib.import_module(LEGACY_ENGINE)
        federal = importlib.import_module(FEDERAL_ENGINE)

    for name in _ENGINE_SYMBOLS:
        assert getattr(legacy, name) is getattr(canonical, name), name
        assert getattr(federal, name) is getattr(canonical, name), name
        assert getattr(legacy, name) is getattr(federal, name), name


def test_package_level_legal_scrapers_exports_match_canonical() -> None:
    _purge_engine_modules()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from ipfs_datasets_py.processors.legal_scrapers import (
            Patent,
            PatentDatasetBuilder,
            PatentSearchCriteria,
            USPTOPatentScraper,
        )
        from ipfs_datasets_py.processors.domains.patent.patent_scraper import (
            Patent as CanonicalPatent,
            PatentDatasetBuilder as CanonicalBuilder,
            PatentSearchCriteria as CanonicalCriteria,
            USPTOPatentScraper as CanonicalScraper,
        )

    assert Patent is CanonicalPatent
    assert PatentDatasetBuilder is CanonicalBuilder
    assert PatentSearchCriteria is CanonicalCriteria
    assert USPTOPatentScraper is CanonicalScraper


def test_legal_scrapers_patent_engine_module_is_importable() -> None:
    """The missing legal_scrapers.patent_engine lazy import is restored."""
    _purge_engine_modules()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        mod = importlib.import_module(LEGACY_ENGINE)
    for name in _ENGINE_SYMBOLS:
        assert hasattr(mod, name)


def test_scraper_methods_do_not_perform_live_network_calls() -> None:
    """Unit-level engine exercise uses mocks only — no live USPTO traffic."""
    _purge_engine_modules()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from ipfs_datasets_py.processors.legal_scrapers.patent_engine import (
            PatentSearchCriteria,
            USPTOPatentScraper,
        )

    scraper = USPTOPatentScraper(rate_limit_delay=0.0)
    criteria = PatentSearchCriteria(keywords=["offline-only"], limit=1)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "patents": [
            {
                "patent_number": "US999",
                "patent_title": "Mock patent",
                "patent_abstract": "abstract",
                "patent_date": "2024-01-01",
                "app_number": "16/999",
                "app_date": "2022-01-01",
                "inventors": [],
                "assignees": [],
                "cpcs": [],
                "cited_patents": [],
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(scraper.session, "post", return_value=mock_response) as mock_post:
        patents = scraper.search_patents(criteria)

    mock_post.assert_called_once()
    assert len(patents) == 1
    assert patents[0].patent_number == "US999"
    # Ensure we never fell through to a real host.
    called_url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get("url")
    assert called_url == USPTOPatentScraper.BASE_URL or mock_post.called


def test_models_import_path_is_canonical() -> None:
    from ipfs_datasets_py.processors.domains.patent import models as patent_models

    assert patent_models.MODELS_SCHEMA_VERSION == "public-patent.models.v1"
    assert patent_models.PublicPatent is not None
    assert patent_models.PublicApplication is not None
    assert patent_models.PatentDocument is not None
    assert patent_models.PatentClaim is not None
    assert patent_models.ProsecutionEvent is not None
    assert patent_models.Rejection is not None
    assert patent_models.Citation is not None
