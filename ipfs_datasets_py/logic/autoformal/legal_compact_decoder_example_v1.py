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
