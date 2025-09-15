"""
IPFS Datasets Python

A unified interface for data processing and distribution across decentralized networks
with automated dependency installation for full functionality.

NEW: Caselaw Access Project GraphRAG integration for legal document search and analysis.
"""

__version__ = "0.2.0"

# Import automated dependency installer
from .auto_installer import get_installer, ensure_module

# Initialize installer with environment configuration
installer = get_installer()

# Main entry points with automated installation
try:
    from .ipfs_datasets import ipfs_datasets_py
    HAVE_IPFS_DATASETS = True
except ImportError:
    HAVE_IPFS_DATASETS = False

# Re-export key functions with automated installation
datasets_module = ensure_module('datasets', 'datasets', required=False)
if datasets_module:
    from datasets import load_dataset
    HAVE_LOAD_DATASET = True
else:
    HAVE_LOAD_DATASET = False
    load_dataset = None


# Use conditional imports to handle missing modules gracefully
try:
    # Core components for Phase 1
    from .ipld.storage import IPLDStorage, IPLDSchema
    from .ipld.optimized_codec import (
        OptimizedEncoder, OptimizedDecoder, BatchProcessor,
        create_batch_processor, optimize_node_structure
    )
    HAVE_IPLD = True
except ImportError:
    HAVE_IPLD = False

try:
    from .dataset_serialization import (
        DatasetSerializer, GraphDataset, GraphNode, VectorAugmentedGraphDataset,
    )
    HAVE_DATASET_SERIALIZATION = True
except ImportError:
    HAVE_DATASET_SERIALIZATION = False

try:
    from .dataset_manager import DatasetManager
    HAVE_DATASET_MANAGER = True
except ImportError:
    HAVE_DATASET_MANAGER = False

try:
    from .car_conversion import DataInterchangeUtils
    HAVE_CAR_CONVERSION = True
except ImportError:
    HAVE_CAR_CONVERSION = False

try:
    from .unixfs_integration import UnixFSHandler, FixedSizeChunker, RabinChunker
    HAVE_UNIXFS = True
except ImportError:
    HAVE_UNIXFS = False

try:
    from .web_archive import WebArchiveProcessor
    HAVE_WEB_ARCHIVE = True
except ImportError:
    HAVE_WEB_ARCHIVE = False

try:
    from .vector_tools import VectorSimilarityCalculator
    HAVE_VECTOR_TOOLS = True
except ImportError:
    HAVE_VECTOR_TOOLS = False

try:
    from . import search
    HAVE_SEARCH = True
except ImportError:
    HAVE_SEARCH = False

try:
    # Import new embeddings and vector store capabilities
    from .embeddings.core import IpfsEmbeddings, PerformanceMetrics
    from .embeddings.schema import EmbeddingModel, EmbeddingRequest, EmbeddingResponse
    from .embeddings.chunker import TextChunker, ChunkingStrategy
    HAVE_EMBEDDINGS = True
except ImportError:
    HAVE_EMBEDDINGS = False

try:
    # Import vector store implementations
    from .vector_stores.base import BaseVectorStore
    from .vector_stores.qdrant_store import QdrantVectorStore
    from .vector_stores.elasticsearch_store import ElasticsearchVectorStore
    from .vector_stores.faiss_store import FaissVectorStore
    HAVE_VECTOR_STORES = True
except ImportError:
    HAVE_VECTOR_STORES = False

# MCP Tools availability
try:
    # from .mcp_server.tools.embedding_tools import embedding_generation
    from .mcp_server.tools.vector_tools import create_vector_index
    HAVE_MCP_TOOLS = True
except ImportError:
    HAVE_MCP_TOOLS = False

# FastAPI service availability  
try:
    from .fastapi_service import app as fastapi_app
    HAVE_FASTAPI = True
except ImportError:
    HAVE_FASTAPI = False

try:
    from .graphrag_processor import GraphRAGProcessor, MockGraphRAGProcessor
    HAVE_GRAPHRAG_PROCESSOR = True
except ImportError:
    HAVE_GRAPHRAG_PROCESSOR = False

try:
    from .ipfs_knn_index import IPFSKnnIndex
    HAVE_KNN = True
except ImportError:
    HAVE_KNN = False

