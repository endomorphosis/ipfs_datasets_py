"""Reproducible legal sample contract for modal parser training."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .frame_bm25_selector import BM25FrameSelector, DEFAULT_LEGAL_FRAME_FIXTURE
from .legal_modal_parser import LegalModalParser
from .modal_ir import ModalIRDocument


class LegalSampleValidationError(ValueError):
    """Raised when a legal sample is incomplete or corrupt."""


def stable_mock_embedding(text: str, *, dimensions: int = 8) -> List[float]:
    """Create a deterministic mock embedding for tests and fixtures."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    return [round(rng.uniform(-1.0, 1.0), 6) for _ in range(dimensions)]


@dataclass(frozen=True)
class LegalSample:
    """One U.S. Code-style sample with parser and training metadata."""

    sample_id: str
    source: str
    title: str
    section: str
    citation: str
    text: str
    normalized_text: str
    embedding_model: str
    embedding_vector: List[float]
    modal_ir: ModalIRDocument
    frame_candidates: List[Dict[str, Any]] = field(default_factory=list)
    selected_frame: Optional[str] = None
    parser_trace: Dict[str, Any] = field(default_factory=dict)
    losses: Dict[str, float] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate required fields and cross-field invariants."""
        if self.source != "us_code":
            raise LegalSampleValidationError("LegalSample.source must be 'us_code'")
        for field_name in ("sample_id", "title", "section", "citation", "text", "normalized_text"):
            if not getattr(self, field_name):
                raise LegalSampleValidationError(f"LegalSample.{field_name} must not be empty")
        if not self.embedding_vector:
            raise LegalSampleValidationError("LegalSample.embedding_vector must not be empty")
        if not all(isinstance(value, (float, int)) for value in self.embedding_vector):
            raise LegalSampleValidationError("LegalSample.embedding_vector must contain only numbers")
        if self.modal_ir.normalized_text != self.normalized_text:
            raise LegalSampleValidationError("LegalSample.modal_ir.normalized_text must match normalized_text")
        if self.selected_frame and self.selected_frame not in {
            str(candidate.get("frame_id")) for candidate in self.frame_candidates
        }:
            raise LegalSampleValidationError("LegalSample.selected_frame must be one of frame_candidates")

    def to_dict(self) -> Dict[str, Any]:
        """Return stable JSON-ready sample data."""
        return {
            "citation": self.citation,
            "embedding_model": self.embedding_model,
            "embedding_vector": list(self.embedding_vector),
            "frame_candidates": list(self.frame_candidates),
            "losses": dict(sorted(self.losses.items())),
            "modal_ir": self.modal_ir.to_dict(),
            "normalized_text": self.normalized_text,
            "parser_trace": dict(sorted(self.parser_trace.items())),
            "sample_id": self.sample_id,
            "section": self.section,
            "selected_frame": self.selected_frame,
            "source": self.source,
            "text": self.text,
            "title": self.title,
        }

    def to_json(self) -> str:
        """Return stable compact JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def build_us_code_sample(
    *,
    title: str,
    section: str,
    text: str,
    citation: Optional[str] = None,
    embedding_model: str = "mock:stable-sha256",
    embedding_vector: Optional[Sequence[float]] = None,
    parser: Optional[LegalModalParser] = None,
    frame_selector: Optional[BM25FrameSelector] = None,
    top_k_frames: int = 3,
) -> LegalSample:
    """Build a deterministic U.S. Code-style sample."""
    resolved_citation = citation or f"{title} U.S.C. {section}"
    resolved_parser = parser or LegalModalParser()
    normalized_text = resolved_parser.normalize_text(text)
    sample_id = _sample_id(title, section, normalized_text)
    modal_ir = resolved_parser.parse(
        text,
        document_id=sample_id,
        source="us_code",
        citation=resolved_citation,
    )
    selector = frame_selector or BM25FrameSelector(DEFAULT_LEGAL_FRAME_FIXTURE)
    frames = [selection.to_dict() for selection in selector.rank(normalized_text, top_k=top_k_frames)]
    selected_frame = str(frames[0]["frame_id"]) if frames else None
    sample = LegalSample(
        sample_id=sample_id,
        source="us_code",
        title=title,
        section=section,
        citation=resolved_citation,
        text=text,
        normalized_text=normalized_text,
        embedding_model=embedding_model,
        embedding_vector=list(embedding_vector) if embedding_vector is not None else stable_mock_embedding(normalized_text),
        modal_ir=modal_ir,
        frame_candidates=frames,
        selected_frame=selected_frame,
        parser_trace={
            "deterministic_parser": "legal_modal_parser_v1",
            "frame_selector": "bm25_v1",
            "top_k_frames": top_k_frames,
        },
    )
    sample.validate()
    return sample


def _sample_id(title: str, section: str, normalized_text: str) -> str:
    digest = hashlib.sha256(f"{title}:{section}:{normalized_text}".encode("utf-8")).hexdigest()[:16]
    return f"us-code-{title}-{section}-{digest}"


__all__ = [
    "LegalSample",
    "LegalSampleValidationError",
    "build_us_code_sample",
    "stable_mock_embedding",
]
