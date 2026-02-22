"""
IPFS Datasets Python

A unified interface for data processing and distribution across decentralized networks
with automated dependency installation for full functionality.
"""

__version__ = "0.2.0"

import importlib
import importlib.util
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

# LLM-related imports are opt-in.
# Default behavior: importing the package should not import transformers/LLM stacks
# or search/GraphRAG integrations.
_ENABLE_LLM_IMPORTS = _truthy(os.environ.get("IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS"))

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

# File type detection (lazy; see __getattr__)
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


# IPLD components (lazy; see __getattr__).
HAVE_IPLD = False
IPLDStorage = None
IPLDSchema = None
OptimizedEncoder = None
OptimizedDecoder = None
BatchProcessor = None
create_batch_processor = None
optimize_node_structure = None

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
# NOTE: import-time engine registration is intentionally disabled.
# Use `ipfs_datasets_py.initialize(register_symai_engines=True)` instead.

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

# Expose Jsonnet helpers for `from ipfs_datasets_py import jsonnet_utils` (lazy; see __getattr__).
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

# GraphRAG processors (lazy; see __getattr__).
HAVE_GRAPHRAG_PROCESSOR = False
UnifiedGraphRAGProcessor = None
GraphRAGConfiguration = None
GraphRAGResult = None
GraphRAGProcessor = None
MockGraphRAGProcessor = None

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

# RAG optimizer components (lazy; see __getattr__).
GraphRAGQueryOptimizer = None
GraphRAGQueryStats = None
QueryRewriter = None
QueryBudgetManager = None
UnifiedGraphRAGQueryOptimizer = None


# Knowledge graph extraction (lazy; see __getattr__).
HAVE_KG_EXTRACTION = False
KnowledgeGraph = None
KnowledgeGraphExtractor = None
Entity = None
Relationship = None

# LLM Integration Components (lazy + opt-in; see __getattr__).
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

# Security and Audit Components (lazy; see __getattr__).
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

# P2P Workflow Scheduler (lazy; see __getattr__).
HAVE_P2P_WORKFLOW_SCHEDULER = False
P2PWorkflowScheduler = None
WorkflowDefinition = None
WorkflowTag = None
MerkleClock = None
FibonacciHeap = None
calculate_hamming_distance = None
get_scheduler = None

# Check for IPFS capability without importing the module.
HAVE_IPFS = importlib.util.find_spec(f"{__name__}.ipfs_backend_router") is not None

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
    # Avoid importing these optional deps at package import time.
    # Use __getattr__ for actual symbol import.
    HAVE_IPLD_CAR = importlib.util.find_spec("ipld_car") is not None
    HAVE_IPLD_DAG_PB = importlib.util.find_spec("ipld_dag_pb") is not None
    HAVE_ARROW = importlib.util.find_spec("pyarrow") is not None
    HAVE_HUGGINGFACE = importlib.util.find_spec("datasets") is not None
    HAVE_ARCHIVENOW = importlib.util.find_spec("archivenow") is not None
    HAVE_IPWB = importlib.util.find_spec("ipwb") is not None

