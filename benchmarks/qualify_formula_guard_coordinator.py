"""Bounded retained-trained original/v1/v2 formula guard coordination comparison.

Replay two pinned 30-step checkpoints without fits, encoders or optimizer steps.
Each CPU route is a single numerical reference call per count. CUDA has twelve
three-way balanced observations per route/count; every public report and every
complete learned projection is retained. All producer source/custody checks
remain inside CUDA timings, which have no extra Python call profiler attached.
Source-bound call observations cover construction, references, warmups and
corruption probes only. This is local numerical/measurement evidence, never
execution attestation, production admission, proof or a universal speedup.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import argparse
import gc
import hashlib
import importlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import resource
import stat
import statistics
import sys
import time
import traceback

SCHEMA = "retained-trained-formula-guard-coordinator-qualification/v1"
CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
HELPERS_SHA = "29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110"
CLEANUP_SHA = "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c"
V1_SHA = "5b5631eb1cf779ea8b6fcf3073d074355f52ef8c74adea84fc595421dea85089"
V2_SHA = "ebc7f8242ec3a4852be4c025b4ef818bc48e74add7634935ec403e1bd3c6dfb9"
BIT_GUARD_SHA = "6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34"
BASELINE_SHA = "d178edbced905e3b55d36a067f8f797aa9a95a612f80162e6aaf6c64f9f26f79"
V1_PROFILE = "modal-latent-formula-bitwise-owned-device-float32/v1"
V2_PROFILE = "modal-latent-formula-bitwise-owned-device-float32/v2"
COUNTS, PAIRS, MAX_SECONDS = (1, 16, 32), 12, 120
MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_FILES = 8388608, 67108864, 1024
ROOT_RAM, ROOT_GPU, ROOT_UNIFIED = 3072, 768, 3840
CHILD_RAM, CHILD_GPU, CHILD_UNIFIED = 1024, 256, 1280
PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
CPU_LANES = ("original_cpu_reference", "bitwise_v1_cpu_opt_out", "bitwise_v2_cpu_opt_out")
CUDA_LANES = ("original_cuda", "bitwise_v1_cuda", "bitwise_v2_cuda")
ORDERS = tuple(itertools.permutations(CUDA_LANES)) * 2
SOURCE_NAMES = ("resource_scheduler", "modal_latent_formula", "modal_latent_formula_inference",
    "modal_latent_formula_device_inference", "modal_latent_formula_bitwise_device_inference",
    "modal_latent_formula_bitwise_device_inference_v2", "owned_tensor_value_guard", "owned_tensor_bitwise_guard",
    "checkpoint_content_guard", "runtime_telemetry", "proof_resource_safety", "legal_formula_codec",
    "legal_ir_grammar_decoder", "legal_ir_family_evaluator", "snapshot_evaluator")
FIXTURES = {
    "formula8_checkpoint": ("legal-cuda-device-qualification-20261003-05/legal-8-checkpoint.json",
        "09558c8db4455bf3caad1f287cea9448da47393fe0fae1c5c140f0ff00e0e466"),
    "formula384_checkpoint": ("legal-cuda-device-qualification-20261003-05/legal-384-checkpoint.json",
        "7d8d0e60f7d644bed06e0a48ffc82c014c9ed697d89b9cdc2e4a5d55863885ce"),
    "formula8_training_inputs": ("legal-cuda-device-qualification-20261003-05/legal-8-training-inputs.json",
        "212b4817fd074e9c3f9c76c53485774ad44083b65c691938bb80e2962723a30c"),
    "formula384_training_inputs": ("legal-cuda-device-qualification-20261003-05/legal-384-training-inputs.json",
        "febf18138dbe1bc8480f06d43586a35453db55c3d8493c03a57ed848dab6093f"),
}


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _directory_fd(path):
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for component in Path(path).absolute().parts[1:]:
            _require(component != "..", "canonical directory required")
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read(path):
    path = Path(path).absolute()
    parent = _directory_fd(path.parent)
    try:
        parent_before = os.fstat(parent)
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_FILE_BYTES,
                 "bounded ordinary single-link source required")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_size == before.st_size,
                     "opened source kind/size differs")
            raw = stream.read(MAX_FILE_BYTES + 1)
            after_open = os.fstat(stream.fileno())
        after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        latest_parent = _directory_fd(path.parent)
        try:
            latest = os.fstat(latest_parent)
            _require((latest.st_dev, latest.st_ino) == (parent_before.st_dev, parent_before.st_ino),
                     "source parent changed while reading")
        finally:
            os.close(latest_parent)
    finally:
        os.close(parent)
    identities = [(part.st_dev, part.st_ino, part.st_size, part.st_mtime_ns, part.st_ctime_ns, part.st_nlink)
                  for part in (before, opened, after_open, after)]
    _require(all(part == identities[0] for part in identities[1:]) and len(raw) == before.st_size,
             "source identity changed while reading")
    return raw


def _pin(path, raw=None):
    raw = _read(path) if raw is None else raw
    return {"path": str(Path(path).absolute()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _load_helper(path, name, expected):
    _require(_pin(path)["sha256"] == expected, "fixed ordinary helper bytes differ")
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    _require(_pin(path)["sha256"] == expected, "ordinary helper changed during import")
    return module


def _code_chain(function):
    result, seen = set(), set()
    while function is not None and id(function) not in seen:
        seen.add(id(function))
        code = getattr(function, "__code__", None)
        if code is not None:
            result.add(code)
        function = getattr(function, "__wrapped__", None)
    return result


def _settings(torch):
    """Read process precision/default policy without changing any setting."""
    cudnn = torch.backends.cudnn
    flags = {name: getattr(cudnn, name) for name in
             ("enabled", "benchmark", "benchmark_limit", "deterministic", "allow_tf32")}
    for name in ("fp32_precision", "depthwise_kernel"):
        if hasattr(cudnn, name):
            flags[name] = getattr(cudnn, name)
    return {"cudnn": flags,
        "cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "default_dtype": str(torch.get_default_dtype()),
        "default_device": str(torch.get_default_device()),
        "autocast_cpu_enabled": torch.is_autocast_enabled("cpu"),
        "autocast_cuda_enabled": torch.is_autocast_enabled("cuda"),
        "deterministic_algorithms_enabled": torch.are_deterministic_algorithms_enabled(),
        "deterministic_algorithms_warn_only": torch.is_deterministic_algorithms_warn_only_enabled(),
        "num_threads": torch.get_num_threads()}


@contextmanager
def _probe_observer(torch, native, counters, *, scope, construction=None):
    """Observe bound call code without replacing any producer/framework method."""
    adam = _code_chain(torch.optim.Adam.__init__)
    steps = _code_chain(torch.optim.Adam.step) | _code_chain(torch.optim.Optimizer.step)
    train, fit = _code_chain(torch.nn.Module.train), _code_chain(native.train)
    restore_code = native._restore.__code__
    previous = sys.getprofile()
    seen_adam, seen_restores = 0, 0
    def observed(frame, event, arg):
        nonlocal seen_adam, seen_restores
        if event == "call":
            code = frame.f_code
            if code in adam:
                # Capture the public constructor only once; a wrapped base
                # frame cannot turn one restoration into two attempts.
                if code is torch.optim.Adam.__init__.__code__:
                    seen_adam += 1
                    counters["optimizer_restore_attempts"] += 1
                    if construction is None:
                        raise RuntimeError("unexpected Adam construction in inference probe")
            elif code in steps:
                counters["optimizer_steps"] += 1
                raise RuntimeError("optimizer step forbidden in inference probe")
            elif code in fit:
                counters["training_calls"] += 1
                counters["new_training_fits"] += 1
                raise RuntimeError("fit forbidden in inference probe")
            elif code in train and frame.f_locals.get("mode") is not False:
                counters["training_mode_true_calls"] += 1
                raise RuntimeError("training mode forbidden in inference probe")
        elif (event == "return" and frame.f_code is restore_code
              and type(arg) is tuple and len(arg) == 3 and isinstance(arg[2], torch.optim.Adam)):
            # A successful source-bound native restoration returns the
            # validated model and populated Adam, even if a later upload or
            # owner check refuses. Count that completion independently of
            # whether the enclosing constructor returns an admitted owner.
            seen_restores += 1
            counters["optimizer_constructor_calls"] += 1
            if construction is None:
                raise RuntimeError("unexpected validated Adam restoration in inference probe")
        if previous is not None:
            previous(frame, event, arg)
    sys.setprofile(observed)
    try:
        yield
    finally:
        sys.setprofile(previous)
        if construction is not None:
            construction["adam_restore_attempts"] = seen_adam
            construction["adam_restore_completions"] = seen_restores
            construction["observation_scope"] = scope


def _construct(torch, native, counters, factory, label, *, dimension, checkpoint_sha256):
    receipt = {"route": label, "dimension": dimension, "checkpoint_sha256": checkpoint_sha256,
        "started": True, "completed": False,
        "adam_restore_attempts": 0, "adam_restore_completions": 0,
        "observation_scope": "constructor_only_source_bound_python_call_observer"}
    owner = None
    started = time.monotonic()
    try:
        with _probe_observer(torch, native, counters,
                scope=receipt["observation_scope"], construction=receipt):
            owner = factory()
        _require(receipt["adam_restore_attempts"] == receipt["adam_restore_completions"] == 1,
                 "one validated Adam restoration per formula constructor required")
        receipt["completed"] = True
        return owner
    except BaseException:
        # If an already returned owner fails the constructor-observation
        # contract, close its owned child before dropping it. A constructor
        # that never returned is responsible for its own admission cleanup.
        if owner is not None and callable(getattr(owner, "close", None)):
            owner.close()
        owner = None
        raise
    finally:
        receipt["elapsed_seconds"] = time.monotonic() - started
        counters["constructor_observations"].append(receipt)


def _decisions(report):
    value = deepcopy(report)
    value.pop("inference_implementation")
    for row in value["rows"]:
        margin = row.get("minimum_decision_logit_margin")
        if margin is not None:
            _require(type(margin) is float and math.isfinite(margin), "finite decision margin required")
            row["minimum_decision_logit_margin"] = {"known_finite_numeric_diagnostic_value_excluded": True}
    return value


def run(output, configuration, *, admission_timeout_seconds=30):
    _require(type(admission_timeout_seconds) is int and 1 <= admission_timeout_seconds <= 60,
             "admission timeout must be1..60seconds")
    _require(type(V2_SHA) is str and len(V2_SHA) == 64, "final pinned v2 source required before qualification")
    output, configuration = Path(output).absolute(), Path(configuration).absolute()
    _require(output.parent.resolve(strict=True) == output.parent, "canonical existing output parent required")
    output.mkdir(parents=False)
    began = time.monotonic()
    counters = {"optimizer_restore_attempts": 0, "optimizer_constructor_calls": 0, "optimizer_steps": 0,
        "training_calls": 0, "new_training_fits": 0, "training_mode_true_calls": 0,
        "encoder_calls": 0, "constructor_observations": []}
    result = {"schema": SCHEMA, "qualified": False, "error": None,
        "scope": "retained_trained_formula8_formula384_original_v1_v2_guard_coordinator_comparison",
        "production_qualified": False, "proof_authority": False, "execution_attestation": False,
        "semantic_correctness_verified": False, "fresh_encoder_execution_qualified": False,
        "native_encoder_origin_authenticated": False,
        "kernel_resource_enforcement": False, "universal_speedup_claimed": False,
        "foreign_process_actions": False, "persistent_precision_policy_mutated": False,
        "selected_existing_profile_changed": False,
        "complete_call_measurements_qualified": False, "conservative_complete_call_gain_observed": False,
        "source_pins": [], "fixture_pins": [], "families": {}, "owned_children": [],
        "max_seconds_after_root_admission": MAX_SECONDS, "admission_timeout_seconds": admission_timeout_seconds,
        "cpu_reference_scope": "one_call_per_route_count_no_repeatability_claim",
        "cuda_timing_scope": "complete_guarded_public_inference_and_completion_sync_uninstrumented_input_copy_before_interval_three_way_balanced",
        "counter_observation_scope": "source_bound_python_calls_during_constructors_cpu_references_cuda_warmups_and_controls_only",
        "timed_call_counters_scope": "authored_harness_invocations_and_bound_inference_only_sources_no_execution_attestation",
        "encoder_call_counter_scope": "authored_harness_has_no_encoder_import_or_invocation_no_execution_attestation",
        "optimizer_constructor_counter_scope": "successful_source_bound_native_restore_return_including_later_constructor_failures",
        "canonical_projection_scope": "all_non_execution_report_fields_only_finite_minimum_decision_margin_value_marked",
        "numeric_tolerance_absolute": 5e-5, "paired_observations_per_route_per_count": PAIRS,
        "total_return_count": 0, "timed_return_count": 0, "formula_projection_count": 0,
        "retained_fixture_positive_steps": {"8": 30, "384": 30}, "pid": os.getpid(),
        "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    torch = device = scheduler = root = cancellation = cleanup = evidence = helpers = None
    probe = product = None
    old_threads, safe_close, admitted = None, True, None
    active, external_children, staged = [], [], []
    try:
        (output / "producers").mkdir()
        (output / "fixtures").mkdir()
        package = Path(__file__).absolute().parent.parent
        workspace = package.parent.parent
        optimizer = package / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
        helper_path = Path(__file__).with_name("qualify_bitwise_trained_head_devices.py").absolute()
        cleanup_path = Path(__file__).with_name("qualify_native_768_device.py").absolute()
        # A retained, qualified helper is imported only for bounded ordinary
        # artifacts, lane ownership, projection comparison and native controls.
        # Its run() is never invoked. Model calls below use the retained
        # original/v1/v2 producer interfaces without global replacements.
        helpers = _load_helper(helper_path, "_formula_coordinator_qualified_helpers", HELPERS_SHA)
        evidence = helpers.Evidence(output)
        expected = {"modal_latent_formula_bitwise_device_inference": V1_SHA,
                    "modal_latent_formula_bitwise_device_inference_v2": V2_SHA,
                    "owned_tensor_bitwise_guard": BIT_GUARD_SHA}
        sources = [("benchmark", Path(__file__).absolute(), None),
            ("cg2_harness_helpers", helper_path, HELPERS_SHA), ("cleanup_helper", cleanup_path, CLEANUP_SHA)]
        sources += [(name, optimizer / (name + ".py"), expected.get(name)) for name in SOURCE_NAMES]
        sources += [("tree_pin", package / "ipfs_datasets_py/logic/autoformal/tree_pin.py", None),
            ("canonical_contracts", package / "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py", None),
            ("cid_utils", package / "ipfs_datasets_py/utils/cid_utils.py", None)]
        paths = {}
        def retain(name, path, role, expected_sha=None):
            raw = _read(path)
            current = _pin(path, raw)
            if expected_sha is not None:
                _require(current["sha256"] == expected_sha, "fixed " + role + " bytes differ")
            entry = {"role": role, "current": current, "retained_copy": evidence.raw(name, raw)}
            staged.append(entry)
            return raw, entry
        for index, (role, path, expected_sha) in enumerate(sources):
            _, entry = retain(f"producers/{index:02d}-{path.name}", path, role, expected_sha)
            result["source_pins"].append(entry)
            paths[role] = path
        raw_config, result["shared_configuration"] = retain("configuration.json", configuration, "shared_configuration", CONFIG_SHA)
        fixtures = {}
        for role, (relative, expected_sha) in FIXTURES.items():
            raw, entry = retain("fixtures/" + role + ".json", workspace / "artifacts/codebase_ir_terminal_bench" / relative,
                                role, expected_sha)
            result["fixture_pins"].append(entry)
            fixtures[role] = json.loads(raw)
        _, result["inherited_cg2_baseline"] = retain("inherited-cg2-result.json",
            workspace / "artifacts/codebase_ir_terminal_bench/bitwise-trained-head-device-qualification-20261004-04/result.json",
            "inherited_cg2_result_baseline_only", BASELINE_SHA)
        result["inherited_cg2_baseline_scope"] = "content_pin_only_no_768_or_4096_report_regeneration"
        _require(not any(PREFIX + name in sys.modules for name in SOURCE_NAMES if name != "resource_scheduler"),
                 "fresh worker required before producer imports")
        resources = importlib.import_module(PREFIX + "resource_scheduler")
        config = json.loads(raw_config)
        scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(**config["persisted_config"],
            state_path=config["state_path"], lease_ttl_seconds=config["lease_ttl_seconds"],
            auto_renew_leases=config["auto_renew_leases"]))
        result["resources_before"] = scheduler.snapshot()
        root = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=3, memory_mb=ROOT_RAM,
            gpu_memory_mb=ROOT_GPU, unified_memory_mb=ROOT_UNIFIED, requires_gpu=True,
            timeout=admission_timeout_seconds, request_id="trained-formula-guard-coordinator-qualification")
        admitted = time.monotonic()
        cancellation = helpers.Cancellation(root, admitted + MAX_SECONDS)
        result["admission"] = root.to_dict()
        print("ADMITTED", root.lease_id, flush=True)
        import torch as native_torch
        torch = native_torch
        old_threads = torch.get_num_threads()
        result["ambient_settings_before_thread_reservation"] = _settings(torch)
        torch.set_num_threads(1)
        result["ambient_settings_before_producer_imports_and_models"] = _settings(torch)
        _require(result["ambient_settings_before_producer_imports_and_models"] ==
                 {**result["ambient_settings_before_thread_reservation"], "num_threads": 1},
                 "one deliberately reserved CPU thread must be the only ambient change")
        result["thread_reservation_scope"] = "caller_owned_one_thread_restored_after_owned_cleanup"
        _require(torch.cuda.is_available(), "actual CUDA required; fallback cannot qualify")
        device = torch.cuda.current_device()
        before = torch.cuda.memory_allocated(device)
        result["gpu_allocated_before_producer_imports_bytes"] = before
        result["gpu_allocated_before_owned_sessions_bytes"] = before
        result["gpu_reserved_before_owned_sessions_bytes"] = torch.cuda.memory_reserved(device)
        _require(before == 0, "fresh worker preimport CUDA allocation must be zero")
        modules = {name: importlib.import_module(PREFIX + name) for name in SOURCE_NAMES}
        for name, module in modules.items():
            _require(Path(module.__file__).absolute() == paths[name], "producer imported from unretained source")
        for entry in staged:
            _require(_pin(entry["current"]["path"]) == entry["current"], "source/fixture/configuration changed before model construction")
        _require(torch.cuda.memory_allocated(device) == 0, "producer import allocated CUDA tensors")
        _require(_settings(torch) == result["ambient_settings_before_producer_imports_and_models"],
                 "producer import changed ambient precision/default policy")
        cleanup = _load_helper(cleanup_path, "_formula_coordinator_owned_cleanup", CLEANUP_SHA)
        probe = torch.tensor([2.], dtype=torch.float32, device=f"cuda:{device}")
        product = probe * probe
        _require(product.detach().cpu().tolist() == [4.], "actual initial CUDA kernel differs")
        probe = product = None
        torch.cuda.synchronize(device)
        torch.cuda.reset_peak_memory_stats(device)
        result["hardware"] = {"torch": str(torch.__version__), "cuda_runtime": torch.version.cuda,
            "device_index": device, "name": torch.cuda.get_device_name(device),
            "capability": list(torch.cuda.get_device_capability(device)), "actual_initial_cuda_kernel": True,
            "physical_memory_bytes": torch.cuda.get_device_properties(device).total_memory}
        result["telemetry_context_admission_scope"] = "initialized_context_only_with_zero_allocated_before_producer_imports"
        native = modules["modal_latent_formula"]

        def lane_close(lane):
            cancellation.clear()
            lane.close(torch, device)

        def make_lane(label, width, checkpoint, sha):
            cancellation.poll()
            _require(_settings(torch) == result["ambient_settings_before_producer_imports_and_models"],
                     "ambient precision/default policy changed before constructor")
            original, optimized = label.startswith("original"), label.endswith("cuda")
            caller = None
            owner = None
            if original:
                caller = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1,
                    memory_mb=CHILD_RAM, gpu_memory_mb=CHILD_GPU if optimized else 0,
                    unified_memory_mb=CHILD_UNIFIED if optimized else 0, requires_gpu=optimized,
                    parent_lease=root, cancel_event=cancellation, timeout=admission_timeout_seconds,
                    request_id=f"formula-coordinator-original-{width}-{label}")
                external_children.append(caller)
                factory = lambda: modules["modal_latent_formula_device_inference"].DeviceLatentFormulaDecoder(
                    deepcopy(checkpoint), expected_binding=deepcopy(checkpoint["binding"]), optimized=optimized)
            else:
                name = ("modal_latent_formula_bitwise_device_inference_v2" if "v2" in label
                        else "modal_latent_formula_bitwise_device_inference")
                factory = lambda: modules[name].BitwiseDeviceLatentFormulaDecoder(deepcopy(checkpoint),
                    expected_checkpoint_sha256=sha, optimized=optimized, scheduler=scheduler, parent_lease=root,
                    cancel_event=cancellation, admission_timeout_seconds=admission_timeout_seconds, max_seconds=MAX_SECONDS,
                    memory_mb=CHILD_RAM, gpu_memory_mb=CHILD_GPU, unified_memory_mb=CHILD_UNIFIED)
            try:
                owner = _construct(torch, native, counters, factory, label,
                    dimension=width, checkpoint_sha256=sha)
                _require(_settings(torch) == result["ambient_settings_before_producer_imports_and_models"],
                         "constructor changed ambient precision/default policy")
                lane = helpers.Lane(owner, "formula", caller_lease=caller)
                active.append(lane)
                result["owned_children"].append({"lease_id": lane.lease_id, "family": "formula", "dimension": width,
                    "route": label, "optimized": optimized, "admission": lane.child_lease.to_dict(), "release_observed": False})
                owner = None
                return lane, deepcopy(counters["constructor_observations"][-1])
            except BaseException:
                if owner is not None and caller is None:
                    owner.close()
                owner = None
                # Failed old constructors can remain in traceback frames.
                # Their caller child is released only after final GPU0 cleanup.
                raise

        def retain_call(stem, lane, inputs, count, *, timed=False, reference=None, reference_numeric=None):
            cancellation.poll()
            authored_rows = deepcopy(inputs["rows"][:count])
            cpu_rng, cuda_rng = torch.random.get_rng_state(), torch.cuda.get_rng_state(device)
            torch.cuda.synchronize(device)
            if timed:
                _require(sys.getprofile() is None, "CUDA measurements require no Python call profiler")
            started = time.monotonic()
            if timed:
                report, vectors = lane.owner.infer_with_projection(authored_rows)
            else:
                with _probe_observer(torch, native, counters, scope="cpu_reference_or_cuda_warmup"):
                    report, vectors = lane.owner.infer_with_projection(authored_rows)
            torch.cuda.synchronize(device)
            elapsed = time.monotonic() - started
            _require(type(elapsed) is float and math.isfinite(elapsed) and elapsed > 0, "positive completed call timing required")
            _require(torch.equal(cpu_rng, torch.random.get_rng_state()) and torch.equal(cuda_rng, torch.cuda.get_rng_state(device)),
                     "inference changed CPU/CUDA RNG state")
            cancellation.poll()
            observed = {"result": evidence.json(stem + "-result.json", report),
                "projected_vectors": evidence.json(stem + "-projected-vectors.json", vectors),
                "elapsed_seconds": elapsed, "included_in_paired_timing": timed, "cpu_cuda_rng_unchanged": True,
                "python_call_profiler_attached_during_timing": False if timed else True,
                "canonical_matches_original_cpu": reference is not None}
            result["total_return_count"] += 1
            result["formula_projection_count"] += 1
            result["timed_return_count"] += int(timed)
            decisions = _decisions(report)
            if reference is not None:
                _require(_wire(decisions) == _wire(reference), "exact canonical decisions differ from original CPU")
                observed["complete_projection_max_abs_error"] = helpers._numeric_error(reference_numeric, vectors)
            profile = report["inference_implementation"]
            optimized = lane.owner._device.startswith("cuda:")
            _require(profile["cuda_selected"] is optimized and profile["cuda_executed"] is optimized
                     and report["training_executed"] is False, "actual inference execution differs from bound lane")
            if hasattr(lane.owner, "_reference_anchor"):
                expected_profile = V2_PROFILE if type(lane.owner) is modules["modal_latent_formula_bitwise_device_inference_v2"].BitwiseDeviceLatentFormulaDecoder else V1_PROFILE
                _require(profile["profile_id"] == expected_profile, "actual v1/v2 execution profile differs")
                _require(profile["owned_tensor_currentness"]["mode"] ==
                         ("cuda_bitwise_single_host_decision" if optimized else "cpu_reference_checks"),
                         "timed currentness guard differs from native bitwise profile")
            return observed, decisions, vectors

        for width in (8, 384):
            cancellation.poll()
            role = f"formula{width}"
            checkpoint, saved = fixtures[role + "_checkpoint"], fixtures[role + "_training_inputs"]
            sha = FIXTURES[role + "_checkpoint"][1]
            _require(checkpoint["progress"]["optimizer_steps"] == 30, "retained positive30-step fixture required")
            inputs = {"schema": "retained-trained-formula-inference-inputs/v1", "dimension": width,
                "rows": [{"id": f"trained-formula{width}-inference-{index}",
                    "source_text": saved[index % len(saved)]["source_text"],
                    "latent": deepcopy(saved[index % len(saved)]["latent"])} for index in range(32)],
                "target_fields_excluded": True, "encoder_execution_performed": False}
            raw_state = _wire(checkpoint["model_state"])
            state_pin = {"bytes": len(raw_state), "sha256": hashlib.sha256(raw_state).hexdigest()}
            family = result["families"][role] = {"family": "formula", "dimension": width, "checkpoint_sha256": sha,
                "retained_checkpoint_progress": deepcopy(checkpoint["progress"]), "retained_checkpoint_model_pin": state_pin,
                "checkpoint_optimizer_sha256": hashlib.sha256(_wire(checkpoint["optimizer_state"])).hexdigest(),
                "inputs": evidence.json(role + "-inference-inputs.json", inputs), "lanes": {}, "counts": {}}
            references, projections = {}, {}
            for label in CPU_LANES:
                lane, constructor = make_lane(label, width, checkpoint, sha)
                lane_record = family["lanes"][label] = {"constructor": constructor, "profile": lane.describe(),
                    "state_before": helpers._state_pin(lane.owner, "formula"), "counts": {}}
                _require(lane_record["state_before"] == state_pin, "restored CPU tensor state differs from fixed checkpoint")
                for count in COUNTS:
                    observed, decisions, vectors = retain_call(f"{role}-{label}-{count}", lane, inputs, count,
                        reference=references.get(count), reference_numeric=projections.get(count))
                    lane_record["counts"][str(count)] = observed
                    if label == "original_cpu_reference":
                        references[count], projections[count] = decisions, vectors
                lane_record["state_after"] = helpers._state_pin(lane.owner, "formula")
                _require(lane_record["state_after"] == state_pin and _wire(lane.owner._checkpoint) == _wire(checkpoint),
                         "CPU inference changed tensors/checkpoint/Adam")
                lane_record["checkpoint_and_adam_unchanged"] = True
                lane_close(lane)
                lane = None
            gpu_lanes = {}
            for label in CUDA_LANES:
                lane, constructor = make_lane(label, width, checkpoint, sha)
                gpu_lanes[label] = lane
                lane_record = family["lanes"][label] = {"constructor": constructor, "profile": lane.describe(),
                    "state_before": helpers._state_pin(lane.owner, "formula"), "counts": {}}
                _require(lane_record["state_before"] == state_pin, "restored CUDA state differs from fixed checkpoint")
                warmup, _, _ = retain_call(f"{role}-{label}-warmup", lane, inputs, 32,
                    reference=references[32], reference_numeric=projections[32])
                lane_record["warmup"] = warmup
            family["three_way_admission"] = {"all_three_gpu_children_live": all(not lane.child_lease.released for lane in gpu_lanes.values()),
                "child_leases": {label: lane.child_lease.to_dict() for label, lane in gpu_lanes.items()}, "resources": scheduler.snapshot()}
            _require(family["three_way_admission"]["all_three_gpu_children_live"] is True, "joint three-way GPU admission required")
            for count in COUNTS:
                trials, samples = [], {label: [] for label in CUDA_LANES}
                # Make partial observations reviewable even if a later call
                # refuses, rather than losing the completed evidence journal.
                count_record = family["counts"][str(count)] = {"trials": trials, "samples_seconds": samples,
                    "sample_count_each_route": 0, "order_schedule": "all_six_permutations_repeated_twice"}
                for index, order in enumerate(ORDERS):
                    trial = {"trial": index, "order": list(order), "observations": {}}
                    trials.append(trial)
                    for label in order:
                        observed, _, _ = retain_call(f"{role}-{count}-trial{index:02d}-{label}", gpu_lanes[label], inputs, count,
                            timed=True, reference=references[count], reference_numeric=projections[count])
                        trial["observations"][label] = observed
                        samples[label].append(observed["elapsed_seconds"])
                medians = {label: statistics.median(values) for label, values in samples.items()}
                summary = {"trials": trials, "samples_seconds": samples, "median_seconds": medians}
                count_record.update(median_seconds=medians, sample_count_each_route=PAIRS,
                    first_position_each_route=4, second_position_each_route=4, third_position_each_route=4,
                    median_original_over_v1_ratio=medians["original_cuda"] / medians["bitwise_v1_cuda"],
                    median_original_over_v2_ratio=medians["original_cuda"] / medians["bitwise_v2_cuda"],
                    median_v1_over_v2_ratio=medians["bitwise_v1_cuda"] / medians["bitwise_v2_cuda"],
                    paired_v1_over_v2_ratios=[a / b for a, b in zip(samples["bitwise_v1_cuda"], samples["bitwise_v2_cuda"])],
                    raw_timing_evidence=evidence.json(f"{role}-{count}-raw-three-way-timings.json", summary),
                    interpretation="descriptive_same_fixture_guarded_complete_calls_no_universal_gain_claim")
            family["new_cuda_controls"] = {}
            for label in ("bitwise_v1_cuda", "bitwise_v2_cuda"):
                with _probe_observer(torch, native, counters, scope="native_mutation_and_boundary_controls"):
                    family["new_cuda_controls"][label] = helpers._new_controls(torch, gpu_lanes[label], inputs, cancellation)
            for label, lane in gpu_lanes.items():
                lane_record = family["lanes"][label]
                lane_record["state_after"] = helpers._state_pin(lane.owner, "formula")
                _require(lane_record["state_after"] == state_pin and _wire(lane.owner._checkpoint) == _wire(checkpoint),
                         "CUDA inference/probes changed tensors/checkpoint/Adam")
                lane_record["checkpoint_and_adam_unchanged"] = True
                lane_close(lane)
            gpu_lanes.clear()
            lane = None
            family["numerical_and_canonical_qualified"] = True
        _require(result["total_return_count"] == result["formula_projection_count"] == 240
                 and result["timed_return_count"] == 216 and len(result["owned_children"]) == 12
                 and counters["optimizer_restore_attempts"] == counters["optimizer_constructor_calls"] == 12,
                 "complete240-return/216-CUDA/12-restoration coverage required")
        _require(all(counters[name] == 0 for name in ("optimizer_steps", "training_calls", "new_training_fits", "training_mode_true_calls", "encoder_calls")),
                 "inference attempted training/steps/encoders")
        result["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
        result["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
        _require(result["gpu_peak_allocated_bytes"] <= ROOT_GPU * 1024**2, "observed peak CUDA allocation exceeded root reservation")
        result["root_gpu_allocation_budget_observed"] = True
        result["qualified"] = result["complete_call_measurements_qualified"] = True
    except BaseException as error:
        result["qualified"] = result["complete_call_measurements_qualified"] = False
        result["error"] = {"type": type(error).__name__, "detail": str(error), "traceback": traceback.format_exc(limit=14)}
    finally:
        if cancellation is not None:
            cancellation.clear()
        for lane in reversed(active):
            try:
                lane.close(torch, device)
            except BaseException as error:
                safe_close = False
                result.setdefault("close_errors", []).append({"type": type(error).__name__, "detail": str(error)})
        probe = product = None
        gc.collect()
        if torch is not None and cleanup is not None and safe_close:
            try:
                cleanup._cleanup_owned_cuda(torch, device, result)
            except BaseException as error:
                safe_close = False
                result["cleanup_error"] = {"type": type(error).__name__, "detail": str(error)}
        elif device is not None:
            safe_close = False
            result["cuda_cleanup_status"] = "owned_cleanup_not_established_root_retained"
        if safe_close:
            for child in external_children:
                if not child.released:
                    try:
                        child.release()
                    except BaseException as error:
                        safe_close = False
                        result.setdefault("child_release_errors", []).append(
                            {"lease_id": child.lease_id, "type": type(error).__name__, "detail": str(error)})
        try:
            result["currentness_after"] = []
            for entry in staged:
                current = _pin(entry["current"]["path"])
                _require(current == entry["current"], "source/checkpoint/configuration/input bytes changed")
                result["currentness_after"].append(current)
            result["retained_sources_fixtures_configuration_unchanged"] = True
        except BaseException as error:
            result["qualified"] = result["complete_call_measurements_qualified"] = False
            result["currentness_error"] = {"type": type(error).__name__, "detail": str(error)}
        if torch is not None and old_threads is not None:
            try:
                result["ambient_settings_after_owned_cleanup_before_thread_restore"] = _settings(torch)
                _require(result["ambient_settings_after_owned_cleanup_before_thread_restore"] ==
                         result["ambient_settings_before_producer_imports_and_models"],
                         "owned inference/cleanup changed ambient precision/default policy")
            except BaseException as error:
                result["qualified"] = result["complete_call_measurements_qualified"] = False
                result["ambient_policy_error"] = {"type": type(error).__name__, "detail": str(error)}
            finally:
                torch.set_num_threads(old_threads)
            result["ambient_settings_after_thread_restore"] = _settings(torch)
            if result["ambient_settings_after_thread_restore"] != result["ambient_settings_before_thread_reservation"]:
                result["qualified"] = result["complete_call_measurements_qualified"] = False
                result["ambient_policy_error"] = {"type": "ValueError", "detail": "original ambient policy not restored"}
            result["ambient_precision_default_policy_unchanged"] = "ambient_policy_error" not in result
            result["persistent_precision_policy_mutated"] = "ambient_policy_error" in result
        for record in result["owned_children"]:
            matches = [lane for lane in active if lane.lease_id == record["lease_id"]]
            record["release_observed"] = len(matches) == 1 and matches[0].child_lease.released
        if root is not None:
            if safe_close and all(record["release_observed"] for record in result["owned_children"]):
                try:
                    root.release()
                except BaseException as error:
                    safe_close = False
                    result["root_release_error"] = {"type": type(error).__name__, "detail": str(error)}
            result["own_root_lease_released"] = result["root_release_observed"] = root.released
        else:
            result["own_root_lease_released"] = result["root_release_observed"] = False
        if scheduler is not None:
            result["resources_after"] = scheduler.snapshot()
        if not safe_close or (root is not None and not root.released):
            result["qualified"] = result["complete_call_measurements_qualified"] = False
        result.update(counters)
        result["safe_owned_cleanup_established"] = safe_close
        result["elapsed_seconds_total"] = time.monotonic() - began
        result["elapsed_seconds_after_root_admission"] = time.monotonic() - admitted if admitted is not None else None
        if admitted is not None and result["elapsed_seconds_after_root_admission"] > MAX_SECONDS:
            result["qualified"] = result["complete_call_measurements_qualified"] = False
            result["deadline_exceeded_after_owned_cleanup"] = True
        if result["qualified"] is False and result["error"] is None:
            result["error"] = {"type": "QualificationClosureFailure",
                "detail": "owned cleanup, source currentness, ambient policy or deadline closure was not established"}
        result["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["evidence_limits"] = {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES, "result_included_in_limits": True}
        if evidence is not None:
            result["evidence_files_except_result"] = list(evidence.files)
            result["evidence_bytes_except_result"] = evidence.bytes
            evidence.json("result.json", result, final=True)
        else:
            # Pre-helper refusal has no authority and no admitted resources.
            # Retain it without importing any producer or model.
            raw = _wire(result)
            _require(len(raw) <= MAX_FILE_BYTES, "bounded early refusal required")
            descriptor = os.open(output / "result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            (output / "result.json").chmod(0o444)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--configuration", required=True, type=Path)
    parser.add_argument("--admission-timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    result = run(args.output, args.configuration, admission_timeout_seconds=args.admission_timeout_seconds)
    print(json.dumps({"qualified": result["qualified"], "result": str(args.output.absolute() / "result.json"),
                      "error": result["error"]}, sort_keys=True), flush=True)
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
