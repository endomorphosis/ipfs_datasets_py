"""Source-bound candidates for unresolved repeated-modal alternatives.

The records in this module preserve syntax and provenance.  They do not choose
between a disjunction of duties and a duty concerning disjunctive actions, and
none is proof-ready or evidence that legal meaning has been verified.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from .utils.deontic_parser import (
    _unresolved_duty_disjunction_groups,
    classify_modal,
    extract_condition_details,
    extract_cross_reference_details,
    extract_exception_details,
    extract_override_clause_details,
    extract_procedure_details,
    extract_temporal_constraint_inventory,
)

COORDINATION_SCHEMA_VERSION = "legal-coordination-candidate/v1"
MAX_SOURCE_CHARACTERS = 65_536
MAX_SOURCE_UTF8_BYTES = 262_144
MAX_SOURCE_ID_CHARACTERS = 512
MAX_COORDINATION_GROUPS = 64
MAX_SUPPORTED_MEMBERS = 8
INTERPRETATION_REQUIRED = "coordination_interpretation_required"
Span = tuple[int, int]

_WORDS_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*(?:\s+[A-Za-z0-9][A-Za-z0-9'’\-]*)*")
_QUALIFIER_RE = re.compile(
    r"\b(?:if|unless|except|when|where|provided|who|which|that|until|once|while|because|whether|"
    r"before|after|during|within|without|absent|notwithstanding|pursuant|under|upon|following|"
    r"pending|subject\s+to|according\s+to|in\s+accordance\s+with|in\s+case|in\s+the\s+event)\b",
    re.IGNORECASE,
)
_ACTOR_FORBIDDEN_RE = re.compile(
    r"\b(?:and|or|nor|but|either|neither|no|none|not|each|every|all|any|some|such|shall|must|may|"
    r"if|unless|except|when|where|provided|who|which|that)\b", re.IGNORECASE,
)
_AUTHORITY_PERMISSION_RE = re.compile(
    r"(?:has|have)\s+(?:the\s+)?(?:authority|power)\s+to|"
    r"(?:is|are)\s+(?:(?:delegated|granted|conferred)\s+(?:the\s+)?(?:authority|power)|"
    r"vested\s+with\s+(?:the\s+)?(?:authority|power)|empowered)\s+to",
    re.IGNORECASE,
)
_ACTION_COORDINATION_RE = re.compile(r"\b(?:and|or|nor|but|either|neither)\b", re.IGNORECASE)
_ACTION_NEGATION_RE = re.compile(r"\b(?:not|never|no|none|neither|without)\b", re.IGNORECASE)
_TEMPORAL_CUE_RE = re.compile(
    r"\b(?:before|after|within|until|during|annually|monthly|weekly|daily|immediately|promptly|"
    r"subsequently|previously|simultaneously|then|whenever|by\s+\d|on\s+\d|"
    r"no\s+later|not\s+later)\b", re.IGNORECASE,
)


def _fail(message: str) -> None:
    raise ValueError(message)


def _span_type(value: Any, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if (type(value) is not tuple or len(value) != 2
            or any(type(item) is not int for item in value)
            or not 0 <= value[0] < value[1] <= MAX_SOURCE_CHARACTERS):
        _fail("Source spans must be immutable, nonempty integer coordinate pairs")


def _string_tuple(value: Any) -> None:
    if (type(value) is not tuple or len(value) > 32
            or any(type(item) is not str or len(item) > 128 for item in value)):
        _fail("Blockers must be an immutable tuple of strings")


@dataclass(frozen=True, slots=True)
class CoordinationConnector:
    span: Span
    raw_text: str

    def __post_init__(self) -> None:
        _span_type(self.span)
        if type(self.raw_text) is not str or self.raw_text.casefold() != "or":
            _fail("A coordination connector must preserve a source 'or'")


@dataclass(frozen=True, slots=True)
class CoordinationMember:
    index: int
    span: Span
    raw_text: str
    actor: str
    actor_span: Span | None
    actor_inherited_from: int | None
    modal_text: str
    modal_span: Span
    modality: str
    action: str
    action_span: Span
    structure_supported: bool
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.index) is not int or not 0 <= self.index < MAX_SUPPORTED_MEMBERS:
            _fail("Member index is outside the bounded candidate profile")
        for span in (self.span, self.modal_span, self.action_span):
            _span_type(span)
        _span_type(self.actor_span, optional=True)
        if self.actor_inherited_from is not None and (
            type(self.actor_inherited_from) is not int
            or not 0 <= self.actor_inherited_from < self.index
        ):
            _fail("Inherited actor must refer to an earlier explicit member")
        for value in (self.raw_text, self.actor, self.modal_text, self.modality, self.action):
            if type(value) is not str or len(value) > MAX_SOURCE_CHARACTERS:
                _fail("Member evidence strings must be bounded strings")
        if self.modality not in {"O", "P", "F"} or type(self.structure_supported) is not bool:
            _fail("Invalid member modality or structural flag")
        _string_tuple(self.blockers)


@dataclass(frozen=True, slots=True)
class CoordinationGroup:
    schema_version: str
    group_id: str
    source_id: str
    source_text: str
    source_sha256: str
    evidence_sha256: str
    group_span: Span
    group_raw_text: str
    scope_span: Span
    scope_raw_text: str
    observed_member_count: int
    members: tuple[CoordinationMember, ...]
    connectors: tuple[CoordinationConnector, ...]
    structure_supported: bool
    blockers: tuple[str, ...]
    interpretation_required: bool
    source_semantics_verified: bool
    proof_ready: bool

    def __post_init__(self) -> None:
        _validate_source_input(self.source_text, self.source_id)
        for value in (self.schema_version, self.group_id, self.source_sha256, self.evidence_sha256,
                      self.group_raw_text, self.scope_raw_text):
            if type(value) is not str or len(value) > MAX_SOURCE_CHARACTERS:
                _fail("Group evidence strings must be bounded strings")
        _span_type(self.group_span)
        _span_type(self.scope_span)
        if (type(self.observed_member_count) is not int or self.observed_member_count < 2
                or self.observed_member_count > MAX_SOURCE_CHARACTERS):
            _fail("Invalid observed member count")
        if (type(self.members) is not tuple or len(self.members) > MAX_SUPPORTED_MEMBERS
                or any(type(item) is not CoordinationMember for item in self.members)):
            _fail("Group members must be a bounded immutable tuple")
        if (type(self.connectors) is not tuple or len(self.connectors) >= MAX_SUPPORTED_MEMBERS
                or any(type(item) is not CoordinationConnector for item in self.connectors)):
            _fail("Group connectors must be a bounded immutable tuple")
        if type(self.structure_supported) is not bool:
            _fail("Structural support must be a boolean")
        _string_tuple(self.blockers)
        if (self.interpretation_required is not True or self.source_semantics_verified is not False
                or self.proof_ready is not False):
            _fail("Coordination candidates always require interpretation and are never proof-ready")

    def validate(self) -> None:
        """Rebuild source evidence, rejecting altered records even with new seals."""
        validate_coordination_group(self)

    def to_dict(self) -> dict[str, Any]:
        """Export a fresh JSON-compatible mapping after source revalidation."""
        self.validate()
        return _group_payload(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CoordinationGroup:
        """Restore only an exact record reproduced from its original source."""
        if type(value) is not dict:
            _fail("A coordination record must be a plain dictionary")
        source_text, source_id = value.get("source_text"), value.get("source_id")
        _validate_source_input(source_text, source_id)
        candidates = build_coordination_groups(source_text, source_id)
        group_id = value.get("group_id")
        candidate = next((group for group in candidates if group.group_id == group_id), None)
        if candidate is None:
            _fail("No source-bound coordination group matches this identity")
        _assert_json_payload(value, _group_payload(candidate))
        return candidate


def _validate_source_input(source_text: Any, source_id: Any) -> None:
    if type(source_text) is not str or type(source_id) is not str:
        _fail("Source text and source identity must be strings")
    if len(source_text) > MAX_SOURCE_CHARACTERS or len(source_id) > MAX_SOURCE_ID_CHARACTERS:
        _fail("Source exceeds the coordination profile length limit")
    try:
        size = len(source_text.encode("utf-8"))
        source_id.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("Source must be valid UTF-8 text") from error
    if size > MAX_SOURCE_UTF8_BYTES:
        _fail("Source exceeds the coordination profile UTF-8 limit")


def _assert_json_payload(actual: Any, expected: Any) -> None:
    """Strict bounded structural equality, including bool/int and tuple/list."""
    if type(actual) is not type(expected):
        _fail("Coordination evidence has a noncanonical field type")
    if isinstance(expected, dict):
        if actual.keys() != expected.keys():
            _fail("Coordination evidence has missing or unexpected fields")
        for key in expected:
            _assert_json_payload(actual[key], expected[key])
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            _fail("Coordination evidence has an unexpected record count")
        for supplied, rebuilt in zip(actual, expected):
            _assert_json_payload(supplied, rebuilt)
    elif actual != expected:
        _fail("Coordination evidence differs from the exact source reconstruction")


def _member_payload(member: CoordinationMember) -> dict[str, Any]:
    return {
        "index": member.index, "span": list(member.span), "raw_text": member.raw_text,
        "actor": member.actor, "actor_span": list(member.actor_span) if member.actor_span is not None else None,
        "actor_inherited_from": member.actor_inherited_from, "modal_text": member.modal_text,
        "modal_span": list(member.modal_span), "modality": member.modality,
        "action": member.action, "action_span": list(member.action_span),
        "structure_supported": member.structure_supported, "blockers": list(member.blockers),
    }


def _group_payload(group: CoordinationGroup, *, include_seal: bool = True) -> dict[str, Any]:
    result = {
        "schema_version": group.schema_version, "group_id": group.group_id,
        "source_id": group.source_id, "source_text": group.source_text,
        "source_sha256": group.source_sha256,
        "group_span": list(group.group_span), "group_raw_text": group.group_raw_text,
        "scope_span": list(group.scope_span), "scope_raw_text": group.scope_raw_text,
        "observed_member_count": group.observed_member_count,
        "members": [_member_payload(member) for member in group.members],
        "connectors": [{"span": list(connector.span), "raw_text": connector.raw_text}
                       for connector in group.connectors],
        "structure_supported": group.structure_supported, "blockers": list(group.blockers),
        "interpretation_required": group.interpretation_required,
        "source_semantics_verified": group.source_semantics_verified, "proof_ready": group.proof_ready,
    }
    if include_seal:
        result["evidence_sha256"] = group.evidence_sha256
    return result


def _digest(payload: Any) -> str:
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _trim_span(source: str, start: int, end: int) -> Span:
    while start < end and source[start].isspace():
        start += 1
    while end > start and source[end - 1].isspace():
        end -= 1
    return start, end


def _member_blockers(actor: str, action: str, raw_text: str) -> tuple[str, ...]:
    blockers: list[str] = []
    if (not _WORDS_RE.fullmatch(actor) or _ACTOR_FORBIDDEN_RE.search(actor)
            or len(actor.split()) > 12):
        blockers.append("coordination_actor_structure_unsupported")
    if not _WORDS_RE.fullmatch(action) or len(action.split()) > 32:
        blockers.append("coordination_action_structure_unsupported")
    if _ACTION_COORDINATION_RE.search(action):
        blockers.append("coordination_action_coordination_unsupported")
    if _ACTION_NEGATION_RE.search(action):
        blockers.append("coordination_action_negation_unsupported")
    if (_QUALIFIER_RE.search(raw_text) or extract_condition_details(raw_text)
            or extract_exception_details(raw_text) or extract_override_clause_details(raw_text)):
        blockers.append("coordination_qualification_unsupported")
    temporal = extract_temporal_constraint_inventory(raw_text)
    if _TEMPORAL_CUE_RE.search(action) or temporal.get("retained") or temporal.get("excluded"):
        blockers.append("coordination_temporal_structure_unsupported")
    if extract_cross_reference_details(raw_text):
        blockers.append("coordination_reference_structure_unsupported")
    if extract_procedure_details(raw_text, action):
        blockers.append("coordination_procedure_structure_unsupported")
    return tuple(dict.fromkeys(blockers))


def build_coordination_groups(source_text: str, source_id: str = "") -> tuple[CoordinationGroup, ...]:
    """Build bounded, immutable unresolved candidates directly from source.

    Two through eight plain branches can expose separate actor/modal/action
    evidence. Unsupported branches retain the raw source and blockers. Larger
    groups retain only raw group/source evidence and the observed member count.
    A structurally supported group still requires an explicit interpretation.
    """
    _validate_source_input(source_text, source_id)
    detected = _unresolved_duty_disjunction_groups(source_text)
    if len(detected) > MAX_COORDINATION_GROUPS:
        _fail("Source exceeds the coordination group count limit")
    source_hash = sha256(source_text.encode("utf-8")).hexdigest()
    groups: list[CoordinationGroup] = []
    for raw in detected:
        blockers: list[str] = []
        count = len(raw["members"])
        if count > MAX_SUPPORTED_MEMBERS:
            blockers.append("coordination_member_count_unsupported")
        group_span = tuple(raw["span"])
        scope_span = tuple(raw["scope_span"])
        if group_span != scope_span:
            blockers.append("coordination_scope_not_fully_represented")
        scope_text = source_text[slice(*scope_span)]
        if any(char in scope_text for char in '()[]{}"“”‘'):
            blockers.append("coordination_nested_source_unsupported")
        if _QUALIFIER_RE.search(scope_text):
            blockers.append("coordination_qualification_unsupported")
        members: list[CoordinationMember] = []
        connectors: list[CoordinationConnector] = []
        last_explicit_actor: CoordinationMember | None = None
        if count <= MAX_SUPPORTED_MEMBERS:
            for index, item in enumerate(raw["members"]):
                member_span = tuple(item["span"])
                modal_span = tuple(item["modal_span"])
                actor_span = _trim_span(source_text, member_span[0], modal_span[0])
                actor = source_text[slice(*actor_span)]
                inherited_from = None
                if not actor:
                    actor_span = None
                    if last_explicit_actor is not None:
                        actor, actor_span = last_explicit_actor.actor, last_explicit_actor.actor_span
                        inherited_from = last_explicit_actor.index
                action_span = _trim_span(source_text, modal_span[1], member_span[1])
                action = source_text[slice(*action_span)]
                member_raw = source_text[slice(*member_span)]
                member_blockers = _member_blockers(actor, action, member_raw)
                member = CoordinationMember(
                    index=index, span=member_span, raw_text=member_raw,
                    actor=actor, actor_span=actor_span, actor_inherited_from=inherited_from,
                    modal_text=source_text[slice(*modal_span)], modal_span=modal_span,
                    modality=("P" if _AUTHORITY_PERMISSION_RE.fullmatch(source_text[slice(*modal_span)])
                              else classify_modal(source_text[slice(*modal_span)])[1]),
                    action=action, action_span=action_span,
                    structure_supported=not member_blockers, blockers=member_blockers,
                )
                members.append(member)
                if actor and inherited_from is None:
                    last_explicit_actor = member
                blockers.extend(member_blockers)
            connectors = [CoordinationConnector(tuple(item["span"]), item["raw_text"])
                          for item in raw["connectors"]]
            # Connector gaps may contain only commas/semicolons and whitespace.
            # A masked quote/qualifier cannot silently disappear between branches.
            for index, connector in enumerate(connectors):
                gaps = (source_text[members[index].span[1]:connector.span[0]],
                        source_text[connector.span[1]:members[index + 1].span[0]])
                if any(gap.strip(" \t\r\n,;") for gap in gaps):
                    blockers.append("coordination_connector_gap_unsupported")
        blockers = list(dict.fromkeys(blockers))
        identity = {"source_sha256": source_hash, "source_id": source_id,
                    "group_span": list(group_span), "scope_span": list(scope_span)}
        values = dict(
            schema_version=COORDINATION_SCHEMA_VERSION, group_id="coordination-" + _digest(identity),
            source_id=source_id, source_text=source_text, source_sha256=source_hash, evidence_sha256="",
            group_span=group_span, group_raw_text=source_text[slice(*group_span)],
            scope_span=scope_span, scope_raw_text=scope_text, observed_member_count=count,
            members=tuple(members), connectors=tuple(connectors), structure_supported=not blockers,
            blockers=tuple([INTERPRETATION_REQUIRED, *blockers]), interpretation_required=True,
            source_semantics_verified=False, proof_ready=False,
        )
        group = CoordinationGroup(**values)
        values["evidence_sha256"] = _digest(_group_payload(group, include_seal=False))
        groups.append(CoordinationGroup(**values))
    return tuple(groups)


def validate_coordination_group(group: CoordinationGroup) -> None:
    """Reject tampered typed candidates, including freshly recomputed hashes."""
    if type(group) is not CoordinationGroup:
        _fail("Expected a typed coordination group")
    group.__post_init__()
    for member in group.members:
        member.__post_init__()
    for connector in group.connectors:
        connector.__post_init__()
    candidates = build_coordination_groups(group.source_text, group.source_id)
    expected = next((candidate for candidate in candidates if candidate.group_id == group.group_id), None)
    if expected is None:
        _fail("Coordination group identity cannot be rebuilt from source")
    _assert_json_payload(_group_payload(group), _group_payload(expected))


def reconstruct_source(group: CoordinationGroup) -> str:
    """Return the exact original independent source region after validation."""
    validate_coordination_group(group)
    return group.source_text[slice(*group.scope_span)]
