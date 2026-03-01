"""Hybrid law reasoner package.

Provides a proof-producing architecture that combines:
- DCEC/dynamic deontic compliance checks,
- temporal FOL deadline/interval reasoning,
- provenance-preserving proof logging.
"""

from .engine import HybridLawReasoner
from .models import (
    IRReference,
    PROOF_SCHEMA_VERSION,
    ProofCertificate,
    ProofObject,
    ProofStep,
    SourceProvenance,
)
from .serialization import (
    SUPPORTED_CNL_VERSION,
    SUPPORTED_IR_VERSION,
    append_proof_to_store,
    load_legal_ir_from_json,
    load_legacy_logic_hybrid_fixture,
    load_proof_store,
    proof_from_dict,
    proof_to_dict,
    validate_contract_versions,
    write_proof_store,
)
from .optimizer_policy import (
    build_optimizer_acceptance_decision,
    build_optimizer_chain_plan,
    build_optimizer_onoff_benchmark,
)
from .kg_enrichment import (
    apply_kg_enrichment,
    build_kg_drift_assessment,
    build_entity_link_adapter,
    build_relation_enrichment_adapter,
    rollback_kg_enrichment,
)
from .prover_backends import (
    FirstOrderProverAdapter,
    MockFOLBackend,
    MockSMTBackend,
    ProverBackend,
    ProverBackendRegistry,
    ProverResult,
    SMTStyleProverAdapter,
    create_default_prover_registry,
)
from .shadow_mode import (
    build_canary_mode_decision,
    build_ga_gate_assessment,
    build_shadow_mode_audit,
)
from .hybrid_v2_blueprint import (
    DefaultKGHookV2,
    DefaultOptimizerHookV2,
    LegalIRV2,
    RegistryProverHookV2,
    parse_cnl_to_ir,
    normalize_ir,
    compile_ir_to_dcec,
    compile_ir_to_temporal_deontic_fol,
    generate_cnl_from_ir,
    run_v2_pipeline,
    run_v2_pipeline_with_defaults,
)
from .v2_cli import run_v2_cli

__all__ = [
    "HybridLawReasoner",
    "IRReference",
    "ProofCertificate",
    "ProofObject",
    "ProofStep",
    "SourceProvenance",
    "PROOF_SCHEMA_VERSION",
    "SUPPORTED_IR_VERSION",
    "SUPPORTED_CNL_VERSION",
    "validate_contract_versions",
    "load_legal_ir_from_json",
    "load_legacy_logic_hybrid_fixture",
    "load_proof_store",
    "write_proof_store",
    "append_proof_to_store",
    "proof_from_dict",
    "proof_to_dict",
    "build_canary_mode_decision",
    "build_ga_gate_assessment",
    "build_optimizer_acceptance_decision",
    "build_optimizer_chain_plan",
    "build_optimizer_onoff_benchmark",
    "build_entity_link_adapter",
    "build_relation_enrichment_adapter",
    "build_kg_drift_assessment",
    "apply_kg_enrichment",
    "rollback_kg_enrichment",
    "ProverResult",
    "ProverBackend",
    "ProverBackendRegistry",
    "SMTStyleProverAdapter",
    "FirstOrderProverAdapter",
    "MockSMTBackend",
    "MockFOLBackend",
    "create_default_prover_registry",
    "build_shadow_mode_audit",
    "DefaultOptimizerHookV2",
    "DefaultKGHookV2",
    "RegistryProverHookV2",
    "LegalIRV2",
    "parse_cnl_to_ir",
    "normalize_ir",
    "compile_ir_to_dcec",
    "compile_ir_to_temporal_deontic_fol",
    "generate_cnl_from_ir",
    "run_v2_pipeline",
    "run_v2_pipeline_with_defaults",
    "run_v2_cli",
]
