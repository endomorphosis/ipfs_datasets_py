"""Exact cited or fixture slot declarations, without source-truth promotion.

Quoted bytes and caller-declared scope/review notes are reproducible evidence
inputs. Their presence does not authenticate a reviewer, establish governing
scope, discharge a premise, or prove that a chosen interpretation is correct.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from . import context_resolution as context

SCHEMA = "formalization-context-slot-binding/v1"
MODES = frozenset({"fixture_assumption", "source_cited_declaration"})
RELATIONS = frozenset({"governing_scope", "defines", "deadline_trigger", "clock_convention",
    "application_policy", "referent"})
REVIEW_METHODS = frozenset({"caller_declaration", "human_review_declared", "machine_review_declared"})
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_FALSE = {**context.AUTHORITY, "source_resolved": False, "source_binding_verified": False,
    "proof_authority": False, "execution_authority": False, "training_allowed": False,
    "reviewer_authenticated": False, "governing_scope_verified": False, "proof_executed": False,
    "assumptions_discharged": False}
_KEYS = {"schema", "slot_id", "sort", "mode", "value", "projection_ids", "bundle_sha256",
    "index_sha256", "selected_source", "slot_sha256", "citations", "citation_bindings", "scope_review",
    "reviewer_record", "fixture_assumptions", "interpretation_assumption", "producer_pins",
    "source_evidence_cited", "declaration_scope", *_FALSE}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _guard():
    context._guard_producers()
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA,
        "context_binding_producer_changed_since_import")


def _wire(value, *, maximum=262144):
    # Check shape before serializing, so oversized/deep caller values cannot
    # allocate an arbitrarily large temporary JSON string or normalize keys.
    remaining = [min(maximum, 16384)]

    def check(item, depth=0):
        remaining[0] -= 1
        _require(depth <= 32 and remaining[0] >= 0, "context_binding_json_shape_limit")
        kind = type(item)
        _require(item is None or kind in (str, bool, int, float, list, dict),
            "closed_inert_context_binding_json_required")
        if kind is str:
            _require(len(item) <= maximum, "context_binding_byte_limit")
        elif kind is list:
            for child in item:
                check(child, depth + 1)
        elif kind is dict:
            for key, child in item.items():
                _require(type(key) is str and len(key) <= maximum,
                    "string_context_binding_json_keys_required")
                check(child, depth + 1)

    check(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("bounded_inert_context_binding_json_required") from exc
    _require(len(raw) <= maximum, "context_binding_byte_limit")
    return raw


def _text(value, label, *, maximum=4096):
    _require(type(value) is str and bool(value.strip()), label)
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(label) from exc
    _require(len(raw) <= maximum, label)
    return value


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), label)


@dataclass(frozen=True, slots=True)
class ContextBindingDeclaration:
    """Canonical immutable bytes; replay is required before any consumption."""

    _bytes: bytes

    def __post_init__(self):
        _require(type(self._bytes) is bytes and len(self._bytes) <= 262144,
            "bounded_context_binding_bytes_required")
        try:
            value = json.loads(self._bytes)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise ValueError("context_binding_json_required") from exc
        _closed(value, _KEYS, "closed_context_binding_required")
        _require(value["schema"] == SCHEMA and type(value["mode"]) is str and value["mode"] in MODES,
            "context_binding_schema_or_mode_required")
        _require(all(value[key] is False for key in _FALSE), "context_binding_cannot_grant_authority")
        _require(value["declaration_scope"] == "caller_supplied_interpretation_not_source_translation",
            "explicit_context_binding_scope_required")
        _require(value["source_evidence_cited"] is (value["mode"] == "source_cited_declaration"),
            "context_citation_mode_differs")
        _require(_wire(value) == self._bytes, "canonical_context_binding_bytes_required")

    @classmethod
    def from_dict(cls, value):
        """Load an inert declaration; this does not validate its source joins."""
        return cls(_wire(value))

    def to_dict(self):
        return json.loads(self._bytes)

    @property
    def sha256(self):
        return hashlib.sha256(self._bytes).hexdigest()


def prepare_context_binding(bundle, *, index, slot_id, mode, value, citations=(),
                            scope_review=None, reviewer_record=None):
    """Declare one slot interpretation using explicit fixtures or cited bytes.

    Citations have exactly ``span_id/start_byte/end_byte/quote``; byte offsets
    are absolute within the candidate's original source. Scope review has
    ``relation/governing_scope/alternatives_disposition``. Reviewer records have
    ``reviewer_id/review_method/rationale`` and are caller declarations only.
    Fixture mode consumes the existing bundle assumption without changing it.
    """
    _guard()
    context.validate_context_bundle(bundle, index=index)
    _text(slot_id, "context_binding_slot_required", maximum=256)
    _require(type(mode) is str and mode in MODES, "unsupported_context_binding_mode")
    _require(value is not None, "context_binding_value_required")
    value = json.loads(_wire(value, maximum=4096))
    slots = [s for s in bundle["slots"] if s["slot_id"] == slot_id]
    _require(len(slots) == 1, "selected_context_slot_required")
    slot = slots[0]
    _require(type(citations) in (list, tuple) and len(citations) <= 16, "bounded_context_citations_required")
    cited, normalized, seen, quote_bytes = [], [], set(), 0
    if mode == "fixture_assumption":
        _require(slot["assumption"] is not None and _wire(value) == _wire(slot["assumption"]["value"]),
            "fixture_binding_differs_from_bundle_assumption")
        _require(not citations and scope_review is None and reviewer_record is None,
            "fixture_binding_cannot_claim_source_review")
    else:
        _require(bool(citations), "source_cited_binding_requires_quotes")
        _closed(scope_review, {"relation", "governing_scope", "alternatives_disposition"},
            "closed_context_scope_review_required")
        _require(type(scope_review["relation"]) is str and scope_review["relation"] in RELATIONS,
            "unsupported_context_scope_relation")
        for key in ("governing_scope", "alternatives_disposition"):
            _text(scope_review[key], "explicit_" + key + "_required")
        _closed(reviewer_record, {"reviewer_id", "review_method", "rationale"},
            "closed_declared_reviewer_record_required")
        _text(reviewer_record["reviewer_id"], "declared_reviewer_id_required", maximum=256)
        _text(reviewer_record["rationale"], "declared_review_rationale_required")
        _require(type(reviewer_record["review_method"]) is str and reviewer_record["review_method"] in REVIEW_METHODS,
            "explicit_declared_review_method_required")
        for citation in citations:
            _closed(citation, {"span_id", "start_byte", "end_byte", "quote"}, "closed_context_citation_required")
            _text(citation["span_id"], "context_citation_span_required", maximum=256)
            hits = [h for h in slot["candidates"] if h["span_id"] == citation["span_id"]]
            _require(len(hits) == 1, "citation_must_be_retrieved_candidate_for_slot")
            candidate = bundle["artifacts"][hits[0]["artifact_sha256"]]
            start, end = citation["start_byte"], citation["end_byte"]
            span = candidate["span"]
            _require(type(start) is int and type(end) is int and
                span["start_byte"] <= start < end <= span["end_byte"], "quote_outside_candidate_span")
            quote = _text(citation["quote"], "bounded_exact_quote_required")
            excerpt = candidate["text"].encode("utf-8")
            raw = excerpt[start - span["start_byte"]:end - span["start_byte"]]
            try:
                exact_quote = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("quote_splits_unicode") from exc
            _require(exact_quote == quote, "citation_quote_differs_from_exact_source_bytes")
            identity = (citation["span_id"], start, end)
            _require(identity not in seen, "duplicate_context_citation")
            seen.add(identity)
            quote_bytes += len(raw)
            _require(quote_bytes <= 16384, "context_quote_byte_limit")
            normalized.append(json.loads(_wire(citation)))
            cited.append({"citation": json.loads(_wire(citation)), "quote_sha256": hashlib.sha256(raw).hexdigest(),
                "candidate_artifact_sha256": hits[0]["artifact_sha256"], "source_ref": candidate["source_ref"],
                "source_span": span, "partition": candidate["partition"],
                "source_review_is_semantic_authority": False, "governing_scope_verified": False})
    fixtures = []
    for item in bundle["slots"]:
        if item["assumption"] is not None:
            changed = item["slot_id"] == slot_id and _wire(item["assumption"]["value"]) != _wire(value)
            fixtures.append({"slot_id": item["slot_id"], "assumption": item["assumption"],
                "assumption_sha256": context.context_digest(item["assumption"]), "discharged": False,
                "status": "superseded_not_discharged" if changed else "retained_not_discharged"})
    report = {"schema": SCHEMA, "slot_id": slot_id, "sort": slot["sort"], "mode": mode, "value": value,
        "projection_ids": slot["projection_ids"], "bundle_sha256": bundle["bundle_sha256"],
        "index_sha256": index.index_sha256, "selected_source": bundle["selected_source"],
        "slot_sha256": context.context_digest(slot), "citations": normalized, "citation_bindings": cited,
        "scope_review": scope_review, "reviewer_record": reviewer_record, "fixture_assumptions": fixtures,
        "interpretation_assumption": {"slot_id": slot_id, "value": value, "discharged": False,
            "scope": "caller_interpretation_not_verified_source_fact"},
        "source_evidence_cited": mode == "source_cited_declaration",
        "declaration_scope": "caller_supplied_interpretation_not_source_translation",
        "producer_pins": {**context._PRODUCER_PINS,
            "logic/formalization/context_slot_bindings.py": _SOURCE_SHA}, **_FALSE}
    result = ContextBindingDeclaration.from_dict(report)
    _guard()
    return result


def validate_context_binding(declaration, *, bundle, index):
    """Replay exact source joins and declarations; never infer semantic truth."""
    _require(type(declaration) is ContextBindingDeclaration, "immutable_context_binding_required")
    value = declaration.to_dict()
    expected = prepare_context_binding(bundle, index=index, **{key: value[key] for key in
        ("slot_id", "mode", "value", "citations", "scope_review", "reviewer_record")})
    _require(expected._bytes == declaration._bytes, "context_binding_differs_from_source_replay")
    return True


__all__ = ["SCHEMA", "ContextBindingDeclaration", "prepare_context_binding", "validate_context_binding"]
