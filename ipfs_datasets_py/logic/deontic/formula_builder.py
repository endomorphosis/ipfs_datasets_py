"""Formula builders for deterministic legal norm IR."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .ir import LegalNormIR


_MENTAL_STATE_TERMS = {
    "knowingly",
    "intentionally",
    "willfully",
    "recklessly",
    "negligently",
}
_LEGAL_REFERENCE_TEXT_RE = re.compile(
    r"(?:\b(?:section|subsection|chapter|title|article|part)\s+|§\s*)"
    r"([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)\b",
    re.IGNORECASE,
)
_LOCAL_SCOPE_REFERENCE_EXCEPTION_RE = re.compile(
    r"^(?:as\s+(?:otherwise\s+)?provided\s+in|(?:otherwise\s+)?provided\s+in|under|pursuant\s+to)\s+this\s+"
    r"(section|subsection|chapter|title|article|part)$",
    re.IGNORECASE,
)
_LOCAL_SCOPE_REFERENCE_CONDITION_RE = re.compile(
    r"^(?:this|current)\s+(section|subsection|chapter|title|article|part)$",
    re.IGNORECASE,
)


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
    deterministic_resolution = _deterministic_formula_resolution(norm, blockers)
    proof_ready = norm.proof_ready or bool(deterministic_resolution)
    requires_validation = not proof_ready
    repair_required = requires_validation

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
        "proof_ready": proof_ready,
        "requires_validation": requires_validation,
        "repair_required": repair_required,
        "blockers": blockers,
        "parser_warnings": parser_warnings,
        "omitted_formula_slots": omitted_slots,
        "deterministic_resolution": deterministic_resolution,
        "schema_version": norm.schema_version,
    }


def build_deontic_formula_records_from_irs(norms: Iterable[LegalNormIR]) -> List[Dict[str, Any]]:
    """Build ordered formula export records for already parsed legal norms.

    This is the multi-norm companion to ``build_deontic_formula_record_from_ir``;
    callers such as ``DeonticConverter`` can expose every expanded child norm
    without reparsing source text or changing legacy first-formula behavior.
    """

    resolved_norms = _with_same_document_reference_resolutions(list(norms))
    return [build_deontic_formula_record_from_ir(norm) for norm in resolved_norms]


def parser_element_to_formula_record(element: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility helper for callers that still hold parser dictionaries."""

    return build_deontic_formula_record_from_ir(LegalNormIR.from_parser_element(element))


def _with_same_document_reference_resolutions(norms: List[LegalNormIR]) -> List[LegalNormIR]:
    """Resolve exact numbered section references against the same IR batch.

    Single-record formula building stays conservative. Batch callers such as
    converter metadata have document context, so they can clear a reference-only
    exception or condition when the cited section is actually present in the
    same parsed batch. The cited section remains provenance only and is not
    emitted as a factual predicate in the formula antecedent.
    """

    section_index = _same_document_section_index(norms)
    if not section_index:
        return norms
    return [_resolve_norm_same_document_references(norm, section_index) for norm in norms]


def _same_document_section_index(norms: Sequence[LegalNormIR]) -> Dict[str, str]:
    section_index: Dict[str, str] = {}
    for norm in norms:
        citation = _canonical_section_citation(norm.canonical_citation)
        if citation and norm.source_id:
            section_index.setdefault(citation, norm.source_id)
        for citation in _section_context_citations(norm):
            if citation and norm.source_id:
                section_index.setdefault(citation, norm.source_id)
    return section_index


def _resolve_norm_same_document_references(
    norm: LegalNormIR,
    section_index: Mapping[str, str],
) -> LegalNormIR:
    additions: List[Dict[str, Any]] = []
    existing = {
        _canonical_section_citation(str(item.get("canonical_citation") or item.get("value") or ""))
        for item in norm.resolved_cross_references
        if isinstance(item, dict)
    }

    for reference in norm.cross_references:
        if not isinstance(reference, dict) or _reference_is_external(reference):
            continue

        citation = _reference_section_citation(reference)
        if not citation or citation not in section_index or citation in existing:
            continue

        additions.append(
            {
                "reference_type": "section",
                "target": citation[len("section ") :],
                "canonical_citation": citation,
                "value": citation,
                "resolution_scope": "same_document",
                "same_document": True,
                "resolved_source_id": section_index[citation],
                "source_id": section_index[citation],
                "span": reference.get("span", []),
            }
        )
        existing.add(citation)

    if not additions:
        return norm
    return replace(norm, resolved_cross_references=list(norm.resolved_cross_references) + additions)


