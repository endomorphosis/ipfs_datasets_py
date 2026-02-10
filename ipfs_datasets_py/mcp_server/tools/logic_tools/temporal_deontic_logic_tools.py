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

import anyio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

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
        from ipfs_datasets_py.logic.integration.temporal_deontic_api import (
            check_document_consistency_from_parameters,
        )

        return await check_document_consistency_from_parameters(
            parameters,
            tool_version=self.version,
        )


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
        from ipfs_datasets_py.logic.integration.temporal_deontic_api import query_theorems_from_parameters

        return await query_theorems_from_parameters(parameters, tool_version=self.version)


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
        from ipfs_datasets_py.logic.integration.temporal_deontic_api import bulk_process_caselaw_from_parameters

        return await bulk_process_caselaw_from_parameters(parameters, tool_version=self.version)


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
        from ipfs_datasets_py.logic.integration.temporal_deontic_api import add_theorem_from_parameters

        return await add_theorem_from_parameters(parameters, tool_version=self.version)


# Tool registry for MCP server
TEMPORAL_DEONTIC_LOGIC_TOOLS = [
    CheckDocumentConsistencyTool(),
    QueryTheoremsTool(),
    BulkProcessCaselawTool(),
    AddTheoremTool()
]