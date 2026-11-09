"""One finite score-vector selection using the existing compact prefix owner.

The complete offered prefix and scores remain observations. This module adds
at most one allowed ID, introduces no grammar or numerical model, and proves
neither score provenance nor learned-head/checkpoint compatibility.
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

SCHEMA = "legal-compact-content-token-selection/v1"
PROFILE = "object-relational-compact-content-selection/v1"
FORMAT = "one-step-allowed-logit-argmax/v1"
VOCABULARY_SIZE = 537
MAX_SEQUENCE_TOKENS = 512
MAX_SCORE_INTEGER = (1 << 53) - 1
MAX_INPUT_BYTES = 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_CONTEXT_BYTES = 524288
MAX_CODEC_BYTES = 32768
MAX_LOGITS_BYTES = 32768
MAX_SOURCE_BYTES = 131072
MAX_JSON_ITEMS, MAX_JSON_DEPTH = 100000, 96
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OWNER_NAME = "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_tokens_v1"
_OWNER_REL = "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py"
_OWNER_SHA = "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_PREFIX_SCHEMA = "legal-compact-content-token-prefix/v1"
_PREFIX_PROFILE = "object-relational-compact-content-tokens/v1"
_PREFIX_FORMAT = "fixed-json-lexical-compact-content/v1"
_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "accepted", "admitted",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "permitted_inference_context_verified", "checkpoint_compatibility_verified",
    "model_executed", "training_executed", "backend_executed", "Lean_admitted",
    "proof_authority", "logits_origin_verified", "head_compatibility_qualified",
    "global_prefix_completability_proven",
), False)
_LIMITATIONS = (
    "Scores are supplied finite observations; no numerical model, head, checkpoint, encoder or training execution is authenticated.",
    "Only the existing public compact token-prefix owner supplies allowed IDs; this selector introduces no grammar, AST or logical constructor.",
    "Selection appends at most one allowed ID before generation; no already offered prefix ID, missing EOS or PAD is repaired or removed.",
    "Allowed next IDs are local constraints, not proof of eventual completion, source meaning, permitted context or learned accuracy.",
    "Context and codec commitments establish supplied byte/value identity only; they grant no inference permission, review, eligibility or graph/Lean authority.",
    "Named source and input endpoint fences are finite custody checks, not a lock, arbitrary loaded-bytecode proof, third-party integrity or an operating-system sandbox.",
)


class CompactContentSelectionError(ValueError):
    """Bounded API, independently committed input or source-custody refusal."""


def _need(value, message):
    if not value:
        raise CompactContentSelectionError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _copy(value, maximum, *, allow_bytes=False):
    """Capture plain bounded values before any whole-value serialization.

    Charge exact canonical JSON bytes for ordinary values and raw length for
    declared byte parameters. Repeated aliases are charged on every occurrence.
    Scalar numbers retain their exact int/float type and negative floating zero.
    """
    remaining, items, active = maximum, MAX_JSON_ITEMS, set()

    def charge(count):
        nonlocal remaining
        remaining -= count
        _need(remaining >= 0, "complete input byte bound exceeded before serialization")

    def text(item):
        _need(len(item) <= maximum, "bounded ordinary string required")
        charge(2)
        for char in item:
            code = ord(char)
            _need(code != 0 and not 0xD800 <= code <= 0xDFFF,
                  "ordinary NUL-free scalar UTF8 required")
            if char in ('"', "\\") or char in "\b\f\n\r\t":
                charge(2)
            elif code < 32:
                charge(6)
            else:
                charge(1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)

    def visit(item, depth):
        nonlocal items
        items -= 1
        _need(items >= 0 and depth <= MAX_JSON_DEPTH,
              "complete ordinary item/depth bound exceeded")
        if type(item) in (dict, list):
            _need(id(item) not in active, "cyclic ordinary value refused")
            _need(len(item) <= items, "complete container item bound exceeded")
            active.add(id(item))
            try:
                charge(2)
                if type(item) is dict:
                    copied = {}
                    for index, (key, child) in enumerate(item.items()):
                        _need(type(key) is str, "plain string JSON keys required")
                        charge(1 + bool(index))
                        visit(key, depth + 1)
                        copied[key] = visit(child, depth + 1)
                else:
                    copied = []
                    for index, child in enumerate(item):
                        if index:
                            charge(1)
                        copied.append(visit(child, depth + 1))
                return copied
            finally:
                active.remove(id(item))
        if type(item) is bytes and allow_bytes:
            charge(len(item))
        elif type(item) is str:
            text(item)
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded plain integer required")
            charge(len(str(item)))
        elif type(item) is float:
            _need(math.isfinite(item), "finite plain float required")
            charge(len(repr(item)))
        else:
            raise CompactContentSelectionError("ordinary containers and primitives required")
        return item

    try:
        return visit(value, 0)
    except (RuntimeError, RecursionError) as error:
        raise CompactContentSelectionError("stable bounded ordinary input required") from error


def _wire(value, maximum):
    detached = _copy(value, maximum)
    try:
        raw = json.dumps(detached, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
        raise CompactContentSelectionError("bounded ordinary canonical JSON required") from error
    _need(len(raw) <= maximum, "complete canonical JSON byte bound exceeded")
    return raw


def _detach(value, maximum):
    return json.loads(_wire(value, maximum))


def _fingerprint(value):
    """Typed length-framed identity for already captured JSON and raw bytes."""
    result = hashlib.sha256()

    def tag(kind, count):
        result.update(kind + str(count).encode("ascii") + b":")

    def visit(item):
        if type(item) is dict:
            tag(b"d", len(item))
            for key in sorted(item):
                visit(key)
                visit(item[key])
        elif type(item) is list:
            tag(b"l", len(item))
            for child in item:
                visit(child)
        elif type(item) is bytes:
            tag(b"b", len(item))
            result.update(item)
        else:
            raw = _wire(item, MAX_INPUT_BYTES)
            tag(b"j", len(raw))
            result.update(raw)

    visit(value)
    return result.hexdigest()


def _source(path, expected):
    _need(path.is_absolute() and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents),
          "direct canonical source parents required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_SOURCE_BYTES,
          "bounded regular source required")
    witness = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                            info.st_mtime_ns, info.st_ctime_ns)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _need(witness(opened) == witness(before), "source changed before read")
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    _need(witness(before) == witness(after) == witness(path.lstat())
          and len(raw) == before.st_size and hashlib.sha256(raw).hexdigest() == expected,
          "source changed or raw source pin differs")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}


def _self_fence():
    return _source(_SELF_PATH, _SELF_SHA)


def _owner():
    self_pin = _self_fence()
    expected_path = None
    for parent in _SELF_PATH.parents:
        for root in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            candidate = root / _OWNER_REL
            if candidate.is_file():
                _need(root.resolve() == root, "canonical package tree required")
                expected_path = candidate
                break
        if expected_path is not None:
            break
    _need(expected_path is not None, "canonical compact token-prefix owner unavailable")
    owner_pin = _source(expected_path, _OWNER_SHA)
    failure = None
    try:
        owner = importlib.import_module(_OWNER_NAME)
        _need(type(owner.__file__) is str and Path(owner.__file__).absolute() == expected_path,
              "compact token-prefix owner origin differs")
        return owner, [owner_pin, self_pin]
    except BaseException as error:
        failure = error
        raise
    finally:
        def final_sources():
            _need(_source(expected_path, _OWNER_SHA) == owner_pin
                  and _self_fence() == self_pin, "source changed during owner loading")
        _finish(failure, final_sources)


def _closing(loaded):
    _need(_owner()[1] == loaded[1], "operation source custody changed")


def _finish(failure, check):
    """Keep the first escaping operation error if a closing fence also fails."""
    try:
        check()
    except BaseException:
        if failure is None:
            raise
        failure.add_note("A closing selector input/source custody check also failed.")


def _scores(logits):
    _need(type(logits) is list and len(logits) == VOCABULARY_SIZE,
          "exact full 537-score plain list required")
    for score in logits:
        _need((type(score) is int and abs(score) <= MAX_SCORE_INTEGER)
              or (type(score) is float and math.isfinite(score)),
              "scores require plain finite floats or at most 53-bit plain integers")


def _preflight(original):
    _scores(original["logits"])
    _need(type(original["prefix_ids"]) is list
          and len(original["prefix_ids"]) <= MAX_SEQUENCE_TOKENS,
          "bounded plain prefix list required")
    _need(type(original["context_raw"]) is bytes
          and 0 < len(original["context_raw"]) <= MAX_CONTEXT_BYTES,
          "bounded exact context bytes required")
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    _scores(snapshot["logits"])
    _need(type(snapshot["prefix_ids"]) is list
          and len(snapshot["prefix_ids"]) <= MAX_SEQUENCE_TOKENS
          and all(type(item) is int and -(1 << 63) < item < (1 << 63)
                  for item in snapshot["prefix_ids"]), "bounded plain integer prefix required")
    _hash(snapshot["expected_context_sha256"], "context raw bytes")
    _need(hashlib.sha256(snapshot["context_raw"]).hexdigest() == snapshot["expected_context_sha256"],
          "independent context raw SHA256 differs")
    _hash(snapshot["expected_codec_sha256"], "codec")
    _need(type(snapshot["codec"]) is dict, "complete plain codec dictionary required")
    _need(hashlib.sha256(_wire(snapshot["codec"], MAX_CODEC_BYTES)).hexdigest()
          == snapshot["expected_codec_sha256"], "independent codec SHA256 differs")
    _wire(snapshot["logits"], MAX_LOGITS_BYTES)
    return snapshot


def _prefix_report(offered, snapshot):
    """Check public result association; all grammar decisions remain its owner."""
    report = _detach(offered, MAX_REPORT_BYTES)
    _need(type(report) is dict and report.get("schema") == _PREFIX_SCHEMA
          and report.get("profile") == _PREFIX_PROFILE and report.get("format") == _PREFIX_FORMAT
          and report.get("codec_sha256") == snapshot["expected_codec_sha256"]
          and report.get("context_raw_sha256") == snapshot["expected_context_sha256"]
          and report.get("offered_ids") == snapshot["prefix_ids"],
          "public prefix report association differs")
    allowed = report.get("allowed_token_ids")
    status = report.get("status")
    _need(status in ("empty", "prefix", "complete", "rejected", "budget_exhausted")
          and (report.get("reason") is None or type(report.get("reason")) is str)
          and type(allowed) is list and len(allowed) <= VOCABULARY_SIZE
          and all(type(item) is int and 0 <= item < VOCABULARY_SIZE for item in allowed)
          and allowed == sorted(set(allowed)), "public prefix selection inventory differs")
    _need((bool(allowed) and status in ("empty", "prefix") and len(snapshot["prefix_ids"]) < MAX_SEQUENCE_TOKENS)
          or (not allowed and status in ("complete", "rejected", "budget_exhausted")),
          "public prefix disposition differs")
    _need(type(report.get("authority")) is dict
          and all(value is False for value in report["authority"].values())
          and type(report.get("training_mask")) is int and report["training_mask"] == 0
          and type(report.get("evaluation_gold_mask")) is int and report["evaluation_gold_mask"] == 0
          and report.get("local_prefix_only") is True
          and report.get("global_completability_proven") is False,
          "public prefix authority or local-only boundary differs")
    return report


def _argmax(scores, allowed):
    best = allowed[0]
    for index in allowed[1:]:
        if scores[index] > scores[best]:
            best = index
    return best


def select_compact_content_token_v1(logits, prefix_ids, context_raw, *, expected_context_sha256,
                                    codec, expected_codec_sha256):
    """Append one allowed score maximum, with lowest-ID ties and full custody.

    Invalid score/API/context/hash/source inputs raise. A legitimate bounded
    rejected, completed or budget-exhausted offered prefix yields a retained
    no-selection observation. No expected target, sidecar or head is accepted.
    """
    original = dict(logits=logits, prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec,
        expected_codec_sha256=expected_codec_sha256)
    snapshot = _preflight(original)
    token = _fingerprint(snapshot)
    loaded = None
    failure = None

    def fence():
        _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
              and _fingerprint(snapshot) == token, "original or captured selector inputs changed")
        if loaded is None:
            _self_fence()
        else:
            _closing(loaded)

    try:
        loaded = _owner()
        fence()
        checked = loaded[0].compact_content_allowed_token_ids_v1(
            snapshot["prefix_ids"], snapshot["context_raw"],
            expected_context_sha256=snapshot["expected_context_sha256"],
            codec=snapshot["codec"], expected_codec_sha256=snapshot["expected_codec_sha256"])
        fence()
        prefix_report = _prefix_report(checked, snapshot)
        scores = snapshot["logits"]
        allowed = prefix_report["allowed_token_ids"]
        raw_id = _argmax(scores, list(range(VOCABULARY_SIZE)))
        selected = _argmax(scores, allowed) if allowed else None
        next_ids = list(snapshot["prefix_ids"])
        if selected is not None:
            next_ids.append(selected)
        reason = None if selected is not None else (prefix_report["reason"] or prefix_report["status"])
        result = {
            "schema": SCHEMA, "profile": PROFILE, "format": FORMAT,
            "status": "selected" if selected is not None else "no_selection",
            "reason": reason, "prefix_status": prefix_report["status"],
            "logits": scores,
            "logits_sha256": hashlib.sha256(_wire(scores, MAX_LOGITS_BYTES)).hexdigest(),
            "offered_prefix_ids": snapshot["prefix_ids"], "next_prefix_ids": next_ids,
            "prefix_report": prefix_report,
            "raw_argmax_token_id": raw_id, "raw_argmax_score": scores[raw_id],
            "selected_token_id": selected,
            "selected_score": scores[selected] if selected is not None else None,
            "selection_performed": selected is not None,
            "selection_overrode_raw_argmax": selected is not None and selected != raw_id,
            "tokens_appended": int(selected is not None), "tie_breaker": "lowest_token_id",
            "codec_sha256": snapshot["expected_codec_sha256"],
            "context_raw_sha256": snapshot["expected_context_sha256"],
            "owner_pins": loaded[1], "logits_origin_verified": False,
            "head_compatibility_qualified": False, "authority": dict(_AUTHORITY),
            "training_mask": 0, "evaluation_gold_mask": 0,
            "limitations": list(_LIMITATIONS),
        }
        detached = _detach(result, MAX_REPORT_BYTES)
        fence()
        return detached
    except BaseException as error:
        failure = error
        raise
    finally:
        _finish(failure, fence)


__all__ = ["CompactContentSelectionError", "select_compact_content_token_v1"]
