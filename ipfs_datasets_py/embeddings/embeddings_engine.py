"""Enhanced IPFS embeddings engine.

Refactored into `ipfs_datasets_py.embeddings`.
Uses `ipfs_datasets_py.embeddings_router` for local / ipfs_accelerate_py-backed embeddings.
"""

import os
import json
import random
import anyio
import logging
import time
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from aiohttp import ClientSession, ClientTimeout

try:
    import torch
    from transformers import AutoTokenizer, AutoModel

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from ipfs_datasets_py.embeddings_router import get_accelerate_manager as _get_accelerate_manager
except Exception:  # pragma: no cover
    _get_accelerate_manager = None

try:
    import datasets
    from datasets import load_dataset

    DATASETS_AVAILABLE = True
except ImportError:
    DATASETS_AVAILABLE = False

try:
    import faiss

    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

try:
    from ipfs_datasets_py.embeddings_router import embed_texts
except Exception:  # pragma: no cover
    embed_texts = None

from .ipfs_multiformats import ipfs_multiformats_py
from .ipfs_only_hash import ipfs_only_hash_py


logger = logging.getLogger(__name__)


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _use_embedding_router() -> bool:
    # Default to using router when available. Allow opt-out.
    return not _truthy(os.getenv("IPFS_DATASETS_PY_DISABLE_EMBEDDINGS_ROUTER"))


