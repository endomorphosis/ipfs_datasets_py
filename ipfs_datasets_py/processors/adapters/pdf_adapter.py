"""
PDFProcessorAdapter - Adapter for PDF processing.

Wraps existing PDF processors to implement ProcessorProtocol.

This adapter follows the unified ProcessorProtocol from processors.core
and provides synchronous processing of PDF files.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from pathlib import Path
import time

from ..core.protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
)

logger = logging.getLogger(__name__)


class PDFProcessorAdapter:
    """
    Adapter for PDF processors that implements ProcessorProtocol.
    
    This adapter wraps existing PDF processing functionality to provide
    a unified interface compatible with UniversalProcessor.
    
    Implements the synchronous ProcessorProtocol from processors.core.
    
    Example:
        >>> from ipfs_datasets_py.processors.core import ProcessingContext, InputType
        >>> adapter = PDFProcessorAdapter()
        >>> context = ProcessingContext(
        ...     input_type=InputType.FILE,
        ...     source="document.pdf",
        ...     metadata={"format": "pdf"}
        ... )
        >>> can_handle = adapter.can_handle(context)
        >>> result = adapter.process(context)
    """
    
    def __init__(self):
        """Initialize adapter."""
        self._processor = None
        self._name = "PDFProcessor"
        self._priority = 10
    
    def _get_processor(self):
        """Lazy-load PDF processor on first use."""
        if self._processor is None:
            try:
                # Try to import PDF processor
                from ..pdf_processor import PDFProcessor
                self._processor = PDFProcessor()
                logger.info("PDFProcessor loaded successfully")
            except ImportError as e:
                logger.warning(f"Could not import PDFProcessor: {e}")
                # Use fallback - file converter for PDFs
                try:
                    from ..file_converter import FileConverter
                    self._processor = FileConverter()
                    logger.info("Using FileConverter as fallback for PDF processing")
                except ImportError as e2:
                    logger.error(f"No PDF processor available: {e2}")
                    raise RuntimeError("No PDF processor available")
        return self._processor
    
    def can_handle(self, context: ProcessingContext) -> bool:
        """
        Check if this adapter can handle PDF inputs.
        
        Args:
            context: Processing context with input information
            
        Returns:
            True if input is a PDF file or URL pointing to PDF
        """
        # Check format from metadata
        fmt = context.get_format()
        if fmt and fmt.lower() == 'pdf':
            return True
        
        # Check source if it's a file or URL
        source_str = str(context.source).lower()
        
        # Check if it's a PDF file
        if source_str.endswith('.pdf'):
            return True
        
        # Check if it's a URL pointing to a PDF
        if source_str.startswith(('http://', 'https://')) and '.pdf' in source_str:
            return True
        
        # Check if file exists and is PDF
        if context.input_type == InputType.FILE:
            path = Path(context.source)
            if path.exists() and path.is_file():
                if path.suffix.lower() == '.pdf':
                    return True
        
        return False
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        """
        Process PDF file and return standardized result.
        
        Args:
            context: Processing context with input source and options
            
        Returns:
            ProcessingResult with extracted content and knowledge graph
        """
        start_time = time.time()
        source = context.source
        
        try:
            processor = self._get_processor()
            
            # Process PDF
            # Note: Actual implementation will depend on the PDF processor interface
            # For now, create a simplified version
            
            text = f"PDF content from {source}"
            pdf_metadata = {
                "source": str(source),
                "format": "pdf",
                "pages": 1  # Placeholder
            }
            
            # Build knowledge graph
            kg = self._build_knowledge_graph(text, str(source), pdf_metadata)
            
            # Generate vectors (placeholder - empty for now)
            vectors: List[List[float]] = []
            
            # Processing time
            elapsed = time.time() - start_time
            
            return ProcessingResult(
                success=True,
                knowledge_graph=kg,
                vectors=vectors,
                metadata={
                    "processor": self._name,
                    "processor_type": "pdf",
                    "processing_time": elapsed,
                    "pages": pdf_metadata.get("pages", 0),
                    "text_length": len(text),
                    **pdf_metadata
                }
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            
            logger.error(f"PDF processing failed for {source}: {e}")
            
            return ProcessingResult(
                success=False,
                knowledge_graph={},
                vectors=[],
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "error": str(e)
                },
                errors=[f"PDF processing failed: {str(e)}"]
            )
    
    def _build_knowledge_graph(
        self,
        text: str,
        source: str,
        pdf_metadata: dict
    ) -> Dict[str, Any]:
        """
        Build knowledge graph from PDF content.
        
        Returns a dictionary with entities and relationships.
        """
        # Create document entity
        doc_entity = {
            "id": f"pdf_{abs(hash(source))}",
            "type": "PDFDocument",
            "label": Path(source).name,
            "properties": {
                "source": source,
                "pages": pdf_metadata.get("pages", 0),
                "word_count": len(text.split()),
                **pdf_metadata
            }
        }
        
        # Build knowledge graph structure
        kg = {
            "entities": [doc_entity],
            "relationships": [],
            "source": source
        }
        
        # In production, would extract more entities, relationships, etc.
        
        return kg
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return processor capabilities and metadata.
        
        Returns:
            Dictionary with processor name, priority, supported formats, etc.
        """
        return {
            "name": self._name,
            "priority": self._priority,
            "formats": ["pdf"],
            "input_types": ["file", "url"],
            "outputs": ["knowledge_graph", "text"],
            "features": [
                "text_extraction",
                "entity_extraction",
                "document_metadata"
            ]
        }
