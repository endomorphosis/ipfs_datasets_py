"""
IPFS Datasets Python

A unified interface for data processing and distribution across decentralized networks.
"""

# Original imports
from .ipfs_datasets import load_dataset
from .s3_kit import s3_kit
from .test_fio import test_fio
from .config import config

# Core components for Phase 1
from ipfs_datasets_py.ipld.storage import IPLDStorage, IPLDSchema
from ipfs_datasets_py.ipld.optimized_codec import (
    OptimizedEncoder, OptimizedDecoder, BatchProcessor,
    create_batch_processor, optimize_node_structure
)
from ipfs_datasets_py.dataset_serialization import (
    DatasetSerializer, GraphDataset, GraphNode, VectorAugmentedGraphDataset,
)
from ipfs_datasets_py.car_conversion import DataInterchangeUtils
from ipfs_datasets_py.unixfs_integration import UnixFSHandler, FixedSizeChunker, RabinChunker
from ipfs_datasets_py.web_archive_utils import WebArchiveProcessor, index_warc, create_warc
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
from ipfs_datasets_py.rag_query_optimizer import GraphRAGQueryOptimizer, GraphRAGQueryStats, VectorIndexPartitioner
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraph, KnowledgeGraphExtractor, Entity, Relationship

# LLM Integration Components
from ipfs_datasets_py.llm_interface import (
    LLMInterface, MockLLMInterface, LLMConfig, PromptTemplate, 
    LLMInterfaceFactory, GraphRAGPromptTemplates
)
from ipfs_datasets_py.llm_graphrag import GraphRAGLLMProcessor, ReasoningEnhancer
from ipfs_datasets_py.graphrag_integration import enhance_dataset_with_llm

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

__all__ = [
    # Original exports
    'load_dataset',
    's3_kit',
    'test_fio',
    'config',
    
    # Phase 1 components
    'IPLDStorage',
    'IPLDSchema',
    'OptimizedEncoder',
    'OptimizedDecoder',
    'BatchProcessor',
    'create_batch_processor',
    'optimize_node_structure',
    'DatasetSerializer',
    'GraphDataset',
    'GraphNode',
    'VectorAugmentedGraphDataset',
    'DataInterchangeUtils',
    'UnixFSHandler',
    'FixedSizeChunker',
    'RabinChunker',
    'WebArchiveProcessor',
    'index_warc',
    'create_warc',
    'IPFSKnnIndex',
    
    # GraphRAG Query Optimization
    'GraphRAGQueryOptimizer',
    'GraphRAGQueryStats',
    'VectorIndexPartitioner',
    
    # Knowledge Graph Extraction
    'KnowledgeGraph',
    'KnowledgeGraphExtractor',
    'Entity',
    'Relationship',
    
    # LLM Integration Components
    'LLMInterface',
    'MockLLMInterface',
    'LLMConfig',
    'PromptTemplate',
    'LLMInterfaceFactory',
    'GraphRAGPromptTemplates',
    'GraphRAGLLMProcessor',
    'ReasoningEnhancer',
    'enhance_dataset_with_llm',
    
    # Dependencies availability flags
    'HAVE_IPFS',
    'HAVE_IPLD_CAR',
    'HAVE_IPLD_DAG_PB',
    'HAVE_ARROW',
    'HAVE_HUGGINGFACE',
    'HAVE_ARCHIVENOW',
    'HAVE_IPWB'
]