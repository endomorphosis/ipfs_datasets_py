"""Versioned, side-effect-free adapters for the benchmark logic pipeline.

The adapters in this module are intentionally thin.  They accept an injected
callable (or no callable when a capability is unavailable), execute it only
when the caller explicitly asks them to, and turn the result into a strict
versioned :class:`~benchmarks.logic_pipeline.contracts.StageRecord`.  No
optional package is imported here and no production router is configured or
modified.

Later stage-specific integrations can provide handlers for the six registered
stages without changing the record format or the baseline route.  A handler
receives :class:`StageRequest` and may return :class:`StageOutput` or a JSON
value.  Raw model output belongs in a bounded stage payload; it never becomes
proof authority merely by passing through an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import importlib
import json
import math
import re
import textwrap
import threading
import time
from types import MappingProxyType, SimpleNamespace
from typing import Any, Callable, Final, Mapping, MutableMapping, Sequence
import urllib.parse
import urllib.request

from .contracts import (
    BASELINE_VARIANT,
    CacheMode,
    CacheScope,
    CaseResultRecord,
    DEFAULT_PROTOCOL_SHA256,
    FailureCode,
    HSSLEV0306C18,
    ProtocolContractError,
    ResourceLane,
    Split,
    StageName,
    StageProvenance,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)
from .source_bound_import import import_source_bound_ipfs_accelerate


ADAPTER_VERSION: Final = "1"
ADAPTER_SOURCE: Final = "benchmarks.logic_pipeline.adapters"
STAGE_ORDER: Final = (
    StageName.COMPILER,
    StageName.SPACY,
    StageName.SYMAI,
    StageName.HAMMER,
    StageName.LEANSTRAL,
    StageName.KERNEL,
)

_SAFE_ID_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
_MAX_DETAIL_LENGTH: Final = 512

HAMMER_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.hammer-evidence.v1"
)
LEANSTRAL_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.leanstral-evidence.v1"
)
LEANSTRAL_DRAFT_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/leanstral-proof-draft@1"
)
LEANSTRAL_PROOF_OUTPUT_SCHEMA: Final = (
    "ipfs_accelerate_py.agent_supervisor.leanstral-proof-proposal@1"
)
LEANSTRAL_GENERATION_BOUNDARY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "leanstral-generation-boundary.v1"
)
LEANSTRAL_MODEL_RESOURCE_CLASS: Final = "model"
LEANSTRAL_KERNEL_RESOURCE_CLASS: Final = "kernel"
LEANSTRAL_MAX_REPAIR_ATTEMPTS: Final = 1
LEANSTRAL_MAX_CONTEXT_BYTES: Final = 64 * 1024
LEANSTRAL_MEASURED_TIMEOUT_SECONDS: Final = 120.0
LEANSTRAL_MEASURED_MAX_NEW_TOKENS: Final = 1_400
# StageRecord also bounds individual strings to 4096 characters.  Keep the
# provider output within that durable wire-contract limit.
LEANSTRAL_MAX_DRAFT_BYTES: Final = 4 * 1024
SPACY_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v1"
)
SPACY_MAX_EVIDENCE_BYTES: Final = 60 * 1024
SPACY_MAX_TEXT_BYTES: Final = 4 * 1024
SYMAI_EVIDENCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v1"
)
SYMAI_PROMPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.symai-prompt.v1"
)
SEMANTIC_CONTEXT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-stage-context.v1"
)
SEMANTIC_CONTEXT_MAX_BYTES: Final = 48 * 1024
SYMAI_MAX_TEXT_BYTES: Final = 8 * 1024
SYMAI_MAX_RAW_OUTPUT_BYTES: Final = 4 * 1024
SYMAI_MAX_CANDIDATE_BYTES: Final = 24 * 1024
SYMAI_MAX_RETRIES: Final = 2
SYMAI_MAX_LIST_ITEMS: Final = 256
SYMAI_MAX_ITEM_LENGTH: Final = 256
SYMAI_ROUTER_ENGINE: Final = (
    "ipfs_datasets_py.utils.symai_ipfs_engine.IPFSSyMAINeurosymbolicEngine"
)
_LEANSTRAL_FORBIDDEN_CONSTRUCT = re.compile(
    r"(?i)(?<![A-Za-z0-9_'])(?:sorry|admit|sorryAx|axiom|unsafe)(?![A-Za-z0-9_'])"
)
_LEANSTRAL_NON_TACTIC_BODY = re.compile(
    r"(?im)^\s*(?:(?:import|namespace|section|theorem|lemma|def|opaque|example)\b|```)"
)
_SYMAI_CONTRACT_KEYS = frozenset(
    {
        "candidate_ir",
        "normalized_predicates",
        "quantifiers",
        "entities",
        "ambiguity_flags",
        "confidence",
        "validation_errors",
    }
)
# The frozen router lock specifies the provider-level ``json_object`` mode.
# The exact seven-field contract remains enforced by the authored prompt and
# by ``_validate_symai_contract`` after strict duplicate-key/NaN rejection.
SYMAI_RESPONSE_FORMAT: Final = {"type": "json_object"}
_SYMAI_RECURSIVE_IDENTITIES = frozenset(
    {
        "symai",
        "symbolicai",
        "symbolic_ai",
        "ipfs_symai",
        "symai_ipfs_engine",
    }
)
_SYMAI_AUTHORITY_KEYS = frozenset(
    {
        "authoritative",
        "is_proved",
        "kernel_accepted",
        "kernel_receipt",
        "kernel_receipt_sha256",
        "proof_authority",
        "verified",
    }
)
_LEANSTRAL_DRAFT_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "artifact_kind",
        "stage",
        "draft_text",
        "proof_text",
        "request_id",
        "llm_provider",
        "model",
        "obligation_ids",
        "canonical_source_digest",
        "prompt_sha256",
        "output_sha256",
        "timeout_ms",
        "token_budget",
        "resource_class",
        "theorem_id",
        "theorem_equivalence_key",
        "context_capsule_id",
        "proposal_kind",
        "proposal_schema",
        "decomposition",
        "reused_artifact_ids",
        "prompt_tokens",
        "response_tokens",
        "assurance",
        "verified",
        "authoritative",
        "proof_attempted",
        "proof_success",
        "kernel_checked",
        "can_mutate_canonical_source",
        "can_mutate_obligations",
        "metadata",
    }
)


class HammerAdapterContractError(ProtocolContractError):
    """Raised when Hammer records cannot be joined to one proof-search path.

    The underlying Hammer package owns the individual record contracts.  This
    exception is specific to the benchmark boundary: it covers the joins
    between request, portfolio, candidate, reconstruction, and environment
    records that are otherwise easy to lose when serializing a stage result.
    """


class SpacyAdapterMode(str, Enum):
    """Explicit linguistic execution paths recorded by :class:`SpacyAdapter`.

    ``FULL_MODEL`` requires the requested installed spaCy package and refuses
    the implicit blank-language fallback used by ``SpaCyLegalEncoder``.
    ``BLANK_MODEL`` opts into that fallback for controlled ablations.
    ``REGEX_LEGAL`` uses the deterministic legal parser and heuristic SRL
    path without importing spaCy.
    """

    FULL_MODEL = "full_model"
    BLANK_MODEL = "blank_model"
    REGEX_LEGAL = "regex_legal"


@dataclass(frozen=True, slots=True)
class SpacyAdapterConfig:
    """Frozen configuration for reproducible linguistic evidence extraction."""

    requested_model: str = "en_core_web_sm"
    mode: SpacyAdapterMode = SpacyAdapterMode.FULL_MODEL
    language: str = "en"
    max_text_bytes: int = SPACY_MAX_TEXT_BYTES

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            try:
                object.__setattr__(self, "mode", SpacyAdapterMode(self.mode))
            except ValueError as exc:
                raise ProtocolContractError(
                    f"unsupported spaCy adapter mode: {self.mode!r}"
                ) from exc
        if not isinstance(self.mode, SpacyAdapterMode):
            raise ProtocolContractError("mode must be a SpacyAdapterMode")
        _safe_id(self.requested_model, "requested_model")
        if (
            not isinstance(self.language, str)
            or not re.fullmatch(r"[a-z]{2,8}", self.language)
        ):
            raise ProtocolContractError(
                "language must be a lowercase ISO-style language identifier"
            )
        if (
            not isinstance(self.max_text_bytes, int)
            or isinstance(self.max_text_bytes, bool)
            or not 1 <= self.max_text_bytes <= SPACY_MAX_TEXT_BYTES
        ):
            raise ProtocolContractError(
                f"max_text_bytes must be between 1 and {SPACY_MAX_TEXT_BYTES}"
            )


@dataclass(frozen=True, slots=True)
class SymaiAdapterConfig:
    """Frozen routing and contract limits for one SyMAI benchmark arm.

    The provider is deliberately pinned to the repository's existing
    ``llm_router`` accelerator provider by default.  The adapter never creates
    a model server and disables the router's local-model fallback, so a
    requested Leanstral model can only reuse the already managed service.
    """

    provider: str = "ipfs_accelerate_py"
    model: str = "default"
    max_retries: int = 1
    dry_run: bool = False
    cache_enabled: bool = True
    max_text_bytes: int = SYMAI_MAX_TEXT_BYTES
    max_raw_output_bytes: int = SYMAI_MAX_RAW_OUTPUT_BYTES
    expected_inner_provider: str | None = None
    expected_inner_model: str | None = None
    expected_inner_endpoint: str | None = None
    expected_inner_backend: str | None = None

    def __post_init__(self) -> None:
        _safe_id(self.provider, "provider")
        _safe_id(self.model, "model")
        if _is_recursive_symai_identity(self.provider):
            raise ProtocolContractError(
                "SyMAI cannot select itself as an llm_router provider"
            )
        if (
            not isinstance(self.max_retries, int)
            or isinstance(self.max_retries, bool)
            or not 0 <= self.max_retries <= SYMAI_MAX_RETRIES
        ):
            raise ProtocolContractError(
                f"max_retries must be between 0 and {SYMAI_MAX_RETRIES}"
            )
        if type(self.dry_run) is not bool:
            raise ProtocolContractError("dry_run must be a boolean")
        if type(self.cache_enabled) is not bool:
            raise ProtocolContractError("cache_enabled must be a boolean")
        inner_bindings = (
            self.expected_inner_provider,
            self.expected_inner_model,
            self.expected_inner_endpoint,
            self.expected_inner_backend,
        )
        if any(value is not None for value in inner_bindings):
            if not all(
                isinstance(value, str)
                and value
                and value == value.strip()
                for value in inner_bindings
            ):
                raise ProtocolContractError(
                    "SyMAI inner route bindings must be supplied together"
                )
            _safe_id(self.expected_inner_provider, "expected_inner_provider")
            _safe_id(self.expected_inner_backend, "expected_inner_backend")
            if (
                len(self.expected_inner_model) > SYMAI_MAX_ITEM_LENGTH
                or any(ord(char) < 32 for char in self.expected_inner_model)
            ):
                raise ProtocolContractError(
                    "expected_inner_model must be a bounded model identity"
                )
            endpoint = urllib.parse.urlsplit(self.expected_inner_endpoint)
            if (
                endpoint.scheme not in {"http", "https"}
                or not endpoint.netloc
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
            ):
                raise ProtocolContractError(
                    "expected_inner_endpoint must be an absolute HTTP endpoint"
                )
        if (
            not isinstance(self.max_text_bytes, int)
            or isinstance(self.max_text_bytes, bool)
            or not 1 <= self.max_text_bytes <= SYMAI_MAX_TEXT_BYTES
        ):
            raise ProtocolContractError(
                f"max_text_bytes must be between 1 and {SYMAI_MAX_TEXT_BYTES}"
            )
        if (
            not isinstance(self.max_raw_output_bytes, int)
            or isinstance(self.max_raw_output_bytes, bool)
            or not 1 <= self.max_raw_output_bytes <= SYMAI_MAX_RAW_OUTPUT_BYTES
        ):
            raise ProtocolContractError(
                "max_raw_output_bytes must be between 1 and "
                f"{SYMAI_MAX_RAW_OUTPUT_BYTES}"
            )


def _safe_id(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        or any(char not in _SAFE_ID_CHARS for char in value)
        or value in {".", ".."}
    ):
        raise ProtocolContractError(
            f"{field_name} must be a safe 1-128 character identifier"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ProtocolContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _freeze_mapping(value: Mapping[str, object], field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ProtocolContractError(f"{field_name} must be an object with string keys")
    # StageRecord performs the complete bounded/deep-freeze validation.  This
    # shallow proxy also prevents mutation between request construction and
    # handler execution.
    return MappingProxyType(dict(value))


def _input_digest(value: object) -> tuple[str, int]:
    try:
        encoded = canonical_json(value).encode("utf-8")
    except ProtocolContractError:
        raise
    if len(encoded) > 64 * 1024:
        raise ProtocolContractError("stage input exceeds the 64 KiB bound")
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def _freeze_json(value: object) -> object:
    """Return an immutable, detached JSON value for live stage handoffs."""

    # Contract records already expose deeply frozen mappings/tuples.  Thaw
    # those containers before the canonical round trip so artifacts can carry
    # either fresh handler output or a previously materialized record.
    encoded = canonical_json(_thaw_json(value)).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise ProtocolContractError("stage artifact exceeds the 64 KiB bound")

    def freeze(item: object) -> object:
        if isinstance(item, dict):
            return MappingProxyType(
                {str(key): freeze(member) for key, member in item.items()}
            )
        if isinstance(item, list):
            return tuple(freeze(member) for member in item)
        return item

    return freeze(json.loads(encoded))


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(member) for key, member in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(member) for member in value]
    return value


@dataclass(frozen=True, slots=True)
class StageArtifact:
    """Typed, content-addressed output passed between live stage handlers.

    Artifacts describe the actual invocation graph.  They deliberately do not
    replace ``StageRecord``: durable records remain in canonical wire order,
    while an A6/A12 Leanstral-first invocation can still be represented
    truthfully in downstream requests.
    """

    stage: StageName
    status: StageStatus
    data: object
    output_sha256: str | None
    effective_identity: Mapping[str, object]
    invocation_index: int
    invoked: bool = True
    policy_reason: str = "scheduled"

    def __post_init__(self) -> None:
        if not isinstance(self.stage, StageName):
            raise ProtocolContractError("artifact stage must be a StageName")
        if not isinstance(self.status, StageStatus):
            raise ProtocolContractError("artifact status must be a StageStatus")
        if (
            isinstance(self.invocation_index, bool)
            or not isinstance(self.invocation_index, int)
            or not 0 <= self.invocation_index < len(StageName)
        ):
            raise ProtocolContractError(
                "artifact invocation_index must be a bounded integer"
            )
        if type(self.invoked) is not bool:
            raise ProtocolContractError("artifact invoked must be a boolean")
        if (
            not isinstance(self.policy_reason, str)
            or not self.policy_reason.strip()
            or len(self.policy_reason) > 256
        ):
            raise ProtocolContractError(
                "artifact policy_reason must be a bounded nonempty string"
            )
        frozen = _freeze_json(self.data)
        object.__setattr__(self, "data", frozen)
        if not isinstance(self.effective_identity, Mapping):
            raise ProtocolContractError(
                "artifact.effective_identity must be an object"
            )
        identity = _freeze_json(self.effective_identity)
        if not isinstance(identity, Mapping):  # defensive after JSON freezing
            raise ProtocolContractError(
                "artifact.effective_identity must remain an object"
            )
        object.__setattr__(self, "effective_identity", identity)
        calculated = hashlib.sha256(
            canonical_json(_thaw_json(frozen)).encode("utf-8")
        ).hexdigest()
        if self.status is StageStatus.SUCCESS:
            if self.output_sha256 is None:
                object.__setattr__(self, "output_sha256", calculated)
            elif _digest(self.output_sha256, "artifact.output_sha256") != calculated:
                raise ProtocolContractError(
                    "artifact output_sha256 does not match its data"
                )
        elif self.output_sha256 is not None:
            raise ProtocolContractError(
                "non-success artifact cannot carry an output digest"
            )

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "data": _thaw_json(self.data),
            "output_sha256": self.output_sha256,
            "effective_identity": _thaw_json(self.effective_identity),
            "invocation_index": self.invocation_index,
            "invoked": self.invoked,
            "policy_reason": self.policy_reason,
        }


@dataclass(frozen=True, slots=True)
class StageRequest:
    """Immutable invocation context shared by all stage handlers."""

    run_id: str
    case_id: str
    case_manifest_sha256: str
    variant_id: str = BASELINE_VARIANT
    split: Split = Split.PILOT
    cache_mode: CacheMode = CacheMode.COLD
    input_data: object = field(default_factory=dict)
    requested_identity: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    environment_sha256: str | None = None
    source: tuple[str, ...] = ("benchmark_input",)
    upstream_stage_digests: tuple[str, ...] = ()
    upstream_artifacts: tuple[StageArtifact, ...] = ()
    invocation_index: int = 0
    protocol_sha256: str = DEFAULT_PROTOCOL_SHA256
    deadline_unix_ms: int | None = None

    def __post_init__(self) -> None:
        _safe_id(self.run_id, "run_id")
        _safe_id(self.case_id, "case_id")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _safe_id(self.variant_id, "variant_id")
        if self.variant_id not in {f"A{i}" for i in range(13)} | {"S1"}:
            raise ProtocolContractError(f"variant_id is not registered: {self.variant_id!r}")
        if not isinstance(self.split, Split) or not isinstance(self.cache_mode, CacheMode):
            raise ProtocolContractError("split and cache_mode must use protocol enums")
        _digest(self.protocol_sha256, "protocol_sha256")
        if self.protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
            raise ProtocolContractError("request must bind frozen protocol revision 1")
        if self.environment_sha256 is not None:
            _digest(self.environment_sha256, "environment_sha256")
        if not isinstance(self.source, tuple) or not self.source:
            raise ProtocolContractError("source must be a nonempty tuple")
        if len(self.source) > len(STAGE_ORDER):
            raise ProtocolContractError("source contains too many entries")
        for item in self.source:
            if not isinstance(item, str) or not item.strip() or len(item) > 256:
                raise ProtocolContractError("source entries must be bounded strings")
        if not isinstance(self.upstream_stage_digests, tuple):
            raise ProtocolContractError("upstream_stage_digests must be a tuple")
        for digest in self.upstream_stage_digests:
            _digest(digest, "upstream_stage_digests[]")
        if not isinstance(self.upstream_artifacts, tuple):
            raise ProtocolContractError("upstream_artifacts must be a tuple")
        if len(self.upstream_artifacts) > len(StageName):
            raise ProtocolContractError("too many upstream stage artifacts")
        if not all(
            isinstance(artifact, StageArtifact)
            for artifact in self.upstream_artifacts
        ):
            raise ProtocolContractError(
                "upstream_artifacts must contain StageArtifact values"
            )
        artifact_stages = tuple(
            artifact.stage for artifact in self.upstream_artifacts
        )
        if len(set(artifact_stages)) != len(artifact_stages):
            raise ProtocolContractError(
                "upstream_artifacts must not contain duplicate stages"
            )
        if (
            isinstance(self.invocation_index, bool)
            or not isinstance(self.invocation_index, int)
            or not 0 <= self.invocation_index < len(StageName)
        ):
            raise ProtocolContractError(
                "invocation_index must be a bounded integer"
            )
        if (
            self.deadline_unix_ms is not None
            and (
                isinstance(self.deadline_unix_ms, bool)
                or not isinstance(self.deadline_unix_ms, int)
                or self.deadline_unix_ms < 0
            )
        ):
            raise ProtocolContractError(
                "deadline_unix_ms must be a nonnegative integer or null"
            )
        identity = _freeze_mapping(
            self.requested_identity, "requested_identity"
        )
        object.__setattr__(self, "requested_identity", identity)
        _input_digest(self.input_data)

    @property
    def input_sha256(self) -> str:
        return _input_digest(self.input_data)[0]

    @property
    def input_bytes(self) -> int:
        return _input_digest(self.input_data)[1]

    def with_upstream(self, digest: str) -> "StageRequest":
        _digest(digest, "upstream_stage_digest")
        return replace(
            self,
            upstream_stage_digests=(*self.upstream_stage_digests, digest),
        )

    def with_artifact(self, artifact: StageArtifact) -> "StageRequest":
        if not isinstance(artifact, StageArtifact):
            raise ProtocolContractError("artifact must be a StageArtifact")
        return replace(
            self,
            upstream_artifacts=(*self.upstream_artifacts, artifact),
        )

    def artifact(self, stage: StageName) -> StageArtifact | None:
        """Return the typed upstream output for ``stage``, when scheduled."""

        return next(
            (
                artifact
                for artifact in self.upstream_artifacts
                if artifact.stage is stage
            ),
            None,
        )


def _mapping_subset(
    value: object,
    keys: Sequence[str],
) -> dict[str, object]:
    """Return a detached allowlisted projection of one evidence mapping."""

    if not isinstance(value, Mapping):
        return {}
    return {
        key: _thaw_json(value[key])
        for key in keys
        if key in value
    }


def _mapping_sequence_prefix(
    value: object,
    keys: Sequence[str],
    *,
    maximum: int,
) -> list[dict[str, object]]:
    """Bound one sequence of evidence records without using evaluator labels."""

    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        return []
    return [
        _mapping_subset(item, keys)
        for item in value[:maximum]
        if isinstance(item, Mapping)
    ]


def _semantic_artifact_projection(
    artifact: StageArtifact,
) -> dict[str, object]:
    """Project one upstream semantic artifact into a label-blind model input.

    The projection deliberately allowlists only stage-generated linguistic or
    semantic evidence.  Benchmark evaluator fields such as ``expected_class``,
    ``expected_ir``, difficulty, and negative controls never enter this
    function and therefore cannot cross either model boundary.
    """

    projection: dict[str, object] = {
        "stage": artifact.stage.value,
        "artifact_sha256": artifact.digest,
        "output_sha256": artifact.output_sha256,
        "invoked": artifact.invoked,
        "status": artifact.status.value,
        "policy_reason": artifact.policy_reason,
    }
    if (
        not artifact.invoked
        or artifact.status is not StageStatus.SUCCESS
        or not isinstance(artifact.data, Mapping)
    ):
        return projection
    data = artifact.data
    if artifact.stage is StageName.SPACY:
        if data.get("schema") != SPACY_EVIDENCE_SCHEMA:
            raise ProtocolContractError(
                "spaCy semantic context used an unsupported evidence schema"
            )
        modal_ir = data.get("modal_ir")
        modal_projection: dict[str, object] = {}
        if isinstance(modal_ir, Mapping):
            modal_projection = _mapping_subset(
                modal_ir,
                (
                    "version",
                    "document_id",
                    "source",
                    "normalized_text",
                    "metadata",
                    "frame_candidates",
                    "frame_logic",
                ),
            )
            modal_projection["formulas"] = _mapping_sequence_prefix(
                modal_ir.get("formulas"),
                (
                    "formula_id",
                    "operator",
                    "predicate",
                    "conditions",
                    "exceptions",
                    "provenance",
                    "metadata",
                ),
                maximum=16,
            )
            modal_projection["modal_ir_sha256"] = hashlib.sha256(
                canonical_json(_thaw_json(modal_ir)).encode("utf-8")
            ).hexdigest()
        projection["evidence"] = {
            "schema": data.get("schema"),
            "document": _mapping_subset(
                data.get("document"),
                (
                    "document_id",
                    "text_sha256",
                    "normalized_text",
                    "citation",
                    "source",
                ),
            ),
            "execution": _mapping_subset(
                data.get("execution"),
                (
                    "mode",
                    "requested_model",
                    "effective_model",
                    "used_fallback_model",
                    "language",
                    "pipeline",
                    "parser_backend",
                    "srl_backend",
                    "model_version",
                    "model_meta_sha256",
                    "configuration_sha256",
                    "variant_id",
                ),
            ),
            "sentences": _mapping_sequence_prefix(
                data.get("sentences"),
                ("text", "start_char", "end_char"),
                maximum=16,
            ),
            "tokens": _mapping_sequence_prefix(
                data.get("tokens"),
                (
                    "text",
                    "lemma",
                    "lower",
                    "pos",
                    "dep",
                    "start_char",
                    "end_char",
                ),
                maximum=96,
            ),
            "entities": _mapping_sequence_prefix(
                data.get("entities"),
                ("text", "label", "start_char", "end_char"),
                maximum=32,
            ),
            "semantic_roles": _mapping_sequence_prefix(
                data.get("semantic_roles"),
                (
                    "frame_id",
                    "sentence",
                    "predicate",
                    "predicate_span",
                    "arguments",
                    "confidence",
                    "source",
                ),
                maximum=24,
            ),
            "modal_cues": _mapping_sequence_prefix(
                data.get("modal_cues"),
                (
                    "cue",
                    "family",
                    "system",
                    "symbol",
                    "label",
                    "start_char",
                    "end_char",
                    "token_indices",
                ),
                maximum=32,
            ),
            "modal_ir": modal_projection,
        }
    elif artifact.stage is StageName.SYMAI:
        if data.get("schema") == SYMAI_EVIDENCE_SCHEMA:
            projection["evidence"] = _mapping_subset(
                data,
                (
                    "schema",
                    "candidate_ir",
                    "candidate_ir_sha256",
                    "normalized_predicates",
                    "quantifiers",
                    "entities",
                    "ambiguity_flags",
                    "confidence",
                    "validation_errors",
                    "assurance",
                ),
            )
        elif data.get("schema") == (
            "ipfs-datasets.logic-pipeline-benchmark.policy-decision.v1"
        ):
            projection["evidence"] = _mapping_subset(
                data,
                ("schema", "stage", "invoked", "reason", "invocation_index"),
            )
        else:
            raise ProtocolContractError(
                "SyMAI semantic context used an unsupported evidence schema"
            )
    else:
        raise ProtocolContractError(
            "semantic context accepts only spaCy and SyMAI artifacts"
        )
    return projection


def build_upstream_semantic_context(
    request: StageRequest,
    *,
    stages: Sequence[StageName] = (
        StageName.SPACY,
        StageName.SYMAI,
    ),
    require_present: Sequence[StageName] = (),
    require_success: Sequence[StageName] = (),
) -> dict[str, object]:
    """Build the exact compact semantic input consumed by model/proof stages."""

    required = set(require_success)
    present = set(require_present) | required
    if not present.issubset(set(stages)):
        raise ProtocolContractError(
            "required semantic stages must be included in the projection"
        )
    artifacts: list[dict[str, object]] = []
    measured_request = _is_frozen_ablation_request(request)
    for stage in stages:
        if stage not in {StageName.SPACY, StageName.SYMAI}:
            raise ProtocolContractError(
                "semantic context stages must be spaCy or SyMAI"
            )
        artifact = request.artifact(stage)
        if artifact is None:
            if stage in present:
                raise ProtocolContractError(
                    f"required {stage.value} semantic artifact is missing"
                )
            continue
        graph_invoked = artifact.effective_identity.get("graph_invoked")
        if measured_request and type(graph_invoked) is not bool:
            raise ProtocolContractError(
                f"{stage.value} semantic artifact omitted graph_invoked"
            )
        if (
            graph_invoked is not None
            and (
                type(graph_invoked) is not bool
                or graph_invoked is not artifact.invoked
            )
        ):
            raise ProtocolContractError(
                f"{stage.value} semantic artifact invocation receipt is inconsistent"
            )
        if (
            not artifact.invoked
            and (
                not isinstance(artifact.data, Mapping)
                or artifact.data.get("invoked") is not False
            )
        ):
            raise ProtocolContractError(
                f"{stage.value} gated artifact omitted invoked=false"
            )
        if stage in required and (
            not artifact.invoked
            or artifact.status is not StageStatus.SUCCESS
        ):
            raise ProtocolContractError(
                f"required {stage.value} semantic artifact is not successful"
            )
        artifacts.append(_semantic_artifact_projection(artifact))
    source_text = None
    if isinstance(request.input_data, Mapping):
        source_text = request.input_data.get(
            "text", request.input_data.get("source_text")
        )
    source_sha256 = (
        hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        if isinstance(source_text, str)
        else None
    )
    context_without_digest = {
        "schema": SEMANTIC_CONTEXT_SCHEMA,
        "source_text_sha256": source_sha256,
        "artifacts": artifacts,
    }
    encoded = canonical_json(context_without_digest).encode("utf-8")
    if len(encoded) > SEMANTIC_CONTEXT_MAX_BYTES:
        raise ProtocolContractError(
            "upstream semantic context exceeds its byte bound"
        )
    return {
        **context_without_digest,
        "context_sha256": hashlib.sha256(encoded).hexdigest(),
    }


@dataclass(frozen=True, slots=True)
class StageOutput:
    """Optional handler result with explicit status and effective identity."""

    data: object = field(default_factory=dict)
    status: StageStatus = StageStatus.SUCCESS
    effective_identity: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    failure_code: FailureCode | None = None
    failure_detail: str | None = None
    telemetry: TelemetryRecord | None = None
    kernel_accepted: bool = False
    kernel_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, StageStatus):
            raise ProtocolContractError("status must be a StageStatus")
        _freeze_mapping(self.effective_identity, "effective_identity")
        if self.failure_code is not None and not isinstance(
            self.failure_code, FailureCode
        ):
            raise ProtocolContractError("failure_code must be a FailureCode")
        if self.failure_detail is not None and (
            not isinstance(self.failure_detail, str)
            or not self.failure_detail.strip()
            or len(self.failure_detail) > _MAX_DETAIL_LENGTH
        ):
            raise ProtocolContractError("failure_detail is empty or too long")
        if self.telemetry is not None and not isinstance(self.telemetry, TelemetryRecord):
            raise ProtocolContractError("telemetry must be a TelemetryRecord")
        if not isinstance(self.kernel_accepted, bool):
            raise ProtocolContractError("kernel_accepted must be a boolean")


StageHandler = Callable[[StageRequest], object]


@dataclass(frozen=True, slots=True)
class StageInvocation:
    """One bounded handler invocation before canonical record materialization."""

    output: StageOutput
    telemetry: TelemetryRecord

    def __post_init__(self) -> None:
        if not isinstance(self.output, StageOutput):
            raise ProtocolContractError(
                "invocation output must be a StageOutput"
            )
        if not isinstance(self.telemetry, TelemetryRecord):
            raise ProtocolContractError(
                "invocation telemetry must be a TelemetryRecord"
            )


@dataclass(frozen=True, slots=True)
class StageAdapter:
    """A versioned adapter around one explicitly injected stage callable."""

    stage: StageName
    handler: StageHandler | None = field(default=None, repr=False, compare=False)
    adapter_version: str = ADAPTER_VERSION
    adapter_id: str | None = None
    source: tuple[str, ...] = (ADAPTER_SOURCE,)
    resource_lane: ResourceLane | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, StageName):
            raise ProtocolContractError("stage must be a StageName")
        _safe_id(self.adapter_version, "adapter_version")
        adapter_id = self.adapter_id or f"{self.stage.value}-adapter"
        _safe_id(adapter_id, "adapter_id")
        object.__setattr__(self, "adapter_id", adapter_id)
        if self.resource_lane is None:
            lane = {
                StageName.SYMAI: ResourceLane.MODEL,
                StageName.LEANSTRAL: ResourceLane.MODEL,
                StageName.HAMMER: ResourceLane.SOLVER,
                StageName.KERNEL: ResourceLane.KERNEL,
            }.get(self.stage, ResourceLane.CPU)
            object.__setattr__(self, "resource_lane", lane)
        elif not isinstance(self.resource_lane, ResourceLane):
            raise ProtocolContractError("resource_lane must be a ResourceLane")
        if not isinstance(self.source, tuple) or not self.source:
            raise ProtocolContractError("source must be a nonempty tuple")
        for item in self.source:
            if not isinstance(item, str) or not item.strip() or len(item) > 256:
                raise ProtocolContractError("source entries must be bounded strings")
        if self.handler is not None and not callable(self.handler):
            raise ProtocolContractError("handler must be callable")

    def _telemetry(
        self,
        request: StageRequest,
        *,
        started_wall: float,
        started_cpu: float,
        output: StageOutput | None,
        output_bytes: int = 0,
    ) -> TelemetryRecord:
        supplied = None if output is None else output.telemetry
        if supplied is not None:
            return supplied
        return TelemetryRecord(
            wall_time_ms=round(max(0.0, time.perf_counter() - started_wall) * 1000, 6),
            cpu_time_ms=round(max(0.0, time.process_time() - started_cpu) * 1000, 6),
            input_items=1,
            output_items=1 if output is not None and output.status is StageStatus.SUCCESS else 0,
            model_calls=1 if self.stage in {StageName.SYMAI, StageName.LEANSTRAL} else 0,
            bytes_in=request.input_bytes,
            bytes_out=output_bytes,
            resource_lane=self.resource_lane or ResourceLane.CPU,
        )

    def _provenance(
        self, request: StageRequest, effective_identity: Mapping[str, object]
    ) -> StageProvenance:
        return StageProvenance(
            schema="ipfs-datasets.logic-pipeline-benchmark.stage-provenance.v1",
            adapter_id=self.adapter_id or f"{self.stage.value}-adapter",
            adapter_version=self.adapter_version,
            source=tuple((*self.source, *request.source)),
            requested_identity=request.requested_identity,
            effective_identity=effective_identity,
            input_sha256=request.input_sha256,
            environment_sha256=request.environment_sha256,
            upstream_stage_digests=request.upstream_stage_digests,
        )

    def invoke(
        self,
        request: StageRequest,
        *,
        telemetry: TelemetryRecord | None = None,
    ) -> StageInvocation:
        """Invoke the handler once and retain a typed, bounded result."""

        if not isinstance(request, StageRequest):
            raise ProtocolContractError("request must be a StageRequest")
        if request.protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
            raise ProtocolContractError("request must bind frozen protocol revision 1")
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        result: StageOutput
        if self.handler is None:
            result = StageOutput(
                status=StageStatus.UNAVAILABLE,
                effective_identity=request.requested_identity,
                failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
                failure_detail=f"{self.stage.value} handler was not configured",
            )
        else:
            try:
                raw = self.handler(request)
                result = raw if isinstance(raw, StageOutput) else StageOutput(data=raw)
            except Exception as exc:  # boundary must retain failure, not escape telemetry
                result = StageOutput(
                    status=StageStatus.FAILED,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
                    failure_detail=f"{self.stage.value} adapter raised {type(exc).__name__}",
                )
        effective_identity = result.effective_identity or request.requested_identity
        encoded_output = b""
        if result.status is StageStatus.SUCCESS:
            encoded_output = canonical_json(result.data).encode("utf-8")
        measured = telemetry or self._telemetry(
            request,
            started_wall=started_wall,
            started_cpu=started_cpu,
            output=result,
            output_bytes=len(encoded_output),
        )
        if measured.resource_lane is not self.resource_lane:
            raise ProtocolContractError(
                f"{self.stage.value} telemetry must use {self.resource_lane.value} resource lane"
            )
        if self.stage is not StageName.KERNEL and result.kernel_accepted:
            # Convert an accidental model/solver claim into an explicit failed
            # stage rather than allowing it to reach a final result.
            result = StageOutput(
                status=StageStatus.FAILED,
                effective_identity=effective_identity,
                failure_code=FailureCode.SAFETY_CONTROL_FAILURE,
                failure_detail="non-kernel stage attempted kernel acceptance",
                telemetry=measured,
            )
        if result.effective_identity != effective_identity:
            result = replace(result, effective_identity=effective_identity)
        return StageInvocation(result, measured)

    def record(
        self,
        request: StageRequest,
        invocation: StageInvocation,
    ) -> StageRecord:
        """Materialize a previously invoked result into a canonical record."""

        if not isinstance(request, StageRequest):
            raise ProtocolContractError("request must be a StageRequest")
        if not isinstance(invocation, StageInvocation):
            raise ProtocolContractError(
                "invocation must be a StageInvocation"
            )
        result = invocation.output
        effective_identity = (
            result.effective_identity or request.requested_identity
        )
        measured = invocation.telemetry
        if measured.resource_lane is not self.resource_lane:
            raise ProtocolContractError(
                f"{self.stage.value} telemetry must use {self.resource_lane.value} resource lane"
            )
        return StageRecord.create(
            protocol_sha256=request.protocol_sha256,
            run_id=request.run_id,
            case_id=request.case_id,
            case_manifest_sha256=request.case_manifest_sha256,
            variant_id=request.variant_id,
            split=request.split,
            cache_mode=request.cache_mode,
            stage=self.stage,
            adapter_version=self.adapter_version,
            status=result.status,
            provenance=self._provenance(request, effective_identity),
            telemetry=measured,
            data=result.data,
            failure_code=result.failure_code,
            failure_detail=result.failure_detail,
            kernel_accepted=result.kernel_accepted,
            kernel_receipt_sha256=result.kernel_receipt_sha256,
        )

    def run(
        self,
        request: StageRequest,
        *,
        telemetry: TelemetryRecord | None = None,
    ) -> StageRecord:
        """Execute the injected handler and always return a strict record."""

        return self.record(
            request,
            self.invoke(request, telemetry=telemetry),
        )

    execute = run


class CompilerAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        super().__init__(StageName.COMPILER, handler=handler, **kwargs)


def HSSLEV0310F79() -> str:
    """Return the AST-verifiable spaCy linguistic-evidence receipt."""

    return (
        "reproducible spaCy tokens, sentences, lemmas, dependencies, entities, "
        "semantic roles, modal cues, and explicit fallback identity"
    )


def _spacy_request_document(
    request: StageRequest,
    config: SpacyAdapterConfig,
) -> tuple[str, str, str | None, str]:
    """Validate and return text, document id, citation, and source."""

    data = request.input_data
    if isinstance(data, str):
        text = data
        document_id = request.case_id
        citation = None
        source = "benchmark_input"
    elif isinstance(data, Mapping):
        raw_text = data.get("text")
        legacy_source = data.get("source")
        if raw_text is None and isinstance(legacy_source, str):
            # StageRequest examples historically use ``source`` for source
            # text.  Keep that input form while preferring the unambiguous
            # ``text`` key in new records.
            raw_text = legacy_source
        if not isinstance(raw_text, str):
            raise ProtocolContractError(
                "spaCy input_data must contain a string text field"
            )
        text = raw_text
        document_id = data.get("document_id", request.case_id)
        citation = data.get("citation")
        source = data.get(
            "source_name",
            (
                legacy_source
                if data.get("text") is not None and isinstance(legacy_source, str)
                else "benchmark_input"
            ),
        )
    else:
        raise ProtocolContractError(
            "spaCy input_data must be text or an object containing text"
        )
    if not text.strip():
        raise ProtocolContractError("spaCy input text must not be empty")
    if len(text.encode("utf-8")) > config.max_text_bytes:
        raise ProtocolContractError(
            f"spaCy input text exceeds {config.max_text_bytes} encoded bytes"
        )
    _safe_id(document_id, "document_id")
    if citation is not None and (
        not isinstance(citation, str)
        or not citation.strip()
        or len(citation) > 256
    ):
        raise ProtocolContractError("citation must be a bounded nonempty string")
    if (
        not isinstance(source, str)
        or not source.strip()
        or len(source) > 256
    ):
        raise ProtocolContractError("source_name must be a bounded nonempty string")
    return text, document_id, citation, source


def _spacy_failure(
    request: StageRequest,
    detail: str,
    *,
    unavailable: bool = False,
    effective_identity: Mapping[str, object] | None = None,
    failure_code: FailureCode = FailureCode.SPACY_PARSE_OR_MODEL_FALLBACK,
) -> StageOutput:
    """Build a bounded fail-closed spaCy result."""

    return StageOutput(
        status=StageStatus.UNAVAILABLE if unavailable else StageStatus.FAILED,
        effective_identity=(
            request.requested_identity
            if effective_identity is None
            else effective_identity
        ),
        failure_code=(
            FailureCode.CAPABILITY_UNAVAILABLE if unavailable else failure_code
        ),
        failure_detail=detail[:_MAX_DETAIL_LENGTH],
    )


def _spacy_frame_value(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _spacy_semantic_roles(frames: object) -> list[dict[str, object]]:
    """Serialize SRL frames without their UUID defaults.

    ``SRLFrame`` intentionally uses UUIDs for graph node identity.  Those IDs
    are inappropriate in a reproducible benchmark record, so the adapter
    derives each frame ID from its stable linguistic content instead.
    """

    if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes)):
        raise ProtocolContractError("semantic-role extractor must return a sequence")
    normalized: list[dict[str, object]] = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            serializer = getattr(frame, "to_dict", None)
            if callable(serializer):
                serialized_frame = serializer()
                if not isinstance(serialized_frame, Mapping):
                    raise ProtocolContractError(
                        "semantic-role frame must serialize to an object"
                    )
                frame = serialized_frame
        raw_arguments = _spacy_frame_value(frame, "arguments", ())
        if not isinstance(raw_arguments, Sequence) or isinstance(
            raw_arguments, (str, bytes)
        ):
            raise ProtocolContractError("semantic-role arguments must be a sequence")
        arguments: list[dict[str, object]] = []
        for argument in raw_arguments:
            span = _spacy_frame_value(argument, "span")
            serialized_span = None
            if span is not None:
                if (
                    not isinstance(span, Sequence)
                    or isinstance(span, (str, bytes))
                    or len(span) != 2
                    or not all(isinstance(item, int) for item in span)
                ):
                    raise ProtocolContractError(
                        "semantic-role argument span must contain two integers"
                    )
                serialized_span = [int(span[0]), int(span[1])]
            arguments.append(
                {
                    "role": str(_spacy_frame_value(argument, "role", "")),
                    "text": str(_spacy_frame_value(argument, "text", "")),
                    "span": serialized_span,
                    "confidence": float(
                        _spacy_frame_value(argument, "confidence", 0.0)
                    ),
                }
            )
        arguments.sort(
            key=lambda item: (
                item["span"] is None,
                item["span"] or [-1, -1],
                item["role"],
                item["text"],
            )
        )
        predicate_span = _spacy_frame_value(frame, "predicate_span")
        serialized_predicate_span = None
        if predicate_span is not None:
            if (
                not isinstance(predicate_span, Sequence)
                or isinstance(predicate_span, (str, bytes))
                or len(predicate_span) != 2
                or not all(isinstance(item, int) for item in predicate_span)
            ):
                raise ProtocolContractError(
                    "semantic-role predicate span must contain two integers"
                )
            serialized_predicate_span = [
                int(predicate_span[0]),
                int(predicate_span[1]),
            ]
        body: dict[str, object] = {
            "predicate": str(_spacy_frame_value(frame, "predicate", "")),
            "predicate_span": serialized_predicate_span,
            "sentence": str(_spacy_frame_value(frame, "sentence", "")),
            "arguments": arguments,
            "confidence": float(_spacy_frame_value(frame, "confidence", 0.0)),
            "source": str(_spacy_frame_value(frame, "source", "")),
        }
        body["frame_id"] = (
            "srl-"
            + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()[:24]
        )
        normalized.append(body)
    normalized.sort(
        key=lambda item: (
            item["predicate_span"] is None,
            item["predicate_span"] or [-1, -1],
            item["predicate"],
            item["frame_id"],
        )
    )
    return normalized


def _spacy_entities(doc: object) -> list[dict[str, object]]:
    entities: list[dict[str, object]] = []
    for entity in getattr(doc, "ents", ()):
        entities.append(
            {
                "text": str(getattr(entity, "text", "")),
                "label": str(getattr(entity, "label_", "")),
                "start_char": int(getattr(entity, "start_char", 0)),
                "end_char": int(getattr(entity, "end_char", 0)),
            }
        )
    entities.sort(
        key=lambda item: (
            item["start_char"],
            item["end_char"],
            item["label"],
            item["text"],
        )
    )
    return entities


def _spacy_dependencies(doc: object) -> list[dict[str, object]]:
    dependencies: list[dict[str, object]] = []
    for index, token in enumerate(doc):
        dep = str(getattr(token, "dep_", ""))
        if not dep:
            continue
        head = getattr(token, "head", token)
        dependencies.append(
            {
                "token_index": int(getattr(token, "i", index)),
                "head_index": int(getattr(head, "i", index)),
                "dep": dep,
                "label": dep,
            }
        )
    dependencies.sort(key=lambda item: (item["token_index"], item["head_index"]))
    return dependencies


_SPACY_REGEX_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*|[^\w\s]")


def _regex_legal_tokens(normalized_text: str) -> list[dict[str, object]]:
    return [
        {
            "text": match.group(0),
            "lemma": match.group(0).lower(),
            "lower": match.group(0).lower(),
            "pos": "",
            "dep": "",
            "start_char": match.start(),
            "end_char": match.end(),
            "is_stop": False,
            "is_alpha": match.group(0).isalpha(),
        }
        for match in _SPACY_REGEX_TOKEN.finditer(normalized_text)
    ]


def _modal_cues_from_ir(modal_ir: Mapping[str, object]) -> list[dict[str, object]]:
    raw_formulas = modal_ir.get("formulas", ())
    if not isinstance(raw_formulas, Sequence):
        raise ProtocolContractError("legal parser formulas must be a sequence")
    cues: list[dict[str, object]] = []
    for formula in raw_formulas:
        if not isinstance(formula, Mapping):
            raise ProtocolContractError("legal parser formula must be an object")
        metadata = formula.get("metadata", {})
        operator = formula.get("operator", {})
        provenance = formula.get("provenance", {})
        if not all(isinstance(item, Mapping) for item in (metadata, operator, provenance)):
            raise ProtocolContractError("legal parser formula metadata is malformed")
        cue = metadata.get("cue")
        if not isinstance(cue, str) or not cue:
            continue
        cues.append(
            {
                "cue": cue,
                "family": str(operator.get("family", "")),
                "system": str(operator.get("system", "")),
                "symbol": str(operator.get("symbol", "")),
                "label": str(operator.get("label", "")),
                "start_char": int(
                    metadata.get("cue_start_char", provenance.get("start_char", 0))
                ),
                "end_char": int(
                    metadata.get("cue_end_char", provenance.get("end_char", 0))
                ),
                "token_indices": [],
            }
        )
    cues.sort(
        key=lambda item: (
            item["start_char"],
            item["end_char"],
            item["family"],
            item["symbol"],
        )
    )
    return cues


def _default_spacy_encoder(config: SpacyAdapterConfig) -> object:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
        SpaCyLegalEncoder,
    )

    encoder = SpaCyLegalEncoder(model_name=config.requested_model)
    if config.mode is SpacyAdapterMode.BLANK_MODEL and not encoder.used_fallback_model:
        # A blank run is an explicit ablation even on hosts where the requested
        # package happens to be installed.
        import spacy

        nlp = spacy.blank(config.language)
        if "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")
        encoder.nlp = nlp
        encoder.used_fallback_model = True
    return encoder


def _default_srl_extractor(nlp: object | None) -> object:
    from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

    return SRLExtractor(nlp=nlp)


def _default_legal_parser() -> object:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import (
        LegalModalParser,
    )

    return LegalModalParser()


def _default_spacy_modal_compiler() -> object:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
        SpaCyModalIRCompiler,
    )

    return SpaCyModalIRCompiler()


def _spacy_evidence_handler(
    config: SpacyAdapterConfig,
    *,
    encoder_factory: Callable[[SpacyAdapterConfig], object],
    srl_factory: Callable[[object | None], object],
    legal_parser_factory: Callable[[], object],
    modal_compiler_factory: Callable[[], object],
) -> StageHandler:
    def handler(request: StageRequest) -> StageOutput:
        try:
            text, document_id, citation, source = _spacy_request_document(
                request, config
            )
        except ProtocolContractError as exc:
            return _spacy_failure(
                request,
                str(exc),
                failure_code=FailureCode.FIXTURE_INVALID,
            )

        try:
            if config.mode is SpacyAdapterMode.REGEX_LEGAL:
                parser = legal_parser_factory()
                modal_ir_object = parser.parse(
                    text,
                    document_id=document_id,
                    citation=citation,
                    source=source,
                )
                modal_ir = modal_ir_object.to_dict()
                normalized_text = str(modal_ir.get("normalized_text", text.strip()))
                segments = parser.segment(normalized_text)
                sentences = [
                    {
                        "text": str(getattr(segment, "text", "")),
                        "start_char": int(getattr(segment, "start_char", 0)),
                        "end_char": int(getattr(segment, "end_char", 0)),
                    }
                    for segment in segments
                ]
                semantic_roles = _spacy_semantic_roles(
                    srl_factory(None).extract_srl(normalized_text)
                )
                tokens = _regex_legal_tokens(normalized_text)
                dependencies: list[dict[str, object]] = []
                entities: list[dict[str, object]] = []
                modal_cues = _modal_cues_from_ir(modal_ir)
                used_fallback = False
                effective_model = "regex-legal-parser-v1"
                package_version = None
                pipeline: list[str] = []
                model_version = "1"
                model_language = config.language
                model_meta_sha256 = hashlib.sha256(
                    canonical_json(
                        {
                            "name": effective_model,
                            "version": model_version,
                            "language": model_language,
                            "pipeline": pipeline,
                        }
                    ).encode("utf-8")
                ).hexdigest()
                parser_backend = "legal_modal_parser_v1"
                srl_backend = "heuristic"
            else:
                encoder = encoder_factory(config)
                encoding = encoder.encode(
                    text,
                    document_id=document_id,
                    citation=citation,
                    source=source,
                )
                used_fallback = bool(
                    getattr(
                        encoding,
                        "used_fallback_model",
                        getattr(encoder, "used_fallback_model", False),
                    )
                )
                nlp = getattr(encoder, "nlp", None)
                pipe_names = list(getattr(nlp, "pipe_names", ()))
                raw_model_meta = getattr(nlp, "meta", {})
                model_meta = (
                    raw_model_meta if isinstance(raw_model_meta, Mapping) else {}
                )
                model_version = str(model_meta.get("version", ""))
                model_language = str(model_meta.get("lang", config.language))
                model_meta_sha256 = hashlib.sha256(
                    canonical_json(
                        {
                            "name": str(
                                model_meta.get("name", config.requested_model)
                            ),
                            "version": model_version,
                            "language": model_language,
                            "pipeline": pipe_names,
                        }
                    ).encode("utf-8")
                ).hexdigest()
                identity = {
                    **dict(request.requested_identity),
                    "requested_model": config.requested_model,
                    "effective_model": (
                        f"spacy.blank:{config.language}"
                        if used_fallback
                        else config.requested_model
                    ),
                    "mode": config.mode.value,
                    "used_fallback_model": used_fallback,
                    "pipeline": pipe_names,
                    "model_version": model_version,
                    "model_language": model_language,
                    "model_meta_sha256": model_meta_sha256,
                }
                if (
                    config.mode is SpacyAdapterMode.FULL_MODEL
                    and used_fallback
                ):
                    return _spacy_failure(
                        request,
                        f"requested spaCy model {config.requested_model!r} is "
                        "unavailable; blank fallback refused",
                        unavailable=True,
                        effective_identity=identity,
                    )
                if (
                    config.mode is SpacyAdapterMode.BLANK_MODEL
                    and not used_fallback
                ):
                    return _spacy_failure(
                        request,
                        "blank-model mode did not produce a blank spaCy pipeline",
                        effective_identity=identity,
                    )
                encoding_data = encoding.to_dict()
                if not isinstance(encoding_data, Mapping):
                    raise ProtocolContractError(
                        "SpaCyLegalEncoder output must serialize to an object"
                    )
                normalized_text = str(
                    encoding_data.get("normalized_text", text.strip())
                )
                tokens = list(encoding_data.get("tokens", ()))
                sentences = list(encoding_data.get("sentences", ()))
                modal_cues = list(encoding_data.get("cues", ()))
                doc = nlp(normalized_text)
                dependencies = _spacy_dependencies(doc)
                entities = _spacy_entities(doc)
                semantic_roles = _spacy_semantic_roles(
                    srl_factory(nlp).extract_srl(normalized_text)
                )
                modal_ir_object = modal_compiler_factory().compile(encoding)
                modal_ir = modal_ir_object.to_dict()
                effective_model = (
                    f"spacy.blank:{config.language}"
                    if used_fallback
                    else config.requested_model
                )
                try:
                    import spacy

                    package_version = str(spacy.__version__)
                except ImportError:
                    package_version = None
                pipeline = pipe_names
                parser_backend = "spacy_modal_codec_v1"
                srl_backend = "heuristic" if used_fallback else "spacy"

            effective_identity = {
                **dict(request.requested_identity),
                "requested_model": config.requested_model,
                "effective_model": effective_model,
                "mode": config.mode.value,
                "used_fallback_model": used_fallback,
                "language": config.language,
                "pipeline": pipeline,
                "model_version": model_version,
                "model_language": model_language,
                "model_meta_sha256": model_meta_sha256,
                "parser_backend": parser_backend,
                "srl_backend": srl_backend,
                "spacy_version": package_version,
            }
            payload = {
                "schema": SPACY_EVIDENCE_SCHEMA,
                "document": {
                    "document_id": document_id,
                    "source": source,
                    "citation": citation,
                    "normalized_text": normalized_text,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
                "tokens": tokens,
                "sentences": sentences,
                "dependencies": dependencies,
                "entities": entities,
                "semantic_roles": semantic_roles,
                "modal_cues": modal_cues,
                "modal_ir": modal_ir,
                "execution": effective_identity,
                "assurance": {
                    "evidence_only": True,
                    "semantic_proof": False,
                    "authoritative": False,
                    "kernel_checked": False,
                },
            }
            encoded = canonical_json(payload).encode("utf-8")
            if len(encoded) > SPACY_MAX_EVIDENCE_BYTES:
                return _spacy_failure(
                    request,
                    f"spaCy evidence exceeds {SPACY_MAX_EVIDENCE_BYTES} encoded bytes",
                    effective_identity=effective_identity,
                )
            return StageOutput(
                data=payload,
                effective_identity=effective_identity,
            )
        except (ImportError, ModuleNotFoundError, RuntimeError) as exc:
            return _spacy_failure(
                request,
                f"spaCy linguistic backend unavailable: {type(exc).__name__}",
                unavailable=True,
                effective_identity={
                    **dict(request.requested_identity),
                    "requested_model": config.requested_model,
                    "mode": config.mode.value,
                },
            )
        except (ProtocolContractError, AttributeError, TypeError, ValueError) as exc:
            return _spacy_failure(
                request,
                f"spaCy linguistic evidence rejected: {type(exc).__name__}: {exc}",
            )
        except Exception as exc:
            return _spacy_failure(
                request,
                f"spaCy linguistic adapter raised {type(exc).__name__}",
                failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
            )

    return handler


class SpacyAdapter(StageAdapter):
    """Stage adapter for injected or existing-path linguistic evidence.

    Passing no handler and no config preserves the dependency-free default
    route.  A config opts into lazy execution of the repository's spaCy modal,
    semantic-role, or regex/legal parser paths.
    """

    config: SpacyAdapterConfig | None

    def __init__(
        self,
        handler: StageHandler | None = None,
        *,
        config: SpacyAdapterConfig | None = None,
        encoder_factory: Callable[[SpacyAdapterConfig], object] | None = None,
        srl_factory: Callable[[object | None], object] | None = None,
        legal_parser_factory: Callable[[], object] | None = None,
        modal_compiler_factory: Callable[[], object] | None = None,
        **kwargs: object,
    ) -> None:
        if handler is not None and config is not None:
            raise ProtocolContractError(
                "SpacyAdapter accepts either an injected handler or a config"
            )
        if config is None and any(
            factory is not None
            for factory in (
                encoder_factory,
                srl_factory,
                legal_parser_factory,
                modal_compiler_factory,
            )
        ):
            raise ProtocolContractError(
                "spaCy component factories require a SpacyAdapterConfig"
            )
        if config is not None:
            if not isinstance(config, SpacyAdapterConfig):
                raise ProtocolContractError(
                    "config must be a SpacyAdapterConfig"
                )
            handler = _spacy_evidence_handler(
                config,
                encoder_factory=encoder_factory or _default_spacy_encoder,
                srl_factory=srl_factory or _default_srl_extractor,
                legal_parser_factory=legal_parser_factory or _default_legal_parser,
                modal_compiler_factory=(
                    modal_compiler_factory or _default_spacy_modal_compiler
                ),
            )
        object.__setattr__(self, "config", config)
        super().__init__(StageName.SPACY, handler=handler, **kwargs)


class SymaiAdapterContractError(ProtocolContractError):
    """Raised when SyMAI returns malformed or unsafe semantic evidence."""


class SymaiRecursiveRoutingError(SymaiAdapterContractError):
    """Raised when a SyMAI request would route back through SyMAI."""


SymaiEngineFactory = Callable[[SymaiAdapterConfig, str], object]
SymaiTraceGetter = Callable[[], Mapping[str, object]]


def HSSLEV0328B3A() -> str:
    """Return the AST-verifiable SyMAI existing-router evidence receipt."""

    return (
        "strict SyMAI semantic contracts through the existing llm_router with "
        "bounded retries and isolated cache namespaces"
    )


def _normalized_identity(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _is_recursive_symai_identity(value: object) -> bool:
    normalized = _normalized_identity(value)
    return normalized in _SYMAI_RECURSIVE_IDENTITIES or normalized.startswith(
        ("symai_", "symbolicai_")
    )


def _symai_routing_stack(request: StageRequest) -> tuple[str, ...]:
    values: list[object] = []
    sources = [request.requested_identity]
    if isinstance(request.input_data, Mapping):
        sources.append(request.input_data)
    for source in sources:
        for key in ("route_stack", "router_stack", "routing_stack"):
            if key not in source:
                continue
            raw = source[key]
            if isinstance(raw, str):
                values.extend(part for part in re.split(r"[,>\s]+", raw) if part)
            elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                values.extend(raw)
            else:
                raise SymaiRecursiveRoutingError(
                    f"{key} must be a string or sequence of route identifiers"
                )
    return tuple(_normalized_identity(value) for value in values)


def _reject_symai_recursion(
    request: StageRequest,
    *,
    metadata: Mapping[str, object] | None = None,
) -> None:
    stack = _symai_routing_stack(request)
    if any(_is_recursive_symai_identity(item) for item in stack):
        raise SymaiRecursiveRoutingError(
            "recursive SyMAI -> llm_router -> SyMAI routing is forbidden"
        )
    if metadata is None:
        return
    for key in (
        "backend",
        "effective_provider",
        "effective_provider_name",
        "provider",
        "route",
        "router_provider",
    ):
        if key in metadata and _is_recursive_symai_identity(metadata[key]):
            raise SymaiRecursiveRoutingError(
                f"llm_router resolved recursively to SyMAI via {key}"
            )


def _symai_request_text(request: StageRequest, config: SymaiAdapterConfig) -> str:
    value = request.input_data
    if isinstance(value, str):
        text = value
    elif isinstance(value, Mapping):
        text = value.get("text")
        if text is None:
            text = value.get("source_text")
    else:
        text = None
    if not isinstance(text, str) or not text.strip():
        raise SymaiAdapterContractError(
            "SyMAI input must contain a nonempty text or source_text string"
        )
    normalized = text.strip()
    if len(normalized.encode("utf-8")) > config.max_text_bytes:
        raise SymaiAdapterContractError(
            f"SyMAI input exceeds {config.max_text_bytes} encoded bytes"
        )
    return normalized


def _symai_cache_namespace(request: StageRequest) -> str:
    return CacheScope(
        run_id=request.run_id,
        protocol_sha256=request.protocol_sha256,
        variant_id=request.variant_id,
        split=request.split,
        mode=request.cache_mode,
    ).namespace


def _symai_cache_key(
    request: StageRequest,
    config: SymaiAdapterConfig,
    namespace: str,
    semantic_context: Mapping[str, object] | None = None,
) -> str:
    artifact_digests = [
        artifact.digest for artifact in request.upstream_artifacts
    ]
    digest = hashlib.sha256(
        canonical_json(
            {
                "schema": SYMAI_PROMPT_SCHEMA,
                "namespace": namespace,
                "case_id": request.case_id,
                "input_sha256": request.input_sha256,
                # During graph invocation the typed artifacts, rather than the
                # later durable-record chain, are the available inputs.  Hash
                # those exact artifacts so changing spaCy evidence cannot hit
                # a stale SyMAI cache entry.
                "upstream_artifact_sha256": artifact_digests,
                "semantic_context_sha256": (
                    None
                    if semantic_context is None
                    else semantic_context.get("context_sha256")
                ),
                "provider": config.provider,
                "model": config.model,
                "inner_route": {
                    "resolved_provider_name": config.expected_inner_provider,
                    "resolved_model_name": config.expected_inner_model,
                    "service_endpoint": config.expected_inner_endpoint,
                    "routing_backend": config.expected_inner_backend,
                },
                "dry_run": config.dry_run,
            }
        ).encode("utf-8")
    ).hexdigest()
    return f"{namespace}/stage/symai/{digest}"


def _symai_prompt(
    text: str,
    namespace: str,
    semantic_context: Mapping[str, object] | None = None,
) -> str:
    # Namespace and receipt-envelope fields belong to the cache/provenance
    # boundary, not to semantic inference.  Keeping them out of the prompt
    # avoids encouraging instruction-following models to reproduce the whole
    # request container instead of returning the seven-field contract.
    del namespace
    evidence: object = None
    if semantic_context is not None:
        concise_artifacts: list[dict[str, object]] = []
        raw_artifacts = semantic_context.get("artifacts", ())
        if isinstance(raw_artifacts, Sequence) and not isinstance(
            raw_artifacts, (str, bytes, bytearray)
        ):
            for artifact in raw_artifacts[:2]:
                if not isinstance(artifact, Mapping):
                    continue
                item: dict[str, object] = {
                    "stage": artifact.get("stage"),
                    "status": artifact.get("status"),
                    "invoked": artifact.get("invoked"),
                    "policy_reason": artifact.get("policy_reason"),
                }
                raw_linguistic = artifact.get("evidence")
                if isinstance(raw_linguistic, Mapping):
                    modal_ir = raw_linguistic.get("modal_ir")
                    formulas: list[dict[str, object]] = []
                    if isinstance(modal_ir, Mapping):
                        raw_formulas = modal_ir.get("formulas", ())
                        if isinstance(
                            raw_formulas, Sequence
                        ) and not isinstance(
                            raw_formulas, (str, bytes, bytearray)
                        ):
                            for formula in raw_formulas[:8]:
                                if not isinstance(formula, Mapping):
                                    continue
                                formulas.append(
                                    {
                                        "operator": _thaw_json(
                                            formula.get("operator")
                                        ),
                                        "predicate": _thaw_json(
                                            formula.get("predicate")
                                        ),
                                        "has_conditions": bool(
                                            formula.get("conditions")
                                        ),
                                        "has_exceptions": bool(
                                            formula.get("exceptions")
                                        ),
                                    }
                                )
                    roles: list[dict[str, object]] = []
                    raw_roles = raw_linguistic.get("semantic_roles", ())
                    if isinstance(raw_roles, Sequence) and not isinstance(
                        raw_roles, (str, bytes, bytearray)
                    ):
                        for role in raw_roles[:12]:
                            if not isinstance(role, Mapping):
                                continue
                            arguments = role.get("arguments", ())
                            roles.append(
                                {
                                    "predicate": role.get("predicate"),
                                    "arguments": (
                                        _thaw_json(arguments[:8])
                                        if isinstance(arguments, Sequence)
                                        and not isinstance(
                                            arguments,
                                            (str, bytes, bytearray),
                                        )
                                        else []
                                    ),
                                    "confidence": role.get("confidence"),
                                }
                            )
                    item["linguistic_evidence"] = {
                        # The model needs to know which linguistic backend
                        # produced the evidence, but it must not see the
                        # benchmark arm id or its configuration digest.  Those
                        # are provenance fields and would let otherwise
                        # identical semantic inputs vary by experimental arm.
                        "execution": _mapping_subset(
                            raw_linguistic.get("execution"),
                            (
                                "mode",
                                "requested_model",
                                "effective_model",
                                "used_fallback_model",
                                "language",
                                "pipeline",
                                "parser_backend",
                                "srl_backend",
                                "model_version",
                            ),
                        ),
                        "entities": _thaw_json(
                            raw_linguistic.get("entities", ())[:24]
                            if isinstance(
                                raw_linguistic.get("entities", ()),
                                Sequence,
                            )
                            else ()
                        ),
                        "semantic_roles": roles,
                        "modal_cues": _thaw_json(
                            raw_linguistic.get("modal_cues", ())[:24]
                            if isinstance(
                                raw_linguistic.get("modal_cues", ()),
                                Sequence,
                            )
                            else ()
                        ),
                        "modal_formulas": formulas,
                    }
                concise_artifacts.append(item)
        evidence = concise_artifacts
    evidence_json = canonical_json(evidence)
    if len(evidence_json.encode("utf-8")) > 12 * 1024:
        raise SymaiAdapterContractError(
            "concise SyMAI semantic evidence exceeds 12 KiB"
        )
    output_skeleton = {
        "candidate_ir": {"propositions": []},
        "normalized_predicates": [],
        "quantifiers": [],
        "entities": [],
        "ambiguity_flags": [],
        "confidence": 0.0,
        "validation_errors": [],
    }
    return (
        "Produce one concise, untrusted semantic interpretation. Return "
        "exactly one JSON object, under 1600 UTF-8 bytes, with the seven keys "
        "and value types shown in OUTPUT_SKELETON. Fill the skeleton; do not "
        "add wrapper keys. candidate_ir must be a small object with at most "
        "6 keys, nesting depth at most 3, and at most 12 items in any array. "
        "Each other array may contain at most 24 strings of at most 80 "
        "characters. confidence must be a number from 0 to 1. Never copy "
        "input-envelope or provenance keys such as schema, cache_namespace, "
        "task, upstream_semantic_context, source_text_sha256, artifacts, "
        "artifact_sha256, or output_sha256 into the top-level output. Do not "
        "repeat the source text or evidence container. Do not claim proof, "
        "kernel acceptance, verification, or authority. No Markdown.\n"
        "OUTPUT_SKELETON:\n"
        + canonical_json(output_skeleton)
        + "\nSOURCE_TEXT_JSON_STRING:\n"
        + canonical_json(text)
        + "\nOPTIONAL_READ_ONLY_SEMANTIC_EVIDENCE_JSON:\n"
        + evidence_json
    )


def _is_frozen_ablation_request(request: StageRequest) -> bool:
    """Return whether a request binds the exact registered arm definition."""

    try:
        from .variants import get_variant_definition

        definition = get_variant_definition(request.variant_id)
    except (ImportError, ProtocolContractError):
        return False
    return (
        request.requested_identity.get("variant_id") == request.variant_id
        and request.requested_identity.get("configuration_sha256")
        == definition.digest
    )


def _symai_input_semantic_context(
    request: StageRequest,
) -> dict[str, object]:
    measured_semantic_arm = (
        _is_frozen_ablation_request(request)
        and request.variant_id in {f"A{index}" for index in range(4, 13)}
    )
    return build_upstream_semantic_context(
        request,
        stages=(StageName.SPACY,),
        require_success=(
            (StageName.SPACY,) if measured_semantic_arm else ()
        ),
    )


def _semantic_context_binding(
    semantic_context: Mapping[str, object],
) -> dict[str, object]:
    artifacts = semantic_context.get("artifacts", ())
    artifact_sha256s: list[str] = []
    if isinstance(artifacts, Sequence) and not isinstance(
        artifacts, (str, bytes, bytearray)
    ):
        for artifact in artifacts:
            if isinstance(artifact, Mapping):
                digest = artifact.get("artifact_sha256")
                if isinstance(digest, str):
                    artifact_sha256s.append(digest)
    return {
        "schema": SEMANTIC_CONTEXT_SCHEMA,
        "context_sha256": semantic_context.get("context_sha256"),
        "source_text_sha256": semantic_context.get("source_text_sha256"),
        "artifact_sha256s": artifact_sha256s,
    }


def _symai_dry_run_raw(request: StageRequest) -> str:
    return canonical_json(
        {
            "candidate_ir": {
                "kind": "dry_run",
                "source_sha256": request.input_sha256,
            },
            "normalized_predicates": [],
            "quantifiers": [],
            "entities": [],
            "ambiguity_flags": ["dry_run"],
            "confidence": 0.0,
            "validation_errors": ["model_call_skipped"],
        }
    )


def _reject_json_constant(value: str) -> object:
    raise SymaiAdapterContractError(f"non-finite JSON number is forbidden: {value}")


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SymaiAdapterContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _symai_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise SymaiAdapterContractError(f"{field_name} must be an array")
    if len(value) > SYMAI_MAX_LIST_ITEMS:
        raise SymaiAdapterContractError(
            f"{field_name} exceeds {SYMAI_MAX_LIST_ITEMS} items"
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SymaiAdapterContractError(
                f"{field_name} must contain nonempty strings"
            )
        normalized = item.strip()
        if len(normalized) > SYMAI_MAX_ITEM_LENGTH:
            raise SymaiAdapterContractError(
                f"{field_name} contains an overlong string"
            )
        result.append(normalized)
    if len(set(result)) != len(result):
        raise SymaiAdapterContractError(f"{field_name} contains duplicate values")
    return result


def _contains_symai_authority_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _normalized_identity(key) in _SYMAI_AUTHORITY_KEYS:
                return True
            if _contains_symai_authority_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_symai_authority_key(item) for item in value)
    return False


def _validate_symai_candidate_value(
    value: object,
    field_name: str = "candidate_ir",
    *,
    depth: int = 0,
) -> None:
    # The enclosing StageRecord adds two levels (stage data + candidate field)
    # to the shared eight-level JSON bound.
    if depth > 6:
        raise SymaiAdapterContractError("candidate_ir exceeds maximum nesting depth")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SymaiAdapterContractError(
                f"{field_name} contains a non-finite number"
            )
        return
    if isinstance(value, str):
        if len(value) > 4096:
            raise SymaiAdapterContractError(
                f"{field_name} contains an overlong string"
            )
        return
    if isinstance(value, list):
        if len(value) > SYMAI_MAX_LIST_ITEMS:
            raise SymaiAdapterContractError(
                f"{field_name} contains too many array items"
            )
        for index, item in enumerate(value):
            _validate_symai_candidate_value(
                item, f"{field_name}[{index}]", depth=depth + 1
            )
        return
    if isinstance(value, dict):
        if len(value) > SYMAI_MAX_LIST_ITEMS:
            raise SymaiAdapterContractError(
                f"{field_name} contains too many object members"
            )
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > SYMAI_MAX_ITEM_LENGTH:
                raise SymaiAdapterContractError(
                    f"{field_name} contains an invalid object key"
                )
            _validate_symai_candidate_value(
                item, f"{field_name}.{key}", depth=depth + 1
            )
        return
    raise SymaiAdapterContractError(
        f"{field_name} contains a non-JSON value"
    )


def _validate_symai_contract(
    raw_output: object,
    config: SymaiAdapterConfig,
) -> tuple[str, dict[str, object]]:
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise SymaiAdapterContractError("SyMAI output must be a nonempty JSON string")
    raw = raw_output.strip()
    if len(raw.encode("utf-8")) > config.max_raw_output_bytes:
        raise SymaiAdapterContractError(
            f"SyMAI raw output exceeds {config.max_raw_output_bytes} encoded bytes"
        )
    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except SymaiAdapterContractError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise SymaiAdapterContractError(
            f"SyMAI output is not strict JSON: {type(exc).__name__}"
        ) from exc
    if not isinstance(decoded, dict):
        raise SymaiAdapterContractError("SyMAI output must be one JSON object")
    missing = _SYMAI_CONTRACT_KEYS - set(decoded)
    unknown = set(decoded) - _SYMAI_CONTRACT_KEYS
    if missing or unknown:
        raise SymaiAdapterContractError(
            "SyMAI contract keys do not match the frozen schema"
        )
    candidate_ir = decoded["candidate_ir"]
    if not isinstance(candidate_ir, dict) or not candidate_ir:
        raise SymaiAdapterContractError("candidate_ir must be a nonempty object")
    _validate_symai_candidate_value(candidate_ir)
    if _contains_symai_authority_key(candidate_ir):
        raise SymaiAdapterContractError(
            "candidate_ir contains a forbidden proof-authority claim"
        )
    candidate_bytes = len(canonical_json(candidate_ir).encode("utf-8"))
    if candidate_bytes > SYMAI_MAX_CANDIDATE_BYTES:
        raise SymaiAdapterContractError(
            f"candidate_ir exceeds {SYMAI_MAX_CANDIDATE_BYTES} encoded bytes"
        )
    confidence = decoded["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        raise SymaiAdapterContractError(
            "confidence must be a finite number between 0 and 1"
        )
    validated = {
        "candidate_ir": candidate_ir,
        "normalized_predicates": _symai_string_list(
            decoded["normalized_predicates"], "normalized_predicates"
        ),
        "quantifiers": _symai_string_list(decoded["quantifiers"], "quantifiers"),
        "entities": _symai_string_list(decoded["entities"], "entities"),
        "ambiguity_flags": _symai_string_list(
            decoded["ambiguity_flags"], "ambiguity_flags"
        ),
        "confidence": float(confidence),
        "validation_errors": _symai_string_list(
            decoded["validation_errors"], "validation_errors"
        ),
    }
    return raw, validated


def _default_symai_engine_factory(
    config: SymaiAdapterConfig,
    namespace: str,
) -> object:
    # Import SyMAI itself first.  Its import may raise SystemExit when the
    # preflight configuration is missing; callers convert that to explicit
    # capability missingness instead of invoking its setup wizard.
    importlib.import_module("symai")
    engine_module = importlib.import_module(
        "ipfs_datasets_py.utils.symai_ipfs_engine"
    )
    engine_type = getattr(engine_module, "IPFSSyMAINeurosymbolicEngine", None)
    if not isinstance(engine_type, type):
        raise ImportError("IPFSSyMAINeurosymbolicEngine is unavailable")
    return engine_type(
        "neurosymbolic",
        "NEUROSYMBOLIC_ENGINE_MODEL",
        provider=config.provider,
        cache_namespace=namespace,
        allow_local_fallback=False,
        dry_run=config.dry_run,
        cache_enabled=(
            config.cache_enabled and namespace.endswith("/cache/warm")
        ),
        model_name=config.model,
        route_binding=_symai_route_binding(config),
    )


def _default_symai_trace_getter() -> Mapping[str, object]:
    router = importlib.import_module("ipfs_datasets_py.llm_router")
    getter = getattr(router, "get_last_generation_trace", None)
    if not callable(getter):
        return {}
    value = getter()
    return value if isinstance(value, Mapping) else {}


def _symai_route_binding(
    config: SymaiAdapterConfig,
) -> dict[str, str] | None:
    values = (
        config.expected_inner_provider,
        config.expected_inner_model,
        config.expected_inner_endpoint,
        config.expected_inner_backend,
    )
    if not all(isinstance(value, str) and value for value in values):
        return None
    return {
        "resolved_provider_name": config.expected_inner_provider,
        "resolved_model_name": config.expected_inner_model,
        "service_endpoint": config.expected_inner_endpoint,
        "routing_backend": config.expected_inner_backend,
    }


def _validate_symai_inner_route(
    config: SymaiAdapterConfig,
    metadata: Mapping[str, object],
) -> None:
    # Generic SyMAI integrations may not have a benchmark-frozen inner route.
    # The all-or-none config validation means ``None`` here is unambiguous:
    # no exact inner identity was requested. Benchmark-bound configurations
    # always provide all four values and remain strictly receipt-gated.
    if _symai_route_binding(config) is None:
        return
    fields = {
        "resolved_provider_name": config.expected_inner_provider,
        "resolved_model_name": config.expected_inner_model,
        "service_endpoint": config.expected_inner_endpoint,
        "routing_backend": config.expected_inner_backend,
    }
    missing = sorted(
        key
        for key in fields
        if not isinstance(metadata.get(key), str)
        or not str(metadata.get(key)).strip()
    )
    if missing:
        raise SymaiAdapterContractError(
            "SyMAI inner route trace omitted: " + ", ".join(missing)
        )
    drifted = sorted(
        key
        for key, expected in fields.items()
        if expected is not None and metadata.get(key) != expected
    )
    if drifted:
        raise SymaiAdapterContractError(
            "SyMAI inner route identity drifted: " + ", ".join(drifted)
        )


def _invoke_symai_engine(engine: object, prompt: str) -> tuple[str, dict[str, object]]:
    forward = getattr(engine, "forward", None)
    if not callable(forward):
        raise SymaiAdapterContractError("SyMAI engine must expose forward()")
    argument = SimpleNamespace(
        prop=SimpleNamespace(
            prepared_input=prompt,
            processed_input="",
            prompt="",
            raw_input=False,
            response_format=SYMAI_RESPONSE_FORMAT,
            payload={"response_format": SYMAI_RESPONSE_FORMAT},
        ),
        args=[],
        kwargs={},
    )
    result = forward(argument)
    if (
        not isinstance(result, tuple)
        or len(result) != 2
        or not isinstance(result[0], Sequence)
        or isinstance(result[0], (str, bytes))
        or len(result[0]) != 1
        or not isinstance(result[0][0], str)
        or not isinstance(result[1], Mapping)
    ):
        raise SymaiAdapterContractError(
            "SyMAI engine must return one text output and metadata"
        )
    return result[0][0], dict(result[1])


def _safe_symai_metadata(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in (
        "backend",
        "cache",
        "cache_key",
        "cached_backend",
        "effective_model_name",
        "effective_provider_name",
        "format",
        "model",
        "provider",
        "resolved_model_name",
        "resolved_provider_name",
        "router_provider",
        "routing_backend",
        "service_endpoint",
    ):
        item = value.get(key)
        if item is None or isinstance(item, (bool, int, float)):
            if item is not None:
                if not isinstance(item, float) or math.isfinite(item):
                    result[key] = item
        elif isinstance(item, str):
            result[key] = item[:SYMAI_MAX_ITEM_LENGTH]
    return result


def _symai_telemetry(
    request: StageRequest,
    *,
    started_wall: float,
    started_cpu: float,
    raw_output: str | None,
    model_calls: int,
    retries: int,
    cache_hit: bool,
    success: bool,
) -> TelemetryRecord:
    return TelemetryRecord(
        wall_time_ms=round(max(0.0, time.perf_counter() - started_wall) * 1000, 6),
        cpu_time_ms=round(max(0.0, time.process_time() - started_cpu) * 1000, 6),
        input_items=1,
        output_items=1 if success else 0,
        model_calls=model_calls,
        cache_hits=1 if cache_hit else 0,
        cache_misses=0 if cache_hit else 1,
        retries=retries,
        bytes_in=request.input_bytes,
        bytes_out=(
            0 if raw_output is None else len(raw_output.encode("utf-8"))
        ),
        resource_lane=ResourceLane.MODEL,
    )


def _symai_failure_output(
    request: StageRequest,
    config: SymaiAdapterConfig,
    *,
    detail: str,
    namespace: str,
    cache_key: str,
    started_wall: float,
    started_cpu: float,
    failure_code: FailureCode,
    raw_output: str | None = None,
    metadata: Mapping[str, object] | None = None,
    model_calls: int = 0,
    retries: int = 0,
    cache_hit: bool = False,
    unavailable: bool = False,
) -> StageOutput:
    bounded_detail = detail.strip()[:_MAX_DETAIL_LENGTH]
    identity = {
        **dict(request.requested_identity),
        "adapter": "symai",
        "requested_provider": config.provider,
        "requested_model": config.model,
        "cache_namespace": namespace,
        "cache_key": cache_key,
        "dry_run": config.dry_run,
        "existing_router_engine": SYMAI_ROUTER_ENGINE,
        "starts_model_server": False,
        "symai_failure_code": failure_code.value,
    }
    if metadata:
        identity.update(
            {
                f"router_{key}": value
                for key, value in _safe_symai_metadata(metadata).items()
            }
        )
    failure_data: dict[str, object] = {
        "schema": SYMAI_EVIDENCE_SCHEMA,
        "raw_output": raw_output,
        "candidate_ir": None,
        "cache_namespace": namespace,
        "cache_key": cache_key,
        "assurance": {
            "semantic_hypothesis": False,
            "authoritative": False,
            "kernel_checked": False,
            "verified": False,
        },
    }
    return StageOutput(
        data=failure_data,
        status=StageStatus.UNAVAILABLE if unavailable else StageStatus.FAILED,
        effective_identity=identity,
        failure_code=(
            FailureCode.CAPABILITY_UNAVAILABLE if unavailable else failure_code
        ),
        failure_detail=bounded_detail,
        telemetry=_symai_telemetry(
            request,
            started_wall=started_wall,
            started_cpu=started_cpu,
            raw_output=raw_output,
            model_calls=model_calls,
            retries=retries,
            cache_hit=cache_hit,
            success=False,
        ),
    )


def _symai_evidence_handler(
    config: SymaiAdapterConfig,
    *,
    engine_factory: SymaiEngineFactory,
    trace_getter: SymaiTraceGetter,
    cache: MutableMapping[str, object],
) -> StageHandler:
    def handler(request: StageRequest) -> StageOutput:
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        namespace = _symai_cache_namespace(request)
        semantic_context: dict[str, object] | None = None
        cache_key = _symai_cache_key(request, config, namespace)
        raw_output: str | None = None
        metadata: dict[str, object] = {}
        cache_hit = False
        model_calls = 0
        retries = 0

        try:
            _reject_symai_recursion(request)
            text = _symai_request_text(request, config)
            semantic_context = _symai_input_semantic_context(request)
            cache_key = _symai_cache_key(
                request,
                config,
                namespace,
                semantic_context,
            )
        except SymaiRecursiveRoutingError as exc:
            return _symai_failure_output(
                request,
                config,
                detail=str(exc),
                namespace=namespace,
                cache_key=cache_key,
                started_wall=started_wall,
                started_cpu=started_cpu,
                failure_code=FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR,
            )
        except ProtocolContractError as exc:
            return _symai_failure_output(
                request,
                config,
                detail=str(exc),
                namespace=namespace,
                cache_key=cache_key,
                started_wall=started_wall,
                started_cpu=started_cpu,
                failure_code=FailureCode.FIXTURE_INVALID,
            )

        if config.cache_enabled and request.cache_mode is CacheMode.WARM:
            cached = cache.get(cache_key)
            if isinstance(cached, Mapping):
                cached_raw = cached.get("raw_output")
                cached_metadata = cached.get("metadata", {})
                if isinstance(cached_raw, str) and isinstance(
                    cached_metadata, Mapping
                ):
                    raw_output = cached_raw
                    metadata = dict(cached_metadata)
                    cache_hit = True

        validated: dict[str, object] | None = None
        last_contract_error: SymaiAdapterContractError | None = None
        last_engine_error: Exception | None = None
        attempts = 1 if cache_hit else config.max_retries + 1
        engine: object | None = None

        for attempt in range(attempts):
            if not cache_hit:
                try:
                    if config.dry_run:
                        raw_output = _symai_dry_run_raw(request)
                        metadata = {
                            "backend": "dry_run",
                            "effective_provider_name": config.provider,
                            "effective_model_name": config.model,
                        }
                    else:
                        if engine is None:
                            engine = engine_factory(config, namespace)
                        model_calls += 1
                        raw_output, metadata = _invoke_symai_engine(
                            engine,
                            _symai_prompt(
                                text,
                                namespace,
                                semantic_context,
                            ),
                        )
                        try:
                            trace = trace_getter()
                        except Exception:
                            trace = {}
                        if isinstance(trace, Mapping):
                            for key, value in trace.items():
                                metadata.setdefault(str(key), value)
                    _reject_symai_recursion(request, metadata=metadata)
                except SymaiRecursiveRoutingError as exc:
                    return _symai_failure_output(
                        request,
                        config,
                        detail=str(exc),
                        namespace=namespace,
                        cache_key=cache_key,
                        started_wall=started_wall,
                        started_cpu=started_cpu,
                        failure_code=FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR,
                        raw_output=raw_output,
                        metadata=metadata,
                        model_calls=model_calls,
                        retries=retries,
                    )
                except (ImportError, ModuleNotFoundError, SystemExit) as exc:
                    return _symai_failure_output(
                        request,
                        config,
                        detail=(
                            "SyMAI package or preflight configuration is unavailable: "
                            f"{type(exc).__name__}"
                        ),
                        namespace=namespace,
                        cache_key=cache_key,
                        started_wall=started_wall,
                        started_cpu=started_cpu,
                        failure_code=FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR,
                        model_calls=model_calls,
                        retries=retries,
                        unavailable=True,
                    )
                except SymaiAdapterContractError as exc:
                    last_contract_error = exc
                except Exception as exc:
                    last_engine_error = exc

            if raw_output is not None:
                if not config.dry_run:
                    try:
                        _validate_symai_inner_route(config, metadata)
                    except SymaiAdapterContractError as exc:
                        return _symai_failure_output(
                            request,
                            config,
                            detail=str(exc),
                            namespace=namespace,
                            cache_key=cache_key,
                            started_wall=started_wall,
                            started_cpu=started_cpu,
                            failure_code=(
                                FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR
                            ),
                            raw_output=raw_output,
                            metadata=metadata,
                            model_calls=model_calls,
                            retries=retries,
                            cache_hit=cache_hit,
                        )
                try:
                    raw_output, validated = _validate_symai_contract(
                        raw_output, config
                    )
                    break
                except SymaiAdapterContractError as exc:
                    last_contract_error = exc

            if cache_hit:
                break
            if attempt < attempts - 1:
                retries += 1

        if validated is None:
            if last_contract_error is not None:
                code = FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE
                detail = f"SyMAI structured contract rejected: {last_contract_error}"
            else:
                code = FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR
                error_name = (
                    type(last_engine_error).__name__
                    if last_engine_error is not None
                    else "UnknownError"
                )
                detail = f"SyMAI existing-router invocation failed: {error_name}"
            return _symai_failure_output(
                request,
                config,
                detail=detail,
                namespace=namespace,
                cache_key=cache_key,
                started_wall=started_wall,
                started_cpu=started_cpu,
                failure_code=code,
                raw_output=raw_output,
                metadata=metadata,
                model_calls=model_calls,
                retries=retries,
                cache_hit=cache_hit,
            )

        effective_provider_value = metadata.get("effective_provider_name")
        if effective_provider_value is None:
            effective_provider_value = metadata.get("provider")
        effective_model_value = metadata.get("effective_model_name")
        if effective_model_value is None:
            effective_model_value = metadata.get("model")
        if (
            not isinstance(effective_provider_value, str)
            or not effective_provider_value.strip()
            or not isinstance(effective_model_value, str)
            or not effective_model_value.strip()
        ):
            return _symai_failure_output(
                request,
                config,
                detail=(
                    "SyMAI existing-router trace omitted the effective "
                    "provider/model identity"
                ),
                namespace=namespace,
                cache_key=cache_key,
                started_wall=started_wall,
                started_cpu=started_cpu,
                failure_code=FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR,
                raw_output=raw_output,
                metadata=metadata,
                model_calls=model_calls,
                retries=retries,
                cache_hit=cache_hit,
            )
        effective_provider = effective_provider_value.strip()
        effective_model = effective_model_value.strip()
        if effective_provider != config.provider or effective_model != config.model:
            return _symai_failure_output(
                request,
                config,
                detail=(
                    "SyMAI existing-router requested/effective "
                    "provider/model identity mismatch"
                ),
                namespace=namespace,
                cache_key=cache_key,
                started_wall=started_wall,
                started_cpu=started_cpu,
                failure_code=FailureCode.SYMAI_IMPORT_OR_CONFIGURATION_ERROR,
                raw_output=raw_output,
                metadata=metadata,
                model_calls=model_calls,
                retries=retries,
                cache_hit=cache_hit,
            )

        if config.cache_enabled and not cache_hit:
            cache[cache_key] = {
                "raw_output": raw_output,
                "metadata": dict(metadata),
            }

        safe_metadata = _safe_symai_metadata(metadata)
        candidate_ir = validated["candidate_ir"]
        candidate_sha256 = hashlib.sha256(
            canonical_json(candidate_ir).encode("utf-8")
        ).hexdigest()
        evidence = {
            "schema": SYMAI_EVIDENCE_SCHEMA,
            "candidate_ir": candidate_ir,
            "candidate_ir_sha256": candidate_sha256,
            "normalized_predicates": validated["normalized_predicates"],
            "quantifiers": validated["quantifiers"],
            "entities": validated["entities"],
            "ambiguity_flags": validated["ambiguity_flags"],
            "confidence": validated["confidence"],
            "validation_errors": validated["validation_errors"],
            "raw_output": raw_output,
            "backend_provenance": {
                "engine": SYMAI_ROUTER_ENGINE,
                "router": "ipfs_datasets_py.llm_router",
                "requested_provider": config.provider,
                "effective_provider": effective_provider,
                "requested_model": config.model,
                "effective_model": effective_model,
                "router_metadata": safe_metadata,
                "attempts": model_calls,
                "retries": retries,
                "dry_run": config.dry_run,
                "starts_model_server": False,
                "reuses_existing_model_service": True,
            },
            "cache": {
                "namespace": namespace,
                "key": cache_key,
                "mode": request.cache_mode.value,
                "hit": cache_hit,
            },
            "semantic_context": _semantic_context_binding(
                semantic_context or _symai_input_semantic_context(request)
            ),
            "assurance": {
                "semantic_hypothesis": True,
                "raw_output_is_canonical": False,
                "contract_validated": True,
                "authoritative": False,
                "kernel_checked": False,
                "verified": False,
            },
        }
        identity = {
            **dict(request.requested_identity),
            "implementation": "symai",
            "requested_provider": config.provider,
            "effective_provider": effective_provider,
            "requested_model": config.model,
            "effective_model": effective_model,
            "cache_namespace": namespace,
            "cache_key": cache_key,
            "cache_hit": cache_hit,
            "dry_run": config.dry_run,
            "existing_router_engine": SYMAI_ROUTER_ENGINE,
            "starts_model_server": False,
            "semantic_context_sha256": (
                None
                if semantic_context is None
                else semantic_context.get("context_sha256")
            ),
        }
        return StageOutput(
            data=evidence,
            effective_identity=identity,
            telemetry=_symai_telemetry(
                request,
                started_wall=started_wall,
                started_cpu=started_cpu,
                raw_output=raw_output,
                model_calls=model_calls,
                retries=retries,
                cache_hit=cache_hit,
                success=True,
            ),
        )

    return handler


class SymaiAdapter(StageAdapter):
    """Stage adapter for strict SyMAI semantics over the existing router.

    With neither a handler nor config this retains the dependency-free default
    route.  A config opts into lazy ``IPFSSyMAINeurosymbolicEngine`` execution;
    explicitly injected handlers retain the generic adapter compatibility used
    by earlier benchmark stages.
    """

    config: SymaiAdapterConfig | None

    def __init__(
        self,
        handler: StageHandler | None = None,
        *,
        config: SymaiAdapterConfig | None = None,
        engine_factory: SymaiEngineFactory | None = None,
        trace_getter: SymaiTraceGetter | None = None,
        cache: MutableMapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        if handler is not None and config is not None:
            raise ProtocolContractError(
                "SymaiAdapter accepts either an injected handler or a config"
            )
        if config is None and any(
            value is not None for value in (engine_factory, trace_getter, cache)
        ):
            raise ProtocolContractError(
                "SyMAI engine, trace, and cache injection require a config"
            )
        if config is not None:
            if not isinstance(config, SymaiAdapterConfig):
                raise ProtocolContractError(
                    "config must be a SymaiAdapterConfig"
                )
            selected_cache = {} if cache is None else cache
            if not isinstance(selected_cache, MutableMapping):
                raise ProtocolContractError("cache must be a mutable mapping")
            handler = _symai_evidence_handler(
                config,
                engine_factory=engine_factory or _default_symai_engine_factory,
                trace_getter=trace_getter or _default_symai_trace_getter,
                cache=selected_cache,
            )
        object.__setattr__(self, "config", config)
        super().__init__(StageName.SYMAI, handler=handler, **kwargs)


def HSSLEV0335D9B() -> str:
    """Return the AST-verifiable Hammer proof-path evidence receipt."""

    return "Hammer request, bounded portfolio, normalization, reconstruction, and receipt records"


def _hammer_contract_types() -> tuple[Any, ...]:
    """Load Hammer record types only when a Hammer handler is executed."""

    from ipfs_datasets_py.logic.hammers.models import (
        EnvironmentLockRecord,
        HammerRequest,
        ProofCandidateRecord,
        ReconstructionRecord,
        SUPPORTED_SCHEMA_VERSIONS,
    )
    from ipfs_datasets_py.logic.hammers.portfolio import PortfolioRunResult

    return (
        HammerRequest,
        PortfolioRunResult,
        ProofCandidateRecord,
        ReconstructionRecord,
        EnvironmentLockRecord,
        SUPPORTED_SCHEMA_VERSIONS,
    )


def _coerce_hammer_record(
    value: object,
    record_type: Any,
    field_name: str,
    *,
    optional: bool = False,
) -> Any:
    if value is None and optional:
        return None
    if isinstance(value, record_type):
        record = value
    elif isinstance(value, Mapping):
        try:
            record = record_type.from_dict(dict(value))
        except (KeyError, TypeError, ValueError) as exc:
            raise HammerAdapterContractError(
                f"{field_name} is not a valid {record_type.__name__}: {exc}"
            ) from exc
    else:
        raise HammerAdapterContractError(
            f"{field_name} must be a {record_type.__name__} or serialized object"
        )
    validator = getattr(record, "validate", None)
    if callable(validator):
        try:
            validator()
        except (TypeError, ValueError) as exc:
            raise HammerAdapterContractError(
                f"{field_name} failed {record_type.__name__} validation: {exc}"
            ) from exc
    return record


def _hammer_record_dict(record: object, field_name: str) -> dict[str, object]:
    to_dict = getattr(record, "to_dict", None)
    if not callable(to_dict):
        raise HammerAdapterContractError(
            f"{field_name} does not expose a serializable to_dict contract"
        )
    value = to_dict()
    if not isinstance(value, dict):
        raise HammerAdapterContractError(f"{field_name}.to_dict() must return an object")
    return value


def _validate_hammer_evidence(
    value: object,
    *,
    request: StageRequest,
) -> dict[str, object]:
    """Validate and serialize one complete Hammer proof-search path.

    The backend handler may return native Hammer records or their serialized
    forms.  The resulting benchmark payload is always JSON data and retains
    each record separately.  Cross-record checks here are intentionally
    stricter than the individual Hammer model validators: a candidate from a
    different request, a reconstruction for a different candidate, or a
    portfolio attempt from a different request must never be presented as one
    stage result.

    Expected payload keys are ``request``, ``portfolio`` (a
    ``PortfolioRunResult``), optional ``proof_candidate``/``candidate``,
    optional ``reconstruction``, optional ``environment_lock``, and optional
    ``normalized_evidence``.  The handler may attach diagnostic keys, but the
    adapter emits only the bounded, contract-defined records below.
    """

    if not isinstance(value, Mapping):
        raise HammerAdapterContractError("Hammer handler output must be an object")
    (
        request_type,
        portfolio_type,
        candidate_type,
        reconstruction_type,
        environment_type,
        supported_schema_versions,
    ) = _hammer_contract_types()

    request_value = value.get("request")
    hammer_request = _coerce_hammer_record(request_value, request_type, "request")
    portfolio_value = value.get("portfolio", value.get("run_result"))
    portfolio = _coerce_hammer_record(portfolio_value, portfolio_type, "portfolio")
    if portfolio.schema_version not in supported_schema_versions:
        raise HammerAdapterContractError(
            f"portfolio.schema_version {portfolio.schema_version!r} is unsupported"
        )
    candidate_value = value.get("proof_candidate", value.get("candidate"))
    candidate = _coerce_hammer_record(
        candidate_value,
        candidate_type,
        "proof_candidate",
        optional=True,
    )
    reconstruction = _coerce_hammer_record(
        value.get("reconstruction"),
        reconstruction_type,
        "reconstruction",
        optional=True,
    )
    environment_lock = _coerce_hammer_record(
        value.get("environment_lock"),
        environment_type,
        "environment_lock",
        optional=True,
    )

    request_id = hammer_request.request_id
    # If the caller supplied a Hammer id in benchmark input/identity, bind it
    # too.  The fields are optional for compatibility with generic stage
    # callers, but when present they prevent a handler from silently switching
    # the request it is answering.
    expected_ids: list[object] = []
    if isinstance(request.input_data, Mapping):
        expected_ids.extend(
            request.input_data.get(name)
            for name in ("hammer_request_id", "request_id")
            if name in request.input_data
        )
    expected_ids.extend(
        request.requested_identity.get(name)
        for name in ("hammer_request_id", "request_id")
        if name in request.requested_identity
    )
    for expected_id in expected_ids:
        if expected_id is not None and expected_id != request_id:
            raise HammerAdapterContractError(
                f"Hammer request_id {request_id!r} does not match benchmark identity "
                f"{expected_id!r}"
            )

    if portfolio.request_id != request_id:
        raise HammerAdapterContractError(
            f"portfolio.request_id {portfolio.request_id!r} does not match "
            f"request.request_id {request_id!r}"
        )
    for attempt in portfolio.attempts:
        try:
            attempt.validate()
        except (TypeError, ValueError) as exc:
            raise HammerAdapterContractError(
                f"portfolio attempt {attempt.attempt_id!r} failed validation: {exc}"
            ) from exc
        if attempt.solver_name not in hammer_request.policy.allowed_solvers:
            raise HammerAdapterContractError(
                f"solver {attempt.solver_name!r} is not allowlisted by request policy"
            )
        if attempt.timeout_seconds > hammer_request.policy.timeout_seconds:
            raise HammerAdapterContractError(
                f"attempt {attempt.attempt_id!r} exceeds the request timeout budget"
            )
        if attempt.network_used and not hammer_request.policy.network_allowed:
            raise HammerAdapterContractError(
                f"attempt {attempt.attempt_id!r} used network under a denied policy"
            )
        if attempt.request_id != request_id:
            raise HammerAdapterContractError(
                f"portfolio attempt {attempt.attempt_id!r} belongs to "
                f"request {attempt.request_id!r}, not {request_id!r}"
            )
    attempt_ids = {attempt.attempt_id for attempt in portfolio.attempts}

    # A policy flag alone is not enough to change the benchmark arm.  The
    # preregistered matrix names the learned and LLM-ranking arms explicitly,
    # so a record cannot smuggle either ranking mode into A0-A9 or A12.
    if hammer_request.policy.allow_learned_premise_selector and request.variant_id != "A10":
        raise HammerAdapterContractError(
            "learned premise selection is only permitted by named variant A10"
        )
    if hammer_request.policy.allow_llm_premise_ranking and request.variant_id != "A11":
        raise HammerAdapterContractError(
            "LLM premise ranking is only permitted by named variant A11"
        )
    if set(portfolio.evidence) - attempt_ids:
        raise HammerAdapterContractError(
            "portfolio evidence contains an unknown solver attempt"
        )

    if candidate is not None:
        if candidate.request_id != request_id:
            raise HammerAdapterContractError(
                f"proof_candidate.request_id {candidate.request_id!r} does not "
                f"match request.request_id {request_id!r}"
            )
        if candidate.solver_attempt_id not in attempt_ids:
            raise HammerAdapterContractError(
                f"proof_candidate.solver_attempt_id {candidate.solver_attempt_id!r} "
                "is not present in portfolio.attempts"
            )

    if reconstruction is not None:
        if reconstruction.request_id != request_id:
            raise HammerAdapterContractError(
                f"reconstruction.request_id {reconstruction.request_id!r} does not "
                f"match request.request_id {request_id!r}"
            )
        if reconstruction.target_itp is not hammer_request.itp:
            raise HammerAdapterContractError(
                f"reconstruction.target_itp {reconstruction.target_itp.value!r} "
                f"does not match request.itp {hammer_request.itp.value!r}"
            )
        if candidate is None:
            raise HammerAdapterContractError(
                "reconstruction requires the corresponding proof_candidate"
            )
        if reconstruction.candidate_id != candidate.candidate_id:
            raise HammerAdapterContractError(
                f"reconstruction.candidate_id {reconstruction.candidate_id!r} "
                f"does not match proof_candidate.candidate_id {candidate.candidate_id!r}"
            )
        if environment_lock is None:
            raise HammerAdapterContractError(
                "reconstruction requires environment_lock"
            )
        if (
            environment_lock is not None
            and reconstruction.environment_lock_id != environment_lock.lock_id
        ):
            raise HammerAdapterContractError(
                "reconstruction.environment_lock_id does not match environment_lock"
            )
        if environment_lock is not None and environment_lock.itp is not hammer_request.itp:
            raise HammerAdapterContractError(
                f"environment_lock.itp {environment_lock.itp.value!r} does not "
                f"match request.itp {hammer_request.itp.value!r}"
            )

    normalized_payload: dict[str, dict[str, object]] = {}
    normalized_value = value.get("normalized_evidence", {})
    if normalized_value is None:
        normalized_value = {}
    if not isinstance(normalized_value, Mapping):
        raise HammerAdapterContractError("normalized_evidence must be an object")
    try:
        from ipfs_datasets_py.logic.hammers.provenance import NormalizedEvidence

        for attempt_id, evidence_value in normalized_value.items():
            if not isinstance(attempt_id, str) or not (
                isinstance(evidence_value, Mapping)
                or isinstance(evidence_value, NormalizedEvidence)
            ):
                raise HammerAdapterContractError(
                    "normalized_evidence keys and values must be objects"
                )
            evidence = (
                evidence_value
                if isinstance(evidence_value, NormalizedEvidence)
                else NormalizedEvidence.from_dict(dict(evidence_value))
            )
            validator = getattr(evidence, "validate", None)
            if callable(validator):
                validator()
            if evidence.request_id != request_id or evidence.attempt_id != attempt_id:
                raise HammerAdapterContractError(
                    f"normalized evidence {attempt_id!r} is not bound to the "
                    "owning request/attempt"
                )
            if attempt_id not in attempt_ids:
                raise HammerAdapterContractError(
                    f"normalized evidence references unknown attempt {attempt_id!r}"
                )
            normalized_payload[attempt_id] = _hammer_record_dict(
                evidence, f"normalized_evidence[{attempt_id!r}]"
            )
    except HammerAdapterContractError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise HammerAdapterContractError(
            f"invalid normalized_evidence payload: {exc}"
        ) from exc

    accepted = bool(reconstruction is not None and reconstruction.kernel_accepted)
    record_payload: dict[str, object] = {
        "request": _hammer_record_dict(hammer_request, "request"),
        "portfolio": _hammer_record_dict(portfolio, "portfolio"),
        "normalized_evidence": normalized_payload,
        "proof_candidate": (
            None if candidate is None else _hammer_record_dict(candidate, "proof_candidate")
        ),
        "reconstruction": (
            None
            if reconstruction is None
            else _hammer_record_dict(reconstruction, "reconstruction")
        ),
        "environment_lock": (
            None
            if environment_lock is None
            else _hammer_record_dict(environment_lock, "environment_lock")
        ),
        "reconstruction_kernel_accepted": accepted,
        "status": "verified" if accepted else ("candidate" if candidate else "unknown"),
    }
    evidence_id = hashlib.sha256(
        canonical_json({"schema": HAMMER_EVIDENCE_SCHEMA, **record_payload}).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "schema": HAMMER_EVIDENCE_SCHEMA,
        "evidence_id": evidence_id,
        **record_payload,
        # This is descriptive evidence for the subsequent kernel stage.  It
        # intentionally does not set StageOutput.kernel_accepted: only the
        # benchmark's explicit kernel adapter can establish final authority.
    }


class HammerAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        # Keep the backend callable injected and lazy.  Importing this module
        # must not import Hammer's optional solver/frontend dependencies.
        wrapped = None if handler is None else self._validated_handler(handler)
        super().__init__(StageName.HAMMER, handler=wrapped, **kwargs)

    @staticmethod
    def _validated_handler(handler: StageHandler) -> StageHandler:
        def invoke(request: StageRequest) -> object:
            try:
                raw = handler(request)
                if not isinstance(raw, StageOutput):
                    raw = StageOutput(data=raw)
                if raw.status is StageStatus.SUCCESS:
                    # Preserve the generic StageAdapter behavior for callers
                    # that use Hammer as an opaque stage payload.  Once a
                    # handler opts into the Hammer record vocabulary, the
                    # complete cross-record contract is mandatory.
                    if not isinstance(raw.data, Mapping) or not any(
                        key in raw.data
                        for key in (
                            "request",
                            "portfolio",
                            "run_result",
                            "proof_candidate",
                            "candidate",
                            "reconstruction",
                            "environment_lock",
                            "normalized_evidence",
                        )
                    ):
                        return raw
                    data = _validate_hammer_evidence(
                        raw.data,
                        request=request,
                    )
                    return replace(raw, data=data)
                return raw
            except HammerAdapterContractError as exc:
                return StageOutput(
                    status=StageStatus.FAILED,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
                    failure_detail=str(exc)[:_MAX_DETAIL_LENGTH],
                )
            except ImportError as exc:
                return StageOutput(
                    status=StageStatus.UNAVAILABLE,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
                    failure_detail=f"Hammer contracts unavailable: {exc}",
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise HammerAdapterContractError(
                    f"invalid Hammer evidence payload: {exc}"
                ) from exc

        return invoke


class LeanstralAdapterContractError(ProtocolContractError):
    """Raised when a Leanstral request or draft crosses the benchmark boundary."""


@dataclass(frozen=True, slots=True)
class LeanstralAdapterConfig:
    """Frozen limits for the benchmark's untrusted Leanstral model lane.

    The supervisor provider has its own limits.  These smaller benchmark-side
    limits keep a malformed case from expanding the provider request and make
    the one-repair rule visible in the stage receipt.
    """

    max_context_bytes: int = LEANSTRAL_MAX_CONTEXT_BYTES
    max_draft_bytes: int = LEANSTRAL_MAX_DRAFT_BYTES
    max_repair_attempts: int = LEANSTRAL_MAX_REPAIR_ATTEMPTS
    model_timeout_seconds: float = LEANSTRAL_MEASURED_TIMEOUT_SECONDS
    model_token_limit: int = LEANSTRAL_MEASURED_MAX_NEW_TOKENS
    model_resource_class: str = LEANSTRAL_MODEL_RESOURCE_CLASS
    kernel_resource_class: str = LEANSTRAL_KERNEL_RESOURCE_CLASS

    def __post_init__(self) -> None:
        for name in ("max_context_bytes", "max_draft_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise LeanstralAdapterContractError(f"{name} must be a positive integer")
        if self.max_draft_bytes > LEANSTRAL_MAX_DRAFT_BYTES:
            raise LeanstralAdapterContractError(
                f"max_draft_bytes cannot exceed {LEANSTRAL_MAX_DRAFT_BYTES}"
            )
        if self.max_repair_attempts != LEANSTRAL_MAX_REPAIR_ATTEMPTS:
            raise LeanstralAdapterContractError(
                "Leanstral benchmark repair is fixed to exactly one bounded attempt"
            )
        if (
            isinstance(self.model_timeout_seconds, bool)
            or not isinstance(self.model_timeout_seconds, (int, float))
            or not math.isfinite(float(self.model_timeout_seconds))
            or not 0 < float(self.model_timeout_seconds)
            <= LEANSTRAL_MEASURED_TIMEOUT_SECONDS
        ):
            raise LeanstralAdapterContractError(
                "model_timeout_seconds must be positive and cannot exceed "
                f"{LEANSTRAL_MEASURED_TIMEOUT_SECONDS:g}"
            )
        if (
            isinstance(self.model_token_limit, bool)
            or not isinstance(self.model_token_limit, int)
            or not 0 < self.model_token_limit
            <= LEANSTRAL_MEASURED_MAX_NEW_TOKENS
        ):
            raise LeanstralAdapterContractError(
                "model_token_limit must be positive and cannot exceed "
                f"{LEANSTRAL_MEASURED_MAX_NEW_TOKENS}"
            )
        for name in ("model_resource_class", "kernel_resource_class"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise LeanstralAdapterContractError(f"{name} must be non-empty")
        if self.model_resource_class == self.kernel_resource_class:
            raise LeanstralAdapterContractError(
                "Leanstral model and kernel resource lanes must differ"
            )


def HSSLEV0342A4C() -> str:
    """Return the AST-verifiable Leanstral synthesis/repair evidence receipt."""

    return "Leanstral proof drafts use strict schemas and one bounded unverified repair"


def _bounded_canonical(value: object, field_name: str, maximum: int) -> object:
    try:
        encoded = canonical_json(value).encode("utf-8")
    except ProtocolContractError as exc:
        raise LeanstralAdapterContractError(f"{field_name} is not strict JSON") from exc
    if len(encoded) > maximum:
        raise LeanstralAdapterContractError(
            f"{field_name} exceeds the {maximum} byte bound"
        )
    return json.loads(encoded.decode("utf-8"))


def _lean_declaration_binders(value: str) -> tuple[str, ...]:
    """Return ordered top-level binders from a frozen Lean declaration."""

    pairs = {"(": ")", "{": "}", "[": "]"}
    binders: list[str] = []
    cursor = 0
    while cursor < len(value):
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if cursor == len(value):
            break
        opener = value[cursor]
        if opener not in pairs:
            raise LeanstralAdapterContractError(
                "compiled theorem contains an unsupported binder declaration"
            )
        stack = [pairs[opener]]
        end = cursor + 1
        while end < len(value) and stack:
            character = value[end]
            if character in pairs:
                stack.append(pairs[character])
            elif character == stack[-1]:
                stack.pop()
            end += 1
        if stack:
            raise LeanstralAdapterContractError(
                "compiled theorem contains an unbalanced binder"
            )
        binders.append(" ".join(value[cursor:end].split()))
        cursor = end
    return tuple(binders)


def _leanstral_input_semantic_context(
    request: StageRequest,
) -> dict[str, object]:
    measured_proof_arm = (
        _is_frozen_ablation_request(request)
        and request.variant_id in {f"A{index}" for index in range(3, 13)}
    )
    requires_symai = (
        measured_proof_arm
        and request.variant_id in {f"A{index}" for index in range(4, 13)}
    )
    required_present: tuple[StageName, ...] = ()
    required_success: tuple[StageName, ...] = ()
    if measured_proof_arm:
        required_present = (StageName.SPACY,)
        required_success = (StageName.SPACY,)
    if requires_symai:
        required_present = (*required_present, StageName.SYMAI)
    return build_upstream_semantic_context(
        request,
        require_present=required_present,
        require_success=required_success,
    )


def _compiled_leanstral_context(
    request: StageRequest,
    config: LeanstralAdapterConfig,
    obligation_id: str,
) -> tuple[dict[str, object], dict[str, object]] | None:
    """Bind one live fallback request to the compiler's fixed theorem."""

    compiler = request.artifact(StageName.COMPILER)
    if compiler is None:
        return None
    if (
        not compiler.invoked
        or compiler.status is not StageStatus.SUCCESS
        or not isinstance(compiler.data, Mapping)
    ):
        raise LeanstralAdapterContractError(
            "Leanstral fallback requires a successful compiler artifact"
        )
    compiled = compiler.data.get("compiled_obligation")
    if not isinstance(compiled, Mapping):
        raise LeanstralAdapterContractError(
            "Leanstral fallback requires a compiled proof obligation"
        )
    if (
        compiled.get("schema")
        != "ipfs-datasets.logic-pipeline-benchmark.compiled-obligation.v1"
    ):
        raise LeanstralAdapterContractError(
            "Leanstral fallback received an unsupported compiled obligation"
        )
    if compiled.get("obligation_id") != obligation_id:
        raise LeanstralAdapterContractError(
            "Leanstral obligation does not match the compiler artifact"
        )

    theorem_name = compiled.get("theorem_name")
    source_template = compiled.get("source_template")
    compiler_version = compiled.get("compiler_version")
    semantic_target = compiled.get("semantic_target")
    if (
        not isinstance(theorem_name, str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_']{0,127}", theorem_name)
        or not isinstance(source_template, str)
        or not source_template.strip()
        or source_template.count("{{PROOF}}") != 1
        or not isinstance(compiler_version, str)
        or not compiler_version.strip()
        or not isinstance(semantic_target, str)
        or not semantic_target.strip()
    ):
        raise LeanstralAdapterContractError(
            "Leanstral fallback received an incomplete compiled obligation"
        )
    source_template_sha256 = _digest(
        compiled.get("source_template_sha256"), "source_template_sha256"
    )
    if hashlib.sha256(source_template.encode("utf-8")).hexdigest() != source_template_sha256:
        raise LeanstralAdapterContractError(
            "Leanstral compiled source template digest changed"
        )
    obligation_sha256 = _digest(
        compiled.get("obligation_sha256"), "obligation_sha256"
    )
    declaration = re.search(
        rf"(?ms)^theorem\s+{re.escape(theorem_name)}\b"
        rf"(?P<declaration>.*?)\s*:=\s*by\s*$",
        source_template,
    )
    declaration_body = (
        "" if declaration is None else declaration.group("declaration").strip()
    )
    if ":" not in declaration_body:
        raise LeanstralAdapterContractError(
            "Leanstral fallback cannot identify the compiled theorem conclusion"
        )
    # Binder annotations also contain colons.  The final declaration colon is
    # the one that introduces the theorem result, for both one-line opaque
    # targets and the compiler's multiline translated entailments.
    raw_binders, conclusion = declaration_body.rsplit(":", 1)
    assumptions = _lean_declaration_binders(raw_binders)
    conclusion = conclusion.strip()
    if not conclusion:
        raise LeanstralAdapterContractError(
            "Leanstral fallback compiled theorem conclusion is empty"
        )
    source_digest = f"sha256:{source_template_sha256}"
    template_id = (
        "ipfs-datasets.logic-pipeline-benchmark.compiled-obligation.v1"
    )

    # Import the supervisor contract only when a real compiler-bound
    # Leanstral request is executed.  Importing this adapter module remains
    # side-effect free and dependency tolerant.
    proof_context = import_source_bound_ipfs_accelerate(
        "ipfs_accelerate_py.agent_supervisor.proof_context"
    )
    try:
        query_type = getattr(proof_context, "ProofContextQuery")
        limits_type = getattr(proof_context, "ProofContextLimits")
        entry_type = getattr(proof_context, "ContextEntry")
        source_type = getattr(proof_context, "SourceExcerpt")
        usage_type = getattr(proof_context, "ProofContextUsage")
        capsule_type = getattr(proof_context, "ProofContextCapsule")
        target_type = getattr(proof_context, "ProofContextTarget")
        trust_type = getattr(proof_context, "ContextTrust")
        theorem_type = getattr(proof_context, "FixedTheoremIdentity")
        token_counter = getattr(proof_context, "estimate_context_tokens")

        source_symbol = f"{request.case_id}.reviewed_source"
        source_text = (
            request.input_data.get("text")
            if isinstance(request.input_data, Mapping)
            else None
        )
        source_excerpts = [
            source_type(
                symbol=theorem_name,
                path="",
                text=source_template,
            )
        ]
        symbols = [theorem_name]
        if isinstance(source_text, str) and source_text.strip():
            source_excerpts.append(
                source_type(
                    symbol=source_symbol,
                    path="",
                    text=source_text,
                )
            )
            symbols.append(source_symbol)
        semantic_context = _leanstral_input_semantic_context(request)
        semantic_artifacts = semantic_context.get("artifacts", ())
        semantic_suggestions = ()
        if isinstance(semantic_artifacts, Sequence) and semantic_artifacts:
            semantic_digest = _digest(
                semantic_context.get("context_sha256"),
                "semantic_context.context_sha256",
            )
            semantic_suggestions = (
                entry_type(
                    trust=trust_type.UNTRUSTED_SUGGESTION,
                    kind="semantic_stage_context",
                    record_id=f"semantic-context-{semantic_digest}",
                    fields=semantic_context,
                ),
            )

        theorem = theorem_type(
            theorem_id=theorem_name,
            obligation_id=obligation_id,
            declaration_name=theorem_name,
            assumptions=assumptions,
            conclusion=conclusion,
            template_id=template_id,
            template_version=compiler_version,
            template_semantic_hash=f"sha256:{obligation_sha256}",
            source_scope=(theorem_name,),
            allowed_premise_ids=(),
            canonical_source_digest=source_digest,
        )
        obligation = entry_type(
            trust=trust_type.TRUSTED_FACT,
            kind="obligation",
            record_id=obligation_id,
            fields={
                "obligation_id": obligation_id,
                "declaration_name": theorem_name,
                "assumptions": list(assumptions),
                "conclusion": conclusion,
                "statement": source_template,
                "semantic_target": semantic_target,
                "template_id": template_id,
                "template_version": compiler_version,
                "template_semantic_hash": f"sha256:{obligation_sha256}",
                "source_scope": [theorem_name],
                "allowed_premise_ids": [],
                "canonical_source_digest": source_digest,
            },
        )
        limits = limits_type(
            max_bytes=config.max_context_bytes,
            max_tokens=max(1, config.max_context_bytes // 4),
            max_graph_hops=0,
        )
        capsule = capsule_type(
            target=target_type.LEANSTRAL,
            query=query_type(
                task_id=request.case_id,
                symbols=tuple(symbols),
                obligation_ids=(obligation_id,),
            ),
            limits=limits,
            trusted_facts=(obligation,),
            untrusted_suggestions=semantic_suggestions,
            source_excerpts=tuple(source_excerpts),
        )
        for _ in range(8):
            encoded = capsule.to_json()
            usage = usage_type(
                rows=1 + len(semantic_suggestions),
                bytes=len(encoded.encode("utf-8")),
                tokens=int(token_counter(encoded)),
                graph_hops=0,
                source_excerpts=len(source_excerpts),
                source_bytes=sum(item.byte_count for item in source_excerpts),
            )
            updated = replace(capsule, usage=usage)
            if updated.usage == capsule.usage:
                capsule = updated
                break
            capsule = updated
        # Reparse the final wire object so the supervisor independently checks
        # its identity, exact usage counters, and byte/token limits.
        capsule = capsule_type.from_dict(capsule.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise LeanstralAdapterContractError(
            "Leanstral fixed theorem context construction failed"
        ) from exc

    return (
        dict(capsule.to_dict()),
        dict(theorem.to_dict()),
    )


def _leanstral_input(
    request: StageRequest,
    config: LeanstralAdapterConfig,
) -> tuple[dict[str, object], str, int]:
    """Build one fixed-obligation provider request from benchmark input."""

    if not isinstance(request.input_data, Mapping):
        raise LeanstralAdapterContractError("Leanstral input_data must be an object")
    # The benchmark case object also carries evaluator-only labels and control
    # metadata.  Start from an explicit provider allowlist instead of copying
    # the whole case.  This prevents expected outcomes, expected IR, difficulty
    # strata, and negative-control annotations from influencing generation.
    provider_input_keys = {
        "text",
        "source_text",
        "obligation_id",
        "obligation_ids",
        "proof_obligation",
        "prompt",
        "context",
        "context_capsule",
        "proof_context_capsule",
        "proof_context",
        "repair",
        "repair_attempt",
    }
    raw = {
        str(key): _thaw_json(value)
        for key, value in request.input_data.items()
        if key in provider_input_keys
    }
    raw_ids = raw.get("obligation_ids", raw.get("obligation_id"))
    if isinstance(raw_ids, str):
        obligation_ids = (raw_ids.strip(),)
    elif isinstance(raw_ids, Sequence) and not isinstance(raw_ids, (bytes, bytearray)):
        obligation_ids = tuple(item.strip() for item in raw_ids if isinstance(item, str))
        if len(obligation_ids) != len(raw_ids):
            raise LeanstralAdapterContractError("obligation_ids must contain strings")
    else:
        raise LeanstralAdapterContractError("one fixed obligation_id is required")
    if len(obligation_ids) != 1:
        raise LeanstralAdapterContractError(
            "Leanstral accepts exactly one fixed obligation_id per request"
        )
    obligation_id = _safe_id(obligation_ids[0], "obligation_id")

    repair_value = raw.get("repair")
    supplied_attempt = raw.get("repair_attempt", 0)
    if isinstance(supplied_attempt, bool) or not isinstance(supplied_attempt, int):
        raise LeanstralAdapterContractError("repair_attempt must be an integer")
    if supplied_attempt not in (0, 1):
        raise LeanstralAdapterContractError("repair_attempt exceeds the one-attempt bound")
    repair_attempt = 0
    if repair_value is not None:
        if not isinstance(repair_value, Mapping):
            raise LeanstralAdapterContractError("repair must be an object")
        repair = dict(_bounded_canonical(repair_value, "repair", config.max_context_bytes))
        if supplied_attempt != 1:
            raise LeanstralAdapterContractError(
                "a repair payload must explicitly identify repair_attempt 1"
            )
        failure = repair.get("failure", repair.get("error"))
        failed_draft = repair.get("failed_draft", repair.get("draft"))
        if not isinstance(failure, str) or not failure.strip():
            raise LeanstralAdapterContractError("repair requires a bounded failure message")
        if not isinstance(failed_draft, (str, Mapping)):
            raise LeanstralAdapterContractError("repair requires the failed draft")
        if isinstance(failed_draft, str) and not failed_draft.strip():
            raise LeanstralAdapterContractError("repair failed_draft cannot be empty")
        repair_attempt = 1
    elif supplied_attempt:
        raise LeanstralAdapterContractError(
            "repair_attempt 1 requires a repair payload"
        )

    context_capsule = raw.get(
        "context_capsule",
        raw.get("proof_context_capsule", raw.get("proof_context")),
    )
    prompt = raw.get("prompt")
    if prompt is None and context_capsule is None:
        compiled_context = _compiled_leanstral_context(
            request, config, obligation_id
        )
        if compiled_context is not None:
            context_capsule, fixed_theorem = compiled_context
            raw["fixed_theorem"] = fixed_theorem
    if prompt is None and context_capsule is None:
        context = raw.get("context")
        if isinstance(context, str):
            prompt = context
        elif context is not None and context_capsule is None:
            # Keep generic benchmark callers useful while still sending a
            # strict string prompt to the provider.
            prompt = canonical_json(_bounded_canonical(context, "context", config.max_context_bytes))
        elif context_capsule is None:
            # Frozen corpus cases name their reviewed source input ``text``.
            # Preserve that exact source at the registered Leanstral boundary
            # instead of requiring a second, divergent copy under ``prompt``.
            prompt = raw.get("text")
    if context_capsule is None and (not isinstance(prompt, str) or not prompt.strip()):
        raise LeanstralAdapterContractError(
            "Leanstral input requires a non-empty prompt or context_capsule"
        )
    if isinstance(prompt, str) and not prompt.strip():
        raise LeanstralAdapterContractError("prompt cannot be empty")

    payload = dict(raw)
    payload["obligation_id"] = obligation_id
    payload["obligation_ids"] = [obligation_id]
    payload["repair_attempt"] = repair_attempt
    payload["max_repair_attempts"] = config.max_repair_attempts
    payload["resource_class"] = config.model_resource_class
    if context_capsule is not None:
        payload["context_capsule"] = _bounded_canonical(
            context_capsule, "context_capsule", config.max_context_bytes
        )
        payload.pop("prompt", None)
        payload.pop("proof_context_capsule", None)
        payload.pop("proof_context", None)
    else:
        payload["prompt"] = prompt
    if repair_value is not None:
        repair = payload["repair"]
        assert isinstance(repair, Mapping)
        failure = repair.get("failure", repair.get("error"))
        failed_draft = repair.get("failed_draft", repair.get("draft"))
        payload["compact_failures"] = [{"message": failure}]
        if isinstance(failed_draft, Mapping):
            payload["reusable_drafts"] = [dict(failed_draft)]
        elif isinstance(prompt, str):
            payload["prompt"] = (
                prompt
                + "\n\nREPAIR FAILURE (untrusted diagnostic):\n"
                + str(failure).strip()
                + "\nPREVIOUS DRAFT (untrusted):\n"
                + failed_draft.strip()
            )
    normalized = _bounded_canonical(payload, "Leanstral provider payload", config.max_context_bytes)
    if not isinstance(normalized, dict):  # pragma: no cover - guarded above
        raise LeanstralAdapterContractError("Leanstral provider payload must be an object")
    return normalized, obligation_id, repair_attempt


def _draft_mapping(value: object) -> Mapping[str, object]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise LeanstralAdapterContractError("Leanstral response must be a draft object")
    # Permit a transport wrapper, but never permit arbitrary nested response
    # data to pass through as if it were a draft.
    for key in ("draft", "proof_draft", "model_artifact"):
        if key in value:
            if len(value) != 1 or not isinstance(value[key], Mapping):
                raise LeanstralAdapterContractError("Leanstral draft wrapper is malformed")
            value = value[key]
            break
    if not isinstance(value, Mapping):  # pragma: no cover - defensive
        raise LeanstralAdapterContractError("Leanstral draft must be an object")
    unknown = sorted(set(value) - _LEANSTRAL_DRAFT_KEYS)
    if unknown:
        raise LeanstralAdapterContractError(
            f"Leanstral draft contains unknown fields: {', '.join(unknown[:8])}"
        )
    return value


def _validate_leanstral_draft(
    value: object,
    *,
    request: StageRequest,
    obligation_id: str,
    repair_attempt: int,
    config: LeanstralAdapterConfig,
) -> dict[str, object]:
    draft = dict(_draft_mapping(value))
    if draft.get("schema_version") != LEANSTRAL_DRAFT_SCHEMA:
        raise LeanstralAdapterContractError("Leanstral response used the wrong draft schema")
    if draft.get("artifact_kind", "llm_output") != "llm_output":
        raise LeanstralAdapterContractError("Leanstral response is not an LLM draft artifact")
    if draft.get("stage", "model_draft") != "model_draft":
        raise LeanstralAdapterContractError("Leanstral response is not a model draft")
    artifact_id = draft.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise LeanstralAdapterContractError("Leanstral draft requires artifact_id")
    text = draft.get("draft_text", draft.get("proof_text"))
    if not isinstance(text, str) or not text.strip():
        raise LeanstralAdapterContractError("Leanstral draft text is empty or missing")
    text = text.strip()
    if len(text.encode("utf-8")) > config.max_draft_bytes:
        raise LeanstralAdapterContractError("Leanstral draft exceeds the byte bound")
    if re.match(r"^by(?:\s|$)", text):
        raise LeanstralAdapterContractError(
            "Leanstral proof_text must be a tactic body without a leading by"
        )
    if _LEANSTRAL_NON_TACTIC_BODY.search(text):
        raise LeanstralAdapterContractError(
            "Leanstral proof_text must not contain imports or declarations"
        )
    if "proof_text" in draft and draft["proof_text"] != text:
        raise LeanstralAdapterContractError("draft_text and proof_text disagree")
    forbidden = _LEANSTRAL_FORBIDDEN_CONSTRUCT.search(text)
    if forbidden:
        raise LeanstralAdapterContractError(
            f"Leanstral draft contains forbidden construct {forbidden.group(0)!r}"
        )
    raw_ids = draft.get("obligation_ids")
    if isinstance(raw_ids, str):
        draft_ids = (raw_ids.strip(),)
    elif isinstance(raw_ids, Sequence) and not isinstance(raw_ids, (bytes, bytearray)):
        draft_ids = tuple(item.strip() for item in raw_ids if isinstance(item, str))
    else:
        draft_ids = ()
    if draft_ids != (obligation_id,):
        raise LeanstralAdapterContractError(
            "Leanstral draft obligation_ids do not match the fixed request"
        )
    if draft.get("resource_class", config.model_resource_class) != config.model_resource_class:
        raise LeanstralAdapterContractError(
            "Leanstral model draft cannot use the kernel resource lane"
        )
    for field_name in (
        "verified",
        "authoritative",
        "proof_success",
        "kernel_checked",
        "can_mutate_canonical_source",
        "can_mutate_obligations",
    ):
        if field_name in draft and draft[field_name] is not False:
            raise LeanstralAdapterContractError(
                f"Leanstral model draft cannot claim {field_name}"
            )
    if draft.get("assurance", "unverified") not in {"unverified", "none"}:
        raise LeanstralAdapterContractError("Leanstral model draft must be unverified")
    supplied_digest = draft.get("output_sha256")
    calculated_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if supplied_digest is not None and supplied_digest != calculated_digest:
        raise LeanstralAdapterContractError("Leanstral draft output digest is invalid")
    draft["draft_text"] = text
    draft["proof_text"] = text
    draft["obligation_ids"] = [obligation_id]
    draft["output_sha256"] = calculated_digest
    draft["assurance"] = "unverified"
    draft["verified"] = False
    draft["authoritative"] = False
    draft["kernel_checked"] = False
    draft["repair_attempt"] = repair_attempt
    draft["benchmark_request_id"] = f"{request.run_id}:{request.case_id}"
    return draft


def _leanstral_failure(
    request: StageRequest,
    detail: str,
    *,
    unavailable: bool = False,
) -> StageOutput:
    return StageOutput(
        status=StageStatus.UNAVAILABLE if unavailable else StageStatus.FAILED,
        effective_identity=request.requested_identity,
        failure_code=(
            FailureCode.CAPABILITY_UNAVAILABLE
            if unavailable
            else FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
        ),
        failure_detail=detail[:_MAX_DETAIL_LENGTH],
    )


def _provider_request_id(request: StageRequest, repair_attempt: int) -> str:
    digest = hashlib.sha256(
        f"{request.run_id}:{request.case_id}:{request.input_sha256}:{repair_attempt}".encode(
            "utf-8"
        )
    ).hexdigest()[:48]
    return f"leanstral-{digest}"


def _strict_leanstral_http_object(
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
    max_response_bytes: int,
) -> dict[str, object]:
    """Read one bounded strict-JSON response from the frozen model service."""

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(max_response_bytes + 1)
    except Exception as exc:
        raise LeanstralAdapterContractError(
            "pinned Leanstral service request failed "
            f"({type(exc).__name__})"
        ) from exc
    if len(raw) > max_response_bytes:
        raise LeanstralAdapterContractError(
            "pinned Leanstral service response exceeded its byte bound"
        )

    def no_duplicates(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LeanstralAdapterContractError(
                    f"pinned Leanstral response contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=no_duplicates,
            parse_constant=lambda item: (_ for _ in ()).throw(
                LeanstralAdapterContractError(
                    f"pinned Leanstral response contains non-finite value {item}"
                )
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LeanstralAdapterContractError(
            "pinned Leanstral service returned invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise LeanstralAdapterContractError(
            "pinned Leanstral service returned a non-object response"
        )
    return value


def _leanstral_model_ids(value: Mapping[str, object]) -> tuple[str, ...]:
    raw = value.get("data", value.get("models"))
    if not isinstance(raw, list):
        raise LeanstralAdapterContractError(
            "pinned Leanstral service omitted its served-model array"
        )
    identities: list[str] = []
    for item in raw:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, Mapping):
            model_id = str(
                item.get("id") or item.get("model") or item.get("name") or ""
            )
        else:
            continue
        if model_id:
            identities.append(model_id)
    return tuple(identities)


def leanstral_strict_llm_generate(
    prompt: str,
    *,
    endpoint: str,
    expected_provider: str,
    expected_model: str,
    audit_receipt: MutableMapping[str, object] | None = None,
    **kwargs: object,
) -> str:
    """Call one exact endpoint/model with strict JSON and no router fallback."""

    if not isinstance(prompt, str) or not prompt.strip():
        raise LeanstralAdapterContractError(
            "Leanstral strict generation requires a non-empty prompt"
        )
    if (
        not isinstance(endpoint, str)
        or not endpoint.strip()
        or not isinstance(expected_provider, str)
        or not expected_provider.strip()
        or not isinstance(expected_model, str)
        or not expected_model.strip()
    ):
        raise LeanstralAdapterContractError(
            "Leanstral strict generation requires a complete frozen identity"
        )
    endpoint = endpoint.strip().rstrip("/")
    parsed_endpoint = urllib.parse.urlsplit(endpoint)
    if (
        parsed_endpoint.scheme not in {"http", "https"}
        or not parsed_endpoint.hostname
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        raise LeanstralAdapterContractError(
            "Leanstral frozen endpoint must be an uncredentialed HTTP(S) origin/path"
        )
    if (
        kwargs.get("provider") != expected_provider
        or kwargs.get("model_name") != expected_model
    ):
        raise LeanstralAdapterContractError(
            "Leanstral provider invocation drifted from the frozen identity"
        )
    if (
        kwargs.get("allow_local_fallback") is not False
        or kwargs.get("disable_model_retry") is not True
    ):
        raise LeanstralAdapterContractError(
            "Leanstral provider invocation did not disable fallback and model retry"
        )
    timeout = kwargs.get("timeout")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or not 0 < float(timeout) <= 300
    ):
        raise LeanstralAdapterContractError(
            "Leanstral provider invocation has an invalid timeout"
        )
    max_tokens = kwargs.get("max_new_tokens")
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or not 1 <= max_tokens <= 1_400
    ):
        raise LeanstralAdapterContractError(
            "Leanstral provider invocation has an invalid token budget"
        )
    temperature = kwargs.get("temperature")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or float(temperature) != 0.0
    ):
        raise LeanstralAdapterContractError(
            "Leanstral pinned route requires temperature zero"
        )
    deadline = time.monotonic() + float(timeout)

    def remaining_timeout() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "pinned Leanstral aggregate HTTP timeout expired"
            )
        return remaining

    def no_duplicates(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LeanstralAdapterContractError(
                    f"Leanstral prompt contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        structured = json.loads(
            prompt,
            object_pairs_hook=no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                LeanstralAdapterContractError(
                    f"Leanstral prompt contains non-finite value {value}"
                )
            ),
        )
    except (TypeError, json.JSONDecodeError) as exc:
        raise LeanstralAdapterContractError(
            "Leanstral strict generation prompt is not JSON"
        ) from exc
    if not isinstance(structured, Mapping):
        raise LeanstralAdapterContractError(
            "Leanstral strict generation prompt must be an object"
        )
    fixed = structured.get("fixed_theorem")
    output_schema = structured.get("output_schema")
    if not isinstance(fixed, Mapping) or not isinstance(output_schema, Mapping):
        raise LeanstralAdapterContractError(
            "Leanstral strict generation requires fixed theorem and output schema"
        )
    theorem_id = _safe_id(fixed.get("theorem_id"), "fixed_theorem.theorem_id")
    if output_schema.get("schema") != LEANSTRAL_PROOF_OUTPUT_SCHEMA:
        raise LeanstralAdapterContractError(
            "Leanstral prompt output schema identity changed"
        )

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "leanstral_fixed_theorem_proof",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "schema": {"const": LEANSTRAL_PROOF_OUTPUT_SCHEMA},
                    "theorem_id": {"const": theorem_id},
                    "proposal_kind": {"const": "proof"},
                    "proof_text": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Lean tactic body inserted after an existing `by`; "
                            "do not prefix the body with `by`, and do not include "
                            "imports, declarations, markdown, or a complete Lean "
                            "source file"
                        ),
                    },
                },
                "required": [
                    "schema",
                    "theorem_id",
                    "proposal_kind",
                    "proof_text",
                ],
                "additionalProperties": False,
            },
        },
    }

    models_request = urllib.request.Request(
        f"{endpoint}/models",
        headers={"Accept": "application/json"},
        method="GET",
    )
    models = _strict_leanstral_http_object(
        models_request,
        timeout_seconds=remaining_timeout(),
        max_response_bytes=1024 * 1024,
    )
    if _leanstral_model_ids(models).count(expected_model) != 1:
        raise LeanstralAdapterContractError(
            "frozen Leanstral model is absent or ambiguous at the pinned endpoint"
        )

    payload = {
        "model": expected_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return exactly one JSON object matching the response schema. "
                    "proof_text is only the Lean tactic body inserted after an "
                    "existing `by`. Never emit markdown, imports, declarations, "
                    "a complete theorem, a leading `by`, or explanatory comments. "
                    "When an `exact ...` term suffices, return only that one line."
                    " Every binder listed in fixed_theorem.assumptions is already "
                    "in scope at the proof start; do not introduce those binders "
                    "again, and use their exact names and types."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
        "response_format": response_format,
        "stop": [
            "<|tool_call_end|>",
            "<|im_end|>",
            "<|im_start|>",
        ],
        "seed": 0,
    }
    completion_request = urllib.request.Request(
        f"{endpoint}/chat/completions",
        data=json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    completion = _strict_leanstral_http_object(
        completion_request,
        timeout_seconds=remaining_timeout(),
        max_response_bytes=64 * 1024,
    )
    if completion.get("model") != expected_model:
        raise LeanstralAdapterContractError(
            "pinned Leanstral completion reported a different model"
        )
    choices = completion.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise LeanstralAdapterContractError(
            "pinned Leanstral completion returned invalid choices"
        )
    choice = choices[0]
    if not isinstance(choice, Mapping) or choice.get("finish_reason") != "stop":
        raise LeanstralAdapterContractError(
            "pinned Leanstral completion did not terminate cleanly"
        )
    message = choice.get("message")
    output = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(output, str) or not output.strip():
        raise LeanstralAdapterContractError(
            "pinned Leanstral completion returned empty text"
        )
    try:
        proposal = json.loads(
            output,
            object_pairs_hook=no_duplicates,
            parse_constant=lambda item: (_ for _ in ()).throw(
                LeanstralAdapterContractError(
                    f"Leanstral proposal contains non-finite value {item}"
                )
            ),
        )
    except (TypeError, json.JSONDecodeError) as exc:
        raise LeanstralAdapterContractError(
            "pinned Leanstral completion did not return a strict JSON proposal"
        ) from exc
    if (
        not isinstance(proposal, dict)
        or set(proposal)
        != {"schema", "theorem_id", "proposal_kind", "proof_text"}
        or proposal.get("schema") != LEANSTRAL_PROOF_OUTPUT_SCHEMA
        or proposal.get("theorem_id") != theorem_id
        or proposal.get("proposal_kind") != "proof"
    ):
        raise LeanstralAdapterContractError(
            "pinned Leanstral completion violated the fixed proposal identity"
        )
    proof_text = proposal.get("proof_text")
    if not isinstance(proof_text, str) or not proof_text.strip():
        raise LeanstralAdapterContractError(
            "pinned Leanstral completion returned an empty proof body"
        )
    proof_text = proof_text.strip()
    normalization = "none"
    if re.match(r"^by(?:\s|$)", proof_text):
        # Leanstral sometimes wraps an otherwise valid tactic sequence in the
        # declaration-level ``by`` requested by its training format.  Remove
        # exactly that outer wrapper; nested tactic terms remain untouched.
        proof_text = textwrap.dedent(proof_text[2:]).strip()
        normalization = "strip_single_leading_by"
    if (
        not proof_text
        or len(proof_text.encode("utf-8")) > LEANSTRAL_MAX_DRAFT_BYTES
        or re.match(r"^by(?:\s|$)", proof_text)
        or _LEANSTRAL_NON_TACTIC_BODY.search(proof_text)
        or _LEANSTRAL_FORBIDDEN_CONSTRUCT.search(proof_text)
    ):
        raise LeanstralAdapterContractError(
            "pinned Leanstral completion did not contain an admissible tactic body"
        )
    proposal["proof_text"] = proof_text
    normalized_output = json.dumps(
        proposal,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if audit_receipt is not None:
        audit_receipt.clear()
        audit_receipt.update(
            {
                "schema": LEANSTRAL_GENERATION_BOUNDARY_SCHEMA,
                "endpoint": endpoint,
                "provider": expected_provider,
                "requested_model": expected_model,
                "response_model": str(completion["model"]),
                "prompt_sha256": hashlib.sha256(
                    prompt.encode("utf-8")
                ).hexdigest(),
                "raw_model_content_sha256": hashlib.sha256(
                    output.encode("utf-8")
                ).hexdigest(),
                "raw_model_content_bytes": len(output.encode("utf-8")),
                "normalized_proposal_sha256": hashlib.sha256(
                    normalized_output.encode("utf-8")
                ).hexdigest(),
                "normalized_proposal_bytes": len(
                    normalized_output.encode("utf-8")
                ),
                "normalization": normalization,
            }
        )
    return normalized_output


class _PinnedLeanstralGenerate:
    """Callable exact-route generator with prompt-keyed audit receipts."""

    def __init__(self, *, endpoint: str, provider: str, model: str) -> None:
        self.endpoint = endpoint
        self.provider = provider
        self.model = model
        self._receipt_local = threading.local()

    def __call__(self, prompt: str, **kwargs: object) -> str:
        if getattr(self._receipt_local, "pending", None) is not None:
            # A delegate can fail after generation but before returning its
            # parsed draft.  Drop that call's unusable receipt so it can never
            # be attached to a later same-prompt proposal on this thread.
            del self._receipt_local.pending
        receipt: dict[str, object] = {}
        output = leanstral_strict_llm_generate(
            prompt,
            endpoint=self.endpoint,
            expected_provider=self.provider,
            expected_model=self.model,
            audit_receipt=receipt,
            **kwargs,
        )
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        self._receipt_local.pending = (prompt_sha256, receipt)
        return output

    def consume_receipt(self, prompt_sha256: str) -> dict[str, object] | None:
        pending = getattr(self._receipt_local, "pending", None)
        if pending is None:
            return None
        del self._receipt_local.pending
        pending_prompt_sha256, receipt = pending
        if pending_prompt_sha256 != prompt_sha256:
            return None
        return receipt


class _AuditedLeanstralProvider:
    """Attach the direct-service receipt to the supervisor's untrusted draft."""

    def __init__(
        self,
        delegate: object,
        generator: _PinnedLeanstralGenerate,
    ) -> None:
        self._delegate = delegate
        self._generator = generator

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    def prove(self, request: object) -> Mapping[str, object]:
        result = getattr(self._delegate, "prove")(request)
        if not isinstance(result, Mapping):
            raise LeanstralAdapterContractError(
                "Leanstral supervisor provider returned a non-object draft"
            )
        draft = dict(result)
        prompt_sha256 = draft.get("prompt_sha256")
        proof_text = draft.get("proof_text")
        proposal = {
            "schema": draft.get("proposal_schema"),
            "theorem_id": draft.get("theorem_id"),
            "proposal_kind": draft.get("proposal_kind"),
            "proof_text": proof_text,
        }
        if (
            proposal["schema"] != LEANSTRAL_PROOF_OUTPUT_SCHEMA
            or not isinstance(proposal["theorem_id"], str)
            or not proposal["theorem_id"]
            or proposal["proposal_kind"] != "proof"
            or not isinstance(proof_text, str)
            or not proof_text
            or draft.get("draft_text") != proof_text
        ):
            raise LeanstralAdapterContractError(
                "Leanstral draft cannot be bound to the four-field proposal"
            )
        normalized_proposal = json.dumps(
            proposal,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        normalized_proposal_sha256 = hashlib.sha256(
            normalized_proposal
        ).hexdigest()
        receipt = (
            self._generator.consume_receipt(prompt_sha256)
            if isinstance(prompt_sha256, str)
            else None
        )
        if receipt is None:
            raise LeanstralAdapterContractError(
                "Leanstral draft omitted its generation-boundary receipt"
            )
        if (
            receipt.get("schema") != LEANSTRAL_GENERATION_BOUNDARY_SCHEMA
            or receipt.get("prompt_sha256") != prompt_sha256
            or receipt.get("normalized_proposal_sha256")
            != normalized_proposal_sha256
            or receipt.get("normalized_proposal_bytes")
            != len(normalized_proposal)
        ):
            raise LeanstralAdapterContractError(
                "Leanstral generation receipt does not match the returned draft"
            )
        metadata = draft.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise LeanstralAdapterContractError(
                "Leanstral draft metadata is not an object"
            )
        if "benchmark_generation_boundary" in metadata:
            raise LeanstralAdapterContractError(
                "Leanstral draft metadata collided with boundary provenance"
            )
        draft["metadata"] = {
            **dict(metadata),
            "benchmark_generation_boundary": receipt,
        }
        return draft


def create_pinned_leanstral_llm_generate(
    *,
    endpoint: str,
    provider: str,
    model: str,
) -> Callable[..., str]:
    """Bind the strict generator to one capability-frozen service identity."""

    return _PinnedLeanstralGenerate(
        endpoint=endpoint,
        provider=provider,
        model=model,
    )


def create_pinned_leanstral_provider(
    provider_config: object,
    *,
    endpoint: str,
    provider: str,
    model: str,
) -> object:
    """Create the supervisor provider with exact-route audit provenance."""

    module = import_source_bound_ipfs_accelerate(
        "ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider"
    )
    factory = getattr(module, "create_leanstral_proof_provider", None)
    if not callable(factory):
        raise LeanstralAdapterContractError(
            "Leanstral supervisor provider factory is unavailable"
        )
    generate = _PinnedLeanstralGenerate(
        endpoint=endpoint,
        provider=provider,
        model=model,
    )
    return _AuditedLeanstralProvider(
        factory(provider_config, llm_generate=generate),
        generate,
    )


def _leanstral_supervisor_request(
    *,
    request: StageRequest,
    payload: Mapping[str, object],
    repair_attempt: int,
    config: LeanstralAdapterConfig,
    protocol: object,
    capabilities: object,
    contracts: object,
) -> object:
    """Bind one provider invocation to measured and enclosing-case caps."""

    configured_wall_time_ms = max(
        1,
        math.ceil(float(config.model_timeout_seconds) * 1_000),
    )
    now_unix_ms = int(time.time() * 1_000)
    deadline_unix_ms = now_unix_ms + configured_wall_time_ms
    if request.deadline_unix_ms is not None:
        deadline_unix_ms = min(
            deadline_unix_ms,
            request.deadline_unix_ms,
        )
    wall_time_ms = max(
        1,
        min(configured_wall_time_ms, deadline_unix_ms - now_unix_ms),
    )
    return getattr(protocol, "ProviderRequest")(
        operation=getattr(capabilities, "ProofProviderOperation").PROVE,
        payload=payload,
        request_id=_provider_request_id(request, repair_attempt),
        resource_budget=getattr(contracts, "ResourceBudget")(
            wall_time_ms=wall_time_ms,
            model_token_limit=config.model_token_limit,
            max_output_bytes=config.max_draft_bytes,
        ),
        network_allowed=False,
        deadline_unix_ms=deadline_unix_ms,
    )


def _local_leanstral_handler(
    provider_config: object | None = None,
    adapter_config: LeanstralAdapterConfig | None = None,
) -> StageHandler:
    """Return a lazy handler over the supervisor-owned local provider."""

    provider_holder: dict[str, object] = {}

    def invoke(request: StageRequest) -> object:
        module = import_source_bound_ipfs_accelerate(
            "ipfs_accelerate_py.agent_supervisor.leanstral_proof_provider"
        )
        protocol = import_source_bound_ipfs_accelerate(
            "ipfs_accelerate_py.agent_supervisor.formal_verification_provider"
        )
        capabilities = import_source_bound_ipfs_accelerate(
            "ipfs_accelerate_py.agent_supervisor.formal_verification_capabilities"
        )
        contracts = import_source_bound_ipfs_accelerate(
            "ipfs_accelerate_py.agent_supervisor.formal_verification_contracts"
        )
        provider = provider_holder.get("provider")
        if provider is None:
            factory = getattr(module, "create_leanstral_proof_provider")
            provider = factory(provider_config) if provider_config is not None else factory()
            provider_holder["provider"] = provider
        if not isinstance(request.input_data, Mapping):
            raise LeanstralAdapterContractError(
                "normalized Leanstral provider payload must be an object"
            )
        payload = dict(request.input_data)
        repair_attempt = payload.get("repair_attempt", 0)
        if (
            isinstance(repair_attempt, bool)
            or not isinstance(repair_attempt, int)
            or repair_attempt not in (0, 1)
        ):
            raise LeanstralAdapterContractError(
                "normalized Leanstral repair_attempt is invalid"
            )
        provider_request = _leanstral_supervisor_request(
            request=request,
            payload=payload,
            repair_attempt=repair_attempt,
            config=adapter_config or LeanstralAdapterConfig(),
            protocol=protocol,
            capabilities=capabilities,
            contracts=contracts,
        )
        return getattr(provider, "prove")(provider_request)

    return invoke


class LeanstralAdapter(StageAdapter):
    """Benchmark boundary for untrusted Leanstral synthesis and one repair.

    ``handler`` remains injectable for deterministic benchmark tests.  With no
    handler the local supervisor provider is resolved lazily at execution time;
    an absent router/model is therefore an explicit unavailable result rather
    than an import-time failure or a silent fallback to another arm.
    """

    def __init__(
        self,
        handler: StageHandler | None = None,
        *,
        provider: object | None = None,
        config: LeanstralAdapterConfig | None = None,
        provider_config: object | None = None,
        **kwargs: object,
    ) -> None:
        if handler is not None and provider is not None:
            raise ProtocolContractError("provide either handler or provider, not both")
        object.__setattr__(self, "config", config or LeanstralAdapterConfig())
        selected = handler
        if provider is not None:
            if callable(provider):
                selected = provider  # type: ignore[assignment]
            elif callable(getattr(provider, "prove", None)):
                def invoke(request: StageRequest) -> object:
                    if not isinstance(request.input_data, Mapping):
                        raise LeanstralAdapterContractError(
                            "normalized Leanstral provider payload must be an object"
                        )
                    payload = dict(request.input_data)
                    repair_attempt = payload.get("repair_attempt", 0)
                    if (
                        isinstance(repair_attempt, bool)
                        or not isinstance(repair_attempt, int)
                        or repair_attempt not in (0, 1)
                    ):
                        raise LeanstralAdapterContractError(
                            "normalized Leanstral repair_attempt is invalid"
                        )
                    # A provider object supplied by a benchmark test follows
                    # the same supervisor ProviderRequest boundary as the
                    # local provider, without importing it at module import.
                    protocol = import_source_bound_ipfs_accelerate(
                        "ipfs_accelerate_py.agent_supervisor.formal_verification_provider"
                    )
                    capabilities = import_source_bound_ipfs_accelerate(
                        "ipfs_accelerate_py.agent_supervisor.formal_verification_capabilities"
                    )
                    verification_contracts = import_source_bound_ipfs_accelerate(
                        "ipfs_accelerate_py.agent_supervisor.formal_verification_contracts"
                    )
                    return provider.prove(
                        _leanstral_supervisor_request(
                            request=request,
                            payload=payload,
                            repair_attempt=repair_attempt,
                            config=self.config,
                            protocol=protocol,
                            capabilities=capabilities,
                            contracts=verification_contracts,
                        )
                    )
                selected = invoke
            else:
                raise ProtocolContractError("provider must be callable or expose prove()")
        elif selected is None:
            selected = _local_leanstral_handler(provider_config, self.config)

        def validated(request: StageRequest) -> object:
            try:
                # The shared route builder has always accepted generic injected
                # handlers.  Preserve that compatibility when the caller has
                # not supplied a Leanstral obligation contract; direct
                # Leanstral benchmark requests still take the strict path.
                if (
                    handler is not None
                    and (
                        not isinstance(request.input_data, Mapping)
                        or not any(
                            key in request.input_data
                            for key in ("obligation_id", "obligation_ids")
                        )
                    )
                ):
                    return selected(request)  # type: ignore[misc]
                payload, obligation_id, repair_attempt = _leanstral_input(
                    request, self.config
                )
                normalized_request = replace(request, input_data=payload)
                raw = selected(normalized_request)  # type: ignore[misc]
                if isinstance(raw, StageOutput):
                    if raw.status is not StageStatus.SUCCESS:
                        return raw
                    output = raw
                else:
                    output = StageOutput(data=raw)
                data = _validate_leanstral_draft(
                    output.data,
                    request=request,
                    obligation_id=obligation_id,
                    repair_attempt=repair_attempt,
                    config=self.config,
                )
                evidence_without_id = {
                    "schema": LEANSTRAL_EVIDENCE_SCHEMA,
                    "obligation_id": obligation_id,
                    "mode": "repair" if repair_attempt else "synthesis",
                    "repair_attempts": repair_attempt,
                    "max_repair_attempts": self.config.max_repair_attempts,
                    "draft": data,
                    "trust": {
                        "assurance": "unverified",
                        "verified": False,
                        "authoritative": False,
                        "kernel_checked": False,
                    },
                    "resource_classes": {
                        "model_inference": self.config.model_resource_class,
                        "kernel_check": self.config.kernel_resource_class,
                    },
                }
                evidence_id = hashlib.sha256(
                    canonical_json(evidence_without_id).encode("utf-8")
                ).hexdigest()
                evidence = {"evidence_id": evidence_id, **evidence_without_id}
                identity = {
                    **dict(output.effective_identity),
                    "provider": data.get("llm_provider", "leanstral"),
                    "model": data.get("model", "Leanstral"),
                    "obligation_id": obligation_id,
                    "repair_attempt": repair_attempt,
                    "resource_class": self.config.model_resource_class,
                }
                return replace(output, data=evidence, effective_identity=identity)
            except LeanstralAdapterContractError as exc:
                return _leanstral_failure(request, str(exc))
            except (ImportError, ModuleNotFoundError) as exc:
                return _leanstral_failure(
                    request,
                    f"Leanstral provider unavailable: {type(exc).__name__}",
                    unavailable=True,
                )
            except TimeoutError as exc:
                return _leanstral_failure(request, f"Leanstral provider timed out: {exc}")
            except Exception as exc:
                provider_code = str(getattr(getattr(exc, "code", None), "value", getattr(exc, "code", "")))
                if provider_code in {"unavailable", "optional_dependency"}:
                    return _leanstral_failure(
                        request, "Leanstral provider is unavailable", unavailable=True
                    )
                if provider_code in {"timed_out", "resource_exhausted", "malformed_response", "malformed_request", "unsupported", "provider_error"}:
                    return _leanstral_failure(
                        request,
                        f"Leanstral provider rejected the request ({provider_code})",
                    )
                return StageOutput(
                    status=StageStatus.FAILED,
                    effective_identity=request.requested_identity,
                    failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
                    failure_detail=f"Leanstral adapter raised {type(exc).__name__}",
                )

        super().__init__(StageName.LEANSTRAL, handler=validated, **kwargs)


def run_leanstral_runtime_readiness_smoke(
    provider: object,
    *,
    provider_identity: Mapping[str, object],
) -> StageRecord:
    """Exercise the non-corpus A3 adapter/provider boundary end to end.

    The caller owns the provider and therefore decides whether this is a
    deterministic injected test or a bounded live-router probe.  Either way,
    the exact same compiler-bound context and strict draft validation used by
    the measured A3 fallback are exercised.
    """

    requested_provider = provider_identity.get("provider")
    requested_model = provider_identity.get("model")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (requested_provider, requested_model)
    ):
        raise LeanstralAdapterContractError(
            "Leanstral readiness identity requires provider and model"
        )
    obligation_id = "leanstral-runtime-smoke-obligation"
    proof_obligation = {
        "kind": "theorem",
        "logic": "fol",
        "target": "identity",
    }
    obligation_sha256 = hashlib.sha256(
        canonical_json(proof_obligation).encode("utf-8")
    ).hexdigest()
    theorem_name = "hssl_leanstral_runtime_smoke"
    source_template = (
        "namespace HSSLBenchmark\n"
        f"theorem {theorem_name} (x : Nat) : x = x := by\n"
        "  {{PROOF}}\n"
        "end HSSLBenchmark\n"
    )
    compiled = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark.compiled-obligation.v1"
        ),
        "compiler_version": "1",
        "obligation_id": obligation_id,
        "kind": "theorem",
        "logic": "fol",
        "semantic_target": "identity",
        "obligation_sha256": obligation_sha256,
        "theorem_name": theorem_name,
        "source_template": source_template,
        "source_template_sha256": hashlib.sha256(
            source_template.encode("utf-8")
        ).hexdigest(),
    }
    compiler = StageArtifact(
        stage=StageName.COMPILER,
        status=StageStatus.SUCCESS,
        data={"compiled_obligation": compiled},
        output_sha256=None,
        effective_identity={"entrypoint": "leanstral-readiness-smoke"},
        invocation_index=0,
    )
    request = StageRequest(
        run_id="leanstral-runtime-smoke",
        case_id="non-corpus-identity",
        case_manifest_sha256=hashlib.sha256(
            b"hssl-leanstral-runtime-readiness-smoke-v1"
        ).hexdigest(),
        variant_id="A3",
        input_data={
            "text": (
                "Non-corpus readiness theorem: for every natural number x, "
                "x equals x."
            ),
            "obligation_id": obligation_id,
            "proof_obligation": proof_obligation,
        },
        requested_identity={
            "provider": requested_provider,
            "model": requested_model,
            "policy": "proof_failure_fallback",
        },
        source=("leanstral_runtime_readiness_smoke",),
        upstream_artifacts=(compiler,),
        invocation_index=1,
    )
    return LeanstralAdapter(provider=provider).run(request)


