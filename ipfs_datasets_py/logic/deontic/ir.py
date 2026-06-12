"""Typed intermediate representation for deterministic legal norm parses."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence


def _coerce_text_value(value: Any) -> str:
    """Return a stable text projection for mixed legacy/parser slot values."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        normalized = _with_value_alias(dict(value))
        for key in (
            "value",
            "normalized_text",
            "raw_text",
            "text",
            "name",
            "term",
        ):
            text = str(normalized.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value)


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = _coerce_text_value(item).strip()
            if text:
                return text
        return ""
    return _coerce_text_value(value)


def _value_is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def _copy_slot_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def _fill_empty_field(target: Dict[str, Any], source: Mapping[str, Any], key: str) -> None:
    if _value_is_present(target.get(key)):
        return
    value = source.get(key)
    if _value_is_present(value):
        target[key] = _copy_slot_value(value)


def _fill_list_field_from_aliases(
    target: Dict[str, Any],
    source: Mapping[str, Any],
    target_key: str,
    aliases: Sequence[str],
) -> None:
    if _value_is_present(target.get(target_key)):
        return
    for alias in aliases:
        value = source.get(alias)
        if not _value_is_present(value):
            continue
        if isinstance(value, list):
            target[target_key] = list(value)
        else:
            target[target_key] = [value]
        return


def _fill_scalar_field_from_aliases(
    target: Dict[str, Any],
    source: Mapping[str, Any],
    target_key: str,
    aliases: Sequence[str],
) -> None:
    if _value_is_present(target.get(target_key)):
        return
    for alias in aliases:
        value = source.get(alias)
        if _value_is_present(value):
            target[target_key] = _copy_slot_value(value)
            return


def _hydrate_parser_element_from_nested_context(element: Mapping[str, Any]) -> Dict[str, Any]:
    """Fill absent IR slots from deterministic nested parser context.

    Metric and repair payloads sometimes retain source-grounded parser slots in
    ``llm_repair.prompt_context`` or ``legal_frame`` while the top-level row is
    reduced to diagnostics. This hydration is fill-only so explicit parser rows
    keep precedence, but decoder and provenance gates can still see recovered
    actor/modality/action slots and spans.
    """

    hydrated = dict(element)
    prompt_context = _prompt_context_mapping(hydrated)
    legal_frame = hydrated.get("legal_frame")
    context_sources = []
    if isinstance(prompt_context, Mapping):
        context_sources.append(prompt_context)
        nested_legal_frame = prompt_context.get("legal_frame")
        if isinstance(nested_legal_frame, Mapping):
            context_sources.append(nested_legal_frame)
    if isinstance(legal_frame, Mapping):
        context_sources.append(legal_frame)

    for source in context_sources:
        for key in (
            "schema_version",
            "source_id",
            "canonical_citation",
            "support_text",
            "support_span",
            "source_span",
            "field_spans",
            "norm_type",
            "deontic_operator",
            "modality",
            "parser_warnings",
            "export_readiness",
            "formal_terms",
            "legal_frame",
            "section_context",
            "definition_scope",
        ):
            _fill_empty_field(hydrated, source, key)
        if not _value_is_present(hydrated.get("text")):
            hydrated["text"] = (
                source.get("text")
                or source.get("source_text")
                or source.get("support_text")
                or ""
            )
        _fill_list_field_from_aliases(
            hydrated,
            source,
            "subject",
            ("subject", "actor", "legal_actor", "regulated_entity", "entity"),
        )
        _fill_list_field_from_aliases(
            hydrated,
            source,
            "action",
            (
                "action",
                "action_text",
                "required_action",
                "permitted_action",
                "prohibited_action",
                "regulated_activity",
                "regulated_conduct",
                "conduct",
            ),
        )
        _fill_scalar_field_from_aliases(
            hydrated,
            source,
            "action_recipient",
            ("action_recipient", "recipient", "beneficiary"),
        )

        for key in (
            "actor_details",
            "subject_details",
            "regulated_entity_details",
            "action_details",
            "action_verb_details",
            "action_object_details",
            "recipient_details",
            "action_recipient_details",
            "regulated_activity_details",
            "condition_details",
            "exception_details",
            "override_clause_details",
            "temporal_constraint_details",
            "cross_reference_details",
            "resolved_cross_references",
            "defined_term_refs",
            "defined_terms",
            "ontology_terms",
            "kg_relationship_hints",
        ):
            _fill_empty_field(hydrated, source, key)

    if not _value_is_present(hydrated.get("deontic_operator")) and _value_is_present(
        hydrated.get("modality")
    ):
        hydrated["deontic_operator"] = hydrated.get("modality")
    return hydrated


def _list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _list_of_strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        text = _coerce_text_value(value).strip()
        return [text] if text else []
    values: List[str] = []
    for item in value:
        text = _coerce_text_value(item).strip()
        if text:
            values.append(text)
    return values


def _actor_texts(value: Any) -> List[str]:
    """Return all structured actor labels while preserving parser order."""

    return [text for text in _list_of_strings(value) if text.strip()]


