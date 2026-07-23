"""
PDF Processing Tools for MCP Server

This module provides MCP-compatible tools for comprehensive PDF processing,
including decomposition, OCR, LLM optimization, entity extraction, vector 
embedding, GraphRAG integration, and cross-document analysis.

The tools support the complete PDF processing pipeline:
PDF Input → Decomposition → IPLD Structuring → OCR Processing → 
LLM Optimization → Entity Extraction → Vector Embedding → 
IPLD GraphRAG Integration → Cross-Document Analysis → Query Interface

Extended pipeline (form intelligence):
Blank Form → Field Discovery → Knowledge Graph → Legal IR →
AI Agent Fill → Theorem Verification → ZKP Certificate
"""

from .pdf_ingest_to_graphrag import pdf_ingest_to_graphrag
from .pdf_query_corpus import pdf_query_corpus
from .pdf_query_knowledge_graph import pdf_query_knowledge_graph
from .pdf_analyze_relationships import pdf_analyze_relationships
from .pdf_batch_process import pdf_batch_process
from .pdf_extract_entities import pdf_extract_entities
from .pdf_optimize_for_llm import pdf_optimize_for_llm
from .pdf_cross_document_analysis import pdf_cross_document_analysis
from .pdf_fill_form_agent import pdf_fill_form_agent
from .pdf_generate_zkp_certificate import pdf_generate_zkp_certificate
from .pdf_verify_zkp_certificate import pdf_verify_zkp_certificate

__all__ = [
    'pdf_ingest_to_graphrag',
    'pdf_query_corpus',
    'pdf_query_knowledge_graph',
    'pdf_analyze_relationships',
    'pdf_batch_process',
    'pdf_extract_entities',
    'pdf_optimize_for_llm',
    'pdf_cross_document_analysis',
    'pdf_fill_form_agent',
    'pdf_generate_zkp_certificate',
    'pdf_verify_zkp_certificate',
]
