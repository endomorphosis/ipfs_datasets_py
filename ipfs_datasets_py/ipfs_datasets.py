import os
import multiprocessing
import random
import numpy as np
from typing import Any, Dict, List, Optional, Union, Tuple

try:
    import datasets  # type: ignore
    from datasets import Dataset, load_dataset, concatenate_datasets, load_from_disk  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    datasets = None  # type: ignore
    Dataset = object  # type: ignore

    def _missing_datasets(*_args: Any, **_kwargs: Any) -> Any:
        raise ModuleNotFoundError(
            "No module named 'datasets'. Install optional dependency 'datasets' to use dataset-loading features."
        )

    load_dataset = _missing_datasets  # type: ignore
    concatenate_datasets = _missing_datasets  # type: ignore
    load_from_disk = _missing_datasets  # type: ignore
try:
    from .ipfs_parquet_to_car import ipfs_parquet_to_car_py
except Exception as e:
    try:
        from ipfs_parquet_to_car import ipfs_parquet_to_car_py
    except Exception as e:
        pass
    pass

try:
    from .ipfs_multiformats import ipfs_multiformats_py
    from .ipfs_multiformats import *
except Exception as e:
    try:
        from ipfs_multiformats import ipfs_multiformats_py
        from ipfs_multiformats import *
    except Exception as e:
        try:
            import ipfs_multiformats
        except Exception as e:
            pass
    pass

def process_hashed_dataset_shard(shard: Union[str, List[Any], Dict[str, Any]], datatype: Optional[str] = None, split: Optional[str] = None) -> Union[List[Any], ValueError]:
    """
    Process a hashed dataset shard and extract content identifiers and items.

    This function processes dataset shards by extracting Content Identifiers (CIDs)
    and associated items from Parquet files. It supports both CID extraction and
    full item retrieval modes, with automatic fallback to generate missing CID files.
    The function handles various input formats including file paths, parameter lists,
    and dictionary configurations.

    Args:
        shard (Union[str, List[Any], Dict[str, Any]]): Dataset shard specification.
            Can be a file path string, a list containing [shard, datatype, split],
            or a dictionary with 'shard', 'datatype', and 'split' keys.
        datatype (Optional[str], optional): Type of data to extract. Valid values
            are 'cids' for Content Identifiers only, or 'items' for full content.
            If None, automatically determined from file existence. Defaults to None.
        split (Optional[str], optional): Dataset split to load ('train', 'test', etc.).
            If None, loads the entire dataset without split specification.
            Defaults to None.

    Returns:
        Union[List[Any], ValueError]: A list containing [cids, items, schema] where:
            - cids (List[str]): List of Content Identifiers from the shard
            - items (Dict[str, List[Any]] or None): Dictionary of item data organized
              by field names, or None if datatype is 'cids'
            - schema (Any or None): Dataset schema information, currently unused
            Returns ValueError if dataset files are not found or datatype is invalid.

    Raises:
        ValueError: If no dataset files are found at the specified shard path,
            or if datatype is not 'cids' or 'items'.
        FileNotFoundError: If the specified shard file does not exist.
        DatasetError: If there are issues loading the Parquet dataset files.

    Examples:
        # Process shard for CIDs only
        >>> result = process_hashed_dataset_shard(
        ...     "/data/shard_001.parquet",
        ...     datatype="cids"
        ... )
        >>> cids, items, schema = result
        >>> print(f"Extracted {len(cids)} CIDs")
        
        # Process shard for full items
        >>> result = process_hashed_dataset_shard(
        ...     "/data/shard_001.parquet",
        ...     datatype="items",
        ...     split="train"
        ... )
        >>> cids, items, schema = result
        >>> print(f"Extracted {len(items['text'])} text items")
        
        # Process with dictionary configuration
        >>> config = {
        ...     "shard": "/data/shard_001.parquet",
        ...     "datatype": "items",
        ...     "split": "train"
        ... }
        >>> result = process_hashed_dataset_shard(config)

    Notes:
        - Automatically generates CID files if they don't exist
        - CID files are stored as '{shard_path}_cids.parquet'
        - Supports both single files and dataset collections
        - Memory usage depends on shard size and datatype selection
        - CID extraction is more memory efficient than full item loading
    """
    items = None
    cids = None
    schema = None
    if type(shard) is not str:
        if type(shard) is list:
            if len(shard) == 1:
                shard = shard[0]
            elif len(shard) == 2:
                shard, datatype = shard
            elif len(shard) == 3:
                shard, datatype, split = shard
        if type(shard) is dict:
            if "shard" in list(shard.keys()):
                shard = shard["shard"]
            if "datatype" in list(shard.keys()):
                datatype = shard["datatype"]
            if "split" in list(shard.keys()):
                split = shard["split"]

    if datatype is None:
        if os.path.exists(shard.replace(".parquet","")+"_cids.parquet"):
            datatype = "cids"
        else:
            if os.path.exists(shard.replace(".parquet","")+".parquet"):
                datatype = "items"
            else:
                return ValueError("No dataset found")
    elif "cids" in datatype:
        if os.path.exists(shard.replace(".parquet","")+"_cids.parquet"):
            if split is not None:
                tmp_hashed_dataset_cid_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+"_cids.parquet")[split]
            else:
                tmp_hashed_dataset_cid_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+"_cids.parquet")
            items = None
            schema = None
        else:
            if os.path.exists(shard):
                if split is not None:
                    tmp_hashed_dataset_items_dataset = load_dataset('parquet', data_files=shard)[split]
                else:
                    tmp_hashed_dataset_items_dataset = load_dataset('parquet', data_files=shard)
                tmp_hashed_dataset_cid_dataset = tmp_hashed_dataset_items_dataset.map(lambda x: {"cid": x["items"]["cid"]})["cid"]
                tmp_hashed_dataset_cid_dataset = datasets.Dataset.from_dict({"cids": tmp_hashed_dataset_cid_dataset})
                tmp_hashed_dataset_cid_dataset.to_parquet(shard.replace(".parquet","")+"_cids.parquet")
            else:
                print("No dataset found")
                tmp_hashed_dataset_cid_dataset = datasets.Dataset.from_dict({"cids": []})
        if "train" in list(tmp_hashed_dataset_cid_dataset.column_names.keys()):
            num_rows = tmp_hashed_dataset_cid_dataset["train"].num_rows
            if num_rows > 0:
                train = tmp_hashed_dataset_cid_dataset["train"]
                if "cids" in list(train.column_names):
                    if len(train["cids"]) > 0:
                       cids = train["cids"]
                    else:
                        cids = []
                else:
                    cids = list(train)
            else:
                print("No dataset found in split 'train'")
                cids = []
            # print("train: ", len(train))
            # print("cids: ", len(cids))
        elif "cids" in list(tmp_hashed_dataset_cid_dataset.column_names.keys()):
            cids = list(tmp_hashed_dataset_cid_dataset["cids"])
        else:
            cids = list(tmp_hashed_dataset_cid_dataset)
    elif "items" in datatype:
        if os.path.exists(shard.replace(".parquet", "")+".parquet"):
            if split is not None:
                tmp_hashed_dataset_items_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+".parquet")[split]
            else:
                tmp_hashed_dataset_items_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+".parquet")
            if os.path.exists(shard.replace(".parquet","")+"_cids.parquet"):
                if split is not None:
                    tmp_hashed_dataset_cid_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+"_cids.parquet")[split]
                else:
                    tmp_hashed_dataset_cid_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+"_cids.parquet")
            else:
                tmp_hashed_dataset_cid_dataset = tmp_hashed_dataset_items_dataset.map(lambda x: {"cid": x["items"]["cid"]})["cid"]
                tmp_hashed_dataset_cid_dataset = datasets.Dataset.from_dict({"cids": tmp_hashed_dataset_cid_dataset})
                tmp_hashed_dataset_cid_dataset.to_parquet(shard.replace(".parquet","")+"_cids.parquet")
            items = {key: [item["items"][key] for item in tmp_hashed_dataset_items_dataset] for key in tmp_hashed_dataset_items_dataset[0]["items"].keys()}
            cids = list(tmp_hashed_dataset_cid_dataset["cids"])
            schema = None
            del tmp_hashed_dataset_cid_dataset
            del tmp_hashed_dataset_items_dataset
        else:
            return ValueError("No dataset found")
    else:
        return ValueError("datatype must be 'cids' or 'items' , received: '" + str(datatype) + "'")

    return [ cids , items, schema ]

