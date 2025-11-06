"""Text chunking utilities for embeddings.

This module provides various text chunking strategies for preparing documents
for embedding operations, migrated and adapted from ipfs_embeddings_py.
"""

import bisect
import logging
import re
from typing import Callable, Dict, List, Optional, AsyncIterator, TypeAlias
from abc import ABC, abstractmethod


Tokenizer: TypeAlias = Callable[[str, Optional[Dict]], str]


from .schema import DocumentChunk, ChunkingStrategy, EmbeddingConfig

try:
    from transformers import AutoTokenizer
except ImportError:
    AutoTokenizer = None

try:
    from llama_index.core.schema import Document
    # from llama_index.embeddings.huggingface import HuggingFaceEmbedding FIXME This is hallucinated and will always be none
    from llama_index.core.node_parser import SemanticSplitterNodeParser
except ImportError:
    Document = None
    HuggingFaceEmbedding = None
    SemanticSplitterNodeParser = None

HuggingFaceEmbedding = None

try:
    import pysbd
except ImportError:
    pysbd = None

try:
    import torch
except ImportError:
    torch = None

# Set the logging level to WARNING to suppress INFO and DEBUG messages
logging.getLogger('sentence_transformers').setLevel(logging.WARNING)
logging.getLogger('transformers').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

CHUNKING_STRATEGIES = ['semantic', 'fixed', 'sentences', 'sliding_window']


class BaseChunker(ABC):
    """Base class for text chunking strategies."""
    
    def __init__(self, config: Optional[EmbeddingConfig] = None):
        self.config = config or EmbeddingConfig(model_name="default")
    
    @abstractmethod
    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text into DocumentChunk objects."""
        pass

    @abstractmethod
    async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
        """Async version of chunk_text."""
        pass


class FixedSizeChunker(BaseChunker):
    """Chunks text into fixed-size pieces with optional overlap."""
    
    def __init__(self, config: Optional[EmbeddingConfig] = None):
        super().__init__(config)
        self.chunk_size = self.config.chunk_size
        self.chunk_overlap = self.config.chunk_overlap
    
    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text into fixed-size pieces."""
        if not text.strip():
            return []
        
        chunks = []
        start = 0
        chunk_id = 0
        
        while start < len(text):
            end = start + self.chunk_size
            chunk_content = text[start:end]
            
            # Avoid cutting words in half (except for very long words)
            if end < len(text) and not text[end].isspace():
                # Find the last whitespace before the cut
                last_space = chunk_content.rfind(' ')
                if last_space > self.chunk_size * 0.7:  # Only adjust if we don't lose too much content
                    end = start + last_space
                    chunk_content = text[start:end]
            
            chunk = DocumentChunk(
                content=chunk_content.strip(),
                chunk_id=f"chunk_{chunk_id}",
                metadata=metadata or {},
                start_index=start,
                end_index=end
            )
            chunks.append(chunk)
            
            chunk_id += 1
            start = end - self.chunk_overlap
            
            # Prevent infinite loops
            if start >= end:
                start = end
        
        return chunks
    
    async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
        """Async version of fixed-size chunking."""
        chunks = self.chunk_text(text, metadata)
        for chunk in chunks:
            yield chunk


