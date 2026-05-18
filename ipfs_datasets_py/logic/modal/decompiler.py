"""Deterministic decompiler for modal IR.

The decompiler keeps two views separate:

* ``DecodedModalText.text`` is a provenance-backed semantic reconstruction of
  the source text carried by the IR, so round-trip diagnostics measure whether
  the compiler/decompiler destroyed information.
* Modal formulas, operators, predicates, cues, and ontology frames remain in
  phrase metadata as audit evidence for expert review and program synthesis.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
)

_CONDITION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("provided that", "provided_that"),
    ("subject to", "subject_to"),
    ("in the case of", "in_the_case_of"),
    ("in the event that", "in_the_event_that"),
    ("notwithstanding", "notwithstanding"),
    ("for the purposes of", "for_the_purposes_of"),
    ("for purposes of", "for_purposes_of"),
    ("with respect to", "with_respect_to"),
    ("to the extent provided", "to_the_extent_provided"),
    ("if", "if"),
    ("when", "when"),
    ("before", "before"),
    ("upon", "upon"),
)
_EXCEPTION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("except as otherwise provided", "except_as_otherwise_provided"),
    ("except to the extent", "except_to_the_extent"),
    ("except that", "except_that"),
    ("except as", "except_as"),
    ("unless", "unless"),
    ("except", "except"),
)
_USCODE_FALLBACK_STATUS_KEYWORDS: tuple[str, ...] = (
    "reclassified",
    "transferred",
    "codification",
    "repealed",
    "omitted",
    "reserved",
    "vacant",
    "renumbered",
    "terminated",
)
_USCODE_STATUS_DERIVATION_RULES = frozenset(
    {
        "uscode_transferred_heading_v1",
        "uscode_codification_transfer_heading_v1",
        "uscode_editorial_status_heading_v1",
    }
)
_USC_CITATION_RE = re.compile(
    r"^\s*(?P<title>\d+[A-Za-z]*)\s+U\.?\s*S\.?\s*C\.?\s*\.?\s*"
    r"(?P<section>[0-9A-Za-z.\-]+(?:\s+(?:to|through|thru)\s+[0-9A-Za-z.\-]+)?)\s*$",
    re.IGNORECASE,
)
_USCODE_SOURCE_ID_RE = re.compile(
    r"^\s*(?P<scheme>us-code)-(?P<title>[^-]+)-(?P<section>.+)-(?P<digest>[0-9a-f]{16})\s*$",
    re.IGNORECASE,
)
_TRAILING_SECTION_PUNCT_RE = re.compile(r"[.;:]+$")
_CITATION_SECTION_COMPONENT_SPLIT_RE = re.compile(r"[.\-]+")
_CITATION_SECTION_RANGE_RE = re.compile(
    r"^\s*(?P<start>[0-9A-Za-z.\-]+)\s+"
    r"(?P<connector>to|through|thru)\s+"
    r"(?P<end>[0-9A-Za-z.\-]+)\s*$",
    re.IGNORECASE,
)
_CITATION_SECTION_PART_RE = re.compile(
    r"^(?P<number>\d+)(?P<suffix>[A-Za-z]+)?$"
)
_USCODE_LEADING_SECTION_REF_RE = re.compile(
    r"^\s*(?:(?:§\s*|sec\.?\s*|section\s+)\d[0-9A-Za-z.\-]*(?:\([^)]+\))*|\d[0-9A-Za-z.\-]*(?:\([^)]+\))*)\s*(?:[.:\-–—]+)?\s*",
    re.IGNORECASE,
)
_SECTION_HEADING_TAIL_SPLIT_RE = re.compile(r"[.;:\n]")
_STATUTORY_SCOPE_UNITS: tuple[str, ...] = (
    "subparagraph",
    "subsection",
    "subclause",
    "subchapter",
    "subdivision",
    "subpart",
    "subtitle",
    "subitem",
    "paragraph",
    "section",
    "chapter",
    "clause",
    "division",
    "article",
    "title",
    "part",
    "item",
)
_STATUTORY_SCOPE_UNIT_PATTERN = "|".join(f"{unit}s?" for unit in _STATUTORY_SCOPE_UNITS)
_STATUTORY_SCOPE_CONNECTORS: tuple[str, ...] = (
    "as otherwise provided in",
    "except as provided in",
    "in accordance with",
    "as referred to in",
    "as described in",
    "as defined in",
    "as set forth in",
    "as provided in",
    "referred to in",
    "described in",
    "defined in",
    "pursuant to",
    "under",
    "within",
    "in",
)
_STATUTORY_SCOPE_CONNECTOR_PATTERN = "|".join(
    re.escape(connector)
    for connector in _STATUTORY_SCOPE_CONNECTORS
)
_ROMAN_NUMERAL_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_STATUTORY_SCOPE_REFERENCE_RE = re.compile(
    rf"(?<!\w)"
    rf"(?P<connector>{_STATUTORY_SCOPE_CONNECTOR_PATTERN})"
    rf"\s+"
    rf"(?:(?P<determiner>this|such)\s+)?"
    rf"(?P<unit>{_STATUTORY_SCOPE_UNIT_PATTERN})"
    rf"(?:\s+(?P<target>(?:\([^)]+\))+|[0-9A-Za-z][0-9A-Za-z.\-]*(?:\([^)]+\))*))?"
    rf"(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DecodedModalPhrase:
    """One phrase rendered from a modal IR slot."""

    text: str
    slot: str
    spans: List[List[int]] = field(default_factory=list)
    fixed: bool = False
    provenance_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecodedModalText:
    """Decompiled modal text plus provenance and audit metadata."""

    source_id: str
    text: str
    phrases: List[DecodedModalPhrase]
    support_span: List[int]
    reconstruction_similarity: float = 0.0
    modal_span_coverage: float = 0.0
    reconstruction_strategy: str = "provenance_span_reconstruction_v1"
    parser_warnings: List[str] = field(default_factory=list)
    missing_slots: List[str] = field(default_factory=list)
    formulas: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phrases"] = [phrase.to_dict() for phrase in self.phrases]
        return data


def decode_modal_ir_document(document: ModalIRDocument) -> DecodedModalText:
    """Reconstruct source semantics while preserving formula audit metadata."""
    source_phrases, modal_span_coverage = _source_reconstruction_phrases(document)
    phrases: List[DecodedModalPhrase] = [
        *source_phrases,
        *_source_identifier_phrases(document),
        *_document_modal_family_count_phrases(document),
        *_frame_candidate_phrases(document),
    ]
    missing_slots: List[str] = []
    formulas: List[str] = []

    if not document.formulas:
        missing_slots.append("formulas")
    if not document.normalized_text:
        missing_slots.append("source_text")
    if document.normalized_text and not source_phrases:
        missing_slots.append("source_spans")

    for index, formula in enumerate(
        sorted(document.formulas, key=lambda item: item.formula_id)
    ):
        if index:
            phrases.append(_fixed_phrase(";", "formula_separator"))
        formula_text = modal_formula_to_text(formula)
        formulas.append(formula_text)
        phrases.extend(_decode_formula_phrases(formula))
        phrases.extend(
            _fallback_section_heading_tail_phrases(
                document=document,
                formula=formula,
            )
        )
        phrases.extend(
            _fallback_surface_text_phrases(
                document=document,
                formula=formula,
            )
        )

    selected_frame = _selected_frame(document)
    if selected_frame:
        if phrases:
            phrases.append(_fixed_phrase("in", "frame_connector"))
        phrases.append(
            DecodedModalPhrase(
                text=selected_frame,
                slot="selected_frame",
                fixed=False,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            selected_frame,
            slot_prefix="selected_frame",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )

    support_span = _support_span(document.formulas)
    parser_warnings = [
        str(value)
        for value in document.metadata.get("parser_warnings", [])
        if value is not None
    ]
    reconstructed_text = _sentence_from_phrases(phrases)
    return DecodedModalText(
        source_id=document.document_id,
        text=reconstructed_text,
        phrases=phrases,
        support_span=support_span,
        reconstruction_similarity=modal_text_token_similarity(
            document.normalized_text,
            reconstructed_text,
        ),
        modal_span_coverage=modal_span_coverage,
        parser_warnings=parser_warnings,
        missing_slots=missing_slots,
        formulas=formulas,
    )


def modal_formula_to_text(formula: ModalIRFormula) -> str:
    """Render a stable formula-like string from one modal IR formula."""
    arguments = ", ".join(formula.predicate.arguments)
    predicate = formula.predicate.name
    if arguments:
        predicate = f"{predicate}({arguments})"
    return f"{formula.operator.symbol}[{formula.operator.family}:{formula.operator.system}]({predicate})"


def decoded_modal_phrase_slot_text_map(
    decoded: DecodedModalText,
    *,
    include_fixed: bool = False,
    include_provenance_only: bool = True,
) -> Dict[str, List[str]]:
    """Return decoded phrase texts grouped by source slot."""
    slot_texts: Dict[str, List[str]] = {}
    for phrase in decoded.phrases:
        if phrase.fixed and not include_fixed:
            continue
        if phrase.provenance_only and not include_provenance_only:
            continue
        slot = str(phrase.slot or "").strip()
        text = _clean_text(phrase.text)
        if not slot or not text:
            continue
        values = slot_texts.setdefault(slot, [])
        if text not in values:
            values.append(text)
    return slot_texts


def modal_text_token_similarity(left: str, right: str) -> float:
    """Return deterministic token-set F1 similarity for reconstruction checks."""
    left_tokens = set(_tokenize_for_similarity(left))
    right_tokens = set(_tokenize_for_similarity(right))
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    if overlap == 0:
        return 0.0
    precision = overlap / len(right_tokens)
    recall = overlap / len(left_tokens)
    return round((2.0 * precision * recall) / (precision + recall), 6)


def _decode_formula_phrases(formula: ModalIRFormula) -> List[DecodedModalPhrase]:
    spans = [[formula.provenance.start_char, formula.provenance.end_char]]
    cue = str(formula.metadata.get("cue") or "").strip()
    cue_start = formula.metadata.get("cue_start_char")
    cue_end = formula.metadata.get("cue_end_char")
    argument_values = _phrase_values(formula.predicate.arguments)
    statutory_scope_emissions: set[Tuple[str, str]] = set()
    predicate_text = _predicate_phrase(formula)
    phrases = [
        DecodedModalPhrase(
            text=modal_formula_to_text(formula),
            slot="formula",
            spans=spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=_operator_phrase(formula),
            slot="operator",
            spans=_span_from_values(cue_start, cue_end) or spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=_clean_text(formula.operator.symbol),
            slot="modal_operator",
            spans=_span_from_values(cue_start, cue_end) or spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=_clean_text(formula.operator.family),
            slot="modal_family",
            spans=_span_from_values(cue_start, cue_end) or spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=_clean_text(formula.operator.system),
            slot="modal_system",
            spans=_span_from_values(cue_start, cue_end) or spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=predicate_text,
            slot="predicate",
            spans=spans,
            provenance_only=True,
        ),
    ]
    for slot, value in _typed_identifier_slots(
        predicate_text,
        slot_prefix="predicate",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    _append_statutory_scope_phrases(
        phrases,
        predicate_text,
        spans=spans,
        emitted=statutory_scope_emissions,
    )
    operator_label = _clean_text(formula.operator.label)
    if operator_label:
        phrases.append(
            DecodedModalPhrase(
                text=operator_label,
                slot="modal_operator_label",
                spans=_span_from_values(cue_start, cue_end) or spans,
                provenance_only=True,
            )
        )
    if cue:
        phrases.append(
            DecodedModalPhrase(
                text=cue,
                slot="cue",
                spans=_span_from_values(cue_start, cue_end) or spans,
                provenance_only=True,
            )
        )
    if argument_values:
        phrases.append(
            DecodedModalPhrase(
                text=", ".join(argument_values),
                slot="arguments",
                spans=spans,
                provenance_only=True,
            )
        )
    for argument in argument_values:
        phrases.append(
            DecodedModalPhrase(
                text=argument,
                slot="argument",
                spans=spans,
                provenance_only=True,
            )
        )
        _append_statutory_scope_phrases(
            phrases,
            argument,
            spans=spans,
            emitted=statutory_scope_emissions,
        )
        typed_argument_slot = _typed_argument_slot(argument)
        if typed_argument_slot is None:
            continue
        slot, value = typed_argument_slot
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    if formula.predicate.role:
        phrases.append(
            DecodedModalPhrase(
                text=str(formula.predicate.role),
                slot="role",
                spans=spans,
                provenance_only=True,
            )
        )
    for condition in _phrase_values(formula.conditions):
        phrases.append(
            DecodedModalPhrase(
                text=condition,
                slot="condition",
                spans=spans,
                provenance_only=True,
            )
        )
        phrases.extend(_typed_clause_phrases(condition, slot="condition", spans=spans))
        _append_statutory_scope_phrases(
            phrases,
            condition,
            spans=spans,
            emitted=statutory_scope_emissions,
        )
    for exception in _phrase_values(formula.exceptions):
        phrases.append(
            DecodedModalPhrase(
                text=exception,
                slot="exception",
                spans=spans,
                provenance_only=True,
            )
        )
        phrases.extend(_typed_clause_phrases(exception, slot="exception", spans=spans))
        _append_statutory_scope_phrases(
            phrases,
            exception,
            spans=spans,
            emitted=statutory_scope_emissions,
        )
    fallback_rule = _clean_text(formula.metadata.get("fallback_rule") or "")
    if fallback_rule:
        phrases.append(
            DecodedModalPhrase(
                text=fallback_rule,
                slot="fallback_rule",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            fallback_rule,
            slot_prefix="fallback_rule",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    status_keyword = _derived_status_keyword(
        formula=formula,
        fallback_rule=fallback_rule,
    )
    if status_keyword:
        phrases.append(
            DecodedModalPhrase(
                text=status_keyword,
                slot="status_keyword",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            status_keyword,
            slot_prefix="status_keyword",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    statement_hint = _clean_text(formula.metadata.get("statement_hint") or "")
    if statement_hint:
        phrases.append(
            DecodedModalPhrase(
                text=statement_hint,
                slot="statement_hint",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            statement_hint,
            slot_prefix="statement_hint",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    citation = _clean_text(formula.provenance.citation or "")
    if citation:
        phrases.append(
            DecodedModalPhrase(
                text=citation,
                slot="citation",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _citation_slots(citation):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    return phrases


def _fallback_section_heading_tail_phrases(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[DecodedModalPhrase]:
    heading_tail = _fallback_section_heading_tail_text(document=document, formula=formula)
    if not heading_tail:
        return []
    spans = [[formula.provenance.start_char, formula.provenance.end_char]]
    phrases = [
        DecodedModalPhrase(
            text=heading_tail,
            slot="section_heading_tail",
            spans=spans,
            provenance_only=True,
        )
    ]
    for slot, value in _typed_identifier_slots(
        heading_tail,
        slot_prefix="section_heading_tail",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


def _fallback_surface_text_phrases(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[DecodedModalPhrase]:
    surface_text = _fallback_surface_text(document=document, formula=formula)
    if not surface_text:
        return []
    spans = [[formula.provenance.start_char, formula.provenance.end_char]]
    phrases = [
        DecodedModalPhrase(
            text=surface_text,
            slot="fallback_surface_text",
            spans=spans,
            provenance_only=True,
        )
    ]
    for slot, value in _typed_identifier_slots(
        surface_text,
        slot_prefix="fallback_surface_text",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


def _fallback_section_heading_tail_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_tokens: int = 18,
) -> str:
    fallback_rule = _clean_text(formula.metadata.get("fallback_rule") or "")
    if fallback_rule != "uscode_section_heading_v1":
        return ""
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    trailing = source_text[end:]
    if not trailing:
        return ""
    trailing = trailing.lstrip(" \t\r\n-–—:;,.")
    if not trailing:
        return ""
    candidate = _SECTION_HEADING_TAIL_SPLIT_RE.split(trailing, maxsplit=1)[0]
    heading_tail = _clean_text(candidate)
    if not heading_tail:
        return ""
    if len(_tokenize_for_similarity(heading_tail)) > max_tokens:
        return ""
    return heading_tail


def _fallback_surface_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_tokens: int = 24,
) -> str:
    fallback_rule = _clean_text(formula.metadata.get("fallback_rule") or "")
    if not fallback_rule:
        return ""
    heading_tail = _fallback_section_heading_tail_text(
        document=document,
        formula=formula,
        max_tokens=max_tokens,
    )
    if heading_tail:
        return heading_tail
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    span_text = _clean_text(source_text[start:end])
    if not span_text:
        return ""
    normalized = _clean_text(_USCODE_LEADING_SECTION_REF_RE.sub("", span_text))
    normalized = _TRAILING_SECTION_PUNCT_RE.sub("", normalized)
    if not normalized:
        return ""
    tokens = _tokenize_for_similarity(normalized)
    if not tokens or len(tokens) > max_tokens:
        return ""
    return normalized


def _source_identifier_phrases(document: ModalIRDocument) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    for source_id in _document_source_ids(document):
        for slot, value in _source_id_slots(source_id):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
    return phrases


def _document_modal_family_count_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    for slot, value in _modal_family_count_slots(
        document.metadata.get("modal_family_counts")
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _modal_family_count_slots(raw_counts: Any) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    for rank, (family, count) in enumerate(
        _normalized_modal_family_counts(raw_counts),
        start=1,
    ):
        slots.extend(
            (
                ("modal_family_count", f"{family}:{count}"),
                ("modal_family_count_ranked", f"{rank}:{family}:{count}"),
                ("modal_family_count_family", family),
                ("modal_family_count_value", count),
                (f"modal_family_count_{_slot_safe_family_key(family)}", count),
            )
        )
    return _unique_slot_values(slots)


def _normalized_modal_family_counts(raw_counts: Any) -> List[Tuple[str, str]]:
    if not isinstance(raw_counts, dict):
        return []
    normalized: Dict[str, str] = {}
    for raw_family, raw_count in raw_counts.items():
        family = _slot_safe_family_key(_clean_text(raw_family).lower())
        if not family:
            continue
        count = _coerce_non_negative_int(raw_count)
        if count is None:
            continue
        normalized[family] = str(count)
    return sorted(normalized.items(), key=lambda item: item[0])


def _coerce_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            return None
        if not float_value.is_integer():
            return None
        number = int(float_value)
    if number < 0:
        return None
    return number


def _slot_safe_family_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").lower()).strip("_")
    return normalized


def _document_source_ids(document: ModalIRDocument) -> List[str]:
    source_ids: List[str] = []
    document_id = _clean_text(document.document_id)
    if document_id:
        source_ids.append(document_id)
    for formula in document.formulas:
        source_id = _clean_text(formula.provenance.source_id)
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


def _source_id_slots(source_id: str) -> List[Tuple[str, str]]:
    cleaned = _clean_text(source_id)
    if not cleaned:
        return []
    match = _USCODE_SOURCE_ID_RE.match(cleaned)
    if not match:
        return [("source_id", cleaned)]
    scheme = _clean_text(match.group("scheme")).lower()
    title = _clean_text(match.group("title"))
    section = _clean_text(match.group("section"))
    digest = _clean_text(match.group("digest")).lower()
    normalized_section = _TRAILING_SECTION_PUNCT_RE.sub("", section)
    section_trailing_punct = _section_trailing_punct(
        raw_section=section,
        normalized_section=normalized_section,
    )

    slots: List[Tuple[str, str]] = [
        ("source_id", cleaned),
        ("source_id_scheme", scheme),
    ]
    if title:
        slots.append(("source_id_title", title))
        slots.extend(_typed_identifier_slots(title, slot_prefix="source_id_title"))
        title_match = _CITATION_SECTION_PART_RE.fullmatch(title)
        if title_match:
            title_number = _clean_text(title_match.group("number"))
            title_suffix = _clean_text(title_match.group("suffix"))
            if title_number:
                slots.append(("source_id_title_number", title_number))
            if title_suffix:
                slots.append(("source_id_title_suffix", title_suffix))

    if section:
        slots.append(("source_id_section", section))
    if normalized_section and normalized_section != section:
        slots.append(("source_id_section_normalized", normalized_section))
    if section_trailing_punct:
        slots.append(("source_id_section_trailing_punct", section_trailing_punct))
    section_for_slots = normalized_section or section
    source_id_canonical = _canonical_usc_citation(title, section_for_slots)
    if source_id_canonical:
        slots.append(("source_id_citation_canonical", source_id_canonical))
    if section_for_slots:
        slots.extend(_source_id_section_slots(section_for_slots))
        slots.extend(
            _typed_identifier_slots(
                section_for_slots,
                slot_prefix="source_id_section",
            )
        )

    if digest:
        slots.append(("source_id_digest", digest))
    return _unique_slot_values(slots)


def _source_id_section_slots(section: str) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    for slot, value in _citation_section_slots(section):
        if slot.startswith("citation_section"):
            slots.append((slot.replace("citation_section", "source_id_section", 1), value))
    return slots


def _frame_candidate_phrases(document: ModalIRDocument) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    ranked_candidates = sorted(
        document.frame_candidates,
        key=lambda candidate: _frame_candidate_sort_key(candidate),
    )
    for rank, candidate in enumerate(ranked_candidates, start=1):
        frame_id = _clean_text(getattr(candidate, "frame_id", "") or "")
        if not frame_id:
            continue
        phrases.append(
            DecodedModalPhrase(
                text=frame_id,
                slot="frame_candidate",
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=str(rank),
                slot="frame_candidate_rank",
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=f"{rank}:{frame_id}",
                slot="frame_candidate_ranked",
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            frame_id,
            slot_prefix="frame_candidate",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
        for term in _phrase_values(getattr(candidate, "matched_terms", ()) or ()):
            phrases.append(
                DecodedModalPhrase(
                    text=term,
                    slot="frame_candidate_term",
                    provenance_only=True,
                )
            )
            for slot, value in _typed_identifier_slots(
                term,
                slot_prefix="frame_candidate_term",
            ):
                phrases.append(
                    DecodedModalPhrase(
                        text=value,
                        slot=slot,
                        provenance_only=True,
                    )
                )
    return phrases


def _frame_candidate_sort_key(candidate: Any) -> Tuple[float, str]:
    frame_id = _clean_text(getattr(candidate, "frame_id", "") or "")
    try:
        score = float(getattr(candidate, "score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return (-score, frame_id)


def _operator_phrase(formula: ModalIRFormula) -> str:
    symbol = formula.operator.symbol
    label = formula.operator.label or symbol
    phrase_map = {
        "O": "obligatory",
        "P": "permitted",
        "F": "forbidden",
        "G": "always",
        "X": "next",
        "K": "known",
        "B": "believed",
        "O|": "conditionally obligatory",
        "[a]": "after action",
        "Frame": "framed as",
        "□": "necessary",
        "◇": "possible",
    }
    return phrase_map.get(symbol, label)


def _predicate_phrase(formula: ModalIRFormula) -> str:
    return _clean_text(formula.predicate.name.replace("_", " "))


def _sentence_from_phrases(phrases: Sequence[DecodedModalPhrase]) -> str:
    words: List[str] = []
    for phrase in phrases:
        if phrase.fixed or phrase.provenance_only:
            continue
        text = _clean_text(phrase.text)
        if not text:
            continue
        words.append(text)
    return _clean_text(" ".join(words))


def _source_reconstruction_phrases(
    document: ModalIRDocument,
) -> Tuple[List[DecodedModalPhrase], float]:
    source_text = _clean_text(document.normalized_text)
    if not source_text:
        return [], 0.0

    modal_spans = _merged_formula_spans(document.formulas, len(source_text))
    if not modal_spans:
        return [
            DecodedModalPhrase(
                text=source_text,
                slot="source_context_span",
                spans=[[0, len(source_text)]],
            )
        ], 0.0

    phrases: List[DecodedModalPhrase] = []
    cursor = 0
    covered_chars = 0
    for start, end in modal_spans:
        if cursor < start:
            _append_source_phrase(
                phrases,
                source_text,
                cursor,
                start,
                slot="source_context_span",
            )
        _append_source_phrase(
            phrases,
            source_text,
            start,
            end,
            slot="modal_source_span",
        )
        covered_chars += max(0, end - start)
        cursor = max(cursor, end)
    if cursor < len(source_text):
        _append_source_phrase(
            phrases,
            source_text,
            cursor,
            len(source_text),
            slot="source_context_span",
        )

    coverage = covered_chars / len(source_text) if source_text else 0.0
    return phrases, round(min(1.0, max(0.0, coverage)), 6)


def _append_source_phrase(
    phrases: List[DecodedModalPhrase],
    source_text: str,
    start: int,
    end: int,
    *,
    slot: str,
) -> None:
    clamped_start = max(0, min(len(source_text), start))
    clamped_end = max(clamped_start, min(len(source_text), end))
    text = _clean_text(source_text[clamped_start:clamped_end])
    if not text:
        return
    phrases.append(
        DecodedModalPhrase(
            text=text,
            slot=slot,
            spans=[[clamped_start, clamped_end]],
        )
    )


def _merged_formula_spans(
    formulas: Sequence[ModalIRFormula],
    source_length: int,
) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    for formula in formulas:
        start = max(0, min(source_length, int(formula.provenance.start_char)))
        end = max(start, min(source_length, int(formula.provenance.end_char)))
        if end > start:
            spans.append((start, end))
    if not spans:
        return []

    spans.sort()
    merged: List[Tuple[int, int]] = []
    current_start, current_end = spans[0]
    for start, end in spans[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        merged.append((current_start, current_end))
        current_start, current_end = start, end
    merged.append((current_start, current_end))
    return merged


def _support_span(formulas: Sequence[ModalIRFormula]) -> List[int]:
    if not formulas:
        return [0, 0]
    starts = [formula.provenance.start_char for formula in formulas]
    ends = [formula.provenance.end_char for formula in formulas]
    return [min(starts), max(ends)]


def _fixed_phrase(text: str, slot: str) -> DecodedModalPhrase:
    return DecodedModalPhrase(text=text, slot=slot, fixed=True)


def _span_from_values(start: Any, end: Any) -> List[List[int]]:
    try:
        start_int = int(start)
        end_int = int(end)
    except (TypeError, ValueError):
        return []
    if start_int < 0 or end_int < start_int:
        return []
    return [[start_int, end_int]]


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _typed_argument_slot(argument: str) -> Tuple[str, str] | None:
    if ":" not in argument:
        return None
    key, value = argument.split(":", 1)
    key = _clean_text(key).lower()
    value = _clean_text(value).replace("_", " ")
    if not key or not value:
        return None
    key = re.sub(r"[^a-z0-9_]+", "_", key).strip("_")
    if not key:
        return None
    return f"argument_{key}", value


def _typed_clause_phrases(
    clause: str,
    *,
    slot: str,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    parsed = _typed_clause_slot(clause, slot=slot)
    if parsed is None:
        return []
    prefix_slot_value, scoped_slot, scoped_value = parsed
    phrases = [
        DecodedModalPhrase(
            text=prefix_slot_value,
            slot=f"{slot}_prefix",
            spans=spans,
            provenance_only=True,
        )
    ]
    if scoped_value:
        phrases.append(
            DecodedModalPhrase(
                text=scoped_value,
                slot=scoped_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


def _typed_clause_slot(
    clause: str,
    *,
    slot: str,
) -> Tuple[str, str, str] | None:
    normalized = _clean_text(clause).lower()
    if not normalized:
        return None
    prefixes = _CONDITION_PREFIXES if slot == "condition" else _EXCEPTION_PREFIXES
    for prefix_text, prefix_key in prefixes:
        if not normalized.startswith(prefix_text):
            continue
        suffix = _clean_text(normalized[len(prefix_text) :].lstrip(",:;- "))
        return prefix_text, f"{slot}_{prefix_key}", suffix
    return None


def _append_statutory_scope_phrases(
    phrases: List[DecodedModalPhrase],
    text: str,
    *,
    spans: List[List[int]],
    emitted: set[Tuple[str, str]],
) -> None:
    for slot, value in _statutory_scope_slots(text):
        marker = (slot, value)
        if marker in emitted:
            continue
        emitted.add(marker)
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                spans=spans,
                provenance_only=True,
            )
        )


def _statutory_scope_slots(text: str) -> List[Tuple[str, str]]:
    normalized = _clean_text(text).replace("_", " ").lower()
    if not normalized:
        return []
    result: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for match in _STATUTORY_SCOPE_REFERENCE_RE.finditer(normalized):
        connector = _clean_text(match.group("connector")).lower()
        unit_surface = _clean_text(match.group("unit")).lower()
        unit = _canonical_statutory_scope_unit(unit_surface)
        determiner = _clean_text(match.group("determiner")).lower()
        has_determiner = bool(determiner)
        target = _clean_text(match.group("target")).lower()
        if (
            has_determiner
            and target
            and not target.startswith("(")
            and not any(character.isdigit() for character in target)
            and _ROMAN_NUMERAL_RE.fullmatch(target) is None
        ):
            target = ""
        reference_parts = (
            [connector, determiner, unit_surface]
            if has_determiner
            else [connector, unit_surface]
        )
        if target:
            reference_parts.append(target)
        reference = " ".join(reference_parts)
        resolved_target = (
            f"{determiner} {target}".strip() if has_determiner else target
        )
        if has_determiner and not target:
            resolved_target = determiner
        values: List[Tuple[str, str]] = [
            ("statutory_scope_reference", reference),
            ("statutory_scope_connector", connector),
            ("statutory_scope_unit", unit),
        ]
        if resolved_target:
            values.append(("statutory_scope_target", resolved_target))
        for slot in values:
            if slot in seen:
                continue
            seen.add(slot)
            result.append(slot)
    return result


def _canonical_statutory_scope_unit(unit: str) -> str:
    normalized = _clean_text(unit).lower()
    if normalized.endswith("s"):
        singular = normalized[:-1]
        if singular in _STATUTORY_SCOPE_UNITS:
            return singular
    return normalized


def _alpha_case_kind(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    letters = "".join(character for character in cleaned if character.isalpha())
    if not letters:
        return ""
    if letters.islower():
        return "lower"
    if letters.isupper():
        return "upper"
    return "mixed"


def _derived_status_keyword(
    *,
    formula: ModalIRFormula,
    fallback_rule: str,
) -> str:
    explicit = _clean_text(formula.metadata.get("status_keyword") or "").lower()
    if explicit:
        return explicit
    normalized_rule = _clean_text(fallback_rule).lower()
    if normalized_rule not in _USCODE_STATUS_DERIVATION_RULES:
        return ""
    predicate_text = _clean_text(formula.predicate.name).replace("_", " ").lower()
    for keyword in _USCODE_FALLBACK_STATUS_KEYWORDS:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", predicate_text):
            return keyword
    if normalized_rule in {
        "uscode_transferred_heading_v1",
        "uscode_codification_transfer_heading_v1",
    }:
        return "transferred"
    return ""


def _citation_slots(citation: str) -> List[Tuple[str, str]]:
    cleaned = _clean_text(citation)
    if not cleaned:
        return []
    match = _USC_CITATION_RE.match(cleaned)
    if not match:
        return []
    title = _clean_text(match.group("title"))
    raw_section = _clean_text(match.group("section"))
    section = _TRAILING_SECTION_PUNCT_RE.sub("", raw_section)
    section_trailing_punct = _section_trailing_punct(
        raw_section=raw_section,
        normalized_section=section,
    )
    slots: List[Tuple[str, str]] = []
    if title:
        slots.append(("citation_title", title))
    slots.append(("citation_code", "U.S.C."))
    if section:
        citation_canonical = _canonical_usc_citation(title, section)
        if citation_canonical:
            slots.append(("citation_canonical", citation_canonical))
        slots.append(("citation_section", section))
        if raw_section and raw_section != section:
            slots.append(("citation_section_raw", raw_section))
            slots.append(("citation_section_normalized", section))
        if section_trailing_punct:
            slots.append(("citation_section_trailing_punct", section_trailing_punct))
        slots.extend(_citation_section_slots(section))
        slots.extend(
            _typed_identifier_slots(
                section,
                slot_prefix="citation_section",
            )
        )
    return _unique_slot_values(slots)


def _section_trailing_punct(
    *,
    raw_section: str,
    normalized_section: str,
) -> str:
    raw = _clean_text(raw_section)
    normalized = _clean_text(normalized_section)
    if not raw or raw == normalized:
        return ""
    if not raw.startswith(normalized):
        return ""
    return _clean_text(raw[len(normalized) :])


def _canonical_usc_citation(title: str, section: str) -> str:
    normalized_title = _clean_text(title)
    normalized_section = _clean_text(_TRAILING_SECTION_PUNCT_RE.sub("", section))
    if not normalized_title or not normalized_section:
        return ""
    return f"{normalized_title} U.S.C. {normalized_section}"


def _citation_section_slots(section: str) -> List[Tuple[str, str]]:
    cleaned = _clean_text(section)
    if not cleaned:
        return []
    range_match = _CITATION_SECTION_RANGE_RE.fullmatch(cleaned)
    range_start = ""
    range_end = ""
    range_connector = ""
    if range_match:
        range_start = _clean_text(range_match.group("start"))
        range_end = _clean_text(range_match.group("end"))
        range_connector = _clean_text(range_match.group("connector")).lower()
    if range_start and range_end and range_connector:
        components = [range_start, range_end]
    else:
        components = [
            _clean_text(component)
            for component in _CITATION_SECTION_COMPONENT_SPLIT_RE.split(cleaned)
            if _clean_text(component)
        ]
    if not components:
        return []
    slots: List[Tuple[str, str]] = [
        ("citation_section_primary", components[0]),
        ("citation_section_component_count", str(len(components))),
    ]
    if range_start and range_end and range_connector:
        slots.extend(
            [
                ("citation_section_range", f"{range_start} {range_connector} {range_end}"),
                ("citation_section_range_start", range_start),
                ("citation_section_range_end", range_end),
                ("citation_section_range_connector", range_connector),
            ]
        )
    component_shapes: List[str] = []
    numeric_component_count = 0
    suffix_component_count = 0
    total_components = len(components)
    for index, component in enumerate(components, start=1):
        position = str(index)
        slots.append(("citation_section_component", component))
        slots.append(("citation_section_component_positioned", f"{position}:{component}"))
        match = _CITATION_SECTION_PART_RE.fullmatch(component)
        if not match:
            component_shapes.append("X")
            slots.append(("citation_section_component_kind", "other"))
            slots.append(
                ("citation_section_component_kind_positioned", f"{position}:other")
            )
            if index == 1:
                slots.append(("citation_section_primary_component_kind", "other"))
            if index == total_components:
                slots.append(("citation_section_terminal_component_kind", "other"))
            continue
        number = _clean_text(match.group("number"))
        suffix = _clean_text(match.group("suffix"))
        numeric_component_count += 1
        if number:
            slots.append(("citation_section_number", number))
            slots.append(("citation_section_number_digit_count", str(len(number))))
            slots.append(("citation_section_number_positioned", f"{position}:{number}"))
            if index == 1:
                slots.append(("citation_section_primary_number", number))
            if index == total_components:
                slots.append(("citation_section_terminal_number", number))
        if suffix:
            component_shapes.append("NA")
            suffix_component_count += 1
            slots.append(("citation_section_component_kind", "alphanumeric"))
            slots.append(
                (
                    "citation_section_component_kind_positioned",
                    f"{position}:alphanumeric",
                )
            )
            slots.append(("citation_section_suffix", suffix))
            slots.append(("citation_section_suffix_positioned", f"{position}:{suffix}"))
            normalized_suffix = suffix.lower()
            if normalized_suffix:
                slots.append(("citation_section_suffix_normalized", normalized_suffix))
                if index == 1:
                    slots.append(("citation_section_primary_suffix_normalized", normalized_suffix))
                if index == total_components:
                    slots.append(("citation_section_terminal_suffix_normalized", normalized_suffix))
            suffix_case = _alpha_case_kind(suffix)
            if suffix_case:
                slots.append(("citation_section_suffix_case", suffix_case))
                slots.append(
                    (
                        "citation_section_suffix_case_positioned",
                        f"{position}:{suffix_case}",
                    )
                )
                if index == 1:
                    slots.append(("citation_section_primary_suffix_case", suffix_case))
                if index == total_components:
                    slots.append(("citation_section_terminal_suffix_case", suffix_case))
            if index == 1:
                slots.append(("citation_section_primary_suffix", suffix))
                slots.append(("citation_section_primary_component_kind", "alphanumeric"))
            if index == total_components:
                slots.append(("citation_section_terminal_suffix", suffix))
                slots.append(("citation_section_terminal_component_kind", "alphanumeric"))
        else:
            component_shapes.append("N")
            slots.append(("citation_section_component_kind", "numeric"))
            slots.append(
                ("citation_section_component_kind_positioned", f"{position}:numeric")
            )
            if index == 1:
                slots.append(("citation_section_primary_component_kind", "numeric"))
            if index == total_components:
                slots.append(("citation_section_terminal_component_kind", "numeric"))
    if component_shapes:
        slots.append(("citation_section_shape", "-".join(component_shapes)))
    slots.append(
        ("citation_section_numeric_component_count", str(numeric_component_count))
    )
    slots.append(
        ("citation_section_suffix_component_count", str(suffix_component_count))
    )
    return slots


def _unique_slot_values(values: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    result: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _typed_identifier_slots(
    value: str,
    *,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized = _clean_text(value).replace("-", "_")
    if not normalized:
        return []
    tokens = [
        token
        for token in re.split(r"[_\s]+", normalized.lower())
        if token
    ]
    if not tokens:
        return []
    slots: List[Tuple[str, str]] = [
        (f"{slot_prefix}_token_count", str(len(tokens))),
        (f"{slot_prefix}_token_prefix", tokens[0]),
        (f"{slot_prefix}_token_suffix", tokens[-1]),
    ]
    for token in tokens:
        slots.append((f"{slot_prefix}_token", token))
    if re.fullmatch(r"v\d+", tokens[-1]):
        slots.append((f"{slot_prefix}_version", tokens[-1]))
        stem_tokens = tokens[:-1]
    else:
        stem_tokens = tokens
    if stem_tokens:
        slots.append((f"{slot_prefix}_stem", "_".join(stem_tokens)))
    return _unique_slot_values(slots)


def _phrase_values(values: Sequence[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _selected_frame(document: ModalIRDocument) -> str:
    metadata_frame = _clean_text(document.metadata.get("selected_frame") or "")
    if metadata_frame:
        return metadata_frame
    frame_logic = getattr(document, "frame_logic", None)
    if frame_logic is not None:
        frame_logic_frame = _clean_text(getattr(frame_logic, "selected_frame", "") or "")
        if frame_logic_frame:
            return frame_logic_frame
    for frame in getattr(document, "frame_candidates", []):
        frame_id = _clean_text(getattr(frame, "frame_id", "") or "")
        if frame_id:
            return frame_id
    return ""


def _tokenize_for_similarity(text: str) -> List[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_'-]*", str(text or ""))
    ]


__all__ = [
    "DecodedModalPhrase",
    "DecodedModalText",
    "decode_modal_ir_document",
    "decoded_modal_phrase_slot_text_map",
    "modal_formula_to_text",
    "modal_text_token_similarity",
]