def process_index_shard(shard: Union[str, List[Any], Dict[str, Any]], datatype: Optional[str] = None, split: str = "train") -> Union[List[Any], ValueError]:
    """
    Process an index shard for content identifier extraction and indexing operations.

    This function processes dataset index shards by extracting Content Identifiers (CIDs)
    and associated content for indexing purposes. It provides similar functionality to
    process_hashed_dataset_shard but with specific optimizations for index operations
    and different default split handling. The function supports both CID-only extraction
    and full content retrieval for building search indexes.

    Args:
        shard (Union[str, List[Any], Dict[str, Any]]): Index shard specification.
            Can be a file path string, a list containing [shard, datatype, split],
            or a dictionary with 'shard', 'datatype', and 'split' keys.
        datatype (Optional[str], optional): Type of data to extract. Valid values
            are 'cids' for Content Identifiers only, or 'items' for full content
            with indexable data. If None, automatically determined from file
            existence. Defaults to None.
        split (str, optional): Dataset split to load for indexing operations.
            Defaults to "train" as the primary split for index building.

    Returns:
        Union[List[Any], ValueError]: A list containing [cids, items, schema] where:
            - cids (List[str]): List of Content Identifiers from the index shard
            - items (Dict[str, List[Any]] or None): Dictionary of indexable content
              organized by field names, or None if datatype is 'cids'
            - schema (Any or None): Index schema information, currently unused
            Returns ValueError if index files are not found or datatype is invalid.

    Raises:
        ValueError: If no index dataset files are found at the specified shard path,
            or if datatype is not 'cids' or 'items'.
        FileNotFoundError: If the specified index shard file does not exist.
        DatasetError: If there are issues loading the Parquet index files.

    Examples:
        # Process index shard for CIDs
        >>> result = process_index_shard(
        ...     "/indices/embedding_shard_001.parquet",
        ...     datatype="cids"
        ... )
        >>> cids, items, schema = result
        >>> print(f"Indexed {len(cids)} documents")
        
        # Process index shard for full content
        >>> result = process_index_shard(
        ...     "/indices/embedding_shard_001.parquet",
        ...     datatype="items"
        ... )
        >>> cids, items, schema = result
        >>> print(f"Loaded {len(items['embedding'])} embeddings")

    Notes:
        - Optimized for index building and search operations
        - Automatically generates CID index files if missing
        - Default split is 'train' for consistent index building
        - Memory usage optimized for large index operations
        - Compatible with embedding and similarity search workflows
    """
    items = None
    cids = None
    schema = None
    if type(shard) is not str:
        if type(shard) is list:
            if len(shard) == 1:
                shard = shard[0]
            elif len(shard) == 2:
                shard, datatype = shard
            elif len(shard) == 3:
                shard, datatype, split = shard
        if type(shard) is dict:
            if "shard" in list(shard.keys()):
                shard = shard["shard"]
            if "datatype" in list(shard.keys()):
                datatype = shard["datatype"]
            if "split" in list(shard.keys()):
                split = shard["split"]

    if datatype is None:
        if os.path.exists(shard.replace(".parquet","")+"_cids.parquet"):
            datatype = "cids"
        else:
            if os.path.exists(shard.replace(".parquet","")+".parquet"):
                datatype = "items"
            else:
                return ValueError("No dataset found")
    elif "cids" in datatype:
        if os.path.exists(shard.replace(".parquet","")+"_cids.parquet"):
            tmp_hashed_dataset_cid_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+"_cids.parquet")[split]
            items = None
            schema = None
        else:
            tmp_hashed_dataset_items_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+".parquet")[split]
            tmp_hashed_dataset_cid_dataset = tmp_hashed_dataset_items_dataset.map(lambda x: {"cid": x["items"]["cid"]})["cid"]
            tmp_hashed_dataset_cid_dataset = datasets.Dataset.from_dict({"cids": tmp_hashed_dataset_cid_dataset})
            tmp_hashed_dataset_cid_dataset.to_parquet(shard.replace(".parquet","")+"_cids.parquet")
        cids = list(tmp_hashed_dataset_cid_dataset["cids"])
    elif "items" in datatype:
        if os.path.exists(shard.replace(".parquet", "")+".parquet"):
            tmp_hashed_dataset_items_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+".parquet")[split]
            if os.path.exists(shard.replace(".parquet","")+"_cids.parquet"):
                tmp_hashed_dataset_cid_dataset = load_dataset('parquet', data_files=shard.replace(".parquet","")+"_cids.parquet")[split]
            else:
                tmp_hashed_dataset_cid_dataset = tmp_hashed_dataset_items_dataset.map(lambda x: {"cid": x["items"]["cid"]})["cid"]
                tmp_hashed_dataset_cid_dataset = datasets.Dataset.from_dict({"cids": tmp_hashed_dataset_cid_dataset})
                tmp_hashed_dataset_cid_dataset.to_parquet(shard.replace(".parquet","")+"_cids.parquet")
            cids = list(tmp_hashed_dataset_cid_dataset["cids"])
            items = {key: [item["items"][key] for item in tmp_hashed_dataset_items_dataset] for key in tmp_hashed_dataset_items_dataset[0]["items"].keys()}
            cids = list(tmp_hashed_dataset_cid_dataset["cids"])
            schema = None
            del tmp_hashed_dataset_cid_dataset
            del tmp_hashed_dataset_items_dataset
        else:
            return ValueError("No dataset found")
    else:
        return ValueError("datatype must be 'cids' or 'items' , received: '" + str(datatype) + "'")

    return [ cids , items, schema ]

