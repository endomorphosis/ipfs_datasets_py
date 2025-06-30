"""
IPFS Embeddings Core Module

Migrated from endomorphosis/ipfs_embeddings_py
Provides advanced embedding generation, vector search, and IPFS integration capabilities.
"""

import os
import sys
import json
import asyncio
import time
import gc
import logging
from typing import List, Dict, Optional, Union, Tuple, Any
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import torch
import psutil
from datasets import Dataset

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import vector store modules
try:
    from ..vector_stores.qdrant import QdrantVectorStore
except ImportError:
    QdrantVectorStore = None

try:
    from ..vector_stores.elasticsearch import ElasticsearchVectorStore
except ImportError:
    ElasticsearchVectorStore = None

try:
    from ..vector_stores.faiss import FaissVectorStore
except ImportError:
    FaissVectorStore = None


@dataclass
class PerformanceMetrics:
    """Performance metrics for batch processing optimization"""
    batch_size: int
    processing_time: float
    memory_usage_mb: float
    throughput: float  # items per second
    success_rate: float
    timestamp: Optional[float] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class MemoryMonitor:
    """Monitor system memory usage for adaptive batch sizing"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__ + ".MemoryMonitor")
    
    def get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB"""
        try:
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except Exception as e:
            self.logger.warning(f"Failed to get memory usage: {e}")
            return 0.0
    
    def get_available_memory_mb(self) -> float:
        """Get available system memory in MB"""
        try:
            return psutil.virtual_memory().available / 1024 / 1024
        except Exception as e:
            self.logger.warning(f"Failed to get available memory: {e}")
            return 1024.0  # Default fallback
    
    def get_memory_percent(self) -> float:
        """Get memory usage percentage"""
        try:
            return psutil.virtual_memory().percent
        except Exception as e:
            self.logger.warning(f"Failed to get memory percentage: {e}")
            return 0.0


