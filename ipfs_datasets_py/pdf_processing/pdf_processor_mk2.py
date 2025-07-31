"""
PDF Processing Pipeline Implementation

Implements the complete PDF processing pipeline:
PDF Input → Decomposition → IPLD Structuring → OCR Processing → 
LLM Optimization → Entity Extraction → Vector Embedding → 
IPLD GraphRAG Integration → Cross-Document Analysis → Query Interface
"""
import logging
import hashlib
import datetime
from pathlib import Path
from typing import Any, Optional, Union
from contextlib import nullcontext
from dataclasses import dataclass


import pymupdf  # PyMuPDF
import pdfplumber
from PIL import Image


from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.audit import AuditLogger
from ipfs_datasets_py.monitoring import MonitoringSystem
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph, Entity
from ipfs_datasets_py.monitoring import MonitoringConfig, MetricsConfig
from ipfs_datasets_py.pdf_processing.ocr_engine import MultiEngineOCR
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMDocument, LLMChunk
from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator


logger = logging.getLogger(__name__)


class PDFProcessor:
    """
    Core PDF Processing Pipeline Implementation

    The PDFProcessor class implements a comprehensive 10-stage PDF processing pipeline
    that transforms PDF documents into structured, searchable, and semantically enriched
    data structures. The pipeline processes PDF files through decomposition, IPLD structuring,
    OCR processing, LLM optimization, entity extraction, vector embedding generation,
    GraphRAG integration, cross-document analysis, and query interface setup.

    This class serves as the primary entry point for converting PDF documents into
    knowledge graphs with full content addressability, semantic search capabilities,
    and cross-document relationship discovery.

    Args:
        storage (Optional[IPLDStorage], optional): IPLD storage instance for data persistence.
            Defaults to a new IPLDStorage instance if not provided.
        enable_monitoring (bool, optional): Enable performance monitoring and metrics collection.
            When True, initializes MonitoringSystem with Prometheus export capabilities.
            Defaults to False.
        enable_audit (bool, optional): Enable audit logging for security and compliance tracking.
            When True, initializes AuditLogger for data access and security event logging.
            Defaults to True.
        mock_dict (Optional[dict[str, Any]], optional): Dictionary for dependency injection
            during testing. Allows replacement of components with mock objects.
            Defaults to None.

    Pipeline Stages:
    1. PDF Input - Validation and analysis of input PDF file
    2. Decomposition - Extract PDF layers, content, images, and metadata
    3. IPLD Structuring - Create content-addressed data structures
    4. OCR Processing - Process images with optical character recognition
    5. LLM Optimization - Optimize content for language model consumption
    6. Entity Extraction - Extract entities and relationships from content
    7. Vector Embedding - Create semantic embeddings for content chunks
    8. IPLD GraphRAG Integration - Integrate with GraphRAG knowledge system
    9. Cross-Document Analysis - Analyze relationships across document collections
    10. Query Interface Setup - Configure natural language query capabilities

    Attributes:
        storage (IPLDStorage): IPLD storage instance for persistent data storage
        audit_logger (Optional[AuditLogger]): Audit logger for security and compliance tracking
        monitoring (Optional[MonitoringSystem]): Performance monitoring system for metrics collection
        pipeline_version (str): Version identifier for the processing pipeline
        integrator (GraphRAGIntegrator): GraphRAG integration component
        ocr_engine (MultiEngineOCR): Multi-engine OCR processor
        optimizer (LLMOptimizer): LLM content optimization engine
        logger (logging.Logger): Logger instance for debug and info messages
        processing_stats (dict[str, Any]): Runtime statistics and performance metrics

    Public Methods:
        process_pdf(pdf_path: Union[str, Path], metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
            Execute the complete PDF processing pipeline from input validation through
            query interface setup, returning comprehensive processing results.

    Private Methods:
        _validate_and_analyze_pdf(pdf_path: Path) -> dict[str, Any]:
            Stage 1: Validate PDF file integrity and extract basic metadata analysis.
        _decompose_pdf(pdf_path: Path) -> dict[str, Any]:
            Stage 2: Decompose PDF into constituent elements including text, images,
            annotations, tables, and structural components.
        _extract_page_content(page: pymupdf.Page, page_num: int) -> dict[str, Any]:
            Extract comprehensive content from a single PDF page including text blocks,
            images, annotations, and vector graphics.
        _create_ipld_structure(decomposed_content: dict[str, Any]) -> dict[str, Any]:
            Stage 3: Create hierarchical IPLD structure with content-addressed storage
            for all decomposed PDF components.
        _process_ocr(decomposed_content: dict[str, Any]) -> dict[str, Any]:
            Stage 4: Process embedded images with multi-engine OCR for text extraction
            with confidence scoring and word-level positioning.
        _optimize_for_llm(decomposed_content: dict[str, Any], ocr_results: dict[str, Any]) -> dict[str, Any]:
            Stage 5: Optimize extracted content for large language model consumption
            through chunking, summarization, and semantic structuring.
        _extract_entities(optimized_content: dict[str, Any]) -> dict[str, Any]:
            Stage 6: Extract named entities and relationships from optimized content
            using pattern matching and co-occurrence analysis.
        _create_embeddings(optimized_content: dict[str, Any], entities_and_relations: dict[str, Any]) -> dict[str, Any]:
            Stage 7: Generate vector embeddings for content chunks and document-level
            representations using transformer models.
        _integrate_with_graphrag(ipld_structure: dict[str, Any], entities_and_relations: dict[str, Any], embeddings: dict[str, Any]) -> dict[str, Any]:
            Stage 8: Integrate processed content with GraphRAG system for knowledge
            graph construction and semantic relationship discovery.
        _analyze_cross_document_relationships(graph_nodes: dict[str, Any]) -> list[dict[str, Any]]:
            Stage 9: Analyze and discover relationships between entities across
            multiple documents in the knowledge graph.
        _setup_query_interface(graph_nodes: dict[str, Any], cross_doc_relations: list[dict[str, Any]]) -> None:
            Stage 10: Configure natural language query interface for semantic search
            and knowledge graph exploration.
        _calculate_file_hash(file_path: Path) -> str:
            Calculate SHA-256 hash of input file for integrity verification and
            content addressability.
        _extract_native_text(text_blocks: list[dict[str, Any]]) -> str:
            Extract and concatenate native text content from PDF text blocks
            preserving document structure.
        _get_processing_time(start_time: float) -> float:
            Calculate total elapsed time for complete pipeline processing
            given a start timestamp.
        _get_quality_scores(result: dict[str, Any]) -> dict[str, float]:
            Generate quality assessment scores for text extraction, OCR confidence,
            entity extraction, and overall processing quality.

    Usage Example:
        # Basic usage with default settings
        processor = PDFProcessor()
        result = await processor.process_pdf("document.pdf")
        
        # Advanced usage with monitoring and custom storage
        storage = IPLDStorage(config={'node_url': 'http://localhost:5001'})
        processor = PDFProcessor(
            storage=storage,
            enable_monitoring=True,
            enable_audit=True
        )
        metadata = {'source': 'legal_docs', 'priority': 'high'}
        result = await processor.process_pdf(
            pdf_path="contract.pdf",
            metadata=metadata
        )
        
        # Check processing results
        if result['status'] == 'success':
            print(f"Document ID: {result['document_id']}")
            print(f"Entities found: {result['entities_count']}")
            print(f"IPLD CID: {result['ipld_cid']}")

    Notes:
        - All processing stages are asynchronous for optimal performance
        - IPLD integration provides content-addressable storage and deduplication
        - GraphRAG integration enables semantic search and relationship discovery
        - Monitoring and audit logging support enterprise deployment requirements
        - Error handling ensures graceful failure with detailed error reporting
        - Cross-document analysis requires multiple documents in the knowledge graph
        - Pipeline is optimized for both single-document and batch processing scenarios
        - Mock dictionary support enables comprehensive unit testing with dependency injection
    """
    
    def __init__(self, 
                 storage: Optional[IPLDStorage] = None,
                 enable_monitoring: bool = False,
                 enable_audit: bool = True,
                 mock_dict: Optional[dict[str, Any]] = None
                 ) -> None:
        """
        Initialize the PDF processor with storage, monitoring, and audit capabilities.

        Sets up the core PDF processing pipeline with configurable storage backend,
        performance monitoring, and audit logging. Initializes processing state
        tracking and prepares all necessary components for document processing.

        Args:
            storage (Optional[IPLDStorage], optional): IPLD storage instance for data persistence.
                If None, creates a new IPLDStorage instance with default configuration.
                Custom storage instances allow for distributed IPFS node configuration.
                Defaults to None.
            enable_monitoring (bool, optional): Enable performance monitoring and metrics collection.
                When True, initializes MonitoringSystem with Prometheus export enabled,
                JSON metrics output, and operation tracking capabilities.
                Defaults to False.
            enable_audit (bool, optional): Enable audit logging for security and compliance.
                When True, initializes AuditLogger singleton for data access logging,
                security event tracking, and compliance reporting.
                Defaults to True.

        Attributes initialized:
            storage (IPLDStorage): IPLD storage instance for persistent data storage.
                Handles content-addressed storage, IPFS integration, and data retrieval.
            audit_logger (Optional[AuditLogger]): Audit logger for security and compliance tracking.
                Logs data access events, security incidents, and processing activities.
            monitoring (Optional[MonitoringSystem]): Performance monitoring system for metrics.
                Tracks operation performance, resource usage, and system health metrics.
            processing_stats (dict[str, Any]): Runtime statistics and performance metrics.
                Stores pipeline execution times, quality scores, and processing metadata.

        Raises:
            ImportError: If monitoring dependencies are missing when enable_monitoring=True
            RuntimeError: If audit logger initialization fails when enable_audit=True
            ConnectionError: If IPLD storage cannot connect to IPFS node

        Examples:
            >>> # Basic initialization with defaults
            >>> processor = PDFProcessor()
            >>> 
            >>> # Enterprise setup with full monitoring
            >>> custom_storage = IPLDStorage(config={'node_url': 'http://ipfs-cluster:5001'})
            >>> processor = PDFProcessor(
            ...     storage=custom_storage,
            ...     enable_monitoring=True,
            ...     enable_audit=True
            ... )
            >>> 
            >>> # Development setup without monitoring
            >>> processor = PDFProcessor(enable_monitoring=False, enable_audit=False)

        Note:
            Monitoring configuration includes Prometheus export and JSON metrics output.
            Audit logging captures all data access and security events for compliance.
            IPLD storage provides content deduplication and distributed storage capabilities.
        """
        self.storage = storage or IPLDStorage()
        self.audit_logger = None 
        self.monitoring = None
        self.pipeline_version: str = '2.0'
        self.integrator = GraphRAGIntegrator(storage=self.storage)
        self.ocr_engine = MultiEngineOCR()
        self.optimizer = LLMOptimizer()
        self.logger = logger

        if enable_audit:
            self.audit_logger = AuditLogger.get_instance()

        if enable_monitoring:
            config = MonitoringConfig()
            config.metrics = MetricsConfig(
                output_file="pdf_processing_metrics.json",
                prometheus_export=True
            )
            self.monitoring = MonitoringSystem.initialize(config)

        # For testing purposes, allow dependency injection of mock objects
        if mock_dict is not None:
            for key, value in mock_dict.items():
                try:
                    setattr(self, key, value)
                except AttributeError:
                    print(f"Warning: Mock attribute '{key}' not set in PDFProcessor")
                except KeyError:
                    print(f"Warning: Mock key '{key}' not found in mock_dict")

        # Processing state
        self.processing_stats = {
            "start_time": None,
            "end_time": None,
        }

    async def process_pdf(self, 
                         pdf_path: Union[str, Path], 
                         metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """
        Execute the complete PDF processing pipeline from input to query interface.

        Processes a PDF document through all 10 pipeline stages: validation, decomposition,
        IPLD structuring, OCR processing, LLM optimization, entity extraction, vector
        embedding, GraphRAG integration, cross-document analysis, and query setup.
        Returns comprehensive processing results with document metadata, entity counts,
        and IPLD content identifiers.

        Args:
            pdf_path (Union[str, Path]): Path to the PDF file to be processed.
                Must be a valid file path pointing to a readable PDF document.
                Supports both string paths and pathlib.Path objects.
            metadata (Optional[dict[str, Any]], optional): Additional metadata for the document.
                Can include source information, processing priorities, custom tags,
                or domain-specific metadata. Merged with extracted document metadata.
                Defaults to None.

        Returns:
            dict[str, Any]: Comprehensive processing results containing:
                - status (str): Processing status ('success' or 'error')
                - document_id (str): Unique identifier for the processed document
                - ipld_cid (str): Content identifier for IPLD root node
                - entities_count (int): Number of extracted entities
                - relationships_count (int): Number of discovered relationships
                - cross_doc_relations (int): Number of cross-document relationships
                - processing_metadata (dict[str, Any]): Processing statistics including:
                    - pipeline_version (str): Version of the processing pipeline
                    - processing_time (float): Total processing time in seconds
                    - quality_scores (dict[str, float]): Quality assessment metrics
                    - stages_completed (int): Number of successfully completed stages
                For error cases, returns:
                - status (str): 'error'
                - error (str): Error message describing the failure
                - pdf_path (str): Original file path for debugging

        Raises:
            FileNotFoundError: If the specified PDF file does not exist
            ValueError: If the PDF file is invalid, corrupted, or empty
            PermissionError: If insufficient permissions to read the PDF file
            RuntimeError: If critical pipeline stage fails and cannot be recovered
            TimeoutError: If processing exceeds configured timeout limits

        Examples:
            >>> # Basic document processing
            >>> result = await processor.process_pdf("document.pdf")
            >>> if result['status'] == 'success':
            ...     print(f"Processed {result['entities_count']} entities")
            >>> 
            >>> # Processing with custom metadata
            >>> metadata = {
            ...     'source': 'legal_department',
            ...     'classification': 'confidential',
            ...     'priority': 'high'
            ... }
            >>> result = await processor.process_pdf("contract.pdf", metadata=metadata)
            >>> 
            >>> # Batch processing example
            >>> results = []
            >>> for pdf_file in pdf_directory.glob("*.pdf"):
            ...     result = await processor.process_pdf(pdf_file)
            ...     results.append(result)

        Note:
            - Processing is fully asynchronous and can handle large PDF files efficiently.
            - All intermediate results are stored in IPLD for content addressability.
            - Failed processing attempts are logged for debugging and error analysis.
            - Cross-document relationships require multiple documents in the knowledge graph.
        """
        pdf_path = Path(pdf_path)
        
        # Audit logging
        if self.audit_logger:
            self.audit_logger.data_access(
                "pdf_processing_start",
                resource_id=str(pdf_path),
                resource_type="pdf_document"
            )
        
        # Performance monitoring
        operation_context: MonitoringSystem = None
        if self.monitoring:
            operation_context = self.monitoring.start_operation_trace(
                "pdf_processing_pipeline",
                tags=["pdf", "llm_optimization"]
            )

        start_time = datetime.datetime.now().timestamp()

        try:
            with operation_context if operation_context is not None else nullcontext():
                # Stage 1: PDF Input
                pdf_info = await self._validate_and_analyze_pdf(pdf_path)
                
                # Stage 2: Decomposition  
                decomposed_content = await self._decompose_pdf(pdf_path)
                
                # Stage 3: IPLD Structuring
                ipld_structure = await self._create_ipld_structure(decomposed_content)
                
                # Stage 4: OCR Processing
                ocr_results = await self._process_ocr(decomposed_content)
                
                # Stage 5: LLM Optimization
                optimized_content = await self._optimize_for_llm(
                    decomposed_content, ocr_results
                )
                
                # Stage 6: Entity Extraction
                entities_and_relations = await self._extract_entities(optimized_content)
                
                # Stage 7: Vector Embedding
                embeddings = await self._create_embeddings(
                    optimized_content, entities_and_relations
                )
                
                # Stage 8: IPLD GraphRAG Integration
                graph_nodes = await self._integrate_with_graphrag(
                    ipld_structure, entities_and_relations, embeddings
                )
                
                # Stage 9: Cross-Document Analysis
                cross_doc_relations = await self._analyze_cross_document_relationships(
                    graph_nodes
                )
                
                # Stage 10: Query Interface Setup
                await self._setup_query_interface(graph_nodes, cross_doc_relations)
                
                # Compile results
                result = {
                    'status': 'success',
                    'document_id': graph_nodes['document']['id'],
                    'ipld_cid': ipld_structure['root_cid'],
                    'entities_count': len(entities_and_relations['entities']),
                    'relationships_count': len(entities_and_relations['relationships']),
                    'cross_doc_relations': len(cross_doc_relations),
                    'processing_metadata': {
                        'pipeline_version': self.pipeline_version,
                        'processing_time': self._get_processing_time(start_time),
                        'quality_scores': None,
                        'stages_completed': 10,
                    },
                    'pdf_info': pdf_info,
                }
                if metadata:
                    result['processing_metadata'].update(metadata)

                quality_scores = self._get_quality_scores(result)
                result['processing_metadata']['quality_scores'] = quality_scores

                # Audit logging
                if self.audit_logger:
                    self.audit_logger.data_access(
                        "pdf_processing_complete",
                        resource_id=str(pdf_path),
                        resource_type="pdf_document",
                        details={"document_id": result['document_id']}
                    )
                
                return result
                
        except Exception as e:
            self.logger.error(f"PDF processing failed for {pdf_path}: {e}")
            
            if self.audit_logger:
                self.audit_logger.security(
                    "pdf_processing_error",
                    details={"error": str(e), "pdf_path": str(pdf_path)}
                )
            
            return {
                'status': 'error',
                'error': str(e),
                'pdf_path': str(pdf_path)
            }
    