#!/usr/bin/env python3
"""Refresh the canonical state-laws corpus and publish merged HF artifacts.

The state-specific scrapers write one JSON-LD file per state. This command
turns those JSON-LD files into canonical CID-keyed parquet shards, optionally
merges already-published Hugging Face rows, and uploads the refreshed shards
back to the canonical JusticeDAO state-laws dataset.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import sys
import types
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence


_RUNNER_SOURCE_PATH = Path(__file__).resolve()
MODULE_IMPORT_SOURCE_SHA256 = hashlib.sha256(
    _RUNNER_SOURCE_PATH.read_bytes()
).hexdigest()


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_data.canonical_legal_corpora import (
    get_canonical_legal_corpus,
)
from ipfs_datasets_py.processors.legal_data.legal_source_recovery_promotion import (
    _resolve_hf_token,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    ACTION_REUSE,
    CoordinationPlan,
    coordinate_default_prior_evidence,
)
from ipfs_datasets_py.processors.legal_data.state_laws_run_seal import (
    IN_PROGRESS_EVIDENCE_MARKER,
    NONQUIESCENT_EVIDENCE_MARKER,
    PENDING_NORMALIZED_RECEIPT_SUFFIX,
    RUN_SEAL_SUFFIX,
    build_state_laws_run_seal,
    canonical_run_seal_bytes,
    run_seal_sha256,
    validate_authorizing_transport_projection,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    normalize_source_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    SourceReceiptRecord,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    DEFAULT_MIN_FULL_TEXT_CHARS,
    MULTIFETCH_EVIDENCE_ROOT_ENV,
    RETAINED_REPLAY_ONLY_ENV,
    STRICT_MULTIFETCH_EVIDENCE_ENV,
    US_STATES,
    _write_state_jsonld_files,
    inventory_registered_state_scraper_transport_bypasses,
    scrape_state_laws,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    atomic_staging,
    atomic_write_bytes,
    atomic_write_canonical_json,
    file_digest,
)
from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import iter_jsonl
from ipfs_datasets_py.utils.cid_utils import canonical_json_bytes, cid_for_obj

STATE_CODES_50: List[str] = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

# Exact production jurisdiction set: 50 postal codes + DC (LCR-007).
STATE_CODES_51: List[str] = list(STATE_CODES_50) + ["DC"]
CANONICAL_PRODUCTION_JURISDICTIONS = frozenset(STATE_CODES_51)
EXPECTED_PRODUCTION_JURISDICTION_COUNT = 51

_CORPUS = get_canonical_legal_corpus("state_laws")
_COMPLETED_STATES_SCHEMA = "ipfs_datasets_py.state_laws_refresh.completed_states.v1"
_LOCAL_MATERIALIZATION_RECEIPT_SCHEMA = (
    "ipfs_datasets_py.state_laws_refresh.local_materialization.v1"
)
_SOURCE_SOFTWARE_IMMUTABILITY_SCHEMA = (
    "ipfs_datasets_py.state_laws_refresh.source_software_immutability.v1"
)
_REGISTRY_RECORDABLE_STATE_STATUSES = {"success", "zero_statutes"}

# A sealed acquisition may consume only selectors that the worker snapshots
# with type-aware semantics.  Legacy fixture/local-input selectors are useful
# for parser tests and migrations, but ambient values are not a production
# run-input attestation and therefore fail strict preflight.
_BOUND_PRODUCTION_SELECTOR_ENV = frozenset(
    """
    ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT ARKANSAS_LEXIS_INVENTORY_PATH
    ARKANSAS_LEXIS_PUBLIC_ACCESS_ENABLE STATE_SCRAPER_MS_LEXIS_EVIDENCE_DIR
    MISSISSIPPI_LEXIS_PUBLIC_ACCESS_ENABLE GEORGIA_LEXIS_PUBLIC_ACCESS_ENABLE
    GEORGIA_ARCHIVED_OFFICIAL_MANIFEST CALIFORNIA_BULK_ZIP
    CALIFORNIA_BULK_ZIP_RECEIPT ILLINOIS_BULK_ZIP ILLINOIS_MANIFEST_TEXT
    INDIANA_BULK_ZIP INDIANA_BULK_ZIP_RECEIPT INDIANA_CODE_ZIP_RECEIPT
    INDIANA_CODE_ZIP_CACHE_DIR NEW_JERSEY_BULK_ZIP
    NEW_JERSEY_BULK_RETAINED_SHA256
    NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY DC_CODE_SECTION_XML
    DC_CODE_XML_DIR MICHIGAN_CHAPTER_XML MICHIGAN_CHAPTER_INDEX_HTML
    NY_OPENLEG_LAW_JSON NY_CATEGORY_HTML UTAH_TITLE_XML UTAH_TOC_HTML
    STATE_SCRAPER_FULL_CORPUS
    """.split()
)
_STRICT_SHARED_AMBIENT_SELECTOR_DENY = frozenset(
    """
    LEGAL_SCRAPER_FETCH_CACHE_DIR IPFS_DATASETS_LEGAL_FETCH_CACHE_DIR
    LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR IPFS_DATASETS_PY_COMMON_CRAWL_INDEX_ROOT
    LEGAL_SCRAPER_FETCH_CACHE_ENABLED LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED
    LEGAL_SCRAPER_IPFS_PAGE_CACHE_PIN
    IPFS_DATASETS_PY_COMMON_CRAWL_MATERIALIZE_LOCAL CCINDEX_PARQUET_ROOT
    CCINDEX_MASTER_DB CCINDEX_MCP_ENDPOINT COMMON_CRAWL_HF_REMOTE_META
    IPFS_DATASETS_PY_COMMON_CRAWL_HF_REMOTE_META
    COMMON_CRAWL_HF_META_INDEX_DATASET
    IPFS_DATASETS_PY_COMMON_CRAWL_HF_META_INDEX_DATASET
    COMMON_CRAWL_HF_POINTER_DATASET
    IPFS_DATASETS_PY_COMMON_CRAWL_HF_POINTER_DATASET COMMON_CRAWL_HF_REVISION
    STATE_SCRAPER_COMMON_CRAWL_COLLECTION STATE_SCRAPER_COMMON_CRAWL_YEAR
    """.split()
)
_STRICT_SOURCE_ROUTING_SELECTOR_DENY = frozenset(
    """
    INDIANA_CODE_YEAR INDIANA_CODE_MIN_YEAR INDIANA_CODE_MAX_YEAR
    INDIANA_WAYBACK_FALLBACK_TIMESTAMP IOWA_CODE_YEAR
    IOWA_OFFICIAL_USE_ARCHIVAL_FALLBACK
    IOWA_ALLOW_JUSTIA_FALLBACK STATE_SCRAPER_IA_ALLOW_JUSTIA_FALLBACK
    STATE_SCRAPER_CT_ALLOW_JUSTIA_FALLBACK STATE_SCRAPER_GA_ALLOW_JUSTIA_FALLBACK
    STATE_SCRAPER_HI_ALLOW_JUSTIA_FALLBACK STATE_SCRAPER_MD_ALLOW_JUSTIA_FALLBACK
    STATE_SCRAPER_MN_ALLOW_JUSTIA_FALLBACK STATE_SCRAPER_OK_ALLOW_JUSTIA_FALLBACK
    STATE_SCRAPER_TN_ALLOW_JUSTIA_FALLBACK STATE_SCRAPER_UT_ALLOW_JUSTIA_FALLBACK
    NORTH_CAROLINA_BYCHAPTER_LIVE STATE_SCRAPER_LA_SKIP_LIVE_TOC
    LEGAL_SOURCE_RECOVERY_ENABLE_COMMON_CRAWL LEGAL_SCRAPER_DISABLE_WAYBACK
    STATE_SCRAPER_MAX_STATUTES STATE_SCRAPER_CODE_TIMEOUT_SECONDS
    STATE_SCRAPER_FETCH_TIMEOUT_SECONDS STATE_SCRAPER_BOUNDED_DIRECT_ONLY
    STATE_SCRAPER_GLOBAL_BOUNDED_ENV
    STATE_SCRAPER_GENERIC_DISCOVERY_DEPTH STATE_SCRAPER_GENERIC_DISCOVERY_FANOUT
    STATE_SCRAPER_GENERIC_MAX_PAGES STATE_SCRAPER_COMMON_CRAWL_FRONTIER_MAX_RESULTS
    STATE_SCRAPER_WAYBACK_PREFIX_MAX_QUERIES
    STATE_SCRAPER_WAYBACK_PREFIX_MAX_QUERIES_PER_ORIGIN
    STATE_SCRAPER_WAYBACK_PREFIX_MAX_RESULTS_PER_QUERY
    STATE_SCRAPER_WAYBACK_PREFIX_RESULT_MULTIPLIER
    ARKANSAS_LEXIS_BODY_PROBE_COUNT ARKANSAS_LEXIS_PROBE_MAX_EXPANSIONS
    HAWAII_WALK_WAYBACK_FULL INDIANA_ARCHIVED_PDF_DISCOVERY_LIMIT
    INDIANA_ARCHIVED_TITLE_PAGES_TOTAL_LIMIT INDIANA_FULL_CORPUS_MIN_RECORDS
    INDIANA_FULL_CORPUS_TARGET INDIANA_JUSTIA_CRAWL_PAGE_LIMIT
    INDIANA_JUSTIA_RECOVERY_FETCH_LIMIT IOWA_ARCHIVAL_STUB_LIMIT
    IOWA_FULL_CORPUS_ACCEPT_MIN IOWA_OFFICIAL_CHAPTER_LIMIT
    IOWA_OFFICIAL_FULL_CORPUS_ACCEPT_MIN IOWA_OFFICIAL_SECTION_LIMIT
    IOWA_SECTION_TEXT_MIN_CHARS KENTUCKY_FULL_CORPUS_MAX_CHAPTERS
    NORTH_CAROLINA_BYCHAPTER_MAX_CHAPTERS
    NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_MAX_AGE_SECONDS
    OREGON_CRIMINAL_PROCEDURE_CHAPTERS OREGON_LOCAL_RULE_COUNTIES
    OREGON_LOCAL_RULE_MAX_COUNTIES OREGON_OAR_MAX_CHAPTERS OREGON_OAR_MAX_RULES
    STATE_SCRAPER_MD_MAX_SECTION_BUDGET_PER_ARTICLE
    STATE_SCRAPER_MS_ARCHIVE_TARGET STATE_SCRAPER_MS_COMMON_CRAWL_SEED_TARGET
    STATE_SCRAPER_MS_JUSTIA_SECTION_SCAN_CAP STATE_SCRAPER_MS_JUSTIA_TARGET
    STATE_SCRAPER_MS_READER_SECTION_SCAN_CAP STATE_SCRAPER_MS_READER_SEED_TARGET
    STATE_SCRAPER_MS_UNICOURT_TARGET STATE_SCRAPER_MS_WAYBACK_SECTION_SCAN_CAP
    STATE_SCRAPER_NH_ARCHIVE_DISCOVERY_LIMIT
    STATE_SCRAPER_NH_FULL_CORPUS_MAX_CANDIDATES
    STATE_SCRAPER_NH_MAX_STAGNANT_CANDIDATES
    STATE_SCRAPER_NH_MAX_STAGNANT_CANDIDATES_BOUNDED
    STATE_SCRAPER_OK_BOOTSTRAP_SEED_COUNT
    STATE_LAWS_COMPLETED_STATES_REGISTRY_PATH
    STATE_LAWS_COMPLETED_STATES_BASELINE_PATH
    STATE_LAWS_REGISTRY_TREAT_ZERO_AS_COMPLETE
    STATE_SCRAPER_DIRECT_FIRST STATE_SCRAPER_UNIFIED_FETCH_ENABLED
    STATE_SCRAPER_ARCHIVAL_FETCH_ENABLED
    STATE_SCRAPER_COMMON_CRAWL_STATE_INDEX_ENABLED
    STATE_SCRAPER_COMMON_CRAWL_HF_FALLBACK_ENABLED
    STATE_SCRAPER_MS_ENABLE_ARCHIVE_BILL_HISTORY_FULL_CORPUS
    STATE_SCRAPER_MS_ENABLE_UNICOURT_BOUNDED_FALLBACK
    STATE_SCRAPER_MS_COMMON_CRAWL_FULL_CORPUS_SEEDS_ENABLED
    STATE_SCRAPER_MS_ENABLE_UNICOURT_FALLBACK
    STATE_SCRAPER_MS_ENABLE_LEGACY_GENERIC_FULL_CORPUS_FALLBACK
    STATE_SCRAPER_OK_HEAVY_FALLBACK_FOR_DELIVERDOCUMENT
    INDIANA_DOWNLOAD_BUNDLE_ENABLE INDIANA_ALLOW_JUSTIA_FALLBACK
    STATE_SCRAPER_IN_ALLOW_JUSTIA_FALLBACK INDIANA_JUSTIA_ENABLE
    INDIANA_JUSTIA_DISABLE INDIANA_ARCHIVED_TITLE_PAGES_ENABLE
    INDIANA_GENERIC_FALLBACK INDIANA_JUSTIA_ALLOW_RECOVERY_FETCH
    INDIANA_ALLOW_ARCHIVAL_FETCH_FALLBACK GEORGIA_JUSTIA_ENABLE
    GEORGIA_SUMMARY_PDF_FALLBACK HAWAII_GENERIC_FALLBACK
    """.split()
)
_STRICT_LEGACY_LOCAL_SELECTOR_DENY = frozenset(
    """
    ALABAMA_CONSTITUTION_TITLES_TEXT ALABAMA_CONSTITUTION_ITEMS_JSON
    ALABAMA_TITLES_TEXT ALABAMA_SECTION_JSON ALASKA_CONSTITUTION_HTML
    ALASKA_SECTION_HTML ALASKA_TOC_HTML ALASKA_SECTION_TOC_HTML
    ARIZONA_CONSTITUTION_HTML ARIZONA_SECTION_HTML ARIZONA_TOC_HTML
    ARKANSAS_CONSTITUTION_TEXT ARKANSAS_SECTION_HTML ARKANSAS_TOC_HTML
    CALIFORNIA_CONSTITUTION_HTML COLORADO_CONSTITUTION_TEXT COLORADO_CRS_SGML
    COLORADO_TITLE_HTML COLORADO_CRS_SGML_ZIP COLORADO_PUBLICATION_HTML
    CONNECTICUT_CHAPTER_HTML CONNECTICUT_TITLES_HTML CONNECTICUT_CONSTITUTION_HTML
    DELAWARE_CHAPTER_HTML DELAWARE_TITLE_LINKS_HTML DELAWARE_TITLE_TEXT
    DELAWARE_TITLE_PDF DELAWARE_CONSTITUTION_HTML
    DISTRICT_OF_COLUMBIA_CONSTITUTION_HTML FLORIDA_TOC_HTML
    FLORIDA_TITLE_INDEX_HTML FLORIDA_SENATE_CHAPTER_HTML FLORIDA_CHAPTER_HTML
    FLORIDA_CONSTITUTION_HTML GEORGIA_CHAPTER_HTML GEORGIA_ARCHIVE_HTML
    GEORGIA_CHAPTER_HTML_DIR GEORGIA_TITLE_TEXT GEORGIA_TITLE_PDF
    GEORGIA_TITLE_TEXT_DIR GEORGIA_TITLE_PDF_DIR GEORGIA_CONSTITUTION_HTML
    HAWAII_SECTION_HTML HAWAII_CHAPTER_HTML HAWAII_CONSTITUTION_HTML
    HAWAII_CHAPTER_URL IDAHO_TOC_HTML IDAHO_CONSTITUTION_HTML
    ILLINOIS_CONSTITUTION_HTML ILLINOIS_CONSTITUTION_HTML_DIR
    INDIANA_CONSTITUTION_TEXT IOWA_CHAPTER_XML IOWA_TOC_HTML
    IOWA_CONSTITUTION_HTML KANSAS_SECTION_HTML KANSAS_STATUTE_TABLE_HTML
    KANSAS_CONSTITUTION_HTML KENTUCKY_SECTION_TEXT KENTUCKY_SECTION_PDF
    KENTUCKY_TOC_HTML KENTUCKY_CONSTITUTION_HTML LOUISIANA_LAW_HTML
    LOUISIANA_TOC_HTML LOUISIANA_CONSTITUTION_TEXT MAINE_SECTION_HTML
    MAINE_TITLE_TOC_HTML MAINE_CONSTITUTION_HTML MARYLAND_SECTION_HTML
    MARYLAND_TOC_HTML MARYLAND_CONSTITUTION_HTML
    MARYLAND_CONSTITUTION_TOC_HTML MASSACHUSETTS_SECTION_HTML
    MASSACHUSETTS_TOC_HTML MASSACHUSETTS_CONSTITUTION_HTML
    MICHIGAN_CONSTITUTION_TEXT MINNESOTA_SECTION_HTML MINNESOTA_TOC_HTML
    MINNESOTA_CONSTITUTION_HTML MISSISSIPPI_SECTION_HTML MISSISSIPPI_TITLE_HTML
    MISSISSIPPI_CONSTITUTION_HTML MISSOURI_HOME_HTML MISSOURI_CONSTITUTION_HTML
    MONTANA_SECTION_HTML MONTANA_TOC_HTML MONTANA_CONSTITUTION_HTML
    NEBRASKA_SECTION_HTML NEBRASKA_TOC_HTML NEBRASKA_CHAPTER_HTML
    NEBRASKA_CONSTITUTION_HTML NEVADA_CHAPTER_HTML NEVADA_INDEX_HTML
    NEVADA_CONSTITUTION_HTML NEW_HAMPSHIRE_SECTION_HTML
    NEW_HAMPSHIRE_CHAPTER_TOC_HTML NEW_HAMPSHIRE_SECTION_HTML_DIR
    NEW_HAMPSHIRE_CONSTITUTION_HTML NEW_JERSEY_CONSTITUTION_HTML
    NEW_MEXICO_CHAPTER_TEXT NEW_MEXICO_CONSTITUTION_TEXT
    NEW_YORK_CONSTITUTION_JSON NORTH_CAROLINA_ARCHIVE_HTML
    NORTH_CAROLINA_ARCHIVE_HTML_DIR NORTH_CAROLINA_BYCHAPTER_INDEX_HTML
    NORTH_CAROLINA_TOC_HTML NORTH_CAROLINA_CHAPTER_HTML
    NORTH_CAROLINA_CHAPTER_HTML_DIR NORTH_CAROLINA_CONSTITUTION_HTML
    NORTH_DAKOTA_CHAPTER_TEXT NORTH_DAKOTA_CHAPTER_PDF NORTH_DAKOTA_TOC_HTML
    NORTH_DAKOTA_CONSTITUTION_HTML OHIO_TOC_HTML OHIO_CONSTITUTION_HTML
    OKLAHOMA_TITLE_TEXT OKLAHOMA_TITLE_PDF OKLAHOMA_TITLES_HTML
    OKLAHOMA_CONSTITUTION_TEXT OREGON_CHAPTER_HTML OREGON_ORS_INDEX_HTML
    OREGON_CONSTITUTION_HTML PENNSYLVANIA_TITLE_TEXT PENNSYLVANIA_TOC_HTML
    PENNSYLVANIA_CONSTITUTION_HTML RHODE_ISLAND_SECTION_HTML
    RHODE_ISLAND_TOC_HTML RHODE_ISLAND_CONSTITUTION_HTML
    SOUTH_CAROLINA_CHAPTER_HTML SOUTH_CAROLINA_TOC_HTML
    SOUTH_CAROLINA_CONSTITUTION_HTML SOUTH_DAKOTA_TITLE_HTML
    SOUTH_DAKOTA_CHAPTER_HTML SOUTH_DAKOTA_CONSTITUTION_HTML
    TENNESSEE_SECTION_HTML TENNESSEE_CONSTITUTION_TEXT TEXAS_CHAPTER_HTML
    TEXAS_STATUTE_ARRAY_JSON TEXAS_CONSTITUTION_HTML TEXAS_STATUTE_ARRAY_CODE
    UTAH_CONSTITUTION_HTML VERMONT_SECTION_HTML VERMONT_TOC_HTML
    VERMONT_CONSTITUTION_HTML VIRGINIA_SECTION_JSON VIRGINIA_TOC_HTML
    VIRGINIA_CONSTITUTION_HTML WASHINGTON_SECTION_HTML WASHINGTON_TOC_HTML
    WASHINGTON_CONSTITUTION_TEXT WEST_VIRGINIA_CODE_HTML
    WEST_VIRGINIA_CHAPTER_HTML WEST_VIRGINIA_CONSTITUTION_HTML
    WISCONSIN_CHAPTER_PDF_TEXT WISCONSIN_TOC_HTML WISCONSIN_CONSTITUTION_TEXT
    WYOMING_TITLE_TEXT WYOMING_TITLE_PDF WYOMING_TITLES_HTML
    WYOMING_CONSTITUTION_TEXT PUERTO_RICO_OGP_TEXT PUERTO_RICO_OGP_PDF
    """.split()
)
_STRICT_LOCAL_SELECTOR_SUFFIXES = (
    "_HTML",
    "_HTML_DIR",
    "_XML",
    "_JSON",
    "_TEXT",
    "_PDF",
    "_ZIP",
    "_RECEIPT",
    "_MANIFEST",
    "_INVENTORY_PATH",
    "_EVIDENCE_ROOT",
    "_EVIDENCE_DIR",
    "_CACHE_DIR",
)
_STRICT_STATE_SELECTOR_PREFIXES = (
    "ALABAMA_", "ALASKA_", "ARIZONA_", "ARKANSAS_", "CALIFORNIA_",
    "COLORADO_", "CONNECTICUT_", "DELAWARE_", "DISTRICT_OF_COLUMBIA_",
    "FLORIDA_", "GEORGIA_", "HAWAII_", "IDAHO_", "ILLINOIS_", "INDIANA_",
    "IOWA_", "KANSAS_", "KENTUCKY_", "LOUISIANA_", "MAINE_", "MARYLAND_",
    "MASSACHUSETTS_", "MICHIGAN_", "MINNESOTA_", "MISSISSIPPI_", "MISSOURI_",
    "MONTANA_", "NEBRASKA_", "NEVADA_", "NEW_HAMPSHIRE_", "NEW_JERSEY_",
    "NEW_MEXICO_", "NEW_YORK_", "NORTH_CAROLINA_", "NORTH_DAKOTA_", "OHIO_",
    "OKLAHOMA_", "OREGON_", "PENNSYLVANIA_", "RHODE_ISLAND_",
    "SOUTH_CAROLINA_", "SOUTH_DAKOTA_", "TENNESSEE_", "TEXAS_", "UTAH_",
    "VERMONT_", "VIRGINIA_", "WASHINGTON_", "WEST_VIRGINIA_", "WISCONSIN_",
    "WYOMING_", "PUERTO_RICO_",
) + tuple(f"{code}_" for code in STATE_CODES_51) + ("STATE_SCRAPER_",)


class SubsetReleaseError(ValueError):
    """Raised when a production release path is asked to publish a subset corpus."""


class LocalStateMaterializationError(RuntimeError):
    """Raised when a completed state cannot be persisted exactly and atomically."""


def _strict_ambient_selector_preflight_errors() -> List[str]:
    """Return configured ambient selectors that a sealed run cannot attest."""

    configured = {
        str(name)
        for name, value in os.environ.items()
        if str(value or "")
    }
    errors: List[str] = []
    explicit_denied = (
        _STRICT_SHARED_AMBIENT_SELECTOR_DENY
        | _STRICT_SOURCE_ROUTING_SELECTOR_DENY
        | _STRICT_LEGACY_LOCAL_SELECTOR_DENY
    )
    for name in sorted(configured & explicit_denied):
        errors.append(f"strict_evidence_forbids_ambient_selector:{name}")

    digest = str(
        os.environ.get("NEW_JERSEY_BULK_RETAINED_SHA256") or ""
    ).strip()
    if digest and re.fullmatch(r"[A-Fa-f0-9]{64}", digest) is None:
        errors.append(
            "strict_evidence_invalid_bound_selector:"
            "NEW_JERSEY_BULK_RETAINED_SHA256"
        )

    for name in sorted(configured):
        if (
            name in _BOUND_PRODUCTION_SELECTOR_ENV
            or name in explicit_denied
            or not name.startswith(_STRICT_STATE_SELECTOR_PREFIXES)
            or not name.endswith(_STRICT_LOCAL_SELECTOR_SUFFIXES)
        ):
            continue
        errors.append(f"strict_evidence_forbids_unrecognized_selector:{name}")
    return errors


def reject_subset_release(
    states: Sequence[str],
    *,
    context: str = "production release",
) -> List[str]:
    """Fail closed unless ``states`` is exactly the sealed 51-jurisdiction set.

    Legacy production entry points must never promote a requested-scope subset
    (including the historical 50-state ``all`` without DC) to a combined release.
    """
    normalized: List[str] = []
    seen = set()
    for item in states:
        code = str(item or "").strip().upper()
        if not code or code in seen:
            continue
        normalized.append(code)
        seen.add(code)
    observed = set(normalized)
    if observed != CANONICAL_PRODUCTION_JURISDICTIONS:
        missing = sorted(CANONICAL_PRODUCTION_JURISDICTIONS - observed)
        extra = sorted(observed - CANONICAL_PRODUCTION_JURISDICTIONS)
        raise SubsetReleaseError(
            f"subset release rejected for {context}: "
            f"count={len(observed)} (expected {EXPECTED_PRODUCTION_JURISDICTION_COUNT}); "
            f"missing={missing}; extra={extra}"
        )
    if "DC" not in observed:
        raise SubsetReleaseError(f"subset release rejected for {context}: DC is required")
    return normalized


def _complete_state_statuses() -> set[str]:
    """Return registry statuses that nominate prior-completion candidates.

    `zero_statutes` entries are recorded for observability, but by default they
    are *not* treated as completion candidates because they can indicate a
    transient scraper/source failure. Set
    `STATE_LAWS_REGISTRY_TREAT_ZERO_AS_COMPLETE=1` to restore the legacy
    candidate classification. Registry rows are never sufficient to skip a
    scrape; the shared acquisition coordinator must independently admit a
    digest-bound receipt against the local state output bytes.
    """

    statuses = {"success"}
    if str(os.getenv("STATE_LAWS_REGISTRY_TREAT_ZERO_AS_COMPLETE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        statuses.add("zero_statutes")
    return statuses


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def runner_source_software_version(
    *,
    require_loaded_source_correspondence: bool = True,
) -> str:
    """Return the content identity of the actually loaded refresh runner."""

    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        _assert_loaded_executables_match_current_source,
        _loaded_executable_sha256,
    )

    raw_path = Path(__file__)
    if raw_path.is_symlink() or not _RUNNER_SOURCE_PATH.is_file():
        raise RuntimeError("refresh runner source is not a regular file")
    current_sha256 = hashlib.sha256(_RUNNER_SOURCE_PATH.read_bytes()).hexdigest()
    if require_loaded_source_correspondence and (
        current_sha256 != MODULE_IMPORT_SOURCE_SHA256
    ):
        raise RuntimeError(
            "loaded refresh runner source bytes differ from current disk: "
            f"import={MODULE_IMPORT_SOURCE_SHA256}, current={current_sha256}"
        )

    loaded_module = types.ModuleType(__name__)
    loaded_module.__dict__.update(globals())
    canonical_module_name = "scripts.ops.legal_data.refresh_state_laws_corpus"
    loaded_sha256 = _loaded_executable_sha256(
        loaded_module,
        canonical_module_name=canonical_module_name,
    )
    record = {
        "target": loaded_module,
        "fresh_import_module": canonical_module_name,
        "fresh_import_file": str(_RUNNER_SOURCE_PATH),
        "source_path": str(_RUNNER_SOURCE_PATH),
        "import_source_sha256": MODULE_IMPORT_SOURCE_SHA256,
        "loaded_executable_sha256": loaded_sha256,
        "source_file_sha256": current_sha256,
        "canonical_module_name": canonical_module_name,
    }
    if require_loaded_source_correspondence:
        _assert_loaded_executables_match_current_source(
            {"scripts.ops.legal_data.refresh_state_laws_corpus": record}
        )
        if hashlib.sha256(_RUNNER_SOURCE_PATH.read_bytes()).hexdigest() != current_sha256:
            raise RuntimeError(
                "refresh runner source changed during correspondence verification"
            )

    digest = hashlib.sha256(
        json.dumps(
            {
                "schema_version": "state-laws-refresh-runner-source-bundle-v1",
                "import_source_sha256": MODULE_IMPORT_SOURCE_SHA256,
                "loaded_executable_sha256": loaded_sha256,
                "source_file_sha256": current_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return (
        "scripts.ops.legal_data.refresh_state_laws_corpus"
        f"@sha256:{digest}"
    )


def _is_content_addressed_source_software_identity(value: Any) -> bool:
    """Return whether ``value`` is a qualified SHA-256 source identity."""

    text = str(value or "").strip()
    prefix, marker, digest = text.rpartition("@sha256:")
    return bool(
        marker
        and prefix
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _registered_state_source_software_version(state_code: str) -> str:
    """Resolve one registered scraper identity from current local source bytes.

    This helper performs no network access.  A fresh scraper instance is used
    for every observation so an acquisition run cannot accidentally compare a
    cached identity with its start snapshot.
    """

    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        get_scraper_for_state,
    )

    code = str(state_code or "").strip().upper()
    if code not in US_STATES:
        raise ValueError(f"unknown registered jurisdiction {code!r}")
    scraper = get_scraper_for_state(code, US_STATES[code])
    if scraper is None:
        raise ValueError(f"no registered current scraper for jurisdiction {code}")
    version = str(
        scraper._state_law_frontier_source_software_version(
            require_loaded_source_correspondence=True,
        )
        or ""
    ).strip()
    if not _is_content_addressed_source_software_identity(version):
        raise ValueError(
            "registered scraper returned a non-content-addressed source "
            f"identity for {code}: {version!r}"
        )
    return version


def _capture_registered_state_source_software_versions(
    states: Sequence[str],
) -> tuple[Dict[str, str], Dict[str, str]]:
    """Capture current identities independently, retaining per-state errors."""

    versions: Dict[str, str] = {}
    errors: Dict[str, str] = {}
    seen: set[str] = set()
    for raw_state in states:
        state_code = str(raw_state or "").strip().upper()
        if not state_code or state_code in seen:
            continue
        seen.add(state_code)
        try:
            versions[state_code] = _registered_state_source_software_version(
                state_code
            )
        except Exception as exc:
            errors[state_code] = f"{type(exc).__name__}: {exc}"
    return versions, errors


def _verify_state_source_software_immutability(
    *,
    states: Sequence[str],
    start_identities: Mapping[str, str],
    phase: str,
) -> Dict[str, Any]:
    """Re-read registered source identities and exact-compare with run start."""

    normalized_states: List[str] = []
    seen: set[str] = set()
    for raw_state in states:
        state_code = str(raw_state or "").strip().upper()
        if not state_code or state_code in seen:
            continue
        normalized_states.append(state_code)
        seen.add(state_code)

    end_identities, capture_errors = (
        _capture_registered_state_source_software_versions(normalized_states)
    )
    verification_errors = dict(capture_errors)
    drift_states: List[str] = []
    state_checks: Dict[str, Dict[str, Any]] = {}
    for state_code in normalized_states:
        start_identity = str(start_identities.get(state_code) or "").strip()
        end_identity = str(end_identities.get(state_code) or "").strip()
        error = str(verification_errors.get(state_code) or "").strip()
        if not start_identity:
            error = error or "run-start source identity is missing"
            verification_errors[state_code] = error
        identities_equal = bool(
            start_identity and end_identity and not error and start_identity == end_identity
        )
        if not error and start_identity != end_identity:
            drift_states.append(state_code)
        state_check: Dict[str, Any] = {
            "start_identity": start_identity or None,
            "end_identity": end_identity or None,
            "identities_equal": identities_equal,
        }
        if error:
            state_check["verification_error"] = error
        state_checks[state_code] = state_check

    identities_equal = bool(
        normalized_states and not verification_errors and not drift_states
    )
    if verification_errors:
        status = "verification_error"
    elif drift_states:
        status = "source_drift_detected"
    else:
        status = "verified"
    return {
        "schema": _SOURCE_SOFTWARE_IMMUTABILITY_SCHEMA,
        "phase": str(phase or "verification"),
        "status": status,
        "checked_at": _utc_now_iso(),
        "states": normalized_states,
        "state_count": len(normalized_states),
        "start_identities": {
            state_code: str(start_identities.get(state_code) or "").strip()
            for state_code in normalized_states
            if str(start_identities.get(state_code) or "").strip()
        },
        "end_identities": end_identities,
        "state_checks": state_checks,
        "identities_equal": identities_equal,
        "drift_states": drift_states,
        "verification_errors": verification_errors,
        "authorizing_for_publication": identities_equal,
    }


def _source_software_immutability_failure_detail(
    verification: Mapping[str, Any],
) -> str:
    """Build a stable fail-closed diagnostic for one verification report."""

    drift_states = [
        str(item).strip().upper()
        for item in list(verification.get("drift_states") or [])
        if str(item).strip()
    ]
    raw_errors = verification.get("verification_errors")
    errors = dict(raw_errors) if isinstance(raw_errors, Mapping) else {}
    details: List[str] = []
    if drift_states:
        details.append(f"source identity drift for {drift_states}")
    if errors:
        details.append(
            "identity verification errors="
            + json.dumps(errors, sort_keys=True, ensure_ascii=False)
        )
    return (
        "state-law acquisition source-software immutability gate failed: "
        + ("; ".join(details) if details else "identity equality was not proven")
    )


def _block_acquisition_evidence_for_source_software_drift(
    evidence_value: Any,
    *,
    verification: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return an explicitly non-authorizing evidence projection."""

    evidence = dict(evidence_value) if isinstance(evidence_value, Mapping) else {}
    raw_aggregate = evidence.get("aggregate")
    aggregate = dict(raw_aggregate) if isinstance(raw_aggregate, Mapping) else {}
    aggregate.update(
        {
            "status": "blocked_source_software_immutability",
            "authorizing_for_publication": False,
            "source_software_immutability_verified": False,
        }
    )
    evidence["aggregate"] = aggregate
    evidence["normalized_source_receipt_usable"] = False
    evidence["source_software_immutability"] = dict(verification)
    return evidence


