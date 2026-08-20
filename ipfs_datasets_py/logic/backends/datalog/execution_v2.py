"""SecPAL / Datalog authorization execution and parity (LFP2-030).

Interface: ``RuleProviderEvidence@2``

Runs typed authorization queries over the in-process Datalog and SecPAL
reference evaluators with:

* policy / query / provenance / semantics bindings on every answer;
* delegation, stratification, closed/open-world semantics receipts;
* native-path and optional engine-shadow parity receipts; and
* a hard fail-closed rule that **fallback or mock output cannot establish
  policy authority**.

External engines (Soufflé, SecPAL CLI) remain shadows.  They may agree or
disagree with the reference; they never mint policy authority alone.
Authorization never elevates to theorem / proof / satisfiability authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.datalog.adapters import (
    DEFAULT_AUTHORIZATION_FIXTURES,
    AuthorizationBackendError,
    AuthorizationBackendOutcome,
    AuthorizationFixture,
    DatalogAuthorizationBackend,
    EngineKind,
    EvaluationReceipt,
    SecPALAuthorizationBackend,
    bound_diagnostics,
    outcome_to_result_status,
    render_datalog_program,
    render_secpal_program,
)
from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
from ipfs_datasets_py.logic.backends.results import (
    AuthorizationResult,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    provider_id,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.software_verification.authorization import (
    AuthorizationEvidenceAuthority,
    AuthorizationIR,
    AuthorizationValidationError,
    DecisionExplanation,
    DecisionOutcome,
    DecisionQuery,
    ExplanationStepKind,
    GeneratedCodeCorrectness,
    PolicyDecision,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

RULE_PROVIDER_EVIDENCE_V2_INTERFACE: Final = "RuleProviderEvidence@2"
RULE_EXECUTION_REQUEST_V2_INTERFACE: Final = "RuleExecutionRequest@2"
RULE_EXECUTION_RESULT_V2_INTERFACE: Final = "RuleExecutionResult@2"
RULE_PARITY_RECEIPT_V2_INTERFACE: Final = "RuleParityReceipt@2"
RULE_SEMANTICS_BINDING_V2_INTERFACE: Final = "RuleSemanticsBinding@2"

RULE_PROVIDER_EVIDENCE_SCHEMA: Final = "rule-provider-evidence/v2"
RULE_EXECUTION_REQUEST_SCHEMA: Final = "rule-execution-request/v2"
RULE_EXECUTION_RESULT_SCHEMA: Final = "rule-execution-result/v2"
RULE_PARITY_RECEIPT_SCHEMA: Final = "rule-parity-receipt/v2"
RULE_SEMANTICS_BINDING_SCHEMA: Final = "rule-semantics-binding/v2"
RULE_PROVENANCE_BINDING_SCHEMA: Final = "rule-provenance-binding/v2"

RULE_EXECUTION_V2_MODULE_VERSION: Final = "1.0.0"
RULE_EXECUTION_V2_TASK_ID: Final = "LFP2-030"
RULE_EXECUTION_V2_GOAL_ID: Final = "LFP2-G060"

RULE_LANE_ID: Final = "datalog_secpal"
RULE_EVIDENCE_KIND: Final = "authorization"

_MAX_DIAGNOSTICS: Final = 64
_MAX_METADATA_BYTES: Final = 8_192
_MAX_SOURCE_REFS: Final = 64
_MAX_PROVENANCE_STEPS: Final = 128

_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "arbitrary_payload",
        "claimed_execution",
        "claimed_policy",
        "claimed_proof",
        "execution_result",
        "fake_replay",
        "family_string",
        "free_form_family",
        "is_proved",
        "logic_family",
        "mock_execution",
        "mock_result",
        "opaque_extension",
        "payload",
        "proof_result",
        "proof_status",
        "proved",
        "raw_formula",
        "raw_result",
        "raw_source",
        "solver_result",
        "target_source",
        "theorem_status",
        "verification_result",
        "verification_status",
    }
)

_NON_AUTHORITATIVE_SIGNAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "availability",
        "available",
        "confidence",
        "fallback",
        "fallback_output",
        "fluent_text",
        "is_valid",
        "mock",
        "mock_output",
        "similarity",
    }
)


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class RuleExecutionError(SyntaxContractError):
    """Raised when rule/authorization execution v2 inputs are malformed."""


class RuleAuthorityError(RuleExecutionError):
    """Raised when a claim would exceed the authorization authority ceiling."""


class RuleProviderKind(StrEnum):
    """Closed set of rule authorization providers."""

    DATALOG = "datalog"
    SECPAL = "secpal"
    PARITY = "parity"


class WorldSemantics(StrEnum):
    """Closed/open-world evaluation policy bound into every answer."""

    CLOSED_WORLD = "closed_world"
    OPEN_WORLD = "open_world"


class RuleExecutionMode(StrEnum):
    """How the evaluation was produced.

    Only ``native_reference`` (and parity of native paths) may establish
    policy authority.  ``engine_shadow``, ``fallback``, and ``mock`` never do.
    """

    NATIVE_REFERENCE = "native_reference"
    ENGINE_SHADOW = "engine_shadow"
    FALLBACK = "fallback"
    MOCK = "mock"


class RuleDisposition(StrEnum):
    """Closed set of rule-execution dispositions."""

    ALLOW = "allow"
    DENY = "deny"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"
    MOCK_REJECTED = "mock_rejected"
    FALLBACK_REJECTED = "fallback_rejected"
    PARITY_DISAGREEMENT = "parity_disagreement"
    BOUNDS_EXHAUSTED = "bounds_exhausted"
    INVALID_REQUEST = "invalid_request"
    SHADOW_UNAVAILABLE = "shadow_unavailable"


class RuleClaimKind(StrEnum):
    """Claims that mock / fallback / availability must never establish."""

    POLICY = "policy"
    PROOF = "proof"
    SATISFIABILITY = "satisfiability"
    THEOREM = "theorem"


_PROVIDER_ALIASES: Final[dict[str, RuleProviderKind]] = {
    "datalog": RuleProviderKind.DATALOG,
    "datalog_authorization": RuleProviderKind.DATALOG,
    "datalog-authorization": RuleProviderKind.DATALOG,
    "authorization-datalog": RuleProviderKind.DATALOG,
    "souffle": RuleProviderKind.DATALOG,
    "secpal": RuleProviderKind.SECPAL,
    "secpal_authorization": RuleProviderKind.SECPAL,
    "secpal-authorization": RuleProviderKind.SECPAL,
    "authorization-secpal": RuleProviderKind.SECPAL,
    "parity": RuleProviderKind.PARITY,
    "datalog_secpal": RuleProviderKind.PARITY,
    "datalog-secpal": RuleProviderKind.PARITY,
}


def normalize_rule_provider(
    value: RuleProviderKind | str,
) -> RuleProviderKind:
    """Normalize provider labels into the closed rule provider set."""

    if isinstance(value, RuleProviderKind):
        return value
    key = str(value).strip().lower().replace("-", "_")
    # Keep hyphenated keys in the alias table too.
    if key not in _PROVIDER_ALIASES:
        # Try original with hyphens restored for ids like datalog-authorization.
        alt = str(value).strip().lower()
        if alt in _PROVIDER_ALIASES:
            return _PROVIDER_ALIASES[alt]
        raise RuleExecutionError(
            f"unsupported rule provider: {value!r}; "
            f"expected datalog, secpal, or parity"
        )
    return _PROVIDER_ALIASES[key]


def provider_backend_id(provider: RuleProviderKind) -> str:
    if provider is RuleProviderKind.DATALOG:
        return "datalog-authorization"
    if provider is RuleProviderKind.SECPAL:
        return "secpal-authorization"
    return "datalog_secpal"


def provider_logic_identity(provider: RuleProviderKind) -> LogicIdentity:
    """Return the canonical provider identity for matrix / evidence binding."""

    if provider is RuleProviderKind.PARITY:
        return provider_id("datalog_secpal")
    if provider is RuleProviderKind.DATALOG:
        return provider_id("datalog-authorization")
    return provider_id("secpal-authorization")


def non_authoritative_signal_establishes(
    claim: RuleClaimKind | str,
    *,
    mock_output: object = None,
    fallback_output: object = None,
    available: bool | None = None,
    confidence: float | None = None,
    fluent_text: str | None = None,
) -> bool:
    """Always ``False``: mock / fallback / availability cannot establish claims.

    Covers policy, proof, satisfiability, and theorem (LFP2-030 acceptance).
    """

    del (
        claim,
        mock_output,
        fallback_output,
        available,
        confidence,
        fluent_text,
    )
    return False


def mock_or_fallback_establishes_policy(
    *,
    mock_output: object = None,
    fallback_output: object = None,
    available: bool | None = None,
) -> bool:
    """Explicit acceptance helper: mock/fallback never establish policy."""

    return non_authoritative_signal_establishes(
        RuleClaimKind.POLICY,
        mock_output=mock_output,
        fallback_output=fallback_output,
        available=available,
    )


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise RuleExecutionError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise RuleExecutionError(f"{field_name} must be a boolean")


def _digest_of(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _source_ref_ids(value: object, field_name: str = "source_ref_ids") -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_SOURCE_REFS:
        raise RuleExecutionError(
            f"{field_name} exceeds hard limit {_MAX_SOURCE_REFS}"
        )
    refs: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        ref = _record_id(item, f"{field_name}[{index}]")
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return tuple(refs)


def _forbid_authority_metadata(metadata: Mapping[str, Any], field_name: str) -> None:
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS or key in _NON_AUTHORITATIVE_SIGNAL_KEYS:
            raise RuleAuthorityError(
                f"{field_name} rejects free-form authority/signal key {key!r}; "
                "use typed rule evidence fields only"
            )


def _outcome_to_disposition(outcome: DecisionOutcome) -> RuleDisposition:
    if outcome is DecisionOutcome.ALLOW:
        return RuleDisposition.ALLOW
    if outcome is DecisionOutcome.DENY:
        return RuleDisposition.DENY
    if outcome is DecisionOutcome.CONFLICT:
        return RuleDisposition.CONFLICT
    return RuleDisposition.UNKNOWN


# ---------------------------------------------------------------------------
# Semantics / provenance bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleSemanticsBindingV2:
    """World, stratification, delegation, and precedence semantics for one answer.

    Interface: ``RuleSemanticsBinding@2``.
    """

    world: WorldSemantics | str
    max_delegation_depth: int
    max_derivation_depth: int
    max_stratum: int
    strata_used: tuple[int, ...] = ()
    precedence: str = "deny_overrides"
    closed_under_negation: bool = True
    schema_version: str = RULE_SEMANTICS_BINDING_SCHEMA

    interface: ClassVar[str] = RULE_SEMANTICS_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "world", _enum(self.world, WorldSemantics, "world")
        )
        for name in (
            "max_delegation_depth",
            "max_derivation_depth",
            "max_stratum",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RuleExecutionError(f"{name} must be a non-negative integer")
        strata = tuple(int(item) for item in self.strata_used)
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in self.strata_used
        ):
            raise RuleExecutionError("strata_used must contain non-negative integers")
        object.__setattr__(self, "strata_used", strata)
        object.__setattr__(
            self, "precedence", _text(self.precedence, "precedence", maximum=128)
        )
        if not isinstance(self.closed_under_negation, bool):
            raise RuleExecutionError("closed_under_negation must be a boolean")
        if self.schema_version != RULE_SEMANTICS_BINDING_SCHEMA:
            raise RuleExecutionError(
                f"unsupported semantics binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_document(
        cls,
        document: AuthorizationIR,
        *,
        world: WorldSemantics | str = WorldSemantics.CLOSED_WORLD,
    ) -> RuleSemanticsBindingV2:
        if not isinstance(document, AuthorizationIR):
            raise RuleExecutionError("document must be an AuthorizationIR")
        strata = tuple(sorted({rule.stratum for rule in document.rules}))
        precedence = (
            document.precedence.resolution.value
            if hasattr(document.precedence.resolution, "value")
            else str(document.precedence.resolution)
        )
        return cls(
            world=world,
            max_delegation_depth=document.bounds.max_delegation_depth,
            max_derivation_depth=document.bounds.max_derivation_depth,
            max_stratum=document.bounds.max_stratum,
            strata_used=strata,
            precedence=precedence,
            closed_under_negation=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "closed_under_negation": self.closed_under_negation,
            "interface": self.interface,
            "max_delegation_depth": self.max_delegation_depth,
            "max_derivation_depth": self.max_derivation_depth,
            "max_stratum": self.max_stratum,
            "precedence": self.precedence,
            "schema_version": self.schema_version,
            "strata_used": list(self.strata_used),
            "world": (
                self.world.value
                if isinstance(self.world, WorldSemantics)
                else self.world
            ),
        }


@dataclass(frozen=True, slots=True)
class RuleProvenanceBindingV2:
    """Concrete provenance bound to one authorization answer."""

    policy_digest: str
    query_id: str
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    bound_rule_ids: tuple[str, ...] = ()
    bound_fact_ids: tuple[str, ...] = ()
    bound_delegation_ids: tuple[str, ...] = ()
    bound_trust_root_ids: tuple[str, ...] = ()
    explanation_id: str = ""
    schema_version: str = RULE_PROVENANCE_BINDING_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_digest", _sha256_hex(self.policy_digest, "policy_digest")
        )
        object.__setattr__(self, "query_id", _record_id(self.query_id, "query_id"))
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )
        object.__setattr__(
            self,
            "bound_rule_ids",
            tuple(_record_id(item, "bound_rule_ids") for item in self.bound_rule_ids),
        )
        object.__setattr__(
            self,
            "bound_fact_ids",
            tuple(_record_id(item, "bound_fact_ids") for item in self.bound_fact_ids),
        )
        object.__setattr__(
            self,
            "bound_delegation_ids",
            tuple(
                _record_id(item, "bound_delegation_ids")
                for item in self.bound_delegation_ids
            ),
        )
        object.__setattr__(
            self,
            "bound_trust_root_ids",
            tuple(
                _record_id(item, "bound_trust_root_ids")
                for item in self.bound_trust_root_ids
            ),
        )
        if self.explanation_id:
            object.__setattr__(
                self,
                "explanation_id",
                _record_id(self.explanation_id, "explanation_id"),
            )
        if self.schema_version != RULE_PROVENANCE_BINDING_SCHEMA:
            raise RuleExecutionError(
                f"unsupported provenance binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_evaluation(
        cls,
        *,
        document: AuthorizationIR,
        query: DecisionQuery,
        explanation: DecisionExplanation | None,
    ) -> RuleProvenanceBindingV2:
        rule_ids: list[str] = []
        fact_ids: list[str] = []
        delegation_ids: list[str] = []
        trust_ids: list[str] = []
        explanation_id = ""
        if explanation is not None:
            explanation_id = explanation.explanation_id
            for step in explanation.steps[:_MAX_PROVENANCE_STEPS]:
                if step.kind is ExplanationStepKind.RULE:
                    rule_ids.append(step.reference_id)
                elif step.kind is ExplanationStepKind.FACT:
                    fact_ids.append(step.reference_id)
                elif step.kind is ExplanationStepKind.DELEGATION:
                    delegation_ids.append(step.reference_id)
                elif step.kind is ExplanationStepKind.TRUST_ROOT:
                    trust_ids.append(step.reference_id)
        source_refs = tuple(
            dict.fromkeys(
                [source.ref_id for source in document.sources]
                + list(query.source_ref_ids)
            )
        )
        return cls(
            policy_digest=document.sha256,
            query_id=query.query_id,
            source_ref_ids=source_refs,
            bound_rule_ids=tuple(dict.fromkeys(rule_ids)),
            bound_fact_ids=tuple(dict.fromkeys(fact_ids)),
            bound_delegation_ids=tuple(dict.fromkeys(delegation_ids)),
            bound_trust_root_ids=tuple(dict.fromkeys(trust_ids)),
            explanation_id=explanation_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_delegation_ids": list(self.bound_delegation_ids),
            "bound_fact_ids": list(self.bound_fact_ids),
            "bound_rule_ids": list(self.bound_rule_ids),
            "bound_trust_root_ids": list(self.bound_trust_root_ids),
            "explanation_id": self.explanation_id,
            "policy_digest": self.policy_digest,
            "query_id": self.query_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class RuleParityReceiptV2:
    """Native Datalog ↔ SecPAL (and optional engine-shadow) parity receipt.

    Interface: ``RuleParityReceipt@2``.
    """

    datalog_outcome: DecisionOutcome | str | None
    secpal_outcome: DecisionOutcome | str | None
    native_agreed: bool
    shadow_engine: EngineKind | str = EngineKind.REFERENCE
    shadow_outcome: DecisionOutcome | str | None = None
    shadow_agreed: bool | None = None
    shadow_invoked: bool = False
    diagnostics: tuple[str, ...] = ()
    schema_version: str = RULE_PARITY_RECEIPT_SCHEMA

    interface: ClassVar[str] = RULE_PARITY_RECEIPT_V2_INTERFACE

    def __post_init__(self) -> None:
        if self.datalog_outcome is not None:
            object.__setattr__(
                self,
                "datalog_outcome",
                _enum(self.datalog_outcome, DecisionOutcome, "datalog_outcome"),
            )
        if self.secpal_outcome is not None:
            object.__setattr__(
                self,
                "secpal_outcome",
                _enum(self.secpal_outcome, DecisionOutcome, "secpal_outcome"),
            )
        if not isinstance(self.native_agreed, bool):
            raise RuleExecutionError("native_agreed must be a boolean")
        object.__setattr__(
            self,
            "shadow_engine",
            _enum(self.shadow_engine, EngineKind, "shadow_engine"),
        )
        if self.shadow_outcome is not None:
            object.__setattr__(
                self,
                "shadow_outcome",
                _enum(self.shadow_outcome, DecisionOutcome, "shadow_outcome"),
            )
        if self.shadow_agreed is not None and not isinstance(self.shadow_agreed, bool):
            raise RuleExecutionError("shadow_agreed must be a boolean or None")
        if not isinstance(self.shadow_invoked, bool):
            raise RuleExecutionError("shadow_invoked must be a boolean")
        object.__setattr__(
            self,
            "diagnostics",
            bound_diagnostics(self.diagnostics)[:_MAX_DIAGNOSTICS],
        )
        if self.schema_version != RULE_PARITY_RECEIPT_SCHEMA:
            raise RuleExecutionError(
                f"unsupported parity receipt schema: {self.schema_version!r}"
            )

    @property
    def parity_ok(self) -> bool:
        if not self.native_agreed:
            return False
        if self.shadow_invoked and self.shadow_agreed is False:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "datalog_outcome": (
                None
                if self.datalog_outcome is None
                else (
                    self.datalog_outcome.value
                    if isinstance(self.datalog_outcome, DecisionOutcome)
                    else self.datalog_outcome
                )
            ),
            "diagnostics": list(self.diagnostics),
            "interface": self.interface,
            "native_agreed": self.native_agreed,
            "parity_ok": self.parity_ok,
            "schema_version": self.schema_version,
            "secpal_outcome": (
                None
                if self.secpal_outcome is None
                else (
                    self.secpal_outcome.value
                    if isinstance(self.secpal_outcome, DecisionOutcome)
                    else self.secpal_outcome
                )
            ),
            "shadow_agreed": self.shadow_agreed,
            "shadow_engine": (
                self.shadow_engine.value
                if isinstance(self.shadow_engine, EngineKind)
                else self.shadow_engine
            ),
            "shadow_invoked": self.shadow_invoked,
            "shadow_outcome": (
                None
                if self.shadow_outcome is None
                else (
                    self.shadow_outcome.value
                    if isinstance(self.shadow_outcome, DecisionOutcome)
                    else self.shadow_outcome
                )
            ),
        }


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleExecutionRequestV2:
    """Typed SecPAL / Datalog authorization execution request.

    Interface: ``RuleExecutionRequest@2``.

    Mock and fallback payloads may be recorded for audit but **never** admit
    policy authority.
    """

    request_id: str
    provider: RuleProviderKind | str
    document: AuthorizationIR | Mapping[str, Any]
    query: DecisionQuery | Mapping[str, Any] | str | None = None
    world: WorldSemantics | str = WorldSemantics.CLOSED_WORLD
    mode: RuleExecutionMode | str = RuleExecutionMode.NATIVE_REFERENCE
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    bounds: ExecutionBounds | None = None
    use_external_shadow: bool = False
    mock_output: Mapping[str, Any] | None = None
    fallback_output: Mapping[str, Any] | None = None
    available: bool = True
    confidence: float = 0.0
    fluent_text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = RULE_EXECUTION_REQUEST_SCHEMA

    interface: ClassVar[str] = RULE_EXECUTION_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_rule_provider(self.provider)
        )
        if isinstance(self.document, AuthorizationIR):
            document = self.document
        elif isinstance(self.document, Mapping):
            try:
                document = AuthorizationIR.from_dict(self.document)
            except (AuthorizationValidationError, TypeError, ValueError) as error:
                raise RuleExecutionError(
                    f"invalid authorization document: {error}"
                ) from error
        else:
            raise RuleExecutionError("document must be AuthorizationIR or mapping")
        object.__setattr__(self, "document", document)

        query = self._resolve_query(document, self.query)
        object.__setattr__(self, "query", query)

        object.__setattr__(
            self, "world", _enum(self.world, WorldSemantics, "world")
        )
        object.__setattr__(
            self, "mode", _enum(self.mode, RuleExecutionMode, "mode")
        )
        # Merge document/query source refs with explicit request refs.
        explicit = _source_ref_ids(self.source_ref_ids) if self.source_ref_ids else ()
        merged = tuple(
            dict.fromkeys(
                [source.ref_id for source in document.sources]
                + list(query.source_ref_ids)
                + list(explicit)
            )
        )
        object.__setattr__(self, "source_ref_ids", merged)

        if self.bounds is None:
            object.__setattr__(
                self,
                "bounds",
                ExecutionBounds(timeout_ms=1_000, max_steps=1_000),
            )
        elif not isinstance(self.bounds, ExecutionBounds):
            raise RuleExecutionError("bounds must be ExecutionBounds")

        if not isinstance(self.use_external_shadow, bool):
            raise RuleExecutionError("use_external_shadow must be a boolean")
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise RuleExecutionError("confidence must be numeric")
        conf = float(self.confidence)
        if conf != conf or conf < 0.0 or conf > 1.0:
            raise RuleExecutionError("confidence must be finite in [0, 1]")
        object.__setattr__(self, "confidence", conf)
        object.__setattr__(
            self,
            "fluent_text",
            _text(self.fluent_text, "fluent_text", maximum=8_192, allow_empty=True),
        )

        if self.mock_output is None:
            object.__setattr__(self, "mock_output", None)
        else:
            mock = _require_mapping(self.mock_output, "mock_output")
            object.__setattr__(
                self, "mock_output", dict(_freeze_mapping(mock, "mock_output"))
            )
        if self.fallback_output is None:
            object.__setattr__(self, "fallback_output", None)
        else:
            fallback = _require_mapping(self.fallback_output, "fallback_output")
            object.__setattr__(
                self,
                "fallback_output",
                dict(_freeze_mapping(fallback, "fallback_output")),
            )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        serialized = canonical_json_bytes(dict(metadata))
        if len(serialized) > _MAX_METADATA_BYTES:
            raise RuleExecutionError("metadata exceeds hard byte limit")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != RULE_EXECUTION_REQUEST_SCHEMA:
            raise RuleExecutionError(
                f"unsupported RuleExecutionRequest@2 schema: "
                f"{self.schema_version!r}"
            )

    @staticmethod
    def _resolve_query(
        document: AuthorizationIR,
        query: DecisionQuery | Mapping[str, Any] | str | None,
    ) -> DecisionQuery:
        if isinstance(query, DecisionQuery):
            return query
        if isinstance(query, Mapping):
            return DecisionQuery.from_dict(query)
        if isinstance(query, str) and query:
            for item in document.queries:
                if item.query_id == query:
                    return item
            raise RuleExecutionError(f"unknown query_id {query!r}")
        if len(document.queries) == 1:
            return document.queries[0]
        if not document.queries:
            raise RuleExecutionError("document has no decision queries")
        raise RuleExecutionError(
            "query is required when the document defines multiple queries"
        )

    @property
    def has_mock_output(self) -> bool:
        return self.mock_output is not None

    @property
    def has_fallback_output(self) -> bool:
        return self.fallback_output is not None

    @property
    def policy_digest(self) -> str:
        return self.document.sha256  # type: ignore[union-attr]

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "bounds": self.bounds.to_dict() if self.bounds else None,  # type: ignore[union-attr]
            "confidence": self.confidence,
            "document_digest": self.policy_digest,
            "document_id": self.document.document_id,  # type: ignore[union-attr]
            "fallback_output": (
                None if self.fallback_output is None else dict(self.fallback_output)
            ),
            "fluent_text": self.fluent_text,
            "has_fallback_output": self.has_fallback_output,
            "has_mock_output": self.has_mock_output,
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output": (
                None if self.mock_output is None else dict(self.mock_output)
            ),
            "mode": (
                self.mode.value
                if isinstance(self.mode, RuleExecutionMode)
                else self.mode
            ),
            "provider": (
                self.provider.value
                if isinstance(self.provider, RuleProviderKind)
                else self.provider
            ),
            "query_id": self.query.query_id,  # type: ignore[union-attr]
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "use_external_shadow": self.use_external_shadow,
            "world": (
                self.world.value
                if isinstance(self.world, WorldSemantics)
                else self.world
            ),
        }


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RuleProviderEvidenceV2:
    """Pinned SecPAL / Datalog authorization evidence.

    Interface: ``RuleProviderEvidence@2``.

    Authorization answers **must** bind policy, query, provenance, and
    semantics.  Policy authority is established only by native reference
    evaluation (or agreed native parity).  Mock / fallback / availability /
    confidence / fluent text never establish policy, proof, satisfiability,
    or theorem authority.
    """

    evidence_id: str
    request_id: str
    request_digest: str
    provider: RuleProviderKind | str
    disposition: RuleDisposition | str
    outcome: DecisionOutcome | str | None
    mode: RuleExecutionMode | str
    policy_digest: str
    query_id: str
    provenance: RuleProvenanceBindingV2 | Mapping[str, Any]
    semantics: RuleSemanticsBindingV2 | Mapping[str, Any]
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    parity: RuleParityReceiptV2 | Mapping[str, Any] | None = None
    result_authority: ResultAuthority | str = ResultAuthority.AUTHORIZATION
    result_status: ResultStatus | str = ResultStatus.UNKNOWN
    role: ToolRole | str = ToolRole.AUTHORITY
    authority_ceiling: ToolchainAuthorityCeiling | str = (
        ToolchainAuthorityCeiling.AUTHORIZATION
    )
    authorization_authority: AuthorizationEvidenceAuthority | str = (
        AuthorizationEvidenceAuthority.AUTHORIZATION
    )
    generated_code_correctness: GeneratedCodeCorrectness | str = (
        GeneratedCodeCorrectness.NOT_ESTABLISHED
    )
    policy_authority_established: bool = False
    mock_output_present: bool = False
    fallback_output_present: bool = False
    available: bool = False
    confidence: float = 0.0
    fluent_text_present: bool = False
    bounds_exhausted: bool = False
    decision: PolicyDecision | Mapping[str, Any] | None = None
    explanation: DecisionExplanation | Mapping[str, Any] | None = None
    evaluation_receipt: EvaluationReceipt | Mapping[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = RULE_PROVIDER_EVIDENCE_SCHEMA

    interface: ClassVar[str] = RULE_PROVIDER_EVIDENCE_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _record_id(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "request_digest",
            _sha256_hex(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self, "provider", normalize_rule_provider(self.provider)
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, RuleDisposition, "disposition"),
        )
        if self.outcome is not None:
            object.__setattr__(
                self, "outcome", _enum(self.outcome, DecisionOutcome, "outcome")
            )
        object.__setattr__(
            self, "mode", _enum(self.mode, RuleExecutionMode, "mode")
        )
        object.__setattr__(
            self, "policy_digest", _sha256_hex(self.policy_digest, "policy_digest")
        )
        object.__setattr__(self, "query_id", _record_id(self.query_id, "query_id"))

        if isinstance(self.provenance, RuleProvenanceBindingV2):
            provenance = self.provenance
        else:
            provenance = RuleProvenanceBindingV2(
                **{
                    key: value
                    for key, value in dict(
                        _require_mapping(self.provenance, "provenance")
                    ).items()
                    if key
                    in {
                        "policy_digest",
                        "query_id",
                        "source_ref_ids",
                        "bound_rule_ids",
                        "bound_fact_ids",
                        "bound_delegation_ids",
                        "bound_trust_root_ids",
                        "explanation_id",
                        "schema_version",
                    }
                }
            )
        object.__setattr__(self, "provenance", provenance)
        if provenance.policy_digest != self.policy_digest:
            raise RuleExecutionError(
                "provenance.policy_digest must match evidence.policy_digest"
            )
        if provenance.query_id != self.query_id:
            raise RuleExecutionError(
                "provenance.query_id must match evidence.query_id"
            )

        if isinstance(self.semantics, RuleSemanticsBindingV2):
            semantics = self.semantics
        else:
            semantics = RuleSemanticsBindingV2(
                **{
                    key: value
                    for key, value in dict(
                        _require_mapping(self.semantics, "semantics")
                    ).items()
                    if key
                    in {
                        "world",
                        "max_delegation_depth",
                        "max_derivation_depth",
                        "max_stratum",
                        "strata_used",
                        "precedence",
                        "closed_under_negation",
                        "schema_version",
                    }
                }
            )
        object.__setattr__(self, "semantics", semantics)

        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )

        if self.parity is None:
            object.__setattr__(self, "parity", None)
        elif isinstance(self.parity, RuleParityReceiptV2):
            object.__setattr__(self, "parity", self.parity)
        else:
            object.__setattr__(
                self,
                "parity",
                RuleParityReceiptV2(
                    **{
                        key: value
                        for key, value in dict(
                            _require_mapping(self.parity, "parity")
                        ).items()
                        if key
                        in {
                            "datalog_outcome",
                            "secpal_outcome",
                            "native_agreed",
                            "shadow_engine",
                            "shadow_outcome",
                            "shadow_agreed",
                            "shadow_invoked",
                            "diagnostics",
                            "schema_version",
                        }
                    }
                ),
            )

        result_authority = (
            self.result_authority
            if isinstance(self.result_authority, ResultAuthority)
            else ResultAuthority(str(self.result_authority))
        )
        if result_authority is not ResultAuthority.AUTHORIZATION:
            raise RuleAuthorityError(
                "RuleProviderEvidence@2 result_authority must be authorization; "
                f"got {result_authority!r}"
            )
        object.__setattr__(self, "result_authority", ResultAuthority.AUTHORIZATION)

        result_status = (
            self.result_status
            if isinstance(self.result_status, ResultStatus)
            else ResultStatus(str(self.result_status))
        )
        # Authorization results may never claim theorem statuses.
        if result_status in {ResultStatus.PROVED, ResultStatus.DISPROVED}:
            raise RuleAuthorityError(
                "RuleProviderEvidence@2 cannot claim theorem result statuses"
            )
        object.__setattr__(self, "result_status", result_status)

        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role not in {ToolRole.AUTHORITY, ToolRole.SHADOW}:
            raise RuleAuthorityError(
                f"RuleProviderEvidence@2 role must be authority or shadow; got {role!r}"
            )
        object.__setattr__(self, "role", role)

        ceiling = (
            self.authority_ceiling
            if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
            else ToolchainAuthorityCeiling(str(self.authority_ceiling))
        )
        if ceiling is not ToolchainAuthorityCeiling.AUTHORIZATION:
            raise RuleAuthorityError(
                "RuleProviderEvidence@2 authority_ceiling must be authorization"
            )
        object.__setattr__(self, "authority_ceiling", ceiling)

        auth_auth = (
            self.authorization_authority
            if isinstance(
                self.authorization_authority, AuthorizationEvidenceAuthority
            )
            else AuthorizationEvidenceAuthority(str(self.authorization_authority))
        )
        if auth_auth is not AuthorizationEvidenceAuthority.AUTHORIZATION:
            raise RuleAuthorityError(
                "authorization_authority cannot exceed authorization"
            )
        object.__setattr__(self, "authorization_authority", auth_auth)

        correctness = (
            self.generated_code_correctness
            if isinstance(
                self.generated_code_correctness, GeneratedCodeCorrectness
            )
            else GeneratedCodeCorrectness(str(self.generated_code_correctness))
        )
        if correctness is not GeneratedCodeCorrectness.NOT_ESTABLISHED:
            raise RuleAuthorityError(
                "authorization evidence never establishes generated-code correctness"
            )
        object.__setattr__(self, "generated_code_correctness", correctness)

        for flag_name in (
            "policy_authority_established",
            "mock_output_present",
            "fallback_output_present",
            "available",
            "fluent_text_present",
            "bounds_exhausted",
        ):
            object.__setattr__(
                self,
                flag_name,
                _optional_bool(getattr(self, flag_name), flag_name),
            )

        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise RuleExecutionError("confidence must be numeric")
        conf = float(self.confidence)
        if conf != conf or conf < 0.0 or conf > 1.0:
            raise RuleExecutionError("confidence must be finite in [0, 1]")
        object.__setattr__(self, "confidence", conf)

        # Fail closed: mock / fallback / non-native modes never establish policy.
        mode = self.mode  # type: ignore[assignment]
        if (
            self.mock_output_present
            or self.fallback_output_present
            or mode
            in {RuleExecutionMode.MOCK, RuleExecutionMode.FALLBACK}
        ):
            if self.policy_authority_established:
                raise RuleAuthorityError(
                    "fallback or mock output cannot establish policy authority"
                )
            object.__setattr__(self, "policy_authority_established", False)
        if mode is RuleExecutionMode.ENGINE_SHADOW and self.policy_authority_established:
            raise RuleAuthorityError(
                "engine shadow alone cannot establish policy authority"
            )

        if self.decision is not None and not isinstance(
            self.decision, (PolicyDecision, Mapping)
        ):
            raise RuleExecutionError("decision must be PolicyDecision or mapping")
        if self.explanation is not None and not isinstance(
            self.explanation, (DecisionExplanation, Mapping)
        ):
            raise RuleExecutionError(
                "explanation must be DecisionExplanation or mapping"
            )

        object.__setattr__(
            self, "diagnostics", bound_diagnostics(self.diagnostics)[:_MAX_DIAGNOSTICS]
        )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != RULE_PROVIDER_EVIDENCE_SCHEMA:
            raise RuleExecutionError(
                f"unsupported RuleProviderEvidence@2 schema: "
                f"{self.schema_version!r}"
            )

        if not self.content_digest:
            object.__setattr__(
                self,
                "content_digest",
                _digest_of(
                    {
                        "disposition": (
                            self.disposition.value
                            if isinstance(self.disposition, RuleDisposition)
                            else self.disposition
                        ),
                        "mode": (
                            self.mode.value
                            if isinstance(self.mode, RuleExecutionMode)
                            else self.mode
                        ),
                        "outcome": (
                            None
                            if self.outcome is None
                            else (
                                self.outcome.value
                                if isinstance(self.outcome, DecisionOutcome)
                                else self.outcome
                            )
                        ),
                        "policy_digest": self.policy_digest,
                        "provider": (
                            self.provider.value
                            if isinstance(self.provider, RuleProviderKind)
                            else self.provider
                        ),
                        "provenance": self.provenance.to_dict(),  # type: ignore[union-attr]
                        "query_id": self.query_id,
                        "request_digest": self.request_digest,
                        "request_id": self.request_id,
                        "semantics": self.semantics.to_dict(),  # type: ignore[union-attr]
                    }
                ),
            )
        else:
            object.__setattr__(
                self,
                "content_digest",
                _sha256_hex(self.content_digest, "content_digest"),
            )

    # --- authority queries (fail closed) -----------------------------------

    @property
    def is_theorem_authority(self) -> bool:
        return False

    @property
    def is_proved(self) -> bool:
        return False

    @property
    def proof_established(self) -> bool:
        return False

    @property
    def satisfiability_established(self) -> bool:
        return False

    @property
    def theorem_established(self) -> bool:
        return False

    @property
    def policy_established(self) -> bool:
        """True only when native evaluation bound policy/query/provenance/semantics."""

        return bool(self.policy_authority_established)

    def claim_established(self, claim: RuleClaimKind | str) -> bool:
        kind = (
            claim
            if isinstance(claim, RuleClaimKind)
            else RuleClaimKind(str(claim))
        )
        if kind is RuleClaimKind.POLICY:
            return self.policy_established
        return False

    def non_authoritative_claim(self, claim: RuleClaimKind | str) -> bool:
        """Whether mock / fallback / availability establish *claim* (always False)."""

        return non_authoritative_signal_establishes(
            claim,
            mock_output={} if self.mock_output_present else None,
            fallback_output={} if self.fallback_output_present else None,
            available=self.available,
            confidence=self.confidence,
            fluent_text="present" if self.fluent_text_present else None,
        )

    def bindings_complete(self) -> bool:
        """Whether policy, query, provenance, and semantics are all bound."""

        return bool(
            self.policy_digest
            and self.query_id
            and isinstance(self.provenance, RuleProvenanceBindingV2)
            and self.provenance.policy_digest == self.policy_digest
            and self.provenance.query_id == self.query_id
            and isinstance(self.semantics, RuleSemanticsBindingV2)
        )

    def to_dict(self) -> dict[str, Any]:
        decision_payload: Any = None
        if isinstance(self.decision, PolicyDecision):
            decision_payload = self.decision.to_dict()
        elif isinstance(self.decision, Mapping):
            decision_payload = dict(self.decision)
        explanation_payload: Any = None
        if isinstance(self.explanation, DecisionExplanation):
            explanation_payload = self.explanation.to_dict()
        elif isinstance(self.explanation, Mapping):
            explanation_payload = dict(self.explanation)
        receipt_payload: Any = None
        if isinstance(self.evaluation_receipt, EvaluationReceipt):
            receipt_payload = self.evaluation_receipt.to_dict()
        elif isinstance(self.evaluation_receipt, Mapping):
            receipt_payload = dict(self.evaluation_receipt)
        return {
            "authorization_authority": (
                self.authorization_authority.value
                if isinstance(
                    self.authorization_authority, AuthorizationEvidenceAuthority
                )
                else self.authorization_authority
            ),
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
                else self.authority_ceiling
            ),
            "available": self.available,
            "bindings_complete": self.bindings_complete(),
            "bounds_exhausted": self.bounds_exhausted,
            "claim_policy": self.policy_established,
            "claim_proof": False,
            "claim_satisfiability": False,
            "claim_theorem": False,
            "confidence": self.confidence,
            "content_digest": self.content_digest,
            "decision": decision_payload,
            "diagnostics": list(self.diagnostics),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, RuleDisposition)
                else self.disposition
            ),
            "evaluation_receipt": receipt_payload,
            "evidence_id": self.evidence_id,
            "explanation": explanation_payload,
            "fallback_output_present": self.fallback_output_present,
            "fluent_text_present": self.fluent_text_present,
            "generated_code_correctness": (
                self.generated_code_correctness.value
                if isinstance(
                    self.generated_code_correctness, GeneratedCodeCorrectness
                )
                else self.generated_code_correctness
            ),
            "interface": self.interface,
            "is_proved": False,
            "is_theorem_authority": False,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output_present": self.mock_output_present,
            "mode": (
                self.mode.value
                if isinstance(self.mode, RuleExecutionMode)
                else self.mode
            ),
            "outcome": (
                None
                if self.outcome is None
                else (
                    self.outcome.value
                    if isinstance(self.outcome, DecisionOutcome)
                    else self.outcome
                )
            ),
            "parity": None if self.parity is None else self.parity.to_dict(),  # type: ignore[union-attr]
            "policy_authority_established": self.policy_authority_established,
            "policy_digest": self.policy_digest,
            "policy_established": self.policy_established,
            "proof_established": False,
            "provenance": self.provenance.to_dict(),  # type: ignore[union-attr]
            "provider": (
                self.provider.value
                if isinstance(self.provider, RuleProviderKind)
                else self.provider
            ),
            "provider_identity": provider_logic_identity(
                self.provider  # type: ignore[arg-type]
            ).to_dict(),
            "query_id": self.query_id,
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "result_authority": ResultAuthority.AUTHORIZATION.value,
            "result_status": (
                self.result_status.value
                if isinstance(self.result_status, ResultStatus)
                else self.result_status
            ),
            "role": (
                self.role.value if isinstance(self.role, ToolRole) else self.role
            ),
            "satisfiability_established": False,
            "schema_version": self.schema_version,
            "semantics": self.semantics.to_dict(),  # type: ignore[union-attr]
            "source_ref_ids": list(self.source_ref_ids),
            "theorem_established": False,
        }


@dataclass(frozen=True, slots=True)
class RuleExecutionResultV2:
    """Typed result of one SecPAL / Datalog authorization execution.

    Interface: ``RuleExecutionResult@2``.
    """

    request: RuleExecutionRequestV2
    evidence: RuleProviderEvidenceV2
    datalog_result: AuthorizationResult | None = None
    secpal_result: AuthorizationResult | None = None
    rendered_datalog: str = ""
    rendered_secpal: str = ""
    schema_version: str = RULE_EXECUTION_RESULT_SCHEMA

    interface: ClassVar[str] = RULE_EXECUTION_RESULT_V2_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.request, RuleExecutionRequestV2):
            raise RuleExecutionError(
                "request must be a RuleExecutionRequestV2"
            )
        if not isinstance(self.evidence, RuleProviderEvidenceV2):
            raise RuleExecutionError(
                "evidence must be a RuleProviderEvidenceV2"
            )
        if self.schema_version != RULE_EXECUTION_RESULT_SCHEMA:
            raise RuleExecutionError(
                f"unsupported RuleExecutionResult@2 schema: "
                f"{self.schema_version!r}"
            )
        if not isinstance(self.rendered_datalog, str):
            raise RuleExecutionError("rendered_datalog must be a string")
        if not isinstance(self.rendered_secpal, str):
            raise RuleExecutionError("rendered_secpal must be a string")

    @property
    def disposition(self) -> RuleDisposition:
        return self.evidence.disposition  # type: ignore[return-value]

    @property
    def policy_established(self) -> bool:
        return self.evidence.policy_established

    @property
    def is_proved(self) -> bool:
        return False

    @property
    def is_theorem_authority(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, RuleDisposition)
                else self.disposition
            ),
            "evidence": self.evidence.to_dict(),
            "interface": self.interface,
            "is_proved": False,
            "is_theorem_authority": False,
            "policy_established": self.policy_established,
            "rendered_datalog_digest": (
                content_sha256(self.rendered_datalog.encode("utf-8"))
                if self.rendered_datalog
                else ""
            ),
            "rendered_secpal_digest": (
                content_sha256(self.rendered_secpal.encode("utf-8"))
                if self.rendered_secpal
                else ""
            ),
            "request": self.request.to_dict(),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _backend_request_for(
    *,
    request_id: str,
    document: AuthorizationIR,
    query: DecisionQuery,
    provider: RuleProviderKind,
    bounds: ExecutionBounds,
    encoding: str,
) -> BackendRequest:
    backend_id = provider_backend_id(
        provider if provider is not RuleProviderKind.PARITY else RuleProviderKind.DATALOG
    )
    family = (
        "secpal"
        if provider is RuleProviderKind.SECPAL
        else "authorization"
    )
    if provider is RuleProviderKind.SECPAL:
        backend_id = "secpal-authorization"
        encoding = encoding or "secpal"
    elif provider is RuleProviderKind.DATALOG:
        backend_id = "datalog-authorization"
        encoding = encoding or "datalog"
    return BackendRequest(
        request_id=f"request:rule-exec:{request_id}",
        claim_id=f"claim:rule-exec:{request_id}",
        declaration_id=f"declaration:rule-exec:{request_id}",
        claim_digest=document.sha256,
        obligation_id=f"obligation:rule-exec:{request_id}",
        obligation_digest=stable_digest(
            {
                "document": document.sha256,
                "query": query.query_id,
            }
        ),
        assumption_ids=("assumption:reviewed-authorization-policy",),
        logic_family=family,
        query_kind=QueryKind.POLICY_APPROVAL,
        bounds=bounds,
        payload=FrozenMap(
            {
                "encoding": encoding,
                "authorization_ir": document.to_dict(),
                "query_id": query.query_id,
            }
        ),
        requested_backend_id=backend_id,
    )


def _apply_world_semantics(
    outcome: DecisionOutcome,
    world: WorldSemantics,
    *,
    has_explicit_deny: bool,
) -> DecisionOutcome:
    """Overlay open/closed-world reading on the reference outcome.

    Closed world (default authorization reading): reference outcome stands.

    Open world: absence of both allow and deny evidence remains UNKNOWN;
    DENY is admitted only when explicit deny evidence was derived.  The
    reference evaluator already returns UNKNOWN for pure absence; this
    overlay additionally refuses to re-label UNKNOWN as DENY under open
    world (fail closed for fabricated denials).
    """

    if world is WorldSemantics.CLOSED_WORLD:
        return outcome
    # Open world: never invent deny from silence.
    if outcome is DecisionOutcome.DENY and not has_explicit_deny:
        return DecisionOutcome.UNKNOWN
    return outcome


def _has_explicit_deny(explanation: DecisionExplanation | None) -> bool:
    if explanation is None:
        return False
    for step in explanation.steps:
        statement = (step.statement or "").casefold()
        if "deny" in statement:
            return True
        attributes = step.attributes.to_dict() if hasattr(step.attributes, "to_dict") else {}
        effect = str(attributes.get("effect", "")).casefold()
        if effect == "deny":
            return True
    # Decision outcome DENY with rule steps counts as explicit deny evidence.
    if explanation.outcome is DecisionOutcome.DENY:
        return any(
            step.kind is ExplanationStepKind.RULE for step in explanation.steps
        )
    return False


class RuleExecutionEngineV2:
    """Execute SecPAL / Datalog authorization with parity and fail-closed authority.

    Interface owner: ``RuleProviderEvidence@2``.
    """

    INTERFACE: ClassVar[str] = RULE_PROVIDER_EVIDENCE_V2_INTERFACE
    interface: ClassVar[str] = RULE_PROVIDER_EVIDENCE_V2_INTERFACE
    VERSION: ClassVar[str] = RULE_EXECUTION_V2_MODULE_VERSION
    TASK_ID: ClassVar[str] = RULE_EXECUTION_V2_TASK_ID
    GOAL_ID: ClassVar[str] = RULE_EXECUTION_V2_GOAL_ID

    def __init__(
        self,
        *,
        datalog_backend: DatalogAuthorizationBackend | None = None,
        secpal_backend: SecPALAuthorizationBackend | None = None,
        runner: BoundedToolRunner | None = None,
    ) -> None:
        self._runner = runner
        self._datalog = datalog_backend or DatalogAuthorizationBackend(
            runner=runner,
            use_external_engine=False,
        )
        self._secpal = secpal_backend or SecPALAuthorizationBackend(
            runner=runner,
            use_external_engine=False,
        )

    def execute(
        self,
        request: RuleExecutionRequestV2 | Mapping[str, Any],
    ) -> RuleExecutionResultV2:
        """Execute one typed authorization request with authority fail-closed."""

        req = (
            request
            if isinstance(request, RuleExecutionRequestV2)
            else RuleExecutionRequestV2(
                **{
                    key: value
                    for key, value in dict(
                        _require_mapping(request, "request")
                    ).items()
                    if key
                    in {
                        "request_id",
                        "provider",
                        "document",
                        "query",
                        "world",
                        "mode",
                        "source_ref_ids",
                        "bounds",
                        "use_external_shadow",
                        "mock_output",
                        "fallback_output",
                        "available",
                        "confidence",
                        "fluent_text",
                        "metadata",
                        "schema_version",
                    }
                }
            )
        )
        request_digest = _digest_of(req.to_dict())
        document: AuthorizationIR = req.document  # type: ignore[assignment]
        query: DecisionQuery = req.query  # type: ignore[assignment]
        world: WorldSemantics = req.world  # type: ignore[assignment]
        provider: RuleProviderKind = req.provider  # type: ignore[assignment]
        semantics = RuleSemanticsBindingV2.from_document(document, world=world)

        # Mock path: never establishes policy authority.
        if req.has_mock_output or req.mode is RuleExecutionMode.MOCK:
            provenance = RuleProvenanceBindingV2(
                policy_digest=document.sha256,
                query_id=query.query_id,
                source_ref_ids=req.source_ref_ids,
            )
            evidence = self._build_evidence(
                req=req,
                request_digest=request_digest,
                disposition=RuleDisposition.MOCK_REJECTED,
                outcome=None,
                mode=RuleExecutionMode.MOCK,
                provenance=provenance,
                semantics=semantics,
                policy_authority_established=False,
                mock_output_present=True,
                fallback_output_present=req.has_fallback_output,
                diagnostics=(
                    "mock_output_cannot_establish_policy",
                    "mock_output_cannot_establish_proof",
                    "mock_output_cannot_establish_satisfiability",
                    "mock_output_cannot_establish_theorem",
                ),
                result_status=ResultStatus.UNKNOWN,
            )
            return RuleExecutionResultV2(request=req, evidence=evidence)

        # Fallback path: never establishes policy authority.
        if req.has_fallback_output or req.mode is RuleExecutionMode.FALLBACK:
            provenance = RuleProvenanceBindingV2(
                policy_digest=document.sha256,
                query_id=query.query_id,
                source_ref_ids=req.source_ref_ids,
            )
            evidence = self._build_evidence(
                req=req,
                request_digest=request_digest,
                disposition=RuleDisposition.FALLBACK_REJECTED,
                outcome=None,
                mode=RuleExecutionMode.FALLBACK,
                provenance=provenance,
                semantics=semantics,
                policy_authority_established=False,
                mock_output_present=False,
                fallback_output_present=True,
                diagnostics=(
                    "fallback_output_cannot_establish_policy",
                    "fallback_output_cannot_establish_proof",
                ),
                result_status=ResultStatus.UNKNOWN,
            )
            return RuleExecutionResultV2(request=req, evidence=evidence)

        if provider is RuleProviderKind.PARITY:
            return self._execute_parity(req, request_digest=request_digest)

        return self._execute_single(req, request_digest=request_digest)

    def execute_fixture(
        self,
        fixture: AuthorizationFixture,
        *,
        request_id: str | None = None,
        provider: RuleProviderKind | str = RuleProviderKind.PARITY,
        world: WorldSemantics | str = WorldSemantics.CLOSED_WORLD,
    ) -> RuleExecutionResultV2:
        """Execute a reviewed authorization fixture through the v2 path."""

        if not isinstance(fixture, AuthorizationFixture):
            raise RuleExecutionError("fixture must be an AuthorizationFixture")
        req = RuleExecutionRequestV2(
            request_id=request_id or f"req:fixture:{fixture.fixture_id}",
            provider=provider,
            document=fixture.document,
            query=fixture.query,
            world=world,
            mode=RuleExecutionMode.NATIVE_REFERENCE,
        )
        return self.execute(req)

    def execute_default_fixtures(
        self,
        *,
        provider: RuleProviderKind | str = RuleProviderKind.PARITY,
    ) -> tuple[RuleExecutionResultV2, ...]:
        """Run the default authorization fixture set under parity."""

        return tuple(
            self.execute_fixture(fixture, provider=provider)
            for fixture in DEFAULT_AUTHORIZATION_FIXTURES
        )

    # --- internal paths ----------------------------------------------------

    def _execute_single(
        self,
        req: RuleExecutionRequestV2,
        *,
        request_digest: str,
    ) -> RuleExecutionResultV2:
        document: AuthorizationIR = req.document  # type: ignore[assignment]
        query: DecisionQuery = req.query  # type: ignore[assignment]
        provider: RuleProviderKind = req.provider  # type: ignore[assignment]
        world: WorldSemantics = req.world  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        semantics = RuleSemanticsBindingV2.from_document(document, world=world)

        backend = (
            self._secpal
            if provider is RuleProviderKind.SECPAL
            else self._datalog
        )
        encoding = "secpal" if provider is RuleProviderKind.SECPAL else "datalog"
        backend_request = _backend_request_for(
            request_id=req.request_id,
            document=document,
            query=query,
            provider=provider,
            bounds=bounds,
            encoding=encoding,
        )

        # Native reference always evaluates; shadow is optional and never sole authority.
        native = backend.run(backend_request)
        shadow_bundle: AuthorizationBackendOutcome | None = None
        if req.use_external_shadow:
            shadow_backend = type(backend)(
                runner=self._runner or backend._runner,  # type: ignore[attr-defined]
                use_external_engine=True,
            )
            try:
                shadow_bundle = shadow_backend.run(backend_request)
            except AuthorizationBackendError:
                # Shadow failure is diagnostic only; native still answers.
                shadow_bundle = None

        return self._finalize_native(
            req,
            request_digest=request_digest,
            native=native,
            shadow=shadow_bundle,
            world=world,
            semantics=semantics,
        )

    def _execute_parity(
        self,
        req: RuleExecutionRequestV2,
        *,
        request_digest: str,
    ) -> RuleExecutionResultV2:
        document: AuthorizationIR = req.document  # type: ignore[assignment]
        query: DecisionQuery = req.query  # type: ignore[assignment]
        world: WorldSemantics = req.world  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        semantics = RuleSemanticsBindingV2.from_document(document, world=world)

        datalog_req = _backend_request_for(
            request_id=f"{req.request_id}:datalog",
            document=document,
            query=query,
            provider=RuleProviderKind.DATALOG,
            bounds=bounds,
            encoding="datalog",
        )
        secpal_req = _backend_request_for(
            request_id=f"{req.request_id}:secpal",
            document=document,
            query=query,
            provider=RuleProviderKind.SECPAL,
            bounds=bounds,
            encoding="secpal",
        )
        datalog_out = self._datalog.run(datalog_req)
        secpal_out = self._secpal.run(secpal_req)

        datalog_outcome = datalog_out.receipt.outcome  # type: ignore[union-attr]
        secpal_outcome = secpal_out.receipt.outcome  # type: ignore[union-attr]
        native_agreed = datalog_outcome is secpal_outcome

        # Prefer datalog native as primary; both must agree for policy authority.
        primary = datalog_out
        decision = primary.receipt.decision
        explanation = primary.receipt.explanation
        explicit_deny = _has_explicit_deny(explanation)
        adjusted = _apply_world_semantics(
            datalog_outcome,  # type: ignore[arg-type]
            world,
            has_explicit_deny=explicit_deny,
        )
        if adjusted is not datalog_outcome:
            # World overlay changed outcome — re-check parity under overlay.
            secpal_adjusted = _apply_world_semantics(
                secpal_outcome,  # type: ignore[arg-type]
                world,
                has_explicit_deny=_has_explicit_deny(secpal_out.receipt.explanation),
            )
            native_agreed = adjusted is secpal_adjusted
            datalog_outcome = adjusted
            secpal_outcome = secpal_adjusted

        shadow_engine = EngineKind.REFERENCE
        shadow_outcome: DecisionOutcome | None = None
        shadow_agreed: bool | None = None
        shadow_invoked = False
        parity_diags: list[str] = []

        if req.use_external_shadow:
            shadow_invoked = True
            shadow_backend = DatalogAuthorizationBackend(
                runner=self._runner or self._datalog._runner,  # type: ignore[attr-defined]
                use_external_engine=True,
            )
            try:
                shadow_out = shadow_backend.run(datalog_req)
                shadow_engine = shadow_out.receipt.engine  # type: ignore[assignment]
                shadow_outcome = shadow_out.receipt.engine_outcome  # type: ignore[assignment]
                if shadow_outcome is None:
                    shadow_agreed = False
                    parity_diags.append("shadow_produced_no_outcome")
                else:
                    shadow_agreed = shadow_outcome is datalog_outcome
                    if not shadow_agreed:
                        parity_diags.append(
                            f"shadow_disagreement:native={datalog_outcome}"
                            f":shadow={shadow_outcome}"
                        )
            except AuthorizationBackendError as error:
                shadow_agreed = False
                parity_diags.append(f"shadow_error:{error}")

        parity = RuleParityReceiptV2(
            datalog_outcome=datalog_outcome,
            secpal_outcome=secpal_outcome,
            native_agreed=native_agreed,
            shadow_engine=shadow_engine,
            shadow_outcome=shadow_outcome,
            shadow_agreed=shadow_agreed,
            shadow_invoked=shadow_invoked,
            diagnostics=tuple(parity_diags),
        )

        provenance = RuleProvenanceBindingV2.from_evaluation(
            document=document, query=query, explanation=explanation
        )
        rendered_datalog = render_datalog_program(document, query)
        rendered_secpal = render_secpal_program(document, query)

        if not native_agreed:
            evidence = self._build_evidence(
                req=req,
                request_digest=request_digest,
                disposition=RuleDisposition.PARITY_DISAGREEMENT,
                outcome=None,
                mode=RuleExecutionMode.NATIVE_REFERENCE,
                provenance=provenance,
                semantics=semantics,
                parity=parity,
                policy_authority_established=False,
                decision=decision,
                explanation=explanation,
                evaluation_receipt=primary.receipt,
                diagnostics=(
                    "datalog_secpal_native_disagreement",
                    f"datalog={datalog_outcome}",
                    f"secpal={secpal_outcome}",
                ),
                result_status=ResultStatus.UNKNOWN,
                bounds_exhausted=primary.receipt.bounds_exhausted,
            )
            return RuleExecutionResultV2(
                request=req,
                evidence=evidence,
                datalog_result=datalog_out.result,
                secpal_result=secpal_out.result,
                rendered_datalog=rendered_datalog,
                rendered_secpal=rendered_secpal,
            )

        if primary.receipt.bounds_exhausted and datalog_outcome is DecisionOutcome.UNKNOWN:
            disposition = RuleDisposition.BOUNDS_EXHAUSTED
            policy_ok = False
            status = ResultStatus.UNKNOWN
        else:
            disposition = _outcome_to_disposition(datalog_outcome)  # type: ignore[arg-type]
            # Policy authority requires complete bindings + native agreement.
            policy_ok = True
            status = outcome_to_result_status(datalog_outcome)  # type: ignore[arg-type]
            # Shadow disagreement quarantines conclusive status but native
            # still holds authorization authority when native paths agreed.
            if shadow_invoked and shadow_agreed is False:
                status = ResultStatus.UNKNOWN
                parity_diags.append("shadow_disagreement_quarantines_conclusive_status")

        evidence = self._build_evidence(
            req=req,
            request_digest=request_digest,
            disposition=disposition,
            outcome=datalog_outcome,  # type: ignore[arg-type]
            mode=RuleExecutionMode.NATIVE_REFERENCE,
            provenance=provenance,
            semantics=semantics,
            parity=parity,
            policy_authority_established=policy_ok,
            decision=decision,
            explanation=explanation,
            evaluation_receipt=primary.receipt,
            diagnostics=tuple(parity_diags),
            result_status=status,
            bounds_exhausted=primary.receipt.bounds_exhausted,
        )
        return RuleExecutionResultV2(
            request=req,
            evidence=evidence,
            datalog_result=datalog_out.result,
            secpal_result=secpal_out.result,
            rendered_datalog=rendered_datalog,
            rendered_secpal=rendered_secpal,
        )

    def _finalize_native(
        self,
        req: RuleExecutionRequestV2,
        *,
        request_digest: str,
        native: AuthorizationBackendOutcome,
        shadow: AuthorizationBackendOutcome | None,
        world: WorldSemantics,
        semantics: RuleSemanticsBindingV2,
    ) -> RuleExecutionResultV2:
        document: AuthorizationIR = req.document  # type: ignore[assignment]
        query: DecisionQuery = req.query  # type: ignore[assignment]
        provider: RuleProviderKind = req.provider  # type: ignore[assignment]

        decision = native.receipt.decision
        explanation = native.receipt.explanation
        outcome = native.receipt.outcome
        explicit_deny = _has_explicit_deny(explanation)
        outcome = _apply_world_semantics(
            outcome,  # type: ignore[arg-type]
            world,
            has_explicit_deny=explicit_deny,
        )

        parity: RuleParityReceiptV2 | None = None
        diagnostics: list[str] = list(native.receipt.diagnostics)
        if shadow is not None:
            shadow_outcome = shadow.receipt.engine_outcome or shadow.receipt.outcome
            shadow_agreed = shadow_outcome is outcome
            parity = RuleParityReceiptV2(
                datalog_outcome=(
                    outcome if provider is RuleProviderKind.DATALOG else None
                ),
                secpal_outcome=(
                    outcome if provider is RuleProviderKind.SECPAL else None
                ),
                native_agreed=True,
                shadow_engine=shadow.receipt.engine,
                shadow_outcome=shadow_outcome,
                shadow_agreed=shadow_agreed,
                shadow_invoked=True,
                diagnostics=()
                if shadow_agreed
                else (
                    f"shadow_disagreement:native={outcome}:shadow={shadow_outcome}",
                ),
            )
            if not shadow_agreed:
                diagnostics.append("shadow_disagreement_quarantines_conclusive_status")

        provenance = RuleProvenanceBindingV2.from_evaluation(
            document=document, query=query, explanation=explanation
        )

        if native.receipt.bounds_exhausted and outcome is DecisionOutcome.UNKNOWN:
            disposition = RuleDisposition.BOUNDS_EXHAUSTED
            policy_ok = False
            status = ResultStatus.UNKNOWN
        else:
            disposition = _outcome_to_disposition(outcome)  # type: ignore[arg-type]
            policy_ok = True
            status = outcome_to_result_status(outcome)  # type: ignore[arg-type]
            if shadow is not None and parity is not None and parity.shadow_agreed is False:
                status = ResultStatus.UNKNOWN

        rendered_datalog = ""
        rendered_secpal = ""
        datalog_result = None
        secpal_result = None
        if provider is RuleProviderKind.DATALOG:
            rendered_datalog = render_datalog_program(document, query)
            datalog_result = native.result
        else:
            rendered_secpal = render_secpal_program(document, query)
            secpal_result = native.result

        evidence = self._build_evidence(
            req=req,
            request_digest=request_digest,
            disposition=disposition,
            outcome=outcome,  # type: ignore[arg-type]
            mode=RuleExecutionMode.NATIVE_REFERENCE,
            provenance=provenance,
            semantics=semantics,
            parity=parity,
            policy_authority_established=policy_ok,
            decision=decision,
            explanation=explanation,
            evaluation_receipt=native.receipt,
            diagnostics=tuple(diagnostics),
            result_status=status,
            bounds_exhausted=native.receipt.bounds_exhausted,
        )
        return RuleExecutionResultV2(
            request=req,
            evidence=evidence,
            datalog_result=datalog_result,
            secpal_result=secpal_result,
            rendered_datalog=rendered_datalog,
            rendered_secpal=rendered_secpal,
        )

    def _build_evidence(
        self,
        *,
        req: RuleExecutionRequestV2,
        request_digest: str,
        disposition: RuleDisposition,
        outcome: DecisionOutcome | None,
        mode: RuleExecutionMode,
        provenance: RuleProvenanceBindingV2,
        semantics: RuleSemanticsBindingV2,
        parity: RuleParityReceiptV2 | None = None,
        policy_authority_established: bool,
        mock_output_present: bool = False,
        fallback_output_present: bool = False,
        decision: PolicyDecision | None = None,
        explanation: DecisionExplanation | None = None,
        evaluation_receipt: EvaluationReceipt | None = None,
        diagnostics: Sequence[str] = (),
        result_status: ResultStatus = ResultStatus.UNKNOWN,
        bounds_exhausted: bool = False,
    ) -> RuleProviderEvidenceV2:
        document: AuthorizationIR = req.document  # type: ignore[assignment]
        query: DecisionQuery = req.query  # type: ignore[assignment]
        provider: RuleProviderKind = req.provider  # type: ignore[assignment]
        # Stable record id (not a namespace evidence-kind identity).
        evidence_key = (
            f"ev:rule:{provider.value}:{req.request_id}:{disposition.value}"
        )
        return RuleProviderEvidenceV2(
            evidence_id=evidence_key,
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=disposition,
            outcome=outcome,
            mode=mode,
            policy_digest=document.sha256,
            query_id=query.query_id,
            provenance=provenance,
            semantics=semantics,
            source_ref_ids=req.source_ref_ids,
            parity=parity,
            result_status=result_status,
            policy_authority_established=policy_authority_established,
            mock_output_present=mock_output_present or req.has_mock_output,
            fallback_output_present=fallback_output_present or req.has_fallback_output,
            available=req.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            bounds_exhausted=bounds_exhausted,
            decision=decision,
            explanation=explanation,
            evaluation_receipt=evaluation_receipt,
            diagnostics=tuple(diagnostics),
        )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def execute_authorization(
    document: AuthorizationIR | Mapping[str, Any],
    query: DecisionQuery | Mapping[str, Any] | str | None = None,
    *,
    request_id: str = "req:authorization:1",
    provider: RuleProviderKind | str = RuleProviderKind.PARITY,
    world: WorldSemantics | str = WorldSemantics.CLOSED_WORLD,
    **kwargs: Any,
) -> RuleExecutionResultV2:
    """Execute one authorization document/query through RuleProviderEvidence@2."""

    request = RuleExecutionRequestV2(
        request_id=request_id,
        provider=provider,
        document=document,
        query=query,
        world=world,
        **kwargs,
    )
    return RuleExecutionEngineV2().execute(request)


def execute_datalog(
    document: AuthorizationIR | Mapping[str, Any],
    query: DecisionQuery | Mapping[str, Any] | str | None = None,
    **kwargs: Any,
) -> RuleExecutionResultV2:
    return execute_authorization(
        document, query, provider=RuleProviderKind.DATALOG, **kwargs
    )


def execute_secpal(
    document: AuthorizationIR | Mapping[str, Any],
    query: DecisionQuery | Mapping[str, Any] | str | None = None,
    **kwargs: Any,
) -> RuleExecutionResultV2:
    return execute_authorization(
        document, query, provider=RuleProviderKind.SECPAL, **kwargs
    )


def execute_parity(
    document: AuthorizationIR | Mapping[str, Any],
    query: DecisionQuery | Mapping[str, Any] | str | None = None,
    **kwargs: Any,
) -> RuleExecutionResultV2:
    return execute_authorization(
        document, query, provider=RuleProviderKind.PARITY, **kwargs
    )


__all__ = [
    "RULE_EXECUTION_REQUEST_V2_INTERFACE",
    "RULE_EXECUTION_RESULT_V2_INTERFACE",
    "RULE_EXECUTION_V2_GOAL_ID",
    "RULE_EXECUTION_V2_MODULE_VERSION",
    "RULE_EXECUTION_V2_TASK_ID",
    "RULE_PARITY_RECEIPT_V2_INTERFACE",
    "RULE_PROVIDER_EVIDENCE_V2_INTERFACE",
    "RULE_SEMANTICS_BINDING_V2_INTERFACE",
    "RuleAuthorityError",
    "RuleClaimKind",
    "RuleDisposition",
    "RuleExecutionEngineV2",
    "RuleExecutionError",
    "RuleExecutionMode",
    "RuleExecutionRequestV2",
    "RuleExecutionResultV2",
    "RuleParityReceiptV2",
    "RuleProvenanceBindingV2",
    "RuleProviderEvidenceV2",
    "RuleProviderKind",
    "RuleSemanticsBindingV2",
    "WorldSemantics",
    "execute_authorization",
    "execute_datalog",
    "execute_parity",
    "execute_secpal",
    "mock_or_fallback_establishes_policy",
    "non_authoritative_signal_establishes",
    "normalize_rule_provider",
    "provider_backend_id",
    "provider_logic_identity",
]
