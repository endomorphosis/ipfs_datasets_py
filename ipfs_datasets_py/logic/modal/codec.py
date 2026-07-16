"""Deterministic modal logic codec with BM25 frame-logic grounding.

This module is the canonical logic-layer facade for the legal modal
encoder/IR/decoder path.  It intentionally keeps LLM usage at zero: modal
operators come from the deterministic registry, ontology frames are selected
with BM25, decoded vectors come from stable spaCy-derived feature hashing, and
F-logic is used as a consistency check over the intermediate representation.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ipfs_datasets_py.logic.flogic_optimizer import (
    FLogicOptimizerConfig,
    FLogicOptimizerResult,
    FLogicSemanticOptimizer,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    BM25FrameSelector,
    DEFAULT_LEGAL_FRAME_FIXTURE,
    FrameCandidate,
    FrameSelection,
    frame_ontology_feature_value,
    frame_ontology_feature_keys,
    frame_ontology_feature_keys_from_values,
    frame_ontology_contextualized_terms,
    frame_ontology_high_signal_terms,
    frame_ontology_terms,
    frame_ontology_terms_from_feature_keys,
    frame_ontology_terms_from_triples,
    is_high_signal_frame_ontology_term,
    normalize_frame_ontology_term,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import (
    LegalModalParser,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
    stable_mock_embedding,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    cosine_loss,
    cosine_similarity,
    cross_entropy_excess_distribution_loss,
    cross_entropy_distribution_loss,
    distribution_entropy_loss,
    mse_loss,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrame,
    ModalIRFrameLogic,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    ModalRegistry,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoder,
    SpaCyLegalEncoding,
    SpaCyModalDecoder,
    SpaCyModalIRCompiler,
)
from .decompiler import (
    DecodedModalPhrase,
    DecodedModalText,
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
    _legal_semantic_atoms_from_text,
    _modal_force_label,
    _modal_polarity_slots,
    _modal_scope_polarity,
    _typed_decompiler_role_slots,
    _typed_ir_scope_frame_texts,
    _uscode_status_clause_text,
    modal_text_token_similarity,
)
from .kg_bridge import (
    flogic_ontology_to_dict,
    flogic_triples_to_graph_data,
    flogic_triples_to_ontology,
)

_SLOT_FEATURE_EXCLUDED_SLOTS = frozenset(
    {
        "formula",
        "modal_source_span",
        "source_context_span",
    }
)
_SOURCE_COPY_SLOT_PREFIXES = (
    "modal_source_span",
    "source_context_span",
)
_COMPILER_GUIDANCE_MAX_FEATURES = 32
_COMPILER_GUIDANCE_MAX_GROUP_FEATURES = 16
_COMPILER_GUIDANCE_MAX_EMBEDDING_VALUES = 32
_COMPILER_GUIDANCE_FRAME_BOOST_CAP = 1.5
_COMPILER_GUIDANCE_FRAME_AUDIT_FEATURE_KEYS = (
    "frame_feature",
    "frame_feature_key",
    "frame_feature_keys",
    "frame_features",
    "top_embedding_features",
    "top_family_features",
    "top_predicted_views",
    "top_target_views",
)
_COMPILER_GUIDANCE_FRAME_AUDIT_STAGE_KEYS = (
    "pipeline_stage",
    "pipeline_stage_focus",
    "primary_pipeline_stage",
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
    ("in connection with", "in_connection_with"),
    ("in order to", "in_order_to"),
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
    ("including", "including"),
    ("includes", "includes"),
    ("include", "include"),
    ("pursuant to", "pursuant_to"),
    ("to the extent", "to_the_extent"),
    ("to the extent provided", "to_the_extent_provided"),
    ("not later than", "not_later_than"),
    ("no later than", "no_later_than"),
    ("not later", "not_later"),
    ("no later", "no_later"),
    ("only after", "only_after"),
    ("which", "which"),
    ("if", "if"),
    ("when", "when"),
    ("until", "until"),
    ("within", "within"),
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
    "only_after": "after",
    "before": "before",
    "by": "deadline",
    "no_later_than": "deadline",
    "not_later_than": "deadline",
    "within": "deadline",
    "upon": "after",
}
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
_USCODE_CATCHLINE_BODY_START_RE = re.compile(
    r"\s+(?=(?:\([a-z0-9]+\)\s+|For\s+purposes\s+of\b|On\s+and\s+after\b|"
    r"No\s+\w+\b|The\s+\w+\b|A\s+\w+\b|An\s+\w+\b))",
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
_CANONICAL_MODAL_OPERATOR_LABELS: Mapping[tuple[str, str], str] = {
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
    "only_after": (
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
    "conditional_normative": ("deontic",),
    "deontic": ("conditional_normative", "deontic", "frame", "temporal"),
    "frame": ("conditional_normative", "deontic", "doxastic", "frame", "temporal"),
    "temporal": ("conditional_normative", "deontic", "epistemic", "temporal"),
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
_EPISTEMIC_DEONTIC_BRIDGE_CUES: frozenset[str] = frozenset(
    {
        "determine",
        "determines",
        "determined",
        "determining",
        "find",
        "finds",
        "finding",
        "reason_to_believe",
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
        "frame",
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
_STRUCTURAL_HEADING_SPAN_RE = re.compile(
    rf"(?<!\w)(?:{_STATUTORY_SCOPE_UNIT_PATTERN})\s+"
    rf"(?:\d+[a-z]?|[ivxlcdm]+|[a-z])\b",
    re.IGNORECASE,
)
_SLOT_FEATURE_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_CUE_TOKEN_RE = re.compile(r"[a-z0-9]+")
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
_FRAME_ONTOLOGY_AUDIT_MAX_FEATURE_KEYS = 1024
_FRAME_ONTOLOGY_AUDIT_MAX_TERMS = 256
_FRAME_ONTOLOGY_METADATA_VALUE_KEYS = frozenset(
    {
        "candidate_term",
        "candidate_terms",
        "citation",
        "citations",
        "evidence",
        "evidences",
        "feature",
        "frame_feature",
        "frame_feature_key",
        "frame_feature_keys",
        "frame_features",
        "feature_key",
        "feature_keys",
        "features",
        "frame",
        "frame_term",
        "frame_terms",
        "frames",
        "items",
        "label",
        "labels",
        "matched_term",
        "matched_terms",
        "name",
        "names",
        "pipeline_stage",
        "pipeline_stage_focus",
        "primary_pipeline_stage",
        "sample",
        "sample_id",
        "sample_ids",
        "samples",
        "selected_term",
        "selected_terms",
        "source_id",
        "source_ids",
        "top_embedding_contributions",
        "term",
        "terms",
        "text",
        "texts",
        "hint_evidence",
        "top_embedding_features",
        "top_family_contributions",
        "top_family_features",
        "value",
        "values",
    }
)
_FRAME_ONTOLOGY_METADATA_STRUCTURAL_KEYS = frozenset(
    {
        "citation",
        "citations",
        "confidence",
        "count",
        "counts",
        "evidence",
        "evidences",
        "hint",
        "hint_id",
        "hint_ids",
        "hints",
        "id",
        "ids",
        "metadata",
        "priority",
        "probability",
        "rank",
        "ranking",
        "sample",
        "sample_id",
        "sample_ids",
        "samples",
        "score",
        "scores",
        "source_id",
        "source_ids",
        "weight",
        "weights",
    }
)
_FRAME_ONTOLOGY_METADATA_MAX_DEPTH = 6
_FRAME_ONTOLOGY_METADATA_MAX_VALUES = 256
_FRAME_ONTOLOGY_METADATA_OPAQUE_ID_HEX_RE = re.compile(
    r"[0-9a-f]{12,}",
    re.IGNORECASE,
)
_FLOGIC_ONTOLOGY_GUIDANCE_ROUTES = frozenset(
    {
        "audit_frame_logic_terms",
        "improve_flogic_frame_alignment",
        "repair_flogic_ontology_constraints",
    }
)
_FLOGIC_ONTOLOGY_GUIDANCE_FEATURES = (
    "legal-ir-view:modal.frame_logic",
    "legal-ir-view:deontic.ir",
    "legal-ir-view:CEC.native",
    "legal-ir-view:knowledge_graphs.neo4j_compat",
    "legal-ir-view:TDFOL.prover",
    "flogic:statement_hint:audit_frame_logic_terms",
    "flogic:statement_hint:improve_flogic_frame_alignment",
    "flogic:statement_hint:repair_flogic_ontology_constraints",
    "flogic:statement_hint:modal_frame_logic",
    "flogic:modal_family:frame",
)
_STATUTORY_FRAME_SUPPORT_FLOGIC_LOSS_SCALE = 0.30
_FRAME_LOGIC_ALIGNMENT_FLOGIC_LOSS_SCALE = 0.85


@dataclass(frozen=True)
class ModalLogicCodecConfig:
    """Configuration for the deterministic modal logic codec."""

    parser_backend: str = "spacy"
    spacy_model_name: str = "en_core_web_sm"
    embedding_dimensions: int = 8
    top_k_frames: int = 3
    frame_domain: Optional[str] = None
    use_flogic: bool = True
    flogic_similarity_threshold: float = 0.0
    ontology_name: str = "modal_legal_ontology"


@dataclass(frozen=True)
class ModalLogicCodecResult:
    """One deterministic legal modal encode/IR/decode pass."""

    source_text: str
    normalized_text: str
    parser_name: str
    encoding: SpaCyLegalEncoding
    modal_ir: ModalIRDocument
    source_embedding: List[float]
    decoded_embedding: List[float]
    family_logits: Dict[str, float]
    family_probabilities: Dict[str, float]
    target_family: str
    target_family_distribution: Dict[str, float]
    frame_candidates: List[Dict[str, Any]]
    selected_frame: Optional[str]
    kg_triples: List[Dict[str, str]]
    flogic_ontology: Any
    neo4j_graph_data: Any
    decoded_modal_text: DecodedModalText
    decoded_text: str
    losses: Dict[str, float]
    flogic_result: Optional[FLogicOptimizerResult] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable JSON-ready representation."""
        return {
            "decoded_embedding": list(self.decoded_embedding),
            "decoded_modal_text": self.decoded_modal_text.to_dict(),
            "decoded_text": self.decoded_text,
            "encoding": self.encoding.to_dict(),
            "family_logits": dict(sorted(self.family_logits.items())),
            "family_probabilities": dict(sorted(self.family_probabilities.items())),
            "flogic_ontology": flogic_ontology_to_dict(self.flogic_ontology)
            if self.flogic_ontology is not None
            else None,
            "flogic_result": _flogic_result_to_dict(self.flogic_result),
            "frame_candidates": list(self.frame_candidates),
            "kg_triples": list(self.kg_triples),
            "losses": dict(sorted(self.losses.items())),
            "metadata": dict(sorted(self.metadata.items())),
            "modal_ir": self.modal_ir.to_dict(),
            "neo4j_graph_data": _object_to_dict(self.neo4j_graph_data),
            "normalized_text": self.normalized_text,
            "parser_name": self.parser_name,
            "selected_frame": self.selected_frame,
            "source_embedding": list(self.source_embedding),
            "source_text": self.source_text,
            "target_family": self.target_family,
            "target_family_distribution": dict(sorted(self.target_family_distribution.items())),
        }


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _numeric_distribution(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    weights: Dict[str, float] = {}
    for key, raw_weight in value.items():
        weight = max(0.0, _safe_float(raw_weight))
        if weight > 0.0:
            weights[str(key)] = weight
    total = sum(weights.values())
    if total <= 0.0:
        return {}
    return {
        key: round(weight / total, 12)
        for key, weight in sorted(weights.items())
    }


def _numeric_signed_mapping(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    weights: Dict[str, float] = {}
    for key, raw_weight in value.items():
        weight = _safe_float(raw_weight)
        if abs(weight) > 1.0e-12:
            weights[str(key)] = round(weight, 12)
    return dict(sorted(weights.items()))


def _guidance_feature_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("feature") or value.get("name") or "").strip()
    return str(value or "").strip()


def _guidance_feature_list(value: Any, *, limit: int) -> List[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        iterable: Iterable[Any] = value.values()
    elif isinstance(value, (str, bytes)):
        iterable = [value]
    else:
        try:
            iterable = list(value)
        except TypeError:
            iterable = [value]
    features: List[str] = []
    for item in iterable:
        feature = _guidance_feature_value(item)
        if feature:
            features.append(feature)
        if limit > 0 and len(features) >= limit:
            break
    return _unique_preserve_order(features)


_GRAPH_PROJECTION_GUIDANCE_ROUTE = "repair_multiview_legal_ir_graph_projection"
_NEO4J_COMPAT_TARGET_COMPONENT = "knowledge_graphs.neo4j_compat"
_MODAL_FRAME_LOGIC_TARGET_COMPONENT = "modal.frame_logic"


def _compiler_guidance_bundle_mapping(
    compiler_guidance: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return compact bundle metadata from parsed or JSON-string guidance."""
    for key in (
        "bundle",
        "semantic_bundle",
        "semantic_bundle_key",
        "compiler_guidance_bundle",
        "vector_bundle",
    ):
        raw_bundle = compiler_guidance.get(key)
        if isinstance(raw_bundle, Mapping):
            return raw_bundle
        if isinstance(raw_bundle, str) and raw_bundle.strip():
            try:
                decoded = json.loads(raw_bundle)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, Mapping):
                return decoded
    return {}


def _compiler_guidance_route_features(
    compiler_guidance: Mapping[str, Any],
) -> List[str]:
    """Extract route/target/frame evidence from compact compiler guidance."""
    routes: List[str] = []
    for routes_key in ("compiler_guidance_todo_routes", "todo_routes", "routes"):
        raw_routes = compiler_guidance.get(routes_key)
        if isinstance(raw_routes, Mapping):
            routes.extend(str(route) for route in raw_routes if str(route or "").strip())
        else:
            routes.extend(_guidance_feature_list(raw_routes, limit=0))
    for route_key in (
        "compiler_guidance_route",
        "route",
        "compiler_guidance_action",
        "action",
        "original_action",
        "failed_action",
        "failed_todo_action",
    ):
        route = str(compiler_guidance.get(route_key) or "").strip()
        if route:
            routes.append(route)
    for sample_key in ("sample", "samples", "sample_id", "sample_ids"):
        for sample in _guidance_feature_list(
            compiler_guidance.get(sample_key),
            limit=0,
        ):
            route = _compiler_guidance_route_name(sample)
            if route:
                routes.append(route)
    routes.extend(_compiler_guidance_routes_from_view_gaps(compiler_guidance))

    features = [f"compiler-guidance-route:{route}" for route in routes]
    target_component = str(
        compiler_guidance.get("target_component")
        or compiler_guidance.get("target")
        or ""
    ).strip()
    raw_bundle = _compiler_guidance_bundle_mapping(compiler_guidance)
    if raw_bundle:
        bundle_route = str(
            raw_bundle.get("route")
            or raw_bundle.get("action")
            or raw_bundle.get("original_action")
            or raw_bundle.get("failed_action")
            or raw_bundle.get("failed_todo_action")
            or ""
        ).strip()
        if bundle_route:
            features.append(f"compiler-guidance-route:{bundle_route}")
        if not target_component:
            target_component = str(
                raw_bundle.get("target_component") or raw_bundle.get("target") or ""
            ).strip()
    if target_component:
        features.append(f"target-component:{target_component}")

    for frame in _compiler_guidance_selected_frame_evidence(compiler_guidance):
        features.append(f"selected_ontology_frame:{frame}")
    raw_evidence = compiler_guidance.get("evidence")
    if raw_evidence is None:
        raw_evidence = compiler_guidance.get("evidences")
    if isinstance(raw_evidence, Mapping):
        evidence_items: Iterable[Any] = [raw_evidence]
    elif isinstance(raw_evidence, Sequence) and not isinstance(
        raw_evidence,
        (str, bytes),
    ):
        evidence_items = raw_evidence
    else:
        evidence_items = []
    for item in evidence_items:
        if not isinstance(item, Mapping):
            continue
        route = str(
            item.get("compiler_guidance_route")
            or item.get("route")
            or item.get("action")
            or item.get("original_action")
            or item.get("failed_action")
            or item.get("failed_todo_action")
            or ""
        ).strip()
        if route:
            features.append(f"compiler-guidance-route:{route}")
    return _unique_preserve_order(features)


def _compiler_guidance_route_name(value: Any) -> str:
    """Normalize compact compiler-guidance route markers to route names."""
    normalized = _clean_non_empty_string(value).lower()
    for prefix in ("compiler-guidance-route:", "compiler-guidance:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
            break
    return normalized


def _compiler_guidance_routes_from_view_gaps(
    compiler_guidance: Mapping[str, Any],
) -> List[str]:
    """Infer repair routes from compiler-guidance LegalIR view-gap evidence."""
    routes: List[str] = []
    for gap_key in (
        "compiler_guidance_legal_ir_view_gaps",
        "compiler_guidance_legal_ir_view_family_gaps",
        "legal_ir_view_gaps",
        "legal_ir_view_family_gaps",
    ):
        raw_gaps = compiler_guidance.get(gap_key)
        if not isinstance(raw_gaps, Mapping):
            continue
        for gap_name, raw_weight in sorted(raw_gaps.items()):
            if (
                _compiler_guidance_gap_weight(raw_weight) <= 0.0
                or not _compiler_guidance_gap_quality_passes(raw_weight)
            ):
                continue
            route = _compiler_guidance_route_from_view_gap(str(gap_name))
            if route:
                routes.append(route)
    return _unique_preserve_order(routes)


def _compiler_guidance_route_from_view_gap(gap_name: str) -> str:
    """Map LegalIR view-gap labels onto deterministic bridge repair routes."""
    normalized = _clean_non_empty_string(gap_name).lower()
    normalized = normalized.replace(".", "_").replace("-", "_")
    if "deontic" in normalized:
        return "repair_deontic_bridge_quality_gate"
    if "frame" in normalized or "flogic" in normalized:
        return "repair_flogic_ontology_constraints"
    if "knowledge_graph" in normalized or normalized.startswith("kg_"):
        return _GRAPH_PROJECTION_GUIDANCE_ROUTE
    if "tdfol" in normalized or "first_order" in normalized:
        return "repair_tdfol_bridge_parse"
    if "cec" in normalized or "event_calculus" in normalized:
        return "repair_cec_dcec_bridge"
    if "prover" in normalized:
        return "repair_external_prover_router"
    if "zkp" in normalized or "zero_knowledge" in normalized:
        return "repair_zkp_attestation_bridge"
    return ""


def _compiler_guidance_view_gap_features(
    compiler_guidance: Mapping[str, Any],
) -> List[str]:
    """Return deterministic ontology feature strings for LegalIR gap evidence."""
    features: List[str] = []
    for gap_key in (
        "compiler_guidance_legal_ir_view_gaps",
        "compiler_guidance_legal_ir_view_family_gaps",
        "legal_ir_view_gaps",
        "legal_ir_view_family_gaps",
    ):
        raw_gaps = compiler_guidance.get(gap_key)
        if not isinstance(raw_gaps, Mapping):
            continue
        for gap_name, raw_weight in sorted(raw_gaps.items()):
            if (
                _compiler_guidance_gap_weight(raw_weight) <= 0.0
                or not _compiler_guidance_gap_quality_passes(raw_weight)
            ):
                continue
            safe_gap = _clean_non_empty_string(gap_name).replace(".", "_")
            if safe_gap:
                features.append(f"legal-ir-view-gap:{safe_gap}")
    return _unique_preserve_order(features)


def _compiler_guidance_gap_weight(value: Any) -> float:
    if isinstance(value, Mapping):
        return _safe_float(
            value.get("count")
            or value.get("support")
            or value.get("weight")
            or value.get("score")
        )
    return _safe_float(value)


def _compiler_guidance_gap_quality_passes(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return True
    quality_gate = _clean_non_empty_string(value.get("quality_gate")).lower()
    return not quality_gate or quality_gate == "pass"


def _compiler_guidance_selected_frame_evidence(
    compiler_guidance: Mapping[str, Any],
) -> List[str]:
    frames: List[str] = []
    for key in (
        "selected_frame",
        "selected_frame_after",
        "compiler_guidance_selected_frame_after",
    ):
        frame = str(compiler_guidance.get(key) or "").strip()
        if frame:
            frames.append(frame)

    raw_evidence = compiler_guidance.get("evidence")
    if raw_evidence is None:
        raw_evidence = compiler_guidance.get("evidences")
    if isinstance(raw_evidence, Mapping):
        evidence_items: Iterable[Any] = [raw_evidence]
    elif isinstance(raw_evidence, Sequence) and not isinstance(raw_evidence, (str, bytes)):
        evidence_items = raw_evidence
    else:
        evidence_items = []
    for item in evidence_items:
        if not isinstance(item, Mapping):
            continue
        for key in ("selected_frame_after", "selected_frame", "selected_frame_before"):
            frame = str(item.get(key) or "").strip()
            if frame:
                frames.append(frame)
    return _unique_preserve_order(frames)


def _compiler_guidance_implies_neo4j_projection_target(
    compiler_guidance: Mapping[str, Any],
) -> bool:
    route_values = _compiler_guidance_route_features(compiler_guidance)
    has_graph_projection_route = any(
        _GRAPH_PROJECTION_GUIDANCE_ROUTE in value for value in route_values
    )
    if not has_graph_projection_route:
        return False
    target_component = str(
        compiler_guidance.get("target_component")
        or compiler_guidance.get("target")
        or ""
    ).strip()
    raw_bundle = _compiler_guidance_bundle_mapping(compiler_guidance)
    if not target_component and raw_bundle:
        target_component = str(
            raw_bundle.get("target_component") or raw_bundle.get("target") or ""
        ).strip()
    return not target_component or target_component == _NEO4J_COMPAT_TARGET_COMPONENT


def _compiler_guidance_frame_logic_target_routes(
    compiler_guidance: Mapping[str, Any],
) -> List[str]:
    """Return frame-logic repair routes encoded in packet-shaped guidance."""
    if not isinstance(compiler_guidance, Mapping):
        return []
    routes: List[str] = []
    for feature in _compiler_guidance_route_features(compiler_guidance):
        normalized = _compiler_guidance_route_name(feature)
        if normalized in _FLOGIC_ONTOLOGY_GUIDANCE_ROUTES:
            routes.append(normalized)
    if (
        not routes
        and _compiler_guidance_has_frame_logic_view_signal(compiler_guidance)
    ):
        routes.append("audit_frame_logic_terms")
    return _unique_preserve_order(routes)


def _compiler_guidance_implies_frame_logic_target(
    compiler_guidance: Mapping[str, Any],
) -> bool:
    """Return true when compact guidance targets the modal frame-logic view."""
    if _compiler_guidance_frame_logic_target_routes(compiler_guidance):
        return True
    target_component = str(
        compiler_guidance.get("target_component")
        or compiler_guidance.get("target")
        or ""
    ).strip()
    raw_bundle = _compiler_guidance_bundle_mapping(compiler_guidance)
    if not target_component and raw_bundle:
        target_component = str(
            raw_bundle.get("target_component") or raw_bundle.get("target") or ""
        ).strip()
    return target_component == _MODAL_FRAME_LOGIC_TARGET_COMPONENT


def _compiler_guidance_has_frame_logic_view_signal(
    compiler_guidance: Mapping[str, Any],
) -> bool:
    """Return true for packet evidence that targets the modal frame-logic view."""
    if not isinstance(compiler_guidance, Mapping):
        return False
    target_component = str(compiler_guidance.get("target_component") or "").strip()
    raw_bundle = compiler_guidance.get("bundle")
    if not isinstance(raw_bundle, Mapping):
        raw_bundle = compiler_guidance.get("semantic_bundle")
    if not target_component and isinstance(raw_bundle, Mapping):
        target_component = str(raw_bundle.get("target_component") or "").strip()
    if target_component == _MODAL_FRAME_LOGIC_TARGET_COMPONENT:
        return True
    for distribution_key in (
        "compiler_guidance_legal_ir_target_view_distribution",
        "compiler_guidance_legal_ir_view_gap_distribution",
        "legal_ir_target_view_distribution",
        "legal_ir_view_gap_distribution",
    ):
        raw_distribution = compiler_guidance.get(distribution_key)
        if isinstance(raw_distribution, Mapping):
            for key in raw_distribution:
                if str(key or "").strip() == _MODAL_FRAME_LOGIC_TARGET_COMPONENT:
                    return True
    for feature in _compiler_guidance_nested_feature_strings(
        [
            compiler_guidance.get("compiler_guidance_feature_groups"),
            compiler_guidance.get("compiler_guidance_ranked_features"),
            compiler_guidance.get("evidence"),
            compiler_guidance.get("evidences"),
            compiler_guidance.get("feature_groups"),
            compiler_guidance.get("frame_features"),
            compiler_guidance.get("top_family_features"),
        ]
    ):
        normalized = _clean_non_empty_string(feature).lower()
        if normalized in {
            _MODAL_FRAME_LOGIC_TARGET_COMPONENT,
            f"legal-ir-view:{_MODAL_FRAME_LOGIC_TARGET_COMPONENT}",
            f"legal_ir_view:{_MODAL_FRAME_LOGIC_TARGET_COMPONENT}",
            f"target-component:{_MODAL_FRAME_LOGIC_TARGET_COMPONENT}",
        }:
            return True
    return False


def _compiler_guidance_summary(
    compiler_guidance: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return a compact JSON-ready autoencoder guidance contract."""
    if not isinstance(compiler_guidance, Mapping):
        return {}
    feature_groups: Dict[str, List[str]] = {}
    raw_groups = compiler_guidance.get("feature_groups")
    if isinstance(raw_groups, Mapping):
        for group_name, raw_features in sorted(raw_groups.items()):
            features = _guidance_feature_list(
                raw_features,
                limit=_COMPILER_GUIDANCE_MAX_GROUP_FEATURES,
            )
            if features:
                feature_groups[str(group_name)] = features
    frame_audit_features = _compiler_guidance_frame_audit_features(
        compiler_guidance
    )
    if frame_audit_features:
        feature_groups["frame_logic_evidence"] = frame_audit_features[
            :_COMPILER_GUIDANCE_MAX_GROUP_FEATURES
        ]
    view_gap_features = _compiler_guidance_view_gap_features(compiler_guidance)
    if view_gap_features:
        feature_groups["legal_ir_view_gap_evidence"] = view_gap_features[
            :_COMPILER_GUIDANCE_MAX_GROUP_FEATURES
        ]
    ranked_guidance_features: List[Dict[str, Any]] = []
    raw_ranked = compiler_guidance.get("ranked_guidance_features")
    if isinstance(raw_ranked, Sequence) and not isinstance(raw_ranked, (str, bytes)):
        for item in raw_ranked[:_COMPILER_GUIDANCE_MAX_FEATURES]:
            if isinstance(item, Mapping):
                feature = _guidance_feature_value(item)
                if not feature:
                    continue
                ranked_guidance_features.append(
                    {
                        "embedding_weight_norm": round(
                            _safe_float(item.get("embedding_weight_norm")),
                            12,
                        ),
                        "family_logit_magnitude": round(
                            _safe_float(item.get("family_logit_magnitude")),
                            12,
                        ),
                        "feature": feature,
                        "legal_ir_view_logit_magnitude": round(
                            _safe_float(item.get("legal_ir_view_logit_magnitude")),
                            12,
                        ),
                        "score": round(_safe_float(item.get("score")), 12),
                    }
                )
    for feature in _compiler_guidance_route_features(compiler_guidance):
        if len(ranked_guidance_features) >= _COMPILER_GUIDANCE_MAX_FEATURES:
            break
        ranked_guidance_features.append(
            {
                "embedding_weight_norm": 0.0,
                "family_logit_magnitude": 0.0,
                "feature": feature,
                "legal_ir_view_logit_magnitude": 0.0,
                "score": 1.0,
            }
        )
    decoded_embedding = []
    raw_decoded_embedding = compiler_guidance.get("decoded_embedding")
    if isinstance(raw_decoded_embedding, Sequence) and not isinstance(
        raw_decoded_embedding,
        (str, bytes),
    ):
        decoded_embedding = [
            round(_safe_float(value), 12)
            for value in raw_decoded_embedding[:_COMPILER_GUIDANCE_MAX_EMBEDDING_VALUES]
        ]
    decoded_embedding_norm = math.sqrt(
        sum(value * value for value in decoded_embedding)
    ) if decoded_embedding else 0.0
    legal_ir_view_metrics: Dict[str, float] = {}
    raw_view_metrics = compiler_guidance.get("legal_ir_view_metrics")
    if isinstance(raw_view_metrics, Mapping):
        legal_ir_view_metrics = {
            str(key): round(_safe_float(value), 12)
            for key, value in sorted(raw_view_metrics.items())
            if math.isfinite(_safe_float(value))
        }
    legal_ir_predicted_view_distribution = _numeric_distribution(
        compiler_guidance.get("legal_ir_predicted_view_distribution")
    )
    legal_ir_target_view_distribution = _numeric_distribution(
        compiler_guidance.get("legal_ir_target_view_distribution")
    )
    if (
        _compiler_guidance_implies_frame_logic_target(compiler_guidance)
        and _MODAL_FRAME_LOGIC_TARGET_COMPONENT
        not in legal_ir_target_view_distribution
    ):
        legal_ir_target_view_distribution = {
            **legal_ir_target_view_distribution,
            _MODAL_FRAME_LOGIC_TARGET_COMPONENT: 1.0,
        }
    if (
        _compiler_guidance_implies_neo4j_projection_target(compiler_guidance)
        and _NEO4J_COMPAT_TARGET_COMPONENT not in legal_ir_target_view_distribution
    ):
        legal_ir_target_view_distribution = {
            **legal_ir_target_view_distribution,
            _NEO4J_COMPAT_TARGET_COMPONENT: 1.0,
        }
    legal_ir_view_gap_distribution = _numeric_signed_mapping(
        compiler_guidance.get("legal_ir_view_gap_distribution")
    )
    if not legal_ir_view_gap_distribution and (
        legal_ir_predicted_view_distribution or legal_ir_target_view_distribution
    ):
        legal_ir_view_gap_distribution = {
            key: round(
                float(legal_ir_target_view_distribution.get(key, 0.0))
                - float(legal_ir_predicted_view_distribution.get(key, 0.0)),
                12,
            )
            for key in sorted(
                set(legal_ir_predicted_view_distribution)
                | set(legal_ir_target_view_distribution)
            )
            if abs(
                float(legal_ir_target_view_distribution.get(key, 0.0))
                - float(legal_ir_predicted_view_distribution.get(key, 0.0))
            )
            > 1.0e-12
        }
    synthesis_focus = _guidance_feature_list(
        compiler_guidance.get("synthesis_focus"),
        limit=_COMPILER_GUIDANCE_MAX_FEATURES,
    )
    frame_logic_routes = _compiler_guidance_frame_logic_target_routes(
        compiler_guidance
    )
    if frame_logic_routes:
        synthesis_focus = _unique_preserve_order(
            [*synthesis_focus, *frame_logic_routes]
        )[:_COMPILER_GUIDANCE_MAX_FEATURES]
    if _compiler_guidance_implies_neo4j_projection_target(compiler_guidance):
        synthesis_focus = _unique_preserve_order(
            [*synthesis_focus, _GRAPH_PROJECTION_GUIDANCE_ROUTE]
        )[:_COMPILER_GUIDANCE_MAX_FEATURES]
    summary = {
        "decoded_embedding": decoded_embedding,
        "decoded_embedding_norm": round(decoded_embedding_norm, 12),
        "family_distribution": _numeric_distribution(
            compiler_guidance.get("family_distribution")
        ),
        "feature_groups": feature_groups,
        "legal_ir_predicted_view_distribution": legal_ir_predicted_view_distribution,
        "legal_ir_target_view_distribution": legal_ir_target_view_distribution,
        "legal_ir_view_gap_distribution": legal_ir_view_gap_distribution,
        "legal_ir_view_metrics": legal_ir_view_metrics,
        "ranked_guidance_features": ranked_guidance_features,
        "sample_id": str(compiler_guidance.get("sample_id") or ""),
        "sample_memory_used": bool(compiler_guidance.get("sample_memory_used")),
        "synthesis_focus": synthesis_focus,
    }
    return {
        key: value
        for key, value in summary.items()
        if value not in ({}, [], "", None)
    }


def _compiler_guidance_frame_audit_features(
    compiler_guidance: Mapping[str, Any],
) -> List[str]:
    """Extract packet-shaped frame features for deterministic ontology audit."""
    candidates: List[str] = []

    def add_feature_values(value: Any) -> None:
        candidates.extend(_guidance_feature_list(value, limit=0))

    def add_stage_values(value: Any) -> None:
        for stage in _guidance_feature_list(value, limit=0):
            candidates.append(f"flogic:statement_hint:{stage}")

    def collect(mapping: Mapping[str, Any]) -> None:
        for key in _COMPILER_GUIDANCE_FRAME_AUDIT_FEATURE_KEYS:
            add_feature_values(mapping.get(key))
        for key in _COMPILER_GUIDANCE_FRAME_AUDIT_STAGE_KEYS:
            add_stage_values(mapping.get(key))
        candidates.extend(_compiler_guidance_legal_ir_view_features(mapping))

    collect(compiler_guidance)
    raw_evidence = compiler_guidance.get("evidence")
    if raw_evidence is None:
        raw_evidence = compiler_guidance.get("evidences")
    if isinstance(raw_evidence, Mapping):
        evidence_items: Iterable[Any] = [raw_evidence]
    elif isinstance(raw_evidence, Sequence) and not isinstance(raw_evidence, (str, bytes)):
        evidence_items = raw_evidence
    else:
        evidence_items = []
    for item in evidence_items:
        if isinstance(item, Mapping):
            collect(item)

    return frame_ontology_feature_keys(
        _unique_preserve_order(candidates),
        max_keys=_COMPILER_GUIDANCE_MAX_FEATURES,
    )


def _compiler_guidance_legal_ir_view_features(
    mapping: Mapping[str, Any],
) -> List[str]:
    """Promote compact LegalIR view evidence into frame audit feature keys."""
    if not isinstance(mapping, Mapping):
        return []

    values: List[Any] = [
        mapping.get("legal_ir_underrepresented_components"),
        mapping.get("underrepresented_components"),
        mapping.get("predicted_view"),
        mapping.get("target_view"),
        mapping.get("target_component"),
        mapping.get("target_file_lane"),
    ]
    for gap_key in (
        "legal_ir_component_gaps",
        "legal_ir_view_gaps",
        "compiler_guidance_legal_ir_view_gaps",
    ):
        raw_gaps = mapping.get(gap_key)
        if not isinstance(raw_gaps, Mapping):
            continue
        values.extend(
            f"legal-ir-view:{component}"
            for component, raw_gap in sorted(raw_gaps.items())
            if _safe_float(raw_gap) > 0.0
        )
    return frame_ontology_feature_keys_from_values(
        values,
        max_keys=_COMPILER_GUIDANCE_MAX_FEATURES,
    )


def _compiler_guidance_feature_strings(
    guidance_summary: Mapping[str, Any],
) -> List[str]:
    features: List[str] = []
    raw_ranked = guidance_summary.get("ranked_guidance_features")
    if isinstance(raw_ranked, Sequence) and not isinstance(raw_ranked, (str, bytes)):
        features.extend(_guidance_feature_list(raw_ranked, limit=0))
    raw_groups = guidance_summary.get("feature_groups")
    if isinstance(raw_groups, Mapping):
        for group_features in raw_groups.values():
            features.extend(_guidance_feature_list(group_features, limit=0))
    features.extend(
        _guidance_feature_list(guidance_summary.get("synthesis_focus"), limit=0)
    )
    for prefix, distribution_key in (
        ("family-distribution", "family_distribution"),
        ("legal-ir-predicted-view", "legal_ir_predicted_view_distribution"),
        ("legal-ir-target-view", "legal_ir_target_view_distribution"),
    ):
        distribution = guidance_summary.get(distribution_key)
        if isinstance(distribution, Mapping):
            features.extend(f"{prefix}:{key}" for key in distribution)
    gap_distribution = guidance_summary.get("legal_ir_view_gap_distribution")
    if isinstance(gap_distribution, Mapping):
        for key, value in gap_distribution.items():
            direction = (
                "underrepresented" if _safe_float(value) > 0.0 else "overrepresented"
            )
            features.append(f"legal-ir-view-gap:{direction}:{key}")
    return _unique_preserve_order(features)


_GUIDANCE_SURFACE_FORCE_LEXEMES = {
    "authorized",
    "may",
    "must",
    "permitted",
    "prohibited",
    "required",
    "requires",
    "shall",
}
_GUIDANCE_SURFACE_SCOPE_TERMS = {
    "condition-prefix": "if",
    "exception-suffix": "except",
    "temporal-suffix": "when",
}
_GUIDANCE_SURFACE_SCOPE_SIGNATURE_TERMS = {
    "conditioned": "if",
    "excepted": "except",
    "temporal": "when",
}
_GUIDANCE_SURFACE_CUE_TERMS = {
    "authority": "authority",
    "condition": "if",
    "conditional": "if",
    "definition": "definition",
    "enforcement": "enforce",
    "exception": "except",
    "obligation": "shall",
    "permission": "may",
    "prohibition": "not",
    "temporal": "when",
}
_GUIDANCE_SURFACE_NEGATING_FORCE_TERMS = {
    "prohibited",
}
_GUIDANCE_SURFACE_SOURCE_ALIASES = {
    "authority": {"authority", "authorized", "authorizes", "authorize"},
    "definition": {"definition", "defined", "means", "includes"},
    "enforce": {"enforce", "enforced", "enforcement"},
    "except": {"except", "exception", "unless", "notwithstanding"},
    "if": {"if", "provided", "condition", "conditions", "where"},
    "may": {"authorized", "may", "permitted"},
    "not": {"no", "nor", "not", "without"},
    "prohibited": {"forbidden", "prohibit", "prohibited", "prohibits"},
    "shall": {"must", "required", "requires", "shall"},
    "when": {"after", "before", "during", "until", "when", "whenever", "within"},
}


def _normalize_guidance_surface_overlay_terms(terms: Sequence[str]) -> List[str]:
    """Drop redundant learned surface markers that encode the same legal force."""
    unique_terms = _unique_preserve_order(
        _clean_non_empty_string(term).lower() for term in terms
    )
    if "not" in unique_terms and any(
        term in unique_terms for term in _GUIDANCE_SURFACE_NEGATING_FORCE_TERMS
    ):
        unique_terms = [term for term in unique_terms if term != "not"]
    return unique_terms


def _guidance_surface_term_source_grounded(
    term: str,
    *,
    source_tokens: set[str],
    source_text: str,
) -> bool:
    aliases = _GUIDANCE_SURFACE_SOURCE_ALIASES.get(term, {term})
    if any(alias in source_tokens for alias in aliases):
        return True
    if term == "prohibited" and any(
        phrase in source_text
        for phrase in ("may not", "shall not", "must not", "is not authorized")
    ):
        return True
    return False


def _source_grounded_guidance_surface_overlay_terms(
    terms: Sequence[str],
    *,
    source_text: str,
) -> List[str]:
    source_rendered = _clean_non_empty_string(source_text).lower()
    source_tokens = {
        token.lower()
        for token in _SLOT_FEATURE_TOKEN_RE.findall(source_rendered)
        if any(character.isalpha() for character in token)
    }
    if not source_tokens:
        return list(terms)
    return [
        term
        for term in terms
        if _guidance_surface_term_source_grounded(
            str(term),
            source_tokens=source_tokens,
            source_text=source_rendered,
        )
    ]


def _compiler_guidance_surface_overlay_terms(
    guidance_summary: Mapping[str, Any],
    *,
    limit: int = 8,
) -> List[str]:
    """Convert learned decompiler-surface features into structural legal terms."""
    if not guidance_summary:
        return []
    terms: List[str] = []

    def add(term: str) -> None:
        cleaned = _clean_non_empty_string(term).lower()
        if cleaned:
            terms.append(cleaned)

    for feature in _compiler_guidance_feature_strings(guidance_summary):
        normalized = _clean_non_empty_string(feature).lower()
        if not normalized.startswith("decompiler-surface:"):
            continue
        parts = [part for part in normalized.split(":") if part]
        if len(parts) < 2:
            continue
        kind = parts[1]
        if kind == "force-lexeme" and len(parts) >= 4:
            lexeme = parts[3]
            if lexeme in _GUIDANCE_SURFACE_FORCE_LEXEMES:
                add(lexeme)
        elif kind == "negation-placement":
            add("not")
        elif kind == "scope-realizer" and len(parts) >= 3:
            term = _GUIDANCE_SURFACE_SCOPE_TERMS.get(parts[2])
            if term:
                add(term)
        elif kind == "force-polarity-template" and len(parts) >= 5:
            polarity = parts[3]
            scope_signature = parts[4]
            if polarity == "negative_scope":
                add("not")
            for marker, term in _GUIDANCE_SURFACE_SCOPE_SIGNATURE_TERMS.items():
                if marker in scope_signature:
                    add(term)
        elif kind == "cue-surface-ir" and len(parts) >= 3:
            term = _GUIDANCE_SURFACE_CUE_TERMS.get(parts[2])
            if term:
                add(term)
    return _normalize_guidance_surface_overlay_terms(terms)[: max(0, int(limit))]


def _with_compiler_guidance_decoded_phrases(
    decoded: DecodedModalText,
    *,
    guidance_summary: Mapping[str, Any],
) -> DecodedModalText:
    """Expose learned compiler guidance as provenance-only decoded slots."""
    if not guidance_summary:
        return decoded
    phrases = list(decoded.phrases)
    seen = {
        (str(phrase.slot or "").strip(), _clean_non_empty_string(phrase.text))
        for phrase in phrases
    }

    def slot_atom(value: Any) -> str:
        return _slot_feature_value(str(value or "").replace(".", "_"), max_tokens=8)

    def add(slot: str, text: Any) -> None:
        normalized_slot = _clean_non_empty_string(slot).replace(" ", "_")
        normalized_text = _clean_non_empty_string(text)
        marker = (normalized_slot, normalized_text)
        if not normalized_slot or not normalized_text or marker in seen:
            return
        seen.add(marker)
        phrases.append(
            DecodedModalPhrase(
                text=normalized_text,
                slot=normalized_slot,
                provenance_only=True,
            )
        )

    add("compiler_guidance_applied", "true")
    add(
        "compiler_guidance_feature_count",
        str(len(_compiler_guidance_feature_strings(guidance_summary))),
    )

    family_distribution = guidance_summary.get("family_distribution")
    if isinstance(family_distribution, Mapping):
        for family, weight in sorted(
            family_distribution.items(),
            key=lambda item: (-_safe_float(item[1]), str(item[0])),
        )[:8]:
            family_atom = slot_atom(family)
            if family_atom:
                add("compiler_guidance_family", family_atom)
                add(
                    "compiler_guidance_family_weight",
                    f"{family_atom}:{_safe_float(weight):.6f}",
                )

    feature_groups = guidance_summary.get("feature_groups")
    if isinstance(feature_groups, Mapping):
        for group, raw_features in sorted(feature_groups.items()):
            group_atom = slot_atom(group)
            if not group_atom:
                continue
            add("compiler_guidance_feature_group", group_atom)
            if isinstance(raw_features, Sequence) and not isinstance(
                raw_features,
                (str, bytes),
            ):
                for feature in raw_features[:8]:
                    feature_text = _clean_non_empty_string(feature)
                    if not feature_text:
                        continue
                    add("compiler_guidance_feature", feature_text)
                    add(f"compiler_guidance_{group_atom}_feature", feature_text)

    for feature in _compiler_guidance_feature_strings(guidance_summary)[:16]:
        add("compiler_guidance_feature", feature)

    gap_distribution = guidance_summary.get("legal_ir_view_gap_distribution")
    if isinstance(gap_distribution, Mapping):
        ranked_gaps = sorted(
            gap_distribution.items(),
            key=lambda item: (-abs(_safe_float(item[1])), str(item[0])),
        )[:8]
        underrepresented_rank = 0
        overrepresented_rank = 0
        for view, value in ranked_gaps:
            gap = _safe_float(value)
            view_atom = slot_atom(view)
            if not view_atom:
                continue
            direction = "underrepresented" if gap > 0.0 else "overrepresented"
            add("compiler_guidance_legal_ir_view_gap", view_atom)
            add(
                "compiler_guidance_legal_ir_view_gap_direction",
                f"{view_atom}:{direction}",
            )
            if gap > 0.0:
                underrepresented_rank += 1
                add("compiler_guidance_legal_ir_underrepresented_view", view_atom)
                add(
                    "compiler_guidance_legal_ir_underrepresented_view_ranked",
                    f"{underrepresented_rank}:{view_atom}",
                )
            elif gap < 0.0:
                overrepresented_rank += 1
                add("compiler_guidance_legal_ir_overrepresented_view", view_atom)
                add(
                    "compiler_guidance_legal_ir_overrepresented_view_ranked",
                    f"{overrepresented_rank}:{view_atom}",
                )
    return replace(decoded, phrases=phrases)


def _apply_compiler_guidance_surface_overlay(
    structural_decoded_text: str,
    overlay_terms: Sequence[str],
    *,
    source_text: Optional[str] = None,
) -> str:
    """Append curated learned surface terms to the structural IR text view."""
    rendered = _clean_non_empty_string(structural_decoded_text)
    if not rendered:
        return rendered
    existing_tokens = {
        token.lower()
        for token in _SLOT_FEATURE_TOKEN_RE.findall(rendered)
        if any(character.isalpha() for character in token)
    }
    source_rendered = _clean_non_empty_string(source_text or "").lower()
    source_tokens = {
        token.lower()
        for token in _SLOT_FEATURE_TOKEN_RE.findall(source_rendered)
        if any(character.isalpha() for character in token)
    }
    additions = [
        term
        for term in _unique_preserve_order(
            _clean_non_empty_string(value).lower() for value in overlay_terms
        )
        if term
        and term not in existing_tokens
        and (
            not source_tokens
            or _guidance_surface_term_source_grounded(
                term,
                source_tokens=source_tokens,
                source_text=source_rendered,
            )
        )
    ]
    if not additions:
        return rendered
    return _clean_non_empty_string(f"{rendered} {' '.join(additions)}")


def _apply_compiler_guidance_typed_semantics(
    modal_ir: ModalIRDocument,
    overlay_terms: Sequence[str],
    *,
    source_text: str,
) -> ModalIRDocument:
    """Promote learned guidance terms into typed IR metadata/clauses."""
    terms = {
        _clean_non_empty_string(term).lower()
        for term in overlay_terms
        if _clean_non_empty_string(term)
    }
    wants_exception = bool(terms.intersection({"except", "unless"}))
    wants_prohibition = bool(terms.intersection({"not", "prohibited"}))
    if not modal_ir.formulas or not (wants_exception or wants_prohibition):
        return modal_ir

    updated_formulas: List[ModalIRFormula] = []
    exception_count = 0
    prohibition_count = 0
    changed = False
    for formula in modal_ir.formulas:
        metadata = dict(formula.metadata)
        exceptions = list(getattr(formula, "exceptions", []) or [])
        formula_changed = False
        if wants_exception:
            inferred_exceptions = exceptions or _inferred_exception_values_from_source_span(
                modal_ir=modal_ir,
                formula=formula,
            )
            if not inferred_exceptions:
                inferred_exceptions = _compiler_guidance_exception_clauses_from_text(
                    source_text,
                )
            if inferred_exceptions:
                exceptions = _unique_preserve_order([*exceptions, *inferred_exceptions])
                metadata["compiler_guidance_typed_exception"] = True
                metadata["compiler_guidance_typed_exception_source"] = (
                    "autoencoder_guidance_v1"
                )
                exception_count += 1
                formula_changed = True
        if wants_prohibition:
            metadata["compiler_guidance_force_polarity"] = "negative"
            metadata["compiler_guidance_deontic_force"] = "prohibition"
            metadata["compiler_guidance_typed_prohibition"] = True
            metadata["compiler_guidance_typed_prohibition_source"] = (
                "autoencoder_guidance_v1"
            )
            prohibition_count += 1
            formula_changed = True
        if formula_changed:
            updated_formulas.append(
                replace(
                    formula,
                    exceptions=exceptions,
                    metadata=metadata,
                )
            )
            changed = True
        else:
            updated_formulas.append(formula)
    if not changed:
        return modal_ir
    typed_semantics = {
        "exception_formula_count": exception_count,
        "prohibition_formula_count": prohibition_count,
        "source": "autoencoder_guidance_v1",
    }
    return replace(
        modal_ir,
        formulas=updated_formulas,
        metadata={
            **modal_ir.metadata,
            "compiler_guidance_typed_semantics": typed_semantics,
        },
    )


def _compiler_guidance_exception_clauses_from_text(
    source_text: str,
    *,
    max_candidates: int = 2,
) -> List[str]:
    source = _clean_non_empty_string(source_text)
    if not source:
        return []
    inferred: List[str] = []
    lowered = source.lower()
    for prefix_text, _prefix_key in sorted(
        _EXCEPTION_PREFIXES,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        pattern = re.compile(rf"(?<!\w){re.escape(prefix_text)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(lowered):
            clause = _trim_inferred_condition_clause(source[match.start() :])
            clause = _TRAILING_SECTION_PUNCT_RE.sub("", _clean_non_empty_string(clause))
            if not clause or _typed_clause_key_value(clause, clause_type="exception") is None:
                continue
            inferred.append(clause)
            if len(inferred) >= max_candidates:
                return _unique_preserve_order(inferred)
    return _unique_preserve_order(inferred)


def _guidance_frame_boost(
    selection: FrameSelection,
    guidance_features: Sequence[str],
) -> tuple[float, List[str]]:
    frame_terms = [
        selection.frame.frame_id,
        selection.frame.label,
        selection.frame.domain,
        *selection.matched_terms,
        *frame_ontology_terms(selection.frame, matched_terms=selection.matched_terms),
    ]
    normalized_terms = {
        normalize_frame_ontology_term(term)
        for term in frame_terms
        if str(term or "").strip()
    }
    normalized_terms = {
        term
        for term in normalized_terms
        if len(term) >= 4 and term not in {"modal", "legal", "frame"}
    }
    frame_id = normalize_frame_ontology_term(selection.frame.frame_id)
    boost = 0.0
    matched_features: List[str] = []
    for feature in guidance_features:
        normalized_feature = normalize_frame_ontology_term(feature)
        if not normalized_feature:
            continue
        feature_boost = 0.0
        if frame_id and frame_id in normalized_feature:
            feature_boost += 0.45
        elif any(term in normalized_feature for term in normalized_terms):
            feature_boost += 0.08
        if (
            "selected_frame" in normalized_feature
            or "selected_ontology_frame" in normalized_feature
        ) and any(term in normalized_feature for term in normalized_terms):
            feature_boost += 0.18
        if (
            "modal_frame_logic" in normalized_feature
            or "knowledge_graphs_neo4j_compat" in normalized_feature
        ) and any(term in normalized_feature for term in normalized_terms):
            feature_boost += 0.04
        if feature_boost > 0.0:
            boost += feature_boost
            matched_features.append(feature)
        if boost >= _COMPILER_GUIDANCE_FRAME_BOOST_CAP:
            boost = _COMPILER_GUIDANCE_FRAME_BOOST_CAP
            break
    return round(boost, 6), matched_features[:8]


def _rerank_frame_selections_with_guidance(
    frame_selections: Sequence[FrameSelection],
    guidance_summary: Mapping[str, Any],
    *,
    top_k: int,
) -> tuple[List[FrameSelection], Dict[str, Dict[str, Any]]]:
    guidance_features = _compiler_guidance_feature_strings(guidance_summary)
    if not guidance_features:
        return list(frame_selections)[:top_k], {}
    reranked: List[FrameSelection] = []
    boosts: Dict[str, Dict[str, Any]] = {}
    for selection in frame_selections:
        boost, matched_features = _guidance_frame_boost(selection, guidance_features)
        if boost > 0.0:
            frame_id = selection.frame.frame_id
            boosts[frame_id] = {
                "boost": boost,
                "matched_features": matched_features,
                "original_score": selection.score,
            }
            reranked.append(
                replace(
                    selection,
                    score=round(selection.score + boost, 6),
                    explanation=(
                        f"{selection.explanation}; autoencoder_guidance_boost={boost:.6f}"
                    ),
                )
            )
        else:
            reranked.append(selection)
    reranked.sort(key=lambda result: (-result.score, result.frame.frame_id))
    return reranked[:top_k], boosts


def _source_copy_reward_hack_penalty(
    *,
    source_span_copy_ratio: float,
    text_reconstruction_similarity: float,
    structural_text_similarity: float,
) -> float:
    copied_similarity_gap = max(
        0.0,
        float(text_reconstruction_similarity) - float(structural_text_similarity),
    )
    return float(source_span_copy_ratio) * copied_similarity_gap


class DeterministicModalLogicCodec:
    """Encode legal text into modal IR and decode it back to vector space."""

    def __init__(
        self,
        config: Optional[ModalLogicCodecConfig] = None,
        *,
        registry: ModalRegistry = DEFAULT_MODAL_REGISTRY,
        frame_selector: Optional[BM25FrameSelector] = None,
        flogic_optimizer: Optional[FLogicSemanticOptimizer] = None,
    ) -> None:
        self.config = config or ModalLogicCodecConfig()
        if self.config.embedding_dimensions < 1:
            raise ValueError("embedding_dimensions must be >= 1")
        self.registry = registry
        self.parser = LegalModalParser(registry=registry)
        self.encoder = SpaCyLegalEncoder(
            model_name=self.config.spacy_model_name,
            registry=registry,
        )
        self.compiler = SpaCyModalIRCompiler()
        self.decoder = SpaCyModalDecoder()
        self.frame_selector = frame_selector or BM25FrameSelector(DEFAULT_LEGAL_FRAME_FIXTURE)
        self.flogic_optimizer = flogic_optimizer or FLogicSemanticOptimizer(
            FLogicOptimizerConfig(
                check_ontology_consistency=self.config.use_flogic,
                ontology_name=self.config.ontology_name,
                similarity_threshold=self.config.flogic_similarity_threshold,
            )
        )

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "legal_text",
        source_embedding: Optional[Sequence[float]] = None,
        compiler_guidance: Optional[Mapping[str, Any]] = None,
    ) -> ModalLogicCodecResult:
        """Run deterministic text -> encoding -> modal IR -> vector decoding."""
        normalized_text = self.parser.normalize_text(text)
        guidance_summary = _compiler_guidance_summary(compiler_guidance)
        guidance_surface_overlay_terms = _compiler_guidance_surface_overlay_terms(
            guidance_summary
        )
        guidance_surface_overlay_terms = _source_grounded_guidance_surface_overlay_terms(
            guidance_surface_overlay_terms,
            source_text=normalized_text,
        )
        encoding = self.encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
        )
        modal_ir, parser_name = self._compile_modal_ir(
            text,
            encoding,
            document_id=document_id or encoding.document_id,
            citation=citation,
            source=source,
        )
        frame_rank_top_k = self.config.top_k_frames
        if guidance_summary:
            frame_count = len(getattr(self.frame_selector, "frames", ()) or ())
            if frame_count > 0:
                frame_rank_top_k = min(
                    frame_count,
                    max(self.config.top_k_frames, self.config.top_k_frames * 3, 12),
                )
        frame_selections = self.frame_selector.rank(
            normalized_text,
            top_k=frame_rank_top_k,
            domain=self.config.frame_domain,
        )
        selected_frame_before_guidance = (
            frame_selections[0].frame.frame_id if frame_selections else None
        )
        guidance_frame_boosts: Dict[str, Dict[str, Any]] = {}
        if guidance_summary:
            frame_selections, guidance_frame_boosts = _rerank_frame_selections_with_guidance(
                frame_selections,
                guidance_summary,
                top_k=self.config.top_k_frames,
            )
        frame_candidates = [selection.to_dict() for selection in frame_selections]
        selected_frame = str(frame_candidates[0]["frame_id"]) if frame_candidates else None
        modal_ir = self._attach_frame_logic(
            modal_ir,
            frame_selections,
            parser_name=parser_name,
            selected_frame=selected_frame,
            encoding=encoding,
        )
        if guidance_summary:
            modal_ir = replace(
                modal_ir,
                metadata={
                    **modal_ir.metadata,
                    "compiler_guidance_applied": True,
                    "compiler_guidance_family_distribution": guidance_summary.get(
                        "family_distribution",
                        {},
                    ),
                    "compiler_guidance_feature_count": len(
                        _compiler_guidance_feature_strings(guidance_summary)
                    ),
                    "compiler_guidance_feature_groups": guidance_summary.get(
                        "feature_groups",
                        {},
                    ),
                    "compiler_guidance_frame_boosts": guidance_frame_boosts,
                    "compiler_guidance_semantic_overlay_terms": (
                        guidance_surface_overlay_terms
                    ),
                    "compiler_guidance_legal_ir_predicted_view_distribution": (
                        guidance_summary.get(
                            "legal_ir_predicted_view_distribution",
                            {},
                        )
                    ),
                    "compiler_guidance_legal_ir_target_view_distribution": (
                        guidance_summary.get(
                            "legal_ir_target_view_distribution",
                            {},
                        )
                    ),
                    "compiler_guidance_legal_ir_view_gap_distribution": (
                        guidance_summary.get(
                            "legal_ir_view_gap_distribution",
                            {},
                        )
                    ),
                    "compiler_guidance_legal_ir_view_metrics": guidance_summary.get(
                        "legal_ir_view_metrics",
                        {},
                    ),
                    "compiler_guidance_ranked_features": guidance_summary.get(
                        "ranked_guidance_features",
                        [],
                    ),
                    "compiler_guidance_sample_id": guidance_summary.get("sample_id", ""),
                    "compiler_guidance_selected_frame_after": selected_frame,
                    "compiler_guidance_selected_frame_before": selected_frame_before_guidance,
                    "compiler_guidance_synthesis_focus": guidance_summary.get(
                        "synthesis_focus",
                        [],
                    ),
                    "frame_selector": "bm25_v1+autoencoder_guidance_v1",
                },
            )
            modal_ir = _apply_compiler_guidance_typed_semantics(
                modal_ir,
                guidance_surface_overlay_terms,
                source_text=normalized_text,
            )
        modal_ir = _enrich_modal_ir_formula_clauses(modal_ir)

        resolved_source_embedding = list(source_embedding) if source_embedding is not None else stable_mock_embedding(
            normalized_text,
            dimensions=self.config.embedding_dimensions,
        )
        source_feature_embedding = self.decoder.decode_embedding(
            encoding,
            dimensions=len(resolved_source_embedding),
        )
        family_logits = self.decoder.family_logits(
            encoding,
            modal_families=_all_modal_families(),
        )
        family_probabilities = _softmax(family_logits)
        target_family = target_family_for_modal_ir(modal_ir)
        target_family_distribution = target_family_distribution_for_modal_ir(modal_ir)
        kg_triples = modal_ir_to_flogic_triples(modal_ir, selected_frame=selected_frame)
        flogic_ontology = flogic_triples_to_ontology(
            kg_triples,
            name=f"{modal_ir.document_id}_flogic",
        )
        neo4j_graph_data = flogic_triples_to_graph_data(
            kg_triples,
            augment_sparse_legal_projection=False,
            graph_id=f"{modal_ir.document_id}:flogic",
            metadata={
                "modal_ir_document_id": modal_ir.document_id,
                "modal_ir_hash": modal_ir.canonical_hash(),
                "modal_ir_version": modal_ir.version,
            },
        )
        graph_schema = neo4j_graph_data.schema
        frame_logic = ModalIRFrameLogic.from_triples(
            kg_triples,
            ontology_name=flogic_ontology.name,
            selected_frame=selected_frame,
            graph_id=neo4j_graph_data.metadata.get("graph_id"),
            neo4j_node_labels=graph_schema.node_labels if graph_schema else [],
            neo4j_relationship_types=graph_schema.relationship_types
            if graph_schema
            else [],
            metadata={
                "compiler_guidance_applied": bool(guidance_summary),
                "neo4j_compatible": True,
                "source": "deterministic_modal_logic_codec_v1",
            },
        )
        modal_ir = replace(
            modal_ir,
            frame_logic=frame_logic,
            metadata={
                **modal_ir.metadata,
                "flogic_ontology": flogic_ontology_to_dict(flogic_ontology),
                "flogic_triple_count": len(kg_triples),
                "flogic_triples": list(kg_triples),
                "neo4j_graph": {
                    "graph_id": neo4j_graph_data.metadata.get("graph_id"),
                    "node_count": neo4j_graph_data.node_count,
                    "relationship_count": neo4j_graph_data.relationship_count,
                    "schema": neo4j_graph_data.schema.to_dict()
                    if neo4j_graph_data.schema
                    else None,
                },
            },
        )
        decoded_modal_text = decode_modal_ir_document(modal_ir)
        if guidance_summary:
            decoded_modal_text = _with_compiler_guidance_decoded_phrases(
                decoded_modal_text,
                guidance_summary=guidance_summary,
            )
        frame_feature_keys = _frame_ontology_audit_feature_keys(
            modal_ir=modal_ir,
            selected_frame=selected_frame,
            kg_triples=kg_triples,
            extra_feature_keys=(
                _slot_features(decoded_modal_text)
                + _frame_decoder_audit_features(encoding, self.decoder)
            ),
        )
        frame_audit_terms = _frame_ontology_audit_terms(
            frame_feature_keys=frame_feature_keys,
            kg_triples=kg_triples,
        )
        frame_high_signal_audit_terms = frame_ontology_high_signal_terms(
            frame_audit_terms,
            max_terms=_FRAME_ONTOLOGY_AUDIT_MAX_TERMS,
        )
        audited_kg_triples = _frame_ontology_audit_triples(
            document_id=modal_ir.document_id,
            kg_triples=kg_triples,
            frame_audit_terms=frame_audit_terms,
            frame_high_signal_audit_terms=frame_high_signal_audit_terms,
        )
        if len(audited_kg_triples) != len(kg_triples):
            kg_triples = audited_kg_triples
            flogic_ontology = flogic_triples_to_ontology(
                kg_triples,
                name=f"{modal_ir.document_id}_flogic",
            )
            neo4j_graph_data = flogic_triples_to_graph_data(
                kg_triples,
                augment_sparse_legal_projection=False,
                graph_id=f"{modal_ir.document_id}:flogic",
                metadata={
                    "modal_ir_document_id": modal_ir.document_id,
                    "modal_ir_hash": modal_ir.canonical_hash(),
                    "modal_ir_version": modal_ir.version,
                },
            )
            graph_schema = neo4j_graph_data.schema
            frame_logic = ModalIRFrameLogic.from_triples(
                kg_triples,
                ontology_name=flogic_ontology.name,
                selected_frame=selected_frame,
                graph_id=neo4j_graph_data.metadata.get("graph_id"),
                neo4j_node_labels=graph_schema.node_labels if graph_schema else [],
                neo4j_relationship_types=graph_schema.relationship_types
                if graph_schema
                else [],
                metadata={
                    "compiler_guidance_applied": bool(guidance_summary),
                    "frame_ontology_audit_projected": True,
                    "neo4j_compatible": True,
                    "source": "deterministic_modal_logic_codec_v1",
                },
            )
            modal_ir = replace(
                modal_ir,
                frame_logic=frame_logic,
                metadata={
                    **modal_ir.metadata,
                    "flogic_ontology": flogic_ontology_to_dict(flogic_ontology),
                    "flogic_triple_count": len(kg_triples),
                    "flogic_triples": list(kg_triples),
                    "neo4j_graph": {
                        "graph_id": neo4j_graph_data.metadata.get("graph_id"),
                        "node_count": neo4j_graph_data.node_count,
                        "relationship_count": neo4j_graph_data.relationship_count,
                        "schema": neo4j_graph_data.schema.to_dict()
                        if neo4j_graph_data.schema
                        else None,
                    },
                },
            )
        modal_ir = replace(
            modal_ir,
            metadata={
                **modal_ir.metadata,
                "frame_ontology_audit_projected": True,
                "frame_ontology_term_audit_count": len(frame_audit_terms),
                "frame_ontology_term_audit_terms": frame_audit_terms,
                "frame_ontology_high_signal_term_audit_count": len(
                    frame_high_signal_audit_terms
                ),
                "frame_ontology_high_signal_term_audit_terms": frame_high_signal_audit_terms,
            },
        )
        decoded_text = decoded_modal_text.text
        structural_decoded_text = _structural_decoded_text(
            decoded_modal_text,
            modal_ir=modal_ir,
            selected_frame=selected_frame,
        )
        structural_decoded_text = _apply_compiler_guidance_surface_overlay(
            structural_decoded_text,
            guidance_surface_overlay_terms,
            source_text=normalized_text,
        )
        decoded_embedding = _decoded_structural_feature_embedding(
            structural_decoded_text,
            encoder=self.encoder,
            decoder=self.decoder,
            dimensions=len(resolved_source_embedding),
            document_id=f"{modal_ir.document_id}:structural-decode",
            citation=citation,
            source=source,
        )
        structural_text_similarity = modal_text_token_similarity(
            normalized_text,
            structural_decoded_text,
        )
        source_span_copy_ratio = _source_span_copy_ratio(decoded_modal_text)
        source_copy_reward_hack_penalty = _source_copy_reward_hack_penalty(
            source_span_copy_ratio=source_span_copy_ratio,
            text_reconstruction_similarity=decoded_modal_text.reconstruction_similarity,
            structural_text_similarity=structural_text_similarity,
        )
        raw_source_embedding_cosine = cosine_similarity(
            resolved_source_embedding,
            decoded_embedding,
        )
        source_decompiled_embedding_cosine = cosine_similarity(
            source_feature_embedding,
            decoded_embedding,
        )
        flogic_result = self._evaluate_flogic(
            normalized_text,
            decoded_text,
            source_feature_embedding,
            decoded_embedding,
            kg_triples,
            frame_feature_keys=frame_feature_keys,
        )
        flogic_similarity_score = _normalized_flogic_similarity_score(flogic_result)
        (
            flogic_similarity_score,
            statutory_frame_support_calibrated,
            frame_logic_alignment_calibrated,
        ) = _calibrated_flogic_similarity_score(
            flogic_similarity_score,
            source_text=normalized_text,
            citation=citation,
            flogic_result=flogic_result,
        )
        losses = {
            "cosine_loss": cosine_loss(source_feature_embedding, decoded_embedding),
            "cosine_similarity": cosine_similarity(source_feature_embedding, decoded_embedding),
            "cross_entropy_entropy_loss": distribution_entropy_loss(
                target_family_distribution,
            ),
            "cross_entropy_excess_loss": cross_entropy_excess_distribution_loss(
                family_probabilities,
                target_family_distribution,
            ),
            "cross_entropy_loss": cross_entropy_distribution_loss(
                family_probabilities,
                target_family_distribution,
            ),
            "flogic_similarity_loss": 1.0 - flogic_similarity_score,
            "flogic_similarity_score": flogic_similarity_score,
            "frame_ranking_loss": 0.0 if selected_frame else 1.0,
            "modal_span_coverage_loss": 1.0 - decoded_modal_text.modal_span_coverage,
            "ontology_violation_count": float(len(flogic_result.violations)) if flogic_result else 0.0,
            "raw_source_embedding_cosine_similarity": raw_source_embedding_cosine,
            "raw_source_embedding_cosine_loss": max(
                0.0,
                1.0 - raw_source_embedding_cosine,
            ),
            "reconstruction_loss": mse_loss(source_feature_embedding, decoded_embedding),
            "source_decompiled_text_embedding_cosine_loss": max(
                0.0,
                1.0 - source_decompiled_embedding_cosine,
            ),
            "source_decompiled_text_embedding_cosine_similarity": (
                source_decompiled_embedding_cosine
            ),
            "source_decompiled_text_raw_embedding_cosine_loss": max(
                0.0,
                1.0 - raw_source_embedding_cosine,
            ),
            "source_decompiled_text_raw_embedding_cosine_similarity": (
                raw_source_embedding_cosine
            ),
            "source_decompiled_text_token_loss": 1.0 - structural_text_similarity,
            "source_decompiled_text_token_similarity": structural_text_similarity,
            "source_copy_loss": source_span_copy_ratio,
            "source_copy_reward_hack_penalty": source_copy_reward_hack_penalty,
            "source_span_copy_ratio": source_span_copy_ratio,
            "source_span_text_reconstruction_loss": 1.0 - decoded_modal_text.reconstruction_similarity,
            "structural_text_reconstruction_loss": 1.0 - structural_text_similarity,
            "structural_text_reconstruction_similarity": structural_text_similarity,
            "symbolic_validity_penalty": 0.0 if modal_ir.formulas else 1.0,
            "text_reconstruction_loss": 1.0 - decoded_modal_text.reconstruction_similarity,
        }
        guidance_family_distribution = guidance_summary.get("family_distribution")
        if isinstance(guidance_family_distribution, Mapping) and guidance_family_distribution:
            losses["guidance_family_cross_entropy_loss"] = cross_entropy_distribution_loss(
                guidance_family_distribution,
                target_family_distribution,
            )
            losses["guidance_family_cross_entropy_excess_loss"] = (
                cross_entropy_excess_distribution_loss(
                    guidance_family_distribution,
                    target_family_distribution,
                )
            )
        guidance_view_distribution = guidance_summary.get(
            "legal_ir_predicted_view_distribution"
        )
        guidance_target_view_distribution = guidance_summary.get(
            "legal_ir_target_view_distribution"
        )
        if (
            isinstance(guidance_view_distribution, Mapping)
            and guidance_view_distribution
            and isinstance(guidance_target_view_distribution, Mapping)
            and guidance_target_view_distribution
        ):
            losses["guidance_legal_ir_view_cross_entropy_loss"] = (
                cross_entropy_distribution_loss(
                    guidance_view_distribution,
                    guidance_target_view_distribution,
                )
            )
            losses["guidance_legal_ir_view_cross_entropy_excess_loss"] = (
                cross_entropy_excess_distribution_loss(
                    guidance_view_distribution,
                    guidance_target_view_distribution,
                )
            )
            losses["guidance_legal_ir_view_entropy_loss"] = distribution_entropy_loss(
                guidance_target_view_distribution,
            )
        metadata = {
            "compiler_guidance_applied": bool(guidance_summary),
            "compiler_guidance_feature_count": len(
                _compiler_guidance_feature_strings(guidance_summary)
            ) if guidance_summary else 0,
            "compiler_guidance_frame_boost_count": len(guidance_frame_boosts),
            "compiler_guidance_semantic_overlay_count": len(
                guidance_surface_overlay_terms
            ),
            "compiler_guidance_semantic_overlay_terms": list(
                guidance_surface_overlay_terms
            ),
            "compiler_guidance_legal_ir_view_gap_distribution": (
                guidance_summary.get("legal_ir_view_gap_distribution", {})
            ),
            "compiler_guidance_selected_frame_after": selected_frame,
            "compiler_guidance_selected_frame_before": selected_frame_before_guidance,
            "deterministic_coverage_ratio": 1.0,
            "deterministic_decompiler": "modal_decompiler_v2",
            "encoder": "spacy_legal_encoder_v1",
            "flogic_ontology_consistent": bool(flogic_result.ontology_consistent) if flogic_result else True,
            "frame_selector": (
                "bm25_v1+autoencoder_guidance_v1"
                if guidance_summary
                else "bm25_v1"
            ),
            "llm_call_count": 0,
            "modal_decompiler_reconstruction_similarity": decoded_modal_text.reconstruction_similarity,
            "modal_decompiler_span_coverage": decoded_modal_text.modal_span_coverage,
            "modal_decompiler_source_span_copy_ratio": source_span_copy_ratio,
            "modal_decompiler_structural_text": structural_decoded_text,
            "modal_decompiler_structural_text_reconstruction_similarity": structural_text_similarity,
            "modal_families": sorted({formula.operator.family for formula in modal_ir.formulas}),
            "modal_systems": sorted({formula.operator.system for formula in modal_ir.formulas}),
            "parser_backend": self.config.parser_backend,
            "spacy_model_name": encoding.model_name,
            "spacy_token_count": len(encoding.tokens),
            "spacy_used_fallback_model": encoding.used_fallback_model,
            "frame_logic_alignment_flogic_calibrated": (
                frame_logic_alignment_calibrated
            ),
            "frame_logic_alignment_flogic_loss_scale": (
                _FRAME_LOGIC_ALIGNMENT_FLOGIC_LOSS_SCALE
                if frame_logic_alignment_calibrated
                else 1.0
            ),
            "statutory_frame_support_flogic_calibrated": (
                statutory_frame_support_calibrated
            ),
            "statutory_frame_support_flogic_loss_scale": (
                _STATUTORY_FRAME_SUPPORT_FLOGIC_LOSS_SCALE
                if statutory_frame_support_calibrated
                else 1.0
            ),
        }
        return ModalLogicCodecResult(
            source_text=text,
            normalized_text=normalized_text,
            parser_name=parser_name,
            encoding=encoding,
            modal_ir=modal_ir,
            source_embedding=resolved_source_embedding,
            decoded_embedding=decoded_embedding,
            family_logits=family_logits,
            family_probabilities=family_probabilities,
            target_family=target_family,
            target_family_distribution=target_family_distribution,
            frame_candidates=frame_candidates,
            selected_frame=selected_frame,
            kg_triples=kg_triples,
            flogic_ontology=flogic_ontology,
            neo4j_graph_data=neo4j_graph_data,
            decoded_modal_text=decoded_modal_text,
            decoded_text=decoded_text,
            losses=losses,
            flogic_result=flogic_result,
            metadata=metadata,
        )

    def encode_sample(self, sample: LegalSample) -> SpaCyLegalEncoding:
        """Return the deterministic encoder output for a ``LegalSample``."""
        return self.encoder.encode(
            sample.text,
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
        )

    def compile_sample_ir(
        self,
        sample: LegalSample,
        *,
        compiler_guidance: Optional[Mapping[str, Any]] = None,
    ) -> ModalIRDocument:
        """Compile a ``LegalSample`` through the canonical modal/F-logic codec."""
        return self.encode(
            sample.text,
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
            compiler_guidance=compiler_guidance,
        ).modal_ir

    def decode_sample_embedding(self, sample: LegalSample, *, dimensions: int) -> List[float]:
        """Decode a ``LegalSample`` into the embedding space expected by SGD."""
        encoding = self.encode_sample(sample)
        return self.decoder.decode_embedding(encoding, dimensions=dimensions)

    def family_logits_for_sample(
        self,
        sample: LegalSample,
        *,
        modal_families: Sequence[str],
    ) -> Dict[str, float]:
        """Return deterministic modal-family logits for a ``LegalSample``."""
        return self.decoder.family_logits(
            self.encode_sample(sample),
            modal_families=modal_families,
        )

    def feature_keys_for_sample(
        self,
        sample: LegalSample,
        *,
        max_features: Optional[int] = None,
    ) -> List[str]:
        """Return generalizable modal, frame, and F-logic features for SGD."""
        limit = max(0, int(max_features or 0))
        if limit <= 0:
            # Preserve the unbounded public API's full codec semantics,
            # including caller-supplied frame selectors and optimized graphs.
            codec_result = self.encode(
                sample.text,
                document_id=sample.sample_id,
                citation=sample.citation,
                source=sample.source,
                source_embedding=sample.embedding_vector,
            )
            encoding = codec_result.encoding
            modal_ir = codec_result.modal_ir
            decoded_modal_text = codec_result.decoded_modal_text
            selected_frame = codec_result.selected_frame
            frame_candidates = codec_result.frame_candidates
            kg_triples = codec_result.kg_triples
        else:
            # Bounded SGD feature extraction reuses the sample's canonical IR;
            # the full codec would also optimize graphs, decompile text, and
            # calculate losses only to obtain a small feature vocabulary.
            encoding = self.encode_sample(sample)
            modal_ir = sample.modal_ir
            decoded_modal_text = None
            selected_frame = sample.selected_frame
            frame_candidates = sample.frame_candidates
            kg_triples = modal_ir_to_flogic_triples(
                modal_ir,
                selected_frame=selected_frame,
            )
        features: List[str] = []
        seen: set[str] = set()

        def add(value: str) -> bool:
            feature = str(value or "")
            if not feature or feature in seen:
                return False
            seen.add(feature)
            features.append(feature)
            return True

        def add_many(values: Iterable[str], *, budget: Optional[int] = None) -> None:
            added = 0
            for value in values:
                if budget is not None and added >= budget:
                    break
                if add(str(value)):
                    added += 1

        decoder_budget = None
        slot_budget = None
        frame_term_budget = None
        triple_budget = None
        if limit > 0:
            # Leave room for every semantic family instead of allowing token
            # features to consume the entire bounded result before frame and
            # F-logic evidence is considered.
            payload_budget = max(4, limit - 8)
            decoder_budget = max(1, int(payload_budget * 0.35))
            slot_budget = max(1, int(payload_budget * 0.20))
            frame_term_budget = max(1, int(payload_budget * 0.20))
            triple_budget = max(
                1,
                payload_budget
                - decoder_budget
                - slot_budget
                - frame_term_budget,
            )

        add_many(self.decoder._feature_stream(encoding), budget=decoder_budget)
        if decoded_modal_text is not None:
            slot_features = _slot_features(decoded_modal_text)
        else:
            slot_features = [
                f"slot:modal_family:{formula.operator.family}"
                for formula in modal_ir.formulas
            ]
            slot_features.extend(
                f"slot:modal_operator:{formula.operator.symbol}"
                for formula in modal_ir.formulas
            )
            if sample.title:
                slot_features.append(f"slot:citation_title:{sample.title}")
            if sample.section:
                slot_features.append(f"slot:citation_section:{sample.section}")
        add_many(slot_features, budget=slot_budget)
        if selected_frame:
            add(f"frame:{selected_frame}")
            selected_frame_families = _selected_frame_modal_families(modal_ir)
            if not selected_frame_families:
                selected_frame_families = sorted(
                    {str(formula.operator.family) for formula in modal_ir.formulas}
                )
            for family in selected_frame_families:
                add(f"family:selected_frame:{family}")
        frame_terms = _frame_ontology_terms_by_frame(modal_ir)
        frame_lookup = {frame.frame_id: frame for frame in self.frame_selector.frames}
        for candidate in frame_candidates:
            frame_id = str(candidate.get("frame_id") or "")
            frame = frame_lookup.get(frame_id)
            if frame is None:
                continue
            frame_terms[frame_id] = _unique_preserve_order(
                [
                    *frame_terms.get(frame_id, ()),
                    *frame_ontology_terms(
                        frame,
                        matched_terms=candidate.get("matched_terms") or (),
                    ),
                ]
            )
        frame_term_count = 0
        for frame_id in sorted(frame_terms):
            terms = frame_terms[frame_id]
            for term in terms:
                if frame_term_budget is not None and frame_term_count >= frame_term_budget:
                    break
                if add(f"frame-term:{term}"):
                    frame_term_count += 1
                if frame_id == selected_frame:
                    add(f"selected-frame-term:{term}")
            if frame_term_budget is not None and frame_term_count >= frame_term_budget:
                break
        for candidate in frame_candidates:
            frame_id = candidate.get("frame_id")
            if frame_id:
                add(f"frame-candidate:{frame_id}")
        triple_count = 0
        triple_priority_prefixes = (
            "modal_family",
            "modal_operator",
            "modal_system",
            "condition",
            "exception",
            "predicate_role",
            "selected_ontology",
        )

        def triple_priority(triple: Mapping[str, Any]) -> tuple[int, str, str]:
            predicate = str(triple.get("predicate", ""))
            priority = next(
                (
                    index
                    for index, prefix in enumerate(triple_priority_prefixes)
                    if predicate.startswith(prefix)
                ),
                len(triple_priority_prefixes),
            )
            return priority, predicate, str(triple.get("object", ""))

        for triple in sorted(kg_triples, key=triple_priority):
            if triple_budget is not None and triple_count >= triple_budget:
                break
            predicate = triple.get("predicate", "")
            obj = triple.get("object", "")
            if predicate and obj:
                if add(f"flogic:{predicate}:{obj}"):
                    triple_count += 1
        if limit > 0:
            return features[:limit]
        return features

    def _compile_modal_ir(
        self,
        text: str,
        encoding: SpaCyLegalEncoding,
        *,
        document_id: str,
        citation: Optional[str],
        source: str,
    ) -> tuple[ModalIRDocument, str]:
        backend = self.config.parser_backend.lower().strip()
        if backend in {"regex", "legal", "legal_modal_parser", "deontic", "deontic:d"}:
            return (
                self.parser.parse(
                    text,
                    document_id=document_id,
                    source=source,
                    citation=citation,
                ),
                "legal_modal_parser_v1",
            )
        return self.compiler.compile(encoding), "spacy_modal_codec_v1"

    def _attach_frame_logic(
        self,
        modal_ir: ModalIRDocument,
        frame_selections: Sequence[FrameSelection],
        *,
        parser_name: str,
        selected_frame: Optional[str],
        encoding: SpaCyLegalEncoding,
    ) -> ModalIRDocument:
        frame_candidates = [
            ModalIRFrame(
                frame_id=selection.frame.frame_id,
                score=selection.score,
                matched_terms=list(selection.matched_terms),
                explanation=selection.explanation,
            )
            for selection in frame_selections
        ]
        metadata = {
            **modal_ir.metadata,
            "deterministic_parser": parser_name,
            "encoder_decoder": "deterministic_modal_logic_codec_v1",
            "frame_ontology_terms": {
                selection.frame.frame_id: frame_ontology_terms(
                    selection.frame,
                    matched_terms=selection.matched_terms,
                )
                for selection in sorted(
                    frame_selections,
                    key=lambda item: item.frame.frame_id,
                )
            },
            "frame_selector": "bm25_v1",
            "llm_call_count": 0,
            "modal_family_counts": encoding.modal_family_counts(),
            "selected_frame": selected_frame,
        }
        return replace(modal_ir, frame_candidates=frame_candidates, metadata=metadata)

    def _evaluate_flogic(
        self,
        source_text: str,
        decoded_text: str,
        source_embedding: Sequence[float],
        decoded_embedding: Sequence[float],
        kg_triples: List[Dict[str, str]],
        *,
        frame_feature_keys: Optional[Sequence[str]] = None,
    ) -> Optional[FLogicOptimizerResult]:
        if not self.config.use_flogic:
            return None
        result = self.flogic_optimizer.evaluate(
            source_text=source_text,
            decoded_text=decoded_text,
            source_embedding=source_embedding,
            decoded_embedding=decoded_embedding,
            kg_triples=kg_triples,
            frame_feature_keys=frame_feature_keys,
        )
        _normalize_flogic_result_frame_terms(result)
        return result


def decode_modal_ir_text(modal_ir: ModalIRDocument) -> str:
    """Render a compact deterministic modal formula string for diagnostics."""
    rendered = [modal_formula_to_text(formula) for formula in modal_ir.formulas]
    return "; ".join(rendered)


def modal_formula_to_text(formula: ModalIRFormula) -> str:
    """Render one modal IR formula into a stable formula-like string."""
    arguments = ", ".join(formula.predicate.arguments)
    predicate = formula.predicate.name
    if arguments:
        predicate = f"{predicate}({arguments})"
    return f"{formula.operator.symbol}[{formula.operator.family}:{formula.operator.system}]({predicate})"


def target_family_for_modal_ir(modal_ir: ModalIRDocument) -> str:
    """Return the training target family used for cross-entropy diagnostics."""
    if not modal_ir.formulas:
        return ModalLogicFamily.HYBRID.value
    return modal_ir.formulas[0].operator.family


def target_family_distribution_for_modal_ir(modal_ir: ModalIRDocument) -> Dict[str, float]:
    """Return observed modal-family frequencies for multi-family legal clauses."""
    families = [formula.operator.family for formula in modal_ir.formulas]
    if not families:
        return {ModalLogicFamily.HYBRID.value: 1.0}
    counts: Dict[str, int] = {}
    for family in families:
        counts[family] = counts.get(family, 0) + 1
    total = float(sum(counts.values()))
    return {
        family: count / total
        for family, count in sorted(counts.items())
    }


def _learned_legal_ir_view_distribution_triples(
    modal_ir: ModalIRDocument,
    *,
    limit: int = 6,
) -> List[Dict[str, str]]:
    """Expose learned LegalIR view distributions to KG/prover bridge adapters."""
    predicted = _numeric_distribution(
        modal_ir.metadata.get(
            "compiler_guidance_legal_ir_predicted_view_distribution"
        )
    )
    target = _numeric_distribution(
        modal_ir.metadata.get("compiler_guidance_legal_ir_target_view_distribution")
    )
    gaps = _numeric_signed_mapping(
        modal_ir.metadata.get("compiler_guidance_legal_ir_view_gap_distribution")
    )
    if not predicted and not target and not gaps:
        return []

    triples: List[Dict[str, str]] = []
    ranked_views = sorted(
        set(predicted) | set(target) | set(gaps),
        key=lambda view: max(
            predicted.get(view, 0.0),
            target.get(view, 0.0),
            abs(gaps.get(view, 0.0)),
        ),
        reverse=True,
    )[: max(0, int(limit))]
    for rank, view in enumerate(ranked_views, start=1):
        safe_view = _clean_non_empty_string(view)
        if not safe_view:
            continue
        if view in predicted:
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_predicted_view",
                    "object": safe_view,
                }
            )
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_predicted_view_weight",
                    "object": f"{safe_view}:{predicted[view]:.6f}",
                }
            )
        if view in target:
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_target_view",
                    "object": safe_view,
                }
            )
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_target_view_weight",
                    "object": f"{safe_view}:{target[view]:.6f}",
                }
            )
        triples.extend(
            [
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_view_rank",
                    "object": f"{rank}:{safe_view}",
                },
                {
                    "subject": modal_ir.document_id,
                    "predicate": "learned_legal_ir_view_gap",
                    "object": (
                        f"{safe_view}:"
                        f"{gaps.get(view, target.get(view, 0.0) - predicted.get(view, 0.0)):.6f}"
                    ),
                },
            ]
        )
    return triples


def modal_ir_to_flogic_triples(
    modal_ir: ModalIRDocument,
    *,
    selected_frame: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Project modal IR into simple F-logic-style triples."""
    if modal_ir.frame_logic.triples:
        return modal_ir.frame_logic.to_triples()
    resolved_selected_frame = _resolved_selected_frame(
        modal_ir,
        explicit_selected_frame=selected_frame,
    )
    triples: List[Dict[str, str]] = [
        {"subject": modal_ir.document_id, "predicate": "type", "object": "legal_modal_document"},
        {"subject": modal_ir.document_id, "predicate": "source", "object": modal_ir.source},
    ]
    typed_semantics = modal_ir.metadata.get("compiler_guidance_typed_semantics")
    if isinstance(typed_semantics, Mapping):
        for name, value in sorted(typed_semantics.items()):
            cleaned_value = _clean_non_empty_string(value)
            if not cleaned_value:
                continue
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": f"compiler_guidance_typed_semantics_{name}",
                    "object": cleaned_value,
                }
            )
    for predicate, value in _document_modal_family_count_components(modal_ir):
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": predicate,
                "object": value,
            }
        )
    for predicate, value in _document_span_components(modal_ir):
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": predicate,
                "object": value,
            }
        )
    triples.extend(_learned_legal_ir_view_distribution_triples(modal_ir))
    if not modal_ir.formulas:
        for predicate, value in _document_source_context_components(modal_ir):
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": predicate,
                    "object": value,
                }
            )
    if resolved_selected_frame:
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": "selected_ontology_frame",
                "object": resolved_selected_frame,
            }
        )
        for predicate, value in _selected_frame_modal_family_count_components(modal_ir):
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": predicate,
                    "object": value,
                }
            )
    frame_terms_by_frame = _frame_ontology_terms_by_frame(modal_ir)
    selected_frame_terms: List[str] = []
    ranked_frame_ids = _ranked_candidate_frame_ids(
        modal_ir,
        frame_terms_by_frame=frame_terms_by_frame,
        selected_frame=resolved_selected_frame,
    )
    for rank, frame_id in enumerate(ranked_frame_ids, start=1):
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": "candidate_ontology_frame",
                "object": frame_id,
            }
        )
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": "candidate_ontology_frame_rank",
                "object": str(rank),
            }
        )
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": "candidate_ontology_frame_ranked",
                "object": f"{rank}:{frame_id}",
            }
        )
        for predicate, value in _numeric_signature_components(
            str(rank),
            slot_prefix="candidate_ontology_frame_rank",
        ):
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": predicate,
                    "object": value,
                }
            )
        for predicate, value in _typed_identifier_components(
            f"{rank}:{frame_id}",
            slot_prefix="candidate_ontology_frame_ranked",
        ):
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": predicate,
                    "object": value,
                }
            )
        candidate_terms = frame_terms_by_frame.get(frame_id, [])
        for term in candidate_terms:
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "candidate_ontology_term",
                    "object": term,
                }
            )
        if resolved_selected_frame and frame_id == resolved_selected_frame:
            selected_frame_terms = list(candidate_terms)
            for term in selected_frame_terms:
                triples.append(
                    {
                        "subject": modal_ir.document_id,
                        "predicate": "selected_ontology_term",
                        "object": term,
                    }
                )
    should_emit_fallback_selected_terms = bool(
        resolved_selected_frame and not selected_frame_terms
    )
    if should_emit_fallback_selected_terms:
        selected_frame_terms = list(frame_terms_by_frame.get(resolved_selected_frame, ()))
    if should_emit_fallback_selected_terms and not selected_frame_terms:
        fallback_selected_term = normalize_frame_ontology_term(resolved_selected_frame)
        if fallback_selected_term:
            selected_frame_terms = [fallback_selected_term]
    if should_emit_fallback_selected_terms and selected_frame_terms:
        for term in selected_frame_terms:
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "selected_ontology_term",
                    "object": term,
                }
            )
    if resolved_selected_frame:
        for term in _compiler_guidance_selected_ontology_terms(modal_ir):
            if term in selected_frame_terms:
                continue
            selected_frame_terms.append(term)
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "selected_ontology_term",
                    "object": term,
                }
            )
        for term in _selected_frame_source_grounding_terms(modal_ir):
            if term in selected_frame_terms:
                continue
            selected_frame_terms.append(term)
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "selected_ontology_term",
                    "object": term,
                }
            )
    for predicate, value in _frame_grounding_profile_components(
        modal_ir,
        selected_frame=resolved_selected_frame,
        selected_frame_terms=selected_frame_terms,
        ranked_frame_ids=ranked_frame_ids,
    ):
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": predicate,
                "object": value,
            }
        )
    triples = _append_selected_frame_ontology_constraint_triples(
        triples,
        document_id=modal_ir.document_id,
        selected_frame=resolved_selected_frame,
        selected_frame_terms=selected_frame_terms,
    )
    for formula in modal_ir.formulas:
        condition_prefixes: set[str] = set()
        condition_prefix_families: set[str] = set()
        condition_prefix_temporal_relations: set[str] = set()
        condition_modal_entries: set[tuple[str, str]] = set()
        exception_prefixes: set[str] = set()
        exception_prefix_families: set[str] = set()
        exception_prefix_temporal_relations: set[str] = set()
        exception_modal_entries: set[tuple[str, str]] = set()
        statutory_scope_entries: set[tuple[str, str]] = set()
        argument_modal_entries: set[tuple[str, str]] = set()
        triples.extend(
            [
                {
                    "subject": formula.formula_id,
                    "predicate": "belongs_to_document",
                    "object": modal_ir.document_id,
                },
                {
                    "subject": formula.formula_id,
                    "predicate": "modal_family",
                    "object": formula.operator.family,
                },
                {
                    "subject": formula.formula_id,
                    "predicate": "modal_system",
                    "object": formula.operator.system,
                },
                {
                    "subject": formula.formula_id,
                    "predicate": "modal_operator",
                    "object": formula.operator.symbol,
                },
                {
                    "subject": formula.formula_id,
                    "predicate": "predicate",
                    "object": formula.predicate.name,
                },
            ]
        )
        formula_metadata = dict(getattr(formula, "metadata", {}) or {})
        if bool(formula_metadata.get("compiler_guidance_typed_exception")):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "compiler_guidance_typed_semantic",
                    "object": "exception",
                }
            )
            source = _clean_non_empty_string(
                formula_metadata.get("compiler_guidance_typed_exception_source")
            )
            if source:
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": "compiler_guidance_typed_exception_source",
                        "object": source,
                    }
                )
        if bool(formula_metadata.get("compiler_guidance_typed_prohibition")):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "compiler_guidance_typed_semantic",
                    "object": "prohibition",
                }
            )
            source = _clean_non_empty_string(
                formula_metadata.get("compiler_guidance_typed_prohibition_source")
            )
            if source:
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": "compiler_guidance_typed_prohibition_source",
                        "object": source,
                    }
                )
        guidance_polarity = _clean_non_empty_string(
            formula_metadata.get("compiler_guidance_force_polarity")
        )
        if guidance_polarity:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "compiler_guidance_force_polarity",
                    "object": guidance_polarity,
                }
            )
        guidance_force = _clean_non_empty_string(
            formula_metadata.get("compiler_guidance_deontic_force")
        )
        if guidance_force:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "compiler_guidance_deontic_force",
                    "object": guidance_force,
                }
            )
        source_id = _clean_non_empty_string(formula.provenance.source_id)
        if source_id:
            for predicate, value in _source_id_components(source_id):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
        for predicate_name, predicate_value in _typed_identifier_components(
            formula.predicate.name,
            slot_prefix="predicate",
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate_name,
                    "object": predicate_value,
                }
            )
        for predicate_name, predicate_value in _content_scope_components(
            formula.predicate.name,
            slot_prefix="predicate",
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate_name,
                    "object": predicate_value,
                }
            )
        for predicate_name, predicate_value in _contextual_modal_cue_components(
            formula,
            text=formula.predicate.name,
            slot_prefix="predicate",
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate_name,
                    "object": predicate_value,
                }
            )
        _append_typed_decompiler_role_triples(
            triples,
            subject=formula.formula_id,
            formula=formula,
            text=formula.predicate.name,
            slot_prefix="predicate",
        )
        predicate_surface_text = _predicate_surface_text_component(
            modal_ir=modal_ir,
            formula=formula,
        )
        if predicate_surface_text is not None:
            surface_text, surface_source = predicate_surface_text
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "predicate_surface_text",
                    "object": surface_text,
                }
            )
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "predicate_surface_text_source",
                    "object": surface_source,
                }
            )
            for predicate_name, predicate_value in _typed_identifier_components(
                surface_text,
                slot_prefix="predicate_surface_text",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate_name,
                        "object": predicate_value,
                    }
                )
            for predicate_name, predicate_value in _contextual_modal_cue_components(
                formula,
                text=surface_text,
                slot_prefix="predicate_surface_text",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate_name,
                        "object": predicate_value,
                    }
                )
            for predicate_name, predicate_value in _content_scope_components(
                surface_text,
                slot_prefix="predicate_surface_text",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate_name,
                        "object": predicate_value,
                    }
                )
            _append_typed_decompiler_role_triples(
                triples,
                subject=formula.formula_id,
                formula=formula,
                text=surface_text,
                slot_prefix="predicate_surface_text",
            )
        modal_operator_label = _resolved_modal_operator_label(formula)
        if modal_operator_label:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "modal_operator_label",
                    "object": modal_operator_label,
                }
            )
            for predicate_name, predicate_value in _typed_identifier_components(
                modal_operator_label,
                slot_prefix="modal_operator_label",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate_name,
                        "object": predicate_value,
                    }
                )
        canonical_modal_operator_label = _canonical_modal_operator_label(
            formula,
            operator_label=modal_operator_label,
        )
        if canonical_modal_operator_label:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "modal_operator_label_canonical",
                    "object": canonical_modal_operator_label,
                }
            )
            for predicate_name, predicate_value in _typed_identifier_components(
                canonical_modal_operator_label,
                slot_prefix="modal_operator_label_canonical",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate_name,
                        "object": predicate_value,
                    }
                )
        modal_operator_signature = _modal_operator_signature(
            formula,
            operator_label=modal_operator_label,
        )
        if modal_operator_signature:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "modal_operator_signature",
                    "object": modal_operator_signature,
                }
            )
            for predicate_name, predicate_value in _typed_identifier_components(
                modal_operator_signature.replace(":", "_"),
                slot_prefix="modal_operator_signature",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate_name,
                        "object": predicate_value,
                    }
                )
        cue_entries: set[tuple[str, str]] = set()
        for cue in _formula_cues(formula):
            cue_value = _clean_non_empty_string(cue)
            if not cue_value:
                continue
            modal_cue_entry = ("modal_cue", cue_value)
            if modal_cue_entry not in cue_entries:
                cue_entries.add(modal_cue_entry)
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": "modal_cue",
                        "object": cue_value,
                    }
                )
            for predicate, value in _cue_modal_components(
                formula,
                cue=cue_value,
            ):
                for resolved_predicate in (
                    predicate,
                    _cue_alias_predicate_name(predicate),
                ):
                    if not resolved_predicate:
                        continue
                    marker = (resolved_predicate, value)
                    if marker in cue_entries:
                        continue
                    cue_entries.add(marker)
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": resolved_predicate,
                            "object": value,
                        }
                    )
        for bridge_cue in _formula_bridge_cues(formula):
            bridge_cue_value = _clean_non_empty_string(bridge_cue)
            if not bridge_cue_value:
                continue
            for predicate, value in (
                ("bridge_cue", bridge_cue_value),
                ("modal_bridge_cue", bridge_cue_value),
            ):
                marker = (predicate, value)
                if marker in cue_entries:
                    continue
                cue_entries.add(marker)
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
            for predicate, value in _modal_lexeme_components(
                formula,
                cue=bridge_cue_value,
                slot_prefix="bridge_modal",
            ):
                marker = (predicate, value)
                if marker in cue_entries:
                    continue
                cue_entries.add(marker)
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
        transition_entries: set[tuple[str, str]] = set()
        for predicate, value in _modal_transition_components(formula):
            marker = (predicate, value)
            if marker in transition_entries:
                continue
            transition_entries.add(marker)
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate,
                    "object": value,
                }
            )
        if formula.predicate.role:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "predicate_role",
                    "object": formula.predicate.role,
                }
            )
        for predicate_name, predicate_value in _source_role_anchor_components(
            modal_ir=modal_ir,
            formula=formula,
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate_name,
                    "object": predicate_value,
                }
            )
        _append_statutory_scope_triples(
            triples,
            subject=formula.formula_id,
            text=formula.predicate.name,
            emitted=statutory_scope_entries,
        )
        for argument in sorted(
            {
                str(value).strip()
                for value in formula.predicate.arguments
                if str(value or "").strip()
            }
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "predicate_argument",
                    "object": argument,
                }
            )
            for predicate_name, predicate_value in _contextual_modal_cue_components(
                formula,
                text=argument,
                slot_prefix="argument",
            ):
                marker = (predicate_name, predicate_value)
                if marker in argument_modal_entries:
                    continue
                argument_modal_entries.add(marker)
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate_name,
                        "object": predicate_value,
                    }
                )
            typed_argument = _typed_argument_key_value(argument)
            if typed_argument is None:
                _append_statutory_scope_triples(
                    triples,
                    subject=formula.formula_id,
                    text=argument,
                    emitted=statutory_scope_entries,
                )
                continue
            key, value = typed_argument
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": f"predicate_argument_{key}",
                    "object": value,
                }
            )
            _append_statutory_scope_triples(
                triples,
                subject=formula.formula_id,
                text=value,
                emitted=statutory_scope_entries,
            )
        fallback_rule = _clean_non_empty_string(formula.metadata.get("fallback_rule"))
        if fallback_rule:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "fallback_rule",
                    "object": fallback_rule,
                }
            )
            for predicate, value in _typed_identifier_components(
                fallback_rule,
                slot_prefix="fallback_rule",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
        section_heading_tail = _fallback_section_heading_tail_text(
            modal_ir=modal_ir,
            formula=formula,
        )
        if section_heading_tail:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "section_heading_tail",
                    "object": section_heading_tail,
                }
            )
            for predicate, value in _typed_identifier_components(
                section_heading_tail,
                slot_prefix="section_heading_tail",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
            for predicate, value in _contextual_modal_cue_components(
                formula,
                text=section_heading_tail,
                slot_prefix="section_heading_tail",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
        fallback_surface_text = _fallback_surface_text(
            modal_ir=modal_ir,
            formula=formula,
        )
        if fallback_surface_text:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "fallback_surface_text",
                    "object": fallback_surface_text,
                }
            )
            for predicate, value in _typed_identifier_components(
                fallback_surface_text,
                slot_prefix="fallback_surface_text",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
            for predicate, value in _contextual_modal_cue_components(
                formula,
                text=fallback_surface_text,
                slot_prefix="fallback_surface_text",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
            fallback_surface_context = _fallback_surface_context_text(
                modal_ir=modal_ir,
                formula=formula,
                surface_text=fallback_surface_text,
            )
            if fallback_surface_context:
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": "fallback_surface_context",
                        "object": fallback_surface_context,
                    }
                )
                for predicate, value in _typed_identifier_components(
                    fallback_surface_context,
                    slot_prefix="fallback_surface_context",
                ):
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": predicate,
                            "object": value,
                        }
                    )
                for predicate, value in _contextual_modal_cue_components(
                    formula,
                    text=fallback_surface_context,
                    slot_prefix="fallback_surface_context",
                ):
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": predicate,
                            "object": value,
                        }
                    )
        source_status_clause = _uscode_status_clause_text(
            document=modal_ir,
            formula=formula,
        )
        if source_status_clause:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "source_status_clause",
                    "object": source_status_clause,
                }
            )
            for predicate, value in _typed_identifier_components(
                source_status_clause,
                slot_prefix="source_status_clause",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
            for atom in _legal_semantic_atoms_from_text(source_status_clause):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": "legal_semantic_atom",
                        "object": atom,
                    }
                )
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": "source_status_clause_legal_semantic_atom",
                        "object": atom,
                    }
                )
            for predicate, value in _contextual_modal_cue_components(
                formula,
                text=source_status_clause,
                slot_prefix="source_status_clause",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
        status_keyword = _status_keyword_value(
            formula,
            fallback_rule=fallback_rule,
        )
        if status_keyword:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "status_keyword",
                    "object": status_keyword,
                }
            )
            for predicate, value in _typed_identifier_components(
                status_keyword,
                slot_prefix="status_keyword",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
            for predicate, value in _status_keyword_modal_components(
                formula,
                status_keyword=status_keyword,
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
        statement_hint = _clean_non_empty_string(formula.metadata.get("statement_hint"))
        if statement_hint:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "statement_hint",
                    "object": statement_hint,
                }
            )
            for predicate, value in _typed_identifier_components(
                statement_hint,
                slot_prefix="statement_hint",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
        procedural_keyword = _clean_non_empty_string(
            formula.metadata.get("procedural_keyword")
        )
        if procedural_keyword:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "procedural_keyword",
                    "object": procedural_keyword,
                }
            )
            for predicate, value in _typed_identifier_components(
                procedural_keyword,
                slot_prefix="procedural_keyword",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
        resolved_conditions = _resolved_formula_conditions(
            modal_ir=modal_ir,
            formula=formula,
        )
        resolved_exceptions = _resolved_formula_exceptions(
            modal_ir=modal_ir,
            formula=formula,
        )
        for predicate_name, predicate_value in _formula_clause_shape_components(
            formula=formula,
            condition_count=len(resolved_conditions),
            exception_count=len(resolved_exceptions),
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate_name,
                    "object": predicate_value,
                }
            )
        for predicate_name, predicate_value in _modal_polarity_slots(
            formula,
            condition_values=resolved_conditions,
            exception_values=resolved_exceptions,
            document=modal_ir,
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate_name,
                    "object": predicate_value,
                }
            )
        for predicate_name, predicate_value in _typed_ir_scope_frame_components(
            modal_ir=modal_ir,
            formula=formula,
            condition_values=resolved_conditions,
            exception_values=resolved_exceptions,
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate_name,
                    "object": predicate_value,
                }
            )
        for condition in resolved_conditions:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "condition",
                    "object": condition,
                }
            )
            for predicate_name, predicate_value in _typed_identifier_components(
                condition,
                slot_prefix="condition",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate_name,
                        "object": predicate_value,
                    }
                )
            _append_statutory_scope_triples(
                triples,
                subject=formula.formula_id,
                text=condition,
                emitted=statutory_scope_entries,
            )
            typed_condition = _typed_clause_key_value(condition, clause_type="condition")
            if typed_condition is not None:
                key, scoped_value = typed_condition
                for predicate_name, predicate_value in _modal_lexeme_components(
                    formula,
                    cue=key,
                    slot_prefix="condition_modal",
                ):
                    marker = (predicate_name, predicate_value)
                    if marker in condition_modal_entries:
                        continue
                    condition_modal_entries.add(marker)
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": predicate_name,
                            "object": predicate_value,
                        }
                    )
                if key not in condition_prefixes:
                    condition_prefixes.add(key)
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": "condition_prefix",
                            "object": key.replace("_", " "),
                        }
                    )
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": "condition_prefix_key",
                            "object": key,
                        }
                    )
                    temporal_relation = _temporal_clause_prefix_relation(key)
                    if temporal_relation:
                        if "temporal" not in condition_prefix_families:
                            condition_prefix_families.add("temporal")
                            triples.append(
                                {
                                    "subject": formula.formula_id,
                                    "predicate": "condition_prefix_family",
                                    "object": "temporal",
                                }
                            )
                        if temporal_relation not in condition_prefix_temporal_relations:
                            condition_prefix_temporal_relations.add(temporal_relation)
                            triples.append(
                                {
                                    "subject": formula.formula_id,
                                    "predicate": "condition_prefix_temporal_relation",
                                    "object": temporal_relation,
                                }
                            )
                if scoped_value:
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": f"condition_{key}",
                            "object": scoped_value,
                        }
                    )
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": "condition_scope",
                            "object": scoped_value,
                        }
                    )
                    for predicate_name, predicate_value in _typed_identifier_components(
                        scoped_value,
                        slot_prefix="condition_scope",
                    ):
                        triples.append(
                            {
                                "subject": formula.formula_id,
                                "predicate": predicate_name,
                                "object": predicate_value,
                            }
                        )
                    for predicate_name, predicate_value in _contextual_modal_cue_components(
                        formula,
                        text=scoped_value,
                        slot_prefix="condition_scope",
                    ):
                        triples.append(
                            {
                                "subject": formula.formula_id,
                                "predicate": predicate_name,
                                "object": predicate_value,
                            }
                        )
                    for predicate_name, predicate_value in _content_scope_components(
                        scoped_value,
                        slot_prefix="condition_scope",
                    ):
                        triples.append(
                            {
                                "subject": formula.formula_id,
                                "predicate": predicate_name,
                                "object": predicate_value,
                            }
                        )
                    _append_typed_decompiler_role_triples(
                        triples,
                        subject=formula.formula_id,
                        formula=formula,
                        text=scoped_value,
                        slot_prefix="condition_scope",
                    )
        for exception in resolved_exceptions:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "exception",
                    "object": exception,
                }
            )
            for predicate_name, predicate_value in _typed_identifier_components(
                exception,
                slot_prefix="exception",
            ):
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate_name,
                        "object": predicate_value,
                    }
                )
            _append_statutory_scope_triples(
                triples,
                subject=formula.formula_id,
                text=exception,
                emitted=statutory_scope_entries,
            )
            typed_exception = _typed_clause_key_value(exception, clause_type="exception")
            if typed_exception is not None:
                key, scoped_value = typed_exception
                for predicate_name, predicate_value in _modal_lexeme_components(
                    formula,
                    cue=key,
                    slot_prefix="exception_modal",
                ):
                    marker = (predicate_name, predicate_value)
                    if marker in exception_modal_entries:
                        continue
                    exception_modal_entries.add(marker)
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": predicate_name,
                            "object": predicate_value,
                        }
                    )
                if key not in exception_prefixes:
                    exception_prefixes.add(key)
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": "exception_prefix",
                            "object": key.replace("_", " "),
                        }
                    )
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": "exception_prefix_key",
                            "object": key,
                        }
                    )
                    temporal_relation = _temporal_clause_prefix_relation(key)
                    if temporal_relation:
                        if "temporal" not in exception_prefix_families:
                            exception_prefix_families.add("temporal")
                            triples.append(
                                {
                                    "subject": formula.formula_id,
                                    "predicate": "exception_prefix_family",
                                    "object": "temporal",
                                }
                            )
                        if temporal_relation not in exception_prefix_temporal_relations:
                            exception_prefix_temporal_relations.add(temporal_relation)
                            triples.append(
                                {
                                    "subject": formula.formula_id,
                                    "predicate": "exception_prefix_temporal_relation",
                                    "object": temporal_relation,
                                }
                            )
                if scoped_value:
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": f"exception_{key}",
                            "object": scoped_value,
                        }
                    )
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": "exception_scope",
                            "object": scoped_value,
                        }
                    )
                    for predicate_name, predicate_value in _typed_identifier_components(
                        scoped_value,
                        slot_prefix="exception_scope",
                    ):
                        triples.append(
                            {
                                "subject": formula.formula_id,
                                "predicate": predicate_name,
                                "object": predicate_value,
                            }
                        )
                    for predicate_name, predicate_value in _contextual_modal_cue_components(
                        formula,
                        text=scoped_value,
                        slot_prefix="exception_scope",
                    ):
                        triples.append(
                            {
                                "subject": formula.formula_id,
                                "predicate": predicate_name,
                                "object": predicate_value,
                            }
                        )
                    for predicate_name, predicate_value in _content_scope_components(
                        scoped_value,
                        slot_prefix="exception_scope",
                    ):
                        triples.append(
                            {
                                "subject": formula.formula_id,
                                "predicate": predicate_name,
                                "object": predicate_value,
                            }
                        )
                    _append_typed_decompiler_role_triples(
                        triples,
                        subject=formula.formula_id,
                        formula=formula,
                        text=scoped_value,
                        slot_prefix="exception_scope",
                    )
            if not resolved_conditions:
                for (
                    condition_predicate,
                    condition_value,
                ) in _condition_proxy_components_from_exception(
                    formula,
                    exception=exception,
                ):
                    triples.append(
                        {
                            "subject": formula.formula_id,
                            "predicate": condition_predicate,
                            "object": condition_value,
                        }
                    )
        citation = _clean_non_empty_string(formula.provenance.citation)
        citation_inferred_from_source_id = False
        if not citation:
            citation = _source_id_inferred_citation(source_id)
            citation_inferred_from_source_id = bool(citation)
        if citation:
            if citation_inferred_from_source_id:
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": "citation_derivation",
                        "object": "source_id_inferred",
                    }
                )
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "citation",
                    "object": citation,
                }
            )
            citation_components = _citation_components(citation)
            for predicate, value in citation_components:
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": predicate,
                        "object": value,
                    }
                )
        for predicate, value in _decompiler_section_cue_components(
            formula=formula,
            source_id=source_id,
            citation=citation,
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate,
                    "object": value,
                }
            )
        for predicate, value in _provenance_alignment_components(
            source_id=source_id,
            citation=citation,
        ):
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": predicate,
                    "object": value,
                }
            )
        if resolved_selected_frame:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "interpreted_in_frame",
                    "object": resolved_selected_frame,
                }
            )
            for term in selected_frame_terms:
                triples.append(
                    {
                        "subject": formula.formula_id,
                        "predicate": "interpreted_in_frame_term",
                        "object": term,
                    }
                )
    return _append_legal_projection_constraint_triples(
        triples,
        document_id=modal_ir.document_id,
    )


def _append_selected_frame_ontology_constraint_triples(
    triples: List[Dict[str, str]],
    *,
    document_id: str,
    selected_frame: Optional[str],
    selected_frame_terms: Sequence[str],
) -> List[Dict[str, str]]:
    """Assert selected-frame grounding facts consumed by F-logic validation."""
    frame = _clean_non_empty_string(selected_frame)
    if not frame:
        return triples

    normalized_terms = _unique_preserve_order(
        _clean_non_empty_string(term)
        for term in selected_frame_terms
        if _clean_non_empty_string(term)
    )
    term_status = "satisfied" if normalized_terms else "missing"
    facts: List[tuple[str, str]] = [
        (
            "modal_frame_logic_ontology_constraint",
            "selected_ontology_frame:required:satisfied",
        ),
        (
            "modal_frame_logic_ontology_constraint",
            f"selected_ontology_term:required:{term_status}",
        ),
        (
            "selected_ontology_frame_grounding",
            f"{frame}:terms:{len(normalized_terms)}",
        ),
        (
            "selected_ontology_frame_term_count",
            str(len(normalized_terms)),
        ),
        (
            "selected_ontology_frame_term_coverage_complete",
            "true" if normalized_terms else "false",
        ),
    ]
    seen = {
        (
            str(triple.get("subject", "")).strip(),
            str(triple.get("predicate", "")).strip(),
            str(triple.get("object", "")).strip(),
        )
        for triple in triples
    }
    for predicate, value in facts:
        normalized_value = _clean_non_empty_string(value)
        if not normalized_value:
            continue
        triple_key = (document_id, predicate, normalized_value)
        if triple_key in seen:
            continue
        seen.add(triple_key)
        triples.append(
            {
                "subject": document_id,
                "predicate": predicate,
                "object": normalized_value,
            }
        )
    return triples


def _append_legal_projection_constraint_triples(
    triples: List[Dict[str, str]],
    *,
    document_id: str,
) -> List[Dict[str, str]]:
    """Assert deterministic ontology constraints for legal projection views."""
    required_views = _required_frame_logic_projection_views(triples)
    if not required_views:
        return triples

    present_views = sorted(
        {
            view
            for triple in triples
            for view in [
                _frame_logic_projection_view_for_predicate(
                    triple.get("predicate", ""),
                    triple.get("object", ""),
                )
            ]
            if view
        }
    )
    missing_views = [view for view in required_views if view not in present_views]
    satisfied_views = [view for view in required_views if view in present_views]
    coverage_ratio = (
        1.0
        if not required_views
        else len(satisfied_views) / float(len(required_views))
    )
    facts: List[tuple[str, str]] = [
        ("learned_legal_ir_projection_constraint", "statutory_frame_ontology"),
        (
            "learned_legal_ir_projection_coverage_complete",
            "true" if not missing_views else "false",
        ),
        ("learned_legal_ir_projection_coverage_ratio", f"{coverage_ratio:.6f}"),
    ]
    facts.extend(
        ("learned_legal_ir_required_projection_view", view)
        for view in required_views
    )
    facts.extend(
        ("learned_legal_ir_present_projection_view", view)
        for view in present_views
    )
    facts.extend(
        ("learned_legal_ir_satisfied_projection_view", view)
        for view in satisfied_views
    )
    facts.extend(
        ("learned_legal_ir_missing_projection_view", view)
        for view in missing_views
    )
    facts.extend(
        (
            "modal_frame_logic_ontology_constraint",
            f"{view}:required:{'missing' if view in missing_views else 'satisfied'}",
        )
        for view in required_views
    )

    seen = {
        (
            str(triple.get("subject", "")).strip(),
            str(triple.get("predicate", "")).strip(),
            str(triple.get("object", "")).strip(),
        )
        for triple in triples
    }
    for predicate, value in facts:
        normalized_value = _clean_non_empty_string(value)
        if not normalized_value:
            continue
        triple_key = (document_id, predicate, normalized_value)
        if triple_key in seen:
            continue
        seen.add(triple_key)
        triples.append(
            {
                "subject": document_id,
                "predicate": predicate,
                "object": normalized_value,
            }
        )
    return triples


def _required_frame_logic_projection_views(
    triples: Sequence[Mapping[str, Any]],
) -> List[str]:
    predicates = {
        _clean_non_empty_string(triple.get("predicate")).lower()
        for triple in triples
    }
    if not predicates:
        return []
    required: List[str] = []
    has_source_id = any(
        predicate == "source_id" or predicate.startswith("source_id_")
        for predicate in predicates
    )
    has_citation = any(
        predicate == "citation" or predicate.startswith("citation_")
        for predicate in predicates
    )
    has_section = any(
        predicate.startswith(
            (
                "citation_section_",
                "citation_source_id_section_",
                "citation_source_id_title_section_",
                "citation_title_section_",
                "fallback_section_heading_",
                "section_heading_",
                "section_component_",
                "section_profile_",
                "section_range_",
                "section_style_",
                "source_id_section_",
                "source_id_title_section_",
            )
        )
        or "section_heading" in predicate
        or "section_component" in predicate
        or "section_profile" in predicate
        for predicate in predicates
    )
    has_editorial_status = any(
        _frame_logic_projection_view_for_predicate(
            triple.get("predicate", ""),
            triple.get("object", ""),
        )
        == "editorial_status"
        for triple in triples
    )
    has_view_alignment = any(
        predicate.startswith("learned_legal_ir_")
        or predicate.startswith("compiler_guidance_legal_ir_")
        for predicate in predicates
    )
    if has_source_id:
        required.append("document_scope")
    if has_source_id or has_citation:
        required.append("citation_structure")
    if has_section:
        required.append("section_structure")
    if has_editorial_status:
        required.append("editorial_status")
    if has_view_alignment:
        required.append("legal_ir_view_alignment")
    return sorted(set(required))


def _frame_logic_projection_view_for_predicate(
    predicate: Any,
    obj: Any = "",
) -> str:
    normalized = _clean_non_empty_string(predicate).lower()
    normalized_object = _clean_non_empty_string(obj).lower()
    if not normalized:
        return ""
    if normalized == "type":
        return "type_assertion"
    if normalized == "status_keyword" or normalized.startswith("status_keyword_"):
        return "editorial_status"
    if (
        normalized.startswith("source_status_clause")
        and normalized_object in {"omitted", "repealed", "transferred"}
    ):
        return "editorial_status"
    if normalized.startswith("learned_legal_ir_") or normalized.startswith(
        "compiler_guidance_legal_ir_"
    ):
        return "legal_ir_view_alignment"
    if normalized in {
        "candidate_ontology_frame",
        "interpreted_in_frame",
        "selected_ontology_frame",
    } or normalized.startswith(
        (
            "candidate_ontology_frame",
            "interpreted_in_frame",
            "selected_ontology_frame",
        )
    ):
        return "frame_link"
    if "ontology_term" in normalized:
        return "ontology_term"
    if normalized.startswith(
        (
            "citation_section_",
            "citation_source_id_section_",
            "citation_source_id_title_section_",
            "citation_title_section_",
            "fallback_section_heading_",
            "section_heading_",
            "section_component_",
            "section_profile_",
            "section_range_",
            "section_style_",
            "source_id_section_",
            "source_id_title_section_",
        )
    ):
        return "section_structure"
    if normalized in {
        "source_id_citation_canonical",
        "source_id_scheme",
        "source_id_title",
        "source_id_title_number",
        "source_id_title_section_key",
    } or normalized.startswith(("source_id_citation_", "source_id_title_")):
        return "citation_structure"
    if normalized in {
        "belongs_to_document",
        "contains_formula",
        "contains_norm",
        "source",
        "source_id",
    } or normalized.startswith(("source_text_", "source_id")):
        return "document_scope"
    if normalized == "citation" or normalized.startswith("citation_"):
        return "citation_structure"
    if any(
        token in normalized
        for token in ("citation", "section", "source_id", "title", "usc")
    ):
        return "citation_structure"
    return "fact"


def _all_modal_families() -> List[str]:
    return [family.value for family in ModalLogicFamily]


def _unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _softmax(logits: Mapping[str, float]) -> Dict[str, float]:
    if not logits:
        return {}
    max_logit = max(float(value) for value in logits.values())
    exponentials = {
        name: math.exp(float(value) - max_logit)
        for name, value in logits.items()
    }
    total = sum(exponentials.values())
    if total == 0.0:
        uniform = 1.0 / len(exponentials)
        return {name: uniform for name in sorted(exponentials)}
    return {name: exponentials[name] / total for name in sorted(exponentials)}


def _clean_non_empty_string(value: Any) -> str:
    cleaned = str(value or "").strip()
    return cleaned if cleaned else ""


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


def _formula_clause_shape_components(
    *,
    formula: ModalIRFormula,
    condition_count: int,
    exception_count: int,
) -> List[tuple[str, str]]:
    """Expose ordered clause/force shape in legal IR projections."""
    family = _slot_safe_family_key(
        _clean_non_empty_string(formula.operator.family).lower()
    )
    operator_symbol = (
        _slot_safe_family_key(_clean_non_empty_string(formula.operator.symbol).lower())
        or "none"
    )
    predicate_role = (
        _slot_safe_family_key(_clean_non_empty_string(formula.predicate.role).lower())
        or "none"
    )
    predicate_head = _predicate_head_anchor(formula) or "none"
    argument_count = len(
        [
            value
            for value in getattr(formula.predicate, "arguments", ()) or ()
            if _clean_non_empty_string(value)
        ]
    )
    arity_bucket = _semantic_count_bucket(argument_count)
    condition_bucket = _semantic_count_bucket(condition_count)
    exception_bucket = _semantic_count_bucket(exception_count)
    shape = f"a{arity_bucket}:c{condition_bucket}:e{exception_bucket}"
    role_shape = f"{predicate_role}:{shape}"
    force_shape = f"{operator_symbol}:{role_shape}"
    components: List[tuple[str, str]] = [
        ("semantic_clause_shape", shape),
        ("semantic_role_clause_shape", role_shape),
        ("semantic_force_clause_shape", force_shape),
        ("semantic_slot_pair", f"conditions:{condition_bucket}|exceptions:{exception_bucket}"),
        ("semantic_slot_pair", f"operator:{operator_symbol}|exceptions:{exception_bucket}"),
        ("semantic_slot_pair", f"predicate-head:{predicate_head}|conditions:{condition_bucket}"),
        ("condition_count_bin", condition_bucket),
        ("exception_count_bin", exception_bucket),
    ]
    if family:
        components.extend(
            [
                ("semantic_family_clause_shape", f"{family}:{shape}"),
                ("semantic_family_role_clause_shape", f"{family}:{role_shape}"),
                ("semantic_family_force_clause_shape", f"{family}:{force_shape}"),
                (
                    "family_semantic_slot_pair",
                    f"{family}:conditions:{condition_bucket}|exceptions:{exception_bucket}",
                ),
                (
                    "family_semantic_slot_pair",
                    f"{family}:operator:{operator_symbol}|exceptions:{exception_bucket}",
                ),
                (
                    "family_semantic_slot_pair",
                    f"{family}:predicate-head:{predicate_head}|conditions:{condition_bucket}",
                ),
            ]
        )
    return _unique_preserve_order_tuples(components)


def _modal_operator_phrase(formula: ModalIRFormula) -> str:
    symbol = _clean_non_empty_string(formula.operator.symbol)
    label = _clean_non_empty_string(formula.operator.label) or symbol
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
    label = _clean_non_empty_string(formula.operator.label)
    if label:
        return label
    fallback = _clean_non_empty_string(_modal_operator_phrase(formula))
    if not fallback or fallback == _clean_non_empty_string(formula.operator.symbol):
        return ""
    return fallback


def _canonical_modal_operator_label(
    formula: ModalIRFormula,
    *,
    operator_label: str,
) -> str:
    family = _clean_non_empty_string(formula.operator.family).lower()
    symbol = _clean_non_empty_string(formula.operator.symbol)
    direct = _CANONICAL_MODAL_OPERATOR_LABELS.get((family, symbol), "")
    if direct:
        return direct
    normalized_label = _clean_non_empty_string(operator_label).lower()
    if not normalized_label:
        return ""
    return _CANONICAL_MODAL_OPERATOR_LABEL_ALIASES.get(normalized_label, "")


def _modal_operator_signature(
    formula: ModalIRFormula,
    *,
    operator_label: str,
) -> str:
    family = _clean_non_empty_string(formula.operator.family)
    symbol = _clean_non_empty_string(formula.operator.symbol)
    label = _clean_non_empty_string(operator_label)
    if not family or not symbol:
        return ""
    if not label:
        return f"{family}:{symbol}"
    return f"{family}:{symbol}:{label}"


def _predicate_surface_text_component(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
) -> tuple[str, str] | None:
    predicate_text = _clean_non_empty_string(formula.predicate.name.replace("_", " "))
    if not _is_low_information_predicate_text(predicate_text):
        return None
    fallback_surface_text = _fallback_surface_text(
        modal_ir=modal_ir,
        formula=formula,
    )
    if (
        fallback_surface_text
        and fallback_surface_text.lower() != predicate_text.lower()
        and not _is_low_information_predicate_text(fallback_surface_text)
    ):
        return fallback_surface_text, "fallback_surface_text"
    modal_span_surface_text = _formula_source_span_surface_text(
        modal_ir=modal_ir,
        formula=formula,
    )
    if (
        modal_span_surface_text
        and modal_span_surface_text.lower() != predicate_text.lower()
        and not _is_low_information_predicate_text(modal_span_surface_text)
    ):
        return modal_span_surface_text, "modal_source_span"
    return None


def _formula_source_span_surface_text(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
    max_tokens: int = 24,
) -> str:
    source_text = str(modal_ir.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    span_text = _clean_non_empty_string(source_text[start:end])
    if not span_text:
        return ""
    normalized = _clean_non_empty_string(_USCODE_LEADING_SECTION_REF_RE.sub("", span_text))
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
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(candidate.lower())
    if not tokens or len(tokens) > max_tokens:
        return ""
    return candidate


def _is_low_information_predicate_text(text: str) -> bool:
    normalized = _clean_non_empty_string(text)
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


def _typed_argument_key_value(argument: str) -> tuple[str, str] | None:
    if ":" not in argument:
        return None
    raw_key, raw_value = argument.split(":", 1)
    key = "".join(
        character.lower() if character.isalnum() else "_"
        for character in raw_key.strip()
    ).strip("_")
    value = raw_value.strip()
    if not key or not value:
        return None
    return key, value


def _source_role_anchor_components(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[tuple[str, str]]:
    anchors = _source_role_anchor_values(modal_ir=modal_ir, formula=formula)
    if not anchors:
        return []
    predicate_role = _clean_non_empty_string(formula.predicate.role).lower()
    predicate_family = _clean_non_empty_string(formula.operator.family).lower()
    source_family_pairs = _source_anchor_family_pairs(
        modal_ir=modal_ir,
        formula=formula,
    )
    predicate_head = _predicate_head_anchor(formula)
    components: List[tuple[str, str]] = []
    structural_roles = [
        role_name
        for role_name in ("subject", "action", "object")
        if _clean_non_empty_string(anchors.get(role_name, ""))
    ]
    role_set = "+".join(structural_roles)
    role_path = "->".join(structural_roles)
    if role_set:
        components.append(("source_role_set", role_set))
        components.append(("source_surface_role_set", role_set))
        if predicate_family:
            components.append(("source_role_set_family", f"{role_set}:{predicate_family}"))
            components.append(
                ("source_surface_role_set_to_family", f"{role_set}:{predicate_family}")
            )
    if role_path:
        components.append(("source_role_path", role_path))
        components.append(("source_role_path_scope", f"{role_path}:unscoped"))
        if predicate_family:
            components.append(("source_role_path_family", f"{role_path}:{predicate_family}"))
    for role_name in ("subject", "action", "object"):
        anchor = _clean_non_empty_string(anchors.get(role_name, "")) or "none"
        variable_name = f"v_{role_name}"
        components.append(
            ("source_logical_variable_map", f"{role_name}:{anchor}:{variable_name}")
        )
        components.append(
            (
                f"source_{role_name}_logical_variable_map",
                f"{role_name}:{anchor}:{variable_name}",
            )
        )
    for role_name in ("subject", "action", "object", "condition", "exception", "temporal"):
        anchor = _clean_non_empty_string(anchors.get(role_name, ""))
        if not anchor:
            continue
        slot_prefix = f"source_{role_name}_anchor"
        components.append((slot_prefix, anchor))
        components.extend(
            _typed_identifier_components(
                anchor,
                slot_prefix=slot_prefix,
            )
        )
        if predicate_family:
            components.append((f"source_{role_name}_family", f"{anchor}:{predicate_family}"))
            for family_pair in source_family_pairs:
                components.append((f"source_{role_name}_family_pair", family_pair))
                components.append(
                    (f"source_{role_name}_family_pair_anchor", f"{anchor}:{family_pair}")
                )
        if predicate_role and role_name in {"subject", "action", "object"}:
            components.append((f"source_{role_name}_role", f"{anchor}:{predicate_role}"))
        if predicate_head and role_name in {"action", "object"}:
            components.append((f"source_{role_name}_predicate", f"{anchor}:{predicate_head}"))
    return _unique_preserve_order_tuples(components)


def _typed_ir_scope_frame_components(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
    condition_values: Sequence[str],
    exception_values: Sequence[str],
) -> List[tuple[str, str]]:
    """Project typed decompiler scope-frame reconstructions into triples."""
    source_family = _clean_non_empty_string(formula.operator.family).lower()
    if not source_family:
        return []

    targets: List[str] = [source_family]
    has_condition_scope = bool(condition_values or exception_values)
    has_temporal_scope = False
    for clause_type, clauses in (
        ("condition", condition_values),
        ("exception", exception_values),
    ):
        for clause in clauses:
            typed_clause = _typed_clause_key_value(clause, clause_type=clause_type)
            if typed_clause is None and clause_type == "exception":
                typed_clause = _typed_clause_key_value(clause, clause_type="condition")
            if typed_clause is None:
                continue
            prefix_key, _scoped_value = typed_clause
            if _temporal_clause_prefix_relation(prefix_key):
                has_temporal_scope = True
    if has_condition_scope and "conditional_normative" not in targets:
        targets.append("conditional_normative")
    if has_temporal_scope and "temporal" not in targets:
        targets.append("temporal")
    if source_family == "frame" and "frame" not in targets:
        targets.append("frame")

    role_values = _source_role_anchor_values(modal_ir=modal_ir, formula=formula)
    roles = {
        role: value
        for role, value in role_values.items()
        if role in {"subject", "action", "object", "temporal"} and value
    }
    semantic_atoms = _legal_semantic_atoms_from_text(
        " ".join(
            value
            for value in (
                formula.predicate.name,
                " ".join(condition_values),
                " ".join(exception_values),
                _fallback_section_heading_tail_text(
                    modal_ir=modal_ir,
                    formula=formula,
                ),
            )
            if _clean_non_empty_string(value)
        )
    )
    force = _modal_force_label(formula)
    polarity = _modal_scope_polarity(
        formula,
        condition_values=condition_values,
        exception_values=exception_values,
        document=modal_ir,
    )

    components: List[tuple[str, str]] = []
    for text in _typed_ir_scope_frame_texts(
        source_family=source_family,
        targets=targets,
        force=force,
        polarity=polarity,
        roles=roles,
        condition_values=condition_values,
        exception_values=exception_values,
        semantic_atoms=semantic_atoms,
    ):
        components.append(("typed_ir_scope_frame_reconstruction", text))
        signature = _slot_safe_family_pair_key(text)
        if signature:
            components.append(("typed_ir_scope_frame_signature", signature))
    return _unique_preserve_order_tuples(components)


def _source_anchor_family_pairs(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[str]:
    source_family = _clean_non_empty_string(formula.operator.family).lower()
    if not source_family:
        return []
    distinct_families: List[str] = []
    for candidate_formula in modal_ir.formulas:
        candidate_family = _clean_non_empty_string(candidate_formula.operator.family).lower()
        if not candidate_family or candidate_family in distinct_families:
            continue
        distinct_families.append(candidate_family)
    if source_family == "frame" and set(distinct_families or [source_family]) == {"frame"}:
        return ["frame->frame"]
    for target_family in _cue_derived_target_families(formula):
        if target_family and target_family not in distinct_families:
            distinct_families.append(target_family)
    for target_family in _SOURCE_ANCHOR_DIRECTIONAL_FAMILY_PAIR_TARGETS.get(
        source_family,
        (),
    ):
        normalized_target = _clean_non_empty_string(target_family).lower()
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
    source_family = _clean_non_empty_string(formula.operator.family).lower()
    if source_family == "temporal":
        derived.append("temporal")
    for cue in (*_formula_cues(formula), *_formula_bridge_cues(formula)):
        cue_key = _clean_non_empty_string(cue).lower().replace(" ", "_")
        if not cue_key:
            continue
        for target_family, _ in _cue_bridge_operator_pairs(cue_key):
            normalized_target = _clean_non_empty_string(target_family).lower()
            if not normalized_target or normalized_target in derived:
                continue
            derived.append(normalized_target)
    return derived


def _source_role_anchor_values(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
) -> Dict[str, str]:
    span_text = _semantic_source_span_text(modal_ir=modal_ir, formula=formula)
    predicate_text = _clean_non_empty_string(formula.predicate.name).replace("_", " ")
    raw_tokens = _CUE_TOKEN_RE.findall(span_text.lower())
    if not raw_tokens:
        raw_tokens = _CUE_TOKEN_RE.findall(predicate_text.lower())
    if not raw_tokens:
        return {}
    cue_sequences: List[List[str]] = []
    cue_tokens: set[str] = set()
    explicit_cue = _clean_non_empty_string(formula.metadata.get("cue"))
    for cue_value in (explicit_cue, *_formula_cues(formula)):
        cue_sequence = _CUE_TOKEN_RE.findall(
            _clean_non_empty_string(cue_value).replace("_", " ").lower()
        )
        if not cue_sequence:
            continue
        cue_sequences.append(cue_sequence)
        cue_tokens.update(cue_sequence)

    cue_window: tuple[int, int] | None = None
    cue_window_sequence: List[str] = []
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
                cue_window_sequence = list(cue_sequence)
            else:
                current_width = cue_window[1] - cue_window[0]
                if width > current_width or (
                    width == current_width and start < cue_window[0]
                ):
                    cue_window = candidate
                    cue_window_sequence = list(cue_sequence)
            break

    cue_start = -1
    cue_end = -1
    passive_cue_action_candidates: List[str] = []
    if cue_window is not None:
        cue_start, cue_end = cue_window
        if _is_passive_by_cue_sequence(cue_window_sequence):
            passive_cue_action_candidates = _source_anchor_role_tokens(
                cue_window_sequence[:-1]
            )
        elif _is_passive_by_marker_context(
            cue_window_sequence=cue_window_sequence,
            raw_tokens=raw_tokens,
            cue_start=cue_start,
        ):
            passive_cue_action_candidates = _source_anchor_role_tokens(
                raw_tokens[cue_start - 1 : cue_start]
            )
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
        # Compilation spans carry long heading scaffolding; prefer anchors
        # derivable from typed predicate slots over heading replay tokens.
        subject_candidates = list(predicate_tokens)
        predicate_candidates = list(predicate_tokens)
    if not subject_candidates and predicate_tokens:
        subject_candidates = predicate_tokens[:1]
    if not predicate_candidates:
        predicate_candidates = list(predicate_tokens)
    condition_values = _resolved_formula_conditions(
        modal_ir=modal_ir,
        formula=formula,
    )
    exception_values = _resolved_formula_exceptions(
        modal_ir=modal_ir,
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
    if passive_cue_action_candidates:
        passive_action_anchor = _preferred_anchor_candidate(
            passive_cue_action_candidates,
            default_index=-1,
        )
        passive_object_anchor = _preferred_anchor_candidate(
            predicate_candidates,
            default_index=0,
        )
        if passive_action_anchor:
            action_anchor = passive_action_anchor
        if passive_object_anchor:
            object_anchor = passive_object_anchor
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


def _is_passive_by_cue_sequence(cue_sequence: Sequence[str]) -> bool:
    """Return True when a matched cue consumes the passive action verb."""

    return (
        len(cue_sequence) >= 2
        and cue_sequence[-1] == "by"
        and any(token not in _SOURCE_ROLE_CONNECTIVE_TOKENS for token in cue_sequence[:-1])
    )


def _is_passive_by_marker_context(
    *,
    cue_window_sequence: Sequence[str],
    raw_tokens: Sequence[str],
    cue_start: int,
) -> bool:
    """Return True for a single ``by`` marker following a passive verb."""

    if list(cue_window_sequence) != ["by"] or cue_start <= 0:
        return False
    previous_token = _clean_non_empty_string(raw_tokens[cue_start - 1]).lower()
    return len(previous_token) > 4 and previous_token.endswith("ed")


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


def _is_temporal_anchor_token(token: str) -> bool:
    normalized_token = _clean_non_empty_string(token).lower()
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
        _clean_non_empty_string(candidate).lower()
        for candidate in candidates
        if _clean_non_empty_string(candidate)
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
        normalized_clause = _clean_non_empty_string(clause).lower()
        if not normalized_clause:
            continue
        typed_clause = _typed_clause_key_value(
            normalized_clause,
            clause_type=clause_type,
        )
        scoped_text = normalized_clause
        if typed_clause is not None:
            prefix_key, scoped_value = typed_clause
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
        _clean_non_empty_string(formula.predicate.name).replace("_", " ").lower()
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


def _typed_clause_key_value(
    clause: str,
    *,
    clause_type: str,
) -> tuple[str, str] | None:
    normalized = _clean_non_empty_string(clause).lower()
    if not normalized:
        return None
    prefixes = _CONDITION_PREFIXES if clause_type == "condition" else _EXCEPTION_PREFIXES
    for prefix_text, prefix_key in sorted(
        prefixes,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if not _text_has_prefix(normalized, prefix_text):
            continue
        value = _clean_non_empty_string(normalized[len(prefix_text) :].lstrip(",:;- "))
        return prefix_key, value
    return None


def _enrich_modal_ir_formula_clauses(modal_ir: ModalIRDocument) -> ModalIRDocument:
    """Backfill formula clause lists from deterministic metadata/span resolvers."""
    if not modal_ir.formulas:
        return modal_ir
    updated_formulas: List[ModalIRFormula] = []
    changed = False
    for formula in modal_ir.formulas:
        resolved_conditions = list(getattr(formula, "conditions", []) or [])
        resolved_exceptions = list(getattr(formula, "exceptions", []) or [])
        if not resolved_conditions:
            resolved_conditions = _resolved_formula_conditions(
                modal_ir=modal_ir,
                formula=formula,
            )
        if not resolved_exceptions:
            resolved_exceptions = _resolved_formula_exceptions(
                modal_ir=modal_ir,
                formula=formula,
            )
        normalized_formula = formula
        if (
            list(getattr(formula, "conditions", []) or []) != resolved_conditions
            or list(getattr(formula, "exceptions", []) or []) != resolved_exceptions
        ):
            normalized_formula = replace(
                formula,
                conditions=list(resolved_conditions),
                exceptions=list(resolved_exceptions),
            )
            changed = True
        updated_formulas.append(normalized_formula)
    if not changed:
        return modal_ir
    return replace(modal_ir, formulas=updated_formulas)


def _resolved_formula_conditions(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[str]:
    explicit_conditions = _unique_preserve_order(
        str(value).strip()
        for value in formula.conditions
        if str(value or "").strip()
    )
    if explicit_conditions:
        return explicit_conditions
    metadata_conditions = _resolved_clause_values_from_metadata(
        formula,
        clause_type="condition",
    )
    if metadata_conditions:
        return metadata_conditions
    inferred_conditions = _inferred_condition_values_from_source_span(
        modal_ir=modal_ir,
        formula=formula,
    )
    return _unique_preserve_order([*explicit_conditions, *inferred_conditions])


def _resolved_formula_exceptions(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
) -> List[str]:
    explicit_exceptions = _unique_preserve_order(
        str(value).strip()
        for value in formula.exceptions
        if str(value or "").strip()
    )
    if explicit_exceptions:
        return explicit_exceptions
    metadata_exceptions = _resolved_clause_values_from_metadata(
        formula,
        clause_type="exception",
    )
    if metadata_exceptions:
        return metadata_exceptions
    inferred_exceptions = _inferred_exception_values_from_source_span(
        modal_ir=modal_ir,
        formula=formula,
    )
    return _unique_preserve_order([*explicit_exceptions, *inferred_exceptions])


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
        cleaned = _clean_non_empty_string(raw_value)
        if cleaned:
            collected.append(cleaned)

    for key, value in metadata.items():
        key_text = _clean_non_empty_string(key).lower()
        if not key_text:
            continue
        if key_text in {slot, f"{slot}s"}:
            _append_values(value)
            continue
        if key_text == scope_key:
            scoped_value = _clean_non_empty_string(value)
            continue
        if key_text == prefix_key_slot:
            scoped_prefix = _clean_non_empty_string(value).lower()
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
        parsed = _typed_clause_key_value(value, clause_type=clause_type)
        if parsed is not None:
            resolved.append(value)
            continue
        if scoped_prefix:
            prefix_text = scoped_prefix.replace("_", " ").strip()
            value_text = _clean_non_empty_string(value)
            if not prefix_text or value_text.lower().startswith(prefix_text.lower()):
                continue
            prefixed = f"{prefix_text} {value_text}".strip()
            parsed = _typed_clause_key_value(prefixed, clause_type=clause_type)
            if parsed is not None and parsed[1]:
                resolved.append(prefixed)
    return _unique_preserve_order(resolved)


def _inferred_condition_values_from_source_span(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
    max_candidates: int = 2,
    max_tokens: int = 40,
) -> List[str]:
    span_text = _semantic_source_span_text(modal_ir=modal_ir, formula=formula)
    if not span_text:
        return []
    cue_key = _clean_non_empty_string(formula.metadata.get("cue")).lower().replace(
        " ",
        "_",
    )
    ordered_prefixes = sorted(
        _CONDITION_PREFIXES,
        key=lambda item: len(item[0]),
        reverse=True,
    )
    prioritized_prefixes: List[tuple[str, str]] = []
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
            clause = _TRAILING_SECTION_PUNCT_RE.sub("", _clean_non_empty_string(clause))
            if not clause:
                continue
            token_count = len(
                [
                    token
                    for token in re.split(
                        r"[_\s]+",
                        _clean_non_empty_string(clause).replace("-", "_").lower(),
                    )
                    if token
                ]
            )
            if token_count < 2 or token_count > max_tokens:
                continue
            typed_clause = _typed_clause_key_value(clause, clause_type="condition")
            if typed_clause is None:
                continue
            parsed_prefix_key, scoped_value = typed_clause
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


def _inferred_exception_values_from_source_span(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
    max_candidates: int = 2,
    max_tokens: int = 40,
) -> List[str]:
    span_text = _formula_source_span_text(modal_ir=modal_ir, formula=formula)
    if not span_text:
        return []
    cue_key = _clean_non_empty_string(formula.metadata.get("cue")).lower().replace(
        " ",
        "_",
    )
    ordered_prefixes = sorted(
        _EXCEPTION_PREFIXES,
        key=lambda item: len(item[0]),
        reverse=True,
    )
    prioritized_prefixes: List[tuple[str, str]] = []
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
            token_count = len(
                [
                    token
                    for token in re.split(
                        r"[_\s]+",
                        _clean_non_empty_string(clause).replace("-", "_").lower(),
                    )
                    if token
                ]
            )
            if token_count < 2 or token_count > max_tokens:
                continue
            typed_clause = _typed_clause_key_value(clause, clause_type="exception")
            if typed_clause is None:
                continue
            parsed_prefix_key, _ = typed_clause
            if parsed_prefix_key != prefix_key:
                continue
            parsed_condition_clause = _typed_clause_key_value(
                clause,
                clause_type="condition",
            )
            if (
                parsed_condition_clause is not None
                and parsed_condition_clause[0] == parsed_prefix_key
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
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
) -> str:
    source_text = str(modal_ir.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    return _clean_non_empty_string(source_text[start:end])


def _semantic_source_span_text(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
) -> str:
    span_text = _formula_source_span_text(modal_ir=modal_ir, formula=formula)
    if not span_text:
        return ""
    normalized = _clean_non_empty_string(_USCODE_LEADING_SECTION_REF_RE.sub("", span_text))
    normalized = _strip_uscode_gpo_attribution_fragment(normalized)
    normalized = _TRAILING_SECTION_PUNCT_RE.sub("", normalized)
    normalized = _trim_uscode_compilation_surface_text(normalized, max_tokens=80)
    normalized = _clean_non_empty_string(normalized)
    if normalized and not _is_low_information_section_marker(normalized):
        return normalized
    return span_text


def _is_probable_uscode_compilation_span(text: str) -> bool:
    normalized = _clean_non_empty_string(text).lower()
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
    normalized = _clean_non_empty_string(text)
    if not normalized:
        return ""
    stripped = _clean_non_empty_string(_USCODE_GPO_ATTRIBUTION_RE.sub("", normalized))
    if stripped != normalized:
        return stripped
    return _clean_non_empty_string(_USCODE_GPO_ATTRIBUTION_FRAGMENT_RE.sub("", normalized))


def _trim_inferred_condition_clause(clause: str) -> str:
    normalized_clause = _clean_non_empty_string(clause)
    if not normalized_clause:
        return ""
    trimmed = _clean_non_empty_string(
        _INFERRED_CONDITION_CLAUSE_SPLIT_RE.split(normalized_clause, maxsplit=1)[0]
    )
    return _TRAILING_SECTION_PUNCT_RE.sub("", trimmed)


def _cue_modal_components(
    formula: ModalIRFormula,
    *,
    cue: str,
) -> List[tuple[str, str]]:
    return _modal_lexeme_components(
        formula,
        cue=cue,
        slot_prefix="cue_modal",
    )


def _formula_cues(formula: ModalIRFormula) -> List[str]:
    cues: List[str] = []
    explicit_cue = _clean_non_empty_string(formula.metadata.get("cue"))
    if explicit_cue:
        cues.append(explicit_cue)
    derived_cue = _derived_modal_cue(formula, explicit_cue=explicit_cue)
    if derived_cue:
        normalized_explicit = explicit_cue.lower()
        if not normalized_explicit or derived_cue.lower() != normalized_explicit:
            cues.append(derived_cue)
    normalized_existing = {cue.lower() for cue in cues}
    for temporal_prefix_cue in _temporal_prefix_cues(formula):
        if temporal_prefix_cue in normalized_existing:
            continue
        cues.append(temporal_prefix_cue)
        normalized_existing.add(temporal_prefix_cue)
    return cues


def _temporal_prefix_cues(formula: ModalIRFormula) -> List[str]:
    cues: List[str] = []
    for clause in formula.conditions:
        typed_clause = _typed_clause_key_value(clause, clause_type="condition")
        if typed_clause is None:
            continue
        prefix_key, _ = typed_clause
        normalized_prefix_key = _clean_non_empty_string(prefix_key).lower()
        if (
            normalized_prefix_key
            and _temporal_clause_prefix_relation(normalized_prefix_key)
            and normalized_prefix_key not in cues
        ):
            cues.append(normalized_prefix_key)
    for clause in formula.exceptions:
        typed_clause = _typed_clause_key_value(clause, clause_type="exception")
        if typed_clause is None:
            continue
        prefix_key, _ = typed_clause
        normalized_prefix_key = _clean_non_empty_string(prefix_key).lower()
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
    normalized_explicit = _clean_non_empty_string(explicit_cue)
    if normalized_explicit and not _is_fallback_modal_cue(normalized_explicit):
        return ""
    cue_terms = _operator_cue_terms(formula)
    source_text = " ".join(
        _clean_non_empty_string(value).replace("_", " ").lower()
        for value in (
            formula.predicate.name,
            *formula.conditions,
            *formula.exceptions,
        )
        if _clean_non_empty_string(value)
    )
    for cue_term in cue_terms:
        normalized_term = _clean_non_empty_string(cue_term).lower()
        if not normalized_term:
            continue
        if _text_contains_cue_term(source_text, normalized_term):
            return normalized_term
    operator_label = _clean_non_empty_string(_resolved_modal_operator_label(formula)).lower()
    if operator_label:
        label_tokens = _CUE_TOKEN_RE.findall(operator_label)
        if label_tokens:
            return label_tokens[0]
    return ""


def _operator_cue_terms(formula: ModalIRFormula) -> List[str]:
    family = _clean_non_empty_string(formula.operator.family).lower()
    symbol = _clean_non_empty_string(formula.operator.symbol)
    if not family or not symbol:
        return []
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        if _clean_non_empty_string(profile.family.value).lower() != family:
            continue
        for operator in profile.operators:
            if _clean_non_empty_string(operator.symbol) != symbol:
                continue
            return [
                _clean_non_empty_string(cue_term)
                for cue_term in operator.cue_terms
                if _clean_non_empty_string(cue_term)
            ]
    return []


def _canonical_cue_operator_symbol(
    formula: ModalIRFormula,
    *,
    cue: str,
) -> str:
    family = _clean_non_empty_string(formula.operator.family).lower()
    cue_value = _clean_non_empty_string(cue).lower()
    if not family or not cue_value:
        return ""
    matching_symbols: List[str] = []
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        if _clean_non_empty_string(profile.family.value).lower() != family:
            continue
        for operator in profile.operators:
            if any(
                _cue_matches_registry_term(cue_value, cue_term)
                for cue_term in operator.cue_terms
            ):
                symbol = _clean_non_empty_string(operator.symbol)
                if symbol and symbol not in matching_symbols:
                    matching_symbols.append(symbol)
    if not matching_symbols:
        return ""
    formula_symbol = _clean_non_empty_string(formula.operator.symbol)
    if formula_symbol and formula_symbol in matching_symbols:
        return formula_symbol
    return matching_symbols[0]


def _registry_cue_operator_match(
    formula: ModalIRFormula,
    *,
    cue: str,
) -> tuple[str, str]:
    matching_pairs = _registry_cue_operator_matches(cue=cue)
    if not matching_pairs:
        return ("", "")
    formula_family = _clean_non_empty_string(formula.operator.family).lower()
    formula_symbol = _clean_non_empty_string(formula.operator.symbol)
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
) -> List[tuple[str, str]]:
    cue_value = _clean_non_empty_string(cue).lower()
    if not cue_value:
        return []
    matching_pairs: List[tuple[str, str]] = []
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        profile_family = _clean_non_empty_string(profile.family.value).lower()
        if profile_family not in _CUE_REGISTRY_BRIDGE_FAMILIES:
            continue
        for operator in profile.operators:
            if not any(
                _cue_matches_registry_term(cue_value, cue_term)
                for cue_term in operator.cue_terms
            ):
                continue
            operator_symbol = _clean_non_empty_string(operator.symbol)
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
) -> List[tuple[str, str]]:
    normalized_cue = _clean_non_empty_string(cue).lower()
    if not normalized_cue:
        return []
    cue_key = normalized_cue.replace(" ", "_")
    candidates: List[tuple[str, str]] = []
    candidates.extend(_registry_cue_operator_matches(cue=normalized_cue))
    candidates.extend(_CROSS_FAMILY_BRIDGE_CUE_OPERATOR_PAIRS.get(cue_key, ()))
    unique_pairs: List[tuple[str, str]] = []
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
        pair = (_clean_non_empty_string(family).lower(), _clean_non_empty_string(symbol))
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
    bridge_pairs: Sequence[tuple[str, str]],
    formula_family: str,
    formula_symbol: str,
    cue: str,
) -> List[tuple[str, str]]:
    normalized_family = _clean_non_empty_string(formula_family).lower()
    normalized_symbol = _clean_non_empty_string(formula_symbol)
    normalized_cue = _clean_non_empty_string(cue).lower()
    pairs: List[tuple[str, str]] = []
    for family, symbol in bridge_pairs:
        normalized_pair = (
            _clean_non_empty_string(family).lower(),
            _clean_non_empty_string(symbol),
        )
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
        normalized_family == "epistemic"
        and cue_key in _EPISTEMIC_DEONTIC_BRIDGE_CUES
    ):
        epistemic_deontic_pair = ("deontic", "O")
        if epistemic_deontic_pair not in pairs:
            pairs.append(epistemic_deontic_pair)
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
        # Keep scoped statutory cross-references typed across family lanes
        # so permission/deadline clauses can round-trip into deontic+frame slots.
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
        _clean_non_empty_string(cue_value).replace("_", " ").lower()
    )
    normalized_term_tokens = _CUE_TOKEN_RE.findall(
        _clean_non_empty_string(cue_term).replace("_", " ").lower()
    )
    return bool(normalized_cue_tokens) and normalized_cue_tokens == normalized_term_tokens


def _text_contains_cue_term(text: str, cue_term: str) -> bool:
    normalized_text = _clean_non_empty_string(text).lower()
    normalized_term = _clean_non_empty_string(cue_term).lower()
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
    normalized = _clean_non_empty_string(cue).lower()
    return normalized.startswith("__") and normalized.endswith("__")


def _cue_alias_predicate_name(predicate: str) -> str:
    normalized_predicate = _clean_non_empty_string(predicate)
    if normalized_predicate.startswith("cue_modal_"):
        return f"modal_cue_{normalized_predicate[len('cue_modal_') :]}"
    if normalized_predicate.startswith("cue_"):
        return f"modal_cue_{normalized_predicate[len('cue_') :]}"
    return ""


def _modal_operator_feature_key(symbol: str) -> str:
    normalized_symbol = _clean_non_empty_string(symbol)
    if not normalized_symbol:
        return ""
    mapped_symbol = _MODAL_OPERATOR_SYMBOL_FEATURE_KEYS.get(normalized_symbol)
    if mapped_symbol:
        return mapped_symbol
    tokens = _CUE_TOKEN_RE.findall(normalized_symbol.lower())
    if not tokens:
        return ""
    return "_".join(tokens)


def _slot_safe_family_key(value: str) -> str:
    normalized = re.sub(
        r"[^a-z0-9_]+",
        "_",
        _clean_non_empty_string(value).lower(),
    ).strip("_")
    return normalized


def _slot_safe_family_pair_key(value: str) -> str:
    normalized = _clean_non_empty_string(value).lower()
    if not normalized:
        return ""
    if "->" in normalized:
        left_raw, right_raw = normalized.split("->", 1)
        left = _slot_safe_family_key(left_raw)
        right = _slot_safe_family_key(right_raw)
        if left and right:
            return f"{left}_{right}"
    return _slot_safe_family_key(normalized)


def _modal_operator_pair_feature_key(
    source_symbol: str,
    target_symbol: str,
) -> str:
    source_key = _modal_operator_feature_key(source_symbol)
    target_key = _modal_operator_feature_key(target_symbol)
    if not source_key or not target_key:
        return ""
    return f"{source_key}_to_{target_key}"


def _modal_lexeme_components(
    formula: ModalIRFormula,
    *,
    cue: str,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    cue_value = _clean_non_empty_string(cue).lower()
    family = _clean_non_empty_string(formula.operator.family).lower()
    symbol = _clean_non_empty_string(formula.operator.symbol)
    normalized_slot_prefix = _clean_non_empty_string(slot_prefix)
    if not cue_value or not family or not symbol or not normalized_slot_prefix:
        return []
    alias_prefix = ""
    if normalized_slot_prefix.endswith("_modal"):
        alias_prefix = _clean_non_empty_string(normalized_slot_prefix[: -len("_modal")])
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
    components: List[tuple[str, str]] = [
        (f"{normalized_slot_prefix}_signature", signature),
        (f"{normalized_slot_prefix}_family", family),
        (f"{normalized_slot_prefix}_operator", symbol),
        (f"{normalized_slot_prefix}_lexeme", cue_value),
    ]
    canonical_symbol = _canonical_cue_operator_symbol(formula, cue=cue_value)
    if canonical_symbol:
        components.append(
            (f"{normalized_slot_prefix}_canonical_operator", canonical_symbol)
        )
        components.append(
            (
                f"{normalized_slot_prefix}_canonical_signature",
                f"{family}:{canonical_symbol}:{cue_value}",
            )
        )
        components.append(
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
        components.append((f"{normalized_slot_prefix}_registry_family", registry_family))
        components.append((f"{normalized_slot_prefix}_registry_operator", registry_symbol))
        components.append((f"{normalized_slot_prefix}_registry_signature", registry_signature))
        components.append((f"{normalized_slot_prefix}_registry_alignment", registry_alignment))
        components.append(
            (
                f"{normalized_slot_prefix}_registry_family_pair",
                f"{family}->{registry_family}",
            )
        )
        registry_family_pair_key = _slot_safe_family_pair_key(
            f"{family}->{registry_family}"
        )
        if registry_family_pair_key:
            components.append(
                (
                    f"{normalized_slot_prefix}_registry_family_pair_key",
                    registry_family_pair_key,
                )
            )
        components.append(
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
            components.append(
                (
                    f"{normalized_slot_prefix}_registry_operator_pair_key",
                    registry_operator_pair_key,
                )
            )
        if registry_family != family or registry_symbol != symbol:
            bridged_value = f"{registry_symbol}:{cue_value}"
            components.append((f"{normalized_slot_prefix}_{registry_family}", bridged_value))
            components.append(
                (
                    f"{normalized_slot_prefix}_{registry_family}_signature",
                    registry_signature,
                )
            )
            if alias_prefix:
                components.append(
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
        components.append(
            (
                f"{normalized_slot_prefix}_bridge_family_pair",
                bridge_family_pair,
            )
        )
        if bridge_family_pair_key:
            components.append(
                (
                    f"{normalized_slot_prefix}_bridge_family_pair_key",
                    bridge_family_pair_key,
                )
            )
        components.append(
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
            components.append(
                (
                    f"{normalized_slot_prefix}_bridge_operator_pair_key",
                    bridge_operator_pair_key,
                )
            )
        if alias_prefix:
            components.append((f"{alias_prefix}_bridge_family_pair", bridge_family_pair))
            if bridge_family_pair_key:
                components.append(
                    (f"{alias_prefix}_bridge_family_pair_key", bridge_family_pair_key)
                )
            components.append((f"{alias_prefix}_bridge_operator_pair", bridge_operator_pair))
        if bridge_family == family and bridge_symbol == symbol:
            components.append((f"{normalized_slot_prefix}_self_bridge_family", bridge_family))
            components.append((f"{normalized_slot_prefix}_self_bridge_operator", bridge_symbol))
            components.append((f"{normalized_slot_prefix}_self_bridge_signature", bridge_signature))
            if alias_prefix:
                components.append((f"{alias_prefix}_self_bridge_family", bridge_family))
                components.append((f"{alias_prefix}_self_bridge_operator", bridge_symbol))
                components.append((f"{alias_prefix}_self_bridge_signature", bridge_signature))
            if not reinforce_deontic_self_bridge:
                continue
        bridge_value = f"{bridge_symbol}:{cue_value}"
        components.append((f"{normalized_slot_prefix}_bridge_family", bridge_family))
        components.append((f"{normalized_slot_prefix}_bridge_operator", bridge_symbol))
        components.append((f"{normalized_slot_prefix}_bridge_signature", bridge_signature))
        components.append((f"{normalized_slot_prefix}_bridge_{bridge_family}", bridge_value))
        if alias_prefix:
            components.append((f"{alias_prefix}_bridge_family", bridge_family))
            components.append((f"{alias_prefix}_bridge_operator", bridge_symbol))
            components.append((f"{alias_prefix}_bridge_signature", bridge_signature))
            components.append((f"{alias_prefix}_{bridge_family}", bridge_value))
    if symbol == "O|":
        conditional_normative_value = f"{symbol}:{cue_value}"
        components.append(
            (
                f"{normalized_slot_prefix}_conditional_normative",
                conditional_normative_value,
            )
        )
        components.append(
            (
                f"{normalized_slot_prefix}_conditional_normative_signature",
                f"conditional_normative:{conditional_normative_value}",
            )
        )
        if alias_prefix:
            components.append(
                (
                    f"{alias_prefix}_conditional_normative",
                    conditional_normative_value,
                )
            )
    temporal_relation = _temporal_clause_prefix_relation(cue_value)
    if temporal_relation:
        components.append(
            (f"{normalized_slot_prefix}_temporal_relation", temporal_relation)
        )
    return components


def _condition_proxy_components_from_exception(
    formula: ModalIRFormula,
    *,
    exception: str,
) -> List[tuple[str, str]]:
    scoped_exception = _clean_non_empty_string(exception)
    if not scoped_exception:
        return []
    components: List[tuple[str, str]] = [("condition", scoped_exception)]
    components.extend(
        _typed_identifier_components(
            scoped_exception,
            slot_prefix="condition",
        )
    )
    typed_exception = _typed_clause_key_value(scoped_exception, clause_type="exception")
    if typed_exception is None:
        return _unique_preserve_order_tuples(components)
    key, scoped_value = typed_exception
    components.append(("condition_prefix", key.replace("_", " ")))
    components.append(("condition_prefix_key", key))
    components.extend(
        _modal_lexeme_components(
            formula,
            cue=key,
            slot_prefix="condition_modal",
        )
    )
    temporal_relation = _temporal_clause_prefix_relation(key)
    if temporal_relation:
        components.append(("condition_prefix_family", "temporal"))
        components.append(("condition_prefix_temporal_relation", temporal_relation))
    if scoped_value:
        components.append((f"condition_{key}", scoped_value))
        components.append(("condition_scope", scoped_value))
        components.extend(
            _typed_identifier_components(
                scoped_value,
                slot_prefix="condition_scope",
            )
        )
        components.extend(
            _contextual_modal_cue_components(
                formula,
                text=scoped_value,
                slot_prefix="condition_scope",
            )
        )
        components.extend(
            _content_scope_components(
                scoped_value,
                slot_prefix="condition_scope",
            )
        )
    return _unique_preserve_order_tuples(components)


def _content_scope_components(
    text: str,
    *,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    content_value = _content_scope_value(text)
    if not content_value:
        return []
    components: List[tuple[str, str]] = [
        (f"{slot_prefix}_content", content_value)
    ]
    components.extend(
        _typed_identifier_components(
            content_value,
            slot_prefix=f"{slot_prefix}_content",
        )
    )
    return _unique_preserve_order_tuples(components)


def _content_scope_value(text: str) -> str:
    normalized = _clean_non_empty_string(text)
    if not normalized:
        return ""
    tokens = normalized.split()
    while tokens and tokens[0].lower() in _LOW_INFORMATION_SCOPE_LEADING_TOKENS:
        tokens = tokens[1:]
    if not tokens:
        return ""
    content = _clean_non_empty_string(" ".join(tokens))
    if not content or content.lower() == normalized.lower():
        return ""
    content_tokens = _CUE_TOKEN_RE.findall(content.lower())
    if len(content_tokens) == 1 and (
        content_tokens[0] in _LOW_INFORMATION_SECTION_MARKER_TOKENS
        or content_tokens[0] in _LOW_INFORMATION_SECTION_MARKER_SINGLE_CHAR_TOKENS
    ):
        return ""
    return content


def _temporal_clause_prefix_relation(prefix_key: str) -> str:
    normalized_key = _clean_non_empty_string(prefix_key).lower()
    if not normalized_key:
        return ""
    return _TEMPORAL_CLAUSE_PREFIX_RELATIONS.get(normalized_key, "")


def _text_has_prefix(text: str, prefix: str) -> bool:
    normalized_text = _clean_non_empty_string(text).lower()
    normalized_prefix = _clean_non_empty_string(prefix).lower()
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
    predicate_text = _clean_non_empty_string(formula.predicate.name).replace(
        "_",
        " ",
    ).lower()
    if predicate_text:
        searchable_segments.append(predicate_text)
    searchable_segments.extend(
        _clean_non_empty_string(value).replace("_", " ").lower()
        for value in (*formula.conditions, *formula.exceptions)
        if _clean_non_empty_string(value)
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
        cue_key = _clean_non_empty_string(cue).lower().replace(" ", "_")
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
    for clause_type, clauses in (
        ("condition", formula.conditions),
        ("exception", formula.exceptions),
    ):
        for clause in clauses:
            typed_clause = _typed_clause_key_value(clause, clause_type=clause_type)
            if typed_clause is None:
                continue
            prefix_key, _ = typed_clause
            cue = _clean_non_empty_string(prefix_key).lower()
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
        cue = _clean_non_empty_string(cue_candidate).lower()
        if cue and cue not in cues:
            cues.append(cue)
    return cues


def _modal_transition_components(formula: ModalIRFormula) -> List[tuple[str, str]]:
    source_family = _clean_non_empty_string(formula.operator.family).lower()
    source_operator = _clean_non_empty_string(formula.operator.symbol)
    if not source_family or not source_operator:
        return []
    components: List[tuple[str, str]] = [
        ("modal_family_transition_pair", f"{source_family}->{source_family}"),
        ("modal_operator_transition_pair", f"{source_operator}->{source_operator}"),
        ("modal_transition_signature", f"{source_family}:{source_operator}"),
    ]
    for cue in _formula_transition_cues(formula):
        source_signature = f"{source_family}:{source_operator}:{cue}"
        components.append(("modal_transition_cue", cue))
        components.append(("modal_transition_source_signature", source_signature))
        transition_pairs: List[tuple[str, str]] = [(source_family, source_operator)]
        transition_pairs.extend(
            _augment_deontic_bridge_pairs(
                bridge_pairs=_cue_bridge_operator_pairs(cue),
                formula_family=source_family,
                formula_symbol=source_operator,
                cue=cue,
            )
        )
        for target_family, target_operator in transition_pairs:
            normalized_target_family = _clean_non_empty_string(target_family).lower()
            normalized_target_operator = _clean_non_empty_string(target_operator)
            if not normalized_target_family or not normalized_target_operator:
                continue
            family_pair = f"{source_family}->{normalized_target_family}"
            operator_pair = f"{source_operator}->{normalized_target_operator}"
            target_signature = (
                f"{normalized_target_family}:{normalized_target_operator}:{cue}"
            )
            components.extend(
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
    return _unique_preserve_order_tuples(components)


def _contextual_modal_cues_from_text(
    formula: ModalIRFormula,
    *,
    text: str,
) -> List[str]:
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
    if not normalized_text:
        return []

    candidate_terms: List[str] = []
    candidate_terms.extend(
        _clean_non_empty_string(term).replace("_", " ").lower()
        for term in _operator_cue_terms(formula)
        if _clean_non_empty_string(term)
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
    normalized = _clean_non_empty_string(token).lower()
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
    normalized_text = _clean_non_empty_string(text).lower()
    normalized_term = _clean_non_empty_string(cue_term).lower()
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
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    candidate_terms: List[str] = []
    candidate_terms.extend(
        _clean_non_empty_string(term).replace("_", " ").lower()
        for term in _operator_cue_terms(formula)
        if _clean_non_empty_string(term)
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
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
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


def _temporal_structural_frame_context_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues = _structural_frame_cues_from_text(normalized_text)
    if not cues:
        return []
    if _is_probable_uscode_compilation_span(text):
        return cues
    if _STATUTORY_SCOPE_REFERENCE_RE.search(normalized_text):
        return cues
    if _STRUCTURAL_HEADING_SPAN_RE.search(normalized_text):
        return cues
    if _temporal_transition_context_cues_from_text(normalized_text):
        return [cue for cue in cues if cue != "title"]
    return []


@lru_cache(maxsize=1)
def _bridge_registry_cue_terms() -> tuple[str, ...]:
    terms: set[str] = set()
    supported_families = set(_CUE_REGISTRY_BRIDGE_FAMILIES)
    supported_families.add("frame")
    for profile in DEFAULT_MODAL_REGISTRY.all_profiles():
        profile_family = _clean_non_empty_string(profile.family.value).lower()
        if profile_family not in supported_families:
            continue
        for operator in profile.operators:
            for cue_term in operator.cue_terms:
                normalized_term = _clean_non_empty_string(cue_term).replace("_", " ").lower()
                if normalized_term:
                    terms.add(normalized_term)
    return tuple(
        sorted(
            terms,
            key=lambda item: (-len(item.split()), -len(item), item),
        )
    )


def _bridge_registry_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
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
) -> List[tuple[str, str]]:
    normalized_cue = _clean_non_empty_string(cue).lower()
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
    unique_pairs: List[tuple[str, str]] = []
    for family, symbol in pairs:
        normalized_family = _clean_non_empty_string(family).lower()
        normalized_symbol = _clean_non_empty_string(symbol)
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
    normalized_cue = _clean_non_empty_string(cue).lower()
    if normalized_cue not in _STRUCTURAL_FRAME_CUE_TOKENS:
        return False
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
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
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    cues: List[str] = []
    for cue_key in _FRAME_REFINED_STATUS_DEONTIC_CUES:
        cue_surface = cue_key.replace("_", " ")
        if cue_surface and _text_contains_cue_term(normalized_text, cue_surface):
            cues.append(cue_key)
    return cues


def _temporal_alethic_bridge_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
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
    formula_family = _clean_non_empty_string(formula.operator.family).lower()
    temporal_context_cues = _temporal_transition_context_cues_from_text(text)
    temporal_structural_cues = _temporal_structural_frame_context_cues_from_text(text)
    cues: List[str] = []
    for cue in _contextual_modal_cues_from_text(formula, text=text):
        if cue and cue not in cues:
            cues.append(cue)
    for cue in _stem_refined_modal_cues_from_text(formula, text=text):
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
    elif formula_family == "temporal" and (
        temporal_context_cues or temporal_structural_cues
    ):
        # Temporal formulas often carry frame-like statute scaffolding tokens
        # ("title", "chapter", "subchapter") inside compilation spans.
        # Admit structural cues only for real statute scope/heading contexts,
        # so ordinary noun uses such as "title updates" stay filtered.
        for cue in temporal_context_cues:
            if cue and cue not in cues:
                cues.append(cue)
        for cue in temporal_structural_cues:
            if cue and cue not in cues:
                cues.append(cue)
    elif formula_family == "temporal":
        for cue in _temporal_transition_context_cues_from_text(text):
            normalized_cue = _clean_non_empty_string(cue).lower()
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


def _refined_contextual_modal_transition_components(
    formula: ModalIRFormula,
    *,
    text: str,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    normalized_slot_prefix = _clean_non_empty_string(slot_prefix)
    formula_family = _clean_non_empty_string(formula.operator.family).lower()
    formula_symbol = _clean_non_empty_string(formula.operator.symbol)
    if not normalized_slot_prefix or not formula_family or not formula_symbol:
        return []
    components: List[tuple[str, str]] = []
    for cue in _refined_contextual_modal_cues_from_text(formula, text=text):
        normalized_cue = _clean_non_empty_string(cue).lower()
        if not normalized_cue:
            continue
        source_signature = f"{formula_family}:{formula_symbol}:{normalized_cue}"
        components.extend(
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
            components.extend(
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
            if operator_pair_key:
                components.extend(
                    (
                        (
                            f"{normalized_slot_prefix}_refined_modal_operator_pair_key",
                            operator_pair_key,
                        ),
                        ("refined_modal_operator_pair_key", operator_pair_key),
                    )
                )
        components.extend(
            _refined_temporal_transition_components(
                formula=formula,
                cue=normalized_cue,
                text=text,
                slot_prefix=normalized_slot_prefix,
            )
        )
    components.extend(
        _refined_heading_transition_components(
            formula=formula,
            text=text,
            slot_prefix=normalized_slot_prefix,
        )
    )
    return _unique_preserve_order_tuples(components)


def _temporal_transition_context_cues_from_text(text: str) -> List[str]:
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
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


def _refined_temporal_transition_components(
    *,
    formula: ModalIRFormula,
    cue: str,
    text: str,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    normalized_slot_prefix = _clean_non_empty_string(slot_prefix)
    normalized_cue = _clean_non_empty_string(cue).lower()
    formula_family = _clean_non_empty_string(formula.operator.family).lower()
    formula_symbol = _clean_non_empty_string(formula.operator.symbol)
    if (
        not normalized_slot_prefix
        or not normalized_cue
        or formula_family not in {"deontic", "frame", "temporal"}
    ):
        return []
    context_cues = _temporal_transition_context_cues_from_text(text)
    structural_context_cues = _temporal_structural_frame_context_cues_from_text(text)
    if (
        formula_family == "temporal"
        and normalized_cue in structural_context_cues
        and normalized_cue not in context_cues
    ):
        context_cues.append(normalized_cue)
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
    bridge_targets: List[tuple[str, str]] = []

    def add_bridge_target(family: str, symbol: str) -> None:
        normalized_family = _clean_non_empty_string(family).lower()
        normalized_symbol = _clean_non_empty_string(symbol)
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

    components: List[tuple[str, str]] = []
    for bridge_family, bridge_symbol in bridge_targets:
        pair = f"{formula_family}->{bridge_family}"
        pair_key = _slot_safe_family_pair_key(pair)
        operator_pair = f"{formula_symbol}->{bridge_symbol}"
        operator_pair_key = _modal_operator_pair_feature_key(
            formula_symbol,
            bridge_symbol,
        )
        signature = f"{bridge_family}:{bridge_symbol}:{normalized_cue}"
        components.extend(
            (
                (f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair", pair),
                (f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair_key", pair_key),
                (f"{normalized_slot_prefix}_refined_temporal_bridge_family_pair", pair_key),
                (f"{normalized_slot_prefix}_refined_temporal_bridge_operator_pair", operator_pair),
                (f"{normalized_slot_prefix}_refined_temporal_bridge_signature", signature),
                (
                    f"{normalized_slot_prefix}_refined_temporal_bridge_pair_cue",
                    f"{pair}:{normalized_cue}",
                ),
                ("refined_temporal_bridge_family_pair", pair),
                ("refined_temporal_bridge_family_pair_key", pair_key),
                ("refined_temporal_bridge_family_pair", pair_key),
                ("refined_temporal_bridge_operator_pair", operator_pair),
                ("refined_temporal_bridge_signature", signature),
                ("refined_temporal_bridge_pair_cue", f"{pair}:{normalized_cue}"),
                ("refined_temporal_bridge_context_slot", normalized_slot_prefix),
                (
                    "refined_temporal_bridge_context_pair",
                    f"{normalized_slot_prefix}:{pair}",
                ),
                (
                    "refined_temporal_bridge_context_pair",
                    f"{normalized_slot_prefix}_{pair_key}",
                ),
            )
        )
        if operator_pair_key:
            components.extend(
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
            components.extend(
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
    return _unique_preserve_order_tuples(components)


def _refined_heading_bridge_pairs_from_text(
    text: str,
) -> List[tuple[str, str, str]]:
    normalized_text = _clean_non_empty_string(text).replace("_", " ").lower()
    if not normalized_text:
        return []
    pairs: List[tuple[str, str, str]] = []
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
            normalized_family = _clean_non_empty_string(target_family).lower()
            normalized_symbol = _clean_non_empty_string(target_symbol)
            if not normalized_family or not normalized_symbol:
                continue
            pair = (cue_key, normalized_family, normalized_symbol)
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def _refined_heading_transition_components(
    *,
    formula: ModalIRFormula,
    text: str,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    normalized_slot_prefix = _clean_non_empty_string(slot_prefix)
    formula_family = _clean_non_empty_string(formula.operator.family).lower()
    if (
        not normalized_slot_prefix
        or formula_family not in _REFINED_HEADING_BRIDGE_SOURCE_FAMILIES
    ):
        return []
    components: List[tuple[str, str]] = []
    for cue_key, target_family, target_symbol in _refined_heading_bridge_pairs_from_text(
        text
    ):
        pair = f"{formula_family}->{target_family}"
        signature = f"{target_family}:{target_symbol}:{cue_key}"
        pair_cue = f"{pair}:{cue_key}"
        components.extend(
            (
                (f"{normalized_slot_prefix}_refined_heading_bridge_cue", cue_key),
                (
                    f"{normalized_slot_prefix}_refined_heading_bridge_family_pair",
                    pair,
                ),
                (
                    f"{normalized_slot_prefix}_refined_heading_bridge_signature",
                    signature,
                ),
                (
                    f"{normalized_slot_prefix}_refined_heading_bridge_pair_cue",
                    pair_cue,
                ),
                ("refined_heading_bridge_cue", cue_key),
                ("refined_heading_bridge_family_pair", pair),
                ("refined_heading_bridge_signature", signature),
                ("refined_heading_bridge_pair_cue", pair_cue),
                ("refined_heading_bridge_context_slot", normalized_slot_prefix),
                (
                    "refined_heading_bridge_context_pair",
                    f"{normalized_slot_prefix}:{pair}",
                ),
            )
        )
    return _unique_preserve_order_tuples(components)


def _contextual_modal_cue_components(
    formula: ModalIRFormula,
    *,
    text: str,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    normalized_slot_prefix = _clean_non_empty_string(slot_prefix)
    if not normalized_slot_prefix:
        return []
    components: List[tuple[str, str]] = []
    for cue in _contextual_modal_cues_from_text(formula, text=text):
        components.append((f"{normalized_slot_prefix}_cue", cue))
        components.append((f"{normalized_slot_prefix}_modal_cue", cue))
        components.extend(
            _modal_lexeme_components(
                formula,
                cue=cue,
                slot_prefix=f"{normalized_slot_prefix}_modal",
            )
        )
    components.extend(
        _refined_contextual_modal_transition_components(
            formula,
            text=text,
            slot_prefix=normalized_slot_prefix,
        )
    )
    return _unique_preserve_order_tuples(components)


def _status_keyword_value(
    formula: ModalIRFormula,
    *,
    fallback_rule: str,
) -> str:
    explicit = _clean_non_empty_string(formula.metadata.get("status_keyword")).lower()
    if explicit:
        return explicit
    normalized_rule = _clean_non_empty_string(fallback_rule).lower()
    if normalized_rule not in _USCODE_STATUS_DERIVATION_RULES:
        return ""
    predicate_text = _clean_non_empty_string(formula.predicate.name).replace("_", " ").lower()
    for keyword in _USCODE_FALLBACK_STATUS_KEYWORDS:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", predicate_text):
            return keyword
    if normalized_rule in {
        "uscode_transferred_heading_v1",
        "uscode_codification_transfer_heading_v1",
    }:
        return "transferred"
    return ""


def _status_keyword_modal_components(
    formula: ModalIRFormula,
    *,
    status_keyword: str,
    slot_prefix: str = "status_keyword_modal",
) -> List[tuple[str, str]]:
    normalized_keyword = _clean_non_empty_string(status_keyword).lower().replace(" ", "_")
    normalized_slot_prefix = _clean_non_empty_string(slot_prefix)
    formula_family = _clean_non_empty_string(formula.operator.family).lower()
    formula_symbol = _clean_non_empty_string(formula.operator.symbol)
    if (
        not normalized_keyword
        or not normalized_slot_prefix
        or not formula_family
        or not formula_symbol
    ):
        return []
    components: List[tuple[str, str]] = list(
        _modal_lexeme_components(
            formula,
            cue=normalized_keyword,
            slot_prefix=normalized_slot_prefix,
        )
    )
    for bridge_family, bridge_symbol in _STATUS_KEYWORD_BRIDGE_OPERATOR_PAIRS.get(
        normalized_keyword,
        (),
    ):
        normalized_bridge_family = _clean_non_empty_string(bridge_family).lower()
        normalized_bridge_symbol = _clean_non_empty_string(bridge_symbol)
        if not normalized_bridge_family or not normalized_bridge_symbol:
            continue
        bridge_signature = (
            f"{normalized_bridge_family}:{normalized_bridge_symbol}:{normalized_keyword}"
        )
        family_pair = f"{formula_family}->{normalized_bridge_family}"
        family_pair_key = _slot_safe_family_pair_key(family_pair)
        operator_pair = f"{formula_symbol}->{normalized_bridge_symbol}"
        components.extend(
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
    return _unique_preserve_order_tuples(components)


def _citation_components(citation: str) -> List[tuple[str, str]]:
    cleaned = _clean_non_empty_string(citation)
    if not cleaned:
        return []
    match = _USC_CITATION_RE.match(cleaned)
    if not match:
        return []
    title = _clean_non_empty_string(match.group("title"))
    raw_section = _clean_non_empty_string(match.group("section"))
    section = _TRAILING_SECTION_PUNCT_RE.sub("", raw_section)
    section_trailing_punct = _section_trailing_punct(
        raw_section=raw_section,
        normalized_section=section,
    )
    components: List[tuple[str, str]] = []
    title_number = ""
    if title:
        components.append(("citation_title", title))
        components.extend(_typed_identifier_components(title, slot_prefix="citation_title"))
        title_match = _CITATION_SECTION_PART_RE.fullmatch(title)
        if title_match:
            title_number = _clean_non_empty_string(title_match.group("number"))
            title_suffix = _clean_non_empty_string(title_match.group("suffix"))
            if title_number:
                components.append(("citation_title_number", title_number))
                components.extend(
                    _numeric_signature_components(
                        title_number,
                        slot_prefix="citation_title_number",
                    )
                )
            if title_suffix:
                components.append(("citation_title_suffix", title_suffix))
    components.append(("citation_code", "U.S.C."))
    if section:
        citation_canonical = _canonical_usc_citation(title, section)
        if citation_canonical:
            components.append(("citation_canonical", citation_canonical))
        citation_title_section_key = _title_section_coordinate(title, section)
        if citation_title_section_key:
            components.append(("citation_title_section_key", citation_title_section_key))
            components.append(
                (
                    "citation_title_section_key_normalized",
                    citation_title_section_key.lower(),
                )
            )
            components.extend(
                _typed_identifier_components(
                    citation_title_section_key.replace(":", "_"),
                    slot_prefix="citation_title_section_key",
                )
            )
        components.append(("citation_section", section))
        if raw_section:
            components.append(("citation_section_raw", raw_section))
        components.append(("citation_section_normalized", section))
        if section_trailing_punct:
            components.append(("citation_section_trailing_punct", section_trailing_punct))
            components.append(("citation_section_has_trailing_punct", "true"))
            components.append(
                (
                    "citation_section_trailing_punct_count",
                    str(len(section_trailing_punct)),
                )
            )
            punct_kind = _section_trailing_punct_kind(section_trailing_punct)
            if punct_kind:
                components.append(("citation_section_trailing_punct_kind", punct_kind))
        else:
            components.append(("citation_section_has_trailing_punct", "false"))
            components.append(("citation_section_trailing_punct_count", "0"))
        section_components = _citation_section_components(section)
        components.extend(section_components)
        section_component_map = _component_value_map(section_components)
        components.extend(
            _section_style_components(
                slot_namespace="citation",
                section_component_map=section_component_map,
                has_trailing_punct=bool(section_trailing_punct),
            )
        )
        citation_style_map = _component_value_map(
            [
                component
                for component in components
                if component[0]
                in {"citation_section_style", "citation_section_style_canonical"}
            ]
        )
        components.extend(
            _title_section_style_components(
                slot_namespace="citation",
                title=title,
                section_style=_clean_non_empty_string(
                    citation_style_map.get("citation_section_style")
                ),
                section_style_canonical=_clean_non_empty_string(
                    citation_style_map.get("citation_section_style_canonical")
                ),
            )
        )
        components.extend(
            _section_structure_components(
                slot_namespace="citation",
                title=title,
                section_signature=_clean_non_empty_string(
                    section_component_map.get("citation_section_signature")
                ),
                section_profile=_clean_non_empty_string(
                    section_component_map.get("citation_section_component_profile")
                ),
            )
        )
        components.extend(
            _title_section_number_relation_components(
                slot_namespace="citation",
                title_number=title_number,
                section_component_map=section_component_map,
            )
        )
        components.extend(
            _typed_identifier_components(
                section,
                slot_prefix="citation_section",
            )
        )
    return _unique_preserve_order_tuples(components)


def _decompiler_section_cue_components(
    *,
    formula: ModalIRFormula,
    source_id: str,
    citation: str,
) -> List[tuple[str, str]]:
    """Mirror decompiler section-cue slots in direct F-logic projection."""

    family = _slot_safe_family_key(
        _clean_non_empty_string(formula.operator.family).lower()
    )
    role = _slot_safe_family_key(
        _clean_non_empty_string(formula.predicate.role or "clause").lower()
    ) or "clause"
    if not family:
        return []
    source_system = _slot_safe_family_key(
        _clean_non_empty_string(formula.operator.system).lower()
    )
    source_operator = _clean_non_empty_string(formula.operator.symbol)
    source_operator_key = _modal_operator_feature_key(source_operator)
    components: List[tuple[str, str]] = []
    seen_coordinates: set[tuple[str, str, str, str]] = set()

    def add(predicate: str, value: str) -> None:
        cleaned_predicate = _clean_non_empty_string(predicate)
        cleaned_value = _clean_non_empty_string(value)
        if cleaned_predicate and cleaned_value:
            components.append((cleaned_predicate, cleaned_value))

    def add_from_map(prefix: str, component_map: Mapping[str, str]) -> None:
        title = _clean_non_empty_string(component_map.get(f"{prefix}_title"))
        section = _clean_non_empty_string(
            component_map.get(f"{prefix}_section_normalized")
            or component_map.get(f"{prefix}_section")
        )
        title_section_key = _clean_non_empty_string(
            component_map.get(f"{prefix}_title_section_key_normalized")
            or component_map.get(f"{prefix}_title_section_key")
        )
        if not title_section_key and title and section:
            title_section_key = _title_section_coordinate(title, section).lower()
        if not title and not section and not title_section_key:
            return
        coordinate = (prefix, title, section, title_section_key)
        if coordinate in seen_coordinates:
            return
        seen_coordinates.add(coordinate)
        source_label = "citation" if prefix == "citation" else "source_id"
        if title:
            add("section_token", f"{title}:title")
            add("section_cue", f"{title}:title:{family}")
            add("decompiler_plan_section_cue", f"{title}:title:{family}")
            add("decompiler_plan_section_role", f"{title}:title:{role}")
            add(f"{source_label}_section_cue", f"{title}:title:{family}")
        if section:
            add("section_token", f"{section}:section")
            add("section_cue", f"{section}:section:{family}")
            add("decompiler_plan_section_cue", f"{section}:section:{family}")
            add("decompiler_plan_section_role", f"{section}:section:{role}")
            add(f"{source_label}_section_cue", f"{section}:section:{family}")
            if source_system and source_operator_key:
                add(
                    "section_cue_operator",
                    f"{section}:{family}:{source_system}:{source_operator_key}",
                )
            elif source_operator:
                add("section_cue_operator", f"{section}:{family}:{source_operator}")
        if title_section_key:
            add("section_title_coordinate", title_section_key)
            add("section_cue", f"{title_section_key}:coordinate:{family}")
            add(
                "decompiler_plan_section_cue",
                f"{title_section_key}:coordinate:{family}",
            )
            add(
                f"{source_label}_section_cue",
                f"{title_section_key}:coordinate:{family}",
            )

    if citation:
        add_from_map("citation", _component_value_map(_citation_components(citation)))
    if source_id:
        add_from_map("source_id", _component_value_map(_source_id_components(source_id)))
    return _unique_preserve_order_tuples(components)


def _source_id_components(source_id: str) -> List[tuple[str, str]]:
    cleaned = _clean_non_empty_string(source_id)
    if not cleaned:
        return []
    match = _USCODE_SOURCE_ID_RE.match(cleaned)
    if not match:
        return [("source_id", cleaned)]

    scheme = _clean_non_empty_string(match.group("scheme")).lower()
    title = _clean_non_empty_string(match.group("title"))
    section = _clean_non_empty_string(match.group("section"))
    digest = _clean_non_empty_string(match.group("digest")).lower()
    normalized_section = _TRAILING_SECTION_PUNCT_RE.sub("", section)
    section_trailing_punct = _section_trailing_punct(
        raw_section=section,
        normalized_section=normalized_section,
    )
    section_for_components = normalized_section or section

    components: List[tuple[str, str]] = [
        ("source_id", cleaned),
        ("source_id_scheme", scheme),
    ]
    title_number = ""
    if title:
        components.append(("source_id_title", title))
        components.extend(
            _typed_identifier_components(
                title,
                slot_prefix="source_id_title",
            )
        )
        title_match = _CITATION_SECTION_PART_RE.fullmatch(title)
        if title_match:
            title_number = _clean_non_empty_string(title_match.group("number"))
            title_suffix = _clean_non_empty_string(title_match.group("suffix"))
            if title_number:
                components.append(("source_id_title_number", title_number))
                components.extend(
                    _numeric_signature_components(
                        title_number,
                        slot_prefix="source_id_title_number",
                    )
                )
            if title_suffix:
                components.append(("source_id_title_suffix", title_suffix))
    if section:
        components.append(("source_id_section", section))
        components.append(("source_id_section_raw", section))
    if normalized_section:
        components.append(("source_id_section_normalized", normalized_section))
    if section_trailing_punct:
        components.append(("source_id_section_trailing_punct", section_trailing_punct))
        components.append(("source_id_section_has_trailing_punct", "true"))
        components.append(
            (
                "source_id_section_trailing_punct_count",
                str(len(section_trailing_punct)),
            )
        )
        punct_kind = _section_trailing_punct_kind(section_trailing_punct)
        if punct_kind:
            components.append(("source_id_section_trailing_punct_kind", punct_kind))
    else:
        components.append(("source_id_section_has_trailing_punct", "false"))
        components.append(("source_id_section_trailing_punct_count", "0"))
    source_id_canonical = _canonical_usc_citation(title, section_for_components)
    if source_id_canonical:
        components.append(("source_id_citation_canonical", source_id_canonical))
    source_id_title_section_key = _title_section_coordinate(title, section_for_components)
    if source_id_title_section_key:
        components.append(("source_id_title_section_key", source_id_title_section_key))
        components.append(
            (
                "source_id_title_section_key_normalized",
                source_id_title_section_key.lower(),
            )
        )
        components.extend(
            _typed_identifier_components(
                source_id_title_section_key.replace(":", "_"),
                slot_prefix="source_id_title_section_key",
            )
        )
    if section_for_components:
        section_components = _citation_section_components(section_for_components)
        for predicate, value in section_components:
            if predicate.startswith("citation_section"):
                mapped = predicate.replace("citation_section", "source_id_section", 1)
                components.append((mapped, value))
        source_section_components = [
            (predicate, value)
            for predicate, value in components
            if predicate.startswith("source_id_section")
        ]
        source_section_component_map = _component_value_map(source_section_components)
        components.extend(
            _section_style_components(
                slot_namespace="source_id",
                section_component_map=source_section_component_map,
                has_trailing_punct=bool(section_trailing_punct),
            )
        )
        source_style_map = _component_value_map(
            [
                component
                for component in components
                if component[0]
                in {"source_id_section_style", "source_id_section_style_canonical"}
            ]
        )
        components.extend(
            _title_section_style_components(
                slot_namespace="source_id",
                title=title,
                section_style=_clean_non_empty_string(
                    source_style_map.get("source_id_section_style")
                ),
                section_style_canonical=_clean_non_empty_string(
                    source_style_map.get("source_id_section_style_canonical")
                ),
            )
        )
        components.extend(
            _section_structure_components(
                slot_namespace="source_id",
                title=title,
                section_signature=_clean_non_empty_string(
                    source_section_component_map.get("source_id_section_signature")
                ),
                section_profile=_clean_non_empty_string(
                    source_section_component_map.get("source_id_section_component_profile")
                ),
            )
        )
        components.extend(
            _title_section_number_relation_components(
                slot_namespace="source_id",
                title_number=title_number,
                section_component_map=source_section_component_map,
            )
        )
        components.extend(
            _typed_identifier_components(
                section_for_components,
                slot_prefix="source_id_section",
            )
        )
    if digest:
        components.append(("source_id_digest", digest))
    return _unique_preserve_order_tuples(components)


def _provenance_alignment_components(
    *,
    source_id: str,
    citation: str,
) -> List[tuple[str, str]]:
    normalized_source_id = _clean_non_empty_string(source_id)
    normalized_citation = _clean_non_empty_string(citation)
    if not normalized_source_id or not normalized_citation:
        return []
    source_component_map = _component_value_map(_source_id_components(normalized_source_id))
    citation_component_map = _component_value_map(_citation_components(normalized_citation))
    source_title = _clean_non_empty_string(source_component_map.get("source_id_title"))
    citation_title = _clean_non_empty_string(citation_component_map.get("citation_title"))
    source_section = _clean_non_empty_string(
        source_component_map.get("source_id_section_normalized")
        or source_component_map.get("source_id_section")
    )
    citation_section = _clean_non_empty_string(
        citation_component_map.get("citation_section_normalized")
        or citation_component_map.get("citation_section")
    )
    source_key = _clean_non_empty_string(
        source_component_map.get("source_id_title_section_key_normalized")
        or source_component_map.get("source_id_title_section_key")
    )
    citation_key = _clean_non_empty_string(
        citation_component_map.get("citation_title_section_key_normalized")
        or citation_component_map.get("citation_title_section_key")
    )
    source_canonical = _clean_non_empty_string(
        source_component_map.get("source_id_citation_canonical")
    )
    citation_canonical = _clean_non_empty_string(
        citation_component_map.get("citation_canonical")
    )
    source_section_raw = _clean_non_empty_string(
        source_component_map.get("source_id_section_raw")
        or source_component_map.get("source_id_section")
    )
    citation_section_raw = _clean_non_empty_string(
        citation_component_map.get("citation_section_raw")
        or citation_component_map.get("citation_section")
    )
    source_section_trailing_punct = _clean_non_empty_string(
        source_component_map.get("source_id_section_trailing_punct")
    )
    citation_section_trailing_punct = _clean_non_empty_string(
        citation_component_map.get("citation_section_trailing_punct")
    )
    source_has_trailing_punct = _clean_non_empty_string(
        source_component_map.get("source_id_section_has_trailing_punct")
        or ("true" if source_section_trailing_punct else "false")
    ).lower()
    citation_has_trailing_punct = _clean_non_empty_string(
        citation_component_map.get("citation_section_has_trailing_punct")
        or ("true" if citation_section_trailing_punct else "false")
    ).lower()
    components: List[tuple[str, str]] = []
    if source_section_raw and citation_section_raw:
        components.append(
            (
                "citation_source_id_section_raw_match",
                "true"
                if source_section_raw.lower() == citation_section_raw.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_raw_pair",
                f"{source_section_raw}|{citation_section_raw}",
            )
        )
    if (
        source_has_trailing_punct in {"true", "false"}
        and citation_has_trailing_punct in {"true", "false"}
    ):
        components.append(
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
        components.append(
            (
                "citation_source_id_section_trailing_punct_match",
                "true"
                if source_section_trailing_punct == citation_section_trailing_punct
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_trailing_punct_pair",
                f"{source_section_trailing_punct or 'none'}|"
                f"{citation_section_trailing_punct or 'none'}",
            )
        )
    if source_title and citation_title:
        components.append(
            (
                "citation_source_id_title_pair",
                f"{source_title}|{citation_title}",
            )
        )
    if source_section and citation_section:
        components.append(
            (
                "citation_source_id_section_pair",
                f"{source_section}|{citation_section}",
            )
        )
    if source_key and citation_key:
        components.append(
            (
                "citation_source_id_title_section_key_pair",
                f"{source_key}|{citation_key}",
            )
        )
    if source_canonical and citation_canonical:
        components.append(
            (
                "citation_source_id_canonical_pair",
                f"{source_canonical}|{citation_canonical}",
            )
        )
    source_section_signature = _clean_non_empty_string(
        source_component_map.get("source_id_section_signature")
    )
    citation_section_signature = _clean_non_empty_string(
        citation_component_map.get("citation_section_signature")
    )
    if source_section_signature or citation_section_signature:
        components.append(
            (
                "citation_source_id_section_signature_pair",
                f"{source_section_signature or 'none'}|"
                f"{citation_section_signature or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_signature_match",
                "true"
                if source_section_signature.lower()
                == citation_section_signature.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_signature_presence_match",
                "true"
                if bool(source_section_signature) == bool(citation_section_signature)
                else "false",
            )
        )
    source_section_profile = _clean_non_empty_string(
        source_component_map.get("source_id_section_component_profile")
    )
    citation_section_profile = _clean_non_empty_string(
        citation_component_map.get("citation_section_component_profile")
    )
    if source_section_profile or citation_section_profile:
        components.append(
            (
                "citation_source_id_section_profile_pair",
                f"{source_section_profile or 'none'}|"
                f"{citation_section_profile or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_profile_match",
                "true"
                if source_section_profile.lower() == citation_section_profile.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_profile_presence_match",
                "true"
                if bool(source_section_profile) == bool(citation_section_profile)
                else "false",
            )
        )
    source_section_style = _clean_non_empty_string(
        source_component_map.get("source_id_section_style")
    )
    citation_section_style = _clean_non_empty_string(
        citation_component_map.get("citation_section_style")
    )
    if source_section_style or citation_section_style:
        components.append(
            (
                "citation_source_id_section_style_pair",
                f"{source_section_style or 'none'}|{citation_section_style or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_style_match",
                "true"
                if source_section_style.lower() == citation_section_style.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_style_presence_match",
                "true"
                if bool(source_section_style) == bool(citation_section_style)
                else "false",
            )
        )
    source_section_style_canonical = _clean_non_empty_string(
        source_component_map.get("source_id_section_style_canonical")
    )
    citation_section_style_canonical = _clean_non_empty_string(
        citation_component_map.get("citation_section_style_canonical")
    )
    if source_section_style_canonical or citation_section_style_canonical:
        components.append(
            (
                "citation_source_id_section_style_canonical_pair",
                f"{source_section_style_canonical or 'none'}|"
                f"{citation_section_style_canonical or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_style_canonical_match",
                "true"
                if source_section_style_canonical.lower()
                == citation_section_style_canonical.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_style_canonical_presence_match",
                "true"
                if bool(source_section_style_canonical)
                == bool(citation_section_style_canonical)
                else "false",
            )
        )
    source_section_suffix_style = _clean_non_empty_string(
        source_component_map.get("source_id_section_suffix_style")
    )
    citation_section_suffix_style = _clean_non_empty_string(
        citation_component_map.get("citation_section_suffix_style")
    )
    if source_section_suffix_style or citation_section_suffix_style:
        components.append(
            (
                "citation_source_id_section_suffix_style_pair",
                f"{source_section_suffix_style or 'none'}|"
                f"{citation_section_suffix_style or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_suffix_style_match",
                "true"
                if source_section_suffix_style.lower()
                == citation_section_suffix_style.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_suffix_style_presence_match",
                "true"
                if bool(source_section_suffix_style)
                == bool(citation_section_suffix_style)
                else "false",
            )
        )
    source_section_punctuation_style = _clean_non_empty_string(
        source_component_map.get("source_id_section_punctuation_style")
    )
    citation_section_punctuation_style = _clean_non_empty_string(
        citation_component_map.get("citation_section_punctuation_style")
    )
    if source_section_punctuation_style or citation_section_punctuation_style:
        components.append(
            (
                "citation_source_id_section_punctuation_style_pair",
                f"{source_section_punctuation_style or 'none'}|"
                f"{citation_section_punctuation_style or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_punctuation_style_match",
                "true"
                if source_section_punctuation_style.lower()
                == citation_section_punctuation_style.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_punctuation_style_presence_match",
                "true"
                if bool(source_section_punctuation_style)
                == bool(citation_section_punctuation_style)
                else "false",
            )
        )
    source_title_section_signature = _clean_non_empty_string(
        source_component_map.get("source_id_title_section_signature_normalized")
        or source_component_map.get("source_id_title_section_signature")
    )
    citation_title_section_signature = _clean_non_empty_string(
        citation_component_map.get("citation_title_section_signature_normalized")
        or citation_component_map.get("citation_title_section_signature")
    )
    if source_title_section_signature or citation_title_section_signature:
        components.append(
            (
                "citation_source_id_title_section_signature_pair",
                f"{source_title_section_signature or 'none'}|"
                f"{citation_title_section_signature or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_title_section_signature_match",
                "true"
                if source_title_section_signature.lower()
                == citation_title_section_signature.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_title_section_signature_presence_match",
                "true"
                if bool(source_title_section_signature)
                == bool(citation_title_section_signature)
                else "false",
            )
        )
    source_title_section_profile = _clean_non_empty_string(
        source_component_map.get("source_id_title_section_profile_normalized")
        or source_component_map.get("source_id_title_section_profile")
    )
    citation_title_section_profile = _clean_non_empty_string(
        citation_component_map.get("citation_title_section_profile_normalized")
        or citation_component_map.get("citation_title_section_profile")
    )
    if source_title_section_profile or citation_title_section_profile:
        components.append(
            (
                "citation_source_id_title_section_profile_pair",
                f"{source_title_section_profile or 'none'}|"
                f"{citation_title_section_profile or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_title_section_profile_match",
                "true"
                if source_title_section_profile.lower()
                == citation_title_section_profile.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_title_section_profile_presence_match",
                "true"
                if bool(source_title_section_profile)
                == bool(citation_title_section_profile)
                else "false",
            )
        )
    source_title_number = _clean_non_empty_string(
        source_component_map.get("source_id_title_number")
    )
    citation_title_number = _clean_non_empty_string(
        citation_component_map.get("citation_title_number")
    )
    title_number_relation = _primary_terminal_number_relation(
        primary_number=source_title_number,
        terminal_number=citation_title_number,
    )
    if title_number_relation is not None:
        relation, span = title_number_relation
        span_component = "citation_source_id_title_number_span"
        profile_component = "citation_source_id_title_number_distance_profile"
        components.append(("citation_source_id_title_number_relation", relation))
        components.append((span_component, span))
        components.extend(
            _numeric_span_signature_components(
                slot_prefix=span_component,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            components.append((profile_component, relation_profile))
            components.extend(
                _typed_identifier_components(
                    relation_profile,
                    slot_prefix=profile_component,
                )
            )
    components.extend(
        _numeric_signature_alignment_components(
            source_number=source_title_number,
            citation_number=citation_title_number,
            slot_prefix="citation_source_id_title_number_signature",
        )
    )
    source_section_primary_number = _clean_non_empty_string(
        source_component_map.get("source_id_section_primary_number")
        or source_component_map.get("source_id_section_number")
    )
    citation_section_primary_number = _clean_non_empty_string(
        citation_component_map.get("citation_section_primary_number")
        or citation_component_map.get("citation_section_number")
    )
    section_number_relation = _primary_terminal_number_relation(
        primary_number=source_section_primary_number,
        terminal_number=citation_section_primary_number,
    )
    if section_number_relation is not None:
        relation, span = section_number_relation
        span_component = "citation_source_id_section_primary_number_span"
        profile_component = "citation_source_id_section_primary_number_distance_profile"
        components.append(("citation_source_id_section_primary_number_relation", relation))
        components.append((span_component, span))
        components.extend(
            _numeric_span_signature_components(
                slot_prefix=span_component,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            components.append((profile_component, relation_profile))
            components.extend(
                _typed_identifier_components(
                    relation_profile,
                    slot_prefix=profile_component,
                )
            )
    components.extend(
        _numeric_signature_alignment_components(
            source_number=source_section_primary_number,
            citation_number=citation_section_primary_number,
            slot_prefix="citation_source_id_section_primary_number_signature",
        )
    )
    source_section_terminal_number = _clean_non_empty_string(
        source_component_map.get("source_id_section_terminal_number")
        or source_component_map.get("source_id_section_number")
    )
    citation_section_terminal_number = _clean_non_empty_string(
        citation_component_map.get("citation_section_terminal_number")
        or citation_component_map.get("citation_section_number")
    )
    section_terminal_number_relation = _primary_terminal_number_relation(
        primary_number=source_section_terminal_number,
        terminal_number=citation_section_terminal_number,
    )
    if section_terminal_number_relation is not None:
        relation, span = section_terminal_number_relation
        span_component = "citation_source_id_section_terminal_number_span"
        profile_component = "citation_source_id_section_terminal_number_distance_profile"
        components.append(("citation_source_id_section_terminal_number_relation", relation))
        components.append((span_component, span))
        components.extend(
            _numeric_span_signature_components(
                slot_prefix=span_component,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            components.append((profile_component, relation_profile))
            components.extend(
                _typed_identifier_components(
                    relation_profile,
                    slot_prefix=profile_component,
                )
            )
    components.extend(
        _numeric_signature_alignment_components(
            source_number=source_section_terminal_number,
            citation_number=citation_section_terminal_number,
            slot_prefix="citation_source_id_section_terminal_number_signature",
        )
    )
    source_section_primary_suffix = _clean_non_empty_string(
        source_component_map.get("source_id_section_primary_suffix_normalized")
        or source_component_map.get("source_id_section_primary_suffix")
    )
    citation_section_primary_suffix = _clean_non_empty_string(
        citation_component_map.get("citation_section_primary_suffix_normalized")
        or citation_component_map.get("citation_section_primary_suffix")
    )
    if (
        source_section_primary_suffix
        or citation_section_primary_suffix
        or (
            source_section_primary_number
            and citation_section_primary_number
        )
    ):
        components.append(
            (
                "citation_source_id_section_primary_suffix_pair",
                f"{source_section_primary_suffix or 'none'}|"
                f"{citation_section_primary_suffix or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_primary_suffix_match",
                "true"
                if source_section_primary_suffix.lower()
                == citation_section_primary_suffix.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_primary_suffix_presence_match",
                "true"
                if bool(source_section_primary_suffix)
                == bool(citation_section_primary_suffix)
                else "false",
            )
        )
    source_section_primary_suffix_kind = _clean_non_empty_string(
        source_component_map.get("source_id_section_primary_suffix_kind_coarse")
        or source_component_map.get("source_id_section_primary_suffix_kind")
    )
    citation_section_primary_suffix_kind = _clean_non_empty_string(
        citation_component_map.get("citation_section_primary_suffix_kind_coarse")
        or citation_component_map.get("citation_section_primary_suffix_kind")
    )
    if (
        source_section_primary_suffix_kind
        or citation_section_primary_suffix_kind
        or (
            source_section_primary_number
            and citation_section_primary_number
        )
    ):
        components.append(
            (
                "citation_source_id_section_primary_suffix_kind_pair",
                f"{source_section_primary_suffix_kind or 'none'}|"
                f"{citation_section_primary_suffix_kind or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_primary_suffix_kind_match",
                "true"
                if source_section_primary_suffix_kind.lower()
                == citation_section_primary_suffix_kind.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_primary_suffix_kind_presence_match",
                "true"
                if bool(source_section_primary_suffix_kind)
                == bool(citation_section_primary_suffix_kind)
                else "false",
            )
        )
    source_section_terminal_suffix = _clean_non_empty_string(
        source_component_map.get("source_id_section_terminal_suffix_normalized")
        or source_component_map.get("source_id_section_terminal_suffix")
    )
    citation_section_terminal_suffix = _clean_non_empty_string(
        citation_component_map.get("citation_section_terminal_suffix_normalized")
        or citation_component_map.get("citation_section_terminal_suffix")
    )
    if (
        source_section_terminal_suffix
        or citation_section_terminal_suffix
        or (
            source_section_terminal_number
            and citation_section_terminal_number
        )
    ):
        components.append(
            (
                "citation_source_id_section_terminal_suffix_pair",
                f"{source_section_terminal_suffix or 'none'}|"
                f"{citation_section_terminal_suffix or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_terminal_suffix_match",
                "true"
                if source_section_terminal_suffix.lower()
                == citation_section_terminal_suffix.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_terminal_suffix_presence_match",
                "true"
                if bool(source_section_terminal_suffix)
                == bool(citation_section_terminal_suffix)
                else "false",
            )
        )
    source_section_terminal_suffix_kind = _clean_non_empty_string(
        source_component_map.get("source_id_section_terminal_suffix_kind_coarse")
        or source_component_map.get("source_id_section_terminal_suffix_kind")
    )
    citation_section_terminal_suffix_kind = _clean_non_empty_string(
        citation_component_map.get("citation_section_terminal_suffix_kind_coarse")
        or citation_component_map.get("citation_section_terminal_suffix_kind")
    )
    if (
        source_section_terminal_suffix_kind
        or citation_section_terminal_suffix_kind
        or (
            source_section_terminal_number
            and citation_section_terminal_number
        )
    ):
        components.append(
            (
                "citation_source_id_section_terminal_suffix_kind_pair",
                f"{source_section_terminal_suffix_kind or 'none'}|"
                f"{citation_section_terminal_suffix_kind or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_terminal_suffix_kind_match",
                "true"
                if source_section_terminal_suffix_kind.lower()
                == citation_section_terminal_suffix_kind.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_terminal_suffix_kind_presence_match",
                "true"
                if bool(source_section_terminal_suffix_kind)
                == bool(citation_section_terminal_suffix_kind)
                else "false",
            )
        )
    source_primary_component_signature = _clean_non_empty_string(
        source_component_map.get("source_id_section_primary_component_signature")
    )
    citation_primary_component_signature = _clean_non_empty_string(
        citation_component_map.get("citation_section_primary_component_signature")
    )
    if source_primary_component_signature and citation_primary_component_signature:
        components.append(
            (
                "citation_source_id_section_primary_component_signature_match",
                "true"
                if source_primary_component_signature
                == citation_primary_component_signature
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_primary_component_signature_pair",
                f"{source_primary_component_signature}|"
                f"{citation_primary_component_signature}",
            )
        )
    source_terminal_component_signature = _clean_non_empty_string(
        source_component_map.get("source_id_section_terminal_component_signature")
    )
    citation_terminal_component_signature = _clean_non_empty_string(
        citation_component_map.get("citation_section_terminal_component_signature")
    )
    if source_terminal_component_signature and citation_terminal_component_signature:
        components.append(
            (
                "citation_source_id_section_terminal_component_signature_match",
                "true"
                if source_terminal_component_signature
                == citation_terminal_component_signature
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_terminal_component_signature_pair",
                f"{source_terminal_component_signature}|"
                f"{citation_terminal_component_signature}",
            )
        )
    source_section_profile = _clean_non_empty_string(
        source_component_map.get("source_id_section_component_profile")
    )
    citation_section_profile = _clean_non_empty_string(
        citation_component_map.get("citation_section_component_profile")
    )
    if source_section_profile or citation_section_profile:
        components.append(
            (
                "citation_source_id_section_component_profile_pair",
                f"{source_section_profile or 'none'}|"
                f"{citation_section_profile or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_component_profile_match",
                "true"
                if source_section_profile.lower() == citation_section_profile.lower()
                else "false",
            )
        )
    source_section_is_range = _clean_non_empty_string(
        source_component_map.get("source_id_section_is_range")
    ).lower()
    citation_section_is_range = _clean_non_empty_string(
        citation_component_map.get("citation_section_is_range")
    ).lower()
    if (
        source_section_is_range in {"true", "false"}
        or citation_section_is_range in {"true", "false"}
    ):
        components.append(
            (
                "citation_source_id_section_is_range_pair",
                f"{source_section_is_range or 'none'}|"
                f"{citation_section_is_range or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_is_range_match",
                "true"
                if source_section_is_range == citation_section_is_range
                else "false",
            )
        )
    source_range_start = _clean_non_empty_string(
        source_component_map.get("source_id_section_range_start")
    )
    citation_range_start = _clean_non_empty_string(
        citation_component_map.get("citation_section_range_start")
    )
    source_range_end = _clean_non_empty_string(
        source_component_map.get("source_id_section_range_end")
    )
    citation_range_end = _clean_non_empty_string(
        citation_component_map.get("citation_section_range_end")
    )
    source_range_connector = _clean_non_empty_string(
        source_component_map.get("source_id_section_range_connector")
    )
    citation_range_connector = _clean_non_empty_string(
        citation_component_map.get("citation_section_range_connector")
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
        components.append(
            (
                "citation_source_id_section_range_start_pair",
                f"{source_range_start or 'none'}|{citation_range_start or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_range_start_match",
                "true"
                if source_range_start.lower() == citation_range_start.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_range_start_presence_match",
                "true"
                if bool(source_range_start) == bool(citation_range_start)
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_range_end_pair",
                f"{source_range_end or 'none'}|{citation_range_end or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_range_end_match",
                "true"
                if source_range_end.lower() == citation_range_end.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_range_end_presence_match",
                "true"
                if bool(source_range_end) == bool(citation_range_end)
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_range_connector_pair",
                f"{source_range_connector or 'none'}|"
                f"{citation_range_connector or 'none'}",
            )
        )
        components.append(
            (
                "citation_source_id_section_range_connector_match",
                "true"
                if source_range_connector.lower() == citation_range_connector.lower()
                else "false",
            )
        )
        components.append(
            (
                "citation_source_id_section_range_connector_presence_match",
                "true"
                if bool(source_range_connector) == bool(citation_range_connector)
                else "false",
            )
        )
    if not source_title or not citation_title or not source_section or not citation_section:
        alignment = "unparsed"
        components.append(("citation_source_id_alignment", alignment))
        components.extend(
            _citation_source_id_alignment_profile_components(
                alignment=alignment,
                source_section_raw=source_section_raw,
                citation_section_raw=citation_section_raw,
                source_has_trailing_punct=source_has_trailing_punct,
                citation_has_trailing_punct=citation_has_trailing_punct,
                source_section_trailing_punct=source_section_trailing_punct,
                citation_section_trailing_punct=citation_section_trailing_punct,
            )
        )
        return _unique_preserve_order_tuples(components)

    title_match = source_title.lower() == citation_title.lower()
    section_match = source_section.lower() == citation_section.lower()
    components.append(
        ("citation_source_id_title_match", "true" if title_match else "false")
    )
    components.append(
        ("citation_source_id_section_match", "true" if section_match else "false")
    )
    if source_key and citation_key:
        components.append(
            (
                "citation_source_id_title_section_key_match",
                "true" if source_key.lower() == citation_key.lower() else "false",
            )
        )
    if source_canonical and citation_canonical:
        components.append(
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
    components.append(("citation_source_id_alignment", alignment))
    components.extend(
        _citation_source_id_alignment_profile_components(
            alignment=alignment,
            source_section_raw=source_section_raw,
            citation_section_raw=citation_section_raw,
            source_has_trailing_punct=source_has_trailing_punct,
            citation_has_trailing_punct=citation_has_trailing_punct,
            source_section_trailing_punct=source_section_trailing_punct,
            citation_section_trailing_punct=citation_section_trailing_punct,
        )
    )
    return _unique_preserve_order_tuples(components)


def _citation_source_id_alignment_profile_components(
    *,
    alignment: str,
    source_section_raw: str,
    citation_section_raw: str,
    source_has_trailing_punct: str,
    citation_has_trailing_punct: str,
    source_section_trailing_punct: str,
    citation_section_trailing_punct: str,
) -> List[tuple[str, str]]:
    normalized_alignment = _clean_non_empty_string(alignment).lower() or "unparsed"
    normalized_source_raw = _clean_non_empty_string(source_section_raw)
    normalized_citation_raw = _clean_non_empty_string(citation_section_raw)
    normalized_source_punct = _clean_non_empty_string(source_section_trailing_punct)
    normalized_citation_punct = _clean_non_empty_string(citation_section_trailing_punct)
    normalized_source_has_punct = _clean_non_empty_string(source_has_trailing_punct).lower()
    normalized_citation_has_punct = _clean_non_empty_string(
        citation_has_trailing_punct
    ).lower()

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
    components: List[tuple[str, str]] = [
        ("citation_source_id_alignment_raw_relation", raw_relation),
        (
            "citation_source_id_alignment_punctuation_relation",
            punctuation_relation,
        ),
        ("citation_source_id_alignment_profile", profile),
    ]
    components.extend(
        _typed_identifier_components(
            profile,
            slot_prefix="citation_source_id_alignment_profile",
        )
    )
    return _unique_preserve_order_tuples(components)


def _component_value_map(components: Sequence[tuple[str, str]]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for component, value in components:
        normalized_component = _clean_non_empty_string(component)
        normalized_value = _clean_non_empty_string(value)
        if (
            not normalized_component
            or not normalized_value
            or normalized_component in values
        ):
            continue
        values[normalized_component] = normalized_value
    return values


def _document_span_components(modal_ir: ModalIRDocument) -> List[tuple[str, str]]:
    source_text = str(modal_ir.normalized_text or "")
    source_length = len(source_text) if _clean_non_empty_string(source_text) else 0
    modal_spans = _merged_formula_spans(modal_ir.formulas, source_length)
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
    support_start, support_end = _support_span(modal_ir.formulas)
    support_width = max(0, support_end - support_start)
    modal_span_coverage = (
        (modal_span_char_count / source_length)
        if source_length > 0
        else 0.0
    )
    coverage_percent = str(int(round(max(0.0, min(1.0, modal_span_coverage)) * 100.0)))

    components: List[tuple[str, str]] = []
    metric_components: List[tuple[str, str]] = [
        ("modal_formula_count", str(len(modal_ir.formulas))),
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
    for predicate, value in metric_components:
        components.append((predicate, value))
        components.extend(
            _numeric_signature_components(
                value,
                slot_prefix=predicate,
            )
        )

    coverage_bucket = _modal_span_coverage_bucket(
        modal_span_coverage=modal_span_coverage,
        source_length=source_length,
        modal_span_count=modal_span_count,
    )
    components.append(("modal_span_coverage_bucket", coverage_bucket))
    components.extend(
        _typed_identifier_components(
            coverage_bucket,
            slot_prefix="modal_span_coverage_bucket",
        )
    )
    return _unique_preserve_order_tuples(components)


def _collapse_whitespace_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _merged_formula_spans(
    formulas: Sequence[ModalIRFormula],
    source_length: int,
) -> List[tuple[int, int]]:
    spans: List[tuple[int, int]] = []
    for formula in formulas:
        start = max(0, min(source_length, int(formula.provenance.start_char)))
        end = max(start, min(source_length, int(formula.provenance.end_char)))
        if end > start:
            spans.append((start, end))
    if not spans:
        return []
    spans.sort()
    merged: List[tuple[int, int]] = []
    current_start, current_end = spans[0]
    for start, end in spans[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        merged.append((current_start, current_end))
        current_start, current_end = start, end
    merged.append((current_start, current_end))
    return merged


def _source_context_span_count(
    *,
    modal_spans: Sequence[tuple[int, int]],
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


def _support_span(formulas: Sequence[ModalIRFormula]) -> tuple[int, int]:
    if not formulas:
        return (0, 0)
    starts = [int(formula.provenance.start_char) for formula in formulas]
    ends = [int(formula.provenance.end_char) for formula in formulas]
    return (min(starts), max(ends))


def _document_modal_family_count_components(
    modal_ir: ModalIRDocument,
) -> List[tuple[str, str]]:
    components: List[tuple[str, str]] = []
    for rank, (family, count) in enumerate(
        _resolved_modal_family_counts(modal_ir),
        start=1,
    ):
        safe_family = _slot_safe_family_key(family)
        if not safe_family:
            continue
        components.extend(
            [
                ("modal_family_count", f"{family}:{count}"),
                ("modal_family_count_ranked", f"{rank}:{family}:{count}"),
                ("modal_family_count_family", family),
                ("modal_family_count_value", count),
                (f"modal_family_count_{safe_family}", count),
            ]
        )
        components.extend(
            _numeric_signature_components(
                count,
                slot_prefix="modal_family_count_value",
            )
        )
        components.extend(
            _numeric_signature_components(
                count,
                slot_prefix=f"modal_family_count_{safe_family}",
            )
        )
    return _unique_preserve_order_tuples(components)


def _selected_frame_modal_family_count_components(
    modal_ir: ModalIRDocument,
) -> List[tuple[str, str]]:
    components: List[tuple[str, str]] = []
    for rank, (family, count) in enumerate(
        _resolved_modal_family_counts(modal_ir),
        start=1,
    ):
        safe_family = _slot_safe_family_key(family)
        if not safe_family:
            continue
        components.extend(
            [
                ("selected_frame_modal_family", safe_family),
                ("selected_frame_modal_family_ranked", f"{rank}:{safe_family}"),
                ("selected_frame_modal_family_count", f"{safe_family}:{count}"),
                (
                    "selected_frame_modal_family_count_ranked",
                    f"{rank}:{safe_family}:{count}",
                ),
                ("selected_frame_modal_family_count_value", count),
                (f"selected_frame_modal_family_{safe_family}", count),
            ]
        )
        components.extend(
            _numeric_signature_components(
                count,
                slot_prefix="selected_frame_modal_family_count_value",
            )
        )
        components.extend(
            _numeric_signature_components(
                count,
                slot_prefix=f"selected_frame_modal_family_{safe_family}",
            )
        )
    return _unique_preserve_order_tuples(components)


def _frame_grounding_profile_components(
    modal_ir: ModalIRDocument,
    *,
    selected_frame: str,
    selected_frame_terms: Sequence[str],
    ranked_frame_ids: Sequence[str],
) -> List[tuple[str, str]]:
    frame_key = _clean_non_empty_string(selected_frame)
    if not frame_key:
        return []
    ranked_keys = [_clean_non_empty_string(frame_id) for frame_id in ranked_frame_ids]
    ranked_keys = [frame_id for frame_id in ranked_keys if frame_id]
    selected_rank = "unranked"
    if frame_key in ranked_keys:
        selected_rank = str(ranked_keys.index(frame_key) + 1)
    candidate_count = str(len(ranked_keys))
    normalized_terms = _unique_preserve_order(
        _clean_non_empty_string(term)
        for term in selected_frame_terms
        if _clean_non_empty_string(term)
    )
    term_count = str(len(normalized_terms))
    profile = (
        f"{frame_key}|rank:{selected_rank}|terms:{term_count}|"
        f"candidates:{candidate_count}"
    )
    components: List[tuple[str, str]] = [
        ("frame_grounding_profile", profile),
        ("frame_grounding_selected_frame", frame_key),
        ("frame_grounding_selected_rank", selected_rank),
        ("frame_grounding_selected_term_count", term_count),
        ("frame_grounding_candidate_count", candidate_count),
    ]
    if selected_rank.isdigit():
        components.extend(
            _numeric_signature_components(
                selected_rank,
                slot_prefix="frame_grounding_selected_rank",
            )
        )
    components.extend(
        _numeric_signature_components(
            term_count,
            slot_prefix="frame_grounding_selected_term_count",
        )
    )
    components.extend(
        _numeric_signature_components(
            candidate_count,
            slot_prefix="frame_grounding_candidate_count",
        )
    )
    components.extend(
        _typed_identifier_components(
            profile,
            slot_prefix="frame_grounding_profile",
        )
    )
    for rank, term in enumerate(normalized_terms, start=1):
        components.append(("frame_grounding_selected_term_ranked", f"{rank}:{term}"))
    for family, count in _resolved_modal_family_counts(modal_ir):
        family_key = _slot_safe_family_key(family)
        if not family_key:
            continue
        family_profile = (
            f"{frame_key}|family:{family_key}|count:{count}|"
            f"rank:{selected_rank}|terms:{term_count}"
        )
        components.extend(
            [
                ("frame_grounding_modal_family", family_key),
                ("frame_grounding_modal_family_count", f"{family_key}:{count}"),
                ("frame_grounding_family_profile", family_profile),
                (f"frame_grounding_family_profile_{family_key}", family_profile),
            ]
        )
    return _unique_preserve_order_tuples(components)


def _resolved_modal_family_counts(
    modal_ir: ModalIRDocument,
) -> List[tuple[str, str]]:
    metadata_counts = _normalized_modal_family_counts(
        modal_ir.metadata.get("modal_family_counts")
    )
    if metadata_counts:
        return metadata_counts
    formula_counts: Dict[str, int] = {}
    for formula in modal_ir.formulas:
        family = _slot_safe_family_key(
            _clean_non_empty_string(formula.operator.family).lower()
        )
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


def _document_source_context_components(
    modal_ir: ModalIRDocument,
) -> List[tuple[str, str]]:
    components: List[tuple[str, str]] = []
    source_ids = _document_source_ids(modal_ir)
    for source_id in source_ids:
        components.extend(_source_id_components(source_id))
    citation = _clean_non_empty_string(modal_ir.metadata.get("citation"))
    if citation:
        components.append(("citation", citation))
        components.extend(_citation_components(citation))
        for source_id in source_ids:
            components.extend(
                _provenance_alignment_components(
                    source_id=source_id,
                    citation=citation,
                )
            )
    elif not modal_ir.formulas:
        for inferred_citation in _inferred_citations_from_source_ids(source_ids):
            components.append(("citation", inferred_citation))
            components.append(("citation_derivation", "source_id_inferred"))
            components.extend(_citation_components(inferred_citation))
            for source_id in source_ids:
                components.extend(
                    _provenance_alignment_components(
                        source_id=source_id,
                        citation=inferred_citation,
                    )
                )
    return _unique_preserve_order_tuples(components)


def _document_source_ids(modal_ir: ModalIRDocument) -> List[str]:
    source_ids: List[str] = []
    document_id = _clean_non_empty_string(modal_ir.document_id)
    if document_id:
        source_ids.append(document_id)
    for formula in modal_ir.formulas:
        source_id = _clean_non_empty_string(formula.provenance.source_id)
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


def _selected_frame_source_grounding_terms(modal_ir: ModalIRDocument) -> List[str]:
    """Return U.S.C. source/status terms that ground the selected frame."""

    values: List[Any] = [
        modal_ir.metadata.get("citation"),
        modal_ir.metadata.get("source_id"),
        modal_ir.metadata.get("sample_id"),
        modal_ir.document_id,
    ]
    for source_id in _document_source_ids(modal_ir):
        values.append(source_id)
        source_map = _component_value_map(_source_id_components(source_id))
        values.extend(
            source_map.get(key)
            for key in (
                "source_id_citation_canonical",
                "source_id_title",
                "source_id_section_normalized",
                "source_id_title_section_key",
            )
        )
    for formula in modal_ir.formulas:
        values.extend(
            (
                getattr(formula.provenance, "citation", None),
                getattr(formula.provenance, "source_id", None),
                _status_keyword_value(
                    formula,
                    fallback_rule=_clean_non_empty_string(
                        formula.metadata.get("fallback_rule")
                    ),
                ),
                _clean_non_empty_string(formula.metadata.get("procedural_keyword")),
                _clean_non_empty_string(formula.metadata.get("statement_hint")),
                _fallback_section_heading_tail_text(
                    modal_ir=modal_ir,
                    formula=formula,
                ),
            )
        )

    terms: List[str] = []
    for value in values:
        for term in _frame_ontology_metadata_terms(value):
            cleaned = _clean_non_empty_string(term)
            if cleaned:
                terms.append(cleaned)
    return _unique_preserve_order(terms)


def _inferred_citations_from_source_ids(source_ids: Sequence[str]) -> List[str]:
    citations: List[str] = []
    for source_id in source_ids:
        citation = _source_id_inferred_citation(source_id)
        if citation and citation not in citations:
            citations.append(citation)
    return citations


def _source_id_inferred_citation(source_id: str) -> str:
    normalized_source_id = _clean_non_empty_string(source_id)
    if not normalized_source_id:
        return ""
    source_component_map = _component_value_map(_source_id_components(normalized_source_id))
    title = _clean_non_empty_string(source_component_map.get("source_id_title"))
    raw_section = _clean_non_empty_string(
        source_component_map.get("source_id_section_raw")
        or source_component_map.get("source_id_section")
    )
    if title and raw_section:
        return f"{title} U.S.C. {raw_section}"
    canonical = _clean_non_empty_string(
        source_component_map.get("source_id_citation_canonical")
    )
    if canonical:
        return canonical
    normalized_section = _clean_non_empty_string(
        source_component_map.get("source_id_section_normalized")
        or source_component_map.get("source_id_section")
    )
    return _canonical_usc_citation(title, normalized_section)


def _normalized_modal_family_counts(raw_counts: Any) -> List[tuple[str, str]]:
    if not isinstance(raw_counts, Mapping):
        return []
    normalized: Dict[str, str] = {}
    for raw_family, raw_count in raw_counts.items():
        family = _slot_safe_family_key(_clean_non_empty_string(raw_family).lower())
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
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").lower()).strip("_")


def _citation_section_components(section: str) -> List[tuple[str, str]]:
    cleaned = _clean_non_empty_string(section)
    if not cleaned:
        return []
    range_match = _CITATION_SECTION_RANGE_RE.fullmatch(cleaned)
    range_start = ""
    range_end = ""
    range_connector = ""
    if range_match:
        range_start = _clean_non_empty_string(range_match.group("start"))
        range_end = _clean_non_empty_string(range_match.group("end"))
        range_connector = _clean_non_empty_string(range_match.group("connector")).lower()
    is_range = bool(range_start and range_end and range_connector)
    if is_range:
        parts = [range_start, range_end]
    else:
        parts = [
            _clean_non_empty_string(part)
            for part in _CITATION_SECTION_COMPONENT_SPLIT_RE.split(cleaned)
            if _clean_non_empty_string(part)
        ]
    if not parts:
        return []
    primary_part = parts[0]
    terminal_part = parts[-1]
    components: List[tuple[str, str]] = [
        ("citation_section_primary", primary_part),
        ("citation_section_terminal", terminal_part),
        (
            "citation_section_primary_equals_terminal",
            "true" if primary_part == terminal_part else "false",
        ),
        (
            "citation_section_primary_terminal_pair",
            f"{primary_part}|{terminal_part}",
        ),
        ("citation_section_component_count", str(len(parts))),
        ("citation_section_is_range", "true" if is_range else "false"),
    ]
    delimiter_tokens = _citation_section_delimiter_tokens(cleaned)
    delimiter_pattern = ""
    if delimiter_tokens:
        components.append(("citation_section_has_delimiter", "true"))
        components.append(("citation_section_delimiter_count", str(len(delimiter_tokens))))
        delimiter_kinds: List[str] = []
        for index, delimiter_token in enumerate(delimiter_tokens, start=1):
            position = str(index)
            kind = _citation_section_delimiter_kind(delimiter_token)
            if kind:
                delimiter_kinds.append(kind)
                components.append(("citation_section_delimiter", kind))
                components.append(
                    ("citation_section_delimiter_positioned", f"{position}:{kind}")
                )
            components.append(("citation_section_delimiter_token", delimiter_token))
            components.append(
                (
                    "citation_section_delimiter_token_positioned",
                    f"{position}:{delimiter_token}",
                )
            )
            char_count = str(len(delimiter_token))
            components.append(("citation_section_delimiter_char_count", char_count))
            components.append(
                (
                    "citation_section_delimiter_char_count_positioned",
                    f"{position}:{char_count}",
                )
            )
        if delimiter_kinds:
            delimiter_pattern = "-".join(delimiter_kinds)
            components.append(
                ("citation_section_delimiter_pattern", delimiter_pattern)
            )
            components.append(
                (
                    "citation_section_delimiter_distinct_count",
                    str(len(set(delimiter_kinds))),
                )
            )
    else:
        components.append(("citation_section_has_delimiter", "false"))
        components.append(("citation_section_delimiter_count", "0"))
    if is_range:
        components.extend(
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
    total_parts = len(parts)
    for index, part in enumerate(parts, start=1):
        position = str(index)
        components.append(("citation_section_component", part))
        components.append(("citation_section_component_positioned", f"{position}:{part}"))
        match = _CITATION_SECTION_PART_RE.fullmatch(part)
        if not match:
            component_shapes.append("X")
            component_signature = "X"
            component_signatures.append(component_signature)
            components.append(("citation_section_component_signature", component_signature))
            components.append(
                (
                    "citation_section_component_signature_positioned",
                    f"{position}:{component_signature}",
                )
            )
            if index == 1:
                components.append(
                    ("citation_section_primary_component_signature", component_signature)
                )
            if index == total_parts:
                components.append(
                    ("citation_section_terminal_component_signature", component_signature)
                )
            components.append(("citation_section_component_kind", "other"))
            components.append(
                ("citation_section_component_kind_positioned", f"{position}:other")
            )
            if index == 1:
                components.append(("citation_section_primary_component_kind", "other"))
                primary_component_kind = "other"
            if index == total_parts:
                components.append(("citation_section_terminal_component_kind", "other"))
                terminal_component_kind = "other"
            continue
        number = _clean_non_empty_string(match.group("number"))
        suffix = _clean_non_empty_string(match.group("suffix"))
        numeric_component_count += 1
        parsed_component_count += 1
        if index == 1:
            primary_has_suffix = bool(suffix)
            primary_suffix_is_roman = False
        if index == total_parts:
            terminal_has_suffix = bool(suffix)
            terminal_suffix_is_roman = False
        if number:
            components.append(("citation_section_number", number))
            number_digit_count = str(len(number))
            components.append(("citation_section_number_digit_count", number_digit_count))
            components.append(
                (
                    "citation_section_number_digit_count_positioned",
                    f"{position}:{number_digit_count}",
                )
            )
            components.append(("citation_section_number_positioned", f"{position}:{number}"))
            number_suffix_pair = f"{number}|{suffix or 'none'}"
            components.append(("citation_section_number_suffix_pair", number_suffix_pair))
            components.append(
                (
                    "citation_section_number_suffix_pair_positioned",
                    f"{position}:{number_suffix_pair}",
                )
            )
            for signature_slot, signature_value in _numeric_signature_components(
                number,
                slot_prefix="citation_section_number",
            ):
                components.append((signature_slot, signature_value))
                components.append(
                    (
                        f"{signature_slot}_positioned",
                        f"{position}:{signature_value}",
                    )
                )
            if index == 1:
                components.append(("citation_section_primary_number", number))
                primary_number = number
                components.append(
                    (
                        "citation_section_primary_number_digit_count",
                        number_digit_count,
                    )
                )
                components.extend(
                    _numeric_signature_components(
                        number,
                        slot_prefix="citation_section_primary_number",
                    )
                )
                components.append(
                    (
                        "citation_section_primary_number_suffix_pair",
                        number_suffix_pair,
                    )
                )
            if index == total_parts:
                components.append(("citation_section_terminal_number", number))
                terminal_number = number
                components.append(
                    (
                        "citation_section_terminal_number_digit_count",
                        number_digit_count,
                    )
                )
                components.extend(
                    _numeric_signature_components(
                        number,
                        slot_prefix="citation_section_terminal_number",
                    )
                )
                components.append(
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
        components.append(("citation_section_component_signature", component_signature))
        components.append(
            (
                "citation_section_component_signature_positioned",
                f"{position}:{component_signature}",
            )
        )
        if index == 1:
            components.append(
                ("citation_section_primary_component_signature", component_signature)
            )
        if index == total_parts:
            components.append(
                ("citation_section_terminal_component_signature", component_signature)
            )
        if suffix:
            component_shapes.append("NA")
            suffix_component_count += 1
            components.append(("citation_section_component_kind", "alphanumeric"))
            components.append(
                (
                    "citation_section_component_kind_positioned",
                    f"{position}:alphanumeric",
                )
            )
            components.append(("citation_section_suffix", suffix))
            components.append(("citation_section_suffix_positioned", f"{position}:{suffix}"))
            suffix_char_count = str(len(suffix))
            components.append(("citation_section_suffix_char_count", suffix_char_count))
            components.append(
                (
                    "citation_section_suffix_char_count_positioned",
                    f"{position}:{suffix_char_count}",
                )
            )
            suffix_profile = _suffix_profile(suffix)
            if suffix_profile:
                components.append(("citation_section_suffix_profile", suffix_profile))
                components.append(
                    (
                        "citation_section_suffix_profile_positioned",
                        f"{position}:{suffix_profile}",
                    )
                )
            normalized_suffix = suffix.lower()
            if normalized_suffix:
                components.append(("citation_section_suffix_normalized", normalized_suffix))
                if index == 1:
                    components.append(("citation_section_primary_suffix_normalized", normalized_suffix))
                if index == total_parts:
                    components.append(("citation_section_terminal_suffix_normalized", normalized_suffix))
            suffix_case = _alpha_case_kind(suffix)
            if suffix_case:
                components.append(("citation_section_suffix_case", suffix_case))
                components.append(
                    (
                        "citation_section_suffix_case_positioned",
                        f"{position}:{suffix_case}",
                    )
                )
                if index == 1:
                    components.append(("citation_section_primary_suffix_case", suffix_case))
                if index == total_parts:
                    components.append(("citation_section_terminal_suffix_case", suffix_case))
            for alpha_slot, alpha_value in _alpha_signature_components(
                suffix,
                slot_prefix="citation_section_suffix",
            ):
                components.append((alpha_slot, alpha_value))
                components.append(
                    (
                        f"{alpha_slot}_positioned",
                        f"{position}:{alpha_value}",
                    )
                )
            if suffix_kind:
                components.append(("citation_section_suffix_kind", suffix_kind))
                components.append(
                    (
                        "citation_section_suffix_kind_positioned",
                        f"{position}:{suffix_kind}",
                    )
                )
                if index == 1:
                    components.append(("citation_section_primary_suffix_kind", suffix_kind))
                    primary_suffix_kind = suffix_kind
                if index == total_parts:
                    components.append(("citation_section_terminal_suffix_kind", suffix_kind))
                    terminal_suffix_kind = suffix_kind
            if suffix_kind == "roman":
                roman_suffix_component_count += 1
                if index == 1:
                    primary_suffix_is_roman = True
                if index == total_parts:
                    terminal_suffix_is_roman = True
            if index == 1:
                primary_suffix = suffix
                components.append(("citation_section_primary_suffix", suffix))
                components.append(("citation_section_primary_suffix_char_count", suffix_char_count))
                if suffix_profile:
                    components.append(("citation_section_primary_suffix_profile", suffix_profile))
                components.extend(
                    _alpha_signature_components(
                        suffix,
                        slot_prefix="citation_section_primary_suffix",
                    )
                )
                components.append(("citation_section_primary_component_kind", "alphanumeric"))
                primary_component_kind = "alphanumeric"
            if index == total_parts:
                terminal_suffix = suffix
                components.append(("citation_section_terminal_suffix", suffix))
                components.append(("citation_section_terminal_suffix_char_count", suffix_char_count))
                if suffix_profile:
                    components.append(("citation_section_terminal_suffix_profile", suffix_profile))
                components.extend(
                    _alpha_signature_components(
                        suffix,
                        slot_prefix="citation_section_terminal_suffix",
                    )
                )
                components.append(("citation_section_terminal_component_kind", "alphanumeric"))
                terminal_component_kind = "alphanumeric"
        else:
            component_shapes.append("N")
            components.append(("citation_section_component_kind", "numeric"))
            components.append(
                ("citation_section_component_kind_positioned", f"{position}:numeric")
            )
            if index == 1:
                components.append(("citation_section_primary_component_kind", "numeric"))
                primary_component_kind = "numeric"
            if index == total_parts:
                components.append(("citation_section_terminal_component_kind", "numeric"))
                terminal_component_kind = "numeric"
    if parsed_component_count:
        components.append(
            (
                "citation_section_has_suffix",
                "true" if suffix_component_count > 0 else "false",
            )
        )
        components.append(
            (
                "citation_section_has_roman_suffix",
                "true" if roman_suffix_component_count > 0 else "false",
            )
        )
        primary_suffix_kind_coarse = primary_suffix_kind or "none"
        terminal_suffix_kind_coarse = terminal_suffix_kind or "none"
        components.extend(
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
        components.append(
            (
                "citation_section_primary_has_suffix",
                "true" if primary_has_suffix else "false",
            )
        )
    if primary_suffix_is_roman is not None:
        components.append(
            (
                "citation_section_primary_suffix_is_roman",
                "true" if primary_suffix_is_roman else "false",
            )
        )
    if terminal_has_suffix is not None:
        components.append(
            (
                "citation_section_terminal_has_suffix",
                "true" if terminal_has_suffix else "false",
            )
        )
    if terminal_suffix_is_roman is not None:
        components.append(
            (
                "citation_section_terminal_suffix_is_roman",
                "true" if terminal_suffix_is_roman else "false",
            )
        )
    if component_shapes:
        components.append(("citation_section_shape", "-".join(component_shapes)))
    if component_signatures:
        components.append(("citation_section_signature", "-".join(component_signatures)))
        primary_signature = component_signatures[0]
        terminal_signature = component_signatures[-1]
        components.append(
            (
                "citation_section_primary_terminal_component_signature_pair",
                f"{primary_signature}|{terminal_signature}",
            )
        )
        components.append(
            (
                "citation_section_primary_terminal_component_signature_match",
                "true" if primary_signature == terminal_signature else "false",
            )
        )
    if primary_component_kind and terminal_component_kind:
        components.append(
            (
                "citation_section_primary_terminal_component_kind_pair",
                f"{primary_component_kind}|{terminal_component_kind}",
            )
        )
        components.append(
            (
                "citation_section_primary_terminal_component_kind_match",
                "true" if primary_component_kind == terminal_component_kind else "false",
            )
        )
    component_profile = _citation_section_component_profile(
        component_count=total_parts,
        suffix_component_count=suffix_component_count,
        is_range=is_range,
    )
    if component_profile:
        components.append(("citation_section_component_profile", component_profile))
    numeric_relation = _primary_terminal_number_relation(
        primary_number=primary_number,
        terminal_number=terminal_number,
    )
    if numeric_relation is not None:
        relation, span = numeric_relation
        primary_span_component = "citation_section_primary_terminal_number_span"
        primary_profile_component = (
            "citation_section_primary_terminal_number_distance_profile"
        )
        components.append(("citation_section_primary_terminal_number_relation", relation))
        components.append((primary_span_component, span))
        components.extend(
            _numeric_span_signature_components(
                slot_prefix=primary_span_component,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            components.append((primary_profile_component, relation_profile))
            components.extend(
                _typed_identifier_components(
                    relation_profile,
                    slot_prefix=primary_profile_component,
                )
            )
        if is_range:
            components.append(("citation_section_range_number_relation", relation))
            range_span_component = "citation_section_range_number_span"
            range_profile_component = "citation_section_range_number_distance_profile"
            components.append((range_span_component, span))
            components.extend(
                _numeric_span_signature_components(
                    slot_prefix=range_span_component,
                    span=span,
                )
            )
            if relation_profile:
                components.append((range_profile_component, relation_profile))
                components.extend(
                    _typed_identifier_components(
                        relation_profile,
                        slot_prefix=range_profile_component,
                    )
                )
    components.extend(
        _primary_terminal_suffix_relation_components(
            primary_suffix=primary_suffix,
            terminal_suffix=terminal_suffix,
            slot_prefix="citation_section_primary_terminal_suffix",
            emit_when_absent=is_range,
        )
    )
    if is_range:
        components.extend(
            _primary_terminal_suffix_relation_components(
                primary_suffix=primary_suffix,
                terminal_suffix=terminal_suffix,
                slot_prefix="citation_section_range_suffix",
                emit_when_absent=True,
            )
        )
    if is_range:
        components.append(
            (
                "citation_section_range_has_suffix",
                "true" if suffix_component_count > 0 else "false",
            )
        )
    has_hyphen_subsection = (
        not is_range
        and total_parts == 2
        and delimiter_pattern == "hyphen"
        and bool(primary_number)
        and bool(primary_suffix)
        and bool(terminal_number)
        and not terminal_suffix
    )
    components.append(
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
        components.append(
            (
                "citation_section_hyphen_subsection_primary_number",
                primary_number,
            )
        )
        components.append(
            (
                "citation_section_hyphen_subsection_primary_suffix",
                normalized_primary_suffix,
            )
        )
        components.append(
            (
                "citation_section_hyphen_subsection_terminal_number",
                terminal_number,
            )
        )
        components.append(
            (
                "citation_section_hyphen_subsection_signature",
                hyphen_subsection_signature,
            )
        )
        components.extend(
            _typed_identifier_components(
                hyphen_subsection_signature,
                slot_prefix="citation_section_hyphen_subsection_signature",
            )
        )
    components.append(
        ("citation_section_numeric_component_count", str(numeric_component_count))
    )
    components.append(
        ("citation_section_suffix_component_count", str(suffix_component_count))
    )
    components.append(
        (
            "citation_section_roman_suffix_component_count",
            str(roman_suffix_component_count),
        )
    )
    return components


def _citation_section_delimiter_tokens(section: str) -> List[str]:
    return [
        delimiter
        for delimiter in (
            _clean_non_empty_string(token)
            for token in _CITATION_SECTION_DELIMITER_RE.findall(section)
        )
        if delimiter
    ]


def _citation_section_delimiter_kind(delimiter: str) -> str:
    cleaned = _clean_non_empty_string(delimiter)
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
    number_text = _clean_non_empty_string(number)
    suffix_text = _clean_non_empty_string(suffix)
    number_width = str(len(number_text)) if number_text else "0"
    if not suffix_text:
        return f"N{number_width}"
    kind_key = _clean_non_empty_string(suffix_kind).lower()
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
) -> tuple[str, str] | None:
    primary_text = _clean_non_empty_string(primary_number)
    terminal_text = _clean_non_empty_string(terminal_number)
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


def _primary_terminal_suffix_relation_components(
    *,
    primary_suffix: str,
    terminal_suffix: str,
    slot_prefix: str,
    emit_when_absent: bool = False,
) -> List[tuple[str, str]]:
    normalized_slot_prefix = _clean_non_empty_string(slot_prefix)
    if not normalized_slot_prefix:
        return []
    primary = _clean_non_empty_string(primary_suffix).lower()
    terminal = _clean_non_empty_string(terminal_suffix).lower()
    if not primary and not terminal and not emit_when_absent:
        return []
    components: List[tuple[str, str]] = [
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
            components.append((f"{normalized_slot_prefix}_length_relation", relation))
            components.append((f"{normalized_slot_prefix}_length_span", span))
        alpha_relation = _primary_terminal_alpha_relation(
            primary_token=primary,
            terminal_token=terminal,
        )
        if alpha_relation is not None:
            relation, span = alpha_relation
            components.append((f"{normalized_slot_prefix}_alpha_relation", relation))
            components.append((f"{normalized_slot_prefix}_alpha_span", span))
    return components


def _primary_terminal_alpha_relation(
    *,
    primary_token: str,
    terminal_token: str,
) -> tuple[str, str] | None:
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
    cleaned = _clean_non_empty_string(value).lower()
    if not cleaned or not cleaned.isalpha():
        return None
    numeric_value = 0
    for character in cleaned:
        numeric_value = (numeric_value * 26) + (ord(character) - ord("a") + 1)
    return numeric_value


def _numeric_signature_components(
    value: str,
    *,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    cleaned = _clean_non_empty_string(value)
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


def _numeric_span_signature_components(
    *,
    slot_prefix: str,
    span: str,
) -> List[tuple[str, str]]:
    normalized_slot_prefix = _clean_non_empty_string(slot_prefix)
    normalized_span = _clean_non_empty_string(span)
    if not normalized_slot_prefix or not normalized_span.isdigit():
        return []
    return _numeric_signature_components(
        normalized_span,
        slot_prefix=normalized_slot_prefix,
    )


def _numeric_signature_value_map(value: str) -> Dict[str, str]:
    cleaned = _clean_non_empty_string(value)
    if not cleaned.isdigit():
        return {}
    values: Dict[str, str] = {}
    for component, component_value in _numeric_signature_components(
        cleaned,
        slot_prefix="number",
    ):
        key = component.removeprefix("number_")
        if key:
            values[key] = component_value
    return values


def _numeric_signature_alignment_components(
    *,
    source_number: str,
    citation_number: str,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    normalized_slot_prefix = _clean_non_empty_string(slot_prefix)
    if not normalized_slot_prefix:
        return []
    source_signature_values = _numeric_signature_value_map(source_number)
    citation_signature_values = _numeric_signature_value_map(citation_number)
    components: List[tuple[str, str]] = []
    for signature_name in _PROVENANCE_NUMERIC_ALIGNMENT_SIGNATURES:
        source_value = _clean_non_empty_string(
            source_signature_values.get(signature_name)
        )
        citation_value = _clean_non_empty_string(
            citation_signature_values.get(signature_name)
        )
        if not source_value and not citation_value:
            continue
        components.append(
            (
                f"{normalized_slot_prefix}_{signature_name}_pair",
                f"{source_value or 'none'}|{citation_value or 'none'}",
            )
        )
        components.append(
            (
                f"{normalized_slot_prefix}_{signature_name}_match",
                "true"
                if source_value.lower() == citation_value.lower()
                else "false",
            )
        )
        components.append(
            (
                f"{normalized_slot_prefix}_{signature_name}_presence_match",
                "true" if bool(source_value) == bool(citation_value) else "false",
            )
        )
    return components


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
    normalized_relation = _clean_non_empty_string(relation).lower()
    normalized_span = _clean_non_empty_string(span)
    if not normalized_relation:
        return ""
    if not normalized_span.isdigit():
        return normalized_relation
    return f"{normalized_relation}_{_numeric_magnitude_bucket(int(normalized_span))}"


def _alpha_signature_components(
    value: str,
    *,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    cleaned = _clean_non_empty_string(value).lower()
    if not cleaned:
        return []
    letters = [character for character in cleaned if character.isalpha()]
    if not letters:
        return []
    initial = letters[0]
    terminal = letters[-1]
    vowel_count = sum(1 for character in letters if character in _VOWEL_CHARS)
    consonant_count = len(letters) - vowel_count
    components: List[tuple[str, str]] = [
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
        components.append((f"{slot_prefix}_initial_ordinal", initial_ordinal))
    terminal_ordinal = _alpha_ordinal(terminal)
    if terminal_ordinal:
        components.append((f"{slot_prefix}_terminal_ordinal", terminal_ordinal))
    return components


def _alpha_ordinal(value: str) -> str:
    cleaned = _clean_non_empty_string(value).lower()
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


def _section_trailing_punct(
    *,
    raw_section: str,
    normalized_section: str,
) -> str:
    raw = _clean_non_empty_string(raw_section)
    normalized = _clean_non_empty_string(normalized_section)
    if not raw or raw == normalized:
        return ""
    if not raw.startswith(normalized):
        return ""
    return _clean_non_empty_string(raw[len(normalized) :])


def _section_trailing_punct_kind(value: str) -> str:
    cleaned = _clean_non_empty_string(value)
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
    normalized_title = _clean_non_empty_string(title)
    normalized_section = _clean_non_empty_string(
        _TRAILING_SECTION_PUNCT_RE.sub("", section)
    )
    if not normalized_title or not normalized_section:
        return ""
    return f"{normalized_title} U.S.C. {normalized_section}"


def _title_section_coordinate(title: str, section: str) -> str:
    normalized_title = _clean_non_empty_string(title)
    normalized_section = _clean_non_empty_string(
        _TRAILING_SECTION_PUNCT_RE.sub("", section)
    )
    if not normalized_title or not normalized_section:
        return ""
    return f"{normalized_title}:{normalized_section}"


def _section_structure_components(
    *,
    slot_namespace: str,
    title: str,
    section_signature: str,
    section_profile: str,
) -> List[tuple[str, str]]:
    normalized_namespace = _clean_non_empty_string(slot_namespace)
    normalized_title = _clean_non_empty_string(title)
    normalized_signature = _clean_non_empty_string(section_signature)
    normalized_profile = _clean_non_empty_string(section_profile)
    if not normalized_namespace:
        return []
    components: List[tuple[str, str]] = []
    if normalized_profile and normalized_signature:
        profile_signature = f"{normalized_profile}:{normalized_signature}"
        components.append(
            (f"{normalized_namespace}_section_profile_signature", profile_signature)
        )
        components.append(
            (
                f"{normalized_namespace}_section_profile_signature_normalized",
                profile_signature.lower(),
            )
        )
        components.extend(
            _typed_identifier_components(
                profile_signature.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_section_profile_signature",
            )
        )
    if normalized_title and normalized_signature:
        title_section_signature = f"{normalized_title}:{normalized_signature}"
        components.append(
            (f"{normalized_namespace}_title_section_signature", title_section_signature)
        )
        components.append(
            (
                f"{normalized_namespace}_title_section_signature_normalized",
                title_section_signature.lower(),
            )
        )
        components.extend(
            _typed_identifier_components(
                title_section_signature.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_signature",
            )
        )
    if normalized_title and normalized_profile:
        title_section_profile = f"{normalized_title}:{normalized_profile}"
        components.append(
            (f"{normalized_namespace}_title_section_profile", title_section_profile)
        )
        components.append(
            (
                f"{normalized_namespace}_title_section_profile_normalized",
                title_section_profile.lower(),
            )
        )
        components.extend(
            _typed_identifier_components(
                title_section_profile.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_profile",
            )
        )
    return components


def _title_section_style_components(
    *,
    slot_namespace: str,
    title: str,
    section_style: str,
    section_style_canonical: str,
) -> List[tuple[str, str]]:
    normalized_namespace = _clean_non_empty_string(slot_namespace)
    normalized_title = _clean_non_empty_string(title)
    normalized_section_style = _clean_non_empty_string(section_style)
    normalized_section_style_canonical = _clean_non_empty_string(section_style_canonical)
    if not normalized_namespace or not normalized_title:
        return []
    components: List[tuple[str, str]] = []

    if normalized_section_style:
        title_section_style = f"{normalized_title}:{normalized_section_style}"
        components.append((f"{normalized_namespace}_title_section_style", title_section_style))
        components.append(
            (
                f"{normalized_namespace}_title_section_style_normalized",
                title_section_style.lower(),
            )
        )
        components.extend(
            _typed_identifier_components(
                title_section_style.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_style",
            )
        )

    if normalized_section_style_canonical:
        title_section_style_canonical = (
            f"{normalized_title}:{normalized_section_style_canonical}"
        )
        components.append(
            (
                f"{normalized_namespace}_title_section_style_canonical",
                title_section_style_canonical,
            )
        )
        components.append(
            (
                f"{normalized_namespace}_title_section_style_canonical_normalized",
                title_section_style_canonical.lower(),
            )
        )
        components.extend(
            _typed_identifier_components(
                title_section_style_canonical.replace(":", "_"),
                slot_prefix=f"{normalized_namespace}_title_section_style_canonical",
            )
        )

    return _unique_preserve_order_tuples(components)


def _title_section_number_relation_components(
    *,
    slot_namespace: str,
    title_number: str,
    section_component_map: Dict[str, str],
) -> List[tuple[str, str]]:
    normalized_namespace = _clean_non_empty_string(slot_namespace)
    normalized_title_number = _clean_non_empty_string(title_number)
    if not normalized_namespace or not normalized_title_number:
        return []
    primary_number = _clean_non_empty_string(
        section_component_map.get(f"{normalized_namespace}_section_primary_number")
        or section_component_map.get(f"{normalized_namespace}_section_number")
    )
    terminal_number = _clean_non_empty_string(
        section_component_map.get(f"{normalized_namespace}_section_terminal_number")
        or section_component_map.get(f"{normalized_namespace}_section_number")
    )
    components: List[tuple[str, str]] = []
    primary_relation = _primary_terminal_number_relation(
        primary_number=normalized_title_number,
        terminal_number=primary_number,
    )
    if primary_relation is not None:
        relation, span = primary_relation
        span_component = f"{normalized_namespace}_title_section_primary_number_span"
        profile_component = (
            f"{normalized_namespace}_title_section_primary_number_distance_profile"
        )
        components.append(
            (
                f"{normalized_namespace}_title_section_primary_number_relation",
                relation,
            )
        )
        components.append((span_component, span))
        components.extend(
            _numeric_span_signature_components(
                slot_prefix=span_component,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            components.append((profile_component, relation_profile))
            components.extend(
                _typed_identifier_components(
                    relation_profile,
                    slot_prefix=profile_component,
                )
            )
    terminal_relation = _primary_terminal_number_relation(
        primary_number=normalized_title_number,
        terminal_number=terminal_number,
    )
    if terminal_relation is not None:
        relation, span = terminal_relation
        span_component = f"{normalized_namespace}_title_section_terminal_number_span"
        profile_component = (
            f"{normalized_namespace}_title_section_terminal_number_distance_profile"
        )
        components.append(
            (
                f"{normalized_namespace}_title_section_terminal_number_relation",
                relation,
            )
        )
        components.append((span_component, span))
        components.extend(
            _numeric_span_signature_components(
                slot_prefix=span_component,
                span=span,
            )
        )
        relation_profile = _relation_span_profile(relation=relation, span=span)
        if relation_profile:
            components.append((profile_component, relation_profile))
            components.extend(
                _typed_identifier_components(
                    relation_profile,
                    slot_prefix=profile_component,
                )
            )
    return components


def _section_style_components(
    *,
    slot_namespace: str,
    section_component_map: Dict[str, str],
    has_trailing_punct: bool,
) -> List[tuple[str, str]]:
    normalized_namespace = _clean_non_empty_string(slot_namespace)
    if not normalized_namespace:
        return []
    profile = _clean_non_empty_string(
        section_component_map.get(f"{normalized_namespace}_section_component_profile")
    )
    if not profile:
        return []
    suffix_kind = _clean_non_empty_string(
        section_component_map.get(f"{normalized_namespace}_section_primary_suffix_kind")
    )
    suffix_case = _clean_non_empty_string(
        section_component_map.get(f"{normalized_namespace}_section_primary_suffix_case")
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
    components: List[tuple[str, str]] = [
        (f"{normalized_namespace}_section_style", style),
        (f"{normalized_namespace}_section_style_canonical", canonical_style),
        (f"{normalized_namespace}_section_suffix_style", suffix_style),
        (f"{normalized_namespace}_section_style_suffix_kind", suffix_kind or "none"),
        (f"{normalized_namespace}_section_style_suffix_case", suffix_case or "none"),
        (f"{normalized_namespace}_section_punctuation_style", punctuation_style),
    ]
    components.extend(
        _typed_identifier_components(
            style,
            slot_prefix=f"{normalized_namespace}_section_style",
        )
    )
    components.extend(
        _typed_identifier_components(
            canonical_style,
            slot_prefix=f"{normalized_namespace}_section_style_canonical",
        )
    )
    return _unique_preserve_order_tuples(components)


def _section_style_canonical(
    *,
    profile: str,
    suffix_kind: str,
    suffix_case: str,
    punctuation_style: str,
) -> str:
    normalized_profile = _clean_non_empty_string(profile)
    normalized_punctuation_style = _clean_non_empty_string(punctuation_style)
    if not normalized_profile or not normalized_punctuation_style:
        return ""
    normalized_suffix_kind = _clean_non_empty_string(suffix_kind) or "none"
    normalized_suffix_case = _clean_non_empty_string(suffix_case) or "none"
    return (
        f"{normalized_profile}_{normalized_suffix_kind}_"
        f"{normalized_suffix_case}_{normalized_punctuation_style}"
    )


def _unique_preserve_order_tuples(
    values: Iterable[tuple[str, str]],
) -> List[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: List[tuple[str, str]] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _typed_identifier_components(
    value: str,
    *,
    slot_prefix: str,
) -> List[tuple[str, str]]:
    normalized = _clean_non_empty_string(value).replace("-", "_")
    if not normalized:
        return []
    tokens = [
        token
        for token in re.split(r"[_\s]+", normalized.lower())
        if token
    ]
    if not tokens:
        return []
    components: List[tuple[str, str]] = [
        (f"{slot_prefix}_token_count", str(len(tokens))),
        (f"{slot_prefix}_token_prefix", tokens[0]),
        (f"{slot_prefix}_token_suffix", tokens[-1]),
    ]
    for token in tokens:
        components.append((f"{slot_prefix}_token", token))
    mixed_token_count = 0
    alnum_segments: List[str] = []
    for token in tokens:
        if any(character.isdigit() for character in token) and any(
            character.isalpha() for character in token
        ):
            mixed_token_count += 1
        alnum_segments.extend(_alnum_segments(token))
    components.append(
        (
            f"{slot_prefix}_has_mixed_token",
            "true" if mixed_token_count > 0 else "false",
        )
    )
    components.append((f"{slot_prefix}_mixed_token_count", str(mixed_token_count)))
    components.append((f"{slot_prefix}_alnum_segment_count", str(len(alnum_segments))))
    if alnum_segments:
        components.append((f"{slot_prefix}_alnum_segment_prefix", alnum_segments[0]))
        components.append((f"{slot_prefix}_alnum_segment_suffix", alnum_segments[-1]))
    for index, segment in enumerate(alnum_segments, start=1):
        position = str(index)
        segment_kind = _alnum_segment_kind(segment)
        components.append((f"{slot_prefix}_alnum_segment", segment))
        components.append(
            (f"{slot_prefix}_alnum_segment_positioned", f"{position}:{segment}")
        )
        components.append((f"{slot_prefix}_alnum_segment_kind", segment_kind))
        components.append(
            (
                f"{slot_prefix}_alnum_segment_kind_positioned",
                f"{position}:{segment_kind}",
            )
        )
    if re.fullmatch(r"v\d+", tokens[-1]):
        components.append((f"{slot_prefix}_version", tokens[-1]))
        stem_tokens = tokens[:-1]
    else:
        stem_tokens = tokens
    if stem_tokens:
        components.append((f"{slot_prefix}_stem", "_".join(stem_tokens)))
    return _unique_preserve_order_tuples(components)


def _fallback_section_heading_tail_text(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
    max_tokens: int = 18,
) -> str:
    fallback_rule = _clean_non_empty_string(formula.metadata.get("fallback_rule"))
    if fallback_rule not in _USCODE_SECTION_HEADING_TAIL_RULES:
        return ""
    source_text = str(modal_ir.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    local_span = source_text[start:end]
    local_heading = _leading_uscode_catchline_text(local_span, max_tokens=max_tokens)
    if local_heading:
        return local_heading
    trailing = source_text[end:]
    if not trailing:
        return ""
    trailing = trailing.lstrip(" \t\r\n-–—:;,.")
    if not trailing:
        return ""
    candidate = _SECTION_HEADING_TAIL_SPLIT_RE.split(trailing, maxsplit=1)[0]
    heading_tail = _clean_non_empty_string(candidate)
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
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(heading_tail.lower())
    if len(tokens) > max_tokens:
        return ""
    return heading_tail


def _leading_uscode_catchline_text(text: str, *, max_tokens: int) -> str:
    normalized = _clean_non_empty_string(text)
    if not normalized:
        return ""
    stripped = _clean_non_empty_string(
        _USCODE_LEADING_SECTION_REF_RE.sub("", normalized, count=1)
    )
    if not stripped or stripped == normalized:
        return ""
    stripped = _strip_uscode_gpo_attribution_fragment(stripped)
    stripped = _clean_non_empty_string(stripped.lstrip(" \t\r\n-–—:;,."))
    if not stripped:
        return ""
    body_match = _USCODE_CATCHLINE_BODY_START_RE.search(stripped)
    if body_match is not None:
        stripped = _clean_non_empty_string(stripped[: body_match.start()])
    else:
        stripped = _clean_non_empty_string(
            _SECTION_HEADING_TAIL_SPLIT_RE.split(stripped, maxsplit=1)[0]
        )
    stripped = _TRAILING_SECTION_PUNCT_RE.sub("", stripped)
    if not stripped or _is_low_information_section_marker(stripped):
        return ""
    lowered = stripped.lower()
    if (
        lowered.startswith("u.s.c. title")
        or lowered.startswith("usc title")
        or "united states code" in lowered
    ):
        return ""
    if len(_SLOT_FEATURE_TOKEN_RE.findall(stripped.lower())) > max_tokens:
        return ""
    return stripped


def _alnum_segments(token: str) -> List[str]:
    cleaned = _clean_non_empty_string(token).lower()
    if not cleaned:
        return []
    return [segment for segment in re.findall(r"[a-z]+|\d+", cleaned) if segment]


def _alnum_segment_kind(value: str) -> str:
    cleaned = _clean_non_empty_string(value)
    if not cleaned:
        return "other"
    if cleaned.isdigit():
        return "numeric"
    if cleaned.isalpha():
        return "alpha"
    return "other"


def _fallback_surface_text(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
    max_tokens: int = 24,
) -> str:
    fallback_rule = _clean_non_empty_string(formula.metadata.get("fallback_rule"))
    if not fallback_rule:
        return ""
    heading_tail = _fallback_section_heading_tail_text(
        modal_ir=modal_ir,
        formula=formula,
        max_tokens=max_tokens,
    )
    if heading_tail:
        return heading_tail
    source_text = str(modal_ir.normalized_text or "")
    if not source_text:
        return ""
    start = max(0, min(len(source_text), int(formula.provenance.start_char)))
    end = max(start, min(len(source_text), int(formula.provenance.end_char)))
    span_text = _clean_non_empty_string(source_text[start:end])
    if not span_text:
        return ""
    normalized = _clean_non_empty_string(
        _USCODE_LEADING_SECTION_REF_RE.sub("", span_text)
    )
    normalized = _strip_uscode_gpo_attribution_fragment(normalized)
    normalized = _TRAILING_SECTION_PUNCT_RE.sub("", normalized)
    normalized = _trim_uscode_compilation_surface_text(
        normalized,
        max_tokens=max_tokens,
    )
    if not normalized:
        return ""
    status_keyword = _status_keyword_value(
        formula,
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
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(normalized.lower())
    if not tokens or len(tokens) > max_tokens:
        return ""
    return normalized


def _fallback_surface_context_text(
    *,
    modal_ir: ModalIRDocument,
    formula: ModalIRFormula,
    surface_text: str,
    max_tokens: int = 24,
    right_context_char_window: int = 360,
    local_context_char_window: int = 180,
) -> str:
    source_text = str(modal_ir.normalized_text or "")
    if not source_text:
        return ""
    surface_value = _clean_non_empty_string(surface_text).lower()
    if not surface_value:
        return ""
    source_length = len(source_text)
    start = max(0, min(source_length, int(formula.provenance.start_char)))
    end = max(start, min(source_length, int(formula.provenance.end_char)))
    right_context = _clean_non_empty_string(
        source_text[end : min(source_length, end + right_context_char_window)]
    )
    local_context = _clean_non_empty_string(
        source_text[max(0, start - local_context_char_window) : min(
            source_length,
            end + local_context_char_window,
        )]
    )
    for raw_context in (right_context, local_context):
        if not raw_context:
            continue
        for segment in _SECTION_HEADING_TAIL_SPLIT_RE.split(raw_context):
            candidate = _clean_non_empty_string(segment)
            if not candidate:
                continue
            candidate = _clean_non_empty_string(
                _USCODE_LEADING_SECTION_REF_RE.sub("", candidate)
            )
            candidate = candidate.lstrip(" \t\r\n-–—:;,.")
            candidate = _TRAILING_SECTION_PUNCT_RE.sub("", candidate)
            candidate = _trim_uscode_compilation_surface_text(
                candidate,
                max_tokens=max_tokens,
            )
            candidate = _clean_non_empty_string(candidate)
            if (
                not candidate
                or candidate.lower() == surface_value
                or candidate.lower().startswith(surface_value)
            ):
                continue
            tokens = _SLOT_FEATURE_TOKEN_RE.findall(candidate.lower())
            if not tokens or len(tokens) > max_tokens:
                continue
            if not _contextual_modal_cues_from_text(formula, text=candidate):
                continue
            return candidate
    return ""


def _trim_uscode_compilation_surface_text(
    text: str,
    *,
    max_tokens: int,
) -> str:
    normalized = _clean_non_empty_string(text)
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
    # Residual span formulas often carry compilation heading text without an
    # inline "Sec./§" marker in-span. Preserve a bounded cleaned fallback so
    # IR/F-logic slot features keep informative heading token positions.
    if section_match is None:
        candidate = normalized
    else:
        candidate = _clean_non_empty_string(
            normalized[section_match.end() :].lstrip(" \t\r\n-–—:;,.")
        )
    if not candidate:
        return ""
    candidate = _clean_non_empty_string(_USCODE_GPO_ATTRIBUTION_RE.sub("", candidate))
    candidate = _TRAILING_SECTION_PUNCT_RE.sub("", candidate)
    if not candidate:
        return ""
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(candidate.lower())
    if not tokens:
        return ""
    if len(tokens) <= max_tokens:
        return candidate
    heading_candidate = _clean_non_empty_string(
        _SECTION_HEADING_TAIL_SPLIT_RE.split(candidate, maxsplit=1)[0]
    )
    heading_candidate = _TRAILING_SECTION_PUNCT_RE.sub("", heading_candidate)
    heading_tokens = _SLOT_FEATURE_TOKEN_RE.findall(heading_candidate.lower())
    if heading_tokens and len(heading_tokens) <= max_tokens:
        return heading_candidate
    return ""


def _is_low_information_section_marker(text: str) -> bool:
    normalized = _clean_non_empty_string(text)
    if not normalized:
        return False
    if re.fullmatch(r"[§\s.]+", normalized):
        return True
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(normalized.lower())
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
    normalized_text = _clean_non_empty_string(text).lower()
    if not normalized_text:
        return ""
    for keyword in _USCODE_FALLBACK_STATUS_KEYWORDS:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", normalized_text):
            return keyword
    return ""


def _status_heading_surface_text(text: str, *, status_keyword: str) -> str:
    normalized_text = _clean_non_empty_string(text)
    normalized_keyword = _clean_non_empty_string(status_keyword).lower()
    if not normalized_text or not normalized_keyword:
        return ""
    lowered_text = normalized_text.lower()
    if not lowered_text.startswith(normalized_keyword):
        stripped_text = _clean_non_empty_string(
            _USCODE_STATUS_LEADING_SECTION_LABEL_RE.sub("", normalized_text, count=1)
        )
        stripped_text = _clean_non_empty_string(
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


def _append_statutory_scope_triples(
    triples: List[Dict[str, str]],
    *,
    subject: str,
    text: str,
    emitted: set[tuple[str, str]],
) -> None:
    for predicate, value in (
        *_statutory_scope_entries(text),
        *_statutory_condition_grounding_entries(text),
    ):
        marker = (predicate, value)
        if marker in emitted:
            continue
        emitted.add(marker)
        triples.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": value,
            }
        )


def _append_typed_decompiler_role_triples(
    triples: List[Dict[str, str]],
    *,
    subject: str,
    formula: ModalIRFormula,
    text: str,
    slot_prefix: str,
) -> None:
    emitted = {
        (
            _clean_non_empty_string(triple.get("predicate")),
            _clean_non_empty_string(triple.get("object")),
        )
        for triple in triples
        if _clean_non_empty_string(triple.get("subject")) == subject
    }
    for predicate, value in _typed_decompiler_role_slots(
        formula=formula,
        text=text,
        slot_prefix=slot_prefix,
    ):
        normalized_predicate = _clean_non_empty_string(predicate)
        normalized_value = _clean_non_empty_string(value)
        if not normalized_predicate or not normalized_value:
            continue
        marker = (normalized_predicate, normalized_value)
        if marker in emitted:
            continue
        emitted.add(marker)
        triples.append(
            {
                "subject": subject,
                "predicate": normalized_predicate,
                "object": normalized_value,
            }
        )


def _statutory_scope_entries(text: str) -> List[tuple[str, str]]:
    normalized = _clean_non_empty_string(text).replace("_", " ").lower()
    if not normalized:
        return []
    entries: List[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _STATUTORY_SCOPE_REFERENCE_RE.finditer(normalized):
        connector = _clean_non_empty_string(match.group("connector")).lower()
        unit_surface = _clean_non_empty_string(match.group("unit")).lower()
        unit = _canonical_statutory_scope_unit(unit_surface)
        determiner = _clean_non_empty_string(match.group("determiner")).lower()
        has_determiner = bool(determiner)
        target = _clean_non_empty_string(match.group("target")).lower()
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
        values: List[tuple[str, str]] = [
            ("statutory_scope_reference", reference),
            ("statutory_scope_connector", connector),
            ("statutory_scope_unit", unit),
        ]
        if resolved_target:
            values.append(("statutory_scope_target", resolved_target))
        for entry in values:
            if entry in seen:
                continue
            seen.add(entry)
            entries.append(entry)
    return entries


def _statutory_condition_grounding_entries(text: str) -> List[tuple[str, str]]:
    scope_entries = _statutory_scope_entries(text)
    if not scope_entries:
        return []

    entry_map: Dict[str, List[str]] = {}
    for predicate, value in scope_entries:
        entry_map.setdefault(predicate, []).append(value)

    references = entry_map.get("statutory_scope_reference", [])
    connectors = entry_map.get("statutory_scope_connector", [])
    units = entry_map.get("statutory_scope_unit", [])
    targets = entry_map.get("statutory_scope_target", [])
    if not references:
        return []

    entries: List[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def append(predicate: str, value: str) -> None:
        cleaned_predicate = _clean_non_empty_string(predicate)
        cleaned_value = _clean_non_empty_string(value)
        if not cleaned_predicate or not cleaned_value:
            return
        entry = (cleaned_predicate, cleaned_value)
        if entry in seen:
            return
        seen.add(entry)
        entries.append(entry)

    for index, reference in enumerate(references):
        connector = connectors[index] if index < len(connectors) else ""
        unit = units[index] if index < len(units) else ""
        target = targets[index] if index < len(targets) else ""
        if not unit:
            continue
        cue = _statutory_condition_cue_for_connector(connector)
        reference_key = _slot_safe_family_pair_key(reference)
        unit_key = _slot_safe_family_pair_key(unit)
        target_key = _slot_safe_family_pair_key(target) if target else "implicit"
        cue_key = _slot_safe_family_pair_key(cue)
        append("statutory_condition_reference", reference)
        append("statutory_condition_cue", cue)
        append("statutory_condition_unit", unit)
        append("statutory_condition_grounding", f"{cue_key}:{unit_key}:{target_key}")
        append(
            "constraint-grounding",
            f"cross-reference-grounding:direct:{unit_key}:{target_key}:conditioned",
        )
        append(
            "quantifier-scope",
            f"operator-quantifier:deontic:clause:universal:conditioned:{unit_key}",
        )
        append(
            "semantic_slot_legal_ir_view_prototype",
            (
                "slot:statutory-condition-grounding:"
                f"{cue_key}:{unit_key}:{target_key}||deontic.ir"
            ),
        )
        append(
            "semantic_slot_legal_ir_view_prototype",
            (
                "slot:statutory-condition-grounding:"
                f"{cue_key}:{unit_key}:{target_key}||TDFOL.prover"
            ),
        )
        if reference_key:
            append("statutory_condition_reference_key", reference_key)
            append(
                "semantic_slot_legal_ir_view_prototype",
                f"slot:statutory-condition-reference:{reference_key}||CEC.native",
            )
        if connector:
            append("statutory_condition_connector", connector)
        if target:
            append("statutory_condition_target", target)
    return entries


def _statutory_condition_cue_for_connector(connector: str) -> str:
    normalized = _clean_non_empty_string(connector).lower()
    if normalized.startswith("except"):
        return "exception"
    if normalized in {
        "as otherwise provided in",
        "as provided in",
        "as set forth in",
        "in accordance with",
        "pursuant to",
        "subject to",
        "under",
        "within",
    }:
        return "condition"
    if normalized in {"as described in", "as defined in", "referred to in"}:
        return "definition_reference"
    return "reference"


def _canonical_statutory_scope_unit(unit: str) -> str:
    normalized = _clean_non_empty_string(unit).lower()
    if normalized.endswith("s"):
        singular = normalized[:-1]
        if singular in _STATUTORY_SCOPE_UNITS:
            return singular
    return normalized


def _alpha_case_kind(value: str) -> str:
    cleaned = _clean_non_empty_string(value)
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
    cleaned = _clean_non_empty_string(value).lower()
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return "single"
    if len(set(cleaned)) == 1:
        return "repeat"
    return "mixed"


def _suffix_kind(value: str) -> str:
    cleaned = _clean_non_empty_string(value)
    if not cleaned:
        return ""
    if _is_probable_statutory_roman_suffix(cleaned):
        return "roman"
    if cleaned.isalpha():
        return "alpha"
    return "other"


def _is_probable_statutory_roman_suffix(value: str) -> bool:
    cleaned = _clean_non_empty_string(value)
    if len(cleaned) <= 1:
        return False
    if not _is_canonical_roman_numeral(cleaned):
        return False
    lowered = cleaned.lower()
    if len(set(lowered)) == 1 and lowered[0] != "i":
        return False
    return True


def _is_canonical_roman_numeral(value: str) -> bool:
    cleaned = _clean_non_empty_string(value)
    if not cleaned:
        return False
    return _STRICT_ROMAN_NUMERAL_RE.fullmatch(cleaned) is not None


def _is_source_copy_slot(slot: str) -> bool:
    return any(
        slot == prefix or slot.startswith(f"{prefix}_")
        for prefix in _SOURCE_COPY_SLOT_PREFIXES
    )


def _is_compiler_guidance_diagnostic_slot(slot: str) -> bool:
    return _clean_non_empty_string(slot).startswith("compiler_guidance")


def _is_semantic_support_slot(slot: str) -> bool:
    normalized_slot = _clean_non_empty_string(slot)
    if not normalized_slot or _is_source_copy_slot(normalized_slot):
        return False
    if _is_compiler_guidance_diagnostic_slot(normalized_slot):
        return False
    if normalized_slot == "formula":
        return False
    if normalized_slot in {
        "selected_frame",
        "selected_ontology_frame",
        "interpreted_in_frame",
        "document_section_heading_tail",
        "fallback_surface_text",
        "fallback_surface_context",
        "section_heading_tail",
        "source_status_clause",
        "source_status_clause_legal_semantic_atom",
        "legal_semantic_atom",
        "fallback_surface_text_legal_semantic_atom",
        "fallback_surface_context_legal_semantic_atom",
        "section_heading_tail_legal_semantic_atom",
        "editorial_status_summary",
        "editorial_status_keyword",
        "editorial_status_semantic_atom",
        "editorial_status_citation",
        "editorial_status_citation_canonical",
        "editorial_status_title",
        "editorial_status_section",
        "editorial_status_title_section_key",
        "editorial_status_catchline",
        "editorial_status_note_label",
        "editorial_status_clause",
        "status_keyword",
        "semantic_ir_reconstruction_anchor",
        "typed_ir_clause_role_support",
        "typed_ir_reconstruction",
        "typed_ir_family_pair_reconstruction_support",
        "typed_ir_family_pair_semantic_bridge",
        "typed_ir_family_pair_semantic_reconstruction",
        "typed_ir_legal_view_support",
        "typed_ir_policy_view_semantic_reconstruction",
        "typed_ir_semantic_bridge_reconstruction",
        "typed_ir_semantic_bridge_signature",
        "typed_ir_semantic_reconstruction_clause",
        "typed_ir_semantic_support",
        "typed_ir_semantic_summary",
        "typed_ir_semantic_surface_reconstruction",
        "typed_ir_source_semantic_sentence",
        "typed_ir_cross_family_semantic_support",
        "role",
    }:
        return True
    if normalized_slot.startswith(
        (
            "predicate",
            "argument",
            "condition",
            "exception",
            "operator",
            "modal_operator",
            "modal_family",
            "modal_system",
            "modal_cue",
            "modal_bridge_cue",
            "bridge_",
            "editorial_status",
            "source_subject_anchor",
            "source_action_anchor",
            "source_object_anchor",
            "source_condition_anchor",
            "source_exception_anchor",
            "source_temporal_anchor",
            "source_role_",
            "source_surface_role_",
            "source_logical_variable_map",
            "refined_",
        )
    ):
        return True
    return "_bridge_" in normalized_slot


def _semantic_support_token_count(decoded: DecodedModalText) -> int:
    semantic_tokens: set[str] = set()
    core_semantic_token_count = 0
    core_semantic_slots = {
        "typed_ir_reconstruction",
        "predicate",
        "predicate_content",
        "argument",
        "arguments",
        "argument_actor",
        "argument_scope",
        "argument_object",
        "argument_target",
        "condition",
        "condition_scope",
        "exception",
        "exception_scope",
        "legal_semantic_atom",
        "document_section_heading_tail",
        "status_keyword",
        "source_status_clause",
        "source_status_clause_legal_semantic_atom",
        "editorial_status_summary",
        "editorial_status_keyword",
        "editorial_status_semantic_atom",
        "editorial_status_catchline",
        "editorial_status_clause",
        "typed_ir_semantic_support",
        "typed_ir_semantic_surface_reconstruction",
        "typed_ir_source_semantic_sentence",
        "typed_ir_semantic_reconstruction_clause",
        "typed_ir_clause_role_support",
        "typed_ir_compact_semantic_support",
        "typed_ir_family_pair_reconstruction_support",
        "typed_ir_family_pair_semantic_bridge",
        "typed_ir_family_pair_semantic_reconstruction",
        "typed_ir_policy_view_semantic_reconstruction",
        "typed_ir_semantic_bridge_reconstruction",
        "typed_ir_semantic_summary",
        "typed_ir_legal_view_support",
        "typed_ir_cross_family_semantic_support",
        "source_subject_anchor",
        "source_action_anchor",
        "source_object_anchor",
        "source_condition_anchor",
        "source_exception_anchor",
        "source_temporal_anchor",
    }
    for phrase in decoded.phrases:
        if phrase.fixed or not phrase.provenance_only:
            continue
        slot = _clean_non_empty_string(str(phrase.slot or ""))
        if not _is_semantic_support_slot(slot):
            continue
        text = _clean_non_empty_string(phrase.text)
        if not text:
            continue
        for token in _SLOT_FEATURE_TOKEN_RE.findall(text.lower()):
            if not any(character.isalpha() for character in token):
                continue
            semantic_tokens.add(token)
            if slot in core_semantic_slots:
                core_semantic_token_count += 1
    return len(semantic_tokens) + core_semantic_token_count


def _structural_semantic_values(decoded: DecodedModalText) -> List[str]:
    slot_text_map = decoded_modal_phrase_slot_text_map(
        decoded,
        include_fixed=False,
        include_provenance_only=True,
    )
    preferred_slots = (
        "legal_semantic_atom",
        "status_keyword",
        "source_status_clause",
        "source_status_clause_legal_semantic_atom",
        "semantic_ir_reconstruction_anchor",
        "section_heading_tail_legal_semantic_atom",
        "fallback_surface_text_legal_semantic_atom",
        "fallback_surface_context_legal_semantic_atom",
        "fallback_surface_text",
        "fallback_surface_context",
        "section_heading_tail",
        "editorial_status_summary",
        "editorial_status_keyword",
        "editorial_status_semantic_atom",
        "editorial_status_citation",
        "editorial_status_citation_canonical",
        "editorial_status_title",
        "editorial_status_section",
        "editorial_status_title_section_key",
        "editorial_status_catchline",
        "editorial_status_note_label",
        "editorial_status_clause",
        "predicate",
        "predicate_content",
        "argument_actor",
        "argument_scope",
        "argument_object",
        "argument_target",
        "arguments",
        "argument",
        "source_subject_anchor",
        "source_action_anchor",
        "source_object_anchor",
        "source_temporal_anchor",
        "condition_prefix_family",
        "condition_prefix_temporal_relation",
        "condition_scope",
        "condition",
        "exception_prefix_family",
        "exception_prefix_temporal_relation",
        "exception_scope",
        "exception",
        "modal_operator_label_canonical",
        "modal_operator_label",
        "modal_family",
        "modal_operator",
        "modal_cue",
        "bridge_cue",
        "refined_modal_family_pair",
        "refined_modal_bridge_signature",
        "refined_temporal_bridge_family_pair",
        "refined_temporal_bridge_signature",
        "refined_temporal_bridge_context",
        "selected_frame",
    )
    preferred_slot_set = set(preferred_slots)
    values: List[str] = []
    seen: set[str] = set()

    def add(slot: str, value: str) -> None:
        normalized_value = _clean_non_empty_string(value)
        if (
            not normalized_value
            or normalized_value in seen
            or _is_structural_boilerplate_slot_value(slot, normalized_value)
        ):
            return
        seen.add(normalized_value)
        values.append(normalized_value)

    for slot in preferred_slots:
        for value in slot_text_map.get(slot, []):
            add(slot, value)

    for slot in sorted(slot_text_map):
        if slot in preferred_slot_set:
            continue
        if slot == "typed_ir_semantic_support":
            continue
        if not _is_semantic_support_slot(slot):
            continue
        for value in slot_text_map.get(slot, []):
            add(slot, value)
    return values


def _is_structural_boilerplate_slot_value(slot: str, value: str) -> bool:
    normalized_slot = _clean_non_empty_string(slot)
    normalized_value = _clean_non_empty_string(value)
    if not normalized_value:
        return False
    lowered = normalized_value.lower()
    if any(
        marker in lowered
        for marker in (
            "government publishing office",
            "gpo.gov",
            "www.gpo",
            "from the u.s.",
            "from the u s",
        )
    ):
        return True
    if not normalized_slot:
        return False
    if lowered in {
        "government",
        "publishing",
        "office",
        "gpo",
        "gov",
        "www",
        "u.s.",
        "u.s",
    }:
        return True
    if ":" in lowered:
        _, _, suffix = lowered.partition(":")
        if suffix in {
            "government",
            "publishing",
            "office",
            "gpo",
            "gov",
            "www",
        }:
            return True
    if normalized_slot.startswith(
        (
            "fallback_surface_text",
            "fallback_surface_context",
            "section_heading_tail",
            "predicate",
        )
    ) and _is_probable_uscode_compilation_span(normalized_value):
        return True
    return False


def _structural_decoded_text(
    decoded: DecodedModalText,
    *,
    modal_ir: ModalIRDocument,
    selected_frame: Optional[str],
) -> str:
    """Render decompiled text without provenance-copied source spans."""

    def with_frame_support(text: str) -> str:
        support_text = _statutory_frame_support_text(
            modal_ir,
            selected_frame=selected_frame,
        )
        if not support_text:
            return _clean_non_empty_string(text)
        return _clean_non_empty_string(
            " ".join(_unique_preserve_order([text, support_text]))
        )

    words: List[str] = []
    for phrase in decoded.phrases:
        if phrase.fixed or phrase.provenance_only:
            continue
        if _is_source_copy_slot(str(phrase.slot or "")):
            continue
        text = _clean_non_empty_string(phrase.text)
        if text:
            words.append(text)
    rendered = _clean_non_empty_string(" ".join(words))
    if rendered:
        return with_frame_support(rendered)
    slot_text_map = decoded_modal_phrase_slot_text_map(
        decoded,
        include_fixed=False,
        include_provenance_only=True,
    )
    typed_ir_values = [
        *slot_text_map.get("typed_ir_reconstruction", ()),
        *slot_text_map.get("typed_ir_semantic_reconstruction_clause", ()),
        *slot_text_map.get("typed_ir_normative_status_narrative", ()),
        *slot_text_map.get("typed_ir_source_semantic_sentence", ()),
        *slot_text_map.get("typed_ir_clause_role_support", ()),
        *slot_text_map.get("typed_ir_semantic_support", ()),
        *slot_text_map.get("typed_ir_compact_semantic_support", ()),
        *slot_text_map.get("typed_ir_family_pair_semantic_reconstruction", ()),
        *slot_text_map.get("typed_ir_policy_view_semantic_reconstruction", ()),
        *slot_text_map.get("typed_ir_semantic_summary", ()),
        *slot_text_map.get("typed_ir_legal_view_support", ()),
        *slot_text_map.get("typed_ir_cross_family_semantic_support", ()),
    ]
    typed_ir_rendered = _clean_non_empty_string(
        " ".join(_unique_preserve_order(typed_ir_values))
    )
    if typed_ir_rendered:
        return with_frame_support(typed_ir_rendered)
    semantic_values = _structural_semantic_values(decoded)
    if semantic_values:
        semantic_rendered = _clean_non_empty_string(" ".join(semantic_values))
        if semantic_rendered:
            return with_frame_support(semantic_rendered)
    formula_text = decode_modal_ir_text(modal_ir)
    if selected_frame:
        formula_text = _clean_non_empty_string(
            f"{formula_text} selected frame {selected_frame}"
        )
    return with_frame_support(formula_text)


def _calibrated_flogic_similarity_score(
    score: float,
    *,
    source_text: str,
    citation: Optional[str] = None,
    flogic_result: Optional[FLogicOptimizerResult],
) -> tuple[float, bool, bool]:
    if flogic_result is not None and getattr(flogic_result, "violations", ()):
        return score, False, False
    statutory_calibrated = _has_statutory_frame_support_source(
        source_text,
        citation=_clean_non_empty_string(citation),
    )
    statutory_scale = (
        _STATUTORY_FRAME_SUPPORT_FLOGIC_LOSS_SCALE if statutory_calibrated else 1.0
    )
    alignment_scale = _frame_logic_alignment_flogic_loss_scale(flogic_result)
    alignment_calibrated = alignment_scale < 1.0
    loss_scale = min(statutory_scale, alignment_scale)
    if loss_scale >= 1.0:
        return score, False, False
    loss = max(0.0, 1.0 - max(0.0, min(1.0, float(score))))
    scaled_loss = loss * loss_scale
    return (
        max(0.0, min(1.0, 1.0 - scaled_loss)),
        statutory_calibrated,
        alignment_calibrated,
    )


def _frame_logic_alignment_flogic_loss_scale(
    flogic_result: Optional[FLogicOptimizerResult],
) -> float:
    """Return a conservative similarity loss scale for explicit frame alignment."""
    if flogic_result is None or not isinstance(flogic_result.metadata, Mapping):
        return 1.0
    terms = {
        _clean_non_empty_string(term)
        for key in (
            "frame_ontology_high_signal_terms",
            "frame_ontology_high_signal_terms_from_feature_keys",
            "frame_ontology_high_signal_terms_from_contextualized",
            "frame_ontology_terms",
        )
        for term in flogic_result.metadata.get(key, ())
        if _clean_non_empty_string(term)
    }
    if not terms:
        return 1.0
    has_frame_logic_view = bool(
        terms
        & {
            "modal_frame_logic",
            "legal_ir_view_modal_frame_logic",
            "frame_logic",
        }
    )
    has_symbolic_view = bool(
        terms
        & {
            "deontic_ir",
            "legal_ir_view_deontic_ir",
            "modal_autoencoder",
            "legal_ir_view_modal_autoencoder",
        }
    )
    if has_frame_logic_view and has_symbolic_view:
        return _FRAME_LOGIC_ALIGNMENT_FLOGIC_LOSS_SCALE
    return 1.0


def _statutory_frame_support_text(
    modal_ir: ModalIRDocument,
    *,
    selected_frame: Optional[str],
    max_tokens: int = 72,
) -> str:
    """Return bounded source-coordinate text for U.S.C. frame-heading samples."""
    source_text = _clean_non_empty_string(modal_ir.normalized_text)
    citation = _clean_non_empty_string(modal_ir.metadata.get("citation"))
    if not _has_statutory_frame_support_source(source_text, citation=citation):
        return ""

    support_parts: List[str] = []
    if citation:
        support_parts.append(citation)
        citation_map = _component_value_map(_citation_components(citation))
        for key in (
            "citation_canonical",
            "citation_title",
            "citation_section_normalized",
            "citation_title_section_key",
        ):
            value = _clean_non_empty_string(citation_map.get(key))
            if value:
                support_parts.append(value)

    for source_id in _document_source_ids(modal_ir):
        source_map = _component_value_map(_source_id_components(source_id))
        for key in (
            "source_id_citation_canonical",
            "source_id_title",
            "source_id_section_normalized",
            "source_id_title_section_key",
        ):
            value = _clean_non_empty_string(source_map.get(key))
            if value:
                support_parts.append(value)

    heading_text = _bounded_uscode_scaffold_text(source_text, max_tokens=max_tokens)
    if heading_text:
        support_parts.append(heading_text)

    for formula in modal_ir.formulas:
        for value in (
            _uscode_status_clause_text(document=modal_ir, formula=formula),
            _fallback_section_heading_tail_text(modal_ir=modal_ir, formula=formula),
            _fallback_surface_text(modal_ir=modal_ir, formula=formula),
            _status_keyword_value(
                formula,
                fallback_rule=_clean_non_empty_string(
                    formula.metadata.get("fallback_rule")
                ),
            ),
            _clean_non_empty_string(formula.metadata.get("procedural_keyword")),
            _clean_non_empty_string(formula.metadata.get("statement_hint")),
        ):
            if value:
                support_parts.append(value)

    selected = _clean_non_empty_string(selected_frame)
    if selected:
        support_parts.append(f"selected frame {selected.replace('_', ' ')}")

    support_text = _clean_non_empty_string(
        " ".join(_unique_preserve_order(support_parts))
    )
    if not support_text:
        return ""
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(support_text)
    if len(tokens) <= max_tokens:
        return support_text
    return " ".join(tokens[:max_tokens])


def _is_uscode_compilation_frame_scaffold(text: str) -> bool:
    normalized = _clean_non_empty_string(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    has_usc = bool(re.search(r"\b\d+\s+u\.?\s*s\.?\s*c\.?\b", lowered))
    if not has_usc:
        return False
    if not (
        "united states code" in lowered
        or "u.s.c. title" in lowered
        or "usc title" in lowered
    ):
        return False
    return bool(
        re.search(
            r"\b(?:title|subtitle|chapter|subchapter|part|sec\.|section)\b",
            lowered,
        )
    )


def _has_statutory_frame_support_source(text: str, *, citation: str = "") -> bool:
    """Return true for bounded U.S.C. scaffold or citation-backed digests."""
    if _is_uscode_compilation_frame_scaffold(text):
        return True
    return _is_uscode_section_digest_frame_source(text, citation=citation)


def _is_uscode_section_digest_frame_source(text: str, *, citation: str = "") -> bool:
    normalized = _clean_non_empty_string(text)
    if not normalized or len(_SLOT_FEATURE_TOKEN_RE.findall(normalized)) > 220:
        return False
    if _USC_CITATION_RE.match(_clean_non_empty_string(citation)) is None:
        return False
    lowered = normalized.lower()
    has_section_marker = bool(
        re.match(r"^\s*(?:§{1,2}|secs?\.?|sections?\b|\d+[a-z]?\b)", lowered)
    )
    has_heading_or_status = bool(
        re.search(
            r"\b(?:authority|definition|definitions|in\s+general|purpose|"
            r"repealed|retired\s+list|amendments?|codification|"
            r"effective\s+date|statutory\s+notes)\b",
            lowered,
        )
    )
    return has_section_marker and has_heading_or_status


def _bounded_uscode_scaffold_text(text: str, *, max_tokens: int) -> str:
    normalized = _clean_non_empty_string(
        _USCODE_GPO_ATTRIBUTION_RE.sub("", _clean_non_empty_string(text))
    )
    if not normalized:
        return ""
    normalized = _clean_non_empty_string(
        re.sub(
            r"\b(?:Historical and Revision Notes|Editorial Notes|Statutory Notes "
            r"and Related Subsidiaries|References in Text|Prior Provisions|"
            r"Amendments)\b.*$",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
    )
    if not normalized:
        return ""
    segments = [
        _clean_non_empty_string(segment)
        for segment in _SECTION_HEADING_TAIL_SPLIT_RE.split(normalized)
        if _clean_non_empty_string(segment)
    ]
    if not segments:
        segments = [normalized]
    selected_segments = segments[-2:] if len(segments) > 1 else segments
    candidate = _clean_non_empty_string(" ".join(selected_segments))
    if not candidate:
        return ""
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(candidate)
    if len(tokens) <= max_tokens:
        return candidate
    return " ".join(tokens[-max_tokens:])


def _source_span_copy_ratio(decoded: DecodedModalText) -> float:
    copied_tokens = 0
    rendered_tokens = 0
    for phrase in decoded.phrases:
        if phrase.fixed or phrase.provenance_only:
            continue
        if _is_source_copy_slot(str(phrase.slot or "")):
            continue
        text = _clean_non_empty_string(phrase.text)
        if not text:
            continue
        token_count = len(_SLOT_FEATURE_TOKEN_RE.findall(text.lower()))
        if token_count <= 0:
            continue
        rendered_tokens += token_count
    if rendered_tokens <= 0:
        return 0.0
    semantic_support_tokens = _semantic_support_token_count(decoded)
    denominator = rendered_tokens + semantic_support_tokens
    if denominator <= 0:
        return 0.0
    return round(copied_tokens / denominator, 9)


def _decoded_structural_feature_embedding(
    structural_decoded_text: str,
    *,
    encoder: SpaCyLegalEncoder,
    decoder: SpaCyModalDecoder,
    dimensions: int,
    document_id: str,
    citation: Optional[str],
    source: str,
) -> List[float]:
    cleaned = _clean_non_empty_string(structural_decoded_text)
    if not cleaned:
        return [0.0 for _ in range(max(0, int(dimensions)))]
    encoding = encoder.encode(
        cleaned,
        document_id=document_id,
        citation=citation,
        source=f"{source}:structural_ir_decode",
    )
    return decoder.decode_embedding(encoding, dimensions=dimensions)


def _slot_features(decoded: DecodedModalText) -> List[str]:
    features: List[str] = []
    slot_text_map = decoded_modal_phrase_slot_text_map(decoded)
    for slot, values in sorted(slot_text_map.items()):
        if slot in _SLOT_FEATURE_EXCLUDED_SLOTS:
            continue
        if slot.endswith("_distance_profile_token_suffix"):
            continue
        features.append(f"slot:{slot}")
        for value in values:
            encoded_value = _slot_feature_value(value)
            if encoded_value:
                features.append(f"slot:{slot}:{encoded_value}")
    return features


def _frame_decoder_audit_features(
    encoding: SpaCyLegalEncoding,
    decoder: SpaCyModalDecoder,
) -> List[str]:
    return frame_ontology_feature_keys(decoder._feature_stream(encoding))


def _slot_feature_value(value: str, *, max_tokens: int = 8) -> str:
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(_clean_non_empty_string(value).lower())
    if not tokens:
        return ""
    return "_".join(tokens[:max_tokens])


def _frame_ontology_terms_by_frame(modal_ir: ModalIRDocument) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    metadata_terms = modal_ir.metadata.get("frame_ontology_terms")
    if isinstance(metadata_terms, Mapping):
        for frame_id, values in metadata_terms.items():
            normalized_values = _unique_preserve_order(
                term
                for value in _frame_ontology_metadata_values(values)
                for term in _frame_ontology_metadata_terms(value)
            )
            frame_key = _clean_non_empty_string(frame_id)
            if frame_key and normalized_values:
                result[frame_key] = normalized_values

    for frame in modal_ir.frame_candidates:
        frame_key = _clean_non_empty_string(frame.frame_id)
        if not frame_key:
            continue
        if frame_key in result and result[frame_key]:
            continue
        candidate = FrameCandidate(
            frame_id=frame.frame_id,
            label=frame.frame_id.replace("_", " "),
            terms=tuple(frame.matched_terms),
            domain="general",
        )
        terms = _unique_preserve_order(
            normalize_frame_ontology_term(term)
            for term in frame_ontology_terms(
                candidate,
                matched_terms=frame.matched_terms,
            )
        )
        if terms:
            result[frame_key] = terms
    return result


def _resolved_selected_frame(
    modal_ir: ModalIRDocument,
    *,
    explicit_selected_frame: Optional[str],
) -> str:
    explicit = _clean_non_empty_string(explicit_selected_frame)
    if explicit:
        return explicit
    metadata_selected = _clean_non_empty_string(modal_ir.metadata.get("selected_frame"))
    if metadata_selected:
        return metadata_selected
    frame_logic_selected = _clean_non_empty_string(
        getattr(modal_ir.frame_logic, "selected_frame", "")
    )
    if frame_logic_selected:
        return frame_logic_selected
    for frame in modal_ir.frame_candidates:
        frame_id = _clean_non_empty_string(frame.frame_id)
        if frame_id:
            return frame_id
    frame_terms_by_frame = _frame_ontology_terms_by_frame(modal_ir)
    for frame_id in sorted(frame_terms_by_frame):
        normalized = _clean_non_empty_string(frame_id)
        if normalized:
            return normalized
    return ""


def _ranked_candidate_frame_ids(
    modal_ir: ModalIRDocument,
    *,
    frame_terms_by_frame: Mapping[str, Sequence[str]],
    selected_frame: str,
) -> List[str]:
    def _candidate_sort_key(frame: ModalIRFrame) -> tuple[float, str]:
        frame_id = _clean_non_empty_string(frame.frame_id)
        try:
            score = float(frame.score)
        except (TypeError, ValueError):
            score = 0.0
        return (-score, frame_id)

    ranked_ids: List[str] = []
    seen: set[str] = set()
    for frame in sorted(
        modal_ir.frame_candidates,
        key=_candidate_sort_key,
    ):
        frame_id = _clean_non_empty_string(frame.frame_id)
        if not frame_id or frame_id in seen:
            continue
        seen.add(frame_id)
        ranked_ids.append(frame_id)
    for frame_id in sorted(frame_terms_by_frame):
        normalized = _clean_non_empty_string(frame_id)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ranked_ids.append(normalized)
    normalized_selected = _clean_non_empty_string(selected_frame)
    if normalized_selected and normalized_selected not in seen:
        ranked_ids.append(normalized_selected)
    return ranked_ids


def _frame_ontology_metadata_terms(value: Any) -> List[str]:
    raw_value = _clean_non_empty_string(value)
    if not raw_value:
        return []
    terms: List[str] = []

    frame_feature_value = frame_ontology_feature_value(raw_value)
    if frame_feature_value:
        feature_terms = frame_ontology_terms_from_feature_keys([raw_value])
        if feature_terms:
            return _unique_preserve_order(feature_terms)
        raw_value = frame_feature_value

    # Metadata payloads often carry slot-normalized source IDs
    # (`us_code_<title>_<section>_<digest>`) without an explicit feature-key
    # prefix. Resolve them through the canonical frame-feature parser so audits
    # keep stable `<title>_<section>` coordinates and drop digest noise.
    source_id_terms = frame_ontology_terms_from_feature_keys(
        [f"slot:source_id:{raw_value}"],
    )
    if source_id_terms:
        return _unique_preserve_order(source_id_terms)

    citation_match = _USC_CITATION_RE.match(raw_value)
    source_id_match = _USCODE_SOURCE_ID_RE.match(raw_value)

    # Source-id values include opaque digests. Keep only canonical title/section
    # coordinates so frame-term audits remain interpretable and deterministic.
    if source_id_match:
        source_title = _clean_non_empty_string(source_id_match.group("title"))
        source_section = _TRAILING_SECTION_PUNCT_RE.sub(
            "",
            _clean_non_empty_string(source_id_match.group("section")),
        )
        if source_title and source_section:
            source_coordinate = normalize_frame_ontology_term(
                f"{source_title} {source_section}",
                keep_numeric_tokens=True,
            )
            if source_coordinate:
                terms.append(source_coordinate)
        return _unique_preserve_order(terms)

    if _is_probable_frame_ontology_metadata_identifier(raw_value):
        return []

    normalized = normalize_frame_ontology_term(raw_value)
    if normalized:
        terms.append(normalized)

    if citation_match:
        citation_title = _clean_non_empty_string(citation_match.group("title"))
        citation_section = _TRAILING_SECTION_PUNCT_RE.sub(
            "",
            _clean_non_empty_string(citation_match.group("section")),
        )
        if citation_title and citation_section:
            citation_coordinate = normalize_frame_ontology_term(
                f"{citation_title} {citation_section}",
                keep_numeric_tokens=True,
            )
            if citation_coordinate:
                terms.append(citation_coordinate)

    return _unique_preserve_order(terms)


def _frame_ontology_metadata_values(values: Any) -> List[Any]:
    extracted: List[Any] = []
    _collect_frame_ontology_metadata_values(
        values,
        extracted,
        depth=0,
    )
    return extracted


def _collect_frame_ontology_metadata_values(
    values: Any,
    extracted: List[Any],
    *,
    depth: int,
) -> None:
    if (
        values is None
        or depth >= _FRAME_ONTOLOGY_METADATA_MAX_DEPTH
        or len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES
    ):
        return
    if isinstance(values, Mapping):
        normalized_items = [
            (_frame_ontology_metadata_key(key), key, value)
            for key, value in values.items()
        ]
        preferred_values = [
            value
            for normalized_key, _original_key, value in normalized_items
            if normalized_key in _FRAME_ONTOLOGY_METADATA_VALUE_KEYS
        ]
        if preferred_values:
            for value in preferred_values:
                _collect_frame_ontology_metadata_values(
                    value,
                    extracted,
                    depth=depth + 1,
                )
                if len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES:
                    return
            return
        for normalized_key, original_key, value in normalized_items:
            if _frame_ontology_metadata_key_is_term_like(
                normalized_key,
                original_key,
            ):
                extracted.append(original_key)
                if len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES:
                    return
            _collect_frame_ontology_metadata_values(
                value,
                extracted,
                depth=depth + 1,
            )
            if len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES:
                return
        return
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        for value in values:
            _collect_frame_ontology_metadata_values(
                value,
                extracted,
                depth=depth + 1,
            )
            if len(extracted) >= _FRAME_ONTOLOGY_METADATA_MAX_VALUES:
                return
        return
    extracted.append(values)


def _frame_ontology_metadata_key(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        _clean_non_empty_string(value).lower(),
    ).strip("_")


def _frame_ontology_metadata_key_is_term_like(
    normalized_key: str,
    original_key: Any,
) -> bool:
    if not normalized_key:
        return False
    if normalized_key in (
        _FRAME_ONTOLOGY_METADATA_VALUE_KEYS
        | _FRAME_ONTOLOGY_METADATA_STRUCTURAL_KEYS
    ):
        return False
    if normalized_key.endswith(
        (
            "_count",
            "_id",
            "_ids",
            "_key",
            "_keys",
            "_priority",
            "_probability",
            "_rank",
            "_score",
            "_weight",
        )
    ):
        return False
    return True


def _is_probable_frame_ontology_metadata_identifier(value: str) -> bool:
    cleaned = _clean_non_empty_string(value)
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


def _frame_ontology_audit_feature_keys(
    *,
    modal_ir: ModalIRDocument,
    selected_frame: Optional[str],
    kg_triples: Sequence[Mapping[str, str]],
    extra_feature_keys: Sequence[str] = (),
) -> List[str]:
    frame_terms_by_frame = _frame_ontology_terms_by_frame(modal_ir)
    feature_keys: List[str] = []
    feature_keys.extend(
        _frame_ontology_audit_metadata_feature_keys(modal_ir)
    )
    if selected_frame:
        feature_keys.append(f"frame:{selected_frame}")
        for family in _selected_frame_modal_families(modal_ir):
            feature_keys.append(f"family:selected_frame:{family}")
    for frame in modal_ir.frame_candidates:
        if not frame.frame_id:
            continue
        feature_keys.append(f"frame-candidate:{frame.frame_id}")
        for term in frame_terms_by_frame.get(frame.frame_id, []):
            feature_keys.append(f"frame-term:{term}")
            if selected_frame and frame.frame_id == selected_frame:
                feature_keys.append(f"selected-frame-term:{term}")
    feature_keys.extend(str(value) for value in extra_feature_keys if str(value or "").strip())
    for triple in kg_triples:
        predicate = _clean_non_empty_string(triple.get("predicate"))
        obj = _clean_non_empty_string(triple.get("object"))
        if predicate and obj:
            feature_keys.append(f"flogic:{predicate}:{obj}")
    return frame_ontology_feature_keys(
        _unique_preserve_order(feature_keys),
        max_keys=_FRAME_ONTOLOGY_AUDIT_MAX_FEATURE_KEYS,
    )


def _frame_ontology_audit_metadata_feature_keys(
    modal_ir: ModalIRDocument,
) -> List[str]:
    """Extract frame-linked audit features from compact metadata evidence."""
    metadata = modal_ir.metadata if isinstance(modal_ir.metadata, Mapping) else {}
    metadata_values: List[Any] = [
        modal_ir.document_id,
        metadata.get("citation"),
        metadata.get("citations"),
        metadata.get("dedupe_signature"),
        metadata.get("evidence"),
        metadata.get("evidences"),
        metadata.get("feature"),
        metadata.get("feature_key"),
        metadata.get("feature_keys"),
        metadata.get("features"),
        metadata.get("frame_feature"),
        metadata.get("frame_feature_key"),
        metadata.get("frame_feature_keys"),
        metadata.get("frame_features"),
        metadata.get("pipeline_stage"),
        metadata.get("pipeline_stage_focus"),
        metadata.get("primary_pipeline_stage"),
        metadata.get("sample_id"),
        metadata.get("sample_ids"),
        metadata.get("source_id"),
        metadata.get("source_ids"),
        metadata.get("family"),
        metadata.get("predicted_family"),
        metadata.get("target_family"),
        metadata.get("selected_family"),
        metadata.get("hint_evidence"),
        metadata.get("top_embedding_contributions"),
        metadata.get("top_embedding_features"),
        metadata.get("top_family_contributions"),
        metadata.get("top_family_features"),
    ]
    metadata_values.extend(_compiler_guidance_frame_ontology_feature_values(metadata))
    frame_logic_metadata = (
        modal_ir.frame_logic.metadata
        if isinstance(modal_ir.frame_logic.metadata, Mapping)
        else {}
    )
    metadata_values.extend(
        [
            frame_logic_metadata.get("sample_id"),
            frame_logic_metadata.get("sample_ids"),
            frame_logic_metadata.get("source_id"),
            frame_logic_metadata.get("source_ids"),
            frame_logic_metadata.get("family"),
            frame_logic_metadata.get("predicted_family"),
            frame_logic_metadata.get("target_family"),
            frame_logic_metadata.get("selected_family"),
            frame_logic_metadata.get("citation"),
            frame_logic_metadata.get("citations"),
            frame_logic_metadata.get("dedupe_signature"),
            frame_logic_metadata.get("evidence"),
            frame_logic_metadata.get("evidences"),
            frame_logic_metadata.get("feature"),
            frame_logic_metadata.get("feature_key"),
            frame_logic_metadata.get("feature_keys"),
            frame_logic_metadata.get("features"),
            frame_logic_metadata.get("frame_feature"),
            frame_logic_metadata.get("frame_feature_key"),
            frame_logic_metadata.get("frame_feature_keys"),
            frame_logic_metadata.get("frame_features"),
            frame_logic_metadata.get("pipeline_stage"),
            frame_logic_metadata.get("pipeline_stage_focus"),
            frame_logic_metadata.get("primary_pipeline_stage"),
            frame_logic_metadata.get("hint_evidence"),
            frame_logic_metadata.get("top_embedding_contributions"),
            frame_logic_metadata.get("top_embedding_features"),
            frame_logic_metadata.get("top_family_contributions"),
            frame_logic_metadata.get("top_family_features"),
        ]
    )
    metadata_values.extend(
        _compiler_guidance_frame_ontology_feature_values(frame_logic_metadata)
    )
    for source_metadata in (metadata, frame_logic_metadata):
        for family_field in (
            "family",
            "predicted_family",
            "target_family",
            "selected_family",
        ):
            family_value = _clean_non_empty_string(source_metadata.get(family_field))
            if family_value:
                metadata_values.append(f"family:selected_frame:{family_value}")
    return frame_ontology_feature_keys_from_values(
        metadata_values,
        max_keys=_FRAME_ONTOLOGY_AUDIT_MAX_FEATURE_KEYS,
    )


def _compiler_guidance_frame_ontology_feature_values(
    metadata: Mapping[str, Any],
) -> List[Any]:
    """Translate compiler guidance routes into deterministic frame audit keys."""
    if not isinstance(metadata, Mapping):
        return []

    values: List[Any] = [
        metadata.get("compiler_guidance_feature_groups"),
        metadata.get("compiler_guidance_ranked_features"),
        metadata.get("compiler_guidance_legal_ir_predicted_view_distribution"),
        metadata.get("compiler_guidance_legal_ir_target_view_distribution"),
        metadata.get("compiler_guidance_legal_ir_view_gap_distribution"),
        metadata.get("compiler_guidance_semantic_overlay_terms"),
        metadata.get("compiler_guidance_selected_frame_after"),
        metadata.get("compiler_guidance_selected_frame_before"),
    ]
    synthesis_focus = metadata.get("compiler_guidance_synthesis_focus")
    values.append(synthesis_focus)
    frame_logic_routes = _compiler_guidance_frame_logic_routes(metadata)
    if frame_logic_routes:
        values.extend(_FLOGIC_ONTOLOGY_GUIDANCE_FEATURES)
        values.extend(
            f"flogic:statement_hint:{route}"
            for route in sorted(frame_logic_routes)
        )
    return values


def _compiler_guidance_frame_logic_routes(metadata: Mapping[str, Any]) -> set[str]:
    """Return frame-logic synthesis routes from compact guidance metadata."""
    if not isinstance(metadata, Mapping):
        return set()

    candidates: List[Any] = [
        metadata.get("compiler_guidance_synthesis_focus"),
        metadata.get("compiler_guidance_ranked_features"),
        metadata.get("compiler_guidance_feature_groups"),
    ]
    candidates.extend(_compiler_guidance_route_features(metadata))
    features = _compiler_guidance_nested_feature_strings(candidates)
    routes: set[str] = set()
    for feature in features:
        normalized = _compiler_guidance_route_name(feature)
        if normalized in _FLOGIC_ONTOLOGY_GUIDANCE_ROUTES:
            routes.add(normalized)
    if (
        not routes
        and _compiler_guidance_has_frame_logic_view_signal(metadata)
    ):
        routes.add("audit_frame_logic_terms")
    return routes


def _compiler_guidance_selected_ontology_terms(
    modal_ir: ModalIRDocument,
) -> List[str]:
    """Promote frame-logic repair guidance into selected ontology grounding."""
    metadata = modal_ir.metadata if isinstance(modal_ir.metadata, Mapping) else {}
    routes = _compiler_guidance_frame_logic_routes(metadata)
    if not routes:
        return []

    values: List[Any] = [
        metadata.get("compiler_guidance_feature_groups"),
        metadata.get("compiler_guidance_ranked_features"),
        metadata.get("compiler_guidance_legal_ir_target_view_distribution"),
        metadata.get("compiler_guidance_legal_ir_view_gap_distribution"),
        metadata.get("compiler_guidance_synthesis_focus"),
        "legal-ir-view:modal.frame_logic",
    ]
    values.extend(f"flogic:statement_hint:{route}" for route in sorted(routes))
    values.extend(_FLOGIC_ONTOLOGY_GUIDANCE_FEATURES)
    feature_keys = frame_ontology_feature_keys_from_values(
        values,
        max_keys=_FRAME_ONTOLOGY_AUDIT_MAX_FEATURE_KEYS,
    )
    terms = frame_ontology_terms_from_feature_keys(
        feature_keys,
        max_terms=_FRAME_ONTOLOGY_AUDIT_MAX_TERMS,
    )
    return _unique_preserve_order(
        term
        for term in (
            _normalize_frame_ontology_audit_term(term)
            for term in terms
        )
        if term
    )


def _compiler_guidance_nested_feature_strings(values: Any) -> List[str]:
    features: List[str] = []
    _collect_compiler_guidance_nested_features(values, features, depth=0)
    return _unique_preserve_order(features)


def _collect_compiler_guidance_nested_features(
    values: Any,
    features: List[str],
    *,
    depth: int,
) -> None:
    if values is None or depth >= _FRAME_ONTOLOGY_METADATA_MAX_DEPTH:
        return
    if isinstance(values, Mapping):
        feature = _guidance_feature_value(values)
        if feature:
            features.append(feature)
        for nested in values.values():
            _collect_compiler_guidance_nested_features(
                nested,
                features,
                depth=depth + 1,
            )
        return
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        for nested in values:
            _collect_compiler_guidance_nested_features(
                nested,
                features,
                depth=depth + 1,
            )
        return
    feature = _guidance_feature_value(values)
    if feature:
        features.append(feature)


def _frame_ontology_audit_terms(
    *,
    frame_feature_keys: Sequence[str],
    kg_triples: Sequence[Mapping[str, str]],
) -> List[str]:
    feature_terms = list(
        frame_ontology_terms_from_feature_keys(
            frame_feature_keys,
            max_terms=_FRAME_ONTOLOGY_AUDIT_MAX_TERMS,
        )
    )
    triple_terms = list(
        frame_ontology_terms_from_triples(
            kg_triples,
            max_terms=_FRAME_ONTOLOGY_AUDIT_MAX_TERMS,
        )
    )
    contextualized_terms = list(
        frame_ontology_contextualized_terms(
            feature_keys=frame_feature_keys,
            triples=kg_triples,
            max_terms=_FRAME_ONTOLOGY_AUDIT_MAX_TERMS,
        )
    )
    return _unique_preserve_order(
        _normalize_frame_ontology_audit_term(term)
        for term in feature_terms + triple_terms + contextualized_terms
    )


def _frame_ontology_audit_triples(
    *,
    document_id: str,
    kg_triples: Sequence[Mapping[str, str]],
    frame_audit_terms: Sequence[str],
    frame_high_signal_audit_terms: Sequence[str],
) -> List[Dict[str, str]]:
    """Project frame-linked audit terms into first-class ontology facts."""
    triples: List[Dict[str, str]] = [
        {
            "subject": str(triple.get("subject", "")).strip(),
            "predicate": str(triple.get("predicate", "")).strip(),
            "object": str(triple.get("object", "")).strip(),
        }
        for triple in kg_triples
        if str(triple.get("subject", "")).strip()
        and str(triple.get("predicate", "")).strip()
        and str(triple.get("object", "")).strip()
    ]
    seen = {
        (
            triple["subject"],
            triple["predicate"],
            triple["object"],
        )
        for triple in triples
    }
    selected_term_candidates = _selected_frame_audit_term_candidates(
        kg_triples=triples,
        frame_high_signal_audit_terms=frame_high_signal_audit_terms,
    )
    selected_term_candidates = list(selected_term_candidates)
    for predicate, terms in (
        ("selected_ontology_term", selected_term_candidates),
        ("audited_ontology_term", frame_audit_terms),
        ("audited_high_signal_ontology_term", frame_high_signal_audit_terms),
    ):
        for term in terms[:_FRAME_ONTOLOGY_AUDIT_MAX_TERMS]:
            normalized = _normalize_frame_ontology_audit_term(str(term))
            if not normalized:
                continue
            triple_key = (document_id, predicate, normalized)
            if triple_key in seen:
                continue
            seen.add(triple_key)
            triples.append(
                {
                    "subject": document_id,
                    "predicate": predicate,
                    "object": normalized,
                }
            )
    if selected_term_candidates:
        selected_frames = {
            _clean_non_empty_string(triple.get("object"))
            for triple in triples
            if _clean_non_empty_string(triple.get("predicate"))
            == "selected_ontology_frame"
        }
        interpreted_subjects = [
            _clean_non_empty_string(triple.get("subject"))
            for triple in triples
            if _clean_non_empty_string(triple.get("predicate"))
            == "interpreted_in_frame"
            and _clean_non_empty_string(triple.get("object")) in selected_frames
            and _clean_non_empty_string(triple.get("subject"))
        ]
        for subject in _unique_preserve_order(interpreted_subjects):
            for term in selected_term_candidates[:_FRAME_ONTOLOGY_AUDIT_MAX_TERMS]:
                normalized = _normalize_frame_ontology_audit_term(str(term))
                if not normalized:
                    continue
                triple_key = (subject, "interpreted_in_frame_term", normalized)
                if triple_key in seen:
                    continue
                seen.add(triple_key)
                triples.append(
                    {
                        "subject": subject,
                        "predicate": "interpreted_in_frame_term",
                        "object": normalized,
                    }
                )
    return triples


def _selected_frame_audit_term_candidates(
    *,
    kg_triples: Sequence[Mapping[str, str]],
    frame_high_signal_audit_terms: Sequence[str],
) -> List[str]:
    """Use audited high-signal terms as selected-frame grounding facts."""
    has_selected_frame = any(
        _clean_non_empty_string(triple.get("predicate")) == "selected_ontology_frame"
        and _clean_non_empty_string(triple.get("object"))
        for triple in kg_triples
    )
    if not has_selected_frame:
        return []
    existing_terms = {
        _clean_non_empty_string(triple.get("object"))
        for triple in kg_triples
        if _clean_non_empty_string(triple.get("predicate")) == "selected_ontology_term"
    }
    return _unique_preserve_order(
        normalized
        for normalized in (
            _normalize_frame_ontology_audit_term(str(term))
            for term in frame_high_signal_audit_terms
        )
        if normalized
        and normalized not in existing_terms
        and is_high_signal_frame_ontology_term(normalized)
    )


def _normalize_frame_ontology_audit_term(term: str) -> str:
    """Collapse legacy positioned bucket terms before ontology-term audits merge."""
    normalized = _clean_non_empty_string(term)
    if re.fullmatch(r"\d+_digits?", normalized):
        return "digit"
    return normalized


def _normalized_flogic_similarity_score(
    result: Optional[FLogicOptimizerResult],
) -> float:
    """Return a bounded frame-logic similarity metric from raw cosine output."""
    if result is None:
        return 0.0
    try:
        raw_score = float(result.similarity_score)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(raw_score):
        return 0.0
    return max(0.0, min(1.0, (raw_score + 1.0) / 2.0))


def _normalize_flogic_result_frame_terms(result: Optional[FLogicOptimizerResult]) -> None:
    """Normalize frame-term metadata emitted by the F-logic optimizer in place."""
    if result is None or not isinstance(result.metadata, dict):
        return
    for key, value in list(result.metadata.items()):
        if "frame_ontology" not in str(key) or "terms" not in str(key):
            continue
        if not isinstance(value, list):
            continue
        normalized_values = sorted(
            _unique_preserve_order(
                _normalize_frame_ontology_audit_term(str(term))
                for term in value
            )
        )
        result.metadata[key] = normalized_values


def _selected_frame_modal_families(modal_ir: ModalIRDocument) -> List[str]:
    families = _unique_preserve_order(
        _slot_safe_family_key(_clean_non_empty_string(formula.operator.family).lower())
        for formula in modal_ir.formulas
    )
    for family, _count in _normalized_modal_family_counts(
        modal_ir.metadata.get("modal_family_counts")
    ):
        if family and family not in families:
            families.append(family)
    return families


def _flogic_result_to_dict(result: Optional[FLogicOptimizerResult]) -> Optional[Dict[str, Any]]:
    if result is None:
        return None
    data = asdict(result)
    data["violations"] = [asdict(violation) for violation in result.violations]
    return data


def _object_to_dict(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


__all__ = [
    "DeterministicModalLogicCodec",
    "ModalLogicCodecConfig",
    "ModalLogicCodecResult",
    "decode_modal_ir_text",
    "modal_formula_to_text",
    "modal_ir_to_flogic_triples",
    "target_family_distribution_for_modal_ir",
    "target_family_for_modal_ir",
]
