"""Crypto IR formalization: sound lowering, portfolio routing, analysis receipts.

CRYPTOIR-G320 owns:

* :class:`~.obligations.FormalObligation` — model-bound security obligations
* :class:`~.compiler.LoweringContract` / :class:`~.compiler.ObligationCompiler`
* :class:`~.portfolio.ProverPortfolio` — bounded backend routing
* :class:`~.receipts.AnalysisReceipt` / :class:`~.receipts.ProofAuthority`

Opaque ``security_verification_condition`` JSON and prose never compile into an
executable logic family.  SAT answers are satisfiability-only authority.
"""

from __future__ import annotations

from .compiler import (
    COMPILER_VERSION,
    LOWERED_FORM_SCHEMA_VERSION,
    LOWERING_CONTRACT_SCHEMA_VERSION,
    LoweredForm,
    LoweringContract,
    LoweringStatus,
    ObligationCompiler,
    SoundnessScope,
    TheoryFragment,
    default_lowering_contracts,
)
from .obligations import (
    CRYPTO_IR_FORMALIZATION_DOMAIN,
    CRYPTO_IR_FORMALIZATION_SCHEMA_VERSION,
    FORMAL_OBLIGATION_SCHEMA_VERSION,
    NON_EXECUTABLE_LOGIC_FAMILIES,
    NON_EXECUTABLE_PAYLOAD_KINDS,
    OPAQUE_SECURITY_VERIFICATION_CONDITION,
    FormalObligation,
    FormalizationError,
    LogicFamily,
    ObligationPayloadKind,
    detect_payload_kind,
    is_executable_payload,
    logic_family_for_formal_target,
)
from .portfolio import (
    BACKEND_RESULT_SCHEMA_VERSION,
    NON_PROOF_BACKEND_STATUSES,
    PORTFOLIO_VERSION,
    BackendDescriptor,
    BackendResult,
    BackendStatus,
    CVC5SmtBackend,
    DatalogBackend,
    InjectedBackend,
    PortfolioRun,
    PropositionalBackend,
    ProverBackend,
    ProverPortfolio,
    TemporalMonitorBackend,
    Z3SmtBackend,
    default_backends,
)
from .receipts import (
    ANALYSIS_ATTEMPT_SCHEMA_VERSION,
    ANALYSIS_RECEIPT_SCHEMA_VERSION,
    AnalysisAttempt,
    AnalysisReceipt,
    AttemptOutcome,
    ProofAuthority,
    analysis_outcome_for_attempt,
    assert_sat_is_not_proof,
    build_analysis_receipt,
    proof_authority_for_outcome,
    satisfiability_outcome_for_attempt,
)

__all__ = [
    "ANALYSIS_ATTEMPT_SCHEMA_VERSION",
    "ANALYSIS_RECEIPT_SCHEMA_VERSION",
    "BACKEND_RESULT_SCHEMA_VERSION",
    "COMPILER_VERSION",
    "CRYPTO_IR_FORMALIZATION_DOMAIN",
    "CRYPTO_IR_FORMALIZATION_SCHEMA_VERSION",
    "FORMAL_OBLIGATION_SCHEMA_VERSION",
    "LOWERED_FORM_SCHEMA_VERSION",
    "LOWERING_CONTRACT_SCHEMA_VERSION",
    "NON_EXECUTABLE_LOGIC_FAMILIES",
    "NON_EXECUTABLE_PAYLOAD_KINDS",
    "NON_PROOF_BACKEND_STATUSES",
    "OPAQUE_SECURITY_VERIFICATION_CONDITION",
    "PORTFOLIO_VERSION",
    "AnalysisAttempt",
    "AnalysisReceipt",
    "AttemptOutcome",
    "BackendDescriptor",
    "BackendResult",
    "BackendStatus",
    "CVC5SmtBackend",
    "DatalogBackend",
    "FormalObligation",
    "FormalizationError",
    "InjectedBackend",
    "LogicFamily",
    "LoweredForm",
    "LoweringContract",
    "LoweringStatus",
    "ObligationCompiler",
    "ObligationPayloadKind",
    "PortfolioRun",
    "ProofAuthority",
    "PropositionalBackend",
    "ProverBackend",
    "ProverPortfolio",
    "SoundnessScope",
    "TemporalMonitorBackend",
    "TheoryFragment",
    "Z3SmtBackend",
    "analysis_outcome_for_attempt",
    "assert_sat_is_not_proof",
    "build_analysis_receipt",
    "default_backends",
    "default_lowering_contracts",
    "detect_payload_kind",
    "is_executable_payload",
    "logic_family_for_formal_target",
    "proof_authority_for_outcome",
    "satisfiability_outcome_for_attempt",
]
