"""Formula builders for deterministic legal norm IR."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from .ir import LegalNormIR


_MENTAL_STATE_TERMS = {
    "knowingly",
    "intentionally",
    "willfully",
    "recklessly",
    "negligently",
}
_LEGAL_REFERENCE_TEXT_RE = re.compile(r"\b(?:section|subsection|chapter|title|article|part)\s+[0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*\b", re.IGNORECASE)


def build_deontic_formula_from_ir(norm: LegalNormIR) -> str:
    """Build a deterministic deontic/frame-logic formula from typed IR."""

    operator = norm.modality
    if operator == "DEF":
        subject = normalize_predicate_name(norm.actor or "DefinedTerm")
        return f"Definition({subject})"
    if operator == "APP":
        subject = normalize_predicate_name(norm.actor or "Scope")
        target = normalize_predicate_name(_applicability_target(norm.action or "Apply"))
        return f"AppliesTo({subject}, {target})"
    if operator == "EXEMPT":
        subject = normalize_predicate_name(norm.actor or "Entity")
        action_text = norm.action or "Requirement"
        if action_text.lower().startswith("exempt from "):
            action_text = action_text[len("exempt from ") :]
        target = normalize_predicate_name(action_text)
        return f"ExemptFrom({subject}, {target})"
    if operator == "LIFE" or norm.norm_type == "instrument_lifecycle":
        subject = normalize_predicate_name(norm.actor or "Instrument")
        action_text = norm.action or "lifecycle"
        lowered = action_text.lower()
        if lowered.startswith("valid for "):
            duration = action_text[len("valid for ") :]
            return f"ValidFor({subject}, {normalize_predicate_name(duration)})"
        if lowered.startswith("expires "):
            anchor = action_text[len("expires ") :]
            return f"ExpiresAfter({subject}, {normalize_predicate_name(anchor)})"
        return f"Lifecycle({subject}, {normalize_predicate_name(action_text)})"

    action_text = _action_without_mental_state(norm.action or "Action")
    action_pred = normalize_predicate_name(action_text) if action_text else "Action"
    subject_pred = normalize_predicate_name(norm.actor or "Agent")
    condition_preds = _unique_predicates(_formula_condition_texts(norm))
    exception_preds = _unique_predicates(_formula_exception_texts(norm))
    temporal_preds = [
        normalize_predicate_name(_temporal_predicate_text(item))
        for item in norm.temporal_constraints[:3]
        if isinstance(item, dict)
    ]
    modifiers = temporal_preds
    mental_state_pred = normalize_predicate_name(norm.mental_state)
    if mental_state_pred and mental_state_pred != "P":
        modifiers.append(mental_state_pred)

    inner_parts = [f"{subject_pred}(x)"]
    inner_parts.extend(f"{pred}(x)" for pred in condition_preds[:3])
    inner_parts.extend(f"{pred}(x)" for pred in modifiers)
    inner_parts.extend(f"¬{pred}(x)" for pred in exception_preds[:3])
    inner = " ∧ ".join(inner_parts)
    return f"{operator}(∀x ({inner} → {action_pred}(x)))"


def build_deontic_formula_record_from_ir(norm: LegalNormIR) -> Dict[str, Any]:
    """Build a source-grounded formula export record from typed IR.

    This record API is intentionally richer than the legacy string formula API:
    downstream proof, metrics, and export code can inspect provenance and
    deterministic blockers without reparsing natural-language source text.
    """

    formula = build_deontic_formula_from_ir(norm)
    parser_warnings = list(norm.quality.parser_warnings)
    blockers = list(norm.blockers)
    omitted_slots = _omitted_formula_slots(norm)

    return {
        "formula_id": _stable_formula_id(norm.source_id, formula),
        "source_id": norm.source_id,
        "canonical_citation": norm.canonical_citation,
        "parent_source_id": norm.parent_source_id,
        "enumeration_label": norm.enumeration_label,
        "enumeration_index": norm.enumeration_index,
        "is_enumerated_child": norm.is_enumerated_child,
        "target_logic": _target_logic_for_norm(norm),
        "formula": formula,
        "modality": norm.modality,
        "norm_type": norm.norm_type,
        "support_span": norm.support_span.to_list(),
        "field_spans": dict(norm.field_spans),
        "proof_ready": norm.proof_ready,
        "requires_validation": not norm.proof_ready,
        "blockers": blockers,
        "parser_warnings": parser_warnings,
        "omitted_formula_slots": omitted_slots,
        "schema_version": norm.schema_version,
    }


def build_deontic_formula_records_from_irs(norms: Iterable[LegalNormIR]) -> List[Dict[str, Any]]:
    """Build ordered formula export records for already parsed legal norms.

    This is the multi-norm companion to ``build_deontic_formula_record_from_ir``;
    callers such as ``DeonticConverter`` can expose every expanded child norm
    without reparsing source text or changing legacy first-formula behavior.
    """

    return [build_deontic_formula_record_from_ir(norm) for norm in norms]


def parser_element_to_formula_record(element: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility helper for callers that still hold parser dictionaries."""

    return build_deontic_formula_record_from_ir(LegalNormIR.from_parser_element(element))


