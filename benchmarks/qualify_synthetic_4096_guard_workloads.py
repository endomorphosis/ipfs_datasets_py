"""Bounded repeated full-session guard comparison over authored source workloads.

Nine equal-width source workloads vary token width and row counts 8/16/32.
Every measured public return and decision projection is retained, including
failed comparisons. Original and bitwise-v2 CUDA calls alternate serial order,
12 paired observations per workload. The empirical acceptance rule requires
all paired ratios >1.02, median >1.05 and bootstrap lower endpoint >1.02
in every workload. The 1999-resample seeded bootstrap is descriptive and does
not establish independence or repeatability. The observed-range
median interval has a nominal sign-distribution interpretation only under IID
continuous pairs, assumptions not established by serial worker timings.

A fresh finite process preserves the shared scheduler/configuration and obtains
root admission before numerical work. No fits, native Leanstral encoder, service
reuse, production/proof authority, or trained latent-conditioning claim occurs.
The 120-second admitted-work limit is cooperative; safe cleanup can exceed it.
Ordinary readers must inspect pinned bytes without importing this producer or
Torch; this new schema does not extend the older qualified reader's authority.
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
import re
import random
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
COUNTS = (8, 16, 32)
PAIRED_OBSERVATIONS = 12
CPU_OBSERVATIONS = 3
WORKLOAD_BUDGET_SECONDS = 120
QUALIFIED_QUAD_SHA = "ddca40604bcd05f172e0ec28bfe13b3e4512a6113a481097ca21623f3cfe71c3"
SCHEDULER_SHA = "9cb9f263c5a72cd1b1fa2dd9dcd070a549e11bd5483937d35508c6a86d929166"
MAX_SOURCE_CHARACTERS = 1024
MAX_SOURCE_TOKENS = 32
MAX_TOKEN_BYTES = 48
MAX_RETAINED_FILES = 512
MAX_RETAINED_TOTAL_BYTES = 64 * 1024**2
BOOTSTRAP_RESAMPLES = 1999
BOOTSTRAP_SEED = 1729
GPU_LABELS = ("cuda_batched", "bitwise_cuda_batched")
CPU_LABELS = ("cpu", "bitwise_cpu")
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
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

def _authored_workloads():
    """Bound all physical source/vector/padding shapes before root admission."""
    forms = {
        "short": "Worker{index:02d} {modal} retain books.",
        "medium": "Worker{index:02d} {modal} publish records after reviewers approve requests unless rules prohibit disclosure.",
        "long": "Worker{index:02d} {modal} retain accounting records under documented archive controls while authorized auditors review access policies before annual reporting deadlines unless approved exemptions apply today.",
    }
    workloads = []
    for family, form in forms.items():
        texts = [form.format(index=index, modal="must" if index % 2 == 0 else "may")
                 for index in range(max(COUNTS))]
        token_records = []
        for source in texts:
            if (not 0 < len(source) <= MAX_SOURCE_CHARACTERS
                    or len(source.encode("utf-8")) > 4096):
                raise ValueError("authored workload source character/physical byte limit exceeded")
            tokens = [{"text": match.group(), "start": match.start(), "end": match.end(),
                       "byte_ids": [byte + 1 for byte in match.group().casefold().encode("utf-8")]}
                      for match in _TOKEN_RE.finditer(source)]
            if (not 0 < len(tokens) <= MAX_SOURCE_TOKENS
                    or any(not 0 < len(token["byte_ids"]) <= MAX_TOKEN_BYTES for token in tokens)):
                raise ValueError("authored workload token/byte bound exceeded")
            token_records.append(tokens)
        widths = {len(tokens) for tokens in token_records}
        if len(widths) != 1:
            raise ValueError("equal row token widths required for pinned CPU singleton numeric reference")
        for count in COUNTS:
            width = next(iter(widths))
            byte_width = max(len(token["byte_ids"]) for row in token_records[:count] for token in row)
            padded = count * width * byte_width
            if padded > max(COUNTS) * MAX_SOURCE_TOKENS * MAX_TOKEN_BYTES:
                raise ValueError("complete authored workload padding exceeds preflight bound")
            workloads.append({"id": f"{family}-rows{count}", "family": family,
                "row_count": count, "texts": texts[:count], "token_records": token_records[:count],
                "shape_preflight": {"source_characters": [len(source) for source in texts[:count]],
                    "source_utf8_bytes": [len(source.encode("utf-8")) for source in texts[:count]],
                    "token_lengths": [len(row) for row in token_records[:count]],
                    "equal_row_token_width": width, "maximum_casefold_token_utf8_bytes": byte_width,
                    "padded_byte_id_elements": padded, "padded_byte_ids_int64_bytes": padded * 8,
                    "latent_float32_bytes": count * 4096 * 4,
                    "estimated_four_logit_float32_bytes": count * (3 + 8 + 12 * width) * 4,
                    "ragged_token_widths_tested": False, "truncation_permitted": False}})
    if len(workloads) != 9 or len({case["id"] for case in workloads}) != 9:
        raise ValueError("exactly nine distinct bounded authored workloads required")
    return workloads


def _paired_ratio_analysis(pairs, workload_count):
    """Observed range plus conservative sign-distribution median interval.

    For n independent continuous draws, a population median lies between the
    sample minimum and maximum with probability 1-2**(1-n). A union bound over
    nine workloads gives the stated nominal family coverage. Serial hardware
    timings do not establish independence/stationarity; no unconditional
    coverage or future-hardware speedup is claimed. The acceptance rule uses
    actual minimum/median/order-group ratios, never a nominal confidence label.
    """
    if len(pairs) != PAIRED_OBSERVATIONS:
        raise ValueError("exact paired observation count required")
    ratios = [pair["seconds"][GPU_LABELS[0]] / pair["seconds"][GPU_LABELS[1]] for pair in pairs]
    if any(not math.isfinite(ratio) or ratio <= 0 for ratio in ratios):
        raise ValueError("positive finite paired ratios required")
    groups = {first: [ratio for pair, ratio in zip(pairs, ratios)
                     if pair["completed_call_order"][0] == first] for first in GPU_LABELS}
    if any(len(group) != PAIRED_OBSERVATIONS // 2 for group in groups.values()):
        raise ValueError("balanced alternating paired call order required")
    group_medians = {first: statistics.median(group) for first, group in groups.items()}
    minimum, maximum, median = min(ratios), max(ratios), statistics.median(ratios)
    gain = (minimum > 1.02 and median > 1.05 and all(value > 1.02 for value in group_medians.values()))
    nominal_tail = 2.0 ** (1 - len(ratios))
    rng = random.Random(BOOTSTRAP_SEED)
    log_ratios = [math.log(ratio) for ratio in ratios]
    resampled = sorted(math.exp(statistics.median(
        [log_ratios[rng.randrange(len(log_ratios))] for _ in log_ratios]))
        for _ in range(BOOTSTRAP_RESAMPLES))
    # Nearest lower order statistics at p*(B-1), explicitly deterministic.
    bootstrap_interval = [resampled[math.floor(fraction * (BOOTSTRAP_RESAMPLES - 1))]
                          for fraction in (0.025, 0.975)]
    return {"profile_id": "paired-observed-range-sign-median-interval/v1",
        "ratio": "original_v2_completed_cuda_seconds / bitwise_v2_completed_cuda_seconds",
        "paired_ratios": ratios, "paired_ratio_median": median,
        "paired_ratio_observed_range": [minimum, maximum],
        "order_first_group_medians": group_medians,
        "population_median_interval": [minimum, maximum],
        "nominal_iid_continuous_median_coverage": 1.0 - nominal_tail,
        "nominal_iid_family_union_bound_coverage": max(0.0, 1.0 - workload_count * nominal_tail),
        "nominal_coverage_assumptions": "independent identically distributed continuous paired ratios with stationary workload/hardware",
        "nominal_coverage_assumptions_established": False,
        "unconditional_confidence_or_future_repeatability_claimed": False,
        "empirical_gain_rule": {"all_pair_ratios_strictly_above": 1.02,
            "paired_ratio_median_strictly_above": 1.05,
            "both_first_order_group_medians_strictly_above": 1.02,
            "all_nine_workloads_required_for_suite_claim": True},
        "bootstrap": {"profile_id": "descriptive-seeded-paired-log-ratio-median-bootstrap/v1",
            "seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES,
            "statistic": "exp(median(resampled log paired original_cuda / bitwise_cuda ratios))",
            "quantile": "sorted value at floor(p * (1999 - 1)); p=0.025,0.975",
            "descriptive_percentile_95_interval": bootstrap_interval,
            "draw_unit": "entire adjacent completed-call pair",
            "serial_autocorrelation_stationarity_or_independence_established": False,
            "simultaneous_family_or_future_repeatability_confidence_claimed": False,
            "descriptive_interval_above_1_02": bootstrap_interval[0] > 1.02},
        "conservative_empirical_gain_observed": gain and bootstrap_interval[0] > 1.02}


def _retain_sample(helpers, output, case_result, label, index, actual, elapsed):
    """Save the entire timed return before testing canonical bytes/profile."""
    directory = output / "workloads" / case_result["id"]
    prefix = f"{label}-sample{index:02d}"
    entry = {"sample_index": index, "seconds_per_completed_public_call": elapsed,
        "result": _write(directory / (prefix + ".json"), actual),
        "canonical_rows_match_cpu": False, "public_profile_checked": False,
        "canonical_projection_profile_id": CANONICAL_PROJECTION_PROFILE}
    case_result["lanes"][label]["samples"].append(entry)
    projection = helpers._decision_projection(actual)
    projection_bytes = _wire(projection)
    entry["canonical_projection"] = {"bytes": len(projection_bytes),
        "sha256": hashlib.sha256(projection_bytes).hexdigest(), "bundle_index": index}
    case_result["lanes"][label].setdefault("_pending_projections", []).append(
        {"sample_index": index, "canonical_projection": projection})
    expected = case_result["cpu_reference_decision_projection"]
    if ((entry["canonical_projection"]["sha256"], entry["canonical_projection"]["bytes"])
            != (expected["sha256"], expected["bytes"])):
        raise ValueError("timed public decisions differ from CPU singleton reference: " + case_result["id"] + "/" + label)
    entry["canonical_rows_match_cpu"] = True
    optimized, bitwise = label in GPU_LABELS, label.startswith("bitwise_")
    profile = actual["execution_profile"]
    expected_profile = BITWISE_SESSION_PROFILE if bitwise and optimized else SESSION_PROFILE
    expected_mode = ("cuda_bitwise_single_host_decision" if bitwise and optimized else
                     "cuda_single_host_decision" if optimized else "cpu_reference_checks")
    if (actual["cuda_executed"] is not optimized or profile["profile_id"] != expected_profile
            or profile["owned_tensor_currentness"]["mode"] != expected_mode
            or (bitwise and profile.get("session_profile_id") != BITWISE_SESSION_PROFILE)):
        raise ValueError("actual timed CPU/CUDA/private session profile differs")
    anchor = profile["reference_byte_currentness"]
    if (anchor["origin"] != "independently_restored_validated_cpu_checkpoint_model"
            or anchor["device_to_cpu_reference_transfers"] != int(optimized)):
        raise ValueError("actual timed public call lost admitted independent reference-byte anchor")
    if optimized:
        observations = actual["actual_forward_batches"]
        if len(observations) != 1 or observations[0]["rows"] != case_result["row_count"]:
            raise ValueError("one complete CUDA numerical batch required in each timed return")
        scope = observations[0]["gru_precision"]
        if (scope["profile_id"] != CUDA_GRU_PROFILE or scope["scoped_cudnn"] is not True
                or scope["effective_policy"]["cudnn"]["allow_tf32"] is not False
                or scope["synchronized_before_restore"] is not True
                or scope["ambient_flags_restored"] is not True):
            raise ValueError("actual timed public CUDA call lacked strict restored GRU scope")
    entry["public_profile_checked"] = True
    return entry


def _measure_cpu(helpers, output, case_result, label, session, texts, vectors, poll):
    for index in range(CPU_OBSERVATIONS):
        poll()
        session._synchronize()
        started = time.monotonic()
        actual = session.decode_formal_logic(texts, vectors)
        session._synchronize()
        elapsed = time.monotonic() - started
        if not math.isfinite(elapsed) or elapsed <= 0:
            raise ValueError("positive finite complete public call timing required")
        _retain_sample(helpers, output, case_result, label, index, actual, elapsed)
        poll()


def _measure_cuda_pairs(helpers, output, case_result, sessions, texts, vectors, poll, *, reverse_first):
    for index in range(PAIRED_OBSERVATIONS):
        order = GPU_LABELS[::-1] if (bool(index % 2) != reverse_first) else GPU_LABELS
        pair = {"pair_index": index, "completed_call_order": list(order), "seconds": {}, "sample_results": {}}
        case_result["cuda_pairs"].append(pair)
        for label in order:
            poll()
            owned = sessions[label]
            owned._synchronize()
            started = time.monotonic()
            actual = owned.decode_formal_logic(texts, vectors)
            owned._synchronize()
            elapsed = time.monotonic() - started
            if not math.isfinite(elapsed) or elapsed <= 0:
                raise ValueError("positive finite complete paired public timing required")
            pair["seconds"][label] = elapsed
            entry = _retain_sample(helpers, output, case_result, label, index, actual, elapsed)
            pair["sample_results"][label] = entry["result"]
            poll()


def _retain_numeric(helpers, torch, span, output, case_result, label, session, records, expected, poll):
    poll()
    numeric, numeric_scope = helpers._checked_private_logits(torch, span, session, records)
    directory = output / "workloads" / case_result["id"]
    entry = case_result["lanes"][label]
    entry["logits"] = _write(directory / (label + "-logits.json"), numeric)
    entry["numeric_scope"] = numeric_scope
    entry["four_logit_max_abs_errors"] = helpers._numeric_errors(torch, expected, numeric)
    poll()


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
    workloads = _authored_workloads()
    output, configuration = Path(output).absolute(), Path(configuration).absolute()
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError("canonical existing output parent required")
    output.mkdir(parents=False)
    started = time.monotonic()
    result = {"schema": "native4096-synthetic-guard-workloads-qualification/v1",
        "architecture_fixture_qualified": False, "native_leanstral_qualified": False,
        "production_qualified": False, "proof_authority": False, "execution_attestation": False,
        "kernel_resource_enforcement": False,
        "scope": "untrained synthetic4096 original and bitwise-v2 full public calls over bounded authored workload families",
        "encoder_calls": 0, "optimizer_steps": 0, "training_calls": 0,
        "optimizer_construction_attempts": 0, "foreign_process_actions": False,
        "persistent_precision_policy_mutated": False, "source_pins": [],
        "head_numerical_fixture_qualified": False,
        "optional_bitwise_primitive_enabled": include_bitwise_guard,
        "bitwise_full_session_fixture_qualified": False,
        "complete_gpu_session_speedups_qualified": False,
        "benchmark_scope": "nine authored equal-row-token-width workloads; four lanes; all measured public returns retained",
        "conservative_complete_call_gain_observed": False,
        "selected_product_route_changed": False, "future_repeatability_claimed": False,
        "workload_budget_seconds": WORKLOAD_BUDGET_SECONDS,
        "deadline_scope": "cooperative admitted-work checks before/after calls; cleanup is always attempted",
        "paired_observations_per_workload": PAIRED_OBSERVATIONS,
        "cpu_observations_per_workload": CPU_OBSERVATIONS,
        "all_timed_return_bytes_and_projections_retained": True,
        "public_timed_return_numeric_replay_scope": "every timed return gets exact decision/profile checks; all four logits replayed once per lane/workload under guarded private scope",
        "ordinary_reader_design": {"schema": "native4096-synthetic-guard-workloads-qualification/v1",
            "qualified_old_reader_source_unchanged": True,
            "producer_or_torch_imports_required": False, "maximum_ordinary_files": MAX_RETAINED_FILES,
            "maximum_total_bytes": MAX_RETAINED_TOTAL_BYTES,
            "checks": ["bounded ordinary single-link current/retained producer pins",
                "all workload/input/checkpoint bytes", "all 270 timed raw returns and per-lane canonical projection bundles",
                "exact projection/profile/strict-scope joins", "complete four-logit CPU reference and private replays",
                "recomputed paired timings/order groups/ratio interval/empirical thresholds",
                "all guard corruption refusals", "lease/allocation cleanup", "zero authority and zero fits"],
            "ordinary_byte_checks_grant_execution_authority": False},
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
    admitted_work_started = deadline = None

    def poll():
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("120-second admitted workload budget exceeded; partial evidence retained")

    try:
        result["workload_inputs"] = _write(output / "authored-workloads.json", workloads)
        sources = output / "producers"
        sources.mkdir()
        cleanup_path = Path(__file__).with_name("qualify_native_768_device.py").absolute()
        helpers_path = Path(__file__).with_name("qualify_synthetic_4096_head_device_v2.py").absolute()
        quad_path = Path(__file__).with_name("qualify_synthetic_4096_bitwise_session_device_v2.py").absolute()
        for role, path in (("benchmark", Path(__file__).absolute()), ("configuration", configuration),
                           ("cuda_cleanup", cleanup_path), ("qualified_v2_helpers", helpers_path),
                           ("qualified_quad_v2", quad_path)):
            item = _retain(path, sources / (role + "-" + path.name), role)
            result["source_pins"].append(item)
            result[role] = item["current"]
        if (result["configuration"]["sha256"] != CONFIG_SHA or result["cuda_cleanup"]["sha256"] != CLEANUP_SHA
                or result["qualified_v2_helpers"]["sha256"] != HELPERS_SHA
                or result["qualified_quad_v2"]["sha256"] != QUALIFIED_QUAD_SHA):
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
        if result["source_pins"][-1]["current"]["sha256"] != SCHEDULER_SHA:
            raise ValueError("unchanged pinned shared scheduler required")
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
            timeout=admission_timeout_seconds, request_id="synthetic4096-guard-workloads-qualification")
        result["admission"] = lease.to_dict()
        admitted_work_started = time.monotonic()
        deadline = admitted_work_started + WORKLOAD_BUDGET_SECONDS
        result["work_budget_started_after_root_admission"] = True
        poll()
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
        poll()
        for case in workloads:
            if [span.tokenize_source(source) for source in case["texts"]] != case["token_records"]:
                raise ValueError("pre-admission token/offset/byte preflight differs from pinned producer")
        result["all_workload_shape_preflights_match_producer_before_first_cuda_tensor"] = True
        result["initial_cuda_kernel_output"] = helpers._initial_kernel(torch, device)
        poll()
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

        poll()
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
                "equal_fixture_token_width_required_per_workload": True,
                "used_for_four_logit_parity": True}
            reference_logits = {}
            result["workloads"] = []
            (output / "workloads").mkdir()
            for case in workloads:
                poll()
                directory = output / "workloads" / case["id"]
                directory.mkdir()
                case_result = {"id": case["id"], "family": case["family"],
                    "row_count": case["row_count"], "shape_preflight": case["shape_preflight"],
                    "lanes": {}, "cuda_pairs": [], "paired_measurement_complete": False,
                    "fixture_qualified": False}
                result["workloads"].append(case_result)
                with torch.inference_mode():
                    actual = baseline.decode_formal_logic(case["texts"], vectors[:case["row_count"]])
                case_result["cpu_reference_result"] = _write(directory / "cpu-singleton-reference.json", actual)
                case_result["cpu_reference_decision_projection"] = _write(
                    directory / "cpu-singleton-reference-canonical-projection.json", helpers._decision_projection(actual))
                records = [{"tokens": tokens, "latent": vector} for tokens, vector in
                           zip(case["token_records"], vectors[:case["row_count"]])]
                numeric = helpers._reference_logits(torch, span, baseline, records)
                reference_logits[case["id"]] = numeric
                case_result["cpu_reference_logits"] = _write(directory / "cpu-singleton-reference-logits.json", numeric)
                poll()
            result["lanes"] = {}

            def start_session(label, session_class, optimized):
                poll()
                session_started = time.monotonic()
                remaining = max(1, math.floor(deadline - session_started))
                owned = session_class(checkpoint, expected_checkpoint_sha256=checkpoint_sha,
                    optimized=optimized, synthetic_unreceipted=True,
                    scheduler=scheduler, parent_lease=lease,
                    memory_mb=CHILD_MEMORY_MB, gpu_memory_mb=CHILD_GPU_MB,
                    unified_memory_mb=CHILD_MEMORY_MB + CHILD_GPU_MB,
                    admission_timeout_seconds=min(admission_timeout_seconds, remaining), max_seconds=remaining)
                active_sessions[label] = owned
                if owned._device != (f"cuda:{device}" if optimized else "cpu"):
                    raise ValueError("requested CPU/CUDA lane device differs: " + label)
                result["lanes"][label] = {"profile": owned.describe(),
                    "constructor_seconds": time.monotonic() - session_started,
                    "timing_scope": "complete public decode with checkpoint/immutable anchor/value/ownership checks",
                    "bitwise_binding_and_comparator_candidate": label.startswith("bitwise_")}
                poll()
                return owned

            def finish_session(label, owned):
                poll()
                lane = result["lanes"][label]
                lane["paired_reference_corruption_refusals"] = helpers._paired_reference_refusals(owned, texts, vectors)
                lane["model_only_subnormal_control"] = helpers._model_only_subnormal_control(owned, texts, vectors)
                lane["final_profile"] = owned.describe()
                poll()
                owned.close()
                lane["own_child_lease_released"] = owned._lease.released
                if lane["own_child_lease_released"] is not True:
                    raise ValueError("owned complete session child lease did not close: " + label)
                active_sessions.pop(label)

            for label, session_class in (("cpu", resident.DeviceLeanstral4096SpanSession),
                    ("bitwise_cpu", bitwise_resident.BitwiseDeviceLeanstral4096SpanSession)):
                session = start_session(label, session_class, False)
                for case, case_result in zip(workloads, result["workloads"]):
                    count, sources_for_case = case["row_count"], case["texts"]
                    case_result["lanes"][label] = {"samples": []}
                    poll()
                    session.decode_formal_logic(sources_for_case, vectors[:count])
                    poll()
                    _measure_cpu(helpers, output, case_result, label, session, sources_for_case, vectors[:count], poll)
                    records = [{"tokens": tokens, "latent": vector} for tokens, vector in
                               zip(case["token_records"], vectors[:count])]
                    _retain_numeric(helpers, torch, span, output, case_result, label, session,
                                    records, reference_logits[case["id"]], poll)
                finish_session(label, session)
                session = None
            gpu_sessions["cuda_batched"] = start_session(
                "cuda_batched", resident.DeviceLeanstral4096SpanSession, True)
            gpu_sessions["bitwise_cuda_batched"] = start_session(
                "bitwise_cuda_batched", bitwise_resident.BitwiseDeviceLeanstral4096SpanSession, True)
            result["cuda_pair_timing_profile"] = {
                "scope": "same fixture; separately admitted private models; serial completed full public calls",
                "sample_count_per_lane_per_workload": PAIRED_OBSERVATIONS,
                "each_lane_first_per_workload": PAIRED_OBSERVATIONS // 2,
                "native_forwards_overlap": False, "source_guard_or_anchor_boundary_removed": False,
                "all_timed_returns_retained_before_comparison": True,
                "serialization_outside_measured_call": True, "warmup_calls_per_lane_per_workload": 1}
            for position, (case, case_result) in enumerate(zip(workloads, result["workloads"])):
                count = case["row_count"]
                for label, owned in gpu_sessions.items():
                    case_result["lanes"][label] = {"samples": []}
                    poll()
                    owned.decode_formal_logic(case["texts"], vectors[:count])
                    owned._synchronize()
                    poll()
                _measure_cuda_pairs(helpers, output, case_result, gpu_sessions,
                    case["texts"], vectors[:count], poll, reverse_first=bool(position % 2))
                case_result["paired_measurement_complete"] = True
                records = [{"tokens": tokens, "latent": vector} for tokens, vector in
                           zip(case["token_records"], vectors[:count])]
                for label, owned in gpu_sessions.items():
                    _retain_numeric(helpers, torch, span, output, case_result, label, owned,
                                    records, reference_logits[case["id"]], poll)
                for label, lane in case_result["lanes"].items():
                    samples = [sample["seconds_per_completed_public_call"] for sample in lane["samples"]]
                    lane["samples_seconds_per_call"] = samples
                    lane["sample_count"] = len(samples)
                    lane["median_seconds"] = statistics.median(samples)
                    lane["repetitions_per_sample"] = 1
                    expected_count = PAIRED_OBSERVATIONS if label in GPU_LABELS else CPU_OBSERVATIONS
                    if len(samples) != expected_count:
                        raise ValueError("complete timed sample coverage required in every lane/workload")
                case_result["paired_ratio_analysis"] = _paired_ratio_analysis(case_result["cuda_pairs"], len(workloads))
                case_result["full_session_speedup_original_cuda_over_bitwise_cuda"] = (
                    case_result["lanes"]["cuda_batched"]["median_seconds"] /
                    case_result["lanes"]["bitwise_cuda_batched"]["median_seconds"])
                case_result["full_session_speedup_original_cpu_over_bitwise_cpu"] = (
                    case_result["lanes"]["cpu"]["median_seconds"] /
                    case_result["lanes"]["bitwise_cpu"]["median_seconds"])
                case_result["original_cpu_over_original_cuda"] = (
                    case_result["lanes"]["cpu"]["median_seconds"] /
                    case_result["lanes"]["cuda_batched"]["median_seconds"])
                case_result["fixture_qualified"] = True
                poll()
            for label, owned in list(gpu_sessions.items()):
                finish_session(label, owned)
            gpu_sessions.clear()
            session = owned = None
            baseline = None
            result["full_session_speedups_v2_cuda_over_bitwise_cuda"] = {
                case["id"]: case["full_session_speedup_original_cuda_over_bitwise_cuda"]
                for case in result["workloads"]}
            result["workloads_with_conservative_empirical_gain"] = [case["id"] for case in result["workloads"]
                if case["paired_ratio_analysis"]["conservative_empirical_gain_observed"]]
            result["suite_empirical_gain_criteria_met"] = (
                len(result["workloads_with_conservative_empirical_gain"]) == len(workloads))
            result["head_numerical_fixture_qualified"] = True
            result["guard_admission"] = None
            poll()
            guard_lease = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1,
                memory_mb=CHILD_MEMORY_MB, gpu_memory_mb=CHILD_GPU_MB,
                unified_memory_mb=CHILD_MEMORY_MB + CHILD_GPU_MB, requires_gpu=True,
                parent_lease=lease, timeout=min(admission_timeout_seconds, max(1, math.floor(deadline - time.monotonic()))),
                request_id="synthetic4096-native-tensor-guard-workloads")
            result["guard_admission"] = guard_lease.to_dict()
            result["guard"] = helpers._guard_body(torch, guard, device, bitwise_guard)
            poll()
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
            poll()
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
        poll()
        result["admitted_work_seconds_before_cleanup"] = time.monotonic() - admitted_work_started
        result["admitted_work_budget_completed"] = True
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
        for case in result.get("workloads", []):
            for label, lane in case.get("lanes", {}).items():
                pending = lane.pop("_pending_projections", None)
                if pending is None:
                    continue
                try:
                    lane["canonical_projection_bundle"] = _write(
                        output / "workloads" / case["id"] / (label + "-canonical-projections.json"), pending)
                except BaseException as error:
                    safe_close = False
                    result.setdefault("projection_bundle_errors", []).append(
                        {"workload": case["id"], "lane": label,
                         "type": type(error).__name__, "message": str(error)})
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
        if admitted_work_started is not None:
            result["admitted_work_seconds_including_cleanup"] = time.monotonic() - admitted_work_started
        retained_files, retained_total_bytes = 0, 0
        try:
            for retained_path in output.rglob("*"):
                entry_stat = retained_path.lstat()
                if stat.S_ISDIR(entry_stat.st_mode):
                    continue
                if (not stat.S_ISREG(entry_stat.st_mode) or entry_stat.st_nlink != 1
                        or entry_stat.st_mode & 0o222 or not 0 < entry_stat.st_size <= MAX_FILE_BYTES):
                    raise ValueError("ordinary immutable retained file required")
                retained_files += 1
                retained_total_bytes += entry_stat.st_size
            if retained_files + 1 > MAX_RETAINED_FILES or retained_total_bytes > MAX_RETAINED_TOTAL_BYTES:
                raise ValueError("closed workload archive exceeds ordinary-reader namespace bound")
            result["retained_namespace_within_bounds_before_result"] = True
        except BaseException as error:
            safe_close = False
            result["retained_namespace_error"] = {"type": type(error).__name__, "message": str(error)}
        result["retained_file_count_before_result"] = retained_files
        result["retained_total_bytes_before_result"] = retained_total_bytes
        result["architecture_fixture_qualified"] = bool(setup_complete and safe_close and sources_current
            and result.get("own_root_lease_released") is True and result["error"] is None
            and not result.get("qualification_refusals")
            and result.get("admitted_work_budget_completed") is True
            and len(result.get("workloads", [])) == 9
            and all(case.get("fixture_qualified") is True for case in result["workloads"]))
        result["bitwise_full_session_fixture_qualified"] = result["architecture_fixture_qualified"]
        result["complete_gpu_session_speedups_qualified"] = result["architecture_fixture_qualified"]
        result["conservative_complete_call_gain_observed"] = bool(result["architecture_fixture_qualified"]
            and result.get("suite_empirical_gain_criteria_met") is True)
        result["timed_return_count"] = sum(len(lane.get("samples", [])) for case in result.get("workloads", [])
            for lane in case.get("lanes", {}).values())
        result["expected_timed_return_count"] = 9 * (2 * CPU_OBSERVATIONS + 2 * PAIRED_OBSERVATIONS)
        result["elapsed_seconds"] = time.monotonic() - started
        result["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        result_bytes = _wire(result)
        if len(result_bytes) + retained_total_bytes > MAX_RETAINED_TOTAL_BYTES:
            result["architecture_fixture_qualified"] = False
            result["bitwise_full_session_fixture_qualified"] = False
            result["complete_gpu_session_speedups_qualified"] = False
            result["conservative_complete_call_gain_observed"] = False
            result["retained_namespace_within_bounds_before_result"] = False
            result["retained_namespace_error"] = {"type": "ValueError", "message": "final result plus retained archive exceeds 64MiB"}
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