# RAG optimizer components
from .rag.rag_query_optimizer_minimal import GraphRAGQueryOptimizer, GraphRAGQueryStats

try:
    from .rag.rag_query_optimizer import (
        QueryRewriter,
        QueryBudgetManager,
        UnifiedGraphRAGQueryOptimizer
    )
except ImportError as e:
    import warnings
    warnings.warn(f"Advanced RAG query optimizer unavailable due to missing dependencies: {e}")
    # Provide minimal fallbacks
    QueryRewriter = None
    QueryBudgetManager = None
    UnifiedGraphRAGQueryOptimizer = None


try:
    from .knowledge_graph_extraction import KnowledgeGraph, KnowledgeGraphExtractor, Entity, Relationship
    HAVE_KG_EXTRACTION = True
except ImportError:
    HAVE_KG_EXTRACTION = False

# LLM Integration Components
try:
    from .llm.llm_interface import (
        LLMInterface, MockLLMInterface, LLMConfig, PromptTemplate,
        LLMInterfaceFactory, GraphRAGPromptTemplates
    )
    HAVE_LLM_INTERFACE = True
except ImportError as e:
    import warnings
    warnings.warn(f"LLM interface unavailable due to missing dependencies: {e}")
    HAVE_LLM_INTERFACE = False
    # Provide minimal fallbacks
    LLMInterface = None
    MockLLMInterface = None
    LLMConfig = None
    PromptTemplate = None
    LLMInterfaceFactory = None
    GraphRAGPromptTemplates = None

try:
    from .llm.llm_graphrag import GraphRAGLLMProcessor, ReasoningEnhancer
    HAVE_LLM_GRAPHRAG = True
except ImportError as e:
    import warnings
    warnings.warn(f"GraphRAG LLM processor unavailable due to missing dependencies: {e}")
    HAVE_LLM_GRAPHRAG = False
    GraphRAGLLMProcessor = None
    ReasoningEnhancer = None

try:
    from ipfs_datasets_py.graphrag_integration import enhance_dataset_with_llm
    HAVE_GRAPHRAG_INTEGRATION = True
except ImportError:
    HAVE_GRAPHRAG_INTEGRATION = False

# Security and Audit Components
try:
    from ipfs_datasets_py.audit import (
        AuditLogger, AuditEvent, AuditLevel, AuditCategory,
        IntrusionDetection, SecurityAlertManager,
        AdaptiveSecurityManager, ResponseRule, ResponseAction
    )
    HAVE_AUDIT = True
except ImportError:
    HAVE_AUDIT = False

# Check for dependencies
try:
    import ipfshttpclient
    HAVE_IPFS = True
except ImportError:
    HAVE_IPFS = False

try:
    import ipld_car
    HAVE_IPLD_CAR = True
except ImportError:
    HAVE_IPLD_CAR = False

try:
    from ipld_dag_pb import PBNode, PBLink
    HAVE_IPLD_DAG_PB = True
except ImportError:
    HAVE_IPLD_DAG_PB = False

try:
    import pyarrow as pa
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False

try:
    from datasets import Dataset
    HAVE_HUGGINGFACE = True
except ImportError:
    HAVE_HUGGINGFACE = False

try:
    import archivenow
    HAVE_ARCHIVENOW = True
except ImportError:
    HAVE_ARCHIVENOW = False

try:
    import ipwb
    HAVE_IPWB = True
except ImportError:
    HAVE_IPWB = False

# PDF Processing Components with conditional automated dependency installation
import os
if installer.auto_install and os.environ.get('IPFS_DATASETS_AUTO_INSTALL', 'false').lower() == 'true':
    print("🔧 Installing PDF processing dependencies...")
    from .auto_installer import install_for_component
    install_for_component('pdf')
    install_for_component('ocr')

try:
    from .pdf_processing import PDFProcessor
    HAVE_PDF_PROCESSOR = True
    if installer.verbose:
        print("✅ PDFProcessor successfully installed and available")
except ImportError as e:
    if installer.verbose:
        print(f"⚠️ PDFProcessor installation failed: {e}")
    PDFProcessor = None
    HAVE_PDF_PROCESSOR = False

