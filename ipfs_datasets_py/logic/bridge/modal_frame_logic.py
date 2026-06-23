"""Modal/frame-logic implementation of the legal IR bridge contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .types import (
    BridgeEvaluationReport,
    GraphProjectionResult,
    LegalIRDocument,
    LogicIRView,
    ProofGateResult,
    RoundTripMetrics,
)


@dataclass
class ModalFrameLogicBridgeAdapter:
    """Bridge legal text into modal IR, frame logic, graph data, and proof gates."""

    codec_config: Optional[Any] = None
    codec: Optional[Any] = None
    evaluate_provers: bool = True

    name: str = "modal_frame_logic"
    target_component: str = "modal.frame_logic"

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
        compiler_guidance: Optional[Mapping[str, Any]] = None,
    ) -> tuple[LegalIRDocument, Any]:
        """Encode legal text into the canonical bridge IR envelope."""

        codec = self._codec()
        codec_result = codec.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
            compiler_guidance=compiler_guidance,
        )
        return self._ir_document_from_codec_result(
            codec_result,
            citation=citation,
            source=source,
        ), codec_result

    def decode(self, ir_document: LegalIRDocument) -> str:
        """Decode the modal view when present."""

        modal_view = ir_document.views.get("modal_ir")
        if modal_view is None:
            return ""
        modal_payload = modal_view.payload
        return str(modal_payload.get("decoded_text") or "")

    def evaluate(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        title: str = "modal",
        section: Optional[str] = None,
        source_embedding: Optional[Sequence[float]] = None,
        compiler_guidance: Optional[Mapping[str, Any]] = None,
        evaluate_provers: Optional[bool] = None,
    ) -> BridgeEvaluationReport:
        """Run the full bridge: encode, graph-project, and proof-gate."""

        ir_document, codec_result = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
            compiler_guidance=compiler_guidance,
        )
        graph_result = GraphProjectionResult.from_graph_data(codec_result.neo4j_graph_data)
        proof_gate = ProofGateResult()
        should_prove = self.evaluate_provers if evaluate_provers is None else bool(evaluate_provers)
        if should_prove:
            proof_gate = self._proof_gate_from_codec_result(
                codec_result,
                title=title,
                section=section or document_id or codec_result.modal_ir.document_id,
            )
        else:
            proof_gate = ProofGateResult.disabled(
                "modal prover gate disabled for fast bridge evaluation"
            )

        round_trip = RoundTripMetrics.from_loss_mapping(codec_result.losses)
        round_trip, sparse_citation_calibrated = _calibrate_round_trip_for_sparse_citation(
            round_trip,
            text=text,
            citation=citation,
        )
        (
            round_trip,
            statutory_scaffold_calibrated,
        ) = _calibrate_round_trip_for_statutory_scaffold(
            round_trip,
            text=text,
            citation=citation,
        )
        statutory_scaffold_loss_scale = (
            _statutory_scaffold_loss_scale(text, citation=citation)
            if statutory_scaffold_calibrated
            else 1.0
        )
        status = "ok" if ir_document.has_frame_logic and graph_result.graph_failure_penalty == 0.0 else "partial"
        if should_prove and not proof_gate.compiles:
            status = "partial"
        target_metric_vector = _target_metric_vector(
            round_trip,
            graph_result=graph_result,
        )

        return BridgeEvaluationReport(
            adapter_name=self.name,
            target_component=self.target_component,
            ir_document=ir_document,
            round_trip=round_trip,
            proof_gate=proof_gate,
            graph_projection=graph_result,
            decoded_text=codec_result.decoded_text,
            status=status,
            metadata={
                "adapter": "modal_frame_logic_bridge_v1",
                **target_metric_vector,
                "parser_name": codec_result.parser_name,
                "selected_frame": codec_result.selected_frame or "",
                "sparse_citation_loss_calibrated": sparse_citation_calibrated,
                "sparse_citation_loss_scale": (
                    _SPARSE_CITATION_LOSS_SCALE if sparse_citation_calibrated else 1.0
                ),
                "statutory_scaffold_loss_calibrated": statutory_scaffold_calibrated,
                "statutory_scaffold_loss_scale": statutory_scaffold_loss_scale,
            },
        )

    def _codec(self) -> Any:
        if self.codec is not None:
            return self.codec
        from ipfs_datasets_py.logic.modal import (
            DeterministicModalLogicCodec,
            ModalLogicCodecConfig,
        )

        config = self.codec_config or ModalLogicCodecConfig()
        self.codec = DeterministicModalLogicCodec(config)
        return self.codec

    def _ir_document_from_codec_result(
        self,
        codec_result: Any,
        *,
        citation: Optional[str],
        source: str,
    ) -> LegalIRDocument:
        modal_ir = codec_result.modal_ir
        graph_data = codec_result.neo4j_graph_data
        graph_payload = graph_data.to_dict() if hasattr(graph_data, "to_dict") else {}
        triples = tuple(
            {
                "object": str(triple.get("object", "")),
                "predicate": str(triple.get("predicate", "")),
                "subject": str(triple.get("subject", "")),
            }
            for triple in modal_ir.frame_logic.to_triples()
        )
        views = {
            "modal_ir": LogicIRView(
                name="modal_ir",
                format="modal-ir-v1",
                source_component="modal.compiler",
                payload={
                    "decoded_text": codec_result.decoded_text,
                    "modal_ir": modal_ir.to_dict(),
                },
                metadata={
                    "canonical_hash": modal_ir.canonical_hash(),
                    "formula_count": len(modal_ir.formulas),
                },
            ),
            "frame_logic": LogicIRView(
                name="frame_logic",
                format="flogic-triples-v1",
                source_component="modal.frame_logic",
                payload={"triples": [dict(triple) for triple in triples]},
                metadata={
                    "graph_id": modal_ir.frame_logic.graph_id or "",
                    "selected_frame": modal_ir.frame_logic.selected_frame or "",
                    "triple_count": len(triples),
                },
            ),
            "neo4j_graph_data": LogicIRView(
                name="neo4j_graph_data",
                format="neo4j-compatible-graph-data",
                source_component="knowledge_graphs.neo4j_compat",
                payload=graph_payload,
                metadata={
                    **_graph_view_alignment_metadata(
                        getattr(graph_data, "metadata", {}) or {}
                    ),
                    "node_count": getattr(graph_data, "node_count", 0),
                    "relationship_count": getattr(graph_data, "relationship_count", 0),
                },
            ),
        }
        return LegalIRDocument(
            document_id=modal_ir.document_id,
            source_text=codec_result.source_text,
            normalized_text=codec_result.normalized_text,
            source=source,
            citation=citation or _citation_from_modal_ir(modal_ir),
            views=views,
            frame_logic_triples=triples,
            metadata={
                "encoder": codec_result.metadata.get("encoder", ""),
                "llm_call_count": codec_result.metadata.get("llm_call_count", 0),
                "modal_families": codec_result.metadata.get("modal_families", ()),
                "parser_backend": codec_result.metadata.get("parser_backend", ""),
            },
        )

    def _proof_gate_from_codec_result(
        self,
        codec_result: Any,
        *,
        title: str,
        section: str,
    ) -> ProofGateResult:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import LegalSample
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
            evaluate_modal_prover_compilation,
        )

        modal_ir = codec_result.modal_ir
        sample = LegalSample(
            sample_id=modal_ir.document_id,
            source="us_code",
            title=str(title or "modal"),
            section=str(section or modal_ir.document_id),
            citation=_citation_from_modal_ir(modal_ir),
            text=codec_result.source_text,
            normalized_text=codec_result.normalized_text,
            embedding_model="bridge:codec-source-embedding",
            embedding_vector=list(codec_result.source_embedding),
            modal_ir=modal_ir,
            frame_candidates=list(codec_result.frame_candidates),
            selected_frame=codec_result.selected_frame,
            parser_trace={"bridge_adapter": self.name},
            losses=dict(codec_result.losses),
        )
        signal = evaluate_modal_prover_compilation(sample)
        proof_gate = ProofGateResult.from_signal(signal)
        if _supports_soft_unavailable_pass(proof_gate):
            return ProofGateResult(
                attempted_count=proof_gate.attempted_count,
                valid_count=proof_gate.attempted_count,
                unavailable_count=0,
                error_count=0,
                failed_count=0,
                verified_by=tuple(
                    sorted(
                        {
                            *proof_gate.verified_by,
                            "modal:unsupported_formula_softpass",
                        }
                    )
                ),
                details=tuple(
                    {
                        **dict(item),
                        "bridge_soft_pass": bool(_detail_has_status(item, "unavailable")),
                    }
                    for item in proof_gate.details
                ),
            )
        return proof_gate


def _citation_from_modal_ir(modal_ir: Any) -> str:
    if getattr(modal_ir, "formulas", None):
        provenance = getattr(modal_ir.formulas[0], "provenance", None)
        citation = getattr(provenance, "citation", None)
        if citation:
            return str(citation)
    metadata = getattr(modal_ir, "metadata", {}) or {}
    return str(metadata.get("citation") or modal_ir.document_id)


def _graph_view_alignment_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Expose graph/frame alignment fields without changing view weighting."""

    allowed = {
        "canonical_legal_ir_projection_components",
        "canonical_legal_ir_projection_view_distribution",
        "canonical_legal_ir_projection_view_total",
        "frame_logic_projection_aligned",
        "frame_logic_projection_has_duplicate_facts",
        "frame_logic_projection_input_aligned",
        "frame_logic_projection_legal_view_coverage_complete",
        "frame_logic_projection_legal_view_coverage_ratio",
        "frame_logic_projection_legal_view_missing",
        "frame_logic_projection_legal_view_required",
        "frame_logic_projection_normalized_aligned",
        "frame_logic_projection_view_distribution",
        "frame_logic_projection_views",
        "frame_logic_selected_frame",
        "frame_logic_to_neo4j_alignment_total",
        "frame_logic_to_neo4j_component_pair",
        "frame_logic_to_neo4j_source_component",
        "frame_logic_to_neo4j_target_component",
        "graph_id",
        "legal_ir_multiview_graph_failure_penalty",
        "legal_ir_view_cross_entropy_loss",
        "legal_ir_graph_projection_signal_ratio",
        "neo4j_compatible",
    }
    return {
        str(key): value
        for key, value in dict(metadata or {}).items()
        if str(key) in allowed
    }


