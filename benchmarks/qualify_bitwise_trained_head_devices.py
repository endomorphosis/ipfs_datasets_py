"""Bounded retained-trained 8D/384D/768D original/bitwise head qualification.

This is an ordinary, finite local evidence producer. It replays pinned trained
checkpoints and historical encoder bytes, and never fits or calls an encoder.
Twelve balanced paired observations include complete public-call checks. Every
timed report and formula projection is retained. Separately checked native768
four-logit snapshots cover each lane/count; they are outside public-call timing.
No timing ratio grants production admission, proof or execution attestation.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
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
import sys
import time
import traceback
from unittest.mock import patch

CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
CLEANUP_SHA = "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c"
FORMULA_SHA = "5b5631eb1cf779ea8b6fcf3073d074355f52ef8c74adea84fc595421dea85089"
SPAN_SHA = "d1c12eb54ca8c17c9815ed20db9237c86876361ac3d72fa30ce2d470b0fccf91"
BIT_GUARD_SHA = "6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34"
FORMULA_PROFILE = "modal-latent-formula-bitwise-owned-device-float32/v1"
SPAN_PROFILE = "native-768-source-span-batched-device-bitwise-checkpoint-anchor-float32/v1"
SPAN_ORIGINAL_PROFILE = "native-768-source-span-batched-device-float32-cpu-decisions/v1"
SPAN_GRU_PROFILE = "native-768-source-span-device-strict-cuda-float32/v2"
DECISION_PROFILE = "retained-trained-head-exact-decisions-numeric-diagnostics/v1"
COUNTS = (1, 16, 32)
PAIRS = 12
MAX_SECONDS = 120
MAX_FILE_BYTES = 8 * 1024**2
MAX_TOTAL_BYTES = 64 * 1024**2
MAX_FILES = 1024
ROOT_RAM, ROOT_GPU, ROOT_UNIFIED = 2048, 512, 2560
CHILD_RAM, CHILD_GPU, CHILD_UNIFIED = 1024, 256, 1280
OUTPUTS = ("modality", "presence", "start", "end")
PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
FIXTURES = {
    "formula8_checkpoint": ("legal-cuda-device-qualification-20261003-05/legal-8-checkpoint.json",
        "09558c8db4455bf3caad1f287cea9448da47393fe0fae1c5c140f0ff00e0e466"),
    "formula384_checkpoint": ("legal-cuda-device-qualification-20261003-05/legal-384-checkpoint.json",
        "7d8d0e60f7d644bed06e0a48ffc82c014c9ed697d89b9cdc2e4a5d55863885ce"),
    "formula8_training_inputs": ("legal-cuda-device-qualification-20261003-05/legal-8-training-inputs.json",
        "212b4817fd074e9c3f9c76c53485774ad44083b65c691938bb80e2962723a30c"),
    "formula384_training_inputs": ("legal-cuda-device-qualification-20261003-05/legal-384-training-inputs.json",
        "febf18138dbe1bc8480f06d43586a35453db55c3d8493c03a57ed848dab6093f"),
    "span768_checkpoint": ("native-768-device-qualification-20261004-04/diagnostic-native768-head.json",
        "9fcd8dd3b9727f5ee93b5b2cb2d7f23e482f16c24f64c23a3ae9da2168e3117b"),
    "span768_sources": ("native-768-device-qualification-20261004-04/source-rows.json",
        "eec38602f9d3c3b0c1511ab05b473bbcf2bb3647ac1c4854e899fb0200ad4e46"),
    "span768_historical_encoder_outputs": ("native-768-device-qualification-20261004-04/encoder-cuda-batch32.json",
        "f728dab53925cd2f9d053d760dcafab756ed718197a8649f24c2000bfc73c221"),
}


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _read(path):
    path = Path(path).absolute()
    if path.parent.resolve(strict=True) != path.parent:
        raise ValueError("canonical ordinary input parent required")
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_FILE_BYTES):
        raise ValueError("bounded single-link ordinary input required: " + str(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(MAX_FILE_BYTES + 1)
        after_open = os.fstat(stream.fileno())
    after = path.lstat()
    identities = [(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
                  for s in (before, opened, after_open, after)]
    if any(item != identities[0] for item in identities[1:]) or len(raw) != before.st_size:
        raise ValueError("ordinary input identity changed while reading: " + str(path))
    return raw


def _pin(path, raw=None):
    raw = _read(path) if raw is None else raw
    return {"path": str(Path(path).absolute()), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


class Evidence:
    """Account every output file, reserving space for a refusal/cleanup result."""
    def __init__(self, root):
        self.root, self.files, self.bytes = root, [], 0

    def raw(self, name, raw, *, final=False):
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_FILE_BYTES:
            raise ValueError("bounded immutable evidence bytes required")
        ceiling = MAX_TOTAL_BYTES if final else MAX_TOTAL_BYTES - 2 * 1024**2
        if self.bytes + len(raw) > ceiling or len(self.files) >= MAX_FILES:
            raise ValueError("bounded evidence file count/total64MiB exceeded")
        path = self.root / name
        if path.parent.resolve(strict=True) != path.parent or not path.is_relative_to(self.root):
            raise ValueError("canonical contained evidence output required")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o444)
        pin = _pin(path)
        self.bytes += len(raw)
        self.files.append(pin)
        return pin

    def json(self, name, value, **kwargs):
        return self.raw(name, _wire(value), **kwargs)

    def retain(self, name, path, role, expected=None):
        raw = _read(path)
        current = _pin(path, raw)
        if expected is not None and current["sha256"] != expected:
            raise ValueError("fixed " + role + " bytes differ")
        retained = self.raw(name, raw)
        return raw, {"role": role, "current": current, "retained_copy": retained}


def _marker(value):
    if value is None:
        return None
    if type(value) is not float or not math.isfinite(value):
        raise ValueError("known numeric diagnostic must be finite float or None")
    return {"known_finite_numeric_diagnostic_value_excluded": True}


def _decisions(report, family):
    """Retain all decision fields; exclude only execution and named scores."""
    result = deepcopy(report)
    excluded = (("inference_implementation",) if family == "formula" else
        ("execution_profile", "actual_forward_batches", "cuda_executed", "numerical_batching",
         "batch_memory_bound", "cpu_head_output_materializations", "device_to_cpu_head_transfers",
         "canonical_decision_device"))
    for name in excluded:
        result.pop(name, None)
    # These describe the batching implementation, rather than a decision.
    if family == "span":
        result.pop("valid_source_count", None)
    for row in result["rows"]:
        if "minimum_decision_logit_margin" in row:
            row["minimum_decision_logit_margin"] = _marker(row["minimum_decision_logit_margin"])
        if "span_diagnostics" not in row:
            continue
        diagnostics = row["span_diagnostics"]
        if "modality_logits" in diagnostics:
            scores = diagnostics["modality_logits"]
            if type(scores) is not list or len(scores) != 3 or any(x is None for x in scores):
                raise ValueError("complete modality diagnostic required")
            diagnostics["modality_logits"] = [_marker(x) for x in scores]
        for facet in diagnostics["facets"].values():
            for name in ("presence_logit_margin", "span_logit_margin"):
                if name in facet:
                    facet[name] = _marker(facet[name])
    return result


def _numeric_error(expected, actual):
    """Compare every numeric element, retaining exact nested shape coverage."""
    if type(expected) is list:
        if type(actual) is not list or len(expected) != len(actual) or not expected:
            raise ValueError("complete numeric nested shape differs")
        return max(_numeric_error(a, b) for a, b in zip(expected, actual))
    if (type(expected) not in (float, int) or type(actual) not in (float, int)
            or not math.isfinite(expected) or not math.isfinite(actual)):
        raise ValueError("finite complete numeric values required")
    error = abs(expected - actual)
    if error > 5e-5:
        raise ValueError("complete numeric parity exceeds absolute5e-5")
    return error


def _state_pin(owner, family):
    model = owner.model if family == "formula" else owner._model
    state = {name: value.detach().cpu().tolist() for name, value in model.state_dict().items()}
    raw = _wire(state)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _constructor(torch, factory):
    """Observe legitimate Adam restoration only during this constructor."""
    code, count = torch.optim.Adam.__init__.__code__, 0
    previous = sys.getprofile()
    def profiler(frame, event, arg):
        nonlocal count
        if event == "call" and frame.f_code is code:
            count += 1
        if previous is not None:
            previous(frame, event, arg)
    sys.setprofile(profiler)
    started = time.monotonic()
    try:
        owner = factory()
        return owner, {"elapsed_seconds": time.monotonic() - started,
                       "adam_constructor_calls": count, "profiler_scope": "constructor_only"}
    finally:
        sys.setprofile(previous)


class Cancellation:
    def __init__(self, root, deadline):
        self.root, self.deadline = root, deadline
        self.owner, self.family, self.action = None, None, None
        self.triggered, self.force_cancel = False, False

    def poll(self):
        if self.root.released or self.root.cancelled:
            raise RuntimeError("owned qualification root revoked")
        if time.monotonic() >= self.deadline:
            raise TimeoutError("qualification exceeded120seconds after root admission")

    def is_set(self):
        self.poll()
        if self.action is not None and self.owner is not None:
            observed = (self.owner._active_observer if self.family == "formula" else
                        self.owner._observations)
            forwarded = (type(observed) is dict and observed.get("output", 0) > 0
                         if self.family == "formula" else bool(observed))
            if forwarded and not self.triggered:
                self.triggered = True
                self.action()
        return self.force_cancel

    def clear(self):
        self.owner, self.family, self.action = None, None, None
        self.triggered, self.force_cancel = False, False


class Lane:
    def __init__(self, owner, family, *, caller_lease=None):
        self.owner, self.family, self.caller_lease = owner, family, caller_lease
        self.child_lease = caller_lease if caller_lease is not None else owner._lease
        self.lease_id = self.child_lease.lease_id

    def call(self, inputs, count):
        if self.family == "formula":
            return self.owner.infer_with_projection(deepcopy(inputs["rows"][:count]))
        return self.owner.decode_formal_logic(deepcopy(inputs["texts"][:count]),
            deepcopy(inputs["vectors"][:count]),
            embedding_receipts=deepcopy(inputs["receipts"][:count]),
            expected_receipt_sha256s=inputs["receipt_pins"][:count]), None

    def describe(self):
        return (self.owner.inference_implementation if self.family == "formula"
                else self.owner.describe())

    def close(self, torch, device):
        if self.owner is None:
            return
        if self.caller_lease is None:
            self.owner.close()
            self.owner = None
        else:
            # Original formula has no owned close. Drop the caller's only
            # object reference before releasing its explicitly acquired child.
            self.owner = None
            gc.collect()
            torch.cuda.synchronize(device)
            self.caller_lease.release()
        if not self.child_lease.released:
            raise ValueError("owned child did not release after synchronized close")


def _plain_row_logits(torch, actual, length):
    shapes = {"modality": (1, 3), "presence": (1, 4, 2),
              "start": (1, 6, length), "end": (1, 6, length)}
    if type(actual) is not dict or set(actual) != set(OUTPUTS):
        raise ValueError("complete native768 four-head output required")
    result = {}
    for name in OUTPUTS:
        value = actual[name]
        if (value.dtype != torch.float32 or tuple(value.shape) != shapes[name]
                or not bool(torch.isfinite(value).all())):
            raise ValueError("native768 finite complete float32 logit shape differs")
        result[name] = value.detach().cpu().tolist()
    return result


def _span_logits(torch, span, batch, lane, inputs, count, *, singleton):
    """Checked independent numeric snapshot; no cached/public result substitution."""
    owner = lane.owner
    records = [{"tokens": span.tokenize_source(text), "latent": vector}
               for text, vector in zip(inputs["texts"][:count], inputs["vectors"][:count])]
    actual = tensors = None
    with owner._operation():
        owner._check()
        start = len(owner._observations)
        try:
            bound = owner._admit_batch_memory(records)
            rows = []
            with torch.inference_mode():
                if singleton:
                    for record in records:
                        tensors = span._batch(owner._tensor_factory, [record])
                        actual = owner._model(*tensors)
                        rows.append(_plain_row_logits(torch, actual, len(record["tokens"])))
                else:
                    tensors = span._batch(owner._tensor_factory, records)
                    actual = owner._model(*tensors)
                    for index, record in enumerate(records):
                        rows.append(_plain_row_logits(torch,
                            batch._row_output(actual, index, len(record["tokens"])), len(record["tokens"])))
            owner._synchronize()
            owner._check()
            observations = deepcopy(owner._observations[start:])
            if len(observations) != (count if singleton else 1):
                raise ValueError("native768 numeric snapshot forward coverage differs")
            if owner._device.startswith("cuda:"):
                for observation in observations:
                    precision = observation["gru_precision"]
                    if (precision["profile_id"] != SPAN_GRU_PROFILE or not precision["scoped_cudnn"]
                            or precision["effective_policy"]["cudnn"]["allow_tf32"] is not False
                            or not precision["synchronized_before_restore"]
                            or not precision["ambient_flags_restored"]):
                        raise ValueError("native768 strict scoped GRU policy not restored")
            return rows, {"scope": "separate_checked_private_four_logit_forward_outside_public_timing",
                "singletons": singleton, "observations": observations, "batch_memory_bound": bound,
                "entry_and_exit_owned_checks": True, "coverage": "one_snapshot_per_lane_per_count"}
        finally:
            actual = tensors = None
            owner._synchronize()
            del owner._observations[start:]


def _four_errors(expected, actual):
    if len(expected) != len(actual):
        raise ValueError("native768 numeric row coverage differs")
    return {name: max(_numeric_error(left[name], right[name])
                     for left, right in zip(expected, actual)) for name in OUTPUTS}


def _new_controls(torch, lane, inputs, cancellation):
    """Actual-device mutable-pair/anchor/input/cancellation refusals on NEW only."""
    owner, family = lane.owner, lane.family
    model = owner.model if family == "formula" else owner._model
    refs = owner._reference_weights if family == "formula" else owner._reference
    state = model.state_dict()
    names = [name for name, value in state.items() if value.dtype == torch.float32 and value.numel()]
    if not names:
        raise ValueError("native trained fixture lacks float32 controls")
    name = names[0]
    current, reference = state[name].view(torch.int32).reshape(-1), refs[name].view(torch.int32).reshape(-1)
    original, original_ref = current.detach().clone(), reference.detach().clone()
    controls = []
    def restore():
        current.data.copy_(original)
        reference.data.copy_(original_ref)
        owner._synchronize()
        cancellation.clear()
    def pair():
        bits = 1056964608 if int(original[0].detach().cpu()) != 1056964608 else 1048576000
        current.data[0] = reference.data[0] = bits
    def refusal(label, invoke, *, expected, callback=False):
        code_methods = ((model.project, model.next_logits, model.output.forward)
                        if family == "formula" else (model.forward,))
        codes = {method.__func__.__code__ for method in code_methods}
        forward_calls = 0
        previous = sys.getprofile()
        def observer(frame, event, arg):
            nonlocal forward_calls
            if event == "call" and frame.f_code in codes:
                forward_calls += 1
            if previous is not None:
                previous(frame, event, arg)
        try:
            sys.setprofile(observer)
            try:
                invoke()
            finally:
                sys.setprofile(previous)
        except ValueError as error:
            if expected not in str(error):
                raise ValueError("unexpected " + label + " refusal: " + str(error)) from error
            if callback and not cancellation.triggered:
                raise ValueError("native boundary callback did not execute")
            if (callback and forward_calls == 0) or (not callback and forward_calls != 0):
                raise ValueError("native control forward boundary coverage differs")
            controls.append({"control": label, "refused": True, "refusal": str(error),
                "post_forward_callback_executed": cancellation.triggered if callback else False,
                "actual_model_forward_calls": forward_calls, "before_forward_refusal": not callback,
                "forward_observation_scope": "control_only_python_call_profiler_no_model_hook_or_method_replacement",
                "scope": "new_owned_session_only_old_paired_reference_custody_not_claimed"})
        else:
            raise ValueError("new native control accepted corruption: " + label)
    try:
        pair()
        refusal("paired_finite_data_mutation", lambda: lane.call(inputs, 1), expected="reference bytes changed")
        restore()
        zero = None
        for key in names:
            bits = state[key].view(torch.int32).reshape(-1)
            indices = ((bits == 0) | (bits == -2147483648)).nonzero()
            if indices.numel():
                zero = (key, int(indices[0, 0].detach().cpu()))
                break
        if zero is None:
            controls.append({"control": "paired_signed_zero_data_mutation", "applicable": False,
                             "reason": "no actual admitted signed zero tensor element"})
        else:
            key, index = zero
            a, b = state[key].view(torch.int32).reshape(-1), refs[key].view(torch.int32).reshape(-1)
            old_a, old_b = int(a[index].detach().cpu()), int(b[index].detach().cpu())
            try:
                a.data[index] = b.data[index] = -2147483648 if old_a == 0 else 0
                refusal("paired_signed_zero_data_mutation", lambda: lane.call(inputs, 1),
                        expected="reference bytes changed")
                controls[-1].update(actual_admitted_zero_tensor=key, actual_admitted_zero_index=index,
                                    original_float32_bits_int32=old_a)
            finally:
                a.data[index], b.data[index] = old_a, old_b
                a = b = None
        anchor = owner._reference_anchor
        try:
            owner._reference_anchor = type(anchor)(anchor.checkpoint_sha256, anchor.layout, anchor.payload, anchor.sha256)
            refusal("equal_content_anchor_identity_replacement", lambda: lane.call(inputs, 1),
                    expected="reference byte anchor changed")
        finally:
            owner._reference_anchor = anchor
        current.data[0] = 1
        refusal("model_only_positive_subnormal_bits", lambda: lane.call(inputs, 1), expected="changed")
        controls[-1].update(mutated_float32_bits_int32=1, original_float32_bits_int32=int(original[0].detach().cpu()),
                            proves_zero_to_subnormal_ftz_refusal=int(original[0].detach().cpu()) == 0)
        restore()
        cancellation.owner, cancellation.family, cancellation.action = owner, family, pair
        refusal("paired_finite_after_actual_forward_poll", lambda: lane.call(inputs, 1),
                expected="reference bytes changed", callback=True)
        restore()
        authored = deepcopy(inputs)
        def change_input():
            vector = authored["rows"][0]["latent"] if family == "formula" else authored["vectors"][0]
            vector[0] = vector[0] + 0.25
        cancellation.owner, cancellation.family, cancellation.action = owner, family, change_input
        # Pass the actual authored containers; Lane.call intentionally copies
        # ordinary benchmark inputs and therefore cannot exercise this control.
        def actual_input_call():
            if family == "formula":
                return owner.infer_with_projection(authored["rows"][:1])
            return owner.decode_formal_logic(authored["texts"][:1], authored["vectors"][:1],
                embedding_receipts=authored["receipts"][:1], expected_receipt_sha256s=authored["receipt_pins"][:1])
        refusal("authored_input_mutation_after_forward_poll", actual_input_call,
                expected="checkpoint content changed", callback=True)
        restore()
        cancellation.force_cancel = True
        try:
            lane.call(inputs, 1)
        except (RuntimeError, TimeoutError) as error:
            if "cancel" not in str(error):
                raise
            controls.append({"control": "cancel_before_forward", "refused": True, "refusal": str(error)})
        else:
            raise ValueError("new owned session ignored cancellation")
        restore()
        lane.describe()
        return controls
    finally:
        restore()
        state.clear()
        current = reference = original = original_ref = model = owner = None


def run(output, configuration, *, admission_timeout_seconds=30):
    if type(admission_timeout_seconds) is not int or not 1 <= admission_timeout_seconds <= 60:
        raise ValueError("admission timeout must be1..60seconds")
    output, configuration = Path(output).absolute(), Path(configuration).absolute()
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError("canonical existing output parent required")
    output.mkdir(parents=False)
    evidence = Evidence(output)
    result = {"schema": "retained-trained-head-bitwise-device-qualification/v1", "qualified": False,
        "scope": "retained_trained_formula8_formula384_native768_local_head_numeric_and_complete_call_measurements",
        "production_qualified": False, "proof_authority": False, "execution_attestation": False,
        "semantic_correctness_verified": False, "fresh_encoder_execution_qualified": False,
        "native_encoder_origin_authenticated": False, "kernel_resource_enforcement": False,
        "encoder_calls": 0, "training_calls": 0, "optimizer_steps": 0,
        "optimizer_constructor_calls": 0, "training_mode_true_calls": 0,
        "complete_call_measurements_qualified": False, "universal_speedup_claimed": False,
        "persistent_precision_policy_mutated": False, "foreign_process_actions": False,
        "pid": os.getpid(), "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "max_seconds_after_root_admission": MAX_SECONDS, "admission_timeout_seconds": admission_timeout_seconds,
        "source_pins": [], "fixture_pins": [], "families": {}, "owned_children": [], "error": None,
        "canonical_projection_profile_id": DECISION_PROFILE,
        "canonical_projection_scope": "all non-execution report fields; only named finite score values marked",
        "numeric_tolerance_absolute": 5e-5, "paired_observations_per_lane_per_count": PAIRS,
        "span_numeric_scope": "one separate complete four-logit snapshot per lane/count, all public timed canonical decisions",
        "historical_receipt_scope": "exact retained content SHA equality only; no fresh encoder call, signatures or origin attestation"}
    scheduler = root = torch = device = cancellation = cleanup = None
    probe = product = None
    old_threads, safe_close, policy_before = None, True, None
    active, external_children = [], []
    staged, fixture_data, module_paths = [], {}, {}
    stack = ExitStack()
    began = time.monotonic()
    try:
        (output / "producers").mkdir()
        (output / "fixtures").mkdir()
        package_root = Path(__file__).absolute().parent.parent
        workspace = package_root.parent.parent
        optimizer = package_root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
        cleanup_path = Path(__file__).with_name("qualify_native_768_device.py").absolute()
        source_names = ("resource_scheduler", "modal_latent_formula", "modal_latent_formula_inference",
            "modal_latent_formula_device_inference", "modal_latent_formula_bitwise_device_inference",
            "legal_span_formula", "legal_span_dimensions", "legal_span_device_inference",
            "legal_span_device_batch_inference", "legal_span_device_bitwise_inference", "legal_formula_codec",
            "legal_ir_grammar_decoder", "legal_ir_family_evaluator", "snapshot_evaluator",
            "owned_tensor_value_guard", "owned_tensor_bitwise_guard", "checkpoint_content_guard",
            "runtime_telemetry", "proof_resource_safety")
        expected_sources = {"modal_latent_formula_bitwise_device_inference": FORMULA_SHA,
                            "legal_span_device_bitwise_inference": SPAN_SHA,
                            "owned_tensor_bitwise_guard": BIT_GUARD_SHA}
        entries = [("benchmark", Path(__file__).absolute(), None), ("cleanup_helper", cleanup_path, CLEANUP_SHA)]
        entries += [(name, optimizer / (name + ".py"), expected_sources.get(name)) for name in source_names]
        entries += [("tree_pin", package_root / "ipfs_datasets_py/logic/autoformal/tree_pin.py", None),
                    ("canonical_contracts", package_root / "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py", None),
                    ("cid_utils", package_root / "ipfs_datasets_py/utils/cid_utils.py", None)]
        for index, (role, path, expected) in enumerate(entries):
            _, pin = evidence.retain(f"producers/{index:02d}-{path.name}", path, role, expected)
            result["source_pins"].append(pin)
            staged.append(pin)
            module_paths[role] = path
        config_raw, result["shared_configuration"] = evidence.retain("configuration.json", configuration,
            "shared_configuration", CONFIG_SHA)
        staged.append(result["shared_configuration"])
        for role, (relative, expected) in FIXTURES.items():
            raw, pin = evidence.retain("fixtures/" + role + ".json",
                workspace / "artifacts/codebase_ir_terminal_bench" / relative, role, expected)
            result["fixture_pins"].append(pin)
            staged.append(pin)
            fixture_data[role] = json.loads(raw)
        # All producer and historical fixture bytes precede head imports.
        if any(PREFIX + name in sys.modules for name in source_names if name != "resource_scheduler"):
            raise ValueError("fresh qualification worker must not have producer modules pre-imported")
        configuration_data = json.loads(config_raw)
        resources = importlib.import_module(PREFIX + "resource_scheduler")
        scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(
            **configuration_data["persisted_config"], state_path=configuration_data["state_path"],
            lease_ttl_seconds=configuration_data["lease_ttl_seconds"],
            auto_renew_leases=configuration_data["auto_renew_leases"]))
        result["resources_before"] = scheduler.snapshot()
        root = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=2,
            memory_mb=ROOT_RAM, gpu_memory_mb=ROOT_GPU, unified_memory_mb=ROOT_UNIFIED,
            requires_gpu=True, timeout=admission_timeout_seconds,
            request_id="retained-trained-bitwise-head-device-qualification")
        admitted = time.monotonic()
        cancellation = Cancellation(root, admitted + MAX_SECONDS)
        result["admission"] = root.to_dict()
        result["root_admission_elapsed_seconds"] = admitted - began
        print("ADMITTED", root.lease_id, flush=True)
        import torch as actual_torch
        torch = actual_torch
        old_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        if not torch.cuda.is_available():
            raise RuntimeError("actual CUDA required; CPU fallback cannot qualify")
        device = torch.cuda.current_device()
        baseline = torch.cuda.memory_allocated(device)
        result["gpu_allocated_before_producer_imports_bytes"] = baseline
        result["telemetry_context_admission_scope"] = "initialized context allowed only at zero allocation before producer imports"
        if baseline != 0:
            raise ValueError("fresh worker has pre-existing allocated CUDA tensors")
        result["gpu_allocated_before_owned_sessions_bytes"] = baseline
        result["gpu_reserved_before_owned_sessions_bytes"] = torch.cuda.memory_reserved(device)
        modules = {name: importlib.import_module(PREFIX + name) for name in source_names}
        for name, module in modules.items():
            if Path(module.__file__).absolute() != module_paths[name]:
                raise ValueError("producer import resolved to unretained source: " + name)
        for pin in staged:
            if _pin(pin["current"]["path"]) != pin["current"]:
                raise ValueError("source/configuration/fixture bytes changed before model construction")
        if torch.cuda.memory_allocated(device) != 0:
            raise ValueError("producer import allocated CUDA tensor before models")
        spec = importlib.util.spec_from_file_location("_trained_head_owned_cleanup", cleanup_path)
        cleanup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cleanup)
        resident, span, batch = (modules[name] for name in
            ("legal_span_device_inference", "legal_span_formula", "legal_span_device_batch_inference"))
        policy_before = resident._cuda_float32_policy(torch)
        result["precision_policy_before"] = policy_before
        probe = torch.tensor([2.], dtype=torch.float32, device=f"cuda:{device}")
        product = probe * probe
        if product.detach().cpu().tolist() != [4.]:
            raise ValueError("actual CUDA initial kernel differs")
        probe = product = None
        torch.cuda.synchronize(device)
        torch.cuda.reset_peak_memory_stats(device)
        result["hardware"] = {"torch": str(torch.__version__), "cuda_runtime": torch.version.cuda,
            "device_index": device, "name": torch.cuda.get_device_name(device),
            "capability": list(torch.cuda.get_device_capability(device)), "actual_initial_cuda_kernel": True,
            "physical_memory_bytes": torch.cuda.get_device_properties(device).total_memory}
        native = modules["modal_latent_formula"]
        forbidden = {"training_calls": 0, "optimizer_steps": 0, "training_mode_true_calls": 0}
        def no_step(*args, **kwargs):
            forbidden["optimizer_steps"] += 1
            raise RuntimeError("optimizer step forbidden in retained inference qualification")
        def no_fit(*args, **kwargs):
            forbidden["training_calls"] += 1
            raise RuntimeError("training forbidden in retained inference qualification")
        original_train = torch.nn.Module.train
        def only_eval(self, mode=True):
            if mode is not False:
                forbidden["training_mode_true_calls"] += 1
                raise RuntimeError("training mode forbidden in retained inference qualification")
            return original_train(self, mode)
        stack.enter_context(patch.object(torch.optim.Adam, "step", no_step))
        stack.enter_context(patch.object(torch.nn.Module, "train", only_eval))
        for module, name in ((native, "train"), (span, "train_decoder"),
                             (modules["legal_span_dimensions"], "train_decoder")):
            if hasattr(module, name):
                stack.enter_context(patch.object(module, name, no_fit))

        def make_lane(family, width, cp, sha, *, bitwise, optimized):
            cancellation.poll()
            caller_lease = None
            if family == "formula" and not bitwise:
                caller_lease = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1,
                    memory_mb=CHILD_RAM, gpu_memory_mb=CHILD_GPU if optimized else 0,
                    unified_memory_mb=CHILD_UNIFIED if optimized else 0, requires_gpu=optimized,
                    parent_lease=root, cancel_event=cancellation, timeout=admission_timeout_seconds,
                    request_id=f"original-formula-{width}-{'cuda' if optimized else 'cpu'}")
                external_children.append(caller_lease)
                factory = lambda: modules["modal_latent_formula_device_inference"].DeviceLatentFormulaDecoder(
                    deepcopy(cp), expected_binding=deepcopy(cp["binding"]), optimized=optimized)
            else:
                cls = (modules["modal_latent_formula_bitwise_device_inference"].BitwiseDeviceLatentFormulaDecoder
                    if family == "formula" else
                    modules["legal_span_device_bitwise_inference"].DeviceBitwiseDimensionalSpanSession
                    if bitwise else batch.DeviceBatchedDimensionalSpanSession)
                factory = lambda: cls(deepcopy(cp), expected_checkpoint_sha256=sha, optimized=optimized,
                    scheduler=scheduler, parent_lease=root, cancel_event=cancellation,
                    admission_timeout_seconds=admission_timeout_seconds, max_seconds=MAX_SECONDS,
                    memory_mb=CHILD_RAM, gpu_memory_mb=CHILD_GPU, unified_memory_mb=CHILD_UNIFIED)
            owner = None
            try:
                owner, constructor = _constructor(torch, factory)
                expected_count = 1 if family == "formula" else 0
                if constructor["adam_constructor_calls"] != expected_count:
                    raise ValueError("actual Adam restoration constructor count differs")
                result["optimizer_constructor_calls"] += constructor["adam_constructor_calls"]
                lane = Lane(owner, family, caller_lease=caller_lease)
                active.append(lane)
                result["owned_children"].append({"lease_id": lane.lease_id, "family": family,
                    "dimension": width, "bitwise": bitwise, "optimized": optimized,
                    "admission": lane.child_lease.to_dict(), "release_observed": False})
                owner = None
                return lane, constructor
            except BaseException:
                if owner is not None and caller_lease is None:
                    owner.close()
                owner = None
                gc.collect()
                torch.cuda.synchronize(device)
                # A failed original constructor can remain in its exception
                # traceback until the outer refusal is rendered. Release that
                # unattached child only after final zero-allocation cleanup.
                raise

        def save_call(label, family, count, lane, inputs, *, timed=False):
            cancellation.poll()
            cpu_rng = torch.random.get_rng_state()
            cuda_rng = torch.cuda.get_rng_state(device)
            torch.cuda.synchronize(device)
            started = time.monotonic()
            report, projected = lane.call(inputs, count)
            torch.cuda.synchronize(device)
            seconds = time.monotonic() - started
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError("positive finite completed call timing required")
            if not torch.equal(cpu_rng, torch.random.get_rng_state()) or not torch.equal(cuda_rng, torch.cuda.get_rng_state(device)):
                raise ValueError("inference changed CPU/CUDA RNG state")
            cancellation.poll()
            decision = _decisions(report, family)
            entry = {"result": evidence.json(label + "-result.json", report),
                     "canonical_projection": evidence.json(label + "-canonical.json", decision),
                     "elapsed_seconds": seconds, "included_in_paired_timing": timed,
                     "cpu_cuda_rng_unchanged": True}
            if family == "formula":
                entry["projected_vectors"] = evidence.json(label + "-projected-vectors.json", projected)
                profile = report["inference_implementation"]
                if profile.get("cuda_executed") is not lane.owner._device.startswith("cuda:"):
                    raise ValueError("actual formula forward CUDA coverage differs")
            else:
                profile = report["execution_profile"]
                if report["cuda_executed"] is not lane.owner._device.startswith("cuda:"):
                    raise ValueError("actual native768 forward CUDA coverage differs")
            if report["training_executed"] is not False:
                raise ValueError("report unexpectedly claims inference training")
            if hasattr(lane.owner, "_reference_anchor"):
                if family == "formula" and profile["profile_id"] != FORMULA_PROFILE:
                    raise ValueError("new formula profile differs")
                if family == "span" and profile["session_profile_id"] != SPAN_PROFILE:
                    raise ValueError("new native768 session profile differs")
                mode = profile["owned_tensor_currentness"]["mode"]
                expected_mode = "cuda_bitwise_single_host_decision" if lane.owner._device.startswith("cuda:") else "cpu_reference_checks"
                if mode != expected_mode:
                    raise ValueError("actual bitwise comparator mode differs")
                anchor = profile["reference_byte_currentness"]
                origin = ("validated_cpu_checkpoint_model_before_reference_clone_and_upload" if family == "formula"
                          else "independently_restored_validated_cpu_checkpoint_model_before_upload")
                if anchor["origin"] != origin or anchor["anchor_identity_checked"] is not True:
                    raise ValueError("new immutable reference anchor missing")
            return entry, decision, projected

        for width in (8, 384, 768):
            cancellation.poll()
            family = "span" if width == 768 else "formula"
            print("FAMILY", family, width, flush=True)
            role = f"span{width}" if family == "span" else f"formula{width}"
            cp = fixture_data[role + "_checkpoint"]
            sha = FIXTURES[role + "_checkpoint"][1]
            if family == "formula":
                saved = fixture_data[role + "_training_inputs"]
                rows = [{"id": f"trained-formula{width}-inference-{index}",
                    "source_text": saved[index % len(saved)]["source_text"],
                    "latent": deepcopy(saved[index % len(saved)]["latent"])} for index in range(32)]
                inputs = {"schema": "retained-trained-formula-inference-inputs/v1", "dimension": width,
                    "rows": rows, "target_fields_excluded": True, "encoder_execution_performed": False}
            else:
                saved = fixture_data["span768_historical_encoder_outputs"]
                sources = fixture_data["span768_sources"]
                if len(sources) != 32 or len(saved["vectors"]) != 32 or len(saved["receipts"]) != 32:
                    raise ValueError("retained native768 source/vector/receipt coverage differs")
                inputs = {"schema": "retained-native768-historical-content-inference-inputs/v1", "dimension": 768,
                    "texts": [row["source_text"] for row in sources], "vectors": deepcopy(saved["vectors"]),
                    "receipts": deepcopy(saved["receipts"]),
                    "receipt_pins": [span.checkpoint_digest(receipt) for receipt in saved["receipts"]],
                    "receipt_pin_authority": "historical_content_only", "encoder_execution_performed": False}
            entry = result["families"][role] = {"family": family, "dimension": width,
                "checkpoint_sha256": sha, "retained_checkpoint_progress": deepcopy(cp["progress"]),
                "checkpoint_optimizer_sha256": hashlib.sha256(_wire(cp["optimizer_state"])).hexdigest(),
                "inputs": evidence.json(role + "-inference-inputs.json", inputs), "lanes": {}, "counts": {}}
            expected_model_raw = _wire(cp["model_state"])
            expected_model_pin = {"sha256": hashlib.sha256(expected_model_raw).hexdigest(),
                                  "bytes": len(expected_model_raw)}
            entry["retained_checkpoint_model_pin"] = expected_model_pin
            references, reference_numeric = {}, {}
            for bitwise in (False, True):
                label = "bitwise_cpu_opt_out" if bitwise else "original_cpu_reference"
                lane, constructor = make_lane(family, width, cp, sha, bitwise=bitwise, optimized=False)
                lane_result = entry["lanes"][label] = {"constructor": constructor, "profile": lane.describe(),
                    "state_before": _state_pin(lane.owner, family), "counts": {}}
                if lane_result["state_before"] != expected_model_pin:
                    raise ValueError("restored CPU tensors differ from retained trained checkpoint")
                for count in COUNTS:
                    observed, decision, projected = save_call(f"{role}-{label}-{count}", family, count, lane, inputs)
                    lane_result["counts"][str(count)] = observed
                    if bitwise:
                        if _wire(decision) != _wire(references[count]):
                            raise ValueError("new CPU opt-out canonical decisions differ")
                        observed["canonical_matches_original_cpu"] = True
                        if family == "formula":
                            observed["complete_projection_max_abs_error"] = _numeric_error(reference_numeric[count], projected)
                    else:
                        references[count] = decision
                        if family == "formula":
                            reference_numeric[count] = projected
                    if family == "span":
                        numeric, scope = _span_logits(torch, span, batch, lane, inputs, count, singleton=True)
                        observed["complete_four_logits"] = evidence.json(f"{role}-{label}-{count}-logits.json", numeric)
                        observed["numeric_snapshot_scope"] = scope
                        if bitwise:
                            observed["four_logit_max_abs_errors"] = _four_errors(reference_numeric[count], numeric)
                        else:
                            reference_numeric[count] = numeric
                lane_result["state_after"] = _state_pin(lane.owner, family)
                if lane_result["state_before"] != lane_result["state_after"]:
                    raise ValueError("CPU inference changed checkpoint model tensors")
                if _wire(lane.owner._checkpoint) != _wire(cp):
                    raise ValueError("CPU inference changed checkpoint/Adam content")
                lane_result["checkpoint_and_adam_unchanged"] = True
                lane.close(torch, device)
                lane = None
            gpu_lanes = {}
            for bitwise, label in ((False, "original_cuda"), (True, "bitwise_cuda")):
                lane, constructor = make_lane(family, width, cp, sha, bitwise=bitwise, optimized=True)
                gpu_lanes[label] = lane
                entry["lanes"][label] = {"constructor": constructor, "profile": lane.describe(),
                    "state_before": _state_pin(lane.owner, family), "counts": {}}
                if entry["lanes"][label]["state_before"] != expected_model_pin:
                    raise ValueError("restored CUDA tensors differ from retained trained checkpoint")
                warmup, decision, projected = save_call(f"{role}-{label}-warmup", family, 32, lane, inputs)
                if _wire(decision) != _wire(references[32]):
                    raise ValueError("warmup canonical decisions differ from CPU")
                warmup["canonical_matches_original_cpu"] = True
                if family == "formula":
                    warmup["complete_projection_max_abs_error"] = _numeric_error(reference_numeric[32], projected)
                entry["lanes"][label]["warmup"] = warmup
            entry["paired_admission"] = {"both_gpu_children_live": all(not x.child_lease.released for x in gpu_lanes.values()),
                "resources": scheduler.snapshot(), "child_leases": {k: v.child_lease.to_dict() for k, v in gpu_lanes.items()}}
            if not entry["paired_admission"]["both_gpu_children_live"]:
                raise ValueError("paired CUDA children must be admitted together")
            for count in COUNTS:
                trials, samples = [], {label: [] for label in gpu_lanes}
                for trial in range(PAIRS):
                    order = ("original_cuda", "bitwise_cuda") if trial % 2 == 0 else ("bitwise_cuda", "original_cuda")
                    observed_trial = {"trial": trial, "order": list(order), "observations": {}}
                    trials.append(observed_trial)
                    for label in order:
                        observed, decision, projected = save_call(f"{role}-{count}-pair{trial:02d}-{label}",
                            family, count, gpu_lanes[label], inputs, timed=True)
                        observed_trial["observations"][label] = observed
                        if _wire(decision) != _wire(references[count]):
                            raise ValueError("complete timed canonical decisions differ from CPU")
                        observed["canonical_matches_original_cpu"] = True
                        if family == "formula":
                            observed["complete_projection_max_abs_error"] = _numeric_error(reference_numeric[count], projected)
                        samples[label].append(observed["elapsed_seconds"])
                medians = {label: statistics.median(values) for label, values in samples.items()}
                count_result = entry["counts"][str(count)] = {"trials": trials, "samples_seconds": samples,
                    "median_seconds": medians, "sample_count_each_lane": PAIRS, "first_position_each_lane": PAIRS // 2,
                    "median_original_over_bitwise_ratio": medians["original_cuda"] / medians["bitwise_cuda"],
                    "paired_original_over_bitwise_ratios": [t["observations"]["original_cuda"]["elapsed_seconds"] /
                        t["observations"]["bitwise_cuda"]["elapsed_seconds"] for t in trials],
                    "interpretation": "descriptive_same_fixture_complete_call_measurements_no_universal_speedup_claim"}
                count_result["raw_timing_evidence"] = evidence.json(f"{role}-{count}-raw-paired-timings.json",
                    {"trials": trials, "samples_seconds": samples, "median_seconds": medians})
                if family == "span":
                    for label, lane in gpu_lanes.items():
                        cancellation.poll()
                        numeric, scope = _span_logits(torch, span, batch, lane, inputs, count, singleton=False)
                        entry["lanes"][label]["counts"][str(count)] = {
                            "complete_four_logits": evidence.json(f"{role}-{label}-{count}-logits.json", numeric),
                            "numeric_snapshot_scope": scope,
                            "four_logit_max_abs_errors": _four_errors(reference_numeric[count], numeric)}
            entry["new_cuda_controls"] = _new_controls(torch, gpu_lanes["bitwise_cuda"], inputs, cancellation)
            for label, lane in gpu_lanes.items():
                lane_result = entry["lanes"][label]
                lane_result["state_after"] = _state_pin(lane.owner, family)
                if lane_result["state_before"] != lane_result["state_after"]:
                    raise ValueError("CUDA inference/controls changed checkpoint model tensors")
                current_checkpoint = lane.owner._checkpoint
                if _wire(current_checkpoint) != _wire(cp):
                    raise ValueError("inference/controls changed checkpoint/Adam content")
                lane_result["checkpoint_and_adam_unchanged"] = True
                lane.close(torch, device)
            gpu_lanes.clear()
            lane = None
            entry["numerical_and_canonical_qualified"] = True
            cancellation.poll()
        result.update(forbidden)
        if any(forbidden.values()):
            raise ValueError("inference attempted training/optimizer step")
        result["precision_policy_after"] = resident._cuda_float32_policy(torch)
        if policy_before != result["precision_policy_after"]:
            raise ValueError("ambient precision policy changed")
        result["precision_policy_unchanged"] = True
        result["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
        result["gpu_peak_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
        if result["gpu_peak_allocated_bytes"] > ROOT_GPU * 1024**2:
            raise ValueError("actual worker peak CUDA allocations exceeded admitted root budget")
        result["root_gpu_allocation_budget_observed"] = True
        result["qualified"] = True
        result["complete_call_measurements_qualified"] = True
    except BaseException as error:
        result["qualified"] = False
        result["complete_call_measurements_qualified"] = False
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
        try:
            stack.close()
        except BaseException as error:
            safe_close = False
            result["interception_restore_error"] = {"type": type(error).__name__, "detail": str(error)}
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
                    child.release()
        try:
            result["currentness_after"] = []
            for pin in staged:
                after = _pin(pin["current"]["path"])
                if after != pin["current"]:
                    raise ValueError("retained source/configuration/checkpoint/input bytes changed")
                result["currentness_after"].append(after)
            result["retained_sources_fixtures_configuration_unchanged"] = True
        except BaseException as error:
            result["currentness_error"] = {"type": type(error).__name__, "detail": str(error)}
            result["qualified"] = False
            result["complete_call_measurements_qualified"] = False
        if torch is not None and old_threads is not None:
            torch.set_num_threads(old_threads)
        for record in result["owned_children"]:
            matching = [lane for lane in active if lane.lease_id == record["lease_id"]]
            record["release_observed"] = len(matching) == 1 and matching[0].child_lease.released
        if root is not None:
            if safe_close and all(record["release_observed"] for record in result["owned_children"]):
                root.release()
            result["root_release_observed"] = root.released
        else:
            result["root_release_observed"] = False
        if scheduler is not None:
            result["resources_after"] = scheduler.snapshot()
        if not safe_close or (root is not None and not root.released):
            result["qualified"] = False
            result["complete_call_measurements_qualified"] = False
        result["safe_owned_cleanup_established"] = safe_close
        result["elapsed_seconds_total"] = time.monotonic() - began
        result["elapsed_seconds_after_root_admission"] = (time.monotonic() - admitted if root is not None else None)
        result["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["evidence_files_except_result"] = list(evidence.files)
        result["evidence_bytes_except_result"] = evidence.bytes
        result["evidence_limits"] = {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES, "result_included_in_limits": True}
        evidence.json("result.json", result, final=True)
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