def _actor_text(element: Dict[str, Any]) -> str:
    """Return a source-grounded actor slot from flat or detail fields."""

    flat_value = _first_text(element.get("subject")).strip()
    if flat_value:
        return flat_value

    for key in ("actor", "legal_actor", "regulated_entity"):
        flat_value = str(element.get(key) or "").strip()
        if flat_value:
            return flat_value

    for detail_key in (
        "actor_details",
        "subject_details",
        "regulated_entity_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "value",
                "normalized_text",
                "raw_text",
                "text",
                "actor",
                "subject",
                "entity",
                "name",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _detail_only_recipient_text(element: Dict[str, Any]) -> str:
    """Return a source-grounded recipient from structured detail-only slots."""

    for detail_key in (
        "recipient_details",
        "action_recipient_details",
        "beneficiary_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "recipient",
                "action_recipient",
                "beneficiary",
                "entity",
                "value",
                "normalized_text",
                "raw_text",
                "text",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _detail_only_regulated_activity_text(element: Dict[str, Any]) -> str:
    """Return a source-grounded regulated activity object from detail slots."""

    for detail_key in (
        "regulated_activity_details",
        "activity_details",
        "regulated_conduct_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "regulated_activity",
                "activity",
                "conduct",
                "action_object",
                "object",
                "value",
                "normalized_text",
                "raw_text",
                "text",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _definition_actor_text(element: Dict[str, Any]) -> str:
    """Return the defined term for detail-only definition parser rows."""

    norm_type = str(element.get("norm_type") or "").strip().lower()
    operator = str(element.get("deontic_operator") or element.get("modality") or "").strip().upper()
    if norm_type != "definition" and operator != "DEF":
        return ""

    for key in ("defined_term", "definition_term", "term"):
        value = str(element.get(key) or "").strip()
        if value:
            return value

    for detail_key in (
        "defined_term_details",
        "definition_details",
        "defined_term_refs",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "value",
                "defined_term",
                "term",
                "normalized_text",
                "raw_text",
                "text",
                "name",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _instrument_lifecycle_actor_text(element: Dict[str, Any]) -> str:
    """Return the regulated instrument for detail-only lifecycle rows."""

    norm_type = str(element.get("norm_type") or "").strip().lower()
    operator = str(element.get("deontic_operator") or element.get("modality") or "").strip().upper()
    if norm_type != "instrument_lifecycle" and operator != "LIFE":
        return ""

    for key in ("instrument", "instrument_type", "regulated_instrument"):
        value = str(element.get(key) or "").strip()
        if value:
            return value

    for detail_key in (
        "instrument_lifecycle_details",
        "lifecycle_details",
        "instrument_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "instrument_type",
                "instrument",
                "regulated_instrument",
                "value",
                "normalized_text",
                "raw_text",
                "text",
                "name",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _instrument_lifecycle_action_text(element: Dict[str, Any]) -> str:
    """Return a lifecycle action from structured duration or anchor details."""

    flat_value = _first_text(element.get("action")).strip()
    if flat_value:
        return flat_value

    norm_type = str(element.get("norm_type") or "").strip().lower()
    operator = str(element.get("deontic_operator") or element.get("modality") or "").strip().upper()
    if norm_type != "instrument_lifecycle" and operator != "LIFE":
        return ""

    kind = str(
        element.get("lifecycle_action")
        or element.get("action_type")
        or element.get("lifecycle_type")
        or ""
    ).strip()
    duration = str(element.get("duration") or element.get("valid_for") or "").strip()
    anchor = str(element.get("anchor") or element.get("expiration_anchor") or "").strip()
    action = _instrument_lifecycle_action_from_parts(kind, duration, anchor)
    if action:
        return action

    for detail_key in ("instrument_lifecycle_details", "lifecycle_details"):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            kind = str(
                normalized.get("lifecycle_action")
                or normalized.get("action_type")
                or normalized.get("lifecycle_type")
                or normalized.get("type")
                or normalized.get("relation")
                or ""
            ).strip()
            duration = str(normalized.get("duration") or normalized.get("valid_for") or "").strip()
            anchor = str(normalized.get("anchor") or normalized.get("expiration_anchor") or "").strip()
            action = _instrument_lifecycle_action_from_parts(kind, duration, anchor)
            if action:
                return action

    return ""


def _instrument_lifecycle_action_from_parts(kind: str, duration: str, anchor: str) -> str:
    normalized_kind = str(kind or "").strip().lower().replace("_", "-")
    if duration and ("valid" in normalized_kind or "duration" in normalized_kind or normalized_kind in {""}):
        return f"valid for {duration}"
    if anchor and ("expir" in normalized_kind or "terminat" in normalized_kind or "expire" in normalized_kind):
        return f"expires {anchor}"
    return ""


def _penalty_action_text(element: Dict[str, Any]) -> str:
    """Return a sanction action from structured detail-only penalty fields."""

    flat_value = _first_text(element.get("action")).strip()
    if flat_value:
        return flat_value

    norm_type = str(element.get("norm_type") or "").strip().lower()
    if norm_type != "penalty":
        return ""

    candidates: List[Dict[str, Any]] = []
    penalty = element.get("penalty")
    if isinstance(penalty, dict):
        candidates.append(dict(penalty))
    candidates.extend(_list_of_dicts(element.get("penalty_details")))
    candidates.extend(_list_of_dicts(element.get("sanction_details")))

    for record in candidates:
        normalized = _with_value_alias(record)
        for key in ("value", "normalized_text", "raw_text", "text", "action"):
            value = str(normalized.get(key) or "").strip()
            if value:
                return value

        action = _penalty_action_from_parts(normalized)
        if action:
            return action

    return ""


def _applicability_actor_text(element: Dict[str, Any]) -> str:
    """Return the scope for detail-only applicability parser rows."""

    norm_type = str(element.get("norm_type") or "").strip().lower()
    operator = str(element.get("deontic_operator") or element.get("modality") or "").strip().upper()
    if norm_type != "applicability" and operator != "APP":
        return ""

    for key in ("scope", "applicability_scope", "legal_scope"):
        value = str(element.get(key) or "").strip()
        if value:
            return value

    for detail_key in (
        "applicability_details",
        "scope_details",
        "applicability_scope_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "scope",
                "scope_text",
                "applicability_scope",
                "value",
                "normalized_text",
                "raw_text",
                "text",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _applicability_action_text(element: Dict[str, Any]) -> str:
    """Return the target for detail-only applicability parser rows."""

    flat_value = _first_text(element.get("action")).strip()
    if flat_value:
        return flat_value

    norm_type = str(element.get("norm_type") or "").strip().lower()
    operator = str(element.get("deontic_operator") or element.get("modality") or "").strip().upper()
    if norm_type != "applicability" and operator != "APP":
        return ""

    for key in ("target", "applicability_target", "regulated_target"):
        value = str(element.get(key) or "").strip()
        if value:
            return value

    for detail_key in (
        "applicability_details",
        "applicability_target_details",
        "target_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in ("target", "target_text", "applicability_target", "value", "normalized_text", "raw_text", "text"):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _exemption_actor_text(element: Dict[str, Any]) -> str:
    """Return the exempt entity for detail-only exemption parser rows."""

    norm_type = str(element.get("norm_type") or "").strip().lower()
    operator = str(element.get("deontic_operator") or element.get("modality") or "").strip().upper()
    if norm_type != "exemption" and operator != "EXEMPT":
        return ""

    for key in ("target", "exemption_target", "exempt_entity", "entity"):
        value = str(element.get(key) or "").strip()
        if value:
            return value

    for detail_key in (
        "exemption_details",
        "exemption_target_details",
        "target_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "target",
                "target_text",
                "exemption_target",
                "exempt_entity",
                "entity",
                "value",
                "normalized_text",
                "raw_text",
                "text",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _exemption_action_text(element: Dict[str, Any]) -> str:
    """Return the exempted requirement for detail-only exemption parser rows."""

    flat_value = _first_text(element.get("action")).strip()
    if flat_value:
        return flat_value

    norm_type = str(element.get("norm_type") or "").strip().lower()
    operator = str(element.get("deontic_operator") or element.get("modality") or "").strip().upper()
    if norm_type != "exemption" and operator != "EXEMPT":
        return ""

    for key in ("requirement", "exemption_requirement", "instrument", "required_instrument"):
        value = str(element.get(key) or "").strip()
        if value:
            return value

    for detail_key in (
        "exemption_details",
        "exemption_requirement_details",
        "requirement_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in ("requirement", "requirement_text", "exemption_requirement", "instrument", "value", "normalized_text", "raw_text", "text"):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _action_verb_text(element: Dict[str, Any]) -> str:
    """Return a source-grounded action verb from flat or detail fields."""

    flat_value = str(element.get("action_verb") or "").strip()
    if flat_value:
        return flat_value

    for detail_key in (
        "action_verb_details",
        "verb_details",
        "action_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "verb",
                "action_verb",
                "value",
                "normalized_text",
                "raw_text",
                "text",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _action_object_text(element: Dict[str, Any]) -> str:
    """Return a source-grounded action object from flat or detail fields."""

    flat_value = str(element.get("action_object") or "").strip()
    if flat_value:
        return flat_value

    for detail_key in (
        "action_object_details",
        "object_details",
        "regulated_object_details",
        "action_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "object",
                "action_object",
                "value",
                "normalized_text",
                "raw_text",
                "text",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


def _generic_action_text(element: Dict[str, Any]) -> str:
    """Return a source-grounded action phrase from common scalar aliases."""

    flat_value = _first_text(element.get("action")).strip()
    if flat_value:
        return flat_value

    for key in (
        "action_text",
        "required_action",
        "permitted_action",
        "prohibited_action",
        "regulated_activity",
        "regulated_conduct",
        "conduct",
        "predicate",
    ):
        value = str(element.get(key) or "").strip()
        if value:
            return value

    legal_frame = element.get("legal_frame")
    if isinstance(legal_frame, Mapping):
        for key in (
            "action",
            "action_text",
            "required_action",
            "permitted_action",
            "prohibited_action",
            "regulated_activity",
            "regulated_conduct",
            "conduct",
            "predicate",
        ):
            value = _first_text(legal_frame.get(key)).strip()
            if value:
                return value

    prompt_context = _prompt_context_mapping(element)
    for key in (
        "action",
        "action_text",
        "required_action",
        "permitted_action",
        "prohibited_action",
        "regulated_activity",
        "regulated_conduct",
        "conduct",
        "predicate",
    ):
        value = _first_text(prompt_context.get(key)).strip()
        if value:
            return value

    return ""


def _penalty_action_from_parts(record: Dict[str, Any]) -> str:
    sanction_class = str(
        record.get("sanction_class")
        or record.get("penalty_class")
        or record.get("type")
        or "penalty"
    ).strip().lower().replace("_", " ")
    sanction_class = sanction_class.replace("sanction", "").strip()

    amount_text = _penalty_amount_text(record)
    recurrence = str(record.get("recurrence") or record.get("per") or "").strip().lower()
    if recurrence and not recurrence.startswith("per "):
        recurrence = f"per {recurrence}"

    parts = ["incur"]
    if sanction_class:
        parts.append(sanction_class)
    if amount_text:
        parts.append(amount_text)
    if recurrence:
        parts.append(recurrence)
    return " ".join(part for part in parts if part).strip()


def _penalty_amount_text(record: Dict[str, Any]) -> str:
    for key in ("amount_text", "fine_text", "amount", "maximum", "minimum"):
        value = str(record.get(key) or "").strip()
        if value:
            return value

    minimum = str(record.get("min_amount") or record.get("minimum_amount") or "").strip()
    maximum = str(record.get("max_amount") or record.get("maximum_amount") or "").strip()
    if minimum and maximum:
        return f"not less than {minimum} and not more than {maximum}"
    if minimum:
        return f"not less than {minimum}"
    if maximum:
        return f"not more than {maximum}"
    return ""


def _actor_entities(element: Dict[str, Any]) -> List[str]:
    """Return all actor labels, including detail-only actor provenance."""

    actors = _actor_texts(element.get("subject"))
    if actors:
        return actors
    actor = (
        _actor_text(element)
        or _applicability_actor_text(element)
        or _exemption_actor_text(element)
        or _definition_actor_text(element)
        or _instrument_lifecycle_actor_text(element)
    )
    return [actor] if actor else []


def _mental_state_text(element: Dict[str, Any]) -> str:
    """Return a source-grounded mental-state slot from flat or detail fields."""

    flat_value = str(element.get("mental_state") or "").strip()
    if flat_value:
        return flat_value

    for detail_key in ("mental_state_details", "mens_rea_details"):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in ("value", "normalized_text", "raw_text", "text", "term"):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    for legacy_key in ("mental_states", "mens_rea"):
        values = _list_of_strings(element.get(legacy_key))
        if values:
            return values[0].strip()

    return ""


def _recipient_text(element: Dict[str, Any]) -> str:
    """Return a source-grounded recipient slot from flat or detail fields."""

    for key in ("action_recipient", "recipient", "beneficiary"):
        flat_value = str(element.get(key) or "").strip()
        if flat_value:
            return flat_value

    for detail_key in (
        "action_recipient_details",
        "recipient_details",
        "beneficiary_details",
    ):
        for record in _list_of_dicts(element.get(detail_key)):
            normalized = _with_value_alias(record)
            for key in (
                "value",
                "normalized_text",
                "raw_text",
                "text",
                "recipient",
                "target",
                "beneficiary",
                "object",
            ):
                value = str(normalized.get(key) or "").strip()
                if value:
                    return value

    return ""


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


_CANONICAL_MODALITY_OPERATORS = {"O", "P", "F", "DEF", "APP", "EXEMPT", "LIFE", "PURP"}
_MODALITY_NORM_TYPE_MAP = {
    "O": "obligation",
    "P": "permission",
    "F": "prohibition",
    "DEF": "definition",
    "APP": "applicability",
    "EXEMPT": "exemption",
    "LIFE": "instrument_lifecycle",
    "PURP": "purpose",
}
_NORM_TYPE_MODALITY_MAP = {
    "obligation": "O",
    "mandatory_obligation": "O",
    "duty": "O",
    "requirement": "O",
    "penalty": "O",
    "sanction": "O",
    "permission": "P",
    "entitlement": "P",
    "authorization": "P",
    "prohibition": "F",
    "violation": "F",
    "offense": "F",
    "infraction": "F",
    "definition": "DEF",
    "applicability": "APP",
    "exemption": "EXEMPT",
    "instrument_lifecycle": "LIFE",
    "purpose": "PURP",
}
_TEXTUAL_MODALITY_MAP = {
    "obligation": "O",
    "obligatory": "O",
    "duty": "O",
    "must": "O",
    "shall": "O",
    "required": "O",
    "requirement": "O",
    "mandatory": "O",
    "permission": "P",
    "permitted": "P",
    "may": "P",
    "authorized": "P",
    "allowed": "P",
    "entitled": "P",
    "entitlement": "P",
    "prohibition": "F",
    "prohibited": "F",
    "forbidden": "F",
    "must not": "F",
    "shall not": "F",
    "may not": "F",
    "cannot": "F",
    "can not": "F",
    "not permitted": "F",
    "not allowed": "F",
    "violation": "F",
    "offense": "F",
    "infraction": "F",
    "definition": "DEF",
    "purpose": "PURP",
    "general purpose": "PURP",
    "mission": "PURP",
    "function": "PURP",
    "functions": "PURP",
    "applicability": "APP",
    "exemption": "EXEMPT",
    "instrument lifecycle": "LIFE",
}
_PROHIBITION_MODALITY_RE = re.compile(
    r"\b(?:shall|must|may|can)\s+not\b|\b(?:prohibit(?:ed|ion)?|forbid(?:den)?|ban(?:ned)?|disallow(?:ed)?)\b",
    re.IGNORECASE,
)
_OBLIGATION_MODALITY_RE = re.compile(
    r"\b(?:shall|required?|must|obligat(?:ion|ory)?|mandatory|duty)\b"
    r"|\b(?:is|are)\s+authorized\s+and\s+directed\s+to\b"
    r"|\b(?:is|are)\s+directed\s+to\b",
    re.IGNORECASE,
)
_PERMISSION_MODALITY_RE = re.compile(
    r"\b(?:may|permit(?:ted|s)?|allow(?:ed|s)?|authoriz(?:e|ed|es)|entitl(?:e|ed|ement))\b",
    re.IGNORECASE,
)


def _modality_from_textual_value(value: Any) -> str:
    """Return a canonical modality inferred from textual modal cues."""

    text = str(value or "").strip()
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", text.lower().replace("_", " ").replace("-", " ")).strip()
    mapped = _TEXTUAL_MODALITY_MAP.get(normalized)
    if mapped:
        return mapped
    if _PROHIBITION_MODALITY_RE.search(text):
        return "F"
    if _OBLIGATION_MODALITY_RE.search(text):
        return "O"
    if _PERMISSION_MODALITY_RE.search(text):
        return "P"
    return ""


def canonical_modality_operator(modality: Any, norm_type: Any = "") -> str:
    """Return a canonical deontic operator from typed IR modality fields."""

    raw_modality = str(modality or "").strip()
    if raw_modality:
        upper_modality = raw_modality.upper()
        if upper_modality in _CANONICAL_MODALITY_OPERATORS:
            return upper_modality
        inferred_modality = _modality_from_textual_value(raw_modality)
        if inferred_modality:
            return inferred_modality

    normalized_norm_type = str(norm_type or "").strip().lower()
    mapped_norm_type = _NORM_TYPE_MODALITY_MAP.get(normalized_norm_type)
    if mapped_norm_type:
        return mapped_norm_type

    inferred_norm_type = _modality_from_textual_value(normalized_norm_type)
    if inferred_norm_type:
        return inferred_norm_type

    return ""


def _modality_from_parser_element(element: Dict[str, Any]) -> str:
    """Return a stable deontic operator for parser and detail-only rows.

    Optimizer/evaluation payloads sometimes carry the structured ``norm_type``
    but omit ``deontic_operator``. The IR can recover the operator from that
    already-classified slot without inspecting raw source text or relaxing any
    parser warning. Unknown norm types still stay empty and blocked downstream.
    """

    resolved_norm_type = _norm_type_from_parser_element(element)
    for key in ("deontic_operator", "modality"):
        inferred = canonical_modality_operator(
            element.get(key),
            resolved_norm_type,
        )
        if inferred:
            return inferred

    legal_frame = element.get("legal_frame")
    if isinstance(legal_frame, Mapping):
        for key in ("deontic_operator", "modality", "norm_type"):
            inferred = canonical_modality_operator(
                legal_frame.get(key),
                resolved_norm_type,
            )
            if inferred:
                return inferred

    prompt_context = _prompt_context_mapping(element)
    for key in ("deontic_operator", "modality", "norm_type"):
        inferred = canonical_modality_operator(
            prompt_context.get(key),
            resolved_norm_type,
        )
        if inferred:
            return inferred

    inferred_norm_type = canonical_modality_operator(
        "",
        resolved_norm_type,
    )
    if inferred_norm_type:
        return inferred_norm_type

    for key in ("text", "support_text", "action"):
        inferred = _modality_from_textual_value(element.get(key))
        if inferred:
            return inferred
    for key in ("source_text", "text", "support_text", "action"):
        inferred = _modality_from_textual_value(prompt_context.get(key))
        if inferred:
            return inferred
    return ""


def _prompt_context_mapping(element: Mapping[str, Any]) -> Dict[str, Any]:
    llm_repair = element.get("llm_repair")
    if not isinstance(llm_repair, Mapping):
        return {}
    prompt_context = llm_repair.get("prompt_context")
    if not isinstance(prompt_context, Mapping):
        return {}
    return dict(prompt_context)


def _norm_type_from_parser_element(element: Dict[str, Any]) -> str:
    """Return a stable norm type from top-level or legacy detail slots."""

    top_level = str(element.get("norm_type") or "").strip()
    if top_level:
        return top_level

    legal_frame = element.get("legal_frame")
    if isinstance(legal_frame, Mapping):
        legal_frame_norm_type = str(legal_frame.get("norm_type") or "").strip()
        if legal_frame_norm_type:
            return legal_frame_norm_type

    prompt_context = _prompt_context_mapping(element)
    prompt_norm_type = str(prompt_context.get("norm_type") or "").strip()
    if prompt_norm_type:
        return prompt_norm_type

    for container in (element, legal_frame, prompt_context):
        if not isinstance(container, Mapping):
            continue
        for key in ("deontic_operator", "modality"):
            inferred_modality = canonical_modality_operator(container.get(key), "")
            inferred_norm_type = _MODALITY_NORM_TYPE_MAP.get(inferred_modality)
            if inferred_norm_type:
                return inferred_norm_type
    return ""


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

    legacy_records: List[Dict[str, Any]] = []
    legacy_value = element.get(legacy_key)
    if isinstance(legacy_value, list):
        for item in legacy_value:
            if isinstance(item, dict):
                record = _with_value_alias(dict(item))
                if default_type and not record.get("type"):
                    record["type"] = default_type
                legacy_records.append(record)
                continue
            if item is None:
                continue
            text = str(item).strip()
            if not text:
                continue
            record = {"value": text}
            if default_type:
                record["type"] = default_type
            legacy_records.append(record)
        if legacy_records:
            return legacy_records

    records: List[Dict[str, Any]] = []
    for text in _list_of_strings(legacy_value):
        record: Dict[str, Any] = {"value": text}
        if default_type:
            record["type"] = default_type
        records.append(record)
    return records


def _support_scoped_slot_records(
    records: Sequence[Mapping[str, Any]],
    support_span: "SourceSpan",
) -> List[Dict[str, Any]]:
    """Keep detail records that are local to this norm's support span.

    Some migrated parser payloads attach section-level condition, exception,
    override, and reference records to every extracted norm.  When both the norm
    and detail record carry absolute spans, the typed IR should expose only the
    details that overlap the norm support text.  Spanless records are retained
    for legacy callers that cannot provide this stronger evidence.
    """

    scoped: List[Dict[str, Any]] = []
    support_start = int(support_span.start)
    support_end = int(support_span.end)
    has_support_span = support_end > support_start
    for record in records:
        row = dict(record)
        spans = _direct_record_spans(row)
        if not has_support_span or not spans:
            scoped.append(row)
            continue
        if any(_spans_overlap(span, [support_start, support_end]) for span in spans):
            scoped.append(row)
    return scoped


def _direct_record_spans(record: Mapping[str, Any]) -> List[List[int]]:
    """Return spans that locate the record itself, excluding nested values."""

    spans: List[List[int]] = []
    for key in ("span", "source_span", "support_span", "clause_span"):
        spans.extend(_normalized_span_records(record.get(key)))
    return spans


def _spans_overlap(left: Sequence[int], right: Sequence[int]) -> bool:
    if len(left) != 2 or len(right) != 2:
        return False
    left_start, left_end = int(left[0]), int(left[1])
    right_start, right_end = int(right[0]), int(right[1])
    return left_start < right_end and right_start < left_end


def _quality_with_scoped_slot_blockers(
    quality: "LegalNormQuality",
    *,
    conditions: Sequence[Mapping[str, Any]],
    exceptions: Sequence[Mapping[str, Any]],
    overrides: Sequence[Mapping[str, Any]],
    cross_references: Sequence[Mapping[str, Any]],
) -> "LegalNormQuality":
    """Drop parser blockers for slot families absent after IR span scoping."""

    absent_warning_by_slot = {
        "conditions": {"condition_requires_scope_review"},
        "exceptions": {"exception_requires_scope_review"},
        "overrides": {"override_clause_requires_precedence_review"},
        "cross_references": {"cross_reference_requires_resolution"},
    }
    present_by_slot = {
        "conditions": bool(conditions),
        "exceptions": bool(exceptions),
        "overrides": bool(overrides),
        "cross_references": bool(cross_references),
    }
    stale_warnings = {
        warning
        for slot_name, warnings in absent_warning_by_slot.items()
        if not present_by_slot[slot_name]
        for warning in warnings
    }
    if not stale_warnings:
        return quality

    parser_warnings = [
        warning for warning in quality.parser_warnings if warning not in stale_warnings
    ]
    export_readiness = dict(quality.export_readiness or {})
    blockers = export_readiness.get("blockers")
    if isinstance(blockers, list):
        export_readiness["blockers"] = [
            blocker for blocker in _list_of_strings(blockers) if blocker not in stale_warnings
        ]

    return LegalNormQuality(
        schema_valid=quality.schema_valid,
        slot_coverage=quality.slot_coverage,
        scaffold_quality=quality.scaffold_quality,
        quality_label=quality.quality_label,
        parser_warnings=parser_warnings,
        promotable_to_theorem=quality.promotable_to_theorem,
        export_readiness=export_readiness,
    )


def _with_value_alias(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(record)
    if normalized.get("value"):
        return normalized

    for key in ("canonical_citation", "citation", "normalized_text", "raw_text", "text", "term", "defined_term", "name"):
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

    alternatives = _temporal_alternatives(normalized)
    if alternatives:
        alternative_values = [_temporal_alternative_value(item) for item in alternatives]
        alternative_values = [value for value in alternative_values if value]
        if alternative_values:
            selector = _temporal_selector(normalized)
            suffix = f" whichever is {selector}" if selector in {"earlier", "later"} else ""
            normalized["value"] = " or ".join(alternative_values) + suffix
            return normalized

    duration = _temporal_duration_value(normalized)
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
    canonical = str(record.get("canonical_citation") or record.get("citation") or "").strip()
    if canonical:
        return canonical

    raw_text = str(record.get("raw_text") or record.get("normalized_text") or "").strip()
    if raw_text and reference_type and raw_text.lower().startswith(reference_type + " "):
        return raw_text

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
    penalty_type = (
        normalized.get("sanction_class")
        or normalized.get("sanction_type")
        or normalized.get("type")
    )
    if normalized.get("value"):
        return normalized

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

    event_relations = normalized.get("event_relations")
    if isinstance(event_relations, list) and event_relations:
        relation_values = [
            _procedure_relation_value(relation)
            for relation in event_relations
            if isinstance(relation, dict)
        ]
        relation_values = [value for value in relation_values if value]
        if relation_values:
            normalized["value"] = " -> ".join(relation_values)
            return normalized

    trigger = normalized.get("trigger_event")
    terminal = normalized.get("terminal_event")
    if trigger and terminal:
        normalized["value"] = f"{trigger} -> {terminal}"
    elif trigger or terminal:
        normalized["value"] = str(trigger or terminal)
    return normalized


def _procedure_relation_value(record: Dict[str, Any]) -> str:
    """Return a compact value alias for a structured procedure relation."""

    event = str(record.get("event") or "").strip()
    relation = str(record.get("relation") or "").strip()
    anchor = str(record.get("anchor_event") or "").strip()
    if not event and not anchor:
        return ""

    if relation == "triggered_by_receipt_of" and event and anchor:
        return f"{anchor} -> {event}"
    if relation in {"before", "after"} and event and anchor:
        return f"{event} {relation} {anchor}"
    if event and anchor:
        return f"{event} {relation} {anchor}".strip()
    if event:
        return event
    return anchor


def _temporal_alternatives(record: Dict[str, Any]) -> List[Any]:
    """Return structured alternative deadlines from known parser shapes."""

    for key in (
        "alternatives",
        "alternative_deadlines",
        "deadline_alternatives",
        "deadline_options",
    ):
        alternatives = record.get(key)
        if isinstance(alternatives, list):
            return alternatives
    return []


def _temporal_selector(record: Dict[str, Any]) -> str:
    """Return normalized whichever-is-earlier/later selector text."""

    selector = str(
        record.get("selector")
        or record.get("comparison")
        or record.get("whichever")
        or ""
    ).strip().lower().replace("-", "_").replace(" ", "_")
    if selector.startswith("whichever_is_"):
        selector = selector[len("whichever_is_") :]
    return selector


def _temporal_alternative_value(value: Any) -> str:
    """Return a compact value for one structured alternative deadline."""

    if isinstance(value, dict):
        for key in ("value", "normalized_text", "raw_text", "text"):
            text = str(value.get(key) or "").strip()
            if text:
                return text

        duration = _temporal_duration_value(value)
        anchor = value.get("anchor") or value.get("anchor_event") or value.get("event")
        if duration and anchor:
            relation = _temporal_anchor_relation(value)
            return f"{duration} {relation} {anchor}"
        return str(duration or anchor or "").strip()

    return str(value or "").strip()


def _temporal_duration_value(record: Dict[str, Any]) -> str:
    """Return a compact duration phrase from structured temporal fields."""

    for key in ("duration", "deadline"):
        value = str(record.get(key) or "").strip()
        if value:
            return value

    quantity = record.get("quantity")
    unit = str(record.get("unit") or record.get("time_unit") or "").strip()
    calendar = str(record.get("calendar") or "").strip()
    if quantity is None or quantity == "":
        return ""

    parts = [str(quantity).strip()]
    if calendar:
        parts.append(calendar)
    if unit:
        parts.append(unit)
    return " ".join(part for part in parts if part)


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
        nested_quality = element.get("quality")
        quality = (
            dict(nested_quality)
            if isinstance(nested_quality, Mapping)
            else {}
        )
        return cls(
            schema_valid=bool(quality.get("schema_valid", element.get("schema_valid"))),
            slot_coverage=float(
                quality.get("slot_coverage", element.get("slot_coverage")) or 0.0
            ),
            scaffold_quality=float(
                quality.get("scaffold_quality", element.get("scaffold_quality")) or 0.0
            ),
            quality_label=str(
                quality.get("quality_label", element.get("quality_label")) or ""
            ),
            parser_warnings=_list_of_strings(
                quality.get("parser_warnings", element.get("parser_warnings"))
            ),
            promotable_to_theorem=bool(
                quality.get(
                    "promotable_to_theorem",
                    element.get("promotable_to_theorem"),
                )
            ),
            export_readiness=dict(
                quality.get("export_readiness")
                or element.get("export_readiness")
                or {}
            ),
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
    section_context: Dict[str, Any] = field(default_factory=dict)
    actor_entities: List[str] = field(default_factory=list)
    quality: LegalNormQuality = field(default_factory=LegalNormQuality)
    definition_scope: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_parser_element(cls, element: Dict[str, Any]) -> "LegalNormIR":
        """Build a deterministic IR from a parser element dictionary."""
        element = _hydrate_parser_element_from_nested_context(element)
        source_span_value = element.get("source_span") or element.get("support_span")
        support_span = SourceSpan.from_value(element.get("support_span"))

        enumeration_label = str(element.get("enumeration_label") or "")
        enumeration_index = element.get("enumeration_index")
        derived_index = _enumeration_index(enumeration_index) or _enumeration_index(enumeration_label)
        conditions = _support_scoped_slot_records(
            _slot_detail_records(element, "condition_details", "conditions"),
            support_span,
        )
        exceptions = _support_scoped_slot_records(
            _slot_detail_records(element, "exception_details", "exceptions"),
            support_span,
        )
        overrides = _support_scoped_slot_records(
            _slot_detail_records(element, "override_clause_details", "override_clauses"),
            support_span,
        )
        temporal_constraints = _support_scoped_slot_records(
            _slot_detail_records(
                element,
                "temporal_constraint_details",
                "temporal_constraints",
                default_type="deadline",
            ),
            support_span,
        )
        cross_references = _support_scoped_slot_records(
            _slot_detail_records(element, "cross_reference_details", "cross_references"),
            support_span,
        )
        quality = _quality_with_scoped_slot_blockers(
            LegalNormQuality.from_parser_element(element),
            conditions=conditions,
            exceptions=exceptions,
            overrides=overrides,
            cross_references=cross_references,
        )

        return cls(
            schema_version=str(element.get("schema_version") or ""),
            source_id=str(element.get("source_id") or ""),
            canonical_citation=str(element.get("canonical_citation") or ""),
            parent_source_id=str(element.get("parent_source_id") or ""),
            enumeration_label=enumeration_label,
            enumeration_index=derived_index,
            is_enumerated_child=bool(element.get("parent_source_id") or enumeration_label or derived_index),
            source_text=str(element.get("text") or element.get("source_text") or ""),
            support_text=str(element.get("support_text") or ""),
            source_span=SourceSpan.from_value(source_span_value),
            support_span=support_span,
            modality=_modality_from_parser_element(element),
            norm_type=_norm_type_from_parser_element(element),
            actor=(
                _actor_text(element)
                or _applicability_actor_text(element)
                or _exemption_actor_text(element)
                or _definition_actor_text(element)
                or _instrument_lifecycle_actor_text(element)
            ),
            actor_type=str(element.get("actor_type") or element.get("entity_type") or ""),
            action=(
                _applicability_action_text(element)
                or _exemption_action_text(element)
                or _instrument_lifecycle_action_text(element)
                or _penalty_action_text(element)
                or _generic_action_text(element)
            ),
            mental_state=_mental_state_text(element),
            action_verb=_action_verb_text(element),
            action_object=_action_object_text(element) or _detail_only_regulated_activity_text(element),
            recipient=_recipient_text(element) or _detail_only_recipient_text(element),
            conditions=conditions,
            exceptions=exceptions,
            overrides=overrides,
            temporal_constraints=temporal_constraints,
            cross_references=cross_references,
            resolved_cross_references=[
                _with_value_alias(record) for record in _list_of_dicts(element.get("resolved_cross_references"))
            ],
            defined_terms=[
                _with_value_alias(record)
                for record in _list_of_dicts(
                    element.get("defined_term_refs") or element.get("defined_terms")
                )
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
            section_context=dict(element.get("section_context") or {}),
            actor_entities=_actor_texts(element.get("actor_entities")) or _actor_entities(element),
            quality=quality,
            definition_scope=dict(element.get("definition_scope") or {}),
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

    @property
    def decoder_requires_validation(self) -> bool:
        """Return whether parser warnings block decoder-quality reconstruction."""

        return parser_warnings_require_decoder_validation(self.quality.parser_warnings)

    @property
    def canonical_modality(self) -> str:
        """Return a canonical modality fallback for typed IR hydration paths."""

        return canonical_modality_operator(self.modality, self.norm_type)

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


DEFAULT_IR_PROVENANCE_SLOTS = (
    "actor",
    "modality",
    "action",
    "mental_state",
    "recipient",
    "conditions",
    "exceptions",
    "temporal_constraints",
    "cross_references",
)

DEFAULT_PHASE8_QUALITY_CORE_SLOTS = (
    "actor",
    "modality",
    "action",
)

DEFAULT_PHASE8_QUALITY_OPTIONAL_SLOTS = (
    "conditions",
    "exceptions",
    "temporal_constraints",
    "cross_references",
)

_FIELD_SPAN_ALIASES = {
    "actor": ("actor", "subject"),
    "modality": ("modality", "deontic_operator", "modal"),
    "action": ("action",),
    "mental_state": ("mental_state", "mens_rea"),
    "recipient": ("recipient", "action_recipient", "beneficiary"),
    "conditions": ("conditions", "condition"),
    "exceptions": ("exceptions", "exception"),
    "temporal_constraints": ("temporal_constraints", "temporal_constraint"),
    "cross_references": ("cross_references", "cross_reference"),
}

_DECODER_WARNING_NON_BLOCKERS = {
    "cross_reference_requires_resolution",
    "enumerated_clause_requires_item_level_review",
    "exception_requires_scope_review",
    "overlong_action_span",
}


def parser_warnings_require_decoder_validation(warnings: Sequence[str]) -> bool:
    """Return whether parser warnings should block decoder reconstruction quality.

    Decoder reconstruction quality tracks whether normalized phrases can be
    rebuilt from grounded IR slots. A cross-reference resolution warning can be
    theorem-gating while still allowing source-grounded reconstruction, so it
    does not force decoder validation by itself.
    """

    for warning in warnings:
        normalized = str(warning or "").strip()
        if not normalized:
            continue
        if normalized in _DECODER_WARNING_NON_BLOCKERS:
            continue
        return True
    return False


def legal_norm_ir_phase8_required_slots(
    norm: "LegalNormIR",
    core_slots: Sequence[str] = DEFAULT_PHASE8_QUALITY_CORE_SLOTS,
    optional_slots: Sequence[str] = DEFAULT_PHASE8_QUALITY_OPTIONAL_SLOTS,
) -> List[str]:
    """Return per-norm Phase 8 slots required for quality-gate completeness.

    Phase 8 quality should require the core slots that the decoder actually
    renders for the norm family. Ordinary O/P/F norms stay strict on
    actor/modality/action. Definition and frame-style legal families express
    their force through fixed connectors, so they require only their
    source-grounded legal arguments. Optional legal slots are required only
    when that norm carries grounded data for them.
    """

    family_core_slots = _phase8_core_slots_for_norm(norm, core_slots)
    required: List[str] = []
    for slot in family_core_slots:
        slot_name = str(slot or "").strip()
        if slot_name and slot_name not in required:
            required.append(slot_name)

    for slot in optional_slots:
        slot_name = str(slot or "").strip()
        if not slot_name or slot_name in required:
            continue
        if not _ir_slot_value_is_empty(_phase8_slot_value(norm, slot_name)):
            required.append(slot_name)
    return required


def _phase8_core_slots_for_norm(
    norm: "LegalNormIR",
    default_core_slots: Sequence[str],
) -> Sequence[str]:
    """Return decoder-native required core slots for a legal norm family."""

    norm_type = str(getattr(norm, "norm_type", "") or "").strip().lower()
    modality = str(getattr(norm, "modality", "") or "").strip().upper()

    if norm_type == "definition" or modality == "DEF":
        return ("actor",)
    if norm_type in {"applicability", "exemption", "instrument_lifecycle"} or modality in {
        "APP",
        "EXEMPT",
        "LIFE",
    }:
        return ("actor", "action")
    return default_core_slots


def legal_norm_ir_slot_provenance(
    norm: LegalNormIR,
    slots: Sequence[str] = DEFAULT_IR_PROVENANCE_SLOTS,
) -> Dict[str, Any]:
    """Return deterministic source-grounding records for legally salient IR slots.

    The decoder/reconstruction quality loop needs to audit whether decoded legal
    phrases came from source-grounded IR slots. This helper reports each checked
    slot as grounded, missing, or ungrounded without changing proof-readiness or
    parser repair gates.
    """

    records: List[Dict[str, Any]] = []
    for slot in dict.fromkeys(str(slot) for slot in slots if slot):
        value = _phase8_slot_value(norm, slot)
        present = not _ir_slot_value_is_empty(value)
        spans = _ir_slot_spans(norm, slot, value)
        status = "grounded" if spans else "ungrounded" if present else "missing"
        records.append(
            {
                "slot": slot,
                "status": status,
                "present": present,
                "grounded": status == "grounded",
                "missing": status == "missing",
                "ungrounded": status == "ungrounded",
                "spans": spans,
                "value": _ir_slot_export_value(value),
            }
        )

    return {
        "source_id": norm.source_id,
        "support_span": norm.support_span.to_list(),
        "checked_slots": [record["slot"] for record in records],
        "grounded_slots": [record["slot"] for record in records if record["grounded"]],
        "missing_slots": [record["slot"] for record in records if record["missing"]],
        "ungrounded_slots": [record["slot"] for record in records if record["ungrounded"]],
        "slot_grounding": records,
    }


def _ir_slot_value_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _phase8_slot_value(norm: LegalNormIR, slot: str) -> Any:
    """Return a normalized slot value for Phase 8 requirement selection."""

    if slot == "cross_references":
        references = list(norm.cross_references or [])
        references.extend(
            reference
            for reference in list(norm.resolved_cross_references or [])
            if reference not in references
        )
        return references
    return getattr(norm, slot, None)


def _ir_slot_spans(norm: LegalNormIR, slot: str, value: Any) -> List[List[int]]:
    spans: List[List[int]] = []
    skip_field_aliases = False
    if slot == "mental_state":
        spans.extend(_mental_state_span_from_action(norm))
    elif slot == "action":
        action_span = _action_span_without_mental_state(norm)
        if action_span:
            spans.append(action_span)
            skip_field_aliases = True
    if not skip_field_aliases:
        for field_name in _FIELD_SPAN_ALIASES.get(slot, (slot,)):
            spans.extend(_normalized_span_records(norm.field_spans.get(field_name)))
    if slot == "actor" and norm.norm_type == "applicability":
        spans.extend(_nested_slot_spans(norm.cross_references))
    if (
        slot == "modality"
        and not spans
        and norm.norm_type in {"definition", "applicability", "exemption", "instrument_lifecycle", "purpose"}
    ):
        spans.extend(_normalized_span_records(norm.support_span.to_list()))
    spans.extend(_nested_slot_spans(value))
    if not spans and slot in {"actor", "action"}:
        spans.extend(_text_value_spans(norm, value))
    return _dedupe_spans(spans)


def _text_value_spans(norm: LegalNormIR, value: Any) -> List[List[int]]:
    """Return a support/source span for scalar slot text when fields are legacy-empty."""

    text = str(value or "").strip()
    if not text:
        return []

    support_text = str(norm.support_text or "")
    support_span = norm.support_span.to_list()
    if support_text and len(support_span) == 2:
        offset = support_text.lower().find(text.lower())
        if offset >= 0:
            return [[support_span[0] + offset, support_span[0] + offset + len(text)]]

    source_text = str(norm.source_text or "")
    if source_text:
        offset = source_text.lower().find(text.lower())
        if offset >= 0:
            return [[offset, offset + len(text)]]
    return []


def _mental_state_span_from_action(norm: LegalNormIR) -> List[List[int]]:
    explicit = _normalized_span_records(norm.field_spans.get("mental_state"))
    if explicit:
        return explicit

    action_spans = _normalized_span_records(norm.field_spans.get("action"))
    if not action_spans:
        return []
    mental_state = str(norm.mental_state or "").strip()
    action = str(norm.action or "").strip()
    if not mental_state or not re.match(
        r"^" + re.escape(mental_state) + r"\b",
        action,
        re.IGNORECASE,
    ):
        return []

    action_span = action_spans[0]
    return [[action_span[0], action_span[0] + len(mental_state)]]


def _action_span_without_mental_state(norm: LegalNormIR) -> List[int]:
    action_spans = _normalized_span_records(norm.field_spans.get("action"))
    if not action_spans:
        return []
    mental_spans = _mental_state_span_from_action(norm)
    if not mental_spans:
        return []
    mental_state = str(norm.mental_state or "").strip()
    action = str(norm.action or "").strip()
    if not re.match(
        r"^" + re.escape(mental_state) + r"\b\s+",
        action,
        re.IGNORECASE,
    ):
        return []
    return [mental_spans[0][1] + 1, action_spans[0][1]]


def _nested_slot_spans(value: Any) -> List[List[int]]:
    spans: List[List[int]] = []
    if isinstance(value, dict):
        for key in ("span", "source_span", "support_span", "clause_span"):
            spans.extend(_normalized_span_records(value.get(key)))
        for nested in value.values():
            if isinstance(nested, (dict, list, tuple)):
                spans.extend(_nested_slot_spans(nested))
    elif isinstance(value, (list, tuple)):
        for item in value:
            spans.extend(_nested_slot_spans(item))
    return spans


def _normalized_span_records(value: Any) -> List[List[int]]:
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(
        isinstance(item, int) for item in value
    ):
        return [[int(value[0]), int(value[1])]]
    if isinstance(value, (list, tuple)):
        spans: List[List[int]] = []
        for item in value:
            spans.extend(_normalized_span_records(item))
        return spans
    return []


def _dedupe_spans(spans: List[List[int]]) -> List[List[int]]:
    seen = set()
    deduped: List[List[int]] = []
    for span in spans:
        key = tuple(span)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(span)
    return deduped


def _ir_slot_export_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_ir_slot_export_value(item) for item in value]
    if isinstance(value, tuple):
        return [_ir_slot_export_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _ir_slot_export_value(item) for key, item in value.items()}
    return str(value)
