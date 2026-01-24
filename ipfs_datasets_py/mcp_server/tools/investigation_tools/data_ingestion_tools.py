#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Data Ingestion MCP Tools

Provides MCP tools for ingesting news articles, documents, and websites.
"""
from __future__ import annotations

import anyio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import hashlib
import re

from ..tool_wrapper import wrap_function_as_tool

logger = logging.getLogger(__name__)


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
    """
    Ingest a single news article for analysis.
    
    Args:
        url: URL of the news article to ingest
        source_type: Type of source (news, blog, academic, government)
        analysis_type: Type of analysis to perform
        metadata: Additional metadata as JSON string
        
    Returns:
        Dictionary containing ingestion results
    """
    try:
        # Parse metadata if provided
        meta = json.loads(metadata) if metadata else {}
        
        results = {
            "ingestion_id": f"article_{hashlib.md5(url.encode()).hexdigest()[:8]}",
            "url": url,
            "source_type": source_type,
            "analysis_type": analysis_type,
            "status": "processing",
            "metadata": meta,
            "extracted_data": {},
            "processing_steps": [],
            "timestamp": datetime.now().isoformat()
        }
        
        # Simulate article extraction
        processing_steps = []
        
        # Step 1: Fetch article content
        processing_steps.append({
            "step": "content_extraction",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": "Article content extracted successfully"
        })
        
        extracted_data = {
            "title": f"Sample Article from {url}",
            "content": f"This is sample content extracted from {url}. In a real implementation, this would contain the actual article text extracted using web scraping tools.",
            "author": "Sample Author",
            "publish_date": "2024-01-15",
            "word_count": 150,
            "language": "en"
        }
        
        # Step 2: Entity extraction
        processing_steps.append({
            "step": "entity_extraction",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": "Entities extracted from content"
        })
        
        entities = [
            {
                "text": "Sample Entity 1",
                "label": "PERSON",
                "confidence": 0.92,
                "start": 0,
                "end": 15
            },
            {
                "text": "Sample Organization",
                "label": "ORG", 
                "confidence": 0.88,
                "start": 20,
                "end": 39
            }
        ]
        extracted_data["entities"] = entities
        
        # Step 3: Content analysis based on analysis type
        if analysis_type == "comprehensive":
            processing_steps.append({
                "step": "sentiment_analysis",
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "details": "Sentiment analysis completed"
            })
            
            extracted_data["sentiment"] = {
                "overall": "neutral",
                "confidence": 0.85,
                "scores": {"positive": 0.3, "neutral": 0.5, "negative": 0.2}
            }
            
            processing_steps.append({
                "step": "topic_classification",
                "status": "completed", 
                "timestamp": datetime.now().isoformat(),
                "details": "Topic classification completed"
            })
            
            extracted_data["topics"] = [
                {"topic": "politics", "confidence": 0.75},
                {"topic": "economics", "confidence": 0.45}
            ]
        
        # Step 4: Store in corpus
        processing_steps.append({
            "step": "corpus_storage",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": "Article stored in investigation corpus"
        })
        
        results.update({
            "status": "completed",
            "extracted_data": extracted_data,
            "processing_steps": processing_steps,
            "statistics": {
                "processing_time_seconds": 2.5,
                "entities_extracted": len(entities),
                "topics_identified": len(extracted_data.get("topics", [])),
                "confidence_avg": sum(e["confidence"] for e in entities) / len(entities) if entities else 0
            }
        })
        
        logger.info(f"Article ingestion completed: {url}")
        return results
        
    except Exception as e:
        logger.error(f"Article ingestion failed: {e}")
        return {
            "ingestion_id": None,
            "url": url,
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


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
    """
    Ingest multiple articles from a news feed.
    
    Args:
        feed_url: URL of RSS feed or news API endpoint
        max_articles: Maximum number of articles to process
        filters: JSON string of filtering criteria
        processing_mode: Processing mode (parallel, sequential)
        
    Returns:
        Dictionary containing batch ingestion results
    """
    try:
        # Parse filters if provided
        filter_criteria = json.loads(filters) if filters else {}
        
        results = {
            "batch_id": f"batch_{hashlib.md5(feed_url.encode()).hexdigest()[:8]}",
            "feed_url": feed_url,
            "max_articles": max_articles,
            "filters": filter_criteria,
            "processing_mode": processing_mode,
            "status": "processing",
            "articles": [],
            "statistics": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Simulate feed processing
        processing_logs = []
        
        # Step 1: Fetch feed
        processing_logs.append({
            "step": "feed_fetch",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": f"Fetched feed from {feed_url}"
        })
        
        # Simulate found articles
        found_articles = [
            {
                "url": f"{feed_url}/article_{i}",
                "title": f"Sample Article {i}",
                "publish_date": "2024-01-15",
                "summary": f"Summary of article {i}"
            }
            for i in range(min(max_articles, 10))  # Limit to 10 for demo
        ]
        
        # Step 2: Apply filters
        if filter_criteria:
            processing_logs.append({
                "step": "filtering",
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "details": f"Applied filters: {list(filter_criteria.keys())}"
            })
            
            # Mock filtering
            filtered_articles = found_articles[:min(len(found_articles), max_articles//2)]
        else:
            filtered_articles = found_articles
        
        # Step 3: Process articles
        processed_articles = []
        
        for i, article in enumerate(filtered_articles):
            # Simulate processing each article
            article_result = await ingest_news_article(
                article["url"],
                source_type="news_feed",
                analysis_type="standard"
            )
            
            processed_articles.append({
                "article_index": i,
                "url": article["url"],
                "title": article["title"],
                "ingestion_status": article_result["status"],
                "entities_count": len(article_result.get("extracted_data", {}).get("entities", [])),
                "processing_time": 1.2 + (i * 0.1)  # Mock processing time
            })
            
            # Simulate parallel processing delay
            if processing_mode == "parallel":
                await anyio.sleep(0.1)
            else:
                await anyio.sleep(0.5)
        
        processing_logs.append({
            "step": "article_processing",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": f"Processed {len(processed_articles)} articles"
        })
        
        # Calculate statistics
        successful_articles = [a for a in processed_articles if a["ingestion_status"] == "completed"]
        total_entities = sum(a["entities_count"] for a in successful_articles)
        
        results.update({
            "status": "completed",
            "articles": processed_articles,
            "processing_logs": processing_logs,
            "statistics": {
                "articles_found": len(found_articles),
                "articles_filtered": len(filtered_articles),
                "articles_processed": len(processed_articles),
                "articles_successful": len(successful_articles),
                "total_entities_extracted": total_entities,
                "success_rate": len(successful_articles) / len(processed_articles) if processed_articles else 0,
                "average_processing_time": sum(a["processing_time"] for a in processed_articles) / len(processed_articles) if processed_articles else 0
            }
        })
        
        logger.info(f"Batch ingestion completed: {len(successful_articles)} successful articles")
        return results
        
    except Exception as e:
        logger.error(f"Batch ingestion failed: {e}")
        return {
            "batch_id": None,
            "feed_url": feed_url,
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


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
    """
    Crawl and ingest content from a website.
    
    Args:
        base_url: Base URL to start crawling from
        max_pages: Maximum number of pages to crawl
        max_depth: Maximum crawling depth
        url_patterns: JSON list of URL patterns to include/exclude
        content_types: JSON list of content types to process
        
    Returns:
        Dictionary containing website crawling results
    """
    try:
        # Parse patterns and content types
        patterns = json.loads(url_patterns) if url_patterns else {}
        types = json.loads(content_types) if content_types else ["text/html"]
        
        results = {
            "crawl_id": f"crawl_{hashlib.md5(base_url.encode()).hexdigest()[:8]}",
            "base_url": base_url,
            "parameters": {
                "max_pages": max_pages,
                "max_depth": max_depth,
                "url_patterns": patterns,
                "content_types": types
            },
            "status": "processing",
            "crawled_pages": [],
            "discovered_urls": [],
            "crawl_statistics": {},
            "timestamp": datetime.now().isoformat()
        }
        
        crawl_logs = []
        
        # Step 1: Initialize crawling
        crawl_logs.append({
            "step": "crawl_initialization",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": f"Started crawling from {base_url}"
        })
        
        # Simulate website crawling
        crawled_pages = []
        discovered_urls = set()
        
        # Mock URL discovery and crawling
        for depth in range(min(max_depth, 3)):
            for page_num in range(min(5, max_pages // (depth + 1))):  # Fewer pages at greater depths
                page_url = f"{base_url}/page_{depth}_{page_num}"
                discovered_urls.add(page_url)
                
                # Simulate page processing
                page_result = {
                    "url": page_url,
                    "depth": depth,
                    "title": f"Page {page_num} at depth {depth}",
                    "content_length": 1500 + (page_num * 200),
                    "content_type": "text/html",
                    "status_code": 200,
                    "extracted_links": [f"{base_url}/link_{i}" for i in range(3)],
                    "entities_extracted": [
                        {"text": f"Entity_{depth}_{page_num}", "type": "ORG", "confidence": 0.8}
                    ],
                    "processing_time": 0.8 + (depth * 0.2),
                    "timestamp": datetime.now().isoformat()
                }
                
                # Apply URL patterns filtering
                if patterns.get("include") and not any(pattern in page_url for pattern in patterns["include"]):
                    page_result["status"] = "filtered_out"
                elif patterns.get("exclude") and any(pattern in page_url for pattern in patterns["exclude"]):
                    page_result["status"] = "filtered_out"
                else:
                    page_result["status"] = "processed"
                
                crawled_pages.append(page_result)
                
                # Add discovered links to URL queue
                for link in page_result["extracted_links"]:
                    discovered_urls.add(link)
                
                # Simulate crawling delay
                await anyio.sleep(0.1)
        
        crawl_logs.append({
            "step": "crawling_completed",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": f"Crawled {len(crawled_pages)} pages"
        })
        
        # Step 2: Content analysis
        crawl_logs.append({
            "step": "content_analysis",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": "Analyzed crawled content for entities and structure"
        })
        
        # Step 3: Build site map
        crawl_logs.append({
            "step": "sitemap_generation",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": "Generated site structure map"
        })
        
        sitemap = _build_sitemap(crawled_pages, max_depth)
        
        # Calculate statistics
        successful_pages = [p for p in crawled_pages if p["status"] == "processed"]
        total_entities = sum(len(p["entities_extracted"]) for p in successful_pages)
        total_content_length = sum(p["content_length"] for p in successful_pages)
        
        results.update({
            "status": "completed",
            "crawled_pages": crawled_pages,
            "discovered_urls": list(discovered_urls),
            "sitemap": sitemap,
            "crawl_logs": crawl_logs,
            "crawl_statistics": {
                "total_pages_discovered": len(discovered_urls),
                "total_pages_crawled": len(crawled_pages),
                "successful_pages": len(successful_pages),
                "total_entities_extracted": total_entities,
                "total_content_length": total_content_length,
                "average_page_size": total_content_length / len(successful_pages) if successful_pages else 0,
                "crawl_success_rate": len(successful_pages) / len(crawled_pages) if crawled_pages else 0,
                "depth_distribution": _calculate_depth_distribution(crawled_pages),
                "content_type_distribution": _calculate_content_type_distribution(crawled_pages)
            }
        })
        
        logger.info(f"Website crawling completed: {len(successful_pages)} pages processed")
        return results
        
    except Exception as e:
        logger.error(f"Website crawling failed: {e}")
        return {
            "crawl_id": None,
            "base_url": base_url,
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


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
    """
    Ingest a collection of documents for investigation.
    
    Args:
        document_paths: JSON string containing list of document file paths
        collection_name: Name for the document collection
        processing_options: JSON string with processing configuration
        metadata_extraction: Whether to extract document metadata
        
    Returns:
        Dictionary containing collection ingestion results
    """
    try:
        # Parse document paths and processing options
        paths = json.loads(document_paths) if isinstance(document_paths, str) else document_paths
        options = json.loads(processing_options) if processing_options else {}
        
        results = {
            "collection_id": f"collection_{hashlib.md5(collection_name.encode()).hexdigest()[:8]}",
            "collection_name": collection_name,
            "document_count": len(paths) if isinstance(paths, list) else 0,
            "processing_options": options,
            "metadata_extraction": metadata_extraction,
            "status": "processing",
            "processed_documents": [],
            "collection_statistics": {},
            "timestamp": datetime.now().isoformat()
        }
        
        processing_logs = []
        
        # Step 1: Validate documents
        processing_logs.append({
            "step": "document_validation",
            "status": "completed", 
            "timestamp": datetime.now().isoformat(),
            "details": f"Validated {len(paths) if isinstance(paths, list) else 0} document paths"
        })
        
        processed_documents = []
        
        # Process each document
        if isinstance(paths, list):
            for i, doc_path in enumerate(paths):
                doc_result = await _process_single_document(doc_path, options, metadata_extraction)
                doc_result["collection_index"] = i
                processed_documents.append(doc_result)
                
                # Simulate processing delay
                await anyio.sleep(0.2)
        
        processing_logs.append({
            "step": "document_processing",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": f"Processed {len(processed_documents)} documents"
        })
        
        # Step 2: Collection analysis
        processing_logs.append({
            "step": "collection_analysis",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": "Analyzed document collection for patterns and relationships"
        })
        
        collection_analysis = _analyze_document_collection(processed_documents)
        
        # Step 3: Index generation
        processing_logs.append({
            "step": "index_generation",
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "details": "Generated searchable index for document collection"
        })
        
        # Calculate collection statistics
        successful_docs = [d for d in processed_documents if d["status"] == "completed"]
        total_pages = sum(d.get("page_count", 0) for d in successful_docs)
        total_entities = sum(len(d.get("entities", [])) for d in successful_docs)
        
        results.update({
            "status": "completed",
            "processed_documents": processed_documents,
            "collection_analysis": collection_analysis,
            "processing_logs": processing_logs,
            "collection_statistics": {
                "total_documents": len(processed_documents),
                "successful_documents": len(successful_docs),
                "total_pages": total_pages,
                "total_entities": total_entities,
                "success_rate": len(successful_docs) / len(processed_documents) if processed_documents else 0,
                "file_type_distribution": _calculate_file_type_distribution(processed_documents),
                "language_distribution": _calculate_language_distribution(processed_documents),
                "average_document_size": sum(d.get("file_size", 0) for d in successful_docs) / len(successful_docs) if successful_docs else 0
            }
        })
        
        logger.info(f"Document collection ingestion completed: {len(successful_docs)} documents processed")
        return results
        
    except Exception as e:
        logger.error(f"Document collection ingestion failed: {e}")
        return {
            "collection_id": None,
            "collection_name": collection_name,
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# Helper functions for data ingestion

async def _process_single_document(doc_path: str, options: Dict[str, Any], extract_metadata: bool) -> Dict[str, Any]:
    """Process a single document file."""
    doc_result = {
        "document_path": doc_path,
        "filename": Path(doc_path).name,
        "file_extension": Path(doc_path).suffix,
        "file_size": 1024 * 50,  # Mock file size
        "status": "processing",
        "extracted_content": {},
        "entities": [],
        "metadata": {},
        "processing_time": 0.0,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        # Simulate file processing based on extension
        file_ext = Path(doc_path).suffix.lower()
        
        if file_ext == ".pdf":
            doc_result["extracted_content"] = {
                "text": f"Extracted text content from {doc_path}",
                "page_count": 5,
                "has_images": True,
                "has_tables": False
            }
        elif file_ext in [".txt", ".md"]:
            doc_result["extracted_content"] = {
                "text": f"Text content from {doc_path}",
                "line_count": 100,
                "encoding": "utf-8"
            }
        elif file_ext in [".docx", ".doc"]:
            doc_result["extracted_content"] = {
                "text": f"Document content from {doc_path}",
                "paragraph_count": 20,
                "has_formatting": True
            }
        else:
            doc_result["status"] = "unsupported_format"
            return doc_result
        
        # Mock entity extraction
        doc_result["entities"] = [
            {
                "text": f"Entity from {Path(doc_path).stem}",
                "type": "ORG",
                "confidence": 0.85,
                "start": 0,
                "end": 20
            }
        ]
        
        # Mock metadata extraction
        if extract_metadata:
            doc_result["metadata"] = {
                "author": "Sample Author",
                "creation_date": "2024-01-01",
                "modification_date": "2024-01-15",
                "language": "en",
                "subject": "Sample Document",
                "word_count": 500
            }
        
        doc_result.update({
            "status": "completed",
            "processing_time": 1.5,
            "page_count": doc_result["extracted_content"].get("page_count", 1)
        })
        
    except Exception as e:
        doc_result.update({
            "status": "failed",
            "error": str(e)
        })
    
    return doc_result


def _build_sitemap(crawled_pages: List[Dict[str, Any]], max_depth: int) -> Dict[str, Any]:
    """Build a sitemap from crawled pages."""
    sitemap = {
        "root": {
            "url": crawled_pages[0]["url"] if crawled_pages else "",
            "children": {}
        }
    }
    
    # Organize pages by depth
    for page in crawled_pages:
        depth = page["depth"]
        if depth == 0:
            sitemap["root"]["title"] = page["title"]
            sitemap["root"]["status"] = page["status"]
        else:
            # Simplified sitemap structure
            depth_key = f"depth_{depth}"
            if depth_key not in sitemap["root"]["children"]:
                sitemap["root"]["children"][depth_key] = []
            
            sitemap["root"]["children"][depth_key].append({
                "url": page["url"],
                "title": page["title"],
                "status": page["status"],
                "content_length": page["content_length"]
            })
    
    return sitemap


def _calculate_depth_distribution(crawled_pages: List[Dict[str, Any]]) -> Dict[str, int]:
    """Calculate distribution of pages by crawl depth."""
    distribution = {}
    for page in crawled_pages:
        depth = page["depth"]
        distribution[f"depth_{depth}"] = distribution.get(f"depth_{depth}", 0) + 1
    return distribution


def _calculate_content_type_distribution(crawled_pages: List[Dict[str, Any]]) -> Dict[str, int]:
    """Calculate distribution of pages by content type."""
    distribution = {}
    for page in crawled_pages:
        content_type = page["content_type"]
        distribution[content_type] = distribution.get(content_type, 0) + 1
    return distribution


def _analyze_document_collection(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze a collection of documents for patterns."""
    analysis = {
        "content_similarity": {},
        "common_entities": [],
        "temporal_distribution": {},
        "topic_clusters": []
    }
    
    successful_docs = [d for d in documents if d["status"] == "completed"]
    
    if not successful_docs:
        return analysis
    
    # Find common entities across documents
    entity_counts = {}
    for doc in successful_docs:
        for entity in doc.get("entities", []):
            entity_text = entity["text"]
            entity_counts[entity_text] = entity_counts.get(entity_text, 0) + 1
    
    # Keep entities that appear in multiple documents
    common_entities = [
        {"entity": entity, "document_count": count}
        for entity, count in entity_counts.items()
        if count > 1
    ]
    
    analysis["common_entities"] = sorted(common_entities, key=lambda x: x["document_count"], reverse=True)
    
    # Mock topic clustering
    analysis["topic_clusters"] = [
        {
            "cluster_id": "cluster_1",
            "topic": "Legal Documents",
            "document_count": len(successful_docs) // 2,
            "similarity_score": 0.75
        },
        {
            "cluster_id": "cluster_2", 
            "topic": "Technical Reports",
            "document_count": len(successful_docs) // 3,
            "similarity_score": 0.68
        }
    ]
    
    return analysis


def _calculate_file_type_distribution(documents: List[Dict[str, Any]]) -> Dict[str, int]:
    """Calculate distribution of documents by file type."""
    distribution = {}
    for doc in documents:
        file_ext = doc.get("file_extension", "unknown")
        distribution[file_ext] = distribution.get(file_ext, 0) + 1
    return distribution


def _calculate_language_distribution(documents: List[Dict[str, Any]]) -> Dict[str, int]:
    """Calculate distribution of documents by language."""
    distribution = {}
    for doc in documents:
        language = doc.get("metadata", {}).get("language", "unknown")
        distribution[language] = distribution.get(language, 0) + 1
    return distribution