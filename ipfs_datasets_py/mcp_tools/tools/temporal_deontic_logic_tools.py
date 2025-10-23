#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Temporal Deontic Logic RAG Tools for MCP (Model Context Protocol).

This module implements MCP tools for the temporal deontic logic RAG system that
functions like a legal debugger for document consistency checking. It converts
the REST API endpoints into proper MCP tools that can be called via JSON-RPC.

Tools included:
- check_document_consistency: Check documents against deontic logic theorems
- query_theorems: RAG-based retrieval of relevant legal precedents  
- bulk_process_caselaw: Process entire caselaw databases
- add_theorem: Add individual theorems (for testing)

These tools enable legal document debugging capabilities through the MCP framework.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)


class CheckDocumentConsistencyTool(ClaudeMCPTool):
    """
    MCP Tool for checking document consistency against temporal deontic logic theorems.
    
    This tool functions like a legal debugger, analyzing documents for logical 
    consistency with existing legal theorems derived from caselaw. It extracts
    deontic logic formulas and checks for conflicts using RAG-based retrieval.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "check_document_consistency"
        self.description = "Check legal document consistency against temporal deontic logic theorems like a debugger"
        self.category = "legal_analysis"
        self.tags = ["legal", "deontic_logic", "rag", "consistency", "debugging"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "document_text": {
                    "type": "string",
                    "description": "Legal document text to analyze for consistency"
                },
                "document_id": {
                    "type": "string", 
                    "description": "Unique identifier for the document",
                    "default": "auto_generated"
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Legal jurisdiction (Federal, State, Supreme Court, etc.)",
                    "default": "Federal"
                },
                "legal_domain": {
                    "type": "string", 
                    "description": "Legal domain (Contract, Employment, IP, etc.)",
                    "default": "general"
                },
                "temporal_context": {
                    "type": "string",
                    "description": "ISO datetime string for temporal context analysis",
                    "default": "current_time"
                }
            },
            "required": ["document_text"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute document consistency checking against temporal deontic logic theorems.
        
        Args:
            parameters: Document text and analysis configuration
            
        Returns:
            Dictionary containing consistency analysis results, conflicts, and debug report
        """
        try:
            # Import required components
            from ...logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
            from ...logic_integration.document_consistency_checker import DocumentConsistencyChecker
            
            # Extract parameters
            document_text = parameters.get('document_text', '')
            document_id = parameters.get('document_id', f'doc_{int(time.time())}')
            jurisdiction = parameters.get('jurisdiction', 'Federal')
            legal_domain = parameters.get('legal_domain', 'general')
            
            if not document_text:
                return {
                    "success": False,
                    "error": "Document text is required",
                    "error_code": "MISSING_DOCUMENT_TEXT"
                }
            
            # Parse temporal context
            temporal_context = datetime.now()
            if parameters.get('temporal_context') and parameters['temporal_context'] != 'current_time':
                try:
                    temporal_context = datetime.fromisoformat(parameters['temporal_context'])
                except ValueError:
                    pass
            
            # Initialize RAG store and checker
            rag_store = TemporalDeonticRAGStore()
            checker = DocumentConsistencyChecker(rag_store=rag_store)
            
            # Perform consistency analysis
            analysis = checker.check_document(
                document_text=document_text,
                document_id=document_id,
                temporal_context=temporal_context,
                jurisdiction=jurisdiction,
                legal_domain=legal_domain
            )
            
            # Generate debug report
            debug_report = checker.generate_debug_report(analysis)
            
            # Format results
            result = {
                "success": True,
                "document_id": analysis.document_id,
                "consistency_analysis": {
                    "is_consistent": analysis.consistency_result.is_consistent if analysis.consistency_result else False,
                    "confidence_score": analysis.confidence_score,
                    "formulas_extracted": len(analysis.extracted_formulas),
                    "issues_found": len(analysis.issues_found),
                    "conflicts": len(analysis.consistency_result.conflicts) if analysis.consistency_result else 0,
                    "temporal_conflicts": len(analysis.consistency_result.temporal_conflicts) if analysis.consistency_result else 0,
                    "processing_time": analysis.processing_time
                },
                "debug_report": {
                    "total_issues": debug_report.total_issues,
                    "critical_errors": debug_report.critical_errors,
                    "warnings": debug_report.warnings,
                    "suggestions": debug_report.suggestions,
                    "issues": debug_report.issues[:10],  # Limit for response size
                    "summary": debug_report.summary,
                    "fix_suggestions": debug_report.fix_suggestions
                },
                "extracted_formulas": [
                    {
                        "operator": f.operator.name,
                        "proposition": f.proposition,
                        "agent": f.agent.name if f.agent else "Unspecified",
                        "confidence": f.confidence
                    } for f in analysis.extracted_formulas[:10]
                ],
                "metadata": {
                    "jurisdiction": jurisdiction,
                    "legal_domain": legal_domain,
                    "temporal_context": temporal_context.isoformat(),
                    "tool_version": self.version
                }
            }
            
            logger.info(f"Document consistency check completed: {document_id}")
            return result
            
        except Exception as e:
            logger.error(f"Document consistency check failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_code": "PROCESSING_ERROR"
            }


