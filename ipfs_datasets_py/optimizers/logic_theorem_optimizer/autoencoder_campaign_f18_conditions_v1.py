"""Fixed F18 four-tensor campaign adapter, after original owner admission.

The job spec is data only. Its hashes establish continuity, never issuer, legal,
native-resource or task authority. Only the original campaign process owner
supplies the real resource/offline/RUN boundary; this module creates no grant.
The numerical implementation remains the unchanged versioned F18 profile.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat

SCHEMA_VERSION = "legal-ir-f18-conditions-training-job/v1"
PREPARED_INPUTS_SCHEMA = "legal-ir-f18-conditions-prepared-inputs/v1"
RECEIPT_SCHEMA = "legal-ir-f18-conditions-training-receipt/v1"
BINDINGS_SCHEMA = "conditions-fullspan-f18-four-tensor-input-bindings/v1"
BINDING_FIELDS = frozenset({"schema", "donor_checkpoint_sha256", "donor_model_state_sha256",
    "donor_provenance_sha256", "source_parent_checkpoint_sha256", "source_parent_model_state_sha256",
    "context_contract_sha256", "training_manifest_sha256", "prepared_training_records_sha256",
    "teacher_checkpoint_sha256", "teacher_model_state_sha256", "teacher_capture_sha256",
    "teacher_training_sha256", "row_weight_training_sha256", "training_mask_certificate_sha256"})
PROFILE_RELATIVE_PATH = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_training_v1.py"
PROFILE_SHA256 = "56bd0a248a07de09519f95e5c4bae02ab9d8eb1134b483c257c1f7e7bcb07147"
ADAPTER_RELATIVE_PATH = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_campaign_f18_conditions_v1.py"
REQUIRED_SOURCE_SHA256 = {
    ADAPTER_RELATIVE_PATH: None,
    PROFILE_RELATIVE_PATH: PROFILE_SHA256,
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_modality_conditions_retention.py": "fb7449d4794ca9a279b2df2ea533b89d360344ff786edc0798395ab799db1823",
    "ipfs_datasets_py/logic/legal_ir/conditions_fullspan_margin_v1.py": "e4f16146cf6f64b16e979e5ee0803a41ee41a8377bfa7833918b0a25dd7d1160",
    "ipfs_datasets_py/logic/legal_ir/structured_span_objective.py": "68a459fe5271248ee478ae05767396842c1e1b83e33971b980c77b1afd3f8c84",
    "tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_modality_conditions_retention_contracts.py": "3094d9fd2bd7f409a913d4096557e9a342c8c79214c5810f7a6980b33f204c58",
    "tests/unit/logic/legal_ir/test_conditions_fullspan_margin_v1.py": "461877c74b2b5661778fc853352db4e90c10f5b8127f9adb457cbf760b70bb27",
}
ASSET_ROLES = (
    "retained_final_F18_donor_checkpoint", "trained_F15_teacher_checkpoint",
    "original_TRAIN_source_export", "fresh_source_export",
    "trained_F15_TRAIN168_teacher_capture", "qualified_F18_training_mask_certificate_v02",
)
# Fixed matched-experiment protocol selected by the original closed632 receipt.
# Paths may relocate; these bytes/roots may not. Another donor needs a new version.
SELECTED_PHYSICAL_INPUTS = {'fresh_source_export': {'bytes': 434236,
                         'sha256': '83078f6028dd63b47661c4e3bb5c9cb27546f926c306d074f13d509d2aeec846'},
 'original_TRAIN_source_export': {'bytes': 4675279,
                                  'sha256': 'ea377724beeffcfc7e8565b03ed207a90cdf3a1955f4ba7d0bfea460ba94c3a9'},
 'qualified_F18_training_mask_certificate_v02': {'bytes': 879934,
                                                 'sha256': '1aef873043042b6aa155a529c70577e583e36084c44c248c9127384642ca4593'},
 'retained_final_F18_donor_checkpoint': {'bytes': 21058430,
                                         'sha256': '90031d084f2d86cf860c5fc95d2dae374dc254adec70bd85a90893f98c5a1555'},
 'trained_F15_TRAIN168_teacher_capture': {'bytes': 3594328,
                                          'sha256': '221fa2ec37fc41298f787d4dfef1d4daf60b07c4c565a1194d2097e7c538fff1'},
 'trained_F15_teacher_checkpoint': {'bytes': 12230969,
                                    'sha256': 'f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4'}}
SELECTED_INPUT_BINDINGS = {'context_contract_sha256': '3340be29cffa3dd9c960c98374a9ccb7f421f24e575f7f037a7c12589843f173',
 'donor_checkpoint_sha256': '90031d084f2d86cf860c5fc95d2dae374dc254adec70bd85a90893f98c5a1555',
 'donor_model_state_sha256': '2ed0ccf633f55fac202e2edb95ea9fa6e390b8d99381a05925f4dd5221925883',
 'donor_provenance_sha256': '92604940383a955e64b062dc95305ce5d586f0e0734a349f840acd8474a21ee5',
 'prepared_training_records_sha256': '3e36dc7fa32d3aaec0bb6039107177a30e10decd25d7bbc8bdc66ed22c243dfa',
 'row_weight_training_sha256': '33bfc4a3e08d4958b78a99b62c25238253f941fb7ff6c704a9568ff6c36dded5',
 'schema': 'conditions-fullspan-f18-four-tensor-input-bindings/v1',
 'source_parent_checkpoint_sha256': 'fd7eb4bd7c8c5d5abb23d168e6b67300497eea6243b5c8cd5779cfbc566d5279',
 'source_parent_model_state_sha256': '54e745f0dc75a79c11828048ad5deb44b0f07dcac5b9083bde17948b5206bfcb',
 'teacher_capture_sha256': '221fa2ec37fc41298f787d4dfef1d4daf60b07c4c565a1194d2097e7c538fff1',
 'teacher_checkpoint_sha256': 'f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4',
 'teacher_model_state_sha256': 'a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42',
 'teacher_training_sha256': 'a37a79041b7304e692363a9757ec3dd59761c0fd37360e0ebd8c57b92eda864d',
 'training_manifest_sha256': 'afa0deeebf4052831883c046104a8808342b67a7c8dc2e58de2f9208a9287c34',
 'training_mask_certificate_sha256': 'f70ddf0a13f57c88386998df412a4e44aeafd508d3a23b3f8509fec6a04f55c7'}
SELECTED_INPUT_MAP_PROVENANCE = {
    "asset_manifest_sha256": "602eb270ce25da70f39ef0c8179de12fae16bbaf450193a56aa29caf0c96a044",
    "initial632_result_metadata_sha256": "de6c6f821bffabdd6015db0ff392d9dc961f9c412edd21e08104bc9649399843",
}
FALSE_FIELDS = (
    "admitted", "formalized", "promoted", "qualified", "semantic_reviewed",
    "training_gold_admitted", "statutory_accuracy_qualified",
    "native_task_completed", "native_goal_completed",
)
SPEC_FIELDS = frozenset({"schema_version", "run_id", "output_directory", "prepared_inputs",
    "initial_checkpoint", "physical_assets", "source_pins", "margin_weight", "max_steps",
    "max_seconds", "runtime_contract"})
PREPARED_FIELDS = frozenset({"schema", "state", "provenance", "records", "teacher", "weights", "expected_bindings"})
RECEIPT_FIELDS = frozenset({"schema_version", "run_id", "job_spec_sha256", "job_file_sha256",
    "prepared_inputs_sha256", "initial_checkpoint_file_sha256", "profile_source_sha256",
    "margin_weight", "requested_steps", "completed_steps", "initial_progress", "final_progress",
    "reason", "status", "checkpoint", "report", "checkpoint_sha256", "elapsed_seconds",
    "training_executed", "all_requested_steps_completed", "prepared_inputs_integrity_only",
    "runtime_contract_sha256", *FALSE_FIELDS})
MAX_PREPARED_BYTES = 32 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
RUNTIME_CONTRACT_BYTES = 758
RUNTIME_CONTRACT_SHA256 = "1caaf4a3d9e779bc569ad92fa7fb953ae42a004db5049766272879ab8a3d5eab"
MAX_RUNTIME_BYTES = 64 * 1024
_ROOT = Path(__file__).resolve().parents[3]
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}\Z")


class F18CampaignError(ValueError):
    """The fixed data/process binding is invalid; no fallback is attempted."""


def _require(condition, message):
    if not condition:
        raise F18CampaignError(message)


def _canonical(value, *, maximum=MAX_REPORT_BYTES):
    # Count the complete escaped UTF8 representation before any encoder can
    # allocate a whole quoted string. Only exact builtin JSON types are read.
    _require(type(maximum) is int and maximum > 0, "positive JSON byte bound required")
    budget, nodes, seen = 0, 0, set()
    def consume(count):
        nonlocal budget
        budget += count
        _require(budget <= maximum, "JSON byte bound exceeded")
    def string(text):
        consume(2)
        for character in text:
            code = ord(character)
            _require(not 0xD800 <= code <= 0xDFFF, "valid UTF8 JSON string required")
            if character in ('"', "\\") or character in "\b\f\n\r\t":
                consume(2)
            elif code < 32:
                consume(6)
            else:
                consume(1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
    def walk(item, depth):
        nonlocal nodes
        nodes += 1
        _require(nodes <= 2_000_000 and depth <= 64, "JSON node/depth bound exceeded")
        kind = type(item)
        if item is None or kind is bool:
            consume(4 if item is None or item is True else 5)
        elif kind is str:
            string(item)
        elif kind is int:
            _require(item.bit_length() <= 256, "bounded JSON integer required")
            consume(len(str(item)))
        elif kind is float:
            _require(math.isfinite(item), "finite JSON required")
            consume(len(repr(item)))
        elif kind in (dict, list):
            _require(id(item) not in seen, "aliased or cyclic JSON container")
            seen.add(id(item))
            consume(2 + max(0, len(item) - 1))
            if kind is dict:
                for key, child in item.items():
                    _require(type(key) is str, "plain JSON string keys required")
                    string(key)
                    consume(1)
                    walk(child, depth + 1)
            else:
                for child in item:
                    walk(child, depth + 1)
        else:
            raise F18CampaignError("exact plain JSON types required")
    walk(value, 0)
    output = bytearray()
    try:
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False)
        for part in encoder.iterencode(value):
            chunk = part.encode("utf-8")
            _require(len(output) + len(chunk) <= maximum, "JSON byte bound exceeded")
            output.extend(chunk)
    except (ValueError, TypeError, RecursionError, UnicodeError, OverflowError) as error:
        if isinstance(error, F18CampaignError):
            raise
        raise F18CampaignError("finite plain JSON required") from error
    _require(len(output) == budget, "canonical JSON byte accounting differs")
    return bytes(output)


def _parse(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, "duplicate JSON key")
            value[key] = item
        return value
    def constant(_):
        raise F18CampaignError("finite JSON required")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError, RecursionError) as error:
        if isinstance(error, F18CampaignError):
            raise
        raise F18CampaignError("plain JSON required") from error


def _sha(value):
    _require(type(value) is str and _SHA.fullmatch(value), "SHA256 required")
    return value


def _path(value):
    _require(type(value) is str and 1 <= len(value) <= 4096
             and all(ord(character) >= 32 and ord(character) != 127 for character in value),
             "literal absolute path required")
    path = Path(value)
    _require(path.is_absolute() and ".." not in path.parts and path != Path("/"),
             "literal absolute path required")
    return path


def _descriptor(value, maximum):
    _require(type(value) is dict and set(value) == {"path", "bytes", "sha256"}, "closed descriptor required")
    _path(value["path"])
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= maximum, "descriptor byte bound")
    _sha(value["sha256"])
    return copy.deepcopy(value)


def _validate_document(value):
    _require(type(value) is dict and set(value) == SPEC_FIELDS, "closed F18 job fields required")
    _require(value["schema_version"] == SCHEMA_VERSION, "fixed F18 job schema required")
    _require(type(value["run_id"]) is str and _ID.fullmatch(value["run_id"]), "bounded run identity required")
    output = _path(value["output_directory"])
    _descriptor(value["prepared_inputs"], MAX_PREPARED_BYTES)
    _descriptor(value["initial_checkpoint"], MAX_CHECKPOINT_BYTES)
    _require(type(value["margin_weight"]) in (int, float) and value["margin_weight"] in (0.0, 0.25), "fixed margin arm required")
    _require(type(value["max_steps"]) is int and 0 <= value["max_steps"] <= 32, "finite32 update bound required")
    _require(type(value["max_seconds"]) in (int, float) and math.isfinite(value["max_seconds"])
             and 0 <= value["max_seconds"] <= 32, "finite32 second bound required")
    assets = value["physical_assets"]
    _require(type(assets) is list and len(assets) == len(ASSET_ROLES), "six physical roles required")
    roles, paths = set(), [value["prepared_inputs"]["path"], value["initial_checkpoint"]["path"]]
    for asset in assets:
        _require(type(asset) is dict and set(asset) == {"role", "path", "bytes", "sha256"}, "closed physical role required")
        _require(type(asset["role"]) is str and asset["role"] in ASSET_ROLES and asset["role"] not in roles,
                 "six distinct physical roles required")
        roles.add(asset["role"])
        _descriptor({key: asset[key] for key in ("path", "bytes", "sha256")}, MAX_ASSET_BYTES)
        paths.append(asset["path"])
    _require(sum(asset["bytes"] for asset in assets) <= 512 * 1024 * 1024, "physical input byte bound")
    _require(len(paths) == len(set(paths)), "distinct input paths required")
    for path in paths:
        source = _path(path)
        _require(source != output and output not in source.parents and source not in output.parents,
                 "input and output storage overlap")
    pins = value["source_pins"]
    _require(type(pins) is dict and set(REQUIRED_SOURCE_SHA256) <= set(pins) and len(pins) <= 128,
             "fixed owner source pins required")
    for name, pin in pins.items():
        _require(type(name) is str and name and not PurePosixPath(name).is_absolute()
                 and ".." not in PurePosixPath(name).parts and "\\" not in name
                 and name.endswith(".py") and PurePosixPath(name).parts[0] in {"ipfs_datasets_py", "scripts", "tests"},
                 "repository-relative source path required")
        _require(type(pin) is dict and set(pin) == {"bytes", "sha256"}
                 and type(pin["bytes"]) is int and 0 < pin["bytes"] <= MAX_SOURCE_BYTES,
                 "bounded source pin required")
        _sha(pin["sha256"])
        expected = REQUIRED_SOURCE_SHA256.get(name)
        _require(expected is None or pin["sha256"] == expected, "immutable numerical owner source differs")
    if value["runtime_contract"] is not None:
        _descriptor(value["runtime_contract"], MAX_RUNTIME_BYTES)
        _require(value["runtime_contract"]["bytes"] == RUNTIME_CONTRACT_BYTES
                 and value["runtime_contract"]["sha256"] == RUNTIME_CONTRACT_SHA256,
                 "original fixed libdl runtime descriptor required")
    _require(len(_canonical(value, maximum=MAX_RECEIPT_BYTES)) <= MAX_RECEIPT_BYTES, "bounded job metadata required")


@dataclass(frozen=True)
class F18JobSpec:
    """Closed metadata identity; construction performs no filesystem/model action."""
    _document: bytes

    def __post_init__(self):
        _require(type(self._document) is bytes and 0 < len(self._document) <= MAX_RECEIPT_BYTES,
                 "bounded canonical job bytes required")
        value = _parse(self._document)
        _validate_document(value)
        _require(_canonical(value) == self._document, "canonical job bytes required")

    @classmethod
    def from_dict(cls, value):
        # Reject custom nested objects and oversized authoring before field/set work.
        raw = _canonical(value, maximum=MAX_RECEIPT_BYTES)
        _validate_document(_parse(raw))
        return cls(raw)

    def to_dict(self):
        return _parse(self._document)

    @property
    def canonical_sha256(self):
        return hashlib.sha256(self._document).hexdigest()

    @property
    def run_id(self):
        return self.to_dict()["run_id"]

    @property
    def output_directory(self):
        return self.to_dict()["output_directory"]

    @property
    def legal_ir_parallel_workers(self):
        return 1

    @property
    def max_steps(self):
        return self.to_dict()["max_steps"]

    @property
    def margin_weight(self):
        return self.to_dict()["margin_weight"]


def _spec(value):
    _require(type(value) is F18JobSpec, "concrete F18JobSpec required")
    return F18JobSpec.from_dict(value.to_dict()).to_dict()


def _directory_identity(path):
    first = None
    for part in (path, *path.parents):
        info = part.lstat()
        _require(stat.S_ISDIR(info.st_mode), "literal directory ancestry required")
        if first is None:
            first = (info.st_dev, info.st_ino)
    return first


def _identity(path):
    _directory_identity(path.parent)
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unaliased regular input required")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_descriptor(descriptor, maximum, *, retain=True):
    _descriptor(descriptor, maximum)
    path = _path(descriptor["path"])
    before = _identity(path)
    _require(before[2] == descriptor["bytes"], "input bytes differ")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest, chunks, count = hashlib.sha256(), [], 0
    try:
        info = os.fstat(fd)
        _require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) == before
                 and stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "input pathname changed")
        while True:
            chunk = os.read(fd, min(65_536, maximum + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            _require(count <= descriptor["bytes"], "input grew beyond bound")
            digest.update(chunk)
            if retain:
                chunks.append(chunk)
        info = os.fstat(fd)
        _require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) == before
                 and info.st_nlink == 1, "input descriptor changed")
    finally:
        os.close(fd)
    _require(count == descriptor["bytes"] and digest.hexdigest() == descriptor["sha256"], "input digest differs")
    _require(_identity(path) == before, "input pathname changed")
    return b"".join(chunks) if retain else None


def _verify_sources(document):
    for relative, pin in document["source_pins"].items():
        _read_descriptor({"path": str(_ROOT / relative), **pin}, MAX_SOURCE_BYTES, retain=False)


def validate_job_inputs(spec):
    """Stream-hash commitments only, inside original admitted execution scope.

    Preparation must not call this reader. No input JSON is parsed and no model,
    profile, native owner or issuer is authenticated by the returned metadata.
    """
    document = _spec(spec)
    _verify_sources(document)
    _read_descriptor(document["prepared_inputs"], MAX_PREPARED_BYTES, retain=False)
    _read_descriptor(document["initial_checkpoint"], MAX_CHECKPOINT_BYTES, retain=False)
    for asset in document["physical_assets"]:
        _read_descriptor({key: asset[key] for key in ("path", "bytes", "sha256")}, MAX_ASSET_BYTES, retain=False)
    if document["runtime_contract"] is not None:
        _read_descriptor(document["runtime_contract"], MAX_RUNTIME_BYTES, retain=False)
    _verify_sources(document)
    return {"schema": "legal-ir-f18-conditions-input-integrity/v1",
            "job_spec_sha256": spec.canonical_sha256, "input_bytes_verified": True,
            "issuer_authenticated": False, "runtime_grant": False,
            "prepared_inputs_integrity_only": True,
            **{key: False for key in FALSE_FIELDS}}


def encode_prepared_inputs(value):
    """Serialize caller-prepared data only; this does not authenticate its author."""
    raw = _canonical(value, maximum=MAX_PREPARED_BYTES)
    _require(type(value) is dict and set(value) == PREPARED_FIELDS
             and value["schema"] == PREPARED_INPUTS_SCHEMA, "closed prepared F18 inputs required")
    _require(all(type(value[key]) is dict for key in ("state", "provenance", "teacher", "weights", "expected_bindings"))
             and type(value["records"]) is list and len(value["records"]) == 168, "prepared168 input objects required")
    bindings = value["expected_bindings"]
    _require(set(bindings) == BINDING_FIELDS and bindings["schema"] == BINDINGS_SCHEMA,
             "closed15 input bindings required")
    for key in BINDING_FIELDS - {"schema"}:
        _sha(bindings[key])
    _require(0 < len(raw) <= MAX_PREPARED_BYTES, "prepared input byte bound")
    return raw


def validate_selected_input_bindings(expected_bindings, physical_assets):
    """Check the fixed selected protocol, never issuer or runtime admission."""
    bindings = _parse(_canonical(expected_bindings, maximum=MAX_RECEIPT_BYTES))
    assets = _parse(_canonical(physical_assets, maximum=MAX_RECEIPT_BYTES))
    _require(bindings == SELECTED_INPUT_BINDINGS, "selected15 input roots differ")
    _require(type(assets) is list and len(assets) == len(ASSET_ROLES), "selected six roles required")
    actual = {}
    for asset in assets:
        _require(type(asset) is dict and set(asset) == {"role", "path", "bytes", "sha256"}
                 and type(asset["role"]) is str and asset["role"] in ASSET_ROLES
                 and asset["role"] not in actual, "selected role identity differs")
        _descriptor({key: asset[key] for key in ("path", "bytes", "sha256")}, MAX_ASSET_BYTES)
        actual[asset["role"]] = {key: asset[key] for key in ("bytes", "sha256")}
    _require(actual == SELECTED_PHYSICAL_INPUTS, "selected physical role commitment differs")
    for field, role in (("donor_checkpoint_sha256", ASSET_ROLES[0]),
                        ("teacher_checkpoint_sha256", ASSET_ROLES[1]),
                        ("teacher_capture_sha256", ASSET_ROLES[4])):
        _require(bindings[field] == actual[role]["sha256"], "physical/canonical role link differs")
    # Raw TRAIN/fresh file roots are fixed above; canonical TRAIN/prepared roots
    # retain distinct fields. The mask raw SHA is not its canonical JSON root.
    _require(bindings["training_mask_certificate_sha256"] != actual[ASSET_ROLES[5]]["sha256"],
             "raw/canonical mask roots conflated")
    return {"schema": "legal-ir-f18-selected-input-continuity/v1",
            "selected_protocol_matches": True, "issuer_authenticated": False,
            "runtime_grant": False, **{key: False for key in FALSE_FIELDS}}


def _load_inputs(document):
    # Called by the fixed execution adapter, after the real original RUN barrier.
    _verify_sources(document)
    raw = _read_descriptor(document["prepared_inputs"], MAX_PREPARED_BYTES)
    prepared = _parse(raw)
    _require(encode_prepared_inputs(prepared) == raw, "canonical prepared JSON required")
    validate_selected_input_bindings(prepared["expected_bindings"], document["physical_assets"])
    for asset in document["physical_assets"]:
        _read_descriptor({key: asset[key] for key in ("path", "bytes", "sha256")}, MAX_ASSET_BYTES, retain=False)
    donor = next(asset for asset in document["physical_assets"] if asset["role"] == ASSET_ROLES[0])
    _require(prepared["expected_bindings"].get("donor_checkpoint_sha256") == donor["sha256"],
             "prepared donor physical commitment differs")
    profile = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_conditions_fullspan_training_v1")
    _require(Path(profile.__file__).resolve() == (_ROOT / PROFILE_RELATIVE_PATH).resolve(), "different profile owner imported")
    _verify_sources(document)
    by_role = {asset["role"]: asset for asset in document["physical_assets"]}
    certificate = _parse(_read_descriptor({key: by_role[ASSET_ROLES[5]][key]
        for key in ("path", "bytes", "sha256")}, MAX_ASSET_BYTES))
    _require(profile.checkpoint_digest(certificate) == prepared["expected_bindings"]["training_mask_certificate_sha256"],
             "canonical physical mask certificate differs")
    original = _parse(_read_descriptor({key: by_role[ASSET_ROLES[2]][key]
        for key in ("path", "bytes", "sha256")}, MAX_ASSET_BYTES))
    _require(type(original) is dict and type(original.get("training_rows")) is list
             and profile.checkpoint_digest(original["training_rows"]) == prepared["expected_bindings"]["training_manifest_sha256"],
             "canonical original TRAIN manifest differs")
    original_records = profile.f18._training_records(original["training_rows"])
    _require(profile.checkpoint_digest(original_records) == prepared["expected_bindings"]["prepared_training_records_sha256"]
             == profile.checkpoint_digest(prepared["records"]), "original/prepared TRAIN168 join differs")
    kwargs = {key: prepared[key] for key in ("state", "provenance", "records", "teacher", "weights", "expected_bindings")}
    kwargs["margin_weight"] = document["margin_weight"]
    checkpoint = profile.load_checkpoint(document["initial_checkpoint"]["path"],
        expected_sha256=document["initial_checkpoint"]["sha256"], **kwargs)
    _require(checkpoint["progress"]["optimizer_steps"] + document["max_steps"] <= 32,
             "cumulative32 update budget exceeded")
    return profile, checkpoint, kwargs


def _torch(document):
    descriptor = document["runtime_contract"]
    if descriptor is None:
        return importlib.import_module("torch")
    runtime = _parse(_read_descriptor(descriptor, MAX_RUNTIME_BYTES))
    _require(type(runtime) is dict and set(runtime) == {"schema", "requested_library", "ctypes_util_pin",
        "cuda_pathfinder_pin", "library_pin", "subprocess_fallback_allowed", "unlisted_library_names_allowed"}
        and runtime["schema"] == "pinned-libdl-resolution/v1" and runtime["requested_library"] == "dl"
        and runtime["subprocess_fallback_allowed"] is False and runtime["unlisted_library_names_allowed"] is False,
        "fixed libdl runtime contract required")
    for key in ("ctypes_util_pin", "cuda_pathfinder_pin", "library_pin"):
        _read_descriptor(runtime[key], MAX_SOURCE_BYTES, retain=False)
    import ctypes.util
    _require(Path(ctypes.util.__file__).resolve() == Path(runtime["ctypes_util_pin"]["path"]).resolve(),
             "different ctypes resolver imported")
    original = ctypes.util.find_library
    def resolve(name):
        _require(name == "dl", "unlisted runtime library requested")
        return runtime["library_pin"]["path"]
    try:
        ctypes.util.find_library = resolve
        torch = importlib.import_module("torch")
    finally:
        ctypes.util.find_library = original
    _require(ctypes.util.find_library is original, "runtime resolver not restored")
    for key in ("ctypes_util_pin", "cuda_pathfinder_pin", "library_pin"):
        _read_descriptor(runtime[key], MAX_SOURCE_BYTES, retain=False)
    return torch


def _write_new(path, value, maximum):
    raw = _canonical(value, maximum=maximum)
    _require(0 < len(raw) <= maximum, "output byte bound")
    parent_identity = _directory_identity(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # Partial artifacts remain owned evidence; never unlink or retry here.
        raise
    _require(_directory_identity(path.parent) == parent_identity, "output directory changed")
    descriptor = {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    _read_descriptor(descriptor, maximum, retain=False)
    return descriptor


def _progress(value):
    _require(type(value) is dict and set(value) == {"epochs_completed", "row_cursor", "optimizer_steps"},
             "closed progress required")
    _require(all(type(item) is int and item >= 0 for item in value.values()), "integer progress required")
    steps = value["optimizer_steps"]
    _require(steps <= 32 and value["epochs_completed"] == steps // 14
             and value["row_cursor"] == (steps % 14) * 12, "fixed168 progress differs")
    return steps


def validate_receipt(spec, receipt, *, job_file_sha256):
    """Validate detached receipt metadata, not artifact bytes or native authority."""
    document = _spec(spec)
    _sha(job_file_sha256)
    _require(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS, "closed F18 receipt required")
    _require(receipt["schema_version"] == RECEIPT_SCHEMA and receipt["run_id"] == spec.run_id
             and receipt["job_spec_sha256"] == spec.canonical_sha256
             and receipt["job_file_sha256"] == job_file_sha256, "F18 receipt job identity differs")
    _require(all(receipt[key] is False for key in FALSE_FIELDS)
             and receipt["prepared_inputs_integrity_only"] is True, "receipt cannot grant authority")
    _require(receipt["prepared_inputs_sha256"] == document["prepared_inputs"]["sha256"]
             and receipt["initial_checkpoint_file_sha256"] == document["initial_checkpoint"]["sha256"]
             and receipt["profile_source_sha256"] == PROFILE_SHA256
             and type(receipt["margin_weight"]) in (int, float)
             and receipt["margin_weight"] == document["margin_weight"], "F18 receipt input identity differs")
    runtime_sha = None if document["runtime_contract"] is None else document["runtime_contract"]["sha256"]
    _require(receipt["runtime_contract_sha256"] == runtime_sha, "runtime commitment differs")
    before, after = _progress(receipt["initial_progress"]), _progress(receipt["final_progress"])
    count = receipt["completed_steps"]
    _require(type(count) is int and type(receipt["requested_steps"]) is int
             and receipt["requested_steps"] == document["max_steps"]
             and 0 <= count == after - before <= document["max_steps"], "actual step accounting differs")
    complete = count == document["max_steps"]
    _require(receipt["status"] == ("completed" if complete else "partial")
             and receipt["all_requested_steps_completed"] is complete
             and receipt["training_executed"] is bool(count)
             and receipt["reason"] == ("step_limit" if complete else "deadline_before_batch"),
             "incomplete training cannot claim requested completion")
    _require(type(receipt["elapsed_seconds"]) in (int, float)
             and math.isfinite(receipt["elapsed_seconds"]) and receipt["elapsed_seconds"] >= 0,
             "finite elapsed time required")
    _sha(receipt["checkpoint_sha256"])
    output = _path(document["output_directory"])
    for key, maximum in (("checkpoint", MAX_CHECKPOINT_BYTES), ("report", MAX_REPORT_BYTES)):
        _descriptor(receipt[key], maximum)
        _require(Path(receipt[key]["path"]) == output / (key + ".json"), "fixed output artifact path required")
    _require(len(_canonical(receipt, maximum=MAX_RECEIPT_BYTES)) <= MAX_RECEIPT_BYTES, "receipt byte bound")
    return _parse(_canonical(receipt, maximum=MAX_RECEIPT_BYTES))


def execute_job(spec, *, job_file_sha256):
    """Fixed worker operation, callable only under original caller-owned admission.

    Preparation/hashes are not grants. No legacy loader, pre-restore, scoring,
    checkpoint selector, generic callback or provider is introduced here.
    """
    document = _spec(spec)
    _sha(job_file_sha256)
    output = _path(document["output_directory"])
    _require(not os.path.lexists(output), "exclusive new output directory required")
    output_parent_identity = _directory_identity(output.parent)
    profile, checkpoint, kwargs = _load_inputs(document)
    initial = dict(checkpoint["progress"])
    torch = _torch(document)
    _require(_directory_identity(output.parent) == output_parent_identity and not os.path.lexists(output),
             "output parent changed before creation")
    output.mkdir(mode=0o700)
    updated, report = profile.run_admitted_updates(checkpoint, torch=torch, **kwargs,
        max_steps=document["max_steps"], max_seconds=document["max_seconds"])
    _verify_sources(document)
    _require(report["before_progress"] == initial and report["after_progress"] == updated["progress"]
             and report["requested_steps"] == document["max_steps"]
             and report["max_seconds"] == document["max_seconds"], "numerical report boundary differs")
    checkpoint_ref = profile.save_checkpoint(updated, output / "checkpoint.json", **kwargs)
    checkpoint_ref = {key: checkpoint_ref[key] for key in ("path", "bytes", "sha256")}
    report_ref = _write_new(output / "report.json", report, MAX_REPORT_BYTES)
    count = _progress(updated["progress"]) - _progress(initial)
    receipt = {"schema_version": RECEIPT_SCHEMA, "run_id": spec.run_id,
        "job_spec_sha256": spec.canonical_sha256, "job_file_sha256": job_file_sha256,
        "prepared_inputs_sha256": document["prepared_inputs"]["sha256"],
        "initial_checkpoint_file_sha256": document["initial_checkpoint"]["sha256"],
        "profile_source_sha256": PROFILE_SHA256, "margin_weight": document["margin_weight"],
        "requested_steps": document["max_steps"], "completed_steps": count,
        "initial_progress": initial, "final_progress": dict(updated["progress"]),
        "reason": report["reason"], "status": "completed" if count == document["max_steps"] else "partial",
        "checkpoint": checkpoint_ref, "report": report_ref,
        "checkpoint_sha256": report["checkpoint_sha256"], "elapsed_seconds": report["elapsed_seconds"],
        "training_executed": bool(count), "all_requested_steps_completed": count == document["max_steps"],
        "prepared_inputs_integrity_only": True,
        "runtime_contract_sha256": None if document["runtime_contract"] is None else document["runtime_contract"]["sha256"],
        **{key: False for key in FALSE_FIELDS}}
    receipt = validate_receipt(spec, receipt, job_file_sha256=job_file_sha256)
    _verify_sources(document)
    for asset in document["physical_assets"]:
        _read_descriptor({key: asset[key] for key in ("path", "bytes", "sha256")}, MAX_ASSET_BYTES, retain=False)
    _read_descriptor(document["prepared_inputs"], MAX_PREPARED_BYTES, retain=False)
    _read_descriptor(document["initial_checkpoint"], MAX_CHECKPOINT_BYTES, retain=False)
    _read_descriptor(checkpoint_ref, MAX_CHECKPOINT_BYTES, retain=False)
    _read_descriptor(report_ref, MAX_REPORT_BYTES, retain=False)
    _write_new(output / "receipt.json", receipt, MAX_RECEIPT_BYTES)
    _verify_sources(document)
    return receipt
