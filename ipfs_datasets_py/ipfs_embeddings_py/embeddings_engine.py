"""
Enhanced IPFS Embeddings Engine
Advanced embeddings search engine with comprehensive MCP integration
"""

import os
import sys
import json
import random
import asyncio
import logging
import time
import numpy as np
from typing import Dict, List, Optional, Union, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from aiohttp import ClientSession, ClientTimeout
import multiprocessing

# Core ML and embeddings
try:
    import torch
    import transformers
    from transformers import AutoTokenizer, AutoModel
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    import datasets
    from datasets import Dataset, load_dataset
    DATASETS_AVAILABLE = True
except ImportError:
    DATASETS_AVAILABLE = False

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

# Local imports
from .ipfs_multiformats import ipfs_multiformats_py
from .ipfs_only_hash import ipfs_only_hash_py

logger = logging.getLogger(__name__)

@dataclass
class EmbeddingConfig:
    """Configuration for embedding operations"""
    model_name: str = "thenlper/gte-small"
    batch_size: int = 32
    max_length: int = 512
    device: str = "cpu"
    endpoint_type: str = "local"  # local, tei, openvino, libp2p
    endpoint_url: Optional[str] = None

@dataclass
class ChunkingConfig:
    """Configuration for text chunking"""
    chunk_size: int = 512
    chunk_overlap: int = 50
    method: str = "fixed"  # fixed, semantic, sliding_window
    n_sentences: int = 8
    step_size: int = 256

