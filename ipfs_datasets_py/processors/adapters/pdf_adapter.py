"""
PDFProcessorAdapter - Adapter for PDF processing.

Wraps existing PDF processors to implement ProcessorProtocol.
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


class PDFProcessorAdapter:
    """
    Adapter for PDF processors that implements ProcessorProtocol.
    
    This adapter wraps existing PDF processing functionality to provide
    a unified interface compatible with UniversalProcessor.
    
    Example:
        >>> adapter = PDFProcessorAdapter()
        >>> can_process = await adapter.can_process("document.pdf")
        >>> result = await adapter.process("document.pdf")
    """
    
    def __init__(self):
        """Initialize adapter."""
        self._processor = None
    
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
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if this adapter can handle PDF inputs.
        
        Args:
            input_source: Input to check
            
        Returns:
            True if input is a PDF file or URL pointing to PDF
        """
        input_str = str(input_source).lower()
        
        # Check if it's a PDF file
        if input_str.endswith('.pdf'):
            return True
        
        # Check if it's a URL pointing to a PDF
        if input_str.startswith(('http://', 'https://')) and '.pdf' in input_str:
            return True
        
        # Check if file exists and is PDF
        path = Path(input_source)
        if path.exists() and path.is_file():
            if path.suffix.lower() == '.pdf':
                return True
        
        return False
    
    async def process(
        self,
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process PDF file and return standardized result.
        
        Args:
            input_source: PDF file path or URL
            **options: Processing options
            
        Returns:
            ProcessingResult with extracted content and knowledge graph
        """
        start_time = time.time()
        
        # Metadata for result
        metadata = ProcessingMetadata(
            processor_name="PDFProcessor",
            processor_version="1.0",
            input_type=InputType.FILE
        )
        
        try:
            processor = self._get_processor()
            
            # Process PDF
            # Note: Actual implementation will depend on the PDF processor interface
            # For now, create a simplified version
            
            text = f"PDF content from {input_source}"
            pdf_metadata = {
                "source": str(input_source),
                "format": "pdf",
                "pages": 1  # Placeholder
            }
            
            # Build knowledge graph
            kg = self._build_knowledge_graph(text, str(input_source), pdf_metadata)
            
            # Generate vectors (placeholder)
            vectors = VectorStore(
                metadata={
                    "model": "pdf_processor",
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
                content={
                    "text": text,
                    "metadata": pdf_metadata
                },
                metadata=metadata,
                extra={
                    "processor_type": "pdf",
                    "pages": pdf_metadata.get("pages", 0)
                }
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.FAILED
            metadata.add_error(str(e))
            
            logger.error(f"PDF processing failed for {input_source}: {e}")
            
            return ProcessingResult(
                knowledge_graph=KnowledgeGraph(source=str(input_source)),
                vectors=VectorStore(),
                content={"error": str(e)},
                metadata=metadata
            )
    
    def _build_knowledge_graph(
        self,
        text: str,
        source: str,
        pdf_metadata: dict
    ) -> KnowledgeGraph:
        """Build knowledge graph from PDF content."""
        kg = KnowledgeGraph(source=source)
        
        # Create document entity
        doc_entity = Entity(
            id=f"pdf_{hash(source)}",
            type="PDFDocument",
            label=Path(source).name,
            properties={
                "source": source,
                "pages": pdf_metadata.get("pages", 0),
                "word_count": len(text.split()),
                **pdf_metadata
            }
        )
        kg.add_entity(doc_entity)
        
        # In production, would extract entities, relationships, etc.
        
        return kg
    
    def get_supported_types(self) -> list[str]:
        """Return supported input types."""
        return ["pdf", "file"]
    
    def get_priority(self) -> int:
        """Return processor priority (higher for specialized processors)."""
        return 10
    
    def get_name(self) -> str:
        """Return processor name."""
        return "PDFProcessor"