class QueryTheoremsTool(ClaudeMCPTool):
    """
    MCP Tool for RAG-based querying of temporal deontic logic theorems.
    
    This tool performs semantic search through the theorem corpus to find
    relevant legal precedents based on natural language queries or filters.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "query_theorems"
        self.description = "RAG-based semantic search of temporal deontic logic theorems from caselaw"
        self.category = "legal_analysis"
        self.tags = ["legal", "rag", "search", "theorems", "precedents"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query for relevant theorems"
                },
                "operator_filter": {
                    "type": "string",
                    "description": "Filter by deontic operator (OBLIGATION, PERMISSION, PROHIBITION)",
                    "enum": ["OBLIGATION", "PERMISSION", "PROHIBITION", "all"],
                    "default": "all"
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Filter by jurisdiction",
                    "default": "all"
                },
                "legal_domain": {
                    "type": "string",
                    "description": "Filter by legal domain",
                    "default": "all"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50
                },
                "min_relevance": {
                    "type": "number",
                    "description": "Minimum relevance score (0.0-1.0)",
                    "default": 0.5,
                    "minimum": 0.0,
                    "maximum": 1.0
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute RAG-based theorem query.
        
        Args:
            parameters: Query string and filtering options
            
        Returns:
            Dictionary containing relevant theorems with relevance scores
        """
        try:
            from ...logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
            from ...logic_integration.deontic_logic_core import DeonticOperator
            
            # Extract parameters
            query = parameters.get('query', '')
            operator_filter = parameters.get('operator_filter', 'all')
            jurisdiction = parameters.get('jurisdiction', 'all')
            legal_domain = parameters.get('legal_domain', 'all')
            limit = parameters.get('limit', 10)
            min_relevance = parameters.get('min_relevance', 0.5)
            
            if not query:
                return {
                    "success": False,
                    "error": "Query string is required",
                    "error_code": "MISSING_QUERY"
                }
            
            # Initialize RAG store
            rag_store = TemporalDeonticRAGStore()
            
            # Parse operator filter
            operator_enum = None
            if operator_filter != 'all':
                try:
                    operator_enum = DeonticOperator[operator_filter]
                except KeyError:
                    pass
            
            # Execute RAG query
            results = rag_store.query_similar_theorems(
                query_text=query,
                top_k=limit,
                min_similarity=min_relevance,
                operator_filter=operator_enum,
                jurisdiction_filter=jurisdiction if jurisdiction != 'all' else None,
                legal_domain_filter=legal_domain if legal_domain != 'all' else None
            )
            
            # Format results
            theorems = []
            for result in results:
                theorem_data = {
                    "theorem_id": result.theorem_id,
                    "formula": {
                        "operator": result.formula.operator.name,
                        "proposition": result.formula.proposition,
                        "agent": result.formula.agent.name if result.formula.agent else "Unspecified",
                        "confidence": result.formula.confidence
                    },
                    "metadata": {
                        "jurisdiction": result.metadata.jurisdiction,
                        "legal_domain": result.metadata.legal_domain,
                        "source_case": result.metadata.source_case,
                        "precedent_strength": result.metadata.precedent_strength,
                        "temporal_scope": {
                            "start": result.metadata.temporal_scope[0].isoformat(),
                            "end": result.metadata.temporal_scope[1].isoformat() if result.metadata.temporal_scope[1] else None
                        }
                    },
                    "relevance_score": result.similarity_score,
                    "embedding_match": result.embedding_similarity
                }
                theorems.append(theorem_data)
            
            result = {
                "success": True,
                "query": query,
                "total_results": len(theorems),
                "theorems": theorems,
                "filters_applied": {
                    "operator": operator_filter,
                    "jurisdiction": jurisdiction,
                    "legal_domain": legal_domain,
                    "min_relevance": min_relevance
                },
                "metadata": {
                    "tool_version": self.version,
                    "query_time": datetime.now().isoformat()
                }
            }
            
            logger.info(f"Theorem query completed: {len(theorems)} results for '{query}'")
            return result
            
        except Exception as e:
            logger.error(f"Theorem query failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_code": "QUERY_ERROR"
            }


