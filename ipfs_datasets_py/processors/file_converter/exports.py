#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File Converter Package Exports

Clean API exports for external consumption by CLI tools, MCP server tools,
and other interfaces. All functions are async-safe and include error handling.

This module provides a unified interface that can be used by:
- ipfs-datasets CLI
- MCP server tools
- MCP server dashboard (via JavaScript SDK)
- External applications
"""

import anyio
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import json

# Import all file_converter components
from . import (
    FileConverter,
    UniversalKnowledgeGraphPipeline,
    TextSummarizationPipeline,
    VectorEmbeddingPipeline,
    ArchiveHandler,
    URLHandler,
    extract_metadata,
    is_url,
    is_archive
)


# ============================================================================
# Core Conversion Functions
# ============================================================================

async def convert_file(
    input_path: str,
    backend: str = 'native',
    extract_archives: bool = False,
    output_format: str = 'text'
) -> Dict[str, Any]:
    """
    Convert a file or URL to text.
    
    Args:
        input_path: Path to file or URL
        backend: Conversion backend ('native', 'markitdown', 'omni', 'auto')
        extract_archives: Whether to extract and process archives
        output_format: Output format ('text', 'json')
    
    Returns:
        Dict with 'text', 'metadata', 'success', 'error'
    """
    try:
        converter = FileConverter(backend=backend)
        result = await converter.convert(input_path, extract_archives=extract_archives)
        
        return {
            'success': True,
            'text': result.text,
            'metadata': result.metadata if hasattr(result, 'metadata') else {},
            'format': result.metadata.get('format', 'unknown') if hasattr(result, 'metadata') else 'unknown',
            'source': input_path
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'source': input_path
        }


def convert_file_sync(
    input_path: str,
    backend: str = 'native',
    extract_archives: bool = False,
    output_format: str = 'text'
) -> Dict[str, Any]:
    """Synchronous wrapper for convert_file."""
    return anyio.run(convert_file, input_path, backend, extract_archives, output_format)


async def batch_convert_files(
    input_paths: List[str],
    backend: str = 'native',
    extract_archives: bool = False,
    max_concurrent: int = 5
) -> Dict[str, Any]:
    """
    Batch convert multiple files or URLs.
    
    Args:
        input_paths: List of file paths or URLs
        backend: Conversion backend
        extract_archives: Whether to extract archives
        max_concurrent: Maximum concurrent conversions
    
    Returns:
        Dict with 'results', 'success_count', 'error_count', 'total'
    """
    results = []
    success_count = 0
    error_count = 0
    
    async with anyio.create_task_group() as tg:
        limiter = anyio.CapacityLimiter(max_concurrent)
        
        async def process_one(path):
            nonlocal success_count, error_count
            async with limiter:
                result = await convert_file(path, backend, extract_archives)
                results.append(result)
                if result['success']:
                    success_count += 1
                else:
                    error_count += 1
        
        for path in input_paths:
            tg.start_soon(process_one, path)
    
    return {
        'results': results,
        'success_count': success_count,
        'error_count': error_count,
        'total': len(input_paths)
    }


def batch_convert_files_sync(
    input_paths: List[str],
    backend: str = 'native',
    extract_archives: bool = False,
    max_concurrent: int = 5
) -> Dict[str, Any]:
    """Synchronous wrapper for batch_convert_files."""
    return anyio.run(batch_convert_files, input_paths, backend, extract_archives, max_concurrent)


# ============================================================================
# Knowledge Graph Extraction
# ============================================================================

async def extract_knowledge_graph(
    input_path: str,
    enable_ipfs: bool = False
) -> Dict[str, Any]:
    """
    Extract knowledge graph (entities and relationships) from a file.
    
    Args:
        input_path: Path to file or URL
        enable_ipfs: Whether to store on IPFS
    
    Returns:
        Dict with 'entities', 'relationships', 'summary', 'success', 'error'
    """
    try:
        pipeline = UniversalKnowledgeGraphPipeline(enable_ipfs=enable_ipfs)
        result = await pipeline.process(input_path)
        
        return {
            'success': True,
            'entities': result.entities,
            'relationships': result.relationships,
            'summary': result.summary if hasattr(result, 'summary') else None,
            'entity_count': len(result.entities),
            'relationship_count': len(result.relationships),
            'source': input_path
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'source': input_path
        }


def extract_knowledge_graph_sync(
    input_path: str,
    enable_ipfs: bool = False
) -> Dict[str, Any]:
    """Synchronous wrapper for extract_knowledge_graph."""
    return anyio.run(extract_knowledge_graph, input_path, enable_ipfs)


# ============================================================================
# Text Summarization
# ============================================================================

async def generate_summary(
    input_path: str,
    llm_model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate a text summary from a file or URL.
    
    Args:
        input_path: Path to file or URL
        llm_model: LLM model to use (optional)
    
    Returns:
        Dict with 'summary', 'key_entities', 'success', 'error'
    """
    try:
        pipeline = TextSummarizationPipeline(llm_model=llm_model)
        result = await pipeline.summarize(input_path)
        
        return {
            'success': True,
            'summary': result.summary,
            'key_entities': result.key_entities if hasattr(result, 'key_entities') else [],
            'source': input_path
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'source': input_path
        }


def generate_summary_sync(
    input_path: str,
    llm_model: Optional[str] = None
) -> Dict[str, Any]:
    """Synchronous wrapper for generate_summary."""
    return anyio.run(generate_summary, input_path, llm_model)


# ============================================================================
# Vector Embeddings
# ============================================================================

