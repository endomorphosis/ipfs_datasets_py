"""Closed ordinary-byte checks for the synthetic4096 guard-workload archive.

The only executed repository helper is the CURRENT, externally pinned ordinary
reader. Retained Python, Torch, models, services, schedulers and native owners
are never imported. Successful consistency preserves a producer's synthetic
fixture status; it does not attest execution, confidence or production quality.
Failed archives have a separate partial-byte scope and remain unqualified.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import math
import os
from pathlib import Path
import random
import re
import stat
import statistics
import struct
import types

HELPER_SHA = "ebaa6b7765e1a5e87c39fe9f5f866221dee116e891f3217af8880ebdeda6952b"
PRODUCER_SHA = "8fa92ebd37c6d38fcd13b34e13034e9634a1cc6e104ff004e28f4af47a78003d"
SCHEMA = "native4096-synthetic-guard-workloads-qualification/v1"
PROFILE_VIEW_SCHEMA = "native4096-synthetic-bitwise-session-device-qualification/v2"
COUNTS = (8, 16, 32)
FAMILIES = ("short", "medium", "long")
CASE_IDS = tuple(f"{family}-rows{count}" for family in FAMILIES for count in COUNTS)
WIDTHS = {"short": 5, "medium": 13, "long": 25}
CPU_LABELS = ("cpu", "bitwise_cpu")
GPU_LABELS = ("cuda_batched", "bitwise_cuda_batched")
LABELS = (*CPU_LABELS, *GPU_LABELS)
PAIRS, CPU_SAMPLES, BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED = 12, 3, 1999, 1729
MAX_FILES, MAX_TOTAL_BYTES, MAX_FILE_BYTES = 512, 64 * 1024**2, 8 * 1024**2
EXPECTED_TIMED_RETURNS = 270
EXPECTED_FILES = 397
EXPECTED_CHECKPOINT_SHA = "04a8f2d317294861a7fcf9b6f156e915cd6c31bfa1482b8eaab4ecf15d00dee7"
EXPECTED_ANCHOR_SHA = "68113f39859dcf0ec17292ea5a2f172efc98064420de7afd983ad5ac4e5d5f1a"
EXPECTED_SOURCE_SHA = {
    "benchmark": PRODUCER_SHA,
    "configuration": "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575",
    "resources": "9cb9f263c5a72cd1b1fa2dd9dcd070a549e11bd5483937d35508c6a86d929166",
    "cuda_cleanup": "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c",
    "qualified_v2_helpers": "a2b85c0e05d9fc652e7e3d2fdb99b83407a511a3321fba3d2299c27e797ceb36",
    "qualified_quad_v2": "ddca40604bcd05f172e0ec28bfe13b3e4512a6113a481097ca21623f3cfe71c3",
    "device_session": "658382fb5b7bb30eb5e82a444b9ac9168b7557f5452a87a8ff59a5f883de55a8",
    "bitwise_device_session": "14678654b927d0b6910fda6a8c82961978a9e7ebc29334aaae6cb2320abc5dc3",
    "bitwise_primitive_candidate": "6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34",
}


def _load_checked_helper():
    """Execute only verified current ordinary-reader bytes, never an archive."""
    path = Path(__file__).absolute().with_name("audit_synthetic_4096_head_device.py")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= MAX_FILE_BYTES):
            raise ValueError("bounded current reader helper required")
        raw = bytearray()
        while len(raw) <= MAX_FILE_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                                  value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if (identity(before) != identity(after) or len(raw) != before.st_size
                or hashlib.sha256(raw).hexdigest() != HELPER_SHA):
            raise ValueError("current ordinary reader helper pin differs")
    finally:
        os.close(descriptor)
    module = types.ModuleType("checked_current_synthetic4096_ordinary_helpers")
    module.__file__ = str(path)
    exec(compile(bytes(raw), str(path), "exec"), module.__dict__)
    return module


base = _load_checked_helper()
AuditError = base.AuditError
_require, _integer, _number = base._require, base._integer, base._number
_wire, _digest, _sha, _json = base._wire, base._digest, base._sha, base._json


def _source_paths():
    paths = base._report_source_paths(PROFILE_VIEW_SCHEMA)
    paths["qualified_quad_v2"] = paths["benchmark"]
    paths["benchmark"] = paths["benchmark"].with_name("qualify_synthetic_4096_guard_workloads.py")
    return paths


def _allowed_names():
    names = {"result.json", "authored-workloads.json", "synthetic-inputs.json",
             "synthetic-untrained-checkpoint.json"}
    names.update("producers/" + role + "-" + path.name for role, path in _source_paths().items())
    for case in CASE_IDS:
        prefix = "workloads/" + case + "/"
        names.update(prefix + name for name in ("cpu-singleton-reference.json",
            "cpu-singleton-reference-canonical-projection.json", "cpu-singleton-reference-logits.json"))
        for label in LABELS:
            names.update(prefix + f"{label}-sample{index:02d}.json" for index in
                         range(PAIRS if label in GPU_LABELS else CPU_SAMPLES))
            names.add(prefix + label + "-logits.json")
            names.add(prefix + label + "-canonical-projections.json")
    return frozenset(names)


class _Reader(base._Reader):
    """Fixed nested paths opened relative to stable ordinary directory fds."""
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.fd = base._directory(self.root)
        self.root_identity = base._identity(os.fstat(self.fd))[:4]
        self.allowed = _allowed_names()
        self.pins, self.identities, self.cache = {}, {}, {}
        self.current_files, self.total = [], 0
        self.directory_identities, self.inventory = {}, {}
        try:
            self._inventory(self.fd, "")
        except BaseException:
            os.close(self.fd)
            raise

    def _inventory(self, descriptor, prefix):
        self.directory_identities[prefix] = base._identity(os.fstat(descriptor))
        permitted_dirs = {"producers", "workloads", *("workloads/" + case for case in CASE_IDS)}
        for leaf in sorted(os.listdir(descriptor)):
            _require(type(leaf) is str and leaf not in (".", "..") and "/" not in leaf,
                     "ordinary bounded inventory leaf required")
            name = prefix + "/" + leaf if prefix else leaf
            info = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                _require(name in permitted_dirs, "unlisted retained directory refused")
                child = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    _require(base._identity(os.fstat(child)) == base._identity(info), "directory changed during inventory")
                    self._inventory(child, name)
                finally:
                    os.close(child)
            else:
                _require(name in self.allowed, "unlisted retained path refused")
                _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                         and not info.st_mode & 0o222 and 0 < info.st_size <= MAX_FILE_BYTES,
                         "bounded immutable single-link ordinary retained file required")
                self.inventory[name] = base._identity(info)
                _require(len(self.inventory) <= MAX_FILES
                         and sum(identity[4] for identity in self.inventory.values()) <= MAX_TOTAL_BYTES,
                         "retained namespace count/byte bound exceeded")

    def _open(self, name):
        _require(name in self.allowed, "unlisted retained path refused")
        parts, descriptor = name.split("/"), os.dup(self.fd)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        finally:
            os.close(descriptor)

    def read(self, name, pin=None):
        raw = super().read(name, pin)
        _require(name in self.inventory and self.identities[name] == self.inventory[name],
                 "retained identity differs from closed initial inventory")
        return raw

    def final_check(self):
        super().final_check()
        inventory, directories = self.inventory, self.directory_identities
        self.inventory, self.directory_identities = {}, {}
        self._inventory(self.fd, "")
        _require(self.inventory == inventory and self.directory_identities == directories,
                 "retained namespace/directory identity changed after read")


def _source_join(reader, report, current):
    paths, joined = _source_paths(), {}
    pins = report["source_pins"]
    _require(type(pins) is list and len(pins) <= len(paths), "bounded source inventory required")
    for item in pins:
        _require(type(item) is dict and set(item) == {"role", "current", "retained_copy"}, "closed producer pin required")
        role = item["role"]
        _require(role in paths and role not in joined, "unknown/repeated producer role")
        path, expected = paths[role], item["current"]
        _require(type(expected) is dict and set(expected) == {"path", "bytes", "sha256"}
                 and expected["path"] == str(path), "fixed current producer path differs")
        raw = reader.read("producers/" + role + "-" + path.name, item["retained_copy"])
        _require(_integer(expected["bytes"], 1, MAX_FILE_BYTES) == len(raw)
                 and _sha(expected["sha256"]) == hashlib.sha256(raw).hexdigest(), "current/retained source pin bytes differ")
        if role in EXPECTED_SOURCE_SHA:
            _require(expected["sha256"] == EXPECTED_SOURCE_SHA[role], "qualified source pin differs: " + role)
        if current:
            reader.current(path, expected, raw)
        joined[role] = expected
    for role in ("benchmark", "configuration", "cuda_cleanup", "qualified_v2_helpers", "qualified_quad_v2"):
        if role in report:
            _require(role in joined and report[role] == joined[role], "top-level producer pin differs")
    return joined


def _authored_inputs():
    """Independently reproduce the fixed physical source/token/padding contract."""
    templates = {
        "short": "Worker{index:02d} {modal} retain books.",
        "medium": "Worker{index:02d} {modal} publish records after reviewers approve requests unless rules prohibit disclosure.",
        "long": "Worker{index:02d} {modal} retain accounting records under documented archive controls while authorized auditors review access policies before annual reporting deadlines unless approved exemptions apply today.",
    }
    result = []
    for family in FAMILIES:
        for count in COUNTS:
            texts = [templates[family].format(index=index, modal="must" if index % 2 == 0 else "may")
                     for index in range(count)]
            records = [[{"text": match.group(), "start": match.start(), "end": match.end(),
                         "byte_ids": [byte + 1 for byte in match.group().casefold().encode("utf-8")]}
                        for match in base._TOKEN.finditer(text)] for text in texts]
            width = WIDTHS[family]
            _require(all(len(tokens) == width for tokens in records), "fixed authored family width differs")
            byte_width = max(len(token["byte_ids"]) for tokens in records for token in tokens)
            _require(all(0 < len(text) <= 1024 and len(text.encode()) <= 4096 for text in texts)
                     and width <= 32 and byte_width <= 48, "physical source/token/byte contract exceeded")
            padded = count * width * byte_width
            result.append({"id": f"{family}-rows{count}", "family": family, "row_count": count,
                "texts": texts, "token_records": records, "shape_preflight": {
                    "source_characters": [len(text) for text in texts],
                    "source_utf8_bytes": [len(text.encode()) for text in texts],
                    "token_lengths": [width] * count, "equal_row_token_width": width,
                    "maximum_casefold_token_utf8_bytes": byte_width,
                    "padded_byte_id_elements": padded, "padded_byte_ids_int64_bytes": padded * 8,
                    "latent_float32_bytes": count * 4096 * 4,
                    "estimated_four_logit_float32_bytes": count * (3 + 8 + 12 * width) * 4,
                    "ragged_token_widths_tested": False, "truncation_permitted": False}})
    return result


def _profile_view(report):
    return {**report, "schema": PROFILE_VIEW_SCHEMA}


def _memory_bound(count, width, byte_width, checkpoint, digests):
    """Independent integer reconstruction of the qualified shape estimate."""
    parameters, checkpoint_bytes = digests["reference_bytes"], len(_wire(checkpoint))
    padded = count * width * byte_width
    embedding = padded * 4 * 4
    recurrent = count * width * 8 * 2 * 4 * 16
    output = count * (3 + 8 + 12 * width) * 4
    working = 128 * 1024**2 + parameters * 2 + padded * 8 + embedding * 3 + recurrent
    latent = count * 4096 * 4 * 3
    result = {"gpu_working_set_bytes": working + latent + parameters * 4,
              "host_working_set_bytes": working + output * 4 + checkpoint_bytes * 12 + latent + parameters * 6}
    _require(result["gpu_working_set_bytes"] <= 256 * 1024**2
             and result["host_working_set_bytes"] <= 1024 * 1024**2, "complete workload exceeds child shape reservation")
    return result


def _forward(observation, count, width, profile, device):
    _require(_integer(observation["rows"]) == count and observation["source_tokens"] == [width] * count
             and observation["input_device"] == device and _integer(observation["native_input_dimension"]) == 4096
             and observation["output_devices"] == {name: device for name in base.OUTPUTS}
             and observation["output_dtype"] == "float32" and observation["gru_executed"] is True,
             "reported forward width/device/row coverage differs")
    base._precision(profile, observation, device)


def _logits(reference, actual, count, width):
    _require(type(reference) is dict and type(actual) is dict and set(reference) == set(actual) == base.OUTPUTS,
             "complete four-logit arrays required")
    errors = {}
    for name in sorted(base.OUTPUTS):
        shape, values = base._shapes(reference[name])
        actual_shape, others = base._shapes(actual[name])
        expected = (count, 3) if name == "modality" else (count, 4, 2) if name == "presence" else (count, 6, width)
        _require(shape == actual_shape == expected and all(type(value) is float and base._float32(value) == value
                  for value in values + others), "complete exact-float32 logit width/shape differs")
        error = max(abs(base._float32(left - right)) for left, right in zip(values, others))
        _require(error <= 5e-5, "four-logit CPU/private parity exceeds5e-5")
        errors[name] = error
    return errors


def _ratio_analysis(pairs):
    """Recompute deterministic descriptive statistics without producer code."""
    _require(type(pairs) is list and len(pairs) == PAIRS, "twelve complete CUDA pairs required")
    ratios = []
    for item in pairs:
        _require(type(item["seconds"]) is dict and set(item["seconds"]) == set(GPU_LABELS), "exact CUDA timing labels required")
        seconds = [_number(item["seconds"][label]) for label in GPU_LABELS]
        _require(all(value > 0 for value in seconds), "positive completed pair times required")
        ratios.append(seconds[0] / seconds[1])
    _require(all(math.isfinite(value) and value > 0 for value in ratios), "positive finite paired ratios required")
    groups = {first: [ratio for item, ratio in zip(pairs, ratios) if item["completed_call_order"][0] == first]
              for first in GPU_LABELS}
    _require(all(len(group) == 6 for group in groups.values()), "balanced six-first order groups required")
    medians = {first: statistics.median(group) for first, group in groups.items()}
    rng = random.Random(BOOTSTRAP_SEED)
    logs = [math.log(ratio) for ratio in ratios]
    bootstrapped = sorted(math.exp(statistics.median([logs[rng.randrange(PAIRS)] for _ in range(PAIRS)]))
                          for _ in range(BOOTSTRAP_RESAMPLES))
    interval = [bootstrapped[math.floor(fraction * (BOOTSTRAP_RESAMPLES - 1))] for fraction in (0.025, 0.975)]
    minimum, maximum, median = min(ratios), max(ratios), statistics.median(ratios)
    gain = minimum > 1.02 and median > 1.05 and all(value > 1.02 for value in medians.values()) and interval[0] > 1.02
    return {"profile_id": "paired-observed-range-sign-median-interval/v1",
        "ratio": "original_v2_completed_cuda_seconds / bitwise_v2_completed_cuda_seconds",
        "paired_ratios": ratios, "paired_ratio_median": median, "paired_ratio_observed_range": [minimum, maximum],
        "order_first_group_medians": medians, "population_median_interval": [minimum, maximum],
        "nominal_iid_continuous_median_coverage": 1.0 - 2.0 ** (1 - PAIRS),
        "nominal_iid_family_union_bound_coverage": 1.0 - len(CASE_IDS) * 2.0 ** (1 - PAIRS),
        "nominal_coverage_assumptions": "independent identically distributed continuous paired ratios with stationary workload/hardware",
        "nominal_coverage_assumptions_established": False,
        "unconditional_confidence_or_future_repeatability_claimed": False,
        "empirical_gain_rule": {"all_pair_ratios_strictly_above": 1.02, "paired_ratio_median_strictly_above": 1.05,
            "both_first_order_group_medians_strictly_above": 1.02, "all_nine_workloads_required_for_suite_claim": True},
        "bootstrap": {"profile_id": "descriptive-seeded-paired-log-ratio-median-bootstrap/v1",
            "seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES,
            "statistic": "exp(median(resampled log paired original_cuda / bitwise_cuda ratios))",
            "quantile": "sorted value at floor(p * (1999 - 1)); p=0.025,0.975",
            "descriptive_percentile_95_interval": interval, "draw_unit": "entire adjacent completed-call pair",
            "serial_autocorrelation_stationarity_or_independence_established": False,
            "simultaneous_family_or_future_repeatability_confidence_claimed": False,
            "descriptive_interval_above_1_02": interval[0] > 1.02},
        "conservative_empirical_gain_observed": gain}


def _session_controls(report, checkpoint, digests, sources):
    _require(type(report["lanes"]) is dict and set(report["lanes"]) == set(LABELS), "exact four session lanes required")
    for label, lane in report["lanes"].items():
        for field in ("profile", "final_profile"):
            base._profile(lane[field], label, _profile_view(report), checkpoint, digests, sources)
        _require(lane["own_child_lease_released"] is True and _number(lane["constructor_seconds"]) > 0,
                 "session constructor/child cleanup differs")
        controls = lane["paired_reference_corruption_refusals"]
        expected = ("paired_finite_value", "paired_signed_zero", "anchor_object_replacement")
        _require(type(controls) is list and [item["corruption"] for item in controls] == list(expected),
                 "complete paired reference/anchor controls required")
        for item in controls:
            reason = "immutable reference byte anchor changed" if item["corruption"] == expected[2] else "reference bytes changed from admitted checkpoint"
            _require(item["refused"] is True and item["entry_refused_before_forward"] is True
                     and reason in item["refusal"], "session paired/reference corruption not refused at entry")
        control = lane["model_only_subnormal_control"]
        _require(control["corruption"] == "model_only_smallest_positive_float32_subnormal"
                 and _integer(control["actual_float32_bits_int32"]) == 1
                 and control["refused"] is True and control["entry_refused_before_forward"] is True
                 and "owned tensor values, signed zeros or finite profile changed" in control["refusal"],
                 "session model-only subnormal guard refusal differs")


def _workloads(reader, report, rows, checkpoint, digests, sources):
    expected_inputs = _authored_inputs()
    _require(reader.json("authored-workloads.json", report["workload_inputs"]) == expected_inputs,
             "exact authored workload source/token/padding bytes differ")
    cases = report["workloads"]
    _require(type(cases) is list and [case["id"] for case in cases] == list(CASE_IDS), "exact nine workload case order required")
    all_errors, gains, total = {}, [], 0
    for position, (case, inputs) in enumerate(zip(cases, expected_inputs)):
        count, width, prefix = inputs["row_count"], WIDTHS[inputs["family"]], "workloads/" + inputs["id"] + "/"
        _require(case["family"] == inputs["family"] and _integer(case["row_count"]) == count
                 and case["shape_preflight"] == inputs["shape_preflight"] and case["fixture_qualified"] is True
                 and case["paired_measurement_complete"] is True
                 and type(case["lanes"]) is dict and set(case["lanes"]) == set(LABELS), "workload shape/completion/lane coverage differs")
        authored_rows = [{"source_text": text, "latent": row["latent"]} for text, row in zip(inputs["texts"], rows[:count])]
        reference = reader.json(prefix + "cpu-singleton-reference.json", case["cpu_reference_result"])
        _require(reference["schema"] == "native-4096-source-span-inference/v1"
                 and reference["synthetic_architecture_control"] is True, "CPU singleton reference schema/scope differs")
        expected_projection = base._decisions(reference, authored_rows, checkpoint, digests)
        projection = reader.json(prefix + "cpu-singleton-reference-canonical-projection.json", case["cpu_reference_decision_projection"])
        _require(projection == expected_projection, "CPU reference projection differs from raw public decisions")
        reference_logits = reader.json(prefix + "cpu-singleton-reference-logits.json", case["cpu_reference_logits"])
        _logits(reference_logits, reference_logits, count, width)
        case_medians, samples_by_lane = {}, {}
        for label, lane in case["lanes"].items():
            sample_count = PAIRS if label in GPU_LABELS else CPU_SAMPLES
            samples = lane["samples"]
            _require(type(samples) is list and len(samples) == sample_count, "complete timed sample coverage required")
            bundle = reader.json(prefix + label + "-canonical-projections.json", lane["canonical_projection_bundle"])
            _require(type(bundle) is list and len(bundle) == sample_count, "complete canonical projection bundle required")
            times = []
            for index, (entry, joined_projection) in enumerate(zip(samples, bundle)):
                _require(_integer(entry["sample_index"]) == index and entry["canonical_rows_match_cpu"] is True
                         and entry["public_profile_checked"] is True
                         and entry["canonical_projection_profile_id"] == "native4096-exact-decisions-separate-numeric-diagnostics/v1",
                         "timed sample index/decision/profile join differs")
                seconds = _number(entry["seconds_per_completed_public_call"])
                _require(seconds > 0, "positive completed public timing required")
                times.append(seconds)
                actual = reader.json(prefix + f"{label}-sample{index:02d}.json", entry["result"])
                _require(actual["schema"] == "native-4096-source-span-device-inference/v1"
                         and actual["synthetic_embeddings"] is True, "timed public schema/synthetic scope differs")
                actual_projection = base._decisions(actual, authored_rows, checkpoint, digests)
                _require(actual_projection == expected_projection, "timed public decisions differ from CPU singleton reference")
                _require(type(joined_projection) is dict and set(joined_projection) == {"sample_index", "canonical_projection"}
                         and _integer(joined_projection["sample_index"]) == index
                         and joined_projection["canonical_projection"] == actual_projection,
                         "retained projection bundle differs from timed raw return")
                projection_pin = entry["canonical_projection"]
                _require(type(projection_pin) is dict and set(projection_pin) == {"bytes", "sha256", "bundle_index"}
                         and _integer(projection_pin["bundle_index"]) == index
                         and _integer(projection_pin["bytes"]) == len(_wire(actual_projection))
                         and _sha(projection_pin["sha256"]) == _digest(actual_projection), "per-sample canonical projection byte pin differs")
                profile = actual["execution_profile"]
                device = base._profile(profile, label, _profile_view(report), checkpoint, digests, sources)
                optimized = label in GPU_LABELS
                expected_bound = _memory_bound(count if optimized else 1, width,
                    inputs["shape_preflight"]["maximum_casefold_token_utf8_bytes"], checkpoint, digests)
                _require(actual["batch_memory_bound"] == expected_bound, "timed public preallocation memory estimate differs")
                _require(actual["cuda_executed"] is optimized and actual["numerical_batching"] is optimized
                         and _integer(actual["valid_source_count"]) == count
                         and _integer(actual["device_to_cpu_head_transfers"]) == (4 if optimized else 0)
                         and _integer(actual["cpu_head_output_materializations"]) == (4 if optimized else 0),
                         "timed actual execution/transfer/batching profile differs")
                observations = actual["actual_forward_batches"]
                _require(type(observations) is list and len(observations) == (1 if optimized else count),
                         "timed full public forward coverage differs")
                for observation in observations:
                    _forward(observation, count if optimized else 1, width, profile, device)
            _require(lane["samples_seconds_per_call"] == times, "raw sample timing list differs")
            case_medians[label] = base._timing(lane, 1, sample_count)
            samples_by_lane[label] = samples
            numeric = reader.json(prefix + label + "-logits.json", lane["logits"])
            errors = _logits(reference_logits, numeric, count, width)
            _require(lane["four_logit_max_abs_errors"] == errors, "reported four-logit max errors differ from retained arrays")
            all_errors[inputs["id"] + "/" + label] = errors
            scope = lane["numeric_scope"]
            _require(scope["scope"] == "benchmark_only_checked_private_forward"
                     and scope["entry_and_exit_owned_session_checks"] is True
                     and scope["public_cpu_opt_out_still_uses_singletons"] is True
                     and type(scope["observations"]) is list and len(scope["observations"]) == 1,
                     "numeric replay guarded scope differs")
            _require(scope["batch_memory_bound"] == _memory_bound(count, width,
                     inputs["shape_preflight"]["maximum_casefold_token_utf8_bytes"], checkpoint, digests),
                     "numeric replay preallocation memory bound differs")
            device = base._profile(report["lanes"][label]["profile"], label, _profile_view(report), checkpoint, digests, sources)
            _forward(scope["observations"][0], count, width, report["lanes"][label]["profile"], device)
            total += len(samples)
        pairs = case["cuda_pairs"]
        _require(type(pairs) is list and len(pairs) == PAIRS, "twelve paired observations required")
        for index, pair in enumerate(pairs):
            expected_order = list(GPU_LABELS[::-1] if (bool(index % 2) != bool(position % 2)) else GPU_LABELS)
            _require(_integer(pair["pair_index"]) == index and pair["completed_call_order"] == expected_order
                     and set(pair["sample_results"]) == set(GPU_LABELS), "exact balanced alternating call order differs")
            for label in GPU_LABELS:
                sample = samples_by_lane[label][index]
                _require(pair["seconds"][label] == sample["seconds_per_completed_public_call"]
                         and pair["sample_results"][label] == sample["result"], "paired observation raw timing/return pin differs")
        analysis = _ratio_analysis(pairs)
        _require(case["paired_ratio_analysis"] == analysis, "reported bootstrap/interval/conservative statistics differ")
        if analysis["conservative_empirical_gain_observed"]:
            gains.append(inputs["id"])
        for name, left, right in (("full_session_speedup_original_cuda_over_bitwise_cuda", GPU_LABELS[0], GPU_LABELS[1]),
                ("full_session_speedup_original_cpu_over_bitwise_cpu", CPU_LABELS[0], CPU_LABELS[1]),
                ("original_cpu_over_original_cuda", CPU_LABELS[0], GPU_LABELS[0])):
            base._ratio(case[name], case_medians[left], case_medians[right])
        _require(report["full_session_speedups_v2_cuda_over_bitwise_cuda"][inputs["id"]]
                 == case["full_session_speedup_original_cuda_over_bitwise_cuda"], "top-level complete-call ratio differs")
    _require(total == EXPECTED_TIMED_RETURNS == _integer(report["timed_return_count"])
             == _integer(report["expected_timed_return_count"]), "all270 timed returns required")
    _require(report["workloads_with_conservative_empirical_gain"] == gains
             and report["suite_empirical_gain_criteria_met"] is (len(gains) == len(CASE_IDS))
             and report["conservative_complete_call_gain_observed"] is (len(gains) == len(CASE_IDS)),
             "empirical complete-call gain claim differs from raw paired timings")
    return {"timed_returns_checked": total, "head_logit_max_abs_errors": all_errors,
            "workloads_with_conservative_empirical_gain": gains,
            "conservative_complete_call_gain_observed": len(gains) == len(CASE_IDS)}


def _partial(reader, report):
    _require(report["architecture_fixture_qualified"] is False
             and report["conservative_complete_call_gain_observed"] is False
             and (report.get("error") is not None or report.get("qualification_refusals")),
             "failed partial archive cannot claim fixture/gain qualification")
    for name in reader.inventory:
        raw = reader.read(name)
        if name.endswith(".json") and not name.startswith("producers/"):
            base._false_authority(_json(raw))
    # Every reported ordinary pin must join the same closed inventory even in
    # failed scope. Per-projection content pins are not file paths.
    pending = [report]
    while pending:
        value = pending.pop()
        if type(value) is dict:
            if set(value) == {"path", "bytes", "sha256"}:
                path = Path(value["path"])
                if path.is_relative_to(reader.root):
                    reader.read(path.relative_to(reader.root).as_posix(), value)
                else:
                    _require(any(value == pin["current"] for pin in report["source_pins"]),
                             "failed report contains unlisted external pin")
            else:
                pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)
    return {"numeric_report_checked": False, "failed_run_remains_unqualified": True,
            "partial_byte_consistency_only": True, **base._cleanup(report, positive=False)}


def _audit(reader, report, current):
    _require(type(report) is dict and report["schema"] == SCHEMA, "explicit guard-workload schema required")
    positive = report["architecture_fixture_qualified"]
    _require(type(positive) is bool and type(report["head_numerical_fixture_qualified"]) is bool
             and report["optional_bitwise_primitive_enabled"] is True
             and report["bitwise_full_session_fixture_qualified"] is positive
             and report["complete_gpu_session_speedups_qualified"] is positive
             and type(report["conservative_complete_call_gain_observed"]) is bool,
             "plain consistent synthetic fixture/timing qualification flags required")
    base._false_authority(report)
    _require(report["selected_product_route_changed"] is False and report["future_repeatability_claimed"] is False,
             "ordinary archive cannot promote product or claim future repeatability")
    sources = _source_join(reader, report, current)
    if not positive:
        checks = _partial(reader, report)
        reader.final_check()
        return {"retained_source_count": len(sources), **checks}
    _require(set(sources) == set(_source_paths()), "complete24 source inventory required")
    _require(report["error"] is None and report["head_numerical_fixture_qualified"] is True
             and not report.get("qualification_refusals") and report["source_bytes_unchanged"] is True
             and report["checkpoint_unchanged"] is True and report["adam_unchanged"] is True
             and all(_integer(report[key]) == 0 for key in ("encoder_calls", "optimizer_steps", "training_calls", "optimizer_construction_attempts"))
             and report["foreign_process_actions"] is False and report["persistent_precision_policy_mutated"] is False,
             "fixture immutability/no-fit/no-native scope differs")
    _require(report["cpu_reference_numeric_profile"] == {"device": "cpu", "dtype": "float32",
        "numeric_batching": "actual_singleton_forwards_concatenated",
        "equal_fixture_token_width_required_per_workload": True, "used_for_four_logit_parity": True}
        and report["all_timed_return_bytes_and_projections_retained"] is True
        and report["binding_check_optimization_does_not_remove_original_boundaries"] is True,
        "CPU reference/complete-return/source-boundary scope differs")
    _require(report["admission_timeout_seconds"] == _integer(report["admission_timeout_seconds"], 1, 60)
             and report["workload_budget_seconds"] == 120 and report["admitted_work_budget_completed"] is True
             and 0 < _number(report["admitted_work_seconds_before_cleanup"]) < 120
             and report["work_budget_started_after_root_admission"] is True,
             "reported admission/workload budget differs")
    _require(report["precision_policy_before"] == report["precision_policy_after"]
             and report["precision_policy_before"]["cuda_matmul_allow_tf32"] is False
             and report["precision_policy_before"]["float32_matmul_precision"] == "highest",
             "persistent precision policy differs")
    _require(report["actual_initial_cuda_kernel"] is True and report["initial_cuda_kernel_output"] == [4.0]
             and report["gpu_allocated_after_producer_imports_bytes"] == 0
             and report["producer_imports_preserved_zero_cuda_allocation"] is True
             and report["all_workload_shape_preflights_match_producer_before_first_cuda_tensor"] is True,
             "zero-allocation import/physical preflight profile differs")
    for item in report["module_import_context_diagnostics"]:
        _require(_integer(item["gpu_allocated_before_bytes"]) == _integer(item["gpu_allocated_after_bytes"]) == 0,
                 "reported import allocated CUDA tensors")
    admission = report["admission"]
    _require(admission["owner_pid"] == report["pid"] and admission["parent_lease_id"] is None
             and admission["requires_gpu"] is True and _integer(admission["memory_mb"]) == 2048
             and _integer(admission["gpu_memory_mb"]) == 512 and _integer(admission["unified_memory_mb"]) == 2560,
             "reported root admission envelope differs")
    pair_profile = report["cuda_pair_timing_profile"]
    _require(report["paired_observations_per_workload"] == PAIRS and report["cpu_observations_per_workload"] == CPU_SAMPLES
             and pair_profile["sample_count_per_lane_per_workload"] == PAIRS
             and pair_profile["each_lane_first_per_workload"] == 6 and pair_profile["native_forwards_overlap"] is False
             and pair_profile["source_guard_or_anchor_boundary_removed"] is False
             and pair_profile["all_timed_returns_retained_before_comparison"] is True
             and pair_profile["serialization_outside_measured_call"] is True
             and pair_profile["warmup_calls_per_lane_per_workload"] == 1,
             "complete serial paired timing/warmup/retention scope differs")
    rows, checkpoint, digests = base._fixture(reader, report, sources)
    _require(digests["checkpoint_sha256"] == EXPECTED_CHECKPOINT_SHA
             and digests["anchor_sha256"] == EXPECTED_ANCHOR_SHA,
             "qualified checkpoint/independent reference anchor bytes differ")
    _session_controls(report, checkpoint, digests, sources)
    checks = _workloads(reader, report, rows, checkpoint, digests, sources)
    checks["guard_lane_integrity"] = base._guard(_profile_view(report), sources)
    checks.update(base._cleanup(report, positive=True))
    checks.update(numeric_report_checked=True, failed_run_remains_unqualified=False,
                  retained_source_count=len(sources), independent_checkpoint_reference_anchor_sha256=digests["anchor_sha256"])
    _require(set(reader.inventory) == set(reader.allowed) == set(reader.pins)
             and len(reader.inventory) == EXPECTED_FILES, "closed complete397-file namespace coverage required")
    _require(report["retained_namespace_within_bounds_before_result"] is True
             and _integer(report["retained_file_count_before_result"]) == EXPECTED_FILES - 1
             and _integer(report["retained_total_bytes_before_result"])
                 == sum(identity[4] for name, identity in reader.inventory.items() if name != "result.json"),
             "reported retained namespace byte/count bound differs")
    reader.final_check()
    return checks


def audit(root, *, expected_result_sha256, check_current_sources=False):
    result = {"schema": "synthetic4096-guard-workloads-closed-audit/v1", "qualified": False,
        "closed_artifacts_consistent": False, "native_execution_attested": False,
        "native_leanstral_outputs_qualified": False, "production_qualified": False,
        "proof_authority": False, "resource_enforcement_attested": False,
        "future_repeatability_attested": False, "conservative_complete_call_gain_observed": False,
        "scope": "ordinary_retained_bytes_and_report_consistency",
        "check_current_sources": check_current_sources, "retained_pins": [], "current_source_pins": [], "error": None}
    reader = None
    try:
        _sha(expected_result_sha256)
        _require(type(check_current_sources) is bool, "current-source option must be a plain boolean")
        reader = _Reader(root)
        raw = reader.read("result.json")
        _require(reader.pins["result.json"]["sha256"] == expected_result_sha256, "external result SHA256 differs")
        report = _json(raw)
        _require(type(report) is dict, "plain producer report required")
        result["producer_architecture_fixture_qualified"] = report.get("architecture_fixture_qualified")
        result["producer_error"] = report.get("error")
        result["checks"] = _audit(reader, report, check_current_sources)
        result["qualified"] = report["architecture_fixture_qualified"]
        result["closed_artifacts_consistent"] = True
        result["conservative_complete_call_gain_observed"] = result["checks"].get("conservative_complete_call_gain_observed", False)
        result["scope"] = ("ordinary_retained_bytes_and_report_consistency" if result["qualified"]
                           else "failed_partial_archive_ordinary_byte_consistency_only")
        result["current_source_pins"] = [item[2] for item in reader.current_files]
    except (AuditError, OSError, ValueError, KeyError, TypeError, AttributeError, IndexError,
            RecursionError, OverflowError, struct.error) as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if reader is not None:
            result["retained_pins"] = list(reader.pins.values())
            reader.close()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-result-sha256", required=True)
    parser.add_argument("--check-current-sources", action="store_true")
    args = parser.parse_args(argv)
    value = audit(args.root, expected_result_sha256=args.expected_result_sha256,
                  check_current_sources=args.check_current_sources)
    print(_wire(value).decode())
    return 0 if value["closed_artifacts_consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
