"""Streaming entity extraction for incremental processing of large documents.

This module provides a streaming interface for entity extraction that processes
large documents incrementally, yielding results as they're found. Useful for:
- Processing unbounded text streams
- Applying backpressure to avoid memory overload
- Real-time entity discovery with progress callbacks
- Integration with streaming pipelines (Kafka, message queues, etc.)

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag.streaming_extractor import StreamingEntityExtractor
    >>> extractor = StreamingEntityExtractor(backend=backend, chunk_size=1024)
    >>> 
    >>> for entity_batch in extractor.extract_stream(large_text):
    ...     process_batch(entity_batch)
    ...     print(f"Extracted {len(entity_batch)} entities")
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterator, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ChunkStrategy(Enum):
    """Strategy for chunking input text."""
    FIXED_SIZE = "fixed_size"  # Fixed number of characters
    SENTENCE = "sentence"  # By sentences (requires NLP)
    PARAGRAPH = "paragraph"  # By paragraphs (double newlines)
    ADAPTIVE = "adaptive"  # Adaptive based on entity density


@dataclass
class StreamingEntity:
    """A single entity extracted from the stream."""
    entity_id: str
    entity_type: str
    text: str
    start_pos: int  # Position in original text
    end_pos: int
    confidence: float
    metadata: dict = field(default_factory=dict)


@dataclass
class EntityBatch:
    """Batch of entities extracted from a chunk."""
    entities: List[StreamingEntity]
    chunk_id: int
    chunk_start_pos: int
    chunk_end_pos: int
    chunk_text: str
    processing_time_ms: float
    is_final: bool = False  # True if this is the last batch


class StreamingEntityExtractor:
    """Streaming entity extractor for incremental document processing.
    
    Processes documents in chunks using a configurable strategy, extracting
    entities incrementally and yielding batches as they're found. Supports:
    - Multiple chunking strategies
    - Progress callbacks
    - Backpressure control
    - Context preservation across chunks
    
    Attributes:
        chunk_size: Size of each chunk (strategy-dependent)
        chunk_strategy: How to split text into chunks
        overlap: Number of overlapping characters between chunks (cross-chunk validation)
        extractor_func: Callable that extracts entities from text chunk
    """
    
    def __init__(
        self,
        extractor_func: Callable[[str], List[dict]],
        chunk_size: int = 1024,
        chunk_strategy: ChunkStrategy = ChunkStrategy.FIXED_SIZE,
        overlap: int = 256,
        batch_size: int = 32,
    ):
        """Initialize streaming entity extractor.
        
        Args:
            extractor_func: Callable that takes text and returns list of entity dicts
            chunk_size: Size of each chunk (character count for FIXED_SIZE strategy)
            chunk_strategy: How to partition the input text
            overlap: Number of overlapping characters between chunks for context
            batch_size: Accumulate this many entities before yielding batch
        """
        self.extractor_func = extractor_func
        self.chunk_size = chunk_size
        self.chunk_strategy = chunk_strategy
        self.overlap = min(overlap, chunk_size - 1)  # Ensure overlap < chunk_size
        self.batch_size = batch_size
        self._log = logging.getLogger(__name__)
    
    def extract_stream(
        self,
        text: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Iterator[EntityBatch]:
        """Extract entities from text as a stream.
        
        Yields batches of entities as they're discovered. Each batch contains
        entities from a chunk plus accumulated overflow from previous chunks.
        
        Args:
            text: Full text to process
            progress_callback: Optional callback(chars_processed) called after each chunk
            
        Yields:
            EntityBatch objects containing extracted entities
        """
        import time
        
        chunks = self._chunk_text(text)
        accumulated_entities = []
        global_entity_id_counter = 0
        
        for chunk_id, (chunk_start, chunk_end) in enumerate(chunks):
            chunk_start_time = time.time()
            chunk_text = text[chunk_start:chunk_end]
            
            try:
                # Extract entities from this chunk
                raw_entities = self.extractor_func(chunk_text)
                
                # Normalize to StreamingEntity objects with absolute positions
                chunk_entities = []
                for entity in raw_entities:
                    streaming_entity = StreamingEntity(
                        entity_id=f"entity_{global_entity_id_counter}",
                        entity_type=entity.get("type", "UNKNOWN"),
                        text=entity.get("text", entity.get("value", "")),
                        start_pos=chunk_start + entity.get("start", 0),
                        end_pos=chunk_start + entity.get("end", len(chunk_text)),
                        confidence=entity.get("confidence", 0.5),
                        metadata=entity.get("metadata", {}),
                    )
                    chunk_entities.append(streaming_entity)
                    global_entity_id_counter += 1
                
                # Append to accumulated entities
                accumulated_entities.extend(chunk_entities)
                
                # Yield batch if we've accumulated enough
                processing_time_ms = (time.time() - chunk_start_time) * 1000.0
                is_final = (chunk_id == len(chunks) - 1)
                
                if len(accumulated_entities) >= self.batch_size or is_final:
                    batch = EntityBatch(
                        entities=accumulated_entities[:self.batch_size],
                        chunk_id=chunk_id,
                        chunk_start_pos=chunk_start,
                        chunk_end_pos=chunk_end,
                        chunk_text=chunk_text,
                        processing_time_ms=processing_time_ms,
                        is_final=is_final,
                    )
                    yield batch
                    
                    # Retain overflow for next batch
                    accumulated_entities = accumulated_entities[self.batch_size:]
                
                # Call progress callback
                if progress_callback:
                    progress_callback(chunk_end)
                
                self._log.debug(
                    f"Processed chunk {chunk_id}: {len(chunk_entities)} entities, "
                    f"{processing_time_ms:.2f}ms"
                )
                
            except Exception as e:
                self._log.error(
                    f"Error processing chunk {chunk_id} [{chunk_start}:{chunk_end}]: {e}"
                )
                raise
        
        # Yield remaining entities
        if accumulated_entities:
            batch = EntityBatch(
                entities=accumulated_entities,
                chunk_id=len(chunks),
                chunk_start_pos=text.rfind('\n', 0, -1000),  # Approximate
                chunk_end_pos=len(text),
                chunk_text=text[-self.chunk_size:],  # Last chunk
                processing_time_ms=0.0,
                is_final=True,
            )
            yield batch
    
    def _chunk_text(self, text: str) -> List[tuple]:
        """Split text into (start, end) position pairs.
        
        Args:
            text: Text to chunk
            
        Returns:
            List of (start_pos, end_pos) tuples
        """
        if self.chunk_strategy == ChunkStrategy.FIXED_SIZE:
            return self._chunk_fixed_size(text)
        elif self.chunk_strategy == ChunkStrategy.PARAGRAPH:
            return self._chunk_by_paragraph(text)
        elif self.chunk_strategy == ChunkStrategy.SENTENCE:
            return self._chunk_by_sentence(text)
        else:  # ADAPTIVE
            return self._chunk_adaptive(text)
    
    def _chunk_fixed_size(self, text: str) -> List[tuple]:
        """Chunk text into fixed-size chunks with overlap."""
        chunks = []
        pos = 0
        
        while pos < len(text):
            chunk_start = max(0, pos - self.overlap)
            chunk_end = min(len(text), pos + self.chunk_size)
            chunks.append((chunk_start, chunk_end))
            pos = chunk_end
        
        return chunks
    
    def _chunk_by_paragraph(self, text: str) -> List[tuple]:
        """Chunk text by paragraphs (double newlines)."""
        chunks = []
        paragraphs = text.split('\n\n')
        pos = 0
        
        for para in paragraphs:
            start = pos
            end = pos + len(para) + 2  # Include newlines
            chunks.append((start, min(end, len(text))))
            pos = end
        
        return chunks if chunks else [(0, len(text))]
    
    def _chunk_by_sentence(self, text: str) -> List[tuple]:
        """Chunk text by sentences (simple heuristic)."""
        # Simple regex-based approach (not dependency-heavy)
        import re
        
        chunks = []
        sentences = re.split(r'(?<=[.!?])\s+', text)
        pos = 0
        
        for sentence in sentences:
            start = pos
            end = pos + len(sentence) + 1
            chunks.append((start, min(end, len(text))))
            pos = end
        
        return chunks if chunks else [(0, len(text))]
    
    def _chunk_adaptive(self, text: str) -> List[tuple]:
        """Adaptively chunk based on entity density (fallback to fixed for now)."""
        # Simplified adaptive: use fixed-size for now
        # In production, could track entity density and adjust chunk size
        return self._chunk_fixed_size(text)
    
    def __repr__(self) -> str:
        """String representation."""
        return (
            f"StreamingEntityExtractor(chunk_size={self.chunk_size}, "
            f"strategy={self.chunk_strategy.value}, overlap={self.overlap})"
        )
