"""
Reasoning subsystem for logic module.

Provides core reasoning engines and proof execution.

Components:
- ProofExecutionEngine: Main proof execution engine
- DeontologicalReasoningEngine: Deontic reasoning engine
- LogicVerification: Logic verification system
"""

from .proof_execution_engine import ProofExecutionEngine
from .deontological_reasoning import DeontologicalReasoningEngine
from .logic_verification import LogicVerifier
from .hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    HammerGoal,
    HammerPipeline,
    HammerPremise,
    HammerStatus,
    HammerVerification,
    hammer_prove,
)
from .hammer_backends import (
    HAMMER_BACKEND_HEALTH_SCHEMA_VERSION,
    HammerBackendHealth,
    HammerBackendSpec,
    backend_health_for_runners,
    check_hammer_backend_availability,
    check_hammer_backend_health,
    default_hammer_backend_specs,
    default_hammer_subprocess_backends,
    hammer_backend_health_summary,
    hammer_backend_specs_by_name,
    lazy_install_hammer_backend,
)
from .hammer_guidance import (
    HAMMER_GUIDANCE_SCHEMA_VERSION,
    HammerGuidanceArtifact,
    hammer_guidance_artifact_from_result,
)
from .legal_ir_hammer import (
    LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION,
    LegalIRHammerConfig,
    LegalIRHammerReport,
    LegalIRHammerRunner,
    run_legal_ir_hammer,
)
from .legal_ir_obligations import (
    LEGAL_IR_OBLIGATION_SCHEMA_VERSION,
    LegalIRProofObligation,
    generate_legal_ir_proof_obligations,
)
from .legal_ir_premises import (
    LEGAL_IR_PREMISE_LIBRARY_VERSION,
    default_legal_ir_premises,
    export_legal_ir_premises,
)
from .legal_ir_verified_gap_repairs import (
    LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION,
    LegalIRVerifiedGapRepair,
    generate_verified_legal_ir_gap_repairs,
)

__all__ = [
    'ProofExecutionEngine',
    'DeontologicalReasoningEngine',
    'LogicVerifier',
    'CallableHammerBackendRunner',
    'HammerBackendResult',
    'HammerBackendStatus',
    'HammerGoal',
    'HammerPipeline',
    'HammerPremise',
    'HammerStatus',
    'HammerVerification',
    'HAMMER_GUIDANCE_SCHEMA_VERSION',
    'HammerGuidanceArtifact',
    'hammer_guidance_artifact_from_result',
    'LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION',
    'LegalIRHammerConfig',
    'LegalIRHammerReport',
    'LegalIRHammerRunner',
    'run_legal_ir_hammer',
    'LEGAL_IR_OBLIGATION_SCHEMA_VERSION',
    'LegalIRProofObligation',
    'generate_legal_ir_proof_obligations',
    'LEGAL_IR_PREMISE_LIBRARY_VERSION',
    'default_legal_ir_premises',
    'export_legal_ir_premises',
    'LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION',
    'LegalIRVerifiedGapRepair',
    'generate_verified_legal_ir_gap_repairs',
    'hammer_prove',
    'HAMMER_BACKEND_HEALTH_SCHEMA_VERSION',
    'HammerBackendHealth',
    'HammerBackendSpec',
    'backend_health_for_runners',
    'check_hammer_backend_availability',
    'check_hammer_backend_health',
    'default_hammer_backend_specs',
    'default_hammer_subprocess_backends',
    'hammer_backend_health_summary',
    'hammer_backend_specs_by_name',
    'lazy_install_hammer_backend',
]
