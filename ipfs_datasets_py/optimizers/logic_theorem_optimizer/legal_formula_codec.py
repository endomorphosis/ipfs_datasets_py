"""Lossless, bounded token grammar for one canonical deontic rule.

This is a new codec, not the historical PGIR identifier-bucket tokenizer.
Source tokens and exact typed target atoms are fitted on training examples
only. Unknown values and overlong sequences raise; nothing is truncated,
hashed into identifier buckets, copied from a target, or inferred by a parser.
Syntax validation grants no semantic qualification or Lake admission.
"""
from __future__ import annotations

from functools import lru_cache
import json
import re

from ...logic.legal_ir.canonical_contracts import CanonicalRoundTripIR, CanonicalContractError
from .legal_ir_grammar_decoder import LegalIRGrammarDecoder

SCHEMA = "legal-source-formula-codec/v1"
MAX_SOURCE_TOKENS = 64
MAX_TARGET_TOKENS = 64
MAX_VOCABULARY = 4096
MAX_EXAMPLES = 4096
MAX_QUALIFIERS = 4
SOURCE_PAD = 0
SOURCE_UNK = 1
TARGET_PAD = 0
TARGET_BOS = 1
TARGET_EOS = 2
FIELDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
SCALARS = FIELDS[:4]
QUALIFIERS = FIELDS[4:]
_SOURCE_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_MODALITIES = {"O": "obligation", "P": "permission", "F": "prohibition"}
_POLICY = {
    "source_tokenization": "unicode_casefold_word_or_punctuation/v1",
    "source_unknown": "reject", "target_unknown": "reject",
    "vocabulary_origin": "training_examples_only", "identifier_hashing": False,
    "target_schema": "CanonicalRoundTripIR@1", "rule_count": 1,
    "field_order": list(FIELDS), "qualifiers": "sorted_unique_input_required",
    "max_qualifiers_per_facet": MAX_QUALIFIERS,
    "max_source_tokens": MAX_SOURCE_TOKENS, "max_target_tokens": MAX_TARGET_TOKENS,
    "max_vocabulary": MAX_VOCABULARY,
    "source_pad_id": SOURCE_PAD, "source_unk_id": SOURCE_UNK,
    "target_pad_id": TARGET_PAD, "target_bos_id": TARGET_BOS, "target_eos_id": TARGET_EOS,
    "truncation": "reject", "generation_fallback": "none",
}


