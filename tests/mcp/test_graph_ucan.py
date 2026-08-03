"""KGP-023: MCP graph tools + UCAN negative authorization matrix.

Proves MCP-facing graph operations deny adversarial authorization,
revocation, and replay cases; denials leave no catalog/storage side
effects; and authorization receipts stay safe when UCAN enforcement is
bound into the server-owned GraphService.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest

from ipfs_datasets_py.knowledge_graphs.auth.contracts import (
    GraphCapability,
    GraphCaveats,
    GraphDelegationLink,
    parse_graph_resource,
)
from ipfs_datasets_py.knowledge_graphs.auth.service import (
    GraphAuthorizationService,
    auth_context_from_chain,
    make_enforcement_context,
)
from ipfs_datasets_py.knowledge_graphs.service import (
    AllowAllAuthorizer,
    GraphTarget,
)
from ipfs_datasets_py.mcp_server.graph_service_registry import (
    open_graph_service,
    reset_graph_service_registry,
)
from ipfs_datasets_py.mcp_server.tools.graph_tools._bridge import (
    ABILITY_ADMIN,
    ABILITY_QUERY,
    ABILITY_READ,
    ABILITY_WRITE,
    resolve_auth,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def kg_ucan_binding(tmp_path: Path):
    """Server-owned GraphService with fail-closed UCAN authorizer."""
    reset_graph_service_registry()
    catalog = tmp_path / "kg_ucan_catalog.sqlite"
    store = tmp_path / "kg_ucan_payloads"
    authz = make_enforcement_context(
        policy_id="policy:mcp-graph-ucan",
        policy_revision="kgp-023",
        require_nonce_for_mutations=True,
    )
    binding = open_graph_service(
        catalog,
        storage_path=store,
        force=True,
        authorizer=authz,
    )
    try:
        yield binding, catalog, store, authz
    finally:
        reset_graph_service_registry()


@pytest.fixture
def kg_tenant_binding(tmp_path: Path):
    """Default TenantScopeAuthorizer binding (MCP isolation surface)."""
    reset_graph_service_registry()
    catalog = tmp_path / "kg_tenant_catalog.sqlite"
    store = tmp_path / "kg_tenant_payloads"
    binding = open_graph_service(catalog, storage_path=store, force=True)
    try:
        yield binding, catalog, store
    finally:
        reset_graph_service_registry()


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


def _chain(
    *,
    now: float,
    resource: str = "kg://acme/skills",
    leaf_ability: str = "graph/admin",
    audience: str = "did:key:agent",
    nonce: str = "mcp-n1",
    expiry_delta: float = 10_000,
    leaf_caveats: Optional[dict] = None,
) -> List[GraphDelegationLink]:
    root = _link(
        "did:key:root",
        "did:key:mid",
        [_cap(resource, "graph/admin")],
        expiry=now + expiry_delta,
        cid="mcp-root",
    )
    leaf = _link(
        "did:key:mid",
        audience,
        [_cap(resource, leaf_ability, leaf_caveats)],
        expiry=now + expiry_delta / 2,
        cid="mcp-leaf",
        proof_cid="mcp-root",
        nonce=nonce,
    )
    return [root, leaf]


def _auth(
    chain: Sequence[GraphDelegationLink],
    *,
    principal: str = "did:key:agent",
    **extra: Any,
) -> Dict[str, Any]:
    return auth_context_from_chain(chain, principal=principal, extra=extra or None)


def _assert_error(payload: Dict[str, Any], *, codes: Optional[set] = None) -> None:
    assert payload.get("status") == "error", payload
    assert "error" in payload
    if codes is not None:
        assert payload["error"]["code"] in codes, payload["error"]
    # Envelopes must stay JSON-safe.
    json.dumps(payload, allow_nan=False)


# ---------------------------------------------------------------------------
# Bridge auth normalization
# ---------------------------------------------------------------------------


class TestResolveAuthBridge:
    def test_resolve_auth_carries_ucan_and_principal(self) -> None:
        out = resolve_auth(
            {"abilities": [ABILITY_READ]},
            principal="did:key:agent",
            tenant="acme",
            ucan="profile-c-token",
            token="raw-token",
        )
        assert out is not None
        assert out["principal"] == "did:key:agent"
        assert out["tenant"] == "acme"
        assert out["ucan"] == "profile-c-token"
        assert out["token"] == "raw-token"
        assert ABILITY_READ in out["abilities"]

    def test_mcp_plus_abilities_vocabulary(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            GRAPH_TOOL_FUNCTIONS,
            iter_mcp_plus_metadata,
        )

        metas = dict(iter_mcp_plus_metadata())
        assert metas
        for name, meta in metas.items():
            ability = meta.get("ability")
            assert ability and ability.startswith("graph/"), name
            assert meta.get("resource_template", "").startswith("kg://"), name


# ---------------------------------------------------------------------------
# MCP tools under GraphAuthorizationService (UCAN fail-closed)
# ---------------------------------------------------------------------------


class TestMcpGraphUcanDenial:
    @pytest.mark.asyncio
    async def test_create_without_chain_unauthorized(self, kg_ucan_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        result = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-no-chain",
            auth={"principal": "did:key:agent"},
        )
        _assert_error(result, codes={"UNAUTHORIZED", "FORBIDDEN"})
        # No catalog entry for denied create.
        _, catalog, store, _ = kg_ucan_binding
        reset_graph_service_registry()
        inspect = open_graph_service(
            catalog,
            storage_path=store,
            force=True,
            authorizer=AllowAllAuthorizer(),
        )
        try:
            listed = inspect.service.list(GraphTarget(tenant="acme", graph_id="skills"))
            assert listed.ok
            graphs = (listed.result or {}).get("graphs") or []
            ids = {
                g.get("graph_id") if isinstance(g, dict) else None for g in graphs
            }
            assert "skills" not in ids
        finally:
            reset_graph_service_registry()

    @pytest.mark.asyncio
    async def test_allow_create_then_deny_sibling_tenant(
        self, kg_ucan_binding
    ) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_describe,
        )

        now = time.time()
        _, _, _, authz = kg_ucan_binding
        chain = _chain(now=now, leaf_ability="graph/admin", nonce="mcp-ok-1")
        created = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-ok-create",
            auth=_auth(chain),
        )
        assert created["status"] == "success", created
        assert created.get("authorization_receipt_ref")

        # Same principal cannot describe evil sibling tenant.
        chain2 = _chain(
            now=now,
            resource="kg://acme/skills",
            leaf_ability="graph/read",
            nonce="mcp-sib-1",
        )
        denied = await graph_describe(
            target="kg://evil/skills",
            auth=_auth(chain2),
        )
        _assert_error(denied, codes={"FORBIDDEN", "UNAUTHORIZED", "NOT_FOUND"})

    @pytest.mark.asyncio
    async def test_deny_sibling_graph(self, kg_ucan_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_describe,
        )

        now = time.time()
        chain = _chain(
            now=now,
            resource="kg://acme/skills",
            leaf_ability="graph/admin",
            nonce="mcp-g-1",
        )
        ok = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-g-create",
            auth=_auth(chain),
        )
        assert ok["status"] == "success", ok

        read_chain = _chain(
            now=now,
            resource="kg://acme/skills",
            leaf_ability="graph/read",
            nonce="mcp-g-2",
        )
        denied = await graph_describe(
            target="kg://acme/payroll",
            auth=_auth(read_chain),
        )
        _assert_error(denied, codes={"FORBIDDEN", "UNAUTHORIZED", "NOT_FOUND"})

    @pytest.mark.asyncio
    async def test_deny_wrong_audience(self, kg_ucan_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        now = time.time()
        chain = _chain(now=now, leaf_ability="graph/admin", nonce="mcp-aud")
        denied = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-aud-create",
            auth=_auth(chain, principal="did:key:impostor"),
        )
        _assert_error(denied, codes={"FORBIDDEN", "UNAUTHORIZED"})

    @pytest.mark.asyncio
    async def test_deny_expired_chain(self, kg_ucan_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        now = time.time()
        chain = _chain(
            now=now - 50_000,
            leaf_ability="graph/admin",
            nonce="mcp-exp",
            expiry_delta=10,
        )
        denied = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-exp-create",
            auth=_auth(chain),
        )
        _assert_error(denied, codes={"FORBIDDEN", "UNAUTHORIZED"})

    @pytest.mark.asyncio
    async def test_deny_revoked_ancestor(self, kg_ucan_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        now = time.time()
        _, _, _, authz = kg_ucan_binding
        authz.revoke("mcp-root")
        chain = _chain(now=now, leaf_ability="graph/admin", nonce="mcp-rev")
        denied = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-rev-create",
            auth=_auth(chain),
        )
        _assert_error(denied, codes={"FORBIDDEN", "UNAUTHORIZED"})

    @pytest.mark.asyncio
    async def test_deny_replayed_mutation(self, kg_ucan_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        now = time.time()
        chain = _chain(now=now, leaf_ability="graph/admin", nonce="mcp-replay-1")
        auth = _auth(chain, nonce="mcp-replay-1")
        first = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-replay-create",
            auth=auth,
        )
        assert first["status"] == "success", first

        # Same UCAN nonce on a second mutating create for another graph.
        chain2 = _chain(
            now=now,
            resource="kg://acme/other",
            leaf_ability="graph/admin",
            nonce="mcp-replay-1",  # reused nonce
        )
        second = await graph_create(
            target="kg://acme/other/branches/main",
            idempotency_key="mcp-replay-create-2",
            auth=_auth(chain2, nonce="mcp-replay-1"),
        )
        _assert_error(second, codes={"FORBIDDEN", "UNAUTHORIZED", "INVALID_REQUEST"})

    @pytest.mark.asyncio
    async def test_deny_widened_ability_write(self, kg_ucan_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_write,
        )

        now = time.time()
        # Bootstrap graph with admin chain.
        admin = _chain(now=now, leaf_ability="graph/admin", nonce="mcp-w-admin")
        created = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-w-create",
            auth=_auth(admin),
        )
        assert created["status"] == "success", created

        # Parent only grants read; child claims write → attenuation fail.
        root = _link(
            "did:key:root",
            "did:key:mid",
            [_cap("kg://acme/skills", "graph/read")],
            expiry=now + 1000,
            cid="mcp-widen-root",
        )
        leaf = _link(
            "did:key:mid",
            "did:key:agent",
            [_cap("kg://acme/skills", "graph/write")],
            expiry=now + 500,
            cid="mcp-widen-leaf",
            nonce="mcp-widen-1",
        )
        denied = await graph_write(
            target="kg://acme/skills/branches/main",
            entities=[{"id": "x", "type": "T", "name": "n"}],
            idempotency_key="mcp-widen-w",
            auth=_auth([root, leaf]),
        )
        _assert_error(denied, codes={"FORBIDDEN", "UNAUTHORIZED"})

    @pytest.mark.asyncio
    async def test_deny_substituted_revision_caveat(self, kg_ucan_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_describe,
        )

        now = time.time()
        admin = _chain(now=now, leaf_ability="graph/admin", nonce="mcp-revsub-a")
        created = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-revsub-c",
            auth=_auth(admin),
        )
        assert created["status"] == "success", created
        allowed_rev = (created.get("result") or {}).get("revision")
        assert allowed_rev

        # Grant only a different revision pin.
        root = _link(
            "did:key:root",
            "did:key:agent",
            [
                _cap(
                    "kg://acme/skills",
                    "graph/read",
                    {"revision": ["bafy-not-the-real-one"]},
                )
            ],
            expiry=now + 1000,
            cid="mcp-revsub",
            nonce="mcp-revsub-1",
        )
        denied = await graph_describe(
            target=f"kg://acme/skills/revisions/{allowed_rev}",
            auth=_auth([root]),
        )
        _assert_error(denied, codes={"FORBIDDEN", "UNAUTHORIZED", "NOT_FOUND"})

    @pytest.mark.asyncio
    async def test_deny_malformed_and_oversized_token(
        self, kg_ucan_binding
    ) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        huge = "Z" * 100_000
        denied = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-huge",
            auth={
                "principal": "did:key:agent",
                "token": huge,
                "ucan": huge,
                "signature": "REDACT_PROBE_SIGNATURE_v1" * 500,
                "chain": [{"not": "a valid link"}],
            },
        )
        _assert_error(
            denied, codes={"UNAUTHORIZED", "FORBIDDEN", "INVALID_REQUEST"}
        )

    @pytest.mark.asyncio
    async def test_deny_confused_deputy_cross_tenant_write(
        self, kg_ucan_binding
    ) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_write,
        )

        now = time.time()
        # Create acme graph legitimately.
        admin = _chain(now=now, leaf_ability="graph/admin", nonce="mcp-cd-a")
        assert (
            await graph_create(
                target="kg://acme/skills/branches/main",
                idempotency_key="mcp-cd-c",
                auth=_auth(admin),
            )
        )["status"] == "success"

        # Create evil graph under allow path would require grant — instead
        # attempt write to evil with acme-only chain (confused deputy).
        chain = _chain(
            now=now,
            resource="kg://acme/skills",
            leaf_ability="graph/write",
            audience="did:key:service",
            nonce="mcp-cd-w",
        )
        denied = await graph_write(
            target="kg://evil/skills/branches/main",
            entities=[{"id": "leak", "type": "Person", "name": "x"}],
            idempotency_key="mcp-cd-write",
            auth=_auth(chain, principal="did:key:service"),
        )
        _assert_error(denied, codes={"FORBIDDEN", "UNAUTHORIZED", "NOT_FOUND"})

    @pytest.mark.asyncio
    async def test_deny_query_with_wrong_ability(self, kg_ucan_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_query_cypher,
        )

        now = time.time()
        admin = _chain(now=now, leaf_ability="graph/admin", nonce="mcp-q-a")
        assert (
            await graph_create(
                target="kg://acme/skills/branches/main",
                idempotency_key="mcp-q-c",
                auth=_auth(admin),
            )
        )["status"] == "success"

        # list-only grant cannot query.
        list_chain = _chain(
            now=now,
            leaf_ability="graph/list",
            nonce="mcp-q-list",
        )
        denied = await graph_query_cypher(
            target="kg://acme/skills/branches/main",
            query="MATCH (n) RETURN n LIMIT 1",
            auth=_auth(list_chain),
        )
        _assert_error(denied, codes={"FORBIDDEN", "UNAUTHORIZED"})

    @pytest.mark.asyncio
    async def test_deny_receipt_ref_present_and_safe(
        self, kg_ucan_binding
    ) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        result = await graph_create(
            target="kg://acme/skills/branches/main",
            idempotency_key="mcp-receipt",
            auth={
                "principal": "did:key:agent",
                "ucan_token": "REDACT_PROBE_UCAN_TOKEN_v1.xxx",
                "password": "redacted-probe-password-v1",
                "signature": "REDACT_PROBE_SIGNATURE_v1",
            },
        )
        _assert_error(result, codes={"UNAUTHORIZED", "FORBIDDEN"})
        # Receipt ref should be content-addressed when authorizer emits one.
        ref = result.get("authorization_receipt_ref")
        if ref:
            assert str(ref).startswith("sha256:") or str(ref).startswith(
                "auth-receipt-"
            )
        blob = json.dumps(result, default=str)
        assert "REDACT_PROBE_UCAN_TOKEN_v1" not in blob
        assert "redacted-probe-password-v1" not in blob


# ---------------------------------------------------------------------------
# TenantScopeAuthorizer path (MCP client isolation, no full UCAN chain)
# ---------------------------------------------------------------------------


class TestMcpTenantScopeNegatives:
    @pytest.mark.asyncio
    async def test_tenant_scope_forbids_sibling(self, kg_tenant_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_list,
            graph_search_hybrid,
        )

        await graph_create(
            target="kg://tenant-a/private/branches/main",
            idempotency_key="ts-a-c",
        )
        await graph_create(
            target="kg://tenant-b/public/branches/main",
            idempotency_key="ts-b-c",
        )

        denied = await graph_search_hybrid(
            query="",
            target="kg://tenant-a/private/branches/main",
            language="scan",
            auth={
                "principal": "client-b",
                "tenant": "tenant-b",
                "abilities": [ABILITY_QUERY, ABILITY_READ, "graph/list"],
            },
        )
        _assert_error(denied, codes={"FORBIDDEN"})

        listed = await graph_list(
            tenant="tenant-b",
            auth={
                "principal": "client-b",
                "tenant": "tenant-b",
                "abilities": ["graph/list"],
            },
        )
        assert listed["status"] == "success"
        assert all(
            g.get("graph_id") != "private" for g in listed["result"]["graphs"]
        )

    @pytest.mark.asyncio
    async def test_cursor_cannot_cross_tenant(self, kg_tenant_binding) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import (
            graph_create,
            graph_query_stream,
            graph_write,
        )

        await graph_create(
            target="kg://tenant-a/s1/branches/main",
            idempotency_key="cur-a-c",
        )
        await graph_write(
            target="kg://tenant-a/s1/branches/main",
            entities=[
                {"id": f"e{i}", "type": "T", "name": f"n{i}"} for i in range(3)
            ],
            idempotency_key="cur-a-w",
        )
        page = await graph_query_stream(
            target="kg://tenant-a/s1/branches/main",
            language="scan",
            page_size=1,
            auth={"principal": "a", "tenant": "tenant-a"},
        )
        assert page["status"] == "success", page
        cursor = page["result"]["cursor"]
        assert cursor

        hijack = await graph_query_stream(
            target="kg://tenant-b/other/branches/main",
            cursor=cursor,
            auth={"principal": "b", "tenant": "tenant-b"},
        )
        _assert_error(
            hijack, codes={"FORBIDDEN", "NOT_FOUND", "INVALID_TARGET", "INVALID_REQUEST"}
        )

    @pytest.mark.asyncio
    async def test_ability_scope_denies_admin_without_grant(
        self, kg_tenant_binding
    ) -> None:
        from ipfs_datasets_py.mcp_server.tools.graph_tools import graph_create

        denied = await graph_create(
            target="kg://tenant-x/g1/branches/main",
            idempotency_key="ts-ab-c",
            auth={
                "principal": "reader",
                "tenant": "tenant-x",
                "abilities": [ABILITY_READ, ABILITY_QUERY],
            },
        )
        _assert_error(denied, codes={"FORBIDDEN"})


# ---------------------------------------------------------------------------
# Direct authorizer unit surface used by MCP bindings
# ---------------------------------------------------------------------------


class TestUcanAuthorizerForMcp:
    def test_prefetch_denied_before_shard_access(self) -> None:
        authz = GraphAuthorizationService()
        result = authz.check_before_access(
            operation="prefetch_shard",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=None,
            access_kind="prefetch",
        )
        assert result.allowed is False
        assert result.phase == "before_prefetch"
        assert result.receipt.decision == "deny"

    def test_not_yet_valid_denied(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService()
        root = _link(
            "did:key:root",
            "did:key:agent",
            [_cap("kg://acme/skills", "graph/read")],
            not_before=now + 10_000,
            expiry=now + 20_000,
            cid="nyv-mcp",
            nonce="nyv-mcp-1",
        )
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=_auth([root]),
            now=now,
        )
        assert result.allowed is False
        assert result.decision.reason == "not_yet_valid"

    def test_revoked_child_denied(self) -> None:
        now = time.time()
        authz = GraphAuthorizationService.create(revoked_cids=["mcp-leaf"])
        chain = _chain(now=now, leaf_ability="graph/read", nonce="rev-child")
        result = authz.enforce(
            operation="open",
            target=GraphTarget(tenant="acme", graph_id="skills"),
            auth=_auth(chain),
            now=now,
        )
        assert result.allowed is False
        assert result.decision.reason == "revoked"


# ---------------------------------------------------------------------------
# Module presence
# ---------------------------------------------------------------------------


def test_expected_mcp_graph_ucan_module() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "tests/mcp/test_graph_ucan.py").is_file()
    assert (
        root / "ipfs_datasets_py/mcp_server/tools/graph_tools/_bridge.py"
    ).is_file()