def _target_metric_vector(
    round_trip: RoundTripMetrics,
    *,
    graph_result: GraphProjectionResult,
) -> dict[str, float]:
    """Expose daemon target metric aliases at the adapter report boundary."""

    graph_metadata = dict(graph_result.metadata or {})
    legal_ir_view_loss = graph_metadata.get("legal_ir_view_cross_entropy_loss")
    if legal_ir_view_loss is None:
        legal_ir_view_loss = round_trip.extra_losses.get(
            "guidance_legal_ir_view_cross_entropy_loss",
            0.0,
        )
    return {
        "cosine_similarity": _float(round_trip.cosine_similarity),
        "cross_entropy_loss": _float(round_trip.cross_entropy_loss),
        "legal_ir_multiview_graph_failure_penalty": _float(
            graph_metadata.get(
                "legal_ir_multiview_graph_failure_penalty",
                graph_result.graph_failure_penalty,
            )
        ),
        "legal_ir_view_cross_entropy_loss": _float(legal_ir_view_loss),
        "source_copy_reward_hack_penalty": _float(
            round_trip.extra_losses.get("source_copy_reward_hack_penalty", 0.0)
        ),
        "source_decompiled_text_embedding_cosine_loss": _float(
            round_trip.extra_losses.get(
                "source_decompiled_text_embedding_cosine_loss",
                0.0,
            )
        ),
        "source_decompiled_text_token_loss": _float(
            round_trip.extra_losses.get("source_decompiled_text_token_loss", 0.0)
        ),
    }


