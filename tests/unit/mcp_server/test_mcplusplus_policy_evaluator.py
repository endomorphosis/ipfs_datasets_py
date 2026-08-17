"""Fail-closed datasets Profile D wiring tests (MCPP-049).

Interface: ProfileDPolicyProvider@1
Acceptance:
  * A deny decision never dispatches.
  * Missing evaluator never degrades to allow.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ---------------------------------------------------------------------------
# Path setup: datasets package + PolicyEvaluator@1 validators path
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).resolve().parent
_DATASETS_ROOT = _TESTS_DIR.parents[2]  # .../ipfs_datasets_py
_WORKSPACE_ROOT = _DATASETS_ROOT.parent
_ACCEL_MCPP_TESTS = _WORKSPACE_ROOT / "ipfs_accelerate_py" / "mcplusplus" / "tests-py"


def _ensure_on_path(path: Path) -> None:
    text = str(path)
    if path.exists() and text not in sys.path:
        sys.path.insert(0, text)


_ensure_on_path(_DATASETS_ROOT)
_ensure_on_path(_WORKSPACE_ROOT / "ipfs_accelerate_py")
_ensure_on_path(_ACCEL_MCPP_TESTS)

from ipfs_datasets_py.mcp_server.mcplusplus import policy as policy_mod  # noqa: E402
from ipfs_datasets_py.mcp_server.mcplusplus.policy import (  # noqa: E402
    INTERFACE_EVALUATOR,
    INTERFACE_PROVIDER,
    REASON_EVALUATOR_ERROR,
    REASON_EVALUATOR_UNAVAILABLE,
    REASON_POLICY_DENIED,
    ProfileDPolicyProvider,
    evaluate_and_gate,
    get_profile_d_policy_provider,
    protected_dispatch,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RecordingHandler:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append({"args": args, "kwargs": dict(kwargs)})
        return {"status": "side_effect_ran", "n": len(self.calls)}


class _StubEvaluator:
    """Minimal stand-in for PolicyEvaluator@1 with controllable verdicts."""

    def __init__(self, decision: str = "allow", *, raise_on_evaluate: bool = False) -> None:
        self.decision = decision
        self.raise_on_evaluate = raise_on_evaluate
        self.calls: List[Dict[str, Any]] = []

    def evaluate(self, intent=None, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append({"intent": intent, **kwargs})
        if self.raise_on_evaluate:
            raise RuntimeError("stub evaluator boom")
        granted = self.decision in {"allow", "allow_with_obligations"}
        return {
            "schema": "mcp++/profile-d-policy-decision@1",
            "interface": "PolicyDecision@1",
            "decision": self.decision,
            "granted": granted,
            "allowed": granted,
            "decision_cid": f"cid-{self.decision}",
            "justification": f"stub:{self.decision}",
            "reason_code": None if granted else "prohibition_matched",
            "obligations": (
                [{"type": "obligation", "action": "audit/log"}]
                if self.decision == "allow_with_obligations"
                else []
            ),
            "policy_cid": "cid-policy",
            "intent_cid": "",
            "evaluated_at": "2024-06-01T00:00:00Z",
        }


def _permission_policy(actor: str = "did:key:alice", action: str = "dataset.export") -> Dict[str, Any]:
    return {
        "schema": "mcp++/profile-d-policy@1",
        "version": "v1",
        "clauses": [
            {
                "clause_id": "p-1",
                "clause_type": "permission",
                "actor": actor,
                "action": action,
            }
        ],
    }


def _prohibition_policy(actor: str = "did:key:alice", action: str = "dataset.export") -> Dict[str, Any]:
    return {
        "schema": "mcp++/profile-d-policy@1",
        "version": "v1",
        "clauses": [
            {
                "clause_id": "f-1",
                "clause_type": "prohibition",
                "actor": actor,
                "action": action,
            }
        ],
    }


def _intent(actor: str = "did:key:alice", action: str = "dataset.export") -> Dict[str, Any]:
    return {"actor": actor, "action": action, "resource": "ds://demo"}


# ---------------------------------------------------------------------------
# Interface / metadata
# ---------------------------------------------------------------------------


class TestProfileDPolicyProviderInterface:
    def test_interface_constant(self) -> None:
        assert INTERFACE_PROVIDER == "ProfileDPolicyProvider@1"
        assert INTERFACE_EVALUATOR == "PolicyEvaluator@1"
        assert policy_mod.INTERFACE_PROVIDER == INTERFACE_PROVIDER

    def test_metadata_is_fail_closed(self) -> None:
        provider = ProfileDPolicyProvider(evaluator=_StubEvaluator("allow"))
        meta = provider.metadata()
        assert meta["interface"] == INTERFACE_PROVIDER
        assert meta["fail_closed"] is True
        assert meta["available"] is True
        assert meta["evaluator_interface"] == INTERFACE_EVALUATOR

    def test_unavailable_metadata(self) -> None:
        provider = ProfileDPolicyProvider(force_unavailable=True)
        meta = provider.metadata()
        assert meta["available"] is False
        assert meta["fail_closed"] is True


# ---------------------------------------------------------------------------
# Acceptance: deny never dispatches
# ---------------------------------------------------------------------------


class TestDenyNeverDispatches:
    def test_stub_deny_does_not_invoke_handler(self) -> None:
        handler = _RecordingHandler()
        provider = ProfileDPolicyProvider(evaluator=_StubEvaluator("deny"))

        gate = provider.authorize_dispatch(
            handler,
            intent=_intent(),
            policy=_prohibition_policy(),
            handler_kwargs={"payload": "secret"},
        )

        assert gate.allowed is False
        assert gate.dispatched is False
        assert gate.result is None
        assert handler.calls == []
        assert gate.decision["decision"] == "deny"
        assert gate.decision["allowed"] is False
        assert gate.reason_code in {REASON_POLICY_DENIED, "prohibition_matched"}

    def test_real_evaluator_deny_does_not_invoke_handler(self) -> None:
        try:
            from validators.policy_evaluation import PolicyEvaluator
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"PolicyEvaluator@1 not importable: {exc}")

        handler = _RecordingHandler()
        provider = ProfileDPolicyProvider(evaluator=PolicyEvaluator())
        gate = provider.authorize_dispatch(
            handler,
            intent=_intent(),
            policy=_prohibition_policy(),
            logical_time="2024-06-01T00:00:00Z",
        )

        assert gate.dispatched is False
        assert gate.allowed is False
        assert handler.calls == []
        assert gate.decision["decision"] == "deny"
        assert gate.decision.get("granted") is False

    def test_protected_dispatch_deny_path(self) -> None:
        handler = _RecordingHandler()
        provider = ProfileDPolicyProvider(evaluator=_StubEvaluator("deny"))
        gate = protected_dispatch(
            handler,
            intent=_intent(),
            policy=_prohibition_policy(),
            provider=provider,
        )
        assert gate.dispatched is False
        assert handler.calls == []

    def test_evaluate_and_gate_deny_sets_may_dispatch_false(self) -> None:
        provider = ProfileDPolicyProvider(evaluator=_StubEvaluator("deny"))
        view = evaluate_and_gate(
            intent=_intent(),
            policy=_prohibition_policy(),
            provider=provider,
        )
        assert view["may_dispatch"] is False
        assert view["decision"]["decision"] == "deny"
        assert view["fail_closed"] is True


# ---------------------------------------------------------------------------
# Acceptance: missing evaluator never degrades to allow
# ---------------------------------------------------------------------------


class TestMissingEvaluatorNeverAllows:
    def test_force_unavailable_evaluate_is_deny(self) -> None:
        provider = ProfileDPolicyProvider(force_unavailable=True)
        decision = provider.evaluate(intent=_intent(), policy=_permission_policy())

        assert provider.available is False
        assert decision["decision"] == "deny"
        assert decision["allowed"] is False
        assert decision["granted"] is False
        assert decision["reason_code"] == REASON_EVALUATOR_UNAVAILABLE
        assert decision.get("fail_closed") is True

    def test_unavailable_never_dispatches(self) -> None:
        handler = _RecordingHandler()
        provider = ProfileDPolicyProvider(force_unavailable=True)

        gate = provider.authorize_dispatch(
            handler,
            intent=_intent(),
            policy=_permission_policy(),
        )

        assert gate.allowed is False
        assert gate.dispatched is False
        assert handler.calls == []
        assert gate.reason_code == REASON_EVALUATOR_UNAVAILABLE
        assert gate.decision["decision"] == "deny"
        assert gate.decision["allowed"] is False

    def test_evaluator_exception_is_deny_and_not_dispatched(self) -> None:
        handler = _RecordingHandler()
        provider = ProfileDPolicyProvider(
            evaluator=_StubEvaluator("allow", raise_on_evaluate=True)
        )

        gate = provider.authorize_dispatch(
            handler,
            intent=_intent(),
            policy=_permission_policy(),
        )

        assert gate.dispatched is False
        assert gate.allowed is False
        assert handler.calls == []
        assert gate.decision["decision"] == "deny"
        assert gate.decision["reason_code"] == REASON_EVALUATOR_ERROR

    def test_may_dispatch_false_when_unavailable(self) -> None:
        provider = ProfileDPolicyProvider(force_unavailable=True)
        # Even a forged "allow" mapping must not pass the provider gate.
        forged = {"decision": "allow", "granted": True, "allowed": True}
        assert provider.may_dispatch(forged) is False

    def test_get_provider_force_unavailable(self) -> None:
        provider = get_profile_d_policy_provider(force_unavailable=True)
        decision = provider.evaluate(actor="a", action="t", policy=_permission_policy())
        assert decision["decision"] == "deny"
        assert decision["allowed"] is False


# ---------------------------------------------------------------------------
# Positive path: allow (and obligations) may dispatch
# ---------------------------------------------------------------------------


class TestAllowDispatches:
    def test_stub_allow_dispatches_once(self) -> None:
        handler = _RecordingHandler()
        provider = ProfileDPolicyProvider(evaluator=_StubEvaluator("allow"))

        gate = provider.authorize_dispatch(
            handler,
            intent=_intent(),
            policy=_permission_policy(),
            handler_kwargs={"x": 1},
        )

        assert gate.allowed is True
        assert gate.dispatched is True
        assert gate.result == {"status": "side_effect_ran", "n": 1}
        assert len(handler.calls) == 1
        assert handler.calls[0]["kwargs"] == {"x": 1}
        assert gate.decision["decision"] == "allow"

    def test_allow_with_obligations_still_dispatches(self) -> None:
        handler = _RecordingHandler()
        provider = ProfileDPolicyProvider(
            evaluator=_StubEvaluator("allow_with_obligations")
        )
        gate = provider.authorize_dispatch(
            handler,
            intent=_intent(),
            policy=_permission_policy(),
        )
        assert gate.dispatched is True
        assert gate.allowed is True
        assert gate.decision["decision"] == "allow_with_obligations"
        assert len(handler.calls) == 1

    def test_real_evaluator_allow_dispatches(self) -> None:
        try:
            from validators.policy_evaluation import PolicyEvaluator
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"PolicyEvaluator@1 not importable: {exc}")

        handler = _RecordingHandler()
        provider = ProfileDPolicyProvider(evaluator=PolicyEvaluator())
        gate = provider.authorize_dispatch(
            handler,
            intent=_intent(),
            policy=_permission_policy(),
            logical_time="2024-06-01T00:00:00Z",
        )
        assert gate.dispatched is True
        assert gate.allowed is True
        assert gate.decision["decision"] in {"allow", "allow_with_obligations"}
        assert gate.decision.get("decision_cid")
        assert len(handler.calls) == 1

    def test_default_provider_resolves_real_evaluator_when_present(self) -> None:
        provider = ProfileDPolicyProvider()
        if not provider.available:
            pytest.skip("PolicyEvaluator@1 not resolvable in this environment")
        decision = provider.evaluate(
            intent=_intent(),
            policy=_permission_policy(),
            logical_time="2024-06-01T00:00:00Z",
        )
        assert decision["decision"] == "allow"
        assert decision["allowed"] is True
        assert decision.get("decision_cid")


# ---------------------------------------------------------------------------
# Gate integrity
# ---------------------------------------------------------------------------


class TestGateIntegrity:
    def test_handler_not_called_between_evaluate_and_deny(self) -> None:
        """Regression: authorize_dispatch must not call handler before evaluate finishes."""
        order: List[str] = []

        class OrderedEval:
            def evaluate(self, intent=None, **kwargs: Any) -> Dict[str, Any]:
                order.append("evaluate")
                return {
                    "decision": "deny",
                    "granted": False,
                    "allowed": False,
                    "justification": "ordered-deny",
                }

        def handler() -> str:
            order.append("handler")
            return "ran"

        provider = ProfileDPolicyProvider(evaluator=OrderedEval())
        gate = provider.authorize_dispatch(handler, intent=_intent(), policy=_prohibition_policy())
        assert order == ["evaluate"]
        assert gate.dispatched is False

    def test_to_dict_omits_result_when_not_dispatched(self) -> None:
        provider = ProfileDPolicyProvider(evaluator=_StubEvaluator("deny"))
        gate = provider.authorize_dispatch(
            _RecordingHandler(),
            intent=_intent(),
            policy=_prohibition_policy(),
        )
        payload = gate.to_dict()
        assert payload["dispatched"] is False
        assert "result" not in payload
        assert payload["allowed"] is False

    def test_unrecognised_verdict_does_not_dispatch(self) -> None:
        class WeirdEval:
            def evaluate(self, intent=None, **kwargs: Any) -> Dict[str, Any]:
                return {"decision": "maybe", "granted": True, "allowed": True}

        handler = _RecordingHandler()
        provider = ProfileDPolicyProvider(evaluator=WeirdEval())
        gate = provider.authorize_dispatch(
            handler, intent=_intent(), policy=_permission_policy()
        )
        assert gate.dispatched is False
        assert gate.allowed is False
        assert handler.calls == []
