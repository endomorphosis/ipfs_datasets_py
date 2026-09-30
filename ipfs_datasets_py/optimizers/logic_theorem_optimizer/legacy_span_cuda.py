"""Immutable legacy CUDA diagnostics for bounded batches of federal spans.

This deliberately uses the historical mock eight-dimensional input contract.
Its embeddings are not semantic evidence. Formula/text outputs belong to the
independent deterministic compiler, not to the learned vector decoder. There
is no optimizer, checkpoint writer, Lake invocation, or publication transport.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import stat
import time
from types import SimpleNamespace
from typing import Any

LEGACY_SHA256 = "7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be"
LEGACY_BYTES = 398209746
MODE = "legacy_mock_diagnostic"
BRIDGE_NAMES = ("modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router")
REPRESENTATION = {
    "embedding_model": "mock:stable-sha256", "dimensions": 8,
    "semantic_embeddings": False,
    "algorithm": "SHA256(normalized_text)[:16] seed; Python Random.uniform(-1,1); round6",
    "historical_runtime_commit": "4f8ec909c82504e64efd5572ca50c7fa2e4f92c0",
    "constituent_training_representation_verified": False,
}
_CPU_PRODUCER_SOURCE: dict[str, Any] | None = None


def _dependencies():
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    tree = require_workspace_logic_tree()
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from .legal_samples import build_us_code_sample
    from .modal_autoencoder import AdaptiveModalAutoencoder, ModalAutoencoderTrainingState, _legal_ir_target_items
    import torch
    package_root = Path(__file__).resolve().parents[2]
    for producer in (AdaptiveModalAutoencoder, ModalAutoencoderTrainingState, build_us_code_sample):
        if package_root not in Path(inspect.getfile(producer)).resolve().parents:
            raise RuntimeError("legacy inference producer imported outside the canonical tree")
    require_workspace_logic_tree()
    return SimpleNamespace(tree=tree, model=AdaptiveModalAutoencoder,
        state=ModalAutoencoderTrainingState, sample=build_us_code_sample,
        session=AutoformalSession, compile=compile_span, target_items=_legal_ir_target_items, torch=torch)


def _logic_target_observation(target: Any) -> dict[str, Any]:
    """Retain source-derived logic artifacts separately from learned outputs.

    A target's acceptance flag is adapter telemetry, never Lake admission.
    Cached summary-only targets must explicitly disclose missing artifacts.
    """
    document = getattr(target, "document", None)
    summary = target.to_dict() if callable(getattr(target, "to_dict", None)) else {}
    document_hash = summary.get("document_hash") if isinstance(summary, Mapping) else None
    if document_hash is None and callable(getattr(document, "canonical_hash", None)):
        document_hash = document.canonical_hash()
    result = {"schema": "legacy-logic-target-observation/v1", "origin": "source_bridge_target",
              "learned_output": False, "bridge_names": list(getattr(target, "bridge_names", ())),
              "document_hash": document_hash, "target_summary": summary,
              "admitted": False, "formalized": False}
    if callable(getattr(document, "to_dict", None)):
        payload = document.to_dict()
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        payload = json.loads(raw)
        result["document_bytes"] = len(raw)
        result["document_sha256"] = hashlib.sha256(raw).hexdigest()
        if len(raw) <= 16 * 1024 * 1024:
            from .legacy_span_logic_artifacts import pack_document
            views = payload.get("views", {})
            result.update(status="captured", document=pack_document(payload),
                          document_encoding="recursive-zlib-json/v1", observed_views=sorted(views),
                          observed_families=sorted({str(view.get("metadata", {}).get("logic_family"))
                              for view in views.values() if isinstance(view, Mapping)
                              and view.get("metadata", {}).get("logic_family")}))
            return result
        reason = "document_exceeds_16mib_decoded_bound"
    else:
        reason = "target_has_no_serializable_document"
    result.update(status="unavailable", reason=reason, document=None, observed_families=[], observed_views=[])
    return result


def _source_snapshot() -> dict[str, Any]:
    """Bind imports to a complete canonical Python producer generation."""
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    candidates = sorted(root.rglob("*.py"))
    paths = []
    for path in candidates:
        if path.is_symlink() or root not in path.resolve().parents:
            raise RuntimeError("producer source must remain inside the canonical tree")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError("producer Python source must be a regular file")
        paths.append(path)
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(bytes.fromhex(_digest(path)))
    return {"package_root": str(root), "python_file_count": len(paths), "sha256": digest.hexdigest()}


def _is_constitution(span: Mapping[str, Any]) -> bool:
    return span.get("constitution_source") is True or any(
        "constitution" in str(span.get(key, "")).lower()
        for key in ("legal_id", "source_span_id", "source_path", "corpus", "dataset_id", "source_url"))


def _constitution_skip() -> dict[str, Any]:
    return {"status": "not_supported_constitution", "compiler_status": "not_run",
            "reason": "constitution_not_formalized", "roundtrip_ok": False,
            "admitted": False, "formalized": False, "learned_formula_generation": False}


def compile_source_span(span: Mapping[str, Any], *, expected_source_sha256: str | None = None) -> dict[str, Any]:
    """Independent CPU-pool task. Returns evidence only; never runs Lake."""
    global _CPU_PRODUCER_SOURCE
    before = _source_snapshot()
    if _CPU_PRODUCER_SOURCE is not None and _CPU_PRODUCER_SOURCE != before:
        raise RuntimeError("persistent compiler process requires a new producer generation")
    _CPU_PRODUCER_SOURCE = before
    if expected_source_sha256 is not None and before["sha256"] != expected_source_sha256:
        raise RuntimeError("compiler producer generation differs from requested source")
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    text, span_id = str(span["text"]), str(span["source_span_id"])
    if _is_constitution(span):
        result = _constitution_skip()
    else:
        try:
            result = dict(compile_span(AutoformalSession(), text, span_id))
        except Exception as error:
            result = {"status": "error", "error_type": type(error).__name__}
    if _source_snapshot() != before:
        raise RuntimeError("compiler source changed during span observation")
    result.update(admitted=False, formalized=False, learned_formula_generation=False)
    return {"source_span_id": span_id, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "producer_source": before, "compiler": result}


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _identity(path: Path) -> tuple[int, int, int, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != LEGACY_BYTES:
        raise ValueError("legacy checkpoint must be the exact regular local canonical artifact")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _widths(state: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, values in vars(state).items():
        if not (name.endswith("embedding_weights") or name == "decoded_embeddings"):
            continue
        if not isinstance(values, Mapping):
            raise ValueError("legacy embedding table is not a mapping")
        for vector in values.values():
            if (not isinstance(vector, (tuple, list)) or len(vector) != 8
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not math.isfinite(value) for value in vector)):
                raise ValueError("legacy checkpoint contains incompatible embedding widths or values")
        counts[name] = len(values)
    if not sum(counts.values()):
        raise ValueError("legacy checkpoint has no embedding vectors")
    return counts


def _defaults(model: Any, model_type: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, parameter in inspect.signature(model_type).parameters.items():
        if name in {"state", "self"} or parameter.default is inspect.Parameter.empty:
            continue
        value = getattr(model, name, parameter.default)
        if name == "compute_device":
            value = "cuda"
        if isinstance(value, tuple):
            value = list(value)
        if value is None or isinstance(value, (bool, str, int, float, list, dict)):
            result[name] = value
        else:
            result[name] = {"type": type(value).__name__}
    return result


def _profile_evaluate(torch: Any, callback):
    """Observe actual CUDA kernels, not merely a requested device string."""
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,
                                           torch.profiler.ProfilerActivity.CUDA]) as profile:
        value = callback()
        torch.cuda.synchronize()
    kernels = [event for event in profile.events()
               if str(event.device_type).rsplit(".", 1)[-1] == "CUDA"]
    report = {"profiled": True, "cuda_kernel_event_count": len(kernels),
              "cuda_device_time_us": sum(float(getattr(event, "device_time_total", 0.0))
                                         for event in kernels)}
    if not kernels:
        raise RuntimeError("CUDA requested but no CUDA kernel events were observed")
    return value, report


class LegacySpanCUDAWorker:
    """One persistent read-only checkpoint owner; dispatch serial bounded batches.

    A controller may own multiple such processes. Do not share an instance
    between threads or fork it after CUDA initialization. No campaign deadline
    is imposed here; the controller owns resources, retries, and resume state.
    """

    def __init__(self, checkpoint: str | Path, *, mode: str = MODE,
                 max_batch_size: int = 32, max_text_chars: int = 16000,
                 legal_ir_parallel_workers: int = 1):
        if mode != MODE:
            raise ValueError("full legacy state requires explicit legacy_mock_diagnostic mode")
        if (type(max_batch_size) is not int or not 1 <= max_batch_size <= 128
                or type(max_text_chars) is not int or not 1 <= max_text_chars <= 65536):
            raise ValueError("invalid bounded batch limits")
        if type(legal_ir_parallel_workers) is not int or not 1 <= legal_ir_parallel_workers <= 8:
            raise ValueError("legal_ir_parallel_workers must be between one and eight")
        self.path = Path(checkpoint).absolute()
        self.identity = _identity(self.path)
        if _digest(self.path) != LEGACY_SHA256:
            raise ValueError("legacy checkpoint digest mismatch")
        os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
        # The campaign is explicitly deadline-free. Keep the same policy in
        # serial and threaded arms; SIGALRM otherwise only applies on one thread.
        os.environ["IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS"] = "0"
        os.environ["IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS"] = "1"
        self.source_identity = _source_snapshot()
        self.dependencies = _dependencies()
        state = self.dependencies.state.load_json(self.path)
        if _identity(self.path) != self.identity or _digest(self.path) != LEGACY_SHA256:
            raise ValueError("legacy checkpoint changed during load")
        self.vector_counts = _widths(state)
        self.model = self.dependencies.model(state=state, compute_device="cuda")
        if self.model.compute_backend != "torch_cuda":
            raise RuntimeError("legacy CUDA worker refuses CPU fallback: " + str(self.model.compute_backend))
        if _source_snapshot() != self.source_identity:
            raise RuntimeError("producer source changed while loading legacy model")
        self.model_config = _defaults(self.model, self.dependencies.model)
        self.max_batch_size, self.max_text_chars = max_batch_size, max_text_chars
        self.legal_ir_parallel_workers = legal_ir_parallel_workers
        self.batches = 0
        self.cuda_initial_profile: dict[str, Any] | None = None

    def _input(self, rows):
        if (not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= self.max_batch_size):
            raise ValueError("batch must contain between one and max_batch_size spans")
        seen, prepared = set(), []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("span must be a mapping")
            values = {name: row.get(name) for name in ("source_span_id", "text", "legal_id")}
            if any(not isinstance(value, str) or not value.strip() for value in values.values()):
                raise ValueError("span requires nonempty source_span_id, text and legal_id strings")
            if (len(values["text"]) > self.max_text_chars or len(values["source_span_id"]) > 1024
                    or len(values["legal_id"]) > 1024 or values["source_span_id"] in seen):
                raise ValueError("span size limit or duplicate source_span_id")
            seen.add(values["source_span_id"])
            values["constitution_source"] = _is_constitution(row)
            prepared.append(values)
        if sum(len(row["text"].encode("utf-8")) for row in prepared) > 1024 * 1024:
            raise ValueError("batch source bytes exceed one MiB")
        return prepared

    def evaluate_batch(self, spans: Sequence[Mapping[str, Any]], *, profile_cuda: bool | None = None,
                       compiler_results: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        rows = self._input(spans)
        guard_started = time.perf_counter()
        if _source_snapshot() != self.source_identity:
            raise RuntimeError("producer source changed between batches; new generation required")
        guard_seconds = time.perf_counter() - guard_started
        if _identity(self.path) != self.identity:
            raise ValueError("legacy checkpoint changed between batches")
        if os.environ.get("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE") != "0":
            raise RuntimeError("legacy diagnostic requires disk metric cache disabled")
        if (os.environ.get("IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS") != "0"
                or os.environ.get("IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS") != "1"):
            raise RuntimeError("legacy diagnostic target timeout or adapter worker policy changed")
        preparation_started = time.perf_counter()
        dep, torch = self.dependencies, self.dependencies.torch
        if compiler_results is not None:
            if set(compiler_results) != {row["source_span_id"] for row in rows}:
                raise ValueError("compiler observations do not match the batch")
            for row in rows:
                result = compiler_results[row["source_span_id"]]
                if (result.get("source_span_id") != row["source_span_id"]
                        or result.get("source_sha256") != hashlib.sha256(row["text"].encode()).hexdigest()
                        or result.get("producer_source") != self.source_identity
                        or not isinstance(result.get("compiler"), Mapping)):
                    raise ValueError("compiler observation source identity mismatch")
        samples, samples_by_span, sample_errors = [], {}, {}
        for row in rows:
            try:
                sample = dep.sample(title=row["legal_id"], section=row["source_span_id"], text=row["text"],
                                    citation=row["legal_id"], embedding_model="mock:stable-sha256")
            except Exception as error:
                sample_errors[row["source_span_id"]] = type(error).__name__
                continue
            samples_by_span[row["source_span_id"]] = (len(samples), sample)
            samples.append(sample)
        if any(sample.embedding_model != "mock:stable-sha256" or len(sample.embedding_vector) != 8
               for sample in samples):
            raise ValueError("legacy diagnostic input representation mismatch")
        preparation_seconds = time.perf_counter() - preparation_started
        torch.cuda.reset_peak_memory_stats()
        kwargs = dict(legal_ir_bridge_names=BRIDGE_NAMES, legal_ir_evaluate_provers=False,
                      legal_ir_parallel_workers=self.legal_ir_parallel_workers, use_sample_memory=False,
                      profile_evaluation=True, reconstruction_objective="raw_decoder")
        evaluate_started = time.perf_counter()
        run_profile = self.cuda_initial_profile is None or profile_cuda is True
        try:
            # Prepare once, retain full artifacts, and give those same objects to
            # evaluate. This avoids another parser/bridge pass for publication.
            target_observation: dict[str, Any] = {}
            targets = dict(dep.target_items(samples, bridge_names=BRIDGE_NAMES,
                evaluate_provers=False, legal_ir_targets=None,
                parallel_workers=self.legal_ir_parallel_workers, observation=target_observation)) if samples else {}
            if set(targets) != {sample.sample_id for sample in samples}:
                raise RuntimeError("bridge target preparation did not cover every sample")
            kwargs["legal_ir_targets"] = targets
            logic_targets = {sample_id: _logic_target_observation(target) for sample_id, target in targets.items()}
            if not samples:
                evaluated = SimpleNamespace(to_dict=lambda: {"sample_count": 0, "legal_ir_target_count": 0,
                                                              "decoded_embeddings": {}})
                cuda_observation = {"profiled": False, "status": "not_run_no_valid_samples"}
            elif run_profile:
                evaluated, cuda_observation = _profile_evaluate(torch, lambda: self.model.evaluate(samples, **kwargs))
                self.cuda_initial_profile = dict(cuda_observation)
            else:
                evaluated = self.model.evaluate(samples, **kwargs)
                torch.cuda.synchronize()
                cuda_observation = {"profiled": False, "initial_batch_profile": self.cuda_initial_profile}
            evaluate_seconds = time.perf_counter() - evaluate_started
            raw = evaluated.to_dict()
            raw["target_preparation_observation"] = target_observation
            if samples and (raw.get("sample_count") != len(samples) or int(raw.get("legal_ir_target_count", 0)) != len(samples)):
                raise RuntimeError("bridge-on inference returned no legal IR targets or incomplete samples")
            projected_started = time.perf_counter()
            projected_vectors = [self.model._decoded_for(sample, use_sample_memory=False,
                                  apply_reconstruction_projection=True) for sample in samples]
            raw_vectors = [raw["decoded_embeddings"][sample.sample_id] for sample in samples]
            projected_cosines, projected_losses, raw_cosines, raw_losses = [], [], [], []
            if samples:
                projected_cosines, projected_losses = self.model._embedding_metrics(
                    [sample.embedding_vector for sample in samples], projected_vectors)
                raw_cosines, raw_losses = self.model._embedding_metrics(
                    [sample.embedding_vector for sample in samples], raw_vectors)
            torch.cuda.synchronize()
            projected_seconds = time.perf_counter() - projected_started
            compiler_started = time.perf_counter()
            output_rows = []
            for row in rows:
                if _is_constitution(row):
                    compiled = _constitution_skip()
                elif compiler_results is not None:
                    compiled = dict(compiler_results[row["source_span_id"]]["compiler"])
                else:
                    try:
                        compiled = dict(dep.compile(dep.session(), row["text"], row["source_span_id"]))
                    except Exception as error:
                        compiled = {"status": "error", "error_type": type(error).__name__}
                # No compiler record is allowed to confer execution/proof authority here.
                compiled.update(admitted=False, formalized=False, learned_formula_generation=False)
                if row["source_span_id"] in sample_errors:
                    output_rows.append({**row, "source_sha256": hashlib.sha256(row["text"].encode()).hexdigest(),
                        "status": "sample_preparation_error", "error_type": sample_errors[row["source_span_id"]],
                        "compiler": compiled, "raw_decoder": None, "safety_projected_decoder": None,
                        "embedding_representation": dict(REPRESENTATION), "admitted": False, "formalized": False,
                        "semantic_qualified": False, "learned_formula_generation": False,
                        "lake": {"status": "not_run", "admitted": False}})
                    continue
                index, sample = samples_by_span[row["source_span_id"]]
                output_rows.append({**row, "sample_id": sample.sample_id,
                    "status": "diagnostic_observed",
                    "source_sha256": hashlib.sha256(row["text"].encode()).hexdigest(),
                    "embedding_representation": dict(REPRESENTATION), "compiler": compiled,
                    "logic_target_observation": logic_targets[sample.sample_id],
                    "raw_decoder": {"embedding": raw_vectors[index], "cosine_similarity": raw_cosines[index],
                                    "reconstruction_loss": raw_losses[index], "safety_projection_used": False},
                    "safety_projected_decoder": {"embedding": projected_vectors[index],
                        "cosine_similarity": projected_cosines[index], "reconstruction_loss": projected_losses[index],
                        "safety_projection_used": True, "target_conditioned": True},
                    "legal_ir_target_hash": raw.get("legal_ir_target_hashes", {}).get(sample.sample_id),
                    "admitted": False, "formalized": False, "semantic_qualified": False,
                    "learned_formula_generation": False, "lake": {"status": "not_run", "admitted": False}})
            compiler_seconds = time.perf_counter() - compiler_started
            guard_started = time.perf_counter()
            if _source_snapshot() != self.source_identity:
                raise RuntimeError("producer source changed during batch; reject observation")
            guard_seconds += time.perf_counter() - guard_started
            elapsed = time.perf_counter() - started
            self.batches += 1
            receipt = {"schema_version": "legacy-span-cuda-diagnostic/v1", "mode": MODE,
                "batch_number": self.batches, "sample_count": len(samples), "requested_span_count": len(rows),
                "sample_error_count": len(sample_errors), "rows": output_rows,
                "checkpoint": {"path": str(self.path), "sha256": LEGACY_SHA256, "bytes": LEGACY_BYTES,
                    "vector_dimensions": 8, "vector_table_counts": self.vector_counts,
                    "runtime_loaded_architecture": getattr(self.model.state, "architecture_version", None)},
                "logic_tree": dep.tree, "producer_source": self.source_identity, "model_config": self.model_config,
                "compute_backend": self.model.compute_backend_metadata(),
                "embedding_representation": dict(REPRESENTATION),
                "raw_evaluation": raw,
                "bridges": {"requested": list(BRIDGE_NAMES), "evaluation_invoked": list(BRIDGE_NAMES) if samples else [],
                    "target_count": raw["legal_ir_target_count"], "evaluate_provers": False,
                    "disk_cache": False, "parallel_workers": self.legal_ir_parallel_workers,
                    "parallel_workers_used": target_observation.get("parallel_workers_used", 0 if not samples else None),
                    "adapter_workers": 1, "native_target_timeout_seconds": 0.0,
                    "native_timeout_fallback_count": target_observation.get("timeout_fallback_count", 0 if not samples else None),
                    "process_metric_caches_may_be_warm": True,
                    "projected_observation_bridge_names": []},
                "cuda": {**cuda_observation, "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                         "peak_reserved_bytes": torch.cuda.max_memory_reserved()},
                "timings": {"elapsed_seconds": elapsed, "wall_seconds_per_span": elapsed / len(rows),
                    "sample_preparation_seconds": preparation_seconds,
                    "bridge_on_evaluate_seconds": evaluate_seconds,
                    "projected_observation_seconds": projected_seconds,
                    "compiler_seconds": compiler_seconds, "producer_guard_seconds": guard_seconds},
                "use_sample_memory": False, "training_executed": False,
                "admitted": False, "formalized": False, "semantic_qualified": False,
                "heldout_canary": False, "temperature": 0}
            return json.loads(json.dumps(receipt, allow_nan=False))
        finally:
            # Bound live per-sample bookkeeping without touching any learned weights.
            for name in ("_sample_feature_cache", "_legal_ir_loss_target_cache", "_legal_ir_view_target_cache"):
                getattr(self.model, name, {}).clear()