class KernelAdapter(StageAdapter):
    def __init__(self, handler: StageHandler | None = None, **kwargs: object) -> None:
        super().__init__(StageName.KERNEL, handler=handler, **kwargs)


def build_default_adapters(
    handlers: Mapping[StageName, StageHandler] | None = None,
) -> Mapping[StageName, StageAdapter]:
    """Build the registered route without importing or configuring backends."""

    handlers = {} if handlers is None else dict(handlers)
    unknown = set(handlers) - set(STAGE_ORDER)
    if unknown:
        raise ProtocolContractError(f"handlers contain unknown stages: {sorted(unknown, key=str)}")
    adapters = {
        StageName.COMPILER: CompilerAdapter(handlers.get(StageName.COMPILER)),
        StageName.SPACY: SpacyAdapter(handlers.get(StageName.SPACY)),
        StageName.SYMAI: SymaiAdapter(handlers.get(StageName.SYMAI)),
        StageName.HAMMER: HammerAdapter(handlers.get(StageName.HAMMER)),
        # Keep the dependency-free default route inert.  The configured
        # LeanstralAdapter resolves a local provider lazily, so using the base
        # adapter here is the only way for an absent handler to remain truly
        # unconfigured as promised by this factory.
        StageName.LEANSTRAL: (
            LeanstralAdapter(handlers[StageName.LEANSTRAL])
            if StageName.LEANSTRAL in handlers
            else StageAdapter(StageName.LEANSTRAL)
        ),
        StageName.KERNEL: KernelAdapter(handlers.get(StageName.KERNEL)),
    }
    return MappingProxyType(adapters)