def _write_nonquiescent_evidence_marker(
    evidence_root: Path,
    *,
    run_id: str,
    state_code: str,
    worker_quiescence: Mapping[str, Any] | None,
) -> Path:
    """Permanently poison a root that a live timed-out worker may mutate."""

    payload = {
        "schema": "ipfs_datasets_py.state_laws_refresh.nonquiescent_evidence.v1",
        "run_id": str(run_id),
        "created_at": _utc_now_iso(),
        "state_code": str(state_code or "").strip().upper(),
        "worker_quiescence": dict(worker_quiescence or {}),
        "reason": "worker remained live after the acquisition timeout",
        "authorizing_for_publication": False,
        "permanently_nonauthorizing": True,
    }
    return _install_permanent_nonauthorization_marker(
        evidence_root,
        payload=payload,
    )


def _install_permanent_nonauthorization_marker(
    evidence_root: Path,
    *,
    payload: Mapping[str, Any],
) -> Path:
    """Install the first permanent root poison without replacing evidence."""

    unresolved_root = Path(evidence_root).expanduser()
    if unresolved_root.is_symlink():
        raise RuntimeError("acquisition evidence root must not be a symlink")
    root = unresolved_root.resolve()
    if not root.is_dir():
        raise RuntimeError("acquisition evidence root must be a directory")
    target = root / NONQUIESCENT_EVIDENCE_MARKER
    marker_bytes = canonical_json_bytes(dict(payload))
    open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, open_flags, 0o600)
    except FileExistsError:
        if target.is_symlink() or not target.is_file():
            raise RuntimeError(
                "permanent nonauthorization marker exists but is unsafe"
            )
        return target
    try:
        offset = 0
        while offset < len(marker_bytes):
            written = os.write(descriptor, marker_bytes[offset:])
            if written <= 0:
                raise OSError(
                    "short write while installing permanent nonauthorization marker"
                )
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    directory_descriptor = os.open(root, directory_flags)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    installed_size, installed_digest = file_digest(target)
    expected_digest = hashlib.sha256(marker_bytes).hexdigest()
    if (
        installed_size != len(marker_bytes)
        or installed_digest.hex() != expected_digest
    ):
        raise RuntimeError("installed permanent nonauthorization marker changed")
    return target


def _write_source_software_immutability_evidence_marker(
    evidence_root: Path,
    *,
    run_id: str,
    failure_reasons: Mapping[str, Any],
) -> Path:
    """Permanently fence a root after post-worker source identity failure."""

    reasons = {
        str(state or "").strip().upper(): str(reason or "").strip()
        for state, reason in failure_reasons.items()
        if str(state or "").strip()
    }
    if not reasons:
        raise RuntimeError(
            "source-software permanent nonauthorization requires a failed state"
        )
    payload = {
        "schema": (
            "ipfs_datasets_py.state_laws_refresh."
            "source_software_immutability_permanent_nonauthorization.v1"
        ),
        "run_id": str(run_id),
        "created_at": _utc_now_iso(),
        "failed_states": sorted(reasons),
        "failure_reasons": dict(sorted(reasons.items())),
        "reason": (
            "source-software immutability verification failed after state "
            "worker execution"
        ),
        "authorizing_for_publication": False,
        "permanently_nonauthorizing": True,
    }
    return _install_permanent_nonauthorization_marker(
        evidence_root,
        payload=payload,
    )


