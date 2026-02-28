#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Legal Dataset MCP Tools — standalone function wrappers.

Business logic is in ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_TOOL_VERSION = "1.0.0"


async def scrape_recap_archive(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape federal court documents from RECAP Archive."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_recap_archive_from_parameters,
    )
    return await scrape_recap_archive_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_recap_documents(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search RECAP Archive for specific court documents."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_recap_documents_from_parameters,
    )
    return await search_recap_documents_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def scrape_state_laws(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape state legislation and statutes."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_state_laws_from_parameters,
    )
    return await scrape_state_laws_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def list_scraping_jobs(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """List all scraping jobs with resume capability."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        list_scraping_jobs_from_parameters,
    )
    return await list_scraping_jobs_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def scrape_us_code(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape United States Code sections."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_us_code_from_parameters,
    )
    return await scrape_us_code_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def scrape_municipal_codes(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape US municipal codes using scrape_the_law_mk3."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_municipal_codes_from_parameters,
    )
    return await scrape_municipal_codes_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def setup_legal_tools_venv(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Create/update .venv for legal vector dataset tooling."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        setup_legal_tools_venv_from_parameters,
    )
    return await setup_legal_tools_venv_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def ingest_caselaw_access_vectors(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest Caselaw Access Project embeddings into vector store."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        ingest_caselaw_access_vectors_from_parameters,
    )
    return await ingest_caselaw_access_vectors_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_caselaw_access_vectors(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search Caselaw Access Project vectors using a query embedding."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_caselaw_access_vectors_from_parameters,
    )
    return await search_caselaw_access_vectors_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def list_caselaw_access_vector_files(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """List CAP parquet/model files available for ingestion."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        list_caselaw_access_vector_files_from_parameters,
    )
    return await list_caselaw_access_vector_files_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_caselaw_access_vectors_with_centroids(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Run centroid-first two-stage retrieval against CAP vectors."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_caselaw_access_vectors_with_centroids_from_parameters,
    )
    return await search_caselaw_access_vectors_with_centroids_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def ingest_caselaw_access_vector_bundle(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest target and centroid CAP embeddings in one operation."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        ingest_caselaw_access_vector_bundle_from_parameters,
    )
    return await ingest_caselaw_access_vector_bundle_from_parameters(parameters, tool_version=_TOOL_VERSION)


# Import patent tools for backward compatibility
try:
    from .patent_dataset_mcp_tools import PATENT_DATASET_MCP_TOOLS
    _patent_tools_available = True
except ImportError:
    _patent_tools_available = False
    PATENT_DATASET_MCP_TOOLS = []

LEGAL_DATASET_MCP_TOOLS: List[Any] = [
    scrape_recap_archive,
    search_recap_documents,
    scrape_state_laws,
    list_scraping_jobs,
    scrape_us_code,
    scrape_municipal_codes,
    setup_legal_tools_venv,
    ingest_caselaw_access_vectors,
    search_caselaw_access_vectors,
    list_caselaw_access_vector_files,
    search_caselaw_access_vectors_with_centroids,
    ingest_caselaw_access_vector_bundle,
]


