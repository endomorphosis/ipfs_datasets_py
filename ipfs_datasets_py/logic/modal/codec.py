"""Deterministic modal logic codec with BM25 frame-logic grounding.

This module is the canonical logic-layer facade for the legal modal
encoder/IR/decoder path.  It intentionally keeps LLM usage at zero: modal
operators come from the deterministic registry, ontology frames are selected
with BM25, decoded vectors come from stable spaCy-derived feature hashing, and
F-logic is used as a consistency check over the intermediate representation.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ipfs_datasets_py.optimizers.logic.flogic_optimizer import (
    FLogicOptimizerConfig,
    FLogicOptimizerResult,
    FLogicSemanticOptimizer,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    BM25FrameSelector,
    DEFAULT_LEGAL_FRAME_FIXTURE,
    FrameSelection,
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
    cross_entropy_distribution_loss,
    mse_loss,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrame,
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
from .decompiler import DecodedModalText, decode_modal_ir_document


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
            "flogic_result": _flogic_result_to_dict(self.flogic_result),
            "frame_candidates": list(self.frame_candidates),
            "kg_triples": list(self.kg_triples),
            "losses": dict(sorted(self.losses.items())),
            "metadata": dict(sorted(self.metadata.items())),
            "modal_ir": self.modal_ir.to_dict(),
            "normalized_text": self.normalized_text,
            "parser_name": self.parser_name,
            "selected_frame": self.selected_frame,
            "source_embedding": list(self.source_embedding),
            "source_text": self.source_text,
            "target_family": self.target_family,
            "target_family_distribution": dict(sorted(self.target_family_distribution.items())),
        }


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
    ) -> ModalLogicCodecResult:
        """Run deterministic text -> encoding -> modal IR -> vector decoding."""
        normalized_text = self.parser.normalize_text(text)
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
        frame_selections = self.frame_selector.rank(
            normalized_text,
            top_k=self.config.top_k_frames,
            domain=self.config.frame_domain,
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

        resolved_source_embedding = list(source_embedding) if source_embedding is not None else stable_mock_embedding(
            normalized_text,
            dimensions=self.config.embedding_dimensions,
        )
        decoded_embedding = self.decoder.decode_embedding(
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
        decoded_modal_text = decode_modal_ir_document(modal_ir)
        decoded_text = decoded_modal_text.text
        kg_triples = modal_ir_to_flogic_triples(modal_ir, selected_frame=selected_frame)
        flogic_result = self._evaluate_flogic(
            normalized_text,
            decoded_text,
            resolved_source_embedding,
            decoded_embedding,
            kg_triples,
        )
        losses = {
            "cosine_loss": cosine_loss(resolved_source_embedding, decoded_embedding),
            "cosine_similarity": cosine_similarity(resolved_source_embedding, decoded_embedding),
            "cross_entropy_loss": cross_entropy_distribution_loss(
                family_probabilities,
                target_family_distribution,
            ),
            "flogic_similarity_loss": 1.0 - (flogic_result.similarity_score if flogic_result else 0.0),
            "flogic_similarity_score": flogic_result.similarity_score if flogic_result else 0.0,
            "frame_ranking_loss": 0.0 if selected_frame else 1.0,
            "modal_span_coverage_loss": 1.0 - decoded_modal_text.modal_span_coverage,
            "ontology_violation_count": float(len(flogic_result.violations)) if flogic_result else 0.0,
            "reconstruction_loss": mse_loss(resolved_source_embedding, decoded_embedding),
            "symbolic_validity_penalty": 0.0 if modal_ir.formulas else 1.0,
            "text_reconstruction_loss": 1.0 - decoded_modal_text.reconstruction_similarity,
        }
        metadata = {
            "deterministic_coverage_ratio": 1.0,
            "deterministic_decompiler": "modal_decompiler_v2",
            "encoder": "spacy_legal_encoder_v1",
            "flogic_ontology_consistent": bool(flogic_result.ontology_consistent) if flogic_result else True,
            "frame_selector": "bm25_v1",
            "llm_call_count": 0,
            "modal_decompiler_reconstruction_similarity": decoded_modal_text.reconstruction_similarity,
            "modal_decompiler_span_coverage": decoded_modal_text.modal_span_coverage,
            "modal_families": sorted({formula.operator.family for formula in modal_ir.formulas}),
            "modal_systems": sorted({formula.operator.system for formula in modal_ir.formulas}),
            "parser_backend": self.config.parser_backend,
            "spacy_model_name": encoding.model_name,
            "spacy_token_count": len(encoding.tokens),
            "spacy_used_fallback_model": encoding.used_fallback_model,
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

    def compile_sample_ir(self, sample: LegalSample) -> ModalIRDocument:
        """Compile a ``LegalSample`` through the canonical modal/F-logic codec."""
        return self.encode(
            sample.text,
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
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

    def feature_keys_for_sample(self, sample: LegalSample) -> List[str]:
        """Return generalizable modal, frame, and F-logic features for SGD."""
        codec_result = self.encode(
            sample.text,
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
        )
        features: List[str] = list(self.decoder._feature_stream(codec_result.encoding))
        if codec_result.selected_frame:
            features.append(f"frame:{codec_result.selected_frame}")
        for candidate in codec_result.frame_candidates:
            frame_id = candidate.get("frame_id")
            if frame_id:
                features.append(f"frame-candidate:{frame_id}")
        for triple in codec_result.kg_triples:
            predicate = triple.get("predicate", "")
            obj = triple.get("object", "")
            if predicate and obj:
                features.append(f"flogic:{predicate}:{obj}")
        return _unique_preserve_order(features)

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
    ) -> Optional[FLogicOptimizerResult]:
        if not self.config.use_flogic:
            return None
        return self.flogic_optimizer.evaluate(
            source_text=source_text,
            decoded_text=decoded_text,
            source_embedding=source_embedding,
            decoded_embedding=decoded_embedding,
            kg_triples=kg_triples,
        )


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


def modal_ir_to_flogic_triples(
    modal_ir: ModalIRDocument,
    *,
    selected_frame: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Project modal IR into simple F-logic-style triples."""
    triples: List[Dict[str, str]] = [
        {"subject": modal_ir.document_id, "predicate": "type", "object": "legal_modal_document"},
        {"subject": modal_ir.document_id, "predicate": "source", "object": modal_ir.source},
    ]
    if selected_frame:
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": "selected_ontology_frame",
                "object": selected_frame,
            }
        )
    for frame in modal_ir.frame_candidates:
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": "candidate_ontology_frame",
                "object": frame.frame_id,
            }
        )
    for formula in modal_ir.formulas:
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
        if formula.predicate.role:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "predicate_role",
                    "object": formula.predicate.role,
                }
            )
        if selected_frame:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "interpreted_in_frame",
                    "object": selected_frame,
                }
            )
    return triples


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


def _flogic_result_to_dict(result: Optional[FLogicOptimizerResult]) -> Optional[Dict[str, Any]]:
    if result is None:
        return None
    data = asdict(result)
    data["violations"] = [asdict(violation) for violation in result.violations]
    return data


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
