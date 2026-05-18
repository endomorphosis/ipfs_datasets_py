"""BM25-guided ontology frame selection for legal modal parsing."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Sequence


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")
_ONTOLOGY_TERM_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_FRAME_ONTOLOGY_PREDICATE_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_FRAME_ONTOLOGY_POSITIONED_VALUE_RE = re.compile(
    r"^\s*\d+\s*:\s*(?P<value>.+?)\s*$"
)
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
        "predicate_argument",
        "predicate_role",
        "predicate_token",
        "section_heading_tail",
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
    "predicate_argument_",
    "predicate_stem",
    "predicate_token_",
    "section_heading_tail_",
    "source_id_section",
    "source_id_title",
    "statement_hint_",
    "statutory_scope_",
    "status_keyword_",
)
_FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATE_PREFIXES: tuple[str, ...] = (
    "citation",
    "citation_",
    "source_id_",
    "statutory_scope_",
)
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
_FRAME_ONTOLOGY_CUE_FEATURE_PREFIX = "cue:frame:"
_FRAME_ONTOLOGY_CUE_VALUE_ALIASES = {
    "is a": "isa",
}


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
) -> str:
    tokens = _informative_ontology_tokens(
        value,
        keep_numeric_tokens=keep_numeric_tokens,
        keep_single_char_alpha_tokens=keep_single_char_alpha_tokens,
    )
    if not tokens:
        return ""
    return "_".join(tokens[:max_tokens])


def frame_ontology_terms_from_triples(
    triples: Iterable[Mapping[str, object]],
    *,
    max_terms: int = 64,
) -> List[str]:
    """Extract canonical frame ontology terms from frame-linked triples."""
    terms: List[str] = []
    for triple in triples:
        predicate = str(triple.get("predicate", "")).strip()
        if not predicate:
            continue
        canonical_predicate = _canonical_frame_ontology_predicate(predicate)
        contextual = _is_contextual_frame_ontology_predicate(predicate)
        if not (canonical_predicate or contextual):
            continue
        allow_numeric_tokens = _predicate_allows_numeric_ontology_tokens(
            canonical_predicate or predicate
        )
        allow_single_char_alpha_tokens = _predicate_allows_single_character_alpha_tokens(
            canonical_predicate or predicate
        )
        raw_value = _normalized_frame_ontology_value(
            canonical_predicate or predicate,
            str(triple.get("object", "")),
        )
        normalized = normalize_frame_ontology_term(
            raw_value,
            keep_numeric_tokens=allow_numeric_tokens,
            keep_single_char_alpha_tokens=allow_single_char_alpha_tokens,
        )
        if not normalized:
            continue
        if normalized in terms:
            continue
        terms.append(normalized)
        if len(terms) >= max_terms:
            break
    return terms


def frame_ontology_terms_from_feature_keys(
    feature_keys: Iterable[str],
    *,
    max_terms: int = 64,
) -> List[str]:
    """Extract canonical frame ontology terms from frame-linked feature keys."""
    terms: List[str] = []
    for feature_key in feature_keys:
        feature = str(feature_key or "").strip()
        if not feature:
            continue

        (
            raw_value,
            allow_numeric_tokens,
            allow_single_char_alpha_tokens,
        ) = _frame_ontology_value_from_feature(feature)
        if not raw_value:
            continue

        normalized = normalize_frame_ontology_term(
            raw_value,
            keep_numeric_tokens=allow_numeric_tokens,
            keep_single_char_alpha_tokens=allow_single_char_alpha_tokens,
        )
        if not normalized:
            continue
        if normalized in terms:
            continue
        terms.append(normalized)
        if len(terms) >= max_terms:
            break
    return terms


def is_frame_ontology_feature_key(feature_key: str) -> bool:
    """Return ``True`` when a feature key encodes a frame-ontology signal."""
    feature = str(feature_key or "").strip()
    if not feature:
        return False
    value, _, _ = _frame_ontology_value_from_feature(feature)
    return bool(value)


def frame_ontology_feature_keys(
    feature_keys: Iterable[str],
    *,
    max_keys: int = 256,
) -> List[str]:
    """Return unique frame-linked feature keys in stable encounter order."""
    result: List[str] = []
    for feature_key in feature_keys:
        feature = str(feature_key or "").strip()
        if not feature or feature in result:
            continue
        if not is_frame_ontology_feature_key(feature):
            continue
        result.append(feature)
        if len(result) >= max_keys:
            break
    return result


def _informative_ontology_tokens(
    value: str,
    *,
    keep_numeric_tokens: bool = False,
    keep_single_char_alpha_tokens: bool = False,
) -> List[str]:
    tokens = _ONTOLOGY_TERM_TOKEN_RE.findall(str(value or "").lower())
    return [
        token
        for token in tokens
        if _is_informative_ontology_token(
            token,
            keep_numeric_tokens=keep_numeric_tokens,
            keep_single_char_alpha_tokens=keep_single_char_alpha_tokens,
        )
    ]


def _is_informative_ontology_token(
    token: str,
    *,
    keep_numeric_tokens: bool = False,
    keep_single_char_alpha_tokens: bool = False,
) -> bool:
    if token.isdigit():
        return keep_numeric_tokens
    if len(token) < 2:
        return (
            keep_single_char_alpha_tokens
            and len(token) == 1
            and token.isalpha()
        )
    if token in _FRAME_ONTOLOGY_STOPWORDS:
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
    return raw_value


def _raw_frame_ontology_value_from_feature(feature: str) -> str:
    value, _, _ = _frame_ontology_value_from_feature(feature)
    return value


def _frame_ontology_value_from_feature(feature: str) -> tuple[str, bool, bool]:
    lowered = feature.lower()

    for prefix in _FRAME_FAMILY_FEATURE_PREFIXES:
        if lowered == prefix or lowered.startswith(f"{prefix}:"):
            return "frame", False, False

    if lowered.startswith(_FRAME_ONTOLOGY_CUE_FEATURE_PREFIX):
        cue_tail = feature[len(_FRAME_ONTOLOGY_CUE_FEATURE_PREFIX) :].strip()
        if not cue_tail:
            return "", False, False
        cue_symbol, separator, cue_value = cue_tail.partition(":")
        resolved_cue_value = cue_value.strip() if separator else cue_symbol.strip()
        if not resolved_cue_value:
            return "", False, False
        return _normalized_frame_ontology_cue_value(resolved_cue_value), False, False

    for prefix in _ORDERED_FRAME_LINKED_FEATURE_PREFIXES:
        if lowered.startswith(prefix):
            return feature[len(prefix) :].strip(), False, False

    head, separator, tail = feature.partition(":")
    if not separator:
        return "", False, False
    canonical_head_predicate = _canonical_frame_ontology_predicate(head)
    if canonical_head_predicate:
        return (
            _normalized_frame_ontology_value(canonical_head_predicate, tail),
            _predicate_allows_numeric_ontology_tokens(canonical_head_predicate),
            _predicate_allows_single_character_alpha_tokens(canonical_head_predicate),
        )

    namespace = head.strip().lower()
    if namespace not in _FRAME_ONTOLOGY_NAMESPACED_FEATURE_PREFIXES:
        return "", False, False
    predicate, separator, value = tail.partition(":")
    if not separator:
        return "", False, False
    canonical_predicate = _canonical_frame_ontology_predicate(predicate)
    if canonical_predicate:
        return (
            _normalized_frame_ontology_value(canonical_predicate, value),
            _predicate_allows_numeric_ontology_tokens(canonical_predicate),
            _predicate_allows_single_character_alpha_tokens(canonical_predicate),
        )
    if (
        namespace in _FRAME_ONTOLOGY_CONTEXTUAL_NAMESPACED_FEATURE_PREFIXES
        and _is_contextual_frame_ontology_predicate(predicate)
    ):
        return (
            _normalized_frame_ontology_value(predicate, value),
            _predicate_allows_numeric_ontology_tokens(predicate),
            _predicate_allows_single_character_alpha_tokens(predicate),
        )
    return "", False, False


def _predicate_allows_numeric_ontology_tokens(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized or normalized.endswith("_count"):
        return False
    canonical = _FRAME_ONTOLOGY_PREDICATE_ALIASES.get(normalized, normalized)
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
    if not any(
        canonical.startswith(prefix)
        for prefix in _FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATE_PREFIXES
    ):
        return False
    return "_suffix" in canonical


def _normalized_frame_ontology_cue_value(value: str) -> str:
    normalized = " ".join(str(value or "").strip().lower().split())
    if not normalized:
        return ""
    return _FRAME_ONTOLOGY_CUE_VALUE_ALIASES.get(
        normalized,
        str(value or "").strip(),
    )


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
    "frame_ontology_feature_keys",
    "frame_ontology_terms_from_feature_keys",
    "frame_ontology_terms_from_triples",
    "frame_ontology_terms",
    "is_frame_ontology_feature_key",
    "normalize_frame_ontology_term",
]