class AdvancedIPFSEmbeddings:
    """
    Advanced IPFS embeddings engine with multi-backend support and MCP integration
    """
    
    def __init__(self, resources: Dict[str, Any], metadata: Dict[str, Any]):
        """Initialize the embeddings engine"""
        self.resources = resources
        self.metadata = metadata
        
        # Core components
        self.multiformats = ipfs_multiformats_py(resources, metadata)
        self.ipfs_only_hash = ipfs_only_hash_py(resources, metadata)
        
        # Endpoint management
        self.tei_endpoints = {}
        self.openvino_endpoints = {}
        self.libp2p_endpoints = {}
        self.local_endpoints = {}
        self.endpoint_status = {}
        
        # Data structures
        self.index = {}
        self.caches = {}
        self.queues = {}
        self.batch_sizes = {}
        self.tokenizer = {}
        
        # Processing state
        self.cid_set = set()
        self.cid_list = []
        self.all_cid_list = {}
        self.all_cid_set = {}
        
        # Initialize endpoints from resources
        self._initialize_endpoints()
        
    def _initialize_endpoints(self):
        """Initialize endpoints from resource configuration"""
        if "tei_endpoints" in self.resources:
            for endpoint_info in self.resources["tei_endpoints"]:
                model, endpoint, context_length = endpoint_info
                self.add_tei_endpoint(model, endpoint, context_length)
                
        if "openvino_endpoints" in self.resources:
            for endpoint_info in self.resources["openvino_endpoints"]:
                model, endpoint, context_length = endpoint_info
                self.add_openvino_endpoint(model, endpoint, context_length)
                
        if "libp2p_endpoints" in self.resources:
            for endpoint_info in self.resources["libp2p_endpoints"]:
                model, endpoint, context_length = endpoint_info
                self.add_libp2p_endpoint(model, endpoint, context_length)
                
        if "local_endpoints" in self.resources:
            for endpoint_info in self.resources["local_endpoints"]:
                model, device, context_length = endpoint_info
                self.add_local_endpoint(model, device, context_length)

    # Endpoint management methods
    def add_tei_endpoint(self, model: str, endpoint: str, context_length: int):
        """Add a TEI (Text Embeddings Inference) endpoint"""
        if model not in self.tei_endpoints:
            self.tei_endpoints[model] = {}
        self.tei_endpoints[model][endpoint] = context_length
        self.endpoint_status[endpoint] = 1  # Active
        
    def add_openvino_endpoint(self, model: str, endpoint: str, context_length: int):
        """Add an OpenVINO endpoint"""
        if model not in self.openvino_endpoints:
            self.openvino_endpoints[model] = {}
        self.openvino_endpoints[model][endpoint] = context_length
        self.endpoint_status[endpoint] = 1
        
    def add_libp2p_endpoint(self, model: str, endpoint: str, context_length: int):
        """Add a LibP2P endpoint"""
        if model not in self.libp2p_endpoints:
            self.libp2p_endpoints[model] = {}
        self.libp2p_endpoints[model][endpoint] = context_length
        self.endpoint_status[endpoint] = 1
        
    def add_local_endpoint(self, model: str, device: str, context_length: int):
        """Add a local endpoint"""
        if model not in self.local_endpoints:
            self.local_endpoints[model] = {}
        self.local_endpoints[model][device] = context_length
        self.endpoint_status[device] = 1

    def get_endpoints(self, model: str, endpoint_type: Optional[str] = None) -> List[str]:
        """Get available endpoints for a model"""
        if endpoint_type == "tei":
            endpoints_dict = self.tei_endpoints.get(model, {})
        elif endpoint_type == "openvino":
            endpoints_dict = self.openvino_endpoints.get(model, {})
        elif endpoint_type == "libp2p":
            endpoints_dict = self.libp2p_endpoints.get(model, {})
        elif endpoint_type == "local":
            endpoints_dict = self.local_endpoints.get(model, {})
        else:
            # Return all endpoints
            all_endpoints = {}
            all_endpoints.update(self.tei_endpoints.get(model, {}))
            all_endpoints.update(self.openvino_endpoints.get(model, {}))
            all_endpoints.update(self.libp2p_endpoints.get(model, {}))
            all_endpoints.update(self.local_endpoints.get(model, {}))
            endpoints_dict = all_endpoints
            
        # Filter by endpoint status
        filtered_endpoints = [
            endpoint for endpoint in endpoints_dict 
            if self.endpoint_status.get(endpoint, 0) >= 1
        ]
        return filtered_endpoints

    async def test_endpoint(self, endpoint: str, model: str) -> bool:
        """Test if an endpoint is responsive"""
        try:
            if endpoint.startswith("http"):
                # Test HTTP endpoint
                async with ClientSession() as session:
                    test_data = {"inputs": "test"}
                    async with session.post(
                        endpoint, 
                        json=test_data,
                        timeout=ClientTimeout(total=10)
                    ) as response:
                        if response.status == 200:
                            self.endpoint_status[endpoint] = 1
                            return True
                        else:
                            self.endpoint_status[endpoint] = 0
                            return False
            else:
                # Test local endpoint (device)
                if TORCH_AVAILABLE and torch.cuda.is_available() and "cuda" in endpoint:
                    self.endpoint_status[endpoint] = 1
                    return True
                elif endpoint == "cpu":
                    self.endpoint_status[endpoint] = 1
                    return True
                else:
                    self.endpoint_status[endpoint] = 0
                    return False
        except Exception as e:
            logger.warning(f"Endpoint {endpoint} test failed: {e}")
            self.endpoint_status[endpoint] = 0
            return False

    async def generate_embeddings(
        self, 
        texts: List[str], 
        model: str, 
        endpoint: Optional[str] = None
    ) -> np.ndarray:
        """Generate embeddings for a list of texts"""
        if not texts:
            return np.array([])
            
        # Select endpoint if not specified
        if endpoint is None:
            endpoints = self.get_endpoints(model)
            if not endpoints:
                raise ValueError(f"No available endpoints for model {model}")
            endpoint = random.choice(endpoints)
            
        # Generate embeddings based on endpoint type
        if endpoint.startswith("http"):
            return await self._generate_http_embeddings(texts, endpoint)
        else:
            return await self._generate_local_embeddings(texts, model, endpoint)

    async def _generate_http_embeddings(
        self, 
        texts: List[str], 
        endpoint: str
    ) -> np.ndarray:
        """Generate embeddings using HTTP endpoint"""
        async with ClientSession() as session:
            data = {"inputs": texts}
            async with session.post(endpoint, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return np.array(result)
                else:
                    raise RuntimeError(f"HTTP embedding request failed: {response.status}")

    async def _generate_local_embeddings(
        self, 
        texts: List[str], 
        model: str, 
        device: str
    ) -> np.ndarray:
        """Generate embeddings using local model"""
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch not available for local embeddings")
            
        # Initialize tokenizer and model if needed
        if model not in self.tokenizer:
            self.tokenizer[model] = {}
            
        if device not in self.tokenizer[model]:
            tokenizer = AutoTokenizer.from_pretrained(model)
            model_obj = AutoModel.from_pretrained(model)
            
            if device != "cpu" and torch.cuda.is_available():
                model_obj = model_obj.to(device)
                
            self.tokenizer[model][device] = {
                "tokenizer": tokenizer,
                "model": model_obj
            }
            
        components = self.tokenizer[model][device]
        tokenizer = components["tokenizer"]
        model_obj = components["model"]
        
        # Tokenize and generate embeddings
        inputs = tokenizer(
            texts, 
            padding=True, 
            truncation=True, 
            return_tensors="pt",
            max_length=512
        )
        
        if device != "cpu" and torch.cuda.is_available():
            inputs = {k: v.to(device) for k, v in inputs.items()}
            
        with torch.no_grad():
            outputs = model_obj(**inputs)
            # Use mean pooling
            embeddings = outputs.last_hidden_state.mean(dim=1)
            
        return embeddings.cpu().numpy()

    def chunk_text(
        self, 
        text: str, 
        config: ChunkingConfig
    ) -> List[Tuple[int, int]]:
        """Chunk text using specified strategy"""
        if not DATASETS_AVAILABLE:
            # Simple fixed chunking fallback
            chunks = []
            for i in range(0, len(text), config.chunk_size):
                chunks.append((i, min(i + config.chunk_size, len(text))))
            return chunks
            
        # Use tokenizer for better chunking
        try:
            # Simple implementation - can be enhanced with proper chunker
            words = text.split()
            chunks = []
            
            if config.method == "fixed":
                chunk_size_words = config.chunk_size // 4  # Rough word estimate
                for i in range(0, len(words), chunk_size_words):
                    start_char = len(" ".join(words[:i]))
                    end_char = len(" ".join(words[:i + chunk_size_words]))
                    chunks.append((start_char, min(end_char, len(text))))
                    
            elif config.method == "sliding_window":
                chunk_size_words = config.chunk_size // 4
                step_size_words = config.step_size // 4
                for i in range(0, len(words), step_size_words):
                    start_char = len(" ".join(words[:i]))
                    end_char = len(" ".join(words[:i + chunk_size_words]))
                    if end_char <= len(text):
                        chunks.append((start_char, end_char))
                        
            return chunks
            
        except Exception as e:
            logger.warning(f"Chunking failed, using simple split: {e}")
            # Fallback to character-based chunking
            chunks = []
            for i in range(0, len(text), config.chunk_size):
                chunks.append((i, min(i + config.chunk_size, len(text))))
            return chunks

    async def index_dataset(
        self, 
        dataset_name: str, 
        split: Optional[str] = None,
        column: str = "text",
        dst_path: str = "./embeddings_cache",
        models: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Index a dataset with embeddings"""
        if not DATASETS_AVAILABLE:
            raise RuntimeError("datasets library not available")
            
        if models is None:
            models = list(self.tei_endpoints.keys()) or list(self.local_endpoints.keys())
            
        if not models:
            raise ValueError("No models specified or available")
            
        # Create output directory
        os.makedirs(dst_path, exist_ok=True)
        
        # Load dataset
        if split is None:
            dataset = load_dataset(dataset_name, streaming=True)
        else:
            dataset = load_dataset(dataset_name, split=split, streaming=True)
            
        # Process dataset
        results = {}
        for model in models:
            model_results = await self._process_dataset_for_model(
                dataset, model, column, dst_path
            )
            results[model] = model_results
            
        return results

    async def _process_dataset_for_model(
        self,
        dataset,
        model: str,
        column: str,
        dst_path: str
    ) -> Dict[str, Any]:
        """Process dataset for a specific model"""
        processed_count = 0
        embeddings_list = []
        texts_list = []
        
        batch_texts = []
        batch_size = 32
        
        try:
            for item in dataset:
                if column in item:
                    text = item[column]
                    batch_texts.append(text)
                    
                    if len(batch_texts) >= batch_size:
                        # Process batch
                        embeddings = await self.generate_embeddings(
                            batch_texts, model
                        )
                        embeddings_list.extend(embeddings)
                        texts_list.extend(batch_texts)
                        
                        processed_count += len(batch_texts)
                        batch_texts = []
                        
                        # Log progress
                        if processed_count % 1000 == 0:
                            logger.info(f"Processed {processed_count} items for {model}")
                            
                # Process remaining items
                if processed_count >= 10000:  # Limit for demo
                    break
                    
            # Process remaining batch
            if batch_texts:
                embeddings = await self.generate_embeddings(batch_texts, model)
                embeddings_list.extend(embeddings)
                texts_list.extend(batch_texts)
                processed_count += len(batch_texts)
                
            # Save results
            output_file = os.path.join(
                dst_path, 
                f"{model.replace('/', '_')}_embeddings.npz"
            )
            
            np.savez_compressed(
                output_file,
                embeddings=np.array(embeddings_list),
                texts=texts_list
            )
            
            return {
                "status": "success",
                "processed_count": processed_count,
                "output_file": output_file,
                "embedding_dim": len(embeddings_list[0]) if embeddings_list else 0
            }
            
        except Exception as e:
            logger.error(f"Error processing dataset for {model}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "processed_count": processed_count
            }

    async def search_similar(
        self,
        query: str,
        model: str,
        top_k: int = 10,
        index_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar texts using embeddings"""
        if not index_path:
            raise ValueError("Index path required for similarity search")
            
        try:
            # Load index
            data = np.load(index_path)
            embeddings = data['embeddings']
            texts = data['texts']
            
            # Generate query embedding
            query_embedding = await self.generate_embeddings([query], model)
            query_embedding = query_embedding[0]
            
            # Calculate similarities
            similarities = np.dot(embeddings, query_embedding) / (
                np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query_embedding)
            )
            
            # Get top results
            top_indices = np.argsort(similarities)[-top_k:][::-1]
            
            results = []
            for idx in top_indices:
                results.append({
                    "text": texts[idx],
                    "similarity": float(similarities[idx]),
                    "index": int(idx)
                })
                
            return results
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def get_status(self) -> Dict[str, Any]:
        """Get current status of the embeddings engine"""
        return {
            "tei_endpoints": len(self.tei_endpoints),
            "openvino_endpoints": len(self.openvino_endpoints),
            "libp2p_endpoints": len(self.libp2p_endpoints),
            "local_endpoints": len(self.local_endpoints),
            "active_endpoints": sum(1 for status in self.endpoint_status.values() if status >= 1),
            "torch_available": TORCH_AVAILABLE,
            "datasets_available": DATASETS_AVAILABLE,
            "faiss_available": FAISS_AVAILABLE,
            "cached_models": list(self.tokenizer.keys())
        }


# Backward compatibility alias
ipfs_embeddings_py = AdvancedIPFSEmbeddings
