"""Deterministic decoder for typed legal norm IR.

The decoder is intentionally conservative: it renders normalized legal text
from ``LegalNormIR`` slots and fixed grammar only. It does not inspect raw legal
text to invent missing facts, and it keeps provenance for each rendered phrase
so reconstruction losses are auditable.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .ir import LegalNormIR


@dataclass(frozen=True)
class DecodedPhrase:
    """One phrase in a decoded legal sentence."""

    text: str
    slot: str
    spans: List[List[int]] = field(default_factory=list)
    fixed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecodedLegalText:
    """Decoded text plus source-grounding metadata."""

    source_id: str
    text: str
    phrases: List[DecodedPhrase]
    support_span: List[int]
    parser_warnings: List[str]
    missing_slots: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phrases"] = [phrase.to_dict() for phrase in self.phrases]
        return data


def decode_legal_norm_ir(norm: LegalNormIR) -> DecodedLegalText:
    """Render normalized legal text from a deterministic legal norm IR."""

    if norm.modality == "DEF" or norm.norm_type == "definition":
        phrases, missing = _decode_definition(norm)
    elif norm.modality == "APP" or norm.norm_type == "applicability":
        phrases, missing = _decode_applicability(norm)
    elif norm.modality == "EXEMPT" or norm.norm_type == "exemption":
        phrases, missing = _decode_exemption(norm)
    elif norm.modality == "LIFE" or norm.norm_type == "instrument_lifecycle":
        phrases, missing = _decode_lifecycle(norm)
    else:
        phrases, missing = _decode_deontic_clause(norm)

    text = _sentence_from_phrases(phrases)
    return DecodedLegalText(
        source_id=norm.source_id,
        text=text,
        phrases=phrases,
        support_span=norm.support_span.to_list(),
        parser_warnings=list(norm.quality.parser_warnings),
        missing_slots=missing,
    )


def _decode_deontic_clause(norm: LegalNormIR) -> tuple[List[DecodedPhrase], List[str]]:
    phrases: List[DecodedPhrase] = []
    missing: List[str] = []

    actor = _clean_text(norm.actor)
    action = _clean_text(_action_without_leading_modal(norm.action))
    recipient = _recipient_phrase_text(norm.recipient)
    mental_state = _clean_text(norm.mental_state)
    modal = _modal_phrase(norm.modality)

    if actor:
        phrases.append(_phrase(actor, "actor", norm))
    else:
        missing.append("actor")

    if modal:
        phrases.append(_phrase(modal, "modality", norm))
    else:
        missing.append("modality")

    if mental_state and not _text_already_contains(action, mental_state):
        phrases.append(_phrase(mental_state, "mental_state", norm))

    if action:
        phrases.append(_phrase(action, "action", norm))
    else:
        missing.append("action")

    if recipient and not _text_already_contains(action, recipient):
        phrases.append(_fixed_phrase("to", "recipient_connector"))
        phrases.append(_phrase(recipient, "recipient", norm))

    for condition in norm.conditions:
        condition_text = _slot_text(condition)
        if condition_text:
            phrases.append(_fixed_phrase("if", "condition_connector"))
            phrases.append(_detail_phrase(condition_text, "conditions", condition, norm))

    for temporal in norm.temporal_constraints:
        temporal_text = _temporal_phrase_text(temporal)
        if temporal_text and not _text_already_contains(action, temporal_text):
            phrases.append(_detail_phrase(temporal_text, "temporal_constraints", temporal, norm))

    for exception in norm.exceptions:
        exception_text = _slot_text(exception)
        if exception_text:
            connector = "except" if exception_text.lower().startswith("as ") else "unless"
            if exception_text.lower().startswith(("unless ", "except ")):
                phrases.append(_detail_phrase(exception_text, "exceptions", exception, norm))
            else:
                phrases.append(_fixed_phrase(connector, "exception_connector"))
                phrases.append(_detail_phrase(exception_text, "exceptions", exception, norm))

    return phrases, missing


def _decode_definition(norm: LegalNormIR) -> tuple[List[DecodedPhrase], List[str]]:
    phrases: List[DecodedPhrase] = []
    missing: List[str] = []
    term = _clean_text(norm.actor)
    body = _definition_body(norm)

    if term:
        phrases.append(_fixed_phrase("the term", "definition_connector"))
        phrases.append(_phrase(term, "actor", norm))
    else:
        missing.append("defined_term")

    phrases.append(_fixed_phrase("means", "definition_connector"))
    if body:
        phrases.append(_phrase(body, "definition_body", norm))
    else:
        missing.append("definition_body")
    return phrases, missing


def _decode_applicability(norm: LegalNormIR) -> tuple[List[DecodedPhrase], List[str]]:
    phrases: List[DecodedPhrase] = []
    missing: List[str] = []
    scope = _clean_text(norm.actor)
    target = _clean_text(_strip_prefix(norm.action, ("apply to", "applies to")))

    if scope:
        phrases.append(_phrase(scope, "actor", norm))
    else:
        missing.append("scope")
    phrases.append(_fixed_phrase("applies to", "applicability_connector"))
    if target:
        phrases.append(_phrase(target, "action", norm))
    else:
        missing.append("applicability_target")
    return phrases, missing


def _decode_exemption(norm: LegalNormIR) -> tuple[List[DecodedPhrase], List[str]]:
    phrases: List[DecodedPhrase] = []
    missing: List[str] = []
    target = _clean_text(norm.actor)
    requirement = _clean_text(_strip_prefix(norm.action, ("exempt from", "not apply to")))

    if target:
        phrases.append(_phrase(target, "actor", norm))
    else:
        missing.append("exemption_target")
    phrases.append(_fixed_phrase("is exempt from", "exemption_connector"))
    if requirement:
        phrases.append(_phrase(requirement, "action", norm))
    else:
        missing.append("requirement")
    return phrases, missing


def _decode_lifecycle(norm: LegalNormIR) -> tuple[List[DecodedPhrase], List[str]]:
    phrases: List[DecodedPhrase] = []
    missing: List[str] = []
    instrument = _clean_text(norm.actor)
    action = _clean_text(norm.action)

    if instrument:
        phrases.append(_phrase(instrument, "actor", norm))
    else:
        missing.append("instrument")
    if action:
        if action.lower().startswith("valid for "):
            phrases.append(_fixed_phrase("is", "lifecycle_connector"))
        phrases.append(_phrase(action, "action", norm))
    else:
        missing.append("lifecycle_action")
    return phrases, missing


def _phrase(text: str, slot: str, norm: LegalNormIR) -> DecodedPhrase:
    return DecodedPhrase(text=_clean_text(text), slot=slot, spans=_slot_spans(norm, slot))


def _detail_phrase(
    text: str,
    slot: str,
    detail: Mapping[str, Any],
    norm: LegalNormIR,
) -> DecodedPhrase:
    span = detail.get("span") or detail.get("clause_span") or []
    spans = [_coerce_span(span)] if _coerce_span(span) else _slot_spans(norm, slot)
    return DecodedPhrase(text=_clean_text(text), slot=slot, spans=spans)


def _fixed_phrase(text: str, slot: str) -> DecodedPhrase:
    return DecodedPhrase(text=text, slot=slot, fixed=True)


def _modal_phrase(modality: str) -> str:
    return {
        "O": "shall",
        "P": "may",
        "F": "shall not",
    }.get(str(modality or "").upper(), "")


def _temporal_phrase_text(record: Mapping[str, Any]) -> str:
    value = _slot_text(record)
    if not value:
        return ""
    lowered = value.lower()
    if lowered.startswith(("within ", "by ", "before ", "after ", "not later than ", "no later than ")):
        return value
    if re.search(r"\b\d+\b", value) or " after " in lowered or " before " in lowered:
        return f"within {value}"
    return value


def _definition_body(norm: LegalNormIR) -> str:
    for key in ("definition_body", "body", "defined_as"):
        value = norm.legal_frame.get(key) or norm.formal_terms.get(key)
        if value:
            return _clean_text(str(value))
    action = _clean_text(norm.action)
    return _strip_prefix(action, ("mean", "means", "defined as"))


def _slot_text(record: Mapping[str, Any]) -> str:
    for key in ("value", "normalized_text", "raw_text", "text", "canonical_citation", "citation"):
        value = record.get(key)
        if value:
            return _clean_text(str(value))
    return ""


def _slot_spans(norm: LegalNormIR, slot: str) -> List[List[int]]:
    field_spans = norm.field_spans if isinstance(norm.field_spans, Mapping) else {}
    candidates = [slot]
    candidates.extend({"actor": ["subject"], "recipient": ["action_recipient"]}.get(slot, []))
    for key in candidates:
        spans = _coerce_spans(field_spans.get(key))
        if spans:
            return spans
    fallback = norm.support_span.to_list()
    return [fallback] if fallback != [0, 0] else []


def _coerce_spans(value: Any) -> List[List[int]]:
    span = _coerce_span(value)
    if span:
        return [span]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        spans = [_coerce_span(item) for item in value]
        return [item for item in spans if item]
    return []


def _coerce_span(value: Any) -> List[int]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        try:
            return [int(value[0]), int(value[1])]
        except (TypeError, ValueError):
            return []
    return []


def _sentence_from_phrases(phrases: Iterable[DecodedPhrase]) -> str:
    text = " ".join(phrase.text for phrase in phrases if phrase.text).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    if text:
        text = text[0].upper() + text[1:]
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _action_without_leading_modal(action: str) -> str:
    return re.sub(r"^(?:shall not|must not|may not|shall|must|may)\s+", "", action.strip(), flags=re.IGNORECASE)


def _recipient_phrase_text(recipient: str) -> str:
    """Return a normalized recipient phrase without duplicating a connector."""
    return re.sub(r"^(?:to|for)\s+", "", _clean_text(recipient), flags=re.IGNORECASE)


def _strip_prefix(text: str, prefixes: Sequence[str]) -> str:
    value = _clean_text(text)
    lowered = value.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix + " "):
            return value[len(prefix) :].strip()
        if lowered == prefix:
            return ""
    return value


def _clean_text(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n.;:")
    return value


def _text_already_contains(container: str, phrase: str) -> bool:
    left = re.sub(r"[^a-z0-9]+", " ", container.lower()).strip()
    right = re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
    return bool(left and right and right in left)