def run_stages(
    request: StageRequest,
    adapters: Mapping[StageName, StageAdapter],
    *,
    stages: Sequence[StageName] = STAGE_ORDER,
) -> CaseResultRecord:
    """Run an explicit stage sequence and bind all emitted records."""

    if not isinstance(adapters, Mapping):
        raise ProtocolContractError("adapters must be a mapping")
    records: list[StageRecord] = []
    current_request = request
    selected_stages = tuple(stages)
    for index, stage in enumerate(selected_stages):
        if not isinstance(stage, StageName):
            raise ProtocolContractError("stages must contain StageName values")
        adapter = adapters.get(stage)
        if not isinstance(adapter, StageAdapter):
            raise ProtocolContractError(f"missing adapter for {stage.value}")
        record = adapter.run(current_request)
        records.append(record)
        if index + 1 < len(selected_stages):
            artifact = StageArtifact(
                stage=stage,
                status=record.status,
                data=record.data,
                output_sha256=record.output_sha256,
                effective_identity={
                    **dict(record.provenance.effective_identity),
                    "graph_invoked": True,
                    "graph_invocation_index": index,
                },
                invocation_index=index,
                invoked=True,
                policy_reason="explicit_stage_sequence",
            )
            current_request = replace(
                current_request,
                upstream_stage_digests=(
                    *current_request.upstream_stage_digests,
                    record.digest,
                ),
                upstream_artifacts=(
                    *current_request.upstream_artifacts,
                    artifact,
                ),
                invocation_index=index + 1,
            )
    return CaseResultRecord.from_stages(records)


