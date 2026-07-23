"""Cheap-first, trust-aware proof routing for Legal IR obligations.

The generic :mod:`.hammer` pipeline is deliberately solver-centric.  Legal IR
has several substantially cheaper ways to discharge (or reject) an obligation
before starting an external process, and a solver proof is not necessarily the
trust boundary requested by a caller.  This module supplies the orchestration
layer which keeps those concerns explicit.

Every route is recorded, including routes which did not apply or were skipped
after an earlier route met policy.  Unsupported lowering is a capability
result, not a failed theorem; the two therefore have distinct statuses.
"""

from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum, IntEnum
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from .hammer import (
    HeuristicPremiseSelector,
    HammerBackendResult,
    HammerBackendStatus,
    HammerGoal,
    HammerPipeline,
    HammerPremise,
    HammerResult,
    HammerStatus,
    PremiseSelection,
)
from .legal_ir_obligations import LegalIRProofObligation


LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION = "legal-ir-proof-router-v1"


class ProofRouteStage(str, Enum):
    """Ordered cost classes.  Enum order is intentionally not relied upon."""

    DETERMINISTIC = "deterministic"
    NATIVE_LOGIC = "native_logic"
    SMT_ATP = "smt_atp"
    LEAN_RECONSTRUCTION = "lean_reconstruction"
    SMT_ATP_PORTFOLIO = "smt_atp"
    NATIVE_LEAN = "lean_reconstruction"


PROOF_ROUTE_STAGE_ORDER = (
    ProofRouteStage.DETERMINISTIC,
    ProofRouteStage.NATIVE_LOGIC,
    ProofRouteStage.SMT_ATP,
    ProofRouteStage.LEAN_RECONSTRUCTION,
)


class ProofRouteStatus(str, Enum):
    """Outcome of one route, with capability and theorem failures separated."""

    PASSED = "passed"
    PROVED = "proved"
    THEOREM_FAILED = "theorem_failed"
    UNSUPPORTED_TRANSLATION = "unsupported_translation"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    ERROR = "error"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    UNSUPPORTED = "unsupported_translation"


class ProofTrustLevel(IntEnum):
    """Monotonic proof authority used by routing policy."""

    NONE = 0
    BACKEND = 10
    NATIVE = 20
    DETERMINISTIC = 30
    KERNEL = 40
    TRUSTED = 20
    LEAN_KERNEL = 40

    @classmethod
    def parse(cls, value: "ProofTrustLevel | str | int") -> "ProofTrustLevel":
        if isinstance(value, cls):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return cls(value)
        normalized = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "": cls.BACKEND,
            "none": cls.NONE,
            "untrusted": cls.NONE,
            "candidate": cls.BACKEND,
            "backend": cls.BACKEND,
            "backend_proof": cls.BACKEND,
            "trusted": cls.NATIVE,
            "native": cls.NATIVE,
            "native_logic": cls.NATIVE,
            "deterministic": cls.DETERMINISTIC,
            "kernel": cls.KERNEL,
            "lean": cls.KERNEL,
            "native_reconstruction": cls.KERNEL,
        }
        if normalized not in aliases:
            raise ValueError(f"Unknown proof trust level: {value!r}")
        return aliases[normalized]


DEFAULT_STAGE_BUDGETS: Mapping[ProofRouteStage, float] = {
    ProofRouteStage.DETERMINISTIC: 0.25,
    ProofRouteStage.NATIVE_LOGIC: 2.0,
    ProofRouteStage.SMT_ATP: 10.0,
    ProofRouteStage.LEAN_RECONSTRUCTION: 10.0,
}


@dataclass(frozen=True)
class ProofRoutingPolicy:
    """Deadline, route availability, and trust requirements for one proof."""

    required_trust: ProofTrustLevel | str | int = ProofTrustLevel.BACKEND
    total_timeout_seconds: float = 22.25
    stage_timeout_seconds: Mapping[ProofRouteStage | str, float] = field(
        default_factory=lambda: dict(DEFAULT_STAGE_BUDGETS)
    )
    enabled_routes: tuple[str, ...] = ()
    stop_on_theorem_failure: bool = True

    def __post_init__(self) -> None:
        required = ProofTrustLevel.parse(self.required_trust)
        object.__setattr__(self, "required_trust", required)
        total = float(self.total_timeout_seconds)
        if not math.isfinite(total) or total <= 0:
            raise ValueError("total_timeout_seconds must be positive and finite")
        normalized: Dict[ProofRouteStage, float] = {}
        for raw_stage, raw_budget in self.stage_timeout_seconds.items():
            stage = raw_stage if isinstance(raw_stage, ProofRouteStage) else ProofRouteStage(str(raw_stage))
            budget = float(raw_budget)
            if not math.isfinite(budget) or budget <= 0:
                raise ValueError(f"stage budget for {stage.value} must be positive and finite")
            normalized[stage] = budget
        missing = [stage.value for stage in PROOF_ROUTE_STAGE_ORDER if stage not in normalized]
        if missing:
            raise ValueError(f"missing stage budgets: {', '.join(missing)}")
        object.__setattr__(self, "stage_timeout_seconds", normalized)
        object.__setattr__(self, "enabled_routes", tuple(dict.fromkeys(self.enabled_routes)))

    def budget_for(self, stage: ProofRouteStage) -> float:
        return float(self.stage_timeout_seconds[stage])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled_routes": list(self.enabled_routes),
            "required_trust": self.required_trust.name.lower(),
            "stage_timeout_seconds": {
                stage.value: self.budget_for(stage) for stage in PROOF_ROUTE_STAGE_ORDER
            },
            "stop_on_theorem_failure": bool(self.stop_on_theorem_failure),
            "total_timeout_seconds": float(self.total_timeout_seconds),
        }


