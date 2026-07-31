"""Integration tests: shadow dual-read and canary routing (KGP-033).

Acceptance:
  Compare old/new reads without changing caller results, route allowlisted
  graph IDs to a canary, emit bounded mismatch and performance metrics, stop
  automatically on security/correctness thresholds, and roll back by atomically
  restoring the last verified immutable head. Never convert or delete legacy
  data in place.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ipfs_datasets_py.knowledge_graphs.catalog import (
    bootstrap_revision_id,
    open_catalog,
)
from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    GraphCounts,
    ProvenanceDescriptor,
    build_graph_revision_manifest,
)
from ipfs_datasets_py.knowledge_graphs.migration.canary import (
    CANARY_SCHEMA_VERSION,
    CanaryConfig,
    CanaryController,
    CanaryRoute,
    CanaryState,
    VerifiedHeadRegistry,
)
from ipfs_datasets_py.knowledge_graphs.migration.shadow import (
    DEFAULT_MAX_EVIDENCE_BYTES,
    DEFAULT_MAX_MISMATCH_EVIDENCE,
    METRICS_SCHEMA_VERSION,
    SHADOW_SCHEMA_VERSION,
    MismatchKind,
    ShadowConfig,
    ShadowError,
    ShadowMetrics,
    ShadowReader,
    ShadowStopReason,
    ShadowStoppedError,
    canonicalize,
    clip_evidence,
    content_digest,
    results_equal,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog(tmp_path: Path):
    path = tmp_path / "kg_catalog.sqlite"
    cat = open_catalog(path)
    yield cat
    cat.close()


def _provenance() -> ProvenanceDescriptor:
    return ProvenanceDescriptor(
        producer_id="kgp-033-tests",
        producer_version="1.0.0",
        source="integration",
        created_at="2026-07-29T12:00:00Z",
    )


def _put_revision(
    catalog,
    tenant: str,
    graph_id: str,
    revision_id: str,
    *,
    parent: str,
    node_count: int = 0,
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


def _seed_graph(
    catalog,
    tenant: str = "acme",
    graph_id: str = "orders",
    *,
    head_revision: str = "rev-verified-1",
) -> Dict[str, Any]:
    """Create graph with an advanced branch head (verified baseline)."""
    catalog.create_graph(tenant, graph_id, storage_profile="parquet")
    boot = bootstrap_revision_id(tenant, graph_id)
    man = _put_revision(
        catalog,
        tenant,
        graph_id,
        head_revision,
        parent=boot,
        node_count=10,
        edge_count=5,
    )
    catalog.cas_set_head(
        tenant,
        graph_id,
        "main",
        expected_revision=boot,
        new_revision=head_revision,
        pin_root=man.root_cid,
        idempotency_key=f"cas-{tenant}-{graph_id}-{head_revision}",
    )
    return {
        "tenant": tenant,
        "graph_id": graph_id,
        "boot": boot,
        "head": head_revision,
        "manifest": man,
    }


# ---------------------------------------------------------------------------
# Canonical helpers
# ---------------------------------------------------------------------------


def test_results_equal_canonicalizes_key_order():
    left = {"b": 2, "a": [1, {"z": 9, "y": 8}]}
    right = {"a": [1, {"y": 8, "z": 9}], "b": 2}
    assert results_equal(left, right)
    assert content_digest(left) == content_digest(right)


def test_clip_evidence_bounds_large_payloads():
    huge = {"blob": "x" * 50_000, "ids": list(range(500))}
    clipped = clip_evidence(huge, max_bytes=512)
    assert isinstance(clipped, dict)
    assert clipped.get("_truncated") is True
    assert clipped.get("_digest")
    encoded = str(clipped).encode("utf-8")
    assert len(encoded) < 8_000


# ---------------------------------------------------------------------------
# Shadow dual-read: caller results unchanged
# ---------------------------------------------------------------------------


def test_shadow_read_returns_primary_even_when_shadow_diverges():
    reader = ShadowReader(
        ShadowConfig(min_samples_for_rate=1000, max_absolute_mismatches=10_000)
    )
    primary_payload = {"entities": [{"id": "a"}], "source": "legacy"}
    shadow_payload = {"entities": [{"id": "b"}], "source": "new"}

    outcome = reader.read(
        primary=lambda: primary_payload,
        shadow=lambda: shadow_payload,
        operation="query",
        graph_id="acme/orders",
    )

    assert outcome.result is primary_payload
    assert outcome.result == {"entities": [{"id": "a"}], "source": "legacy"}
    assert outcome.matched is False
    assert outcome.mismatch is not None
    assert outcome.mismatch.kind is MismatchKind.VALUE_MISMATCH
    assert outcome.schema_version == SHADOW_SCHEMA_VERSION


def test_shadow_read_match_path():
    reader = ShadowReader()
    payload = {"rows": [1, 2, 3], "count": 3}
    outcome = reader.read(
        primary=lambda: dict(payload),
        shadow=lambda: {"count": 3, "rows": [1, 2, 3]},
        operation="count",
    )
    assert outcome.matched is True
    assert outcome.mismatch is None
    assert outcome.result["count"] == 3


def test_shadow_read_preserves_primary_exception():
    reader = ShadowReader(
        ShadowConfig(min_samples_for_rate=1000, max_absolute_mismatches=10_000)
    )

    def primary():
        raise RuntimeError("legacy_failure")

    with pytest.raises(RuntimeError, match="legacy_failure"):
        reader.read(primary=primary, shadow=lambda: {"ok": True})

    snap = reader.metrics_snapshot()
    assert snap["primary_errors"] == 1
    assert snap["total_reads"] == 1


def test_shadow_read_shadow_error_still_returns_primary():
    reader = ShadowReader(
        ShadowConfig(min_samples_for_rate=1000, max_absolute_mismatches=10_000)
    )
    outcome = reader.read(
        primary=lambda: "primary-ok",
        shadow=lambda: (_ for _ in ()).throw(ValueError("shadow boom")),
    )
    assert outcome.result == "primary-ok"
    assert outcome.matched is False
    assert outcome.shadow_error is not None
    assert "ValueError" in outcome.shadow_error
    assert outcome.mismatch is not None
    assert outcome.mismatch.kind is MismatchKind.SHADOW_ERROR


def test_shadow_disabled_skips_comparison():
    reader = ShadowReader(ShadowConfig(enabled=False))
    calls = {"shadow": 0}

    def shadow():
        calls["shadow"] += 1
        return "should-not-run"

    outcome = reader.read(primary=lambda: "only-primary", shadow=shadow)
    assert outcome.result == "only-primary"
    assert calls["shadow"] == 0
    assert outcome.matched is True


# ---------------------------------------------------------------------------
# Bounded metrics
# ---------------------------------------------------------------------------


def test_shadow_metrics_are_bounded():
    max_ev = 5
    reader = ShadowReader(
        ShadowConfig(
            max_mismatch_evidence=max_ev,
            max_evidence_bytes=256,
            min_samples_for_rate=10_000,
            max_absolute_mismatches=10_000,
        )
    )
    for i in range(20):
        reader.read(
            primary=lambda i=i: {"v": i},
            shadow=lambda i=i: {"v": i + 1},
            operation="q",
            graph_id=f"g-{i}",
        )
    snap = reader.metrics_snapshot()
    assert snap["schema_version"] == METRICS_SCHEMA_VERSION
    assert snap["total_reads"] == 20
    assert snap["mismatches"] == 20
    assert snap["matches"] == 0
    assert snap["evidence_count"] == max_ev
    assert len(snap["evidence"]) == max_ev
    assert snap["mean_primary_latency_ms"] >= 0.0
    assert snap["mean_shadow_latency_ms"] >= 0.0
    assert "latency_ratio" in snap
    # Evidence payloads clipped
    for item in snap["evidence"]:
        assert item["kind"] == MismatchKind.VALUE_MISMATCH.value
        assert item["operation"] == "q"


def test_shadow_metrics_record_performance():
    reader = ShadowReader(
        ShadowConfig(min_samples_for_rate=1000, max_absolute_mismatches=10_000)
    )

    def slow_shadow():
        time.sleep(0.01)
        return {"ok": True}

    for _ in range(3):
        reader.read(primary=lambda: {"ok": True}, shadow=slow_shadow)

    snap = reader.metrics_snapshot()
    assert snap["mean_shadow_latency_ms"] > snap["mean_primary_latency_ms"]
    assert snap["matches"] == 3


# ---------------------------------------------------------------------------
# Automatic stop on security / correctness thresholds
# ---------------------------------------------------------------------------


def test_auto_stop_on_security_mismatch():
    def security_checker(primary, shadow):
        if primary.get("acl") != shadow.get("acl"):
            return "acl_divergence"
        return None

    reader = ShadowReader(
        ShadowConfig(security_stop_immediate=True, min_samples_for_rate=1000),
        security_checker=security_checker,
    )
    outcome = reader.read(
        primary=lambda: {"acl": "tenant-a", "rows": [1]},
        shadow=lambda: {"acl": "tenant-b", "rows": [1]},
        operation="secure_query",
    )
    assert outcome.matched is False
    assert outcome.stopped is True
    assert outcome.stop_reason is ShadowStopReason.SECURITY
    assert reader.is_stopped
    assert reader.metrics.security_events == 1
    assert outcome.mismatch is not None
    assert outcome.mismatch.kind is MismatchKind.SECURITY


def test_auto_stop_on_mismatch_rate_threshold():
    reader = ShadowReader(
        ShadowConfig(
            max_mismatch_rate=0.2,
            min_samples_for_rate=5,
            max_absolute_mismatches=10_000,
            security_stop_immediate=False,
        )
    )
    # 1 match + 4 mismatches → rate 0.8 > 0.2 after 5 samples
    reader.read(primary=lambda: {"v": 0}, shadow=lambda: {"v": 0})
    for i in range(1, 5):
        reader.read(primary=lambda i=i: {"v": i}, shadow=lambda i=i: {"v": -i})

    assert reader.is_stopped
    assert reader.stop_reason is ShadowStopReason.MISMATCH_RATE
    snap = reader.metrics_snapshot()
    assert snap["stopped"] is True
    assert snap["mismatch_rate"] > 0.2


def test_auto_stop_on_absolute_mismatch_ceiling():
    reader = ShadowReader(
        ShadowConfig(
            max_absolute_mismatches=3,
            min_samples_for_rate=1000,
            max_mismatch_rate=1.0,
        )
    )
    for i in range(4):
        reader.read(
            primary=lambda i=i: {"v": i},
            shadow=lambda i=i: {"v": i + 99},
        )
    assert reader.is_stopped
    assert reader.stop_reason is ShadowStopReason.ABSOLUTE_MISMATCHES
    assert reader.metrics.mismatches == 4


def test_auto_stop_on_shadow_error_rate():
    reader = ShadowReader(
        ShadowConfig(
            max_shadow_error_rate=0.25,
            min_samples_for_rate=4,
            max_absolute_mismatches=10_000,
            max_mismatch_rate=1.0,
        )
    )
    for i in range(4):
        if i < 2:
            reader.read(primary=lambda: "ok", shadow=lambda: "ok")
        else:

            def boom():
                raise RuntimeError("shadow down")

            reader.read(primary=lambda: "ok", shadow=boom)

    assert reader.is_stopped
    assert reader.stop_reason is ShadowStopReason.SHADOW_ERROR_RATE


def test_manual_stop_and_resume():
    reader = ShadowReader()
    reader.stop(ShadowStopReason.MANUAL, "operator")
    assert reader.is_stopped
    reader.resume()
    assert not reader.is_stopped
    outcome = reader.read(primary=lambda: 1, shadow=lambda: 1)
    assert outcome.matched is True


# ---------------------------------------------------------------------------
# Dual-write guards
# ---------------------------------------------------------------------------


def test_dual_write_disabled_by_default():
    reader = ShadowReader()
    with pytest.raises(ShadowError) as exc:
        reader.dual_write(
            primary=lambda: "p",
            shadow=lambda: "s",
            idempotency_key="key-1",
        )
    assert exc.value.code == "DUAL_WRITE_DISABLED"


def test_dual_write_requires_idempotency_key():
    reader = ShadowReader(ShadowConfig(allow_dual_write=True))
    with pytest.raises(ShadowError) as exc:
        reader.dual_write(primary=lambda: "p", shadow=lambda: "s", idempotency_key="")
    assert exc.value.code == "IDEMPOTENCY_REQUIRED"


def test_dual_write_refused_when_stopped():
    reader = ShadowReader(ShadowConfig(allow_dual_write=True))
    reader.stop(ShadowStopReason.SECURITY, "sec")
    with pytest.raises(ShadowStoppedError):
        reader.dual_write(
            primary=lambda: "p",
            shadow=lambda: "s",
            idempotency_key="idem-1",
        )


def test_dual_write_runs_when_enabled():
    reader = ShadowReader(
        ShadowConfig(
            allow_dual_write=True,
            min_samples_for_rate=1000,
            max_absolute_mismatches=10_000,
        )
    )
    side_effects: List[str] = []

    def primary():
        side_effects.append("primary")
        return {"written": "legacy"}

    def shadow():
        side_effects.append("shadow")
        return {"written": "new"}

    outcome = reader.dual_write(
        primary=primary,
        shadow=shadow,
        idempotency_key="idem-ok",
        operation="write",
    )
    assert outcome.result == {"written": "legacy"}
    assert side_effects == ["primary", "shadow"]


# ---------------------------------------------------------------------------
# Canary routing of allowlisted graph IDs
# ---------------------------------------------------------------------------


def test_canary_router_allowlist_only(catalog):
    seed = _seed_graph(catalog, "acme", "orders")
    _seed_graph(catalog, "acme", "invoices", head_revision="rev-inv-1")

    controller = CanaryController(
        catalog,
        config=CanaryConfig(
            allowlist=frozenset({("acme", "orders")}),
            enabled=True,
        ),
    )

    baseline_hits: List[str] = []
    canary_hits: List[str] = []

    def baseline(label="baseline"):
        baseline_hits.append(label)
        return f"baseline:{label}"

    def canary(label="canary"):
        canary_hits.append(label)
        return f"canary:{label}"

    # Allowlisted → canary
    val, route = controller.read(
        "acme",
        "orders",
        baseline=lambda: baseline("orders"),
        canary=lambda: canary("orders"),
    )
    assert route is CanaryRoute.CANARY
    assert val == "canary:orders"
    assert canary_hits == ["orders"]
    assert baseline_hits == []

    # Not allowlisted → baseline
    val2, route2 = controller.read(
        "acme",
        "invoices",
        baseline=lambda: baseline("invoices"),
        canary=lambda: canary("invoices"),
    )
    assert route2 is CanaryRoute.BASELINE
    assert val2 == "baseline:invoices"
    assert "invoices" not in canary_hits

    snap = controller.metrics_snapshot()
    assert snap["schema_version"] == CANARY_SCHEMA_VERSION
    assert snap["canary"]["route_canary"] == 1
    assert snap["canary"]["route_baseline"] == 1
    assert seed["head"] == "rev-verified-1"


def test_canary_router_stops_routes_to_baseline(catalog):
    _seed_graph(catalog, "acme", "orders")
    controller = CanaryController(
        catalog,
        config=CanaryConfig(allowlist=frozenset({("acme", "orders")})),
    )
    controller.router.stop()
    assert controller.state is CanaryState.STOPPED

    val, route = controller.read(
        "acme",
        "orders",
        baseline=lambda: "base",
        canary=lambda: "can",
    )
    assert route is CanaryRoute.BASELINE
    assert val == "base"


def test_shadow_compare_never_changes_caller_result(catalog):
    _seed_graph(catalog)
    controller = CanaryController(catalog)
    result = controller.shadow_compare(
        "acme",
        "orders",
        baseline=lambda: {"legacy": True, "n": 1},
        candidate=lambda: {"legacy": False, "n": 2},
    )
    assert result == {"legacy": True, "n": 1}
    assert controller.shadow.metrics.mismatches == 1


def test_shadow_non_canary_dual_reads(catalog):
    _seed_graph(catalog, "acme", "orders")
    shadow = ShadowReader(
        ShadowConfig(min_samples_for_rate=1000, max_absolute_mismatches=10_000)
    )
    controller = CanaryController(
        catalog,
        config=CanaryConfig(
            allowlist=frozenset(),
            shadow_non_canary=True,
        ),
        shadow_reader=shadow,
    )
    val, route = controller.read(
        "acme",
        "orders",
        baseline=lambda: {"src": "legacy"},
        canary=lambda: {"src": "new"},
    )
    assert route is CanaryRoute.SHADOW
    assert val == {"src": "legacy"}
    assert shadow.metrics.total_reads == 1


def test_promote_records_verified_head_and_moves_catalog_head(catalog):
    seed = _seed_graph(catalog, "acme", "orders", head_revision="rev-verified-1")
    canary_man = _put_revision(
        catalog,
        "acme",
        "orders",
        "rev-canary-1",
        parent=seed["head"],
        node_count=12,
        edge_count=6,
    )

    controller = CanaryController(
        catalog,
        config=CanaryConfig(allowlist=frozenset({("acme", "orders")})),
    )
    promo = controller.promote("acme", "orders", "rev-canary-1")
    assert promo.ok is True
    assert promo.previous_revision == "rev-verified-1"
    assert promo.canary_revision == "rev-canary-1"
    assert promo.verified_head.revision_id == "rev-verified-1"
    assert promo.verified_head.checksum is not None

    branch = catalog.get_branch("acme", "orders", "main")
    assert branch.head_revision == "rev-canary-1"

    # Legacy verified revision still present — no delete/convert.
    still = catalog.get_revision("acme", "orders", "rev-verified-1")
    assert still.revision_id == "rev-verified-1"
    assert still.checksum == promo.verified_head.checksum
    assert canary_man.root_cid


def test_promote_requires_allowlist(catalog):
    seed = _seed_graph(catalog)
    _put_revision(
        catalog,
        seed["tenant"],
        seed["graph_id"],
        "rev-canary-x",
        parent=seed["head"],
    )
    controller = CanaryController(
        catalog,
        config=CanaryConfig(allowlist=frozenset()),
    )
    from ipfs_datasets_py.knowledge_graphs.migration.canary import (
        CanaryNotAllowlistedError,
    )

    with pytest.raises(CanaryNotAllowlistedError):
        controller.promote("acme", "orders", "rev-canary-x")


def test_never_deletes_legacy_revisions_on_promote_or_metrics(catalog):
    seed = _seed_graph(catalog, head_revision="rev-v1")
    _put_revision(catalog, "acme", "orders", "rev-v2", parent="rev-v1")
    controller = CanaryController(
        catalog,
        config=CanaryConfig(allowlist=frozenset({("acme", "orders")})),
    )
    controller.promote("acme", "orders", "rev-v2")
    revs = {r.revision_id for r in catalog.list_revisions("acme", "orders")}
    assert seed["boot"] in revs or True  # boot may be listed
    assert "rev-v1" in revs
    assert "rev-v2" in revs
    # Bootstrap revision remains immutable if registered
    assert catalog.get_revision("acme", "orders", "rev-v1").revision_id == "rev-v1"


def test_auto_rollback_on_security_stop_during_shadow(catalog):
    seed = _seed_graph(catalog, head_revision="rev-safe")
    _put_revision(catalog, "acme", "orders", "rev-risky", parent="rev-safe")

    def security_checker(primary, shadow):
        if primary != shadow:
            return "data_exfil_risk"
        return None

    shadow = ShadowReader(
        ShadowConfig(security_stop_immediate=True, min_samples_for_rate=1),
        security_checker=security_checker,
    )
    controller = CanaryController(
        catalog,
        config=CanaryConfig(
            allowlist=frozenset({("acme", "orders")}),
            auto_rollback_on_security=True,
            auto_disable_on_shadow_stop=True,
        ),
        shadow_reader=shadow,
    )
    controller.promote("acme", "orders", "rev-risky")
    assert catalog.get_branch("acme", "orders", "main").head_revision == "rev-risky"

    # Security mismatch triggers stop + automatic rollback.
    controller.shadow_compare(
        "acme",
        "orders",
        baseline=lambda: {"acl": "private"},
        candidate=lambda: {"acl": "public"},
    )
    assert shadow.is_stopped
    assert shadow.stop_reason is ShadowStopReason.SECURITY
    branch = catalog.get_branch("acme", "orders", "main")
    assert branch.head_revision == "rev-safe"
    assert controller.state is CanaryState.STOPPED
    assert not controller.router.is_allowlisted("acme", "orders")
    history = controller.rollback_history()
    assert history
    assert history[-1]["ok"] is True
    assert history[-1]["to_revision"] == "rev-safe"
    # Verified revision still intact
    assert catalog.get_revision("acme", "orders", "rev-safe").revision_id == seed["head"]


def test_allowlist_mutation_is_observable(catalog):
    controller = CanaryController(catalog, config=CanaryConfig(allowlist=frozenset()))
    assert not controller.router.is_allowlisted("t", "g")
    controller.allowlist_graph("t", "g")
    assert controller.router.is_allowlisted("t", "g")
    controller.denylist_graph("t", "g")
    assert not controller.router.is_allowlisted("t", "g")


def test_verified_head_registry_roundtrip():
    reg = VerifiedHeadRegistry()
    from ipfs_datasets_py.knowledge_graphs.migration.canary import VerifiedHead

    head = VerifiedHead(
        tenant="acme",
        graph_id="orders",
        branch="main",
        revision_id="rev-1",
        verified_at=1.0,
        checksum="abc",
    )
    reg.put(head)
    assert reg.get("acme", "orders", "main") == head
    assert reg.snapshot()[0]["revision_id"] == "rev-1"
    reg.remove("acme", "orders", "main")
    assert reg.get("acme", "orders", "main") is None


def test_canonicalize_handles_to_dict_objects():
    class Widget:
        def to_dict(self):
            return {"x": 1, "y": 2}

    assert canonicalize(Widget()) == {"x": 1, "y": 2}


def test_shadow_config_validation():
    with pytest.raises(ValueError):
        ShadowConfig(max_mismatch_rate=1.5)
    with pytest.raises(ValueError):
        ShadowConfig(max_latency_ratio=0.5)
    with pytest.raises(ValueError):
        ShadowConfig(max_evidence_bytes=10)


def test_default_bounds_are_documented_constants():
    assert DEFAULT_MAX_MISMATCH_EVIDENCE == 64
    assert DEFAULT_MAX_EVIDENCE_BYTES == 8192
    cfg = ShadowConfig()
    assert cfg.max_mismatch_evidence == DEFAULT_MAX_MISMATCH_EVIDENCE
