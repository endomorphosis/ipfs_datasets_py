"""
IPFS Datasets Python

A unified interface for data processing and distribution across decentralized networks.
"""

# Main entry points
try:
    from .ipfs_datasets import ipfs_datasets_py
    HAVE_IPFS_DATASETS = True
except ImportError:
    HAVE_IPFS_DATASETS = False

# Re-export key functions
try:
    from datasets import load_dataset
    HAVE_LOAD_DATASET = True
except ImportError:
    HAVE_LOAD_DATASET = False

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
    from .graphrag_processor import GraphRAGProcessor, MockGraphRAGProcessor
    HAVE_GRAPHRAG_PROCESSOR = True
except ImportError:
    HAVE_GRAPHRAG_PROCESSOR = False

try:
    from .ipfs_knn_index import IPFSKnnIndex
    HAVE_KNN = True
except ImportError:
    HAVE_KNN = False

try:
    from .rag_query_optimizer_minimal import GraphRAGQueryOptimizer, GraphRAGQueryStats
    HAVE_RAG_OPTIMIZER_MINIMAL = True
except ImportError:
    HAVE_RAG_OPTIMIZER_MINIMAL = False

try:
    # Import advanced RAG optimizer components directly
    from .rag_query_optimizer import (
        QueryRewriter,
        QueryBudgetManager,
        UnifiedGraphRAGQueryOptimizer
    )
    HAVE_RAG_OPTIMIZER_ADVANCED = True
except ImportError:
    HAVE_RAG_OPTIMIZER_ADVANCED = False


try:
    from .knowledge_graph_extraction import KnowledgeGraph, KnowledgeGraphExtractor, Entity, Relationship
    HAVE_KG_EXTRACTION = True
except ImportError:
    HAVE_KG_EXTRACTION = False

# LLM Integration Components
try:
    from .llm_interface import (
        LLMInterface, MockLLMInterface, LLMConfig, PromptTemplate,
        LLMInterfaceFactory, GraphRAGPromptTemplates
    )
    HAVE_LLM_INTERFACE = True
except ImportError:
    HAVE_LLM_INTERFACE = False

try:
    from .llm_graphrag import GraphRAGLLMProcessor, ReasoningEnhancer
    HAVE_LLM_GRAPHRAG = True
except ImportError:
    HAVE_LLM_GRAPHRAG = False

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

try:
    from .pdf_processing import (
        PDFProcessor, MultiEngineOCR, LLMOptimizer, 
        GraphRAGIntegrator, QueryEngine, BatchProcessor
    )
    HAVE_PDF_PROCESSING = True
except ImportError:
    HAVE_PDF_PROCESSING = False

# Define base exports that should always be available
__all__ = [
    # Original exports
    'load_dataset',
    's3_kit',
    'test_fio',
    'config',

    # Dependencies availability flags
    'HAVE_IPFS',
    'HAVE_IPLD_CAR',
    'HAVE_IPLD_DAG_PB',
    'HAVE_ARROW',
    'HAVE_HUGGINGFACE',
    'HAVE_ARCHIVENOW',
    'HAVE_IPWB',
    'HAVE_IPLD',
    'HAVE_DATASET_SERIALIZATION',
    'HAVE_CAR_CONVERSION',
    'HAVE_UNIXFS',
    'HAVE_WEB_ARCHIVE',
    'HAVE_VECTOR_TOOLS',
    'HAVE_GRAPHRAG_PROCESSOR',
    'HAVE_KNN',
    'HAVE_RAG_OPTIMIZER_MINIMAL',
    'HAVE_RAG_OPTIMIZER_ADVANCED',
    'HAVE_KG_EXTRACTION',
    'HAVE_LLM_INTERFACE',
    'HAVE_LLM_GRAPHRAG',
    'HAVE_GRAPHRAG_INTEGRATION',
    'HAVE_AUDIT'
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

if HAVE_GRAPHRAG_PROCESSOR:
    __all__.extend(['GraphRAGProcessor', 'MockGraphRAGProcessor'])

if HAVE_KNN:
    __all__.extend(['IPFSKnnIndex'])

if HAVE_RAG_OPTIMIZER_MINIMAL:
    __all__.extend([
        'GraphRAGQueryOptimizer',
        'GraphRAGQueryStats'
    ])

if HAVE_RAG_OPTIMIZER_ADVANCED:
    __all__.extend([
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

if HAVE_LLM_INTERFACE:
    __all__.extend([
        'LLMInterface',
        'MockLLMInterface',
        'LLMConfig',
        'PromptTemplate',
        'LLMInterfaceFactory',
        'GraphRAGPromptTemplates'
    ])

if HAVE_LLM_GRAPHRAG:
    __all__.extend([
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
