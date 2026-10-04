"""Additive Legal384 inference with a private device-bound formula head.

The released sparse modal core retains its explicit CPU binding. Only the
separately identified, unchanged formula-head weights and GTE encoder select
CUDA when available. ``optimized=False`` opts both private stages out to CPU.
Neither this numerical device profile nor released candidates grants authority.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import legal_384_package as package
from . import legal_inference_session as cpu
from .checkpoint_hub import HubAutoencoder


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()


class LegalDeviceInferenceRuntime(cpu.OptimizedRuntime):
    @cpu._cpu_inference
    def __init__(self, runtime, *, optimized=True):
        package._require(type(optimized) is bool, "optimized must be boolean")
        self._optimized, self._closed = optimized, False
        super().__init__(runtime)
        if self._session is not None:
            from ....optimizers.logic_theorem_optimizer.modal_latent_formula_device_inference import DeviceLatentFormulaDecoder
            # This session and decoder are private to this wrapper. The loaded
            # package's own decoder, core, checkpoint and Adam are untouched.
            checkpoint = runtime._payload["formula_checkpoint"]
            self._session._decoder = DeviceLatentFormulaDecoder(
                checkpoint, expected_binding=runtime._payload["core_binding"], optimized=optimized)

    def _check(self):
        package._require(not self._closed, "Legal device inference session is closed")
        package._require(_source_sha256() == _SOURCE_AT_IMPORT,
                         "Legal device inference producer changed since import")
        return super()._check()

    def _inference_implementation(self):
        base = super()._inference_implementation()
        selection = (None if self._session is None
                     else self._session._decoder.inference_implementation)
        return {"schema": "legal-384-private-device-inference/v1", "source_sha256": _SOURCE_AT_IMPORT,
                "core_device": "cpu", "formula_head_selection": selection,
                "optimized": self._optimized, "parent_cpu_projection": base,
                "checkpoint_conversion_performed": False, "whole_model_cuda": False}

    def close(self):
        self._closed, self._session = True, None


class DeviceLegalAutoencoder(HubAutoencoder):
    """A verified release with explicitly owned encoder and formula sessions."""
    def __init__(self, loaded, *, optimized=True):
        package._require(type(loaded) is HubAutoencoder and loaded.domain == "legal_ir",
                         "original verified Legal Hub autoencoder required")
        self._optimized, self._embedding = optimized, None
        super().__init__(loaded.domain, LegalDeviceInferenceRuntime(loaded.runtime, optimized=optimized),
                         loaded.manifest, loaded.descriptor)

    @cpu._cpu_inference
    def infer_texts(self, texts, *, snapshot_path=None):
        if (type(texts) not in (list, tuple) or not 1 <= len(texts) <= 128
                or any(type(text) is not str or not text.strip() or len(text) > 32768 for text in texts)):
            raise ValueError("bounded nonempty Legal source texts required")
        from .source_embeddings_device_384 import SourceEmbeddingDeviceSession384
        self.runtime._check()
        if self._embedding is None:
            self._embedding = SourceEmbeddingDeviceSession384(snapshot_path=snapshot_path,
                                                              optimized=self._optimized)
        elif snapshot_path is not None and Path(snapshot_path).resolve() != self._embedding._snapshot.resolve():
            raise ValueError("resident Legal encoder requires the same pinned snapshot")
        embedded = self._embedding.infer(texts)
        rows = [{"id": "input-" + str(index), "source_text": text, "embedding": vector}
                for index, (text, vector) in enumerate(zip(texts, embedded["vectors"]))]
        result = self.infer(rows)
        result["embedding_execution"] = {key: embedded[key] for key in
            ("profile", "source_sha256", "tokens", "actual_forward_batches", "cuda_executed")}
        return result

    def close(self):
        if self._embedding is not None:
            self._embedding.close()
            self._embedding = None
        self.runtime.close()

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        self.close()


def open_legal_device_autoencoder(*, descriptor=None, cache_dir=None, local_files_only=False,
                                 optimized=True):
    """Load a pinned release, then choose CUDA for compatible private stages."""
    from .checkpoint_hub import open_autoencoder
    package._require(type(optimized) is bool, "optimized must be boolean")
    loaded = open_autoencoder("legal_ir", descriptor=descriptor, cache_dir=cache_dir,
                              local_files_only=local_files_only, optimized=False)
    return DeviceLegalAutoencoder(loaded, optimized=optimized)


__all__ = ["LegalDeviceInferenceRuntime", "DeviceLegalAutoencoder", "open_legal_device_autoencoder"]