def _lazy_router_embed_texts():
    try:
        from ipfs_datasets_py.embeddings_router import embed_texts as router_embed_texts

        return router_embed_texts
    except Exception:
        return None


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
    """Advanced embeddings engine with multi-backend support.

    For local embeddings, prefers the shared `embeddings_router` so callers can
    switch between local adapter and ipfs_accelerate_py without changing code.
    """

    def __init__(self, resources: Dict[str, Any], metadata: Dict[str, Any], use_accelerate: bool = True):
        self.resources = resources
        self.metadata = metadata

        self.multiformats = ipfs_multiformats_py(resources, metadata)
        self.ipfs_only_hash = ipfs_only_hash_py(resources, metadata)

        self.tei_endpoints = {}
        self.openvino_endpoints = {}
        self.libp2p_endpoints = {}
        self.local_endpoints = {}
        self.endpoint_status = {}

        self.index = {}
        self.caches = {}
        self.queues = {}
        self.batch_sizes = {}
        self.tokenizer = {}

        self.cid_set = set()
        self.cid_list = []
        self.all_cid_list = {}
        self.all_cid_set = {}

        self.accelerate_manager = None
        if use_accelerate and callable(_get_accelerate_manager):
            try:
                self.accelerate_manager = _get_accelerate_manager(
                    purpose="embeddings_engine",
                    enable_distributed=True,
                    resources=resources,
                )
                if self.accelerate_manager is not None:
                    logger.info("✓ Accelerate integration enabled for embeddings engine")
                else:
                    logger.info("⚠ Accelerate integration not available, using router/local/endpoint inference")
            except Exception as e:
                logger.warning(f"⚠ Failed to initialize accelerate manager: {e}")
                self.accelerate_manager = None
        else:
            logger.info("⚠ Accelerate integration not available, using router/local/endpoint inference")

        self._initialize_endpoints()

    def _initialize_endpoints(self):
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

    def add_tei_endpoint(self, model: str, endpoint: str, context_length: int):
        if model not in self.tei_endpoints:
            self.tei_endpoints[model] = {}
        self.tei_endpoints[model][endpoint] = context_length
        self.endpoint_status[endpoint] = 1

    def add_openvino_endpoint(self, model: str, endpoint: str, context_length: int):
        if model not in self.openvino_endpoints:
            self.openvino_endpoints[model] = {}
        self.openvino_endpoints[model][endpoint] = context_length
        self.endpoint_status[endpoint] = 1

    def add_libp2p_endpoint(self, model: str, endpoint: str, context_length: int):
        if model not in self.libp2p_endpoints:
            self.libp2p_endpoints[model] = {}
        self.libp2p_endpoints[model][endpoint] = context_length
        self.endpoint_status[endpoint] = 1

    def add_local_endpoint(self, model: str, device: str, context_length: int):
        if model not in self.local_endpoints:
            self.local_endpoints[model] = {}
        self.local_endpoints[model][device] = context_length
        self.endpoint_status[device] = 1

    def get_endpoints(self, model: str, endpoint_type: Optional[str] = None) -> List[str]:
        if endpoint_type == "tei":
            endpoints_dict = self.tei_endpoints.get(model, {})
        elif endpoint_type == "openvino":
            endpoints_dict = self.openvino_endpoints.get(model, {})
        elif endpoint_type == "libp2p":
            endpoints_dict = self.libp2p_endpoints.get(model, {})
        elif endpoint_type == "local":
            endpoints_dict = self.local_endpoints.get(model, {})
        else:
            all_endpoints = {}
            all_endpoints.update(self.tei_endpoints.get(model, {}))
            all_endpoints.update(self.openvino_endpoints.get(model, {}))
            all_endpoints.update(self.libp2p_endpoints.get(model, {}))
            all_endpoints.update(self.local_endpoints.get(model, {}))
            endpoints_dict = all_endpoints

        return [endpoint for endpoint in endpoints_dict if self.endpoint_status.get(endpoint, 0) >= 1]

    async def test_endpoint(self, endpoint: str, model: str) -> bool:
        try:
            if endpoint.startswith("http"):
                async with ClientSession() as session:
                    test_data = {"inputs": "test"}
                    async with session.post(endpoint, json=test_data, timeout=ClientTimeout(total=10)) as response:
                        ok = response.status == 200
                        self.endpoint_status[endpoint] = 1 if ok else 0
                        return ok

            # Local endpoint (device)
            if endpoint == "cpu":
                self.endpoint_status[endpoint] = 1
                return True
            if TORCH_AVAILABLE and torch.cuda.is_available() and "cuda" in endpoint:
                self.endpoint_status[endpoint] = 1
                return True

            self.endpoint_status[endpoint] = 0
            return False
        except Exception as e:
            logger.warning(f"Endpoint {endpoint} test failed: {e}")
            self.endpoint_status[endpoint] = 0
            return False

    async def generate_embeddings(self, texts: List[str], model: str, endpoint: Optional[str] = None) -> np.ndarray:
        if not texts:
            return np.array([])

        if endpoint is None:
            endpoints = self.get_endpoints(model)
            if endpoints:
                endpoint = random.choice(endpoints)

        # Prefer router for non-HTTP endpoints.
        if _use_embedding_router() and (endpoint is None or not str(endpoint).startswith("http")):
            device = None
            if endpoint and not str(endpoint).startswith("http"):
                device = str(endpoint)
            router_fn = _lazy_router_embed_texts() or embed_texts
            if callable(router_fn):
                router_embeddings = await anyio.to_thread.run_sync(
                    lambda: router_fn(texts, model_name=model, device=device)
                )
                return np.array(router_embeddings, dtype=np.float32)

        if endpoint is None:
            raise ValueError(f"No available endpoints for model {model}")

        if str(endpoint).startswith("http"):
            return await self._generate_http_embeddings(texts, str(endpoint))
        return await self._generate_local_embeddings(texts, model, str(endpoint))

    async def _generate_http_embeddings(self, texts: List[str], endpoint: str) -> np.ndarray:
        async with ClientSession() as session:
            data = {"inputs": texts}
            async with session.post(endpoint, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return np.array(result, dtype=np.float32)
                raise RuntimeError(f"HTTP embedding request failed: {response.status}")

    async def _generate_local_embeddings(self, texts: List[str], model: str, device: str) -> np.ndarray:
        # Router-first for local embeddings so callers benefit from provider
        # selection (ipfs_accelerate_py, CLI/cloud, local HF) in one place.
        if _use_embedding_router():
            router_fn = _lazy_router_embed_texts() or embed_texts
            if callable(router_fn):
                try:
                    vectors = await anyio.to_thread.run_sync(
                        lambda: router_fn(texts, model_name=model, device=device)
                    )
                    return np.array(vectors, dtype=np.float32)
                except Exception:
                    pass

        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch not available for local embeddings")

        if model not in self.tokenizer:
            self.tokenizer[model] = {}

        if device not in self.tokenizer[model]:
            tokenizer = AutoTokenizer.from_pretrained(model)
            model_obj = AutoModel.from_pretrained(model)

            if device != "cpu" and torch.cuda.is_available():
                model_obj = model_obj.to(device)

            self.tokenizer[model][device] = {"tokenizer": tokenizer, "model": model_obj}

        components = self.tokenizer[model][device]
        tokenizer = components["tokenizer"]
        model_obj = components["model"]

        inputs = tokenizer(texts, padding=True, truncation=True, return_tensors="pt", max_length=512)
        if device != "cpu" and torch.cuda.is_available():
            inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model_obj(**inputs)
            embeddings = outputs.last_hidden_state.mean(dim=1)

        return embeddings.cpu().numpy()

    def chunk_text(self, text: str, config: ChunkingConfig) -> List[Tuple[int, int]]:
        if not DATASETS_AVAILABLE:
            return [(i, min(i + config.chunk_size, len(text))) for i in range(0, len(text), config.chunk_size)]

        try:
            words = text.split()
            chunks: List[Tuple[int, int]] = []

            if config.method == "fixed":
                chunk_size_words = config.chunk_size // 4
                for i in range(0, len(words), chunk_size_words):
                    start_char = len(" ".join(words[:i]))
                    end_char = len(" ".join(words[: i + chunk_size_words]))
                    chunks.append((start_char, min(end_char, len(text))))

            elif config.method == "sliding_window":
                chunk_size_words = config.chunk_size // 4
                step_size_words = config.step_size // 4
                for i in range(0, len(words), step_size_words):
                    start_char = len(" ".join(words[:i]))
                    end_char = len(" ".join(words[: i + chunk_size_words]))
                    if end_char <= len(text):
                        chunks.append((start_char, end_char))

            return chunks
        except Exception as e:
            logger.warning(f"Chunking failed, using simple split: {e}")
            return [(i, min(i + config.chunk_size, len(text))) for i in range(0, len(text), config.chunk_size)]

    async def index_dataset(
        self,
        dataset_name: str,
        split: Optional[str] = None,
        column: str = "text",
        dst_path: str = "./embeddings_cache",
        models: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not DATASETS_AVAILABLE:
            raise RuntimeError("datasets library not available")

        if models is None:
            models = list(self.tei_endpoints.keys()) or list(self.local_endpoints.keys())

        if not models:
            raise ValueError("No models specified or available")

        os.makedirs(dst_path, exist_ok=True)

        if split is None:
            dataset = load_dataset(dataset_name, streaming=True)
        else:
            dataset = load_dataset(dataset_name, split=split, streaming=True)

        results: Dict[str, Any] = {}
        for model in models:
            results[model] = await self._process_dataset_for_model(dataset, model, column, dst_path)

        return results

    async def _process_dataset_for_model(self, dataset, model: str, column: str, dst_path: str) -> Dict[str, Any]:
        processed_count = 0
        embeddings_list = []
        texts_list = []

        batch_texts: List[str] = []
        batch_size = 32

        try:
            for item in dataset:
                if column in item:
                    text = item[column]
                    batch_texts.append(text)

                    if len(batch_texts) >= batch_size:
                        embeddings = await self.generate_embeddings(batch_texts, model)
                        embeddings_list.extend(embeddings)
                        texts_list.extend(batch_texts)

                        processed_count += len(batch_texts)
                        batch_texts = []

                        if processed_count % 1000 == 0:
                            logger.info(f"Processed {processed_count} items for {model}")

                if processed_count >= 10000:
                    break

            if batch_texts:
                embeddings = await self.generate_embeddings(batch_texts, model)
                embeddings_list.extend(embeddings)
                texts_list.extend(batch_texts)
                processed_count += len(batch_texts)

            output_file = os.path.join(dst_path, f"{model.replace('/', '_')}_embeddings.npz")
            np.savez_compressed(output_file, embeddings=np.array(embeddings_list), texts=texts_list)

            return {
                "status": "success",
                "processed_count": processed_count,
                "output_file": output_file,
                "embedding_dim": len(embeddings_list[0]) if embeddings_list else 0,
            }
        except Exception as e:
            logger.error(f"Error processing dataset for {model}: {e}")
            return {"status": "error", "error": str(e), "processed_count": processed_count}

    async def search_similar(self, query: str, model: str, top_k: int = 10, index_path: Optional[str] = None):
        if not index_path:
            raise ValueError("Index path required for similarity search")

        try:
            data = np.load(index_path)
            embeddings = data["embeddings"]
            texts = data["texts"]

            query_embedding = await self.generate_embeddings([query], model)
            query_embedding = query_embedding[0]

            similarities = np.dot(embeddings, query_embedding) / (
                np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query_embedding)
            )
            top_indices = np.argsort(similarities)[-top_k:][::-1]

            return [
                {"text": texts[idx], "similarity": float(similarities[idx]), "index": int(idx)}
                for idx in top_indices
            ]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def get_status(self) -> Dict[str, Any]:
        return {
            "tei_endpoints": len(self.tei_endpoints),
            "openvino_endpoints": len(self.openvino_endpoints),
            "libp2p_endpoints": len(self.libp2p_endpoints),
            "local_endpoints": len(self.local_endpoints),
            "active_endpoints": sum(1 for status in self.endpoint_status.values() if status >= 1),
            "torch_available": TORCH_AVAILABLE,
            "datasets_available": DATASETS_AVAILABLE,
            "faiss_available": FAISS_AVAILABLE,
            "cached_models": list(self.tokenizer.keys()),
        }