class SentenceChunker(BaseChunker):
    """Chunks text by sentences, grouping them to fit within size limits."""
    
    def __init__(self, config: Optional[EmbeddingConfig] = None):
        super().__init__(config)
        self.chunk_size = self.config.chunk_size
        self.sentence_splitter = self._initialize_sentence_splitter()
    
    def _initialize_sentence_splitter(self):
        """Initialize sentence splitter."""
        if pysbd is not None:
            return pysbd.Segmenter(language="en", clean=False)
        else:
            # Fallback to simple regex-based splitting
            return None
    
    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        if self.sentence_splitter is not None:
            return self.sentence_splitter.segment(text)
        else:
            # Simple fallback sentence splitting
            sentences = re.split(r'[.!?]+', text)
            return [s.strip() for s in sentences if s.strip()]
    
    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text by sentences."""
        if not text.strip():
            return []
        
        sentences = self._split_sentences(text)
        chunks = []
        current_chunk = []
        current_length = 0
        chunk_id = 0
        start_index = 0
        
        for sentence in sentences:
            sentence_length = len(sentence)
            
            # If adding this sentence would exceed chunk size, finalize current chunk
            if current_length + sentence_length > self.chunk_size and current_chunk:
                chunk_content = ' '.join(current_chunk)
                chunk = DocumentChunk(
                    content=chunk_content,
                    chunk_id=f"chunk_{chunk_id}",
                    metadata=metadata or {},
                    start_index=start_index,
                    end_index=start_index + len(chunk_content)
                )
                chunks.append(chunk)
                
                chunk_id += 1
                start_index += len(chunk_content)
                current_chunk = []
                current_length = 0
            
            current_chunk.append(sentence)
            current_length += sentence_length + 1  # +1 for space
        
        # Handle remaining content
        if current_chunk:
            chunk_content = ' '.join(current_chunk)
            chunk = DocumentChunk(
                content=chunk_content,
                chunk_id=f"chunk_{chunk_id}",
                metadata=metadata or {},
                start_index=start_index,
                end_index=start_index + len(chunk_content)
            )
            chunks.append(chunk)
        
        return chunks
    
    async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
        """Async version of sentence chunking."""
        chunks = self.chunk_text(text, metadata)
        for chunk in chunks:
            yield chunk


class SlidingWindowChunker(BaseChunker):
    """Chunks text using a sliding window approach."""
    
    def __init__(self, config: Optional[EmbeddingConfig] = None):
        super().__init__(config)
        self.chunk_size = self.config.chunk_size
        self.step_size = self.chunk_size - self.config.chunk_overlap
    
    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text using sliding window."""
        if not text.strip():
            return []
        
        chunks = []
        chunk_id = 0
        
        for start in range(0, len(text), self.step_size):
            end = min(start + self.chunk_size, len(text))
            chunk_content = text[start:end].strip()
            
            if chunk_content:  # Only add non-empty chunks
                chunk = DocumentChunk(
                    content=chunk_content,
                    chunk_id=f"chunk_{chunk_id}",
                    metadata=metadata or {},
                    start_index=start,
                    end_index=end
                )
                chunks.append(chunk)
                chunk_id += 1
            
            if end >= len(text):
                break
        
        return chunks
    
    async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
        """Async version of sliding window chunking."""
        chunks = self.chunk_text(text, metadata)
        for chunk in chunks:
            yield chunk


