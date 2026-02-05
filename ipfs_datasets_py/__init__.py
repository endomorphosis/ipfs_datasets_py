"""
IPFS Datasets Python

A unified interface for data processing and distribution across decentralized networks
with automated dependency installation for full functionality.
"""

__version__ = "0.2.0"

import os
import warnings

# File type detection
try:
    from .file_detector import FileTypeDetector, DetectionMethod, DetectionStrategy
    HAVE_FILE_DETECTOR = True
except ImportError:
    HAVE_FILE_DETECTOR = False
    FileTypeDetector = None
    DetectionMethod = None
    DetectionStrategy = None

# File conversion (Phase 1: Import & Wrap existing libraries)
try:
    from .file_converter import FileConverter, ConversionResult
    HAVE_FILE_CONVERTER = True
except ImportError:
    HAVE_FILE_CONVERTER = False
    FileConverter = None
    ConversionResult = None

# Import automated dependency installer
from .auto_installer import get_installer, ensure_module

# Initialize installer with environment configuration
installer = get_installer()

# Main entry points with automated installation
try:
    from .ipfs_datasets import ipfs_datasets_py
    # Provide alias for backward compatibility and clearer naming
    IPFSDatasets = ipfs_datasets_py
    HAVE_IPFS_DATASETS = True
except ImportError:
    HAVE_IPFS_DATASETS = False
    ipfs_datasets_py = None
    class _FallbackIPFSDatasets:
        """Fallback IPFSDatasets interface when core dependencies are missing."""

        def __init__(self, *_: object, **__: object) -> None:
            self.status = "initialized"

        def list_datasets(self) -> list:
            """Return an empty dataset list as a safe fallback."""
            return []

        def download_dataset(self, *_: object, **__: object) -> dict:
            """Return a stub response for dataset downloads."""
            return {"status": "success", "dataset": None}

        def upload_dataset(self, *_: object, **__: object) -> dict:
            """Return a stub response for dataset uploads."""
            return {"status": "success"}

    ipfs_datasets_py = _FallbackIPFSDatasets
    IPFSDatasets = _FallbackIPFSDatasets

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

# Import accelerate integration (graceful fallback if not available)
try:
    from .accelerate_integration import (
        is_accelerate_available,
        get_accelerate_status,
        AccelerateManager,
        HAVE_ACCELERATE_MANAGER
    )
    HAVE_ACCELERATE_INTEGRATION = True
except ImportError:
    HAVE_ACCELERATE_INTEGRATION = False
    is_accelerate_available = None
    get_accelerate_status = None
    AccelerateManager = None
    HAVE_ACCELERATE_MANAGER = False

