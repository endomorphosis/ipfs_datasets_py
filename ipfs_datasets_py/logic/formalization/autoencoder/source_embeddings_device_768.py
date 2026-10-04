"""Owned, bounded native multilingual GTE sessions with explicit device identity.

The unchanged complete CPU loader admits every published tensor. This session
keeps that model resident and defaults to CUDA when available; ``optimized=False``
selects CPU. It never emits the historical CPU producer's receipt profile.

Full asset SHA admission occurs once while NOFOLLOW file descriptors are held.
Every operation checks their exact inode/size/mtime/ctime custody, native model
values and tokenizer state at entry and exit. These checks detect ordinary local
replacement/write races; they are sequential observations, not an atomic file
snapshot or protection against a privileged actor falsifying filesystem metadata.
Callers own resource admission and must reserve memory for both model and its
private frozen tensor copies. Deadlines/cancellation are cooperative around native
forwards, not interruption of a running kernel. No fitting or downloading occurs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import stat
import sys
import threading
import time

from . import source_embeddings_768 as reference
from . import source_embeddings_768_complete as complete

SCHEMA = "gte-native-device-embedding-production/v1"
RECEIPT_SCHEMA = "gte-native-device-embedding-receipt/v1"
DIMENSION = 768
FALSE = {"training_executed": False, "download_executed": False,
         "ir_decoder_executed": False, "source_semantics_verified": False,
         "proof_authority": False, "execution_authority": False,
         "promotion_performed": False}
_require = reference._require


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _implementation():
    return {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ("device_session", __file__), ("complete_loader", complete.__file__),
        ("reference_producer", reference.__file__), ("asset_profile", reference._PROFILE.__file__))}


_IMPLEMENTATION_AT_IMPORT = _implementation()


@dataclass(frozen=True)
class SourceEmbeddingDeviceLimits768:
    """Admission ceilings, not a promise that a maximum context fits hardware."""
    max_rows: int = 128
    max_batch_size: int = 16
    max_total_tokens: int = 32768
    max_padded_tokens: int = 8192
    max_attention_cells: int = 8388608

    def __post_init__(self):
        for name, ceiling in (("max_rows", 4096), ("max_batch_size", 16),
                              ("max_total_tokens", 262144), ("max_padded_tokens", 131072),
                              ("max_attention_cells", 67108864)):
            value = getattr(self, name)
            _require(type(value) is int and 1 <= value <= ceiling,
                     name + " must be a bounded positive integer")


def _device(torch, optimized):
    return "cuda:" + str(torch.cuda.current_device()) if optimized and torch.cuda.is_available() else "cpu"


def _deadline(seconds):
    _require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 120,
             "timeout_seconds must be finite in (0,120]")
    return time.monotonic() + seconds


def _checkpoint(deadline, cancel_event):
    if cancel_event is not None:
        _require(callable(getattr(cancel_event, "is_set", None)), "cancel_event must expose is_set")
        if cancel_event.is_set():
            raise InterruptedError("native embedding cancelled")
    if time.monotonic() >= deadline:
        raise TimeoutError("native embedding operation deadline exceeded")


class _AssetCustody:
    """Descriptors established before full SHA inspection, never a public token."""
    def __init__(self, manifest_path, model_directory, code_directory):
        profile = reference._PROFILE
        self.roots = {"model": profile._absolute(model_directory, "model_directory"),
                      "code": profile._absolute(code_directory, "code_directory")}
        manifest = profile._absolute(manifest_path, "manifest_path")
        self.files = []
        try:
            paths = [manifest] + [self.roots[role] / name for role, name in sorted(profile.PUBLISHED_ASSETS)]
            for path in paths:
                fd = profile._open_file(path)
                try:
                    info = os.fstat(fd)
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                             "private custody requires ordinary nonaliased asset files")
                    self.files.append((path, fd, profile._identity(info), info.st_mode, info.st_nlink))
                except BaseException:
                    os.close(fd)
                    raise
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        profile = reference._PROFILE
        for path, fd, identity, mode, links in self.files:
            held, current = os.fstat(fd), profile._file_stat(path)
            _require(profile._identity(held) == identity == profile._identity(current)
                     and held.st_mode == current.st_mode == mode
                     and held.st_nlink == current.st_nlink == links == 1,
                     "native embedding asset custody changed")
        for role, root in self.roots.items():
            _require(profile._directory(root), "native embedding asset directory disappeared")
            profile._scan_root(root, role)

    def close(self):
        errors = []
        for _, fd, *_ in self.files:
            try:
                os.close(fd)
            except OSError as error:
                errors.append(error)
        self.files = []
        if errors:
            raise errors[0]


def _method(value):
    return getattr(value, "__func__", value)


def _tokenizer_guard(tokenizer):
    _require(tokenizer.padding_side == "right", "right padding required")
    backend = tokenizer.backend_tokenizer
    text = backend.to_str()
    _require(type(text) is str and len(text.encode("utf-8")) <= reference._PROFILE.MAX_JSON_BYTES,
             "bounded native tokenizer serialization required")
    return (id(tokenizer), id(backend), type(tokenizer), _method(tokenizer.encode), _method(tokenizer.pad),
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            hashlib.sha256(_wire(tokenizer.special_tokens_map)).hexdigest(),
            tokenizer.padding_side, tokenizer.truncation_side, tokenizer.model_max_length)


def _model_guard(model):
    hooks = ("_forward_hooks", "_forward_pre_hooks", "_backward_hooks")
    return (hashlib.sha256(_wire(model.config.to_dict())).hexdigest(), tuple(
        (name, id(module), type(module), _method(module.forward), module.extra_repr(),
         tuple(sorted((key, value) for key, value in vars(module).items()
                      if type(value) in (type(None), bool, int, float, str))),
         tuple((field, tuple((key, id(value)) for key, value in getattr(module, field).items()))
               for field in hooks)) for name, module in model.named_modules()),
        tuple((name, id(value)) for name, value in model.named_parameters()),
        tuple((name, id(value)) for name, value in model.named_buffers()))


def _precision(torch):
    return {"float32_matmul_precision": torch.get_float32_matmul_precision(),
            "cuda_matmul_allow_tf32": bool(torch.backends.cuda.matmul.allow_tf32),
            "cudnn_allow_tf32": bool(torch.backends.cudnn.allow_tf32),
            "cudnn_deterministic": bool(torch.backends.cudnn.deterministic)}


class SourceEmbeddingDeviceSession768:
    """A single PID/thread owns admitted model, tokenizer and open asset custody."""
    def __init__(self, *, manifest_path, expected_manifest_sha256, model_directory,
                 code_directory, optimized=True, limits=None, cancel_event=None,
                 timeout_seconds=120):
        _require(type(optimized) is bool, "optimized must be boolean")
        _require(limits is None or type(limits) is SourceEmbeddingDeviceLimits768,
                 "limits must be exact SourceEmbeddingDeviceLimits768")
        # Freeze caller inputs once before custody or any executable asset load.
        # A custom PathLike must not select different roots on a second call.
        profile = reference._PROFILE
        manifest_path = profile._absolute(manifest_path, "manifest_path")
        model_directory = profile._absolute(model_directory, "model_directory")
        code_directory = profile._absolute(code_directory, "code_directory")
        profile._sha(expected_manifest_sha256, "expected manifest SHA256")
        owned_limits = SourceEmbeddingDeviceLimits768(**asdict(limits)) if limits is not None else SourceEmbeddingDeviceLimits768()
        deadline = _deadline(timeout_seconds)
        _checkpoint(deadline, cancel_event)
        self._limits = owned_limits
        self._process, self._thread = os.getpid(), threading.get_ident()
        self._closed, self._failed, self._active = False, False, False
        self._custody, self._model, self._reference, self._buffer_reference = None, None, {}, {}
        self._optimized = optimized
        self._dense_path_verified = False
        try:
            self._custody = _AssetCustody(manifest_path, model_directory, code_directory)
            self._assets = reference._PROFILE.inspect_local_assets(manifest_path,
                expected_sha256=expected_manifest_sha256, model_directory=model_directory,
                code_directory=code_directory)
            _require(self._assets["status"] == "available", "complete native model assets unavailable")
            self._custody.check()
            _checkpoint(deadline, cancel_event)
            import torch
            _require(torch.get_num_threads() == 1, "caller must reserve CPU and set torch.set_num_threads(1)")
            self._torch, self._tokenizer, self._model, self._loading = complete._load_backend(self._assets)
            _require(self._torch is torch, "native loader returned foreign tensor runtime")
            self._device = _device(torch, optimized)
            self._model.to(device=self._device, dtype=torch.float32)
            self._model.eval()
            self._reference = {name: value.detach().clone() for name, value in self._model.state_dict().items()}
            # Rotary/position buffers are intentionally absent from safetensors
            # state_dict, but affect numerical execution and must stay frozen.
            self._buffer_reference = {name: self._reference[name] if name in self._reference
                                      else value.detach().clone()
                                      for name, value in self._model.named_buffers()}
            self._model_identity = _model_guard(self._model)
            self._tokenizer_identity = _tokenizer_guard(self._tokenizer)
            self._precision_identity = _precision(torch)
            self._pins = dict(_IMPLEMENTATION_AT_IMPORT)
            self._profile_id = (f"{reference._PROFILE.MODEL_REPO}@{reference._PROFILE.MODEL_REV}:"
                f"code={reference._PROFILE.CODE_REV}:d768:pool=cls:norm=l2:"
                f"{self._device.split(':')[0]}:float32:eager:tokens8192:reject_overlength:"
                f"precision={hashlib.sha256(_wire(self._precision_identity)).hexdigest()}:device-session-v1")
            _checkpoint(deadline, cancel_event)
            self._check()
            _require(time.monotonic() < deadline, "native embedding admission deadline exceeded")
        except BaseException:
            self._release()
            raise

    def _owner(self):
        _require(not self._closed, "native embedding device session is closed")
        _require(os.getpid() == self._process, "native embedding session cannot cross PID/fork")
        _require(threading.get_ident() == self._thread, "native embedding session cannot cross thread")

    def _check(self):
        self._owner()
        _require(_implementation() == self._pins, "native embedding implementation changed")
        torch, model = self._torch, self._model
        _require(torch.get_num_threads() == 1 and _precision(torch) == self._precision_identity,
                 "native embedding execution precision/thread configuration changed")
        _require(not any(torch.is_autocast_enabled(kind) for kind in ("cpu", "cuda")),
                 "native float32 embedding cannot run under autocast")
        _require(_tokenizer_guard(self._tokenizer) == self._tokenizer_identity,
                 "native embedding tokenizer changed")
        _require(_model_guard(model) == self._model_identity
                 and not any(module.training for module in model.modules()),
                 "native embedding model structure/configuration changed")
        state = model.state_dict()
        _require(set(state) == set(self._reference) and all(
            value.shape == self._reference[name].shape and value.dtype == self._reference[name].dtype
            and str(value.device) == self._device and torch.equal(value, self._reference[name])
            for name, value in state.items()), "native embedding model tensor values changed")
        buffers = dict(model.named_buffers())
        _require(set(buffers) == set(self._buffer_reference) and all(
            value.shape == self._buffer_reference[name].shape
            and value.dtype == self._buffer_reference[name].dtype and str(value.device) == self._device
            and torch.equal(value, self._buffer_reference[name]) for name, value in buffers.items()),
            "native embedding nonpersistent buffer values changed")
        # This is last: native config/tokenizer/state callbacks precede file custody.
        self._custody.check()

    def _description(self):
        return {"schema": "source-embedding-device-768/v1", "profile_id": self._profile_id,
            "dimension": DIMENSION, "model_id": reference._PROFILE.MODEL_REPO,
            "model_revision": reference._PROFILE.MODEL_REV, "code_revision": reference._PROFILE.CODE_REV,
            "device": self._device, "optimized": self._optimized, "dtype": "float32",
            "pooling": "cls", "normalization": "l2", "attention_implementation": "eager",
            "max_tokens_including_special_tokens": reference.MAX_TOKENS, "overlength_policy": "reject",
            "limits": asdict(self._limits), "implementation": dict(self._pins),
            "precision": dict(self._precision_identity), "asset_manifest_sha256": self._assets["manifest_sha256"],
            "asset_admission": "full_sha256_once_with_held_nofollow_file_custody",
            "closing_checks": "file_custody_and_exact_native_model_and_tokenizer",
            "maximum_context_numerics_verified": False, **FALSE}

    def describe(self):
        self._owner()
        _require(not self._active and not self._failed, "native embedding session unavailable for operation")
        self._check()
        result = self._description()
        result["profile_sha256"] = hashlib.sha256(_wire(result)).hexdigest()
        return result

    def _inputs(self, batch):
        torch, tokenizer = self._torch, self._tokenizer
        inputs = tokenizer.pad(batch, padding=True, return_tensors="pt")
        _require(type(inputs) is dict or hasattr(inputs, "keys"), "native token mapping required")
        _require(set(inputs) == {"input_ids", "attention_mask"}, "closed native token fields required")
        width = max(len(row["input_ids"]) for row in batch)
        for key, value in inputs.items():
            _require(isinstance(value, torch.Tensor) and value.dtype == torch.long
                     and tuple(value.shape) == (len(batch), width), "native token tensor shape/dtype differs")
        for i, row in enumerate(batch):
            _require(inputs["input_ids"][i].tolist() == row["input_ids"] +
                     [tokenizer.pad_token_id] * (width - len(row["input_ids"]))
                     and inputs["attention_mask"][i].tolist() == row["attention_mask"] +
                     [0] * (width - len(row["input_ids"])), "native padding changed exact token inputs")
        result = {key: value.to(self._device) for key, value in inputs.items()}
        _require(all(str(value.device) == self._device for value in result.values()),
                 "actual native token input device differs")
        return result

    def _hidden(self, output, rows, width):
        value = output.last_hidden_state
        _require(isinstance(value, self._torch.Tensor) and tuple(value.shape) == (rows, width, DIMENSION)
                 and str(value.device) == self._device and value.dtype == self._torch.float32,
                 "actual native forward output shape/device/dtype differs")
        return value

    def infer(self, rows, *, batch_size=16, cancel_event=None, timeout_seconds=120):
        data = reference._source_rows(rows)
        _require(len(data) <= self._limits.max_rows, "source row session limit exceeded")
        _require(type(batch_size) is int and 1 <= batch_size <= self._limits.max_batch_size,
                 "batch_size must be within session limit")
        deadline = _deadline(timeout_seconds)
        self._owner()
        _require(not self._active and not self._failed, "native embedding session unavailable for operation")
        self._active = True
        try:
            _checkpoint(deadline, cancel_event)
            self._check()
            tokens = reference._tokenize(data, self._tokenizer, self._model.config.vocab_size)
            _require(sum(len(row["input_ids"]) for row in tokens) <= self._limits.max_total_tokens,
                     "source request exceeds session total token budget")
            batches = []
            for start in range(0, len(tokens), batch_size):
                batch = tokens[start:start + batch_size]
                width = max(len(row["input_ids"]) for row in batch)
                _require(len(batch) * width <= self._limits.max_padded_tokens
                         and len(batch) * width * width <= self._limits.max_attention_cells,
                         "native batch padded token/attention budget exceeded")
                batches.append(batch)
            # All rows/batches admitted before the first native forward.
            vectors, observations, probe = [], [], None
            torch = self._torch
            with torch.inference_mode():
                for batch in batches:
                    _checkpoint(deadline, cancel_event)
                    inputs = self._inputs(batch)
                    saved = {key: value.clone() for key, value in inputs.items()}
                    width = inputs["input_ids"].shape[1]
                    if not self._dense_path_verified:
                        complete_hidden = self._hidden(self._model(**inputs), len(batch), width)
                        encoder_hidden = self._hidden(self._model.new(**inputs), len(batch), width)
                        _require(torch.equal(complete_hidden, encoder_hidden), "complete checkpoint changed native dense path")
                        probe = {"rows": len(batch), "tokens_per_row": width, "native_forward_calls": 2,
                                 "bitwise_equal": True, "input_device": self._device, "output_device": self._device}
                        self._dense_path_verified = True
                        del complete_hidden, encoder_hidden
                    hidden = self._hidden(self._model(**inputs), len(batch), width)
                    _require(all(torch.equal(value, saved[key]) for key, value in inputs.items()),
                             "native forward mutated exact token inputs")
                    cls = hidden[:, 0, :]
                    norms = torch.linalg.vector_norm(cls, dim=1, keepdim=True)
                    _require(bool(torch.isfinite(cls).all()) and bool(torch.isfinite(norms).all())
                             and bool((norms > 0).all()), "native CLS values/norms must be finite and nonzero")
                    part = (cls / norms).detach().cpu().tolist()
                    _require(all(len(v) == DIMENSION and all(math.isfinite(x) for x in v)
                                 and abs(math.hypot(*v) - 1.) <= 1e-4 for v in part),
                             "native normalized vectors must be finite 768D unit vectors")
                    vectors.extend(part)
                    observations.append({"rows": len(batch), "tokens_per_row": width,
                        "input_device": self._device, "output_device": str(hidden.device),
                        "output_dtype": str(hidden.dtype), "output_shape": list(hidden.shape),
                        "native_forward_calls": 1})
                    _checkpoint(deadline, cancel_event)
            profile = self._description()
            profile_sha256 = hashlib.sha256(_wire(profile)).hexdigest()
            profile["profile_sha256"] = profile_sha256
            receipts = [{"schema": RECEIPT_SCHEMA, "id": row["id"], "source_sha256": row["source_sha256"],
                "profile_id": self._profile_id, "dimension": DIMENSION, "embedding": list(vector),
                "profile_sha256": profile_sha256,
                "embedding_sha256": hashlib.sha256(_wire(vector)).hexdigest(),
                "token_count_including_special_tokens": len(token["input_ids"]),
                "token_input_sha256": reference._digest(token["input_ids"]),
                "truncated": False, "normalized": True, "asset_manifest_sha256": self._assets["manifest_sha256"],
                "device": self._device, "dtype": "float32", "proof_authority": False,
                "source_semantics_verified": False} for row, token, vector in zip(data, tokens, vectors)]
            versions = {"python": sys.version.split()[0]}
            for dependency in ("torch", "transformers", "tokenizers", "safetensors"):
                try:
                    versions[dependency] = importlib.metadata.version(dependency)
                except importlib.metadata.PackageNotFoundError:
                    versions[dependency] = "unavailable"
            result = {"schema": SCHEMA, "status": "completed", "profile": profile,
                "profile_id": self._profile_id, "input_row_count": len(data), "receipt_count": len(receipts),
                "receipts": receipts, "vectors": vectors, "tokens": tokens,
                "complete_checkpoint_loading": json.loads(_wire(self._loading)), "runtime_versions": versions,
                "actual_forward_batches": observations, "dense_path_verification": probe,
                "cuda_executed": self._device.startswith("cuda:"), "model_inference_executed": True,
                "maximum_context_numerics_verified": False, **FALSE}
            _checkpoint(deadline, cancel_event)
            self._check()
            if time.monotonic() >= deadline:
                raise TimeoutError("native embedding operation deadline exceeded")
            return result
        except BaseException:
            self._failed = True
            raise
        finally:
            self._active = False

    def _release(self):
        try:
            if getattr(self, "_device", "cpu").startswith("cuda:"):
                self._torch.cuda.synchronize(self._device)
        finally:
            try:
                if self._custody is not None:
                    self._custody.close()
            finally:
                self._model, self._reference, self._buffer_reference, self._tokenizer = None, {}, {}, None
                self._closed = True

    def close(self):
        if self._closed:
            return
        self._owner()
        _require(not self._active, "cannot close an active native embedding operation")
        try:
            self._check()
        finally:
            self._release()

    def __enter__(self):
        self._owner()
        return self

    def __exit__(self, exc_type, *unused):
        if exc_type is None:
            self.close()
        else:
            # Release deterministically while preserving the original refusal.
            try:
                self.close()
            except BaseException:
                pass


__all__ = ["SourceEmbeddingDeviceSession768", "SourceEmbeddingDeviceLimits768"]
