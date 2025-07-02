"""
Federated Search Module for IPFS Datasets.

This module provides comprehensive support for federated search across distributed dataset
fragments, enabling efficient and scalable searches across sharded datasets stored on
multiple IPFS nodes. It supports multiple search types including vector similarity,
keyword, and hybrid searches with customizable ranking and result aggregation strategies.

Key features:
- Distributed vector search with approximate nearest neighbors (ANN)
- Keyword and full-text search across sharded datasets
- Hybrid search combining vector and keyword matching
- Custom ranking and scoring functions
- Search result aggregation from multiple nodes
- Fault-tolerant search with configurable timeouts
- Parallel query execution for improved performance
- Privacy-preserving search capabilities (optional)
- Search result caching and optimization
"""

import os
import json
import time
import logging
import asyncio
import numpy as np
from typing import Dict, List, Any, Optional, Tuple, TypeVar
from dataclasses import dataclass, field, asdict
from enum import Enum
import random
from concurrent.futures import ThreadPoolExecutor
import hashlib

# Conditional imports for optional dependencies
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

try:
    from multiaddr import Multiaddr
    import py_libp2p # TODO Debug import of py_libp2p
    from py_libp2p.network.stream.net_stream_interface import INetStream # TODO INetStream is not defined in the original code. Also does this library even exist?
    LIBP2P_AVAILABLE = True
except ImportError:
    LIBP2P_AVAILABLE = False
    # Create stub classes for type checking
    class INetStream:
        pass

# Import our own modules
from ipfs_datasets_py.libp2p_kit import (
    NetworkProtocol, # TODO NetworkProtocol is not defined in the original code
    LibP2PNotAvailableError,
    ShardMetadata, # TODO ShardMetadata is not defined in the original code
)

T = TypeVar('T')

class SearchType(Enum):
    """Types of search supported by the federated search system."""
    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"
    FILTER = "filter"
    AGGREGATE = "aggregate"


@dataclass
class SearchQuery:
    """Represents a search query to be executed across the network."""
    dataset_id: str
    query_type: SearchType
    top_k: int = 10
    timeout_ms: int = 5000  # 5 seconds default timeout

    # Vector search parameters
    vector: Optional[List[float]] = None
    distance_metric: str = "cosine"  # or "l2", "dot"
    min_similarity: float = 0.0
    vector_field: str = "vector"  # Field containing vectors

    # Keyword search parameters
    query_text: Optional[str] = None
    fields: Optional[List[str]] = None
    operator: str = "and"  # or "or"

    # Hybrid search parameters
    vector_weight: float = 0.5
    text_weight: float = 0.5

    # Filter search parameters
    filters: Optional[List[Dict[str, Any]]] = None

    # Common parameters
    include_metadata: bool = True
    max_distance: Optional[float] = None  # Maximum distance/minimum similarity threshold

    # Advanced parameters
    shard_routing_hint: Optional[List[str]] = None  # Specific shards to search
    search_config: Optional[Dict[str, Any]] = None  # Additional search configuration
    trace_id: Optional[str] = None  # For search tracing/debugging


@dataclass
class SearchResult:
    """Represents a single search result."""
    id: str  # Unique identifier for the result
    dataset_id: str  # Dataset ID the result belongs to
    shard_id: str  # Shard ID the result was found in
    score: float  # Search score (higher is better)
    distance: Optional[float] = None  # Distance (lower is better, for vector search)
    node_id: Optional[str] = None  # Node ID that provided this result
    metadata: Optional[Dict[str, Any]] = None  # Result metadata
    vector: Optional[List[float]] = None  # Vector (if requested)
    source_rank: int = 0  # Rank of this result in its original result set
    matched_terms: Optional[List[str]] = None  # Terms that matched (for keyword search)
    matched_fields: Optional[List[str]] = None  # Fields that matched


@dataclass
class AggregatedSearchResults:
    """Represents search results aggregated from multiple nodes."""
    query: SearchQuery
    total_results: int = 0
    results: List[SearchResult] = field(default_factory=list)
    nodes_queried: List[str] = field(default_factory=list)
    nodes_responded: List[str] = field(default_factory=list)
    execution_time_ms: int = 0
    shards_searched: List[str] = field(default_factory=list)
    trace_info: Optional[Dict[str, Any]] = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    debug_info: Optional[Dict[str, Any]] = None


class RankingStrategy(Enum):
    """Strategies for ranking and aggregating results from multiple nodes."""
    SCORE = "score"  # Rank by score alone
    SOURCE_WEIGHTED = "source_weighted"  # Weight by source node reliability
    ROUND_ROBIN = "round_robin"  # Take results from each node in turn
    HYBRID = "hybrid"  # Combine multiple strategies


