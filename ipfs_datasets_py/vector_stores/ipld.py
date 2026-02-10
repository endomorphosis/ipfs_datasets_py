"""
IPLD Vector Store Module

Provides a class for storing and retrieving embedding vectors using IPLD.
This module implements efficient vector storage with IPLD and vector
similarity search capabilities.

Features:
- Store embedding vectors in IPLD format with content addressing
- Metadata storage for each vector
- Efficient nearest-neighbor search for similarity queries
- Multiple distance metrics (cosine, L2, inner product)
- Memory-mapped storage for large-scale vector collections
- Batch operations for efficient processing
- Serialization to/from CAR files
"""

import os
import json
import numpy as np
import tempfile
import logging
from typing import Dict, List, Any, Optional, Union, Tuple, Set, TypeVar, Generic
from collections import defaultdict
from dataclasses import dataclass

from ipfs_datasets_py.data_transformation.ipld.storage import IPLDStorage
from ipfs_datasets_py.data_transformation.ipld.dag_pb import create_dag_node, parse_dag_node
from ipfs_datasets_py.data_transformation.ipld.optimized_codec import OptimizedEncoder, OptimizedDecoder

# Check if we have optional dependencies
try:
    import faiss
    HAVE_FAISS = True
except ImportError:
    HAVE_FAISS = False

try:
    import ipld_car
    HAVE_IPLD_CAR = True
except ImportError:
    HAVE_IPLD_CAR = False

# Type for vector IDs
VectorID = str

@dataclass
class SearchResult:
    """Represents a search result from a vector store."""
    id: VectorID
    score: float
    metadata_index: int = None
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "score": self.score,
            "metadata_index": self.metadata_index,
            "metadata": self.metadata
        }

