#!/usr/bin/env python3
"""Targeted cProfile of two frame-ontology audit calls during preparation.

Uses the frozen cold/modal harnesses and their exact six inputs. Profiling is
enabled only inside codec._frame_ontology_audit_terms and
flogic_optimizer._frame_ontology_metadata. Nested profiler enables are skipped
and reported. All original target timeouts remain active, so profiling can
change partial bridge outcomes. Full failure telemetry and profiles are saved
even if the final source check rejects the run. This is diagnostic only.

Three coarse decompiler boundaries are also timed, without enabling cProfile.
"""
from __future__ import annotations

from contextlib import contextmanager
import cProfile
import functools
from pathlib import Path
import sys
import time

import profile_modal_target_preparation as modal


base = modal.base
MODAL_SHA = "4645cefc6dc4c227cf8bd8de20b7faad4c5ffbc45501f86fb0f5d6e6cef9cf70"
TARGETS = (
    ("codec_audit_terms", "ipfs_datasets_py.logic.modal.codec", "_frame_ontology_audit_terms"),
    ("flogic_frame_metadata", "ipfs_datasets_py.logic.flogic_optimizer", "_frame_ontology_metadata"),
)
DECOMPILER_PHASES = (
    ("decompiler_frame_ontology_phrases", "_frame_ontology_phrases"),
    ("decompiler_target_reconstruction_slots", "_typed_decompiler_target_reconstruction_slots"),
    ("decompiler_target_surface_profiles", "_typed_decompiler_target_surface_profiles"),
)
SELECTED_FUNCTIONS = frozenset({
    "normalize_frame_ontology_term", "_informative_ontology_tokens", "_is_informative_ontology_token",
    "frame_ontology_terms_from_feature_keys", "frame_ontology_terms_from_triples",
    "frame_ontology_contextualized_terms", "_contextualized_frame_ontology_term_from_feature",
    "_frame_ontology_value_from_feature", "_frame_ontology_coordinate_value",
    "_normalized_frame_ontology_predicate", "_normalized_frame_ontology_value",
    "_is_contextual_frame_ontology_predicate", "_canonical_frame_ontology_predicate",
    "_bounded_ontology_values", "_deduplicated_ontology_entries",
})


def stats_row(key, value):
    return {"file": key[0], "line": key[1], "function": key[2],
            "primitive_calls": value[0], "calls": value[1],
            "self_seconds": value[2], "cumulative_seconds": value[3]}