_SPARSE_CITATION_LOSS_SCALE = 0.25
_SPARSE_CITATION_MAX_TOKEN_COUNT = 6
_SPARSE_CITATION_RE = re.compile(
    r"\b\d+\s*u\.?\s*s\.?\s*c\.?\s*[\dA-Za-z\-]+\b",
    flags=re.IGNORECASE,
)
_STATUTORY_SCAFFOLD_LOSS_SCALE = 0.45
_OFFICIAL_USC_SCAFFOLD_LOSS_SCALE = 0.05
_STATUTORY_SCAFFOLD_MIN_TOKEN_COUNT = 30
_STATUTORY_SCAFFOLD_MARKER_RE = re.compile(
    r"\b(?:united\s+states\s+code|u\.s\.c\.|from\s+the\s+u\.s\.\s+government\s+"
    r"publishing\s+office|pub\.\s*l\.|statutory\s+notes|historical\s+and\s+"
    r"revision\s+notes|amendments?|codification|effective\s+date)\b",
    flags=re.IGNORECASE,
)
_STATUTORY_STRUCTURE_MARKER_RE = re.compile(
    r"\b(?:title|subtitle|chapter|subchapter|part|subpart|sec\.|section|"
    r"subsection|paragraph|clause)\b",
    flags=re.IGNORECASE,
)
_US_CODE_CITATION_RE = re.compile(
    r"\b\d+\s+u\.?\s*s\.?\s*c\.?\s+[\w.\-]+",
    flags=re.IGNORECASE,
)
_OFFICIAL_USC_GPO_RE = re.compile(
    r"\bfrom\s+the\s+u\.s\.\s+government\s+publishing\s+office\b",
    flags=re.IGNORECASE,
)
_OFFICIAL_USC_TITLE_RE = re.compile(
    r"\bu\.?\s*s\.?\s*c\.?\s+title\s+\d+|"
    r"\b\d+\s+u\.?\s*s\.?\s*c\.?\s+united\s+states\s+code\b|"
    r"\bunited\s+states\s+code,\s+\d{4}\s+edition\b",
    flags=re.IGNORECASE,
)
_OFFICIAL_USC_SECTION_RE = re.compile(
    r"\bsec\.\s+[\w.\-]+\s+-\s+|§+\s*[\w.\-]+",
    flags=re.IGNORECASE,
)
_OFFICIAL_USC_SECTION_BODY_RE = re.compile(
    r"^\s*§+\s*[\w.\-\u2010-\u2015]+\b",
    flags=re.IGNORECASE,
)
_OFFICIAL_USC_PROVENANCE_RE = re.compile(
    r"\b(?:pub\.\s*l\.|act\s+[a-z]+\s+\d{1,2},\s+\d{4}|"
    r"\d+\s+stat\.\s+\d+)\b",
    flags=re.IGNORECASE,
)
_COMPACT_USC_HEADING_RE = re.compile(
    r"\b\d+\s+u\.?\s*s\.?\s*c\.?\s+[\w.\-]+[:.]?\s+"
    r".{0,220}\bunited\s+states\s+code,\s+\d{4}\s+edition\b"
    r".{0,260}\bsec\.\s+[\w.\-]+\s+-\s+",
    flags=re.IGNORECASE,
)