def _reference_section_citation(reference: Mapping[str, Any]) -> str:
    for key in ("canonical_citation", "citation", "value", "normalized_text", "raw_text", "text"):
        citation = _canonical_section_citation(str(reference.get(key) or ""))
        if citation:
            return citation

    reference_type = str(reference.get("reference_type") or reference.get("type") or "").strip().lower()
    target = str(reference.get("target") or reference.get("section") or "").strip()
    if reference_type == "section" and target and target.lower() not in {"this", "current"}:
        return _canonical_section_citation(f"section {target}")
    return ""


def _canonical_section_citation(text: str) -> str:
    match = _LEGAL_REFERENCE_TEXT_RE.search(str(text or ""))
    if not match:
        return ""
    raw = match.group(0).strip().lower()
    if raw.startswith("§"):
        return f"section {match.group(1).lower()}"
    return raw


def _section_context_citations(norm: LegalNormIR) -> List[str]:
    """Return exact numbered section citations carried by parser context.

    Some parser batches preserve the current section only in ``section_context``
    rather than on ``canonical_citation``. Treat that source-grounded context as
    same-document evidence for exact numbered section references, while still
    rejecting empty, local-self, and non-numbered values.
    """

    context = norm.section_context
    if not isinstance(context, dict):
        return []

    citations: List[str] = []
    for key in (
        "canonical_citation",
        "citation",
        "section_citation",
        "current_section_citation",
    ):
        citation = _canonical_section_citation(str(context.get(key) or ""))
        if citation and citation not in citations:
            citations.append(citation)

    for key in ("section", "section_number", "current_section", "current_section_number"):
        value = str(context.get(key) or "").strip()
        if not value or value.lower() in {"this", "current"}:
            continue
        citation = _canonical_section_citation(f"section {value}")
        if citation and citation not in citations:
            citations.append(citation)

    return citations


def _reference_is_external(reference: Mapping[str, Any]) -> bool:
    for key in ("resolution_scope", "document_scope", "source_scope", "scope"):
        value = str(reference.get(key) or "").strip().lower().replace("-", "_")
        if value in {"external", "external_document", "other_document"}:
            return True
    return False


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
    if _is_local_scope_reference_condition_text(normalized):
        return True
    if reference_values and any(reference and reference in normalized for reference in reference_values):
        return True
    return condition_type == "subject_to" and bool(_LEGAL_REFERENCE_TEXT_RE.search(text))


def _is_reference_exception(item: Dict[str, Any], text: str, reference_values: Iterable[str]) -> bool:
    reference_type = str(item.get("reference_type") or item.get("type") or "").lower()
    if reference_type in {"section", "subsection", "chapter", "title", "article", "part", "cross_reference"}:
        return True

    normalized = text.strip().lower()
    if _is_local_scope_reference_exception_text(normalized):
        return True
    if _LEGAL_REFERENCE_TEXT_RE.search(normalized):
        return normalized.startswith(("as provided", "provided in", "under ", "pursuant to "))
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