class BulkProcessCaselawTool(ClaudeMCPTool):
    """
    MCP Tool for bulk processing of caselaw databases to build unified deontic logic systems.
    
    This tool processes entire caselaw corpora to extract temporal deontic logic
    theorems and build comprehensive legal knowledge systems.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "bulk_process_caselaw"
        self.description = "Bulk process entire caselaw databases to build unified temporal deontic logic systems"
        self.category = "legal_analysis"
        self.tags = ["legal", "bulk_processing", "caselaw", "deontic_logic", "corpus"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "caselaw_directories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of directories containing caselaw documents"
                },
                "output_directory": {
                    "type": "string",
                    "description": "Directory to save the unified deontic logic system",
                    "default": "unified_deontic_logic_system"
                },
                "max_concurrent_documents": {
                    "type": "integer",
                    "description": "Maximum number of documents to process concurrently",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20
                },
                "enable_parallel_processing": {
                    "type": "boolean",
                    "description": "Enable parallel processing for better performance",
                    "default": True
                },
                "min_precedent_strength": {
                    "type": "number",
                    "description": "Minimum precedent strength threshold",
                    "default": 0.5,
                    "minimum": 0.0,
                    "maximum": 1.0
                },
                "jurisdictions_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by specific jurisdictions"
                },
                "legal_domains_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by specific legal domains"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date for temporal filtering (ISO format)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date for temporal filtering (ISO format)"
                },
                "async_processing": {
                    "type": "boolean",
                    "description": "Run processing asynchronously and return session ID",
                    "default": True
                }
            },
            "required": ["caselaw_directories"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute bulk caselaw processing.
        
        Args:
            parameters: Processing configuration and directory paths
            
        Returns:
            Dictionary containing processing results or session ID for async processing
        """
        try:
            from ...logic_integration.caselaw_bulk_processor import (
                CaselawBulkProcessor, BulkProcessingConfig
            )
            import os
            
            # Extract parameters
            caselaw_directories = parameters.get('caselaw_directories', [])
            if not caselaw_directories:
                return {
                    "success": False,
                    "error": "At least one caselaw directory is required",
                    "error_code": "MISSING_DIRECTORIES"
                }
            
            # Validate directories
            valid_directories = []
            for directory in caselaw_directories:
                directory = directory.strip()
                if directory and os.path.exists(directory):
                    valid_directories.append(directory)
                elif directory:
                    logger.warning(f"Directory not found: {directory}")
            
            if not valid_directories:
                return {
                    "success": False,
                    "error": "No valid caselaw directories found",
                    "error_code": "INVALID_DIRECTORIES"
                }
            
            # Create processing configuration
            config = BulkProcessingConfig(
                caselaw_directories=valid_directories,
                output_directory=parameters.get('output_directory', 'unified_deontic_logic_system'),
                max_concurrent_documents=parameters.get('max_concurrent_documents', 5),
                enable_parallel_processing=parameters.get('enable_parallel_processing', True),
                min_precedent_strength=parameters.get('min_precedent_strength', 0.5),
                enable_consistency_validation=True,
                jurisdictions_filter=parameters.get('jurisdictions_filter'),
                legal_domains_filter=parameters.get('legal_domains_filter')
            )
            
            # Handle date filtering
            if parameters.get('start_date'):
                try:
                    start_date = datetime.fromisoformat(parameters['start_date'])
                    config.date_range = (start_date, config.date_range[1])
                except ValueError:
                    pass
            
            if parameters.get('end_date'):
                try:
                    end_date = datetime.fromisoformat(parameters['end_date'])
                    config.date_range = (config.date_range[0], end_date)
                except ValueError:
                    pass
            
            # Initialize processor
            processor = CaselawBulkProcessor(config)
            
            # Check if async processing requested
            if parameters.get('async_processing', True):
                # Create session for async processing
                session_id = str(uuid.uuid4())
                
                # Store session info (in real implementation, this would be persisted)
                session_data = {
                    "session_id": session_id,
                    "status": "starting",
                    "start_time": datetime.now().isoformat(),
                    "config": {
                        "directories": valid_directories,
                        "output_directory": config.output_directory,
                        "concurrent_limit": config.max_concurrent_documents
                    },
                    "progress": 0.0
                }
                
                # In real implementation, start async processing here
                # For now, return session info
                return {
                    "success": True,
                    "async_processing": True,
                    "session_id": session_id,
                    "status": "started",
                    "message": "Bulk processing started - use session ID to monitor progress",
                    "session_data": session_data
                }
            
            else:
                # Synchronous processing (for smaller datasets)
                result = processor.process_caselaw_directories(
                    directories=valid_directories,
                    progress_callback=None
                )
                
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
                        "unified_system_path": result.unified_system_path
                    },
                    "statistics": result.processing_statistics
                }
                
        except Exception as e:
            logger.error(f"Bulk caselaw processing failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_code": "PROCESSING_ERROR"
            }


