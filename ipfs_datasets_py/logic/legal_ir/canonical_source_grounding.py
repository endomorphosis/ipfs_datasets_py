"""Opt-in exact source anchors and proposal transport checks.

This controlled-English extension preserves the existing compiler and decoder
owners. Parser-derived canonical symbols and their literal source anchors are
different fields. Neither successful grounding nor transport compatibility
establishes independently reviewed meaning, decoder quality, or proof authority.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import canonical_explicit_qualifiers as grammar
from .canonical_contracts import CompilerRequest, OperationStatus
from .canonical_decoder_preflight import analyze_decoder_source, validate_decoder_preflight

SCHEMA = "canonical-decoder-source-grounding/v1"
TRANSPORT_SCHEMA = "canonical-decoder-proposal-transport/v1"
PROFILE = "explicit-qualifier-exact-source-anchors/v1"
DECODER_PROFILES = (
    "retained-native768-literal-span/v1",
    "retained-native768-fixed-codec/v1",
    "anchored-canonical-proposal/v1",
)
_QUALIFIERS = ("conditions", "exceptions", "temporal")
_OPERATORS = {"conditions": "all", "exceptions": "any", "temporal": "all"}
_FALSE = {"target_access": False, "model_executed": False,
          "source_fidelity_established": False, "qualified": False, "proof_authority": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _seal(value):
    return {**value, "content_sha256": _digest(value)}


def _normalize_with_offsets(source):
    """Apply the existing ASCII grammar normalization, retaining original indices."""
    body, offsets = [], []
    for match in re.finditer(r"\S+", source):
        if body:
            body.append(" ")
            offsets.append(match.start() - 1)
        for index in range(match.start(), match.end()):
            body.append(source[index].lower())
            offsets.append(index)
    normalized = "".join(body)
    if normalized.endswith("."):
        normalized = normalized[:-1].rstrip()
        offsets = offsets[:len(normalized)]
    return normalized, offsets


def _trim(body, start, end):
    while start < end and body[start].isspace():
        start += 1
    while end > start and body[end - 1].isspace():
        end -= 1
    return start, end


def _regions(body):
    """Locate clauses only after the unchanged complete parser has succeeded."""
    core_start, leading = 0, None
    if body.startswith("if "):
        comma = body.index(",")
        leading = _trim(body, 3, comma)
        core_start = comma + 1
    markers = list(re.finditer(r"\b(if|unless)\b", body[core_start:]))
    bounds = [(match.group(), core_start + match.start(), core_start + match.end()) for match in markers]
    core_end = bounds[0][1] if bounds else len(body)
    core_start, core_end = _trim(body, core_start, core_end)
    if core_end > core_start and body[core_end - 1] == ",":
        core_start, core_end = _trim(body, core_start, core_end - 1)
    result = {"core": (core_start, core_end), "conditions": leading, "exceptions": None}
    for index, (kind, _, marker_end) in enumerate(bounds):
        clause_end = bounds[index + 1][1] if index + 1 < len(bounds) else len(body)
        start, end = _trim(body, marker_end, clause_end)
        if end > start and body[end - 1] == ",":
            start, end = _trim(body, start, end - 1)
        result["conditions" if kind == "if" else "exceptions"] = (start, end)
    return result


def _prefix(body, cursor, end, atom, facet):
    cursor, end = _trim(body, cursor, end)
    matches = []
    for surface in grammar._surfaces(atom, facet):
        stop = cursor + len(surface)
        if body[cursor:stop] == surface and stop <= end and (stop == end or body[stop] == " "):
            matches.append((cursor, stop))
    return matches


def _make_anchor(source, offsets, field_path, facet, symbol, start, end):
    _require(start < end, "empty source anchor")
    left, right = offsets[start], offsets[end - 1] + 1
    return {"field_path": field_path, "facet": facet, "canonical_symbol": symbol,
            "start": left, "end": right, "source_text": source[left:right],
            "offset_unit": "unicode_character_half_open"}


def _qualifier_anchors(source, body, offsets, region, facet, atoms):
    if not atoms:
        _require(region is None or not body[region[0]:region[1]], "unaccounted qualifier source")
        return []
    _require(region is not None, "qualifier source region missing")
    start, end = region
    connector = " or " if facet == "exceptions" else " and "
    parts, cursor = [], start
    for match in re.finditer(re.escape(connector), body[start:end]):
        boundary = start + match.start()
        parts.append(_trim(body, cursor, boundary))
        cursor = start + match.end()
    parts.append(_trim(body, cursor, end))
    anchors, seen = [], set()
    for left, right in parts:
        matches = [atom for atom in atoms if body[left:right] in grammar._surfaces(atom, facet)]
        _require(len(matches) == 1 and matches[0] not in seen, "ambiguous qualifier grounding")
        atom = matches[0]
        seen.add(atom)
        anchors.append(_make_anchor(source, offsets, f"/rules/0/{facet}/{atoms.index(atom)}",
                                    facet, atom, left, right))
    _require(seen == set(atoms), "qualifier anchors do not cover the complete proposal")
    return anchors


def _anchors(source, rule):
    body, offsets = _normalize_with_offsets(source)
    regions = _regions(body)
    core_start, core_end = regions["core"]
    plans = []
    for actor_start, actor_end in _prefix(body, core_start, core_end, rule.actor, "actor"):
        modal_start, _ = _trim(body, actor_end, core_end)
        for surface, modality in grammar._MODALS:
            modal_end = modal_start + len(surface)
            if (modality != rule.modality or body[modal_start:modal_end] != surface
                    or modal_end >= core_end or body[modal_end] != " "):
                continue
            for action_start, action_end in _prefix(body, modal_end, core_end, rule.action, "action"):
                objects = _prefix(body, action_end, core_end, rule.object, "object") if rule.object else [(action_end, action_end)]
                for object_start, object_end in objects:
                    temporal = _trim(body, object_end, core_end)
                    temporal_region = temporal if temporal[0] < temporal[1] else None
                    try:
                        extra = _qualifier_anchors(source, body, offsets, temporal_region, "temporal", list(rule.temporal))
                    except ValueError:
                        continue
                    core = [
                        _make_anchor(source, offsets, "/rules/0/actor", "actor", rule.actor, actor_start, actor_end),
                        _make_anchor(source, offsets, "/rules/0/modality", "modality", rule.modality, modal_start, modal_end),
                        _make_anchor(source, offsets, "/rules/0/action", "action", rule.action, action_start, action_end),
                    ]
                    if rule.object:
                        core.append(_make_anchor(source, offsets, "/rules/0/object", "object", rule.object, object_start, object_end))
                    plans.append(core + extra)
    _require(len(plans) == 1, "complete parse has no unique structural grounding")
    anchors = plans[0]
    for facet in ("conditions", "exceptions"):
        anchors += _qualifier_anchors(source, body, offsets, regions[facet], facet, list(getattr(rule, facet)))
    for left, right in zip(sorted(anchors, key=lambda anchor: anchor["start"]),
                           sorted(anchors, key=lambda anchor: anchor["start"])[1:], strict=False):
        _require(left["end"] <= right["start"], "source anchors overlap")
    return sorted(anchors, key=lambda anchor: anchor["field_path"])


def construct_grounded_source(request, *, context_text="", requires_context_resolution=False):
    """Construct a grammar proposal from source and caller-declared vocabulary only."""
    _require(isinstance(request, CompilerRequest), "bound CompilerRequest required")
    _require(not dict(request.config) and request.allow_explicit_partial is False,
             "grounding accepts no overrides or partial projection")
    preflight = analyze_decoder_source(request.source_text, context_text=context_text,
                                       requires_context_resolution=requires_context_resolution)
    result, anchors, candidate, outcome = None, [], None, "source_blocked"
    if preflight["outcome"] == "unassessed":
        result = grammar.ExplicitQualifierCanonicalCompiler().compile(request)
        outcome = "proposal_unavailable"
        if result.status is OperationStatus.SUCCESS:
            _require(len(result.canonical_ir.rules) == 1, "single-rule source profile required")
            anchors = _anchors(request.source_text, result.canonical_ir.rules[0])
            candidate = result.canonical_ir.to_dict()
            outcome = "grounded_candidate"
    return _seal({"schema": SCHEMA, "profile": PROFILE, "request": request.to_dict(),
                  "explicit_compiler_config_cid": grammar.EXPLICIT_QUALIFIER_CONFIG_CID,
                  "preflight": preflight, "outcome": outcome,
                  "compiler_result": None if result is None else result.to_dict(),
                  "canonical_ir": candidate, "anchors": anchors,
                  "facet_operators": dict(_OPERATORS), "single_rule_scope": True,
                  "context_applied": False, "partial_projection": False,
                  "normalization_scope": "existing_declared_controlled_english_atom_surfaces",
                  "semantic_scope": "opaque_named_atoms_with_explicit_flat_connectives", **_FALSE})


def validate_grounded_source(record):
    """Replay the deterministic source construction, including exact anchor offsets."""
    _require(type(record) is dict and record.get("schema") == SCHEMA, "grounding schema required")
    request = CompilerRequest.from_dict(record.get("request"))
    validate_decoder_preflight(record.get("preflight"))
    context = record["preflight"]["context"]
    expected = construct_grounded_source(request, context_text=context["text"],
                                         requires_context_resolution=context["requires_resolution"])
    _require(_raw(record) == _raw(expected), "grounding differs from complete source construction")
    return expected


def _minimum_codec_tokens(text, tokens):
    """Bounded word-break reachability for the actual serialized proposal."""
    _require(len(text) <= 65_536, "serialized proposal exceeds codec assay bound")
    usable = tuple(sorted(set(tokens), key=lambda token: (len(token), token)))
    shortest = [None] * (len(text) + 1)
    shortest[0] = 0
    by_first = {}
    for token in usable:
        by_first.setdefault(token[0], []).append(token)
    attempts = 0
    for index in range(len(text)):
        count = shortest[index]
        if count is None:
            continue
        for token in by_first.get(text[index], ()):
            attempts += 1
            _require(attempts <= 1_048_576, "codec tokenization search bound exceeded")
            end = index + len(token)
            if text.startswith(token, index) and (shortest[end] is None or shortest[end] > count + 1):
                shortest[end] = count + 1
    return shortest[-1]


def assess_decoder_transport(record, *, decoder_profile, codec_tokens=None, output_cap=512):
    """Check a source-constructed proposal's transport, never an authored target.

    Compatibility is scoped to this source proposal and the named static output
    contract. It does not select a checkpoint or accept a generated candidate.
    """
    validate_grounded_source(record)
    _require(decoder_profile in DECODER_PROFILES, "unknown decoder transport profile")
    _require(type(output_cap) is int and 3 <= output_cap <= 4096, "bounded configured output cap required")
    if decoder_profile == DECODER_PROFILES[1]:
        _require(type(codec_tokens) is list and 4 <= len(codec_tokens) <= 4096
                 and all(type(token) is str and 0 < len(token) <= 4096 for token in codec_tokens),
                 "bounded saved token vocabulary required")
        _require(len(codec_tokens) == len(set(codec_tokens)), "codec tokens must be unique")
        _require(codec_tokens[:3] == ["<pad>", "<bos>", "<eos>"], "fixed-codec special token IDs differ")
        _require(sum(len(token.encode()) for token in codec_tokens) <= 1_048_576,
                 "saved token vocabulary exceeds byte bound")
    else:
        _require(codec_tokens is None, "codec tokens apply only to fixed-codec transport")
    issues, minimum = [], None
    outcome = record["outcome"]
    if outcome == "grounded_candidate":
        outcome = "transport_compatible"
        rule = record["canonical_ir"]["rules"][0]
        if decoder_profile == DECODER_PROFILES[0]:
            source = record["request"]["source_text"]
            lexical = list(re.finditer(r"\w+|[^\w\s]", source))
            starts, ends = {match.start() for match in lexical}, {match.end() for match in lexical}
            if len(lexical) > 256 or any(len(match.group().casefold().encode()) > 2048 for match in lexical):
                issues.append({"code": "literal_span.source_encoding_bound", "field_path": None})
            for facet in _QUALIFIERS:
                if len(rule[facet]) > 1:
                    issues.append({"code": "literal_span.multiple_qualifier_atoms", "field_path": f"/rules/0/{facet}"})
            spans = []
            for anchor in record["anchors"]:
                if anchor["facet"] == "modality":
                    continue
                atom, locations = anchor["canonical_symbol"], []
                for match in re.finditer(re.escape(atom), source):
                    if match.start() in starts and match.end() in ends:
                        locations.append((match.start(), match.end()))
                if len(locations) != 1:
                    issues.append({"code": "literal_span.atom_absent" if not locations else "literal_span.ambiguous_mention",
                                   "field_path": anchor["field_path"]})
                else:
                    spans.append(locations[0])
            ordered = sorted(spans)
            if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:], strict=False)):
                issues.append({"code": "literal_span.overlapping_fields", "field_path": None})
        elif decoder_profile == DECODER_PROFILES[1]:
            serialized = _raw(record["canonical_ir"]).decode()
            minimum = _minimum_codec_tokens(serialized, codec_tokens[3:])
            if minimum is None:
                issues.append({"code": "fixed_codec.serialized_proposal_unrepresentable", "field_path": None})
            elif minimum + 2 > output_cap:
                issues.append({"code": "fixed_codec.BOS_content_EOS_exceeds_output_cap", "field_path": None})
        if issues:
            outcome = "unsupported_transport"
    return _seal({"schema": TRANSPORT_SCHEMA, "grounding_sha256": record["content_sha256"],
                  "decoder_profile": decoder_profile, "outcome": outcome, "issues": issues,
                  "codec_tokens_sha256": None if codec_tokens is None else _digest(codec_tokens),
                  "configured_output_cap": output_cap, "minimum_content_tokens": minimum,
                  "assessment_scope": "source_constructed_proposal_transport_only",
                  "generated_candidate_assessed": False, "checkpoint_selected": False, **_FALSE})


def validate_decoder_transport(transport, grounding, *, codec_tokens=None):
    """Reject stale or modified transport receipts even when they were resealed."""
    _require(type(transport) is dict and transport.get("schema") == TRANSPORT_SCHEMA,
             "decoder transport schema required")
    expected = assess_decoder_transport(grounding, decoder_profile=transport.get("decoder_profile"),
                                        codec_tokens=codec_tokens, output_cap=transport.get("configured_output_cap"))
    _require(_raw(transport) == _raw(expected), "transport differs from source proposal and output contract")
    return expected
