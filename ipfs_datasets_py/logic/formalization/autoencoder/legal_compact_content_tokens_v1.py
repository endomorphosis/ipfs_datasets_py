"""Fixed lexical tokens and local prefixes for existing compact LegalIR content.

The existing public compact-content owner validates context and complete ASTs.
This module introduces no logical constructors, model, checkpoint migration,
source interpretation or eligibility. Reference/identity sidecars are absent
from prediction and prefix APIs. Context permission remains the caller's duty.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import re
import stat

CODEC_SCHEMA = "legal-compact-content-token-codec/v1"
ENCODING_SCHEMA = "legal-compact-content-token-encoding/v1"
PREFIX_SCHEMA = "legal-compact-content-token-prefix/v1"
CANDIDATE_SCHEMA = "legal-compact-content-token-candidate/v1"
CONTENT_SCHEMA = "legal-relational-compact-content/v1"
CONTEXT_SCHEMA = "legal-relational-compact-context/v1"
PROFILE = "object-relational-compact-content-tokens/v1"
FORMAT = "fixed-json-lexical-compact-content/v1"
PAD_ID, BOS_ID, EOS_ID = 0, 1, 2
MAX_SEQUENCE_TOKENS = 512
MAX_NODES, MAX_DEPTH = 512, 48
MAX_CONTENT_BYTES = 262144
MAX_CONTEXT_BYTES = 524288
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_CODEC_BYTES = 32768
MAX_JSON_ITEMS, MAX_JSON_DEPTH = 100000, 96
_CONSTRUCTORS = ("variable", "predicate", "forall", "exists", "and", "or",
                 "implies", "iff", "not", "extension")
_BINARY = frozenset(("and", "or", "implies", "iff"))
_FORMULAS = tuple(kind for kind in _CONSTRUCTORS if kind != "variable")
_LEXICAL = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
                      r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
                      r'|true|false|null|[{}\[\],:]')
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OWNER_NAME = "ipfs_datasets_py.logic.autoformal.legal_compact_content_v1"
_OWNER_REL = "logic/autoformal/legal_compact_content_v1.py"
_OWNER_SHA = "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "accepted", "admitted",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "permitted_inference_context_verified", "checkpoint_compatibility_verified",
    "model_executed", "training_executed", "backend_executed", "Lean_admitted",
    "proof_authority", "global_prefix_completability_proven",
), False)


class CompactContentTokensError(ValueError):
    """Bounded API, fixed vocabulary, hash or source custody refusal."""


class _GrammarError(Exception):
    """A bounded offered lexical sequence violates this explicit grammar."""


class _More(Exception):
    def __init__(self, choices):
        self.choices = set(choices)


def _need(value, message):
    if not value:
        raise CompactContentTokensError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _wire(value, maximum):
    """Capture bounded plain JSON before complete serialization/allocation."""
    remaining, byte_budget, active = MAX_JSON_ITEMS, maximum, set()

    def charge(count):
        nonlocal byte_budget
        byte_budget -= count
        _need(byte_budget >= 0, "complete JSON byte bound exceeded before serialization")

    def text(text_value):
        _need(len(text_value) <= maximum and "\x00" not in text_value,
              "bounded NUL-free UTF8 strings required")
        charge(2)
        for character in text_value:
            code = ord(character)
            _need(not 0xD800 <= code <= 0xDFFF, "valid scalar UTF8 required")
            if character in ('"', "\\") or character in "\b\f\n\r\t":
                charge(2)
            elif code < 0x20:
                charge(6)
            else:
                charge(1 if code < 0x80 else 2 if code < 0x800 else 3 if code < 0x10000 else 4)

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= MAX_JSON_DEPTH, "complete JSON item/depth bound exceeded")
        if type(item) in (dict, list):
            identity = id(item)
            _need(identity not in active, "cyclic JSON refused")
            active.add(identity)
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
                active.remove(identity)
        if type(item) is str:
            text(item)
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded plain JSON integer required")
            charge(len(str(item)))
        else:
            raise CompactContentTokensError("plain JSON without floats or custom values required")
        return item

    try:
        copied = visit(value, 0)
        raw = json.dumps(copied, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, UnicodeError, RecursionError, OverflowError, RuntimeError) as error:
        raise CompactContentTokensError("bounded stable ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _detach(value, maximum):
    return json.loads(_wire(value, maximum))


def _sha(value, maximum):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _pairs(rows):
    result = {}
    for key, value in rows:
        _need(key not in result, "duplicate JSON key refused")
        result[key] = value
    return result


def _reject_number(_):
    raise CompactContentTokensError("JSON float/nonfinite values refused")


def _parse(raw, expected, maximum, label):
    _hash(expected, label)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded exact bytes required: " + label)
    _need(hashlib.sha256(raw).hexdigest() == expected, label + " raw SHA256 differs")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=_reject_number, parse_constant=_reject_number)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise CompactContentTokensError("bounded duplicate-free UTF8 JSON required: " + label) from error
    return _detach(value, maximum)


def _source(path, expected):
    _need(path.is_absolute() and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents),
          "direct canonical source parents required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 131072,
          "bounded regular source required")
    raw = path.read_bytes()
    after = path.lstat()
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    _need(identity(before) == identity(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, "source changed or raw pin differs")
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
    _need(expected_path is not None, "canonical compact-content owner unavailable")
    owner_pin = _source(expected_path, _OWNER_SHA)
    owner = importlib.import_module(_OWNER_NAME)
    _need(Path(owner.__file__).absolute() == expected_path, "compact-content owner origin differs")
    _source(expected_path, _OWNER_SHA)
    return owner, [owner_pin, self_pin]


def _closing(loaded):
    _need(_owner()[1] == loaded[1], "operation source custody changed")


def _fixed():
    strings = ("schema", "tree", CONTENT_SCHEMA, *_CONSTRUCTORS, "O", "P", "F")
    tokens = {json.dumps(text, ensure_ascii=False) for text in strings}
    tokens.update("{}[],:".strip())
    tokens.update(str(index) for index in range(512))
    vocabulary = ["<pad>", "<bos>", "<eos>", *sorted(tokens)]
    return {
        "schema": CODEC_SCHEMA, "profile": PROFILE, "format": FORMAT,
        "content_schema": CONTENT_SCHEMA, "context_schema": CONTEXT_SCHEMA,
        "vocabulary": vocabulary, "vocabulary_size": len(vocabulary),
        "pad_id": PAD_ID, "bos_id": BOS_ID, "eos_id": EOS_ID,
        "max_sequence_tokens": MAX_SEQUENCE_TOKENS, "max_nodes": MAX_NODES,
        "max_depth": MAX_DEPTH, "integer_min": 0, "integer_max": 511,
        "constructors": list(_CONSTRUCTORS),
        "grammar_scope": "local canonical JSON prefixes; context-dependent arity, lexical binding and complete predicate use",
        "global_completability_proven": False, "numerical_head_compatible": False,
        "permitted_inference_context_verified": False,
    }


def build_compact_content_token_codec_v1():
    """Publish the same fixed vocabulary before any source/target/context."""
    _self_fence()
    result = _detach(_fixed(), MAX_CODEC_BYTES)
    _self_fence()
    return result


def compact_content_token_codec_sha256(codec):
    """Validate and hash the complete fixed codec; no operation owner loads."""
    _self_fence()
    raw = _wire(codec, MAX_CODEC_BYTES)
    _need(raw == _wire(_fixed(), MAX_CODEC_BYTES), "exact fixed token codec required")
    result = hashlib.sha256(raw).hexdigest()
    _self_fence()
    return result


def _codec(codec, expected):
    _hash(expected, "codec")
    _need(compact_content_token_codec_sha256(codec) == expected, "independent codec SHA256 differs")
    # Use the fixed owner-built value after checking the captured offered
    # identity; do not reread a caller's mutable dictionary after validation.
    return _detach(_fixed(), MAX_CODEC_BYTES)


def _ids(offered):
    _need(type(offered) is list and len(offered) <= MAX_SEQUENCE_TOKENS,
          "plain ID list within512 total tokens required; no truncation")
    copied = []
    for index, item in enumerate(offered):
        _need(index < MAX_SEQUENCE_TOKENS and type(item) is int and -(1 << 63) < item < (1 << 63),
              "plain bounded integer IDs required; booleans/floats/custom values refused")
        copied.append(item)
    return copied


def _context(raw, expected, loaded):
    context = _parse(raw, expected, MAX_CONTEXT_BYTES, "context")
    _need(type(context) is dict and set(context) == {"schema", "signature", "argument_roles"}
          and context["schema"] == CONTEXT_SCHEMA and type(context["signature"]) is dict
          and "signature_id" not in context["signature"], "closed identity-free context required")
    signature = {**context["signature"], "signature_id": "compact-token-context-signature-v1"}
    signature_raw, roles_raw = _wire(signature, MAX_CONTEXT_BYTES), _wire(context["argument_roles"], MAX_CONTEXT_BYTES)
    owner = loaded[0]
    checked = owner.prepare_context_v1(signature_raw, roles_raw,
        expected_signature_sha256=hashlib.sha256(signature_raw).hexdigest(),
        expected_argument_roles_sha256=hashlib.sha256(roles_raw).hexdigest())
    _need(_wire(checked, MAX_CONTEXT_BYTES) == _wire(context, MAX_CONTEXT_BYTES),
          "context differs from public compact owner preparation")
    return context


class _PrefixParser:
    """Reference parser for the existing compact JSON projection, not a new AST."""
    def __init__(self, lexical, context):
        self.tokens, self.position = lexical, 0
        self.arities = [len(symbol["domain"]) for symbol in context["signature"]["symbols"]]
        self.used = set()
        self.binders = 0
        self.counts = {"nodes": 0, "quantifiers": 0, "modal_nodes": 0, "predicate_occurrences": 0}

    def take(self, choices):
        choices = set(choices)
        if self.position == len(self.tokens):
            raise _More(choices)
        item = self.tokens[self.position]
        if item not in choices:
            raise _GrammarError("unexpected lexical token")
        self.position += 1
        return item

    def literal(self, value):
        return self.take((value,))

    def tree(self, bound, depth, formula=True):
        if depth > MAX_DEPTH or self.counts["nodes"] >= MAX_NODES:
            raise _GrammarError("relational node/depth limit")
        self.literal("[")
        kind = json.loads(self.take(json.dumps(name) for name in (_FORMULAS if formula else ("variable",))))
        self.counts["nodes"] += 1
        self.literal(",")
        if kind == "variable":
            if not bound:
                raise _GrammarError("no lexically active binder")
            index = int(self.take(str(index) for index in bound))
            result = [kind, index]
        elif kind == "predicate":
            index = int(self.take(str(index) for index in range(len(self.arities))))
            self.used.add(index)
            self.counts["predicate_occurrences"] += 1
            self.literal(",")
            self.literal("[")
            children = []
            for argument in range(self.arities[index]):
                if argument:
                    self.literal(",")
                children.append(self.tree(bound, depth + 1, False))
            self.literal("]")
            result = [kind, index, children]
        elif kind in {"forall", "exists"}:
            if self.binders > 511:
                raise _GrammarError("binder index outside fixed vocabulary")
            index = self.binders
            self.literal(str(index))
            self.binders += 1
            self.counts["quantifiers"] += 1
            self.literal(",")
            result = [kind, index, self.tree(bound | {index}, depth + 1)]
        elif kind in _BINARY:
            left = self.tree(bound, depth + 1)
            self.literal(",")
            result = [kind, left, self.tree(bound, depth + 1)]
        elif kind == "not":
            result = [kind, self.tree(bound, depth + 1)]
        elif kind == "extension":
            letter = json.loads(self.take(('"O"', '"P"', '"F"')))
            self.counts["modal_nodes"] += 1
            self.literal(",")
            result = [kind, letter, self.tree(bound, depth + 1)]
        else:
            raise _GrammarError("unsupported existing constructor")
        self.literal("]")
        return result

    def document(self):
        for token in ("{", '"schema"', ":", json.dumps(CONTENT_SCHEMA), ",", '"tree"', ":"):
            self.literal(token)
        tree = self.tree(frozenset(), 0)
        self.literal("}")
        if self.used != set(range(len(self.arities))) or self.binders == 0:
            raise _GrammarError("completed tree must quantify and use every declared predicate")
        if self.position != len(self.tokens):
            raise _GrammarError("tokens after complete content")
        return {"schema": CONTENT_SCHEMA, "tree": tree}


def _scan(ids, vocabulary, context):
    """Return syntax state without loading or calling any operation owner."""
    counts = {"nodes": 0, "quantifiers": 0, "modal_nodes": 0, "predicate_occurrences": 0}
    if not ids:
        return "empty", None, {BOS_ID}, counts, None
    if any(index < 0 or index >= len(vocabulary) for index in ids):
        return "rejected", "invalid_token_ids", set(), counts, None
    if ids[0] != BOS_ID:
        return "rejected", "missing_bos", set(), counts, None
    terminal = len(ids) > 1 and ids[-1] == EOS_ID
    body = ids[1:-1] if terminal else ids[1:]
    if any(index < 3 for index in body):
        return "rejected", "interior_special_tokens", set(), counts, None
    parser = _PrefixParser([vocabulary[index] for index in body], context)
    try:
        content = parser.document()
    except _More as error:
        if terminal:
            return "rejected", "invalid_compact_prefix", set(), parser.counts, None
        positions = {token: index for index, token in enumerate(vocabulary)}
        return "prefix", None, {positions[token] for token in error.choices}, parser.counts, None
    except _GrammarError:
        return "rejected", "invalid_compact_prefix", set(), parser.counts, None
    if terminal:
        return "complete", None, set(), parser.counts, content
    return "prefix", None, {EOS_ID}, parser.counts, content


def _analysis(ids, codec, context):
    status, reason, choices, counts, content = _scan(ids, codec["vocabulary"], context)
    if status in {"rejected", "complete"}:
        return status, reason, [], counts, content
    if len(ids) == MAX_SEQUENCE_TOKENS:
        return "budget_exhausted", "output_limit_without_eos", [], counts, content
    # Check only the immediate next state and total framing capacity. This is
    # deliberately not a search/proof that every offered branch can finish.
    allowed = []
    for token in sorted(choices):
        trial = ids + [token]
        trial_status, _, _, _, _ = _scan(trial, codec["vocabulary"], context)
        if trial_status != "rejected" and (len(trial) < MAX_SEQUENCE_TOKENS or trial_status == "complete"):
            allowed.append(token)
    if not allowed:
        if len(ids) >= MAX_SEQUENCE_TOKENS - 1:
            return "budget_exhausted", "no_admissible_next_token_within_total_limit", [], counts, content
        return "rejected", "invalid_compact_prefix", [], counts, content
    return status, reason, allowed, counts, content


def _base(schema, codec_sha, context, context_raw_sha, loaded):
    return {"schema": schema, "profile": PROFILE, "format": FORMAT,
            "codec_sha256": codec_sha, "context_sha256": _sha(context, MAX_CONTEXT_BYTES),
            "context_raw_sha256": context_raw_sha, "owner_pins": loaded[1],
            "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0}


def _prediction(content, context, loaded):
    content_raw, context_raw = _wire(content, MAX_CONTENT_BYTES), _wire(context, MAX_CONTEXT_BYTES)
    # Any source/context/owner exception, including interrupts, propagates.
    prediction = loaded[0].decode_prediction_v1(content_raw, context_raw,
        expected_content_sha256=hashlib.sha256(content_raw).hexdigest(),
        expected_context_sha256=hashlib.sha256(context_raw).hexdigest())
    if _wire(prediction["content"], MAX_CONTENT_BYTES) != content_raw:
        raise RuntimeError("public compact owner disagrees with complete lexical content")
    return prediction


def encode_compact_content_tokens_v1(content_raw, context_raw, *, expected_content_sha256,
                                    expected_context_sha256, codec, expected_codec_sha256):
    """Encode validated complete content; identities/provenance are not labels."""
    fixed = _codec(codec, expected_codec_sha256)
    content = _parse(content_raw, expected_content_sha256, MAX_CONTENT_BYTES, "content")
    canonical = _wire(content, MAX_CONTENT_BYTES)
    lexical = _LEXICAL.findall(canonical.decode("utf-8"))
    _need("".join(lexical).encode("utf-8") == canonical, "canonical JSON lexical coverage differs")
    positions = {token: index for index, token in enumerate(fixed["vocabulary"])}
    _need(all(token in positions for token in lexical), "content token outside fixed vocabulary")
    ids = [BOS_ID, *(positions[token] for token in lexical), EOS_ID]
    _ids(ids)
    loaded = _owner()
    context = _context(context_raw, expected_context_sha256, loaded)
    status, _, _, counts, checked = _analysis(ids, fixed, context)
    _need(status == "complete" and _wire(checked, MAX_CONTENT_BYTES) == canonical,
          "complete content violates fixed context-aware grammar")
    prediction = _prediction(checked, context, loaded)
    if prediction["counts"] != counts:
        raise RuntimeError("public compact owner disagrees with complete lexical counts")
    result = _base(ENCODING_SCHEMA, expected_codec_sha256, context, expected_context_sha256, loaded)
    result.update(status="encoded_unreviewed_content", target_ids=ids, lexical_tokens=lexical,
        lexical_token_count=len(lexical), total_token_count=len(ids),
        canonical_content_raw_utf8=canonical.decode("utf-8"),
        content_sha256=hashlib.sha256(canonical).hexdigest(), original_content_raw_sha256=expected_content_sha256,
        prediction=prediction, counts=counts)
    detached = _detach(result, MAX_REPORT_BYTES)
    _closing(loaded)
    return detached


def compact_content_allowed_token_ids_v1(prefix_ids, context_raw, *, expected_context_sha256,
                                         codec, expected_codec_sha256):
    """Inspect one offered prefix; only immediate grammar/budget steps are checked."""
    ids = _ids(prefix_ids)
    fixed = _codec(codec, expected_codec_sha256)
    loaded = _owner()
    context = _context(context_raw, expected_context_sha256, loaded)
    status, reason, allowed, counts, _ = _analysis(ids, fixed, context)
    result = _base(PREFIX_SCHEMA, expected_codec_sha256, context, expected_context_sha256, loaded)
    result.update(status=status, reason=reason, offered_ids=ids, allowed_token_ids=allowed,
                  counts=counts, local_prefix_only=True, global_completability_proven=False,
                  remaining_token_slots=MAX_SEQUENCE_TOKENS - len(ids))
    detached = _detach(result, MAX_REPORT_BYTES)
    _closing(loaded)
    return detached


def decode_compact_content_tokens_v1(generated_ids, context_raw, *, expected_context_sha256,
                                     codec, expected_codec_sha256):
    """Retain bounded raw IDs/framing, classify syntax only, then call public owner."""
    ids = _ids(generated_ids)
    fixed = _codec(codec, expected_codec_sha256)
    loaded = _owner()
    context = _context(context_raw, expected_context_sha256, loaded)
    status, reason, _, counts, content = _analysis(ids, fixed, context)
    valid = all(0 <= index < fixed["vocabulary_size"] for index in ids)
    bos, eos, terminal = bool(ids) and ids[0] == BOS_ID, EOS_ID in ids, bool(ids) and ids[-1] == EOS_ID
    body = ids[1:-1] if bos and terminal else ids[1:] if bos else ids
    interior = any(0 <= index < 3 for index in body)
    text = "".join(fixed["vocabulary"][index] for index in body) if valid and not interior else None
    result = _base(CANDIDATE_SCHEMA, expected_codec_sha256, context, expected_context_sha256, loaded)
    result.update(status="rejected", reason=reason, generated_ids=ids,
        generated_content_raw_utf8=text, generated_content_hex=text.encode("utf-8").hex() if text is not None else None,
        generated_content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
        framing={"bos_present": bos, "eos_present": eos, "eos_terminal": terminal,
                 "token_ids_valid": valid, "interior_special_tokens": interior,
                 "terminated": bool(valid and bos and terminal and not interior)},
        prediction=None, counts=None)
    if not ids:
        result.update(status="incomplete", reason="missing_bos_and_eos")
    elif status == "complete":
        prediction = _prediction(content, context, loaded)
        if prediction["counts"] != counts:
            raise RuntimeError("public compact owner disagrees with complete lexical counts")
        result.update(status="valid_candidate", reason=None, prediction=prediction, counts=counts)
    elif status == "prefix":
        result.update(status="incomplete", reason="missing_eos")
    elif terminal and reason == "invalid_compact_prefix":
        result["reason"] = "invalid_compact_content"
    detached = _detach(result, MAX_REPORT_BYTES)
    _closing(loaded)
    return detached


__all__ = ["CompactContentTokensError", "build_compact_content_token_codec_v1",
           "compact_content_token_codec_sha256", "encode_compact_content_tokens_v1",
           "compact_content_allowed_token_ids_v1", "decode_compact_content_tokens_v1"]
