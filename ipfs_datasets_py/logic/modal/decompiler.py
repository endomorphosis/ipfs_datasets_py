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
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    DEFAULT_MODAL_REGISTRY,
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
    ("not later than", "not_later_than"),
    ("no later than", "no_later_than"),
    ("if", "if"),
    ("when", "when"),
    ("until", "until"),
    ("after", "after"),
    ("before", "before"),
    ("by", "by"),
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
_TEMPORAL_CLAUSE_PREFIX_RELATIONS: dict[str, str] = {
    "until": "until",
    "after": "after",
    "before": "before",
    "by": "deadline",
    "no_later_than": "deadline",
    "not_later_than": "deadline",
    "upon": "after",
}
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
_USCODE_SECTION_HEADING_TAIL_RULES = frozenset(
    {
        "uscode_section_heading_v1",
        "uscode_section_heading_coarse_v1",
    }
)
_USC_CITATION_RE = re.compile(
    r"^\s*(?P<title>\d+[A-Za-z]*)\s+U\.?\s*S\.?\s*C\.?\s*\.?\s*"
    r"(?:§{1,2}\s*|sec\.?\s*|section\s+)?"
    r"(?P<section>[0-9A-Za-z.\-]+(?:\s+(?:to|through|thru)\s+[0-9A-Za-z.\-]+)?)\s*$",
    re.IGNORECASE,
)
_USCODE_SOURCE_ID_RE = re.compile(
    r"^\s*(?P<scheme>us-code)-(?P<title>[^-]+)-(?P<section>.+)-(?P<digest>[0-9a-f]{16})\s*$",
    re.IGNORECASE,
)
_TRAILING_SECTION_PUNCT_RE = re.compile(r"[.;:]+$")
_CITATION_SECTION_COMPONENT_SPLIT_RE = re.compile(r"[.\-]+")
_CITATION_SECTION_DELIMITER_RE = re.compile(r"[.\-]+")
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
_STRICT_ROMAN_NUMERAL_RE = re.compile(
    r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$",
    re.IGNORECASE,
)
_VOWEL_CHARS = frozenset({"a", "e", "i", "o", "u"})
_PROVENANCE_NUMERIC_ALIGNMENT_SIGNATURES: tuple[str, ...] = (
    "leading_digit",
    "parity",
    "has_zero_digit",
    "zero_digit_count",
    "magnitude_bucket",
    "thousands_block",
)
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
_CUE_TOKEN_RE = re.compile(r"[a-z0-9]+")


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
        *_document_span_metric_phrases(
            document=document,
            modal_span_coverage=modal_span_coverage,
        ),
        *_source_identifier_phrases(document),
        *_document_citation_phrases(document),
        *_document_modal_family_count_phrases(document),
        *_frame_candidate_phrases(document),
    ]
    if not document.formulas:
        phrases.extend(_document_provenance_alignment_phrases(document))
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
        phrases.extend(_selected_frame_modal_family_phrases(document))

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
    cue_start = formula.metadata.get("cue_start_char")
    cue_end = formula.metadata.get("cue_end_char")
    cue_values = _formula_cues(formula)
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
    operator_label = _resolved_modal_operator_label(formula)
    if operator_label:
        operator_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=operator_label,
                slot="modal_operator_label",
                spans=operator_spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            operator_label,
            slot_prefix="modal_operator_label",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=operator_spans,
                    provenance_only=True,
                )
            )
    operator_signature = _modal_operator_signature(
        formula,
        operator_label=operator_label,
    )
    if operator_signature:
        operator_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=operator_signature,
                slot="modal_operator_signature",
                spans=operator_spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            operator_signature.replace(":", "_"),
            slot_prefix="modal_operator_signature",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=operator_spans,
                    provenance_only=True,
                )
            )
    for cue in cue_values:
        cue_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=cue,
                slot="cue",
                spans=cue_spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=cue,
                slot="modal_cue",
                spans=cue_spans,
                provenance_only=True,
            )
        )
        for cue_slot, cue_value in _cue_modal_slots(formula, cue=cue):
            phrases.append(
                DecodedModalPhrase(
                    text=cue_value,
                    slot=cue_slot,
                    spans=cue_spans,
                    provenance_only=True,
                )
            )
            alias_slot = _cue_alias_slot_name(cue_slot)
            if alias_slot:
                phrases.append(
                    DecodedModalPhrase(
                        text=cue_value,
                        slot=alias_slot,
                        spans=cue_spans,
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
    condition_values = _phrase_values(formula.conditions)
    exception_values = _phrase_values(formula.exceptions)
    proxy_condition_from_exception = not condition_values and bool(exception_values)
    for condition in condition_values:
        phrases.append(
            DecodedModalPhrase(
                text=condition,
                slot="condition",
                spans=spans,
                provenance_only=True,
            )
        )
        for typed_slot, typed_value in _typed_identifier_slots(
            condition,
            slot_prefix="condition",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=typed_value,
                    slot=typed_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        phrases.extend(
            _typed_clause_phrases(
                condition,
                slot="condition",
                spans=spans,
                formula=formula,
            )
        )
        _append_statutory_scope_phrases(
            phrases,
            condition,
            spans=spans,
            emitted=statutory_scope_emissions,
        )
    for exception in exception_values:
        phrases.append(
            DecodedModalPhrase(
                text=exception,
                slot="exception",
                spans=spans,
                provenance_only=True,
            )
        )
        for typed_slot, typed_value in _typed_identifier_slots(
            exception,
            slot_prefix="exception",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=typed_value,
                    slot=typed_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        phrases.extend(
            _typed_clause_phrases(
                exception,
                slot="exception",
                spans=spans,
                formula=formula,
            )
        )
        _append_statutory_scope_phrases(
            phrases,
            exception,
            spans=spans,
            emitted=statutory_scope_emissions,
        )
        if proxy_condition_from_exception:
            phrases.extend(
                _condition_proxy_phrases_from_exception(
                    exception=exception,
                    spans=spans,
                    formula=formula,
                )
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
    procedural_keyword = _clean_text(formula.metadata.get("procedural_keyword") or "")
    if procedural_keyword:
        phrases.append(
            DecodedModalPhrase(
                text=procedural_keyword,
                slot="procedural_keyword",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            procedural_keyword,
            slot_prefix="procedural_keyword",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    source_id = _clean_text(formula.provenance.source_id or "")
    citation = _clean_text(formula.provenance.citation or "")
    citation_inferred_from_source_id = False
    if not citation:
        citation = _source_id_inferred_citation(source_id)
        citation_inferred_from_source_id = bool(citation)
    if citation:
        if citation_inferred_from_source_id:
            phrases.append(
                DecodedModalPhrase(
                    text="source_id_inferred",
                    slot="citation_derivation",
                    spans=spans,
                    provenance_only=True,
                )
            )
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
    for slot, value in _provenance_alignment_slots(
        source_id=source_id,
        citation=citation,
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
    if fallback_rule not in _USCODE_SECTION_HEADING_TAIL_RULES:
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
    status_surface = _status_heading_surface_text(
        normalized,
        status_keyword=_derived_status_keyword(
            formula=formula,
            fallback_rule=fallback_rule,
        ),
    )
    if status_surface:
        return status_surface
    tokens = _tokenize_for_similarity(normalized)
    if not tokens or len(tokens) > max_tokens:
        return ""
    return normalized


def _status_heading_surface_text(text: str, *, status_keyword: str) -> str:
    normalized_text = _clean_text(text)
    normalized_keyword = _clean_text(status_keyword).lower()
    if not normalized_text or not normalized_keyword:
        return ""
    lowered_text = normalized_text.lower()
    if not lowered_text.startswith(normalized_keyword):
        return ""
    if lowered_text == normalized_keyword:
        return normalized_text
    if re.match(
        rf"^{re.escape(normalized_keyword)}\s+from\s+the\s+u(?:\b|\s)",
        lowered_text,
    ):
        return normalized_text.split(maxsplit=1)[0]
    return ""


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


def _document_citation_phrases(document: ModalIRDocument) -> List[DecodedModalPhrase]:
    citation = _clean_text(document.metadata.get("citation") or "")
    if not citation:
        if document.formulas:
            return []
        inferred_citations = _inferred_citations_from_source_ids(
            _document_source_ids(document)
        )
        if not inferred_citations:
            return []
        phrases: List[DecodedModalPhrase] = []
        for inferred_citation in inferred_citations:
            phrases.append(
                DecodedModalPhrase(
                    text=inferred_citation,
                    slot="citation",
                    provenance_only=True,
                )
            )
            phrases.append(
                DecodedModalPhrase(
                    text="source_id_inferred",
                    slot="citation_derivation",
                    provenance_only=True,
                )
            )
            for slot, value in _citation_slots(inferred_citation):
                phrases.append(
                    DecodedModalPhrase(
                        text=value,
                        slot=slot,
                        provenance_only=True,
                    )
                )
        return phrases
    formula_citations = {
        _clean_text(formula.provenance.citation or "")
        for formula in document.formulas
        if _clean_text(formula.provenance.citation or "")
    }
    if citation in formula_citations:
        return []
    phrases: List[DecodedModalPhrase] = [
        DecodedModalPhrase(
            text=citation,
            slot="citation",
            provenance_only=True,
        )
    ]
    for slot, value in _citation_slots(citation):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _document_provenance_alignment_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    citation = _clean_text(document.metadata.get("citation") or "")
    if not citation and not document.formulas:
        inferred_citations = _inferred_citations_from_source_ids(
            _document_source_ids(document)
        )
        if inferred_citations:
            citation = inferred_citations[0]
    if not citation:
        return []
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str]] = set()
    for source_id in _document_source_ids(document):
        for slot, value in _provenance_alignment_slots(
            source_id=source_id,
            citation=citation,
        ):
            marker = (slot, value)
            if marker in seen:
                continue
            seen.add(marker)
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
        document.metadata.get("modal_family_counts"),
        formulas=document.formulas,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _selected_frame_modal_family_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    if not _selected_frame(document):
        return []
    phrases: List[DecodedModalPhrase] = []
    for slot, value in _selected_frame_modal_family_slots(
        document.metadata.get("modal_family_counts"),
        formulas=document.formulas,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _selected_frame_modal_family_slots(
    raw_counts: Any,
    *,
    formulas: Sequence[ModalIRFormula] = (),
) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    for rank, (family, count) in enumerate(
        _resolved_modal_family_counts(raw_counts, formulas=formulas),
        start=1,
    ):
        safe_family = _slot_safe_family_key(family)
        if not safe_family:
            continue
        slots.extend(
            (
                ("selected_frame_modal_family", safe_family),
                ("selected_frame_modal_family_ranked", f"{rank}:{safe_family}"),
                ("selected_frame_modal_family_count", f"{safe_family}:{count}"),
                (
                    "selected_frame_modal_family_count_ranked",
                    f"{rank}:{safe_family}:{count}",
                ),
                ("selected_frame_modal_family_count_value", count),
                (f"selected_frame_modal_family_{safe_family}", count),
            )
        )
        slots.extend(
            _numeric_signature_slots(
                count,
                slot_prefix="selected_frame_modal_family_count_value",
            )
        )
        slots.extend(
            _numeric_signature_slots(
                count,
                slot_prefix=f"selected_frame_modal_family_{safe_family}",
            )
        )
    return _unique_slot_values(slots)


def _modal_family_count_slots(
    raw_counts: Any,
    *,
    formulas: Sequence[ModalIRFormula] = (),
) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    for rank, (family, count) in enumerate(
        _resolved_modal_family_counts(raw_counts, formulas=formulas),
        start=1,
    ):
        safe_family = _slot_safe_family_key(family)
        if not safe_family:
            continue
        slots.extend(
            (
                ("modal_family_count", f"{family}:{count}"),
                ("modal_family_count_ranked", f"{rank}:{family}:{count}"),
                ("modal_family_count_family", family),
                ("modal_family_count_value", count),
                (f"modal_family_count_{safe_family}", count),
            )
        )
        slots.extend(
            _numeric_signature_slots(
                count,
                slot_prefix="modal_family_count_value",
            )
        )
        slots.extend(
            _numeric_signature_slots(
                count,
                slot_prefix=f"modal_family_count_{safe_family}",
            )
        )
    return _unique_slot_values(slots)


def _resolved_modal_family_counts(
    raw_counts: Any,
    *,
    formulas: Sequence[ModalIRFormula] = (),
) -> List[Tuple[str, str]]:
    metadata_counts = _normalized_modal_family_counts(raw_counts)
    if metadata_counts:
        return metadata_counts
    formula_counts: Dict[str, int] = {}
    for formula in formulas:
        family = _slot_safe_family_key(_clean_text(formula.operator.family).lower())
        if not family:
            continue
        formula_counts[family] = formula_counts.get(family, 0) + 1
    return sorted(
        (
            (family, str(count))
            for family, count in formula_counts.items()
        ),
        key=lambda item: item[0],
    )


def _normalized_modal_family_counts(raw_counts: Any) -> List[Tuple[str, str]]:
    if not isinstance(raw_counts, Mapping):
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


def _inferred_citations_from_source_ids(source_ids: Sequence[str]) -> List[str]:
    citations: List[str] = []
    for source_id in source_ids:
        citation = _source_id_inferred_citation(source_id)
        if citation and citation not in citations:
            citations.append(citation)
    return citations


def _source_id_inferred_citation(source_id: str) -> str:
    normalized_source_id = _clean_text(source_id)
    if not normalized_source_id:
        return ""
    source_slot_map = _slot_value_map(_source_id_slots(normalized_source_id))
    title = _clean_text(source_slot_map.get("source_id_title") or "")
    raw_section = _clean_text(
        source_slot_map.get("source_id_section_raw")
        or source_slot_map.get("source_id_section")
        or ""
    )
    if title and raw_section:
        return f"{title} U.S.C. {raw_section}"
    canonical = _clean_text(source_slot_map.get("source_id_citation_canonical") or "")
    if canonical:
        return canonical
    normalized_section = _clean_text(
        source_slot_map.get("source_id_section_normalized")
        or source_slot_map.get("source_id_section")
        or ""
    )
    return _canonical_usc_citation(title, normalized_section)


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
    title_number = ""
    if title:
        slots.append(("source_id_title", title))
        slots.extend(_typed_identifier_slots(title, slot_prefix="source_id_title"))
        title_match = _CITATION_SECTION_PART_RE.fullmatch(title)
        if title_match:
            title_number = _clean_text(title_match.group("number"))
            title_suffix = _clean_text(title_match.group("suffix"))
            if title_number:
                slots.append(("source_id_title_number", title_number))
                slots.extend(
                    _numeric_signature_slots(
                        title_number,
                        slot_prefix="source_id_title_number",
                    )
                )
            if title_suffix:
                slots.append(("source_id_title_suffix", title_suffix))

    if section:
        slots.append(("source_id_section", section))
        slots.append(("source_id_section_raw", section))
    if normalized_section:
        slots.append(("source_id_section_normalized", normalized_section))
    if section_trailing_punct:
        slots.append(("source_id_section_trailing_punct", section_trailing_punct))
        slots.append(("source_id_section_has_trailing_punct", "true"))
        slots.append(
            (
                "source_id_section_trailing_punct_count",
                str(len(section_trailing_punct)),
            )
        )
        punct_kind = _section_trailing_punct_kind(section_trailing_punct)
        if punct_kind:
            slots.append(("source_id_section_trailing_punct_kind", punct_kind))
    else:
        slots.append(("source_id_section_has_trailing_punct", "false"))
        slots.append(("source_id_section_trailing_punct_count", "0"))
    section_for_slots = normalized_section or section
    source_id_canonical = _canonical_usc_citation(title, section_for_slots)
    if source_id_canonical:
        slots.append(("source_id_citation_canonical", source_id_canonical))
    source_id_title_section_key = _title_section_coordinate(title, section_for_slots)
    if source_id_title_section_key:
        slots.append(("source_id_title_section_key", source_id_title_section_key))
        slots.append(
            (
                "source_id_title_section_key_normalized",
                source_id_title_section_key.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                source_id_title_section_key.replace(":", "_"),
                slot_prefix="source_id_title_section_key",
            )
        )
    if section_for_slots:
        section_slots = _source_id_section_slots(section_for_slots)
        slots.extend(section_slots)
        section_slot_map = _slot_value_map(section_slots)
        slots.extend(
            _section_style_slots(
                slot_namespace="source_id",
                section_slot_map=section_slot_map,
                has_trailing_punct=bool(section_trailing_punct),
            )
        )
        source_style_map = _slot_value_map(
            [
                slot
                for slot in slots
                if slot[0] in {"source_id_section_style", "source_id_section_style_canonical"}
            ]
        )
        slots.extend(
            _title_section_style_slots(
                slot_namespace="source_id",
                title=title,
                section_style=_clean_text(
                    source_style_map.get("source_id_section_style") or ""
                ),
                section_style_canonical=_clean_text(
                    source_style_map.get("source_id_section_style_canonical") or ""
                ),
            )
        )
        slots.extend(
            _section_structure_slots(
                slot_namespace="source_id",
                title=title,
                section_signature=_clean_text(
                    section_slot_map.get("source_id_section_signature") or ""
                ),
                section_profile=_clean_text(
                    section_slot_map.get("source_id_section_component_profile") or ""
                ),
            )
        )
        slots.extend(
            _title_section_number_relation_slots(
                slot_namespace="source_id",
                title_number=title_number,
                section_slot_map=section_slot_map,
            )
        )
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


def _provenance_alignment_slots(
    *,
    source_id: str,
    citation: str,
) -> List[Tuple[str, str]]:
    normalized_source_id = _clean_text(source_id)
    normalized_citation = _clean_text(citation)
    if not normalized_source_id or not normalized_citation:
        return []
    source_slot_map = _slot_value_map(_source_id_slots(normalized_source_id))
    citation_slot_map = _slot_value_map(_citation_slots(normalized_citation))
    source_title = _clean_text(source_slot_map.get("source_id_title") or "")
    citation_title = _clean_text(citation_slot_map.get("citation_title") or "")
    source_section = _clean_text(
        source_slot_map.get("source_id_section_normalized")
        or source_slot_map.get("source_id_section")
        or ""
    )
    citation_section = _clean_text(
        citation_slot_map.get("citation_section_normalized")
        or citation_slot_map.get("citation_section")
        or ""
    )
    source_key = _clean_text(
        source_slot_map.get("source_id_title_section_key_normalized")
        or source_slot_map.get("source_id_title_section_key")
        or ""
    )
    citation_key = _clean_text(
        citation_slot_map.get("citation_title_section_key_normalized")
        or citation_slot_map.get("citation_title_section_key")
        or ""
    )
    source_canonical = _clean_text(
        source_slot_map.get("source_id_citation_canonical") or ""
    )
    citation_canonical = _clean_text(citation_slot_map.get("citation_canonical") or "")
    source_section_raw = _clean_text(
        source_slot_map.get("source_id_section_raw")
        or source_slot_map.get("source_id_section")
        or ""
    )
    citation_section_raw = _clean_text(
        citation_slot_map.get("citation_section_raw")
        or citation_slot_map.get("citation_section")
        or ""
    )
    source_section_trailing_punct = _clean_text(
        source_slot_map.get("source_id_section_trailing_punct") or ""
    )
    citation_section_trailing_punct = _clean_text(
        citation_slot_map.get("citation_section_trailing_punct") or ""
    )
    source_has_trailing_punct = _clean_text(
        source_slot_map.get("source_id_section_has_trailing_punct")
        or ("true" if source_section_trailing_punct else "false")
    ).lower()
    citation_has_trailing_punct = _clean_text(
        citation_slot_map.get("citation_section_has_trailing_punct")
        or ("true" if citation_section_trailing_punct else "false")
    ).lower()
    slots: List[Tuple[str, str]] = []
    if source_section_raw and citation_section_raw:
        slots.append(
            (
                "citation_source_id_section_raw_match",
                "true"
                if source_section_raw.lower() == citation_section_raw.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_raw_pair",
                f"{source_section_raw}|{citation_section_raw}",
            )
        )
    if (
        source_has_trailing_punct in {"true", "false"}
        and citation_has_trailing_punct in {"true", "false"}
    ):
        slots.append(
            (
                "citation_source_id_section_trailing_punct_presence_match",
                "true"
                if source_has_trailing_punct == citation_has_trailing_punct
                else "false",
            )
        )
    if (
        source_section_trailing_punct
        or citation_section_trailing_punct
        or (
            source_has_trailing_punct in {"true", "false"}
            and citation_has_trailing_punct in {"true", "false"}
        )
    ):
        slots.append(
            (
                "citation_source_id_section_trailing_punct_match",
                "true"
                if source_section_trailing_punct == citation_section_trailing_punct
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_trailing_punct_pair",
                f"{source_section_trailing_punct or 'none'}|"
                f"{citation_section_trailing_punct or 'none'}",
            )
        )
    if source_title and citation_title:
        slots.append(
            (
                "citation_source_id_title_pair",
                f"{source_title}|{citation_title}",
            )
        )
    if source_section and citation_section:
        slots.append(
            (
                "citation_source_id_section_pair",
                f"{source_section}|{citation_section}",
            )
        )
    if source_key and citation_key:
        slots.append(
            (
                "citation_source_id_title_section_key_pair",
                f"{source_key}|{citation_key}",
            )
        )
    if source_canonical and citation_canonical:
        slots.append(
            (
                "citation_source_id_canonical_pair",
                f"{source_canonical}|{citation_canonical}",
            )
        )
    source_section_signature = _clean_text(
        source_slot_map.get("source_id_section_signature") or ""
    )
    citation_section_signature = _clean_text(
        citation_slot_map.get("citation_section_signature") or ""
    )
    if source_section_signature or citation_section_signature:
        slots.append(
            (
                "citation_source_id_section_signature_pair",
                f"{source_section_signature or 'none'}|"
                f"{citation_section_signature or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_signature_match",
                "true"
                if source_section_signature.lower()
                == citation_section_signature.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_signature_presence_match",
                "true"
                if bool(source_section_signature) == bool(citation_section_signature)
                else "false",
            )
        )
    source_section_profile = _clean_text(
        source_slot_map.get("source_id_section_component_profile") or ""
    )
    citation_section_profile = _clean_text(
        citation_slot_map.get("citation_section_component_profile") or ""
    )
    if source_section_profile or citation_section_profile:
        slots.append(
            (
                "citation_source_id_section_profile_pair",
                f"{source_section_profile or 'none'}|"
                f"{citation_section_profile or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_profile_match",
                "true"
                if source_section_profile.lower() == citation_section_profile.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_profile_presence_match",
                "true"
                if bool(source_section_profile) == bool(citation_section_profile)
                else "false",
            )
        )
    source_section_style = _clean_text(
        source_slot_map.get("source_id_section_style") or ""
    )
    citation_section_style = _clean_text(
        citation_slot_map.get("citation_section_style") or ""
    )
    if source_section_style or citation_section_style:
        slots.append(
            (
                "citation_source_id_section_style_pair",
                f"{source_section_style or 'none'}|{citation_section_style or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_style_match",
                "true"
                if source_section_style.lower() == citation_section_style.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_style_presence_match",
                "true"
                if bool(source_section_style) == bool(citation_section_style)
                else "false",
            )
        )
    source_section_style_canonical = _clean_text(
        source_slot_map.get("source_id_section_style_canonical") or ""
    )
    citation_section_style_canonical = _clean_text(
        citation_slot_map.get("citation_section_style_canonical") or ""
    )
    if source_section_style_canonical or citation_section_style_canonical:
        slots.append(
            (
                "citation_source_id_section_style_canonical_pair",
                f"{source_section_style_canonical or 'none'}|"
                f"{citation_section_style_canonical or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_style_canonical_match",
                "true"
                if source_section_style_canonical.lower()
                == citation_section_style_canonical.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_style_canonical_presence_match",
                "true"
                if bool(source_section_style_canonical)
                == bool(citation_section_style_canonical)
                else "false",
            )
        )
    source_section_suffix_style = _clean_text(
        source_slot_map.get("source_id_section_suffix_style") or ""
    )
    citation_section_suffix_style = _clean_text(
        citation_slot_map.get("citation_section_suffix_style") or ""
    )
    if source_section_suffix_style or citation_section_suffix_style:
        slots.append(
            (
                "citation_source_id_section_suffix_style_pair",
                f"{source_section_suffix_style or 'none'}|"
                f"{citation_section_suffix_style or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_suffix_style_match",
                "true"
                if source_section_suffix_style.lower()
                == citation_section_suffix_style.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_suffix_style_presence_match",
                "true"
                if bool(source_section_suffix_style)
                == bool(citation_section_suffix_style)
                else "false",
            )
        )
    source_section_punctuation_style = _clean_text(
        source_slot_map.get("source_id_section_punctuation_style") or ""
    )
    citation_section_punctuation_style = _clean_text(
        citation_slot_map.get("citation_section_punctuation_style") or ""
    )
    if source_section_punctuation_style or citation_section_punctuation_style:
        slots.append(
            (
                "citation_source_id_section_punctuation_style_pair",
                f"{source_section_punctuation_style or 'none'}|"
                f"{citation_section_punctuation_style or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_punctuation_style_match",
                "true"
                if source_section_punctuation_style.lower()
                == citation_section_punctuation_style.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_punctuation_style_presence_match",
                "true"
                if bool(source_section_punctuation_style)
                == bool(citation_section_punctuation_style)
                else "false",
            )
        )
    source_title_section_signature = _clean_text(
        source_slot_map.get("source_id_title_section_signature_normalized")
        or source_slot_map.get("source_id_title_section_signature")
        or ""
    )
    citation_title_section_signature = _clean_text(
        citation_slot_map.get("citation_title_section_signature_normalized")
        or citation_slot_map.get("citation_title_section_signature")
        or ""
    )
    if source_title_section_signature or citation_title_section_signature:
        slots.append(
            (
                "citation_source_id_title_section_signature_pair",
                f"{source_title_section_signature or 'none'}|"
                f"{citation_title_section_signature or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_title_section_signature_match",
                "true"
                if source_title_section_signature.lower()
                == citation_title_section_signature.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_title_section_signature_presence_match",
                "true"
                if bool(source_title_section_signature)
                == bool(citation_title_section_signature)
                else "false",
            )
        )
    source_title_section_profile = _clean_text(
        source_slot_map.get("source_id_title_section_profile_normalized")
        or source_slot_map.get("source_id_title_section_profile")
        or ""
    )
    citation_title_section_profile = _clean_text(
        citation_slot_map.get("citation_title_section_profile_normalized")
        or citation_slot_map.get("citation_title_section_profile")
        or ""
    )
    if source_title_section_profile or citation_title_section_profile:
        slots.append(
            (
                "citation_source_id_title_section_profile_pair",
                f"{source_title_section_profile or 'none'}|"
                f"{citation_title_section_profile or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_title_section_profile_match",
                "true"
                if source_title_section_profile.lower()
                == citation_title_section_profile.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_title_section_profile_presence_match",
                "true"
                if bool(source_title_section_profile)
                == bool(citation_title_section_profile)
                else "false",
            )
        )
    source_title_number = _clean_text(source_slot_map.get("source_id_title_number") or "")
    citation_title_number = _clean_text(
        citation_slot_map.get("citation_title_number") or ""
    )
    title_number_relation = _primary_terminal_number_relation(
        primary_number=source_title_number,
        terminal_number=citation_title_number,
    )
    if title_number_relation is not None:
        relation, span = title_number_relation
        span_slot = "citation_source_id_title_number_span"
        profile_slot = "citation_source_id_title_number_distance_profile"
        slots.append(("citation_source_id_title_number_relation", relation))
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    slots.extend(
        _numeric_signature_alignment_slots(
            source_number=source_title_number,
            citation_number=citation_title_number,
            slot_prefix="citation_source_id_title_number_signature",
        )
    )
    source_section_primary_number = _clean_text(
        source_slot_map.get("source_id_section_primary_number")
        or source_slot_map.get("source_id_section_number")
        or ""
    )
    citation_section_primary_number = _clean_text(
        citation_slot_map.get("citation_section_primary_number")
        or citation_slot_map.get("citation_section_number")
        or ""
    )
    section_number_relation = _primary_terminal_number_relation(
        primary_number=source_section_primary_number,
        terminal_number=citation_section_primary_number,
    )
    if section_number_relation is not None:
        relation, span = section_number_relation
        span_slot = "citation_source_id_section_primary_number_span"
        profile_slot = "citation_source_id_section_primary_number_distance_profile"
        slots.append(("citation_source_id_section_primary_number_relation", relation))
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    slots.extend(
        _numeric_signature_alignment_slots(
            source_number=source_section_primary_number,
            citation_number=citation_section_primary_number,
            slot_prefix="citation_source_id_section_primary_number_signature",
        )
    )
    source_section_terminal_number = _clean_text(
        source_slot_map.get("source_id_section_terminal_number")
        or source_slot_map.get("source_id_section_number")
        or ""
    )
    citation_section_terminal_number = _clean_text(
        citation_slot_map.get("citation_section_terminal_number")
        or citation_slot_map.get("citation_section_number")
        or ""
    )
    section_terminal_number_relation = _primary_terminal_number_relation(
        primary_number=source_section_terminal_number,
        terminal_number=citation_section_terminal_number,
    )
    if section_terminal_number_relation is not None:
        relation, span = section_terminal_number_relation
        span_slot = "citation_source_id_section_terminal_number_span"
        profile_slot = "citation_source_id_section_terminal_number_distance_profile"
        slots.append(("citation_source_id_section_terminal_number_relation", relation))
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    slots.extend(
        _numeric_signature_alignment_slots(
            source_number=source_section_terminal_number,
            citation_number=citation_section_terminal_number,
            slot_prefix="citation_source_id_section_terminal_number_signature",
        )
    )
    source_section_primary_suffix = _clean_text(
        source_slot_map.get("source_id_section_primary_suffix_normalized")
        or source_slot_map.get("source_id_section_primary_suffix")
        or ""
    )
    citation_section_primary_suffix = _clean_text(
        citation_slot_map.get("citation_section_primary_suffix_normalized")
        or citation_slot_map.get("citation_section_primary_suffix")
        or ""
    )
    if (
        source_section_primary_suffix
        or citation_section_primary_suffix
        or (
            source_section_primary_number
            and citation_section_primary_number
        )
    ):
        slots.append(
            (
                "citation_source_id_section_primary_suffix_pair",
                f"{source_section_primary_suffix or 'none'}|"
                f"{citation_section_primary_suffix or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_suffix_match",
                "true"
                if source_section_primary_suffix.lower()
                == citation_section_primary_suffix.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_suffix_presence_match",
                "true"
                if bool(source_section_primary_suffix)
                == bool(citation_section_primary_suffix)
                else "false",
            )
        )
    source_section_terminal_suffix = _clean_text(
        source_slot_map.get("source_id_section_terminal_suffix_normalized")
        or source_slot_map.get("source_id_section_terminal_suffix")
        or ""
    )
    citation_section_terminal_suffix = _clean_text(
        citation_slot_map.get("citation_section_terminal_suffix_normalized")
        or citation_slot_map.get("citation_section_terminal_suffix")
        or ""
    )
    if (
        source_section_terminal_suffix
        or citation_section_terminal_suffix
        or (
            source_section_terminal_number
            and citation_section_terminal_number
        )
    ):
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_pair",
                f"{source_section_terminal_suffix or 'none'}|"
                f"{citation_section_terminal_suffix or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_match",
                "true"
                if source_section_terminal_suffix.lower()
                == citation_section_terminal_suffix.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_presence_match",
                "true"
                if bool(source_section_terminal_suffix)
                == bool(citation_section_terminal_suffix)
                else "false",
            )
        )
    source_primary_component_signature = _clean_text(
        source_slot_map.get("source_id_section_primary_component_signature") or ""
    )
    citation_primary_component_signature = _clean_text(
        citation_slot_map.get("citation_section_primary_component_signature") or ""
    )
    if source_primary_component_signature and citation_primary_component_signature:
        slots.append(
            (
                "citation_source_id_section_primary_component_signature_match",
                "true"
                if source_primary_component_signature
                == citation_primary_component_signature
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_component_signature_pair",
                f"{source_primary_component_signature}|"
                f"{citation_primary_component_signature}",
            )
        )
    source_terminal_component_signature = _clean_text(
        source_slot_map.get("source_id_section_terminal_component_signature") or ""
    )
    citation_terminal_component_signature = _clean_text(
        citation_slot_map.get("citation_section_terminal_component_signature") or ""
    )
    if source_terminal_component_signature and citation_terminal_component_signature:
        slots.append(
            (
                "citation_source_id_section_terminal_component_signature_match",
                "true"
                if source_terminal_component_signature
                == citation_terminal_component_signature
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_component_signature_pair",
                f"{source_terminal_component_signature}|"
                f"{citation_terminal_component_signature}",
            )
        )
    source_section_profile = _clean_text(
        source_slot_map.get("source_id_section_component_profile") or ""
    )
    citation_section_profile = _clean_text(
        citation_slot_map.get("citation_section_component_profile") or ""
    )
    if source_section_profile or citation_section_profile:
        slots.append(
            (
                "citation_source_id_section_component_profile_pair",
                f"{source_section_profile or 'none'}|"
                f"{citation_section_profile or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_component_profile_match",
                "true"
                if source_section_profile.lower() == citation_section_profile.lower()
                else "false",
            )
        )
    source_section_is_range = _clean_text(
        source_slot_map.get("source_id_section_is_range") or ""
    ).lower()
    citation_section_is_range = _clean_text(
        citation_slot_map.get("citation_section_is_range") or ""
    ).lower()
    if (
        source_section_is_range in {"true", "false"}
        or citation_section_is_range in {"true", "false"}
    ):
        slots.append(
            (
                "citation_source_id_section_is_range_pair",
                f"{source_section_is_range or 'none'}|"
                f"{citation_section_is_range or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_is_range_match",
                "true"
                if source_section_is_range == citation_section_is_range
                else "false",
            )
        )
    source_range_start = _clean_text(
        source_slot_map.get("source_id_section_range_start") or ""
    )
    citation_range_start = _clean_text(
        citation_slot_map.get("citation_section_range_start") or ""
    )
    source_range_end = _clean_text(
        source_slot_map.get("source_id_section_range_end") or ""
    )
    citation_range_end = _clean_text(
        citation_slot_map.get("citation_section_range_end") or ""
    )
    source_range_connector = _clean_text(
        source_slot_map.get("source_id_section_range_connector") or ""
    )
    citation_range_connector = _clean_text(
        citation_slot_map.get("citation_section_range_connector") or ""
    )
    if (
        source_section_is_range == "true"
        or citation_section_is_range == "true"
        or source_range_start
        or citation_range_start
        or source_range_end
        or citation_range_end
        or source_range_connector
        or citation_range_connector
    ):
        slots.append(
            (
                "citation_source_id_section_range_start_pair",
                f"{source_range_start or 'none'}|{citation_range_start or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_start_match",
                "true"
                if source_range_start.lower() == citation_range_start.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_start_presence_match",
                "true"
                if bool(source_range_start) == bool(citation_range_start)
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_end_pair",
                f"{source_range_end or 'none'}|{citation_range_end or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_end_match",
                "true"
                if source_range_end.lower() == citation_range_end.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_end_presence_match",
                "true"
                if bool(source_range_end) == bool(citation_range_end)
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_connector_pair",
                f"{source_range_connector or 'none'}|"
                f"{citation_range_connector or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_connector_match",
                "true"
                if source_range_connector.lower() == citation_range_connector.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_range_connector_presence_match",
                "true"
                if bool(source_range_connector) == bool(citation_range_connector)
                else "false",
            )
        )
    if not source_title or not citation_title or not source_section or not citation_section:
        alignment = "unparsed"
        slots.append(("citation_source_id_alignment", alignment))
        slots.extend(
            _citation_source_id_alignment_profile_slots(
                alignment=alignment,
                source_section_raw=source_section_raw,
                citation_section_raw=citation_section_raw,
                source_has_trailing_punct=source_has_trailing_punct,
                citation_has_trailing_punct=citation_has_trailing_punct,
                source_section_trailing_punct=source_section_trailing_punct,
                citation_section_trailing_punct=citation_section_trailing_punct,
            )
        )
        return _unique_slot_values(slots)

    title_match = source_title.lower() == citation_title.lower()
    section_match = source_section.lower() == citation_section.lower()
    slots.append(
        ("citation_source_id_title_match", "true" if title_match else "false")
    )
    slots.append(
        ("citation_source_id_section_match", "true" if section_match else "false")
    )
    if source_key and citation_key:
        slots.append(
            (
                "citation_source_id_title_section_key_match",
                "true" if source_key.lower() == citation_key.lower() else "false",
            )
        )
    if source_canonical and citation_canonical:
        slots.append(
            (
                "citation_source_id_canonical_match",
                "true"
                if source_canonical.lower() == citation_canonical.lower()
                else "false",
            )
        )
    if title_match and section_match:
        alignment = "exact_match"
    elif title_match:
        alignment = "title_only_match"
    elif section_match:
        alignment = "section_only_match"
    else:
        alignment = "mismatch"
    slots.append(("citation_source_id_alignment", alignment))
    slots.extend(
        _citation_source_id_alignment_profile_slots(
            alignment=alignment,
            source_section_raw=source_section_raw,
            citation_section_raw=citation_section_raw,
            source_has_trailing_punct=source_has_trailing_punct,
            citation_has_trailing_punct=citation_has_trailing_punct,
            source_section_trailing_punct=source_section_trailing_punct,
            citation_section_trailing_punct=citation_section_trailing_punct,
        )
    )
    return _unique_slot_values(slots)


def _citation_source_id_alignment_profile_slots(
    *,
    alignment: str,
    source_section_raw: str,
    citation_section_raw: str,
    source_has_trailing_punct: str,
    citation_has_trailing_punct: str,
    source_section_trailing_punct: str,
    citation_section_trailing_punct: str,
) -> List[Tuple[str, str]]:
    normalized_alignment = _clean_text(alignment).lower() or "unparsed"
    normalized_source_raw = _clean_text(source_section_raw)
    normalized_citation_raw = _clean_text(citation_section_raw)
    normalized_source_punct = _clean_text(source_section_trailing_punct)
    normalized_citation_punct = _clean_text(citation_section_trailing_punct)
    normalized_source_has_punct = _clean_text(source_has_trailing_punct).lower()
    normalized_citation_has_punct = _clean_text(citation_has_trailing_punct).lower()

    if normalized_source_raw and normalized_citation_raw:
        raw_relation = (
            "raw_exact"
            if normalized_source_raw.lower() == normalized_citation_raw.lower()
            else "raw_mismatch"
        )
    elif normalized_source_raw or normalized_citation_raw:
        raw_relation = "raw_partial"
    else:
        raw_relation = "raw_unknown"

    source_has_punct_known = normalized_source_has_punct in {"true", "false"}
    citation_has_punct_known = normalized_citation_has_punct in {"true", "false"}
    if source_has_punct_known and citation_has_punct_known:
        if (
            normalized_source_has_punct == "false"
            and normalized_citation_has_punct == "false"
        ):
            punctuation_relation = "punct_none"
        elif (
            normalized_source_has_punct == "true"
            and normalized_citation_has_punct == "true"
        ):
            punctuation_relation = (
                "punct_exact"
                if normalized_source_punct == normalized_citation_punct
                else "punct_variant"
            )
        else:
            punctuation_relation = "punct_presence_mismatch"
    elif normalized_source_punct or normalized_citation_punct:
        punctuation_relation = "punct_partial"
    else:
        punctuation_relation = "punct_unknown"

    profile = f"{normalized_alignment}_{raw_relation}_{punctuation_relation}"
    slots: List[Tuple[str, str]] = [
        ("citation_source_id_alignment_raw_relation", raw_relation),
        (
            "citation_source_id_alignment_punctuation_relation",
            punctuation_relation,
        ),
        ("citation_source_id_alignment_profile", profile),
    ]
    slots.extend(
        _typed_identifier_slots(
            profile,
            slot_prefix="citation_source_id_alignment_profile",
        )
    )
    return _unique_slot_values(slots)


def _slot_value_map(slots: Sequence[Tuple[str, str]]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for slot, value in slots:
        normalized_slot = _clean_text(slot)
        normalized_value = _clean_text(value)
        if (
            not normalized_slot
            or not normalized_value
            or normalized_slot in values
        ):
            continue
        values[normalized_slot] = normalized_value
    return values


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
        for slot, value in _numeric_signature_slots(
            str(rank),
            slot_prefix="frame_candidate_rank",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
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
            f"{rank}:{frame_id}",
            slot_prefix="frame_candidate_ranked",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
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


def _resolved_modal_operator_label(formula: ModalIRFormula) -> str:
    label = _clean_text(formula.operator.label)
    if label:
        return label
    fallback = _clean_text(_operator_phrase(formula))
    if not fallback or fallback == _clean_text(formula.operator.symbol):
        return ""
    return fallback


def _modal_operator_signature(
    formula: ModalIRFormula,
    *,
    operator_label: str,
) -> str:
    family = _clean_text(formula.operator.family)
    symbol = _clean_text(formula.operator.symbol)
    label = _clean_text(operator_label)
    if not family or not symbol:
        return ""
    if not label:
        return f"{family}:{symbol}"
    return f"{family}:{symbol}:{label}"


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


def _document_span_metric_phrases(
    *,
    document: ModalIRDocument,
    modal_span_coverage: float,
) -> List[DecodedModalPhrase]:
    source_text = _clean_text(document.normalized_text)
    source_length = len(source_text)
    modal_spans = _merged_formula_spans(document.formulas, source_length)
    modal_span_count = len(modal_spans)
    modal_span_char_count = sum(
        max(0, span_end - span_start)
        for span_start, span_end in modal_spans
    )
    source_context_span_count = _source_context_span_count(
        modal_spans=modal_spans,
        source_length=source_length,
    )
    source_context_span_char_count = max(0, source_length - modal_span_char_count)
    support_start, support_end = _support_span(document.formulas)
    support_width = max(0, support_end - support_start)
    coverage_percent = str(int(round(max(0.0, min(1.0, modal_span_coverage)) * 100.0)))

    metric_slots: List[Tuple[str, str]] = [
        ("modal_formula_count", str(len(document.formulas))),
        ("source_text_char_count", str(source_length)),
        ("modal_span_count", str(modal_span_count)),
        ("modal_span_char_count", str(modal_span_char_count)),
        ("source_context_span_count", str(source_context_span_count)),
        ("source_context_span_char_count", str(source_context_span_char_count)),
        ("support_span_start_char", str(support_start)),
        ("support_span_end_char", str(support_end)),
        ("support_span_width", str(support_width)),
        ("modal_span_coverage_percent", coverage_percent),
    ]
    phrases: List[DecodedModalPhrase] = []
    for slot, value in metric_slots:
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
        for signature_slot, signature_value in _numeric_signature_slots(
            value,
            slot_prefix=slot,
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=signature_value,
                    slot=signature_slot,
                    provenance_only=True,
                )
            )

    coverage_bucket = _modal_span_coverage_bucket(
        modal_span_coverage=modal_span_coverage,
        source_length=source_length,
        modal_span_count=modal_span_count,
    )
    phrases.append(
        DecodedModalPhrase(
            text=coverage_bucket,
            slot="modal_span_coverage_bucket",
            provenance_only=True,
        )
    )
    for slot, value in _typed_identifier_slots(
        coverage_bucket,
        slot_prefix="modal_span_coverage_bucket",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _source_context_span_count(
    *,
    modal_spans: Sequence[Tuple[int, int]],
    source_length: int,
) -> int:
    if source_length <= 0:
        return 0
    if not modal_spans:
        return 1
    count = 0
    cursor = 0
    for start, end in modal_spans:
        if cursor < start:
            count += 1
        cursor = max(cursor, end)
    if cursor < source_length:
        count += 1
    return count


def _modal_span_coverage_bucket(
    *,
    modal_span_coverage: float,
    source_length: int,
    modal_span_count: int,
) -> str:
    if source_length <= 0:
        return "no_source_text"
    if modal_span_count <= 0:
        return "no_modal_span"
    normalized_coverage = max(0.0, min(1.0, float(modal_span_coverage)))
    if normalized_coverage < 0.25:
        return "sparse_coverage"
    if normalized_coverage < 0.5:
        return "partial_coverage"
    if normalized_coverage < 0.75:
        return "majority_coverage"
    if normalized_coverage < 1.0:
        return "high_coverage"
    return "full_coverage"


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
    formula: ModalIRFormula,
) -> List[DecodedModalPhrase]:
    parsed = _typed_clause_slot(clause, slot=slot)
    if parsed is None:
        return []
    prefix_slot_value, prefix_key, scoped_value = parsed
    scoped_slot = f"{slot}_{prefix_key}"
    phrases = [
        DecodedModalPhrase(
            text=prefix_slot_value,
            slot=f"{slot}_prefix",
            spans=spans,
            provenance_only=True,
        ),
        DecodedModalPhrase(
            text=prefix_key,
            slot=f"{slot}_prefix_key",
            spans=spans,
            provenance_only=True,
        ),
    ]
    temporal_relation = _temporal_clause_prefix_relation(prefix_key)
    if temporal_relation:
        phrases.append(
            DecodedModalPhrase(
                text="temporal",
                slot=f"{slot}_prefix_family",
                spans=spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=temporal_relation,
                slot=f"{slot}_prefix_temporal_relation",
                spans=spans,
                provenance_only=True,
            )
        )
    for modal_slot, modal_value in _modal_lexeme_slots(
        formula,
        cue=prefix_key,
        slot_prefix=f"{slot}_modal",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=modal_value,
                slot=modal_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    if scoped_value:
        phrases.append(
            DecodedModalPhrase(
                text=scoped_value,
                slot=scoped_slot,
                spans=spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=scoped_value,
                slot=f"{slot}_scope",
                spans=spans,
                provenance_only=True,
            )
        )
        for typed_slot, typed_value in _typed_identifier_slots(
            scoped_value,
            slot_prefix=f"{slot}_scope",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=typed_value,
                    slot=typed_slot,
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
        if not _text_has_prefix(normalized, prefix_text):
            continue
        suffix = _clean_text(normalized[len(prefix_text) :].lstrip(",:;- "))
        return prefix_text, prefix_key, suffix
    return None


def _condition_proxy_phrases_from_exception(
    *,
    exception: str,
    spans: List[List[int]],
    formula: ModalIRFormula,
) -> List[DecodedModalPhrase]:
    scoped_exception = _clean_text(exception)
    if not scoped_exception:
        return []
    phrases: List[DecodedModalPhrase] = [
        DecodedModalPhrase(
            text=scoped_exception,
            slot="condition",
            spans=spans,
            provenance_only=True,
        )
    ]
    for typed_slot, typed_value in _typed_identifier_slots(
        scoped_exception,
        slot_prefix="condition",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=typed_value,
                slot=typed_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    typed_exception = _typed_clause_slot(scoped_exception, slot="exception")
    if typed_exception is None:
        return phrases
    prefix_slot_value, prefix_key, scoped_value = typed_exception
    phrases.extend(
        (
            DecodedModalPhrase(
                text=prefix_slot_value,
                slot="condition_prefix",
                spans=spans,
                provenance_only=True,
            ),
            DecodedModalPhrase(
                text=prefix_key,
                slot="condition_prefix_key",
                spans=spans,
                provenance_only=True,
            ),
        )
    )
    temporal_relation = _temporal_clause_prefix_relation(prefix_key)
    if temporal_relation:
        phrases.extend(
            (
                DecodedModalPhrase(
                    text="temporal",
                    slot="condition_prefix_family",
                    spans=spans,
                    provenance_only=True,
                ),
                DecodedModalPhrase(
                    text=temporal_relation,
                    slot="condition_prefix_temporal_relation",
                    spans=spans,
                    provenance_only=True,
                ),
            )
        )
    for modal_slot, modal_value in _modal_lexeme_slots(
        formula,
        cue=prefix_key,
        slot_prefix="condition_modal",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=modal_value,
                slot=modal_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    if not scoped_value:
        return phrases
    phrases.extend(
        (
            DecodedModalPhrase(
                text=scoped_value,
                slot=f"condition_{prefix_key}",
                spans=spans,
                provenance_only=True,
            ),
            DecodedModalPhrase(
                text=scoped_value,
                slot="condition_scope",
                spans=spans,
                provenance_only=True,
            ),
        )
    )
    for typed_slot, typed_value in _typed_identifier_slots(
        scoped_value,
        slot_prefix="condition_scope",
    ):
        phrases.append(
            DecodedModalPhrase(
                text=typed_value,
                slot=typed_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


def _cue_modal_slots(
    formula: ModalIRFormula,
    *,
    cue: str,
) -> List[Tuple[str, str]]:
    return _modal_lexeme_slots(
        formula,
        cue=cue,
        slot_prefix="cue_modal",
    )


def _formula_cues(formula: ModalIRFormula) -> List[str]:
    cues: List[str] = []
    explicit_cue = _clean_text(formula.metadata.get("cue") or "")
    if explicit_cue:
        cues.append(explicit_cue)
    derived_cue = _derived_modal_cue(formula, explicit_cue=explicit_cue)
    if derived_cue:
        normalized_existing = {value.lower() for value in cues}
        if derived_cue.lower() not in normalized_existing:
            cues.append(derived_cue)
    return cues


def _derived_modal_cue(
    formula: ModalIRFormula,
    *,
    explicit_cue: str,
) -> str:
    normalized_explicit = _clean_text(explicit_cue)
    if normalized_explicit and not _is_fallback_modal_cue(normalized_explicit):
        return ""
    cue_terms = _operator_cue_terms(formula)
    source_text = " ".join(
        _clean_text(value).replace("_", " ").lower()
        for value in (
            formula.predicate.name,
            *formula.conditions,
            *formula.exceptions,
        )
        if _clean_text(value)
    )
    for cue_term in cue_terms:
        normalized_term = _clean_text(cue_term).lower()
        if not normalized_term:
            continue
        if _text_contains_cue_term(source_text, normalized_term):
            return normalized_term
    operator_label = _clean_text(_resolved_modal_operator_label(formula)).lower()
    if operator_label:
        label_tokens = _CUE_TOKEN_RE.findall(operator_label)
        if label_tokens:
            return label_tokens[0]
    return ""


def _operator_cue_terms(formula: ModalIRFormula) -> List[str]:
    family = _clean_text(formula.operator.family).lower()
    symbol = _clean_text(formula.operator.symbol)
    if not family or not symbol:
        return []
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        if _clean_text(profile.family.value).lower() != family:
            continue
        for operator in profile.operators:
            if _clean_text(operator.symbol) != symbol:
                continue
            return [
                _clean_text(cue_term)
                for cue_term in operator.cue_terms
                if _clean_text(cue_term)
            ]
    return []


def _canonical_cue_operator_symbol(
    formula: ModalIRFormula,
    *,
    cue: str,
) -> str:
    family = _clean_text(formula.operator.family).lower()
    cue_value = _clean_text(cue).lower()
    if not family or not cue_value:
        return ""
    matching_symbols: List[str] = []
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        if _clean_text(profile.family.value).lower() != family:
            continue
        for operator in profile.operators:
            if any(
                _cue_matches_registry_term(cue_value, cue_term)
                for cue_term in operator.cue_terms
            ):
                symbol = _clean_text(operator.symbol)
                if symbol and symbol not in matching_symbols:
                    matching_symbols.append(symbol)
    if not matching_symbols:
        return ""
    formula_symbol = _clean_text(formula.operator.symbol)
    if formula_symbol and formula_symbol in matching_symbols:
        return formula_symbol
    return matching_symbols[0]


def _cue_matches_registry_term(
    cue_value: str,
    cue_term: str,
) -> bool:
    normalized_cue_tokens = _CUE_TOKEN_RE.findall(
        _clean_text(cue_value).replace("_", " ").lower()
    )
    normalized_term_tokens = _CUE_TOKEN_RE.findall(
        _clean_text(cue_term).replace("_", " ").lower()
    )
    return bool(normalized_cue_tokens) and normalized_cue_tokens == normalized_term_tokens


def _text_contains_cue_term(text: str, cue_term: str) -> bool:
    normalized_text = _clean_text(text).lower()
    normalized_term = _clean_text(cue_term).lower()
    if not normalized_text or not normalized_term:
        return False
    if " " in normalized_term:
        pattern = re.compile(
            rf"(?<!\w){re.escape(normalized_term)}(?!\w)",
            re.IGNORECASE,
        )
        return pattern.search(normalized_text) is not None
    token_set = set(_CUE_TOKEN_RE.findall(normalized_text))
    if normalized_term in token_set:
        return True
    if normalized_term.endswith("y"):
        plural_variant = f"{normalized_term[:-1]}ies"
        if plural_variant in token_set:
            return True
    return False


def _is_fallback_modal_cue(cue: str) -> bool:
    normalized = _clean_text(cue).lower()
    return normalized.startswith("__") and normalized.endswith("__")


def _cue_alias_slot_name(slot: str) -> str:
    normalized_slot = _clean_text(slot)
    if normalized_slot.startswith("cue_modal_"):
        return f"modal_cue_{normalized_slot[len('cue_modal_') :]}"
    if normalized_slot.startswith("cue_"):
        return f"modal_cue_{normalized_slot[len('cue_') :]}"
    return ""


def _modal_lexeme_slots(
    formula: ModalIRFormula,
    *,
    cue: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    cue_value = _clean_text(cue).lower()
    family = _clean_text(formula.operator.family).lower()
    symbol = _clean_text(formula.operator.symbol)
    normalized_slot_prefix = _clean_text(slot_prefix)
    if not cue_value or not family or not symbol or not normalized_slot_prefix:
        return []
    signature = f"{family}:{symbol}:{cue_value}"
    slots: List[Tuple[str, str]] = [
        (f"{normalized_slot_prefix}_signature", signature),
        (f"{normalized_slot_prefix}_family", family),
        (f"{normalized_slot_prefix}_operator", symbol),
        (f"{normalized_slot_prefix}_lexeme", cue_value),
    ]
    canonical_symbol = _canonical_cue_operator_symbol(formula, cue=cue_value)
    if canonical_symbol:
        slots.append(
            (f"{normalized_slot_prefix}_canonical_operator", canonical_symbol)
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_canonical_signature",
                f"{family}:{canonical_symbol}:{cue_value}",
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_operator_alignment",
                "aligned" if canonical_symbol == symbol else "divergent",
            )
        )
    if symbol == "O|":
        conditional_normative_value = f"{symbol}:{cue_value}"
        slots.append(
            (
                f"{normalized_slot_prefix}_conditional_normative",
                conditional_normative_value,
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_conditional_normative_signature",
                f"conditional_normative:{conditional_normative_value}",
            )
        )
        if normalized_slot_prefix.endswith("_modal"):
            alias_prefix = _clean_text(normalized_slot_prefix[: -len("_modal")])
            if alias_prefix:
                slots.append(
                    (
                        f"{alias_prefix}_conditional_normative",
                        conditional_normative_value,
                    )
                )
    temporal_relation = _temporal_clause_prefix_relation(cue_value)
    if temporal_relation:
        slots.append((f"{normalized_slot_prefix}_temporal_relation", temporal_relation))
    return slots


def _temporal_clause_prefix_relation(prefix_key: str) -> str:
    normalized_key = _clean_text(prefix_key).lower()
    if not normalized_key:
        return ""
    return _TEMPORAL_CLAUSE_PREFIX_RELATIONS.get(normalized_key, "")


def _text_has_prefix(text: str, prefix: str) -> bool:
    normalized_text = _clean_text(text).lower()
    normalized_prefix = _clean_text(prefix).lower()
    if not normalized_text or not normalized_prefix:
        return False
    if not normalized_text.startswith(normalized_prefix):
        return False
    if len(normalized_text) == len(normalized_prefix):
        return True
    suffix_char = normalized_text[len(normalized_prefix)]
    return not suffix_char.isalnum()


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


def _suffix_profile(value: str) -> str:
    cleaned = _clean_text(value).lower()
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return "single"
    if len(set(cleaned)) == 1:
        return "repeat"
    return "mixed"


def _suffix_kind(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    if _is_probable_statutory_roman_suffix(cleaned):
        return "roman"
    if cleaned.isalpha():
        return "alpha"
    return "other"


def _is_probable_statutory_roman_suffix(value: str) -> bool:
    cleaned = _clean_text(value)
    if len(cleaned) <= 1:
        return False
    if not _is_canonical_roman_numeral(cleaned):
        return False
    lowered = cleaned.lower()
    if len(set(lowered)) == 1 and lowered[0] != "i":
        return False
    return True


def _is_canonical_roman_numeral(value: str) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return False
    return _STRICT_ROMAN_NUMERAL_RE.fullmatch(cleaned) is not None


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
    title_number = ""
    if title:
        slots.append(("citation_title", title))
        slots.extend(_typed_identifier_slots(title, slot_prefix="citation_title"))
        title_match = _CITATION_SECTION_PART_RE.fullmatch(title)
        if title_match:
            title_number = _clean_text(title_match.group("number"))
            title_suffix = _clean_text(title_match.group("suffix"))
            if title_number:
                slots.append(("citation_title_number", title_number))
                slots.extend(
                    _numeric_signature_slots(
                        title_number,
                        slot_prefix="citation_title_number",
                    )
                )
            if title_suffix:
                slots.append(("citation_title_suffix", title_suffix))
    slots.append(("citation_code", "U.S.C."))
    if section:
        citation_canonical = _canonical_usc_citation(title, section)
        if citation_canonical:
            slots.append(("citation_canonical", citation_canonical))
        citation_title_section_key = _title_section_coordinate(title, section)
        if citation_title_section_key:
            slots.append(("citation_title_section_key", citation_title_section_key))
            slots.append(
                (
                    "citation_title_section_key_normalized",
                    citation_title_section_key.lower(),
                )
            )
            slots.extend(
                _typed_identifier_slots(
                    citation_title_section_key.replace(":", "_"),
                    slot_prefix="citation_title_section_key",
                )
            )
        slots.append(("citation_section", section))
        if raw_section:
            slots.append(("citation_section_raw", raw_section))
        slots.append(("citation_section_normalized", section))
        if section_trailing_punct:
            slots.append(("citation_section_trailing_punct", section_trailing_punct))
            slots.append(("citation_section_has_trailing_punct", "true"))
            slots.append(
                (
                    "citation_section_trailing_punct_count",
                    str(len(section_trailing_punct)),
                )
            )
            punct_kind = _section_trailing_punct_kind(section_trailing_punct)
            if punct_kind:
                slots.append(("citation_section_trailing_punct_kind", punct_kind))
        else:
            slots.append(("citation_section_has_trailing_punct", "false"))
            slots.append(("citation_section_trailing_punct_count", "0"))
        section_slots = _citation_section_slots(section)
        slots.extend(section_slots)
        section_slot_map = _slot_value_map(section_slots)
        slots.extend(
            _section_style_slots(
                slot_namespace="citation",
                section_slot_map=section_slot_map,
                has_trailing_punct=bool(section_trailing_punct),
            )
        )
        citation_style_map = _slot_value_map(
            [
                slot
                for slot in slots
                if slot[0] in {"citation_section_style", "citation_section_style_canonical"}
            ]
        )
        slots.extend(
            _title_section_style_slots(
                slot_namespace="citation",
                title=title,
                section_style=_clean_text(
                    citation_style_map.get("citation_section_style") or ""
                ),
                section_style_canonical=_clean_text(
                    citation_style_map.get("citation_section_style_canonical") or ""
                ),
            )
        )
        slots.extend(
            _section_structure_slots(
                slot_namespace="citation",
                title=title,
                section_signature=_clean_text(
                    section_slot_map.get("citation_section_signature") or ""
                ),
                section_profile=_clean_text(
                    section_slot_map.get("citation_section_component_profile") or ""
                ),
            )
        )
        slots.extend(
            _title_section_number_relation_slots(
                slot_namespace="citation",
                title_number=title_number,
                section_slot_map=section_slot_map,
            )
        )
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


def _section_trailing_punct_kind(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    if all(character == "." for character in cleaned):
        return "dot"
    if all(character == ":" for character in cleaned):
        return "colon"
    if all(character == ";" for character in cleaned):
        return "semicolon"
    return "other"


def _canonical_usc_citation(title: str, section: str) -> str:
    normalized_title = _clean_text(title)
    normalized_section = _clean_text(_TRAILING_SECTION_PUNCT_RE.sub("", section))
    if not normalized_title or not normalized_section:
        return ""
    return f"{normalized_title} U.S.C. {normalized_section}"


def _title_section_coordinate(title: str, section: str) -> str:
    normalized_title = _clean_text(title)
    normalized_section = _clean_text(_TRAILING_SECTION_PUNCT_RE.sub("", section))
    if not normalized_title or not normalized_section:
        return ""
    return f"{normalized_title}:{normalized_section}"


def _section_structure_slots(
    *,
    slot_namespace: str,
    title: str,
    section_signature: str,
    section_profile: str,
) -> List[Tuple[str, str]]:
    normalized_namespace = _clean_text(slot_namespace)
    normalized_title = _clean_text(title)
    normalized_signature = _clean_text(section_signature)
    normalized_profile = _clean_text(section_profile)
    if not normalized_namespace:
        return []
    slots: List[Tuple[str, str]] = []
    if normalized_profile and normalized_signature:
        profile_signature = f"{normalized_profile}:{normalized_signature}"
        slots.append((f"{normalized_namespace}_section_profile_signature", profile_signature))
        slots.append(
            (
                f"{normalized_namespace}_section_profile_signature_normalized",
                profile_signature.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                profile_signature.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_section_profile_signature",
            )
        )
    if normalized_title and normalized_signature:
        title_section_signature = f"{normalized_title}:{normalized_signature}"
        slots.append(
            (f"{normalized_namespace}_title_section_signature", title_section_signature)
        )
        slots.append(
            (
                f"{normalized_namespace}_title_section_signature_normalized",
                title_section_signature.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                title_section_signature.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_signature",
            )
        )
    if normalized_title and normalized_profile:
        title_section_profile = f"{normalized_title}:{normalized_profile}"
        slots.append((f"{normalized_namespace}_title_section_profile", title_section_profile))
        slots.append(
            (
                f"{normalized_namespace}_title_section_profile_normalized",
                title_section_profile.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                title_section_profile.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_profile",
            )
        )
    return slots


def _title_section_style_slots(
    *,
    slot_namespace: str,
    title: str,
    section_style: str,
    section_style_canonical: str,
) -> List[Tuple[str, str]]:
    normalized_namespace = _clean_text(slot_namespace)
    normalized_title = _clean_text(title)
    normalized_section_style = _clean_text(section_style)
    normalized_section_style_canonical = _clean_text(section_style_canonical)
    if not normalized_namespace or not normalized_title:
        return []
    slots: List[Tuple[str, str]] = []

    if normalized_section_style:
        title_section_style = f"{normalized_title}:{normalized_section_style}"
        slots.append((f"{normalized_namespace}_title_section_style", title_section_style))
        slots.append(
            (
                f"{normalized_namespace}_title_section_style_normalized",
                title_section_style.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                title_section_style.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_style",
            )
        )

    if normalized_section_style_canonical:
        title_section_style_canonical = (
            f"{normalized_title}:{normalized_section_style_canonical}"
        )
        slots.append(
            (
                f"{normalized_namespace}_title_section_style_canonical",
                title_section_style_canonical,
            )
        )
        slots.append(
            (
                f"{normalized_namespace}_title_section_style_canonical_normalized",
                title_section_style_canonical.lower(),
            )
        )
        slots.extend(
            _typed_identifier_slots(
                title_section_style_canonical.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_style_canonical",
            )
        )

    return _unique_slot_values(slots)


def _title_section_number_relation_slots(
    *,
    slot_namespace: str,
    title_number: str,
    section_slot_map: Dict[str, str],
) -> List[Tuple[str, str]]:
    normalized_namespace = _clean_text(slot_namespace)
    normalized_title_number = _clean_text(title_number)
    if not normalized_namespace or not normalized_title_number:
        return []
    primary_number = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_primary_number")
        or section_slot_map.get(f"{normalized_namespace}_section_number")
        or ""
    )
    terminal_number = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_terminal_number")
        or section_slot_map.get(f"{normalized_namespace}_section_number")
        or ""
    )
    slots: List[Tuple[str, str]] = []
    primary_relation = _primary_terminal_number_relation(
        primary_number=normalized_title_number,
        terminal_number=primary_number,
    )
    if primary_relation is not None:
        relation, span = primary_relation
        span_slot = f"{normalized_namespace}_title_section_primary_number_span"
        profile_slot = f"{normalized_namespace}_title_section_primary_number_distance_profile"
        slots.append(
            (
                f"{normalized_namespace}_title_section_primary_number_relation",
                relation,
            )
        )
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    terminal_relation = _primary_terminal_number_relation(
        primary_number=normalized_title_number,
        terminal_number=terminal_number,
    )
    if terminal_relation is not None:
        relation, span = terminal_relation
        span_slot = f"{normalized_namespace}_title_section_terminal_number_span"
        profile_slot = f"{normalized_namespace}_title_section_terminal_number_distance_profile"
        slots.append(
            (
                f"{normalized_namespace}_title_section_terminal_number_relation",
                relation,
            )
        )
        slots.append((span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=profile_slot,
                )
            )
    return slots


def _section_style_slots(
    *,
    slot_namespace: str,
    section_slot_map: Dict[str, str],
    has_trailing_punct: bool,
) -> List[Tuple[str, str]]:
    normalized_namespace = _clean_text(slot_namespace)
    if not normalized_namespace:
        return []
    profile = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_component_profile")
        or ""
    )
    if not profile:
        return []
    suffix_kind = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_primary_suffix_kind")
        or ""
    )
    suffix_case = _clean_text(
        section_slot_map.get(f"{normalized_namespace}_section_primary_suffix_case")
        or ""
    )
    suffix_style = "none"
    if suffix_kind:
        suffix_style = suffix_kind
        if suffix_case:
            suffix_style = f"{suffix_style}_{suffix_case}"
    punctuation_style = "trailing_punct" if has_trailing_punct else "clean"
    style_parts: List[str] = [profile]
    if suffix_style != "none":
        style_parts.append(suffix_style)
    style_parts.append(punctuation_style)
    style = "_".join(style_parts)
    canonical_style = _section_style_canonical(
        profile=profile,
        suffix_kind=suffix_kind,
        suffix_case=suffix_case,
        punctuation_style=punctuation_style,
    )
    slots: List[Tuple[str, str]] = [
        (f"{normalized_namespace}_section_style", style),
        (f"{normalized_namespace}_section_style_canonical", canonical_style),
        (f"{normalized_namespace}_section_suffix_style", suffix_style),
        (f"{normalized_namespace}_section_style_suffix_kind", suffix_kind or "none"),
        (f"{normalized_namespace}_section_style_suffix_case", suffix_case or "none"),
        (f"{normalized_namespace}_section_punctuation_style", punctuation_style),
    ]
    slots.extend(
        _typed_identifier_slots(
            style,
            slot_prefix=f"{normalized_namespace}_section_style",
        )
    )
    slots.extend(
        _typed_identifier_slots(
            canonical_style,
            slot_prefix=f"{normalized_namespace}_section_style_canonical",
        )
    )
    return _unique_slot_values(slots)


def _section_style_canonical(
    *,
    profile: str,
    suffix_kind: str,
    suffix_case: str,
    punctuation_style: str,
) -> str:
    normalized_profile = _clean_text(profile)
    normalized_punctuation_style = _clean_text(punctuation_style)
    if not normalized_profile or not normalized_punctuation_style:
        return ""
    normalized_suffix_kind = _clean_text(suffix_kind) or "none"
    normalized_suffix_case = _clean_text(suffix_case) or "none"
    return (
        f"{normalized_profile}_{normalized_suffix_kind}_"
        f"{normalized_suffix_case}_{normalized_punctuation_style}"
    )


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
    is_range = bool(range_start and range_end and range_connector)
    if is_range:
        components = [range_start, range_end]
    else:
        components = [
            _clean_text(component)
            for component in _CITATION_SECTION_COMPONENT_SPLIT_RE.split(cleaned)
            if _clean_text(component)
        ]
    if not components:
        return []
    primary_component = components[0]
    terminal_component = components[-1]
    slots: List[Tuple[str, str]] = [
        ("citation_section_primary", primary_component),
        ("citation_section_terminal", terminal_component),
        (
            "citation_section_primary_equals_terminal",
            "true" if primary_component == terminal_component else "false",
        ),
        (
            "citation_section_primary_terminal_pair",
            f"{primary_component}|{terminal_component}",
        ),
        ("citation_section_component_count", str(len(components))),
        ("citation_section_is_range", "true" if is_range else "false"),
    ]
    delimiter_tokens = _citation_section_delimiter_tokens(cleaned)
    delimiter_pattern = ""
    if delimiter_tokens:
        slots.append(("citation_section_has_delimiter", "true"))
        slots.append(("citation_section_delimiter_count", str(len(delimiter_tokens))))
        delimiter_kinds: List[str] = []
        for index, delimiter_token in enumerate(delimiter_tokens, start=1):
            position = str(index)
            kind = _citation_section_delimiter_kind(delimiter_token)
            if kind:
                delimiter_kinds.append(kind)
                slots.append(("citation_section_delimiter", kind))
                slots.append(
                    ("citation_section_delimiter_positioned", f"{position}:{kind}")
                )
            slots.append(("citation_section_delimiter_token", delimiter_token))
            slots.append(
                (
                    "citation_section_delimiter_token_positioned",
                    f"{position}:{delimiter_token}",
                )
            )
            char_count = str(len(delimiter_token))
            slots.append(("citation_section_delimiter_char_count", char_count))
            slots.append(
                (
                    "citation_section_delimiter_char_count_positioned",
                    f"{position}:{char_count}",
                )
            )
        if delimiter_kinds:
            delimiter_pattern = "-".join(delimiter_kinds)
            slots.append(
                ("citation_section_delimiter_pattern", delimiter_pattern)
            )
            slots.append(
                (
                    "citation_section_delimiter_distinct_count",
                    str(len(set(delimiter_kinds))),
                )
            )
    else:
        slots.append(("citation_section_has_delimiter", "false"))
        slots.append(("citation_section_delimiter_count", "0"))
    if is_range:
        slots.extend(
            [
                ("citation_section_range", f"{range_start} {range_connector} {range_end}"),
                ("citation_section_range_start", range_start),
                ("citation_section_range_end", range_end),
                ("citation_section_range_connector", range_connector),
            ]
        )
    component_shapes: List[str] = []
    component_signatures: List[str] = []
    numeric_component_count = 0
    suffix_component_count = 0
    roman_suffix_component_count = 0
    parsed_component_count = 0
    primary_has_suffix: bool | None = None
    terminal_has_suffix: bool | None = None
    primary_suffix_is_roman: bool | None = None
    terminal_suffix_is_roman: bool | None = None
    primary_component_kind = ""
    terminal_component_kind = ""
    primary_number = ""
    terminal_number = ""
    primary_suffix = ""
    terminal_suffix = ""
    total_components = len(components)
    for index, component in enumerate(components, start=1):
        position = str(index)
        slots.append(("citation_section_component", component))
        slots.append(("citation_section_component_positioned", f"{position}:{component}"))
        match = _CITATION_SECTION_PART_RE.fullmatch(component)
        if not match:
            component_shapes.append("X")
            component_signature = "X"
            component_signatures.append(component_signature)
            slots.append(("citation_section_component_signature", component_signature))
            slots.append(
                (
                    "citation_section_component_signature_positioned",
                    f"{position}:{component_signature}",
                )
            )
            if index == 1:
                slots.append(
                    ("citation_section_primary_component_signature", component_signature)
                )
            if index == total_components:
                slots.append(
                    ("citation_section_terminal_component_signature", component_signature)
                )
            slots.append(("citation_section_component_kind", "other"))
            slots.append(
                ("citation_section_component_kind_positioned", f"{position}:other")
            )
            if index == 1:
                slots.append(("citation_section_primary_component_kind", "other"))
                primary_component_kind = "other"
            if index == total_components:
                slots.append(("citation_section_terminal_component_kind", "other"))
                terminal_component_kind = "other"
            continue
        number = _clean_text(match.group("number"))
        suffix = _clean_text(match.group("suffix"))
        numeric_component_count += 1
        parsed_component_count += 1
        if index == 1:
            primary_has_suffix = bool(suffix)
            primary_suffix_is_roman = False
        if index == total_components:
            terminal_has_suffix = bool(suffix)
            terminal_suffix_is_roman = False
        if number:
            slots.append(("citation_section_number", number))
            number_digit_count = str(len(number))
            slots.append(("citation_section_number_digit_count", number_digit_count))
            slots.append(
                (
                    "citation_section_number_digit_count_positioned",
                    f"{position}:{number_digit_count}",
                )
            )
            slots.append(("citation_section_number_positioned", f"{position}:{number}"))
            number_suffix_pair = f"{number}|{suffix or 'none'}"
            slots.append(("citation_section_number_suffix_pair", number_suffix_pair))
            slots.append(
                (
                    "citation_section_number_suffix_pair_positioned",
                    f"{position}:{number_suffix_pair}",
                )
            )
            for signature_slot, signature_value in _numeric_signature_slots(
                number,
                slot_prefix="citation_section_number",
            ):
                slots.append((signature_slot, signature_value))
                slots.append(
                    (
                        f"{signature_slot}_positioned",
                        f"{position}:{signature_value}",
                    )
                )
            if index == 1:
                slots.append(("citation_section_primary_number", number))
                primary_number = number
                slots.append(
                    (
                        "citation_section_primary_number_digit_count",
                        number_digit_count,
                    )
                )
                slots.extend(
                    _numeric_signature_slots(
                        number,
                        slot_prefix="citation_section_primary_number",
                    )
                )
                slots.append(
                    (
                        "citation_section_primary_number_suffix_pair",
                        number_suffix_pair,
                    )
                )
            if index == total_components:
                slots.append(("citation_section_terminal_number", number))
                terminal_number = number
                slots.append(
                    (
                        "citation_section_terminal_number_digit_count",
                        number_digit_count,
                    )
                )
                slots.extend(
                    _numeric_signature_slots(
                        number,
                        slot_prefix="citation_section_terminal_number",
                    )
                )
                slots.append(
                    (
                        "citation_section_terminal_number_suffix_pair",
                        number_suffix_pair,
                    )
                )
        suffix_kind = _suffix_kind(suffix) if suffix else ""
        component_signature = _citation_section_component_signature(
            number=number,
            suffix=suffix,
            suffix_kind=suffix_kind,
        )
        component_signatures.append(component_signature)
        slots.append(("citation_section_component_signature", component_signature))
        slots.append(
            (
                "citation_section_component_signature_positioned",
                f"{position}:{component_signature}",
            )
        )
        if index == 1:
            slots.append(("citation_section_primary_component_signature", component_signature))
        if index == total_components:
            slots.append(
                ("citation_section_terminal_component_signature", component_signature)
            )
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
            suffix_char_count = str(len(suffix))
            slots.append(("citation_section_suffix_char_count", suffix_char_count))
            slots.append(
                (
                    "citation_section_suffix_char_count_positioned",
                    f"{position}:{suffix_char_count}",
                )
            )
            suffix_profile = _suffix_profile(suffix)
            if suffix_profile:
                slots.append(("citation_section_suffix_profile", suffix_profile))
                slots.append(
                    (
                        "citation_section_suffix_profile_positioned",
                        f"{position}:{suffix_profile}",
                    )
                )
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
            for alpha_slot, alpha_value in _alpha_signature_slots(
                suffix,
                slot_prefix="citation_section_suffix",
            ):
                slots.append((alpha_slot, alpha_value))
                slots.append(
                    (
                        f"{alpha_slot}_positioned",
                        f"{position}:{alpha_value}",
                    )
                )
            if suffix_kind:
                slots.append(("citation_section_suffix_kind", suffix_kind))
                slots.append(
                    (
                        "citation_section_suffix_kind_positioned",
                        f"{position}:{suffix_kind}",
                    )
                )
                if index == 1:
                    slots.append(("citation_section_primary_suffix_kind", suffix_kind))
                if index == total_components:
                    slots.append(("citation_section_terminal_suffix_kind", suffix_kind))
            if suffix_kind == "roman":
                roman_suffix_component_count += 1
                if index == 1:
                    primary_suffix_is_roman = True
                if index == total_components:
                    terminal_suffix_is_roman = True
            if index == 1:
                primary_suffix = suffix
                slots.append(("citation_section_primary_suffix", suffix))
                slots.append(("citation_section_primary_suffix_char_count", suffix_char_count))
                if suffix_profile:
                    slots.append(("citation_section_primary_suffix_profile", suffix_profile))
                slots.extend(
                    _alpha_signature_slots(
                        suffix,
                        slot_prefix="citation_section_primary_suffix",
                    )
                )
                slots.append(("citation_section_primary_component_kind", "alphanumeric"))
                primary_component_kind = "alphanumeric"
            if index == total_components:
                terminal_suffix = suffix
                slots.append(("citation_section_terminal_suffix", suffix))
                slots.append(("citation_section_terminal_suffix_char_count", suffix_char_count))
                if suffix_profile:
                    slots.append(("citation_section_terminal_suffix_profile", suffix_profile))
                slots.extend(
                    _alpha_signature_slots(
                        suffix,
                        slot_prefix="citation_section_terminal_suffix",
                    )
                )
                slots.append(("citation_section_terminal_component_kind", "alphanumeric"))
                terminal_component_kind = "alphanumeric"
        else:
            component_shapes.append("N")
            slots.append(("citation_section_component_kind", "numeric"))
            slots.append(
                ("citation_section_component_kind_positioned", f"{position}:numeric")
            )
            if index == 1:
                slots.append(("citation_section_primary_component_kind", "numeric"))
                primary_component_kind = "numeric"
            if index == total_components:
                slots.append(("citation_section_terminal_component_kind", "numeric"))
                terminal_component_kind = "numeric"
    if parsed_component_count:
        slots.append(
            (
                "citation_section_has_suffix",
                "true" if suffix_component_count > 0 else "false",
            )
        )
        slots.append(
            (
                "citation_section_has_roman_suffix",
                "true" if roman_suffix_component_count > 0 else "false",
            )
        )
    if primary_has_suffix is not None:
        slots.append(
            (
                "citation_section_primary_has_suffix",
                "true" if primary_has_suffix else "false",
            )
        )
    if primary_suffix_is_roman is not None:
        slots.append(
            (
                "citation_section_primary_suffix_is_roman",
                "true" if primary_suffix_is_roman else "false",
            )
        )
    if terminal_has_suffix is not None:
        slots.append(
            (
                "citation_section_terminal_has_suffix",
                "true" if terminal_has_suffix else "false",
            )
        )
    if terminal_suffix_is_roman is not None:
        slots.append(
            (
                "citation_section_terminal_suffix_is_roman",
                "true" if terminal_suffix_is_roman else "false",
            )
        )
    if component_shapes:
        slots.append(("citation_section_shape", "-".join(component_shapes)))
    if component_signatures:
        slots.append(("citation_section_signature", "-".join(component_signatures)))
        primary_signature = component_signatures[0]
        terminal_signature = component_signatures[-1]
        slots.append(
            (
                "citation_section_primary_terminal_component_signature_pair",
                f"{primary_signature}|{terminal_signature}",
            )
        )
        slots.append(
            (
                "citation_section_primary_terminal_component_signature_match",
                "true" if primary_signature == terminal_signature else "false",
            )
        )
    if primary_component_kind and terminal_component_kind:
        slots.append(
            (
                "citation_section_primary_terminal_component_kind_pair",
                f"{primary_component_kind}|{terminal_component_kind}",
            )
        )
        slots.append(
            (
                "citation_section_primary_terminal_component_kind_match",
                "true" if primary_component_kind == terminal_component_kind else "false",
            )
        )
    component_profile = _citation_section_component_profile(
        component_count=total_components,
        suffix_component_count=suffix_component_count,
        is_range=is_range,
    )
    if component_profile:
        slots.append(("citation_section_component_profile", component_profile))
    numeric_relation = _primary_terminal_number_relation(
        primary_number=primary_number,
        terminal_number=terminal_number,
    )
    if numeric_relation is not None:
        relation, span = numeric_relation
        slots.append(("citation_section_primary_terminal_number_relation", relation))
        slots.append(("citation_section_primary_terminal_number_span", span))
        if is_range:
            slots.append(("citation_section_range_number_relation", relation))
            slots.append(("citation_section_range_number_span", span))
    slots.extend(
        _primary_terminal_suffix_relation_slots(
            primary_suffix=primary_suffix,
            terminal_suffix=terminal_suffix,
            slot_prefix="citation_section_primary_terminal_suffix",
            emit_when_absent=is_range,
        )
    )
    if is_range:
        slots.extend(
            _primary_terminal_suffix_relation_slots(
                primary_suffix=primary_suffix,
                terminal_suffix=terminal_suffix,
                slot_prefix="citation_section_range_suffix",
                emit_when_absent=True,
            )
        )
    if is_range:
        slots.append(
            (
                "citation_section_range_has_suffix",
                "true" if suffix_component_count > 0 else "false",
            )
        )
    slots.append(
        ("citation_section_numeric_component_count", str(numeric_component_count))
    )
    slots.append(
        ("citation_section_suffix_component_count", str(suffix_component_count))
    )
    slots.append(
        (
            "citation_section_roman_suffix_component_count",
            str(roman_suffix_component_count),
        )
    )
    return slots


def _citation_section_delimiter_tokens(section: str) -> List[str]:
    return [
        delimiter
        for delimiter in (
            _clean_text(token) for token in _CITATION_SECTION_DELIMITER_RE.findall(section)
        )
        if delimiter
    ]


def _citation_section_delimiter_kind(delimiter: str) -> str:
    cleaned = _clean_text(delimiter)
    if not cleaned:
        return ""
    if all(character == "." for character in cleaned):
        return "dot"
    if all(character == "-" for character in cleaned):
        return "hyphen"
    if all(character in ".-" for character in cleaned):
        return "mixed"
    return "other"


def _citation_section_component_signature(
    *,
    number: str,
    suffix: str,
    suffix_kind: str,
) -> str:
    number_text = _clean_text(number)
    suffix_text = _clean_text(suffix)
    number_width = str(len(number_text)) if number_text else "0"
    if not suffix_text:
        return f"N{number_width}"
    kind_key = _clean_text(suffix_kind).lower()
    kind_symbol = "R" if kind_key == "roman" else "A" if kind_key == "alpha" else "O"
    return f"N{number_width}{kind_symbol}{len(suffix_text)}"


def _citation_section_component_profile(
    *,
    component_count: int,
    suffix_component_count: int,
    is_range: bool,
) -> str:
    if component_count <= 0:
        return ""
    if is_range:
        return "range"
    if component_count == 1:
        return "single_alphanumeric" if suffix_component_count else "single_numeric"
    if suffix_component_count == 0:
        return "compound_numeric"
    if suffix_component_count == component_count:
        return "compound_alphanumeric"
    return "compound_mixed"


def _primary_terminal_number_relation(
    *,
    primary_number: str,
    terminal_number: str,
) -> Tuple[str, str] | None:
    primary_text = _clean_text(primary_number)
    terminal_text = _clean_text(terminal_number)
    if not primary_text or not terminal_text:
        return None
    try:
        primary_value = int(primary_text)
        terminal_value = int(terminal_text)
    except (TypeError, ValueError):
        return None
    if primary_value == terminal_value:
        return ("equal", "0")
    if primary_value < terminal_value:
        return ("ascending", str(terminal_value - primary_value))
    return ("descending", str(primary_value - terminal_value))


def _primary_terminal_suffix_relation_slots(
    *,
    primary_suffix: str,
    terminal_suffix: str,
    slot_prefix: str,
    emit_when_absent: bool = False,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    if not normalized_slot_prefix:
        return []
    primary = _clean_text(primary_suffix).lower()
    terminal = _clean_text(terminal_suffix).lower()
    if not primary and not terminal and not emit_when_absent:
        return []
    slots: List[Tuple[str, str]] = [
        (
            f"{normalized_slot_prefix}_pair",
            f"{primary or 'none'}|{terminal or 'none'}",
        ),
        (
            f"{normalized_slot_prefix}_match",
            "true" if primary == terminal else "false",
        ),
        (
            f"{normalized_slot_prefix}_presence_match",
            "true" if bool(primary) == bool(terminal) else "false",
        ),
    ]
    if primary and terminal:
        length_relation = _primary_terminal_number_relation(
            primary_number=str(len(primary)),
            terminal_number=str(len(terminal)),
        )
        if length_relation is not None:
            relation, span = length_relation
            slots.append((f"{normalized_slot_prefix}_length_relation", relation))
            slots.append((f"{normalized_slot_prefix}_length_span", span))
        alpha_relation = _primary_terminal_alpha_relation(
            primary_token=primary,
            terminal_token=terminal,
        )
        if alpha_relation is not None:
            relation, span = alpha_relation
            slots.append((f"{normalized_slot_prefix}_alpha_relation", relation))
            slots.append((f"{normalized_slot_prefix}_alpha_span", span))
    return slots


def _primary_terminal_alpha_relation(
    *,
    primary_token: str,
    terminal_token: str,
) -> Tuple[str, str] | None:
    primary_value = _alpha_token_value(primary_token)
    terminal_value = _alpha_token_value(terminal_token)
    if primary_value is None or terminal_value is None:
        return None
    if primary_value == terminal_value:
        return ("equal", "0")
    if primary_value < terminal_value:
        return ("ascending", str(terminal_value - primary_value))
    return ("descending", str(primary_value - terminal_value))


def _alpha_token_value(value: str) -> int | None:
    cleaned = _clean_text(value).lower()
    if not cleaned or not cleaned.isalpha():
        return None
    numeric_value = 0
    for character in cleaned:
        numeric_value = (numeric_value * 26) + (ord(character) - ord("a") + 1)
    return numeric_value


def _numeric_signature_slots(
    value: str,
    *,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    cleaned = _clean_text(value)
    if not cleaned or not cleaned.isdigit():
        return []
    numeric_value = int(cleaned)
    last_digit = cleaned[-1]
    trailing_two_digits = cleaned[-2:] if len(cleaned) > 1 else cleaned
    parity = "even" if last_digit in {"0", "2", "4", "6", "8"} else "odd"
    zero_digit_count = cleaned.count("0")
    trailing_zero_count = len(cleaned) - len(cleaned.rstrip("0"))
    digit_count_bucket = f"{len(cleaned)}_digit"
    magnitude_bucket = _numeric_magnitude_bucket(numeric_value)
    prefix_two_digits = cleaned[:2] if len(cleaned) > 1 else cleaned
    prefix_three_digits = cleaned[:3] if len(cleaned) > 2 else cleaned
    hundreds_block = str(numeric_value // 100)
    thousands_block = str(numeric_value // 1_000)
    return [
        (f"{slot_prefix}_parity", parity),
        (f"{slot_prefix}_digit_count_bucket", digit_count_bucket),
        (f"{slot_prefix}_magnitude_bucket", magnitude_bucket),
        (f"{slot_prefix}_prefix_two_digits", prefix_two_digits),
        (f"{slot_prefix}_prefix_three_digits", prefix_three_digits),
        (f"{slot_prefix}_hundreds_block", hundreds_block),
        (f"{slot_prefix}_thousands_block", thousands_block),
        (f"{slot_prefix}_leading_digit", cleaned[0]),
        (f"{slot_prefix}_trailing_two_digits", trailing_two_digits),
        (f"{slot_prefix}_zero_digit_count", str(zero_digit_count)),
        (
            f"{slot_prefix}_has_zero_digit",
            "true" if zero_digit_count > 0 else "false",
        ),
        (f"{slot_prefix}_trailing_zero_count", str(trailing_zero_count)),
    ]


def _numeric_span_signature_slots(
    *,
    slot_prefix: str,
    span: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    normalized_span = _clean_text(span)
    if not normalized_slot_prefix or not normalized_span.isdigit():
        return []
    return _numeric_signature_slots(normalized_span, slot_prefix=normalized_slot_prefix)


def _numeric_signature_value_map(value: str) -> Dict[str, str]:
    cleaned = _clean_text(value)
    if not cleaned.isdigit():
        return {}
    values: Dict[str, str] = {}
    for slot, slot_value in _numeric_signature_slots(cleaned, slot_prefix="number"):
        key = slot.removeprefix("number_")
        if key:
            values[key] = slot_value
    return values


def _numeric_signature_alignment_slots(
    *,
    source_number: str,
    citation_number: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    if not normalized_slot_prefix:
        return []
    source_signature_values = _numeric_signature_value_map(source_number)
    citation_signature_values = _numeric_signature_value_map(citation_number)
    slots: List[Tuple[str, str]] = []
    for signature_name in _PROVENANCE_NUMERIC_ALIGNMENT_SIGNATURES:
        source_value = _clean_text(source_signature_values.get(signature_name) or "")
        citation_value = _clean_text(citation_signature_values.get(signature_name) or "")
        if not source_value and not citation_value:
            continue
        slots.append(
            (
                f"{normalized_slot_prefix}_{signature_name}_pair",
                f"{source_value or 'none'}|{citation_value or 'none'}",
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_{signature_name}_match",
                "true"
                if source_value.lower() == citation_value.lower()
                else "false",
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_{signature_name}_presence_match",
                "true" if bool(source_value) == bool(citation_value) else "false",
            )
        )
    return slots


def _numeric_magnitude_bucket(value: int) -> str:
    if value < 1_000:
        return "lt_1k"
    if value < 10_000:
        return "1k_to_9k"
    if value < 100_000:
        return "10k_to_99k"
    if value < 1_000_000:
        return "100k_to_999k"
    return "1m_plus"


def _relation_span_profile(
    *,
    relation: str,
    span: str,
) -> str:
    normalized_relation = _clean_text(relation).lower()
    normalized_span = _clean_text(span)
    if not normalized_relation:
        return ""
    if not normalized_span.isdigit():
        return normalized_relation
    return f"{normalized_relation}_{_numeric_magnitude_bucket(int(normalized_span))}"


def _alpha_signature_slots(
    value: str,
    *,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    cleaned = _clean_text(value).lower()
    if not cleaned:
        return []
    letters = [character for character in cleaned if character.isalpha()]
    if not letters:
        return []
    initial = letters[0]
    terminal = letters[-1]
    vowel_count = sum(1 for character in letters if character in _VOWEL_CHARS)
    consonant_count = len(letters) - vowel_count
    slots: List[Tuple[str, str]] = [
        (f"{slot_prefix}_initial", initial),
        (f"{slot_prefix}_terminal", terminal),
        (f"{slot_prefix}_vowel_count", str(vowel_count)),
        (f"{slot_prefix}_consonant_count", str(consonant_count)),
        (
            f"{slot_prefix}_has_vowel",
            "true" if vowel_count > 0 else "false",
        ),
        (
            f"{slot_prefix}_has_consonant",
            "true" if consonant_count > 0 else "false",
        ),
        (f"{slot_prefix}_unique_char_count", str(len(set(letters)))),
        (f"{slot_prefix}_repeat_kind", _alpha_repeat_kind(letters)),
        (f"{slot_prefix}_max_run_length", str(_alpha_max_run_length(letters))),
    ]
    initial_ordinal = _alpha_ordinal(initial)
    if initial_ordinal:
        slots.append((f"{slot_prefix}_initial_ordinal", initial_ordinal))
    terminal_ordinal = _alpha_ordinal(terminal)
    if terminal_ordinal:
        slots.append((f"{slot_prefix}_terminal_ordinal", terminal_ordinal))
    return slots


def _alpha_ordinal(value: str) -> str:
    cleaned = _clean_text(value).lower()
    if len(cleaned) != 1 or not ("a" <= cleaned <= "z"):
        return ""
    return str(ord(cleaned) - ord("a") + 1)


def _alpha_repeat_kind(letters: Sequence[str]) -> str:
    if not letters:
        return ""
    if len(letters) == 1:
        return "single"
    unique_count = len(set(letters))
    if unique_count == 1:
        return "uniform_repeat"
    if unique_count == len(letters):
        return "all_distinct"
    return "mixed_repeat"


def _alpha_max_run_length(letters: Sequence[str]) -> int:
    if not letters:
        return 0
    max_run_length = 1
    current_run_length = 1
    previous = letters[0]
    for character in letters[1:]:
        if character == previous:
            current_run_length += 1
        else:
            current_run_length = 1
            previous = character
        if current_run_length > max_run_length:
            max_run_length = current_run_length
    return max_run_length


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
    mixed_token_count = 0
    alnum_segments: List[str] = []
    for token in tokens:
        if any(character.isdigit() for character in token) and any(
            character.isalpha() for character in token
        ):
            mixed_token_count += 1
        alnum_segments.extend(_alnum_segments(token))
    slots.append(
        (
            f"{slot_prefix}_has_mixed_token",
            "true" if mixed_token_count > 0 else "false",
        )
    )
    slots.append((f"{slot_prefix}_mixed_token_count", str(mixed_token_count)))
    slots.append((f"{slot_prefix}_alnum_segment_count", str(len(alnum_segments))))
    if alnum_segments:
        slots.append((f"{slot_prefix}_alnum_segment_prefix", alnum_segments[0]))
        slots.append((f"{slot_prefix}_alnum_segment_suffix", alnum_segments[-1]))
    for index, segment in enumerate(alnum_segments, start=1):
        position = str(index)
        segment_kind = _alnum_segment_kind(segment)
        slots.append((f"{slot_prefix}_alnum_segment", segment))
        slots.append((f"{slot_prefix}_alnum_segment_positioned", f"{position}:{segment}"))
        slots.append((f"{slot_prefix}_alnum_segment_kind", segment_kind))
        slots.append(
            (
                f"{slot_prefix}_alnum_segment_kind_positioned",
                f"{position}:{segment_kind}",
            )
        )
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


def _alnum_segments(token: str) -> List[str]:
    cleaned = _clean_text(token).lower()
    if not cleaned:
        return []
    return [segment for segment in re.findall(r"[a-z]+|\d+", cleaned) if segment]


def _alnum_segment_kind(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return "other"
    if cleaned.isdigit():
        return "numeric"
    if cleaned.isalpha():
        return "alpha"
    return "other"


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
