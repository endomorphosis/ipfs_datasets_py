#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Package-level API for the Temporal Deontic Logic RAG system.

This module centralizes the core business logic used by MCP/CLI/SDK entrypoints.
MCP tool implementations should remain thin wrappers that delegate into these
functions.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import anyio

logger = logging.getLogger(__name__)


def _parse_temporal_context(value: Optional[str]) -> datetime:
    temporal_context = datetime.now()
    if value and value != "current_time":
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return temporal_context
    return temporal_context


async def check_document_consistency_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """MCP/CLI-friendly wrapper for document consistency checks."""

    def _run() -> Dict[str, Any]:
        from .temporal_deontic_rag_store import TemporalDeonticRAGStore
        from .document_consistency_checker import DocumentConsistencyChecker

        document_text = parameters.get("document_text", "")
        document_id = parameters.get("document_id", f"doc_{int(time.time())}")
        jurisdiction = parameters.get("jurisdiction", "Federal")
        legal_domain = parameters.get("legal_domain", "general")

        if not document_text:
            return {
                "success": False,
                "error": "Document text is required",
                "error_code": "MISSING_DOCUMENT_TEXT",
            }

        temporal_context = _parse_temporal_context(parameters.get("temporal_context"))

        rag_store = TemporalDeonticRAGStore()
        checker = DocumentConsistencyChecker(rag_store=rag_store)

        analysis = checker.check_document(
            document_text=document_text,
            document_id=document_id,
            temporal_context=temporal_context,
            jurisdiction=jurisdiction,
            legal_domain=legal_domain,
        )

        debug_report = checker.generate_debug_report(analysis)

        result: Dict[str, Any] = {
            "success": True,
            "document_id": analysis.document_id,
            "consistency_analysis": {
                "is_consistent": analysis.consistency_result.is_consistent
                if analysis.consistency_result
                else False,
                "confidence_score": analysis.confidence_score,
                "formulas_extracted": len(analysis.extracted_formulas),
                "issues_found": len(analysis.issues_found),
                "conflicts": len(analysis.consistency_result.conflicts)
                if analysis.consistency_result
                else 0,
                "temporal_conflicts": len(analysis.consistency_result.temporal_conflicts)
                if analysis.consistency_result
                else 0,
                "processing_time": analysis.processing_time,
            },
            "debug_report": {
                "total_issues": debug_report.total_issues,
                "critical_errors": debug_report.critical_errors,
                "warnings": debug_report.warnings,
                "suggestions": debug_report.suggestions,
                "issues": debug_report.issues[:10],
                "summary": debug_report.summary,
                "fix_suggestions": debug_report.fix_suggestions,
            },
            "extracted_formulas": [
                {
                    "operator": f.operator.name,
                    "proposition": f.proposition,
                    "agent": f.agent.name if f.agent else "Unspecified",
                    "confidence": f.confidence,
                }
                for f in analysis.extracted_formulas[:10]
            ],
            "metadata": {
                "jurisdiction": jurisdiction,
                "legal_domain": legal_domain,
                "temporal_context": temporal_context.isoformat(),
                "tool_version": tool_version,
            },
        }

        logger.info("Document consistency check completed: %s", document_id)
        return result

    try:
        return await anyio.to_thread.run_sync(_run)
    except Exception as e:
        logger.error("Document consistency check failed: %s", e)
        return {"success": False, "error": str(e), "error_code": "PROCESSING_ERROR"}