class TargetedProfiles:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.profiles = {name: cProfile.Profile() for name, _, _ in TARGETS}
        self.calls = []
        self.dropped_calls = 0
        self.active = None
        self.installed = False
        self.restored = False
        self.nested_enable_skips = 0
        self.external_profiler_skips = 0
        self.replacements = []
        self.observer = None

    def coarse_wrap(self, phase, original):
        @functools.wraps(original)
        def measured(*args, **kwargs):
            with self.observer.phase(phase, original.__name__):
                return original(*args, **kwargs)
        return measured

    def wrap(self, name, original):
        @functools.wraps(original)
        def measured(*args, **kwargs):
            if self.active is not None:
                self.nested_enable_skips += 1
                return original(*args, **kwargs)
            if sys.getprofile() is not None:
                self.external_profiler_skips += 1
                return original(*args, **kwargs)
            profile = self.profiles[name]
            raised_type = None
            started = time.perf_counter()
            try:
                self.active = name
                profile.enable()
                return original(*args, **kwargs)
            except BaseException as exc:
                raised_type = type(exc).__module__ + "." + type(exc).__qualname__
                raise
            finally:
                profile.disable()
                self.active = None
                elapsed = time.perf_counter() - started
                if len(self.calls) < 12:
                    self.calls.append({"profile": name, "sample_id": self.observer.sample_id,
                                       "profiled_wall_seconds": elapsed,
                                       "raised_exception_type": raised_type})
                else:
                    self.dropped_calls += 1
        return measured

    def install(self):
        if self.installed:
            return
        # These modules were loaded by the original adapter._codec call. The
        # modal profiler has already installed its coarse wrappers here.
        bindings = [(name, sys.modules[module], function) for name, module, function in TARGETS]
        decompiler = sys.modules["ipfs_datasets_py.logic.modal.decompiler"]
        for _, owner, function in bindings:
            if not callable(getattr(owner, function)):
                raise TypeError("targeted profile boundary is not callable: " + function)
        for _, function in DECOMPILER_PHASES:
            if not callable(getattr(decompiler, function)):
                raise TypeError("coarse decompiler boundary is not callable: " + function)
        for name, owner, function in bindings:
            original = getattr(owner, function)
            self.replacements.append((owner, function, original))
            setattr(owner, function, self.wrap(name, original))
        for phase, function in DECOMPILER_PHASES:
            original = getattr(decompiler, function)
            self.replacements.append((decompiler, function, original))
            setattr(decompiler, function, self.coarse_wrap(phase, original))
        self.installed = True

    def restore(self):
        for owner, function, original in reversed(self.replacements):
            setattr(owner, function, original)
        self.restored = True

    def save(self):
        result = {"targets": [dict(profile=name, module=module, function=function)
                              for name, module, function in TARGETS],
                  "additional_coarse_phases": [dict(phase=phase, function=function)
                                               for phase, function in DECOMPILER_PHASES],
                  "installed": self.installed, "restored": self.restored,
                  "nested_enable_skips": self.nested_enable_skips,
                  "external_profiler_skips": self.external_profiler_skips,
                  "calls": self.calls, "max_retained_calls": 12, "dropped_calls": self.dropped_calls,
                  "scope": "two independently accumulated profiles; nested calls never enable a second profiler",
                  "timing_scope": "cProfile attribution and profiled wall intervals only; unsuitable for native speed claims",
                  "profiles": {}}
        for name, profile in self.profiles.items():
            path = self.directory / (name + ".pstats")
            if path.exists():
                raise FileExistsError(path)
            profile.dump_stats(str(path))
            # Empty profiles are valid evidence when a timeout or preflight
            # rejection prevented this boundary from being reached.
            stats = profile.stats
            rows = [stats_row(key, value) for key, value in stats.items()]
            selected = [row for row in rows if row["function"] in SELECTED_FUNCTIONS
                        or (row["file"] == "~" and ("'findall'" in row["function"]
                                                     or "'finditer'" in row["function"]))]
            profiled_wall = sum(row["profiled_wall_seconds"] for row in self.calls if row["profile"] == name)
            normalization = sum(row["cumulative_seconds"] for row in rows
                                if row["function"] == "normalize_frame_ontology_term")
            result["profiles"][name] = {
                "artifact": {"path": str(path), "sha256": base.sha(path), "bytes": path.stat().st_size},
                "function_entry_count": len(rows),
                "profiled_wall_seconds": profiled_wall,
                "normalize_cumulative_seconds": normalization,
                "normalize_fraction_of_profiled_wall": normalization / profiled_wall if profiled_wall else None,
                "top_cumulative": sorted(rows, key=lambda row: row["cumulative_seconds"], reverse=True)[:100],
                "top_self": sorted(rows, key=lambda row: row["self_seconds"], reverse=True)[:60],
                "selected_function_stats": sorted(selected, key=lambda row: row["cumulative_seconds"], reverse=True),
            }
        return result


@contextmanager
def targeted_instrument(collector, observer):
    from ipfs_datasets_py.logic.bridge import modal_frame_logic

    collector.observer = observer
    adapter = modal_frame_logic.ModalFrameLogicBridgeAdapter
    original = adapter._codec

    @functools.wraps(original)
    def acquire(*args, **kwargs):
        codec = original(*args, **kwargs)
        collector.install()
        return codec

    try:
        adapter._codec = acquire
        yield
    finally:
        collector.restore()
        adapter._codec = original


@contextmanager
def extension():
    if base.sha(modal.__file__) != MODAL_SHA:
        raise ValueError("frozen modal profile harness changed")
    script_sha = base.sha(__file__)
    original_run, original_instrument = base.run, base.instrument
    original_phases = base.PHASES
    collector = None

    @contextmanager
    def instrument(observer):
        with original_instrument(observer), targeted_instrument(collector, observer):
            yield

    def run(args, result):
        nonlocal collector
        collector = TargetedProfiles(args.directory)
        try:
            original_run(args, result)
            if not collector.installed or not collector.restored:
                raise ValueError("targeted profiling boundaries did not install/restore")
            if collector.nested_enable_skips or collector.external_profiler_skips or collector.dropped_calls:
                raise ValueError("targeted profiling was incomplete; see explicit skip/drop counts")
            if base.sha(__file__) != script_sha:
                raise ValueError("targeted profile extension changed during diagnostic")
        finally:
            result["schema"] = "frame-ontology-targeted-profile-v1"
            result["cprofile_used"] = True
            result["targeted_profile_extension"] = {
                "path": str(Path(__file__).resolve()), "sha256": script_sha,
                "source_unchanged": base.sha(__file__) == script_sha,
                "modal_harness_sha256": MODAL_SHA, "cold_harness_sha256": modal.BASE_SHA,
                "source_files_edited": False,
                "timeout_scope": "unchanged original SIGALRM guard; profiled calls may exhaust its budget and produce partial bridge results",
            }
            result["targeted_profiles"] = collector.save()

    try:
        base.run, base.instrument = run, instrument
        base.PHASES = (*original_phases, *(phase for phase, _ in DECOMPILER_PHASES))
        yield
    finally:
        base.run, base.instrument = original_run, original_instrument
        base.PHASES = original_phases


def main():
    with modal.extension(True), extension():
        return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