def _write_acquisition_in_progress_marker(
    evidence_root: Path,
    *,
    run_id: str,
    active_states: Sequence[str],
) -> tuple[Path, str]:
    """Acquire a durable, exclusive non-authorizing lease on an evidence root."""

    root = Path(evidence_root).expanduser().resolve()
    target = root / IN_PROGRESS_EVIDENCE_MARKER
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "ipfs_datasets_py.state_laws_refresh.in_progress.v1",
        "run_id": str(run_id),
        "created_at": _utc_now_iso(),
        "active_states": [str(state).strip().upper() for state in active_states],
        "authorizing_for_publication": False,
        "in_progress": True,
    }
    expected_bytes = canonical_json_bytes(payload)
    open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, open_flags, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(
            "the acquisition evidence root already has an in-progress lease"
        ) from exc
    try:
        offset = 0
        while offset < len(expected_bytes):
            written = os.write(descriptor, expected_bytes[offset:])
            if written <= 0:
                raise OSError("short write while installing acquisition lease")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory_descriptor = os.open(root, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    installed_size, installed_digest = file_digest(target)
    expected_digest = hashlib.sha256(expected_bytes).hexdigest()
    if installed_size != len(expected_bytes) or installed_digest.hex() != expected_digest:
        raise RuntimeError("installed acquisition in-progress marker changed")
    return target, expected_digest


def _verify_acquisition_in_progress_marker(
    marker_path: Path,
    *,
    run_id: str,
    expected_sha256: str,
) -> None:
    """Fail unless this run still exclusively owns its durable root lease."""

    target = Path(marker_path)
    if target.is_symlink() or not target.is_file():
        raise RuntimeError("acquisition in-progress marker is absent or unsafe")
    marker_bytes = target.read_bytes()
    if hashlib.sha256(marker_bytes).hexdigest() != str(expected_sha256):
        raise RuntimeError("acquisition in-progress marker bytes changed")
    payload = json.loads(marker_bytes.decode("utf-8", errors="strict"))
    if not isinstance(payload, Mapping) or payload.get("run_id") != str(run_id):
        raise RuntimeError("acquisition in-progress marker owner changed")
    if payload.get("in_progress") is not True:
        raise RuntimeError("acquisition in-progress marker is not active")


@contextmanager
def _state_scraper_run_environment(
    *,
    output_root: Path,
    full_corpus: bool,
    acquisition_evidence_root: Path | None = None,
    strict_acquisition_evidence: bool = False,
    retained_replay_only: bool = False,
) -> Iterator[None]:
    """Apply and restore scraper scope for every initial or recovery pass."""

    previous_full_corpus = os.environ.get("STATE_SCRAPER_FULL_CORPUS")
    previous_checkpoint_dir = os.environ.get("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR")
    previous_evidence_root = os.environ.get(MULTIFETCH_EVIDENCE_ROOT_ENV)
    previous_strict_evidence = os.environ.get(STRICT_MULTIFETCH_EVIDENCE_ENV)
    previous_retained_replay_only = os.environ.get(RETAINED_REPLAY_ONLY_ENV)
    os.environ["STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR"] = str(
        output_root / "partial_checkpoints"
    )
    if full_corpus:
        os.environ["STATE_SCRAPER_FULL_CORPUS"] = "1"
    if acquisition_evidence_root is not None:
        os.environ[MULTIFETCH_EVIDENCE_ROOT_ENV] = str(
            Path(acquisition_evidence_root).expanduser().resolve()
        )
    else:
        os.environ.pop(MULTIFETCH_EVIDENCE_ROOT_ENV, None)
    if strict_acquisition_evidence:
        os.environ[STRICT_MULTIFETCH_EVIDENCE_ENV] = "1"
    else:
        os.environ.pop(STRICT_MULTIFETCH_EVIDENCE_ENV, None)
    if retained_replay_only:
        os.environ[RETAINED_REPLAY_ONLY_ENV] = "1"
    else:
        os.environ.pop(RETAINED_REPLAY_ONLY_ENV, None)
    try:
        yield
    finally:
        if full_corpus:
            if previous_full_corpus is None:
                os.environ.pop("STATE_SCRAPER_FULL_CORPUS", None)
            else:
                os.environ["STATE_SCRAPER_FULL_CORPUS"] = previous_full_corpus
        if previous_checkpoint_dir is None:
            os.environ.pop("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", None)
        else:
            os.environ["STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR"] = (
                previous_checkpoint_dir
            )
        if previous_evidence_root is None:
            os.environ.pop(MULTIFETCH_EVIDENCE_ROOT_ENV, None)
        else:
            os.environ[MULTIFETCH_EVIDENCE_ROOT_ENV] = previous_evidence_root
        if previous_strict_evidence is None:
            os.environ.pop(STRICT_MULTIFETCH_EVIDENCE_ENV, None)
        else:
            os.environ[STRICT_MULTIFETCH_EVIDENCE_ENV] = previous_strict_evidence
        if previous_retained_replay_only is None:
            os.environ.pop(RETAINED_REPLAY_ONLY_ENV, None)
        else:
            os.environ[RETAINED_REPLAY_ONLY_ENV] = previous_retained_replay_only


def _canonical_completed_states_registry_path() -> Path:
    env_override = str(os.getenv("STATE_LAWS_COMPLETED_STATES_REGISTRY_PATH", "") or "").strip()
    if env_override:
        return Path(env_override).expanduser().resolve()
    canonical_root = Path(_CORPUS.default_local_root()).expanduser().resolve()
    return canonical_root / "state_laws_completed_states.json"


def _uses_shared_completed_registry(output_root: Path) -> bool:
    try:
        resolved_output = Path(output_root).expanduser().resolve()
    except Exception:
        return False
    canonical_root = Path(_CORPUS.default_local_root()).expanduser().resolve()
    if resolved_output == canonical_root:
        return True
    parts = {part.lower() for part in resolved_output.parts}
    if "legal_scraper_parallel" in parts and resolved_output.name.lower() == "output":
        return True
    return False


def _default_completed_states_registry_path(output_root: Path) -> Path:
    # Use a shared registry for canonical corpus output roots and daemon shard
    # outputs, but keep ad-hoc/custom output roots isolated.
    if _uses_shared_completed_registry(output_root):
        return _canonical_completed_states_registry_path()
    return Path(output_root).expanduser().resolve() / "state_laws_completed_states.json"


def _default_completed_states_baseline_path() -> Path:
    env_override = str(os.getenv("STATE_LAWS_COMPLETED_STATES_BASELINE_PATH", "") or "").strip()
    if env_override:
        return Path(env_override).expanduser().resolve()
    return Path(__file__).resolve().with_name("state_laws_completed_states.baseline.json")


def _empty_completed_states_registry() -> Dict[str, Any]:
    return {
        "schema": _COMPLETED_STATES_SCHEMA,
        "updated_at": "",
        "states": {},
    }


def _normalize_completed_states_registry(payload: Any) -> Dict[str, Any]:
    normalized = _empty_completed_states_registry()
    if not isinstance(payload, Mapping):
        return normalized

    allowed_states = set(US_STATES)
    raw_states = payload.get("states")
    if not isinstance(raw_states, Mapping):
        raw_states = {}

    normalized_states: Dict[str, Dict[str, Any]] = {}
    for raw_code, raw_entry in raw_states.items():
        state_code = str(raw_code or "").strip().upper()
        if not state_code or state_code not in allowed_states:
            continue
        if not isinstance(raw_entry, Mapping):
            continue
        status = str(raw_entry.get("status") or "").strip().lower()
        if status not in _REGISTRY_RECORDABLE_STATE_STATUSES:
            continue
        entry: Dict[str, Any] = {"status": status}
        completed_at = str(raw_entry.get("completed_at") or "").strip()
        if completed_at:
            entry["completed_at"] = completed_at
        first_completed_at = str(raw_entry.get("first_completed_at") or "").strip()
        if first_completed_at:
            entry["first_completed_at"] = first_completed_at
        updated_at = str(raw_entry.get("updated_at") or "").strip()
        if updated_at:
            entry["updated_at"] = updated_at
        try:
            statutes_count = int(raw_entry.get("statutes_count") or 0)
        except Exception:
            statutes_count = 0
        entry["statutes_count"] = statutes_count
        for key in ("output_root", "source_progress_path"):
            value = str(raw_entry.get(key) or "").strip()
            if value:
                entry[key] = value
        for key in ("completion_mode", "timeout_classification", "timeout_signal_kind", "timeout_original_error"):
            value = str(raw_entry.get(key) or "").strip()
            if value:
                entry[key] = value
        timeout_work_remaining = raw_entry.get("timeout_work_remaining")
        if isinstance(timeout_work_remaining, bool):
            entry["timeout_work_remaining"] = timeout_work_remaining
        timeout_promoted = raw_entry.get("timeout_promoted_to_success")
        if isinstance(timeout_promoted, bool):
            entry["timeout_promoted_to_success"] = timeout_promoted
        normalized_states[state_code] = entry

    normalized["states"] = dict(sorted(normalized_states.items()))
    normalized["updated_at"] = str(payload.get("updated_at") or "").strip()
    return normalized


def _load_completed_states_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_completed_states_registry()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_completed_states_registry()
    return _normalize_completed_states_registry(payload)


def _write_completed_states_registry(path: Path, registry: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_completed_states_registry(registry)
    normalized["updated_at"] = _utc_now_iso()
    path.write_text(
        json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _merge_completed_states_registries(
    *,
    base_registry: Mapping[str, Any],
    overlay_registry: Mapping[str, Any],
) -> Dict[str, Any]:
    base = _normalize_completed_states_registry(base_registry)
    overlay = _normalize_completed_states_registry(overlay_registry)
    merged = _empty_completed_states_registry()

    base_states = base.get("states") if isinstance(base.get("states"), Mapping) else {}
    overlay_states = overlay.get("states") if isinstance(overlay.get("states"), Mapping) else {}
    states_map: Dict[str, Dict[str, Any]] = {}
    for state_code, entry in base_states.items():
        if isinstance(entry, Mapping):
            states_map[str(state_code)] = dict(entry)
    for state_code, entry in overlay_states.items():
        if isinstance(entry, Mapping):
            states_map[str(state_code)] = dict(entry)

    merged["states"] = dict(sorted(states_map.items()))
    merged["updated_at"] = str(overlay.get("updated_at") or base.get("updated_at") or "").strip()
    return merged


def _completed_states_to_skip(states: Sequence[str], registry: Mapping[str, Any]) -> List[str]:
    """Return registry completion candidates, not authoritative skip evidence."""

    complete_statuses = _complete_state_statuses()
    entries = registry.get("states")
    if not isinstance(entries, Mapping):
        return []
    skipped: List[str] = []
    for state in states:
        entry = entries.get(state)
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status") or "").strip().lower()
        if status in complete_statuses:
            skipped.append(state)
    return skipped


def _completed_states_missing_canonical_jsonld(
    *,
    states: Sequence[str],
    jsonld_dir: Path,
) -> List[str]:
    missing: List[str] = []
    for state in states:
        state_code = str(state or "").strip().upper()
        if not state_code:
            continue
        state_jsonld = Path(jsonld_dir).expanduser().resolve() / f"STATE-{state_code}.jsonld"
        if not state_jsonld.exists():
            missing.append(state_code)
    return missing


def _validate_staged_state_jsonld(
    path: Path,
    *,
    state_code: str,
    expected_rows: int | None,
) -> int:
    """Validate one standard-writer output without materializing its rows."""

    observed_rows = 0
    try:
        for payload in iter_jsonl(path):
            embedded_code = str(payload.get("stateCode") or "").strip().upper()
            if embedded_code and embedded_code != state_code:
                raise LocalStateMaterializationError(
                    f"staged JSON-LD stateCode={embedded_code!r} does not match "
                    f"{state_code}"
                )
            jurisdiction = str(
                payload.get("legislationJurisdiction") or ""
            ).strip().upper()
            if jurisdiction and jurisdiction != f"US-{state_code}":
                raise LocalStateMaterializationError(
                    f"staged JSON-LD legislationJurisdiction={jurisdiction!r} "
                    f"does not match US-{state_code}"
                )
            observed_rows += 1
    except LocalStateMaterializationError:
        raise
    except Exception as exc:
        raise LocalStateMaterializationError(
            f"cannot validate staged JSON-LD for {state_code}: {exc}"
        ) from exc

    if observed_rows <= 0:
        raise LocalStateMaterializationError(
            f"state JSON-LD for {state_code} contains no object rows"
        )
    if expected_rows is not None and observed_rows != expected_rows:
        raise LocalStateMaterializationError(
            f"standard JSON-LD writer row-count mismatch for {state_code}: "
            f"expected={expected_rows}, observed={observed_rows}"
        )
    return observed_rows


def _relative_artifact_label(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        # Receipts deliberately avoid embedding machine-specific absolute paths.
        return path.name


def _materialize_completed_state_locally(
    *,
    state_code: str,
    state_name: str,
    statute_data: Mapping[str, Any],
    statutes_count: int,
    output_root: Path,
    jsonld_dir: Path,
    full_corpus_requested: bool,
    max_statutes: Optional[int],
) -> Dict[str, Any]:
    """Atomically persist one successful callback payload and a local receipt.

    The receipt is intentionally diagnostic and non-authorizing.  Restart reuse
    still requires an independent receipt that the shared acquisition
    coordinator admits after checking the exact JSON-LD bytes and a replayed,
    closed official-source frontier.
    """

    code = str(state_code or "").strip().upper()
    if code not in US_STATES:
        raise LocalStateMaterializationError(
            f"cannot materialize unknown jurisdiction {state_code!r}"
        )
    if type(statutes_count) is not int or statutes_count <= 0:
        raise LocalStateMaterializationError(
            f"successful {code} materialization requires a positive exact row count"
        )
    if not isinstance(statute_data, Mapping):
        raise LocalStateMaterializationError(
            f"successful {code} callback has no normalized statute_data mapping"
        )
    payload_code = str(statute_data.get("state_code") or "").strip().upper()
    if payload_code and payload_code != code:
        raise LocalStateMaterializationError(
            f"callback state_code mismatch for {code}: {payload_code!r}"
        )
    statutes = statute_data.get("statutes")
    if not isinstance(statutes, list):
        raise LocalStateMaterializationError(
            f"successful {code} callback statutes must be a list"
        )
    if len(statutes) != statutes_count:
        raise LocalStateMaterializationError(
            f"callback statute count mismatch for {code}: "
            f"declared={statutes_count}, observed={len(statutes)}"
        )

    filename = f"STATE-{code}.jsonld"
    normalized_block = dict(statute_data)
    normalized_block["state_code"] = code
    normalized_block["state_name"] = str(
        state_name or statute_data.get("state_name") or US_STATES[code]
    ).strip()
    normalized_block["statutes"] = statutes

    output_path = jsonld_dir / filename
    if output_path.is_symlink():
        raise LocalStateMaterializationError(
            f"refusing to replace symlink canonical JSON-LD for {code}"
        )

    artifact_disposition = "installed_callback_artifact"
    prior_rows: int | None = None
    prior_size: int | None = None
    prior_digest: bytes | None = None
    if output_path.is_file():
        try:
            prior_rows = _validate_staged_state_jsonld(
                output_path,
                state_code=code,
                expected_rows=None,
            )
            prior_size, prior_digest = file_digest(output_path)
        except Exception:
            # Invalid prior output is not eligible for the legacy
            # "keep the larger shard" behavior.  The fully validated callback
            # artifact below may replace it atomically.
            prior_rows = None
            prior_size = None
            prior_digest = None
            artifact_disposition = "replaced_invalid_prior_artifact"

    with atomic_staging(
        jsonld_dir,
        prefix=f".state-laws-{code.lower()}-incremental-",
    ) as stage:
        written = _write_state_jsonld_files([normalized_block], stage.path)
        staged_path = stage.confine(filename)
        if written != [str(staged_path)] or not staged_path.is_file():
            raise LocalStateMaterializationError(
                f"standard JSON-LD writer did not emit {filename}"
            )
        output_rows = _validate_staged_state_jsonld(
            staged_path,
            state_code=code,
            expected_rows=statutes_count,
        )
        staged_size, staged_digest = file_digest(staged_path)

        # Match the established state JSON-LD writer's best-known-output rule:
        # a smaller retry or bounded probe must not destroy a larger valid
        # canonical shard.  The staged callback bytes are still independently
        # described in the diagnostic receipt below.
        if prior_rows is not None and prior_rows > output_rows:
            artifact_disposition = "preserved_larger_prior_artifact"
            installed_expected_size = prior_size
            installed_expected_digest = prior_digest
        else:
            output_path = stage.commit_file(filename, overwrite=True)
            installed_expected_size = staged_size
            installed_expected_digest = staged_digest

    installed_size, installed_digest = file_digest(output_path)
    if (installed_size, installed_digest) != (
        installed_expected_size,
        installed_expected_digest,
    ):
        raise LocalStateMaterializationError(
            f"installed JSON-LD digest changed during materialization for {code}"
        )
    installed_rows = (
        int(prior_rows)
        if artifact_disposition == "preserved_larger_prior_artifact"
        else output_rows
    )

    checkpoint_path = output_root / "partial_checkpoints" / f"STATE-{code}-partial.json"
    checkpoint_descriptor: Dict[str, Any] = {
        "present": False,
        "authorizing_frontier_closure": False,
    }
    if checkpoint_path.is_file() and not checkpoint_path.is_symlink():
        checkpoint_size, checkpoint_digest = file_digest(checkpoint_path)
        checkpoint_descriptor = {
            "present": True,
            "relative_path": _relative_artifact_label(
                checkpoint_path,
                root=output_root,
            ),
            "sha256": checkpoint_digest.hex(),
            "size_bytes": checkpoint_size,
            # A digest of the scraper checkpoint aids recovery, but is not a
            # substitute for the coordinator's official-source receipt gates.
            "authorizing_frontier_closure": False,
        }

    receipt_path = (
        output_root
        / "receipts"
        / f"STATE-{code}-incremental-local-materialization.json"
    )
    receipt = {
        "schema": _LOCAL_MATERIALIZATION_RECEIPT_SCHEMA,
        "status": "materialized",
        "jurisdiction": code,
        "state_name": normalized_block["state_name"],
        "operation": "incremental_local_jsonld_materialization",
        "materialized_at": _utc_now_iso(),
        "network_access_during_materialization": False,
        "huggingface_access_during_materialization": False,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "authorizing_coordinator_reuse": False,
        "coordinator_reuse_requires_independent_receipt": True,
        "scope": {
            "mode": "full" if full_corpus_requested else "bounded",
            "max_statutes": None if full_corpus_requested else max_statutes,
        },
        "artifact_disposition": artifact_disposition,
        "callback_artifact": {
            "row_count": output_rows,
            "sha256": staged_digest.hex(),
            "size_bytes": staged_size,
            "installed_as_canonical": (
                artifact_disposition != "preserved_larger_prior_artifact"
            ),
        },
        "source_checkpoint": checkpoint_descriptor,
        "output_artifact": {
            "relative_path": _relative_artifact_label(output_path, root=output_root),
            "media_type": "application/x-ndjson",
            "row_count": installed_rows,
            "sha256": installed_digest.hex(),
            "size_bytes": installed_size,
        },
    }
    atomic_write_canonical_json(receipt_path, receipt)
    receipt_size, receipt_digest = file_digest(receipt_path)
    return {
        "status": "success",
        "state": code,
        "jsonld_path": str(output_path),
        "jsonld_sha256": installed_digest.hex(),
        "jsonld_size_bytes": installed_size,
        "row_count": installed_rows,
        "callback_row_count": output_rows,
        "callback_jsonld_sha256": staged_digest.hex(),
        "callback_jsonld_size_bytes": staged_size,
        "artifact_disposition": artifact_disposition,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_digest.hex(),
        "receipt_size_bytes": receipt_size,
        "authorizing_coordinator_reuse": False,
        "authorizing_for_publication": False,
    }


def _close_incremental_state_acquisition_aggregate(
    *,
    state_code: str,
    state_result: Mapping[str, Any],
    materialization_result: Mapping[str, Any] | None,
    acquisition_evidence_root: Path | None,
    strict: bool,
    defer_normalized_receipt: bool = False,
) -> tuple[Dict[str, Any], str]:
    """Close a retained multi-fetch ledger after exact JSON-LD materialization.

    A scraper/source enumerator must prospectively retain a content-addressed
    closure projection and hand its exact path through acquisition evidence.
    Missing input stays explicitly pending in diagnostic mode and is an error
    in strict mode; a local checkpoint/materialization receipt is never
    substituted for the source frontier.
    """

    statute_data = (
        state_result.get("statute_data")
        if isinstance(state_result.get("statute_data"), Mapping)
        else {}
    )
    raw_evidence = state_result.get("acquisition_evidence")
    if not isinstance(raw_evidence, Mapping):
        raw_evidence = statute_data.get("acquisition_evidence")
    evidence = dict(raw_evidence) if isinstance(raw_evidence, Mapping) else {}
    aggregate = dict(evidence.get("aggregate") or {})
    evidence["aggregate"] = aggregate

    def _blocked(status: str, detail: str) -> tuple[Dict[str, Any], str]:
        aggregate.update(
            {
                "authorizing_for_publication": False,
                "detail": detail,
                "status": status,
            }
        )
        evidence["all_fetch_coverage_claimed"] = False
        return evidence, detail if strict else ""

    if acquisition_evidence_root is None or evidence.get("enabled") is not True:
        if strict:
            return _blocked(
                "blocked_unattached",
                f"{state_code} strict acquisition ledger was not attached",
            )
        return evidence, ""
    if evidence.get("aggregate_eligible") is not True:
        blockers = list(evidence.get("eligibility_blockers") or [])
        return _blocked(
            "blocked_before_materialization",
            f"{state_code} acquisition aggregate is ineligible: {blockers}",
        )
    if not isinstance(materialization_result, Mapping):
        return _blocked(
            "pending_canonical_materialization",
            f"{state_code} canonical JSON-LD was not materialized",
        )

    from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
        StateLawMultiFetchAcquisitionLedger,
    )

    parser_name = str(evidence.get("parser_name") or "").strip()
    if not parser_name:
        return _blocked(
            "blocked_invalid_runner_projection",
            f"{state_code} acquisition evidence omitted parser_name",
        )
    ledger = StateLawMultiFetchAcquisitionLedger(
        acquisition_evidence_root,
        jurisdiction=state_code,
        parser_name=parser_name,
    )
    closure_input_value = str(evidence.get("closure_input_path") or "").strip()
    if not closure_input_value:
        return _blocked(
            "pending_source_frontier_replay",
            f"{state_code} source frontier closure input is missing",
        )
    canonical_path = str(materialization_result.get("jsonld_path") or "").strip()
    try:
        closure_input_path = ledger.resolve_frontier_closure_projection_path(
            closure_input_value
        )
        evidence["closure_input_path"] = str(closure_input_path)
        closed = ledger.close_from_projection_file(
            closure_input_path,
            canonical_jsonld_path=canonical_path,
            defer_normalized_receipt=defer_normalized_receipt,
        )
    except Exception as exc:
        return _blocked(
            "source_frontier_closure_rejected",
            f"{state_code} source frontier closure rejected: "
            f"{type(exc).__name__}: {exc}",
        )

    aggregate.update(
        {
            "authorizing_for_publication": not defer_normalized_receipt,
            "byte_verification_ok": bool(closed.byte_verification.ok),
            "canonical_jsonld_row_count": int(
                closed.receipt.get("canonical_row_count") or 0
            ),
            "canonical_jsonld_sha256": str(
                closed.receipt.get("canonical_artifact_sha256") or ""
            ),
            "frontier_verification_ok": bool(closed.frontier_verification.ok),
            "normalized_source_receipt_path": str(closed.normalized_receipt_path),
            "receipt_path": str(closed.receipt_path),
            "status": (
                "closed_pending_run_seal"
                if defer_normalized_receipt
                else "closed_and_normalized"
            ),
        }
    )
    evidence["all_fetch_coverage_claimed"] = True
    evidence["normalized_source_receipt_usable"] = not defer_normalized_receipt
    return evidence, ""


def _prefill_state_results_from_verified_receipts(
    *,
    states: Sequence[str],
    coordination_by_state: Mapping[str, CoordinationPlan],
) -> Dict[str, Dict[str, Any]]:
    """Build progress rows only for coordinator-admitted prior outputs."""
    prefilled: Dict[str, Dict[str, Any]] = {}
    for state in states:
        coordination = coordination_by_state.get(state)
        if coordination is None:
            continue
        accepted = {
            admission.jurisdiction_code: admission
            for admission in coordination.admissions
            if admission.accepted
        }
        admission = accepted.get(state)
        if admission is None:
            continue
        lease = coordination.lease_for(state)
        byte_verification = admission.byte_verification
        frontier_verification = admission.frontier_verification
        if not (
            lease.action == ACTION_REUSE
            and lease.prior_receipt_accepted
            and lease.byte_verified
            and lease.frontier_verified
            and byte_verification is not None
            and byte_verification.ok
            and byte_verification.raw_bytes_checked
            and frontier_verification is not None
            and frontier_verification.ok
            and frontier_verification.closed
        ):
            continue
        prefilled[state] = {
            "state_code": state,
            "status": "success",
            "statutes_count": int(admission.row_count or 0),
            "completed_at": "",
            "skip_reason": "verified_prior_receipt_reuse",
            "prior_receipt_accepted": True,
            "local_output_bytes_verified": True,
            "frontier_verified": True,
        }
    return prefilled


def _merge_completed_states_registry(
    *,
    existing_registry: Mapping[str, Any],
    state_results: Mapping[str, Any],
    output_root: Path,
    progress_path: Path,
) -> Dict[str, Any]:
    merged = _normalize_completed_states_registry(existing_registry)
    states_map = dict(merged.get("states") or {})
    now = _utc_now_iso()
    for state_code, raw_entry in state_results.items():
        code = str(state_code or "").strip().upper()
        if code not in US_STATES or not isinstance(raw_entry, Mapping):
            continue
        status = str(raw_entry.get("status") or "").strip().lower()
        if status not in _REGISTRY_RECORDABLE_STATE_STATUSES:
            continue
        prior = states_map.get(code) if isinstance(states_map.get(code), Mapping) else {}
        try:
            statutes_count = int(raw_entry.get("statutes_count") or 0)
        except Exception:
            statutes_count = 0
        completed_at = str(raw_entry.get("completed_at") or "").strip() or now
        entry: Dict[str, Any] = {
            "status": status,
            "statutes_count": statutes_count,
            "completed_at": completed_at,
            "first_completed_at": str(prior.get("first_completed_at") or completed_at),
            "updated_at": now,
            "output_root": str(output_root),
            "source_progress_path": str(progress_path),
        }
        for key in ("completion_mode", "timeout_classification", "timeout_signal_kind", "timeout_original_error"):
            value = str(raw_entry.get(key) or "").strip()
            if value:
                entry[key] = value
        timeout_work_remaining = raw_entry.get("timeout_work_remaining")
        if isinstance(timeout_work_remaining, bool):
            entry["timeout_work_remaining"] = timeout_work_remaining
        timeout_promoted = raw_entry.get("timeout_promoted_to_success")
        if isinstance(timeout_promoted, bool):
            entry["timeout_promoted_to_success"] = timeout_promoted
        states_map[code] = entry
    merged["states"] = dict(sorted(states_map.items()))
    merged["updated_at"] = now
    return merged


def _reconcile_state_results_from_partial_checkpoints(
    *,
    progress_state: Dict[str, Any],
    checkpoint_dir: Path,
    strict_acquisition_evidence: bool = False,
) -> Dict[str, Any]:
    """Promote terminal checkpoint-complete states that timed out in callback flow.

    Some long-running state scrapes can exceed the callback timeout envelope yet
    finish shortly after in their worker thread, leaving a final
    `STATE-XX-partial.json` with stage `...complete` and larger statute counts.
    This reconciliation pass converts those stale timeout/error rows into
    success so completed states are not retried forever.
    """

    if strict_acquisition_evidence:
        # Parser-complete checkpoints do not contain the retained replay and
        # closure projection required by strict acquisition.  The callback's
        # lifecycle result is the only result eligible for strict success.
        return {
            "reconciled_states": [],
            "checked_state_count": 0,
            "reconciled_count": 0,
            "disabled_reason": "strict_acquisition_requires_lifecycle_completion",
        }

    results = progress_state.get("state_results")
    if not isinstance(results, dict):
        results = {}
        progress_state["state_results"] = results

    reconciled_states: List[Dict[str, Any]] = []
    rejected_states: Dict[str, str] = {}
    checked_state_count = 0
    checkpoint_root = Path(checkpoint_dir).expanduser().resolve()
    checkpoint_states: set[str] = set()
    try:
        for checkpoint_path in checkpoint_root.glob("STATE-*-partial.json"):
            stem = str(checkpoint_path.stem or "")
            if not stem.startswith("STATE-") or not stem.endswith("-partial"):
                continue
            state_code = stem[len("STATE-") : -len("-partial")].strip().upper()
            if state_code:
                checkpoint_states.add(state_code)
    except Exception:
        checkpoint_states = set()

    candidate_states: List[str] = []
    seen_states: set[str] = set()
    for state_code in list(results.keys()) + sorted(checkpoint_states):
        state = str(state_code or "").strip().upper()
        if not state or state in seen_states:
            continue
        seen_states.add(state)
        candidate_states.append(state)

    for state_code in candidate_states:
        entry = results.get(state_code)
        if entry is None:
            entry = {
                "state_code": state_code,
                "state_name": US_STATES.get(state_code, state_code),
                "status": "missing",
                "statutes_count": 0,
            }
            results[state_code] = entry
        if not isinstance(entry, dict):
            continue
        checked_state_count += 1
        identity_gate = entry.get("source_software_immutability")
        worker_gate = entry.get("worker_quiescence")
        if not (
            isinstance(identity_gate, Mapping)
            and identity_gate.get("run_gate_passed") is True
        ):
            # A parser checkpoint proves neither the loaded producer identity
            # nor worker termination.  Missing attestation is never upgraded.
            rejected_states[state_code] = (
                "missing_source_software_run_attestation"
            )
            continue
        if not (
            isinstance(worker_gate, Mapping)
            and worker_gate.get("attested") is True
            and worker_gate.get("quiescent") is True
        ):
            rejected_states[state_code] = "missing_worker_quiescence_attestation"
            continue
        status = str(entry.get("status") or "").strip().lower()
        if status not in {"error", "zero_statutes", "running", "started", "missing", ""}:
            continue

        checkpoint_path = checkpoint_root / f"STATE-{str(state_code or '').upper()}-partial.json"
        if not checkpoint_path.exists():
            continue
        try:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, Mapping):
            continue

        stage_label = str(payload.get("stage_label") or "").strip()
        stage_label_lower = stage_label.lower()
        progress = payload.get("progress") if isinstance(payload.get("progress"), Mapping) else {}
        try:
            checkpoint_statutes_count = int(payload.get("statutes_count") or len(list(payload.get("statutes") or [])))
        except Exception:
            checkpoint_statutes_count = 0
        try:
            prior_count = int(entry.get("statutes_count") or 0)
        except Exception:
            prior_count = 0

        try:
            codes_completed = int(progress.get("codes_completed") or payload.get("codes_completed") or 0)
        except Exception:
            codes_completed = 0
        try:
            codes_total = int(progress.get("codes_total") or payload.get("codes_total") or 0)
        except Exception:
            codes_total = 0

        checkpoint_complete = bool(
            checkpoint_statutes_count > 0
            and (
                stage_label_lower == "complete"
                or stage_label_lower.endswith(":complete")
                or stage_label_lower.startswith("scrape_all:complete")
                or (codes_total > 0 and codes_completed >= codes_total)
            )
        )
        if not checkpoint_complete:
            continue
        if checkpoint_statutes_count < prior_count:
            continue

        entry["status"] = "success"
        entry["statutes_count"] = int(checkpoint_statutes_count)
        entry["completion_mode"] = "checkpoint_reconciled_complete"
        entry["checkpoint_reconciled"] = True
        entry["checkpoint_path"] = str(checkpoint_path)
        entry["checkpoint_stage_label"] = stage_label
        if str(payload.get("updated_at") or "").strip():
            entry["checkpoint_updated_at"] = str(payload.get("updated_at") or "").strip()
        if "error" in entry:
            entry["timeout_original_error"] = str(entry.get("error") or "")
            entry.pop("error", None)
        reconciled_states.append(
            {
                "state": str(state_code).upper(),
                "prior_status": status,
                "prior_statutes_count": prior_count,
                "checkpoint_statutes_count": checkpoint_statutes_count,
                "checkpoint_stage_label": stage_label,
            }
        )

    return {
        "reconciled_states": reconciled_states,
        "checked_state_count": checked_state_count,
        "reconciled_count": len(reconciled_states),
        "rejected_states": dict(sorted(rejected_states.items())),
    }


def _eligible_timeout_recovery_states(
    *,
    states: Sequence[str],
    progress_state: Mapping[str, Any],
) -> List[str]:
    """Return timeout error states that should be retried with larger budgets."""

    state_results = progress_state.get("state_results")
    if not isinstance(state_results, Mapping):
        return []

    candidates: List[str] = []
    for state_code in states:
        entry = state_results.get(state_code)
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status") or "").strip().lower()
        if status != "error":
            continue

        identity_gate = entry.get("source_software_immutability")
        worker_gate = entry.get("worker_quiescence")
        if not (
            isinstance(identity_gate, Mapping)
            and identity_gate.get("run_gate_passed") is True
            and isinstance(worker_gate, Mapping)
            and worker_gate.get("attested") is True
            and worker_gate.get("quiescent") is True
        ):
            continue

        timeout_classification = str(entry.get("timeout_classification") or "").strip().lower()
        if not timeout_classification and isinstance(entry.get("timeout_diagnostics"), Mapping):
            timeout_classification = str(
                (entry.get("timeout_diagnostics") or {}).get("classification") or ""
            ).strip().lower()
        if not timeout_classification.startswith("timeout_"):
            continue

        timeout_work_remaining = entry.get("timeout_work_remaining")
        if not isinstance(timeout_work_remaining, bool) and isinstance(entry.get("timeout_diagnostics"), Mapping):
            timeout_work_remaining = (entry.get("timeout_diagnostics") or {}).get("work_remaining")
        if timeout_work_remaining is False:
            # Already classified as timeout with no remaining work.
            continue

        candidates.append(str(state_code).upper())

    deduped: List[str] = []
    seen = set()
    for state_code in candidates:
        if state_code in seen:
            continue
        deduped.append(state_code)
        seen.add(state_code)
    return deduped


def _normalize_states(value: str, *, include_dc: bool = True) -> List[str]:
    """Normalize a states token.

    Production ``all`` is exactly 51 jurisdictions (50 states + DC). The legacy
    50-only ``all`` with opt-in DC is removed (LCR-007). Explicit subset lists
    remain allowed for non-release operations; production publish/combined paths
    call :func:`reject_subset_release`.
    """
    raw = str(value or "all").strip()
    if not raw or raw.lower() == "all":
        # DC is always part of the canonical ``all`` set.
        return list(STATE_CODES_51)

    states: List[str] = []
    for item in raw.split(","):
        code = item.strip().upper()
        if not code:
            continue
        if code not in US_STATES:
            raise ValueError(f"Unknown state code: {code}")
        # DC no longer requires --include-dc; flag retained for CLI compatibility.
        states.append(code)

    deduped: List[str] = []
    seen = set()
    for state in states:
        if state not in seen:
            deduped.append(state)
            seen.add(state)
    return deduped


def _coerce_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _first_text(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _safe_cid_for_obj(payload: Mapping[str, Any]) -> str:
    try:
        return cid_for_obj(dict(payload))
    except Exception:
        digest = hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()
        return f"sha256:{digest}"


def jsonld_payload_to_canonical_row(payload: Mapping[str, Any], *, state_code: str) -> Dict[str, Any]:
    """Convert one state-law JSON-LD object into the canonical parquet schema."""
    state = str(state_code or payload.get("stateCode") or payload.get("state_code") or "").strip().upper()
    identifier = _first_text(
        payload,
        ("identifier", "legislationIdentifier", "sectionNumber", "source_id", "@id"),
    )
    name = _first_text(payload, ("name", "sectionName", "title", "description"))
    text = _first_text(payload, ("text", "articleBody", "description"))
    source_url = _first_text(payload, ("sourceUrl", "url", "sameAs"))
    source_id = _first_text(payload, ("@id", "source_id")) or identifier or source_url

    row_without_cid = {
        "state_code": state,
        "source_id": source_id,
        "identifier": identifier,
        "name": name,
        "text": text,
        "source_url": source_url,
        "jsonld": json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
        "legislation_type": _first_text(payload, ("legislationType", "@type")),
        "legislation_jurisdiction": _first_text(payload, ("legislationJurisdiction",)),
    }
    return {
        "ipfs_cid": _safe_cid_for_obj(row_without_cid),
        **row_without_cid,
    }


def _logical_row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Stable logical identity (not content CID).

    CID-first merge was a production hazard: content edits under the same
    source identity created duplicate logical rows.  Prefer the canonical
    ``source_id`` (the JSON-LD converter projects ``@id`` there) before a bare
    citation such as ``sectionNumber``.  Section numbers are not globally
    unique across titles and may identify concurrent official source records.
    Rows from older datasets without ``source_id`` retain the citation-based
    fallback and current/history behavior.
    """
    state = str(row.get("state_code") or row.get("jurisdiction") or "").strip().upper()
    for field in (
        "legal_id",
        "source_id",
        "identifier",
        "legislationIdentifier",
        "section_number",
        "sectionNumber",
        "source_url",
        "sourceUrl",
    ):
        value = str(row.get(field) or "").strip()
        if value:
            return ("logical", state, field, value)
    # Last resort: content cid (only when no logical identity exists).
    cid = str(row.get("ipfs_cid") or row.get("entry_cid") or "").strip()
    if cid:
        return ("cid", state, cid)
    return ("row", state, json.dumps(dict(row), ensure_ascii=True, sort_keys=True, default=str))


def _row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Backward-compatible alias used by tests; prefers logical identity."""
    return _logical_row_key(row)


def merge_canonical_rows(
    existing_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
    *,
    retain_history: bool = True,
) -> List[Dict[str, Any]]:
    """Merge rows by logical identity, preferring the refreshed scraped row.

    When content CID changes under the same logical key, the prior CID is
    recorded on ``logical_history`` of the current row (current/history handling).
    """
    merged: Dict[tuple[str, ...], Dict[str, Any]] = {}
    order: List[tuple[str, ...]] = []
    for row in list(existing_rows) + list(new_rows):
        normalized = dict(row)
        key = _logical_row_key(normalized)
        if key not in merged:
            order.append(key)
            merged[key] = normalized
            continue
        prior = merged[key]
        prior_cid = str(prior.get("ipfs_cid") or prior.get("entry_cid") or "").strip()
        new_cid = str(normalized.get("ipfs_cid") or normalized.get("entry_cid") or "").strip()
        if retain_history and prior_cid and new_cid and prior_cid != new_cid:
            history = list(prior.get("logical_history") or [])
            if isinstance(normalized.get("logical_history"), list):
                history.extend(list(normalized.get("logical_history") or []))
            history.append({"ipfs_cid": prior_cid, "replaced": True})
            # Deduplicate history cids while preserving order.
            seen_cids = set()
            deduped_history = []
            for item in history:
                cid = str((item or {}).get("ipfs_cid") or "").strip()
                if not cid or cid in seen_cids or cid == new_cid:
                    continue
                seen_cids.add(cid)
                deduped_history.append({"ipfs_cid": cid, "replaced": True})
            normalized = dict(normalized)
            normalized["logical_history"] = deduped_history
            normalized["logical_key"] = ":".join(str(p) for p in key)
        merged[key] = normalized
    return [merged[key] for key in order]


def _normalize_rows_for_parquet(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return [{"_empty": True}]
    fields: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fields.append(key)
    return [{field: row.get(field) for field in fields} for row in rows]


def _read_parquet_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    import pyarrow.parquet as pq

    return [dict(row) for row in pq.read_table(path).to_pylist()]


def _write_parquet_rows(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(_normalize_rows_for_parquet(rows)), path, compression="snappy")


def _iter_jsonld_payloads(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                yield payload


def _download_existing_hf_state_parquet(
    *,
    repo_id: str,
    state_code: str,
    token: Optional[str],
    cache_dir: Path,
    repo_files: Optional[set[str]] = None,
) -> Path | None:
    remote_path = f"{_CORPUS.parquet_dir_name}/{_CORPUS.state_parquet_filename(state_code)}"
    if repo_files is not None and remote_path not in repo_files:
        return None
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return None
    try:
        downloaded = hf_hub_download(
            repo_id=repo_id,
            repo_type="dataset",
            filename=remote_path,
            token=token,
            cache_dir=str(cache_dir),
        )
    except Exception:
        return None
    return Path(downloaded)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hf_state_repo_path(state_code: str) -> str:
    return f"{_CORPUS.parquet_dir_name}/{_CORPUS.state_parquet_filename(state_code)}"


def _publish_state_parquet_file(
    *,
    state_code: str,
    state_parquet_path: Path,
    repo_id: str,
    token: Optional[str],
    create_repo: bool,
    commit_message: str,
) -> Dict[str, Any]:
    from huggingface_hub import HfApi

    if not state_parquet_path.exists():
        return {
            "status": "skipped",
            "state": state_code,
            "reason": "missing_local_state_parquet",
            "local_path": str(state_parquet_path),
        }

    api = HfApi(token=token)
    if create_repo:
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)

    repo_path = _hf_state_repo_path(state_code)
    try:
        upload_info = api.upload_file(
            path_or_fileobj=str(state_parquet_path),
            path_in_repo=repo_path,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=commit_message,
        )
    except Exception as exc:
        msg = str(exc)
        if "no files have been modified" in msg.lower() or "nothing to commit" in msg.lower() or "empty commit" in msg.lower():
            upload_info = "no_change_already_current"
        else:
            raise

    return {
        "status": "success",
        "state": state_code,
        "repo_id": repo_id,
        "repo_path": repo_path,
        "local_path": str(state_parquet_path),
        "local_sha256": _file_sha256(state_parquet_path),
        "upload_commit": str(upload_info),
    }


def _sync_stale_local_state_shards_to_hf(
    *,
    states: Sequence[str],
    parquet_dir: Path,
    repo_id: str,
    token: Optional[str],
    create_repo: bool,
    commit_message: str,
) -> Dict[str, Any]:
    """Upload local state shards whose bytes differ from the HF shard.

    This is intentionally content-hash based instead of relying on mtimes:
    Hugging Face download caches and git metadata do not provide a simple,
    stable remote mtime for every shard, while hash mismatch tells us the
    remote is stale relative to local content.
    """
    try:
        from huggingface_hub import HfApi
    except Exception as exc:
        return {"status": "error", "error": str(exc), "states": list(states), "uploaded": []}

    api = HfApi(token=token)
    if create_repo:
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)

    try:
        repo_files = set(api.list_repo_files(repo_id=repo_id, repo_type="dataset"))
    except Exception:
        repo_files = set()

    uploaded: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    hf_cache_dir = Path.home() / ".cache" / "state_laws_hf_merge"
    for state in states:
        local_path = parquet_dir / _CORPUS.state_parquet_filename(state)
        if not local_path.exists():
            skipped.append({"state": state, "reason": "missing_local_state_parquet"})
            continue

        local_hash = _file_sha256(local_path)
        repo_path = _hf_state_repo_path(state)
        remote_hash = ""
        remote_path = _download_existing_hf_state_parquet(
            repo_id=repo_id,
            state_code=state,
            token=token,
            cache_dir=hf_cache_dir,
            repo_files=repo_files,
        )
        if remote_path is not None and remote_path.exists():
            try:
                remote_hash = _file_sha256(remote_path)
            except Exception:
                remote_hash = ""

        if repo_path in repo_files and remote_hash == local_hash:
            skipped.append({"state": state, "reason": "remote_already_current", "sha256": local_hash})
            continue

        uploaded.append(
            _publish_state_parquet_file(
                state_code=state,
                state_parquet_path=local_path,
                repo_id=repo_id,
                token=token,
                create_repo=False,
                commit_message=f"{commit_message} ({state} stale shard sync)",
            )
        )

    return {
        "status": "success",
        "states": list(states),
        "uploaded": uploaded,
        "uploaded_count": len(uploaded),
        "skipped": skipped,
        "skipped_count": len(skipped),
    }


def _build_and_sync_stale_local_state_shards_to_hf(
    *,
    states: Sequence[str],
    jsonld_dir: Path,
    parquet_dir: Path,
    merge_existing_local: bool,
    merge_hf_existing: bool,
    repo_id: str,
    token: Optional[str],
    create_repo: bool,
    commit_message: str,
) -> Dict[str, Any]:
    uploaded: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for index, state in enumerate(states, start=1):
        print(
            f"[state_laws_refresh] startup_stale_sync state={state} index={index}/{len(states)}",
            flush=True,
        )
        try:
            state_jsonld_path = jsonld_dir / f"STATE-{state}.jsonld"
            state_parquet_path = parquet_dir / _CORPUS.state_parquet_filename(state)
            if state_jsonld_path.exists():
                build_state_laws_parquet_artifacts(
                    states=[state],
                    jsonld_dir=jsonld_dir,
                    parquet_dir=parquet_dir,
                    merge_existing_local=merge_existing_local,
                    merge_hf_existing=merge_hf_existing,
                    repo_id=repo_id,
                    token=token,
                )
            if not state_parquet_path.exists():
                skipped.append({"state": state, "reason": "no_local_jsonld_or_parquet"})
                continue

            sync = _sync_stale_local_state_shards_to_hf(
                states=[state],
                parquet_dir=parquet_dir,
                repo_id=repo_id,
                token=token,
                create_repo=create_repo and index == 1,
                commit_message=commit_message,
            )
            uploaded.extend(sync.get("uploaded") or [])
            skipped.extend(sync.get("skipped") or [])
        except Exception as exc:
            errors.append({"state": state, "error": str(exc)})

    return {
        "status": "success" if not errors else "partial_success",
        "states": list(states),
        "uploaded": uploaded,
        "uploaded_count": len(uploaded),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "errors": errors,
        "error_count": len(errors),
    }


def build_state_laws_parquet_artifacts(
    *,
    states: Sequence[str],
    jsonld_dir: Path,
    parquet_dir: Path,
    merge_existing_local: bool = True,
    merge_hf_existing: bool = False,
    repo_id: str = _CORPUS.hf_dataset_id,
    token: Optional[str] = None,
    hf_cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build per-state and combined parquet files from state-law JSON-LD."""
    parquet_dir.mkdir(parents=True, exist_ok=True)
    hf_cache_dir = hf_cache_dir or (Path.home() / ".cache" / "state_laws_hf_merge")
    repo_files: Optional[set[str]] = None

    if merge_hf_existing:
        try:
            from huggingface_hub import HfApi

            repo_files = set(HfApi(token=token).list_repo_files(repo_id=repo_id, repo_type="dataset"))
        except Exception:
            repo_files = set()

    state_reports: List[Dict[str, Any]] = []
    combined_rows: List[Dict[str, Any]] = []
    missing_jsonld: List[str] = []

    for state in states:
        state_jsonld_path = jsonld_dir / f"STATE-{state}.jsonld"
        if not state_jsonld_path.exists():
            missing_jsonld.append(state)
            new_rows: List[Dict[str, Any]] = []
        else:
            new_rows = [
                jsonld_payload_to_canonical_row(payload, state_code=state)
                for payload in _iter_jsonld_payloads(state_jsonld_path)
            ]

        state_parquet_path = parquet_dir / _CORPUS.state_parquet_filename(state)
        existing_rows: List[Dict[str, Any]] = []
        if merge_hf_existing:
            remote_path = _download_existing_hf_state_parquet(
                repo_id=repo_id,
                state_code=state,
                token=token,
                cache_dir=hf_cache_dir,
                repo_files=repo_files,
            )
            if remote_path is not None:
                existing_rows.extend(_read_parquet_rows(remote_path))
        if merge_existing_local:
            existing_rows.extend(_read_parquet_rows(state_parquet_path))

        merged_rows = merge_canonical_rows(existing_rows, new_rows)
        if merged_rows:
            _write_parquet_rows(merged_rows, state_parquet_path)
        combined_rows.extend(merged_rows)
        state_reports.append(
            {
                "state": state,
                "jsonld_path": str(state_jsonld_path),
                "parquet_path": str(state_parquet_path),
                "scraped_row_count": len(new_rows),
                "existing_row_count": len(existing_rows),
                "merged_row_count": len(merged_rows),
                "jsonld_exists": state_jsonld_path.exists(),
            }
        )

    combined_rows = merge_canonical_rows([], combined_rows)
    combined_path = parquet_dir / _CORPUS.combined_parquet_filename
    state_set = {str(s).strip().upper() for s in states}
    is_exact_production_set = state_set == CANONICAL_PRODUCTION_JURISDICTIONS
    combined_written = False
    # Never overwrite a shared combined parquet from a subset scrape (LCR-007).
    if combined_rows and is_exact_production_set:
        _write_parquet_rows(combined_rows, combined_path)
        combined_written = True
    elif combined_rows and not is_exact_production_set:
        # Isolated non-production builds may still emit a *local* combined only
        # when the caller opts in via env; default is skip (fail-closed).
        if str(os.getenv("STATE_LAWS_ALLOW_SUBSET_COMBINED", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            subset_combined = parquet_dir / "state_laws_subset_combined.parquet"
            _write_parquet_rows(combined_rows, subset_combined)
            combined_path = subset_combined
            combined_written = True
        else:
            combined_path = parquet_dir / "state_laws_subset_combined.skipped"
            combined_rows = []

    manifest = {
        "status": "success",
        "corpus_key": _CORPUS.key,
        "repo_id": repo_id,
        "states": list(states),
        "state_count": len(states),
        "missing_jsonld_states": missing_jsonld,
        "parquet_dir": str(parquet_dir),
        "combined_parquet_path": str(combined_path),
        "combined_row_count": len(combined_rows),
        "combined_written": bool(combined_written),
        "exact_production_jurisdiction_set": bool(is_exact_production_set),
        "shared_combined_overwrite": bool(combined_written and is_exact_production_set),
        "merge_existing_local": bool(merge_existing_local),
        "merge_hf_existing": bool(merge_hf_existing),
        "state_reports": state_reports,
    }
    manifest_path = parquet_dir / "state_laws_refresh_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _publish_parquet_dir(
    *,
    parquet_dir: Path,
    repo_id: str,
    token: Optional[str],
    create_repo: bool,
    verify: bool,
    commit_message: str,
) -> Dict[str, Any]:
    from scripts.repair.publish_parquet_to_hf import publish

    return publish(
        local_dir=parquet_dir,
        repo_id=repo_id,
        commit_message=commit_message,
        create_repo=create_repo,
        token=token,
        path_in_repo=_CORPUS.parquet_dir_name,
        allow_patterns=["*.parquet", "*.json", "*.md"],
        do_verify=verify,
        cid_column=_CORPUS.cid_field,
    )


def _run_full_corpus_guard_audit(*, states: Sequence[str]) -> Dict[str, Any]:
    """Run the static full-corpus truncation audit before uncapped scrapes."""
    script_path = Path(__file__).with_name("audit_state_scraper_full_corpus_guards.py")
    spec = importlib.util.spec_from_file_location("audit_state_scraper_full_corpus_guards", script_path)
    if spec is None or spec.loader is None:
        return {
            "status": "fail",
            "states_checked": 0,
            "missing_states": list(states),
            "error_count": 1,
            "warning_count": 0,
            "findings": [{"severity": "error", "detail": f"unable_to_load_audit:{script_path}"}],
        }

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    repo_root = Path(__file__).resolve().parents[3]
    scraper_root = repo_root / "ipfs_datasets_py" / "processors" / "legal_scrapers" / "state_scrapers"
    findings: List[Any] = []
    missing: List[str] = []
    for state in states:
        state_code = str(state).upper()
        module_name = module.STATE_MODULES.get(state_code)
        if not module_name:
            missing.append(state_code)
            continue
        path = scraper_root / f"{module_name}.py"
        if not path.exists():
            missing.append(state_code)
            continue
        findings.extend(module.audit_file(state=state_code, path=path, repo_root=repo_root))

    error_count = sum(1 for item in findings if str(getattr(item, "severity", "")) == "error")
    warning_count = sum(1 for item in findings if str(getattr(item, "severity", "")) == "warning")
    return {
        "status": "fail" if error_count or warning_count or missing else "pass",
        "states_checked": len(states) - len(missing),
        "missing_states": missing,
        "error_count": error_count,
        "warning_count": warning_count,
        "findings": [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in findings],
    }


async def refresh_state_laws_corpus(args: argparse.Namespace) -> Dict[str, Any]:
    requested_states = _normalize_states(args.states, include_dc=bool(args.include_dc))
    acquisition_run_id = uuid.uuid4().hex
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else _CORPUS.default_local_root()
    jsonld_dir = Path(args.jsonld_dir).expanduser().resolve() if args.jsonld_dir else _CORPUS.jsonld_dir(str(output_root))
    parquet_dir = Path(args.parquet_dir).expanduser().resolve() if args.parquet_dir else _CORPUS.parquet_dir(str(output_root))
    acquisition_evidence_root_raw = str(
        getattr(args, "acquisition_evidence_root", "") or ""
    ).strip()
    acquisition_evidence_root = (
        Path(acquisition_evidence_root_raw).expanduser().resolve()
        if acquisition_evidence_root_raw
        else None
    )
    retained_replay_only = bool(getattr(args, "retained_replay_only", False))
    strict_acquisition_evidence = bool(
        getattr(args, "strict_acquisition_evidence", False)
        or retained_replay_only
    )
    direct_external_mutation_requested = bool(
        getattr(args, "publish_to_hf", False)
        or getattr(args, "create_repo", False)
    )
    if direct_external_mutation_requested:
        return {
            "status": "failed_preflight",
            "reason": "refresh_external_mutation_requires_sealed_production_runner",
            "detail": (
                "the refresh runner never performs Hugging Face repository creation, "
                "startup/incremental synchronization, or publication; use the exact-51 "
                "production input-map runner, which revalidates every artifact, "
                "receipt, seal, evidence root, and runner identity immediately before "
                "creating release output"
            ),
            "authorizing_for_publication": False,
        }
    strict_evidence_preflight_errors: List[str] = []
    if strict_acquisition_evidence and acquisition_evidence_root is None:
        strict_evidence_preflight_errors.append("acquisition_evidence_root_required")
    if strict_acquisition_evidence and not bool(args.scrape):
        strict_evidence_preflight_errors.append("strict_evidence_requires_scrape")
    if strict_acquisition_evidence and int(args.max_statutes or 0) > 0:
        strict_evidence_preflight_errors.append("strict_evidence_forbids_bounded_scrape")
    if strict_acquisition_evidence and bool(
        getattr(args, "allow_justia_fallback", False)
    ):
        strict_evidence_preflight_errors.append("strict_evidence_forbids_secondary_fallback")
    if strict_acquisition_evidence and not bool(
        getattr(args, "incremental_state_materialize", bool(args.scrape))
    ):
        strict_evidence_preflight_errors.append(
            "strict_evidence_requires_incremental_materialization"
        )
    if strict_acquisition_evidence:
        strict_evidence_preflight_errors.extend(
            _strict_ambient_selector_preflight_errors()
        )
    if retained_replay_only and bool(getattr(args, "merge_hf_existing", False)):
        strict_evidence_preflight_errors.append(
            "retained_replay_only_forbids_hf_merge"
        )
    if retained_replay_only and bool(getattr(args, "publish_to_hf", False)):
        strict_evidence_preflight_errors.append(
            "retained_replay_only_forbids_hf_publish"
        )
    if retained_replay_only and bool(getattr(args, "verify", False)):
        strict_evidence_preflight_errors.append(
            "retained_replay_only_forbids_remote_verification"
        )
    if retained_replay_only and bool(getattr(args, "create_repo", False)):
        strict_evidence_preflight_errors.append(
            "retained_replay_only_forbids_remote_repo_creation"
        )
    if strict_evidence_preflight_errors:
        return {
            "status": "failed_preflight",
            "reason": "strict_acquisition_evidence_preflight_failed",
            "errors": strict_evidence_preflight_errors,
            "acquisition_evidence": {
                "evidence_root": (
                    str(acquisition_evidence_root)
                    if acquisition_evidence_root is not None
                    else None
                ),
                "retained_replay_only": retained_replay_only,
                "strict": True,
            },
        }

    if acquisition_evidence_root is not None:
        permanent_nonauthorization_marker = (
            acquisition_evidence_root / NONQUIESCENT_EVIDENCE_MARKER
        )
        if (
            permanent_nonauthorization_marker.exists()
            or permanent_nonauthorization_marker.is_symlink()
        ):
            return {
                "status": "failed_preflight",
                "reason": "permanently_nonauthorizing_evidence_root",
                "detail": (
                    "the acquisition evidence root contains a prior "
                    "permanent nonauthorization marker and must not be reused"
                ),
                "acquisition_run_id": acquisition_run_id,
                "marker_path": str(permanent_nonauthorization_marker),
            }
        in_progress_marker = acquisition_evidence_root / IN_PROGRESS_EVIDENCE_MARKER
        if in_progress_marker.exists() or in_progress_marker.is_symlink():
            return {
                "status": "failed_preflight",
                "reason": "acquisition_evidence_root_in_progress",
                "detail": (
                    "the acquisition evidence root contains an unfinished "
                    "non-authorizing run lease and must not be reused"
                ),
                "acquisition_run_id": acquisition_run_id,
                "marker_path": str(in_progress_marker),
            }

    # Bind the already-loaded producers before registry reconciliation, local
    # output admission, audit loading, or any remote side effect.  The active
    # state subset is selected later, but its start identities always come from
    # this first point-in-time capture of the requested set.
    early_source_software_versions: Dict[str, str] = {}
    early_source_software_errors: Dict[str, str] = {}
    early_runner_source_software_identity = ""
    early_runner_source_software_error = ""
    early_source_software_snapshot_at: str | None = None
    if bool(args.scrape) and not bool(getattr(args, "dry_run", False)):
        early_source_software_snapshot_at = _utc_now_iso()
        try:
            early_runner_source_software_identity = (
                runner_source_software_version(
                    require_loaded_source_correspondence=True
                )
            )
        except Exception as exc:
            early_runner_source_software_error = (
                f"{type(exc).__name__}: {exc}"
            )
        (
            early_source_software_versions,
            early_source_software_errors,
        ) = _capture_registered_state_source_software_versions(requested_states)
    repo_id = str(args.repo_id or _CORPUS.hf_dataset_id).strip()
    completed_registry_raw = str(getattr(args, "completed_states_registry", "") or "").strip()
    completed_states_registry_path = (
        Path(completed_registry_raw).expanduser().resolve()
        if completed_registry_raw
        else _default_completed_states_registry_path(output_root)
    )
    completed_baseline_raw = str(getattr(args, "completed_states_baseline", "") or "").strip()
    completed_states_baseline_path = (
        Path(completed_baseline_raw).expanduser().resolve()
        if completed_baseline_raw
        else _default_completed_states_baseline_path()
    )
    skip_completed_states = bool(getattr(args, "skip_completed_states", True))
    persist_completed_states_registry = bool(getattr(args, "persist_completed_states_registry", True))
    if hasattr(args, "load_completed_states_baseline"):
        load_completed_states_baseline = bool(getattr(args, "load_completed_states_baseline", True))
    elif completed_baseline_raw:
        load_completed_states_baseline = True
    else:
        load_completed_states_baseline = _uses_shared_completed_registry(output_root)
    completed_states_registry = _load_completed_states_registry(completed_states_registry_path)
    baseline_registry = (
        _load_completed_states_registry(completed_states_baseline_path)
        if load_completed_states_baseline and completed_states_baseline_path.exists()
        else _empty_completed_states_registry()
    )
    completed_states_registry = _merge_completed_states_registries(
        base_registry=baseline_registry,
        overlay_registry=completed_states_registry,
    )
    registry_completed_state_candidates = (
        _completed_states_to_skip(requested_states, completed_states_registry)
        if skip_completed_states
        else []
    )

    # A completion-ledger row is deliberately not a reuse credential. Feed each
    # exact local output to the shared coordinator one state at a time. This
    # keeps peak restart memory bounded by the largest state file rather than
    # retaining the entire completed corpus in one bytes dictionary. The
    # coordinator still admits reuse only when the independent receipt's
    # declared/replayed hashes match these bytes and its official-source
    # frontier is closed and replayed.
    coordination_by_state: Dict[str, CoordinationPlan] = {}
    base_acquisition_coordination: CoordinationPlan | None = None
    local_output_bytes_checked_states: List[str] = []
    local_output_row_counts: Dict[str, int] = {}
    local_output_read_errors: Dict[str, str] = {}
    if skip_completed_states:
        for state in requested_states:
            state_jsonld = jsonld_dir / f"STATE-{state}.jsonld"
            if not state_jsonld.is_file():
                continue
            if state_jsonld.is_symlink():
                local_output_read_errors[state] = "local state output is a symlink"
                continue
            try:
                row_count = _validate_staged_state_jsonld(
                    state_jsonld,
                    state_code=state,
                    expected_rows=None,
                )
                body = state_jsonld.read_bytes()
            except Exception as exc:
                local_output_read_errors[state] = f"{type(exc).__name__}: {exc}"
                continue
            if not body:
                local_output_read_errors[state] = "empty local state output"
                continue
            body_digest = hashlib.sha256(body).digest()
            state_coordination = coordinate_default_prior_evidence(
                repo_root=Path(__file__).resolve().parents[3],
                body_bytes={state: body},
            )
            try:
                installed_size, installed_digest = file_digest(state_jsonld)
            except Exception as exc:
                local_output_read_errors[state] = f"{type(exc).__name__}: {exc}"
                body = b""
                continue
            if installed_size != len(body) or installed_digest != body_digest:
                local_output_read_errors[state] = (
                    "local state output changed during coordinator verification"
                )
                body = b""
                continue
            coordination_by_state[state] = state_coordination
            local_output_row_counts[state] = row_count
            if base_acquisition_coordination is None:
                base_acquisition_coordination = state_coordination
            local_output_bytes_checked_states.append(state)
            # Do not retain a completed jurisdiction payload after its
            # coordinator admission decision has been reduced to immutable
            # verdict metadata.
            body = b""

    if base_acquisition_coordination is None:
        base_acquisition_coordination = coordinate_default_prior_evidence(
            repo_root=Path(__file__).resolve().parents[3],
            body_bytes={},
        )

    verified_prior_receipt_states: List[str] = []
    for state in requested_states:
        state_coordination = coordination_by_state.get(
            state,
            base_acquisition_coordination,
        )
        lease = state_coordination.lease_for(state)
        accepted_admissions = {
            admission.jurisdiction_code: admission
            for admission in state_coordination.admissions
            if admission.accepted
        }
        admission = accepted_admissions.get(state)
        byte_verification = admission.byte_verification if admission is not None else None
        frontier_verification = (
            admission.frontier_verification if admission is not None else None
        )
        if (
            state in coordination_by_state
            and lease.action == ACTION_REUSE
            and lease.prior_receipt_accepted
            and lease.byte_verified
            and lease.frontier_verified
            and byte_verification is not None
            and byte_verification.ok
            and byte_verification.raw_bytes_checked
            and frontier_verification is not None
            and frontier_verification.ok
            and frontier_verification.closed
            and int(admission.row_count or 0) == local_output_row_counts.get(state)
        ):
            verified_prior_receipt_states.append(state)

    skipped_completed_states = (
        list(verified_prior_receipt_states) if skip_completed_states else []
    )
    reopened_missing_canonical_states = _completed_states_missing_canonical_jsonld(
        states=registry_completed_state_candidates,
        jsonld_dir=jsonld_dir,
    )
    registry_only_completion_states = [
        state
        for state in registry_completed_state_candidates
        if state not in set(verified_prior_receipt_states)
    ]
    states = [state for state in requested_states if state not in set(skipped_completed_states)]
    if skipped_completed_states and direct_external_mutation_requested:
        return {
            "status": "failed_preflight",
            "reason": "reused_inputs_require_sealed_production_runner",
            "detail": (
                "a refresh with retained/reused jurisdictions cannot authorize a "
                "combined external mutation from an active-subset seal; use the "
                "exact-51 production input-map runner"
            ),
            "requested_states": list(requested_states),
            "active_states": list(states),
            "reused_states": list(skipped_completed_states),
            "authorizing_for_publication": False,
        }
    needs_hf_token = bool(args.merge_hf_existing or args.publish_to_hf or args.verify)
    hf_token = (
        _resolve_hf_token(str(args.hf_token or "").strip() or None)
        if needs_hf_token
        else (str(args.hf_token or "").strip() or None)
    )
    publish_to_hf = bool(args.publish_to_hf)
    startup_stale_sync_requested = bool(
        getattr(args, "startup_stale_sync", bool(args.scrape))
    )
    incremental_state_publish_requested = bool(
        getattr(args, "incremental_state_publish", bool(args.scrape))
    )
    run_identity_gate_enabled = bool(args.scrape or direct_external_mutation_requested)
    # Remote mutation cannot precede the run-final identity/quiescence seal.
    startup_stale_sync = bool(
        startup_stale_sync_requested and not run_identity_gate_enabled
    )
    incremental_state_publish = bool(
        incremental_state_publish_requested and not run_identity_gate_enabled
    )
    incremental_state_materialize = bool(
        getattr(args, "incremental_state_materialize", bool(args.scrape))
    )
    materialize_completed_states = bool(
        args.scrape
        and (
            incremental_state_materialize
            or (publish_to_hf and incremental_state_publish_requested)
            or acquisition_evidence_root is not None
        )
    )
    transport_bypass_inventory = (
        inventory_registered_state_scraper_transport_bypasses(requested_states)
        if acquisition_evidence_root is not None
        else None
    )

    plan = {
        "requested_states": requested_states,
        "requested_state_count": len(requested_states),
        "states": states,
        "state_count": len(states),
        "skipped_completed_states": skipped_completed_states,
        "skipped_completed_count": len(skipped_completed_states),
        "verified_prior_receipt_states": verified_prior_receipt_states,
        "verified_prior_receipt_count": len(verified_prior_receipt_states),
        "registry_completed_state_candidates": registry_completed_state_candidates,
        "registry_only_completion_states": registry_only_completion_states,
        "local_output_bytes_checked_states": sorted(local_output_bytes_checked_states),
        "local_output_byte_verification_mode": "one_state_at_a_time",
        "local_output_row_counts": dict(sorted(local_output_row_counts.items())),
        "local_output_read_errors": dict(sorted(local_output_read_errors.items())),
        "acquisition_lease_actions": {
            state: coordination_by_state.get(
                state,
                base_acquisition_coordination,
            ).lease_for(state).action
            for state in requested_states
        },
        "reopened_missing_canonical_states": reopened_missing_canonical_states,
        "reopened_missing_canonical_count": len(reopened_missing_canonical_states),
        "skip_completed_states": skip_completed_states,
        "completed_states_registry_path": str(completed_states_registry_path),
        "completed_states_baseline_path": str(completed_states_baseline_path),
        "load_completed_states_baseline": load_completed_states_baseline,
        "persist_completed_states_registry": persist_completed_states_registry,
        "scrape": bool(args.scrape),
        "jsonld_dir": str(jsonld_dir),
        "parquet_dir": str(parquet_dir),
        "repo_id": repo_id,
        "publish_to_hf": publish_to_hf,
        "merge_hf_existing": bool(args.merge_hf_existing),
        "incremental_state_materialize": incremental_state_materialize,
        "incremental_state_publish": incremental_state_publish,
        "incremental_state_publish_requested": incremental_state_publish_requested,
        "incremental_state_publish_suppressed_until_run_seal": bool(
            incremental_state_publish_requested and run_identity_gate_enabled
        ),
        "startup_stale_sync": startup_stale_sync,
        "startup_stale_sync_requested": startup_stale_sync_requested,
        "startup_stale_sync_suppressed_until_run_seal": bool(
            startup_stale_sync_requested and run_identity_gate_enabled
        ),
        "acquisition_evidence_root": (
            str(acquisition_evidence_root)
            if acquisition_evidence_root is not None
            else None
        ),
        "strict_acquisition_evidence": strict_acquisition_evidence,
        "retained_replay_only": retained_replay_only,
        "transport_bypass_inventory": transport_bypass_inventory,
        "source_software_immutability_gate": {
            "enabled": run_identity_gate_enabled,
            "active_states": list(states),
            "start_snapshot_before_scrape": True,
            "exact_identity_recheck_required": True,
            "run_id": acquisition_run_id,
        },
    }
    if args.dry_run:
        return {"status": "dry_run", "plan": plan}

    startup_sync_result: Dict[str, Any] | None = None

    progress_path = output_root / "state_refresh_progress.json"
    source_software_gate_failed_states: set[str] = set()
    source_software_gate_failure_reasons: Dict[str, str] = {}
    source_software_permanent_marker_path = ""
    source_software_start_identities: Dict[str, str] = {}
    source_software_immutability: Dict[str, Any] = {
        "schema": _SOURCE_SOFTWARE_IMMUTABILITY_SCHEMA,
        "run_id": acquisition_run_id,
        "status": "not_applicable",
        "started_at": _utc_now_iso(),
        "active_states": list(states),
        "active_state_count": len(states),
        "start_identities": {},
        "end_identities": {},
        "completion_checks": {},
        "final_state_checks": {},
        "identities_equal": None,
        "failed_states": [],
        "verification_errors": {},
        "runner_start_identity": None,
        "runner_end_identity": None,
        "runner_identity_equal": None,
        "runner_verification_error": None,
        "authorizing_for_publication": False,
    }
    acquisition_in_progress_marker_path: Path | None = None
    acquisition_in_progress_marker_sha256 = ""
    if args.scrape and states:
        start_versions = {
            state: early_source_software_versions[state]
            for state in states
            if state in early_source_software_versions
        }
        start_errors = {
            state: early_source_software_errors[state]
            for state in states
            if state in early_source_software_errors
        }
        for state in states:
            if state not in start_versions and state not in start_errors:
                start_errors[state] = "early run-start source identity is missing"
        source_software_start_identities = dict(start_versions)
        source_software_immutability.update(
            {
                "status": "running" if not start_errors else "start_snapshot_failed",
                "start_snapshot_at": (
                    early_source_software_snapshot_at or _utc_now_iso()
                ),
                "start_snapshot_scope": list(requested_states),
                "start_identities": dict(start_versions),
                "runner_start_identity": (
                    early_runner_source_software_identity or None
                ),
                "identities_equal": None if not start_errors else False,
                "failed_states": sorted(start_errors),
                "verification_errors": dict(start_errors),
            }
        )
        if early_runner_source_software_error:
            source_software_immutability["status"] = "start_snapshot_failed"
            source_software_immutability["identities_equal"] = False
            source_software_immutability["runner_identity_equal"] = False
            source_software_immutability["runner_verification_error"] = (
                early_runner_source_software_error
            )
            source_software_immutability["verification_errors"] = {
                **dict(start_errors),
                "refresh_runner": early_runner_source_software_error,
            }
        elif early_runner_source_software_identity:
            source_software_immutability["runner_identity_equal"] = None
        if start_errors or early_runner_source_software_error:
            source_software_gate_failed_states.update(start_errors)
            for state_code, error in start_errors.items():
                source_software_gate_failure_reasons[state_code] = error
            if early_runner_source_software_error:
                for state_code in states:
                    source_software_gate_failed_states.add(state_code)
                    source_software_gate_failure_reasons.setdefault(
                        state_code,
                        "refresh runner start identity could not be proven: "
                        + early_runner_source_software_error,
                    )
            source_software_immutability["authorizing_for_publication"] = False
            failed_progress = {
                "schema": "ipfs_datasets_py.state_laws_refresh.progress.v1",
                "status": "failed_preflight",
                "started_at": source_software_immutability["started_at"],
                "finished_at": _utc_now_iso(),
                "states": requested_states,
                "active_states": states,
                "states_total": len(requested_states),
                "active_states_total": len(states),
                "source_software_immutability": source_software_immutability,
            }
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_path.write_text(
                json.dumps(
                    failed_progress,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                ),
                encoding="utf-8",
            )
            return {
                "status": "failed_preflight",
                "reason": "source_software_start_snapshot_failed",
                "plan": plan,
                "progress_path": str(progress_path),
                "source_software_immutability": source_software_immutability,
            }

        if acquisition_evidence_root is not None:
            try:
                (
                    acquisition_in_progress_marker_path,
                    acquisition_in_progress_marker_sha256,
                ) = _write_acquisition_in_progress_marker(
                    acquisition_evidence_root,
                    run_id=acquisition_run_id,
                    active_states=states,
                )
            except Exception as exc:
                source_software_immutability["status"] = (
                    "evidence_root_lease_failed"
                )
                source_software_immutability["authorizing_for_publication"] = False
                return {
                    "status": "failed_preflight",
                    "reason": "acquisition_evidence_root_lease_failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "plan": plan,
                    "source_software_immutability": source_software_immutability,
                }

    prefilled_state_results = _prefill_state_results_from_verified_receipts(
        states=skipped_completed_states,
        coordination_by_state=coordination_by_state,
    )
    progress_state: Dict[str, Any] = {
        "schema": "ipfs_datasets_py.state_laws_refresh.progress.v1",
        "acquisition_run_id": acquisition_run_id,
        "status": "running",
        "started_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "states": requested_states,
        "active_states": states,
        "states_total": len(requested_states),
        "active_states_total": len(states),
        "skipped_completed_states": skipped_completed_states,
        "state_results": prefilled_state_results,
        "states_completed": [],
        "completed_count": 0,
        "success_count": 0,
        "error_count": 0,
        "zero_statute_count": 0,
        "acquisition_evidence_root": (
            str(acquisition_evidence_root)
            if acquisition_evidence_root is not None
            else None
        ),
        "strict_acquisition_evidence": strict_acquisition_evidence,
        "retained_replay_only": retained_replay_only,
        "source_software_immutability": source_software_immutability,
    }

    def _record_source_software_check(check: Mapping[str, Any]) -> None:
        raw_state_checks = check.get("state_checks")
        state_checks = (
            raw_state_checks if isinstance(raw_state_checks, Mapping) else {}
        )
        raw_errors = check.get("verification_errors")
        verification_errors = (
            raw_errors if isinstance(raw_errors, Mapping) else {}
        )
        for raw_state, raw_state_check in state_checks.items():
            state_code = str(raw_state or "").strip().upper()
            state_check = (
                raw_state_check if isinstance(raw_state_check, Mapping) else {}
            )
            if state_check.get("identities_equal") is True:
                continue
            source_software_gate_failed_states.add(state_code)
            error = str(verification_errors.get(state_code) or "").strip()
            if not error:
                start_identity = str(
                    state_check.get("start_identity") or ""
                ).strip()
                end_identity = str(state_check.get("end_identity") or "").strip()
                error = (
                    "registered source identity changed during the acquisition run: "
                    f"start={start_identity!r}, end={end_identity!r}"
                )
            source_software_gate_failure_reasons.setdefault(state_code, error)

    def _check_state_source_software(
        state_code: str,
        *,
        phase: str,
    ) -> Dict[str, Any]:
        check = _verify_state_source_software_immutability(
            states=[state_code],
            start_identities=source_software_start_identities,
            phase=phase,
        )
        completion_checks = source_software_immutability.setdefault(
            "completion_checks", {}
        )
        if isinstance(completion_checks, dict):
            prior_checks = completion_checks.setdefault(state_code, [])
            if isinstance(prior_checks, list):
                prior_checks.append(check)
        _record_source_software_check(check)
        check["run_gate_passed"] = bool(
            check.get("identities_equal") is True
            and state_code not in source_software_gate_failed_states
        )
        return check

    def _check_refresh_runner_source_software(*, phase: str) -> Dict[str, Any]:
        end_identity = ""
        verification_error = ""
        try:
            end_identity = runner_source_software_version(
                require_loaded_source_correspondence=True
            )
        except Exception as exc:
            verification_error = f"{type(exc).__name__}: {exc}"
        identities_equal = bool(
            early_runner_source_software_identity
            and end_identity
            and not verification_error
            and early_runner_source_software_identity == end_identity
        )
        check = {
            "phase": str(phase),
            "checked_at": _utc_now_iso(),
            "start_identity": early_runner_source_software_identity or None,
            "end_identity": end_identity or None,
            "identities_equal": identities_equal,
            "verification_error": verification_error or None,
            "authorizing_for_publication": identities_equal,
        }
        runner_checks = source_software_immutability.setdefault(
            "runner_completion_checks",
            [],
        )
        if isinstance(runner_checks, list):
            runner_checks.append(check)
        if not identities_equal:
            detail = verification_error or (
                "refresh runner identity changed during the acquisition run: "
                f"start={early_runner_source_software_identity!r}, "
                f"end={end_identity!r}"
            )
            for state_code in states:
                source_software_gate_failed_states.add(state_code)
                source_software_gate_failure_reasons.setdefault(
                    state_code,
                    detail,
                )
        return check

    def _mark_run_finalization_failure(state_code: str, reason: str) -> None:
        code = str(state_code or "").strip().upper()
        run_finalization_failed_states.add(code)
        run_finalization_failure_reasons.setdefault(code, str(reason))
        results = progress_state.setdefault("state_results", {})
        if not isinstance(results, dict):
            return
        prior = results.get(code)
        entry = dict(prior) if isinstance(prior, Mapping) else {
            "state_code": code,
            "state_name": US_STATES.get(code, code),
            "statutes_count": 0,
            "completed_at": _utc_now_iso(),
        }
        entry["status"] = "error"
        entry["error"] = str(reason)
        entry["authorizing_for_publication"] = False
        raw_evidence = entry.get("acquisition_evidence")
        evidence = dict(raw_evidence) if isinstance(raw_evidence, Mapping) else {}
        aggregate = dict(evidence.get("aggregate") or {})
        aggregate.update(
            {
                "status": "blocked_run_finalization",
                "detail": str(reason),
                "authorizing_for_publication": False,
            }
        )
        evidence["aggregate"] = aggregate
        evidence["normalized_source_receipt_usable"] = False
        entry["acquisition_evidence"] = evidence
        results[code] = entry

    def _recompute_progress_counts() -> None:
        results = progress_state.get("state_results") if isinstance(progress_state.get("state_results"), dict) else {}
        completed_states = [state for state in requested_states if state in results]
        success_count = 0
        error_count = 0
        zero_statute_count = 0
        for state in completed_states:
            entry = results.get(state) if isinstance(results.get(state), dict) else {}
            status = str(entry.get("status") or "").strip().lower()
            if status == "success":
                success_count += 1
            elif status == "error":
                error_count += 1
            elif status == "zero_statutes":
                zero_statute_count += 1
        progress_state["states_completed"] = completed_states
        progress_state["completed_count"] = len(completed_states)
        progress_state["success_count"] = success_count
        progress_state["error_count"] = error_count
        progress_state["zero_statute_count"] = zero_statute_count
        progress_state["updated_at"] = _utc_now_iso()

    def _write_progress_state() -> None:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            json.dumps(progress_state, indent=2, sort_keys=True, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def _write_completed_states_registry_snapshot() -> None:
        nonlocal completed_states_registry
        if not persist_completed_states_registry:
            return
        state_results = progress_state.get("state_results")
        if not isinstance(state_results, Mapping):
            return
        completed_states_registry = _merge_completed_states_registry(
            existing_registry=completed_states_registry,
            state_results=state_results,
            output_root=output_root,
            progress_path=progress_path,
        )
        _write_completed_states_registry(completed_states_registry_path, completed_states_registry)

    _recompute_progress_counts()
    _write_progress_state()
    _write_completed_states_registry_snapshot()

    if publish_to_hf and startup_stale_sync:
        # Reconcile stale HF state shards before the long scrape starts, but do
        # it one state at a time so a large local corpus does not have to be
        # loaded into a combined in-memory table.
        startup_sync_result = _build_and_sync_stale_local_state_shards_to_hf(
            states=requested_states,
            jsonld_dir=jsonld_dir,
            parquet_dir=parquet_dir,
            merge_existing_local=not bool(args.no_merge_existing_local),
            merge_hf_existing=bool(args.merge_hf_existing),
            repo_id=repo_id,
            token=hf_token,
            create_repo=bool(args.create_repo),
            commit_message=str(args.commit_message or "Refresh canonical state laws corpus"),
        )

    incremental_materialization_results: List[Dict[str, Any]] = []
    incremental_publish_results: List[Dict[str, Any]] = []
    pending_acquisition_finalizations: Dict[str, Dict[str, Any]] = {}
    worker_gate_failed_states: set[str] = set()
    run_finalization_failed_states: set[str] = set()
    run_finalization_failure_reasons: Dict[str, str] = {}
    nonquiescent_marker_paths: set[str] = set()
    run_seal_result: Dict[str, Any] | None = None
    state_completion_lock = asyncio.Lock()
    progress_heartbeat_seconds = max(10.0, float(getattr(args, "progress_heartbeat_seconds", 60.0)))

    async def _progress_heartbeat_loop(stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=progress_heartbeat_seconds)
                break
            except asyncio.TimeoutError:
                pass
            except Exception:
                break
            progress_state["status"] = "running"
            _recompute_progress_counts()
            _write_progress_state()

    async def _on_state_complete(state_result: Dict[str, Any]) -> None:
        async with state_completion_lock:
            state_code = str((state_result or {}).get("state_code") or "").strip().upper()
            statute_data = (state_result or {}).get("statute_data") or {}
            state_status = "error"
            materialization_result: Dict[str, Any] | None = None
            state_acquisition_evidence: Dict[str, Any] = {}
            raw_worker_quiescence = (state_result or {}).get("worker_quiescence")
            worker_quiescence = (
                dict(raw_worker_quiescence)
                if isinstance(raw_worker_quiescence, Mapping)
                else {}
            )
            worker_quiescent = bool(
                worker_quiescence.get("attested") is True
                and worker_quiescence.get("quiescent") is True
            )
            state_identity_evidence: Dict[str, Any] = {
                "schema": _SOURCE_SOFTWARE_IMMUTABILITY_SCHEMA,
                "checks": [],
                "run_gate_passed": False,
            }
            if state_code:
                statutes_count = int((state_result or {}).get("statutes_count") or 0)
                if statutes_count <= 0 and isinstance(statute_data, dict):
                    statutes_count = len(list(statute_data.get("statutes") or []))
                error_text = str((state_result or {}).get("error") or "").strip()
                timeout_diagnostics_raw = (state_result or {}).get("timeout_diagnostics")
                timeout_diagnostics = (
                    dict(timeout_diagnostics_raw)
                    if isinstance(timeout_diagnostics_raw, Mapping)
                    else {}
                )
                timeout_classification = str(timeout_diagnostics.get("classification") or "").strip()
                timeout_signal_kind = str(timeout_diagnostics.get("signal_kind") or "").strip()
                timeout_work_remaining_value = timeout_diagnostics.get("work_remaining")
                timeout_work_remaining = (
                    timeout_work_remaining_value
                    if isinstance(timeout_work_remaining_value, bool)
                    else None
                )
                # Absence of a detectable remaining-work signal is not proof of
                # frontier closure. Keep every timeout as an error here; the
                # later checkpoint reconciliation may promote it only from an
                # explicit terminal/full-frontier checkpoint.
                state_status = "error" if error_text else ("zero_statutes" if statutes_count <= 0 else "success")
                state_name = str((state_result or {}).get("state_name") or (statute_data.get("state_name") if isinstance(statute_data, dict) else "") or "").strip()
                if not worker_quiescent:
                    worker_gate_failed_states.add(state_code)
                    worker_error = (
                        f"{state_code} worker quiescence was not proven; "
                        "the run is permanently non-authorizing"
                    )
                    error_text = (
                        f"{error_text}; {worker_error}" if error_text else worker_error
                    )
                    state_status = "error"
                    state_result["error"] = error_text
                    state_result["publication_authorized"] = False
                    state_result["retry_authorized"] = False
                    if isinstance(statute_data, dict):
                        statute_data["error"] = error_text
                    if acquisition_evidence_root is not None:
                        try:
                            marker_path = _write_nonquiescent_evidence_marker(
                                acquisition_evidence_root,
                                run_id=acquisition_run_id,
                                state_code=state_code,
                                worker_quiescence=worker_quiescence,
                            )
                            nonquiescent_marker_paths.add(str(marker_path))
                        except Exception as marker_exc:
                            worker_quiescence["marker_write_error"] = (
                                f"{type(marker_exc).__name__}: {marker_exc}"
                            )
                            _mark_run_finalization_failure(
                                state_code,
                                f"{state_code} worker quiescence was not proven "
                                "and permanent poison marker installation failed; "
                                "the durable in-progress lease remains non-authorizing: "
                                f"{type(marker_exc).__name__}: {marker_exc}",
                            )
                completion_identity_check = _check_state_source_software(
                    state_code,
                    phase="state_completion_before_materialization",
                )
                state_identity_evidence["checks"].append(completion_identity_check)
                state_identity_evidence["start_identity"] = (
                    source_software_start_identities.get(state_code)
                )
                state_identity_evidence["run_gate_passed"] = bool(
                    completion_identity_check.get("run_gate_passed") is True
                )
                state_result["source_software_immutability"] = (
                    state_identity_evidence
                )
                if not state_identity_evidence["run_gate_passed"]:
                    identity_error = source_software_gate_failure_reasons.get(
                        state_code
                    ) or _source_software_immutability_failure_detail(
                        completion_identity_check
                    )
                    gate_error = (
                        f"{state_code} source-software immutability gate failed: "
                        f"{identity_error}"
                    )
                    error_text = (
                        f"{error_text}; {gate_error}" if error_text else gate_error
                    )
                    state_status = "error"
                    state_result["error"] = error_text
                    if isinstance(statute_data, dict):
                        statute_data["error"] = error_text
                    state_acquisition_evidence = (
                        _block_acquisition_evidence_for_source_software_drift(
                            state_result.get("acquisition_evidence"),
                            verification=completion_identity_check,
                        )
                    )
                    state_result["acquisition_evidence"] = (
                        state_acquisition_evidence
                    )
                    if isinstance(statute_data, dict):
                        statute_data["acquisition_evidence"] = (
                            state_acquisition_evidence
                        )
                    if materialize_completed_states:
                        incremental_materialization_results.append(
                            {
                                "status": "error",
                                "state": state_code,
                                "reason": "source_software_immutability_failed",
                                "error": error_text,
                            }
                        )
                if state_status == "success" and materialize_completed_states:
                    try:
                        materialization_result = _materialize_completed_state_locally(
                            state_code=state_code,
                            state_name=state_name,
                            statute_data=statute_data,
                            statutes_count=statutes_count,
                            output_root=output_root,
                            jsonld_dir=jsonld_dir,
                            full_corpus_requested=int(args.max_statutes or 0) <= 0,
                            max_statutes=(
                                int(args.max_statutes)
                                if int(args.max_statutes or 0) > 0
                                else None
                            ),
                        )
                    except Exception as exc:
                        error_text = (
                            f"{state_code} local JSON-LD materialization failed: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        state_status = "error"
                        state_result["error"] = error_text
                        if isinstance(statute_data, dict):
                            statute_data["error"] = error_text
                        incremental_materialization_results.append(
                            {
                                "status": "error",
                                "state": state_code,
                                "error": error_text,
                            }
                        )
                    else:
                        incremental_materialization_results.append(
                            dict(materialization_result)
                        )
                if state_status == "success" and acquisition_evidence_root is not None:
                    raw_evidence = state_result.get("acquisition_evidence")
                    if not isinstance(raw_evidence, Mapping) and isinstance(
                        statute_data,
                        Mapping,
                    ):
                        raw_evidence = statute_data.get("acquisition_evidence")
                    state_acquisition_evidence = (
                        dict(raw_evidence) if isinstance(raw_evidence, Mapping) else {}
                    )
                    pending_aggregate = dict(
                        state_acquisition_evidence.get("aggregate") or {}
                    )
                    pending_aggregate.update(
                        {
                            "status": "pending_run_finalization",
                            "authorizing_for_publication": False,
                        }
                    )
                    state_acquisition_evidence["aggregate"] = pending_aggregate
                    state_acquisition_evidence[
                        "normalized_source_receipt_usable"
                    ] = False
                    state_result["acquisition_evidence"] = state_acquisition_evidence
                    if isinstance(statute_data, dict):
                        statute_data["acquisition_evidence"] = state_acquisition_evidence
                    pending_acquisition_finalizations[state_code] = {
                        "state_result": {
                            "state_code": state_code,
                            "acquisition_evidence": dict(state_acquisition_evidence),
                        },
                        "materialization_result": (
                            dict(materialization_result)
                            if isinstance(materialization_result, Mapping)
                            else None
                        ),
                    }
                state_entry = {
                    "state_code": state_code,
                    "state_name": state_name,
                    "status": state_status,
                    "statutes_count": statutes_count,
                    "completed_at": _utc_now_iso(),
                    "source_software_immutability": state_identity_evidence,
                    # A callback is never an authorization point.  This flips
                    # only after the run-final seal is durable.
                    "authorizing_for_publication": False,
                    "worker_quiescence": worker_quiescence,
                }
                if timeout_diagnostics:
                    state_entry["timeout_diagnostics"] = timeout_diagnostics
                if timeout_classification:
                    state_entry["timeout_classification"] = timeout_classification
                if timeout_signal_kind:
                    state_entry["timeout_signal_kind"] = timeout_signal_kind
                if timeout_work_remaining is not None:
                    state_entry["timeout_work_remaining"] = timeout_work_remaining
                if error_text:
                    state_entry["error"] = error_text
                if materialization_result is not None:
                    state_entry["incremental_materialization_status"] = "success"
                    state_entry["incremental_materialization_at"] = _utc_now_iso()
                    state_entry["jsonld_sha256"] = str(
                        materialization_result.get("jsonld_sha256") or ""
                    )
                    state_entry["jsonld_row_count"] = int(
                        materialization_result.get("row_count") or 0
                    )
                    state_entry["local_materialization_receipt"] = str(
                        materialization_result.get("receipt_path") or ""
                    )
                    state_entry["authorizing_coordinator_reuse"] = False
                elif state_status == "error" and "local JSON-LD materialization failed" in error_text:
                    state_entry["incremental_materialization_status"] = "error"
                if state_acquisition_evidence:
                    state_entry["acquisition_evidence"] = state_acquisition_evidence
                if state_status != "success":
                    pending_acquisition_finalizations.pop(state_code, None)
                results = progress_state.setdefault("state_results", {})
                if isinstance(results, dict):
                    existing_entry = results.get(state_code)
                    if isinstance(existing_entry, Mapping):
                        existing_status = str(existing_entry.get("status") or "").strip().lower()
                        try:
                            existing_count = int(existing_entry.get("statutes_count") or 0)
                        except Exception:
                            existing_count = 0

                        # Never downgrade a previously successful state to error.
                        if (
                            existing_status == "success"
                            and state_status != "success"
                            and not strict_acquisition_evidence
                            and state_code not in source_software_gate_failed_states
                            and state_code not in worker_gate_failed_states
                        ):
                            state_entry = dict(existing_entry)
                            state_entry["retry_result_disposition"] = "kept_prior_success"
                            state_entry["last_retry_completed_at"] = _utc_now_iso()
                        else:
                            # Preserve the best observed statute count across retries.
                            if existing_count > int(state_entry.get("statutes_count") or 0):
                                state_entry["statutes_count"] = existing_count
                            # Keep prior timeout diagnostics when the new attempt
                            # has a weaker payload.
                            for key in (
                                "timeout_diagnostics",
                                "timeout_classification",
                                "timeout_signal_kind",
                                "timeout_work_remaining",
                                "timeout_original_error",
                            ):
                                if key not in state_entry and key in existing_entry:
                                    state_entry[key] = existing_entry.get(key)
                    results[state_code] = state_entry
                _recompute_progress_counts()
                _write_progress_state()
                _write_completed_states_registry_snapshot()

            if state_status != "success":
                return
            if not publish_to_hf or not incremental_state_publish:
                return
            if not state_code or materialization_result is None:
                return
            publish_identity_check = _check_state_source_software(
                state_code,
                phase="state_completion_before_incremental_publish",
            )
            state_identity_evidence["checks"].append(publish_identity_check)
            state_identity_evidence["run_gate_passed"] = bool(
                publish_identity_check.get("run_gate_passed") is True
            )
            if not state_identity_evidence["run_gate_passed"]:
                identity_error = source_software_gate_failure_reasons.get(
                    state_code
                ) or _source_software_immutability_failure_detail(
                    publish_identity_check
                )
                gate_error = (
                    f"{state_code} source-software immutability gate failed "
                    f"before incremental publish: {identity_error}"
                )
                blocked_evidence = (
                    _block_acquisition_evidence_for_source_software_drift(
                        state_acquisition_evidence,
                        verification=publish_identity_check,
                    )
                )
                state_result_entry = (
                    progress_state.get("state_results", {}).get(state_code)
                    if isinstance(progress_state.get("state_results"), dict)
                    else None
                )
                if isinstance(state_result_entry, dict):
                    state_result_entry["status"] = "error"
                    state_result_entry["error"] = gate_error
                    state_result_entry["authorizing_for_publication"] = False
                    state_result_entry["source_software_immutability"] = (
                        state_identity_evidence
                    )
                    state_result_entry["acquisition_evidence"] = blocked_evidence
                    state_result_entry["incremental_publish_status"] = "error"
                    state_result_entry["incremental_publish_error"] = gate_error
                    state_result_entry["incremental_publish_at"] = _utc_now_iso()
                incremental_publish_results.append(
                    {
                        "status": "error",
                        "state": state_code,
                        "reason": "source_software_immutability_failed",
                        "error": gate_error,
                    }
                )
                _recompute_progress_counts()
                _write_progress_state()
                _write_completed_states_registry_snapshot()
                return
            written_paths = [str(materialization_result["jsonld_path"])]
            state_jsonld_path = jsonld_dir / f"STATE-{state_code}.jsonld"
            if not state_jsonld_path.exists():
                incremental_publish_results.append(
                    {"status": "skipped", "state": state_code, "reason": "missing_state_jsonld_after_scrape"}
                )
                return
            print(f"[state_laws_refresh] incremental_publish state={state_code} stage=build", flush=True)
            build = build_state_laws_parquet_artifacts(
                states=[state_code],
                jsonld_dir=jsonld_dir,
                parquet_dir=parquet_dir,
                merge_existing_local=not bool(args.no_merge_existing_local),
                merge_hf_existing=bool(args.merge_hf_existing),
                repo_id=repo_id,
                token=hf_token,
            )
            state_parquet_path = parquet_dir / _CORPUS.state_parquet_filename(state_code)
            try:
                print(f"[state_laws_refresh] incremental_publish state={state_code} stage=upload", flush=True)
                publish = _publish_state_parquet_file(
                    state_code=state_code,
                    state_parquet_path=state_parquet_path,
                    repo_id=repo_id,
                    token=hf_token,
                    create_repo=bool(args.create_repo),
                    commit_message=f"{str(args.commit_message or 'Refresh canonical state laws corpus')} ({state_code})",
                )
                incremental_publish_results.append(
                    {
                        "status": "success",
                        "state": state_code,
                        "jsonld_paths": written_paths,
                        "build": build,
                        "publish": publish,
                    }
                )
                state_result_entry = progress_state.get("state_results", {}).get(state_code) if isinstance(progress_state.get("state_results"), dict) else None
                if isinstance(state_result_entry, dict):
                    state_result_entry["incremental_publish_status"] = "success"
                    state_result_entry["incremental_publish_at"] = _utc_now_iso()
                    _recompute_progress_counts()
                    _write_progress_state()
                    _write_completed_states_registry_snapshot()
                print(f"[state_laws_refresh] incremental_publish state={state_code} stage=done", flush=True)
            except Exception as exc:
                incremental_publish_results.append(
                    {
                        "status": "error",
                        "state": state_code,
                        "jsonld_paths": written_paths,
                        "build": build,
                        "error": str(exc),
                    }
                )
                state_result_entry = progress_state.get("state_results", {}).get(state_code) if isinstance(progress_state.get("state_results"), dict) else None
                if isinstance(state_result_entry, dict):
                    state_result_entry["incremental_publish_status"] = "error"
                    state_result_entry["incremental_publish_error"] = str(exc)
                    state_result_entry["incremental_publish_at"] = _utc_now_iso()
                    _recompute_progress_counts()
                    _write_progress_state()
                    _write_completed_states_registry_snapshot()

    scrape_result: Dict[str, Any] | None = None
    full_corpus_guard_audit: Dict[str, Any] | None = None
    checkpoint_reconciliation: Dict[str, Any] | None = None
    timeout_recovery_history: List[Dict[str, Any]] = []
    scrape_max_statutes_for_run: Optional[int] = None
    progress_heartbeat_stop: asyncio.Event | None = None
    progress_heartbeat_task: asyncio.Task[Any] | None = None
    if args.scrape:
        if not states:
            scrape_result = {
                "status": "skipped",
                "reason": "all_requested_states_already_completed",
                "requested_states": requested_states,
                "skipped_completed_states": skipped_completed_states,
            }
        else:
            scrape_max_statutes = int(args.max_statutes) if int(args.max_statutes or 0) > 0 else None
            scrape_max_statutes_for_run = scrape_max_statutes
            if scrape_max_statutes is None and not bool(getattr(args, "skip_full_corpus_guard_audit", False)):
                full_corpus_guard_audit = _run_full_corpus_guard_audit(states=states)
                if str(full_corpus_guard_audit.get("status")) != "pass":
                    return {
                        "status": "failed_preflight",
                        "reason": "full_corpus_guard_audit_failed",
                        "plan": plan,
                        "full_corpus_guard_audit": full_corpus_guard_audit,
                    }
            progress_heartbeat_stop = asyncio.Event()
            progress_heartbeat_task = asyncio.create_task(_progress_heartbeat_loop(progress_heartbeat_stop))
            try:
                # Several state scrapers intentionally keep normal probes bounded
                # unless this scope is active. Apply it to this pass and every
                # recovery pass so an uncapped refresh cannot silently fall back
                # to sample-sized state shards.
                with _state_scraper_run_environment(
                    output_root=output_root,
                    full_corpus=scrape_max_statutes is None,
                    acquisition_evidence_root=acquisition_evidence_root,
                    strict_acquisition_evidence=strict_acquisition_evidence,
                    retained_replay_only=retained_replay_only,
                ):
                    scrape_result = await scrape_state_laws(
                        states=states,
                        legal_areas=None,
                        output_format="json",
                        include_metadata=True,
                        rate_limit_delay=float(args.rate_limit_delay),
                        max_statutes=scrape_max_statutes,
                        use_state_specific_scrapers=True,
                        allow_justia_fallback=bool(args.allow_justia_fallback),
                        output_dir=str(output_root),
                        write_jsonld=True,
                        strict_full_text=bool(args.strict_full_text),
                        min_full_text_chars=int(args.min_full_text_chars),
                        hydrate_statute_text=not bool(args.no_hydrate_statute_text),
                        parallel_workers=int(args.parallel_workers),
                        per_state_retry_attempts=int(args.per_state_retry_attempts),
                        retry_zero_statute_states=True,
                        per_state_timeout_seconds=float(args.per_state_timeout_seconds),
                        state_completion_callback=_on_state_complete,
                        retain_state_data=not materialize_completed_states,
                    )
            finally:
                if progress_heartbeat_stop is not None:
                    progress_heartbeat_stop.set()
                if progress_heartbeat_task is not None:
                    try:
                        await progress_heartbeat_task
                    except Exception:
                        pass

    if args.scrape:
        checkpoint_reconciliation = _reconcile_state_results_from_partial_checkpoints(
            progress_state=progress_state,
            checkpoint_dir=output_root / "partial_checkpoints",
            strict_acquisition_evidence=strict_acquisition_evidence,
        )
        _recompute_progress_counts()
        _write_progress_state()
        _write_completed_states_registry_snapshot()

        timeout_recovery_rounds = max(0, int(getattr(args, "timeout_recovery_rounds", 0) or 0))
        timeout_recovery_multiplier = max(1.0, float(getattr(args, "timeout_recovery_timeout_multiplier", 1.5) or 1.5))
        timeout_recovery_timeout_cap = max(0.0, float(getattr(args, "timeout_recovery_timeout_cap_seconds", 0.0) or 0.0))
        timeout_recovery_retry_attempts = max(
            int(args.per_state_retry_attempts or 0),
            int(getattr(args, "timeout_recovery_retry_attempts", 0) or 0),
        )
        timeout_recovery_parallel_workers = int(getattr(args, "timeout_recovery_parallel_workers", 0) or 0)
        if timeout_recovery_parallel_workers <= 0:
            timeout_recovery_parallel_workers = max(1, int(args.parallel_workers or 1))

        base_timeout_seconds = max(0.0, float(args.per_state_timeout_seconds or 0.0))
        for round_idx in range(timeout_recovery_rounds):
            retry_states = _eligible_timeout_recovery_states(
                states=states,
                progress_state=progress_state,
            )
            if not retry_states:
                break

            round_timeout_seconds = base_timeout_seconds
            if round_idx >= 0:
                round_timeout_seconds = base_timeout_seconds * (timeout_recovery_multiplier ** float(round_idx + 1))
            if timeout_recovery_timeout_cap > 0:
                round_timeout_seconds = min(round_timeout_seconds, timeout_recovery_timeout_cap)
            round_timeout_seconds = max(base_timeout_seconds, round_timeout_seconds)

            round_started_at = _utc_now_iso()
            with _state_scraper_run_environment(
                output_root=output_root,
                full_corpus=scrape_max_statutes_for_run is None,
                acquisition_evidence_root=acquisition_evidence_root,
                strict_acquisition_evidence=strict_acquisition_evidence,
                retained_replay_only=retained_replay_only,
            ):
                round_result = await scrape_state_laws(
                    states=retry_states,
                    legal_areas=None,
                    output_format="json",
                    include_metadata=True,
                    rate_limit_delay=float(args.rate_limit_delay),
                    max_statutes=scrape_max_statutes_for_run,
                    use_state_specific_scrapers=True,
                    allow_justia_fallback=bool(args.allow_justia_fallback),
                    output_dir=str(output_root),
                    write_jsonld=True,
                    strict_full_text=bool(args.strict_full_text),
                    min_full_text_chars=int(args.min_full_text_chars),
                    hydrate_statute_text=not bool(args.no_hydrate_statute_text),
                    parallel_workers=int(timeout_recovery_parallel_workers),
                    per_state_retry_attempts=int(timeout_recovery_retry_attempts),
                    retry_zero_statute_states=True,
                    per_state_timeout_seconds=float(round_timeout_seconds),
                    state_completion_callback=_on_state_complete,
                    retain_state_data=not materialize_completed_states,
                )

            round_reconciliation = _reconcile_state_results_from_partial_checkpoints(
                progress_state=progress_state,
                checkpoint_dir=output_root / "partial_checkpoints",
                strict_acquisition_evidence=strict_acquisition_evidence,
            )
            _recompute_progress_counts()
            _write_progress_state()
            _write_completed_states_registry_snapshot()

            timeout_recovery_history.append(
                {
                    "round": int(round_idx + 1),
                    "started_at": round_started_at,
                    "finished_at": _utc_now_iso(),
                    "states": list(retry_states),
                    "state_count": len(retry_states),
                    "per_state_timeout_seconds": float(round_timeout_seconds),
                    "parallel_workers": int(timeout_recovery_parallel_workers),
                    "per_state_retry_attempts": int(timeout_recovery_retry_attempts),
                    "scrape_status": str((round_result or {}).get("status") or ""),
                    "round_reconciliation": round_reconciliation,
                }
            )

    final_source_software_check: Dict[str, Any] | None = None
    worker_quiescence_by_state: Dict[str, Dict[str, Any]] = {}
    if args.scrape and states:
        progress_results_for_finalization = progress_state.get("state_results")
        progress_results_for_finalization = (
            progress_results_for_finalization
            if isinstance(progress_results_for_finalization, Mapping)
            else {}
        )
        for state_code in states:
            entry = progress_results_for_finalization.get(state_code)
            if not isinstance(entry, Mapping):
                _mark_run_finalization_failure(
                    state_code,
                    f"{state_code} has no lifecycle completion result",
                )
                continue
            worker_value = entry.get("worker_quiescence")
            worker = dict(worker_value) if isinstance(worker_value, Mapping) else {}
            if not (
                worker.get("attested") is True
                and worker.get("quiescent") is True
            ):
                worker_gate_failed_states.add(state_code)
                _mark_run_finalization_failure(
                    state_code,
                    f"{state_code} worker quiescence is not positively attested",
                )
                continue
            worker_quiescence_by_state[state_code] = worker
            if str(entry.get("status") or "").strip().lower() != "success":
                _mark_run_finalization_failure(
                    state_code,
                    f"{state_code} lifecycle did not finish successfully",
                )

        preclosure_runner_check = _check_refresh_runner_source_software(
            phase="run_quiescent_before_pending_receipt_closure",
        )
        preclosure_source_check = _verify_state_source_software_immutability(
            states=states,
            start_identities=source_software_start_identities,
            phase="run_quiescent_before_pending_receipt_closure",
        )
        _record_source_software_check(preclosure_source_check)

        pending_receipts: Dict[str, Path] = {}
        final_receipts: Dict[str, Path] = {}
        canonical_artifacts: Dict[str, Path] = {}
        run_seal_state_bindings: Dict[str, Dict[str, str]] = {}
        closed_evidence_by_state: Dict[str, Dict[str, Any]] = {}
        can_attempt_closure = bool(
            preclosure_runner_check.get("identities_equal") is True
            and preclosure_source_check.get("identities_equal") is True
            and not source_software_gate_failed_states
            and not worker_gate_failed_states
            and not run_finalization_failed_states
        )
        if acquisition_evidence_root is not None and can_attempt_closure:
            missing_pending = sorted(
                set(states).difference(pending_acquisition_finalizations)
            )
            for state_code in missing_pending:
                _mark_run_finalization_failure(
                    state_code,
                    f"{state_code} has no pending acquisition closure input",
                )

            if not run_finalization_failed_states:
                for state_code in states:
                    pending = pending_acquisition_finalizations[state_code]
                    state_evidence, acquisition_error = (
                        _close_incremental_state_acquisition_aggregate(
                            state_code=state_code,
                            state_result=pending["state_result"],
                            materialization_result=pending.get(
                                "materialization_result"
                            ),
                            acquisition_evidence_root=acquisition_evidence_root,
                            strict=True,
                            defer_normalized_receipt=True,
                        )
                    )
                    closed_evidence_by_state[state_code] = state_evidence
                    aggregate = state_evidence.get("aggregate")
                    aggregate = aggregate if isinstance(aggregate, Mapping) else {}
                    if acquisition_error or aggregate.get("status") != "closed_pending_run_seal":
                        _mark_run_finalization_failure(
                            state_code,
                            acquisition_error
                            or f"{state_code} pending source frontier did not close",
                        )
                        continue
                    pending_path = Path(
                        str(aggregate.get("normalized_source_receipt_path") or "")
                    ).expanduser().resolve()
                    if (
                        not pending_path.is_file()
                        or pending_path.is_symlink()
                        or not pending_path.name.endswith(
                            PENDING_NORMALIZED_RECEIPT_SUFFIX
                        )
                    ):
                        _mark_run_finalization_failure(
                            state_code,
                            f"{state_code} pending normalized receipt is absent or unsafe",
                        )
                        continue
                    try:
                        pending_bytes = pending_path.read_bytes()
                        pending_payload = json.loads(
                            pending_bytes.decode("utf-8", errors="strict")
                        )
                        if not isinstance(pending_payload, Mapping):
                            raise ValueError(
                                "pending normalized receipt is not a mapping"
                            )
                        validate_authorizing_transport_projection(pending_payload)
                        receipt_source_identity = str(
                            pending_payload.get("source_software_version") or ""
                        ).strip()
                        if (
                            receipt_source_identity
                            != source_software_start_identities[state_code]
                        ):
                            raise ValueError(
                                "pending normalized receipt source identity differs "
                                "from the run-start producer identity"
                            )
                        materialization = pending.get("materialization_result")
                        if not isinstance(materialization, Mapping):
                            raise ValueError("canonical materialization is missing")
                        canonical_path = Path(
                            str(materialization.get("jsonld_path") or "")
                        ).expanduser().resolve()
                        if not canonical_path.is_file() or canonical_path.is_symlink():
                            raise ValueError("canonical JSON-LD is absent or unsafe")
                        canonical_bytes = canonical_path.read_bytes()
                        canonical_sha256 = hashlib.sha256(
                            canonical_bytes
                        ).hexdigest()
                        declared_canonical_sha256 = str(
                            aggregate.get("canonical_jsonld_sha256") or ""
                        ).strip()
                        if declared_canonical_sha256 != canonical_sha256:
                            raise ValueError(
                                "closed receipt canonical JSON-LD digest mismatch"
                            )
                        typed_receipt = SourceReceiptRecord.from_mapping(
                            pending_payload
                        )
                        if typed_receipt.jurisdiction != state_code:
                            raise ValueError(
                                "pending normalized receipt jurisdiction differs "
                                "from the active state"
                            )
                        normalized_receipt = normalize_source_receipt(
                            typed_receipt,
                            input_path=canonical_path,
                            jurisdiction=state_code,
                            release_point=typed_receipt.release_point,
                            relative_path=typed_receipt.relative_path,
                            input_bytes=canonical_bytes,
                        )
                        if not normalized_receipt.admission_eligible:
                            raise ValueError(
                                "pending normalized receipt failed typed admission: "
                                + ",".join(
                                    normalized_receipt.qualification_reasons
                                )
                            )
                        if normalized_receipt.input_sha256 != canonical_sha256:
                            raise ValueError(
                                "typed receipt input digest differs from canonical bytes"
                            )
                        materialized_rows = int(
                            materialization.get("row_count") or 0
                        )
                        aggregate_rows = int(
                            aggregate.get("canonical_jsonld_row_count") or 0
                        )
                        if (
                            normalized_receipt.input_row_count != materialized_rows
                            or normalized_receipt.input_row_count != aggregate_rows
                        ):
                            raise ValueError(
                                "typed receipt canonical row count differs from "
                                "materialization/closure counts"
                            )
                        installed_size, installed_digest = file_digest(
                            canonical_path
                        )
                        if (
                            installed_size != len(canonical_bytes)
                            or installed_digest.hex() != canonical_sha256
                        ):
                            raise ValueError(
                                "canonical JSON-LD changed during typed receipt admission"
                            )
                    except Exception as exc:
                        _mark_run_finalization_failure(
                            state_code,
                            f"{state_code} pending receipt verification failed: "
                            f"{type(exc).__name__}: {exc}",
                        )
                        continue
                    pending_digest = hashlib.sha256(pending_bytes).hexdigest()
                    pending_receipts[state_code] = pending_path
                    final_receipts[state_code] = pending_path.with_name(
                        pending_path.name[: -len(PENDING_NORMALIZED_RECEIPT_SUFFIX)]
                        + ".normalized.json"
                    )
                    canonical_artifacts[state_code] = canonical_path
                    run_seal_state_bindings[state_code] = {
                        "canonical_jsonld_sha256": canonical_sha256,
                        "normalized_source_receipt_sha256": pending_digest,
                        "source_software_version": receipt_source_identity,
                    }

        final_runner_source_check = _check_refresh_runner_source_software(
            phase="run_completion_before_publication_authorization",
        )
        final_source_software_check = _verify_state_source_software_immutability(
            states=states,
            start_identities=source_software_start_identities,
            phase="run_completion_before_publication_authorization",
        )
        _record_source_software_check(final_source_software_check)
        for state_code in sorted(source_software_gate_failed_states):
            reason = source_software_gate_failure_reasons.get(
                state_code,
                "source identity equality was not proven",
            )
            _mark_run_finalization_failure(
                state_code,
                f"{state_code} source-software immutability gate failed: {reason}",
            )
            entry = progress_state.get("state_results", {}).get(state_code)
            if isinstance(entry, dict):
                state_identity = entry.get("source_software_immutability")
                state_identity = (
                    dict(state_identity)
                    if isinstance(state_identity, Mapping)
                    else {"schema": _SOURCE_SOFTWARE_IMMUTABILITY_SCHEMA}
                )
                state_identity["run_gate_passed"] = False
                state_identity["failure_reason"] = reason
                final_state_check = (
                    final_source_software_check.get("state_checks") or {}
                ).get(state_code)
                if isinstance(final_state_check, Mapping):
                    state_identity["final_check"] = dict(final_state_check)
                entry["source_software_immutability"] = state_identity
                entry["acquisition_evidence"] = (
                    _block_acquisition_evidence_for_source_software_drift(
                        entry.get("acquisition_evidence"),
                        verification=final_source_software_check,
                    )
                )
        if (
            acquisition_evidence_root is not None
            and source_software_gate_failed_states
        ):
            try:
                source_software_permanent_marker_path = str(
                    _write_source_software_immutability_evidence_marker(
                        acquisition_evidence_root,
                        run_id=acquisition_run_id,
                        failure_reasons={
                            state_code: source_software_gate_failure_reasons.get(
                                state_code,
                                "source identity equality was not proven",
                            )
                            for state_code in sorted(
                                source_software_gate_failed_states
                            )
                        },
                    )
                )
            except Exception as marker_exc:
                source_software_immutability[
                    "permanent_nonauthorization_marker_error"
                ] = f"{type(marker_exc).__name__}: {marker_exc}"
                for state_code in sorted(source_software_gate_failed_states):
                    _mark_run_finalization_failure(
                        state_code,
                        f"{state_code} source-software immutability failed and "
                        "permanent nonauthorization marker installation failed; "
                        "the durable in-progress lease remains non-authorizing: "
                        f"{type(marker_exc).__name__}: {marker_exc}",
                    )
        all_identities_stable = bool(
            final_runner_source_check.get("identities_equal") is True
            and final_source_software_check.get("identities_equal") is True
            and not source_software_gate_failed_states
        )

        if (
            acquisition_evidence_root is not None
            and all_identities_stable
            and not worker_gate_failed_states
            and not run_finalization_failed_states
            and set(run_seal_state_bindings) == set(states)
        ):
            seal_path = (
                acquisition_evidence_root
                / "run-seals"
                / f"{acquisition_run_id}{RUN_SEAL_SUFFIX}"
            )
            try:
                if acquisition_in_progress_marker_path is None:
                    raise RuntimeError("acquisition in-progress marker was not installed")
                _verify_acquisition_in_progress_marker(
                    acquisition_in_progress_marker_path,
                    run_id=acquisition_run_id,
                    expected_sha256=acquisition_in_progress_marker_sha256,
                )
                poison_path = (
                    acquisition_evidence_root / NONQUIESCENT_EVIDENCE_MARKER
                )
                if poison_path.exists() or poison_path.is_symlink():
                    raise RuntimeError(
                        "permanently nonauthorizing evidence poison appeared "
                        "before receipt promotion"
                    )

                # Promotion is intentionally non-authorizing: no run seal is
                # discoverable until every receipt has reached and retained
                # its exact final bytes.
                for state_code in states:
                    pending_path = pending_receipts[state_code]
                    final_path = final_receipts[state_code]
                    expected_digest = run_seal_state_bindings[state_code][
                        "normalized_source_receipt_sha256"
                    ]
                    try:
                        if final_path.exists() or final_path.is_symlink():
                            if final_path.is_symlink() or not final_path.is_file():
                                raise RuntimeError(
                                    "normalized receipt target is not a regular file"
                                )
                            _, existing_digest = file_digest(final_path)
                            if existing_digest.hex() != expected_digest:
                                raise RuntimeError(
                                    "normalized receipt target has conflicting bytes"
                                )
                            pending_path.unlink()
                        else:
                            os.replace(pending_path, final_path)
                        _, promoted_digest = file_digest(final_path)
                        if promoted_digest.hex() != expected_digest:
                            raise RuntimeError(
                                "promoted normalized receipt digest mismatch"
                            )
                    except Exception as exc:
                        _mark_run_finalization_failure(
                            state_code,
                            f"{state_code} normalized receipt promotion failed: "
                            f"{type(exc).__name__}: {exc}",
                        )
                if run_finalization_failed_states:
                    raise RuntimeError(
                        "one or more normalized receipt promotions failed"
                    )

                # Re-open every promoted receipt and canonical artifact before
                # the seal is constructed. A successful earlier observation
                # cannot authorize bytes that changed during promotion.
                for state_code in states:
                    final_path = final_receipts[state_code]
                    canonical_path = canonical_artifacts[state_code]
                    _, receipt_digest = file_digest(final_path)
                    _, canonical_digest = file_digest(canonical_path)
                    binding = run_seal_state_bindings[state_code]
                    if receipt_digest.hex() != binding[
                        "normalized_source_receipt_sha256"
                    ]:
                        raise RuntimeError(
                            f"{state_code} promoted receipt changed before sealing"
                        )
                    if canonical_digest.hex() != binding[
                        "canonical_jsonld_sha256"
                    ]:
                        raise RuntimeError(
                            f"{state_code} canonical artifact changed before sealing"
                        )

                seal_runner_source_check = _check_refresh_runner_source_software(
                    phase="immediately_before_run_seal_install",
                )
                seal_source_check = _verify_state_source_software_immutability(
                    states=states,
                    start_identities=source_software_start_identities,
                    phase="immediately_before_run_seal_install",
                )
                _record_source_software_check(seal_source_check)
                if (
                    seal_runner_source_check.get("identities_equal") is not True
                    or seal_source_check.get("identities_equal") is not True
                    or source_software_gate_failed_states
                ):
                    raise RuntimeError(
                        "source identity equality failed immediately before sealing"
                    )
                _verify_acquisition_in_progress_marker(
                    acquisition_in_progress_marker_path,
                    run_id=acquisition_run_id,
                    expected_sha256=acquisition_in_progress_marker_sha256,
                )
                if poison_path.exists() or poison_path.is_symlink():
                    raise RuntimeError(
                        "permanently nonauthorizing evidence poison appeared "
                        "before seal install"
                    )

                seal_payload = build_state_laws_run_seal(
                    run_id=acquisition_run_id,
                    created_at=_utc_now_iso(),
                    active_states=states,
                    start_identities=source_software_start_identities,
                    end_identities=dict(
                        seal_source_check.get("end_identities") or {}
                    ),
                    runner_start_identity=early_runner_source_software_identity,
                    runner_end_identity=str(
                        seal_runner_source_check.get("end_identity") or ""
                    ),
                    worker_quiescence=worker_quiescence_by_state,
                    states=run_seal_state_bindings,
                )
                seal_bytes = canonical_run_seal_bytes(seal_payload)
                atomic_write_bytes(seal_path, seal_bytes)
                seal_size, installed_seal_digest = file_digest(seal_path)
                seal_digest = installed_seal_digest.hex()
                if (
                    seal_size != len(seal_bytes)
                    or seal_digest != run_seal_sha256(seal_payload)
                ):
                    raise RuntimeError("installed run seal changed during verification")

                # Installing the seal is not yet authorization.  Recheck every
                # security boundary after the write, while the durable
                # non-authorizing lease is still present.  A daemon that became
                # observably nonquiescent during the seal write therefore
                # causes the just-installed seal to be removed in the exception
                # path without ever being reported as authorizing.
                _verify_acquisition_in_progress_marker(
                    acquisition_in_progress_marker_path,
                    run_id=acquisition_run_id,
                    expected_sha256=acquisition_in_progress_marker_sha256,
                )
                if poison_path.exists() or poison_path.is_symlink():
                    raise RuntimeError(
                        "permanently nonauthorizing evidence poison appeared "
                        "after seal install"
                    )
                post_seal_runner_source_check = (
                    _check_refresh_runner_source_software(
                        phase="after_run_seal_install_before_authorization",
                    )
                )
                post_seal_source_check = (
                    _verify_state_source_software_immutability(
                        states=states,
                        start_identities=source_software_start_identities,
                        phase="after_run_seal_install_before_authorization",
                    )
                )
                _record_source_software_check(post_seal_source_check)
                if (
                    post_seal_runner_source_check.get("identities_equal") is not True
                    or post_seal_source_check.get("identities_equal") is not True
                    or dict(post_seal_source_check.get("end_identities") or {})
                    != dict(seal_payload.get("end_identities") or {})
                    or str(post_seal_runner_source_check.get("end_identity") or "")
                    != str(seal_payload.get("runner_end_identity") or "")
                    or source_software_gate_failed_states
                ):
                    raise RuntimeError(
                        "source identity equality failed after seal install"
                    )
                for state_code in states:
                    _, receipt_digest = file_digest(final_receipts[state_code])
                    _, canonical_digest = file_digest(canonical_artifacts[state_code])
                    binding = run_seal_state_bindings[state_code]
                    if receipt_digest.hex() != binding[
                        "normalized_source_receipt_sha256"
                    ]:
                        raise RuntimeError(
                            f"{state_code} promoted receipt changed after seal install"
                        )
                    if canonical_digest.hex() != binding[
                        "canonical_jsonld_sha256"
                    ]:
                        raise RuntimeError(
                            f"{state_code} canonical artifact changed after seal install"
                        )
                _verify_acquisition_in_progress_marker(
                    acquisition_in_progress_marker_path,
                    run_id=acquisition_run_id,
                    expected_sha256=acquisition_in_progress_marker_sha256,
                )
                if poison_path.exists() or poison_path.is_symlink():
                    raise RuntimeError(
                        "permanently nonauthorizing evidence poison appeared "
                        "before lease release"
                    )
                acquisition_in_progress_marker_path.unlink()
                directory_flags = os.O_RDONLY
                if hasattr(os, "O_DIRECTORY"):
                    directory_flags |= os.O_DIRECTORY
                directory_descriptor = os.open(
                    acquisition_evidence_root,
                    directory_flags,
                )
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
                if acquisition_in_progress_marker_path.exists() or (
                    acquisition_in_progress_marker_path.is_symlink()
                ):
                    raise RuntimeError(
                        "acquisition in-progress marker remained after sealing"
                    )
                if poison_path.exists() or poison_path.is_symlink():
                    raise RuntimeError(
                        "permanently nonauthorizing evidence poison appeared "
                        "during lease release"
                    )
                final_seal_size, final_seal_digest = file_digest(seal_path)
                if (
                    final_seal_size != seal_size
                    or final_seal_digest.hex() != seal_digest
                ):
                    raise RuntimeError(
                        "installed run seal changed during lease release"
                    )
                run_seal_result = {
                    "status": "sealed",
                    "path": str(seal_path),
                    "sha256": seal_digest,
                    "size_bytes": seal_size,
                    "run_id": acquisition_run_id,
                    "active_states": list(states),
                    "authorizing_for_publication": True,
                }

                for state_code in states:
                    final_path = final_receipts[state_code]
                    entry = progress_state.get("state_results", {}).get(state_code)
                    if isinstance(entry, dict):
                        evidence = dict(closed_evidence_by_state[state_code])
                        aggregate = dict(evidence.get("aggregate") or {})
                        aggregate.update(
                            {
                                "status": "closed_and_normalized",
                                "authorizing_for_publication": True,
                                "normalized_source_receipt_path": str(final_path),
                                "run_seal_path": str(seal_path),
                                "run_seal_sha256": seal_digest,
                            }
                        )
                        evidence["aggregate"] = aggregate
                        evidence["normalized_source_receipt_usable"] = True
                        evidence["run_seal"] = dict(run_seal_result)
                        entry["acquisition_evidence"] = evidence
                        entry["authorizing_for_publication"] = True
                        entry["run_seal_path"] = str(seal_path)
                        entry["run_seal_sha256"] = seal_digest
            except Exception as exc:
                try:
                    seal_path.unlink(missing_ok=True)
                except OSError:
                    pass
                for state_code in states:
                    _mark_run_finalization_failure(
                        state_code,
                        f"run-final seal creation failed: {type(exc).__name__}: {exc}",
                    )
                run_seal_result = {
                    "status": "error",
                    "run_id": acquisition_run_id,
                    "error": f"{type(exc).__name__}: {exc}",
                    "authorizing_for_publication": False,
                }
        elif acquisition_evidence_root is not None:
            run_seal_result = {
                "status": "not_issued",
                "run_id": acquisition_run_id,
                "failed_states": sorted(
                    set(source_software_gate_failed_states)
                    | set(worker_gate_failed_states)
                    | set(run_finalization_failed_states)
                ),
                "authorizing_for_publication": False,
            }

        source_authorizing = bool(
            final_runner_source_check.get("identities_equal") is True
            and final_source_software_check.get("identities_equal") is True
            and not source_software_gate_failed_states
            and not worker_gate_failed_states
            and not run_finalization_failed_states
            and (
                acquisition_evidence_root is None
                or (
                    isinstance(run_seal_result, Mapping)
                    and run_seal_result.get("status") == "sealed"
                )
            )
        )
        source_software_immutability.update(
            {
                "status": "verified" if source_authorizing else "failed_closed",
                "finished_at": _utc_now_iso(),
                "end_identities": dict(
                    final_source_software_check.get("end_identities") or {}
                ),
                "runner_end_identity": (
                    final_runner_source_check.get("end_identity")
                ),
                "runner_identity_equal": bool(
                    final_runner_source_check.get("identities_equal") is True
                ),
                "runner_verification_error": (
                    final_runner_source_check.get("verification_error")
                ),
                "final_state_checks": dict(
                    final_source_software_check.get("state_checks") or {}
                ),
                "identities_equal": bool(
                    final_source_software_check.get("identities_equal") is True
                    and not source_software_gate_failed_states
                ),
                "failed_states": sorted(source_software_gate_failed_states),
                "failure_reasons": dict(
                    sorted(source_software_gate_failure_reasons.items())
                ),
                "verification_errors": dict(
                    final_source_software_check.get("verification_errors") or {}
                ),
                "worker_quiescence": worker_quiescence_by_state,
                "worker_quiescence_failed_states": sorted(worker_gate_failed_states),
                "run_finalization_failed_states": sorted(
                    run_finalization_failed_states
                ),
                "run_finalization_failure_reasons": dict(
                    sorted(run_finalization_failure_reasons.items())
                ),
                "run_seal": run_seal_result,
                "permanent_nonauthorization_marker_path": (
                    source_software_permanent_marker_path or None
                ),
                "authorizing_for_publication": source_authorizing,
            }
        )
        _recompute_progress_counts()
        _write_progress_state()
        _write_completed_states_registry_snapshot()
    else:
        source_software_immutability["finished_at"] = _utc_now_iso()

    build_result = build_state_laws_parquet_artifacts(
        states=requested_states,
        jsonld_dir=jsonld_dir,
        parquet_dir=parquet_dir,
        merge_existing_local=not bool(args.no_merge_existing_local),
        merge_hf_existing=bool(args.merge_hf_existing),
        repo_id=repo_id,
        token=hf_token,
    )

    scrape_gaps = []
    if isinstance(scrape_result, dict):
        metadata = scrape_result.get("metadata") or {}
        coverage = metadata.get("coverage_summary") or {}
        scrape_gaps = list(coverage.get("coverage_gap_states") or [])
    build_gaps = list(build_result.get("missing_jsonld_states") or [])
    progress_results = (
        progress_state.get("state_results")
        if isinstance(progress_state.get("state_results"), Mapping)
        else {}
    )
    acquisition_aggregate_closed_states: List[str] = []
    acquisition_evidence_gap_states: List[str] = []
    if acquisition_evidence_root is not None:
        for state_code in states:
            entry = progress_results.get(state_code)
            evidence = (
                entry.get("acquisition_evidence")
                if isinstance(entry, Mapping)
                and isinstance(entry.get("acquisition_evidence"), Mapping)
                else {}
            )
            aggregate = (
                evidence.get("aggregate")
                if isinstance(evidence.get("aggregate"), Mapping)
                else {}
            )
            if (
                aggregate.get("status") == "closed_and_normalized"
                and aggregate.get("authorizing_for_publication") is True
            ):
                acquisition_aggregate_closed_states.append(state_code)
            else:
                acquisition_evidence_gap_states.append(state_code)
    if strict_acquisition_evidence:
        scrape_gaps = list(
            dict.fromkeys([*scrape_gaps, *acquisition_evidence_gap_states])
        )
    if source_software_gate_failed_states:
        scrape_gaps = list(
            dict.fromkeys(
                [*scrape_gaps, *sorted(source_software_gate_failed_states)]
            )
        )
    if worker_gate_failed_states or run_finalization_failed_states:
        scrape_gaps = list(
            dict.fromkeys(
                [
                    *scrape_gaps,
                    *sorted(worker_gate_failed_states),
                    *sorted(run_finalization_failed_states),
                ]
            )
        )
    acquisition_evidence_summary = {
        "aggregate_closed_states": acquisition_aggregate_closed_states,
        "aggregate_closed_count": len(acquisition_aggregate_closed_states),
        "authorizing_for_publication": bool(
            acquisition_evidence_root is not None
            and not acquisition_evidence_gap_states
            and bool(states)
            and source_software_immutability.get("authorizing_for_publication")
            is True
            and isinstance(run_seal_result, Mapping)
            and run_seal_result.get("status") == "sealed"
        ),
        "evidence_gap_states": acquisition_evidence_gap_states,
        "evidence_root": (
            str(acquisition_evidence_root)
            if acquisition_evidence_root is not None
            else None
        ),
        "strict": strict_acquisition_evidence,
        "retained_replay_only": retained_replay_only,
        "transport_bypass_inventory": transport_bypass_inventory,
        "source_software_immutability_verified": bool(
            source_software_immutability.get("authorizing_for_publication") is True
        ),
        "worker_quiescence_failed_states": sorted(worker_gate_failed_states),
        "run_finalization_failed_states": sorted(run_finalization_failed_states),
        "run_finalization_failure_reasons": dict(
            sorted(run_finalization_failure_reasons.items())
        ),
        "run_seal": run_seal_result,
        "nonquiescent_marker_paths": sorted(nonquiescent_marker_paths),
        "permanent_nonauthorization_marker_paths": (
            [source_software_permanent_marker_path]
            if source_software_permanent_marker_path
            else sorted(nonquiescent_marker_paths)
        ),
    }
    is_complete = not scrape_gaps and not build_gaps

    publish_result: Dict[str, Any] | None = None
    production_set_ok = set(requested_states) == CANONICAL_PRODUCTION_JURISDICTIONS
    if args.publish_to_hf:
        if not bool(args.scrape):
            publish_result = {
                "status": "rejected",
                "reason": "unsealed_no_scrape_external_mutation_rejected",
                "detail": "publish through the sealed exact-51 production runner",
            }
        elif skipped_completed_states:
            publish_result = {
                "status": "rejected",
                "reason": "reused_inputs_require_sealed_production_runner",
                "detail": (
                    "an active-subset run seal cannot authorize reused jurisdiction "
                    "artifacts in a combined external publication"
                ),
                "reused_states": list(skipped_completed_states),
            }
        # Production final publish requires the exact 51-set (including DC).
        # Requested-scope completeness is not sufficient (LCR-007).
        elif not production_set_ok:
            publish_result = {
                "status": "rejected",
                "reason": "subset_release_rejected",
                "detail": (
                    "final combined production publish requires the exact "
                    f"{EXPECTED_PRODUCTION_JURISDICTION_COUNT}-jurisdiction set including DC; "
                    f"requested={len(requested_states)}"
                ),
                "requested_states": list(requested_states),
            }
        elif not is_complete and not bool(args.allow_incomplete_publish):
            publish_result = {
                "status": "skipped",
                "reason": "final_combined_publish_waits_for_complete_corpus",
                "detail": "Per-state startup sync and incremental completed-state publishes do not require complete all-state coverage.",
            }
        elif not is_complete and bool(args.allow_incomplete_publish):
            # Even with the flag, never promote a partial corpus to production.
            publish_result = {
                "status": "rejected",
                "reason": "partial_success_promotion_rejected",
                "detail": "allow_incomplete_publish cannot authorize a production combined release",
                "scrape_gap_states": list(scrape_gaps),
                "build_gap_states": list(build_gaps),
            }
        elif (
            args.scrape
            and states
            and source_software_immutability.get("authorizing_for_publication")
            is not True
        ):
            publish_result = {
                "status": "rejected",
                "reason": "run_final_authorization_missing",
                "detail": (
                    "external publication requires stable producer identities, "
                    "quiescent workers, and the run-final evidence seal"
                ),
            }
        elif args.scrape and not states:
            publish_result = {
                "status": "rejected",
                "reason": "all_reused_inputs_require_sealed_production_runner",
                "detail": (
                    "an all-reused refresh cannot mint a new run seal; publish "
                    "through the exact-51 production runner so every retained "
                    "receipt, artifact, run seal, and current runner identity "
                    "is reverified"
                ),
            }
        else:
            # Exact 51 and complete — still enforce the gate explicitly.
            try:
                reject_subset_release(requested_states, context="refresh_state_laws_corpus publish")
            except SubsetReleaseError as exc:
                publish_result = {
                    "status": "rejected",
                    "reason": "subset_release_rejected",
                    "detail": str(exc),
                }
            else:
                publication_source_check = None
                publication_runner_check = None
                if args.scrape and states:
                    publication_runner_check = (
                        _check_refresh_runner_source_software(
                            phase="immediately_before_external_publication",
                        )
                    )
                    publication_source_check = (
                        _verify_state_source_software_immutability(
                            states=states,
                            start_identities=source_software_start_identities,
                            phase="immediately_before_external_publication",
                        )
                    )
                    _record_source_software_check(publication_source_check)
                if (
                    (
                        publication_source_check is not None
                        and publication_source_check.get("identities_equal") is not True
                    )
                    or (
                        publication_runner_check is not None
                        and publication_runner_check.get("identities_equal") is not True
                    )
                ):
                    publish_result = {
                        "status": "rejected",
                        "reason": "source_software_changed_after_run_seal",
                        "detail": (
                            str(
                                (publication_runner_check or {}).get(
                                    "verification_error"
                                )
                                or ""
                            )
                            or _source_software_immutability_failure_detail(
                                publication_source_check or {}
                            )
                        ),
                    }
                else:
                    blocking_marker = None
                    if acquisition_evidence_root is not None:
                        for marker_name in (
                            NONQUIESCENT_EVIDENCE_MARKER,
                            IN_PROGRESS_EVIDENCE_MARKER,
                        ):
                            candidate = acquisition_evidence_root / marker_name
                            if candidate.exists() or candidate.is_symlink():
                                blocking_marker = candidate
                                break
                    if blocking_marker is not None:
                        publish_result = {
                            "status": "rejected",
                            "reason": "acquisition_evidence_root_nonauthorizing",
                            "detail": (
                                "a permanent-nonauthorization or in-progress "
                                "evidence marker "
                                "appeared immediately before publication"
                            ),
                            "marker_path": str(blocking_marker),
                        }
                    elif args.scrape and states and not (
                        isinstance(run_seal_result, Mapping)
                        and run_seal_result.get("status") == "sealed"
                        and run_seal_result.get("authorizing_for_publication")
                        is True
                    ):
                        publish_result = {
                            "status": "rejected",
                            "reason": "run_final_seal_missing",
                            "detail": (
                                "the active acquisition run has no authorizing "
                                "run-final seal immediately before publication"
                            ),
                        }
                    else:
                        publish_result = _publish_parquet_dir(
                            parquet_dir=parquet_dir,
                            repo_id=repo_id,
                            token=hf_token,
                            create_repo=bool(args.create_repo),
                            verify=bool(args.verify),
                            commit_message=str(
                                args.commit_message
                                or "Refresh canonical state laws corpus"
                            ),
                        )

    # Partial runs stay partial; never promote to production success.
    run_status = "success" if (is_complete and production_set_ok) else "partial_success"
    if is_complete and not production_set_ok:
        run_status = "partial_success"
    if source_software_gate_failed_states:
        run_status = "failed_source_software_immutability"
    elif worker_gate_failed_states:
        run_status = "failed_worker_nonquiescence"
    elif run_finalization_failed_states:
        run_status = "failed_acquisition_run_finalization"
    progress_state["status"] = run_status
    progress_state["finished_at"] = _utc_now_iso()
    progress_state["scrape_gap_states"] = list(scrape_gaps)
    progress_state["build_gap_states"] = list(build_gaps)
    progress_state["is_complete"] = bool(is_complete and production_set_ok)
    progress_state["exact_production_jurisdiction_set"] = bool(production_set_ok)
    progress_state["acquisition_evidence"] = acquisition_evidence_summary
    progress_state["source_software_immutability"] = (
        source_software_immutability
    )
    progress_state["acquisition_run_id"] = acquisition_run_id
    progress_state["run_seal"] = run_seal_result
    progress_state["worker_quiescence_failed_states"] = sorted(
        worker_gate_failed_states
    )
    _recompute_progress_counts()
    _write_progress_state()
    _write_completed_states_registry_snapshot()

    completed_registry_states = (
        completed_states_registry.get("states")
        if isinstance(completed_states_registry.get("states"), Mapping)
        else {}
    )

    return {
        "status": run_status,
        "acquisition_run_id": acquisition_run_id,
        "plan": plan,
        "scrape": scrape_result,
        "build": build_result,
        "startup_sync": startup_sync_result,
        "full_corpus_guard_audit": full_corpus_guard_audit,
        "checkpoint_reconciliation": checkpoint_reconciliation,
        "timeout_recovery": {
            "enabled": bool(args.scrape and int(getattr(args, "timeout_recovery_rounds", 0) or 0) > 0),
            "round_count": len(timeout_recovery_history),
            "rounds": timeout_recovery_history,
        },
        "progress_path": str(progress_path),
        "acquisition_evidence": acquisition_evidence_summary,
        "source_software_immutability": source_software_immutability,
        "run_seal": run_seal_result,
        "incremental_state_materialization": {
            "enabled": materialize_completed_states,
            "local_only": True,
            "authorizing_coordinator_reuse": False,
            "results": incremental_materialization_results,
            "success_count": sum(
                1
                for item in incremental_materialization_results
                if str(item.get("status")) == "success"
            ),
            "error_count": sum(
                1
                for item in incremental_materialization_results
                if str(item.get("status")) == "error"
            ),
        },
        "incremental_state_publish": {
            "enabled": bool(publish_to_hf and incremental_state_publish),
            "results": incremental_publish_results,
            "success_count": sum(1 for item in incremental_publish_results if str(item.get("status")) == "success"),
            "error_count": sum(1 for item in incremental_publish_results if str(item.get("status")) == "error"),
        },
        "publish": publish_result,
        "scrape_gap_states": scrape_gaps,
        "build_gap_states": build_gaps,
        "completed_states_registry": {
            "path": str(completed_states_registry_path),
            "persisted": bool(persist_completed_states_registry),
            "completed_state_count": len(completed_registry_states),
            "skipped_completed_states": skipped_completed_states,
            "baseline_path": str(completed_states_baseline_path),
            "baseline_loaded": bool(load_completed_states_baseline and completed_states_baseline_path.exists()),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh and publish the canonical state-laws corpus")
    parser.add_argument(
        "--states",
        default="all",
        help="Comma-separated state codes, or all (exactly 51 jurisdictions including DC)",
    )
    parser.add_argument(
        "--include-dc",
        action="store_true",
        help="Deprecated no-op: DC is always included in --states=all (LCR-007)",
    )
    parser.add_argument("--output-root", default="", help="Corpus output root; defaults to ~/.ipfs_datasets/state_laws")
    parser.add_argument("--jsonld-dir", default="", help="Override source JSON-LD directory")
    parser.add_argument("--parquet-dir", default="", help="Override destination parquet directory")
    parser.add_argument("--scrape", action="store_true", help="Run state scrapers before building parquet")
    parser.add_argument(
        "--acquisition-evidence-root",
        default="",
        help=(
            "Prospective per-jurisdiction parser-input evidence root. When set, "
            "the real state scraper attaches a content-addressed multi-fetch "
            "ledger before scrape_all."
        ),
    )
    parser.add_argument(
        "--strict-acquisition-evidence",
        action="store_true",
        help=(
            "Fail closed unless the ledger is attached, parser outputs and "
            "transport inventory are covered, and the canonical JSON-LD closes "
            "against a replayed official-source frontier projection."
        ),
    )
    parser.add_argument(
        "--retained-replay-only",
        action="store_true",
        help=(
            "Run the scraper offline from exact retained parser inputs only. "
            "An exact ledger miss fails before cache, direct HTTP, Common "
            "Crawl, Wayback, archive, browser, or remote-pointer access. "
            "Requires --scrape and --acquisition-evidence-root, implies "
            "--strict-acquisition-evidence, and forbids HF/remote operations."
        ),
    )
    parser.add_argument("--max-statutes", type=int, default=0, help="Optional cap across the scrape run; 0 means all")
    parser.add_argument("--rate-limit-delay", type=float, default=1.0)
    parser.add_argument("--parallel-workers", type=int, default=4)
    parser.add_argument("--per-state-retry-attempts", type=int, default=1)
    parser.add_argument("--per-state-timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--timeout-recovery-rounds",
        type=int,
        default=0,
        help="After the main scrape pass, retry timeout-error states for this many additional rounds.",
    )
    parser.add_argument(
        "--timeout-recovery-timeout-multiplier",
        type=float,
        default=1.5,
        help="Per recovery round timeout multiplier applied to --per-state-timeout-seconds.",
    )
    parser.add_argument(
        "--timeout-recovery-timeout-cap-seconds",
        type=float,
        default=0.0,
        help="Optional cap for recovery round per-state timeout; 0 disables cap.",
    )
    parser.add_argument(
        "--timeout-recovery-retry-attempts",
        type=int,
        default=2,
        help="Per-state retry attempts used during timeout-recovery rounds.",
    )
    parser.add_argument(
        "--timeout-recovery-parallel-workers",
        type=int,
        default=0,
        help="Parallel workers for timeout-recovery rounds; 0 uses --parallel-workers.",
    )
    parser.add_argument("--strict-full-text", action="store_true")
    parser.add_argument(
        "--min-full-text-chars",
        type=int,
        default=DEFAULT_MIN_FULL_TEXT_CHARS,
        help=(
            "Minimum non-empty statute-body length; defaults to 1 because valid "
            "public-law provisions may be short"
        ),
    )
    parser.add_argument("--no-hydrate-statute-text", action="store_true")
    parser.add_argument("--progress-heartbeat-seconds", type=float, default=60.0)
    parser.add_argument("--allow-justia-fallback", action="store_true")
    parser.add_argument("--no-merge-existing-local", action="store_true")
    parser.add_argument("--merge-hf-existing", action="store_true", help="Download and merge existing HF state parquet shards")
    parser.add_argument("--publish-to-hf", action="store_true")
    parser.add_argument(
        "--completed-states-registry",
        default="",
        help="Path to persistent completed-state registry JSON (default: ~/.ipfs_datasets/state_laws/state_laws_completed_states.json).",
    )
    parser.add_argument(
        "--completed-states-baseline",
        default="",
        help="Path to repo-tracked completed-state baseline JSON (default: scripts/ops/legal_data/state_laws_completed_states.baseline.json).",
    )
    parser.add_argument(
        "--no-load-completed-states-baseline",
        dest="load_completed_states_baseline",
        action="store_false",
        default=True,
        help="Do not load repo-tracked completed-state baseline before evaluating skips.",
    )
    parser.add_argument(
        "--no-skip-completed-states",
        dest="skip_completed_states",
        action="store_false",
        default=True,
        help=(
            "Do not reuse states admitted by the shared acquisition coordinator "
            "after receipt/frontier/local-output-byte verification. Registry-only "
            "completion rows never authorize a skip."
        ),
    )
    parser.add_argument(
        "--no-persist-completed-states-registry",
        dest="persist_completed_states_registry",
        action="store_false",
        default=True,
        help="Do not update the completed-state registry for this run.",
    )
    parser.add_argument(
        "--no-startup-stale-sync",
        dest="startup_stale_sync",
        action="store_false",
        default=True,
        help="Disable startup upload of local state shards that differ from Hugging Face.",
    )
    parser.add_argument(
        "--no-incremental-state-materialize",
        dest="incremental_state_materialize",
        action="store_false",
        default=True,
        help=(
            "Disable local atomic per-state JSON-LD materialization. By default "
            "successful callback payloads are persisted immediately and released "
            "from memory even when Hugging Face publication is disabled."
        ),
    )
    parser.add_argument(
        "--no-incremental-state-publish",
        dest="incremental_state_publish",
        action="store_false",
        default=True,
        help="Disable per-state HF upload as each state finishes scraping.",
    )
    parser.add_argument("--allow-incomplete-publish", action="store_true")
    parser.add_argument(
        "--skip-full-corpus-guard-audit",
        action="store_true",
        help="Skip the static full-corpus truncation audit before an uncapped scrape.",
    )
    parser.add_argument("--repo-id", default=_CORPUS.hf_dataset_id)
    parser.add_argument("--hf-token", default="")
    parser.add_argument("--create-repo", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--commit-message", default="Refresh canonical state laws corpus")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = asyncio.run(refresh_state_laws_corpus(args))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Status: {result.get('status')}")
        plan = result.get("plan") or {}
        print(f"States: {plan.get('state_count')} ({','.join(plan.get('states') or [])})")
        print(f"JSON-LD: {plan.get('jsonld_dir')}")
        print(f"Parquet: {plan.get('parquet_dir')}")
        build = result.get("build") or {}
        if build:
            print(f"Combined rows: {build.get('combined_row_count')}")
            print(f"Missing JSON-LD states: {','.join(build.get('missing_jsonld_states') or []) or 'None'}")
        if result.get("publish"):
            print(f"Publish: {(result.get('publish') or {}).get('upload_commit')}")
    status = str(result.get("status") or "").strip().lower()
    return 0 if status in {"success", "partial_success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
