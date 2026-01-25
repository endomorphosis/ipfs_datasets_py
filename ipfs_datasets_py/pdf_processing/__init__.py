"""
PDF Processing Pipeline Module

A comprehensive PDF processing pipeline that follows the order:
PDF Input → Decomposition → IPLD Structuring → OCR Processing → 
LLM Optimization → Entity Extraction → Vector Embedding → 
IPLD GraphRAG Integration → Cross-Document Analysis → Query Interface

This module provides:
- Complete PDF decomposition and analysis
- Multi-engine OCR with intelligent fallback
- LLM-optimized content chunking and summarization
- Knowledge graph extraction and IPLD integration
- Advanced querying and cross-document analysis
- Batch processing capabilities
"""

# Main components with safe imports
try:
    from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
    HAVE_PDF_PROCESSOR = True
except ImportError as e:
    print(f"Warning: PDFProcessor not available: {e}")
    HAVE_PDF_PROCESSOR = False
    PDFProcessor = None  # type: ignore[assignment]

try:
    from ipfs_datasets_py.pdf_processing.ocr_engine import MultiEngineOCR, SuryaOCR, TesseractOCR, EasyOCR
    HAVE_OCR_ENGINE = True
except ImportError as e:
    print(f"Warning: OCR engines not available: {e}")
    HAVE_OCR_ENGINE = False
    MultiEngineOCR = None  # type: ignore[assignment]
    SuryaOCR = None  # type: ignore[assignment]
    TesseractOCR = None  # type: ignore[assignment]
    EasyOCR = None  # type: ignore[assignment]

try:
    from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMDocument, LLMChunk
    HAVE_LLM_OPTIMIZER = True
except ImportError as e:
    print(f"Warning: LLM optimizer not available: {e}")
    HAVE_LLM_OPTIMIZER = False
    LLMOptimizer = None  # type: ignore[assignment]
    LLMDocument = None  # type: ignore[assignment]
    LLMChunk = None  # type: ignore[assignment]

try:
    from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph, Entity, Relationship
    HAVE_GRAPHRAG_INTEGRATOR = True
except ImportError as e:
    print(f"Warning: GraphRAG integrator not available: {e}")
    HAVE_GRAPHRAG_INTEGRATOR = False
    GraphRAGIntegrator = None  # type: ignore[assignment]
    KnowledgeGraph = None  # type: ignore[assignment]
    Entity = None  # type: ignore[assignment]
    Relationship = None  # type: ignore[assignment]

try:
    from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine, QueryResult, QueryResponse
    HAVE_QUERY_ENGINE = True
except ImportError as e:
    print(f"Warning: Query engine not available: {e}")
    HAVE_QUERY_ENGINE = False
    QueryEngine = None  # type: ignore[assignment]
    QueryResult = None  # type: ignore[assignment]
    QueryResponse = None  # type: ignore[assignment]

try:
    from ipfs_datasets_py.pdf_processing.batch_processor import BatchProcessor, ProcessingJob, BatchStatus
    HAVE_BATCH_PROCESSOR = True
except ImportError as e:
    print(f"Warning: Batch processor not available: {e}")
    HAVE_BATCH_PROCESSOR = False
    BatchProcessor = None  # type: ignore[assignment]
    ProcessingJob = None  # type: ignore[assignment]
    BatchStatus = None  # type: ignore[assignment]

__all__ = [
    # Core processing
    'PDFProcessor',
    
    # OCR engines
    'MultiEngineOCR',
    'SuryaOCR', 
    'TesseractOCR',
    'EasyOCR',
    
    # LLM optimization
    'LLMOptimizer',
    'LLMDocument',
    'LLMChunk',
    
    # GraphRAG integration
    'GraphRAGIntegrator',
    'KnowledgeGraph',
    'Entity',
    'Relationship',
    
    # Query engine
    'QueryEngine',
    'QueryResult',
    'QueryResponse',
    
    # Batch processing
    'BatchProcessor',
    'ProcessingJob',
    'BatchStatus'
]

# Version information
__version__ = "2.0.0"
__author__ = "IPFS Datasets Team"

# Pipeline configuration
DEFAULT_PIPELINE_CONFIG = {
    'ocr_engines': ['surya', 'tesseract', 'easyocr'],
    'llm_model': 'sentence-transformers/all-MiniLM-L6-v2',
    'max_chunk_size': 2048,
    'chunk_overlap': 200,
    'enable_monitoring': True,
    'enable_audit': True,
    'batch_max_workers': 4
}
