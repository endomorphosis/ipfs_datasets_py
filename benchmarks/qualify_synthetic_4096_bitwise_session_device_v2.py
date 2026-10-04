"""Compare complete original and bitwise-v2 synthetic4096 inference sessions.

This finite worker uses the pinned qualified v2 benchmark's ordinary helper
functions, with no producer/class/global mutation. CPU opt-out and admitted
CUDA lanes use one identical untrained fixture. CUDA samples alternate call
order; complete checkpoint, independent reference anchor, value and ownership
checks remain inside every timed public inference call. No Leanstral encoder,
fit, optimizer, remote service, production admission or proof is opened.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gc
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import stat
import statistics
import time
import traceback
from unittest.mock import patch

CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
CLEANUP_SHA = "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c"
HELPERS_SHA = "a2b85c0e05d9fc652e7e3d2fdb99b83407a511a3321fba3d2299c27e797ceb36"
SESSION_PROFILE = "native-4096-source-span-batched-device-float32-cpu-decisions/v2"
BITWISE_SESSION_PROFILE = "native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/v2"
BITWISE_SESSION_SHA = "14678654b927d0b6910fda6a8c82961978a9e7ebc29334aaae6cb2320abc5dc3"
BITWISE_GUARD_SHA = "6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34"
CUDA_GRU_PROFILE = "native-4096-source-span-strict-cuda-float32/v1"
CANONICAL_PROJECTION_PROFILE = "native4096-exact-decisions-separate-numeric-diagnostics/v1"
COUNTS = (1, 16, 32)
MAX_FILE_BYTES = 32 * 1024**2
ROOT_MEMORY_MB, ROOT_GPU_MB = 2048, 512
CHILD_MEMORY_MB, CHILD_GPU_MB = 1024, 256


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()

def _read(path):
    """Read bounded ordinary bytes; reject path replacement during the read."""
    path = Path(path).absolute()
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_FILE_BYTES):
        raise ValueError("bounded single-link ordinary file required: " + str(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(MAX_FILE_BYTES + 1)
        after_open = os.fstat(stream.fileno())
    after = path.lstat()
    identities = [(item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns,
                   item.st_ctime_ns, item.st_nlink) for item in
                  (before, opened, after_open, after)]
    if (any(identity != identities[0] for identity in identities[1:])
            or len(raw) != before.st_size):
        raise ValueError("ordinary file identity changed during read: " + str(path))
    return raw

def _pin(path):
    path = Path(path).absolute()
    raw = _read(path)
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

def _write_raw(path, raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_FILE_BYTES:
        raise ValueError("bounded immutable output bytes required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)
    return _pin(path)

def _write(path, value):
    return _write_raw(path, _wire(value))

def _retain(path, target, role):
    raw = _read(path)
    return {"role": role, "current": _pin(path), "retained_copy": _write_raw(target, raw)}

def _timed_cuda_pair(sessions, texts, vectors, *, reverse_first=False):
    """Four completed samples per lane; each lane runs first twice."""
    labels = ("cuda_batched", "bitwise_cuda_batched")
    samples, latest, orders = {label: [] for label in labels}, {}, []
    for trial in range(4):
        order = labels[::-1] if (bool(trial % 2) != reverse_first) else labels
        orders.append(list(order))
        for label in order:
            session = sessions[label]
            session._synchronize()
            started = time.monotonic()
            latest[label] = session.decode_formal_logic(texts, vectors)
            session._synchronize()
            elapsed = time.monotonic() - started
            if not math.isfinite(elapsed) or elapsed <= 0:
                raise ValueError("positive finite complete-session timing required")
            samples[label].append(elapsed)
    timings = {label: {"samples_seconds_per_call": samples[label],
        "median_seconds": statistics.median(samples[label]), "sample_count": 4,
        "repetitions_per_sample": 1} for label in labels}
    return timings, latest, orders


def _retain_count(helpers, torch, span, output, result, lane, label, session,
                  count, actual, timing, reference_logits, texts, vectors):
    """Retain raw evidence before exact decision and complete numeric joins."""
    entry = {**timing, "result": _write(output / f"head-{label}-batch{count}.json", actual),
        "canonical_rows_match_cpu": False,
        "canonical_projection_profile_id": CANONICAL_PROJECTION_PROFILE,
        "canonical_reference_projection": result["cpu_reference_decision_projections"][str(count)]}
    lane["batches"][str(count)] = entry
    entry["canonical_projection"] = _write(
        output / f"head-{label}-batch{count}-canonical-projection.json", helpers._decision_projection(actual))
    expected = entry["canonical_reference_projection"]
    if ((entry["canonical_projection"]["sha256"], entry["canonical_projection"]["bytes"])
            != (expected["sha256"], expected["bytes"])):
        raise ValueError("synthetic4096 exact CPU/private decisions differ: " + label)
    entry["canonical_rows_match_cpu"] = True
    optimized = label in ("cuda_batched", "bitwise_cuda_batched")
    bitwise = label in ("bitwise_cpu", "bitwise_cuda_batched")
    if actual["cuda_executed"] is not optimized:
        raise ValueError("public inference actual CUDA execution differs: " + label)
    profile = actual["execution_profile"]
    expected_profile = BITWISE_SESSION_PROFILE if bitwise and optimized else SESSION_PROFILE
    if profile["profile_id"] != expected_profile:
        raise ValueError("actual complete session profile differs: " + label)
    if bitwise and profile.get("session_profile_id") != BITWISE_SESSION_PROFILE:
        raise ValueError("new session identity missing from CPU or CUDA opt-out profile")
    guard_mode = ("cuda_bitwise_single_host_decision" if bitwise and optimized else
                  "cuda_single_host_decision" if optimized else "cpu_reference_checks")
    if profile["owned_tensor_currentness"]["mode"] != guard_mode:
        raise ValueError("actual timed full session comparator differs: " + label)
    anchor = profile["reference_byte_currentness"]
    if (anchor["origin"] != "independently_restored_validated_cpu_checkpoint_model"
            or anchor["device_to_cpu_reference_transfers"] != int(optimized)):
        raise ValueError("timed full session lost admitted checkpoint reference byte anchor")
    records = [{"tokens": span.tokenize_source(text), "latent": vector}
               for text, vector in zip(texts[:count], vectors[:count])]
    numeric, numeric_scope = helpers._checked_private_logits(torch, span, session, records)
    entry["logits"] = _write(output / f"head-{label}-batch{count}-logits.json", numeric)
    entry["numeric_scope"] = numeric_scope
    entry["four_logit_max_abs_errors"] = helpers._numeric_errors(torch, reference_logits[count], numeric)


def _equal_nonfinite_pair_controls(torch, guard, bitwise_guard, device):
    """Even equal NaN/Inf bits must refuse because the reference is nonfinite."""
    states, references = {}, {}
    try:
        states = {"adapter": torch.zeros((16, 4096), device=f"cuda:{device}", dtype=torch.float32)}
        references = {name: value.detach().clone() for name, value in states.items()}
        result = []
        for corruption, bits in (("paired_equal_nan_bits", 2143289344), ("paired_equal_inf_bits", 2139095040)):
            states["adapter"].view(torch.int32).data[0, 0] = bits
            references["adapter"].view(torch.int32).data[0, 0] = bits
            observed = [int(values["adapter"].view(torch.int32)[0, 0].detach().cpu())
                        for values in (states, references)]
            if observed != [bits, bits]:
                raise ValueError("actual CUDA paired nonfinite bits differ")
            for optimized, lane, checker in ((False, "cuda_reference", guard.check_owned_tensor_values),
                    (True, "cuda_combined", guard.check_owned_tensor_values),
                    (True, "cuda_bitwise_candidate", bitwise_guard.check_owned_tensor_bytes)):
                try:
                    checker(torch, states, references, optimized=optimized)
                except ValueError as error:
                    result.append({"corruption": corruption, "lane": lane, "optimized": optimized,
                        "state_float32_bits_int32": bits, "reference_float32_bits_int32": bits,
                        "refused": True, "refusal": str(error)})
                else:
                    result.append({"corruption": corruption, "lane": lane, "optimized": optimized,
                        "state_float32_bits_int32": bits, "reference_float32_bits_int32": bits,
                        "refused": False, "refusal": None})
            states["adapter"].view(torch.int32).data[0, 0] = 0
            references["adapter"].view(torch.int32).data[0, 0] = 0
            torch.cuda.synchronize(device)
        return result
    finally:
        states.clear()
        references.clear()


def run(output, configuration, *, admission_timeout_seconds=30):
    include_bitwise_guard = True
    if type(admission_timeout_seconds) is not int or not 1 <= admission_timeout_seconds <= 60:
        raise ValueError("bounded admission wait of 1..60 seconds required")
    if type(include_bitwise_guard) is not bool:
        raise ValueError("explicit optional bitwise primitive flag required")
    output, configuration = Path(output).absolute(), Path(configuration).absolute()
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError("canonical existing output parent required")
    output.mkdir(parents=False)
    started = time.monotonic()
    result = {"schema": "native4096-synthetic-bitwise-session-device-qualification/v2",
        "architecture_fixture_qualified": False, "native_leanstral_qualified": False,
        "production_qualified": False, "proof_authority": False, "execution_attestation": False,
        "kernel_resource_enforcement": False,
        "scope": "untrained synthetic4096 original and bitwise-owned sessions with independent immutable anchors",
        "encoder_calls": 0, "optimizer_steps": 0, "training_calls": 0,
        "optimizer_construction_attempts": 0, "foreign_process_actions": False,
        "persistent_precision_policy_mutated": False, "source_pins": [],
        "head_numerical_fixture_qualified": False,
        "optional_bitwise_primitive_enabled": include_bitwise_guard,
        "bitwise_full_session_fixture_qualified": False,
        "complete_gpu_session_speedups_qualified": False,
        "benchmark_scope": "same-fixture four-lane CPU/originalCUDA/bitwiseV2CPU/bitwiseV2CUDA comparison",
        "binding_check_optimization_does_not_remove_original_boundaries": True,
        "canonical_projection_profile": {
            "profile_id": CANONICAL_PROJECTION_PROFILE,
            "comparison": "exact canonical serialized projection bytes",
            "preserved": "all row fields except known diagnostic numeric values; tokens and facet decisions/indices/offsets/text; statuses/reasons; canonical/formal outputs; input hashes; ablation; syntax and semantic flags",
            "numeric_diagnostic_paths": ["rows[*].minimum_decision_logit_margin",
                "rows[*].span_diagnostics.modality_logits[*]",
                "rows[*].span_diagnostics.facets[*].presence_logit_margin",
                "rows[*].span_diagnostics.facets[*].span_logit_margin"],
            "numeric_diagnostic_presence_and_none_float_profile_preserved": True,
            "raw_numeric_diagnostics_retained": True,
            "complete_four_logit_absolute_tolerance": 5e-5},
        "admission_timeout_seconds": admission_timeout_seconds, "pid": os.getpid(),
        "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "error": None}
    scheduler = lease = session = torch = device = baseline = guard_lease = None
    old_threads, safe_close, setup_complete = None, True, False
    active_sessions, gpu_sessions = {}, {}
    owned_zero_cuda_baseline = False
    cleanup = None
    try:
        sources = output / "producers"
        sources.mkdir()
        cleanup_path = Path(__file__).with_name("qualify_native_768_device.py").absolute()
        helpers_path = Path(__file__).with_name("qualify_synthetic_4096_head_device_v2.py").absolute()
        for role, path in (("benchmark", Path(__file__).absolute()), ("configuration", configuration),
                           ("cuda_cleanup", cleanup_path), ("qualified_v2_helpers", helpers_path)):
            item = _retain(path, sources / (role + "-" + path.name), role)
            result["source_pins"].append(item)
            result[role] = item["current"]
        if (result["configuration"]["sha256"] != CONFIG_SHA or result["cuda_cleanup"]["sha256"] != CLEANUP_SHA
                or result["qualified_v2_helpers"]["sha256"] != HELPERS_SHA):
            raise ValueError("pinned shared configuration or cleanup implementation differs")
        helper_spec = importlib.util.spec_from_file_location("qualified_synthetic4096_v2_helpers", helpers_path)
        helpers = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helpers)
        spec = importlib.util.spec_from_file_location("synthetic4096_bitwise_session_cuda_cleanup", cleanup_path)
        cleanup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cleanup)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
        resource_path = Path(resources.__file__).absolute()
        result["source_pins"].append(_retain(resource_path,
            sources / ("resources-" + resource_path.name), "resources"))
        module_root = resource_path.parent
        package_root = resource_path.parents[2]
        staged_paths = {"head": module_root / "legal_span_4096.py",
            "device_session": module_root / "legal_span_4096_device_inference.py",
            "span": module_root / "legal_span_formula.py",
            "precision": module_root / "legal_span_device_inference.py",
            "batch_primitives": module_root / "legal_span_device_batch_inference.py",
            "dimensional_checkpoint": module_root / "legal_span_dimensions.py",
            "tensor_guard": module_root / "owned_tensor_value_guard.py",
            "checkpoint_guard": module_root / "checkpoint_content_guard.py",
            "codec": module_root / "legal_formula_codec.py",
            "grammar": module_root / "legal_ir_grammar_decoder.py",
            "family_evaluator": module_root / "legal_ir_family_evaluator.py",
            "snapshot_evaluator": module_root / "snapshot_evaluator.py",
            "canonical": package_root / "logic/legal_ir/canonical_contracts.py",
            "cid_utils": package_root / "utils/cid_utils.py",
            "runtime_telemetry": module_root / "runtime_telemetry.py",
            "proof_resource_safety": module_root / "proof_resource_safety.py"}
        if include_bitwise_guard:
            staged_paths["bitwise_primitive_candidate"] = module_root / "owned_tensor_bitwise_guard.py"
        staged_paths["bitwise_device_session"] = module_root / "legal_span_4096_bitwise_device_inference_v2.py"
        staged_pins = {}
        # The source bytes are retained without importing head/span/grammar or
        # running their implementation captures. Admission failures retain the
        # complete intended bundle; no model or numerical work exists yet.
        for role, path in staged_paths.items():
            item = _retain(path, sources / (role + "-" + path.name), role)
            result["source_pins"].append(item)
            staged_pins[role] = item["current"]
        if (staged_pins["bitwise_device_session"]["sha256"] != BITWISE_SESSION_SHA
                or staged_pins["bitwise_primitive_candidate"]["sha256"] != BITWISE_GUARD_SHA):
            raise ValueError("pinned new bitwise session/helper source differs")
        settings = json.loads(_read(configuration))
        scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(
            **settings["persisted_config"], state_path=settings["state_path"],
            lease_ttl_seconds=settings["lease_ttl_seconds"], auto_renew_leases=settings["auto_renew_leases"]))
        result["resources_before"] = scheduler.snapshot()
        lease = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=2,
            memory_mb=ROOT_MEMORY_MB, gpu_memory_mb=ROOT_GPU_MB,
            unified_memory_mb=ROOT_MEMORY_MB + ROOT_GPU_MB, requires_gpu=True,
            timeout=admission_timeout_seconds, request_id="synthetic4096-bitwise-session-device-qualification-v2")
        result["admission"] = lease.to_dict()
        # The scheduler's unchanged pressure sampler can import Torch and
        # initialize a context while reading device properties during admission.
        # Accept that observed bootstrap only with no current tensor allocation.
        # Harness runtime handling occurs immediately after root admission and
        # before any head/span/grammar import or numerical model construction.
        import torch as runtime
        torch = runtime
        result["cuda_initialized_after_scheduler_admission"] = torch.cuda.is_initialized()
        result["cuda_initialized_immediately_after_torch_import"] = torch.cuda.is_initialized()
        result["scheduler_bootstrap_scope"] = {
            "telemetry_context_initialization_permitted": True,
            "source": staged_pins["runtime_telemetry"],
            "call_chain": "resource_scheduler._sample_pressure -> collect_resource_snapshot -> _gpu_snapshot -> _torch_gpu_snapshot -> cuda.get_device_properties",
            "foreign_model_reuse_permitted": False, "preexisting_tensor_allocation_permitted": False,
            "fresh_finite_worker_process_required": True, "execution_attestation": False}
        # Track the default visible device before any query that could lazily
        # initialize CUDA. Backend/default-policy reads are not assumed inert.
        device = 0
        if not torch.cuda.is_available():
            raise RuntimeError("actual CUDA required")
        if not torch.cuda.is_initialized():
            torch.cuda.init()
        device = torch.cuda.current_device()
        result["gpu_allocated_before_owned_sessions_bytes"] = torch.cuda.memory_allocated(device)
        result["gpu_reserved_before_owned_sessions_bytes"] = torch.cuda.memory_reserved(device)
        result["free_total_device_bytes_before_fixture"] = list(torch.cuda.mem_get_info(device))
        if result["gpu_allocated_before_owned_sessions_bytes"] != 0:
            raise ValueError("fresh admitted worker must own no preexisting CUDA tensor allocation")
        owned_zero_cuda_baseline = True
        old_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        if str(torch.get_default_device()) != "cpu" or torch.get_default_dtype() != torch.float32:
            raise ValueError("unchanged CPU/float32 Torch defaults required")
        result["module_import_context_diagnostics"] = []

        def import_producer(role, module_name):
            before_context = torch.cuda.is_initialized()
            before_allocated = torch.cuda.memory_allocated(device)
            module = importlib.import_module(module_name)
            after_context = torch.cuda.is_initialized()
            after_allocated = torch.cuda.memory_allocated(device)
            result["module_import_context_diagnostics"].append({"role": role,
                "module": module_name, "cuda_initialized_before": before_context,
                "cuda_initialized_after": after_context, "gpu_allocated_before_bytes": before_allocated,
                "gpu_allocated_after_bytes": after_allocated})
            if before_allocated != 0 or after_allocated != 0:
                raise ValueError("producer import allocated CUDA model/tensor state: " + role)
            if _pin(Path(module.__file__).absolute()) != staged_pins[role]:
                raise ValueError("imported producer path/source differs from staged bytes: " + role)
            return module

        namespace = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
        head = import_producer("head", namespace + "legal_span_4096")
        resident = import_producer("device_session", namespace + "legal_span_4096_device_inference")
        span = import_producer("span", namespace + "legal_span_formula")
        precision = import_producer("precision", namespace + "legal_span_device_inference")
        import_producer("batch_primitives", namespace + "legal_span_device_batch_inference")
        import_producer("dimensional_checkpoint", namespace + "legal_span_dimensions")
        guard = import_producer("tensor_guard", namespace + "owned_tensor_value_guard")
        import_producer("checkpoint_guard", namespace + "checkpoint_content_guard")
        import_producer("codec", namespace + "legal_formula_codec")
        import_producer("grammar", namespace + "legal_ir_grammar_decoder")
        import_producer("family_evaluator", namespace + "legal_ir_family_evaluator")
        import_producer("snapshot_evaluator", namespace + "snapshot_evaluator")
        import_producer("canonical", "ipfs_datasets_py.logic.legal_ir.canonical_contracts")
        import_producer("cid_utils", "ipfs_datasets_py.utils.cid_utils")
        import_producer("runtime_telemetry", namespace + "runtime_telemetry")
        import_producer("proof_resource_safety", namespace + "proof_resource_safety")
        bitwise_guard = (import_producer("bitwise_primitive_candidate", namespace + "owned_tensor_bitwise_guard")
                         if include_bitwise_guard else None)
        bitwise_resident = import_producer("bitwise_device_session", namespace + "legal_span_4096_bitwise_device_inference_v2")
        if (bitwise_resident.PROFILE != BITWISE_SESSION_PROFILE
                or bitwise_resident.CUDA_GRU_PROFILE != CUDA_GRU_PROFILE):
            raise ValueError("separate optimized-binding bitwise-v2 session profile required")
        result["gpu_allocated_after_producer_imports_bytes"] = torch.cuda.memory_allocated(device)
        result["producer_imports_preserved_zero_cuda_allocation"] = (
            result["gpu_allocated_after_producer_imports_bytes"] == 0)
        if resident.PROFILE != SESSION_PROFILE or resident.CUDA_GRU_PROFILE != CUDA_GRU_PROFILE:
            raise ValueError("independently anchored v2 private session required")
        policy_before = precision._cuda_float32_policy(torch)
        result["initial_cuda_kernel_output"] = helpers._initial_kernel(torch, device)
        result["actual_initial_cuda_kernel"] = True
        result["hardware"] = {"torch": str(torch.__version__), "cuda_runtime": torch.version.cuda,
                              "device": torch.cuda.get_device_name(device), "device_index": device}
        torch.cuda.reset_peak_memory_stats(device)
        texts = ["Lark must retain books."] + [f"Worker{i} may publish records." for i in range(1, 32)]
        vectors = [[0.0001] * 4096 for _ in texts]
        for index, vector in enumerate(vectors):
            vector[4095] = float(index + 1) / 32
        rows = [{"id": f"synthetic4096-{i}", "source_text": text, "latent": vector}
                for i, (text, vector) in enumerate(zip(texts, vectors))]
        training = [{**rows[0], "canonical_ir": {"rules": [{"actor": "Lark", "modality": "O",
            "action": "retain", "object": "books", "conditions": [], "exceptions": [], "temporal": []}]}}]
        context = {"dimension": 4096, "representation_id": "synthetic-4096-untrained-architecture-control",
                   "producer_sha256": hashlib.sha256(b"authored synthetic vectors; no encoder").hexdigest(),
                   "training_index_sha256": span.checkpoint_digest(training)}

        def forbid_optimizer(*args, **kwargs):
            result["optimizer_construction_attempts"] += 1
            raise AssertionError("optimizer construction forbidden during fixture qualification")

        def forbid_training(*args, **kwargs):
            result["training_calls"] += 1
            raise AssertionError("training forbidden during fixture qualification")

        with patch.object(torch.optim, "Adam", forbid_optimizer), patch.object(head, "train_decoder", forbid_training):
            checkpoint = head.build_synthetic_fixture(training, context_contract=context,
                hidden_size=8, embedding_dim=4, projection_width=4, batch_size=1, seed=1729)
            checkpoint_sha = span.checkpoint_digest(checkpoint)
            adam_sha = span.checkpoint_digest(checkpoint["optimizer_state"])
            result["checkpoint"] = _write(output / "synthetic-untrained-checkpoint.json", checkpoint)
            result["rows"] = _write(output / "synthetic-inputs.json", rows)
            result["latent_adapter_shape"] = [4, 4096]
            result["zero_output_adapter"] = True
            result["latent_conditioning_trained"] = False
            baseline = head.Leanstral4096SpanDecoder(checkpoint)
            result["cpu_reference_numeric_profile"] = {
                "device": "cpu", "dtype": "float32",
                "numeric_batching": "actual_singleton_forwards_concatenated",
                "equal_fixture_token_width_required": True,
                "used_for_four_logit_parity": True}
            references, reference_logits = {}, {}
            for count in COUNTS:
                with torch.inference_mode():
                    references[count] = baseline.decode_formal_logic(texts[:count], vectors[:count])
                result.setdefault("cpu_reference_results", {})[str(count)] = _write(
                    output / f"head-cpu-reference-batch{count}.json", references[count])
                result.setdefault("cpu_reference_decision_projections", {})[str(count)] = _write(
                    output / f"head-cpu-reference-batch{count}-canonical-projection.json",
                    helpers._decision_projection(references[count]))
                records = [{"tokens": span.tokenize_source(text), "latent": vector}
                           for text, vector in zip(texts[:count], vectors[:count])]
                reference_logits[count] = helpers._reference_logits(torch, span, baseline, records)
                result.setdefault("cpu_reference_logits", {})[str(count)] = _write(
                    output / f"head-cpu-singleton-reference-batch{count}-logits.json", reference_logits[count])
            result["lanes"] = {}
            def start_session(label, session_class, optimized):
                session_started = time.monotonic()
                owned = session_class(checkpoint, expected_checkpoint_sha256=checkpoint_sha,
                    optimized=optimized, synthetic_unreceipted=True,
                    scheduler=scheduler, parent_lease=lease,
                    memory_mb=CHILD_MEMORY_MB, gpu_memory_mb=CHILD_GPU_MB,
                    unified_memory_mb=CHILD_MEMORY_MB + CHILD_GPU_MB,
                    admission_timeout_seconds=admission_timeout_seconds, max_seconds=120)
                active_sessions[label] = owned
                if owned._device != (f"cuda:{device}" if optimized else "cpu"):
                    raise ValueError("requested CPU/CUDA lane device differs: " + label)
                result["lanes"][label] = {"profile": owned.describe(),
                    "constructor_seconds": time.monotonic() - session_started, "batches": {},
                    "timing_scope": "complete public decode with checkpoint/immutable anchor/value/ownership checks",
                    "comparator_changed_only": label.startswith("bitwise_")}
                return owned

            def finish_session(label, owned):
                lane = result["lanes"][label]
                lane["paired_reference_corruption_refusals"] = helpers._paired_reference_refusals(owned, texts, vectors)
                lane["model_only_subnormal_control"] = helpers._model_only_subnormal_control(owned, texts, vectors)
                lane["final_profile"] = owned.describe()
                owned.close()
                lane["own_child_lease_released"] = owned._lease.released
                if lane["own_child_lease_released"] is not True:
                    raise ValueError("owned complete session child lease did not close: " + label)
                active_sessions.pop(label)

            for label, session_class in (("cpu", resident.DeviceLeanstral4096SpanSession),
                    ("bitwise_cpu", bitwise_resident.BitwiseDeviceLeanstral4096SpanSession)):
                session = start_session(label, session_class, False)
                lane = result["lanes"][label]
                for count in COUNTS:
                    session.decode_formal_logic(texts[:count], vectors[:count])
                    timing, actual = helpers._timed(
                        lambda: session.decode_formal_logic(texts[:count], vectors[:count]))
                    _retain_count(helpers, torch, span, output, result, lane, label, session,
                                  count, actual, timing, reference_logits, texts, vectors)
                finish_session(label, session)
                session = None
            gpu_sessions["cuda_batched"] = start_session(
                "cuda_batched", resident.DeviceLeanstral4096SpanSession, True)
            gpu_sessions["bitwise_cuda_batched"] = start_session(
                "bitwise_cuda_batched", bitwise_resident.BitwiseDeviceLeanstral4096SpanSession, True)
            result["cuda_pair_timing_profile"] = {
                "scope": "same fixture and finite worker; separately admitted private models; serial completed public calls",
                "sample_count_per_lane_per_batch": 4, "each_lane_first_per_batch": 2,
                "native_forwards_overlap": False, "source_guard_or_anchor_boundary_removed": False,
                "batches": {}}
            for position, count in enumerate(COUNTS):
                for label, owned in gpu_sessions.items():
                    owned.decode_formal_logic(texts[:count], vectors[:count])
                timings, actuals, orders = _timed_cuda_pair(
                    gpu_sessions, texts[:count], vectors[:count], reverse_first=bool(position % 2))
                result["cuda_pair_timing_profile"]["batches"][str(count)] = {"completed_call_orders": orders}
                for label, owned in gpu_sessions.items():
                    _retain_count(helpers, torch, span, output, result, result["lanes"][label],
                                  label, owned, count, actuals[label], timings[label], reference_logits, texts, vectors)
            for label, owned in list(gpu_sessions.items()):
                finish_session(label, owned)
            gpu_sessions.clear()
            session = owned = None
            baseline = None

            def ratios(left, right):
                return {str(count): result["lanes"][left]["batches"][str(count)]["median_seconds"] /
                        result["lanes"][right]["batches"][str(count)]["median_seconds"] for count in COUNTS}

            result["full_session_speedups_v2_cuda_over_bitwise_cuda"] = ratios("cuda_batched", "bitwise_cuda_batched")
            result["full_session_speedups_v2_cpu_over_bitwise_cpu"] = ratios("cpu", "bitwise_cpu")
            result["head_warm_speedups_cpu_over_cuda_batched"] = ratios("cpu", "cuda_batched")
            result["head_warm_speedups_cpu_over_bitwise_cuda_batched"] = ratios("cpu", "bitwise_cuda_batched")
            result["head_warm_speedups_bitwise_cpu_over_bitwise_cuda_batched"] = ratios("bitwise_cpu", "bitwise_cuda_batched")
            result["bitwise_full_session_faster_batches"] = [count for count, speedup in
                result["full_session_speedups_v2_cuda_over_bitwise_cuda"].items() if speedup > 1.0]
            result["bitwise_full_session_speedup_demonstrated"] = bool(result["bitwise_full_session_faster_batches"])
            result["head_numerical_fixture_qualified"] = True
            result["guard_admission"] = None
            guard_lease = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1,
                memory_mb=CHILD_MEMORY_MB, gpu_memory_mb=CHILD_GPU_MB,
                unified_memory_mb=CHILD_MEMORY_MB + CHILD_GPU_MB, requires_gpu=True,
                parent_lease=lease, timeout=admission_timeout_seconds,
                request_id="synthetic4096-native-tensor-guard-v2")
            result["guard_admission"] = guard_lease.to_dict()
            result["guard"] = helpers._guard_body(torch, guard, device, bitwise_guard)
            result["guard"]["candidate_integrated_into_timed_head_session"] = True
            result["guard"]["integration_scope"] = ["bitwise_cpu", "bitwise_cuda_batched"]
            result["guard"]["native_equal_nonfinite_pair_refusals"] = _equal_nonfinite_pair_controls(
                torch, guard, bitwise_guard, device)
            result["qualification_refusals"] = ["standalone guard accepted corruption: " + lane
                for lane, accepted in result["guard"]["lane_integrity_qualified"].items() if not accepted]
            result["qualification_refusals"].extend("session accepted model-only subnormal: " + lane
                for lane, profile in result["lanes"].items()
                if not profile["model_only_subnormal_control"]["refused"])
            result["qualification_refusals"].extend("standalone guard accepted equal nonfinite bits: " + item["lane"]
                for item in result["guard"]["native_equal_nonfinite_pair_refusals"] if not item["refused"])
            gc.collect()
            torch.cuda.synchronize(device)
            guard_lease.release()
            result["guard_child_lease_released"] = guard_lease.released
            guard_lease = None
            result["checkpoint_unchanged"] = span.checkpoint_digest(checkpoint) == checkpoint_sha
            result["adam_unchanged"] = span.checkpoint_digest(checkpoint["optimizer_state"]) == adam_sha
            if (not result["checkpoint_unchanged"] or not result["adam_unchanged"]
                    or checkpoint["progress"]["optimizer_steps"] != 0):
                raise ValueError("synthetic checkpoint/Adam changed or fixture was trained")
            if result["optimizer_construction_attempts"] or result["training_calls"]:
                raise ValueError("optimizer/training interception was invoked")
        result["precision_policy_before"] = policy_before
        result["precision_policy_after"] = precision._cuda_float32_policy(torch)
        if result["precision_policy_after"] != policy_before:
            raise ValueError("benchmark changed persistent CUDA precision policy")
        result["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
        result["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
        setup_complete = True
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        baseline = None
        for label, owned in list(active_sessions.items()):
            try:
                owned.close()
                result.setdefault("remaining_session_child_leases_released", {})[label] = (
                    owned._lease is None or owned._lease.released)
            except BaseException as error:
                safe_close = False
                result.setdefault("close_errors", []).append(
                    {"lane": label, "type": type(error).__name__, "message": str(error)})
        active_sessions.clear()
        gpu_sessions.clear()
        session = owned = None
        gc.collect()
        if torch is not None and guard_lease is not None:
            try:
                if device is not None:
                    torch.cuda.synchronize(device)
                guard_lease.release()
                result["guard_child_lease_released"] = guard_lease.released
            except BaseException as error:
                safe_close = False
                result["guard_close_error"] = {"type": type(error).__name__, "message": str(error)}
        if torch is not None and cleanup is not None:
            if not owned_zero_cuda_baseline:
                safe_close = False
                result["cuda_cleanup_status"] = "refused_without_admitted_zero_allocation_baseline"
                result["foreign_context_workspace_clear_attempted"] = False
            else:
                try:
                    cleanup._cleanup_owned_cuda(torch, device, result)
                except BaseException as error:
                    safe_close = False
                    result["cuda_cleanup_error"] = {"type": type(error).__name__, "message": str(error)}
            if old_threads is not None:
                try:
                    torch.set_num_threads(old_threads)
                    result["cpu_threads_restored"] = torch.get_num_threads() == old_threads
                except BaseException as error:
                    safe_close = False
                    result["thread_restore_error"] = {"type": type(error).__name__, "message": str(error)}
        if lease is not None:
            try:
                if safe_close:
                    lease.release()
                result["own_root_lease_released"] = lease.released
                result["root_release_does_not_force_child_release"] = True
            except BaseException as error:
                safe_close = False
                result["root_close_error"] = {"type": type(error).__name__, "message": str(error)}
        if scheduler is not None:
            try:
                result["resources_after"] = scheduler.snapshot()
            except BaseException as error:
                safe_close = False
                result["resource_snapshot_error"] = {"type": type(error).__name__, "message": str(error)}
        sources_current = bool(result["source_pins"])
        for item in result["source_pins"]:
            try:
                current, retained = _pin(Path(item["current"]["path"])), _pin(Path(item["retained_copy"]["path"]))
                if (current != item["current"] or retained != item["retained_copy"]
                        or (current["bytes"], current["sha256"]) != (retained["bytes"], retained["sha256"])):
                    raise ValueError("current/retained producer bytes differ")
            except BaseException as error:
                sources_current = False
                result.setdefault("source_currentness_errors", []).append(
                    {"role": item["role"], "type": type(error).__name__, "message": str(error)})
        result["source_bytes_unchanged"] = sources_current
        result["architecture_fixture_qualified"] = bool(setup_complete and safe_close and sources_current
            and result.get("own_root_lease_released") is True and result["error"] is None
            and not result.get("qualification_refusals"))
        result["bitwise_full_session_fixture_qualified"] = result["architecture_fixture_qualified"]
        result["complete_gpu_session_speedups_qualified"] = result["architecture_fixture_qualified"]
        result["elapsed_seconds"] = time.monotonic() - started
        result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        item = _write(output / "result.json", result)
        print(json.dumps({"architecture_fixture_qualified": result["architecture_fixture_qualified"],
                          "result": item, "error": result["error"],
                          "own_root_lease_released": result.get("own_root_lease_released")}))
    return 0 if result["architecture_fixture_qualified"] else 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--admission-timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.configuration, admission_timeout_seconds=args.admission_timeout_seconds))