class AddTheoremTool(ClaudeMCPTool):
    """
    MCP Tool for adding individual temporal deontic logic theorems (primarily for testing).
    
    This tool allows manual addition of theorems to the knowledge base, useful for
    testing and validation purposes.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "add_theorem"
        self.description = "Add individual temporal deontic logic theorem to the knowledge base"
        self.category = "legal_analysis"
        self.tags = ["legal", "theorem", "deontic_logic", "testing"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "operator": {
                    "type": "string",
                    "description": "Deontic operator type",
                    "enum": ["OBLIGATION", "PERMISSION", "PROHIBITION"]
                },
                "proposition": {
                    "type": "string",
                    "description": "The proposition or action being regulated"
                },
                "agent_name": {
                    "type": "string",
                    "description": "Name of the legal agent (person, organization, etc.)",
                    "default": "Unspecified Party"
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Legal jurisdiction",
                    "default": "Federal"
                },
                "legal_domain": {
                    "type": "string",
                    "description": "Legal domain or area of law",
                    "default": "general"
                },
                "source_case": {
                    "type": "string",
                    "description": "Source case or legal document",
                    "default": "Test Case"
                },
                "precedent_strength": {
                    "type": "number",
                    "description": "Precedent strength (0.0-1.0)",
                    "default": 0.8,
                    "minimum": 0.0,
                    "maximum": 1.0
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date for temporal scope (ISO format)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date for temporal scope (ISO format)"
                }
            },
            "required": ["operator", "proposition"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute theorem addition.
        
        Args:
            parameters: Theorem data and metadata
            
        Returns:
            Dictionary containing success status and theorem ID
        """
        try:
            from ...logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
            from ...logic_integration.deontic_logic_core import DeonticFormula, DeonticOperator, LegalAgent
            
            # Extract parameters
            operator_str = parameters.get('operator')
            proposition = parameters.get('proposition', '')
            agent_name = parameters.get('agent_name', 'Unspecified Party')
            jurisdiction = parameters.get('jurisdiction', 'Federal')
            legal_domain = parameters.get('legal_domain', 'general')
            source_case = parameters.get('source_case', 'Test Case')
            precedent_strength = parameters.get('precedent_strength', 0.8)
            
            if not proposition:
                return {
                    "success": False,
                    "error": "Proposition is required",
                    "error_code": "MISSING_PROPOSITION"
                }
            
            # Create deontic formula
            operator = DeonticOperator[operator_str]
            agent = LegalAgent(agent_name.lower().replace(' ', '_'), agent_name, "person")
            
            formula = DeonticFormula(
                operator=operator,
                proposition=proposition,
                agent=agent,
                confidence=0.9,
                source_text=f"{agent_name} {operator_str.lower()} {proposition}"
            )
            
            # Parse temporal scope
            start_date = parameters.get('start_date')
            end_date = parameters.get('end_date')
            
            temporal_scope = (
                datetime.fromisoformat(start_date) if start_date else datetime(2000, 1, 1),
                datetime.fromisoformat(end_date) if end_date else None
            )
            
            # Add to RAG store
            rag_store = TemporalDeonticRAGStore()
            theorem_id = rag_store.add_theorem(
                formula=formula,
                temporal_scope=temporal_scope,
                jurisdiction=jurisdiction,
                legal_domain=legal_domain,
                source_case=source_case,
                precedent_strength=precedent_strength
            )
            
            result = {
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
                        "end": temporal_scope[1].isoformat() if temporal_scope[1] else None
                    }
                }
            }
            
            logger.info(f"Added theorem {theorem_id} from {source_case}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to add theorem: {e}")
            return {
                "success": False,
                "error": str(e),
                "error_code": "ADD_THEOREM_ERROR"
            }


# Tool registry for MCP server
TEMPORAL_DEONTIC_LOGIC_TOOLS = [
    CheckDocumentConsistencyTool(),
    QueryTheoremsTool(),
    BulkProcessCaselawTool(),
    AddTheoremTool()
]