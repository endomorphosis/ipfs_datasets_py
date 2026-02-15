"""
BatchProcessorAdapter - Adapter for batch processing.

Wraps the existing BatchProcessor to implement ProcessorProtocol,
enabling batch/folder processing through UniversalProcessor.
"""

from __future__ import annotations

import logging
from typing import Union, List
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


class BatchProcessorAdapter:
    """
    Adapter for batch processing that implements ProcessorProtocol.
    
    Wraps the existing BatchProcessor to provide unified interface for
    processing folders and multiple files through UniversalProcessor.
    
    Example:
        >>> adapter = BatchProcessorAdapter()
        >>> can_process = await adapter.can_process("/path/to/folder")
        >>> result = await adapter.process("/path/to/folder")
    """
    
    def __init__(self, universal_processor=None):
        """
        Initialize batch processor adapter.
        
        Args:
            universal_processor: Optional UniversalProcessor instance for processing individual items.
                               If None, will be created on first use.
        """
        self._batch_processor = None
        self._universal_processor = universal_processor
    
    def _get_batch_processor(self):
        """Lazy-load batch processor on first use."""
        if self._batch_processor is None:
            try:
                from ..batch_processor import BatchProcessor
                self._batch_processor = BatchProcessor()
                logger.info("BatchProcessor loaded successfully")
            except ImportError as e:
                logger.warning(f"BatchProcessor not available: {e}")
        return self._batch_processor
    
    def _get_universal_processor(self):
        """Get or create UniversalProcessor for processing individual items."""
        if self._universal_processor is None:
            # Avoid circular import by importing here
            from ..universal_processor import UniversalProcessor
            self._universal_processor = UniversalProcessor()
            logger.info("UniversalProcessor created for batch processing")
        return self._universal_processor
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if this adapter can handle folder/batch inputs.
        
        Args:
            input_source: Input to check
            
        Returns:
            True if input is a directory or list of files
        """
        # Check if it's a directory
        path = Path(input_source)
        if path.exists() and path.is_dir():
            return True
        
        # Check if it's a pattern or glob (simple check)
        input_str = str(input_source)
        if '*' in input_str or '?' in input_str:
            return True
        
        return False
    
    async def process(
        self,
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process folder or multiple files and return aggregated result.
        
        Args:
            input_source: Folder path or file pattern
            **options: Processing options
            
        Returns:
            ProcessingResult with aggregated knowledge graph and statistics
        """
        start_time = time.time()
        
        metadata = ProcessingMetadata(
            processor_name="BatchProcessor",
            processor_version="1.0",
            input_type=InputType.FOLDER
        )
        
        try:
            path = Path(input_source)
            
            # Collect files to process
            if path.is_dir():
                # Get all files in directory (recursively or not based on options)
                recursive = options.get('recursive', False)
                if recursive:
                    files = list(path.rglob('*'))
                else:
                    files = list(path.glob('*'))
                files = [f for f in files if f.is_file()]
            else:
                # Handle glob pattern
                parent = path.parent
                pattern = path.name
                files = list(parent.glob(pattern))
            
            logger.info(f"Found {len(files)} files to process in batch")
            
            if not files:
                metadata.add_warning("No files found to process")
            
            # Process each file using UniversalProcessor
            universal = self._get_universal_processor()
            processed_results = []
            errors = []
            
            for file_path in files:
                try:
                    result = await universal.process(str(file_path), **options)
                    processed_results.append(result)
                except Exception as e:
                    logger.error(f"Failed to process {file_path}: {e}")
                    errors.append((str(file_path), str(e)))
                    metadata.add_error(f"Failed: {file_path.name} - {e}")
            
            # Aggregate results into single knowledge graph
            aggregated_kg = self._aggregate_knowledge_graphs(processed_results, str(input_source))
            
            # Aggregate vectors
            aggregated_vectors = self._aggregate_vectors(processed_results)
            
            # Calculate statistics
            total_files = len(files)
            successful = len(processed_results)
            failed = len(errors)
            
            # Processing time
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            
            if successful > 0:
                metadata.status = ProcessingStatus.SUCCESS if failed == 0 else ProcessingStatus.PARTIAL
            else:
                metadata.status = ProcessingStatus.FAILED
            
            return ProcessingResult(
                knowledge_graph=aggregated_kg,
                vectors=aggregated_vectors,
                content={
                    "total_files": total_files,
                    "successful": successful,
                    "failed": failed,
                    "errors": errors,
                    "folder_path": str(input_source)
                },
                metadata=metadata,
                extra={
                    "processor_type": "batch",
                    "success_rate": successful / total_files if total_files > 0 else 0.0,
                    "processed_files": [str(f) for f in files if f in [Path(r.content.get('source', '')) for r in processed_results]]
                }
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            metadata.processing_time_seconds = elapsed
            metadata.status = ProcessingStatus.FAILED
            metadata.add_error(str(e))
            
            logger.error(f"Batch processing failed for {input_source}: {e}")
            
            return ProcessingResult(
                knowledge_graph=KnowledgeGraph(source=str(input_source)),
                vectors=VectorStore(),
                content={"error": str(e)},
                metadata=metadata
            )
    
    def _aggregate_knowledge_graphs(
        self,
        results: List[ProcessingResult],
        source: str
    ) -> KnowledgeGraph:
        """
        Aggregate multiple knowledge graphs into one.
        
        Args:
            results: List of processing results
            source: Source folder path
            
        Returns:
            Aggregated knowledge graph
        """
        aggregated = KnowledgeGraph(source=source)
        
        # Create a folder entity
        folder_entity = Entity(
            id=f"folder_{hash(source)}",
            type="Folder",
            label=Path(source).name,
            properties={
                "path": source,
                "file_count": len(results)
            }
        )
        aggregated.add_entity(folder_entity)
        
        # Merge all entities and relationships from individual results
        entity_ids = set()
        for result in results:
            kg = result.knowledge_graph
            
            # Add entities (avoid duplicates by ID)
            for entity in kg.entities:
                if entity.id not in entity_ids:
                    aggregated.add_entity(entity)
                    entity_ids.add(entity.id)
                    
                    # Link entity to folder
                    aggregated.add_relationship(Relationship(
                        id=f"contains_{entity.id}",
                        source=folder_entity.id,
                        target=entity.id,
                        type="CONTAINS",
                        properties={}
                    ))
            
            # Add relationships
            for rel in kg.relationships:
                aggregated.add_relationship(rel)
        
        return aggregated
    
    def _aggregate_vectors(self, results: List[ProcessingResult]) -> VectorStore:
        """
        Aggregate vector embeddings from multiple results.
        
        Args:
            results: List of processing results
            
        Returns:
            Aggregated vector store
        """
        aggregated = VectorStore(
            metadata={
                "aggregated_from": len(results),
                "model": "batch_aggregation"
            }
        )
        
        # Merge all embeddings (with unique IDs)
        for i, result in enumerate(results):
            vectors = result.vectors
            for content_id, embedding in vectors.embeddings.items():
                # Prefix with result index to ensure uniqueness
                unique_id = f"result_{i}_{content_id}"
                if embedding is not None:
                    aggregated.add_embedding(unique_id, embedding)
        
        return aggregated
    
    def get_supported_types(self) -> list[str]:
        """Return supported input types."""
        return ["folder", "directory", "batch"]
    
    def get_priority(self) -> int:
        """Return processor priority (higher for specialized folder processing)."""
        return 15
    
    def get_name(self) -> str:
        """Return processor name."""
        return "BatchProcessor"
