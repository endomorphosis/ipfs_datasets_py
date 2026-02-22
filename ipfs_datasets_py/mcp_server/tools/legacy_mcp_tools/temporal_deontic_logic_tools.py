#!/usr/bin/env python
from __future__ import annotations

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.logic_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.temporal_deontic_logic_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.logic_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def check_document_consistency(
    document_text: str = "",
    document_id: Optional[str] = None,
    jurisdiction: str = "Federal",
    legal_domain: str = "general",
    temporal_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Check legal document consistency against temporal deontic logic theorems."""
    try:
        from ...logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
        from ...logic_integration.document_consistency_checker import DocumentConsistencyChecker

        if not document_text:
            return {"success": False, "error": "Document text is required", "error_code": "MISSING_DOCUMENT_TEXT"}

        doc_id = document_id or f"doc_{int(time.time())}"
        tc = datetime.now()
        if temporal_context and temporal_context != "current_time":
            try:
                tc = datetime.fromisoformat(temporal_context)
            except ValueError:
                pass

        rag_store = TemporalDeonticRAGStore()
        checker = DocumentConsistencyChecker(rag_store=rag_store)
        analysis = checker.check_document(
            document_text=document_text,
            document_id=doc_id,
            temporal_context=tc,
            jurisdiction=jurisdiction,
            legal_domain=legal_domain,
        )
        debug_report = checker.generate_debug_report(analysis)
        return {
            "success": True,
            "document_id": analysis.document_id,
            "consistency_analysis": {
                "is_consistent": analysis.consistency_result.is_consistent if analysis.consistency_result else False,
                "confidence_score": analysis.confidence_score,
                "formulas_extracted": len(analysis.extracted_formulas),
                "issues_found": len(analysis.issues_found),
                "conflicts": len(analysis.consistency_result.conflicts) if analysis.consistency_result else 0,
                "temporal_conflicts": len(analysis.consistency_result.temporal_conflicts) if analysis.consistency_result else 0,
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
                "temporal_context": tc.isoformat(),
            },
        }
    except Exception as e:
        logger.error(f"Document consistency check failed: {e}")
        return {"success": False, "error": str(e), "error_code": "PROCESSING_ERROR"}


async def query_theorems(
    query: str = "",
    operator_filter: str = "all",
    jurisdiction: str = "all",
    legal_domain: str = "all",
    limit: int = 10,
    min_relevance: float = 0.5,
) -> Dict[str, Any]:
    """Query temporal deontic logic theorems using RAG retrieval."""
    try:
        from ...logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
        from ...logic_integration.deontic_logic_core import DeonticOperator

        if not query:
            return {"success": False, "error": "Query string is required", "error_code": "MISSING_QUERY"}

        rag_store = TemporalDeonticRAGStore()
        operator_enum = None
        if operator_filter != "all":
            try:
                operator_enum = DeonticOperator[operator_filter]
            except KeyError:
                pass

        results = rag_store.query_similar_theorems(
            query_text=query,
            top_k=limit,
            min_similarity=min_relevance,
            operator_filter=operator_enum,
            jurisdiction_filter=jurisdiction if jurisdiction != "all" else None,
            legal_domain_filter=legal_domain if legal_domain != "all" else None,
        )

        theorems = [
            {
                "theorem_id": r.theorem_id,
                "formula": {
                    "operator": r.formula.operator.name,
                    "proposition": r.formula.proposition,
                    "agent": r.formula.agent.name if r.formula.agent else "Unspecified",
                    "confidence": r.formula.confidence,
                },
                "metadata": {
                    "jurisdiction": r.metadata.jurisdiction,
                    "legal_domain": r.metadata.legal_domain,
                    "source_case": r.metadata.source_case,
                    "precedent_strength": r.metadata.precedent_strength,
                    "temporal_scope": {
                        "start": r.metadata.temporal_scope[0].isoformat(),
                        "end": r.metadata.temporal_scope[1].isoformat() if r.metadata.temporal_scope[1] else None,
                    },
                },
                "relevance_score": r.similarity_score,
                "embedding_match": r.embedding_similarity,
            }
            for r in results
        ]
        return {
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
            "metadata": {"query_time": datetime.now().isoformat()},
        }
    except Exception as e:
        logger.error(f"Theorem query failed: {e}")
        return {"success": False, "error": str(e), "error_code": "QUERY_ERROR"}


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
    """Bulk process caselaw documents to extract deontic logic theorems."""
    try:
        import os
        from ...logic_integration.caselaw_bulk_processor import CaselawBulkProcessor, BulkProcessingConfig

        directories = caselaw_directories or []
        if not directories:
            return {"success": False, "error": "At least one caselaw directory is required", "error_code": "MISSING_DIRECTORIES"}

        valid_dirs = [d.strip() for d in directories if d.strip() and os.path.exists(d.strip())]
        if not valid_dirs:
            return {"success": False, "error": "No valid caselaw directories found", "error_code": "INVALID_DIRECTORIES"}

        config = BulkProcessingConfig(
            caselaw_directories=valid_dirs,
            output_directory=output_directory,
            max_concurrent_documents=max_concurrent_documents,
            enable_parallel_processing=enable_parallel_processing,
            min_precedent_strength=min_precedent_strength,
            enable_consistency_validation=True,
            jurisdictions_filter=jurisdictions_filter,
            legal_domains_filter=legal_domains_filter,
        )
        if start_date:
            try:
                config.date_range = (datetime.fromisoformat(start_date), config.date_range[1])
            except ValueError:
                pass
        if end_date:
            try:
                config.date_range = (config.date_range[0], datetime.fromisoformat(end_date))
            except ValueError:
                pass

        if async_processing:
            session_id = str(uuid.uuid4())
            return {
                "success": True,
                "async_processing": True,
                "session_id": session_id,
                "status": "started",
                "message": "Bulk processing started - use session ID to monitor progress",
                "session_data": {
                    "session_id": session_id,
                    "status": "starting",
                    "start_time": datetime.now().isoformat(),
                    "config": {"directories": valid_dirs, "output_directory": output_directory, "concurrent_limit": max_concurrent_documents},
                    "progress": 0.0,
                },
            }

        processor = CaselawBulkProcessor(config)
        result = processor.process_caselaw_directories(directories=valid_dirs, progress_callback=None)
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
        }
    except Exception as e:
        logger.error(f"Bulk caselaw processing failed: {e}")
        return {"success": False, "error": str(e), "error_code": "PROCESSING_ERROR"}


async def add_theorem(
    operator: Optional[str] = None,
    proposition: str = "",
    agent_name: str = "Unspecified Party",
    jurisdiction: str = "Federal",
    legal_domain: str = "general",
    source_case: str = "Test Case",
    precedent_strength: float = 0.8,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a deontic logic theorem to the RAG store."""
    try:
        from ...logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
        from ...logic_integration.deontic_logic_core import DeonticFormula, DeonticOperator, LegalAgent

        if not proposition:
            return {"success": False, "error": "Proposition is required", "error_code": "MISSING_PROPOSITION"}

        if not operator:
            return {"success": False, "error": "Operator is required", "error_code": "MISSING_OPERATOR"}

        op_enum = DeonticOperator[operator]
        agent = LegalAgent(agent_name.lower().replace(" ", "_"), agent_name, "person")
        formula = DeonticFormula(
            operator=op_enum,
            proposition=proposition,
            agent=agent,
            confidence=0.9,
            source_text=f"{agent_name} {operator.lower()} {proposition}",
        )
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
        return {
            "success": True,
            "theorem_id": theorem_id,
            "message": f"Theorem added successfully from {source_case}",
            "theorem_data": {
                "operator": operator,
                "proposition": proposition,
                "agent": agent_name,
                "jurisdiction": jurisdiction,
                "legal_domain": legal_domain,
                "source_case": source_case,
                "precedent_strength": precedent_strength,
                "temporal_scope": {"start": temporal_scope[0].isoformat(), "end": temporal_scope[1].isoformat() if temporal_scope[1] else None},
            },
        }
    except Exception as e:
        logger.error(f"Failed to add theorem: {e}")
        return {"success": False, "error": str(e), "error_code": "ADD_THEOREM_ERROR"}


# Legacy class-based registry for backward compatibility
TEMPORAL_DEONTIC_LOGIC_TOOLS = [
    check_document_consistency,
    query_theorems,
    bulk_process_caselaw,
    add_theorem,
]
