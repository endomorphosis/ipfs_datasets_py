"""
IPFS Datasets Python

A unified interface for data processing and distribution across decentralized networks.
"""

# Original imports
from .ipfs_datasets import load_dataset
from .s3_kit import s3_kit
from .test_fio import test_fio
from .config import config

# Use conditional imports to handle missing modules gracefully
try:
    # Core components for Phase 1
    from ipfs_datasets_py.ipld.storage import IPLDStorage, IPLDSchema
    from ipfs_datasets_py.ipld.optimized_codec import (
        OptimizedEncoder, OptimizedDecoder, BatchProcessor,
        create_batch_processor, optimize_node_structure
    )
    HAVE_IPLD = True
except ImportError:
    HAVE_IPLD = False
    
try:
    from ipfs_datasets_py.dataset_serialization import (
        DatasetSerializer, GraphDataset, GraphNode, VectorAugmentedGraphDataset,
    )
    HAVE_DATASET_SERIALIZATION = True
except ImportError:
    HAVE_DATASET_SERIALIZATION = False

try:
    from ipfs_datasets_py.car_conversion import DataInterchangeUtils
    HAVE_CAR_CONVERSION = True
except ImportError:
    HAVE_CAR_CONVERSION = False

try:
    from ipfs_datasets_py.unixfs_integration import UnixFSHandler, FixedSizeChunker, RabinChunker
    HAVE_UNIXFS = True
except ImportError:
    HAVE_UNIXFS = False

try:
    from ipfs_datasets_py.web_archive_utils import WebArchiveProcessor, index_warc, create_warc
    HAVE_WEB_ARCHIVE = True
except ImportError:
    HAVE_WEB_ARCHIVE = False

try:
    from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
    HAVE_KNN = True
except ImportError:
    HAVE_KNN = False

try:
    from ipfs_datasets_py.rag_query_optimizer import GraphRAGQueryOptimizer, GraphRAGQueryStats
    HAVE_RAG_OPTIMIZER = True
except ImportError:
    HAVE_RAG_OPTIMIZER = False

try:
    from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraph, KnowledgeGraphExtractor, Entity, Relationship
    HAVE_KG_EXTRACTION = True
except ImportError:
    HAVE_KG_EXTRACTION = False

# LLM Integration Components
try:
    from ipfs_datasets_py.llm_interface import (
        LLMInterface, MockLLMInterface, LLMConfig, PromptTemplate, 
        LLMInterfaceFactory, GraphRAGPromptTemplates
    )
    HAVE_LLM_INTERFACE = True
except ImportError:
    HAVE_LLM_INTERFACE = False

try:
    from ipfs_datasets_py.llm_graphrag import GraphRAGLLMProcessor, ReasoningEnhancer
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
    'HAVE_KNN',
    'HAVE_RAG_OPTIMIZER',
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

if HAVE_CAR_CONVERSION:
    __all__.extend(['DataInterchangeUtils'])

if HAVE_UNIXFS:
    __all__.extend([
        'UnixFSHandler',
        'FixedSizeChunker',
        'RabinChunker'
    ])

if HAVE_WEB_ARCHIVE:
    __all__.extend([
        'WebArchiveProcessor',
        'index_warc',
        'create_warc'
    ])

if HAVE_KNN:
    __all__.extend(['IPFSKnnIndex'])

if HAVE_RAG_OPTIMIZER:
    __all__.extend([
        'GraphRAGQueryOptimizer',
        'GraphRAGQueryStats'
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
