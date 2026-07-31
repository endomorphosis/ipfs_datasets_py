"""KGP-023: Negative authorization, revocation, and replay matrices.

Proves fail-closed denial for every adversarial class in the acceptance
criteria, and that denials leave no catalog/storage side effects while
audit receipts stay redacted and safe.

Coverage matrix
---------------
- sibling tenant / sibling graph
- widened child ability / resource / caveat
- wrong audience
- expired / not-yet-valid
- revoked ancestor / child
- substituted revision / cursor
- replayed mutation
- unknown caveat key
- bad signature
- malformed chain
- oversized token
- confused deputy
- unauthorized shard prefetch
- denial → no storage/catalog mutation
- deny receipts remain safe (redaction + digests)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest

from ipfs_datasets_py.knowledge_graphs.audit import (
    AuthorizationAuditLog,
    assert_receipt_safe,
    bound_payload,
    redact_for_audit,
)
from ipfs_datasets_py.knowledge_graphs.auth.contracts import (
    CONTRACT_VERSION,
    UCANContractError,
    GraphCapability,
    GraphCaveats,
    GraphDelegationLink,
    caveats_from_mapping,
    parse_graph_resource,
    validate_delegation_chain,
)
from ipfs_datasets_py.knowledge_graphs.auth.service import (
    GraphAuthorizationService,
    InMemoryNonceStore,
    InMemoryRevocationStore,
    auth_context_from_chain,
    make_enforcement_context,
    parse_delegation_chain,
)
from ipfs_datasets_py.knowledge_graphs.query.runtime import (
    CursorBinding,
    CursorCodec,
    InvalidCursorError,
)
from ipfs_datasets_py.knowledge_graphs.service import (
    AllowAllAuthorizer,
    GraphService,
    GraphTarget,
    InMemoryAuditSink,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cap(
    uri: str,
    ability: str,
    caveats: Optional[dict] = None,
) -> GraphCapability:
    return GraphCapability(
        resource=parse_graph_resource(uri),
        ability=ability,
        caveats=GraphCaveats.from_mapping(caveats),
    )


def _link(
    issuer: str,
    audience: str,
    caps: Sequence[GraphCapability],
    *,
    expiry: Optional[float] = None,
    not_before: Optional[float] = None,
    cid: Optional[str] = None,
    proof_cid: Optional[str] = None,
    nonce: Optional[str] = None,
    caveats: Optional[dict] = None,
) -> GraphDelegationLink:
    return GraphDelegationLink(
        issuer=issuer,
        audience=audience,
        capabilities=tuple(caps),
        expiry=expiry,
        not_before=not_before,
        cid=cid,
        proof_cid=proof_cid,
        nonce=nonce,
        caveats=GraphCaveats.from_mapping(caveats),
    )


def _two_hop(
    *,
    now: float,
    resource: str = "kg://acme/skills",
    parent_ability: str = "graph/admin",
    leaf_ability: str = "graph/read",
    audience: str = "did:key:agent",
    nonce: Optional[str] = "n-1",
    parent_caveats: Optional[dict] = None,
    leaf_caveats: Optional[dict] = None,
    leaf_resource: Optional[str] = None,
    root_cid: str = "cid-root",
    leaf_cid: str = "cid-leaf",
    expiry_delta: float = 10_000,
) -> List[GraphDelegationLink]:
    root = _link(
        "did:key:root",
        "did:key:mid",
        [_cap(resource, parent_ability, parent_caveats)],
        expiry=now + expiry_delta,
        cid=root_cid,
    )
    leaf = _link(
        "did:key:mid",
        audience,
        [_cap(leaf_resource or resource, leaf_ability, leaf_caveats)],
        expiry=now + expiry_delta / 2,
        cid=leaf_cid,
        proof_cid=root_cid,
        nonce=nonce,
    )
    return [root, leaf]


def _assert_denied(
    result: Any,
    *,
    reasons: Optional[set] = None,
    codes: Optional[set] = None,
) -> None:
    assert result.allowed is False
    assert result.decision.allowed is False
    assert result.receipt.decision == "deny"
    if reasons is not None:
        assert result.decision.reason in reasons, (
            f"unexpected reason {result.decision.reason!r}; want {reasons}"
        )
    if codes is not None:
        assert result.decision.code in codes, (
            f"unexpected code {result.decision.code!r}; want {codes}"
        )


def _assert_receipt_safe(result: Any) -> None:
    event = result.receipt.to_audit_event()
    payload = result.receipt.to_json_dict()
    assert_receipt_safe(event)
    assert_receipt_safe(payload)
    assert result.receipt.receipt_ref.startswith("sha256:")
    assert result.receipt.core.contract_version == CONTRACT_VERSION
    # Deny must not re-embed probe material under sensitive keys.
    blob = json.dumps(event, default=str)
    for needle in (
        "REDACT_PROBE_UCAN_TOKEN_v1",
        "REDACT_PROBE_SIGNATURE_v1",
        "redacted-probe-password-v1",
    ):
        assert needle not in blob


# ---------------------------------------------------------------------------
# Sibling tenant / graph
# ---------------------------------------------------------------------------


class TestSiblingTenantAndGraphDenial:
    def test_deny_sibling_tenant(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        chain = _two_hop(now=now, resource="kg://acme/skills", leaf_ability="graph/read")
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="evil", graph_id="skills"),
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
            now=now,
        )
        _assert_denied(
            result,
            reasons={"capability_missing", "resource_not_contained"},
            codes={"FORBIDDEN"},
        )
        _assert_receipt_safe(result)

    def test_deny_sibling_graph_same_tenant(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        chain = _two_hop(
            now=now,
            resource="kg://acme/skills",
            leaf_ability="graph/read",
            nonce="sib-g-1",
        )
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="payroll"),
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
            now=now,
        )
        _assert_denied(
            result,
            reasons={"capability_missing", "resource_not_contained"},
            codes={"FORBIDDEN"},
        )


# ---------------------------------------------------------------------------
# Widened child ability / resource / caveat
# ---------------------------------------------------------------------------


class TestWidenedChildDenial:
    def test_deny_widened_child_ability(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        root = _link(
            "did:key:root",
            "did:key:mid",
            [_cap("kg://acme/skills", "graph/read")],
            expiry=now + 1000,
            cid="w-ab-root",
        )
        leaf = _link(
            "did:key:mid",
            "did:key:agent",
            [_cap("kg://acme/skills", "graph/write")],
            expiry=now + 500,
            cid="w-ab-leaf",
            nonce="widen-ab-1",
        )
        result = authz.enforce(
            operation="write",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain([root, leaf], principal="did:key:agent"),
            now=now,
        )
        _assert_denied(
            result,
            reasons={
                "ability_not_attenuated",
                "resource_not_contained",
                "caveat_not_attenuated",
                "capability_missing",
            },
            codes={"FORBIDDEN"},
        )

    def test_deny_widened_child_resource(self) -> None:
        """Child claims tenant-wide authority while parent is graph-scoped."""
        now = time.time()
        authz = GraphAuthorizationService()
        root = _link(
            "did:key:root",
            "did:key:mid",
            [_cap("kg://acme/skills", "graph/admin")],
            expiry=now + 1000,
            cid="w-res-root",
        )
        leaf = _link(
            "did:key:mid",
            "did:key:agent",
            [_cap("kg://acme/*", "graph/read")],
            expiry=now + 500,
            cid="w-res-leaf",
            nonce="widen-res-1",
        )
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain([root, leaf], principal="did:key:agent"),
            now=now,
        )
        _assert_denied(
            result,
            reasons={
                "resource_not_contained",
                "ability_not_attenuated",
                "capability_missing",
            },
            codes={"FORBIDDEN"},
        )

    def test_deny_widened_child_caveat_row_budget(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        root = _link(
            "did:key:root",
            "did:key:mid",
            [_cap("kg://acme/skills", "graph/query", {"row": 10})],
            expiry=now + 1000,
            cid="w-cav-root",
            caveats={"row": 10},
        )
        # Child tries to raise the row ceiling above the parent.
        leaf = _link(
            "did:key:mid",
            "did:key:agent",
            [_cap("kg://acme/skills", "graph/query", {"row": 10_000})],
            expiry=now + 500,
            cid="w-cav-leaf",
            nonce="widen-cav-1",
            caveats={"row": 10_000},
        )
        result = authz.enforce(
            operation="query",
            target=GraphTarget(tenant="acme", graph_id="skills", branch="main"),
            auth=auth_context_from_chain(
                [root, leaf],
                principal="did:key:agent",
                extra={"query_kind": "cypher"},
            ),
            now=now,
        )
        _assert_denied(
            result,
            reasons={"caveat_not_attenuated", "ability_not_attenuated"},
            codes={"FORBIDDEN"},
        )

    def test_deny_widened_branch_set(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        root = _link(
            "did:key:root",
            "did:key:mid",
            [_cap("kg://acme/skills", "graph/read", {"branch": ["main"]})],
            expiry=now + 1000,
            cid="w-br-root",
            caveats={"branch": ["main"]},
        )
        leaf = _link(
            "did:key:mid",
            "did:key:agent",
            [_cap("kg://acme/skills", "graph/read", {"branch": ["main", "dev"]})],
            expiry=now + 500,
            cid="w-br-leaf",
            nonce="widen-br-1",
            caveats={"branch": ["main", "dev"]},
        )
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills", branch="main"),
            auth=auth_context_from_chain([root, leaf], principal="did:key:agent"),
            now=now,
        )
        _assert_denied(
            result,
            reasons={"caveat_not_attenuated"},
            codes={"FORBIDDEN"},
        )


# ---------------------------------------------------------------------------
# Audience, expiry, not-before
# ---------------------------------------------------------------------------


class TestAudienceAndTimeDenial:
    def test_deny_wrong_audience(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        chain = _two_hop(now=now, leaf_ability="graph/read", nonce="aud-x")
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain(chain, principal="did:key:impostor"),
            now=now,
        )
        _assert_denied(
            result,
            reasons={"audience_mismatch"},
            codes={"FORBIDDEN"},
        )

    def test_deny_audience_caveat_excludes_invoker(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        root = _link(
            "did:key:root",
            "did:key:agent",
            [
                _cap(
                    "kg://acme/skills",
                    "graph/read",
                    {"audience": ["did:key:other"]},
                )
            ],
            expiry=now + 1000,
            cid="aud-cav",
            nonce="aud-cav-1",
            caveats={"audience": ["did:key:other"]},
        )
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain([root], principal="did:key:agent"),
            now=now,
        )
        _assert_denied(
            result,
            reasons={"audience_mismatch", "caveat_not_attenuated"},
            codes={"FORBIDDEN"},
        )

    def test_deny_expired(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        chain = _two_hop(
            now=now - 20_000,
            leaf_ability="graph/read",
            nonce="exp-x",
            expiry_delta=100,
        )
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
            now=now,
        )
        _assert_denied(result, reasons={"expired"}, codes={"FORBIDDEN"})

    def test_deny_not_yet_valid(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        root = _link(
            "did:key:root",
            "did:key:agent",
            [_cap("kg://acme/skills", "graph/read")],
            not_before=now + 3600,
            expiry=now + 7200,
            cid="nyv-x",
            nonce="nyv-x-1",
        )
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain([root], principal="did:key:agent"),
            now=now,
        )
        _assert_denied(result, reasons={"not_yet_valid"}, codes={"FORBIDDEN"})


# ---------------------------------------------------------------------------
# Revocation (ancestor + child)
# ---------------------------------------------------------------------------


class TestRevocationDenial:
    def test_deny_revoked_ancestor(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService.create(revoked_cids=["cid-root"])
        chain = _two_hop(now=now, leaf_ability="graph/read", nonce="rev-anc")
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
            now=now,
        )
        _assert_denied(result, reasons={"revoked"}, codes={"FORBIDDEN"})

    def test_deny_revoked_child(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService.create(revoked_cids=["cid-leaf"])
        chain = _two_hop(now=now, leaf_ability="graph/read", nonce="rev-ch")
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
            now=now,
        )
        _assert_denied(result, reasons={"revoked"}, codes={"FORBIDDEN"})

    def test_deny_revoked_proof_cid(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        authz.revoke("cid-root")  # leaf.proof_cid points here
        chain = _two_hop(now=now, leaf_ability="graph/read", nonce="rev-proof")
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
            now=now,
        )
        _assert_denied(result, reasons={"revoked"}, codes={"FORBIDDEN"})

    def test_runtime_revoke_then_deny(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        chain = _two_hop(now=now, leaf_ability="graph/read", nonce="rev-rt")
        ok = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
            now=now,
        )
        assert ok.allowed is True
        authz.revoke("cid-leaf")
        chain2 = _two_hop(now=now, leaf_ability="graph/read", nonce="rev-rt-2")
        denied = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain(chain2, principal="did:key:agent"),
            now=now,
        )
        _assert_denied(denied, reasons={"revoked"}, codes={"FORBIDDEN"})


# ---------------------------------------------------------------------------
# Substituted revision / cursor
# ---------------------------------------------------------------------------


class TestSubstitutedRevisionAndCursor:
    def test_deny_substituted_revision_via_caveat(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        root = _link(
            "did:key:root",
            "did:key:agent",
            [
                _cap(
                    "kg://acme/skills",
                    "graph/read",
                    {"revision": ["bafy-allowed-rev"]},
                )
            ],
            expiry=now + 1000,
            cid="rev-sub",
            nonce="rev-sub-1",
        )
        result = authz.enforce(
            operation="open",
            target=GraphTarget(
                tenant="acme",
                graph_id="skills",
                revision="bafy-attacker-rev",
            ),
            auth=auth_context_from_chain([root], principal="did:key:agent"),
            now=now,
        )
        _assert_denied(
            result,
            reasons={"caveat_not_attenuated", "capability_missing"},
            codes={"FORBIDDEN"},
        )

    def test_deny_cursor_substituted_revision(self) -> None:
        codec = CursorCodec(secret=b"kgp-023-test-hmac-material-v1")
        binding = CursorBinding.from_target(
            tenant="acme",
            graph_id="skills",
            revision="bafy-rev-1",
            query_digest="a" * 64,
            authorization_digest="b" * 64,
        )
        token = codec.encode(binding, offset=10)
        # Attacker rebinds to a different revision.
        wrong = CursorBinding.from_target(
            tenant="acme",
            graph_id="skills",
            revision="bafy-rev-2",
            query_digest="a" * 64,
            authorization_digest="b" * 64,
        )
        with pytest.raises(InvalidCursorError) as excinfo:
            codec.decode(token, expected=wrong)
        assert "not valid" in str(excinfo.value).lower() or "mismatch" in str(
            excinfo.value
        ).lower() or "revision" in str(excinfo.value.details).lower()

    def test_deny_cursor_substituted_graph_and_auth(self) -> None:
        codec = CursorCodec(secret=b"kgp-023-test-hmac-material-v1")
        binding = CursorBinding.from_target(
            tenant="acme",
            graph_id="skills",
            revision="bafy-rev-1",
            query_digest="q" * 64,
            authorization_digest="auth-digest-alice",
        )
        token = codec.encode(binding, offset=0)
        for expected in (
            CursorBinding.from_target(
                tenant="acme",
                graph_id="payroll",
                revision="bafy-rev-1",
                query_digest="q" * 64,
                authorization_digest="auth-digest-alice",
            ),
            CursorBinding.from_target(
                tenant="evil",
                graph_id="skills",
                revision="bafy-rev-1",
                query_digest="q" * 64,
                authorization_digest="auth-digest-alice",
            ),
            CursorBinding.from_target(
                tenant="acme",
                graph_id="skills",
                revision="bafy-rev-1",
                query_digest="q" * 64,
                authorization_digest="auth-digest-eve",
            ),
        ):
            with pytest.raises(InvalidCursorError):
                codec.decode(token, expected=expected)

    def test_deny_forged_cursor_mac(self) -> None:
        codec = CursorCodec(secret=b"kgp-023-test-hmac-material-v1")
        binding = CursorBinding.from_target(
            tenant="acme",
            graph_id="skills",
            revision="bafy-rev-1",
            query_digest="q" * 64,
        )
        token = codec.encode(binding, offset=5)
        # Tamper payload portion while keeping structure.
        parts = token.split(".")
        assert len(parts) == 3  # kgc1.<body>.<mac> after split on '.'
        # Actually format is "kgc1.<body>.<mac>" — prefix is "kgc1."
        assert token.startswith("kgc1.")
        body_and_mac = token[len("kgc1.") :]
        body_b64, mac_b64 = body_and_mac.split(".", 1)
        forged = f"kgc1.{body_b64}.{'A' * len(mac_b64)}"
        with pytest.raises(InvalidCursorError) as excinfo:
            codec.decode(forged, expected=binding)
        assert "integrity" in str(excinfo.value).lower() or "mac" in str(
            getattr(excinfo.value, "details", {})
        ).lower()


# ---------------------------------------------------------------------------
# Replayed mutation
# ---------------------------------------------------------------------------


class TestReplayDenial:
    def test_deny_replayed_mutation_nonce(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService(require_nonce_for_mutations=True)
        chain = _two_hop(
            now=now,
            leaf_ability="graph/write",
            nonce="replay-mut-1",
        )
        auth = auth_context_from_chain(
            chain, principal="did:key:agent", nonce="replay-mut-1"
        )
        target = GraphTarget(tenant="acme", graph_id="skills")
        first = authz.enforce(operation="write", target=target, auth=auth, now=now)
        assert first.allowed is True
        second = authz.enforce(operation="write", target=target, auth=auth, now=now)
        _assert_denied(second, reasons={"replay"}, codes={"FORBIDDEN"})
        _assert_receipt_safe(second)

    def test_deny_replayed_admin_idempotency_key(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService(require_nonce_for_mutations=True)
        root = _link(
            "did:key:root",
            "did:key:agent",
            [_cap("kg://acme/skills", "graph/admin")],
            expiry=now + 1000,
            cid="idemp-root",
        )
        auth = {
            "principal": "did:key:agent",
            "chain": [root],
            "idempotency_key": "create-once-42",
        }
        target = GraphTarget(tenant="acme", graph_id="skills")
        assert authz.enforce(operation="create", target=target, auth=auth, now=now).allowed
        second = authz.enforce(operation="create", target=target, auth=auth, now=now)
        _assert_denied(second, reasons={"replay"}, codes={"FORBIDDEN"})


# ---------------------------------------------------------------------------
# Unknown key / bad signature / malformed chain / oversized token
# ---------------------------------------------------------------------------


class TestStructuralAndCryptoDenial:
    def test_deny_unknown_caveat_key(self) -> None:
        with pytest.raises(UCANContractError) as excinfo:
            caveats_from_mapping({"row": 10, "sql_injection": "1=1"})
        assert excinfo.value.reason == "unknown_caveat_key"

        now = time.time()
        authz = GraphAuthorizationService()
        # Unknown keys on a capability mapping fail closed at chain parse.
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth={
                "principal": "did:key:agent",
                "chain": [
                    {
                        "issuer": "did:key:root",
                        "audience": "did:key:agent",
                        "expiry": now + 1000,
                        "cid": "unk-key",
                        "nonce": "unk-key-1",
                        "capabilities": [
                            {
                                "resource": "kg://acme/skills",
                                "ability": "graph/read",
                                "caveats": {"superpower": True},
                            }
                        ],
                    }
                ],
            },
            now=now,
        )
        assert result.allowed is False
        assert result.decision.reason in {
            "unknown_caveat_key",
            "invalid_caveat",
            "invalid_resource",
            "missing_token",
        }
        assert result.decision.code in {"INVALID_REQUEST", "FORBIDDEN", "UNAUTHORIZED"}
        _assert_receipt_safe(result)

    def test_deny_bad_signature_profile_c(self) -> None:
        try:
            from ipfs_datasets_py.mcp_server.ucan_delegation import (
                Capability,
                Delegation,
                DelegationEvaluator,
                DIDSignedDelegation,
                verify_delegation_signature,
            )
        except Exception:
            pytest.skip("ucan_delegation unavailable")

        now = time.time()
        d = Delegation(
            issuer="did:key:root",
            audience="did:key:agent",
            capabilities=[
                Capability(resource="kg://acme/skills", ability="graph/read")
            ],
            expiry=now + 3600,
            cid="sig-bad-1",
        )
        # Fabricated signed wrapper with nonsense signature.
        signed = DIDSignedDelegation(
            delegation=d,
            signature="00" * 32,
            signer_did="did:key:root",
            verified=False,
        )
        assert verify_delegation_signature(signed) is False

        # Evaluator require_signatures path rejects unsigned DID issuers.
        evaluator = DelegationEvaluator(require_signatures=True)
        evaluator.add(d)
        allowed, reason = evaluator.can_invoke(
            leaf_cid="sig-bad-1",
            resource="kg://acme/skills",
            ability="graph/read",
            actor="did:key:agent",
            now=now,
        )
        assert allowed is False
        assert "signature" in reason.lower() or "lacks" in reason.lower()

        # Attach broken signed object on the delegation and re-check.
        d._signed = signed  # type: ignore[attr-defined]
        evaluator2 = DelegationEvaluator(require_signatures=False)
        evaluator2.add(d)
        allowed2, reason2 = evaluator2.can_invoke(
            leaf_cid="sig-bad-1",
            resource="kg://acme/skills",
            ability="graph/read",
            actor="did:key:agent",
            now=now,
        )
        assert allowed2 is False
        assert "signature" in reason2.lower() or "invalid" in reason2.lower()

    def test_deny_malformed_chain_shapes(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        target = GraphTarget(tenant="acme", graph_id="skills")

        # Empty chain
        r = authz.enforce(
            operation="open",
            target=target,
            auth={"principal": "did:key:agent", "chain": []},
            now=now,
        )
        _assert_denied(
            r,
            reasons={"empty_chain", "missing_token"},
            codes={"UNAUTHORIZED"},
        )

        # Issuer mismatch (malformed linkage)
        root = _link(
            "did:key:root",
            "did:key:mid",
            [_cap("kg://acme/skills", "graph/admin")],
            expiry=now + 1000,
            cid="mf-root",
        )
        leaf = _link(
            "did:key:stranger",
            "did:key:agent",
            [_cap("kg://acme/skills", "graph/read")],
            expiry=now + 500,
            cid="mf-leaf",
            nonce="mf-1",
        )
        r2 = authz.enforce(
            operation="open",
            target=target,
            auth=auth_context_from_chain([root, leaf], principal="did:key:agent"),
            now=now,
        )
        _assert_denied(r2, reasons={"issuer_mismatch"}, codes={"FORBIDDEN"})

        # Garbage chain items → parse failure, never allow
        r3 = authz.enforce(
            operation="open",
            target=target,
            auth={"principal": "did:key:agent", "chain": [12345, None]},
            now=now,
        )
        assert r3.allowed is False
        assert r3.decision.code in {"UNAUTHORIZED", "INVALID_REQUEST", "FORBIDDEN"}

        # Missing issuer/audience fields on mapping links
        r4 = authz.enforce(
            operation="open",
            target=target,
            auth={
                "principal": "did:key:agent",
                "chain": [
                    {
                        "issuer": "",
                        "audience": "did:key:agent",
                        "capabilities": [
                            {"resource": "kg://acme/skills", "ability": "graph/read"}
                        ],
                    }
                ],
            },
            now=now,
        )
        assert r4.allowed is False

    def test_deny_oversized_token_and_deep_chain(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()

        # Oversized raw token material must not authorize anything.
        huge_token = "A" * 200_000
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth={
                "principal": "did:key:agent",
                "token": huge_token,
                "ucan_token": huge_token,
                "signature": "REDACT_PROBE_SIGNATURE_v1" * 1000,
            },
            now=now,
        )
        assert result.allowed is False
        # Receipt must stay bounded / redacted despite huge inputs.
        event = result.receipt.to_audit_event()
        bounded = bound_payload(event, max_bytes=8_192)
        assert len(json.dumps(bounded, default=str).encode("utf-8")) < 40_000
        assert_receipt_safe(redact_for_audit({"token": huge_token, "signature": "x"}))
        _assert_receipt_safe(result)

        # Profile C evaluator rejects chains beyond max depth (DoS guard).
        try:
            from ipfs_datasets_py.mcp_server.ucan_delegation import (
                Capability,
                Delegation,
                DelegationEvaluator,
            )
        except Exception:
            return

        evaluator = DelegationEvaluator(max_chain_depth=3)
        prev_cid: Optional[str] = None
        for i in range(6):
            cid = f"deep-{i}"
            d = Delegation(
                issuer=f"did:key:n{i}",
                audience=f"did:key:n{i + 1}",
                capabilities=[
                    Capability(resource="kg://acme/skills", ability="graph/read")
                ],
                expiry=now + 3600,
                cid=cid,
                proof_cid=prev_cid,
            )
            evaluator.add(d)
            prev_cid = cid
        with pytest.raises(ValueError, match="max_chain_depth"):
            evaluator.build_chain("deep-5")
        allowed, reason = evaluator.can_invoke(
            leaf_cid="deep-5",
            resource="kg://acme/skills",
            ability="graph/read",
            actor="did:key:n6",
            now=now,
        )
        assert allowed is False
        assert "max_chain_depth" in reason or "exceeds" in reason.lower()


# ---------------------------------------------------------------------------
# Confused deputy + unauthorized shard prefetch
# ---------------------------------------------------------------------------


class TestConfusedDeputyAndPrefetch:
    def test_deny_confused_deputy_cross_tenant_escape(self) -> None:
        """Mid-tier service must not use acme grant to act for evil tenant."""
        now = time.time()
        authz = GraphAuthorizationService()
        # Honest chain for acme, but request targets evil (deputy confusion).
        chain = _two_hop(
            now=now,
            resource="kg://acme/skills",
            leaf_ability="graph/admin",
            audience="did:key:service",
            nonce="cd-1",
        )
        result = authz.enforce(
            operation="write",
            target=GraphTarget(tenant="evil", graph_id="skills"),
            auth=auth_context_from_chain(
                chain,
                principal="did:key:service",
                extra={
                    # Attacker tries to smuggle target via request metadata.
                    "on_behalf_of": "did:key:victim",
                    "forwarded_tenant": "evil",
                },
            ),
            now=now,
        )
        _assert_denied(
            result,
            reasons={"capability_missing", "resource_not_contained"},
            codes={"FORBIDDEN"},
        )
        _assert_receipt_safe(result)

    def test_deny_confused_deputy_resource_escape_in_chain(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        root = _link(
            "did:key:root",
            "did:key:mid",
            [_cap("kg://acme/skills", "graph/admin")],
            expiry=now + 1000,
            cid="cd-root",
        )
        # Child tries to escape to another tenant resource.
        leaf = _link(
            "did:key:mid",
            "did:key:agent",
            [_cap("kg://evil/skills", "graph/write")],
            expiry=now + 500,
            cid="cd-leaf",
            nonce="cd-esc-1",
        )
        result = authz.enforce(
            operation="write",
            target=GraphTarget(tenant="evil", graph_id="skills"),
            auth=auth_context_from_chain([root, leaf], principal="did:key:agent"),
            now=now,
        )
        _assert_denied(
            result,
            reasons={
                "resource_not_contained",
                "ability_not_attenuated",
                "capability_missing",
            },
            codes={"FORBIDDEN"},
        )

    @pytest.mark.parametrize(
        "operation,access_kind",
        [
            ("prefetch_shard", "prefetch"),
            ("prefetch_shard", "shard"),
            ("open", "shard"),
            ("read_metadata", "metadata"),
            ("open_index", "index"),
        ],
    )
    def test_deny_unauthorized_shard_prefetch(
        self, operation: str, access_kind: str
    ) -> None:
        authz = make_enforcement_context()
        result = authz.check_before_access(
            operation=operation,
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=None,
            access_kind=access_kind,
        )
        assert result.allowed is False
        assert result.phase == f"before_{access_kind}"
        assert result.decision.code in {"UNAUTHORIZED", "FORBIDDEN"}
        assert result.receipt.decision == "deny"

    def test_deny_prefetch_with_wrong_resource_chain(self) -> None:
        now = time.time()
        authz = make_enforcement_context()
        chain = _two_hop(
            now=now,
            resource="kg://acme/other",
            leaf_ability="graph/read",
            nonce="pf-wrong",
        )
        result = authz.check_before_access(
            operation="prefetch_shard",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
            access_kind="prefetch",
        )
        _assert_denied(
            result,
            reasons={"capability_missing", "resource_not_contained"},
            codes={"FORBIDDEN"},
        )


# ---------------------------------------------------------------------------
# No storage / catalog side effects + audit safety
# ---------------------------------------------------------------------------


class TestDenialSideEffectsAndAudit:
    def test_deny_create_has_no_catalog_side_effect(self, tmp_path: Path) -> None:
        authz = make_enforcement_context(policy_id="policy:adv")
        catalog = tmp_path / "cat.db"
        svc = GraphService.open(catalog, authorizer=authz)
        try:
            r = svc.create(
                GraphTarget(tenant="acme", graph_id="nope"),
                idempotency_key="nope-adv-1",
                auth={
                    "principal": "did:key:agent",
                    # Present but empty → unauthorized, not allow-all.
                    "chain": [],
                },
            )
            assert not r.ok
            assert r.error is not None
            assert r.error.code in {"UNAUTHORIZED", "FORBIDDEN"}
            assert r.authorization_receipt_ref
        finally:
            svc.close()

        # Reopen with allow-all to inspect catalog truthfully.
        svc2 = GraphService.open(catalog, authorizer=AllowAllAuthorizer())
        try:
            listed = svc2.list(GraphTarget(tenant="acme", graph_id="nope"))
            assert listed.ok
            graphs = (listed.result or {}).get("graphs") or []
            ids = {
                g.get("graph_id") if isinstance(g, dict) else getattr(g, "graph_id", None)
                for g in graphs
            }
            assert "nope" not in ids
        finally:
            svc2.close()

    def test_deny_write_has_no_storage_side_effect(self, tmp_path: Path) -> None:
        now = time.time()
        # Create graph under allow-all, then deny write under UCAN.
        catalog = tmp_path / "cat.db"
        store = tmp_path / "store"
        store.mkdir()
        bootstrap = GraphService.open(
            catalog, storage_path=store, authorizer=AllowAllAuthorizer()
        )
        try:
            created = bootstrap.create(
                GraphTarget(tenant="acme", graph_id="skills", branch="main"),
                idempotency_key="boot-1",
            )
            assert created.ok, created.to_json_dict()
            describe_before = bootstrap.describe(
                GraphTarget(tenant="acme", graph_id="skills")
            )
            assert describe_before.ok
            before = describe_before.to_json_dict()
        finally:
            bootstrap.close()

        authz = make_enforcement_context(require_nonce_for_mutations=True)
        svc = GraphService.open(catalog, storage_path=store, authorizer=authz)
        try:
            denied = svc.write(
                GraphTarget(tenant="acme", graph_id="skills", branch="main"),
                params={
                    "entities": [{"id": "x", "type": "T", "name": "evil"}],
                },
                idempotency_key="evil-w-1",
                auth={
                    "principal": "did:key:agent",
                    "ucan_token": "REDACT_PROBE_UCAN_TOKEN_v1",
                    "signature": "REDACT_PROBE_SIGNATURE_v1",
                    "password": "redacted-probe-password-v1",
                },
            )
            assert not denied.ok
            assert denied.error is not None
            assert denied.error.code in {"UNAUTHORIZED", "FORBIDDEN"}
            # Receipt present and safe.
            assert denied.authorization_receipt_ref
            # Capture last audit receipt if available.
            for receipt in authz.audit_log.recent(5):
                assert_receipt_safe(receipt)
                blob = json.dumps(receipt, default=str)
                assert "REDACT_PROBE_UCAN_TOKEN_v1" not in blob
                assert "redacted-probe-password-v1" not in blob
        finally:
            svc.close()

        # Catalog head / describe must be unchanged.
        inspect = GraphService.open(
            catalog, storage_path=store, authorizer=AllowAllAuthorizer()
        )
        try:
            after = inspect.describe(
                GraphTarget(tenant="acme", graph_id="skills")
            ).to_json_dict()
            # Graph still exists; no attacker entity materialization required.
            assert after["status"] == "success"
            # Revision identity must not advance from a denied write.
            before_rev = (before.get("result") or {}).get("head_revision")
            after_rev = (after.get("result") or {}).get("head_revision")
            assert before_rev is not None and after_rev is not None
            assert before_rev == after_rev
        finally:
            inspect.close()

    def test_deny_receipts_redact_and_digest(self) -> None:
        now = time.time()
        sink = InMemoryAuditSink()
        log = AuthorizationAuditLog(sink=sink)
        authz = GraphAuthorizationService(audit_log=log)
        chain = _two_hop(now=now, leaf_ability="graph/read", nonce="audit-1")
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="evil", graph_id="skills"),
            auth=auth_context_from_chain(
                chain,
                principal="did:key:agent",
                extra={
                    "ucan_token": "REDACT_PROBE_UCAN_TOKEN_v1.payload.sig",
                    "signature": "REDACT_PROBE_SIGNATURE_v1",
                    "password": "redacted-probe-password-v1",
                    "query_text": "MATCH (n) RETURN n",
                },
            ),
            now=now,
        )
        _assert_denied(result)
        _assert_receipt_safe(result)
        assert result.receipt.core.policy_digest.startswith("sha256:")
        assert result.receipt.core.request_digest.startswith("sha256:")
        assert result.receipt.core.chain_digest.startswith("sha256:")
        assert log.size >= 1
        assert len(sink.events) >= 1
        for e in sink.events:
            assert_receipt_safe(e)

    def test_parametrized_negative_matrix_smoke(self) -> None:
        """Compact matrix: each adversarial class denies at least once."""
        now = time.time()
        cases: List[Dict[str, Any]] = []

        # sibling tenant
        cases.append(
            {
                "name": "sibling_tenant",
                "chain": _two_hop(now=now, nonce="m-sib"),
                "target": GraphTarget(tenant="evil", graph_id="skills"),
                "principal": "did:key:agent",
                "op": "open",
            }
        )
        # wrong audience
        cases.append(
            {
                "name": "wrong_audience",
                "chain": _two_hop(now=now, nonce="m-aud"),
                "target": GraphTarget(tenant="acme", graph_id="skills"),
                "principal": "did:key:eve",
                "op": "open",
            }
        )
        # expired
        cases.append(
            {
                "name": "expired",
                "chain": _two_hop(
                    now=now - 50_000, nonce="m-exp", expiry_delta=10
                ),
                "target": GraphTarget(tenant="acme", graph_id="skills"),
                "principal": "did:key:agent",
                "op": "open",
            }
        )
        # revoked
        cases.append(
            {
                "name": "revoked",
                "chain": _two_hop(now=now, nonce="m-rev"),
                "target": GraphTarget(tenant="acme", graph_id="skills"),
                "principal": "did:key:agent",
                "op": "open",
                "revoked": ["cid-root"],
            }
        )
        # missing token
        cases.append(
            {
                "name": "missing_token",
                "chain": None,
                "target": GraphTarget(tenant="acme", graph_id="skills"),
                "principal": "did:key:agent",
                "op": "open",
            }
        )

        for case in cases:
            authz = GraphAuthorizationService.create(
                revoked_cids=case.get("revoked") or []
            )
            if case["chain"] is None:
                auth: Optional[Dict[str, Any]] = {"principal": case["principal"]}
            else:
                auth = auth_context_from_chain(
                    case["chain"], principal=case["principal"]
                )
            result = authz.enforce(
                operation=case["op"],
                target=case["target"],
                auth=auth,
                now=now,
            )
            assert result.allowed is False, case["name"]
            assert result.receipt.decision == "deny", case["name"]
            _assert_receipt_safe(result)


# ---------------------------------------------------------------------------
# Contract-level validate_delegation_chain adversarial checks
# ---------------------------------------------------------------------------


class TestContractLevelNegatives:
    def test_validate_delegation_chain_unknown_ability(self) -> None:
        now = time.time()
        link = _link(
            "did:key:root",
            "did:key:agent",
            [_cap("kg://acme/skills", "graph/read")],
            expiry=now + 100,
            nonce="c-1",
        )
        # Request an unknown ability via normalize path — enforce maps ops;
        # direct validate should reject unknown abilities.
        with pytest.raises(UCANContractError):
            from ipfs_datasets_py.knowledge_graphs.auth.contracts import (
                normalize_ability,
            )

            normalize_ability("graph/rootkit")

        denied = validate_delegation_chain(
            [link],
            resource="kg://acme/skills",
            ability="graph/write",  # not granted
            invoker="did:key:agent",
            now=now,
        )
        assert denied.allowed is False
        assert denied.reason == "capability_missing"

    def test_parse_delegation_chain_rejects_empty_and_missing(self) -> None:
        links, reason = parse_delegation_chain(None)
        assert links == [] and reason == "missing_token"
        links, reason = parse_delegation_chain({"chain": []})
        assert reason == "empty_chain"
        links, reason = parse_delegation_chain({"principal": "x"})
        assert reason == "missing_token"

    def test_in_memory_stores_replay_and_revoke(self) -> None:
        rev = InMemoryRevocationStore(["a"])
        assert rev.is_revoked("a")
        rev.revoke("b")
        assert "b" in set(rev.revoked_cids())
        nonces = InMemoryNonceStore(max_entries=2)
        assert nonces.remember("n1") is True
        assert nonces.remember("n1") is False
        assert nonces.seen("n1")


# ---------------------------------------------------------------------------
# Module presence (expected outputs)
# ---------------------------------------------------------------------------


def test_expected_adversarial_module_path() -> None:
    root = Path(__file__).resolve().parents[3]
    assert (
        root / "tests/security/knowledge_graphs/test_ucan_adversarial.py"
    ).is_file()
    assert (root / "ipfs_datasets_py/knowledge_graphs/auth/service.py").is_file()
    assert (root / "ipfs_datasets_py/knowledge_graphs/auth/contracts.py").is_file()
