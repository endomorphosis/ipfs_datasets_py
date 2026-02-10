"""
PDF LLM Optimization Tool

MCP tool for optimizing PDF content specifically for Large Language Model
consumption with advanced chunking, summarization, and context enhancement.
"""

import anyio
import logging
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger(__name__)

async def pdf_optimize_for_llm(
    pdf_source: Union[str, dict],
    target_llm: str = "gpt-4",
    chunk_strategy: str = "semantic",
    max_chunk_size: int = 4000,
    overlap_size: int = 200,
    preserve_structure: bool = True,
    include_metadata: bool = True
) -> Dict[str, Any]:
    """
    Optimize PDF content specifically for Large Language Model consumption
    with advanced chunking strategies, summarization, and context enhancement.
    
    This tool provides LLM-optimized content processing including:
    - Intelligent chunking strategies (semantic, structural, adaptive)
    - Content summarization and key information extraction
    - Context preservation and enhancement
    - Metadata integration for better LLM understanding
    - Format optimization for specific LLM architectures
    - Token efficiency analysis and optimization
    
    Args:
        pdf_source: Path to PDF file or document data dict
        target_llm: Target LLM model ("gpt-4", "claude", "gemini", "llama")
        chunk_strategy: Chunking strategy ("semantic", "structural", "adaptive", "fixed")
        max_chunk_size: Maximum size per chunk in characters
        overlap_size: Overlap between chunks in characters
        preserve_structure: Maintain document structure in optimization
        include_metadata: Include document metadata in optimized content
        
    Returns:
        Dict containing:
        - status: "success" or "error"
        - document_info: Information about the processed document
        - optimized_chunks: LLM-optimized content chunks
        - document_summary: High-level document summary
        - structure_analysis: Analysis of document structure
        - optimization_metrics: Metrics about the optimization process
        - llm_recommendations: Specific recommendations for the target LLM
        - token_analysis: Token usage analysis and efficiency metrics
        - processing_time: Optimization processing time
        - message: Success/error message
    """
    try:
        # Import LLM optimization components
        from ipfs_datasets_py.processors.pdf_processing import LLMOptimizer
        from ipfs_datasets_py.utils.chunk_optimizer import ChunkOptimizer, make_chunk_optimizer
        from ipfs_datasets_py.monitoring import monitor_context
        
        # Validate inputs
        match pdf_source:
            case str() as pdf_path_str:
                from pathlib import Path
                pdf_path = Path(pdf_path_str)
                if not pdf_path.exists():
                    return {
                    "status": "error",
                    "message": f"PDF file not found: {pdf_path_str}"
                    }
                document_id = None
            case dict() as pdf_dict:
                match pdf_dict:
                    case {"document_id": document_id}:
                        pdf_path = None
                    case {"path": path}:
                        pdf_path = Path(path)
                        document_id = None
                    case _:
                        return {
                            "status": "error",
                            "message": "PDF source dict must contain 'document_id' or 'path'"
                        }
            case _:
                return {
                    "status": "error",
                    "message": "PDF source must be file path string or data dict"
                }
            
        # Validate parameters
        valid_llms = ["gpt-4", "gpt-3.5", "claude", "claude-3", "gemini", "llama", "mistral"]
        if target_llm not in valid_llms:
            return {
                "status": "error",
                "message": f"Invalid target_llm. Must be one of: {valid_llms}"
            }
            
        valid_strategies = ["semantic", "structural", "adaptive", "fixed"]
        if chunk_strategy not in valid_strategies:
            return {
                "status": "error",
                "message": f"Invalid chunk_strategy. Must be one of: {valid_strategies}"
            }
            
        if max_chunk_size <= 0:
            return {
                "status": "error",
                "message": "max_chunk_size must be greater than 0"
            }
            
        if overlap_size < 0 or overlap_size >= max_chunk_size:
            return {
                "status": "error",
                "message": "overlap_size must be non-negative and less than max_chunk_size"
            }
        
        # Initialize optimizer with target LLM configuration
        llm_optimizer = LLMOptimizer(
            target_llm=target_llm,
            chunk_strategy=chunk_strategy,
            max_chunk_size=max_chunk_size,
            overlap_size=overlap_size
        )
        
        # Track the optimization operation
        with monitor_context("pdf_optimize_for_llm"):
            # Get or process document content
            if document_id:
                # Optimize already processed document
                from ipfs_datasets_py.processors.pdf_processing import GraphRAGIntegrator
                integrator = GraphRAGIntegrator()
                
                document_content = await integrator.get_document_content(document_id)
                if not document_content:
                    return {
                        "status": "error",
                        "message": f"Document not found: {document_id}"
                    }
                document_info = await integrator.get_document_info(document_id)
            else:
                # Process PDF file and extract content
                from ipfs_datasets_py.processors.pdf_processing import PDFProcessor
                processor = PDFProcessor()
                
                # Extract structured content from PDF
                content_result = await processor.extract_structured_content(str(pdf_path))
                if content_result.get("status") != "success":
                    return {
                        "status": "error",
                        "message": f"Failed to extract content from PDF: {content_result.get('message')}"
                    }
                
                document_content = content_result["content"]
                document_info = {
                    "source_path": str(pdf_path),
                    "pages": content_result.get("pages", 0),
                    "text_length": len(document_content.get("text", "")),
                    "structure": content_result.get("structure", {})
                }
            
            # Perform LLM optimization
            optimization_result = await llm_optimizer.optimize_document(
                document_content=document_content,
                preserve_structure=preserve_structure,
                include_metadata=include_metadata
            )
            
            # Generate optimized chunks
            chunk_optimizer = ChunkOptimizer(
                strategy=chunk_strategy,
                target_llm=target_llm,
                max_size=max_chunk_size,
                overlap_size=overlap_size
            )
            
            chunking_result = await chunk_optimizer.create_optimized_chunks(
                content=optimization_result["optimized_content"],
                structure=document_content.get("structure", {}),
                metadata=document_content.get("metadata", {})
            )
            
            optimized_chunks = []
            for i, chunk in enumerate(chunking_result.get("chunks", [])):
                chunk_data = {
                    "chunk_id": f"chunk_{i:04d}",
                    "content": chunk["content"],
                    "metadata": chunk.get("metadata", {}),
                    "token_count": chunk.get("token_count", 0),
                    "chunk_type": chunk.get("type", "content"),
                    "page_range": chunk.get("page_range", []),
                    "structure_level": chunk.get("structure_level", 0),
                    "semantic_score": chunk.get("semantic_score", 0),
                    "importance_score": chunk.get("importance_score", 0)
                }
                optimized_chunks.append(chunk_data)
            
            # Analyze document structure
            structure_analysis = {
                "total_pages": document_info.get("pages", 0),
                "sections_detected": len(document_content.get("structure", {}).get("sections", [])),
                "headings_count": len(document_content.get("structure", {}).get("headings", [])),
                "tables_count": len(document_content.get("structure", {}).get("tables", [])),
                "images_count": len(document_content.get("structure", {}).get("images", [])),
                "complexity_score": optimization_result.get("complexity_score", 0),
                "structure_quality": optimization_result.get("structure_quality", "medium")
            }
            
            # Generate optimization metrics
            optimization_metrics = {
                "original_length": len(document_content.get("text", "")),
                "optimized_length": len(optimization_result.get("optimized_content", "")),
                "compression_ratio": optimization_result.get("compression_ratio", 1.0),
                "chunks_created": len(optimized_chunks),
                "average_chunk_size": sum(c["token_count"] for c in optimized_chunks) / len(optimized_chunks) if optimized_chunks else 0,
                "overlap_efficiency": chunking_result.get("overlap_efficiency", 0),
                "semantic_coherence": optimization_result.get("semantic_coherence", 0)
            }
            
            # Generate LLM-specific recommendations
            llm_recommendations = llm_optimizer.get_llm_recommendations(
                target_llm=target_llm,
                content_analysis=optimization_result,
                chunk_analysis=chunking_result
            )
            
            # Analyze token usage
            token_analysis = {
                "estimated_total_tokens": optimization_result.get("estimated_tokens", 0),
                "tokens_per_chunk": [c["token_count"] for c in optimized_chunks],
                "token_efficiency": optimization_result.get("token_efficiency", 0),
                "cost_estimate": llm_optimizer.estimate_processing_cost(
                    target_llm=target_llm,
                    token_count=optimization_result.get("estimated_tokens", 0)
                ),
                "recommended_batch_size": llm_recommendations.get("batch_size", 1)
            }
            
            return {
                "status": "success",
                "document_info": document_info,
                "optimized_chunks": optimized_chunks,
                "structure_analysis": structure_analysis,
                "optimization_metrics": optimization_metrics,
                "llm_recommendations": llm_recommendations,
                "token_analysis": token_analysis,
                "optimization_settings": {
                    "target_llm": target_llm,
                    "chunk_strategy": chunk_strategy,
                    "max_chunk_size": max_chunk_size,
                    "overlap_size": overlap_size,
                    "preserve_structure": preserve_structure,
                    "include_metadata": include_metadata
                },
                "processing_time": optimization_result.get("processing_time", 0),
                "message": f"Successfully optimized document for {target_llm}. Created {len(optimized_chunks)} chunks with {optimization_metrics['compression_ratio']:.2f} compression ratio."
            }
            
    except ImportError as e:
        logger.error(f"LLM optimization dependencies not available: {e}")
        return {
            "status": "error",
            "message": f"LLM optimization dependencies not available: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error optimizing PDF for LLM: {e}")
        return {
            "status": "error",
            "message": f"Failed to optimize PDF for LLM: {str(e)}"
        }
