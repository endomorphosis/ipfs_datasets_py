"""Isolated execution primitives for the legal logic pipeline benchmark.

This package deliberately lives outside :mod:`ipfs_datasets_py`: importing it
must never configure an optional backend or alter a production routing default.
The dependency-free contracts and versioned adapter boundary live here; later
goals inject optional backend handlers explicitly.  This package provides:

* every mutable path is below a caller-selected run directory;
* the smoke configuration is offline, shadow-only, and deterministic; and
* creating directories is an explicit operation, never an import side effect.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Final, Iterator

BENCHMARK_ID: Final = "hammer-symai-spacy-leanstral"
"""Stable identifier used in manifests and cache namespaces."""

SMOKE_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.smoke-manifest.v1"
)
"""Schema identifier for the deterministic package smoke manifest."""

DEFAULT_BENCHMARK_ROOT: Final = (
    Path("workspace") / "benchmarks" / BENCHMARK_ID
)
"""Base directory below which a required run id scopes all mutable data."""

SMOKE_VARIANTS: Final = ("A0", "A1", "A7", "A8")
"""Offline variants selected by the preregistered deterministic smoke stage."""

RUN_DIRECTORY_NAMES: Final = (
    "cache",
    "corpus",
    "objective_bundles",
    "receipts",
    "results",
    "state",
    "logs",
    "worktrees",
)
"""Complete set of mutable state and output directories for one run."""

_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def HSSLEV0009A31() -> str:
    """Return the objective evidence bound to this execution contract.

    The intentionally stable function name is an AST-verifiable receipt for
    HSSL-G000.  It makes the supervisor's evidence a code symbol rather than a
    prose-only mention in generated planning state.
    """

    return "isolated benchmark package and execution skeleton"


def _validate_run_id(run_id: str) -> str:
    """Return a safe run id or raise :class:`ValueError`.

    A run id becomes one path component and a cache-namespace component, so
    absolute paths, traversal, whitespace, path separators, and empty values
    are rejected rather than normalized into a surprising destination.
    """

    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            "run_id must be 1-128 characters, start with an ASCII letter or "
            "digit, and contain only ASCII letters, digits, '.', '_', or '-'"
        )
    if run_id in {".", ".."}:
        raise ValueError("run_id must identify a run, not a path traversal")
    return run_id


def _coerce_benchmark_root(benchmark_root: str | Path) -> Path:
    """Return a usable base path while rejecting an accidental empty string."""

    if isinstance(benchmark_root, str) and not benchmark_root.strip():
        raise ValueError("benchmark_root must not be empty")
    return Path(benchmark_root)


@dataclass(frozen=True, slots=True)
class RunPaths:
    """All mutable filesystem locations allocated to one benchmark run.

    Construct instances with :meth:`for_run` so every member is guaranteed to
    be a direct descendant of ``<benchmark_root>/<run_id>``.  Merely creating a
    :class:`RunPaths` value does not touch the filesystem.
    """

    benchmark_root: Path
    run_id: str
    run_root: Path
    cache: Path
    corpus: Path
    objective_bundles: Path
    receipts: Path
    results: Path
    state: Path
    logs: Path
    worktrees: Path

    @classmethod
    def for_run(
        cls,
        run_id: str,
        *,
        benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
    ) -> "RunPaths":
        """Build a run-scoped path set without creating any directories."""

        safe_run_id = _validate_run_id(run_id)
        root = _coerce_benchmark_root(benchmark_root)
        run_root = root / safe_run_id
        children = {name: run_root / name for name in RUN_DIRECTORY_NAMES}
        return cls(
            benchmark_root=root,
            run_id=safe_run_id,
            run_root=run_root,
            **children,
        )

    def directories(self) -> Iterator[Path]:
        """Yield the run root followed by every defined child directory."""

        yield self.run_root
        for name in RUN_DIRECTORY_NAMES:
            yield getattr(self, name)

    def as_dict(self) -> dict[str, str]:
        """Return deterministic, JSON-ready path values keyed by purpose."""

        return {
            "run_root": self.run_root.as_posix(),
            **{
                name: getattr(self, name).as_posix()
                for name in RUN_DIRECTORY_NAMES
            },
        }

    def materialize(self, *, mode: int = 0o700) -> None:
        """Create this run's private directories.

        Directory creation is intentionally explicit.  The default mode keeps
        potentially sensitive model traces and proof artifacts private on
        POSIX systems; existing directories are left intact.
        """

        if not 0 <= mode <= 0o777:
            raise ValueError("mode must be a valid permission mask")
        for directory in self.directories():
            directory.mkdir(mode=mode, parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class ExecutionDefaults:
    """Safe defaults shared by smoke runners and future stage adapters."""

    run_id: str
    benchmark_root: Path = DEFAULT_BENCHMARK_ROOT
    variants: tuple[str, ...] = SMOKE_VARIANTS
    shadow_only: bool = True
    network_enabled: bool = False
    model_calls_enabled: bool = False
    auto_merge: bool = False
    production_routing_changes: bool = False

    def __post_init__(self) -> None:
        _validate_run_id(self.run_id)
        object.__setattr__(
            self,
            "benchmark_root",
            _coerce_benchmark_root(self.benchmark_root),
        )
        object.__setattr__(self, "variants", tuple(self.variants))
        if not self.variants or any(
            not isinstance(variant, str) or not variant
            for variant in self.variants
        ):
            raise ValueError("variants must contain at least one nonempty id")
        if len(set(self.variants)) != len(self.variants):
            raise ValueError("variants must not contain duplicate ids")

    @property
    def paths(self) -> RunPaths:
        """Return the isolated path layout for this execution."""

        return RunPaths.for_run(
            self.run_id,
            benchmark_root=self.benchmark_root,
        )

    @property
    def cache_namespace(self) -> str:
        """Return a namespace that cannot be shared across run ids."""

        return f"{BENCHMARK_ID}/{self.run_id}"

    def smoke_manifest(self) -> dict[str, object]:
        """Build a deterministic, JSON-serializable smoke manifest.

        Volatile data such as timestamps, hostnames, process IDs, and random
        identifiers are intentionally absent.  Capability and revision
        identities belong to later versioned run records, not this package
        import smoke contract.
        """

        return {
            "schema": SMOKE_MANIFEST_SCHEMA,
            "benchmark_id": BENCHMARK_ID,
            "evidence": HSSLEV0009A31(),
            "run_id": self.run_id,
            "mode": "shadow" if self.shadow_only else "active",
            "variants": list(self.variants),
            "execution": {
                "network_enabled": self.network_enabled,
                "model_calls_enabled": self.model_calls_enabled,
                "auto_merge": self.auto_merge,
                "production_routing_changes": self.production_routing_changes,
            },
            "cache_namespace": self.cache_namespace,
            "paths": self.paths.as_dict(),
        }


def build_smoke_manifest(
    run_id: str,
    *,
    benchmark_root: str | Path = DEFAULT_BENCHMARK_ROOT,
) -> dict[str, object]:
    """Return the default deterministic manifest for ``run_id``."""

    return ExecutionDefaults(
        run_id=run_id,
        benchmark_root=_coerce_benchmark_root(benchmark_root),
    ).smoke_manifest()


def canonical_manifest_json(manifest: dict[str, object]) -> str:
    """Serialize a manifest canonically for storage or content hashing."""

    return json.dumps(
        manifest,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def manifest_sha256(manifest: dict[str, object]) -> str:
    """Return the SHA-256 digest of a canonical smoke manifest."""

    return hashlib.sha256(canonical_manifest_json(manifest).encode("utf-8")).hexdigest()


__all__ = [
    "BENCHMARK_ID",
    "DEFAULT_BENCHMARK_ROOT",
    "ExecutionDefaults",
    "HSSLEV0009A31",
    "RUN_DIRECTORY_NAMES",
    "RunPaths",
    "SMOKE_MANIFEST_SCHEMA",
    "SMOKE_VARIANTS",
    "build_smoke_manifest",
    "canonical_manifest_json",
    "manifest_sha256",
]

# The protocol module is side-effect-free and depends only on the required
# multiformats stack beyond the standard library.  These imports live at the
# end so it can reuse ``BENCHMARK_ID`` without creating an initialization cycle.
from .contracts import (  # noqa: E402
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
    CASE_RESULT_RECEIPT_SCHEMA,
    CASE_RESULT_SCHEMA,
    CaseResultRecord,
    CaseResultReceipt,
    DEFAULT_PROTOCOL,
    DEFAULT_PROTOCOL_SHA256,
    HSSLEV0103C72,
    HSSLEV0306C18,
    HSSLEV0357C0D,
    HSSLEV2007A42,
    BenchmarkProtocol,
    ProtocolContractError,
    ResourceLane,
    SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID,
    SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID,
    SEMANTIC_NORMALIZATION_V2_CID,
    SEMANTIC_PRODUCER_REGISTRY_V2_CID,
    SEMANTIC_PROJECTION_SCHEMA_V2,
    SEMANTIC_PROJECTION_SCHEMA_V2_CID,
    SEMANTIC_PROMPT_V2_CID,
    SEMANTIC_PROTOCOL_V2,
    SEMANTIC_PROTOCOL_V2_CID,
    SEMANTIC_RESPONSE_SCHEMA_V2,
    SEMANTIC_RESPONSE_SCHEMA_V2_CID,
    SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
    SemanticProjection,
    SemanticProtocolSpec,
    STAGE_PROVENANCE_SCHEMA,
    STAGE_RECORD_SCHEMA,
    StageName,
    StageProvenance,
    StageRecord,
    StageStatus,
    TELEMETRY_SCHEMA,
    TelemetryRecord,
    build_default_protocol,
)

__all__ += [
    "BenchmarkProtocol",
    "CAUSAL_PROOF_PROTOCOL_V2_CID",
    "CAUSAL_PROOF_VARIANT_PROFILE_V2_CID",
    "CASE_RESULT_RECEIPT_SCHEMA",
    "CASE_RESULT_SCHEMA",
    "CaseResultRecord",
    "CaseResultReceipt",
    "DEFAULT_PROTOCOL",
    "DEFAULT_PROTOCOL_SHA256",
    "HSSLEV0103C72",
    "HSSLEV0306C18",
    "HSSLEV0357C0D",
    "HSSLEV2007A42",
    "ProtocolContractError",
    "ResourceLane",
    "SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID",
    "SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID",
    "SEMANTIC_NORMALIZATION_V2_CID",
    "SEMANTIC_PRODUCER_REGISTRY_V2_CID",
    "SEMANTIC_PROJECTION_SCHEMA_V2",
    "SEMANTIC_PROJECTION_SCHEMA_V2_CID",
    "SEMANTIC_PROMPT_V2_CID",
    "SEMANTIC_PROTOCOL_V2",
    "SEMANTIC_PROTOCOL_V2_CID",
    "SEMANTIC_RESPONSE_SCHEMA_V2",
    "SEMANTIC_RESPONSE_SCHEMA_V2_CID",
    "SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID",
    "SemanticProjection",
    "SemanticProtocolSpec",
    "STAGE_PROVENANCE_SCHEMA",
    "STAGE_RECORD_SCHEMA",
    "StageName",
    "StageProvenance",
    "StageRecord",
    "StageStatus",
    "TELEMETRY_SCHEMA",
    "TelemetryRecord",
    "build_default_protocol",
]

# Adapters remain dependency-free.  These imports only expose constructors;
# optional stage packages are imported by explicit handlers supplied by a
# caller, never while importing this benchmark package.
from .adapters import (  # noqa: E402
    ADAPTER_SOURCE,
    ADAPTER_VERSION,
    CompilerAdapter,
    HammerAdapter,
    KernelAdapter,
    HSSLEV0310F79,
    HSSLEV0328B3A,
    HSSLEV0342A4C,
    LEANSTRAL_DRAFT_SCHEMA,
    LEANSTRAL_EVIDENCE_SCHEMA,
    LEANSTRAL_KERNEL_RESOURCE_CLASS,
    LEANSTRAL_MAX_CONTEXT_BYTES,
    LEANSTRAL_MAX_DRAFT_BYTES,
    LEANSTRAL_MAX_REPAIR_ATTEMPTS,
    LEANSTRAL_MODEL_RESOURCE_CLASS,
    LeanstralAdapterConfig,
    LeanstralAdapterContractError,
    LeanstralAdapter,
    PipelineResult,
    SPACY_EVIDENCE_SCHEMA,
    SPACY_EVIDENCE_SCHEMA_V2,
    SPACY_MAX_EVIDENCE_BYTES,
    SPACY_MAX_TEXT_BYTES,
    SpacyAdapter,
    SpacyAdapterConfig,
    SpacyAdapterMode,
    StageAdapter,
    StageArtifact,
    StageInvocation,
    StageOutput,
    StageRequest,
    StageTelemetry,
    STAGE_ORDER,
    SYMAI_EVIDENCE_SCHEMA,
    SYMAI_EVIDENCE_SCHEMA_V2,
    SYMAI_MAX_CANDIDATE_BYTES,
    SYMAI_MAX_LIST_ITEMS,
    SYMAI_MAX_RAW_OUTPUT_BYTES,
    SYMAI_MAX_RETRIES,
    SYMAI_MAX_TEXT_BYTES,
    SYMAI_PROMPT_SCHEMA,
    SYMAI_ROUTER_ENGINE,
    SEMANTIC_CONTEXT_SCHEMA_V2,
    SymaiAdapter,
    SymaiAdapterConfig,
    SymaiAdapterContractError,
    SymaiRecursiveRoutingError,
    VersionedStageAdapter,
    build_modal_semantic_projection_v2,
    build_default_adapters,
    run_stages,
)

__all__ += [
    "ADAPTER_SOURCE",
    "ADAPTER_VERSION",
    "CompilerAdapter",
    "HammerAdapter",
    "KernelAdapter",
    "HSSLEV0310F79",
    "HSSLEV0328B3A",
    "HSSLEV0342A4C",
    "LEANSTRAL_DRAFT_SCHEMA",
    "LEANSTRAL_EVIDENCE_SCHEMA",
    "LEANSTRAL_KERNEL_RESOURCE_CLASS",
    "LEANSTRAL_MAX_CONTEXT_BYTES",
    "LEANSTRAL_MAX_DRAFT_BYTES",
    "LEANSTRAL_MAX_REPAIR_ATTEMPTS",
    "LEANSTRAL_MODEL_RESOURCE_CLASS",
    "LeanstralAdapterConfig",
    "LeanstralAdapterContractError",
    "LeanstralAdapter",
    "PipelineResult",
    "SPACY_EVIDENCE_SCHEMA",
    "SPACY_EVIDENCE_SCHEMA_V2",
    "SPACY_MAX_EVIDENCE_BYTES",
    "SPACY_MAX_TEXT_BYTES",
    "SpacyAdapter",
    "SpacyAdapterConfig",
    "SpacyAdapterMode",
    "StageAdapter",
    "StageArtifact",
    "StageInvocation",
    "StageOutput",
    "StageRequest",
    "StageTelemetry",
    "STAGE_ORDER",
    "SYMAI_EVIDENCE_SCHEMA",
    "SYMAI_EVIDENCE_SCHEMA_V2",
    "SYMAI_MAX_CANDIDATE_BYTES",
    "SYMAI_MAX_LIST_ITEMS",
    "SYMAI_MAX_RAW_OUTPUT_BYTES",
    "SYMAI_MAX_RETRIES",
    "SYMAI_MAX_TEXT_BYTES",
    "SYMAI_PROMPT_SCHEMA",
    "SYMAI_ROUTER_ENGINE",
    "SEMANTIC_CONTEXT_SCHEMA_V2",
    "SymaiAdapter",
    "SymaiAdapterConfig",
    "SymaiAdapterContractError",
    "SymaiRecursiveRoutingError",
    "VersionedStageAdapter",
    "build_modal_semantic_projection_v2",
    "build_default_adapters",
    "run_stages",
]

# Capability/worktree contracts are standard-library-only and perform no
# probing or filesystem access at import time.
from .capabilities import (  # noqa: E402
    CAPABILITY_INVENTORY_SCHEMA,
    REQUIRED_CAPABILITY_KINDS,
    WORKTREE_SAFETY_SCHEMA,
    CapabilityContractError,
    CapabilityInventory,
    CapabilityKind,
    CapabilityRecord,
    CapabilityStatus,
    CapabilityUnavailableError,
    HSSLEV0118D14,
    HSSLEV0125F83,
    WorktreeSafetyReceipt,
    prepare_isolated_worktree,
    probe_runtime_capabilities,
    require_capabilities,
)

__all__ += [
    "CAPABILITY_INVENTORY_SCHEMA",
    "REQUIRED_CAPABILITY_KINDS",
    "WORKTREE_SAFETY_SCHEMA",
    "CapabilityContractError",
    "CapabilityInventory",
    "CapabilityKind",
    "CapabilityRecord",
    "CapabilityStatus",
    "CapabilityUnavailableError",
    "HSSLEV0118D14",
    "HSSLEV0125F83",
    "WorktreeSafetyReceipt",
    "prepare_isolated_worktree",
    "probe_runtime_capabilities",
    "require_capabilities",
]

# Live runtime construction is explicit and remains side-effect free until a
# stage is invoked.
from .runtime import (  # noqa: E402
    CAUSAL_PROOF_HAMMER_FAILURE_CODES_V2,
    COMPILED_OBLIGATION_SCHEMA,
    KERNEL_RECEIPT_SCHEMA,
    CausalKernelCheck,
    CausalProofCandidate,
    CausalProofFailure,
    CausalProofGraphController,
    CausalProofGraphResult,
    CompiledObligation,
    HSSLEV1142E95,
    HSSLEV1207F16,
    HSSLEV1305A27,
    LiveRuntime,
    NativeKernelRunner,
    RuntimeBackendHandlers,
    RuntimeBindingError,
    build_live_adapters,
    build_live_runtime,
    compile_reviewed_obligation,
)

__all__ += [
    "CAUSAL_PROOF_HAMMER_FAILURE_CODES_V2",
    "COMPILED_OBLIGATION_SCHEMA",
    "KERNEL_RECEIPT_SCHEMA",
    "CausalKernelCheck",
    "CausalProofCandidate",
    "CausalProofFailure",
    "CausalProofGraphController",
    "CausalProofGraphResult",
    "CompiledObligation",
    "HSSLEV1142E95",
    "HSSLEV1207F16",
    "HSSLEV1305A27",
    "LiveRuntime",
    "NativeKernelRunner",
    "RuntimeBackendHandlers",
    "RuntimeBindingError",
    "build_live_adapters",
    "build_live_runtime",
    "compile_reviewed_obligation",
]

# Corpus records are dependency-free and load no fixture data until a caller
# explicitly asks for it.
from .cases import (  # noqa: E402
    CASE_SCHEMA,
    CORPUS_ID,
    CORPUS_MANIFEST_SCHEMA,
    DEFAULT_CORPUS_PATH,
    DEFAULT_MANIFEST_PATH,
    FROZEN_SPLIT_INTEGRITY_SHA256,
    FROZEN_SPLIT_SHA256,
    HOLDOUT_ACCESS_SCHEMA,
    REPLACEMENT_HOLDOUT_LEDGER_AUTHORITY_SCHEMA,
    REPLACEMENT_HOLDOUT_PROTOCOL_KEYS,
    REPLACEMENT_HOLDOUT_SEAL_SCHEMA,
    SPLIT_INTEGRITY_SCHEMA,
    SPLIT_MANIFEST_SCHEMA,
    BenchmarkCase,
    CorpusContractError,
    CorpusManifest,
    Difficulty,
    ExpectedClass,
    HSSLEV0201B64,
    HSSLEV0232D57,
    HoldoutAccessAudit,
    ReviewAttestation,
    ReplacementHoldoutSeal,
    ReviewedCorpus,
    SplitIntegrityManifest,
    SplitManifest,
    build_split_integrity_manifest,
    case_sha256,
    corpus_manifest_sha256,
    frozen_holdout_manifest,
    load_corpus,
    load_manifest,
    load_reviewed_corpus,
    load_unsealed_pilot_development,
    normalize_source_text,
    replacement_holdout_ledger_authority_cid,
    validate_replacement_holdout_external_path,
    validate_holdout_access_log,
    validate_holdout_prompt_isolation,
    validate_split_integrity,
)

__all__ += [
    "CASE_SCHEMA",
    "CORPUS_ID",
    "CORPUS_MANIFEST_SCHEMA",
    "DEFAULT_CORPUS_PATH",
    "DEFAULT_MANIFEST_PATH",
    "FROZEN_SPLIT_INTEGRITY_SHA256",
    "FROZEN_SPLIT_SHA256",
    "HOLDOUT_ACCESS_SCHEMA",
    "REPLACEMENT_HOLDOUT_LEDGER_AUTHORITY_SCHEMA",
    "REPLACEMENT_HOLDOUT_PROTOCOL_KEYS",
    "REPLACEMENT_HOLDOUT_SEAL_SCHEMA",
    "SPLIT_INTEGRITY_SCHEMA",
    "SPLIT_MANIFEST_SCHEMA",
    "BenchmarkCase",
    "CorpusContractError",
    "CorpusManifest",
    "Difficulty",
    "ExpectedClass",
    "HSSLEV0201B64",
    "HSSLEV0232D57",
    "HoldoutAccessAudit",
    "ReviewAttestation",
    "ReplacementHoldoutSeal",
    "ReviewedCorpus",
    "SplitIntegrityManifest",
    "SplitManifest",
    "build_split_integrity_manifest",
    "case_sha256",
    "corpus_manifest_sha256",
    "frozen_holdout_manifest",
    "load_corpus",
    "load_manifest",
    "load_reviewed_corpus",
    "load_unsealed_pilot_development",
    "normalize_source_text",
    "replacement_holdout_ledger_authority_cid",
    "validate_replacement_holdout_external_path",
    "validate_holdout_access_log",
    "validate_holdout_prompt_isolation",
    "validate_split_integrity",
]

# Existing-fixture adapters preserve upstream identities and expected-result
# provenance.  Importing the contract does not read the manifest or sources;
# loading remains an explicit caller operation.
from .fixture_import import (  # noqa: E402
    DEFAULT_IMPORT_MANIFEST_PATH,
    FIXTURE_IMPORT_MANIFEST_SCHEMA,
    FIXTURE_IMPORT_SCHEMA,
    FROZEN_IMPORT_MANIFEST_SHA256,
    FixtureFamily,
    FixtureImportError,
    FixtureImportManifest,
    FixtureImportSpec,
    HSSLEV0217E25,
    ImportedFixture,
    ImportedFixtureSet,
    load_fixture_imports,
)

__all__ += [
    "DEFAULT_IMPORT_MANIFEST_PATH",
    "FIXTURE_IMPORT_MANIFEST_SCHEMA",
    "FIXTURE_IMPORT_SCHEMA",
    "FROZEN_IMPORT_MANIFEST_SHA256",
    "FixtureFamily",
    "FixtureImportError",
    "FixtureImportManifest",
    "FixtureImportSpec",
    "HSSLEV0217E25",
    "ImportedFixture",
    "ImportedFixtureSet",
    "load_fixture_imports",
]

# Adversarial controls are also dependency-free and side-effect-free on
# import.  The fixture suite is authenticated only when explicitly loaded.
from .adversarial import (  # noqa: E402
    CONTROL_MANIFEST_SCHEMA,
    CONTROL_SCHEMA,
    REQUIRED_CONTROL_KINDS,
    AdversarialContractError,
    AdversarialControl,
    CandidateAssessment,
    CandidateClaim,
    CandidateDisposition,
    ControlKind,
    ControlManifest,
    ControlSuite,
    HSSLEV0224A96,
    classify_candidate,
    gate_candidate,
    load_control_suite,
    validate_control_coverage,
)

__all__ += [
    "CONTROL_MANIFEST_SCHEMA",
    "CONTROL_SCHEMA",
    "REQUIRED_CONTROL_KINDS",
    "AdversarialContractError",
    "AdversarialControl",
    "CandidateAssessment",
    "CandidateClaim",
    "CandidateDisposition",
    "ControlKind",
    "ControlManifest",
    "ControlSuite",
    "HSSLEV0224A96",
    "classify_candidate",
    "gate_candidate",
    "load_control_suite",
    "validate_control_coverage",
]

# The source-only semantic-v2 flow is public while all filesystem mutations
# remain explicit calls.  Calibration stays lazy to avoid an import cycle
# through the legacy matrix facade.
from .ablation import (  # noqa: E402
    AblationPlan,
    AblationRunResult,
    AblationValidationError,
    build_semantic_ablation_plan,
    execute_semantic_ablation,
    validate_semantic_ablation_evidence,
)


def evaluate_semantic_ablation_calibration_v2(
    **kwargs: object,
) -> object:
    """Evaluate reviewed targets only from validated persisted v2 graphs."""

    from .semantic_reassessment import (
        evaluate_semantic_ablation_calibration_v2 as evaluate,
    )

    return evaluate(**kwargs)


__all__ += [
    "AblationPlan",
    "AblationRunResult",
    "AblationValidationError",
    "build_semantic_ablation_plan",
    "evaluate_semantic_ablation_calibration_v2",
    "execute_semantic_ablation",
    "validate_semantic_ablation_evidence",
]

# Revision-2 causal execution and readiness are additive, side-effect-free
# boundaries.  They expose no positive holdout authorization until their
# source-recomputed prerequisites exist.
from .causal_ablation import (  # noqa: E402
    CausalAblationError,
    CausalAblationRunResultV2,
    CausalExecutionProfileV2,
    CausalRescueCaseV2,
    CausalRescueManifestV2,
    build_causal_rescue_manifest_v2,
    revalidate_semantic_calibration_prerequisite_v2,
)
from .causal_runtime import (  # noqa: E402
    CAUSAL_RUNTIME_EVIDENCE_SCHEMA_V2,
    COMPILER_REFERENCE_EXPOSURE_SCHEMA_V2,
    CausalRuntimeBridgeError,
    CausalRuntimeEvidenceV2,
    CompilerReferenceExposureV2,
    execute_causal_runtime_case_v2,
    validate_causal_runtime_evidence_v2,
)
from .causal_batch import (  # noqa: E402
    G211_CAUSAL_RUNTIME_BATCH_SCHEMA_V2,
    G211_CAUSAL_RUNTIME_ENVELOPE_SCHEMA_V2,
    G211_COMPILER_REFERENCE_POPULATION_SCHEMA_V2,
    CausalRuntimeBatchError,
    CausalRuntimeBatchResultV2,
    HSSLEV2116C82,
    build_g211_compiler_reference_population_v2,
    persist_causal_runtime_batch_v2,
    validate_causal_runtime_batch_v2,
)
from .reviewed_control import (  # noqa: E402
    G236_REQUIRED_CACHE_MODES,
    G236_REQUIRED_VARIANT_IDS,
    HSSLEV2367D38,
    REVIEWED_CONTROL_ATTESTATION_SCHEMA_V2,
    REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2,
    REVIEWED_CONTROL_ENTRY_SCHEMA_V2,
    REVIEWED_CONTROL_INDEX_SCHEMA_V2,
    REVIEWED_CONTROL_POLICY_V2_CID,
    REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID,
    REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2,
    ReviewedControlAttestationV2,
    ReviewedControlEntryV2,
    ReviewedControlIndexV2,
    ReviewedControlSafetyError,
    build_reviewed_control_index_v2,
    build_reviewed_control_safety_gate_v2,
    reviewed_control_policy_v2,
    reviewed_control_review_protocol_v2,
    validate_reviewed_control_safety_gate_v2,
)
from .semantic_quality import (  # noqa: E402
    G201_SEMANTIC_EVIDENCE_INDEX_SCHEMA_V2,
    G201_SEMANTIC_PREFLIGHT_PLAN_SCHEMA_V2,
    G201_SEMANTIC_SOURCE_COORDINATE_SCHEMA_V2,
    G201SemanticEvidenceIndexV2,
    G235_RUNTIME_SEMANTIC_OBSERVATION_SCHEMA_V2,
    G235_SEMANTIC_QUALITY_GATE_SCHEMA_V2,
    HSSLEV2350C27,
    SemanticQualityError,
    build_g201_semantic_evidence_index_v2,
    build_g201_semantic_preflight_plan_v2,
    build_g235_semantic_quality_gate_v2,
    validate_g201_semantic_evidence_index_v2,
    validate_g235_semantic_quality_gate_v2,
)
from .resource_statistics import (  # noqa: E402
    HSSLEV2374E49,
    INDEPENDENT_COMPONENT_RESOURCE_SCHEMA_V2,
    INDEPENDENT_RESOURCE_RECEIPT_SCHEMA_V2,
    IndependentComponentResourceV2,
    IndependentResourceReceiptV2,
    PAIRED_COST_ANALYSIS_SCHEMA_V2,
    PAIRED_COST_OBSERVATION_SCHEMA_V2,
    RESOURCE_COORDINATE_SCHEMA_V2,
    RESOURCE_COST_AGGREGATE_SCHEMA_V2,
    RESOURCE_EFFICACY_PROJECTION_SCHEMA_V2,
    RESOURCE_ENVIRONMENT_COMPATIBILITY_SCHEMA_V2,
    RESOURCE_EVIDENCE_SET_SCHEMA_V2,
    RESOURCE_MEASUREMENT_POLICY_SCHEMA_V2,
    RESOURCE_MEASUREMENT_POLICY_V2_CID,
    RESOURCE_PARETO_FRONTIER_SCHEMA_V2,
    RESOURCE_REPLAY_COMPARISON_POLICY_SCHEMA_V2,
    RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID,
    RESOURCE_REPLAY_COMPARISON_SCHEMA_V2,
    RESOURCE_REPLAY_COORDINATE_SCHEMA_V2,
    RESOURCE_REPLAY_IDENTITY_SCHEMA_V2,
    RESOURCE_REPLAY_MEASUREMENT_SCHEMA_V2,
    RESOURCE_RUN_IDENTITY_SCHEMA_V2,
    RESOURCE_STATISTICS_GATE_SCHEMA_V2,
    RESOURCE_STRATUM_SCHEMA_V2,
    ResourceStatisticsError,
    build_independent_resource_receipt_v2,
    build_resource_statistics_gate_v2,
    compare_resource_replay_measurements_v2,
    resource_evidence_set_cid_v2,
    resource_measurement_policy_v2,
    resource_replay_comparison_policy_v2,
    runtime_resource_coordinate_cid_v2,
    runtime_resource_replay_coordinate_cid_v2,
    validate_independent_resource_receipt_v2,
    validate_resource_replay_comparison_v2,
    validate_resource_statistics_gate_v2,
)
from .replay_gate import (  # noqa: E402
    G238_COMPARISON_SCHEMA_V2,
    G238_DETACHED_REPLAY_RECEIPT_SCHEMA_V2,
    G238_FAILURE_SAMPLE_PER_STRATUM,
    G238_GIT_COMMIT_IDENTITY_SCHEMA_V2,
    G238_KERNEL_IDENTITY_SCHEMA_V2,
    G238_REPLAY_GATE_SCHEMA_V2,
    G238_REPLAY_POLICY_SCHEMA_V2,
    G238_REPLAY_POLICY_V2_CID,
    G238_REPLAY_SOURCE_INDEX_SCHEMA_V2,
    G238_REPLAY_SOURCE_RECORD_SCHEMA_V2,
    G238_RUNTIME_COORDINATE_SCHEMA_V2,
    G238_SEMANTIC_IDENTITY_SCHEMA_V2,
    G238_SEMANTIC_OBSERVATION_SCHEMA_V2,
    G238_STATUS_IDENTITY_SCHEMA_V2,
    G238DetachedReplayReceiptV2,
    G238ReplaySourceIndexV2,
    G238ReplaySourceRecordV2,
    G238SemanticObservationV2,
    FreshReplayGateError,
    HSSLEV2381F50,
    build_g238_detached_replay_gate_v2,
    build_g238_replay_comparison_v2,
    g238_git_commit_cid,
    runtime_replay_coordinate_cid_v2,
    validate_g238_detached_replay_gate_v2,
    validate_g238_replay_comparison_v2,
    validate_g238_semantic_observation_v2,
)

__all__ += [
    "G201_SEMANTIC_EVIDENCE_INDEX_SCHEMA_V2",
    "G201_SEMANTIC_PREFLIGHT_PLAN_SCHEMA_V2",
    "G201_SEMANTIC_SOURCE_COORDINATE_SCHEMA_V2",
    "G201SemanticEvidenceIndexV2",
    "G235_RUNTIME_SEMANTIC_OBSERVATION_SCHEMA_V2",
    "G235_SEMANTIC_QUALITY_GATE_SCHEMA_V2",
    "G236_REQUIRED_CACHE_MODES",
    "G236_REQUIRED_VARIANT_IDS",
    "G238_COMPARISON_SCHEMA_V2",
    "G238_DETACHED_REPLAY_RECEIPT_SCHEMA_V2",
    "G238_FAILURE_SAMPLE_PER_STRATUM",
    "G238_GIT_COMMIT_IDENTITY_SCHEMA_V2",
    "G238_KERNEL_IDENTITY_SCHEMA_V2",
    "G238_REPLAY_GATE_SCHEMA_V2",
    "G238_REPLAY_POLICY_SCHEMA_V2",
    "G238_REPLAY_POLICY_V2_CID",
    "G238_REPLAY_SOURCE_INDEX_SCHEMA_V2",
    "G238_REPLAY_SOURCE_RECORD_SCHEMA_V2",
    "G238_RUNTIME_COORDINATE_SCHEMA_V2",
    "G238_SEMANTIC_IDENTITY_SCHEMA_V2",
    "G238_SEMANTIC_OBSERVATION_SCHEMA_V2",
    "G238_STATUS_IDENTITY_SCHEMA_V2",
    "G238DetachedReplayReceiptV2",
    "G238ReplaySourceIndexV2",
    "G238ReplaySourceRecordV2",
    "G238SemanticObservationV2",
    "FreshReplayGateError",
    "HSSLEV2350C27",
    "HSSLEV2367D38",
    "HSSLEV2374E49",
    "HSSLEV2381F50",
    "INDEPENDENT_COMPONENT_RESOURCE_SCHEMA_V2",
    "INDEPENDENT_RESOURCE_RECEIPT_SCHEMA_V2",
    "IndependentComponentResourceV2",
    "IndependentResourceReceiptV2",
    "PAIRED_COST_ANALYSIS_SCHEMA_V2",
    "PAIRED_COST_OBSERVATION_SCHEMA_V2",
    "RESOURCE_COORDINATE_SCHEMA_V2",
    "RESOURCE_COST_AGGREGATE_SCHEMA_V2",
    "RESOURCE_EFFICACY_PROJECTION_SCHEMA_V2",
    "RESOURCE_ENVIRONMENT_COMPATIBILITY_SCHEMA_V2",
    "RESOURCE_EVIDENCE_SET_SCHEMA_V2",
    "RESOURCE_MEASUREMENT_POLICY_SCHEMA_V2",
    "RESOURCE_MEASUREMENT_POLICY_V2_CID",
    "RESOURCE_PARETO_FRONTIER_SCHEMA_V2",
    "RESOURCE_REPLAY_COMPARISON_POLICY_SCHEMA_V2",
    "RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID",
    "RESOURCE_REPLAY_COMPARISON_SCHEMA_V2",
    "RESOURCE_REPLAY_COORDINATE_SCHEMA_V2",
    "RESOURCE_REPLAY_IDENTITY_SCHEMA_V2",
    "RESOURCE_REPLAY_MEASUREMENT_SCHEMA_V2",
    "RESOURCE_RUN_IDENTITY_SCHEMA_V2",
    "RESOURCE_STATISTICS_GATE_SCHEMA_V2",
    "RESOURCE_STRATUM_SCHEMA_V2",
    "REVIEWED_CONTROL_ATTESTATION_SCHEMA_V2",
    "REVIEWED_CONTROL_CLASSIFICATION_SCHEMA_V2",
    "REVIEWED_CONTROL_ENTRY_SCHEMA_V2",
    "REVIEWED_CONTROL_INDEX_SCHEMA_V2",
    "REVIEWED_CONTROL_POLICY_V2_CID",
    "REVIEWED_CONTROL_REVIEW_PROTOCOL_V2_CID",
    "REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2",
    "ReviewedControlAttestationV2",
    "ReviewedControlEntryV2",
    "ReviewedControlIndexV2",
    "ReviewedControlSafetyError",
    "ResourceStatisticsError",
    "SemanticQualityError",
    "build_g201_semantic_evidence_index_v2",
    "build_g201_semantic_preflight_plan_v2",
    "build_g235_semantic_quality_gate_v2",
    "build_g238_detached_replay_gate_v2",
    "build_g238_replay_comparison_v2",
    "build_independent_resource_receipt_v2",
    "build_reviewed_control_index_v2",
    "build_reviewed_control_safety_gate_v2",
    "build_resource_statistics_gate_v2",
    "compare_resource_replay_measurements_v2",
    "g238_git_commit_cid",
    "resource_evidence_set_cid_v2",
    "resource_measurement_policy_v2",
    "resource_replay_comparison_policy_v2",
    "reviewed_control_policy_v2",
    "reviewed_control_review_protocol_v2",
    "runtime_resource_coordinate_cid_v2",
    "runtime_resource_replay_coordinate_cid_v2",
    "runtime_replay_coordinate_cid_v2",
    "validate_g201_semantic_evidence_index_v2",
    "validate_g235_semantic_quality_gate_v2",
    "validate_g238_detached_replay_gate_v2",
    "validate_g238_replay_comparison_v2",
    "validate_g238_semantic_observation_v2",
    "validate_independent_resource_receipt_v2",
    "validate_resource_replay_comparison_v2",
    "validate_reviewed_control_safety_gate_v2",
    "validate_resource_statistics_gate_v2",
]

from .revised_pilot_authorization import (  # noqa: E402
    G210ReceiptMatrix,
    G210RuntimeReceiptMatrixV2,
    G230AuthorizationResult,
    G230ExecutionIdentities,
    G230_RECEIPT_REPLAY_ASSESSMENT_SCHEMA,
    G230RevisedPilotDecision,
    G230SourceFreezeReceipt,
    G234_GATE_IDS,
    G234_PAIRED_EFFICACY_COMPARISON_SCHEMA,
    G234_PAIRED_EFFICACY_PAIR_SCHEMA,
    G234_RUNTIME_GATE_RECEIPT_SCHEMA,
    HSSLEV2343B16,
    RevisedPilotAuthorizationError,
    build_g210_runtime_receipt_matrix_v2,
    build_g230_receipt_replay_assessment_v2,
    build_g234_efficacy_gate_v2,
    build_g234_reliability_gate_v2,
    build_g234_routing_gate_v2,
    evaluate_revised_pilot_authorization,
    validate_g230_receipt_replay_assessment_v2,
    validate_g234_efficacy_gate_v2,
    validate_g234_reliability_gate_v2,
    validate_g234_routing_gate_v2,
)

__all__ += [
    "CAUSAL_RUNTIME_EVIDENCE_SCHEMA_V2",
    "COMPILER_REFERENCE_EXPOSURE_SCHEMA_V2",
    "G211_CAUSAL_RUNTIME_BATCH_SCHEMA_V2",
    "G211_CAUSAL_RUNTIME_ENVELOPE_SCHEMA_V2",
    "G211_COMPILER_REFERENCE_POPULATION_SCHEMA_V2",
    "CausalAblationError",
    "CausalAblationRunResultV2",
    "CausalExecutionProfileV2",
    "CausalRescueCaseV2",
    "CausalRescueManifestV2",
    "CausalRuntimeBridgeError",
    "CausalRuntimeBatchError",
    "CausalRuntimeBatchResultV2",
    "CausalRuntimeEvidenceV2",
    "CompilerReferenceExposureV2",
    "G210ReceiptMatrix",
    "G210RuntimeReceiptMatrixV2",
    "G230AuthorizationResult",
    "G230ExecutionIdentities",
    "G230_RECEIPT_REPLAY_ASSESSMENT_SCHEMA",
    "G230RevisedPilotDecision",
    "G230SourceFreezeReceipt",
    "G234_GATE_IDS",
    "G234_PAIRED_EFFICACY_COMPARISON_SCHEMA",
    "G234_PAIRED_EFFICACY_PAIR_SCHEMA",
    "G234_RUNTIME_GATE_RECEIPT_SCHEMA",
    "HSSLEV2116C82",
    "HSSLEV2343B16",
    "RevisedPilotAuthorizationError",
    "build_g211_compiler_reference_population_v2",
    "build_g210_runtime_receipt_matrix_v2",
    "build_g230_receipt_replay_assessment_v2",
    "build_g234_efficacy_gate_v2",
    "build_g234_reliability_gate_v2",
    "build_g234_routing_gate_v2",
    "build_causal_rescue_manifest_v2",
    "execute_causal_runtime_case_v2",
    "evaluate_revised_pilot_authorization",
    "persist_causal_runtime_batch_v2",
    "revalidate_semantic_calibration_prerequisite_v2",
    "validate_causal_runtime_batch_v2",
    "validate_causal_runtime_evidence_v2",
    "validate_g230_receipt_replay_assessment_v2",
    "validate_g234_efficacy_gate_v2",
    "validate_g234_reliability_gate_v2",
    "validate_g234_routing_gate_v2",
]

# Runtime namespace and process orchestration remain inert on import.  Their
# public records are exported together so callers can freeze, execute, and
# source-replay the same G240 boundary without reaching into private modules.
from .namespace_provenance import (  # noqa: E402
    G240_CACHE_KEY_OBSERVATION_SCHEMA_V2,
    G240_CACHE_NAMESPACE_SET_SCHEMA_V2,
    G240_JOB_NAMESPACE_PLAN_SCHEMA_V2,
    G240_NAMESPACE_CONTEXT_SCHEMA_V2,
    G240_NAMESPACE_POLICY_SCHEMA_V2,
    G240_NAMESPACE_PREIMAGE_SCHEMA_V2,
    G240_RECURSIVE_GITLINKS_PROJECTION_SCHEMA_V2,
    G240_REPLAY_NAMESPACE_CONTEXT_SCHEMA_V2,
    G240_REPLAY_NAMESPACE_RECEIPT_SCHEMA_V2,
    G240_REPLAY_ORCHESTRATION_RECEIPT_SCHEMA_V2,
    G240_REPLAY_WORKTREE_PROJECTION_SCHEMA_V2,
    G240_RUNTIME_NAMESPACE_EVIDENCE_SET_SCHEMA_V2,
    G240_RUNTIME_NAMESPACE_RECEIPT_SCHEMA_V2,
    G240JobNamespacePlanV2,
    G240NamespacePolicyV2,
    G240PrivateReplayValidationSourcesV2,
    G240ReplayNamespaceReceiptV2,
    G240ReplayOrchestrationReceiptV2,
    G240RuntimeNamespaceEvidenceSetV2,
    G240RuntimeNamespaceReceiptV2,
    RuntimeNamespaceProvenanceError,
    build_g240_namespace_policy_v2,
    g240_cache_namespace_set_cid,
    g240_recursive_gitlinks_cid,
    g240_replay_namespace_request_v2,
    g240_worktree_safety_projection_cid,
    validate_g240_namespace_policy_v2,
    validate_g240_private_replay_sources_v2,
    validate_g240_replay_namespace_receipt_v2,
    validate_g240_replay_orchestration_receipt_v2,
    validate_g240_runtime_namespace_evidence_set_v2,
    validate_g240_runtime_namespace_population_v2,
    validate_g240_runtime_namespace_receipt_from_policy_v2,
    validate_g240_runtime_namespace_receipt_v2,
)
from .source_orchestration import (  # noqa: E402
    G240_GIT_COMMIT_IDENTITY_SCHEMA_V2,
    G240_INTERPRETER_IDENTITY_SCHEMA_V2,
    G240_SOURCE_CACHE_MARKER_SCHEMA_V2,
    G240_SOURCE_COMMAND_PROJECTION_SCHEMA_V2,
    G240_SOURCE_EXECUTOR_CONTRACT_SCHEMA_V2,
    G240_SOURCE_ORCHESTRATION_EVIDENCE_SET_SCHEMA_V2,
    G240_SOURCE_ORCHESTRATION_RECEIPT_SCHEMA_V2,
    G240_SOURCE_PHYSICAL_NAMESPACE_SCHEMA_V2,
    G240_SOURCE_RUNTIME_ENVIRONMENT_PROJECTION_SCHEMA_V2,
    G240PrivateSourceValidationSourcesV2,
    G240SourceExecutionResultV2,
    G240SourceExecutorContractV2,
    G240SourceOrchestrationEvidenceSetV2,
    G240SourceOrchestrationReceiptV2,
    HSSLEV2405D72,
    SourceRuntimeOrchestrationError,
    build_g240_source_executor_contract_v2,
    build_g240_source_orchestration_evidence_set_v2,
    g240_source_git_commit_cid,
    run_g240_source_job_v2,
    validate_g240_private_source_sources_v2,
    validate_g240_source_orchestration_evidence_set_v2,
)
from .source_executor import (  # noqa: E402
    G240_EXECUTION_REQUEST_FILE_V2,
    G240_EXECUTION_REQUEST_SCHEMA_V2,
    G240_LIVE_ADAPTER_FACTORY_ID_V2,
    G240_LIVE_ADAPTER_FACTORY_SCHEMA_V2,
    G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2,
    G240_TRACKED_SOURCE_EXECUTOR_COMMAND_V2,
    G240_TRACKED_SOURCE_EXECUTOR_MODULE_V2,
    G240ExecutionRequestV2,
    G240SourceExecutorError,
    build_g240_live_adapter_configuration_v2,
    execute_g240_request_from_environment_v2,
    validate_g240_execution_request_v2,
    validate_g240_production_execution_request_v2,
    validate_g240_runtime_for_execution_request_v2,
)
from .replay import (  # noqa: E402
    REPLAY_RECEIPT_FILE,
    REPLAY_RECEIPT_SCHEMA,
    REPLAY_REQUEST_SCHEMA,
    ReplayError,
    ReplayReceipt,
    ReplayRequest,
    run_detached_replay,
    run_g240_detached_replay_v2,
    validate_detached_replay_pair,
)

__all__ += [
    "G240_CACHE_KEY_OBSERVATION_SCHEMA_V2",
    "G240_CACHE_NAMESPACE_SET_SCHEMA_V2",
    "G240_GIT_COMMIT_IDENTITY_SCHEMA_V2",
    "G240_INTERPRETER_IDENTITY_SCHEMA_V2",
    "G240_EXECUTION_REQUEST_FILE_V2",
    "G240_EXECUTION_REQUEST_SCHEMA_V2",
    "G240_JOB_NAMESPACE_PLAN_SCHEMA_V2",
    "G240_LIVE_ADAPTER_FACTORY_ID_V2",
    "G240_LIVE_ADAPTER_FACTORY_SCHEMA_V2",
    "G240_NAMESPACE_CONTEXT_SCHEMA_V2",
    "G240_NAMESPACE_POLICY_SCHEMA_V2",
    "G240_NAMESPACE_PREIMAGE_SCHEMA_V2",
    "G240_RECURSIVE_GITLINKS_PROJECTION_SCHEMA_V2",
    "G240_REPLAY_NAMESPACE_CONTEXT_SCHEMA_V2",
    "G240_REPLAY_NAMESPACE_RECEIPT_SCHEMA_V2",
    "G240_REPLAY_ORCHESTRATION_RECEIPT_SCHEMA_V2",
    "G240_REPLAY_WORKTREE_PROJECTION_SCHEMA_V2",
    "G240_RUNTIME_NAMESPACE_EVIDENCE_SET_SCHEMA_V2",
    "G240_RUNTIME_NAMESPACE_RECEIPT_SCHEMA_V2",
    "G240_SOURCE_CACHE_MARKER_SCHEMA_V2",
    "G240_SOURCE_COMMAND_PROJECTION_SCHEMA_V2",
    "G240_SOURCE_EXECUTOR_CONTRACT_SCHEMA_V2",
    "G240_SOURCE_ORCHESTRATION_EVIDENCE_SET_SCHEMA_V2",
    "G240_SOURCE_ORCHESTRATION_RECEIPT_SCHEMA_V2",
    "G240_SOURCE_PHYSICAL_NAMESPACE_SCHEMA_V2",
    "G240_SOURCE_RUNTIME_ENVIRONMENT_PROJECTION_SCHEMA_V2",
    "G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2",
    "G240_TRACKED_SOURCE_EXECUTOR_COMMAND_V2",
    "G240_TRACKED_SOURCE_EXECUTOR_MODULE_V2",
    "G240ExecutionRequestV2",
    "G240JobNamespacePlanV2",
    "G240NamespacePolicyV2",
    "G240PrivateReplayValidationSourcesV2",
    "G240PrivateSourceValidationSourcesV2",
    "G240ReplayNamespaceReceiptV2",
    "G240ReplayOrchestrationReceiptV2",
    "G240RuntimeNamespaceEvidenceSetV2",
    "G240RuntimeNamespaceReceiptV2",
    "G240SourceExecutionResultV2",
    "G240SourceExecutorError",
    "G240SourceExecutorContractV2",
    "G240SourceOrchestrationEvidenceSetV2",
    "G240SourceOrchestrationReceiptV2",
    "HSSLEV2405D72",
    "REPLAY_RECEIPT_FILE",
    "REPLAY_RECEIPT_SCHEMA",
    "REPLAY_REQUEST_SCHEMA",
    "ReplayError",
    "ReplayReceipt",
    "ReplayRequest",
    "RuntimeNamespaceProvenanceError",
    "SourceRuntimeOrchestrationError",
    "build_g240_namespace_policy_v2",
    "build_g240_live_adapter_configuration_v2",
    "build_g240_source_executor_contract_v2",
    "build_g240_source_orchestration_evidence_set_v2",
    "execute_g240_request_from_environment_v2",
    "g240_cache_namespace_set_cid",
    "g240_recursive_gitlinks_cid",
    "g240_replay_namespace_request_v2",
    "g240_source_git_commit_cid",
    "g240_worktree_safety_projection_cid",
    "run_detached_replay",
    "run_g240_detached_replay_v2",
    "run_g240_source_job_v2",
    "validate_detached_replay_pair",
    "validate_g240_namespace_policy_v2",
    "validate_g240_private_replay_sources_v2",
    "validate_g240_private_source_sources_v2",
    "validate_g240_replay_namespace_receipt_v2",
    "validate_g240_replay_orchestration_receipt_v2",
    "validate_g240_runtime_namespace_evidence_set_v2",
    "validate_g240_runtime_namespace_population_v2",
    "validate_g240_runtime_namespace_receipt_from_policy_v2",
    "validate_g240_runtime_namespace_receipt_v2",
    "validate_g240_execution_request_v2",
    "validate_g240_production_execution_request_v2",
    "validate_g240_runtime_for_execution_request_v2",
    "validate_g240_source_orchestration_evidence_set_v2",
]

# G202/G231 are composite contracts over the source-recomputed child gates.
# Exporting the complete module API keeps callers on the typed public boundary
# while preserving the module's fail-closed, authorization-free semantics.
from .positive_gate_bundle import (  # noqa: E402
    G202_AUTHORITY_ROLE_KEYS,
    G202_AUTHORITY_ROLE_MANIFEST_SCHEMA_V2,
    G202_CACHE_POLICY_SCHEMA_V2,
    G202_EFFICACY_EVALUATION_POLICY_V2_CID,
    G202_EXECUTION_IDENTITIES_SCHEMA_V2,
    G202_FROZEN_RUN_INPUTS_SCHEMA_V2,
    G202_GATE_POLICY_BUNDLE_SCHEMA_V2,
    G202_G210_CASE_INDEX_SCHEMA_V2,
    G202_G210_INPUT_PLAN_SCHEMA_V2,
    G202_G210_RESCUE_PLAN_SET_SCHEMA_V2,
    G202_PARETO_POLICY_V2_CID,
    G202_RUN_PLAN_SCHEMA_V2,
    G202_RUNTIME_IDENTITY_POLICY_SCHEMA_V2,
    G202_SEMANTIC_QUALITY_POLICY_V2_CID,
    G202_SHORTLIST_SELECTION_POLICY_V2_CID,
    G202_STAGE_IDENTITY_PROJECTION_SCHEMA_V2,
    G202_SYMAI_NAMESPACE_PREIMAGE_SCHEMA_V2,
    G202CachePolicyV2,
    G202AuthorityRoleManifestV2,
    G202ExecutionIdentitiesV2,
    G202FrozenRunInputsV2,
    G202GatePolicyBundleV2,
    G202RuntimeIdentityPolicyV2,
    G231_ARTIFACT_BINDINGS_SCHEMA_V2,
    G231_ARTIFACT_KEYS,
    G231_CASE_INDEX_SCHEMA_V2,
    G231_EVALUATED_CANDIDATE_IDS,
    G231_GATE_SUBSECTION_SCHEMA_V2,
    G231_MODEL_IDENTITY_SCHEMA_V2,
    G231_POSITIVE_GATE_BUNDLE_SCHEMA_V2,
    G231_ROUTE_MANIFEST_SCHEMA_V2,
    G231_RUN_PLAN_SCHEMA_V2,
    G231_SEMANTIC_PLAN_SET_SCHEMA_V2,
    G231ArtifactBindingsV2,
    HSSLEV2312F74,
    PositiveGateBundleError,
    build_g202_g201_input_plan_v2,
    build_g202_g210_input_plan_v2,
    build_g231_observed_runtime_model_identity_v2,
    build_g231_positive_gate_bundle_v2,
    build_g231_replay_source_records_v2,
    g202_run_plan_cid_v2,
    g202_shortlist_selection_policy_v2,
    g202_stage_identity_cid_v2,
    g202_stage_identity_coordinate_v2,
    g202_stage_identity_input_cid_v2,
    g231_case_index_cid_v2,
    g231_model_identity_cid_v2,
    g231_route_manifest_cid_v2,
    g231_run_plan_cid_v2,
    g231_semantic_plan_set_cid_v2,
    validate_g231_positive_gate_bundle_v2,
)

__all__ += [
    "G202_AUTHORITY_ROLE_KEYS",
    "G202_AUTHORITY_ROLE_MANIFEST_SCHEMA_V2",
    "G202_CACHE_POLICY_SCHEMA_V2",
    "G202_EFFICACY_EVALUATION_POLICY_V2_CID",
    "G202_EXECUTION_IDENTITIES_SCHEMA_V2",
    "G202_FROZEN_RUN_INPUTS_SCHEMA_V2",
    "G202_GATE_POLICY_BUNDLE_SCHEMA_V2",
    "G202_G210_CASE_INDEX_SCHEMA_V2",
    "G202_G210_INPUT_PLAN_SCHEMA_V2",
    "G202_G210_RESCUE_PLAN_SET_SCHEMA_V2",
    "G202_PARETO_POLICY_V2_CID",
    "G202_RUN_PLAN_SCHEMA_V2",
    "G202_RUNTIME_IDENTITY_POLICY_SCHEMA_V2",
    "G202_SEMANTIC_QUALITY_POLICY_V2_CID",
    "G202_SHORTLIST_SELECTION_POLICY_V2_CID",
    "G202_STAGE_IDENTITY_PROJECTION_SCHEMA_V2",
    "G202_SYMAI_NAMESPACE_PREIMAGE_SCHEMA_V2",
    "G202CachePolicyV2",
    "G202AuthorityRoleManifestV2",
    "G202ExecutionIdentitiesV2",
    "G202FrozenRunInputsV2",
    "G202GatePolicyBundleV2",
    "G202RuntimeIdentityPolicyV2",
    "G231_ARTIFACT_BINDINGS_SCHEMA_V2",
    "G231_ARTIFACT_KEYS",
    "G231_CASE_INDEX_SCHEMA_V2",
    "G231_EVALUATED_CANDIDATE_IDS",
    "G231_GATE_SUBSECTION_SCHEMA_V2",
    "G231_MODEL_IDENTITY_SCHEMA_V2",
    "G231_POSITIVE_GATE_BUNDLE_SCHEMA_V2",
    "G231_ROUTE_MANIFEST_SCHEMA_V2",
    "G231_RUN_PLAN_SCHEMA_V2",
    "G231_SEMANTIC_PLAN_SET_SCHEMA_V2",
    "G231ArtifactBindingsV2",
    "HSSLEV2312F74",
    "PositiveGateBundleError",
    "build_g202_g201_input_plan_v2",
    "build_g202_g210_input_plan_v2",
    "build_g231_observed_runtime_model_identity_v2",
    "build_g231_positive_gate_bundle_v2",
    "build_g231_replay_source_records_v2",
    "g202_run_plan_cid_v2",
    "g202_shortlist_selection_policy_v2",
    "g202_stage_identity_cid_v2",
    "g202_stage_identity_coordinate_v2",
    "g202_stage_identity_input_cid_v2",
    "g231_case_index_cid_v2",
    "g231_model_identity_cid_v2",
    "g231_route_manifest_cid_v2",
    "g231_run_plan_cid_v2",
    "g231_semantic_plan_set_cid_v2",
    "validate_g231_positive_gate_bundle_v2",
]

# Holdout custody is an independently governed boundary layered after the
# authorization-free G231 composite.  Importing these contracts performs no
# ledger access; release remains an explicit, externally authorized call.
from .custodian_release import (  # noqa: E402
    G239_EXTERNAL_ARTIFACT_SCHEMA,
    G239_EXTERNAL_AUTHORITY_SCHEMA,
    G239_EXTERNAL_GITLINK_SCHEMA,
    G239_EXTERNAL_RECEIPT_SCHEMA,
    G239_EXTERNAL_REQUIREMENT_SCHEMA,
    G239_EXTERNAL_SOURCE_SCHEMA,
    G241_ACTIVITY_KEYS,
    G241_CUSTODIAN_TRUST_ROOT_SCHEMA_V1,
    G241_EXTERNAL_ARTIFACT_KEYS,
    G241_EXTERNAL_PROJECTION_SCHEMA_V1,
    G241_GIT_EXECUTABLE_IDENTITY_SCHEMA_V1,
    G241_GOVERNED_EVIDENCE_TERM,
    G241_GOVERNED_GOAL_ID,
    G241_LEDGER_FILE_IDENTITY_SCHEMA_V1,
    G241_PARENT_KEYS,
    G241_RELEASE_CONSUMPTION_TOMBSTONE_SCHEMA_V1,
    G241_RELEASE_LEDGER_AUTHORITY_SCHEMA_V1,
    G241_RELEASE_RECEIPT_SCHEMA_V1,
    G241_RELEASE_REQUEST_SCHEMA_V1,
    G241_SOURCE_INDEX_SCHEMA_V1,
    CustodianReleaseError,
    G241CustodyAccessTransactionV1,
    G241CustodianReleaseRequestV1,
    G241CustodianTrustRootV1,
    G241ExternallyGovernedCustodianReleaseReceiptV1,
    G241G239ExternalProjectionV1,
    G241PersistedBatchSourceV1,
    G241ReleaseConsumptionTombstoneV1,
    G241SourceDecisionIndexV1,
    G241SourceReplayResultV1,
    authorize_g241_custodian_release_v1,
    consume_g241_release_for_access_v1,
    derive_g232_shortlist_from_validated_gates_v1,
    evaluate_g239_for_g241_v1,
    g241_artifact_slot_cid,
    g241_git_executable_cid_v1,
    g241_git_tree_cid,
    g241_release_ledger_authority_cid_v1,
    load_and_validate_g241_release_receipt_v1,
    load_g241_custodian_trust_root_v1,
    recompute_g241_source_chain_v1,
    validate_g232_proposal_against_source_replay_v1,
    zero_g241_activity,
)

__all__ += [
    "G239_EXTERNAL_ARTIFACT_SCHEMA",
    "G239_EXTERNAL_AUTHORITY_SCHEMA",
    "G239_EXTERNAL_GITLINK_SCHEMA",
    "G239_EXTERNAL_RECEIPT_SCHEMA",
    "G239_EXTERNAL_REQUIREMENT_SCHEMA",
    "G239_EXTERNAL_SOURCE_SCHEMA",
    "G241_ACTIVITY_KEYS",
    "G241_CUSTODIAN_TRUST_ROOT_SCHEMA_V1",
    "G241_EXTERNAL_ARTIFACT_KEYS",
    "G241_EXTERNAL_PROJECTION_SCHEMA_V1",
    "G241_GIT_EXECUTABLE_IDENTITY_SCHEMA_V1",
    "G241_GOVERNED_EVIDENCE_TERM",
    "G241_GOVERNED_GOAL_ID",
    "G241_LEDGER_FILE_IDENTITY_SCHEMA_V1",
    "G241_PARENT_KEYS",
    "G241_RELEASE_CONSUMPTION_TOMBSTONE_SCHEMA_V1",
    "G241_RELEASE_LEDGER_AUTHORITY_SCHEMA_V1",
    "G241_RELEASE_RECEIPT_SCHEMA_V1",
    "G241_RELEASE_REQUEST_SCHEMA_V1",
    "G241_SOURCE_INDEX_SCHEMA_V1",
    "CustodianReleaseError",
    "G241CustodyAccessTransactionV1",
    "G241CustodianReleaseRequestV1",
    "G241CustodianTrustRootV1",
    "G241ExternallyGovernedCustodianReleaseReceiptV1",
    "G241G239ExternalProjectionV1",
    "G241PersistedBatchSourceV1",
    "G241ReleaseConsumptionTombstoneV1",
    "G241SourceDecisionIndexV1",
    "G241SourceReplayResultV1",
    "authorize_g241_custodian_release_v1",
    "consume_g241_release_for_access_v1",
    "derive_g232_shortlist_from_validated_gates_v1",
    "evaluate_g239_for_g241_v1",
    "g241_artifact_slot_cid",
    "g241_git_executable_cid_v1",
    "g241_git_tree_cid",
    "g241_release_ledger_authority_cid_v1",
    "load_and_validate_g241_release_receipt_v1",
    "load_g241_custodian_trust_root_v1",
    "recompute_g241_source_chain_v1",
    "validate_g232_proposal_against_source_replay_v1",
    "zero_g241_activity",
]
