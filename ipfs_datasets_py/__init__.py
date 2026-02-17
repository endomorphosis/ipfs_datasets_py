"""
IPFS Datasets Python

A unified interface for data processing and distribution across decentralized networks
with automated dependency installation for full functionality.
"""

__version__ = "0.2.0"

import logging
import os
import warnings

# Routers + dependency injection
try:
    from .router_deps import RouterDeps, get_default_router_deps, set_default_router_deps
except Exception:
    RouterDeps = None  # type: ignore
    get_default_router_deps = None  # type: ignore
    set_default_router_deps = None  # type: ignore


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


# In benchmark/CI contexts we want imports to be as hermetic as possible.
# This prevents package import-time side effects from optional subsystems
# (FastAPI services, vector stores, search integrations) that are unrelated to
# model routing benchmarks.
_MINIMAL_IMPORTS = _truthy(os.environ.get("IPFS_DATASETS_PY_MINIMAL_IMPORTS")) or _truthy(
    os.environ.get("IPFS_DATASETS_PY_BENCHMARK")
)

# Optional import-time exports.
#
# IMPORTANT: The package core should not import MCP/FastAPI/tooling layers unless
# explicitly requested. Importing submodules like `ipfs_datasets_py.logic.tools`
# necessarily executes this __init__, so keep default imports as hermetic as
# possible.
_ENABLE_MCP_IMPORTS = _truthy(os.environ.get("IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS"))
_ENABLE_FASTAPI_IMPORTS = _truthy(os.environ.get("IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS"))
_ENABLE_FINANCE_DASHBOARD_IMPORTS = _truthy(
    os.environ.get("IPFS_DATASETS_PY_ENABLE_FINANCE_DASHBOARD_IMPORTS")
)

# Optional dependency import notices.
#
# Default behavior: stay quiet on missing optional dependencies so that importing
# lightweight submodules (e.g. `ipfs_datasets_py.logic.api`) doesn't spam stdout.
# Set IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS=1 to emit warnings.
_WARN_OPTIONAL_IMPORTS = _truthy(os.environ.get("IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS"))


def _optional_import_notice(message: str) -> None:
    if _WARN_OPTIONAL_IMPORTS:
        try:
            warnings.warn(message)
        except Exception:
            logging.debug(message)
    else:
        logging.debug(message)

# File type detection
if _MINIMAL_IMPORTS:
    HAVE_FILE_DETECTOR = False
    FileTypeDetector = None
    DetectionMethod = None
    DetectionStrategy = None
else:
    try:
        from .file_detector import FileTypeDetector, DetectionMethod, DetectionStrategy
        HAVE_FILE_DETECTOR = True
    except ImportError:
        HAVE_FILE_DETECTOR = False
        FileTypeDetector = None
        DetectionMethod = None
        DetectionStrategy = None

def _dedupe_root_logging_handlers() -> None:
    """
    Reduce duplicate root handlers when running benchmarks.
    """
    if os.environ.get("IPFS_DATASETS_PY_LOG_DEDUP", "0") != "1":
        return

    root_logger = logging.getLogger()
    handlers = list(root_logger.handlers)
    if not handlers:
        return

    unique_handlers = []
    seen = set()

    for handler in handlers:
        stream = getattr(handler, "stream", None)
        filename = getattr(handler, "baseFilename", None)
        key = (type(handler), id(stream), filename)
        if key in seen:
            continue
        seen.add(key)
        unique_handlers.append(handler)

    if unique_handlers != handlers:
        root_logger.handlers = unique_handlers


_dedupe_root_logging_handlers()


