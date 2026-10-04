"""Opt-in bounded UTF8 transport for unaccepted source-anchored proposals.

The fixed byte alphabet separates canonical symbols from exact source spans.
Validation establishes closed structure, occurrence joins and transport only;
it cannot establish whether a symbol or modality means what its span says.
No grammar, vocabulary, numerical model or prover is consulted here.
"""
from __future__ import annotations

import hashlib
import json

PROPOSAL_SCHEMA = "canonical-anchored-byte-proposal/v1"
WIRE_SCHEMA = "canonical-anchored-byte-wire/v1"
INSPECTION_SCHEMA = "canonical-anchored-byte-encoding-inspection/v1"
CODEC_PROFILE = "utf8-byte259-canonical-anchored/v1"
PAD_ID, BOS_ID, EOS_ID = 0, 1, 2
BYTE_OFFSET, VOCAB_SIZE = 3, 259
DEFAULT_OUTPUT_CAP = 4096
MAX_PAYLOAD_BYTES = 32_768
MAX_SOURCE_CHARS = 16_384
MAX_ATOM_CHARS = 512
MAX_QUALIFIERS_PER_FACET = 64
MAX_JSON_DEPTH = 16
_OPERATORS = {"conditions": "all", "exceptions": "any", "temporal": "all"}
_FALSE = {field: False for field in (
    "target_access", "model_executed", "source_fidelity_established", "qualified",
    "proof_authority", "accepted")}
_PROPOSAL_FIELDS = {"schema", "source_sha256", "canonical_ir", "anchors",
                    "facet_operators", "single_rule_scope", *_FALSE}
_WIRE_FIELDS = {"schema", "source_sha256", "canonical_ir", "anchors"}
_RULE_FIELDS = {"actor", "action", "modality", "object", *_OPERATORS}
_ANCHOR_FIELDS = {"field_path", "facet", "canonical_symbol", "start", "end",
                  "source_text", "offset_unit"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, expected, field):
    _require(type(value) is dict and set(value) == expected,
             field + " has unknown or missing fields")


def _text(value, maximum, field, *, allow_empty=False):
    _require(type(value) is str and len(value) <= maximum
             and (value == "" and allow_empty or bool(value.strip())),
             field + " must be bounded nonblank text" + (" or empty" if allow_empty else ""))
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(field + " must be valid UTF8 text") from error


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("strict finite UTF8 JSON required") from error


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _hash(value, field):
    _require(type(value) is str and len(value) == 64
             and all(character in "0123456789abcdef" for character in value),
             field + " must be lowercase SHA256")


def _output_cap(value):
    _require(type(value) is int and 3 <= value <= MAX_PAYLOAD_BYTES + 2,
             "output_cap must be an integer from 3 to 32770")
    return value


def _canonical_ir(value):
    """Check canonical shape without repairing, sorting or interpreting atoms."""
    _keys(value, {"rules"}, "canonical_ir")
    _require(type(value["rules"]) is list and len(value["rules"]) == 1,
             "exactly one complete flat rule required")
    rule = value["rules"][0]
    _keys(rule, _RULE_FIELDS, "canonical rule")
    for facet in ("actor", "action", "modality", "object"):
        _text(rule[facet], MAX_ATOM_CHARS, facet, allow_empty=facet == "object")
    _require(rule["modality"] in ("O", "P", "F"), "modality must be O, P or F")
    for facet in _OPERATORS:
        atoms = rule[facet]
        _require(type(atoms) is list and len(atoms) <= MAX_QUALIFIERS_PER_FACET,
                 facet + " must be a bounded qualifier list")
        for atom in atoms:
            _text(atom, MAX_ATOM_CHARS, facet + " atom")
        _require(atoms == sorted(set(atoms)), facet + " must already be sorted and unique")
    # The validated values contain only exact dictionaries, lists and strings.
    return json.loads(_raw(value))


