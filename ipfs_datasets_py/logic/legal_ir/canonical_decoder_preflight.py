"""Source-only warnings for a separately versioned flat decoder profile.

Patterns diagnose a few explicit unsupported or unresolved constructions. Their
absence leaves representability unassessed. This is neither a general semantic
parser nor an acceptance gate, and it never resolves supplied context. Offsets
refer to the exact source, including its original case and whitespace.
"""
from __future__ import annotations

import hashlib
import json
import re

from .canonical_source_guards import _quoted_mask, analyze_canonical_source

SCHEMA = "canonical-decoder-source-preflight/v1"
SOURCE_PROFILE = "flat-single-rule-deontic-english/v1"
MAX_SOURCE_CHARS = 65_536
MAX_PROFILE_CHARS = 16_384
MAX_CONTEXT_CHARS = 2_000
MAX_DIAGNOSTICS = 256
_FLAGS = ("target_access", "model_executed", "source_fidelity_established", "qualified", "proof_authority")
_FIELDS = {"schema", "source_text", "source_sha256", "context", "source_profile", "outcome",
           "diagnostics", "content_sha256", *_FLAGS}
_CONTEXT_FIELDS = {"text", "sha256", "requires_resolution", "applied"}
_DIAGNOSTIC_FIELDS = {"code", "message", "start", "end", "source_text"}
_BOUNDARY = re.compile(r"[.!?;]")
_NORMATIVE = re.compile(
    r"\b(?:must(?:\s+not)?|shall(?:\s+not)?|may|cannot|can\s+not|"
    r"(?:is|are)\s+(?:not\s+)?(?:required|obligated|allowed|permitted)\s+to|"
    r"(?:is|are)\s+prohibited\s+from|need\s+not)\b", re.IGNORECASE)
_UNIVERSAL = re.compile(r"\A\s*(?P<quantifier>every|each)\b", re.IGNORECASE)
_CARDINALITY = re.compile(
    r"\bexactly\s+(?:[0-9]+|zero|one|two|three|four|five|six|seven|eight|nine|ten)\b", re.IGNORECASE)
_NEGATED_OBLIGATION = re.compile(
    r"\b(?:(?:is|are)\s+not\s+(?:required|obligated)\s+to|need\s+not)\b", re.IGNORECASE)
_CLAUSE_MARKER = re.compile(r"\b(if|unless)\b", re.IGNORECASE)
_LINKED_VARIABLE = re.compile(
    r"\bonly\s+if\s+(?:that\s+[^,.;!?\n]{1,120}['’]s\b|(?:their|his|her|its)\b)", re.IGNORECASE)
_RELATIVE_CALENDAR = re.compile(
    r"\b(?:(?:next|last|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"tomorrow|yesterday)\b", re.IGNORECASE)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _text(value, maximum, field, *, blank=False):
    _require(type(value) is str and len(value) <= maximum and (blank or value.strip()),
             f"{field} must be {'possibly blank ' if blank else 'nonblank '}text of at most {maximum} characters")
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} must be valid UTF-8 text") from error


def _segments(text):
    start = 0
    for match in _BOUNDARY.finditer(text):
        yield start, text[start:match.start()]
        start = match.end()
    yield start, text[start:]