# Optional SyMAI engine router registration
try:
    if os.environ.get("IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        from .utils.symai_ipfs_engine import register_ipfs_symai_engines

        register_ipfs_symai_engines()
except Exception:
    pass

try:
    from .data_transformation.dataset_serialization import (
        DatasetSerializer, GraphDataset, GraphNode, VectorAugmentedGraphDataset,
    )
    HAVE_DATASET_SERIALIZATION = True
except ImportError:
    HAVE_DATASET_SERIALIZATION = False

# Expose the module itself for `from ipfs_datasets_py import dataset_serialization`.
try:
    from .data_transformation import dataset_serialization as dataset_serialization  # type: ignore
except Exception:
    dataset_serialization = None  # type: ignore

try:
    from .dataset_manager import DatasetManager
    HAVE_DATASET_MANAGER = True
except ImportError:
    HAVE_DATASET_MANAGER = False

try:
    from .data_transformation.car_conversion import DataInterchangeUtils
    HAVE_CAR_CONVERSION = True
except ImportError:
    HAVE_CAR_CONVERSION = False

# Expose the module itself for `from ipfs_datasets_py import car_conversion`.
try:
    from .data_transformation import car_conversion as car_conversion  # type: ignore
except Exception:
    car_conversion = None  # type: ignore

# Expose Jsonnet helpers for `from ipfs_datasets_py import jsonnet_utils`.
try:
    from . import jsonnet_utils as jsonnet_utils  # type: ignore
except Exception:
    jsonnet_utils = None  # type: ignore

try:
    from .unixfs_integration import UnixFSHandler, FixedSizeChunker, RabinChunker
    HAVE_UNIXFS = True
except ImportError:
    HAVE_UNIXFS = False

try:
    from .web_archive import WebArchiveProcessor
    from .web_archiving import CommonCrawlSearchEngine, create_search_engine
    HAVE_WEB_ARCHIVE = True
    HAVE_COMMON_CRAWL = True
except ImportError:
    WebArchiveProcessor = None
    CommonCrawlSearchEngine = None
    create_search_engine = None
    HAVE_WEB_ARCHIVE = False
    HAVE_COMMON_CRAWL = False

try:
    from .unified_web_scraper import (
        UnifiedWebScraper,
        ScraperConfig,
        ScraperMethod,
        ScraperResult,
        scrape_url,
        scrape_urls,
        scrape_url_async,
        scrape_urls_async
    )
    HAVE_UNIFIED_SCRAPER = True
except ImportError:
    HAVE_UNIFIED_SCRAPER = False
    UnifiedWebScraper = None
    ScraperConfig = None
    ScraperMethod = None
    ScraperResult = None

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
    from .embeddings.core import IPFSEmbeddings, PerformanceMetrics
    # FIXME All the embeddings models in schema are hallucinated
    from .embeddings.schema import EmbeddingModel, EmbeddingRequest, EmbeddingResponse
    from .embeddings.chunker import Chunker, ChunkingStrategy
    HAVE_EMBEDDINGS = True
except ImportError:
    HAVE_EMBEDDINGS = False

try:
    # Import vector store implementations
    from .vector_stores.base import BaseVectorStore
    from .vector_stores.qdrant_store import QdrantVectorStore
    from .vector_stores.elasticsearch_store import ElasticsearchVectorStore
    from .vector_stores.faiss_store import FAISSVectorStore
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
    from ipfs_datasets_py.integrations.graphrag_integration import enhance_dataset_with_llm
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

# P2P Workflow Scheduler
try:
    from ipfs_datasets_py.p2p_networking.p2p_workflow_scheduler import (
        P2PWorkflowScheduler,
        WorkflowDefinition,
        WorkflowTag,
        MerkleClock,
        FibonacciHeap,
        calculate_hamming_distance,
        get_scheduler
    )
    HAVE_P2P_WORKFLOW_SCHEDULER = True
except ImportError:
    HAVE_P2P_WORKFLOW_SCHEDULER = False
    P2PWorkflowScheduler = None
    WorkflowDefinition = None
    WorkflowTag = None
    MerkleClock = None
    FibonacciHeap = None
    calculate_hamming_distance = None
    get_scheduler = None

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
if (
    installer.auto_install
    and os.environ.get('IPFS_DATASETS_AUTO_INSTALL', 'false').lower() == 'true'
    and os.environ.get('IPFS_DATASETS_INSTALL_ON_IMPORT', 'false').lower() == 'true'
):
    # Import-time installation is opt-in because it can trigger heavyweight optional
    # dependencies (e.g., OCR/ML stacks) and should not break basic imports.
    from .auto_installer import install_for_component
    for _component in ('pdf', 'ocr'):
        try:
            install_for_component(_component)
        except Exception as e:
            import warnings
            warnings.warn(f"Auto-install for component '{_component}' failed during import: {e}")

    if os.environ.get('IPFS_DATASETS_INSTALL_SYMAI_ROUTER', 'false').lower() == 'true':
        try:
            install_for_component('symai_router')
        except Exception as e:
            import warnings
            warnings.warn(f"Auto-install for component 'symai_router' failed during import: {e}")

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

# Add core ipfs_datasets class if available
if HAVE_IPFS_DATASETS:
    __all__.extend([
        'ipfs_datasets_py',
        'IPFSDatasets',  # Alias for backward compatibility
    ])

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

if HAVE_P2P_WORKFLOW_SCHEDULER:
    __all__.extend([
        'P2PWorkflowScheduler',
        'WorkflowDefinition',
        'WorkflowTag',
        'MerkleClock',
        'FibonacciHeap',
        'calculate_hamming_distance',
        'get_scheduler'
    ])

if HAVE_EMBEDDINGS:
    __all__.extend([
        'IPFSEmbeddings',
        'PerformanceMetrics',
        'EmbeddingModel', 
        'EmbeddingRequest',
        'EmbeddingResponse',
        'Chunker',
        'ChunkingStrategy'
    ])

if HAVE_VECTOR_STORES:
    __all__.extend([
        'BaseVectorStore',
        'QdrantVectorStore',
        'ElasticsearchVectorStore',
        'FAISSVectorStore'
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

# Finance Dashboard Tools - Phase 7 Enhancement
try:
    from .mcp_server.tools.finance_data_tools import stock_scrapers
    from .mcp_server.tools.finance_data_tools import news_scrapers
    from .mcp_server.tools.finance_data_tools import finance_theorems
    from .mcp_server.tools.finance_data_tools import graphrag_news_analyzer
    from .mcp_server.tools.finance_data_tools import embedding_correlation
    
    # Software Engineering Tools
    from .mcp_server.tools.software_engineering_tools import (
        github_repository_scraper,
        github_actions_analyzer,
        systemd_log_parser,
        kubernetes_log_analyzer,
        dependency_chain_analyzer,
        dag_workflow_planner,
        gpu_provisioning_predictor,
        error_pattern_detector,
        auto_healing_coordinator,
        software_theorems
    )
    
    # Expose key classes
    StockDataScraper = stock_scrapers.StockDataScraper
    NewsScraperBase = news_scrapers.NewsScraperBase
    FinancialTheoremLibrary = finance_theorems.FinancialTheoremLibrary
    GraphRAGNewsAnalyzer = graphrag_news_analyzer.GraphRAGNewsAnalyzer
    VectorEmbeddingAnalyzer = embedding_correlation.VectorEmbeddingAnalyzer
    
    # Expose MCP tool functions
    fetch_stock_data = stock_scrapers.fetch_stock_data
    fetch_financial_news = news_scrapers.fetch_financial_news
    list_financial_theorems = finance_theorems.list_financial_theorems
    analyze_executive_performance = graphrag_news_analyzer.analyze_executive_performance
    
    # Software Engineering Tool Functions
    scrape_github_repository = github_repository_scraper.scrape_github_repository
    analyze_github_actions = github_actions_analyzer.analyze_github_actions
    parse_systemd_logs = systemd_log_parser.parse_systemd_logs
    parse_kubernetes_logs = kubernetes_log_analyzer.parse_kubernetes_logs
    analyze_dependency_chain = dependency_chain_analyzer.analyze_dependency_chain
    create_workflow_dag = dag_workflow_planner.create_workflow_dag
    plan_speculative_execution = dag_workflow_planner.plan_speculative_execution
    predict_gpu_needs = gpu_provisioning_predictor.predict_gpu_needs
    detect_error_patterns = error_pattern_detector.detect_error_patterns
    coordinate_auto_healing = auto_healing_coordinator.coordinate_auto_healing
    list_software_theorems = software_theorems.list_software_theorems
    validate_against_theorem = software_theorems.validate_against_theorem
    
    HAVE_SOFTWARE_ENGINEERING_TOOLS = True
    HAVE_FINANCE_TOOLS = True
    if installer.verbose:
        print("✅ Finance dashboard tools successfully loaded")
except ImportError as e:
    HAVE_SOFTWARE_ENGINEERING_TOOLS = False
    HAVE_FINANCE_TOOLS = False
    
    # Set finance tools to None
    StockDataScraper = None
    NewsScraperBase = None
    FinancialTheoremLibrary = None
    GraphRAGNewsAnalyzer = None
    VectorEmbeddingAnalyzer = None
    fetch_stock_data = None
    fetch_financial_news = None
    list_financial_theorems = None
    analyze_executive_performance = None
    analyze_embedding_market_correlation = None
    
    # Set software engineering tools to None
    scrape_github_repository = None
    analyze_github_actions = None
    parse_systemd_logs = None
    parse_kubernetes_logs = None
    analyze_dependency_chain = None
    create_workflow_dag = None
    plan_speculative_execution = None
    predict_gpu_needs = None
    detect_error_patterns = None
    coordinate_auto_healing = None
    list_software_theorems = None
    validate_against_theorem = None
    
    if installer.verbose:
        import warnings
        warnings.warn(f"Finance/Software engineering tools unavailable due to missing dependencies: {e}")

except AttributeError:
    rag_query_optimizer = None