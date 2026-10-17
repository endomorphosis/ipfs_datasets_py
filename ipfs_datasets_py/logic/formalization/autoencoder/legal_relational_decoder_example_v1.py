"""Candidate decoder examples with independently replayed source/label separation.

The model input is exactly the existing source/context request. Typed targets,
alternative declarations and embedding provenance remain outside that input.
This adapter creates neither reviewed meaning nor training/gold eligibility.
Public import is standard-library-only; original owners load after preflight.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

REQUEST_SCHEMA = "legal-relational-decoder-example-request/v1"
SCHEMA = "legal-relational-decoder-example/v1"
PROFILE = "candidate-source-separated-relational-byte-target/v1"
TASK_ID = "typed_relational_IR_reconstruction"
MAX_REQUEST_BYTES = 16 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_CODEC_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REPLAY_FIELDS = frozenset({
    "scope_report", "relational_report", "join_request_raw",
    "expected_join_request_sha256", "expected_scope_report_sha256",
    "expected_relational_report_sha256", "scope_replay_inputs",
    "relational_request_raw", "expected_relational_request_sha256",
})
_SCOPE_FIELDS = frozenset({
    "sampling_report", "raw_html", "scope_request_raw", "scope_declaration_raw",
    "expected_sampling_report_sha256", "selected_unit_ref",
    "expected_scope_request_sha256", "expected_scope_declaration_sha256",
    "descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes",
})
_EMBEDDING_FIELDS = frozenset({
    "dimension", "producer_id", "profile_id", "token_limit", "cache_key",
    "payload_bytes", "payload_sha256", "source_input_sha256",
})
AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_meaning_selected", "legal_roles_verified",
    "context_closure_verified", "dependency_inventory_exhaustive", "applicability_verified",
    "governing_use_verified", "independently_reviewed", "review_authenticated",
    "exposure_authenticated", "candidate_blind_target_verified", "accepted", "admitted",
    "semantic_graph_admitted", "training_qualified", "training_gold_qualified",
    "evaluation_gold_qualified", "teacher_qualified", "proof_authority", "Lean_admitted",
    "model_executed", "training_executed", "encoder_executed", "backend_executed",
    "embedding_payload_verified", "embedding_producer_verified",
    "embedding_source_independence_verified", "split_independence_verified",
), False)
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA256 = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()


class RelationalDecoderExampleError(ValueError):
    """An exact original input, candidate contract or bounded source differs."""


def _need(condition, message):
    if not condition:
        raise RelationalDecoderExampleError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == set(fields),
          "closed exact fields required: " + label)


def _copy(value, maximum, *, allow_bytes=False):
    """Detach ordinary inputs with byte/node/depth bounds before owner imports."""
    remaining, nodes = maximum, 2_000_000

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "ordinary input node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + len(item)
            _need(remaining >= 0 and len(item) <= nodes, "ordinary object bound exceeded")
            result = {}
            for key, child in item.items():
                _need(type(key) is str, "ordinary JSON string keys required")
                result[visit(key, depth + 1)] = visit(child, depth + 1)
            return result
        if type(item) is list:
            remaining -= 2 + len(item)
            _need(remaining >= 0 and len(item) <= nodes, "ordinary list bound exceeded")
            return [visit(child, depth + 1) for child in item]
        if type(item) is bytes and allow_bytes:
            remaining -= len(item)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded ordinary UTF8 required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise RelationalDecoderExampleError("ordinary UTF8 required") from error
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(abs(item) <= (1 << 63) - 1, "bounded ordinary integer required")
            remaining -= len(str(item))
        elif type(item) is float:
            _need(math.isfinite(item), "finite ordinary JSON required")
            remaining -= len(repr(item))
        else:
            raise RelationalDecoderExampleError("ordinary JSON/exact byte input required")
        _need(remaining >= 0, "complete input byte bound exceeded; truncation refused")
        return item

    return visit(value, 0)


def _wire(value, maximum=MAX_REPORT_BYTES):
    value = _copy(value, maximum)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise RelationalDecoderExampleError("bounded ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded; truncation refused")
    return raw


def _digest(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _fingerprint(value):
    digest = hashlib.sha256()

    def visit(item):
        if type(item) is dict:
            digest.update(b"d" + str(len(item)).encode() + b":")
            for key in sorted(item):
                visit(key)
                visit(item[key])
        elif type(item) is list:
            digest.update(b"l" + str(len(item)).encode() + b":")
            for child in item:
                visit(child)
        else:
            raw = item if type(item) is bytes else _wire(item, MAX_INPUT_BYTES)
            digest.update((b"b" if type(item) is bytes else b"j") + str(len(raw)).encode() + b":" + raw)

    visit(value)
    return digest.hexdigest()


def _raw(raw, maximum, label, expected=None):
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded exact bytes required: " + label)
    if expected is not None:
        _sha(expected, label)
        _need(hashlib.sha256(raw).hexdigest() == expected, "independent byte pin differs: " + label)


def _json(raw, expected):
    _raw(raw, MAX_REQUEST_BYTES, "example request", expected)

    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, "duplicate example request key")
            result[key] = value
        return result

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(RelationalDecoderExampleError("finite JSON required")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise RelationalDecoderExampleError("duplicate-free bounded example request required") from error
    _wire(result, MAX_REQUEST_BYTES)
    _keys(result, {"schema", "task_id", "exposure_status", "embedding_reference"}, "example request")
    _need(result["schema"] == REQUEST_SCHEMA and result["task_id"] == TASK_ID,
          "exact candidate example schema/task required")
    _need(type(result["exposure_status"]) is str and result["exposure_status"] in {"exposed", "unknown"},
          "caller-declared exposed or unknown status required; no blind claim")
    embedding = result["embedding_reference"]
    if embedding is not None:
        _keys(embedding, _EMBEDDING_FIELDS, "embedding reference")
        _need(type(embedding["dimension"]) is int and embedding["dimension"] in (8, 384, 768),
              "explicit supported embedding dimension required")
        for key in ("producer_id", "profile_id", "cache_key"):
            value = embedding[key]
            _need(type(value) is str and 0 < len(value) <= 512 and bool(value.strip())
                  and value.isprintable(), "bounded explicit embedding identity required: " + key)
        limit = embedding["token_limit"]
        _need(limit is None or type(limit) is int and 0 < limit <= (1 << 31) - 1,
              "unknown or positive declared token limit required")
        _need(type(embedding["payload_bytes"]) is int and 0 < embedding["payload_bytes"] <= (1 << 63) - 1,
              "positive declared embedding byte count required")
        for key in ("payload_sha256", "source_input_sha256"):
            _sha(embedding[key], "embedding " + key)
    return result


def _preflight(original):
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    request = _json(snapshot["example_request_raw"], snapshot["expected_example_request_sha256"])
    _sha(snapshot["expected_join_report_sha256"], "complete join report")
    _sha(snapshot["expected_codec_sha256"], "complete codec")
    _need(_digest(snapshot["join_report"]) == snapshot["expected_join_report_sha256"],
          "independent complete join report pin differs")
    _need(_digest(snapshot["codec"], MAX_CODEC_BYTES) == snapshot["expected_codec_sha256"],
          "independent codec pin differs")
    replay = snapshot["join_replay_inputs"]
    _keys(replay, _REPLAY_FIELDS, "join replay inputs")
    _wire(replay["scope_report"], 1024 * 1024)
    _sha(replay["expected_scope_report_sha256"], "scope report")
    _need(_digest(replay["scope_report"], 1024 * 1024) == replay["expected_scope_report_sha256"],
          "independent scope report pin differs")
    _raw(replay["join_request_raw"], 512 * 1024, "join request", replay["expected_join_request_sha256"])
    absent = tuple(replay[key] is None for key in ("relational_report", "relational_request_raw",
                   "expected_relational_report_sha256", "expected_relational_request_sha256"))
    _need(all(absent) or not any(absent), "relational inputs must all be present or null")
    if not any(absent):
        _sha(replay["expected_relational_report_sha256"], "relational report")
        _need(_digest(replay["relational_report"]) == replay["expected_relational_report_sha256"],
              "independent relational report pin differs")
        _raw(replay["relational_request_raw"], 512 * 1024, "relational request",
             replay["expected_relational_request_sha256"])
    scope = replay["scope_replay_inputs"]
    _need(type(scope) is dict and _SCOPE_FIELDS <= set(scope)
          and not (set(scope) - _SCOPE_FIELDS - {"view_limits", "limits"}),
          "closed complete scope replay inputs required")
    for key, maximum in (("sampling_report", 32 * 1024 * 1024), ("descriptor", 65536),
                         ("selected_unit_ref", 65536)):
        _wire(scope[key], maximum)
    for key in ("scope_request_raw", "scope_declaration_raw"):
        _raw(scope[key], 65536, key, scope["expected_" + key[:-4] + "_sha256"])
    _raw(scope["raw_html"], 8_000_000, "original raw HTML", scope["expected_raw_sha256"])
    _need(type(scope["expected_raw_bytes"]) is int and scope["expected_raw_bytes"] == len(scope["raw_html"]),
          "complete original HTML byte count differs")
    for key in ("expected_sampling_report_sha256", "expected_descriptor_sha256"):
        _sha(scope[key], key)
    for key in ("view_limits", "limits"):
        if key in scope:
            _wire(scope[key], 65536)
    return snapshot, request


def _owners():
    from ...autoformal import legal_source_typed_norm_join_v1 as join
    from . import legal_relational_target_codec_v1 as codec
    return join, codec


def _source_sha(path):
    path = Path(path).absolute()
    try:
        for parent in (path.parent, *path.parent.parents):
            _need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased trusted source parents required")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                  and 0 < before.st_size <= MAX_SOURCE_BYTES, "bounded regular trusted source required")
            raw = stream.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
              "trusted producer changed during read")
    except OSError as error:
        raise RelationalDecoderExampleError("trusted producer unavailable") from error
    return hashlib.sha256(raw).hexdigest()


def _owner_pins(owners):
    _need(_source_sha(_SELF_PATH) == _SELF_SHA256, "decoder example owner changed since import")
    result = {str(_SELF_PATH): _SELF_SHA256}
    for owner in owners:
        path = Path(owner.__file__).absolute()
        result[str(path)] = _source_sha(path)
    return result


def prepare_relational_decoder_example_v1(
    join_report, example_request_raw, *, expected_example_request_sha256,
    expected_join_report_sha256, join_replay_inputs, codec, expected_codec_sha256,
):
    """Replay original custody and retain a separated candidate byte-codec label.

    ``join_replay_inputs`` is the complete original preparation call by name.
    Embedding references are declarations, never payload or producer reads.
    Every independent commitment must originate outside this adapter.
    """
    original = dict(join_report=join_report, example_request_raw=example_request_raw,
        expected_example_request_sha256=expected_example_request_sha256,
        expected_join_report_sha256=expected_join_report_sha256, join_replay_inputs=join_replay_inputs,
        codec=codec, expected_codec_sha256=expected_codec_sha256)
    snapshot, request = _preflight(original)
    token = _fingerprint(snapshot)
    owners = _owners()
    join, target_codec = owners
    pins = _owner_pins(owners)

    def fence(extra=None):
        _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token,
              "original example inputs changed during preparation")
        _need(_fingerprint(snapshot) == token, "detached example inputs changed during preparation")
        _need(_owner_pins(owners) == pins, "trusted example owners changed during preparation")
        if extra is not None:
            for path, expected in extra.items():
                _need(_source_sha(path) == expected, "validated join producer changed during preparation")

    fence()
    replay = snapshot["join_replay_inputs"]
    checked = join.validate_source_typed_norm_join_v1(snapshot["join_report"],
        expected_report_sha256=snapshot["expected_join_report_sha256"], **replay)
    fence()
    _need(_wire(checked) == _wire(snapshot["join_report"]), "authoritative join replay differs")
    # Only the actual public owner's fully replayed map may nominate these reads.
    trusted_join_pins = _copy(checked["producer_pins"], 65536)
    _need(type(trusted_join_pins) is dict and len(trusted_join_pins) <= 128,
          "bounded authoritative join producer map required")
    for path, expected in trusted_join_pins.items():
        _need(type(path) is str and Path(path).is_absolute(), "absolute validated producer path required")
        _sha(expected, "validated join producer")
        _need(path not in pins or pins[path] == expected, "conflicting trusted join producer pin")
    fence(trusted_join_pins)
    expected_codec = target_codec.build_relational_target_codec_v1()
    fence(trusted_join_pins)
    _need(_wire(expected_codec, MAX_CODEC_BYTES) == _wire(snapshot["codec"], MAX_CODEC_BYTES)
          and target_codec.relational_target_codec_sha256(expected_codec) == snapshot["expected_codec_sha256"],
          "fixed target codec differs from independently retained codec")
    fence(trusted_join_pins)
    scope = checked["source_scope_report"]
    model_input = _copy(scope["scope_request"], 65536)
    _keys(model_input, {"source_text", "context"}, "source-only model input")
    source_input_sha256 = _digest(model_input, 65536)
    _need(source_input_sha256 == scope["input_pins"]["scope_request_canonical_sha256"],
          "verified source/context input identity differs")
    embedding = request["embedding_reference"]
    _need(embedding is None or embedding["source_input_sha256"] == source_input_sha256,
          "embedding declaration does not bind exact source/context input")
    occurrence = scope["source_records"]["source_occurrence"]
    source_identity = {
        "schema": "legal-relational-decoder-physical-source/v1",
        "raw_html_sha256": replay["scope_replay_inputs"]["expected_raw_sha256"],
        "raw_html_bytes": replay["scope_replay_inputs"]["expected_raw_bytes"],
        "source_version_cid": occurrence["source_version_cid"],
        "coordinate_system": occurrence["coordinate_system"],
        **{key: occurrence[key] for key in ("start_char", "end_char", "start_utf8", "end_utf8", "span_sha256")},
    }
    label = None
    trusted_output_pins = dict(trusted_join_pins)
    if replay["relational_request_raw"] is not None:
        encoding = target_codec.encode_relational_target_v1(replay["relational_request_raw"],
            expected_request_sha256=replay["expected_relational_request_sha256"],
            codec=snapshot["codec"], expected_codec_sha256=snapshot["expected_codec_sha256"])
        _need(encoding["relational_owner_report_sha256"] == replay["expected_relational_report_sha256"],
              "encoded label differs from the independently replayed relational report")
        encoding_pins = encoding["producer_pins"]
        _need(type(encoding_pins) is dict and len(encoding_pins) <= 128,
              "bounded authoritative encoding producer map required")
        for path, expected in encoding_pins.items():
            _need(type(path) is str and Path(path).is_absolute(), "absolute validated codec producer path required")
            _sha(expected, "validated codec producer")
            _need(path not in pins or pins[path] == expected, "conflicting direct codec producer pin")
            _need(path not in trusted_output_pins or trusted_output_pins[path] == expected,
                  "conflicting shared encoding producer pin")
            trusted_output_pins[path] = expected
        fence(trusted_output_pins)
        label = {"request_raw_utf8": replay["relational_request_raw"].decode("utf-8"),
                 "request_raw_sha256": replay["expected_relational_request_sha256"],
                 "relational_report_sha256": replay["expected_relational_report_sha256"],
                 "encoding": encoding}
    result = {
        "schema": SCHEMA, "profile": PROFILE, "ir_family_id": "legal_ir", "task_id": TASK_ID,
        "status": "candidate_target_prepared" if label is not None else "source_only_pending_target",
        "model_input": model_input, "source_input_sha256": source_input_sha256,
        "source_identity": source_identity, "source_group_sha256": _digest(source_identity, 65536),
        "label": label, "embedding_reference": embedding,
        "embedding_reference_declaration_only": True,
        "codec_sha256": snapshot["expected_codec_sha256"],
        "provenance": {
            "component_id": checked["component_id"], "alternative_id": checked["alternative_id"],
            "join_report_sha256": snapshot["expected_join_report_sha256"],
            "example_request_raw_sha256": snapshot["expected_example_request_sha256"],
            "selected_unit_ref": scope["input_pins"]["selected_unit_ref"],
            "scope_request_raw_sha256": scope["input_pins"]["scope_request_raw_sha256"],
            "scope_declaration_raw_sha256": scope["input_pins"]["scope_declaration_raw_sha256"],
            "original_unresolved": checked["original_unresolved"],
            "introduced_unresolved": checked["introduced_unresolved"],
            "source_context_packet": scope["source_context_packet"],
            "source_context_declaration": scope["source_records"]["context"],
            "provenance_ledger": checked["provenance_ledger"],
            "exposure_status": request["exposure_status"], "exposure_status_caller_declared": True,
            "declared_semantic_coverage": checked["declared_semantic_coverage"],
        },
        "split": "unassigned", "training_mask": 0, "evaluation_gold_mask": 0,
        "authority": dict(AUTHORITY), "producer_pins": {**trusted_output_pins, **pins},
        "limitations": [
            "The exact model input contains source/context only; labels, alternative declarations and embedding metadata are separate.",
            "A candidate byte target is not a reviewed meaning, semantic-action decoder or training-admission decision.",
            "Physical-source grouping does not authenticate a train/evaluation partition; related alternatives must not become independent examples.",
            "Embedding bytes, producer identity, token budget and source independence are caller declarations and have not been verified.",
            "Original unresolved meaning, context and introduced assumptions remain open; pending source has no manufactured target.",
            "The existing relational profile refuses unsupported operators; no richer source semantics or governing-use decision is inferred.",
        ],
    }
    _wire(result)
    fence(trusted_output_pins)
    return _copy(result, MAX_REPORT_BYTES)


def relational_decoder_example_sha256(report):
    """Commit the complete candidate envelope; this hash is not admission."""
    return _digest(report)


def validate_relational_decoder_example_v1(report, *args, expected_report_sha256, **kwargs):
    """Require independent output identity and complete original-input replay."""
    _sha(expected_report_sha256, "complete example report")
    supplied = _copy(report, MAX_REPORT_BYTES)
    _need(_digest(supplied) == expected_report_sha256, "independent example report pin differs")
    regenerated = prepare_relational_decoder_example_v1(*args, **kwargs)
    _need(_wire(supplied) == _wire(regenerated), "candidate example differs from complete authoritative replay")
    return regenerated


__all__ = ["prepare_relational_decoder_example_v1", "relational_decoder_example_sha256",
           "validate_relational_decoder_example_v1", "RelationalDecoderExampleError"]
