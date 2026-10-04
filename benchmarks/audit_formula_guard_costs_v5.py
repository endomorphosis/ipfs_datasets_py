"""Ordinary-byte reader for bounded diagnostic guard-cost profiling evidence.

Only a pinned CURRENT ordinary reader helper is imported. Retained Python,
producer/model/tensor libraries, schedulers and services are never executed.
Instrumented costs establish trace consistency and no inference speed gain.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import struct
import types

FORMULA_SCHEMA = "retained-trained-formula-guard-cost-profile/v1"
FORMULA_SCHEMA_V2 = "retained-trained-formula-guard-cost-profile/v2"
DIMENSION_SCHEMA = "dimension-guard-cost-profiling/v1"
DIMENSION_SCHEMA_V2 = "dimension-guard-cost-profiling/v2"
DIMENSION_SCHEMA_V3 = "dimension-guard-cost-profiling/v3"
DIMENSION_SCHEMA_V4 = "dimension-guard-cost-profiling/v4"
DIMENSION_SCHEMA_V5 = "dimension-guard-cost-profiling/v5"
DIMENSION_SCHEMA_V6 = "dimension-guard-cost-profiling/v6"
REVIEW_SCHEMA = "guard-cost-profile-ordinary-archive-review/v1"
HELPER_SHA = "f38e215b5052242b682ad2e6a5b2e2631588a8f98957c75e8b3f3137a9475c53"
HELPER_BYTES = 63951
HELPER = Path(__file__).absolute().with_name("audit_formula_guard_coordinator_v3.py")
SPAN_HELPER_SHA = "fd020261328d05d6e4df7ec1e85e2d9c5278fa01195dac3c8f8bb156be2a11c2"
SPAN_HELPER_BYTES = 69735
SPAN_HELPER = HELPER.with_name("review_bitwise_trained_head_devices.py")
CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
SCHEDULER_SHA = "f156511991e33d3b4ba523c3c5080ea30d0a53ad8a4dbcccea0487432679a9aa"
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 1024, 8 * 1024**2, 64 * 1024**2
COUNTS = (1, 16, 32)


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _directory_fd(path):
    path = Path(path).absolute()
    _require(".." not in path.parts, "canonical ordinary helper path required")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _helper_bytes(path=HELPER, size=HELPER_BYTES, digest=HELPER_SHA):
    parent = _directory_fd(path.parent)
    try:
        parent_identity = os.fstat(parent)
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == size
                 and not before.st_mode & 0o222, "fixed read-only ordinary helper custody required")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _require(_identity(opened) == _identity(before), "opened helper identity differs")
            raw = stream.read(size + 1)
            after_open = os.fstat(stream.fileno())
        after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        current_parent = _directory_fd(path.parent)
        try:
            latest = os.fstat(current_parent)
            _require((latest.st_dev, latest.st_ino) == (parent_identity.st_dev, parent_identity.st_ino),
                     "ordinary helper parent identity changed")
        finally:
            os.close(current_parent)
        _require(_identity(before) == _identity(after_open) == _identity(after)
                 and len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
                 "fixed ordinary helper source changed")
        return raw, _identity(before)
    finally:
        os.close(parent)


def _load_current(path, size, digest):
    raw, identity = _helper_bytes(path, size, digest)
    spec = importlib.util.spec_from_file_location("_current_guard_cost_ordinary_helpers_" + digest[:12], path)
    _require(spec is not None and spec.loader is not None, "current ordinary helper loader unavailable")
    module = importlib.util.module_from_spec(spec)
    # Compile the verified CURRENT ordinary source, avoiding bytecode-cache or
    # pathname substitution between the descriptor read and normal import.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    later, later_identity = _helper_bytes(path, size, digest)
    _require(raw == later and identity == later_identity and Path(module.__file__).absolute() == path,
             "ordinary helper changed during current source import")
    return module


def _base():
    return _load_current(HELPER, HELPER_BYTES, HELPER_SHA)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _integer(value, minimum=0, maximum=2**63 - 1):
    _require(type(value) is int and minimum <= value <= maximum, "bounded plain profiling integer required")
    return value


def _finite(value, *, minimum=0.0):
    _require(type(value) is float and math.isfinite(value) and value >= minimum, "finite plain-float profiling value required")
    return value


PYTHON_COLUMNS = ["id", "parent_id", "thread_id", "registry_id", "start_wall_ns", "end_wall_ns",
    "start_thread_cpu_ns", "end_thread_cpu_ns", "inclusive_wall_ns", "exclusive_wall_ns",
    "inclusive_thread_cpu_ns", "exclusive_thread_cpu_ns", "return_event"]
PYTHON_AGGREGATE_COLUMNS = ["thread_scope", "registry_id", "call_count", "inclusive_wall_ns", "exclusive_wall_ns",
    "inclusive_thread_cpu_ns", "exclusive_thread_cpu_ns", "c_exception_count"]
OPERATOR_COLUMNS = ["id", "name_id", "device_type_id", "device_index", "thread_id", "start_us", "end_us",
    "cpu_total_us", "cpu_self_us", "device_total_us", "device_self_us"]


def _code_inventory(raw, path):
    """Compile verified current source without executing it or its imports."""
    pending, output = [compile(raw, str(path), "exec")], set()
    while pending:
        code = pending.pop()
        output.add((code.co_qualname, code.co_firstlineno, hashlib.sha256(code.co_code).hexdigest(),
                    bool(code.co_flags & 0x20)))
        pending.extend(item for item in code.co_consts if type(item) is types.CodeType)
    return output


def _registry(registry, sources):
    _require(type(registry) is list and 1 <= len(registry) <= 512, "bounded plain source registry required")
    result, identities = {}, set()
    for position, item in enumerate(registry):
        _require(type(item) is dict and set(item) == {"id", "label", "source_role", "function_qualname",
                 "firstlineno", "code_sha256", "kind"}, "exact source registry descriptor required")
        identifier = _integer(item["id"], 0, 511)
        role, name, kind = item["source_role"], item["function_qualname"], item["kind"]
        _require(identifier == position and identifier not in result and role in sources and type(name) is str and 0 < len(name) <= 512
                 and type(item["label"]) is str and 0 < len(item["label"]) <= 512, "unique registered source identity required")
        identity = (role, name, item["firstlineno"], item["code_sha256"], kind)
        _require(identity not in identities, "source registry alias")
        if kind in ("python", "generator_segment"):
            _require((_integer(item["firstlineno"], 1), type(item["code_sha256"]))[1] is str
                     and (name, item["firstlineno"], item["code_sha256"], kind == "generator_segment") in sources[role],
                     "registered Python code does not match pinned current source")
        elif kind == "cfunction":
            _require(role == "resource_scheduler" and name in {"os.fsync", "fcntl.flock", "os.replace"}
                     and item["firstlineno"] == 0 and type(item["firstlineno"]) is int and item["code_sha256"] is None,
                     "registered C function exceeds exact scheduler call allowlist")
        elif kind == "manual":
            _require(role in {"benchmark", "cost_profiler"} and name == "complete_public_call" and type(item["firstlineno"]) is int
                     and item["firstlineno"] == 0 and item["code_sha256"] is None, "manual public call descriptor differs")
        else:
            raise ValueError("unknown registered profiling function kind")
        result[identifier] = item
        identities.add(identity)
    _require(sum(item["kind"] == "manual" for item in result.values()) == 1
             and {item["function_qualname"] for item in result.values() if item["kind"] == "cfunction"} ==
                 {"os.fsync", "fcntl.flock", "os.replace"}, "complete exact manual and scheduler C registry required")
    return result


def _span_arithmetic(spans, threads, registry, main_thread, window_start, window_end, censored=()):
    _require(type(spans) is list and 1 <= len(spans) <= 20000, "bounded plain source spans required")
    records, children, manual = {}, {}, []
    for row in spans:
        _require(type(row) is list and len(row) == len(PYTHON_COLUMNS), "complete source span columns required")
        identifier, parent, thread, registered = [_integer(value) for value in row[:4]]
        _require(identifier > 0 and identifier not in records and thread in threads and registered in registry,
                 "unique span/thread/registry joins required")
        for value in row[4:12]:
            _integer(value)
        _require(window_start <= row[4] <= row[5] <= window_end and row[6] <= row[7]
                 and row[8] == row[5] - row[4] and row[10] == row[7] - row[6]
                 and row[9] <= row[8] and row[11] <= row[10], "inclusive span clock arithmetic differs")
        kind = registry[registered]["kind"]
        _require(row[12] in ({"c_return", "c_exception"} if kind == "cfunction" else
                            {"manual_return"} if kind == "manual" else {"return"}),
                 "source span return event differs")
        if kind == "manual":
            _require(parent == 0 and thread == main_thread, "manual complete call is not an inline root")
            manual.append(identifier)
        records[identifier] = row
        children.setdefault(parent, []).append(identifier)
    _require(len(manual) == 1, "exact one manual complete public call required")
    unfinished = {}
    for item in censored:
        _require(type(item) is dict and _integer(item["thread_id"], 1) in threads
                 and threads[item["thread_id"]] == "owned_background"
                 and _integer(item["registry_id"], 0, 511) in registry,
                 "censored edge must join a registered owned background thread")
        if item["edge"] == "entered_before_window":
            _require(set(item) == {"edge", "thread_id", "registry_id", "return_event", "observed_wall_ns"}
                     and item["return_event"] in {"return", "c_return", "c_exception"}
                     and window_start <= _integer(item["observed_wall_ns"]) <= window_end,
                     "censored prewindow return metadata differs")
        else:
            _require(item["edge"] == "unfinished_at_window_end" and set(item) == {"edge", "thread_id", "id", "parent_id",
                     "registry_id", "start_wall_ns", "start_thread_cpu_ns"}, "censored unfinished edge metadata differs")
            identifier = _integer(item["id"], 1, 20000)
            _integer(item["parent_id"])
            _require(identifier not in records and identifier not in unfinished
                     and window_start <= _integer(item["start_wall_ns"]) <= window_end,
                     "censored unfinished span identity/time differs")
            _integer(item["start_thread_cpu_ns"])
            unfinished[identifier] = item
    for identifier, item in unfinished.items():
        parent = item["parent_id"]
        if parent:
            _require(parent in unfinished and parent < identifier and unfinished[parent]["thread_id"] == item["thread_id"]
                     and unfinished[parent]["start_wall_ns"] <= item["start_wall_ns"]
                     and unfinished[parent]["start_thread_cpu_ns"] <= item["start_thread_cpu_ns"],
                     "unfinished background parent custody differs")
    aggregates = {}
    for identifier, row in records.items():
        parent = row[1]
        if parent:
            _require(parent < identifier and (parent in records or parent in unfinished), "acyclic earlier selected parent required")
            if parent in records:
                outer = records[parent]
                _require(row[2] == outer[2] and outer[4] <= row[4] <= row[5] <= outer[5]
                         and outer[6] <= row[6] <= row[7] <= outer[7], "selected parent/thread clock containment differs")
            else:
                outer = unfinished[parent]
                _require(row[2] == outer["thread_id"] and threads[row[2]] == "owned_background"
                         and outer["start_wall_ns"] <= row[4] and outer["start_thread_cpu_ns"] <= row[6],
                         "completed background span does not join censored partial parent")
        selected = [records[child] for child in children.get(identifier, [])]
        ordered = sorted(selected, key=lambda child: (child[4], child[5], child[0]))
        _require(all(left[5] <= right[4] for left, right in zip(ordered, ordered[1:])),
                 "selected sibling spans overlap")
        _require(row[9] == row[8] - sum(child[8] for child in selected)
                 and row[11] == row[10] - sum(child[10] for child in selected),
                 "selected-scope exclusive span arithmetic differs")
        if registry[row[3]]["kind"] == "cfunction":
            parent_registry = records[parent][3] if parent in records else unfinished[parent]["registry_id"] if parent in unfinished else None
            _require(parent_registry in registry and registry[parent_registry]["source_role"] == "resource_scheduler"
                     and registry[parent_registry]["function_qualname"].endswith("._locked_state")
                     and registry[parent_registry]["kind"] == "generator_segment",
                     "C scheduler call lacks exact selected locked-state calling frame")
        scope = threads[row[2]]
        key = (scope, row[3])
        aggregate = aggregates.setdefault(key, [scope, row[3], 0, 0, 0, 0, 0, 0])
        aggregate[2] += 1
        for source_index, destination in ((8, 3), (9, 4), (10, 5), (11, 6)):
            aggregate[destination] += row[source_index]
        aggregate[7] += int(row[12] == "c_exception")
    root = records[manual[0]]
    _require(all(identifier == root[0] or row[2] != main_thread or row[1] != 0
                 for identifier, row in records.items()), "inline selected span escaped complete public call root")
    return [aggregates[key] for key in sorted(aggregates)], root


def _python_profile(value, sources, observation, *, max_callback_events=1000000, manual_source_role="benchmark",
                    registry_binding=None):
    _base()._authority(value)
    _require(type(value) is dict and value["schema"] == "source-bound-guard-call-costs/v1"
             and value["instrumented"] is True and value["performance_qualified"] is False,
             "source profiling diagnostic schema/scope differs")
    _require(("registry_binding" not in value if registry_binding is None else value["registry_binding"] == registry_binding),
             "source registry runtime identity policy differs")
    exact = {"clock": {"wall": "perf_counter_ns", "cpu": "thread_time_ns", "operator_clock_alignment_claimed": False},
        "exclusive_scope": "inclusive_minus_direct_selected_children_unselected_work_stays_with_parent",
        "generator_scope": "resumption_segments_not_logical_transactions",
        "background_scope": "windowed_owned_python_threads_prior_default_none_edges_censored_no_whole_job_coverage",
        "background_censor_scope": "complete_spans_only_partial_start_or_end_not_added_to_completed_costs",
        "observer_overhead_scope": "callback_and_native_profiler_overhead_included_not_measured_or_subtracted",
        "background_activity_claim": "observed_events_only_absence_is_not_zero_activity_attestation",
        "span_columns": PYTHON_COLUMNS, "aggregate_columns": PYTHON_AGGREGATE_COLUMNS}
    _require(all(_wire(value[key]) == _wire(expected) for key, expected in exact.items()),
             "selected costs, generator, thread visibility or independent clock scope differs")
    _require(value["overflow"] is False and value["unsupported_thread_observed"] is False
             and value["hooks_restored"] is True, "source profiler overflow/thread/hook refusal")
    bounds = value["bounds"]
    _require(type(bounds) is dict and set(bounds) == {"max_events", "max_spans", "max_threads"}, "exact profile bounds required")
    _require(max_callback_events in (1000000, 4000000, 8000000) and type(max_callback_events) is int,
             "fixed instance-local callback policy required")
    for name, maximum in (("max_events", max_callback_events), ("max_spans", 20000), ("max_threads", 32)):
        _integer(bounds[name], 1, maximum)
    _require(_wire(bounds) == _wire({"max_events": max_callback_events, "max_spans": 20000, "max_threads": 32}),
             "fixed authored observer callback/span/thread limits differ")
    _integer(value["callback_events_observed"], 1, bounds["max_events"])
    registry = _registry(value["registry"], sources)
    _require(all(item["source_role"] == manual_source_role for item in registry.values() if item["kind"] == "manual"),
             "manual public cost source role differs from pinned utility")
    main = _integer(value["main_thread_id"], 1)
    start, end = _integer(value["window_start_ns"]), _integer(value["window_end_ns"])
    _require(start < end and type(value["threads"]) is list and 1 <= len(value["threads"]) <= bounds["max_threads"],
             "bounded completed profiler window/threads required")
    threads = {}
    for item in value["threads"]:
        _require(type(item) is dict and set(item) == {"thread_id", "scope"}, "exact observed Python thread required")
        identifier = _integer(item["thread_id"], 1)
        _require(identifier not in threads and item["scope"] == ("inline_main" if identifier == main else "owned_background"),
                 "unique observed inline/background thread identity required")
        threads[identifier] = item["scope"]
    _require(main in threads and len(value["spans"]) <= bounds["max_spans"], "main thread or bounded span coverage missing")
    censored = value["censored_background"]
    _require(type(censored) is list and len(censored) + len(value["spans"]) <= bounds["max_spans"],
             "bounded complete plus censored selected spans required")
    aggregates, root = _span_arithmetic(value["spans"], threads, registry, main, start, end, censored)
    _require(_wire(aggregates) == _wire(value["aggregates"]), "source cost aggregate differs from complete raw spans")
    _require(_integer(observation["instrumented_public_call_wall_ns"]) == root[8]
             and _integer(observation["instrumented_public_call_thread_cpu_ns"]) == root[10],
             "public return diagnostic cost does not join manual complete call span")
    return {"raw_span_count": len(value["spans"]), "observed_thread_count": len(threads),
            "manual_wall_ns": root[8], "manual_thread_cpu_ns": root[10], "aggregates": aggregates}


def _operator_trace(value, *, expected_pid, expected_event_limit=50000):
    _base()._authority(value)
    _integer(expected_pid, 1, 2**31 - 1)
    _require(type(value) is dict and value["schema"] == "bounded-torch-operator-costs/v1"
             and value["instrumented"] is True and value["performance_qualified"] is False
             and value["record_shapes"] is False and value["profile_memory"] is False and value["with_stack"] is False,
             "bounded native operator diagnostic scope differs")
    _require(value["activities"] == ["CPU", "CUDA"]
             and value["clock"] == "native_profiler_relative_microseconds_alignment_to_python_clock_not_claimed"
             and value["collection_bound_scope"] == "fixed_admitted_workload_only_native_buffer_allocation_not_enforced"
             and value["event_columns"] == OPERATOR_COLUMNS
             and value["aggregate_columns"] == ["name_id", "device_type_id", "count", "cpu_total_us", "cpu_self_us",
                 "device_total_us", "device_self_us"], "native clock/collection/column scope differs")
    limit = _integer(value["postcollection_event_limit"], 1, 50000)
    _require(limit == expected_event_limit and type(expected_event_limit) is int, "fixed native postcollection event limit differs")
    names, devices, events = value["names"], value["device_types"], value["events"]
    _require(type(names) is list and 1 <= len(names) <= 4096 and len(set(names)) == len(names)
             and all(type(name) is str and 0 < len(name) <= 4096 for name in names), "bounded unique native names required")
    _require(type(devices) is list and 1 <= len(devices) <= 16 and len(set(devices)) == len(devices)
             and all(type(device) is str and device in {"DeviceType.CPU", "DeviceType.CUDA"} for device in devices),
             "bounded exact CPU/CUDA device table required")
    _require(type(events) is list and 0 < len(events) <= limit and _integer(value["event_count"]) == len(events),
             "native event count/bound differs")
    aggregates, cuda, seen_names, seen_devices = {}, 0, set(), set()
    for index, row in enumerate(events):
        _require(type(row) is list and len(row) == len(OPERATOR_COLUMNS) and _integer(row[0]) == index,
                 "unique complete native event required")
        name, device = _integer(row[1], 0, len(names) - 1), _integer(row[2], 0, len(devices) - 1)
        if devices[device] == "DeviceType.CPU":
            # The native profiler records the host PID here for ordinary CPU
            # events; -1 is its unspecified-index sentinel. This is not a
            # CUDA ordinal, and an unrelated host PID must never be admitted.
            _require(_integer(row[3], -1, 2**31 - 1) in (-1, expected_pid),
                     "native CPU device index does not join producer PID")
        else:
            _integer(row[3], 0, 63)
        _integer(row[4], 0)
        for amount in row[5:]:
            _finite(amount)
        _require(row[6] >= row[5], "native event interval reversed")
        items = aggregates.setdefault((name, device), [name, device, 0, 0.0, 0.0, 0.0, 0.0])
        items[2] += 1
        for slot, amount in enumerate(row[7:], 3):
            items[slot] += amount
        cuda += int(devices[device].endswith(".CUDA"))
        seen_names.add(name)
        seen_devices.add(device)
    derived = [aggregates[key] for key in sorted(aggregates)]
    _require(seen_names == set(range(len(names))) and seen_devices == set(range(len(devices))) and cuda > 0
             and _integer(value["cuda_event_count"]) == cuda and _wire(value["aggregates"]) == _wire(derived),
             "native label coverage/CUDA activity/aggregate arithmetic differs")
    return {"native_event_count": len(events), "native_cuda_event_count": cuda, "aggregates": derived}


FORMULA_PRODUCER_SHA = "61786537ff7e6d442322d307ef7d7a1a609cf9279d8a005017eb9e1e73127577"
FORMULA_PRODUCER_V2_SHA = "f0f4b9d5daa1c3380ec9f742aeacc24e815ccfee2f1e0aa180ad9fe2b08275f4"
DIMENSION_PRODUCER_SHA = "cabc64a5479c92ac52cb577673f36615176d4660d6bc4956666c98748b7c584c"
DIMENSION_PRODUCER_V2_SHA = "1623ab2602b56c4a178f2aef437947ffadbe987ba6c4430ceccf4c8429b857ba"
DIMENSION_PRODUCER_V3_SHA = "e29b9b299564abb530699dcee9c00163b35f6d7fbfd5205cf99c0ba074e1f06b"
DIMENSION_PRODUCER_V4_SHA = "231cda2130e81054925d4478600b4eb282639f0bbaa473ded416862f3e4aab65"
DIMENSION_PRODUCER_V5_SHA = "8c3cf068624bc47e41f90df3bb3217d602f3c17d91b85a797b066b669a9767c0"
DIMENSION_PRODUCER_V6_SHA = "c1843cf34591200f53caca9e0655ea41d077a7783123f0cc924d639c8ccb3cd0"
COST_OBSERVER_BUDGET_SHA = "1f1e1a1699c230618e8f14a77715219664a34d60ca25d333745dace73fd3b825"
COST_OBSERVER_BUDGET_V3_SHA = "149ca08c53dc97606a8fe877cbcf8a4dae56b3f67a9a0730e2e697b26458b196"
COST_OBSERVER_BUDGET_V4_SHA = "7716ea86869c56b5506e62ee45dea159a646759405ae922d5fd5833a84f8b2dd"
IDENTITY_POLICY = "code_object_identity_with_strong_references"
COMMON_DIMENSION_ROLES = frozenset({"resource_scheduler", "legal_span_formula", "legal_span_dimensions",
    "legal_span_device_inference", "legal_span_device_batch_inference", "owned_tensor_value_guard",
    "owned_tensor_bitwise_guard", "checkpoint_content_guard", "runtime_telemetry", "proof_resource_safety",
    "legal_formula_codec", "legal_ir_grammar_decoder", "legal_ir_family_evaluator", "snapshot_evaluator"})
DIMENSION_EXTRA_ROLES = frozenset({"benchmark", "cost_profiler", "coordinator_helpers", "trained_helpers",
    "synthetic_helpers", "cleanup_helper", "ordinary_span_reader_helpers", "tree_pin", "canonical_contracts", "cid_utils"})
DIMENSION_FIXTURES = {
    768: {"checkpoint": "9fcd8dd3b9727f5ee93b5b2cb2d7f23e482f16c24f64c23a3ae9da2168e3117b",
          "sources": "eec38602f9d3c3b0c1511ab05b473bbcf2bb3647ac1c4854e899fb0200ad4e46",
          "historical_outputs": "f728dab53925cd2f9d053d760dcafab756ed718197a8649f24c2000bfc73c221"},
    4096: {"checkpoint": "04a8f2d317294861a7fcf9b6f156e915cd6c31bfa1482b8eaab4ecf15d00dee7",
           "rows": "90c2ae29b4eb7aca66eeb9539c3cbbd42536d245938a449465106469cd46d4bf"}}
DIMENSION_SOURCES = {768: frozenset({"legal_span_device_bitwise_inference"}), 4096: frozenset({"legal_span_4096",
    "legal_span_4096_device_inference", "legal_span_4096_bitwise_device_inference", "legal_span_4096_bitwise_device_inference_v2"})}
DIMENSION_FIXED = {"legal_span_device_inference": "4efff4c197af2d5749e7f2463a256ce814a174f53615b26a3a414a37e53c2be5",
    "legal_span_device_bitwise_inference": "d1c12eb54ca8c17c9815ed20db9237c86876361ac3d72fa30ce2d470b0fccf91",
    "legal_span_4096_device_inference": "658382fb5b7bb30eb5e82a444b9ac9168b7557f5452a87a8ff59a5f883de55a8",
    "legal_span_4096_bitwise_device_inference": "90d2a06081b4391216fb63cc82968b0c8ea1ff8138d564448281b5e3b2b88595",
    "legal_span_4096_bitwise_device_inference_v2": "14678654b927d0b6910fda6a8c82961978a9e7ebc29334aaae6cb2320abc5dc3"}


def _source_path(base, role, dimension, schema):
    special = {"benchmark": ("profile_formula_guard_costs_v2.py" if schema == FORMULA_SCHEMA_V2 else
            "profile_formula_guard_costs.py") if dimension is None else
            "profile_dimension_guard_costs_v6.py" if schema == DIMENSION_SCHEMA_V6 else
            "profile_dimension_guard_costs_v5.py" if schema == DIMENSION_SCHEMA_V5 else
            "profile_dimension_guard_costs_v4.py" if schema == DIMENSION_SCHEMA_V4 else
            "profile_dimension_guard_costs_v3.py" if schema == DIMENSION_SCHEMA_V3 else
            "profile_dimension_guard_costs_v2.py" if schema == DIMENSION_SCHEMA_V2 else "profile_dimension_guard_costs.py",
        "coordinator_helpers": "qualify_formula_guard_coordinator.py", "cost_profiler":
            "profile_formula_guard_costs_v2.py" if schema in (DIMENSION_SCHEMA_V3, DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6) else "profile_formula_guard_costs.py",
        "ordinary_reader_helpers": "audit_formula_guard_coordinator_v3.py",
        "ordinary_span_reader_helpers": "review_bitwise_trained_head_devices.py",
        "trained_helpers": "qualify_bitwise_trained_head_devices.py",
        "synthetic_helpers": "qualify_synthetic_4096_head_device_v2.py", "cost_observer_budget":
            "guard_cost_observer_budget_v4.py" if schema == DIMENSION_SCHEMA_V6 else
            "guard_cost_observer_budget_v3.py" if schema in (DIMENSION_SCHEMA_V3, DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6) else "guard_cost_observer_budget_v2.py"}
    return Path(__file__).absolute().with_name(special[role]) if role in special else base._current_path(role)


def _staging(base, archive, result, check_current):
    dimension = None if result["schema"] in (FORMULA_SCHEMA, FORMULA_SCHEMA_V2) else _integer(result["dimension"])
    roles = (base.SOURCE_ROLES | {"coordinator_helpers", "ordinary_reader_helpers"} if dimension is None else
             COMMON_DIMENSION_ROLES | DIMENSION_EXTRA_ROLES | DIMENSION_SOURCES[dimension] |
             ({"cost_observer_budget"} if result["schema"] in (DIMENSION_SCHEMA_V2, DIMENSION_SCHEMA_V3, DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6) else set()))
    expected_fixtures = base.FIXTURES if dimension is None else DIMENSION_FIXTURES[dimension]
    fixed = {**base.FIXED_SOURCES, **DIMENSION_FIXED, "resource_scheduler": SCHEDULER_SHA,
        "benchmark": (FORMULA_PRODUCER_V2_SHA if result["schema"] == FORMULA_SCHEMA_V2 else FORMULA_PRODUCER_SHA) if dimension is None else
            DIMENSION_PRODUCER_V6_SHA if result["schema"] == DIMENSION_SCHEMA_V6 else
            DIMENSION_PRODUCER_V5_SHA if result["schema"] == DIMENSION_SCHEMA_V5 else
            DIMENSION_PRODUCER_V4_SHA if result["schema"] == DIMENSION_SCHEMA_V4 else
            DIMENSION_PRODUCER_V3_SHA if result["schema"] == DIMENSION_SCHEMA_V3 else
            DIMENSION_PRODUCER_V2_SHA if result["schema"] == DIMENSION_SCHEMA_V2 else DIMENSION_PRODUCER_SHA,
        "cost_observer_budget": COST_OBSERVER_BUDGET_V4_SHA if result["schema"] == DIMENSION_SCHEMA_V6 else
            COST_OBSERVER_BUDGET_V3_SHA if result["schema"] in (DIMENSION_SCHEMA_V3, DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6) else COST_OBSERVER_BUDGET_SHA,
        "cost_profiler": FORMULA_PRODUCER_V2_SHA if result["schema"] in (DIMENSION_SCHEMA_V3, DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6) else FORMULA_PRODUCER_SHA,
        "coordinator_helpers": base.FIXED_SOURCES["benchmark"], "ordinary_reader_helpers": HELPER_SHA,
        "ordinary_span_reader_helpers": SPAN_HELPER_SHA,
        "trained_helpers": base.FIXED_SOURCES["cg2_harness_helpers"],
        "synthetic_helpers": "a2b85c0e05d9fc652e7e3d2fdb99b83407a511a3321fba3d2299c27e797ceb36"}
    sources, fixture_entries = result["source_pins"], result["fixture_pins"]
    _require(type(sources) is list and len(sources) == len(roles) and {item["role"] for item in sources} == roles,
             "exact unique diagnostic producer source inventory required")
    _require(type(fixture_entries) is list and len(fixture_entries) == len(expected_fixtures)
             and {item["role"] for item in fixture_entries} == set(expected_fixtures), "exact retained diagnostic fixtures required")
    config = result["shared_configuration"]
    _require(config["role"] == "shared_configuration", "configuration role differs")
    source_shas, code_sources, fixtures, current_pins, verified = {}, {}, {}, [], []
    for item in [*sources, config, *fixture_entries]:
        _require(type(item) is dict and set(item) == {"role", "current", "retained_copy"}, "exact staged source/fixture wrapper required")
        role, current, retained = item["role"], item["current"], item["retained_copy"]
        base._pin_shape(current)
        raw = archive.raw(retained)
        _require((current["bytes"], current["sha256"]) == (retained["bytes"], retained["sha256"]),
                 "staged current/retained byte pins differ")
        expected = CONFIG_SHA if item is config else expected_fixtures.get(role) if item in fixture_entries else fixed.get(role)
        if expected is not None:
            _require(current["sha256"] == expected, "fixed diagnostic source/configuration/fixture differs: " + role)
        if item in sources:
            path = _source_path(base, role, dimension, result["schema"])
            _require(current["path"] == str(path.absolute()) and path.suffix == ".py", "current registered repository source path differs")
            # Bytecode identity needs the current Python compiler and current
            # pinned source. Compilation never executes source or its imports.
            current_raw = base._read(path, readonly=False)
            _require(base._pin(path, current_raw) == current, "registered current source changed")
            code_sources[role] = _code_inventory(current_raw, path)
            source_shas[role] = current["sha256"]
            verified.append(current)
        elif check_current:
            _require(base._pin(current["path"], base._read(current["path"], readonly=False)) == current,
                     "current fixture/configuration changed")
        if item in fixture_entries:
            fixtures[role] = base._json(raw)
        current_pins.append(current)
    _require(result["retained_sources_fixtures_configuration_unchanged"] is True
             and _wire(result["currentness_after"]) == _wire(current_pins), "source/fixture final closure differs")
    configuration = archive.value(config["retained_copy"])
    _require(result["resources_after"]["state_path"] == configuration["state_path"], "resource/configuration state path differs")
    return dimension, fixtures, source_shas, code_sources, current_pins, verified


def _scope(base, result):
    _require(type(result["qualified"]) is bool and result["qualified"] is (result["error"] is None),
             "diagnostic qualification/error contradicts")
    if not result["qualified"]:
        _require(type(result["error"]) is dict and type(result["error"]["type"]) is str
                 and 0 < len(result["error"]["type"]) <= 512 and type(result["error"]["detail"]) is str
                 and 0 < len(result["error"]["detail"]) <= 65536, "plain bounded producer refusal required")
    ordinary = {key: value for key, value in result.items() if key != "qualified"}
    base._authority(ordinary)
    for name in ("performance_qualified", "production_qualified", "proof_authority", "execution_attestation",
        "semantic_correctness_verified", "fresh_encoder_execution_qualified", "native_encoder_origin_authenticated",
        "kernel_resource_enforcement", "selected_existing_profile_changed", "foreign_process_actions"):
        _require(result[name] is False, "profiling archive claims inference gain or authority: " + name)
    for name in ("optimizer_steps", "new_training_fits", "training_mode_true_calls", "encoder_calls"):
        _require(_integer(result[name]) == 0, "new training/encoder work is outside diagnostic inference")
    _require(_integer(result["max_seconds_after_root_admission"]) == 120
             and 1 <= _integer(result["admission_timeout_seconds"]) <= 60, "bounded diagnostic deadline differs")
    if result["qualified"]:
        _require(type(result["elapsed_seconds_after_root_admission"]) is float
                 and 0 < result["elapsed_seconds_after_root_admission"] <= 120,
                 "qualified diagnostic exceeded admitted workload deadline")
        _require(result["ambient_precision_default_policy_unchanged"] is True
                 and result["hardware"]["actual_initial_cuda_kernel"] is True
                 and _integer(result["gpu_peak_allocated_bytes"]) <= 768 * 1024**2,
                 "actual kernel/allocation/policy closure missing")
        _integer(result["hardware"]["device_index"], 0, 63)
        before, reserved = result["ambient_settings_before_thread_reservation"], result["ambient_settings_before_producer_imports_and_models"]
        _require(_integer(before["num_threads"], 1, 1024) > 0
                 and _wire(reserved) == _wire({**before, "num_threads": 1})
                 and _wire(result["ambient_settings_after_owned_cleanup_before_thread_restore"]) == _wire(reserved)
                 and _wire(result["ambient_settings_after_thread_restore"]) == _wire(before)
                 and reserved["default_device"] == "cpu" and reserved["default_dtype"] == "torch.float32"
                 and reserved["autocast_cpu_enabled"] is False and reserved["autocast_cuda_enabled"] is False,
                 "caller-owned thread/default/precision restoration differs")


def _formula_observation(base, archive, observed, stem, label, count, checkpoint, inputs, shas, byte_plan,
                         lease, cuda_device, code_sources, *, canonical=None, numeric=None, profiled=False, profiling_pid=None):
    report = archive.value(observed["result"], name=stem + "-result.json", unique=True)
    vectors = archive.value(observed["projected_vectors"], name=stem + "-projected-vectors.json", unique=True)
    base._authority(report)
    _require(report["checkpoint_sha256"] == hashlib.sha256(_wire(checkpoint)).hexdigest(), "public formula checkpoint differs")
    base._row_inputs(report, inputs, count, checkpoint)
    base._source_profile(report["inference_implementation"], label, checkpoint, shas, byte_plan,
                         lease=lease, cuda_device=cuda_device)
    base._shape(vectors, (count, checkpoint["binding"]["dimension"]))
    decision = base._decisions(report)
    _require(observed["instrumented"] is profiled and observed["cpu_cuda_rng_unchanged"] is True
             and observed["canonical_matches_original_cpu"] is (canonical is not None), "public diagnostic phase/RNG/reference differs")
    if canonical is not None:
        _require(_wire(decision) == _wire(canonical), "public formula canonical decisions differ from original CPU")
        error = base._numeric(numeric, vectors)
        _require(_finite(observed["complete_projection_max_abs_error"]) == error, "formula error arithmetic differs")
    costs = None
    if profiled:
        python = archive.value(observed["python_profile"], name=stem + "-python-profile.json", unique=True)
        operators = archive.value(observed["operator_trace"], name=stem + "-operator-trace.json", unique=True)
        costs = {"python": _python_profile(python, code_sources, observed,
            registry_binding=IDENTITY_POLICY if shas["benchmark"] == FORMULA_PRODUCER_V2_SHA else None),
            "operators": _operator_trace(operators, expected_pid=profiling_pid)}
    return decision, vectors, costs


def _formula_family(base, archive, role, entry, fixtures, shas, code_sources, leases, cuda_device, profiling_pid):
    _require(role in {"formula8", "formula384"}, "unknown formula diagnostic family")
    width, checkpoint = int(role[7:]), fixtures[role + "_checkpoint"]
    _require(entry["family"] == "formula" and _integer(entry["dimension"]) == width
             and entry["checkpoint_sha256"] == base.FIXTURES[role + "_checkpoint"]
             and _wire(entry["retained_checkpoint_progress"]) == _wire(checkpoint["progress"])
             and _integer(checkpoint["progress"]["optimizer_steps"]) == 30, "retained trained formula identity differs")
    model = {"bytes": len(_wire(checkpoint["model_state"])), "sha256": hashlib.sha256(_wire(checkpoint["model_state"])).hexdigest()}
    _require(_wire(entry["retained_checkpoint_model_pin"]) == _wire(model)
             and entry["checkpoint_optimizer_sha256"] == hashlib.sha256(_wire(checkpoint["optimizer_state"])).hexdigest(),
             "formula model/Adam digest differs")
    inputs = base._inputs(archive, entry["inputs"], role, checkpoint, fixtures[role + "_training_inputs"])
    plan = base._model_bytes(checkpoint)
    lanes = entry["lanes"]
    _require(type(lanes) is dict and set(lanes) == set(base.CPU_LANES + base.CUDA_LANES)
             and entry["numerical_and_canonical_qualified"] is True, "complete formula diagnostic route coverage missing")
    canonical, numeric, algebra, summaries, constructors = {}, {}, {}, {}, []
    for label in base.CPU_LANES + base.CUDA_LANES:
        panel, lease = lanes[label], leases[(width, label)]
        constructor = panel["constructor"]
        _require(constructor["route"] == label and constructor["started"] is True and constructor["completed"] is True
                 and _integer(constructor["dimension"]) == width and constructor["checkpoint_sha256"] == entry["checkpoint_sha256"]
                 and constructor["observation_scope"] == "constructor_only_source_bound_python_call_observer"
                 and _integer(constructor["adam_restore_attempts"]) == _integer(constructor["adam_restore_completions"]) == 1,
                 "actual cold Adam restore constructor receipt differs")
        base._positive(constructor["elapsed_seconds"])
        constructors.append(constructor)
        _require(_wire(panel["state_before"]) == _wire(model) == _wire(panel["state_after"])
                 and panel["checkpoint_and_adam_unchanged"] is True, "formula model/checkpoint/Adam was changed")
        base._source_profile(panel["profile"], label, checkpoint, shas, plan, public=False, lease=lease, cuda_device=cuda_device)
        if label in base.CPU_LANES:
            _require(type(panel["counts"]) is dict and set(panel["counts"]) == {"1", "16", "32"}, "complete CPU references missing")
            for count in COUNTS:
                decision, vectors, _ = _formula_observation(base, archive, panel["counts"][str(count)],
                    f"{role}-{label}-{count}", label, count, checkpoint, inputs, shas, plan, lease, cuda_device, code_sources,
                    canonical=canonical.get(count), numeric=numeric.get(count))
                if label == "original_cpu_reference":
                    expected = base._projection_algebra(checkpoint, [row["latent"] for row in inputs["rows"][:count]])
                    algebra[str(count)] = base._numeric(expected, vectors)
                    canonical[count], numeric[count] = decision, vectors
        else:
            _require(panel["counts"] == {}, "instrumented CUDA probes must use separate declared panels")
            _formula_observation(base, archive, panel["warmup"], f"{role}-{label}-warmup", label, 32, checkpoint,
                inputs, shas, plan, lease, cuda_device, code_sources, canonical=canonical[32], numeric=numeric[32])
    _joint_resources(entry["three_way_admission"], {label: leases[(width, label)] for label in base.CUDA_LANES}, 3,
                     live_name="all_three_gpu_children_live")
    _require(type(entry["counts"]) is dict and set(entry["counts"]) == {"1", "16", "32"}, "complete CUDA diagnostic counts missing")
    for count in COUNTS:
        group = entry["counts"][str(count)]
        _require(group["instrumented"] is True and type(group["observations"]) is dict
                 and set(group["observations"]) == set(base.CUDA_LANES), "complete instrumented three-route observations missing")
        summaries[str(count)] = {}
        for label in base.CUDA_LANES:
            _, _, costs = _formula_observation(base, archive, group["observations"][label], f"{role}-{count}-{label}-profile",
                label, count, checkpoint, inputs, shas, plan, leases[(width, label)], cuda_device, code_sources,
                canonical=canonical[count], numeric=numeric[count], profiled=True, profiling_pid=profiling_pid)
            summaries[str(count)][label] = costs
    _require(type(entry["new_cuda_controls"]) is dict and set(entry["new_cuda_controls"]) == {"bitwise_v1_cuda", "bitwise_v2_cuda"},
             "both bitwise native guard controls required")
    for controls in entry["new_cuda_controls"].values():
        base._controls(controls, checkpoint)
    return {"dimension": width, "public_reports": 21, "profiled_reports": 9, "numeric_projections": 21,
            "checkpoint_float32_anchor": plan, "original_cpu_projection_algebra_max_abs_errors": algebra,
            "counts": summaries}, constructors


def _joint_resources(value, leases, count, *, live_name):
    _require(value[live_name] is True and _wire(value["child_leases"]) == _wire(leases),
             "joint live CUDA children do not join owned admission")
    resource = value["resources"]
    _require(tuple(_integer(resource[name]) for name in ("active_lease_count", "active_root_lease_count", "active_child_lease_count"))
             == (count + 1, 1, count) and _integer(resource["waiting_request_count"]) == 0
             and _integer(resource["allocated"]["cpu_slots"]) == 3 and _integer(resource["allocated"]["memory_mb"]) == 3072
             and _integer(resource["allocated_gpu_memory_mb"]) == 768
             and _integer(resource["allocated_unified_memory_mb"]) == 3840, "joint live root resource counters differ")


def _dimension_cleanup(base, result, routes):
    final = result["resources_after"]
    for name in ("active_lease_count", "active_root_lease_count", "active_child_lease_count", "waiting_request_count"):
        _require(_integer(final[name]) == 0, "final resource counters must be plain zero")
    _require(_integer(final["allocated"]["cpu_slots"]) == _integer(final["allocated"]["memory_mb"]) ==
             _integer(final["allocated_gpu_memory_mb"]) == _integer(final["allocated_unified_memory_mb"]) == 0,
             "final resource allocation counters must be plain zero")
    root = result["admission"]
    _require(tuple(_integer(root[name]) for name in ("cpu_slots", "memory_mb", "gpu_memory_mb", "unified_memory_mb"))
             == (3, 3072, 768, 3840) and root["requires_gpu"] is True and root["released"] is False
             and root["cancelled"] is False and _integer(root["owner_pid"], 1) == _integer(result["pid"], 1)
             and result["safe_owned_cleanup_established"] is True and result["root_release_observed"] is True
             and result["own_root_lease_released"] is True
             and result["cuda_cleanup_status"] == "owned_allocations_restored_to_baseline", "root owned closure differs")
    for name in ("gpu_allocated_before_producer_imports_bytes", "gpu_allocated_before_owned_sessions_bytes",
                 "gpu_allocated_after_framework_workspace_clear_bytes"):
        _require(_integer(result[name]) == 0, "CUDA allocator baseline closure must be plain zero")
    labels = {route + suffix for route in routes for suffix in ("_cpu_opt_out", "_cuda")}
    children, identities = result["owned_children"], set()
    _require(type(children) is list and len(children) <= len(labels), "bounded dimension-owned children required")
    leases = {}
    for item in children:
        label, admission = item["route"], item["admission"]
        cuda = label.endswith("_cuda")
        _require(label in labels and label not in leases and item["lease_id"] not in identities
                 and item["lease_id"] == admission["lease_id"] and item["release_observed"] is True,
                 "unique dimension-owned child route/release differs")
        _require(tuple(_integer(admission[name]) for name in ("cpu_slots", "memory_mb", "gpu_memory_mb", "unified_memory_mb"))
                 == (1, 1024, 256 if cuda else 0, 1280 if cuda else 0) and admission["requires_gpu"] is cuda
                 and admission["parent_lease_id"] == root["lease_id"] and admission["released"] is False
                 and admission["cancelled"] is False and _integer(admission["owner_pid"], 1) == result["pid"],
                 "dimension-owned child process/root/budget differs")
        leases[label] = admission
        identities.add(item["lease_id"])
    return leases


def _synthetic_projection(span, report):
    names = ("lineage_id", "checkpoint_sha256", "context_contract_sha256", "input_dimension", "decoded_count", "status",
        "latent_ablation", "target_access", "teacher_forcing", "training_executed", "model_state_unchanged", "qualified",
        "admitted", "formalized", "roundtrip_ok", "proof_authority", "semantic_correctness_verified", "promotion_performed", "publication_performed")
    marked = span._decisions(report, "span")
    return {name: marked[name] for name in (*names, "rows")}


def _dimension_profile(base, span, profile, dimension, label, checkpoint, shas, plan, lease, device):
    cuda, route = label.endswith("_cuda"), label.rsplit("_", 1)[0] if label.endswith("_cuda") else label[:-12]
    bitwise = route.startswith("bitwise")
    _require(_integer(profile["dimension"]) == dimension and profile["optimized"] is cuda and profile["device"] == device
             and profile["dtype"] == "float32" and profile["checkpoint_sha256"] == hashlib.sha256(_wire(checkpoint)).hexdigest()
             and profile["optimizer_state_sha256"] == hashlib.sha256(_wire(checkpoint["optimizer_state"])).hexdigest()
             and profile["stored_checkpoint_device"] == "cpu" and profile["checkpoint_conversion_performed"] is False
             and profile["inference_only"] is True and profile["canonical_decision_device"] ==
                 ("resident_cpu" if dimension == 768 and not cuda else "cpu")
             and profile["numerical_batching"] == ("one_complete_valid_source_batch" if cuda else "singleton_cpu_opt_out"),
             "dimension checkpoint/profile/device/precision differs")
    _require(_wire(profile["resource_lease"]) == _wire(lease), "dimension profile does not join owned exact child")
    policy = profile["precision_policy"]
    _require(policy["persistent_flags_mutated"] is False and policy["cuda_gru_allow_tf32"] is (False if cuda else None),
             "dimension scoped precision differs")
    if dimension == 768:
        expected = "native-768-source-span-batched-device-float32-cpu-decisions/v1"
        bit_profile = "native-768-source-span-batched-device-bitwise-checkpoint-anchor-float32/v1"
        _require(profile["profile_id"] == (bit_profile if bitwise and cuda else expected), "768 actual route profile differs")
        span._sources(profile, "span", bitwise, checkpoint, shas)
        if bitwise:
            _require(profile["session_profile_id"] == bit_profile, "768 bitwise session identity differs")
    else:
        expected = "native-4096-source-span-batched-device-float32-cpu-decisions/v2"
        bit_profile = "native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/" + ("v2" if route == "bitwise_v2" else "v1")
        _require(profile["profile_id"] == (bit_profile if bitwise and cuda else expected)
                 and profile["strict_cuda_gru_profile_id"] == "native-4096-source-span-strict-cuda-float32/v1"
                 and profile["synthetic_unreceipted_enabled"] is True, "4096 synthetic route profile differs")
        implementation = profile["implementation"]
        if bitwise:
            role = "legal_span_4096_bitwise_device_inference" + ("_v2" if route == "bitwise_v2" else "")
            _require(profile["session_profile_id"] == bit_profile and profile["inherited_profile_id"] == expected
                     and implementation["source_sha256"] == shas[role]
                     and implementation["inherited_session_source_sha256"] == shas["legal_span_4096_device_inference"]
                     and implementation["bitwise_guard_source_sha256"] == shas["owned_tensor_bitwise_guard"]
                     and implementation["boundary_consolidation_performed"] is False, "4096 bitwise source/custody joins differ")
            _require(implementation["schema"] == "native-4096-bitwise-device-session-implementation/" +
                     ("v2" if route == "bitwise_v2" else "v1"), "4096 bitwise implementation schema differs")
            if route == "bitwise_v2":
                _require(implementation["duplicate_transitive_verification_in_pure_check"] is False
                         and implementation["source_verification_success_cached"] is False,
                         "4096 bitwise v2 duplicate verification policy differs")
            else:
                _require("source_verification_success_cached" not in implementation,
                         "4096 v1 receipt invents a v2 verification declaration")
            implementation = implementation["inherited_session_implementation"]
        _require(implementation["source_sha256"] == shas["legal_span_4096_device_inference"]
                 and _wire(implementation["native4096_checkpoint_producer"]) == _wire(checkpoint["implementation"])
                 and implementation["owned_tensor_value_guard_sha256"] == shas["owned_tensor_value_guard"],
                 "4096 original source/checkpoint/value comparator joins differ")
    if bitwise or dimension == 4096:
        anchor, guard = profile["reference_byte_currentness"], profile["owned_tensor_currentness"]
        expected_origin = ("independently_restored_validated_cpu_checkpoint_model" if dimension == 4096 else
                           "independently_restored_validated_cpu_checkpoint_model_before_upload")
        _require(anchor["checkpoint_sha256"] == hashlib.sha256(_wire(checkpoint)).hexdigest()
                 and anchor["anchor_sha256"] == plan["sha256"] and _integer(anchor["reference_bytes"]) == plan["bytes"]
                 and anchor["origin"] == expected_origin and anchor["anchor_identity_checked"] is True
                 and anchor["reference_device"] == device and _integer(anchor["device_to_cpu_reference_transfers"]) == int(cuda)
                 and anchor["metadata_and_reservation_checked_before_allocation"] is True,
                 "independent dimension checkpoint immutable float32 byte anchor differs")
        kind, role = ("bitwise", "owned_tensor_bitwise_guard") if bitwise else ("value", "owned_tensor_value_guard")
        mode = "cpu_reference_checks" if not cuda else "cuda_bitwise_single_host_decision" if bitwise else "cuda_single_host_decision"
        comparison = "finite-float32-exact-bits-with-reference-finiteness/v1" if bitwise else "finite-float32-exact-values-and-signed-zero/v1"
        _require(guard["schema"] == "owned-tensor-" + ("bitwise-value" if bitwise else "value") + "-guard/v1"
                 and guard["mode"] == mode and guard["comparison_device"] == device
                 and _wire(guard["implementation"]) == _wire({"schema": "owned-tensor-" + kind + "-guard-implementation/v1",
                     "comparison": comparison, "source_sha256": shas[role]})
                 and _integer(guard["tensor_count"]) == plan["tensor_count"]
                 and _integer(guard["state_and_reference_bytes"]) == 2 * plan["bytes"]
                 and _integer(guard["host_decision_count"]) == (1 if cuda else 4 * plan["tensor_count"])
                 and all(guard[key] is True for key in ("finite_values_checked", "signed_zero_checked", "all_current_values_checked")),
                 "complete dimension tensor comparator receipt differs")
    base._authority(profile)


def _numeric_dimension(base, span, archive, panel, label, count, dimension, inputs, reference, device):
    stem = f"{label}-{count}"
    rows = archive.value(panel["complete_four_logits"], name=stem + "-four-logits.json", unique=True)
    scope = archive.value(panel["numeric_scope"], name=stem + "-numeric-scope.json", unique=True)
    _require(type(rows) is list and len(rows) == count, "complete dimension four-logit rows required")
    tokens = [len(span._tokens(text)) for text in inputs["texts"][:count]]
    for index, row in enumerate(rows):
        _require(type(row) is dict and set(row) == {"modality", "presence", "start", "end"}, "all four numeric heads required")
        base._shape(row["modality"], (1, 3))
        base._shape(row["presence"], (1, 4, 2))
        _integer(tokens[index], 1, 256)
        base._shape(row["start"], (1, 6, tokens[index]))
        base._shape(row["end"], (1, 6, tokens[index]))
    cuda = label.endswith("_cuda")
    _require(scope["singletons"] is (not cuda) and (scope["entry_and_exit_owned_session_checks"] is True
             if dimension == 4096 and cuda else scope["entry_and_exit_owned_checks"] is True),
             "separate numeric scope/singleton owned checks differ")
    if dimension == 768:
        _require(scope["scope"] == "separate_checked_private_four_logit_forward_outside_public_timing"
                 and scope["coverage"] == "one_snapshot_per_lane_per_count", "768 numeric snapshot scope differs")
        forwards = scope["observations"]
    elif not cuda:
        _require(scope["scope"] == "separate_checked_private_four_logits", "4096 singleton snapshot scope differs")
        _require(all(item["scope"] == "benchmark_only_checked_private_forward"
                     and item["entry_and_exit_owned_session_checks"] is True and len(item["observations"]) == 1
                     for item in scope["per_singleton_scopes"]), "4096 singleton checked scope differs")
        forwards = [item["observations"][0] for item in scope["per_singleton_scopes"]]
    else:
        _require(scope["scope"] == "benchmark_only_checked_private_forward", "4096 CUDA checked scope differs")
        forwards = scope["observations"]
    _forward_scope(forwards, tokens, device, dimension, cuda)
    if reference is not None:
        errors = {name: max(base._numeric(left[name], right[name]) for left, right in zip(reference, rows))
                  for name in ("modality", "presence", "start", "end")}
        _require(_wire(panel["max_abs_errors"]) == _wire(errors), "complete four-logit numeric error arithmetic differs")
    else:
        _require("max_abs_errors" not in panel, "original CPU numeric reference must be independent")
    return rows


def _forward_scope(forwards, tokens, device, dimension, cuda):
    _require(type(forwards) is list and len(forwards) == (1 if cuda else len(tokens)), "complete actual forward coverage differs")
    for index, forward in enumerate(forwards):
        lengths = tokens if cuda else [tokens[index]]
        _require(_integer(forward["rows"]) == len(lengths) and forward["source_tokens"] == lengths
                 and _integer(forward["native_input_dimension"]) == dimension and forward["input_device"] == device
                 and forward["output_dtype"] == "float32" and forward["gru_executed"] is True
                 and set(forward["output_devices"]) == {"modality", "presence", "start", "end"}
                 and all(item == device for item in forward["output_devices"].values()), "numeric actual device/source forward differs")
        if cuda:
            precision = forward["gru_precision"]
            _require(precision["profile_id"] == ("native-768-source-span-device-strict-cuda-float32/v2" if dimension == 768 else
                     "native-4096-source-span-strict-cuda-float32/v1") and precision["scoped_cudnn"] is True
                     and precision["effective_policy"]["cudnn"]["allow_tf32"] is False
                     and precision["synchronized_before_restore"] is True and precision["ambient_flags_restored"] is True,
                     "numeric strict CUDA policy/restoration differs")


def _dimension_native_policy(result, shas, route_count):
    fields = {"native_operator_counts", "native_operator_profiled_return_count", "native_operator_profile_scope"}
    if result["schema"] not in (DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6):
        _require(not (fields & set(result)), "historical dimension archive cannot acquire representative trace policy")
        return None
    _require(shas["benchmark"] == (DIMENSION_PRODUCER_V6_SHA if result["schema"] == DIMENSION_SCHEMA_V6 else DIMENSION_PRODUCER_V5_SHA)
             and _wire(result["native_operator_counts"]) == _wire([1])
             and _integer(result["native_operator_profiled_return_count"]) == _integer(route_count, 2, 3)
             and result["native_operator_profile_scope"] ==
                 "representative_cuda_count1_only_larger_counts_python_source_costs_only",
             "fixed representative native count/route coverage policy differs")
    return (1,)


def _dimension_native_panel(archive, observed, stem, count, *, profiling_pid, native_event_limit, representative_counts=None):
    """Join collected trace bytes or explicitly refuse large-call coverage."""
    if representative_counts is not None:
        _require(representative_counts == (1,) and type(count) is int and count in COUNTS,
                 "closed representative native trace counts required")
        collected = count in representative_counts
        _require(observed["native_operator_profiled"] is collected
                 and observed["native_operator_not_collected_scope"] == (None if collected else
                     "outside_fixed_representative_native_trace_counts_python_observer_only"),
                 "diagnostic observation native collection scope differs")
        if not collected:
            _require(observed["operators"] is None, "uncollected larger-call native trace must be absent")
            return None
    else:
        _require("native_operator_profiled" not in observed and "native_operator_not_collected_scope" not in observed,
                 "historical full native trace cannot acquire representative observation scope")
    native = archive.value(observed["operators"], name=stem + "-operators.json", unique=True)
    return _operator_trace(native, expected_pid=profiling_pid, expected_event_limit=native_event_limit)


def _dimension_observation(base, span, archive, observed, label, count, phase, dimension, inputs, checkpoint,
                           shas, plan, lease, device, code_sources, reference, logits, max_callback_events, *, profiling_pid, native_event_limit, representative_counts=None):
    stem = f"{label}-{count}-{phase}"
    report = archive.value(observed["result"], name=stem + "-result.json", unique=True)
    decision = archive.value(observed["decision_projection"], name=stem + "-decision-projection.json", unique=True)
    base._authority(report)
    _require(report["checkpoint_sha256"] == hashlib.sha256(_wire(checkpoint)).hexdigest()
             and type(report["rows"]) is list and len(report["rows"]) == count
             and _integer(report["input_dimension"]) == dimension and report["latent_ablation"] == "none"
             and report["lineage_id"] == checkpoint["lineage_id"]
             and report["context_contract_sha256"] == checkpoint["context_contract_sha256"],
             "public dimension checkpoint/input/lineage/context differs")
    if dimension == 768:
        span._row_inputs(report, "span", count, inputs, checkpoint)
        canonical = span._decisions(report, "span")
    else:
        for returned, text, vector in zip(report["rows"], inputs["texts"][:count], inputs["vectors"][:count]):
            _require(returned["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
                     and returned["latent_sha256"] == hashlib.sha256(_wire(vector)).hexdigest()
                     and _wire(returned["span_diagnostics"]["tokens"]) == _wire(span._tokens(text)),
                     "synthetic public source/latent/token join differs")
        decoded = sum(row["status"] == "decoded" for row in report["rows"])
        _require(_integer(report["decoded_count"]) == decoded
                 and report["status"] == ("decoded" if decoded == count else "partial" if decoded else "abstained"),
                 "synthetic decoded/status arithmetic differs")
        canonical = _synthetic_projection(span, report)
    _require(_wire(decision) == _wire(canonical), "saved complete decision projection differs from raw public return")
    if reference is not None:
        _require(_wire(decision) == _wire(reference), "complete dimension canonical decisions differ from original CPU")
    _require(observed["canonical_matches_original_cpu"] is (reference is not None)
             and observed["cpu_cuda_rng_unchanged"] is True and observed["caller_input_copies_before_interval"] is True
             and observed["instrumented"] is (phase == "profiled")
             and observed["elapsed_seconds_scope"] == "outer_diagnostic_interval_including_registry_profiler_startup_drain_and_completion_sync"
             and observed["instrumented_durations_qualify_speedup"] is False, "diagnostic public phase/input/timing scope differs")
    elapsed = base._positive(observed["elapsed_seconds"])
    profile = report["execution_profile"]
    _dimension_profile(base, span, profile, dimension, label, checkpoint, shas, plan, lease, device)
    _require(report["cuda_executed"] is label.endswith("_cuda"), "public CUDA actual execution flag differs")
    forwards = report["actual_forward_batches"]
    _forward_scope(forwards, [len(span._tokens(text)) for text in inputs["texts"][:count]],
                   device, dimension, label.endswith("_cuda"))
    # Independent bounded scalar selection/offset arithmetic joins the four
    # retained logits to both raw public calls; recurrent/model code is absent.
    decisions = [span._span_decision(text, row) for text, row in zip(inputs["texts"][:count], logits)]
    span._span_join(report, decisions)
    costs = None
    if phase == "profiled":
        python = archive.value(observed["python_costs"], name=stem + "-python-costs.json", unique=True)
        native = _dimension_native_panel(archive, observed, stem, count, profiling_pid=profiling_pid,
            native_event_limit=native_event_limit, representative_counts=representative_counts)
        costs = {"python": _python_profile(python, code_sources, observed, max_callback_events=max_callback_events,
                    manual_source_role="cost_profiler", registry_binding=IDENTITY_POLICY
                    if shas["cost_profiler"] == FORMULA_PRODUCER_V2_SHA else None),
                 "operators": native}
        _require(costs["python"]["manual_wall_ns"] <= elapsed * 1e9,
                 "manual public interval exceeds enclosing instrumentation interval")
    return canonical, costs


RETAINED_DIMENSION_PROGRESS = {
    768: {"epochs_completed": 0, "optimizer_steps": 1, "row_cursor": 2},
    4096: {"epochs_completed": 0, "optimizer_steps": 0, "row_cursor": 0}}
RETAINED_DIMENSION_PARENT_PROGRESS = {"epochs_completed": 1, "optimizer_steps": 3, "row_cursor": 2}
RETAINED_768_PARENT_SHA = "72fcb7430d0c676bf1e8b5e9e427a272a1dfcd1bc062e5dcd7667b03dda71fa9"


def _progress_binding(checkpoint, dimension, checkpoint_sha, parent_sha):
    """Reconstruct content provenance only; no training execution is inferred."""
    _require(type(checkpoint) is dict and type(dimension) is int and dimension in RETAINED_DIMENSION_PROGRESS
             and type(checkpoint_sha) is str and hashlib.sha256(_wire(checkpoint)).hexdigest() == checkpoint_sha,
             "retained dimension checkpoint bytes do not join fixed SHA")
    progress = checkpoint["progress"]
    expected_progress = RETAINED_DIMENSION_PROGRESS[dimension]
    _require(type(progress) is dict and set(progress) == set(expected_progress)
             and all(type(value) is int and value >= 0 for value in progress.values())
             and _wire(progress) == _wire(expected_progress), "exact retained dimension child progress differs")
    steps = _integer(checkpoint["source_parent_optimizer_steps"])
    parent = checkpoint["source_parent_checkpoint"]
    if dimension == 768:
        _require(type(parent) is dict and type(parent_sha) is str and steps == 3
                 and checkpoint["source_parent_checkpoint_sha256"] == parent_sha
                 and hashlib.sha256(_wire(parent)).hexdigest() == parent_sha,
                 "retained dimension source-parent bytes do not join fixed SHA")
        parent_progress = parent["progress"]
        _require(type(parent_progress) is dict and set(parent_progress) == set(RETAINED_DIMENSION_PARENT_PROGRESS)
                 and all(type(value) is int and value >= 0 for value in parent_progress.values())
                 and _wire(parent_progress) == _wire(RETAINED_DIMENSION_PARENT_PROGRESS),
                 "exact retained dimension source-parent progress differs")
    else:
        _require(parent_sha is None and parent is None and steps == 0
                 and checkpoint["source_parent_checkpoint_sha256"] is None,
                 "synthetic retained checkpoint must not acquire a trained parent")
        parent_progress = None
    return {"schema": "dimension-retained-checkpoint-progress-binding/v1",
        "checkpoint_sha256": checkpoint_sha, "checkpoint_progress": progress,
        "source_parent_checkpoint_sha256": parent_sha, "source_parent_optimizer_steps": steps,
        "source_parent_progress": parent_progress,
        "scope": "exact_retained_content_and_embedded_parent_sha256_new_training_counters_separate",
        "training_execution_authenticated": False, "model_quality_qualified": False,
        "new_training_execution_claimed": False}


def _dimension_family(base, archive, result, dimension, fixtures, shas, code_sources):
    span = _load_current(SPAN_HELPER, SPAN_HELPER_BYTES, SPAN_HELPER_SHA)
    routes = ("original", "bitwise_v1") if dimension == 768 else ("original", "bitwise_v1", "bitwise_v2")
    max_callback_events = _budget_policy(result, shas)
    representative_counts = _dimension_native_policy(result, shas, len(routes))
    native_event_limit = 50000 if result["schema"] in (DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6) else 15000
    _require(result["routes"] == list(routes) and _wire(result["counts"]) == _wire(list(COUNTS))
             and result["synthetic_only"] is (dimension == 4096)
             and _integer(result["retained_training_steps"]) ==
                 (RETAINED_DIMENSION_PROGRESS[dimension]["optimizer_steps"] if result["schema"] in (DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6) else
                  30 if dimension == 768 else 0)
             and result["numeric_tolerance_absolute"] == 5e-5 and type(result["numeric_tolerance_absolute"]) is float,
             "dimension synthetic/trained scope/count/tolerance differs")
    for name in ("native_leanstral_outputs_qualified", "trained_4096_latent_conditioning_qualified",
                 "resource_configuration_changed", "instrumented_durations_qualify_speedup"):
        _require(result[name] is False, "dimension profiling scope exceeds retained fixture evidence")
    expected_scopes = {"counter_scope": "source_bound_python_observer_chained_through_cost_profiler_all_authored_model_calls",
        "encoder_counter_scope": "no_encoder_import_or_invocation_in_authored_harness_no_execution_attestation",
        "profiling_scope": "one_instrumented_call_per_cuda_route_count_no_repeatability_or_gain_claim",
        "numeric_scope": "separate_checked_private_four_logits_per_lane_count_original_cpu_singleton_reference",
        "historical_receipt_scope": "exact_content_only_no_fresh_encoder_or_origin_attestation" if dimension == 768 else
            "explicit_unreceipted_synthetic_fixture_only_native_gate_closed"}
    _require(all(result[key] == value for key, value in expected_scopes.items()), "dimension counter/diagnostic/numeric scope differs")
    _require(_integer(result["optimizer_constructor_calls"]) == 0, "span restore must not construct an optimizer")
    checkpoint = fixtures["checkpoint"]
    if result["schema"] in (DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6):
        binding = _progress_binding(checkpoint, dimension, DIMENSION_FIXTURES[dimension]["checkpoint"],
                                    RETAINED_768_PARENT_SHA if dimension == 768 else None)
        _require(_wire(result["retained_checkpoint_progress_binding"]) == _wire(binding),
                 "reported child/parent retained progress binding differs from ordinary checkpoint bytes")
    _require(result["checkpoint_sha256"] == DIMENSION_FIXTURES[dimension]["checkpoint"]
             and _integer(checkpoint["progress"]["optimizer_steps"]) == result["retained_training_steps"],
             "fixed dimension checkpoint/training progress differs")
    model = {"bytes": len(_wire(checkpoint["model_state"])), "sha256": hashlib.sha256(_wire(checkpoint["model_state"])).hexdigest()}
    _require(_wire(result["checkpoint_model_pin"]) == _wire(model)
             and result["checkpoint_optimizer_sha256"] == hashlib.sha256(_wire(checkpoint["optimizer_state"])).hexdigest(),
             "dimension restored model/Adam pin differs")
    plan = span._model_bytes(checkpoint)
    _require(_integer(plan["tensor_count"]) == 23, "exact native dimension checkpoint parameter inventory required")
    inputs = archive.value(result["inputs"], name="dimension-inference-inputs.json")
    _require(inputs["schema"] == "dimension-guard-profiling-inputs/v1" and _integer(inputs["dimension"]) == dimension
             and inputs["encoder_execution_performed"] is False and inputs["synthetic_unreceipted"] is (dimension == 4096),
             "dimension inference input scope differs")
    if dimension == 768:
        saved = fixtures["historical_outputs"]
        expected = {"texts": [row["source_text"] for row in fixtures["sources"]], "vectors": saved["vectors"],
                    "receipts": saved["receipts"], "receipt_pins": [hashlib.sha256(_wire(row)).hexdigest() for row in saved["receipts"]]}
    else:
        expected = {"texts": [row["source_text"] for row in fixtures["rows"]], "vectors": [row["latent"] for row in fixtures["rows"]]}
    _require(all(_wire(inputs[key]) == _wire(value) for key, value in expected.items()) and len(inputs["texts"]) == len(inputs["vectors"]) == 32,
             "dimension target-free input/historical fixture join differs")
    for text, vector in zip(inputs["texts"], inputs["vectors"]):
        _require(type(text) is str and 0 < len(text) <= 8192 and 1 <= len(span._tokens(text)) <= 256,
                 "bounded exact dimension source text/token coverage required")
        base._input_shape(vector, (dimension,))
    leases = _dimension_cleanup(base, result, routes)
    labels = tuple(route + "_cpu_opt_out" for route in routes) + tuple(route + "_cuda" for route in routes)
    _require(type(result["lanes"]) is dict and set(result["lanes"]) == set(labels) == set(leases),
             "complete uniquely owned dimension routes required")
    reference, numeric_reference, summaries, profiled_calls = {}, {}, {}, []
    for label in labels:
        panel, cuda = result["lanes"][label], label.endswith("_cuda")
        route = label[:-5] if cuda else label[:-12]
        device = f"cuda:{result['hardware']['device_index']}" if cuda else "cpu"
        _require(panel["route"] == route and panel["optimized"] is cuda
                 and _wire(panel["state_before"]) == _wire(model) == _wire(panel["state_after"])
                 and panel["checkpoint_and_adam_unchanged"] is True, "dimension restored/closed owner state differs")
        base._positive(panel["constructor_seconds"])
        _dimension_profile(base, span, panel["profile"], dimension, label, checkpoint, shas, plan, leases[label], device)
        _require(type(panel["counts"]) is dict and set(panel["counts"]) == {"1", "16", "32"}, "complete dimension count panels required")
        summaries[label] = {}
        for count in COUNTS:
            entry = panel["counts"][str(count)]
            logits = _numeric_dimension(base, span, archive, entry, label, count, dimension, inputs, numeric_reference.get(count), device)
            decision, _ = _dimension_observation(base, span, archive, entry["reference"], label, count, "reference", dimension,
                inputs, checkpoint, shas, plan, leases[label], device, code_sources, reference.get(count), logits, max_callback_events, profiling_pid=result["pid"], native_event_limit=native_event_limit, representative_counts=representative_counts)
            if label == "original_cpu_opt_out":
                reference[count], numeric_reference[count] = decision, logits
            if cuda:
                _, costs = _dimension_observation(base, span, archive, entry["profiled"], label, count, "profiled", dimension,
                    inputs, checkpoint, shas, plan, leases[label], device, code_sources, reference[count], logits, max_callback_events, profiling_pid=result["pid"], native_event_limit=native_event_limit, representative_counts=representative_counts)
                summaries[label][str(count)] = costs
                profiled_calls.append({"route": label, "count": count, **entry["profiled"]})
        if cuda and dimension == 768 and route.startswith("bitwise"):
            base._controls(panel["corruption_controls"], checkpoint)
        if cuda and dimension == 4096:
            controls = panel["corruption_controls"]
            _require(type(controls) is list and len(controls) == 3
                     and {item["corruption"] for item in controls} == {"paired_finite_value", "paired_signed_zero", "anchor_object_replacement"},
                     "4096 paired finite/zero/anchor refusal coverage missing")
            for item in [*controls, panel["model_only_subnormal_control"]]:
                _require(item["refused"] is True and item["entry_refused_before_forward"] is True
                         and type(item["refusal"]) is str and 0 < len(item["refusal"]) <= 8192,
                         "4096 native guard corruption refusal missing")
            item = panel["model_only_subnormal_control"]
            _require(item["corruption"] == "model_only_smallest_positive_float32_subnormal"
                     and _integer(item["actual_float32_bits_int32"]) == 1, "4096 actual subnormal-bit refusal differs")
    if representative_counts is not None:
        collected = sum(observed["native_operator_profiled"] is True for observed in profiled_calls)
        _require(collected == len(routes) == result["native_operator_profiled_return_count"],
                 "native representative collection count does not join actual profiled panels")
    _require(_wire(result["profiled_calls"]) == _wire(profiled_calls), "profiled top journal does not join all unique route/count returns")
    _joint_resources(result["joint_cuda_admission"], {label: leases[label] for label in labels if label.endswith("_cuda")}, len(routes),
                     live_name="all_requested_children_live")
    expected_total = 9 * len(routes)
    _require(_integer(result["total_return_count"]) == expected_total
             and _integer(result["profiled_return_count"]) == 3 * len(routes)
             and _integer(result["numeric_snapshot_count"]) == 6 * len(routes), "complete dimension coverage totals differ")
    _helper_bytes(SPAN_HELPER, SPAN_HELPER_BYTES, SPAN_HELPER_SHA)
    return {"dimension": dimension, "public_reports": expected_total, "profiled_reports": 3 * len(routes),
            "numeric_snapshots": 6 * len(routes), "checkpoint_float32_anchor": plan, "counts": summaries,
            "python_profiles": 3 * len(routes),
            "native_operator_traces": len(routes) if representative_counts is not None else 3 * len(routes),
            "native_operator_counts": list(representative_counts) if representative_counts is not None else list(COUNTS),
            "native_large_batch_coverage_claimed": representative_counts is None}


def _budget_policy(result, shas):
    if result["schema"] not in (DIMENSION_SCHEMA_V2, DIMENSION_SCHEMA_V3, DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6):
        _require("callback_limit_policy" not in result and "observer_budget_adapter_policy" not in result
                 and "cost_observer_budget" not in shas, "original profiling policy must retain original callback cap")
        return 1000000
    large4096 = result["schema"] == DIMENSION_SCHEMA_V6
    _require(not large4096 or (type(result["dimension"]) is int and result["dimension"] == 4096),
             "separately pinned 8M callback policy is restricted to retained 4096 diagnostic")
    maximum = 8000000 if large4096 else 4000000
    newest = result["schema"] in (DIMENSION_SCHEMA_V3, DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6)
    base_sha = FORMULA_PRODUCER_V2_SHA if newest else FORMULA_PRODUCER_SHA
    _require(shas["cost_observer_budget"] == (COST_OBSERVER_BUDGET_V4_SHA if large4096 else
                 COST_OBSERVER_BUDGET_V3_SHA if newest else COST_OBSERVER_BUDGET_SHA)
             and shas["benchmark"] == (DIMENSION_PRODUCER_V6_SHA if large4096 else
                 DIMENSION_PRODUCER_V5_SHA if result["schema"] == DIMENSION_SCHEMA_V5 else
                 DIMENSION_PRODUCER_V4_SHA if result["schema"] == DIMENSION_SCHEMA_V4 else
                 DIMENSION_PRODUCER_V3_SHA if newest else DIMENSION_PRODUCER_V2_SHA)
             and shas["cost_profiler"] == base_sha, "new callback budget requires exact pinned adapter and producer")
    _require(_wire(result["callback_limit_policy"]) == _wire({"schema": "dimension-guard-cost-callback-budget/" + ("v3" if large4096 else "v2"),
             "max_callback_events": maximum, "scope": "all_python_and_c_callbacks_including_unselected_recursive_guard_atoms",
             "selected_span_limit": 20000, "native_operator_postcollection_limit":
                 50000 if result["schema"] in (DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6) else 15000,
             "global_observer_limits_changed": False, "producer_checks_changed": False}),
             "instance-local callback limit declaration differs")
    adapter = {"schema": "guard-cost-observer-callback-budget/" + ("v4" if large4096 else "v3" if newest else "v2"),
             "all_profile_callback_cap": maximum, "base_observer_callback_cap": 1000000, "selected_span_cap": 20000,
             "thread_cap": 32, "native_operator_cap": 50000, "base_source_sha256": base_sha,
             "scope": "owned_instance_limit_only_all_callbacks_counted_guards_unchanged",
             "overflow_scope": "diagnostic_refusal_after_operation_without_interrupting_guards",
             "base_module_or_class_mutated": False, "performance_qualified": False}
    if newest:
        adapter["registry_binding"] = IDENTITY_POLICY
    _require(_wire(result["observer_budget_adapter_policy"]) == _wire(adapter),
             "adapter policy must preserve pinned base and all current checks")
    return maximum


def review(result_path, expected_result_sha256, *, check_current_sources=False):
    base = _base()
    _require(type(check_current_sources) is bool and type(expected_result_sha256) is str
             and base.SHA.fullmatch(expected_result_sha256) is not None, "external result SHA/current-source boolean required")
    path = Path(result_path).absolute()
    _require(path.name == "result.json", "exact result.json entry required")
    raw = base._read(path)
    result_pin = base._pin(path, raw)
    _require(result_pin["sha256"] == expected_result_sha256, "external exact result SHA differs")
    result = base._json(raw)
    _require(type(result) is dict and result["schema"] in (FORMULA_SCHEMA, FORMULA_SCHEMA_V2, DIMENSION_SCHEMA,
             DIMENSION_SCHEMA_V2, DIMENSION_SCHEMA_V3, DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6), "exact diagnostic profiling schema required")
    _scope(base, result)
    if result["schema"] in (DIMENSION_SCHEMA, DIMENSION_SCHEMA_V2, DIMENSION_SCHEMA_V3, DIMENSION_SCHEMA_V4, DIMENSION_SCHEMA_V5, DIMENSION_SCHEMA_V6):
        _require(_integer(result["dimension"]) in (768, 4096)
                 and (result["schema"] != DIMENSION_SCHEMA_V6 or result["dimension"] == 4096),
                 "closed profiled dimension and separately pinned 4096 callback policy required")
        routes = ("original", "bitwise_v1") if result["dimension"] == 768 else ("original", "bitwise_v1", "bitwise_v2")
        _require(type(result["lanes"]) is dict and set(result["lanes"]).issubset(
            {route + suffix for route in routes for suffix in ("_cpu_opt_out", "_cuda")})
            and all(type(panel) is dict for panel in result["lanes"].values()), "plain closed dimension lane map required")
    else:
        base._families(result["families"])
    archive = base.Archive(path.parent, result)
    dimension, fixtures, shas, codes, pins, verified = _staging(base, archive, result, check_current_sources)
    families, totals, leftovers = {}, {}, []
    if result["qualified"] and dimension is None:
        scopes = {"scope": "retained_trained_formula8_formula384_original_v1_v2_instrumented_guard_costs",
            "counter_observation_scope": "constructors_references_warmups_controls_and_profiled_main_calls_source_bound_no_execution_attestation",
            "profile_scope": "one_instrumented_cuda_probe_per_route_count_no_repeatability_or_speed_claim",
            "native_trace_buffer_scope": "workload_bounded_postcollection_limits_no_allocator_enforcement",
            "thread_reservation_scope": "caller_owned_one_thread_restored_after_owned_cleanup"}
        _require(all(result[key] == expected for key, expected in scopes.items())
                 and result["instrumented"] is True and result["diagnostic_profile_qualified"] is True
                 and result["complete_call_measurements_qualified"] is False
                 and result["conservative_complete_call_gain_observed"] is False
                 and result["universal_speedup_claimed"] is False and result["persistent_precision_policy_mutated"] is False
                 and _wire(result["retained_fixture_positive_steps"]) == _wire({"8": 30, "384": 30})
                 and _integer(result["training_calls"]) == 0, "formula instrumented scope must not qualify inference gain")
        _require(type(result["families"]) is dict and set(result["families"]) == {"formula8", "formula384"},
                 "complete formula profiled family map required")
        admitted, leases = base._cleanup(result)
        _require(admitted and len(leases) == 12, "all formula owners require observed admission and cleanup")
        journal = base._constructor_journal(result)
        constructors = []
        for role in ("formula8", "formula384"):
            families[role], observed = _formula_family(base, archive, role, result["families"][role], fixtures, shas, codes,
                leases, f"cuda:{result['hardware']['device_index']}", result["pid"])
            constructors.extend(observed)
        _require(_wire(constructors) == _wire(journal) and len(journal) == 12
                 and _integer(result["optimizer_restore_attempts"]) == _integer(result["optimizer_constructor_calls"]) == 12,
                 "all actual cold optimizer restore journal/panel joins differ")
        totals = {"public_reports": 42, "profiled_reports": 18, "formula_projections": 42}
        _require(_integer(result["total_return_count"]) == 42 and _integer(result["profiled_return_count"]) == 18
                 and _integer(result["formula_projection_count"]) == 42, "formula full retained profiling coverage differs")
    elif result["qualified"]:
        families[str(dimension)] = _dimension_family(base, archive, result, dimension, fixtures, shas, codes)
        totals = {key: families[str(dimension)][key] for key in ("public_reports", "profiled_reports", "numeric_snapshots")}
    else:
        # A failed run can retain ordinary partial bytes. No projections,
        # traces, execution, timing or model behavior become qualified here.
        import re
        pattern = (re.compile(r"formula(?:8|384)-(?:original_cpu_reference|bitwise_v[12]_cpu_opt_out|original_cuda|bitwise_v[12]_cuda|1|16|32).+\.json\Z")
                   if dimension is None else re.compile(r"(?:original|bitwise_v[12])_(?:cpu_opt_out|cuda)-(?:1|16|32)-.+\.json\Z"))
        for remaining in sorted(set(archive.pins) - archive.used):
            _require(Path(remaining).parent == archive.root and (pattern.fullmatch(Path(remaining).name) is not None
                     or Path(remaining).name in {"formula8-inference-inputs.json", "formula384-inference-inputs.json", "dimension-inference-inputs.json"}),
                     "unknown unjoined failed diagnostic evidence")
            base._authority(archive.value(archive.pins[remaining]))
            leftovers.append(archive.pins[remaining])
        if "admission" in result and dimension is None:
            base._cleanup(result)
            base._constructor_journal(result)
        elif "admission" in result:
            _dimension_cleanup(base, result, ("original", "bitwise_v1") if dimension == 768 else ("original", "bitwise_v1", "bitwise_v2"))
    archive.finish()
    _require(base._pin(path, base._read(path)) == result_pin, "externally pinned diagnostic result changed")
    for pin in pins:
        if check_current_sources or pin["path"] in {item["path"] for item in verified}:
            _require(base._pin(pin["path"], base._read(pin["path"], readonly=False)) == pin, "current registered source/fixture changed during audit")
    _helper_bytes()
    return {"schema": REVIEW_SCHEMA, "qualified": result["qualified"], "closed_artifacts_consistent": True, "error": None,
        "producer_refusal": result["error"], "result_pin": result_pin, "expected_result_sha256": expected_result_sha256,
        "scope": "ordinary_pinned_diagnostic_public_outputs_numeric_joins_selected_source_spans_and_native_trace_aggregate_consistency",
        "check_current_sources": check_current_sources, "current_sources_verified": check_current_sources,
        "registry_current_source_bytes_compiled_without_execution": True, "current_source_pins": verified,
        "retained_pins": [result_pin, *archive.pins.values()], "families": families, "coverage": totals,
        "unjoined_failed_partial_evidence": leftovers, "bounded_archive_files": len(archive.pins) + 1,
        "bounded_archive_bytes": sum(pin["bytes"] for pin in archive.pins.values()) + len(raw),
        "instrumented_performance_qualification": False, "complete_call_gain_qualified": False,
        "whole_job_background_coverage_claimed": False, "python_operator_clock_alignment_claimed": False,
        "native_trace_buffer_allocator_enforcement": False, "retained_python_executed": False,
        "tensor_library_imported": False, "model_executed": False, "encoder_executed": False,
        "recurrent_grammar_replayed": False, "proof_authority": False, "execution_attestation": False,
        "production_qualified": False, "semantic_correctness_verified": False,
        "native_leanstral_outputs_qualified": False, "trained_4096_latent_conditioning_qualified": False,
        "universal_speedup_claimed": False, "selected_existing_profile_changed": False}


def audit(root, expected_result_sha256, *, check_current_sources=False):
    try:
        return review(Path(root).absolute() / "result.json", expected_result_sha256, check_current_sources=check_current_sources)
    except (ValueError, KeyError, TypeError, OSError, OverflowError, RecursionError, struct.error, SyntaxError) as error:
        return {"schema": REVIEW_SCHEMA, "qualified": False, "closed_artifacts_consistent": False,
            "error": {"type": type(error).__name__, "detail": str(error)}, "retained_python_executed": False,
            "tensor_library_imported": False, "model_executed": False, "encoder_executed": False,
            "instrumented_performance_qualification": False, "complete_call_gain_qualified": False,
            "proof_authority": False, "execution_attestation": False, "production_qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--expected-result-sha256", required=True)
    parser.add_argument("--check-current-sources", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    _require(args.result.name == "result.json", "exact result.json CLI entry required")
    report = audit(args.result.absolute().parent, args.expected_result_sha256, check_current_sources=args.check_current_sources)
    raw = _wire(report)
    if args.output is None:
        print(raw.decode(), flush=True)
    else:
        output = args.output.absolute()
        parent = _directory_fd(output.parent)
        try:
            descriptor = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o444)
        finally:
            os.close(parent)
        base = _base()
        _require(base._pin(output, base._read(output)) == base._pin(output, raw), "reader output differs from intended diagnostic report bytes")
    return 0 if report["closed_artifacts_consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