class SemanticChunker(BaseChunker):
    """Chunks text based on semantic similarity using embeddings."""
    
    def __init__(self, config: Optional[EmbeddingConfig] = None):
        super().__init__(config)
        self.embedding_model_name = self.config.model_name
        self.device = self.config.device
        self.batch_size = self.config.batch_size
        self.chunkers = {}
        self._setup_semantic_chunking()
    
    def _setup_semantic_chunking(self):
        """Setup semantic chunking with embedding model."""
        if SemanticSplitterNodeParser is None or HuggingFaceEmbedding is None:
            logger.warning("LlamaIndex components not available. Falling back to sentence chunking.")
            self.fallback_chunker = SentenceChunker(self.config)
            return
        
        try:
            if self.embedding_model_name not in self.chunkers:
                self.chunkers[self.embedding_model_name] = {}
            
            if self.device not in self.chunkers[self.embedding_model_name]:
                self.chunkers[self.embedding_model_name][self.device] = SemanticSplitterNodeParser(
                    embed_model=HuggingFaceEmbedding(
                        model_name=self.embedding_model_name,
                        trust_remote_code=True,
                        embed_batch_size=min(self.batch_size, 64),
                        device=self.device,
                    ),
                    show_progress=False,
                )
        except Exception as e:
            logger.error(f"Failed to setup semantic chunking: {e}")
            self.fallback_chunker = SentenceChunker(self.config)
    
    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text using semantic similarity."""
        if not text.strip():
            return []
        
        # Check if semantic chunking is available
        if (self.embedding_model_name not in self.chunkers or 
            self.device not in self.chunkers[self.embedding_model_name]):
            if hasattr(self, 'fallback_chunker'):
                logger.info("Using fallback sentence chunker for semantic chunking")
                return self.fallback_chunker.chunk_text(text, metadata)
            else:
                # Final fallback to fixed-size chunking
                fallback = FixedSizeChunker(self.config)
                return fallback.chunk_text(text, metadata)
        
        try:
            # Use LlamaIndex semantic splitter
            splitter = self.chunkers[self.embedding_model_name][self.device]
            
            # Create a document for the splitter
            if Document is not None:
                doc = Document(text=text, metadata=metadata or {})
                nodes = splitter.get_nodes_from_documents([doc])
                
                chunks = []
                for i, node in enumerate(nodes):
                    chunk = DocumentChunk(
                        content=node.text,
                        chunk_id=f"semantic_chunk_{i}",
                        metadata={**(metadata or {}), **node.metadata},
                        start_index=getattr(node, 'start_char_idx', None),
                        end_index=getattr(node, 'end_char_idx', None)
                    )
                    chunks.append(chunk)
                
                return chunks
            else:
                # Fallback if Document class not available
                if hasattr(self, 'fallback_chunker'):
                    return self.fallback_chunker.chunk_text(text, metadata)
                else:
                    fallback = SentenceChunker(self.config)
                    return fallback.chunk_text(text, metadata)
                
        except Exception as e:
            logger.error(f"Semantic chunking failed: {e}")
            if hasattr(self, 'fallback_chunker'):
                return self.fallback_chunker.chunk_text(text, metadata)
            else:
                fallback = SentenceChunker(self.config)
                return fallback.chunk_text(text, metadata)
    
    async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
        """Async version of semantic chunking."""
        chunks = self.chunk_text(text, metadata)
        for chunk in chunks:
            yield chunk

    async def delete_endpoint(self, model_name: str, endpoint: str):
        """Delete a model endpoint and free memory."""
        if model_name in self.chunkers and endpoint in self.chunkers[model_name]:
            del self.chunkers[model_name][endpoint]
            if torch is not None:
                with torch.no_grad():
                    torch.cuda.empty_cache()


class Chunker:
    """Main chunker class that delegates to specific chunking strategies."""
    
    def __init__(self, resources: Optional[Dict] = None, metadata: Optional[Dict] = None):
        if resources is None:
            resources = {}
        if metadata is None:  
            metadata = {}
        
        self.resources = resources
        self.metadata = metadata
        
        # Determine chunking strategy
        if "chunking_strategy" in metadata:
            chunking_strategy = metadata["chunking_strategy"]
        else:
            chunking_strategy = "semantic"
        
        if chunking_strategy not in CHUNKING_STRATEGIES:
            raise ValueError(f"Unsupported chunking strategy: {chunking_strategy}")
        
        self.chunking_strategy = chunking_strategy
        
        # Extract model information
        if "models" in metadata and len(metadata["models"]) > 0:
            self.embedding_model_name = metadata["models"][0]
        else:
            self.embedding_model_name = "sentence-transformers/all-MiniLM-L6-v2"
        
        # Create configuration
        self.config = EmbeddingConfig(
            model_name=self.embedding_model_name,
            chunking_strategy=ChunkingStrategy(chunking_strategy),
            chunk_size=metadata.get("chunk_size", 512),
            chunk_overlap=metadata.get("chunk_overlap", 50),
            batch_size=metadata.get("batch_size", 32),
            device=metadata.get("device", "cpu")
        )
        
        # Initialize the appropriate chunker
        self.chunker = self._create_chunker()
        
        # Legacy compatibility
        self.batch_size = self.config.batch_size
        self.device = self.config.device
        self.chunkers = {}
    
    def _create_chunker(self) -> BaseChunker:
        """Create the appropriate chunker based on strategy."""
        match self.chunking_strategy:
            case "semantic":
                return SemanticChunker(self.config)
            case "fixed":
                return FixedSizeChunker(self.config)
            case "sentences":
                return SentenceChunker(self.config)
            case "sliding_window":
                return SlidingWindowChunker(self.config)
            case _:
                raise ValueError(f"Unknown chunking strategy: {self.chunking_strategy}")
    
    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
        """Chunk text using the configured strategy."""
        return self.chunker.chunk_text(text, metadata)
    
    async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
        """Async version of text chunking."""
        async for chunk in self.chunker.chunk_text_async(text, metadata):
            yield chunk
    
    # Legacy methods for backward compatibility
    def chunk_semantically(self, text: str, tokenizer: Optional[Tokenizer] = None, **kwargs) -> List[DocumentChunk]:
        """Legacy method for semantic chunking."""
        return self.chunk_text(text)
    
    async def _setup_semantic_chunking(self, embedding_model_name: str, device: Optional[str] = None, 
                                     target_devices=None, embed_batch_size: Optional[int] = None):
        """Legacy method for setting up semantic chunking."""
        if isinstance(self.chunker, SemanticChunker):
            # Update configuration if needed
            if device:
                self.config.device = device
            if embed_batch_size:
                self.config.batch_size = embed_batch_size
            
            # Re-setup the chunker
            self.chunker._setup_semantic_chunking()
    
    async def delete_endpoint(self, model_name: str, endpoint: str):
        """Delete a model endpoint."""
        if isinstance(self.chunker, SemanticChunker):
            await self.chunker.delete_endpoint(model_name, endpoint)


# Legacy alias for backward compatibility
chunker = Chunker

# Export public interface
__all__ = [
    'BaseChunker',
    'FixedSizeChunker', 
    'SentenceChunker',
    'SlidingWindowChunker',
    'SemanticChunker',
    'Chunker',
    'chunker',
    'CHUNKING_STRATEGIES'
]