# Descriptive aliases make the public boundary easy to discover for callers
# that use "versioned" terminology from the objective heap.
VersionedStageAdapter = StageAdapter
StageTelemetry = TelemetryRecord
PipelineResult = CaseResultRecord


__all__ = [
    "ADAPTER_SOURCE",
    "ADAPTER_VERSION",
    "CaseResultRecord",
    "CompilerAdapter",
    "create_pinned_leanstral_llm_generate",
    "create_pinned_leanstral_provider",
    "HAMMER_EVIDENCE_SCHEMA",
    "HammerAdapter",
    "HammerAdapterContractError",
    "HSSLEV0335D9B",
    "HSSLEV0306C18",
    "HSSLEV0310F79",
    "HSSLEV0328B3A",
    "HSSLEV0342A4C",
    "KernelAdapter",
    "LEANSTRAL_DRAFT_SCHEMA",
    "LEANSTRAL_EVIDENCE_SCHEMA",
    "LEANSTRAL_GENERATION_BOUNDARY_SCHEMA",
    "LEANSTRAL_KERNEL_RESOURCE_CLASS",
    "LEANSTRAL_MAX_CONTEXT_BYTES",
    "LEANSTRAL_MAX_DRAFT_BYTES",
    "LEANSTRAL_MAX_REPAIR_ATTEMPTS",
    "LEANSTRAL_MEASURED_MAX_NEW_TOKENS",
    "LEANSTRAL_MEASURED_TIMEOUT_SECONDS",
    "LEANSTRAL_MODEL_RESOURCE_CLASS",
    "LEANSTRAL_PROOF_OUTPUT_SCHEMA",
    "LeanstralAdapterConfig",
    "LeanstralAdapterContractError",
    "LeanstralAdapter",
    "leanstral_strict_llm_generate",
    "PipelineResult",
    "SEMANTIC_CONTEXT_MAX_BYTES",
    "SEMANTIC_CONTEXT_SCHEMA",
    "SPACY_EVIDENCE_SCHEMA",
    "SPACY_MAX_EVIDENCE_BYTES",
    "SPACY_MAX_TEXT_BYTES",
    "SpacyAdapter",
    "SpacyAdapterConfig",
    "SpacyAdapterMode",
    "StageAdapter",
    "StageArtifact",
    "StageHandler",
    "StageInvocation",
    "StageOutput",
    "StageRequest",
    "StageTelemetry",
    "STAGE_ORDER",
    "SYMAI_EVIDENCE_SCHEMA",
    "SYMAI_MAX_CANDIDATE_BYTES",
    "SYMAI_MAX_LIST_ITEMS",
    "SYMAI_MAX_RAW_OUTPUT_BYTES",
    "SYMAI_MAX_RETRIES",
    "SYMAI_MAX_TEXT_BYTES",
    "SYMAI_PROMPT_SCHEMA",
    "SYMAI_RESPONSE_FORMAT",
    "SYMAI_ROUTER_ENGINE",
    "SymaiAdapter",
    "SymaiAdapterConfig",
    "SymaiAdapterContractError",
    "SymaiEngineFactory",
    "SymaiRecursiveRoutingError",
    "SymaiTraceGetter",
    "VersionedStageAdapter",
    "build_upstream_semantic_context",
    "build_default_adapters",
    "run_stages",
]