# PDF Processing Components
#
# IMPORTANT: Do not eagerly import `.pdf_processing` here.
# Importing it can trigger heavyweight optional dependency checks/installers at import-time,
# which makes unrelated imports (and pytest collection) slow and side-effectful.
#
# Instead, expose these symbols via module-level lazy import.
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
    if name in {"FileTypeDetector", "DetectionMethod", "DetectionStrategy"}:
        global HAVE_FILE_DETECTOR
        if _MINIMAL_IMPORTS:
            globals()["FileTypeDetector"] = None
            globals()["DetectionMethod"] = None
            globals()["DetectionStrategy"] = None
            HAVE_FILE_DETECTOR = False
            return globals()[name]
        try:
            from .file_detector import (
                FileTypeDetector as _FileTypeDetector,
                DetectionMethod as _DetectionMethod,
                DetectionStrategy as _DetectionStrategy,
            )

            globals()["FileTypeDetector"] = _FileTypeDetector
            globals()["DetectionMethod"] = _DetectionMethod
            globals()["DetectionStrategy"] = _DetectionStrategy
            HAVE_FILE_DETECTOR = True
            return globals()[name]
        except Exception as e:
            globals()["FileTypeDetector"] = None
            globals()["DetectionMethod"] = None
            globals()["DetectionStrategy"] = None
            HAVE_FILE_DETECTOR = False
            _optional_import_notice(f"File detector unavailable: {e}")
            return globals()[name]

    if name in {
        "DatasetSerializer",
        "GraphDataset",
        "GraphNode",
        "VectorAugmentedGraphDataset",
        "dataset_serialization",
    }:
        global HAVE_DATASET_SERIALIZATION
        if _MINIMAL_IMPORTS:
            globals()[name] = None
            HAVE_DATASET_SERIALIZATION = False
            return globals()[name]
        try:
            from .data_transformation.serialization.dataset_serialization import (
                DatasetSerializer as _DatasetSerializer,
                GraphDataset as _GraphDataset,
                GraphNode as _GraphNode,
                VectorAugmentedGraphDataset as _VectorAugmentedGraphDataset,
            )

            globals()["DatasetSerializer"] = _DatasetSerializer
            globals()["GraphDataset"] = _GraphDataset
            globals()["GraphNode"] = _GraphNode
            globals()["VectorAugmentedGraphDataset"] = _VectorAugmentedGraphDataset
            HAVE_DATASET_SERIALIZATION = True

            if globals().get("dataset_serialization") is None:
                try:
                    from .data_transformation.serialization import dataset_serialization as _dataset_serialization  # type: ignore

                    globals()["dataset_serialization"] = _dataset_serialization
                except Exception:
                    globals()["dataset_serialization"] = None  # type: ignore

            return globals()[name]
        except Exception as e:
            globals()["DatasetSerializer"] = None
            globals()["GraphDataset"] = None
            globals()["GraphNode"] = None
            globals()["VectorAugmentedGraphDataset"] = None
            globals()["dataset_serialization"] = None  # type: ignore
            HAVE_DATASET_SERIALIZATION = False
            _optional_import_notice(f"Dataset serialization unavailable: {e}")
            return globals()[name]

    if name == "DatasetManager":
        global HAVE_DATASET_MANAGER
        if _MINIMAL_IMPORTS:
            globals()["DatasetManager"] = None
            HAVE_DATASET_MANAGER = False
            return None
        try:
            from .dataset_manager import DatasetManager as _DatasetManager

            globals()["DatasetManager"] = _DatasetManager
            HAVE_DATASET_MANAGER = True
            return _DatasetManager
        except Exception as e:
            globals()["DatasetManager"] = None
            HAVE_DATASET_MANAGER = False
            _optional_import_notice(f"DatasetManager unavailable: {e}")
            return None

    if name in {"DataInterchangeUtils", "car_conversion"}:
        global HAVE_CAR_CONVERSION
        if _MINIMAL_IMPORTS:
            globals()["DataInterchangeUtils"] = None
            globals()["car_conversion"] = None  # type: ignore
            HAVE_CAR_CONVERSION = False
            return globals()[name]
        try:
            from .data_transformation.serialization.car_conversion import DataInterchangeUtils as _DataInterchangeUtils

            globals()["DataInterchangeUtils"] = _DataInterchangeUtils
            HAVE_CAR_CONVERSION = True

            if globals().get("car_conversion") is None:
                try:
                    from .data_transformation import car_conversion as _car_conversion  # type: ignore

                    globals()["car_conversion"] = _car_conversion  # type: ignore
                except Exception:
                    globals()["car_conversion"] = None  # type: ignore

            return globals()[name]
        except Exception as e:
            globals()["DataInterchangeUtils"] = None
            globals()["car_conversion"] = None  # type: ignore
            HAVE_CAR_CONVERSION = False
            _optional_import_notice(f"CAR conversion unavailable: {e}")
            return globals()[name]

    if name == "jsonnet_utils":
        if _MINIMAL_IMPORTS:
            globals()["jsonnet_utils"] = None  # type: ignore
            return None
        try:
            mod = importlib.import_module(f"{__name__}.jsonnet_utils")
            globals()["jsonnet_utils"] = mod  # type: ignore
            return mod
        except Exception as e:
            globals()["jsonnet_utils"] = None  # type: ignore
            _optional_import_notice(f"jsonnet_utils unavailable: {e}")
            return None

    if name in {"PBNode", "PBLink"}:
        if _MINIMAL_IMPORTS:
            globals()["PBNode"] = None
            globals()["PBLink"] = None
            globals()["HAVE_IPLD_DAG_PB"] = False
            return globals()[name]
        try:
            from ipld_dag_pb import PBNode as _PBNode, PBLink as _PBLink

            globals()["PBNode"] = _PBNode
            globals()["PBLink"] = _PBLink
            globals()["HAVE_IPLD_DAG_PB"] = True
            return globals()[name]
        except Exception as e:
            globals()["PBNode"] = None
            globals()["PBLink"] = None
            globals()["HAVE_IPLD_DAG_PB"] = False
            _optional_import_notice(f"ipld-dag-pb unavailable: {e}")
            return globals()[name]

    if name == "pa":
        if _MINIMAL_IMPORTS:
            globals()["pa"] = None  # type: ignore
            globals()["HAVE_ARROW"] = False
            return None
        try:
            import pyarrow as _pa

            globals()["pa"] = _pa  # type: ignore
            globals()["HAVE_ARROW"] = True
            return _pa
        except Exception as e:
            globals()["pa"] = None  # type: ignore
            globals()["HAVE_ARROW"] = False
            _optional_import_notice(f"pyarrow unavailable: {e}")
            return None

    if name == "Dataset":
        if _MINIMAL_IMPORTS:
            globals()["Dataset"] = None
            globals()["HAVE_HUGGINGFACE"] = False
            return None
        try:
            from datasets import Dataset as _Dataset

            globals()["Dataset"] = _Dataset
            globals()["HAVE_HUGGINGFACE"] = True
            return _Dataset
        except Exception as e:
            globals()["Dataset"] = None
            globals()["HAVE_HUGGINGFACE"] = False
            _optional_import_notice(f"datasets unavailable: {e}")
            return None

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

    # -----------------------------------------------------------------------
    # Phase E+F canonical package modules (lazy on first access)
    # These were extracted from mcp_server/tools/ to canonical package
    # locations so they can be imported directly as package members.
    # -----------------------------------------------------------------------

    _CANONICAL_MODULE_MAP: dict = {
        # Maps attribute name → (relative_module_path, class_or_function_name).
        # When code accesses `ipfs_datasets_py.<name>` and the name is not yet in
        # globals, __getattr__ fires, looks up the tuple here, imports it from the
        # canonical ipfs_datasets_py package module (not from mcp_server/tools/),
        # caches it in globals, and returns it.  Only names added during Phase E+F
        # extraction appear here; names already exported via the module-level try/
        # except blocks (e.g. finance dashboard) are NOT listed here.
        # sessions package
        "MockSessionManager": (".sessions.session_engine", "MockSessionManager"),
        # tasks package
        "BackgroundTask": (".tasks.background_task_engine", "MockBackgroundTask"),
        "MockBackgroundTask": (".tasks.background_task_engine", "MockBackgroundTask"),
        "MockTaskManager": (".tasks.background_task_engine", "MockTaskManager"),
        "TaskStatus": (".tasks.background_task_engine", "TaskStatus"),
        "TaskType": (".tasks.background_task_engine", "TaskType"),
        # storage package
        "StorageBackend": (".storage.storage_engine", "StorageBackend"),
        "MockStorageService": (".storage.storage_engine", "MockStorageService"),
        # rate_limiting package
        "MockRateLimiter": (".rate_limiting.rate_limiting_engine", "MockRateLimiter"),
        "RateLimitConfig": (".rate_limiting.rate_limiting_engine", "RateLimitConfig"),
        "RateLimitStrategy": (".rate_limiting.rate_limiting_engine", "RateLimitStrategy"),
        # caching package
        "MockCacheService": (".caching.cache_engine", "MockCacheService"),
        "CacheType": (".caching.cache_engine", "CacheType"),
        "CacheStrategy": (".caching.cache_engine", "CacheStrategy"),
        "CacheEntry": (".caching.cache_engine", "CacheEntry"),
        "CacheStats": (".caching.cache_engine", "CacheStats"),
        # admin package
        "MockAdminService": (".admin.admin_engine", "MockAdminService"),
        "ServiceStatus": (".admin.admin_engine", "ServiceStatus"),
        "MaintenanceMode": (".admin.admin_engine", "MaintenanceMode"),
        # ipfs_cluster package
        "MockIPFSClusterService": (".ipfs_cluster.cluster_engine", "MockIPFSClusterService"),
        # processors/auth
        "MockAuthService": (".processors.auth.auth_engine", "MockAuthService"),
        # processors/development
        "TestGeneratorCore": (".processors.development.test_generator_engine", "TestGeneratorCore"),
        "TestGeneratorConfig": (".processors.development.test_generator_engine", "TestGeneratorConfig"),
        "generate_test_file": (".processors.development.test_generator_engine", "generate_test_file"),
        # processors/discord
        "discord_analyze_channel": (".processors.discord.discord_analysis_engine", "discord_analyze_channel"),
        "discord_export_channel": (".processors.discord.discord_export_engine", "discord_export_channel"),
        # web_archiving engines
        "SerpStackSearchAPI": (".web_archiving.serpstack_engine", "SerpStackSearchAPI"),
        "OpenVerseSearchAPI": (".web_archiving.openverse_engine", "OpenVerseSearchAPI"),
        "GitHubRepositoryScraper": (".web_archiving.github_repository_engine", "GitHubRepositoryScraper"),
        # processors/legal_scrapers engines
        "ClinicalTrialsScraper": (".scrapers.medical.clinical_trials_engine", "ClinicalTrialsScraper"),
        "PubMedScraper": (".scrapers.medical.pubmed_engine", "PubMedScraper"),
        "AIDatasetBuilder": (".scrapers.medical.ai_dataset_builder_engine", "AIDatasetBuilder"),
        "USPTOPatentScraper": (".processors.legal_scrapers.patent_engine", "USPTOPatentScraper"),
        "PatentDatasetBuilder": (".processors.legal_scrapers.patent_engine", "PatentDatasetBuilder"),
        "MunicipalScraperFallbacks": (".processors.legal_scrapers.municipal_scraper_engine", "MunicipalScraperFallbacks"),
        "StateLawsUpdateScheduler": (".processors.legal_scrapers.state_laws_scheduler_engine", "StateLawsUpdateScheduler"),
        "IncrementalUpdateTracker": (".processors.legal_scrapers.incremental_updates_engine", "IncrementalUpdateTracker"),
        "FederalRegisterVerifier": (".processors.legal_scrapers.federal_register_verifier", "FederalRegisterVerifier"),
        "USCodeVerifier": (".processors.legal_scrapers.us_code_verifier", "USCodeVerifier"),
    }

    if name in _CANONICAL_MODULE_MAP:
        if _MINIMAL_IMPORTS:
            globals()[name] = None
            return None
        module_path, attr_name = _CANONICAL_MODULE_MAP[name]
        try:
            import importlib as _importlib
            _mod = _importlib.import_module(module_path, package=__name__)
            _val = getattr(_mod, attr_name)
            globals()[name] = _val
            return _val
        except Exception as _exc:
            globals()[name] = None
            _optional_import_notice(f"Canonical module {module_path}.{attr_name} unavailable: {_exc}")
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

