"""Fixed-byte serialization of the existing authored relational request.

This is a model-free training-interface building block, not a semantic action
language, grammar-constrained decoder, source translator or training admission.
Original transports and canonical UTF8 targets have separate hash namespaces.
Public imports are stdlib only; supported typed/native owners load lazily.
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
import threading

CODEC_SCHEMA = "legal-relational-target-codec/v1"
ENCODING_SCHEMA = "legal-relational-target-encoding/v1"
CANDIDATE_SCHEMA = "legal-relational-candidate-decoding/v1"
PROFILE = "authored-object-relational-deontic/v1"
FORMAT = "canonical-relational-request-utf8/v1"
IR_FAMILY = "legal_ir"
DECODER_TASK = "typed_relational_IR_reconstruction"
PAD_ID, BOS_ID, EOS_ID, BYTE_OFFSET, BYTE_COUNT = 0, 1, 2, 3, 256
VOCABULARY_SIZE = BYTE_OFFSET + BYTE_COUNT
MAX_REQUEST_BYTES = 524288
MAX_SEQUENCE_TOKENS = MAX_REQUEST_BYTES + 2
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_CODEC_BYTES = 32768
MAX_JSON_NODES = 100000
MAX_JSON_DEPTH = 96
_SHA = re.compile(r"[0-9a-f]{64}\Z")
FALSE_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "independently_reviewed",
    "accepted", "admitted", "semantic_graph_admitted", "training_qualified",
    "training_gold_qualified", "evaluation_gold_qualified", "teacher_qualified",
    "model_execution_verified", "model_executed", "training_executed",
    "backend_executed", "Lean_admitted", "proof_authority",
    "semantic_action_language", "grammar_constrained_generation",
), False)
_IDENTITY_FIELDS = {"profile", "ir_family", "decoder_task", "format"}
_ENCODING_FIELDS = {"schema", *_IDENTITY_FIELDS, "codec_sha256", "original_request",
    "canonical_request", "canonical_request_raw_utf8", "target_ids",
    "relational_owner_report_sha256", "typed_expression_codec_sha256",
    "producer_pins", "authority", "training_mask", "evaluation_gold_mask"}
_SELF_PATH = Path(__file__).absolute()
_REPO = _SELF_PATH.parents[4]
# The fixed public relational producer closure plus the actual typed codec
# and elaboration owners. This is not an installed-package import census.
_SOURCE_RELS = (
    "ipfs_datasets_py/logic/autoformal/legal_relational_norm_v1.py",
    "ipfs_datasets_py/logic/syntax_core/codec.py",
    "ipfs_datasets_py/logic/syntax_core/ast.py",
    "ipfs_datasets_py/logic/syntax_core/contracts.py",
    "ipfs_datasets_py/logic/syntax_core/signatures.py",
    "ipfs_datasets_py/logic/syntax_core/elaboration.py",
    "ipfs_datasets_py/logic/syntax_core/algebra.py",
    "ipfs_datasets_py/logic/families/namespaces.py",
    "ipfs_datasets_py/logic/parsers/legacy_modal.py",
    "ipfs_datasets_py/logic/TDFOL/tdfol_core.py",
    "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py",
    "ipfs_datasets_py/logic/intent_ir/formalize/modal_projections.py",
    "ipfs_datasets_py/logic/autoformal/legal_family_routes.py",
    "ipfs_datasets_py/logic/autoformal/family_qualification.py",
    "ipfs_datasets_py/logic/autoformal/legal_canonical_calendar.py",
    "ipfs_datasets_py/logic/autoformal/legal_canonical_qualified.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/native_family_lean_emitters.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/native_legal_qualified_lean.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/native_qualified_lean.py",
    "ipfs_datasets_py/logic/ir_core/provenance.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
    "ipfs_datasets_py/logic/CEC/native/dcec_integration.py",
    "ipfs_datasets_py/logic/CEC/native/dcec_core.py",
    "ipfs_datasets_py/logic/CEC/native/dcec_parsing.py",
    "ipfs_datasets_py/logic/CEC/native/dcec_cleaning.py",
    "ipfs_datasets_py/logic/CEC/native/dcec_prototypes.py",
)
_SOURCE_BASELINE = None
_BUSY_LOCK = threading.Lock()
_BUSY = False


class LegalRelationalTargetCodecError(ValueError):
    """A complete bound, original pin, source fence or codec contract failed."""


class _CompleteBoundExceeded(LegalRelationalTargetCodecError):
    """Whole input overflow is refusal, never a classified model outcome."""


def _need(condition, message):
    if not condition:
        raise LegalRelationalTargetCodecError(message)


def _bound(condition, message):
    if not condition:
        raise _CompleteBoundExceeded(message)


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _copy(value, maximum, *, sequence_report=False):
    """Detach only bounded plain JSON without invoking offered serializers."""
    remaining = MAX_JSON_NODES + (MAX_SEQUENCE_TOKENS if sequence_report else 0)
    stack = [(value, 0)]
    try:
        while stack:
            current, depth = stack.pop()
            remaining -= 1
            _bound(remaining >= 0 and depth <= MAX_JSON_DEPTH, "complete JSON node/depth bound exceeded")
            if type(current) is dict:
                _need(all(type(k) is str for k in current), "plain JSON string keys required")
                stack.extend((child, depth + 1) for child in current.values())
            elif type(current) is list:
                _bound(len(current) <= MAX_SEQUENCE_TOKENS, "complete JSON collection bound exceeded")
                stack.extend((child, depth + 1) for child in current)
            else:
                _need(current is None or type(current) in (bool, str, int, float), "plain JSON values required")
                if type(current) is int:
                    _bound(current.bit_length() <= 64, "bounded JSON integer required")
                if type(current) is float:
                    _need(math.isfinite(current), "finite JSON values required")
        raw = _wire(value, maximum)
        return json.loads(raw)
    except (RuntimeError, TypeError, RecursionError, UnicodeError, OverflowError):
        raise LegalRelationalTargetCodecError("bounded stable plain JSON required") from None


def _wire(value, maximum):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError, OverflowError):
        raise LegalRelationalTargetCodecError("finite canonical UTF8 JSON required") from None
    _bound(0 < len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _pairs(items):
    value = {}
    for key, child in items:
        _need(key not in value, "duplicate JSON field refused")
        value[key] = child
    return value


def _request(raw, expected):
    _need(type(raw) is bytes and len(raw) > 0, "nonempty original request bytes required")
    _bound(len(raw) <= MAX_REQUEST_BYTES, "complete original request byte bound exceeded")
    _need(_sha(expected) and hashlib.sha256(raw).hexdigest() == expected, "original request transport SHA256 differs")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(LegalRelationalTargetCodecError("finite request JSON required")))
    except RecursionError:
        raise _CompleteBoundExceeded("complete request JSON depth bound exceeded") from None
    except (ValueError, UnicodeError):
        raise LegalRelationalTargetCodecError("duplicate-free finite original UTF8 request required") from None
    detached = _copy(value, MAX_REQUEST_BYTES)
    _need(type(detached) is dict and set(detached) == {
        "schema", "interpretation_status", "expression", "argument_roles", "source_binding"}
        and detached["schema"] == "legal-relational-norm-request/v1"
        and detached["interpretation_status"] == "authored_unreviewed_declaration"
        and detached["source_binding"] is None and type(detached["expression"]) is dict
        and type(detached["argument_roles"]) is list, "closed authored relational request required")
    return detached


def _identity():
    return {"profile": PROFILE, "ir_family": IR_FAMILY,
            "decoder_task": DECODER_TASK, "format": FORMAT}


def build_relational_target_codec_v1():
    """Return the same fresh closed259-symbol codec for every target/dimension."""
    _need(_snapshot(_SELF_PATH) == _SELF_SNAPSHOT, "codec owner changed since import")
    return {"schema": CODEC_SCHEMA, **_identity(), "typed_codec_interface": "TypedLogicCodec@1",
        "request_schema": "legal-relational-norm-request/v1",
        "vocabulary": ["PAD", "BOS", "EOS", *("BYTE_%02X" % i for i in range(BYTE_COUNT))],
        "vocabulary_size": VOCABULARY_SIZE, "pad_id": PAD_ID, "bos_id": BOS_ID, "eos_id": EOS_ID,
        "byte_offset": BYTE_OFFSET, "byte_count": BYTE_COUNT,
        "serialization": {"encoding": "utf-8", "sort_object_keys": True,
            "ensure_ascii": False, "separators": [",", ":"], "preserve_array_order": True},
        "source_binding": "unsupported_in_authored_profile",
        "semantic_action_language": False, "grammar_constrained_generation": False}


def relational_target_codec_sha256(codec):
    """Validate the exact fixed codec and hash its complete canonical bytes."""
    detached = _copy(codec, MAX_CODEC_BYTES)
    _need(type(detached) is dict and _wire(detached, MAX_CODEC_BYTES) ==
          _wire(build_relational_target_codec_v1(), MAX_CODEC_BYTES),
          "exact fixed target-independent codec required")
    return hashlib.sha256(_wire(detached, MAX_CODEC_BYTES)).hexdigest()


def _codec(codec, expected):
    _need(_sha(expected), "independent complete codec SHA256 required")
    detached = _copy(codec, MAX_CODEC_BYTES)
    _need(relational_target_codec_sha256(detached) == expected, "independent complete codec pin differs")
    return detached


def _snapshot(path):
    try:
        _need(path.is_absolute() and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents),
              "direct trusted source parents required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                  and 0 < before.st_size <= MAX_SOURCE_BYTES, "bounded regular trusted source required")
            raw = bytearray()
            while len(raw) <= MAX_SOURCE_BYTES:
                block = os.read(fd, min(65536, MAX_SOURCE_BYTES + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            witness = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size,
                                 s.st_mtime_ns, s.st_ctime_ns)
            _need(len(raw) == before.st_size and witness(before) == witness(os.fstat(fd)) == witness(path.lstat()),
                  "trusted source changed during snapshot")
            return hashlib.sha256(raw).hexdigest(), witness(before)
        finally:
            os.close(fd)
    except OSError:
        raise LegalRelationalTargetCodecError("trusted source snapshot refused") from None


_SELF_SNAPSHOT = _snapshot(_SELF_PATH)


def _sources():
    global _SOURCE_BASELINE
    snapshots = {str(p): _snapshot(p) for p in (_SELF_PATH, *(_REPO / r for r in _SOURCE_RELS))}
    _need(snapshots[str(_SELF_PATH)] == _SELF_SNAPSHOT, "codec owner changed since import")
    if _SOURCE_BASELINE is None:
        _SOURCE_BASELINE = dict(snapshots)
    _need(snapshots == _SOURCE_BASELINE, "trusted source bytes/identity changed since first use")
    return {p: s[0] for p, s in snapshots.items()}, snapshots


@contextmanager
def _operation():
    global _BUSY
    with _BUSY_LOCK:
        _need(not _BUSY, "concurrent or reentrant target-codec operation refused")
        _BUSY = True
    try:
        yield
    finally:
        with _BUSY_LOCK:
            _BUSY = False


def _owners():
    from ...autoformal import legal_relational_norm_v1 as relational
    from ...syntax_core import codec as typed_codec
    for module, relative in ((relational, _SOURCE_RELS[0]), (typed_codec, _SOURCE_RELS[1])):
        _need(type(module.__file__) is str and Path(module.__file__).absolute() == _REPO / relative,
              "original fixed public owner origin required")
    _need(typed_codec.TYPED_LOGIC_CODEC_INTERFACE == "TypedLogicCodec@1", "exact typed codec interface required")
    return relational, typed_codec


def _inspect(raw, expected, owners, fence):
    relational, typed_codec = owners
    request = _request(raw, expected)
    fence()
    report = relational.prepare_relational_norm_v1(raw, expected_request_sha256=expected)
    fence()
    report = _copy(report, MAX_REPORT_BYTES)
    report_sha = relational.relational_norm_report_sha256(report)
    fence()
    replayed = relational.validate_relational_norm_v1(report, raw,
        expected_request_sha256=expected, expected_report_sha256=report_sha)
    fence()
    _need(_wire(replayed, MAX_REPORT_BYTES) == _wire(report, MAX_REPORT_BYTES)
          and report["request"] == request, "public relational owner replay differs")
    pins, _ = _sources()
    _need(type(report["producer_pins"]) is dict and report["producer_pins"].items() <= pins.items(),
          "fixed relational producer closure differs")
    # Use the public typed codec, including its strict digest/version gate.
    typed = typed_codec.TypedLogicCodec(strict_digests=True, extension_registry=None, metadata={})
    expression = typed.decode({"kind": "typed_expression",
        "schema_version": report["typed_expression"]["schema_version"],
        "payload": report["typed_expression"]})
    fence()
    envelope = typed.encode(expression)
    fence()
    roundtrip = typed.decode(envelope)
    fence()
    _need(expression.to_dict() == roundtrip.to_dict() == report["typed_expression"] == request["expression"],
          "full typed expression serialization changed IDs/order/signature")
    envelope_sha = hashlib.sha256(_wire(envelope.to_dict(), MAX_REPORT_BYTES)).hexdigest()
    return request, report_sha, envelope_sha


def _flags():
    return {"authority": dict(FALSE_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0}


def _encoding_shape(report):
    detached = _copy(report, MAX_REPORT_BYTES, sequence_report=True)
    _need(type(detached) is dict and set(detached) == _ENCODING_FIELDS
          and detached["schema"] == ENCODING_SCHEMA
          and all(detached[k] == v for k, v in _identity().items())
          and type(detached["authority"]) is dict and set(detached["authority"]) == set(FALSE_AUTHORITY)
          and all(x is False for x in detached["authority"].values())
          and type(detached["training_mask"]) is int and detached["training_mask"] == 0
          and type(detached["evaluation_gold_mask"]) is int and detached["evaluation_gold_mask"] == 0,
          "closed candidate-only encoding report required")
    for key in ("codec_sha256", "relational_owner_report_sha256", "typed_expression_codec_sha256"):
        _need(_sha(detached[key]), "complete encoding SHA256 required")
    for key in ("original_request", "canonical_request"):
        row = detached[key]
        _need(type(row) is dict and set(row) == {"bytes", "sha256"}
              and type(row["bytes"]) is int and 0 < row["bytes"] <= MAX_REQUEST_BYTES
              and _sha(row["sha256"]), "closed original/canonical request binding required")
    text = detached["canonical_request_raw_utf8"]
    _need(type(text) is str, "canonical request UTF8 required")
    raw = text.encode("utf-8")
    _need(detached["canonical_request"] == {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
          and detached["target_ids"] == [BOS_ID, *(BYTE_OFFSET + x for x in raw), EOS_ID]
          and all(type(x) is int for x in detached["target_ids"]), "fixed byte target or canonical binding differs")
    pins = detached["producer_pins"]
    _need(type(pins) is dict and 0 < len(pins) <= 128
          and all(type(p) is str and Path(p).is_absolute() and _sha(s) for p, s in pins.items()),
          "bounded producer pin declarations required")
    return detached


def encode_relational_target_v1(request_raw, *, expected_request_sha256, codec, expected_codec_sha256):
    """Encode a complete unreviewed request; derive no statutory target or label."""
    detached_codec = _codec(codec, expected_codec_sha256)
    _request(request_raw, expected_request_sha256)
    with _operation():
        initial_pins, initial_snapshots = _sources()
        def fence():
            _need(_sources() == (initial_pins, initial_snapshots), "operation source fence changed")
            _need(relational_target_codec_sha256(detached_codec) == expected_codec_sha256, "detached codec changed")
        owners = _owners()
        fence()
        request, report_sha, envelope_sha = _inspect(request_raw, expected_request_sha256, owners, fence)
        canonical = _wire(request, MAX_REQUEST_BYTES)
        report = {"schema": ENCODING_SCHEMA, **_identity(), "codec_sha256": expected_codec_sha256,
            "original_request": {"bytes": len(request_raw), "sha256": expected_request_sha256},
            "canonical_request": {"bytes": len(canonical), "sha256": hashlib.sha256(canonical).hexdigest()},
            "canonical_request_raw_utf8": canonical.decode("utf-8"),
            "target_ids": [BOS_ID, *(BYTE_OFFSET + x for x in canonical), EOS_ID],
            "relational_owner_report_sha256": report_sha, "typed_expression_codec_sha256": envelope_sha,
            "producer_pins": initial_pins, **_flags()}
        result = _encoding_shape(report)
        fence()
        return result


def relational_target_encoding_sha256(report):
    """Hash the bounded exact encoding; the hash grants no training authority."""
    return hashlib.sha256(_wire(_encoding_shape(report), MAX_REPORT_BYTES)).hexdigest()


def validate_relational_target_encoding_v1(report, request_raw, *, expected_encoding_sha256,
        expected_request_sha256, codec, expected_codec_sha256):
    """Replay from the independently pinned original request and fixed codec."""
    _need(_sha(expected_encoding_sha256), "independent complete encoding SHA256 required")
    offered = _encoding_shape(report)
    _need(relational_target_encoding_sha256(offered) == expected_encoding_sha256, "complete encoding pin differs")
    regenerated = encode_relational_target_v1(request_raw, expected_request_sha256=expected_request_sha256,
        codec=codec, expected_codec_sha256=expected_codec_sha256)
    _need(_wire(offered, MAX_REPORT_BYTES) == _wire(regenerated, MAX_REPORT_BYTES),
          "encoding differs from exact original-bound regeneration")
    return regenerated


def decode_relational_candidate_v1(generated_ids, *, codec, expected_codec_sha256):
    """Decode offered IDs without references, repair, truncation or fallback.

    Only a valid byte frame yields transport bytes; invalid UTF8 still retains
    the exact hexadecimal bytes and SHA. Incomplete bytes never become a typed
    candidate. Owner refusal is combined rejection, not an inferred semantic
    reason extracted from exception text. No numerical execution is attested.
    """
    detached_codec = _codec(codec, expected_codec_sha256)
    _need(type(generated_ids) is list and len(generated_ids) <= MAX_SEQUENCE_TOKENS,
          "complete bounded generated ID list required")
    _need(all(type(x) is int and -(2 ** 31) <= x < 2 ** 31 for x in generated_ids),
          "plain bounded generated integer IDs required")
    ids = list(generated_ids)
    with _operation():
        initial_pins, initial_snapshots = _sources()
        def fence():
            _need(_sources() == (initial_pins, initial_snapshots), "operation source fence changed")
            _need(relational_target_codec_sha256(detached_codec) == expected_codec_sha256, "detached codec changed")
        valid_ids = all(0 <= x < VOCABULARY_SIZE for x in ids)
        bos = bool(ids) and ids[0] == BOS_ID
        eos = EOS_ID in ids
        terminal = bool(ids) and ids[-1] == EOS_ID
        middle = ids[1:-1] if bos and terminal else ids[1:] if bos else ids
        special = any(0 <= x < BYTE_OFFSET for x in middle)
        frame = valid_ids and bos and not special
        report = {"schema": CANDIDATE_SCHEMA, **_identity(), "codec_sha256": expected_codec_sha256,
            "status": "rejected", "reason": "invalid_frame", "generated_ids": ids,
            "generated_transport_utf8": None, "generated_transport_hex": None,
            "generated_transport_sha256": None, "generated_transport_bytes": None,
            "framing": {"bos_present": bos, "eos_present": eos, "eos_terminal": terminal,
                "token_ids_valid": valid_ids, "interior_special_tokens": special,
                "terminated": bool(frame and terminal)},
            "canonical_request_raw_utf8": None, "canonical_request_sha256": None,
            "canonical_request_bytes": None, "relational_owner_report_sha256": None,
            "typed_expression_codec_sha256": None, "producer_pins": initial_pins, **_flags()}
        if not ids:
            report.update(status="incomplete", reason="missing_bos_and_eos")
        elif frame:
            raw = bytes(x - BYTE_OFFSET for x in middle)
            _bound(len(raw) <= MAX_REQUEST_BYTES, "complete generated request byte bound exceeded")
            report.update(generated_transport_hex=raw.hex(), generated_transport_bytes=len(raw),
                          generated_transport_sha256=hashlib.sha256(raw).hexdigest())
            try:
                report["generated_transport_utf8"] = raw.decode("utf-8")
            except UnicodeError:
                pass
            if not terminal:
                report.update(status="incomplete", reason="missing_eos")
            elif report["generated_transport_utf8"] is None:
                report["reason"] = "invalid_utf8"
            else:
                # Bounds are checked before imports; overflow is refusal, not
                # a silently truncated or semantically classified candidate.
                try:
                    _request(raw, report["generated_transport_sha256"])
                except _CompleteBoundExceeded:
                    raise
                except ValueError:
                    report["reason"] = "request_json_rejected"
                else:
                    owners = _owners()
                    fence()
                    try:
                        checked, owner_sha, envelope_sha = _inspect(raw,
                            report["generated_transport_sha256"], owners, fence)
                    except _CompleteBoundExceeded:
                        raise
                    except ValueError:
                        fence()
                        report["reason"] = "typed_request_rejected"
                    else:
                        canonical = _wire(checked, MAX_REQUEST_BYTES)
                        report.update(status="valid_candidate", reason=None,
                            canonical_request_raw_utf8=canonical.decode("utf-8"),
                            canonical_request_sha256=hashlib.sha256(canonical).hexdigest(),
                            canonical_request_bytes=len(canonical), relational_owner_report_sha256=owner_sha,
                            typed_expression_codec_sha256=envelope_sha)
        result = _copy(report, MAX_REPORT_BYTES, sequence_report=True)
        fence()
        return result


__all__ = ["LegalRelationalTargetCodecError", "build_relational_target_codec_v1",
    "relational_target_codec_sha256", "encode_relational_target_v1",
    "decode_relational_candidate_v1", "relational_target_encoding_sha256",
    "validate_relational_target_encoding_v1"]
