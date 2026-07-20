"""ITP hammer pipeline package.

This package hosts the deterministic, auditable "hammer" pipeline that
selects premises from a content-addressed corpus, translates supported goals
to TPTP/SMT-LIB, runs a policy-controlled solver portfolio, and reconstructs
the result inside the originating Interactive Theorem Prover (ITP).

The trust contract and result schema (versioned request, premise,
translation, solver-attempt, proof-candidate, reconstruction,
environment-lock, and final-result records) live in :mod:`.models`. See
``docs/logic/itp_hammer_contract.md`` for the full narrative specification.

The content-addressed premise corpus and theorem manifest (declared corpus
sources, ingested theorem entries with normalized-statement digests and
license metadata, and the versioned ``corpus_revision`` threaded through
every hammer result) lives in :mod:`.corpus`. See
``docs/logic/itp_hammer_corpus.md`` for the full narrative specification.

The deterministic premise selection baseline (goal symbol/type/import
feature extraction, a one-hop dependency-graph proximity signal, and
stable, bounded ``top_k`` ranking with an explicit exclusion reason for
every non-selected candidate) lives in :mod:`.premise_selection`. See
``docs/logic/itp_hammer_premise_selection.md`` for the full narrative
specification.

The optional, opt-in learned/graph-based premise selector (a pinned,
content-addressed :class:`~.learned_selector.LearnedModelArtifact`,
reproducible feature extraction that extends the HAMMER-004 baseline's own
symbol/type/import/graph features, and a gated
:func:`~.learned_selector.select_premises_gated` entry point that always
falls back to the deterministic baseline when the learned selector is not
opted in, denied by policy, or its model is missing, mismatched, or fails)
lives in :mod:`.learned_selector`. See
``docs/logic/itp_hammer_learned_selection.md`` for the full narrative
specification.

The native ITP frontend adapters (a common protocol capturing the exact
goal, local hypotheses, imports, universe/type context, source position,
target ITP version, and native reconstruction command, plus one concrete
adapter per :class:`ITPKind` and structured capability evidence for
unavailable frontends) live in :mod:`.frontends`.

The typed translation to TPTP/SMT-LIB (explicit monomorphization, lambda
elimination/lifting, and type encodings, with a persisted translation map
and obligations for every transformed construct) lives in
:mod:`.translation`, :mod:`.tptp`, and :mod:`.smtlib`.

The policy-controlled, parallel Z3/CVC5/Vampire/E solver portfolio executor
lives in :mod:`.portfolio`, governed by the allowlisted solver policy
(per-solver time/CPU/memory budgets, executable-path resolution, a
process-count budget, and a cancellation-budget switch) in :mod:`.policy`.
Every attempt is captured as an untrusted
:class:`~.models.SolverAttemptRecord` plus out-of-band
:class:`~.portfolio.SolverAttemptEvidence` (exact command, input digest,
raw stdout/stderr, solver trace) — never as a verified result.

Normalizing the raw, solver-specific evidence produced by that portfolio
(TSTP/TPTP derivation listings, SMT-LIB unsat-core/model s-expressions) into
a single, content-addressed record — proofs decomposed into structural
:class:`~.provenance.ProofStep` entries, unsat cores and models/
counterexamples cross-referenced against caller-supplied premise ids and the
HAMMER-007 translation map, and a hard restriction to only ever recommend
``candidate``/``counterexample``/``unknown`` (never ``verified``) for a
malformed, absent, or unsupported trace — lives in :mod:`.provenance`.

Reconstructing a genuine native tactic/proof term from that normalized,
*still-untrusted* candidate evidence and independently checking it with the
target ITP's own kernel — in a pinned, versioned environment, storing the
checked source, kernel stdout/stderr, exit status, and digest — lives in
:mod:`.reconstruction` and its per-ITP :mod:`.reconstructors` package. This
is the *only* place a hammer run can be promoted to
:attr:`~.models.HammerResultStatus.VERIFIED`; that invariant is enforced
independently by :meth:`~.models.HammerResult.validate`.

On a translation, search, or reconstruction failure, the recovery pipeline
in :mod:`.fallbacks` first tries an explicitly operator-enabled native
automation attempt (reusing HAMMER-010's own reconstructor machinery with a
synthetic, empty-premise candidate — no untrusted solver is involved), and
otherwise returns a bounded :class:`~.fallbacks.DecompositionPlan` of
native-structural and/or policy-gated, redacted, human-reviewed
LLM-suggested subgoals, each requiring its own independent native kernel
check before it may ever be marked verified. See
``docs/logic/itp_hammer_failure_policy.md`` for the full narrative
specification.

Bundling every one of those records (the canonical request, selected
premises, translation artifacts, solver candidates, reconstruction sources,
environment lock, and verification outcome) plus their out-of-band evidence
into one coherent, content-addressed, replayable :class:`~.receipts.
HammerReceipt`, and persisting it through an IPFS-aware
:class:`~.receipts.ReceiptStore` with a local-disk fallback and a redacted,
credential-and-private-theorem-source-scrubbed publishable view, lives in
:mod:`.receipts`. See ``docs/logic/itp_hammer_receipts.md`` for the full
narrative specification.

:mod:`.models`, :mod:`.corpus`, :mod:`.premise_selection`,
:mod:`.frontends`, :mod:`.translation`/:mod:`.tptp`/:mod:`.smtlib`,
:mod:`.policy`/:mod:`.portfolio`, :mod:`.provenance`,
:mod:`.reconstruction`/:mod:`.reconstructors`, :mod:`.fallbacks`, and
:mod:`.receipts` are implemented so far; later taskboard items add governed
MCP/CLI operations described in
``docs/logic/itp_hammer_taskboard.todo.md``.
"""

