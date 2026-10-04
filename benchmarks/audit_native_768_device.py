"""Ordinary bounded reader for an externally SHA-pinned native768 archive.

This verifies retained byte joins, numerical parity and report consistency. It
does not load a model, open an owner, prove native execution, or turn reported
resource counters into process/resource authority. No retained Python is run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import statistics

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
DIMENSION = 768
TOLERANCE = 5e-5
MANIFEST_SHA256 = "8beb874aa7b06599346173fde12e95f9f926b3028942d5014cdd2f99c4385166"
MODEL_REVISION = "9bbca17d9273fd0d03d5725c7a4b0f6b45142062"
CODE_REVISION = "40ced75c3017eb27626c9d4ea981bde21a2662f4"
MODEL_ID = "Alibaba-NLP/gte-multilingual-base"
REFERENCE_PROFILE = (f"{MODEL_ID}@{MODEL_REVISION}:code=Alibaba-NLP/new-impl@{CODE_REVISION}:"
                     "d768:pool=cls:norm=l2:cpu:float32:tokens8192:reject_overlength:v1")
SOURCE_FILES = (
    "benchmarks/qualify_native_768_device.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_device_768.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768_complete.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_multilingual_profile.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_device_inference.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_dimensions.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_formula.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_formula_codec.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/checkpoint_content_guard.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_device_batch_inference.py",
)
PRODUCER_COPIES = tuple(f"producers/{i:02d}-{Path(path).name}" for i, path in enumerate(SOURCE_FILES))
FIXED_JSON_FILES = frozenset({
    "result.json", "source-rows.json", "encoder-reference.json",
    "diagnostic-training-index.json", "diagnostic-source-training-index.json",
    "diagnostic-source-parent.json", "diagnostic-native768-head.json",
    "diagnostic-parent-fit-report.json", "diagnostic-child-fit-report.json",
    "head-native-reference.json", "head-native-reference-logits.json", "inherited-head-source-result.json",
    *[f"encoder-{lane}-warmup.json" for lane in ("cpu", "cuda")],
    *[f"encoder-{lane}-batch{count}.json" for lane in ("cpu", "cuda") for count in (1, 16, 32)],
    *[f"head-{lane}-logits.json" for lane in ("cpu", "cuda", "cuda_batched")],
    *[f"head-{lane}-batch{count}.json" for lane in ("cpu", "cuda", "cuda_batched") for count in (1, 16, 32)],
})
AUTHORITY_FLAGS = ("proof_authority", "source_semantics_verified", "semantic_correctness_verified",
                   "execution_authority", "promotion_performed", "publication_performed")
DECISION_KEYS = ("source_sha256", "latent_sha256", "status", "reason", "detail", "canonical_ir",
                 "formula_text", "formal_outputs", "family_syntax_checked", "latent_input_enabled")


class AuditError(ValueError):
    """The retained evidence is incomplete or inconsistent."""


def _require(condition, message):
    if not condition:
        raise AuditError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "lowercase SHA256 required")
    return value


def _integer(value, minimum=0, maximum=2**63-1):
    _require(type(value) is int and minimum <= value <= maximum, "bounded plain integer required")
    return value


def _number(value):
    _require(type(value) in (int, float), "finite plain number required")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    _require(finite, "finite plain number required")
    return value


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def reject(value):
        raise AuditError("nonfinite JSON constant: " + value)
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(depth <= 64 and nodes <= 1000000, "JSON depth/node bound exceeded")
        if type(item) is dict:
            pending.extend((part, depth + 1) for part in item.values())
        elif type(item) is list:
            pending.extend((part, depth + 1) for part in item)
        elif type(item) in (float, int):
            _number(item)
    return value


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _open_directory(path):
    path = Path(path).absolute()
    _require(".." not in path.parts, "canonical directory path required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


class _Reader:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.fd = _open_directory(self.root)
        self.directory_identity = _identity(os.fstat(self.fd))[:4]
        self.total, self.pins, self.identities = 0, {}, {}

    def close(self):
        os.close(self.fd)

    def _open(self, name):
        _require(name in FIXED_JSON_FILES or name in PRODUCER_COPIES, "unlisted retained path refused")
        if "/" not in name:
            return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        parent = os.open("producers", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            return os.open(name.split("/")[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)

    def read(self, name, pin=None):
        _require(name not in self.pins, "retained path read twice")
        fd = self._open(name)
        try:
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                     and 0 < before.st_size <= MAX_FILE_BYTES, "bounded single-link regular file required")
            _require(self.total + before.st_size <= MAX_TOTAL_BYTES, "archive total byte bound exceeded")
            raw = bytearray()
            while len(raw) <= MAX_FILE_BYTES:
                part = os.read(fd, min(65536, MAX_FILE_BYTES + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
            after = os.fstat(fd)
            _require(_identity(before) == _identity(after) and len(raw) == before.st_size,
                     "retained file changed while reading")
            actual = {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            if pin is not None:
                _require(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}, "closed file pin required")
                _require(pin["path"] == str(self.root / name), "retained pin path differs from fixed path")
                _integer(pin["bytes"], 1, MAX_FILE_BYTES)
                _sha(pin["sha256"])
                _require(actual["bytes"] == pin["bytes"] and actual["sha256"] == pin["sha256"],
                         "retained bytes differ from report pin: " + name)
            self.total += len(raw)
            self.pins[name], self.identities[name] = actual, _identity(after)
            return bytes(raw)
        finally:
            os.close(fd)

    def json(self, name, pin=None):
        return _json(self.read(name, pin))

    def final_check(self):
        current = _open_directory(self.root)
        try:
            _require(_identity(os.fstat(current))[:4] == self.directory_identity, "retained root identity changed")
        finally:
            os.close(current)
        for name, identity in self.identities.items():
            fd = self._open(name)
            try:
                _require(_identity(os.fstat(fd)) == identity, "retained path changed after read: " + name)
            finally:
                os.close(fd)


def _false_authority(value):
    if type(value) is dict:
        for key, part in value.items():
            if key in AUTHORITY_FLAGS:
                _require(part is False, "retained report asserts authority: " + key)
            _false_authority(part)
    elif type(value) is list:
        for part in value:
            _false_authority(part)


def _vectors(value, count):
    _require(type(value) is list and len(value) == count, "vector row coverage differs")
    for vector in value:
        _require(type(vector) is list and len(vector) == DIMENSION, "native vector dimension differs")
        _require(all(abs(_number(number)) <= 3.4028234e38 for number in vector), "float32 vector bound exceeded")
        _require(abs(math.hypot(*vector) - 1.) <= 1e-4, "native vector is not L2-normalized")
    return value


def _parity(left, right):
    _require(len(left) == len(right), "numeric row coverage differs")
    error = max(abs(a-b) for aa, bb in zip(left, right) for a, b in zip(aa, bb))
    _require(math.isfinite(error) and error <= TOLERANCE, "numeric parity exceeds5e-5")
    return error


def _shape_numbers(value):
    if type(value) is list:
        _require(bool(value), "empty numeric tensor")
        parts = [_shape_numbers(part) for part in value]
        _require(all(shape == parts[0][0] for shape, _ in parts), "ragged numeric tensor")
        return (len(value), *parts[0][0]), [number for _, numbers in parts for number in numbers]
    return (), [_number(value)]


def _logits(native, actual):
    names = {"modality", "presence", "start", "end"}
    _require(type(native) is dict and type(actual) is dict and set(native) == set(actual) == names,
             "closed native logit fields required")
    errors = {}
    for name in sorted(names):
        shape, values = _shape_numbers(native[name])
        other_shape, other_values = _shape_numbers(actual[name])
        expected = (16, 3) if name == "modality" else (16, 4, 2) if name == "presence" else None
        _require(shape == other_shape and (shape == expected if expected else
                 len(shape) == 3 and shape[:2] == (16, 6) and 1 <= shape[2] <= 256), "native logit shape differs")
        error = max(abs(a-b) for a, b in zip(values, other_values))
        _require(math.isfinite(error) and error <= TOLERANCE, "head logit parity exceeds5e-5")
        errors[name] = error
    _require(_shape_numbers(native["start"])[0] == _shape_numbers(native["end"])[0], "span logit widths differ")
    return errors


def _timing(value):
    samples = value["samples_seconds"]
    _require(type(samples) is list and len(samples) == 3 and all(_number(x) > 0 for x in samples),
             "three positive timing samples required")
    _require(_number(value["median_seconds"]) == statistics.median(samples), "timing median differs")


def _profile(profile, lane, device):
    _require(profile["schema"] == "source-embedding-device-768/v1" and profile["dimension"] == DIMENSION,
             "native768 encoder profile required")
    expected = {"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "code_revision": CODE_REVISION,
                "device": device, "optimized": lane == "cuda", "dtype": "float32", "pooling": "cls",
                "normalization": "l2", "attention_implementation": "eager", "overlength_policy": "reject",
                "max_tokens_including_special_tokens": 8192, "asset_manifest_sha256": MANIFEST_SHA256}
    _require(all(type(profile[key]) is type(value) and profile[key] == value for key, value in expected.items()),
             "encoder profile/device differs")
    unsigned = {key: value for key, value in profile.items() if key != "profile_sha256"}
    _require(profile["profile_sha256"] == _digest(unsigned), "encoder profile hash differs")
    expected_id = (f"{MODEL_ID}@{MODEL_REVISION}:code={CODE_REVISION}:d768:pool=cls:norm=l2:"
                   f"{lane}:float32:eager:tokens8192:reject_overlength:precision={_digest(profile['precision'])}:device-session-v1")
    _require(profile["profile_id"] == expected_id, "encoder profile identity differs")


def _receipt(receipt, source, vector, *, profile=None, token=None, reference=None):
    _require(receipt["id"] == source["id"] and receipt["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(),
             "source receipt join differs")
    _require(type(receipt["dimension"]) is int and receipt["dimension"] == DIMENSION
             and receipt["embedding"] == vector and receipt["asset_manifest_sha256"] == MANIFEST_SHA256
             and receipt["normalized"] is True and receipt["truncated"] is False, "embedding receipt differs")
    _integer(receipt["token_count_including_special_tokens"], 1, 8192)
    _sha(receipt["token_input_sha256"])
    if profile is not None:
        _require(receipt["profile_id"] == profile["profile_id"] and receipt["profile_sha256"] == profile["profile_sha256"]
                 and receipt["embedding_sha256"] == _digest(vector) and receipt["device"] == profile["device"]
                 and receipt["dtype"] == "float32", "device embedding receipt profile differs")
        _require(type(token) is dict and set(token) == {"input_ids", "attention_mask"}, "closed exact token input required")
        ids = token["input_ids"]
        _require(type(ids) is list and 1 <= len(ids) <= 8192 and all(type(x) is int and 0 <= x <= 2**31-1 for x in ids)
                 and token["attention_mask"] == [1] * len(ids), "untruncated native token input differs")
        _require(receipt["token_count_including_special_tokens"] == len(ids) and receipt["token_input_sha256"] == _digest(ids),
                 "token receipt does not match retained exact IDs")
    if reference is not None:
        _require(all(receipt[key] == reference[key] for key in ("token_input_sha256", "token_count_including_special_tokens")),
                 "independent token receipt parity differs")


def _encoder(actual, rows, reference, lane, device, *, warmup=False):
    count = len(rows)
    _require(actual["schema"] == "gte-native-device-embedding-production/v1" and actual["status"] == "completed"
             and actual["input_row_count"] == actual["receipt_count"] == count
             and type(actual["input_row_count"]) is int and type(actual["receipt_count"]) is int,
             "encoder report/row counts differ")
    _profile(actual["profile"], lane, device)
    _require(actual["profile_id"] == actual["profile"]["profile_id"]
             and actual["cuda_executed"] is (lane == "cuda") and actual["model_inference_executed"] is True
             and actual["training_executed"] is False, "encoder execution flags differ")
    vectors = _vectors(actual["vectors"], count)
    _require(len(actual["receipts"]) == len(actual["tokens"]) == count, "encoder retained input coverage differs")
    for source, vector, receipt, token, baseline in zip(rows, vectors, actual["receipts"], actual["tokens"], reference):
        _receipt(receipt, source, vector, profile=actual["profile"], token=token, reference=baseline)
    batches = actual["actual_forward_batches"]
    _require(type(batches) is list and len(batches) == (count + 15) // 16, "encoder forward count differs")
    for index, batch in enumerate(batches):
        width = max(len(token["input_ids"]) for token in actual["tokens"][index*16:(index+1)*16])
        size = min(16, count-index*16)
        _require(type(batch["rows"]) is int and batch["rows"] == size and batch["tokens_per_row"] == width
                 and batch["input_device"] == batch["output_device"] == device
                 and batch["output_dtype"] == "torch.float32" and batch["output_shape"] == [size, width, DIMENSION]
                 and type(batch["native_forward_calls"]) is int and batch["native_forward_calls"] == 1,
                 "encoder actual forward device/dtype/shape differs")
    if warmup:
        probe = actual["dense_path_verification"]
        _require(type(probe) is dict and probe["bitwise_equal"] is True and probe["native_forward_calls"] == 2
                 and probe["input_device"] == probe["output_device"] == device, "warmup complete-model path probe differs")
    else:
        _require(actual["dense_path_verification"] is None, "timed encoder unexpectedly re-admitted dense path")
    _false_authority(actual)
    return _parity([row["embedding"] for row in reference], vectors)


def _decisions(actual, rows, vectors):
    _require(type(actual["rows"]) is list and len(actual["rows"]) == len(rows), "head row coverage differs")
    for row, source, vector in zip(actual["rows"], rows, vectors):
        _require(row["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest()
                 and row["latent_sha256"] == _digest(vector) and row["latent_input_enabled"] is True,
                 "head source/latent receipt join differs")
        _require(row["status"] in ("decoded", "abstained"), "invalid head row status")
    decoded = sum(row["status"] == "decoded" for row in actual["rows"])
    _require(type(actual["decoded_count"]) is int and actual["decoded_count"] == decoded
             and actual["status"] == ("decoded" if decoded == len(rows) else "partial" if decoded else "abstained"),
             "head decoded counters differ")
    _false_authority(actual)
    return [{key: row.get(key) for key in DECISION_KEYS} for row in actual["rows"]]


def _checkpoint(checkpoint, steps, dimension):
    _require(type(checkpoint["progress"]["optimizer_steps"]) is int and checkpoint["progress"]["optimizer_steps"] == steps,
             "checkpoint optimizer step count differs")
    config = checkpoint["config"]
    _require(type(config["latent_dimension"]) is int and config["latent_dimension"] == dimension
             and config["latent_enabled"] is bool(dimension) and config["device"] == "cpu", "native checkpoint dimension/device differs")
    _require(config["hidden_size"] == 8 and config["embedding_dim"] == 4 and config["projection_width"] == 4
             and config["batch_size"] == 2, "diagnostic native head architecture differs")
    state, optimizer = checkpoint["model_state"], checkpoint["optimizer_state"]
    shapes = {"byte_embedding.weight": (257, 4), "token_projection.weight": (8, 13), "token_projection.bias": (8,)}
    for suffix in ("", "_reverse"):
        for name in ("weight_ih_l0", "weight_hh_l0"):
            shapes[f"encoder.{name}{suffix}"] = (24, 8)
        for name in ("bias_ih_l0", "bias_hh_l0"):
            shapes[f"encoder.{name}{suffix}"] = (24,)
    for name, width in (("modality", 3), ("presence", 8), ("start", 6), ("end", 6)):
        shapes[name + ".weight"], shapes[name + ".bias"] = (width, 16), (width,)
    if dimension:
        shapes.update({"latent_down.weight": (4, 768), "latent_down.bias": (4,),
                       "latent_up.weight": (16, 4), "latent_up.bias": (16,)})
    _require(type(state) is dict and set(state) == set(shapes) and optimizer["schema"] == "adam-default-betas-eps/v1"
             and set(optimizer["parameters"]) == set(state), "complete checkpoint Adam/model coverage differs")
    for name, weight in state.items():
        shape, _ = _shape_numbers(weight)
        moment = optimizer["parameters"][name]
        _require(shape == shapes[name] and type(moment["step"]) is int and moment["step"] == steps
                 and _shape_numbers(moment["exp_avg"])[0] == shape
                 and _shape_numbers(moment["exp_avg_sq"])[0] == shape
                 and all(x >= 0 for x in _shape_numbers(moment["exp_avg_sq"])[1]), "checkpoint Adam shape/step differs")
    _false_authority(checkpoint)


def _gru_precision(profile, forward, device):
    policy, receipt = profile["precision_policy"], forward["gru_precision"]
    _require(policy["persistent_flags_mutated"] is False, "head persistently changed precision flags")
    if device == "cpu":
        _require(receipt == {"profile_id": "native-768-source-span-device-float32/v1", "scoped_cudnn": False,
                 "persistent_flags_mutated": False, "device": "cpu"}, "CPU GRU precision receipt differs")
        return
    ambient = policy["ambient_at_admission"]
    _require(ambient["cuda_matmul_allow_tf32"] is False and ambient["float32_matmul_precision"] == "highest"
             and policy["cuda_gru_allow_tf32"] is False and policy["cuda_matmul_allow_tf32"] is False
             and policy["float32_matmul_precision"] == "highest"
             and policy["requires_owned_process_without_unrelated_concurrent_cudnn"] is True,
             "strict CUDA head precision policy differs")
    effective = {**ambient, "cudnn": {**ambient["cudnn"], "allow_tf32": False}}
    _require(receipt == {"profile_id": "native-768-source-span-device-strict-cuda-float32/v2", "device": device,
             "scoped_cudnn": True, "ambient_policy": ambient, "effective_policy": effective,
             "synchronized_before_restore": True, "ambient_flags_restored": True, "persistent_flags_mutated": False,
             "requires_owned_process_without_unrelated_concurrent_cudnn": True}, "CUDA GRU scoped precision/restoration differs")


def _audit(reader, report, check_current_sources):
    _require(report["schema"] == "native768-device-qualification/v1" and report["qualified"] is True
             and report["error"] is None, "native report is unavailable or unqualified")
    for key in ("production_model_quality_qualified", "codebase768_scan_qualified", "leanstral4096_qualified",
                "proof_authority", "source_semantics_verified", "execution_attestation", "kernel_resource_enforcement"):
        _require(report[key] is False, "native report widens qualification authority: " + key)
    _require(not any(key.endswith("_error") for key in report), "native cleanup contains an error")
    current_fits = _integer(report["setup_training_calls"], 0, 2)
    inherited_fits = _integer(report.get("inherited_setup_training_calls", 0), 0, 2)
    _require((current_fits, inherited_fits) in ((2, 0), (0, 2))
             and type(report["inference_training_calls"]) is int and report["inference_training_calls"] == 0,
             "current/inherited setup or inference fit accounting differs")
    _require(report["own_root_lease_released"] is True, "own root lease was not reported released")
    before_gpu = _integer(report["gpu_allocated_before_owned_sessions_bytes"])
    after_sessions = _integer(report["gpu_allocated_after_owned_sessions_closed_bytes"])
    after_workspace = _integer(report["gpu_allocated_after_framework_workspace_clear_bytes"])
    supported = report["framework_cuda_workspace_clear_supported"]
    _require(type(supported) is bool and after_sessions >= after_workspace == before_gpu
             and (supported or after_sessions == before_gpu), "post-workspace-close GPU allocation baseline differs")
    _integer(report["gpu_reserved_after_cache_release_bytes"])
    _require(report["hardware"]["actual_initial_cuda_kernel"] is True, "initial actual CUDA probe missing")
    device = "cuda:" + str(_integer(report["hardware"]["device_index"], 0, 255))
    _require(report["checkpoint_unchanged"] is True and report["adam_unchanged"] is True
             and report["head_canonical_decision_parity"] is True, "inference immutability/parity flags differ")
    pins = report["source_pins"]
    _require(type(pins) is list and len(pins) == len(SOURCE_FILES), "exact12 producer source pins required")
    repo = Path(__file__).absolute().parent.parent
    current_pins = []
    for pin, source, copy in zip(pins, SOURCE_FILES, PRODUCER_COPIES):
        _require(type(pin) is dict and set(pin) == {"path", "bytes", "sha256", "copy"}
                 and pin["copy"] == copy and pin["path"] == str(repo / source), "fixed producer source/copy path differs")
        _integer(pin["bytes"], 1, MAX_FILE_BYTES)
        _sha(pin["sha256"])
        raw = reader.read(copy)
        _require(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"], "retained source copy differs")
        if check_current_sources:
            parent = _open_directory((repo / source).parent)
            try:
                fd = os.open(Path(source).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == len(raw),
                             "current producer ordinary file identity differs")
                    current = bytearray()
                    while len(current) <= MAX_FILE_BYTES:
                        chunk = os.read(fd, min(65536, MAX_FILE_BYTES+1-len(current)))
                        if not chunk:
                            break
                        current.extend(chunk)
                    _require(_identity(before) == _identity(os.fstat(fd)) and bytes(current) == raw,
                             "current producer bytes differ from retained source")
                    current_pins.append({"path": str(repo / source), "bytes": len(current), "sha256": pin["sha256"]})
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
    rows = reader.json("source-rows.json")
    expected_texts = ["Lark must retain books.", "Wren may publish records.", "Finch must not destroy files.",
                      *[f"def compare_{i}(a: int, b: int) -> bool:\n    return a < b\n" for i in range(29)]]
    _require(rows == [{"id": f"native768-{i}", "source_text": text} for i, text in enumerate(expected_texts)],
             "fixed32 source rows differ")
    baseline = reader.json("encoder-reference.json", report["encoder_reference"]["result"])
    _require(baseline["schema"] == "gte-complete-native-embedding-production/v1" and baseline["status"] == "completed"
             and baseline["profile_id"] == REFERENCE_PROFILE and baseline["input_row_count"] == baseline["receipt_count"] == 32
             and len(baseline["receipts"]) == 32 and baseline["training_executed"] is False,
             "unchanged complete encoder reference differs")
    _require(baseline["execution_profile"]["device"] == "cpu" and baseline["execution_profile"]["dtype"] == "float32",
             "independent reference device/dtype differs")
    baseline_vectors = _vectors([row["embedding"] for row in baseline["receipts"]], 32)
    for receipt, row, vector in zip(baseline["receipts"], rows, baseline_vectors):
        _require(receipt["profile_id"] == REFERENCE_PROFILE, "reference receipt profile differs")
        _receipt(receipt, row, vector)
    _false_authority(baseline)
    _require(set(report["encoder"]) == {"cpu", "cuda"} and set(report["head"]) == {"cpu", "cuda", "cuda_batched"},
             "exact CPU/CUDA encoder and CPU/CUDA/batched head lanes required")
    numeric_errors, lane_vectors, lane_receipts = {}, {}, {}
    for lane in ("cpu", "cuda"):
        value = report["encoder"][lane]
        _require(set(value["batches"]) == {"1", "16", "32"}, "exact1/16/32 encoder batches required")
        expected_device = "cpu" if lane == "cpu" else device
        warmup = reader.json(f"encoder-{lane}-warmup.json", value["warmup"])
        _encoder(warmup, rows, baseline["receipts"], lane, expected_device, warmup=True)
        _require(value["profile"] == warmup["profile"], "encoder lane profile differs from retained result")
        for count in (1, 16, 32):
            batch = value["batches"][str(count)]
            _timing(batch)
            actual = reader.json(f"encoder-{lane}-batch{count}.json", batch["result"])
            error = _encoder(actual, rows[:count], baseline["receipts"][:count], lane, expected_device)
            _require(actual["profile"] == value["profile"] and _number(batch["reference_max_abs_error"]) == error,
                     "encoder reported numeric error/profile differs")
            numeric_errors[f"{lane}-{count}"] = error
        _require(value["token_parity_with_reference"] is True and value["reference_max_abs_error"] == error,
                 "encoder final parity summary differs")
        lane_vectors[lane], lane_receipts[lane] = actual["vectors"], actual["receipts"]
    training = reader.json("diagnostic-training-index.json")
    source_training = reader.json("diagnostic-source-training-index.json", report["head_setup"]["source_training_index"])
    _require(type(training) is list and len(training) == 3 and source_training == [
        {key: value for key, value in row.items() if key != "latent"} for row in training], "setup source-only training join differs")
    for index, row in enumerate(training):
        _require(set(row) == {"id", "source_text", "latent", "canonical_ir"}
                 and row["id"] == rows[index]["id"] and row["source_text"] == rows[index]["source_text"]
                 and row["latent"] == lane_vectors["cuda"][index], "setup actual CUDA vector/source join differs")
    setup = report["head_setup"]
    parent = reader.json("diagnostic-source-parent.json", setup["source_parent"])
    child = reader.json("diagnostic-native768-head.json", setup["child"])
    _checkpoint(parent, 3, 0)
    _checkpoint(child, 1, 768)
    parent_hash, child_hash, adam_hash = _digest(parent), _digest(child), _digest(child["optimizer_state"])
    if inherited_fits:
        inherited = reader.json("inherited-head-source-result.json", report["inherited_head_source_result"])
        _require(inherited["schema"] == "native768-device-qualification/v1"
                 and type(inherited["setup_training_calls"]) is int and inherited["setup_training_calls"] == 2
                 and type(inherited["inference_training_calls"]) is int and inherited["inference_training_calls"] == 0,
                 "retained inherited setup accounting differs")
        for key in ("source_parent", "child", "parent_fit_report", "child_fit_report"):
            old, current = inherited["head_setup"][key], setup[key]
            _require(old["sha256"] == current["sha256"] and old["bytes"] == current["bytes"],
                     "inherited setup retained bytes differ")
    else:
        _require("inherited_head_source_result" not in report, "fresh setup unexpectedly claims inherited bytes")
    _require(setup["parent_optimizer_steps"] == 3 and setup["child_optimizer_steps"] == 1
             and setup["production_selected"] is False and child["source_parent_checkpoint"] == parent
             and child["source_parent_checkpoint_sha256"] == parent_hash and child["source_parent_optimizer_steps"] == 3,
             "source parent/child setup linkage differs")
    context = child["context_contract"]
    _require(context == setup["context"] and context["dimension"] == DIMENSION
             and context["representation_id"] == report["encoder"]["cuda"]["profile"]["profile_id"]
             and context["producer_sha256"] == report["encoder"]["cuda"]["profile"]["profile_sha256"]
             and context["training_index_sha256"] == reader.pins["diagnostic-training-index.json"]["sha256"]
             and child["context_contract_sha256"] == _digest(context)
             and child["training_manifest_sha256"] == _digest(training)
             and parent["training_manifest_sha256"] == _digest(source_training), "setup context/training byte join differs")
    for label, steps, checkpoint_hash in (("parent", 3, parent_hash), ("child", 1, child_hash)):
        fit = reader.json(f"diagnostic-{label}-fit-report.json", setup[f"{label}_fit_report"])
        _require(type(fit["optimizer_steps"]) is int and fit["optimizer_steps"] == steps
                 and fit["training_executed"] is True and fit["checkpoint_sha256"] == checkpoint_hash
                 and len(fit["batch_losses"]) == steps and fit["stopped_reason"] == "step_limit",
                 "actual setup fit report/count differs")
        _require(fit["schema"] == ("span-legal-formula-training/v1" if label == "parent" else
                                   "native-dimensional-source-span-training/v1"), "setup fit report schema differs")
        if label == "child":
            _require(fit["source_parent_checkpoint_sha256"] == parent_hash and fit["source_parent_optimizer_steps"] == 3
                     and fit["new_optimizer_steps_total"] == 1, "child fit source-parent linkage differs")
        _require(all(_number(loss) >= 0 for loss in fit["batch_losses"]), "invalid setup loss")
        _false_authority(fit)
    native = reader.json("head-native-reference.json", report["head_native_reference"])
    vectors = lane_vectors["cuda"]
    _require(native["schema"] == "native-dimensional-source-span-inference/v1"
             and native["checkpoint_sha256"] == child_hash and native["input_dimension"] == DIMENSION
             and native["training_executed"] is False and native["model_state_unchanged"] is True,
             "unchanged native head reference differs")
    reference_decisions = _decisions(native, rows, vectors)
    native_logits = reader.json("head-native-reference-logits.json", report["head_native_reference_logits"])
    logit_errors = {}
    for lane in ("cpu", "cuda", "cuda_batched"):
        value, expected_device = report["head"][lane], "cpu" if lane == "cpu" else device
        _require(set(value["batches"]) == {"1", "16", "32"} and value["checkpoint_unchanged"] is True,
                 "head batch/checkpoint summary differs")
        private_logits = reader.json(f"head-{lane}-logits.json", value["native_logits"])
        errors = _logits(native_logits, private_logits)
        _require(value["native_logit_max_abs_errors"] == errors, "reported logit parity errors differ")
        logit_errors[lane] = errors
        for count in (1, 16, 32):
            batch = value["batches"][str(count)]
            _timing(batch)
            actual = reader.json(f"head-{lane}-batch{count}.json", batch["result"])
            _require(actual["schema"] == ("native-768-source-span-batched-device-inference/v1" if lane == "cuda_batched"
                                          else "native-768-source-span-device-inference/v1")
                     and actual["checkpoint_sha256"] == child_hash and actual["input_dimension"] == DIMENSION
                     and actual["source_parent_checkpoint_sha256"] == parent_hash
                     and actual["context_contract_sha256"] == _digest(context)
                     and actual["cuda_executed"] is (lane != "cpu")
                     and actual["training_executed"] is False and actual["model_state_unchanged"] is True
                     and actual["target_access"] is False and actual["teacher_forcing"] is False
                     and actual["latent_ablation"] == "none", "head execution/checkpoint flags differ")
            decisions = _decisions(actual, rows[:count], vectors[:count])
            _require(decisions == reference_decisions[:count], "unchanged native head canonical decision parity differs")
            profile = actual["execution_profile"]
            expected_profile = ("native-768-source-span-device-float32/v1" if lane == "cpu" else
                                "native-768-source-span-device-strict-cuda-float32/v2" if lane == "cuda" else
                                "native-768-source-span-batched-device-float32-cpu-decisions/v1")
            _require(profile == value["profile"] and profile["profile_id"] == expected_profile
                     and profile["dimension"] == DIMENSION and profile["device"] == expected_device
                     and profile["optimized"] is (lane != "cpu") and profile["dtype"] == "float32"
                     and profile["checkpoint_sha256"] == child_hash and profile["optimizer_state_sha256"] == adam_hash
                     and profile["stored_checkpoint_device"] == "cpu" and profile["checkpoint_conversion_performed"] is False
                     and profile["inference_only"] is True, "actual head profile/device differs")
            receipts = actual["input_receipts"]
            _require(receipts == {"status": "externally_content_pinned", "native_encoder_inputs_authenticated": True,
                     "receipt_sha256s": [_digest(row) for row in lane_receipts["cuda"][:count]],
                     "context_producer_sha256": context["producer_sha256"],
                     "profile_sha256s": [row["profile_sha256"] for row in lane_receipts["cuda"][:count]],
                     "signature_verified": False, "semantic_qualification": False}, "head encoder receipt content pins differ")
            forwards = actual["actual_forward_batches"]
            batched = lane == "cuda_batched"
            _require(type(forwards) is list and len(forwards) == (1 if batched else count), "head forward coverage differs")
            if batched:
                _require(actual["numerical_batching"] is True and actual["valid_source_count"] == count
                         and type(actual["cpu_head_output_materializations"]) is int and actual["cpu_head_output_materializations"] == 4
                         and type(actual["device_to_cpu_head_transfers"]) is int and actual["device_to_cpu_head_transfers"] == 4
                         and actual["canonical_decision_device"] == "cpu" and profile["canonical_decision_device"] == "cpu"
                         and profile["output_transfer_policy"] == "four_complete_head_tensors_once_per_request"
                         and profile["request_local_numerical_cache"] is True and profile["kernel_resource_enforcement"] is False,
                         "batched output transfer/CPU decision profile differs")
            for index, forward in enumerate(forwards):
                sources = rows[:count] if batched else [rows[index]]
                token_counts = [len(re.findall(r"\w+|[^\w\s]", source["source_text"], re.UNICODE)) for source in sources]
                _require(type(forward["rows"]) is int and forward["rows"] == len(sources)
                         and forward["source_tokens"] == token_counts and forward["input_device"] == expected_device
                         and forward["native_input_dimension"] == DIMENSION and forward["output_dtype"] == "float32"
                         and forward["gru_executed"] is True and set(forward["output_devices"]) == {"modality", "presence", "start", "end"}
                         and all(output == expected_device for output in forward["output_devices"].values()),
                         "actual head forward device/dtype/source coverage differs")
                _gru_precision(profile, forward, expected_device)
        _require(value["decisions"] == decisions, "head decision summary differs")
    reader.final_check()
    return {"source_rows": 32, "encoder_batches": [1, 16, 32], "head_batches": [1, 16, 32],
            "encoder_max_abs_errors": numeric_errors, "head_logit_max_abs_errors": logit_errors,
            "setup_fit_reports_joined": 2, "reported_current_setup_fits": current_fits,
            "reported_inherited_setup_fits": inherited_fits, "reported_parent_steps": 3, "reported_child_steps": 1,
            "reported_inference_fits": 0, "reported_own_root_lease_released": True,
            "reported_postclose_gpu_allocated_bytes": after_sessions,
            "reported_post_framework_workspace_clear_bytes": after_workspace, "current_source_pins": current_pins}


def audit(root, *, expected_result_sha256, check_current_sources=False):
    """Read only fixed archive files; an external result SHA is mandatory.

    Positive output means the retained evidence is internally consistent with
    that supplied SHA. Reported devices, fit/resource counters, and execution
    remain reports; this reader provides no native or proof authority.
    """
    result = {"schema": "native768-device-closed-audit/v1", "qualified": False,
              "closed_artifacts_consistent": False, "native_execution_attested": False,
              "resource_enforcement_attested": False, "model_quality_qualified": False,
              "proof_authority": False, "source_semantics_verified": False,
              "leanstral4096_qualified": False, "scope": "ordinary_retained_bytes_and_report_consistency",
              "error": None, "retained_pins": []}
    reader = None
    try:
        _sha(expected_result_sha256)
        _require(type(check_current_sources) is bool, "current-source option must be boolean")
        reader = _Reader(root)
        report = reader.json("result.json")
        _require(reader.pins["result.json"]["sha256"] == expected_result_sha256, "external result SHA256 differs")
        if type(report) is dict:
            result["native_report_qualified"] = report.get("qualified")
            result["native_report_error"] = report.get("error")
            result["native_cleanup_errors"] = {key: value for key, value in report.items() if key.endswith("_error")}
        result["checks"] = _audit(reader, report, check_current_sources)
        result["qualified"] = result["closed_artifacts_consistent"] = True
    except (AuditError, OSError, ValueError, KeyError, TypeError, RecursionError, OverflowError) as error:
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
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
