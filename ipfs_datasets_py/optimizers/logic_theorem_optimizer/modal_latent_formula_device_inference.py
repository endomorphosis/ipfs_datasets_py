"""Private CUDA inference for the unchanged 8D and 384D Legal formula heads.

Checkpoint architecture, grammar, weights and Adam remain unchanged. This
separate numerical execution profile selects CUDA by default when available;
``optimized=False`` selects CPU. Device selection grants no semantic authority.
The caller must hold admission and reserve one CPU thread, as in the original
formula runtime. No module attribute or global Torch default is modified.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import modal_latent_formula_inference as batched
from .checkpoint_content_guard import CheckpointContentGuard


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()


def inference_implementation():
    batched._require(_source_sha256() == _SOURCE_AT_IMPORT,
                     "device formula inference source changed since import")
    return {"schema": "modal-latent-formula-device-inference/v1",
            "source_sha256": _SOURCE_AT_IMPORT,
            "parent": batched.inference_implementation(),
            "checkpoint_conversion_performed": False,
            "cuda_policy": "available_by_default_cpu_opt_out",
            "dtype": "float32", "device_parity": "finite_numeric_and_decisions_not_bitwise",
            "semantic_qualification": False}


class _DeviceTorch:
    """Forward Torch operations while placing only private input tensors."""
    __slots__ = ("_torch", "_device")

    def __init__(self, torch, device):
        self._torch, self._device = torch, device

    def tensor(self, values, *args, **kwargs):
        batched._require("device" not in kwargs or str(kwargs["device"]) == self._device,
                         "private formula tensor requested on a foreign device")
        return self._torch.tensor(values, *args, **{**kwargs, "device": self._device})

    def __getattr__(self, name):
        return getattr(self._torch, name)


class DeviceLatentFormulaDecoder(batched.BatchedLatentFormulaDecoder):
    """Restore exact native weights once, then execute on the selected device.

    Each request retains original source, grammar, finite-value and tensor-value
    checks. Moving private inference tensors does not rewrite checkpoint device
    metadata or move its retained optimizer. CUDA failures propagate; they do
    not silently change devices part way through an inference request.
    """
    def __init__(self, checkpoint, *, expected_binding=None, optimized=True):
        batched._require(type(optimized) is bool, "optimized must be boolean")
        super().__init__(checkpoint, expected_binding=expected_binding)
        torch = self.torch
        device = ("cuda:" + str(torch.cuda.current_device())
                  if optimized and torch.cuda.is_available() else "cpu")
        self._process, self._device, self._optimized = os.getpid(), device, optimized
        self._native_torch = torch
        self.model.to(device)
        self._reference_weights = {name: tensor.to(device)
                                   for name, tensor in self._reference_weights.items()}
        self.torch = _DeviceTorch(torch, device)
        self._tensor_factory = self.torch
        self._checkpoint_guard = CheckpointContentGuard(
            self._checkpoint, expected_sha256=self.checkpoint_sha256)
        self._check()

    def _check(self):
        batched._require(os.getpid() == self._process,
                         "formula device session cannot be inherited across a fork")
        batched._require(self.torch is self._tensor_factory
                         and self.torch._torch is self._native_torch
                         and self.torch._device == self._device,
                         "formula tensor factory changed")
        self._checkpoint_guard.check(self._checkpoint)
        super()._check()
        batched._require(all(str(value.device) == self._device
                             and value.dtype == self._native_torch.float32
                             for value in self.model.state_dict().values()),
                         "formula tensors moved away from their bound device")
        return {**inference_implementation(), "device": self._device,
                "cuda_selected": self._device.startswith("cuda:"),
                "optimized": self._optimized,
                "dimension": self._checkpoint["binding"]["dimension"]}

    def _infer(self, rows, *, projection_id, include_projection):
        # Selection and actual execution are different observations. Hooks on
        # this privately owned model record real input/output tensors only for
        # forward operations that actually ran during this request.
        calls = {"projection_down": 0, "projection_up": 0, "output": 0}
        handles = []
        def observed(name):
            def hook(module, inputs, output):
                batched._require(len(inputs) == 1
                                 and isinstance(inputs[0], self._native_torch.Tensor)
                                 and isinstance(output, self._native_torch.Tensor)
                                 and str(inputs[0].device) == self._device
                                 and str(output.device) == self._device
                                 and inputs[0].dtype == self._native_torch.float32
                                 and output.dtype == self._native_torch.float32,
                                 "actual formula forward tensors differ from bound device/dtype")
                calls[name] += 1
            return hook
        try:
            for name in calls:
                handles.append(getattr(self.model, name).register_forward_hook(observed(name)))
            result = super()._infer(rows, projection_id=projection_id, include_projection=include_projection)
            report = result[0] if include_projection else result
            report["inference_implementation"].update(
                actual_forward_calls=dict(calls), actual_forward_executed=bool(sum(calls.values())),
                cuda_executed=self._device.startswith("cuda:") and bool(sum(calls.values())))
            return result
        finally:
            for handle in handles:
                handle.remove()

    @property
    def inference_implementation(self):
        return self._check()


__all__ = ["DeviceLatentFormulaDecoder", "inference_implementation"]
