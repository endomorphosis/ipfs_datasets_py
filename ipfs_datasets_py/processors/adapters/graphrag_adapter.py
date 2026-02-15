"""
GraphRAGProcessorAdapter - Adapter for GraphRAG processing.

Wraps existing GraphRAG processors to implement ProcessorProtocol.
This will eventually use the consolidated GraphRAG processor.
"""

from __future__ import annotations

import logging
from typing import Union, Dict, Any, List
from pathlib import Path
import time

from ..core.protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
)

logger = logging.getLogger(__name__)


class GraphRAGProcessorAdapter:
    """
    Adapter for GraphRAG processors that implements ProcessorProtocol.
    
    This adapter wraps existing GraphRAG functionality (website processing,
    document graph extraction) to provide a unified interface.
    
    Implements the synchronous ProcessorProtocol from processors.core.
    
    Example:
        >>> from ipfs_datasets_py.processors.core import ProcessingContext, InputType
        >>> adapter = GraphRAGProcessorAdapter()
        >>> context = ProcessingContext(
        ...     input_type=InputType.URL,
        ...     source="https://example.com",
        ...     metadata={"format": "html"}
        ... )
        >>> can_handle = adapter.can_handle(context)
        >>> result = adapter.process(context)
    """
    
    def __init__(self):
        """Initialize adapter."""
        self._processor = None
        self._name = "GraphRAGProcessor"
        self._priority = 10
    
    def _get_processor(self):
        """Lazy-load GraphRAG processor on first use."""
        if self._processor is None:
            try:
                # Use new unified processor (consolidates all 4 implementations)
                from ..graphrag.unified_graphrag import UnifiedGraphRAGProcessor
                self._processor = UnifiedGraphRAGProcessor()
                logger.info("UnifiedGraphRAGProcessor loaded (consolidated implementation)")
            except ImportError:
                try:
                    # Fall back to advanced processor
                    from ..advanced_graphrag_website_processor import AdvancedGraphRAGWebsiteProcessor
                    self._processor = AdvancedGraphRAGWebsiteProcessor()
                    logger.info("AdvancedGraphRAGWebsiteProcessor loaded (fallback)")
                except ImportError:
                    try:
                        # Fall back to website processor
                        from ..website_graphrag_processor import WebsiteGraphRAGProcessor
                        self._processor = WebsiteGraphRAGProcessor()
                        logger.info("WebsiteGraphRAGProcessor loaded (fallback)")
                    except ImportError:
                        try:
                            # Fall back to basic processor
                            from ..graphrag_processor import GraphRAGProcessor
                            self._processor = GraphRAGProcessor()
                            logger.info("GraphRAGProcessor loaded (fallback)")
                        except ImportError as e:
                            logger.error(f"No GraphRAG processor available: {e}")
                            raise RuntimeError("No GraphRAG processor available")
        return self._processor
    
    def can_handle(self, context: ProcessingContext) -> bool:
        """
        Check if this adapter can handle web/document inputs for GraphRAG.
        
        Args:
            context: Processing context with input information
            
        Returns:
            True if input is a URL or document suitable for GraphRAG
        """
        # Check if it's a URL
        if context.input_type in (InputType.URL, InputType.IPFS_CID, InputType.IPNS):
            return True
        
        # Check format from metadata
        fmt = context.get_format()
        if fmt and fmt.lower() in ('html', 'htm', 'md', 'txt'):
            return True
        
        # Check source if it's a file
        source_str = str(context.source).lower()
        if source_str.endswith(('.html', '.htm', '.md', '.txt')):
            return True
        
        return False
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        """
        Process input for GraphRAG and return standardized result.
        
        Args:
            context: Processing context with input source and options
            
        Returns:
            ProcessingResult with knowledge graph and vectors
        """
        start_time = time.time()
        source = context.source
        
        try:
            processor = self._get_processor()
            
            # Process based on input type
            if context.input_type == InputType.URL:
                # Process website
                result_data = self._process_website(processor, str(source), context.options)
            else:
                # Process document
                result_data = self._process_document(processor, source, context.options)
            
            # Extract knowledge graph and content
            kg = result_data.get("knowledge_graph", {})
            content = result_data.get("content", {})
            
            # Generate vectors (placeholder)
            vectors: List[List[float]] = []
            
            # Processing time
            elapsed = time.time() - start_time
            
            return ProcessingResult(
                success=True,
                knowledge_graph=kg,
                vectors=vectors,
                metadata={
                    "processor": self._name,
                    "processor_type": "graphrag",
                    "processing_time": elapsed,
                    "entity_count": len(kg.get("entities", [])),
                    "relationship_count": len(kg.get("relationships", [])),
                    **content
                }
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            
            logger.error(f"GraphRAG processing failed for {source}: {e}")
            
            return ProcessingResult(
                success=False,
                knowledge_graph={},
                vectors=[],
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "error": str(e)
                },
                errors=[f"GraphRAG processing failed: {str(e)}"]
            )
    
    def _process_website(self, processor, url: str, options: dict) -> dict:
        """Process website for GraphRAG."""
        # Simplified - actual implementation will call processor methods
        
        # Create page entity
        page_entity = {
            "id": f"page_{abs(hash(url))}",
            "type": "WebPage",
            "label": url,
            "properties": {"url": url}
        }
        
        kg = {
            "entities": [page_entity],
            "relationships": [],
            "source": url
        }
        
        return {
            "knowledge_graph": kg,
            "content": {
                "url": url,
                "type": "website"
            }
        }
    
    def _process_document(self, processor, file_path: Union[str, Path], options: dict) -> dict:
        """Process document for GraphRAG."""
        # Create document entity
        doc_entity = {
            "id": f"doc_{abs(hash(str(file_path)))}",
            "type": "Document",
            "label": Path(file_path).name,
            "properties": {"path": str(file_path)}
        }
        
        kg = {
            "entities": [doc_entity],
            "relationships": [],
            "source": str(file_path)
        }
        
        return {
            "knowledge_graph": kg,
            "content": {
                "path": str(file_path),
                "type": "document"
            }
        }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return processor capabilities and metadata.
        
        Returns:
            Dictionary with processor name, priority, supported formats, etc.
        """
        return {
            "name": self._name,
            "priority": self._priority,
            "formats": ["html", "htm", "md", "txt"],
            "input_types": ["url", "webpage", "file"],
            "outputs": ["knowledge_graph", "text"],
            "features": [
                "entity_extraction",
                "relationship_extraction",
                "graph_generation"
            ]
        }