async def generate_embeddings(
    input_path: str,
    embedding_model: str = 'sentence-transformers/all-MiniLM-L6-v2',
    vector_store: str = 'faiss',
    enable_ipfs: bool = False,
    enable_acceleration: bool = False
) -> Dict[str, Any]:
    """
    Generate vector embeddings from a file or URL.
    
    Args:
        input_path: Path to file or URL
        embedding_model: Embedding model to use
        vector_store: Vector store type ('faiss', 'qdrant', 'elasticsearch')
        enable_ipfs: Whether to store on IPFS
        enable_acceleration: Whether to use ML acceleration
    
    Returns:
        Dict with 'embedding_count', 'vector_store_ids', 'success', 'error'
    """
    try:
        pipeline = VectorEmbeddingPipeline(
            embedding_model=embedding_model,
            vector_store=vector_store,
            enable_ipfs=enable_ipfs,
            enable_acceleration=enable_acceleration
        )
        result = await pipeline.process(input_path)
        
        return {
            'success': True,
            'embedding_count': len(result.embeddings),
            'vector_store_ids': result.vector_store_ids,
            'model': embedding_model,
            'vector_store': vector_store,
            'source': input_path
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'source': input_path
        }


def generate_embeddings_sync(
    input_path: str,
    embedding_model: str = 'sentence-transformers/all-MiniLM-L6-v2',
    vector_store: str = 'faiss',
    enable_ipfs: bool = False,
    enable_acceleration: bool = False
) -> Dict[str, Any]:
    """Synchronous wrapper for generate_embeddings."""
    return anyio.run(generate_embeddings, input_path, embedding_model, vector_store, enable_ipfs, enable_acceleration)


# ============================================================================
# Archive Handling
# ============================================================================

async def extract_archive_contents(
    archive_path: str,
    max_depth: int = 3,
    recursive: bool = True
) -> Dict[str, Any]:
    """
    Extract contents from an archive file.
    
    Args:
        archive_path: Path to archive file
        max_depth: Maximum extraction depth
        recursive: Whether to extract nested archives
    
    Returns:
        Dict with 'extracted_files', 'file_count', 'total_size', 'success', 'error'
    """
    try:
        handler = ArchiveHandler(max_depth=max_depth)
        result = await handler.extract(archive_path, recursive=recursive)
        
        return {
            'success': True,
            'extracted_files': result.extracted_files,
            'file_count': len(result.extracted_files),
            'total_size': result.total_size,
            'extraction_path': result.extraction_path,
            'source': archive_path
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'source': archive_path
        }


def extract_archive_contents_sync(
    archive_path: str,
    max_depth: int = 3,
    recursive: bool = True
) -> Dict[str, Any]:
    """Synchronous wrapper for extract_archive_contents."""
    return anyio.run(extract_archive_contents, archive_path, max_depth, recursive)


# ============================================================================
# URL Downloading
# ============================================================================

async def download_from_url_export(
    url: str,
    timeout: int = 30,
    max_size_mb: int = 100
) -> Dict[str, Any]:
    """
    Download a file from a URL.
    
    Args:
        url: URL to download from
        timeout: Download timeout in seconds
        max_size_mb: Maximum file size in MB
    
    Returns:
        Dict with 'local_path', 'content_type', 'content_length', 'success', 'error'
    """
    try:
        handler = URLHandler(timeout=timeout, max_size_mb=max_size_mb)
        result = await handler.download(url)
        
        if result.success:
            return {
                'success': True,
                'local_path': result.local_path,
                'content_type': result.content_type,
                'content_length': result.content_length,
                'filename': result.filename,
                'url': url
            }
        else:
            return {
                'success': False,
                'error': result.error,
                'url': url
            }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'url': url
        }


def download_from_url_export_sync(
    url: str,
    timeout: int = 30,
    max_size_mb: int = 100
) -> Dict[str, Any]:
    """Synchronous wrapper for download_from_url_export."""
    return anyio.run(download_from_url_export, url, timeout, max_size_mb)


# ============================================================================
# File Information
# ============================================================================

async def get_file_info(
    input_path: str
) -> Dict[str, Any]:
    """
    Get information about a file.
    
    Args:
        input_path: Path to file or URL
    
    Returns:
        Dict with 'format', 'mime_type', 'metadata', 'is_url', 'is_archive', 'success', 'error'
    """
    try:
        from .format_detector import FormatDetector
        
        detector = FormatDetector()
        mime_type = detector.detect(input_path)
        
        # Get metadata if possible
        metadata = {}
        try:
            metadata = extract_metadata(input_path)
        except:
            pass
        
        return {
            'success': True,
            'format': mime_type,
            'mime_type': mime_type,
            'metadata': metadata,
            'is_url': is_url(input_path),
            'is_archive': is_archive(input_path),
            'source': input_path
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'source': input_path
        }


def get_file_info_sync(input_path: str) -> Dict[str, Any]:
    """Synchronous wrapper for get_file_info."""
    return anyio.run(get_file_info, input_path)


# ============================================================================
# Export All Functions
# ============================================================================

__all__ = [
    # Core conversion
    'convert_file',
    'convert_file_sync',
    'batch_convert_files',
    'batch_convert_files_sync',
    
    # Knowledge graphs
    'extract_knowledge_graph',
    'extract_knowledge_graph_sync',
    
    # Summarization
    'generate_summary',
    'generate_summary_sync',
    
    # Embeddings
    'generate_embeddings',
    'generate_embeddings_sync',
    
    # Archives
    'extract_archive_contents',
    'extract_archive_contents_sync',
    
    # URLs
    'download_from_url_export',
    'download_from_url_export_sync',
    
    # File info
    'get_file_info',
    'get_file_info_sync',
]
