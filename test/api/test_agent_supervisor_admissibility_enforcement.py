"""Unit tests for SupervisorPreInvocationEnforcement@1 (LIG-037).

Acceptance:

* Import agent_supervisor without datasets/heavy prover side effects.
* Explicit off/audit/shadow/enforce mode and injected store/service.
* Bind supervisor actor/delegation/audience/task/plan/tool/arguments/effects/
  environment.
* Reject abstain/reject/error/expired/replayed/root-changed/environment-changed
  receipts.
* Call fake delegate once only after atomic consumption.
* Emit decision/runtime observation without treating it as theorem proof.

Evidence subset: lazy import, pinned-root load, non-allow rejection,
exact-context mutation, no-call, and one-call supervisor receipt.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from ipfs_accelerate_py.agent_supervisor import admissibility_enforcement as enf
from ipfs_accelerate_py.agent_supervisor.admissibility_enforcement import (
    ENV_ENFORCEMENT_MODE,
    SUPERVISOR_ENFORCEMENT_OBSERVATION_SCHEMA,
    SUPERVISOR_PRE_INVOCATION_ENFORCEMENT_INTERFACE,
    SUPERVISOR_PRE_INVOCATION_ENFORCEMENT_VERSION,
    AdmissibilityEnforcementError,
    EnforcementDenialReason,
    EnforcementDisposition,
    EnforcementMode,
    EnforcementObservation,
    InMemoryCapabilityConsumptionStore,
    SupervisorInvocationContext,
    SupervisorPreInvocationEnforcement,
    authorize_and_delegate,
    create_supervisor_enforcement,
    datasets_auth_available,
    reset_datasets_auth_surface_cache,
)


# ---------------------------------------------------------------------------
# Digests / time fixtures (shared with LIG-034 receipt tests)
# ---------------------------------------------------------------------------

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_DIGEST_D = "d" * 64
_DIGEST_E = "e" * 64
_DIGEST_F = "f" * 64
_DIGEST_1 = "1" * 64
_DIGEST_2 = "2" * 64
_DIGEST_3 = "3" * 64

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_EXPIRED = "2026-07-28T12:11:00Z"


@pytest.fixture(autouse=True)
def _reset_lazy_cache() -> None:
    reset_datasets_auth_surface_cache()
    yield
    reset_datasets_auth_surface_cache()


def _require_datasets_auth() -> None:
    if not datasets_auth_available():
        pytest.skip("ipfs_datasets_py authorization surface unavailable")


def _receipt_modules() -> Any:
    _require_datasets_auth()
    from ipfs_datasets_py.logic.admissibility.compose import InternalDecisionStatus
    from ipfs_datasets_py.logic.admissibility.receipt import (
        BoundContext,
        BoundRoots,
        build_decision_receipt,
        derive_capability,
    )

    return InternalDecisionStatus, BoundContext, BoundRoots, build_decision_receipt, derive_capability


def _roots(**overrides: Any) -> Any:
    _, _, BoundRoots, _, _ = _receipt_modules()
    base = {
        "policy_root": "policy:root-v1",
        "corpus_roots": ("corpus:legal-v1", "corpus:security-v1"),
        "revocation_root": "revocation:root-v1",
        "circuit_roots": ("circuit:auth-v1",),
        "vk_roots": ("vk:auth-v1",),
    }
    base.update(overrides)
    return BoundRoots(**base)


def _bound_context(**overrides: Any) -> Any:
    _, BoundContext, _, _, _ = _receipt_modules()
    base = {
        "request_digest": _DIGEST_A,
        "arguments_digest": _DIGEST_B,
        "actor_id": "actor:alice",
        "audience_id": "audience:supervisor-dispatcher",
        "tool_id": "tool:supervisor.delegate",
        "tool_version": "1.0.0",
        "effect_ids": (
            "effect:side-effect",
            "effect:notify",
            "effect:audit-log",
        ),
        "environment_digest": _DIGEST_C,
        "environment_id": "env:prod-sandbox",
        "delegation_ids": ("delegation:link-1",),
        "delegation_digest": _DIGEST_D,
        "resource_ids": ("resource:workspace",),
        "capability_ids": ("capability:write",),
        "nonce": "nonce-supervisor-001",
    }
    base.update(overrides)
    return BoundContext(**base)


def _allow_receipt(**overrides: Any) -> Any:
    InternalDecisionStatus, _, _, build_decision_receipt, _ = _receipt_modules()
    kwargs: dict[str, Any] = {
        "receipt_id": "receipt:allow-supervisor-001",
        "context": _bound_context(),
        "roots": _roots(),
        "outcome": InternalDecisionStatus.ALLOW,
        "reasons": ("positive grant proved",),
        "reason_codes": ("allow.positive_grant",),
        "selected_evidence_cids": (
            "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
        ),
        "obligation_ids": ("obl:pre-check",),
        "residual_duties": (),
        "attempt_digests": (_DIGEST_1,),
        "result_digests": (_DIGEST_2,),
        "decision_digest": _DIGEST_E,
        "policy_digest": _DIGEST_F,
        "profile_id": "profile:closed-world",
        "issued_at": _ISSUED,
        "deadline": _DEADLINE,
        "expiry": _EXPIRY,
        "producer_id": "producer:auth-service",
    }
    kwargs.update(overrides)
    return build_decision_receipt(**kwargs)


def _receipt_for_status(status: Any, **overrides: Any) -> Any:
    return _allow_receipt(
        receipt_id=f"receipt:{getattr(status, 'value', status)}",
        outcome=status,
        reasons=(f"status={getattr(status, 'value', status)}",),
        reason_codes=(f"code.{getattr(status, 'value', status)}",),
        **overrides,
    )


def _supervisor_context(**overrides: Any) -> SupervisorInvocationContext:
    base = {
        "actor_id": "actor:alice",
        "audience_id": "audience:supervisor-dispatcher",
        "tool_id": "tool:supervisor.delegate",
        "tool_version": "1.0.0",
        "request_digest": _DIGEST_A,
        "arguments_digest": _DIGEST_B,
        "environment_digest": _DIGEST_C,
        "environment_id": "env:prod-sandbox",
        "effect_ids": ("effect:side-effect",),
        "task_id": "task:lig-037",
        "plan_id": "plan:pre-dispatch",
        "delegation_ids": ("delegation:link-1",),
        "delegation_digest": _DIGEST_D,
        "nonce": "nonce-supervisor-001",
        "resource_ids": ("resource:workspace",),
    }
    base.update(overrides)
    return SupervisorInvocationContext(**base)


def _capability_for(receipt: Any, *, effect: str = "effect:side-effect") -> Any:
    _, _, _, _, derive_capability = _receipt_modules()
    return derive_capability(
        receipt,
        capability_id="capability:supervisor-once",
        allowed_effects=(effect,),
        require_strict_subset=True,
    )


class _CountingDelegate:
    def __init__(self, value: Any = "ok") -> None:
        self.calls = 0
        self.value = value

    def __call__(self) -> Any:
        self.calls += 1
        return self.value


# ---------------------------------------------------------------------------
# Import / prover isolation / lazy import
# ---------------------------------------------------------------------------


def test_enforcement_module_does_not_import_datasets_at_load() -> None:
    source = Path(enf.__file__).read_text(encoding="utf-8")
    assert "importlib.import_module" in source
    assert "_load_datasets_auth_surface" in source
    assert "from ipfs_datasets_py.logic.admissibility" not in source
    for banned in ("z3", "cvc5", "vampire", "lean_dojo", "shadowprover"):
        assert f"import {banned}" not in source
        assert f'importlib.import_module("{banned}' not in source
        assert f"importlib.import_module('{banned}" not in source


def test_import_agent_supervisor_without_heavy_provers() -> None:
    import ipfs_accelerate_py.agent_supervisor as supervisor  # noqa: F401
    import ipfs_accelerate_py.agent_supervisor.admissibility_enforcement as ae

    assert (
        ae.SUPERVISOR_PRE_INVOCATION_ENFORCEMENT_INTERFACE
        == SUPERVISOR_PRE_INVOCATION_ENFORCEMENT_INTERFACE
    )
    external = [
        name
        for name in sys.modules
        if name.split(".")[0]
        in {"z3", "cvc5", "vampire", "lean_dojo", "nltk_tactics", "shadowprover"}
    ]
    assert external == []


def test_interface_constants_are_pinned() -> None:
    assert (
        SUPERVISOR_PRE_INVOCATION_ENFORCEMENT_INTERFACE
        == "SupervisorPreInvocationEnforcement@1"
    )
    assert SUPERVISOR_PRE_INVOCATION_ENFORCEMENT_VERSION == 1
    assert EnforcementMode.OFF.value == "off"
    assert EnforcementMode.AUDIT.value == "audit"
    assert EnforcementMode.SHADOW.value == "shadow"
    assert EnforcementMode.ENFORCE.value == "enforce"
    assert EnforcementMode.ENFORCE.blocks is True
    assert EnforcementMode.SHADOW.blocks is False


# ---------------------------------------------------------------------------
# Construction / modes / injection
# ---------------------------------------------------------------------------


def test_capabilities_report_without_evaluation() -> None:
    store = InMemoryCapabilityConsumptionStore()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.SHADOW,
        store=store,
        service=object(),
        expected_roots={"policy_root": "policy:x"},
    )
    caps = enforcer.capabilities()
    assert caps["interface"] == SUPERVISOR_PRE_INVOCATION_ENFORCEMENT_INTERFACE
    assert caps["executed"] is False
    assert caps["provers_imported"] is False
    assert caps["theorem_proof"] is False
    assert caps["mode"] == "shadow"
    assert caps["store_injected"] is True
    assert caps["service_injected"] is True
    assert caps["env_flags"]["mode"] == ENV_ENFORCEMENT_MODE
    assert "off" in caps["modes"]
    assert "enforce" in caps["modes"]


def test_from_env_reads_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_ENFORCEMENT_MODE, "audit")
    enforcer = SupervisorPreInvocationEnforcement.from_env()
    assert enforcer.active_mode is EnforcementMode.AUDIT


def test_unknown_mode_fails_closed() -> None:
    with pytest.raises(AdmissibilityEnforcementError, match="unknown enforcement mode"):
        create_supervisor_enforcement(mode="canary")


def test_injected_store_is_used() -> None:
    store = InMemoryCapabilityConsumptionStore()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.OFF, store=store
    )
    assert enforcer.consumption_store is store


# ---------------------------------------------------------------------------
# Mode off / audit / shadow / enforce
# ---------------------------------------------------------------------------


def test_mode_off_calls_delegate_without_receipt() -> None:
    delegate = _CountingDelegate("passthrough")
    enforcer = create_supervisor_enforcement(mode=EnforcementMode.OFF)
    result = enforcer.authorize_and_delegate(_supervisor_context(), delegate)
    assert delegate.calls == 1
    assert result.delegate_called is True
    assert result.delegate_result == "passthrough"
    assert result.observation.disposition is EnforcementDisposition.OFF
    assert result.observation.theorem_proof is False


def test_mode_audit_records_and_does_not_block_reject() -> None:
    _require_datasets_auth()
    from ipfs_datasets_py.logic.admissibility.compose import InternalDecisionStatus

    receipt = _receipt_for_status(InternalDecisionStatus.DENY)
    delegate = _CountingDelegate()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.AUDIT,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(
        _supervisor_context(),
        delegate,
        receipt=receipt,
    )
    assert delegate.calls == 1
    assert result.observation.disposition is EnforcementDisposition.AUDITED
    assert result.observation.allowed is True
    assert EnforcementDenialReason.REJECT.value in result.observation.reason_codes
    assert result.observation.theorem_proof is False


def test_mode_shadow_would_block_still_calls() -> None:
    _require_datasets_auth()
    from ipfs_datasets_py.logic.admissibility.compose import InternalDecisionStatus

    receipt = _receipt_for_status(InternalDecisionStatus.REVIEW)
    delegate = _CountingDelegate()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.SHADOW,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(
        _supervisor_context(),
        delegate,
        receipt=receipt,
    )
    assert delegate.calls == 1
    assert (
        result.observation.disposition
        is EnforcementDisposition.SHADOW_WOULD_BLOCK
    )
    assert result.observation.allowed is True


# ---------------------------------------------------------------------------
# Enforce: allow once after atomic consumption
# ---------------------------------------------------------------------------


def test_enforce_allow_calls_delegate_once_after_consumption() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    store = InMemoryCapabilityConsumptionStore()
    delegate = _CountingDelegate({"status": "delegated"})
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        store=store,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(
        _supervisor_context(),
        delegate,
        receipt=receipt,
        capability=capability,
    )
    assert delegate.calls == 1
    assert result.delegate_called is True
    assert result.delegate_result == {"status": "delegated"}
    assert result.observation.disposition is EnforcementDisposition.ALLOWED
    assert result.observation.allowed is True
    assert result.observation.consumed is True
    assert result.observation.delegated is True
    assert result.observation.theorem_proof is False
    assert result.observation.task_id == "task:lig-037"
    assert result.observation.plan_id == "plan:pre-dispatch"
    assert result.observation.actor_id == "actor:alice"
    assert result.observation.tool_id == "tool:supervisor.delegate"


def test_enforce_replay_is_rejected_with_zero_calls() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    store = InMemoryCapabilityConsumptionStore()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        store=store,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    first = _CountingDelegate("first")
    second = _CountingDelegate("second")
    r1 = enforcer.authorize_and_delegate(
        _supervisor_context(), first, receipt=receipt, capability=capability
    )
    r2 = enforcer.authorize_and_delegate(
        _supervisor_context(), second, receipt=receipt, capability=capability
    )
    assert first.calls == 1
    assert r1.observation.consumed is True
    assert second.calls == 0
    assert r2.delegate_called is False
    assert r2.observation.disposition is EnforcementDisposition.DENIED
    assert r2.observation.denial_reason == EnforcementDenialReason.REPLAYED.value


def test_concurrent_consumption_only_one_wins() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    store = InMemoryCapabilityConsumptionStore()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        store=store,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    barrier = threading.Barrier(8)
    outcomes: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        delegate = _CountingDelegate()
        barrier.wait()
        result = enforcer.authorize_and_delegate(
            _supervisor_context(),
            delegate,
            receipt=receipt,
            capability=capability,
        )
        with lock:
            outcomes.append(result.delegate_called)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7


# ---------------------------------------------------------------------------
# Non-allow and invalid receipt rejection (enforce, no call)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status_name,expected_reason",
    [
        ("DENY", EnforcementDenialReason.REJECT.value),
        ("REVIEW", EnforcementDenialReason.ABSTAIN.value),
        ("INDETERMINATE", EnforcementDenialReason.ABSTAIN.value),
        ("ERROR", EnforcementDenialReason.ERROR.value),
    ],
)
def test_enforce_rejects_non_allow_with_zero_calls(
    status_name: str, expected_reason: str
) -> None:
    _require_datasets_auth()
    from ipfs_datasets_py.logic.admissibility.compose import InternalDecisionStatus

    status = InternalDecisionStatus[status_name]
    receipt = _receipt_for_status(status)
    delegate = _CountingDelegate()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(
        _supervisor_context(),
        delegate,
        receipt=receipt,
    )
    assert delegate.calls == 0
    assert result.delegate_called is False
    assert result.observation.disposition is EnforcementDisposition.DENIED
    assert expected_reason in result.observation.reason_codes


def test_enforce_rejects_expired_receipt() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    delegate = _CountingDelegate()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        expected_roots=_roots(),
        clock=lambda: _NOW_EXPIRED,
    )
    result = enforcer.authorize_and_delegate(
        _supervisor_context(),
        delegate,
        receipt=receipt,
        capability=capability,
    )
    assert delegate.calls == 0
    assert EnforcementDenialReason.EXPIRED.value in result.observation.reason_codes


def test_enforce_rejects_root_changed() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    delegate = _CountingDelegate()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        expected_roots=_roots(policy_root="policy:root-v0-stale"),
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(
        _supervisor_context(),
        delegate,
        receipt=receipt,
        capability=capability,
    )
    assert delegate.calls == 0
    assert (
        EnforcementDenialReason.ROOT_CHANGED.value
        in result.observation.reason_codes
    )


def test_enforce_rejects_environment_changed() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    delegate = _CountingDelegate()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(
        _supervisor_context(environment_digest=_DIGEST_1),
        delegate,
        receipt=receipt,
        capability=capability,
    )
    assert delegate.calls == 0
    assert (
        EnforcementDenialReason.ENVIRONMENT_CHANGED.value
        in result.observation.reason_codes
    )


def test_enforce_rejects_exact_context_mutation_actor() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    delegate = _CountingDelegate()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(
        _supervisor_context(actor_id="actor:eve"),
        delegate,
        receipt=receipt,
        capability=capability,
    )
    assert delegate.calls == 0
    assert result.observation.disposition is EnforcementDisposition.DENIED


def test_enforce_rejects_missing_receipt() -> None:
    delegate = _CountingDelegate()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(_supervisor_context(), delegate)
    assert delegate.calls == 0
    assert (
        EnforcementDenialReason.MISSING_RECEIPT.value
        in result.observation.reason_codes
    )


# ---------------------------------------------------------------------------
# Injected service + observation schema
# ---------------------------------------------------------------------------


def test_injected_service_supplies_receipt() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)

    class _FakeService:
        def evaluate(self, *, context: SupervisorInvocationContext) -> Any:
            assert context.task_id == "task:lig-037"
            return receipt, capability

    delegate = _CountingDelegate("from-service")
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        service=_FakeService(),
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(_supervisor_context(), delegate)
    assert delegate.calls == 1
    assert result.delegate_result == "from-service"
    assert result.observation.consumed is True


def test_observation_is_not_theorem_proof_and_json_serializable() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
    )
    result = enforcer.authorize_and_delegate(
        _supervisor_context(),
        _CountingDelegate(),
        receipt=receipt,
        capability=capability,
    )
    payload = result.observation.to_dict()
    assert payload["theorem_proof"] is False
    assert payload["interface"] == SUPERVISOR_PRE_INVOCATION_ENFORCEMENT_INTERFACE
    assert payload["schema"] == SUPERVISOR_ENFORCEMENT_OBSERVATION_SCHEMA
    encoded = json.dumps(payload, sort_keys=True)
    assert "theorem_proof" in encoded
    assert '"theorem_proof": false' in encoded
    # Construction hard-forces theorem_proof=False even if a caller tries.
    forced = EnforcementObservation(
        disposition=EnforcementDisposition.ALLOWED,
        mode=EnforcementMode.ENFORCE,
        allowed=True,
        delegated=True,
        reason_codes=(),
        theorem_proof=True,  # type: ignore[arg-type]
    )
    assert forced.theorem_proof is False


def test_module_helper_authorize_and_delegate() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    delegate = _CountingDelegate("helper")
    result = authorize_and_delegate(
        _supervisor_context(),
        delegate,
        mode=EnforcementMode.ENFORCE,
        expected_roots=_roots(),
        clock=lambda: _NOW_OK,
        receipt=receipt,
        capability=capability,
    )
    assert delegate.calls == 1
    assert result.observation.disposition is EnforcementDisposition.ALLOWED


def test_context_binds_supervisor_axes() -> None:
    ctx = _supervisor_context()
    payload = ctx.to_dict()
    for key in (
        "actor_id",
        "delegation_ids",
        "audience_id",
        "task_id",
        "plan_id",
        "tool_id",
        "arguments_digest",
        "effect_ids",
        "environment_digest",
    ):
        assert key in payload
    restored = SupervisorInvocationContext.from_dict(payload)
    assert restored.task_id == "task:lig-037"
    assert restored.plan_id == "plan:pre-dispatch"
    assert restored.delegation_ids == ("delegation:link-1",)


def test_pinned_roots_load_via_expected_roots_mapping() -> None:
    _require_datasets_auth()
    receipt = _allow_receipt()
    capability = _capability_for(receipt)
    roots_map = _roots().to_dict()
    enforcer = create_supervisor_enforcement(
        mode=EnforcementMode.ENFORCE,
        expected_roots=roots_map,
        clock=lambda: _NOW_OK,
    )
    result = enforcer.dispatch(
        _supervisor_context(),
        _CountingDelegate(),
        receipt=receipt,
        capability=capability,
    )
    assert result.delegate_called is True
    assert result.observation.consumed is True
