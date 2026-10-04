"""Bounded diagnostic profiling of retained 768D and synthetic 4096D heads.

Each invocation profiles one dimension in a fresh, caller-owned worker.
An independently pinned adapter admits at most four million callback events
on each owned observer instance; the original profiler and producers retain
their global policies unchanged. Selected spans and native traces retain the
original twenty-thousand/fifteen-thousand bounds respectively. The
768D fixture has 30 retained training steps and historical receipt-bound
vectors. The 4096D fixture is unchanged synthetic zero-step data: no Leanstral
embedding, native owner or positive-step 4096 training claim is made. Existing
producer checks and numerical kernels remain intact. Instrumented durations
cannot qualify a speedup, promote a route or grant proof/production authority.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import gc
import hashlib
import importlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import resource
import sys
import threading
import time
import traceback

SCHEMA = "dimension-guard-cost-profiling/v2"
BASE_COST_PROFILER_SHA = "61786537ff7e6d442322d307ef7d7a1a609cf9279d8a005017eb9e1e73127577"
BUDGET_ADAPTER_SHA = "1f1e1a1699c230618e8f14a77715219664a34d60ca25d333745dace73fd3b825"
CALLBACK_LIMIT_POLICY = {"schema": "dimension-guard-cost-callback-budget/v2", "max_callback_events": 4000000,
    "scope": "all_python_and_c_callbacks_including_unselected_recursive_guard_atoms",
    "selected_span_limit": 20000, "native_operator_postcollection_limit": 15000,
    "global_observer_limits_changed": False, "producer_checks_changed": False}
CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
SCHEDULER_SHA = "f156511991e33d3b4ba523c3c5080ea30d0a53ad8a4dbcccea0487432679a9aa"
COORDINATOR_SHA = "e8b9634c6e905d0c63e7eba067e86a034796537f08d758d548a1d22123190ed8"
TRAINED_HELPERS_SHA = "29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110"
SYNTHETIC_HELPERS_SHA = "a2b85c0e05d9fc652e7e3d2fdb99b83407a511a3321fba3d2299c27e797ceb36"
CLEANUP_SHA = "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c"
ORDINARY_SPAN_HELPERS_SHA = "fd020261328d05d6e4df7ec1e85e2d9c5278fa01195dac3c8f8bb156be2a11c2"
COUNTS = (1, 16, 32)
ROOT_CPU, ROOT_RAM, ROOT_GPU, ROOT_UNIFIED = 3, 3072, 768, 3840
CHILD_RAM, CHILD_GPU, CHILD_UNIFIED = 1024, 256, 1280
MAX_SECONDS, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_FILES = 120, 8388608, 67108864, 1024
PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
COMMON_SOURCES = ("resource_scheduler", "legal_span_formula", "legal_span_dimensions",
    "legal_span_device_inference", "legal_span_device_batch_inference", "owned_tensor_value_guard",
    "owned_tensor_bitwise_guard", "checkpoint_content_guard", "runtime_telemetry", "proof_resource_safety",
    "legal_formula_codec", "legal_ir_grammar_decoder", "legal_ir_family_evaluator", "snapshot_evaluator")
DIMENSION_SOURCES = {768: ("legal_span_device_bitwise_inference",), 4096:
    ("legal_span_4096", "legal_span_4096_device_inference", "legal_span_4096_bitwise_device_inference",
     "legal_span_4096_bitwise_device_inference_v2")}
FIXED_SOURCES = {"resource_scheduler": SCHEDULER_SHA,
    "legal_span_device_inference": "4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5",
    "legal_span_device_bitwise_inference": "d1c12eb54ca8c17c9815ed20db9237c86876361ac3d72fa30ce2d470b0fccf91",
    "legal_span_4096_device_inference": "658382fb5b7bb30eb5e82a444b9ac9168b7557f5452a87a8ff59a5f883de55a8",
    "legal_span_4096_bitwise_device_inference": "90d2a06081b4391216fb63cc82968b0c8ea1ff8138d564448281b5e3b2b88595",
    "legal_span_4096_bitwise_device_inference_v2": "14678654b927d0b6910fda6a8c82961978a9e7ebc29334aaae6cb2320abc5dc3",
    "owned_tensor_bitwise_guard": "6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34"}
FIXTURES = {
    768: {"checkpoint": ("native-768-device-qualification-20261004-04/diagnostic-native768-head.json",
        "9fcd8dd3b9727f5ee93b5b2cb2d7f23e482f16c24f64c23a3ae9da2168e3117b"),
        "sources": ("native-768-device-qualification-20261004-04/source-rows.json",
            "eec38602f9d3c3b0c1511ab05b473bbcf2bb3647ac1c4854e899fb0200ad4e46"),
        "historical_outputs": ("native-768-device-qualification-20261004-04/encoder-cuda-batch32.json",
            "f728dab53925cd2f9d053d760dcafab756ed718197a8649f24c2000bfc73c221")},
    4096: {"checkpoint": ("native-4096-synthetic-head-device-v2-qualification-20261004-04/synthetic-untrained-checkpoint.json",
        "04a8f2d317294861a7fcf9b6f156e915cd6c31bfa1482b8eaab4ecf15d00dee7"),
        "rows": ("native-4096-synthetic-head-device-v2-qualification-20261004-04/synthetic-inputs.json",
            "90c2ae29b4eb7aca66eeb9539c3cbbd42536d245938a449465106469cd46d4bf")}}
ROUTES = {768: ("original", "bitwise_v1"), 4096: ("original", "bitwise_v1", "bitwise_v2")}


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _rows_from_batched_logits(values, token_lengths):
    """Keep every real-token value and omit only per-row batch padding.

    The source-bound private forward already verifies finite float32 tensors.
    This plain-data shape check prevents comparing a singleton to a different
    row or to its padded batch width after transfer to CPU.
    """
    _require(type(values) is dict and set(values) == {"modality", "presence", "start", "end"},
             "complete four-logit batch required")
    _require(type(token_lengths) is list and token_lengths and
             all(type(length) is int and 1 <= length <= 256 for length in token_lengths),
             "bounded actual token lengths required")
    count, width = len(token_lengths), max(token_lengths)
    _require(all(type(values[name]) is list and len(values[name]) == count for name in values),
             "complete four-logit row coverage required")
    rows = []
    for index, length in enumerate(token_lengths):
        modality, presence = values["modality"][index], values["presence"][index]
        _require(type(modality) is list and len(modality) == 3 and type(presence) is list
                 and len(presence) == 4 and all(type(pair) is list and len(pair) == 2 for pair in presence),
                 "complete modality/presence shape required")
        row = {"modality": [deepcopy(modality)], "presence": [deepcopy(presence)]}
        for name in ("start", "end"):
            panels = values[name][index]
            _require(type(panels) is list and len(panels) == 6 and
                     all(type(panel) is list and len(panel) == width for panel in panels),
                     "complete padded span-logit shape required")
            row[name] = [[deepcopy(panel[:length]) for panel in panels]]
        _require(all(type(value) is float and math.isfinite(value)
                     for panel in (modality, *presence, *values["start"][index], *values["end"][index])
                     for value in panel), "finite plain float32 snapshot values required")
        rows.append(row)
    return rows


def _bootstrap_coordinator():
    """Only a fixed stdlib-only helper is loaded before resource admission."""
    path = Path(__file__).with_name("qualify_formula_guard_coordinator.py").absolute()
    # The fixed helper owns the more complete anchored ordinary-reader checks.
    # This preliminary read cannot import model code or execute an unpinned helper.
    import stat
    _require(path.parent.resolve(strict=True) == path.parent, "canonical bootstrap source parent required")
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_FILE_BYTES,
             "bounded ordinary bootstrap helper required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(MAX_FILE_BYTES + 1)
        final_open = os.fstat(stream.fileno())
    after = path.lstat()
    identities = [(x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns, x.st_nlink)
                  for x in (before, opened, final_open, after)]
    _require(all(value == identities[0] for value in identities) and len(raw) == before.st_size
             and hashlib.sha256(raw).hexdigest() == COORDINATOR_SHA, "bootstrap helper pin changed")
    specification = importlib.util.spec_from_file_location("_dimension_coordinator_helpers", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    _require(module._pin(path)["sha256"] == COORDINATOR_SHA, "bootstrap helper changed during import")
    return module


@contextmanager
def _forbidden_calls(torch, modules, counters):
    """Observe existing call code; do not replace producer/framework methods."""
    def chain(function):
        codes, seen = set(), set()
        while function is not None and id(function) not in seen:
            seen.add(id(function))
            if hasattr(function, "__code__"):
                codes.add(function.__code__)
            function = getattr(function, "__wrapped__", None)
        return codes
    adam = chain(torch.optim.Adam.__init__)
    steps = chain(torch.optim.Adam.step) | chain(torch.optim.Optimizer.step)
    train_mode = chain(torch.nn.Module.train)
    fits = set()
    for module in modules.values():
        for name in ("train_decoder", "train"):
            if inspect.isfunction(getattr(module, name, None)):
                fits.update(chain(getattr(module, name)))
    previous = sys.getprofile()
    def observe(frame, event, arg):
        if event == "call":
            code = frame.f_code
            key = ("optimizer_constructor_calls" if code in adam else "optimizer_steps" if code in steps else
                   "new_training_fits" if code in fits else "training_mode_true_calls"
                   if code in train_mode and frame.f_locals.get("mode") is not False else None)
            if key is not None:
                counters[key] += 1
                raise RuntimeError("dimension inference attempted forbidden work: " + key)
        if previous is not None:
            previous(frame, event, arg)
    sys.setprofile(observe)
    try:
        yield
    finally:
        sys.setprofile(previous)


def _registry(profiler, modules, source_paths, model):
    """Select source-bound phases; recursive scalar guard atoms stay untraced.

    Every scalar guard still executes. Selecting its containing check measures
    that cost without retaining one span per checkpoint/input scalar.
    """
    by_filename = {str(Path(path).absolute()): role for role, path in source_paths.items()}
    registry = profiler.build_registry(modules)
    def add(function):
        function = getattr(function, "__func__", function)
        seen = set()
        while inspect.isfunction(function) and id(function) not in seen:
            seen.add(id(function))
            code = function.__code__
            role = by_filename.get(str(Path(code.co_filename).absolute()))
            if role is not None and code not in registry:
                _require(len(registry) < 508, "bound producer registry plus utility descriptors must fit512")
                profiler.register(registry, role + ":" + function.__qualname__, function, role)
            function = getattr(function, "__wrapped__", None)
    functions = {
        "legal_span_formula": ("_implementation", "_batch", "checkpoint_digest"),
        "legal_span_dimensions": ("_implementation", "_restore_for_inference"),
        "legal_span_device_inference": ("_implementation", "_restore", "_strict_json", "_verify_receipts", "_strict_cuda_gru"),
        "legal_span_device_batch_inference": ("_implementation", "_batch_memory_bound"),
        "legal_span_device_bitwise_inference": ("_source_sha256", "_check_bindings", "_implementation_receipt", "_implementation"),
        "legal_span_4096": ("_capture_implementation", "_implementation", "_restore_for_inference"),
        "legal_span_4096_device_inference": ("_implementation", "_receipt_status"),
        "legal_span_4096_bitwise_device_inference": ("_source_sha256", "_implementation"),
        "legal_span_4096_bitwise_device_inference_v2": ("_source_sha256", "_check_bindings", "_implementation_receipt", "_implementation"),
    }
    for role, names in functions.items():
        module = modules.get(role)
        if module is not None:
            for name in names:
                if hasattr(module, name):
                    add(getattr(module, name))
    methods = {
        "legal_span_formula": (("SpanLegalFormulaDecoder", ("_decode",)),),
        "legal_span_device_inference": (("DeviceDimensionalSpanSession", ("_poll", "_pure_check", "_check", "_operation",
            "_description", "decode_formal_logic", "_synchronize")),),
        "legal_span_device_batch_inference": (("DeviceBatchedDimensionalSpanSession", ("_check", "_description",
            "_decision", "_admit_batch_memory", "decode_formal_logic")), ("_CachedOutput", ("__init__", "bind", "__call__"))),
        "legal_span_device_bitwise_inference": (("DeviceBitwiseDimensionalSpanSession", ("_reference_byte_plan",
            "_reference_state_bytes", "_check_reference_anchor", "_pure_check", "_admit_batch_memory", "_description")),),
        "legal_span_4096_device_inference": (("DeviceLeanstral4096SpanSession", ("_poll", "_pure_check", "_check",
            "_reference_byte_plan", "_reference_state_bytes", "_check_reference_anchor", "_operation", "_description",
            "_admit_batch_memory", "_decision", "decode_formal_logic", "_synchronize")),),
        "legal_span_4096_bitwise_device_inference": (("BitwiseDeviceLeanstral4096SpanSession", ("_pure_check", "_description")),),
        "legal_span_4096_bitwise_device_inference_v2": (("BitwiseDeviceLeanstral4096SpanSession", ("_pure_check", "_description")),),
    }
    for role, declarations in methods.items():
        module = modules.get(role)
        if module is not None:
            for class_name, names in declarations:
                owner = getattr(module, class_name)
                for name in names:
                    member = owner.__dict__.get(name)
                    if isinstance(member, property):
                        add(member.fget)
                    elif isinstance(member, (staticmethod, classmethod)):
                        add(member.__func__)
                    else:
                        add(member)
    for child in model.modules():
        for name in ("forward", "project", "start", "next_logits"):
            add(getattr(child, name, None))
    _require(registry and len(registry) <= 508, "nonempty bounded producer-code registry required")
    return registry


class DimensionLane:
    def __init__(self, owner, dimension):
        self.owner, self.dimension, self.family = owner, dimension, "span"
        self.child_lease = owner._lease
        self.lease_id = self.child_lease.lease_id

    def call(self, inputs, count):
        texts, vectors = deepcopy(inputs["texts"][:count]), deepcopy(inputs["vectors"][:count])
        options = ({} if self.dimension == 4096 else {"embedding_receipts": deepcopy(inputs["receipts"][:count]),
                   "expected_receipt_sha256s": inputs["receipt_pins"][:count]})
        return self.owner.decode_formal_logic(texts, vectors, **options)

    def describe(self):
        return self.owner.describe()

    def close(self, torch, device):
        if self.owner is not None:
            self.owner.close()
            self.owner = None
        _require(self.child_lease.released, "owned dimension child lease did not close")


def run(output, configuration, *, dimension, expected_profiler_sha256, expected_budget_adapter_sha256, admission_timeout_seconds=30):
    _require(type(dimension) is int and dimension in ROUTES, "dimension must be768or4096")
    _require(type(admission_timeout_seconds) is int and 1 <= admission_timeout_seconds <= 60,
             "admission timeout must be1..60seconds")
    _require(type(expected_profiler_sha256) is str and len(expected_profiler_sha256) == 64
             and all(character in "0123456789abcdef" for character in expected_profiler_sha256),
             "externally supplied exact profiling utility SHA required")
    _require(expected_profiler_sha256 == BASE_COST_PROFILER_SHA,
             "original qualified profiling utility SHA required by budget adapter")
    _require(type(expected_budget_adapter_sha256) is str and len(expected_budget_adapter_sha256) == 64
             and all(character in "0123456789abcdef" for character in expected_budget_adapter_sha256),
             "externally supplied exact observer budget adapter SHA required")
    _require(expected_budget_adapter_sha256 == BUDGET_ADAPTER_SHA,
             "fixed v2 observer budget adapter SHA required")
    coordinator = _bootstrap_coordinator()
    output, configuration = Path(output).absolute(), Path(configuration).absolute()
    _require(output.parent.resolve(strict=True) == output.parent, "canonical existing output parent required")
    output.mkdir(parents=False)
    (output / "producers").mkdir()
    (output / "fixtures").mkdir()
    began = time.monotonic()
    counters = {"optimizer_constructor_calls": 0, "optimizer_steps": 0, "new_training_fits": 0,
                "training_mode_true_calls": 0, "encoder_calls": 0}
    result = {"schema": SCHEMA, "dimension": dimension, "qualified": False, "error": None,
        "scope": "retained_dimension_guard_cost_diagnostic_only", "instrumented_durations_qualify_speedup": False,
        "performance_qualified": False, "production_qualified": False, "proof_authority": False,
        "execution_attestation": False, "semantic_correctness_verified": False, "kernel_resource_enforcement": False,
        "native_leanstral_outputs_qualified": False, "trained_4096_latent_conditioning_qualified": False,
        "fresh_encoder_execution_qualified": False, "native_encoder_origin_authenticated": False,
        "selected_existing_profile_changed": False, "foreign_process_actions": False,
        "synthetic_only": dimension == 4096, "retained_training_steps": 30 if dimension == 768 else 0,
        "historical_receipt_scope": "exact_content_only_no_fresh_encoder_or_origin_attestation" if dimension == 768
            else "explicit_unreceipted_synthetic_fixture_only_native_gate_closed",
        "routes": list(ROUTES[dimension]), "counts": list(COUNTS), "source_pins": [], "fixture_pins": [],
        "lanes": {}, "profiled_calls": [], "owned_children": [], "total_return_count": 0,
        "profiled_return_count": 0, "numeric_snapshot_count": 0, "pid": os.getpid(),
        "max_seconds_after_root_admission": MAX_SECONDS, "admission_timeout_seconds": admission_timeout_seconds,
        "counter_scope": "source_bound_python_observer_chained_through_cost_profiler_all_authored_model_calls",
        "encoder_counter_scope": "no_encoder_import_or_invocation_in_authored_harness_no_execution_attestation",
        "profiling_scope": "one_instrumented_call_per_cuda_route_count_no_repeatability_or_gain_claim",
        "callback_limit_policy": deepcopy(CALLBACK_LIMIT_POLICY),
        "numeric_scope": "separate_checked_private_four_logits_per_lane_count_original_cpu_singleton_reference",
        "numeric_tolerance_absolute": 5e-5, "resource_configuration_changed": False,
        "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    torch = device = root = scheduler = cancel = cleanup = evidence = profiler = budget_adapter = trained = synthetic = None
    old_threads, admitted, safe_close = None, None, True
    active, staged = [], []
    try:
        trained = coordinator._load_helper(Path(__file__).with_name("qualify_bitwise_trained_head_devices.py"),
            "_dimension_trained_helpers", TRAINED_HELPERS_SHA)
        synthetic = coordinator._load_helper(Path(__file__).with_name("qualify_synthetic_4096_head_device_v2.py"),
            "_dimension_synthetic_helpers", SYNTHETIC_HELPERS_SHA)
        evidence = trained.Evidence(output)
        package = Path(__file__).absolute().parent.parent
        workspace, optimizer = package.parent.parent, package / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
        paths = {name: optimizer / (name + ".py") for name in (*COMMON_SOURCES, *DIMENSION_SOURCES[dimension])}
        paths.update({"benchmark": Path(__file__).absolute(),
            "cost_profiler": Path(__file__).with_name("profile_formula_guard_costs.py").absolute(),
            "cost_observer_budget": Path(__file__).with_name("guard_cost_observer_budget_v2.py").absolute(),
            "coordinator_helpers": Path(__file__).with_name("qualify_formula_guard_coordinator.py").absolute(),
            "trained_helpers": Path(__file__).with_name("qualify_bitwise_trained_head_devices.py").absolute(),
            "synthetic_helpers": Path(__file__).with_name("qualify_synthetic_4096_head_device_v2.py").absolute(),
            "cleanup_helper": Path(__file__).with_name("qualify_native_768_device.py").absolute(),
            "ordinary_span_reader_helpers": Path(__file__).with_name("review_bitwise_trained_head_devices.py").absolute(),
            "tree_pin": package / "ipfs_datasets_py/logic/autoformal/tree_pin.py",
            "canonical_contracts": package / "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
            "cid_utils": package / "ipfs_datasets_py/utils/cid_utils.py"})
        expected_sources = {**FIXED_SOURCES, "cost_profiler": expected_profiler_sha256,
            "cost_observer_budget": expected_budget_adapter_sha256,
            "coordinator_helpers": COORDINATOR_SHA, "trained_helpers": TRAINED_HELPERS_SHA,
            "synthetic_helpers": SYNTHETIC_HELPERS_SHA, "cleanup_helper": CLEANUP_SHA}
        expected_sources["ordinary_span_reader_helpers"] = ORDINARY_SPAN_HELPERS_SHA
        def retain(name, path, role, expected=None):
            raw = coordinator._read(path)
            pin = coordinator._pin(path, raw)
            _require(expected is None or pin["sha256"] == expected, "fixed source/fixture differs: " + role)
            entry = {"role": role, "current": pin, "retained_copy": evidence.raw(name, raw)}
            staged.append(entry)
            return raw, entry
        for index, (role, path) in enumerate(paths.items()):
            _, entry = retain(f"producers/{index:02d}-{path.name}", path, role, expected_sources.get(role))
            result["source_pins"].append(entry)
        config_raw, result["shared_configuration"] = retain("configuration.json", configuration, "shared_configuration", CONFIG_SHA)
        fixture_values = {}
        for role, (relative, digest) in FIXTURES[dimension].items():
            raw, entry = retain("fixtures/" + role + ".json", workspace / "artifacts/codebase_ir_terminal_bench" / relative,
                role, digest)
            fixture_values[role] = json.loads(raw)
            result["fixture_pins"].append(entry)
        checkpoint = fixture_values["checkpoint"]
        checkpoint_sha = FIXTURES[dimension]["checkpoint"][1]
        _require(checkpoint["progress"]["optimizer_steps"] == result["retained_training_steps"],
                 "retained checkpoint progress differs")
        if dimension == 768:
            saved = fixture_values["historical_outputs"]
            sources = fixture_values["sources"]
            _require(len(sources) == len(saved["vectors"]) == len(saved["receipts"]) == 32,
                     "complete historical768 receipt/vector/source coverage required")
            inputs = {"schema": "dimension-guard-profiling-inputs/v1", "dimension": dimension,
                "texts": [row["source_text"] for row in sources], "vectors": deepcopy(saved["vectors"]),
                "receipts": deepcopy(saved["receipts"]), "receipt_pins": [hashlib.sha256(_wire(x)).hexdigest() for x in saved["receipts"]],
                "encoder_execution_performed": False, "synthetic_unreceipted": False}
        else:
            rows = fixture_values["rows"]
            _require(type(rows) is list and len(rows) == 32, "complete synthetic4096 input rows required")
            inputs = {"schema": "dimension-guard-profiling-inputs/v1", "dimension": dimension,
                "texts": [row["source_text"] for row in rows], "vectors": [deepcopy(row["latent"]) for row in rows],
                "encoder_execution_performed": False, "synthetic_unreceipted": True}
        result["inputs"] = evidence.json("dimension-inference-inputs.json", inputs)
        result["checkpoint_sha256"] = checkpoint_sha
        result["checkpoint_model_pin"] = {"bytes": len(_wire(checkpoint["model_state"])),
            "sha256": hashlib.sha256(_wire(checkpoint["model_state"])).hexdigest()}
        result["checkpoint_optimizer_sha256"] = hashlib.sha256(_wire(checkpoint["optimizer_state"])).hexdigest()
        _require(not any(PREFIX + name in sys.modules for name in (*COMMON_SOURCES, *DIMENSION_SOURCES[dimension])
                         if name != "resource_scheduler"), "fresh worker required before producer imports")
        resources = importlib.import_module(PREFIX + "resource_scheduler")
        config = json.loads(config_raw)
        scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(**config["persisted_config"],
            state_path=config["state_path"], lease_ttl_seconds=config["lease_ttl_seconds"], auto_renew_leases=config["auto_renew_leases"]))
        result["resources_before"] = scheduler.snapshot()
        root = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=ROOT_CPU, memory_mb=ROOT_RAM,
            gpu_memory_mb=ROOT_GPU, unified_memory_mb=ROOT_UNIFIED, requires_gpu=True,
            timeout=admission_timeout_seconds, request_id=f"dimension-{dimension}-guard-cost-profiling")
        admitted = time.monotonic()
        cancel = trained.Cancellation(root, admitted + MAX_SECONDS)
        result["admission"] = root.to_dict()
        print("ADMITTED", root.lease_id, flush=True)
        import torch as actual_torch
        torch = actual_torch
        _require(sys.getprofile() is None and threading.getprofile() is None, "fresh worker requires no ambient Python profiling")
        old_threads = torch.get_num_threads()
        result["ambient_settings_before_thread_reservation"] = coordinator._settings(torch)
        torch.set_num_threads(1)
        result["ambient_settings_before_producer_imports_and_models"] = coordinator._settings(torch)
        _require(result["ambient_settings_before_producer_imports_and_models"] ==
                 {**result["ambient_settings_before_thread_reservation"], "num_threads": 1}, "only reserved thread setting may change")
        _require(torch.cuda.is_available(), "actual CUDA required; CPU fallback cannot qualify")
        device = torch.cuda.current_device()
        result["gpu_allocated_before_producer_imports_bytes"] = torch.cuda.memory_allocated(device)
        result["gpu_allocated_before_owned_sessions_bytes"] = torch.cuda.memory_allocated(device)
        _require(result["gpu_allocated_before_producer_imports_bytes"] == 0, "fresh worker initial CUDA allocation must be zero")
        modules = {name: importlib.import_module(PREFIX + name) for name in (*COMMON_SOURCES, *DIMENSION_SOURCES[dimension])}
        for name, module in modules.items():
            _require(Path(module.__file__).absolute() == paths[name], "producer import resolved to unretained source")
        for entry in staged:
            _require(coordinator._pin(entry["current"]["path"]) == entry["current"], "source/fixture changed before model admission")
        _require(torch.cuda.memory_allocated(device) == 0, "producer import allocated CUDA tensors")
        _require(coordinator._settings(torch) == result["ambient_settings_before_producer_imports_and_models"],
                 "producer import changed ambient precision/default policy")
        profiler = coordinator._load_helper(paths["cost_profiler"], "_dimension_cost_profiler", expected_profiler_sha256)
        budget_adapter = coordinator._load_helper(paths["cost_observer_budget"], "_dimension_cost_observer_budget",
            expected_budget_adapter_sha256)
        result["observer_budget_adapter_policy"] = budget_adapter.callback_limit_policy()
        _require(result["observer_budget_adapter_policy"]["all_profile_callback_cap"] ==
                 CALLBACK_LIMIT_POLICY["max_callback_events"], "adapter callback budget differs from declared envelope")
        cleanup = coordinator._load_helper(paths["cleanup_helper"], "_dimension_cleanup", CLEANUP_SHA)
        result["hardware"] = {"torch": str(torch.__version__), "cuda_runtime": torch.version.cuda,
            "device_index": device, "name": torch.cuda.get_device_name(device), "capability": list(torch.cuda.get_device_capability(device)),
            "actual_initial_cuda_kernel": synthetic._initial_kernel(torch, device) == [4.]}
        torch.cuda.reset_peak_memory_stats(device)
        span, batch = modules["legal_span_formula"], modules["legal_span_device_batch_inference"]
        classes = ({"original": batch.DeviceBatchedDimensionalSpanSession,
                    "bitwise_v1": modules["legal_span_device_bitwise_inference"].DeviceBitwiseDimensionalSpanSession}
            if dimension == 768 else {"original": modules["legal_span_4096_device_inference"].DeviceLeanstral4096SpanSession,
                "bitwise_v1": modules["legal_span_4096_bitwise_device_inference"].BitwiseDeviceLeanstral4096SpanSession,
                "bitwise_v2": modules["legal_span_4096_bitwise_device_inference_v2"].BitwiseDeviceLeanstral4096SpanSession})
        references, numeric_references = {}, {}
        def open_lane(route, optimized):
            cancel.poll()
            options = {"expected_checkpoint_sha256": checkpoint_sha, "optimized": optimized, "scheduler": scheduler,
                "parent_lease": root, "cancel_event": cancel, "admission_timeout_seconds": admission_timeout_seconds,
                "max_seconds": MAX_SECONDS, "memory_mb": CHILD_RAM, "gpu_memory_mb": CHILD_GPU, "unified_memory_mb": CHILD_UNIFIED}
            if dimension == 4096:
                options["synthetic_unreceipted"] = True
            started = time.monotonic()
            with _forbidden_calls(torch, modules, counters):
                owner = classes[route](deepcopy(checkpoint), **options)
            lane = DimensionLane(owner, dimension)
            active.append(lane)
            label = route + ("_cuda" if optimized else "_cpu_opt_out")
            result["owned_children"].append({"route": label, "lease_id": lane.lease_id,
                "admission": lane.child_lease.to_dict(), "release_observed": False})
            record = result["lanes"][label] = {"route": route, "optimized": optimized,
                "constructor_seconds": time.monotonic() - started, "profile": lane.describe(),
                "state_before": trained._state_pin(owner, "span"), "counts": {}}
            _require(record["state_before"] == result["checkpoint_model_pin"], "restored tensors differ from fixed checkpoint")
            _require(owner._device == (f"cuda:{device}" if optimized else "cpu"), "requested route device differs")
            _require(coordinator._settings(torch) == result["ambient_settings_before_producer_imports_and_models"],
                     "constructor changed ambient policy")
            return label, lane
        def canonical(report):
            return trained._decisions(report, "span") if dimension == 768 else synthetic._decision_projection(report)
        def save_public(label, lane, count, phase):
            cancel.poll()
            # Copies and RNG observations precede the diagnostic interval.
            texts, vectors = deepcopy(inputs["texts"][:count]), deepcopy(inputs["vectors"][:count])
            options = ({} if dimension == 4096 else {"embedding_receipts": deepcopy(inputs["receipts"][:count]),
                "expected_receipt_sha256s": inputs["receipt_pins"][:count]})
            cpu_rng, cuda_rng = torch.random.get_rng_state(), torch.cuda.get_rng_state(device)
            invoke = lambda: lane.owner.decode_formal_logic(texts, vectors, **options)
            torch.cuda.synchronize(device)
            started = time.monotonic()
            with _forbidden_calls(torch, modules, counters):
                if phase == "profiled":
                    background = [root._heartbeat_thread, *(owned.child_lease._heartbeat_thread
                        for owned in active if not owned.child_lease.released)]
                    observer = budget_adapter.GuardCostObserver(_registry(profiler, modules, paths, lane.owner._model),
                        expected_main_profiler=sys.getprofile(), allowed_background_threads=background,
                        utility_source_role="cost_profiler", max_events=4000000, max_spans=20000, max_threads=32)
                    report, python_cost, operators = profiler.profile_public_call(torch, observer, invoke,
                        device=device, max_operator_events=15000)
                else:
                    report = invoke()
            torch.cuda.synchronize(device)
            elapsed = time.monotonic() - started
            _require(type(elapsed) is float and math.isfinite(elapsed) and elapsed > 0, "positive diagnostic interval required")
            _require(torch.equal(cpu_rng, torch.random.get_rng_state()) and torch.equal(cuda_rng, torch.cuda.get_rng_state(device)),
                     "diagnostic inference changed RNG")
            stem = f"{label}-{count}-{phase}"
            decision = canonical(report)
            if count in references:
                _require(_wire(decision) == _wire(references[count]), "complete canonical decisions differ from original CPU")
            observed = {"result": evidence.json(stem + "-result.json", report),
                "decision_projection": evidence.json(stem + "-decision-projection.json", decision),
                "elapsed_seconds": elapsed, "cpu_cuda_rng_unchanged": True,
                "elapsed_seconds_scope": "outer_diagnostic_interval_including_registry_profiler_startup_drain_and_completion_sync",
                "caller_input_copies_before_interval": True, "instrumented": phase == "profiled",
                "instrumented_durations_qualify_speedup": False, "canonical_matches_original_cpu": count in references}
            result["total_return_count"] += 1
            if phase == "profiled":
                roots = [span for span in python_cost["spans"]
                    if python_cost["registry"][span[3]]["label"] == "complete_public_call"]
                _require(len(roots) == 1, "one complete instrumented public call span required")
                observed["instrumented_public_call_wall_ns"] = roots[0][8]
                observed["instrumented_public_call_thread_cpu_ns"] = roots[0][10]
                observed["python_costs"] = evidence.json(stem + "-python-costs.json", python_cost)
                observed["operators"] = evidence.json(stem + "-operators.json", operators)
                result["profiled_return_count"] += 1
                result["profiled_calls"].append({"route": label, "count": count, **observed})
            cancel.poll()
            return observed, decision
        def numeric(label, lane, count, *, singleton):
            cancel.poll()
            with _forbidden_calls(torch, modules, counters):
                if dimension == 768:
                    rows, scope = trained._span_logits(torch, span, batch, lane, inputs, count, singleton=singleton)
                else:
                    records = [{"tokens": span.tokenize_source(text), "latent": vector}
                        for text, vector in zip(inputs["texts"][:count], inputs["vectors"][:count])]
                    if singleton:
                        rows, scopes = [], []
                        for record in records:
                            values, one_scope = synthetic._checked_private_logits(torch, span, lane.owner, [record])
                            rows.append({name: values[name] for name in values})
                            scopes.append(one_scope)
                        scope = {"scope": "separate_checked_private_four_logits", "singletons": True,
                            "entry_and_exit_owned_checks": True, "per_singleton_scopes": scopes}
                    else:
                        values, scope = synthetic._checked_private_logits(torch, span, lane.owner, records)
                        rows = _rows_from_batched_logits(values, [len(record["tokens"]) for record in records])
                        scope = {**scope, "singletons": False}
            panel = {"complete_four_logits": evidence.json(f"{label}-{count}-four-logits.json", rows),
                "numeric_scope": evidence.json(f"{label}-{count}-numeric-scope.json", scope)}
            if count in numeric_references:
                panel["max_abs_errors"] = trained._four_errors(numeric_references[count], rows)
            result["numeric_snapshot_count"] += 1
            return panel, rows
        def close_lane(label, lane):
            record = result["lanes"][label]
            record["state_after"] = trained._state_pin(lane.owner, "span")
            _require(record["state_after"] == result["checkpoint_model_pin"] and _wire(lane.owner._checkpoint) == _wire(checkpoint),
                     "inference changed checkpoint/model/Adam")
            record["checkpoint_and_adam_unchanged"] = True
            cancel.clear()
            lane.close(torch, device)
        for route in ROUTES[dimension]:
            label, lane = open_lane(route, False)
            for count in COUNTS:
                public, decisions = save_public(label, lane, count, "reference")
                panel, logits = numeric(label, lane, count, singleton=True)
                result["lanes"][label]["counts"][str(count)] = {"reference": public, **panel}
                if route == "original":
                    references[count], numeric_references[count] = decisions, logits
            close_lane(label, lane)
            lane = None
        cuda_lanes = {}
        for route in ROUTES[dimension]:
            label, lane = open_lane(route, True)
            cuda_lanes[label] = lane
        result["joint_cuda_admission"] = {"child_leases": {label: lane.child_lease.to_dict() for label, lane in cuda_lanes.items()},
            "resources": scheduler.snapshot(), "all_requested_children_live": all(not lane.child_lease.released for lane in cuda_lanes.values())}
        for label, lane in cuda_lanes.items():
            for count in COUNTS:
                warmup, _ = save_public(label, lane, count, "reference")
                measured, _ = save_public(label, lane, count, "profiled")
                panel, _ = numeric(label, lane, count, singleton=False)
                result["lanes"][label]["counts"][str(count)] = {"reference": warmup, "profiled": measured, **panel}
            with _forbidden_calls(torch, modules, counters):
                if dimension == 768 and label.startswith("bitwise"):
                    result["lanes"][label]["corruption_controls"] = trained._new_controls(torch, lane, inputs, cancel)
                elif dimension == 4096:
                    result["lanes"][label]["corruption_controls"] = synthetic._paired_reference_refusals(lane.owner, inputs["texts"], inputs["vectors"])
                    result["lanes"][label]["model_only_subnormal_control"] = synthetic._model_only_subnormal_control(lane.owner, inputs["texts"], inputs["vectors"])
            close_lane(label, lane)
        cuda_lanes.clear()
        lane = None
        count_routes = len(ROUTES[dimension])
        _require(result["total_return_count"] == 9 * count_routes and result["profiled_return_count"] == 3 * count_routes
                 and result["numeric_snapshot_count"] == 6 * count_routes and len(result["owned_children"]) == 2 * count_routes,
                 "complete declared dimension profiling coverage required")
        _require(all(value == 0 for value in counters.values()), "diagnostic attempted forbidden work")
        result["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
        result["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
        _require(result["gpu_peak_allocated_bytes"] <= ROOT_GPU * 1024**2, "observed Torch allocation exceeds root GPU reservation")
        result["qualified"] = True
    except BaseException as error:
        result["qualified"] = False
        result["error"] = {"type": type(error).__name__, "detail": str(error), "traceback": traceback.format_exc(limit=14)}
    finally:
        if cancel is not None:
            cancel.clear()
        for lane in reversed(active):
            try:
                lane.close(torch, device)
            except BaseException as error:
                safe_close = False
                result.setdefault("close_errors", []).append({"type": type(error).__name__, "detail": str(error)})
        gc.collect()
        if cleanup is not None and safe_close:
            try:
                cleanup._cleanup_owned_cuda(torch, device, result)
            except BaseException as error:
                safe_close = False
                result["cleanup_error"] = {"type": type(error).__name__, "detail": str(error)}
        elif device is not None:
            safe_close = False
        try:
            result["currentness_after"] = []
            for entry in staged:
                current = coordinator._pin(entry["current"]["path"])
                _require(current == entry["current"], "source/fixture/configuration changed")
                result["currentness_after"].append(current)
            result["retained_sources_fixtures_configuration_unchanged"] = True
        except BaseException as error:
            result["qualified"] = False
            result["currentness_error"] = {"type": type(error).__name__, "detail": str(error)}
        if torch is not None and old_threads is not None:
            try:
                result["ambient_settings_after_owned_cleanup_before_thread_restore"] = coordinator._settings(torch)
                _require(result["ambient_settings_after_owned_cleanup_before_thread_restore"] ==
                         result["ambient_settings_before_producer_imports_and_models"], "inference/cleanup changed ambient policy")
            except BaseException as error:
                result["qualified"] = False
                result["ambient_policy_error"] = {"type": type(error).__name__, "detail": str(error)}
            finally:
                torch.set_num_threads(old_threads)
            result["ambient_settings_after_thread_restore"] = coordinator._settings(torch)
            if result["ambient_settings_after_thread_restore"] != result["ambient_settings_before_thread_reservation"]:
                result["qualified"] = False
                result["ambient_policy_error"] = {"type": "ValueError", "detail": "original thread/default policy not restored"}
            result["ambient_precision_default_policy_unchanged"] = "ambient_policy_error" not in result
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
            result["root_release_observed"] = result["own_root_lease_released"] = root.released
        else:
            result["root_release_observed"] = result["own_root_lease_released"] = False
        if scheduler is not None:
            result["resources_after"] = scheduler.snapshot()
        result.update(counters)
        result["safe_owned_cleanup_established"] = safe_close
        result["elapsed_seconds_total"] = time.monotonic() - began
        result["elapsed_seconds_after_root_admission"] = time.monotonic() - admitted if admitted is not None else None
        if not safe_close or (root is not None and not root.released) or (admitted is not None and result["elapsed_seconds_after_root_admission"] > MAX_SECONDS):
            result["qualified"] = False
        if result["qualified"] is False and result["error"] is None:
            result["error"] = {"type": "DiagnosticClosureFailure", "detail": "source, policy, deadline or owned cleanup did not close"}
        result["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if evidence is not None:
            result["evidence_files_except_result"] = list(evidence.files)
            result["evidence_bytes_except_result"] = evidence.bytes
            result["evidence_limits"] = {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES,
                "max_total_bytes": MAX_TOTAL_BYTES, "result_included_in_limits": True}
            evidence.json("result.json", result, final=True)
        else:
            raw = _wire(result)
            _require(len(raw) <= MAX_FILE_BYTES, "bounded early refusal required")
            descriptor = os.open(output / "result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o444)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--configuration", required=True, type=Path)
    parser.add_argument("--dimension", required=True, type=int, choices=(768, 4096))
    parser.add_argument("--expected-profiler-sha256", required=True)
    parser.add_argument("--expected-budget-adapter-sha256", required=True)
    parser.add_argument("--admission-timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    result = run(args.output, args.configuration, dimension=args.dimension,
        expected_profiler_sha256=args.expected_profiler_sha256, expected_budget_adapter_sha256=args.expected_budget_adapter_sha256,
        admission_timeout_seconds=args.admission_timeout_seconds)
    print(json.dumps({"qualified": result["qualified"], "dimension": args.dimension,
        "result": str(args.output.absolute() / "result.json"), "error": result["error"]}, sort_keys=True), flush=True)
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