CAP_LEGAL_DATASET_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "setup_legal_tools_venv",
        "description": "Create/update .venv and install legal vector dependencies.",
        "function": setup_legal_tools_venv,
        "parameters": {
            "venv_dir": {"type": "string", "default": ".venv"},
            "packages": {"type": "array", "required": False},
            "upgrade_pip": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "list_caselaw_access_vector_files",
        "description": "List available CAP parquet files and inferred model names.",
        "function": list_caselaw_access_vector_files,
        "parameters": {
            "model_hint": {"type": "string", "required": False},
            "auto_setup_venv": {"type": "boolean", "default": True},
            "venv_dir": {"type": "string", "default": ".venv"},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "ingest_caselaw_access_vectors",
        "description": "Ingest one CAP embedding parquet source into a vector collection.",
        "function": ingest_caselaw_access_vectors,
        "parameters": {
            "collection_name": {"type": "string", "required": True},
            "store_type": {"type": "string", "default": "faiss"},
            "parquet_file": {"type": "string", "required": False},
            "model_hint": {"type": "string", "required": False},
            "max_rows": {"type": "integer", "default": 10000},
            "batch_size": {"type": "integer", "default": 512},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "ingest_caselaw_access_vector_bundle",
        "description": "Ingest both target and centroid CAP collections in one call.",
        "function": ingest_caselaw_access_vector_bundle,
        "parameters": {
            "target_collection_name": {"type": "string", "required": True},
            "centroid_collection_name": {"type": "string", "required": True},
            "store_type": {"type": "string", "default": "faiss"},
            "target_parquet_file": {"type": "string", "required": False},
            "centroid_parquet_file": {"type": "string", "required": False},
            "target_model_hint": {"type": "string", "required": False},
            "centroid_model_hint": {"type": "string", "required": False},
            "target_max_rows": {"type": "integer", "default": 10000},
            "centroid_max_rows": {"type": "integer", "default": 0},
            "batch_size": {"type": "integer", "default": 512},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "search_caselaw_access_vectors",
        "description": "Search CAP vectors in one collection using a precomputed query vector.",
        "function": search_caselaw_access_vectors,
        "parameters": {
            "collection_name": {"type": "string", "required": True},
            "query_vector": {"type": "array", "required": True},
            "store_type": {"type": "string", "default": "faiss"},
            "top_k": {"type": "integer", "default": 10},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "search_caselaw_access_vectors_with_centroids",
        "description": "Two-stage retrieval: centroid routing followed by filtered target search.",
        "function": search_caselaw_access_vectors_with_centroids,
        "parameters": {
            "target_collection_name": {"type": "string", "required": True},
            "centroid_collection_name": {"type": "string", "required": True},
            "query_vector": {"type": "array", "required": True},
            "store_type": {"type": "string", "default": "faiss"},
            "centroid_top_k": {"type": "integer", "default": 5},
            "per_cluster_top_k": {"type": "integer", "default": 20},
            "final_top_k": {"type": "integer", "default": 10},
            "cluster_metadata_field": {"type": "string", "default": "cluster_id"},
            "cluster_cids_parquet_file": {"type": "string", "required": False},
            "cid_metadata_field": {"type": "string", "default": "cid"},
            "cid_list_field": {"type": "string", "default": "cids"},
            "cluster_id_field_in_cid_map": {"type": "string", "default": "cluster_id"},
            "cid_candidate_multiplier": {"type": "integer", "default": 20},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
]


def get_cap_legal_dataset_tool_specs() -> List[Dict[str, Any]]:
    """Return CAP legal dataset tool specs with parameter metadata."""
    return CAP_LEGAL_DATASET_TOOL_SPECS


def register_cap_legal_dataset_tools(tool_registry: Any) -> None:
    """Register CAP legal dataset tools with a registry if available."""
    for spec in CAP_LEGAL_DATASET_TOOL_SPECS:
        fn = spec.get("function")
        if fn is None:
            continue
        try:
            tool_registry.register_tool(fn)
        except Exception:
            continue

if _patent_tools_available:
    LEGAL_DATASET_MCP_TOOLS.extend(PATENT_DATASET_MCP_TOOLS)

__all__ = [
    "scrape_recap_archive",
    "search_recap_documents",
    "scrape_state_laws",
    "list_scraping_jobs",
    "scrape_us_code",
    "scrape_municipal_codes",
    "setup_legal_tools_venv",
    "ingest_caselaw_access_vectors",
    "search_caselaw_access_vectors",
    "list_caselaw_access_vector_files",
    "search_caselaw_access_vectors_with_centroids",
    "ingest_caselaw_access_vector_bundle",
    "CAP_LEGAL_DATASET_TOOL_SPECS",
    "get_cap_legal_dataset_tool_specs",
    "register_cap_legal_dataset_tools",
    "LEGAL_DATASET_MCP_TOOLS",
]
