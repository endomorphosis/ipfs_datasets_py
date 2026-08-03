"""Integration tests: atomic canary rollback to verified immutable heads (KGP-033).

Acceptance:
  Roll back by atomically restoring the last verified immutable head. Never
  convert or delete legacy data in place. Shadow comparison and canary routing
  remain observable around rollback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Set

import pytest

from ipfs_datasets_py.knowledge_graphs.catalog import (
    CatalogError,
    bootstrap_revision_id,
    open_catalog,
)
from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    GraphCounts,
    ProvenanceDescriptor,
    build_graph_revision_manifest,
)
from ipfs_datasets_py.knowledge_graphs.migration.canary import (
    CanaryConfig,
    CanaryController,
    CanaryRoute,
    CanaryState,
    NoVerifiedHeadError,
    RollbackConflictError,
    RollbackReason,
    VerifiedHead,
    VerifiedHeadRegistry,
    capture_verified_head_from_catalog,
)
from ipfs_datasets_py.knowledge_graphs.migration.shadow import (
    ShadowConfig,
    ShadowReader,
    ShadowStopReason,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog(tmp_path: Path):
    path = tmp_path / "kg_rollback.sqlite"
    cat = open_catalog(path)
    yield cat
    cat.close()


def _provenance() -> ProvenanceDescriptor:
    return ProvenanceDescriptor(
        producer_id="kgp-033-rollback",
        producer_version="1.0.0",
        source="integration",
        created_at="2026-07-29T15:00:00Z",
    )


def _put_revision(
    catalog,
    tenant: str,
    graph_id: str,
    revision_id: str,
    *,
    parent: str,
    node_count: int = 1,
    edge_count: int = 0,
) -> Any:
    man = build_graph_revision_manifest(
        tenant=tenant,
        graph_id=graph_id,
        revision_id=revision_id,
        schema_id=f"{graph_id}-schema",
        schema_version="1",
        ontology_id=f"{graph_id}-onto",
        ontology_version="1",
        graph_kind="generic",
        storage_profile="parquet",
        codec="json",
        counts=GraphCounts(node_count=node_count, edge_count=edge_count),
        provenance=_provenance(),
        parent_revision=parent,
    )
    catalog.put_revision(
        tenant,
        graph_id,
        revision_id,
        parent_revision=parent,
        manifest_cid=man.root_cid,
        manifest_json=man.to_json(),
        pin_root=man.root_cid,
        checksum=man.checksum.hex_digest,
    )
    return man


def _seed_with_canary(
    catalog,
    tenant: str = "acme",
    graph_id: str = "orders",
    *,
    verified: str = "rev-verified",
    canary: str = "rev-canary",
) -> Dict[str, Any]:
    catalog.create_graph(tenant, graph_id, storage_profile="parquet")
    boot = bootstrap_revision_id(tenant, graph_id)
    v_man = _put_revision(
        catalog, tenant, graph_id, verified, parent=boot, node_count=5
    )
    catalog.cas_set_head(
        tenant,
        graph_id,
        "main",
        expected_revision=boot,
        new_revision=verified,
        pin_root=v_man.root_cid,
        idempotency_key=f"cas-{tenant}-{graph_id}-{verified}",
    )
    c_man = _put_revision(
        catalog, tenant, graph_id, canary, parent=verified, node_count=7
    )
    controller = CanaryController(
        catalog,
        config=CanaryConfig(allowlist=frozenset({(tenant, graph_id)})),
    )
    promo = controller.promote(tenant, graph_id, canary)
    assert promo.ok
    assert catalog.get_branch(tenant, graph_id, "main").head_revision == canary
    return {
        "tenant": tenant,
        "graph_id": graph_id,
        "boot": boot,
        "verified": verified,
        "canary": canary,
        "verified_manifest": v_man,
        "canary_manifest": c_man,
        "controller": controller,
    }


def _revision_ids(catalog, tenant: str, graph_id: str) -> Set[str]:
    return {r.revision_id for r in catalog.list_revisions(tenant, graph_id)}


# ---------------------------------------------------------------------------
# Atomic CAS rollback
# ---------------------------------------------------------------------------


def test_rollback_restores_last_verified_immutable_head(catalog):
    ctx = _seed_with_canary(catalog)
    controller: CanaryController = ctx["controller"]

    result = controller.rollback(
        ctx["tenant"],
        ctx["graph_id"],
        reason=RollbackReason.MANUAL,
    )
    assert result.ok is True
    assert result.from_revision == ctx["canary"]
    assert result.to_revision == ctx["verified"]
    assert result.reason is RollbackReason.MANUAL
    assert result.verified_head is not None
    assert result.verified_head.revision_id == ctx["verified"]

    branch = catalog.get_branch(ctx["tenant"], ctx["graph_id"], "main")
    assert branch.head_revision == ctx["verified"]

    # Canary disabled after rollback
    assert controller.state is CanaryState.STOPPED
    assert not controller.router.is_allowlisted(ctx["tenant"], ctx["graph_id"])

    val, route = controller.read(
        ctx["tenant"],
        ctx["graph_id"],
        baseline=lambda: "baseline",
        canary=lambda: "canary-should-not-run",
    )
    assert route is CanaryRoute.BASELINE
    assert val == "baseline"


def test_rollback_is_atomic_cas_not_data_mutation(catalog):
    ctx = _seed_with_canary(catalog)
    controller: CanaryController = ctx["controller"]

    before_revs = _revision_ids(catalog, ctx["tenant"], ctx["graph_id"])
    verified_before = catalog.get_revision(
        ctx["tenant"], ctx["graph_id"], ctx["verified"]
    )
    canary_before = catalog.get_revision(
        ctx["tenant"], ctx["graph_id"], ctx["canary"]
    )

    result = controller.rollback(ctx["tenant"], ctx["graph_id"])
    assert result.ok

    after_revs = _revision_ids(catalog, ctx["tenant"], ctx["graph_id"])
    # No revisions deleted
    assert before_revs == after_revs
    assert ctx["verified"] in after_revs
    assert ctx["canary"] in after_revs

    # Immutable content unchanged
    verified_after = catalog.get_revision(
        ctx["tenant"], ctx["graph_id"], ctx["verified"]
    )
    canary_after = catalog.get_revision(
        ctx["tenant"], ctx["graph_id"], ctx["canary"]
    )
    assert verified_after.checksum == verified_before.checksum
    assert verified_after.manifest_cid == verified_before.manifest_cid
    assert verified_after.manifest_json == verified_before.manifest_json
    assert canary_after.checksum == canary_before.checksum
    assert canary_after.pin_root == canary_before.pin_root


def test_rollback_idempotent_when_already_at_verified(catalog):
    ctx = _seed_with_canary(catalog)
    controller: CanaryController = ctx["controller"]

    first = controller.rollback(ctx["tenant"], ctx["graph_id"])
    assert first.ok
    assert first.to_revision == ctx["verified"]

    # Re-record allowlist and re-register verified head for second call path
    controller.allowlist_graph(ctx["tenant"], ctx["graph_id"])
    controller.router.resume()
    controller.record_verified_head(
        ctx["tenant"],
        ctx["graph_id"],
        ctx["verified"],
        source="reverify",
    )
    second = controller.rollback(ctx["tenant"], ctx["graph_id"])
    assert second.ok
    assert second.message == "already_at_verified_head"
    assert second.from_revision == ctx["verified"]
    assert second.to_revision == ctx["verified"]


def test_rollback_without_verified_head_raises(catalog):
    catalog.create_graph("acme", "lonely", storage_profile="parquet")
    boot = bootstrap_revision_id("acme", "lonely")
    man = _put_revision(catalog, "acme", "lonely", "rev-only", parent=boot)
    catalog.cas_set_head(
        "acme",
        "lonely",
        "main",
        expected_revision=boot,
        new_revision="rev-only",
        pin_root=man.root_cid,
        idempotency_key="cas-lonely",
    )
    controller = CanaryController(
        catalog,
        config=CanaryConfig(allowlist=frozenset({("acme", "lonely")})),
    )
    with pytest.raises(NoVerifiedHeadError):
        controller.rollback("acme", "lonely")


def test_capture_verified_head_from_catalog(catalog):
    catalog.create_graph("acme", "g", storage_profile="parquet")
    boot = bootstrap_revision_id("acme", "g")
    man = _put_revision(catalog, "acme", "g", "rev-head", parent=boot)
    catalog.cas_set_head(
        "acme",
        "g",
        "main",
        expected_revision=boot,
        new_revision="rev-head",
        pin_root=man.root_cid,
        idempotency_key="cas-g",
    )
    head = capture_verified_head_from_catalog(catalog, "acme", "g")
    assert head.revision_id == "rev-head"
    assert head.checksum == man.checksum.hex_digest
    assert head.pin_root == man.root_cid


def test_record_verified_head_rejects_unknown_revision(catalog):
    catalog.create_graph("acme", "g", storage_profile="parquet")
    controller = CanaryController(catalog)
    with pytest.raises(CatalogError) as exc:
        controller.record_verified_head("acme", "g", "rev-does-not-exist")
    assert exc.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Conflict handling
# ---------------------------------------------------------------------------


def test_rollback_cas_conflict_when_head_raced(catalog):
    ctx = _seed_with_canary(
        catalog, verified="rev-v", canary="rev-c"
    )
    controller: CanaryController = ctx["controller"]

    # Advance head out from under the controller's expected canary head.
    _put_revision(
        catalog,
        ctx["tenant"],
        ctx["graph_id"],
        "rev-racer",
        parent=ctx["canary"],
        node_count=9,
    )
    # Simulate external CAS that moves head away from canary without updating
    # the verified-head registry. We need expected=current canary.
    catalog.cas_set_head(
        ctx["tenant"],
        ctx["graph_id"],
        "main",
        expected_revision=ctx["canary"],
        new_revision="rev-racer",
        idempotency_key="race-cas",
    )
    # Move back to canary so controller sees from_rev != verified, then
    # race again mid-flight by monkeypatching get_branch... simpler path:
    # Force verified head target while current head is racer; CAS expects
    # from_rev=racer and should succeed actually. For conflict we need
    # concurrent change. Use a stub that changes head between read and CAS.

    original_get_branch = catalog.get_branch
    original_cas = catalog.cas_set_head
    calls = {"get": 0}

    def racing_get_branch(tenant, graph_id, branch, **kwargs):
        calls["get"] += 1
        br = original_get_branch(tenant, graph_id, branch, **kwargs)
        return br

    def racing_cas(tenant, graph_id, branch, **kwargs):
        # First CAS attempt: force conflict by claiming head moved.
        raise CatalogError(
            "CONFLICT",
            "branch head CAS conflict",
            details={
                "expected_revision": kwargs.get("expected_revision"),
                "current_revision": "rev-racer",
                "new_revision": kwargs.get("new_revision"),
            },
        )

    catalog.get_branch = racing_get_branch  # type: ignore[method-assign]
    catalog.cas_set_head = racing_cas  # type: ignore[method-assign]
    try:
        with pytest.raises(RollbackConflictError) as exc:
            controller.rollback(ctx["tenant"], ctx["graph_id"])
        assert exc.value.code == "ROLLBACK_CONFLICT"
    finally:
        catalog.get_branch = original_get_branch  # type: ignore[method-assign]
        catalog.cas_set_head = original_cas  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Automatic rollback from thresholds
# ---------------------------------------------------------------------------


def test_correctness_threshold_triggers_auto_rollback(catalog):
    ctx = _seed_with_canary(catalog)
    shadow = ShadowReader(
        ShadowConfig(
            max_absolute_mismatches=2,
            min_samples_for_rate=1000,
            max_mismatch_rate=1.0,
            security_stop_immediate=False,
        )
    )
    controller = CanaryController(
        catalog,
        config=CanaryConfig(
            allowlist=frozenset({(ctx["tenant"], ctx["graph_id"])}),
            auto_rollback_on_correctness=True,
            auto_disable_on_shadow_stop=True,
        ),
        shadow_reader=shadow,
        verified_heads=ctx["controller"].verified_heads,
    )
    # Re-sync allowlist after taking verified heads from prior controller
    controller.allowlist_graph(ctx["tenant"], ctx["graph_id"])
    assert catalog.get_branch(ctx["tenant"], ctx["graph_id"], "main").head_revision == ctx[
        "canary"
    ]

    for i in range(3):
        controller.shadow_compare(
            ctx["tenant"],
            ctx["graph_id"],
            baseline=lambda i=i: {"n": i},
            candidate=lambda i=i: {"n": i + 100},
        )

    assert shadow.is_stopped
    assert shadow.stop_reason is ShadowStopReason.ABSOLUTE_MISMATCHES
    branch = catalog.get_branch(ctx["tenant"], ctx["graph_id"], "main")
    assert branch.head_revision == ctx["verified"]
    history = controller.rollback_history()
    assert any(h.get("ok") and h.get("to_revision") == ctx["verified"] for h in history)


def test_rollback_all_graphs(catalog):
    a = _seed_with_canary(
        catalog, "acme", "orders", verified="rev-a-v", canary="rev-a-c"
    )
    b = _seed_with_canary(
        catalog, "acme", "invoices", verified="rev-b-v", canary="rev-b-c"
    )
    # Merge verified heads into one controller
    registry = VerifiedHeadRegistry()
    for ctx in (a, b):
        for head in ctx["controller"].verified_heads.list_heads():
            registry.put(head)
    controller = CanaryController(
        catalog,
        config=CanaryConfig(
            allowlist=frozenset(
                {("acme", "orders"), ("acme", "invoices")}
            )
        ),
        verified_heads=registry,
    )
    results = controller.rollback_all(reason=RollbackReason.OPERATOR)
    assert len(results) == 2
    assert all(r.ok for r in results)
    assert (
        catalog.get_branch("acme", "orders", "main").head_revision == "rev-a-v"
    )
    assert (
        catalog.get_branch("acme", "invoices", "main").head_revision == "rev-b-v"
    )


def test_metrics_snapshot_includes_rollback_evidence(catalog):
    ctx = _seed_with_canary(catalog)
    controller: CanaryController = ctx["controller"]
    controller.rollback(ctx["tenant"], ctx["graph_id"], reason=RollbackReason.OPERATOR)
    snap = controller.metrics_snapshot()
    assert snap["canary"]["rollbacks"] == 1
    assert snap["canary"]["last_rollback"]["ok"] is True
    assert snap["canary"]["last_rollback"]["to_revision"] == ctx["verified"]
    assert snap["state"] == CanaryState.STOPPED.value
    assert any(
        h["revision_id"] == ctx["verified"] for h in snap["verified_heads"]
    )


def test_promote_then_manual_rollback_preserves_both_revisions(catalog):
    """End-to-end: baseline → promote canary → rollback; both revs remain."""
    catalog.create_graph("tenant", "graph", storage_profile="parquet")
    boot = bootstrap_revision_id("tenant", "graph")
    v = _put_revision(catalog, "tenant", "graph", "v1", parent=boot, node_count=3)
    catalog.cas_set_head(
        "tenant",
        "graph",
        "main",
        expected_revision=boot,
        new_revision="v1",
        pin_root=v.root_cid,
        idempotency_key="to-v1",
    )
    c = _put_revision(catalog, "tenant", "graph", "v2-canary", parent="v1", node_count=4)

    controller = CanaryController(
        catalog,
        config=CanaryConfig(allowlist=frozenset({("tenant", "graph")})),
    )
    promo = controller.promote("tenant", "graph", "v2-canary")
    assert promo.ok
    assert promo.verified_head.revision_id == "v1"

    # Observe canary route while active
    val, route = controller.read(
        "tenant",
        "graph",
        baseline=lambda: "old",
        canary=lambda: "new",
    )
    assert route is CanaryRoute.CANARY
    assert val == "new"

    rb = controller.rollback("tenant", "graph", reason=RollbackReason.MANUAL)
    assert rb.ok
    assert rb.to_revision == "v1"
    assert catalog.get_branch("tenant", "graph", "main").head_revision == "v1"

    revs = _revision_ids(catalog, "tenant", "graph")
    assert "v1" in revs
    assert "v2-canary" in revs
    # Checksums stable
    assert catalog.get_revision("tenant", "graph", "v1").checksum == v.checksum.hex_digest
    assert (
        catalog.get_revision("tenant", "graph", "v2-canary").checksum
        == c.checksum.hex_digest
    )


def test_verified_head_to_dict_roundtrip():
    head = VerifiedHead(
        tenant="t",
        graph_id="g",
        branch="main",
        revision_id="r1",
        verified_at=42.0,
        checksum="deadbeef",
        pin_root="bafy",
        manifest_cid="bafy",
        source="test",
        metadata={"k": "v"},
    )
    restored = VerifiedHead.from_dict(head.to_dict())
    assert restored.tenant == "t"
    assert restored.revision_id == "r1"
    assert restored.checksum == "deadbeef"
    assert restored.metadata == {"k": "v"}


def test_rollback_reason_security_in_history(catalog):
    ctx = _seed_with_canary(catalog)
    controller: CanaryController = ctx["controller"]
    result = controller.rollback(
        ctx["tenant"],
        ctx["graph_id"],
        reason=RollbackReason.SECURITY,
    )
    assert result.ok
    assert result.reason is RollbackReason.SECURITY
    hist = controller.rollback_history()
    assert hist[-1]["reason"] == "security"


def test_no_legacy_data_conversion_apis_exist_on_controller(catalog):
    """Controller surface must not expose destructive conversion helpers."""
    controller = CanaryController(catalog)
    forbidden = [
        "convert_legacy",
        "delete_legacy",
        "destroy_revision",
        "drop_graph_data",
        "migrate_in_place",
    ]
    for name in forbidden:
        assert not hasattr(controller, name), f"unexpected API: {name}"
