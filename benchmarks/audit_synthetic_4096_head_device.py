"""Closed byte/report audit of an externally pinned synthetic4096 v2 archive.

Only bounded ordinary files are opened. No Torch, model, retained Python,
resource owner, SQL, network, service or writer is used. Device and cleanup
claims remain reported observations; this does not attest their execution.
Failed producers remain unqualified even when their retained bytes are valid.
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

MAX_FILE_BYTES = 8 * 1024**2
MAX_TOTAL_BYTES = 64 * 1024**2
COUNTS = (1, 16, 32)
OUTPUTS = frozenset(("modality", "presence", "start", "end"))
SESSION_PROFILE = "native-4096-source-span-batched-device-float32-cpu-decisions/v2"
BITWISE_PROFILE = "native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/v1"
BITWISE_PROFILE_V2 = "native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/v2"
BASE_SCHEMA = "native4096-synthetic-head-device-qualification/v2"
SEQUEL_SCHEMAS = {"native4096-synthetic-bitwise-session-device-qualification/v1": BITWISE_PROFILE,
    "native4096-synthetic-bitwise-session-device-qualification/v2": BITWISE_PROFILE_V2}
HELPERS_SHA = "a2b85c0e05d9fc652e7e3d2fdb99b83407a511a3321fba3d2299c27e797ceb36"
GRU_PROFILE = "native-4096-source-span-strict-cuda-float32/v1"
CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
CLEANUP_SHA = "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c"
FALSE_FLAGS = ("qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
               "semantic_correctness_verified", "promotion_performed", "publication_performed")
AUTHORITY_FLAGS = frozenset(("proof_authority", "execution_attestation", "kernel_resource_enforcement",
    "semantic_correctness_verified", "promotion_performed", "publication_performed", "production_admission",
    "trusted_native_owner_verified", "native_leanstral_qualified", "production_qualified",
    "native_cuda_qualified", "performance_qualified", "native_bitwise_session_cuda_qualified",
    "bitwise_session_performance_qualified", "native_leanstral_encoder_available", "native_leanstral_head_qualified",
    "qualified", "admitted", "formalized", "roundtrip_ok", "target_access", "teacher_forcing", "training_executed"))
OUTER_DECISIONS = ("lineage_id", "checkpoint_sha256", "context_contract_sha256", "input_dimension",
    "decoded_count", "status", "latent_ablation", "target_access", "teacher_forcing", "training_executed",
    "model_state_unchanged", *FALSE_FLAGS)
_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class AuditError(ValueError):
    """The externally pinned report or one of its byte joins is inconsistent."""


def _require(condition, message):
    if not condition:
        raise AuditError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "lowercase external SHA256 required")
    return value


def _integer(value, low=0, high=2**63 - 1):
    _require(type(value) is int and low <= value <= high, "bounded plain integer required")
    return value


def _number(value):
    _require(type(value) in (int, float), "finite plain number required")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    _require(finite, "finite plain number required")
    return value


def _float32(value):
    value = _number(value)
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise AuditError("float32 number bound exceeded") from exc
    _require(math.isfinite(result), "finite float32 required")
    return result


def _json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise AuditError("nonfinite JSON constant refused")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    pending, nodes = [(value, 0)], 0
    while pending:
        part, depth = pending.pop()
        nodes += 1
        _require(depth <= 64 and nodes <= 1_000_000, "JSON depth/node bound exceeded")
        if type(part) is dict:
            pending.extend((child, depth + 1) for child in part.values())
        elif type(part) is list:
            pending.extend((child, depth + 1) for child in part)
        elif type(part) in (int, float):
            _number(part)
    return value


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _directory(path):
    path = Path(path).absolute()
    _require(".." not in path.parts, "canonical directory path required")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _source_paths():
    repo = Path(__file__).absolute().parent.parent
    package = repo / "ipfs_datasets_py"
    module = package / "optimizers/logic_theorem_optimizer"
    names = {"head": "legal_span_4096.py", "device_session": "legal_span_4096_device_inference.py",
        "span": "legal_span_formula.py", "precision": "legal_span_device_inference.py",
        "batch_primitives": "legal_span_device_batch_inference.py", "dimensional_checkpoint": "legal_span_dimensions.py",
        "tensor_guard": "owned_tensor_value_guard.py", "checkpoint_guard": "checkpoint_content_guard.py",
        "codec": "legal_formula_codec.py", "grammar": "legal_ir_grammar_decoder.py",
        "family_evaluator": "legal_ir_family_evaluator.py", "snapshot_evaluator": "snapshot_evaluator.py",
        "runtime_telemetry": "runtime_telemetry.py", "proof_resource_safety": "proof_resource_safety.py",
        "resources": "resource_scheduler.py", "bitwise_primitive_candidate": "owned_tensor_bitwise_guard.py",
        "bitwise_device_session": "legal_span_4096_bitwise_device_inference.py"}
    result = {role: module / name for role, name in names.items()}
    result.update(benchmark=repo / "benchmarks/qualify_synthetic_4096_head_device_v2.py",
        cuda_cleanup=repo / "benchmarks/qualify_native_768_device.py",
        configuration=repo.parents[1] / "artifacts/codebase_ir_terminal_bench/successor-expansion-resources-20261003-01/configuration.json",
        canonical=package / "logic/legal_ir/canonical_contracts.py", cid_utils=package / "utils/cid_utils.py")
    return result


def _report_source_paths(schema):
    paths = dict(_source_paths())
    if schema in SEQUEL_SCHEMAS:
        paths["qualified_v2_helpers"] = paths["benchmark"]
        suffix = "_v2" if schema.endswith("/v2") else ""
        paths["benchmark"] = paths["benchmark"].with_name("qualify_synthetic_4096_bitwise_session_device" + suffix + ".py")
        if suffix:
            paths["bitwise_device_session"] = paths["bitwise_device_session"].with_name("legal_span_4096_bitwise_device_inference_v2.py")
    return paths


def _json_names():
    result = {"result.json", "synthetic-inputs.json", "synthetic-untrained-checkpoint.json"}
    for count in COUNTS:
        result.update({f"head-cpu-reference-batch{count}.json",
                       f"head-cpu-reference-batch{count}-canonical-projection.json",
                       f"head-cpu-singleton-reference-batch{count}-logits.json"})
        for lane in ("cpu", "cuda_batched", "bitwise_cpu", "bitwise_cuda_batched"):
            result.update({f"head-{lane}-batch{count}.json", f"head-{lane}-batch{count}-logits.json",
                           f"head-{lane}-batch{count}-canonical-projection.json"})
    return frozenset(result)


class _Reader:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.fd = _directory(self.root)
        self.root_identity = _identity(os.fstat(self.fd))[:4]
        self.allowed = _json_names() | {"producers/" + role + "-" + path.name
             for schema in (BASE_SCHEMA, *SEQUEL_SCHEMAS) for role, path in _report_source_paths(schema).items()}
        self.pins, self.identities, self.cache = {}, {}, {}
        self.current_files, self.total = [], 0

    def close(self):
        os.close(self.fd)

    def _open(self, name):
        _require(name in self.allowed, "unlisted retained path refused")
        if "/" not in name:
            return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        parent = os.open("producers", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            return os.open(name.split("/")[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)

    def _bytes(self, descriptor, label):
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_FILE_BYTES,
                 "bounded single-link ordinary file required: " + label)
        _require(self.total + before.st_size <= MAX_TOTAL_BYTES, "total reader byte bound exceeded")
        raw = bytearray()
        while len(raw) <= MAX_FILE_BYTES:
            part = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(descriptor)
        _require(_identity(before) == _identity(after) and len(raw) == before.st_size,
                 "file changed during read: " + label)
        self.total += len(raw)
        return bytes(raw), _identity(after)

    def _pin(self, actual, expected, path):
        _require(type(expected) is dict and set(expected) == {"path", "bytes", "sha256"}, "closed file pin required")
        _require(expected["path"] == str(path), "fixed retained/current pin path differs")
        _integer(expected["bytes"], 1, MAX_FILE_BYTES)
        _sha(expected["sha256"])
        _require((actual["bytes"], actual["sha256"]) == (expected["bytes"], expected["sha256"]),
                 "file bytes differ from admitted/report pin: " + str(path))

    def read(self, name, pin=None):
        if name not in self.cache:
            descriptor = self._open(name)
            try:
                raw, identity = self._bytes(descriptor, name)
            finally:
                os.close(descriptor)
            _require(identity[:2] not in [other[:2] for other in self.identities.values()], "retained file alias refused")
            self.cache[name] = raw
            self.identities[name] = identity
            self.pins[name] = {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if pin is not None:
            self._pin(self.pins[name], pin, self.root / name)
        return self.cache[name]

    def json(self, name, pin=None):
        return _json(self.read(name, pin))

    def current(self, path, expected, raw):
        parent = _directory(path.parent)
        try:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                current, identity = self._bytes(descriptor, str(path))
            finally:
                os.close(descriptor)
        finally:
            os.close(parent)
        actual = {"path": str(path), "bytes": len(current), "sha256": hashlib.sha256(current).hexdigest()}
        self._pin(actual, expected, path)
        _require(current == raw, "current source differs from retained bytes")
        self.current_files.append((path, identity, actual))

    def final_check(self):
        descriptor = _directory(self.root)
        try:
            _require(_identity(os.fstat(descriptor))[:4] == self.root_identity, "retained root identity changed")
        finally:
            os.close(descriptor)
        for name, identity in self.identities.items():
            descriptor = self._open(name)
            try:
                _require(_identity(os.fstat(descriptor)) == identity, "retained path changed after read")
            finally:
                os.close(descriptor)
        for path, identity, _ in self.current_files:
            parent = _directory(path.parent)
            try:
                descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    _require(_identity(os.fstat(descriptor)) == identity, "current source changed after read")
                finally:
                    os.close(descriptor)
            finally:
                os.close(parent)


def _false_authority(value):
    if type(value) is dict:
        for key, child in value.items():
            if key in AUTHORITY_FLAGS:
                _require(child is False, "retained report widens authority: " + key)
            _false_authority(child)
    elif type(value) is list:
        for child in value:
            _false_authority(child)


def _source_join(reader, report, current):
    paths, joined = _report_source_paths(report["schema"]), {}
    pins = report["source_pins"]
    _require(type(pins) is list and len(pins) <= len(paths), "bounded producer inventory required")
    for item in pins:
        _require(type(item) is dict and set(item) == {"role", "current", "retained_copy"}, "closed producer pin required")
        role = item["role"]
        _require(role in paths and role not in joined, "unknown or repeated producer role")
        path = paths[role]
        expected = item["current"]
        _require(expected["path"] == str(path), "fixed current producer path differs")
        name = "producers/" + role + "-" + path.name
        raw = reader.read(name, item["retained_copy"])
        actual = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        _integer(expected["bytes"], 1, MAX_FILE_BYTES)
        _sha(expected["sha256"])
        _require(set(expected) == {"path", "bytes", "sha256"} and actual == {key: expected[key] for key in actual},
                 "retained/current source pin bytes differ")
        if current:
            reader.current(path, expected, raw)
        joined[role] = expected
    for role in ("benchmark", "configuration", "cuda_cleanup", "qualified_v2_helpers"):
        if role in report:
            _require(role in joined and report[role] == joined[role], "top-level producer pin differs")
    if "configuration" in joined:
        _require(joined["configuration"]["sha256"] == CONFIG_SHA, "shared configuration SHA differs")
    if "cuda_cleanup" in joined:
        _require(joined["cuda_cleanup"]["sha256"] == CLEANUP_SHA, "cleanup implementation SHA differs")
    if report["schema"] in SEQUEL_SCHEMAS and "qualified_v2_helpers" in joined:
        _require(joined["qualified_v2_helpers"]["sha256"] == HELPERS_SHA, "qualified v2 helper source SHA differs")
    return joined


def _shapes(value):
    if type(value) is list:
        _require(bool(value), "empty numeric tensor")
        parts = [_shapes(child) for child in value]
        _require(all(shape == parts[0][0] for shape, _ in parts), "ragged numeric tensor")
        return (len(value), *parts[0][0]), [number for _, numbers in parts for number in numbers]
    return (), [_number(value)]


def _weight_shapes():
    result = {"byte_embedding.weight": (257, 4), "token_projection.weight": (8, 13), "token_projection.bias": (8,),
              "latent_down.weight": (4, 4096), "latent_down.bias": (4,),
              "latent_up.weight": (16, 4), "latent_up.bias": (16,)}
    for suffix in ("", "_reverse"):
        for name in ("weight_ih_l0", "weight_hh_l0"):
            result["encoder." + name + suffix] = (24, 8)
        for name in ("bias_ih_l0", "bias_hh_l0"):
            result["encoder." + name + suffix] = (24,)
    for name, width in (("modality", 3), ("presence", 8), ("start", 6), ("end", 6)):
        result[name + ".weight"], result[name + ".bias"] = (width, 16), (width,)
    return result


def _fixture(reader, report, sources):
    rows = reader.json("synthetic-inputs.json", report["rows"])
    texts = ["Lark must retain books."] + [f"Worker{i} may publish records." for i in range(1, 32)]
    expected = []
    for index, text in enumerate(texts):
        vector = [0.0001] * 4096
        vector[4095] = (index + 1) / 32
        expected.append({"id": f"synthetic4096-{index}", "source_text": text, "latent": vector})
    _require(rows == expected, "exact authored 32-row native-width fixture differs")
    checkpoint = reader.json("synthetic-untrained-checkpoint.json", report["checkpoint"])
    _require(checkpoint["schema"] == "native-4096-source-span-checkpoint/v1"
             and checkpoint["lineage_id"] == "native_4096_source_span_v1", "4096 checkpoint schema/lineage differs")
    _require(all(checkpoint[name] is False for name in FALSE_FLAGS), "synthetic checkpoint asserts authority")
    config = checkpoint["config"]
    fields = {"architecture": "utf8-byte-bidirectional-gru-native-4096-film-spans/v1", "latent_dimension": 4096,
              "latent_enabled": True, "device": "cpu", "dtype": "float32", "hidden_size": 8, "embedding_dim": 4,
              "projection_width": 4, "batch_size": 1, "seed": 1729, "residual_scale": 0.25,
              "max_source_characters": 16384, "max_source_tokens": 256, "max_token_bytes": 2048}
    _require(all(type(config[key]) is type(value) and config[key] == value for key, value in fields.items()),
             "exact untrained4096 fixture configuration differs")
    _require(checkpoint["progress"] == {"epochs_completed": 0, "optimizer_steps": 0, "row_cursor": 0}
             and all(type(value) is int for value in checkpoint["progress"].values()), "fixture has optimizer/training progress")
    _require(checkpoint["optimizer_state"] == {"schema": "adam-default-betas-eps/v1", "parameters": {}},
             "untrained fixture contains Adam state")
    _require(checkpoint["source_parent_checkpoint"] is None and checkpoint["source_parent_checkpoint_sha256"] is None
             and checkpoint["parent_checkpoint_sha256"] is None and checkpoint["source_parent_optimizer_steps"] == 0,
             "synthetic fixture contains a trained parent")
    _require(checkpoint["provenance"] == {"schema": "native-4096-source-span-provenance/v1",
             "kind": "synthetic_untrained_architecture_control", "synthetic_embeddings": True,
             "trusted_native_owner_verified": False}, "synthetic provenance differs")
    shapes = _weight_shapes()
    _require(set(checkpoint["model_state"]) == set(shapes), "complete actual4096 model blocks required")
    payload = bytearray()
    for name in sorted(shapes):
        shape, numbers = _shapes(checkpoint["model_state"][name])
        _require(shape == shapes[name] and all(type(number) is float and _float32(number) == number for number in numbers),
                 "exact float32 checkpoint shape/serialization differs")
        if name.startswith("latent_up."):
            _require(all(struct.pack("<f", number) == b"\0\0\0\0" for number in numbers), "fixture output adapter is not exact positive zero")
        payload.extend(b"".join(struct.pack("<f", number) for number in numbers))
    source = {name: value for name, value in checkpoint["model_state"].items() if not name.startswith(("latent_down.", "latent_up."))}
    _require(checkpoint["initial_model_state_sha256"] == _digest(checkpoint["model_state"])
             and checkpoint["initial_source_model_sha256"] == _digest(source), "zero-step checkpoint initial state digest differs")
    training = [{**rows[0], "canonical_ir": {"rules": [{"actor": "Lark", "modality": "O", "action": "retain",
        "object": "books", "conditions": [], "exceptions": [], "temporal": []}]}}]
    context = {"dimension": 4096, "representation_id": "synthetic-4096-untrained-architecture-control",
               "producer_sha256": hashlib.sha256(b"authored synthetic vectors; no encoder").hexdigest(),
               "training_index_sha256": _digest(training)}
    _require(checkpoint["context_contract"] == context and checkpoint["context_contract_sha256"] == _digest(context)
             and checkpoint["training_manifest_sha256"] == _digest(training) and checkpoint["tuning_manifest_sha256"] == _digest([])
             and checkpoint["training_count"] == 1 and checkpoint["tuning_count"] == 0,
             "synthetic training/context manifest join differs")
    base = {role: sources[role]["sha256"] for role in ("span", "codec", "grammar", "canonical")}
    _require(checkpoint["implementation"] == {"native4096_sha256": sources["head"]["sha256"], "base_span": base},
             "checkpoint retained implementation source joins differ")
    _require(report["latent_adapter_shape"] == [4, 4096] and report["zero_output_adapter"] is True
             and report["latent_conditioning_trained"] is False, "fixture adapter scope differs")
    return rows, checkpoint, {"checkpoint_sha256": _digest(checkpoint), "optimizer_state_sha256": _digest(checkpoint["optimizer_state"]),
                              "anchor_sha256": hashlib.sha256(payload).hexdigest(), "reference_bytes": len(payload)}


def _projection(value):
    """Preserve all row decisions; replace only the four declared float paths."""
    result = {name: deepcopy(value[name]) for name in OUTER_DECISIONS}
    result["rows"] = deepcopy(value["rows"])
    def marker(number):
        if number is None:
            return None
        _require(type(number) is float and math.isfinite(number), "finite float/None decision diagnostic required")
        return {"known_finite_numeric_diagnostic_value_excluded": True}
    for row in result["rows"]:
        if "minimum_decision_logit_margin" in row:
            row["minimum_decision_logit_margin"] = marker(row["minimum_decision_logit_margin"])
        if "span_diagnostics" not in row:
            continue
        diagnostics = row["span_diagnostics"]
        if "modality_logits" in diagnostics:
            logits = diagnostics["modality_logits"]
            _require(type(logits) is list and len(logits) == 3 and all(number is not None for number in logits),
                     "complete three-score modality diagnostic required")
            diagnostics["modality_logits"] = [marker(number) for number in logits]
        _require(type(diagnostics["facets"]) is dict, "exact facet diagnostic mapping required")
        for facet in diagnostics["facets"].values():
            for name in ("presence_logit_margin", "span_logit_margin"):
                if name in facet:
                    facet[name] = marker(facet[name])
    return result


def _decisions(value, rows, checkpoint, digests):
    _require(value["lineage_id"] == checkpoint["lineage_id"] and value["checkpoint_sha256"] == digests["checkpoint_sha256"]
             and value["context_contract_sha256"] == checkpoint["context_contract_sha256"]
             and _integer(value["input_dimension"]) == 4096 and value["latent_ablation"] == "none"
             and value["target_access"] is False and value["teacher_forcing"] is False
             and value["training_executed"] is False and value["model_state_unchanged"] is True
             and all(value[name] is False for name in FALSE_FLAGS), "public/reference immutable fixture binding differs")
    _require(type(value["rows"]) is list and len(value["rows"]) == len(rows), "public/reference row coverage differs")
    for actual, row in zip(value["rows"], rows):
        _require(actual["source_sha256"] == hashlib.sha256(row["source_text"].encode()).hexdigest()
                 and actual["latent_sha256"] == _digest(row["latent"]) and actual["latent_input_enabled"] is True
                 and actual["status"] in {"decoded", "abstained"}
                 and all(actual[name] is False for name in FALSE_FLAGS), "source/vector/decision receipt join differs")
        diagnostics = actual.get("span_diagnostics")
        if diagnostics is not None:
            _require(type(diagnostics) is dict and type(diagnostics["facets"]) is dict,
                     "plain source-span diagnostic/facet mappings required")
            tokens = [{"text": match.group(), "start": match.start(), "end": match.end()}
                      for match in _TOKEN.finditer(row["source_text"])]
            _require(diagnostics["tokens"] == tokens, "exact source tokens/offsets differ")
            for facet in diagnostics["facets"].values():
                _require(type(facet) is dict, "plain facet decision mapping required")
                if facet["present"] is True:
                    start = _integer(facet["token_start"], 0, len(tokens) - 1)
                    end = _integer(facet["token_end_inclusive"], start, len(tokens) - 1)
                    a, b = tokens[start]["start"], tokens[end]["end"]
                    _require((facet["char_start"], facet["char_end"], facet["text"]) == (a, b, row["source_text"][a:b]),
                             "facet copied token/character/text decision differs")
                else:
                    _require(facet["present"] is False and all(facet[name] is None for name in
                             ("token_start", "token_end_inclusive", "char_start", "char_end", "text")), "absent facet decision differs")
    decoded = sum(row["status"] == "decoded" for row in value["rows"])
    _require(_integer(value["decoded_count"]) == decoded and value["status"] ==
             ("decoded" if decoded == len(rows) else "partial" if decoded else "abstained"), "decoded count/status differs")
    _false_authority(value)
    return _projection(value)


def _logits(reference, actual, count):
    _require(type(reference) is dict and type(actual) is dict and set(reference) == set(actual) == OUTPUTS,
             "all four saved logit arrays required")
    errors = {}
    for name in sorted(OUTPUTS):
        shape, values = _shapes(reference[name])
        other_shape, others = _shapes(actual[name])
        expected = (count, 3) if name == "modality" else (count, 4, 2) if name == "presence" else (count, 6, 5)
        _require(shape == other_shape == expected, "saved complete logit shape differs")
        _require(all(type(number) is float and _float32(number) == number for number in values + others),
                 "saved logits are not exact float32 serialization")
        error = max(abs(_float32(left - right)) for left, right in zip(values, others))
        _require(error <= 5e-5, "four-logit CPU/private parity exceeds5e-5")
        errors[name] = error
    return errors


def _timing(value, repetitions, sample_count=3):
    samples = value["samples_seconds_per_call"]
    _require(type(samples) is list and len(samples) == sample_count and all(_number(number) > 0 for number in samples),
             "exact positive timing sample count required")
    _require(_integer(value["sample_count"]) == sample_count and _integer(value["repetitions_per_sample"]) == repetitions
             and _number(value["median_seconds"]) == statistics.median(samples), "timing median/repetition profile differs")
    return value["median_seconds"]


def _ratio(actual, left, right):
    _require(_number(actual) > 0 and math.isclose(actual, left / right, rel_tol=1e-12, abs_tol=1e-15),
             "reported warm timing ratio differs from retained raw samples")


def _precision(profile, observation, device):
    receipt = observation["gru_precision"]
    _require(receipt["device"] == device and receipt["persistent_flags_mutated"] is False, "GRU precision device/persistence differs")
    if device == "cpu":
        _require(receipt["profile_id"] == SESSION_PROFILE and receipt["scoped_cudnn"] is False, "CPU opt-out GRU profile differs")
        return
    ambient = profile["precision_policy"]["ambient_at_admission"]
    effective = {**ambient, "cudnn": {**ambient["cudnn"], "allow_tf32": False}}
    _require(ambient["cuda_matmul_allow_tf32"] is False and ambient["float32_matmul_precision"] == "highest"
             and receipt["profile_id"] == GRU_PROFILE and receipt["scoped_cudnn"] is True
             and receipt["ambient_policy"] == ambient and receipt["effective_policy"] == effective
             and receipt["synchronized_before_restore"] is True and receipt["ambient_flags_restored"] is True
             and receipt["requires_owned_process_without_unrelated_concurrent_cudnn"] is True,
             "strict CUDA GRU effective policy/restoration differs")


def _forward(observation, count, profile, device):
    _require(_integer(observation["rows"]) == count and observation["source_tokens"] == [5] * count
             and observation["input_device"] == device and _integer(observation["native_input_dimension"]) == 4096
             and observation["output_devices"] == {name: device for name in OUTPUTS}
             and observation["output_dtype"] == "float32" and observation["gru_executed"] is True,
             "actual reported forward width/device/source coverage differs")
    _precision(profile, observation, device)


def _guard_identity(receipt, *, bitwise, device, optimized, source_sha256):
    _require(type(receipt) is dict, "plain owned tensor receipt mapping required")
    schema = "owned-tensor-bitwise-value-guard/v1" if bitwise else "owned-tensor-value-guard/v1"
    implementation_schema = "owned-tensor-bitwise-guard-implementation/v1" if bitwise else "owned-tensor-value-guard-implementation/v1"
    comparison = "finite-float32-exact-bits-with-reference-finiteness/v1" if bitwise else "finite-float32-exact-values-and-signed-zero/v1"
    mode = ("cpu_reference_checks" if device == "cpu" else
            "cuda_bitwise_single_host_decision" if bitwise and optimized else
            "cuda_single_host_decision" if optimized else "cuda_reference_checks")
    _require(receipt["schema"] == schema and receipt["mode"] == mode and receipt["comparison_device"] == device
             and receipt["implementation"] == {"schema": implementation_schema, "comparison": comparison,
                  "source_sha256": source_sha256}, "exact lane-specific guard schema/mode/comparison source join differs")


def _profile(profile, lane, report, checkpoint, digests, sources):
    optimized, variant = lane in ("cuda_batched", "bitwise_cuda_batched"), lane.startswith("bitwise_")
    device = "cuda:" + str(_integer(report["hardware"]["device_index"], 0, 255)) if optimized else "cpu"
    variant_profile = SEQUEL_SCHEMAS.get(report["schema"])
    _require(profile.get("session_profile_id") == variant_profile if variant else "session_profile_id" not in profile,
             "explicit original/bitwise lane session identity differs")
    expected_profile = variant_profile if variant and optimized else SESSION_PROFILE
    _require(profile["profile_id"] == expected_profile and profile["strict_cuda_gru_profile_id"] == GRU_PROFILE
             and _integer(profile["dimension"]) == 4096 and profile["device"] == device and profile["dtype"] == "float32"
             and profile["optimized"] is optimized and profile["numerical_batching"] ==
             ("one_complete_valid_source_batch" if optimized else "singleton_cpu_opt_out")
             and profile["checkpoint_sha256"] == digests["checkpoint_sha256"]
             and profile["optimizer_state_sha256"] == digests["optimizer_state_sha256"]
             and profile["stored_checkpoint_device"] == "cpu" and profile["checkpoint_conversion_performed"] is False
             and profile["inference_only"] is True and profile["synthetic_unreceipted_enabled"] is True
             and profile["canonical_decision_device"] == "cpu", "private session profile differs")
    anchor = profile["reference_byte_currentness"]
    for name in ("checkpoint_sha256", "anchor_sha256", "reference_bytes"):
        _require(anchor[name] == digests[name], "independent checkpoint byte anchor differs")
    _require(anchor["schema"] == "native-4096-owned-reference-byte-currentness/v1"
             and anchor["reference_device"] == device and anchor["origin"] == "independently_restored_validated_cpu_checkpoint_model"
             and anchor["comparison"] == "complete_immutable_float32_bytes_including_signed_zero"
             and _integer(anchor["device_to_cpu_reference_transfers"]) == int(optimized)
             and _integer(anchor["cpu_byte_materializations"]) == 1 and anchor["anchor_identity_checked"] is True
             and anchor["metadata_and_reservation_checked_before_allocation"] is True, "reference anchor copy/custody scope differs")
    guard = profile["owned_tensor_currentness"]
    guard_source = sources["bitwise_primitive_candidate" if variant else "tensor_guard"]["sha256"]
    _guard_identity(guard, bitwise=variant, device=device, optimized=optimized, source_sha256=guard_source)
    _require(guard["implementation"]["source_sha256"] == guard_source and guard["comparison_device"] == device
             and _integer(guard["tensor_count"]) == len(_weight_shapes())
             and _integer(guard["state_and_reference_bytes"]) == 2 * digests["reference_bytes"]
             and _integer(guard["host_decision_count"]) == (1 if optimized else 4 * len(_weight_shapes()))
             and all(guard[name] is True for name in ("finite_values_checked", "signed_zero_checked", "all_current_values_checked")),
             "owned tensor guard byte/profile/host decision join differs")
    implementation = profile["implementation"]
    if variant:
        _require("bitwise_device_session" in sources and implementation["source_sha256"] == sources["bitwise_device_session"]["sha256"]
                 and implementation["bitwise_guard_source_sha256"] == guard_source
                 and implementation["inherited_session_source_sha256"] == sources["device_session"]["sha256"]
                 and profile["inherited_profile_id"] == SESSION_PROFILE and profile["boundary_consolidation_performed"] is False,
                 "explicit bitwise session source/profile differs")
        implementation = implementation["inherited_session_implementation"]
    _require(implementation["source_sha256"] == sources["device_session"]["sha256"]
             and implementation["native4096_checkpoint_producer"] == checkpoint["implementation"]
             and implementation["owned_tensor_value_guard_sha256"] == sources["tensor_guard"]["sha256"],
             "session/checkpoint/value-guard retained source joins differ")
    policy = profile["precision_policy"]
    _require(policy["persistent_flags_mutated"] is False and policy["cuda_gru_allow_tf32"] is (False if optimized else None),
             "session persistent/scoped precision differs")
    lease = profile["resource_lease"]
    _require(lease["parent_lease_id"] == report["admission"]["lease_id"] and lease["owner_pid"] == report["pid"]
             and lease["requires_gpu"] is optimized and _integer(lease["memory_mb"]) == 1024
             and _integer(lease["gpu_memory_mb"]) == (256 if optimized else 0), "reported child lease binding differs")
    _false_authority(profile)
    return device


def _head(reader, report, rows, checkpoint, digests, sources):
    sequel = report["schema"] in SEQUEL_SCHEMAS
    lanes = ("cpu", "cuda_batched", "bitwise_cpu", "bitwise_cuda_batched") if sequel else ("cpu", "cuda_batched")
    _require(set(report["lanes"]) == set(lanes), "complete explicit CPU/CUDA head lanes required")
    _require(report["cpu_reference_numeric_profile"] == {"device": "cpu", "dtype": "float32",
             "numeric_batching": "actual_singleton_forwards_concatenated", "equal_fixture_token_width_required": True,
             "used_for_four_logit_parity": True}, "actual singleton reference numerical profile differs")
    refs, logits, errors, medians = {}, {}, {}, {}
    for count in COUNTS:
        key = str(count)
        reference = reader.json(f"head-cpu-reference-batch{count}.json", report["cpu_reference_results"][key])
        _require(reference["schema"] == "native-4096-source-span-inference/v1"
                 and reference["synthetic_architecture_control"] is True, "independent CPU reference schema differs")
        refs[key] = _decisions(reference, rows[:count], checkpoint, digests)
        logits[key] = reader.json(f"head-cpu-singleton-reference-batch{count}-logits.json", report["cpu_reference_logits"][key])
        # Validate singleton arrays independently, including all four shapes.
        _logits(logits[key], logits[key], count)
        if "cpu_reference_decision_projections" in report:
            projection = reader.json(f"head-cpu-reference-batch{count}-canonical-projection.json",
                                     report["cpu_reference_decision_projections"][key])
            _require(projection == refs[key], "retained CPU canonical projection differs from public rows")
    for lane in lanes:
        optimized = lane in ("cuda_batched", "bitwise_cuda_batched")
        value = report["lanes"][lane]
        _require(set(value["batches"]) == {str(count) for count in COUNTS} and value["own_child_lease_released"] is True,
                 "complete head batches/child cleanup required")
        _number(value["constructor_seconds"])
        device = _profile(value["profile"], lane, report, checkpoint, digests, sources)
        _profile(value["final_profile"], lane, report, checkpoint, digests, sources)
        medians[lane] = {}
        for count in COUNTS:
            key = str(count)
            batch = value["batches"][key]
            medians[lane][key] = _timing(batch, 1, 4 if sequel and optimized else 3)
            actual = reader.json(f"head-{lane}-batch{count}.json", batch["result"])
            _require(actual["schema"] == "native-4096-source-span-device-inference/v1"
                     and actual["cuda_executed"] is optimized and actual["numerical_batching"] is optimized
                     and _integer(actual["valid_source_count"]) == count and actual["synthetic_embeddings"] is True,
                     "public head actual lane/count differs")
            projection = _decisions(actual, rows[:count], checkpoint, digests)
            _require(projection == refs[key] and batch["canonical_rows_match_cpu"] is True,
                     "exact canonical/source/span/flag decision projection differs")
            if "canonical_projection" in batch:
                retained = reader.json(f"head-{lane}-batch{count}-canonical-projection.json", batch["canonical_projection"])
                _require(retained == projection, "retained private canonical projection differs from public rows")
                _require(batch["canonical_reference_projection"] == report["cpu_reference_decision_projections"][key],
                         "canonical projection reference pin differs")
            _profile(actual["execution_profile"], lane, report, checkpoint, digests, sources)
            forwards = actual["actual_forward_batches"]
            _require(type(forwards) is list and len(forwards) == (1 if optimized else count), "public forward coverage differs")
            for observation in forwards:
                _forward(observation, count if optimized else 1, actual["execution_profile"], device)
            _require(_integer(actual["device_to_cpu_head_transfers"]) == (4 if optimized else 0)
                     and _integer(actual["cpu_head_output_materializations"]) == (4 if optimized else 0),
                     "public CPU decision materialization profile differs")
            numeric = reader.json(f"head-{lane}-batch{count}-logits.json", batch["logits"])
            error = _logits(logits[key], numeric, count)
            _require(set(batch["four_logit_max_abs_errors"]) == OUTPUTS and
                     all(_number(batch["four_logit_max_abs_errors"][name]) == error[name] for name in OUTPUTS),
                     "reported logit max errors differ from retained float32 arrays")
            errors[lane + "-" + key] = error
            scope = batch["numeric_scope"]
            _require(scope["scope"] == "benchmark_only_checked_private_forward"
                     and scope["entry_and_exit_owned_session_checks"] is True
                     and scope["public_cpu_opt_out_still_uses_singletons"] is True
                     and len(scope["observations"]) == 1, "checked private numeric scope differs")
            _forward(scope["observations"][0], count, actual["execution_profile"], device)
        paired = value["paired_reference_corruption_refusals"]
        labels = {"paired_finite_value", "paired_signed_zero", "anchor_object_replacement"}
        _require(type(paired) is list and len(paired) == 3 and {item["corruption"] for item in paired} == labels,
                 "complete v2 anchor paired/reference controls required")
        for item in paired:
            needle = "immutable reference byte anchor changed" if item["corruption"] == "anchor_object_replacement" else "reference bytes changed from admitted checkpoint"
            _require(item["refused"] is True and item["entry_refused_before_forward"] is True
                     and type(item["refusal"]) is str and needle in item["refusal"], "paired mutation/anchor refusal claim differs")
        subnormal = value["model_only_subnormal_control"]
        _require(subnormal["corruption"] == "model_only_smallest_positive_float32_subnormal"
                 and _integer(subnormal["actual_float32_bits_int32"]) == 1 and type(subnormal["refused"]) is bool,
                 "actual model-only subnormal control profile differs")
        if report["architecture_fixture_qualified"]:
            _require(subnormal["refused"] is True and subnormal["entry_refused_before_forward"] is True
                     and type(subnormal["refusal"]) is str, "model-only subnormal escaped a qualified head session")
    for key in (str(count) for count in COUNTS):
        _ratio(report["head_warm_speedups_cpu_over_cuda_batched"][key], medians["cpu"][key], medians["cuda_batched"][key])
    if sequel:
        _session_timings(report, medians)
    return errors


def _session_timings(report, medians):
    """Recompute complete-call ratios independently of standalone guard gains."""
    timing = report["cuda_pair_timing_profile"]
    _require(timing["sample_count_per_lane_per_batch"] == 4 and timing["each_lane_first_per_batch"] == 2
             and timing["native_forwards_overlap"] is False and timing["source_guard_or_anchor_boundary_removed"] is False
             and set(timing["batches"]) == {str(count) for count in COUNTS}, "paired serial CUDA timing scope differs")
    for position, count in enumerate(COUNTS):
        labels = ["cuda_batched", "bitwise_cuda_batched"]
        expected = [labels[::-1] if (bool(trial % 2) != bool(position % 2)) else labels for trial in range(4)]
        _require(timing["batches"][str(count)] == {"completed_call_orders": expected}, "completed CUDA alternating orders differ")
    ratios = {"full_session_speedups_v2_cuda_over_bitwise_cuda": ("cuda_batched", "bitwise_cuda_batched"),
        "full_session_speedups_v2_cpu_over_bitwise_cpu": ("cpu", "bitwise_cpu"),
        "head_warm_speedups_cpu_over_bitwise_cuda_batched": ("cpu", "bitwise_cuda_batched"),
        "head_warm_speedups_bitwise_cpu_over_bitwise_cuda_batched": ("bitwise_cpu", "bitwise_cuda_batched")}
    for field, (left, right) in ratios.items():
        _require(set(report[field]) == {str(count) for count in COUNTS}, "complete full-session ratio batches required")
        for count in COUNTS:
            key = str(count)
            _ratio(report[field][key], medians[left][key], medians[right][key])
    faster = [str(count) for count in COUNTS if medians["cuda_batched"][str(count)] / medians["bitwise_cuda_batched"][str(count)] > 1.]
    _require(report["bitwise_full_session_faster_batches"] == faster
             and report["bitwise_full_session_speedup_demonstrated"] is bool(faster),
             "complete-call speedup claim differs from retained samples")


def _guard(report, sources):
    guard = report["guard"]
    lanes = ["cuda_reference", "cuda_combined"]
    if report["optional_bitwise_primitive_enabled"]:
        lanes.append("cuda_bitwise_candidate")
    _require(guard["tensor_shapes"] == {"adapter": [128, 4096], "gru": [128, 128]}
             and guard["timing_includes_complete_current_value_and_source_checks"] is True,
             "standalone guard complete tensor/timing scope differs")
    medians = {}
    device = "cuda:" + str(report["hardware"]["device_index"])
    for lane in lanes:
        entry = guard[lane]
        medians[lane] = _timing(entry, 8)
        receipt = entry["receipt"]
        role = "bitwise_primitive_candidate" if lane == "cuda_bitwise_candidate" else "tensor_guard"
        _guard_identity(receipt, bitwise=lane == "cuda_bitwise_candidate", device=device,
                        optimized=lane != "cuda_reference", source_sha256=sources[role]["sha256"])
        _require(receipt["implementation"]["source_sha256"] == sources[role]["sha256"]
                 and receipt["comparison_device"] == device and _integer(receipt["tensor_count"]) == 2
                 and _integer(receipt["state_and_reference_bytes"]) == 2 * 4 * (128 * 4096 + 128 * 128)
                 and _integer(receipt["host_decision_count"]) == (8 if lane == "cuda_reference" else 1)
                 and all(receipt[key] is True for key in ("finite_values_checked", "signed_zero_checked", "all_current_values_checked")),
                 "guard source/tensor/full currentness/host decision profile differs")
    _ratio(guard["speedup_reference_over_combined"], medians["cuda_reference"], medians["cuda_combined"])
    if "cuda_bitwise_candidate" in lanes:
        _ratio(guard["speedup_reference_over_bitwise_candidate"], medians["cuda_reference"], medians["cuda_bitwise_candidate"])
        _ratio(guard["speedup_combined_over_bitwise_candidate"], medians["cuda_combined"], medians["cuda_bitwise_candidate"])
    expected_bits = {"changed_value": 1065353216, "signed_zero": -2147483648,
                     "smallest_positive_float32_subnormal": 1, "nan": 2143289344, "inf": 2139095040}
    expected = {(lane, owner, corruption) for lane in lanes for owner in ("state", "reference") for corruption in expected_bits}
    observations, seen = guard["native_corruption_refusals"], set()
    _require(type(observations) is list and len(observations) == len(expected), "complete native guard corruption coverage required")
    integrity = {lane: True for lane in lanes}
    for item in observations:
        key = (item["lane"], item["owner"], item["corruption"])
        _require(key in expected and key not in seen and type(item["refused"]) is bool
                 and item["optimized"] is (item["lane"] != "cuda_reference")
                 and type(item["actual_float32_bits_int32"]) is int
                 and item["actual_float32_bits_int32"] == expected_bits[item["corruption"]],
                 "native corruption lane/owner/actual-bit coverage differs")
        seen.add(key)
        if item["refused"]:
            _require(type(item["refusal"]) is str and bool(item["refusal"]), "claimed guard refusal has no reason")
        else:
            _require(item["refusal"] is None, "accepted corruption falsely reports a refusal")
            integrity[item["lane"]] = False
    _require(guard["lane_integrity_qualified"] == integrity and all(type(x) is bool for x in guard["lane_integrity_qualified"].values()),
             "reported guard lane integrity differs from corruption refusals")
    _require(guard["native_guard_primitive_qualified"] is all(integrity[lane] for lane in ("cuda_reference", "cuda_combined"))
             and guard["native_bitwise_guard_primitive_qualified"] is ("cuda_bitwise_candidate" in lanes and integrity.get("cuda_bitwise_candidate", False)),
             "guard aggregate qualification differs from corruption controls")
    if report["architecture_fixture_qualified"]:
        _require(all(integrity.values()), "qualified fixture contains accepted native corruption")
    if report["schema"] in SEQUEL_SCHEMAS:
        _require(guard["candidate_integrated_into_timed_head_session"] is True
                 and guard["integration_scope"] == ["bitwise_cpu", "bitwise_cuda_batched"],
                 "new session comparator integration scope differs")
        observations = guard["native_equal_nonfinite_pair_refusals"]
        expected = {(lane, corruption) for lane in lanes for corruption in ("paired_equal_nan_bits", "paired_equal_inf_bits")}
        _require(type(observations) is list and len(observations) == 6, "complete equal nonfinite pair controls required")
        seen = set()
        for item in observations:
            key = item["lane"], item["corruption"]
            bits = 2143289344 if item["corruption"] == "paired_equal_nan_bits" else 2139095040
            _require(key in expected and key not in seen and item["optimized"] is (item["lane"] != "cuda_reference")
                     and type(item["state_float32_bits_int32"]) is int and type(item["reference_float32_bits_int32"]) is int
                     and item["state_float32_bits_int32"] == item["reference_float32_bits_int32"] == bits
                     and type(item["refused"]) is bool, "equal nonfinite pair lane/actual bits differ")
            seen.add(key)
            _require((item["refused"] and type(item["refusal"]) is str and bool(item["refusal"]))
                     or (not item["refused"] and item["refusal"] is None), "equal nonfinite pair refusal reason differs")
            if report["architecture_fixture_qualified"]:
                _require(item["refused"] is True, "qualified session accepts equal nonfinite bits")
    return integrity


def _cleanup(report, *, positive):
    _require("resources_after" not in report or type(report["resources_after"]) is dict,
             "plain reported resource cleanup mapping required")
    result = {"reported_own_root_lease_released": report.get("own_root_lease_released"),
              "reported_after_workspace_allocation_bytes": report.get("gpu_allocated_after_framework_workspace_clear_bytes"),
              "reported_active_leases": report.get("resources_after", {}).get("active_lease_count"),
              "reported_cleanup_errors": {name: value for name, value in report.items() if name.endswith("_error")}}
    if not positive:
        for key in ("gpu_allocated_before_owned_sessions_bytes", "gpu_allocated_after_owned_sessions_closed_bytes",
                    "gpu_allocated_after_framework_workspace_clear_bytes"):
            if key in report:
                _integer(report[key])
        return result
    _require(not result["reported_cleanup_errors"], "qualified run contains a cleanup error")
    _require(report["own_root_lease_released"] is True and report["guard_child_lease_released"] is True
             and report["root_release_does_not_force_child_release"] is True and report["cpu_threads_restored"] is True,
             "owned root/guard child/thread cleanup differs")
    before = _integer(report["gpu_allocated_before_owned_sessions_bytes"])
    after = _integer(report["gpu_allocated_after_framework_workspace_clear_bytes"])
    closed = _integer(report["gpu_allocated_after_owned_sessions_closed_bytes"])
    supported = report["framework_cuda_workspace_clear_supported"]
    _require(before == after == 0 and closed >= after and type(supported) is bool and (supported or closed == 0),
             "reported postclose CUDA allocation did not return to admitted zero baseline")
    _require(report["cuda_cleanup_status"] == "owned_allocations_restored_to_baseline", "reported CUDA cleanup status differs")
    state = report["resources_after"]
    for key in ("active_lease_count", "active_child_lease_count", "active_root_lease_count", "allocated_child_process_slots",
                "allocated_gpu_memory_mb", "allocated_unified_memory_mb"):
        _require(_integer(state[key]) == 0, "reported resource cleanup is nonzero")
    _require(state["allocated"] == {"cpu_slots": 0, "memory_mb": 0}, "reported CPU/RAM allocation cleanup is nonzero")
    return result


def _audit(reader, report, current):
    _require(type(report) is dict and report["schema"] in (BASE_SCHEMA, *SEQUEL_SCHEMAS),
             "explicit supported synthetic4096 device report required")
    _require(type(report["architecture_fixture_qualified"]) is bool and type(report["head_numerical_fixture_qualified"]) is bool
             and type(report["optional_bitwise_primitive_enabled"]) is bool, "plain report qualification flags required")
    _false_authority(report)
    sources = _source_join(reader, report, current)
    positive = report["architecture_fixture_qualified"]
    sequel = report["schema"] in SEQUEL_SCHEMAS
    if sequel:
        _require(report["optional_bitwise_primitive_enabled"] is True
                 and report["bitwise_full_session_fixture_qualified"] is positive
                 and report["complete_gpu_session_speedups_qualified"] is positive,
                 "separate session fixture/timing qualification differs")
    checks = {"retained_source_count": len(sources), "numeric_report_checked": False,
              "failed_run_remains_unqualified": not positive, **_cleanup(report, positive=positive)}
    if positive:
        _require(report["error"] is None and report["head_numerical_fixture_qualified"] is True
                 and not report.get("qualification_refusals"), "qualified fixture contains failure/refusal")
    if not report["head_numerical_fixture_qualified"]:
        _require(not positive and (report["error"] is not None or report.get("qualification_refusals")),
                 "unfinished report lacks failure/refusal")
        # Every available explicitly pinned datum is read, but missing or
        # incomplete numeric lanes never become a successful numerical audit.
        for key, name in (("checkpoint", "synthetic-untrained-checkpoint.json"), ("rows", "synthetic-inputs.json")):
            if key in report:
                _false_authority(reader.json(name, report[key]))
        reader.final_check()
        return checks
    optional = set() if sequel else {"bitwise_primitive_candidate", "bitwise_device_session"}
    _require(set(_report_source_paths(report["schema"])) - optional <= set(sources), "complete intended retained producer bundle required")
    _require(report["source_bytes_unchanged"] is True and report["checkpoint_unchanged"] is True and report["adam_unchanged"] is True
             and all(_integer(report[key]) == 0 for key in ("encoder_calls", "optimizer_steps", "training_calls", "optimizer_construction_attempts"))
             and report["foreign_process_actions"] is False and report["persistent_precision_policy_mutated"] is False,
             "fixture producer immutability/no-fit/no-encoder scope differs")
    _require(report["precision_policy_before"] == report["precision_policy_after"]
             and report["precision_policy_before"]["cuda_matmul_allow_tf32"] is False
             and report["precision_policy_before"]["float32_matmul_precision"] == "highest", "persistent precision policy was not restored")
    _require(report["actual_initial_cuda_kernel"] is True and report["initial_cuda_kernel_output"] == [4.]
             and _integer(report["gpu_allocated_after_producer_imports_bytes"]) == 0
             and report["producer_imports_preserved_zero_cuda_allocation"] is True, "reported initial kernel/import zero-allocation profile differs")
    for entry in report["module_import_context_diagnostics"]:
        _require(_integer(entry["gpu_allocated_before_bytes"]) == _integer(entry["gpu_allocated_after_bytes"]) == 0,
                 "reported producer import allocated CUDA tensors")
    admission = report["admission"]
    _require(admission["owner_pid"] == report["pid"] and admission["parent_lease_id"] is None
             and admission["requires_gpu"] is True and _integer(admission["memory_mb"]) == 2048
             and _integer(admission["gpu_memory_mb"]) == 512 and _integer(admission["unified_memory_mb"]) == 2560,
             "reported owned root admission profile differs")
    rows, checkpoint, digests = _fixture(reader, report, sources)
    checks["head_logit_max_abs_errors"] = _head(reader, report, rows, checkpoint, digests, sources)
    checks["guard_lane_integrity"] = _guard(report, sources)
    checks["numeric_report_checked"] = True
    if sequel:
        checks["bitwise_full_session_fixture_qualified"] = positive
        checks["complete_call_timing_report_qualified"] = positive
        checks["bitwise_full_session_speedup_demonstrated"] = report["bitwise_full_session_speedup_demonstrated"]
        checks["full_session_speedups_v2_cuda_over_bitwise_cuda"] = report["full_session_speedups_v2_cuda_over_bitwise_cuda"]
    checks["independent_checkpoint_reference_anchor_sha256"] = digests["anchor_sha256"]
    reader.final_check()
    return checks


def audit(root, *, expected_result_sha256, check_current_sources=False):
    """Audit immutable report bytes against an externally supplied result pin.

    ``qualified`` preserves the producer's architecture-fixture status after
    ordinary consistency checks. It never means native execution attestation.
    ``closed_artifacts_consistent`` may be true for a failed, unqualified run.
    """
    result = {"schema": "synthetic4096-device-closed-audit/v1", "qualified": False,
              "closed_artifacts_consistent": False, "native_execution_attested": False,
              "native_leanstral_outputs_qualified": False, "production_qualified": False,
              "proof_authority": False, "resource_enforcement_attested": False,
              "scope": "ordinary_retained_bytes_and_report_consistency",
              "check_current_sources": check_current_sources, "retained_pins": [], "error": None}
    reader = None
    try:
        _sha(expected_result_sha256)
        _require(type(check_current_sources) is bool, "current-source option must be a plain boolean")
        reader = _Reader(root)
        raw = reader.read("result.json")
        _require(reader.pins["result.json"]["sha256"] == expected_result_sha256, "external result SHA256 differs")
        report = _json(raw)
        _require(type(report) is dict, "plain producer report object required")
        result["producer_architecture_fixture_qualified"] = report.get("architecture_fixture_qualified")
        result["producer_head_numerical_fixture_qualified"] = report.get("head_numerical_fixture_qualified")
        result["producer_error"] = report.get("error")
        result["checks"] = _audit(reader, report, check_current_sources)
        result["closed_artifacts_consistent"] = True
        result["qualified"] = report["architecture_fixture_qualified"]
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
    result = audit(args.root, expected_result_sha256=args.expected_result_sha256,
                   check_current_sources=args.check_current_sources)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["closed_artifacts_consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
