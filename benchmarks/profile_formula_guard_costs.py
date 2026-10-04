"""Bounded, inference-only guard cost diagnostics for retained 8D/384D heads.

Instrumented wall and CPU times are diagnostics, never speed qualification.
Source-bound Python spans and exact scheduler C calls accompany compact native
Torch CPU/CUDA events. All original guard boundaries, numerical returns and
ownership checks remain enabled. No shared producer/framework method is replaced.
Native trace collection is bounded by the admitted fixed workload, not by an
allocator enforcement mechanism; event and artifact limits are checked afterward.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
import argparse
import fcntl
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
import stat
import sys
import threading
import time
import traceback

SCHEMA = "retained-trained-formula-guard-cost-profile/v1"
PYTHON_SCHEMA = "source-bound-guard-call-costs/v1"
OPERATOR_SCHEMA = "bounded-torch-operator-costs/v1"
CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
COORDINATOR_SHA = "e8b9634c6e905d0c63e7eba067e86a034796537f08d758d548a1d22123190ed8"
HELPERS_SHA = "29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110"
CLEANUP_SHA = "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c"
READER_HELPERS_SHA = "f38e215b5052242b682ad2e6a5b2e2631588a8f98957c75e8b3f3137a9475c53"
SCHEDULER_SHA = "f156511991e33d3b4ba523c3c5080ea30d0a53ad8a4dbcccea0487432679a9aa"
V1_SHA = "5b5631eb1cf779ea8b6fcf3073d074355f52ef8c74adea84fc595421dea85089"
V2_SHA = "ebc7f8242ec3a4852be4c025b4ef818bc48e74add7634935ec403e1bd3c6dfb9"
MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_FILES = 8388608, 67108864, 1024
MAX_EVENTS, MAX_SPANS, MAX_THREADS, MAX_OPERATOR_EVENTS = 1000000, 20000, 32, 50000
MAX_SECONDS = 120
PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
COUNTS = (1, 16, 32)
CPU_LANES = ("original_cpu_reference", "bitwise_v1_cpu_opt_out", "bitwise_v2_cpu_opt_out")
CUDA_LANES = ("original_cuda", "bitwise_v1_cuda", "bitwise_v2_cuda")
SPAN_COLUMNS = ("id", "parent_id", "thread_id", "registry_id", "start_wall_ns", "end_wall_ns",
    "start_thread_cpu_ns", "end_thread_cpu_ns", "inclusive_wall_ns", "exclusive_wall_ns",
    "inclusive_thread_cpu_ns", "exclusive_thread_cpu_ns", "return_event")
AGGREGATE_COLUMNS = ("thread_scope", "registry_id", "call_count", "inclusive_wall_ns",
    "exclusive_wall_ns", "inclusive_thread_cpu_ns", "exclusive_thread_cpu_ns", "c_exception_count")
OPERATOR_COLUMNS = ("id", "name_id", "device_type_id", "device_index", "thread_id",
    "start_us", "end_us", "cpu_total_us", "cpu_self_us", "device_total_us", "device_self_us")
OPERATOR_AGGREGATE_COLUMNS = ("name_id", "device_type_id", "count", "cpu_total_us",
    "cpu_self_us", "device_total_us", "device_self_us")
_FSYNC, _FLOCK, _REPLACE = os.fsync, fcntl.flock, os.replace


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


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
                 "bounded ordinary single-link file required")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_size == before.st_size,
                     "opened ordinary input differs")
            raw = stream.read(MAX_FILE_BYTES + 1)
            after_open = os.fstat(stream.fileno())
        after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        latest = _directory_fd(path.parent)
        try:
            current_parent = os.fstat(latest)
            _require((current_parent.st_dev, current_parent.st_ino) == (parent_before.st_dev, parent_before.st_ino),
                     "ordinary input parent changed")
        finally:
            os.close(latest)
    finally:
        os.close(parent)
    identities = [(part.st_dev, part.st_ino, part.st_size, part.st_mtime_ns, part.st_ctime_ns, part.st_nlink)
                  for part in (before, opened, after_open, after)]
    _require(len(raw) == before.st_size and all(part == identities[0] for part in identities[1:]),
             "ordinary input changed while reading")
    return raw


def _pin(path, raw=None):
    raw = _read(path) if raw is None else raw
    return {"path": str(Path(path).absolute()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _load_helper(path, name, expected):
    _require(_pin(path)["sha256"] == expected, "current helper source differs")
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    _require(_pin(path)["sha256"] == expected, "current helper changed during import")
    return module


def _settings(torch):
    cudnn = torch.backends.cudnn
    flags = {name: getattr(cudnn, name) for name in
             ("enabled", "benchmark", "benchmark_limit", "deterministic", "allow_tf32")}
    for name in ("fp32_precision", "depthwise_kernel"):
        if hasattr(cudnn, name):
            flags[name] = getattr(cudnn, name)
    return {"cudnn": flags, "cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "default_dtype": str(torch.get_default_dtype()), "default_device": str(torch.get_default_device()),
        "autocast_cpu_enabled": torch.is_autocast_enabled("cpu"),
        "autocast_cuda_enabled": torch.is_autocast_enabled("cuda"),
        "deterministic_algorithms_enabled": torch.are_deterministic_algorithms_enabled(),
        "deterministic_algorithms_warn_only": torch.is_deterministic_algorithms_warn_only_enabled(),
        "num_threads": torch.get_num_threads()}


def register(registry, label, function, source_role):
    """Bind an actual loaded Python code object; unwrap generator decorators."""
    function = function.fget if isinstance(function, property) else getattr(function, "__func__", function)
    function = inspect.unwrap(function)
    code = getattr(function, "__code__", None)
    _require(code is not None, "Python source code required for registry")
    descriptor = {"label": label, "source_role": source_role, "function_qualname": code.co_qualname,
        "firstlineno": code.co_firstlineno, "code_sha256": hashlib.sha256(code.co_code).hexdigest(),
        "kind": "generator_segment" if code.co_flags & inspect.CO_GENERATOR else "python"}
    if code in registry:
        _require(registry[code] == descriptor, "ambiguous registered source code")
    else:
        registry[code] = descriptor


def build_registry(modules, *, owners=(), extra=()):
    """Select high-level costs; recursive checkpoint atom matching is omitted."""
    registry = {}
    functions = {
        "modal_latent_formula": ("_source_sha256", "_pins", "_implementation", "_restore", "_rows"),
        "modal_latent_formula_inference": ("_source_sha256", "inference_implementation", "_validated_rows"),
        "modal_latent_formula_device_inference": ("_source_sha256", "inference_implementation"),
        "modal_latent_formula_bitwise_device_inference": ("_source_sha256", "inference_implementation"),
        "modal_latent_formula_bitwise_device_inference_v2": ("_source_sha256", "_check_bindings",
            "_base_current_implementation", "_implementation_receipt", "inference_implementation"),
        "checkpoint_content_guard": ("_source_sha256", "inference_implementation", "_raw"),
        "owned_tensor_bitwise_guard": ("_source_sha256", "inference_implementation", "_plan", "check_owned_tensor_bytes"),
        "owned_tensor_value_guard": ("_source_sha256", "inference_implementation", "check_owned_tensor_values"),
    }
    for role, names in functions.items():
        module = modules.get(role)
        if module is None:
            continue
        for name in names:
            if hasattr(module, name):
                register(registry, role + "." + name, getattr(module, name), role)
    class_methods = {
        "resource_scheduler": (("GlobalResourceScheduler", ("renew", "is_cancelled", "_locked_state", "_recover_stale_locked")),
                              ("ResourceLease", ("renew", "cancelled", "to_dict", "_heartbeat_loop"))),
        "checkpoint_content_guard": (("CheckpointContentGuard", ("__init__", "matches", "check")),),
        "modal_latent_formula": (("LatentFormulaDecoder", ("_check",)),),
        "modal_latent_formula_inference": (("BatchedLatentFormulaDecoder",
            ("_check", "_infer", "_decode_scalar", "_decode_batch", "_decoded")),),
        "modal_latent_formula_device_inference": (("DeviceLatentFormulaDecoder", ("_check", "_infer")),),
        "modal_latent_formula_bitwise_device_inference": (("BitwiseDeviceLatentFormulaDecoder",
            ("_poll", "_pure_check", "_byte_plan", "_storage_layout", "_state_bytes",
             "_check_reference_anchor", "_check", "_infer", "_synchronize")),),
        "modal_latent_formula_bitwise_device_inference_v2": (("BitwiseDeviceLatentFormulaDecoder",
            ("_check_guard_identities", "_check", "_infer")),),
    }
    # Register only definitions belonging to this role; inherited duplicates
    # would otherwise give the same code two different descriptor identities.
    for role, declarations in class_methods.items():
        module = modules.get(role)
        if module is None:
            continue
        for class_name, names in declarations:
            owner = getattr(module, class_name)
            for name in names:
                if name in owner.__dict__:
                    register(registry, role + "." + class_name + "." + name, owner.__dict__[name], role)
    for owner, role in owners:
        model = owner.model if hasattr(owner, "model") else owner._model
        for name in ("project", "start", "next_logits", "forward"):
            method = getattr(model, name, None)
            function = getattr(method, "__func__", method)
            if (method is not None and getattr(function, "__code__", None) is not None
                    and Path(function.__code__.co_filename).absolute() == Path(modules[role].__file__).absolute()):
                register(registry, role + ".model." + name, method, role)
    for label, function, role in extra:
        register(registry, label, function, role)
    return registry


class GuardCostObserver:
    """Selected source-call tree, preserving an explicitly allowed main hook.

    Exclusive cost subtracts direct selected children; unselected work stays
    with its nearest selected parent. Generator yields end one resumption
    segment. Background observation is restricted to supplied owned heartbeat
    Thread objects created with an empty default hook in this fresh worker.
    Overflow marks refusal after the operation; callbacks never interrupt guards.
    """
    def __init__(self, registry, *, expected_main_profiler=None, allowed_background_threads=(),
                 utility_source_role="benchmark", max_events=MAX_EVENTS, max_spans=MAX_SPANS,
                 max_threads=MAX_THREADS):
        _require(type(registry) is dict and registry, "nonempty code registry required")
        for value, maximum in ((max_events, MAX_EVENTS), (max_spans, MAX_SPANS), (max_threads, MAX_THREADS)):
            _require(type(value) is int and 1 <= value <= maximum, "bounded observer limit required")
        self.main_thread_id = threading.get_ident()
        self.expected_main_profiler = expected_main_profiler
        self.allowed_background_threads = tuple(thread for thread in allowed_background_threads if thread is not None)
        self.utility_source_role = utility_source_role
        self.max_events, self.max_spans, self.max_threads = max_events, max_spans, max_threads
        self.registry = []
        self.codes = {}
        for code, descriptor in registry.items():
            self.codes[code] = len(self.registry)
            self.registry.append({"id": len(self.registry), **descriptor})
        self.manual_id = len(self.registry)
        self.registry.append({"id": self.manual_id, "label": "complete_public_call",
            "source_role": utility_source_role, "function_qualname": "complete_public_call",
            "firstlineno": 0, "code_sha256": None, "kind": "manual"})
        self.c_functions = {}
        for label, function in (("os.fsync", _FSYNC), ("fcntl.flock", _FLOCK), ("os.replace", _REPLACE)):
            self.c_functions[function] = len(self.registry)
            self.registry.append({"id": len(self.registry), "label": label, "source_role": "resource_scheduler",
                "function_qualname": label, "firstlineno": 0, "code_sha256": None, "kind": "cfunction"})
        self.stacks, self.threads, self.records = {}, {}, []
        self.censored_background = []
        self.callbacks = self.next_id = 0
        self.overflow, self.unsupported_thread_observed, self.hooks_restored = False, False, False
        self.window_start_ns = self.window_end_ns = None
        self._running = False

    def _thread(self):
        identity = threading.get_ident()
        if identity not in self.threads:
            if len(self.threads) >= self.max_threads:
                self.overflow = True
                return None
            if identity != self.main_thread_id and identity not in self.background_ids:
                self.unsupported_thread_observed = True
                return None
            self.threads[identity] = "inline_main" if identity == self.main_thread_id else "owned_background"
            self.stacks[identity] = []
        return identity

    def _push(self, identity, token, descriptor_id):
        if self.next_id + len(self.censored_background) >= self.max_spans:
            self.overflow = True
            return
        stack = self.stacks[identity]
        self.next_id += 1
        stack.append({"id": self.next_id, "parent": stack[-1]["id"] if stack else 0,
            "token": token, "registry": descriptor_id, "wall": time.perf_counter_ns(),
            "cpu": time.thread_time_ns(), "child_wall": 0, "child_cpu": 0})

    def _pop(self, identity, token, event):
        stack = self.stacks[identity]
        if not stack or stack[-1]["token"] != token:
            if identity == self.main_thread_id:
                self.overflow = True
            else:
                if self.next_id + len(self.censored_background) >= self.max_spans:
                    self.overflow = True
                else:
                    self.censored_background.append({"edge": "entered_before_window", "thread_id": identity,
                        "registry_id": None, "return_event": event, "observed_wall_ns": time.perf_counter_ns()})
            return
        value = stack.pop()
        wall, cpu = time.perf_counter_ns(), time.thread_time_ns()
        inclusive_wall, inclusive_cpu = wall - value["wall"], cpu - value["cpu"]
        exclusive_wall, exclusive_cpu = inclusive_wall - value["child_wall"], inclusive_cpu - value["child_cpu"]
        if min(inclusive_wall, inclusive_cpu, exclusive_wall, exclusive_cpu) < 0:
            self.overflow = True
            return
        self.records.append([value["id"], value["parent"], identity, value["registry"], value["wall"], wall,
            value["cpu"], cpu, inclusive_wall, exclusive_wall, inclusive_cpu, exclusive_cpu, event])
        if stack:
            stack[-1]["child_wall"] += inclusive_wall
            stack[-1]["child_cpu"] += inclusive_cpu

    def _observe(self, frame, event, arg):
        self.callbacks += 1
        if self.callbacks > self.max_events:
            self.overflow = True
        if not self.overflow:
            descriptor = self.codes.get(frame.f_code)
            c_event = event in ("c_call", "c_return", "c_exception")
            if c_event:
                source = self.registry[descriptor] if descriptor is not None else None
                # Only exact native scheduler generator frames qualify. A
                # same-named function elsewhere cannot contribute fsync cost.
                if (source is None or source["source_role"] != "resource_scheduler"
                        or not source["function_qualname"].endswith("._locked_state")):
                    descriptor = None
                else:
                    descriptor = self.c_functions.get(arg)
            if descriptor is not None and event in ("call", "return", "c_call", "c_return", "c_exception"):
                identity = self._thread()
                if identity is not None:
                    token = (id(frame), id(arg) if c_event else None)
                    if event in ("call", "c_call"):
                        self._push(identity, token, descriptor)
                    else:
                        before = len(self.censored_background)
                        self._pop(identity, token, event)
                        if len(self.censored_background) != before:
                            self.censored_background[-1]["registry_id"] = descriptor
        if threading.get_ident() == self.main_thread_id and self.previous_main is not None:
            self.previous_main(frame, event, arg)

    def __enter__(self):
        _require(not self._running, "observer cannot be reentered")
        _require(os.fsync is _FSYNC and fcntl.flock is _FLOCK and os.replace is _REPLACE,
                 "scheduler C callable identity changed")
        self.previous_main, self.previous_default = sys.getprofile(), threading.getprofile()
        _require(self.previous_main is self.expected_main_profiler and self.previous_default is None,
                 "unsupported existing main/default profiling hook")
        self.background_ids = set()
        supplied = set(self.allowed_background_threads)
        for thread in threading.enumerate():
            if thread.ident == self.main_thread_id:
                continue
            target = getattr(thread, "_target", None)
            function = getattr(target, "__func__", None)
            descriptor = self.codes.get(getattr(function, "__code__", None))
            _require(thread in supplied and descriptor is not None
                     and self.registry[descriptor]["source_role"] == "resource_scheduler"
                     and self.registry[descriptor]["function_qualname"].endswith("._heartbeat_loop"),
                     "unapproved existing Python background thread")
            self.background_ids.add(thread.ident)
        _require(hasattr(threading, "setprofile_all_threads"), "all-owned-thread profiling requires supported Python")
        self.window_start_ns = time.perf_counter_ns()
        self._running = True
        threading.setprofile_all_threads(self._observe)
        return self

    @contextmanager
    def public_scope(self):
        identity = self._thread()
        token = ("manual", self.next_id + 1)
        self._push(identity, token, self.manual_id)
        try:
            yield
        finally:
            if not self.overflow:
                self._pop(identity, token, "manual_return")

    def __exit__(self, *error):
        # Restore the empty prior default/background hooks first, then the
        # permitted source-bound main counter hook. No background foreign
        # hook is overwritten under this fresh-owned-thread admission.
        threading.setprofile_all_threads(self.previous_default)
        sys.setprofile(self.previous_main)
        self.window_end_ns = time.perf_counter_ns()
        self._running = False
        self.hooks_restored = sys.getprofile() is self.previous_main and threading.getprofile() is self.previous_default
        for identity, stack in self.stacks.items():
            if identity == self.main_thread_id:
                if stack:
                    self.overflow = True
                continue
            for value in stack:
                self.censored_background.append({"edge": "unfinished_at_window_end", "thread_id": identity,
                    "id": value["id"], "parent_id": value["parent"], "registry_id": value["registry"],
                    "start_wall_ns": value["wall"], "start_thread_cpu_ns": value["cpu"]})
            stack.clear()
        return False

    def spans(self):
        return sorted(self.records, key=lambda value: value[0])

    def summary(self):
        _require(not self._running and self.window_end_ns is not None, "completed observer required")
        aggregates = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
        for row in self.records:
            key = (self.threads[row[2]], row[3])
            value = aggregates[key]
            for index, item in enumerate((1, row[8], row[9], row[10], row[11], int(row[12] == "c_exception"))):
                value[index] += item
        return {"schema": PYTHON_SCHEMA, "instrumented": True, "performance_qualified": False,
            "clock": {"wall": "perf_counter_ns", "cpu": "thread_time_ns", "operator_clock_alignment_claimed": False},
            "observer_overhead_scope": "callback_and_native_profiler_overhead_included_not_measured_or_subtracted",
            "exclusive_scope": "inclusive_minus_direct_selected_children_unselected_work_stays_with_parent",
            "generator_scope": "resumption_segments_not_logical_transactions",
            "background_scope": "windowed_owned_python_threads_prior_default_none_edges_censored_no_whole_job_coverage",
            "background_activity_claim": "observed_events_only_absence_is_not_zero_activity_attestation",
            "main_thread_id": self.main_thread_id, "window_start_ns": self.window_start_ns,
            "window_end_ns": self.window_end_ns, "callback_events_observed": self.callbacks,
            "bounds": {"max_events": self.max_events, "max_spans": self.max_spans, "max_threads": self.max_threads},
            "overflow": self.overflow, "unsupported_thread_observed": self.unsupported_thread_observed,
            "hooks_restored": self.hooks_restored,
            "censored_background": deepcopy(self.censored_background),
            "background_censor_scope": "complete_spans_only_partial_start_or_end_not_added_to_completed_costs",
            "registry": deepcopy(self.registry),
            "threads": [{"thread_id": identity, "scope": scope} for identity, scope in sorted(self.threads.items())],
            "span_columns": list(SPAN_COLUMNS), "spans": self.spans(),
            "aggregate_columns": list(AGGREGATE_COLUMNS),
            "aggregates": [[scope, identifier, *items] for (scope, identifier), items in sorted(aggregates.items())]}


def _operator_trace(profiler, *, max_events):
    _require(type(max_events) is int and 1 <= max_events <= MAX_OPERATOR_EVENTS, "bounded operator event limit required")
    actual = profiler.events()
    _require(0 < len(actual) <= max_events, "native operator collection exceeded postcollection event bound")
    names, devices, name_ids, device_ids, rows = [], [], {}, {}, []
    aggregates = defaultdict(lambda: [0, 0., 0., 0., 0.])
    for index, event in enumerate(actual):
        name, device = str(event.name), str(event.device_type)
        _require(0 < len(name) <= 4096 and 0 < len(device) <= 128, "bounded native operator labels required")
        if name not in name_ids:
            _require(len(names) < 4096, "bounded distinct operator names required")
            name_ids[name] = len(names)
            names.append(name)
        if device not in device_ids:
            _require(len(devices) < 16, "bounded distinct device types required")
            device_ids[device] = len(devices)
            devices.append(device)
        values = [float(event.time_range.start), float(event.time_range.end),
            float(event.cpu_time_total), float(event.self_cpu_time_total),
            float(event.device_time_total), float(event.self_device_time_total)]
        _require(all(math.isfinite(value) and value >= 0 for value in values) and values[1] >= values[0],
                 "finite nonnegative native event durations required")
        row = [index, name_ids[name], device_ids[device], int(event.device_index), int(event.thread), *values]
        rows.append(row)
        items = aggregates[(row[1], row[2])]
        for slot, value in enumerate((1, *values[2:])):
            items[slot] += value
    cuda_count = sum(1 for row in rows if devices[row[2]].endswith(".CUDA"))
    _require(cuda_count > 0, "actual native CUDA operator activity required")
    return {"schema": OPERATOR_SCHEMA, "instrumented": True, "performance_qualified": False,
        "activities": ["CPU", "CUDA"], "record_shapes": False, "profile_memory": False, "with_stack": False,
        "clock": "native_profiler_relative_microseconds_alignment_to_python_clock_not_claimed",
        "collection_bound_scope": "fixed_admitted_workload_only_native_buffer_allocation_not_enforced",
        "postcollection_event_limit": max_events, "event_count": len(rows), "cuda_event_count": cuda_count,
        "names": names, "device_types": devices, "event_columns": list(OPERATOR_COLUMNS), "events": rows,
        "aggregate_columns": list(OPERATOR_AGGREGATE_COLUMNS),
        "aggregates": [[name, device, *items] for (name, device), items in sorted(aggregates.items())]}


def profile_public_call(torch, observer, invoke, *, device, max_operator_events=MAX_OPERATOR_EVENTS):
    """Return (public result, Python profile, compact native operator trace).

    Profiler startup/teardown sits outside the manual public-call span. That
    span includes completion synchronization. Captured timings have observer
    overhead and are not compared to qualified uninstrumented measurements.
    """
    torch.cuda.synchronize(device)
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA],
            record_shapes=False, profile_memory=False, with_stack=False) as profiler:
        with observer:
            with observer.public_scope():
                returned = invoke()
                torch.cuda.synchronize(device)
    summary = observer.summary()
    _require(not summary["overflow"] and not summary["unsupported_thread_observed"] and summary["hooks_restored"],
             "bounded source observer completion required")
    return returned, summary, _operator_trace(profiler, max_events=max_operator_events)


def run(output, configuration, *, admission_timeout_seconds=30):
    _require(type(admission_timeout_seconds) is int and 1 <= admission_timeout_seconds <= 60, "bounded admission timeout required")
    _require(sys.getprofile() is None and threading.getprofile() is None, "fresh worker with empty profiling hooks required")
    output, configuration = Path(output).absolute(), Path(configuration).absolute()
    _require(output.parent.resolve(strict=True) == output.parent, "canonical existing output parent required")
    output.mkdir(parents=False)
    (output / "producers").mkdir()
    (output / "fixtures").mkdir()
    began = time.monotonic()
    result = {"schema": SCHEMA, "qualified": False, "diagnostic_profile_qualified": False, "error": None,
        "scope": "retained_trained_formula8_formula384_original_v1_v2_instrumented_guard_costs",
        "instrumented": True, "performance_qualified": False, "complete_call_measurements_qualified": False,
        "conservative_complete_call_gain_observed": False, "selected_existing_profile_changed": False,
        "production_qualified": False, "proof_authority": False, "execution_attestation": False,
        "semantic_correctness_verified": False, "fresh_encoder_execution_qualified": False,
        "native_encoder_origin_authenticated": False, "kernel_resource_enforcement": False,
        "universal_speedup_claimed": False, "foreign_process_actions": False,
        "persistent_precision_policy_mutated": False, "source_pins": [], "fixture_pins": [],
        "families": {}, "owned_children": [], "pid": os.getpid(), "total_return_count": 0,
        "profiled_return_count": 0, "formula_projection_count": 0,
        "retained_fixture_positive_steps": {"8": 30, "384": 30}, "max_seconds_after_root_admission": MAX_SECONDS,
        "admission_timeout_seconds": admission_timeout_seconds,
        "counter_observation_scope": "constructors_references_warmups_controls_and_profiled_main_calls_source_bound_no_execution_attestation",
        "profile_scope": "one_instrumented_cuda_probe_per_route_count_no_repeatability_or_speed_claim",
        "native_trace_buffer_scope": "workload_bounded_postcollection_limits_no_allocator_enforcement"}
    counters = {"optimizer_restore_attempts": 0, "optimizer_constructor_calls": 0, "optimizer_steps": 0,
        "training_calls": 0, "new_training_fits": 0, "training_mode_true_calls": 0, "encoder_calls": 0,
        "constructor_observations": []}
    torch = scheduler = root = device = cancellation = cleanup = evidence = old_threads = admitted = None
    active, external, staged = [], [], []
    probe = product = None
    safe = True
    try:
        package = Path(__file__).absolute().parent.parent
        workspace = package.parent.parent
        benchmark = Path(__file__).absolute().parent
        coordinator = _load_helper(benchmark / "qualify_formula_guard_coordinator.py", "_cost_profile_coordinator", COORDINATOR_SHA)
        helpers = _load_helper(benchmark / "qualify_bitwise_trained_head_devices.py", "_cost_profile_lanes", HELPERS_SHA)
        evidence = helpers.Evidence(output)
        sources = [("benchmark", Path(__file__).absolute(), None),
            ("coordinator_helpers", benchmark / "qualify_formula_guard_coordinator.py", COORDINATOR_SHA),
            ("cg2_harness_helpers", benchmark / "qualify_bitwise_trained_head_devices.py", HELPERS_SHA),
            ("cleanup_helper", benchmark / "qualify_native_768_device.py", CLEANUP_SHA),
            ("ordinary_reader_helpers", benchmark / "audit_formula_guard_coordinator_v3.py", READER_HELPERS_SHA)]
        expected = {"resource_scheduler": SCHEDULER_SHA, "modal_latent_formula_bitwise_device_inference": V1_SHA,
                    "modal_latent_formula_bitwise_device_inference_v2": V2_SHA}
        sources += [(role, package / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / (role + ".py"), expected.get(role))
                    for role in coordinator.SOURCE_NAMES]
        sources += [("tree_pin", package / "ipfs_datasets_py/logic/autoformal/tree_pin.py", None),
            ("canonical_contracts", package / "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py", None),
            ("cid_utils", package / "ipfs_datasets_py/utils/cid_utils.py", None)]
        paths = {}
        def retain(name, path, role, expected_sha=None):
            raw = _read(path)
            pin = _pin(path, raw)
            if expected_sha is not None:
                _require(pin["sha256"] == expected_sha, "fixed current source/fixture differs: " + role)
            entry = {"role": role, "current": pin, "retained_copy": evidence.raw(name, raw)}
            staged.append(entry)
            return raw, entry
        for index, (role, path, expected_sha) in enumerate(sources):
            _, entry = retain(f"producers/{index:02d}-{path.name}", path, role, expected_sha)
            result["source_pins"].append(entry)
            paths[role] = path
        raw_config, result["shared_configuration"] = retain("configuration.json", configuration, "shared_configuration", CONFIG_SHA)
        fixtures = {}
        for role, (relative, expected_sha) in coordinator.FIXTURES.items():
            raw, entry = retain("fixtures/" + role + ".json", workspace / "artifacts/codebase_ir_terminal_bench" / relative, role, expected_sha)
            fixtures[role] = json.loads(raw)
            result["fixture_pins"].append(entry)
        _require(not any(PREFIX + name in sys.modules for name in coordinator.SOURCE_NAMES if name != "resource_scheduler"),
                 "fresh worker required before producer imports")
        resources = importlib.import_module(PREFIX + "resource_scheduler")
        config = json.loads(raw_config)
        scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(**config["persisted_config"],
            state_path=config["state_path"], lease_ttl_seconds=config["lease_ttl_seconds"],
            auto_renew_leases=config["auto_renew_leases"]))
        result["resources_before"] = scheduler.snapshot()
        root = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=3, memory_mb=3072,
            gpu_memory_mb=768, unified_memory_mb=3840, requires_gpu=True, timeout=admission_timeout_seconds,
            request_id="formula-guard-cost-profile")
        admitted = time.monotonic()
        cancellation = helpers.Cancellation(root, admitted + MAX_SECONDS)
        result["admission"] = root.to_dict()
        print("ADMITTED", root.lease_id, flush=True)
        import torch as actual_torch
        torch = actual_torch
        old_threads = torch.get_num_threads()
        result["ambient_settings_before_thread_reservation"] = _settings(torch)
        torch.set_num_threads(1)
        ambient = result["ambient_settings_before_producer_imports_and_models"] = _settings(torch)
        _require(ambient == {**result["ambient_settings_before_thread_reservation"], "num_threads": 1}, "only reserved thread count may change")
        result["thread_reservation_scope"] = "caller_owned_one_thread_restored_after_owned_cleanup"
        _require(torch.cuda.is_available(), "actual CUDA required for diagnostic profile")
        device = torch.cuda.current_device()
        result["gpu_allocated_before_producer_imports_bytes"] = torch.cuda.memory_allocated(device)
        result["gpu_allocated_before_owned_sessions_bytes"] = torch.cuda.memory_allocated(device)
        _require(result["gpu_allocated_before_producer_imports_bytes"] == 0, "preimport allocated CUDA must be zero")
        modules = {name: importlib.import_module(PREFIX + name) for name in coordinator.SOURCE_NAMES}
        for name, module in modules.items():
            _require(Path(module.__file__).absolute() == paths[name], "producer imported outside retained source")
        _require(torch.cuda.memory_allocated(device) == 0 and _settings(torch) == ambient, "producer import changed allocation/policy")
        for entry in staged:
            _require(_pin(entry["current"]["path"]) == entry["current"],
                     "source/configuration/fixture changed before model construction")
        cleanup = _load_helper(benchmark / "qualify_native_768_device.py", "_cost_profile_cleanup", CLEANUP_SHA)
        probe = torch.tensor([2.], dtype=torch.float32, device=f"cuda:{device}")
        product = probe * probe
        _require(product.cpu().tolist() == [4.], "actual initial CUDA kernel differs")
        probe = product = None
        torch.cuda.synchronize(device)
        torch.cuda.reset_peak_memory_stats(device)
        result["hardware"] = {"torch": str(torch.__version__), "cuda_runtime": torch.version.cuda, "device_index": device,
            "name": torch.cuda.get_device_name(device), "capability": list(torch.cuda.get_device_capability(device)),
            "physical_memory_bytes": torch.cuda.get_device_properties(device).total_memory, "actual_initial_cuda_kernel": True}
        native = modules["modal_latent_formula"]

        def make_lane(label, width, checkpoint, sha):
            cancellation.poll()
            _require(_settings(torch) == ambient, "ambient policy changed before constructor")
            caller, owner = None, None
            optimized = label in CUDA_LANES
            if label.startswith("original"):
                caller = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1, memory_mb=1024,
                    gpu_memory_mb=256 if optimized else 0, unified_memory_mb=1280 if optimized else 0,
                    requires_gpu=optimized, parent_lease=root, cancel_event=cancellation, timeout=admission_timeout_seconds,
                    request_id=f"formula-guard-costs-{width}-{label}")
                external.append(caller)
                factory = lambda: modules["modal_latent_formula_device_inference"].DeviceLatentFormulaDecoder(
                    deepcopy(checkpoint), expected_binding=deepcopy(checkpoint["binding"]), optimized=optimized)
            else:
                role = "modal_latent_formula_bitwise_device_inference" + ("_v2" if "v2" in label else "")
                factory = lambda: modules[role].BitwiseDeviceLatentFormulaDecoder(deepcopy(checkpoint),
                    expected_checkpoint_sha256=sha, expected_binding=deepcopy(checkpoint["binding"]), optimized=optimized,
                    scheduler=scheduler, parent_lease=root, cancel_event=cancellation,
                    admission_timeout_seconds=admission_timeout_seconds, max_seconds=MAX_SECONDS,
                    memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=1280)
            try:
                owner = coordinator._construct(torch, native, counters, factory, label, dimension=width, checkpoint_sha256=sha)
                _require(_settings(torch) == ambient, "constructor changed ambient policy")
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
                raise

        def call(stem, lane, inputs, count, *, reference=None, reference_numeric=None, profiled=False):
            cancellation.poll()
            authored = deepcopy(inputs["rows"][:count])
            cpu_rng, cuda_rng = torch.random.get_rng_state(), torch.cuda.get_rng_state(device)
            with coordinator._probe_observer(torch, native, counters, scope="references_warmups_or_profiled_main_inference"):
                if profiled:
                    owners = [(lane.owner, "modal_latent_formula")]
                    registry = build_registry(modules, owners=owners)
                    threads = [root._heartbeat_thread] + [item.child_lease._heartbeat_thread for item in active if item.owner is not None]
                    observer = GuardCostObserver(registry, expected_main_profiler=sys.getprofile(),
                        allowed_background_threads=threads)
                    returned, python_profile, operator_trace = profile_public_call(torch, observer,
                        lambda: lane.owner.infer_with_projection(authored), device=device)
                else:
                    returned = lane.owner.infer_with_projection(authored)
                    torch.cuda.synchronize(device)
            report, vectors = returned
            _require(torch.equal(cpu_rng, torch.random.get_rng_state()) and torch.equal(cuda_rng, torch.cuda.get_rng_state(device)),
                     "inference/profiling changed RNG")
            cancellation.poll()
            decisions = coordinator._decisions(report)
            observed = {"result": evidence.json(stem + "-result.json", report),
                "projected_vectors": evidence.json(stem + "-projected-vectors.json", vectors),
                "instrumented": profiled, "cpu_cuda_rng_unchanged": True,
                "canonical_matches_original_cpu": reference is not None}
            if reference is not None:
                _require(_wire(reference) == _wire(decisions), "exact original CPU canonical decisions differ")
                observed["complete_projection_max_abs_error"] = helpers._numeric_error(reference_numeric, vectors)
            if profiled:
                observed["python_profile"] = evidence.json(stem + "-python-profile.json", python_profile)
                observed["operator_trace"] = evidence.json(stem + "-operator-trace.json", operator_trace)
                roots = [row for row in python_profile["spans"] if row[3] == observer.manual_id]
                _require(len(roots) == 1 and roots[0][2] == observer.main_thread_id, "one inline public-call cost root required")
                observed["instrumented_public_call_wall_ns"] = roots[0][8]
                observed["instrumented_public_call_thread_cpu_ns"] = roots[0][10]
                result["profiled_return_count"] += 1
            result["total_return_count"] += 1
            result["formula_projection_count"] += 1
            return observed, decisions, vectors

        for width in (8, 384):
            role = f"formula{width}"
            checkpoint, saved = fixtures[role + "_checkpoint"], fixtures[role + "_training_inputs"]
            sha = coordinator.FIXTURES[role + "_checkpoint"][1]
            _require(checkpoint["progress"]["optimizer_steps"] == 30, "retained positive thirty-step fixture required")
            inputs = {"schema": "retained-trained-formula-inference-inputs/v1", "dimension": width,
                "rows": [{"id": f"trained-formula{width}-inference-{index}",
                    "source_text": saved[index % len(saved)]["source_text"], "latent": deepcopy(saved[index % len(saved)]["latent"])}
                    for index in range(32)], "target_fields_excluded": True, "encoder_execution_performed": False}
            raw_state = _wire(checkpoint["model_state"])
            state_pin = {"bytes": len(raw_state), "sha256": hashlib.sha256(raw_state).hexdigest()}
            family = result["families"][role] = {"family": "formula", "dimension": width, "checkpoint_sha256": sha,
                "retained_checkpoint_progress": deepcopy(checkpoint["progress"]), "retained_checkpoint_model_pin": state_pin,
                "checkpoint_optimizer_sha256": hashlib.sha256(_wire(checkpoint["optimizer_state"])).hexdigest(),
                "inputs": evidence.json(role + "-inference-inputs.json", inputs), "lanes": {}, "counts": {}}
            references, numerics = {}, {}
            for label in CPU_LANES:
                lane, constructor = make_lane(label, width, checkpoint, sha)
                panel = family["lanes"][label] = {"constructor": constructor, "profile": lane.describe(),
                    "state_before": helpers._state_pin(lane.owner, "formula"), "counts": {}}
                _require(panel["state_before"] == state_pin, "CPU restored state differs")
                for count in COUNTS:
                    observation, decisions, vectors = call(f"{role}-{label}-{count}", lane, inputs, count,
                        reference=references.get(count), reference_numeric=numerics.get(count))
                    panel["counts"][str(count)] = observation
                    if label == "original_cpu_reference":
                        references[count], numerics[count] = decisions, vectors
                panel["state_after"] = helpers._state_pin(lane.owner, "formula")
                _require(panel["state_after"] == state_pin and _wire(lane.owner._checkpoint) == _wire(checkpoint), "CPU checkpoint/Adam changed")
                panel["checkpoint_and_adam_unchanged"] = True
                cancellation.clear()
                lane.close(torch, device)
                lane = None
            gpu_lanes = {}
            for label in CUDA_LANES:
                lane, constructor = make_lane(label, width, checkpoint, sha)
                gpu_lanes[label] = lane
                panel = family["lanes"][label] = {"constructor": constructor, "profile": lane.describe(),
                    "state_before": helpers._state_pin(lane.owner, "formula"), "counts": {}}
                _require(panel["state_before"] == state_pin, "CUDA restored state differs")
                panel["warmup"], _, _ = call(f"{role}-{label}-warmup", lane, inputs, 32,
                    reference=references[32], reference_numeric=numerics[32])
            family["three_way_admission"] = {"all_three_gpu_children_live": all(not item.child_lease.released for item in gpu_lanes.values()),
                "child_leases": {label: item.child_lease.to_dict() for label, item in gpu_lanes.items()}, "resources": scheduler.snapshot()}
            _require(family["three_way_admission"]["all_three_gpu_children_live"], "all three admitted CUDA children must remain live")
            for count in COUNTS:
                entry = family["counts"][str(count)] = {"observations": {}, "instrumented": True}
                for label in CUDA_LANES:
                    observation, _, _ = call(f"{role}-{count}-{label}-profile", gpu_lanes[label], inputs, count,
                        reference=references[count], reference_numeric=numerics[count], profiled=True)
                    entry["observations"][label] = observation
            family["new_cuda_controls"] = {}
            for label in ("bitwise_v1_cuda", "bitwise_v2_cuda"):
                with coordinator._probe_observer(torch, native, counters, scope="native_mutation_and_boundary_controls"):
                    family["new_cuda_controls"][label] = helpers._new_controls(torch, gpu_lanes[label], inputs, cancellation)
            for label, lane in gpu_lanes.items():
                panel = family["lanes"][label]
                panel["state_after"] = helpers._state_pin(lane.owner, "formula")
                _require(panel["state_after"] == state_pin and _wire(lane.owner._checkpoint) == _wire(checkpoint), "CUDA checkpoint/Adam changed")
                panel["checkpoint_and_adam_unchanged"] = True
                cancellation.clear()
                lane.close(torch, device)
            gpu_lanes.clear()
            lane = None
            family["numerical_and_canonical_qualified"] = True
        _require(result["total_return_count"] == result["formula_projection_count"] == 42 and result["profiled_return_count"] == 18
                 and len(result["owned_children"]) == 12 and counters["optimizer_restore_attempts"] == counters["optimizer_constructor_calls"] == 12,
                 "complete diagnostic returns/restores required")
        _require(all(counters[name] == 0 for name in ("optimizer_steps", "training_calls", "new_training_fits", "training_mode_true_calls", "encoder_calls")),
                 "training/steps/encoder work forbidden")
        result["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
        result["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
        _require(result["gpu_peak_allocated_bytes"] <= 768 * 1024**2, "observed GPU allocation exceeded reservation")
        result["root_gpu_allocation_budget_observed"] = True
        result["qualified"] = result["diagnostic_profile_qualified"] = True
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "detail": str(error), "traceback": traceback.format_exc(limit=14)}
    finally:
        if cancellation is not None:
            cancellation.clear()
        for lane in reversed(active):
            try:
                lane.close(torch, device)
            except BaseException as error:
                safe = False
                result.setdefault("close_errors", []).append({"type": type(error).__name__, "detail": str(error)})
        probe = product = None
        gc.collect()
        if torch is not None and cleanup is not None and safe:
            try:
                cleanup._cleanup_owned_cuda(torch, device, result)
            except BaseException as error:
                safe = False
                result["cleanup_error"] = {"type": type(error).__name__, "detail": str(error)}
        elif device is not None:
            safe = False
            result["cuda_cleanup_status"] = "owned_cleanup_not_established_root_retained"
        if safe:
            for child in external:
                if not child.released:
                    try:
                        child.release()
                    except BaseException as error:
                        safe = False
                        result.setdefault("child_release_errors", []).append({"type": type(error).__name__, "detail": str(error)})
        try:
            result["currentness_after"] = []
            for entry in staged:
                current = _pin(entry["current"]["path"])
                _require(current == entry["current"], "retained input/configuration/source changed")
                result["currentness_after"].append(current)
            result["retained_sources_fixtures_configuration_unchanged"] = True
        except BaseException as error:
            result["currentness_error"] = {"type": type(error).__name__, "detail": str(error)}
        if torch is not None and old_threads is not None:
            try:
                result["ambient_settings_after_owned_cleanup_before_thread_restore"] = _settings(torch)
                _require(result["ambient_settings_after_owned_cleanup_before_thread_restore"] == result["ambient_settings_before_producer_imports_and_models"],
                         "ambient precision/default policy changed")
            except BaseException as error:
                result["ambient_policy_error"] = {"type": type(error).__name__, "detail": str(error)}
            finally:
                torch.set_num_threads(old_threads)
            result["ambient_settings_after_thread_restore"] = _settings(torch)
            if result["ambient_settings_after_thread_restore"] != result["ambient_settings_before_thread_reservation"]:
                result["ambient_policy_error"] = {"type": "ValueError", "detail": "original ambient settings not restored"}
            result["ambient_precision_default_policy_unchanged"] = "ambient_policy_error" not in result
            result["persistent_precision_policy_mutated"] = "ambient_policy_error" in result
        for record in result["owned_children"]:
            matches = [lane for lane in active if lane.lease_id == record["lease_id"]]
            record["release_observed"] = len(matches) == 1 and matches[0].child_lease.released
        if root is not None:
            if safe and all(record["release_observed"] for record in result["owned_children"]):
                try:
                    root.release()
                except BaseException as error:
                    safe = False
                    result["root_release_error"] = {"type": type(error).__name__, "detail": str(error)}
            result["own_root_lease_released"] = result["root_release_observed"] = root.released
        else:
            result["own_root_lease_released"] = result["root_release_observed"] = False
        if scheduler is not None:
            result["resources_after"] = scheduler.snapshot()
        result.update(counters)
        result["safe_owned_cleanup_established"] = safe
        result["elapsed_seconds_total"] = time.monotonic() - began
        result["elapsed_seconds_after_root_admission"] = time.monotonic() - admitted if admitted is not None else None
        result["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["evidence_limits"] = {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES, "result_included_in_limits": True}
        if (not safe or "currentness_error" in result or "ambient_policy_error" in result
                or (root is not None and not root.released)
                or (admitted is not None and result["elapsed_seconds_after_root_admission"] > MAX_SECONDS)):
            result["qualified"] = result["diagnostic_profile_qualified"] = False
        if result["qualified"] is False and result["error"] is None:
            result["error"] = {"type": "DiagnosticClosureFailure", "detail": "owned cleanup/currentness/ambient policy/deadline closure missing"}
        if evidence is not None:
            result["evidence_files_except_result"] = list(evidence.files)
            result["evidence_bytes_except_result"] = evidence.bytes
            evidence.json("result.json", result, final=True)
        else:
            raw = _wire(result)
            _require(len(raw) <= MAX_FILE_BYTES, "bounded early diagnostic refusal required")
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