def _leaves(canonical_ir):
    rule = canonical_ir["rules"][0]
    result = {}
    for facet in ("actor", "action", "modality", "object"):
        if facet != "object" or rule[facet]:
            result["/rules/0/" + facet] = (facet, rule[facet])
    for facet in _OPERATORS:
        for index, symbol in enumerate(rule[facet]):
            result[f"/rules/0/{facet}/{index}"] = (facet, symbol)
    return dict(sorted(result.items()))


def _anchor(source_text, path, facet, symbol, start, end):
    _require(type(start) is int and type(end) is int
             and 0 <= start < end <= len(source_text),
             "anchor offsets must be exact nonempty source character spans")
    return {"field_path": path, "facet": facet, "canonical_symbol": symbol,
            "start": start, "end": end, "source_text": source_text[start:end],
            "offset_unit": "unicode_character_half_open"}


def _anchors(value, canonical_ir, source_text, *, compact=False):
    leaves = _leaves(canonical_ir)
    _require(type(value) is list and len(value) == len(leaves),
             "anchors must cover every canonical leaf exactly once")
    result = []
    for item, (path, (facet, symbol)) in zip(value, leaves.items(), strict=True):
        if compact:
            _require(type(item) is list and len(item) == 3,
                     "wire anchor must be a path/start/end triple")
            observed_path, start, end = item
        else:
            _keys(item, _ANCHOR_FIELDS, "source anchor")
            observed_path, start, end = item["field_path"], item["start"], item["end"]
        _require(type(observed_path) is str and observed_path == path,
                 "anchors must follow complete sorted canonical leaf paths")
        expected = _anchor(source_text, path, facet, symbol, start, end)
        if not compact:
            _require(_raw(item) == _raw(expected), "anchor does not match canonical leaf and exact source occurrence")
        result.append(expected)
    ordered = sorted(result, key=lambda item: item["start"])
    _require(all(left["end"] <= right["start"] for left, right in zip(ordered, ordered[1:], strict=False)),
             "source anchors must not overlap")
    return result


def _proposal(source_sha256, canonical_ir, anchors):
    return {"schema": PROPOSAL_SCHEMA, "source_sha256": source_sha256,
            "canonical_ir": canonical_ir, "anchors": anchors,
            "facet_operators": dict(_OPERATORS), "single_rule_scope": True, **_FALSE}


def validate_proposal(proposal, source_text):
    """Return detached structure joined to exact occurrences, not reviewed meaning."""
    source_bytes = _text(source_text, MAX_SOURCE_CHARS, "source_text")
    _keys(proposal, _PROPOSAL_FIELDS, "source-anchored proposal")
    _require(proposal["schema"] == PROPOSAL_SCHEMA, "source-anchored proposal schema differs")
    _hash(proposal["source_sha256"], "source_sha256")
    _require(proposal["source_sha256"] == _sha(source_bytes), "source SHA256 differs")
    _keys(proposal["facet_operators"], set(_OPERATORS), "facet operators")
    _require(proposal["facet_operators"] == _OPERATORS, "fixed flat facet operators differ")
    _require(proposal["single_rule_scope"] is True, "single-rule scope must remain true")
    _require(all(proposal[field] is False for field in _FALSE), "proposal authority flags must remain false")
    canonical_ir = _canonical_ir(proposal["canonical_ir"])
    anchors = _anchors(proposal["anchors"], canonical_ir, source_text)
    return _proposal(proposal["source_sha256"], canonical_ir, anchors)


def _wire(proposal, source_text):
    validated = validate_proposal(proposal, source_text)
    wire = {"schema": WIRE_SCHEMA, "source_sha256": validated["source_sha256"],
            "canonical_ir": validated["canonical_ir"],
            "anchors": [[item["field_path"], item["start"], item["end"]] for item in validated["anchors"]]}
    payload = _raw(wire)
    _require(len(payload) <= MAX_PAYLOAD_BYTES, "wire payload exceeds 32768-byte hard bound; no truncation performed")
    return validated, payload


