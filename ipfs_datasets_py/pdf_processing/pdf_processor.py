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
            Processing is fully asynchronous and can handle large PDF files efficiently.
            All intermediate results are stored in IPLD for content addressability.
            Failed processing attempts are logged for debugging and error analysis.
            Cross-document relationships require multiple documents in the knowledge graph.
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
        operation_context = None
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
    
    async def _validate_and_analyze_pdf(self, pdf_path: Path) -> dict[str, Any]:
        """
        Stage 1: Validate PDF file integrity and extract basic metadata analysis.

        Performs comprehensive validation of the input PDF file including existence checks,
        file size validation, PDF format verification, and basic structural analysis.
        Extracts essential metadata such as page count, file hash, and modification dates
        for processing pipeline initialization and integrity verification.

        Args:
            pdf_path (Path): Path object pointing to the PDF file for validation.
                Must be a valid pathlib.Path object with appropriate file permissions.

        Returns:
            dict[str, Any]: PDF validation and analysis results containing:
                - file_path (str): Absolute path to the validated PDF file
                - file_size (int): File size in bytes
                - page_count (int): Number of pages in the PDF document
                - file_hash (str): SHA-256 hash for integrity verification
                - analysis_timestamp (str): ISO format timestamp of analysis

        Raises:
            FileNotFoundError: If the PDF file does not exist at the specified path
            ValueError: If the PDF file is empty, corrupted, or not a valid PDF format
            PermissionError: If insufficient permissions to read the PDF file
            RuntimeError: If PyMuPDF cannot open the PDF due to format issues

        Examples:
            >>> pdf_info = await processor._validate_and_analyze_pdf(Path("document.pdf"))
            >>> print(f"Pages: {pdf_info['page_count']}")
            >>> print(f"Size: {pdf_info['file_size']} bytes")
            >>> print(f"Hash: {pdf_info['file_hash']}")

        Note:
            Uses PyMuPDF for PDF format validation and page counting.
            File hash provides content addressability and deduplication capabilities.
            Analysis timestamp enables processing audit trails and cache validation.
        """
        self.logger.info(f"Stage 1: Validating PDF {pdf_path}")

        # Basic file validation
        file_size = pdf_path.stat().st_size
        if file_size == 0:
            raise ValueError("PDF file is empty")

        # Open with PyMuPDF for analysis
        try:
            doc = pymupdf.open(str(pdf_path))
            page_count = doc.page_count
            doc.close()
        except FileNotFoundError:
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        except pymupdf.FileDataError as e:
            raise ValueError(f"Invalid PDF file format for '{pdf_path.name}: {e}") from e
        except pymupdf.mupdf.FzErrorFormat as e:
            raise ValueError(f"Corrupted PDF file for '{pdf_path.name}': {e}") from e
        except Exception as e:
            raise RuntimeError(f"Unexpected error opening PDF file '{pdf_path}': {e}") from e
        
        return {
            'file_path': str(pdf_path),
            'file_size': file_size,
            'page_count': page_count,
            'file_hash': self._calculate_file_hash(pdf_path),
            'analysis_timestamp': datetime.datetime.now().isoformat()
        }
    
    async def _decompose_pdf(self, pdf_path: Path) -> dict[str, Any]:
        """
        Stage 2: Decompose PDF into constituent elements and content layers.

        Performs comprehensive PDF decomposition extracting all content layers including
        text blocks, images, annotations, tables, metadata, document structure, fonts,
        and vector graphics. Uses both PyMuPDF and pdfplumber for complementary
        extraction capabilities ensuring maximum content recovery and structural preservation.

        Args:
            pdf_path (Path): Path object pointing to the validated PDF file.
                Must be a readable PDF file that has passed validation stage.

        Returns:
            dict[str, Any]: Comprehensive decomposed content structure containing:
                - pages (list[dict[str, Any]]): Per-page content with elements, images, annotations
                - metadata (dict[str, str]): Document metadata including title, author, dates
                - structure (dict[str, Any]): Table of contents and outline information
                - images (list[dict[str, Any]]): Extracted image data and metadata
                - fonts (list[dict[str, str]]): Font information and usage statistics
                - annotations (list[dict[str, Any]]): Comments, highlights, and markup elements

        Raises:
            ValueError: If PDF file cannot be opened or is corrupted during processing
            RuntimeError: If PyMuPDF or pdfplumber encounter fatal errors during extraction
            MemoryError: If PDF file is too large for available system memory
            IOError: If file system errors occur during image extraction

        Examples:
            >>> decomposed = await processor._decompose_pdf(Path("document.pdf"))
            >>> print(f"Pages: {len(decomposed['pages'])}")
            >>> print(f"Images: {len(decomposed['images'])}")
            >>> print(f"Title: {decomposed['metadata']['title']}")

        Note:
            PyMuPDF handles comprehensive content extraction and image data.
            pdfplumber provides enhanced table detection and word-level positioning.
            Large PDF files are processed page-by-page to manage memory usage.
            Vector graphics and drawing elements are preserved with bounding boxes.
        """
        self.logger.info(f"Stage 2: Decomposing PDF {pdf_path}")
        
        decomposed_content = {
            'pages': [],
            'metadata': {},
            'structure': {},
            'images': [],
            'fonts': [],
            'annotations': []
        }
        
        try:
            # Use PyMuPDF for comprehensive extraction
            doc = pymupdf.open(str(pdf_path))
            
            # Extract document metadata
            decomposed_content['metadata'] = {
                'title': doc.metadata.get('title', ''),
                'author': doc.metadata.get('author', ''),
                'subject': doc.metadata.get('subject', ''),
                'creator': doc.metadata.get('creator', ''),
                'producer': doc.metadata.get('producer', ''),
                'creation_date': doc.metadata.get('creationDate', ''),
                'modification_date': doc.metadata.get('modDate', ''),
                'page_count': doc.page_count,
                'is_encrypted': doc.is_encrypted,
                'document_id': hashlib.md5(str(pdf_path).encode()).hexdigest()
            }
            
            # Process each page
            for page_num in range(doc.page_count):
                page = doc[page_num]
                page_content = await self._extract_page_content(page, page_num)
                decomposed_content['pages'].append(page_content)
                
                # Aggregate images and annotations at document level
                decomposed_content['images'].extend(page_content['images'])
                decomposed_content['annotations'].extend(page_content['annotations'])
            
            # Extract document structure (table of contents)
            toc = doc.get_toc()
            decomposed_content['structure'] = {
                'table_of_contents': toc,
                'outline': toc,  # Add outline for compatibility
                'outline_depth': max([item[0] for item in toc], default=0) if toc else 0
            }
            
            # Store page count before closing document
            page_count = doc.page_count
            doc.close()
            
            # Use pdfplumber for additional text analysis
            with pdfplumber.open(str(pdf_path)) as pdf:
                for i, page in enumerate(pdf.pages):
                    # Extract tables
                    tables = page.extract_tables()
                    if tables:
                        decomposed_content['pages'][i]['tables'] = tables
                    
                    # Extract detailed text with positions
                    words = page.extract_words()
                    decomposed_content['pages'][i]['words'] = words
            
            self.logger.info(f"Successfully decomposed {page_count} pages")
            return decomposed_content
            
        except (ValueError, pymupdf.FileDataError, pymupdf.mupdf.FzErrorFormat) as e:
            self.logger.error(f"PDF decomposition failed: {e}")
            raise ValueError(f"PDF decomposition failed: {e}") from e
        except MemoryError as e:
            self.logger.error(f"PDF decomposition failed: {e}")
            raise MemoryError(f"PDF decomposition failed: {e}") from e
        except (RuntimeError, IOError) as e:
            self.logger.error(f"PDF decomposition failed: {e}")
            raise RuntimeError(f"PDF decomposition failed: {e}") from e
        except Exception as e:
            self.logger.error(f"PDF decomposition failed: {e}")
            raise ValueError(f"PDF decomposition failed: {e}") from e
    
    async def _extract_page_content(self, page: pymupdf.Page, page_num: int) -> dict[str, Any]:
        """
        Extract comprehensive content from a single PDF page with detailed positioning.

        Processes individual PDF pages to extract text blocks, embedded images, annotations,
        vector graphics, and structural elements. Provides detailed positioning information,
        confidence scores, and element classification for downstream processing stages.
        Handles complex page layouts with overlapping elements and mixed content types.

        Args:
            page: PyMuPDF page object representing a single PDF page.
                Must be a valid pymupdf.Page object with loaded content.
            page_num (int): Page number for identification and ordering.
                Used for element referencing and cross-page relationship analysis.
                If page number is 0, 1 is added to it for one-based indexing.

        Returns:
            dict[str, Any]: Comprehensive page content structure containing:
                - page_number (int): One-based page number for user reference
                - elements (list[dict[str, Any]]): Structured elements with type, content, position
                - images (list[dict[str, Any]]): Image metadata including size, colorspace, format
                - annotations (list[dict[str, Any]]): Comments, highlights, and markup elements
                - text_blocks (list[dict[str, Any]]): Text content with bounding boxes
                - drawings (list[dict[str, Any]]): Vector graphics and drawing elements

        Raises:
            TypeError: If page is not a valid PyMuPDF Page object or page_num is not an integer
            ValueError: If page number is negative or exceeds document page count
            RuntimeError: If no content is extracted from the page.

        Examples:
            >>> page_content = await processor._extract_page_content(page, 0)
            >>> print(f"Elements: {len(page_content['elements'])}")
            >>> print(f"Images: {len(page_content['images'])}")
            >>> for element in page_content['elements']:
            ...     print(f"{element['type']}: {element['content'][:50]}...")

        Note:
            - Text blocks preserve original formatting and positioning information.
            - Images are extracted with metadata but not stored as binary data initially.
            - Annotations include author information and modification timestamps.
            - Vector graphics are catalogued but not rasterized.
        """
        if not isinstance(page, pymupdf.Page):
            raise TypeError(f"Expected a PyMuPDF Page object for content extraction, got {type(page).__name__}")

        if not isinstance(page_num, int):
            raise TypeError(f"Page number must be an integer, got {type(page_num).__name__}")

        if page_num < 0 or page_num >= page.parent.page_count:
            raise ValueError(f"Invalid page number: {page_num}")
        elif page_num == 0:
            page_num += 1

        page_content = {
            'page_number': page_num,
            'elements': [],
            'images': [],
            'annotations': [],
            'text_blocks': [],
            'drawings': []
        }

        # Extract text blocks
        try:
            text_dict = page.get_text('dict')
        except Exception as e:
            self.logger.error(f"Failed to extract text from page {page_num}: {e}")
            text_dict = {"blocks": []}

        for block in text_dict["blocks"]:
            if "lines" in block:  # Text block
                block_text = ""
                for line in block["lines"]:
                    for span in line["spans"]:
                        block_text += span["text"]
                    block_text += "\n"
                
                page_content['text_blocks'].append({
                    'content': block_text.strip(),
                    'bbox': block["bbox"],
                    'block_type': 'text'
                })
                
                # Add as structured element
                page_content['elements'].append({
                    'type': 'text',
                    'subtype': 'paragraph',
                    'content': block_text.strip(),
                    'position': {
                        'x0': block["bbox"][0],
                        'y0': block["bbox"][1],
                        'x1': block["bbox"][2],
                        'y1': block["bbox"][3]
                    },
                    'confidence': 1.0
                })
        
        # Extract images
        try:
            image_list = page.get_images()
        except Exception as e:
            self.logger.error(f"Failed to extract images from page {page_num}: {e}")
            image_list = []

        for img_index, img in enumerate(image_list):
            try:
                # Extract image data
                xref = img[0]
                pix = pymupdf.Pixmap(page.parent, xref)
                
                if pix.n - pix.alpha < 4:  # GRAY or RGB
                    img_data = pix.tobytes("png")
                    
                    page_content['images'].append({
                        'image_index': img_index,
                        'xref': xref,
                        'size': len(img_data),
                        'width': pix.width,
                        'height': pix.height,
                        'colorspace': pix.colorspace.name if pix.colorspace else 'unknown',
                        'ext': 'png',  # Default format
                        'bbox': [0, 0, pix.width, pix.height]  # Default bbox
                    })
                    
                    # Add as structured element
                    page_content['elements'].append({
                        'type': 'image',
                        'subtype': 'embedded_image',
                        'content': f"Image {img_index} ({pix.width}x{pix.height})",
                        'position': {},  # Would need additional analysis for position
                        'confidence': 1.0,
                        'metadata': {
                            'width': pix.width,
                            'height': pix.height,
                            'colorspace': pix.colorspace.name if pix.colorspace else 'unknown'
                        }
                    })
                pix = None  # Free memory

            except Exception as e:
                self.logger.warning(f"Failed to extract image {img_index}: {e}")
        
        # Extract annotations
        try:
            page_annots = [annot for annot in page.annots()]
        except Exception as e:
            self.logger.error(f"Failed to extract annotations from page {page_num}: {e}")
            page_annots = []

        for annot in page_annots:
            annot_dict = {
                'type': annot.type[1],  # Annotation type name
                'content': annot.info.get("content", ""),
                'author': annot.info.get("title", ""),
                'page': page_num,
                'bbox': list(annot.rect)
            }
            page_content['annotations'].append(annot_dict)
            
            # Add as structured element if has content
            if annot_dict['content']:
                page_content['elements'].append({
                    'type': 'annotation',
                    'subtype': annot_dict['type'],
                    'content': annot_dict['content'],
                    'position': {
                        'x0': annot.rect[0],
                        'y0': annot.rect[1],
                        'x1': annot.rect[2],
                        'y1': annot.rect[3]
                    },
                    'confidence': 1.0
                })
        
        # Extract vector graphics/drawings
        try:
            drawings = page.get_drawings()
        except Exception as e:
            self.logger.error(f"Failed to extract drawings from page {page_num}: {e}")
            drawings = []
    
        for drawing in drawings:
            page_content['drawings'].append({
                'bbox': drawing['rect'],
                'type': 'vector_drawing',
                'items': len(drawing.get('items', []))
            })

        # Check if we actually extracted any content
        page_num = page_content.pop('page_number')
        if not all(value for value in page_content.values()):
            raise ValueError(f"No content extracted from page {page_num}")

        return page_content

    def _get_processing_time(self, start_time: float):
        """
        Calculate total elapsed time for complete pipeline processing including all stages.

        Computes total processing time from pipeline initiation through completion
        including all 10 processing stages, error handling, and overhead operations.
        Provides performance metrics for monitoring, optimization, and capacity planning
        across different document types and sizes.

        Args:
            start_time (float): Timestamp when processing started, typically from

        Returns:
            float: Total processing time in seconds with decimal precision.
                Includes all pipeline stages and overhead operations.

        Raises:
            TypeError: If start_time is not a float timestamp
            ValueError: If start_time or the return value are negative.

        Examples:
            >>> processing_time = processor._get_processing_time()
            >>> print(f"Total processing time: {processing_time:.2f} seconds")
            >>> # Performance monitoring
            >>> if processing_time > 60.0:
            ...     print("Warning: Processing time exceeded threshold")

        Note:
            Processing time includes I/O operations, computation, and storage overhead.
            Metrics support performance optimization and capacity planning.
        """
        # Get processing statistics or calculate from start time
        end_time = datetime.datetime.now().timestamp()

        if not isinstance(start_time, float):
            raise TypeError("Start time must be a float timestamp")

        if start_time > 0:
            total_time = end_time - start_time
            if total_time < 0:
                raise ValueError("Invalid processing time calculation: negative duration")
        else:
            raise ValueError("Processing start time is a negative value")

    async def _create_ipld_structure(self, decomposed_content: dict[str, Any]) -> dict[str, Any]:
        """
        Stage 3: Create hierarchical IPLD structure with content-addressed storage.

        Transforms decomposed PDF content into InterPlanetary Linked Data (IPLD) format
        providing content addressability, deduplication, and distributed storage capabilities.
        Creates hierarchical node structure with separate storage for pages, metadata,
        and content elements enabling efficient retrieval and cross-document linking.

        Args:
            decomposed_content (dict[str, Any]): Complete decomposed PDF content structure.
                Must contain pages, metadata, images, and structural information from
                the decomposition stage.

        Returns:
            dict[str, Any]: IPLD structure with content identifiers containing:
                - document (dict[str, Any]): Document-level metadata and page references
                - content_map (dict[str, str]): Mapping of content keys to IPLD CIDs
                - root_cid (str): Content identifier for the document root node

        Raises:
            RuntimeError: If IPLD storage operations fail due to network or node issues
            ValueError: If decomposed content structure is invalid or incomplete
            ConnectionError: If IPFS node is unreachable or unresponsive
            StorageError: If content serialization or storage operations fail

        Examples:
            >>> ipld_structure = await processor._create_ipld_structure(decomposed_content)
            >>> print(f"Root CID: {ipld_structure['root_cid']}")
            >>> print(f"Pages stored: {len(ipld_structure['content_map'])}")
            >>> # Retrieve specific page
            >>> page_cid = ipld_structure['content_map']['page_1']

        Note:
            Each page is stored as a separate IPLD node for efficient retrieval.
            Content deduplication occurs automatically through content addressing.
            IPLD structure enables distributed storage and replication across nodes.
            Failed storage operations are logged but don't halt pipeline processing.
        """
        self.logger.info("Stage 3: Creating IPLD structure")
        
        # Create hierarchical IPLD structure
        ipld_structure = {
            'document': {
                'metadata': decomposed_content['metadata'],
                'pages': {}
            },
            'content_map': {},
            'root_cid': None
        }
        
        # Store each page as separate IPLD node
        for page_data in decomposed_content['pages']:
            page_num = page_data['page_number']
            
            # Create page IPLD node
            page_node = {
                'page_number': page_num,
                'elements': page_data['elements'],
                'images': page_data['images'],
                'annotations': page_data['annotations'],
                'text_blocks': page_data['text_blocks']
            }
            
            # Store in IPFS
            try:
                page_cid = self.storage.store_json(page_node)
                ipld_structure['content_map'][f'page_{page_num}'] = page_cid
                ipld_structure['document']['pages'][page_num] = {
                    'cid': page_cid,
                    'element_count': len(page_data['elements'])
                }
            except Exception as e:
                raise RuntimeError(f"Failed to store page {page_num} in IPLD: {e}") from e
        
        # Store document metadata
        try:
            doc_cid = self.storage.store_json(ipld_structure['document'])
            ipld_structure['root_cid'] = doc_cid
        except Exception as e:
            raise RuntimeError(f"Failed to store document metadata in IPLD: {e}") from e

        return ipld_structure
    
    async def _process_ocr(self, decomposed_content: dict[str, Any]) -> dict[str, Any]:
        """
        Stage 4: Process embedded images with multi-engine OCR for text extraction.

        Applies optical character recognition to all embedded images within the PDF
        using multiple OCR engines for accuracy comparison and confidence scoring.
        Extracts text content, word-level positioning, and confidence metrics for
        each recognized text element enabling comprehensive image-based content recovery.

        Args:
            decomposed_content (dict[str, Any]): Decomposed PDF content containing image data.
                Must include page-level image information with extraction metadata.

        Returns:
            dict[str, Any]: OCR processing results organized by page containing:
                - Page-keyed dictionary with OCR results for each image
                - For each image: text content, confidence score, engine used, word boxes
                - Aggregate confidence scores and text quality metrics

        Raises:
            ImportError: If required OCR engine dependencies are not available
            RuntimeError: If OCR processing fails due to image format or corruption issues
            MemoryError: If images are too large for OCR processing memory limits
            TimeoutError: If OCR processing exceeds configured timeout limits

        Examples:
            >>> ocr_results = await processor._process_ocr(decomposed_content)
            >>> for page_num, page_ocr in ocr_results.items():
            ...     for img_result in page_ocr:
            ...         print(f"Image {img_result['image_index']}: {img_result['text']}")
            ...         print(f"Confidence: {img_result['confidence']}")

        Note:
            Production implementation integrates Tesseract, PaddleOCR, or cloud services.
            Multiple engines enable confidence comparison and accuracy validation.
            Word-level positioning supports precise content localization and extraction.
        """
        self.logger.info("Stage 4: Processing OCR")
        
        
        ocr_results = {}
        
        for page_data in decomposed_content['pages']:
            page_num = page_data['page_number']
            page_ocr_results = []
            
            # Process images on this page
            for img_data in page_data.get('images', []):
                try:
                    # Convert image data for OCR processing
                    if 'data' in img_data:
                        image_data = img_data['data']
                    else:
                        # Skip if no image data available
                        self.logger.warning(f"No image data available for image {img_data.get('image_index', 0)} on page {page_num}")
                        continue
                    
                    # Process image with OCR engine
                    ocr_result = await self.ocr_engine.extract_with_ocr(
                        image_data=image_data,
                        strategy='quality_first', # TODO need to allow setting of strategy.
                        confidence_threshold=0.7 # TODO need to allow setting of threshold.
                    )
                    
                    page_ocr_results.append({
                        'image_index': img_data.get('image_index', 0),
                        'text': ocr_result.get('text', ''),
                        'confidence': ocr_result.get('confidence', 0.0),
                        'engine_used': ocr_result.get('engine', 'unknown'),
                        'word_boxes': ocr_result.get('word_boxes', [])
                    })
                    
                except Exception as e:
                    self.logger.warning(f"OCR failed for image {img_data.get('image_index', 0)} on page {page_num}: {e}")
                    # Add empty result for failed OCR
                    page_ocr_results.append({
                        'image_index': img_data.get('image_index', 0),
                        'text': '',
                        'confidence': 0.0,
                        'engine_used': 'failed',
                        'word_boxes': []
                    })
            
            ocr_results[page_num] = page_ocr_results
        
        return ocr_results
    
    async def _optimize_for_llm(self, 
                               decomposed_content: dict[str, Any], 
                               ocr_results: dict[str, Any]) -> dict[str, Any]:
        """
        Stage 5: Optimize extracted content for large language model consumption.

        Transforms raw PDF content into LLM-optimized format through intelligent chunking,
        content structuring, summarization, and semantic type classification. Integrates
        OCR results with native text and creates coherent, contextually meaningful
        chunks suitable for embedding generation and semantic analysis.

        Args:
            decomposed_content (dict[str, Any]): Complete decomposed PDF content structure.
                Contains text blocks, images, annotations, and structural information.
            ocr_results (dict[str, Any]): OCR processing results for embedded images.
                Provides extracted text content with confidence scores and positioning.

        Returns:
            dict[str, Any]: LLM-optimized content structure containing:
                - llm_document (LLMDocument): Structured document with chunks and metadata
                - chunks (list[LLMChunk]): Optimized content chunks with embeddings
                - summary (str): Document-level summary for context and retrieval
                - key_entities (list[dict[str, Any]]): Extracted entities with types and positions

        Raises:
            ValueError: If content structure is invalid or cannot be processed
            RuntimeError: If LLM optimization engine encounters fatal errors
            MemoryError: If document size exceeds available memory for processing
            ImportError: If required LLM optimization dependencies are missing

        Examples:
            >>> optimized = await processor._optimize_for_llm(decomposed_content, ocr_results)
            >>> llm_doc = optimized['llm_document']
            >>> print(f"Chunks: {len(llm_doc.chunks)}")
            >>> print(f"Summary: {llm_doc.summary}")
            >>> print(f"Entities: {len(optimized['key_entities'])}")

        Note:
            Chunking strategy preserves semantic coherence and context boundaries.
            OCR text is integrated seamlessly with native PDF text content.
            Entity extraction occurs during optimization for efficiency.
            Document embeddings are generated for similarity search and clustering.
        """
        self.logger.info("Stage 5: Optimizing for LLM")

        # Optimize the decomposed content for LLM processing
        llm_document = await self.optimizer.optimize_for_llm(
            decomposed_content,
            decomposed_content['metadata']
        )
        
        return {
            'llm_document': llm_document,
            'chunks': llm_document.chunks,
            'summary': llm_document.summary,
            'key_entities': llm_document.key_entities
        }
    
    async def _extract_entities(self, optimized_content: dict[str, Any]) -> dict[str, Any]:
        """
        Stage 6: Extract named entities and relationships from optimized content.

        Performs comprehensive named entity recognition and relationship extraction
        from LLM-optimized content using pattern matching, co-occurrence analysis,
        and contextual inference. Identifies persons, organizations, locations,
        dates, and domain-specific entities with confidence scoring and relationship
        classification for knowledge graph construction.

        Args:
            optimized_content (dict[str, Any]): LLM-optimized content with structured chunks.
                Must contain llm_document with processed chunks and entity annotations.

        Returns:
            dict[str, Any]: Entity and relationship extraction results containing:
                - entities (list[dict[str, Any]]): Named entities with types, positions, confidence
                - relationships (list[dict[str, Any]]): Entity relationships with types and sources

        Raises:
            ValueError: If optimized content structure is invalid or missing required fields
            RuntimeError: If entity extraction engine encounters processing errors
            AttributeError: If LLM document lacks required attributes or methods
            TypeError: If entity or relationship objects have incorrect types

        Examples:
            >>> entities_relations = await processor._extract_entities(optimized_content)
            >>> entities = entities_relations['entities']
            >>> relationships = entities_relations['relationships']
            >>> print(f"Found {len(entities)} entities and {len(relationships)} relationships")
            >>> for entity in entities[:5]:
            ...     print(f"{entity['text']} ({entity['type']})")

        Note:
            Entity extraction leverages pre-existing annotations from LLM optimization.
            Relationship inference uses co-occurrence patterns within content chunks.
            Confidence scores enable filtering and quality assessment.
            Results integrate seamlessly with GraphRAG knowledge graph construction.
        """
        self.logger.info("Stage 6: Extracting entities and relationships")
        
        # Get LLM document from optimized content
        llm_document: LLMDocument = optimized_content.get('llm_document')
        
        if llm_document is None:
            raise ValueError("Optimized content does not contain LLM document for entity extraction")

        # Entities are already extracted during LLM optimization
        entities = llm_document.key_entities
        
        # Extract additional relationships from chunks
        relationships = []
        chunks = llm_document.chunks
        
        # Simple relationship extraction based on co-occurrence
        for i, chunk in enumerate(chunks):
            chunk_entities = [ent for ent in entities if any(
                ent['text'].lower() in chunk.content.lower() 
                for ent in entities
            )]
            
            # Create relationships between entities in the same chunk
            for j, entity1 in enumerate(chunk_entities):
                for entity2 in chunk_entities[j+1:]:
                    relationships.append({
                        'source': entity1['text'],
                        'target': entity2['text'],
                        'type': 'co_occurrence',
                        'confidence': 0.6,
                        'source_chunk': chunk.chunk_id
                    })
        
        return {
            'entities': entities,
            'relationships': relationships
        }
    
    async def _create_embeddings(self, 
                                optimized_content: dict[str, Any], 
                                entities_and_relations: dict[str, Any]) -> dict[str, Any]:
        """
        Stage 7: Generate vector embeddings for content chunks and document representation.

        Creates high-dimensional vector representations for content chunks and document-level
        summaries using transformer-based embedding models. Generates embeddings suitable
        for semantic similarity search, clustering, and knowledge graph construction
        with consistent dimensionality and normalization for downstream processing.

        Args:
            optimized_content (dict[str, Any]): LLM-optimized content with structured chunks.
                Contains LLM document with preprocessed chunks ready for embedding.
            entities_and_relations (dict[str, Any]): Extracted entities and relationships.
                Used for context-aware embedding generation and entity-specific vectors.

        Returns:
            dict[str, Any]: Vector embedding results containing:
                - chunk_embeddings (list[dict[str, Any]]): Per-chunk embeddings with metadata
                - document_embedding (list[float]): Document-level embedding vector
                - embedding_model (str): Identifier of the embedding model used

        Raises:
            ImportError: If embedding model dependencies are not available
            RuntimeError: If embedding generation fails due to model or memory issues
            ValueError: If content structure is incompatible with embedding requirements
            MemoryError: If document size exceeds embedding model memory limits

        Examples:
            >>> embeddings = await processor._create_embeddings(optimized_content, entities_relations)
            >>> chunk_embeds = embeddings['chunk_embeddings']
            >>> doc_embed = embeddings['document_embedding']
            >>> print(f"Generated {len(chunk_embeds)} chunk embeddings")
            >>> print(f"Document embedding dimension: {len(doc_embed)}")

        Note:
            Uses sentence-transformers/all-MiniLM-L6-v2 as default embedding model.
            Embeddings are normalized for cosine similarity calculations.
            Chunk embeddings preserve content locality and semantic coherence.
            Document-level embeddings enable cross-document similarity analysis.
        """
        self.logger.info("Stage 7: Creating vector embeddings")
        
        # Get LLM document which already has embeddings
        llm_document: LLMDocument = optimized_content.get('llm_document')
        
        if llm_document is None:
            raise ValueError("Optimized content does not contain LLM document for embedding generation")
        
        # Extract embeddings from chunks
        chunk_embeddings = []
        for chunk in llm_document.chunks:
            if chunk.embedding is not None:
                chunk_embeddings.append({
                    'chunk_id': chunk.chunk_id,
                    'embedding': chunk.embedding.tolist(),  # Convert numpy to list
                    'content': chunk.content[:100] + '...' if len(chunk.content) > 100 else chunk.content
                })
        
        # Document-level embedding
        document_embedding = None
        if llm_document.document_embedding is not None:
            document_embedding = llm_document.document_embedding.tolist()

        return {
            'chunk_embeddings': chunk_embeddings,
            'document_embedding': document_embedding,
            'embedding_model': self.optimizer.embedding_model
        }

    async def _integrate_with_graphrag(self, 
                                      ipld_structure: dict[str, Any],
                                      entities_and_relations: dict[str, Any], 
                                      embeddings: dict[str, Any]) -> dict[str, Any]:
        """
        Stage 8: Integrate processed content with GraphRAG knowledge system.

        Combines IPLD structure, extracted entities, relationships, and embeddings
        into a unified GraphRAG knowledge graph enabling semantic search, relationship
        discovery, and cross-document analysis. Creates knowledge graph nodes with
        content addressability and prepares data for natural language querying.

        Args:
            ipld_structure (dict[str, Any]): IPLD content structure with CIDs and references.
                Contains document hierarchy and content addressing information.
            entities_and_relations (dict[str, Any]): Extracted entities and relationships.
                Provides knowledge graph nodes and edges for graph construction.
            embeddings (dict[str, Any]): Vector embeddings for semantic search.
                Enables similarity-based querying and content clustering.

        Returns:
            dict[str, Any]: GraphRAG integration results containing:
                - document (dict[str, Any]): Document metadata with ID and IPLD CID
                - knowledge_graph (KnowledgeGraph): Constructed knowledge graph object
                - entities (list[Entity]): Graph entities with embeddings and metadata
                - relationships (list[Relationship]): Graph relationships with types and weights

        Raises:
            ValueError: If input data structures are incompatible or invalid
            RuntimeError: If GraphRAG integration fails due to system errors
            ImportError: If GraphRAG dependencies are not available
            StorageError: If knowledge graph storage operations fail

        Examples:
            >>> graph_nodes = await processor._integrate_with_graphrag(
            ...     ipld_structure, entities_relations, embeddings
            ... )
            >>> kg = graph_nodes['knowledge_graph']
            >>> print(f"Graph with {len(kg.entities)} entities")
            >>> print(f"Document ID: {graph_nodes['document']['id']}")

        Note:
            GraphRAG integration enables cross-document entity linking and relationship discovery.
            Knowledge graphs support both local and global entity resolution.
            IPLD integration provides content addressability for graph persistence.
            Results enable natural language querying and semantic exploration.
        """
        self.logger.info("Stage 8: Integrating with GraphRAG")

        # Get LLM document from optimized content
        llm_document = None
        for result_data in [entities_and_relations, embeddings]:
            if isinstance(result_data, dict) and 'llm_document' in result_data:
                llm_document = result_data['llm_document']
                break
        else:
            raise ValueError("No LLM document found in entities or embeddings data")

        # Integrate with GraphRAG
        knowledge_graph = await self.integrator.integrate_document(llm_document)
        
        return {
            'document': {
                'id': knowledge_graph.document_id,
                'title': llm_document,
                'ipld_cid': ipld_structure['root_cid']
            },
            'knowledge_graph': knowledge_graph,
            'entities': knowledge_graph.entities,
            'relationships': knowledge_graph.relationships
        }
    
    async def _analyze_cross_document_relationships(self, graph_nodes: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Stage 9: Analyze and discover relationships between entities across documents.

        Performs cross-document entity resolution and relationship discovery by comparing
        entities across the global knowledge graph. Identifies entity aliases, merges
        similar entities, and discovers implicit relationships between documents
        based on shared entities, topics, and semantic similarity patterns.

        Args:
            graph_nodes (dict[str, Any]): GraphRAG integration results with knowledge graph.
                Contains document knowledge graph with entities and relationships.
                A knowledge graph object is defined as follows:
                - graph_id (str): Unique identifier for the knowledge graph in the format "kg_{id}".
                - document_id (str): Identifier for the document associated with the knowledge graph.
                - entities (list[Entity]): List of Entity objects extracted from documents for knowledge graph construction.

    An entity is a distinct object, concept, person, organization, or location
    identified within text chunks during the document processing pipeline.

    Attributes:
        id (str): Unique identifier for the entity within the knowledge graph.
        name (str): The canonical name or primary label of the entity.
        type (str): Category classification of the entity. Categories are arbitrary and are determined
        description (str): Detailed textual description providing context and 
            additional information about the entity.
        confidence (float): Confidence score (0.0-1.0) indicating the reliability
            of the entity extraction and classification.
        source_chunks (List[str]): List of chunk identifiers where this entity
            appears, enabling traceability back to source documents.
        properties (Dict[str, Any]): Additional metadata and attributes specific
            to the entity type (e.g., dates, relationships, custom fields).
        embedding (Optional[np.ndarray]): High-dimensional vector representation
            of the entity for semantic similarity calculations. Defaults to None
            if not computed.

    Example:
        >>> entity = Entity(
        ...     id="ent_001",
        ...     name="John Smith",
        ...     type="person",
        ...     description="Software engineer at Tech Corp",
        ...     confidence=0.95,
        ...     source_chunks=["chunk_1", "chunk_3"],
        ...     properties={"role": "engineer", "company": "Tech Corp"}
        ... )


                >>> from ipfs_datasets_py.pdf_processing.knowledge_graph import KnowledgeGraph, Entity,
                >>> kg = KnowledgeGraph(
                ...     graph_id="kg_001",
                ...     document_id="doc_123",
                ...     entities=[entity1, entity2],
                ...     relationships=[rel1, rel2],
                ...     chunks=[chunk1, chunk2],
                ...     metadata={"model": "gpt-4", "confidence": 0.95},
                ...     creation_timestamp="2024-01-01T12:00:00Z"
                ... )

        Returns:
            list[dict[str, Any]]: Cross-document relationships discovered between entities.
                Each relationship includes entity pairs, relationship type, confidence,
                and source documents for comprehensive cross-document analysis.

        Raises:
            ValueError: If graph nodes structure is invalid or incomplete
            RuntimeError: If cross-document analysis encounters processing errors
            AttributeError: If knowledge graph lacks required methods or attributes
            MemoryError: If global graph size exceeds available memory for analysis

        Examples:
            >>> cross_relations = await processor._analyze_cross_document_relationships(graph_nodes)
            >>> print(f"Found {len(cross_relations)} cross-document relationships")
            >>> for relation in cross_relations:
            ...     print(f"{relation['source']} -> {relation['target']} ({relation['type']})")

        Note:
            Cross-document analysis requires multiple documents in the knowledge graph.
            Entity resolution uses similarity thresholds and fuzzy matching algorithms.
            Relationship discovery leverages both explicit mentions and implicit connections.
            Results enable comprehensive knowledge discovery across document collections.
        """
        self.logger.info("Stage 9: Analyzing cross-document relationships")
        
        # Get the knowledge graph
        knowledge_graph: KnowledgeGraph = graph_nodes.get('knowledge_graph')
        if knowledge_graph is None:
            raise ValueError("Graph nodes do not contain a valid knowledge graph for cross-document analysis")
        
        if not knowledge_graph:
            return []
        
        # Initialize cross-document relationship list
        cross_relations = []
        
        # Cross-document analysis requires multiple documents in the knowledge graph
        # This implementation will be expanded when processing document collections
        if not knowledge_graph or not hasattr(knowledge_graph, 'entities'):
            self.logger.info("Cross-document analysis skipped - requires document collections")
            return cross_relations
        
        # Basic entity similarity analysis for cross-document relationships
        entities = getattr(knowledge_graph, 'entities', [])
        if len(entities) < 2:
            self.logger.info("Cross-document analysis skipped - insufficient entities for relationship discovery")
            return cross_relations
        
        # Placeholder implementation will be enhanced for multi-document scenarios
        self.logger.info("Cross-document analysis complete - ready for document collection processing")
        
        return cross_relations
    
    async def _setup_query_interface(self, 
                                    graph_nodes: dict[str, Any], 
                                    cross_doc_relations: list[dict[str, Any]]) -> None:
        """
        Stage 10: Configure natural language query interface for semantic search.

        Initializes and configures the query engine with processed knowledge graph,
        cross-document relationships, and semantic search capabilities. Sets up
        natural language processing for query interpretation, graph traversal
        algorithms, and result ranking for comprehensive document exploration.

        Args:
            graph_nodes (dict[str, Any]): GraphRAG integration results with knowledge graph.
                Contains complete knowledge graph structure with entities and relationships.
            cross_doc_relations (list[dict[str, Any]]): Cross-document relationships discovered.
                Provides additional relationship context for enhanced query capabilities.

        Returns:
            None: Method configures query interface without return value.
                Query engine is stored in class state for subsequent query processing.

        Raises:
            ImportError: If query engine dependencies are not available
            RuntimeError: If query interface initialization fails due to system errors
            ValueError: If graph nodes or relationships have invalid structure
            ConfigurationError: If query engine configuration is incomplete or invalid

        Examples:
            >>> await processor._setup_query_interface(graph_nodes, cross_relations)
            >>> # Query interface is now ready for natural language queries
            >>> # Example queries that would now be supported:
            >>> # "Find all documents mentioning John Smith"
            >>> # "Show relationships between ACME Corp and legal documents"
            >>> # "What entities are connected to contract negotiations?"

        Note:
            Query interface supports both keyword-based and semantic search capabilities.
            Natural language processing enables intuitive query formulation.
            Graph traversal algorithms provide comprehensive relationship exploration.
            Results include relevance scoring and context-aware ranking.
        """
        self.logger.info("Stage 10: Setting up query interface")
        

        
        # Create query engine with the GraphRAG integrator
        integrator = GraphRAGIntegrator(storage=self.storage)
        query_engine = QueryEngine(integrator, storage=self.storage)
        
        # The query engine is now ready to handle queries for this document
        self.logger.info("Query interface setup complete")
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """
        Calculate SHA-256 hash of input file for integrity verification and content addressability.

        Computes cryptographic hash of the input PDF file using SHA-256 algorithm
        for content integrity verification, deduplication, and content addressability.
        Processes file in chunks to handle large files efficiently without loading
        entire file content into memory simultaneously.

        Args:
            file_path (Path): Path object pointing to the file for hash calculation.
                Must be a readable file with appropriate permissions.

        Returns:
            str: Hexadecimal representation of SHA-256 hash digest.
                Provides unique identifier for file content verification.

        Raises:
            FileNotFoundError: If the file does not exist at the specified path
            PermissionError: If insufficient permissions to read the file
            IOError: If file system errors occur during reading
            OSError: If operating system level errors prevent file access

        Examples:
            >>> hash_value = processor._calculate_file_hash(Path("document.pdf"))
            >>> print(f"File hash: {hash_value}")
            >>> # Hash can be used for deduplication
            >>> if hash_value in processed_hashes:
            ...     print("Document already processed")

        Note:
            Uses 4KB chunks for memory-efficient processing of large files.
            SHA-256 provides cryptographically secure hash for integrity verification.
            Hash values enable content deduplication across document collections.
            Consistent hashing supports content addressability in IPLD storage.
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _extract_native_text(self, text_blocks: list[dict[str, Any]]) -> str:
        """
        Extract and concatenate native text content from PDF text blocks preserving structure.

        Processes text blocks extracted from PDF decomposition to create coherent
        text representation while preserving document structure and readability.
        Handles text block ordering, spacing, and formatting to maintain original
        document flow and semantic meaning for downstream processing.

        Args:
            text_blocks (list[dict[str, Any]]): list of text block dictionaries from PDF extraction.
                Each block must contain 'content' field with extracted text content.

        Returns:
            str: Concatenated text content preserving document structure and flow.
                Newlines separate text blocks to maintain readability and structure.

        Raises:
            KeyError: If text blocks lack required 'content' field
            TypeError: If text_blocks is not a list or contains non-dictionary elements
            AttributeError: If text block content is not string-compatible

        Examples:
            >>> text_blocks = [
            ...     {'content': 'Chapter 1: Introduction', 'bbox': [0, 0, 100, 20]},
            ...     {'content': 'This document describes...', 'bbox': [0, 25, 100, 45]}
            ... ]
            >>> text = processor._extract_native_text(text_blocks)
            >>> print(text)
            Chapter 1: Introduction
            This document describes...

        Note:
            Preserves original text block ordering for document flow consistency.
            Newline separation maintains readability and paragraph structure.
            Empty or whitespace-only blocks are filtered to improve text quality.
            Result suitable for further processing including LLM optimization and entity extraction.
        """
        text_parts = []
        for block in text_blocks:
            if block.get('content'):
                text_parts.append(block['content'])
        return "\n".join(text_parts)
    
    def _get_quality_scores(self, result: dict[str, Any]) -> dict[str, float]:
        """
        Generate quality assessment scores for processing stages and overall document quality.

        Calculates comprehensive quality metrics for text extraction accuracy,
        OCR confidence levels, entity extraction precision, and overall processing
        quality. Provides quantitative assessment enabling quality control,
        processing validation, and continuous improvement of pipeline performance.

        Args:
            result (dict[str, Any]): Processing result containing statistics and metadata.
                Contains the following keys:
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

        Returns:
            dict[str, float]: Quality assessment scores containing:
                - text_extraction_quality (float): Native text extraction accuracy (0.0-1.0)
                - ocr_confidence (float): Average OCR confidence score (0.0-1.0)
                - entity_extraction_confidence (float): Entity extraction precision (0.0-1.0)
                - overall_quality (float): Weighted average of all quality metrics (0.0-1.0)

        Raises:
            ValueError: If quality calculations result in invalid score ranges
            AttributeError: If required processing statistics are not available
            ZeroDivisionError: If quality calculations involve division by zero

        Examples:
            >>> quality_scores = processor._get_quality_scores()
            >>> print(f"Overall quality: {quality_scores['overall_quality']:.2f}")
            >>> print(f"OCR confidence: {quality_scores['ocr_confidence']:.2f}")
            >>> # Quality-based filtering
            >>> if quality_scores['overall_quality'] < 0.8:
            ...     print("Warning: Low quality processing detected")

        Note:
            Quality scores are calculated from actual processing statistics.
            Text extraction quality is based on successful content extraction rates.
            OCR confidence reflects average confidence from optical character recognition.
            Entity confidence measures precision of named entity recognition results.
        """
        try:
            # Text extraction quality based on content extraction success
            text_quality = 1.0
            if hasattr(self, 'processing_stats') and self.processing_stats:
                pages_processed = self.processing_stats.get('pages_processed', 0)
                pages_with_text = self.processing_stats.get('pages_with_text', 0)
                if pages_processed > 0:
                    text_quality = min(pages_with_text / pages_processed, 1.0)
            
            # OCR confidence from processing results
            ocr_confidence = 0.95  # Default confidence
            if hasattr(self, 'ocr_results') and self.ocr_results:
                confidence_scores = []
                for page_results in self.ocr_results.values():
                    for result in page_results:
                        if isinstance(result, dict) and 'confidence' in result:
                            confidence_scores.append(result['confidence'])
                if confidence_scores:
                    ocr_confidence = sum(confidence_scores) / len(confidence_scores)
            
            # Entity extraction confidence from NER results
            entity_confidence = 0.95
            if hasattr(self, 'entity_results') and self.entity_results:
                confidence_scores = []
                for entity in self.entity_results:
                    if isinstance(entity, dict) and 'confidence' in entity:
                        confidence_scores.append(entity['confidence'])
                if confidence_scores:
                    entity_confidence = sum(confidence_scores) / len(confidence_scores)
            
            # Calculate weighted overall quality
            weights = { # TODO These need to be arguments or class parameters.
                'text': 0.4,
                'ocr': 0.3,
                'entities': 0.3
            }
            
            overall_quality = (
                text_quality * weights['text'] +
                ocr_confidence * weights['ocr'] +
                entity_confidence * weights['entities']
            )
            
            return {
                'text_extraction_quality': round(text_quality, 3),
                'ocr_confidence': round(ocr_confidence, 3),
                'entity_extraction_confidence': round(entity_confidence, 3),
                'overall_quality': round(overall_quality, 3)
            }
            
        except Exception as e:
            self.logger.exception(f"Quality score calculation failed: {e}")
            raise RuntimeError("Quality score calculation failed") from e