def analyze_decoder_source(source_text, *, context_text="", requires_context_resolution=False):
    """Return bounded profile warnings without targets, vocabulary or models.

    Quoted material is masked before pattern checks. Lexical warnings require a
    recognized deontic clause; connective checks examine suffix ``if``/``unless``
    clauses only. Unmatched or more complex syntax remains unassessed. Any
    context declaration is retained and requires separate clarification.
    """
    source_bytes = _text(source_text, MAX_SOURCE_CHARS, "source_text")
    context_bytes = _text(context_text, MAX_CONTEXT_CHARS, "context_text", blank=True)
    _require(type(requires_context_resolution) is bool, "requires_context_resolution must be boolean")
    diagnostics = []
    clarification = False

    def add(code, message, start, end, *, clarify=False):
        nonlocal clarification
        _require(0 <= start < end <= len(source_text), "diagnostic must have a nonempty source span")
        diagnostics.append({"code": code, "message": message, "start": start, "end": end,
                            "source_text": source_text[start:end]})
        _require(len(diagnostics) <= MAX_DIAGNOSTICS, "diagnostic count exceeds bound; no truncation performed")
        clarification = clarification or clarify

    if requires_context_resolution or bool(context_text):
        add("source.context_resolution_unavailable",
            "Supplied or required context is retained but this profile cannot resolve or apply it.",
            0, len(source_text), clarify=True)
        if requires_context_resolution and not context_text.strip():
            add("source.required_context_missing", "Explicit context resolution was requested without nonblank context.",
                0, len(source_text), clarify=True)
    if len(source_text) > MAX_PROFILE_CHARS:
        add("source.profile_character_bound", "Source exceeds the 16384-character decoder profile; no truncation performed.",
            0, len(source_text))
    else:
        guard = analyze_canonical_source(source_text)
        for item in guard["diagnostics"]:
            add(item["code"], item["message"], item["start"], item["end"], clarify=True)
        mask = _quoted_mask(source_text)
        unquoted = "".join(" " if mask[index] else character for index, character in enumerate(source_text))
        for base, segment in _segments(unquoted):
            modal = _NORMATIVE.search(segment)
            if modal is None:
                continue
            universal = _UNIVERSAL.search(segment)
            if universal is not None and universal.end() < modal.start():
                add("source.quantified_binding", "This flat profile does not encode explicit universal or per-entity binding.",
                    base + universal.start("quantifier"), base + universal.end("quantifier"))
            for match in _CARDINALITY.finditer(segment, modal.end()):
                add("source.quantified_cardinality", "This flat profile does not encode explicit cardinality or unique witnesses.",
                    base + match.start(), base + match.end())
            for match in _NEGATED_OBLIGATION.finditer(segment):
                add("source.negated_obligation", "Absence of obligation cannot be represented by silently choosing O, P or F.",
                    base + match.start(), base + match.end())
            for match in _LINKED_VARIABLE.finditer(segment, modal.end()):
                add("source.linked_variable_binding", "The explicit only-if possessive linkage requires variable binding outside this profile.",
                    base + match.start(), base + match.end())
            for match in _RELATIVE_CALENDAR.finditer(segment, modal.end()):
                add("source.relative_calendar_anchor", "The relative calendar expression requires an explicit reference date and interpretation.",
                    base + match.start(), base + match.end(), clarify=True)
            markers = list(_CLAUSE_MARKER.finditer(segment, modal.end()))
            if [marker.group().casefold() for marker in markers] not in (["if"], ["unless"], ["if", "unless"]):
                continue
            for index, marker in enumerate(markers):
                end = markers[index + 1].start() if index + 1 < len(markers) else len(segment)
                clause = segment[marker.end():end]
                connective = "or" if marker.group().casefold() == "if" else "and"
                for match in re.finditer(rf"\b{connective}\b", clause, re.IGNORECASE):
                    condition = connective == "or"
                    add("source.condition_disjunction" if condition else "source.exception_conjunction",
                        "This flat profile declares conjunctive conditions and disjunctive exceptions.",
                        base + marker.end() + match.start(), base + marker.end() + match.end())
    diagnostics.sort(key=lambda item: (item["start"], item["end"], item["code"]))
    result = {"schema": SCHEMA, "source_text": source_text,
              "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
              "context": {"text": context_text, "sha256": hashlib.sha256(context_bytes).hexdigest(),
                          "requires_resolution": requires_context_resolution, "applied": False},
              "source_profile": SOURCE_PROFILE,
              "outcome": "clarification_required" if clarification else "unsupported_profile" if diagnostics else "unassessed",
              "diagnostics": diagnostics, **{field: False for field in _FLAGS}}
    result["content_sha256"] = _digest(result)
    return result


def validate_decoder_preflight(record):
    """Recompute the complete detached receipt; resealing cannot change findings."""
    _require(type(record) is dict and set(record) == _FIELDS, "closed decoder preflight schema required")
    context = record["context"]
    _require(type(context) is dict and set(context) == _CONTEXT_FIELDS, "closed context schema required")
    _require(type(record["diagnostics"]) is list, "diagnostics must be a list")
    for item in record["diagnostics"]:
        _require(type(item) is dict and set(item) == _DIAGNOSTIC_FIELDS, "closed diagnostic schema required")
        _require(type(item["start"]) is int and type(item["end"]) is int,
                 "diagnostic offsets must be exact integers")
    expected = analyze_decoder_source(record["source_text"], context_text=context["text"],
                                      requires_context_resolution=context["requires_resolution"])
    _require(_raw(record) == _raw(expected), "decoder preflight differs from exact source/context recomputation")
    return expected


__all__ = ["analyze_decoder_source", "validate_decoder_preflight"]
