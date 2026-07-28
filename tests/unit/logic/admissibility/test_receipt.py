"""Unit tests for exact-context decision receipts and capabilities (LIG-034).

Evidence subset:

* receipt identity
* outcome mapping
* context mutation
* attenuation
* audience
* expiry
* replay receipt

Acceptance:

* Bind request/arguments/actor/delegation/audience/tool/effects/environment,
  selected evidence, obligations/attempts/results, policy/corpus/revocation/
  circuit/VK roots, outcome/reasons/residual duties, nonce/issued/deadline/
  expiry and producer.
* Derive capability only from allow; require strict subset attenuation and
  one-time marker.
* Reject mutation/widening/wrong audience/stale roots/expiry/unknown
  schema-algorithm and all non-allow derivation.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from ipfs_datasets_py.logic.admissibility.compose import (
    AuthorizationDecision,
    InternalDecisionStatus,
    map_internal_to_wire,
)
from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus
from ipfs_datasets_py.logic.admissibility.receipt import (
    AUTHORIZATION_CAPABILITY_INTERFACE,
    AUTHORIZATION_CAPABILITY_SCHEMA_VERSION,
    DECISION_RECEIPT_INTERFACE,
    DECISION_RECEIPT_SCHEMA_VERSION,
    DEFAULT_IDENTITY_ALGORITHM,
    AuthorizationCapability,
    BoundContext,
    BoundRoots,
    CapabilityDerivationError,
    DecisionReceipt,
    ReceiptError,
    ReceiptVerificationError,
    attenuate_capability,
    build_decision_receipt,
    derive_capability,
    receipt_context_fingerprint,
    verify_capability,
    verify_decision_receipt,
)
from ipfs_datasets_py.logic.ir_core.claims import stable_digest


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

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_PAST_DEADLINE = "2026-07-28T12:06:00Z"
_NOW_EXPIRED = "2026-07-28T12:11:00Z"


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
    base = {
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
            "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku",
        ),
        "obligation_ids": ("obl:pre-check", "obl:coverage"),
        "residual_duties": ("duty:post-audit",),
        "attempt_digests": (_DIGEST_1, _DIGEST_2),
        "result_digests": (_DIGEST_3,),
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
    return _allow_receipt(
        receipt_id=f"receipt:{status.value}",
        outcome=status,
        reasons=(f"status={status.value}",),
        reason_codes=(f"code.{status.value}",),
        **overrides,
    )


# ---------------------------------------------------------------------------
# Bound roots / context
# ---------------------------------------------------------------------------


class TestBoundRootsAndContext:
    def test_roots_sorted_unique_and_digest_stable(self) -> None:
        a = _roots(
            corpus_roots=("corpus:b", "corpus:a"),
            circuit_roots=("circuit:z", "circuit:a"),
        )
        b = _roots(
            corpus_roots=("corpus:a", "corpus:b"),
            circuit_roots=("circuit:a", "circuit:z"),
        )
        assert a.corpus_roots == ("corpus:a", "corpus:b")
        assert a.digest == b.digest
        assert a.matches(b)
        assert BoundRoots.from_dict(a.to_dict()).digest == a.digest

    def test_roots_reject_unknown_schema(self) -> None:
        with pytest.raises(ReceiptError, match="unsupported bound-roots schema"):
            BoundRoots(
                policy_root="policy:x",
                schema_version="bound-roots/v999",
            )

    def test_context_binds_all_required_fields(self) -> None:
        ctx = _context()
        payload = ctx.to_dict()
        for key in (
            "request_digest",
            "arguments_digest",
            "actor_id",
            "audience_id",
            "tool_id",
            "effect_ids",
            "environment_digest",
            "delegation_ids",
            "nonce",
        ):
            assert key in payload
        assert BoundContext.from_dict(payload).digest == ctx.digest

    def test_context_rejects_bad_digest(self) -> None:
        with pytest.raises(ReceiptError, match="request_digest"):
            _context(request_digest="not-a-digest")


# ---------------------------------------------------------------------------
# Decision receipt identity, binding, outcome mapping
# ---------------------------------------------------------------------------


class TestDecisionReceipt:
    def test_builds_allow_receipt_with_full_binding(self) -> None:
        receipt = _allow_receipt()
        assert receipt.interface == DECISION_RECEIPT_INTERFACE
        assert receipt.schema_version == DECISION_RECEIPT_SCHEMA_VERSION
        assert receipt.is_allow
        assert receipt.permits_capability_derivation
        assert receipt.wire_status is AdmissibilityStatus.ALLOW
        assert receipt.outcome is InternalDecisionStatus.ALLOW
        assert receipt.content_digest.startswith("sha256:")
        assert receipt.content_cid.startswith("b")
        assert receipt.producer_id == "producer:auth-service"
        assert receipt.nonce == "nonce-abc-001"
        assert "effect:ledger-write" in receipt.effect_ids
        assert receipt.roots.policy_root == "policy:root-v1"
        assert "corpus:legal-v1" in receipt.roots.corpus_roots
        assert receipt.roots.revocation_root == "revocation:root-v1"
        assert "circuit:auth-v1" in receipt.roots.circuit_roots
        assert "vk:auth-v1" in receipt.roots.vk_roots
        assert receipt.residual_duties == ("duty:post-audit",)
        assert len(receipt.attempt_digests) == 2
        assert len(receipt.result_digests) == 1
        assert receipt.selected_evidence_cids
        assert receipt.obligation_ids

    def test_identity_stable_across_rebuild(self) -> None:
        a = _allow_receipt()
        b = DecisionReceipt.from_dict(a.to_dict())
        assert a.content_digest == b.content_digest
        assert a.content_cid == b.content_cid
        assert a.digest == b.digest
        b.verify_integrity()

    def test_replay_same_inputs_same_identity(self) -> None:
        a = _allow_receipt()
        b = _allow_receipt()
        assert a.content_digest == b.content_digest
        assert receipt_context_fingerprint(a) == receipt_context_fingerprint(b)

    def test_context_mutation_changes_identity(self) -> None:
        base = _allow_receipt()
        mutated = _allow_receipt(
            context=_context(actor_id="actor:eve"),
            receipt_id="receipt:mutated-actor",
        )
        assert base.content_digest != mutated.content_digest
        assert receipt_context_fingerprint(base) != receipt_context_fingerprint(
            mutated
        )

    @pytest.mark.parametrize(
        "field,mutator",
        [
            ("actor", lambda: _context(actor_id="actor:other")),
            ("audience", lambda: _context(audience_id="audience:other")),
            ("tool", lambda: _context(tool_id="tool:other")),
            ("arguments", lambda: _context(arguments_digest=_DIGEST_1)),
            ("effects", lambda: _context(effect_ids=("effect:other",))),
            ("environment", lambda: _context(environment_digest=_DIGEST_2)),
            ("nonce", lambda: _context(nonce="nonce-mutated")),
            ("request", lambda: _context(request_digest=_DIGEST_3)),
            ("delegation", lambda: _context(delegation_digest=_DIGEST_F)),
        ],
    )
    def test_security_relevant_context_mutations_change_fingerprint(
        self, field: str, mutator: Any
    ) -> None:
        base = _allow_receipt()
        mutated = _allow_receipt(
            receipt_id=f"receipt:mut-{field}",
            context=mutator(),
        )
        assert receipt_context_fingerprint(base) != receipt_context_fingerprint(
            mutated
        ), field

    def test_root_mutation_changes_identity(self) -> None:
        base = _allow_receipt()
        mutated = _allow_receipt(
            receipt_id="receipt:stale-roots",
            roots=_roots(policy_root="policy:root-v0-stale"),
        )
        assert base.content_digest != mutated.content_digest

    def test_outcome_mapping_for_all_internal_statuses(self) -> None:
        for status in InternalDecisionStatus:
            receipt = _receipt_for_status(status)
            assert receipt.wire_status is map_internal_to_wire(status)
            if status is InternalDecisionStatus.ALLOW:
                assert receipt.wire_status is AdmissibilityStatus.ALLOW
                assert receipt.permits_capability_derivation
            elif status is InternalDecisionStatus.DENY:
                assert receipt.wire_status is AdmissibilityStatus.REJECT
                assert not receipt.permits_capability_derivation
            else:
                assert receipt.wire_status is AdmissibilityStatus.ABSTAIN
                assert not receipt.permits_capability_derivation

    def test_inconsistent_wire_status_rejected(self) -> None:
        with pytest.raises(ReceiptError, match="wire_status"):
            DecisionReceipt(
                receipt_id="receipt:bad-wire",
                context=_context(),
                roots=_roots(),
                outcome=InternalDecisionStatus.ALLOW,
                wire_status=AdmissibilityStatus.REJECT,
                reasons=("x",),
                reason_codes=("y",),
                selected_evidence_cids=(),
                selected_evidence_digest=_DIGEST_A,
                obligation_ids=(),
                residual_duties=(),
                attempt_digests=(),
                result_digests=(),
                decision_digest=_DIGEST_B,
                policy_digest=_DIGEST_C,
                profile_id="profile:closed-world",
                issued_at=_ISSUED,
                deadline=_DEADLINE,
                expiry=_EXPIRY,
                producer_id="producer:auth-service",
            )

    def test_unknown_schema_rejected(self) -> None:
        payload = _allow_receipt().to_dict()
        payload["schema_version"] = "decision-receipt/v999"
        with pytest.raises(ReceiptError, match="schema"):
            DecisionReceipt.from_dict(payload)

    def test_unknown_schema_via_from_dict(self) -> None:
        payload = _allow_receipt().to_dict()
        payload["schema_version"] = "decision-receipt/v0"
        with pytest.raises(ReceiptError, match="schema"):
            DecisionReceipt.from_dict(payload)

    def test_unknown_algorithm_rejected(self) -> None:
        with pytest.raises(ReceiptError, match="unknown identity_algorithm"):
            _allow_receipt(identity_algorithm="md5-legacy/v0")

    def test_tampered_content_digest_rejected(self) -> None:
        payload = _allow_receipt().to_dict()
        payload["content_digest"] = "sha256:" + ("0" * 64)
        with pytest.raises(ReceiptError, match="content_digest"):
            DecisionReceipt.from_dict(payload)

    def test_unknown_field_rejected(self) -> None:
        payload = _allow_receipt().to_dict()
        payload["extra_field"] = "nope"
        with pytest.raises(ReceiptError, match="unknown decision receipt field"):
            DecisionReceipt.from_dict(payload)

    def test_binds_authorization_decision_when_supplied(self) -> None:
        decision = AuthorizationDecision(
            status=InternalDecisionStatus.ALLOW,
            wire_status=AdmissibilityStatus.ALLOW,
            reasons=("grant",),
            job_results=(),
            bundle_digest=_DIGEST_A,
            policy_digest=_DIGEST_B,
            profile_id="profile:closed-world",
            reason_codes=("allow.positive_grant",),
            selected_evidence_cids=(
                "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
            ),
            residual_obligations=("duty:post",),
        )
        receipt = build_decision_receipt(
            receipt_id="receipt:from-decision",
            context=_context(),
            roots=_roots(),
            outcome=InternalDecisionStatus.DENY,  # overridden by decision
            profile_id="profile:ignored",
            issued_at=_ISSUED,
            deadline=_DEADLINE,
            expiry=_EXPIRY,
            producer_id="producer:auth-service",
            decision=decision,
        )
        assert receipt.outcome is InternalDecisionStatus.ALLOW
        assert receipt.decision_digest == decision.digest
        assert receipt.policy_digest == decision.policy_digest
        assert receipt.residual_duties == ("duty:post",)
        assert receipt.selected_evidence_cids == decision.selected_evidence_cids

    def test_time_ordering_enforced(self) -> None:
        with pytest.raises(ReceiptError, match="deadline"):
            _allow_receipt(deadline="2026-07-28T11:00:00Z")
        with pytest.raises(ReceiptError, match="expiry"):
            _allow_receipt(expiry="2026-07-28T12:01:00Z", deadline=_DEADLINE)


# ---------------------------------------------------------------------------
# Receipt verification
# ---------------------------------------------------------------------------


class TestVerifyDecisionReceipt:
    def test_verify_happy_path(self) -> None:
        receipt = _allow_receipt()
        out = verify_decision_receipt(
            receipt,
            now=_NOW_OK,
            expected_roots=_roots(),
            expected_audience="audience:dispatcher-1",
            expected_actor="actor:alice",
            expected_nonce="nonce-abc-001",
            expected_request_digest=_DIGEST_A,
        )
        assert out.content_digest == receipt.content_digest

    def test_verify_accepts_mapping_roundtrip(self) -> None:
        receipt = _allow_receipt()
        out = verify_decision_receipt(receipt.to_dict(), now=_NOW_OK)
        assert out.receipt_id == receipt.receipt_id

    def test_reject_wrong_audience(self) -> None:
        with pytest.raises(ReceiptVerificationError, match="audience"):
            verify_decision_receipt(
                _allow_receipt(), expected_audience="audience:other"
            )

    def test_reject_stale_roots(self) -> None:
        with pytest.raises(ReceiptVerificationError, match="stale|roots"):
            verify_decision_receipt(
                _allow_receipt(),
                expected_roots=_roots(policy_root="policy:old"),
            )

    def test_reject_expired(self) -> None:
        with pytest.raises(ReceiptVerificationError, match="expired"):
            verify_decision_receipt(_allow_receipt(), now=_NOW_EXPIRED)

    def test_reject_past_deadline(self) -> None:
        with pytest.raises(ReceiptVerificationError, match="deadline"):
            verify_decision_receipt(_allow_receipt(), now=_NOW_PAST_DEADLINE)

    def test_reject_request_mutation(self) -> None:
        with pytest.raises(ReceiptVerificationError, match="request_digest"):
            verify_decision_receipt(
                _allow_receipt(),
                expected_request_digest=_DIGEST_1,
            )

    def test_reject_nonce_mismatch(self) -> None:
        with pytest.raises(ReceiptVerificationError, match="nonce"):
            verify_decision_receipt(
                _allow_receipt(), expected_nonce="nonce-other"
            )

    def test_mutated_payload_fails_integrity(self) -> None:
        payload = _allow_receipt().to_dict()
        # Keep content_digest, mutate a bound field → integrity fails on rebuild
        # (from_dict recomputes and mismatches stored digest).
        payload["producer_id"] = "producer:attacker"
        with pytest.raises(ReceiptError, match="content_digest"):
            DecisionReceipt.from_dict(payload)


# ---------------------------------------------------------------------------
# Capability derivation, attenuation, verification
# ---------------------------------------------------------------------------


class TestAuthorizationCapability:
    def test_derive_only_from_allow(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:dispatch-1",
            allowed_effects=("effect:ledger-write",),
        )
        assert cap.interface == AUTHORIZATION_CAPABILITY_INTERFACE
        assert cap.schema_version == AUTHORIZATION_CAPABILITY_SCHEMA_VERSION
        assert cap.one_time is True
        assert cap.audience_id == receipt.audience_id
        assert cap.receipt_digest == receipt.digest
        assert cap.nonce == receipt.nonce
        assert cap.allowed_effects == ("effect:ledger-write",)
        assert cap.roots.matches(receipt.roots)
        cap.verify_integrity()

    @pytest.mark.parametrize(
        "status",
        [
            InternalDecisionStatus.DENY,
            InternalDecisionStatus.REVIEW,
            InternalDecisionStatus.INDETERMINATE,
            InternalDecisionStatus.ERROR,
        ],
    )
    def test_reject_non_allow_derivation(
        self, status: InternalDecisionStatus
    ) -> None:
        receipt = _receipt_for_status(status)
        with pytest.raises(
            CapabilityDerivationError, match="allow decision receipt"
        ):
            derive_capability(
                receipt,
                capability_id="cap:bad",
                allowed_effects=("effect:ledger-write",),
            )

    def test_require_strict_subset_attenuation(self) -> None:
        receipt = _allow_receipt()
        # Full copy of multi-effect set is rejected under strict subset.
        with pytest.raises(
            CapabilityDerivationError, match="strict subset"
        ):
            derive_capability(
                receipt,
                capability_id="cap:full",
                allowed_effects=receipt.effect_ids,
            )
        # Proper subset accepted.
        cap = derive_capability(
            receipt,
            capability_id="cap:subset",
            allowed_effects=("effect:ledger-write", "effect:notify"),
        )
        assert set(cap.allowed_effects) < set(receipt.effect_ids)

    def test_single_effect_receipt_allows_equality(self) -> None:
        receipt = _allow_receipt(
            context=_context(effect_ids=("effect:only",)),
            receipt_id="receipt:single-effect",
        )
        cap = derive_capability(
            receipt,
            capability_id="cap:only",
            allowed_effects=("effect:only",),
        )
        assert cap.allowed_effects == ("effect:only",)

    def test_reject_widening_effects(self) -> None:
        receipt = _allow_receipt()
        with pytest.raises(CapabilityDerivationError, match="subset|widening"):
            derive_capability(
                receipt,
                capability_id="cap:wide",
                allowed_effects=("effect:ledger-write", "effect:admin"),
            )

    def test_reject_widening_resources(self) -> None:
        receipt = _allow_receipt()
        with pytest.raises(CapabilityDerivationError, match="resource"):
            derive_capability(
                receipt,
                capability_id="cap:wide-res",
                allowed_effects=("effect:ledger-write",),
                resource_ids=("resource:ledger", "resource:secrets"),
            )

    def test_reject_wrong_audience_on_derive(self) -> None:
        receipt = _allow_receipt()
        with pytest.raises(CapabilityDerivationError, match="audience"):
            derive_capability(
                receipt,
                capability_id="cap:aud",
                allowed_effects=("effect:ledger-write",),
                audience_id="audience:other",
            )

    def test_reject_expiry_beyond_receipt(self) -> None:
        receipt = _allow_receipt()
        with pytest.raises(CapabilityDerivationError, match="expiry"):
            derive_capability(
                receipt,
                capability_id="cap:long",
                allowed_effects=("effect:ledger-write",),
                expiry="2026-07-28T13:00:00Z",
            )

    def test_one_time_marker_required(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:ot",
            allowed_effects=("effect:ledger-write",),
        )
        payload = cap.to_dict()
        payload["one_time"] = False
        # from_dict will recompute identity; one_time=False fails validation
        with pytest.raises(ReceiptError, match="one-time"):
            AuthorizationCapability.from_dict(payload)

    def test_re_attenuation_requires_strict_subset(self) -> None:
        receipt = _allow_receipt()
        parent = derive_capability(
            receipt,
            capability_id="cap:parent",
            allowed_effects=("effect:ledger-write", "effect:notify"),
        )
        child = attenuate_capability(
            parent,
            capability_id="cap:child",
            allowed_effects=("effect:ledger-write",),
        )
        assert child.parent_capability_id == parent.capability_id
        assert child.parent_capability_digest == parent.digest
        assert child.allowed_effects == ("effect:ledger-write",)
        assert child.one_time is True

        with pytest.raises(CapabilityDerivationError, match="strict subset"):
            attenuate_capability(
                parent,
                capability_id="cap:copy",
                allowed_effects=parent.allowed_effects,
            )
        with pytest.raises(CapabilityDerivationError, match="strict subset"):
            attenuate_capability(
                parent,
                capability_id="cap:wide",
                allowed_effects=(
                    "effect:ledger-write",
                    "effect:notify",
                    "effect:audit-log",
                ),
            )

    def test_verify_capability_happy_path(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:ok",
            allowed_effects=("effect:ledger-write",),
        )
        out = verify_capability(
            cap,
            receipt,
            now=_NOW_OK,
            expected_audience="audience:dispatcher-1",
            expected_roots=_roots(),
            expected_request_digest=_DIGEST_A,
        )
        assert out.capability_id == "cap:ok"

    def test_verify_capability_rejects_wrong_audience(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:aud2",
            allowed_effects=("effect:ledger-write",),
        )
        with pytest.raises(ReceiptVerificationError, match="audience"):
            verify_capability(cap, expected_audience="audience:other")

    def test_verify_capability_rejects_stale_roots(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:roots",
            allowed_effects=("effect:ledger-write",),
        )
        with pytest.raises(ReceiptVerificationError, match="stale|roots"):
            verify_capability(
                cap, expected_roots=_roots(revocation_root="revocation:old")
            )

    def test_verify_capability_rejects_expiry(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:exp",
            allowed_effects=("effect:ledger-write",),
        )
        with pytest.raises(ReceiptVerificationError, match="expired"):
            verify_capability(cap, now=_NOW_EXPIRED)

    def test_verify_capability_rejects_receipt_mutation(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:mut",
            allowed_effects=("effect:ledger-write",),
        )
        other = _allow_receipt(
            receipt_id="receipt:other",
            context=_context(nonce="nonce-other"),
        )
        with pytest.raises(ReceiptVerificationError, match="receipt"):
            verify_capability(cap, other)

    def test_verify_capability_rejects_non_allow_receipt_binding(self) -> None:
        allow = _allow_receipt()
        cap = derive_capability(
            allow,
            capability_id="cap:deny-bind",
            allowed_effects=("effect:ledger-write",),
        )
        # Same receipt_id as the allow receipt but non-allow outcome.
        deny = _allow_receipt(
            receipt_id=allow.receipt_id,
            outcome=InternalDecisionStatus.DENY,
            reasons=("denied",),
            reason_codes=("deny.hard",),
        )
        with pytest.raises(ReceiptVerificationError, match="non-allow|receipt"):
            verify_capability(cap, deny)

    def test_unknown_capability_schema_rejected(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:schema",
            allowed_effects=("effect:ledger-write",),
        )
        payload = cap.to_dict()
        payload["schema_version"] = "authorization-capability/v999"
        with pytest.raises(ReceiptError, match="schema"):
            AuthorizationCapability.from_dict(payload)

    def test_unknown_capability_algorithm_rejected(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:alg",
            allowed_effects=("effect:ledger-write",),
        )
        payload = cap.to_dict()
        payload["identity_algorithm"] = "unknown-alg/v0"
        with pytest.raises(ReceiptError, match="unknown identity_algorithm"):
            AuthorizationCapability.from_dict(payload)

    def test_default_attenuation_picks_strict_subset(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(receipt, capability_id="cap:default")
        assert len(cap.allowed_effects) == 1
        assert cap.allowed_effects[0] in receipt.effect_ids
        assert set(cap.allowed_effects) < set(receipt.effect_ids)

    def test_capability_roundtrip_dict(self) -> None:
        receipt = _allow_receipt()
        cap = derive_capability(
            receipt,
            capability_id="cap:rt",
            allowed_effects=("effect:ledger-write",),
        )
        restored = AuthorizationCapability.from_dict(cap.to_dict())
        assert restored.content_digest == cap.content_digest
        assert restored.one_time is True


# ---------------------------------------------------------------------------
# Cross-cutting acceptance checks
# ---------------------------------------------------------------------------


class TestAcceptanceMatrix:
    def test_all_bound_fields_present_on_wire(self) -> None:
        receipt = _allow_receipt()
        payload = receipt.to_dict()
        # Top-level bindings
        for key in (
            "receipt_id",
            "context",
            "roots",
            "outcome",
            "wire_status",
            "reasons",
            "reason_codes",
            "selected_evidence_cids",
            "selected_evidence_digest",
            "obligation_ids",
            "residual_duties",
            "attempt_digests",
            "result_digests",
            "policy_digest",
            "decision_digest",
            "issued_at",
            "deadline",
            "expiry",
            "producer_id",
            "nonce",  # nested under context — checked below
            "content_digest",
            "content_cid",
            "interface",
            "schema_version",
            "identity_algorithm",
        ):
            if key == "nonce":
                assert payload["context"]["nonce"]
                continue
            assert key in payload, key

        ctx = payload["context"]
        for key in (
            "request_digest",
            "arguments_digest",
            "actor_id",
            "audience_id",
            "tool_id",
            "effect_ids",
            "environment_digest",
            "delegation_ids",
            "nonce",
        ):
            assert key in ctx and ctx[key] not in (None, [], ""), key

        roots = payload["roots"]
        for key in (
            "policy_root",
            "corpus_roots",
            "revocation_root",
            "circuit_roots",
            "vk_roots",
        ):
            assert key in roots, key

    def test_algorithm_default_is_known(self) -> None:
        assert DEFAULT_IDENTITY_ALGORITHM in {
            "sha256-canonical-json/v1",
        }
        receipt = _allow_receipt()
        assert receipt.identity_algorithm == DEFAULT_IDENTITY_ALGORITHM

    def test_deep_copy_payload_mutation_detected(self) -> None:
        receipt = _allow_receipt()
        payload = copy.deepcopy(receipt.to_dict())
        payload["context"]["audience_id"] = "audience:attacker"
        with pytest.raises(ReceiptError, match="content_digest"):
            DecisionReceipt.from_dict(payload)

    def test_capability_cannot_be_forged_from_reject_wire(self) -> None:
        # Even if someone tries to force wire allow with deny outcome,
        # construction fails; non-allow statuses cannot derive.
        deny = _receipt_for_status(InternalDecisionStatus.DENY)
        assert deny.wire_status is AdmissibilityStatus.REJECT
        with pytest.raises(CapabilityDerivationError):
            derive_capability(
                deny,
                capability_id="cap:forged",
                allowed_effects=("effect:ledger-write",),
            )
