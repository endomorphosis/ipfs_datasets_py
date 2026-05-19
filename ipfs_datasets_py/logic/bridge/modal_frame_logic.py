"""Modal/frame-logic implementation of the legal IR bridge contract."""

from __future__ import annotations

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
    ) -> tuple[LegalIRDocument, Any]:
        """Encode legal text into the canonical bridge IR envelope."""

        codec = self._codec()
        codec_result = codec.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
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
        evaluate_provers: Optional[bool] = None,
    ) -> BridgeEvaluationReport:
        """Run the full bridge: encode, graph-project, and proof-gate."""

        ir_document, codec_result = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
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

        round_trip = RoundTripMetrics.from_loss_mapping(codec_result.losses)
        status = "ok" if ir_document.has_frame_logic and graph_result.graph_failure_penalty == 0.0 else "partial"
        if should_prove and not proof_gate.compiles:
            status = "partial"

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
                "parser_name": codec_result.parser_name,
                "selected_frame": codec_result.selected_frame or "",
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
        return ProofGateResult.from_signal(signal)


def _citation_from_modal_ir(modal_ir: Any) -> str:
    if getattr(modal_ir, "formulas", None):
        provenance = getattr(modal_ir.formulas[0], "provenance", None)
        citation = getattr(provenance, "citation", None)
        if citation:
            return str(citation)
    metadata = getattr(modal_ir, "metadata", {}) or {}
    return str(metadata.get("citation") or modal_ir.document_id)


__all__ = ["ModalFrameLogicBridgeAdapter"]
