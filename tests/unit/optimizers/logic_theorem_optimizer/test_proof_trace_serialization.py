"""Tests for canonical proof trace serialization."""

from __future__ import annotations

import json

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.additional_provers import (
    ProverResult,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_trace import (
    proof_trace_to_json,
    serialize_aggregated_proof_trace,
    serialize_dataclass_like,
    serialize_prover_result_trace,
    write_proof_trace_json,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
    AggregatedProverResult,
    ProverStatus,
    ProverVerificationResult,
)


def test_serialize_aggregated_proof_trace_has_canonical_keys() -> None:
    aggregated = AggregatedProverResult(
        overall_valid=True,
        confidence=0.91,
        prover_results=[
            ProverVerificationResult(
                prover_name="z3",
                status=ProverStatus.VALID,
                is_valid=True,
                confidence=0.95,
                proof_time=0.012,
                details={"model": "sat"},
                error_message=None,
            )
        ],
        agreement_rate=1.0,
        verified_by=["z3"],
    )

    trace = serialize_aggregated_proof_trace(
        statement={"predicate": "implies", "args": ["P", "Q"]},
        aggregated=aggregated,
        session_id="logic-sess-001",
        metadata={"domain": "legal"},
    )

    assert trace["schema"] == "logic_theorem_optimizer.proof_trace"
    assert trace["schema_version"] == "1.0"
    assert trace["session_id"] == "logic-sess-001"
    assert trace["overall_valid"] is True
    assert trace["confidence"] == 0.91
    assert trace["agreement_rate"] == 1.0
    assert trace["verified_by"] == ["z3"]
    assert len(trace["prover_results"]) == 1
    assert trace["prover_results"][0]["status"] == "valid"


def test_serialize_prover_result_trace_is_json_serializable() -> None:
    result = ProverResult(
        prover_name="vampire",
        is_proved=False,
        confidence=0.0,
        proof_time=1.23,
        proof_output="SZS status CounterSatisfiable",
        proof_certificate=None,
        error_message=None,
        timeout=False,
        metadata={"format": "fof"},
    )
    trace = serialize_prover_result_trace(
        formula="fof(goal, conjecture, p=>q).",
        result=result,
        session_id="logic-sess-002",
    )

    payload = proof_trace_to_json(trace)
    parsed = json.loads(payload)
    assert parsed["schema"] == "logic_theorem_optimizer.proof_trace"
    assert parsed["prover_result"]["prover_name"] == "vampire"
    assert parsed["prover_result"]["metadata"]["format"] == "fof"


def test_write_proof_trace_json_writes_file(tmp_path) -> None:
    trace = {
        "schema": "logic_theorem_optimizer.proof_trace",
        "schema_version": "1.0",
        "timestamp": "2026-02-24T00:00:00+00:00",
    }
    out = write_proof_trace_json(trace, tmp_path / "proof_trace.json")
    written = out.read_text(encoding="utf-8")
    loaded = json.loads(written)
    assert loaded["schema"] == "logic_theorem_optimizer.proof_trace"


def test_serialize_dataclass_like_for_verification_result() -> None:
    result = ProverVerificationResult(
        prover_name="z3",
        status=ProverStatus.ERROR,
        is_valid=False,
        confidence=0.0,
        proof_time=0.2,
        details={},
        error_message="bridge failure",
    )
    serialized = serialize_dataclass_like(result)
    assert serialized["prover_name"] == "z3"
    assert serialized["status"] == "error"
    assert serialized["error_message"] == "bridge failure"