@dataclass(frozen=True)
class ProofRouteOutcome:
    """Normalized return value accepted from a route implementation."""

    status: ProofRouteStatus
    trust_level: ProofTrustLevel = ProofTrustLevel.NONE
    reason: str = ""
    hammer_result: Optional[HammerResult] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProofRouteRequest:
    """Bounded context passed to an injected route runner."""

    obligation: LegalIRProofObligation
    goal: HammerGoal
    premises: Sequence[HammerPremise | Mapping[str, Any] | str]
    sample_or_document: Any
    pipeline: HammerPipeline
    stage: ProofRouteStage
    route: str
    timeout_seconds: float
    deadline_monotonic: float
    total_deadline_monotonic: float
    cancellation_event: Optional[threading.Event] = None
    prior_hammer_result: Optional[HammerResult] = None


ProofRouteRunner = Callable[[ProofRouteRequest], ProofRouteOutcome | HammerResult | Mapping[str, Any] | bool]


@dataclass(frozen=True)
class ProofRouteAttempt:
    """Persistable audit record for one executed, skipped, or cancelled route."""

    stage: ProofRouteStage
    route: str
    status: ProofRouteStatus
    trust_level: ProofTrustLevel
    allocated_seconds: float
    elapsed_seconds: float = 0.0
    deadline_seconds_from_start: float = 0.0
    reason: str = ""
    skip_reason: str = ""
    cancellation_reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def executed(self) -> bool:
        return self.status not in {ProofRouteStatus.SKIPPED, ProofRouteStatus.CANCELLED}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allocated_seconds": round(float(self.allocated_seconds), 12),
            "cancellation_reason": self.cancellation_reason,
            "deadline_seconds_from_start": round(float(self.deadline_seconds_from_start), 12),
            "elapsed_seconds": round(float(self.elapsed_seconds), 12),
            "executed": self.executed,
            "metadata": dict(sorted(self.metadata.items())),
            "reason": self.reason,
            "route": self.route,
            "skip_reason": self.skip_reason,
            "stage": self.stage.value,
            "status": self.status.value,
            "trust_level": self.trust_level.name.lower(),
        }


@dataclass(frozen=True)
class LegalIRProofRouteResult:
    """Complete routing decision for a single Legal IR obligation."""

    obligation_id: str
    status: ProofRouteStatus
    trust_level: ProofTrustLevel
    required_trust: ProofTrustLevel
    attempts: tuple[ProofRouteAttempt, ...]
    hammer_result: HammerResult
    elapsed_seconds: float
    stop_reason: str
    schema_version: str = LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION

    @property
    def proved(self) -> bool:
        return self.status == ProofRouteStatus.PROVED

    @property
    def trust_satisfied(self) -> bool:
        return self.proved and self.trust_level >= self.required_trust

    @property
    def skipped_routes(self) -> tuple[str, ...]:
        return tuple(item.route for item in self.attempts if item.status == ProofRouteStatus.SKIPPED)

    @property
    def cancellation_reasons(self) -> tuple[str, ...]:
        return tuple(
            item.cancellation_reason
            for item in self.attempts
            if item.cancellation_reason
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "cancellation_reasons": list(self.cancellation_reasons),
            "elapsed_seconds": round(float(self.elapsed_seconds), 12),
            "obligation_id": self.obligation_id,
            "proved": self.proved,
            "required_trust": self.required_trust.name.lower(),
            "schema_version": self.schema_version,
            "skipped_routes": list(self.skipped_routes),
            "status": self.status.value,
            "stop_reason": self.stop_reason,
            "trust_level": self.trust_level.name.lower(),
            "trust_satisfied": self.trust_satisfied,
        }


_ROUTES: tuple[tuple[ProofRouteStage, str], ...] = (
    (ProofRouteStage.DETERMINISTIC, "deterministic_syntax"),
    (ProofRouteStage.DETERMINISTIC, "deterministic_graph"),
    (ProofRouteStage.DETERMINISTIC, "deterministic_contract"),
    (ProofRouteStage.NATIVE_LOGIC, "native_tdfol"),
    (ProofRouteStage.NATIVE_LOGIC, "native_cec"),
    (ProofRouteStage.SMT_ATP, "smt_atp_portfolio"),
    (ProofRouteStage.LEAN_RECONSTRUCTION, "native_lean_reconstruction"),
)


