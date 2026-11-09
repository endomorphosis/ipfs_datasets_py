"""Compact labels beside the existing source-separated decoder example.

The original public example owner replays all original inputs. Its complete
output stays unchanged; the existing compact owner supplies a separate label.
No target context, identity sidecar or provenance becomes inference input.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = "legal-compact-decoder-example/v1"
PROFILE = "candidate-source-separated-compact-content/v1"
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_SOURCE_EXAMPLE_BYTES = 8 * 1024 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_REQUEST_BYTES = 524288
MAX_EXAMPLE_REQUEST_BYTES = 16384
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_JSON_ITEMS = 2_000_000
MAX_JSON_DEPTH = 96
MAX_PRODUCER_PINS = 256
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_OWNER_SPECS = (
    ("ipfs_datasets_py.logic.formalization.autoencoder.legal_relational_decoder_example_v1",
     "logic/formalization/autoencoder/legal_relational_decoder_example_v1.py",
     "4aed1fde35efce9cdd6579be83be6901143003e996611850f6b35f0cce3f705c"),
    ("ipfs_datasets_py.logic.autoformal.legal_compact_content_v1",
     "logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
)
AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "independently_reviewed",
    "accepted", "admitted", "semantic_graph_admitted", "training_qualified",
    "training_gold_qualified", "evaluation_gold_qualified", "model_executed",
    "training_executed", "encoder_executed", "backend_executed", "Lean_admitted",
    "proof_authority", "permitted_inference_context_verified",
    "embedding_payload_verified", "split_independence_verified",
    "compact_context_is_permitted_model_input",
), False)
_OUTPUT_FIELDS = {"schema", "profile", "source_example", "source_example_sha256",
                  "compact_label", "producer_pins", "authority", "training_mask",
                  "evaluation_gold_mask", "limitations"}
_LIMITATIONS = (
    "source_example.model_input is the sole source/context input compartment; the entire original byte example is retained unchanged.",
    "compact_label.context is target-derived label information. Permitted inference context and exposure are not established and it is never copied into model_input.",
    "Compact content, context and archival identity are separate labels; no tokenizer, numerical decoder, compatible checkpoint, target budget or savings is qualified.",
    "Pending source retains null labels. Original grouping, unresolved alternatives, provenance, exposure and zero eligibility remain the existing owners' declarations.",
    "Exact public replay and source fences establish finite engineering custody only, not reviewed source meaning, legal acceptance, graph/Lean admission, training eligibility or convergence.",
    "Named raw-source fences do not independently establish executed bytecode, a transitive interpreter/third-party closure, authenticated principals or a hermetic runtime.",
)


class CompactDecoderExampleError(ValueError):
    """Complete original inputs, public replay or finite custody differ."""


def _need(condition, message):
    if not condition:
        raise CompactDecoderExampleError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _string_size(value):
    """Exact ensure_ascii=False JSON string bytes, before serialization."""
    size = 2
    for char in value:
        code = ord(char)
        _need(code != 0 and not 0xD800 <= code <= 0xDFFF, "ordinary non-NUL UTF8 required")
        if char in '"\\\b\f\n\r\t':
            size += 2
        elif code < 32:
            size += 6
        else:
            size += 1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4
    return size


def _copy(value, maximum, *, allow_bytes=False):
    """Detach exact ordinary containers with cumulative whole-value bounds."""
    remaining, items, active = maximum, MAX_JSON_ITEMS, set()

    def visit(item, depth):
        nonlocal remaining, items
        items -= 1
        _need(items >= 0 and depth <= MAX_JSON_DEPTH, "complete input item/depth bound exceeded")
        if type(item) in (dict, list):
            _need(id(item) not in active, "cyclic ordinary input refused")
            _need(len(item) <= items, "complete container item bound exceeded")
            active.add(id(item))
            remaining -= 2 + max(0, len(item) - 1)
            _need(remaining >= 0, "complete input byte bound exceeded")
            try:
                if type(item) is dict:
                    result = {}
                    for key, child in item.items():
                        _need(type(key) is str, "ordinary string keys required")
                        remaining -= 1
                        result[visit(key, depth + 1)] = visit(child, depth + 1)
                else:
                    result = [visit(child, depth + 1) for child in item]
                _need(remaining >= 0, "complete input byte bound exceeded")
                return result
            finally:
                active.remove(id(item))
        if type(item) is bytes and allow_bytes:
            remaining -= len(item)
        elif type(item) is str:
            _need(len(item) <= remaining, "complete ordinary string bound exceeded")
            remaining -= _string_size(item)
        elif item is None:
            remaining -= 4
        elif type(item) is bool:
            remaining -= 4 if item else 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded plain integer required")
            remaining -= len(str(item))
        elif type(item) is float:
            _need(math.isfinite(item), "finite ordinary JSON required")
            remaining -= len(repr(item))
        else:
            raise CompactDecoderExampleError("ordinary JSON or declared exact bytes required")
        _need(remaining >= 0, "complete input byte bound exceeded; truncation refused")
        return item

    return visit(value, 0)


def _wire(value, maximum=MAX_REPORT_BYTES):
    detached = _copy(value, maximum)
    try:
        raw = json.dumps(detached, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        raise CompactDecoderExampleError("bounded ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete canonical JSON byte bound exceeded")
    return raw


def _digest(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _fingerprint(value):
    """Unambiguous identity for already detached JSON plus exact byte inputs."""
    result = hashlib.sha256()

    def visit(item):
        if type(item) is dict:
            result.update(b"d" + str(len(item)).encode() + b":")
            for key in sorted(item):
                visit(key)
                visit(item[key])
        elif type(item) is list:
            result.update(b"l" + str(len(item)).encode() + b":")
            for child in item:
                visit(child)
        else:
            raw = item if type(item) is bytes else _wire(item, MAX_INPUT_BYTES)
            result.update((b"b" if type(item) is bytes else b"j") + str(len(raw)).encode() + b":" + raw)

    visit(value)
    return result.hexdigest()


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, "duplicate JSON key refused")
        result[key] = value
    return result


def _json(raw, maximum):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "complete nonempty JSON bytes required")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise CompactDecoderExampleError("duplicate-free ordinary UTF8 JSON required") from error
    return _copy(value, maximum)


def _snapshot(path):
    """Read only a caller-fixed or public-replay-validated producer path."""
    _need(path.is_absolute(), "absolute fixed source required")
    try:
        for parent in path.parents:
            _need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased source directory chain required")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            before = os.fstat(stream.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                  and 0 < before.st_size <= MAX_SOURCE_BYTES, "bounded regular producer source required")
            raw = stream.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink,
                              s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
              "producer changed during source read")
    except OSError as error:
        raise CompactDecoderExampleError("fixed producer source unavailable") from error
    return hashlib.sha256(raw).hexdigest(), identity(before)


_SELF_SNAPSHOT = _snapshot(_SELF_PATH)


def _package_root():
    root = _SELF_PATH.parents[2]
    _need(root.name == "ipfs_datasets_py" and _SELF_PATH ==
          root / "logic/autoformal/legal_compact_decoder_example_v1.py",
          "actual canonical autoformal package owner required")
    return root


def _direct_sources(root):
    result = {str(_SELF_PATH): _snapshot(_SELF_PATH)}
    _need(result[str(_SELF_PATH)] == _SELF_SNAPSHOT, "compact example producer changed since import")
    for _, relative, expected in _OWNER_SPECS:
        path = root / relative
        result[str(path)] = _snapshot(path)
        _need(result[str(path)][0] == expected, "fixed direct owner source differs")
    return result


def _owners():
    root = _package_root()
    before = _direct_sources(root)
    modules = tuple(importlib.import_module(name) for name, _, _ in _OWNER_SPECS)
    for module, (_, relative, _) in zip(modules, _OWNER_SPECS, strict=True):
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
              "direct owner imported outside canonical package")
    _need(_direct_sources(root) == before, "direct owner changed during import")
    return modules, root, before


def _fence(owners, original, snapshot, token, trusted):
    modules, root, before = owners
    _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
          and _fingerprint(snapshot) == token, "original or detached compact example inputs changed")
    for module, (_, relative, _) in zip(modules, _OWNER_SPECS, strict=True):
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
              "direct owner origin changed")
    _need(_direct_sources(root) == before, "direct producer changed during compact example preparation")
    for path, expected in trusted.items():
        _need(_snapshot(Path(path)) == expected, "validated producer closure changed during preparation")


def _adopt_pins(offered, root, trusted, direct):
    """Only call after a successful public owner has validated its output."""
    _need(type(offered) is dict and 0 < len(offered) <= MAX_PRODUCER_PINS,
          "bounded validated producer map required")
    for path, expected in offered.items():
        _need(type(path) is str and Path(path).is_absolute() and ".." not in Path(path).parts
              and Path(path).is_relative_to(root),
              "validated producer must belong to canonical package")
        _sha(expected, "validated producer")
        _need(path not in direct or direct[path][0] == expected, "conflicting direct producer pin")
        observed = _snapshot(Path(path))
        _need(observed[0] == expected and (path not in trusted or trusted[path] == observed),
              "validated producer bytes or identity differ")
        trusted[path] = observed
    _need(len(set(direct) | set(trusted)) <= MAX_PRODUCER_PINS, "complete combined producer bound exceeded")


def _preflight(original):
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    example = snapshot["source_example_report"]
    _need(type(example) is dict and example.get("schema") == "legal-relational-decoder-example/v1",
          "complete existing source example required")
    _sha(snapshot["expected_source_example_sha256"], "complete source example")
    _need(_digest(example, MAX_SOURCE_EXAMPLE_BYTES) == snapshot["expected_source_example_sha256"],
          "independent complete source example pin differs")
    for field in ("expected_example_request_sha256", "expected_join_report_sha256", "expected_codec_sha256"):
        _sha(snapshot[field], field)
    raw = snapshot["example_request_raw"]
    _json(raw, MAX_EXAMPLE_REQUEST_BYTES)
    _need(hashlib.sha256(raw).hexdigest() == snapshot["expected_example_request_sha256"],
          "independent example request raw pin differs")
    _need(_digest(snapshot["join_report"], MAX_SOURCE_EXAMPLE_BYTES) == snapshot["expected_join_report_sha256"],
          "independent join report pin differs")
    _need(_digest(snapshot["codec"], 1024 * 1024) == snapshot["expected_codec_sha256"],
          "independent original byte codec pin differs")
    return snapshot


def _crossbind(checked, projection, raw):
    label, encoding = checked["label"], checked["label"]["encoding"]
    canonical = encoding["canonical_request_raw_utf8"].encode("utf-8")
    request = _json(raw, MAX_REQUEST_BYTES)
    _need(_wire(request, MAX_REQUEST_BYTES) == canonical, "original byte label canonical value differs")
    expression_sha = _digest(request["expression"], MAX_REQUEST_BYTES)
    _need(label["request_raw_sha256"] == hashlib.sha256(raw).hexdigest()
          == encoding["original_request"]["sha256"] == projection["original_request_raw_sha256"]
          and encoding["original_request"]["bytes"] == len(raw)
          and encoding["canonical_request"] == {"bytes": len(canonical), "sha256": hashlib.sha256(canonical).hexdigest()}
          and projection["original_request_sha256"] == encoding["canonical_request"]["sha256"]
          and projection["original_expression_sha256"] == expression_sha
          and projection["identity_sidecar"]["original_request_sha256"] == projection["original_request_sha256"]
          and projection["identity_sidecar"]["original_expression_sha256"] == expression_sha
          and label["relational_report_sha256"] == encoding["relational_owner_report_sha256"]
          and encoding["codec_sha256"] == checked["codec_sha256"],
          "compact and original byte label commitments differ")


def prepare_compact_decoder_example_v1(source_example_report, join_report, example_request_raw, *,
        expected_source_example_sha256, expected_example_request_sha256,
        expected_join_report_sha256, join_replay_inputs, codec, expected_codec_sha256):
    """Retain a completely replayed byte example beside a separate compact label."""
    original = dict(source_example_report=source_example_report, join_report=join_report,
        example_request_raw=example_request_raw, expected_source_example_sha256=expected_source_example_sha256,
        expected_example_request_sha256=expected_example_request_sha256,
        expected_join_report_sha256=expected_join_report_sha256, join_replay_inputs=join_replay_inputs,
        codec=codec, expected_codec_sha256=expected_codec_sha256)
    snapshot = _preflight(original)
    token = _fingerprint(snapshot)
    owners = _owners()
    modules, root, direct = owners
    example_owner, compact_owner = modules
    trusted = {}
    fence = lambda: _fence(owners, original, snapshot, token, trusted)
    try:
        fence()
        checked = example_owner.validate_relational_decoder_example_v1(
            snapshot["source_example_report"], snapshot["join_report"], snapshot["example_request_raw"],
            expected_report_sha256=snapshot["expected_source_example_sha256"],
            expected_example_request_sha256=snapshot["expected_example_request_sha256"],
            expected_join_report_sha256=snapshot["expected_join_report_sha256"],
            join_replay_inputs=snapshot["join_replay_inputs"], codec=snapshot["codec"],
            expected_codec_sha256=snapshot["expected_codec_sha256"])
        fence()
        _need(_wire(checked, MAX_SOURCE_EXAMPLE_BYTES) == _wire(snapshot["source_example_report"], MAX_SOURCE_EXAMPLE_BYTES),
              "public source example replay differs")
        _adopt_pins(checked["producer_pins"], root, trusted, direct)
        fence()
        projection = None
        if checked["label"] is not None:
            raw = checked["label"]["request_raw_utf8"].encode("utf-8")
            projection = compact_owner.project_request_v1(raw,
                expected_request_sha256=checked["label"]["request_raw_sha256"])
            fence()
            _crossbind(checked, projection, raw)
            _need(type(projection["owner_pins"]) is list and len(projection["owner_pins"]) <= MAX_PRODUCER_PINS,
                  "bounded validated compact producer descriptors required")
            compact_pins = {}
            for row in projection["owner_pins"]:
                _need(type(row) is dict and set(row) == {"path", "bytes", "sha256"}
                      and type(row["path"]) is str
                      and type(row["bytes"]) is int and 0 < row["bytes"] <= MAX_SOURCE_BYTES
                      and row["path"] not in compact_pins, "unique compact producer descriptor required")
                compact_pins[row["path"]] = row["sha256"]
            _adopt_pins(compact_pins, root, trusted, direct)
            fence()
        report = {"schema": SCHEMA, "profile": PROFILE, "source_example": checked,
                  "source_example_sha256": snapshot["expected_source_example_sha256"],
                  "compact_label": projection,
                  "producer_pins": {path: state[0] for path, state in {**direct, **trusted}.items()},
                  "authority": dict(AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
                  "limitations": list(_LIMITATIONS)}
        _need(set(report) == _OUTPUT_FIELDS, "closed compact example report required")
        detached = _copy(report, MAX_REPORT_BYTES)
        _wire(detached)
        fence()
        return detached
    finally:
        fence()


def compact_decoder_example_sha256(report):
    """Canonical bounded report identity only; no owner import or authority."""
    return _digest(report)


def validate_compact_decoder_example_v1(report, source_example_report, join_report, example_request_raw, *,
        expected_report_sha256, expected_source_example_sha256, expected_example_request_sha256,
        expected_join_report_sha256, join_replay_inputs, codec, expected_codec_sha256):
    """Require independent output identity and full fresh original-input replay."""
    _sha(expected_report_sha256, "complete compact example report")
    offered = _copy(report, MAX_REPORT_BYTES)
    _need(compact_decoder_example_sha256(offered) == expected_report_sha256,
          "independent compact example report pin differs")
    regenerated = prepare_compact_decoder_example_v1(source_example_report, join_report, example_request_raw,
        expected_source_example_sha256=expected_source_example_sha256,
        expected_example_request_sha256=expected_example_request_sha256,
        expected_join_report_sha256=expected_join_report_sha256,
        join_replay_inputs=join_replay_inputs, codec=codec, expected_codec_sha256=expected_codec_sha256)
    _need(_wire(offered) == _wire(regenerated), "compact example differs from complete original-input replay")
    return regenerated


__all__ = ["prepare_compact_decoder_example_v1", "compact_decoder_example_sha256",
           "validate_compact_decoder_example_v1", "CompactDecoderExampleError"]


# Additive counted companion.  The relational byte example remains an exact
# source-only envelope; its historical target and compact profiles are intact.
COUNTED_SCHEMA = "legal-counted-compact-decoder-example/v1"
COUNTED_PROFILE = "source-only-example-with-partial-counted-label/v1"
COUNTED_TASK_ID = "typed_counted_frame_IR_reconstruction"
_COUNTED_CODEC_SHA256 = "8a1e8e0f8c6c2259b7c1040d3518974b1c84ac6d532521199f46a76b7d78dcd8"
_COUNTED_SOURCE_INPUT_FIELDS = frozenset({
    "join_report", "example_request_raw", "expected_example_request_sha256",
    "expected_join_report_sha256", "join_replay_inputs", "codec", "expected_codec_sha256",
})
_COUNTED_JOIN_INPUT_FIELDS = frozenset({
    "scope_report", "counted_report", "join_request_raw", "expected_join_request_sha256",
    "expected_scope_report_sha256", "expected_counted_report_sha256", "scope_replay_inputs",
    "counted_request_raw", "expected_counted_request_sha256",
})
_COUNTED_SOURCE_JOIN_FIELDS = frozenset({
    "scope_report", "relational_report", "join_request_raw", "expected_join_request_sha256",
    "expected_scope_report_sha256", "expected_relational_report_sha256", "scope_replay_inputs",
    "relational_request_raw", "expected_relational_request_sha256",
})
_COUNTED_OWNER_SPECS = (
    _OWNER_SPECS[0],
    ("ipfs_datasets_py.logic.autoformal.legal_source_typed_norm_join_v1",
     "logic/autoformal/legal_source_typed_norm_join_v1.py",
     "f51377e4c2446d464cd6cbbc97f6838f591e652e50c460e8084771944e937976"),
    ("ipfs_datasets_py.logic.autoformal.legal_counted_frame_v1",
     "logic/autoformal/legal_counted_frame_v1.py",
     "df91798d11e2b0da36afc75e0bc1a8b6d0a3d08bc255e7362d1c200e5e9baa13"),
)
_COUNTED_OUTPUT_FIELDS = {
    "schema", "profile", "status", "ir_family_id", "task_id", "source_example",
    "source_example_sha256", "counted_correspondence", "counted_correspondence_sha256",
    "compact_label", "compact_encoding", "codec_sha256", "input_pins", "producer_pins",
    "authority", "training_mask", "evaluation_gold_mask", "limitations",
}
_COUNTED_AUTHORITY = {**AUTHORITY, **dict.fromkeys((
    "full_norm_qualified", "checkpoint_compatibility_verified",
    "conditioning_space_training_compatibility_verified", "source_to_model_equivalence_verified",
), False)}
_COUNTED_LIMITATIONS = [
    "The complete original source-only example is retained unchanged; its model_input is the sole source/context input compartment.",
    "Counted content, target-derived context, archival identity and lexical encoding are separate unreviewed label compartments, never added to model_input.",
    "The source-only v1 and partial counted v2 joins independently replay exactly the same complete scope report and raw scope inputs; text equality alone is insufficient.",
    "The counted label remains the existing fixed authored partial frame; all original source issues, introduced assumptions and 55 node/binder rows remain unresolved.",
    "Original exposure and embedding references are caller declarations; no embedding payload or source-conditioning receipt is consumed and no inference permission or blind split is established.",
    "Normalized official-view identity is not an authenticated raw-HTML/Parquet offset mapping or an arbitrary-native SourceSpan/embedding-input correspondence.",
    "Exact fixed lexical roundtrip and source custody do not supply a compatible numerical head, learned conditioning space, total inference-token savings, training eligibility, convergence, statutory meaning or Lean admission.",
    "Named source/input fences do not attest arbitrary preloaded bytecode, third-party binaries, mutable globals, atomic concurrency or a hermetic runtime.",
]


def _counted_example_keys(value, expected, label):
    _need(type(value) is dict and set(value) == set(expected), "closed counted companion fields required: " + label)


def _counted_example_raw(raw, expected, maximum, label):
    _sha(expected, label)
    value = _json(raw, maximum)
    _need(hashlib.sha256(raw).hexdigest() == expected, "independent counted companion raw pin differs: " + label)
    return value


def _counted_example_scope_inputs(value):
    required = {"sampling_report", "raw_html", "scope_request_raw", "scope_declaration_raw",
        "expected_sampling_report_sha256", "selected_unit_ref", "expected_scope_request_sha256",
        "expected_scope_declaration_sha256", "descriptor", "expected_descriptor_sha256",
        "expected_raw_sha256", "expected_raw_bytes"}
    _need(type(value) is dict and required <= set(value) and
          not set(value) - required - {"view_limits", "limits"}, "closed complete raw scope inputs required")
    for field, expected, maximum in (("sampling_report", "expected_sampling_report_sha256", 32 * 1024 * 1024),
                                      ("descriptor", "expected_descriptor_sha256", 65536)):
        _sha(value[expected], field)
        _need(type(value[field]) is dict and _digest(value[field], maximum) == value[expected],
              "independent raw scope metadata pin differs: " + field)
    for field, expected in (("scope_request_raw", "expected_scope_request_sha256"),
                             ("scope_declaration_raw", "expected_scope_declaration_sha256")):
        _counted_example_raw(value[field], value[expected], 65536, field)
    _sha(value["expected_raw_sha256"], "original HTML")
    _need(type(value["raw_html"]) is bytes and 0 < len(value["raw_html"]) <= 8_000_000
          and type(value["expected_raw_bytes"]) is int and value["expected_raw_bytes"] == len(value["raw_html"])
          and hashlib.sha256(value["raw_html"]).hexdigest() == value["expected_raw_sha256"],
          "complete independent original HTML pins required")
    _need(type(value["selected_unit_ref"]) is dict, "original selected-unit reference required")
    _wire(value["selected_unit_ref"], 65536)
    for field in ("view_limits", "limits"):
        if field in value:
            _wire(value[field], 65536)


def _counted_example_preflight(original):
    """Bound and detach all original inputs before any operation owner loads."""
    data = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    source, proposal = data["source_example_report"], data["counted_join_report"]
    for report, expected, schema, profile, label in (
        (source, data["expected_source_example_sha256"], "legal-relational-decoder-example/v1",
         "candidate-source-separated-relational-byte-target/v1", "source example"),
        (proposal, data["expected_counted_join_sha256"], "legal-source-typed-norm-join-proposal/v2",
         "whole-source-partial-counted-frame-correspondence/v1", "counted join"),
    ):
        _sha(expected, label)
        _need(type(report) is dict and report.get("schema") == schema and report.get("profile") == profile,
              "exact existing counted companion upstream profile required: " + label)
        _need(_digest(report, MAX_SOURCE_EXAMPLE_BYTES) == expected, "independent complete upstream report differs: " + label)
    _need(source.get("label", "absent") is None and source.get("status") == "source_only_pending_target",
          "counted companion requires an unchanged source-only original example")
    _need(type(source.get("model_input")) is dict and set(source["model_input"]) == {"source_text", "context"},
          "sole original closed source/context input required")
    source_inputs, counted_inputs = data["source_example_inputs"], data["counted_join_inputs"]
    _counted_example_keys(source_inputs, _COUNTED_SOURCE_INPUT_FIELDS, "original source example inputs")
    _counted_example_keys(counted_inputs, _COUNTED_JOIN_INPUT_FIELDS, "original counted join inputs")
    source_join = source_inputs["join_report"]
    _need(type(source_join) is dict and source_join.get("schema") == "legal-source-typed-norm-join-proposal/v1"
          and source_join.get("profile") == "whole-source-partial-typed-correspondence/v1"
          and source_join.get("status") == "source_only_pending_typed_interpretation_retained"
          and source_join.get("typed_candidate", "absent") is None,
          "original v1 source-only join required; no relational target substitution")
    _sha(source_inputs["expected_join_report_sha256"], "original source-only join")
    _need(_digest(source_join, MAX_SOURCE_EXAMPLE_BYTES) == source_inputs["expected_join_report_sha256"],
          "independent original source-only join differs")
    source_replay = source_inputs["join_replay_inputs"]
    _counted_example_keys(source_replay, _COUNTED_SOURCE_JOIN_FIELDS, "source-only v1 replay")
    for field in ("relational_report", "relational_request_raw", "expected_relational_report_sha256",
                  "expected_relational_request_sha256"):
        _need(source_replay[field] is None, "all original relational inputs must remain null")
    request = _counted_example_raw(source_inputs["example_request_raw"],
        source_inputs["expected_example_request_sha256"], MAX_EXAMPLE_REQUEST_BYTES, "source example request")
    _counted_example_keys(request, {"schema", "task_id", "exposure_status", "embedding_reference"}, "source example request")
    _need(request["schema"] == "legal-relational-decoder-example-request/v1"
          and request["task_id"] == "typed_relational_IR_reconstruction"
          and request["exposure_status"] in ("exposed", "unknown"), "existing source example declaration required")
    embedding = request["embedding_reference"]
    if embedding is not None:
        _counted_example_keys(embedding, {"dimension", "producer_id", "profile_id", "token_limit", "cache_key",
            "payload_bytes", "payload_sha256", "source_input_sha256"}, "original embedding declaration")
        _need(type(embedding["dimension"]) is int and embedding["dimension"] in (8, 384, 768),
              "original supported declared embedding dimension required")
        for field in ("producer_id", "profile_id", "cache_key"):
            _need(type(embedding[field]) is str and 0 < len(embedding[field]) <= 512 and
                  embedding[field].strip() and embedding[field].isprintable(), "bounded original embedding declaration required")
        _need(embedding["token_limit"] is None or type(embedding["token_limit"]) is int and
              0 < embedding["token_limit"] <= (1 << 31) - 1, "original declared token limit required")
        _need(type(embedding["payload_bytes"]) is int and 0 < embedding["payload_bytes"] <= (1 << 63) - 1,
              "original declared embedding byte count required")
        for field in ("payload_sha256", "source_input_sha256"):
            _sha(embedding[field], field)
    for replay, request_schema, label in (
        (source_replay, "legal-source-typed-norm-join-request/v1", "source-only join request"),
        (counted_inputs, "legal-source-typed-norm-join-request/v2", "counted join request"),
    ):
        join_request = _counted_example_raw(replay["join_request_raw"], replay["expected_join_request_sha256"],
                                            MAX_REQUEST_BYTES, label)
        _need(type(join_request) is dict and join_request.get("schema") == request_schema,
              "exact original join request schema required")
        _sha(replay["expected_scope_report_sha256"], "complete shared scope")
        _need(_digest(replay["scope_report"], 1024 * 1024) == replay["expected_scope_report_sha256"],
              "independent complete shared scope pin differs")
    _need(type(source_replay["scope_replay_inputs"]) is dict and type(counted_inputs["scope_replay_inputs"]) is dict,
          "complete original scope replay dictionaries required")
    _counted_example_scope_inputs(source_replay["scope_replay_inputs"])
    _counted_example_scope_inputs(counted_inputs["scope_replay_inputs"])
    _need(_fingerprint(source_replay["scope_replay_inputs"]) == _fingerprint(counted_inputs["scope_replay_inputs"]),
          "complete original scope replay inputs must be exactly identical")
    _need(_wire(source_replay["scope_report"], 1024 * 1024) == _wire(counted_inputs["scope_report"], 1024 * 1024)
          and source_replay["expected_scope_report_sha256"] == counted_inputs["expected_scope_report_sha256"],
          "complete independently replayed scope reports must be identical")
    for report in (source_join, proposal):
        _need(type(report.get("source_scope_report")) is dict and type(report.get("source_custody")) is dict,
              "complete original scope and custody reports required")
        _need(_wire(report["source_scope_report"], 1024 * 1024) == _wire(counted_inputs["scope_report"], 1024 * 1024),
              "upstream full scope differs from original shared replay")
    _need(_wire(source_join["source_custody"]) == _wire(proposal["source_custody"]),
          "complete physical source custody differs between source-only and counted joins")
    _need(source_join.get("provenance_ledger") == [] and source_join.get("introduced_unresolved") == [],
          "source-only original retains no manufactured typed correspondence")
    counted_request = _counted_example_raw(counted_inputs["counted_request_raw"],
        counted_inputs["expected_counted_request_sha256"], 131072, "counted frame request")
    _need(type(counted_request) is dict and counted_request.get("schema") == "legal-counted-frame-request/v1",
          "original authored counted request required")
    _sha(counted_inputs["expected_counted_report_sha256"], "complete original counted frame report")
    _need(_digest(counted_inputs["counted_report"], 1024 * 1024) == counted_inputs["expected_counted_report_sha256"],
          "complete original counted frame pin differs")
    _need(type(proposal.get("counted_frame_report")) is dict and
          _wire(proposal["counted_frame_report"], 1024 * 1024) == _wire(counted_inputs["counted_report"], 1024 * 1024),
          "counted proposal differs from independent complete counted frame")
    for codec, expected, label in ((source_inputs["codec"], source_inputs["expected_codec_sha256"], "source byte codec"),
                                    (data["codec"], data["expected_codec_sha256"], "counted lexical codec")):
        _sha(expected, label)
        _need(_digest(codec, 1024 * 1024) == expected, "independent codec identity differs: " + label)
    _need(type(data["codec"]) is dict and data["codec"].get("schema") == "legal-counted-compact-token-codec/v1",
          "separate counted codec required; no legacy codec alias")
    _need(data["expected_codec_sha256"] == _COUNTED_CODEC_SHA256,
          "exact qualified counted codec identity required before operation imports")
    return data


def _counted_example_direct_sources(root):
    result = {str(_SELF_PATH): _snapshot(_SELF_PATH)}
    _need(result[str(_SELF_PATH)] == _SELF_SNAPSHOT, "counted companion producer changed since import")
    for _, relative, expected in _COUNTED_OWNER_SPECS:
        path = root / relative
        result[str(path)] = _snapshot(path)
        _need(result[str(path)][0] == expected, "fixed counted companion direct owner source differs")
    return result


def _counted_example_owners():
    root = _package_root()
    before = _counted_example_direct_sources(root)
    modules = tuple(importlib.import_module(name) for name, _, _ in _COUNTED_OWNER_SPECS)
    for module, (_, relative, _) in zip(modules, _COUNTED_OWNER_SPECS, strict=True):
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
              "counted companion direct owner imported outside canonical package")
    _need(_counted_example_direct_sources(root) == before, "counted direct owner changed during import")
    return modules, root, before


def _counted_example_fence(owners, original, data, token, trusted, offered=()):
    modules, root, before = owners
    _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
          and _fingerprint(data) == token, "original or detached counted companion inputs changed")
    for module, (_, relative, _) in zip(modules, _COUNTED_OWNER_SPECS, strict=True):
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
              "counted companion direct owner origin changed")
    _need(_counted_example_direct_sources(root) == before, "counted companion direct producer changed")
    for path, expected in trusted.items():
        _need(_snapshot(Path(path)) == expected, "counted companion trusted producer closure changed")
    for original_report, captured, commitment in offered:
        _need(_wire(original_report) == commitment and _wire(captured) == commitment,
              "offered counted companion report changed")


def _counted_example_known_pins(owners, data):
    """Discover actual producer maps before any offered map can select reads."""
    modules, root, direct = owners
    example_owner, join_owner, counted_owner = modules
    scope_owner, actual_counted = join_owner._counted_owners()
    _need(actual_counted is counted_owner, "actual counted operation owner differs")
    counted_inputs = data["counted_join_inputs"]
    # The existing join owner checks both actual upstream maps before its reads.
    counted_join_pins = join_owner._counted_producer_pins(scope_owner, counted_owner,
        counted_inputs["scope_report"], counted_inputs["counted_report"])
    scope_pins = scope_owner._pins(scope_owner._owners())
    source_join_pins = {**scope_pins,
        str(root / "logic/autoformal/legal_source_typed_norm_join_v1.py"):
            direct[str(root / "logic/autoformal/legal_source_typed_norm_join_v1.py")][0]}
    source_direct = example_owner._owner_pins(example_owner._owners())
    source_example_pins = dict(source_join_pins)
    for path, expected in source_direct.items():
        _need(path not in source_example_pins or source_example_pins[path] == expected,
              "actual source example producer conflict")
        source_example_pins[path] = expected
    counted_pins = counted_owner._owners()[-1]
    for report, expected, label in (
        (data["source_example_report"], source_example_pins, "source example"),
        (data["source_example_inputs"]["join_report"], source_join_pins, "source-only join"),
        (data["counted_join_report"], counted_join_pins, "counted join"),
    ):
        _need(type(report.get("producer_pins")) is dict and report["producer_pins"] == expected,
              "offered producer map differs from actual trusted owners: " + label)
    pins = {path: witness[0] for path, witness in direct.items()}
    for known in (source_example_pins, counted_join_pins, counted_pins):
        _need(type(known) is dict and 0 < len(known) <= MAX_PRODUCER_PINS, "bounded actual producer map required")
        for path, expected in known.items():
            _need(type(path) is str and Path(path).is_absolute() and Path(path).is_relative_to(root)
                  and ".." not in Path(path).parts, "actual producer must be canonical package source")
            _sha(expected, "actual producer")
            _need(path not in pins or pins[path] == expected, "actual producer closure conflict")
            pins[path] = expected
    _need(len(pins) <= MAX_PRODUCER_PINS, "complete counted producer bound exceeded")
    trusted = {}
    for path, expected in pins.items():
        observed = _snapshot(Path(path))
        _need(observed[0] == expected, "actual producer changed before counted companion replay")
        trusted[path] = observed
    return trusted, source_example_pins, counted_join_pins, counted_pins


def _counted_example_finish(report, fence):
    fence()
    _need(set(report) == _COUNTED_OUTPUT_FIELDS, "closed counted companion report required")
    result = _copy(report, MAX_REPORT_BYTES)
    _wire(result)
    fence()
    return result


def _counted_example_no_authority(value):
    if type(value) is dict:
        for name, child in value.items():
            if name == "authority":
                _need(type(child) is dict and all(type(flag) is bool and flag is False for flag in child.values()),
                      "counted companion dependency authority must remain false")
            if name.endswith("_mask"):
                _need(type(child) is int and child == 0, "counted companion masks must remain integer zero")
            if name in {"checkpoint_compatibility_verified", "numerical_head_compatible",
                        "conditioning_space_training_compatibility_verified", "permitted_inference_context_verified"}:
                _need(child is False, "counted companion grants no numerical or context compatibility")
            _counted_example_no_authority(child)
    elif type(value) is list:
        for child in value:
            _counted_example_no_authority(child)


def _counted_example_projection_binding(projection, proposal, replay):
    required = {"schema", "profile", "status", "content", "context", "identity_sidecar", "content_sha256",
        "context_sha256", "identity_sha256", "original_request_sha256", "original_request_canonical_sha256",
        "original_expression_sha256", "counts", "context_origin", "roundtrip_receipt", "counted_report"}
    _need(type(projection) is dict and required <= set(projection), "complete counted projection required")
    request = _json(replay["counted_request_raw"], 131072)
    expression = request["expression"]
    node_ids, binder_names = [], []

    def identities(node):
        node_ids.append(node["node_id"])
        binder_names.extend(binder["name"] for binder in node["binders"])
        for child in node["arguments"]:
            identities(child)

    identities(expression["root"])
    content_sha = _digest(projection["content"], 131072)
    context_sha = _digest(projection["context"], 131072)
    canonical_request_sha = _digest(request, 131072)
    expression_sha = _digest(expression, 131072)
    expected_identity = {"schema": "legal-counted-compact-identity/v1",
        "expression_id": expression["expression_id"], "signature_id": expression["signature"]["signature_id"],
        "node_ids": node_ids, "binder_names": binder_names,
        "content_sha256": content_sha, "context_sha256": context_sha,
        "original_request_sha256": replay["expected_counted_request_sha256"],
        "original_request_canonical_sha256": canonical_request_sha,
        "original_expression_sha256": expression_sha}
    _need(projection["schema"] == "legal-counted-compact-projection/v1"
          and projection["profile"] == "authored-at-most-three-many-sorted-compact/v1"
          and projection["status"] == "authored_counted_content_projected_unreviewed"
          and projection["context_origin"] == "target_derived_authored_declaration",
          "existing counted projection schema/profile/context origin required")
    _need(projection["original_request_sha256"] == replay["expected_counted_request_sha256"]
          and projection["original_request_canonical_sha256"] == canonical_request_sha
          and projection["original_expression_sha256"] == expression_sha
          and projection["content_sha256"] == content_sha and projection["context_sha256"] == context_sha
          and _wire(projection["identity_sidecar"], 131072) == _wire(expected_identity, 131072)
          and projection["identity_sha256"] == _digest(expected_identity, 131072),
          "counted projection identities differ from independently pinned original request")
    _need(_wire(projection["counts"]) == _wire(proposal["counted_frame_report"]["counts"])
          and _wire(projection["roundtrip_receipt"]) == _wire({"canonical_request_exact": True,
              "typed_expression_exact": True, "node_identity_exact": True,
              "original_transport_whitespace_restored": False}),
          "counted projection counts or exact canonical roundtrip receipt differ")
    _counted_example_no_authority(projection)


def _counted_example_arguments(source_example_report, counted_join_report,
        expected_source_example_sha256, expected_counted_join_sha256, source_example_inputs,
        counted_join_inputs, codec, expected_codec_sha256):
    return dict(source_example_report=source_example_report, counted_join_report=counted_join_report,
        expected_source_example_sha256=expected_source_example_sha256,
        expected_counted_join_sha256=expected_counted_join_sha256, source_example_inputs=source_example_inputs,
        counted_join_inputs=counted_join_inputs, codec=codec, expected_codec_sha256=expected_codec_sha256)


def prepare_counted_compact_decoder_example_v1(source_example_report, counted_join_report, *,
        expected_source_example_sha256, expected_counted_join_sha256, source_example_inputs,
        counted_join_inputs, codec, expected_codec_sha256):
    """Keep the source-only original and a separately replayed counted label."""
    original = _counted_example_arguments(source_example_report, counted_join_report,
        expected_source_example_sha256, expected_counted_join_sha256, source_example_inputs,
        counted_join_inputs, codec, expected_codec_sha256)
    data = _counted_example_preflight(original)
    token = _fingerprint(data)
    owners = _counted_example_owners()
    example_owner, join_owner, counted_owner = owners[0]
    trusted = {}
    fence = lambda: _counted_example_fence(owners, original, data, token, trusted)
    try:
        fence()
        # Fixed request rejection precedes lazy syntax/producer discovery.
        counted_owner._parse(data["counted_join_inputs"]["counted_request_raw"],
            data["counted_join_inputs"]["expected_counted_request_sha256"])
        discovered, source_pins, join_pins, counted_pins = _counted_example_known_pins(owners, data)
        trusted.update(discovered)
        fence()
        source = example_owner.validate_relational_decoder_example_v1(data["source_example_report"],
            expected_report_sha256=data["expected_source_example_sha256"], **data["source_example_inputs"])
        fence()
        _need(_wire(source, MAX_SOURCE_EXAMPLE_BYTES) == _wire(data["source_example_report"], MAX_SOURCE_EXAMPLE_BYTES)
              and source["producer_pins"] == source_pins and source["label"] is None,
              "public original source-only example replay differs")
        proposal = join_owner.validate_source_typed_norm_join_v2(data["counted_join_report"],
            expected_report_sha256=data["expected_counted_join_sha256"], **data["counted_join_inputs"])
        fence()
        _need(_wire(proposal, MAX_SOURCE_EXAMPLE_BYTES) == _wire(data["counted_join_report"], MAX_SOURCE_EXAMPLE_BYTES)
              and proposal["producer_pins"] == join_pins,
              "public original counted join replay differs")
        scope = proposal["source_scope_report"]
        _need(_wire(source["model_input"], 65536) == _wire(scope["scope_request"], 65536)
              and source["source_input_sha256"] == _digest(scope["scope_request"], 65536),
              "sole original source/context input differs from counted source scope")
        replay = data["counted_join_inputs"]
        projection = counted_owner.project_counted_frame_request_v1(replay["counted_request_raw"],
            expected_request_sha256=replay["expected_counted_request_sha256"])
        fence()
        _need(projection["producer_pins"] == counted_pins
              and _wire(projection["counted_report"], 1024 * 1024) == _wire(proposal["counted_frame_report"], 1024 * 1024)
              and projection["original_request_sha256"] == replay["expected_counted_request_sha256"],
              "counted projection differs from independently replayed original frame")
        _counted_example_projection_binding(projection, proposal, replay)
        content_raw = _wire(projection["content"], 131072)
        context_raw = _wire(projection["context"], 131072)
        encoding = counted_owner.encode_counted_frame_tokens_v1(content_raw, context_raw,
            expected_content_sha256=projection["content_sha256"], expected_context_sha256=projection["context_sha256"],
            codec=data["codec"], expected_codec_sha256=data["expected_codec_sha256"])
        fence()
        _need(encoding["producer_pins"] == counted_pins
              and encoding["schema"] == "legal-counted-compact-token-encoding/v1"
              and encoding["profile"] == "authored-at-most-three-many-sorted-compact/v1"
              and encoding["status"] == "encoded_unreviewed_counted_content"
              and encoding["content_sha256"] == projection["content_sha256"]
              and encoding["context_sha256"] == projection["context_sha256"],
              "counted lexical label differs from original counted projection")
        decoded = counted_owner.decode_counted_frame_tokens_v1(encoding["target_ids"], context_raw,
            expected_context_sha256=projection["context_sha256"], codec=data["codec"],
            expected_codec_sha256=data["expected_codec_sha256"])
        fence()
        _need(decoded["producer_pins"] == counted_pins and decoded["status"] == "valid_candidate"
              and decoded["schema"] == "legal-counted-compact-token-candidate/v1"
              and decoded["profile"] == "authored-at-most-three-many-sorted-compact/v1"
              and decoded["generated_ids"] == encoding["target_ids"]
              and decoded["content_sha256"] == projection["content_sha256"]
              and decoded["context_sha256"] == projection["context_sha256"]
              and decoded["codec_sha256"] == encoding["codec_sha256"] == data["expected_codec_sha256"]
              and decoded["canonical_content_raw_utf8"].encode("utf-8") == content_raw
              == encoding["canonical_content_raw_utf8"].encode("utf-8")
              and _wire(decoded["prediction"]) == _wire(encoding["prediction"])
              and _wire(decoded["counts"]) == _wire(encoding["counts"])
              == _wire(proposal["counted_frame_report"]["counts"])
              and type(encoding["total_token_count"]) is int
              and encoding["total_token_count"] == len(encoding["target_ids"])
              and _wire(encoding["lexical_tokens"]) == _wire([
                  data["codec"]["vocabulary"][index] for index in encoding["target_ids"][1:-1]])
              and type(encoding["lexical_token_count"]) is int
              and encoding["lexical_token_count"] == len(encoding["lexical_tokens"]),
              "complete counted lexical label differs from genuine decoded original content")
        _counted_example_no_authority(encoding)
        _counted_example_no_authority(decoded)
        result = {"schema": COUNTED_SCHEMA, "profile": COUNTED_PROFILE,
            "status": "unreviewed_counted_companion_prepared", "ir_family_id": "legal_ir", "task_id": COUNTED_TASK_ID,
            "source_example": source, "source_example_sha256": data["expected_source_example_sha256"],
            "counted_correspondence": proposal, "counted_correspondence_sha256": data["expected_counted_join_sha256"],
            "compact_label": projection, "compact_encoding": encoding, "codec_sha256": data["expected_codec_sha256"],
            "input_pins": {
                "source_example_inputs_commitment_sha256": _fingerprint(data["source_example_inputs"]),
                "counted_join_inputs_commitment_sha256": _fingerprint(replay),
                "source_scope_report_full_canonical_sha256": replay["expected_scope_report_sha256"],
                "example_request_raw_sha256": data["source_example_inputs"]["expected_example_request_sha256"],
                "source_only_join_full_canonical_sha256": data["source_example_inputs"]["expected_join_report_sha256"],
                "counted_request_raw_sha256": replay["expected_counted_request_sha256"],
                "counted_report_full_canonical_sha256": replay["expected_counted_report_sha256"],
                "source_input_sha256": source["source_input_sha256"],
                "physical_source_group_sha256": source["source_group_sha256"],
            },
            "producer_pins": {path: state[0] for path, state in trusted.items()},
            "authority": dict(_COUNTED_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
            "limitations": list(_COUNTED_LIMITATIONS)}
        return _counted_example_finish(result, fence)
    finally:
        fence()


def validate_counted_compact_decoder_example_v1(report, source_example_report, counted_join_report, *,
        expected_report_sha256, expected_source_example_sha256, expected_counted_join_sha256,
        source_example_inputs, counted_join_inputs, codec, expected_codec_sha256):
    """Pin the whole offered companion, then fully regenerate both input chains."""
    _sha(expected_report_sha256, "complete counted companion")
    captured = _copy(report, MAX_REPORT_BYTES)
    _counted_example_keys(captured, _COUNTED_OUTPUT_FIELDS, "offered counted companion")
    _need(captured["schema"] == COUNTED_SCHEMA and captured["profile"] == COUNTED_PROFILE
          and captured["status"] == "unreviewed_counted_companion_prepared", "exact counted companion profile required")
    commitment = _wire(captured)
    _need(hashlib.sha256(commitment).hexdigest() == expected_report_sha256,
          "independent complete counted companion report pin differs")
    original = _counted_example_arguments(source_example_report, counted_join_report,
        expected_source_example_sha256, expected_counted_join_sha256, source_example_inputs,
        counted_join_inputs, codec, expected_codec_sha256)
    data = _counted_example_preflight(original)
    token = _fingerprint(data)
    owners = _counted_example_owners()
    trusted = {}
    fence = lambda: _counted_example_fence(owners, original, data, token, trusted,
        ((report, captured, commitment),))
    try:
        fence()
        owners[0][2]._parse(data["counted_join_inputs"]["counted_request_raw"],
            data["counted_join_inputs"]["expected_counted_request_sha256"])
        trusted.update(_counted_example_known_pins(owners, data)[0])
        fence()
        regenerated = prepare_counted_compact_decoder_example_v1(**data)
        fence()
        _need(_wire(regenerated) == commitment, "counted companion differs from complete original-input replay")
        return _counted_example_finish(regenerated, fence)
    finally:
        fence()


__all__ += ["prepare_counted_compact_decoder_example_v1", "validate_counted_compact_decoder_example_v1"]
