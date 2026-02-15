"""
BatchProcessorAdapter - Adapter for batch processing.

Wraps the existing BatchProcessor to implement ProcessorProtocol,
enabling batch/folder processing through UniversalProcessor.
"""

from __future__ import annotations

import logging
from typing import Union, List, Dict, Any
from pathlib import Path
import time

from ..core.protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
)

logger = logging.getLogger(__name__)


class BatchProcessorAdapter:
    """
    Adapter for batch processing that implements ProcessorProtocol.
    
    Wraps the existing BatchProcessor to provide unified interface for
    processing folders and multiple files through UniversalProcessor.
    
    Implements the synchronous ProcessorProtocol from processors.core.
    
    Example:
        >>> from ipfs_datasets_py.processors.core import ProcessingContext, InputType
        >>> adapter = BatchProcessorAdapter()
        >>> context = ProcessingContext(
        ...     input_type=InputType.FOLDER,
        ...     source="/path/to/folder",
        ...     metadata={}
        ... )
        >>> can_handle = adapter.can_handle(context)
        >>> result = adapter.process(context)
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
        self._name = "BatchProcessor"
        self._priority = 15
    
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
    
    def can_handle(self, context: ProcessingContext) -> bool:
        """
        Check if this adapter can handle folder/batch inputs.
        
        Args:
            context: Processing context with input information
            
        Returns:
            True if input is a directory or list of files
        """
        # Check if it's a folder input type
        if context.input_type == InputType.FOLDER:
            return True
        
        # Check if it's a directory
        if context.input_type == InputType.FILE:
            path = Path(context.source)
            if path.exists() and path.is_dir():
                return True
        
        # Check if it's a pattern or glob (simple check)
        source_str = str(context.source)
        if '*' in source_str or '?' in source_str:
            return True
        
        return False
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        """
        Process folder or multiple files and return aggregated result.
        
        Args:
            context: Processing context with input source and options
            
        Returns:
            ProcessingResult with aggregated knowledge graph and statistics
        """
        start_time = time.time()
        source = context.source
        
        try:
            path = Path(source)
            
            # Collect files to process
            if path.is_dir():
                # Get all files in directory (recursively or not based on options)
                recursive = context.options.get('recursive', False)
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
            
            warnings = []
            if not files:
                warnings.append("No files found to process")
            
            # Process each file using UniversalProcessor
            # Note: In sync version, we can't await, so this is placeholder
            # Real implementation would need to call processor.process() synchronously
            processed_results = []
            errors = []
            
            for file_path in files:
                try:
                    # Placeholder - in real implementation, would process each file
                    # result = universal.process(str(file_path), **context.options)
                    # processed_results.append(result)
                    logger.debug(f"Would process: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to process {file_path}: {e}")
                    errors.append((str(file_path), str(e)))
            
            # Aggregate results into single knowledge graph
            aggregated_kg = self._aggregate_knowledge_graphs(processed_results, str(source))
            
            # Aggregate vectors
            aggregated_vectors: List[List[float]] = []
            
            # Calculate statistics
            total_files = len(files)
            successful = len(processed_results)
            failed = len(errors)
            
            # Processing time
            elapsed = time.time() - start_time
            
            return ProcessingResult(
                success=(successful > 0 or total_files == 0),
                knowledge_graph=aggregated_kg,
                vectors=aggregated_vectors,
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "total_files": total_files,
                    "successful": successful,
                    "failed": failed,
                    "folder_path": str(source)
                },
                warnings=warnings,
                errors=[f"Failed: {f} - {e}" for f, e in errors]
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            
            logger.error(f"Batch processing failed for {source}: {e}")
            
            return ProcessingResult(
                success=False,
                knowledge_graph={},
                vectors=[],
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "error": str(e)
                },
                errors=[f"Batch processing failed: {str(e)}"]
            )
    
    def _aggregate_knowledge_graphs(
        self,
        results: List[ProcessingResult],
        source: str
    ) -> Dict[str, Any]:
        """
        Aggregate multiple knowledge graphs into one.
        
        Args:
            results: List of processing results
            source: Source folder path
            
        Returns:
            Aggregated knowledge graph
        """
        # Create a folder entity
        folder_entity = {
            "id": f"folder_{abs(hash(source))}",
            "type": "Folder",
            "label": Path(source).name,
            "properties": {
                "path": source,
                "file_count": len(results)
            }
        }
        
        entities = [folder_entity]
        relationships = []
        
        # Merge all entities and relationships from individual results
        entity_ids = set()
        entity_ids.add(folder_entity["id"])
        
        for result in results:
            kg = result.knowledge_graph
            
            # Add entities (avoid duplicates by ID)
            for entity in kg.get("entities", []):
                if entity["id"] not in entity_ids:
                    entities.append(entity)
                    entity_ids.add(entity["id"])
                    
                    # Link entity to folder
                    relationships.append({
                        "id": f"contains_{entity['id']}",
                        "source": folder_entity["id"],
                        "target": entity["id"],
                        "type": "CONTAINS",
                        "properties": {}
                    })
            
            # Add relationships
            for rel in kg.get("relationships", []):
                relationships.append(rel)
        
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
            "formats": ["*"],  # Handles all formats via delegation
            "input_types": ["folder", "directory", "batch"],
            "outputs": ["knowledge_graph", "aggregated_results"],
            "features": [
                "batch_processing",
                "folder_processing",
                "recursive_processing",
                "result_aggregation"
            ]
        }