class LegalIRProofRouter:
    """Route a Legal IR obligation through monotonically more costly checks."""

    def __init__(
        self,
        pipeline: HammerPipeline,
        *,
        policy: Optional[ProofRoutingPolicy] = None,
        route_runners: Optional[Mapping[str, ProofRouteRunner]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pipeline = pipeline
        self.policy = policy or ProofRoutingPolicy()
        self.route_runners = dict(route_runners or {})
        unknown = set(self.route_runners) - {route for _, route in _ROUTES}
        if unknown:
            raise ValueError(f"Unknown proof routes: {', '.join(sorted(unknown))}")
        self._clock = clock

    def route(
        self,
        obligation: LegalIRProofObligation,
        goal: HammerGoal,
        premises: Sequence[HammerPremise | Mapping[str, Any] | str],
        *,
        sample_or_document: Any = None,
        cancellation_event: Optional[threading.Event] = None,
    ) -> LegalIRProofRouteResult:
        started = self._clock()
        total_deadline = started + self.policy.total_timeout_seconds
        attempts: list[ProofRouteAttempt] = []
        best: Optional[ProofRouteOutcome] = None
        last_hammer_result: Optional[HammerResult] = None
        portfolio_result: Optional[HammerResult] = None
        stop_reason = "routes_exhausted"
        terminal_status: Optional[ProofRouteStatus] = None
        stage_deadlines: Dict[ProofRouteStage, float] = {}

        for index, (stage, route) in enumerate(_ROUTES):
            now = self._clock()
            if stage not in stage_deadlines:
                stage_deadlines[stage] = min(total_deadline, now + self.policy.budget_for(stage))
            stage_deadline = stage_deadlines[stage]

            cancellation_reason = self._cancellation_reason(cancellation_event, now, total_deadline)
            if cancellation_reason:
                attempts.extend(self._cancel_remaining(index, started, cancellation_reason))
                stop_reason = cancellation_reason
                terminal_status = ProofRouteStatus.CANCELLED if cancellation_reason == "caller_cancelled" else ProofRouteStatus.TIMEOUT
                break
            if self.policy.enabled_routes and route not in self.policy.enabled_routes:
                attempts.append(self._skipped(stage, route, started, "route_disabled_by_policy"))
                continue
            applicability = self._applicability(route, obligation, portfolio_result)
            if applicability:
                attempts.append(self._skipped(stage, route, started, applicability))
                continue
            remaining = min(stage_deadline, total_deadline) - now
            if remaining <= 0:
                attempts.append(
                    ProofRouteAttempt(
                        stage=stage,
                        route=route,
                        status=ProofRouteStatus.CANCELLED,
                        trust_level=ProofTrustLevel.NONE,
                        allocated_seconds=0.0,
                        deadline_seconds_from_start=max(0.0, stage_deadline - started),
                        cancellation_reason="stage_deadline_exhausted",
                        reason="stage budget was exhausted before this route started",
                    )
                )
                continue

            request = ProofRouteRequest(
                obligation=obligation,
                goal=goal,
                premises=premises,
                sample_or_document=sample_or_document,
                pipeline=self.pipeline,
                stage=stage,
                route=route,
                timeout_seconds=remaining,
                deadline_monotonic=stage_deadline,
                total_deadline_monotonic=total_deadline,
                cancellation_event=cancellation_event,
                prior_hammer_result=portfolio_result,
            )
            route_started = self._clock()
            try:
                raw = self._runner(route)(request)
                outcome = self._normalize_outcome(raw, route)
            except Exception as exc:  # a route failure must not erase later options
                outcome = ProofRouteOutcome(
                    status=ProofRouteStatus.ERROR,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            route_finished = self._clock()
            elapsed = max(0.0, route_finished - route_started)
            post_cancellation = self._cancellation_reason(
                cancellation_event, route_finished, total_deadline
            )
            attempt_cancellation = ""
            if post_cancellation:
                outcome = replace(
                    outcome,
                    status=(
                        ProofRouteStatus.CANCELLED
                        if post_cancellation == "caller_cancelled"
                        else ProofRouteStatus.TIMEOUT
                    ),
                    trust_level=ProofTrustLevel.NONE,
                    reason=post_cancellation,
                )
                attempt_cancellation = post_cancellation
            elif route_finished > stage_deadline:
                outcome = replace(
                    outcome,
                    status=ProofRouteStatus.TIMEOUT,
                    trust_level=ProofTrustLevel.NONE,
                    reason=outcome.reason or "stage deadline exhausted",
                )
                attempt_cancellation = "stage_deadline_exhausted"
            attempts.append(
                ProofRouteAttempt(
                    stage=stage,
                    route=route,
                    status=outcome.status,
                    trust_level=outcome.trust_level,
                    allocated_seconds=max(0.0, remaining),
                    elapsed_seconds=elapsed,
                    deadline_seconds_from_start=max(0.0, stage_deadline - started),
                    reason=outcome.reason,
                    cancellation_reason=attempt_cancellation,
                    metadata=outcome.metadata,
                )
            )
            if route == "smt_atp_portfolio" and outcome.hammer_result is not None:
                portfolio_result = outcome.hammer_result
            if outcome.hammer_result is not None:
                last_hammer_result = outcome.hammer_result
            if post_cancellation:
                attempts.extend(self._cancel_remaining(index + 1, started, post_cancellation))
                stop_reason = post_cancellation
                terminal_status = outcome.status
                break
            if outcome.status == ProofRouteStatus.PROVED:
                if best is None or outcome.trust_level > best.trust_level:
                    best = outcome
                if outcome.trust_level >= self.policy.required_trust:
                    stop_reason = "required_trust_obtained"
                    terminal_status = ProofRouteStatus.PROVED
                    attempts.extend(self._skip_remaining(index + 1, started, stop_reason))
                    break
            elif outcome.status == ProofRouteStatus.THEOREM_FAILED and self.policy.stop_on_theorem_failure:
                best = outcome
                stop_reason = "conclusive_theorem_failure"
                terminal_status = ProofRouteStatus.THEOREM_FAILED
                attempts.extend(self._skip_remaining(index + 1, started, stop_reason))
                break

        final = best or self._fallback_outcome(
            attempts, goal, premises, last_hammer_result=last_hammer_result
        )
        final_hammer = final.hammer_result or self._synthetic_hammer_result(
            goal, premises, final.status, final.reason
        )
        status = terminal_status or final.status
        trust = final.trust_level if status == ProofRouteStatus.PROVED else ProofTrustLevel.NONE
        route_metadata = {
            "proof_route_attempts": [attempt.to_dict() for attempt in attempts],
            "proof_route_schema_version": LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION,
            "proof_route_status": status.value,
            "proof_route_stop_reason": stop_reason,
            "proof_route_trust_level": trust.name.lower(),
            "proof_route_required_trust": self.policy.required_trust.name.lower(),
        }
        final_hammer.metadata.update(route_metadata)
        return LegalIRProofRouteResult(
            obligation_id=obligation.obligation_id,
            status=status,
            trust_level=trust,
            required_trust=self.policy.required_trust,
            attempts=tuple(attempts),
            hammer_result=final_hammer,
            elapsed_seconds=max(0.0, self._clock() - started),
            stop_reason=stop_reason,
        )

    def _runner(self, route: str) -> ProofRouteRunner:
        return self.route_runners.get(route) or {
            "deterministic_syntax": self._deterministic_syntax,
            "deterministic_graph": self._deterministic_graph,
            "deterministic_contract": self._deterministic_contract,
            "native_tdfol": self._native_logic,
            "native_cec": self._native_logic,
            "smt_atp_portfolio": self._smt_atp,
            "native_lean_reconstruction": self._lean_reconstruction,
        }[route]

    def _applicability(
        self, route: str, obligation: LegalIRProofObligation, portfolio: Optional[HammerResult]
    ) -> str:
        family = f"{obligation.logic_family} {obligation.legal_ir_view}".lower()
        if route == "deterministic_graph" and not (
            "graph" in obligation.kind.lower() or "knowledge_graph" in family or obligation.logic_family.lower() == "frame"
        ):
            return "not_a_graph_obligation"
        if route == "deterministic_contract" and not obligation.metadata.get("contract_id"):
            return "not_a_contract_obligation"
        if route == "native_tdfol" and not any(token in family for token in ("tdfol", "temporal", "deontic", "modal")):
            return "logic_family_not_supported_by_tdfol"
        if route == "native_cec" and not any(token in family for token in ("cec", "event", "lifecycle", "cognitive")):
            return "logic_family_not_supported_by_cec"
        if route == "native_lean_reconstruction" and (
            portfolio is None or not any(item.proved for item in portfolio.backend_results)
        ):
            return "no_backend_candidate_to_reconstruct"
        return ""

    def _deterministic_syntax(self, request: ProofRouteRequest) -> ProofRouteOutcome:
        statement = request.obligation.statement.strip()
        if not statement:
            return ProofRouteOutcome(ProofRouteStatus.THEOREM_FAILED, reason="empty_obligation_statement")
        pairs = {')': '(', ']': '[', '}': '{'}
        stack: list[str] = []
        for char in statement:
            if char in "([{":
                stack.append(char)
            elif char in pairs and (not stack or stack.pop() != pairs[char]):
                return ProofRouteOutcome(ProofRouteStatus.THEOREM_FAILED, reason="unbalanced_obligation_syntax")
        if stack:
            return ProofRouteOutcome(ProofRouteStatus.THEOREM_FAILED, reason="unbalanced_obligation_syntax")
        explicit = request.obligation.metadata.get("deterministic_syntax_valid")
        if explicit is not None:
            return ProofRouteOutcome(
                ProofRouteStatus.PROVED if bool(explicit) else ProofRouteStatus.THEOREM_FAILED,
                ProofTrustLevel.DETERMINISTIC if bool(explicit) else ProofTrustLevel.NONE,
                reason="explicit_deterministic_syntax_check",
            )
        return ProofRouteOutcome(ProofRouteStatus.PASSED, reason="syntax_precheck_passed")

    def _deterministic_graph(self, request: ProofRouteRequest) -> ProofRouteOutcome:
        explicit = request.obligation.metadata.get("deterministic_graph_valid")
        if explicit is not None:
            return ProofRouteOutcome(
                ProofRouteStatus.PROVED if bool(explicit) else ProofRouteStatus.THEOREM_FAILED,
                ProofTrustLevel.DETERMINISTIC if bool(explicit) else ProofTrustLevel.NONE,
                reason="explicit_deterministic_graph_check",
            )
        # Generated edge obligations contain the three typed positions.  This
        # check establishes structural typing only; it does not infer a legal
        # theorem from arbitrary graph text.
        if request.obligation.kind == "knowledge_graph_edge_typing":
            match = re.fullmatch(
                r"kg_edge_typed\(subject:([^,]+),\s*predicate:([^,]+),\s*object:([^\)]+)\)",
                request.obligation.statement,
            )
            triple = self._graph_triple(request)
            if triple is None:
                return ProofRouteOutcome(
                    ProofRouteStatus.PASSED,
                    reason="graph_payload_not_available_for_deterministic_proof",
                )
            expected = tuple(self._atom(part) for part in match.groups()) if match else ()
            actual = tuple(
                self._atom(self._value(triple, key))
                for key in ("subject", "predicate", "object")
            )
            valid = bool(expected and expected == actual and all(actual))
            return ProofRouteOutcome(
                ProofRouteStatus.PROVED if valid else ProofRouteStatus.THEOREM_FAILED,
                ProofTrustLevel.DETERMINISTIC if valid else ProofTrustLevel.NONE,
                reason="canonical_graph_edge_typing_check",
            )
        return ProofRouteOutcome(ProofRouteStatus.PASSED, reason="graph_structure_precheck_passed")

    def _graph_triple(self, request: ProofRouteRequest) -> Any:
        document = self._value(request.sample_or_document, "modal_ir")
        if document is None:
            document = request.sample_or_document
        frame_logic = self._value(document, "frame_logic")
        triples = self._value(frame_logic, "triples") if frame_logic is not None else None
        if not isinstance(triples, Sequence) or isinstance(triples, (str, bytes, bytearray)):
            return None
        try:
            index = int(request.obligation.metadata.get("triple_index") or 0) - 1
        except (TypeError, ValueError):
            return None
        return triples[index] if 0 <= index < len(triples) else None

    @staticmethod
    def _value(value: Any, key: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(key)
        return getattr(value, key, None)

    @staticmethod
    def _atom(value: Any) -> str:
        return re.sub(r"[^a-z0-9_.:-]+", "_", str(value or "").strip().lower()).strip("_")

    def _deterministic_contract(self, request: ProofRouteRequest) -> ProofRouteOutcome:
        explicit = request.obligation.metadata.get("deterministic_contract_valid")
        if explicit is not None:
            return ProofRouteOutcome(
                ProofRouteStatus.PROVED if bool(explicit) else ProofRouteStatus.THEOREM_FAILED,
                ProofTrustLevel.DETERMINISTIC if bool(explicit) else ProofTrustLevel.NONE,
                reason="explicit_deterministic_contract_check",
            )
        # Contract identity and coverage scope are deterministic registry
        # checks, but by themselves do not establish the semantic statement.
        required = ("contract_id", "contract_view", "coverage_scope")
        missing = [key for key in required if not request.obligation.metadata.get(key)]
        if missing:
            return ProofRouteOutcome(
                ProofRouteStatus.THEOREM_FAILED,
                reason=f"contract_metadata_missing:{','.join(missing)}",
            )
        return ProofRouteOutcome(ProofRouteStatus.PASSED, reason="contract_registry_precheck_passed")

    def _native_logic(self, request: ProofRouteRequest) -> ProofRouteOutcome:
        key = "native_tdfol_result" if request.route == "native_tdfol" else "native_cec_result"
        raw = request.obligation.metadata.get(key)
        if callable(raw):
            raw = raw(request)
        if raw is None:
            raw = self._run_embedded_native_formula(request)
        if raw is None:
            return ProofRouteOutcome(
                ProofRouteStatus.UNSUPPORTED_TRANSLATION,
                reason=f"{request.route}_formula_not_available",
                metadata={"capability": request.route},
            )
        normalized = self._normalize_outcome(raw, request.route)
        if normalized.status == ProofRouteStatus.PROVED and normalized.trust_level == ProofTrustLevel.NONE:
            normalized = replace(normalized, trust_level=ProofTrustLevel.NATIVE)
        return normalized

    def _run_embedded_native_formula(self, request: ProofRouteRequest) -> Any:
        """Run an already typed native formula without guessing a text lowering.

        Legal IR producers may attach typed formulas to in-memory obligations.
        They are intentionally not serialized by the obligation exporter.  If
        no typed object is available, the route reports unsupported translation
        instead of treating the display statement as prover syntax.
        """

        metadata = request.obligation.metadata
        if request.route == "native_tdfol":
            formula = metadata.get("native_tdfol_formula")
            if formula is None:
                formula = metadata.get("tdfol_formula")
            if formula is None:
                return None
            prover = metadata.get("native_tdfol_prover")
            if prover is None:
                from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver

                prover = TDFOLProver(kb=metadata.get("native_tdfol_kb"), enable_cache=True)
            prove = getattr(prover, "prove", prover)
            if not callable(prove):
                raise TypeError("native_tdfol_prover must be callable or expose prove()")
            return prove(formula, timeout_ms=max(1, int(request.timeout_seconds * 1000)))

        formula = metadata.get("native_cec_formula")
        if formula is None:
            formula = metadata.get("cec_formula")
        if formula is None:
            return None
        prover = metadata.get("native_cec_prover")
        if prover is None:
            from ipfs_datasets_py.logic.CEC.native.prover_core import TheoremProver

            prover = TheoremProver()
        prove = getattr(prover, "prove_theorem", prover)
        if not callable(prove):
            raise TypeError("native_cec_prover must be callable or expose prove_theorem()")
        return prove(
            formula,
            axioms=list(metadata.get("native_cec_axioms") or ()),
            timeout=request.timeout_seconds,
        )

    def _smt_atp(self, request: ProofRouteRequest) -> ProofRouteOutcome:
        required_attributes = (
            "premise_selector",
            "translator",
            "backends",
            "reconstructor",
            "max_premises",
            "parallel_workers",
            "kernel_verifier",
        )
        if not all(hasattr(request.pipeline, name) for name in required_attributes):
            # Compatibility for protocol-style injected pipelines.  Full
            # HammerPipeline instances take the separated path below.
            return self._from_hammer_result(
                request.pipeline.prove(request.goal, request.premises)
            )
        pipeline = HammerPipeline(
            premise_selector=request.pipeline.premise_selector,
            translator=request.pipeline.translator,
            backends=request.pipeline.backends,
            reconstructor=request.pipeline.reconstructor,
            max_premises=request.pipeline.max_premises,
            timeout_seconds=max(0.001, request.timeout_seconds),
            parallel_workers=request.pipeline.parallel_workers,
            verify_reconstruction=False,
            kernel_verifier=request.pipeline.kernel_verifier,
        )
        result = pipeline.prove(request.goal, request.premises)
        return self._from_hammer_result(result)

    def _lean_reconstruction(self, request: ProofRouteRequest) -> ProofRouteOutcome:
        result = request.prior_hammer_result
        if result is None:
            return ProofRouteOutcome(ProofRouteStatus.UNKNOWN, reason="no_backend_candidate")
        if result.reconstruction is not None and result.reconstruction.verified:
            return ProofRouteOutcome(
                ProofRouteStatus.PROVED,
                ProofTrustLevel.KERNEL,
                reason="existing_native_reconstruction_verified",
                hammer_result=result,
            )
        winner = next((item for item in result.backend_results if item.proved), None)
        if winner is None:
            return ProofRouteOutcome(ProofRouteStatus.UNKNOWN, reason="no_backend_candidate", hammer_result=result)
        reconstruction = request.pipeline.reconstructor.reconstruct(
            goal=result.goal,
            selected_premises=result.premise_selection.selected,
            backend_result=winner,
            verify=True,
            verifier=request.pipeline.kernel_verifier,
        )
        status = HammerStatus.PROVED if reconstruction.verified else HammerStatus.RECONSTRUCTION_FAILED
        rebuilt = HammerResult(
            status=status,
            goal=result.goal,
            premise_selection=result.premise_selection,
            translations=result.translations,
            backend_results=result.backend_results,
            reconstruction=reconstruction,
            fallback_plan=result.fallback_plan,
            elapsed_seconds=result.elapsed_seconds + float(getattr(reconstruction.verification, "elapsed_seconds", 0.0) or 0.0),
            metadata={**result.metadata, "winner_backend": winner.backend},
        )
        return ProofRouteOutcome(
            ProofRouteStatus.PROVED if reconstruction.verified else ProofRouteStatus.THEOREM_FAILED,
            ProofTrustLevel.KERNEL if reconstruction.verified else ProofTrustLevel.NONE,
            reason="native_lean_kernel_accepted" if reconstruction.verified else "native_lean_kernel_rejected",
            hammer_result=rebuilt,
            metadata={"checker": str(getattr(reconstruction.verification, "checker", "") or "")},
        )

    def _normalize_outcome(self, raw: Any, route: str) -> ProofRouteOutcome:
        if isinstance(raw, ProofRouteOutcome):
            return raw
        if isinstance(raw, HammerResult):
            return self._from_hammer_result(raw)
        if isinstance(raw, bool):
            return ProofRouteOutcome(
                ProofRouteStatus.PROVED if raw else ProofRouteStatus.THEOREM_FAILED,
                self._default_trust(route) if raw else ProofTrustLevel.NONE,
            )
        if isinstance(raw, Mapping):
            data = dict(raw)
            raw_status = data.get("status")
            if raw_status is None:
                raw_status = "proved" if data.get("proved") else "theorem_failed"
            status_text = str(getattr(raw_status, "value", raw_status)).lower()
            aliases = {
                "disproved": ProofRouteStatus.THEOREM_FAILED,
                "failed": ProofRouteStatus.THEOREM_FAILED,
                "unsupported": ProofRouteStatus.UNSUPPORTED_TRANSLATION,
                "translation_failed": ProofRouteStatus.UNSUPPORTED_TRANSLATION,
                "unproved": ProofRouteStatus.UNKNOWN,
            }
            status = aliases.get(status_text)
            if status is None:
                status = ProofRouteStatus(status_text)
            trust = ProofTrustLevel.parse(data.get("trust_level") or data.get("trust") or (
                self._default_trust(route) if status == ProofRouteStatus.PROVED else ProofTrustLevel.NONE
            ))
            return ProofRouteOutcome(
                status=status,
                trust_level=trust,
                reason=str(data.get("reason") or data.get("error") or ""),
                hammer_result=data.get("hammer_result") if isinstance(data.get("hammer_result"), HammerResult) else None,
                metadata=dict(data.get("metadata") or {}),
            )
        raw_result = getattr(raw, "result", None)
        if raw_result is None:
            raw_result = getattr(raw, "status", None)
        result_value = str(getattr(raw_result, "value", raw_result or "")).lower()
        if result_value:
            return self._normalize_outcome({"status": result_value}, route)
        raise TypeError(f"Route {route} returned unsupported outcome {type(raw).__name__}")

    def _from_hammer_result(self, result: HammerResult) -> ProofRouteOutcome:
        diagnostics = {
            "hammer_status": result.status.value,
            "backend_results": [
                {
                    "backend": item.backend,
                    "error": str(item.error or "")[:240],
                    "status": item.status.value,
                    "timed_out": bool(item.timed_out),
                }
                for item in result.backend_results[:8]
            ],
            "translation_errors": {
                str(name): [str(error)[:240] for error in translation.errors[:4]]
                for name, translation in result.translations.items()
                if translation.errors
            },
        }
        if result.status == HammerStatus.TRANSLATION_FAILED:
            return ProofRouteOutcome(
                ProofRouteStatus.UNSUPPORTED_TRANSLATION,
                reason="unsupported_translation",
                hammer_result=result,
                metadata=diagnostics,
            )
        if result.status == HammerStatus.PROVED:
            verified = bool(result.reconstruction and result.reconstruction.verified)
            return ProofRouteOutcome(
                ProofRouteStatus.PROVED,
                ProofTrustLevel.KERNEL if verified else ProofTrustLevel.BACKEND,
                reason="native_reconstruction_verified" if verified else "backend_proof_candidate",
                hammer_result=result,
                metadata=diagnostics,
            )
        if any(item.status == HammerBackendStatus.DISPROVED for item in result.backend_results):
            return ProofRouteOutcome(
                ProofRouteStatus.THEOREM_FAILED,
                reason="backend_counterexample",
                hammer_result=result,
                metadata=diagnostics,
            )
        if result.status == HammerStatus.RECONSTRUCTION_FAILED:
            return ProofRouteOutcome(
                ProofRouteStatus.THEOREM_FAILED,
                reason="native_reconstruction_failed",
                hammer_result=result,
                metadata=diagnostics,
            )
        if result.backend_results and all(item.status == HammerBackendStatus.TIMEOUT for item in result.backend_results):
            return ProofRouteOutcome(
                ProofRouteStatus.TIMEOUT,
                reason="portfolio_timeout",
                hammer_result=result,
                metadata=diagnostics,
            )
        return ProofRouteOutcome(
            ProofRouteStatus.UNKNOWN,
            reason=str(result.status.value),
            hammer_result=result,
            metadata=diagnostics,
        )

    def _default_trust(self, route: str) -> ProofTrustLevel:
        if route.startswith("deterministic_"):
            return ProofTrustLevel.DETERMINISTIC
        if route.startswith("native_") and route != "native_lean_reconstruction":
            return ProofTrustLevel.NATIVE
        if route == "native_lean_reconstruction":
            return ProofTrustLevel.KERNEL
        return ProofTrustLevel.BACKEND

    def _selection(self, goal: HammerGoal, premises: Sequence[Any]) -> PremiseSelection:
        selector = getattr(self.pipeline, "premise_selector", None) or HeuristicPremiseSelector()
        max_premises = int(getattr(self.pipeline, "max_premises", 256))
        return selector.select(goal, premises, max_premises=max_premises)

    def _synthetic_hammer_result(
        self, goal: HammerGoal, premises: Sequence[Any], status: ProofRouteStatus, reason: str
    ) -> HammerResult:
        hammer_status = HammerStatus.PROVED if status == ProofRouteStatus.PROVED else (
            HammerStatus.TRANSLATION_FAILED if status == ProofRouteStatus.UNSUPPORTED_TRANSLATION else HammerStatus.UNPROVED
        )
        backend_results = []
        if hammer_status == HammerStatus.PROVED:
            backend_results.append(
                HammerBackendResult(
                    backend="legal_ir_proof_router",
                    status=HammerBackendStatus.PROVED,
                    proved=True,
                    elapsed_seconds=0.0,
                    translation_format="deterministic-or-native",
                    proof_trace=reason or status.value,
                    metadata={"route_status": status.value},
                )
            )
        return HammerResult(
            status=hammer_status,
            goal=goal,
            premise_selection=self._selection(goal, premises),
            translations={},
            backend_results=backend_results,
            elapsed_seconds=0.0,
            fallback_plan=[] if hammer_status == HammerStatus.PROVED else [f"proof_router:{reason or status.value}"],
        )

    def _fallback_outcome(
        self,
        attempts: Sequence[ProofRouteAttempt],
        goal: HammerGoal,
        premises: Sequence[Any],
        *,
        last_hammer_result: Optional[HammerResult] = None,
    ) -> ProofRouteOutcome:
        executed = [item for item in attempts if item.executed]
        terminal = {
            ProofRouteStatus.THEOREM_FAILED,
            ProofRouteStatus.TIMEOUT,
            ProofRouteStatus.UNSUPPORTED_TRANSLATION,
            ProofRouteStatus.ERROR,
            ProofRouteStatus.UNKNOWN,
        }
        status = next(
            (item.status for item in reversed(executed) if item.status in terminal),
            ProofRouteStatus.UNKNOWN,
        )
        return ProofRouteOutcome(
            status,
            reason=status.value,
            hammer_result=last_hammer_result
            or self._synthetic_hammer_result(goal, premises, status, status.value),
        )

    def _skipped(self, stage: ProofRouteStage, route: str, started: float, reason: str) -> ProofRouteAttempt:
        return ProofRouteAttempt(
            stage=stage,
            route=route,
            status=ProofRouteStatus.SKIPPED,
            trust_level=ProofTrustLevel.NONE,
            allocated_seconds=0.0,
            deadline_seconds_from_start=max(0.0, self._clock() - started),
            skip_reason=reason,
        )

    def _skip_remaining(self, start_index: int, started: float, reason: str) -> list[ProofRouteAttempt]:
        return [self._skipped(stage, route, started, reason) for stage, route in _ROUTES[start_index:]]

    def _cancel_remaining(self, start_index: int, started: float, reason: str) -> list[ProofRouteAttempt]:
        return [
            ProofRouteAttempt(
                stage=stage,
                route=route,
                status=ProofRouteStatus.CANCELLED,
                trust_level=ProofTrustLevel.NONE,
                allocated_seconds=0.0,
                deadline_seconds_from_start=max(0.0, self._clock() - started),
                cancellation_reason=reason,
                reason="route not started",
            )
            for stage, route in _ROUTES[start_index:]
        ]

    @staticmethod
    def _cancellation_reason(
        event: Optional[threading.Event], now: float, total_deadline: float
    ) -> str:
        if event is not None and event.is_set():
            return "caller_cancelled"
        if now >= total_deadline:
            return "total_deadline_exhausted"
        return ""


# Compact compatibility aliases for callers that use the shorter noun form.
ProofRouter = LegalIRProofRouter
ProofRouteResult = LegalIRProofRouteResult
LegalIRProofRoutingPolicy = ProofRoutingPolicy
LegalIRProofRoutingResult = LegalIRProofRouteResult


__all__ = [
    "DEFAULT_STAGE_BUDGETS",
    "LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION",
    "PROOF_ROUTE_STAGE_ORDER",
    "LegalIRProofRouteResult",
    "LegalIRProofRouter",
    "LegalIRProofRoutingPolicy",
    "LegalIRProofRoutingResult",
    "ProofRouteAttempt",
    "ProofRouteOutcome",
    "ProofRouteRequest",
    "ProofRouteResult",
    "ProofRouteRunner",
    "ProofRouteStage",
    "ProofRouteStatus",
    "ProofRouter",
    "ProofRoutingPolicy",
    "ProofTrustLevel",
]
