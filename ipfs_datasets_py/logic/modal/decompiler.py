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
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    FrameCandidate,
    frame_ontology_terms,
    frame_ontology_terms_from_feature_keys,
    normalize_frame_ontology_term,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    DEFAULT_MODAL_REGISTRY,
)

_CONDITION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("provided that", "provided_that"),
    ("subject to this subsection", "subject_to_this_subsection"),
    ("subject to this subchapter", "subject_to_this_subchapter"),
    ("subject to this subparagraph", "subject_to_this_subparagraph"),
    ("subject to this paragraph", "subject_to_this_paragraph"),
    ("subject to this section", "subject_to_this_section"),
    ("subject to this chapter", "subject_to_this_chapter"),
    ("subject to this title", "subject_to_this_title"),
    ("subject to subsection", "subject_to_subsection"),
    ("subject to subchapter", "subject_to_subchapter"),
    ("subject to subparagraph", "subject_to_subparagraph"),
    ("subject to paragraph", "subject_to_paragraph"),
    ("subject to section", "subject_to_section"),
    ("subject to chapter", "subject_to_chapter"),
    ("subject to title", "subject_to_title"),
    (
        "subject to the terms and conditions",
        "subject_to_the_terms_and_conditions",
    ),
    (
        "subject to such terms and conditions",
        "subject_to_such_terms_and_conditions",
    ),
    ("subject to terms and conditions", "subject_to_terms_and_conditions"),
    ("subject only to", "subject_only_to"),
    ("subject however to", "subject_however_to"),
    ("subject to", "subject_to"),
    ("in the case of", "in_the_case_of"),
    ("in the event that", "in_the_event_that"),
    ("notwithstanding", "notwithstanding"),
    ("for the purposes of", "for_the_purposes_of"),
    ("for purposes of", "for_purposes_of"),
    ("with respect to", "with_respect_to"),
    ("as otherwise provided in", "as_otherwise_provided_in"),
    ("as set forth in", "as_set_forth_in"),
    ("as described in", "as_described_in"),
    ("as defined in", "as_defined_in"),
    ("in accordance with", "in_accordance_with"),
    ("as provided in", "as_provided_in"),
    ("referred to in", "referred_to_in"),
    ("described in", "described_in"),
    ("defined in", "defined_in"),
    ("pursuant to", "pursuant_to"),
    ("to the extent", "to_the_extent"),
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
    ("except as provided in", "except_as_provided_in"),
    ("except to the extent", "except_to_the_extent"),
    ("except that", "except_that"),
    ("except as", "except_as"),
    ("provided that", "provided_that"),
    ("provided", "provided"),
    ("unless", "unless"),
    ("except", "except"),
)
_TEMPORAL_CLAUSE_PREFIX_RELATIONS: dict[str, str] = {
    "when": "when",
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
_USCODE_SECTION_TOKEN_PATTERN = r"\d[0-9A-Za-z.\-]*(?:\([^)]+\))*"
_USCODE_SECTION_LIST_PATTERN = (
    rf"{_USCODE_SECTION_TOKEN_PATTERN}"
    rf"(?:\s*(?:,|and|or|to|through|thru)\s*{_USCODE_SECTION_TOKEN_PATTERN})*"
)
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
    rf"^\s*(?:(?:§{{1,2}}\s*|secs?\.?\s*|sections?\s+){_USCODE_SECTION_LIST_PATTERN}|{_USCODE_SECTION_TOKEN_PATTERN})\s*(?:[.:\-–—]+)?\s*",
    re.IGNORECASE,
)
_USCODE_STATUS_LEADING_SECTION_LABEL_RE = re.compile(
    r"^\s*(?:(?:this|such)\s+)?(?:sections?|secs?\.?)\b\s*[,.:;\-–—]*\s*",
    re.IGNORECASE,
)
_USCODE_STATUS_LEADING_SECTION_NUMBERS_RE = re.compile(
    rf"^\s*[,.:;\-–—]*\s*(?:{_USCODE_SECTION_LIST_PATTERN})\s*[,.:;\-–—]*\s*",
    re.IGNORECASE,
)
_USCODE_INLINE_SECTION_REF_RE = re.compile(
    rf"(?<!\w)(?:§{{1,2}}\s*|secs?\.?\s*|sections?\s+){_USCODE_SECTION_LIST_PATTERN}",
    re.IGNORECASE,
)
_USCODE_GPO_ATTRIBUTION_RE = re.compile(
    r"\bfrom\s+the\s+u\.?\s*s\.?\s+government\s+publishing\s+office\b.*$",
    re.IGNORECASE,
)
_SECTION_HEADING_TAIL_SPLIT_RE = re.compile(r"[.;:\n]")
_INFERRED_CONDITION_CLAUSE_SPLIT_RE = re.compile(r"(?:;|[.?!]|—|–|,(?!\d))")
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
_LOW_INFORMATION_SECTION_MARKER_TOKENS = frozenset(
    {
        "sec",
        "secs",
        "section",
        "sections",
    }
)
_LOW_INFORMATION_SECTION_MARKER_SINGLE_CHAR_TOKENS = frozenset(
    {
        "s",
    }
)
_LOW_INFORMATION_SCOPE_LEADING_TOKENS = frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "that",
        "such",
    }
)
_STRUCTURAL_FRAME_CUE_TOKENS = frozenset(
    {
        "article",
        "chapter",
        "clause",
        "division",
        "paragraph",
        "part",
        "section",
        "subchapter",
        "subclause",
        "subparagraph",
        "subsection",
        "subtitle",
        "title",
    }
)
_CANONICAL_MODAL_OPERATOR_LABELS: Mapping[Tuple[str, str], str] = {
    ("deontic", "O"): "obligation",
    ("deontic", "P"): "permission",
    ("deontic", "F"): "prohibition",
    ("conditional_normative", "O|"): "conditional_obligation",
    ("temporal", "F"): "eventuality",
    ("temporal", "G"): "always",
    ("temporal", "X"): "next",
    ("epistemic", "K"): "knowledge",
    ("doxastic", "B"): "belief",
    ("dynamic", "[a]"): "after_action",
    ("frame", "Frame"): "frame",
}
_CANONICAL_MODAL_OPERATOR_LABEL_ALIASES: Mapping[str, str] = {
    "obligatory": "obligation",
    "obligation": "obligation",
    "permitted": "permission",
    "permission": "permission",
    "forbidden": "prohibition",
    "prohibited": "prohibition",
    "prohibition": "prohibition",
    "conditionally obligatory": "conditional_obligation",
    "conditional obligation": "conditional_obligation",
    "eventually": "eventuality",
    "eventuality": "eventuality",
    "always": "always",
    "next": "next",
    "known": "knowledge",
    "knowledge": "knowledge",
    "believed": "belief",
    "belief": "belief",
    "after action": "after_action",
    "after_action": "after_action",
    "framed as": "frame",
    "frame": "frame",
}
_CUE_REGISTRY_BRIDGE_FAMILIES: frozenset[str] = frozenset(
    {
        "conditional_normative",
        "deontic",
        "temporal",
        "epistemic",
        "doxastic",
        "dynamic",
    }
)
_CUE_REGISTRY_BRIDGE_FAMILY_PRIORITY: Mapping[str, int] = {
    "deontic": 0,
    "temporal": 1,
    "conditional_normative": 2,
    "epistemic": 3,
    "doxastic": 4,
    "dynamic": 5,
}
_CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS: Mapping[str, tuple[tuple[str, str], ...]] = {
    "if": (("conditional_normative", "O|"),),
    "unless": (("conditional_normative", "O|"),),
    "except": (("conditional_normative", "O|"),),
    "except_as": (("conditional_normative", "O|"),),
    "except_as_provided_in": (("conditional_normative", "O|"),),
    "except_that": (("conditional_normative", "O|"),),
    "except_as_otherwise_provided": (("conditional_normative", "O|"),),
    "except_to_the_extent": (("conditional_normative", "O|"),),
    "provided": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "provided_that": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_subsection": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_subchapter": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_subparagraph": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_paragraph": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_section": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_chapter": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_this_title": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_subsection": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_subchapter": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_subparagraph": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_paragraph": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_section": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_chapter": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_title": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_the_terms_and_conditions": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_such_terms_and_conditions": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_to_terms_and_conditions": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_only_to": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "subject_however_to": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
        ("frame", "Frame"),
    ),
    "notwithstanding": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
    ),
    "to_the_extent": (("conditional_normative", "O|"),),
    "to_the_extent_provided": (("conditional_normative", "O|"),),
    "in_accordance_with": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_otherwise_provided_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_provided_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_set_forth_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_described_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "as_defined_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "referred_to_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "described_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "defined_in": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "pursuant_to": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "in_the_event_that": (("conditional_normative", "O|"),),
    "in_the_case_of": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "for_purposes_of": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "for_the_purposes_of": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "with_respect_to": (
        ("conditional_normative", "O|"),
        ("frame", "Frame"),
    ),
    "when": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
    ),
    "until": (
        ("conditional_normative", "O|"),
        ("temporal", "G"),
    ),
    "after": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
        ("dynamic", "[a]"),
    ),
    "before": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
        ("dynamic", "[a]"),
    ),
    "upon": (
        ("conditional_normative", "O|"),
        ("temporal", "X"),
        ("dynamic", "[a]"),
    ),
    "by": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "no_later_than": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "not_later_than": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "shall": (("deontic", "O"),),
    "must": (("deontic", "O"),),
    "obligation": (("deontic", "O"),),
    "obligated": (("deontic", "O"),),
    "obligatory": (("deontic", "O"),),
    "required": (("deontic", "O"),),
    "require": (("deontic", "O"),),
    "requires": (("deontic", "O"),),
    "requiring": (("deontic", "O"),),
    "authorized": (("deontic", "P"),),
    "may": (("deontic", "P"),),
    "authority": (
        ("frame", "Frame"),
        ("deontic", "O"),
    ),
    "jurisdiction": (("frame", "Frame"),),
    "administered_by": (("frame", "Frame"),),
    "transfer": (("dynamic", "[a]"),),
    "transfers": (("dynamic", "[a]"),),
    "transferred": (("dynamic", "[a]"),),
    "transferring": (("dynamic", "[a]"),),
    "vest": (("dynamic", "[a]"),),
    "vests": (("dynamic", "[a]"),),
    "vested": (("dynamic", "[a]"),),
    "vesting": (("dynamic", "[a]"),),
    "fiscal_year": (("temporal", "F"),),
    "fiscal_years": (("temporal", "F"),),
    "calendar_year": (("temporal", "F"),),
    "calendar_years": (("temporal", "F"),),
    "effective_date": (("temporal", "F"),),
    "effective_dates": (("temporal", "F"),),
    "on_and_after": (("temporal", "F"),),
    "on_or_after": (("temporal", "F"),),
    "determine": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "determines": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "determined": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "determining": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "finding": (("epistemic", "K"),),
    "find": (("epistemic", "K"),),
    "finds": (("epistemic", "K"),),
    "knows": (("epistemic", "K"),),
    "know": (("epistemic", "K"),),
    "known": (("epistemic", "K"),),
    "believe": (("doxastic", "B"),),
    "believes": (("doxastic", "B"),),
    "believed": (("doxastic", "B"),),
    "believing": (("doxastic", "B"),),
    "reason_to_believe": (
        ("epistemic", "K"),
        ("doxastic", "B"),
        ("conditional_normative", "O|"),
    ),
    "reasonably_believes": (("doxastic", "B"),),
    "intent_to": (("doxastic", "B"),),
    "with_intent_to": (("doxastic", "B"),),
}
_CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY: Mapping[str, int] = {
    "conditional_normative": 0,
    "deontic": 1,
    "frame": 2,
    "temporal": 3,
    "epistemic": 4,
    "doxastic": 5,
    "dynamic": 6,
}
_DEONTIC_BRIDGE_REINFORCEMENT_OPERATORS: frozenset[str] = frozenset(
    {
        "O",
        "P",
        "F",
    }
)
_DEONTIC_BRIDGE_REINFORCEMENT_CUES: frozenset[str] = frozenset(
    {
        "in_accordance_with",
        "may",
        "must",
        "shall",
        "authorized",
        "with_respect_to",
    }
)
_DEONTIC_EPISTEMIC_BRIDGE_CUES: frozenset[str] = frozenset(
    {
        "believe",
        "believes",
        "believed",
        "believing",
        "reasonably_believes",
    }
)
_DEONTIC_TEMPORAL_BRIDGE_CUES: frozenset[str] = frozenset(
    {
        "shall",
        "must",
        "obligation",
        "obligated",
        "obligatory",
        "required",
        "require",
        "requires",
        "requiring",
        "authorized",
        "may",
    }
)
_FRAME_TEMPORAL_BRIDGE_CUES: frozenset[str] = frozenset(
    _STRUCTURAL_FRAME_CUE_TOKENS
    | {
        "code",
        "frame",
    }
)
_TEMPORAL_BRIDGE_CONTEXT_TOKENS: frozenset[str] = frozenset(
    {
        "year",
        "day",
        "month",
        "deadline",
        "effective",
        "edition",
        "fiscal",
        "calendar",
        "immediately",
        "promptly",
        "timely",
        "period",
        "date",
    }
)
_TEMPORAL_BRIDGE_CONTEXT_PHRASES: tuple[tuple[str, str], ...] = (
    ("on and after", "on_and_after"),
    ("on or after", "on_or_after"),
    ("no later than", "no_later_than"),
    ("not later than", "not_later_than"),
    ("effective date", "effective_date"),
    ("effective dates", "effective_date"),
    ("fiscal year", "fiscal_year"),
    ("fiscal years", "fiscal_year"),
    ("calendar year", "calendar_year"),
    ("calendar years", "calendar_year"),
)
_TEMPORAL_BRIDGE_YEAR_RE = re.compile(r"(?<!\d)(?:18|19|20)\d{2}(?!\d)")
_MODAL_OPERATOR_SYMBOL_FEATURE_KEYS: Mapping[str, str] = {
    "O|": "o_pipe",
    "[a]": "a_box",
    "□": "box",
    "◇": "diamond",
}
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
_FRAME_ONTOLOGY_METADATA_MAX_DEPTH = 6
_FRAME_ONTOLOGY_METADATA_MAX_VALUES = 256
_FRAME_ONTOLOGY_METADATA_OPAQUE_ID_HEX_RE = re.compile(
    r"[0-9a-f]{12,}",
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
    formula_order = tuple(sorted(document.formulas, key=lambda item: item.formula_id))
    phrases: List[DecodedModalPhrase] = [
        *source_phrases,
        *_source_span_slot_phrases(
            source_phrases,
            formulas=document.formulas,
        ),
        *_source_span_slot_phrases(source_phrases, formulas=formula_order),
        *_document_span_metric_phrases(
            document=document,
            modal_span_coverage=modal_span_coverage,
        ),
        *_source_identifier_phrases(document),
        *_document_citation_phrases(document),
        *_document_modal_family_count_phrases(document),
        *_frame_candidate_phrases(document),
        *_frame_ontology_phrases(document),
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

    for index, formula in enumerate(formula_order):
        if index:
            phrases.append(_fixed_phrase(";", "formula_separator"))
        formula_text = modal_formula_to_text(formula)
        formulas.append(formula_text)
        phrases.extend(_decode_formula_phrases(formula, document=document))
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


def _decode_formula_phrases(
    formula: ModalIRFormula,
    *,
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
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
    phrases.extend(
        _content_scope_phrases(
            predicate_text,
            slot_prefix="predicate",
            spans=spans,
        )
    )
    _append_statutory_scope_phrases(
        phrases,
        predicate_text,
        spans=spans,
        emitted=statutory_scope_emissions,
    )
    phrases.extend(
        _contextual_modal_cue_phrases(
            formula=formula,
            text=predicate_text,
            slot_prefix="predicate",
            spans=spans,
        )
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
    canonical_operator_label = _canonical_modal_operator_label(
        formula,
        operator_label=operator_label,
    )
    if canonical_operator_label:
        operator_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=canonical_operator_label,
                slot="modal_operator_label_canonical",
                spans=operator_spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            canonical_operator_label,
            slot_prefix="modal_operator_label_canonical",
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
    for bridge_cue in _formula_bridge_cues(formula):
        bridge_spans = _span_from_values(cue_start, cue_end) or spans
        phrases.append(
            DecodedModalPhrase(
                text=bridge_cue,
                slot="bridge_cue",
                spans=bridge_spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=bridge_cue,
                slot="modal_bridge_cue",
                spans=bridge_spans,
                provenance_only=True,
            )
        )
        for bridge_slot, bridge_value in _modal_lexeme_slots(
            formula,
            cue=bridge_cue,
            slot_prefix="bridge_modal",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=bridge_value,
                    slot=bridge_slot,
                    spans=bridge_spans,
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
        phrases.extend(
            _contextual_modal_cue_phrases(
                formula=formula,
                text=argument,
                slot_prefix="argument",
                spans=spans,
            )
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
    if not condition_values:
        condition_values = _inferred_condition_values_from_source_span(
            document=document,
            formula=formula,
        )
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
    phrases.extend(
        _contextual_modal_cue_phrases(
            formula=formula,
            text=heading_tail,
            slot_prefix="section_heading_tail",
            spans=spans,
        )
    )
    return phrases


def _inferred_condition_values_from_source_span(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_candidates: int = 2,
    max_tokens: int = 40,
) -> List[str]:
    if formula.conditions:
        return []
    span_text = _formula_source_span_text(document=document, formula=formula)
    if not span_text:
        return []
    cue_key = _clean_text(formula.metadata.get("cue") or "").lower().replace(" ", "_")
    ordered_prefixes = sorted(
        _CONDITION_PREFIXES,
        key=lambda item: len(item[0]),
        reverse=True,
    )
    prioritized_prefixes: List[Tuple[str, str]] = []
    if cue_key:
        for prefix_text, prefix_key in ordered_prefixes:
            if prefix_key == cue_key:
                prioritized_prefixes.append((prefix_text, prefix_key))
    prioritized_prefixes.extend(
        (prefix_text, prefix_key)
        for prefix_text, prefix_key in ordered_prefixes
        if (prefix_text, prefix_key) not in prioritized_prefixes
    )
    lowered_span = span_text.lower()
    inferred: List[str] = []
    inferred_lower: set[str] = set()
    for prefix_text, prefix_key in prioritized_prefixes:
        pattern = re.compile(rf"(?<!\w){re.escape(prefix_text)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(lowered_span):
            clause = _trim_inferred_condition_clause(span_text[match.start() :])
            if not clause:
                continue
            token_count = len(_tokenize_for_similarity(clause))
            if token_count < 2 or token_count > max_tokens:
                continue
            parsed_clause = _typed_clause_slot(clause, slot="condition")
            if parsed_clause is None:
                continue
            _, parsed_prefix_key, scoped_value = parsed_clause
            if not scoped_value or parsed_prefix_key != prefix_key:
                continue
            clause_lower = clause.lower()
            if clause_lower in inferred_lower:
                continue
            inferred.append(clause)
            inferred_lower.add(clause_lower)
            if len(inferred) >= max_candidates:
                return inferred
    return inferred


def _formula_source_span_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> str:
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    return _clean_text(source_text[start:end])


def _trim_inferred_condition_clause(clause: str) -> str:
    normalized_clause = _clean_text(clause)
    if not normalized_clause:
        return ""
    trimmed = _clean_text(
        _INFERRED_CONDITION_CLAUSE_SPLIT_RE.split(normalized_clause, maxsplit=1)[0]
    )
    return _TRAILING_SECTION_PUNCT_RE.sub("", trimmed)


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
    phrases.extend(
        _contextual_modal_cue_phrases(
            formula=formula,
            text=surface_text,
            slot_prefix="fallback_surface_text",
            spans=spans,
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
    normalized = _trim_uscode_compilation_surface_text(
        normalized,
        max_tokens=max_tokens,
    )
    if not normalized:
        return ""
    status_keyword = _derived_status_keyword(
        formula=formula,
        fallback_rule=fallback_rule,
    )
    status_surface = _status_heading_surface_text(
        normalized,
        status_keyword=status_keyword,
    )
    if status_surface:
        return status_surface
    if _is_low_information_section_marker(normalized):
        if status_keyword:
            return status_keyword
        inferred_status = _status_keyword_from_source_text(source_text)
        if inferred_status:
            return inferred_status
        return ""
    tokens = _tokenize_for_similarity(normalized)
    if not tokens or len(tokens) > max_tokens:
        return ""
    return normalized


def _trim_uscode_compilation_surface_text(
    text: str,
    *,
    max_tokens: int,
) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    lowered = normalized.lower()
    likely_compilation = (
        "united states code" in lowered
        or lowered.startswith("u.s.c. title")
        or lowered.startswith("usc title")
        or "gpo.gov" in lowered
        or "government publishing office" in lowered
    )
    if not likely_compilation:
        return normalized
    section_match = _USCODE_INLINE_SECTION_REF_RE.search(normalized)
    # Residual span formulas often capture U.S.C. compilation headings that do
    # not include an inline "Sec./§" marker inside the selected span. Keep a
    # bounded cleaned fallback instead of dropping the span entirely so the
    # typed slot indexer preserves informative heading segments.
    if section_match is None:
        candidate = normalized
    else:
        candidate = _clean_text(
            normalized[section_match.end() :].lstrip(" \t\r\n-–—:;,.")
        )
    if not candidate:
        return ""
    candidate = _clean_text(_USCODE_GPO_ATTRIBUTION_RE.sub("", candidate))
    candidate = _TRAILING_SECTION_PUNCT_RE.sub("", candidate)
    if not candidate:
        return ""
    tokens = _tokenize_for_similarity(candidate)
    if not tokens:
        return ""
    if len(tokens) <= max_tokens:
        return candidate
    heading_candidate = _clean_text(_SECTION_HEADING_TAIL_SPLIT_RE.split(candidate, maxsplit=1)[0])
    heading_candidate = _TRAILING_SECTION_PUNCT_RE.sub("", heading_candidate)
    heading_tokens = _tokenize_for_similarity(heading_candidate)
    if heading_tokens and len(heading_tokens) <= max_tokens:
        return heading_candidate
    return ""


def _is_low_information_section_marker(text: str) -> bool:
    normalized = _clean_text(text)
    if not normalized:
        return False
    if re.fullmatch(r"[§\s.]+", normalized):
        return True
    tokens = _CUE_TOKEN_RE.findall(normalized.lower())
    if not tokens:
        return False
    if len(tokens) == 1:
        token = tokens[0]
        if (
            token in _LOW_INFORMATION_SECTION_MARKER_TOKENS
            or token in _LOW_INFORMATION_SECTION_MARKER_SINGLE_CHAR_TOKENS
            or token in _STRUCTURAL_FRAME_CUE_TOKENS
            or token.isdigit()
            or len(token) == 1
        ):
            return True
        if _is_canonical_roman_numeral(token):
            return True
        return False
    if len(tokens) == 2:
        first, second = tokens
        if (
            first in (
                _LOW_INFORMATION_SECTION_MARKER_TOKENS
                | _LOW_INFORMATION_SECTION_MARKER_SINGLE_CHAR_TOKENS
                | _STRUCTURAL_FRAME_CUE_TOKENS
            )
            and (
                second.isdigit()
                or len(second) == 1
                or _is_canonical_roman_numeral(second)
            )
        ):
            return True
    return False


def _status_keyword_from_source_text(text: str) -> str:
    normalized_text = _clean_text(text).lower()
    if not normalized_text:
        return ""
    for keyword in _USCODE_FALLBACK_STATUS_KEYWORDS:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", normalized_text):
            return keyword
    return ""


def _status_heading_surface_text(text: str, *, status_keyword: str) -> str:
    normalized_text = _clean_text(text)
    normalized_keyword = _clean_text(status_keyword).lower()
    if not normalized_text or not normalized_keyword:
        return ""
    lowered_text = normalized_text.lower()
    if not lowered_text.startswith(normalized_keyword):
        stripped_text = _clean_text(
            _USCODE_STATUS_LEADING_SECTION_LABEL_RE.sub("", normalized_text, count=1)
        )
        stripped_text = _clean_text(
            _USCODE_STATUS_LEADING_SECTION_NUMBERS_RE.sub("", stripped_text, count=1)
        )
        lowered_stripped_text = stripped_text.lower()
        if not stripped_text or not lowered_stripped_text.startswith(normalized_keyword):
            return ""
        normalized_text = stripped_text
        lowered_text = lowered_stripped_text
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
    source_section_primary_suffix_kind = _clean_text(
        source_slot_map.get("source_id_section_primary_suffix_kind_coarse")
        or source_slot_map.get("source_id_section_primary_suffix_kind")
        or ""
    )
    citation_section_primary_suffix_kind = _clean_text(
        citation_slot_map.get("citation_section_primary_suffix_kind_coarse")
        or citation_slot_map.get("citation_section_primary_suffix_kind")
        or ""
    )
    if (
        source_section_primary_suffix_kind
        or citation_section_primary_suffix_kind
        or (
            source_section_primary_number
            and citation_section_primary_number
        )
    ):
        slots.append(
            (
                "citation_source_id_section_primary_suffix_kind_pair",
                f"{source_section_primary_suffix_kind or 'none'}|"
                f"{citation_section_primary_suffix_kind or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_suffix_kind_match",
                "true"
                if source_section_primary_suffix_kind.lower()
                == citation_section_primary_suffix_kind.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_primary_suffix_kind_presence_match",
                "true"
                if bool(source_section_primary_suffix_kind)
                == bool(citation_section_primary_suffix_kind)
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
    source_section_terminal_suffix_kind = _clean_text(
        source_slot_map.get("source_id_section_terminal_suffix_kind_coarse")
        or source_slot_map.get("source_id_section_terminal_suffix_kind")
        or ""
    )
    citation_section_terminal_suffix_kind = _clean_text(
        citation_slot_map.get("citation_section_terminal_suffix_kind_coarse")
        or citation_slot_map.get("citation_section_terminal_suffix_kind")
        or ""
    )
    if (
        source_section_terminal_suffix_kind
        or citation_section_terminal_suffix_kind
        or (
            source_section_terminal_number
            and citation_section_terminal_number
        )
    ):
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_kind_pair",
                f"{source_section_terminal_suffix_kind or 'none'}|"
                f"{citation_section_terminal_suffix_kind or 'none'}",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_kind_match",
                "true"
                if source_section_terminal_suffix_kind.lower()
                == citation_section_terminal_suffix_kind.lower()
                else "false",
            )
        )
        slots.append(
            (
                "citation_source_id_section_terminal_suffix_kind_presence_match",
                "true"
                if bool(source_section_terminal_suffix_kind)
                == bool(citation_section_terminal_suffix_kind)
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
        for term in _informative_frame_candidate_terms(
            _phrase_values(getattr(candidate, "matched_terms", ()) or ())
        ):
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


def _informative_frame_candidate_terms(terms: Sequence[str]) -> List[str]:
    informative_terms: List[str] = []
    for raw_term in terms:
        cleaned_term = _clean_text(raw_term)
        if not cleaned_term:
            continue
        # Keep only terms that survive ontology normalization; this drops
        # low-information stopword fragments such as "and"/"the".
        if not normalize_frame_ontology_term(cleaned_term):
            continue
        if cleaned_term not in informative_terms:
            informative_terms.append(cleaned_term)
    return informative_terms


def _frame_ontology_phrases(document: ModalIRDocument) -> List[DecodedModalPhrase]:
    selected_frame = _selected_frame(document)
    frame_terms_by_frame = _frame_ontology_terms_by_frame(document)
    ranked_frame_ids = _ranked_candidate_frame_ids(
        document,
        frame_terms_by_frame=frame_terms_by_frame,
        selected_frame=selected_frame,
    )
    phrases: List[DecodedModalPhrase] = []
    selected_frame_terms: List[str] = []

    for rank, frame_id in enumerate(ranked_frame_ids, start=1):
        phrases.append(
            DecodedModalPhrase(
                text=frame_id,
                slot="candidate_ontology_frame",
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=str(rank),
                slot="candidate_ontology_frame_rank",
                provenance_only=True,
            )
        )
        for slot, value in _numeric_signature_slots(
            str(rank),
            slot_prefix="candidate_ontology_frame_rank",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
        ranked_value = f"{rank}:{frame_id}"
        phrases.append(
            DecodedModalPhrase(
                text=ranked_value,
                slot="candidate_ontology_frame_ranked",
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            ranked_value,
            slot_prefix="candidate_ontology_frame_ranked",
        ):
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    provenance_only=True,
                )
            )
        candidate_terms = frame_terms_by_frame.get(frame_id, [])
        for term in candidate_terms:
            phrases.append(
                DecodedModalPhrase(
                    text=term,
                    slot="candidate_ontology_term",
                    provenance_only=True,
                )
            )
        if selected_frame and frame_id == selected_frame:
            selected_frame_terms = list(candidate_terms)
            for term in selected_frame_terms:
                phrases.append(
                    DecodedModalPhrase(
                        text=term,
                        slot="selected_ontology_term",
                        provenance_only=True,
                    )
                )

    if selected_frame and not selected_frame_terms:
        selected_frame_terms = list(frame_terms_by_frame.get(selected_frame, ()))
        for term in selected_frame_terms:
            phrases.append(
                DecodedModalPhrase(
                    text=term,
                    slot="selected_ontology_term",
                    provenance_only=True,
                )
            )

    if selected_frame:
        phrases.append(
            DecodedModalPhrase(
                text=selected_frame,
                slot="selected_ontology_frame",
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=selected_frame,
                slot="interpreted_in_frame",
                provenance_only=True,
            )
        )
        for term in selected_frame_terms:
            phrases.append(
                DecodedModalPhrase(
                    text=term,
                    slot="interpreted_in_frame_term",
                    provenance_only=True,
                )
            )

    return phrases


def _frame_ontology_terms_by_frame(document: ModalIRDocument) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    metadata_terms = document.metadata.get("frame_ontology_terms")
    if isinstance(metadata_terms, Mapping):
        for frame_id, values in metadata_terms.items():
            frame_key = _clean_text(frame_id)
            if not frame_key:
                continue
            terms = _frame_ontology_metadata_terms(values)
            if terms:
                result[frame_key] = terms

    for frame in document.frame_candidates:
        frame_key = _clean_text(getattr(frame, "frame_id", "") or "")
        if not frame_key:
            continue
        if frame_key in result and result[frame_key]:
            continue
        matched_terms = list(getattr(frame, "matched_terms", ()) or ())
        candidate = FrameCandidate(
            frame_id=frame_key,
            label=frame_key.replace("_", " "),
            terms=tuple(matched_terms),
            domain="general",
        )
        terms = _unique_preserve_order(
            normalize_frame_ontology_term(term)
            for term in frame_ontology_terms(
                candidate,
                matched_terms=matched_terms,
            )
        )
        if terms:
            result[frame_key] = terms
    return result


def _frame_ontology_metadata_terms(value: Any) -> List[str]:
    terms: List[str] = []
    for raw_value in _frame_ontology_metadata_strings(value):
        cleaned = _clean_text(raw_value)
        if not cleaned:
            continue
        if _is_probable_frame_ontology_metadata_identifier(cleaned):
            continue
        source_id_match = _USCODE_SOURCE_ID_RE.match(cleaned)
        if source_id_match:
            source_terms = frame_ontology_terms_from_feature_keys(
                [f"slot:source_id:{cleaned}"],
            )
            if source_terms:
                terms.extend(source_terms)
                continue
        feature_terms = frame_ontology_terms_from_feature_keys([cleaned])
        if feature_terms:
            terms.extend(feature_terms)
            continue
        normalized = normalize_frame_ontology_term(
            cleaned,
            keep_numeric_tokens=True,
        )
        if normalized:
            terms.append(normalized)
    return _unique_preserve_order(terms)


def _frame_ontology_metadata_strings(value: Any) -> List[str]:
    extracted: List[str] = []
    _collect_frame_ontology_metadata_strings(
        value,
        extracted,
        depth=0,
    )
    return extracted


def _collect_frame_ontology_metadata_strings(
    value: Any,
    extracted: List[str],
    *,
    depth: int,
) -> None:
    if (
        value is None
        or depth >= _FRAME_ONTOLOGY_METADATA_MAX_DEPTH
        or len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES
    ):
        return
    if isinstance(value, Mapping):
        for nested_value in value.values():
            _collect_frame_ontology_metadata_strings(
                nested_value,
                extracted,
                depth=depth + 1,
            )
            if len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES:
                return
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested_value in value:
            _collect_frame_ontology_metadata_strings(
                nested_value,
                extracted,
                depth=depth + 1,
            )
            if len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES:
                return
        return
    if isinstance(value, str):
        cleaned = _clean_text(value)
        if cleaned:
            extracted.append(cleaned)


def _is_probable_frame_ontology_metadata_identifier(value: str) -> bool:
    cleaned = _clean_text(value)
    if not cleaned or " " in cleaned:
        return False
    lowered = cleaned.lower()
    if lowered.startswith("modal-synthesis-"):
        return True
    if lowered.startswith("program-"):
        return True
    if _USCODE_SOURCE_ID_RE.match(cleaned):
        return False
    if _FRAME_ONTOLOGY_METADATA_OPAQUE_ID_HEX_RE.search(cleaned) is None:
        return False
    return "-" in cleaned or "_" in cleaned


def _ranked_candidate_frame_ids(
    document: ModalIRDocument,
    *,
    frame_terms_by_frame: Mapping[str, Sequence[str]],
    selected_frame: str,
) -> List[str]:
    ranked_frame_ids: List[str] = []
    seen: set[str] = set()

    for frame in sorted(
        document.frame_candidates,
        key=lambda candidate: _frame_candidate_sort_key(candidate),
    ):
        frame_id = _clean_text(getattr(frame, "frame_id", "") or "")
        if not frame_id or frame_id in seen:
            continue
        seen.add(frame_id)
        ranked_frame_ids.append(frame_id)
    for frame_id in sorted(frame_terms_by_frame):
        cleaned = _clean_text(frame_id)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ranked_frame_ids.append(cleaned)
    normalized_selected = _clean_text(selected_frame)
    if normalized_selected and normalized_selected not in seen:
        ranked_frame_ids.append(normalized_selected)
    return ranked_frame_ids


def _frame_candidate_sort_key(candidate: Any) -> Tuple[float, str]:
    frame_id = _clean_text(getattr(candidate, "frame_id", "") or "")
    try:
        score = float(getattr(candidate, "score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return (-score, frame_id)


def _unique_preserve_order(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


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


def _canonical_modal_operator_label(
    formula: ModalIRFormula,
    *,
    operator_label: str,
) -> str:
    family = _clean_text(formula.operator.family).lower()
    symbol = _clean_text(formula.operator.symbol)
    direct = _CANONICAL_MODAL_OPERATOR_LABELS.get((family, symbol), "")
    if direct:
        return direct
    normalized_label = _clean_text(operator_label).lower()
    if not normalized_label:
        return ""
    return _CANONICAL_MODAL_OPERATOR_LABEL_ALIASES.get(normalized_label, "")


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
    source_text = str(document.normalized_text or "")
    if not _clean_text(source_text):
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


def _source_span_slot_phrases(
    source_phrases: Sequence[DecodedModalPhrase],
    *,
    formulas: Sequence[ModalIRFormula] = (),
) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str, Tuple[Tuple[int, int], ...]]] = set()
    for source_phrase in source_phrases:
        slot_prefix = _clean_text(source_phrase.slot)
        text = _clean_text(source_phrase.text)
        if slot_prefix not in {"modal_source_span", "source_context_span"} or not text:
            continue
        spans = source_phrase.spans
        span_marker = tuple(
            (int(start), int(end))
            for start, end in (
                (span[0], span[1])
                for span in spans
                if isinstance(span, Sequence) and len(span) == 2
            )
            if isinstance(start, int) and isinstance(end, int)
        )
        for slot, value in _typed_identifier_slots(
            text,
            slot_prefix=slot_prefix,
        ):
            marker = (slot, value, span_marker)
            if marker in seen:
                continue
            seen.add(marker)
            phrases.append(
                DecodedModalPhrase(
                    text=value,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        for cue in _bridge_cues_from_text(text):
            cue_marker = (f"{slot_prefix}_bridge_cue", cue, span_marker)
            if cue_marker not in seen:
                seen.add(cue_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=cue,
                        slot=f"{slot_prefix}_bridge_cue",
                        spans=spans,
                        provenance_only=True,
                    )
                )
            modal_cue_marker = (f"{slot_prefix}_modal_bridge_cue", cue, span_marker)
            if modal_cue_marker not in seen:
                seen.add(modal_cue_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=cue,
                        slot=f"{slot_prefix}_modal_bridge_cue",
                        spans=spans,
                        provenance_only=True,
                    )
                )
            for bridge_family, bridge_symbol in _cue_bridge_operator_pairs(cue):
                bridge_signature = f"{bridge_family}:{bridge_symbol}:{cue}"
                bridge_value = f"{bridge_symbol}:{cue}"
                for bridge_slot, bridge_value_text in (
                    (f"{slot_prefix}_bridge_modal_family", bridge_family),
                    (f"{slot_prefix}_bridge_modal_operator", bridge_symbol),
                    (f"{slot_prefix}_bridge_modal_signature", bridge_signature),
                    (
                        f"{slot_prefix}_bridge_modal_{bridge_family}",
                        bridge_value,
                    ),
                ):
                    bridge_marker = (bridge_slot, bridge_value_text, span_marker)
                    if bridge_marker in seen:
                        continue
                    seen.add(bridge_marker)
                    phrases.append(
                        DecodedModalPhrase(
                            text=bridge_value_text,
                            slot=bridge_slot,
                            spans=spans,
                            provenance_only=True,
                        )
                    )
            for (
                formula_family,
                formula_symbol,
                formula_signature,
            ) in _span_formula_modal_signatures(
                formulas,
                spans=spans,
            ):
                formula_signature_marker = (
                    f"{slot_prefix}_bridge_modal_formula_signature",
                    formula_signature,
                    span_marker,
                )
                if formula_signature_marker not in seen:
                    seen.add(formula_signature_marker)
                    phrases.append(
                        DecodedModalPhrase(
                            text=formula_signature,
                            slot=f"{slot_prefix}_bridge_modal_formula_signature",
                            spans=spans,
                            provenance_only=True,
                        )
                    )
                for bridge_family, bridge_symbol in _augment_deontic_bridge_pairs(
                    bridge_pairs=_cue_bridge_operator_pairs(cue),
                    formula_family=formula_family,
                    formula_symbol=formula_symbol,
                    cue=cue,
                ):
                    family_pair = f"{formula_family}->{bridge_family}"
                    operator_pair = f"{formula_symbol}->{bridge_symbol}"
                    transition_signature = (
                        f"{formula_family}:{formula_symbol}->"
                        f"{bridge_family}:{bridge_symbol}:{cue}"
                    )
                    pair_cue = f"{family_pair}:{cue}"
                    for transition_slot, transition_value in (
                        (
                            f"{slot_prefix}_bridge_modal_family_pair",
                            family_pair,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_operator_pair",
                            operator_pair,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_pair_cue",
                            pair_cue,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_transition_signature",
                            transition_signature,
                        ),
                    ):
                        transition_marker = (
                            transition_slot,
                            transition_value,
                            span_marker,
                        )
                        if transition_marker in seen:
                            continue
                        seen.add(transition_marker)
                        phrases.append(
                            DecodedModalPhrase(
                                text=transition_value,
                                slot=transition_slot,
                                spans=spans,
                                provenance_only=True,
                            )
                        )
        for formula in formulas:
            for refined_slot, refined_value in _refined_contextual_modal_transition_slots(
                formula,
                text=text,
                slot_prefix=slot_prefix,
            ):
                refined_marker = (refined_slot, refined_value, span_marker)
                if refined_marker in seen:
                    continue
                seen.add(refined_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=refined_value,
                        slot=refined_slot,
                        spans=spans,
                        provenance_only=True,
                    )
                )
    return phrases


def _span_formula_modal_signatures(
    formulas: Sequence[ModalIRFormula],
    *,
    spans: Sequence[Sequence[int]],
) -> List[Tuple[str, str, str]]:
    signatures: List[Tuple[str, str, str]] = []
    if not formulas or not spans:
        return signatures
    normalized_spans: List[Tuple[int, int]] = []
    for span in spans:
        if not isinstance(span, Sequence) or len(span) != 2:
            continue
        try:
            start = int(span[0])
            end = int(span[1])
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        normalized_spans.append((start, end))
    if not normalized_spans:
        return signatures
    for formula in formulas:
        family = _clean_text(formula.operator.family).lower()
        symbol = _clean_text(formula.operator.symbol)
        if not family or not symbol:
            continue
        try:
            formula_start = int(formula.provenance.start_char)
            formula_end = int(formula.provenance.end_char)
        except (TypeError, ValueError):
            continue
        if formula_end <= formula_start:
            continue
        overlaps = any(
            formula_start < span_end and formula_end > span_start
            for span_start, span_end in normalized_spans
        )
        if not overlaps:
            continue
        signature = (family, symbol, f"{family}:{symbol}")
        if signature not in signatures:
            signatures.append(signature)
    return signatures


def _document_span_metric_phrases(
    *,
    document: ModalIRDocument,
    modal_span_coverage: float,
) -> List[DecodedModalPhrase]:
    source_text = str(document.normalized_text or "")
    source_length = len(source_text) if _clean_text(source_text) else 0
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
    starts: List[int] = []
    ends: List[int] = []
    for formula in formulas:
        try:
            start = int(formula.provenance.start_char)
            end = int(formula.provenance.end_char)
        except (TypeError, ValueError):
            continue
        starts.append(start)
        ends.append(max(start, end))
    if not starts or not ends:
        return [0, 0]
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
        phrases.extend(
            _contextual_modal_cue_phrases(
                formula=formula,
                text=scoped_value,
                slot_prefix=f"{slot}_scope",
                spans=spans,
            )
        )
        phrases.extend(
            _content_scope_phrases(
                scoped_value,
                slot_prefix=f"{slot}_scope",
                spans=spans,
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
    for prefix_text, prefix_key in sorted(
        prefixes,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
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
    phrases.extend(
        _contextual_modal_cue_phrases(
            formula=formula,
            text=scoped_value,
            slot_prefix="condition_scope",
            spans=spans,
        )
    )
    phrases.extend(
        _content_scope_phrases(
            scoped_value,
            slot_prefix="condition_scope",
            spans=spans,
        )
    )
    return phrases


def _content_scope_phrases(
    text: str,
    *,
    slot_prefix: str,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    content_value = _content_scope_value(text)
    if not content_value:
        return []
    phrases: List[DecodedModalPhrase] = [
        DecodedModalPhrase(
            text=content_value,
            slot=f"{slot_prefix}_content",
            spans=spans,
            provenance_only=True,
        )
    ]
    for slot, value in _typed_identifier_slots(
        content_value,
        slot_prefix=f"{slot_prefix}_content",
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


def _content_scope_value(text: str) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    tokens = normalized.split()
    while tokens and tokens[0].lower() in _LOW_INFORMATION_SCOPE_LEADING_TOKENS:
        tokens = tokens[1:]
    if not tokens:
        return ""
    content = _clean_text(" ".join(tokens))
    if not content or content.lower() == normalized.lower():
        return ""
    return content


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
    normalized_existing = {value.lower() for value in cues}
    for temporal_prefix_cue in _temporal_prefix_cues(formula):
        if temporal_prefix_cue in normalized_existing:
            continue
        cues.append(temporal_prefix_cue)
        normalized_existing.add(temporal_prefix_cue)
    return cues


def _temporal_prefix_cues(formula: ModalIRFormula) -> List[str]:
    cues: List[str] = []
    for clause in formula.conditions:
        parsed_clause = _typed_clause_slot(clause, slot="condition")
        if parsed_clause is None:
            continue
        _, prefix_key, _ = parsed_clause
        normalized_prefix_key = _clean_text(prefix_key).lower()
        if (
            normalized_prefix_key
            and _temporal_clause_prefix_relation(normalized_prefix_key)
            and normalized_prefix_key not in cues
        ):
            cues.append(normalized_prefix_key)
    for clause in formula.exceptions:
        parsed_clause = _typed_clause_slot(clause, slot="exception")
        if parsed_clause is None:
            continue
        _, prefix_key, _ = parsed_clause
        normalized_prefix_key = _clean_text(prefix_key).lower()
        if (
            normalized_prefix_key
            and _temporal_clause_prefix_relation(normalized_prefix_key)
            and normalized_prefix_key not in cues
        ):
            cues.append(normalized_prefix_key)
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


def _registry_cue_operator_match(
    formula: ModalIRFormula,
    *,
    cue: str,
) -> Tuple[str, str]:
    matching_pairs = _registry_cue_operator_matches(cue=cue)
    if not matching_pairs:
        return ("", "")
    formula_family = _clean_text(formula.operator.family).lower()
    formula_symbol = _clean_text(formula.operator.symbol)
    if formula_family and formula_symbol and (formula_family, formula_symbol) in matching_pairs:
        return formula_family, formula_symbol
    if formula_family:
        for profile_family, operator_symbol in matching_pairs:
            if profile_family == formula_family:
                return profile_family, operator_symbol
    return matching_pairs[0]


def _registry_cue_operator_matches(
    *,
    cue: str,
) -> List[Tuple[str, str]]:
    cue_value = _clean_text(cue).lower()
    if not cue_value:
        return []
    matching_pairs: List[Tuple[str, str]] = []
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        profile_family = _clean_text(profile.family.value).lower()
        if profile_family not in _CUE_REGISTRY_BRIDGE_FAMILIES:
            continue
        for operator in profile.operators:
            if not any(
                _cue_matches_registry_term(cue_value, cue_term)
                for cue_term in operator.cue_terms
            ):
                continue
            operator_symbol = _clean_text(operator.symbol)
            if not operator_symbol:
                continue
            pair = (profile_family, operator_symbol)
            if pair not in matching_pairs:
                matching_pairs.append(pair)
    return sorted(
        matching_pairs,
        key=lambda item: (
            _CUE_REGISTRY_BRIDGE_FAMILY_PRIORITY.get(
                item[0],
                len(_CUE_REGISTRY_BRIDGE_FAMILY_PRIORITY),
            ),
            item[0],
            item[1],
        ),
    )


def _cue_bridge_operator_pairs(
    cue: str,
) -> List[Tuple[str, str]]:
    normalized_cue = _clean_text(cue).lower()
    if not normalized_cue:
        return []
    cue_key = normalized_cue.replace(" ", "_")
    candidates: List[Tuple[str, str]] = []
    candidates.extend(_registry_cue_operator_matches(cue=normalized_cue))
    candidates.extend(_CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS.get(cue_key, ()))
    unique_pairs: List[Tuple[str, str]] = []
    for family, symbol in sorted(
        candidates,
        key=lambda item: (
            _CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY.get(
                item[0],
                len(_CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY),
            ),
            item[0],
            item[1],
        ),
    ):
        pair = (_clean_text(family).lower(), _clean_text(symbol))
        if (
            not pair[0]
            or not pair[1]
            or pair in unique_pairs
        ):
            continue
        unique_pairs.append(pair)
    return unique_pairs


def _augment_deontic_bridge_pairs(
    *,
    bridge_pairs: Sequence[Tuple[str, str]],
    formula_family: str,
    formula_symbol: str,
    cue: str,
) -> List[Tuple[str, str]]:
    normalized_family = _clean_text(formula_family).lower()
    normalized_symbol = _clean_text(formula_symbol)
    normalized_cue = _clean_text(cue).lower()
    pairs: List[Tuple[str, str]] = []
    for family, symbol in bridge_pairs:
        normalized_pair = (_clean_text(family).lower(), _clean_text(symbol))
        if (
            not normalized_pair[0]
            or not normalized_pair[1]
            or normalized_pair in pairs
        ):
            continue
        pairs.append(normalized_pair)
    if not normalized_cue:
        return pairs
    cue_key = normalized_cue.replace(" ", "_")
    if cue_key in _DEONTIC_BRIDGE_REINFORCEMENT_CUES:
        deontic_scope_pair = ("deontic", "O")
        if deontic_scope_pair not in pairs:
            pairs.append(deontic_scope_pair)
    if (
        normalized_family == "deontic"
        and cue_key in _DEONTIC_EPISTEMIC_BRIDGE_CUES
    ):
        deontic_epistemic_pair = ("epistemic", "K")
        if deontic_epistemic_pair not in pairs:
            pairs.append(deontic_epistemic_pair)
    if (
        normalized_family == "deontic"
        and normalized_symbol in _DEONTIC_BRIDGE_REINFORCEMENT_OPERATORS
        and _temporal_clause_prefix_relation(cue_key)
    ):
        deontic_temporal_pair = ("deontic", normalized_symbol)
        if deontic_temporal_pair not in pairs:
            pairs.append(deontic_temporal_pair)
    return pairs


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


def _modal_operator_feature_key(symbol: str) -> str:
    normalized_symbol = _clean_text(symbol)
    if not normalized_symbol:
        return ""
    mapped_symbol = _MODAL_OPERATOR_SYMBOL_FEATURE_KEYS.get(normalized_symbol)
    if mapped_symbol:
        return mapped_symbol
    tokens = _CUE_TOKEN_RE.findall(normalized_symbol.lower())
    if not tokens:
        return ""
    return "_".join(tokens)


def _modal_operator_pair_feature_key(
    source_symbol: str,
    target_symbol: str,
) -> str:
    source_key = _modal_operator_feature_key(source_symbol)
    target_key = _modal_operator_feature_key(target_symbol)
    if not source_key or not target_key:
        return ""
    return f"{source_key}_to_{target_key}"


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
    alias_prefix = ""
    if normalized_slot_prefix.endswith("_modal"):
        alias_prefix = _clean_text(normalized_slot_prefix[: -len("_modal")])
    cue_key = cue_value.replace(" ", "_")
    reinforce_deontic_self_bridge = (
        family == "deontic"
        and symbol in _DEONTIC_BRIDGE_REINFORCEMENT_OPERATORS
        and (
            cue_key in _DEONTIC_BRIDGE_REINFORCEMENT_CUES
            or bool(_temporal_clause_prefix_relation(cue_key))
        )
    )
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
    registry_family, registry_symbol = _registry_cue_operator_match(
        formula,
        cue=cue_value,
    )
    if registry_family and registry_symbol:
        registry_signature = f"{registry_family}:{registry_symbol}:{cue_value}"
        if registry_family == family and registry_symbol == symbol:
            registry_alignment = "aligned"
        elif registry_family == family:
            registry_alignment = "operator_shift"
        else:
            registry_alignment = "family_shift"
        slots.append((f"{normalized_slot_prefix}_registry_family", registry_family))
        slots.append((f"{normalized_slot_prefix}_registry_operator", registry_symbol))
        slots.append((f"{normalized_slot_prefix}_registry_signature", registry_signature))
        slots.append((f"{normalized_slot_prefix}_registry_alignment", registry_alignment))
        slots.append(
            (
                f"{normalized_slot_prefix}_registry_family_pair",
                f"{family}->{registry_family}",
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_registry_operator_pair",
                f"{symbol}->{registry_symbol}",
            )
        )
        registry_operator_pair_key = _modal_operator_pair_feature_key(
            symbol,
            registry_symbol,
        )
        if registry_operator_pair_key:
            slots.append(
                (
                    f"{normalized_slot_prefix}_registry_operator_pair_key",
                    registry_operator_pair_key,
                )
            )
        if registry_family != family or registry_symbol != symbol:
            bridged_value = f"{registry_symbol}:{cue_value}"
            slots.append((f"{normalized_slot_prefix}_{registry_family}", bridged_value))
            slots.append(
                (
                    f"{normalized_slot_prefix}_{registry_family}_signature",
                    registry_signature,
                )
            )
            if alias_prefix:
                slots.append(
                    (
                        f"{alias_prefix}_{registry_family}",
                        bridged_value,
                    )
                )
    for bridge_family, bridge_symbol in _augment_deontic_bridge_pairs(
        bridge_pairs=_cue_bridge_operator_pairs(cue_value),
        formula_family=family,
        formula_symbol=symbol,
        cue=cue_value,
    ):
        bridge_signature = f"{bridge_family}:{bridge_symbol}:{cue_value}"
        bridge_family_pair = f"{family}->{bridge_family}"
        bridge_operator_pair = f"{symbol}->{bridge_symbol}"
        slots.append(
            (
                f"{normalized_slot_prefix}_bridge_family_pair",
                bridge_family_pair,
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_bridge_operator_pair",
                bridge_operator_pair,
            )
        )
        bridge_operator_pair_key = _modal_operator_pair_feature_key(
            symbol,
            bridge_symbol,
        )
        if bridge_operator_pair_key:
            slots.append(
                (
                    f"{normalized_slot_prefix}_bridge_operator_pair_key",
                    bridge_operator_pair_key,
                )
            )
        if alias_prefix:
            slots.append((f"{alias_prefix}_bridge_family_pair", bridge_family_pair))
            slots.append((f"{alias_prefix}_bridge_operator_pair", bridge_operator_pair))
        if bridge_family == family and bridge_symbol == symbol:
            slots.append((f"{normalized_slot_prefix}_self_bridge_family", bridge_family))
            slots.append((f"{normalized_slot_prefix}_self_bridge_operator", bridge_symbol))
            slots.append((f"{normalized_slot_prefix}_self_bridge_signature", bridge_signature))
            if alias_prefix:
                slots.append((f"{alias_prefix}_self_bridge_family", bridge_family))
                slots.append((f"{alias_prefix}_self_bridge_operator", bridge_symbol))
                slots.append((f"{alias_prefix}_self_bridge_signature", bridge_signature))
            if not reinforce_deontic_self_bridge:
                continue
        bridge_value = f"{bridge_symbol}:{cue_value}"
        slots.append((f"{normalized_slot_prefix}_bridge_family", bridge_family))
        slots.append((f"{normalized_slot_prefix}_bridge_operator", bridge_symbol))
        slots.append((f"{normalized_slot_prefix}_bridge_signature", bridge_signature))
        slots.append((f"{normalized_slot_prefix}_bridge_{bridge_family}", bridge_value))
        if alias_prefix:
            slots.append((f"{alias_prefix}_bridge_family", bridge_family))
            slots.append((f"{alias_prefix}_bridge_operator", bridge_symbol))
            slots.append((f"{alias_prefix}_bridge_signature", bridge_signature))
            slots.append((f"{alias_prefix}_{bridge_family}", bridge_value))
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


def _formula_bridge_cues(formula: ModalIRFormula) -> List[str]:
    searchable_segments: List[str] = []
    predicate_text = _clean_text(formula.predicate.name).replace("_", " ").lower()
    if predicate_text:
        searchable_segments.append(predicate_text)
    searchable_segments.extend(
        _clean_text(value).replace("_", " ").lower()
        for value in (*formula.conditions, *formula.exceptions)
        if _clean_text(value)
    )
    if not searchable_segments:
        return []
    searchable_text = " ".join(searchable_segments)
    cues: List[str] = []
    for cue_key in sorted(
        _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS,
        key=lambda item: (-len(item), item),
    ):
        cue_surface = cue_key.replace("_", " ")
        if not cue_surface:
            continue
        if re.search(rf"(?<!\w){re.escape(cue_surface)}(?!\w)", searchable_text):
            cues.append(cue_key)
    return cues


def _bridge_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    candidate_cue_keys = [
        *sorted(
            _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS,
            key=lambda item: (-len(item), item),
        ),
        *_registry_bridge_cue_keys(),
    ]
    for cue_key in candidate_cue_keys:
        cue_surface = cue_key.replace("_", " ")
        if not cue_surface:
            continue
        if (
            cue_key not in cues
            and re.search(rf"(?<!\w){re.escape(cue_surface)}(?!\w)", normalized_text)
        ):
            cues.append(cue_key)
    return cues


@lru_cache(maxsize=1)
def _registry_bridge_cue_keys() -> Tuple[str, ...]:
    cue_keys: set[str] = set()
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        family = _clean_text(profile.family.value).lower()
        if family not in _CUE_REGISTRY_BRIDGE_FAMILIES and family != "frame":
            continue
        for operator in profile.operators:
            for cue_term in operator.cue_terms:
                normalized_cue = _clean_text(cue_term).replace("_", " ").lower()
                if not normalized_cue:
                    continue
                cue_key = normalized_cue.replace(" ", "_")
                if cue_key in _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS:
                    continue
                if not _is_high_signal_registry_bridge_cue_key(cue_key):
                    continue
                cue_keys.add(cue_key)
    return tuple(sorted(cue_keys, key=lambda item: (-len(item), item)))


def _is_high_signal_registry_bridge_cue_key(cue_key: str) -> bool:
    if not cue_key:
        return False
    # Keep single-token additions conservative to avoid over-triggering on
    # common short words in long section-heading noise.
    return "_" in cue_key or len(cue_key) >= 6


def _contextual_modal_cues_from_text(
    formula: ModalIRFormula,
    *,
    text: str,
) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []

    candidate_terms: List[str] = []
    candidate_terms.extend(
        _clean_text(term).replace("_", " ").lower()
        for term in _operator_cue_terms(formula)
        if _clean_text(term)
    )
    candidate_terms.extend(
        cue_key.replace("_", " ").lower()
        for cue_key in _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS
        if cue_key
    )
    unique_terms = sorted(
        {
            term
            for term in candidate_terms
            if term
        },
        key=lambda item: (-len(item.split()), -len(item), item),
    )

    cues: List[str] = []
    for cue_term in unique_terms:
        if not _text_contains_cue_term(normalized_text, cue_term):
            continue
        cue_tokens = _CUE_TOKEN_RE.findall(cue_term)
        if not cue_tokens:
            continue
        cue_key = "_".join(cue_tokens)
        if cue_key and cue_key not in cues:
            cues.append(cue_key)
    return cues


def _cue_token_stem(token: str) -> str:
    normalized = _clean_text(token).lower()
    if len(normalized) <= 3:
        return normalized
    if normalized.endswith("ies") and len(normalized) > 4:
        return f"{normalized[:-3]}y"
    if (
        normalized.endswith("es")
        and len(normalized) > 4
        and normalized[-3] in {"s", "x", "z", "h"}
    ):
        return normalized[:-2]
    if normalized.endswith("s") and len(normalized) > 4 and not normalized.endswith("ss"):
        return normalized[:-1]
    return normalized


def _text_contains_cue_term_with_stem(text: str, cue_term: str) -> bool:
    normalized_text = _clean_text(text).lower()
    normalized_term = _clean_text(cue_term).lower()
    if not normalized_text or not normalized_term:
        return False
    if _text_contains_cue_term(normalized_text, normalized_term):
        return True
    term_tokens = _CUE_TOKEN_RE.findall(normalized_term)
    if len(term_tokens) != 1:
        return False
    target_stem = _cue_token_stem(term_tokens[0])
    if not target_stem:
        return False
    token_stems = {
        _cue_token_stem(token)
        for token in _CUE_TOKEN_RE.findall(normalized_text)
        if token
    }
    return target_stem in token_stems


def _stem_refined_modal_cues_from_text(
    formula: ModalIRFormula,
    *,
    text: str,
) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    candidate_terms: List[str] = []
    candidate_terms.extend(
        _clean_text(term).replace("_", " ").lower()
        for term in _operator_cue_terms(formula)
        if _clean_text(term)
    )
    candidate_terms.extend(
        cue_key.replace("_", " ").lower()
        for cue_key in _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS
        if cue_key
    )
    unique_terms = sorted(
        {
            term
            for term in candidate_terms
            if term
        },
        key=lambda item: (-len(item.split()), -len(item), item),
    )
    cues: List[str] = []
    for cue_term in unique_terms:
        if not _text_contains_cue_term_with_stem(normalized_text, cue_term):
            continue
        cue_tokens = _CUE_TOKEN_RE.findall(cue_term)
        if not cue_tokens:
            continue
        cue_key = "_".join(cue_tokens)
        if cue_key and cue_key not in cues:
            cues.append(cue_key)
    return cues


def _structural_frame_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for token in _CUE_TOKEN_RE.findall(normalized_text):
        if not token:
            continue
        normalized_token = token
        if normalized_token.endswith("s"):
            singular = normalized_token[:-1]
            if singular in _STRUCTURAL_FRAME_CUE_TOKENS:
                normalized_token = singular
        if (
            normalized_token in _STRUCTURAL_FRAME_CUE_TOKENS
            and normalized_token not in cues
        ):
            cues.append(normalized_token)
    return cues


@lru_cache(maxsize=1)
def _bridge_registry_cue_terms() -> tuple[str, ...]:
    terms: set[str] = set()
    supported_families = set(_CUE_REGISTRY_BRIDGE_FAMILIES)
    supported_families.add("frame")
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        profile_family = _clean_text(profile.family.value).lower()
        if profile_family not in supported_families:
            continue
        for operator in profile.operators:
            for cue_term in operator.cue_terms:
                normalized_term = _clean_text(cue_term).replace("_", " ").lower()
                if normalized_term:
                    terms.add(normalized_term)
    return tuple(
        sorted(
            terms,
            key=lambda item: (-len(item.split()), -len(item), item),
        )
    )


def _bridge_registry_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for cue_term in _bridge_registry_cue_terms():
        if not _text_contains_cue_term(normalized_text, cue_term):
            continue
        cue_tokens = _CUE_TOKEN_RE.findall(cue_term)
        if not cue_tokens:
            continue
        cue_key = "_".join(cue_tokens)
        if cue_key and cue_key not in cues:
            cues.append(cue_key)
    return cues


def _refined_cue_bridge_operator_pairs(
    cue: str,
) -> List[Tuple[str, str]]:
    normalized_cue = _clean_text(cue).lower()
    if not normalized_cue:
        return []
    pairs = _cue_bridge_operator_pairs(normalized_cue)
    if (
        normalized_cue in _STRUCTURAL_FRAME_CUE_TOKENS
        and ("frame", "Frame") not in pairs
    ):
        pairs.append(("frame", "Frame"))
    unique_pairs: List[Tuple[str, str]] = []
    for family, symbol in pairs:
        normalized_family = _clean_text(family).lower()
        normalized_symbol = _clean_text(symbol)
        pair = (normalized_family, normalized_symbol)
        if not pair[0] or not pair[1] or pair in unique_pairs:
            continue
        unique_pairs.append(pair)
    return unique_pairs


def _refined_contextual_modal_cues_from_text(
    formula: ModalIRFormula,
    *,
    text: str,
) -> List[str]:
    formula_family = _clean_text(formula.operator.family).lower()
    cues: List[str] = []
    for cue in _contextual_modal_cues_from_text(formula, text=text):
        if cue and cue not in cues:
            cues.append(cue)
    for cue in _stem_refined_modal_cues_from_text(formula, text=text):
        if cue and cue not in cues:
            cues.append(cue)
    for cue in _structural_frame_cues_from_text(text):
        if cue and cue not in cues:
            cues.append(cue)
    if formula_family == "frame":
        for cue in _bridge_registry_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
        for cue in _structural_frame_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
    return cues


def _refined_contextual_modal_transition_slots(
    formula: ModalIRFormula,
    *,
    text: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    formula_family = _clean_text(formula.operator.family).lower()
    formula_symbol = _clean_text(formula.operator.symbol)
    if not normalized_slot_prefix or not formula_family or not formula_symbol:
        return []
    slots: List[Tuple[str, str]] = []
    for cue in _refined_contextual_modal_cues_from_text(formula, text=text):
        normalized_cue = _clean_text(cue).lower()
        if not normalized_cue:
            continue
        source_signature = f"{formula_family}:{formula_symbol}:{normalized_cue}"
        slots.extend(
            (
                (f"{normalized_slot_prefix}_refined_modal_cue", normalized_cue),
                ("refined_modal_cue", normalized_cue),
                (f"{normalized_slot_prefix}_refined_modal_signature", source_signature),
                ("refined_modal_signature", source_signature),
            )
        )
        for bridge_family, bridge_symbol in _augment_deontic_bridge_pairs(
            bridge_pairs=_refined_cue_bridge_operator_pairs(normalized_cue),
            formula_family=formula_family,
            formula_symbol=formula_symbol,
            cue=normalized_cue,
        ):
            pair = f"{formula_family}->{bridge_family}"
            bridge_signature = f"{bridge_family}:{bridge_symbol}:{normalized_cue}"
            slots.extend(
                (
                    (f"{normalized_slot_prefix}_refined_modal_family_pair", pair),
                    (f"{normalized_slot_prefix}_refined_modal_pair_cue", f"{pair}:{normalized_cue}"),
                    (
                        f"{normalized_slot_prefix}_refined_modal_bridge_signature",
                        bridge_signature,
                    ),
                    ("refined_modal_family_pair", pair),
                    ("refined_modal_pair_cue", f"{pair}:{normalized_cue}"),
                    ("refined_modal_bridge_signature", bridge_signature),
                    ("refined_modal_context_slot", normalized_slot_prefix),
                    ("refined_modal_context_pair", f"{normalized_slot_prefix}:{pair}"),
                )
            )
        slots.extend(
            _refined_temporal_transition_slots(
                formula=formula,
                cue=normalized_cue,
                text=text,
                slot_prefix=normalized_slot_prefix,
            )
        )
    return _unique_slot_values(slots)


def _temporal_transition_context_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for phrase, cue in _TEMPORAL_BRIDGE_CONTEXT_PHRASES:
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized_text):
            if cue not in cues:
                cues.append(cue)
    tokens = _CUE_TOKEN_RE.findall(normalized_text)
    token_set = set(tokens)
    for token in tokens:
        normalized_token = token[:-1] if token.endswith("s") else token
        if (
            normalized_token in _TEMPORAL_BRIDGE_CONTEXT_TOKENS
            and normalized_token not in cues
        ):
            cues.append(normalized_token)
    if _TEMPORAL_BRIDGE_YEAR_RE.search(normalized_text):
        if "year" not in cues:
            cues.append("year")
        if "edition" in token_set and "edition_year" not in cues:
            cues.append("edition_year")
    return cues


def _refined_temporal_transition_slots(
    *,
    formula: ModalIRFormula,
    cue: str,
    text: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    normalized_cue = _clean_text(cue).lower()
    formula_family = _clean_text(formula.operator.family).lower()
    if (
        not normalized_slot_prefix
        or not normalized_cue
        or formula_family not in {"deontic", "frame"}
    ):
        return []
    context_cues = _temporal_transition_context_cues_from_text(text)
    if not context_cues:
        return []
    if formula_family == "deontic":
        if normalized_cue not in _DEONTIC_TEMPORAL_BRIDGE_CUES:
            return []
    elif formula_family == "frame":
        if normalized_cue not in _FRAME_TEMPORAL_BRIDGE_CUES:
            return []

    pair = f"{formula_family}->temporal"
    signature = f"temporal:F:{normalized_cue}"
    slots: List[Tuple[str, str]] = [
        (f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair", pair),
        (f"{normalized_slot_prefix}_refined_temporal_bridge_signature", signature),
        (
            f"{normalized_slot_prefix}_refined_temporal_bridge_pair_cue",
            f"{pair}:{normalized_cue}",
        ),
        ("refined_temporal_bridge_family_pair", pair),
        ("refined_temporal_bridge_signature", signature),
        ("refined_temporal_bridge_pair_cue", f"{pair}:{normalized_cue}"),
        ("refined_temporal_bridge_context_slot", normalized_slot_prefix),
        (
            "refined_temporal_bridge_context_pair",
            f"{normalized_slot_prefix}:{pair}",
        ),
    ]
    for context_cue in context_cues:
        slots.extend(
            (
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_context",
                    context_cue,
                ),
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_context_signature",
                    f"{signature}:{context_cue}",
                ),
                ("refined_temporal_bridge_context", context_cue),
                (
                    "refined_temporal_bridge_context_signature",
                    f"{signature}:{context_cue}",
                ),
            )
        )
    return _unique_slot_values(slots)


def _contextual_modal_cue_phrases(
    *,
    formula: ModalIRFormula,
    text: str,
    slot_prefix: str,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    if not normalized_slot_prefix:
        return []
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str]] = set()
    for cue in _contextual_modal_cues_from_text(formula, text=text):
        for cue_slot, cue_value in (
            (f"{normalized_slot_prefix}_cue", cue),
            (f"{normalized_slot_prefix}_modal_cue", cue),
        ):
            marker = (cue_slot, cue_value)
            if marker in seen:
                continue
            seen.add(marker)
            phrases.append(
                DecodedModalPhrase(
                    text=cue_value,
                    slot=cue_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
        for modal_slot, modal_value in _modal_lexeme_slots(
            formula,
            cue=cue,
            slot_prefix=f"{normalized_slot_prefix}_modal",
        ):
            marker = (modal_slot, modal_value)
            if marker in seen:
                continue
            seen.add(marker)
            phrases.append(
                DecodedModalPhrase(
                    text=modal_value,
                    slot=modal_slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    for refined_slot, refined_value in _refined_contextual_modal_transition_slots(
        formula,
        text=text,
        slot_prefix=normalized_slot_prefix,
    ):
        marker = (refined_slot, refined_value)
        if marker in seen:
            continue
        seen.add(marker)
        phrases.append(
            DecodedModalPhrase(
                text=refined_value,
                slot=refined_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


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
    primary_suffix_kind = ""
    terminal_suffix_kind = ""
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
                    primary_suffix_kind = suffix_kind
                if index == total_components:
                    slots.append(("citation_section_terminal_suffix_kind", suffix_kind))
                    terminal_suffix_kind = suffix_kind
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
        primary_suffix_kind_coarse = primary_suffix_kind or "none"
        terminal_suffix_kind_coarse = terminal_suffix_kind or "none"
        slots.extend(
            [
                (
                    "citation_section_primary_suffix_kind_coarse",
                    primary_suffix_kind_coarse,
                ),
                (
                    "citation_section_terminal_suffix_kind_coarse",
                    terminal_suffix_kind_coarse,
                ),
                (
                    "citation_section_primary_terminal_suffix_kind_pair",
                    f"{primary_suffix_kind_coarse}|{terminal_suffix_kind_coarse}",
                ),
                (
                    "citation_section_primary_terminal_suffix_kind_match",
                    "true"
                    if primary_suffix_kind_coarse == terminal_suffix_kind_coarse
                    else "false",
                ),
            ]
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
        primary_span_slot = "citation_section_primary_terminal_number_span"
        primary_profile_slot = "citation_section_primary_terminal_number_distance_profile"
        slots.append(("citation_section_primary_terminal_number_relation", relation))
        slots.append((primary_span_slot, span))
        slots.extend(
            _numeric_span_signature_slots(
                slot_prefix=primary_span_slot,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            slots.append((primary_profile_slot, relation_profile))
            slots.extend(
                _typed_identifier_slots(
                    relation_profile,
                    slot_prefix=primary_profile_slot,
                )
            )
        if is_range:
            slots.append(("citation_section_range_number_relation", relation))
            range_span_slot = "citation_section_range_number_span"
            range_profile_slot = "citation_section_range_number_distance_profile"
            slots.append((range_span_slot, span))
            slots.extend(
                _numeric_span_signature_slots(
                    slot_prefix=range_span_slot,
                    span=span,
                )
            )
            if relation_profile:
                slots.append((range_profile_slot, relation_profile))
                slots.extend(
                    _typed_identifier_slots(
                        relation_profile,
                        slot_prefix=range_profile_slot,
                    )
                )
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
    has_hyphen_subsection = (
        not is_range
        and total_components == 2
        and delimiter_pattern == "hyphen"
        and bool(primary_number)
        and bool(primary_suffix)
        and bool(terminal_number)
        and not terminal_suffix
    )
    slots.append(
        (
            "citation_section_has_hyphen_subsection",
            "true" if has_hyphen_subsection else "false",
        )
    )
    if has_hyphen_subsection:
        normalized_primary_suffix = primary_suffix.lower()
        hyphen_subsection_signature = (
            f"{primary_number}{normalized_primary_suffix}-{terminal_number}"
        )
        slots.append(
            (
                "citation_section_hyphen_subsection_primary_number",
                primary_number,
            )
        )
        slots.append(
            (
                "citation_section_hyphen_subsection_primary_suffix",
                normalized_primary_suffix,
            )
        )
        slots.append(
            (
                "citation_section_hyphen_subsection_terminal_number",
                terminal_number,
            )
        )
        slots.append(
            (
                "citation_section_hyphen_subsection_signature",
                hyphen_subsection_signature,
            )
        )
        slots.extend(
            _typed_identifier_slots(
                hyphen_subsection_signature,
                slot_prefix="citation_section_hyphen_subsection_signature",
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
    frame_terms_by_frame = _frame_ontology_terms_by_frame(document)
    for frame_id in sorted(frame_terms_by_frame):
        normalized = _clean_text(frame_id)
        if normalized:
            return normalized
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
