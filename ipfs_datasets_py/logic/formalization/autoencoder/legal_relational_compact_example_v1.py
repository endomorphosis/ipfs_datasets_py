"""Source-separated compact labels accompanying complete original byte examples.

The original example owner replays source custody and eligibility; the compact
owner replays exact target transport. This adapter changes neither model inputs
nor the original byte label, and grants no source, training or proof authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = "legal-relational-compact-example/v1"
PROFILE = "candidate-source-separated-relational-compact-companion/v1"
TASK_ID = "typed_relational_IR_reconstruction"
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 16 * 1024
MAX_CODEC_BYTES = 32768
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PREPARE_FIELDS = {"join_report", "example_request_raw", "expected_example_request_sha256",
    "expected_join_report_sha256", "join_replay_inputs", "codec", "expected_codec_sha256"}
_JOIN_FIELDS = {"scope_report", "relational_report", "join_request_raw", "expected_join_request_sha256",
    "expected_scope_report_sha256", "expected_relational_report_sha256", "scope_replay_inputs",
    "relational_request_raw", "expected_relational_request_sha256"}
_SCOPE_FIELDS = {"sampling_report", "raw_html", "scope_request_raw", "scope_declaration_raw",
    "expected_sampling_report_sha256", "selected_unit_ref", "expected_scope_request_sha256",
    "expected_scope_declaration_sha256", "descriptor", "expected_descriptor_sha256",
    "expected_raw_sha256", "expected_raw_bytes"}
_FIELDS = {"schema", "profile", "ir_family_id", "task_id", "status", "original_example",
    "original_example_sha256", "model_input", "source_input_sha256", "source_group_sha256",
    "compact_label", "input_pins", "split", "training_mask", "evaluation_gold_mask", "authority",
    "producer_pins"}
_INPUT_PIN_FIELDS = {"original_example_sha256", "original_example_request_sha256", "join_report_sha256",
    "original_codec_sha256", "compact_codec_sha256", "original_replay_inputs_sha256"}
_SELF_PATH = Path(__file__).absolute()


class RelationalCompactExampleError(ValueError):
    """An original commitment, complete bound or source-separated contract failed."""


def _need(ok, message):
    if not ok:
        raise RelationalCompactExampleError(message)


def _keys(value, fields):
    _need(type(value) is dict and set(value) == set(fields), "closed exact fields required")


def _sha(value):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "independent lowercase SHA256 required")


def _copy(value, maximum, *, allow_bytes=False):
    remaining, nodes = maximum, 2_000_000
    def visit(item, depth=0):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "complete input node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + len(item)
            _need(remaining >= 0 and len(item) <= nodes, "complete object bound exceeded")
            _need(all(type(k) is str for k in item), "ordinary string keys required")
            return {visit(k, depth + 1): visit(v, depth + 1) for k, v in item.items()}
        if type(item) is list:
            remaining -= 2 + len(item)
            _need(remaining >= 0 and len(item) <= nodes, "complete list bound exceeded")
            return [visit(child, depth + 1) for child in item]
        if type(item) is bytes and allow_bytes:
            remaining -= len(item)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded ordinary UTF8 required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError:
                raise RelationalCompactExampleError("ordinary UTF8 required") from None
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(abs(item) <= (1 << 63) - 1, "bounded plain integer required")
            remaining -= len(str(item))
        elif type(item) is float:
            _need(math.isfinite(item), "finite JSON required")
            remaining -= len(repr(item))
        else:
            raise RelationalCompactExampleError("plain JSON/exact bytes required")
        _need(remaining >= 0, "complete byte bound exceeded; truncation refused")
        return item
    return visit(value)


def _wire(value, maximum=MAX_REPORT_BYTES):
    detached = _copy(value, maximum)
    raw = json.dumps(detached, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _digest(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _fingerprint(value):
    digest = hashlib.sha256()
    def visit(item):
        if type(item) is dict:
            digest.update(b"d" + str(len(item)).encode() + b":")
            for key in sorted(item):
                visit(key); visit(item[key])
        elif type(item) is list:
            digest.update(b"l" + str(len(item)).encode() + b":")
            for child in item:
                visit(child)
        else:
            raw = item if type(item) is bytes else _wire(item, MAX_INPUT_BYTES)
            digest.update((b"b" if type(item) is bytes else b"j") + str(len(raw)).encode() + b":" + raw)
    visit(value)
    return digest.hexdigest()


def _raw(raw, expected, maximum):
    _sha(expected)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded complete original bytes required")
    _need(hashlib.sha256(raw).hexdigest() == expected, "independent original byte pin differs")


def _preflight(original):
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    for report_key, pin_key, limit in (("original_example_report", "expected_original_example_sha256", MAX_REPORT_BYTES),
                                     ("compact_codec", "expected_compact_codec_sha256", MAX_CODEC_BYTES)):
        _sha(snapshot[pin_key])
        _need(type(snapshot[report_key]) is dict, "ordinary complete report/codec required")
        _need(_digest(snapshot[report_key], limit) == snapshot[pin_key], "independent original report/codec pin differs")
    replay = snapshot["original_replay_inputs"]
    _keys(replay, _PREPARE_FIELDS)
    _raw(replay["example_request_raw"], replay["expected_example_request_sha256"], MAX_REQUEST_BYTES)
    def pairs(rows):
        value = {}
        for key, child in rows:
            _need(key not in value, "duplicate original example request key")
            value[key] = child
        return value
    try:
        request = json.loads(replay["example_request_raw"].decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise RelationalCompactExampleError("bounded duplicate-free original example request required") from None
    _keys(request, {"schema", "task_id", "exposure_status", "embedding_reference"})
    _need(request["schema"] == "legal-relational-decoder-example-request/v1" and request["task_id"] == TASK_ID and
          type(request["exposure_status"]) is str and request["exposure_status"] in {"exposed", "unknown"},
          "original candidate example request required")
    _wire(request, MAX_REQUEST_BYTES)
    for report_key, pin_key, limit in (("join_report", "expected_join_report_sha256", MAX_REPORT_BYTES),
                                     ("codec", "expected_codec_sha256", MAX_CODEC_BYTES)):
        _sha(replay[pin_key])
        _need(type(replay[report_key]) is dict, "ordinary original report/codec required")
        _need(_digest(replay[report_key], limit) == replay[pin_key], "independent original replay pin differs")
    join = replay["join_replay_inputs"]
    _keys(join, _JOIN_FIELDS)
    scope = join["scope_replay_inputs"]
    _need(type(scope) is dict and _SCOPE_FIELDS <= set(scope) and
          not (set(scope) - _SCOPE_FIELDS - {"view_limits", "limits"}), "closed original scope inputs required")
    _raw(join["join_request_raw"], join["expected_join_request_sha256"], 524288)
    _sha(join["expected_scope_report_sha256"])
    _need(_digest(join["scope_report"], 1024 * 1024) == join["expected_scope_report_sha256"], "original scope pin differs")
    absent = [join[k] is None for k in ("relational_report", "relational_request_raw",
                                      "expected_relational_report_sha256", "expected_relational_request_sha256")]
    _need(all(absent) or not any(absent), "original relational inputs must all be present or null")
    if not any(absent):
        _raw(join["relational_request_raw"], join["expected_relational_request_sha256"], 524288)
        _sha(join["expected_relational_report_sha256"])
        _need(_digest(join["relational_report"]) == join["expected_relational_report_sha256"], "original relational pin differs")
    for key, limit in (("raw_html", 8_000_000), ("scope_request_raw", 65536), ("scope_declaration_raw", 65536)):
        pin = "expected_raw_sha256" if key == "raw_html" else "expected_" + key[:-4] + "_sha256"
        _raw(scope[key], scope[pin], limit)
    _need(type(scope["expected_raw_bytes"]) is int and scope["expected_raw_bytes"] == len(scope["raw_html"]), "original HTML size differs")
    for key, pin_key, limit in (("sampling_report", "expected_sampling_report_sha256", 32 * 1024 * 1024),
                              ("descriptor", "expected_descriptor_sha256", 65536)):
        _sha(scope[pin_key])
        _need(_digest(scope[key], limit) == scope[pin_key], "original sampled-source pin differs")
    for key in ("selected_unit_ref", "view_limits", "limits"):
        if key in scope:
            _wire(scope[key], 65536)
    return snapshot


def _source_snapshot(path):
    path = Path(path).absolute()
    try:
        _need(all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents), "direct source parents required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                  0 < before.st_size <= MAX_SOURCE_BYTES, "bounded regular source required")
            raw = bytearray()
            while len(raw) <= MAX_SOURCE_BYTES:
                chunk = os.read(fd, min(65536, MAX_SOURCE_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            _need(len(raw) == before.st_size and identity(before) == identity(os.fstat(fd)) == identity(path.lstat()),
                  "source changed during snapshot")
            return hashlib.sha256(raw).hexdigest(), identity(before)
        finally:
            os.close(fd)
    except OSError:
        raise RelationalCompactExampleError("trusted source snapshot refused") from None


_SELF_SNAPSHOT = _source_snapshot(_SELF_PATH)


def _owners():
    from . import legal_relational_decoder_example_v1 as example
    from . import legal_relational_compact_codec_v1 as compact
    for owner, filename in ((example, "legal_relational_decoder_example_v1.py"), (compact, "legal_relational_compact_codec_v1.py")):
        _need(Path(owner.__file__).absolute() == _SELF_PATH.with_name(filename), "original sibling owner required")
    return example, compact


@contextmanager
def _guard(fence):
    fence()
    try:
        yield
    except BaseException as original_error:
        try:
            fence()
        except BaseException:
            original_error.add_note("Compact companion final source/input fence also failed; no result was produced.")
        raise
    else:
        fence()


def _report(report):
    value = _copy(report, MAX_REPORT_BYTES)
    _keys(value, _FIELDS)
    _need(value["schema"] == SCHEMA and value["profile"] == PROFILE and value["task_id"] == TASK_ID and
          value["ir_family_id"] == "legal_ir", "exact compact companion identity required")
    original = value["original_example"]
    _sha(value["original_example_sha256"])
    _need(type(original) is dict and _digest(original) == value["original_example_sha256"], "complete original example binding differs")
    for key in ("model_input", "source_input_sha256", "source_group_sha256", "status", "split"):
        _need(key in original and _wire(value[key]) == _wire(original[key]), "original source compartment differs")
    _keys(value["model_input"], {"source_text", "context"})
    _need(_digest(value["model_input"], 65536) == value["source_input_sha256"] and value["split"] == "unassigned",
          "source-only model input or split differs")
    for key in ("training_mask", "evaluation_gold_mask"):
        _need(type(value[key]) is int and value[key] == 0, "zero candidate masks required")
    _need(type(original.get("authority")) is dict and type(value["authority"]) is dict and
          set(value["authority"]) == set(original["authority"]) | {"provider_tokens_measured", "compact_checkpoint_qualified"}
          and all(flag is False for flag in value["authority"].values()), "candidate-only authority required")
    _keys(value["input_pins"], _INPUT_PIN_FIELDS)
    for pin in value["input_pins"].values():
        _sha(pin)
    _need(value["input_pins"]["original_example_sha256"] == value["original_example_sha256"], "original report pin differs")
    label = value["compact_label"]
    _need((label is None) == (original.get("label") is None), "pending source must retain null compact label")
    if label is not None:
        _keys(label, {"request_raw_sha256", "relational_report_sha256", "encoding", "encoding_sha256"})
        _need(label["request_raw_sha256"] == original["label"]["request_raw_sha256"] and
              label["relational_report_sha256"] == original["label"]["relational_report_sha256"] and
              _digest(label["encoding"]) == label["encoding_sha256"], "compact label binding differs")
    pins = value["producer_pins"]
    _need(type(pins) is dict and 0 < len(pins) <= 128, "bounded complete producer map required")
    for path, pin in pins.items():
        _need(Path(path).is_absolute(), "absolute producer path required")
        _sha(pin)
    _wire(value)
    return value


def prepare_relational_compact_example_v1(original_example_report, *, expected_original_example_sha256,
        original_replay_inputs, compact_codec, expected_compact_codec_sha256):
    """Retain the whole original example and append its exact compact companion."""
    original = dict(original_example_report=original_example_report, expected_original_example_sha256=expected_original_example_sha256,
        original_replay_inputs=original_replay_inputs, compact_codec=compact_codec, expected_compact_codec_sha256=expected_compact_codec_sha256)
    snapshot = _preflight(original)
    token = _fingerprint(snapshot)
    sources = {str(_SELF_PATH): _source_snapshot(_SELF_PATH)}
    _need(sources[str(_SELF_PATH)] == _SELF_SNAPSHOT, "companion source changed since import")
    def fence():
        _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token and
              _fingerprint(snapshot) == token, "original or detached companion inputs changed")
        _need(all(_source_snapshot(path) == expected for path, expected in sources.items()), "companion producer source changed")
    def adopt(pins):
        _need(type(pins) is dict and len(pins) <= 128, "bounded validated producer map required")
        for path, pin in pins.items():
            _need(type(path) is str and Path(path).is_absolute(), "absolute validated producer path required")
            _sha(pin)
            actual = _source_snapshot(path)
            _need(actual[0] == pin and (path not in sources or sources[path] == actual), "validated producer identity differs")
            sources[path] = actual
        _need(len(sources) <= 128, "complete producer union bound exceeded")
    with _guard(fence):
        example, compact = _owners()
        for owner in (example, compact):
            path = str(Path(owner.__file__).absolute())
            sources[path] = _source_snapshot(path)
        fence()
        checked = example.validate_relational_decoder_example_v1(snapshot["original_example_report"],
            expected_report_sha256=snapshot["expected_original_example_sha256"], **snapshot["original_replay_inputs"])
        fence()
        _need(_wire(checked) == _wire(snapshot["original_example_report"]), "original example replay differs")
        adopt(checked["producer_pins"])
        _need(compact.relational_compact_codec_sha256(snapshot["compact_codec"]) == snapshot["expected_compact_codec_sha256"],
              "fixed compact codec differs")
        fence()
        label = None
        if checked["label"] is not None:
            original_label = checked["label"]
            raw = original_label["request_raw_utf8"].encode("utf-8")
            options = dict(expected_request_sha256=original_label["request_raw_sha256"], codec=snapshot["compact_codec"],
                           expected_codec_sha256=snapshot["expected_compact_codec_sha256"])
            encoding = compact.encode_relational_compact_target_v1(raw, **options)
            fence()
            encoding_sha = compact.relational_compact_encoding_sha256(encoding)
            verified = compact.validate_relational_compact_encoding_v1(encoding, raw,
                expected_encoding_sha256=encoding_sha, **options)
            fence()
            _need(_wire(verified) == _wire(encoding), "compact encoding replay differs")
            byte = original_label["encoding"]
            for key in ("original_request", "canonical_request", "canonical_request_raw_utf8",
                        "relational_owner_report_sha256", "typed_expression_codec_sha256"):
                _need(_wire(encoding[key]) == _wire(byte[key]), "compact and original byte target identities differ")
            _need(encoding["owner_codec_sha256"] == checked["codec_sha256"] and
                  encoding["relational_owner_report_sha256"] == original_label["relational_report_sha256"],
                  "original codec/report identity differs")
            adopt(verified["producer_pins"])
            label = {"request_raw_sha256": original_label["request_raw_sha256"],
                "relational_report_sha256": original_label["relational_report_sha256"],
                "encoding": verified, "encoding_sha256": encoding_sha}
        replay = snapshot["original_replay_inputs"]
        result = {"schema": SCHEMA, "profile": PROFILE, "ir_family_id": "legal_ir", "task_id": TASK_ID,
            **{key: checked[key] for key in ("status", "model_input", "source_input_sha256", "source_group_sha256", "split")},
            "original_example": checked, "original_example_sha256": snapshot["expected_original_example_sha256"],
            "compact_label": label, "input_pins": {"original_example_sha256": snapshot["expected_original_example_sha256"],
                "original_example_request_sha256": replay["expected_example_request_sha256"],
                "join_report_sha256": replay["expected_join_report_sha256"], "original_codec_sha256": replay["expected_codec_sha256"],
                "compact_codec_sha256": snapshot["expected_compact_codec_sha256"],
                "original_replay_inputs_sha256": _fingerprint(replay)},
            "training_mask": 0, "evaluation_gold_mask": 0,
            "authority": {**checked["authority"], "provider_tokens_measured": False, "compact_checkpoint_qualified": False},
            "producer_pins": {path: identity[0] for path, identity in sources.items()}}
        return _report(result)


def relational_compact_example_sha256(report):
    """Hash a closed companion; full original-input replay remains required."""
    return _digest(_report(report))


def validate_relational_compact_example_v1(report, *args, expected_report_sha256, **kwargs):
    """Replay the original source example and compact label, then compare everything."""
    _sha(expected_report_sha256)
    supplied = _report(report)
    _need(_digest(supplied) == expected_report_sha256, "independent companion report pin differs")
    regenerated = prepare_relational_compact_example_v1(*args, **kwargs)
    _need(_wire(supplied) == _wire(regenerated), "compact companion differs from complete authoritative replay")
    return regenerated


__all__ = ["RelationalCompactExampleError", "prepare_relational_compact_example_v1",
           "relational_compact_example_sha256", "validate_relational_compact_example_v1"]
