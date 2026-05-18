"""Deterministic modal logic codec with BM25 frame-logic grounding.

This module is the canonical logic-layer facade for the legal modal
encoder/IR/decoder path.  It intentionally keeps LLM usage at zero: modal
operators come from the deterministic registry, ontology frames are selected
with BM25, decoded vectors come from stable spaCy-derived feature hashing, and
F-logic is used as a consistency check over the intermediate representation.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field, replace
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
    frame_ontology_high_signal_terms,
    frame_ontology_terms,
    frame_ontology_terms_from_feature_keys,
    frame_ontology_terms_from_triples,
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
    cross_entropy_distribution_loss,
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
    DecodedModalText,
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
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
    "after": "after",
    "before": "before",
    "by": "deadline",
    "no_later_than": "deadline",
    "not_later_than": "deadline",
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
_SLOT_FEATURE_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
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
        "sample",
        "sample_id",
        "sample_ids",
        "samples",
        "selected_term",
        "selected_terms",
        "source_id",
        "source_ids",
        "term",
        "terms",
        "text",
        "texts",
        "hint_evidence",
        "top_embedding_features",
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
        kg_triples = modal_ir_to_flogic_triples(modal_ir, selected_frame=selected_frame)
        flogic_ontology = flogic_triples_to_ontology(
            kg_triples,
            name=f"{modal_ir.document_id}_flogic",
        )
        neo4j_graph_data = flogic_triples_to_graph_data(
            kg_triples,
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
        modal_ir = replace(
            modal_ir,
            metadata={
                **modal_ir.metadata,
                "frame_ontology_term_audit_count": len(frame_audit_terms),
                "frame_ontology_term_audit_terms": frame_audit_terms,
                "frame_ontology_high_signal_term_audit_count": len(
                    frame_high_signal_audit_terms
                ),
                "frame_ontology_high_signal_term_audit_terms": frame_high_signal_audit_terms,
            },
        )
        decoded_text = decoded_modal_text.text
        flogic_result = self._evaluate_flogic(
            normalized_text,
            decoded_text,
            resolved_source_embedding,
            decoded_embedding,
            kg_triples,
            frame_feature_keys=frame_feature_keys,
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
        features.extend(_slot_features(codec_result.decoded_modal_text))
        if codec_result.selected_frame:
            features.append(f"frame:{codec_result.selected_frame}")
            for family in _selected_frame_modal_families(codec_result.modal_ir):
                features.append(f"family:selected_frame:{family}")
        frame_terms = _frame_ontology_terms_by_frame(codec_result.modal_ir)
        for frame_id in sorted(frame_terms):
            terms = frame_terms[frame_id]
            for term in terms:
                features.append(f"frame-term:{term}")
                if frame_id == codec_result.selected_frame:
                    features.append(f"selected-frame-term:{term}")
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
        return self.flogic_optimizer.evaluate(
            source_text=source_text,
            decoded_text=decoded_text,
            source_embedding=source_embedding,
            decoded_embedding=decoded_embedding,
            kg_triples=kg_triples,
            frame_feature_keys=frame_feature_keys,
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
    frame_terms_by_frame = _frame_ontology_terms_by_frame(modal_ir)
    selected_frame_terms: List[str] = []
    for frame_id in _ranked_candidate_frame_ids(
        modal_ir,
        frame_terms_by_frame=frame_terms_by_frame,
        selected_frame=resolved_selected_frame,
    ):
        triples.append(
            {
                "subject": modal_ir.document_id,
                "predicate": "candidate_ontology_frame",
                "object": frame_id,
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
    if resolved_selected_frame and not selected_frame_terms:
        selected_frame_terms = list(frame_terms_by_frame.get(resolved_selected_frame, ()))
        for term in selected_frame_terms:
            triples.append(
                {
                    "subject": modal_ir.document_id,
                    "predicate": "selected_ontology_term",
                    "object": term,
                }
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
        modal_operator_label = _clean_non_empty_string(formula.operator.label)
        if modal_operator_label:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "modal_operator_label",
                    "object": modal_operator_label,
                }
            )
        cue = _clean_non_empty_string(formula.metadata.get("cue"))
        if cue:
            triples.append(
                {
                    "subject": formula.formula_id,
                    "predicate": "modal_cue",
                    "object": cue,
                }
            )
            for predicate, value in _cue_modal_components(
                formula,
                cue=cue,
            ):
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
        for condition in sorted({value for value in formula.conditions if value}):
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
        for exception in sorted({value for value in formula.exceptions if value}):
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


def _clean_non_empty_string(value: Any) -> str:
    cleaned = str(value or "").strip()
    return cleaned if cleaned else ""


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


def _typed_clause_key_value(
    clause: str,
    *,
    clause_type: str,
) -> tuple[str, str] | None:
    normalized = _clean_non_empty_string(clause).lower()
    if not normalized:
        return None
    prefixes = _CONDITION_PREFIXES if clause_type == "condition" else _EXCEPTION_PREFIXES
    for prefix_text, prefix_key in prefixes:
        if not _text_has_prefix(normalized, prefix_text):
            continue
        value = _clean_non_empty_string(normalized[len(prefix_text) :].lstrip(",:;- "))
        return prefix_key, value
    return None


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
    signature = f"{family}:{symbol}:{cue_value}"
    components: List[tuple[str, str]] = [
        (f"{normalized_slot_prefix}_signature", signature),
        (f"{normalized_slot_prefix}_family", family),
        (f"{normalized_slot_prefix}_operator", symbol),
        (f"{normalized_slot_prefix}_lexeme", cue_value),
    ]
    temporal_relation = _temporal_clause_prefix_relation(cue_value)
    if temporal_relation:
        components.append(
            (f"{normalized_slot_prefix}_temporal_relation", temporal_relation)
        )
    return components


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
        components.append(("citation_source_id_alignment", "unparsed"))
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
    source_text = _collapse_whitespace_text(modal_ir.normalized_text)
    source_length = len(source_text)
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
        components.extend(
            [
                ("modal_family_count", f"{family}:{count}"),
                ("modal_family_count_ranked", f"{rank}:{family}:{count}"),
                ("modal_family_count_family", family),
                ("modal_family_count_value", count),
                (f"modal_family_count_{_slot_safe_family_key(family)}", count),
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
                if index == total_parts:
                    components.append(("citation_section_terminal_suffix_kind", suffix_kind))
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
        components.append(("citation_section_primary_terminal_number_relation", relation))
        components.append(("citation_section_primary_terminal_number_span", span))
        if is_range:
            components.append(("citation_section_range_number_relation", relation))
            components.append(("citation_section_range_number_span", span))
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
    components: List[tuple[str, str]] = [
        (f"{normalized_namespace}_section_style", style),
        (f"{normalized_namespace}_section_suffix_style", suffix_style),
        (f"{normalized_namespace}_section_punctuation_style", punctuation_style),
    ]
    components.extend(
        _typed_identifier_components(
            style,
            slot_prefix=f"{normalized_namespace}_section_style",
        )
    )
    return _unique_preserve_order_tuples(components)


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
    trailing = source_text[end:]
    if not trailing:
        return ""
    trailing = trailing.lstrip(" \t\r\n-–—:;,.")
    if not trailing:
        return ""
    candidate = _SECTION_HEADING_TAIL_SPLIT_RE.split(trailing, maxsplit=1)[0]
    heading_tail = _clean_non_empty_string(candidate)
    if not heading_tail:
        return ""
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(heading_tail.lower())
    if len(tokens) > max_tokens:
        return ""
    return heading_tail


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
    normalized = _TRAILING_SECTION_PUNCT_RE.sub("", normalized)
    if not normalized:
        return ""
    status_surface = _status_heading_surface_text(
        normalized,
        status_keyword=_status_keyword_value(
            formula,
            fallback_rule=fallback_rule,
        ),
    )
    if status_surface:
        return status_surface
    tokens = _SLOT_FEATURE_TOKEN_RE.findall(normalized.lower())
    if not tokens or len(tokens) > max_tokens:
        return ""
    return normalized


def _status_heading_surface_text(text: str, *, status_keyword: str) -> str:
    normalized_text = _clean_non_empty_string(text)
    normalized_keyword = _clean_non_empty_string(status_keyword).lower()
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


def _append_statutory_scope_triples(
    triples: List[Dict[str, str]],
    *,
    subject: str,
    text: str,
    emitted: set[tuple[str, str]],
) -> None:
    for predicate, value in _statutory_scope_entries(text):
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


def _slot_features(decoded: DecodedModalText) -> List[str]:
    features: List[str] = []
    slot_text_map = decoded_modal_phrase_slot_text_map(decoded)
    for slot, values in sorted(slot_text_map.items()):
        if slot in _SLOT_FEATURE_EXCLUDED_SLOTS:
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
        metadata.get("feature"),
        metadata.get("feature_key"),
        metadata.get("feature_keys"),
        metadata.get("features"),
        metadata.get("frame_feature"),
        metadata.get("frame_feature_key"),
        metadata.get("frame_feature_keys"),
        metadata.get("frame_features"),
        metadata.get("sample_id"),
        metadata.get("sample_ids"),
        metadata.get("source_id"),
        metadata.get("source_ids"),
        metadata.get("hint_evidence"),
        metadata.get("top_embedding_features"),
        metadata.get("top_family_features"),
    ]
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
            frame_logic_metadata.get("citation"),
            frame_logic_metadata.get("citations"),
            frame_logic_metadata.get("dedupe_signature"),
            frame_logic_metadata.get("feature"),
            frame_logic_metadata.get("feature_key"),
            frame_logic_metadata.get("feature_keys"),
            frame_logic_metadata.get("features"),
            frame_logic_metadata.get("frame_feature"),
            frame_logic_metadata.get("frame_feature_key"),
            frame_logic_metadata.get("frame_feature_keys"),
            frame_logic_metadata.get("frame_features"),
            frame_logic_metadata.get("hint_evidence"),
            frame_logic_metadata.get("top_embedding_features"),
            frame_logic_metadata.get("top_family_features"),
        ]
    )
    return frame_ontology_feature_keys_from_values(
        metadata_values,
        max_keys=_FRAME_ONTOLOGY_AUDIT_MAX_FEATURE_KEYS,
    )


def _frame_ontology_audit_terms(
    *,
    frame_feature_keys: Sequence[str],
    kg_triples: Sequence[Mapping[str, str]],
) -> List[str]:
    return sorted(_unique_preserve_order(
        list(
            frame_ontology_terms_from_feature_keys(
                frame_feature_keys,
                max_terms=_FRAME_ONTOLOGY_AUDIT_MAX_TERMS,
            )
        )
        + list(
            frame_ontology_terms_from_triples(
                kg_triples,
                max_terms=_FRAME_ONTOLOGY_AUDIT_MAX_TERMS,
            )
        )
    ))


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
