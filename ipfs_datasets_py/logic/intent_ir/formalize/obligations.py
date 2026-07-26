"""Bounded proof obligations and backend execution for Intent formalizations.

This module is the authority boundary between deterministic formalization and
proof execution.  It derives theorem-shaped obligations from a
``FormalizationArtifact``, keeps every premise explicit, and delegates only to
the shared bounded backend registry.  Retrieved GraphRAG context is never
promoted to a proof premise.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ...backends.registry import (
    BackendRegistryError,
    ProofBackendRegistry,
    UnsupportedBackendRequest,
)
from ...formalization.compiler import FormalizationArtifact
from ...ir_core.claims import FrozenMap, IRClaim, ProofObligation
from ...ir_core.protocols import (
    AttemptStatus,
    AuthorityKind,
    BackendAttempt,
    BackendRequest,
    BoundedResult,
    ExecutionBounds,
    ProofResult,
    QueryKind,
    ResultStatus,
)
from .compiler import (
    INTENT_ACTION_VIEW_ID,
    INTENT_FAILURE_VIEW_ID,
    INTENT_INVARIANT_VIEW_ID,
    INTENT_MODAL_VIEW_ID,
    INTENT_VERIFICATION_VIEW_ID,
    INTENT_WORKFLOW_VIEW_ID,
)


INTENT_PROOF_OBLIGATIONS_VERSION: Final = "intent-proof-obligations/v1"
INTENT_SEMANTIC_ENCODING: Final = "intent-semantic-obligation/v1"


class IntentProofObligationError(ValueError):
    """Raised when a bounded, source-grounded proof packet cannot be built."""


class IntentObligationKind(str, Enum):
    """Semantic property checked by an Intent obligation."""

    SAFETY = "safety"
    LIVENESS = "liveness"
    MODALITY = "modality"
    ACTION_EFFECT = "action_effect"
    CONTROL_FLOW = "control_flow"
    ACTION_ORDER = "control_flow"
    GUARD = "guard"
    VERIFICATION = "verification"


class IntentProofDisposition(str, Enum):
    """Normalized terminal outcome of one proof attempt."""

    POSITIVE = "positive"
    COUNTEREXAMPLE = "counterexample"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    ERROR = "error"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:32]}"


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if isinstance(value, FrozenMap):
        return value.to_dict()
    if not isinstance(value, Mapping):
        raise IntentProofObligationError(f"{field_name} must be a mapping")
    return dict(value)


@dataclass(frozen=True, slots=True)
class IntentProofAuthorityPolicy:
    """Explicit policy for premises and authoritative backend verdicts.

    An empty ``accepted_backend_ids`` tuple means that any registered issuer is
    acceptable.  It does not bypass the result's exact authority-kind and
    request bindings, which are enforced by the shared registry.
    """

    accepted_backend_ids: tuple[str, ...] = ()
    accepted_authority_kinds: tuple[AuthorityKind, ...] = (
        AuthorityKind.THEOREM_PROOF,
    )
    allow_context_assumptions: bool = False
    require_source_grounding: bool = True
    max_obligations: int = 256
    schema_version: str = INTENT_PROOF_OBLIGATIONS_VERSION

    def __post_init__(self) -> None:
        backend_ids = tuple(self.accepted_backend_ids)
        if any(
            not isinstance(item, str) or not item.strip() or item != item.strip()
            for item in backend_ids
        ):
            raise IntentProofObligationError(
                "accepted_backend_ids must contain trimmed non-empty strings"
            )
        if len(backend_ids) != len(set(backend_ids)):
            raise IntentProofObligationError(
                "accepted_backend_ids must not contain duplicates"
            )
        object.__setattr__(self, "accepted_backend_ids", tuple(sorted(backend_ids)))
        try:
            authority_kinds = tuple(
                item if isinstance(item, AuthorityKind) else AuthorityKind(item)
                for item in self.accepted_authority_kinds
            )
        except (TypeError, ValueError) as exc:
            raise IntentProofObligationError(
                "accepted_authority_kinds contains an unknown authority"
            ) from exc
        if not authority_kinds or len(authority_kinds) != len(set(authority_kinds)):
            raise IntentProofObligationError(
                "accepted_authority_kinds must be non-empty and unique"
            )
        object.__setattr__(
            self,
            "accepted_authority_kinds",
            tuple(sorted(authority_kinds, key=lambda item: item.value)),
        )
        if not isinstance(self.allow_context_assumptions, bool):
            raise IntentProofObligationError(
                "allow_context_assumptions must be a boolean"
            )
        if not isinstance(self.require_source_grounding, bool):
            raise IntentProofObligationError(
                "require_source_grounding must be a boolean"
            )
        if (
            isinstance(self.max_obligations, bool)
            or not isinstance(self.max_obligations, int)
            or self.max_obligations <= 0
        ):
            raise IntentProofObligationError(
                "max_obligations must be a positive integer"
            )
        if self.schema_version != INTENT_PROOF_OBLIGATIONS_VERSION:
            raise IntentProofObligationError(
                f"unsupported authority policy schema: {self.schema_version}"
            )

    def permits_assumption(self, metadata: Mapping[str, Any]) -> bool:
        """Return whether an assumption may participate in a proof request."""

        authority = metadata.get("authority", "")
        proof_authority = metadata.get("proof_authority")
        is_context = authority == "context_only" or proof_authority is False
        return self.allow_context_assumptions or not is_context

    def accepts_result(self, result: BoundedResult) -> bool:
        """Check issuer and exact authority kind; never infer authority by status."""

        return (
            result.authority.kind in self.accepted_authority_kinds
            and (
                not self.accepted_backend_ids
                or result.backend_id in self.accepted_backend_ids
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_authority_kinds": [
                item.value for item in self.accepted_authority_kinds
            ],
            "accepted_backend_ids": list(self.accepted_backend_ids),
            "allow_context_assumptions": self.allow_context_assumptions,
            "max_obligations": self.max_obligations,
            "require_source_grounding": self.require_source_grounding,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "IntentProofAuthorityPolicy":
        payload = _mapping(value, "authority policy")
        allowed = {
            "accepted_authority_kinds",
            "accepted_backend_ids",
            "allow_context_assumptions",
            "max_obligations",
            "require_source_grounding",
            "schema_version",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise IntentProofObligationError(
                "unknown authority policy field(s): " + ", ".join(unknown)
            )
        return cls(
            accepted_backend_ids=tuple(
                payload.get("accepted_backend_ids", ())
            ),
            accepted_authority_kinds=tuple(
                payload.get(
                    "accepted_authority_kinds",
                    (AuthorityKind.THEOREM_PROOF.value,),
                )
            ),
            allow_context_assumptions=payload.get(
                "allow_context_assumptions", False
            ),
            require_source_grounding=payload.get(
                "require_source_grounding", True
            ),
            max_obligations=payload.get("max_obligations", 256),
            schema_version=payload.get(
                "schema_version", INTENT_PROOF_OBLIGATIONS_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class IntentProofPacket:
    """Immutable claim and bounded requests generated from one artifact."""

    artifact_digest: str
    claim: IRClaim
    requests: tuple[BackendRequest, ...]
    obligation_kinds: FrozenMap
    authority_policy: IntentProofAuthorityPolicy
    schema_version: str = INTENT_PROOF_OBLIGATIONS_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.artifact_digest, str)
            or not self.artifact_digest.startswith("sha256:")
            or len(self.artifact_digest) != 71
        ):
            raise IntentProofObligationError(
                "artifact_digest must be a sha256:<hex> digest"
            )
        if not isinstance(self.claim, IRClaim):
            raise IntentProofObligationError("claim must be an IRClaim")
        if not isinstance(self.authority_policy, IntentProofAuthorityPolicy):
            raise IntentProofObligationError(
                "authority_policy must be an IntentProofAuthorityPolicy"
            )
        requests = tuple(self.requests)
        if not all(isinstance(item, BackendRequest) for item in requests):
            raise IntentProofObligationError(
                "requests must contain BackendRequest values"
            )
        if len(requests) > self.authority_policy.max_obligations:
            raise IntentProofObligationError("proof packet exceeds max_obligations")
        request_obligations = [item.obligation_id for item in requests]
        if len(request_obligations) != len(set(request_obligations)):
            raise IntentProofObligationError(
                "proof packet must contain one request per obligation"
            )
        known = {item.obligation_id for item in self.claim.obligations}
        if set(request_obligations) != known:
            raise IntentProofObligationError(
                "proof requests must exactly cover claim obligations"
            )
        object.__setattr__(self, "requests", tuple(sorted(
            requests, key=lambda item: item.obligation_id
        )))
        object.__setattr__(
            self,
            "obligation_kinds",
            self.obligation_kinds
            if isinstance(self.obligation_kinds, FrozenMap)
            else FrozenMap(self.obligation_kinds),
        )
        if set(self.obligation_kinds) != known:
            raise IntentProofObligationError(
                "obligation_kinds must exactly cover claim obligations"
            )
        if self.schema_version != INTENT_PROOF_OBLIGATIONS_VERSION:
            raise IntentProofObligationError(
                f"unsupported proof packet schema: {self.schema_version}"
            )

    @property
    def assumptions(self) -> tuple[Any, ...]:
        return self.claim.assumptions

    @property
    def obligations(self) -> tuple[ProofObligation, ...]:
        return self.claim.obligations

    def request_for(self, obligation_id: str) -> BackendRequest:
        for request in self.requests:
            if request.obligation_id == obligation_id:
                return request
        raise KeyError(obligation_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_digest": self.artifact_digest,
            "authority_policy": self.authority_policy.to_dict(),
            "claim": self.claim.to_dict(),
            "obligation_kinds": self.obligation_kinds.to_dict(),
            "requests": [item.to_dict() for item in self.requests],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntentProofPacket":
        payload = _mapping(value, "proof packet")
        allowed = {
            "artifact_digest",
            "authority_policy",
            "claim",
            "obligation_kinds",
            "requests",
            "schema_version",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise IntentProofObligationError(
                "unknown proof packet field(s): " + ", ".join(unknown)
            )
        requests = payload.get("requests", ())
        if (
            isinstance(requests, (str, bytes, bytearray))
            or not isinstance(requests, Sequence)
        ):
            raise IntentProofObligationError(
                "proof packet requests must be a sequence"
            )
        return cls(
            artifact_digest=payload.get("artifact_digest", ""),
            claim=IRClaim.from_dict(
                _mapping(payload.get("claim", {}), "claim")
            ),
            requests=tuple(
                BackendRequest.from_dict(item) for item in requests
            ),
            obligation_kinds=FrozenMap(
                _mapping(
                    payload.get("obligation_kinds", {}),
                    "obligation_kinds",
                )
            ),
            authority_policy=IntentProofAuthorityPolicy.from_dict(
                _mapping(
                    payload.get("authority_policy", {}),
                    "authority_policy",
                )
            ),
            schema_version=payload.get(
                "schema_version", INTENT_PROOF_OBLIGATIONS_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class IntentProofOutcome:
    """One normalized backend or local unsupported outcome."""

    obligation_id: str
    disposition: IntentProofDisposition
    authoritative: bool
    attempt: BackendAttempt | None = None
    result: BoundedResult | None = None
    diagnostics: tuple[str, ...] = ()

    @property
    def positive(self) -> bool:
        return (
            self.disposition is IntentProofDisposition.POSITIVE
            and self.authoritative
        )

    @property
    def counterexample(self) -> bool:
        return self.disposition is IntentProofDisposition.COUNTEREXAMPLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt.to_dict() if self.attempt else None,
            "authoritative": self.authoritative,
            "diagnostics": list(self.diagnostics),
            "disposition": self.disposition.value,
            "obligation_id": self.obligation_id,
            "result": self.result.to_dict() if self.result else None,
        }


@dataclass(frozen=True, slots=True)
class IntentProofExecution:
    """Results for a packet; partial/unknown paths never count as success."""

    packet: IntentProofPacket
    outcomes: tuple[IntentProofOutcome, ...]

    def __post_init__(self) -> None:
        outcomes = tuple(sorted(
            self.outcomes, key=lambda item: item.obligation_id
        ))
        expected = {item.obligation_id for item in self.packet.obligations}
        actual = {item.obligation_id for item in outcomes}
        if actual != expected or len(actual) != len(outcomes):
            raise IntentProofObligationError(
                "execution outcomes must exactly cover packet obligations"
            )
        object.__setattr__(self, "outcomes", outcomes)

    @property
    def passed(self) -> bool:
        return bool(self.outcomes) and all(item.positive for item in self.outcomes)

    def outcome_for(self, obligation_id: str) -> IntentProofOutcome:
        for outcome in self.outcomes:
            if outcome.obligation_id == obligation_id:
                return outcome
        raise KeyError(obligation_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcomes": [item.to_dict() for item in self.outcomes],
            "packet": self.packet.to_dict(),
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class _ObligationSpec:
    kind: IntentObligationKind
    semantic_id: str
    formula_id: str
    logic_family: str
    statement: Mapping[str, Any]
    assumption_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    supported: bool


class IntentProofObligations:
    """Generate and execute explicit bounded Intent proof obligations."""

    version: Final = INTENT_PROOF_OBLIGATIONS_VERSION

    def __init__(
        self,
        authority_policy: IntentProofAuthorityPolicy | None = None,
    ) -> None:
        self.authority_policy = authority_policy or IntentProofAuthorityPolicy()

    def generate(
        self,
        artifact: FormalizationArtifact,
        *,
        bounds: ExecutionBounds | None = None,
        requested_backend_id: str = "",
        authority_policy: IntentProofAuthorityPolicy | None = None,
    ) -> IntentProofPacket:
        """Derive a deterministic claim and one bounded request per obligation."""

        if not isinstance(artifact, FormalizationArtifact):
            raise IntentProofObligationError(
                "artifact must be a FormalizationArtifact"
            )
        if artifact.domain != "intent":
            raise IntentProofObligationError(
                "Intent obligations require an intent formalization artifact"
            )
        policy = authority_policy or self.authority_policy
        if not isinstance(policy, IntentProofAuthorityPolicy):
            raise IntentProofObligationError(
                "authority_policy must be an IntentProofAuthorityPolicy"
            )
        execution_bounds = bounds or ExecutionBounds()
        if not isinstance(execution_bounds, ExecutionBounds):
            raise IntentProofObligationError("bounds must be ExecutionBounds")

        eligible_assumptions = tuple(
            item
            for item in artifact.assumptions
            if policy.permits_assumption(item.metadata)
        )
        eligible_ids = {item.assumption_id for item in eligible_assumptions}
        declared_ids = {
            item.assumption_id
            for item in eligible_assumptions
            if item.metadata.get("kind") == "assumption"
        }
        specs = self._specs(
            artifact,
            eligible_assumption_ids=eligible_ids,
            declared_assumption_ids=declared_ids,
        )
        if not specs:
            raise IntentProofObligationError(
                "artifact has no proof-relevant Intent semantics"
            )
        if len(specs) > policy.max_obligations:
            raise IntentProofObligationError(
                f"generated {len(specs)} obligations, exceeding "
                f"max_obligations={policy.max_obligations}"
            )

        obligations: list[ProofObligation] = []
        kinds: dict[str, str] = {}
        for spec in specs:
            obligation_id = _stable_id(
                f"obligation:intent:{spec.kind.value}",
                artifact.digest,
                spec.formula_id,
                spec.semantic_id,
            )
            if policy.require_source_grounding and not spec.source_refs:
                raise IntentProofObligationError(
                    f"obligation for {spec.semantic_id} is not source-grounded"
                )
            obligation = ProofObligation(
                obligation_id=obligation_id,
                statement=_canonical_json(spec.statement),
                assumption_ids=spec.assumption_ids,
                logic_family=spec.logic_family,
                source_refs=spec.source_refs,
                metadata={
                    "artifact_digest": artifact.digest,
                    "encoding": INTENT_SEMANTIC_ENCODING,
                    "formula_id": spec.formula_id,
                    "intent_semantic_id": spec.semantic_id,
                    "obligation_kind": spec.kind.value,
                    "opaque_semantics": not spec.supported,
                    "retrieved_premises_excluded": not policy.allow_context_assumptions,
                    "schema_version": self.version,
                },
            )
            obligations.append(obligation)
            kinds[obligation_id] = spec.kind.value

        claim = IRClaim(
            claim_id=_stable_id("claim:intent", artifact.digest),
            statement=f"Intent semantic obligations for {artifact.declaration_id}",
            assumptions=eligible_assumptions,
            obligations=tuple(sorted(
                obligations, key=lambda item: item.obligation_id
            )),
            domain="intent",
            declaration_id=artifact.declaration_id,
            source_refs=tuple(
                sorted(item.ref_id for item in artifact.source_map.sources)
            ),
            metadata={
                "artifact_digest": artifact.digest,
                "authority_policy": policy.to_dict(),
                "schema_version": self.version,
            },
        )
        requests = tuple(
            BackendRequest.for_claim(
                claim,
                obligation.obligation_id,
                request_id=_stable_id(
                    "request:intent",
                    claim.digest,
                    obligation.obligation_id,
                    requested_backend_id or "auto",
                ),
                query_kind=QueryKind.THEOREM_PROOF,
                bounds=execution_bounds,
                payload={
                    "encoding": INTENT_SEMANTIC_ENCODING,
                    "semantic_obligation": json.loads(obligation.statement),
                    "source_ref_ids": list(obligation.source_refs),
                },
                requested_backend_id=requested_backend_id,
            )
            for obligation in claim.obligations
        )
        return IntentProofPacket(
            artifact_digest=artifact.digest,
            claim=claim,
            requests=requests,
            obligation_kinds=FrozenMap(kinds),
            authority_policy=policy,
        )

    build = generate

    def execute(
        self,
        packet: IntentProofPacket,
        registry: ProofBackendRegistry,
        *,
        backend_id: str | None = None,
    ) -> IntentProofExecution:
        """Execute every request, normalizing every terminal backend path."""

        if not isinstance(packet, IntentProofPacket):
            raise IntentProofObligationError("packet must be an IntentProofPacket")
        if not isinstance(registry, ProofBackendRegistry):
            raise IntentProofObligationError(
                "registry must be a ProofBackendRegistry"
            )
        outcomes: list[IntentProofOutcome] = []
        obligations = {
            item.obligation_id: item for item in packet.obligations
        }
        for request in packet.requests:
            obligation = obligations[request.obligation_id]
            if obligation.metadata.get("opaque_semantics") is True:
                outcomes.append(
                    IntentProofOutcome(
                        obligation_id=request.obligation_id,
                        disposition=IntentProofDisposition.UNSUPPORTED,
                        authoritative=False,
                        diagnostics=(
                            "opaque Intent semantics cannot be submitted as a theorem",
                        ),
                    )
                )
                continue
            try:
                attempt, result = registry.run(request, backend_id=backend_id)
            except UnsupportedBackendRequest as exc:
                outcomes.append(
                    IntentProofOutcome(
                        obligation_id=request.obligation_id,
                        disposition=IntentProofDisposition.UNSUPPORTED,
                        authoritative=False,
                        diagnostics=(str(exc),),
                    )
                )
                continue
            except BackendRegistryError as exc:
                outcomes.append(
                    IntentProofOutcome(
                        obligation_id=request.obligation_id,
                        disposition=IntentProofDisposition.ERROR,
                        authoritative=False,
                        diagnostics=(str(exc),),
                    )
                )
                continue
            outcomes.append(
                self._outcome(
                    request.obligation_id,
                    attempt,
                    result,
                    packet.authority_policy,
                )
            )
        return IntentProofExecution(packet=packet, outcomes=tuple(outcomes))

    prove = execute

    @staticmethod
    def _outcome(
        obligation_id: str,
        attempt: BackendAttempt,
        result: BoundedResult,
        policy: IntentProofAuthorityPolicy,
    ) -> IntentProofOutcome:
        classification = str(result.payload.get("solver_result", ""))
        if attempt.status is AttemptStatus.TIMED_OUT:
            disposition = IntentProofDisposition.TIMEOUT
        elif attempt.status is AttemptStatus.UNAVAILABLE:
            disposition = IntentProofDisposition.UNAVAILABLE
        elif classification == "unsupported":
            disposition = IntentProofDisposition.UNSUPPORTED
        elif result.status is ResultStatus.PROVED:
            disposition = IntentProofDisposition.POSITIVE
        elif result.status is ResultStatus.DISPROVED:
            disposition = IntentProofDisposition.COUNTEREXAMPLE
        elif result.status is ResultStatus.UNKNOWN:
            disposition = IntentProofDisposition.UNKNOWN
        else:
            disposition = IntentProofDisposition.ERROR
        authoritative = (
            isinstance(result, ProofResult)
            and result.status in {ResultStatus.PROVED, ResultStatus.DISPROVED}
            and attempt.status is AttemptStatus.SUCCEEDED
            and policy.accepts_result(result)
        )
        return IntentProofOutcome(
            obligation_id=obligation_id,
            disposition=disposition,
            authoritative=authoritative,
            attempt=attempt,
            result=result,
            diagnostics=tuple(
                dict.fromkeys((*attempt.diagnostics, *result.diagnostics))
            ),
        )

    @staticmethod
    def _specs(
        artifact: FormalizationArtifact,
        *,
        eligible_assumption_ids: set[str],
        declared_assumption_ids: set[str],
    ) -> tuple[_ObligationSpec, ...]:
        specs: list[_ObligationSpec] = []

        def add(
            formula: Any,
            kind: IntentObligationKind,
            semantic_id: str,
            statement: Mapping[str, Any],
            *,
            logic_family: str | None = None,
        ) -> None:
            assumptions = tuple(sorted(
                (
                    set(formula.assumption_ids)
                    | declared_assumption_ids
                )
                & eligible_assumption_ids
            ))
            specs.append(
                _ObligationSpec(
                    kind=kind,
                    semantic_id=semantic_id,
                    formula_id=formula.formula_id,
                    logic_family=logic_family
                    or artifact.view_registry[formula.view_id].logic_family,
                    statement={
                        "formula": _mapping(formula.expression, "formula expression"),
                        "formula_id": formula.formula_id,
                        "kind": kind.value,
                        "semantic_id": semantic_id,
                    },
                    assumption_ids=assumptions,
                    source_refs=formula.source_ref_ids,
                    supported=not formula.opaque,
                )
            )

        for formula in artifact.formulas:
            expression = _mapping(formula.expression, "formula expression")
            node_ids = tuple(formula.metadata.get("intent_node_ids", ()))
            semantic_id = str(node_ids[0] if node_ids else formula.formula_id)
            if formula.view_id == INTENT_MODAL_VIEW_ID:
                body = _mapping(expression.get("body", {}), "modal body")
                if body.get("statement_kind") == "goal":
                    add(
                        formula,
                        IntentObligationKind.LIVENESS,
                        semantic_id,
                        expression,
                        logic_family="first_order_temporal",
                    )
                add(
                    formula,
                    IntentObligationKind.MODALITY,
                    semantic_id,
                    expression,
                )
            elif formula.view_id == INTENT_ACTION_VIEW_ID:
                add(
                    formula,
                    IntentObligationKind.ACTION_EFFECT,
                    semantic_id,
                    expression,
                )
            elif formula.view_id == INTENT_WORKFLOW_VIEW_ID:
                if expression.get("kind") == "workflow_boundary":
                    add(
                        formula,
                        IntentObligationKind.LIVENESS,
                        semantic_id,
                        expression,
                        logic_family="first_order_temporal",
                    )
                elif expression.get("kind") == "workflow_temporal_transition":
                    add(
                        formula,
                        IntentObligationKind.CONTROL_FLOW,
                        semantic_id,
                        expression,
                        logic_family="first_order_temporal",
                    )
                    if expression.get("guard") is not None:
                        add(
                            formula,
                            IntentObligationKind.GUARD,
                            semantic_id,
                            expression,
                            logic_family="first_order_temporal",
                        )
            elif formula.view_id in {
                INTENT_INVARIANT_VIEW_ID,
                INTENT_FAILURE_VIEW_ID,
            }:
                add(
                    formula,
                    IntentObligationKind.SAFETY,
                    semantic_id,
                    expression,
                )
            elif formula.view_id == INTENT_VERIFICATION_VIEW_ID:
                add(
                    formula,
                    IntentObligationKind.VERIFICATION,
                    semantic_id,
                    expression,
                )
        return tuple(sorted(
            specs,
            key=lambda item: (
                item.kind.value,
                item.semantic_id,
                item.formula_id,
            ),
        ))


generate_intent_proof_obligations = IntentProofObligations().generate


__all__ = [
    "INTENT_PROOF_OBLIGATIONS_VERSION",
    "INTENT_SEMANTIC_ENCODING",
    "IntentObligationKind",
    "IntentProofAuthorityPolicy",
    "IntentProofDisposition",
    "IntentProofExecution",
    "IntentProofObligationError",
    "IntentProofObligations",
    "IntentProofOutcome",
    "IntentProofPacket",
    "generate_intent_proof_obligations",
]