def initialize(
    *,
    deps: "RouterDeps | None" = None,
    register_symai_engines: bool | None = None,
) -> "RouterDeps | None":
    """Initialize process-wide shared dependencies.

    Goals:
    - Provide an explicit entrypoint for applications/tests to share router deps.
    - Keep import-time side effects minimal; this function is opt-in.

    Parameters:
    - deps: optional RouterDeps container to install as the process-global default.
    - register_symai_engines: if True, attempt best-effort SyMAI engine registration.
      If None, respects existing env flags.
    """

    if set_default_router_deps is not None and deps is not None:
        try:
            set_default_router_deps(deps)
        except Exception:
            pass

    resolved_deps = None
    if get_default_router_deps is not None:
        try:
            resolved_deps = get_default_router_deps()
        except Exception:
            resolved_deps = None

    # Optional SyMAI engine registration (kept best-effort).
    should_register = register_symai_engines
    if should_register is None:
        should_register = os.environ.get("IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    if should_register and not _MINIMAL_IMPORTS:
        try:
            from .utils.symai_ipfs_engine import register_ipfs_symai_engines

            register_ipfs_symai_engines()
        except Exception:
            pass

    return resolved_deps

# File conversion (Phase 1: Import & Wrap existing libraries)
# NOTE: this is intentionally lazy to avoid import-time side effects from optional
# subsystems (PDF pipelines, auto-installers, accelerate patching, etc.).
HAVE_FILE_CONVERTER = False

# Import automated dependency installer
if _MINIMAL_IMPORTS:
    class _MinimalInstaller:
        auto_install = False
        verbose = False

    installer = _MinimalInstaller()

    def ensure_module(*_: object, **__: object) -> bool:  # type: ignore
        return False
else:
    from .auto_installer import get_installer, ensure_module

    # Initialize installer with environment configuration
    installer = get_installer()

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


# Main entry points with automated installation
# NOTE: intentionally lazy; see `__getattr__`.
HAVE_IPFS_DATASETS = False

# Re-export key functions with automated installation (lazy; see __getattr__)
HAVE_LOAD_DATASET = False
load_dataset = None


# Use conditional imports to handle missing modules gracefully
try:
    # Core components for Phase 1
    from .data_transformation.ipld.storage import IPLDStorage, IPLDSchema
    from .data_transformation.ipld.optimized_codec import (
        OptimizedEncoder, OptimizedDecoder, BatchProcessor,
        create_batch_processor, optimize_node_structure
    )
    HAVE_IPLD = True
except ImportError:
    HAVE_IPLD = False

# Import accelerate integration (graceful fallback if not available)
if _MINIMAL_IMPORTS:
    HAVE_ACCELERATE_INTEGRATION = False
    is_accelerate_available = None
    get_accelerate_status = None
    AccelerateManager = None
    HAVE_ACCELERATE_MANAGER = False
else:
    # Avoid importing accelerate integration at package import time.
    # The accelerate subsystem pulls in ipfs_accelerate_py / ipfs_kit_py and can
    # trigger transformers patching and heavy optional deps.
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

if _MINIMAL_IMPORTS:
    HAVE_DATASET_SERIALIZATION = False
    DatasetSerializer = None
    GraphDataset = None
    GraphNode = None
    VectorAugmentedGraphDataset = None
    dataset_serialization = None  # type: ignore

    HAVE_DATASET_MANAGER = False
    DatasetManager = None

    HAVE_CAR_CONVERSION = False
    DataInterchangeUtils = None
    car_conversion = None  # type: ignore
else:
    try:
        from .data_transformation.serialization.dataset_serialization import (
            DatasetSerializer,
            GraphDataset,
            GraphNode,
            VectorAugmentedGraphDataset,
        )
        HAVE_DATASET_SERIALIZATION = True
    except ImportError:
        HAVE_DATASET_SERIALIZATION = False
        DatasetSerializer = None
        GraphDataset = None
        GraphNode = None
        VectorAugmentedGraphDataset = None

    # Expose the module itself for `from ipfs_datasets_py import dataset_serialization`.
    try:
        from .data_transformation.serialization import dataset_serialization as dataset_serialization  # type: ignore
    except Exception:
        dataset_serialization = None  # type: ignore

    try:
        from .dataset_manager import DatasetManager
        HAVE_DATASET_MANAGER = True
    except ImportError:
        HAVE_DATASET_MANAGER = False
        DatasetManager = None

    try:
        from .data_transformation.serialization.car_conversion import DataInterchangeUtils
        HAVE_CAR_CONVERSION = True
    except ImportError:
        HAVE_CAR_CONVERSION = False
        DataInterchangeUtils = None

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

if _MINIMAL_IMPORTS:
    HAVE_UNIXFS = False
else:
    # Avoid importing UnixFS integration at package import time.
    HAVE_UNIXFS = False

if _MINIMAL_IMPORTS:
    HAVE_WEB_ARCHIVE = False
    HAVE_COMMON_CRAWL = False
else:
    # Avoid importing web-archiving subsystems at package import time.
    HAVE_WEB_ARCHIVE = False
    HAVE_COMMON_CRAWL = False

if _MINIMAL_IMPORTS:
    HAVE_UNIFIED_SCRAPER = False
else:
    # Avoid importing unified scraper subsystem at package import time.
    HAVE_UNIFIED_SCRAPER = False

if _MINIMAL_IMPORTS:
    HAVE_VECTOR_TOOLS = False
    VectorSimilarityCalculator = None
else:
    # Keep package import hermetic: avoid importing search tooling at import time.
    # These symbols remain available via `ipfs_datasets_py.search` and lazy exports.
    HAVE_VECTOR_TOOLS = False
    VectorSimilarityCalculator = None

if _MINIMAL_IMPORTS:
    HAVE_SEARCH = False
else:
    # Avoid importing the search subpackage at import time.
    # Users can still `import ipfs_datasets_py.search` explicitly.
    HAVE_SEARCH = False

if _MINIMAL_IMPORTS:
    HAVE_EMBEDDINGS = False
else:
    # Avoid importing embeddings at import time.
    # Access via `ipfs_datasets_py.embeddings` package or lazy exports.
    HAVE_EMBEDDINGS = False
    IPFSEmbeddings = None
    PerformanceMetrics = None
    EmbeddingModel = None
    EmbeddingRequest = None
    EmbeddingResponse = None
    Chunker = None
    ChunkingStrategy = None

if _MINIMAL_IMPORTS:
    HAVE_VECTOR_STORES = False
else:
    # Avoid importing vector stores at import time (FAISS import is heavy).
    # Users can import `ipfs_datasets_py.vector_stores.*` explicitly.
    HAVE_VECTOR_STORES = False
    BaseVectorStore = None
    QdrantVectorStore = None
    ElasticsearchVectorStore = None
    FAISSVectorStore = None

# MCP Tools availability
if _MINIMAL_IMPORTS:
    HAVE_MCP_TOOLS = False
    create_vector_index = None
else:
    if _ENABLE_MCP_IMPORTS:
        try:
            # from .mcp_server.tools.embedding_tools import embedding_generation
            from .mcp_server.tools.vector_tools import create_vector_index
            HAVE_MCP_TOOLS = True
        except ImportError:
            HAVE_MCP_TOOLS = False
            create_vector_index = None
    else:
        HAVE_MCP_TOOLS = False
        create_vector_index = None

# FastAPI service availability
if _MINIMAL_IMPORTS:
    HAVE_FASTAPI = False
    fastapi_app = None
else:
    if _ENABLE_FASTAPI_IMPORTS:
        try:
            from .mcp_server.fastapi_service import app as fastapi_app
            HAVE_FASTAPI = True
        except ImportError:
            HAVE_FASTAPI = False
            fastapi_app = None
    else:
        HAVE_FASTAPI = False
        fastapi_app = None

if _MINIMAL_IMPORTS:
    HAVE_GRAPHRAG_PROCESSOR = False
    UnifiedGraphRAGProcessor = None
    GraphRAGConfiguration = None
    GraphRAGResult = None
    GraphRAGProcessor = None
    MockGraphRAGProcessor = None
else:
    # GraphRAG processors - Unified implementation recommended
    UnifiedGraphRAGProcessor = None
    GraphRAGConfiguration = None
    GraphRAGResult = None
    GraphRAGProcessor = None
    MockGraphRAGProcessor = None
    HAVE_GRAPHRAG_PROCESSOR = False
    
    try:
        # Import unified GraphRAG processor (recommended)
        from .processors.graphrag.unified_graphrag import (
            UnifiedGraphRAGProcessor,
            GraphRAGConfiguration,
            GraphRAGResult
        )
        HAVE_GRAPHRAG_PROCESSOR = True
    except ImportError as e:
        logging.debug(f"UnifiedGraphRAGProcessor unavailable: {e}")
    
    try:
        # Legacy imports with deprecation warnings (backward compatibility)
        from .processors.graphrag_processor import GraphRAGProcessor, MockGraphRAGProcessor
        HAVE_GRAPHRAG_PROCESSOR = True
    except ImportError as e:
        logging.debug(f"Legacy GraphRAGProcessor unavailable: {e}")

if _MINIMAL_IMPORTS:
    HAVE_KNN = False
    IPFSKnnIndex = None
else:
    try:
        from .ipfs_knn_index import IPFSKnnIndex
        HAVE_KNN = True
    except ImportError:
        HAVE_KNN = False
        IPFSKnnIndex = None

# RAG optimizer components
if _MINIMAL_IMPORTS:
    GraphRAGQueryOptimizer = None
    GraphRAGQueryStats = None
    QueryRewriter = None
    QueryBudgetManager = None
    UnifiedGraphRAGQueryOptimizer = None
else:
    try:
        from .optimizers.graphrag.query_optimizer_minimal import (
            GraphRAGQueryOptimizer,
            GraphRAGQueryStats,
        )
    except ImportError as e:
        _optional_import_notice(
            f"Minimal RAG query optimizer unavailable due to missing dependencies: {e}"
        )
        GraphRAGQueryOptimizer = None
        GraphRAGQueryStats = None

    try:
        from .optimizers.graphrag.query_optimizer import (
            QueryRewriter,
            QueryBudgetManager,
            UnifiedGraphRAGQueryOptimizer,
        )
    except ImportError as e:
        _optional_import_notice(
            f"Advanced RAG query optimizer unavailable due to missing dependencies: {e}"
        )
        # Provide minimal fallbacks
        QueryRewriter = None
        QueryBudgetManager = None
        UnifiedGraphRAGQueryOptimizer = None


if _MINIMAL_IMPORTS:
    HAVE_KG_EXTRACTION = False
    KnowledgeGraph = None
    KnowledgeGraphExtractor = None
    Entity = None
    Relationship = None
else:
    try:
        from .knowledge_graph_extraction import (
            KnowledgeGraph,
            KnowledgeGraphExtractor,
            Entity,
            Relationship,
        )
        HAVE_KG_EXTRACTION = True
    except ImportError:
        HAVE_KG_EXTRACTION = False
        KnowledgeGraph = None
        KnowledgeGraphExtractor = None
        Entity = None
        Relationship = None

# LLM Integration Components
if _MINIMAL_IMPORTS:
    HAVE_LLM_INTERFACE = False
    LLMInterface = None
    MockLLMInterface = None
    LLMConfig = None
    PromptTemplate = None
    LLMInterfaceFactory = None
    GraphRAGPromptTemplates = None

    HAVE_LLM_GRAPHRAG = False
    GraphRAGLLMProcessor = None
    ReasoningEnhancer = None

    HAVE_GRAPHRAG_INTEGRATION = False
else:
    try:
        from .ml.llm.llm_interface import (
            LLMInterface,
            MockLLMInterface,
            LLMConfig,
            PromptTemplate,
            LLMInterfaceFactory,
            GraphRAGPromptTemplates,
        )
        HAVE_LLM_INTERFACE = True
    except ImportError as e:
        _optional_import_notice(
            f"LLM interface unavailable due to missing dependencies: {e}"
        )
        HAVE_LLM_INTERFACE = False
        # Provide minimal fallbacks
        LLMInterface = None
        MockLLMInterface = None
        LLMConfig = None
        PromptTemplate = None
        LLMInterfaceFactory = None
        GraphRAGPromptTemplates = None

    try:
        from .ml.llm.llm_graphrag import GraphRAGLLMProcessor, ReasoningEnhancer
        HAVE_LLM_GRAPHRAG = True
    except ImportError as e:
        _optional_import_notice(
            f"GraphRAG LLM processor unavailable due to missing dependencies: {e}"
        )
        HAVE_LLM_GRAPHRAG = False
        GraphRAGLLMProcessor = None
        ReasoningEnhancer = None

    # IMPORTANT: do not import `ipfs_datasets_py.search` at package import time.
    # Access `enhance_dataset_with_llm` via module-level __getattr__ (PEP 562).
    HAVE_GRAPHRAG_INTEGRATION = False

# Security and Audit Components
if _MINIMAL_IMPORTS:
    HAVE_AUDIT = False
    AuditLogger = None
    AuditEvent = None
    AuditLevel = None
    AuditCategory = None
    IntrusionDetection = None
    SecurityAlertManager = None
    AdaptiveSecurityManager = None
    ResponseRule = None
    ResponseAction = None
else:
    try:
        from ipfs_datasets_py.audit import (
            AuditLogger,
            AuditEvent,
            AuditLevel,
            AuditCategory,
            IntrusionDetection,
            SecurityAlertManager,
            AdaptiveSecurityManager,
            ResponseRule,
            ResponseAction,
        )
        HAVE_AUDIT = True
    except ImportError:
        HAVE_AUDIT = False

# P2P Workflow Scheduler
if _MINIMAL_IMPORTS:
    HAVE_P2P_WORKFLOW_SCHEDULER = False
    P2PWorkflowScheduler = None
    WorkflowDefinition = None
    WorkflowTag = None
    MerkleClock = None
    FibonacciHeap = None
    calculate_hamming_distance = None
    get_scheduler = None
else:
    try:
        from ipfs_datasets_py.p2p_networking.p2p_workflow_scheduler import (
            P2PWorkflowScheduler,
            WorkflowDefinition,
            WorkflowTag,
            MerkleClock,
            FibonacciHeap,
            calculate_hamming_distance,
            get_scheduler,
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

# Check for IPFS capability (prefer router entrypoint)
try:
    from . import ipfs_backend_router as _ipfs_backend_router
    HAVE_IPFS = True
except Exception:
    HAVE_IPFS = False

if _MINIMAL_IMPORTS:
    HAVE_IPLD_CAR = False
    HAVE_IPLD_DAG_PB = False
    PBNode = None
    PBLink = None

    HAVE_ARROW = False
    pa = None  # type: ignore

    HAVE_HUGGINGFACE = False
    Dataset = None

    HAVE_ARCHIVENOW = False
    HAVE_IPWB = False
else:
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
        import archivenow  # type: ignore
        HAVE_ARCHIVENOW = True
    except ImportError:
        HAVE_ARCHIVENOW = False

    try:
        import ipwb  # type: ignore
        HAVE_IPWB = True
    except ImportError:
        HAVE_IPWB = False

# PDF Processing Components
#
# IMPORTANT: Do not eagerly import `.pdf_processing` here.
# Importing it can trigger heavyweight optional dependency checks/installers at import-time,
# which makes unrelated imports (and pytest collection) slow and side-effectful.
#
# Instead, expose these symbols via module-level lazy import.
import os

HAVE_PDF_PROCESSOR = False
HAVE_MULTI_ENGINE_OCR = False
HAVE_LLM_OPTIMIZER = False
HAVE_GRAPHRAG_INTEGRATOR = False
HAVE_QUERY_ENGINE = False
HAVE_PDF_PROCESSING = False

_PDF_LAZY_EXPORTS = {
    'PDFProcessor': 'HAVE_PDF_PROCESSOR',
    'MultiEngineOCR': 'HAVE_MULTI_ENGINE_OCR',
    'LLMOptimizer': 'HAVE_LLM_OPTIMIZER',
    'GraphRAGIntegrator': 'HAVE_GRAPHRAG_INTEGRATOR',
    'QueryEngine': 'HAVE_QUERY_ENGINE',
}


def _lazy_import_pdf_symbol(name: str):
    global HAVE_PDF_PROCESSOR
    global HAVE_MULTI_ENGINE_OCR
    global HAVE_LLM_OPTIMIZER
    global HAVE_GRAPHRAG_INTEGRATOR
    global HAVE_QUERY_ENGINE
    global HAVE_PDF_PROCESSING

    if name not in _PDF_LAZY_EXPORTS:
        raise AttributeError(name)

    # Optional import-time installation remains opt-in.
    if (
        (not _MINIMAL_IMPORTS)
        and installer.auto_install
        and os.environ.get('IPFS_DATASETS_AUTO_INSTALL', 'false').lower() == 'true'
        and os.environ.get('IPFS_DATASETS_INSTALL_ON_IMPORT', 'false').lower() == 'true'
    ):
        try:
            from .auto_installer import install_for_component

            for _component in ('pdf', 'ocr'):
                install_for_component(_component)

            if os.environ.get('IPFS_DATASETS_INSTALL_SYMAI_ROUTER', 'false').lower() == 'true':
                install_for_component('symai_router')
        except Exception as e:
            _optional_import_notice(
                f"Auto-install for PDF components failed during lazy import: {e}"
            )

    try:
        from .processors import pdf_processing as _pdf_processing

        value = getattr(_pdf_processing, name)
        globals()[name] = value
        globals()[_PDF_LAZY_EXPORTS[name]] = True
        HAVE_PDF_PROCESSING = True
        return value
    except Exception as e:
        # Match previous behavior: if unavailable, expose as `None`.
        globals()[name] = None
        if installer.verbose:
            try:
                _optional_import_notice(f"{name} unavailable: {e}")
            except Exception:
                pass
        return None


def __getattr__(name: str):
    if name in {"UnixFSHandler", "FixedSizeChunker", "RabinChunker"}:
        if _MINIMAL_IMPORTS:
            globals()[name] = None
            globals()["HAVE_UNIXFS"] = False
            return None
        try:
            from .integrations.unixfs_integration import (
                UnixFSHandler as _UnixFSHandler,
                FixedSizeChunker as _FixedSizeChunker,
                RabinChunker as _RabinChunker,
            )

            globals()["UnixFSHandler"] = _UnixFSHandler
            globals()["FixedSizeChunker"] = _FixedSizeChunker
            globals()["RabinChunker"] = _RabinChunker
            globals()["HAVE_UNIXFS"] = True
            return globals()[name]
        except Exception as e:
            globals()["UnixFSHandler"] = None
            globals()["FixedSizeChunker"] = None
            globals()["RabinChunker"] = None
            globals()["HAVE_UNIXFS"] = False
            _optional_import_notice(f"UnixFS integration unavailable: {e}")
            return None

    if name in {"WebArchiveProcessor", "CommonCrawlSearchEngine", "create_search_engine"}:
        if _MINIMAL_IMPORTS:
            globals()[name] = None
            globals()["HAVE_WEB_ARCHIVE"] = False
            globals()["HAVE_COMMON_CRAWL"] = False
            return None
        try:
            from .web_archive import WebArchiveProcessor as _WebArchiveProcessor
            from .web_archiving import (
                CommonCrawlSearchEngine as _CommonCrawlSearchEngine,
                create_search_engine as _create_search_engine,
            )

            globals()["WebArchiveProcessor"] = _WebArchiveProcessor
            globals()["CommonCrawlSearchEngine"] = _CommonCrawlSearchEngine
            globals()["create_search_engine"] = _create_search_engine
            globals()["HAVE_WEB_ARCHIVE"] = True
            globals()["HAVE_COMMON_CRAWL"] = True
            return globals()[name]
        except Exception as e:
            globals()["WebArchiveProcessor"] = None
            globals()["CommonCrawlSearchEngine"] = None
            globals()["create_search_engine"] = None
            globals()["HAVE_WEB_ARCHIVE"] = False
            globals()["HAVE_COMMON_CRAWL"] = False
            _optional_import_notice(f"Web archive subsystem unavailable: {e}")
            return None

    if name in {
        "UnifiedWebScraper",
        "ScraperConfig",
        "ScraperMethod",
        "ScraperResult",
        "scrape_url",
        "scrape_urls",
        "scrape_url_async",
        "scrape_urls_async",
    }:
        if _MINIMAL_IMPORTS:
            globals()[name] = None
            globals()["HAVE_UNIFIED_SCRAPER"] = False
            return None
        try:
            from .unified_web_scraper import (
                UnifiedWebScraper as _UnifiedWebScraper,
                ScraperConfig as _ScraperConfig,
                ScraperMethod as _ScraperMethod,
                ScraperResult as _ScraperResult,
                scrape_url as _scrape_url,
                scrape_urls as _scrape_urls,
                scrape_url_async as _scrape_url_async,
                scrape_urls_async as _scrape_urls_async,
            )

            globals()["UnifiedWebScraper"] = _UnifiedWebScraper
            globals()["ScraperConfig"] = _ScraperConfig
            globals()["ScraperMethod"] = _ScraperMethod
            globals()["ScraperResult"] = _ScraperResult
            globals()["scrape_url"] = _scrape_url
            globals()["scrape_urls"] = _scrape_urls
            globals()["scrape_url_async"] = _scrape_url_async
            globals()["scrape_urls_async"] = _scrape_urls_async
            globals()["HAVE_UNIFIED_SCRAPER"] = True
            return globals()[name]
        except Exception as e:
            globals()["UnifiedWebScraper"] = None
            globals()["ScraperConfig"] = None
            globals()["ScraperMethod"] = None
            globals()["ScraperResult"] = None
            globals()["scrape_url"] = None
            globals()["scrape_urls"] = None
            globals()["scrape_url_async"] = None
            globals()["scrape_urls_async"] = None
            globals()["HAVE_UNIFIED_SCRAPER"] = False
            _optional_import_notice(f"Unified web scraper unavailable: {e}")
            return None

    if name == "enhance_dataset_with_llm":
        if _MINIMAL_IMPORTS:
            globals()["enhance_dataset_with_llm"] = None
            globals()["HAVE_GRAPHRAG_INTEGRATION"] = False
            return None
        try:
            from ipfs_datasets_py.search.graphrag_integration import (
                enhance_dataset_with_llm as _enhance_dataset_with_llm,
            )

            globals()["enhance_dataset_with_llm"] = _enhance_dataset_with_llm
            globals()["HAVE_GRAPHRAG_INTEGRATION"] = True
            return _enhance_dataset_with_llm
        except Exception as e:
            globals()["enhance_dataset_with_llm"] = None
            globals()["HAVE_GRAPHRAG_INTEGRATION"] = False
            _optional_import_notice(f"GraphRAG integration unavailable: {e}")
            return None

    # Heavy optional subsystems: keep import-time hermetic; lazy-load on access.
    if name == "search":
        if _MINIMAL_IMPORTS:
            globals()["search"] = None
            return None
        try:
            import importlib

            mod = importlib.import_module(f"{__name__}.search")
            globals()["search"] = mod
            globals()["HAVE_SEARCH"] = True
            return mod
        except Exception:
            globals()["search"] = None
            globals()["HAVE_SEARCH"] = False
            return None

    if name == "VectorSimilarityCalculator":
        if _MINIMAL_IMPORTS:
            globals()["VectorSimilarityCalculator"] = None
            globals()["HAVE_VECTOR_TOOLS"] = False
            return None
        try:
            from .search.vector_tools import VectorSimilarityCalculator as _VectorSimilarityCalculator

            globals()["VectorSimilarityCalculator"] = _VectorSimilarityCalculator
            globals()["HAVE_VECTOR_TOOLS"] = True
            return _VectorSimilarityCalculator
        except Exception:
            globals()["VectorSimilarityCalculator"] = None
            globals()["HAVE_VECTOR_TOOLS"] = False
            return None

    if name in {
        "IPFSEmbeddings",
        "PerformanceMetrics",
        "EmbeddingModel",
        "EmbeddingRequest",
        "EmbeddingResponse",
        "Chunker",
        "ChunkingStrategy",
    }:
        if _MINIMAL_IMPORTS:
            globals()[name] = None
            globals()["HAVE_EMBEDDINGS"] = False
            return None
        try:
            from .embeddings.core import IPFSEmbeddings as _IPFSEmbeddings, PerformanceMetrics as _PerformanceMetrics
            from .embeddings.schema import (
                EmbeddingModel as _EmbeddingModel,
                EmbeddingRequest as _EmbeddingRequest,
                EmbeddingResponse as _EmbeddingResponse,
            )
            from .embeddings.chunker import Chunker as _Chunker, ChunkingStrategy as _ChunkingStrategy

            globals()["IPFSEmbeddings"] = _IPFSEmbeddings
            globals()["PerformanceMetrics"] = _PerformanceMetrics
            globals()["EmbeddingModel"] = _EmbeddingModel
            globals()["EmbeddingRequest"] = _EmbeddingRequest
            globals()["EmbeddingResponse"] = _EmbeddingResponse
            globals()["Chunker"] = _Chunker
            globals()["ChunkingStrategy"] = _ChunkingStrategy
            globals()["HAVE_EMBEDDINGS"] = True
            return globals()[name]
        except Exception:
            globals()[name] = None
            globals()["HAVE_EMBEDDINGS"] = False
            return None

    if name in {"BaseVectorStore", "QdrantVectorStore", "ElasticsearchVectorStore", "FAISSVectorStore"}:
        if _MINIMAL_IMPORTS:
            globals()[name] = None
            globals()["HAVE_VECTOR_STORES"] = False
            return None
        try:
            from .vector_stores.base import BaseVectorStore as _BaseVectorStore
            from .vector_stores.qdrant_store import QdrantVectorStore as _QdrantVectorStore
            from .vector_stores.elasticsearch_store import ElasticsearchVectorStore as _ElasticsearchVectorStore
            from .vector_stores.faiss_store import FAISSVectorStore as _FAISSVectorStore

            globals()["BaseVectorStore"] = _BaseVectorStore
            globals()["QdrantVectorStore"] = _QdrantVectorStore
            globals()["ElasticsearchVectorStore"] = _ElasticsearchVectorStore
            globals()["FAISSVectorStore"] = _FAISSVectorStore
            globals()["HAVE_VECTOR_STORES"] = True
            return globals()[name]
        except Exception:
            globals()[name] = None
            globals()["HAVE_VECTOR_STORES"] = False
            return None

    if name in {"is_accelerate_available", "get_accelerate_status", "AccelerateManager", "HAVE_ACCELERATE_MANAGER"}:
        if _MINIMAL_IMPORTS:
            if name == "HAVE_ACCELERATE_MANAGER":
                globals()[name] = False
                return False
            globals()[name] = None
            globals()["HAVE_ACCELERATE_INTEGRATION"] = False
            globals()["HAVE_ACCELERATE_MANAGER"] = False
            return None
        try:
            from .ml.accelerate_integration import (
                is_accelerate_available as _is_accelerate_available,
                get_accelerate_status as _get_accelerate_status,
                AccelerateManager as _AccelerateManager,
                HAVE_ACCELERATE_MANAGER as _HAVE_ACCELERATE_MANAGER,
            )

            globals()["is_accelerate_available"] = _is_accelerate_available
            globals()["get_accelerate_status"] = _get_accelerate_status
            globals()["AccelerateManager"] = _AccelerateManager
            globals()["HAVE_ACCELERATE_MANAGER"] = _HAVE_ACCELERATE_MANAGER
            globals()["HAVE_ACCELERATE_INTEGRATION"] = True
            return globals()[name]
        except Exception:
            if name == "HAVE_ACCELERATE_MANAGER":
                globals()[name] = False
                globals()["HAVE_ACCELERATE_MANAGER"] = False
                globals()["HAVE_ACCELERATE_INTEGRATION"] = False
                return False
            globals()[name] = None
            globals()["HAVE_ACCELERATE_MANAGER"] = False
            globals()["HAVE_ACCELERATE_INTEGRATION"] = False
            return None

    if name in _PDF_LAZY_EXPORTS:
        return _lazy_import_pdf_symbol(name)

    if name in {"FileConverter", "ConversionResult"}:
        global HAVE_FILE_CONVERTER
        if _MINIMAL_IMPORTS:
            globals()["FileConverter"] = None
            globals()["ConversionResult"] = None
            HAVE_FILE_CONVERTER = False
            return globals()[name]
        try:
            from .file_converter import FileConverter as _FileConverter, ConversionResult as _ConversionResult

            globals()["FileConverter"] = _FileConverter
            globals()["ConversionResult"] = _ConversionResult
            HAVE_FILE_CONVERTER = True
        except Exception:
            globals()["FileConverter"] = None
            globals()["ConversionResult"] = None
            HAVE_FILE_CONVERTER = False
        return globals()[name]

    if name in {"ipfs_datasets_py", "IPFSDatasets"}:
        global HAVE_IPFS_DATASETS
        if _MINIMAL_IMPORTS:
            globals()["ipfs_datasets_py"] = _FallbackIPFSDatasets
            globals()["IPFSDatasets"] = _FallbackIPFSDatasets
            HAVE_IPFS_DATASETS = False
            return globals()[name]
        try:
            from .ipfs_datasets import ipfs_datasets_py as _ipfs_datasets_py

            globals()["ipfs_datasets_py"] = _ipfs_datasets_py
            globals()["IPFSDatasets"] = _ipfs_datasets_py
            HAVE_IPFS_DATASETS = True
        except Exception:
            globals()["ipfs_datasets_py"] = _FallbackIPFSDatasets
            globals()["IPFSDatasets"] = _FallbackIPFSDatasets
            HAVE_IPFS_DATASETS = False
        return globals()[name]

    if name == "load_dataset":
        global HAVE_LOAD_DATASET
        if _MINIMAL_IMPORTS:
            globals()["load_dataset"] = None
            HAVE_LOAD_DATASET = False
            return None
        try:
            # Best-effort: only attempt optional dependency resolution when requested.
            ok = ensure_module("datasets", "datasets", required=False)
            if ok:
                from datasets import load_dataset as _load_dataset

                globals()["load_dataset"] = _load_dataset
                HAVE_LOAD_DATASET = True
                return _load_dataset
        except Exception:
            pass

        globals()["load_dataset"] = None
        HAVE_LOAD_DATASET = False
        return None

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

# Define base exports that should always be available
__all__ = [
    # Original exports
    's3_kit',
    'test_fio', 
    'config',
    # Lazy core exports (safe even if unavailable)
    'ipfs_datasets_py',
    'IPFSDatasets',
    'FileConverter',
    'ConversionResult',
    'load_dataset',
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
    __all__.extend([
        'UnifiedGraphRAGProcessor',  # Recommended unified implementation
        'GraphRAGConfiguration',
        'GraphRAGResult',
        'GraphRAGProcessor',  # Legacy (deprecated)
        'MockGraphRAGProcessor'  # Legacy (deprecated)
    ])

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
    from .web_archiving.web_text_extractor import (
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
        _optional_import_notice(
            f"Web text extractor unavailable due to missing dependencies: {e}"
        )

# Proper module aliasing for backward compatibility
if _MINIMAL_IMPORTS:
    llm = None  # type: ignore
    rag = None  # type: ignore
else:
    try:
        from . import llm
    except ImportError:
        llm = None  # type: ignore

# Direct aliases without polluting sys.modules
try:
    llm_interface = llm.llm_interface
except AttributeError:
    llm_interface = None

try:
    llm_graphrag = llm.llm_graphrag
except AttributeError:
    llm_graphrag = None

# Finance Dashboard Tools - Phase 7 Enhancement
try:
    if (not _MINIMAL_IMPORTS) and _ENABLE_FINANCE_DASHBOARD_IMPORTS:
        # Core package modules (MCP/CLI wrappers should depend on these)
        from .knowledge_graphs import finance_graphrag as graphrag_news_analyzer
        from .mcp_server.tools.finance_data_tools import stock_scrapers
        from .mcp_server.tools.finance_data_tools import news_scrapers
        from .mcp_server.tools.finance_data_tools import finance_theorems
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
            software_theorems,
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
    else:
        HAVE_SOFTWARE_ENGINEERING_TOOLS = False
        HAVE_FINANCE_TOOLS = False

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
except (ImportError, AttributeError) as e:
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
        _optional_import_notice(
            f"Finance/Software engineering tools unavailable due to missing dependencies: {e}"
        )