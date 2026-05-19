"""Lightweight bridge layer for legal text -> formal logic IR workflows."""

from __future__ import annotations

from .registry import (
    DEFAULT_LEGAL_IR_BRIDGE_NAMES,
    LogicBridgeSpec,
    bridge_name_for_component,
    load_logic_bridge_adapter,
    logic_bridge_manifest,
    logic_bridge_spec,
    logic_bridge_specs,
)
from .multiview import (
    LegalIRTrainingTarget,
    MultiViewLegalIRReport,
    evaluate_legal_ir_multiview,
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
    "DEFAULT_LEGAL_IR_BRIDGE_NAMES",
    "GraphProjectionResult",
    "LegalIRDocument",
    "LegalIRTrainingTarget",
    "LogicBridgeSpec",
    "LogicIRView",
    "MultiViewLegalIRReport",
    "ProofGateResult",
    "RoundTripMetrics",
    "bridge_name_for_component",
    "evaluate_legal_ir_multiview",
    "load_logic_bridge_adapter",
    "logic_bridge_manifest",
    "logic_bridge_spec",
    "logic_bridge_specs",
]