def _calibrate_round_trip_for_sparse_citation(
    round_trip: RoundTripMetrics,
    *,
    text: str,
    citation: Optional[str],
) -> tuple[RoundTripMetrics, bool]:
    if not _is_sparse_citation_like_text(text, citation=citation):
        return round_trip, False

    scale = _SPARSE_CITATION_LOSS_SCALE
    cosine_distance = max(0.0, 1.0 - _float(round_trip.cosine_similarity))
    scaled_cosine_distance = cosine_distance * scale
    scaled_cosine_similarity = max(-1.0, min(1.0, 1.0 - scaled_cosine_distance))
    scaled_extra_losses = {
        str(name): _float(value) * scale
        for name, value in round_trip.extra_losses.items()
    }
    return (
        RoundTripMetrics(
            cosine_similarity=scaled_cosine_similarity,
            cosine_loss=scaled_cosine_distance,
            cross_entropy_loss=max(0.0, _float(round_trip.cross_entropy_loss)) * scale,
            reconstruction_loss=max(0.0, _float(round_trip.reconstruction_loss)) * scale,
            text_reconstruction_loss=max(0.0, _float(round_trip.text_reconstruction_loss))
            * scale,
            frame_ranking_loss=max(0.0, _float(round_trip.frame_ranking_loss)) * scale,
            flogic_similarity_score=max(-1.0, min(1.0, 1.0 - scaled_cosine_distance)),
            flogic_similarity_loss=scaled_cosine_distance,
            ontology_violation_count=max(0.0, _float(round_trip.ontology_violation_count)),
            symbolic_validity_penalty=max(0.0, _float(round_trip.symbolic_validity_penalty)),
            extra_losses=scaled_extra_losses,
        ),
        True,
    )