# Web Text Extraction (lazy; see __getattr__).
HAVE_WEB_TEXT_EXTRACTOR = False
WebTextExtractor = None
WebTextExtractionResult = None
extract_website_text = None
extract_multiple_websites = None
save_website_text = None

# Proper module aliasing for backward compatibility (lazy; see __getattr__).
llm = None  # type: ignore
rag = None  # type: ignore

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
        # Core package modules — canonical locations (Phase E+F migration)
        from .knowledge_graphs import finance_graphrag as graphrag_news_analyzer
        # Finance scrapers: canonical package engines (not mcp_server.tools shims)
        from .processors.finance.stock_scraper_engine import (
            StockDataScraper,
            StockDataPoint,
            CorporateAction,
            YahooFinanceScraper,
        )
        from .processors.finance.news_scraper_engine import (
            NewsScraperBase,
            NewsArticle,
            APNewsScraper,
            ReutersScraper,
            BloombergScraper,
        )
        from .processors.finance.finance_theorems_engine import (
            FinancialTheoremLibrary,
            FinancialTheorem,
            FinancialEventType,
            TheoremApplication,
        )
        from .processors.development.software_theorems_engine import (
            SOFTWARE_THEOREMS,
            list_software_theorems,
            validate_against_theorem,
            apply_theorem_actions,
        )
        from .web_archiving.github_repository_engine import (
            GitHubRepositoryScraper,
            scrape_github_repository,
            analyze_repository_health,
        )
        # Standalone MCP functions still live in tools/ shims because they wrap
        # async calls with anyio.run() and perform MCP-specific error handling.
        # The *classes* above come from canonical engines; these *functions* remain
        # in the tools/ layer for backward compatibility with existing callers.
        from .mcp_server.tools.finance_data_tools import stock_scrapers as _stock_scrapers
        from .mcp_server.tools.finance_data_tools import news_scrapers as _news_scrapers
        from .mcp_server.tools.finance_data_tools import finance_theorems as _finance_theorems
        fetch_stock_data = _stock_scrapers.fetch_stock_data
        fetch_financial_news = _news_scrapers.fetch_financial_news
        list_financial_theorems = _finance_theorems.list_financial_theorems

        # Embedding analysis (still in tools/ shim — kept for compat)
        from .mcp_server.tools.finance_data_tools import embedding_correlation
        VectorEmbeddingAnalyzer = embedding_correlation.VectorEmbeddingAnalyzer
        GraphRAGNewsAnalyzer = graphrag_news_analyzer.GraphRAGNewsAnalyzer
        analyze_executive_performance = graphrag_news_analyzer.analyze_executive_performance

        # Software Engineering Tool Functions (canonical SE tools still in tools/)
        from .mcp_server.tools.software_engineering_tools import (
            github_actions_analyzer,
            systemd_log_parser,
            kubernetes_log_analyzer,
            dependency_chain_analyzer,
            dag_workflow_planner,
            gpu_provisioning_predictor,
            error_pattern_detector,
            auto_healing_coordinator,
        )
        analyze_github_actions = github_actions_analyzer.analyze_github_actions
        parse_systemd_logs = systemd_log_parser.parse_systemd_logs
        parse_kubernetes_logs = kubernetes_log_analyzer.parse_kubernetes_logs
        analyze_dependency_chain = dependency_chain_analyzer.analyze_dependency_chain
        create_workflow_dag = dag_workflow_planner.create_workflow_dag
        plan_speculative_execution = dag_workflow_planner.plan_speculative_execution
        predict_gpu_needs = gpu_provisioning_predictor.predict_gpu_needs
        detect_error_patterns = error_pattern_detector.detect_error_patterns
        coordinate_auto_healing = auto_healing_coordinator.coordinate_auto_healing

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