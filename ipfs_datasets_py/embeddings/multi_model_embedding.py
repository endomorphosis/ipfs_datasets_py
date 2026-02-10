"""Multi-model embedding generation.

Refactored into `ipfs_datasets_py.embeddings`.
When available, uses `ipfs_datasets_py.embeddings_router` to generate embeddings so
callers can switch between local embeddings and ipfs_accelerate_py-backed providers.
"""

import json
import time
import uuid
import logging
from typing import Dict, List, Any, Optional, Union

import numpy as np

try:
    import torch
    from transformers import AutoTokenizer, AutoModel

    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False

try:
    from ipfs_datasets_py.embeddings_router import embed_texts
except Exception:  # pragma: no cover
    embed_texts = None

try:
    from ipfs_datasets_py.embeddings_router import get_accelerate_manager as _get_accelerate_manager
except Exception:  # pragma: no cover
    _get_accelerate_manager = None


def _lazy_router_embed_texts():
    try:
        from ipfs_datasets_py.embeddings_router import embed_texts as router_embed_texts

        return router_embed_texts
    except Exception:
        return None


class MultiModelEmbeddingGenerator:
    def __init__(
        self,
        model_configs: Optional[List[Dict[str, Any]]] = None,
        device: str = "cpu",
        cache_dir: Optional[str] = None,
        enable_model_fusion: bool = False,
        use_accelerate: bool = True,
        use_router: bool = True,
    ):
        self.models: Dict[str, Any] = {}
        self.tokenizers: Dict[str, Any] = {}
        self.model_configs = model_configs or [
            {"name": "sentence-transformers/all-MiniLM-L6-v2", "dimension": 384, "type": "sentence"},
            {"name": "sentence-transformers/multi-qa-mpnet-base-dot-v1", "dimension": 768, "type": "qa"},
        ]
        self.device = device
        self.cache_dir = cache_dir
        self.enable_model_fusion = enable_model_fusion
        self.use_router = use_router

        self.stats = {
            "models_loaded": 0,
            "embedding_requests": 0,
            "total_chunks_processed": 0,
            "average_embedding_time": 0.0,
            "total_embedding_time": 0.0,
            "embedding_errors": 0,
        }

        self.accelerate_manager = None
        if use_accelerate and callable(_get_accelerate_manager):
            try:
                self.accelerate_manager = _get_accelerate_manager(
                    purpose="multi_model_embedding",
                    enable_distributed=True,
                    resources={"device": device, "cache_dir": cache_dir},
                )
            except Exception as e:
                logging.warning(f"⚠ Failed to initialize accelerate manager: {e}")
                self.accelerate_manager = None

        # If we can use router, avoid eager heavyweight model loading.
        if HAS_TRANSFORMERS and not (self.use_router and embed_texts is not None):
            self._load_models()
        elif not HAS_TRANSFORMERS and not (self.use_router and embed_texts is not None):
            logging.warning(
                "Transformers library not available. MultiModelEmbeddingGenerator will use fallback methods."
            )

    def _load_models(self):
        for config in self.model_configs:
            model_name = config["name"]
            try:
                self.tokenizers[model_name] = AutoTokenizer.from_pretrained(model_name, cache_dir=self.cache_dir)
                self.models[model_name] = AutoModel.from_pretrained(model_name, cache_dir=self.cache_dir).to(
                    self.device
                )
                self.stats["models_loaded"] += 1
                logging.info(f"Loaded model: {model_name}")
            except Exception as e:
                logging.error(f"Error loading model {model_name}: {str(e)}")
                self.stats["embedding_errors"] += 1

    def generate_embeddings(
        self,
        text: Union[str, List[str]],
        model_names: Optional[List[str]] = None,
        chunk_size: int = 512,
        overlap: int = 50,
        batch_size: int = 8,
        normalize: bool = True,
    ) -> Dict[str, List[np.ndarray]]:
        start_time = time.time()
        self.stats["embedding_requests"] += 1

        texts = [text] if isinstance(text, str) else text

        configured_models = [cfg["name"] for cfg in self.model_configs]
        models_to_use = model_names or configured_models
        models_to_use = [m for m in models_to_use if m in configured_models]
        if not models_to_use:
            return {}

        all_chunks: List[str] = []
        for text_item in texts:
            all_chunks.extend(self._chunk_text(text_item, chunk_size, overlap))
        self.stats["total_chunks_processed"] += len(all_chunks)

        result: Dict[str, List[np.ndarray]] = {}
        for model_name in models_to_use:
            try:
                embeddings = self._batch_encode(
                    model_name=model_name, chunks=all_chunks, batch_size=batch_size, normalize=normalize
                )
                result[model_name] = embeddings
            except Exception as e:
                logging.error(f"Error generating embeddings with model {model_name}: {str(e)}")
                self.stats["embedding_errors"] += 1

        if self.enable_model_fusion and len(models_to_use) > 1:
            try:
                result["fused"] = self._fuse_embeddings(result)
            except Exception as e:
                logging.error(f"Error during model fusion: {str(e)}")

        embedding_time = time.time() - start_time
        self.stats["total_embedding_time"] += embedding_time
        embedding_count = self.stats["embedding_requests"]
        self.stats["average_embedding_time"] = self.stats["total_embedding_time"] / embedding_count

        return result

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        if "\n\n" in text:
            segments = text.split("\n\n")
        else:
            segments = text.replace(". ", ".\n").split("\n")

        chunks: List[str] = []
        current_chunk = ""

        for segment in segments:
            if len(current_chunk) + len(segment) > chunk_size:
                if current_chunk:
                    chunks.append(current_chunk.strip())

                if len(segment) > chunk_size:
                    words = segment.split()
                    temp_chunk = ""
                    for word in words:
                        if len(temp_chunk) + len(word) + 1 > chunk_size:
                            chunks.append(temp_chunk.strip())
                            prev_words = temp_chunk.split()[-overlap:] if overlap > 0 else []
                            temp_chunk = " ".join(prev_words + [word])
                        else:
                            temp_chunk = f"{temp_chunk} {word}".strip()
                    current_chunk = temp_chunk
                else:
                    if overlap > 0 and chunks:
                        prev_words = chunks[-1].split()[-overlap:]
                        current_chunk = (" ".join(prev_words) + " " + segment).strip()
                    else:
                        current_chunk = segment
            else:
                current_chunk = f"{current_chunk} {segment}".strip()

        if current_chunk:
            chunks.append(current_chunk.strip())
        return chunks

    def _batch_encode(self, model_name: str, chunks: List[str], batch_size: int, normalize: bool) -> List[np.ndarray]:
        # Router-first: lets callers choose local vs accelerate without changing code.
        if self.use_router:
            router_fn = _lazy_router_embed_texts() or embed_texts
            if callable(router_fn):
                vectors = router_fn(chunks, model_name=model_name, device=self.device)
                embeddings = [np.array(v, dtype=np.float32) for v in vectors]
                if normalize:
                    out: List[np.ndarray] = []
                    for emb in embeddings:
                        norm = np.linalg.norm(emb)
                        out.append(emb / norm if norm > 0 else emb)
                    return out
                return embeddings

        if embed_texts is not None and self.use_router:
            # Back-compat (should be redundant with lazy import above)
            vectors = embed_texts(chunks, model_name=model_name, device=self.device)
            embeddings = [np.array(v, dtype=np.float32) for v in vectors]
            if normalize:
                out: List[np.ndarray] = []
                for emb in embeddings:
                    norm = np.linalg.norm(emb)
                    out.append(emb / norm if norm > 0 else emb)
                return out
            return embeddings

        if not HAS_TRANSFORMERS:
            dimension = next((cfg["dimension"] for cfg in self.model_configs if cfg["name"] == model_name), 768)
            return [np.random.rand(dimension).astype(np.float32) for _ in chunks]

        # Local transformers fallback (only if router unavailable/disabled)
        if model_name not in self.models:
            self._load_models()
        model = self.models[model_name]
        tokenizer = self.tokenizers[model_name]

        all_embeddings: List[np.ndarray] = []
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i : i + batch_size]
            inputs = tokenizer(batch_chunks, padding=True, truncation=True, return_tensors="pt").to(self.device)
            with torch.no_grad():
                outputs = model(**inputs)

            attention_mask = inputs["attention_mask"]
            pooled = self._mean_pooling(outputs, attention_mask)
            if normalize:
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            for embedding in pooled:
                all_embeddings.append(embedding.cpu().numpy())
        return all_embeddings

    def _mean_pooling(self, model_output, attention_mask):
        token_embeddings = model_output[0]
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        return sum_embeddings / sum_mask

    def _fuse_embeddings(self, model_embeddings: Dict[str, List[np.ndarray]]) -> List[np.ndarray]:
        num_chunks = len(next(iter(model_embeddings.values()))) if model_embeddings else 0
        fused: List[np.ndarray] = []

        for i in range(num_chunks):
            chunk_embeddings = [embeddings[i] for _, embeddings in model_embeddings.items()]
            normalized = [emb / np.linalg.norm(emb) for emb in chunk_embeddings if np.linalg.norm(emb) > 0]
            if normalized:
                fused_vector = np.concatenate(normalized)
                norm = np.linalg.norm(fused_vector)
                if norm > 0:
                    fused_vector = fused_vector / norm
                fused.append(fused_vector.astype(np.float32))
            else:
                fused.append(np.zeros(sum(emb.shape[0] for emb in chunk_embeddings), dtype=np.float32))

        return fused

    def store_on_ipfs(self, embeddings: Dict[str, List[np.ndarray]], metadata: Optional[Dict[str, Any]] = None, ipfs_client=None):
        if ipfs_client is None:
            logging.warning("IPFS client not provided. Generating CIDs locally.")
            return {model_name: f"bafy..{uuid.uuid4().hex[:16]}" for model_name in embeddings}

        result: Dict[str, str] = {}
        metadata = metadata or {}
        for model_name, model_embeddings in embeddings.items():
            try:
                model_data = {
                    "model": model_name,
                    "dimension": len(model_embeddings[0]) if model_embeddings else 0,
                    "count": len(model_embeddings),
                    "embeddings": [emb.tolist() for emb in model_embeddings],
                    "metadata": metadata,
                }
                block_data = json.dumps(model_data).encode()
                cid = ipfs_client.add_bytes(block_data)
                result[model_name] = cid
            except Exception as e:
                logging.error(f"Error storing embeddings for {model_name} on IPFS: {str(e)}")
                result[model_name] = f"error:{str(e)}"
        return result

    def load_from_ipfs(self, cids: Dict[str, str], ipfs_client=None) -> Dict[str, List[np.ndarray]]:
        if ipfs_client is None:
            logging.error("IPFS client required to load embeddings from IPFS")
            return {}

        result: Dict[str, List[np.ndarray]] = {}
        for model_name, cid in cids.items():
            try:
                block_data = ipfs_client.get_bytes(cid)
                model_data = json.loads(block_data.decode())
                result[model_name] = [np.array(emb, dtype=np.float32) for emb in model_data["embeddings"]]
            except Exception as e:
                logging.error(f"Error loading embeddings for {model_name} from IPFS: {str(e)}")
        return result

    def get_model_dimensions(self) -> Dict[str, int]:
        return {cfg["name"]: cfg["dimension"] for cfg in self.model_configs}

    def get_stats(self) -> Dict[str, Any]:
        return self.stats

    @classmethod
    def from_config(cls, config_path: str) -> "MultiModelEmbeddingGenerator":
        with open(config_path, "r") as f:
            config = json.load(f)
        return cls(
            model_configs=config.get("models", None),
            device=config.get("device", "cpu"),
            cache_dir=config.get("cache_dir", None),
            enable_model_fusion=config.get("enable_model_fusion", False),
            use_router=config.get("use_router", True),
        )
