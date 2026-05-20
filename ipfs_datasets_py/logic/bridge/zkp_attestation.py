"""ZKP proof-attestation implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .fol_tdfol import FolTdfolBridgeAdapter
from .types import (
    BridgeEvaluationReport,
    GraphProjectionResult,
    LegalIRDocument,
    LogicIRView,
    ProofGateResult,
    RoundTripMetrics,
)


@dataclass
class ZkpAttestationBridgeAdapter:
    """Bridge formal legal formulas into ZKP attestation records.

    The current ``logic.zkp`` package defaults to a simulated backend.  This
    adapter keeps that status visible in metadata while still giving the
    optimizer a concrete ZKP view, proof gate, graph projection, and loss names.
    """

    tdfol_adapter: Optional[FolTdfolBridgeAdapter] = None
    prover_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: {
            "backend": "simulated",
            "enable_caching": True,
        }
    )
    verifier_kwargs: Mapping[str, Any] = field(default_factory=lambda: {"backend": "simulated"})

    name: str = "zkp_attestation"
    target_component: str = "zkp.circuits"

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
    ) -> tuple[LegalIRDocument, Mapping[str, Any]]:
        adapter = self.tdfol_adapter or FolTdfolBridgeAdapter()
        _, context = adapter.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
        )
        formula_records = list(context.get("formula_records") or [])
        resolved_document_id = document_id or _document_id("zkp", text)
        attestations = _zkp_attestation_records(
            formula_records,
            prover_kwargs=self.prover_kwargs,
            verifier_kwargs=self.verifier_kwargs,
        )
        triples = tuple(
            _zkp_frame_logic_triples(
                resolved_document_id,
                attestations=attestations,
            )
        )
        graph_data = _graph_data_from_triples(
            triples,
            graph_id=f"{resolved_document_id}:zkp-flogic",
            metadata={
                "source": "zkp_attestation_bridge_ir",
                "zkp_attestation_count": len(attestations),
            },
        )
        views = {
            "zkp_attestations": LogicIRView(
                name="zkp_attestations",
                format="zkp-attestation-records",
                source_component="zkp.circuits",
                payload={
                    "records": [
                        _public_attestation_record(record)
                        for record in attestations
                    ]
                },
                metadata={
                    "attestation_count": len(attestations),
                    "verified_count": sum(1 for record in attestations if record["verified"]),
                },
            ),
            "zkp_public_inputs": LogicIRView(
                name="zkp_public_inputs",
                format="zkp-public-input-records",
                source_component="zkp.backends",
                payload={
                    "records": [
                        {
                            "public_inputs": dict(record.get("public_inputs") or {}),
                            "source_id": record["source_id"],
                        }
                        for record in attestations
                    ]
                },
                metadata={"record_count": len(attestations)},
            ),
            "frame_logic": LogicIRView(
                name="frame_logic",
                format="flogic-triples-v1",
                source_component="zkp.circuits",
                payload={"triples": [dict(triple) for triple in triples]},
                metadata={"triple_count": len(triples)},
            ),
        }
        if graph_data is not None:
            views["neo4j_graph_data"] = LogicIRView(
                name="neo4j_graph_data",
                format="neo4j-compatible-graph-data",
                source_component="knowledge_graphs.neo4j_compat",
                payload=graph_data.to_dict(),
                metadata={
                    "node_count": graph_data.node_count,
                    "relationship_count": graph_data.relationship_count,
                },
            )

        return (
            LegalIRDocument(
                document_id=resolved_document_id,
                source_text=text,
                normalized_text=" ".join(str(text or "").split()),
                source=source,
                citation=citation,
                views=views,
                frame_logic_triples=triples,
                metadata={
                    "formula_count": len(formula_records),
                    "proof_system": "simulated_zkp",
                    "zkp_attestation_count": len(attestations),
                },
            ),
            {
                "attestations": attestations,
                "formula_records": formula_records,
                "graph_data": graph_data,
            },
        )

    def evaluate(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
        **_: Any,
    ) -> BridgeEvaluationReport:
        ir_document, context = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
        )
        attestations = list(context["attestations"])
        proof_gate = _proof_gate_from_attestations(attestations)
        graph_result = GraphProjectionResult.from_graph_data(context["graph_data"])
        attempted = max(1, len(attestations))
        verified_count = sum(1 for record in attestations if record["verified"])
        missing_loss = 0.0 if attestations else 1.0
        verification_failure_ratio = (
            max(0.0, (attempted - verified_count) / attempted)
            if attestations
            else 1.0
        )
        round_trip = RoundTripMetrics(
            cosine_similarity=max(0.0, 1.0 - missing_loss),
            cosine_loss=missing_loss,
            symbolic_validity_penalty=verification_failure_ratio,
            extra_losses={
                "zkp_attestation_missing_loss": missing_loss,
                "zkp_verification_failure_ratio": verification_failure_ratio,
            },
        )
        status = "ok" if attestations and proof_gate.compiles else "partial"
        if graph_result.graph_failure_penalty:
            status = "partial"
        return BridgeEvaluationReport(
            adapter_name=self.name,
            target_component=self.target_component,
            ir_document=ir_document,
            round_trip=round_trip,
            proof_gate=proof_gate,
            graph_projection=graph_result,
            decoded_text=" ".join(str(record.get("theorem") or "") for record in attestations),
            status=status,
            metadata={
                "adapter": "zkp_attestation_bridge_v1",
                "proof_system": "simulated_zkp",
                "simulated_only": True,
            },
        )


def _zkp_attestation_records(
    formula_records: Sequence[Mapping[str, Any]],
    *,
    prover_kwargs: Mapping[str, Any],
    verifier_kwargs: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not formula_records:
        return []
    from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        prover = ZKPProver(**dict(prover_kwargs))
        verifier = ZKPVerifier(**dict(verifier_kwargs))

    records: list[dict[str, Any]] = []
    for index, formula_record in enumerate(formula_records):
        theorem = str(formula_record.get("formula") or "").strip()
        if not theorem:
            continue
        source_id = str(formula_record.get("source_id") or f"zkp:formula:{index}")
        axioms = _private_axioms_for_formula(formula_record, theorem=theorem)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                proof = prover.generate_proof(
                    theorem,
                    axioms,
                    metadata={
                        "circuit_ref": "legal_ir_zkp_attestation@v1",
                        "circuit_version": 1,
                        "ruleset_id": "LegalIR_TDFOL_v1",
                    },
                )
                verified = bool(verifier.verify_proof(proof))
            proof_dict = proof.to_dict()
            proof_hash = hashlib.sha256(proof.proof_data).hexdigest()
            public_inputs = dict(proof.public_inputs)
            error = ""
        except Exception as exc:
            proof_dict = {}
            proof_hash = ""
            public_inputs = {}
            verified = False
            error = f"{type(exc).__name__}: {str(exc)[:120]}"
        records.append(
            {
                "axiom_count": len(axioms),
                "error": error,
                "proof": proof_dict,
                "proof_hash": proof_hash,
                "public_inputs": public_inputs,
                "source_id": source_id,
                "theorem": theorem,
                "verified": verified,
            }
        )
    return records


def _private_axioms_for_formula(record: Mapping[str, Any], *, theorem: str) -> list[str]:
    axioms = [theorem]
    for predicate in record.get("predicates") or []:
        predicate_text = str(predicate or "").strip()
        if predicate_text:
            axioms.append(f"uses_predicate({predicate_text})")
    source_id = str(record.get("source_id") or "").strip()
    if source_id:
        axioms.append(f"source_id({source_id})")
    return sorted(set(axioms))


def _proof_gate_from_attestations(
    records: Sequence[Mapping[str, Any]],
) -> ProofGateResult:
    attempted = len(records)
    valid = sum(1 for record in records if record.get("verified"))
    failed = attempted - valid
    return ProofGateResult(
        attempted_count=attempted,
        valid_count=valid,
        failed_count=failed,
        verified_by=("zkp:simulated",) if valid else (),
        details=tuple(
            {
                "error": record.get("error") or "",
                "proof_hash": record.get("proof_hash") or "",
                "source_id": record.get("source_id") or "",
                "verified": bool(record.get("verified")),
            }
            for record in records
        ),
    )


def _zkp_frame_logic_triples(
    document_id: str,
    *,
    attestations: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    triples = [
        {"subject": document_id, "predicate": "type", "object": "legal_zkp_document"}
    ]
    for record in attestations:
        source_id = str(record.get("source_id") or "")
        if not source_id:
            continue
        public_inputs = dict(record.get("public_inputs") or {})
        proof_node = f"{source_id}:zkp_proof"
        triples.extend(
            [
                {"subject": document_id, "predicate": "contains_zkp_attestation", "object": proof_node},
                {"subject": proof_node, "predicate": "type", "object": "zkp_attestation"},
                {"subject": proof_node, "predicate": "attests_formula", "object": source_id},
                {"subject": proof_node, "predicate": "proof_hash", "object": str(record.get("proof_hash") or "")},
                {"subject": proof_node, "predicate": "verified", "object": str(bool(record.get("verified"))).lower()},
            ]
        )
        for key in ("theorem_hash", "axioms_commitment", "ruleset_id"):
            value = public_inputs.get(key)
            if value:
                triples.append(
                    {"subject": proof_node, "predicate": key, "object": str(value)}
                )
    return [triple for triple in triples if triple["object"]]


def _graph_data_from_triples(
    triples: Sequence[Mapping[str, str]],
    *,
    graph_id: str,
    metadata: Mapping[str, Any],
) -> Any:
    if not triples:
        return None
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    return flogic_triples_to_graph_data(triples, graph_id=graph_id, metadata=metadata)


def _public_attestation_record(record: Mapping[str, Any]) -> dict[str, Any]:
    proof = dict(record.get("proof") or {})
    public_inputs = dict(record.get("public_inputs") or {})
    return {
        "axiom_count": int(record.get("axiom_count") or 0),
        "error": record.get("error") or "",
        "proof_hash": record.get("proof_hash") or "",
        "proof_size_bytes": int(proof.get("size_bytes") or 0),
        "public_inputs": public_inputs,
        "source_id": record.get("source_id") or "",
        "theorem": record.get("theorem") or "",
        "verified": bool(record.get("verified")),
    }


def _document_id(prefix: str, text: str) -> str:
    digest = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


__all__ = ["ZkpAttestationBridgeAdapter"]
