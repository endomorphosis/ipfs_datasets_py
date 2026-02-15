"""
GraphRAGProcessorAdapter - Adapter for GraphRAG processing.

Wraps the consolidated GraphRAG processor (processors.specialized.graphrag) 
to implement ProcessorProtocol. Uses UnifiedGraphRAGProcessor as the primary
implementation with fallbacks for backward compatibility.

Updated: 2026-02-15 - Now uses processors.specialized.graphrag
"""

from __future__ import annotations

import logging
from typing import Union
from pathlib import Path
import time

from ..protocol import (
    ProcessorProtocol,
    ProcessingResult,
    ProcessingMetadata,
    ProcessingStatus,
    InputType,
    KnowledgeGraph,
    VectorStore,
    Entity,
    Relationship
)

logger = logging.getLogger(__name__)


class GraphRAGProcessorAdapter:
    """
    Adapter for GraphRAG processors that implements ProcessorProtocol.
    
    This adapter wraps existing GraphRAG functionality (website processing,
    document graph extraction) to provide a unified interface.
    
    Example:
        >>> adapter = GraphRAGProcessorAdapter()
        >>> can_process = await adapter.can_process("https://example.com")
        >>> result = await adapter.process("https://example.com")
    """
    
    def __init__(self):
        """Initialize adapter."""
        self._processor = None
    
    def _get_processor(self):
        """Lazy-load GraphRAG processor on first use."""
        if self._processor is None:
            try:
                # Use new specialized unified processor (consolidates all implementations)
                from ..specialized.graphrag import UnifiedGraphRAGProcessor
                self._processor = UnifiedGraphRAGProcessor()
                logger.info("UnifiedGraphRAGProcessor loaded from specialized.graphrag")
            except ImportError as e:
                logger.warning(f"Could not load UnifiedGraphRAGProcessor from specialized.graphrag: {e}")
                try:
                    # Fall back to old location (deprecated)
                    from ..graphrag.unified_graphrag import UnifiedGraphRAGProcessor
                    self._processor = UnifiedGraphRAGProcessor()
                    logger.warning("Loaded UnifiedGraphRAGProcessor from deprecated location")
                except ImportError:
                    try:
                        # Fall back to deprecated processors (with warnings)
                        from ..graphrag_processor import GraphRAGProcessor
                        self._processor = GraphRAGProcessor()
                        logger.warning("Loaded GraphRAGProcessor from deprecated location")
                    except ImportError as e:
                        logger.error(f"No GraphRAG processor available: {e}")
                        raise RuntimeError("No GraphRAG processor available")
        return self._processor
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if this adapter can handle web/document inputs for GraphRAG.
        
        Args:
            input_source: Input to check
            
        Returns:
            True if input is a URL or document suitable for GraphRAG
        """
        input_str = str(input_source).lower()
        
        # Check if it's a URL
        if input_str.startswith(('http://', 'https://')):
            return True
        
        # Check if it's a document that can benefit from GraphRAG
        # (PDFs, docs, etc. can be processed for knowledge graphs)
        if input_str.endswith(('.html', '.htm', '.md', '.txt')):
            return True
        
        return False
    
    async def process(
        self,
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process input for GraphRAG and return standardized result.
        
        Args:
            input_source: URL or document path
            **options: Processing options
            
        Returns:
            ProcessingResult with knowledge graph and vectors
        """
        start_time = time.time()
        
        # Metadata for result
        input_type = InputType.URL if str(input_source).startswith(('http://', 'https://')) else InputType.FILE
        metadata = ProcessingMetadata(
            processor_name="GraphRAGProcessor",
            processor_version="1.0",
            input_type=input_type
        )
        
        try:
            processor = self._get_processor()
            
            # Process based on input type
            if input_type == InputType.URL:
                # Process website
                result_data = await self._process_website(processor, str(input_source), **options)
            else:
                # Process document
                result_data = await self._process_document(processor, input_source, **options)
            
            # Extract knowledge graph and content
            kg = result_data.get("knowledge_graph", KnowledgeGraph(source=str(input_source)))
            content = result_data.get("content", {})
            
            # Generate vectors
            vectors = VectorStore(
                metadata={
                    "model": "graphrag",
                    "source": str(input_source)
                }
            )
            
            # Processing time
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.SUCCESS
            
            return ProcessingResult(
                knowledge_graph=kg,
                vectors=vectors,
                content=content,
                metadata=metadata,
                extra={
                    "processor_type": "graphrag",
                    "entity_count": len(kg.entities),
                    "relationship_count": len(kg.relationships)
                }
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.FAILED
            metadata.add_error(str(e))
            
            logger.error(f"GraphRAG processing failed for {input_source}: {e}")
            
            return ProcessingResult(
                knowledge_graph=KnowledgeGraph(source=str(input_source)),
                vectors=VectorStore(),
                content={"error": str(e)},
                metadata=metadata
            )
    
    async def _process_website(self, processor, url: str, **options) -> dict:
        """Process website for GraphRAG."""
        # Simplified - actual implementation will call processor methods
        kg = KnowledgeGraph(source=url)
        
        # Create page entity
        page_entity = Entity(
            id=f"page_{hash(url)}",
            type="WebPage",
            label=url,
            properties={"url": url}
        )
        kg.add_entity(page_entity)
        
        return {
            "knowledge_graph": kg,
            "content": {
                "url": url,
                "type": "website"
            }
        }
    
    async def _process_document(self, processor, file_path: Union[str, Path], **options) -> dict:
        """Process document for GraphRAG."""
        kg = KnowledgeGraph(source=str(file_path))
        
        # Create document entity
        doc_entity = Entity(
            id=f"doc_{hash(str(file_path))}",
            type="Document",
            label=Path(file_path).name,
            properties={"path": str(file_path)}
        )
        kg.add_entity(doc_entity)
        
        return {
            "knowledge_graph": kg,
            "content": {
                "path": str(file_path),
                "type": "document"
            }
        }
    
    def get_supported_types(self) -> list[str]:
        """Return supported input types."""
        return ["url", "webpage", "html", "document"]
    
    def get_priority(self) -> int:
        """Return processor priority."""
        return 10
    
    def get_name(self) -> str:
        """Return processor name."""
        return "GraphRAGProcessor"