def _deterministic_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Return a narrow deterministic formula-level resolution when safe.

    Parser-level theorem promotion remains conservative. This helper can mark
    an exported formula record proof-ready only when all unresolved blockers are
    addressed by source-grounded IR slots that already appear in the formula.

    Parser-level theorem promotion remains conservative. This helper only
    promotes the exported frame formula for local applicability clauses where
    the unresolved reference is the clause's own scope, e.g. ``this section``.
    External references such as ``the chapter`` or numbered sections stay
    blocked until a citation resolver supplies source-grounded context.
    """

    exception_resolution = _standard_exception_formula_resolution(norm, blockers)
    if exception_resolution:
        return exception_resolution

    override_resolution = _pure_override_formula_resolution(norm, blockers)
    if override_resolution:
        return override_resolution

    reference_exception_resolution = _resolved_reference_exception_formula_resolution(norm, blockers)
    if reference_exception_resolution:
        return reference_exception_resolution

    local_reference_exception_resolution = _local_scope_reference_exception_formula_resolution(norm, blockers)
    if local_reference_exception_resolution:
        return local_reference_exception_resolution

    local_reference_condition_resolution = _local_scope_reference_condition_formula_resolution(norm, blockers)
    if local_reference_condition_resolution:
        return local_reference_condition_resolution

    reference_condition_resolution = _resolved_reference_condition_formula_resolution(norm, blockers)
    if reference_condition_resolution:
        return reference_condition_resolution

    if norm.modality != "APP" or norm.norm_type != "applicability":
        return {}

    allowed_blockers = {"cross_reference_requires_resolution", "llm_repair_required"}
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}

    actor_text = norm.actor.strip().lower()
    if not re.match(r"^this\s+(section|chapter|title|article|part)$", actor_text):
        return {}

    if not norm.action.strip():
        return {}

    return {
        "type": "local_scope_applicability",
        "resolved_blockers": sorted(blocker_set),
        "scope": norm.actor,
        "reason": "local self-scope applicability formula is source-grounded",
    }


def _standard_exception_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve simple substantive exceptions at formula-record level.

    A clause like ``The applicant shall obtain a permit unless approval is
    denied`` already has a deterministic IR exception slot and the formula
    includes that slot as a negated antecedent.  The record can be proof-ready
    without changing parser-level blockers when the exception is a single,
    non-reference phrase and no precedence/citation review is pending.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.exceptions:
        return {}
    if norm.overrides or norm.cross_references or norm.resolved_cross_references:
        return {}

    allowed_blockers = {"exception_requires_scope_review", "llm_repair_required"}
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}

    substantive_exceptions = _formula_exception_texts(norm)
    if len(substantive_exceptions) != 1:
        return {}

    exception_record = next(
        (item for item in norm.exceptions if isinstance(item, dict)),
        {},
    )
    exception_text = substantive_exceptions[0].strip()
    if not exception_text:
        return {}
    if _exception_text_needs_external_resolution(exception_text):
        return {}

    return {
        "type": "standard_substantive_exception",
        "resolved_blockers": sorted(blocker_set),
        "exception": exception_text,
        "exception_span": exception_record.get("span", []),
        "reason": "single substantive exception is represented as a negated formula antecedent",
    }


def _pure_override_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve pure precedence overrides at formula-record level.

    A clause such as ``Notwithstanding section 5.01.020, the Director may issue
    a variance`` has a source-grounded operative permission plus a precedence
    reference. The precedence slot remains exported as omitted provenance, but
    the operative formula can be proof-ready when no other unresolved semantic
    slot is present. Parser-level theorem promotion remains conservative.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if len(norm.overrides) != 1:
        return {}
    if norm.conditions or norm.exceptions or norm.temporal_constraints:
        return {}

    allowed_blockers = {
        "cross_reference_requires_resolution",
        "override_clause_requires_precedence_review",
        "llm_repair_required",
    }
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "override_clause_requires_precedence_review" not in blocker_set:
        return {}

    override_record = next((item for item in norm.overrides if isinstance(item, dict)), {})
    override_text = _slot_primary_text(override_record)
    if not override_text:
        return {}

    reference_texts = [_slot_primary_text(item) for item in norm.cross_references if isinstance(item, dict)]
    for reference_text in reference_texts:
        if reference_text and reference_text.lower() not in override_text.lower():
            return {}

    return {
        "type": "pure_precedence_override",
        "resolved_blockers": sorted(blocker_set),
        "override": override_text,
        "override_span": override_record.get("span", []),
        "reason": "single source-grounded precedence override is exported as provenance outside the operative formula",
    }


def _resolved_reference_exception_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve reference-only exceptions when citation resolution is explicit.

    A clause such as ``except as provided in section 552`` should not fabricate
    a factual predicate in the theorem text. It can still be proof-ready at the
    formula/export layer when the omitted exception is backed by same-document
    ``resolved_cross_references`` metadata. Parser-level theorem promotion stays
    conservative because precedence and scope review remain visible as blockers.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.exceptions or not norm.cross_references:
        return {}
    if norm.conditions or norm.overrides:
        return {}

    allowed_blockers = {
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
        "llm_repair_required",
    }
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "cross_reference_requires_resolution" not in blocker_set:
        return {}
    if "exception_requires_scope_review" not in blocker_set:
        return {}

    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references) + _slot_texts(norm.resolved_cross_references)
        if str(value).strip()
    }
    reference_exceptions = [
        item
        for item in norm.exceptions
        if isinstance(item, dict)
        and _is_reference_exception(item, _slot_primary_text(item), reference_values)
    ]
    if len(reference_exceptions) != len(norm.exceptions):
        return {}

    resolved_references = _same_document_reference_records(norm)
    if not resolved_references:
        return {}

    resolved_texts = [_reference_resolution_text(item) for item in resolved_references]
    for exception in reference_exceptions:
        exception_text = _slot_primary_text(exception).lower()
        if not exception_text:
            return {}
        if not any(_reference_text_matches_slot(reference_text, exception_text) for reference_text in resolved_texts):
            return {}

    return {
        "type": "resolved_same_document_reference_exception",
        "resolved_blockers": sorted(blocker_set),
        "references": resolved_texts,
        "exception_spans": [item.get("span", []) for item in reference_exceptions],
        "reason": "reference-only exception is backed by explicit same-document cross-reference resolution",
    }


def _resolved_reference_condition_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve reference-only conditions when citation resolution is explicit.

    A clause such as ``Subject to section 552, the Secretary shall publish the
    notice`` should not fabricate a factual predicate like ``Section552(x)``.
    It can still become proof-ready at the formula/export layer when every
    omitted condition is a legal reference backed by explicit same-document
    resolution. Parser-level theorem promotion remains conservative.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.conditions or not norm.cross_references:
        return {}
    if norm.exceptions or norm.overrides:
        return {}

    allowed_blockers = {
        "cross_reference_requires_resolution",
        "llm_repair_required",
    }
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "cross_reference_requires_resolution" not in blocker_set:
        return {}

    reference_values = {
        str(value).strip().lower()
        for value in _slot_texts(norm.cross_references) + _slot_texts(norm.resolved_cross_references)
        if str(value).strip()
    }
    reference_conditions = [
        item
        for item in norm.conditions
        if isinstance(item, dict)
        and _is_reference_condition(item, _slot_primary_text(item), reference_values)
    ]
    if len(reference_conditions) != len(norm.conditions):
        return {}

    resolved_references = _same_document_reference_records(norm)
    if not resolved_references:
        return {}

    resolved_texts = [_reference_resolution_text(item) for item in resolved_references]
    for condition in reference_conditions:
        condition_text = _slot_primary_text(condition).lower()
        if not condition_text:
            return {}
        if not any(_reference_text_matches_slot(reference_text, condition_text) for reference_text in resolved_texts):
            return {}

    return {
        "type": "resolved_same_document_reference_condition",
        "resolved_blockers": sorted(blocker_set),
        "references": resolved_texts,
        "condition_spans": [item.get("span", []) for item in reference_conditions],
        "reason": "reference-only condition is backed by explicit same-document cross-reference resolution",
    }


def _local_scope_reference_condition_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve exact local self-reference conditions at formula-record level.

    A clause such as ``Subject to this section, the Secretary shall publish the
    notice`` carries local provenance, not a factual precondition. The condition
    remains exported as an omitted source-grounded slot, but the operative
    formula can be proof-ready when no other unresolved semantic slot is present.
    Numbered and external references stay blocked by the existing same-document
    reference resolver.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.conditions:
        return {}
    if norm.exceptions or norm.overrides:
        return {}

    allowed_blockers = {"cross_reference_requires_resolution", "llm_repair_required"}
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "cross_reference_requires_resolution" not in blocker_set:
        return {}

    reference_conditions = [
        item
        for item in norm.conditions
        if isinstance(item, dict)
        and _is_local_scope_reference_condition_text(_slot_primary_text(item))
    ]
    if len(reference_conditions) != len(norm.conditions):
        return {}

    local_reference_records = _local_scope_reference_records(norm)
    if (norm.cross_references or norm.resolved_cross_references) and not local_reference_records:
        return {}

    scopes = []
    for condition in reference_conditions:
        match = _LOCAL_SCOPE_REFERENCE_CONDITION_RE.match(_slot_primary_text(condition).strip())
        if not match:
            return {}
        scope = f"this {match.group(1).lower()}"
        if scope not in scopes:
            scopes.append(scope)

    for reference in local_reference_records:
        scope = _local_scope_reference_record_scope(reference)
        if not scope:
            return {}
        if scope.replace("current ", "this ") not in scopes:
            return {}

    return {
        "type": "local_scope_reference_condition",
        "resolved_blockers": sorted(blocker_set),
        "scopes": scopes,
        "condition_spans": [item.get("span", []) for item in reference_conditions],
        "reason": "local self-reference condition is exported as provenance outside the operative formula",
    }


def _local_scope_reference_exception_formula_resolution(norm: LegalNormIR, blockers: List[str]) -> Dict[str, Any]:
    """Resolve exact local self-reference exceptions at formula-record level.

    Clauses such as ``except as provided in this section`` point back to the
    same local scope rather than to an unresolved numbered or external legal
    reference. The exception remains exported as omitted provenance, but the
    operative formula can be proof-ready when no other unresolved semantic slot
    is present. This does not relax parser-level theorem promotion.
    """

    if norm.modality not in {"O", "P", "F"}:
        return {}
    if norm.norm_type not in {"obligation", "permission", "prohibition"}:
        return {}
    if not norm.actor.strip() or not norm.action.strip():
        return {}
    if not norm.exceptions:
        return {}
    if norm.conditions or norm.overrides:
        return {}

    allowed_blockers = {"exception_requires_scope_review", "llm_repair_required"}
    blocker_set = set(blockers)
    if not blocker_set or not blocker_set.issubset(allowed_blockers):
        return {}
    if "exception_requires_scope_review" not in blocker_set:
        return {}

    reference_exceptions = [
        item
        for item in norm.exceptions
        if isinstance(item, dict)
        and _is_local_scope_reference_exception_text(_slot_primary_text(item))
    ]
    if len(reference_exceptions) != len(norm.exceptions):
        return {}

    local_reference_records = _local_scope_reference_records(norm)
    if (norm.cross_references or norm.resolved_cross_references) and not local_reference_records:
        return {}

    scopes = []
    for exception in reference_exceptions:
        match = _LOCAL_SCOPE_REFERENCE_EXCEPTION_RE.match(_slot_primary_text(exception).strip())
        if not match:
            return {}
        scope = f"this {match.group(1).lower()}"
        if scope not in scopes:
            scopes.append(scope)

    for reference in local_reference_records:
        scope = _local_scope_reference_record_scope(reference)
        if not scope:
            return {}
        if scope not in scopes:
            return {}

    return {
        "type": "local_scope_reference_exception",
        "resolved_blockers": sorted(blocker_set),
        "scopes": scopes,
        "exception_spans": [item.get("span", []) for item in reference_exceptions],
        "reason": "local self-reference exception is exported as provenance outside the operative formula",
    }


def _same_document_reference_records(norm: LegalNormIR) -> List[Dict[str, Any]]:
    """Return source-grounded same-document reference records for exceptions.

    The parser may represent a deterministically resolved local reference in
    either ``resolved_cross_references`` or directly on ``cross_reference_details``
    with a ``same_document``/``resolution_scope`` marker. Treat both shapes as
    equivalent for formula-level repair clearance, while unmarked references
    remain blocked.
    """

    records: List[Dict[str, Any]] = []
    for item in norm.resolved_cross_references:
        if isinstance(item, dict) and _is_same_document_resolved_reference(item):
            records.append(item)

    if records:
        return records

    return [
        item
        for item in norm.cross_references
        if isinstance(item, dict) and _is_same_document_resolved_reference(item)
    ]


def _reference_text_matches_slot(reference_text: str, slot_text: str) -> bool:
    reference = str(reference_text or "").strip().lower()
    slot = str(slot_text or "").strip().lower()
    if not reference or not slot:
        return False
    if reference in slot:
        return True
    reference_citation = _canonical_section_citation(reference)
    slot_citation = _canonical_section_citation(slot)
    return bool(reference_citation and slot_citation and reference_citation == slot_citation)


def _local_scope_reference_records(norm: LegalNormIR) -> List[Dict[str, Any]]:
    """Return explicit local self-reference records, rejecting mixed references."""

    all_references = [
        item
        for item in list(norm.cross_references) + list(norm.resolved_cross_references)
        if isinstance(item, dict)
    ]
    if not all_references:
        return []

    local_references = [item for item in all_references if _local_scope_reference_record_scope(item)]
    if len(local_references) != len(all_references):
        return []
    return local_references


def _local_scope_reference_record_scope(item: Dict[str, Any]) -> str:
    """Return `this section` style scope for a structured local reference."""

    reference_type = str(item.get("reference_type") or item.get("type") or "").strip().lower()
    if reference_type not in {"section", "subsection", "chapter", "title", "article", "part"}:
        return ""

    target = str(item.get("target") or item.get("section") or item.get("subsection") or "").strip().lower()
    if target in {"this", f"this {reference_type}"}:
        return f"this {reference_type}"

    for key in ("value", "normalized_text", "raw_text", "text", "canonical_citation", "citation"):
        text = str(item.get(key) or "").strip().lower()
        if text == f"this {reference_type}":
            return text

    return ""


def _reference_resolution_text(item: Dict[str, Any]) -> str:
    """Return canonical display text for resolved legal references."""

    for key in ("canonical_citation", "citation", "value", "normalized_text", "raw_text", "text"):
        value = item.get(key)
        if value:
            return str(value).strip()

    reference_type = str(item.get("reference_type") or item.get("type") or "").strip().lower()
    target = str(item.get("target") or item.get("section") or item.get("subsection") or "").strip()
    if reference_type and target:
        return target if target.lower().startswith(reference_type + " ") else f"{reference_type} {target}"
    return ""


def _slot_primary_text(item: Dict[str, Any]) -> str:
    """Return the stable text value for a structured IR slot."""

    for key in ("value", "normalized_text", "raw_text", "text", "canonical_citation", "citation"):
        value = item.get(key)
        if value:
            return str(value).strip()
    return ""


def _is_same_document_resolved_reference(item: Dict[str, Any]) -> bool:
    """Return whether a resolved reference is explicitly same-document."""

    if item.get("same_document") is True:
        return True

    for key in ("resolution_scope", "document_scope", "source_scope", "scope"):
        value = str(item.get(key) or "").strip().lower().replace("-", "_")
        if value in {"same_document", "this_document", "current_document", "local"}:
            return True

    target_document = str(item.get("target_document") or "").strip().lower()
    return target_document in {"same_document", "this_document", "current_document"}


def _is_local_scope_reference_exception_text(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    return bool(_LOCAL_SCOPE_REFERENCE_EXCEPTION_RE.match(normalized))


def _is_local_scope_reference_condition_text(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    return bool(_LOCAL_SCOPE_REFERENCE_CONDITION_RE.match(normalized))


def _exception_text_needs_external_resolution(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return True
    if _LEGAL_REFERENCE_TEXT_RE.search(normalized):
        return True
    return normalized.startswith((
        "as otherwise provided",
        "as provided",
        "otherwise provided in",
        "provided in",
        "under ",
        "pursuant to ",
        "notwithstanding ",
    ))
