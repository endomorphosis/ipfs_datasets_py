"""Profile D policy wiring for datasets MCP++ dispatch (fail-closed).

``ProfileDPolicyProvider@1`` consults the real ``PolicyEvaluator@1`` (MCPP-046)
before any side-effecting handler runs. This module intentionally does **not**
reimplement deontic evaluation; it only:

* resolve / hold the evaluator,
* convert provider inputs into evaluator kwargs,
* gate dispatch so deny and unavailable-evaluator paths never call handlers.

Acceptance (MCPP-049):
  * A deny decision never dispatches.
  * Missing evaluator never degrades to allow.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------

INTERFACE_PROVIDER = "ProfileDPolicyProvider@1"
INTERFACE_EVALUATOR = "PolicyEvaluator@1"
INTERFACE_DECISION = "PolicyDecision@1"

REASON_EVALUATOR_UNAVAILABLE = "evaluator_unavailable"
REASON_EVALUATOR_ERROR = "evaluator_error"
REASON_POLICY_DENIED = "policy_denied"
REASON_INVALID_DECISION = "invalid_decision"

_DENY_VERDICTS = frozenset({"deny"})
_ALLOW_VERDICTS = frozenset({"allow", "allow_with_obligations"})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchGateResult:
    """Outcome of a fail-closed policy gate around a side-effecting handler.

    ``dispatched`` is True only when the handler was actually invoked.
    Deny and unavailable-evaluator paths always set ``dispatched=False``.
    """

    allowed: bool
    dispatched: bool
    decision: Dict[str, Any]
    reason_code: str
    result: Any = None
    error: Optional[str] = None
    interface: str = INTERFACE_PROVIDER

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "interface": self.interface,
            "allowed": self.allowed,
            "dispatched": self.dispatched,
            "reason_code": self.reason_code,
            "decision": dict(self.decision),
        }
        if self.error is not None:
            payload["error"] = self.error
        if self.dispatched:
            payload["result"] = self.result
        return payload


class ProfileDPolicyProvider:
    """Datasets Profile D provider that wires dispatch to PolicyEvaluator@1.

    Construction never raises when the evaluator cannot be loaded. Callers
    inspect :attr:`available` and/or consult :meth:`evaluate` /
    :meth:`authorize_dispatch`, which fail closed (deny, no side effects).
    """

    def __init__(
        self,
        evaluator: Any = None,
        *,
        force_unavailable: bool = False,
        provider_id: str = "ipfs_datasets_py.mcp_server.mcplusplus.policy",
    ) -> None:
        self.provider_id = provider_id
        self.interface = INTERFACE_PROVIDER
        self._evaluator = evaluator
        self._load_error: Optional[BaseException] = None
        self._resolve_attempted = evaluator is not None
        self._force_unavailable = bool(force_unavailable)

    # -- availability -------------------------------------------------------

    def _resolve(self) -> Any:
        """Return a PolicyEvaluator@1 instance or None (fail closed)."""
        if self._force_unavailable:
            return None
        if self._evaluator is not None:
            return self._evaluator
        if self._resolve_attempted:
            return None
        self._resolve_attempted = True
        try:
            self._evaluator = _load_policy_evaluator()
        except Exception as exc:  # noqa: BLE001 — fail closed
            self._load_error = exc
            logger.warning(
                "Profile D PolicyEvaluator@1 unavailable (fail-closed): %s",
                exc,
            )
            self._evaluator = None
        return self._evaluator

    @property
    def available(self) -> bool:
        """True when a real evaluator instance is ready for evaluation."""
        return self._resolve() is not None

    @property
    def load_error(self) -> Optional[BaseException]:
        self._resolve()
        return self._load_error

    def metadata(self) -> Dict[str, Any]:
        return {
            "interface": self.interface,
            "provider": self.provider_id,
            "evaluator_interface": INTERFACE_EVALUATOR,
            "decision_interface": INTERFACE_DECISION,
            "available": self.available,
            "fail_closed": True,
            "load_error": str(self._load_error) if self._load_error else None,
        }

    # -- evaluation ---------------------------------------------------------

    def evaluate(
        self,
        intent: Optional[Mapping[str, Any]] = None,
        *,
        policy: Optional[Mapping[str, Any]] = None,
        policies: Optional[Sequence[Mapping[str, Any]]] = None,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        tool: Optional[str] = None,
        delegation: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]] = None,
        context_roots: Any = None,
        expected_context_roots: Any = None,
        required_context_keys: Optional[Sequence[str]] = None,
        logical_time: Optional[Union[str, float, int]] = None,
        prior_events: Optional[Sequence[Mapping[str, Any]]] = None,
        policy_version: Optional[str] = None,
        signature: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """Evaluate intent under policy via PolicyEvaluator@1 (fail closed).

        Always returns a decision mapping. When the evaluator is missing or
        raises, the decision is ``deny`` with an unavailable/error reason code.
        """
        evaluator = self._resolve()
        if evaluator is None:
            return _unavailable_decision(
                reason_code=REASON_EVALUATOR_UNAVAILABLE,
                justification=(
                    "PolicyEvaluator@1 is unavailable; refusing policy-governed execution"
                    + (f" ({self._load_error})" if self._load_error else "")
                ),
                intent=intent,
                actor=actor,
                action=action or tool,
                resource=resource,
                provider_id=self.provider_id,
            )

        eval_intent = _coerce_intent(
            intent,
            actor=actor,
            action=action,
            tool=tool,
            resource=resource,
        )
        kwargs: Dict[str, Any] = {
            "intent": eval_intent,
            "policy": policy,
            "policies": policies,
            "delegation": delegation,
            "context_roots": context_roots,
            "expected_context_roots": expected_context_roots,
            "required_context_keys": required_context_keys,
            "logical_time": logical_time,
            "prior_events": prior_events,
            "policy_version": policy_version,
            "signature": signature,
        }
        # Drop Nones so injected/minimal evaluators are not forced to accept them.
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        if extra:
            kwargs.update(extra)

        try:
            decision = evaluator.evaluate(**kwargs)
        except TypeError:
            # Some injected evaluators use a narrower signature.
            try:
                decision = evaluator.evaluate(eval_intent, policy=policy)
            except Exception as exc:  # noqa: BLE001 — fail closed
                return _error_decision(exc, eval_intent, self.provider_id)
        except Exception as exc:  # noqa: BLE001 — fail closed
            return _error_decision(exc, eval_intent, self.provider_id)

        payload = _decision_to_mapping(decision)
        payload.setdefault("policy_provider", self.provider_id)
        payload.setdefault("interface", INTERFACE_DECISION)
        payload.setdefault("evaluator_interface", INTERFACE_EVALUATOR)
        # Never upgrade an unrecognised verdict to allow.
        if not _is_granted(payload):
            payload["allowed"] = False
            payload["granted"] = False
            if payload.get("decision") not in _DENY_VERDICTS:
                # Preserve original decision text but force closed-world deny flags.
                payload.setdefault("reason_code", REASON_INVALID_DECISION)
        return payload

    # -- dispatch gate ------------------------------------------------------

    def authorize_dispatch(
        self,
        handler: Callable[..., Any],
        *,
        intent: Optional[Mapping[str, Any]] = None,
        policy: Optional[Mapping[str, Any]] = None,
        policies: Optional[Sequence[Mapping[str, Any]]] = None,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        tool: Optional[str] = None,
        handler_args: Sequence[Any] = (),
        handler_kwargs: Optional[Mapping[str, Any]] = None,
        **evaluate_kwargs: Any,
    ) -> DispatchGateResult:
        """Consult the evaluator, then invoke *handler* only on allow.

        Deny and unavailable-evaluator outcomes never call *handler*.
        """
        if not callable(handler):
            decision = _unavailable_decision(
                reason_code=REASON_INVALID_DECISION,
                justification="dispatch handler is not callable",
                intent=intent,
                actor=actor,
                action=action or tool,
                resource=resource,
                provider_id=self.provider_id,
            )
            return DispatchGateResult(
                allowed=False,
                dispatched=False,
                decision=decision,
                reason_code=REASON_INVALID_DECISION,
                error="handler is not callable",
            )

        # Unavailable short-circuit: never degrade to allow and never dispatch.
        if not self.available:
            decision = self.evaluate(
                intent,
                policy=policy,
                policies=policies,
                actor=actor,
                action=action,
                resource=resource,
                tool=tool,
                **evaluate_kwargs,
            )
            return DispatchGateResult(
                allowed=False,
                dispatched=False,
                decision=decision,
                reason_code=str(
                    decision.get("reason_code") or REASON_EVALUATOR_UNAVAILABLE
                ),
                error=str(decision.get("justification") or "evaluator unavailable"),
            )

        decision = self.evaluate(
            intent,
            policy=policy,
            policies=policies,
            actor=actor,
            action=action,
            resource=resource,
            tool=tool,
            **evaluate_kwargs,
        )

        if not _is_granted(decision):
            reason = str(
                decision.get("reason_code")
                or (
                    REASON_EVALUATOR_UNAVAILABLE
                    if decision.get("decision") == "deny"
                    and "unavailable" in str(decision.get("justification", "")).lower()
                    else REASON_POLICY_DENIED
                )
            )
            return DispatchGateResult(
                allowed=False,
                dispatched=False,
                decision=decision,
                reason_code=reason,
                error=str(decision.get("justification") or "policy denied"),
            )

        # Allowed (including allow_with_obligations): invoke side effects.
        try:
            result = handler(*(handler_args or ()), **dict(handler_kwargs or {}))
        except Exception as exc:  # noqa: BLE001 — surface handler errors, keep decision
            return DispatchGateResult(
                allowed=True,
                dispatched=True,
                decision=decision,
                reason_code=str(decision.get("reason_code") or "handler_error"),
                error=str(exc),
            )
        return DispatchGateResult(
            allowed=True,
            dispatched=True,
            decision=decision,
            reason_code=str(decision.get("reason_code") or decision.get("decision") or "allow"),
            result=result,
        )

    def may_dispatch(self, decision: Mapping[str, Any]) -> bool:
        """Return True only when *decision* is a grant and provider is available."""
        if not self.available:
            return False
        return _is_granted(decision)


# ---------------------------------------------------------------------------
# Module-level helpers / singleton
# ---------------------------------------------------------------------------

_DEFAULT_PROVIDER: Optional[ProfileDPolicyProvider] = None


def get_profile_d_policy_provider(
    *,
    reset: bool = False,
    evaluator: Any = None,
    force_unavailable: bool = False,
) -> ProfileDPolicyProvider:
    """Return the process-default Profile D provider (or a configured instance)."""
    global _DEFAULT_PROVIDER
    if evaluator is not None or force_unavailable:
        return ProfileDPolicyProvider(
            evaluator=evaluator,
            force_unavailable=force_unavailable,
        )
    if reset or _DEFAULT_PROVIDER is None:
        _DEFAULT_PROVIDER = ProfileDPolicyProvider()
    return _DEFAULT_PROVIDER


def protected_dispatch(
    handler: Callable[..., Any],
    *,
    intent: Optional[Mapping[str, Any]] = None,
    policy: Optional[Mapping[str, Any]] = None,
    provider: Optional[ProfileDPolicyProvider] = None,
    **kwargs: Any,
) -> DispatchGateResult:
    """Module-level fail-closed dispatch helper for datasets MCP++ tools."""
    gate = provider or get_profile_d_policy_provider()
    return gate.authorize_dispatch(handler, intent=intent, policy=policy, **kwargs)


def evaluate_and_gate(
    *,
    intent: Optional[Mapping[str, Any]] = None,
    policy: Optional[Mapping[str, Any]] = None,
    provider: Optional[ProfileDPolicyProvider] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Evaluate policy and return a gate view without invoking a handler.

    Useful for pre-checks. ``may_dispatch`` is False on deny / unavailable.
    """
    gate = provider or get_profile_d_policy_provider()
    decision = gate.evaluate(intent, policy=policy, **kwargs)
    return {
        "interface": INTERFACE_PROVIDER,
        "may_dispatch": gate.may_dispatch(decision),
        "available": gate.available,
        "decision": decision,
        "fail_closed": True,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_policy_evaluator() -> Any:
    """Import and instantiate the real PolicyEvaluator@1.

    Resolution order:
      1. ``validators.policy_evaluation.PolicyEvaluator`` (tests-py on path)
      2. monorepo path ``ipfs_accelerate_py/mcplusplus/tests-py``
    """
    try:
        from validators.policy_evaluation import PolicyEvaluator  # type: ignore

        return PolicyEvaluator()
    except Exception:
        pass

    for parent in Path(__file__).resolve().parents:
        tests_py = parent / "ipfs_accelerate_py" / "mcplusplus" / "tests-py"
        module_path = tests_py / "validators" / "policy_evaluation.py"
        if not module_path.is_file():
            continue
        tests_text = str(tests_py)
        if tests_text not in sys.path:
            sys.path.insert(0, tests_text)
        try:
            from validators.policy_evaluation import PolicyEvaluator  # type: ignore

            return PolicyEvaluator()
        except Exception as exc:
            raise RuntimeError(
                f"PolicyEvaluator@1 found at {module_path} but failed to import: {exc}"
            ) from exc

    raise RuntimeError(
        "PolicyEvaluator@1 (validators.policy_evaluation) could not be resolved"
    )


def _coerce_intent(
    intent: Optional[Mapping[str, Any]],
    *,
    actor: Optional[str],
    action: Optional[str],
    tool: Optional[str],
    resource: Optional[str],
) -> Dict[str, Any]:
    base: Dict[str, Any] = dict(intent) if isinstance(intent, Mapping) else {}
    if actor is not None:
        base.setdefault("actor", actor)
    effective_action = action if action is not None else tool
    if effective_action is not None:
        base.setdefault("action", effective_action)
        base.setdefault("tool", effective_action)
    if resource is not None:
        base.setdefault("resource", resource)
    if "actor" not in base:
        base["actor"] = "*"
    if "action" not in base and "tool" not in base:
        base["action"] = "*"
    return base


def _decision_to_mapping(decision: Any) -> Dict[str, Any]:
    if decision is None:
        return {
            "decision": "deny",
            "granted": False,
            "allowed": False,
            "justification": "evaluator returned no decision",
            "reason_code": REASON_INVALID_DECISION,
            "schema": "mcp++/profile-d-policy-decision@1",
            "interface": INTERFACE_DECISION,
        }
    if isinstance(decision, Mapping):
        payload = dict(decision)
    elif hasattr(decision, "to_dict") and callable(decision.to_dict):
        payload = dict(decision.to_dict())
    else:
        payload = {
            "decision": str(getattr(decision, "decision", "deny")),
            "granted": bool(getattr(decision, "granted", getattr(decision, "allowed", False))),
            "allowed": bool(getattr(decision, "allowed", getattr(decision, "granted", False))),
            "decision_cid": str(getattr(decision, "decision_cid", "") or ""),
            "justification": str(getattr(decision, "justification", "") or ""),
            "reason_code": getattr(decision, "reason_code", None),
            "obligations": list(getattr(decision, "obligations", ()) or ()),
            "policy_cid": str(getattr(decision, "policy_cid", "") or ""),
            "intent_cid": str(getattr(decision, "intent_cid", "") or ""),
            "evaluated_at": str(getattr(decision, "evaluated_at", "") or ""),
            "interface": INTERFACE_DECISION,
        }

    decision_value = str(payload.get("decision") or "deny").strip().lower()
    payload["decision"] = decision_value
    granted = payload.get("granted")
    if granted is None:
        granted = payload.get("allowed")
    if granted is None:
        granted = decision_value in _ALLOW_VERDICTS
    granted = bool(granted) and decision_value in _ALLOW_VERDICTS
    payload["granted"] = granted
    payload["allowed"] = granted
    return payload


def _is_granted(decision: Mapping[str, Any]) -> bool:
    verdict = str(decision.get("decision") or "").strip().lower()
    if verdict in _DENY_VERDICTS or verdict not in _ALLOW_VERDICTS:
        return False
    if "granted" in decision:
        return bool(decision.get("granted"))
    if "allowed" in decision:
        return bool(decision.get("allowed"))
    return verdict in _ALLOW_VERDICTS


def _unavailable_decision(
    *,
    reason_code: str,
    justification: str,
    intent: Optional[Mapping[str, Any]],
    actor: Optional[str],
    action: Optional[str],
    resource: Optional[str],
    provider_id: str,
) -> Dict[str, Any]:
    coerced = _coerce_intent(intent, actor=actor, action=action, tool=None, resource=resource)
    return {
        "schema": "mcp++/profile-d-policy-decision@1",
        "interface": INTERFACE_DECISION,
        "evaluator_interface": INTERFACE_EVALUATOR,
        "decision": "deny",
        "granted": False,
        "allowed": False,
        "decision_cid": "",
        "policy_cid": "",
        "intent_cid": str(coerced.get("intent_cid") or ""),
        "justification": justification,
        "reason_code": reason_code,
        "obligations": [],
        "fired_rules": [],
        "facts": [{"kind": "provider", "status": "unavailable"}],
        "deadlines": [],
        "compensation": [],
        "policy_provider": provider_id,
        "fail_closed": True,
        "witness": {
            "actor": coerced.get("actor"),
            "action": coerced.get("action") or coerced.get("tool"),
            "resource": coerced.get("resource"),
        },
    }


def _error_decision(
    exc: BaseException,
    intent: Mapping[str, Any],
    provider_id: str,
) -> Dict[str, Any]:
    return {
        "schema": "mcp++/profile-d-policy-decision@1",
        "interface": INTERFACE_DECISION,
        "evaluator_interface": INTERFACE_EVALUATOR,
        "decision": "deny",
        "granted": False,
        "allowed": False,
        "decision_cid": "",
        "justification": f"PolicyEvaluator@1 raised (fail-closed): {exc}",
        "reason_code": REASON_EVALUATOR_ERROR,
        "obligations": [],
        "policy_provider": provider_id,
        "fail_closed": True,
        "witness": {
            "actor": intent.get("actor"),
            "action": intent.get("action") or intent.get("tool"),
            "resource": intent.get("resource"),
        },
    }


__all__ = [
    "INTERFACE_DECISION",
    "INTERFACE_EVALUATOR",
    "INTERFACE_PROVIDER",
    "REASON_EVALUATOR_ERROR",
    "REASON_EVALUATOR_UNAVAILABLE",
    "REASON_INVALID_DECISION",
    "REASON_POLICY_DENIED",
    "DispatchGateResult",
    "ProfileDPolicyProvider",
    "evaluate_and_gate",
    "get_profile_d_policy_provider",
    "protected_dispatch",
]