class AdaptiveBatchProcessor:
    """Intelligent batch size optimization based on performance metrics and memory usage"""
    
    def __init__(self, max_memory_percent: float = 80.0, min_batch_size: int = 1, max_batch_size: int = 512):
        self.max_memory_percent = max_memory_percent
        self.min_batch_size = min_batch_size
        self.max_batch_size = max_batch_size
        self.optimal_batch_sizes: Dict[str, int] = {}
        self.performance_history: Dict[str, List[PerformanceMetrics]] = {}
        self.memory_monitor = MemoryMonitor()
        self.logger = logging.getLogger(__name__ + ".AdaptiveBatchProcessor")
    
    def get_memory_aware_batch_size(self) -> int:
        """Calculate batch size based on available memory"""
        try:
            available_mb = self.memory_monitor.get_available_memory_mb()
            memory_percent = self.memory_monitor.get_memory_percent()
            
            if memory_percent > 85:
                return max(self.min_batch_size, self.max_batch_size // 8)
            elif memory_percent > 70:
                return max(self.min_batch_size, self.max_batch_size // 4)
            elif memory_percent > 50:
                return max(self.min_batch_size, self.max_batch_size // 2)
            else:
                return self.max_batch_size
                
        except Exception as e:
            self.logger.warning(f"Error calculating memory-aware batch size: {e}")
            return self.min_batch_size * 4


@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation"""
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    batch_size: int = 32
    max_length: int = 512
    device: str = "auto"
    normalize_embeddings: bool = True
    show_progress_bar: bool = True


class IPFSEmbeddings:
    """
    Core IPFS Embeddings class providing advanced embedding generation,
    vector search, and IPFS integration capabilities.
    
    Migrated from endomorphosis/ipfs_embeddings_py with enhancements for
    integration with ipfs_datasets_py.
    """
    
    def __init__(self, resources: Dict[str, Any], metadata: Dict[str, Any]):
        """
        Initialize IPFS Embeddings system
        
        Args:
            resources: Dictionary containing endpoint configurations
            metadata: Dictionary containing metadata configuration
        """
        self.resources = resources
        self.metadata = metadata
        self.logger = logging.getLogger(__name__ + ".IPFSEmbeddings")
        
        # Initialize performance monitoring
        self.adaptive_batch_processor = AdaptiveBatchProcessor(
            max_memory_percent=80.0,
            min_batch_size=1,
            max_batch_size=512
        )
        self.memory_monitor = self.adaptive_batch_processor.memory_monitor
        
        # Initialize endpoints
        self.endpoint_types = ["tei_endpoints", "openvino_endpoints", "libp2p_endpoints", "local_endpoints"]
        self.tei_endpoints = {}
        self.openvino_endpoints = {}
        self.libp2p_endpoints = {}
        self.local_endpoints = {}
        self.endpoint_status = {}
        
        # Initialize vector stores
        self._initialize_vector_stores()
        
        # Initialize state tracking
        self.index = {}
        self.schemas = {}
        self.queues = {}
        self.caches = {}
        self.batch_sizes = {}
        self.processing_errors = {}
        
        # Parse resources configuration
        self._parse_resources()
        
        self.logger.info("IPFS Embeddings system initialized successfully")
    
    def _initialize_vector_stores(self):
        """Initialize available vector store backends"""
        self.vector_stores = {}
        
        if QdrantVectorStore:
            try:
                self.vector_stores['qdrant'] = QdrantVectorStore(self.resources, self.metadata)
                self.logger.info("Qdrant vector store initialized")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Qdrant: {e}")
        
        if ElasticsearchVectorStore:
            try:
                self.vector_stores['elasticsearch'] = ElasticsearchVectorStore(self.resources, self.metadata)
                self.logger.info("Elasticsearch vector store initialized")
            except Exception as e:
                self.logger.warning(f"Failed to initialize Elasticsearch: {e}")
        
        if FaissVectorStore:
            try:
                self.vector_stores['faiss'] = FaissVectorStore(self.resources, self.metadata)
                self.logger.info("FAISS vector store initialized")
            except Exception as e:
                self.logger.warning(f"Failed to initialize FAISS: {e}")
    
    def _parse_resources(self):
        """Parse and validate resources configuration"""
        try:
            # Parse local endpoints
            if "local_endpoints" in self.resources:
                for endpoint_config in self.resources["local_endpoints"]:
                    if len(endpoint_config) >= 3:
                        model, device, ctx_length = endpoint_config[:3]
                        self.add_local_endpoint(model, device, ctx_length)
            
            # Parse TEI endpoints
            if "tei_endpoints" in self.resources:
                for endpoint_config in self.resources["tei_endpoints"]:
                    if len(endpoint_config) >= 3:
                        model, endpoint, ctx_length = endpoint_config[:3]
                        self.add_tei_endpoint(model, endpoint, ctx_length)
            
            # Parse OpenVINO endpoints
            if "openvino_endpoints" in self.resources:
                for endpoint_config in self.resources["openvino_endpoints"]:
                    if len(endpoint_config) >= 3:
                        model, endpoint, ctx_length = endpoint_config[:3]
                        self.add_openvino_endpoint(model, endpoint, ctx_length)
                        
        except Exception as e:
            self.logger.error(f"Error parsing resources configuration: {e}")
    
    def add_local_endpoint(self, model: str, device: str, ctx_length: int):
        """Add local endpoint to the system"""
        if model not in self.local_endpoints:
            self.local_endpoints[model] = {}
        self.local_endpoints[model][device] = ctx_length
        self.endpoint_status[f"{model}:{device}"] = ctx_length
        self.logger.info(f"Added local endpoint: {model} on {device} with context length {ctx_length}")
    
    def add_tei_endpoint(self, model: str, endpoint: str, ctx_length: int):
        """Add TEI endpoint to the system"""
        if model not in self.tei_endpoints:
            self.tei_endpoints[model] = {}
        self.tei_endpoints[model][endpoint] = ctx_length
        self.endpoint_status[endpoint] = ctx_length
        self.logger.info(f"Added TEI endpoint: {model} at {endpoint} with context length {ctx_length}")
    
    def add_openvino_endpoint(self, model: str, endpoint: str, ctx_length: int):
        """Add OpenVINO endpoint to the system"""
        if model not in self.openvino_endpoints:
            self.openvino_endpoints[model] = {}
        self.openvino_endpoints[model][endpoint] = ctx_length
        self.endpoint_status[endpoint] = ctx_length
        self.logger.info(f"Added OpenVINO endpoint: {model} at {endpoint} with context length {ctx_length}")
    
    async def generate_embeddings(self, 
                                texts: List[str], 
                                config: Optional[EmbeddingConfig] = None) -> np.ndarray:
        """
        Generate embeddings for a list of texts using optimal batching
        
        Args:
            texts: List of texts to embed
            config: Embedding configuration
            
        Returns:
            NumPy array of embeddings
        """
        if config is None:
            config = EmbeddingConfig()
        
        try:
            # Determine optimal batch size
            batch_size = self.adaptive_batch_processor.get_memory_aware_batch_size()
            batch_size = min(batch_size, config.batch_size)
            
            embeddings = []
            total_batches = (len(texts) + batch_size - 1) // batch_size
            
            self.logger.info(f"Generating embeddings for {len(texts)} texts in {total_batches} batches")
            
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                batch_embeddings = await self._generate_batch_embeddings(batch_texts, config)
                embeddings.extend(batch_embeddings)
                
                # Memory cleanup
                if i % (batch_size * 10) == 0:
                    self._force_garbage_collection()
            
            return np.array(embeddings)
            
        except Exception as e:
            self.logger.error(f"Error generating embeddings: {e}")
            raise
    
    async def _generate_batch_embeddings(self, texts: List[str], config: EmbeddingConfig) -> List[np.ndarray]:
        """Generate embeddings for a batch of texts"""
        try:
            # For now, use a simple implementation
            # This would be replaced with actual embedding model inference
            embeddings = []
            for text in texts:
                # Placeholder embedding generation
                embedding = np.random.randn(384).astype(np.float32)
                if config.normalize_embeddings:
                    embedding = embedding / np.linalg.norm(embedding)
                embeddings.append(embedding)
            
            return embeddings
            
        except Exception as e:
            self.logger.error(f"Error in batch embedding generation: {e}")
            raise
    
    def _force_garbage_collection(self):
        """Force garbage collection to free memory"""
        try:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            self.logger.warning(f"Memory cleanup failed: {e}")
    
    async def search_similar(self, 
                           query_embedding: np.ndarray, 
                           top_k: int = 10,
                           vector_store: str = "qdrant") -> List[Dict[str, Any]]:
        """
        Search for similar embeddings in the specified vector store
        
        Args:
            query_embedding: Query embedding vector
            top_k: Number of results to return
            vector_store: Vector store backend to use
            
        Returns:
            List of similar results with scores and metadata
        """
        if vector_store not in self.vector_stores:
            raise ValueError(f"Vector store '{vector_store}' not available")
        
        try:
            results = await self.vector_stores[vector_store].search(
                query_embedding, top_k=top_k
            )
            return results
            
        except Exception as e:
            self.logger.error(f"Error searching similar embeddings: {e}")
            raise
    
    async def store_embeddings(self, 
                             embeddings: np.ndarray, 
                             metadata: List[Dict[str, Any]], 
                             vector_store: str = "qdrant") -> bool:
        """
        Store embeddings in the specified vector store
        
        Args:
            embeddings: Array of embeddings to store
            metadata: List of metadata dictionaries for each embedding
            vector_store: Vector store backend to use
            
        Returns:
            Success status
        """
        if vector_store not in self.vector_stores:
            raise ValueError(f"Vector store '{vector_store}' not available")
        
        try:
            success = await self.vector_stores[vector_store].store(embeddings, metadata)
            return success
            
        except Exception as e:
            self.logger.error(f"Error storing embeddings: {e}")
            raise
    
    def get_status(self) -> Dict[str, Any]:
        """Get system status and metrics"""
        return {
            "endpoints": {
                "local": len(self.local_endpoints),
                "tei": len(self.tei_endpoints),
                "openvino": len(self.openvino_endpoints)
            },
            "vector_stores": list(self.vector_stores.keys()),
            "memory_usage_percent": self.memory_monitor.get_memory_percent(),
            "memory_usage_mb": self.memory_monitor.get_memory_usage_mb(),
            "available_memory_mb": self.memory_monitor.get_available_memory_mb()
        }


# Backwards compatibility function
def ipfs_embeddings_py(resources: Dict[str, Any], metadata: Dict[str, Any]) -> IPFSEmbeddings:
    """
    Create an IPFSEmbeddings instance (backwards compatibility)
    
    Args:
        resources: Dictionary containing endpoint configurations
        metadata: Dictionary containing metadata configuration
        
    Returns:
        IPFSEmbeddings instance
    """
    return IPFSEmbeddings(resources, metadata)
