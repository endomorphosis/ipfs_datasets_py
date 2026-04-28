"""Typed intermediate representation for deterministic legal norm parses."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _list_of_strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return [str(value)] if value else []
    return [str(item) for item in value if item is not None]


def _enumeration_index(value: Any) -> Optional[int]:
    """Return a deterministic one-based enumeration index when available."""

    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None

    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        index = int(text)
        return index if index > 0 else None

    if len(text) == 1 and text.isalpha():
        return ord(text.lower()) - ord("a") + 1

    roman_values = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
    return roman_values.get(text.lower())


def _slot_detail_records(
    element: Dict[str, Any],
    detail_key: str,
    legacy_key: str,
    *,
    default_type: str = "",
) -> List[Dict[str, Any]]:
    """Return source-grounded slot details with legacy-list compatibility.

    Current parser elements usually carry rich ``*_details`` arrays. Some
    downstream callers still construct v12-compatible dictionaries with only
    legacy string lists such as ``conditions`` or ``cross_references``. The IR
    keeps the rich records preferred, but normalizes both shapes to records that
    expose a stable ``value`` field for exporters and snapshot tests.
    """

    detail_records = _list_of_dicts(element.get(detail_key))
    if detail_records:
        return [_with_value_alias(record) for record in detail_records]

    records: List[Dict[str, Any]] = []
    for text in _list_of_strings(element.get(legacy_key)):
        record: Dict[str, Any] = {"value": text}
        if default_type:
            record["type"] = default_type
        records.append(record)
    return records


def _with_value_alias(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(record)
    if normalized.get("value"):
        return normalized

    for key in ("normalized_text", "raw_text", "text", "term", "defined_term", "name", "canonical_citation", "citation"):
        value = normalized.get(key)
        if value:
            normalized["value"] = value
            return normalized

    reference_value = _reference_value_alias(normalized)
    if reference_value:
        normalized["value"] = reference_value
        return normalized

    if normalized.get("target"):
        normalized["value"] = normalized["target"]
        return normalized

    duration = normalized.get("duration") or normalized.get("deadline") or normalized.get("quantity")
    anchor = normalized.get("anchor") or normalized.get("anchor_event") or normalized.get("event")
    if duration and anchor:
        relation = _temporal_anchor_relation(normalized)
        normalized["value"] = f"{duration} {relation} {anchor}"
        return normalized
    if duration:
        normalized["value"] = str(duration)
        return normalized
    if anchor:
        normalized["value"] = str(anchor)
        return normalized

    return normalized


def _reference_value_alias(record: Dict[str, Any]) -> str:
    """Return a canonical human-readable alias for structured legal references."""

    reference_type = str(record.get("reference_type") or record.get("type") or "").strip().lower()
    target = record.get("target") or record.get("section") or record.get("subsection")
    if not reference_type or not target:
        return ""

    target_text = str(target).strip()
    if not target_text:
        return ""

    if reference_type in {"section", "subsection", "chapter", "title", "article", "part"}:
        if target_text.lower().startswith(f"{reference_type} "):
            return target_text
        return f"{reference_type} {target_text}"
    return target_text


def _with_relationship_value_alias(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a KG relationship hint with a stable exporter value."""

    normalized = _with_value_alias(record)
    if normalized.get("value"):
        return normalized

    subject = normalized.get("subject")
    predicate = normalized.get("predicate")
    object_value = normalized.get("object")
    if subject and predicate and object_value:
        normalized["value"] = f"{subject} {predicate} {object_value}"
    return normalized


