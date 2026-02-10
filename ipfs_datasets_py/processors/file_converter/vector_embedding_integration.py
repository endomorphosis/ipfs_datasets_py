"""
Vector Embedding Integration for File Converter

Connects the file_converter module with the existing embeddings infrastructure to enable:
- Text extraction from any file format
- Text chunking for embeddings
- Vector embedding generation with multiple models
- Storage in vector stores (FAISS, Qdrant, Elasticsearch)
- Semantic search capabilities
- IPFS storage integration
- ML acceleration support

This module provides a complete pipeline from arbitrary files to searchable vector embeddings.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field

try:
    import anyio
    import numpy as np
    ANYIO_AVAILABLE = True
except ImportError:
    ANYIO_AVAILABLE = False
    np = None

# File converter imports
from .converter import FileConverter, ConversionResult
from .ipfs_accelerate_converter import IPFSAcceleratedConverter, IPFSConversionResult
from .batch_processor import BatchProcessor, ResourceLimits
from .metadata_extractor import extract_metadata

# Embeddings infrastructure imports
try:
    from ..embeddings.core import IPFSEmbeddings, EmbeddingConfig
    from ..embeddings.chunker import (
        Chunker,
        ChunkingStrategy,
        CHUNKING_STRATEGIES
    )
    from ..embeddings.schema import DocumentChunk
    HAVE_EMBEDDINGS = True
except ImportError:
    HAVE_EMBEDDINGS = False
    IPFSEmbeddings = None
    EmbeddingConfig = None
    Chunker = None
    ChunkingStrategy = None
    DocumentChunk = None

# Vector store imports
try:
    from ..vector_stores.faiss_store import FAISSVectorStore
    HAVE_FAISS = True
except ImportError:
    HAVE_FAISS = False
    FAISSVectorStore = None

try:
    from ..vector_stores.qdrant_store import QdrantVectorStore
    HAVE_QDRANT = True
except ImportError:
    HAVE_QDRANT = False
    QdrantVectorStore = None

try:
    from ..vector_stores.elasticsearch_store import ElasticsearchVectorStore
    HAVE_ELASTICSEARCH = True
except ImportError:
    HAVE_ELASTICSEARCH = False
    ElasticsearchVectorStore = None

logger = logging.getLogger(__name__)


@dataclass
class VectorEmbeddingResult:
    """Result from vector embedding generation."""
    
    file_path: str
    text: str
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    embeddings: Optional[List[np.ndarray]] = None
    embedding_metadata: Dict[str, Any] = field(default_factory=dict)
    vector_store_ids: List[str] = field(default_factory=list)
    ipfs_cid: Optional[str] = None
    ipfs_embedding_cid: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    
    def __post_init__(self):
        """Convert embeddings to numpy arrays if needed."""
        if self.embeddings and not isinstance(self.embeddings, list):
            self.embeddings = [self.embeddings]


@dataclass
class SearchResult:
    """Result from semantic search."""
    
    text: str
    score: float
    chunk_index: int
    file_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class VectorEmbeddingPipeline:
    """
    Complete pipeline for generating vector embeddings from any file format.
    
    Pipeline:
    1. File → Text (via FileConverter)
    2. Text → Chunks (via Chunker)
    3. Chunks → Embeddings (via IPFSEmbeddings)
    4. Store embeddings (FAISS/Qdrant/Elasticsearch)
    5. Optional IPFS storage
    
    Usage:
        pipeline = VectorEmbeddingPipeline(
            embedding_model='sentence-transformers/all-MiniLM-L6-v2',
            vector_store='faiss',
            enable_ipfs=True
        )
        result = await pipeline.process('document.pdf')
        
        # Search
        results = await pipeline.search('query text', top_k=5)
    """
    
    def __init__(
        self,
        backend: str = 'native',
        embedding_model: str = 'sentence-transformers/all-MiniLM-L6-v2',
        chunking_strategy: str = 'fixed',
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        vector_store: str = 'faiss',
        vector_store_path: Optional[str] = None,
        enable_ipfs: bool = False,
        enable_acceleration: bool = False,
        device: str = 'auto'
    ):
        """
        Initialize the vector embedding pipeline.
        
        Args:
            backend: FileConverter backend ('native', 'auto')
            embedding_model: Model for embeddings (HuggingFace model name)
            chunking_strategy: Strategy for text chunking ('fixed', 'semantic', 'sentences')
            chunk_size: Size of text chunks
            chunk_overlap: Overlap between chunks
            vector_store: Vector store type ('faiss', 'qdrant', 'elasticsearch')
            vector_store_path: Path to store vector index
            enable_ipfs: Enable IPFS storage
            enable_acceleration: Enable ML acceleration
            device: Device for embeddings ('auto', 'cuda', 'cpu')
        """
        if not HAVE_EMBEDDINGS:
            raise ImportError("Embeddings module not available. Install required dependencies.")
        
        self.backend = backend
        self.embedding_model = embedding_model
        self.chunking_strategy = chunking_strategy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.vector_store_type = vector_store
        self.vector_store_path = vector_store_path or f"./vector_store_{vector_store}"
        self.enable_ipfs = enable_ipfs
        self.enable_acceleration = enable_acceleration
        self.device = device
        
        # Initialize file converter
        if enable_ipfs or enable_acceleration:
            self.converter = IPFSAcceleratedConverter(
                backend=backend,
                enable_ipfs=enable_ipfs,
                enable_acceleration=enable_acceleration
            )
        else:
            self.converter = FileConverter(backend=backend)
        
        # Initialize embeddings config
        self.embedding_config = EmbeddingConfig(
            model_name=embedding_model,
            device=device,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunking_strategy=chunking_strategy
        )
        
        # Initialize embeddings engine (lazy)
        self._embeddings_engine = None
        
        # Initialize chunker (lazy)
        self._chunker = None
        
        # Initialize vector store (lazy)
        self._vector_store = None
        
        # Track documents
        self.document_registry: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"Initialized VectorEmbeddingPipeline with {embedding_model} and {vector_store}")
    
    @property
    def embeddings_engine(self):
        """Lazy-load embeddings engine."""
        if self._embeddings_engine is None:
            self._embeddings_engine = IPFSEmbeddings(
                resources={},
                metadata={"model": self.embedding_model}
            )
        return self._embeddings_engine
    
    @property
    def chunker(self):
        """Lazy-load text chunker."""
        if self._chunker is None:
            self._chunker = Chunker(config=self.embedding_config)
        return self._chunker
    
    @property
    def vector_store(self):
        """Lazy-load vector store."""
        if self._vector_store is None:
            self._vector_store = self._initialize_vector_store()
        return self._vector_store
    
    def _initialize_vector_store(self):
        """Initialize the appropriate vector store."""
        if self.vector_store_type == 'faiss' and HAVE_FAISS:
            return FAISSVectorStore(
                dimension=384,  # Default for all-MiniLM-L6-v2
                index_path=self.vector_store_path
            )
        elif self.vector_store_type == 'qdrant' and HAVE_QDRANT:
            return QdrantVectorStore(
                collection_name="file_converter_embeddings",
                dimension=384
            )
        elif self.vector_store_type == 'elasticsearch' and HAVE_ELASTICSEARCH:
            return ElasticsearchVectorStore(
                index_name="file_converter_embeddings",
                dimension=384
            )
        else:
            logger.warning(f"Vector store '{self.vector_store_type}' not available. Using FAISS fallback.")
            if HAVE_FAISS:
                return FAISSVectorStore(
                    dimension=384,
                    index_path=self.vector_store_path
                )
            else:
                raise ImportError(f"No vector store available. Install faiss, qdrant, or elasticsearch.")
    
    async def process(
        self,
        file_path: Union[str, Path],
        store_embeddings: bool = True,
        store_on_ipfs: bool = None
    ) -> VectorEmbeddingResult:
        """
        Process a file to generate vector embeddings.
        
        Args:
            file_path: Path to file to process
            store_embeddings: Store embeddings in vector store
            store_on_ipfs: Store on IPFS (uses enable_ipfs if None)
        
        Returns:
            VectorEmbeddingResult with embeddings and metadata
        """
        if not ANYIO_AVAILABLE:
            raise ImportError("anyio is required for async operations")
        
        file_path = str(file_path)
        store_on_ipfs = store_on_ipfs if store_on_ipfs is not None else self.enable_ipfs
        
        try:
            # Step 1: Convert file to text
            logger.info(f"Processing file: {file_path}")
            if isinstance(self.converter, IPFSAcceleratedConverter):
                conversion_result = await self.converter.convert(
                    file_path,
                    store_on_ipfs=store_on_ipfs
                )
                text = conversion_result.text
                ipfs_cid = getattr(conversion_result, 'ipfs_cid', None)
            else:
                conversion_result = await self.converter.convert(file_path)
                text = conversion_result.text
                ipfs_cid = None
            
            if not text or not text.strip():
                return VectorEmbeddingResult(
                    file_path=file_path,
                    text="",
                    success=False,
                    error="No text extracted from file"
                )
            
            # Step 2: Chunk text
            logger.info(f"Chunking text ({len(text)} characters)")
            chunks = await anyio.to_thread.run_sync(
                self.chunker.chunk_text,
                text,
                {"file_path": file_path}
            )
            
            if not chunks:
                return VectorEmbeddingResult(
                    file_path=file_path,
                    text=text,
                    success=False,
                    error="No chunks generated from text"
                )
            
            # Step 3: Generate embeddings
            logger.info(f"Generating embeddings for {len(chunks)} chunks")
            chunk_texts = [chunk.text for chunk in chunks]
            
            embeddings = await self.embeddings_engine.generate_embeddings(
                texts=chunk_texts,
                config=self.embedding_config
            )
            
            if embeddings is None or len(embeddings) == 0:
                return VectorEmbeddingResult(
                    file_path=file_path,
                    text=text,
                    chunks=[{"text": c.text, "metadata": c.metadata} for c in chunks],
                    success=False,
                    error="Failed to generate embeddings"
                )
            
            # Step 4: Store embeddings in vector store
            vector_store_ids = []
            if store_embeddings and self.vector_store:
                logger.info(f"Storing {len(embeddings)} embeddings in {self.vector_store_type}")
                for i, (embedding, chunk) in enumerate(zip(embeddings, chunks)):
                    metadata = {
                        "file_path": file_path,
                        "chunk_index": i,
                        "text": chunk.text,
                        "chunk_metadata": chunk.metadata
                    }
                    if ipfs_cid:
                        metadata["ipfs_cid"] = ipfs_cid
                    
                    doc_id = await anyio.to_thread.run_sync(
                        self.vector_store.add_vector,
                        embedding,
                        metadata
                    )
                    vector_store_ids.append(doc_id)
            
            # Step 5: Optional IPFS storage for embeddings
            ipfs_embedding_cid = None
            if store_on_ipfs and ipfs_cid:
                # TODO: Store embeddings on IPFS
                logger.info("IPFS embedding storage not yet implemented")
            
            # Register document
            self.document_registry[file_path] = {
                "num_chunks": len(chunks),
                "num_embeddings": len(embeddings),
                "ipfs_cid": ipfs_cid,
                "vector_store_ids": vector_store_ids
            }
            
            return VectorEmbeddingResult(
                file_path=file_path,
                text=text,
                chunks=[{"text": c.text, "metadata": c.metadata} for c in chunks],
                embeddings=embeddings,
                embedding_metadata={
                    "model": self.embedding_model,
                    "num_chunks": len(chunks),
                    "chunk_strategy": self.chunking_strategy
                },
                vector_store_ids=vector_store_ids,
                ipfs_cid=ipfs_cid,
                ipfs_embedding_cid=ipfs_embedding_cid,
                success=True
            )
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}", exc_info=True)
            return VectorEmbeddingResult(
                file_path=file_path,
                text="",
                success=False,
                error=str(e)
            )
    
    def process_sync(
        self,
        file_path: Union[str, Path],
        store_embeddings: bool = True,
        store_on_ipfs: bool = None
    ) -> VectorEmbeddingResult:
        """Synchronous wrapper for process()."""
        if not ANYIO_AVAILABLE:
            raise ImportError("anyio is required for sync operations")
        
        return anyio.from_thread.run(
            self.process,
            file_path,
            store_embeddings,
            store_on_ipfs
        )
    
    async def process_batch(
        self,
        file_paths: List[Union[str, Path]],
        max_concurrent: int = 5,
        store_embeddings: bool = True,
        store_on_ipfs: bool = None
    ) -> List[VectorEmbeddingResult]:
        """
        Process multiple files in parallel.
        
        Args:
            file_paths: List of file paths
            max_concurrent: Maximum concurrent processing
            store_embeddings: Store embeddings in vector store
            store_on_ipfs: Store on IPFS
        
        Returns:
            List of VectorEmbeddingResult
        """
        if not ANYIO_AVAILABLE:
            raise ImportError("anyio is required for batch processing")
        
        results = []
        limiter = anyio.CapacityLimiter(max_concurrent)
        
        async def process_with_limit(file_path):
            async with limiter:
                return await self.process(file_path, store_embeddings, store_on_ipfs)
        
        async with anyio.create_task_group() as tg:
            tasks = []
            for file_path in file_paths:
                task = tg.start_soon(process_with_limit, file_path)
                tasks.append(task)
        
        # Collect results in order
        for file_path in file_paths:
            result = await process_with_limit(file_path)
            results.append(result)
        
        return results
    
    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[SearchResult]:
        """
        Semantic search over stored embeddings.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            filter_metadata: Optional metadata filters
        
        Returns:
            List of SearchResult
        """
        if not ANYIO_AVAILABLE:
            raise ImportError("anyio is required for search")
        
        if not self.vector_store:
            raise ValueError("Vector store not initialized")
        
        try:
            # Generate query embedding
            query_embeddings = await self.embeddings_engine.generate_embeddings(
                texts=[query],
                config=self.embedding_config
            )
            
            if not query_embeddings or len(query_embeddings) == 0:
                return []
            
            query_embedding = query_embeddings[0]
            
            # Search vector store
            results = await anyio.to_thread.run_sync(
                self.vector_store.search,
                query_embedding,
                top_k,
                filter_metadata
            )
            
            # Convert to SearchResult
            search_results = []
            for i, (score, metadata) in enumerate(results):
                search_results.append(SearchResult(
                    text=metadata.get("text", ""),
                    score=float(score),
                    chunk_index=metadata.get("chunk_index", i),
                    file_path=metadata.get("file_path"),
                    metadata=metadata
                ))
            
            return search_results
            
        except Exception as e:
            logger.error(f"Error during search: {e}", exc_info=True)
            return []
    
    def get_status(self) -> Dict[str, Any]:
        """Get pipeline status."""
        accelerate_status = {"available": False, "enabled": False}
        try:
            from ..embeddings_router import get_accelerate_status as _get_accelerate_status

            accelerate_status = _get_accelerate_status() or accelerate_status
        except Exception:
            pass

        return {
            "backend": self.backend,
            "embedding_model": self.embedding_model,
            "chunking_strategy": self.chunking_strategy,
            "vector_store": self.vector_store_type,
            "enable_ipfs": self.enable_ipfs,
            "enable_acceleration": self.enable_acceleration,
            "num_documents": len(self.document_registry),
            "embeddings_available": HAVE_EMBEDDINGS,
            "vector_store_available": self.vector_store is not None,
            "accelerate_available": bool(accelerate_status.get("available")) and bool(accelerate_status.get("enabled", True)),
        }


# Convenience functions
def create_vector_pipeline(
    embedding_model: str = 'sentence-transformers/all-MiniLM-L6-v2',
    vector_store: str = 'faiss',
    enable_ipfs: bool = False,
    enable_acceleration: bool = False
) -> VectorEmbeddingPipeline:
    """
    Create a vector embedding pipeline with sensible defaults.
    
    Args:
        embedding_model: HuggingFace embedding model name
        vector_store: Vector store type ('faiss', 'qdrant', 'elasticsearch')
        enable_ipfs: Enable IPFS storage
        enable_acceleration: Enable ML acceleration
    
    Returns:
        VectorEmbeddingPipeline instance
    """
    return VectorEmbeddingPipeline(
        backend='native',
        embedding_model=embedding_model,
        vector_store=vector_store,
        enable_ipfs=enable_ipfs,
        enable_acceleration=enable_acceleration
    )