try:
    from .pdf_processing import MultiEngineOCR
    HAVE_MULTI_ENGINE_OCR = True
    if installer.verbose:
        print("✅ MultiEngineOCR successfully installed and available")
except ImportError as e:
    if installer.verbose:
        print(f"⚠️ MultiEngineOCR installation failed: {e}")
    MultiEngineOCR = None
    HAVE_MULTI_ENGINE_OCR = False

try:
    from .pdf_processing import LLMOptimizer
    HAVE_LLM_OPTIMIZER = True
    if installer.verbose:
        print("✅ LLMOptimizer successfully installed and available")
except ImportError as e:
    if installer.verbose:
        print(f"⚠️ LLMOptimizer installation failed: {e}")
    LLMOptimizer = None
    HAVE_LLM_OPTIMIZER = False

try:
    from .pdf_processing import GraphRAGIntegrator
    HAVE_GRAPHRAG_INTEGRATOR = True
    if installer.verbose:
        print("✅ GraphRAGIntegrator successfully installed and available")
except ImportError as e:
    if installer.verbose:
        print(f"⚠️ GraphRAGIntegrator installation failed: {e}")
    GraphRAGIntegrator = None
    HAVE_GRAPHRAG_INTEGRATOR = False

try:
    from .pdf_processing import QueryEngine
    HAVE_QUERY_ENGINE = True
    if installer.verbose:
        print("✅ QueryEngine successfully installed and available")
except ImportError as e:
    if installer.verbose:
        print(f"⚠️ QueryEngine installation failed: {e}")
    QueryEngine = None
    HAVE_QUERY_ENGINE = False

try:
    from .pdf_processing import BatchProcessor
    HAVE_BATCH_PROCESSOR = True
    if installer.verbose:
        print("✅ BatchProcessor successfully installed and available")
except ImportError as e:
    if installer.verbose:
        print(f"⚠️ BatchProcessor installation failed: {e}")
    BatchProcessor = None
    HAVE_BATCH_PROCESSOR = False

HAVE_PDF_PROCESSING = (HAVE_PDF_PROCESSOR or HAVE_MULTI_ENGINE_OCR or 
                       HAVE_LLM_OPTIMIZER or HAVE_GRAPHRAG_INTEGRATOR or 
                       HAVE_QUERY_ENGINE or HAVE_BATCH_PROCESSOR)

# Define base exports that should always be available
__all__ = [
    # Original exports
    's3_kit',
    'test_fio', 
    'config',
]

# Conditionally add exports based on available components
if HAVE_IPLD:
    __all__.extend([
        'IPLDStorage',
        'IPLDSchema',
        'OptimizedEncoder',
        'OptimizedDecoder',
        'BatchProcessor',
        'create_batch_processor',
        'optimize_node_structure'
    ])

if HAVE_DATASET_SERIALIZATION:
    __all__.extend([
        'DatasetSerializer',
        'GraphDataset',
        'GraphNode',
        'VectorAugmentedGraphDataset'
    ])

if HAVE_DATASET_MANAGER:
    __all__.extend(['DatasetManager'])

if HAVE_CAR_CONVERSION:
    __all__.extend(['DataInterchangeUtils'])

if HAVE_UNIXFS:
    __all__.extend([
        'UnixFSHandler',
        'FixedSizeChunker',
        'RabinChunker'
    ])

if HAVE_WEB_ARCHIVE:
    __all__.extend(['WebArchiveProcessor'])

if HAVE_VECTOR_TOOLS:
    __all__.extend(['VectorSimilarityCalculator'])

if HAVE_SEARCH:
    __all__.extend(['search'])

if HAVE_EMBEDDINGS:
    __all__.extend([
        'IpfsEmbeddings',
        'PerformanceMetrics',
        'EmbeddingModel', 
        'EmbeddingRequest',
        'EmbeddingResponse',
        'TextChunker',
        'ChunkingStrategy'
    ])

if HAVE_VECTOR_STORES:
    __all__.extend([
        'BaseVectorStore',
        'QdrantVectorStore',
        'ElasticsearchVectorStore',
        'FaissVectorStore'
    ])

if HAVE_GRAPHRAG_PROCESSOR:
    __all__.extend(['GraphRAGProcessor', 'MockGraphRAGProcessor'])

