"""Lightweight bridge layer for legal text -> formal logic IR workflows."""

from __future__ import annotations

from .registry import (
    LogicBridgeSpec,
    bridge_name_for_component,
    load_logic_bridge_adapter,
    logic_bridge_manifest,
    logic_bridge_spec,
    logic_bridge_specs,
)
from .types import (
    BridgeEvaluationReport,
    GraphProjectionResult,
    LegalIRDocument,
    LogicIRView,
    ProofGateResult,
    RoundTripMetrics,
)

__all__ = [
    "BridgeEvaluationReport",
    "GraphProjectionResult",
    "LegalIRDocument",
    "LogicBridgeSpec",
    "LogicIRView",
    "ProofGateResult",
    "RoundTripMetrics",
    "bridge_name_for_component",
    "load_logic_bridge_adapter",
    "logic_bridge_manifest",
    "logic_bridge_spec",
    "logic_bridge_specs",
]
