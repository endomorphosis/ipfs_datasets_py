"""A separately versioned callback budget for dimension guard diagnostics.

The pinned current base observer remains unchanged. This adapter changes only
the callback limit on its own observer instance. Every callback is counted;
all guard code, selected span/thread limits and native trace limits remain.
Overflow still marks diagnostic refusal after the operation, without skipping
or interrupting live guards. Instrumented times cannot qualify a speedup.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import stat

BASE_SOURCE_SHA256 = "f0f4b9d5daa1c3380ec9f742aeacc24e815ccfee2f1e0aa180ad9fe2b08275f4"
BASE_SOURCE_BYTES = 55098
MAX_EVENTS = 4000000
POLICY_SCHEMA = "guard-cost-observer-callback-budget/v3"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _directory_fd(path):
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for component in Path(path).absolute().parts[1:]:
            _require(component != "..", "canonical current base directory required")
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _base_bytes(path):
    parent = _directory_fd(path.parent)
    try:
        parent_before = os.fstat(parent)
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and before.st_size == BASE_SOURCE_BYTES, "ordinary fixed-size current base source required")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1
                     and opened.st_size == BASE_SOURCE_BYTES, "opened current base differs")
            raw = stream.read(BASE_SOURCE_BYTES + 1)
            final_open = os.fstat(stream.fileno())
        after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        latest = _directory_fd(path.parent)
        try:
            current_parent = os.fstat(latest)
            _require((current_parent.st_dev, current_parent.st_ino) == (parent_before.st_dev, parent_before.st_ino),
                     "current base source parent changed")
        finally:
            os.close(latest)
    finally:
        os.close(parent)
    identities = [(item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns, item.st_nlink)
                  for item in (before, opened, final_open, after)]
    _require(len(raw) == BASE_SOURCE_BYTES and all(item == identities[0] for item in identities[1:])
             and hashlib.sha256(raw).hexdigest() == BASE_SOURCE_SHA256, "fixed current base source changed")
    return raw


def _load_base():
    path = Path(__file__).absolute().with_name("profile_formula_guard_costs_v2.py")
    before = _base_bytes(path)
    specification = importlib.util.spec_from_file_location("_guard_cost_budget_v3_pinned_current_base", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    _require(_base_bytes(path) == before, "current base changed during import")
    return module


_BASE = _load_base()
_BASE_OBSERVER = _BASE.GuardCostObserver
_BASE_OBSERVER_INIT = _BASE_OBSERVER.__init__

# Export only the pinned current diagnostic APIs. No module global, class or
# producer method in the base is replaced or modified.
registry_key = _BASE.registry_key
register = _BASE.register
build_registry = _BASE.build_registry
profile_public_call = _BASE.profile_public_call
_read, _pin, _settings, _load_helper = _BASE._read, _BASE._pin, _BASE._settings, _BASE._load_helper
MAX_SPANS, MAX_THREADS, MAX_OPERATOR_EVENTS = _BASE.MAX_SPANS, _BASE.MAX_THREADS, _BASE.MAX_OPERATOR_EVENTS


def callback_limit_policy():
    return {"schema": POLICY_SCHEMA, "all_profile_callback_cap": MAX_EVENTS,
        "base_observer_callback_cap": 1000000, "selected_span_cap": 20000,
        "thread_cap": 32, "native_operator_cap": 50000,
        "base_source_sha256": BASE_SOURCE_SHA256,
        "scope": "owned_instance_limit_only_all_callbacks_counted_guards_unchanged",
        "registry_binding": "code_object_identity_with_strong_references",
        "overflow_scope": "diagnostic_refusal_after_operation_without_interrupting_guards",
        "base_module_or_class_mutated": False, "performance_qualified": False}


class GuardCostObserver(_BASE_OBSERVER):
    def __init__(self, registry, *, expected_main_profiler=None, allowed_background_threads=(),
                 utility_source_role="benchmark", max_events=MAX_EVENTS,
                 max_spans=MAX_SPANS, max_threads=MAX_THREADS):
        _require(type(max_events) is int and 1 <= max_events <= MAX_EVENTS,
                 "bounded v3 callback limit required")
        _require(_BASE.MAX_EVENTS == 1000000 and _BASE.GuardCostObserver is _BASE_OBSERVER
                 and _BASE_OBSERVER.__init__ is _BASE_OBSERVER_INIT,
                 "pinned base callback admission changed")
        super().__init__(registry, expected_main_profiler=expected_main_profiler,
            allowed_background_threads=allowed_background_threads, utility_source_role=utility_source_role,
            max_events=min(max_events, _BASE.MAX_EVENTS), max_spans=max_spans, max_threads=max_threads)
        self.max_events = max_events