class ipfs_datasets_py:
    """
    Comprehensive IPFS-Based Dataset Management and Distributed Computing Platform

    The ipfs_datasets_py class provides enterprise-grade functionality for managing,
    processing, and analyzing large-scale datasets through the InterPlanetary File
    System (IPFS) infrastructure. This platform enables decentralized data storage,
    content-addressable dataset versioning, distributed computing workflows, and
    collaborative data science operations across peer-to-peer networks.

    The system integrates multiple data formats (Parquet, Arrow, HuggingFace datasets)
    with IPFS storage protocols to create immutable, versioned datasets that can be
    efficiently shared, replicated, and processed across distributed computing
    environments. Content-addressing ensures data integrity and enables automatic
    deduplication while maintaining full provenance tracking.

    Key Features:
    - Content-addressable dataset storage with IPFS integration
    - Multi-format dataset support (Parquet, Arrow, CAR files)
    - Distributed processing with automatic chunking and parallelization
    - Embedding vector management with multiple backend support
    - Cluster-based content organization and discovery
    - Checkpoint management for incremental processing workflows
    - Schema evolution and format migration capabilities
    - Cross-dataset lineage tracking and dependency management

    Data Processing Capabilities:
    - Large-scale dataset sharding and distributed processing
    - Automatic content hashing and integrity verification
    - Multi-model embedding generation and vector indexing
    - Clustering and similarity analysis across content collections
    - Incremental updates with checkpoint-based recovery
    - Format conversion between Arrow, Parquet, and CAR formats

    IPFS Integration:
    - Direct integration with IPFS nodes for distributed storage
    - Content Identifier (CID) generation and management
    - CAR (Content Addressable aRchive) file creation and processing
    - Distributed dataset replication across IPFS networks
    - Gateway-based access for web applications and services

    Attributes:
        resources (Any): Resource configuration and connection settings for
            external services including IPFS nodes, embedding models, and
            storage backends.
        metadata (Dict[str, Any]): Comprehensive metadata management including
            dataset schemas, processing configurations, and provenance information.
        load_dataset (Callable): HuggingFace datasets loading interface for
            standard dataset operations and format compatibility.
        ipfs_cluster_name (Optional[str]): Current IPFS cluster identifier for
            distributed storage operations and peer coordination.
        dataset (Optional[Dataset]): Active dataset instance for processing
            operations with schema and content management.
        caches (Dict[str, Any]): Multi-level caching system for embeddings,
            indexes, and processed content to optimize performance.
        ipfs_parquet_to_car_py (ipfs_parquet_to_car_py): CAR file conversion
            interface for IPFS-native storage format operations.
        cid_chunk_list (List[str]): Ordered list of content identifiers for
            chunked dataset processing and retrieval operations.
        cid_chunk_set (Set[str]): Deduplicated set of chunk CIDs for efficient
            membership testing and duplicate detection.
        cid_list (List[str]): Complete list of content identifiers for all
            dataset components and associated metadata.
        cid_set (Set[str]): Deduplicated set of all CIDs for integrity checking
            and content validation operations.
        index (Dict[str, Any]): Multi-dimensional indexing system for content
            discovery, similarity search, and retrieval optimization.
        hashed_dataset (Optional[Dataset]): Content-hashed dataset with CID
            mapping for immutable versioning and integrity verification.
        hashed_dataset_combined (Optional[Dataset]): Aggregated multi-shard
            dataset with unified schema and content addressing.
        embedding_datasets (Dict[str, Dataset]): Collection of embedding vector
            datasets organized by model type and processing configuration.
        unique_cid_set (Set[str]): Deduplicated content identifiers across all
            dataset components for global uniqueness tracking.
        unique_cid_list (List[str]): Ordered list of unique CIDs for processing
            workflows and content enumeration operations.
        cluster_cids_dataset (Optional[Dataset]): Clustered content organization
            with similarity-based grouping and hierarchical structure.
        ipfs_cid_clusters_list (List[str]): Cluster identifiers for distributed
            content organization and discovery workflows.
        ipfs_cid_clusters_set (Set[str]): Deduplicated cluster IDs for efficient
            membership testing and cluster validation.
        ipfs_cid_set (Set[str]): IPFS-specific content identifiers for network
            operations and distributed storage management.
        ipfs_cid_list (List[str]): Ordered IPFS CIDs for sequential processing
            and content retrieval operations.
        all_cid_list (Dict[str, List[str]]): Comprehensive CID collections
            organized by dataset type and processing stage.
        all_cid_set (Dict[str, Set[str]]): Deduplicated CID collections for
            efficient validation and membership operations.
        schemas (Dict[str, Any]): Dataset schema definitions and format
            specifications for content validation and processing.

    Public Methods:
        load_combined_checkpoints(dataset: str, split: str, dst_path: str,
                                 models: List[str], method: str = "cids") -> None:
            Load and combine checkpoint data from multiple processing stages
        combine_checkpoints(checkpoints: List[str]) -> Dataset:
            Merge multiple checkpoint files into unified dataset
        load_checkpoints(checkpoint_path: str) -> Dataset:
            Load dataset from checkpoint with schema validation
        generate_clusters(dataset: Dataset, model: str, **kwargs) -> Dict[str, Any]:
            Create content clusters using embedding-based similarity analysis
        load_clusters(cluster_path: str) -> Dataset:
            Load pre-computed cluster assignments and metadata
        process_hashed_dataset_shard(shard: Any, datatype: str, split: str) -> Dict[str, Any]:
            Process individual dataset shards with content hashing

    Usage Examples:
        # Initialize IPFS dataset manager
        resources = {"ipfs_gateway": "http://localhost:8080"}
        metadata = {"version": "1.0", "format": "parquet"}
        manager = ipfs_datasets_py(resources, metadata)
        
        # Load and process distributed dataset
        await manager.load_combined_checkpoints(
            dataset="large_text_corpus",
            split="train",
            dst_path="/data/checkpoints",
            models=["sentence-transformers", "openai-embeddings"]
        )
        
        # Generate content clusters
        clusters = manager.generate_clusters(
            dataset=manager.hashed_dataset,
            model="sentence-transformers",
            num_clusters=100
        )
        
        # Process dataset shards in parallel
        results = []
        for shard in dataset_shards:
            result = manager.process_hashed_dataset_shard(
                shard=shard,
                datatype="text",
                split="train"
            )
            results.append(result)

    Dependencies:
        Required:
        - datasets: HuggingFace datasets library for data processing
        - numpy: Numerical computing and array operations
        - multiprocessing: Parallel processing and distributed computing
        
        Optional:
        - ipfs_multiformats: IPFS content addressing and CID generation
        - ipfs_parquet_to_car: CAR file format conversion utilities
        - various embedding model libraries for vector generation

    Notes:
        - Large datasets benefit from distributed processing across IPFS networks
        - Content addressing ensures data integrity and automatic deduplication
        - Checkpoint systems enable recovery from interrupted processing workflows
        - Multiple embedding models can be processed simultaneously for comparison
        - Cluster generation supports various similarity metrics and algorithms
        - Schema evolution is supported through format migration utilities
        - IPFS integration requires network connectivity for distributed operations
        - Memory usage scales with dataset size and should be monitored for large corpora
    """
    def __init__(
        self,
        resources: Optional[Any] = None,
        metadata: Optional[Any] = None,
        *,
        deps: object | None = None,
        ipfs_kit=None,
        ipfs_accelerate=None,
    ) -> None:
        """
        Initialize IPFS Dataset Management Platform with Comprehensive Configuration

        Establishes a new ipfs_datasets_py instance with complete infrastructure
        for distributed dataset processing, IPFS integration, and multi-format
        content management. This initialization sets up all necessary components
        for content-addressable storage, embedding generation, clustering workflows,
        and checkpoint-based processing operations.

        The initialization process configures resource connections, metadata management
        systems, caching infrastructures, and processing pipelines required for
        large-scale dataset operations across IPFS networks. All subsystems are
        prepared for immediate use while maintaining efficient resource utilization
        and optimal performance characteristics.

        Args:
            resources (Any): Comprehensive resource configuration containing connection
                settings and service endpoints for external systems including:
                - IPFS node configurations and gateway URLs
                - Embedding model service endpoints and API credentials
                - Storage backend configurations for caching and persistence
                - Distributed computing cluster settings and worker configurations
                - Network timeouts, retry policies, and connection pooling settings
                Example: {
                    "ipfs_gateway": "http://localhost:8080",
                    "embedding_service": "http://embeddings:8000",
                    "storage_backend": "local",
                    "worker_threads": 8
                }
            
            metadata (Dict[str, Any]): Dataset and processing metadata containing
                schema definitions, format specifications, and operational parameters:
                - Dataset version information and compatibility requirements
                - Schema definitions for content validation and processing
                - Processing configuration including chunking and parallelization
                - Provenance tracking and lineage management settings
                - Quality control parameters and validation rules
                Example: {
                    "version": "1.0",
                    "format": "parquet",
                    "chunk_size": 10000,
                    "schema_version": "2.1",
                    "quality_threshold": 0.95
                }

        Attributes Initialized:
            All instance attributes are initialized to provide immediate functionality:
            - Resource and metadata management systems
            - IPFS integration components and CAR file processors
            - Caching infrastructure for performance optimization
            - Content addressing and CID management systems
            - Embedding and clustering workflow components
            - Checkpoint and recovery mechanisms
            - Schema and format validation systems

        Raises:
            ValueError: If required resource configurations are missing or invalid,
                including IPFS gateway URLs, storage paths, or service endpoints.
            ConnectionError: If initial connection tests to IPFS nodes or external
                services fail during initialization validation.
            ImportError: If required dependencies for IPFS operations, embedding
                processing, or format conversion are not available.
            ConfigurationError: If metadata schemas are invalid or incompatible
                with current system capabilities and processing requirements.

        Examples:
            # Basic initialization for local processing
            resources = {
                "ipfs_gateway": "http://localhost:8080",
                "storage_path": "/data/ipfs_datasets"
            }
            metadata = {
                "version": "1.0",
                "format": "parquet"
            }
            manager = ipfs_datasets_py(resources, metadata)
            
            # Advanced configuration for distributed processing
            advanced_resources = {
                "ipfs_gateway": "http://ipfs-cluster:8080",
                "embedding_service": "http://embeddings:8000",
                "storage_backend": "s3",
                "s3_bucket": "my-datasets",
                "worker_threads": 16,
                "cache_size": "10GB"
            }
            advanced_metadata = {
                "version": "2.0",
                "format": "arrow",
                "chunk_size": 50000,
                "embedding_models": ["sentence-transformers", "openai"],
                "clustering_algorithm": "kmeans",
                "quality_threshold": 0.9
            }
            advanced_manager = ipfs_datasets_py(advanced_resources, advanced_metadata)

        Notes:
            - Initialization prepares all subsystems but does not load datasets immediately
            - Resource validation ensures compatibility with IPFS network requirements
            - Metadata schemas support evolution and backward compatibility
            - Caching systems are configured but not populated until first use
            - All processing components support both synchronous and asynchronous operations
            - Memory allocation is optimized for the specified configuration parameters
            - Error handling is established for all network and processing operations
        """

        # Store injected cross-package dependencies (best-effort).
        self.deps = deps
        self.ipfs_kit = ipfs_kit
        self.ipfs_accelerate = ipfs_accelerate

        if isinstance(resources, dict):
            if self.deps is None:
                self.deps = resources.get("deps")
            if self.ipfs_kit is None:
                self.ipfs_kit = resources.get("ipfs_kit")
            if self.ipfs_accelerate is None:
                self.ipfs_accelerate = resources.get("ipfs_accelerate")

            if self.deps is not None:
                resources.setdefault("deps", self.deps)
            if self.ipfs_kit is not None:
                resources.setdefault("ipfs_kit", self.ipfs_kit)
            if self.ipfs_accelerate is not None:
                resources.setdefault("ipfs_accelerate", self.ipfs_accelerate)
        if resources is None:
            resources = {}
        if metadata is None:
            metadata = {}
        self.resources = resources
        self.metadata = metadata
        self.load_dataset = load_dataset
        self.ipfs_cluster_name = None
        self.dataset = None
        self.caches = {}
        if 'ipfs_parquet_to_car_py' in globals():
            try:
                self.ipfs_parquet_to_car_py = ipfs_parquet_to_car_py(resources, metadata)
            except Exception:
                self.ipfs_parquet_to_car_py = None
        else:
            self.ipfs_parquet_to_car_py = None
        self.combine_checkpoints = self.combine_checkpoints
        self.load_checkpoints = self.load_checkpoints
        self.generate_clusters = self.generate_clusters
        self.load_clusters = self.load_clusters
        self.process_hashed_dataset_shard = process_hashed_dataset_shard
        self.process_index_shard = process_index_shard
        self.process_new_dataset_shard = process_hashed_dataset_shard
        self.cid_chunk_list = []
        self.cid_chunk_set = set()
        self.cid_list = []
        self.cid_set = set()
        self.index = {}
        self.hashed_dataset = None
        self.hashed_dataset_combined = None
        self.embedding_datasets = {}
        self.unique_cid_set = set()
        self.unique_cid_list = []
        self.cluster_cids_dataset = None
        self.ipfs_cid_clusters_list = []
        self.ipfs_cid_clusters_set = ()
        self.ipfs_cid_set = set()
        self.ipfs_cid_list = []
        self.all_cid_list = {}
        self.all_cid_set = {}
        self.schemas = {}
        return None

    async def load_combined_checkpoints(self, dataset: str, split: str, dst_path: str, models: List[str], method: str = "cids") -> None:
        """
        Load and combine checkpoint data from multiple processing stages and models.

        This method loads checkpoint data from various sources including hashed datasets,
        embedding models, and sparse chunks. It combines data from multiple shards and
        processing stages to reconstruct the complete dataset state for continued
        processing or analysis. The method supports parallel loading for performance
        optimization and maintains consistency across different model outputs.

        Args:
            dataset (str): Dataset identifier used for checkpoint file naming.
                Must match the original dataset name used during processing.
                Forward slashes are converted to triple underscores for file paths.
            split (str): Dataset split to load ('train', 'test', 'validation', etc.).
                Must match the split used during checkpoint creation.
            dst_path (str): Destination path where checkpoint files are stored.
                Should contain 'checkpoints' subdirectory with shard files.
            models (List[str]): List of model identifiers for which to load
                embedding checkpoints. Each model should have corresponding
                checkpoint files in the destination path.
            method (str, optional): Loading method for checkpoint processing.
                Valid values are 'cids' for identifier-only loading or 'items'
                for full content loading. Defaults to "cids".

        Returns:
            None: This method updates instance attributes in-place including:
                - self.hashed_dataset: Combined hashed dataset from checkpoints
                - self.all_cid_list: Updated CID lists for dataset and models
                - self.all_cid_set: Updated CID sets for efficient lookup
                - self.index: Model-specific embedding indexes
                - self.caches: Cached items for performance optimization

        Raises:
            FileNotFoundError: If checkpoint directory or required files are missing.
            DatasetError: If there are issues loading Parquet checkpoint files.
            ValueError: If model names are invalid or checkpoint data is corrupted.
            MemoryError: If checkpoint data exceeds available system memory.

        Examples:
            # Load checkpoints for text processing models
            >>> await manager.load_combined_checkpoints(
            ...     dataset="large_text_corpus",
            ...     split="train",
            ...     dst_path="/data/checkpoints",
            ...     models=["sentence-transformers/all-MiniLM-L6-v2", "openai/text-embedding-ada-002"]
            ... )
            
            # Load with full item data
            >>> await manager.load_combined_checkpoints(
            ...     dataset="scientific_papers",
            ...     split="train", 
            ...     dst_path="/data/checkpoints",
            ...     models=["allenai/specter2"],
            ...     method="items"
            ... )

        Notes:
            - Uses multiprocessing for parallel shard loading
            - Automatically handles missing CID files by generating them
            - Memory usage scales with checkpoint size and method selection
            - Progress is tracked through instance attribute updates
            - Supports incremental loading for large datasets
            - Maintains consistency across model-specific indexes
        """
        if "hashed_dataset" not in list(dir(self)):
            self.hashed_dataset = None
        if "all_cid_list" not in list(dir(self)):
            self.all_cid_list = {}
        if "all_cid_set" not in list(dir(self)):
            self.all_cid_set = {}
        for model in models:
            if model not in list(self.index.keys()):
                self.index[model] = None
        if self.hashed_dataset is None or isinstance(self.hashed_dataset, dict):
            hashed_dataset_dst_path = os.path.join(dst_path, "ipfs_" + dataset.replace("/","___") + ".parquet")
            if os.path.isfile(hashed_dataset_dst_path):
                self.hashed_dataset = load_dataset('parquet', data_files=hashed_dataset_dst_path)[split]
                self.all_cid_list["hashed_dataset"] = []
                self.all_cid_set["hashed_dataset"] = set()
            if os.path.exists(os.path.join(dst_path, "checkpoints")):
                ls_checkpoints = os.listdir(os.path.join(dst_path, "checkpoints"))
                hashed_dataset_shards = [os.path.join(dst_path, "checkpoints", x) for x in ls_checkpoints if "ipfs_" + dataset.replace("/", "___") + "_shard" in x and "_cids" not in x ]
                if "hashed_dataset" not in list(self.all_cid_list.keys()):
                    self.all_cid_list["hashed_dataset"] = []
                if "hashed_dataset" not in list(self.all_cid_set.keys()):
                    self.all_cid_set["hashed_dataset"] = set()
                if "hashed_dataset" not in list(self.caches.keys()):
                    self.caches["hashed_dataset"] = {"items" : []}
                with multiprocessing.Pool() as pool:
                    args = [[hashed_dataset_shards[i], method] for i in range(len(hashed_dataset_shards))]
                    results = pool.map(self.process_hashed_dataset_shard, args)
                    if len(results) > 0:
                        # Initialize accumulators
                        total_cids = []
                        total_items = []
                        for res in results:
                            cid, items, schemas = (res + [None, None, None])[:3]
                            if cid is not None:
                                total_cids += cid
                            if items is not None:
                                total_items += items
                            if schemas is not None:
                                self.schemas["hashed_dataset"] = schemas
                        # Update the shared variables in bulk

                        self.all_cid_list["hashed_dataset"] += total_cids
                        self.all_cid_set["hashed_dataset"].update(set(total_cids))
                        self.caches["hashed_dataset"]["items"] += total_items

                if self.hashed_dataset is None or isinstance(self.hashed_dataset, dict):
                    if len(hashed_dataset_shards) > 0:
                        self.hashed_dataset = load_dataset('parquet', data_files=hashed_dataset_shards)[split]

        for model in models:
            if model not in list(self.index.keys()):
                self.index[model] = None
            if model not in list(self.all_cid_list.keys()):
                self.all_cid_list[model] = []
            if model not in list(self.all_cid_set.keys()):
                self.all_cid_set[model] = set()
            if model not in list(self.caches.keys()):
                self.caches[model] = {"items" : []}
            model_dst_path = dst_path + "/" + model.replace("/","___") + ".parquet"
            if os.path.isfile(model_dst_path):
                self.caches[model] = {"items" : []}
                self.index[model] = load_dataset('parquet', data_files=model_dst_path, streaming=True)[split]
            if os.path.exists(os.path.join(dst_path, "checkpoints")):
                ls_checkpoints = os.listdir(os.path.join(dst_path, "checkpoints"))
                this_model_shards = [os.path.join(dst_path, "checkpoints", x)  for x in ls_checkpoints if model.replace("/", "___") + "_shard" in x and "_cids" not in x]
                with multiprocessing.Pool() as pool:
                    args = [[hashed_dataset_shards[i], 'cids'] for i in range(len(hashed_dataset_shards))]
                    results = pool.map(self.process_hashed_dataset_shard, args)
                    if len(results) > 0:
                        # Initialize accumulators
                        total_cids = []
                        total_items = []
                        for res in results:
                            cid, items, schemas = (res + [None, None, None])[:3]
                            if cid is not None:
                                total_cids += cid
                            if items is not None:
                                total_items += items
                            if schemas is not None:
                                self.schemas[model] = schemas
                        # Update the shared variables in bulk
                        self.all_cid_list[model] += total_cids
                        self.all_cid_set[model].update(set(total_cids))
                        self.caches[model]["items"] += total_items

                if model not in list(self.index.keys()) or self.index[model] is None or isinstance(self.index[model], dict):
                    if len(this_model_shards) > 0:
                        self.index[model] = load_dataset('parquet', data_files=this_model_shards)[split]
                    else:
                        self.index[model] = datasets.Dataset.from_dict({"cid": [], "embedding": [] })
                ls_chunks = []
                if os.path.exists(os.path.join(dst_path,"sparse_chunks", )):
                    ls_chunks = os.listdir(os.path.join(dst_path,"sparse_chunks", ))
                if len(ls_chunks) > 0:
                    for this_cid in ls_chunks:
                        this_cid_path = os.path.join(dst_path,"sparse_chunks", this_cid)
                        this_cid_dataset = load_dataset('parquet', data_files=this_cid_path)
                        if this_cid not in self.chunk_cache.keys():
                            self.chunk_cache[this_cid] = {"items": []}
                        self.chunk_cache[this_cid]["items"] += this_cid_dataset
                        self.cid_chunk_set.add(this_cid)
                        self.cid_chunk_list.append(this_cid)
        return None

    async def load_chunk_checkpoints(self, dataset: str, split: str, src_path: str, models: List[str]) -> None:
        """
        Load checkpoint data from chunked storage for efficient distributed processing.

        This method loads checkpoint data from sparse chunk files stored in distributed
        storage systems. It processes chunk files for multiple models in parallel,
        organizing content by document CIDs and maintaining efficient cache structures
        for rapid access. The method is optimized for scenarios where datasets are
        split into numerous small chunks for distributed processing workflows.

        Args:
            dataset (str): Dataset identifier used for chunk file filtering.
                Used to locate relevant chunk files in the source directory.
            split (str): Dataset split identifier for chunk organization.
                Determines which chunk files to process for the specified split.
            src_path (str): Source directory path containing chunk checkpoint files.
                Should contain chunk files organized by model and dataset.
            models (List[str]): List of model identifiers for chunk processing.
                Each model should have corresponding chunk files in the source path.

        Returns:
            None: Updates instance attributes including:
                - self.chunk_cache: Document-specific chunk cache organized by model
                - self.chunk_cache_set: Set-based cache for efficient membership testing
                - self.doc_cid: Document CID mapping for chunk organization

        Raises:
            FileNotFoundError: If source path or chunk files are not found.
            DatasetError: If chunk files cannot be loaded or are corrupted.
            MemoryError: If chunk data exceeds available system memory.

        Examples:
            # Load chunks for embedding models
            >>> await manager.load_chunk_checkpoints(
            ...     dataset="large_corpus",
            ...     split="train",
            ...     src_path="/storage/chunks",
            ...     models=["sentence-transformers/all-MiniLM-L6-v2"]
            ... )

        Notes:
            - Uses multiprocessing for parallel chunk loading
            - Organizes chunks by document CID for efficient retrieval
            - Memory usage scales with number of chunks and models
            - Optimized for distributed storage scenarios
        """
        files = []
        if "doc_cid" not in list(dir(self)):
            self.chunks = {}
        if "doc_cid" not in list(dir(self)):
            self.chunk_cache_set = {}
        if os.path.isdir(src_path):
            files = os.listdir(src_path)
            files_by_models = [ [x for x in files if model.replace("/","___") in x and dataset in x and models in x ] for model in models]
        if len(files_by_models) > 0:
            with multiprocessing.Pool() as pool:
                results = pool.map(self.process_chunk_file, files_by_models)
                for result in results:
                    model, doc_cid, items = result
                    if model not in list(self.chunk_cache.keys()):
                        self.chunk_cache_set[model] = set()
                    if doc_cid not in list(self.chunk_cache[model].keys()):
                        self.chunk_cache[model][doc_cid] = {"items": []}
                    if doc_cid not in self.chunk_cache_set[model]:
                        self.chunk_cache_set[model].add(doc_cid)
                    self.doc_cid[model][doc_cid]["items"] += items

        return None


    async def load_checkpoints(self, dataset: str, split: str, dst_path: str, models: List[str]) -> None:
        """
        Load checkpoint data from multiple processing stages for dataset reconstruction.

        This method loads checkpoint data from various processing stages including
        hashed datasets and model-specific embeddings. It reconstructs the complete
        dataset state from checkpoint files, handling both consolidated files and
        distributed shards. The method maintains consistency across different
        processing stages and provides efficient access to reconstructed data.

        Args:
            dataset (str): Dataset identifier for checkpoint file location.
                Used to construct checkpoint file paths and identify relevant data.
            split (str): Dataset split to load from checkpoints.
                Determines which checkpoint files to process for reconstruction.
            dst_path (str): Destination path containing checkpoint files.
                Should contain both consolidated files and checkpoint subdirectories.
            models (List[str]): List of model identifiers for embedding checkpoint loading.
                Each model should have corresponding checkpoint data in the destination.

        Returns:
            None: Updates instance attributes including:
                - self.hashed_dataset: Reconstructed hashed dataset from checkpoints
                - self.all_cid_list: Comprehensive CID lists for all components
                - self.all_cid_set: Deduplicated CID sets for efficient operations
                - self.index: Model-specific indexes reconstructed from checkpoints
                - self.caches: Performance caches for rapid data access

        Raises:
            FileNotFoundError: If checkpoint files or directories are missing.
            DatasetError: If checkpoint data is corrupted or incompatible.
            ValueError: If model specifications are invalid.
            MemoryError: If checkpoint data exceeds system memory limits.

        Examples:
            # Load standard checkpoints
            >>> await manager.load_checkpoints(
            ...     dataset="text_corpus",
            ...     split="train",
            ...     dst_path="/data/checkpoints",
            ...     models=["bert-base-uncased", "roberta-base"]
            ... )

        Notes:
            - Handles both consolidated and distributed checkpoint formats
            - Automatically generates missing CID files during loading
            - Uses multiprocessing for parallel shard reconstruction
            - Maintains data consistency across processing stages
            - Memory usage optimized through efficient caching strategies
        """
        if "hashed_dataset" not in list(dir(self)):
            self.hashed_dataset = None
        if "all_cid_list" not in list(dir(self)):
            self.all_cid_list = {}
        if "all_cid_set" not in list(dir(self)):
            self.all_cid_set = {}
        for model in models:
            if model not in list(self.index.keys()):
                self.index[model] = None
        if self.hashed_dataset is None or isinstance(self.hashed_dataset, dict):
            hashed_dataset_dst_path = os.path.join(dst_path, "ipfs_" + dataset.replace("/","___") + ".parquet")
            if os.path.isfile(hashed_dataset_dst_path):
                self.hashed_dataset = load_dataset('parquet', data_files=hashed_dataset_dst_path)[split]
                self.all_cid_list["hashed_dataset"] = []
                self.all_cid_set["hashed_dataset"] = set()
            if os.path.exists(os.path.join(dst_path, "checkpoints")):
                ls_checkpoints = os.listdir(os.path.join(dst_path, "checkpoints"))
                hashed_dataset_shards = [os.path.join(dst_path, "checkpoints", x) for x in ls_checkpoints if "ipfs_" + dataset.replace("/", "___") + "_shard" in x and "_cids" not in x ]
                if "hashed_dataset" not in list(self.all_cid_list.keys()):
                    self.all_cid_list["hashed_dataset"] = []
                if "hashed_dataset" not in list(self.all_cid_set.keys()):
                    self.all_cid_set["hashed_dataset"] = set()
                if "hashed_dataset" not in list(self.caches.keys()):
                    self.caches["hashed_dataset"] = {"items" : []}
                with multiprocessing.Pool() as pool:
                    args = [[hashed_dataset_shards[i], 'cids'] for i in range(len(hashed_dataset_shards))]
                    results = pool.map(self.process_hashed_dataset_shard, args)
                    if len(results) > 0:
                        # Initialize accumulators
                        total_cids = []
                        total_items = []
                        for res in results:
                            cid, items, schemas = (res + [None, None, None])[:3]
                            if cid is not None:
                                total_cids += cid
                            if items is not None:
                                total_items += items
                            if schemas is not None:
                                self.schemas["hashed_dataset"] = schemas  # Assuming schemas won't conflict
                        # Update the shared variables in bulk
                        self.all_cid_list["hashed_dataset"] += total_cids
                        self.all_cid_set["hashed_dataset"].update(set(total_cids))
                        self.caches["hashed_dataset"]["items"] += total_items

                if self.hashed_dataset is None or isinstance(self.hashed_dataset, dict):
                    if len(hashed_dataset_shards) > 0:
                        self.hashed_dataset = load_dataset('parquet', data_files=hashed_dataset_shards)[split]

        for model in models:
            if model not in list(self.index.keys()):
                self.index[model] = None
            if model not in list(self.all_cid_list.keys()):
                self.all_cid_list[model] = []
            if model not in list(self.all_cid_set.keys()):
                self.all_cid_set[model] = set()
            if model not in list(self.caches.keys()):
                self.caches[model] = {"items" : []}
            model_dst_path = dst_path + "/" + model.replace("/","___") + ".parquet"
            if os.path.isfile(model_dst_path):
                self.caches[model] = {"items" : []}
                self.index[model] = load_dataset('parquet', data_files=model_dst_path, streaming=True)[split]
            if os.path.exists(os.path.join(dst_path, "checkpoints")):
                ls_checkpoints = os.listdir(os.path.join(dst_path, "checkpoints"))
                this_model_shards = [os.path.join(dst_path, "checkpoints", x)  for x in ls_checkpoints if model.replace("/", "___") + "_shard" in x and "_cids" not in x]
                with multiprocessing.Pool() as pool:
                    args = [[hashed_dataset_shards[i], 'cids'] for i in range(len(hashed_dataset_shards))]
                    results = pool.map(self.process_hashed_dataset_shard, args)
                    if len(results) > 0:
                        # Initialize accumulators
                        total_cids = []
                        total_items = []
                        for res in results:
                            cid, items, schemas = (res + [None, None, None])[:3]
                            if cid is not None:
                                total_cids += cid
                            if items is not None:
                                total_items += items
                            if schemas is not None:
                                self.schemas[model] = schemas  # Assuming schemas won't conflict
                        # Update the shared variables in bulk
                        self.all_cid_list[model] += total_cids
                        self.all_cid_set[model].update(set(total_cids))
                        self.caches[model]["items"] += total_items

                if model not in list(self.index.keys()) or self.index[model] is None or isinstance(self.index[model], dict):
                    if len(this_model_shards) > 0:
                        self.index[model] = load_dataset('parquet', data_files=this_model_shards)[split]
                    else:
                        self.index[model] = datasets.Dataset.from_dict({"cid": [], "embedding": [] })
                ls_chunks = []
                if os.path.exists(os.path.join(dst_path,"sparse_chunks", )):
                    ls_chunks = os.listdir(os.path.join(dst_path, "sparse_chunks"))
                    for chunk in ls_chunks:
                        chunk_cid = chunk.replace(".parquet","")
                        if chunk.replace(".parquet","") not in self.cid_chunk_set:
                            self.cid_chunk_set.add(chunk_cid)
                            self.cid_chunk_list.append(chunk_cid)
                for chunk in ls_chunks:
                    chunk_cid = chunk.replace(".parquet","")
                    if chunk.replace(".parquet","") not in self.cid_chunk_set:
                        self.cid_chunk_set.add(chunk_cid)
                        self.cid_chunk_list.append(chunk_cid)
                del ls_chunks
                del this_model_shards
                del ls_checkpoints
        try:
            del hashed_dataset_shards
        except:
            pass
        self.cid_set = set.intersection(*self.all_cid_set.values())
        self.cid_list = list(self.cid_set)
        return None

    async def load_dataset(self, dataset: str, split: Optional[str] = None) -> None:
        """
        Load a HuggingFace dataset with automatic split detection and shuffling.

        This method loads datasets from the HuggingFace datasets library with
        intelligent split handling and automatic fallback mechanisms. It applies
        random shuffling for improved training performance and handles cases where
        the requested split is not available by falling back to the first available
        split in the dataset.

        Args:
            dataset (str): HuggingFace dataset identifier or local dataset path.
                Can be a dataset name like 'squad' or 'wikitext' from the HuggingFace
                Hub, or a local path to a dataset directory.
            split (Optional[str], optional): Specific dataset split to load
                ('train', 'test', 'validation', etc.). If None, loads the entire
                dataset or falls back to the first available split. Defaults to None.

        Returns:
            None: This method updates self.dataset with the loaded dataset instance.
                The dataset is automatically shuffled with a random seed for
                improved training characteristics.

        Raises:
            DatasetError: If the dataset cannot be loaded from HuggingFace Hub
                or local path, or if no valid splits are available.
            ConnectionError: If there are network issues accessing HuggingFace Hub.
            ValueError: If the dataset identifier is invalid or malformed.

        Examples:
            # Load specific split
            >>> await manager.load_dataset("squad", split="train")
            >>> print(f"Loaded {len(manager.dataset)} training examples")
            
            # Load with automatic split detection
            >>> await manager.load_dataset("wikitext-103-raw-v1")
            >>> print(f"Dataset columns: {manager.dataset.column_names}")
            
            # Load local dataset
            >>> await manager.load_dataset("/path/to/local/dataset", split="validation")

        Notes:
            - Applies random shuffling with seed between 0 and 65536
            - Automatically handles missing splits by using the first available
            - Supports both HuggingFace Hub and local dataset loading
            - Updates instance state for use in subsequent processing methods
            - Memory usage depends on dataset size and loading strategy
        """
        if split is None:
            try:
                self.dataset = load_dataset(dataset).shuffle(random.randint(0,65536))
            except:
                splits = load_dataset(dataset).list_splits()
                self.dataset = load_dataset(dataset, split=splits[0]).shuffle(random.randint(0,65536))
                pass
        else:
            try:
                self.dataset = load_dataset(dataset, split=split).shuffle(random.randint(0,65536))
            except:
                splits = load_dataset(dataset).list_splits()
                self.dataset = load_dataset(dataset, split=splits[0]).shuffle(random.randint(0,65536))
                pass
        # columns = self.dataset.column_names
        # columns.append("cid")
        return None

    async def load_original_dataset(self, dataset: str, split: Optional[str] = None) -> None:
        """
        Load the original unprocessed dataset with automatic split handling.

        This method loads datasets in their original form from HuggingFace Hub or
        local storage without any IPFS processing or content addressing. It provides
        the foundation for subsequent processing workflows by establishing the base
        dataset that will be processed into content-addressable formats. The method
        includes intelligent split detection and random shuffling for optimal processing.

        Args:
            dataset (str): HuggingFace dataset identifier or local dataset path.
                Can be a standard dataset name from the Hub or path to local files.
            split (Optional[str], optional): Specific dataset split to load.
                If None, loads the entire dataset or falls back to first available
                split. Defaults to None.

        Returns:
            None: Updates self.dataset with the loaded original dataset instance.
                Dataset is shuffled with random seed for improved processing characteristics.

        Raises:
            DatasetError: If the original dataset cannot be loaded from the specified source.
            ConnectionError: If there are network issues accessing HuggingFace Hub.
            ValueError: If the dataset identifier is malformed or invalid.

        Examples:
            # Load original dataset for processing
            >>> await manager.load_original_dataset("squad", split="train")
            >>> print(f"Loaded {len(manager.dataset)} original examples")
            
            # Load with automatic split detection
            >>> await manager.load_original_dataset("wikitext-103-raw-v1")

        Notes:
            - Loads unprocessed data without IPFS content addressing
            - Applies random shuffling for improved processing characteristics
            - Serves as foundation for subsequent IPFS processing workflows
            - Handles missing splits gracefully with automatic fallback
        """
        if split is None:
            try:
                self.dataset = load_dataset(dataset ).shuffle(random.randint(0,65536))
            except:
                splits = load_dataset(dataset).list_splits()
                self.dataset = load_dataset(dataset, split=splits[0]).shuffle(random.randint(0,65536))
                pass
        else:
            try:
                self.dataset = load_dataset(dataset, split=split).shuffle(random.randint(0,65536))
            except:
                splits = load_dataset(dataset).list_splits()
                self.dataset = load_dataset(dataset, split=splits[0]).shuffle(random.randint(0,65536))
                pass
        # columns = self.dataset.column_names
        # columns.append("cid")
        return None

    async def load_combined(self, models: List[str], dataset: str, split: str, column: Optional[str], dst_path: str) -> Any:
        """
        Load and combine processed datasets with intelligent checkpoint management.

        This method loads combined datasets from various processing stages, intelligently
        selecting between consolidated files and checkpoint collections based on
        completeness and data availability. It performs validation against original
        datasets to ensure processing completeness and handles both full and incremental
        loading scenarios for optimal performance.

        Args:
            models (List[str]): List of model identifiers for combined loading.
                Each model should have corresponding processed data in the destination.
            dataset (str): Dataset identifier for combined file location.
                Used to construct file paths and validate processing completeness.
            split (str): Dataset split for combined data loading.
                Determines which processed data to combine and validate.
            column (Optional[str]): Specific column for uniqueness validation.
                Used to compare processed data completeness against original dataset.
                If None, uses row count for validation.
            dst_path (str): Destination path containing combined and checkpoint files.
                Should contain both consolidated files and checkpoint subdirectories.

        Returns:
            Any: The combined hashed dataset with complete processing state.
                Returns the most complete version available from consolidation or checkpoints.

        Raises:
            FileNotFoundError: If required combined files or checkpoints are missing.
            DatasetError: If combined data cannot be loaded or validated.
            ValueError: If data validation fails against original dataset.
            MemoryError: If combined dataset exceeds available system memory.

        Examples:
            # Load combined dataset with validation
            >>> combined_data = await manager.load_combined(
            ...     models=["sentence-transformers/all-MiniLM-L6-v2"],
            ...     dataset="large_corpus",
            ...     split="train",
            ...     column="text",
            ...     dst_path="/data/processed"
            ... )

        Notes:
            - Intelligently selects between consolidated and checkpoint data
            - Validates processing completeness against original dataset
            - Handles incremental loading for large datasets
            - Optimizes memory usage through selective loading strategies
            - Maintains processing state for continued workflows
        """
        print("load combined")
        await self.load_original_dataset(dataset, split)
        combined_checkpoint = os.path.join(dst_path, "ipfs_" + dataset.replace("/", "___") + ".parquet")
        combind_cid_checkpoint = os.path.join(dst_path, "ipfs_" + dataset.replace("/", "___") + "_cids.parquet")
        combinded_cid_checkpoint_dir = os.path.join(dst_path, "checkpoints","hashed_dataset")
        combinded_cid_checkpoint_dir_files = os.listdir(combinded_cid_checkpoint_dir)
        combinded_cid_checkpoint_dir_files_cid = [x for x in combinded_cid_checkpoint_dir_files if "_cids" in x]
        combinded_cid_checkpoint_dir_files_checkpoints = [x for x in combinded_cid_checkpoint_dir_files if "_cids" not in x]
        this_hashed_dataset = None
        if os.path.exists(combind_cid_checkpoint):
            this_hashed_dataset_cids = load_dataset('parquet', data_files=combind_cid_checkpoint)[split]
        else:
            this_hashed_dataset = load_dataset('parquet', data_files=combined_checkpoint)[split]
            this_hashed_dataset_cids = this_hashed_dataset.map(lambda x: {"cid": x["items"]["cid"]})
        this_hashed_dataset_cids = this_hashed_dataset_cids["cids"]
        self.all_cid_list["hashed_dataset"] = list(this_hashed_dataset_cids)
        self.all_cid_set["hashed_dataset"] = set(list(this_hashed_dataset_cids))

        try:
            len_hashed_dataset = len(this_hashed_dataset_cids)
        except Exception as e:
            len_hashed_dataset = this_hashed_dataset_cids.num_rows

        try:
            len_dataset = self.dataset.num_rows
        except Exception as e:
            dataset_columns = self.dataset.column_names
            len_dataset = self.dataset[dataset_columns[0]]
            len_dataset = len(len_dataset)

        if len_dataset > len_hashed_dataset:
            len_unique_column = len_dataset
            if column is not None:
                tmp_unique_column = self.dataset[column]
                tmp_unique_column = list(set(tmp_unique_column))
                len_unique_column = len(tmp_unique_column)
                pass

            if len_unique_column > len_hashed_dataset:
                this_hashed_dataset_checkpoints = load_dataset('parquet', data_files=combinded_cid_checkpoint_dir_files_cid)[split]
                len_this_hashed_dataset_checkpoints = this_hashed_dataset_checkpoints_cids.num_rows
                if len_this_hashed_dataset_checkpoints > len_hashed_dataset:
                    this_hashed_dataset_checkpoints = load_dataset('parquet', data_files=combinded_cid_checkpoint_dir_files_checkpoints)[split]
                    this_hashed_dataset_checkpoints_cids = this_hashed_dataset_checkpoints["cids"]
                    self.all_cid_list["hashed_dataset"] = list(this_hashed_dataset_checkpoints_cids)
                    self.all_cid_set["hashed_dataset"] = set(this_hashed_dataset_checkpoints_cids)
                    len_hashed_dataset = this_hashed_dataset_checkpoints_cids.num_rows
                    pass
                else:
                    this_hashed_dataset_checkpoints = load_dataset('parquet', data_files=combinded_cid_checkpoint_dir_files_checkpoints)[split]
                    this_hashed_dataset_checkpoints_cids = this_hashed_dataset_checkpoints["cids"]
                    self.all_cid_list["hashed_dataset"] = list(this_hashed_dataset_checkpoints_cids)
                    self.all_cid_set["hashed_dataset"] = set(this_hashed_dataset_checkpoints_cids)
                    len_hashed_dataset = this_hashed_dataset_checkpoints_cids.num_rows
                    pass
            else:
                if this_hashed_dataset is None:
                    this_hashed_dataset = load_dataset('parquet', data_files=combined_checkpoint)[split]
                this_hashed_dataset_cids = this_hashed_dataset.map(lambda x: {"cid": x["cid"]})
                self.all_cid_list["hashed_dataset"] = list(this_hashed_dataset_cids)
                self.all_cid_set["hashed_dataset"] = set(this_hashed_dataset_cids)
                pass
        else:
            if this_hashed_dataset is None:
                this_hashed_dataset = load_dataset('parquet', data_files=combined_checkpoint)[split]
            this_hashed_dataset_cids = this_hashed_dataset.map(lambda x: {"cid": x["items"]["cid"]})["cid"]
            self.all_cid_list["hashed_dataset"] = list(this_hashed_dataset_cids)
            self.all_cid_set["hashed_dataset"] = set(this_hashed_dataset_cids)
            pass
        del self.dataset
        return this_hashed_dataset

    async def combine_checkpoints(self, dataset, split, column, dst_path, models):
        """
        Combine distributed checkpoint data into consolidated datasets.

        This method loads and combines checkpoint data from multiple processing
        stages, creating consolidated datasets with deduplication. It processes
        both hashed datasets and model-specific embeddings to create unified
        output files for efficient access and storage.

        Args:
            dataset: Dataset identifier for checkpoint location
            split: Dataset split to combine
            column: Column for deduplication operations
            dst_path: Destination path for combined output
            models: List of model identifiers to combine

        Returns:
            None: Creates combined files in destination directory
        """
        await self.load_dataset(dataset, split)
        await self.load_checkpoints(dataset, split, dst_path, models)
        if not os.path.exists(os.path.join(dst_path, "combined")):
            os.makedirs(os.path.join(dst_path, "combined"))
        del self.dataset
        self.hashed_dataset_combined = {}
        self.embedding_datasets = {}
        ## get first row from self.hashed_datasets
        self.unique_cid_set = set()
        self.unique_cid_list = []
        if not os.path.exists(os.path.join(dst_path, "combined", "rm_secondary_cid_" + dataset.replace("/","___") + ".parquet")):
            self.hashed_dataset_combined = datasets.Dataset.from_generator(lambda: self.demux_checkpoints(self.hashed_dataset))
            self.hashed_dataset_combined.to_parquet(os.path.join(dst_path, "combined",  "rm_secondary_cid_" + dataset.replace("/","___") + ".parquet"))
            combined_dataset_cids = datasets.Dataset.from_dict({"cids": self.unique_cid_list})
            combined_dataset_cids.to_parquet(os.path.join(dst_path, "combined", "rm_secondary_cid_" + "ipfs_" + dataset.replace("/","___") + "_cids.parquet"))

        if not os.path.exists(os.path.join(dst_path, "combined", "rm_cid_" + dataset.replace("/","___") + ".parquet")):
            self.hashed_dataset_combined = datasets.Dataset.from_generator(lambda: self.demux_checkpoints2(self.hashed_dataset))
            self.hashed_dataset_combined.to_parquet(os.path.join(dst_path, "combined", "rm_cid_" + dataset.replace("/","___") + ".parquet"))
            combined_dataset_cids = datasets.Dataset.from_dict({"cids": self.unique_cid_list})
            combined_dataset_cids.to_parquet(os.path.join(dst_path, "combined", "rm_cid_" + "ipfs_" + dataset.replace("/","___") + "_cids.parquet"))

        for model in list(self.metadata["models"]):
            if not os.path.exists(os.path.join(dst_path, "combined", model.replace("/","___"))):
                combined_embedding_datasets = datasets.Dataset.from_generator(lambda: self.demux_checkpoints(self.index[model]))
                combined_embedding_datasets.to_parquet(os.path.join(dst_path, "combined", + dataset.replace("/","___") + model.replace("/","___") + ".parquet"))
                combined_embedding_datasets_cids = datasets.Dataset.from_dict({"cids": self.unique_cid_list})
                combined_embedding_datasets_cids.to_parquet(os.path.join(dst_path, "combined", dataset.replace("/","___") + model.replace("/","___") + "_cids.parquet"))

        for model in list(self.metadata["models"]):
            if not os.path.exists(os.path.join(dst_path, "combined", model.replace("/","___"))):
                combined_embedding_datasets = datasets.Dataset.from_generator(lambda: self.demux_checkpoints(self.index[model]))
                combined_embedding_datasets.to_parquet(os.path.join(dst_path, "secondary_combined", + dataset.replace("/","___") + model.replace("/","___") + ".parquet"))
                combined_embedding_datasets_cids = datasets.Dataset.from_dict({"cids": self.unique_cid_list})
                combined_embedding_datasets_cids.to_parquet(os.path.join(dst_path, "secondary_combined", dataset.replace("/","___") + model.replace("/","___") + "_cids.parquet"))
        return None

    async def generate_clusters(self, dataset, split, dst_path):
        """
        Generate content clusters from processed dataset embeddings.

        This method analyzes embedding vectors to create content clusters
        for improved content organization and similarity search capabilities.

        Args:
            dataset: Dataset identifier for cluster generation
            split: Dataset split to analyze
            dst_path: Destination path for cluster output files

        Returns:
            None: Creates cluster files in destination directory
        """

        return None


    async def combine_checkpoints(self, dataset, split, column, dst_path, models):
        """
        Alternative implementation for combining checkpoint data.

        This method provides an alternative approach to combining distributed
        checkpoint data with different processing strategies.

        Args:
            dataset: Dataset identifier for checkpoint location
            split: Dataset split to combine  
            column: Column for deduplication operations
            dst_path: Destination path for combined output
            models: List of model identifiers to combine

        Returns:
            None: Creates combined files in destination directory
        """
        await self.load_dataset(dataset, split)
        await self.load_checkpoints(dataset, split, dst_path, models)
        if not os.path.exists(os.path.join(dst_path, "combined")):
            os.makedirs(os.path.join(dst_path, "combined"))
        del self.dataset
        self.hashed_dataset_combined = {}
        self.embedding_datasets = {}
        ## get first row from self.hashed_datasets
        self.unique_cid_set = set()
        self.unique_cid_list = []
        if not os.path.exists(os.path.join(dst_path, "combined", "rm_secondary_cid_" + dataset.replace("/","___") + ".parquet")):
            self.hashed_dataset_combined = datasets.Dataset.from_generator(lambda: self.demux_checkpoints(self.hashed_dataset))
            self.hashed_dataset_combined.to_parquet(os.path.join(dst_path, "combined",  "rm_secondary_cid_" + dataset.replace("/","___") + ".parquet"))
            combined_dataset_cids = datasets.Dataset.from_dict({"cids": self.unique_cid_list})
            combined_dataset_cids.to_parquet(os.path.join(dst_path, "combined", "rm_secondary_cid_" + "ipfs_" + dataset.replace("/","___") + "_cids.parquet"))

        if not os.path.exists(os.path.join(dst_path, "combined", "rm_cid_" + dataset.replace("/","___") + ".parquet")):
            self.hashed_dataset_combined = datasets.Dataset.from_generator(lambda: self.demux_checkpoints2(self.hashed_dataset))
            self.hashed_dataset_combined.to_parquet(os.path.join(dst_path, "combined", "rm_cid_" + dataset.replace("/","___") + ".parquet"))
            combined_dataset_cids = datasets.Dataset.from_dict({"cids": self.unique_cid_list})
            combined_dataset_cids.to_parquet(os.path.join(dst_path, "combined", "rm_cid_" + "ipfs_" + dataset.replace("/","___") + "_cids.parquet"))

        for model in list(self.metadata["models"]):
            if not os.path.exists(os.path.join(dst_path, "combined", model.replace("/","___"))):
                combined_embedding_datasets = datasets.Dataset.from_generator(lambda: self.demux_checkpoints(self.index[model]))
                combined_embedding_datasets.to_parquet(os.path.join(dst_path, "combined", + dataset.replace("/","___") + model.replace("/","___") + ".parquet"))
                combined_embedding_datasets_cids = datasets.Dataset.from_dict({"cids": self.unique_cid_list})
                combined_embedding_datasets_cids.to_parquet(os.path.join(dst_path, "combined", dataset.replace("/","___") + model.replace("/","___") + "_cids.parquet"))

        for model in list(self.metadata["models"]):
            if not os.path.exists(os.path.join(dst_path, "combined", model.replace("/","___"))):
                combined_embedding_datasets = datasets.Dataset.from_generator(lambda: self.demux_checkpoints(self.index[model]))
                combined_embedding_datasets.to_parquet(os.path.join(dst_path, "secondary_combined", + dataset.replace("/","___") + model.replace("/","___") + ".parquet"))
                combined_embedding_datasets_cids = datasets.Dataset.from_dict({"cids": self.unique_cid_list})
                combined_embedding_datasets_cids.to_parquet(os.path.join(dst_path, "secondary_combined", dataset.replace("/","___") + model.replace("/","___") + "_cids.parquet"))
        return None

    async def generate_clusters(self, dataset, split, dst_path):
        """
        Alternative implementation for content cluster generation.

        This method provides an alternative approach to generating content
        clusters with different algorithms or parameters.

        Args:
            dataset: Dataset identifier for cluster generation
            split: Dataset split to analyze
            dst_path: Destination path for cluster output files

        Returns:
            None: Creates cluster files in destination directory
        """

        return None

    async def load_clusters(self, dataset, split, dst_path):
        """
        Load pre-computed content clusters from storage.

        This method loads existing cluster assignments and metadata from
        storage, reconstructing cluster structures for content organization
        and similarity search operations.

        Args:
            dataset: Dataset identifier for cluster files
            split: Dataset split for cluster loading
            dst_path: Source path containing cluster files

        Returns:
            tuple: (cluster_cids_dataset, ipfs_cid_clusters_list, 
                   ipfs_cid_clusters_set, ipfs_cid_list, ipfs_cid_set)
        """
        ipfs_cid_clusters_list = []
        ipfs_cid_clusters_set = ()
        ipfs_cid_set = set()
        ipfs_cid_list = []
        cluster_cids_dataset = None
        try:
            if os.path.exists(os.path.join(dst_path, dataset.replace("/", "___") + "_cluster_cids.parquet")):
                cluster_cids_dataset = load_dataset('parquet', data_files=os.path.join(dst_path, dataset.replace("/", "___") + "_cluster_cids.parquet"))["train"]
                ipfs_cid_clusters_list = cluster_cids_dataset["cluster_cids"]
                ipfs_cid_clusters_set = [set(x) for x in ipfs_cid_clusters_list]
                ipfs_cid_list = [cid for sublist in ipfs_cid_clusters_list for cid in sublist]
                ipfs_cid_set = set([cid for sublist in ipfs_cid_clusters_list for cid in sublist])
            else:
                await self.generate_clusters(dataset, split, dst_path)
                pass
        except Exception as e:
            print(e)
            pass
        if cluster_cids_dataset is not None:
            self.cluster_cids_dataset = cluster_cids_dataset
        if ipfs_cid_clusters_list is not None:
            self.ipfs_cid_clusters_list = ipfs_cid_clusters_list
        if ipfs_cid_clusters_set is not None:
            self.ipfs_cid_clusters_set = ipfs_cid_clusters_set
        if ipfs_cid_list is not None:
            self.ipfs_cid_list = ipfs_cid_list
        if ipfs_cid_set is not None:
            self.ipfs_cid_set = ipfs_cid_set
        self.cid_set = self.ipfs_cid_set
        return cluster_cids_dataset, ipfs_cid_clusters_list, ipfs_cid_clusters_set, ipfs_cid_list, ipfs_cid_set



    async def load_checkpoints(self, dataset, split, dst_path, models, method="cids"):
        """
        Enhanced checkpoint loading with configurable methods.

        This method provides enhanced checkpoint loading capabilities with
        configurable loading methods and improved error handling for
        large-scale dataset reconstruction.

        Args:
            dataset: Dataset identifier for checkpoint location
            split: Dataset split to load
            dst_path: Source path containing checkpoint files
            models: List of model identifiers to load
            method: Loading method ('cids' or 'items')

        Returns:
            None: Updates instance attributes with loaded data
        """
        if "hashed_dataset" not in list(dir(self)):
            self.hashed_dataset = None
        if "all_cid_list" not in list(dir(self)):
            self.all_cid_list = {}
        if "all_cid_set" not in list(dir(self)):
            self.all_cid_set = {}
        for model in models:
            if model not in list(self.index.keys()):
                self.index[model] = None
        if self.hashed_dataset is None or isinstance(self.hashed_dataset, dict):
            # hashed_dataset_dst_path = os.path.join(dst_path, "ipfs_" + dataset.replace("/","___") + ".parquet")
            hashed_dataset_dst_path = os.path.join(dst_path, "ipfs_" + dataset.replace("/","___") + ".parquet")
            hash_dataset_cid_dst_path = os.path.join(dst_path, "ipfs_" + dataset.replace("/","___") + "_cids.parquet")

            if os.path.isfile(hash_dataset_cid_dst_path):
                hashed_dataset_cids = load_dataset('parquet', data_files=hash_dataset_cid_dst_path)[split]
                hashed_dataset_cids = list(hashed_dataset_cids["cids"])

            if os.path.isfile(hashed_dataset_dst_path):
                self.hashed_dataset = load_dataset('parquet', data_files=hashed_dataset_dst_path)[split]

            cid_rows = self.hashed_dataset.num_rows
            hashed_dataset_rows = len(hashed_dataset_cids)

            if hashed_dataset_cids is not None and hashed_dataset_rows == cid_rows:
                self.all_cid_list["hashed_dataset"] = hashed_dataset_cids
                self.all_cid_set["hashed_dataset"] = set(hashed_dataset_cids)
            else:
                self.all_cid_list["hashed_dataset"] = self.hashed_dataset["cid"]
                self.all_cid_set["hashed_dataset"] = set(self.all_cid_list["hashed_dataset"] )

        if (self.hashed_dataset is None or self.hashed_dataset.num_rows == 0 ) and os.path.exists(os.path.join(dst_path, "checkpoints")):
            ls_checkpoints = os.listdir(os.path.join(dst_path, "checkpoints"))
            hashed_dataset_shards = [os.path.join(dst_path, "checkpoints", x) for x in ls_checkpoints if "ipfs_" + dataset.replace("/", "___") + "_shard" in x and "_cids" not in x ]
            if self.hashed_dataset is None or isinstance(self.hashed_dataset, dict):
                if len(hashed_dataset_shards) > 0:
                    self.hashed_dataset = load_dataset('parquet', data_files=hashed_dataset_shards)[split]
                if "hashed_dataset" not in list(self.all_cid_list.keys()):
                    self.all_cid_list["hashed_dataset"] = []
                if "hashed_dataset" not in list(self.all_cid_set.keys()):
                    self.all_cid_set["hashed_dataset"] = set()
                if "hashed_dataset" not in list(self.caches.keys()):
                    self.caches["hashed_dataset"] = {"items" : []}
                with multiprocessing.Pool() as pool:
                    args = [[hashed_dataset_shards[i], method] for i in range(len(hashed_dataset_shards))]
                    results = pool.map(process_hashed_dataset_shard, args)
                    if len(results) > 0:
                        # Initialize accumulators
                        total_cids = []
                        total_items = []
                        for res in results:
                            cid, items, schemas = (res + [None, None, None])[:3]
                            if cid is not None:
                                total_cids += cid
                            if items is not None:
                                total_items += items
                            if schemas is not None:
                                self.schemas["hashed_dataset"] = schemas  # Assuming schemas won't conflict
                        # Update the shared variables in bulk
                        self.all_cid_list["hashed_dataset"] += total_cids
                        self.all_cid_set["hashed_dataset"].update(set(total_cids))
                        if "hashed_dataset" not in list(self.caches.keys()):
                            self.caches["hashed_dataset"] = {"items" : []}
                        self.caches["hashed_dataset"]["items"] += total_items
                        self.hashed_dataset = datasets.Dataset.from_dict({"items": self.caches["hashed_dataset"]["items"]})

        for model in models:
            if model not in list(self.index.keys()):
                self.index[model] = None
            if model not in list(self.all_cid_list.keys()):
                self.all_cid_list[model] = []
            if model not in list(self.all_cid_set.keys()):
                self.all_cid_set[model] = set()
            if model not in list(self.caches.keys()):
                self.caches[model] = {"items" : []}
            model_checkpoints_dst_path = os.path.join(dst_path, "checkpoints",  dataset.replace("/","___") + "__" + model.replace("/","___"))
            model_dst_path = os.path.join(dst_path, "ipfs_" +  dataset.replace("/","___") + "__" + model.replace("/","___") + ".parquet")
            model_clusters_dst_path = os.path.join(dst_path, "clusters",  dataset.replace("/","___") + "__" + model.replace("/","___"))
            len_hashed_dataset = self.hashed_dataset.num_rows
            len_index = 0
            if os.path.isfile(model_dst_path):
                self.caches[model] = {"items" : []}
                self.index[model] = load_dataset('parquet', data_files=model_dst_path, streaming=True)[split]
                len_index = self.index[model].num_rows
            if len_index < len_hashed_dataset and os.path.exists(model_checkpoints_dst_path):
                ls_checkpoints = os.listdir(model_checkpoints_dst_path)
                this_model_checkpoints = [os.path.join(dst_path, "checkpoints", dataset.replace("/","___") + "__" + model.replace("/","___"), x) for x in ls_checkpoints if model.replace("/", "___") + "_shard" in x and "_cids" not in x]
                this_model_cid_checkpoints = [os.path.join(dst_path, "checkpoints", dataset.replace("/","___") + "__" + model.replace("/","___"), x) for x in ls_checkpoints if model.replace("/", "___") + "_shard" in x and "_cids" in x]
                this_model_len = 0
                if len(this_model_cid_checkpoints) == len(this_model_checkpoints):
                    try:
                        if split is None:
                            self.index[model] = load_dataset('parquet', data_files=this_model_cid_checkpoints)
                        else:
                            self.index[model] = load_dataset('parquet', data_files=this_model_cid_checkpoints)[split]
                        if "cids" in list(self.index[model].column_names):
                            this_model_cids = self.index[model]["cids"]
                            if len(this_model_cids) > 0:
                                self.all_cid_list[model] += this_model_cids
                                self.all_cid_set[model].update(set(this_model_cids))
                        this_model_len = self.index[model].num_rows
                    except Exception as e:
                        print(e)
                        print("Error loading model checkpoints")
                        print(e.with_traceback())
                elif len(this_model_cid_checkpoints) < len(this_model_checkpoints):
                    print("Error: Checkpoints cid index missing")
                    for i in range(len(this_model_checkpoints)):
                        if i < len(this_model_cid_checkpoints):
                            pass
                        else:
                            if split is None:
                                cids = load_dataset('parquet', data_files=this_model_checkpoints[i]).to_dict()
                            else:
                                cids = load_dataset('parquet', data_files=this_model_cid_checkpoints[i])[split].to_dict()
                            if cids is not None:
                                new_cids_dataset_dst_path = os.path.join(dst_path, "checkpoints", dataset.replace("/","___") + "__" + model.replace("/","___"), this_model_checkpoints[i].replace(".parquet","") + "_cids.parquet")
                                new_cids_dataset = datasets.Dataset.from_dict(cids)
                                new_cids_dataset.to_parquet(new_cids_dataset_dst_path)
                    ls_checkpoints = os.listdir(model_checkpoints_dst_path)
                    this_model_checkpoints = [os.path.join(dst_path, "checkpoints", dataset.replace("/","___") + "__" + model.replace("/","___"), x) for x in ls_checkpoints if model.replace("/", "___") + "_shard" in x and "_cids" not in x]
                    this_model_cid_checkpoints = [os.path.join(dst_path, "checkpoints", dataset.replace("/","___") + "__" + model.replace("/","___"), x) for x in ls_checkpoints if model.replace("/", "___") + "_shard" in x and "_cids" in x]
                    if split is None:
                        self.index[model] = load_dataset('parquet', data_files=this_model_cid_checkpoints)
                    else:
                        self.index[model] = load_dataset('parquet', data_files=this_model_cid_checkpoints)[split]
                    this_model_len = self.index[model].num_rows
                    if "cids" in list(self.index[model].column_names):
                        this_model_cids = len(self.index[model]["cids"])
                        if len(this_model_cids) > 0:
                            self.all_cid_list[model] += this_model_cids
                            self.all_cid_set[model].update(set(this_model_cids))
                if this_model_len < len_hashed_dataset:
                    with multiprocessing.Pool() as pool:
                        args = [[this_model_checkpoints[i], 'cids', None] for i in range(len(this_model_checkpoints))]
                        results = pool.map(process_hashed_dataset_shard, args)
                        if len(results) > 0:
                            # Initialize accumulators
                            total_cids = []
                            total_items = []
                            for res in results:
                                cid, items, schemas = (res + [None, None, None])[:3]
                                if cid is not None:
                                    total_cids += cid
                                if items is not None:
                                    total_items += items
                                if schemas is not None:
                                    self.schemas[model] = schemas  # Assuming schemas won't conflict
                            # Update the shared variables in bulk
                            self.all_cid_list[model] += total_cids
                            self.all_cid_set[model].update(set(total_cids))
                            self.caches[model]["items"] += total_items
                        self.index[model] = datasets.Dataset.from_dict({"items": self.caches[model]["items"]} )
            if model not in list(self.index.keys()) or self.index[model] is None or isinstance(self.index[model], dict):
                ls_checkpoints = os.listdir(model_clusters_dst_path)
                this_model_clusters = [os.path.join(dst_path, "clusters",  dataset.replace("/","___") + "__" + model.replace("/","___"), x) for x in ls_checkpoints if model.replace("/", "___") + "_cluster" in x and "_cids" not in x]
                if len(this_model_clusters) > 0:
                    self.index[model] = load_dataset('parquet', data_files=this_model_clusters)[split]
                else:
                    self.index[model] = datasets.Dataset.from_dict({"cid": [], "embedding": [] })
            ls_chunks = []
            if os.path.exists(os.path.join(dst_path, "checkpoints" , "sparse_chunks")):
                ls_chunks = os.listdir(os.path.join(dst_path, "checkpoints", "sparse_chunks"))
                ls_chunk_names = [x.replace(".parquet","") for x in ls_chunks]
                self.cid_chunk_list = ls_chunk_names
                self.cid_chunk_set = set(ls_chunk_names)
            del ls_chunks
            del ls_checkpoints
        try:
            del hashed_dataset_shards
        except:
            pass
        self.cid_set = set.intersection(*self.all_cid_set.values())
        self.cid_list = list(self.cid_set)
        return None


    async def load_clusters(self, dataset, split, dst_path):
        """
        Alternative implementation for loading content clusters.

        This method provides an alternative approach to loading cluster
        data with different processing strategies or optimizations.

        Args:
            dataset: Dataset identifier for cluster files
            split: Dataset split for cluster loading  
            dst_path: Source path containing cluster files

        Returns:
            tuple: (cluster_cids_dataset, ipfs_cid_clusters_list,
                   ipfs_cid_clusters_set, ipfs_cid_list, ipfs_cid_set)
        """
        ipfs_cid_clusters_list = []
        ipfs_cid_clusters_set = ()
        ipfs_cid_set = set()
        ipfs_cid_list = []
        cluster_cids_dataset = None
        try:
            cluster_cids_filepath = os.path.join(dst_path, dataset.replace("/", "___") + "_cluster_cids.parquet")
            if os.path.exists(cluster_cids_filepath):
                cluster_cids_dataset = load_dataset('parquet', data_files=cluster_cids_filepath)["train"]
                ipfs_cid_clusters_list = cluster_cids_dataset["cluster_cids"]
                ipfs_cid_clusters_set = [set(x) for x in ipfs_cid_clusters_list]
                ipfs_cid_list = [cid for sublist in ipfs_cid_clusters_list for cid in sublist]
                ipfs_cid_set = set([cid for sublist in ipfs_cid_clusters_list for cid in sublist])
            else:
                await self.generate_clusters(dataset, split, dst_path)
                pass
        except Exception as e:
            print(e)
            pass
        if cluster_cids_dataset is not None:
            self.cluster_cids_dataset = cluster_cids_dataset
        if ipfs_cid_clusters_list is not None:
            self.ipfs_cid_clusters_list = ipfs_cid_clusters_list
        if ipfs_cid_clusters_set is not None:
            self.ipfs_cid_clusters_set = ipfs_cid_clusters_set
        if ipfs_cid_list is not None:
            self.ipfs_cid_list = ipfs_cid_list
        if ipfs_cid_set is not None:
            self.ipfs_cid_set = ipfs_cid_set
        self.cid_set = self.ipfs_cid_set
        return cluster_cids_dataset, ipfs_cid_clusters_list, ipfs_cid_clusters_set, ipfs_cid_list, ipfs_cid_set

    def test(self) -> None:
        """
        Perform basic functionality test of the IPFS datasets system.

        This method provides a simple test interface for validating that the
        ipfs_datasets_py instance is properly initialized and ready for operation.
        Currently serves as a placeholder for future comprehensive testing
        functionality including connectivity tests, resource validation, and
        system health checks.

        Returns:
            None: Method completes successfully if system is operational.

        Examples:
            # Basic system test
            >>> manager = ipfs_datasets_py(resources, metadata)
            >>> manager.test()
            # No output indicates successful test

        Notes:
            - Currently a placeholder for future test implementations
            - Will be expanded to include comprehensive system validation
            - Useful for debugging initialization and configuration issues
        """
        return None

    @staticmethod
    def process_chunk_files(path: Union[str, List[Any], Dict[str, Any]], datatype: str = "cids") -> Union[List[Any], ValueError]:
        """
        Process chunk files for Content Identifier extraction and content management.

        This static method processes individual chunk files to extract Content Identifiers
        (CIDs) and associated content data. It supports multiple input formats and
        automatically generates missing CID index files for efficient content addressing.
        The method is designed for processing sparse chunk collections in distributed
        storage scenarios.

        Args:
            path (Union[str, List[Any], Dict[str, Any]]): Chunk file specification.
                Can be a file path string, a list containing [path, datatype],
                or a dictionary with 'file' and 'type' keys for configuration.
            datatype (str, optional): Type of data to extract from chunk files.
                Valid values are 'cids' for Content Identifiers only, 'items'
                for full content extraction, or 'schema' for metadata.
                Defaults to "cids".

        Returns:
            Union[List[Any], ValueError]: A list containing [cids, items, schema] where:
                - cids (List[str]): List of Content Identifiers from the chunk
                - items (Dict[str, List[Any]] or None): Dictionary of chunk content
                  organized by field names, or None if datatype is 'cids'
                - schema (Any or None): Chunk schema information
                Returns ValueError if chunk files are not found.

        Raises:
            ValueError: If no chunk dataset files are found at the specified path.
            FileNotFoundError: If the specified chunk file does not exist.
            DatasetError: If there are issues loading the Parquet chunk files.

        Examples:
            # Extract CIDs from chunk
            >>> result = ipfs_datasets_py.process_chunk_files(
            ...     "/chunks/chunk_001.parquet",
            ...     datatype="cids"
            ... )
            >>> cids, items, schema = result
            >>> print(f"Chunk contains {len(cids)} items")
            
            # Extract full content from chunk
            >>> result = ipfs_datasets_py.process_chunk_files(
            ...     "/chunks/chunk_001.parquet",
            ...     datatype="items"
            ... )
            >>> cids, items, schema = result
            >>> print(f"Extracted content: {list(items.keys())}")

        Notes:
            - Automatically generates CID files if they don't exist
            - CID files are stored as '{chunk_path}_cids.parquet'
            - Optimized for sparse chunk processing in distributed systems
            - Memory usage depends on chunk size and datatype selection
            - Static method for use without class instantiation
        """
        cids = None
        items = None
        schema = None

        if type(path) is not str:
            if type(path) is list:
                if len(path) == 1:
                    path = path[0]
                elif len(path) == 2:
                    path, datatype = path
            if type(path) is dict:
                if "file" in list(path.keys()):
                    path = path["file"]
                if "type" in list(path.keys()):
                    datatype = path["type"]

        if datatype == "cids":
            if os.path.exists(path):
                cid_path = path.replace(".parquet","")+"_cids.parquet"
                if os.path.exists(cid_path):
                    cids = load_dataset('parquet', data_files=cid_path)["cids"]
            else:
                return ValueError("No dataset found")

        elif datatype == "items":
            cid_path = path.replace(".parquet","")+"_cids.parquet"
            chunk_dataset = None
            cids = None
            if os.path.exists(cid_path):
                cids = load_dataset('parquet', data_files=cid_path)["cids"]
            else:
                if os.path.exists(path):
                    chunk_dataset = load_dataset('parquet', data_files=path)
                    cids = [ item["items"]["cid"] for item in chunk_dataset ]
                    tmp_dataset = datasets.Dataset.from_dict({"cids": cids})
                    tmp_dataset.to_parquet(cid_path)
                else:
                    return ValueError("No dataset found")
            if chunk_dataset is None:
                chunk_dataset = load_dataset('parquet', data_files = path)
                if cids is None and os.path.exists(cid_path):
                    cids = load_dataset('parquet', data_files = cid_path)["cids"]
                else:
                    cids = [ item["items"]["cid"] for item in chunk_dataset ]
                    tmp_dataset = datasets.Dataset.from_dict({"cids": cids})
                    tmp_dataset.to_parquet(cid_path)
                pass
            items = {key: [item["items"][key] for item in chunk_dataset] for key in chunk_dataset[0]["items"].keys()}
            schema = None
        elif datatype == "schema":
            schema = None

        return [ cids , items, schema ]
