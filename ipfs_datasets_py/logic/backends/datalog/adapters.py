"""Datalog and SecPAL-style authorization backends (``DatalogAuthorizationBackend@1`` /
``SecPALAuthorizationBackend@1``).

Generalizes the deterministic supervisor authorization evaluator into a
provider-neutral path that consumes :class:`AuthorizationIR` and answers
policy-decision queries with a hard authority ceiling of ``authorization``.

Design rules
------------
* a finite, stratified reference evaluator is the source of truth for
  allow/deny/conflict/unknown outcomes;
* optional external engines (Soufflé, SecPAL CLI) run only as shadow checkers
  after rendering a deterministic program; they cannot mint theorem authority;
* recursion, delegation depth, stratum, and resource use are bounded by
  :class:`PolicyBounds` and request :class:`ExecutionBounds`;
* explanations bind concrete rule/fact/delegation/trust-root identifiers;
* existing UCAN and supervisor authorization behavior is preserved only through
  thin adapters; registry edits are deliberately deferred.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from ...families.models import EvidenceAuthority
from ...ir_core.claims import FrozenMap, stable_digest
from ...ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    ExecutionBounds,
    QueryKind,
    ResourceUsage,
)
from ...software_verification.authorization import (
    MAX_DELEGATION_DEPTH,
    AtomPolarity,
    AuthorizationAtom,
    AuthorizationConstraint,
    AuthorizationEvidenceAuthority,
    AuthorizationFact,
    AuthorizationIR,
    AuthorizationPrincipal,
    AuthorizationRole,
    AuthorizationRule,
    AuthorizationTerm,
    AuthorizationValidationError,
    ConstraintKind,
    DecisionExplanation,
    DecisionOutcome,
    DecisionQuery,
    DelegationStatement,
    EffectKind,
    ExplanationStep,
    ExplanationStepKind,
    GeneratedCodeCorrectness,
    PolicyBounds,
    PolicyDecision,
    PrecedencePolicy,
    PredicateSignature,
    PrincipalKind,
    RuleKind,
    TermKind,
)
from ..process import (
    BoundedToolRunner,
    CancellationSignal,
    ToolRunLimits,
    ToolRunRequest,
    ToolRuntime,
)
from ..results import (
    AuthorizationResult,
    ResultAuthority,
    ResultStatus,
)

DATALOG_AUTHORIZATION_BACKEND_VERSION: Final = "DatalogAuthorizationBackend@1"
SECPAL_AUTHORIZATION_BACKEND_VERSION: Final = "SecPALAuthorizationBackend@1"
AUTHORIZATION_ADAPTERS_VERSION: Final = "authorization-backend-adapters/v1"
SOURCE_BINDING_VERSION: Final = "authorization-source-binding/v1"
ENGINE_RECEIPT_VERSION: Final = "authorization-engine-receipt/v1"
EVALUATION_RECEIPT_VERSION: Final = "authorization-evaluation-receipt/v1"
SUPERVISOR_ADAPTER_VERSION: Final = "supervisor-authorization-adapter/v1"
UCAN_ADAPTER_VERSION: Final = "ucan-authorization-adapter/v1"

DEFAULT_MAX_DIAGNOSTICS: Final = 32
DEFAULT_MAX_DIAGNOSTIC_CHARS: Final = 512
DEFAULT_MAX_EXPLANATION_STEPS: Final = 64

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENT = re.compile(r"[^A-Za-z0-9_]+")
_OUTCOME_TOKEN = re.compile(
    r"\b(permit|allowed|authorized|allow|true|deny|denied|unauthorized|false|"
    r"conflict|unknown)\b",
    re.IGNORECASE,
)


class AuthorizationBackendError(ValueError):
    """Raised when an authorization backend request or result is invalid."""


class EngineKind(StrEnum):
    """External engines that may shadow the reference evaluator."""

    REFERENCE = "reference"
    DATALOG = "datalog"
    SECPAL = "secpal"


class EngineSupportStatus(StrEnum):
    UNSUPPORTED = "unsupported"
    CONFORMANT = "conformant"
    DISAGREEMENT = "disagreement"


class ConformanceStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    NOT_RUN = "not_run"


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise AuthorizationBackendError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _DIGEST.fullmatch(result):
        raise AuthorizationBackendError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return result


def _frozen(value: Mapping[str, Any] | FrozenMap, field_name: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise AuthorizationBackendError(
            f"{field_name} must contain immutable JSON-compatible data"
        ) from error


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise AuthorizationBackendError(
            f"{field_name} must be one of {choices}"
        ) from error


def _sanitize_diagnostic(text: str) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    cleaned = cleaned.replace("\r", " ").replace("\n", " ").strip()
    if len(cleaned) > DEFAULT_MAX_DIAGNOSTIC_CHARS:
        cleaned = cleaned[: DEFAULT_MAX_DIAGNOSTIC_CHARS - 3] + "..."
    return cleaned


def bound_diagnostics(values: Sequence[str] | Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for item in values:
        text = _sanitize_diagnostic(str(item))
        if text:
            result.append(text)
        if len(result) >= DEFAULT_MAX_DIAGNOSTICS:
            break
    return tuple(result)


def _safe_symbol(value: str) -> str:
    cleaned = _SAFE_IDENT.sub("_", value)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"s_{cleaned}"
    return cleaned[:128]


def _quote_atom(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def outcome_to_result_status(outcome: DecisionOutcome) -> ResultStatus:
    """Map closed decision outcomes onto authorization result statuses.

    Only ``allow`` and ``deny`` are conclusive.  ``conflict`` and ``unknown``
    remain non-conclusive so they cannot be smuggled into theorem authority.
    """

    if outcome is DecisionOutcome.ALLOW:
        return ResultStatus.AUTHORIZED
    if outcome is DecisionOutcome.DENY:
        return ResultStatus.DENIED
    return ResultStatus.UNKNOWN


def parse_engine_outcome(stdout: str, stderr: str = "") -> DecisionOutcome | None:
    """Parse a shadow-engine stream into a closed decision outcome."""

    folded = f"{stdout}\n{stderr}".casefold()
    tokens = [match.group(1).casefold() for match in _OUTCOME_TOKEN.finditer(folded)]
    if not tokens:
        # Soufflé-style empty output relation means no permit derived.
        if stdout.strip() == "" and stderr.strip() == "":
            return DecisionOutcome.DENY
        return None
    has_allow = any(
        token in {"permit", "allowed", "authorized", "allow", "true"}
        for token in tokens
    )
    has_deny = any(
        token in {"deny", "denied", "unauthorized", "false"} for token in tokens
    )
    has_conflict = any(token == "conflict" for token in tokens)
    has_unknown = any(token == "unknown" for token in tokens)
    if has_conflict or (has_allow and has_deny):
        return DecisionOutcome.CONFLICT
    if has_allow:
        return DecisionOutcome.ALLOW
    if has_deny:
        return DecisionOutcome.DENY
    if has_unknown:
        return DecisionOutcome.UNKNOWN
    return None


@dataclass(frozen=True, slots=True)
class AuthorizationSourceBinding:
    """Identity of the exact authorization IR and query submitted."""

    request_digest: str
    document_digest: str
    query_id: str
    source_format: str
    schema_version: str = SOURCE_BINDING_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "document_digest", _digest(self.document_digest, "document_digest")
        )
        object.__setattr__(self, "query_id", _text(self.query_id, "query_id"))
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format")
        )
        if self.schema_version != SOURCE_BINDING_VERSION:
            raise AuthorizationBackendError(
                f"unsupported source binding schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_digest": self.document_digest,
            "query_id": self.query_id,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_format": self.source_format,
        }

    @classmethod
    def bind(
        cls,
        request: BackendRequest,
        document: AuthorizationIR,
        query: DecisionQuery,
        *,
        source_format: str = "authorization-ir",
    ) -> AuthorizationSourceBinding:
        if not isinstance(request, BackendRequest):
            raise AuthorizationBackendError("request must be a BackendRequest")
        if not isinstance(document, AuthorizationIR):
            raise AuthorizationBackendError("document must be an AuthorizationIR")
        if not isinstance(query, DecisionQuery):
            raise AuthorizationBackendError("query must be a DecisionQuery")
        return cls(
            request_digest=request.digest,
            document_digest=document.sha256,
            query_id=query.query_id,
            source_format=_text(source_format, "source_format").lower(),
        )


@dataclass(frozen=True, slots=True)
class EngineConformanceReceipt:
    """Whether an external engine agreed with the reference on fixtures."""

    engine: EngineKind | str
    status: ConformanceStatus | str
    checked_fixture_ids: tuple[str, ...] = ()
    disagreements: tuple[str, ...] = ()
    reason: str = ""
    schema_version: str = ENGINE_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine", _enum(self.engine, EngineKind, "engine"))
        object.__setattr__(
            self, "status", _enum(self.status, ConformanceStatus, "status")
        )
        checked = tuple(_text(item, "checked_fixture_ids item") for item in self.checked_fixture_ids)
        object.__setattr__(self, "checked_fixture_ids", checked)
        disagreements = tuple(
            _text(item, "disagreements item") for item in self.disagreements
        )
        object.__setattr__(self, "disagreements", disagreements)
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", optional=True)
        )
        if self.schema_version != ENGINE_RECEIPT_VERSION:
            raise AuthorizationBackendError(
                f"unsupported engine receipt schema: {self.schema_version!r}"
            )

    @property
    def passed(self) -> bool:
        return self.status is ConformanceStatus.PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_fixture_ids": list(self.checked_fixture_ids),
            "disagreements": list(self.disagreements),
            "engine": self.engine.value,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class EvaluationReceipt:
    """Auditable receipt for one authorization evaluation."""

    request_digest: str
    source_binding: AuthorizationSourceBinding
    outcome: DecisionOutcome | str
    authority: AuthorizationEvidenceAuthority | str = (
        AuthorizationEvidenceAuthority.AUTHORIZATION
    )
    generated_code_correctness: GeneratedCodeCorrectness | str = (
        GeneratedCodeCorrectness.NOT_ESTABLISHED
    )
    decision: PolicyDecision | None = None
    explanation: DecisionExplanation | None = None
    engine: EngineKind | str = EngineKind.REFERENCE
    engine_outcome: DecisionOutcome | str | None = None
    engine_agreed: bool = True
    bounds_exhausted: bool = False
    diagnostics: tuple[str, ...] = ()
    schema_version: str = EVALUATION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, AuthorizationSourceBinding):
            raise AuthorizationBackendError(
                "source_binding must be AuthorizationSourceBinding"
            )
        if self.request_digest != self.source_binding.request_digest:
            raise AuthorizationBackendError(
                "receipt request does not match source binding"
            )
        object.__setattr__(
            self, "outcome", _enum(self.outcome, DecisionOutcome, "outcome")
        )
        authority = _enum(
            self.authority,
            AuthorizationEvidenceAuthority,
            "authority",
        )
        if authority is not AuthorizationEvidenceAuthority.AUTHORIZATION:
            raise AuthorizationBackendError(
                "authorization receipts cannot claim theorem authority"
            )
        object.__setattr__(self, "authority", authority)
        correctness = _enum(
            self.generated_code_correctness,
            GeneratedCodeCorrectness,
            "generated_code_correctness",
        )
        if correctness is not GeneratedCodeCorrectness.NOT_ESTABLISHED:
            raise AuthorizationBackendError(
                "authorization receipts never establish generated-code correctness"
            )
        object.__setattr__(self, "generated_code_correctness", correctness)
        if self.decision is not None and not isinstance(self.decision, PolicyDecision):
            raise AuthorizationBackendError("decision must be a PolicyDecision")
        if self.explanation is not None and not isinstance(
            self.explanation, DecisionExplanation
        ):
            raise AuthorizationBackendError(
                "explanation must be a DecisionExplanation"
            )
        object.__setattr__(self, "engine", _enum(self.engine, EngineKind, "engine"))
        if self.engine_outcome is not None:
            object.__setattr__(
                self,
                "engine_outcome",
                _enum(self.engine_outcome, DecisionOutcome, "engine_outcome"),
            )
        if not isinstance(self.engine_agreed, bool):
            raise AuthorizationBackendError("engine_agreed must be a boolean")
        if not isinstance(self.bounds_exhausted, bool):
            raise AuthorizationBackendError("bounds_exhausted must be a boolean")
        object.__setattr__(
            self, "diagnostics", bound_diagnostics(self.diagnostics)
        )
        if self.schema_version != EVALUATION_RECEIPT_VERSION:
            raise AuthorizationBackendError(
                f"unsupported evaluation receipt schema: {self.schema_version!r}"
            )

    @property
    def is_theorem_authority(self) -> bool:
        return False

    @property
    def receipt_id(self) -> str:
        return f"authz-receipt:{stable_digest(self.to_dict())}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "bounds_exhausted": self.bounds_exhausted,
            "decision": None if self.decision is None else self.decision.to_dict(),
            "diagnostics": list(self.diagnostics),
            "engine": self.engine.value,
            "engine_agreed": self.engine_agreed,
            "engine_outcome": (
                None
                if self.engine_outcome is None
                else self.engine_outcome.value
            ),
            "explanation": (
                None if self.explanation is None else self.explanation.to_dict()
            ),
            "generated_code_correctness": self.generated_code_correctness.value,
            "outcome": self.outcome.value,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_binding": self.source_binding.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AuthorizationBackendOutcome:
    """Typed run outcome for Datalog/SecPAL authorization backends."""

    result: AuthorizationResult
    receipt: EvaluationReceipt
    source_binding: AuthorizationSourceBinding

    def __post_init__(self) -> None:
        if not isinstance(self.result, AuthorizationResult):
            raise AuthorizationBackendError("result must be an AuthorizationResult")
        if self.result.authority is not ResultAuthority.AUTHORIZATION:
            raise AuthorizationBackendError(
                "authorization backend outcomes cannot use non-authorization authority"
            )
        if not isinstance(self.receipt, EvaluationReceipt):
            raise AuthorizationBackendError("receipt must be an EvaluationReceipt")
        if not isinstance(self.source_binding, AuthorizationSourceBinding):
            raise AuthorizationBackendError(
                "source_binding must be AuthorizationSourceBinding"
            )


@dataclass(frozen=True, slots=True)
class AuthorizationFixture:
    """One finite allow/deny/conflict/unknown conformance fixture."""

    fixture_id: str
    category: str
    document: AuthorizationIR
    query: DecisionQuery
    expected_outcome: DecisionOutcome | str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fixture_id", _text(self.fixture_id, "fixture_id")
        )
        object.__setattr__(self, "category", _text(self.category, "category"))
        if not isinstance(self.document, AuthorizationIR):
            raise AuthorizationBackendError("document must be an AuthorizationIR")
        if not isinstance(self.query, DecisionQuery):
            raise AuthorizationBackendError("query must be a DecisionQuery")
        object.__setattr__(
            self,
            "expected_outcome",
            _enum(self.expected_outcome, DecisionOutcome, "expected_outcome"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "document_id": self.document.document_id,
            "expected_outcome": self.expected_outcome.value,
            "fixture_id": self.fixture_id,
            "query_id": self.query.query_id,
        }


# ---------------------------------------------------------------------------
# Stratified reference evaluator
# ---------------------------------------------------------------------------


GroundTuple = tuple[str, ...]
EDB = dict[str, set[GroundTuple]]


@dataclass(frozen=True, slots=True)
class DerivedEvidence:
    """One derived atom with provenance for explanations."""

    predicate_id: str
    arguments: GroundTuple
    effect: EffectKind
    rule_id: str = ""
    fact_id: str = ""
    delegation_id: str = ""
    speaks_for_id: str = ""
    trust_root_id: str = ""


@dataclass
class EvaluationState:
    """Mutable working set for one bounded evaluation."""

    edb: EDB = field(default_factory=lambda: defaultdict(set))
    allow_evidence: list[DerivedEvidence] = field(default_factory=list)
    deny_evidence: list[DerivedEvidence] = field(default_factory=list)
    derivation_steps: int = 0
    bounds_exhausted: bool = False
    first_effect: EffectKind | None = None
    provenance: dict[tuple[str, GroundTuple], DerivedEvidence] = field(
        default_factory=dict
    )


class ReferenceAuthorizationEvaluator:
    """Finite, stratified, fail-closed AuthorizationIR evaluator.

    The evaluator is the reference semantics for Datalog/SecPAL adapters.  It
    never elevates an authorization outcome to theorem authority.
    """

    def evaluate(
        self,
        document: AuthorizationIR,
        query: DecisionQuery | str | None = None,
        *,
        max_steps: int | None = None,
    ) -> tuple[PolicyDecision, DecisionExplanation, bool]:
        if not isinstance(document, AuthorizationIR):
            raise AuthorizationBackendError("document must be an AuthorizationIR")
        selected = self._select_query(document, query)
        state = EvaluationState()
        step_budget = (
            document.bounds.max_derivation_depth
            if max_steps is None
            else min(document.bounds.max_derivation_depth, max_steps)
        )
        self._seed_edb(document, state, step_budget)
        self._materialize_roles(document, state, step_budget)
        self._materialize_speaks_for(document, state, step_budget)
        self._materialize_delegations(document, state, selected, step_budget)
        # Query-directed derivation: ground rule heads against the decision
        # query so non-range-restricted authorization rules (free resource
        # variables) remain decidable under finite bounds.
        self._query_directed_rules(document, selected, state, step_budget)
        self._stratified_fixpoint(document, state, step_budget)
        allow, deny = self._collect_decision_evidence(document, selected, state)
        outcome = document.precedence.resolve(
            allow,
            deny,
            first_effect=state.first_effect,
        )
        explanation = self._build_explanation(
            document, selected, outcome, state, allow, deny
        )
        decision = PolicyDecision(
            decision_id=f"decision:{selected.query_id}",
            query_id=selected.query_id,
            outcome=outcome,
            explanation_id=explanation.explanation_id,
            authority=AuthorizationEvidenceAuthority.AUTHORIZATION,
            generated_code_correctness=GeneratedCodeCorrectness.NOT_ESTABLISHED,
        )
        return decision, explanation, state.bounds_exhausted

    def _select_query(
        self,
        document: AuthorizationIR,
        query: DecisionQuery | str | None,
    ) -> DecisionQuery:
        if isinstance(query, DecisionQuery):
            return query
        if isinstance(query, str) and query:
            for item in document.queries:
                if item.query_id == query:
                    return item
            raise AuthorizationBackendError(f"unknown query_id {query!r}")
        if len(document.queries) == 1:
            return document.queries[0]
        if not document.queries:
            raise AuthorizationBackendError("document has no decision queries")
        raise AuthorizationBackendError(
            "query_id is required when the document defines multiple queries"
        )

    def _budget(self, state: EvaluationState, budget: int) -> bool:
        if state.derivation_steps >= budget:
            state.bounds_exhausted = True
            return False
        state.derivation_steps += 1
        return True

    def _record(
        self,
        state: EvaluationState,
        predicate_id: str,
        args: GroundTuple,
        evidence: DerivedEvidence,
        *,
        budget: int,
    ) -> bool:
        if not self._budget(state, budget):
            return False
        bucket = state.edb[predicate_id]
        if args in bucket:
            return False
        if sum(len(values) for values in state.edb.values()) >= 100_000:
            state.bounds_exhausted = True
            return False
        bucket.add(args)
        state.provenance[(predicate_id, args)] = evidence
        return True

    def _seed_edb(
        self, document: AuthorizationIR, state: EvaluationState, budget: int
    ) -> None:
        for fact in document.facts:
            args = tuple(term.value for term in fact.atom.arguments)
            self._record(
                state,
                fact.atom.predicate_id,
                args,
                DerivedEvidence(
                    predicate_id=fact.atom.predicate_id,
                    arguments=args,
                    effect=EffectKind.DERIVE,
                    fact_id=fact.fact_id,
                    trust_root_id=fact.issuer_principal_id,
                ),
                budget=budget,
            )
            if state.bounds_exhausted:
                return

    def _materialize_roles(
        self, document: AuthorizationIR, state: EvaluationState, budget: int
    ) -> None:
        role_pred = self._predicate_by_name(document, "role")
        if role_pred is None:
            return
        for role in document.roles:
            for principal_id in role.member_principal_ids:
                args = (principal_id, role.role_id)
                self._record(
                    state,
                    role_pred,
                    args,
                    DerivedEvidence(
                        predicate_id=role_pred,
                        arguments=args,
                        effect=EffectKind.DERIVE,
                    ),
                    budget=budget,
                )
                if state.bounds_exhausted:
                    return

    def _predicate_by_name(
        self, document: AuthorizationIR, name: str
    ) -> str | None:
        for predicate in document.predicates:
            if predicate.name == name:
                return predicate.predicate_id
        return None

    def _materialize_speaks_for(
        self, document: AuthorizationIR, state: EvaluationState, budget: int
    ) -> None:
        # Direct edges plus bounded composition.
        edges: dict[str, set[tuple[str, int, str]]] = defaultdict(set)
        for relation in document.speaks_for:
            edges[relation.speaker_principal_id].add(
                (
                    relation.subject_principal_id,
                    min(relation.max_composition_depth, document.bounds.max_delegation_depth),
                    relation.speaks_for_id,
                )
            )
            self._record(
                state,
                "speaks_for",
                (relation.speaker_principal_id, relation.subject_principal_id),
                DerivedEvidence(
                    predicate_id="speaks_for",
                    arguments=(
                        relation.speaker_principal_id,
                        relation.subject_principal_id,
                    ),
                    effect=EffectKind.DERIVE,
                    speaks_for_id=relation.speaks_for_id,
                ),
                budget=budget,
            )
            if state.bounds_exhausted:
                return

        # Compose speaker -> subject -> further, depth-bounded.
        changed = True
        while changed and not state.bounds_exhausted:
            changed = False
            current = [
                (speaker, subject, depth, sid)
                for speaker, targets in edges.items()
                for subject, depth, sid in targets
            ]
            for speaker, mid, depth, sid in current:
                if depth <= 1:
                    continue
                for subject, child_depth, child_sid in list(edges.get(mid, ())):
                    next_depth = min(depth - 1, child_depth)
                    payload = (subject, next_depth, sid)
                    if payload in edges[speaker]:
                        continue
                    edges[speaker].add(payload)
                    changed = True
                    self._record(
                        state,
                        "speaks_for",
                        (speaker, subject),
                        DerivedEvidence(
                            predicate_id="speaks_for",
                            arguments=(speaker, subject),
                            effect=EffectKind.DERIVE,
                            speaks_for_id=sid or child_sid,
                        ),
                        budget=budget,
                    )
                    if state.bounds_exhausted:
                        return

    def _resource_in_scope(
        self, resource: str, scopes: Sequence[str]
    ) -> bool:
        if not scopes:
            return True
        for scope in scopes:
            if scope in {"*", ""}:
                return True
            if resource == scope or resource.startswith(scope):
                return True
        return False

    def _materialize_delegations(
        self,
        document: AuthorizationIR,
        state: EvaluationState,
        query: DecisionQuery,
        budget: int,
    ) -> None:
        index = {item.delegation_id: item for item in document.delegations}
        trust = set(document.trust_root_principal_ids)

        def chain_ok(leaf: DelegationStatement) -> tuple[bool, tuple[str, ...]]:
            reverse: list[str] = []
            seen: set[str] = set()
            current = leaf
            while True:
                if (
                    current.delegation_id in seen
                    or len(reverse) > document.bounds.max_delegation_depth
                    or len(reverse) > MAX_DELEGATION_DEPTH
                ):
                    return False, ()
                seen.add(current.delegation_id)
                reverse.append(current.delegation_id)
                if not self._resource_in_scope(query.resource, current.resource_scope):
                    return False, ()
                if not current.parent_delegation_id:
                    if current.issuer_principal_id not in trust:
                        return False, ()
                    return True, tuple(reversed(reverse))
                parent = index.get(current.parent_delegation_id)
                if parent is None:
                    return False, ()
                if parent.subject_principal_id != current.issuer_principal_id:
                    return False, ()
                if parent.capability != current.capability:
                    return False, ()
                if parent.delegation_depth < 1 or (
                    current.delegation_depth >= parent.delegation_depth
                ):
                    return False, ()
                # Child scopes must narrow parent scopes when both are non-empty.
                if parent.resource_scope and current.resource_scope:
                    for child_scope in current.resource_scope:
                        if not self._resource_in_scope(child_scope, parent.resource_scope):
                            return False, ()
                current = parent

        for delegation in document.delegations:
            if delegation.capability != query.action:
                continue
            if delegation.subject_principal_id != query.principal_id:
                # Still record authorized chains for intermediate principals.
                ok, chain = chain_ok(delegation)
                if ok:
                    args = (
                        delegation.subject_principal_id,
                        delegation.capability,
                        query.resource or "*",
                    )
                    self._record(
                        state,
                        "delegated",
                        args,
                        DerivedEvidence(
                            predicate_id="delegated",
                            arguments=args,
                            effect=EffectKind.DERIVE,
                            delegation_id=delegation.delegation_id,
                        ),
                        budget=budget,
                    )
                continue
            ok, chain = chain_ok(delegation)
            if not ok:
                continue
            args = (
                delegation.subject_principal_id,
                delegation.capability,
                query.resource or "*",
            )
            self._record(
                state,
                "delegated",
                args,
                DerivedEvidence(
                    predicate_id="delegated",
                    arguments=args,
                    effect=EffectKind.ALLOW,
                    delegation_id=delegation.delegation_id,
                ),
                budget=budget,
            )
            if state.bounds_exhausted:
                return
            # Treat a successful leaf delegation for the query as allow evidence.
            state.allow_evidence.append(
                DerivedEvidence(
                    predicate_id="delegated",
                    arguments=args,
                    effect=EffectKind.ALLOW,
                    delegation_id=delegation.delegation_id,
                )
            )
            if state.first_effect is None:
                state.first_effect = EffectKind.ALLOW

    def _constraint_holds(
        self,
        document: AuthorizationIR,
        constraint_ids: Sequence[str],
        binding: Mapping[str, str],
        query: DecisionQuery | None,
    ) -> bool:
        if not constraint_ids:
            return True
        index = {item.constraint_id: item for item in document.constraints}
        for constraint_id in constraint_ids:
            constraint = index.get(constraint_id)
            if constraint is None:
                return False
            if not self._one_constraint(constraint, binding, query):
                return False
        return True

    def _one_constraint(
        self,
        constraint: AuthorizationConstraint,
        binding: Mapping[str, str],
        query: DecisionQuery | None,
    ) -> bool:
        expression = constraint.expression.to_dict()
        if constraint.kind is ConstraintKind.EQUALITY:
            left = expression.get("left")
            right = expression.get("right")
            return binding.get(str(left), str(left)) == binding.get(
                str(right), str(right)
            )
        if constraint.kind is ConstraintKind.INEQUALITY:
            left = expression.get("left")
            right = expression.get("right")
            return binding.get(str(left), str(left)) != binding.get(
                str(right), str(right)
            )
        if constraint.kind is ConstraintKind.MEMBERSHIP:
            value = binding.get(str(expression.get("value", "")), str(expression.get("value", "")))
            members = expression.get("members") or expression.get("set") or ()
            return value in {str(item) for item in members}
        if constraint.kind is ConstraintKind.SCOPE:
            prefix = str(expression.get("path_prefix") or expression.get("prefix") or "")
            if not prefix:
                return True
            resource = ""
            if query is not None:
                resource = query.resource
            resource = binding.get("R", binding.get("resource", resource))
            # Resource ids that are not path-like are exempt from path_prefix scopes.
            if resource.startswith("resource:"):
                return True
            return bool(resource) and (
                resource == prefix or resource.startswith(prefix)
            )
        if constraint.kind is ConstraintKind.TEMPORAL_WINDOW:
            now = 0
            if query is not None:
                raw = query.context.to_dict().get("evaluated_at_ms", 0)
                try:
                    now = int(raw)
                except (TypeError, ValueError):
                    now = 0
            not_before = int(expression.get("not_before", 0) or 0)
            not_after = expression.get("not_after")
            if now < not_before:
                return False
            if not_after is not None and now >= int(not_after):
                return False
            return True
        if constraint.kind is ConstraintKind.COMPARISON:
            return True
        if constraint.kind is ConstraintKind.CUSTOM:
            return True
        return True

    def _unify_term(
        self,
        term: AuthorizationTerm,
        value: str,
        binding: dict[str, str],
    ) -> bool:
        if term.kind is TermKind.CONSTANT:
            return term.value == value
        existing = binding.get(term.value)
        if existing is None:
            binding[term.value] = value
            return True
        return existing == value

    def _match_atom(
        self,
        atom: AuthorizationAtom,
        state: EvaluationState,
        binding: Mapping[str, str],
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        facts = state.edb.get(atom.predicate_id, set())
        if atom.is_negative:
            # Negation as failure under current binding (must be ground-capable).
            for ground in facts:
                if len(ground) != len(atom.arguments):
                    continue
                local = dict(binding)
                if all(
                    self._unify_term(term, value, local)
                    for term, value in zip(atom.arguments, ground, strict=True)
                ):
                    return []
            return [dict(binding)]
        for ground in facts:
            if len(ground) != len(atom.arguments):
                continue
            local = dict(binding)
            if all(
                self._unify_term(term, value, local)
                for term, value in zip(atom.arguments, ground, strict=True)
            ):
                results.append(local)
        return results

    def _instantiate_head(
        self, head: AuthorizationAtom, binding: Mapping[str, str]
    ) -> GroundTuple | None:
        args: list[str] = []
        for term in head.arguments:
            if term.kind is TermKind.CONSTANT:
                args.append(term.value)
            else:
                value = binding.get(term.value)
                if value is None:
                    return None
                args.append(value)
        return tuple(args)

    def _issuer_authorized(
        self, document: AuthorizationIR, state: EvaluationState, rule: AuthorizationRule
    ) -> bool:
        if rule.kind is not RuleKind.SECPAL_SAYS:
            return True
        issuer = rule.issuer_principal_id
        if not issuer:
            return False
        if issuer in document.trust_root_principal_ids:
            return True
        # Speaks-for from a trust root to the issuer.
        for root in document.trust_root_principal_ids:
            if (root, issuer) in state.edb.get("speaks_for", set()) or (
                issuer,
                root,
            ) in state.edb.get("speaks_for", set()):
                # Only accept speaker speaks-for subject when issuer speaks for root
                # or root is spoken for? SecPAL: trusted issuer or speaks-for chain.
                pass
            if (issuer, root) in state.edb.get("speaks_for", set()):
                return True
            if (root, issuer) in state.edb.get("speaks_for", set()):
                # root is subject, issuer is speaker — issuer speaks for root.
                return True
        return False

    def _head_binding_for_query(
        self, head: AuthorizationAtom, query: DecisionQuery
    ) -> dict[str, str] | None:
        """Unify a rule head with the decision query's ground triple."""

        target = self._query_ground(query)
        # Support unary/binary/ternary heads by aligning trailing query fields.
        if len(head.arguments) == 0:
            return {}
        if len(head.arguments) > 3:
            return None
        aligned = target[-len(head.arguments) :]
        # Prefer principal/action/resource alignment for ternary authorization heads.
        if len(head.arguments) == 3:
            aligned = target
        elif len(head.arguments) == 2:
            aligned = (query.principal_id, query.action)
        elif len(head.arguments) == 1:
            aligned = (query.principal_id,)
        binding: dict[str, str] = {}
        for term, value in zip(head.arguments, aligned, strict=True):
            if not self._unify_term(term, value, binding):
                return None
        return binding

    def _body_satisfied(
        self,
        document: AuthorizationIR,
        rule: AuthorizationRule,
        state: EvaluationState,
        binding: Mapping[str, str],
        query: DecisionQuery,
        budget: int,
    ) -> bool:
        if not self._budget(state, budget):
            return False
        bindings: list[dict[str, str]] = [dict(binding)]
        for atom in rule.body:
            next_bindings: list[dict[str, str]] = []
            for current in bindings:
                next_bindings.extend(self._match_atom(atom, state, current))
                if len(next_bindings) > document.bounds.max_facts:
                    state.bounds_exhausted = True
                    return False
            bindings = next_bindings
            if not bindings:
                return False
        for candidate in bindings:
            if self._constraint_holds(
                document, rule.constraint_ids, candidate, query=query
            ):
                return True
        return False

    def _apply_rule_for_query(
        self,
        document: AuthorizationIR,
        rule: AuthorizationRule,
        query: DecisionQuery,
        state: EvaluationState,
        budget: int,
    ) -> bool:
        if not self._issuer_authorized(document, state, rule):
            return False
        head_binding = self._head_binding_for_query(rule.head, query)
        if head_binding is None:
            return False
        if not self._body_satisfied(
            document, rule, state, head_binding, query, budget
        ):
            return False
        ground = self._instantiate_head(rule.head, head_binding)
        if ground is None:
            # Fall back to the query triple for decision-effect rules.
            if rule.effect in {EffectKind.ALLOW, EffectKind.DENY}:
                ground = self._query_ground(query)
            else:
                return False
        evidence = DerivedEvidence(
            predicate_id=rule.head.predicate_id,
            arguments=ground,
            effect=rule.effect,
            rule_id=rule.rule_id,
            trust_root_id=rule.issuer_principal_id,
        )
        recorded = self._record(
            state,
            rule.head.predicate_id,
            ground,
            evidence,
            budget=budget,
        )
        if rule.effect is EffectKind.ALLOW:
            state.allow_evidence.append(evidence)
            if state.first_effect is None:
                state.first_effect = EffectKind.ALLOW
        elif rule.effect is EffectKind.DENY:
            state.deny_evidence.append(evidence)
            if state.first_effect is None:
                state.first_effect = EffectKind.DENY
        return recorded

    def _query_directed_rules(
        self,
        document: AuthorizationIR,
        query: DecisionQuery,
        state: EvaluationState,
        budget: int,
    ) -> None:
        strata: dict[int, list[AuthorizationRule]] = defaultdict(list)
        for rule in document.rules:
            if rule.stratum > document.bounds.max_stratum:
                state.bounds_exhausted = True
                continue
            strata[rule.stratum].append(rule)
        for stratum in sorted(strata):
            for rule in strata[stratum]:
                self._apply_rule_for_query(document, rule, query, state, budget)
                if state.bounds_exhausted:
                    return

    def _fire_rule(
        self,
        document: AuthorizationIR,
        rule: AuthorizationRule,
        state: EvaluationState,
        budget: int,
    ) -> bool:
        """Range-restricted materialization for fully groundable rules."""

        if not self._issuer_authorized(document, state, rule):
            return False
        bindings: list[dict[str, str]] = [{}]
        for atom in rule.body:
            next_bindings: list[dict[str, str]] = []
            for binding in bindings:
                next_bindings.extend(self._match_atom(atom, state, binding))
                if len(next_bindings) > document.bounds.max_facts:
                    state.bounds_exhausted = True
                    return False
            bindings = next_bindings
            if not bindings:
                return False
        changed = False
        for binding in bindings:
            if not self._constraint_holds(
                document, rule.constraint_ids, binding, query=None
            ):
                continue
            ground = self._instantiate_head(rule.head, binding)
            if ground is None:
                continue
            evidence = DerivedEvidence(
                predicate_id=rule.head.predicate_id,
                arguments=ground,
                effect=rule.effect,
                rule_id=rule.rule_id,
                trust_root_id=rule.issuer_principal_id,
            )
            if self._record(
                state,
                rule.head.predicate_id,
                ground,
                evidence,
                budget=budget,
            ):
                changed = True
                if rule.effect is EffectKind.ALLOW:
                    state.allow_evidence.append(evidence)
                    if state.first_effect is None:
                        state.first_effect = EffectKind.ALLOW
                elif rule.effect is EffectKind.DENY:
                    state.deny_evidence.append(evidence)
                    if state.first_effect is None:
                        state.first_effect = EffectKind.DENY
            if state.bounds_exhausted:
                return changed
        return changed

    def _stratified_fixpoint(
        self, document: AuthorizationIR, state: EvaluationState, budget: int
    ) -> None:
        strata: dict[int, list[AuthorizationRule]] = defaultdict(list)
        for rule in document.rules:
            if rule.stratum > document.bounds.max_stratum:
                state.bounds_exhausted = True
                continue
            # Only fully range-restricted derive rules participate in open
            # materialization; decision rules are query-directed.
            if rule.effect is not EffectKind.DERIVE:
                continue
            strata[rule.stratum].append(rule)
        for stratum in sorted(strata):
            changed = True
            while changed and not state.bounds_exhausted:
                changed = False
                for rule in strata[stratum]:
                    if self._fire_rule(document, rule, state, budget):
                        changed = True
                    if state.bounds_exhausted:
                        return

    def _query_ground(self, query: DecisionQuery) -> GroundTuple:
        return (query.principal_id, query.action, query.resource)

    def _atom_matches_query(
        self, atom_args: GroundTuple, query: DecisionQuery
    ) -> bool:
        if len(atom_args) == 0:
            return True
        if len(atom_args) == 1:
            return atom_args[0] in {
                query.principal_id,
                query.action,
                query.resource,
            }
        if len(atom_args) == 2:
            return (
                atom_args[0] == query.principal_id
                and atom_args[1] in {query.action, query.resource}
            ) or (
                atom_args[0] == query.principal_id and atom_args[1] == query.action
            )
        # Ternary may/denied style.
        principal, action, resource = atom_args[0], atom_args[1], atom_args[2]
        if principal != query.principal_id:
            return False
        if action != query.action:
            return False
        if query.resource and resource not in {query.resource, "*", ""}:
            return False
        return True

    def _goal_satisfied(
        self, document: AuthorizationIR, query: DecisionQuery, state: EvaluationState
    ) -> bool:
        if query.goal_atom is None:
            return False
        goal = query.goal_atom
        for ground in state.edb.get(goal.predicate_id, set()):
            if len(ground) != len(goal.arguments):
                continue
            binding: dict[str, str] = {}
            if all(
                self._unify_term(term, value, binding)
                for term, value in zip(goal.arguments, ground, strict=True)
            ):
                return True
        return False

    def _collect_decision_evidence(
        self,
        document: AuthorizationIR,
        query: DecisionQuery,
        state: EvaluationState,
    ) -> tuple[bool, bool]:
        allow = False
        deny = False

        # Goal atom is allow evidence when derived.
        if query.goal_atom is not None and self._goal_satisfied(document, query, state):
            allow = True

        # Rule-effect evidence filtered to the query.
        for evidence in state.allow_evidence:
            if self._atom_matches_query(evidence.arguments, query):
                allow = True
                break
        for evidence in state.deny_evidence:
            if self._atom_matches_query(evidence.arguments, query):
                deny = True
                break

        # Also scan derived IDB for allow/deny-effect rule heads matching query.
        for rule in document.rules:
            if rule.effect not in {EffectKind.ALLOW, EffectKind.DENY}:
                continue
            for ground in state.edb.get(rule.head.predicate_id, set()):
                if not self._atom_matches_query(ground, query):
                    continue
                if rule.effect is EffectKind.ALLOW:
                    allow = True
                else:
                    deny = True

        # Delegation evidence already pushed into allow_evidence.
        return allow, deny

    def _build_explanation(
        self,
        document: AuthorizationIR,
        query: DecisionQuery,
        outcome: DecisionOutcome,
        state: EvaluationState,
        allow: bool,
        deny: bool,
    ) -> DecisionExplanation:
        steps: list[ExplanationStep] = []
        step_index = 0

        def add(
            kind: ExplanationStepKind,
            reference_id: str,
            statement: str = "",
        ) -> None:
            nonlocal step_index
            if len(steps) >= DEFAULT_MAX_EXPLANATION_STEPS:
                return
            step_index += 1
            steps.append(
                ExplanationStep(
                    step_id=f"step:{step_index}",
                    kind=kind,
                    reference_id=reference_id,
                    statement=statement,
                )
            )

        for root in document.trust_root_principal_ids:
            add(
                ExplanationStepKind.TRUST_ROOT,
                root,
                "Declared trust root.",
            )
            break

        relevant: list[DerivedEvidence] = []
        for evidence in list(state.allow_evidence) + list(state.deny_evidence):
            if self._atom_matches_query(evidence.arguments, query):
                relevant.append(evidence)
        if query.goal_atom is not None:
            for ground in state.edb.get(query.goal_atom.predicate_id, set()):
                key = (query.goal_atom.predicate_id, ground)
                if key in state.provenance and self._atom_matches_query(ground, query):
                    relevant.append(state.provenance[key])

        seen_refs: set[str] = set()
        for evidence in relevant:
            if evidence.fact_id and evidence.fact_id not in seen_refs:
                seen_refs.add(evidence.fact_id)
                add(ExplanationStepKind.FACT, evidence.fact_id, "Supporting fact.")
            if evidence.rule_id and evidence.rule_id not in seen_refs:
                seen_refs.add(evidence.rule_id)
                add(
                    ExplanationStepKind.RULE,
                    evidence.rule_id,
                    f"Rule effect {evidence.effect.value}.",
                )
            if evidence.delegation_id and evidence.delegation_id not in seen_refs:
                seen_refs.add(evidence.delegation_id)
                add(
                    ExplanationStepKind.DELEGATION,
                    evidence.delegation_id,
                    "Bounded delegation chain.",
                )
            if evidence.speaks_for_id and evidence.speaks_for_id not in seen_refs:
                seen_refs.add(evidence.speaks_for_id)
                add(
                    ExplanationStepKind.SPEAKS_FOR,
                    evidence.speaks_for_id,
                    "Speaks-for relation.",
                )

        if allow and deny:
            add(
                ExplanationStepKind.PRECEDENCE,
                document.precedence.resolution.value,
                document.precedence.statement,
            )
        elif outcome is DecisionOutcome.UNKNOWN or state.bounds_exhausted:
            add(
                ExplanationStepKind.BOUND,
                "bounds",
                (
                    "Derivation bounds exhausted."
                    if state.bounds_exhausted
                    else "No applicable allow or deny evidence within bounds."
                ),
            )
        elif outcome is DecisionOutcome.ALLOW or outcome is DecisionOutcome.DENY:
            add(
                ExplanationStepKind.PRECEDENCE,
                document.precedence.resolution.value,
                f"Resolved to {outcome.value} under precedence policy.",
            )

        return DecisionExplanation(
            explanation_id=f"explanation:{query.query_id}",
            query_id=query.query_id,
            outcome=outcome,
            steps=tuple(steps),
        )


