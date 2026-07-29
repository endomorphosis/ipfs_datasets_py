"""KGP-021: Graph UCAN resource, ability, and caveat contract regressions.

Validates ``ipfs_datasets_py.knowledge_graphs.auth.contracts`` against the
normative ADR ``docs/architecture/knowledge_graphs_ucan.md``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

import pytest

from ipfs_datasets_py.knowledge_graphs.auth.contracts import (
    AUDIT_EVENT_TYPES,
    AUDIT_REDACT_KEYS,
    CAVEAT_KEYS,
    CONTRACT_VERSION,
    DENY_REASONS,
    ERROR_CODE_MAP,
    GRAPH_ABILITIES,
    OPERATION_ABILITIES,
    QUERY_KINDS,
    AuthorizationReceipt,
    GraphCapability,
    GraphCaveats,
    GraphDelegationLink,
    GraphResource,
    UCANContractError,
    abilities_cover,
    ability_contains,
    ability_for_operation,
    assert_ability_attenuated,
    assert_capability_attenuated,
    assert_caveats_attenuated,
    assert_resource_contained,
    build_authorization_receipt,
    capability_contains,
    caveat_contains,
    caveats_allow_request,
    caveats_from_mapping,
    content_digest,
    deny_reason_to_error_code,
    link_from_delegation_token,
    link_to_profile_c_capability_dicts,
    normalize_ability,
    parse_graph_resource,
    redact_for_audit,
    resource_contains,
    resource_to_uri,
    validate_chain_attenuation,
    validate_chain_audience,
    validate_chain_issuance,
    validate_chain_replay,
    validate_chain_revocation,
    validate_chain_time,
    validate_delegation_chain,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
UCAN_ADR = REPO_ROOT / "docs/architecture/knowledge_graphs_ucan.md"
CONTRACTS_MOD = (
    REPO_ROOT / "ipfs_datasets_py/knowledge_graphs/auth/contracts.py"
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
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


@dataclass
class _FakeCap:
    resource: str
    ability: str


@dataclass
class _FakeToken:
    issuer: str
    audience: str
    capabilities: List[Any]
    expiry: Optional[float] = None
    not_before: Optional[float] = None
    cid: Optional[str] = None
    proof_cid: Optional[str] = None
    nonce: Optional[str] = None


# ---------------------------------------------------------------------------
# ADR / vocabulary presence
# ---------------------------------------------------------------------------


def test_contract_version_and_artifacts_exist():
    assert CONTRACT_VERSION == "kg-ucan-contract/v1"
    assert UCAN_ADR.is_file()
    assert CONTRACTS_MOD.is_file()
    text = UCAN_ADR.read_text(encoding="utf-8")
    for needle in (
        "graph/list",
        "graph/read",
        "graph/query",
        "graph/write",
        "graph/admin",
        "graph/pin",
        "graph/delegate",
        "branch",
        "revision",
        "monotonic",
        "revocation",
        "replay",
        "kg-ucan-contract/v1",
    ):
        assert needle in text


def test_closed_vocabularies():
    assert GRAPH_ABILITIES == frozenset(
        {
            "graph/list",
            "graph/read",
            "graph/query",
            "graph/write",
            "graph/admin",
            "graph/pin",
            "graph/delegate",
        }
    )
    assert CAVEAT_KEYS == frozenset(
        {
            "branch",
            "revision",
            "query",
            "property",
            "row",
            "byte",
            "depth",
            "time",
            "audience",
            "count",
        }
    )
    assert "cypher" in QUERY_KINDS
    assert "ucan.allow" in AUDIT_EVENT_TYPES
    assert "token" in AUDIT_REDACT_KEYS
    for reason in DENY_REASONS:
        assert reason in ERROR_CODE_MAP


def test_operation_ability_map_covers_lifecycle():
    for op in (
        "create",
        "list",
        "describe",
        "open",
        "branch",
        "delete",
        "write",
        "query",
        "begin_tx",
        "commit_tx",
        "rollback_tx",
        "pin",
        "unpin",
        "delegate",
    ):
        ability = ability_for_operation(op)
        assert ability in GRAPH_ABILITIES
    assert ability_for_operation("query") == "graph/query"
    assert ability_for_operation("write") == "graph/write"
    assert ability_for_operation("create") == "graph/admin"


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri,tenant,graph_id,branch,revision,wildcard",
    [
        ("kg://acme", "acme", None, None, None, False),
        ("kg://acme/*", "acme", None, None, None, True),
        ("kg://acme/skills", "acme", "skills", None, None, False),
        ("kg://acme/skills/branches/main", "acme", "skills", "main", None, False),
        (
            "kg://acme/skills/revisions/bafyreib123",
            "acme",
            "skills",
            None,
            "bafyreib123",
            False,
        ),
    ],
)
def test_parse_and_roundtrip_resource(uri, tenant, graph_id, branch, revision, wildcard):
    res = parse_graph_resource(uri)
    assert res.tenant == tenant
    assert res.graph_id == graph_id
    assert res.branch == branch
    assert res.revision == revision
    assert res.wildcard_graph is wildcard
    assert resource_to_uri(res) == uri
    assert GraphResource.from_uri(uri).uri == uri


def test_invalid_resources_rejected():
    with pytest.raises(UCANContractError) as ei:
        parse_graph_resource("https://example/not-kg")
    assert ei.value.reason == "invalid_resource"

    with pytest.raises(UCANContractError):
        parse_graph_resource("kg://ACME/skills")  # uppercase tenant

    with pytest.raises(UCANContractError):
        GraphResource(tenant="acme", graph_id="skills", branch="main", revision="r1")


def test_resource_containment_matrix():
    base = "kg://acme/skills"
    branch = "kg://acme/skills/branches/main"
    other_branch = "kg://acme/skills/branches/dev"
    rev = "kg://acme/skills/revisions/bafy1"
    other_tenant = "kg://other/skills"
    tenant = "kg://acme"
    tenant_star = "kg://acme/*"

    assert resource_contains(base, base)
    assert resource_contains(base, branch)
    assert resource_contains(base, rev)
    assert resource_contains(tenant, base)
    assert resource_contains(tenant_star, branch)
    assert resource_contains(branch, branch)

    assert not resource_contains(branch, base)
    assert not resource_contains(branch, other_branch)
    assert not resource_contains(branch, rev)
    assert not resource_contains(rev, branch)
    assert not resource_contains(base, other_tenant)
    assert not resource_contains(other_tenant, base)
    assert not resource_contains(branch, "kg://acme/other/branches/main")

    assert_resource_contained(base, branch)
    with pytest.raises(UCANContractError) as ei:
        assert_resource_contained(branch, base)
    assert ei.value.reason == "resource_not_contained"
    assert ei.value.error_code == "FORBIDDEN"


# ---------------------------------------------------------------------------
# Abilities
# ---------------------------------------------------------------------------


def test_ability_normalization_and_unknown():
    assert normalize_ability("graph/read") == "graph/read"
    with pytest.raises(UCANContractError) as ei:
        normalize_ability("graph/execute")
    assert ei.value.reason == "unknown_ability"
    assert ei.value.error_code == "INVALID_REQUEST"


def test_ability_attenuation_lattice():
    assert ability_contains("graph/admin", "graph/write")
    assert ability_contains("graph/admin", "graph/delegate")
    assert ability_contains("graph/write", "graph/read")
    assert ability_contains("graph/write", "graph/query")
    assert ability_contains("graph/write", "graph/list")
    assert ability_contains("graph/read", "graph/list")
    assert ability_contains("graph/pin", "graph/pin")
    assert ability_contains("graph/query", "graph/query")

    assert not ability_contains("graph/read", "graph/write")
    assert not ability_contains("graph/list", "graph/read")
    assert not ability_contains("graph/pin", "graph/write")
    assert not ability_contains("graph/delegate", "graph/admin")
    assert not ability_contains("graph/query", "graph/list")

    assert_ability_attenuated("graph/admin", "graph/query")
    with pytest.raises(UCANContractError) as ei:
        assert_ability_attenuated("graph/list", "graph/admin")
    assert ei.value.reason == "ability_not_attenuated"

    assert abilities_cover(["graph/admin"], "graph/pin")
    assert not abilities_cover(["graph/read"], "graph/write")


# ---------------------------------------------------------------------------
# Caveats
# ---------------------------------------------------------------------------


def test_caveats_parse_closed_keys_and_aliases():
    cav = caveats_from_mapping(
        {
            "branch": ["main", "dev"],
            "revision": "bafy1",
            "query": ["cypher", "hybrid"],
            "property": ["name", "score"],
            "row": 100,
            "byte": 1_000_000,
            "depth": 4,
            "count": 10,
            "audience": ["did:key:zAlice"],
            "exp": 9_999_999_999,
            "nbf": 1_000,
            "ttl": 3600,
        }
    )
    assert cav.branch == frozenset({"main", "dev"})
    assert cav.revision == frozenset({"bafy1"})
    assert cav.query == frozenset({"cypher", "hybrid"})
    assert cav.row == 100
    assert cav.byte == 1_000_000
    assert cav.depth == 4
    assert cav.count == 10
    assert cav.audience == frozenset({"did:key:zAlice"})
    assert cav.time is not None
    assert "expiry" in cav.time
    assert "not_before" in cav.time
    assert cav.time["max_ttl_seconds"] == 3600
    assert set(cav.to_json_dict()) <= CAVEAT_KEYS


def test_unknown_caveat_key_and_query_kind_rejected():
    with pytest.raises(UCANContractError) as ei:
        caveats_from_mapping({"storage_profile": "parquet"})
    assert ei.value.reason == "unknown_caveat_key"

    with pytest.raises(UCANContractError) as ei:
        caveats_from_mapping({"query": ["nope"]})
    assert ei.value.reason == "invalid_caveat"

    with pytest.raises(UCANContractError):
        caveats_from_mapping({"row": -1})


def test_caveat_monotonic_attenuation():
    parent = GraphCaveats.from_mapping(
        {
            "branch": ["main", "dev"],
            "query": ["cypher", "sparql"],
            "row": 100,
            "byte": 5000,
            "depth": 8,
            "count": 20,
            "property": ["a", "b", "c"],
            "audience": ["did:key:zA", "did:key:zB"],
            "time": {"expiry": 2000.0, "not_before": 100.0, "max_ttl_seconds": 3600},
        }
    )
    child_ok = GraphCaveats.from_mapping(
        {
            "branch": ["main"],
            "query": ["cypher"],
            "row": 50,
            "byte": 1000,
            "depth": 3,
            "count": 5,
            "property": ["a"],
            "audience": ["did:key:zA"],
            "time": {"expiry": 1500.0, "not_before": 200.0, "max_ttl_seconds": 600},
        }
    )
    assert caveat_contains(parent, child_ok)
    assert_caveats_attenuated(parent, child_ok)

    # Child may further restrict an unrestricted parent dimension.
    loose_parent = GraphCaveats.empty()
    tight_child = GraphCaveats.from_mapping({"row": 10, "branch": ["main"]})
    assert caveat_contains(loose_parent, tight_child)

    # Dropping a parent restriction is not attenuation.
    child_drop_branch = GraphCaveats.from_mapping(
        {
            "query": ["cypher"],
            "row": 50,
            "byte": 1000,
            "depth": 3,
            "count": 5,
            "property": ["a"],
            "audience": ["did:key:zA"],
            "time": {"expiry": 1500.0, "not_before": 200.0, "max_ttl_seconds": 600},
        }
    )
    assert not caveat_contains(parent, child_drop_branch)

    # Widening a set is not attenuation.
    child_wide = GraphCaveats.from_mapping(
        {
            "branch": ["main", "dev", "staging"],
            "query": ["cypher"],
            "row": 50,
            "byte": 1000,
            "depth": 3,
            "count": 5,
            "property": ["a"],
            "audience": ["did:key:zA"],
            "time": {"expiry": 1500.0, "not_before": 200.0, "max_ttl_seconds": 600},
        }
    )
    assert not caveat_contains(parent, child_wide)

    # Raising an upper bound is not attenuation.
    child_more_rows = GraphCaveats.from_mapping(
        {
            "branch": ["main"],
            "query": ["cypher"],
            "row": 200,
            "byte": 1000,
            "depth": 3,
            "count": 5,
            "property": ["a"],
            "audience": ["did:key:zA"],
            "time": {"expiry": 1500.0, "not_before": 200.0, "max_ttl_seconds": 600},
        }
    )
    assert not caveat_contains(parent, child_more_rows)

    # Extending expiry past parent is not attenuation.
    child_late = GraphCaveats.from_mapping(
        {
            "branch": ["main"],
            "query": ["cypher"],
            "row": 50,
            "byte": 1000,
            "depth": 3,
            "count": 5,
            "property": ["a"],
            "audience": ["did:key:zA"],
            "time": {"expiry": 9000.0, "not_before": 200.0, "max_ttl_seconds": 600},
        }
    )
    assert not caveat_contains(parent, child_late)

    with pytest.raises(UCANContractError) as ei:
        assert_caveats_attenuated(parent, child_drop_branch)
    assert ei.value.reason == "caveat_not_attenuated"


def test_caveats_allow_request():
    cav = GraphCaveats.from_mapping(
        {
            "branch": ["main"],
            "query": ["cypher"],
            "row": 10,
            "byte": 1000,
            "depth": 2,
            "count": 3,
            "property": ["name"],
            "audience": ["did:key:zAlice"],
            "time": {"expiry": time.time() + 3600, "not_before": time.time() - 10},
        }
    )
    ok, reason = caveats_allow_request(
        cav,
        branch="main",
        query_kind="cypher",
        properties=["name"],
        rows=5,
        bytes_=100,
        depth=1,
        audience="did:key:zAlice",
        mutation_count=1,
    )
    assert ok and reason is None

    ok, reason = caveats_allow_request(cav, branch="dev", query_kind="cypher")
    assert not ok and reason == "caveat_not_attenuated"

    ok, reason = caveats_allow_request(
        cav, branch="main", query_kind="cypher", rows=50
    )
    assert not ok

    ok, reason = caveats_allow_request(
        cav,
        branch="main",
        query_kind="cypher",
        audience="did:key:zEve",
    )
    assert not ok and reason == "audience_mismatch"

    expired = GraphCaveats.from_mapping({"time": {"expiry": time.time() - 5}})
    ok, reason = caveats_allow_request(expired)
    assert not ok and reason == "expired"

    nbf = GraphCaveats.from_mapping({"time": {"not_before": time.time() + 10_000}})
    ok, reason = caveats_allow_request(nbf)
    assert not ok and reason == "not_yet_valid"


# ---------------------------------------------------------------------------
# Capability attenuation
# ---------------------------------------------------------------------------


def test_capability_contains_and_covers():
    parent = _cap("kg://acme/skills", "graph/admin", {"row": 100})
    child = _cap(
        "kg://acme/skills/branches/main",
        "graph/query",
        {"row": 10, "query": ["cypher"]},
    )
    assert capability_contains(parent, child)
    assert parent.attenuates_to(child)
    assert parent.covers("kg://acme/skills/branches/main", "graph/read")
    assert not parent.covers("kg://other/skills", "graph/read")
    assert not _cap("kg://acme/skills", "graph/read").covers(
        "kg://acme/skills", "graph/write"
    )

    assert_capability_attenuated(parent, child)
    with pytest.raises(UCANContractError):
        assert_capability_attenuated(child, parent)


# ---------------------------------------------------------------------------
# Chain: issuance, attenuation, time, revocation, audience, replay
# ---------------------------------------------------------------------------


def test_validate_chain_issuance_ok_and_break():
    root = _link("did:key:root", "did:key:mid", [_cap("kg://acme/skills", "graph/admin")])
    leaf = _link("did:key:mid", "did:key:agent", [_cap("kg://acme/skills", "graph/read")])
    assert validate_chain_issuance([root, leaf]) is None

    broken = _link(
        "did:key:stranger", "did:key:agent", [_cap("kg://acme/skills", "graph/read")]
    )
    failure = validate_chain_issuance([root, broken])
    assert failure is not None
    assert failure.reason == "issuer_mismatch"
    assert failure.error_code == "FORBIDDEN"

    empty = validate_chain_issuance([])
    assert empty is not None and empty.reason == "empty_chain"
    assert empty.error_code == "UNAUTHORIZED"


def test_validate_chain_attenuation_resource_ability_caveat_expiry():
    now = time.time()
    root = _link(
        "did:key:root",
        "did:key:mid",
        [_cap("kg://acme/skills", "graph/admin", {"row": 100})],
        expiry=now + 10_000,
        caveats={"branch": ["main", "dev"]},
    )
    good_leaf = _link(
        "did:key:mid",
        "did:key:agent",
        [_cap("kg://acme/skills/branches/main", "graph/query", {"row": 10})],
        expiry=now + 5_000,
        caveats={"branch": ["main"]},
    )
    assert validate_chain_attenuation([root, good_leaf]) is None

    # Ability escalation
    escalate = _link(
        "did:key:mid",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/admin")],
        expiry=now + 5_000,
        caveats={"branch": ["main"]},
    )
    # Parent admin can grant admin — use write parent instead.
    write_root = _link(
        "did:key:root",
        "did:key:mid",
        [_cap("kg://acme/skills", "graph/write")],
        expiry=now + 10_000,
    )
    bad_ability = _link(
        "did:key:mid",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/admin")],
        expiry=now + 5_000,
    )
    failure = validate_chain_attenuation([write_root, bad_ability])
    assert failure is not None
    assert failure.allowed is False

    # Resource escape to other tenant
    escape = _link(
        "did:key:mid",
        "did:key:agent",
        [_cap("kg://other/skills", "graph/read")],
        expiry=now + 5_000,
        caveats={"branch": ["main"]},
    )
    failure = validate_chain_attenuation([root, escape])
    assert failure is not None
    assert failure.reason in {
        "resource_not_contained",
        "ability_not_attenuated",
        "caveat_not_attenuated",
    }

    # Expiry extension past parent
    long_lived = _link(
        "did:key:mid",
        "did:key:agent",
        [_cap("kg://acme/skills/branches/main", "graph/read")],
        expiry=now + 50_000,
        caveats={"branch": ["main"]},
    )
    failure = validate_chain_attenuation([root, long_lived])
    assert failure is not None
    assert failure.reason == "caveat_not_attenuated"


def test_validate_chain_time_revocation_audience_replay():
    now = time.time()
    root = _link(
        "did:key:root",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/read")],
        expiry=now + 100,
        not_before=now - 100,
        cid="cid-root",
        nonce="n1",
    )

    assert validate_chain_time([root], now=now) is None
    expired = _link(
        "did:key:root",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/read")],
        expiry=now - 1,
        cid="cid-x",
    )
    failure = validate_chain_time([expired], now=now)
    assert failure is not None and failure.reason == "expired"

    nbf = _link(
        "did:key:root",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/read")],
        not_before=now + 1000,
    )
    failure = validate_chain_time([nbf], now=now)
    assert failure is not None and failure.reason == "not_yet_valid"

    failure = validate_chain_revocation([root], revoked_cids={"cid-root"})
    assert failure is not None and failure.reason == "revoked"
    assert validate_chain_revocation([root], revoked_cids={"other"}) is None

    assert (
        validate_chain_audience([root], invoker="did:key:agent", require_invoker=True)
        is None
    )
    failure = validate_chain_audience(
        [root], invoker="did:key:eve", require_invoker=True
    )
    assert failure is not None and failure.reason == "audience_mismatch"
    failure = validate_chain_audience([root], invoker=None, require_invoker=True)
    assert failure is not None and failure.reason == "missing_principal"
    assert failure.error_code == "UNAUTHORIZED"

    assert validate_chain_replay([root], seen_nonces=set()) is None
    failure = validate_chain_replay([root], seen_nonces={"n1"})
    assert failure is not None and failure.reason == "replay"

    no_nonce = _link(
        "did:key:root",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/write")],
    )
    failure = validate_chain_replay(
        [no_nonce], require_nonce=True, ability="graph/write"
    )
    assert failure is not None and failure.reason == "nonce_required"
    assert failure.error_code == "INVALID_REQUEST"


def test_validate_delegation_chain_end_to_end_allow_and_deny():
    now = time.time()
    root = _link(
        "did:key:root",
        "did:key:mid",
        [_cap("kg://acme/skills", "graph/admin")],
        expiry=now + 10_000,
        cid="c0",
    )
    leaf = _link(
        "did:key:mid",
        "did:key:agent",
        [
            _cap(
                "kg://acme/skills/branches/main",
                "graph/query",
                {"query": ["cypher"], "row": 50},
            )
        ],
        expiry=now + 5_000,
        cid="c1",
        proof_cid="c0",
        nonce="once-1",
    )
    result = validate_delegation_chain(
        [root, leaf],
        resource="kg://acme/skills/branches/main",
        ability="graph/query",
        invoker="did:key:agent",
        now=now,
    )
    assert result.allowed is True
    assert result.root_issuer == "did:key:root"
    assert result.leaf_audience == "did:key:agent"
    assert result.effective_capabilities

    # Wrong ability
    denied = validate_delegation_chain(
        [root, leaf],
        resource="kg://acme/skills/branches/main",
        ability="graph/write",
        invoker="did:key:agent",
        now=now,
    )
    assert denied.allowed is False
    assert denied.reason == "capability_missing"
    assert denied.error_code == "FORBIDDEN"

    # Cross-tenant
    denied = validate_delegation_chain(
        [root, leaf],
        resource="kg://evil/skills/branches/main",
        ability="graph/query",
        invoker="did:key:agent",
        now=now,
    )
    assert denied.allowed is False

    # Revoked proof
    denied = validate_delegation_chain(
        [root, leaf],
        resource="kg://acme/skills/branches/main",
        ability="graph/query",
        invoker="did:key:agent",
        now=now,
        revoked_cids={"c0"},
    )
    assert denied.allowed is False
    assert denied.reason == "revoked"

    # Replay
    denied = validate_delegation_chain(
        [root, leaf],
        resource="kg://acme/skills/branches/main",
        ability="graph/query",
        invoker="did:key:agent",
        now=now,
        seen_nonces={"once-1"},
    )
    assert denied.allowed is False
    assert denied.reason == "replay"


# ---------------------------------------------------------------------------
# Profile C adapter (no invented token format)
# ---------------------------------------------------------------------------


def test_link_from_delegation_token_adapter():
    token = _FakeToken(
        issuer="did:key:root",
        audience="did:key:agent",
        capabilities=[_FakeCap("kg://acme/skills", "graph/read")],
        expiry=time.time() + 100,
        cid="tok-1",
        nonce="n-adapter",
    )
    link = link_from_delegation_token(token)
    assert link.issuer == "did:key:root"
    assert link.audience == "did:key:agent"
    assert link.capabilities[0].ability == "graph/read"
    assert link.capabilities[0].resource.uri == "kg://acme/skills"
    exported = link_to_profile_c_capability_dicts(link)
    assert exported == [{"resource": "kg://acme/skills", "ability": "graph/read"}]


def test_optional_profile_c_import_shapes():
    """When Profile C is importable, real Capability objects adapt cleanly."""
    try:
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            Capability,
            DelegationToken,
        )
    except Exception:
        pytest.skip("ucan_delegation unavailable")

    token = DelegationToken(
        issuer="did:key:root",
        audience="did:key:agent",
        capabilities=[Capability(resource="kg://acme/skills", ability="graph/list")],
        expiry=time.time() + 60,
        nonce="pc-1",
    )
    link = link_from_delegation_token(token)
    result = validate_delegation_chain(
        [link],
        resource="kg://acme/skills",
        ability="graph/list",
        invoker="did:key:agent",
    )
    assert result.allowed is True


# ---------------------------------------------------------------------------
# Errors and audit
# ---------------------------------------------------------------------------


def test_deny_reason_error_code_map():
    assert deny_reason_to_error_code("missing_principal") == "UNAUTHORIZED"
    assert deny_reason_to_error_code("empty_chain") == "UNAUTHORIZED"
    assert deny_reason_to_error_code("resource_not_contained") == "FORBIDDEN"
    assert deny_reason_to_error_code("revoked") == "FORBIDDEN"
    assert deny_reason_to_error_code("replay") == "FORBIDDEN"
    assert deny_reason_to_error_code("unknown_ability") == "INVALID_REQUEST"
    assert deny_reason_to_error_code("nonce_required") == "INVALID_REQUEST"


def test_redact_for_audit_and_receipt():
    event = {
        "principal": "did:key:agent",
        "resource": "kg://acme/skills",
        "ucan_token": "eyJhbGciOi...",
        "signature": "deadbeef",
        "nested": {"password": "s3cret", "ok": 1},
        "query_text": "MATCH (n) RETURN n",
        "rows": [["alice", 1]],
    }
    redacted = redact_for_audit(event)
    assert redacted["principal"] == "did:key:agent"
    assert redacted["ucan_token"] == "[REDACTED]"
    assert redacted["signature"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["ok"] == 1
    assert redacted["query_text"] == "[REDACTED]"
    assert redacted["rows"] == "[REDACTED]"

    now = time.time()
    link = _link(
        "did:key:root",
        "did:key:agent",
        [_cap("kg://acme/skills", "graph/read")],
        expiry=now + 100,
    )
    result = validate_delegation_chain(
        [link],
        resource="kg://acme/skills",
        ability="graph/read",
        invoker="did:key:agent",
        now=now,
    )
    receipt = build_authorization_receipt(
        result=result,
        resource="kg://acme/skills",
        ability="graph/read",
        principal="did:key:agent",
        request={"operation": "open", "ucan_token": "SECRET"},
        chain=[link],
    )
    assert isinstance(receipt, AuthorizationReceipt)
    assert receipt.decision == "allow"
    assert receipt.receipt_cid.startswith("sha256:")
    assert receipt.contract_version == CONTRACT_VERSION
    payload = receipt.to_json_dict()
    assert "SECRET" not in str(payload)
    assert payload["policy_digest"].startswith("sha256:")
    assert payload["request_digest"].startswith("sha256:")
    assert payload["chain_digest"].startswith("sha256:")

    deny = validate_delegation_chain(
        [link],
        resource="kg://acme/skills",
        ability="graph/admin",
        invoker="did:key:agent",
        now=now,
    )
    deny_receipt = build_authorization_receipt(
        result=deny,
        resource="kg://acme/skills",
        ability="graph/admin",
        principal="did:key:agent",
        chain=[link],
    )
    assert deny_receipt.decision == "deny"
    assert deny_receipt.error_code == "FORBIDDEN"


def test_content_digest_stable():
    d1 = content_digest({"a": 1, "b": 2})
    d2 = content_digest({"b": 2, "a": 1})
    assert d1 == d2
    assert d1.startswith("sha256:")
    assert content_digest({"a": 1}) != content_digest({"a": 2})


def test_graph_capability_from_mapping_and_link_json():
    cap = GraphCapability.from_mapping(
        {
            "resource": "kg://acme/skills",
            "ability": "graph/pin",
            "caveats": {"count": 2},
        }
    )
    assert cap.ability == "graph/pin"
    assert cap.caveats.count == 2
    link = _link("did:key:a", "did:key:b", [cap], cid="x")
    data = link.to_json_dict()
    assert data["capabilities"][0]["ability"] == "graph/pin"
    assert data["cid"] == "x"


def test_ucan_contract_error_json():
    err = UCANContractError(
        "resource_not_contained",
        "nope",
        details={"parent": "kg://a/b", "child": "kg://c/d"},
    )
    body = err.to_json_dict()
    assert body["error_code"] == "FORBIDDEN"
    assert body["reason"] == "resource_not_contained"
    assert body["details"]["parent"] == "kg://a/b"