class IPLDVectorStore:
    """
    IPLD-based vector storage for embeddings.

    This class provides a vector store implementation that uses IPLD for
    content-addressed storage of embedding vectors. It supports efficient
    nearest-neighbor search for similarity queries and can be serialized
    to/from CAR files for portability.
    """

    def __init__(
        self,
        dimension: int = 768,
        metric: str = "cosine",
        storage: Optional[IPLDStorage] = None
    ):
        """
        Initialize vector store with dimension and similarity metric.

        Args:
            dimension: int - Dimensionality of vectors
            metric: str - Distance metric ('cosine', 'l2', 'ip')
            storage: Optional[IPLDStorage] - IPLD storage to use
        """
        self.dimension = dimension
        self.metric = metric
        self.storage = storage or IPLDStorage()

        # Initialize data structures
        self.vectors = []  # List of vectors
        self.vector_ids = []  # List of vector IDs (CIDs)
        self.metadata = []  # List of metadata dictionaries
        self.root_cid = None  # Root CID of the vector store

        # Metrics
        self.metrics = {
            "vectors_added": 0,
            "searches_performed": 0,
            "average_search_time": 0.0,
            "total_search_time": 0.0
        }

        # Initialize index if faiss is available
        self._index = None
        self._init_index()

    def _init_index(self):
        """Initialize the vector index based on the metric."""
        if not HAVE_FAISS:
            logging.warning("FAISS not available. Using numpy for vector search (slower).")
            return

        if self.metric == "cosine":
            # L2 normalized vectors with inner product is equivalent to cosine similarity
            self._index = faiss.IndexFlatIP(self.dimension)
        elif self.metric == "l2":
            self._index = faiss.IndexFlatL2(self.dimension)
        elif self.metric == "ip":
            self._index = faiss.IndexFlatIP(self.dimension)
        else:
            raise ValueError(f"Unsupported metric: {self.metric}. Use 'cosine', 'l2', or 'ip'.")

    def add_vectors(
        self,
        vectors: List[np.ndarray],
        metadata: Optional[List[Dict[str, Any]]] = None
    ) -> List[VectorID]:
        """
        Store vectors in IPLD format.

        Args:
            vectors: List[np.ndarray] - List of vectors to store
            metadata: List[dict] - Optional metadata for each vector

        Returns:
            List[str] - List of vector IDs (CIDs)
        """
        if not vectors:
            return []

        # Validate inputs
        if metadata and len(metadata) != len(vectors):
            raise ValueError("Metadata list length must match vectors list length")

        # Check vector dimensions
        for i, vec in enumerate(vectors):
            if len(vec) != self.dimension:
                raise ValueError(f"Vector {i} has dimension {len(vec)}, expected {self.dimension}")

        # Prepare metadata if not provided
        if metadata is None:
            metadata = [{} for _ in range(len(vectors))]

        # Process the vectors in batches for IPLD storage
        vector_ids = []

        # Store each vector as an IPLD block
        for i, (vector, meta) in enumerate(zip(vectors, metadata)):
            # Convert vector to float32 for consistency
            vector = vector.astype(np.float32)

            # Normalize if using cosine similarity
            if self.metric == "cosine":
                norm = np.linalg.norm(vector)
                if norm > 0:
                    vector = vector / norm

            # Serialize vector to bytes
            vector_bytes = vector.tobytes()

            # Create IPLD node with vector data and metadata
            vector_node = {
                "dimension": self.dimension,
                "metric": self.metric,
                "vector": vector_bytes,
                "metadata": meta
            }

            # Store the node
            vector_cid = self.storage.store(json.dumps(vector_node).encode())
            vector_ids.append(vector_cid)

            # Add to in-memory collections
            self.vectors.append(vector)
            self.vector_ids.append(vector_cid)
            self.metadata.append(meta)

        # Update the index if using FAISS
        if HAVE_FAISS and self._index is not None:
            vectors_array = np.array(vectors, dtype=np.float32)
            if self.metric == "cosine":
                # Normalize for cosine similarity
                faiss.normalize_L2(vectors_array)
            self._index.add(vectors_array)

        # Update metrics
        self.metrics["vectors_added"] += len(vectors)

        # Update the root CID
        self._update_root_cid()

        return vector_ids

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filter_fn: Optional[callable] = None
    ) -> List[SearchResult]:
        """
        Perform vector similarity search.

        Args:
            query_vector: np.ndarray - Query vector
            top_k: int - Number of results to return
            filter_fn: Optional[callable] - Function to filter results

        Returns:
            List[SearchResult] - Ranked search results
        """
        import time
        start_time = time.time()

        # Check if we have vectors to search
        if not self.vectors:
            return []

        # Convert query_vector to float32 and correct shape
        query_vector = np.array(query_vector, dtype=np.float32).reshape(1, -1)

        # Check dimensions
        if query_vector.shape[1] != self.dimension:
            raise ValueError(f"Query vector has dimension {query_vector.shape[1]}, expected {self.dimension}")

        # Normalize if using cosine similarity
        if self.metric == "cosine":
            norm = np.linalg.norm(query_vector)
            if norm > 0:
                query_vector = query_vector / norm

        # Perform search
        if HAVE_FAISS and self._index is not None:
            # Use FAISS for fast search
            scores, indices = self._index.search(query_vector, min(top_k * 2, len(self.vectors)))
            scores = scores[0]  # Flatten
            indices = indices[0]  # Flatten

            # Convert scores based on metric
            if self.metric == "l2":
                # Convert L2 distance to similarity score (higher is better)
                max_distance = max(scores) if scores.size > 0 else 1.0
                scores = 1.0 - (scores / max_distance)

            # Create search results
            results = []
            for score, idx in zip(scores, indices):
                # Skip if the score is NaN or below threshold
                if np.isnan(score):
                    continue

                # Get the vector ID and metadata
                vector_id = self.vector_ids[idx]
                metadata = self.metadata[idx]

                # Apply filter if provided
                if filter_fn and not filter_fn(metadata):
                    continue

                # Add to results
                results.append(SearchResult(
                    id=vector_id,
                    score=float(score),
                    metadata_index=idx,
                    metadata=metadata
                ))

                # Stop after reaching top_k valid results
                if len(results) >= top_k:
                    break
        else:
            # Fallback to numpy for search
            results = self._numpy_search(query_vector, top_k, filter_fn)

        # Update metrics
        elapsed = time.time() - start_time
        self.metrics["searches_performed"] += 1
        self.metrics["total_search_time"] += elapsed
        self.metrics["average_search_time"] = (
            self.metrics["total_search_time"] / self.metrics["searches_performed"]
        )

        return results

    def _numpy_search(
        self,
        query_vector: np.ndarray,
        top_k: int,
        filter_fn: Optional[callable]
    ) -> List[SearchResult]:
        """
        Perform search using numpy (fallback when FAISS is not available).

        Args:
            query_vector: np.ndarray - Query vector
            top_k: int - Number of results to return
            filter_fn: Optional[callable] - Function to filter results

        Returns:
            List[SearchResult] - Ranked search results
        """
        if not self.vectors:
            return []

        # Convert list of vectors to 2D array
        vectors_array = np.array(self.vectors, dtype=np.float32)

        # Calculate scores based on metric
        if self.metric == "cosine" or self.metric == "ip":
            # Compute dot product for cosine or inner product
            scores = np.dot(vectors_array, query_vector.reshape(-1))
        elif self.metric == "l2":
            # Compute L2 distances
            diff = vectors_array - query_vector
            distances = np.sqrt(np.sum(diff * diff, axis=1))
            # Convert to similarity scores (higher is better)
            max_distance = np.max(distances) if distances.size > 0 else 1.0
            scores = 1.0 - (distances / max_distance)
        else:
            raise ValueError(f"Unsupported metric: {self.metric}")

        # Filter results if necessary
        valid_indices = []
        for i in range(len(self.vectors)):
            if filter_fn and not filter_fn(self.metadata[i]):
                continue
            valid_indices.append(i)

        # If no valid indices, return empty results
        if not valid_indices:
            return []

        # Get scores for valid indices
        valid_scores = scores[valid_indices]

        # Sort by score (descending)
        sorted_indices = np.argsort(-valid_scores)

        # Get top_k results
        results = []
        for i in range(min(top_k, len(sorted_indices))):
            idx = valid_indices[sorted_indices[i]]
            score = float(scores[idx])

            # Skip if the score is NaN
            if np.isnan(score):
                continue

            # Create search result
            results.append(SearchResult(
                id=self.vector_ids[idx],
                score=score,
                metadata_index=idx,
                metadata=self.metadata[idx]
            ))

        return results

    def get_vector(self, vector_id: VectorID) -> Optional[np.ndarray]:
        """
        Get a vector by its ID.

        Args:
            vector_id: str - Vector ID

        Returns:
            Optional[np.ndarray] - The vector if found, None otherwise
        """
        try:
            idx = self.vector_ids.index(vector_id)
            return self.vectors[idx]
        except ValueError:
            return None

    def get_metadata(self, vector_id: VectorID) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a vector.

        Args:
            vector_id: str - Vector ID

        Returns:
            Optional[Dict[str, Any]] - The metadata if found, None otherwise
        """
        try:
            idx = self.vector_ids.index(vector_id)
            return self.metadata[idx]
        except ValueError:
            return None

    def update_metadata(
        self,
        vector_id: VectorID,
        metadata: Dict[str, Any]
    ) -> bool:
        """
        Update metadata for a vector.

        Args:
            vector_id: str - Vector ID
            metadata: Dict[str, Any] - New metadata

        Returns:
            bool - Success status
        """
        try:
            idx = self.vector_ids.index(vector_id)

            # Get the original vector node
            node_bytes = self.storage.get(vector_id)
            if not node_bytes:
                return False

            vector_node = json.loads(node_bytes.decode())

            # Update metadata
            vector_node["metadata"] = metadata

            # Store updated node
            updated_cid = self.storage.store(json.dumps(vector_node).encode())

            # Update in-memory collections if CID hasn't changed
            if updated_cid == vector_id:
                self.metadata[idx] = metadata
                return True

            # If CID changed, we need to update the vectors list
            self.vector_ids[idx] = updated_cid
            self.metadata[idx] = metadata

            # Update the root CID
            self._update_root_cid()

            return True
        except ValueError:
            return False

    def delete_vectors(self, vector_ids: List[VectorID]) -> bool:
        """
        Delete vectors from the store.

        Args:
            vector_ids: List[str] - Vector IDs to delete

        Returns:
            bool - Success status
        """
        if not vector_ids:
            return True

        # Convert to set for faster lookups
        vector_id_set = set(vector_ids)

        # Collect indices to remove (in reverse order)
        indices_to_remove = []
        for i, vid in enumerate(self.vector_ids):
            if vid in vector_id_set:
                indices_to_remove.append(i)

        # Sort in reverse order to remove from end first
        indices_to_remove.sort(reverse=True)

        # Remove vectors, IDs, and metadata
        for idx in indices_to_remove:
            del self.vectors[idx]
            del self.vector_ids[idx]
            del self.metadata[idx]

        # Rebuild the index if using FAISS
        if HAVE_FAISS and self._index is not None:
            self._index.reset()
            if self.vectors:
                vectors_array = np.array(self.vectors, dtype=np.float32)
                if self.metric == "cosine":
                    # Normalize for cosine similarity
                    faiss.normalize_L2(vectors_array)
                self._index.add(vectors_array)

        # Update the root CID
        self._update_root_cid()

        return True

    def _update_root_cid(self):
        """Update the root CID of the vector store."""
        # Create IPLD node with store metadata and vector IDs
        root_node = {
            "type": "vector_store",
            "dimension": self.dimension,
            "metric": self.metric,
            "count": len(self.vectors),
            "vector_ids": self.vector_ids
        }

        # Store the root node
        self.root_cid = self.storage.store(json.dumps(root_node).encode())

    def export_to_ipld(self) -> Tuple[VectorID, Dict[VectorID, bytes]]:
        """
        Export vector index as IPLD structure.

        Returns:
            tuple: (root_cid, {cid: block_data}) - Root CID and blocks
        """
        # Make sure the root CID is updated
        self._update_root_cid()

        # Collect all blocks
        blocks = {}

        # Add the root block
        root_block = self.storage.get(self.root_cid)
        if root_block:
            blocks[self.root_cid] = root_block

        # Add all vector blocks
        for vector_id in self.vector_ids:
            vector_block = self.storage.get(vector_id)
            if vector_block:
                blocks[vector_id] = vector_block

        return self.root_cid, blocks

    def export_to_car(self, output_path: str) -> VectorID:
        """
        Export vector index to CAR file.

        Args:
            output_path: str - Path to output CAR file

        Returns:
            str - Root CID of the exported index
        """
        if not HAVE_IPLD_CAR:
            raise ImportError("ipld_car module is required for CAR file export")

        # Export to IPLD
        root_cid, blocks = self.export_to_ipld()

        # Convert blocks to the format expected by ipld_car
        car_blocks = [(cid, data) for cid, data in blocks.items()]

        # Encode as CAR file
        car_data = ipld_car.encode([root_cid], car_blocks)

        # Write to file
        with open(output_path, "wb") as f:
            f.write(car_data)

        return root_cid

    @classmethod
    def from_cid(
        cls,
        cid: VectorID,
        storage: Optional[IPLDStorage] = None
    ) -> 'IPLDVectorStore':
        """
        Load vector store from IPFS by CID.

        Args:
            cid: str - Root CID of the vector store
            storage: Optional[IPLDStorage] - Storage to use

        Returns:
            IPLDVectorStore - Loaded vector store
        """
        # Initialize storage if not provided
        storage = storage or IPLDStorage()

        # Get the root node
        root_bytes = storage.get(cid)
        if not root_bytes:
            raise ValueError(f"Could not find root node with CID {cid}")

        root_node = json.loads(root_bytes.decode())

        # Check if it's a vector store
        if root_node.get("type") != "vector_store":
            raise ValueError(f"Node with CID {cid} is not a vector store")

        # Create a new vector store
        vector_store = cls(
            dimension=root_node.get("dimension", 768),
            metric=root_node.get("metric", "cosine"),
            storage=storage
        )

        # Set the root CID
        vector_store.root_cid = cid

        # Load vector IDs
        vector_ids = root_node.get("vector_ids", [])

        # Load vectors and metadata
        for vector_id in vector_ids:
            vector_bytes = storage.get(vector_id)
            if not vector_bytes:
                logging.warning(f"Could not find vector with CID {vector_id}")
                continue

            vector_node = json.loads(vector_bytes.decode())

            # Get vector data
            vector_data = vector_node.get("vector")
            if not vector_data:
                logging.warning(f"Vector with CID {vector_id} has no data")
                continue

            # Decode base64 if necessary
            if isinstance(vector_data, str):
                import base64
                vector_data = base64.b64decode(vector_data)

            # Convert to numpy array
            vector = np.frombuffer(vector_data, dtype=np.float32)

            # Get metadata
            metadata = vector_node.get("metadata", {})

            # Add to in-memory collections
            vector_store.vectors.append(vector)
            vector_store.vector_ids.append(vector_id)
            vector_store.metadata.append(metadata)

        # Rebuild the index if using FAISS
        if HAVE_FAISS and vector_store._index is not None and vector_store.vectors:
            vectors_array = np.array(vector_store.vectors, dtype=np.float32)
            if vector_store.metric == "cosine":
                # Normalize for cosine similarity
                faiss.normalize_L2(vectors_array)
            vector_store._index.add(vectors_array)

        return vector_store

    @classmethod
    def from_car(
        cls,
        car_path: str,
        storage: Optional[IPLDStorage] = None
    ) -> 'IPLDVectorStore':
        """
        Load vector store from CAR file.

        Args:
            car_path: str - Path to CAR file
            storage: Optional[IPLDStorage] - Storage to use

        Returns:
            IPLDVectorStore - Loaded vector store
        """
        if not HAVE_IPLD_CAR:
            raise ImportError("ipld_car module is required for CAR file import")

        # Initialize storage if not provided
        storage = storage or IPLDStorage()

        # Read CAR file
        with open(car_path, "rb") as f:
            car_data = f.read()

        # Decode CAR file
        roots, blocks = ipld_car.decode(car_data)
        if not roots:
            raise ValueError("CAR file has no roots")

        root_cid = roots[0]

        # Import blocks into storage
        for cid, block_data in blocks.items():
            storage.put(cid, block_data)

        # Load vector store from root CID
        return cls.from_cid(root_cid, storage)

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get vector store metrics.

        Returns:
            Dict[str, Any] - Dictionary of metrics
        """
        # Add current vector count
        self.metrics["vector_count"] = len(self.vectors)

        return self.metrics

    def __len__(self) -> int:
        """Get the number of vectors in the store."""
        return len(self.vectors)

    def __str__(self) -> str:
        """Get a string representation of the vector store."""
        return f"IPLDVectorStore(dimension={self.dimension}, metric={self.metric}, vectors={len(self.vectors)})"