class FederatedSearch:
    """
    Main class for federated search across distributed dataset fragments.

    This class provides methods for searching sharded datasets across multiple
    IPFS nodes, with support for vector similarity, keyword, and hybrid searches.
    """

    def __init__(
        self,
        node: Any,  # LibP2PNode instance
        storage_dir: Optional[str] = None,
        max_concurrent_requests: int = 10,
        default_timeout_ms: int = 5000,
        use_cache: bool = True,
        cache_ttl_seconds: int = 300,  # 5 minutes
        max_cache_size: int = 100,
        ranking_strategy: RankingStrategy = RankingStrategy.SCORE
    ):
        """
        Initialize the federated search engine.

        Args:
            node: The LibP2P node for network communication
            storage_dir: Directory for storing search indices and caches
            max_concurrent_requests: Maximum concurrent search requests
            default_timeout_ms: Default timeout for search requests in milliseconds
            use_cache: Whether to use result caching
            cache_ttl_seconds: Time-to-live for cached results in seconds
            max_cache_size: Maximum number of cached queries
            ranking_strategy: Strategy for ranking and aggregating results
        """
        if not LIBP2P_AVAILABLE:
            raise LibP2PNotAvailableError(
                "LibP2P is required for federated search. "
                "Install with: pip install py-libp2p"
            )

        self.node = node
        self.storage_dir = storage_dir or os.path.join(os.getcwd(), ".federated_search")
        self.max_concurrent_requests = max_concurrent_requests
        self.default_timeout_ms = default_timeout_ms
        self.use_cache = use_cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_size = max_cache_size
        self.ranking_strategy = ranking_strategy

        # Create necessary directories
        os.makedirs(os.path.join(self.storage_dir, "cache"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "indices"), exist_ok=True)

        # Initialize caches
        self.result_cache: Dict[str, Tuple[AggregatedSearchResults, float]] = {}  # {query_hash: (results, timestamp)}

        # Register protocol handlers
        self._setup_protocol_handlers()

        # Statistics
        self.stats = {
            "total_queries": 0,
            "cache_hits": 0,
            "total_execution_time_ms": 0,
            "nodes_queried": set(),
            "errors": 0
        }

    def _setup_protocol_handlers(self):
        """Set up protocol handlers for federated search."""
        if hasattr(self.node, 'register_protocol_handler'):
            # Register the federated search handler
            self.node.register_protocol_handler(
                NetworkProtocol.FEDERATED_SEARCH,
                self._handle_federated_search
            )
        else:
            logging.warning("Node does not support protocol handlers, search handling will not be available")

    async def _handle_federated_search(self, stream: 'INetStream'):
        """
        Handle incoming federated search requests.

        Args:
            stream: The network stream
        """
        try:
            # Read request data
            request_data = await stream.read()
            request = json.loads(request_data.decode())

            # Process the search request
            if request.get("action") == "search":
                # Convert dict to SearchQuery
                query_dict = request.get("query", {})
                query_type = SearchType(query_dict.get("query_type", "vector"))
                query = SearchQuery(
                    dataset_id=query_dict.get("dataset_id", ""),
                    query_type=query_type,
                    top_k=query_dict.get("top_k", 10),
                    timeout_ms=query_dict.get("timeout_ms", self.default_timeout_ms)
                )

                # Set type-specific parameters
                if query_type == SearchType.VECTOR:
                    query.vector = query_dict.get("vector")
                    query.distance_metric = query_dict.get("distance_metric", "cosine")
                    query.min_similarity = query_dict.get("min_similarity", 0.0)
                    query.vector_field = query_dict.get("vector_field", "vector")
                elif query_type == SearchType.KEYWORD:
                    query.query_text = query_dict.get("query_text")
                    query.fields = query_dict.get("fields")
                    query.operator = query_dict.get("operator", "and")
                elif query_type == SearchType.HYBRID:
                    query.vector = query_dict.get("vector")
                    query.query_text = query_dict.get("query_text")
                    query.vector_weight = query_dict.get("vector_weight", 0.5)
                    query.text_weight = query_dict.get("text_weight", 0.5)

                # Set common parameters
                query.include_metadata = query_dict.get("include_metadata", True)
                query.max_distance = query_dict.get("max_distance")
                query.shard_routing_hint = query_dict.get("shard_routing_hint")
                query.search_config = query_dict.get("search_config")
                query.trace_id = query_dict.get("trace_id")

                # Execute the search on local shards
                results = await self._search_local_shards(query)

                # Build and send response
                response = {
                    "status": "success",
                    "node_id": self.node.node_id,
                    "results": [asdict(result) for result in results],
                    "total_results": len(results),
                    "dataset_id": query.dataset_id,
                    "searched_shards": query.shard_routing_hint,  # Return which shards were searched
                    "trace_id": query.trace_id
                }
            else:
                # Unknown action
                response = {
                    "status": "error",
                    "message": f"Unknown action: {request.get('action')}"
                }

            # Send response
            await stream.write(json.dumps(response).encode())

        except Exception as e:
            # Handle errors
            logging.error(f"Error handling federated search: {str(e)}")
            try:
                error_response = {
                    "status": "error",
                    "message": str(e),
                    "node_id": getattr(self.node, "node_id", "unknown")
                }
                await stream.write(json.dumps(error_response).encode())
            except:
                pass
        finally:
            # Always close the stream
            await stream.close()

    async def _search_local_shards(self, query: SearchQuery) -> List[SearchResult]:
        """
        Search locally available shards for the query.

        Args:
            query: The search query

        Returns:
            List[SearchResult]: Search results from local shards
        """
        # Access the shard manager to get relevant shards
        if not hasattr(self.node, 'shard_manager'):
            logging.warning("Node does not have a shard manager, cannot search local shards")
            return []

        # Get shards for the dataset
        dataset_shards = [
            shard for shard in self.node.shard_manager.shards.values()
            if shard.dataset_id == query.dataset_id
        ]

        # Filter by shard routing hint if provided
        if query.shard_routing_hint:
            dataset_shards = [
                shard for shard in dataset_shards
                if shard.shard_id in query.shard_routing_hint
            ]

        # If no shards available, return empty results
        if not dataset_shards:
            return []

        results = []

        # Process each shard
        for shard in dataset_shards:
            # Get shard storage path
            shard_path = os.path.join(
                self.node.shard_manager.storage_dir,
                "shards",
                f"{shard.shard_id}.{shard.format}"
            )

            # Check if the shard file exists
            if not os.path.exists(shard_path):
                logging.warning(f"Shard file not found: {shard_path}")
                continue

            # Choose the appropriate search method based on query type
            if query.query_type == SearchType.VECTOR:
                shard_results = await self._vector_search_shard(shard, shard_path, query)
            elif query.query_type == SearchType.KEYWORD:
                shard_results = await self._keyword_search_shard(shard, shard_path, query)
            elif query.query_type == SearchType.HYBRID:
                shard_results = await self._hybrid_search_shard(shard, shard_path, query)
            elif query.query_type == SearchType.FILTER:
                shard_results = await self._filter_search_shard(shard, shard_path, query)
            else:
                logging.warning(f"Unsupported query type: {query.query_type}")
                shard_results = []

            # Add shard's results to the combined results
            results.extend(shard_results)

        # Sort results by score (descending) and limit to top_k
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:query.top_k]

    async def _vector_search_shard(
        self,
        shard: ShardMetadata,
        shard_path: str,
        query: SearchQuery
    ) -> List[SearchResult]:
        """
        Perform vector search on a shard.

        Args:
            shard: Metadata for the shard
            shard_path: Path to the shard file
            query: The search query

        Returns:
            List[SearchResult]: Search results from this shard
        """
        results = []

        try:
            # Load the shard data
            if shard.format == "parquet":
                import pyarrow.parquet as pq
                shard_data = pq.read_table(shard_path)
            elif shard.format == "arrow":
                import pyarrow as pa
                with pa.memory_map(shard_path, "r") as source:
                    shard_data = pa.ipc.open_file(source).read_all()
            else:
                logging.warning(f"Unsupported shard format: {shard.format}")
                return results

            # Check if the vector field exists
            if query.vector_field not in shard_data.column_names:
                logging.warning(f"Vector field '{query.vector_field}' not found in shard {shard.shard_id}")
                return results

            # Extract vectors from the shard
            vector_column = shard_data[query.vector_field]
            vectors = np.array(vector_column.to_pylist())

            # Ensure vectors are 2D
            if len(vectors.shape) == 1:
                # Single vector in column, needs reshaping
                vectors = vectors.reshape(1, -1)
            elif len(vectors.shape) == 3:
                # Nested list structure in column, flatten first dimension
                vectors = vectors.reshape(vectors.shape[0], -1)

            # Convert query vector to numpy array
            query_vector = np.array(query.vector, dtype=np.float32)

            # Compute similarities based on distance metric
            if query.distance_metric == "cosine":
                # Normalize vectors for cosine similarity
                vectors_norm = np.linalg.norm(vectors, axis=1, keepdims=True)
                vectors_norm = np.where(vectors_norm == 0, 1e-10, vectors_norm)  # Avoid division by zero
                normalized_vectors = vectors / vectors_norm

                query_norm = np.linalg.norm(query_vector)
                query_norm = query_norm if query_norm > 0 else 1e-10
                normalized_query = query_vector / query_norm

                # Compute cosine similarities
                similarities = np.dot(normalized_vectors, normalized_query)
                distances = 1 - similarities
            elif query.distance_metric == "l2":
                # Compute Euclidean (L2) distances
                distances = np.sqrt(np.sum((vectors - query_vector)**2, axis=1))
                similarities = 1 / (1 + distances)  # Convert to similarity score
            elif query.distance_metric == "dot":
                # Compute dot product
                similarities = np.dot(vectors, query_vector)
                distances = -similarities  # Use negative similarity as distance
            else:
                logging.warning(f"Unsupported distance metric: {query.distance_metric}")
                return results

            # Apply similarity threshold if specified
            if query.min_similarity > 0:
                valid_indices = np.where(similarities >= query.min_similarity)[0]
                if len(valid_indices) == 0:
                    return results
            else:
                valid_indices = np.arange(len(vectors))

            # Sort by similarity (descending)
            sorted_indices = valid_indices[np.argsort(-similarities[valid_indices])]

            # Get top_k results
            top_indices = sorted_indices[:query.top_k]

            # Create result objects
            for i, idx in enumerate(top_indices):
                # Get result ID (use index if no ID field)
                result_id = str(idx)
                if "id" in shard_data.column_names:
                    result_id = str(shard_data["id"][idx].as_py())

                # Create metadata if requested
                metadata = None
                if query.include_metadata:
                    metadata = {
                        field: shard_data[field][idx].as_py()
                        for field in shard_data.column_names
                        if field != query.vector_field  # Exclude vector field
                    }

                # Include vector if requested
                result_vector = None
                if query.include_metadata:
                    try:
                        result_vector = vectors[idx].tolist()
                    except:
                        # Skip vector if it can't be converted
                        pass

                # Create the result
                result = SearchResult(
                    id=result_id,
                    dataset_id=query.dataset_id,
                    shard_id=shard.shard_id,
                    score=float(similarities[idx]),
                    distance=float(distances[idx]),
                    node_id=self.node.node_id,
                    metadata=metadata,
                    vector=result_vector,
                    source_rank=i
                )

                results.append(result)

        except Exception as e:
            logging.error(f"Error performing vector search on shard {shard.shard_id}: {str(e)}")

        return results

    async def _keyword_search_shard(
        self,
        shard: ShardMetadata,
        shard_path: str,
        query: SearchQuery
    ) -> List[SearchResult]:
        """
        Perform keyword search on a shard.

        Args:
            shard: Metadata for the shard
            shard_path: Path to the shard file
            query: The search query

        Returns:
            List[SearchResult]: Search results from this shard
        """
        results = []

        try:
            # Load the shard data
            if shard.format == "parquet":
                import pyarrow.parquet as pq
                shard_data = pq.read_table(shard_path)
            elif shard.format == "arrow":
                import pyarrow as pa
                with pa.memory_map(shard_path, "r") as source:
                    shard_data = pa.ipc.open_file(source).read_all()
            else:
                logging.warning(f"Unsupported shard format: {shard.format}")
                return results

            # Convert to pandas DataFrame for easier text search
            import pandas as pd
            df = shard_data.to_pandas()

            # Determine which fields to search
            search_fields = query.fields if query.fields else [
                col for col in df.columns
                if df[col].dtype == 'object'  # String columns
            ]

            # Filter out fields that don't exist
            search_fields = [field for field in search_fields if field in df.columns]

            if not search_fields:
                logging.warning(f"No text fields found to search in shard {shard.shard_id}")
                return results

            # Parse query terms
            query_terms = query.query_text.lower().split()

            # Initialize result arrays
            match_scores = np.zeros(len(df))
            matched_terms_list = [[] for _ in range(len(df))]
            matched_fields_list = [set() for _ in range(len(df))]

            # Search each field for matches
            for field in search_fields:
                # Convert field to string and lowercase
                field_values = df[field].fillna("").astype(str).str.lower()

                # Check each query term
                for term in query_terms:
                    # Find matches
                    matches = field_values.str.contains(term, regex=False)

                    # Update scores and matched terms
                    for i, match in enumerate(matches):
                        if match:
                            match_scores[i] += 1
                            matched_terms_list[i].append(term)
                            matched_fields_list[i].add(field)

            # Adjust scores based on operator
            if query.operator.lower() == "and":
                # Only keep rows that match all terms
                valid_mask = match_scores >= len(query_terms)
                match_scores = np.where(valid_mask, match_scores, 0)

            # Sort by score and get top results
            top_indices = np.argsort(-match_scores)[:query.top_k]

            # Create result objects
            for i, idx in enumerate(top_indices):
                # Skip if score is 0
                if match_scores[idx] == 0:
                    continue

                # Calculate normalized score
                score = float(match_scores[idx]) / len(query_terms)

                # Get result ID (use index if no ID field)
                result_id = str(idx)
                if "id" in df.columns:
                    result_id = str(df.iloc[idx]["id"])

                # Create metadata if requested
                metadata = None
                if query.include_metadata:
                    metadata = df.iloc[idx].to_dict()

                # Create the result
                result = SearchResult(
                    id=result_id,
                    dataset_id=query.dataset_id,
                    shard_id=shard.shard_id,
                    score=score,
                    node_id=self.node.node_id,
                    metadata=metadata,
                    source_rank=i,
                    matched_terms=matched_terms_list[idx],
                    matched_fields=list(matched_fields_list[idx])
                )

                results.append(result)

        except Exception as e:
            logging.error(f"Error performing keyword search on shard {shard.shard_id}: {str(e)}")

        return results

    async def _hybrid_search_shard(
        self,
        shard: ShardMetadata,
        shard_path: str,
        query: SearchQuery
    ) -> List[SearchResult]:
        """
        Perform hybrid search (vector + keyword) on a shard.

        Args:
            shard: Metadata for the shard
            shard_path: Path to the shard file
            query: The search query

        Returns:
            List[SearchResult]: Search results from this shard
        """
        # Execute both vector and keyword searches
        vector_query = SearchQuery(
            dataset_id=query.dataset_id,
            query_type=SearchType.VECTOR,
            top_k=query.top_k * 2,  # Get more results for hybrid ranking
            vector=query.vector,
            distance_metric=query.distance_metric,
            min_similarity=0.0,  # No minimum similarity for hybrid
            vector_field=query.vector_field,
            include_metadata=query.include_metadata
        )

        keyword_query = SearchQuery(
            dataset_id=query.dataset_id,
            query_type=SearchType.KEYWORD,
            top_k=query.top_k * 2,  # Get more results for hybrid ranking
            query_text=query.query_text,
            fields=query.fields,
            operator=query.operator,
            include_metadata=query.include_metadata
        )

        # Execute both searches
        vector_results = await self._vector_search_shard(shard, shard_path, vector_query)
        keyword_results = await self._keyword_search_shard(shard, shard_path, keyword_query)

        # Combine results
        combined_results = {}

        # Add vector results with weighted scores
        for result in vector_results:
            result_id = result.id
            combined_results[result_id] = result
            combined_results[result_id].score *= query.vector_weight

        # Add keyword results with weighted scores
        for result in keyword_results:
            result_id = result.id
            if result_id in combined_results:
                # Result exists in both sets, combine scores
                existing = combined_results[result_id]
                combined_score = existing.score + (result.score * query.text_weight)

                # Update the existing result
                existing.score = combined_score
                existing.matched_terms = result.matched_terms
                existing.matched_fields = result.matched_fields
            else:
                # New result from keyword search
                result.score *= query.text_weight
                combined_results[result_id] = result

        # Convert to list and sort by score
        results = list(combined_results.values())
        results.sort(key=lambda x: x.score, reverse=True)

        # Return top_k results
        return results[:query.top_k]

    async def _filter_search_shard(
        self,
        shard: ShardMetadata,
        shard_path: str,
        query: SearchQuery
    ) -> List[SearchResult]:
        """
        Perform filter-based search on a shard.

        Args:
            shard: Metadata for the shard
            shard_path: Path to the shard file
            query: The search query

        Returns:
            List[SearchResult]: Search results from this shard
        """
        results = []

        try:
            # Load the shard data
            if shard.format == "parquet":
                import pyarrow.parquet as pq
                shard_data = pq.read_table(shard_path)
            elif shard.format == "arrow":
                import pyarrow as pa
                with pa.memory_map(shard_path, "r") as source:
                    shard_data = pa.ipc.open_file(source).read_all()
            else:
                logging.warning(f"Unsupported shard format: {shard.format}")
                return results

            # Convert to pandas DataFrame for filtering
            import pandas as pd
            df = shard_data.to_pandas()

            # No filters provided, return all rows
            if not query.filters:
                # Create results from all rows
                for i in range(min(len(df), query.top_k)):
                    # Get result ID (use index if no ID field)
                    result_id = str(i)
                    if "id" in df.columns:
                        result_id = str(df.iloc[i]["id"])

                    # Create metadata if requested
                    metadata = None
                    if query.include_metadata:
                        metadata = df.iloc[i].to_dict()

                    # Create result with score 1.0
                    result = SearchResult(
                        id=result_id,
                        dataset_id=query.dataset_id,
                        shard_id=shard.shard_id,
                        score=1.0,
                        node_id=self.node.node_id,
                        metadata=metadata,
                        source_rank=i
                    )

                    results.append(result)

                return results[:query.top_k]

            # Apply each filter
            mask = pd.Series([True] * len(df))
            for filter_dict in query.filters:
                field = filter_dict.get("field")
                operator = filter_dict.get("operator", "eq")
                value = filter_dict.get("value")

                # Skip invalid filters
                if not field or field not in df.columns:
                    continue

                # Apply the filter based on operator
                if operator == "eq":
                    mask &= df[field] == value
                elif operator == "neq":
                    mask &= df[field] != value
                elif operator == "gt":
                    mask &= df[field] > value
                elif operator == "gte":
                    mask &= df[field] >= value
                elif operator == "lt":
                    mask &= df[field] < value
                elif operator == "lte":
                    mask &= df[field] <= value
                elif operator == "in":
                    mask &= df[field].isin(value)
                elif operator == "nin":
                    mask &= ~df[field].isin(value)
                elif operator == "contains":
                    if isinstance(value, str):
                        mask &= df[field].astype(str).str.contains(value, regex=False)
                elif operator == "between":
                    if isinstance(value, list) and len(value) == 2:
                        mask &= (df[field] >= value[0]) & (df[field] <= value[1])

            # Get filtered rows
            filtered_df = df[mask]

            # Create results from filtered rows
            for i in range(min(len(filtered_df), query.top_k)):
                # Get result ID (use index if no ID field)
                result_id = str(filtered_df.index[i])
                if "id" in filtered_df.columns:
                    result_id = str(filtered_df.iloc[i]["id"])

                # Create metadata if requested
                metadata = None
                if query.include_metadata:
                    metadata = filtered_df.iloc[i].to_dict()

                # Create result with score 1.0
                result = SearchResult(
                    id=result_id,
                    dataset_id=query.dataset_id,
                    shard_id=shard.shard_id,
                    score=1.0,
                    node_id=self.node.node_id,
                    metadata=metadata,
                    source_rank=i
                )

                results.append(result)

        except Exception as e:
            logging.error(f"Error performing filter search on shard {shard.shard_id}: {str(e)}")

        return results

    def _generate_query_hash(self, query: SearchQuery) -> str:
        """
        Generate a hash key for the query for caching purposes.

        Args:
            query: The search query

        Returns:
            str: Hash of the query
        """
        # Convert query to a dictionary
        query_dict = asdict(query)

        # Remove non-deterministic fields
        query_dict.pop("timeout_ms", None)
        query_dict.pop("trace_id", None)

        # Convert to string and hash
        query_str = json.dumps(query_dict, sort_keys=True)
        return hashlib.sha256(query_str.encode()).hexdigest()

    def _check_cache(self, query_hash: str) -> Optional[AggregatedSearchResults]:
        """
        Check if results for this query are in the cache.

        Args:
            query_hash: Hash of the query

        Returns:
            Optional[AggregatedSearchResults]: Cached results or None
        """
        if not self.use_cache:
            return None

        # Check if query is in cache and not expired
        if query_hash in self.result_cache:
            results, timestamp = self.result_cache[query_hash]
            if time.time() - timestamp <= self.cache_ttl_seconds:
                # Cache hit
                self.stats["cache_hits"] += 1
                return results

            # Expired, remove from cache
            del self.result_cache[query_hash]

        return None

    def _update_cache(self, query_hash: str, results: AggregatedSearchResults):
        """
        Update the cache with new results.

        Args:
            query_hash: Hash of the query
            results: The search results
        """
        if not self.use_cache:
            return

        # Add to cache with current timestamp
        self.result_cache[query_hash] = (results, time.time())

        # Check if cache is too large
        if len(self.result_cache) > self.max_cache_size:
            # Remove oldest items
            sorted_items = sorted(self.result_cache.items(), key=lambda x: x[1][1])
            items_to_remove = sorted_items[:len(self.result_cache) // 4]  # Remove 25%
            for key, _ in items_to_remove:
                del self.result_cache[key]

    async def search(self, query: SearchQuery) -> AggregatedSearchResults:
        """
        Perform a federated search across multiple nodes.

        Args:
            query: The search query

        Returns:
            AggregatedSearchResults: Aggregated search results
        """
        self.stats["total_queries"] += 1
        start_time = time.time()

        # Check cache first
        query_hash = self._generate_query_hash(query)
        cached_results = self._check_cache(query_hash)
        if cached_results:
            return cached_results

        # Need to perform the search
        trace_info = {"search_started": start_time, "query": asdict(query)}

        # Initialize empty results
        aggregated_results = AggregatedSearchResults(
            query=query,
            trace_info=trace_info
        )

        try:
            # Get dataset metadata
            if not hasattr(self.node, 'shard_manager'):
                raise ValueError("Node does not have a shard manager")

            if query.dataset_id not in self.node.shard_manager.datasets:
                raise ValueError(f"Dataset {query.dataset_id} not found")

            dataset = self.node.shard_manager.datasets[query.dataset_id]

            # Find all shards for this dataset
            dataset_info = await self.node.shard_manager.find_dataset_shards(
                dataset_id=query.dataset_id,
                include_metadata=True
            )

            # Get all nodes with shards
            nodes_with_shards = set()
            for shard_id, node_ids in dataset_info["shard_locations"].items():
                nodes_with_shards.update(node_ids)

            # Add trace info
            trace_info["dataset"] = dataset.__dict__
            trace_info["nodes_with_shards"] = list(nodes_with_shards)
            trace_info["total_shards"] = len(dataset_info["shard_locations"])

            # Search local shards
            local_results = await self._search_local_shards(query)

            # Add local results
            aggregated_results.results.extend(local_results)
            aggregated_results.total_results += len(local_results)
            aggregated_results.nodes_queried.append(self.node.node_id)
            aggregated_results.nodes_responded.append(self.node.node_id)

            # Add local shard IDs
            local_shard_ids = [
                shard.shard_id for shard in self.node.shard_manager.shards.values()
                if shard.dataset_id == query.dataset_id
            ]
            aggregated_results.shards_searched.extend(local_shard_ids)

            # Query remote nodes
            remote_nodes = [node_id for node_id in nodes_with_shards if node_id != self.node.node_id]

            # Search remote nodes if present
            if remote_nodes:
                remote_results = await self._search_remote_nodes(
                    query=query,
                    node_ids=remote_nodes
                )

                # Add remote results
                for node_results in remote_results:
                    if node_results.get("status") == "success":
                        node_id = node_results.get("node_id")
                        results_list = node_results.get("results", [])

                        # Convert to SearchResult objects
                        for result_dict in results_list:
                            result = SearchResult(**result_dict)
                            aggregated_results.results.append(result)

                        # Update aggregated stats
                        aggregated_results.total_results += len(results_list)
                        aggregated_results.nodes_responded.append(node_id)

                        # Add searched shards
                        if "searched_shards" in node_results and node_results["searched_shards"]:
                            aggregated_results.shards_searched.extend(node_results["searched_shards"])
                    else:
                        # Add error info
                        error = {
                            "node_id": node_results.get("node_id", "unknown"),
                            "message": node_results.get("message", "Unknown error")
                        }
                        aggregated_results.errors.append(error)

                # Add all queried nodes
                for node_id in remote_nodes:
                    if node_id not in aggregated_results.nodes_queried:
                        aggregated_results.nodes_queried.append(node_id)

            # Rank and limit results
            aggregated_results.results = self._rank_results(
                aggregated_results.results,
                query.top_k,
                self.ranking_strategy
            )

        except Exception as e:
            # Record error
            self.stats["errors"] += 1
            error = {"message": str(e)}
            aggregated_results.errors.append(error)
            trace_info["error"] = str(e)
            logging.error(f"Error in federated search: {str(e)}")

        # Update execution time
        end_time = time.time()
        execution_time_ms = int((end_time - start_time) * 1000)
        aggregated_results.execution_time_ms = execution_time_ms
        trace_info["search_completed"] = end_time
        trace_info["execution_time_ms"] = execution_time_ms

        # Update stats
        self.stats["total_execution_time_ms"] += execution_time_ms
        self.stats["nodes_queried"].update(aggregated_results.nodes_queried)

        # Cache the results
        self._update_cache(query_hash, aggregated_results)

        return aggregated_results

    async def _search_remote_nodes(
        self,
        query: SearchQuery,
        node_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Search for data on remote nodes.

        Args:
            query: The search query
            node_ids: IDs of nodes to search

        Returns:
            List[Dict[str, Any]]: Results from each node
        """
        # Prepare search request
        search_request = {
            "action": "search",
            "query": asdict(query)
        }

        # Create tasks for each node
        tasks = []
        for node_id in node_ids:
            tasks.append(self._query_node(node_id, search_request))

        # Execute tasks concurrently
        if not tasks:
            return []

        # Set timeout based on query or default
        timeout = query.timeout_ms / 1000 if query.timeout_ms else self.default_timeout_ms / 1000

        # Execute tasks with timeout
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.TimeoutError:
            logging.warning(f"Search timed out after {timeout} seconds")
            results = [{"status": "error", "message": f"Timeout after {timeout} seconds"}] * len(tasks)

        # Process results
        processed_results = []
        for i, result in enumerate(results):
            node_id = node_ids[i]

            if isinstance(result, Exception):
                # Handle exceptions
                processed_results.append({
                    "status": "error",
                    "node_id": node_id,
                    "message": str(result)
                })
            elif isinstance(result, dict):
                # Add node_id if not present
                if "node_id" not in result:
                    result["node_id"] = node_id
                processed_results.append(result)
            else:
                # Unexpected result type
                processed_results.append({
                    "status": "error",
                    "node_id": node_id,
                    "message": f"Unexpected result type: {type(result)}"
                })

        return processed_results

    async def _query_node(self, node_id: str, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a search request to a specific node.

        Args:
            node_id: ID of the node to query
            request: The search request

        Returns:
            Dict[str, Any]: Response from the node
        """
        try:
            # Send message to the node
            response = await self.node.send_message(
                peer_id=node_id,
                protocol=NetworkProtocol.FEDERATED_SEARCH,
                data=request
            )
            return response
        except Exception as e:
            # Return error response
            return {
                "status": "error",
                "node_id": node_id,
                "message": str(e)
            }

    def _rank_results(
        self,
        results: List[SearchResult],
        top_k: int,
        strategy: RankingStrategy
    ) -> List[SearchResult]:
        """
        Rank and limit the search results.

        Args:
            results: The search results to rank
            top_k: Maximum number of results to return
            strategy: Ranking strategy to use

        Returns:
            List[SearchResult]: Ranked and limited results
        """
        if not results:
            return []

        if strategy == RankingStrategy.SCORE:
            # Simply sort by score
            ranked_results = sorted(results, key=lambda x: x.score, reverse=True)
            return ranked_results[:top_k]

        elif strategy == RankingStrategy.SOURCE_WEIGHTED:
            # Weight results by source node reliability
            # For simplicity, we'll just use a random weight for each node
            # In a real implementation, this would be based on node performance
            node_weights = {}
            for result in results:
                if result.node_id not in node_weights:
                    node_weights[result.node_id] = random.uniform(0.5, 1.0)

            # Apply weights
            for result in results:
                result.score *= node_weights[result.node_id]

            # Sort by adjusted score
            ranked_results = sorted(results, key=lambda x: x.score, reverse=True)
            return ranked_results[:top_k]

        elif strategy == RankingStrategy.ROUND_ROBIN:
            # Take results from each node in turn
            nodes = set(result.node_id for result in results)
            results_by_node = {node: [] for node in nodes}

            # Group results by node
            for result in results:
                results_by_node[result.node_id].append(result)

            # Sort each node's results
            for node in nodes:
                results_by_node[node].sort(key=lambda x: x.score, reverse=True)

            # Round-robin selection
            ranked_results = []
            while len(ranked_results) < top_k and any(results_by_node.values()):
                for node in list(nodes):
                    if results_by_node[node]:
                        ranked_results.append(results_by_node[node].pop(0))
                        if len(ranked_results) >= top_k:
                            break

            return ranked_results

        elif strategy == RankingStrategy.HYBRID:
            # Combine multiple strategies
            # Start with top half from score-based ranking
            score_results = sorted(results, key=lambda x: x.score, reverse=True)
            half_count = min(top_k // 2, len(score_results))
            ranked_results = score_results[:half_count]

            # Take remaining from round-robin
            remaining_count = top_k - half_count
            if remaining_count > 0:
                # Remove already selected results
                selected_ids = set(result.id for result in ranked_results)
                remaining_results = [r for r in results if r.id not in selected_ids]

                # Group by node
                nodes = set(result.node_id for result in remaining_results)
                results_by_node = {node: [] for node in nodes}

                for result in remaining_results:
                    results_by_node[result.node_id].append(result)

                # Sort each node's results
                for node in nodes:
                    results_by_node[node].sort(key=lambda x: x.score, reverse=True)

                # Round-robin selection for remaining slots
                while len(ranked_results) < top_k and any(results_by_node.values()):
                    for node in list(nodes):
                        if results_by_node[node]:
                            ranked_results.append(results_by_node[node].pop(0))
                            if len(ranked_results) >= top_k:
                                break

            return ranked_results

        # Default to score-based ranking
        ranked_results = sorted(results, key=lambda x: x.score, reverse=True)
        return ranked_results[:top_k]

    async def vector_search(
        self,
        dataset_id: str,
        query_vector: List[float],
        top_k: int = 10,
        distance_metric: str = "cosine",
        min_similarity: float = 0.0,
        timeout_ms: int = 5000,
        include_metadata: bool = True
    ) -> AggregatedSearchResults:
        """
        Perform a federated vector search.

        Args:
            dataset_id: ID of the dataset to search
            query_vector: Vector to search for
            top_k: Maximum number of results to return
            distance_metric: Distance metric to use (cosine, l2, dot)
            min_similarity: Minimum similarity score for results
            timeout_ms: Timeout in milliseconds
            include_metadata: Whether to include metadata in results

        Returns:
            AggregatedSearchResults: Search results
        """
        # Create a vector search query
        query = SearchQuery(
            dataset_id=dataset_id,
            query_type=SearchType.VECTOR,
            top_k=top_k,
            timeout_ms=timeout_ms,
            vector=query_vector,
            distance_metric=distance_metric,
            min_similarity=min_similarity,
            include_metadata=include_metadata
        )

        # Execute the search
        return await self.search(query)

    async def keyword_search(
        self,
        dataset_id: str,
        query_text: str,
        fields: Optional[List[str]] = None,
        top_k: int = 10,
        operator: str = "and",
        timeout_ms: int = 5000,
        include_metadata: bool = True
    ) -> AggregatedSearchResults:
        """
        Perform a federated keyword search.

        Args:
            dataset_id: ID of the dataset to search
            query_text: Text to search for
            fields: Fields to search in (all text fields if None)
            top_k: Maximum number of results to return
            operator: Logical operator for term matching (and, or)
            timeout_ms: Timeout in milliseconds
            include_metadata: Whether to include metadata in results

        Returns:
            AggregatedSearchResults: Search results
        """
        # Create a keyword search query
        query = SearchQuery(
            dataset_id=dataset_id,
            query_type=SearchType.KEYWORD,
            top_k=top_k,
            timeout_ms=timeout_ms,
            query_text=query_text,
            fields=fields,
            operator=operator,
            include_metadata=include_metadata
        )

        # Execute the search
        return await self.search(query)

    async def hybrid_search(
        self,
        dataset_id: str,
        query_text: str,
        query_vector: List[float],
        fields: Optional[List[str]] = None,
        top_k: int = 10,
        vector_weight: float = 0.5,
        text_weight: float = 0.5,
        timeout_ms: int = 5000,
        include_metadata: bool = True
    ) -> AggregatedSearchResults:
        """
        Perform a federated hybrid search (vector + keyword).

        Args:
            dataset_id: ID of the dataset to search
            query_text: Text to search for
            query_vector: Vector to search for
            fields: Fields to search in (all text fields if None)
            top_k: Maximum number of results to return
            vector_weight: Weight for vector similarity (0.0 to 1.0)
            text_weight: Weight for text similarity (0.0 to 1.0)
            timeout_ms: Timeout in milliseconds
            include_metadata: Whether to include metadata in results

        Returns:
            AggregatedSearchResults: Search results
        """
        # Create a hybrid search query
        query = SearchQuery(
            dataset_id=dataset_id,
            query_type=SearchType.HYBRID,
            top_k=top_k,
            timeout_ms=timeout_ms,
            query_text=query_text,
            vector=query_vector,
            fields=fields,
            vector_weight=vector_weight,
            text_weight=text_weight,
            include_metadata=include_metadata
        )

        # Execute the search
        return await self.search(query)

    async def filter_search(
        self,
        dataset_id: str,
        filters: List[Dict[str, Any]],
        top_k: int = 10,
        timeout_ms: int = 5000,
        include_metadata: bool = True
    ) -> AggregatedSearchResults:
        """
        Perform a federated filter search.

        Args:
            dataset_id: ID of the dataset to search
            filters: List of filters to apply
            top_k: Maximum number of results to return
            timeout_ms: Timeout in milliseconds
            include_metadata: Whether to include metadata in results

        Returns:
            AggregatedSearchResults: Search results
        """
        # Create a filter search query
        query = SearchQuery(
            dataset_id=dataset_id,
            query_type=SearchType.FILTER,
            top_k=top_k,
            timeout_ms=timeout_ms,
            filters=filters,
            include_metadata=include_metadata
        )

        # Execute the search
        return await self.search(query)

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about search operations.

        Returns:
            Dict[str, Any]: Search statistics
        """
        stats = self.stats.copy()

        # Calculate derived statistics
        if stats["total_queries"] > 0:
            stats["avg_execution_time_ms"] = stats["total_execution_time_ms"] / stats["total_queries"]
            stats["cache_hit_rate"] = stats["cache_hits"] / stats["total_queries"]
            stats["error_rate"] = stats["errors"] / stats["total_queries"]
        else:
            stats["avg_execution_time_ms"] = 0
            stats["cache_hit_rate"] = 0
            stats["error_rate"] = 0

        # Convert sets to lists for JSON serialization
        stats["nodes_queried"] = list(stats["nodes_queried"])
        stats["nodes_queried_count"] = len(stats["nodes_queried"])

        # Add cache stats
        stats["cache_size"] = len(self.result_cache)
        stats["cache_enabled"] = self.use_cache

        return stats

    def clear_cache(self):
        """Clear the search result cache."""
        self.result_cache.clear()

    def reset_statistics(self):
        """Reset all search statistics."""
        self.stats = {
            "total_queries": 0,
            "cache_hits": 0,
            "total_execution_time_ms": 0,
            "nodes_queried": set(),
            "errors": 0
        }


# Helper for vector similarity calculation
def vector_similarity(
    vec1: np.ndarray,
    vec2: np.ndarray,
    metric: str = "cosine"
) -> float:
    """
    Calculate similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector
        metric: Similarity metric (cosine, l2, dot)

    Returns:
        float: Similarity score
    """
    # Convert to numpy arrays
    v1 = np.array(vec1)
    v2 = np.array(vec2)

    if metric == "cosine":
        # Cosine similarity
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return np.dot(v1, v2) / (norm1 * norm2)

    elif metric == "l2":
        # Euclidean distance converted to similarity
        distance = np.linalg.norm(v1 - v2)
        return 1.0 / (1.0 + distance)

    elif metric == "dot":
        # Dot product
        return float(np.dot(v1, v2))

    else:
        raise ValueError(f"Unsupported metric: {metric}")


# Helper class for creating a distributed federated search index
class DistributedSearchIndex:
    """
    Utility for creating and managing distributed search indices.

    This class assists with creating and managing search indices for sharded
    datasets distributed across IPFS nodes, with support for vector similarity,
    keyword, and hybrid searches.
    """

    def __init__(
        self,
        dataset_id: str,
        base_dir: str,
        vector_dimensions: Optional[int] = None,
        distance_metric: str = "cosine",
        enable_faiss: bool = True
    ):
        """
        Initialize a distributed search index.

        Args:
            dataset_id: ID of the dataset for this index
            base_dir: Base directory for index storage
            vector_dimensions: Dimensions of vectors (for vector search)
            distance_metric: Distance metric for vector search
            enable_faiss: Whether to use FAISS for vector search if available
        """
        self.dataset_id = dataset_id
        self.base_dir = base_dir
        self.vector_dimensions = vector_dimensions
        self.distance_metric = distance_metric
        self.enable_faiss = enable_faiss and FAISS_AVAILABLE

        # Create index directories
        self.index_dir = os.path.join(base_dir, "indices", dataset_id)
        os.makedirs(self.index_dir, exist_ok=True)

        # Initialize vector index if needed
        self.vector_index = None
        if vector_dimensions and self.enable_faiss:
            self._init_vector_index()

    def _init_vector_index(self):
        """Initialize the FAISS vector index."""
        if not FAISS_AVAILABLE:
            logging.warning("FAISS is not available, using numpy for vector search")
            return

        try:
            # Choose index type based on dimensions and metric
            if self.distance_metric == "cosine":
                # L2 index for cosine similarity (with normalization)
                self.vector_index = faiss.IndexFlatL2(self.vector_dimensions)
            elif self.distance_metric == "l2":
                # L2 index
                self.vector_index = faiss.IndexFlatL2(self.vector_dimensions)
            elif self.distance_metric == "dot":
                # Inner product index
                self.vector_index = faiss.IndexFlatIP(self.vector_dimensions)
            else:
                logging.warning(f"Unsupported metric for FAISS: {self.distance_metric}")
                self.vector_index = None

        except Exception as e:
            logging.error(f"Error initializing FAISS index: {str(e)}")
            self.vector_index = None

    async def build_indices_for_shard(
        self,
        shard_path: str,
        shard_id: str,
        shard_format: str = "parquet",
        vector_field: str = "vector",
        text_fields: Optional[List[str]] = None,
        include_all_text_fields: bool = True
    ) -> Dict[str, Any]:
        """
        Build search indices for a shard.

        Args:
            shard_path: Path to the shard file
            shard_id: ID of the shard
            shard_format: Format of the shard
            vector_field: Field containing vectors
            text_fields: Fields to index for text search
            include_all_text_fields: Whether to index all text fields

        Returns:
            Dict[str, Any]: Index building results
        """
        results = {
            "shard_id": shard_id,
            "vector_index": False,
            "text_index": False,
            "vector_count": 0,
            "text_field_count": 0,
            "errors": []
        }

        try:
            # Load the shard data
            if shard_format == "parquet":
                import pyarrow.parquet as pq
                shard_data = pq.read_table(shard_path)
            elif shard_format == "arrow":
                import pyarrow as pa
                with pa.memory_map(shard_path, "r") as source:
                    shard_data = pa.ipc.open_file(source).read_all()
            else:
                error = f"Unsupported shard format: {shard_format}"
                results["errors"].append(error)
                return results

            # Build vector index if needed
            if self.vector_dimensions and vector_field in shard_data.column_names:
                try:
                    # Get vectors
                    vectors = np.array(shard_data[vector_field].to_pylist())

                    # Adjust dimensions if needed
                    if len(vectors.shape) == 1:
                        # Single vector, reshape
                        vectors = vectors.reshape(1, -1)
                    elif len(vectors.shape) == 3:
                        # Nested vectors, flatten first dimension
                        vectors = vectors.reshape(vectors.shape[0], -1)

                    if vectors.shape[1] != self.vector_dimensions:
                        error = f"Vector dimensions mismatch: expected {self.vector_dimensions}, got {vectors.shape[1]}"
                        results["errors"].append(error)
                    else:
                        # Add vectors to FAISS index if available
                        if self.vector_index is not None:
                            # Normalize vectors for cosine similarity
                            if self.distance_metric == "cosine":
                                faiss.normalize_L2(vectors)

                            # Add to index
                            self.vector_index.add(vectors.astype(np.float32))

                            # Save vectors to shard-specific file
                            vector_path = os.path.join(self.index_dir, f"{shard_id}_vectors.npy")
                            np.save(vector_path, vectors)

                            results["vector_index"] = True
                            results["vector_count"] = len(vectors)

                except Exception as e:
                    error = f"Error building vector index: {str(e)}"
                    results["errors"].append(error)

            # Build text index
            import pandas as pd
            df = shard_data.to_pandas()

            # Determine fields to index
            if text_fields:
                fields_to_index = [f for f in text_fields if f in df.columns]
            elif include_all_text_fields:
                # Include all string/object columns
                fields_to_index = [
                    col for col in df.columns
                    if df[col].dtype == 'object' or pd.api.types.is_string_dtype(df[col])
                ]
            else:
                fields_to_index = []

            if fields_to_index:
                # Create a simple inverted index
                inverted_index = {}
                doc_data = {}

                for i, row in df.iterrows():
                    # Get document ID
                    doc_id = str(i)
                    if "id" in df.columns:
                        doc_id = str(row["id"])

                    # Store document data
                    doc_data[doc_id] = {
                        field: row[field] for field in fields_to_index
                        if field in row and pd.notna(row[field])
                    }

                    # Index each field
                    for field in fields_to_index:
                        if field in row and pd.notna(row[field]):
                            # Get field value as string
                            value = str(row[field]).lower()

                            # Split into terms
                            terms = value.split()

                            # Add to inverted index
                            for term in terms:
                                if term not in inverted_index:
                                    inverted_index[term] = {}

                                if field not in inverted_index[term]:
                                    inverted_index[term][field] = set()

                                inverted_index[term][field].add(doc_id)

                # Convert sets to lists for JSON serialization
                for term in inverted_index:
                    for field in inverted_index[term]:
                        inverted_index[term][field] = list(inverted_index[term][field])

                # Save inverted index to file
                index_path = os.path.join(self.index_dir, f"{shard_id}_text_index.json")
                with open(index_path, "w") as f:
                    json.dump(inverted_index, f)

                # Save document data to file
                data_path = os.path.join(self.index_dir, f"{shard_id}_doc_data.json")
                with open(data_path, "w") as f:
                    json.dump(doc_data, f)

                results["text_index"] = True
                results["text_field_count"] = len(fields_to_index)

        except Exception as e:
            error = f"Error building indices: {str(e)}"
            results["errors"].append(error)

        return results

    def save_indices(self):
        """Save all indices to disk."""
        # Save FAISS index if available
        if self.vector_index is not None:
            try:
                # Create FAISS index file
                index_path = os.path.join(self.index_dir, "vector_index.faiss")
                faiss.write_index(self.vector_index, index_path)

                # Save metadata
                metadata = {
                    "dataset_id": self.dataset_id,
                    "vector_dimensions": self.vector_dimensions,
                    "distance_metric": self.distance_metric,
                    "vector_count": self.vector_index.ntotal,
                    "created_at": time.time()
                }

                metadata_path = os.path.join(self.index_dir, "vector_index_metadata.json")
                with open(metadata_path, "w") as f:
                    json.dump(metadata, f)

                return True
            except Exception as e:
                logging.error(f"Error saving FAISS index: {str(e)}")
                return False

        return False

    @classmethod
    async def build_for_dataset(
        cls,
        dataset_id: str,
        shard_manager: Any,
        base_dir: str,
        vector_dimensions: Optional[int] = None,
        distance_metric: str = "cosine",
        vector_field: str = "vector",
        text_fields: Optional[List[str]] = None,
        include_all_text_fields: bool = True
    ) -> "DistributedSearchIndex":
        """
        Build search indices for an entire dataset.

        Args:
            dataset_id: ID of the dataset
            shard_manager: Shard manager instance
            base_dir: Base directory for index storage
            vector_dimensions: Dimensions of vectors
            distance_metric: Distance metric for vector search
            vector_field: Field containing vectors
            text_fields: Fields to index for text search
            include_all_text_fields: Whether to index all text fields

        Returns:
            DistributedSearchIndex: The created index
        """
        # Create index instance
        index = cls(dataset_id, base_dir, vector_dimensions, distance_metric)

        # Get all shards for the dataset
        dataset_shards = [
            shard for shard in shard_manager.shards.values()
            if shard.dataset_id == dataset_id
        ]

        # Build indices for each shard
        for shard in dataset_shards:
            shard_path = os.path.join(
                shard_manager.storage_dir,
                "shards",
                f"{shard.shard_id}.{shard.format}"
            )

            # Skip if shard file doesn't exist
            if not os.path.exists(shard_path):
                continue

            # Build indices for this shard
            await index.build_indices_for_shard(
                shard_path=shard_path,
                shard_id=shard.shard_id,
                shard_format=shard.format,
                vector_field=vector_field,
                text_fields=text_fields,
                include_all_text_fields=include_all_text_fields
            )

        # Save the indices
        index.save_indices()

        return index
