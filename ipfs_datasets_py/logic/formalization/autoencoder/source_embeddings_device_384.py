"""Bounded resident GTE-small device sessions with actual tensor evidence.

Default CUDA selection has an explicit CPU opt-out. Pinned assets, strict
untruncated tokens and frozen model tensor values are checked at both request
boundaries. A device receipt establishes numerical execution, not source or
proof correctness. Existing embedding producer and receipt profiles are intact.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading

from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer

FALSE = {"proof_authority": False, "source_semantics_verified": False,
         "execution_authority": False, "promotion_performed": False,
         "training_executed": False}


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()
_PRODUCER_AT_IMPORT = hashlib.sha256(Path(producer.__file__).read_bytes()).hexdigest()


def _device_features(features, torch, device):
    # New SentenceTransformer preprocessors also include an inert text-modality
    # marker. Preserve that exact marker; arbitrary non-tensor inputs are not
    # accepted or treated as device evidence.
    if (not {"input_ids", "attention_mask"} <= set(features)
            or set(features) - {"input_ids", "attention_mask", "token_type_ids", "modality"}
            or ("modality" in features and features["modality"] != "text")):
        raise ValueError("closed text-only embedding features required")
    result = {}
    for name, value in features.items():
        if name == "modality":
            result[name] = "text"
        else:
            if not isinstance(value, torch.Tensor):
                raise ValueError("actual embedding inputs must be native tensors")
            result[name] = value.to(device)
            if str(result[name].device) != device:
                raise ValueError("embedding inputs moved to a foreign device")
    return result


class SourceEmbeddingDeviceSession384:
    """One explicitly owned local float32 encoder; close releases its tensors."""
    def __init__(self, *, snapshot_path=None, optimized=True):
        if type(optimized) is not bool:
            raise ValueError("optimized must be boolean")
        import torch
        from sentence_transformers import SentenceTransformer
        if torch.get_num_threads() != 1:
            raise ValueError("caller must reserve CPU and set torch.set_num_threads(1)")
        self._process, self._torch, self._lock = os.getpid(), torch, threading.RLock()
        self._snapshot, self._manifest = producer._snapshot_assets(
            snapshot_path or producer.DEFAULT_SNAPSHOT_PATH)
        self._device = ("cuda:" + str(torch.cuda.current_device())
                        if optimized and torch.cuda.is_available() else "cpu")
        self._optimized = optimized
        with torch.random.fork_rng(devices=[]):
            self._model = SentenceTransformer(str(self._snapshot), local_files_only=True,
                                              trust_remote_code=False, device="cpu")
        self._model.eval()
        producer._validate_model(self._model, torch)
        self._model.to(self._device)
        self._reference = {name: tensor.detach().clone()
                           for name, tensor in self._model.state_dict().items()}
        self._check()

    def _check(self):
        if self._model is None:
            raise ValueError("embedding device session is closed")
        if os.getpid() != self._process:
            raise ValueError("embedding device session cannot be inherited across a fork")
        if (_source_sha256() != _SOURCE_AT_IMPORT
                or hashlib.sha256(Path(producer.__file__).read_bytes()).hexdigest() != _PRODUCER_AT_IMPORT):
            raise ValueError("embedding device producer changed since import")
        _, manifest = producer._snapshot_assets(self._snapshot)
        if manifest != self._manifest:
            raise ValueError("embedding assets changed after loading")
        state = self._model.state_dict()
        if (set(state) != set(self._reference)
                or any(value.shape != self._reference[name].shape
                       or value.dtype != self._reference[name].dtype
                       or str(value.device) != self._device
                       or not self._torch.equal(value, self._reference[name])
                       for name, value in state.items())
                or any(module.training for module in self._model.modules())):
            raise ValueError("embedding model tensors changed after loading")

    def _description(self):
        return {"schema": "source-embedding-device-384/v1", "dimension": 384,
                    "model_id": "thenlper/gte-small", "revision": producer.PINNED_REVISION,
                    "device": self._device, "optimized": self._optimized,
                    "dtype": "float32", "max_rows": 128, "max_batch_size": producer.MAX_BATCH_SIZE,
                    "source_sha256": _SOURCE_AT_IMPORT,
                    "asset_producer_sha256": _PRODUCER_AT_IMPORT,
                "assets": [dict(item) for item in self._manifest], **FALSE}

    def describe(self):
        with self._lock:
            self._check()
            return self._description()

    def infer(self, texts):
        if (type(texts) not in (list, tuple) or not 1 <= len(texts) <= 128
                or any(type(text) is not str or not text.strip() or len(text) > 32768 for text in texts)):
            raise ValueError("bounded nonempty source texts required")
        with self._lock:
            self._check()
            model, torch = self._model, self._torch
            counted = [producer._untruncated_tokens(model, text) for text in texts]
            if any(len(tokens["input_ids"]) > producer.MAX_TOKENS for tokens in counted):
                raise ValueError("source exceeds GTE-small's 512-token limit; chunk it before inference")
            vectors, batches = [], []
            for offset in range(0, len(texts), producer.MAX_BATCH_SIZE):
                part = list(texts[offset:offset + producer.MAX_BATCH_SIZE])
                features = model.tokenize(part)
                captures = [producer._captured_tokens(features, row) for row in range(len(part))]
                if captures != counted[offset:offset + len(part)]:
                    raise ValueError("actual forward tokens differ from untruncated tokenizer output")
                features = _device_features(features, torch, self._device)
                with torch.inference_mode():
                    output = model(features)["sentence_embedding"]
                if (str(output.device) != self._device or output.dtype != torch.float32
                        or tuple(output.shape) != (len(part), 384)
                        or not bool(torch.isfinite(output).all())):
                    raise ValueError("actual embedding forward returned invalid device/dtype/shape/values")
                if [producer._captured_tokens(features, row) for row in range(len(part))] != captures:
                    raise ValueError("embedding forward changed actual token inputs")
                norms = torch.linalg.vector_norm(output, dim=1)
                if not bool(torch.all(torch.abs(norms - 1.) <= 2e-5)):
                    raise ValueError("actual embedding forward did not return normalized vectors")
                vectors.extend(output.detach().cpu().tolist())
                batches.append({"rows": len(part), "input_device": self._device,
                                "output_device": str(output.device), "output_dtype": str(output.dtype)})
            self._check()
            return {"profile": self._description(), "vectors": vectors,
                    "source_sha256": [hashlib.sha256(text.encode()).hexdigest() for text in texts],
                    "tokens": counted, "actual_forward_batches": batches,
                    "cuda_executed": self._device.startswith("cuda:"), **FALSE}

    def embed_texts(self, texts):
        return self.infer(texts)["vectors"]

    def close(self):
        with self._lock:
            self._model, self._reference = None, {}

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        self.close()


__all__ = ["SourceEmbeddingDeviceSession384"]