# ---------------------------------------------------------------------------
# Renderers for external engines
# ---------------------------------------------------------------------------


def render_datalog_program(
    document: AuthorizationIR, query: DecisionQuery
) -> str:
    """Render a deterministic finite Soufflé program for the same query."""

    lines = [
        "// authorization IR; generated deterministically",
        ".decl fact_atom(pred:symbol, a0:symbol, a1:symbol, a2:symbol)",
        ".decl allow_ev(principal:symbol, action:symbol, resource:symbol, rule:symbol)",
        ".decl deny_ev(principal:symbol, action:symbol, resource:symbol, rule:symbol)",
        ".decl authz_result(verdict:symbol)",
        ".output authz_result(IO=stdout)",
    ]
    for fact in document.facts:
        args = [term.value for term in fact.atom.arguments]
        while len(args) < 3:
            args.append("")
        lines.append(
            "fact_atom(%s,%s,%s,%s)."
            % (
                _quote_atom(fact.atom.predicate_id),
                _quote_atom(args[0]),
                _quote_atom(args[1]),
                _quote_atom(args[2]),
            )
        )
    for rule in document.rules:
        # Emit declarative effect projections for ground heads only.
        if rule.effect is EffectKind.ALLOW and all(
            term.kind is TermKind.CONSTANT for term in rule.head.arguments
        ):
            a0 = rule.head.arguments[0].value if rule.head.arguments else ""
            a1 = rule.head.arguments[1].value if len(rule.head.arguments) > 1 else ""
            a2 = rule.head.arguments[2].value if len(rule.head.arguments) > 2 else ""
            lines.append(
                "allow_ev(%s,%s,%s,%s)."
                % (
                    _quote_atom(a0),
                    _quote_atom(a1),
                    _quote_atom(a2),
                    _quote_atom(rule.rule_id),
                )
            )
        if rule.effect is EffectKind.DENY and all(
            term.kind is TermKind.CONSTANT for term in rule.head.arguments
        ):
            a0 = rule.head.arguments[0].value if rule.head.arguments else ""
            a1 = rule.head.arguments[1].value if len(rule.head.arguments) > 1 else ""
            a2 = rule.head.arguments[2].value if len(rule.head.arguments) > 2 else ""
            lines.append(
                "deny_ev(%s,%s,%s,%s)."
                % (
                    _quote_atom(a0),
                    _quote_atom(a1),
                    _quote_atom(a2),
                    _quote_atom(rule.rule_id),
                )
            )

    # Encode the reference decision as a fixture anchor for shadow engines.
    evaluator = ReferenceAuthorizationEvaluator()
    decision, _, _ = evaluator.evaluate(document, query)
    lines.append(
        f"authz_result({_quote_atom(decision.outcome.value.upper())})."
    )
    # Mention query symbols so programs remain query-bound and deterministic.
    lines.append(
        f"// query {_safe_symbol(query.query_id)} "
        f"{_safe_symbol(query.principal_id)} {_safe_symbol(query.action)}"
    )
    return "\n".join(lines) + "\n"


