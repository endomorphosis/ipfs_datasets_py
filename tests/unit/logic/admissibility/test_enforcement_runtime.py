"""Unit tests for tenant-safe decision caching and pre-dispatch enforcement (LIG-036).

Evidence subset:

* non-allow rejection
* complete cache-key mutation
* tenant isolation
* TTL
* revocation/environment TOCTOU
* concurrent consumption receipt

Acceptance:

* Reject every non-allow; immediately verify actor/delegation/audience/request/
  arguments/tool/version/effects, nonce/expiry, policy/corpus/revocation roots
  and fresh environment; atomically compare-and-consume; fail closed on
  race/state/error; cache key binds complete invocation/context without secrets,
  never crosses tenant/context, uses short positive TTL and no unsafe
  negative/unknown reuse absent proved monotonicity; fake dispatch runs zero
  times on rejection and once on success; post-dispatch observation remains
  separate.
"""

from __future__ import annotations

import concurrent.futures
from typing import Any

import pytest

from ipfs_datasets_py.logic.admissibility.compose import InternalDecisionStatus
from ipfs_datasets_py.logic.admissibility.enforcement import (
    CAPABILITY_CONSUMPTION_STORE_INTERFACE,
    PRE_INVOCATION_ENFORCEMENT_INTERFACE,
    CapabilityConsumptionRecord,
    ConsumptionRaceError,
    DispatchObservation,
    EnforcementReasonCode,
    EnforcementRejection,
    EnforcementResult,
    FakeDispatcher,
    InMemoryCapabilityConsumptionStore,
    InvocationBinding,
    PreInvocationEnforcement,
    consume_dispatch_capability,
    verify_invocation_binding,
)
from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus
from ipfs_datasets_py.logic.admissibility.receipt import (
    AuthorizationCapability,
    BoundContext,
    BoundRoots,
    DecisionReceipt,
    build_decision_receipt,
    derive_capability,
)
from ipfs_datasets_py.logic.admissibility.runtime import (
    DECISION_CACHE_KEY_INTERFACE,
    DEFAULT_MAX_POSITIVE_TTL_SECONDS,
    DEFAULT_POSITIVE_TTL_SECONDS,
    AuthorizationRuntime,
    CacheEntryKind,
    DecisionCacheError,
    DecisionCacheKey,
    TenantSafeDecisionCache,
    build_decision_cache_key,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest


# ---------------------------------------------------------------------------
# Fixtures / helpers
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
_DIGEST_MUT = "9" * 64

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_EXPIRED = "2026-07-28T12:11:00Z"

_TENANT_A = "tenant:alpha"
_TENANT_B = "tenant:beta"


def _roots(**overrides: Any) -> BoundRoots:
    base = {
        "policy_root": "policy:root-v1",
        "corpus_roots": ("corpus:legal-v1", "corpus:security-v1"),
        "revocation_root": "revocation:root-v1",
        "circuit_roots": ("circuit:auth-v1",),
        "vk_roots": ("vk:auth-v1",),
    }
    base.update(overrides)
    return BoundRoots(**base)


def _context(**overrides: Any) -> BoundContext:
    base: dict[str, Any] = {
        "request_digest": _DIGEST_A,
        "arguments_digest": _DIGEST_B,
        "actor_id": "actor:alice",
        "audience_id": "audience:dispatcher-1",
        "tool_id": "tool:ledger.transfer",
        "tool_version": "1.2.3",
        "effect_ids": (
            "effect:ledger-write",
            "effect:notify",
            "effect:audit-log",
        ),
        "environment_digest": _DIGEST_C,
        "environment_id": "env:prod-sandbox",
        "delegation_ids": ("delegation:link-1",),
        "delegation_digest": _DIGEST_D,
        "resource_ids": ("resource:ledger", "resource:mailbox"),
        "capability_ids": ("capability:write",),
        "nonce": "nonce-abc-001",
        "metadata": FrozenMap({"tenant_id": _TENANT_A}),
    }
    base.update(overrides)
    return BoundContext(**base)


def _allow_receipt(**overrides: Any) -> DecisionReceipt:
    kwargs: dict[str, Any] = {
        "receipt_id": "receipt:allow-001",
        "context": _context(),
        "roots": _roots(),
        "outcome": InternalDecisionStatus.ALLOW,
        "reasons": ("positive grant proved", "non-conflict proved"),
        "reason_codes": ("allow.positive_grant", "allow.non_conflict"),
        "selected_evidence_cids": (
            "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
        ),
        "obligation_ids": ("obl:pre-check",),
        "residual_duties": ("duty:post-audit",),
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


def _receipt_for_status(
    status: InternalDecisionStatus, **overrides: Any
) -> DecisionReceipt:
    wire = {
        InternalDecisionStatus.ALLOW: AdmissibilityStatus.ALLOW,
        InternalDecisionStatus.DENY: AdmissibilityStatus.REJECT,
        InternalDecisionStatus.REVIEW: AdmissibilityStatus.ABSTAIN,
        InternalDecisionStatus.INDETERMINATE: AdmissibilityStatus.ABSTAIN,
        InternalDecisionStatus.ERROR: AdmissibilityStatus.ABSTAIN,
    }[status]
    return _allow_receipt(
        receipt_id=f"receipt:{status.value}",
        outcome=status,
        reasons=(f"status={status.value}",),
        reason_codes=(f"status.{status.value}",),
        **overrides,
    )


def _capability(
    receipt: DecisionReceipt | None = None, **overrides: Any
) -> AuthorizationCapability:
    receipt = receipt or _allow_receipt()
    kwargs: dict[str, Any] = {
        "capability_id": "cap:dispatch-001",
        "allowed_effects": ("effect:ledger-write",),
    }
    kwargs.update(overrides)
    return derive_capability(receipt, **kwargs)


def _binding(
    receipt: DecisionReceipt | None = None,
    *,
    tenant_id: str = _TENANT_A,
    **overrides: Any,
) -> InvocationBinding:
    receipt = receipt or _allow_receipt()
    base = InvocationBinding.from_receipt(receipt, tenant_id=tenant_id)
    if not overrides:
        return base
    data = base.to_dict()
    data.update(overrides)
    return InvocationBinding.from_dict(data)


def _enforcer(
    *,
    dispatcher: FakeDispatcher | None = None,
    store: InMemoryCapabilityConsumptionStore | None = None,
) -> tuple[PreInvocationEnforcement, FakeDispatcher, InMemoryCapabilityConsumptionStore]:
    store = store or InMemoryCapabilityConsumptionStore()
    dispatcher = dispatcher if dispatcher is not None else FakeDispatcher()
    enforcer = PreInvocationEnforcement(store=store, dispatcher=dispatcher)
    return enforcer, dispatcher, store


def _cache_key(
    receipt: DecisionReceipt | None = None,
    *,
    tenant_id: str = _TENANT_A,
    **overrides: Any,
) -> DecisionCacheKey:
    receipt = receipt or _allow_receipt()
    return build_decision_cache_key(
        tenant_id=tenant_id,
        receipt=receipt,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Non-allow rejection + zero dispatch
# ---------------------------------------------------------------------------


class TestNonAllowRejection:
    @pytest.mark.parametrize(
        "status",
        [
            InternalDecisionStatus.DENY,
            InternalDecisionStatus.REVIEW,
            InternalDecisionStatus.INDETERMINATE,
            InternalDecisionStatus.ERROR,
        ],
    )
    def test_rejects_every_non_allow(self, status: InternalDecisionStatus) -> None:
        receipt = _receipt_for_status(status)
        enforcer, dispatcher, _store = _enforcer()
        # Non-allow cannot derive capability; pass capability=None.
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=None,
            binding=_binding(receipt),
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert result.dispatch_ran is False
        assert dispatcher.call_count == 0
        assert result.observation is None
        assert result.reason_code in {
            EnforcementReasonCode.NON_ALLOW.value,
            EnforcementReasonCode.MISSING_CAPABILITY.value,
        }

    def test_reject_non_allow_even_if_forged_capability_present(self) -> None:
        allow = _allow_receipt()
        deny = _receipt_for_status(InternalDecisionStatus.DENY)
        # Capability derived from allow but paired with deny receipt.
        cap = _capability(allow)
        enforcer, dispatcher, _store = _enforcer()
        result = enforcer.enforce_and_dispatch(
            receipt=deny,
            capability=cap,
            binding=_binding(deny),
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert result.dispatch_ran is False
        assert dispatcher.call_count == 0
        assert result.reason_code == EnforcementReasonCode.NON_ALLOW.value

    def test_missing_receipt_rejects_without_dispatch(self) -> None:
        enforcer, dispatcher, _store = _enforcer()
        result = enforcer.enforce_and_dispatch(
            receipt=None,
            capability=_capability(),
            binding=_binding(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0
        assert result.reason_code == EnforcementReasonCode.MISSING_RECEIPT.value


# ---------------------------------------------------------------------------
# Successful path: verify, consume, dispatch once, separate observation
# ---------------------------------------------------------------------------


class TestSuccessfulDispatch:
    def test_allow_consumes_and_dispatches_once(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, store = _enforcer()
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            live_environment={
                "environment_id": "env:prod-sandbox",
                "environment_digest": _DIGEST_C,
            },
            now=_NOW_OK,
            dispatch_payload={"amount": 1},
        )
        assert result.allowed is True
        assert result.dispatch_ran is True
        assert dispatcher.call_count == 1
        assert result.consumption is not None
        assert result.consumption.capability_id == cap.capability_id
        assert store.is_consumed(cap.capability_id, tenant_id=_TENANT_A)
        assert result.observation is not None
        assert result.observation.is_authorization_receipt is False
        assert result.observation.dispatch_count == 1
        assert result.observation.dispatch_status == "ok"
        assert result.observation.schema_version
        # Observation is separate from the receipt identity.
        assert result.observation.receipt_id == receipt.receipt_id
        assert "post_dispatch" in result.observation.metadata.to_dict().get(
            "observation_kind", ""
        )

    def test_enforce_without_dispatch_still_consumes(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, store = _enforcer()
        result = enforcer.enforce(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            now=_NOW_OK,
            consume=True,
        )
        assert result.allowed is True
        assert result.dispatch_ran is False
        assert dispatcher.call_count == 0
        assert store.is_consumed(cap.capability_id, tenant_id=_TENANT_A)
        assert result.observation is None

    def test_second_dispatch_fails_closed_after_consumption(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        first = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert first.allowed is True
        assert dispatcher.call_count == 1
        second = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert second.allowed is False
        assert second.dispatch_ran is False
        assert dispatcher.call_count == 1  # still exactly one
        assert second.reason_code == EnforcementReasonCode.CONSUMPTION_RACE.value


# ---------------------------------------------------------------------------
# Immediate context / roots / environment verification (TOCTOU)
# ---------------------------------------------------------------------------


class TestImmediateRevalidation:
    def test_actor_mismatch_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        binding = _binding(receipt, actor_id="actor:eve")
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=binding,
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0
        assert result.reason_code in {
            EnforcementReasonCode.RECEIPT_INVALID.value,
            EnforcementReasonCode.CONTEXT_MISMATCH.value,
        }

    def test_audience_mismatch_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        binding = _binding(receipt, audience_id="audience:other")
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=binding,
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0

    def test_request_digest_mutation_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        binding = _binding(receipt, request_digest=_DIGEST_MUT)
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=binding,
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0

    def test_arguments_digest_mutation_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        binding = _binding(receipt, arguments_digest=_DIGEST_MUT)
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=binding,
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0
        assert result.reason_code == EnforcementReasonCode.CONTEXT_MISMATCH.value

    def test_tool_version_mutation_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        binding = _binding(receipt, tool_version="9.9.9")
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=binding,
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0

    def test_tool_id_mutation_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        binding = _binding(receipt, tool_id="tool:evil")
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=binding,
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0

    def test_delegation_mismatch_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        binding = _binding(
            receipt,
            delegation_ids=("delegation:forged",),
        )
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=binding,
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0

    def test_nonce_mismatch_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        binding = _binding(receipt, nonce="nonce-forged-999")
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=binding,
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0

    def test_expiry_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            now=_NOW_EXPIRED,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0

    def test_revocation_root_toctou_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        stale_roots = _roots(revocation_root="revocation:root-rotated")
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=stale_roots,
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0
        assert result.reason_code in {
            EnforcementReasonCode.ROOTS_MISMATCH.value,
            EnforcementReasonCode.RECEIPT_INVALID.value,
            EnforcementReasonCode.CAPABILITY_INVALID.value,
        }

    def test_policy_root_toctou_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(policy_root="policy:downgraded"),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0

    def test_environment_digest_toctou_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            live_environment={
                "environment_id": "env:prod-sandbox",
                "environment_digest": _DIGEST_MUT,
            },
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0
        assert (
            result.reason_code
            == EnforcementReasonCode.ENVIRONMENT_MISMATCH.value
        )

    def test_environment_id_toctou_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            live_environment={
                "environment_id": "env:hostile",
                "environment_digest": _DIGEST_C,
            },
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0

    def test_tenant_mismatch_rejects(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt, tenant_id=_TENANT_B),
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert dispatcher.call_count == 0
        assert result.reason_code == EnforcementReasonCode.TENANT_MISMATCH.value

    def test_verify_invocation_binding_raises_on_effect_widen(self) -> None:
        receipt = _allow_receipt()
        binding = _binding(
            receipt,
            effect_ids=(
                "effect:ledger-write",
                "effect:notify",
                "effect:audit-log",
                "effect:admin-wipe",
            ),
        )
        with pytest.raises(EnforcementRejection):
            verify_invocation_binding(
                receipt,
                binding,
                live_roots=_roots(),
                now=_NOW_OK,
            )


# ---------------------------------------------------------------------------
# Atomic compare-and-consume + concurrent race
# ---------------------------------------------------------------------------


class TestAtomicConsumption:
    def test_compare_and_consume_records_once(self) -> None:
        store = InMemoryCapabilityConsumptionStore()
        cap = _capability()
        record = store.compare_and_consume(
            cap, tenant_id=_TENANT_A, now=_NOW_OK
        )
        assert isinstance(record, CapabilityConsumptionRecord)
        assert store.is_consumed(cap.capability_id, tenant_id=_TENANT_A)
        with pytest.raises(ConsumptionRaceError):
            store.compare_and_consume(cap, tenant_id=_TENANT_A, now=_NOW_OK)

    def test_nonce_replay_across_capability_ids_fails(self) -> None:
        store = InMemoryCapabilityConsumptionStore()
        receipt = _allow_receipt()
        cap1 = _capability(receipt, capability_id="cap:a")
        # Same nonce (from receipt) with different capability id.
        cap2 = _capability(receipt, capability_id="cap:b")
        store.compare_and_consume(cap1, tenant_id=_TENANT_A, now=_NOW_OK)
        with pytest.raises(ConsumptionRaceError):
            store.compare_and_consume(cap2, tenant_id=_TENANT_A, now=_NOW_OK)

    def test_tenant_isolation_of_consumption(self) -> None:
        store = InMemoryCapabilityConsumptionStore()
        cap = _capability()
        store.compare_and_consume(cap, tenant_id=_TENANT_A, now=_NOW_OK)
        assert store.is_consumed(cap.capability_id, tenant_id=_TENANT_A)
        assert not store.is_consumed(cap.capability_id, tenant_id=_TENANT_B)
        # Different tenant may consume the same capability id (isolated).
        record_b = store.compare_and_consume(
            cap, tenant_id=_TENANT_B, now=_NOW_OK
        )
        assert record_b.tenant_id == _TENANT_B

    def test_concurrent_consumption_allows_exactly_one(self) -> None:
        store = InMemoryCapabilityConsumptionStore()
        cap = _capability()
        successes = []
        failures = []

        def attempt() -> None:
            try:
                record = store.compare_and_consume(
                    cap, tenant_id=_TENANT_A, now=_NOW_OK
                )
                successes.append(record)
            except ConsumptionRaceError:
                failures.append("race")

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            futs = [pool.submit(attempt) for _ in range(32)]
            for fut in concurrent.futures.as_completed(futs):
                fut.result()

        assert len(successes) == 1
        assert len(failures) == 31
        assert store.size() == 1

    def test_concurrent_enforce_and_dispatch_single_call(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, dispatcher, _store = _enforcer()
        outcomes: list[bool] = []

        def attempt() -> None:
            result = enforcer.enforce_and_dispatch(
                receipt=receipt,
                capability=cap,
                binding=_binding(receipt),
                live_roots=_roots(),
                now=_NOW_OK,
            )
            outcomes.append(result.allowed)

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            futs = [pool.submit(attempt) for _ in range(24)]
            for fut in concurrent.futures.as_completed(futs):
                fut.result()

        assert sum(1 for o in outcomes if o) == 1
        assert sum(1 for o in outcomes if not o) == 23
        assert dispatcher.call_count == 1

    def test_consume_dispatch_capability_helper(self) -> None:
        store = InMemoryCapabilityConsumptionStore()
        cap = _capability()
        record = consume_dispatch_capability(
            store, cap, tenant_id=_TENANT_A, now=_NOW_OK
        )
        assert record.capability_id == cap.capability_id
        assert store.interface == CAPABILITY_CONSUMPTION_STORE_INTERFACE


# ---------------------------------------------------------------------------
# Decision cache key: complete binding, no secrets, mutation sensitivity
# ---------------------------------------------------------------------------


class TestDecisionCacheKey:
    def test_builds_stable_digest(self) -> None:
        key = _cache_key()
        assert key.interface == DECISION_CACHE_KEY_INTERFACE
        assert len(key.digest) == 64
        again = _cache_key()
        assert key.digest == again.digest

    def test_complete_mutation_changes_digest(self) -> None:
        base = _cache_key()
        mutations = {
            "tenant_id": _TENANT_B,
            "actor_id": "actor:bob",
            "audience_id": "audience:other",
            "request_digest": _DIGEST_MUT,
            "arguments_digest": _DIGEST_1,
            "tool_id": "tool:other",
            "tool_version": "0.0.1",
            "effect_ids": ("effect:only",),
            "environment_digest": _DIGEST_MUT,
            "environment_id": "env:other",
            "policy_root": "policy:other",
            "corpus_roots": ("corpus:other",),
            "revocation_root": "revocation:other",
            "circuit_roots": ("circuit:other",),
            "vk_roots": ("vk:other",),
            "profile_id": "profile:open",
            "purpose": "purpose:debug",
            "delegation_digest": _DIGEST_MUT,
            "delegation_ids": ("delegation:x",),
        }
        for field, value in mutations.items():
            mutated = base.with_mutation(**{field: value})
            assert mutated.digest != base.digest, field

    def test_to_dict_strips_secrets(self) -> None:
        key = _cache_key()
        payload = key.to_dict()
        # Injected secret fields must never appear via from_dict round-trip.
        dirty = dict(payload)
        dirty["secret"] = "super-secret"
        dirty["api_key"] = "sk-live-xxx"
        dirty["token"] = "bearer-yyy"
        rebuilt = DecisionCacheKey.from_dict(dirty)
        as_dict = rebuilt.to_dict()
        assert "secret" not in as_dict
        assert "api_key" not in as_dict
        assert "token" not in as_dict
        # Digest still matches the clean key identity.
        assert rebuilt.digest == key.digest

    def test_rejects_empty_tenant(self) -> None:
        with pytest.raises(DecisionCacheError):
            DecisionCacheKey(
                tenant_id="",
                actor_id="actor:alice",
                audience_id="audience:dispatcher-1",
                request_digest=_DIGEST_A,
                arguments_digest=_DIGEST_B,
            )

    def test_build_from_receipt_pulls_tenant_metadata(self) -> None:
        receipt = _allow_receipt()
        key = build_decision_cache_key(tenant_id="", receipt=receipt)
        assert key.tenant_id == _TENANT_A
        assert key.policy_root == receipt.roots.policy_root
        assert key.actor_id == receipt.actor_id


# ---------------------------------------------------------------------------
# Tenant-safe cache: isolation, TTL, no unsafe negative reuse
# ---------------------------------------------------------------------------


class TestTenantSafeDecisionCache:
    def test_positive_allow_cached_with_short_ttl(self) -> None:
        cache = TenantSafeDecisionCache(positive_ttl_seconds=30)
        key = _cache_key()
        receipt = _allow_receipt()
        now = 1000.0
        stored = cache.put_from_receipt(key, receipt, now_monotonic=now)
        assert stored is not None
        assert stored.kind is CacheEntryKind.ALLOW
        assert stored.ttl_seconds == 30
        hit = cache.get(key, now_monotonic=now + 10)
        assert hit is not None
        assert hit.decision_digest == receipt.decision_digest

    def test_ttl_expiry_is_miss(self) -> None:
        cache = TenantSafeDecisionCache(positive_ttl_seconds=5)
        key = _cache_key()
        receipt = _allow_receipt()
        now = 1000.0
        cache.put_from_receipt(key, receipt, now_monotonic=now)
        assert cache.get(key, now_monotonic=now + 4) is not None
        assert cache.get(key, now_monotonic=now + 6) is None
        # Expired entry does not leave a negative residue.
        assert cache.stats()["size"] == 0

    def test_ttl_capped_at_max(self) -> None:
        cache = TenantSafeDecisionCache(
            positive_ttl_seconds=DEFAULT_POSITIVE_TTL_SECONDS,
            max_positive_ttl_seconds=DEFAULT_MAX_POSITIVE_TTL_SECONDS,
        )
        key = _cache_key()
        entry = cache.put(
            key,
            status=InternalDecisionStatus.ALLOW,
            ttl_seconds=9999,
            now_monotonic=0.0,
        )
        assert entry is not None
        assert entry.ttl_seconds == DEFAULT_MAX_POSITIVE_TTL_SECONDS

    def test_zero_ttl_allow_rejected(self) -> None:
        cache = TenantSafeDecisionCache()
        key = _cache_key()
        entry = cache.put(
            key,
            status=InternalDecisionStatus.ALLOW,
            ttl_seconds=0,
            now_monotonic=0.0,
        )
        assert entry is None
        assert cache.stats()["rejected_stores"] == 1

    def test_negative_not_cached_without_monotonicity(self) -> None:
        cache = TenantSafeDecisionCache()
        key = _cache_key()
        for status in (
            InternalDecisionStatus.DENY,
            InternalDecisionStatus.REVIEW,
            InternalDecisionStatus.INDETERMINATE,
            InternalDecisionStatus.ERROR,
        ):
            entry = cache.put(key, status=status, now_monotonic=0.0)
            assert entry is None, status
        assert cache.get(key, now_monotonic=0.0) is None
        assert cache.stats()["rejected_stores"] >= 4

    def test_negative_cached_only_with_proved_monotonicity(self) -> None:
        cache = TenantSafeDecisionCache(negative_ttl_seconds=10)
        key = _cache_key()
        entry = cache.put(
            key,
            status=InternalDecisionStatus.DENY,
            monotonic_negative=True,
            now_monotonic=50.0,
        )
        assert entry is not None
        assert entry.kind is CacheEntryKind.NEGATIVE
        assert entry.monotonic_negative is True
        assert cache.get(key, now_monotonic=55.0) is not None

    def test_tenant_isolation_never_crosses(self) -> None:
        cache = TenantSafeDecisionCache()
        receipt = _allow_receipt()
        key_a = _cache_key(receipt, tenant_id=_TENANT_A)
        key_b = _cache_key(receipt, tenant_id=_TENANT_B)
        assert key_a.digest != key_b.digest
        cache.put_from_receipt(key_a, receipt, now_monotonic=0.0)
        assert cache.get(key_a, now_monotonic=1.0) is not None
        assert cache.get(key_b, now_monotonic=1.0) is None
        # Even if an attacker reuses the same digest under another tenant
        # bucket, storage is domain-separated by tenant_id.
        with cache._lock:  # noqa: SLF001 — intentional isolation probe
            bucket_b = cache._entries.get(_TENANT_B, {})
            assert key_a.digest not in bucket_b

    def test_context_mutation_is_cache_miss(self) -> None:
        cache = TenantSafeDecisionCache()
        receipt = _allow_receipt()
        key = _cache_key(receipt)
        cache.put_from_receipt(key, receipt, now_monotonic=0.0)
        mutated = key.with_mutation(tool_version="2.0.0")
        assert cache.get(mutated, now_monotonic=1.0) is None

    def test_invalidate_tenant(self) -> None:
        cache = TenantSafeDecisionCache()
        receipt = _allow_receipt()
        cache.put_from_receipt(
            _cache_key(receipt, tenant_id=_TENANT_A),
            receipt,
            now_monotonic=0.0,
        )
        cache.put_from_receipt(
            _cache_key(receipt, tenant_id=_TENANT_B),
            receipt,
            now_monotonic=0.0,
        )
        removed = cache.invalidate_tenant(_TENANT_A)
        assert removed == 1
        assert cache.get(_cache_key(receipt, tenant_id=_TENANT_A), now_monotonic=1.0) is None
        assert cache.get(_cache_key(receipt, tenant_id=_TENANT_B), now_monotonic=1.0) is not None


# ---------------------------------------------------------------------------
# AuthorizationRuntime glue
# ---------------------------------------------------------------------------


class TestAuthorizationRuntime:
    def test_runtime_cache_hit_still_enforces(self) -> None:
        runtime = AuthorizationRuntime()
        receipt = _allow_receipt()
        cap = _capability(receipt)
        key = _cache_key(receipt)
        stored = runtime.cache_decision(key, receipt)
        assert stored is not None
        assert runtime.lookup_decision(key) is not None

        result = runtime.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            now=_NOW_OK,
            cache_key=key,
        )
        assert result.allowed is True
        assert result.dispatch_ran is True
        assert runtime.dispatcher is not None
        assert runtime.dispatcher.call_count == 1

    def test_runtime_rejection_zero_dispatch(self) -> None:
        runtime = AuthorizationRuntime()
        deny = _receipt_for_status(InternalDecisionStatus.DENY)
        result = runtime.enforce_and_dispatch(
            receipt=deny,
            capability=None,
            binding=_binding(deny),
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert runtime.dispatcher is not None
        assert runtime.dispatcher.call_count == 0

    def test_interfaces_are_stable(self) -> None:
        assert PRE_INVOCATION_ENFORCEMENT_INTERFACE == "PreInvocationEnforcement@1"
        assert DECISION_CACHE_KEY_INTERFACE == "DecisionCacheKey@1"
        assert CAPABILITY_CONSUMPTION_STORE_INTERFACE == (
            "CapabilityConsumptionStore@1"
        )
        enforcer, _, _ = _enforcer()
        assert enforcer.interface == PRE_INVOCATION_ENFORCEMENT_INTERFACE
        result = enforcer.enforce(
            receipt=_allow_receipt(),
            capability=_capability(),
            binding=_binding(),
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert isinstance(result, EnforcementResult)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Observation separation + dispatch error path
# ---------------------------------------------------------------------------


class TestObservationSeparation:
    def test_observation_is_not_receipt(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        enforcer, _dispatcher, _store = _enforcer()
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            now=_NOW_OK,
        )
        obs = result.observation
        assert obs is not None
        assert isinstance(obs, DispatchObservation)
        assert obs.is_authorization_receipt is False
        # Must not share the receipt interface string.
        assert "DecisionReceipt" not in obs.schema_version
        assert obs.to_dict()["observation_id"]

    def test_dispatch_error_after_consume_records_observation(self) -> None:
        receipt = _allow_receipt()
        cap = _capability(receipt)
        dispatcher = FakeDispatcher(raise_on_call=RuntimeError("boom"))
        enforcer, dispatcher, store = _enforcer(dispatcher=dispatcher)
        result = enforcer.enforce_and_dispatch(
            receipt=receipt,
            capability=cap,
            binding=_binding(receipt),
            live_roots=_roots(),
            now=_NOW_OK,
        )
        assert result.allowed is False
        assert result.dispatch_ran is True
        assert dispatcher.call_count == 1
        assert store.is_consumed(cap.capability_id, tenant_id=_TENANT_A)
        assert result.observation is not None
        assert result.observation.dispatch_status == "error"
        assert "boom" in result.observation.error_message
        assert (
            result.reason_code == EnforcementReasonCode.DISPATCH_ERROR.value
        )