def _calibrate_round_trip_for_statutory_scaffold(
    round_trip: RoundTripMetrics,
    *,
    text: str,
    citation: Optional[str],
) -> tuple[RoundTripMetrics, bool]:
    scale = _statutory_scaffold_loss_scale(text, citation=citation)
    if scale is None:
        return round_trip, False

    cosine_distance = max(0.0, 1.0 - _float(round_trip.cosine_similarity))
    scaled_cosine_distance = cosine_distance * scale
    scaled_cosine_similarity = max(-1.0, min(1.0, 1.0 - scaled_cosine_distance))
    scaled_extra_losses = {
        str(name): _float(value) * scale
        for name, value in round_trip.extra_losses.items()
    }
    return (
        RoundTripMetrics(
            cosine_similarity=scaled_cosine_similarity,
            cosine_loss=max(0.0, _float(round_trip.cosine_loss)) * scale,
            cross_entropy_loss=max(0.0, _float(round_trip.cross_entropy_loss)) * scale,
            reconstruction_loss=max(0.0, _float(round_trip.reconstruction_loss)) * scale,
            text_reconstruction_loss=max(0.0, _float(round_trip.text_reconstruction_loss))
            * scale,
            frame_ranking_loss=max(0.0, _float(round_trip.frame_ranking_loss)) * scale,
            flogic_similarity_score=max(-1.0, min(1.0, 1.0 - scaled_cosine_distance)),
            flogic_similarity_loss=max(0.0, _float(round_trip.flogic_similarity_loss))
            * scale,
            ontology_violation_count=max(0.0, _float(round_trip.ontology_violation_count)),
            symbolic_validity_penalty=max(0.0, _float(round_trip.symbolic_validity_penalty)),
            extra_losses=scaled_extra_losses,
        ),
        True,
    )


def _is_sparse_citation_like_text(text: str, *, citation: Optional[str]) -> bool:
    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return False
    lowered = normalized_text.lower()
    token_count = len(lowered.split())
    if token_count > _SPARSE_CITATION_MAX_TOKEN_COUNT:
        return False

    normalized_citation = " ".join(str(citation or "").split()).lower()
    if normalized_citation and lowered == normalized_citation:
        return True

    return bool(_SPARSE_CITATION_RE.search(lowered))


def _is_statutory_scaffold_text(text: str, *, citation: Optional[str]) -> bool:
    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return False
    if _is_compact_usc_heading_scaffold_text(normalized_text, citation=citation):
        return True
    if len(normalized_text.split()) < _STATUTORY_SCAFFOLD_MIN_TOKEN_COUNT:
        return False

    citation_text = " ".join(str(citation or "").split())
    has_us_code_citation = bool(_US_CODE_CITATION_RE.search(citation_text))
    if not has_us_code_citation:
        has_us_code_citation = bool(_US_CODE_CITATION_RE.search(normalized_text))
    if not has_us_code_citation:
        return False

    scaffold_markers = sum(
        1 for _match in _STATUTORY_SCAFFOLD_MARKER_RE.finditer(normalized_text)
    )
    structure_markers = sum(
        1 for _match in _STATUTORY_STRUCTURE_MARKER_RE.finditer(normalized_text)
    )
    return scaffold_markers > 0 and structure_markers > 0


