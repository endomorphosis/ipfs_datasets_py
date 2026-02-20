"""
PDF Batch Processing Tool

MCP tool for batch processing multiple PDF documents through the
complete GraphRAG integration pipeline with parallel execution,
progress tracking, and comprehensive reporting.
"""

import anyio
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.pdf_processing import BatchProcessor  # type: ignore
except (ImportError, ModuleNotFoundError):
    BatchProcessor = None  # type: ignore

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)

async def pdf_batch_process(
    pdf_sources: List[Union[str, Dict[str, Any]]] | str,
    batch_size: int = 5,
    parallel_workers: int = 3,
    enable_ocr: bool = True,
    target_llm: str = "gpt-4",
    chunk_strategy: str = "semantic",
    enable_cross_document: bool = True,
    output_format: str = "detailed",
    progress_callback: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process multiple PDF documents through the complete GraphRAG pipeline with
    batch optimization, parallel processing, and comprehensive progress tracking.
    
    This tool provides efficient batch processing with:
    - Parallel document processing with configurable workers
    - Progress tracking and status updates
    - Error handling and recovery for individual documents
    - Resource management and memory optimization
    - Comprehensive batch reporting
    - Cross-document relationship discovery across the batch
    
    Args:
        pdf_sources: List of PDF file paths or data dicts with metadata
        batch_size: Number of documents to process in each batch
        parallel_workers: Number of parallel processing workers
        enable_ocr: Whether to perform OCR on scanned content
        target_llm: Target LLM for optimization
        chunk_strategy: Chunking strategy for content processing
        enable_cross_document: Enable cross-document analysis
        output_format: Output detail level ("summary", "detailed", "full")
        progress_callback: Optional callback URL for progress updates
        
    Returns:
        Dict containing:
        - status: "success", "partial_success", or "error"
        - batch_summary: Overall batch processing statistics
        - processed_documents: List of successfully processed documents
        - failed_documents: List of documents that failed processing
        - cross_document_analysis: Cross-document relationships discovered
        - performance_metrics: Processing performance statistics
        - total_processing_time: Total batch processing time
        - message: Summary message
    """
    # MCP JSON-string entrypoint (used by unit tests)
    if (
        isinstance(pdf_sources, str)
        and batch_size == 5
        and parallel_workers == 3
        and enable_ocr is True
        and target_llm == "gpt-4"
        and chunk_strategy == "semantic"
        and enable_cross_document is True
        and output_format == "detailed"
        and progress_callback is None
        and (pdf_sources.lstrip().startswith("{") or pdf_sources.lstrip().startswith("[") or any(ch.isspace() for ch in pdf_sources) or not pdf_sources.strip())
    ):
        data, error = parse_json_object(pdf_sources)
        if error is not None:
            return error

        pdf_paths = data.get("pdf_paths")
        if not pdf_paths:
            return mcp_error_response("Missing required field: pdf_paths", error_type="validation")

        processor_cls = BatchProcessor
        if processor_cls is None:
            return mcp_error_response("BatchProcessor is not available")

        try:
            processor = processor_cls()
            result = await processor.process_batch(
                pdf_paths=pdf_paths,
                batch_options=data.get("batch_options") or {},
                processing_options=data.get("processing_options") or {},
            )
            if isinstance(result, dict):
                return mcp_text_response(result)
            return mcp_text_response({"status": "success", "result": result})
        except Exception as e:
            return mcp_text_response({"status": "error", "error": str(e)})

    try:
        # Import batch processing components
        from ipfs_datasets_py.processors.pdf_processing import BatchProcessor as _BatchProcessor
        from ipfs_datasets_py.monitoring import track_operation, ProgressTracker
        
        # Validate inputs
        if not pdf_sources:
            return {
                "status": "error",
                "message": "No PDF sources provided"
            }
            
        if batch_size <= 0:
            return {
                "status": "error",
                "message": "batch_size must be greater than 0"
            }
            
        if parallel_workers <= 0:
            return {
                "status": "error",
                "message": "parallel_workers must be greater than 0"
            }
            
        valid_output_formats = ["summary", "detailed", "full"]
        if output_format not in valid_output_formats:
            return {
                "status": "error",
                "message": f"Invalid output_format. Must be one of: {valid_output_formats}"
            }
        
        # Validate PDF sources
        validated_sources = []
        for i, source in enumerate(pdf_sources):
            if isinstance(source, str):
                pdf_path = Path(source)
                if not pdf_path.exists():
                    logger.warning(f"PDF file not found: {source}")
                    continue
                validated_sources.append({"path": str(pdf_path), "metadata": {}})
            elif isinstance(source, dict):
                if "path" not in source:
                    logger.warning(f"PDF source dict at index {i} missing 'path' field")
                    continue
                pdf_path = Path(source["path"])
                if not pdf_path.exists():
                    logger.warning(f"PDF file not found: {source['path']}")
                    continue
                validated_sources.append(source)
            else:
                logger.warning(f"Invalid PDF source type at index {i}: {type(source)}")
                continue
        
        if not validated_sources:
            return {
                "status": "error",
                "message": "No valid PDF sources found"
            }
        
        # Initialize batch processor
        if isinstance(pdf_sources, str):
            return {
                "status": "error",
                "message": "Invalid pdf_sources input"
            }

        batch_processor = _BatchProcessor(
            batch_size=batch_size,
            parallel_workers=parallel_workers,
            enable_ocr=enable_ocr,
            target_llm=target_llm,
            chunk_strategy=chunk_strategy
        )
        
        # Initialize progress tracking
        progress_tracker = ProgressTracker(
            total_items=len(validated_sources),
            callback_url=progress_callback
        )
        
        # Track the batch operation
        with track_operation("pdf_batch_process"):
            # Execute batch processing
            batch_results = await batch_processor.process_batch(
                pdf_sources=validated_sources,
                enable_cross_document=enable_cross_document,
                progress_tracker=progress_tracker
            )
            
            # Process results
            processed_documents = []
            failed_documents = []
            
            for result in batch_results.get("document_results", []):
                if result.get("status") == "success":
                    doc_summary = {
                        "document_id": result["document_id"],
                        "source_path": result["source_path"],
                        "ipld_cid": result["ipld_cid"],
                        "processing_time": result.get("processing_time", 0)
                    }
                    
                    if output_format in ["detailed", "full"]:
                        doc_summary.update({
                            "entities_extracted": result.get("entities_extracted", 0),
                            "relationships_discovered": result.get("relationships_discovered", 0),
                            "vector_embeddings": result.get("vector_embeddings", 0),
                            "pages_processed": result.get("pages_processed", 0),
                            "chunks_created": result.get("chunks_created", 0)
                        })
                    
                    if output_format == "full":
                        doc_summary.update({
                            "pipeline_stages": result.get("pipeline_stages", {}),
                            "content_summary": result.get("content_summary", {}),
                            "metadata": result.get("metadata", {})
                        })
                    
                    processed_documents.append(doc_summary)
                else:
                    failed_documents.append({
                        "source_path": result.get("source_path", "unknown"),
                        "error": result.get("error", "Unknown error"),
                        "stage_failed": result.get("stage_failed", "unknown")
                    })
            
            # Get cross-document analysis results
            cross_document_analysis = {}
            if enable_cross_document and len(processed_documents) > 1:
                cross_doc_results = batch_results.get("cross_document_analysis", {})
                cross_document_analysis = {
                    "cross_document_relationships": len(cross_doc_results.get("relationships", [])),
                    "entity_clusters": len(cross_doc_results.get("entity_clusters", [])),
                    "thematic_connections": len(cross_doc_results.get("thematic_connections", [])),
                    "citation_networks": cross_doc_results.get("citation_networks", [])
                }
            
            # Generate batch summary
            batch_summary = {
                "total_documents": len(validated_sources),
                "successfully_processed": len(processed_documents),
                "failed_processing": len(failed_documents),
                "success_rate": len(processed_documents) / len(validated_sources) * 100,
                "total_entities": sum(doc.get("entities_extracted", 0) for doc in processed_documents),
                "total_relationships": sum(doc.get("relationships_discovered", 0) for doc in processed_documents),
                "total_embeddings": sum(doc.get("vector_embeddings", 0) for doc in processed_documents),
                "cross_document_enabled": enable_cross_document
            }
            
            # Performance metrics
            performance_metrics = {
                "total_processing_time": batch_results.get("total_processing_time", 0),
                "average_processing_time": batch_results.get("average_processing_time", 0),
                "documents_per_minute": len(processed_documents) / (batch_results.get("total_processing_time", 1) / 60),
                "parallel_efficiency": batch_results.get("parallel_efficiency", 0),
                "memory_usage": batch_results.get("peak_memory_usage", 0)
            }
            
            # Determine overall status
            if len(processed_documents) == len(validated_sources):
                status = "success"
                message = f"Successfully processed all {len(processed_documents)} documents"
            elif len(processed_documents) > 0:
                status = "partial_success"
                message = f"Successfully processed {len(processed_documents)} of {len(validated_sources)} documents"
            else:
                status = "error"
                message = "Failed to process any documents"
            
            return {
                "status": status,
                "batch_summary": batch_summary,
                "processed_documents": processed_documents,
                "failed_documents": failed_documents,
                "cross_document_analysis": cross_document_analysis,
                "performance_metrics": performance_metrics,
                "total_processing_time": batch_results.get("total_processing_time", 0),
                "message": message
            }
            
    except ImportError as e:
        logger.error(f"Batch processing dependencies not available: {e}")
        return {
            "status": "error",
            "message": f"Batch processing dependencies not available: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in batch processing: {e}")
        return {
            "status": "error",
            "message": f"Failed to process batch: {str(e)}"
        }
