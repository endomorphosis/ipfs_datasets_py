"""KGP-022: UCAN enforcement in GraphService + content-addressed audit receipts.

Validates ``GraphAuthorizationService`` and ``knowledge_graphs.audit`` against
acceptance criteria:

- resource, ability, full-chain attenuation
- issuer/audience, expiry, revocation
- nonce/idempotency and caveats
- enforcement before metadata / graph / index / shard access
- bounded redacted allow/deny receipts with policy/revision/request digests
- Python/CLI opt-in via the same enforcement context
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from ipfs_datasets_py.knowledge_graphs.audit import (
    AUDIT_MODULE_VERSION,
    AuthorizationAuditLog,
    assert_receipt_safe,
    bound_payload,
    build_enriched_receipt,
    policy_revision_digest,
    redact_for_audit,
    revision_digest,
)
from ipfs_datasets_py.knowledge_graphs.auth.contracts import (
    CONTRACT_VERSION,
    GraphCapability,
    GraphCaveats,
    GraphDelegationLink,
    build_authorization_receipt,
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
    target_to_resource,
)
from ipfs_datasets_py.knowledge_graphs.service import (
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
    caps: List[GraphCapability],
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


def _admin_chain(
    *,
    now: float,
    resource: str = "kg://acme/skills",
    leaf_ability: str = "graph/admin",
    audience: str = "did:key:agent",
    nonce: Optional[str] = "n-admin-1",
    expiry_delta: float = 10_000,
) -> List[GraphDelegationLink]:
    root = _link(
        "did:key:root",
        "did:key:mid",
        [_cap(resource, "graph/admin")],
        expiry=now + expiry_delta,
        cid="cid-root",
    )
    leaf = _link(
        "did:key:mid",
        audience,
        [_cap(resource, leaf_ability)],
        expiry=now + expiry_delta / 2,
        cid="cid-leaf",
        proof_cid="cid-root",
        nonce=nonce,
    )
    return [root, leaf]


def _query_chain(
    *,
    now: float,
    nonce: str = "n-query-1",
) -> List[GraphDelegationLink]:
    root = _link(
        "did:key:root",
        "did:key:mid",
        [_cap("kg://acme/skills", "graph/admin")],
        expiry=now + 10_000,
        cid="q-root",
    )
    leaf = _link(
        "did:key:mid",
        "did:key:agent",
        [
            _cap(
                "kg://acme/skills/branches/main",
                "graph/query",
                {"query": ["cypher"], "row": 100},
            )
        ],
        expiry=now + 5_000,
        cid="q-leaf",
        proof_cid="q-root",
        nonce=nonce,
    )
    return [root, leaf]


# ---------------------------------------------------------------------------
# Unit: target / chain parsing
# ---------------------------------------------------------------------------


def test_target_to_resource_from_graph_target():
    t = GraphTarget(tenant="acme", graph_id="skills", branch="main")
    r = target_to_resource(t)
    assert r.uri == "kg://acme/skills/branches/main"
    assert r.branch == "main"


def test_parse_delegation_chain_missing_and_empty():
    links, reason = parse_delegation_chain(None)
    assert links == [] and reason == "missing_token"
    links, reason = parse_delegation_chain({})
    assert reason == "missing_token"
    links, reason = parse_delegation_chain({"chain": []})
    assert reason == "empty_chain"


def test_parse_delegation_chain_from_links_and_profile_c_shape():
    now = time.time()
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="parse-1")
    auth = auth_context_from_chain(chain, principal="did:key:agent")
    links, reason = parse_delegation_chain(auth)
    assert reason is None
    assert len(links) == 2
    assert links[-1].audience == "did:key:agent"

    # Mapping form
    auth2 = {
        "principal": "did:key:agent",
        "links": [lnk.to_json_dict() for lnk in chain],
    }
    links2, reason2 = parse_delegation_chain(auth2)
    assert reason2 is None
    assert links2[0].cid == "cid-root"


# ---------------------------------------------------------------------------
# Core enforcement matrix
# ---------------------------------------------------------------------------


def test_allow_read_with_valid_chain():
    now = time.time()
    authz = GraphAuthorizationService.create(
        policy_id="policy:test",
        policy_revision="rev-1",
        require_nonce_for_mutations=True,
    )
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="allow-read-1")
    target = GraphTarget(tenant="acme", graph_id="skills")
    result = authz.enforce(
        operation="open",
        target=target,
        auth=auth_context_from_chain(chain, principal="did:key:agent"),
        request_id="r1",
        now=now,
    )
    assert result.allowed is True
    assert result.decision.allowed is True
    assert result.decision.ability == "graph/read"
    assert result.decision.receipt_ref.startswith("sha256:")
    assert result.receipt.decision == "allow"
    assert result.receipt.core.policy_digest.startswith("sha256:")
    assert result.receipt.core.request_digest.startswith("sha256:")
    assert result.receipt.revision_digest.startswith("sha256:")
    assert result.receipt.core.contract_version == CONTRACT_VERSION


def test_deny_missing_token_unauthorized():
    authz = make_enforcement_context()
    target = GraphTarget(tenant="acme", graph_id="skills")
    result = authz.enforce(
        operation="describe",
        target=target,
        auth=None,
        request_id="r-missing",
    )
    assert result.allowed is False
    assert result.decision.code == "UNAUTHORIZED"
    assert result.decision.reason == "missing_token"
    assert result.receipt.decision == "deny"
    assert result.receipt.event_type == "ucan.deny"


def test_deny_missing_principal():
    now = time.time()
    authz = GraphAuthorizationService(require_invoker=True)
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="mp-1")
    result = authz.enforce(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth={"chain": chain},  # no principal
        now=now,
    )
    assert result.allowed is False
    assert result.decision.code == "UNAUTHORIZED"
    assert result.decision.reason == "missing_principal"


def test_deny_audience_mismatch():
    now = time.time()
    authz = GraphAuthorizationService()
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="aud-1")
    result = authz.enforce(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain(chain, principal="did:key:impostor"),
        now=now,
    )
    assert result.allowed is False
    assert result.decision.reason == "audience_mismatch"
    assert result.decision.code == "FORBIDDEN"


def test_deny_cross_tenant_resource():
    now = time.time()
    authz = GraphAuthorizationService()
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="xt-1")
    result = authz.enforce(
        operation="open",
        target=GraphTarget(tenant="evil", graph_id="skills"),
        auth=auth_context_from_chain(chain, principal="did:key:agent"),
        now=now,
    )
    assert result.allowed is False
    assert result.decision.reason == "capability_missing"
    assert result.decision.code == "FORBIDDEN"


def test_deny_ability_not_granted():
    now = time.time()
    authz = GraphAuthorizationService()
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="ab-1")
    # create requires graph/admin
    result = authz.enforce(
        operation="create",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain(chain, principal="did:key:agent", nonce="ab-create"),
        now=now,
    )
    assert result.allowed is False
    assert result.decision.reason == "capability_missing"


def test_deny_expired_chain():
    now = time.time()
    authz = GraphAuthorizationService()
    chain = _admin_chain(
        now=now - 20_000,
        leaf_ability="graph/read",
        nonce="exp-1",
        expiry_delta=100,  # expired relative to now
    )
    result = authz.enforce(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain(chain, principal="did:key:agent"),
        now=now,
    )
    assert result.allowed is False
    assert result.decision.reason == "expired"
    assert result.decision.code == "FORBIDDEN"


def test_deny_not_yet_valid():
    now = time.time()
    authz = GraphAuthorizationService()
    root = _link(
        "did:key:root",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/read")],
        not_before=now + 3600,
        expiry=now + 7200,
        cid="nyv",
        nonce="nyv-1",
    )
    result = authz.enforce(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain([root], principal="did:key:agent"),
        now=now,
    )
    assert result.allowed is False
    assert result.decision.reason == "not_yet_valid"


def test_deny_revoked_ancestor():
    now = time.time()
    authz = GraphAuthorizationService.create(revoked_cids=["cid-root"])
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="rev-1")
    result = authz.enforce(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain(chain, principal="did:key:agent"),
        now=now,
    )
    assert result.allowed is False
    assert result.decision.reason == "revoked"


def test_deny_widened_child_ability_on_chain():
    now = time.time()
    authz = GraphAuthorizationService()
    # Parent only grants read; child claims write → attenuation failure
    root = _link(
        "did:key:root",
        "did:key:mid",
        [_cap("kg://acme/skills", "graph/read")],
        expiry=now + 1000,
        cid="w-root",
    )
    leaf = _link(
        "did:key:mid",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/write")],
        expiry=now + 500,
        cid="w-leaf",
        nonce="widen-1",
    )
    result = authz.enforce(
        operation="write",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain([root, leaf], principal="did:key:agent"),
        now=now,
    )
    assert result.allowed is False
    assert result.decision.reason in {
        "ability_not_attenuated",
        "resource_not_contained",
        "caveat_not_attenuated",
    }


def test_deny_issuer_mismatch():
    now = time.time()
    authz = GraphAuthorizationService()
    root = _link(
        "did:key:root",
        "did:key:mid",
        [_cap("kg://acme/skills", "graph/admin")],
        expiry=now + 1000,
        cid="iss-root",
    )
    leaf = _link(
        "did:key:stranger",  # should be mid
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/read")],
        expiry=now + 500,
        cid="iss-leaf",
        nonce="iss-1",
    )
    result = authz.enforce(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain([root, leaf], principal="did:key:agent"),
        now=now,
    )
    assert result.allowed is False
    assert result.decision.reason == "issuer_mismatch"


def test_caveat_query_kind_enforced():
    now = time.time()
    authz = GraphAuthorizationService(require_nonce_for_mutations=False)
    chain = _query_chain(now=now, nonce="cq-1")
    target = GraphTarget(tenant="acme", graph_id="skills", branch="main")
    # Allowed cypher (grant allows only cypher)
    ok = authz.enforce(
        operation="query",
        target=target,
        auth=auth_context_from_chain(
            chain,
            principal="did:key:agent",
            extra={"query_kind": "cypher"},
        ),
        now=now,
    )
    assert ok.allowed is True, (ok.decision.reason, ok.chain_result.to_json_dict())

    # Fresh nonce for second attempt — sparql not in grant
    chain2 = _query_chain(now=now, nonce="cq-2")
    bad = authz.enforce(
        operation="query",
        target=target,
        auth=auth_context_from_chain(
            chain2,
            principal="did:key:agent",
            extra={"query_kind": "sparql"},
        ),
        now=now,
    )
    assert bad.allowed is False
    assert bad.decision.reason == "caveat_not_attenuated"


def test_nonce_required_for_mutations():
    now = time.time()
    authz = GraphAuthorizationService(require_nonce_for_mutations=True)
    chain = _admin_chain(now=now, leaf_ability="graph/write", nonce=None)
    # Strip nonces entirely
    chain = [
        GraphDelegationLink(
            issuer=lnk.issuer,
            audience=lnk.audience,
            capabilities=lnk.capabilities,
            expiry=lnk.expiry,
            not_before=lnk.not_before,
            cid=lnk.cid,
            proof_cid=lnk.proof_cid,
            nonce=None,
            caveats=lnk.caveats,
        )
        for lnk in chain
    ]
    result = authz.enforce(
        operation="write",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth={"principal": "did:key:agent", "chain": chain},
        now=now,
    )
    assert result.allowed is False
    assert result.decision.reason == "nonce_required"
    assert result.decision.code == "INVALID_REQUEST"


def test_replay_nonce_denied():
    now = time.time()
    authz = GraphAuthorizationService(require_nonce_for_mutations=True)
    chain = _admin_chain(now=now, leaf_ability="graph/write", nonce="replay-n1")
    auth = auth_context_from_chain(chain, principal="did:key:agent", nonce="replay-n1")
    target = GraphTarget(tenant="acme", graph_id="skills")
    first = authz.enforce(operation="write", target=target, auth=auth, now=now)
    assert first.allowed is True
    second = authz.enforce(operation="write", target=target, auth=auth, now=now)
    assert second.allowed is False
    assert second.decision.reason == "replay"
    assert second.decision.code == "FORBIDDEN"


def test_idempotency_key_binds_like_nonce():
    now = time.time()
    authz = GraphAuthorizationService(require_nonce_for_mutations=True)
    # Leaf without nonce; request carries idempotency_key
    root = _link(
        "did:key:root",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/write")],
        expiry=now + 1000,
        cid="idemp-root",
    )
    auth = {
        "principal": "did:key:agent",
        "chain": [root],
        "idempotency_key": "idem-42",
    }
    target = GraphTarget(tenant="acme", graph_id="skills")
    assert authz.enforce(operation="write", target=target, auth=auth, now=now).allowed
    assert (
        authz.enforce(operation="write", target=target, auth=auth, now=now).decision.reason
        == "replay"
    )


# ---------------------------------------------------------------------------
# Pre-access phases (metadata / graph / index / shard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("access_kind", ["metadata", "graph", "index", "shard", "prefetch"])
def test_check_before_access_fail_closed(access_kind: str):
    authz = make_enforcement_context()
    target = GraphTarget(tenant="acme", graph_id="skills")
    result = authz.check_before_access(
        operation="open",
        target=target,
        auth=None,
        access_kind=access_kind,
    )
    assert result.allowed is False
    assert result.phase == f"before_{access_kind}"
    # No catalog/storage side effects — pure decision.
    assert result.receipt.decision == "deny"


def test_check_before_access_allow_with_chain():
    now = time.time()
    authz = make_enforcement_context()
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="pre-1")
    result = authz.check_before_access(
        operation="read_metadata",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain(chain, principal="did:key:agent"),
        access_kind="metadata",
    )
    # read_metadata maps to graph/read
    assert result.allowed is True
    assert result.ability == "graph/read"


# ---------------------------------------------------------------------------
# Audit receipts: digests, redaction, bounds
# ---------------------------------------------------------------------------


def test_receipt_redacts_tokens_and_query_text():
    now = time.time()
    authz = GraphAuthorizationService()
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="redact-1")
    auth = auth_context_from_chain(
        chain,
        principal="did:key:agent",
        extra={
            "ucan_token": "eyJhbGciOiJIUzI1NiJ9.SECRET",
            "signature": "deadbeef",
            "query_text": "MATCH (n) RETURN n",
            "password": "s3cret",
        },
    )
    result = authz.enforce(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth,
        now=now,
    )
    event = result.receipt.to_audit_event()
    blob = str(event)
    assert "SECRET" not in blob
    assert "deadbeef" not in blob or event.get("signature") == "[REDACTED]"
    assert "MATCH (n)" not in blob
    assert "s3cret" not in blob
    assert_receipt_safe(redact_for_audit(auth))
    # Digests present
    assert result.receipt.core.policy_digest.startswith("sha256:")
    assert result.receipt.core.request_digest.startswith("sha256:")
    assert result.receipt.core.chain_digest.startswith("sha256:")
    assert result.receipt.revision_digest.startswith("sha256:")


def test_policy_and_revision_digests_stable():
    d1 = policy_revision_digest(policy_id="p1", policy_revision="r1")
    d2 = policy_revision_digest(policy_id="p1", policy_revision="r1")
    assert d1 == d2
    assert d1 != policy_revision_digest(policy_id="p1", policy_revision="r2")
    assert revision_digest("bafy1") == revision_digest("bafy1")
    assert revision_digest("bafy1") != revision_digest("bafy2")


def test_bound_payload_truncates_large_events():
    huge = {"decision": "allow", "bulk": "x" * 100_000, "receipt_cid": "sha256:abc"}
    out = bound_payload(huge, max_bytes=2_000)
    assert out.get("truncated") is True
    assert out["decision"] == "allow"
    assert "receipt_cid" in out
    assert len(str(out).encode("utf-8")) <= 4_000  # soft bound after trim


def test_audit_log_records_allow_and_deny():
    now = time.time()
    sink = InMemoryAuditSink()
    log = AuthorizationAuditLog(sink=sink)
    authz = GraphAuthorizationService(audit_log=log)
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="log-1")
    authz.enforce(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain(chain, principal="did:key:agent"),
        now=now,
    )
    authz.enforce(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=None,
        now=now,
    )
    assert log.size >= 2
    recent = log.recent(10)
    decisions = {e.get("decision") for e in recent}
    assert "allow" in decisions
    assert "deny" in decisions
    # Secondary sink received events
    assert len(sink.events) >= 2
    for e in recent:
        if e.get("receipt_cid"):
            assert log.get_receipt(e["receipt_cid"]) is not None


def test_enriched_receipt_event_types():
    now = time.time()
    link = _link(
        "did:key:root",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/list")],
        expiry=now + 100,
        nonce="ev-1",
    )
    ok = validate_delegation_chain(
        [link],
        resource="kg://acme/skills",
        ability="graph/list",
        invoker="did:key:agent",
        now=now,
    )
    receipt = build_enriched_receipt(
        result=ok,
        resource="kg://acme/skills",
        ability="graph/list",
        principal="did:key:agent",
        chain=[link],
        revision="bafy-rev",
        operation="list",
        request_id="req-x",
        now=now,
    )
    assert receipt.event_type == "ucan.allow"
    assert receipt.audit_version == AUDIT_MODULE_VERSION
    payload = receipt.to_json_dict()
    assert payload["revision_digest"].startswith("sha256:")
    assert payload["operation"] == "list"


# ---------------------------------------------------------------------------
# GraphService integration (authorization precedes catalog/handler)
# ---------------------------------------------------------------------------


def test_graph_service_denies_before_create_without_token(tmp_path: Path):
    authz = make_enforcement_context(policy_id="policy:svc")
    audit = InMemoryAuditSink()
    authz.bind_audit_sink(audit)
    svc = GraphService.open(tmp_path / "cat.db", authorizer=authz, audit=audit)
    try:
        r = svc.create(
            GraphTarget(tenant="acme", graph_id="g1"),
            idempotency_key="c1",
        )
        assert not r.ok
        assert r.error.code == "UNAUTHORIZED"
        assert r.authorization_receipt_ref
        assert r.authorization_receipt_ref.startswith("sha256:")
        # Catalog must not have created the graph
        listed = svc.list(GraphTarget(tenant="acme", graph_id="g1"))
        # list also denied without token
        assert not listed.ok
    finally:
        svc.close()


def test_graph_service_allow_create_with_admin_chain(tmp_path: Path):
    now = time.time()
    authz = make_enforcement_context(require_nonce_for_mutations=True)
    svc = GraphService.open(tmp_path / "cat.db", authorizer=authz, audit=authz.audit_log)
    try:
        # Grant resource must cover the GraphTarget (same graph_id).
        chain = _admin_chain(
            now=now,
            resource="kg://acme/skills",
            leaf_ability="graph/admin",
            nonce="svc-create-1",
        )
        r = svc.create(
            GraphTarget(tenant="acme", graph_id="skills"),
            idempotency_key="c2",
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
        )
        assert r.ok, r.to_json_dict()
        assert r.authorization_receipt_ref.startswith("sha256:")

        # Subsequent list with list-capable chain on the same graph
        read_chain = _admin_chain(
            now=now,
            resource="kg://acme/skills",
            leaf_ability="graph/list",
            nonce="svc-list-1",
        )
        listed = svc.list(
            GraphTarget(tenant="acme", graph_id="skills"),
            auth=auth_context_from_chain(read_chain, principal="did:key:agent"),
        )
        assert listed.ok, listed.to_json_dict()
    finally:
        svc.close()


def test_graph_service_forbids_sibling_tenant(tmp_path: Path):
    now = time.time()
    authz = make_enforcement_context()
    svc = GraphService.open(tmp_path / "cat.db", authorizer=authz)
    try:
        # Create under acme with valid chain first using allow path
        chain = _admin_chain(
            now=now,
            resource="kg://acme/skills",
            leaf_ability="graph/admin",
            nonce="sib-1",
        )
        created = svc.create(
            GraphTarget(tenant="acme", graph_id="skills"),
            idempotency_key="c3",
            auth=auth_context_from_chain(chain, principal="did:key:agent"),
        )
        assert created.ok, created.to_json_dict()

        # Same principal chain for acme cannot open evil tenant
        evil = svc.open_graph(
            GraphTarget(tenant="evil", graph_id="skills"),
            auth=auth_context_from_chain(
                _admin_chain(
                    now=now,
                    resource="kg://acme/skills",
                    leaf_ability="graph/read",
                    nonce="sib-2",
                ),
                principal="did:key:agent",
            ),
        )
        assert not evil.ok
        assert evil.error.code == "FORBIDDEN"
    finally:
        svc.close()


def test_deny_has_no_storage_side_effect(tmp_path: Path):
    """Denied create must not leave catalog entries."""
    authz = make_enforcement_context()
    # Use permissive second service only to inspect catalog after deny.
    svc = GraphService.open(tmp_path / "cat.db", authorizer=authz)
    try:
        r = svc.create(
            GraphTarget(tenant="acme", graph_id="nope"),
            idempotency_key="nope-1",
            auth={"principal": "did:key:agent"},  # missing chain
        )
        assert not r.ok
    finally:
        svc.close()

    # Reopen with allow-all authorizer to inspect catalog
    from ipfs_datasets_py.knowledge_graphs.service import AllowAllAuthorizer

    svc2 = GraphService.open(tmp_path / "cat.db", authorizer=AllowAllAuthorizer())
    try:
        listed = svc2.list(GraphTarget(tenant="acme", graph_id="nope"))
        assert listed.ok
        graphs = listed.result.get("graphs") if listed.result else None
        # Empty or not containing "nope"
        if graphs is not None:
            ids = {
                g.get("graph_id") if isinstance(g, dict) else getattr(g, "graph_id", None)
                for g in graphs
            }
            assert "nope" not in ids
    finally:
        svc2.close()


# ---------------------------------------------------------------------------
# Python / CLI opt-in surface
# ---------------------------------------------------------------------------


def test_make_enforcement_context_opt_in():
    ctx = make_enforcement_context(
        policy_id="policy:cli",
        policy_revision="cli-1",
        revoked_cids=["bad-cid"],
    )
    assert isinstance(ctx, GraphAuthorizationService)
    assert ctx.policy_id == "policy:cli"
    assert ctx.is_revoked("bad-cid")
    assert ctx.audit_log is not None


def test_authorizer_protocol_matches_graph_service():
    """authorize() signature matches GraphService Authorizer protocol."""
    now = time.time()
    authz = GraphAuthorizationService()
    chain = _admin_chain(now=now, leaf_ability="graph/read", nonce="proto-1")
    decision = authz.authorize(
        operation="open",
        target=GraphTarget(tenant="acme", graph_id="skills"),
        auth=auth_context_from_chain(chain, principal="did:key:agent"),
        request_id="proto-req",
    )
    assert decision.allowed is True
    assert decision.receipt_ref
    assert decision.ability == "graph/read"


def test_revoke_runtime_and_nonce_store():
    store = InMemoryRevocationStore()
    store.revoke("c1")
    assert store.is_revoked("c1")
    nonces = InMemoryNonceStore(max_entries=10)
    assert nonces.remember("n1") is True
    assert nonces.remember("n1") is False
    assert nonces.seen("n1")


def test_auth_context_from_chain_sets_principal_from_leaf():
    now = time.time()
    chain = _admin_chain(now=now, audience="did:key:leaf-user", nonce="ctx-1")
    ctx = auth_context_from_chain(chain)
    assert ctx["principal"] == "did:key:leaf-user"
    assert len(ctx["chain"]) == 2


# ---------------------------------------------------------------------------
# Module / artifact presence
# ---------------------------------------------------------------------------


def test_expected_modules_exist():
    root = Path(__file__).resolve().parents[3]
    assert (root / "ipfs_datasets_py/knowledge_graphs/auth/service.py").is_file()
    assert (root / "ipfs_datasets_py/knowledge_graphs/audit.py").is_file()
