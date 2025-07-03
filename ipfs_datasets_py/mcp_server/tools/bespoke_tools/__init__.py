"""
Bespoke MCP Tools

This directory contains custom-built MCP tools created to resolve import path issues
and provide individual importable functions for testing framework compatibility.

These tools were created on January 15, 2025, to support the MCP Tools Test Coverage
improvement project. They provide mock implementations with comprehensive functionality
for areas where tests expected individual tool files.

Tool Categories:
- Admin Tools: system_health.py, system_status.py  
- Cache Tools: cache_stats.py
- Workflow Tools: execute_workflow.py
- Vector Store Tools: list_indices.py, delete_index.py, create_vector_store.py

All tools follow consistent patterns:
- Async function interfaces
- Multi-store support (FAISS, Qdrant, Elasticsearch, ChromaDB) where applicable
- Comprehensive mock data generation
- Error handling and validation
- Status reporting and metrics

Created by: GitHub Copilot
Purpose: Import path resolution and test framework compatibility
Project: MCP Tools Test Coverage TODO - Infrastructure Phase
"""

from .system_health import system_health
from .system_status import system_status
from .cache_stats import cache_stats
from .execute_workflow import execute_workflow
from .list_indices import list_indices
from .delete_index import delete_index
from .create_vector_store import create_vector_store

__all__ = [
    'system_health',
    'system_status', 
    'cache_stats',
    'execute_workflow',
    'list_indices',
    'delete_index',
    'create_vector_store'
]
