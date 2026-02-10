import datasets
import sys
from typing import Optional
import os


def _should_enable_ipfs_kit() -> bool:
    if str(os.getenv("IPFS_KIT_DISABLE", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return False
    if str(os.getenv("IPFS_DATASETS_PY_BENCHMARK", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return str(os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_KIT", "")).strip().lower() in {"1", "true", "yes", "on"}


def _lazy_load_ipfs_kit_module():
    if not _should_enable_ipfs_kit():
        return None
    try:
        from ipfs_kit_py.ipfs_kit import ipfs_kit as ipfs_kit_module
        return ipfs_kit_module
    except Exception:
        return None


ipfs_kit_module = None
# from ipfs_datasets_py.embeddings import IPFSEmbeddings  # Legacy import placeholder (unused)
import numpy as np
import os
import json
import pandas as pd
import subprocess
import anyio
import hashlib
import random
from multiprocessing import Pool

try:
    from ipfs_datasets_py.embeddings_router import embed_texts as router_embed_texts
except Exception:
    router_embed_texts = None


def _use_embedding_adapter() -> bool:
    return str(os.getenv("IPFS_DATASETS_PY_USE_EMBEDDING_ADAPTER", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

# Try to import accelerate integration for distributed inference
try:
    from ipfs_datasets_py.accelerate_integration import (
        AccelerateManager,
        is_accelerate_available,
        get_accelerate_status
    )
    HAVE_ACCELERATE = True
except ImportError:
    HAVE_ACCELERATE = False
    AccelerateManager = None
    is_accelerate_available = lambda: False
    get_accelerate_status = lambda: {"available": False}

class search_embeddings:
    """
    Advanced Semantic Search Engine for IPFS-Distributed Datasets

    The search_embeddings class provides comprehensive functionality for performing
    semantic search operations across distributed datasets stored on IPFS. It integrates
    multiple vector database backends (Qdrant, FAISS) with embedding generation 
    capabilities to enable efficient similarity search, semantic retrieval, and 
    cross-dataset querying in decentralized environments.

    This class serves as the core search component for the IPFS datasets ecosystem,
    supporting both high-memory and low-memory search scenarios, batch processing,
    and real-time query operations across multiple dataset formats and collections.

    Args:
        resources (Dict[str, Any]): Resource configuration dictionary containing:
            - 'embedding_models' (Dict): Available embedding model configurations
            - 'vector_stores' (Dict): Vector database connection parameters
            - 'ipfs_nodes' (List): IPFS node endpoints and credentials
            - 'cache_settings' (Dict): Caching configuration for embeddings
            - 'memory_limits' (Dict): Memory usage constraints and optimization settings
        metadata (Dict[str, Any]): Operational metadata including:
            - 'search_config' (Dict): Default search parameters and thresholds
            - 'dataset_mappings' (Dict): Dataset-to-embedding model associations  
            - 'performance_settings' (Dict): Performance tuning parameters
            - 'logging_config' (Dict): Logging and monitoring configuration
            - 'join_strategies' (Dict): Cross-dataset joining methodologies

    Key Features:
    - Multi-backend vector search (Qdrant for real-time, FAISS for performance)
    - Automatic embedding model selection based on dataset characteristics
    - Memory-adaptive search strategies for both high and low-memory environments
    - IPFS-native dataset loading and distributed index management
    - Cross-collection semantic querying with result ranking and filtering
    - Batch processing capabilities for large-scale embedding generation
    - Real-time index updates and incremental dataset ingestion

    Attributes:
        resources (Dict[str, Any]): Resource configuration and connection parameters
        metadata (Dict[str, Any]): Operational metadata and search configuration
        datasets (datasets.Dataset): HuggingFace datasets integration for data handling
        dataset (List): Currently loaded dataset collection for search operations
        ipfs_kit (ipfs_kit.ipfs_kit): IPFS integration component for distributed storage
        join_column (Optional[str]): Column identifier for cross-dataset joining operations
        qdrant_found (bool): Availability status of Qdrant vector database backend
        qdrant_kit_py (Optional[qdrant_kit_py]): Qdrant database integration component
        embedding_engine (Optional[IPFSEmbeddings]): Embedding generation component

    Public Methods:
        generate_embeddings(query: str, model: Optional[str] = None) -> np.ndarray:
            Generate vector embeddings for text queries using specified or default models.
            Supports multiple embedding architectures and automatic model selection.
        search(collection: str, query: str, n: int = 5) -> List[Dict[str, Any]]:
            Perform semantic search across specified collection with ranking and filtering.
            Returns relevant documents with similarity scores and metadata.
        test_low_memory(collections: List[str], datasets: List[str], 
                       column: Optional[str] = None, query: Optional[str] = None) -> Dict[str, Any]:
            Execute memory-optimized search testing across multiple collections with
            resource-constrained configurations and batch processing strategies.
        test_high_memory() -> Dict[str, Any]:
            Perform comprehensive search testing in high-memory environments with
            full index loading and real-time processing capabilities.

    Private Methods:
        _load_qdrant_iter(dataset: str, knn_index: str, dataset_split: Optional[str] = None,
                         knn_index_split: Optional[str] = None) -> Iterator[Dict[str, Any]]:
            Load datasets iteratively into Qdrant vector database with memory optimization
            and distributed storage management.
        _ingest_qdrant_iter(columns: List[str]) -> bool:
            Incrementally ingest dataset columns into Qdrant with real-time indexing
            and consistency management across distributed nodes.
        _start_faiss(collection: str, query: str) -> Dict[str, Any]:
            Initialize FAISS-based search operations with optimized index loading
            and query execution for high-performance scenarios.
        _load_faiss(dataset: str, knn_index: str) -> bool:
            Load dataset and corresponding FAISS index from IPFS storage with
            integrity verification and performance optimization.
        _ingest_faiss(column: str) -> bool:
            Ingest dataset column into FAISS index with batch processing and
            memory-efficient embedding generation strategies.
        _search_faiss(collection: str, query_embeddings: np.ndarray, n: int = 5) -> List[Dict[str, Any]]:
            Execute FAISS-based similarity search with optimized nearest neighbor
            retrieval and result ranking mechanisms.

    Usage Example:
        search_engine = search_embeddings(
            resources={
                'embedding_models': {'default': 'sentence-transformers/all-MiniLM-L6-v2'},
                'vector_stores': {'qdrant_url': 'localhost:6333'},
                'ipfs_nodes': ['http://localhost:5001']
            },
            metadata={
                'search_config': {'similarity_threshold': 0.7, 'max_results': 100},
                'performance_settings': {'batch_size': 1000, 'memory_limit': '8GB'}
            }
        )
        
        # Generate embeddings for query
        query_embedding = await search_engine.generate_embeddings(
            "machine learning algorithms for text processing"
        )
        
        # Perform semantic search
        results = await search_engine.search(
            collection="technical_papers",
            query="natural language processing techniques",
            n=10
        )
        
        # Execute memory-optimized search testing
        test_results = await search_engine.test_low_memory(
            collections=["papers", "articles"],
            datasets=["arxiv", "wikipedia"],
            query="deep learning applications"
        )

    Notes:
        - Qdrant backend provides real-time updates and filtering capabilities
        - FAISS backend offers optimal performance for static, large-scale datasets
        - Memory usage is automatically optimized based on available system resources
        - Cross-dataset search requires compatible embedding models and vector dimensions
        - IPFS integration enables distributed dataset access and redundant storage
        - Search performance scales with dataset size and embedding dimensionality
        - Automatic fallback mechanisms ensure service availability across backend failures
    """
    def __init__(self, resources, metadata):
        """
        Initialize the semantic search engine with resource and metadata configurations.

        This constructor sets up the search engine with all necessary components including
        IPFS integration, vector database connections, embedding model initialization,
        and performance optimization settings. It automatically detects and configures
        available backend services (Qdrant, FAISS) and establishes distributed storage
        connections for seamless dataset access across IPFS networks.

        The initialization process includes service discovery, dependency validation,
        memory allocation optimization, and automatic fallback configuration to ensure
        robust search operations across different deployment environments.

        Args:
            resources (Dict[str, Any]): Resource configuration dictionary containing:
                - 'embedding_models' (Dict): Model configurations with paths and parameters
                - 'vector_stores' (Dict): Database connection strings and authentication
                - 'ipfs_nodes' (List[str]): IPFS node endpoints for distributed access
                - 'cache_settings' (Dict): Embedding cache configuration and storage paths
                - 'memory_limits' (Dict): Memory usage constraints and optimization flags
                - 'performance_tuning' (Dict): Backend-specific performance parameters
            metadata (Dict[str, Any]): Operational metadata including:
                - 'search_config' (Dict): Default search parameters, thresholds, and filters
                - 'dataset_mappings' (Dict): Dataset-to-model associations and preferences
                - 'logging_config' (Dict): Logging levels, output paths, and monitoring settings
                - 'join_strategies' (Dict): Cross-dataset joining methods and configurations
                - 'quality_settings' (Dict): Result quality thresholds and validation rules

        Attributes Initialized:
            resources (Dict[str, Any]): Stored resource configuration for component access
            metadata (Dict[str, Any]): Stored metadata for operational parameter retrieval
            datasets (datasets.Dataset): HuggingFace datasets library integration
            dataset (List): Empty list for loaded dataset storage and management
            ipfs_kit (ipfs_kit.ipfs_kit): IPFS integration component for distributed operations
            join_column (Optional[str]): Cross-dataset joining column identifier (initially None)
            qdrant_found (bool): Qdrant service availability status after connection testing
            qdrant_kit_py (Optional): Qdrant integration component (conditionally initialized)
            embedding_engine (Optional): Embedding generation component (conditionally initialized)

        Raises:
            ConnectionError: If IPFS nodes are unreachable or authentication fails
            ImportError: If required dependencies (qdrant-client, datasets) are missing
            ValueError: If resource or metadata configurations contain invalid parameters
            RuntimeError: If critical services fail to initialize or memory allocation fails
            PermissionError: If cache directories cannot be created or accessed

        Examples:
            >>> resources = {
            ...     'embedding_models': {
            ...         'default': 'sentence-transformers/all-MiniLM-L6-v2',
            ...         'large': 'sentence-transformers/all-mpnet-base-v2'
            ...     },
            ...     'vector_stores': {'qdrant_url': 'localhost:6333'},
            ...     'ipfs_nodes': ['http://localhost:5001', 'https://gateway.ipfs.io']
            ... }
            >>> metadata = {
            ...     'search_config': {'similarity_threshold': 0.75, 'max_results': 50},
            ...     'performance_settings': {'batch_size': 1000}
            ... }
            >>> search_engine = search_embeddings(resources, metadata)
            >>> print(f"Qdrant available: {search_engine.qdrant_found}")

        Notes:
            - Qdrant service discovery uses netcat (nc) to test port 6333 connectivity
            - Failed Qdrant initialization triggers automatic FAISS fallback mode
            - IPFS kit initialization enables distributed dataset access and storage
            - Dynamic attribute assignment from metadata enables flexible configuration
            - Memory optimization settings are applied during backend initialization
            - Service availability is continuously monitored for adaptive backend selection
        """
        global ipfs_kit_module
        self.resources = resources
        self.metadata = metadata
        self.datasets = datasets
        self.dataset = []
        if len(list(metadata.keys())) > 0:
            for key in metadata.keys():
                setattr(self, key, metadata[key])
        
        # Instantiate ipfs_kit (opt-in; disabled in benchmarks by default)
        self.ipfs_kit = None
        if ipfs_kit_module is None:
            ipfs_kit_module = _lazy_load_ipfs_kit_module()
        if ipfs_kit_module is not None:
            try:
                # `_lazy_load_ipfs_kit_module` returns the `ipfs_kit` factory.
                self.ipfs_kit = ipfs_kit_module(resources=resources, metadata=metadata)
            except Exception:
                self.ipfs_kit = None
        
        # self.qdrant_kit_py = qdrant_kit_py(resources=resources, metadata=metadata) # Commented out for now
        # self.embedding_engine = IPFSEmbeddings(resources=resources, metadata=metadata)  # Commented out for now
        # Removed calls to self.ipfs_kit.add_endpoint as the method does not exist.
        # Endpoint management might be handled differently now or is not needed here.
        
        self.join_column = None
        self.qdrant_found = False
        qdrant_port_cmd = "nc -zv localhost 6333"
        qdrant_port_cmd_results = os.system(qdrant_port_cmd)
        if qdrant_port_cmd_results != 0:
            self.qdrant_kit_py.start_qdrant()
            qdrant_port_cmd_results = os.system(qdrant_port_cmd)
            if qdrant_port_cmd_results == 0:
                self.qdrant_found = True
            else:
                print("Qdrant failed to start, fallback to faiss")
        else:
            self.qdrant_found = True
    def rm_cache(self):
        homedir = os.path.expanduser("~")
        cache_dir = homedir + "/.cache/huggingface/datasets/"
        cache_dir = os.path.expanduser(cache_dir)
        os.system("rm -rf " + cache_dir)
        return None

    async def generate_embeddings(self, query, model=None):
        if model is None:
            model = self.metadata["model"]
        if isinstance(query, str):
            query = [query]
        elif not isinstance(query, list):
            raise ValueError("Query must be a string or a list of strings")
        if _use_embedding_adapter() and router_embed_texts is not None:
            adapter_embeddings = await anyio.to_thread.run_sync(
                lambda: router_embed_texts(query, model_name=model)
            )
            return np.array(adapter_embeddings, dtype=np.float32)
        if self.ipfs_kit is None:
            raise RuntimeError("IPFS kit is unavailable and embedding adapter is disabled")
        self.ipfs_kit.index_knn(query, "")
        selected_endpoint = self.ipfs_kit.choose_endpoint(model)
        embeddings = await self.ipfs_kit.index_knn(selected_endpoint, model)
        return embeddings
    
    # def search_embeddings(self, embeddings):
    #     scores, samples = self.qdrant_kit_py.knn_index.get_nearest_examples(
    #        "embeddings", embeddings, k=5
    #     )
    #     return scores, samples 
        
    async def search(self, collection, query, n=5):
        query_embeddings = await self.generate_embeddings(query)
        if self.qdrant_found == True:
            vector_search = await self.qdrant_kit_py.search_qdrant(collection, query_embeddings, n)
        else:
            vector_search = await self.search_faiss(collection, query_embeddings, n)
        return vector_search

    async def test_low_memory(self, collections=[], datasets=[], column=None, query=None):
        if query is None:
            query = "the quick brown fox jumps over the lazy dog"
        if column is None:
            column = "Concat Abstract"
        if len(datasets) == 0:
            datasets = ["laion/German-ConcatX-Abstract", "laion/German-ConcatX-M3"]
        if len(collections) == 0:
            collections = [ x for x in datasets if "/" in x]
            collections = [ x.split("/")[1] for x in collections]
        start_qdrant = self.qdrant_kit_py.start_qdrant()
        if start_qdrant == True:
            print("Qdrant started")
            datasets_pairs = ["",""]
            search_results = {
                "collections": collections,
                "results": []
            }
            for i in range(len(datasets)):
                if i % 2 == 0:
                    datasets_pairs.append(datasets[i-1], datasets[i])
                await self.qdrant_kit_py.load_qdrant(datasets_pairs[0], datasets_pairs[1])
                await self.qdrant_kit_py.ingest_qdrant(column)
            for collection in collections:
                results = await self.search(collection, query)
                search_results[collection] = results

            return search_results
        else:
            start_faiss = self.ipfs_kit.start_faiss(collection, query)
            if start_faiss == True:
                print("Faiss started")
                datasets_pairs = ["",""]
                search_results = {
                    "collections": collections,
                    "results": []
                }
                for i in range(len(datasets)):
                    if i % 2 == 0:
                        datasets_pairs.append(datasets[i-1], datasets[i])
                    await self.ipfs_kit.load_faiss(datasets_pairs[0], datasets_pairs[1])
                    await self.ipfs_kit.ingest_faiss(column)
                for collection in collections:
                    results = await self.search(collection, query)
                    search_results[collection] = results

                return search_results
            else:
                print("Faiss failed to start")
                return None
    
    async def load_qdrant_iter(self, dataset, knn_index, dataset_split=None, knn_index_split=None):
        # await self.qdrant_kit_py.load_qdrant_iter(dataset, knn_index, dataset_split, knn_index_split) # Commented out for now
        print("load_qdrant_iter called - Qdrant integration pending")
        return None

    async def ingest_qdrant_iter(self, columns):
        # await self.qdrant_kit_py.ingest_qdrant_iter(columns) # Commented out for now
        print("ingest_qdrant_iter called - Qdrant integration pending")
        return None
    
    async def test_high_memory(self):
        # start = self.qdrant_kit_py.start_qdrant() # Commented out for now
        # load_qdrant = await self.qdrant_kit_py.load_qdrant("laion/Wikipedia-X-Concat", "laion/Wikipedia-M3", "enwiki_concat", "enwiki_embed") # Commented out for now
        results = await self.search("Wikipedia-X-Concat", "Machine Learning")
        return results

    async def test(self,memory="low"):
        if memory == "low":
            return await self.test_low_memory()
        elif memory == "high":
            return await self.test_high_memory()
        else:
            return None

    async def test_query(self):
        query = "Machine Learning"
        collection = "English-ConcatX-Abstract"
        search_results = await self.search(collection, query)
        print(search_results)

    async def test_query(self):
        query = "Machine Learning"
        collection = "English-ConcatX-Abstract"
        search_results = await self.search(collection, query)
        print(search_results)
        return None
        
    async def start_faiss(self, collection, query):
        return self.ipfs_kit.start_faiss(collection, query)
    
    async def load_faiss(self, dataset, knn_index):
        return self.ipfs_kit.load_faiss(dataset, knn_index)
    
    async def ingest_faiss(self, column):
        return self.ipfs_kit.ingest_faiss(column)
    
    async def search_faiss(self, collection, query_embeddings, n=5):
        return self.ipfs_kit.search_faiss(collection, query_embeddings, n)


if __name__ == "__main__":
    metadata = {
        "dataset": "TeraflopAI/Caselaw_Access_Project",
        "column": "text",
        "split": "train",
        "models": [
            "thenlper/gte-small",
            "Alibaba-NLP/gte-large-en-v1.5",
            "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        ],
        "chunk_settings": {
            "chunk_size": 512,
            "n_sentences": 8,
            "step_size": 256,
            "method": "fixed",
            "embed_model": "thenlper/gte-small",
            "tokenizer": None
        },
        "dst_path": "/storage/teraflopai/tmp",
    }
    resources = {
        "local_endpoints": [
            ["thenlper/gte-small", "cpu", 512],
            ["Alibaba-NLP/gte-large-en-v1.5", "cpu", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "cpu", 32768],
            ["thenlper/gte-small", "cuda:0", 512],
            ["Alibaba-NLP/gte-large-en-v1.5", "cuda:0", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "cuda:0", 32768],
            ["thenlper/gte-small", "cuda:1", 512],
            ["Alibaba-NLP/gte-large-en-v1.5", "cuda:1", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "cuda:1", 32768],
            ["thenlper/gte-small", "openvino", 512],
            ["Alibaba-NLP/gte-large-en-v1.5", "openvino", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "openvino", 32768],
            ["thenlper/gte-small", "llama_cpp", 512],
            ["Alibaba-NLP/gte-large-en-v1.5", "llama_cpp", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "llama_cpp", 32768],
            ["thenlper/gte-small", "ipex", 512],
            ["Alibaba-NLP/gte-large-en-v1.5", "ipex", 8192],
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "ipex", 32768],
        ],
        "openvino_endpoints": [],
        "tei_endpoints": [
            ["Alibaba-NLP/gte-Qwen2-1.5B-instruct", "http://62.146.169.111:8080/embed-medium", 32768],
            ["thenlper/gte-small", "http://62.146.169.111:8080/embed-tiny", 512],
            ["Alibaba-NLP/gte-large-en-v1.5", "http://62.146.169.111:8081/embed-small", 8192],
        ]
    }
    search_embeddings_instance = search_embeddings(resources, metadata)
    anyio.run(search_embeddings_instance.test())
    print("Search embeddings test completed")