from __future__ import annotations

from .corpus import (
    CorpusError,
    CorpusManifest,
    CorpusRevisionMismatchError,
    CorpusSource,
    CorpusSourceConflictError,
    DuplicateTheoremIdentityError,
    TheoremEntry,
    UndeclaredCorpusSourceError,
    compute_content_digest,
    compute_statement_digest,
    normalize_statement,
    verify_hammer_result_corpus,
)
from .models import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    EnvironmentLockRecord,
    HammerPolicy,
    HammerRequest,
    HammerResult,
    HammerResultStatus,
    ITPKind,
    PremiseRecord,
    ProofCandidateRecord,
    ReconstructionRecord,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
)
from .premise_selection import (
    DETERMINISTIC_BASELINE_METHOD,
    ExcludedPremise,
    GoalFeatures,
    InvalidTopKError,
    PremiseExclusionReason,
    PremiseSelectionError,
    PremiseSelectionResult,
    PremiseSelectionWeights,
    ScoredCandidate,
    extract_symbols,
    extract_types,
    score_candidates,
    select_premises,
    select_premises_for_theorem,
)
from .learned_selector import (
    DEFAULT_GRAPH_SELECTOR_MODEL_ID,
    LEARNED_FEATURE_VERSION,
    LEARNED_SELECTION_METHOD_PREFIX,
    LearnedModelArtifact,
    LearnedSelectionResult,
    LearnedSelectorConfig,
    LearnedSelectorConfigError,
    LearnedSelectorError,
    ModelArtifactError,
    ModelDigestMismatchError,
    SelectorFallbackReason,
    build_default_graph_selector_artifact,
    compute_model_digest,
    compute_recall_at_k,
    compute_reciprocal_rank,
    extract_learned_features,
    relevant_theorem_ids_by_import_overlap,
    score_candidates_learned,
    score_with_model,
    select_premises_for_theorem_gated,
    select_premises_gated,
)
from .frontends import (
    CapabilityEvidence,
    CoqFrontend,
    FrontendUnavailableError,
    GoalCaptureError,
    GoalSnapshot,
    ITPFrontend,
    IsabelleFrontend,
    LeanFrontend,
    LocalHypothesis,
    SourcePosition,
    UniverseContext,
    get_frontend,
    iter_frontends,
)
from .translation import (
    And,
    App,
    BoolLit,
    Const,
    DependentTypeRef,
    Eq,
    Exists,
    Forall,
    FunctionTypeRef,
    Iff,
    Implies,
    Lambda,
    LambdaLiftedDefinition,
    LambdaParam,
    MalformedTermError,
    Not,
    Opaque,
    Or,
    PROP_SORT,
    SortRef,
    Term,
    TranslationContext,
    TranslationError,
    TranslationMap,
    TranslationMapEntry,
    TypeRef,
    TypeVarRef,
    UnsupportedConstructError,
    Var,
)
from . import tptp as tptp
from . import smtlib as smtlib
from .policy import (
    PolicyError,
    PortfolioPolicy,
    SolverBudget,
    SolverSpec,
    known_solver_names,
    solver_spec,
)
from .portfolio import (
    PortfolioAttemptSpec,
    PortfolioRunResult,
    SolverAttemptEvidence,
    SolverPortfolio,
    SolverProcessOutcome,
    build_solver_input_text,
    parse_smtlib_verdict,
    parse_tptp_verdict,
    run_bounded_solver_process,
)
from .provenance import (
    ALLOWED_RECOMMENDED_STATUSES,
    EvidenceKind,
    MalformedEvidenceError,
    ModelBinding,
    NormalizedEvidence,
    NormalizedModel,
    NormalizedUnsatCore,
    ProofStep,
    aggregate_recommended_status,
    build_proof_candidate_record,
    normalize_certificate,
    normalize_portfolio_run,
    normalize_solver_evidence,
    parse_all_sexprs,
    parse_smtlib_model,
    parse_smtlib_unsat_core,
    parse_tptp_model,
    parse_tstp_proof,
    unsat_core_from_proof_steps,
)
from .reconstruction import (
    DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS,
    KernelUnavailableError,
    ReconstructionEvidence,
    ReconstructionInputError,
    Reconstructor,
    build_environment_lock,
    build_reconstruction_records,
    get_reconstructor,
    iter_reconstructors,
    reconstruct_candidate,
    require_matching_ids,
    require_single_marker,
    run_kernel_check,
    select_hypothesis_names,
)
from .reconstructors import (
    CoqReconstructor,
    IsabelleReconstructor,
    LeanReconstructor,
)
from .fallbacks import (
    DecompositionPlan,
    DecompositionSource,
    DecompositionSubgoal,
    FallbackInputError,
    FallbackOutcome,
    FallbackTrigger,
    NativeAutomationAttempt,
    ReviewStatus,
    SubgoalStatus,
    attempt_fallback,
    attempt_native_automation,
    build_decomposition_plan,
    redact_llm_text,
    review_decomposition_subgoal,
    split_top_level_conjuncts,
    verify_decomposition_subgoal,
)
from .receipts import (
    HammerReceipt,
    PersistResult,
    ReceiptError,
    ReceiptNotFoundError,
    ReceiptStorageError,
    ReceiptStore,
    ReceiptValidationError,
    StorageLocation,
    build_publishable_view,
    compute_receipt_digest,
    default_receipt_store_root,
    persist_hammer_receipt,
    scrub_credential_text,
)

