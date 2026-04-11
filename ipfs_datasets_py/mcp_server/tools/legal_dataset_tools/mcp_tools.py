#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Legal Dataset MCP Tools — standalone function wrappers.

Business logic is in ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import get_canonical_legal_corpus
from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
    DEFAULT_CAP_CHUNK_HF_PARQUET_FILE,
    DEFAULT_CAP_HF_DATASET_ID,
    DEFAULT_CAP_HF_PARQUET_FILE,
    DEFAULT_FEDERAL_REGISTER_HF_DATASET_ID,
    DEFAULT_NETHERLANDS_LAWS_HF_DATASET_ID,
    DEFAULT_STATE_LAWS_HF_DATASET_ID,
    DEFAULT_COURT_RULES_HF_DATASET_ID,
    DEFAULT_USCODE_HF_DATASET_ID,
    DEFAULT_USCODE_HF_PARQUET_PREFIX,
)

logger = logging.getLogger(__name__)

_TOOL_VERSION = "1.0.0"
_STATE_LAWS_CORPUS = get_canonical_legal_corpus("state_laws")
_STATE_ADMIN_RULES_CORPUS = get_canonical_legal_corpus("state_admin_rules")
_STATE_COURT_RULES_CORPUS = get_canonical_legal_corpus("state_court_rules")
_FEDERAL_REGISTER_CORPUS = get_canonical_legal_corpus("federal_register")
_NETHERLANDS_CORPUS = get_canonical_legal_corpus("netherlands_laws")


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


async def scrape_state_admin_rules(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape state administrative rules and regulations."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_state_admin_rules_from_parameters,
    )
    return await scrape_state_admin_rules_from_parameters(parameters, tool_version=_TOOL_VERSION)


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


async def scrape_federal_laws(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape federal procedural rules and local court rules."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_federal_laws_from_parameters,
    )
    return await scrape_federal_laws_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def scrape_netherlands_laws(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape Netherlands laws from official Dutch government law sources."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_netherlands_laws_from_parameters,
    )
    return await scrape_netherlands_laws_from_parameters(parameters, tool_version=_TOOL_VERSION)


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