class CodecError(ValueError):
    """Unrepresentable, malformed, unknown, or oversized codec input."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _tag(field):
    return _json(["field", field])


def _end(field):
    return _json(["end", field])


def _atom(field, value):
    return _json(["atom", field, value])


_STRUCTURAL = ("<pad>", "<bos>", "<eos>") + tuple(
    item for field in FIELDS for item in ((_tag(field), _end(field)) if field in QUALIFIERS else (_tag(field),)))


def _source_tokens(text):
    if type(text) is not str or not text.strip() or len(text) > 16384:
        raise CodecError("source_text must be nonempty text of at most 16384 characters")
    tokens = _SOURCE_RE.findall(text.casefold())
    if not tokens or len(tokens) > MAX_SOURCE_TOKENS:
        raise CodecError("source exceeds 64 tokens; truncation is forbidden")
    if any(len(token) > 512 for token in tokens):
        raise CodecError("source lexeme exceeds 512 characters")
    return tokens


def _rule(canonical_ir):
    if type(canonical_ir) is not dict or set(canonical_ir) != {"rules"}:
        raise CodecError("canonical_ir must contain exactly rules")
    rules = canonical_ir["rules"]
    if type(rules) is not list or len(rules) != 1 or type(rules[0]) is not dict:
        raise CodecError("v1 requires exactly one rule in a rules list")
    rule = rules[0]
    if set(rule) != set(FIELDS):
        raise CodecError("rule must contain exactly the seven canonical facets")
    if any(type(rule[field]) is not str for field in SCALARS):
        raise CodecError("scalar facets require exact strings")
    for field in QUALIFIERS:
        values = rule[field]
        if type(values) is not list or len(values) > MAX_QUALIFIERS or any(type(v) is not str for v in values):
            raise CodecError("qualifier facets require at most four exact string atoms")
        if values != sorted(set(values)):
            raise CodecError("qualifier atoms must already be sorted and unique; normalization is forbidden")
    try:
        validated = CanonicalRoundTripIR.from_dict(canonical_ir).to_dict()
    except (CanonicalContractError, TypeError, ValueError) as error:
        raise CodecError("canonical rule validation failed: " + str(error)) from error
    if validated != canonical_ir:
        raise CodecError("canonical validation would change the supplied IR")
    # PGIR's rule schema uses spelled-out modality and subject. This explicit
    # validation projection is never emitted in place of the canonical payload.
    projected = {"rules": [{**rule, "modality": _MODALITIES[rule["modality"]], "subject": rule["actor"]}]}
    result = LegalIRGrammarDecoder().validate(projected, family="deontic")
    if not result.accepted:
        reasons = ",".join(reason.reason for reason in result.rejection_reasons)
        raise CodecError("deontic grammar rejected rule: " + reasons)
    return rule


@lru_cache(maxsize=16)
def _vocabularies(source, target):
    """Compile immutable vocabulary tuples; repeated generation stays cheap."""
    if source[:2] != ("<pad>", "<unk>") or len(source) < 3:
        raise CodecError("source vocabulary must start with PAD0 and UNK1 and contain training tokens")
    if source[2:] != tuple(sorted(set(source[2:]))):
        raise CodecError("source vocabulary must have deterministic unique token order")
    if len(set(source)) != len(source) or len(set(target)) != len(target):
        raise CodecError("vocabulary entries must be unique")
    for token in source[2:]:
        if _source_tokens(token) != [token]:
            raise CodecError("source vocabulary entry is not one casefolded token")
    if target[:len(_STRUCTURAL)] != _STRUCTURAL:
        raise CodecError("target special IDs or structural grammar tags differ")
    atoms = target[len(_STRUCTURAL):]
    if atoms != tuple(sorted(set(atoms))):
        raise CodecError("target atom vocabulary must have deterministic unique token order")
    by_field = {field: [] for field in FIELDS}
    decoded = {}
    for token_id, token in enumerate(target[len(_STRUCTURAL):], len(_STRUCTURAL)):
        try:
            row = json.loads(token)
        except (ValueError, TypeError) as error:
            raise CodecError("target atom must be canonical JSON") from error
        if (type(row) is not list or len(row) != 3 or row[0] != "atom"
                or row[1] not in FIELDS or type(row[2]) is not str or _json(row) != token):
            raise CodecError("target atom must be an exact typed field/string tuple")
        field, value = row[1:]
        trial = {"modality": "O", "actor": "agent", "action": "act", "object": "",
                 "conditions": [], "exceptions": [], "temporal": []}
        trial[field] = [value] if field in QUALIFIERS else value
        _rule({"rules": [trial]})
        by_field[field].append((token_id, value))
        decoded[token_id] = (field, value)
    if any(not by_field[field] for field in SCALARS):
        raise CodecError("each scalar field requires at least one training atom")
    return ({token: index for index, token in enumerate(source)},
            {token: index for index, token in enumerate(target)}, by_field, decoded)


def _validated(codec):
    if type(codec) is not dict or set(codec) != {"schema", "source_vocabulary", "target_vocabulary", "policy"}:
        raise CodecError("codec schema fields differ")
    if codec["schema"] != SCHEMA or type(codec["policy"]) is not dict or codec["policy"] != _POLICY:
        raise CodecError("codec version or declared policy differs")
    try:
        if _json(codec["policy"]) != _json(_POLICY):
            raise CodecError("codec policy numeric types differ")
    except (ValueError, TypeError) as error:
        raise CodecError("codec policy must be exact finite JSON") from error
    for name in ("source_vocabulary", "target_vocabulary"):
        values = codec[name]
        if type(values) is not list or not 1 <= len(values) <= MAX_VOCABULARY:
            raise CodecError("each vocabulary must be a list of at most 4096 tokens")
        if any(type(value) is not str or len(value) > 4096 for value in values):
            raise CodecError("vocabulary entries must be bounded strings")
    return _vocabularies(tuple(codec["source_vocabulary"]), tuple(codec["target_vocabulary"]))


def validate_codec(codec):
    """Validate the exact stored vocabulary, token IDs, limits and policy."""
    _validated(codec)


def fit_codec(examples):
    """Freeze vocabularies from explicitly supplied training examples only."""
    if type(examples) is not list or not 1 <= len(examples) <= MAX_EXAMPLES:
        raise CodecError("fit requires between one and 4096 training examples")
    source, target, seen = set(), set(), set()
    for example in examples:
        if type(example) is not dict or set(example) != {"id", "source_text", "canonical_ir"}:
            raise CodecError("training example requires exactly id, source_text and canonical_ir")
        identifier = example["id"]
        if type(identifier) is not str or not identifier.strip() or identifier in seen:
            raise CodecError("training example ids must be unique nonempty strings")
        seen.add(identifier)
        source.update(_source_tokens(example["source_text"]))
        rule = _rule(example["canonical_ir"])
        for field in FIELDS:
            for value in rule[field] if field in QUALIFIERS else [rule[field]]:
                target.add(_atom(field, value))
        if len(source) + 2 > MAX_VOCABULARY or len(target) + len(_STRUCTURAL) > MAX_VOCABULARY:
            raise CodecError("training vocabulary exceeds 4096 tokens")
    codec = {"schema": SCHEMA, "source_vocabulary": ["<pad>", "<unk>", *sorted(source)],
             "target_vocabulary": [*_STRUCTURAL, *sorted(target)], "policy": json.loads(_json(_POLICY))}
    validate_codec(codec)
    for example in examples:
        encode_source(codec, example["source_text"])
        encode_target(codec, example["canonical_ir"])
    return codec


def encode_source(codec, text):
    """Tokenize raw text without a compiler, target, IR or unknown fallback."""
    source_ids = _validated(codec)[0]
    tokens = _source_tokens(text)
    missing = sorted(set(tokens) - source_ids.keys())
    if missing:
        raise CodecError("source contains out-of-vocabulary tokens: " + ", ".join(repr(x) for x in missing[:8]))
    return [source_ids[token] for token in tokens]


def encode_target(codec, canonical_ir):
    target_ids = _validated(codec)[1]
    rule = _rule(canonical_ir)
    pieces = ["<bos>"]
    for field in FIELDS:
        pieces.append(_tag(field))
        pieces.extend(_atom(field, value) for value in (rule[field] if field in QUALIFIERS else [rule[field]]))
        if field in QUALIFIERS:
            pieces.append(_end(field))
    pieces.append("<eos>")
    if len(pieces) > MAX_TARGET_TOKENS:
        raise CodecError("target exceeds 64 tokens; truncation is forbidden")
    missing = [piece for piece in pieces if piece not in target_ids]
    if missing:
        raise CodecError("target contains out-of-vocabulary typed atoms")
    return [target_ids[piece] for piece in pieces]


def _prefix(codec, token_ids):
    _, target_ids, by_field, decoded = _validated(codec)
    if type(token_ids) not in (list, tuple) or len(token_ids) > MAX_TARGET_TOKENS:
        raise CodecError("target prefix must be at most 64 token IDs")
    if any(type(token) is not int or not 0 <= token < len(codec["target_vocabulary"]) for token in token_ids):
        raise CodecError("target token IDs must be exact integers in the vocabulary")
    position, mode, values, rule = 0, "bos", [], {}
    for token_id in token_ids:
        if mode == "bos":
            if token_id != TARGET_BOS:
                raise CodecError("target must begin with BOS")
            mode = "field"
        elif mode == "field":
            field = FIELDS[position]
            if token_id != target_ids[_tag(field)]:
                raise CodecError("target field order or marker differs")
            mode, values = "values", []
        elif mode == "values":
            field = FIELDS[position]
            if field in QUALIFIERS and token_id == target_ids[_end(field)]:
                rule[field] = list(values)
                position += 1
                mode = "eos" if position == len(FIELDS) else "field"
            else:
                atom = decoded.get(token_id)
                if atom is None or atom[0] != field:
                    raise CodecError("target atom belongs to another field or is structural")
                value = atom[1]
                if field in QUALIFIERS:
                    if len(values) >= MAX_QUALIFIERS or (values and value <= values[-1]):
                        raise CodecError("qualifier tokens must be sorted unique and at most four")
                    values.append(value)
                else:
                    rule[field] = value
                    position += 1
                    mode = "field"
        elif mode == "eos":
            if token_id != TARGET_EOS:
                raise CodecError("complete target requires EOS")
            mode = "done"
        else:
            raise CodecError("tokens after EOS are forbidden")
    if mode == "bos":
        allowed = [TARGET_BOS]
    elif mode == "field":
        allowed = [target_ids[_tag(FIELDS[position])]]
    elif mode == "values":
        field = FIELDS[position]
        allowed = [token_id for token_id, value in by_field[field]
                   if field in SCALARS or (len(values) < MAX_QUALIFIERS and (not values or value > values[-1]))]
        if field in QUALIFIERS:
            allowed.append(target_ids[_end(field)])
    elif mode == "eos":
        allowed = [TARGET_EOS]
    else:
        allowed = []
    return sorted(allowed), rule, mode


def allowed_token_ids(codec, prefix_ids):
    """Exact next-token grammar; an EOS-only or incomplete rule never passes."""
    return _prefix(codec, prefix_ids)[0]


def decode_target(codec, token_ids):
    """Parse a complete prediction into exact validated IR, without fallback."""
    _, rule, mode = _prefix(codec, token_ids)
    if mode != "done":
        raise CodecError("target is incomplete; all facets and EOS are required")
    result = {"rules": [rule]}
    _rule(result)
    return result


__all__ = ["SCHEMA", "CodecError", "fit_codec", "validate_codec", "encode_source", "encode_target",
           "decode_target", "allowed_token_ids", "MAX_SOURCE_TOKENS", "MAX_TARGET_TOKENS", "MAX_VOCABULARY",
           "SOURCE_PAD", "SOURCE_UNK", "TARGET_PAD", "TARGET_BOS", "TARGET_EOS"]