async def query_theorems_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """MCP/CLI-friendly wrapper for RAG-based theorem querying."""

    def _run() -> Dict[str, Any]:
        from .temporal_deontic_rag_store import TemporalDeonticRAGStore
        from ..integration.deontic_logic_core import DeonticOperator

        query = parameters.get("query", "")
        operator_filter = parameters.get("operator_filter", "all")
        jurisdiction = parameters.get("jurisdiction", "all")
        legal_domain = parameters.get("legal_domain", "all")
        limit = parameters.get("limit", 10)
        min_relevance = parameters.get("min_relevance", 0.5)

        if not query:
            return {"success": False, "error": "Query string is required", "error_code": "MISSING_QUERY"}

        rag_store = TemporalDeonticRAGStore()

        operator_enum = None
        if operator_filter != "all":
            try:
                operator_enum = DeonticOperator[operator_filter]
            except KeyError:
                operator_enum = None

        results = rag_store.query_similar_theorems(
            query_text=query,
            top_k=limit,
            min_similarity=min_relevance,
            operator_filter=operator_enum,
            jurisdiction_filter=jurisdiction if jurisdiction != "all" else None,
            legal_domain_filter=legal_domain if legal_domain != "all" else None,
        )

        theorems = []
        for result in results:
            theorems.append(
                {
                    "theorem_id": result.theorem_id,
                    "formula": {
                        "operator": result.formula.operator.name,
                        "proposition": result.formula.proposition,
                        "agent": result.formula.agent.name if result.formula.agent else "Unspecified",
                        "confidence": result.formula.confidence,
                    },
                    "metadata": {
                        "jurisdiction": result.metadata.jurisdiction,
                        "legal_domain": result.metadata.legal_domain,
                        "source_case": result.metadata.source_case,
                        "precedent_strength": result.metadata.precedent_strength,
                        "temporal_scope": {
                            "start": result.metadata.temporal_scope[0].isoformat(),
                            "end": result.metadata.temporal_scope[1].isoformat()
                            if result.metadata.temporal_scope[1]
                            else None,
                        },
                    },
                    "relevance_score": result.similarity_score,
                    "embedding_match": result.embedding_similarity,
                }
            )

        payload: Dict[str, Any] = {
            "success": True,
            "query": query,
            "total_results": len(theorems),
            "theorems": theorems,
            "filters_applied": {
                "operator": operator_filter,
                "jurisdiction": jurisdiction,
                "legal_domain": legal_domain,
                "min_relevance": min_relevance,
            },
            "metadata": {"tool_version": tool_version, "query_time": datetime.now().isoformat()},
        }

        logger.info("Theorem query completed: %s results for '%s'", len(theorems), query)
        return payload

    try:
        return await anyio.to_thread.run_sync(_run)
    except Exception as e:
        logger.error("Theorem query failed: %s", e)
        return {"success": False, "error": str(e), "error_code": "QUERY_ERROR"}


async def bulk_process_caselaw_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """MCP/CLI-friendly wrapper for bulk caselaw processing."""

    def _run() -> Dict[str, Any]:
        from .caselaw_bulk_processor import CaselawBulkProcessor, BulkProcessingConfig

        caselaw_directories = parameters.get("caselaw_directories", [])
        if not caselaw_directories:
            return {
                "success": False,
                "error": "At least one caselaw directory is required",
                "error_code": "MISSING_DIRECTORIES",
            }

        valid_directories = []
        for directory in caselaw_directories:
            directory = str(directory).strip()
            if directory and os.path.exists(directory):
                valid_directories.append(directory)
            elif directory:
                logger.warning("Directory not found: %s", directory)

        if not valid_directories:
            return {"success": False, "error": "No valid caselaw directories found", "error_code": "INVALID_DIRECTORIES"}

        config = BulkProcessingConfig(
            caselaw_directories=valid_directories,
            output_directory=parameters.get("output_directory", "unified_deontic_logic_system"),
            max_concurrent_documents=parameters.get("max_concurrent_documents", 5),
            enable_parallel_processing=parameters.get("enable_parallel_processing", True),
            min_precedent_strength=parameters.get("min_precedent_strength", 0.5),
            enable_consistency_validation=True,
            jurisdictions_filter=parameters.get("jurisdictions_filter"),
            legal_domains_filter=parameters.get("legal_domains_filter"),
        )

        if parameters.get("start_date"):
            try:
                start_date = datetime.fromisoformat(parameters["start_date"])
                config.date_range = (start_date, config.date_range[1])
            except ValueError:
                pass

        if parameters.get("end_date"):
            try:
                end_date = datetime.fromisoformat(parameters["end_date"])
                config.date_range = (config.date_range[0], end_date)
            except ValueError:
                pass

        processor = CaselawBulkProcessor(config)

        if parameters.get("async_processing", True):
            session_id = str(uuid.uuid4())
            session_data = {
                "session_id": session_id,
                "status": "starting",
                "start_time": datetime.now().isoformat(),
                "config": {
                    "directories": valid_directories,
                    "output_directory": config.output_directory,
                    "concurrent_limit": config.max_concurrent_documents,
                },
                "progress": 0.0,
            }
            return {
                "success": True,
                "async_processing": True,
                "session_id": session_id,
                "status": "started",
                "message": "Bulk processing started - use session ID to monitor progress",
                "session_data": session_data,
                "metadata": {"tool_version": tool_version},
            }

        result = processor.process_caselaw_directories(directories=valid_directories, progress_callback=None)

        return {
            "success": True,
            "async_processing": False,
            "processing_complete": True,
            "results": {
                "documents_processed": result.documents_processed,
                "theorems_extracted": result.theorems_extracted,
                "jurisdictions_covered": list(result.jurisdictions_covered),
                "legal_domains_covered": list(result.legal_domains_covered),
                "processing_time": result.total_processing_time,
                "unified_system_path": result.unified_system_path,
            },
            "statistics": result.processing_statistics,
            "metadata": {"tool_version": tool_version},
        }

    try:
        return await anyio.to_thread.run_sync(_run)
    except Exception as e:
        logger.error("Bulk caselaw processing failed: %s", e)
        return {"success": False, "error": str(e), "error_code": "PROCESSING_ERROR"}


