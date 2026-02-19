#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Temporal Deontic Logic RAG tools for MCP / CLI.

Implements MCP tools for the temporal deontic logic RAG system — a legal
debugger for document consistency checking.

Functions
---------
check_document_consistency
    Check a legal document against temporal deontic logic theorems.
query_theorems
    RAG-based semantic search of the theorem knowledge base.
bulk_process_caselaw
    Process entire caselaw corpora into a unified logic system.
add_theorem
    Add an individual temporal deontic logic theorem.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"


async def check_document_consistency(
    document_text: str,
    document_id: str = "auto_generated",
    jurisdiction: str = "Federal",
    legal_domain: str = "general",
    temporal_context: str = "current_time",
) -> Dict[str, Any]:
    """Check legal document consistency against temporal deontic logic theorems.

    Functions like a legal debugger: extracts deontic formulas and searches for
    conflicts using RAG-based retrieval over known theorems.

    Args:
        document_text: Legal document text to analyse.
        document_id: Optional document identifier.
        jurisdiction: Jurisdiction (Federal, State, EU, …).
        legal_domain: Domain hint (general, contract, criminal, …).
        temporal_context: Temporal reference point.

    Returns:
        Dict with consistency check results.
    """
    try:
        from ipfs_datasets_py.logic.integration.temporal_deontic_api import (
            check_document_consistency_from_parameters,
        )
        parameters = {
            "document_text": document_text,
            "document_id": document_id,
            "jurisdiction": jurisdiction,
            "legal_domain": legal_domain,
            "temporal_context": temporal_context,
        }
        return await check_document_consistency_from_parameters(parameters, tool_version=TOOL_VERSION)
    except ImportError:
        return {
            "success": False,
            "error": "temporal_deontic_api not available (optional dependency).",
            "document_id": document_id,
        }


async def query_theorems(
    query: str,
    operator_filter: str = "all",
    jurisdiction: str = "all",
    legal_domain: str = "all",
    limit: int = 10,
    min_relevance: float = 0.5,
) -> Dict[str, Any]:
    """RAG-based semantic search of temporal deontic logic theorems.

    Args:
        query: Natural language search query.
        operator_filter: Deontic operator filter (obligation, permission, prohibition, all).
        jurisdiction: Jurisdiction filter.
        legal_domain: Legal domain filter.
        limit: Maximum number of results (1–100).
        min_relevance: Minimum relevance threshold (0–1).

    Returns:
        Dict with matching theorems.
    """
    try:
        from ipfs_datasets_py.logic.integration.temporal_deontic_api import (
            query_theorems_from_parameters,
        )
        parameters = {
            "query": query,
            "operator_filter": operator_filter,
            "jurisdiction": jurisdiction,
            "legal_domain": legal_domain,
            "limit": limit,
            "min_relevance": min_relevance,
        }
        return await query_theorems_from_parameters(parameters, tool_version=TOOL_VERSION)
    except ImportError:
        return {"success": False, "error": "temporal_deontic_api not available."}


async def bulk_process_caselaw(
    caselaw_directories: Optional[List[str]] = None,
    output_directory: str = "unified_deontic_logic_system",
    max_concurrent_documents: int = 5,
    enable_parallel_processing: bool = True,
    min_precedent_strength: float = 0.5,
    jurisdictions_filter: Optional[List[str]] = None,
    legal_domains_filter: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    async_processing: bool = True,
) -> Dict[str, Any]:
    """Bulk process caselaw corpora into a unified temporal deontic logic system.

    Args:
        caselaw_directories: Directories containing caselaw documents.
        output_directory: Destination for the unified logic system.
        max_concurrent_documents: Concurrency limit.
        enable_parallel_processing: Enable parallel document processing.
        min_precedent_strength: Minimum strength threshold (0–1).
        jurisdictions_filter: Optional jurisdiction whitelist.
        legal_domains_filter: Optional domain whitelist.
        start_date: ISO date lower bound.
        end_date: ISO date upper bound.
        async_processing: Use async I/O for processing.

    Returns:
        Dict with processing results.
    """
    try:
        from ipfs_datasets_py.logic.integration.temporal_deontic_api import (
            bulk_process_caselaw_from_parameters,
        )
        parameters: Dict[str, Any] = {
            "caselaw_directories": caselaw_directories or [],
            "output_directory": output_directory,
            "max_concurrent_documents": max_concurrent_documents,
            "enable_parallel_processing": enable_parallel_processing,
            "min_precedent_strength": min_precedent_strength,
            "async_processing": async_processing,
        }
        if jurisdictions_filter is not None:
            parameters["jurisdictions_filter"] = jurisdictions_filter
        if legal_domains_filter is not None:
            parameters["legal_domains_filter"] = legal_domains_filter
        if start_date is not None:
            parameters["start_date"] = start_date
        if end_date is not None:
            parameters["end_date"] = end_date
        return await bulk_process_caselaw_from_parameters(parameters, tool_version=TOOL_VERSION)
    except ImportError:
        return {"success": False, "error": "temporal_deontic_api not available."}


async def add_theorem(
    operator: str,
    proposition: str,
    agent_name: str = "Unspecified Party",
    jurisdiction: str = "Federal",
    legal_domain: str = "general",
    source_case: str = "Test Case",
    precedent_strength: float = 0.8,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Add an individual temporal deontic logic theorem.

    Args:
        operator: Deontic operator (obligation | permission | prohibition).
        proposition: Theorem proposition text.
        agent_name: Agent the theorem applies to.
        jurisdiction: Legal jurisdiction.
        legal_domain: Legal domain.
        source_case: Source case citation.
        precedent_strength: Strength of the precedent (0–1).
        start_date: Optional ISO effective start date.
        end_date: Optional ISO effective end date.

    Returns:
        Dict with the added theorem metadata.
    """
    try:
        from ipfs_datasets_py.logic.integration.temporal_deontic_api import (
            add_theorem_from_parameters,
        )
        parameters: Dict[str, Any] = {
            "operator": operator,
            "proposition": proposition,
            "agent_name": agent_name,
            "jurisdiction": jurisdiction,
            "legal_domain": legal_domain,
            "source_case": source_case,
            "precedent_strength": precedent_strength,
        }
        if start_date is not None:
            parameters["start_date"] = start_date
        if end_date is not None:
            parameters["end_date"] = end_date
        return await add_theorem_from_parameters(parameters, tool_version=TOOL_VERSION)
    except ImportError:
        return {"success": False, "error": "temporal_deontic_api not available."}


__all__ = [
    "check_document_consistency",
    "query_theorems",
    "bulk_process_caselaw",
    "add_theorem",
]
