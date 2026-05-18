"""BM25-guided ontology frame selection for legal modal parsing."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")
_ONTOLOGY_TERM_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_FRAME_ONTOLOGY_PREDICATE_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_FRAME_ONTOLOGY_POSITIONED_VALUE_RE = re.compile(
    r"^\s*\d+\s*:\s*(?P<value>.+?)\s*$"
)
_FRAME_ONTOLOGY_POSITIONED_VALUE_LEGACY_SLOT_RE = re.compile(
    r"^\s*\d+\s*_\s*(?P<value>.+?)\s*$"
)
_FRAME_ONTOLOGY_SOURCE_ID_RE = re.compile(
    r"^\s*(?P<scheme>us-code)-(?P<title>[^-]+)-(?P<section>.+)-(?P<digest>[0-9a-f]{16})\s*$",
    re.IGNORECASE,
)
_FRAME_ONTOLOGY_SOURCE_ID_NO_DIGEST_RE = re.compile(
    r"^\s*(?P<scheme>us-code)-(?P<title>\d+[A-Za-z]*)-(?P<section>.+?)\s*$",
    re.IGNORECASE,
)
_FRAME_ONTOLOGY_SOURCE_ID_SLOT_NORMALIZED_RE = re.compile(
    r"^\s*(?P<scheme>us[_-]code)[_-](?P<title>[^_-]+)[_-](?P<section>.+)[_-](?P<digest>[0-9a-f]{16})\s*$",
    re.IGNORECASE,
)
_FRAME_ONTOLOGY_SOURCE_ID_SLOT_NORMALIZED_NO_DIGEST_RE = re.compile(
    r"^\s*(?P<scheme>us[_-]code)[_-](?P<title>\d+[A-Za-z]*)[_-](?P<section>.+?)\s*$",
    re.IGNORECASE,
)
_FRAME_ONTOLOGY_USC_CITATION_RE = re.compile(
    r"^\s*(?P<title>\d+[A-Za-z]*)\s+U\.?\s*S\.?\s*C\.?\s*\.?\s*"
    r"(?:§{1,2}\s*|sec\.?\s*|section\s+)?"
    r"(?P<section>[0-9A-Za-z.\-]+(?:\s+(?:to|through|thru)\s+[0-9A-Za-z.\-]+)?)\s*$",
    re.IGNORECASE,
)
_FRAME_ONTOLOGY_SOURCE_ID_SECTION_TRAILING_PUNCT_RE = re.compile(r"[.;:]+$")
_FRAME_ONTOLOGY_USC_TITLE_TOKEN_RE = re.compile(r"^\d+[a-z]*$", re.IGNORECASE)
_FRAME_ONTOLOGY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)
_FRAME_ONTOLOGY_TERM_PREDICATES = frozenset(
    {
        "candidate_ontology_term",
        "selected_ontology_term",
        "interpreted_in_frame_term",
    }
)
_FRAME_ONTOLOGY_FRAME_PREDICATES = frozenset(
    {
        "candidate_ontology_frame",
        "selected_ontology_frame",
        "interpreted_in_frame",
    }
)
_FRAME_ONTOLOGY_AUDIT_PREDICATES = frozenset(
    set(_FRAME_ONTOLOGY_TERM_PREDICATES) | set(_FRAME_ONTOLOGY_FRAME_PREDICATES)
)
_FRAME_ONTOLOGY_CONTEXTUAL_FLOGIC_PREDICATES = frozenset(
    {
        "belongs_to_document",
        "citation",
        "condition",
        "exception",
        "fallback_rule",
        "fallback_surface_text",
        "modal_family",
        "modal_cue",
        "modal_operator",
        "modal_operator_label",
        "modal_system",
        "predicate",
        "predicate_alnum_segment",
        "predicate_alnum_segment_positioned",
        "predicate_argument",
        "predicate_role",
        "predicate_token",
        "procedural_keyword",
        "section_heading_tail",
        "source_id",
        "statement_hint",
        "status_keyword",
    }
)
_FRAME_ONTOLOGY_CONTEXTUAL_FLOGIC_PREDICATE_PREFIXES: tuple[str, ...] = (
    "citation_",
    "condition_",
    "exception_",
    "fallback_rule_",
    "fallback_surface_text_",
    "modal_family_count",
    "predicate_argument_",
    "procedural_keyword_",
    "predicate_stem",
    "predicate_token_",
    "section_heading_tail_",
    "source_id_section",
    "source_id_citation",
    "source_id_title",
    "statement_hint_",
    "statutory_scope_",
    "status_keyword_",
)
_FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATE_PREFIXES: tuple[str, ...] = (
    "belongs_to_document",
    "citation",
    "citation_",
    "source_id",
    "source_id_",
    "statutory_scope_",
)
_FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATES = frozenset(
    {
        "predicate_alnum_segment",
        "predicate_alnum_segment_positioned",
    }
)
_FRAME_ONTOLOGY_NUMERIC_COUNT_PREDICATE_SUFFIXES: tuple[str, ...] = (
    "_trailing_zero_count",
    "_zero_digit_count",
)
_FRAME_ONTOLOGY_SINGLE_CHAR_ALPHA_PREDICATES = frozenset(
    {
        "modal_operator",
        "modal_system",
    }
)
_FRAME_ONTOLOGY_SINGLE_CHAR_ALPHA_VALUE_PREDICATES = frozenset(
    {
        "predicate_alnum_segment",
        "predicate_alnum_segment_positioned",
    }
)
_FRAME_ONTOLOGY_TRAILING_PUNCT_PREDICATES = frozenset(
    {
        "citation_section_trailing_punct",
        "source_id_section_trailing_punct",
    }
)
_FRAME_ONTOLOGY_PUNCTUATION_TOKEN_ALIASES = {
    ".": "period",
    ",": "comma",
    ";": "semicolon",
    ":": "colon",
    "-": "dash",
    "(": "left_paren",
    ")": "right_paren",
    "[": "left_bracket",
    "]": "right_bracket",
    "{": "left_brace",
    "}": "right_brace",
}
_FRAME_ONTOLOGY_RANGE_CONNECTOR_ALIASES = {
    "thru": "through",
    "through": "through",
    "to": "through",
}
_FRAME_ONTOLOGY_PREDICATE_ALIASES = {
    "candidate_frame": "candidate_ontology_frame",
    "candidate_term": "candidate_ontology_term",
    "candidate_frame_term": "candidate_ontology_term",
    "frame": "selected_ontology_frame",
    "frame_term": "candidate_ontology_term",
    "interpreted_frame": "interpreted_in_frame",
    "interpreted_frame_term": "interpreted_in_frame_term",
    "selected_frame": "selected_ontology_frame",
    "selected_term": "selected_ontology_term",
    "selected_frame_term": "selected_ontology_term",
}
_FRAME_FAMILY_FEATURE_PREFIXES: tuple[str, ...] = (
    "family:frame",
    "modal-family:frame",
    "modal_family:frame",
)
_FRAME_SCOPED_FAMILY_FEATURE_PREFIXES: tuple[str, ...] = (
    "family:selected_frame",
    "family:selected-frame",
    "modal-family:selected_frame",
    "modal-family:selected-frame",
    "modal_family:selected_frame",
    "modal_family:selected-frame",
)
_FRAME_LINKED_FEATURE_PREFIXES: tuple[str, ...] = (
    "frame:",
    "selected-frame:",
    "selected_frame:",
    "frame-candidate:",
    "frame_candidate:",
    "candidate-frame:",
    "candidate_frame:",
    "frame-term:",
    "frame_term:",
    "frame-candidate-term:",
    "frame_candidate_term:",
    "candidate-frame-term:",
    "candidate_frame_term:",
    "selected-frame-term:",
    "selected_frame_term:",
    "slot:selected_frame:",
    "slot:selected-frame:",
    "slot:selected-frame-term:",
    "slot:selected_frame_term:",
    "slot:frame-candidate:",
    "slot:frame_candidate:",
    "slot:candidate-frame:",
    "slot:candidate_frame:",
    "slot:frame-term:",
    "slot:frame_term:",
    "slot:frame-candidate-term:",
    "slot:frame_candidate_term:",
    "slot:candidate-frame-term:",
    "slot:candidate_frame_term:",
)
_ORDERED_FRAME_LINKED_FEATURE_PREFIXES: tuple[str, ...] = tuple(
    sorted(_FRAME_LINKED_FEATURE_PREFIXES, key=lambda value: (-len(value), value))
)
_FRAME_ONTOLOGY_NAMESPACED_FEATURE_PREFIXES = frozenset({"flogic", "slot"})
_FRAME_ONTOLOGY_CONTEXTUAL_NAMESPACED_FEATURE_PREFIXES = frozenset(
    {"flogic", "slot"}
)
_FRAME_ONTOLOGY_SLOT_FRAME_SEMANTIC_VALUE_ALIASES = {
    ("operator", "frame"): "frame",
    ("operator", "framed_as"): "frame",
    ("role", "frame"): "frame",
}
_FRAME_ONTOLOGY_CUE_FEATURE_PREFIX = "cue:frame:"
_FRAME_ONTOLOGY_CUE_VALUE_ALIASES = {
    "is a": "isa",
}
_FRAME_ONTOLOGY_SLOT_FRAME_PREDICATE_PREFIXES: tuple[str, ...] = (
    "candidate_frame",
    "frame_candidate",
    "selected_frame",
)
_FRAME_ONTOLOGY_VALUE_KEY_FEATURE_PREFIXES = {
    "candidate_frame": "frame-candidate:",
    "candidate_ontology_frame": "frame-candidate:",
    "candidate_frame_term": "frame-term:",
    "candidate_ontology_term": "frame-term:",
    "frame_id": "frame:",
    "frame_term": "frame-term:",
    "modal_family": "family:selected_frame:",
    "predicted_family": "family:selected_frame:",
    "selected_frame": "frame:",
    "selected_frame_term": "selected-frame-term:",
    "selected_ontology_frame": "frame:",
    "selected_ontology_term": "selected-frame-term:",
    "target_family": "family:selected_frame:",
}
_FRAME_ONTOLOGY_TERM_PRIORITY_NONE = 0
_FRAME_ONTOLOGY_TERM_PRIORITY_CONTEXTUAL_STRUCTURAL = 1
_FRAME_ONTOLOGY_TERM_PRIORITY_CONTEXTUAL = 2
_FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT = 3
_FRAME_ONTOLOGY_AUDIT_LOW_SIGNAL_TERMS = frozenset(
    {
        "equal",
        "even",
        "false",
        "odd",
        "true",
    }
)
_FRAME_ONTOLOGY_AUDIT_MIN_NUMERIC_TERM_LENGTH = 3
_FRAME_ONTOLOGY_STRUCTURAL_CONTEXTUAL_PREDICATE_SUFFIXES: tuple[str, ...] = (
    "_alignment",
    "_bucket",
    "_char_count",
    "_count",
    "_digit_count",
    "_has_delimiter",
    "_has_suffix",
    "_has_trailing_punct",
    "_is_range",
    "_kind",
    "_match",
    "_pair",
    "_parity",
    "_positioned",
    "_presence_match",
    "_profile",
    "_relation",
    "_repeat_kind",
    "_shape",
    "_signature",
    "_span",
    "_token_count",
    "_unique_char_count",
)
_FRAME_ONTOLOGY_FEATURE_VALUE_MAX_DEPTH = 6
_FRAME_ONTOLOGY_FEATURE_VALUE_MAX_VALUES = 2048
_FRAME_ONTOLOGY_FEATURE_VALUE_JSON_MAX_LENGTH = 4096


@dataclass(frozen=True)
class FrameCandidate:
    """Candidate ontology frame for legal interpretation."""

    frame_id: str
    label: str
    description: str = ""
    terms: Sequence[str] = field(default_factory=tuple)
    domain: str = "general"
    metadata: Mapping[str, object] = field(default_factory=dict)

    def document_text(self) -> str:
        """Return lexical text indexed by BM25."""
        return " ".join([self.label, self.description, *self.terms, self.domain])


@dataclass(frozen=True)
class FrameSelection:
    """BM25 selection result with deterministic explanation fields."""

    frame: FrameCandidate
    score: float
    matched_terms: List[str]
    explanation: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "domain": self.frame.domain,
            "explanation": self.explanation,
            "frame_id": self.frame.frame_id,
            "label": self.frame.label,
            "matched_terms": list(self.matched_terms),
            "score": self.score,
        }


class BM25FrameSelector:
    """Deterministic BM25 ranker for ontology frame candidates."""

    def __init__(
        self,
        frames: Iterable[FrameCandidate],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.frames = tuple(frames)
        self.k1 = k1
        self.b = b
        self._documents = [self._tokenize(frame.document_text()) for frame in self.frames]
        self._avgdl = sum(len(document) for document in self._documents) / len(self._documents) if self._documents else 0.0
        self._doc_freq = self._build_doc_freq(self._documents)

    def rank(
        self,
        text: str,
        *,
        top_k: int = 3,
        domain: str | None = None,
    ) -> List[FrameSelection]:
        """Rank frame candidates for text."""
        query_tokens = self._tokenize(text)
        query_terms = sorted(set(query_tokens))
        results: List[FrameSelection] = []
        for frame, document in zip(self.frames, self._documents):
            if domain is not None and frame.domain != domain:
                continue
            matched_terms = sorted(set(query_terms) & set(document))
            score = self._score(query_terms, document)
            if matched_terms:
                score += 0.05 * len(matched_terms)
            results.append(
                FrameSelection(
                    frame=frame,
                    score=round(score, 6),
                    matched_terms=matched_terms,
                    explanation=self._explain(frame, matched_terms, score),
                )
            )
        results.sort(key=lambda result: (-result.score, result.frame.frame_id))
        return results[:max(top_k, 0)]

    def _score(self, query_terms: Sequence[str], document: Sequence[str]) -> float:
        if not query_terms or not document or not self.frames:
            return 0.0
        doc_len = len(document)
        term_counts = {term: document.count(term) for term in set(document)}
        total = 0.0
        for term in query_terms:
            freq = term_counts.get(term, 0)
            if freq == 0:
                continue
            doc_freq = self._doc_freq.get(term, 0)
            idf = math.log(1 + (len(self.frames) - doc_freq + 0.5) / (doc_freq + 0.5))
            denominator = freq + self.k1 * (1 - self.b + self.b * (doc_len / (self._avgdl or 1.0)))
            total += idf * ((freq * (self.k1 + 1)) / denominator)
        return total

    def _explain(self, frame: FrameCandidate, matched_terms: Sequence[str], score: float) -> str:
        if matched_terms:
            return f"Frame {frame.frame_id} matched {', '.join(matched_terms)} with BM25 score {score:.3f}."
        return f"Frame {frame.frame_id} had no lexical query matches; BM25 score {score:.3f}."

    def _tokenize(self, text: str) -> List[str]:
        return [token.lower() for token in _TOKEN_RE.findall(text)]

    def _build_doc_freq(self, documents: Sequence[Sequence[str]]) -> Dict[str, int]:
        frequencies: Dict[str, int] = {}
        for document in documents:
            for term in set(document):
                frequencies[term] = frequencies.get(term, 0) + 1
        return frequencies


def frame_ontology_terms(
    frame: FrameCandidate,
    *,
    matched_terms: Sequence[str] = (),
    max_terms: int = 24,
) -> List[str]:
    """Return deterministic ontology terms for one frame candidate.

    The term list is intentionally stable and explainable: we keep canonical
    phrase forms plus tokenized atoms for frame id/label/domain/terms and the
    lexical matches that affected BM25 scoring.
    """

    raw_values = [
        (frame.frame_id, False),
        *((value, True) for value in matched_terms),
        (frame.label, True),
        (frame.domain, True),
        *((value, True) for value in frame.terms),
    ]
    terms: List[str] = []
    for raw, include_tokens in raw_values:
        text = str(raw or "").strip()
        if not text:
            continue
        canonical = normalize_frame_ontology_term(text)
        if canonical and canonical not in terms:
            terms.append(canonical)
            if len(terms) >= max_terms:
                break
        if include_tokens:
            for token in _informative_ontology_tokens(text):
                if token not in terms:
                    terms.append(token)
                    if len(terms) >= max_terms:
                        break
        if len(terms) >= max_terms:
            break
    return terms


def normalize_frame_ontology_term(
    value: str,
    *,
    max_tokens: int = 8,
    keep_numeric_tokens: bool = False,
    keep_single_char_alpha_tokens: bool = False,
    keep_stopword_tokens: bool = False,
) -> str:
    tokens = _informative_ontology_tokens(
        value,
        keep_numeric_tokens=keep_numeric_tokens,
        keep_single_char_alpha_tokens=keep_single_char_alpha_tokens,
        keep_stopword_tokens=keep_stopword_tokens,
    )
    if not tokens:
        return ""
    return "_".join(tokens[:max_tokens])


def frame_ontology_terms_from_triples(
    triples: Iterable[Mapping[str, object]],
    *,
    max_terms: int = 256,
) -> List[str]:
    """Extract canonical frame ontology terms from frame-linked triples."""
    term_entries: List[tuple[str, int]] = []
    for triple in triples:
        predicate = str(triple.get("predicate", "")).strip()
        if not predicate:
            continue
        canonical_predicate = _canonical_frame_ontology_predicate(predicate)
        contextual = _is_contextual_frame_ontology_predicate(predicate)
        if not (canonical_predicate or contextual):
            continue
        priority = (
            _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT
            if canonical_predicate
            else _contextual_frame_ontology_priority(predicate)
        )
        allow_numeric_tokens = _predicate_allows_numeric_ontology_tokens(
            canonical_predicate or predicate
        )
        allow_single_char_alpha_tokens = _predicate_allows_single_character_alpha_tokens(
            canonical_predicate or predicate
        )
        allow_stopword_tokens = _predicate_allows_stopword_ontology_tokens(
            canonical_predicate or predicate
        )
        raw_value = _normalized_frame_ontology_value(
            canonical_predicate or predicate,
            str(triple.get("object", "")),
        )
        coordinate_value = _frame_ontology_coordinate_value(raw_value)
        if coordinate_value:
            raw_value = coordinate_value
            allow_numeric_tokens = True
        normalized = normalize_frame_ontology_term(
            raw_value,
            keep_numeric_tokens=allow_numeric_tokens,
            keep_single_char_alpha_tokens=allow_single_char_alpha_tokens,
            keep_stopword_tokens=allow_stopword_tokens,
        )
        if not normalized:
            continue
        term_entries.append(
            (normalized, _priority_for_frame_ontology_term(priority, normalized))
        )
    return _bounded_ontology_values(
        term_entries,
        max_items=max_terms,
    )


def frame_ontology_terms_from_feature_keys(
    feature_keys: Iterable[str],
    *,
    max_terms: int = 256,
) -> List[str]:
    """Extract canonical frame ontology terms from frame-linked feature keys."""
    term_entries: List[tuple[str, int]] = []
    for feature_key in feature_keys:
        feature = str(feature_key or "").strip()
        if not feature:
            continue

        (
            raw_value,
            allow_numeric_tokens,
            allow_single_char_alpha_tokens,
            priority,
        ) = _frame_ontology_value_from_feature(feature)
        if not raw_value:
            continue
        allow_stopword_tokens = _feature_allows_stopword_ontology_tokens(feature)

        coordinate_value = _frame_ontology_coordinate_value(raw_value)
        if coordinate_value:
            raw_value = coordinate_value
            allow_numeric_tokens = True
        normalized = normalize_frame_ontology_term(
            raw_value,
            keep_numeric_tokens=allow_numeric_tokens,
            keep_single_char_alpha_tokens=allow_single_char_alpha_tokens,
            keep_stopword_tokens=allow_stopword_tokens,
        )
        if not normalized:
            continue
        term_entries.append(
            (normalized, _priority_for_frame_ontology_term(priority, normalized))
        )
    return _bounded_ontology_values(
        term_entries,
        max_items=max_terms,
    )


def is_frame_ontology_feature_key(feature_key: str) -> bool:
    """Return ``True`` when a feature key encodes a frame-ontology signal."""
    feature = str(feature_key or "").strip()
    if not feature:
        return False
    value, _, _, _ = _frame_ontology_value_from_feature(feature)
    return bool(value)


def frame_ontology_feature_keys(
    feature_keys: Iterable[str],
    *,
    max_keys: int = 1024,
) -> List[str]:
    """Return unique frame-linked feature keys in stable encounter order."""
    key_entries: List[tuple[str, int]] = []
    for feature_key in feature_keys:
        feature = str(feature_key or "").strip()
        if not feature:
            continue
        value, _, _, priority = _frame_ontology_value_from_feature(feature)
        if not value:
            continue
        key_entries.append((feature, priority))
    return _bounded_ontology_values(
        key_entries,
        max_items=max_keys,
    )


def frame_ontology_feature_keys_from_values(
    values: Any,
    *,
    max_keys: int = 1024,
    max_depth: int = _FRAME_ONTOLOGY_FEATURE_VALUE_MAX_DEPTH,
    max_values: int = _FRAME_ONTOLOGY_FEATURE_VALUE_MAX_VALUES,
) -> List[str]:
    """Extract frame-linked feature keys from nested evidence payloads."""
    extracted_values: List[str] = []
    _collect_frame_ontology_feature_value_candidates(
        values,
        extracted_values,
        depth=0,
        max_depth=max_depth,
        max_values=max_values,
    )
    return frame_ontology_feature_keys(
        extracted_values,
        max_keys=max_keys,
    )


def _collect_frame_ontology_feature_value_candidates(
    values: Any,
    extracted: List[str],
    *,
    depth: int,
    max_depth: int,
    max_values: int,
) -> None:
    if (
        values is None
        or depth >= max(max_depth, 1)
        or len(extracted) >= max(max_values, 1)
    ):
        return
    if isinstance(values, Mapping):
        for key, value in values.items():
            if len(extracted) >= max(max_values, 1):
                return
            key_text = str(key or "").strip()
            if key_text and is_frame_ontology_feature_key(key_text):
                extracted.append(key_text)
                if len(extracted) >= max(max_values, 1):
                    return
            for synthetic_feature in _synthetic_frame_feature_candidates_from_key_value(
                key_text,
                value,
            ):
                extracted.append(synthetic_feature)
                if len(extracted) >= max(max_values, 1):
                    return
            _collect_frame_ontology_feature_value_candidates(
                value,
                extracted,
                depth=depth + 1,
                max_depth=max_depth,
                max_values=max_values,
            )
        return
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        for value in values:
            if len(extracted) >= max(max_values, 1):
                return
            _collect_frame_ontology_feature_value_candidates(
                value,
                extracted,
                depth=depth + 1,
                max_depth=max_depth,
                max_values=max_values,
            )
        return
    text = str(values or "").strip()
    if not text:
        return
    parsed = _parsed_frame_ontology_feature_value(text)
    if parsed is not None:
        _collect_frame_ontology_feature_value_candidates(
            parsed,
            extracted,
            depth=depth + 1,
            max_depth=max_depth,
            max_values=max_values,
        )
        return
    extracted.append(text)


def _synthetic_frame_feature_candidates_from_key_value(
    key_text: str,
    value: Any,
) -> List[str]:
    normalized_key = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(key_text or "").strip().lower(),
    ).strip("_")
    if not normalized_key:
        return []
    prefix = _FRAME_ONTOLOGY_VALUE_KEY_FEATURE_PREFIXES.get(normalized_key)
    if not prefix:
        return []
    candidates: List[str] = []
    values: Sequence[Any]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = value
    else:
        values = (value,)
    for item in values:
        if isinstance(item, Mapping):
            continue
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            continue
        text = str(item or "").strip()
        if not text:
            continue
        if is_frame_ontology_feature_key(text):
            candidates.append(text)
            continue
        candidates.append(f"{prefix}{text}")
    return candidates


def _parsed_frame_ontology_feature_value(text: str) -> Any | None:
    stripped = str(text or "").strip()
    if not stripped or len(stripped) > _FRAME_ONTOLOGY_FEATURE_VALUE_JSON_MAX_LENGTH:
        return None
    is_json_object = stripped.startswith("{") and stripped.endswith("}")
    is_json_array = stripped.startswith("[") and stripped.endswith("]")
    if not (is_json_object or is_json_array):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, Mapping):
        return parsed
    if isinstance(parsed, Sequence) and not isinstance(parsed, (str, bytes)):
        return parsed
    return None


def is_high_signal_frame_ontology_term(
    term: str,
    *,
    min_numeric_length: int = _FRAME_ONTOLOGY_AUDIT_MIN_NUMERIC_TERM_LENGTH,
) -> bool:
    """Return ``True`` when ``term`` is informative enough for ontology audits."""
    normalized = str(term or "").strip().lower()
    if not normalized:
        return False
    if normalized in _FRAME_ONTOLOGY_AUDIT_LOW_SIGNAL_TERMS:
        return False
    if normalized in _FRAME_ONTOLOGY_STOPWORDS:
        return False
    if normalized.isdigit() and len(normalized) < max(min_numeric_length, 1):
        return False
    return True


def frame_ontology_high_signal_terms(
    terms: Iterable[str],
    *,
    max_terms: int = 256,
    min_numeric_length: int = _FRAME_ONTOLOGY_AUDIT_MIN_NUMERIC_TERM_LENGTH,
) -> List[str]:
    """Return deterministic high-signal ontology terms for audit summaries."""
    term_entries: List[tuple[str, int]] = []
    for term in terms:
        normalized = str(term or "").strip()
        if not normalized:
            continue
        if not is_high_signal_frame_ontology_term(
            normalized,
            min_numeric_length=min_numeric_length,
        ):
            continue
        term_entries.append((normalized, _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT))
    return _bounded_ontology_values(
        term_entries,
        max_items=max_terms,
    )


def frame_ontology_contextualized_terms(
    *,
    feature_keys: Iterable[str] = (),
    triples: Iterable[Mapping[str, object]] = (),
    max_terms: int = 256,
    include_positioned_terms: bool = True,
) -> List[str]:
    """Return contextualized frame terms for low-signal and positioned values."""
    term_entries: List[tuple[str, int]] = []
    for feature_key in feature_keys:
        contextualized = _contextualized_frame_ontology_term_from_feature(
            feature_key,
            include_positioned_terms=include_positioned_terms,
        )
        if not contextualized:
            continue
        term_entries.append((contextualized, _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT))
    for triple in triples:
        predicate = str(triple.get("predicate", "")).strip()
        obj = str(triple.get("object", "")).strip()
        if not predicate or not obj:
            continue
        contextualized = _contextualized_frame_ontology_term_from_feature(
            f"flogic:{predicate}:{obj}",
            include_positioned_terms=include_positioned_terms,
        )
        if not contextualized:
            continue
        term_entries.append((contextualized, _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT))
    return _bounded_ontology_values(
        term_entries,
        max_items=max_terms,
    )


def _bounded_ontology_values(
    entries: Iterable[tuple[str, int]],
    *,
    max_items: int,
) -> List[str]:
    """Return deterministic bounded values with overflow priority handling."""
    if max_items <= 0:
        return []
    deduplicated = _deduplicated_ontology_entries(entries)
    if len(deduplicated) <= max_items:
        return [value for value, _priority in deduplicated]

    selected: List[str] = []
    seen: set[str] = set()
    for priority in (
        _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
        _FRAME_ONTOLOGY_TERM_PRIORITY_CONTEXTUAL,
        _FRAME_ONTOLOGY_TERM_PRIORITY_CONTEXTUAL_STRUCTURAL,
        _FRAME_ONTOLOGY_TERM_PRIORITY_NONE,
    ):
        for value, entry_priority in deduplicated:
            if entry_priority != priority or value in seen:
                continue
            selected.append(value)
            seen.add(value)
            if len(selected) >= max_items:
                return selected
    return selected


def _deduplicated_ontology_entries(
    entries: Iterable[tuple[str, int]]
) -> List[tuple[str, int]]:
    result: List[tuple[str, int]] = []
    index_by_value: Dict[str, int] = {}
    for value, priority in entries:
        normalized_value = str(value or "").strip()
        if not normalized_value:
            continue
        resolved_priority = int(priority)
        existing_index = index_by_value.get(normalized_value)
        if existing_index is None:
            index_by_value[normalized_value] = len(result)
            result.append((normalized_value, resolved_priority))
            continue
        existing_priority = result[existing_index][1]
        if resolved_priority > existing_priority:
            result[existing_index] = (normalized_value, resolved_priority)
    return result


def _informative_ontology_tokens(
    value: str,
    *,
    keep_numeric_tokens: bool = False,
    keep_single_char_alpha_tokens: bool = False,
    keep_stopword_tokens: bool = False,
) -> List[str]:
    tokens = _ONTOLOGY_TERM_TOKEN_RE.findall(str(value or "").lower())
    return [
        token
        for token in tokens
        if _is_informative_ontology_token(
            token,
            keep_numeric_tokens=keep_numeric_tokens,
            keep_single_char_alpha_tokens=keep_single_char_alpha_tokens,
            keep_stopword_tokens=keep_stopword_tokens,
        )
    ]


def _is_informative_ontology_token(
    token: str,
    *,
    keep_numeric_tokens: bool = False,
    keep_single_char_alpha_tokens: bool = False,
    keep_stopword_tokens: bool = False,
) -> bool:
    if token.isdigit():
        return keep_numeric_tokens
    if len(token) < 2:
        return (
            keep_single_char_alpha_tokens
            and len(token) == 1
            and token.isalpha()
        )
    if token in _FRAME_ONTOLOGY_STOPWORDS and not keep_stopword_tokens:
        return False
    return any(character.isalpha() for character in token)


def _canonical_frame_ontology_predicate(predicate: str) -> str:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized:
        return ""
    canonical = _FRAME_ONTOLOGY_PREDICATE_ALIASES.get(normalized, normalized)
    if canonical in _FRAME_ONTOLOGY_AUDIT_PREDICATES:
        return canonical
    return ""


def _is_contextual_frame_ontology_predicate(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    return (
        normalized in _FRAME_ONTOLOGY_CONTEXTUAL_FLOGIC_PREDICATES
        or any(
            normalized.startswith(prefix)
            for prefix in _FRAME_ONTOLOGY_CONTEXTUAL_FLOGIC_PREDICATE_PREFIXES
        )
    )


def _normalized_frame_ontology_value(predicate: str, value: str) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    normalized_predicate = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if normalized_predicate in {"source_id", "belongs_to_document"}:
        normalized_source_id = _normalized_source_id_ontology_value(raw_value)
        if normalized_source_id:
            return normalized_source_id
        return ""
    if normalized_predicate in _FRAME_ONTOLOGY_TRAILING_PUNCT_PREDICATES:
        normalized_trailing_punct = _normalized_trailing_punct_ontology_value(raw_value)
        if normalized_trailing_punct:
            return normalized_trailing_punct
    if normalized_predicate.startswith("modal_family_count"):
        return _normalized_modal_family_count_value(
            normalized_predicate=normalized_predicate,
            raw_value=raw_value,
        )
    if normalized_predicate.endswith("_range_connector"):
        normalized_range_connector = _normalized_range_connector_ontology_value(raw_value)
        if normalized_range_connector:
            return normalized_range_connector
    if normalized_predicate.endswith("_pair"):
        normalized_pair_value = _normalized_pair_ontology_value(raw_value)
        if normalized_pair_value:
            raw_value = normalized_pair_value
    if normalized_predicate == "statutory_scope_target":
        scoped_target = raw_value.split("(", 1)[0].strip()
        if scoped_target:
            raw_value = scoped_target
    if normalized_predicate.endswith("_positioned"):
        match = _FRAME_ONTOLOGY_POSITIONED_VALUE_RE.match(raw_value)
        if match:
            positioned_value = str(match.group("value") or "").strip()
            if positioned_value:
                return positioned_value
        legacy_slot_match = _FRAME_ONTOLOGY_POSITIONED_VALUE_LEGACY_SLOT_RE.match(
            raw_value
        )
        if legacy_slot_match:
            positioned_value = str(
                legacy_slot_match.group("value") or ""
            ).strip()
            if positioned_value:
                return positioned_value
    return raw_value


def _normalized_source_id_ontology_value(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    match = _FRAME_ONTOLOGY_SOURCE_ID_RE.match(text)
    if match is None:
        # Slot-value feature keys normalize punctuation to underscores, so
        # source IDs often arrive as `us_code_<title>_<section>_<digest>`.
        # Accept that canonicalized shape to keep source coordinates in audits.
        match = _FRAME_ONTOLOGY_SOURCE_ID_SLOT_NORMALIZED_RE.match(text)
    if match is None:
        match = _FRAME_ONTOLOGY_SOURCE_ID_NO_DIGEST_RE.match(text)
    if match is None:
        match = _FRAME_ONTOLOGY_SOURCE_ID_SLOT_NORMALIZED_NO_DIGEST_RE.match(text)
    if not match:
        return ""
    title = str(match.group("title") or "").strip()
    section = str(match.group("section") or "").strip()
    if not title or not section:
        return ""
    normalized_section = _FRAME_ONTOLOGY_SOURCE_ID_SECTION_TRAILING_PUNCT_RE.sub(
        "",
        section,
    ).strip()
    if normalized_section:
        section = normalized_section
    return f"{title} {section}"


def _normalized_usc_citation_ontology_value(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    match = _FRAME_ONTOLOGY_USC_CITATION_RE.match(text)
    if not match:
        return ""
    title = str(match.group("title") or "").strip()
    section = str(match.group("section") or "").strip()
    if not title or not section:
        return ""
    normalized_section = _FRAME_ONTOLOGY_SOURCE_ID_SECTION_TRAILING_PUNCT_RE.sub(
        "",
        section,
    ).strip()
    if normalized_section:
        section = normalized_section
    return f"{title} {section}"


def _frame_ontology_coordinate_value(raw_value: str) -> str:
    source_coordinate = _normalized_source_id_ontology_value(raw_value)
    if source_coordinate:
        return source_coordinate
    return _normalized_usc_citation_ontology_value(raw_value)


def _normalized_trailing_punct_ontology_value(raw_value: str) -> str:
    compact = "".join(str(raw_value or "").strip().split())
    if not compact:
        return ""
    tokens: List[str] = []
    for character in compact:
        mapped = _FRAME_ONTOLOGY_PUNCTUATION_TOKEN_ALIASES.get(character)
        if not mapped:
            continue
        if tokens and tokens[-1] == mapped:
            continue
        tokens.append(mapped)
    if tokens:
        return "_".join(tokens)
    return compact


def _normalized_range_connector_ontology_value(raw_value: str) -> str:
    normalized = " ".join(str(raw_value or "").strip().lower().split())
    if not normalized:
        return ""
    return _FRAME_ONTOLOGY_RANGE_CONNECTOR_ALIASES.get(normalized, normalized)


def _normalized_pair_ontology_value(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    normalized_truncated_usc_pair = _normalized_truncated_usc_pair_value(text)
    if normalized_truncated_usc_pair:
        return normalized_truncated_usc_pair
    if "|" in text:
        left, separator, right = text.partition("|")
        if separator:
            normalized_left = left.strip()
            normalized_right = right.strip()
            if (
                normalized_left
                and normalized_right
                and normalized_left.lower() == normalized_right.lower()
            ):
                return normalized_left
    tokenized = [token for token in text.split("_") if token]
    token_count = len(tokenized)
    if token_count >= 2 and token_count % 2 == 0:
        half = token_count // 2
        left_tokens = tokenized[:half]
        right_tokens = tokenized[half:]
        if left_tokens == right_tokens:
            collapsed = "_".join(left_tokens).strip("_")
            if collapsed:
                return collapsed
    return text


def _normalized_truncated_usc_pair_value(raw_value: str) -> str:
    """Recover the canonical first citation from truncated slot-encoded pairs."""
    tokens = [
        token.strip().lower()
        for token in str(raw_value or "").strip().split("_")
        if token.strip()
    ]
    if len(tokens) < 5:
        return ""
    title = tokens[0]
    if (
        _FRAME_ONTOLOGY_USC_TITLE_TOKEN_RE.fullmatch(title) is None
        or tokens[1:4] != ["u", "s", "c"]
    ):
        return ""
    for index in range(4, len(tokens)):
        if tokens[index] != title:
            continue
        if index + 1 >= len(tokens) or tokens[index + 1] != "u":
            continue
        # Slot feature values are token-capped and can truncate the second
        # citation in `*_canonical_pair` values. Keep the first full citation.
        collapsed_tokens = tokens[:index]
        if len(collapsed_tokens) >= 5:
            return "_".join(collapsed_tokens)
    return ""


def _normalized_modal_family_count_value(
    *,
    normalized_predicate: str,
    raw_value: str,
) -> str:
    if normalized_predicate == "modal_family_count_value":
        return ""
    if normalized_predicate == "modal_family_count_family":
        return raw_value
    if normalized_predicate == "modal_family_count":
        family, separator, _count = raw_value.partition(":")
        if separator:
            return family.strip()
        return raw_value
    if normalized_predicate == "modal_family_count_ranked":
        _rank, separator, remainder = raw_value.partition(":")
        if not separator:
            return raw_value
        family, separator, _count = remainder.partition(":")
        if separator:
            return family.strip()
        return family.strip() or raw_value
    if normalized_predicate.startswith("modal_family_count_"):
        family = normalized_predicate[len("modal_family_count_") :].strip("_")
        if family and family not in {"family", "ranked", "value"}:
            return family
    return raw_value


def _raw_frame_ontology_value_from_feature(feature: str) -> str:
    value, _, _, _ = _frame_ontology_value_from_feature(feature)
    return value


def frame_ontology_feature_value(feature_key: str) -> str:
    """Return normalized raw ontology value from one feature key, if present."""
    return _raw_frame_ontology_value_from_feature(str(feature_key or ""))


def _frame_ontology_value_from_feature(
    feature: str,
) -> tuple[str, bool, bool, int]:
    lowered = feature.lower()

    for prefix in _FRAME_FAMILY_FEATURE_PREFIXES:
        if lowered == prefix or lowered.startswith(f"{prefix}:"):
            return "frame", False, False, _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT
    for prefix in _FRAME_SCOPED_FAMILY_FEATURE_PREFIXES:
        if lowered.startswith(f"{prefix}:"):
            return (
                feature[len(prefix) + 1 :].strip(),
                False,
                False,
                _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
            )

    if lowered.startswith(_FRAME_ONTOLOGY_CUE_FEATURE_PREFIX):
        cue_tail = feature[len(_FRAME_ONTOLOGY_CUE_FEATURE_PREFIX) :].strip()
        if not cue_tail:
            return "", False, False, _FRAME_ONTOLOGY_TERM_PRIORITY_NONE
        cue_symbol, separator, cue_value = cue_tail.partition(":")
        resolved_cue_value = cue_value.strip() if separator else cue_symbol.strip()
        if not resolved_cue_value:
            return "", False, False, _FRAME_ONTOLOGY_TERM_PRIORITY_NONE
        return (
            _normalized_frame_ontology_cue_value(resolved_cue_value),
            False,
            False,
            _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
        )

    for prefix in _ORDERED_FRAME_LINKED_FEATURE_PREFIXES:
        if lowered.startswith(prefix):
            return (
                feature[len(prefix) :].strip(),
                False,
                False,
                _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
            )

    # Autoencoder/hint pipelines may surface frame-linked source coordinates
    # as raw values (without `flogic:`/`slot:` prefixes). Keep those values in
    # the deterministic frame-term audit path.
    raw_source_coordinate = _normalized_source_id_ontology_value(feature)
    if raw_source_coordinate:
        return (
            raw_source_coordinate,
            True,
            False,
            _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
        )
    raw_citation_coordinate = _normalized_usc_citation_ontology_value(feature)
    if raw_citation_coordinate:
        return (
            raw_citation_coordinate,
            True,
            False,
            _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
        )

    head, separator, tail = feature.partition(":")
    if not separator:
        return "", False, False, _FRAME_ONTOLOGY_TERM_PRIORITY_NONE
    canonical_head_predicate = _canonical_frame_ontology_predicate(head)
    if canonical_head_predicate:
        return (
            _normalized_frame_ontology_value(canonical_head_predicate, tail),
            _predicate_allows_numeric_ontology_tokens(canonical_head_predicate),
            _predicate_allows_single_character_alpha_tokens(canonical_head_predicate),
            _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
        )
    if _is_contextual_frame_ontology_predicate(head):
        return (
            _normalized_frame_ontology_value(head, tail),
            _predicate_allows_numeric_ontology_tokens(head),
            _predicate_allows_single_character_alpha_tokens(head),
            _contextual_frame_ontology_priority(head),
        )

    namespace = head.strip().lower()
    if namespace not in _FRAME_ONTOLOGY_NAMESPACED_FEATURE_PREFIXES:
        return "", False, False, _FRAME_ONTOLOGY_TERM_PRIORITY_NONE
    predicate, separator, value = tail.partition(":")
    if not separator:
        return "", False, False, _FRAME_ONTOLOGY_TERM_PRIORITY_NONE
    if namespace == "slot":
        frame_semantic_value = _normalized_frame_semantic_slot_value(
            predicate,
            value,
        )
        if frame_semantic_value:
            return (
                frame_semantic_value,
                False,
                False,
                _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
            )
    canonical_predicate = _canonical_frame_ontology_predicate(predicate)
    if canonical_predicate:
        return (
            _normalized_frame_ontology_value(canonical_predicate, value),
            _predicate_allows_numeric_ontology_tokens(canonical_predicate),
            _predicate_allows_single_character_alpha_tokens(canonical_predicate),
            _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
        )
    if (
        namespace in _FRAME_ONTOLOGY_CONTEXTUAL_NAMESPACED_FEATURE_PREFIXES
        and _is_contextual_frame_ontology_predicate(predicate)
    ):
        return (
            _normalized_frame_ontology_value(predicate, value),
            _predicate_allows_numeric_ontology_tokens(predicate),
            _predicate_allows_single_character_alpha_tokens(predicate),
            _contextual_frame_ontology_priority(predicate),
        )
    if namespace == "slot" and _is_slot_frame_ontology_predicate(predicate):
        return (
            _normalized_frame_ontology_value(predicate, value),
            False,
            False,
            _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT,
        )
    return "", False, False, _FRAME_ONTOLOGY_TERM_PRIORITY_NONE


def _normalized_frame_semantic_slot_value(predicate: str, value: str) -> str:
    normalized_predicate = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized_predicate:
        return ""
    normalized_value = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(value or "").strip().lower(),
    ).strip("_")
    if not normalized_value:
        return ""
    return _FRAME_ONTOLOGY_SLOT_FRAME_SEMANTIC_VALUE_ALIASES.get(
        (normalized_predicate, normalized_value),
        "",
    )


def _is_slot_frame_ontology_predicate(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized:
        return False
    return any(
        normalized.startswith(prefix)
        for prefix in _FRAME_ONTOLOGY_SLOT_FRAME_PREDICATE_PREFIXES
    )


def _predicate_allows_numeric_ontology_tokens(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized:
        return False
    canonical = _FRAME_ONTOLOGY_PREDICATE_ALIASES.get(normalized, normalized)
    if canonical.endswith("_count"):
        return any(
            canonical.endswith(suffix)
            for suffix in _FRAME_ONTOLOGY_NUMERIC_COUNT_PREDICATE_SUFFIXES
        )
    if canonical in _FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATES:
        return True
    return any(
        canonical.startswith(prefix)
        for prefix in _FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATE_PREFIXES
    )


def _predicate_allows_single_character_alpha_tokens(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized or normalized.endswith("_count"):
        return False
    canonical = _FRAME_ONTOLOGY_PREDICATE_ALIASES.get(normalized, normalized)
    if canonical in _FRAME_ONTOLOGY_SINGLE_CHAR_ALPHA_VALUE_PREDICATES:
        return True
    if canonical in _FRAME_ONTOLOGY_SINGLE_CHAR_ALPHA_PREDICATES:
        return True
    if not any(
        canonical.startswith(prefix)
        for prefix in _FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATE_PREFIXES
    ):
        return False
    return "_suffix" in canonical


def _predicate_allows_stopword_ontology_tokens(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized:
        return False
    canonical = _FRAME_ONTOLOGY_PREDICATE_ALIASES.get(normalized, normalized)
    return (
        canonical.startswith("condition_alnum_segment")
        or canonical.startswith("condition_scope_alnum_segment")
        or canonical.startswith("exception_alnum_segment")
        or canonical.startswith("exception_scope_alnum_segment")
    )


def _feature_allows_stopword_ontology_tokens(feature: str) -> bool:
    head, separator, tail = str(feature or "").partition(":")
    if not separator:
        return False
    canonical_head_predicate = _canonical_frame_ontology_predicate(head)
    if canonical_head_predicate:
        return _predicate_allows_stopword_ontology_tokens(canonical_head_predicate)
    if _is_contextual_frame_ontology_predicate(head):
        return _predicate_allows_stopword_ontology_tokens(head)
    namespace = head.strip().lower()
    if namespace not in _FRAME_ONTOLOGY_NAMESPACED_FEATURE_PREFIXES:
        return False
    predicate, separator, _value = tail.partition(":")
    if not separator:
        return False
    canonical_predicate = _canonical_frame_ontology_predicate(predicate)
    if canonical_predicate:
        return _predicate_allows_stopword_ontology_tokens(canonical_predicate)
    if _is_contextual_frame_ontology_predicate(predicate):
        return _predicate_allows_stopword_ontology_tokens(predicate)
    return False


def _normalized_frame_ontology_cue_value(value: str) -> str:
    normalized = " ".join(str(value or "").strip().lower().split())
    if not normalized:
        return ""
    return _FRAME_ONTOLOGY_CUE_VALUE_ALIASES.get(
        normalized,
        str(value or "").strip(),
    )


def _contextual_frame_ontology_priority(predicate: str) -> int:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized:
        return _FRAME_ONTOLOGY_TERM_PRIORITY_CONTEXTUAL
    if any(
        normalized.endswith(suffix)
        for suffix in _FRAME_ONTOLOGY_STRUCTURAL_CONTEXTUAL_PREDICATE_SUFFIXES
    ):
        return _FRAME_ONTOLOGY_TERM_PRIORITY_CONTEXTUAL_STRUCTURAL
    return _FRAME_ONTOLOGY_TERM_PRIORITY_CONTEXTUAL


def _priority_for_frame_ontology_term(priority: int, term: str) -> int:
    if priority >= _FRAME_ONTOLOGY_TERM_PRIORITY_DIRECT:
        return int(priority)
    normalized = str(term or "").strip().lower()
    if normalized in _FRAME_ONTOLOGY_AUDIT_LOW_SIGNAL_TERMS:
        return min(
            int(priority),
            _FRAME_ONTOLOGY_TERM_PRIORITY_CONTEXTUAL_STRUCTURAL,
        )
    return int(priority)


def _contextualized_frame_ontology_term_from_feature(
    feature_key: str,
    *,
    include_positioned_terms: bool,
) -> str:
    feature = str(feature_key or "").strip()
    if not feature:
        return ""
    raw_value = _raw_frame_ontology_value_from_feature(feature)
    if not raw_value:
        return ""
    predicate = _frame_ontology_contextual_predicate_from_feature(feature)
    if not predicate:
        return ""
    normalized_value = normalize_frame_ontology_term(
        raw_value,
        keep_numeric_tokens=True,
        keep_single_char_alpha_tokens=True,
        keep_stopword_tokens=True,
    )
    if not normalized_value:
        return ""
    if not _should_contextualize_frame_ontology_value(
        predicate=predicate,
        normalized_value=normalized_value,
        include_positioned_terms=include_positioned_terms,
    ):
        return ""
    return normalize_frame_ontology_term(
        f"{predicate}_{normalized_value}",
        max_tokens=24,
        keep_numeric_tokens=True,
        keep_single_char_alpha_tokens=True,
        keep_stopword_tokens=True,
    )


def _frame_ontology_contextual_predicate_from_feature(feature_key: str) -> str:
    head, separator, tail = str(feature_key or "").partition(":")
    if not separator:
        return ""
    if _is_contextual_frame_ontology_predicate(head):
        return _normalized_frame_ontology_predicate(head)
    namespace = head.strip().lower()
    if namespace not in _FRAME_ONTOLOGY_NAMESPACED_FEATURE_PREFIXES:
        return ""
    raw_predicate, separator, _value = tail.partition(":")
    if not separator or not _is_contextual_frame_ontology_predicate(raw_predicate):
        return ""
    return _normalized_frame_ontology_predicate(raw_predicate)


def _normalized_frame_ontology_predicate(value: str) -> str:
    return _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(value or "").strip().lower(),
    ).strip("_")


def _should_contextualize_frame_ontology_value(
    *,
    predicate: str,
    normalized_value: str,
    include_positioned_terms: bool,
) -> bool:
    if _is_frame_ontology_contextual_low_signal_value(normalized_value):
        return True
    if include_positioned_terms and predicate.endswith("_positioned"):
        return True
    return False


def _is_frame_ontology_contextual_low_signal_value(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    if normalized in _FRAME_ONTOLOGY_AUDIT_LOW_SIGNAL_TERMS:
        return True
    if normalized.isdigit():
        return len(normalized) <= 2
    return len(normalized) == 1 and normalized.isalpha()


DEFAULT_LEGAL_FRAME_FIXTURE: tuple[FrameCandidate, ...] = (
    FrameCandidate(
        frame_id="housing_voucher_benefits",
        label="Housing voucher benefits",
        description="Public housing agency benefit administration, voucher eligibility, accommodation, rent subsidy.",
        terms=("housing", "voucher", "benefit", "agency", "tenant", "rent", "accommodation"),
        domain="housing",
    ),
    FrameCandidate(
        frame_id="criminal_penalty_enforcement",
        label="Criminal penalty enforcement",
        description="Offense, penalty, sentence, prosecution, enforcement, mens rea, intent.",
        terms=("criminal", "penalty", "offense", "prosecution", "sentence", "intent"),
        domain="criminal",
    ),
    FrameCandidate(
        frame_id="administrative_notice_hearing",
        label="Administrative notice and hearing",
        description="Agency notice, finding, hearing rights, final order, appeal deadlines.",
        terms=("agency", "notice", "hearing", "finding", "order", "appeal", "deadline"),
        domain="administrative",
    ),
)


__all__ = [
    "BM25FrameSelector",
    "DEFAULT_LEGAL_FRAME_FIXTURE",
    "FrameCandidate",
    "FrameSelection",
    "frame_ontology_feature_value",
    "frame_ontology_feature_keys",
    "frame_ontology_feature_keys_from_values",
    "frame_ontology_high_signal_terms",
    "frame_ontology_contextualized_terms",
    "frame_ontology_terms_from_feature_keys",
    "frame_ontology_terms_from_triples",
    "frame_ontology_terms",
    "is_high_signal_frame_ontology_term",
    "is_frame_ontology_feature_key",
    "normalize_frame_ontology_term",
]