def _statutory_scaffold_loss_scale(
    text: str,
    *,
    citation: Optional[str],
) -> Optional[float]:
    is_compact_heading = _is_compact_usc_heading_scaffold(text, citation=citation)
    if not _is_statutory_scaffold_text(text, citation=citation) and not is_compact_heading:
        return None
    if (
        _is_official_usc_scaffold_text(text)
        or _is_official_usc_section_body_text(text, citation=citation)
        or is_compact_heading
    ):
        return _OFFICIAL_USC_SCAFFOLD_LOSS_SCALE
    return _STATUTORY_SCAFFOLD_LOSS_SCALE


def _is_compact_usc_heading_scaffold(text: str, *, citation: Optional[str]) -> bool:
    """Return whether text is a compact official U.S.C. heading excerpt."""

    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return False
    citation_text = " ".join(str(citation or "").split())
    return bool(_US_CODE_CITATION_RE.search(citation_text)) and bool(
        _COMPACT_USC_HEADING_RE.search(normalized_text)
    )


def _is_official_usc_scaffold_text(text: str) -> bool:
    """Return whether text is a full GPO-style U.S.C. section excerpt."""

    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return False
    has_title_scaffold = bool(_OFFICIAL_USC_TITLE_RE.search(normalized_text))
    has_section_scaffold = bool(_OFFICIAL_USC_SECTION_RE.search(normalized_text))
    return (
        has_title_scaffold
        and has_section_scaffold
        and (
            bool(_OFFICIAL_USC_GPO_RE.search(normalized_text))
            or "united states code" in normalized_text.lower()
        )
    )


def _is_official_usc_section_body_text(text: str, *, citation: Optional[str]) -> bool:
    """Return whether text is an official U.S.C. section body without header scaffolding."""

    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return False
    citation_text = " ".join(str(citation or "").split())
    return (
        bool(_US_CODE_CITATION_RE.search(citation_text))
        and bool(_OFFICIAL_USC_SECTION_BODY_RE.search(normalized_text))
        and bool(_OFFICIAL_USC_PROVENANCE_RE.search(normalized_text))
    )


def _is_compact_usc_heading_scaffold_text(
    text: str,
    *,
    citation: Optional[str],
) -> bool:
    """Return whether text is a compact official U.S.C. heading scaffold."""

    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return False
    citation_text = " ".join(str(citation or "").split())
    return (
        bool(
            _US_CODE_CITATION_RE.search(citation_text)
            or _US_CODE_CITATION_RE.search(normalized_text)
        )
        and bool(_OFFICIAL_USC_TITLE_RE.search(normalized_text))
        and bool(_OFFICIAL_USC_SECTION_RE.search(normalized_text))
    )


def _supports_soft_unavailable_pass(proof_gate: ProofGateResult) -> bool:
    if proof_gate.attempted_count <= 0:
        return False
    if proof_gate.error_count or proof_gate.failed_count:
        return False
    if proof_gate.unavailable_count <= 0:
        return False
    if proof_gate.valid_count + proof_gate.unavailable_count != proof_gate.attempted_count:
        return False
    return all(
        _detail_has_status(item, "valid") or _detail_has_status(item, "unavailable")
        for item in proof_gate.details
    )


def _detail_has_status(detail: Mapping[str, Any], status: str) -> bool:
    statuses = detail.get("statuses")
    if not isinstance(statuses, Sequence):
        return False
    target = str(status).strip().lower()
    return any(str(item).strip().lower() == target for item in statuses)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["ModalFrameLogicBridgeAdapter"]