__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "ALLOWED_RECOMMENDED_STATUSES",
    "And",
    "App",
    "BoolLit",
    "CapabilityEvidence",
    "Const",
    "CorpusError",
    "CorpusManifest",
    "CorpusRevisionMismatchError",
    "CorpusSource",
    "CorpusSourceConflictError",
    "CoqFrontend",
    "CoqReconstructor",
    "DEFAULT_GRAPH_SELECTOR_MODEL_ID",
    "DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS",
    "DETERMINISTIC_BASELINE_METHOD",
    "DecompositionPlan",
    "DecompositionSource",
    "DecompositionSubgoal",
    "DependentTypeRef",
    "DuplicateTheoremIdentityError",
    "Eq",
    "EnvironmentLockRecord",
    "EvidenceKind",
    "ExcludedPremise",
    "Exists",
    "FallbackInputError",
    "FallbackOutcome",
    "FallbackTrigger",
    "Forall",
    "FrontendUnavailableError",
    "FunctionTypeRef",
    "GoalCaptureError",
    "GoalFeatures",
    "GoalSnapshot",
    "HammerPolicy",
    "HammerReceipt",
    "HammerRequest",
    "HammerResult",
    "HammerResultStatus",
    "ITPFrontend",
    "ITPKind",
    "Iff",
    "Implies",
    "InvalidTopKError",
    "IsabelleFrontend",
    "IsabelleReconstructor",
    "KernelUnavailableError",
    "LEARNED_FEATURE_VERSION",
    "LEARNED_SELECTION_METHOD_PREFIX",
    "Lambda",
    "LambdaLiftedDefinition",
    "LambdaParam",
    "LearnedModelArtifact",
    "LearnedSelectionResult",
    "LearnedSelectorConfig",
    "LearnedSelectorConfigError",
    "LearnedSelectorError",
    "LeanFrontend",
    "LeanReconstructor",
    "LocalHypothesis",
    "MalformedEvidenceError",
    "MalformedTermError",
    "ModelArtifactError",
    "ModelBinding",
    "ModelDigestMismatchError",
    "NativeAutomationAttempt",
    "Not",
    "NormalizedEvidence",
    "NormalizedModel",
    "NormalizedUnsatCore",
    "Opaque",
    "Or",
    "PROP_SORT",
    "PersistResult",
    "PolicyError",
    "PortfolioAttemptSpec",
    "PortfolioPolicy",
    "PortfolioRunResult",
    "PremiseExclusionReason",
    "PremiseRecord",
    "PremiseSelectionError",
    "PremiseSelectionResult",
    "PremiseSelectionWeights",
    "ProofCandidateRecord",
    "ProofStep",
    "ReceiptError",
    "ReceiptNotFoundError",
    "ReceiptStorageError",
    "ReceiptStore",
    "ReceiptValidationError",
    "ReconstructionEvidence",
    "ReconstructionInputError",
    "ReconstructionRecord",
    "Reconstructor",
    "ReviewStatus",
    "ScoredCandidate",
    "SelectorFallbackReason",
    "SolverAttemptEvidence",
    "SolverAttemptRecord",
    "SolverBudget",
    "SolverPortfolio",
    "SolverProcessOutcome",
    "SolverSpec",
    "SolverVerdict",
    "SortRef",
    "SourcePosition",
    "StorageLocation",
    "SubgoalStatus",
    "Term",
    "TheoremEntry",
    "TranslationContext",
    "TranslationError",
    "TranslationMap",
    "TranslationMapEntry",
    "TranslationRecord",
    "TranslationStatus",
    "TranslationTarget",
    "TypeRef",
    "TypeVarRef",
    "UndeclaredCorpusSourceError",
    "UniverseContext",
    "UnsupportedConstructError",
    "Var",
    "aggregate_recommended_status",
    "attempt_fallback",
    "attempt_native_automation",
    "build_decomposition_plan",
    "build_default_graph_selector_artifact",
    "build_environment_lock",
    "build_proof_candidate_record",
    "build_publishable_view",
    "build_reconstruction_records",
    "build_solver_input_text",
    "compute_content_digest",
    "compute_model_digest",
    "compute_recall_at_k",
    "compute_receipt_digest",
    "compute_reciprocal_rank",
    "compute_statement_digest",
    "default_receipt_store_root",
    "extract_learned_features",
    "extract_symbols",
    "extract_types",
    "smtlib",
    "tptp",
    "get_frontend",
    "get_reconstructor",
    "iter_frontends",
    "iter_reconstructors",
    "known_solver_names",
    "normalize_certificate",
    "normalize_portfolio_run",
    "normalize_solver_evidence",
    "normalize_statement",
    "parse_all_sexprs",
    "parse_smtlib_model",
    "parse_smtlib_unsat_core",
    "parse_smtlib_verdict",
    "parse_tptp_model",
    "parse_tptp_verdict",
    "parse_tstp_proof",
    "persist_hammer_receipt",
    "reconstruct_candidate",
    "redact_llm_text",
    "relevant_theorem_ids_by_import_overlap",
    "require_matching_ids",
    "require_single_marker",
    "review_decomposition_subgoal",
    "run_bounded_solver_process",
    "run_kernel_check",
    "score_candidates",
    "score_candidates_learned",
    "score_with_model",
    "scrub_credential_text",
    "select_hypothesis_names",
    "select_premises",
    "select_premises_for_theorem",
    "select_premises_for_theorem_gated",
    "select_premises_gated",
    "solver_spec",
    "split_top_level_conjuncts",
    "unsat_core_from_proof_steps",
    "verify_decomposition_subgoal",
    "verify_hammer_result_corpus",
]
