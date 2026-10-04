"""Batched numerical forwards with unchanged CPU canonical span decisions.

Only valid, complete native768 inputs enter the resident device model. The four
head tensors cross to CPU once per numerical batch; a request-local surrogate
serves each exactly bound source/token/vector row to the original single-rule
decision kernel. Pointer padding never enters a row's candidate spans.
``optimized=False`` retains the original singleton CPU execution path.

This is a separate numerical profile, not a conversion, trained head, proof
admission, or guarantee of bitwise equality to singleton GRU operations.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

from . import legal_span_device_inference as resident
from . import legal_span_dimensions as dimensional
from . import legal_span_formula as span
from .checkpoint_content_guard import CheckpointContentGuard

SCHEMA = "native-768-source-span-batched-device-inference/v1"
PROFILE = "native-768-source-span-batched-device-float32-cpu-decisions/v1"
_SOURCE_AT_IMPORT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RESIDENT_AT_IMPORT = hashlib.sha256(Path(resident.__file__).read_bytes()).hexdigest()
_DECODE_AT_IMPORT = resident._DECODE_AT_IMPORT
_TOKENIZER_AT_IMPORT = resident._TOKENIZER_AT_IMPORT
_BATCH_AT_IMPORT = resident._BATCH_AT_IMPORT
_OUTPUTS = ("modality", "presence", "start", "end")
_require = span._require


def _implementation():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_AT_IMPORT
             and hashlib.sha256(Path(resident.__file__).read_bytes()).hexdigest() == _RESIDENT_AT_IMPORT,
             "batched native768 inference producer changed since import")
    _require(resident._DECODE_AT_IMPORT is _DECODE_AT_IMPORT
             and resident._TOKENIZER_AT_IMPORT is _TOKENIZER_AT_IMPORT
             and resident._BATCH_AT_IMPORT is _BATCH_AT_IMPORT,
             "batched native768 inference dependency identity changed")
    return {"source_sha256": _SOURCE_AT_IMPORT, "resident_source_sha256": _RESIDENT_AT_IMPORT,
            "native_checkpoint_producers": resident._implementation()}


class _CachedOutput:
    """One CPU row, usable only with its exact native input tensors and gate."""
    def __init__(self, torch, *, text, vector, tokens, output, enabled):
        self._torch, self._enabled = torch, enabled
        self._binding = deepcopy({"text": text, "vector": vector, "tokens": tokens})
        self._binding_guard = CheckpointContentGuard(self._binding)
        self._expected = _BATCH_AT_IMPORT(torch, [{"tokens": tokens, "latent": vector}])
        shapes = {"modality": (1, 3), "presence": (1, 4, 2),
                  "start": (1, 6, len(tokens)), "end": (1, 6, len(tokens))}
        _require(type(output) is dict and set(output) == set(_OUTPUTS) and all(
            isinstance(value, torch.Tensor) and str(value.device) == "cpu" and value.dtype == torch.float32
            and tuple(value.shape) == shapes[name] and bool(torch.isfinite(value).all())
            for name, value in output.items()), "closed finite CPU cached head tensors required")
        self._output = {name: value.detach().clone() for name, value in output.items()}
        self._reference = {name: value.detach().clone() for name, value in self._output.items()}
        self._used = False
        self.bind(text, vector)

    def bind(self, text, vector):
        # byte tensors alone lose the original case and character offsets.
        # Preserve those full token records and exact source text as well.
        self._binding_guard.check(self._binding)
        self._binding_guard.check({"text": text, "vector": vector,
                                   "tokens": _TOKENIZER_AT_IMPORT(text)})

    def eval(self):
        return self

    def __call__(self, *inputs, enabled=True):
        _require(not self._used and type(enabled) is bool and enabled == self._enabled
                 and len(inputs) == len(self._expected), "cached numerical output gate/use differs")
        torch = self._torch
        self._binding_guard.check(self._binding)
        _require(all(isinstance(value, torch.Tensor) and str(value.device) == "cpu"
                     and value.dtype == expected.dtype and value.shape == expected.shape
                     and torch.equal(value, expected)
                     and (not value.is_floating_point() or torch.equal(torch.signbit(value), torch.signbit(expected)))
                     for value, expected in zip(inputs, self._expected)),
                 "cached numerical output source/token/native vector differs")
        _require(set(self._output) == set(_OUTPUTS) and all(
            str(value.device) == "cpu" and value.dtype == torch.float32
            and value.shape == self._reference[name].shape and bool(torch.isfinite(value).all())
            and torch.equal(value, self._reference[name])
            and torch.equal(torch.signbit(value), torch.signbit(self._reference[name]))
            for name, value in self._output.items()), "cached numerical outputs changed")
        self._used = True
        # The inherited kernel only reads these tensors. Returning fresh values
        # also prevents a decision helper from retaining mutable cache storage.
        return {name: value.clone() for name, value in self._output.items()}


class _NoForward:
    def eval(self):
        return self

    def __call__(self, *args, **kwargs):
        raise ValueError("invalid source unexpectedly requested a numerical forward")


def _row_output(output, index, length):
    _require(type(index) is int and type(length) is int and 0 <= index < output["modality"].shape[0]
             and 1 <= length <= output["start"].shape[2], "bounded cached output row required")
    return {"modality": output["modality"][index:index + 1],
            "presence": output["presence"][index:index + 1],
            "start": output["start"][index:index + 1, :, :length],
            "end": output["end"][index:index + 1, :, :length]}


def _batch_memory_bound(records, config, *, parameter_bytes, checkpoint_bytes):
    """Conservative shape bound before any padded input tensor is allocated.

    This accounts for private weights/references, padded byte IDs and three
    embedding-sized buffers, recurrent intermediates and CPU decision tensors.
    The fixed allowance covers library workspace; it is an admission estimate,
    not a kernel or process memory enforcement claim.
    """
    if not records:
        return {"gpu_working_set_bytes": 0, "host_working_set_bytes": 0}
    count = len(records)
    width = max(len(record["tokens"]) for record in records)
    byte_width = max(len(token["byte_ids"]) for record in records for token in record["tokens"])
    padded = count * width * byte_width
    embedding = padded * config["embedding_dim"] * 4
    recurrent = count * width * config["hidden_size"] * 2 * 4 * 16
    output = count * (3 + 8 + 12 * width) * 4
    working = 128 * 1024**2 + parameter_bytes * 2 + padded * 8 + embedding * 3 + recurrent
    return {"gpu_working_set_bytes": working,
            "host_working_set_bytes": working + output * 4 + checkpoint_bytes * 12}


class DeviceBatchedDimensionalSpanSession(resident.DeviceDimensionalSpanSession):
    """The resident768 admission/fences, with a request-local batched forward."""
    def _check(self):
        _implementation()
        return super()._check()

    def _description(self):
        parent = super()._description()
        return {**parent, "profile_id": PROFILE,
                "numerical_batching": "one_complete_valid_source_batch" if self._optimized else "singleton_cpu_opt_out",
                "canonical_decision_device": "cpu" if self._optimized else "resident_cpu",
                "output_transfer_policy": "four_complete_head_tensors_once_per_request" if self._optimized else "none",
                "request_local_numerical_cache": self._optimized,
                "batch_memory_policy": "conservative_shape_bound_before_padded_allocation_refuse_without_truncation",
                "kernel_resource_enforcement": False,
                "singleton_numeric_bitwise_parity_claimed": False,
                "batched_implementation": _implementation()}

    def _decision(self, text, vector, tokens, output, *, enabled):
        torch = self._torch
        surrogate = (_NoForward() if tokens is None else _CachedOutput(torch,
            text=text, vector=vector, tokens=tokens, output=output, enabled=enabled))
        decoder = span.SpanLegalFormulaDecoder.__new__(span.SpanLegalFormulaDecoder)
        decoder.torch, decoder.model = torch, surrogate
        decoder.checkpoint, decoder.checkpoint_sha256 = self._checkpoint, self.checkpoint_sha256
        result = _DECODE_AT_IMPORT(decoder, text, vector, enabled=enabled)
        _require(tokens is None or surrogate._used, "valid source did not consume its bound numerical output")
        return result

    def _admit_batch_memory(self, records):
        state_bytes = sum(value.numel() * value.element_size() for value in self._model.state_dict().values())
        bound = _batch_memory_bound(records, self._checkpoint["config"], parameter_bytes=state_bytes,
                                    checkpoint_bytes=len(self._guard._canonical_bytes))
        _require(bound["host_working_set_bytes"] <= self._lease.memory_mb * 1024**2,
                 "complete native768 batch exceeds reserved host memory estimate")
        if self._device.startswith("cuda:"):
            _require(bound["gpu_working_set_bytes"] <= self._lease.gpu_memory_mb * 1024**2,
                     "complete native768 batch exceeds reserved GPU memory estimate")
        return bound

    def decode_formal_logic(self, texts, latents, *, latent_ablation="none",
                            embedding_receipts=None, expected_receipt_sha256s=None):
        if not self._optimized:
            result = super().decode_formal_logic(texts, latents, latent_ablation=latent_ablation,
                embedding_receipts=embedding_receipts, expected_receipt_sha256s=expected_receipt_sha256s)
            return {**result, "schema": SCHEMA, "numerical_batching": False,
                    "cpu_head_output_materializations": 0, "device_to_cpu_head_transfers": 0,
                    "canonical_decision_device": "cpu"}
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128
                 and all(type(text) is str for text in texts), "one to 128 source strings required")
        _require(type(latents) in (list, tuple) and len(latents) == len(texts), "one native768 vector per source required")
        vectors = [span._vector(vector, 768) for vector in latents]
        _require(type(latent_ablation) is str and latent_ablation in ("none", "zero", "rotate", "disabled"),
                 "unsupported latent ablation")
        _require(latent_ablation != "rotate" or len(texts) > 1, "rotate requires at least two sources")
        authored = deepcopy({"texts": list(texts), "vectors": vectors,
                             "receipts": embedding_receipts, "receipt_pins": expected_receipt_sha256s})
        inputs_guard = CheckpointContentGuard(authored)
        with self._operation():
            self._check()
            receipt_status = resident._verify_receipts(self._checkpoint["context_contract"],
                authored["texts"], authored["vectors"], authored["receipts"], authored["receipt_pins"])
            if latent_ablation == "zero":
                vectors = [[0.] * 768 for _ in vectors]
            elif latent_ablation == "rotate":
                vectors = vectors[1:] + vectors[:1]
            enabled = latent_ablation != "disabled"
            tokens, valid, locations = [], [], {}
            for position, (text, vector) in enumerate(zip(authored["texts"], vectors)):
                self._poll()
                try:
                    source_tokens = _TOKENIZER_AT_IMPORT(text)
                except ValueError:
                    source_tokens = None
                tokens.append(source_tokens)
                if source_tokens is not None:
                    locations[position] = len(valid)
                    valid.append({"tokens": source_tokens, "latent": vector})
            self._check()
            memory_bound = self._admit_batch_memory(valid)
            start = len(self._observations)
            output, rows = None, []
            try:
                if valid:
                    with self._torch.inference_mode():
                        actual = self._model(*_BATCH_AT_IMPORT(self._tensor_factory, valid), enabled=enabled)
                    _require(type(actual) is dict and set(actual) == set(_OUTPUTS)
                             and tuple(actual["modality"].shape) == (len(valid), 3)
                             and tuple(actual["presence"].shape) == (len(valid), 4, 2)
                             and tuple(actual["start"].shape) == tuple(actual["end"].shape)
                             and actual["start"].shape[:2] == (len(valid), 6),
                             "batched source-span head output coverage/shape differs")
                    output = {name: actual[name].detach().cpu() for name in _OUTPUTS}
                    self._synchronize()
                    self._check()
                    _require(all(str(value.device) == "cpu" and value.dtype == self._torch.float32
                                 and bool(self._torch.isfinite(value).all()) for value in output.values()),
                             "batched CPU decision tensors differ from finite float32 profile")
                for position, (text, vector, source_tokens) in enumerate(zip(authored["texts"], vectors, tokens)):
                    self._poll()
                    row_output = (None if source_tokens is None else
                                  _row_output(output, locations[position], len(source_tokens)))
                    with self._torch.inference_mode():
                        rows.append(self._decision(text, vector, source_tokens, row_output, enabled=enabled))
                count = sum(row["status"] == "decoded" for row in rows)
                result = {"schema": SCHEMA, "lineage_id": dimensional.LINEAGE_ID,
                    "checkpoint_sha256": self.checkpoint_sha256,
                    "source_parent_checkpoint_sha256": self._checkpoint["source_parent_checkpoint_sha256"],
                    "context_contract_sha256": self._checkpoint["context_contract_sha256"], "input_dimension": 768,
                    "rows": rows, "decoded_count": count,
                    "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
                    "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
                    "training_executed": False, "model_state_unchanged": True, "input_receipts": receipt_status,
                    "execution_profile": self._description(),
                    "actual_forward_batches": deepcopy(self._observations[start:]),
                    "cuda_executed": self._device.startswith("cuda:") and bool(valid),
                    "numerical_batching": True, "valid_source_count": len(valid),
                    "batch_memory_bound": memory_bound,
                    "cpu_head_output_materializations": 4 if valid else 0,
                    "device_to_cpu_head_transfers": 4 if valid and self._device.startswith("cuda:") else 0,
                    "canonical_decision_device": "cpu", **span.FALSE}
                result_guard = CheckpointContentGuard(result)
                self._check()
                inputs_guard.check({"texts": list(texts), "vectors": [span._vector(vector, 768) for vector in latents],
                                    "receipts": embedding_receipts, "receipt_pins": expected_receipt_sha256s})
                self._pure_check()
                result_guard.check(result)
                return result
            finally:
                self._synchronize()
                del self._observations[start:]

    infer = decode_formal_logic


__all__ = ["DeviceBatchedDimensionalSpanSession", "SCHEMA", "PROFILE"]
