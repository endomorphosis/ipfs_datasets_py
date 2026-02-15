"""
FileConverterProcessorAdapter - Adapter for file_converter module.

Wraps the existing FileConverter to implement ProcessorProtocol,
enabling it to work with UniversalProcessor.
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


class FileConverterProcessorAdapter:
    """
    Adapter for FileConverter that implements ProcessorProtocol.
    
    This adapter wraps the existing file_converter.FileConverter to provide
    a unified interface compatible with UniversalProcessor.
    
    Example:
        >>> adapter = FileConverterProcessorAdapter()
        >>> can_process = await adapter.can_process("document.docx")
        >>> result = await adapter.process("document.docx")
    """
    
    def __init__(self, backend: str = 'auto'):
        """
        Initialize adapter.
        
        Args:
            backend: FileConverter backend to use ('auto', 'native', etc.)
        """
        self.backend_name = backend
        self._converter = None
    
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
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if FileConverter can handle this input.
        
        FileConverter can handle most file types for conversion to text.
        """
        path = Path(input_source)
        
        # Check if it's a file (not URL, folder, etc.)
        if not path.exists() and not str(input_source).startswith(('http://', 'https://')):
            return False
        
        if path.exists() and path.is_dir():
            return False
        
        # FileConverter can handle many file types
        # It has built-in format detection
        return True
    
    async def process(
        self,
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process file using FileConverter and return standardized result.
        
        Args:
            input_source: File path or URL to process
            **options: FileConverter options
            
        Returns:
            ProcessingResult with extracted content and metadata
        """
        start_time = time.time()
        converter = self._get_converter()
        
        # Metadata for result
        metadata = ProcessingMetadata(
            processor_name="FileConverterProcessor",
            processor_version="1.0",
            input_type=InputType.FILE
        )
        
        try:
            # Convert file
            result = await converter.convert(input_source, **options)
            
            # Extract content
            text = result.text
            file_metadata = result.metadata
            
            # Build knowledge graph from extracted text
            kg = self._build_knowledge_graph(text, str(input_source), file_metadata)
            
            # Generate vector embeddings (simplified - in production, use real embeddings)
            vectors = self._generate_vectors(text, str(input_source))
            
            # Processing time
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.SUCCESS if result.success else ProcessingStatus.PARTIAL
            
            if result.error:
                metadata.add_error(result.error)
            
            # Create result
            return ProcessingResult(
                knowledge_graph=kg,
                vectors=vectors,
                content={
                    "text": text,
                    "metadata": file_metadata,
                    "backend": result.backend
                },
                metadata=metadata,
                extra={
                    "conversion_backend": result.backend,
                    "original_format": file_metadata.get("format", "unknown")
                }
            )
        
        except Exception as e:
            # Handle errors
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.FAILED
            metadata.add_error(str(e))
            
            logger.error(f"FileConverter failed for {input_source}: {e}")
            
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
        file_metadata: dict
    ) -> KnowledgeGraph:
        """
        Build a basic knowledge graph from extracted text.
        
        In production, this would use NLP/NER to extract entities and relationships.
        For now, we create a simple document-level node.
        """
        kg = KnowledgeGraph(source=source)
        
        # Create document entity
        doc_entity = Entity(
            id=f"doc_{hash(source)}",
            type="Document",
            label=file_metadata.get("title", Path(source).name),
            properties={
                "source": source,
                "format": file_metadata.get("format", "unknown"),
                "word_count": len(text.split()),
                "char_count": len(text),
                **file_metadata
            }
        )
        kg.add_entity(doc_entity)
        
        # In production, we would:
        # 1. Run NER to extract entities (Person, Organization, Location, etc.)
        # 2. Extract relationships between entities
        # 3. Link entities to the document
        # 4. Build a comprehensive graph
        
        # For now, add some basic metadata entities
        if "author" in file_metadata:
            author_entity = Entity(
                id=f"author_{hash(file_metadata['author'])}",
                type="Person",
                label=file_metadata["author"],
                properties={"role": "author"}
            )
            kg.add_entity(author_entity)
            
            # Create authorship relationship
            kg.add_relationship(Relationship(
                id=f"authored_{hash(source)}",
                source=author_entity.id,
                target=doc_entity.id,
                type="AUTHORED",
                properties={}
            ))
        
        return kg
    
    def _generate_vectors(self, text: str, source: str) -> VectorStore:
        """
        Generate vector embeddings for text.
        
        In production, this would use a real embedding model.
        For now, we create a placeholder VectorStore.
        """
        vectors = VectorStore(
            metadata={
                "model": "placeholder",
                "source": source
            }
        )
        
        # In production:
        # 1. Chunk text into segments
        # 2. Generate embeddings using transformer model
        # 3. Store embeddings with content IDs
        # vectors.add_embedding("chunk_0", embedding_array)
        
        return vectors
    
    def get_supported_types(self) -> list[str]:
        """Return supported input types."""
        return [
            "file",
            "pdf",
            "document",
            "spreadsheet",
            "presentation",
            "text",
            "html",
            "image"
        ]
    
    def get_priority(self) -> int:
        """Return processor priority (lower than specialized processors)."""
        return 5
    
    def get_name(self) -> str:
        """Return processor name."""
        return "FileConverterProcessor"