def _stable_formula_id(source_id: str, formula: str) -> str:
    seed = f"{source_id}|{formula}"
    import hashlib

    return "formula:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _target_logic_for_norm(norm: LegalNormIR) -> str:
    if norm.modality in {"APP", "EXEMPT", "LIFE"} or norm.norm_type in {
        "applicability",
        "exemption",
        "instrument_lifecycle",
    }:
        return "frame_logic"
    return "deontic"


def parser_element_to_formula(element: Dict[str, Any]) -> str:
    """Compatibility helper for callers that still hold parser dictionaries."""

    return build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))


def normalize_predicate_name(name: str) -> str:
    """Normalize a legal phrase to a stable predicate or symbol name."""

    if not name:
        return "P"
    name = re.sub(r"[_\-]+", " ", str(name))
    name = re.sub(r"[^0-9A-Za-z\s]", "", name)
    words = name.strip().split()
    filtered_words = [
        word
        for word in words
        if word.lower() not in ["the", "a", "an", "of", "in", "on", "at", "to", "for", "with", "by"]
    ]
    if not filtered_words:
        return "P"
    return "".join(word.capitalize() for word in filtered_words)


def _slot_texts(items: Iterable[Dict[str, Any]]) -> List[str]:
    texts: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get("value") or item.get("normalized_text") or item.get("raw_text")
        if value:
            texts.append(str(value))
    return texts


def _unique_predicates(texts: Iterable[str]) -> List[str]:
    """Return stable predicate names while suppressing duplicate slot aliases."""

    predicates: List[str] = []
    seen = set()
    for text in texts:
        predicate = normalize_predicate_name(text)
        if not predicate or predicate == "P" or predicate in seen:
            continue
        predicates.append(predicate)
        seen.add(predicate)
    return predicates


def _formula_exception_texts(norm: LegalNormIR) -> List[str]:
    """Return exception phrases that are substantive formula antecedents.

    Exceptions that only restate an unresolved legal cross reference, such as
    ``except as provided in section 552``, are provenance and proof blockers.
    They should not become factual predicates like ``¬AsProvidedSection552(x)``.
    """

    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references)
        + _slot_texts(norm.resolved_cross_references)
        + _slot_texts(norm.overrides)
        if str(value).strip()
    }

    texts: List[str] = []
    for item in norm.exceptions:
        if not isinstance(item, dict):
            continue
        value = item.get("value") or item.get("normalized_text") or item.get("raw_text")
        if not value:
            continue
        text = str(value).strip()
        if not text or _is_reference_exception(item, text, reference_values):
            continue
        texts.append(text)
    return texts


def _formula_condition_texts(norm: LegalNormIR) -> List[str]:
    """Return condition phrases that are substantive formula antecedents.

    Conditions that only restate an unresolved legal cross reference, such as
    ``subject to section 552``, are provenance and proof blockers. They should
    remain in IR/export metadata but should not become factual predicates like
    ``Section552(x)`` in theorem scaffolds.
    """

    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references)
        + _slot_texts(norm.resolved_cross_references)
        + _slot_texts(norm.overrides)
        if str(value).strip()
    }

    texts: List[str] = []
    for item in norm.conditions:
        if not isinstance(item, dict):
            continue
        value = item.get("value") or item.get("normalized_text") or item.get("raw_text")
        if not value:
            continue
        text = str(value).strip()
        if not text or _is_reference_condition(item, text, reference_values):
            continue
        texts.append(text)
    return texts