def inspect_encoding(proposal, source_text, *, output_cap=DEFAULT_OUTPUT_CAP):
    """Assess fixed-byte capacity only; never truncate or select model weights."""
    cap = _output_cap(output_cap)
    validated, payload = _wire(proposal, source_text)
    count = len(payload) + 2
    available = count <= cap
    result = {"schema": INSPECTION_SCHEMA, "codec_profile": CODEC_PROFILE,
              "source_sha256": validated["source_sha256"], "proposal_sha256": _sha(_raw(validated)),
              "wire_sha256": _sha(payload), "vocabulary_size": VOCAB_SIZE,
              "payload_bytes": len(payload), "content_token_count": len(payload),
              "required_token_count": count, "configured_output_cap": cap,
              "outcome": "encoding_admitted" if available else "encoding_unavailable",
              "reason": None if available else "BOS_content_EOS_exceeds_output_cap",
              "assessment_scope": "exact_structural_proposal_transport_only",
              "truncation_performed": False, "checkpoint_selected": False, **_FALSE}
    return {**result, "content_sha256": _sha(_raw(result))}


def encode_proposal(proposal, source_text, *, output_cap=DEFAULT_OUTPUT_CAP):
    """Encode the complete canonical wire or raise instead of truncating."""
    cap = _output_cap(output_cap)
    _, payload = _wire(proposal, source_text)
    _require(len(payload) + 2 <= cap, "BOS/content/EOS exceeds output_cap; no truncation performed")
    return [BOS_ID, *(byte + BYTE_OFFSET for byte in payload), EOS_ID]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def _json_depth(text):
    """Bound parser nesting before loading; strings and escapes hide brackets."""
    depth, quoted, escaped = 0, False, False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            _require(depth <= MAX_JSON_DEPTH, "JSON nesting exceeds depth16 hard bound")
        elif character in "]}":
            depth -= 1
            _require(depth >= 0, "unbalanced JSON delimiters")
    _require(depth == 0 and not quoted, "incomplete JSON string or delimiters")


def decode_proposal(token_ids, source_text, *, output_cap=DEFAULT_OUTPUT_CAP):
    """Decode a complete bounded wire and reconstruct exact public anchors.

    This validates the generated structure and supplied source occurrences. An
    internally consistent wrong symbol/span assignment can still pass; there is
    no semantic alias oracle or proof acceptance in this codec.
    """
    cap = _output_cap(output_cap)
    source_bytes = _text(source_text, MAX_SOURCE_CHARS, "source_text")
    _require(type(token_ids) in (list, tuple) and 3 <= len(token_ids) <= cap,
             "complete token sequence must fit configured output_cap")
    _require(all(type(token) is int and 0 <= token < VOCAB_SIZE for token in token_ids),
             "token IDs must be exact integers in the fixed 259-token alphabet")
    _require(token_ids[0] == BOS_ID and token_ids[-1] == EOS_ID,
             "complete BOS/content/EOS framing required")
    content = token_ids[1:-1]
    _require(all(BYTE_OFFSET <= token < VOCAB_SIZE for token in content),
             "content cannot contain padding, BOS or EOS IDs")
    payload = bytes(token - BYTE_OFFSET for token in content)
    _require(len(payload) <= MAX_PAYLOAD_BYTES, "wire payload exceeds 32768-byte hard bound")
    try:
        text = payload.decode("utf-8")
        _json_depth(text)
        wire = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, OverflowError) as error:
        raise ValueError("complete strict bounded UTF8 JSON required") from error
    _keys(wire, _WIRE_FIELDS, "byte wire")
    _require(wire["schema"] == WIRE_SCHEMA, "byte wire schema differs")
    _hash(wire["source_sha256"], "source_sha256")
    _require(wire["source_sha256"] == _sha(source_bytes), "wire source SHA256 differs")
    canonical_ir = _canonical_ir(wire["canonical_ir"])
    anchors = _anchors(wire["anchors"], canonical_ir, source_text, compact=True)
    _require(payload == _raw(wire), "wire must use the exact canonical UTF8 JSON serialization")
    return _proposal(wire["source_sha256"], canonical_ir, anchors)


__all__ = ["validate_proposal", "inspect_encoding", "encode_proposal", "decode_proposal"]