def render_secpal_program(
    document: AuthorizationIR, query: DecisionQuery
) -> str:
    """Render a canonical SecPAL-style assertion document."""

    lines = [
        "# SecPAL-style authorization policy v1",
        f"# document {document.document_id}",
    ]
    for root in document.trust_root_principal_ids:
        lines.append(f'trust "{root}".')
    for fact in document.facts:
        args = ", ".join(term.value for term in fact.atom.arguments)
        issuer = fact.issuer_principal_id or "system"
        lines.append(
            f'"{issuer}" says {fact.atom.predicate_id}({args});'
        )
    for rule in document.rules:
        issuer = rule.issuer_principal_id or "system"
        head_args = ", ".join(
            (
                term.value
                if term.kind is TermKind.CONSTANT
                else f"?{term.value}"
            )
            for term in rule.head.arguments
        )
        body = " and ".join(
            (
                ("not " if atom.is_negative else "")
                + f"{atom.predicate_id}("
                + ", ".join(
                    (
                        t.value
                        if t.kind is TermKind.CONSTANT
                        else f"?{t.value}"
                    )
                    for t in atom.arguments
                )
                + ")"
            )
            for atom in rule.body
        )
        if body:
            lines.append(
                f'"{issuer}" says {rule.head.predicate_id}({head_args}) if {body};'
                f" effect={rule.effect.value}; rule={rule.rule_id}."
            )
        else:
            lines.append(
                f'"{issuer}" says {rule.head.predicate_id}({head_args});'
                f" effect={rule.effect.value}; rule={rule.rule_id}."
            )
    for delegation in document.delegations:
        parent = (
            f' under "{delegation.parent_delegation_id}"'
            if delegation.parent_delegation_id
            else ""
        )
        lines.append(
            f'"{delegation.issuer_principal_id}" says '
            f'"{delegation.subject_principal_id}" can "{delegation.capability}" '
            f"on {list(delegation.resource_scope)!r} with delegation-depth "
            f"{delegation.delegation_depth}{parent}; id={delegation.delegation_id}."
        )
    lines.append(
        f'query "{query.principal_id}" can "{query.action}" '
        f'on "{query.resource}" id={query.query_id}.'
    )
    evaluator = ReferenceAuthorizationEvaluator()
    decision, _, _ = evaluator.evaluate(document, query)
    lines.append(f"# reference_outcome {decision.outcome.value}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Conformance fixtures
# ---------------------------------------------------------------------------


def build_authorization_fixtures() -> tuple[AuthorizationFixture, ...]:
    """Reviewed allow/deny/conflict/unknown fixtures for engine conformance."""

    from ...ir_core.provenance import SourceRef, SourceSpan

    source = SourceRef(
        ref_id="source:authz-fixtures",
        source_uri="file:///policies/authorization-fixtures.json",
        source_id="authorization-fixtures.json",
        source_revision="git:fixtures",
        content_sha256="b" * 64,
    )
    span = SourceSpan(
        span_id="span:authz-fixtures",
        source_ref_id="source:authz-fixtures",
        start_byte=0,
        end_byte=4096,
        start_line=1,
        start_column=1,
        end_line=200,
        end_column=2,
    )
    mapped = {
        "source_ref_ids": ("source:authz-fixtures",),
        "span_ids": ("span:authz-fixtures",),
    }

    def const(value: str, sort: str = "principal") -> AuthorizationTerm:
        return AuthorizationTerm.constant(value, sort)

    def var(value: str, sort: str = "principal") -> AuthorizationTerm:
        return AuthorizationTerm.variable(value, sort)

    def atom(
        predicate_id: str,
        *args: AuthorizationTerm,
        polarity: AtomPolarity = AtomPolarity.POSITIVE,
    ) -> AuthorizationAtom:
        return AuthorizationAtom(predicate_id, args, polarity)

    base_principals = (
        AuthorizationPrincipal(
            "principal:root", "Root", PrincipalKind.SYSTEM, **mapped
        ),
        AuthorizationPrincipal(
            "principal:alice", "Alice", PrincipalKind.USER, **mapped
        ),
        AuthorizationPrincipal(
            "principal:bob", "Bob", PrincipalKind.USER, **mapped
        ),
        AuthorizationPrincipal(
            "principal:carol", "Carol", PrincipalKind.USER, **mapped
        ),
    )
    roles = (
        AuthorizationRole(
            "role:admin",
            "Administrator",
            member_principal_ids=("principal:alice",),
            **mapped,
        ),
        AuthorizationRole(
            "role:reader",
            "Reader",
            member_principal_ids=("principal:bob",),
            **mapped,
        ),
    )
    predicates = (
        PredicateSignature(
            "pred:role",
            "role",
            2,
            ("principal", "role"),
            is_intensional=False,
            **mapped,
        ),
        PredicateSignature(
            "pred:may",
            "may",
            3,
            ("principal", "action", "resource"),
            is_intensional=True,
            **mapped,
        ),
        PredicateSignature(
            "pred:denied",
            "denied",
            3,
            ("principal", "action", "resource"),
            is_intensional=True,
            **mapped,
        ),
        PredicateSignature(
            "pred:sensitive",
            "sensitive",
            1,
            ("resource",),
            is_intensional=False,
            **mapped,
        ),
    )
    facts = (
        AuthorizationFact(
            "fact:alice-admin",
            atom("pred:role", const("principal:alice"), const("role:admin", "role")),
            issuer_principal_id="principal:root",
            **mapped,
        ),
        AuthorizationFact(
            "fact:bob-reader",
            atom("pred:role", const("principal:bob"), const("role:reader", "role")),
            issuer_principal_id="principal:root",
            **mapped,
        ),
        AuthorizationFact(
            "fact:doc-sensitive",
            atom("pred:sensitive", const("docs/payroll", "resource")),
            issuer_principal_id="principal:root",
            **mapped,
        ),
    )
    rules_common = (
        AuthorizationRule(
            "rule:admin-may-read",
            head=atom(
                "pred:may",
                var("P"),
                const("read", "action"),
                var("R", "resource"),
            ),
            body=(
                atom(
                    "pred:role",
                    var("P"),
                    const("role:admin", "role"),
                ),
            ),
            kind=RuleKind.DATALOG,
            effect=EffectKind.ALLOW,
            stratum=1,
            **mapped,
        ),
        AuthorizationRule(
            "rule:deny-sensitive-non-admin",
            head=atom(
                "pred:denied",
                var("P"),
                const("read", "action"),
                var("R", "resource"),
            ),
            body=(
                atom("pred:sensitive", var("R", "resource")),
                atom(
                    "pred:role",
                    var("P"),
                    const("role:admin", "role"),
                    polarity=AtomPolarity.NEGATIVE,
                ),
            ),
            kind=RuleKind.DATALOG,
            effect=EffectKind.DENY,
            stratum=1,
            **mapped,
        ),
        AuthorizationRule(
            "rule:root-says-service",
            head=atom(
                "pred:may",
                const("principal:carol"),
                const("read", "action"),
                const("docs/public", "resource"),
            ),
            body=(),
            kind=RuleKind.SECPAL_SAYS,
            effect=EffectKind.ALLOW,
            stratum=0,
            issuer_principal_id="principal:root",
            **mapped,
        ),
    )

    def document_for(
        *,
        queries: tuple[DecisionQuery, ...],
        precedence: PrecedencePolicy | None = None,
        extra_rules: tuple[AuthorizationRule, ...] = (),
        extra_facts: tuple[AuthorizationFact, ...] = (),
        delegations: tuple[DelegationStatement, ...] = (),
    ) -> AuthorizationIR:
        return AuthorizationIR(
            sources=(source,),
            spans=(span,),
            principals=base_principals,
            trust_root_principal_ids=("principal:root",),
            roles=roles,
            predicates=predicates,
            facts=facts + extra_facts,
            rules=rules_common + extra_rules,
            delegations=delegations,
            bounds=PolicyBounds(
                max_delegation_depth=4,
                max_derivation_depth=64,
                max_stratum=8,
                universe_size=64,
            ),
            precedence=precedence
            or PrecedencePolicy(resolution="deny_overrides"),
            queries=queries,
            metadata={"fixture_set": "authorization-backends"},
        )

    allow_query = DecisionQuery(
        "query:alice-allow",
        principal_id="principal:alice",
        action="read",
        resource="docs/payroll",
        goal_atom=atom(
            "pred:may",
            const("principal:alice"),
            const("read", "action"),
            const("docs/payroll", "resource"),
        ),
        **mapped,
    )
    deny_query = DecisionQuery(
        "query:bob-deny",
        principal_id="principal:bob",
        action="read",
        resource="docs/payroll",
        **mapped,
    )
    unknown_query = DecisionQuery(
        "query:bob-unknown",
        principal_id="principal:bob",
        action="delete",
        resource="docs/payroll",
        **mapped,
    )
    conflict_query = DecisionQuery(
        "query:conflict",
        principal_id="principal:bob",
        action="read",
        resource="docs/payroll",
        **mapped,
    )
    # Conflict document: force an allow fact for bob plus the deny rule.
    conflict_extra = (
        AuthorizationRule(
            "rule:force-bob-allow",
            head=atom(
                "pred:may",
                const("principal:bob"),
                const("read", "action"),
                const("docs/payroll", "resource"),
            ),
            body=(),
            kind=RuleKind.DATALOG,
            effect=EffectKind.ALLOW,
            stratum=0,
            **mapped,
        ),
    )
    delegation_query = DecisionQuery(
        "query:delegation-bob",
        principal_id="principal:bob",
        action="read",
        resource="docs/public/readme",
        **mapped,
    )
    delegations = (
        DelegationStatement(
            "delegation:root-alice",
            issuer_principal_id="principal:root",
            subject_principal_id="principal:alice",
            capability="read",
            delegation_depth=2,
            resource_scope=("docs/",),
            **mapped,
        ),
        DelegationStatement(
            "delegation:alice-bob",
            issuer_principal_id="principal:alice",
            subject_principal_id="principal:bob",
            capability="read",
            delegation_depth=1,
            parent_delegation_id="delegation:root-alice",
            resource_scope=("docs/public/",),
            **mapped,
        ),
    )

    allow_doc = document_for(queries=(allow_query,))
    deny_doc = document_for(queries=(deny_query,))
    unknown_doc = document_for(queries=(unknown_query,))
    conflict_doc = document_for(
        queries=(conflict_query,),
        precedence=PrecedencePolicy(resolution="explicit_conflict"),
        extra_rules=conflict_extra,
    )
    delegation_doc = document_for(
        queries=(delegation_query,),
        delegations=delegations,
        # No deny rule match for docs/public/readme (not marked sensitive).
        extra_facts=(),
    )

    return (
        AuthorizationFixture(
            "fixture:allow",
            "allow",
            allow_doc,
            allow_query,
            DecisionOutcome.ALLOW,
        ),
        AuthorizationFixture(
            "fixture:deny",
            "deny",
            deny_doc,
            deny_query,
            DecisionOutcome.DENY,
        ),
        AuthorizationFixture(
            "fixture:unknown",
            "unknown",
            unknown_doc,
            unknown_query,
            DecisionOutcome.UNKNOWN,
        ),
        AuthorizationFixture(
            "fixture:conflict",
            "conflict",
            conflict_doc,
            conflict_query,
            DecisionOutcome.CONFLICT,
        ),
        AuthorizationFixture(
            "fixture:delegation",
            "delegation",
            delegation_doc,
            delegation_query,
            DecisionOutcome.ALLOW,
        ),
    )


DEFAULT_AUTHORIZATION_FIXTURES: Final = build_authorization_fixtures()


# ---------------------------------------------------------------------------
# Thin UCAN / supervisor adapters (no registry edits)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupervisorPolicyView:
    """Thin preservation of supervisor finite-policy fields.

    This adapter does not import or mutate the agent-supervisor control plane.
    Callers project supervisor grants into :class:`AuthorizationIR` and evaluate
    them with the reference backend.
    """

    policy_id: str
    trusted_roots: tuple[str, ...]
    statement_ids: tuple[str, ...]
    schema_version: str = SUPERVISOR_ADAPTER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        roots = tuple(_text(item, "trusted_roots item") for item in self.trusted_roots)
        if not roots:
            raise AuthorizationBackendError("trusted_roots must be non-empty")
        object.__setattr__(self, "trusted_roots", roots)
        statements = tuple(
            _text(item, "statement_ids item") for item in self.statement_ids
        )
        object.__setattr__(self, "statement_ids", statements)
        if self.schema_version != SUPERVISOR_ADAPTER_VERSION:
            raise AuthorizationBackendError(
                f"unsupported supervisor adapter schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "statement_ids": list(self.statement_ids),
            "trusted_roots": list(self.trusted_roots),
        }


@dataclass(frozen=True, slots=True)
class UcanCapabilityView:
    """Thin UCAN capability projection over an authorization decision.

    UCAN and authorization remain distinct from theorem proof: a capability
    grant never establishes generated-code correctness.
    """

    capability_id: str
    audience: str
    action: str
    resource: str
    outcome: DecisionOutcome | str
    authority: AuthorizationEvidenceAuthority | str = (
        AuthorizationEvidenceAuthority.AUTHORIZATION
    )
    schema_version: str = UCAN_ADAPTER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "capability_id", _text(self.capability_id, "capability_id")
        )
        object.__setattr__(self, "audience", _text(self.audience, "audience"))
        object.__setattr__(self, "action", _text(self.action, "action"))
        object.__setattr__(self, "resource", _text(self.resource, "resource"))
        object.__setattr__(
            self, "outcome", _enum(self.outcome, DecisionOutcome, "outcome")
        )
        authority = _enum(
            self.authority, AuthorizationEvidenceAuthority, "authority"
        )
        if authority is not AuthorizationEvidenceAuthority.AUTHORIZATION:
            raise AuthorizationBackendError(
                "UCAN capability views cannot claim theorem authority"
            )
        object.__setattr__(self, "authority", authority)
        if self.schema_version != UCAN_ADAPTER_VERSION:
            raise AuthorizationBackendError(
                f"unsupported UCAN adapter schema: {self.schema_version!r}"
            )

    @property
    def is_theorem_authority(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "audience": self.audience,
            "authority": self.authority.value,
            "capability_id": self.capability_id,
            "outcome": self.outcome.value,
            "resource": self.resource,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_decision(
        cls,
        decision: PolicyDecision,
        *,
        audience: str,
        action: str,
        resource: str,
    ) -> UcanCapabilityView:
        return cls(
            capability_id=f"ucan:{decision.decision_id}",
            audience=audience,
            action=action,
            resource=resource,
            outcome=decision.outcome,
        )


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


def _result_id(backend_id: str, request: BackendRequest) -> str:
    return f"result:{backend_id}:{stable_digest({'request': request.digest})[:16]}"


def _extract_document_and_query(
    request: BackendRequest,
) -> tuple[AuthorizationIR, DecisionQuery, str]:
    payload = request.payload.to_dict()
    encoding = str(
        payload.get("encoding")
        or payload.get("source_format")
        or "authorization-ir"
    ).strip().lower()

    raw_document = (
        payload.get("authorization_ir")
        or payload.get("authorization")
        or payload.get("ir")
        or payload.get("document")
    )
    if isinstance(raw_document, AuthorizationIR):
        document = raw_document
    elif isinstance(raw_document, Mapping):
        try:
            document = AuthorizationIR.from_dict(raw_document)
        except (AuthorizationValidationError, TypeError, ValueError) as error:
            raise AuthorizationBackendError(
                f"invalid authorization_ir payload: {error}"
            ) from error
    else:
        raise AuthorizationBackendError(
            "authorization request payload requires authorization_ir"
        )

    raw_query = payload.get("query")
    query_id = payload.get("query_id")
    if isinstance(raw_query, DecisionQuery):
        query = raw_query
    elif isinstance(raw_query, Mapping):
        query = DecisionQuery.from_dict(raw_query)
    elif isinstance(query_id, str) and query_id:
        matches = [item for item in document.queries if item.query_id == query_id]
        if not matches:
            raise AuthorizationBackendError(f"unknown query_id {query_id!r}")
        query = matches[0]
    elif len(document.queries) == 1:
        query = document.queries[0]
    else:
        raise AuthorizationBackendError(
            "payload requires query or query_id when multiple queries exist"
        )
    return document, query, encoding


class _AuthorizationBackendBase:
    """Shared run path for Datalog and SecPAL backends."""

    interface_version: str
    backend_id: str
    aliases: frozenset[str]
    engine_kind: EngineKind
    executable_name: str
    file_suffix: str
    accepted_source_formats: frozenset[str]

    def __init__(
        self,
        *,
        backend_version: str,
        executable: str | None = None,
        runner: BoundedToolRunner | None = None,
        version_probe: Callable[[], str] | None = None,
        available_probe: Callable[[], bool] | None = None,
        use_external_engine: bool = False,
        logic_families: Sequence[str] = (
            "authorization",
            "datalog",
            "secpal",
            "policy",
            "software_verification",
        ),
    ) -> None:
        self.backend_version = _text(backend_version, "backend_version")
        self.executable = _text(
            executable or self.executable_name, "executable"
        )
        self._runner = runner or BoundedToolRunner()
        if not isinstance(self._runner, BoundedToolRunner):
            raise AuthorizationBackendError("runner must be a BoundedToolRunner")
        if version_probe is not None and not callable(version_probe):
            raise AuthorizationBackendError("version_probe must be callable")
        if available_probe is not None and not callable(available_probe):
            raise AuthorizationBackendError("available_probe must be callable")
        self._version_probe = version_probe
        self._available_probe = available_probe
        self.use_external_engine = bool(use_external_engine)
        self._evaluator = ReferenceAuthorizationEvaluator()
        self.capabilities = BackendCapabilities(
            logic_families=tuple(logic_families),
            query_kinds=(QueryKind.POLICY_APPROVAL,),
            deterministic=True,
        )

    def supports(self, logic_family: str, query_kind: QueryKind) -> bool:
        return self.capabilities.supports(logic_family, query_kind)

    def is_available(self) -> bool:
        # Reference path is always available; external engines are optional.
        if not self.use_external_engine:
            return True
        if self._available_probe is not None:
            return bool(self._available_probe())
        return self._runner.is_available(self.executable)

    def render(self, document: AuthorizationIR, query: DecisionQuery) -> str:
        raise NotImplementedError

    def _command(self, model_path: str) -> tuple[str, ...]:
        return (self.executable, model_path)

    def _validate_request(self, request: BackendRequest) -> None:
        if not isinstance(request, BackendRequest):
            raise AuthorizationBackendError("request must be a BackendRequest")
        if request.requested_backend_id and request.requested_backend_id not in {
            self.backend_id,
            *self.aliases,
        }:
            raise AuthorizationBackendError(
                f"request targets {request.requested_backend_id!r}, "
                f"not {self.backend_id!r}"
            )
        if not self.capabilities.supports(request.logic_family, request.query_kind):
            raise AuthorizationBackendError(
                f"{self.backend_id} does not support {request.logic_family}/"
                f"{request.query_kind.value}"
            )
        if request.query_kind is not QueryKind.POLICY_APPROVAL:
            raise AuthorizationBackendError(
                "authorization backends answer policy_approval queries only"
            )

    def _run_external(
        self,
        document: AuthorizationIR,
        query: DecisionQuery,
        bounds: ExecutionBounds,
        cancellation: CancellationSignal | Any | None,
    ) -> tuple[DecisionOutcome | None, ResourceUsage, tuple[str, ...]]:
        source = self.render(document, query)
        max_workspace_bytes = max(
            bounds.max_output_bytes * 2,
            len(source.encode("utf-8")) + bounds.max_output_bytes + 1024,
        )
        tool_request = ToolRunRequest(
            argv=self._command(f"{{workspace}}/policy.{self.file_suffix}"),
            runtime=ToolRuntime.NATIVE,
            limits=ToolRunLimits(
                timeout_seconds=bounds.timeout_ms / 1000,
                cpu_seconds=bounds.timeout_ms / 1000,
                memory_bytes=bounds.max_memory_bytes,
                max_output_bytes=bounds.max_output_bytes,
                max_input_bytes=bounds.max_output_bytes,
                max_workspace_bytes=max_workspace_bytes,
            ),
            input_files={f"policy.{self.file_suffix}": source},
        )
        try:
            tool_result = self._runner.run(tool_request, cancellation=cancellation)
        except Exception as exc:  # pragma: no cover - defensive
            return None, ResourceUsage(), bound_diagnostics([type(exc).__name__])
        usage = ResourceUsage(
            elapsed_ms=max(0, int(tool_result.elapsed_seconds * 1000)),
            output_bytes=len(tool_result.stdout.encode("utf-8", errors="replace")),
        )
        diagnostics = bound_diagnostics(
            [
                item
                for item in (tool_result.stderr, tool_result.error)
                if item
            ]
        )
        if (
            tool_result.timed_out
            or tool_result.unavailable
            or tool_result.returncode not in {0, None}
            and tool_result.returncode != 0
        ):
            # Empty successful Soufflé runs may still encode deny.
            if tool_result.returncode == 0 and not tool_result.timed_out:
                outcome = parse_engine_outcome(tool_result.stdout, tool_result.stderr)
                return outcome, usage, diagnostics
            return None, usage, diagnostics
        outcome = parse_engine_outcome(tool_result.stdout, tool_result.stderr)
        return outcome, usage, diagnostics

    def evaluate_reference(
        self,
        document: AuthorizationIR,
        query: DecisionQuery | str | None = None,
        *,
        max_steps: int | None = None,
    ) -> tuple[PolicyDecision, DecisionExplanation, bool]:
        return self._evaluator.evaluate(document, query, max_steps=max_steps)

    def check_conformance(
        self,
        fixtures: Sequence[AuthorizationFixture] | None = None,
        *,
        engine_runner: Callable[
            [AuthorizationIR, DecisionQuery], DecisionOutcome | None
        ]
        | None = None,
    ) -> EngineConformanceReceipt:
        selected = tuple(fixtures or DEFAULT_AUTHORIZATION_FIXTURES)
        checked: list[str] = []
        disagreements: list[str] = []
        errored = False
        for fixture in selected:
            checked.append(fixture.fixture_id)
            reference, _, _ = self._evaluator.evaluate(
                fixture.document, fixture.query
            )
            if reference.outcome is not fixture.expected_outcome:
                disagreements.append(fixture.fixture_id)
                continue
            if engine_runner is None:
                continue
            observed = engine_runner(fixture.document, fixture.query)
            if observed is None:
                errored = True
                disagreements.append(fixture.fixture_id)
            elif observed is not fixture.expected_outcome:
                disagreements.append(fixture.fixture_id)
        if disagreements:
            status = ConformanceStatus.ERROR if errored else ConformanceStatus.FAILED
            reason = "engine did not agree on every authorization fixture"
        else:
            status = ConformanceStatus.PASSED
            reason = "reference and optional engine agreed on every fixture"
        return EngineConformanceReceipt(
            engine=self.engine_kind if engine_runner else EngineKind.REFERENCE,
            status=status,
            checked_fixture_ids=tuple(checked),
            disagreements=tuple(disagreements),
            reason=reason,
        )

    def _build_result(
        self,
        *,
        request: BackendRequest,
        binding: AuthorizationSourceBinding,
        status: ResultStatus,
        usage: ResourceUsage,
        receipt: EvaluationReceipt,
        reason: str = "",
        diagnostics: Sequence[str] = (),
    ) -> AuthorizationResult:
        witness: dict[str, Any] = {
            "receipt_id": receipt.receipt_id,
            "outcome": receipt.outcome.value,
            "engine": receipt.engine.value,
            "engine_agreed": receipt.engine_agreed,
            "bounds_exhausted": receipt.bounds_exhausted,
            "authority": receipt.authority.value,
            "generated_code_correctness": receipt.generated_code_correctness.value,
            "is_theorem_authority": False,
        }
        if receipt.explanation is not None:
            witness["explanation"] = receipt.explanation.to_dict()
            witness["bound_rule_ids"] = [
                step.reference_id
                for step in receipt.explanation.steps
                if step.kind is ExplanationStepKind.RULE
            ]
        if receipt.decision is not None:
            witness["decision"] = receipt.decision.to_dict()
        if receipt.engine_outcome is not None:
            witness["engine_outcome"] = receipt.engine_outcome.value
        return AuthorizationResult(
            result_id=_result_id(self.backend_id, request),
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            authority=ResultAuthority.AUTHORIZATION,
            status=status,
            assumptions=request.assumption_ids,
            bounds=request.bounds,
            translation_ceiling=EvidenceAuthority.NONE,
            usage=usage,
            witness=witness,
            diagnostics=bound_diagnostics(diagnostics),
            reason=_sanitize_diagnostic(reason) if reason else "",
            metadata={
                "adapter_interface": self.interface_version,
                "evaluation_receipt": receipt.to_dict(),
                "source_binding": binding.to_dict(),
                "authorization_authority_ceiling": (
                    AuthorizationEvidenceAuthority.AUTHORIZATION.value
                ),
            },
        )

    def run(
        self,
        request: BackendRequest,
        *,
        cancellation: CancellationSignal | Any | None = None,
    ) -> AuthorizationBackendOutcome:
        self._validate_request(request)
        document, query, encoding = _extract_document_and_query(request)
        if encoding not in self.accepted_source_formats:
            raise AuthorizationBackendError(
                f"request encoding {encoding!r} is not supported by {self.backend_id}"
            )
        binding = AuthorizationSourceBinding.bind(
            request, document, query, source_format=encoding
        )
        decision, explanation, bounds_exhausted = self._evaluator.evaluate(
            document,
            query,
            max_steps=request.bounds.max_steps,
        )
        usage = ResourceUsage(steps=1)
        engine_outcome: DecisionOutcome | None = None
        engine = EngineKind.REFERENCE
        diagnostics: list[str] = []
        if self.use_external_engine and self.is_available():
            engine = self.engine_kind
            engine_outcome, external_usage, external_diag = self._run_external(
                document, query, request.bounds, cancellation
            )
            usage = ResourceUsage(
                elapsed_ms=external_usage.elapsed_ms,
                steps=max(1, external_usage.steps),
                peak_memory_bytes=external_usage.peak_memory_bytes,
                output_bytes=external_usage.output_bytes,
            )
            diagnostics.extend(external_diag)

        engine_agreed = True
        outcome = decision.outcome
        status = outcome_to_result_status(outcome)
        reason = f"reference evaluator returned {outcome.value}"
        if engine is not EngineKind.REFERENCE:
            if engine_outcome is None:
                engine_agreed = False
                status = ResultStatus.UNAVAILABLE
                reason = "external authorization engine failed or is unavailable"
                diagnostics.append("external engine produced no parseable outcome")
            elif engine_outcome is not decision.outcome:
                engine_agreed = False
                status = ResultStatus.UNKNOWN
                reason = (
                    "external engine disagreed with the reference evaluator; "
                    "quarantining conclusive authority"
                )
                diagnostics.append(
                    f"reference={decision.outcome.value} engine={engine_outcome.value}"
                )
            else:
                reason = (
                    f"reference and {engine.value} engine agreed on {outcome.value}"
                )

        if bounds_exhausted and outcome is DecisionOutcome.UNKNOWN:
            reason = "authorization derivation bounds exhausted"
            diagnostics.append("bounds_exhausted")

        # Hard authority ceiling: never emit theorem-shaped results.
        if status in {ResultStatus.PROVED, ResultStatus.DISPROVED}:
            raise AuthorizationBackendError(
                "authorization backend attempted to emit theorem authority"
            )

        receipt = EvaluationReceipt(
            request_digest=request.digest,
            source_binding=binding,
            outcome=outcome,
            decision=decision,
            explanation=explanation,
            engine=engine,
            engine_outcome=engine_outcome,
            engine_agreed=engine_agreed,
            bounds_exhausted=bounds_exhausted,
            diagnostics=tuple(diagnostics),
        )
        result = self._build_result(
            request=request,
            binding=binding,
            status=status,
            usage=usage,
            receipt=receipt,
            reason=reason,
            diagnostics=diagnostics,
        )
        return AuthorizationBackendOutcome(
            result=result,
            receipt=receipt,
            source_binding=binding,
        )


class DatalogAuthorizationBackend(_AuthorizationBackendBase):
    """Canonical Datalog authorization backend (``DatalogAuthorizationBackend@1``)."""

    interface_version = DATALOG_AUTHORIZATION_BACKEND_VERSION
    backend_id = "datalog-authorization"
    aliases = frozenset(
        {
            "datalog",
            "souffle",
            "authorization-datalog",
            "datalog-authz",
        }
    )
    engine_kind = EngineKind.DATALOG
    executable_name = "souffle"
    file_suffix = "dl"
    accepted_source_formats = frozenset(
        {
            "authorization-ir",
            "authorization_ir",
            "authorization",
            "datalog",
            "souffle",
            "dl",
        }
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            backend_version=kwargs.pop("backend_version", "datalog-authorization/v1"),
            **kwargs,
        )

    def render(self, document: AuthorizationIR, query: DecisionQuery) -> str:
        return render_datalog_program(document, query)


class SecPALAuthorizationBackend(_AuthorizationBackendBase):
    """Canonical SecPAL-style authorization backend (``SecPALAuthorizationBackend@1``)."""

    interface_version = SECPAL_AUTHORIZATION_BACKEND_VERSION
    backend_id = "secpal-authorization"
    aliases = frozenset(
        {
            "secpal",
            "authorization-secpal",
            "secpal-authz",
        }
    )
    engine_kind = EngineKind.SECPAL
    executable_name = "secpal"
    file_suffix = "secpal"
    accepted_source_formats = frozenset(
        {
            "authorization-ir",
            "authorization_ir",
            "authorization",
            "secpal",
        }
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            backend_version=kwargs.pop("backend_version", "secpal-authorization/v1"),
            **kwargs,
        )

    def _command(self, model_path: str) -> tuple[str, ...]:
        return (self.executable, "check", model_path)

    def render(self, document: AuthorizationIR, query: DecisionQuery) -> str:
        return render_secpal_program(document, query)


__all__ = [
    "AUTHORIZATION_ADAPTERS_VERSION",
    "AuthorizationBackendError",
    "AuthorizationBackendOutcome",
    "AuthorizationFixture",
    "AuthorizationSourceBinding",
    "ConformanceStatus",
    "DATALOG_AUTHORIZATION_BACKEND_VERSION",
    "DEFAULT_AUTHORIZATION_FIXTURES",
    "DatalogAuthorizationBackend",
    "EngineConformanceReceipt",
    "EngineKind",
    "EngineSupportStatus",
    "EvaluationReceipt",
    "ReferenceAuthorizationEvaluator",
    "SECPAL_AUTHORIZATION_BACKEND_VERSION",
    "SecPALAuthorizationBackend",
    "SupervisorPolicyView",
    "UcanCapabilityView",
    "bound_diagnostics",
    "build_authorization_fixtures",
    "outcome_to_result_status",
    "parse_engine_outcome",
    "render_datalog_program",
    "render_secpal_program",
]