async def search_caselaw_access_cases(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search CAP vectors and enrich results with caselaw metadata/snippets by CID."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_caselaw_access_cases_from_parameters,
    )
    return await search_caselaw_access_cases_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_us_code_corpus(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search US Code corpus vectors and enrich with section metadata/snippets."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_us_code_corpus_from_parameters,
    )
    return await search_us_code_corpus_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_state_law_corpus(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search a state-law corpus vectors with optional statute metadata enrichment.

    Defaults combine the canonical multi-state corpora from:
    - ``justicedao/ipfs_state_laws``
    - ``justicedao/ipfs_state_admin_rules``
    """
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_state_law_corpus_from_parameters,
    )
    return await search_state_law_corpus_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_court_rules_corpus(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search federal/state court-rules corpus vectors with optional metadata enrichment."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_court_rules_corpus_from_parameters,
    )
    return await search_court_rules_corpus_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_federal_register_corpus(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search Federal Register corpus vectors with metadata enrichment."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_federal_register_corpus_from_parameters,
    )
    return await search_federal_register_corpus_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_netherlands_law_corpus(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search Netherlands law corpus vectors with metadata enrichment."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_netherlands_law_corpus_from_parameters,
    )
    return await search_netherlands_law_corpus_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def recover_missing_legal_citation_source(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Recover candidate official sources for an unresolved legal citation and optionally publish the manifest."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        recover_missing_legal_citation_source_from_parameters,
    )
    return await recover_missing_legal_citation_source_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_federal_register_hf_index(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search Federal Register directly from HF-hosted FAISS + metadata files."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_federal_register_hf_index_from_parameters,
    )
    return await search_federal_register_hf_index_from_parameters(parameters, tool_version=_TOOL_VERSION)


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


async def legal_search_brave(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Unified Brave legal search wrapper with dataset-style parameters."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch

        query = str(parameters.get("query") or "").strip()
        if not query:
            return {"status": "error", "error": "Missing required parameter: query"}

        max_results = int(parameters.get("max_results", 20))
        country = str(parameters.get("country", "US"))
        lang = str(parameters.get("lang", "en"))

        results = BraveLegalSearch().search(
            query=query,
            max_results=max_results,
            country=country,
            lang=lang,
        )
        return {"status": "success", **results}
    except Exception as exc:
        logger.error("legal_search_brave error: %s", exc)
        return {"status": "error", "error": str(exc)}


async def legal_search_brave_terms(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Generate optimized legal search terms from natural language query."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch

        query = str(parameters.get("query") or "").strip()
        if not query:
            return {"status": "error", "error": "Missing required parameter: query"}

        terms = BraveLegalSearch().generate_search_terms(query)
        return {"status": "success", "query": query, "search_terms": terms}
    except Exception as exc:
        logger.error("legal_search_brave_terms error: %s", exc)
        return {"status": "error", "error": str(exc)}


async def legal_search_brave_explain(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Explain legal query parsing and search-term generation."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch

        query = str(parameters.get("query") or "").strip()
        if not query:
            return {"status": "error", "error": "Missing required parameter: query"}

        details = BraveLegalSearch().explain_query(query)
        return {"status": "success", **details}
    except Exception as exc:
        logger.error("legal_search_brave_explain error: %s", exc)
        return {"status": "error", "error": str(exc)}


async def legal_search_entities(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search legal knowledge-base entities using dataset-style args."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch

        query = str(parameters.get("query") or "").strip()
        if not query:
            return {"status": "error", "error": "Missing required parameter: query"}

        entity_type = str(parameters.get("entity_type", "all"))
        searcher = BraveLegalSearch()
        if entity_type == "all":
            results = searcher.search_entities(query)
        else:
            results = searcher.search_entities(query, entity_type=entity_type)

        return {
            "status": "success",
            "query": query,
            "entity_type": entity_type,
            "results": results,
            "total_found": sum(len(v) for v in results.values()),
        }
    except Exception as exc:
        logger.error("legal_search_entities error: %s", exc)
        return {"status": "error", "error": str(exc)}


async def legal_search_web_archive(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Unified legal search across current web + archives."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch

        query = str(parameters.get("query") or "").strip()
        if not query:
            return {"status": "error", "error": "Missing required parameter: query"}

        max_results = int(parameters.get("max_results", 20))
        include_archives = bool(parameters.get("include_archives", False))
        archive_results = bool(parameters.get("archive_results", False))
        archive_dir: Optional[str] = parameters.get("archive_dir")

        searcher = LegalWebArchiveSearch(archive_dir=archive_dir, auto_archive=archive_results)
        results = searcher.unified_search(
            query=query,
            max_results=max_results,
            include_archives=include_archives,
            archive_results=archive_results,
        )
        return {"status": "success", **results}
    except Exception as exc:
        logger.error("legal_search_web_archive error: %s", exc)
        return {"status": "error", "error": str(exc)}


async def legal_search_archives_only(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search archived legal documents only."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch

        query = str(parameters.get("query") or "").strip()
        if not query:
            return {"status": "error", "error": "Missing required parameter: query"}

        results = LegalWebArchiveSearch().search_archives(
            query=query,
            from_date=parameters.get("from_date"),
            to_date=parameters.get("to_date"),
            domains=parameters.get("domains"),
            max_results=int(parameters.get("max_results", 50)),
        )
        return {"status": "success", **results}
    except Exception as exc:
        logger.error("legal_search_archives_only error: %s", exc)
        return {"status": "error", "error": str(exc)}


async def legal_archive_results(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Archive legal search results for preservation."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch

        query = str(parameters.get("query") or "").strip()
        results = parameters.get("results") or []
        if not query or not isinstance(results, list) or not results:
            return {"status": "error", "error": "Missing required parameters: query and results"}

        archive_dir: Optional[str] = parameters.get("archive_dir")
        info = LegalWebArchiveSearch(archive_dir=archive_dir)._archive_search_results(
            query=query,
            results=results,
            intent=None,
        )
        return {"status": "success", **info}
    except Exception as exc:
        logger.error("legal_archive_results error: %s", exc)
        return {"status": "error", "error": str(exc)}


async def legal_get_archive_stats(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Get archived legal-content statistics."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch

        archive_dir: Optional[str] = parameters.get("archive_dir")
        stats = LegalWebArchiveSearch(archive_dir=archive_dir).get_archive_stats()
        return {"status": "success", **stats}
    except Exception as exc:
        logger.error("legal_get_archive_stats error: %s", exc)
        return {"status": "error", "error": str(exc)}


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
    scrape_state_admin_rules,
    list_scraping_jobs,
    scrape_us_code,
    scrape_federal_laws,
    scrape_netherlands_laws,
    scrape_municipal_codes,
    setup_legal_tools_venv,
    ingest_caselaw_access_vectors,
    search_caselaw_access_vectors,
    search_caselaw_access_cases,
    search_us_code_corpus,
    search_state_law_corpus,
    search_court_rules_corpus,
    search_federal_register_corpus,
    search_netherlands_law_corpus,
    search_federal_register_hf_index,
    legal_search_brave,
    legal_search_brave_terms,
    legal_search_brave_explain,
    legal_search_entities,
    legal_search_web_archive,
    legal_search_archives_only,
    legal_archive_results,
    legal_get_archive_stats,
    list_caselaw_access_vector_files,
    search_caselaw_access_vectors_with_centroids,
    ingest_caselaw_access_vector_bundle,
]


CAP_LEGAL_DATASET_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "scrape_netherlands_laws",
        "description": "Scrape Netherlands laws from official Dutch government law pages.",
        "function": scrape_netherlands_laws,
        "parameters": {
            "document_urls": {"type": "array", "required": False},
            "seed_urls": {"type": "array", "required": False},
            "output_format": {"type": "string", "default": "json"},
            "output_dir": {"type": "string", "required": False},
            "rate_limit_delay": {"type": "number", "default": 0.4},
            "max_documents": {"type": "integer", "required": False},
            "include_metadata": {"type": "boolean", "default": True},
            "custom_sources": {"type": "array", "required": False},
        },
        "category": "legal_dataset_tools",
    },
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
        "name": "search_caselaw_access_cases",
        "description": "Search vectors and return caselaw details plus optional sparse chunk snippets.",
        "function": search_caselaw_access_cases,
        "parameters": {
            "collection_name": {"type": "string", "required": True},
            "query_vector": {"type": "array", "required": True},
            "store_type": {"type": "string", "default": "faiss"},
            "top_k": {"type": "integer", "default": 10},
            "hf_dataset_id": {"type": "string", "default": DEFAULT_CAP_HF_DATASET_ID},
            "hf_parquet_file": {"type": "string", "default": DEFAULT_CAP_HF_PARQUET_FILE},
            "cid_metadata_field": {"type": "string", "default": "cid"},
            "cid_column": {"type": "string", "default": "cid"},
            "text_field_candidates": {"type": "array", "required": False},
            "snippet_chars": {"type": "integer", "default": 320},
            "local_case_parquet_file": {"type": "string", "required": False},
            "chunk_lookup_enabled": {"type": "boolean", "default": True},
            "chunk_hf_dataset_id": {"type": "string", "default": DEFAULT_CAP_HF_DATASET_ID},
            "chunk_hf_parquet_file": {"type": "string", "default": DEFAULT_CAP_CHUNK_HF_PARQUET_FILE},
            "local_chunk_parquet_file": {"type": "string", "required": False},
            "chunk_snippet_chars": {"type": "integer", "default": 1000},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "search_us_code_corpus",
        "description": "Search US Code vector corpus and enrich matches with section metadata/snippets.",
        "function": search_us_code_corpus,
        "parameters": {
            "collection_name": {"type": "string", "required": True},
            "query_vector": {"type": "array", "required": True},
            "store_type": {"type": "string", "default": "faiss"},
            "top_k": {"type": "integer", "default": 10},
            "hf_dataset_id": {"type": "string", "default": DEFAULT_USCODE_HF_DATASET_ID},
            "hf_parquet_prefix": {"type": "string", "default": DEFAULT_USCODE_HF_PARQUET_PREFIX},
            "hf_parquet_file": {"type": "string", "required": False},
            "cid_metadata_field": {"type": "string", "default": "cid"},
            "cid_column": {"type": "string", "default": "cid"},
            "text_field_candidates": {"type": "array", "required": False},
            "snippet_chars": {"type": "integer", "default": 320},
            "local_case_parquet_file": {"type": "string", "required": False},
            "chunk_lookup_enabled": {"type": "boolean", "default": False},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "search_state_law_corpus",
        "description": f"Search state-law vector corpus (vector-first) with optional metadata enrichment; defaults combine {_STATE_LAWS_CORPUS.hf_dataset_id} and {_STATE_ADMIN_RULES_CORPUS.hf_dataset_id} under <STATE>/parsed/parquet.",
        "function": search_state_law_corpus,
        "parameters": {
            "collection_name": {"type": "string", "required": True},
            "query_vector": {"type": "array", "required": True},
            "state": {"type": "string", "default": "OR"},
            "store_type": {"type": "string", "default": "faiss"},
            "top_k": {"type": "integer", "default": 10},
            "enrich_with_cases": {"type": "boolean", "default": False},
            "hf_dataset_id": {"type": "string", "default": DEFAULT_STATE_LAWS_HF_DATASET_ID},
            "hf_dataset_ids": {"type": "array", "required": False},
            "hf_parquet_prefix": {"type": "string", "required": False},
            "hf_parquet_file": {"type": "string", "required": False},
            "hf_parquet_files": {"type": "array", "required": False},
            "max_case_parquet_files": {"type": "integer", "default": 0},
            "cid_metadata_field": {"type": "string", "default": "cid"},
            "cid_column": {"type": "string", "default": "cid"},
            "text_field_candidates": {"type": "array", "required": False},
            "snippet_chars": {"type": "integer", "default": 320},
            "local_case_parquet_file": {"type": "string", "required": False},
            "preferred_case_parquet_names": {"type": "array", "required": False},
            "chunk_lookup_enabled": {"type": "boolean", "default": False},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "search_court_rules_corpus",
        "description": f"Search court-rules vector corpus with federal/state jurisdiction filtering from {_STATE_COURT_RULES_CORPUS.hf_dataset_id}.",
        "function": search_court_rules_corpus,
        "parameters": {
            "collection_name": {"type": "string", "required": True},
            "query_vector": {"type": "array", "required": True},
            "jurisdiction": {"type": "string", "default": "both"},
            "state": {"type": "string", "required": False},
            "store_type": {"type": "string", "default": "faiss"},
            "top_k": {"type": "integer", "default": 10},
            "enrich_with_cases": {"type": "boolean", "default": True},
            "hf_dataset_id": {"type": "string", "default": DEFAULT_COURT_RULES_HF_DATASET_ID},
            "hf_dataset_ids": {"type": "array", "required": False},
            "hf_parquet_prefix": {"type": "string", "required": False},
            "hf_parquet_file": {"type": "string", "required": False},
            "hf_parquet_files": {"type": "array", "required": False},
            "max_case_parquet_files": {"type": "integer", "default": 24},
            "cid_metadata_field": {"type": "string", "default": "cid"},
            "cid_column": {"type": "string", "default": "cid"},
            "text_field_candidates": {"type": "array", "required": False},
            "snippet_chars": {"type": "integer", "default": 320},
            "local_case_parquet_file": {"type": "string", "required": False},
            "preferred_case_parquet_names": {"type": "array", "required": False},
            "chunk_lookup_enabled": {"type": "boolean", "default": False},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "search_federal_register_corpus",
        "description": "Search Federal Register vector corpus and enrich matches with document metadata/snippets.",
        "function": search_federal_register_corpus,
        "parameters": {
            "collection_name": {"type": "string", "required": True},
            "query_vector": {"type": "array", "required": True},
            "store_type": {"type": "string", "default": "faiss"},
            "top_k": {"type": "integer", "default": 10},
            "hf_dataset_id": {"type": "string", "default": DEFAULT_FEDERAL_REGISTER_HF_DATASET_ID},
            "hf_parquet_file": {"type": "string", "default": _FEDERAL_REGISTER_CORPUS.combined_parquet_filename},
            "hf_parquet_prefix": {"type": "string", "required": False},
            "cid_metadata_field": {"type": "string", "default": "ipfs_cid"},
            "cid_column": {"type": "string", "default": "ipfs_cid"},
            "text_field_candidates": {"type": "array", "required": False},
            "snippet_chars": {"type": "integer", "default": 320},
            "local_case_parquet_file": {"type": "string", "required": False},
            "preferred_case_parquet_names": {"type": "array", "required": False},
            "max_case_parquet_files": {"type": "integer", "default": 0},
            "chunk_lookup_enabled": {"type": "boolean", "default": False},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "search_netherlands_law_corpus",
        "description": "Search Netherlands law vector corpus and enrich matches with metadata/snippets.",
        "function": search_netherlands_law_corpus,
        "parameters": {
            "collection_name": {"type": "string", "required": True},
            "query_vector": {"type": "array", "required": True},
            "query_text": {"type": "string", "required": False},
            "citation_query": {"type": "string", "required": False},
            "store_type": {"type": "string", "default": "faiss"},
            "top_k": {"type": "integer", "default": 10},
            "hf_dataset_id": {"type": "string", "default": DEFAULT_NETHERLANDS_LAWS_HF_DATASET_ID},
            "hf_parquet_file": {"type": "string", "default": _NETHERLANDS_CORPUS.combined_parquet_filename},
            "hf_parquet_prefix": {"type": "string", "required": False},
            "cid_metadata_field": {"type": "string", "default": "ipfs_cid"},
            "cid_column": {"type": "string", "default": "ipfs_cid"},
            "text_field_candidates": {"type": "array", "required": False},
            "snippet_chars": {"type": "integer", "default": 320},
            "local_case_parquet_file": {"type": "string", "required": False},
            "preferred_case_parquet_names": {"type": "array", "required": False},
            "max_case_parquet_files": {"type": "integer", "default": 0},
            "chunk_lookup_enabled": {"type": "boolean", "default": False},
            "prefer_current_versions": {"type": "boolean", "default": True},
            "include_historical_versions": {"type": "boolean", "default": True},
            "as_of_date": {"type": "string", "required": False},
            "effective_date": {"type": "string", "required": False},
            "auto_setup_venv": {"type": "boolean", "default": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "recover_missing_legal_citation_source",
        "description": "Recover candidate official sources for an unresolved legal citation using search, archive, and optional HF publish steps.",
        "function": recover_missing_legal_citation_source,
        "parameters": {
            "citation_text": {"type": "string", "required": True},
            "normalized_citation": {"type": "string", "required": False},
            "corpus_key": {"type": "string", "required": False},
            "state": {"type": "string", "required": False},
            "state_code": {"type": "string", "required": False},
            "candidate_corpora": {"type": "array", "required": False},
            "metadata": {"type": "object", "required": False},
            "max_candidates": {"type": "integer", "default": 8},
            "archive_top_k": {"type": "integer", "default": 3},
            "publish_to_hf": {"type": "boolean", "default": False},
            "hf_token": {"type": "string", "required": False},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "search_federal_register_hf_index",
        "description": "Search Federal Register directly from HF-hosted FAISS index + metadata using query text.",
        "function": search_federal_register_hf_index,
        "parameters": {
            "query_text": {"type": "string", "required": True},
            "top_k": {"type": "integer", "default": 10},
            "hf_dataset_id": {"type": "string", "default": DEFAULT_FEDERAL_REGISTER_HF_DATASET_ID},
            "hf_index_file": {"type": "string", "default": "federal_register_gte_small.faiss"},
            "hf_metadata_file": {"type": "string", "default": "federal_register_gte_small_metadata.parquet"},
            "model_name": {"type": "string", "default": "thenlper/gte-small"},
            "snippet_chars": {"type": "integer", "default": 320},
            "hf_cache_dir": {"type": "string", "required": False},
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


LEGAL_SEARCH_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "legal_search_brave",
        "description": "Search legal web sources with Brave using natural-language query.",
        "function": legal_search_brave,
        "parameters": {
            "query": {"type": "string", "required": True},
            "max_results": {"type": "integer", "default": 20},
            "country": {"type": "string", "default": "US"},
            "lang": {"type": "string", "default": "en"},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "legal_search_brave_terms",
        "description": "Generate optimized legal search terms from natural-language query.",
        "function": legal_search_brave_terms,
        "parameters": {
            "query": {"type": "string", "required": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "legal_search_brave_explain",
        "description": "Explain how a legal query is parsed and translated into search terms.",
        "function": legal_search_brave_explain,
        "parameters": {
            "query": {"type": "string", "required": True},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "legal_search_entities",
        "description": "Search legal knowledge-base entities.",
        "function": legal_search_entities,
        "parameters": {
            "query": {"type": "string", "required": True},
            "entity_type": {"type": "string", "default": "all"},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "legal_search_web_archive",
        "description": "Unified search across current legal web and archive snapshots.",
        "function": legal_search_web_archive,
        "parameters": {
            "query": {"type": "string", "required": True},
            "max_results": {"type": "integer", "default": 20},
            "include_archives": {"type": "boolean", "default": False},
            "archive_results": {"type": "boolean", "default": False},
            "archive_dir": {"type": "string", "required": False},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "legal_search_archives_only",
        "description": "Search archived legal documents only, with optional date/domain filters.",
        "function": legal_search_archives_only,
        "parameters": {
            "query": {"type": "string", "required": True},
            "from_date": {"type": "string", "required": False},
            "to_date": {"type": "string", "required": False},
            "domains": {"type": "array", "required": False},
            "max_results": {"type": "integer", "default": 50},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "legal_archive_results",
        "description": "Archive legal search result records for future retrieval.",
        "function": legal_archive_results,
        "parameters": {
            "query": {"type": "string", "required": True},
            "results": {"type": "array", "required": True},
            "archive_dir": {"type": "string", "required": False},
        },
        "category": "legal_dataset_tools",
    },
    {
        "name": "legal_get_archive_stats",
        "description": "Get statistics for archived legal search data.",
        "function": legal_get_archive_stats,
        "parameters": {
            "archive_dir": {"type": "string", "required": False},
        },
        "category": "legal_dataset_tools",
    },
]

CAP_LEGAL_DATASET_TOOL_SPECS.extend(LEGAL_SEARCH_TOOL_SPECS)


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
    "scrape_state_admin_rules",
    "list_scraping_jobs",
    "scrape_us_code",
    "scrape_federal_laws",
    "scrape_netherlands_laws",
    "scrape_municipal_codes",
    "setup_legal_tools_venv",
    "ingest_caselaw_access_vectors",
    "search_caselaw_access_vectors",
    "search_caselaw_access_cases",
    "search_us_code_corpus",
    "search_state_law_corpus",
    "search_court_rules_corpus",
    "search_federal_register_corpus",
    "search_netherlands_law_corpus",
    "recover_missing_legal_citation_source",
    "search_federal_register_hf_index",
    "legal_search_brave",
    "legal_search_brave_terms",
    "legal_search_brave_explain",
    "legal_search_entities",
    "legal_search_web_archive",
    "legal_search_archives_only",
    "legal_archive_results",
    "legal_get_archive_stats",
    "list_caselaw_access_vector_files",
    "search_caselaw_access_vectors_with_centroids",
    "ingest_caselaw_access_vector_bundle",
    "CAP_LEGAL_DATASET_TOOL_SPECS",
    "LEGAL_SEARCH_TOOL_SPECS",
    "get_cap_legal_dataset_tool_specs",
    "register_cap_legal_dataset_tools",
    "LEGAL_DATASET_MCP_TOOLS",
]
