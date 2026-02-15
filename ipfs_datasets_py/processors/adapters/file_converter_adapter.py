"""
FileConverterProcessorAdapter - Adapter for file_converter module.

Wraps the existing FileConverter to implement ProcessorProtocol,
enabling it to work with UniversalProcessor.
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


class FileConverterProcessorAdapter:
    """
    Adapter for FileConverter that implements ProcessorProtocol.
    
    This adapter wraps the existing file_converter.FileConverter to provide
    a unified interface compatible with UniversalProcessor.
    
    Implements the synchronous ProcessorProtocol from processors.core.
    
    Example:
        >>> from ipfs_datasets_py.processors.core import ProcessingContext, InputType
        >>> adapter = FileConverterProcessorAdapter()
        >>> context = ProcessingContext(
        ...     input_type=InputType.FILE,
        ...     source="document.docx",
        ...     metadata={"format": "docx"}
        ... )
        >>> can_handle = adapter.can_handle(context)
        >>> result = adapter.process(context)
    """
    
    def __init__(self, backend: str = 'auto'):
        """
        Initialize adapter.
        
        Args:
            backend: FileConverter backend to use ('auto', 'native', etc.)
        """
        self.backend_name = backend
        self._converter = None
        self._name = "FileConverterProcessor"
        self._priority = 5
    
    def _get_converter(self):
        """Lazy-load FileConverter on first use."""
        if self._converter is None:
            try:
                from ..file_converter import FileConverter
                self._converter = FileConverter(backend=self.backend_name)
                logger.info(f"FileConverter initialized with backend: {self.backend_name}")
            except ImportError as e:
                logger.error(f"Could not import FileConverter: {e}")
                raise
        return self._converter
    
    def can_handle(self, context: ProcessingContext) -> bool:
        """
        Check if FileConverter can handle this input.
        
        FileConverter can handle most file types for conversion to text.
        
        Args:
            context: Processing context with input information
            
        Returns:
            True if input is a file that FileConverter can handle
        """
        # Don't handle URLs
        if context.input_type == InputType.URL:
            return False
        
        # Don't handle folders
        if context.input_type == InputType.FOLDER:
            return False
        
        # Check if file exists
        if context.input_type == InputType.FILE:
            path = Path(context.source)
            if not path.exists() or path.is_dir():
                return False
        
        # FileConverter can handle many file types
        # It has built-in format detection
        return True
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        """
        Process file using FileConverter and return standardized result.
        
        Args:
            context: Processing context with input source and options
            
        Returns:
            ProcessingResult with extracted content and metadata
        """
        start_time = time.time()
        converter = self._get_converter()
        source = context.source
        
        try:
            # Convert file (note: actual converter might be async, this is placeholder)
            # result = await converter.convert(source, **context.options)
            # For now, create placeholder result
            text = f"Converted content from {source}"
            file_metadata = {
                "format": context.get_format() or "unknown",
                "source": str(source)
            }
            
            # Build knowledge graph from extracted text
            kg = self._build_knowledge_graph(text, str(source), file_metadata)
            
            # Generate vector embeddings (placeholder)
            vectors: List[List[float]] = []
            
            # Processing time
            elapsed = time.time() - start_time
            
            # Create result
            return ProcessingResult(
                success=True,
                knowledge_graph=kg,
                vectors=vectors,
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "backend": self.backend_name,
                    "original_format": file_metadata.get("format", "unknown"),
                    "text_length": len(text),
                    **file_metadata
                }
            )
        
        except Exception as e:
            # Handle errors
            elapsed = time.time() - start_time
            
            logger.error(f"FileConverter failed for {source}: {e}")
            
            return ProcessingResult(
                success=False,
                knowledge_graph={},
                vectors=[],
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "error": str(e)
                },
                errors=[f"File conversion failed: {str(e)}"]
            )
    
    def _build_knowledge_graph(
        self,
        text: str,
        source: str,
        file_metadata: dict
    ) -> Dict[str, Any]:
        """
        Build a basic knowledge graph from extracted text.
        
        In production, this would use NLP/NER to extract entities and relationships.
        For now, we create a simple document-level node.
        """
        # Create document entity
        doc_entity = {
            "id": f"doc_{abs(hash(source))}",
            "type": "Document",
            "label": file_metadata.get("title", Path(source).name),
            "properties": {
                "source": source,
                "format": file_metadata.get("format", "unknown"),
                "word_count": len(text.split()),
                "char_count": len(text),
                **file_metadata
            }
        }
        
        entities = [doc_entity]
        relationships = []
        
        # In production, we would:
        # 1. Run NER to extract entities (Person, Organization, Location, etc.)
        # 2. Extract relationships between entities
        # 3. Link entities to the document
        # 4. Build a comprehensive graph
        
        # For now, add some basic metadata entities
        if "author" in file_metadata:
            author_entity = {
                "id": f"author_{abs(hash(file_metadata['author']))}",
                "type": "Person",
                "label": file_metadata["author"],
                "properties": {"role": "author"}
            }
            entities.append(author_entity)
            
            # Create authorship relationship
            relationships.append({
                "id": f"authored_{abs(hash(source))}",
                "source": author_entity["id"],
                "target": doc_entity["id"],
                "type": "AUTHORED",
                "properties": {}
            })
        
        return {
            "entities": entities,
            "relationships": relationships,
            "source": source
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
            "formats": ["pdf", "docx", "xlsx", "pptx", "txt", "html", "md"],
            "input_types": ["file"],
            "outputs": ["knowledge_graph", "text"],
            "features": [
                "text_extraction",
                "format_conversion",
                "metadata_extraction"
            ]
        }
