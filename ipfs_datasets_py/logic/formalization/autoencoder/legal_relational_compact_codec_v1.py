"""Lossless fixed JSON transport around the existing relational target owner.

No AST, semantic decoder, target-derived dictionary or model head is introduced.
Identifiers, array order and all admitted request fields survive reconstruction.
Source/context model inputs and external provenance remain their owners' concern.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

CODEC_SCHEMA = "legal-relational-compact-codec/v1"
PAYLOAD_SCHEMA = "legal-relational-compact-payload/v1"
ENCODING_SCHEMA = "legal-relational-compact-encoding/v1"
CANDIDATE_SCHEMA = "legal-relational-compact-candidate/v1"
PROFILE = "authored-object-relational-deontic/v1"
FORMAT = "fixed-json-relational-compact-utf8/v1"
PAD_ID, BOS_ID, EOS_ID, BYTE_OFFSET, VOCABULARY_SIZE = 0, 1, 2, 3, 259
MAX_REQUEST_BYTES = 524288
MAX_SEQUENCE_TOKENS = MAX_REQUEST_BYTES + 2
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_JSON_NODES, MAX_JSON_DEPTH = 100000, 96
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_KEYS = ("arguments", "binders", "kind", "metadata", "node_id", "schema_version",
    "symbol", "sort", "extension", "family", "profile", "features", "payload_schema",
    "payload", "children", "range", "expression_id", "content_digest", "interface",
    "signature", "signature_id", "sorts", "symbols", "domain", "name", "value",
    "version", "namespace", "source_binding", "interpretation_status", "expression",
    "argument_roles", "roles", "schema", "resolution")
_STRINGS = ("syntax-logic-node/v1", "syntax-logic-binder/v1", "syntax-logic-sort/v1",
    "syntax-symbol-declaration/v1", "syntax-logic-signature/v1", "syntax-typed-expression/v1",
    "logic-identity-namespaces/v1", "LogicIdentityNamespaces@1", "TypedExpression@1",
    "LogicSignature@1", "legal-relational-norm-request/v1", "authored_unreviewed_declaration",
    "legacy.deontic/v1", "syntax-logic-extension-node/v1")
_AUTHORITY_NAMES = ("source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "independently_reviewed", "accepted",
    "admitted", "semantic_graph_admitted", "training_qualified", "training_gold_qualified",
    "evaluation_gold_qualified", "teacher_qualified", "model_execution_verified", "model_executed",
    "training_executed", "backend_executed", "Lean_admitted", "proof_authority",
    "semantic_action_language", "grammar_constrained_generation", "provider_tokens_measured")
_SELF_PATH = Path(__file__).absolute()


class LegalRelationalCompactCodecError(ValueError):
    """The complete transport, fixed projection or original owner refused input."""


class _CompleteBoundExceeded(LegalRelationalCompactCodecError):
    """Whole-input refusal, never a truncated or classified model outcome."""


def _need(ok, message):
    if not ok:
        raise LegalRelationalCompactCodecError(message)


def _bound(ok, message):
    if not ok:
        raise _CompleteBoundExceeded(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value, maximum=MAX_REQUEST_BYTES, *, sequence=False):
    stack, remaining = [(value, 0)], MAX_JSON_NODES + (MAX_SEQUENCE_TOKENS if sequence else 0)
    while stack:
        item, depth = stack.pop()
        remaining -= 1
        _bound(remaining >= 0 and depth <= MAX_JSON_DEPTH, "complete JSON node/depth bound exceeded")
        if type(item) is dict:
            _bound(len(item) <= MAX_JSON_NODES, "complete JSON object bound exceeded")
            _need(all(type(k) is str for k in item), "plain string keys required")
            stack.extend((v, depth + 1) for pair in item.items() for v in pair)
        elif type(item) is list:
            _bound(len(item) <= MAX_SEQUENCE_TOKENS, "complete JSON list bound exceeded")
            stack.extend((v, depth + 1) for v in item)
        else:
            _need(item is None or type(item) in (bool, int, str), "ordinary finite JSON required")
            if type(item) is int:
                _bound(-(1 << 63) < item < (1 << 63), "bounded plain integer required")
            if type(item) is str:
                _bound(len(item) <= maximum, "complete string bound exceeded")
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise LegalRelationalCompactCodecError("canonical UTF8 JSON required") from None
    _bound(0 < len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, "duplicate JSON key refused")
        result[key] = value
    return result


def _parse(raw):
    _need(type(raw) is bytes and bool(raw), "nonempty UTF8 JSON bytes required")
    _bound(len(raw) <= MAX_REQUEST_BYTES, "complete request byte bound exceeded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except RecursionError:
        raise _CompleteBoundExceeded("complete JSON depth bound exceeded") from None
    except (ValueError, UnicodeError):
        raise LegalRelationalCompactCodecError("duplicate-free UTF8 JSON required") from None
    _wire(value)
    return value


def _snapshot():
    try:
        _need(all(stat.S_ISDIR(p.lstat().st_mode) for p in _SELF_PATH.parents), "direct source parents required")
        fd = os.open(_SELF_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                  0 < before.st_size <= MAX_REQUEST_BYTES, "bounded regular codec source required")
            raw = bytearray()
            while len(raw) <= MAX_REQUEST_BYTES:
                part = os.read(fd, min(65536, MAX_REQUEST_BYTES + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
            witness = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            _need(len(raw) == before.st_size and witness(before) == witness(os.fstat(fd)) ==
                  witness(_SELF_PATH.lstat()), "codec source changed during snapshot")
            return _sha(raw), witness(before)
        finally:
            os.close(fd)
    except OSError:
        raise LegalRelationalCompactCodecError("codec source snapshot refused") from None


_SELF_SNAPSHOT = _snapshot()


def _fence():
    _need(_snapshot() == _SELF_SNAPSHOT, "compact codec source changed since import")


def build_relational_compact_codec_v1():
    """Return fixed target-independent tables; no operation owner is imported."""
    _fence()
    containers = [{"arguments": [], "kind": kind, "name": name, "schema_version": "syntax-logic-sort/v1"}
                  for kind, name in (("bool", "Bool"), ("atomic", "Object"))]
    containers += [{"interface": "LogicIdentityNamespaces@1", "namespace": ns,
        "schema_version": "logic-identity-namespaces/v1", "value": value, "version": "1.0.0"}
        for ns, value in (("family", "tdfol"), ("profile", "tdfol_default"))]
    return {"schema": CODEC_SCHEMA, "profile": PROFILE, "format": FORMAT,
        "ir_family": "legal_ir", "decoder_task": "typed_relational_IR_reconstruction",
        "owner_codec_schema": "legal-relational-target-codec/v1", "payload_schema": PAYLOAD_SCHEMA,
        "key_map": dict(zip(_KEYS, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")),
        "string_constants": list(_STRINGS), "container_constants": containers,
        "key_escape": ":", "string_marker": "@", "container_marker": "!",
        "vocabulary": ["PAD", "BOS", "EOS", *("BYTE_%02X" % i for i in range(256))],
        "vocabulary_size": VOCABULARY_SIZE, "pad_id": PAD_ID, "bos_id": BOS_ID,
        "eos_id": EOS_ID, "byte_offset": BYTE_OFFSET, "preserve_array_order": True,
        "semantic_action_language": False, "grammar_constrained_generation": False}


def relational_compact_codec_sha256(codec):
    raw = _wire(codec, 32768)
    _need(raw == _wire(build_relational_compact_codec_v1(), 32768), "exact fixed compact codec required")
    return _sha(raw)


def _codec(codec, expected):
    _need(type(expected) is str and _SHA.fullmatch(expected) is not None and
          relational_compact_codec_sha256(codec) == expected, "independent compact codec SHA256 differs")
    return json.loads(_wire(codec, 32768))


def _project(value, codec):
    if type(value) is dict:
        for index, constant in enumerate(codec["container_constants"]):
            if value == constant:
                return {"!": index}
        return {codec["key_map"].get(k, ":" + k): _project(v, codec) for k, v in value.items()}
    if type(value) is list:
        return [_project(v, codec) for v in value]
    if type(value) is str and value in codec["string_constants"]:
        return {"@": codec["string_constants"].index(value)}
    return value


def _expand(value, codec):
    reverse = {v: k for k, v in codec["key_map"].items()}
    budget = [MAX_JSON_NODES, MAX_REQUEST_BYTES]
    def visit(item, depth=0, literal=False):
        budget[0] -= 1
        _bound(budget[0] >= 0 and depth <= MAX_JSON_DEPTH, "complete reconstruction bound exceeded")
        if type(item) is dict:
            if not literal and ("@" in item or "!" in item):
                _need(len(item) == 1, "closed compact marker required")
                marker = next(iter(item)); index = item[marker]
                table = codec["string_constants" if marker == "@" else "container_constants"]
                _need(type(index) is int and 0 <= index < len(table), "fixed marker index required")
                return visit(table[index], depth, literal=True)
            result = {}
            for key, child in item.items():
                if literal:
                    original = key
                else:
                    _need(key in reverse or key.startswith(":"), "unknown compact key")
                    original = reverse[key] if key in reverse else key[1:]
                    _need(key in reverse or original not in codec["key_map"], "noncanonical escaped key")
                _need(original not in result, "duplicate expanded key")
                budget[1] -= len(original.encode("utf-8"))
                result[original] = visit(child, depth + 1, literal)
            return result
        if type(item) is list:
            return [visit(child, depth + 1, literal) for child in item]
        if type(item) is str:
            budget[1] -= len(item.encode("utf-8"))
        _bound(budget[1] >= 0, "complete reconstruction string bound exceeded")
        return item
    expanded = visit(value)
    _wire(expanded)
    _need(_project(expanded, codec) == value, "noncanonical compact projection")
    return expanded


def _flags():
    return {"authority": dict.fromkeys(_AUTHORITY_NAMES, False), "training_mask": 0, "evaluation_gold_mask": 0}


def _binding(raw):
    return {"bytes": len(raw), "sha256": _sha(raw)}


def _base():
    from . import legal_relational_target_codec_v1 as owner
    _need(Path(owner.__file__).absolute() == _SELF_PATH.with_name("legal_relational_target_codec_v1.py"),
          "sibling original relational target owner required")
    codec = owner.build_relational_target_codec_v1()
    return owner, codec, owner.relational_target_codec_sha256(codec)


def encode_relational_compact_target_v1(request_raw, *, expected_request_sha256, codec, expected_codec_sha256):
    """Validate the original request, then replace fixed serialization boilerplate."""
    fixed = _codec(codec, expected_codec_sha256)
    _parse(request_raw)
    _need(type(expected_request_sha256) is str and _SHA.fullmatch(expected_request_sha256) is not None and
          _sha(request_raw) == expected_request_sha256, "independent original request SHA256 differs")
    try:
        owner, base_codec, base_sha = _base()
        original = owner.encode_relational_target_v1(request_raw, expected_request_sha256=expected_request_sha256,
            codec=base_codec, expected_codec_sha256=base_sha)
        canonical = original["canonical_request_raw_utf8"].encode("utf-8")
        request = _parse(canonical)
        compact = _wire({"schema": PAYLOAD_SCHEMA, "request": _project(request, fixed)})
        _need(_wire(_expand(_parse(compact)["request"], fixed)) == canonical, "exact reconstruction differs")
        return {"schema": ENCODING_SCHEMA, "profile": PROFILE, "format": FORMAT,
            "codec_sha256": expected_codec_sha256, "owner_codec_sha256": base_sha,
            "original_request": original["original_request"], "canonical_request": _binding(canonical),
            "canonical_request_raw_utf8": canonical.decode("utf-8"), "compact_request": _binding(compact),
            "compact_request_raw_utf8": compact.decode("utf-8"),
            "target_ids": [BOS_ID, *(BYTE_OFFSET + x for x in compact), EOS_ID],
            "relational_owner_report_sha256": original["relational_owner_report_sha256"],
            "typed_expression_codec_sha256": original["typed_expression_codec_sha256"],
            "producer_pins": {**original["producer_pins"], str(_SELF_PATH): _SELF_SNAPSHOT[0]}, **_flags()}
    finally:
        _fence()


def _encoding(report):
    raw = _wire(report, MAX_REPORT_BYTES, sequence=True)
    value = json.loads(raw)
    fields = {"schema", "profile", "format", "codec_sha256", "owner_codec_sha256", "original_request",
        "canonical_request", "canonical_request_raw_utf8", "compact_request", "compact_request_raw_utf8",
        "target_ids", "relational_owner_report_sha256", "typed_expression_codec_sha256", "producer_pins", *_flags()}
    _need(type(value) is dict and set(value) == fields and value["schema"] == ENCODING_SCHEMA and
          value["profile"] == PROFILE and value["format"] == FORMAT, "closed compact encoding required")
    _need(all(type(value[k]) is type(v) and value[k] == v for k, v in _flags().items()) and
          all(v is False for v in value["authority"].values()), "candidate-only flags required")
    for key in ("codec_sha256", "owner_codec_sha256", "relational_owner_report_sha256", "typed_expression_codec_sha256"):
        _need(type(value[key]) is str and _SHA.fullmatch(value[key]) is not None, "complete encoding SHA256 required")
    fixed = _codec(build_relational_compact_codec_v1(), value["codec_sha256"])
    for key in ("canonical_request", "compact_request"):
        _need(type(value[key + "_raw_utf8"]) is str, "exact encoding UTF8 required")
        encoded = value[key + "_raw_utf8"].encode("utf-8")
        binding = value[key]
        _need(type(binding) is dict and set(binding) == {"bytes", "sha256"} and type(binding["bytes"]) is int and
              binding == _binding(encoded) and _wire(_parse(encoded)) == encoded, "canonical encoding binding differs")
    original = value["original_request"]
    _need(type(original) is dict and set(original) == {"bytes", "sha256"} and type(original["bytes"]) is int and
          0 < original["bytes"] <= MAX_REQUEST_BYTES and type(original["sha256"]) is str and
          _SHA.fullmatch(original["sha256"]) is not None, "original request binding required")
    compact = value["compact_request_raw_utf8"].encode("utf-8")
    payload = _parse(compact)
    _need(type(payload) is dict and set(payload) == {"schema", "request"} and payload["schema"] == PAYLOAD_SCHEMA,
          "closed compact payload required")
    _need(_wire(_expand(payload["request"], fixed)).decode("utf-8") == value["canonical_request_raw_utf8"],
          "full reconstructed request differs")
    _need(type(value["target_ids"]) is list and all(type(x) is int for x in value["target_ids"]) and
          value["target_ids"] == [BOS_ID, *(BYTE_OFFSET + x for x in compact), EOS_ID], "compact byte target differs")
    pins = value["producer_pins"]
    _need(type(pins) is dict and 0 < len(pins) <= 128 and all(Path(p).is_absolute() and type(s) is str and
          _SHA.fullmatch(s) is not None for p, s in pins.items()), "bounded source pins required")
    return value


def relational_compact_encoding_sha256(report):
    return _sha(_wire(_encoding(report), MAX_REPORT_BYTES, sequence=True))


def validate_relational_compact_encoding_v1(report, request_raw, *, expected_encoding_sha256,
        expected_request_sha256, codec, expected_codec_sha256):
    _need(type(expected_encoding_sha256) is str and _SHA.fullmatch(expected_encoding_sha256) is not None,
          "independent complete encoding SHA256 required")
    offered = _encoding(report)
    _need(relational_compact_encoding_sha256(offered) == expected_encoding_sha256, "complete encoding pin differs")
    regenerated = encode_relational_compact_target_v1(request_raw, expected_request_sha256=expected_request_sha256,
        codec=codec, expected_codec_sha256=expected_codec_sha256)
    _need(_wire(offered, MAX_REPORT_BYTES, sequence=True) == _wire(regenerated, MAX_REPORT_BYTES, sequence=True),
          "compact encoding differs from original-bound replay")
    return regenerated


def decode_relational_compact_candidate_v1(generated_ids, *, codec, expected_codec_sha256):
    """Reference-free generated intake; no target repair, implicit EOS or truncation."""
    fixed = _codec(codec, expected_codec_sha256)
    _need(type(generated_ids) is list, "plain generated ID list required")
    _bound(len(generated_ids) <= MAX_SEQUENCE_TOKENS, "complete generated sequence bound exceeded")
    _need(all(type(x) is int and -(1 << 31) <= x < (1 << 31) for x in generated_ids), "plain bounded IDs required")
    ids = list(generated_ids)
    valid, bos, eos, terminal = all(0 <= x < VOCABULARY_SIZE for x in ids), bool(ids) and ids[0] == BOS_ID, EOS_ID in ids, bool(ids) and ids[-1] == EOS_ID
    middle = ids[1:-1] if bos and terminal else ids[1:] if bos else ids
    special = any(0 <= x < BYTE_OFFSET for x in middle)
    frame = valid and bos and not special
    report = {"schema": CANDIDATE_SCHEMA, "profile": PROFILE, "format": FORMAT, "codec_sha256": expected_codec_sha256,
        "status": "rejected", "reason": "invalid_frame", "generated_ids": ids,
        **dict.fromkeys(("generated_transport_utf8", "generated_transport_hex", "generated_transport_sha256",
        "generated_transport_bytes", "canonical_request_raw_utf8", "canonical_request_sha256", "canonical_request_bytes",
        "relational_owner_report_sha256", "typed_expression_codec_sha256", "owner_codec_sha256")),
        "framing": {"bos_present": bos, "eos_present": eos, "eos_terminal": terminal, "token_ids_valid": valid,
                    "interior_special_tokens": special, "terminated": bool(frame and terminal)},
        "producer_pins": {str(_SELF_PATH): _SELF_SNAPSHOT[0]}, **_flags()}
    try:
        if not ids:
            report.update(status="incomplete", reason="missing_bos_and_eos")
        elif frame:
            raw = bytes(x - BYTE_OFFSET for x in middle)
            _bound(len(raw) <= MAX_REQUEST_BYTES, "complete generated byte bound exceeded")
            report.update(generated_transport_hex=raw.hex(), generated_transport_sha256=_sha(raw), generated_transport_bytes=len(raw))
            try:
                report["generated_transport_utf8"] = raw.decode("utf-8")
            except UnicodeError:
                pass
            if not terminal:
                report.update(status="incomplete", reason="missing_eos")
            elif report["generated_transport_utf8"] is None:
                report["reason"] = "invalid_utf8"
            else:
                try:
                    payload = _parse(raw)
                    report["reason"] = "compact_projection_rejected"
                    _need(type(payload) is dict and set(payload) == {"schema", "request"} and
                          payload["schema"] == PAYLOAD_SCHEMA, "closed compact payload required")
                    canonical = _wire(_expand(payload["request"], fixed))
                except _CompleteBoundExceeded:
                    raise
                except ValueError:
                    if report["reason"] == "invalid_frame":
                        report["reason"] = "compact_json_rejected"
                else:
                    owner, base_codec, base_sha = _base()
                    checked = owner.decode_relational_candidate_v1([BOS_ID, *(BYTE_OFFSET + x for x in canonical), EOS_ID],
                        codec=base_codec, expected_codec_sha256=base_sha)
                    report.update(owner_codec_sha256=base_sha, producer_pins={**checked["producer_pins"], **report["producer_pins"]})
                    report["reason"] = "typed_request_rejected"
                    if checked["status"] == "valid_candidate":
                        _need(checked["canonical_request_raw_utf8"].encode("utf-8") == canonical, "owner reconstruction differs")
                        report.update(status="valid_candidate", reason=None)
                        for key in ("canonical_request_raw_utf8", "canonical_request_sha256", "canonical_request_bytes",
                                    "relational_owner_report_sha256", "typed_expression_codec_sha256"):
                            report[key] = checked[key]
        return json.loads(_wire(report, MAX_REPORT_BYTES, sequence=True))
    finally:
        _fence()


__all__ = ["LegalRelationalCompactCodecError", "build_relational_compact_codec_v1",
    "relational_compact_codec_sha256", "encode_relational_compact_target_v1",
    "decode_relational_compact_candidate_v1", "relational_compact_encoding_sha256",
    "validate_relational_compact_encoding_v1"]
