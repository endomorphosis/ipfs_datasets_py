"""Canonical proof-trace serialization for logic theorem optimizer.

This module provides a stable, JSON-friendly schema for prover outputs so
proof traces can be exported, diffed, and consumed by downstream tooling.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .additional_provers import ProverResult
from .prover_integration import AggregatedProverResult, ProverVerificationResult


def _utc_timestamp_iso() -> str:
    """Return current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _prover_verification_to_dict(result: ProverVerificationResult) -> Dict[str, Any]:
    """Serialize ProverVerificationResult to canonical dict shape."""
    status = result.status.value if hasattr(result.status, "value") else str(result.status)
    return {
        "prover_name": result.prover_name,
        "status": status,
        "is_valid": bool(result.is_valid),
        "confidence": float(result.confidence),
        "proof_time": float(result.proof_time),
        "details": dict(result.details or {}),
        "error_message": result.error_message,
    }


def _prover_result_to_dict(result: ProverResult) -> Dict[str, Any]:
    """Serialize ProverResult to canonical dict shape."""
    return {
        "prover_name": result.prover_name,
        "is_proved": bool(result.is_proved),
        "confidence": float(result.confidence),
        "proof_time": float(result.proof_time),
        "proof_output": result.proof_output,
        "proof_certificate": result.proof_certificate,
        "error_message": result.error_message,
        "timeout": bool(result.timeout),
        "metadata": dict(result.metadata or {}),
    }


def serialize_aggregated_proof_trace(
    statement: Any,
    aggregated: AggregatedProverResult,
    *,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Serialize an AggregatedProverResult into canonical proof-trace dict.

    Args:
        statement: Original statement that was verified.
        aggregated: Aggregated prover result.
        session_id: Optional session identifier.
        metadata: Optional caller metadata to attach at top level.

    Returns:
        Canonical proof-trace dictionary.
    """
    prover_results = [
        _prover_verification_to_dict(item) for item in aggregated.prover_results
    ]
    return {
        "schema": "logic_theorem_optimizer.proof_trace",
        "schema_version": "1.0",
        "timestamp": _utc_timestamp_iso(),
        "session_id": session_id,
        "statement": statement,
        "overall_valid": bool(aggregated.overall_valid),
        "confidence": float(aggregated.confidence),
        "agreement_rate": float(aggregated.agreement_rate),
        "verified_by": list(aggregated.verified_by),
        "prover_results": prover_results,
        "metadata": dict(metadata or {}),
    }


def serialize_prover_result_trace(
    formula: str,
    result: ProverResult,
    *,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Serialize a single additional-prover result into canonical trace dict."""
    return {
        "schema": "logic_theorem_optimizer.proof_trace",
        "schema_version": "1.0",
        "timestamp": _utc_timestamp_iso(),
        "session_id": session_id,
        "formula": formula,
        "prover_result": _prover_result_to_dict(result),
        "metadata": dict(metadata or {}),
    }


def proof_trace_to_json(trace: Dict[str, Any], *, indent: int = 2) -> str:
    """Serialize canonical proof trace to deterministic JSON string."""
    return json.dumps(trace, indent=indent, sort_keys=True, default=str)


def write_proof_trace_json(trace: Dict[str, Any], output_path: str | Path) -> Path:
    """Write proof trace JSON to disk and return resolved path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proof_trace_to_json(trace) + "\n", encoding="utf-8")
    return path.resolve()


def serialize_dataclass_like(obj: Any) -> Dict[str, Any]:
    """Best-effort serialization helper for dataclass-based proof artifacts."""
    if is_dataclass(obj):
        return {
            key: value.value if hasattr(value, "value") else value
            for key, value in obj.__dict__.items()
        }
    if isinstance(obj, dict):
        return dict(obj)
    return {"value": str(obj)}

