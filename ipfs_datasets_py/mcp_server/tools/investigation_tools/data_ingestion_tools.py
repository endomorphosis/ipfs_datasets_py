#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Data Ingestion MCP Tools (thin wrapper)

Business logic lives in data_ingestion_engine.DataIngestionEngine.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..tool_wrapper import wrap_function_as_tool
from .data_ingestion_engine import DataIngestionEngine

logger = logging.getLogger(__name__)

_engine = DataIngestionEngine()


@wrap_function_as_tool(
    name="ingest_news_article",
    description="Ingest a single news article for analysis",
    category="investigation"
)
async def ingest_news_article(
    url: str,
    source_type: str = "news",
    analysis_type: str = "comprehensive",
    metadata: Optional[str] = None
) -> Dict[str, Any]:
    """Ingest a single news article for analysis."""
    meta = json.loads(metadata) if metadata else {}
    return _engine.ingest_article(url, source_type, analysis_type, meta)


@wrap_function_as_tool(
    name="ingest_news_feed",
    description="Ingest multiple articles from a news feed or RSS",
    category="investigation"
)
async def ingest_news_feed(
    feed_url: str,
    max_articles: int = 50,
    filters: Optional[str] = None,
    processing_mode: str = "parallel"
) -> Dict[str, Any]:
    """Ingest multiple articles from a news feed."""
    filter_criteria = json.loads(filters) if filters else {}
    return _engine.ingest_feed(feed_url, max_articles, filter_criteria, processing_mode)


@wrap_function_as_tool(
    name="ingest_website",
    description="Crawl and ingest content from an entire website",
    category="investigation"
)
async def ingest_website(
    base_url: str,
    max_pages: int = 100,
    max_depth: int = 3,
    url_patterns: Optional[str] = None,
    content_types: Optional[str] = None
) -> Dict[str, Any]:
    """Crawl and ingest content from a website."""
    patterns = json.loads(url_patterns) if url_patterns else {}
    types = json.loads(content_types) if content_types else ["text/html"]
    return _engine.ingest_website(base_url, max_pages, max_depth, patterns, types)


@wrap_function_as_tool(
    name="ingest_document_collection",
    description="Ingest a collection of documents (PDFs, text files, etc.)",
    category="investigation"
)
async def ingest_document_collection(
    document_paths: str,
    collection_name: str = "document_collection",
    processing_options: Optional[str] = None,
    metadata_extraction: bool = True
) -> Dict[str, Any]:
    """Ingest a collection of documents for investigation."""
    paths = json.loads(document_paths) if isinstance(document_paths, str) else document_paths
    options = json.loads(processing_options) if processing_options else {}
    return _engine.ingest_document_collection(paths, collection_name, options, metadata_extraction)


# Re-export helpers for backward compatibility
def _build_sitemap(crawled_pages, max_depth):
    return _engine._build_sitemap(crawled_pages, max_depth)


def _calculate_depth_distribution(crawled_pages):
    return _engine._calculate_depth_distribution(crawled_pages)