if HAVE_KNN:
    __all__.extend(['IPFSKnnIndex'])

# Always export RAG components  
__all__.extend([
    'GraphRAGQueryOptimizer',
    'GraphRAGQueryStats',
    'QueryRewriter',
    'QueryBudgetManager', 
    'UnifiedGraphRAGQueryOptimizer'
])

if HAVE_KG_EXTRACTION:
    __all__.extend([
        'KnowledgeGraph',
        'KnowledgeGraphExtractor',
        'Entity',
        'Relationship'
    ])

# Always export LLM components
__all__.extend([
    'LLMInterface',
    'MockLLMInterface', 
    'LLMConfig',
    'PromptTemplate',
    'LLMInterfaceFactory',
    'GraphRAGPromptTemplates',
    'GraphRAGLLMProcessor',
    'ReasoningEnhancer'
])

if HAVE_GRAPHRAG_INTEGRATION:
    __all__.extend(['enhance_dataset_with_llm'])

if HAVE_AUDIT:
    __all__.extend([
        'AuditLogger',
        'AuditEvent',
        'AuditLevel',
        'AuditCategory',
        'IntrusionDetection',
        'SecurityAlertManager',
        'AdaptiveSecurityManager',
        'ResponseRule',
        'ResponseAction'
    ])

if HAVE_PDF_PROCESSING:
    __all__.extend([
        'PDFProcessor', 
        'MultiEngineOCR', 
        'LLMOptimizer', 
        'GraphRAGIntegrator', 
        'QueryEngine', 
        'BatchProcessor'
    ])

# Web Text Extraction
try:
    from .web_text_extractor import (
        WebTextExtractor,
        WebTextExtractionResult,
        extract_website_text,
        extract_multiple_websites,
        save_website_text
    )
    HAVE_WEB_TEXT_EXTRACTOR = True
    __all__.extend([
        'WebTextExtractor',
        'WebTextExtractionResult', 
        'extract_website_text',
        'extract_multiple_websites',
        'save_website_text'
    ])
except ImportError as e:
    HAVE_WEB_TEXT_EXTRACTOR = False
    WebTextExtractor = None
    if installer.verbose:
        warnings.warn(f"Web text extractor unavailable due to missing dependencies: {e}")

# Proper module aliasing for backward compatibility
from . import llm
from . import rag

# Direct aliases without polluting sys.modules
try:
    llm_interface = llm.llm_interface
except AttributeError:
    llm_interface = None

try:
    llm_graphrag = llm.llm_graphrag
except AttributeError:
    llm_graphrag = None

try:
    rag_query_optimizer = rag.rag_query_optimizer
except AttributeError:
    rag_query_optimizer = None

# Caselaw Access Project GraphRAG Integration
try:
    from .caselaw_dataset import CaselawDatasetLoader, load_caselaw_dataset
    from .caselaw_graphrag import (
        CaselawGraphRAGProcessor, LegalEntityExtractor, 
        LegalRelationshipMapper, CaselawKnowledgeGraph,
        create_caselaw_graphrag_processor
    )
    from .caselaw_dashboard import CaselawDashboard, create_caselaw_dashboard
    HAVE_CASELAW_INTEGRATION = True
    
    # Add to __all__ exports
    __all__.extend([
        'CaselawDatasetLoader', 'load_caselaw_dataset',
        'CaselawGraphRAGProcessor', 'LegalEntityExtractor',
        'LegalRelationshipMapper', 'CaselawKnowledgeGraph', 
        'create_caselaw_graphrag_processor',
        'CaselawDashboard', 'create_caselaw_dashboard'
    ])
    
except ImportError as e:
    HAVE_CASELAW_INTEGRATION = False
    if installer.verbose:
        warnings.warn(f"Caselaw GraphRAG integration unavailable due to missing dependencies: {e}")
    
    # Provide fallbacks
    CaselawDatasetLoader = None
    load_caselaw_dataset = None
    CaselawGraphRAGProcessor = None
    LegalEntityExtractor = None
    LegalRelationshipMapper = None
    CaselawKnowledgeGraph = None
    create_caselaw_graphrag_processor = None
    CaselawDashboard = None
    create_caselaw_dashboard = None