def _omitted_formula_slots(norm: LegalNormIR) -> Dict[str, List[Dict[str, Any]]]:
    """Return source-grounded slots intentionally omitted from theorem text."""

    omitted: Dict[str, List[Dict[str, Any]]] = {}
    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references)
        + _slot_texts(norm.resolved_cross_references)
        + _slot_texts(norm.overrides)
        if str(value).strip()
    }

    reference_conditions = [
        dict(item)
        for item in norm.conditions
        if isinstance(item, dict)
        and _is_reference_condition(
            item,
            str(item.get("value") or item.get("normalized_text") or item.get("raw_text") or ""),
            reference_values,
        )
    ]
    reference_exceptions = [
        dict(item)
        for item in norm.exceptions
        if isinstance(item, dict)
        and _is_reference_exception(
            item,
            str(item.get("value") or item.get("normalized_text") or item.get("raw_text") or ""),
            reference_values,
        )
    ]
    if reference_conditions:
        omitted["conditions"] = reference_conditions
    if reference_exceptions:
        omitted["exceptions"] = reference_exceptions
    if norm.overrides:
        omitted["overrides"] = [dict(item) for item in norm.overrides if isinstance(item, dict)]
    return omitted


def _is_reference_condition(item: Dict[str, Any], text: str, reference_values: Iterable[str]) -> bool:
    condition_type = str(item.get("condition_type") or item.get("type") or "").lower()
    reference_type = str(item.get("reference_type") or "").lower()
    if reference_type in {"section", "subsection", "chapter", "title", "article", "part", "cross_reference"}:
        return True

    normalized = text.strip().lower()
    if reference_values and any(reference and reference in normalized for reference in reference_values):
        return True
    return condition_type == "subject_to" and bool(_LEGAL_REFERENCE_TEXT_RE.search(text))


def _is_reference_exception(item: Dict[str, Any], text: str, reference_values: Iterable[str]) -> bool:
    reference_type = str(item.get("reference_type") or item.get("type") or "").lower()
    if reference_type in {"section", "subsection", "chapter", "title", "article", "part", "cross_reference"}:
        return True

    normalized = text.strip().lower()
    return any(reference and reference in normalized for reference in reference_values)


def _temporal_predicate_text(item: Dict[str, Any]) -> str:
    """Return a stable temporal predicate phrase from a structured slot."""

    temporal_type = str(item.get("type") or "Temporal")
    value = item.get("value") or item.get("normalized_text") or item.get("raw_text")
    if value:
        return f"{temporal_type} {value}"

    duration = item.get("duration") or item.get("deadline") or item.get("quantity")
    anchor = item.get("anchor") or item.get("anchor_event") or item.get("event")
    anchor_relation = _temporal_anchor_relation(item)
    if duration and anchor:
        return f"{temporal_type} {duration} {anchor_relation} {anchor}"
    if duration:
        return f"{temporal_type} {duration}"
    if anchor:
        return f"{temporal_type} {anchor}"
    return temporal_type


def _temporal_anchor_relation(item: Dict[str, Any]) -> str:
    """Return the explicit relation between a duration and its anchor event."""

    for key in ("anchor_relation", "relation", "connector"):
        value = str(item.get(key) or "").strip().lower()
        if value in {"after", "before"}:
            return value
        if "before" in value:
            return "before"
        if "after" in value or value.startswith("upon"):
            return "after"

    return "after"


def _action_without_mental_state(action: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'’\-]*", action or "")
    if words and words[0].lower() in _MENTAL_STATE_TERMS:
        return " ".join(words[1:]).strip()
    return action


def _applicability_target(action: str) -> str:
    """Return the regulated target phrase from an applicability action slot."""

    text = str(action or "").strip()
    text = re.sub(r"^apply\s+to\s+", "", text, flags=re.IGNORECASE)
    return re.sub(r"^apply\s+", "", text, flags=re.IGNORECASE)
