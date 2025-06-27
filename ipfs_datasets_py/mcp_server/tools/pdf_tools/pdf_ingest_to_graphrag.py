"""
PDF to GraphRAG Ingestion Tool

MCP tool for ingesting PDF documents into the GraphRAG system with
complete pipeline processing including OCR, LLM optimization, and
entity extraction.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union

logger = logging.getLogger(__name__)

async def pdf_ingest_to_graphrag(
    pdf_source: Union[str, dict],
    metadata: Optional[Dict[str, Any]] = None,
    enable_ocr: bool = True,
    target_llm: str = "gpt-4",
    chunk_strategy: str = "semantic",
    enable_cross_document: bool = True
) -> Dict[str, Any]:
    """
    Ingest a PDF document into the GraphRAG system with full pipeline processing.
    
    This tool executes the complete PDF processing pipeline:
    1. PDF validation and decomposition
    2. IPLD structuring  
    3. Multi-engine OCR processing
    4. LLM-optimized content chunking
    5. Entity and relationship extraction
    6. Vector embedding generation
    7. GraphRAG integration and indexing
    8. Cross-document relationship discovery
    
    Args:
        pdf_source: Path to PDF file or PDF data dict
        metadata: Additional metadata for the document
        enable_ocr: Whether to perform OCR on scanned content
        target_llm: Target LLM for optimization (gpt-4, claude, etc.)
        chunk_strategy: Chunking strategy ("semantic", "fixed", "adaptive")
        enable_cross_document: Enable cross-document relationship discovery
        
    Returns:
        Dict containing:
        - status: "success" or "error"
        - document_id: Unique identifier for the processed document
        - ipld_cid: IPLD content identifier for the document
        - entities_added: Number of entities extracted and added
        - relationships_added: Number of relationships discovered
        - vector_embeddings: Number of vector embeddings created
        - processing_time: Total processing time in seconds
        - pipeline_stages: Status of each pipeline stage
        - message: Success/error message
    """
    try:
        # Import PDF processing components
        from ipfs_datasets_py.pdf_processing import PDFProcessor
        from ipfs_datasets_py.ipld import IPLDStorage
        from ipfs_datasets_py.monitoring import track_operation
        
        # Initialize processor
        processor = PDFProcessor(
            enable_ocr=enable_ocr,
            target_llm=target_llm,
            chunk_strategy=chunk_strategy
        )
        
        # Validate PDF source
        if isinstance(pdf_source, str):
            pdf_path = Path(pdf_source)
            if not pdf_path.exists():
                return {
                    "status": "error",
                    "message": f"PDF file not found: {pdf_source}"
                }
        elif isinstance(pdf_source, dict):
            # Handle PDF data dict
            if "path" not in pdf_source:
                return {
                    "status": "error", 
                    "message": "PDF source dict must contain 'path' field"
                }
            pdf_path = Path(pdf_source["path"])
            metadata = metadata or {}
            metadata.update(pdf_source.get("metadata", {}))
        else:
            return {
                "status": "error",
                "message": "PDF source must be file path string or data dict"
            }
            
        # Track the complete operation
        with track_operation("pdf_ingest_to_graphrag"):
            # Execute the full PDF processing pipeline
            result = await processor.process_complete_pipeline(
                pdf_path=str(pdf_path),
                metadata=metadata,
                enable_cross_document=enable_cross_document
            )
            
            # Extract result details
            pipeline_stages = result.get("pipeline_stages", {})
            processing_stats = result.get("processing_stats", {})
            
            return {
                "status": "success",
                "document_id": result["document_id"],
                "ipld_cid": result["ipld_cid"],
                "entities_added": processing_stats.get("entities_extracted", 0),
                "relationships_added": processing_stats.get("relationships_discovered", 0),
                "vector_embeddings": processing_stats.get("embeddings_created", 0),
                "processing_time": processing_stats.get("total_time", 0),
                "pipeline_stages": {
                    "decomposition": pipeline_stages.get("decomposition", {}).get("status"),
                    "ipld_structuring": pipeline_stages.get("ipld_structuring", {}).get("status"),
                    "ocr_processing": pipeline_stages.get("ocr_processing", {}).get("status"),
                    "llm_optimization": pipeline_stages.get("llm_optimization", {}).get("status"),
                    "entity_extraction": pipeline_stages.get("entity_extraction", {}).get("status"),
                    "vector_embedding": pipeline_stages.get("vector_embedding", {}).get("status"),
                    "graphrag_integration": pipeline_stages.get("graphrag_integration", {}).get("status"),
                    "cross_document_analysis": pipeline_stages.get("cross_document_analysis", {}).get("status")
                },
                "content_summary": {
                    "pages_processed": processing_stats.get("pages_processed", 0),
                    "text_length": processing_stats.get("text_length", 0),
                    "images_processed": processing_stats.get("images_processed", 0),
                    "chunks_created": processing_stats.get("chunks_created", 0)
                },
                "message": f"Successfully ingested PDF into GraphRAG system. Document ID: {result['document_id']}"
            }
            
    except ImportError as e:
        logger.error(f"PDF processing dependencies not available: {e}")
        return {
            "status": "error",
            "message": f"PDF processing dependencies not available: {str(e)}"
        }
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return {
            "status": "error",
            "message": f"File not found: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error ingesting PDF to GraphRAG: {e}")
        return {
            "status": "error",
            "message": f"Failed to ingest PDF: {str(e)}"
        }
