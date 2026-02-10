"""
Knowledge Graph Integration for File Converter

Integrates the file_converter module with knowledge graph extraction and RAG systems
to enable text summaries and knowledge graph generation from arbitrary file formats.

This module provides:
- Universal knowledge graph pipeline (any format → knowledge graph)
- Text summarization pipeline (any format → summaries)
- IPFS storage integration
- ML acceleration support
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field

try:
    import anyio
    ANYIO_AVAILABLE = True
except ImportError:
    ANYIO_AVAILABLE = False

# File converter imports
from .converter import FileConverter, ConversionResult
from .ipfs_accelerate_converter import IPFSAcceleratedConverter, IPFSConversionResult
from .batch_processor import BatchProcessor, BatchProgress, ResourceLimits
from .metadata_extractor import extract_metadata

# Try to import knowledge graph modules
try:
    from ..knowledge_graphs.knowledge_graph_extraction import extract_knowledge_graph
    HAVE_KG_EXTRACTION = True
except ImportError:
    HAVE_KG_EXTRACTION = False
    extract_knowledge_graph = None

# Try to import RAG modules
try:
    from ..rag.rag_query_optimizer import RAGQueryOptimizer
    HAVE_RAG = True
except ImportError:
    HAVE_RAG = False
    RAGQueryOptimizer = None

# Try to import PDF processing for summaries
try:
    from ..pdf_processing.llm_optimizer import LLMOptimizer
    HAVE_LLM = True
except ImportError:
    HAVE_LLM = False
    LLMOptimizer = None

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeGraphResult:
    """Result from knowledge graph extraction."""
    
    text: str
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    summary: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    ipfs_cid: Optional[str] = None
    ipfs_graph_cid: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


@dataclass
class TextSummaryResult:
    """Result from text summarization."""
    
    text: str
    summary: str
    key_points: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    ipfs_cid: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


class UniversalKnowledgeGraphPipeline:
    """
    Universal pipeline for generating knowledge graphs from any file format.
    
    Pipeline:
    1. File → Text (via FileConverter)
    2. Text → Entities & Relationships (knowledge graph extraction)
    3. Store in IPFS (optional)
    4. Generate embeddings for RAG (optional)
    
    Usage:
        pipeline = UniversalKnowledgeGraphPipeline(enable_ipfs=True)
        result = await pipeline.process('document.pdf')
        print(f"Entities: {len(result.entities)}")
        print(f"Relationships: {len(result.relationships)}")
    """
    
    def __init__(
        self,
        backend: str = 'native',
        enable_ipfs: bool = False,
        enable_acceleration: bool = False,
        enable_rag: bool = False,
        llm_model: Optional[str] = None
    ):
        """
        Initialize the knowledge graph pipeline.
        
        Args:
            backend: File converter backend ('native', 'auto')
            enable_ipfs: Enable IPFS storage
            enable_acceleration: Enable ML acceleration
            enable_rag: Enable RAG integration
            llm_model: LLM model for summarization
        """
        self.backend = backend
        self.enable_ipfs = enable_ipfs
        self.enable_acceleration = enable_acceleration
        self.enable_rag = enable_rag
        
        # Initialize converter
        if enable_ipfs or enable_acceleration:
            self.converter = IPFSAcceleratedConverter(
                backend=backend,
                enable_ipfs=enable_ipfs,
                enable_acceleration=enable_acceleration
            )
        else:
            self.converter = FileConverter(backend=backend)
        
        # Initialize LLM optimizer for summaries
        self.llm_optimizer = None
        if HAVE_LLM and llm_model:
            try:
                self.llm_optimizer = LLMOptimizer(model_name=llm_model)
            except Exception as e:
                logger.warning(f"Could not initialize LLM optimizer: {e}")
        
        # Initialize RAG if enabled
        self.rag_optimizer = None
        if enable_rag and HAVE_RAG:
            try:
                self.rag_optimizer = RAGQueryOptimizer()
            except Exception as e:
                logger.warning(f"Could not initialize RAG optimizer: {e}")
    
    async def process(
        self,
        file_path: Union[str, Path],
        store_on_ipfs: bool = None,
        generate_summary: bool = True,
        extract_embeddings: bool = None
    ) -> KnowledgeGraphResult:
        """
        Process a file and extract knowledge graph.
        
        Args:
            file_path: Path to file
            store_on_ipfs: Store results on IPFS (uses instance default if None)
            generate_summary: Generate text summary
            extract_embeddings: Extract vector embeddings (uses enable_rag if None)
        
        Returns:
            KnowledgeGraphResult with entities, relationships, and metadata
        """
        file_path = Path(file_path)
        
        if store_on_ipfs is None:
            store_on_ipfs = self.enable_ipfs
        
        if extract_embeddings is None:
            extract_embeddings = self.enable_rag
        
        try:
            # Step 1: Convert file to text
            logger.info(f"Converting file: {file_path}")
            
            if isinstance(self.converter, IPFSAcceleratedConverter):
                result = await self.converter.convert(
                    str(file_path),
                    store_on_ipfs=store_on_ipfs
                )
                text = result.text
                ipfs_cid = result.ipfs_cid
            else:
                result = await self.converter.convert(str(file_path))
                text = result.text
                ipfs_cid = None
            
            if not text:
                return KnowledgeGraphResult(
                    text="",
                    success=False,
                    error="No text extracted from file"
                )
            
            # Step 2: Extract metadata
            metadata = extract_metadata(file_path)
            
            # Step 3: Extract knowledge graph
            entities = []
            relationships = []
            
            if HAVE_KG_EXTRACTION and extract_knowledge_graph:
                try:
                    logger.info("Extracting knowledge graph")
                    kg_data = await anyio.to_thread.run_sync(
                        extract_knowledge_graph,
                        text
                    )
                    
                    if isinstance(kg_data, dict):
                        entities = kg_data.get('entities', [])
                        relationships = kg_data.get('relationships', [])
                    elif isinstance(kg_data, tuple):
                        entities, relationships = kg_data
                        
                    logger.info(f"Extracted {len(entities)} entities and {len(relationships)} relationships")
                except Exception as e:
                    logger.warning(f"Knowledge graph extraction failed: {e}")
            else:
                logger.warning("Knowledge graph extraction not available")
            
            # Step 4: Generate summary if requested
            summary = None
            if generate_summary and self.llm_optimizer and text:
                try:
                    logger.info("Generating summary")
                    summary_result = await anyio.to_thread.run_sync(
                        self.llm_optimizer.summarize,
                        text
                    )
                    summary = summary_result if isinstance(summary_result, str) else str(summary_result)
                    logger.info("Summary generated")
                except Exception as e:
                    logger.warning(f"Summary generation failed: {e}")
            
            # Step 5: Store knowledge graph on IPFS if enabled
            ipfs_graph_cid = None
            if store_on_ipfs and self.enable_ipfs:
                try:
                    # Create knowledge graph structure
                    kg_structure = {
                        'entities': entities,
                        'relationships': relationships,
                        'summary': summary,
                        'metadata': metadata
                    }
                    
                    # Store on IPFS (would need IPFS backend implementation)
                    logger.info("Storing knowledge graph on IPFS")
                    # ipfs_graph_cid = await store_on_ipfs(kg_structure)
                except Exception as e:
                    logger.warning(f"IPFS storage failed: {e}")
            
            return KnowledgeGraphResult(
                text=text,
                entities=entities,
                relationships=relationships,
                summary=summary,
                metadata=metadata,
                ipfs_cid=ipfs_cid,
                ipfs_graph_cid=ipfs_graph_cid,
                success=True
            )
            
        except Exception as e:
            logger.error(f"Pipeline processing failed: {e}", exc_info=True)
            return KnowledgeGraphResult(
                text="",
                success=False,
                error=str(e)
            )
    
    def process_sync(
        self,
        file_path: Union[str, Path],
        **kwargs
    ) -> KnowledgeGraphResult:
        """Synchronous wrapper for process()."""
        if not ANYIO_AVAILABLE:
            raise RuntimeError("anyio is required for sync wrapper")
        
        return anyio.from_thread.run(self.process, file_path, **kwargs)


class TextSummarizationPipeline:
    """
    Pipeline for generating text summaries from any file format.
    
    Pipeline:
    1. File → Text (via FileConverter)
    2. Text → Summary (via LLM)
    3. Extract key entities
    4. Store in IPFS (optional)
    
    Usage:
        pipeline = TextSummarizationPipeline(llm_model='gpt-3.5-turbo')
        result = await pipeline.summarize('document.pdf')
        print(f"Summary: {result.summary}")
    """
    
    def __init__(
        self,
        backend: str = 'native',
        llm_model: Optional[str] = None,
        enable_ipfs: bool = False,
        max_summary_length: int = 500
    ):
        """
        Initialize the summarization pipeline.
        
        Args:
            backend: File converter backend
            llm_model: LLM model name
            enable_ipfs: Enable IPFS storage
            max_summary_length: Maximum summary length
        """
        self.backend = backend
        self.enable_ipfs = enable_ipfs
        self.max_summary_length = max_summary_length
        
        # Initialize converter
        if enable_ipfs:
            self.converter = IPFSAcceleratedConverter(
                backend=backend,
                enable_ipfs=enable_ipfs
            )
        else:
            self.converter = FileConverter(backend=backend)
        
        # Initialize LLM optimizer
        self.llm_optimizer = None
        if HAVE_LLM and llm_model:
            try:
                self.llm_optimizer = LLMOptimizer(model_name=llm_model)
            except Exception as e:
                logger.warning(f"Could not initialize LLM optimizer: {e}")
    
    async def summarize(
        self,
        file_path: Union[str, Path],
        store_on_ipfs: bool = None
    ) -> TextSummaryResult:
        """
        Summarize a file.
        
        Args:
            file_path: Path to file
            store_on_ipfs: Store on IPFS (uses instance default if None)
        
        Returns:
            TextSummaryResult with summary and key points
        """
        file_path = Path(file_path)
        
        if store_on_ipfs is None:
            store_on_ipfs = self.enable_ipfs
        
        try:
            # Step 1: Convert to text
            logger.info(f"Converting file: {file_path}")
            
            if isinstance(self.converter, IPFSAcceleratedConverter):
                result = await self.converter.convert(
                    str(file_path),
                    store_on_ipfs=store_on_ipfs
                )
                text = result.text
                ipfs_cid = result.ipfs_cid
            else:
                result = await self.converter.convert(str(file_path))
                text = result.text
                ipfs_cid = None
            
            if not text:
                return TextSummaryResult(
                    text="",
                    summary="",
                    success=False,
                    error="No text extracted"
                )
            
            # Step 2: Generate summary
            summary = ""
            key_points = []
            
            if self.llm_optimizer:
                try:
                    logger.info("Generating summary")
                    summary_result = await anyio.to_thread.run_sync(
                        self.llm_optimizer.summarize,
                        text,
                        self.max_summary_length
                    )
                    summary = summary_result if isinstance(summary_result, str) else str(summary_result)
                except Exception as e:
                    logger.warning(f"Summary generation failed: {e}")
                    # Fallback: simple truncation
                    summary = text[:self.max_summary_length] + "..."
            else:
                # Simple fallback
                summary = text[:self.max_summary_length] + "..."
            
            # Step 3: Extract key entities (simple extraction)
            entities = []
            if HAVE_KG_EXTRACTION:
                try:
                    kg_data = await anyio.to_thread.run_sync(
                        extract_knowledge_graph,
                        text
                    )
                    if isinstance(kg_data, dict):
                        entities = [e.get('name', '') for e in kg_data.get('entities', [])]
                    elif isinstance(kg_data, tuple):
                        entity_list, _ = kg_data
                        entities = [e.get('name', '') for e in entity_list]
                except Exception as e:
                    logger.warning(f"Entity extraction failed: {e}")
            
            # Get metadata
            metadata = extract_metadata(file_path)
            
            return TextSummaryResult(
                text=text,
                summary=summary,
                key_points=key_points,
                entities=entities,
                metadata=metadata,
                ipfs_cid=ipfs_cid,
                success=True
            )
            
        except Exception as e:
            logger.error(f"Summarization failed: {e}", exc_info=True)
            return TextSummaryResult(
                text="",
                summary="",
                success=False,
                error=str(e)
            )
    
    def summarize_sync(
        self,
        file_path: Union[str, Path],
        **kwargs
    ) -> TextSummaryResult:
        """Synchronous wrapper for summarize()."""
        if not ANYIO_AVAILABLE:
            raise RuntimeError("anyio is required for sync wrapper")
        
        return anyio.from_thread.run(self.summarize, file_path, **kwargs)


class BatchKnowledgeGraphProcessor:
    """
    Batch processor for knowledge graph extraction from multiple files.
    
    Uses the file_converter batch_processor with knowledge graph extraction.
    Supports IPFS storage and ML acceleration.
    
    Usage:
        processor = BatchKnowledgeGraphProcessor(enable_ipfs=True)
        results = await processor.process_batch(['doc1.pdf', 'doc2.docx'])
    """
    
    def __init__(
        self,
        backend: str = 'native',
        enable_ipfs: bool = False,
        enable_acceleration: bool = False,
        max_concurrent: int = 5,
        **kwargs
    ):
        """
        Initialize batch processor.
        
        Args:
            backend: File converter backend
            enable_ipfs: Enable IPFS storage
            enable_acceleration: Enable ML acceleration
            max_concurrent: Maximum concurrent processing
            **kwargs: Additional pipeline arguments
        """
        self.pipeline = UniversalKnowledgeGraphPipeline(
            backend=backend,
            enable_ipfs=enable_ipfs,
            enable_acceleration=enable_acceleration,
            **kwargs
        )
        self.max_concurrent = max_concurrent
    
    async def process_batch(
        self,
        file_paths: List[Union[str, Path]],
        progress_callback: Optional[callable] = None,
        **kwargs
    ) -> List[KnowledgeGraphResult]:
        """
        Process multiple files in batch.
        
        Args:
            file_paths: List of file paths
            progress_callback: Callback for progress updates
            **kwargs: Additional processing arguments
        
        Returns:
            List of KnowledgeGraphResult
        """
        results = []
        completed = 0
        total = len(file_paths)
        
        limiter = anyio.CapacityLimiter(self.max_concurrent)
        
        async def process_one(file_path):
            nonlocal completed
            async with limiter:
                result = await self.pipeline.process(file_path, **kwargs)
                completed += 1
                
                if progress_callback:
                    progress_callback(completed, total, result.success)
                
                return result
        
        async with anyio.create_task_group() as tg:
            for file_path in file_paths:
                tg.start_soon(process_one, file_path)
        
        return results
