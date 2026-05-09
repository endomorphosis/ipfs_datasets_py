"""BM25-guided ontology frame selection for legal modal parsing."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Sequence


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")


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
]