async def add_theorem_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """MCP/CLI-friendly wrapper for adding a single theorem."""

    def _run() -> Dict[str, Any]:
        from .temporal_deontic_rag_store import TemporalDeonticRAGStore
        from ..integration.deontic_logic_core import DeonticFormula, DeonticOperator, LegalAgent

        operator_str = parameters.get("operator")
        proposition = parameters.get("proposition", "")
        agent_name = parameters.get("agent_name", "Unspecified Party")
        jurisdiction = parameters.get("jurisdiction", "Federal")
        legal_domain = parameters.get("legal_domain", "general")
        source_case = parameters.get("source_case", "Test Case")
        precedent_strength = parameters.get("precedent_strength", 0.8)

        if not proposition:
            return {"success": False, "error": "Proposition is required", "error_code": "MISSING_PROPOSITION"}

        operator = DeonticOperator[operator_str]
        agent = LegalAgent(agent_name.lower().replace(" ", "_"), agent_name, "person")

        formula = DeonticFormula(
            operator=operator,
            proposition=proposition,
            agent=agent,
            confidence=0.9,
            source_text=f"{agent_name} {operator_str.lower()} {proposition}",
        )

        start_date = parameters.get("start_date")
        end_date = parameters.get("end_date")

        temporal_scope = (
            datetime.fromisoformat(start_date) if start_date else datetime(2000, 1, 1),
            datetime.fromisoformat(end_date) if end_date else None,
        )

        rag_store = TemporalDeonticRAGStore()
        theorem_id = rag_store.add_theorem(
            formula=formula,
            temporal_scope=temporal_scope,
            jurisdiction=jurisdiction,
            legal_domain=legal_domain,
            source_case=source_case,
            precedent_strength=precedent_strength,
        )

        payload: Dict[str, Any] = {
            "success": True,
            "theorem_id": theorem_id,
            "message": f"Theorem added successfully from {source_case}",
            "theorem_data": {
                "operator": operator_str,
                "proposition": proposition,
                "agent": agent_name,
                "jurisdiction": jurisdiction,
                "legal_domain": legal_domain,
                "source_case": source_case,
                "precedent_strength": precedent_strength,
                "temporal_scope": {
                    "start": temporal_scope[0].isoformat(),
                    "end": temporal_scope[1].isoformat() if temporal_scope[1] else None,
                },
            },
            "metadata": {"tool_version": tool_version},
        }

        logger.info("Added theorem %s from %s", theorem_id, source_case)
        return payload

    try:
        return await anyio.to_thread.run_sync(_run)
    except Exception as e:
        logger.error("Failed to add theorem: %s", e)
        return {"success": False, "error": str(e), "error_code": "ADD_THEOREM_ERROR"}