def _with_penalty_value_alias(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a penalty record with a stable exporter value."""

    normalized = _with_value_alias(record)
    if normalized.get("value"):
        return normalized

    penalty_type = (
        normalized.get("sanction_class")
        or normalized.get("sanction_type")
        or normalized.get("type")
    )
    modality = normalized.get("modality")
    minimum = (
        normalized.get("minimum_amount")
        or normalized.get("fine_min")
        or normalized.get("min_amount")
    )
    maximum = (
        normalized.get("maximum_amount")
        or normalized.get("fine_max")
        or normalized.get("max_amount")
    )
    imprisonment = normalized.get("imprisonment_duration")
    recurrence = normalized.get("recurrence")

    parts: List[str] = []
    if modality:
        parts.append(str(modality))
    if penalty_type:
        parts.append(str(penalty_type))
    if minimum and maximum:
        parts.append(f"from {minimum} to {maximum}")
    elif minimum:
        parts.append(f"minimum {minimum}")
    elif maximum:
        parts.append(f"maximum {maximum}")
    if imprisonment:
        parts.append(f"imprisonment {imprisonment}")
    if recurrence:
        parts.append(str(recurrence))

    if parts:
        normalized["value"] = " ".join(parts)
    return normalized


def _with_procedure_value_alias(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a procedure record with a stable exporter value."""

    normalized = _with_value_alias(record)
    if normalized.get("value"):
        return normalized

    event_chain = normalized.get("event_chain")
    if isinstance(event_chain, list) and event_chain:
        normalized["value"] = " -> ".join(str(event) for event in event_chain)
        return normalized

    events = normalized.get("events")
    if isinstance(events, list) and events:
        normalized["value"] = " -> ".join(str(event) for event in events)
        return normalized

    trigger = normalized.get("trigger_event")
    terminal = normalized.get("terminal_event")
    if trigger and terminal:
        normalized["value"] = f"{trigger} -> {terminal}"
    elif trigger or terminal:
        normalized["value"] = str(trigger or terminal)
    return normalized


def _temporal_anchor_relation(record: Dict[str, Any]) -> str:
    for key in ("anchor_relation", "relation", "connector"):
        value = str(record.get(key) or "").strip().lower()
        if value in {"after", "before"}:
            return value
        if "before" in value:
            return "before"
        if "after" in value or value.startswith("upon"):
            return "after"

    return "after"


@dataclass(frozen=True)
class SourceSpan:
    """A source-grounded character span."""

    start: int
    end: int

    @classmethod
    def from_value(cls, value: Any) -> "SourceSpan":
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                return cls(int(value[0]), int(value[1]))
            except (TypeError, ValueError):
                pass
        return cls(0, 0)

    def to_list(self) -> List[int]:
        return [self.start, self.end]


@dataclass(frozen=True)
class LegalNormQuality:
    """Quality gates that decide deterministic theorem promotion."""

    schema_valid: bool = False
    slot_coverage: float = 0.0
    scaffold_quality: float = 0.0
    quality_label: str = ""
    parser_warnings: List[str] = field(default_factory=list)
    promotable_to_theorem: bool = False
    export_readiness: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_parser_element(cls, element: Dict[str, Any]) -> "LegalNormQuality":
        return cls(
            schema_valid=bool(element.get("schema_valid")),
            slot_coverage=float(element.get("slot_coverage") or 0.0),
            scaffold_quality=float(element.get("scaffold_quality") or 0.0),
            quality_label=str(element.get("quality_label") or ""),
            parser_warnings=_list_of_strings(element.get("parser_warnings")),
            promotable_to_theorem=bool(element.get("promotable_to_theorem")),
            export_readiness=dict(element.get("export_readiness") or {}),
        )


@dataclass(frozen=True)
class LegalNormIR:
    """Canonical deterministic IR for legal norms.

    The IR is intentionally source-grounded and slot-based. Formal exporters
    should consume this representation rather than reparsing natural language.
    """

    schema_version: str
    source_id: str
    canonical_citation: str
    parent_source_id: str
    enumeration_label: str
    enumeration_index: Optional[int]
    is_enumerated_child: bool
    source_text: str
    support_text: str
    source_span: SourceSpan
    support_span: SourceSpan
    modality: str
    norm_type: str
    actor: str
    actor_type: str
    action: str
    mental_state: str
    action_verb: str
    action_object: str
    recipient: str
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    exceptions: List[Dict[str, Any]] = field(default_factory=list)
    overrides: List[Dict[str, Any]] = field(default_factory=list)
    temporal_constraints: List[Dict[str, Any]] = field(default_factory=list)
    cross_references: List[Dict[str, Any]] = field(default_factory=list)
    resolved_cross_references: List[Dict[str, Any]] = field(default_factory=list)
    defined_terms: List[Dict[str, Any]] = field(default_factory=list)
    penalty: Dict[str, Any] = field(default_factory=dict)
    procedure: Dict[str, Any] = field(default_factory=dict)
    ontology_terms: List[Dict[str, Any]] = field(default_factory=list)
    kg_relationship_hints: List[Dict[str, Any]] = field(default_factory=list)
    field_spans: Dict[str, Any] = field(default_factory=dict)
    formal_terms: Dict[str, Any] = field(default_factory=dict)
    legal_frame: Dict[str, Any] = field(default_factory=dict)
    quality: LegalNormQuality = field(default_factory=LegalNormQuality)

    @classmethod
    def from_parser_element(cls, element: Dict[str, Any]) -> "LegalNormIR":
        """Build a deterministic IR from a parser element dictionary."""
        source_span_value = element.get("source_span") or element.get("support_span")

        enumeration_label = str(element.get("enumeration_label") or "")
        enumeration_index = element.get("enumeration_index")
        derived_index = _enumeration_index(enumeration_index) or _enumeration_index(enumeration_label)

        return cls(
            schema_version=str(element.get("schema_version") or ""),
            source_id=str(element.get("source_id") or ""),
            canonical_citation=str(element.get("canonical_citation") or ""),
            parent_source_id=str(element.get("parent_source_id") or ""),
            enumeration_label=enumeration_label,
            enumeration_index=derived_index,
            is_enumerated_child=bool(element.get("parent_source_id") or enumeration_label or derived_index),
            source_text=str(element.get("text") or ""),
            support_text=str(element.get("support_text") or ""),
            source_span=SourceSpan.from_value(source_span_value),
            support_span=SourceSpan.from_value(element.get("support_span")),
            modality=str(element.get("deontic_operator") or ""),
            norm_type=str(element.get("norm_type") or ""),
            actor=_first_text(element.get("subject")),
            actor_type=str(element.get("actor_type") or element.get("entity_type") or ""),
            action=_first_text(element.get("action")),
            mental_state=str(element.get("mental_state") or ""),
            action_verb=str(element.get("action_verb") or ""),
            action_object=str(element.get("action_object") or ""),
            recipient=str(element.get("action_recipient") or ""),
            conditions=_slot_detail_records(element, "condition_details", "conditions"),
            exceptions=_slot_detail_records(element, "exception_details", "exceptions"),
            overrides=_slot_detail_records(element, "override_clause_details", "override_clauses"),
            temporal_constraints=_slot_detail_records(
                element,
                "temporal_constraint_details",
                "temporal_constraints",
                default_type="deadline",
            ),
            cross_references=_slot_detail_records(element, "cross_reference_details", "cross_references"),
            resolved_cross_references=[
                _with_value_alias(record) for record in _list_of_dicts(element.get("resolved_cross_references"))
            ],
            defined_terms=[
                _with_value_alias(record) for record in _list_of_dicts(element.get("defined_term_refs"))
            ],
            penalty=_with_penalty_value_alias(dict(element.get("penalty") or {})),
            procedure=_with_procedure_value_alias(dict(element.get("procedure") or {})),
            ontology_terms=[
                _with_value_alias(record) for record in _list_of_dicts(element.get("ontology_terms"))
            ],
            kg_relationship_hints=[
                _with_relationship_value_alias(record) for record in _list_of_dicts(element.get("kg_relationship_hints"))
            ],
            field_spans=dict(element.get("field_spans") or {}),
            formal_terms=dict(element.get("formal_terms") or {}),
            legal_frame=dict(element.get("legal_frame") or {}),
            quality=LegalNormQuality.from_parser_element(element),
        )

    @property
    def proof_ready(self) -> bool:
        """Return whether this norm can be theorem-promoted without repair."""

        return bool(self.quality.promotable_to_theorem)

    @property
    def blockers(self) -> List[str]:
        """Return deterministic blockers for theorem promotion."""

        readiness = self.quality.export_readiness or {}
        blockers = readiness.get("blockers")
        if isinstance(blockers, list):
            return _list_of_strings(blockers)
        return list(self.quality.parser_warnings)

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable JSON-friendly dictionary."""

        data = asdict(self)
        data["source_span"] = self.source_span.to_list()
        data["support_span"] = self.support_span.to_list()
        data["proof_ready"] = self.proof_ready
        data["blockers"] = self.blockers
        return data


def parser_element_to_ir(element: Dict[str, Any]) -> LegalNormIR:
    """Compatibility helper for callers that prefer a function API."""

    return LegalNormIR.from_parser_element(element)
