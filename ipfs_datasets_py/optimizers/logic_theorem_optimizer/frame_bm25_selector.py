"""BM25-guided ontology frame selection for legal modal parsing."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Sequence


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")
_ONTOLOGY_TERM_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_FRAME_ONTOLOGY_PREDICATE_TOKEN_RE = re.compile(r"[^a-z0-9]+")
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


def normalize_frame_ontology_term(value: str, *, max_tokens: int = 8) -> str:
    tokens = _informative_ontology_tokens(value)
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
        predicate = _canonical_frame_ontology_predicate(
            str(triple.get("predicate", "")).strip()
        )
        if not predicate:
            continue
        normalized = normalize_frame_ontology_term(
            str(triple.get("object", "")).strip()
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

        raw_value = _raw_frame_ontology_value_from_feature(feature)
        if not raw_value:
            continue

        normalized = normalize_frame_ontology_term(raw_value)
        if not normalized:
            continue
        if normalized in terms:
            continue
        terms.append(normalized)
        if len(terms) >= max_terms:
            break
    return terms


def _informative_ontology_tokens(value: str) -> List[str]:
    tokens = _ONTOLOGY_TERM_TOKEN_RE.findall(str(value or "").lower())
    return [
        token
        for token in tokens
        if _is_informative_ontology_token(token)
    ]


def _is_informative_ontology_token(token: str) -> bool:
    if len(token) < 2:
        return False
    if token in _FRAME_ONTOLOGY_STOPWORDS:
        return False
    if token.isdigit():
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


def _raw_frame_ontology_value_from_feature(feature: str) -> str:
    lowered = feature.lower()
    for prefix in _ORDERED_FRAME_LINKED_FEATURE_PREFIXES:
        if lowered.startswith(prefix):
            return feature[len(prefix) :].strip()

    head, separator, tail = feature.partition(":")
    if not separator:
        return ""
    if _canonical_frame_ontology_predicate(head):
        return tail.strip()

    namespace = head.strip().lower()
    if namespace not in _FRAME_ONTOLOGY_NAMESPACED_FEATURE_PREFIXES:
        return ""
    predicate, separator, value = tail.partition(":")
    if not separator:
        return ""
    if not _canonical_frame_ontology_predicate(predicate):
        return ""
    return value.strip()


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
    "frame_ontology_terms_from_feature_keys",
    "frame_ontology_terms_from_triples",
    "frame_ontology_terms",
    "normalize_frame_ontology_term",
]
