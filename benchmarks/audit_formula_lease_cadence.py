"""Closed ordinary-byte reader for formula lease cadence candidate evidence.

No tensor library or producer code is imported. Qualification means that the
externally pinned finite archive agrees with its source, input, checkpoint,
numeric and timing receipts; it grants no execution or proof authority.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import statistics
import struct

SCHEMA = "retained-trained-formula-lease-cadence-qualification/v1"
REVIEW_SCHEMA = "formula-lease-cadence-archive-review/v1"
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 1024, 8 * 1024**2, 64 * 1024**2
MAX_DEPTH, MAX_NODES, MAX_DIRECTORIES = 64, 2_000_000, 2
SHA = re.compile(r"[0-9a-f]{64}\Z")
COUNTS, ROUTES = (1, 16, 32), ("original", "bitwise_v2", "lease_cadence")
CPU_LANES = ("original_cpu_reference", "bitwise_v2_cpu_opt_out", "lease_cadence_cpu_opt_out")
CUDA_LANES = ("original_cuda", "bitwise_v2_cuda", "lease_cadence_cuda")
ORDERS = (("original_cuda", "bitwise_v2_cuda", "lease_cadence_cuda"),
          ("original_cuda", "lease_cadence_cuda", "bitwise_v2_cuda"),
          ("bitwise_v2_cuda", "original_cuda", "lease_cadence_cuda"),
          ("bitwise_v2_cuda", "lease_cadence_cuda", "original_cuda"),
          ("lease_cadence_cuda", "original_cuda", "bitwise_v2_cuda"),
          ("lease_cadence_cuda", "bitwise_v2_cuda", "original_cuda"))
PAIRS = 12
CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
FIXTURES = {
    "formula8_checkpoint": "09558c8db4455bf3caad1f287cea9448da47393fe0fae1c5c140f0ff00e0e466",
    "formula384_checkpoint": "7d8d0e60f7d644bed06e0a48ffc82c014c9ed697d89b9cdc2e4a5d55863885ce",
    "formula8_training_inputs": "212b4817fd074e9c3f9c76c53485774ad44083b65c691938bb80e2962723a30c",
    "formula384_training_inputs": "febf18138dbe1bc8480f06d43586a35453db55c3d8493c03a57ed848dab6093f",
}
# The producer and new coordinator pins are filled only after their owners hold
# the new sources. Old qualified producers/readers are never modified.
FIXED_SOURCES = {
    "benchmark": "ed3bbfc3b20bfab34d58a8dc76a0a858a31cbd28e3e1d1183a8d54bcd18848a1",
    "coordinator_helpers": "e8b9634c6e905d0c63e7eba067e86a034796537f08d758d548a1d22123190ed8",
    "ordinary_reader_helpers": "f38e215b5052242b682ad2e6a5b2e2631588a8f98957c75e8b3f3137a9475c53",
    "authenticated_lease_heartbeat": "584ddf7f8274481940ff48648da5947d08ba42534cf46157da3591a4ac634b30",
    "modal_latent_formula_lease_heartbeat_device_inference": "d367abb349d909247b334424445cd690486170e833dcac4d26ec434e7b0b804f",
    "cg2_harness_helpers": "29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110",
    "cleanup_helper": "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c",
    "resource_scheduler": "f156511991e33d3b4ba523c3c5080ea30d0a53ad8a4dbcccea0487432679a9aa",
    "modal_latent_formula_bitwise_device_inference": "5b5631eb1cf779ea8b6fcf3073d074355f52ef8c74adea84fc595421dea85089",
    "owned_tensor_bitwise_guard": "6bf14ce3b99ff3ce6e3707b6e9d232e10bd92fbb980f29187687513adc83ab34",
    "modal_latent_formula_bitwise_device_inference_v2": "ebc7f8242ec3a4852be4c025b4ef818bc48e74add7634935ec403e1bd3c6dfb9",
}
SOURCE_ROLES = frozenset({"benchmark", "coordinator_helpers", "ordinary_reader_helpers", "authenticated_lease_heartbeat",
    "modal_latent_formula_lease_heartbeat_device_inference", "cg2_harness_helpers", "cleanup_helper", "resource_scheduler", "modal_latent_formula",
    "modal_latent_formula_inference", "modal_latent_formula_device_inference", "modal_latent_formula_bitwise_device_inference",
    "modal_latent_formula_bitwise_device_inference_v2", "owned_tensor_value_guard", "owned_tensor_bitwise_guard",
    "checkpoint_content_guard", "runtime_telemetry", "proof_resource_safety", "legal_formula_codec",
    "legal_ir_grammar_decoder", "legal_ir_family_evaluator", "snapshot_evaluator", "tree_pin", "canonical_contracts", "cid_utils"})
BASELINE_SHA = "d178edbced905e3b55d36a067f8f797aa9a95a612f80162e6aaf6c64f9f26f79"
AUTHORITY_FALSE = frozenset({
    "qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
    "semantic_correctness_verified", "promotion_performed", "publication_performed", "lake_executed",
    "source_semantics_verified", "execution_attestation", "production_admission", "production_qualified",
    "native_cuda_qualified", "performance_qualified", "semantic_qualification", "kernel_resource_enforcement",
    "training_executed", "target_access", "teacher_forcing", "native_encoder_origin_authenticated",
    "fresh_encoder_execution_qualified", "universal_speedup_claimed", "foreign_process_actions",
    "trusted_native_owner_verified", "native_leanstral_encoder_available", "native_leanstral_head_qualified",
})


def _require(condition, detail):
    if not condition:
        raise ValueError(detail)


def _integer(value, minimum=0, maximum=2**63 - 1):
    _require(type(value) is int and minimum <= value <= maximum, "bounded plain integer required")
    return value


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _json(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_FILE_BYTES, "bounded JSON bytes required")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result
    def finite_float(value):
        parsed = float(value)
        _require(math.isfinite(parsed), "nonfinite JSON exponent")
        return parsed
    def bounded_int(value):
        _require(len(value) <= 80, "bounded JSON integer text required")
        return int(value)
    value = json.loads(raw, object_pairs_hook=unique, parse_float=finite_float, parse_int=bounded_int,
                       parse_constant=lambda item: (_ for _ in ()).throw(ValueError("nonfinite JSON constant")))
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(nodes <= MAX_NODES and depth <= MAX_DEPTH, "bounded JSON depth/node count exceeded")
        _require(type(item) in (dict, list, str, int, float, bool, type(None)), "plain JSON types required")
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "plain JSON keys required")
            pending.extend((part, depth + 1) for part in item.values())
        elif type(item) is list:
            pending.extend((part, depth + 1) for part in item)
        elif type(item) is float:
            _require(math.isfinite(item), "finite JSON scalar required")
    return value


def _authority(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            for name, child in item.items():
                if name in AUTHORITY_FALSE:
                    _require(child is False, "nested inference authority must be plain False: " + name)
                pending.append(child)
        elif type(item) is list:
            pending.extend(item)


def _directory_fd(path):
    path = Path(path).absolute()
    _require(".." not in path.parts and path.parts[0] == "/", "canonical absolute directory required")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _ordinary(info, *, readonly):
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= MAX_FILE_BYTES,
             "bounded single-link ordinary leaf required")
    if readonly:
        _require(info.st_mode & 0o222 == 0, "retained ordinary leaf must be read-only")


def _read(path, *, readonly=True):
    path = Path(path).absolute()
    _require(".." not in path.parts and path.name not in ("", ".", ".."), "canonical leaf path required")
    parent = _directory_fd(path.parent)
    try:
        parent_identity = os.fstat(parent)
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _ordinary(before, readonly=readonly)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _ordinary(opened, readonly=readonly)
            _require(_identity(opened) == _identity(before), "opened leaf identity changed")
            raw = stream.read(MAX_FILE_BYTES + 1)
            after_open = os.fstat(stream.fileno())
        after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        current_parent = _directory_fd(path.parent)
        try:
            latest = os.fstat(current_parent)
            _require((latest.st_dev, latest.st_ino) == (parent_identity.st_dev, parent_identity.st_ino),
                     "ordinary input parent identity changed")
        finally:
            os.close(current_parent)
        _require(_identity(before) == _identity(after_open) == _identity(after) and len(raw) == before.st_size,
                 "ordinary input changed during read")
        return raw
    finally:
        os.close(parent)


def _pin(path, raw):
    return {"path": str(Path(path).absolute()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _pin_shape(pin):
    _require(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
             and type(pin["path"]) is str and Path(pin["path"]).is_absolute()
             and ".." not in Path(pin["path"]).parts and type(pin["sha256"]) is str
             and SHA.fullmatch(pin["sha256"]) is not None, "exact canonical artifact pin required")
    _integer(pin["bytes"], 1, MAX_FILE_BYTES)


def _inventory(root):
    root, files, entries, total = Path(root).absolute(), {}, 0, 0
    descriptor = _directory_fd(root)
    try:
        root_identity = os.fstat(descriptor)
        directories = set()
        with os.scandir(descriptor) as listing:
            for item in listing:
                entries += 1
                _require(entries <= MAX_FILES + MAX_DIRECTORIES, "bounded archive entries exceeded before collection")
                info = item.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    _require(item.name in {"producers", "fixtures"} and item.name not in directories,
                             "unknown archive directory/depth")
                    directories.add(item.name)
                    child = os.open(item.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                    dir_fd=descriptor)
                    try:
                        with os.scandir(child) as children:
                            for leaf in children:
                                entries += 1
                                _require(entries <= MAX_FILES + MAX_DIRECTORIES, "bounded archive entries exceeded before collection")
                                leaf_info = leaf.stat(follow_symlinks=False)
                                _ordinary(leaf_info, readonly=True)
                                total += leaf_info.st_size
                                _require(len(files) < MAX_FILES and total <= MAX_TOTAL_BYTES, "bounded archive files/bytes exceeded")
                                files[str(root / item.name / leaf.name)] = _identity(leaf_info)
                    finally:
                        os.close(child)
                else:
                    _ordinary(info, readonly=True)
                    total += info.st_size
                    _require(len(files) < MAX_FILES and total <= MAX_TOTAL_BYTES, "bounded archive files/bytes exceeded")
                    files[str(root / item.name)] = _identity(info)
        current = _directory_fd(root)
        try:
            latest = os.fstat(current)
            _require((latest.st_dev, latest.st_ino) == (root_identity.st_dev, root_identity.st_ino), "archive root changed")
        finally:
            os.close(current)
        return files
    finally:
        os.close(descriptor)


class Archive:
    def __init__(self, root, result):
        self.root, self.pins, self.used, self.panels = Path(root).absolute(), {}, set(), set()
        self.inventory = _inventory(self.root)
        entries = result["evidence_files_except_result"]
        _require(type(entries) is list and len(entries) < MAX_FILES, "bounded exact manifest required")
        total = 0
        for pin in entries:
            _pin_shape(pin)
            path = Path(pin["path"])
            _require(path.is_relative_to(self.root) and path != self.root / "result.json"
                     and str(path) not in self.pins, "contained unique artifact required")
            total += pin["bytes"]
            _require(total <= MAX_TOTAL_BYTES, "manifest declared byte bound exceeded before read")
            _require(_pin(path, _read(path)) == pin, "retained bytes/hash mismatch")
            self.pins[str(path)] = pin
        _require(_integer(result["evidence_bytes_except_result"]) == total, "manifest byte arithmetic differs")
        _require(set(self.inventory) == set(self.pins) | {str(self.root / "result.json")}, "missing/unmanifested artifact")
        _require(_wire(result["evidence_limits"]) == _wire({"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES, "result_included_in_limits": True}), "archive limits differ")

    def raw(self, pin, *, name=None, unique=False):
        _pin_shape(pin)
        _require(self.pins.get(pin["path"]) == pin, "artifact not in exact retained manifest")
        if name is not None:
            _require(pin["path"] == str(self.root / name), "artifact filename/route/count/trial identity differs")
        if unique:
            _require(pin["path"] not in self.panels, "panel artifact reused by another public call")
            self.panels.add(pin["path"])
        raw = _read(pin["path"])
        _require(_pin(pin["path"], raw) == pin, "retained bytes changed")
        self.used.add(pin["path"])
        return raw

    def value(self, pin, **kwargs):
        return _json(self.raw(pin, **kwargs))

    def finish(self, *, partial=False):
        leftovers = []
        if partial:
            pattern = re.compile(r"formula(?:8|384)-(?:"
                r"(?:original_cpu_reference|(?:bitwise_v2|lease_cadence)_cpu_opt_out)-(?:1|16|32)-(?:result|projected-vectors)|"
                r"(?:original_cuda|(?:bitwise_v2|lease_cadence)_cuda)-warmup-(?:result|projected-vectors)|"
                r"(?:1|16|32)-trial(?:0[0-9]|1[01])-(?:original_cuda|(?:bitwise_v2|lease_cadence)_cuda)-(?:result|projected-vectors)|"
                r"(?:1|16|32)-raw-three-way-timings)\.json\Z")
            for path in sorted(set(self.pins) - self.used):
                _require(Path(path).parent == self.root and pattern.fullmatch(Path(path).name) is not None,
                         "unjoined evidence is not a bounded failed partial panel")
                value = _json(self.raw(self.pins[path]))
                _authority(value)
                leftovers.append(self.pins[path])
        _require(self.used == set(self.pins), "unjoined archive evidence")
        _require(_inventory(self.root) == self.inventory, "archive inventory/identity changed")
        for pin in self.pins.values():
            _require(_pin(pin["path"], _read(pin["path"])) == pin, "archive changed during audit")
        return leftovers


def _positive(value):
    _require(type(value) is float and math.isfinite(value) and value > 0, "positive finite plain-float timing required")
    return value


def _float32(value):
    _require(type(value) is float and math.isfinite(value), "finite plain-float float32 scalar required")
    raw = struct.pack("<f", value)
    _require(struct.unpack("<f", raw)[0] == value, "scalar is not genuinely float32")
    return raw


def _shape(value, dimensions):
    if not dimensions:
        _float32(value)
        return
    _require(type(value) is list and len(value) == dimensions[0], "complete numeric shape differs")
    for child in value:
        _shape(child, dimensions[1:])


def _input_shape(value, dimensions):
    if not dimensions:
        _require(type(value) in (int, float) and math.isfinite(value), "finite plain input scalar required")
        _round32(value)
        return
    _require(type(value) is list and len(value) == dimensions[0], "complete input shape differs")
    for child in value:
        _input_shape(child, dimensions[1:])


def _numeric(left, right):
    if type(left) is list:
        _require(type(right) is list and len(left) == len(right) > 0, "complete numeric parity shape differs")
        return max(_numeric(a, b) for a, b in zip(left, right))
    _float32(left)
    _float32(right)
    error = abs(left - right)
    _require(error <= 5e-5, "complete numeric absolute5e-5 parity exceeded")
    return error


def _model_bytes(checkpoint):
    digest, size = hashlib.sha256(), 0
    def append(value):
        nonlocal size
        if type(value) is list:
            _require(len(value) > 0, "nonempty tensor shape required")
            for child in value:
                append(child)
        else:
            digest.update(_float32(value))
            size += 4
    _require(type(checkpoint["model_state"]) is dict and len(checkpoint["model_state"]) == 13,
             "exact native formula parameter inventory required")
    for name in sorted(checkpoint["model_state"]):
        append(checkpoint["model_state"][name])
    return {"sha256": digest.hexdigest(), "bytes": size, "tensor_count": 13}


def _decisions(report):
    result = deepcopy(report)
    result.pop("inference_implementation", None)
    for row in result["rows"]:
        if "minimum_decision_logit_margin" in row:
            margin = row["minimum_decision_logit_margin"]
            _require(margin is None or type(margin) is float and math.isfinite(margin), "finite decision margin required")
            row["minimum_decision_logit_margin"] = (None if margin is None else
                {"known_finite_numeric_diagnostic_value_excluded": True})
    return result


def _round32(value):
    _require(math.isfinite(value), "finite projection algebra required")
    result = struct.unpack("<f", struct.pack("<f", value))[0]
    _require(math.isfinite(result), "projection algebra overflows float32")
    return result


def _projection_algebra(checkpoint, latents):
    """Reconstruct only bounded projection arithmetic; no model code executes."""
    state, width = checkpoint["model_state"], _integer(checkpoint["binding"]["dimension"], 8, 384)
    _require(width in (8, 384) and type(latents) is list and 1 <= len(latents) <= 32,
             "exact bounded formula projection input required")
    down, down_bias = state["projection_down.weight"], state["projection_down.bias"]
    up, up_bias = state["projection_up.weight"], state["projection_up.bias"]
    hidden = len(down_bias)
    _integer(hidden, 1, 128)
    _shape(down, (hidden, width))
    _shape(down_bias, (hidden,))
    _shape(up, (width, hidden))
    _shape(up_bias, (width,))
    output = []
    for latent in latents:
        _input_shape(latent, (width,))
        latent = [_round32(value) for value in latent]
        reduced = [_round32(math.tanh(_round32(math.fsum(a * b for a, b in zip(row, latent)) + bias)))
                   for row, bias in zip(down, down_bias)]
        restored = [_round32(math.fsum(a * b for a, b in zip(row, reduced)) + bias)
                    for row, bias in zip(up, up_bias)]
        output.append([_round32(a + b) for a, b in zip(latent, restored)])
    return output


def _inputs(archive, pin, role, checkpoint, training_rows):
    inputs = archive.value(pin, name=role + "-inference-inputs.json")
    width = checkpoint["binding"]["dimension"]
    _require(inputs["schema"] == "retained-trained-formula-inference-inputs/v1"
             and _integer(inputs["dimension"]) == width and inputs["encoder_execution_performed"] is False
             and inputs["target_fields_excluded"] is True, "formula input scope differs")
    _require(type(training_rows) is list and 0 < len(training_rows) <= 4096, "bounded retained training input rows required")
    expected = [{"id": f"trained-formula{width}-inference-{index}",
                 "source_text": training_rows[index % len(training_rows)]["source_text"],
                 "latent": training_rows[index % len(training_rows)]["latent"]} for index in range(32)]
    _require(_wire(inputs["rows"]) == _wire(expected), "stripped inference input/retained fixture join differs")
    for row in inputs["rows"]:
        _require(set(row) == {"id", "source_text", "latent"} and type(row["source_text"]) is str
                 and 0 < len(row["source_text"]) <= 8192, "closed target-free source input required")
        _input_shape(row["latent"], (width,))
    return inputs


def _row_inputs(report, inputs, count, checkpoint):
    _require(_wire(report["binding"]) == _wire(checkpoint["binding"]), "public checkpoint binding differs")
    _require(type(report["rows"]) is list and len(report["rows"]) == count, "public input row count differs")
    decoded = 0
    for returned, expected in zip(report["rows"], inputs["rows"][:count]):
        _require(returned["id"] == expected["id"] and returned["projection_id"] == checkpoint["projection_id"]
                 and returned["source_sha256"] == hashlib.sha256(expected["source_text"].encode()).hexdigest()
                 and returned["latent_sha256"] == hashlib.sha256(_wire(expected["latent"])).hexdigest(),
                 "public source/latent/id/projection join differs")
        _require(returned["status"] in ("decoded", "abstained")
                 and returned["syntax_scope"] == "canonical_rule_schema_and_decoder_grammar",
                 "public formula decision scope differs")
        margin = returned["minimum_decision_logit_margin"]
        if returned["status"] == "decoded":
            _require(type(margin) is float and math.isfinite(margin) and margin > 1e-7,
                     "decoded formula requires finite positive decision margin")
            _require(type(returned["generated_token_ids"]) is list and 1 <= len(returned["generated_token_ids"]) <= 256
                     and all(type(value) is int and value >= 0 for value in returned["generated_token_ids"]),
                     "complete finite generated token sequence required")
        else:
            _require(margin is None or type(margin) is float and math.isfinite(margin), "finite abstention margin required")
        decoded += returned["status"] == "decoded"
    _require(_integer(report["decoded_count"]) == decoded and report["status"] ==
             ("decoded" if decoded == count else "partial" if decoded else "abstained"), "public status/decoded arithmetic differs")


def _source_profile(profile, label, checkpoint, source_shas, byte_plan, *, public=True, lease=None, cuda_device="cuda:0"):
    cuda, bitwise, version2 = label in CUDA_LANES, not label.startswith("original"), not label.startswith("original")
    lease_cadence = label.startswith("lease_cadence")
    width = checkpoint["binding"]["dimension"]
    _authority(profile)
    _require(_integer(profile["dimension"]) == width and profile["optimized"] is cuda
             and profile["dtype"] == "float32" and profile["cuda_selected"] is cuda
             and (profile["device"] == cuda_device if cuda else profile["device"] == "cpu"),
             "public route/device/dtype/forward identity differs")
    if public:
        _require(profile["cuda_executed"] is cuda and profile["actual_forward_executed"] is True,
                 "actual formula device/forward receipt differs")
        calls = profile["actual_forward_calls"]
        _require(type(calls) is dict and set(calls) == {"projection_down", "projection_up", "output"}
                 and all(type(value) is int and value > 0 for value in calls.values()), "actual formula forward calls missing")
    inherited = profile["inherited_device_implementation"] if bitwise else profile
    _require(inherited["schema"] == "modal-latent-formula-device-inference/v1"
             and inherited["source_sha256"] == source_shas["modal_latent_formula_device_inference"]
             and inherited["parent"]["schema"] == "modal-latent-formula-inference-implementation/v1"
             and inherited["parent"]["source_sha256"] == source_shas["modal_latent_formula_inference"],
             "original formula source/callee binding differs")
    files = checkpoint["implementation"]["files"]
    _require(all(files[name + ".py"] == source_shas[name] for name in
        ("modal_latent_formula", "legal_formula_codec", "legal_ir_grammar_decoder", "canonical_contracts", "tree_pin")),
        "checkpoint native producer source inventory differs")
    if not bitwise:
        return
    source_role = ("modal_latent_formula_lease_heartbeat_device_inference" if lease_cadence else
                   "modal_latent_formula_bitwise_device_inference_v2")
    _require(profile["schema"] == ("modal-latent-formula-lease-heartbeat-device-implementation/v1" if lease_cadence else
             "modal-latent-formula-bitwise-device-implementation/v2")
             and profile["profile_id"] == ("modal-latent-formula-bitwise-owned-device-lease-heartbeat-float32/v1" if lease_cadence else
                 "modal-latent-formula-bitwise-owned-device-float32/" + ("v2" if version2 else "v1"))
             and profile["source_sha256"] == source_shas[source_role]
             and profile["native_checkpoint_implementation"] == checkpoint["implementation"]
             and profile["checkpoint_guard_source_sha256"] == source_shas["checkpoint_content_guard"]
             and profile["resource_scheduler_source_sha256"] == source_shas["resource_scheduler"]
             and profile["bitwise_guard_implementation"]["source_sha256"] == source_shas["owned_tensor_bitwise_guard"]
             and profile["lineage_id"] == checkpoint["binding"]["lineage_id"]
             and profile["adam_restoration_performed"] is True and _integer(profile["adam_restore_count"]) == 1
             and _integer(profile["optimizer_steps_executed"]) == 0, "bitwise formula source/profile/restoration binding differs")
    if version2:
        _require(profile["inherited_owner_source_sha256"] == source_shas["modal_latent_formula_bitwise_device_inference"]
                 and profile["source_verification_success_cached"] is False
                 and profile["boundary_consolidation_performed"] is False
                 and profile["duplicate_native_source_verification_in_boundary"] is False
                 and profile["checkpoint_matches_method_identity_checked"] is True
                 and profile["owned_content_guard_object_and_snapshot_identities_checked"] is True
                 and profile["owned_content_guard_identity_policy"] == "fixed_after_source_bound_constructor_guard_creation"
                 and _integer(profile["native_source_verifications_per_boundary"]) == 1
                 and profile["outer_discarded_receipt_construction_avoided"] is True,
                 "v2 coordinator uncached source-boundary receipt differs")
        if public:
            _require(profile["public_receipt_boundary_scope"] ==
                "inherited_exit_receipt_with_fresh_outer_exit_guard_and_no_outer_receipt", "public v2 boundary receipt scope differs")
    if lease_cadence:
        _lease_heartbeat_profile(profile, source_shas, public=public)
    if lease is not None:
        _require(_wire(profile["resource_lease"]) == _wire(lease), "public/constructor child lease receipt differs")
    guard, anchor = profile["owned_tensor_currentness"], profile["reference_byte_currentness"]
    _require(guard["schema"] == "owned-tensor-bitwise-value-guard/v1"
             and guard["mode"] == ("cuda_bitwise_single_host_decision" if cuda else "cpu_reference_checks")
             and guard["implementation"]["source_sha256"] == source_shas["owned_tensor_bitwise_guard"]
             and guard["implementation"]["comparison"] == "finite-float32-exact-bits-with-reference-finiteness/v1"
             and all(guard[key] is True for key in ("all_current_values_checked", "finite_values_checked", "signed_zero_checked"))
             and _integer(guard["tensor_count"]) == byte_plan["tensor_count"]
             and _integer(guard["state_and_reference_bytes"]) == 2 * byte_plan["bytes"]
             and guard["comparison_device"] == profile["device"], "complete tensor bit-currentness receipt differs")
    _require(anchor["schema"] == "modal-formula-owned-reference-byte-currentness/v1"
             and anchor["checkpoint_sha256"] == hashlib.sha256(_wire(checkpoint)).hexdigest()
             and anchor["origin"] == "validated_cpu_checkpoint_model_before_reference_clone_and_upload"
             and anchor["anchor_sha256"] == byte_plan["sha256"] and _integer(anchor["reference_bytes"]) == byte_plan["bytes"]
             and anchor["comparison"] == "complete_immutable_float32_bytes_including_signed_zero"
             and anchor["anchor_identity_checked"] is True and anchor["independent_of_mutable_reference_storage"] is True
             and anchor["metadata_and_reservation_checked_before_allocation"] is True
             and anchor["reference_device"] == profile["device"]
             and _integer(anchor["cpu_byte_materializations"]) == 1
             and _integer(anchor["device_to_cpu_reference_transfers"]) == int(cuda),
             "independent checkpoint float32 byte anchor differs")


def _lease_observation(value, source_shas, *, phase, candidate, public_call=False):
    _authority(value)
    _require(type(value) is dict and value["schema"] == "source-bound-lease-cadence-call-observation/v1"
             and value["scope"] == "main_thread_helper_check_only_no_background_or_timed_interval_attestation"
             and value["source_role"] == "authenticated_lease_heartbeat"
             and value["source_sha256"] == source_shas["authenticated_lease_heartbeat"]
             and value["phase"] == phase and _integer(value["thread_id"], 1) > 0
             and value["generator_segment_scope"] ==
                 "call_events_include_contextmanager_resume_segments_not_transaction_count"
             and value["background_threads_observed"] is False and value["timed_cuda_interval_observed"] is False
             and value["profile_restored"] is True,
             "untimed source-bound lease helper observation scope differs")
    checks = value["checks"]
    _require(type(checks) is list and len(checks) <= 64, "bounded lease helper checks required")
    counts = {"valid_non_due": 0, "renewed_due": 0, "refused": 0}
    for index, row in enumerate(checks):
        _require(type(row) is dict and set(row) == {"index", "outcome", "read_lock_segments", "persist_requested_lock_segments",
                                                   "fsync_calls", "replace_calls"}
                 and _integer(row["index"]) == index and row["outcome"] in counts,
                 "lease helper check identity/outcome differs")
        for key in ("read_lock_segments", "persist_requested_lock_segments", "fsync_calls", "replace_calls"):
            _integer(row[key], 0, 1024)
        if row["outcome"] == "valid_non_due":
            _require(row["fsync_calls"] == row["replace_calls"] == 0,
                     "valid non-due helper observation reports a persistent mutation")
        counts[row["outcome"]] += 1
    _require(_integer(value["check_count"]) == len(checks)
             and _integer(value["valid_non_due_count"]) == counts["valid_non_due"]
             and _integer(value["due_renewal_count"]) == counts["renewed_due"]
             and _integer(value["refusal_count"]) == counts["refused"], "lease helper observation arithmetic differs")
    if not candidate:
        _require(checks == [], "noncandidate route claims new lease helper calls")
    if public_call and candidate:
        _require(len(checks) == 4 and counts["refused"] == 0, "four fresh successful public lease checks required")
    return {"check_count": len(checks), "valid_non_due_count": counts["valid_non_due"],
            "due_renewal_count": counts["renewed_due"], "refusal_count": counts["refused"],
            "background_and_timed_interval_attestation": False}


def _lease_heartbeat_implementation(value, source_shas):
    expected = {"schema": "authenticated-lease-heartbeat-implementation/v1",
        "source_sha256": source_shas["authenticated_lease_heartbeat"],
        "scheduler_source_sha256": source_shas["resource_scheduler"],
        "comparison": "fresh_locked_authenticated_lease_and_complete_current_ancestry",
        "nondue_state_lock_persist": False, "renewal_fraction_default": 1 / 3,
        "renewal_fraction_maximum": .5, "max_ancestors": 4096,
        "due_policy": "shared_heartbeat_at_plus_fixed_initial_TTL_times_fraction",
        "due_writer_reauthenticates_and_rechecks_expiry_cancellation_ancestry_and_cadence": True,
        "helper_mutation_scope": "own_lease_heartbeat_at_and_expires_at_only",
        "inherited_writer_configuration_validation_retained": True,
        "writer_durability": "unchanged_scheduler_file_fsync_replace_directory_fsync",
        "unrelated_recovery_performed": False, "parent_renewal_or_release_performed": False,
        "live_reservations_pruned_or_freed": False, "existing_auto_heartbeat_modified": False,
        "check_return": "renewed_bool_false_is_a_valid_nondue_poll_refusals_raise",
        "success_or_revision_cached": False, "performance_qualified": False,
        "proof_authority": False, "execution_attestation": False, "production_qualified": False}
    _require(type(value) is dict and _wire(value) == _wire(expected),
             "fresh lease helper source/cadence/authentication/durability policy differs")


def _lease_heartbeat_profile(profile, source_shas, *, public):
    _require(profile["inherited_coordinator_source_sha256"] == source_shas["modal_latent_formula_bitwise_device_inference_v2"]
             and profile["lease_currentness_policy"] ==
                 "fresh_authenticated_read_each_boundary_durable_own_renewal_only_when_due"
             and profile["lease_heartbeat_identity_policy"] ==
                 "source_bound_constructor_owned_helper_and_immutable_snapshots"
             and profile["lease_currentness_success_cached"] is False
             and profile["input_guard_substitution_performed"] is False
             and profile["existing_scheduler_or_auto_heartbeat_modified"] is False
             and profile["authenticated_lease_heartbeat_object_and_snapshot_identities_checked"] is True,
             "lease cadence coordinator/custody/currentness scope differs")
    _lease_heartbeat_implementation(profile["authenticated_lease_heartbeat_implementation"], source_shas)
    current = profile["lease_currentness"]
    _require(type(current) is dict and set(current) == {"schema", "fresh_authenticated_read_completed",
             "renewed_at_receipt_boundary", "boundary_scope"}
             and current["schema"] == "modal-latent-formula-authenticated-lease-currentness/v1"
             and current["fresh_authenticated_read_completed"] is True
             and type(current["renewed_at_receipt_boundary"]) is bool
             and current["boundary_scope"] == "this_checked_boundary_only_no_whole_call_or_execution_attestation",
             "actual fresh lease receipt boundary observation differs")


def _observation(archive, observation, *, name, label, count, checkpoint, inputs, source_shas, byte_plan,
                 reference=None, reference_numeric=None, timed=False, lease=None, cuda_device="cuda:0"):
    report = archive.value(observation["result"], name=name + "-result.json", unique=True)
    numeric = archive.value(observation["projected_vectors"], name=name + "-projected-vectors.json", unique=True)
    _authority(report)
    _require(report["checkpoint_sha256"] == hashlib.sha256(_wire(checkpoint)).hexdigest(), "public checkpoint SHA differs")
    _row_inputs(report, inputs, count, checkpoint)
    _source_profile(report["inference_implementation"], label, checkpoint, source_shas, byte_plan, lease=lease, cuda_device=cuda_device)
    _positive(observation["elapsed_seconds"])
    _require(observation["cpu_cuda_rng_unchanged"] is True and observation["included_in_paired_timing"] is timed,
             "completed public call timing/RNG scope differs")
    _require(observation["python_call_profiler_attached_during_timing"] is (not timed),
             "public-call profiler/timing separation differs")
    if timed:
        _require("lease_check_observation" not in observation, "timed public call claims lease instrumentation")
    else:
        _lease_observation(observation["lease_check_observation"], source_shas,
            phase="cpu_reference_or_cuda_warmup", candidate=label.startswith("lease_cadence"), public_call=True)
    _shape(numeric, (count, checkpoint["binding"]["dimension"]))
    canonical = _decisions(report)
    if reference is not None:
        _require(_wire(canonical) == _wire(reference) and observation["canonical_matches_original_cpu"] is True,
                 "exact public decisions differ from original CPU")
    if reference_numeric is not None:
        error = _numeric(reference_numeric, numeric)
        _require(type(observation["complete_projection_max_abs_error"]) is float
                 and observation["complete_projection_max_abs_error"] == error, "complete numeric error arithmetic differs")
    return canonical, numeric


def _flatten_numbers(value):
    if type(value) is list:
        for child in value:
            yield from _flatten_numbers(child)
    else:
        _float32(value)
        yield value


def _lease_native_controls(controls, source_shas, child_lease):
    _authority(controls)
    labels = {"local_lease_key_alias_before_forward", "local_lease_key_alias_after_forward",
              "valid_helper_replacement_before_forward", "paired_helper_snapshot_after_forward",
              "actual_owned_child_cancel_after_all_measurements"}
    _require(type(controls) is list and len(controls) == 5
             and {row["control"] for row in controls} == labels, "complete native lease controls required")
    for row in controls:
        name = row["control"]
        callback = name in {"local_lease_key_alias_after_forward", "paired_helper_snapshot_after_forward"}
        _require(row["refused"] is True and type(row["refusal"]) is str and 0 < len(row["refusal"]) <= 8192
                 and row["before_forward_refusal"] is (not callback) and row["post_forward_callback_executed"] is callback
                 and (_integer(row["actual_model_forward_calls"]) > 0 if callback else
                      _integer(row["actual_model_forward_calls"]) == 0), "native lease refusal boundary differs")
        if name == "actual_owned_child_cancel_after_all_measurements":
            _require("cancel" in row["refusal"].lower() and row["child_cancel_requested"] is True
                     and row["owned_child_lease_id"] == child_lease["lease_id"] and row["released_before_close"] is False
                     and row["scope"] ==
                         "actual_owned_child_only_revocation_after_all_public_measurements_and_model_state_joins",
                     "actual admitted child cancellation/cleanup join differs")
            snapshot = row["resources_after_cancel_before_close"]
            _require(tuple(_integer(snapshot[key]) for key in
                           ("active_lease_count", "active_root_lease_count", "active_child_lease_count")) == (4, 1, 3)
                     and _integer(snapshot["allocated"]["cpu_slots"]) == 3
                     and _integer(snapshot["allocated"]["memory_mb"]) == 3072
                     and _integer(snapshot["allocated_gpu_memory_mb"]) == 768
                     and _integer(snapshot["allocated_unified_memory_mb"]) == 3840,
                     "cancelled live child reservation was not retained before actual close")
            phase = "native_owned_child_cancel_control"
        elif name in {"valid_helper_replacement_before_forward", "paired_helper_snapshot_after_forward"}:
            _require(row["refusal"] == "formula heartbeat helper object or immutable snapshot changed"
                     and row["original_helper_and_snapshot_restored"] is True
                     and row["persisted_lease_metadata_modified"] is False and row["scope"] ==
                         "candidate_owned_helper_and_markers_only_original_bindings_restored_no_persisted_authority_change",
                     "actual helper and paired-marker substitution refusal scope differs")
            phase = "native_lease_helper_custody_control"
        else:
            _require(any(word in row["refusal"].lower() for word in ("lease", "authority", "changed"))
                     and row["persisted_lease_key_modified"] is False and row["scope"] ==
                         "candidate_owned_local_token_alias_only_no_persisted_authority_or_configuration_change",
                     "local lease token alias refusal scope differs")
            phase = "native_lease_key_control"
        _lease_observation(row["lease_check_observation"], source_shas, phase=phase, candidate=True)
    return {"native_control_count": 5, "actual_child_cancel_refused_before_forward": True,
            "natural_expiry_or_due_renewal_qualified": False}


def _controls(controls, checkpoint):
    labels = {"paired_finite_data_mutation", "paired_signed_zero_data_mutation", "equal_content_anchor_identity_replacement",
              "model_only_positive_subnormal_bits", "paired_finite_after_actual_forward_poll",
              "authored_input_mutation_after_forward_poll", "cancel_before_forward"}
    _require(type(controls) is list and len(controls) == len(labels)
             and {item["control"] for item in controls} == labels, "complete new-route native refusal controls required")
    for item in controls:
        name = item["control"]
        if name == "paired_signed_zero_data_mutation" and item.get("applicable") is False:
            _require(item["reason"] == "no actual admitted signed zero tensor element"
                     and not any(value == 0.0 for tensor in checkpoint["model_state"].values()
                                 for value in _flatten_numbers(tensor)), "signed-zero non-applicability contradicts fixed checkpoint")
            continue
        if name == "paired_signed_zero_data_mutation":
            name_tensor = item["actual_admitted_zero_tensor"]
            _require(type(name_tensor) is str and name_tensor in checkpoint["model_state"], "signed-zero admitted tensor name differs")
            values = list(_flatten_numbers(checkpoint["model_state"][name_tensor]))
            index = _integer(item["actual_admitted_zero_index"], 0, len(values) - 1)
            bits = struct.unpack("<i", _float32(values[index]))[0]
            _require(bits in (0, -2147483648) and type(item["original_float32_bits_int32"]) is int
                     and item["original_float32_bits_int32"] == bits, "signed-zero checkpoint tensor/index/original bits differ")
        _require(item["refused"] is True and type(item["refusal"]) is str and 0 < len(item["refusal"]) <= 8192,
                 "native corruption refusal receipt missing")
        if name == "cancel_before_forward":
            _require("cancel" in item["refusal"], "cancellation refusal receipt differs")
            continue
        callback = name.endswith("after_actual_forward_poll") or name.endswith("after_forward_poll")
        _require(item["post_forward_callback_executed"] is callback and item["before_forward_refusal"] is (not callback)
                 and (_integer(item["actual_model_forward_calls"]) > 0 if callback else
                      _integer(item["actual_model_forward_calls"]) == 0), "native corruption refusal boundary differs")


def _timings(archive, role, count, entry, consume):
    trials = entry["trials"]
    _require(type(trials) is list and len(trials) == PAIRS
             and _integer(entry["sample_count_each_route"]) == PAIRS
             and entry["order_schedule"] == "all_six_permutations_repeated_twice", "twelve complete three-way trials required")
    raw = archive.value(entry["raw_timing_evidence"], name=f"{role}-{count}-raw-three-way-timings.json", unique=True)
    _require(_wire(raw) == _wire({name: entry[name] for name in ("trials", "samples_seconds", "median_seconds")}),
             "raw three-way timing evidence differs")
    samples = {lane: [] for lane in CUDA_LANES}
    positions = {lane: [0, 0, 0] for lane in CUDA_LANES}
    for index, trial in enumerate(trials):
        order = list(ORDERS[index % len(ORDERS)])
        _require(_integer(trial["trial"]) == index and trial["order"] == order
                 and type(trial["observations"]) is dict and set(trial["observations"]) == set(CUDA_LANES),
                 "unique trial/all-permutation execution order differs")
        for position, lane in enumerate(order):
            observation = trial["observations"][lane]
            consume(lane, observation, f"{role}-{count}-trial{index:02d}-{lane}")
            samples[lane].append(_positive(observation["elapsed_seconds"]))
            positions[lane][position] += 1
    medians = {lane: statistics.median(values) for lane, values in samples.items()}
    _require(_wire(samples) == _wire(entry["samples_seconds"]) and _wire(medians) == _wire(entry["median_seconds"])
             and all(value == [4, 4, 4] for value in positions.values()), "complete timing/order-position arithmetic differs")
    _require(all(_integer(entry[name]) == 4 for name in
                 ("first_position_each_route", "second_position_each_route", "third_position_each_route")),
             "three-way position counts differ")
    ratios = {"median_original_over_v2_ratio": medians["original_cuda"] / medians["bitwise_v2_cuda"],
              "median_original_over_lease_cadence_ratio": medians["original_cuda"] / medians["lease_cadence_cuda"],
              "median_v2_over_lease_cadence_ratio": medians["bitwise_v2_cuda"] / medians["lease_cadence_cuda"]}
    _require(all(type(entry[name]) is float and math.isfinite(entry[name]) and entry[name] == value
                 for name, value in ratios.items()), "three-way median-ratio arithmetic differs")
    paired = [a / b for a, b in zip(samples["bitwise_v2_cuda"], samples["lease_cadence_cuda"])]
    _require(all(math.isfinite(value) for value in paired) and _wire(paired) == _wire(entry["paired_v2_over_lease_cadence_ratios"]),
             "paired v2-over-lease-cadence ratio arithmetic differs")
    _require(type(entry["paired_v2_over_lease_cadence_min_ratio"]) is float
             and type(entry["paired_v2_over_lease_cadence_max_ratio"]) is float
             and entry["paired_v2_over_lease_cadence_min_ratio"] == min(paired)
             and entry["paired_v2_over_lease_cadence_max_ratio"] == max(paired), "paired timing range arithmetic differs")
    _require(entry["interpretation"] == "descriptive_same_fixture_guarded_complete_calls_no_universal_gain_claim",
             "timing interpretation exceeds descriptive scope")
    return samples, medians, positions


def _family(archive, role, entry, fixtures, source_shas, leases, *, complete, cuda_device):
    _require(role in ("formula8", "formula384"), "unknown formula lineage")
    width = int(role[7:])
    checkpoint = fixtures[role + "_checkpoint"]
    _require(entry["family"] == "formula" and _integer(entry["dimension"]) == width
             and entry["checkpoint_sha256"] == FIXTURES[role + "_checkpoint"]
             and _wire(entry["retained_checkpoint_progress"]) == _wire(checkpoint["progress"])
             and _integer(checkpoint["progress"]["optimizer_steps"]) == 30,
             "fixed trained formula checkpoint/width/progress differs")
    model = _wire(checkpoint["model_state"])
    model_pin = {"bytes": len(model), "sha256": hashlib.sha256(model).hexdigest()}
    _require(_wire(entry["retained_checkpoint_model_pin"]) == _wire(model_pin)
             and entry["checkpoint_optimizer_sha256"] == hashlib.sha256(_wire(checkpoint["optimizer_state"])).hexdigest(),
             "fixed native model/Adam state digest differs")
    byte_plan = _model_bytes(checkpoint)
    inputs = _inputs(archive, entry["inputs"], role, checkpoint, fixtures[role + "_training_inputs"])
    lanes = entry["lanes"]
    _require(type(lanes) is dict and set(lanes).issubset(set(CPU_LANES + CUDA_LANES)), "unknown formula route")
    if complete:
        _require(set(lanes) == set(CPU_LANES + CUDA_LANES) and entry["numerical_and_canonical_qualified"] is True,
                 "complete six-route formula evidence required")
    references, numeric_references, algebra_errors = {}, {}, {}
    total = {"public_reports": 0, "paired_timed_reports": 0, "formula_projections": 0, "adam_constructor_calls": 0}
    for lane in CPU_LANES + CUDA_LANES:
        if lane not in lanes:
            continue
        panel = lanes[lane]
        constructor = panel["constructor"]
        _positive(constructor["elapsed_seconds"])
        _require(constructor["route"] == lane and constructor["started"] is True and constructor["completed"] is True
                 and _integer(constructor["dimension"]) == width and constructor["checkpoint_sha256"] == entry["checkpoint_sha256"]
                 and constructor["observation_scope"] == "constructor_only_source_bound_python_call_observer"
                 and _integer(constructor["adam_restore_attempts"]) == _integer(constructor["adam_restore_completions"]) == 1,
                 "cold native Adam restore constructor receipt differs")
        total["adam_constructor_calls"] += 1
        _require(_wire(panel["state_before"]) == _wire(model_pin), "admitted model is not fixed checkpoint bytes")
        if complete:
            _require(_wire(panel["state_after"]) == _wire(model_pin) and panel["checkpoint_and_adam_unchanged"] is True,
                     "native model/Adam closure missing")
        _require((width, lane) in leases, "lane has no owned child admission")
        lease = leases[(width, lane)]
        _source_profile(panel["profile"], lane, checkpoint, source_shas, byte_plan, public=False, lease=lease, cuda_device=cuda_device)
        _lease_observation(panel["lease_constructor_observation"], source_shas, phase="constructor",
                           candidate=lane.startswith("lease_cadence"))
        if lane in CPU_LANES:
            _require(type(panel["counts"]) is dict and set(panel["counts"]).issubset({"1", "16", "32"}), "unknown CPU row count")
            if complete:
                _require(set(panel["counts"]) == {"1", "16", "32"}, "complete CPU reference row counts missing")
            for count in COUNTS:
                if str(count) not in panel["counts"]:
                    continue
                canonical, numeric = _observation(archive, panel["counts"][str(count)],
                    name=f"{role}-{lane}-{count}", label=lane, count=count, checkpoint=checkpoint, inputs=inputs,
                    source_shas=source_shas, byte_plan=byte_plan, reference=references.get(count),
                    reference_numeric=numeric_references.get(count), lease=lease, cuda_device=cuda_device)
                if lane == "original_cpu_reference":
                    expected = _projection_algebra(checkpoint, [row["latent"] for row in inputs["rows"][:count]])
                    algebra_errors[str(count)] = _numeric(expected, numeric)
                    references[count], numeric_references[count] = canonical, numeric
                total["public_reports"] += 1
                total["formula_projections"] += 1
        elif "warmup" in panel:
            _observation(archive, panel["warmup"], name=f"{role}-{lane}-warmup", label=lane, count=32,
                checkpoint=checkpoint, inputs=inputs, source_shas=source_shas, byte_plan=byte_plan,
                reference=references.get(32), reference_numeric=numeric_references.get(32), lease=lease, cuda_device=cuda_device)
            total["public_reports"] += 1
            total["formula_projections"] += 1
        elif complete:
            raise ValueError("complete CUDA warmup missing")
    count_entries = entry["counts"]
    _require(type(count_entries) is dict and set(count_entries).issubset({"1", "16", "32"}), "unknown CUDA count")
    if complete:
        _require(set(count_entries) == {"1", "16", "32"}, "complete CUDA count coverage required")
        admission = entry["three_way_admission"]
        _require(admission["all_three_gpu_children_live"] is True
                 and _wire(admission["child_leases"]) == _wire({lane: leases[(width, lane)] for lane in CUDA_LANES}),
                 "three-way live child identity/admission receipt differs")
        snapshot = admission["resources"]
        _require(tuple(_integer(snapshot[name]) for name in ("active_lease_count", "active_root_lease_count", "active_child_lease_count"))
                 == (4, 1, 3) and _integer(snapshot["waiting_request_count"]) == 0
                 and _integer(snapshot["allocated"]["cpu_slots"]) == 3 and _integer(snapshot["allocated"]["memory_mb"]) == 3072
                 and _integer(snapshot["allocated_gpu_memory_mb"]) == 768
                 and _integer(snapshot["allocated_unified_memory_mb"]) == 3840, "three-way live resource snapshot differs")
    summaries = {}
    for key, count_entry in count_entries.items():
        count = int(key)
        _require(count in references, "CUDA trial has no independently reconstructed original CPU reference")
        def consume(lane, observation, name):
            _observation(archive, observation, name=name, label=lane, count=count, checkpoint=checkpoint, inputs=inputs,
                source_shas=source_shas, byte_plan=byte_plan, reference=references[count],
                reference_numeric=numeric_references[count], timed=True, lease=leases[(width, lane)], cuda_device=cuda_device)
            total["public_reports"] += 1
            total["paired_timed_reports"] += 1
            total["formula_projections"] += 1
        samples, medians, positions = _timings(archive, role, count, count_entry, consume)
        summaries[key] = {"median_seconds": medians, "order_position_counts": positions,
            "recomputed_ratios": {"original_over_v2": medians["original_cuda"] / medians["bitwise_v2_cuda"],
                                  "original_over_lease_cadence": medians["original_cuda"] / medians["lease_cadence_cuda"],
                                  "v2_over_lease_cadence": medians["bitwise_v2_cuda"] / medians["lease_cadence_cuda"]},
            "paired_v2_over_lease_cadence_min_ratio": count_entry["paired_v2_over_lease_cadence_min_ratio"],
            "paired_v2_over_lease_cadence_max_ratio": count_entry["paired_v2_over_lease_cadence_max_ratio"]}
    if complete:
        _require(type(entry["new_cuda_controls"]) is dict and set(entry["new_cuda_controls"]) == {"bitwise_v2_cuda", "lease_cadence_cuda"},
                 "both new CUDA route corruption controls required")
        for controls in entry["new_cuda_controls"].values():
            _controls(controls, checkpoint)
        lease_controls = _lease_native_controls(entry["lease_cadence_native_controls"], source_shas,
                                                leases[(width, "lease_cadence_cuda")])
    else:
        lease_controls = None
    return {**total, "lease_cadence_native_controls": lease_controls, "width": width, "checkpoint_float32_anchor": byte_plan,
            "original_cpu_projection_algebra_max_abs_errors": algebra_errors, "counts": summaries}


def _constructor_journal(result):
    journal = result["constructor_observations"]
    _require(type(journal) is list and len(journal) <= 12, "bounded source-bound restoration journal required")
    identities, attempts, completions = set(), 0, 0
    for receipt in journal:
        width, route = _integer(receipt["dimension"]), receipt["route"]
        _require(width in (8, 384) and route in CPU_LANES + CUDA_LANES and (width, route) not in identities
                 and receipt["checkpoint_sha256"] == FIXTURES[f"formula{width}_checkpoint"]
                 and receipt["started"] is True and type(receipt["completed"]) is bool
                 and receipt["observation_scope"] == "constructor_only_source_bound_python_call_observer",
                 "unique constructor journal checkpoint/route identity differs")
        attempt = _integer(receipt["adam_restore_attempts"], 0, 1)
        completion = _integer(receipt["adam_restore_completions"], 0, 1)
        _positive(receipt["elapsed_seconds"])
        _require(completion <= attempt and (not receipt["completed"] or attempt == completion == 1),
                 "actual restore attempt/completion/owner-return accounting differs")
        identities.add((width, route))
        attempts += attempt
        completions += completion
    _require(_integer(result["optimizer_restore_attempts"]) == attempts
             and _integer(result["optimizer_constructor_calls"]) == completions,
             "observed restore journal/top-level totals differ")
    return journal


def _partial_family(archive, role, entry, fixtures):
    """Failed bytes can be consistent while numeric/timing qualification stays closed."""
    _require(role in ("formula8", "formula384"), "unknown partial formula lineage")
    width, checkpoint = int(role[7:]), fixtures[role + "_checkpoint"]
    _require(entry["family"] == "formula" and _integer(entry["dimension"]) == width
             and entry["checkpoint_sha256"] == FIXTURES[role + "_checkpoint"], "partial fixed checkpoint identity differs")
    _inputs(archive, entry["inputs"], role, checkpoint, fixtures[role + "_training_inputs"])
    return {"scope": "failed_partial_bytes_only_no_numeric_or_timing_qualification", "width": width,
            "public_reports": 0, "paired_timed_reports": 0, "formula_projections": 0, "adam_constructor_calls": 0}


def _cleanup(result):
    admitted = "admission" in result
    _require(type(result["owned_children"]) is list and len(result["owned_children"]) <= 12,
             "bounded owned child closure required")
    for name in ("active_lease_count", "active_root_lease_count", "active_child_lease_count", "waiting_request_count"):
        _require(_integer(result["resources_after"][name]) == 0, "final resource lease counter not plain zero")
    final_resources = result["resources_after"]
    _require(_integer(final_resources["allocated"]["cpu_slots"]) == 0
             and _integer(final_resources["allocated"]["memory_mb"]) == 0
             and _integer(final_resources["allocated_gpu_memory_mb"]) == 0
             and _integer(final_resources["allocated_unified_memory_mb"]) == 0,
             "final CPU/RAM/GPU/unified allocation counters not plain zero")
    if admitted:
        root = result["admission"]
        _require((_integer(root["cpu_slots"]), _integer(root["memory_mb"]), _integer(root["gpu_memory_mb"]),
                  _integer(root["unified_memory_mb"])) == (3, 3072, 768, 3840), "root admitted envelope differs")
        _require(root["requires_gpu"] is True and root["released"] is False and root["cancelled"] is False
                 and _integer(root["owner_pid"], 1) == _integer(result["pid"], 1), "root admission process/liveness identity differs")
        _require(result["safe_owned_cleanup_established"] is True and result["root_release_observed"] is True
                 and result["own_root_lease_released"] is True
                 and result["cuda_cleanup_status"] == "owned_allocations_restored_to_baseline", "root owned cleanup missing")
        for name in ("gpu_allocated_before_producer_imports_bytes", "gpu_allocated_before_owned_sessions_bytes",
                     "gpu_allocated_after_framework_workspace_clear_bytes"):
            _require(_integer(result[name]) == 0, "owned device allocation closure not plain zero")
    else:
        _require(result["qualified"] is False and result["owned_children"] == [] and result["families"] == {}
                 and _integer(result["optimizer_constructor_calls"]) == 0
                 and result["root_release_observed"] is False and result["own_root_lease_released"] is False,
                 "pre-admission refusal claims owned execution")
    identities, leases = set(), {}
    for record in result["owned_children"]:
        admission = record["admission"]
        _require(record["release_observed"] is True and record["lease_id"] == admission["lease_id"]
                 and record["lease_id"] not in identities, "unique owned child identity/release missing")
        cuda = admission["requires_gpu"]
        combination = (_integer(record["dimension"]), record["route"])
        _require(record["family"] == "formula" and combination[0] in (8, 384)
                 and record["route"] in CPU_LANES + CUDA_LANES and combination not in leases
                 and record["optimized"] is (record["route"] in CUDA_LANES) and cuda is record["optimized"],
                 "unique owned route/dimension/device combination required")
        _require(type(cuda) is bool and _integer(admission["cpu_slots"]) == 1
                 and _integer(admission["memory_mb"]) == 1024
                 and _integer(admission["gpu_memory_mb"]) == (256 if cuda else 0)
                 and _integer(admission["unified_memory_mb"]) == (1280 if cuda else 0)
                 and admission["parent_lease_id"] == result["admission"]["lease_id"]
                 and admission["released"] is False and admission["cancelled"] is False
                 and _integer(admission["owner_pid"], 1) == _integer(result["pid"], 1), "owned child envelope/process/parent differs")
        identities.add(record["lease_id"])
        leases[combination] = admission
    return admitted, leases


def _current_path(role):
    package = Path(__file__).absolute().parent.parent
    special = {"benchmark": Path(__file__).with_name("qualify_formula_lease_cadence.py"),
        "coordinator_helpers": Path(__file__).with_name("qualify_formula_guard_coordinator.py"),
        "ordinary_reader_helpers": Path(__file__).with_name("audit_formula_guard_coordinator_v3.py"),
        "cleanup_helper": Path(__file__).with_name("qualify_native_768_device.py"),
        "cg2_harness_helpers": Path(__file__).with_name("qualify_bitwise_trained_head_devices.py"),
        "tree_pin": package / "ipfs_datasets_py/logic/autoformal/tree_pin.py",
        "canonical_contracts": package / "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
        "cid_utils": package / "ipfs_datasets_py/utils/cid_utils.py"}
    return special.get(role, package / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / (role + ".py"))


def _families(value):
    _require(type(value) is dict and set(value).issubset({"formula8", "formula384"})
             and all(type(entry) is dict for entry in value.values()), "plain closed formula family map required")
    return value


def _scopes(result):
    expected = {
        "scope": "retained_trained_formula8_formula384_original_v2_lease_cadence_complete_call_comparison",
        "cpu_reference_scope": "one_call_per_route_count_no_repeatability_claim",
        "cuda_timing_scope": "complete_guarded_public_inference_and_completion_sync_uninstrumented_input_copy_before_interval_three_way_balanced",
        "counter_observation_scope": "source_bound_python_calls_during_constructors_cpu_references_cuda_warmups_and_controls_only",
    }
    _require(all(result[name] == value for name, value in expected.items()), "inference timing/counter observation scope differs")


def review(result_path, expected_result_sha256, *, check_current_sources=False):
    _require(type(check_current_sources) is bool and type(expected_result_sha256) is str
             and SHA.fullmatch(expected_result_sha256) is not None, "external result SHA/current-source boolean required")
    result_path = Path(result_path).absolute()
    _require(result_path.name == "result.json", "exact result.json entry required")
    raw = _read(result_path)
    result_pin = _pin(result_path, raw)
    _require(result_pin["sha256"] == expected_result_sha256, "external result SHA differs")
    result = _json(raw)
    _require(result["schema"] == SCHEMA and type(result["qualified"]) is bool, "exact coordinator result schema required")
    complete = result["qualified"]
    _families(result["families"])
    _scopes(result)
    # Only this top-level boolean describes report consistency. All nested
    # authority declarations remain closed, including native control journals.
    _authority({name: value for name, value in result.items() if name != "qualified"})
    _require(complete is (result["error"] is None) and result["complete_call_measurements_qualified"] is complete,
             "qualification/refusal flags inconsistent")
    for name in ("training_calls", "new_training_fits", "optimizer_steps", "training_mode_true_calls", "encoder_calls"):
        _require(_integer(result[name]) == 0, "inference archive reports new training/encoder work")
    for name in ("production_qualified", "proof_authority", "execution_attestation", "semantic_correctness_verified",
                 "fresh_encoder_execution_qualified", "native_encoder_origin_authenticated", "kernel_resource_enforcement",
                 "universal_speedup_claimed", "persistent_precision_policy_mutated", "foreign_process_actions"):
        _require(result[name] is False, "archive exceeds ordinary consistency authority: " + name)
    _require(result["native_due_renewal_qualified"] is False and result["native_lease_expiry_qualified"] is False
             and result["lease_observation_scope"] == "untimed_constructor_reference_warmup_and_controls_main_thread_only",
             "native due/expiry or whole-interval observation scope exceeded")
    _require(result["conservative_complete_call_gain_observed"] is False
             and result["selected_existing_profile_changed"] is False
             and _integer(result["paired_observations_per_route_per_count"]) == PAIRS
             and _integer(result["max_seconds_after_root_admission"]) == 120
             and type(result["admission_timeout_seconds"]) is int
             and math.isfinite(result["admission_timeout_seconds"]) and 1 <= result["admission_timeout_seconds"] <= 60
             and type(result["numeric_tolerance_absolute"]) is float and result["numeric_tolerance_absolute"] == 5e-5,
             "bounded inference sample/deadline/tolerance differs")
    archive = Archive(result_path.parent, result)
    sources, fixtures, current_pins, verified_sources, source_shas = result["source_pins"], {}, [], [], {}
    _require(type(sources) is list and len(sources) == len(SOURCE_ROLES)
             and {item["role"] for item in sources} == SOURCE_ROLES, "exact unique25 producer source roles required")
    _require(type(result["fixture_pins"]) is list and len(result["fixture_pins"]) == len(FIXTURES)
             and {item["role"] for item in result["fixture_pins"]} == set(FIXTURES), "exact four retained trained fixtures required")
    _require(result["shared_configuration"]["role"] == "shared_configuration", "configuration role differs")
    baseline = result["inherited_cg2_baseline"]
    _require(baseline["role"] == "inherited_cg2_result_baseline_only"
             and result["inherited_cg2_baseline_scope"] == "content_pin_only_no_768_or_4096_report_regeneration",
             "inherited baseline scope differs")
    for item in [*sources, result["shared_configuration"], *result["fixture_pins"], baseline]:
        role, current, retained = item["role"], item["current"], item["retained_copy"]
        _pin_shape(current)
        retained_raw = archive.raw(retained)
        _require((current["bytes"], current["sha256"]) == (retained["bytes"], retained["sha256"]), "current/retained source pin differs")
        expected = (CONFIG_SHA if role == "shared_configuration" else BASELINE_SHA if item is baseline else
                    FIXTURES.get(role) or FIXED_SOURCES.get(role))
        if expected is not None:
            _require(current["sha256"] == expected, "fixed source/configuration/fixture differs: " + role)
        if item in sources:
            _require(current["path"] == str(_current_path(role).absolute()), "source pin path differs from checked current repository")
            source_shas[role] = current["sha256"]
        if check_current_sources:
            observed = _pin(current["path"], _read(current["path"], readonly=False))
            _require(observed == current, "current source/configuration/fixture changed")
            if item in sources:
                verified_sources.append(observed)
        if role in FIXTURES:
            fixtures[role] = _json(retained_raw)
        current_pins.append(current)
    _require(result["retained_sources_fixtures_configuration_unchanged"] is True
             and _wire(result["currentness_after"]) == _wire(current_pins), "producer final source/fixture/configuration closure differs")
    configuration = archive.value(result["shared_configuration"]["retained_copy"])
    _require(result["resources_after"]["state_path"] == configuration["state_path"], "scheduler/configuration state path differs")
    admitted, leases = _cleanup(result)
    journal = _constructor_journal(result)
    if complete:
        _require(admitted and set(result["families"]) == {"formula8", "formula384"}
                 and result["ambient_precision_default_policy_unchanged"] is True
                 and result["root_gpu_allocation_budget_observed"] is True
                 and 0 <= _integer(result["hardware"]["device_index"], 0, 63) <= 63
                 and result["hardware"]["actual_initial_cuda_kernel"] is True
                 and _integer(result["gpu_peak_allocated_bytes"]) <= 768 * 1024**2,
                 "complete family/precision/device-allocation envelope differs")
        before = result["ambient_settings_before_thread_reservation"]
        reserved = result["ambient_settings_before_producer_imports_and_models"]
        _require(_integer(before["num_threads"], 1, 1024) > 0
                 and _wire(reserved) == _wire({**before, "num_threads": 1})
                 and _wire(result["ambient_settings_after_owned_cleanup_before_thread_restore"]) == _wire(reserved)
                 and _wire(result["ambient_settings_after_thread_restore"]) == _wire(before)
                 and result["thread_reservation_scope"] == "caller_owned_one_thread_restored_after_owned_cleanup"
                 and reserved["default_device"] == "cpu" and reserved["default_dtype"] == "torch.float32"
                 and reserved["autocast_cpu_enabled"] is False and reserved["autocast_cuda_enabled"] is False,
                 "ambient precision/default/thread reservation closure differs")
    families = ({role: _family(archive, role, entry, fixtures, source_shas, leases, complete=True,
                              cuda_device=f"cuda:{result['hardware']['device_index']}")
                 for role, entry in result["families"].items()} if complete else
                {role: _partial_family(archive, role, entry, fixtures) for role, entry in result["families"].items()})
    totals = {name: sum(family[name] for family in families.values()) for name in
              ("public_reports", "paired_timed_reports", "formula_projections", "adam_constructor_calls")}
    if complete:
        _require(totals == {"public_reports": 240, "paired_timed_reports": 216, "formula_projections": 240, "adam_constructor_calls": 12}
                 and len(result["owned_children"]) == 12 and _integer(result["optimizer_restore_attempts"]) == 12
                 and _integer(result["total_return_count"]) == 240 and _integer(result["timed_return_count"]) == 216
                 and _integer(result["formula_projection_count"]) == 240, "complete archive/restore/return coverage differs")
        expected_journal = [result["families"][f"formula{width}"]["lanes"][lane]["constructor"]
                            for width in (8, 384) for lane in CPU_LANES + CUDA_LANES]
        _require(_wire(journal) == _wire(expected_journal), "constructor journal/each admitted lane join differs")
    leftovers = archive.finish(partial=not complete)
    _require(_pin(result_path, _read(result_path)) == result_pin, "externally pinned result changed during audit")
    if check_current_sources:
        for pin in current_pins:
            _require(_pin(pin["path"], _read(pin["path"], readonly=False)) == pin, "current source changed during audit")
    return {"schema": REVIEW_SCHEMA, "qualified": complete, "closed_artifacts_consistent": True, "error": None,
        "producer_refusal": result["error"], "result_pin": result_pin, "expected_result_sha256": expected_result_sha256,
        "retained_pins": [result_pin, *archive.pins.values()], "check_current_sources": check_current_sources,
        "current_sources_verified": check_current_sources, "current_source_pins": verified_sources,
        "scope": "ordinary_pinned_formula_projection_arithmetic_and_three_way_timing_consistency",
        "projection_algebra_recomputed": complete, "recurrent_grammar_replayed": False,
        "observed_restore_attempts": result["optimizer_restore_attempts"],
        "observed_restore_completions": result["optimizer_constructor_calls"],
        "retained_python_executed": False, "tensor_library_imported": False, "model_executed": False,
        "encoder_executed": False, "proof_authority": False, "execution_attestation": False,
        "production_qualified": False, "semantic_correctness_verified": False, "universal_speedup_claimed": False,
        "families": families, "coverage": totals, "unjoined_failed_partial_evidence": leftovers,
        "bounded_archive_files": len(archive.pins) + 1,
        "bounded_archive_bytes": sum(pin["bytes"] for pin in archive.pins.values()) + len(raw)}


def audit(root, expected_result_sha256, *, check_current_sources=False):
    try:
        return review(Path(root).absolute() / "result.json", expected_result_sha256,
                      check_current_sources=check_current_sources)
    except (ValueError, KeyError, TypeError, OSError, OverflowError, RecursionError, struct.error) as error:
        return {"schema": REVIEW_SCHEMA, "qualified": False, "closed_artifacts_consistent": False,
            "error": {"type": type(error).__name__, "detail": str(error)}, "retained_python_executed": False,
            "tensor_library_imported": False, "model_executed": False, "encoder_executed": False,
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
            descriptor = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=parent)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o444)
        finally:
            os.close(parent)
        _require(_pin(output, _read(output)) == _pin(output, raw), "reader output differs from intended report bytes")
    return 0 if report["closed_artifacts_consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
