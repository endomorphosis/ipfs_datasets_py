"""Deterministic decompiler for modal IR.

The decompiler keeps two views separate:

* ``DecodedModalText.text`` is a provenance-backed semantic reconstruction of
  the source text carried by the IR, so round-trip diagnostics measure whether
  the compiler/decompiler destroyed information.
* Modal formulas, operators, predicates, cues, and ontology frames remain in
  phrase metadata as audit evidence for expert review and program synthesis.
"""

from __future__ import annotations

import math
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
    ("which", "which"),
    ("if", "if"),
    ("when", "when"),
    ("until", "until"),
    ("after", "after"),
    ("before", "before"),
    ("by", "by"),
    ("upon", "upon"),
    ("under", "under"),
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
_LEGAL_SEMANTIC_ATOM_PHRASES: tuple[tuple[str, str], ...] = (
    ("administrative notice hearing", "administrative_notice_hearing"),
    ("notice hearing", "notice_hearing"),
    ("review appeal", "review_appeal"),
    ("records report", "records_report"),
    ("applications", "application"),
    ("application", "application"),
    ("procedures", "procedure"),
    ("procedure", "procedure"),
    ("stationery room", "stationery_room"),
    ("specifications", "specification"),
    ("specification", "specification"),
    ("memorial amphitheater", "memorial_amphitheater"),
    ("amphitheater", "amphitheater"),
    ("reclassified", "reclassified"),
    ("transferred", "transferred"),
    ("codification", "codification"),
    ("repealed", "repealed"),
    ("omitted", "omitted"),
    ("reserved", "reserved"),
    ("vacant", "vacant"),
    ("renumbered", "renumbered"),
    ("terminated", "terminated"),
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
_USCODE_GPO_ATTRIBUTION_FRAGMENT_RE = re.compile(
    r"\bfrom\s+the\s+u(?:\s*\.?\s*s(?:\s*\.?\s*c\.?)?)?\b.*$",
    re.IGNORECASE,
)
_SECTION_HEADING_TAIL_SPLIT_RE = re.compile(r"[.;:\n]")
_INFERRED_CONDITION_CLAUSE_SPLIT_RE = re.compile(
    r"(?:;|[.?!]|—|–|,(?!\s*\d))"
)
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
_SOURCE_ROLE_CUE_MARKERS = frozenset(
    {
        "shall",
        "must",
        "may",
        "required",
        "requires",
        "prohibited",
        "authorized",
        "permitted",
        "eligible",
        "entitled",
        "means",
        "defined",
        "within",
        "before",
        "after",
        "until",
        "during",
        "except",
        "notwithstanding",
    }
)
_SOURCE_ROLE_CONDITION_MARKERS = frozenset(
    {"if", "when", "whenever", "unless", "provided", "subject", "under"}
)
_SOURCE_ROLE_EXCEPTION_MARKERS = frozenset(
    {"except", "exception", "notwithstanding", "waiver", "exemption"}
)
_SOURCE_ROLE_TEMPORAL_MARKERS = frozenset(
    {"before", "after", "within", "until", "during", "by", "upon"}
)
_SOURCE_ROLE_MONTH_TOKENS = frozenset(
    {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
)
_SOURCE_ROLE_TEMPORAL_CONTEXT_TOKENS = frozenset(
    set(_SOURCE_ROLE_TEMPORAL_MARKERS)
    | {
        "calendar",
        "date",
        "dates",
        "deadline",
        "edition",
        "effective",
        "fiscal",
        "month",
        "months",
        "year",
        "years",
    }
)
_SOURCE_ROLE_COMPILATION_NOISE_TOKENS = frozenset(
    {
        "united",
        "states",
        "government",
        "publishing",
        "office",
        "edition",
        "historical",
        "revision",
        "notes",
        "source",
        "statutes",
        "large",
        "codification",
        "editorial",
    }
)
_SOURCE_ROLE_NEGATION_MARKERS = frozenset({"not", "no", "never", "without"})
_SOURCE_ROLE_RELATIONAL_TOKENS = frozenset(
    {
        "across",
        "against",
        "along",
        "among",
        "around",
        "at",
        "between",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "onto",
        "over",
        "per",
        "regarding",
        "respect",
        "through",
        "to",
        "under",
        "upon",
        "with",
    }
)
_SOURCE_ROLE_NOISE_TOKENS = frozenset(
    set(_LOW_INFORMATION_SCOPE_LEADING_TOKENS)
    | set(_SOURCE_ROLE_RELATIONAL_TOKENS)
    | {
        "code",
        "title",
        "chapter",
        "section",
        "subchapter",
        "subsection",
        "paragraph",
        "clause",
        "term",
        "under",
    }
)
_SOURCE_ROLE_CONNECTIVE_TOKENS = frozenset(
    {
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "over",
        "per",
        "to",
        "under",
        "upon",
        "via",
        "with",
        "within",
    }
)
_SOURCE_ROLE_QUANTIFIER_TOKENS = frozenset(
    {
        "all",
        "any",
        "each",
        "either",
        "every",
        "many",
        "most",
        "much",
        "neither",
        "no",
        "some",
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
_LEGAL_IR_VIEW_PROTOTYPES: tuple[str, ...] = (
    "deontic.ir",
    "modal.frame_logic",
    "TDFOL.prover",
    "knowledge_graphs.neo4j_compat",
    "external_provers.router",
    "CEC.native",
    "zkp.circuits",
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
    "unless": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
    ),
    "except": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
    ),
    "except_as": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
    ),
    "except_as_provided_in": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
    ),
    "except_that": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
    ),
    "except_as_otherwise_provided": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
    ),
    "except_to_the_extent": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
    ),
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
    "under": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
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
    "which": (
        ("conditional_normative", "O|"),
        ("deontic", "O"),
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
    "is_entitled_to": (("deontic", "O"),),
    "shall_be_entitled_to": (("deontic", "O"),),
    "has_a_duty_to": (("deontic", "O"),),
    "have_a_duty_to": (("deontic", "O"),),
    "under_an_obligation_to": (("deontic", "O"),),
    "authorized": (("deontic", "P"),),
    "may": (("deontic", "P"),),
    "allowed": (("deontic", "P"),),
    "permitted": (("deontic", "P"),),
    "may_not": (("deontic", "F"),),
    "must_not": (("deontic", "F"),),
    "shall_not": (("deontic", "F"),),
    "prohibited": (("deontic", "F"),),
    "forbidden": (("deontic", "F"),),
    "rule": (
        ("frame", "Frame"),
        ("deontic", "O"),
    ),
    "rules": (
        ("frame", "Frame"),
        ("deontic", "O"),
    ),
    "procedure": (
        ("frame", "Frame"),
        ("deontic", "O"),
    ),
    "procedures": (
        ("frame", "Frame"),
        ("deontic", "O"),
    ),
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
    "reclassified": (
        ("dynamic", "[a]"),
        ("frame", "Frame"),
    ),
    "codification": (
        ("dynamic", "[a]"),
        ("frame", "Frame"),
    ),
    "renumbered": (
        ("dynamic", "[a]"),
        ("frame", "Frame"),
    ),
    "vest": (("dynamic", "[a]"),),
    "vests": (("dynamic", "[a]"),),
    "vested": (("dynamic", "[a]"),),
    "vesting": (("dynamic", "[a]"),),
    "repealed": (
        ("deontic", "F"),
        ("frame", "Frame"),
        ("temporal", "F"),
    ),
    "omitted": (
        ("frame", "Frame"),
        ("temporal", "F"),
    ),
    "reserved": (("frame", "Frame"),),
    "vacant": (("frame", "Frame"),),
    "terminated": (
        ("deontic", "F"),
        ("frame", "Frame"),
        ("temporal", "F"),
    ),
    "fiscal_year": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "fiscal_years": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "calendar_year": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "calendar_years": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "effective_date": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "effective_dates": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "on_and_after": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
    "on_or_after": (
        ("conditional_normative", "O|"),
        ("temporal", "F"),
    ),
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
_SOURCE_ANCHOR_DIRECTIONAL_FAMILY_PAIR_TARGETS: Mapping[str, tuple[str, ...]] = {
    "alethic": ("conditional_normative", "deontic", "temporal"),
    "deontic": ("conditional_normative", "deontic", "temporal"),
    "frame": ("deontic", "doxastic", "frame", "temporal"),
    "deontic": ("conditional_normative", "deontic"),
    "frame": ("conditional_normative", "deontic", "doxastic", "frame", "temporal"),
    "temporal": ("conditional_normative", "deontic", "epistemic", "temporal"),
}
_DECOMPILER_REFINED_FAMILY_PAIR_TARGETS: Mapping[str, tuple[str, ...]] = {
    "conditional_normative": ("temporal",),
    "deontic": ("conditional_normative",),
    "frame": ("conditional_normative", "deontic", "frame", "temporal"),
    "temporal": ("deontic",),
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
        "as_defined_in",
        "as_described_in",
        "as_otherwise_provided_in",
        "as_provided_in",
        "as_set_forth_in",
        "as_otherwise_provided_in",
        "except_as_otherwise_provided",
        "except_as_provided_in",
        "except_as",
        "except_that",
        "except_to_the_extent",
        "except",
        "unless",
        "in_accordance_with",
        "may",
        "allowed",
        "permitted",
        "may_not",
        "must",
        "pursuant_to",
        "defined_in",
        "described_in",
        "referred_to_in",
        "must_not",
        "shall",
        "shall_not",
        "obligation",
        "obligated",
        "obligatory",
        "required",
        "require",
        "requires",
        "requiring",
        "authorized",
        "prohibited",
        "forbidden",
        "is_entitled_to",
        "shall_be_entitled_to",
        "has_a_duty_to",
        "have_a_duty_to",
        "under_an_obligation_to",
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
_DEONTIC_ALETHIC_BRIDGE_CUES: frozenset[str] = frozenset(
    {
        "authorized",
        "can_be",
        "may",
        "may_be",
        "permitted",
        "possible",
        "possibly",
    }
)
_CLAUSE_PREFIX_BRIDGE_CUES: frozenset[str] = frozenset(
    prefix_key
    for _, prefix_key in (*_CONDITION_PREFIXES, *_EXCEPTION_PREFIXES)
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
        "within",
        "not_later_than",
        "no_later_than",
        "deadline",
        "effective_date",
        "fiscal_year",
        "calendar_year",
    }
)
_STATUTORY_SCOPE_BRIDGE_CUES: frozenset[str] = frozenset(
    {
        "under",
        "subject_to",
        "subject_only_to",
        "subject_however_to",
        "subject_to_section",
        "subject_to_subsection",
        "subject_to_paragraph",
        "subject_to_subparagraph",
        "subject_to_chapter",
        "subject_to_subchapter",
        "subject_to_title",
        "subject_to_the_terms_and_conditions",
        "subject_to_such_terms_and_conditions",
        "subject_to_terms_and_conditions",
        "as_defined_in",
        "as_described_in",
        "as_otherwise_provided_in",
        "as_provided_in",
        "as_set_forth_in",
        "defined_in",
        "described_in",
        "referred_to_in",
        "pursuant_to",
    }
)
_STATUS_KEYWORD_BRIDGE_OPERATOR_PAIRS: Mapping[str, tuple[tuple[str, str], ...]] = {
    "codification": (
        ("frame", "Frame"),
        ("epistemic", "K"),
    ),
    "omitted": (
        ("frame", "Frame"),
        ("epistemic", "K"),
    ),
    "reclassified": (
        ("frame", "Frame"),
        ("epistemic", "K"),
        ("dynamic", "[a]"),
    ),
    "renumbered": (
        ("frame", "Frame"),
        ("epistemic", "K"),
        ("dynamic", "[a]"),
    ),
    "repealed": (
        ("frame", "Frame"),
        ("epistemic", "K"),
    ),
    "reserved": (
        ("frame", "Frame"),
        ("epistemic", "K"),
    ),
    "terminated": (
        ("frame", "Frame"),
        ("epistemic", "K"),
        ("temporal", "F"),
    ),
    "transferred": (
        ("frame", "Frame"),
        ("epistemic", "K"),
        ("dynamic", "[a]"),
    ),
    "vacant": (
        ("frame", "Frame"),
        ("epistemic", "K"),
    ),
}
_FRAME_TEMPORAL_BRIDGE_CUES: frozenset[str] = frozenset(
    _STRUCTURAL_FRAME_CUE_TOKENS
    | {
        "code",
        "deadline",
        "effective_date",
        "fiscal_year",
        "calendar_year",
        "frame",
        "not_later_than",
        "no_later_than",
        "within",
    }
)
_TEMPORAL_ALETHIC_BRIDGE_CUE_OPERATOR_SYMBOLS: Mapping[str, str] = {
    "cannot": "□",
    "impossible": "□",
    "must_be": "□",
    "necessary": "□",
    "can_be": "◇",
    "possible": "◇",
}
_FRAME_REFINED_STATUS_DEONTIC_CUES: frozenset[str] = frozenset(
    {
        "reclassified",
        "transferred",
        "codification",
        "repealed",
        "omitted",
        "reserved",
        "vacant",
        "renumbered",
        "terminated",
    }
)
_TEMPORAL_BRIDGE_CONTEXT_TOKENS: frozenset[str] = frozenset(
    {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
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
_FRAME_STRUCTURAL_DEONTIC_BRIDGE_TRIGGER_RE = re.compile(
    r"(?<!\w)(?:shall|must|may|required|requires|obligation|obligatory|authorized)(?!\w)",
    re.IGNORECASE,
)
_REFINED_HEADING_BRIDGE_SOURCE_FAMILIES: frozenset[str] = frozenset(
    {
        "frame",
        "temporal",
    }
)
_TYPED_IR_REFINED_FAMILY_PAIR_TARGETS: Mapping[str, tuple[str, ...]] = {
    "conditional_normative": ("conditional_normative",),
    "deontic": ("deontic",),
    "frame": ("deontic", "frame"),
    "temporal": ("deontic", "temporal"),
}
_REFINED_HEADING_BRIDGE_CUE_OPERATOR_PAIRS: Mapping[
    str,
    tuple[tuple[str, str], ...],
] = {
    "annual_report": (("deontic", "O"),),
    "report": (("deontic", "O"),),
    "reports": (("deontic", "O"),),
    "notice": (("deontic", "O"),),
    "notices": (("deontic", "O"),),
    "records": (("deontic", "O"),),
    "recordkeeping": (("deontic", "O"),),
    "compliance": (("deontic", "O"),),
    "information_security": (("deontic", "O"), ("epistemic", "K")),
    "information": (("epistemic", "K"),),
    "finding": (("epistemic", "K"),),
    "findings": (("epistemic", "K"),),
}
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
        *_typed_ir_reconstruction_phrases(document, formula_order),
        *_source_span_slot_phrases(
            source_phrases,
            formulas=formula_order,
        ),
        *_document_span_metric_phrases(
            document=document,
            modal_span_coverage=modal_span_coverage,
        ),
        *_source_identifier_phrases(document),
        *_document_citation_phrases(document),
        *_document_provenance_summary_phrases(document),
        *_document_modal_family_count_phrases(document),
        *_document_modal_family_transition_phrases(document),
        *_document_semantic_slot_summary_phrases(document),
        *_frame_candidate_phrases(document),
        *_frame_ontology_phrases(document),
        *_compiler_guidance_phrases(document),
        *_legal_ir_view_prototype_phrases(document),
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
            _decode_formula_phrases(
                formula,
                document=document,
            )
        )
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
    document: ModalIRDocument | None = None,
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
    predicate_surface_text = _predicate_surface_text_rescue(
        formula=formula,
        predicate_text=predicate_text,
        document=document,
    )
    if predicate_surface_text is not None:
        surface_text, surface_source = predicate_surface_text
        phrases.append(
            DecodedModalPhrase(
                text=surface_text,
                slot="predicate_surface_text",
                spans=spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=surface_source,
                slot="predicate_surface_text_source",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            surface_text,
            slot_prefix="predicate_surface_text",
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
                slot_prefix="predicate_surface_text",
                spans=spans,
            )
        )
        phrases.extend(
            _content_scope_phrases(
                surface_text,
                slot_prefix="predicate_surface_text",
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
        phrases.append(
            DecodedModalPhrase(
                text=canonical_operator_label,
                slot="text_cue",
                spans=operator_spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=f"{canonical_operator_label}:{formula.operator.family}",
                slot="text_cue_family",
                spans=operator_spans,
                provenance_only=True,
            )
        )
    predicate_head = _predicate_head_anchor(formula)
    if predicate_head:
        phrases.append(
            DecodedModalPhrase(
                text=predicate_head,
                slot="predicate_head",
                spans=spans,
                provenance_only=True,
            )
        )
        phrases.append(
            DecodedModalPhrase(
                text=f"{formula.operator.family}:{predicate_head}",
                slot="predicate_head_family",
                spans=spans,
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
    condition_values = _resolved_formula_conditions(
        document=document,
        formula=formula,
    )
    exception_values = _resolved_formula_exceptions(
        document=document,
        formula=formula,
    )
    for bridge_cue in _formula_bridge_cues(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
    ):
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
    for transition_slot, transition_value in _modal_transition_slots(formula):
        phrases.append(
            DecodedModalPhrase(
                text=transition_value,
                slot=transition_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    for polarity_slot, polarity_value in _modal_polarity_slots(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=polarity_value,
                slot=polarity_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    for refined_slot, refined_value in _typed_ir_refined_family_pair_slots(formula):
        phrases.append(
            DecodedModalPhrase(
                text=refined_value,
                slot=refined_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    phrases.extend(
        _typed_decompiler_bridge_phrases(
            document=document,
            formula=formula,
            condition_values=condition_values,
            exception_values=exception_values,
            spans=spans,
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
        for slot, value in _typed_argument_slots(argument):
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
    predicate_role = _clean_text(formula.predicate.role).lower()
    predicate_family = _clean_text(formula.operator.family).lower()
    argument_arity = len(argument_values)
    phrases.append(
        DecodedModalPhrase(
            text=str(argument_arity),
            slot="predicate_argument_arity",
            spans=spans,
            provenance_only=True,
        )
    )
    if predicate_role:
        role_arity_signature = f"{predicate_role}:{argument_arity}"
        phrases.append(
            DecodedModalPhrase(
                text=role_arity_signature,
                slot="predicate_role_arity",
                spans=spans,
                provenance_only=True,
            )
        )
        if predicate_family:
            family_role_arity_signature = (
                f"{predicate_family}:{predicate_role}:{argument_arity}"
            )
            phrases.append(
                DecodedModalPhrase(
                    text=family_role_arity_signature,
                    slot="predicate_role_family_arity",
                    spans=spans,
                    provenance_only=True,
                )
            )
    semantic_span_text = _semantic_source_span_text(
        document=document,
        formula=formula,
    )
    if semantic_span_text:
        phrases.append(
            DecodedModalPhrase(
                text=semantic_span_text,
                slot="source_semantic_span",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            semantic_span_text,
            slot_prefix="source_semantic_span",
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
            semantic_span_text,
            spans=spans,
            emitted=statutory_scope_emissions,
        )
        phrases.extend(
            _contextual_modal_cue_phrases(
                formula=formula,
                text=semantic_span_text,
                slot_prefix="source_semantic_span",
                spans=spans,
            )
        )
    phrases.extend(
        _source_role_anchor_phrases(
            document=document,
            formula=formula,
            spans=spans,
        )
    )
    semantic_source_span = _semantic_source_span_text(
        document=document,
        formula=formula,
    )
    if semantic_source_span:
        phrases.append(
            DecodedModalPhrase(
                text=semantic_source_span,
                slot="modal_source_span",
                spans=spans,
                provenance_only=True,
            )
        )
        for typed_slot, typed_value in _typed_identifier_slots(
            semantic_source_span,
            slot_prefix="modal_source_span",
        ):
            if typed_slot in {
                "modal_source_span_token_count",
                "modal_source_span_token_prefix",
                "modal_source_span_token_suffix",
                "modal_source_span_stem",
            }:
                continue
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
                text=semantic_source_span,
                slot_prefix="modal_source_span",
                spans=spans,
            )
        )
    semantic_source_context_span = _semantic_source_context_span_text(
        document=document,
        formula=formula,
        source_span_text=semantic_source_span,
    )
    if semantic_source_context_span:
        phrases.append(
            DecodedModalPhrase(
                text=semantic_source_context_span,
                slot="source_context_span",
                spans=spans,
                provenance_only=True,
            )
        )
        for typed_slot, typed_value in _typed_identifier_slots(
            semantic_source_context_span,
            slot_prefix="source_context_span",
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
                text=semantic_source_context_span,
                slot_prefix="source_context_span",
                spans=spans,
            )
        )
    condition_values = _resolved_formula_conditions(
        document=document,
        formula=formula,
    )
    exception_values = _resolved_formula_exceptions(
        document=document,
        formula=formula,
    )
    proxy_condition_from_exception = not condition_values and bool(exception_values)
    for condition_index, condition in enumerate(condition_values):
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
                clause_index=condition_index,
            )
        )
        phrases.extend(
            _refined_clause_bridge_phrases(
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
    for exception_index, exception in enumerate(exception_values):
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
                clause_index=exception_index,
            )
        )
        phrases.extend(
            _refined_clause_bridge_phrases(
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
        for slot, value in _status_keyword_modal_slots(
            formula,
            status_keyword=status_keyword,
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
        _legal_semantic_atom_phrases(
            text=heading_tail,
            slot_prefix="section_heading_tail",
            spans=spans,
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
    span_text = _semantic_source_span_text(document=document, formula=formula)
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
            clause = _strip_uscode_gpo_attribution_fragment(clause)
            clause = _TRAILING_SECTION_PUNCT_RE.sub("", _clean_text(clause))
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


def _resolved_formula_conditions(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[str]:
    explicit_conditions = _phrase_values(formula.conditions)
    if explicit_conditions:
        return explicit_conditions
    metadata_conditions = _resolved_clause_values_from_metadata(
        formula,
        clause_type="condition",
    )
    if metadata_conditions:
        return metadata_conditions
    inferred_conditions = _inferred_condition_values_from_source_span(
        document=document,
        formula=formula,
    )
    return _phrase_values([*explicit_conditions, *inferred_conditions])


def _resolved_formula_exceptions(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[str]:
    explicit_exceptions = _phrase_values(formula.exceptions)
    if explicit_exceptions:
        return explicit_exceptions
    metadata_exceptions = _resolved_clause_values_from_metadata(
        formula,
        clause_type="exception",
    )
    if metadata_exceptions:
        return metadata_exceptions
    inferred_exceptions = _inferred_exception_values_from_source_span(
        document=document,
        formula=formula,
    )
    return _phrase_values([*explicit_exceptions, *inferred_exceptions])


def _resolved_clause_values_from_metadata(
    formula: ModalIRFormula,
    *,
    clause_type: str,
) -> List[str]:
    metadata = formula.metadata if isinstance(formula.metadata, Mapping) else {}
    slot = "condition" if clause_type == "condition" else "exception"
    scope_key = f"{slot}_scope"
    prefix_key_slot = f"{slot}_prefix_key"
    scoped_prefix = ""
    scoped_value = ""
    collected: List[str] = []

    def _append_values(raw_value: Any) -> None:
        if isinstance(raw_value, (list, tuple, set, frozenset)):
            for item in raw_value:
                _append_values(item)
            return
        cleaned = _clean_text(raw_value)
        if cleaned:
            collected.append(cleaned)

    for key, value in metadata.items():
        key_text = _clean_text(key).lower()
        if not key_text:
            continue
        if key_text in {slot, f"{slot}s"}:
            _append_values(value)
            continue
        if key_text == scope_key:
            scoped_value = _clean_text(value)
            continue
        if key_text == prefix_key_slot:
            scoped_prefix = _clean_text(value).lower()
            continue
        if key_text.startswith(f"{slot}_") and key_text not in {
            prefix_key_slot,
            scope_key,
            f"{slot}_prefix",
            f"{slot}_prefix_family",
            f"{slot}_prefix_temporal_relation",
        }:
            suffix = key_text[len(f"{slot}_") :]
            if suffix and not scoped_prefix:
                scoped_prefix = suffix
            _append_values(value)
    if scoped_prefix and scoped_value:
        collected.append(f"{scoped_prefix.replace('_', ' ')} {scoped_value}")

    resolved: List[str] = []
    for value in _unique_preserve_order(collected):
        parsed = _typed_clause_slot(value, slot=slot)
        if parsed is not None:
            resolved.append(value)
            continue
        if scoped_prefix:
            prefix_text = scoped_prefix.replace("_", " ").strip()
            value_text = _clean_text(value)
            if not prefix_text or value_text.lower().startswith(prefix_text.lower()):
                continue
            prefixed = f"{prefix_text} {value_text}".strip()
            parsed = _typed_clause_slot(prefixed, slot=slot)
            if parsed is not None and parsed[2]:
                resolved.append(prefixed)
    return _unique_preserve_order(resolved)


def _inferred_exception_values_from_source_span(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_candidates: int = 2,
    max_tokens: int = 40,
) -> List[str]:
    span_text = _formula_source_span_text(document=document, formula=formula)
    if not span_text:
        return []
    cue_key = _clean_text(formula.metadata.get("cue") or "").lower().replace(" ", "_")
    ordered_prefixes = sorted(
        _EXCEPTION_PREFIXES,
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
            parsed_clause = _typed_clause_slot(clause, slot="exception")
            if parsed_clause is None:
                continue
            _, parsed_prefix_key, _ = parsed_clause
            if parsed_prefix_key != prefix_key:
                continue
            parsed_condition_clause = _typed_clause_slot(clause, slot="condition")
            if (
                parsed_condition_clause is not None
                and parsed_condition_clause[1] == parsed_prefix_key
                and not parsed_prefix_key.startswith("except")
                and parsed_prefix_key != "unless"
            ):
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


def _semantic_source_span_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> str:
    span_text = _formula_source_span_text(document=document, formula=formula)
    if not span_text:
        return ""
    normalized = _clean_text(_USCODE_LEADING_SECTION_REF_RE.sub("", span_text))
    normalized = _strip_uscode_gpo_attribution_fragment(normalized)
    normalized = _TRAILING_SECTION_PUNCT_RE.sub("", normalized)
    normalized = _trim_uscode_compilation_surface_text(normalized, max_tokens=80)
    normalized = _clean_text(normalized)
    if normalized and not _is_low_information_section_marker(normalized):
        return normalized
    return span_text


def _semantic_source_context_span_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    source_span_text: str,
    max_tokens: int = 36,
    context_char_window: int = 200,
) -> str:
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    source_length = len(source_text)
    start = max(0, min(source_length, int(formula.provenance.start_char)))
    end = max(start, min(source_length, int(formula.provenance.end_char)))
    around_text = _clean_text(
        source_text[max(0, start - context_char_window) : min(source_length, end + context_char_window)]
    )
    if not around_text:
        return ""
    cleaned = _clean_text(_USCODE_LEADING_SECTION_REF_RE.sub("", around_text))
    cleaned = _strip_uscode_gpo_attribution_fragment(cleaned)
    cleaned = _TRAILING_SECTION_PUNCT_RE.sub("", cleaned)
    cleaned = _trim_uscode_compilation_surface_text(cleaned, max_tokens=max_tokens)
    cleaned = _clean_text(cleaned)
    if not cleaned:
        return ""
    span_text = _clean_text(source_span_text)
    selected_from_span = False
    if span_text:
        cleaned_cues = _bridge_cues_from_text(cleaned)
        span_cues = _bridge_cues_from_text(span_text)
        if len(span_cues) > len(cleaned_cues):
            cleaned = span_text
            selected_from_span = True
    if source_span_text and cleaned.lower() == source_span_text.lower() and not selected_from_span:
        return ""
    if len(_tokenize_for_similarity(cleaned)) > max_tokens:
        return ""
    return cleaned


def _is_probable_uscode_compilation_span(text: str) -> bool:
    normalized = _clean_text(text).lower()
    if not normalized:
        return False
    if any(
        marker in normalized
        for marker in (
            "united states code",
            "u.s.c.",
            "u s c",
            "www.gpo.gov",
            "government publishing office",
        )
    ):
        return True
    tokens = _CUE_TOKEN_RE.findall(normalized)
    if len(tokens) < 12:
        return False
    scaffolding_tokens = {
        "title",
        "chapter",
        "subchapter",
        "section",
        "sec",
        "subtitle",
        "part",
        "subsection",
        "article",
        "division",
        "code",
        "edition",
    }
    scaffold_count = sum(token in scaffolding_tokens for token in tokens)
    return scaffold_count >= 3


def _strip_uscode_gpo_attribution_fragment(text: str) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    stripped = _clean_text(_USCODE_GPO_ATTRIBUTION_RE.sub("", normalized))
    if stripped != normalized:
        return stripped
    return _clean_text(_USCODE_GPO_ATTRIBUTION_FRAGMENT_RE.sub("", normalized))


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
        _legal_semantic_atom_phrases(
            text=surface_text,
            slot_prefix="fallback_surface_text",
            spans=spans,
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
    context_text = _fallback_surface_context_text(
        document=document,
        formula=formula,
        surface_text=surface_text,
    )
    if context_text:
        phrases.append(
            DecodedModalPhrase(
                text=context_text,
                slot="fallback_surface_context",
                spans=spans,
                provenance_only=True,
            )
        )
        for slot, value in _typed_identifier_slots(
            context_text,
            slot_prefix="fallback_surface_context",
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
            _legal_semantic_atom_phrases(
                text=context_text,
                slot_prefix="fallback_surface_context",
                spans=spans,
            )
        )
        phrases.extend(
            _contextual_modal_cue_phrases(
                formula=formula,
                text=context_text,
                slot_prefix="fallback_surface_context",
                spans=spans,
            )
        )
    return phrases


def _legal_semantic_atom_phrases(
    *,
    text: str,
    slot_prefix: str,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    prefix = _clean_text(slot_prefix).replace(" ", "_")
    slots = ["legal_semantic_atom"]
    if prefix:
        slots.append(f"{prefix}_legal_semantic_atom")
    for atom in _legal_semantic_atoms_from_text(text):
        for slot in slots:
            phrases.append(
                DecodedModalPhrase(
                    text=atom,
                    slot=slot,
                    spans=spans,
                    provenance_only=True,
                )
            )
    return phrases


def _legal_semantic_atoms_from_text(text: str) -> List[str]:
    normalized = _clean_text(text).lower()
    if not normalized:
        return []
    tokens = set(_CUE_TOKEN_RE.findall(normalized))
    atoms: List[str] = []
    seen: set[str] = set()
    for phrase, atom in _LEGAL_SEMANTIC_ATOM_PHRASES:
        phrase_tokens = _CUE_TOKEN_RE.findall(phrase)
        if phrase in normalized or (
            phrase_tokens and all(token in tokens for token in phrase_tokens)
        ):
            if atom not in seen:
                seen.add(atom)
                atoms.append(atom)
    return atoms


def _fallback_surface_context_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    surface_text: str,
    max_tokens: int = 24,
    right_context_char_window: int = 360,
    local_context_char_window: int = 180,
) -> str:
    source_text = str(document.normalized_text or "")
    if not source_text:
        return ""
    surface_value = _clean_text(surface_text).lower()
    if not surface_value:
        return ""
    source_length = len(source_text)
    start = max(0, min(source_length, int(formula.provenance.start_char)))
    end = max(start, min(source_length, int(formula.provenance.end_char)))
    right_context = _clean_text(source_text[end : min(source_length, end + right_context_char_window)])
    local_context = _clean_text(
        source_text[max(0, start - local_context_char_window) : min(
            source_length,
            end + local_context_char_window,
        )]
    )
    for raw_context in (right_context, local_context):
        if not raw_context:
            continue
        for segment in _SECTION_HEADING_TAIL_SPLIT_RE.split(raw_context):
            candidate = _clean_text(segment)
            if not candidate:
                continue
            candidate = _clean_text(_USCODE_LEADING_SECTION_REF_RE.sub("", candidate))
            candidate = candidate.lstrip(" \t\r\n-–—:;,.")
            candidate = _TRAILING_SECTION_PUNCT_RE.sub("", candidate)
            candidate = _trim_uscode_compilation_surface_text(
                candidate,
                max_tokens=max_tokens,
            )
            candidate = _clean_text(candidate)
            if (
                not candidate
                or candidate.lower() == surface_value
                or candidate.lower().startswith(surface_value)
            ):
                continue
            if len(_tokenize_for_similarity(candidate)) > max_tokens:
                continue
            if not _contextual_modal_cues_from_text(formula, text=candidate):
                continue
            return candidate
    return ""


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
    heading_tail = _strip_uscode_gpo_attribution_fragment(heading_tail)
    heading_tail = _TRAILING_SECTION_PUNCT_RE.sub("", heading_tail)
    if not heading_tail:
        return ""
    if _is_low_information_section_marker(heading_tail):
        return ""
    lower_heading_tail = heading_tail.lower()
    if (
        lower_heading_tail.startswith("u.s.c. title")
        or lower_heading_tail.startswith("usc title")
        or "united states code" in lower_heading_tail
    ):
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
    normalized = _strip_uscode_gpo_attribution_fragment(normalized)
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


def _document_provenance_summary_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    provenance_maps = _document_provenance_slot_maps(document)
    if not provenance_maps:
        return []

    families = _document_provenance_families(document)
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str]] = set()

    def add(slot: str, value: str) -> None:
        normalized_slot = _clean_text(slot)
        normalized_value = _clean_text(value)
        marker = (normalized_slot, normalized_value)
        if not normalized_slot or not normalized_value or marker in seen:
            return
        seen.add(marker)
        phrases.append(
            DecodedModalPhrase(
                text=normalized_value,
                slot=normalized_slot,
                provenance_only=True,
            )
        )

    for slot_map in provenance_maps:
        title = _clean_text(
            slot_map.get("source_id_title")
            or slot_map.get("citation_title")
            or ""
        )
        section = _clean_text(
            slot_map.get("source_id_section_normalized")
            or slot_map.get("source_id_section")
            or slot_map.get("citation_section_normalized")
            or slot_map.get("citation_section")
            or ""
        )
        title_section_key = _clean_text(
            slot_map.get("source_id_title_section_key_normalized")
            or slot_map.get("source_id_title_section_key")
            or slot_map.get("citation_title_section_key_normalized")
            or slot_map.get("citation_title_section_key")
            or ""
        )
        canonical = _clean_text(
            slot_map.get("source_id_citation_canonical")
            or slot_map.get("citation_canonical")
            or ""
        )
        section_style = _clean_text(
            slot_map.get("source_id_section_style_canonical")
            or slot_map.get("source_id_section_style")
            or slot_map.get("citation_section_style_canonical")
            or slot_map.get("citation_section_style")
            or ""
        )
        if title:
            add("semantic_provenance_title", title)
        if section:
            add("semantic_provenance_section", section)
        if title_section_key:
            add("semantic_provenance_title_section_key", title_section_key)
            for slot, value in _typed_identifier_slots(
                title_section_key.replace(":", "_"),
                slot_prefix="semantic_provenance_title_section_key",
            ):
                add(slot, value)
        if canonical:
            add("semantic_provenance_citation", canonical)
        if section_style:
            add("semantic_provenance_section_style", section_style)

        coordinate = title_section_key or (
            _title_section_coordinate(title, section) if title and section else ""
        )
        if not coordinate:
            continue
        normalized_coordinate = coordinate.lower()
        for family in families:
            add(
                "semantic_provenance_family_title_section_key",
                f"{family}:{normalized_coordinate}",
            )
            if section_style:
                add(
                    "semantic_provenance_family_section_style",
                    f"{family}:{section_style}",
                )

    return phrases


def _document_provenance_slot_maps(
    document: ModalIRDocument,
) -> List[Dict[str, str]]:
    slot_maps: List[Dict[str, str]] = []
    seen_keys: set[Tuple[str, str]] = set()

    def add_slots(slots: Sequence[Tuple[str, str]]) -> None:
        slot_map = _slot_value_map(slots)
        key = (
            _clean_text(
                slot_map.get("source_id_title_section_key_normalized")
                or slot_map.get("source_id_title_section_key")
                or slot_map.get("citation_title_section_key_normalized")
                or slot_map.get("citation_title_section_key")
                or ""
            ).lower(),
            _clean_text(
                slot_map.get("source_id_citation_canonical")
                or slot_map.get("citation_canonical")
                or ""
            ).lower(),
        )
        if not any(key) or key in seen_keys:
            return
        seen_keys.add(key)
        slot_maps.append(slot_map)

    for source_id in _document_source_ids(document):
        add_slots(_source_id_slots(source_id))
    citation = _clean_text(document.metadata.get("citation") or "")
    if citation:
        add_slots(_citation_slots(citation))
    for formula in document.formulas:
        formula_citation = _clean_text(formula.provenance.citation or "")
        if formula_citation:
            add_slots(_citation_slots(formula_citation))
    if not citation and not document.formulas:
        for inferred_citation in _inferred_citations_from_source_ids(
            _document_source_ids(document)
        ):
            add_slots(_citation_slots(inferred_citation))
    return slot_maps


def _document_provenance_families(document: ModalIRDocument) -> List[str]:
    families: List[str] = []
    for formula in document.formulas:
        family = _slot_safe_family_key(_clean_text(formula.operator.family).lower())
        if family and family not in families:
            families.append(family)
    if not families:
        families.append("no_formula")
    return families


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


def _document_modal_family_transition_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    for slot, value in _modal_family_transition_slots(
        document.formulas,
        document=document,
    ):
        phrases.append(
            DecodedModalPhrase(
                text=value,
                slot=slot,
                provenance_only=True,
            )
        )
    return phrases


def _document_semantic_slot_summary_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    slots: List[Tuple[str, str]] = [
        ("semantic_formula_count_bucket", _semantic_count_bucket(len(document.formulas))),
    ]
    if not document.formulas:
        slots.append(("semantic_no_modal_formula", "true"))

    frame_logic = document.frame_logic
    if frame_logic is not None:
        ontology_name = _slot_safe_family_key(
            _clean_text(getattr(frame_logic, "ontology_name", ""))
        )
        if ontology_name:
            slots.append(("semantic_frame_logic_ontology", ontology_name))
        triples = list(getattr(frame_logic, "triples", []) or [])
        slots.append(
            ("semantic_frame_logic_triple_count_bucket", _semantic_count_bucket(len(triples)))
        )
        for triple in triples[:8]:
            predicate = _slot_safe_family_key(
                _clean_text(
                    triple.get("predicate", "")
                    if isinstance(triple, Mapping)
                    else getattr(triple, "predicate", "")
                )
            )
            if predicate:
                slots.append(("semantic_frame_logic_predicate", predicate))

    for formula in document.formulas:
        family = _slot_safe_family_key(_clean_text(formula.operator.family).lower())
        system = _slot_safe_family_key(_clean_text(formula.operator.system).lower())
        symbol = _slot_safe_family_key(_clean_text(formula.operator.symbol))
        label = _slot_safe_family_key(_clean_text(formula.operator.label).lower())
        predicate_role = _slot_safe_family_key(
            _clean_text(formula.predicate.role or "none").lower()
        )
        predicate_name = _slot_safe_family_key(_clean_text(formula.predicate.name).lower())
        predicate_tokens = [token for token in predicate_name.split("_") if token]
        arguments = list(formula.predicate.arguments or [])
        conditions = _resolved_formula_conditions(document=document, formula=formula)
        exceptions = _resolved_formula_exceptions(document=document, formula=formula)

        if family:
            slots.append(("semantic_modal_family", family))
        if family and system and symbol:
            slots.append(("semantic_modal_operator", f"{family}:{system}:{symbol}"))
        if family and label:
            slots.append(("semantic_operator_label", f"{family}:{label}"))
        if predicate_role:
            slots.append(("semantic_predicate_role", predicate_role))
            if family:
                slots.append(("semantic_family_role", f"{family}:{predicate_role}"))
        if predicate_tokens:
            slots.append(("semantic_predicate_head", predicate_tokens[0]))
        slots.append(
            (
                "semantic_predicate_token_count_bucket",
                _semantic_count_bucket(len(predicate_tokens)),
            )
        )
        slots.append(
            ("semantic_predicate_arity_bucket", _semantic_count_bucket(len(arguments)))
        )
        slots.append(
            ("semantic_condition_count_bucket", _semantic_count_bucket(len(conditions)))
        )
        slots.append(
            ("semantic_exception_count_bucket", _semantic_count_bucket(len(exceptions)))
        )
        condition_present = "true" if conditions else "false"
        exception_present = "true" if exceptions else "false"
        slots.append(("semantic_condition_present", condition_present))
        slots.append(("semantic_exception_present", exception_present))
        if family and conditions:
            slots.append(("semantic_family_condition_present", family))
        if family and exceptions:
            slots.append(("semantic_family_exception_present", family))
        for cue in _formula_cues(formula):
            cue_name = _slot_safe_family_key(_clean_text(cue).lower())
            if not cue_name:
                continue
            slots.append(("semantic_modal_cue", cue_name))
            if family:
                slots.append(("semantic_cue_family", f"{cue_name}:{family}"))

    return [
        DecodedModalPhrase(
            text=value,
            slot=slot,
            provenance_only=True,
        )
        for slot, value in _unique_slot_values(slots)
    ]


def _semantic_count_bucket(value: int) -> str:
    count = max(0, int(value))
    if count <= 1:
        return str(count)
    if count <= 3:
        return "2_3"
    if count <= 7:
        return "4_7"
    if count <= 15:
        return "8_15"
    if count <= 31:
        return "16_31"
    return "32_plus"


def _compiler_guidance_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    """Expose learned autoencoder guidance as decompiler semantic slots."""
    metadata = document.metadata if isinstance(document.metadata, Mapping) else {}
    if not metadata.get("compiler_guidance_applied"):
        return []
    phrases: List[DecodedModalPhrase] = [
        DecodedModalPhrase(
            text="true",
            slot="compiler_guidance_applied",
            provenance_only=True,
        )
    ]

    def add(slot: str, value: Any) -> None:
        text = _clean_text(str(value or ""))
        if not text:
            return
        phrases.append(
            DecodedModalPhrase(
                text=text,
                slot=slot,
                provenance_only=True,
            )
        )

    def add_distribution(prefix: str, raw_distribution: Any) -> None:
        if not isinstance(raw_distribution, Mapping):
            return
        ranked = sorted(
            (
                (_clean_text(str(name)), _safe_float(weight))
                for name, weight in raw_distribution.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )
        for rank, (name, weight) in enumerate(ranked[:8], start=1):
            if not name or weight <= 0.0:
                continue
            safe_name = _slot_safe_family_key(name)
            if not safe_name:
                continue
            add(prefix, safe_name)
            add(f"{prefix}_ranked", f"{rank}:{safe_name}")
            add(f"{prefix}_weight_bucket", _guidance_weight_bucket(weight))

    def add_signed_distribution(prefix: str, raw_distribution: Any) -> None:
        if not isinstance(raw_distribution, Mapping):
            return
        ranked = sorted(
            (
                (_clean_text(str(name)), _safe_float(weight))
                for name, weight in raw_distribution.items()
            ),
            key=lambda item: (-abs(item[1]), item[0]),
        )
        for rank, (name, weight) in enumerate(ranked[:8], start=1):
            if not name or abs(weight) <= 1.0e-12:
                continue
            safe_name = _slot_safe_family_key(name)
            if not safe_name:
                continue
            direction = "underrepresented" if weight > 0.0 else "overrepresented"
            add(prefix, safe_name)
            add(f"{prefix}_direction", f"{safe_name}:{direction}")
            add(f"{prefix}_ranked", f"{rank}:{direction}:{safe_name}")
            add(f"{prefix}_weight_bucket", _guidance_weight_bucket(abs(weight)))

    add_distribution(
        "compiler_guidance_family",
        metadata.get("compiler_guidance_family_distribution"),
    )
    add_distribution(
        "compiler_guidance_legal_ir_predicted_view",
        metadata.get("compiler_guidance_legal_ir_predicted_view_distribution"),
    )
    add_distribution(
        "compiler_guidance_legal_ir_target_view",
        metadata.get("compiler_guidance_legal_ir_target_view_distribution"),
    )
    add_signed_distribution(
        "compiler_guidance_legal_ir_view_gap",
        metadata.get("compiler_guidance_legal_ir_view_gap_distribution"),
    )
    raw_view_gaps = metadata.get("compiler_guidance_legal_ir_view_gap_distribution")
    if isinstance(raw_view_gaps, Mapping):
        underrepresented_views = sorted(
            (
                (_clean_text(str(name)), _safe_float(weight))
                for name, weight in raw_view_gaps.items()
            ),
            key=lambda item: (-item[1], item[0]),
        )
        for rank, (name, weight) in enumerate(underrepresented_views[:8], start=1):
            if not name or weight <= 0.0:
                continue
            safe_name = _slot_safe_family_key(name)
            if not safe_name:
                continue
            add("compiler_guidance_legal_ir_underrepresented_view", safe_name)
            add(
                "compiler_guidance_legal_ir_underrepresented_view_ranked",
                f"{rank}:{safe_name}",
            )

    feature_groups = metadata.get("compiler_guidance_feature_groups")
    if isinstance(feature_groups, Mapping):
        for group_name, features in sorted(feature_groups.items()):
            safe_group = _slot_safe_family_key(str(group_name))
            if not safe_group:
                continue
            add("compiler_guidance_feature_group", safe_group)
            if isinstance(features, Sequence) and not isinstance(features, (str, bytes)):
                for index, feature in enumerate(features[:8], start=1):
                    feature_text = _clean_text(str(feature or ""))
                    if not feature_text:
                        continue
                    add(
                        f"compiler_guidance_{safe_group}_feature",
                        feature_text,
                    )
                    add(
                        f"compiler_guidance_{safe_group}_feature_ranked",
                        f"{index}:{_slot_safe_family_key(feature_text)}",
                    )

    ranked_features = metadata.get("compiler_guidance_ranked_features")
    if isinstance(ranked_features, Sequence) and not isinstance(
        ranked_features,
        (str, bytes),
    ):
        for rank, item in enumerate(ranked_features[:16], start=1):
            if not isinstance(item, Mapping):
                continue
            feature = _clean_text(str(item.get("feature") or ""))
            if not feature:
                continue
            add("compiler_guidance_feature", feature)
            add(
                "compiler_guidance_feature_ranked",
                f"{rank}:{_slot_safe_family_key(feature)}",
            )
            route = _guidance_todo_route(feature)
            if route:
                add("compiler_guidance_todo_route", route)

    overlay_terms = metadata.get("compiler_guidance_semantic_overlay_terms")
    if isinstance(overlay_terms, Sequence) and not isinstance(
        overlay_terms,
        (str, bytes),
    ):
        for term in overlay_terms[:8]:
            add("refined_compiler_guidance_surface_term", term)

    before = _clean_text(
        str(metadata.get("compiler_guidance_selected_frame_before") or "")
    )
    after = _clean_text(
        str(metadata.get("compiler_guidance_selected_frame_after") or "")
    )
    if before:
        add("compiler_guidance_selected_frame_before", before)
    if after:
        add("compiler_guidance_selected_frame_after", after)
    if before or after:
        add(
            "compiler_guidance_frame_selection_changed",
            "true" if before and after and before != after else "false",
        )

    return phrases


def _safe_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _guidance_weight_bucket(value: float) -> str:
    if value >= 0.75:
        return "very_high"
    if value >= 0.5:
        return "high"
    if value >= 0.25:
        return "medium"
    if value > 0.0:
        return "low"
    return "zero"


def _guidance_todo_route(feature: str) -> str:
    normalized = _clean_text(feature).lower()
    marker = "todo-route:"
    if marker not in normalized:
        return ""
    suffix = normalized.split(marker, 1)[1]
    route = suffix.split(":", 1)[0]
    return _slot_safe_family_key(route)


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


def _legal_ir_view_prototype_phrases(
    document: ModalIRDocument,
) -> List[DecodedModalPhrase]:
    """Expose deterministic typed-IR anchors for LegalIR multiview bridges."""

    phrases: List[DecodedModalPhrase] = []
    selected_frame = _selected_frame(document)
    frame_logic = getattr(document, "frame_logic", None)
    has_frame_logic = bool(
        frame_logic
        and (
            getattr(frame_logic, "selected_frame", None)
            or getattr(frame_logic, "triples", None)
            or getattr(frame_logic, "ontology_name", None)
        )
    )
    for formula in document.formulas:
        spans = [[formula.provenance.start_char, formula.provenance.end_char]]
        family = _slot_safe_family_key(formula.operator.family)
        if not family:
            continue
        predicate_head = _predicate_head(formula.predicate.name)
        role = _slot_safe_family_key(formula.predicate.role or "")
        cues = _formula_cues(formula) or _formula_bridge_cues(formula)
        slot_values: List[Tuple[str, str]] = [
            ("family-role", f"{family}:{role or 'unspecified'}"),
            ("predicate-role", role or "unspecified"),
            ("predicate-head", predicate_head or "unspecified"),
            ("text-cue", family),
        ]
        if selected_frame:
            slot_values.append(("selected-frame", selected_frame))
        if has_frame_logic:
            ontology_name = _clean_text(getattr(frame_logic, "ontology_name", ""))
            if ontology_name:
                slot_values.append(("frame-logic-ontology", ontology_name))
            triples = list(getattr(frame_logic, "triples", ()) or ())
            if triples:
                slot_values.append(("frame-logic-triples", str(len(triples))))
        for cue in cues:
            cue_key = _normalized_bridge_cue_key(cue)
            if cue_key:
                slot_values.append(("modal-cue", cue_key))
        for slot_name, slot_value in _unique_slot_values(slot_values):
            phrases.append(
                DecodedModalPhrase(
                    text=slot_value,
                    slot=f"family_semantic_slot_prototype_{family}_{slot_name}",
                    spans=spans,
                    provenance_only=True,
                )
            )
            for view_name in _LEGAL_IR_VIEW_PROTOTYPES:
                view_key = view_name.replace(".", "_")
                phrases.append(
                    DecodedModalPhrase(
                        text=slot_value,
                        slot=(
                            "family_semantic_slot_legal_ir_view_prototype_"
                            f"{family}_{slot_name}_{view_key}"
                        ),
                        spans=spans,
                        provenance_only=True,
                    )
                )
    return phrases


def _predicate_head(predicate_name: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", _clean_text(predicate_name).lower())
        if token
    ]
    return tokens[0] if tokens else ""


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


def _modal_family_transition_slots(
    formulas: Sequence[ModalIRFormula],
    *,
    document: ModalIRDocument | None = None,
) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    for formula in formulas:
        family = _slot_safe_family_key(_clean_text(formula.operator.family).lower())
        symbol = _clean_text(formula.operator.symbol)
        if not family or not symbol:
            continue
        slots.extend(
            (
                ("modal_formula_family", family),
                ("modal_formula_operator", symbol),
                ("modal_formula_family_operator", f"{family}:{symbol}"),
                ("modal_formula_family_pair", f"{family}->{family}"),
                ("modal_formula_operator_pair", f"{symbol}->{symbol}"),
            )
        )
        for target_family in _DECOMPILER_REFINED_FAMILY_PAIR_TARGETS.get(family, ()):
            if target_family == family:
                continue
            slots.append(("modal_formula_family_pair", f"{family}->{target_family}"))
        # Include metadata-derived clause scopes (for example,
        # ``condition_prefix_key=subject_to`` + ``condition_scope=this section``)
        # so family transition slots preserve inferred deontic/conditional links
        # even when explicit condition/exception arrays are empty.
        if document is None:
            resolved_conditions = _resolved_clause_values_from_metadata(
                formula,
                clause_type="condition",
            )
            resolved_exceptions = _resolved_clause_values_from_metadata(
                formula,
                clause_type="exception",
            )
        else:
            resolved_conditions = _resolved_formula_conditions(
                document=document,
                formula=formula,
            )
            resolved_exceptions = _resolved_formula_exceptions(
                document=document,
                formula=formula,
            )
        cues: List[str] = []
        for cue_value in (
            *_formula_cues(formula),
            *_formula_bridge_cues(
                formula,
                condition_values=resolved_conditions,
                exception_values=resolved_exceptions,
            ),
        ):
            cue_key = _normalized_bridge_cue_key(cue_value)
            if cue_key and cue_key not in cues:
                cues.append(cue_key)
        for cue in cues:
            for bridge_family, bridge_symbol in _cue_bridge_operator_pairs(cue):
                normalized_bridge_family = _slot_safe_family_key(
                    _clean_text(bridge_family).lower()
                )
                normalized_bridge_symbol = _clean_text(bridge_symbol)
                if not normalized_bridge_family or not normalized_bridge_symbol:
                    continue
                family_pair = f"{family}->{normalized_bridge_family}"
                operator_pair = f"{symbol}->{normalized_bridge_symbol}"
                slots.extend(
                    (
                        ("modal_formula_family_pair", family_pair),
                        ("modal_formula_operator_pair", operator_pair),
                        (
                            "modal_formula_family_operator_bridge_signature",
                            f"{normalized_bridge_family}:{normalized_bridge_symbol}:{cue}",
                        ),
                        (
                            "modal_formula_family_pair_cue",
                            f"{family_pair}:{cue}",
                        ),
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


def _slot_safe_family_pair_key(value: str) -> str:
    normalized = _clean_text(value).lower()
    if not normalized:
        return ""
    if "->" in normalized:
        left_raw, right_raw = normalized.split("->", 1)
        left = _slot_safe_family_key(left_raw)
        right = _slot_safe_family_key(right_raw)
        if left and right:
            return f"{left}_{right}"
    return _slot_safe_family_key(normalized)


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


def _predicate_surface_text_rescue(
    *,
    formula: ModalIRFormula,
    predicate_text: str,
    document: ModalIRDocument | None,
) -> tuple[str, str] | None:
    if document is None or not _is_low_information_predicate_text(predicate_text):
        return None
    fallback_surface_text = _fallback_surface_text(
        document=document,
        formula=formula,
    )
    if (
        fallback_surface_text
        and fallback_surface_text.lower() != _clean_text(predicate_text).lower()
        and not _is_low_information_predicate_text(fallback_surface_text)
    ):
        return fallback_surface_text, "fallback_surface_text"
    modal_span_surface_text = _formula_source_span_surface_text(
        document=document,
        formula=formula,
    )
    if (
        modal_span_surface_text
        and modal_span_surface_text.lower() != _clean_text(predicate_text).lower()
        and not _is_low_information_predicate_text(modal_span_surface_text)
    ):
        return modal_span_surface_text, "modal_source_span"
    return None


def _formula_source_span_surface_text(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    max_tokens: int = 24,
) -> str:
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
    trimmed = _trim_uscode_compilation_surface_text(
        normalized,
        max_tokens=max_tokens,
    )
    candidate = trimmed or normalized
    if _is_low_information_section_marker(candidate):
        return ""
    tokens = _tokenize_for_similarity(candidate)
    if not tokens or len(tokens) > max_tokens:
        return ""
    return candidate


def _is_low_information_predicate_text(text: str) -> bool:
    normalized = _clean_text(text)
    if not normalized:
        return True
    segments: List[str] = []
    for token in re.split(r"[_\s]+", normalized.lower()):
        if not token:
            continue
        segments.extend(_alnum_segments(token))
    if not segments:
        return True
    return not any(
        len(segment) > 1 and any(character.isalpha() for character in segment)
        for segment in segments
    )


def _sentence_from_phrases(phrases: Sequence[DecodedModalPhrase]) -> str:
    words: List[str] = []
    for phrase in phrases:
        if phrase.fixed or phrase.provenance_only:
            continue
        if _clean_text(phrase.slot) == "typed_ir_reconstruction":
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


def _typed_ir_reconstruction_phrases(
    document: ModalIRDocument,
    formulas: Sequence[ModalIRFormula],
) -> List[DecodedModalPhrase]:
    """Render a semantic surface from typed IR slots, not copied spans."""

    phrases: List[DecodedModalPhrase] = []
    seen: set[str] = set()
    for formula in formulas:
        spans = [[formula.provenance.start_char, formula.provenance.end_char]]
        values: List[str] = []
        predicate_text = _predicate_phrase(formula)
        if predicate_text:
            values.append(predicate_text)
        values.extend(_phrase_values(formula.predicate.arguments))
        values.extend(
            _resolved_formula_conditions(
                document=document,
                formula=formula,
            )
        )
        values.extend(
            _resolved_formula_exceptions(
                document=document,
                formula=formula,
            )
        )
        anchors = _source_role_anchor_values(document=document, formula=formula)
        for role_name in (
            "subject",
            "action",
            "object",
            "condition",
            "exception",
            "temporal",
        ):
            anchor = _clean_text(anchors.get(role_name, ""))
            if anchor:
                values.append(anchor)
        rendered = _clean_text(" ".join(_unique_preserve_order(values)))
        if not rendered or rendered in seen:
            continue
        seen.add(rendered)
        phrases.append(
            DecodedModalPhrase(
                text=rendered,
                slot="typed_ir_reconstruction",
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


def _source_span_slot_phrases(
    source_phrases: Sequence[DecodedModalPhrase],
    *,
    formulas: Sequence[ModalIRFormula] = (),
) -> List[DecodedModalPhrase]:
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str, Tuple[Tuple[int, int], ...]]] = set()
    aggregate_text_by_slot: Dict[str, List[str]] = {
        "modal_source_span": [],
        "source_context_span": [],
        "modal_source_span_semantic": [],
        "source_context_span_semantic": [],
    }
    aggregate_spans_by_slot: Dict[str, List[List[int]]] = {
        "modal_source_span": [],
        "source_context_span": [],
        "modal_source_span_semantic": [],
        "source_context_span_semantic": [],
    }
    for source_phrase in source_phrases:
        slot_prefix = _clean_text(source_phrase.slot)
        text = _clean_text(source_phrase.text)
        if slot_prefix not in {"modal_source_span", "source_context_span"} or not text:
            continue
        aggregate_text_by_slot[slot_prefix].append(text)
        aggregate_spans_by_slot[slot_prefix].extend(
            [
                [int(span[0]), int(span[1])]
                for span in source_phrase.spans
                if (
                    isinstance(span, Sequence)
                    and len(span) == 2
                    and isinstance(span[0], int)
                    and isinstance(span[1], int)
                    and int(span[1]) > int(span[0])
                )
            ]
        )
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
        span_formula_signatures = _span_formula_modal_signatures(
            formulas,
            spans=spans,
        )
        contextual_formula_signatures = _nearest_formula_modal_signatures(
            formulas,
            spans=spans,
        )
        span_bridge_cues = _bridge_cues_from_text(text)
        for formula_cue in _span_formula_bridge_cues(formulas, spans=spans):
            if formula_cue and formula_cue not in span_bridge_cues:
                span_bridge_cues.append(formula_cue)
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
        semantic_text = _semantic_source_phrase_text(text)
        if semantic_text:
            semantic_slot_prefix = f"{slot_prefix}_semantic"
            aggregate_text_by_slot[semantic_slot_prefix].append(semantic_text)
            aggregate_spans_by_slot[semantic_slot_prefix].extend(
                [
                    [int(span[0]), int(span[1])]
                    for span in source_phrase.spans
                    if (
                        isinstance(span, Sequence)
                        and len(span) == 2
                        and isinstance(span[0], int)
                        and isinstance(span[1], int)
                        and int(span[1]) > int(span[0])
                    )
                ]
            )
            semantic_marker = (semantic_slot_prefix, semantic_text, span_marker)
            if semantic_marker not in seen:
                seen.add(semantic_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=semantic_text,
                        slot=semantic_slot_prefix,
                        spans=spans,
                        provenance_only=True,
                    )
                )
            for formula in formulas:
                for refined_slot, refined_value in _refined_contextual_modal_transition_slots(
                    formula,
                    text=semantic_text,
                    slot_prefix=semantic_slot_prefix,
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
            for slot, value in _typed_identifier_slots(
                semantic_text,
                slot_prefix=semantic_slot_prefix,
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
            for cue in _bridge_cues_from_text(semantic_text):
                semantic_cue_marker = (
                    f"{semantic_slot_prefix}_bridge_cue",
                    cue,
                    span_marker,
                )
                if semantic_cue_marker in seen:
                    continue
                seen.add(semantic_cue_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=cue,
                        slot=f"{semantic_slot_prefix}_bridge_cue",
                        spans=spans,
                        provenance_only=True,
                    )
                )
            for clause_slot, clause_value in _source_span_clause_prefix_slots(
                semantic_text,
                slot_prefix=semantic_slot_prefix,
            ):
                clause_marker = (clause_slot, clause_value, span_marker)
                if clause_marker in seen:
                    continue
                seen.add(clause_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=clause_value,
                        slot=clause_slot,
                        spans=spans,
                        provenance_only=True,
                    )
                )
        for cue in span_bridge_cues:
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
                distance_bucket,
            ) in contextual_formula_signatures:
                context_signature = f"{formula_signature}:{distance_bucket}"
                context_items: List[Tuple[str, str]] = [
                    (
                        f"{slot_prefix}_bridge_modal_context_formula_signature",
                        context_signature,
                    ),
                    (
                        f"{slot_prefix}_bridge_modal_context_formula_family",
                        formula_family,
                    ),
                    (
                        f"{slot_prefix}_bridge_modal_context_formula_operator",
                        formula_symbol,
                    ),
                    (
                        f"{slot_prefix}_bridge_modal_context_distance_bucket",
                        distance_bucket,
                    ),
                ]
                for context_slot, context_value in context_items:
                    context_marker = (context_slot, context_value, span_marker)
                    if context_marker in seen:
                        continue
                    seen.add(context_marker)
                    phrases.append(
                        DecodedModalPhrase(
                            text=context_value,
                            slot=context_slot,
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
                        f"{bridge_family}:{bridge_symbol}:{cue}:{distance_bucket}"
                    )
                    for transition_slot, transition_value in (
                        (
                            f"{slot_prefix}_bridge_modal_context_family_pair",
                            family_pair,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_context_operator_pair",
                            operator_pair,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_context_transition_signature",
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
            for (
                formula_family,
                formula_symbol,
                formula_signature,
            ) in span_formula_signatures:
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
                    operator_pair_key = _modal_operator_pair_feature_key(
                        formula_symbol,
                        bridge_symbol,
                    )
                    transition_signature = (
                        f"{formula_family}:{formula_symbol}->"
                        f"{bridge_family}:{bridge_symbol}:{cue}"
                    )
                    pair_cue = f"{family_pair}:{cue}"
                    family_pair_key = _slot_safe_family_pair_key(family_pair)
                    transition_items: List[Tuple[str, str]] = [
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
                    ]
                    transition_items.extend(
                        _modal_operator_transition_signature_slots(
                            source_family=formula_family,
                            source_system=_default_modal_system_key(formula_family),
                            source_symbol=formula_symbol,
                            target_family=bridge_family,
                            target_symbol=bridge_symbol,
                            slot_prefix=f"{slot_prefix}_bridge_modal",
                        )
                    )
                    if family_pair_key:
                        transition_items.append(
                            (
                                f"{slot_prefix}_bridge_modal_family_pair_key",
                                family_pair_key,
                            )
                        )
                    if operator_pair_key:
                        transition_items.append(
                            (
                                f"{slot_prefix}_bridge_modal_operator_pair_key",
                                operator_pair_key,
                            )
                        )
                    for transition_slot, transition_value in transition_items:
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
        for clause_slot, clause_value in _source_span_clause_prefix_slots(
            text,
            slot_prefix=slot_prefix,
        ):
            clause_marker = (clause_slot, clause_value, span_marker)
            if clause_marker in seen:
                continue
            seen.add(clause_marker)
            phrases.append(
                DecodedModalPhrase(
                    text=clause_value,
                    slot=clause_slot,
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
    # Emit aggregate slot evidence so typed source-span position features are
    # preserved across fragmented spans instead of resetting per fragment.
    for slot_prefix in (
        "modal_source_span",
        "source_context_span",
        "modal_source_span_semantic",
        "source_context_span_semantic",
    ):
        aggregate_text = _clean_text(" ".join(aggregate_text_by_slot.get(slot_prefix, ())))
        if not aggregate_text:
            continue
        aggregate_spans = _merge_span_lists(aggregate_spans_by_slot.get(slot_prefix, ()))
        span_marker = tuple((span[0], span[1]) for span in aggregate_spans) or ((-1, -1),)
        span_formula_signatures = _span_formula_modal_signatures(
            formulas,
            spans=aggregate_spans,
        )
        contextual_formula_signatures = _nearest_formula_modal_signatures(
            formulas,
            spans=aggregate_spans,
        )
        aggregate_bridge_cues = _bridge_cues_from_text(aggregate_text)
        semantic_aggregate_text = _semantic_source_phrase_text(aggregate_text)
        if semantic_aggregate_text and (
            not slot_prefix.endswith("_semantic")
            or semantic_aggregate_text.lower() != aggregate_text.lower()
        ):
            semantic_slot_prefix = f"{slot_prefix}_semantic"
            semantic_marker = (semantic_slot_prefix, semantic_aggregate_text, span_marker)
            if semantic_marker not in seen:
                seen.add(semantic_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=semantic_aggregate_text,
                        slot=semantic_slot_prefix,
                        spans=aggregate_spans,
                        provenance_only=True,
                    )
                )
            for slot, value in _typed_identifier_slots(
                semantic_aggregate_text,
                slot_prefix=semantic_slot_prefix,
            ):
                marker = (slot, value, span_marker)
                if marker in seen:
                    continue
                seen.add(marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=value,
                        slot=slot,
                        spans=aggregate_spans,
                        provenance_only=True,
                    )
                )
            for formula in formulas:
                for refined_slot, refined_value in _refined_contextual_modal_transition_slots(
                    formula,
                    text=semantic_aggregate_text,
                    slot_prefix=semantic_slot_prefix,
                ):
                    refined_marker = (refined_slot, refined_value, span_marker)
                    if refined_marker in seen:
                        continue
                    seen.add(refined_marker)
                    phrases.append(
                        DecodedModalPhrase(
                            text=refined_value,
                            slot=refined_slot,
                            spans=aggregate_spans,
                            provenance_only=True,
                        )
                    )
            for cue in _bridge_cues_from_text(semantic_aggregate_text):
                cue_marker = (f"{semantic_slot_prefix}_bridge_cue", cue, span_marker)
                if cue_marker in seen:
                    continue
                seen.add(cue_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=cue,
                        slot=f"{semantic_slot_prefix}_bridge_cue",
                        spans=aggregate_spans,
                        provenance_only=True,
                    )
                )
                if cue not in aggregate_bridge_cues:
                    aggregate_bridge_cues.append(cue)
            for clause_slot, clause_value in _source_span_clause_prefix_slots(
                semantic_aggregate_text,
                slot_prefix=semantic_slot_prefix,
            ):
                clause_marker = (clause_slot, clause_value, span_marker)
                if clause_marker in seen:
                    continue
                seen.add(clause_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=clause_value,
                        slot=clause_slot,
                        spans=aggregate_spans,
                        provenance_only=True,
                    )
                )
        for clause_slot, clause_value in _source_span_clause_prefix_slots(
            aggregate_text,
            slot_prefix=slot_prefix,
        ):
            clause_marker = (clause_slot, clause_value, span_marker)
            if clause_marker in seen:
                continue
            seen.add(clause_marker)
            phrases.append(
                DecodedModalPhrase(
                    text=clause_value,
                    slot=clause_slot,
                    spans=aggregate_spans,
                    provenance_only=True,
                )
            )
        for slot, value in _typed_identifier_slots(
            aggregate_text,
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
                    spans=aggregate_spans,
                    provenance_only=True,
                )
            )
        for cue in aggregate_bridge_cues:
            cue_marker = (f"{slot_prefix}_bridge_cue", cue, span_marker)
            if cue_marker not in seen:
                seen.add(cue_marker)
                phrases.append(
                    DecodedModalPhrase(
                        text=cue,
                        slot=f"{slot_prefix}_bridge_cue",
                        spans=aggregate_spans,
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
                        spans=aggregate_spans,
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
                            spans=aggregate_spans,
                            provenance_only=True,
                        )
                    )
            for (
                formula_family,
                formula_symbol,
                formula_signature,
                distance_bucket,
            ) in contextual_formula_signatures:
                context_signature = f"{formula_signature}:{distance_bucket}"
                for context_slot, context_value in (
                    (
                        f"{slot_prefix}_bridge_modal_context_formula_signature",
                        context_signature,
                    ),
                    (
                        f"{slot_prefix}_bridge_modal_context_formula_family",
                        formula_family,
                    ),
                    (
                        f"{slot_prefix}_bridge_modal_context_formula_operator",
                        formula_symbol,
                    ),
                    (
                        f"{slot_prefix}_bridge_modal_context_distance_bucket",
                        distance_bucket,
                    ),
                ):
                    context_marker = (context_slot, context_value, span_marker)
                    if context_marker in seen:
                        continue
                    seen.add(context_marker)
                    phrases.append(
                        DecodedModalPhrase(
                            text=context_value,
                            slot=context_slot,
                            spans=aggregate_spans,
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
                        f"{bridge_family}:{bridge_symbol}:{cue}:{distance_bucket}"
                    )
                    for transition_slot, transition_value in (
                        (
                            f"{slot_prefix}_bridge_modal_context_family_pair",
                            family_pair,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_context_operator_pair",
                            operator_pair,
                        ),
                        (
                            f"{slot_prefix}_bridge_modal_context_transition_signature",
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
                                spans=aggregate_spans,
                                provenance_only=True,
                            )
                        )
            for (
                formula_family,
                formula_symbol,
                formula_signature,
            ) in span_formula_signatures:
                signature_marker = (
                    f"{slot_prefix}_bridge_modal_formula_signature",
                    formula_signature,
                    span_marker,
                )
                if signature_marker not in seen:
                    seen.add(signature_marker)
                    phrases.append(
                        DecodedModalPhrase(
                            text=formula_signature,
                            slot=f"{slot_prefix}_bridge_modal_formula_signature",
                            spans=aggregate_spans,
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
                    operator_pair_key = _modal_operator_pair_feature_key(
                        formula_symbol,
                        bridge_symbol,
                    )
                    transition_signature = (
                        f"{formula_family}:{formula_symbol}->"
                        f"{bridge_family}:{bridge_symbol}:{cue}"
                    )
                    pair_cue = f"{family_pair}:{cue}"
                    family_pair_key = _slot_safe_family_pair_key(family_pair)
                    transition_items: List[Tuple[str, str]] = [
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
                    ]
                    transition_items.extend(
                        _modal_operator_transition_signature_slots(
                            source_family=formula_family,
                            source_system=_default_modal_system_key(formula_family),
                            source_symbol=formula_symbol,
                            target_family=bridge_family,
                            target_symbol=bridge_symbol,
                            slot_prefix=f"{slot_prefix}_bridge_modal",
                        )
                    )
                    if family_pair_key:
                        transition_items.append(
                            (
                                f"{slot_prefix}_bridge_modal_family_pair_key",
                                family_pair_key,
                            )
                        )
                    if operator_pair_key:
                        transition_items.append(
                            (
                                f"{slot_prefix}_bridge_modal_operator_pair_key",
                                operator_pair_key,
                            )
                        )
                    for transition_slot, transition_value in transition_items:
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
                                spans=aggregate_spans,
                                provenance_only=True,
                            )
                        )
        # Preserve cross-fragment modal/temporal bridge semantics by replaying
        # refined transition slots over the merged source span surface.
        for formula in formulas:
            for refined_slot, refined_value in _refined_contextual_modal_transition_slots(
                formula,
                text=aggregate_text,
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
                        spans=aggregate_spans,
                        provenance_only=True,
                    )
                )
    return phrases


def _source_span_clause_prefix_slots(
    text: str,
    *,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_slot_prefix or not normalized_text:
        return []
    slots: List[Tuple[str, str]] = []
    for clause_kind, prefixes in (
        ("condition", _CONDITION_PREFIXES),
        ("exception", _EXCEPTION_PREFIXES),
    ):
        for prefix_text, prefix_key in sorted(
            prefixes,
            key=lambda item: (-len(item[0]), item[1]),
        ):
            if not re.search(
                rf"(?<!\w){re.escape(prefix_text)}(?!\w)",
                normalized_text,
            ):
                continue
            slots.extend(
                (
                    (f"{normalized_slot_prefix}_{clause_kind}_present", "true"),
                    (
                        f"{normalized_slot_prefix}_{clause_kind}_prefix",
                        prefix_text,
                    ),
                    (
                        f"{normalized_slot_prefix}_{clause_kind}_prefix_key",
                        prefix_key,
                    ),
                    (
                        f"{normalized_slot_prefix}_clause_prefix_key",
                        f"{clause_kind}:{prefix_key}",
                    ),
                    (
                        "source_span_clause_prefix_key",
                        f"{normalized_slot_prefix}:{clause_kind}:{prefix_key}",
                    ),
                )
            )
    return _unique_slot_values(slots)


def _semantic_source_phrase_text(text: str, *, max_tokens: int = 80) -> str:
    normalized = _clean_text(text)
    if not normalized:
        return ""
    normalized = _clean_text(_USCODE_LEADING_SECTION_REF_RE.sub("", normalized))
    normalized = _strip_uscode_gpo_attribution_fragment(normalized)
    normalized = _TRAILING_SECTION_PUNCT_RE.sub("", normalized)
    normalized = _trim_uscode_compilation_surface_text(
        normalized,
        max_tokens=max_tokens,
    )
    normalized = _clean_text(normalized)
    if not normalized or _is_low_information_section_marker(normalized):
        return ""
    return normalized


def _merge_span_lists(spans: Sequence[Sequence[int]]) -> List[List[int]]:
    normalized: List[Tuple[int, int]] = []
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
        normalized.append((start, end))
    if not normalized:
        return []
    normalized.sort()
    merged: List[List[int]] = []
    current_start, current_end = normalized[0]
    for start, end in normalized[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        merged.append([current_start, current_end])
        current_start, current_end = start, end
    merged.append([current_start, current_end])
    return merged


def _span_formula_modal_signatures(
    formulas: Sequence[ModalIRFormula],
    *,
    spans: Sequence[Sequence[int]],
) -> List[Tuple[str, str, str]]:
    signatures: List[Tuple[str, str, str]] = []
    for formula in _span_overlapping_formulas(formulas, spans=spans):
        family = _clean_text(formula.operator.family).lower()
        symbol = _clean_text(formula.operator.symbol)
        if not family or not symbol:
            continue
        signature = (family, symbol, f"{family}:{symbol}")
        if signature not in signatures:
            signatures.append(signature)
    return signatures


def _nearest_formula_modal_signatures(
    formulas: Sequence[ModalIRFormula],
    *,
    spans: Sequence[Sequence[int]],
) -> List[Tuple[str, str, str, str]]:
    if not formulas or not spans:
        return []
    if _span_overlapping_formulas(formulas, spans=spans):
        return []
    normalized_spans = _normalized_spans(spans)
    if not normalized_spans:
        return []
    anchor_start = min(start for start, _ in normalized_spans)
    anchor_end = max(end for _, end in normalized_spans)
    ranked: List[Tuple[int, ModalIRFormula]] = []
    for formula in formulas:
        try:
            formula_start = int(formula.provenance.start_char)
            formula_end = int(formula.provenance.end_char)
        except (TypeError, ValueError):
            continue
        if formula_end <= formula_start:
            continue
        distance = _span_distance(
            anchor_start=anchor_start,
            anchor_end=anchor_end,
            formula_start=formula_start,
            formula_end=formula_end,
        )
        ranked.append((distance, formula))
    if not ranked:
        return []
    ranked.sort(key=lambda item: item[0])
    signatures: List[Tuple[str, str, str, str]] = []
    for distance, formula in ranked[:2]:
        family = _clean_text(formula.operator.family).lower()
        symbol = _clean_text(formula.operator.symbol)
        if not family or not symbol:
            continue
        distance_bucket = _span_distance_bucket(distance)
        candidate = (family, symbol, f"{family}:{symbol}", distance_bucket)
        if candidate not in signatures:
            signatures.append(candidate)
    return signatures


def _normalized_spans(spans: Sequence[Sequence[int]]) -> List[Tuple[int, int]]:
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
    return normalized_spans


def _span_distance(
    *,
    anchor_start: int,
    anchor_end: int,
    formula_start: int,
    formula_end: int,
) -> int:
    if formula_end <= anchor_start:
        return max(0, anchor_start - formula_end)
    if formula_start >= anchor_end:
        return max(0, formula_start - anchor_end)
    return 0


def _span_distance_bucket(distance: int) -> str:
    normalized = max(0, int(distance))
    if normalized == 0:
        return "adjacent"
    if normalized <= 64:
        return "near"
    if normalized <= 256:
        return "mid"
    return "far"


def _span_formula_bridge_cues(
    formulas: Sequence[ModalIRFormula],
    *,
    spans: Sequence[Sequence[int]],
) -> List[str]:
    cues: List[str] = []
    for formula in _span_overlapping_formulas(formulas, spans=spans):
        for raw_cue in (*_formula_cues(formula), *_formula_bridge_cues(formula)):
            cue_key = _normalized_bridge_cue_key(raw_cue)
            if cue_key and cue_key not in cues:
                cues.append(cue_key)
    return cues


def _normalized_bridge_cue_key(cue: str) -> str:
    cleaned_cue = _clean_text(cue).lower()
    if not cleaned_cue or _is_fallback_modal_cue(cleaned_cue):
        return ""
    tokens = _CUE_TOKEN_RE.findall(cleaned_cue.replace("_", " "))
    if not tokens:
        return ""
    return "_".join(tokens)


def _span_overlapping_formulas(
    formulas: Sequence[ModalIRFormula],
    *,
    spans: Sequence[Sequence[int]],
) -> List[ModalIRFormula]:
    overlapping_formulas: List[ModalIRFormula] = []
    if not formulas or not spans:
        return overlapping_formulas
    normalized_spans = _normalized_spans(spans)
    if not normalized_spans:
        return overlapping_formulas
    for formula in formulas:
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
        overlapping_formulas.append(formula)
    return overlapping_formulas


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
    provenance_only = False
    if slot == "source_context_span":
        semantic_text = _semantic_source_phrase_text(text, max_tokens=48)
        token_count = len(_tokenize_for_similarity(text))
        if _is_probable_uscode_compilation_span(text):
            if semantic_text:
                text = semantic_text
            else:
                provenance_only = True
        elif token_count > 48:
            semantic_token_count = len(_tokenize_for_similarity(semantic_text))
            if semantic_text and semantic_token_count and semantic_token_count < token_count:
                text = semantic_text
            else:
                provenance_only = True
    if slot == "modal_source_span":
        semantic_text = _semantic_source_phrase_text(text, max_tokens=48)
        token_count = len(_tokenize_for_similarity(text))
        if _is_probable_uscode_compilation_span(text):
            if semantic_text:
                text = semantic_text
            else:
                provenance_only = True
        elif token_count > 48:
            semantic_token_count = len(_tokenize_for_similarity(semantic_text))
            if semantic_text and semantic_token_count and semantic_token_count < token_count:
                text = semantic_text
            else:
                provenance_only = True
    phrases.append(
        DecodedModalPhrase(
            text=text,
            slot=slot,
            spans=[[clamped_start, clamped_end]],
            provenance_only=provenance_only,
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


def _typed_argument_slots(argument: str) -> List[Tuple[str, str]]:
    cleaned = _clean_text(argument)
    if not cleaned or ":" not in cleaned:
        return []
    slots: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for match in re.finditer(
        r"(?:(?<=^)|(?<=[,;]))\s*(?P<key>[A-Za-z][A-Za-z0-9_ -]*)\s*:\s*"
        r"(?P<value>.*?)(?=\s*[,;]\s*[A-Za-z][A-Za-z0-9_ -]*\s*:|$)",
        cleaned,
    ):
        key = re.sub(
            r"[^a-z0-9_]+",
            "_",
            _clean_text(match.group("key")).lower(),
        ).strip("_")
        value = _clean_text(match.group("value")).replace("_", " ")
        if not key or not value:
            continue
        marker = (f"argument_{key}", value)
        if marker in seen:
            continue
        seen.add(marker)
        slots.append(marker)
    if slots:
        return slots
    fallback = _typed_argument_slot(cleaned)
    return [fallback] if fallback is not None else []


def _source_role_anchor_phrases(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    anchors = _source_role_anchor_values(document=document, formula=formula)
    if not anchors:
        return []
    predicate_role = _clean_text(formula.predicate.role).lower()
    predicate_family = _clean_text(formula.operator.family).lower()
    predicate_role_label = predicate_role or "clause"
    predicate_operator = _modal_operator_feature_key(formula.operator.symbol)
    source_family_pairs = _source_anchor_family_pairs(
        document=document,
        formula=formula,
    )
    predicate_head = _predicate_head_anchor(formula)
    structural_roles = [
        role_name
        for role_name in ("subject", "action", "object")
        if _clean_text(anchors.get(role_name, ""))
    ]
    role_set = "+".join(structural_roles)
    role_path = "->".join(structural_roles)
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str]] = set()

    def add(slot: str, value: str) -> None:
        normalized_slot = _clean_text(slot)
        normalized_value = _clean_text(value)
        marker = (normalized_slot, normalized_value)
        if not normalized_slot or not normalized_value or marker in seen:
            return
        seen.add(marker)
        phrases.append(
            DecodedModalPhrase(
                text=normalized_value,
                slot=normalized_slot,
                spans=spans,
                provenance_only=True,
            )
        )

    if role_set:
        add("source_role_set", role_set)
        add("source_surface_role_set", role_set)
        if predicate_family:
            add("source_role_set_family", f"{role_set}:{predicate_family}")
            add("source_surface_role_set_to_family", f"{role_set}:{predicate_family}")
    if role_path:
        add("source_role_path", role_path)
        add("source_role_path_scope", f"{role_path}:unscoped")
        if predicate_family:
            add("source_role_path_family", f"{role_path}:{predicate_family}")
    for role_name in ("subject", "action", "object"):
        anchor = _clean_text(anchors.get(role_name, "")) or "none"
        variable_name = f"v_{role_name}"
        add("source_logical_variable_map", f"{role_name}:{anchor}:{variable_name}")
        add(
            f"source_{role_name}_logical_variable_map",
            f"{role_name}:{anchor}:{variable_name}",
        )

    for role_name in ("subject", "action", "object", "condition", "exception", "temporal"):
        anchor = _clean_text(anchors.get(role_name, ""))
        if not anchor:
            continue
        slot_prefix = f"source_{role_name}_anchor"
        add(slot_prefix, anchor)
        for slot_name, slot_value in _typed_identifier_slots(
            anchor,
            slot_prefix=slot_prefix,
        ):
            add(slot_name, slot_value)
        if predicate_family:
            add(f"source_{role_name}_family", f"{anchor}:{predicate_family}")
            add(
                f"predicate_argument_source_{role_name}_family",
                f"{anchor}:{predicate_family}",
            )
            add(
                "predicate_argument_feature",
                f"predicate-argument:source-{role_name}-family:{anchor}:{predicate_family}",
            )
            for family_pair in source_family_pairs:
                add(f"source_{role_name}_family_pair", family_pair)
                add(
                    f"source_{role_name}_family_pair_anchor",
                    f"{anchor}:{family_pair}",
                )
        if predicate_role and role_name in {"subject", "action", "object"}:
            add(f"source_{role_name}_role", f"{anchor}:{predicate_role}")
        if predicate_family and role_name in {"subject", "action", "object"}:
            # Preserve deterministic role-style features even when predicate.role
            # is missing or generic; downstream IR views rely on these anchors.
            add(f"source_{role_name}_role", f"{anchor}_{predicate_family}")
            add(f"source_{role_name}_role_family", f"{anchor}_{predicate_family}")
            add(
                f"predicate_argument_source_{role_name}_role",
                f"{anchor}:{predicate_role_label}",
            )
            add(
                "predicate_argument_feature",
                f"predicate-argument:source-{role_name}-role:{anchor}:{predicate_role_label}",
            )
            if predicate_operator:
                add(
                    f"predicate_argument_source_{role_name}_operator",
                    f"{anchor}:{predicate_family}:{predicate_operator}",
                )
                add(
                    "predicate_argument_feature",
                    (
                        "predicate-argument:"
                        f"source-{role_name}-operator:{anchor}:{predicate_family}:{predicate_operator}"
                    ),
                )
        if predicate_head and role_name in {"action", "object"}:
            add(f"source_{role_name}_predicate", f"{anchor}:{predicate_head}")
            add(
                f"predicate_argument_source_{role_name}_predicate",
                f"{anchor}:{predicate_head}",
            )
            add(
                "predicate_argument_feature",
                f"predicate-argument:source-{role_name}-predicate:{anchor}:{predicate_head}",
            )
    if predicate_family and predicate_operator:
        add(
            "predicate_argument_operator",
            f"{predicate_family}:{formula.operator.system}:{predicate_operator}",
        )
        add(
            "predicate_argument_feature",
            (
                "predicate-argument:"
                f"operator:{predicate_family}:{formula.operator.system}:{predicate_operator}"
            ),
        )
    if predicate_role:
        # Preserve stable role anchors from typed predicate/citation scaffolding
        # so decompiler slot features keep legal-IR semantics when span anchors
        # are noisy (for example, heading-heavy U.S. Code compilation text).
        if predicate_head:
            add("source_action_role", f"{predicate_head}:{predicate_role}")
            if predicate_family:
                add("source_action_role_family", f"{predicate_head}_{predicate_family}")
        citation_text = _clean_text(formula.provenance.citation or "")
        if not citation_text:
            citation_text = _source_id_inferred_citation(
                _clean_text(formula.provenance.source_id or "")
            )
        if citation_text:
            add("source_action_role", f"section:{predicate_role}")
            add("source_object_role", f"title:{predicate_role}")
            if predicate_family:
                add("source_action_role_family", f"section_{predicate_family}")
                add("source_object_role_family", f"title_{predicate_family}")
    return phrases


def _source_anchor_family_pairs(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[str]:
    source_family = _clean_text(formula.operator.family).lower()
    if not source_family:
        return []
    distinct_families: List[str] = []
    for candidate_formula in document.formulas:
        candidate_family = _clean_text(candidate_formula.operator.family).lower()
        if not candidate_family or candidate_family in distinct_families:
            continue
        distinct_families.append(candidate_family)
    for target_family in _cue_derived_target_families(formula):
        if target_family and target_family not in distinct_families:
            distinct_families.append(target_family)
    for target_family in _SOURCE_ANCHOR_DIRECTIONAL_FAMILY_PAIR_TARGETS.get(
        source_family,
        (),
    ):
        normalized_target = _clean_text(target_family).lower()
        if normalized_target and normalized_target not in distinct_families:
            distinct_families.append(normalized_target)
    if source_family not in distinct_families:
        distinct_families.append(source_family)
    ordered_targets = sorted(
        distinct_families,
        key=lambda family: (
            0 if family == source_family else 1,
            _CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY.get(
                family,
                len(_CROSS_FAMILY_BRIDGE_FAMILY_PRIORITY),
            ),
            family,
        ),
    )
    return [f"{source_family}->{target_family}" for target_family in ordered_targets]


def _cue_derived_target_families(formula: ModalIRFormula) -> List[str]:
    derived: List[str] = []
    source_family = _clean_text(formula.operator.family).lower()
    if source_family == "temporal":
        derived.append("temporal")
    for cue in (*_formula_cues(formula), *_formula_bridge_cues(formula)):
        cue_key = _clean_text(cue).lower().replace(" ", "_")
        if not cue_key:
            continue
        for target_family, _ in _cue_bridge_operator_pairs(cue_key):
            normalized_target = _clean_text(target_family).lower()
            if not normalized_target or normalized_target in derived:
                continue
            derived.append(normalized_target)
    return derived


def _typed_decompiler_bridge_phrases(
    *,
    document: ModalIRDocument | None,
    formula: ModalIRFormula,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    spans: List[List[int]],
) -> List[DecodedModalPhrase]:
    family = _clean_text(formula.operator.family).lower()
    if not family:
        return []
    predicate_head = _predicate_head_anchor(formula)
    source_family_pairs = (
        _source_anchor_family_pairs(document=document, formula=formula)
        if document is not None
        else [f"{family}->{family}"]
    )
    legal_ir_views = (
        "deontic.ir",
        "TDFOL.prover",
        "modal.frame_logic",
        "external_provers.router",
        "knowledge_graphs.neo4j_compat",
        "CEC.native",
        "zkp.circuits",
    )
    phrases: List[DecodedModalPhrase] = []
    seen: set[Tuple[str, str]] = set()

    def add(slot: str, value: str) -> None:
        normalized_slot = _clean_text(slot)
        normalized_value = _clean_text(value)
        marker = (normalized_slot, normalized_value)
        if not normalized_slot or not normalized_value or marker in seen:
            return
        seen.add(marker)
        phrases.append(
            DecodedModalPhrase(
                text=normalized_value,
                slot=normalized_slot,
                spans=spans,
                provenance_only=True,
            )
        )

    add("typed_decompiler_family", family)
    for family_pair in source_family_pairs:
        pair_key = _slot_safe_family_pair_key(family_pair)
        add("typed_decompiler_family_pair", family_pair)
        if pair_key:
            add("typed_decompiler_family_pair_key", pair_key)
    if predicate_head:
        semantic_slot = f"{family}||slot:predicate-head:{predicate_head}"
        add("family_semantic_slot_prototype", semantic_slot)
        add("typed_decompiler_predicate_head_family", f"{family}:{predicate_head}")
        for view in legal_ir_views:
            add(
                "family_semantic_slot_legal_ir_view_prototype",
                f"{semantic_slot}||{view}",
            )
    for clause_slot, clause_values in (
        ("condition", condition_values),
        ("exception", exception_values),
    ):
        for clause in clause_values:
            parsed = _typed_clause_slot(clause, slot=clause_slot)
            if parsed is None:
                continue
            _, prefix_key, scoped_value = parsed
            normalized_prefix = _clean_text(prefix_key).lower()
            if normalized_prefix:
                for family_pair in source_family_pairs:
                    add(
                        f"{clause_slot}_scope_family_pair",
                        f"{normalized_prefix}:{family_pair}",
                    )
            content_value = _content_scope_value(scoped_value)
            if not content_value:
                continue
            for family_pair in source_family_pairs:
                add(
                    f"{clause_slot}_scope_content_family_pair",
                    f"{content_value}:{family_pair}",
                )
            for slot, value in _typed_identifier_slots(
                content_value,
                slot_prefix=f"{clause_slot}_scope_content",
            ):
                add(slot, value)
    if document is not None:
        anchors = _source_role_anchor_values(document=document, formula=formula)
        for role_name in ("subject", "action", "object", "condition", "temporal"):
            anchor = _clean_text(anchors.get(role_name, ""))
            if not anchor:
                continue
            for family_pair in source_family_pairs:
                add(
                    f"typed_decompiler_source_{role_name}_family_pair_anchor",
                    f"{anchor}:{family_pair}",
                )
            if role_name == "object" and anchor in {"pub", "publication", "public_law"}:
                add("source_object_publication_anchor", anchor)
                add("source_object_anchor_publication_family", f"{anchor}:{family}")
    return phrases


def _source_role_anchor_values(
    *,
    document: ModalIRDocument,
    formula: ModalIRFormula,
) -> Dict[str, str]:
    span_text = _semantic_source_span_text(document=document, formula=formula)
    predicate_text = _predicate_phrase(formula)
    raw_tokens = _CUE_TOKEN_RE.findall(span_text.lower())
    if not raw_tokens:
        raw_tokens = _CUE_TOKEN_RE.findall(predicate_text.lower())
    if not raw_tokens:
        return {}
    cue_sequences: List[List[str]] = []
    cue_tokens: set[str] = set()
    explicit_cue = _clean_text(formula.metadata.get("cue") or "")
    for cue_value in (explicit_cue, *_formula_cues(formula)):
        cue_sequence = _CUE_TOKEN_RE.findall(
            _clean_text(cue_value).replace("_", " ").lower()
        )
        if not cue_sequence:
            continue
        cue_sequences.append(cue_sequence)
        cue_tokens.update(cue_sequence)

    cue_window: tuple[int, int] | None = None
    for cue_sequence in sorted(cue_sequences, key=len, reverse=True):
        width = len(cue_sequence)
        if width <= 0 or width > len(raw_tokens):
            continue
        for start in range(0, len(raw_tokens) - width + 1):
            if raw_tokens[start : start + width] != cue_sequence:
                continue
            candidate = (start, start + width)
            if cue_window is None:
                cue_window = candidate
            else:
                current_width = cue_window[1] - cue_window[0]
                if width > current_width or (
                    width == current_width and start < cue_window[0]
                ):
                    cue_window = candidate
            break

    cue_start = -1
    cue_end = -1
    if cue_window is not None:
        cue_start, cue_end = cue_window
    else:
        cue_start = next(
            (
                index
                for index, token in enumerate(raw_tokens)
                if token in cue_tokens or token in _SOURCE_ROLE_CUE_MARKERS
            ),
            -1,
        )
        cue_end = cue_start + 1 if cue_start >= 0 else -1

    if cue_start >= 0 and cue_end > cue_start:
        subject_candidates = _source_anchor_role_tokens(raw_tokens[:cue_start])
        predicate_candidates = _source_anchor_role_tokens(raw_tokens[cue_end:])
    else:
        subject_candidates = _source_anchor_role_tokens(raw_tokens[:2])
        predicate_candidates = _source_anchor_role_tokens(raw_tokens[1:])
    if cue_start == 0 and cue_end > 0:
        scoped_cue_index = next(
            (
                index
                for index, token in enumerate(raw_tokens[cue_end:], start=cue_end)
                if token in _SOURCE_ROLE_CUE_MARKERS
            ),
            -1,
        )
        if scoped_cue_index >= cue_end:
            scoped_subject_candidates = _source_anchor_role_tokens(
                raw_tokens[cue_end:scoped_cue_index]
            )
            scoped_predicate_candidates = _source_anchor_role_tokens(
                raw_tokens[scoped_cue_index + 1 :]
            )
            if scoped_predicate_candidates:
                if scoped_subject_candidates:
                    subject_candidates = scoped_subject_candidates
                predicate_candidates = scoped_predicate_candidates
    predicate_tokens = _source_anchor_role_tokens(
        _CUE_TOKEN_RE.findall(predicate_text.lower())
    )
    if _is_probable_uscode_compilation_span(span_text) and predicate_tokens:
        # Compilation spans carry long heading scaffolding. Keep high-signal
        # semantic anchors from the span (for example "commission") when
        # present, and backfill with predicate-derived anchors.
        semantic_span_candidates = _source_semantic_anchor_role_tokens(raw_tokens)
        if semantic_span_candidates:
            subject_candidates = [
                *semantic_span_candidates,
                *[token for token in predicate_tokens if token not in semantic_span_candidates],
            ]
            predicate_candidates = [
                *semantic_span_candidates,
                *[token for token in predicate_tokens if token not in semantic_span_candidates],
            ]
        else:
            subject_candidates = list(predicate_tokens)
            predicate_candidates = list(predicate_tokens)
    if not subject_candidates and predicate_tokens:
        subject_candidates = predicate_tokens[:1]
    if not predicate_candidates:
        predicate_candidates = list(predicate_tokens)
    condition_values = _resolved_formula_conditions(
        document=document,
        formula=formula,
    )
    exception_values = _resolved_formula_exceptions(
        document=document,
        formula=formula,
    )
    temporal_anchor = _source_anchor_from_clauses(
        clauses=condition_values,
        clause_type="condition",
        temporal_only=True,
    )
    if not temporal_anchor:
        temporal_anchor = _source_anchor_from_clauses(
            clauses=exception_values,
            clause_type="exception",
            temporal_only=True,
        )
    subject_anchor = _preferred_anchor_candidate(
        subject_candidates,
        default_index=-1,
    )
    action_anchor = _preferred_anchor_candidate(
        predicate_candidates,
        default_index=0,
    )
    object_anchor = _preferred_anchor_candidate(
        predicate_candidates,
        default_index=1,
    )
    predicate_default_anchor = _preferred_anchor_candidate(
        predicate_tokens,
        default_index=0,
    )
    if not action_anchor:
        action_anchor = predicate_default_anchor
    if (
        not object_anchor
        or object_anchor == action_anchor
        or _is_temporal_anchor_token(object_anchor)
    ):
        object_anchor = _preferred_anchor_candidate(
            [
                token
                for token in predicate_tokens
                if token != action_anchor
            ],
            default_index=0,
        )
    anchors = {
        "subject": subject_anchor,
        "action": action_anchor,
        "object": object_anchor,
        "condition": _source_anchor_from_clauses(
            clauses=condition_values,
            clause_type="condition",
        ),
        "exception": _source_anchor_from_clauses(
            clauses=exception_values,
            clause_type="exception",
        ),
        "temporal": temporal_anchor
        or _source_anchor_first_after(
            tokens=raw_tokens,
            markers=_SOURCE_ROLE_TEMPORAL_MARKERS,
        ),
    }
    return {name: value for name, value in anchors.items() if value}


def _source_anchor_role_tokens(tokens: Sequence[str]) -> List[str]:
    return [
        token
        for token in tokens
        if len(token) > 2
        and token not in _SOURCE_ROLE_NOISE_TOKENS
        and token not in _SOURCE_ROLE_CONNECTIVE_TOKENS
        and token not in _SOURCE_ROLE_QUANTIFIER_TOKENS
        and token not in _LOW_INFORMATION_SCOPE_LEADING_TOKENS
        and token not in _SOURCE_ROLE_CUE_MARKERS
        and token not in _SOURCE_ROLE_CONDITION_MARKERS
        and token not in _SOURCE_ROLE_EXCEPTION_MARKERS
        and token not in _SOURCE_ROLE_TEMPORAL_MARKERS
        and token not in _SOURCE_ROLE_NEGATION_MARKERS
        and not _is_low_information_section_marker(token)
    ]


def _source_semantic_anchor_role_tokens(tokens: Sequence[str]) -> List[str]:
    candidates = _source_anchor_role_tokens(tokens)
    if not candidates:
        return []
    filtered = [
        token
        for token in candidates
        if token not in _SOURCE_ROLE_COMPILATION_NOISE_TOKENS
    ]
    if filtered:
        return filtered
    return candidates


def _is_temporal_anchor_token(token: str) -> bool:
    normalized_token = _clean_text(token).lower()
    if not normalized_token:
        return False
    if _TEMPORAL_BRIDGE_YEAR_RE.fullmatch(normalized_token):
        return True
    return (
        normalized_token in _SOURCE_ROLE_MONTH_TOKENS
        or normalized_token in _SOURCE_ROLE_TEMPORAL_CONTEXT_TOKENS
    )


def _anchor_candidate_search_order(
    *,
    candidate_count: int,
    default_index: int,
) -> List[int]:
    if candidate_count <= 0:
        return []
    if default_index < 0:
        normalized_index = candidate_count + default_index
    else:
        normalized_index = default_index
    normalized_index = min(max(normalized_index, 0), candidate_count - 1)
    return [
        normalized_index,
        *range(normalized_index + 1, candidate_count),
        *range(normalized_index - 1, -1, -1),
    ]


def _preferred_anchor_candidate(
    candidates: Sequence[str],
    *,
    default_index: int = 0,
    prefer_temporal: bool = False,
) -> str:
    normalized_candidates = [
        _clean_text(candidate).lower()
        for candidate in candidates
        if _clean_text(candidate)
    ]
    if not normalized_candidates:
        return ""
    search_order = _anchor_candidate_search_order(
        candidate_count=len(normalized_candidates),
        default_index=default_index,
    )
    default_candidate = normalized_candidates[search_order[0]]
    for index in search_order:
        candidate = normalized_candidates[index]
        is_temporal = _is_temporal_anchor_token(candidate)
        if prefer_temporal and is_temporal:
            return candidate
        if not prefer_temporal and not is_temporal:
            return candidate
    return default_candidate


def _source_anchor_first_after(
    *,
    tokens: Sequence[str],
    markers: set[str] | frozenset[str],
) -> str:
    for index, token in enumerate(tokens):
        if token not in markers:
            continue
        candidates = _source_anchor_role_tokens(tokens[index + 1 : index + 6])
        if candidates:
            return candidates[0]
    return ""


def _source_anchor_from_clauses(
    *,
    clauses: Sequence[str],
    clause_type: str,
    temporal_only: bool = False,
) -> str:
    for clause in clauses:
        normalized_clause = _clean_text(clause).lower()
        if not normalized_clause:
            continue
        parsed_clause = _typed_clause_slot(normalized_clause, slot=clause_type)
        scoped_text = normalized_clause
        if parsed_clause is not None:
            _, prefix_key, scoped_value = parsed_clause
            if temporal_only and not _temporal_clause_prefix_relation(prefix_key):
                continue
            scoped_text = scoped_value or scoped_text
        elif temporal_only:
            continue
        candidates = _source_anchor_role_tokens(_CUE_TOKEN_RE.findall(scoped_text))
        if candidates:
            return _preferred_anchor_candidate(
                candidates,
                default_index=0,
                prefer_temporal=temporal_only,
            )
    return ""


def _predicate_head_anchor(formula: ModalIRFormula) -> str:
    predicate_tokens = _CUE_TOKEN_RE.findall(
        _clean_text(formula.predicate.name).replace("_", " ").lower()
    )
    if not predicate_tokens:
        return ""
    for token in predicate_tokens:
        if token in _LOW_INFORMATION_SCOPE_LEADING_TOKENS:
            continue
        if _is_low_information_section_marker(token):
            continue
        return token
    return predicate_tokens[0]


def _typed_clause_phrases(
    clause: str,
    *,
    slot: str,
    spans: List[List[int]],
    formula: ModalIRFormula,
    clause_index: int | None = None,
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
    if clause_index is not None and clause_index >= 0:
        plural_slot = f"{slot}s"
        indexed_clause_role = f"{plural_slot}:{clause_index}|predicate-role:clause"
        phrases.extend(
            (
                DecodedModalPhrase(
                    text=str(clause_index),
                    slot=f"{slot}_index",
                    spans=spans,
                    provenance_only=True,
                ),
                DecodedModalPhrase(
                    text="predicate-role:clause",
                    slot=f"{slot}_predicate_role",
                    spans=spans,
                    provenance_only=True,
                ),
                DecodedModalPhrase(
                    text=indexed_clause_role,
                    slot=f"{slot}_indexed_predicate_role",
                    spans=spans,
                    provenance_only=True,
                ),
                DecodedModalPhrase(
                    text=indexed_clause_role,
                    slot="clause_indexed_predicate_role",
                    spans=spans,
                    provenance_only=True,
                ),
            )
        )
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


def _refined_clause_bridge_phrases(
    clause: str,
    *,
    slot: str,
    spans: List[List[int]],
    formula: ModalIRFormula,
) -> List[DecodedModalPhrase]:
    parsed = _typed_clause_slot(clause, slot=slot)
    if parsed is None:
        return []
    _, prefix_key, scoped_value = parsed
    normalized_slot = _clean_text(slot)
    normalized_prefix = _clean_text(prefix_key).lower()
    normalized_scope = _clean_text(scoped_value)
    if not normalized_slot or not normalized_prefix:
        return []

    source_family = _clean_text(formula.operator.family).lower()
    source_operator = _clean_text(formula.operator.symbol)
    if not source_family or not source_operator:
        return []
    bridge_pairs = _augment_deontic_bridge_pairs(
        bridge_pairs=_cue_bridge_operator_pairs(normalized_prefix),
        formula_family=source_family,
        formula_symbol=source_operator,
        cue=normalized_prefix,
    )
    if source_family == "deontic" and normalized_slot == "exception":
        deontic_pair = ("deontic", source_operator)
        if deontic_pair not in bridge_pairs:
            bridge_pairs.append(deontic_pair)

    slot_items: List[Tuple[str, str]] = [
        (f"{normalized_slot}_scope_refined_modal_cue", normalized_prefix),
        ("clause_scope_refined_modal_cue", f"{normalized_slot}:{normalized_prefix}"),
        (
            f"{normalized_slot}_scope_refined_modal_source_signature",
            f"{source_family}:{source_operator}:{normalized_prefix}",
        ),
    ]
    temporal_relation = _temporal_clause_prefix_relation(normalized_prefix)
    if temporal_relation:
        slot_items.extend(
            (
                (
                    f"{normalized_slot}_scope_refined_temporal_relation",
                    temporal_relation,
                ),
                (
                    f"{normalized_slot}_scope_refined_temporal_bridge_context",
                    f"{normalized_prefix}:{temporal_relation}",
                ),
                (
                    "refined_temporal_bridge_context",
                    f"{normalized_slot}:{normalized_prefix}:{temporal_relation}",
                ),
            )
        )
    if normalized_scope:
        scope_atom = _slot_safe_text_atom(normalized_scope, max_tokens=6)
        if scope_atom:
            slot_items.extend(
                (
                    (f"{normalized_slot}_scope_refined_scope_atom", scope_atom),
                    (
                        f"{normalized_slot}_scope_refined_cue_scope",
                        f"{normalized_prefix}:{scope_atom}",
                    ),
                )
            )

    for target_family, target_operator in bridge_pairs:
        target_family = _clean_text(target_family).lower()
        target_operator = _clean_text(target_operator)
        if not target_family or not target_operator:
            continue
        family_pair = f"{source_family}->{target_family}"
        operator_pair = f"{source_operator}->{target_operator}"
        family_pair_key = _slot_safe_family_pair_key(family_pair)
        operator_pair_key = _modal_operator_pair_feature_key(
            source_operator,
            target_operator,
        )
        slot_items.extend(
            (
                (
                    f"{normalized_slot}_scope_refined_modal_family_pair",
                    family_pair,
                ),
                (
                    f"{normalized_slot}_scope_refined_modal_operator_pair",
                    operator_pair,
                ),
                (
                    f"{normalized_slot}_scope_refined_modal_pair_cue",
                    f"{family_pair}:{normalized_prefix}",
                ),
                (
                    f"{normalized_slot}_scope_refined_modal_bridge_signature",
                    f"{target_family}:{target_operator}:{normalized_prefix}",
                ),
                (
                    "refined_modal_context_pair",
                    f"{normalized_slot}_scope:{family_pair}",
                ),
            )
        )
        if family_pair_key:
            slot_items.append(
                (
                    f"{normalized_slot}_scope_refined_modal_family_pair_key",
                    family_pair_key,
                )
            )
        if operator_pair_key:
            slot_items.append(
                (
                    f"{normalized_slot}_scope_refined_modal_operator_pair_key",
                    operator_pair_key,
                )
            )

    phrases: List[DecodedModalPhrase] = []
    for refined_slot, refined_value in _unique_slot_values(slot_items):
        phrases.append(
            DecodedModalPhrase(
                text=refined_value,
                slot=refined_slot,
                spans=spans,
                provenance_only=True,
            )
        )
    return phrases


def _slot_safe_text_atom(value: str, *, max_tokens: int = 6) -> str:
    tokens = _CUE_TOKEN_RE.findall(_clean_text(value).lower())
    if not tokens:
        return ""
    return "_".join(tokens[:max(1, int(max_tokens))])


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
    phrases.extend(
        _refined_clause_bridge_phrases(
            scoped_exception,
            slot="condition",
            spans=spans,
            formula=formula,
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
    content_tokens = _CUE_TOKEN_RE.findall(content.lower())
    if len(content_tokens) == 1 and (
        content_tokens[0] in _LOW_INFORMATION_SECTION_MARKER_TOKENS
        or content_tokens[0] in _LOW_INFORMATION_SECTION_MARKER_SINGLE_CHAR_TOKENS
    ):
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
        normalized_family == "conditional_normative"
        and normalized_symbol == "O|"
        and cue_key in _CLAUSE_PREFIX_BRIDGE_CUES
    ):
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
        normalized_family == "temporal"
        and _temporal_clause_prefix_relation(cue_key)
    ):
        deontic_scope_pair = ("deontic", "O")
        if deontic_scope_pair not in pairs:
            pairs.append(deontic_scope_pair)
    if (
        normalized_family == "deontic"
        and cue_key in _DEONTIC_ALETHIC_BRIDGE_CUES
    ):
        deontic_alethic_pair = ("alethic", "◇")
        if deontic_alethic_pair not in pairs:
            pairs.append(deontic_alethic_pair)
    if (
        normalized_family == "deontic"
        and normalized_symbol in _DEONTIC_BRIDGE_REINFORCEMENT_OPERATORS
        and _temporal_clause_prefix_relation(cue_key)
    ):
        deontic_temporal_pair = ("deontic", normalized_symbol)
        if deontic_temporal_pair not in pairs:
            pairs.append(deontic_temporal_pair)
    if cue_key in _STATUTORY_SCOPE_BRIDGE_CUES:
        # Mirror codec bridge refinements so typed scope slots stay symmetric
        # between compilation and deterministic decompilation.
        if normalized_family == "deontic":
            deontic_scope_pair = ("deontic", "O")
            if deontic_scope_pair not in pairs:
                pairs.append(deontic_scope_pair)
            frame_scope_pair = ("frame", "Frame")
            if frame_scope_pair not in pairs:
                pairs.append(frame_scope_pair)
        if normalized_family == "temporal":
            temporal_scope_pairs = (
                ("conditional_normative", "O|"),
                ("deontic", "O"),
                ("frame", "Frame"),
            )
            for temporal_scope_pair in temporal_scope_pairs:
                if temporal_scope_pair not in pairs:
                    pairs.append(temporal_scope_pair)
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


def _modal_operator_transition_signature_slots(
    *,
    source_family: str,
    source_system: str,
    source_symbol: str,
    target_family: str,
    target_symbol: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    source_family_key = _clean_text(source_family).lower()
    source_system_key = _clean_text(source_system).lower()
    source_symbol_key = _modal_operator_feature_key(source_symbol)
    target_family_key = _clean_text(target_family).lower()
    target_symbol_key = _modal_operator_feature_key(target_symbol)
    target_system_key = _default_modal_system_key(target_family_key)
    if (
        not normalized_slot_prefix
        or not source_family_key
        or not source_system_key
        or not source_symbol_key
        or not target_family_key
        or not target_system_key
        or not target_symbol_key
    ):
        return []
    operator_pair = f"{_clean_text(source_symbol)}->{_clean_text(target_symbol)}"
    family_pair = f"{source_family_key}->{target_family_key}"
    signature = (
        f"{source_family_key}:{source_system_key}:{source_symbol_key}->"
        f"{target_family_key}:{target_system_key}:{target_symbol_key}"
    )
    slots: List[Tuple[str, str]] = [
        (f"{normalized_slot_prefix}_operator_transition", operator_pair),
        (f"{normalized_slot_prefix}_operator_transition_signature", signature),
        ("operator_transition", operator_pair),
        ("operator_transition_signature", signature),
        ("modal_operator_transition", operator_pair),
        ("modal_operator_transition_signature", signature),
    ]
    if family_pair:
        slots.extend(
            (
                (f"{normalized_slot_prefix}_family_transition", family_pair),
                ("modal_family_transition", family_pair),
            )
        )
    return slots


def _default_modal_system_key(family: str) -> str:
    normalized_family = _clean_text(family).lower()
    if normalized_family == "deontic":
        return "d"
    if normalized_family == "temporal":
        return "ltl"
    if normalized_family == "conditional_normative":
        return "dyadic"
    if normalized_family == "frame":
        return "frame"
    if normalized_family == "epistemic":
        return "s5"
    if normalized_family == "dynamic":
        return "pdl"
    if normalized_family == "alethic":
        return "s4"
    return normalized_family


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
        registry_family_pair_key = _slot_safe_family_pair_key(
            f"{family}->{registry_family}"
        )
        if registry_family_pair_key:
            slots.append(
                (
                    f"{normalized_slot_prefix}_registry_family_pair_key",
                    registry_family_pair_key,
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
        bridge_family_pair_key = _slot_safe_family_pair_key(bridge_family_pair)
        bridge_operator_pair = f"{symbol}->{bridge_symbol}"
        slots.extend(
            _modal_operator_transition_signature_slots(
                source_family=family,
                source_system=formula.operator.system,
                source_symbol=symbol,
                target_family=bridge_family,
                target_symbol=bridge_symbol,
                slot_prefix=f"{normalized_slot_prefix}_bridge",
            )
        )
        slots.append(
            (
                f"{normalized_slot_prefix}_bridge_family_pair",
                bridge_family_pair,
            )
        )
        if bridge_family_pair_key:
            slots.append(
                (
                    f"{normalized_slot_prefix}_bridge_family_pair_key",
                    bridge_family_pair_key,
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
            if bridge_family_pair_key:
                slots.append(
                    (
                        f"{alias_prefix}_bridge_family_pair_key",
                        bridge_family_pair_key,
                    )
                )
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


def _formula_bridge_cues(
    formula: ModalIRFormula,
    *,
    condition_values: Sequence[str] | None = None,
    exception_values: Sequence[str] | None = None,
) -> List[str]:
    searchable_segments: List[str] = []
    predicate_text = _clean_text(formula.predicate.name).replace("_", " ").lower()
    if predicate_text:
        searchable_segments.append(predicate_text)
    resolved_conditions = list(condition_values or formula.conditions)
    resolved_exceptions = list(exception_values or formula.exceptions)
    searchable_segments.extend(
        _clean_text(value).replace("_", " ").lower()
        for value in (*resolved_conditions, *resolved_exceptions)
        if _clean_text(value)
    )
    cues: List[str] = []
    if searchable_segments:
        searchable_text = " ".join(searchable_segments)
        for cue_key in sorted(
            _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS,
            key=lambda item: (-len(item), item),
        ):
            cue_surface = cue_key.replace("_", " ")
            if not cue_surface:
                continue
            if re.search(rf"(?<!\w){re.escape(cue_surface)}(?!\w)", searchable_text):
                cues.append(cue_key)
    if cues:
        return cues
    for cue in _formula_cues(formula):
        cue_key = _clean_text(cue).lower().replace(" ", "_")
        if (
            not cue_key
            or cue_key in cues
            or cue_key not in _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS
        ):
            continue
        cues.append(cue_key)
    return cues


def _formula_clause_prefix_cues(formula: ModalIRFormula) -> List[str]:
    cues: List[str] = []
    for slot_name, clauses in (
        ("condition", formula.conditions),
        ("exception", formula.exceptions),
    ):
        for clause in clauses:
            parsed_clause = _typed_clause_slot(clause, slot=slot_name)
            if parsed_clause is None:
                continue
            _, prefix_key, _ = parsed_clause
            cue = _clean_text(prefix_key).lower()
            if cue and cue not in cues:
                cues.append(cue)
    return cues


def _formula_transition_cues(formula: ModalIRFormula) -> List[str]:
    cues: List[str] = []
    for cue_candidate in (
        *_formula_cues(formula),
        *_formula_bridge_cues(formula),
        *_formula_clause_prefix_cues(formula),
    ):
        cue = _clean_text(cue_candidate).lower()
        if cue and cue not in cues:
            cues.append(cue)
    return cues


def _modal_transition_slots(formula: ModalIRFormula) -> List[Tuple[str, str]]:
    source_family = _clean_text(formula.operator.family).lower()
    source_operator = _clean_text(formula.operator.symbol)
    if not source_family or not source_operator:
        return []
    slots: List[Tuple[str, str]] = [
        ("modal_family_transition_pair", f"{source_family}->{source_family}"),
        ("modal_operator_transition_pair", f"{source_operator}->{source_operator}"),
        ("modal_transition_signature", f"{source_family}:{source_operator}"),
    ]
    for cue in _formula_transition_cues(formula):
        source_signature = f"{source_family}:{source_operator}:{cue}"
        slots.append(("modal_transition_cue", cue))
        slots.append(("modal_transition_source_signature", source_signature))
        transition_pairs: List[Tuple[str, str]] = [(source_family, source_operator)]
        transition_pairs.extend(
            _augment_deontic_bridge_pairs(
                bridge_pairs=_cue_bridge_operator_pairs(cue),
                formula_family=source_family,
                formula_symbol=source_operator,
                cue=cue,
            )
        )
        for target_family, target_operator in transition_pairs:
            normalized_target_family = _clean_text(target_family).lower()
            normalized_target_operator = _clean_text(target_operator)
            if not normalized_target_family or not normalized_target_operator:
                continue
            family_pair = f"{source_family}->{normalized_target_family}"
            operator_pair = f"{source_operator}->{normalized_target_operator}"
            target_signature = (
                f"{normalized_target_family}:{normalized_target_operator}:{cue}"
            )
            slots.extend(
                (
                    ("modal_family_transition_pair", family_pair),
                    ("modal_family_transition_pair_cue", f"{family_pair}:{cue}"),
                    ("modal_operator_transition_pair", operator_pair),
                    ("modal_operator_transition_pair_cue", f"{operator_pair}:{cue}"),
                    ("modal_transition_signature", target_signature),
                    ("modal_transition_target_family", normalized_target_family),
                    ("modal_transition_target_operator", normalized_target_operator),
                )
            )
            slots.extend(
                _modal_operator_transition_signature_slots(
                    source_family=source_family,
                    source_system=formula.operator.system,
                    source_symbol=source_operator,
                    target_family=normalized_target_family,
                    target_symbol=normalized_target_operator,
                    slot_prefix="modal_transition",
                )
            )
    return _unique_slot_values(slots)


def _modal_polarity_slots(
    formula: ModalIRFormula,
    *,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    document: ModalIRDocument | None = None,
) -> List[Tuple[str, str]]:
    source_family = _clean_text(formula.operator.family).lower()
    source_operator = _clean_text(formula.operator.symbol)
    if not source_family or not source_operator:
        return []
    force = _modal_force_label(formula)
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=document,
    )
    scope = "conditioned" if condition_values or exception_values else "unconditioned"
    slots: List[Tuple[str, str]] = [
        ("modal_force", force),
        ("modal_scope_polarity", polarity),
        ("modal_force_scope", f"{force}:{scope}"),
        ("modal_polarity_scope", f"{polarity}:{scope}"),
        (
            "modal_force_polarity",
            f"{force}:{polarity}",
        ),
        (
            "modal_force_polarity_family",
            f"{force}:{polarity}:{source_family}",
        ),
        (
            "modal_force_polarity_signature",
            f"{force}:{polarity}:{source_family}:{source_operator.lower()}:{scope}",
        ),
    ]
    if polarity == "negative_scope":
        slots.extend(
            (
                ("compiler_contract_force_polarity", f"{force}:negative_scope"),
                (
                    "compiler_contract_force_polarity_family",
                    f"{force}:negative_scope:{source_family}",
                ),
                ("normative_polarity", "negative_scope"),
                ("normative_force_polarity", f"{force}:negative_scope"),
                ("normative_force_scope", f"{force}:{scope}"),
                ("normative_polarity_scope", f"negative_scope:{scope}"),
            )
        )
    if exception_values:
        slots.extend(
            (
                ("modal_exception_scope", "excepted"),
                ("modal_force_exception_scope", f"{force}:excepted"),
                ("modal_polarity_exception_scope", f"{polarity}:excepted"),
                ("normative_polarity_scope", f"{polarity}:excepted"),
                ("normative_force_scope", f"{force}:excepted"),
                ("normative_force_exception_scope", f"{force}:excepted"),
            )
        )
        if force == "obligation":
            slots.extend(
                (
                    ("normative_polarity_scope", "mandatory:excepted"),
                    ("normative_force_scope", "mandatory:excepted"),
                )
            )
        if polarity == "negative_scope":
            slots.extend(
                (
                    (
                        "compiler_contract_force_polarity_exception",
                        f"{force}:negative_scope:excepted",
                    ),
                    (
                        "logic_view_contract_deontic_slot",
                        f"{force}:negative_scope:deontic:{source_operator.lower()}",
                    ),
                    (
                        "logic_view_contract_deontic_slot_exception",
                        f"{force}:negative_scope:excepted:deontic:{source_operator.lower()}",
                    ),
                    ("normative_polarity_scope", "negative_scope:excepted"),
                )
            )
    return _unique_slot_values(slots)


def _modal_force_label(formula: ModalIRFormula) -> str:
    symbol = _clean_text(formula.operator.symbol)
    label = _clean_text(formula.operator.label).lower()
    metadata = formula.metadata if isinstance(formula.metadata, Mapping) else {}
    guided_force = _clean_text(
        metadata.get("compiler_guidance_deontic_force")
        or metadata.get("deontic_force")
        or metadata.get("force")
        or ""
    ).lower()
    if guided_force in {"permission", "obligation", "prohibition"}:
        return guided_force
    if symbol == "P" or label in {"permission", "permitted"}:
        return "permission"
    if symbol == "F" or label in {"prohibition", "prohibited", "forbidden"}:
        return "prohibition"
    if symbol in {"O", "O|"} or label in {
        "obligation",
        "obligatory",
        "conditional_obligation",
        "conditionally obligatory",
    }:
        return "obligation"
    return label.replace(" ", "_") or symbol.lower()


def _modal_scope_polarity(
    formula: ModalIRFormula,
    *,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
    document: ModalIRDocument | None = None,
) -> str:
    metadata = formula.metadata if isinstance(formula.metadata, Mapping) else {}
    guided_polarity = _clean_text(
        metadata.get("compiler_guidance_force_polarity")
        or metadata.get("force_polarity")
        or metadata.get("polarity")
        or ""
    ).lower()
    if guided_polarity in {"negative", "negative_scope", "negated"}:
        return "negative_scope"
    if guided_polarity in {"positive", "positive_scope", "affirmative"}:
        return "positive_scope"
    if _clean_text(formula.operator.symbol) == "F":
        return "negative_scope"
    polarity_text = " ".join(
        value
        for value in (
            _clean_text(formula.operator.label),
            _clean_text(metadata.get("cue") or ""),
            _predicate_phrase(formula),
            " ".join(_phrase_values(condition_values)),
            " ".join(_phrase_values(exception_values)),
            _semantic_source_span_text(document=document, formula=formula)
            if document is not None
            else "",
        )
        if value
    ).lower()
    if re.search(r"(?<!\w)(?:not|no|never|without|prohibited|forbidden)(?!\w)", polarity_text):
        return "negative_scope"
    return "positive_scope"


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
    alethic_symbol = _TEMPORAL_ALETHIC_BRIDGE_CUE_OPERATOR_SYMBOLS.get(normalized_cue)
    if alethic_symbol and ("alethic", alethic_symbol) not in pairs:
        pairs.append(("alethic", alethic_symbol))
    if (
        normalized_cue in _STRUCTURAL_FRAME_CUE_TOKENS
        and ("frame", "Frame") not in pairs
    ):
        pairs.append(("frame", "Frame"))
    if normalized_cue in _FRAME_REFINED_STATUS_DEONTIC_CUES:
        if ("deontic", "O") not in pairs:
            pairs.append(("deontic", "O"))
        if ("frame", "Frame") not in pairs:
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


def _should_emit_frame_structural_deontic_bridge(
    *,
    formula_family: str,
    cue: str,
    text: str,
) -> bool:
    if formula_family != "frame":
        return False
    normalized_cue = _clean_text(cue).lower()
    if normalized_cue not in _STRUCTURAL_FRAME_CUE_TOKENS:
        return False
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return False
    if _temporal_transition_context_cues_from_text(normalized_text):
        return True
    if _STATUTORY_SCOPE_REFERENCE_RE.search(normalized_text):
        return True
    structural_heading_cues = {
        token[:-1] if token.endswith("s") else token
        for token in _CUE_TOKEN_RE.findall(normalized_text)
        if token
    }
    if len(structural_heading_cues.intersection(_STRUCTURAL_FRAME_CUE_TOKENS)) >= 2:
        return True
    return (
        _FRAME_STRUCTURAL_DEONTIC_BRIDGE_TRIGGER_RE.search(normalized_text) is not None
    )


def _frame_status_keyword_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for cue_key in _FRAME_REFINED_STATUS_DEONTIC_CUES:
        cue_surface = cue_key.replace("_", " ")
        if cue_surface and _text_contains_cue_term(normalized_text, cue_surface):
            cues.append(cue_key)
    return cues


def _temporal_alethic_bridge_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for cue_key in sorted(
        _TEMPORAL_ALETHIC_BRIDGE_CUE_OPERATOR_SYMBOLS,
        key=lambda item: (-len(item.split("_")), -len(item), item),
    ):
        cue_surface = cue_key.replace("_", " ")
        if cue_surface and _text_contains_cue_term(normalized_text, cue_surface):
            cues.append(cue_key)
    return cues


def _refined_contextual_modal_cues_from_text(
    formula: ModalIRFormula,
    *,
    text: str,
) -> List[str]:
    formula_family = _clean_text(formula.operator.family).lower()
    temporal_context_cues = _temporal_transition_context_cues_from_text(text)
    cues: List[str] = []
    for cue in _contextual_modal_cues_from_text(formula, text=text):
        if cue and cue not in cues:
            cues.append(cue)
    for cue in _stem_refined_modal_cues_from_text(formula, text=text):
        if cue and cue not in cues:
            cues.append(cue)
    # Preserve explicit typed-IR cue semantics when source spans are clipped or
    # noisy; keep this conservative by only admitting cues recognized by the
    # bridge vocabulary.
    for cue in _formula_cues(formula):
        normalized_cue = _clean_text(cue).replace(" ", "_").lower()
        if (
            not normalized_cue
            or normalized_cue in cues
            or (
                normalized_cue not in _CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS
                and normalized_cue not in _registry_bridge_cue_keys()
            )
        ):
            continue
        cues.append(normalized_cue)
    # Preserve typed IR clause semantics even when source spans are noisy or
    # clipped; this keeps directional family-pair slots aligned with
    # condition/exception prefixes carried in IR.
    for cue in _formula_clause_prefix_cues(formula):
        if cue and cue not in cues:
            cues.append(cue)
    # Structural U.S.C. heading tokens such as "title"/"section" are useful
    # for frame formulas, but they over-trigger cross-family bridges for
    # non-frame formulas and dilute deontic/temporal slot semantics.
    if formula_family == "frame":
        for cue in _bridge_registry_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
        for cue in _structural_frame_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
        for cue in _frame_status_keyword_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
    elif formula_family == "temporal" and temporal_context_cues:
        # Temporal formulas often carry frame-like statute scaffolding tokens
        # ("title", "chapter", "subchapter") inside compilation spans.
        # Only admit those structural cues when the same text also has
        # temporal context so non-temporal noun noise stays filtered.
        for cue in _structural_frame_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
    elif formula_family == "temporal":
        for cue in _temporal_transition_context_cues_from_text(text):
            normalized_cue = _clean_text(cue).lower()
            if not normalized_cue or normalized_cue in cues:
                continue
            if (
                normalized_cue in _TEMPORAL_BRIDGE_CONTEXT_TOKENS
                or normalized_cue
                in {
                    "calendar_year",
                    "edition_year",
                    "effective_date",
                    "fiscal_year",
                    "no_later_than",
                    "not_later_than",
                    "on_and_after",
                    "on_or_after",
                    "year",
                }
            ):
                cues.append(normalized_cue)
    if formula_family == "temporal":
        for cue in _temporal_alethic_bridge_cues_from_text(text):
            if cue and cue not in cues:
                cues.append(cue)
    return cues


def _formula_clause_prefix_cues(formula: ModalIRFormula) -> List[str]:
    cues: List[str] = []
    for slot_name, clauses in (
        ("condition", formula.conditions),
        ("exception", formula.exceptions),
    ):
        for clause in clauses:
            parsed_clause = _typed_clause_slot(clause, slot=slot_name)
            if parsed_clause is None:
                continue
            _, prefix_key, _ = parsed_clause
            normalized_prefix = _clean_text(prefix_key).lower()
            if normalized_prefix and normalized_prefix not in cues:
                cues.append(normalized_prefix)
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
        bridge_pairs = list(_refined_cue_bridge_operator_pairs(normalized_cue))
        if _should_emit_frame_structural_deontic_bridge(
            formula_family=formula_family,
            cue=normalized_cue,
            text=text,
        ):
            bridge_pairs.append(("deontic", "O"))
        for bridge_family, bridge_symbol in _augment_deontic_bridge_pairs(
            bridge_pairs=bridge_pairs,
            formula_family=formula_family,
            formula_symbol=formula_symbol,
            cue=normalized_cue,
        ):
            pair = f"{formula_family}->{bridge_family}"
            pair_key = _slot_safe_family_pair_key(pair)
            operator_pair = f"{formula_symbol}->{bridge_symbol}"
            operator_pair_key = _modal_operator_pair_feature_key(
                formula_symbol,
                bridge_symbol,
            )
            bridge_signature = f"{bridge_family}:{bridge_symbol}:{normalized_cue}"
            slots.extend(
                (
                    (f"{normalized_slot_prefix}_refined_modal_family_pair", pair),
                    (f"{normalized_slot_prefix}_refined_modal_family_pair_key", pair_key),
                    (
                        f"{normalized_slot_prefix}_refined_modal_operator_pair",
                        operator_pair,
                    ),
                    (f"{normalized_slot_prefix}_refined_modal_pair_cue", f"{pair}:{normalized_cue}"),
                    (
                        f"{normalized_slot_prefix}_refined_modal_bridge_signature",
                        bridge_signature,
                    ),
                    ("refined_modal_family_pair", pair),
                    ("refined_modal_family_pair_key", pair_key),
                    ("refined_modal_operator_pair", operator_pair),
                    ("refined_modal_pair_cue", f"{pair}:{normalized_cue}"),
                    ("refined_modal_bridge_signature", bridge_signature),
                    ("refined_modal_context_slot", normalized_slot_prefix),
                    ("refined_modal_context_pair", f"{normalized_slot_prefix}:{pair}"),
                )
            )
            slots.extend(
                _modal_operator_transition_signature_slots(
                    source_family=formula_family,
                    source_system=formula.operator.system,
                    source_symbol=formula_symbol,
                    target_family=bridge_family,
                    target_symbol=bridge_symbol,
                    slot_prefix=f"{normalized_slot_prefix}_refined_modal",
                )
            )
            if operator_pair_key:
                slots.extend(
                    (
                        (
                            f"{normalized_slot_prefix}_refined_modal_operator_pair_key",
                            operator_pair_key,
                        ),
                        ("refined_modal_operator_pair_key", operator_pair_key),
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
    slots.extend(
        _refined_heading_transition_slots(
            formula=formula,
            text=text,
            slot_prefix=normalized_slot_prefix,
        )
    )
    return _unique_slot_values(slots)


def _typed_ir_refined_family_pair_slots(
    formula: ModalIRFormula,
) -> List[Tuple[str, str]]:
    formula_family = _clean_text(formula.operator.family).lower()
    formula_symbol = _clean_text(formula.operator.symbol)
    if not formula_family or not formula_symbol:
        return []
    slots: List[Tuple[str, str]] = []
    for target_family in _TYPED_IR_REFINED_FAMILY_PAIR_TARGETS.get(
        formula_family,
        (),
    ):
        target_symbol = _typed_ir_refined_target_symbol(
            target_family,
            fallback_symbol=formula_symbol,
        )
        pair = f"{formula_family}->{target_family}"
        pair_key = _slot_safe_family_pair_key(pair)
        operator_pair = f"{formula_symbol}->{target_symbol}"
        operator_pair_key = _modal_operator_pair_feature_key(
            formula_symbol,
            target_symbol,
        )
        signature = (
            f"{formula_family}:{formula_symbol}->"
            f"{target_family}:{target_symbol}:typed_ir"
        )
        slots.extend(
            (
                ("refined_modal_family_pair", pair),
                ("refined_modal_family_pair_key", pair_key),
                ("refined_modal_operator_pair", operator_pair),
                ("refined_modal_pair_cue", f"{pair}:typed_ir"),
                ("refined_modal_bridge_signature", signature),
                ("typed_ir_refined_modal_family_pair", pair),
                ("typed_ir_refined_modal_family_pair_key", pair_key),
                ("typed_ir_refined_modal_operator_pair", operator_pair),
                ("typed_ir_refined_modal_pair_cue", f"{pair}:typed_ir"),
                ("typed_ir_refined_modal_bridge_signature", signature),
                ("typed_ir_refined_modal_source_family", formula_family),
                ("typed_ir_refined_modal_target_family", target_family),
            )
        )
        if operator_pair_key:
            slots.extend(
                (
                    ("refined_modal_operator_pair_key", operator_pair_key),
                    ("typed_ir_refined_modal_operator_pair_key", operator_pair_key),
                )
            )
        if target_family == "temporal":
            slots.extend(
                (
                    ("refined_temporal_bridge_family_pair", pair),
                    ("refined_temporal_bridge_family_pair_key", pair_key),
                    ("refined_temporal_bridge_operator_pair", operator_pair),
                    ("refined_temporal_bridge_pair_cue", f"{pair}:typed_ir"),
                    ("refined_temporal_bridge_signature", signature),
                )
            )
        if target_family == "deontic" and formula_family in {"frame", "temporal"}:
            slots.extend(
                (
                    ("typed_ir_refined_deontic_bridge_family_pair", pair),
                    ("typed_ir_refined_deontic_bridge_signature", signature),
                )
            )
    return _unique_slot_values(slots)


def _typed_ir_refined_target_symbol(
    target_family: str,
    *,
    fallback_symbol: str,
) -> str:
    normalized_family = _clean_text(target_family).lower()
    if normalized_family == "conditional_normative":
        return "O|"
    if normalized_family == "deontic":
        return "O"
    if normalized_family == "frame":
        return "Frame"
    if normalized_family == "temporal":
        return fallback_symbol or "F"
    return fallback_symbol


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
    formula_symbol = _clean_text(formula.operator.symbol)
    if (
        not normalized_slot_prefix
        or not normalized_cue
        or formula_family not in {"deontic", "frame", "temporal"}
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
    elif formula_family == "temporal":
        if not (
            _temporal_clause_prefix_relation(normalized_cue)
            or normalized_cue in _TEMPORAL_BRIDGE_CONTEXT_TOKENS
            or normalized_cue in _STRUCTURAL_FRAME_CUE_TOKENS
            or normalized_cue in {
                "calendar_year",
                "edition_year",
                "effective_date",
                "fiscal_year",
                "no_later_than",
                "not_later_than",
                "on_and_after",
                "on_or_after",
            }
        ):
            return []

    temporal_symbol = formula_symbol if formula_family == "temporal" and formula_symbol else "F"
    bridge_targets: List[Tuple[str, str]] = []

    def add_bridge_target(family: str, symbol: str) -> None:
        normalized_family = _clean_text(family).lower()
        normalized_symbol = _clean_text(symbol)
        target = (normalized_family, normalized_symbol)
        if target[0] and target[1] and target not in bridge_targets:
            bridge_targets.append(target)

    add_bridge_target("temporal", temporal_symbol)
    if formula_family == "temporal":
        if normalized_cue in _DEONTIC_TEMPORAL_BRIDGE_CUES:
            add_bridge_target("deontic", "O")
        if normalized_cue in _STATUS_KEYWORD_BRIDGE_OPERATOR_PAIRS or normalized_cue in {
            "effective_date",
            "edition_year",
        }:
            add_bridge_target("epistemic", "K")

    slots: List[Tuple[str, str]] = []
    for bridge_family, bridge_symbol in bridge_targets:
        pair = f"{formula_family}->{bridge_family}"
        pair_key = _slot_safe_family_pair_key(pair)
        operator_pair = f"{formula_symbol}->{bridge_symbol}"
        operator_pair_key = _modal_operator_pair_feature_key(
            formula_symbol,
            bridge_symbol,
        )
        signature = f"{bridge_family}:{bridge_symbol}:{normalized_cue}"
        slots.extend(
            (
                (f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair", pair),
                (f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair_key", pair_key),
                (f"{normalized_slot_prefix}_refined_temporal_bridge_operator_pair", operator_pair),
                (f"{normalized_slot_prefix}_refined_temporal_bridge_signature", signature),
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_pair_cue",
                    f"{pair}:{normalized_cue}",
                ),
                ("refined_temporal_bridge_family_pair", pair),
                ("refined_temporal_bridge_family_pair_key", pair_key),
                ("refined_temporal_bridge_operator_pair", operator_pair),
                ("refined_temporal_bridge_signature", signature),
                ("refined_temporal_bridge_pair_cue", f"{pair}:{normalized_cue}"),
                ("refined_temporal_bridge_context_slot", normalized_slot_prefix),
                (
                    "refined_temporal_bridge_context_pair",
                    f"{normalized_slot_prefix}:{pair}",
                ),
            )
        )
        slots.extend(
            _modal_operator_transition_signature_slots(
                source_family=formula_family,
                source_system=formula.operator.system,
                source_symbol=formula_symbol,
                target_family=bridge_family,
                target_symbol=bridge_symbol,
                slot_prefix=f"{normalized_slot_prefix}_refined_temporal_bridge",
            )
        )
        if operator_pair_key:
            slots.extend(
                (
                    (
                        f"{normalized_slot_prefix}_refined_temporal_bridge_operator_pair_key",
                        operator_pair_key,
                    ),
                    ("refined_temporal_bridge_operator_pair_key", operator_pair_key),
                )
            )
    for context_cue in context_cues:
        for bridge_family, bridge_symbol in bridge_targets:
            signature = f"{bridge_family}:{bridge_symbol}:{normalized_cue}"
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
    slots.extend(
        _refined_temporal_to_deontic_transition_slots(
            formula=formula,
            cue=normalized_cue,
            text=text,
            context_cues=context_cues,
            slot_prefix=normalized_slot_prefix,
        )
    )
    return _unique_slot_values(slots)


def _refined_temporal_to_deontic_transition_slots(
    *,
    formula: ModalIRFormula,
    cue: str,
    text: str,
    context_cues: Sequence[str],
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    formula_family = _clean_text(formula.operator.family).lower()
    formula_symbol = _clean_text(formula.operator.symbol)
    normalized_slot_prefix = _clean_text(slot_prefix)
    normalized_cue = _clean_text(cue).lower()
    if (
        not formula_family
        or not formula_symbol
        or not normalized_slot_prefix
        or not normalized_cue
        or formula_family not in {"frame", "temporal"}
    ):
        return []

    deontic_pairs: List[Tuple[str, str]] = []
    candidate_cues = [normalized_cue, *(_clean_text(item).lower() for item in context_cues)]
    for cue_value in candidate_cues:
        if not cue_value:
            continue
        for family, symbol in _augment_deontic_bridge_pairs(
            bridge_pairs=_refined_cue_bridge_operator_pairs(cue_value),
            formula_family=formula_family,
            formula_symbol=formula_symbol,
            cue=cue_value,
        ):
            if family != "deontic":
                continue
            pair = (family, symbol)
            if pair not in deontic_pairs:
                deontic_pairs.append(pair)

    if not deontic_pairs:
        normalized_text = _clean_text(text).replace("_", " ").lower()
        if (
            normalized_text
            and _FRAME_STRUCTURAL_DEONTIC_BRIDGE_TRIGGER_RE.search(normalized_text)
        ):
            deontic_pairs.append(("deontic", "O"))
    if not deontic_pairs:
        return []

    slots: List[Tuple[str, str]] = []
    family_pair = f"{formula_family}->deontic"
    family_pair_key = _slot_safe_family_pair_key(family_pair)
    for _, deontic_symbol in deontic_pairs:
        operator_pair = f"{formula_symbol}->{deontic_symbol}"
        operator_pair_key = _modal_operator_pair_feature_key(
            formula_symbol,
            deontic_symbol,
        )
        bridge_signature = f"deontic:{deontic_symbol}:{normalized_cue}"
        slots.extend(
            (
                (f"{normalized_slot_prefix}_refined_modal_family_pair", family_pair),
                (
                    f"{normalized_slot_prefix}_refined_modal_family_pair_key",
                    family_pair_key,
                ),
                (
                    f"{normalized_slot_prefix}_refined_modal_operator_pair",
                    operator_pair,
                ),
                (f"{normalized_slot_prefix}_refined_modal_pair_cue", f"{family_pair}:{normalized_cue}"),
                (
                    f"{normalized_slot_prefix}_refined_modal_bridge_signature",
                    bridge_signature,
                ),
                ("refined_modal_family_pair", family_pair),
                ("refined_modal_family_pair_key", family_pair_key),
                ("refined_modal_operator_pair", operator_pair),
                ("refined_modal_pair_cue", f"{family_pair}:{normalized_cue}"),
                ("refined_modal_bridge_signature", bridge_signature),
                ("refined_modal_context_slot", normalized_slot_prefix),
                ("refined_modal_context_pair", f"{normalized_slot_prefix}:{family_pair}"),
            )
        )
        slots.extend(
            _modal_operator_transition_signature_slots(
                source_family=formula_family,
                source_system=formula.operator.system,
                source_symbol=formula_symbol,
                target_family="deontic",
                target_symbol=deontic_symbol,
                slot_prefix=f"{normalized_slot_prefix}_refined_modal",
            )
        )
        if operator_pair_key:
            slots.extend(
                (
                    (
                        f"{normalized_slot_prefix}_refined_modal_operator_pair_key",
                        operator_pair_key,
                    ),
                    ("refined_modal_operator_pair_key", operator_pair_key),
                )
            )
    return _unique_slot_values(slots)


def _refined_heading_bridge_pairs_from_text(
    text: str,
) -> List[Tuple[str, str, str]]:
    normalized_text = _clean_text(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    pairs: List[Tuple[str, str, str]] = []
    for cue_key in sorted(
        _REFINED_HEADING_BRIDGE_CUE_OPERATOR_PAIRS,
        key=lambda item: (-len(item), item),
    ):
        cue_surface = cue_key.replace("_", " ")
        if (
            not cue_surface
            or re.search(rf"(?<!\w){re.escape(cue_surface)}(?!\w)", normalized_text)
            is None
        ):
            continue
        for target_family, target_symbol in _REFINED_HEADING_BRIDGE_CUE_OPERATOR_PAIRS[
            cue_key
        ]:
            normalized_family = _clean_text(target_family).lower()
            normalized_symbol = _clean_text(target_symbol)
            if not normalized_family or not normalized_symbol:
                continue
            pair = (cue_key, normalized_family, normalized_symbol)
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def _refined_heading_transition_slots(
    *,
    formula: ModalIRFormula,
    text: str,
    slot_prefix: str,
) -> List[Tuple[str, str]]:
    normalized_slot_prefix = _clean_text(slot_prefix)
    formula_family = _clean_text(formula.operator.family).lower()
    if (
        not normalized_slot_prefix
        or formula_family not in _REFINED_HEADING_BRIDGE_SOURCE_FAMILIES
    ):
        return []
    slots: List[Tuple[str, str]] = []
    for cue_key, target_family, target_symbol in _refined_heading_bridge_pairs_from_text(
        text
    ):
        pair = f"{formula_family}->{target_family}"
        signature = f"{target_family}:{target_symbol}:{cue_key}"
        pair_cue = f"{pair}:{cue_key}"
        slots.extend(
            (
                (f"{normalized_slot_prefix}_refined_heading_bridge_cue", cue_key),
                (f"{normalized_slot_prefix}_refined_heading_bridge_family_pair", pair),
                (f"{normalized_slot_prefix}_refined_heading_bridge_signature", signature),
                (f"{normalized_slot_prefix}_refined_heading_bridge_pair_cue", pair_cue),
                ("refined_heading_bridge_cue", cue_key),
                ("refined_heading_bridge_family_pair", pair),
                ("refined_heading_bridge_signature", signature),
                ("refined_heading_bridge_pair_cue", pair_cue),
                ("refined_heading_bridge_context_slot", normalized_slot_prefix),
                ("refined_heading_bridge_context_pair", f"{normalized_slot_prefix}:{pair}"),
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


def _status_keyword_modal_slots(
    formula: ModalIRFormula,
    *,
    status_keyword: str,
    slot_prefix: str = "status_keyword_modal",
) -> List[Tuple[str, str]]:
    normalized_keyword = _clean_text(status_keyword).lower().replace(" ", "_")
    normalized_slot_prefix = _clean_text(slot_prefix)
    formula_family = _clean_text(formula.operator.family).lower()
    formula_symbol = _clean_text(formula.operator.symbol)
    if (
        not normalized_keyword
        or not normalized_slot_prefix
        or not formula_family
        or not formula_symbol
    ):
        return []
    slots: List[Tuple[str, str]] = list(
        _modal_lexeme_slots(
            formula,
            cue=normalized_keyword,
            slot_prefix=normalized_slot_prefix,
        )
    )
    for bridge_family, bridge_symbol in _STATUS_KEYWORD_BRIDGE_OPERATOR_PAIRS.get(
        normalized_keyword,
        (),
    ):
        normalized_bridge_family = _clean_text(bridge_family).lower()
        normalized_bridge_symbol = _clean_text(bridge_symbol)
        if not normalized_bridge_family or not normalized_bridge_symbol:
            continue
        bridge_signature = (
            f"{normalized_bridge_family}:{normalized_bridge_symbol}:{normalized_keyword}"
        )
        family_pair = f"{formula_family}->{normalized_bridge_family}"
        family_pair_key = _slot_safe_family_pair_key(family_pair)
        operator_pair = f"{formula_symbol}->{normalized_bridge_symbol}"
        slots.extend(
            (
                (
                    f"{normalized_slot_prefix}_status_bridge_family",
                    normalized_bridge_family,
                ),
                (
                    f"{normalized_slot_prefix}_status_bridge_operator",
                    normalized_bridge_symbol,
                ),
                (
                    f"{normalized_slot_prefix}_status_bridge_signature",
                    bridge_signature,
                ),
                (
                    f"{normalized_slot_prefix}_status_bridge_family_pair",
                    family_pair,
                ),
                (
                    f"{normalized_slot_prefix}_status_bridge_family_pair_key",
                    family_pair_key,
                ),
                (
                    f"{normalized_slot_prefix}_status_bridge_operator_pair",
                    operator_pair,
                ),
                (
                    f"{normalized_slot_prefix}_status_bridge_pair_cue",
                    f"{family_pair}:{normalized_keyword}",
                ),
                (
                    f"{normalized_slot_prefix}_status_bridge_{normalized_bridge_family}",
                    f"{normalized_bridge_symbol}:{normalized_keyword}",
                ),
            )
        )
    return _unique_slot_values(slots)


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
