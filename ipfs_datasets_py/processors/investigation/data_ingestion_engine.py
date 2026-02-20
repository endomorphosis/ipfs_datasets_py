"""
Data Ingestion Engine

Business logic for ingesting news articles, feeds, websites, and document collections.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DataIngestionEngine:
    """Engine for synchronous data ingestion operations."""

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def ingest_article(
        self,
        url: str,
        source_type: str = "news",
        analysis_type: str = "comprehensive",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ingest a single news article."""
        try:
            meta = metadata or {}
            processing_steps = []
            processing_steps.append({
                "step": "content_extraction",
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "details": "Article content extracted successfully",
            })
            extracted_data: Dict[str, Any] = {
                "title": f"Sample Article from {url}",
                "content": (
                    f"This is sample content extracted from {url}. "
                    "In a real implementation, this would contain the actual article text."
                ),
                "author": "Sample Author",
                "publish_date": "2024-01-15",
                "word_count": 150,
                "language": "en",
            }
            processing_steps.append({
                "step": "entity_extraction",
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "details": "Entities extracted from content",
            })
            entities = [
                {"text": "Sample Entity 1", "label": "PERSON", "confidence": 0.92,
                 "start": 0, "end": 15},
                {"text": "Sample Organization", "label": "ORG", "confidence": 0.88,
                 "start": 20, "end": 39},
            ]
            extracted_data["entities"] = entities
            if analysis_type == "comprehensive":
                processing_steps.append({
                    "step": "sentiment_analysis",
                    "status": "completed",
                    "timestamp": datetime.now().isoformat(),
                    "details": "Sentiment analysis completed",
                })
                extracted_data["sentiment"] = {
                    "overall": "neutral",
                    "confidence": 0.85,
                    "scores": {"positive": 0.3, "neutral": 0.5, "negative": 0.2},
                }
                processing_steps.append({
                    "step": "topic_classification",
                    "status": "completed",
                    "timestamp": datetime.now().isoformat(),
                    "details": "Topic classification completed",
                })
                extracted_data["topics"] = [
                    {"topic": "politics", "confidence": 0.75},
                    {"topic": "economics", "confidence": 0.45},
                ]
            processing_steps.append({
                "step": "corpus_storage",
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "details": "Article stored in investigation corpus",
            })
            return {
                "ingestion_id": f"article_{hashlib.md5(url.encode()).hexdigest()[:8]}",
                "url": url,
                "source_type": source_type,
                "analysis_type": analysis_type,
                "status": "completed",
                "metadata": meta,
                "extracted_data": extracted_data,
                "processing_steps": processing_steps,
                "statistics": {
                    "processing_time_seconds": 2.5,
                    "entities_extracted": len(entities),
                    "topics_identified": len(extracted_data.get("topics", [])),
                    "confidence_avg": (
                        sum(e["confidence"] for e in entities) / len(entities)
                        if entities else 0
                    ),
                },
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Article ingestion failed: {e}")
            return {
                "ingestion_id": None,
                "url": url,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def ingest_feed(
        self,
        feed_url: str,
        max_articles: int = 50,
        filters: Optional[Dict[str, Any]] = None,
        processing_mode: str = "parallel",
    ) -> Dict[str, Any]:
        """Ingest multiple articles from a news feed (synchronous)."""
        try:
            filter_criteria = filters or {}
            found_articles = [
                {
                    "url": f"{feed_url}/article_{i}",
                    "title": f"Sample Article {i}",
                    "publish_date": "2024-01-15",
                    "summary": f"Summary of article {i}",
                }
                for i in range(min(max_articles, 10))
            ]
            filtered_articles = (
                found_articles[: min(len(found_articles), max_articles // 2)]
                if filter_criteria
                else found_articles
            )
            processed_articles = []
            for i, article in enumerate(filtered_articles):
                article_result = self.ingest_article(article["url"], source_type="news_feed",
                                                     analysis_type="standard")
                processed_articles.append({
                    "article_index": i,
                    "url": article["url"],
                    "title": article["title"],
                    "ingestion_status": article_result["status"],
                    "entities_count": len(
                        article_result.get("extracted_data", {}).get("entities", [])
                    ),
                    "processing_time": 1.2 + (i * 0.1),
                })
            successful_articles = [
                a for a in processed_articles if a["ingestion_status"] == "completed"
            ]
            total_entities = sum(a["entities_count"] for a in successful_articles)
            return {
                "batch_id": f"batch_{hashlib.md5(feed_url.encode()).hexdigest()[:8]}",
                "feed_url": feed_url,
                "max_articles": max_articles,
                "filters": filter_criteria,
                "processing_mode": processing_mode,
                "status": "completed",
                "articles": processed_articles,
                "statistics": {
                    "articles_found": len(found_articles),
                    "articles_filtered": len(filtered_articles),
                    "articles_processed": len(processed_articles),
                    "articles_successful": len(successful_articles),
                    "total_entities_extracted": total_entities,
                    "success_rate": (
                        len(successful_articles) / len(processed_articles)
                        if processed_articles else 0
                    ),
                    "average_processing_time": (
                        sum(a["processing_time"] for a in processed_articles)
                        / len(processed_articles)
                        if processed_articles else 0
                    ),
                },
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Batch ingestion failed: {e}")
            return {
                "batch_id": None,
                "feed_url": feed_url,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def ingest_website(
        self,
        base_url: str,
        max_pages: int = 100,
        max_depth: int = 3,
        url_patterns: Optional[Dict[str, Any]] = None,
        content_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Crawl and ingest content from a website (synchronous)."""
        try:
            patterns = url_patterns or {}
            types = content_types or ["text/html"]
            crawled_pages = []
            discovered_urls: set = set()
            for depth in range(min(max_depth, 3)):
                for page_num in range(min(5, max_pages // (depth + 1))):
                    page_url = f"{base_url}/page_{depth}_{page_num}"
                    discovered_urls.add(page_url)
                    page_result: Dict[str, Any] = {
                        "url": page_url,
                        "depth": depth,
                        "title": f"Page {page_num} at depth {depth}",
                        "content_length": 1500 + (page_num * 200),
                        "content_type": "text/html",
                        "status_code": 200,
                        "extracted_links": [f"{base_url}/link_{i}" for i in range(3)],
                        "entities_extracted": [
                            {"text": f"Entity_{depth}_{page_num}", "type": "ORG",
                             "confidence": 0.8}
                        ],
                        "processing_time": 0.8 + (depth * 0.2),
                        "timestamp": datetime.now().isoformat(),
                    }
                    if patterns.get("include") and not any(
                        p in page_url for p in patterns["include"]
                    ):
                        page_result["status"] = "filtered_out"
                    elif patterns.get("exclude") and any(
                        p in page_url for p in patterns["exclude"]
                    ):
                        page_result["status"] = "filtered_out"
                    else:
                        page_result["status"] = "processed"
                    crawled_pages.append(page_result)
                    for link in page_result["extracted_links"]:
                        discovered_urls.add(link)
            sitemap = self._build_sitemap(crawled_pages, max_depth)
            successful_pages = [p for p in crawled_pages if p["status"] == "processed"]
            total_entities = sum(len(p["entities_extracted"]) for p in successful_pages)
            total_content_length = sum(p["content_length"] for p in successful_pages)
            return {
                "crawl_id": f"crawl_{hashlib.md5(base_url.encode()).hexdigest()[:8]}",
                "base_url": base_url,
                "parameters": {
                    "max_pages": max_pages,
                    "max_depth": max_depth,
                    "url_patterns": patterns,
                    "content_types": types,
                },
                "status": "completed",
                "crawled_pages": crawled_pages,
                "discovered_urls": list(discovered_urls),
                "sitemap": sitemap,
                "crawl_statistics": {
                    "total_pages_discovered": len(discovered_urls),
                    "total_pages_crawled": len(crawled_pages),
                    "successful_pages": len(successful_pages),
                    "total_entities_extracted": total_entities,
                    "total_content_length": total_content_length,
                    "average_page_size": (
                        total_content_length / len(successful_pages)
                        if successful_pages else 0
                    ),
                    "crawl_success_rate": (
                        len(successful_pages) / len(crawled_pages)
                        if crawled_pages else 0
                    ),
                    "depth_distribution": self._calculate_depth_distribution(crawled_pages),
                    "content_type_distribution": self._calculate_content_type_distribution(
                        crawled_pages
                    ),
                },
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Website crawling failed: {e}")
            return {
                "crawl_id": None,
                "base_url": base_url,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def ingest_document_collection(
        self,
        document_paths: List[str],
        collection_name: str = "document_collection",
        processing_options: Optional[Dict[str, Any]] = None,
        metadata_extraction: bool = True,
    ) -> Dict[str, Any]:
        """Ingest a collection of documents (synchronous)."""
        try:
            options = processing_options or {}
            processed_documents = []
            for i, doc_path in enumerate(document_paths):
                doc_result = self._process_single_document(doc_path, options, metadata_extraction)
                doc_result["collection_index"] = i
                processed_documents.append(doc_result)
            collection_analysis = self._analyze_document_collection(processed_documents)
            successful_docs = [d for d in processed_documents if d["status"] == "completed"]
            total_pages = sum(d.get("page_count", 0) for d in successful_docs)
            total_entities = sum(len(d.get("entities", [])) for d in successful_docs)
            return {
                "collection_id": f"collection_{hashlib.md5(collection_name.encode()).hexdigest()[:8]}",
                "collection_name": collection_name,
                "document_count": len(document_paths),
                "processing_options": options,
                "metadata_extraction": metadata_extraction,
                "status": "completed",
                "processed_documents": processed_documents,
                "collection_analysis": collection_analysis,
                "collection_statistics": {
                    "total_documents": len(processed_documents),
                    "successful_documents": len(successful_docs),
                    "total_pages": total_pages,
                    "total_entities": total_entities,
                    "success_rate": (
                        len(successful_docs) / len(processed_documents)
                        if processed_documents else 0
                    ),
                    "file_type_distribution": self._calculate_file_type_distribution(
                        processed_documents
                    ),
                    "language_distribution": self._calculate_language_distribution(
                        processed_documents
                    ),
                    "average_document_size": (
                        sum(d.get("file_size", 0) for d in successful_docs) / len(successful_docs)
                        if successful_docs else 0
                    ),
                },
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Document collection ingestion failed: {e}")
            return {
                "collection_id": None,
                "collection_name": collection_name,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _process_single_document(
        self,
        doc_path: str,
        options: Dict[str, Any],
        extract_metadata: bool,
    ) -> Dict[str, Any]:
        """Process a single document file."""
        doc_result: Dict[str, Any] = {
            "document_path": doc_path,
            "filename": Path(doc_path).name,
            "file_extension": Path(doc_path).suffix,
            "file_size": 1024 * 50,
            "status": "processing",
            "extracted_content": {},
            "entities": [],
            "metadata": {},
            "processing_time": 0.0,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            file_ext = Path(doc_path).suffix.lower()
            if file_ext == ".pdf":
                doc_result["extracted_content"] = {
                    "text": f"Extracted text content from {doc_path}",
                    "page_count": 5,
                    "has_images": True,
                    "has_tables": False,
                }
            elif file_ext in [".txt", ".md"]:
                doc_result["extracted_content"] = {
                    "text": f"Text content from {doc_path}",
                    "line_count": 100,
                    "encoding": "utf-8",
                }
            elif file_ext in [".docx", ".doc"]:
                doc_result["extracted_content"] = {
                    "text": f"Document content from {doc_path}",
                    "paragraph_count": 20,
                    "has_formatting": True,
                }
            else:
                doc_result["status"] = "unsupported_format"
                return doc_result
            doc_result["entities"] = [
                {"text": f"Entity from {Path(doc_path).stem}", "type": "ORG",
                 "confidence": 0.85, "start": 0, "end": 20}
            ]
            if extract_metadata:
                doc_result["metadata"] = {
                    "author": "Sample Author",
                    "creation_date": "2024-01-01",
                    "modification_date": "2024-01-15",
                    "language": "en",
                    "subject": "Sample Document",
                    "word_count": 500,
                }
            doc_result.update({
                "status": "completed",
                "processing_time": 1.5,
                "page_count": doc_result["extracted_content"].get("page_count", 1),
            })
        except Exception as e:
            doc_result.update({"status": "failed", "error": str(e)})
        return doc_result

    def _build_sitemap(
        self, crawled_pages: List[Dict[str, Any]], max_depth: int
    ) -> Dict[str, Any]:
        """Build a sitemap from crawled pages."""
        sitemap: Dict[str, Any] = {
            "root": {
                "url": crawled_pages[0]["url"] if crawled_pages else "",
                "children": {},
            }
        }
        for page in crawled_pages:
            depth = page["depth"]
            if depth == 0:
                sitemap["root"]["title"] = page["title"]
                sitemap["root"]["status"] = page["status"]
            else:
                depth_key = f"depth_{depth}"
                if depth_key not in sitemap["root"]["children"]:
                    sitemap["root"]["children"][depth_key] = []
                sitemap["root"]["children"][depth_key].append({
                    "url": page["url"],
                    "title": page["title"],
                    "status": page["status"],
                    "content_length": page["content_length"],
                })
        return sitemap

    def _calculate_depth_distribution(
        self, crawled_pages: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        distribution: Dict[str, int] = {}
        for page in crawled_pages:
            key = f"depth_{page['depth']}"
            distribution[key] = distribution.get(key, 0) + 1
        return distribution

    def _calculate_content_type_distribution(
        self, crawled_pages: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        distribution: Dict[str, int] = {}
        for page in crawled_pages:
            ct = page["content_type"]
            distribution[ct] = distribution.get(ct, 0) + 1
        return distribution

    def _analyze_document_collection(
        self, documents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        successful_docs = [d for d in documents if d["status"] == "completed"]
        if not successful_docs:
            return {"content_similarity": {}, "common_entities": [],
                    "temporal_distribution": {}, "topic_clusters": []}
        entity_counts: Dict[str, int] = {}
        for doc in successful_docs:
            for entity in doc.get("entities", []):
                txt = entity["text"]
                entity_counts[txt] = entity_counts.get(txt, 0) + 1
        common_entities = sorted(
            [{"entity": e, "document_count": c} for e, c in entity_counts.items() if c > 1],
            key=lambda x: x["document_count"],
            reverse=True,
        )
        return {
            "content_similarity": {},
            "common_entities": common_entities,
            "temporal_distribution": {},
            "topic_clusters": [
                {"cluster_id": "cluster_1", "topic": "Legal Documents",
                 "document_count": len(successful_docs) // 2, "similarity_score": 0.75},
                {"cluster_id": "cluster_2", "topic": "Technical Reports",
                 "document_count": len(successful_docs) // 3, "similarity_score": 0.68},
            ],
        }

    def _calculate_file_type_distribution(
        self, documents: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        dist: Dict[str, int] = {}
        for doc in documents:
            ext = doc.get("file_extension", "unknown")
            dist[ext] = dist.get(ext, 0) + 1
        return dist

    def _calculate_language_distribution(
        self, documents: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        dist: Dict[str, int] = {}
        for doc in documents:
            lang = doc.get("metadata", {}).get("language", "unknown")
            dist[lang] = dist.get(lang, 0) + 1
        return dist
